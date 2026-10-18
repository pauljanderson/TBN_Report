"""Shared pace for ordinary HTTP reads. Not for a websocket book update.

Every scan process and every live-game poller waits on the same files
before a web read. Do not call wait_turn when applying a stream message
or when comparing prices that already arrived on a stream.

Gemini: about one request per second across all processes.
Kalshi: about two requests per second across all processes.
Polymarket US public reads: under the documented 20 requests per second
per IP (public unauthenticated limit). The slot is 0.06 seconds.

No orders. No API keys. A process that sees HTTP 429 still backs off
inside its own request helper (2s, then 4s, then 8s).
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAMP = ROOT / "drive" / "paul_experiments" / "prediction_market_arb_exhaustive_20261017"
RAW = STAMP / "raw"

# Seconds between reserved slots. 1.05 matches the scan's previous in-process gap.
INTERVAL = {
    "gemini": 1.05,
    "kalshi": 0.50,
    "polymarket": 0.06,
}
_thread_guard = {name: threading.Lock() for name in INTERVAL}


class FileLock:
    """Exclusive lock that works across threads and processes."""

    def __init__(self, path: Path):
        self.path = path
        self._fh = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a+b")
        self._fh.seek(0, os.SEEK_END)
        if self._fh.tell() == 0:
            self._fh.write(b"\0")
            self._fh.flush()
        self._fh.seek(0)
        if os.name == "nt":
            import msvcrt
            while True:
                try:
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.05)
        else:
            import fcntl
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if os.name == "nt":
                import msvcrt
                self._fh.seek(0)
                try:
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._fh.close()
            self._fh = None
        return False


def wait_turn(venue: str) -> None:
    """Reserve the next slot for this venue, then sleep until that slot."""
    interval = INTERVAL[venue]
    guard = _thread_guard[venue]
    data = RAW / f"pace_{venue}.next"
    lock_path = RAW / f"pace_{venue}.lock"
    with guard:
        with FileLock(lock_path):
            now = time.time()
            try:
                nxt = float(data.read_text(encoding="utf-8").strip() or "0")
            except (OSError, ValueError):
                nxt = 0.0
            slot = max(now, nxt)
            RAW.mkdir(parents=True, exist_ok=True)
            data.write_text(f"{slot + interval:.6f}", encoding="utf-8")
        delay = slot - time.time()
        if delay > 0:
            time.sleep(delay)
