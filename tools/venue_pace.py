"""Shared pace for ordinary HTTP reads. Not for a websocket book update.

Every scan process and every live-game poller waits on the same files
before a web read. Do not call wait_turn when applying a stream message
or when comparing prices that already arrived on a stream.

Gemini: about one request per second across all processes.
Kalshi: about two requests per second across all processes.
Polymarket US public reads: under the documented 20 requests per second
    per IP (public unauthenticated limit). The slot is 0.06 seconds.
Novig public catalog and book reads are unauthenticated and throttled per IP.
The slot is 0.50 seconds. A websocket book update does not wait on it.

In-flight cap (2026-10-28): at most this many processes may be inside
wait_turn for a platform at once. Extra background callers skip the tick
instead of joining a 80-helper convoy on the file lock. One seat is
reserved for send-path REST confirm (B 50-cross, T0 send, lock send,
dip GTC) so catalog / leftover / C-D-E walks cannot starve a now-or-never
send.

  gemini      cap 2   (~1 req/s at 1.05s; ~2s of queue; 1 send reserved)
  kalshi      cap 4   (~2 req/s at 0.50s; ~2s of queue; 1 send reserved)
  polymarket  cap 8   (~16 req/s at 0.06s; half-second of queue under 20/s)
  novig       cap 2   (0.50s slot; ~1s of queue; 1 send reserved)

No orders. No API keys. A process that sees HTTP 429 still backs off
inside its own request helper (2s, then 4s, then 8s).
"""
from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
from prediction_paths import RAW_DIR as RAW  # noqa: E402

ET = ZoneInfo("America/New_York")

# Seconds between reserved slots. 1.05 matches the scan's previous in-process gap.
INTERVAL = {
    "gemini": 1.05,
    "kalshi": 0.50,
    "polymarket": 0.06,
    "novig": 0.50,
}
IN_FLIGHT_CAP = {
    "gemini": 2,
    "kalshi": 4,
    "polymarket": 8,
    "novig": 2,
}
INFLIGHT_CAP = IN_FLIGHT_CAP
SEND_RESERVED = {
    "gemini": 1,
    "kalshi": 1,
    "polymarket": 1,
    "novig": 1,
}
PRIORITY_BACKGROUND = "background"
PRIORITY_SEND = "send"
SKIPPED = "http budget skip"
VENUES = ("kalshi", "gemini", "polymarket", "novig")
VENUE_LABELS = {
    "kalshi": "Kalshi",
    "gemini": "Gemini",
    "polymarket": "Polymarket US",
    "novig": "Novig",
}
HOLDERS_STALE_SEC = 30.0
BACKGROUND_LOCK_TIMEOUT_SEC = 0.15
SEND_RETRY_SLEEP_SEC = 0.05
EWMA_ALPHA = 0.2

_thread_guard = {name: threading.Lock() for name in INTERVAL}


class FileLock:
    """Exclusive lock that works across threads and processes."""

    def __init__(self, path: Path):
        self.path = path
        self._fh = None

    def acquire(self, timeout: float | None = None) -> float:
        """Block until locked. timeout=0 tries once. Returns wait milliseconds."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a+b")
        self._fh.seek(0, os.SEEK_END)
        if self._fh.tell() == 0:
            self._fh.write(b"\0")
            self._fh.flush()
        self._fh.seek(0)
        started = time.perf_counter()
        deadline = None if timeout is None else started + max(0.0, timeout)
        if os.name == "nt":
            import msvcrt
            while True:
                try:
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if deadline is not None and time.perf_counter() >= deadline:
                        self._close_unlocked()
                        raise TimeoutError("pace file lock timeout")
                    time.sleep(0.05)
        else:
            import fcntl
            while True:
                try:
                    flags = fcntl.LOCK_EX
                    if deadline is not None:
                        flags |= fcntl.LOCK_NB
                    fcntl.flock(self._fh.fileno(), flags)
                    break
                except OSError:
                    if deadline is not None and time.perf_counter() >= deadline:
                        self._close_unlocked()
                        raise TimeoutError("pace file lock timeout")
                    time.sleep(0.05)
        return (time.perf_counter() - started) * 1000.0

    def _close_unlocked(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None

    def release(self) -> None:
        if self._fh is None:
            return
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
            self._close_unlocked()

    def __enter__(self):
        self.acquire(timeout=None)
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False


def pid_alive(pid: int) -> bool:
    if not pid or int(pid) <= 0:
        return False
    if os.name == "nt":
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x1000, False, int(pid))
        if not handle:
            return False
        kernel.CloseHandle(handle)
        return True
    try:
        os.kill(int(pid), 0)
    except OSError:
        return False
    return True


def _iso_now() -> str:
    return datetime.now(ET).isoformat(timespec="seconds")


def _health_path(venue: str) -> Path:
    return RAW / f"pace_{venue}.health.json"


def _slot_path(venue: str) -> Path:
    return RAW / f"pace_{venue}.next"


def _lock_path(venue: str) -> Path:
    return RAW / f"pace_{venue}.lock"


def _is_send(priority) -> bool:
    if priority is True:
        return True
    if priority is False or priority is None:
        return False
    return str(priority) == PRIORITY_SEND


def background_limit(venue: str) -> int:
    return max(0, int(IN_FLIGHT_CAP[venue]) - int(SEND_RESERVED[venue]))


def is_send_priority(priority) -> bool:
    """True for send-path REST confirm. Accepts 'send' or bool True (sibling flag)."""
    if priority is True:
        return True
    if priority is False or priority is None:
        return False
    text = str(priority).strip().lower()
    return text in ("send", "priority", "1", "true")


def _empty_health(venue: str) -> dict:
    return {
        "venue": venue,
        "interval_s": INTERVAL.get(venue),
        "cap": IN_FLIGHT_CAP.get(venue),
        "reserved": SEND_RESERVED.get(venue),
        "background_limit": background_limit(venue) if venue in IN_FLIGHT_CAP else None,
        "in_flight": 0,
        "skipped_ticks": 0,
        "granted": 0,
        "send_granted": 0,
        "lock_wait_ms": 0.0,
        "lock_wait_ms_ewma": 0.0,
        "lock_wait_ms_max": 0.0,
        "updated": None,
        "holders": [],
        "nxt": 0.0,
        "send_nxt": 0.0,
    }


def _read_health(venue: str) -> dict:
    path = _health_path(venue)
    row = _empty_health(venue)
    if not path.is_file():
        return row
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return row
    if isinstance(data, dict):
        row.update(data)
    row["venue"] = venue
    row["interval_s"] = INTERVAL.get(venue)
    row["cap"] = IN_FLIGHT_CAP.get(venue)
    row["reserved"] = SEND_RESERVED.get(venue)
    row["background_limit"] = background_limit(venue) if venue in IN_FLIGHT_CAP else None
    return row


def _write_health(venue: str, row: dict) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    payload = dict(row)
    payload["venue"] = venue
    payload["updated"] = _iso_now()
    payload["in_flight"] = len(payload.get("holders") or [])
    text = json.dumps(payload, indent=2, default=str) + "\n"
    _health_path(venue).write_text(text, encoding="utf-8")
    try:
        combined = health_snapshot()
        (RAW / "venue_pace_health.json").write_text(
            json.dumps(combined, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass


def _read_slots(venue: str) -> tuple[float, float]:
    path = _slot_path(venue)
    nxt = 0.0
    send_nxt = 0.0
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return nxt, send_nxt
    if not text:
        return nxt, send_nxt
    try:
        if text.startswith("{"):
            blob = json.loads(text)
            nxt = float(blob.get("nxt") or 0)
            send_nxt = float(blob.get("send_nxt") or 0)
        else:
            nxt = float(text or "0")
    except (TypeError, ValueError, json.JSONDecodeError):
        nxt = 0.0
        send_nxt = 0.0
    return nxt, send_nxt


def _write_slots(venue: str, nxt: float, send_nxt: float) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    payload = {"nxt": round(float(nxt), 6), "send_nxt": round(float(send_nxt), 6)}
    _slot_path(venue).write_text(json.dumps(payload), encoding="utf-8")


def _prune_holders(holders: list) -> list:
    now = time.time()
    kept = []
    for item in holders or []:
        if not isinstance(item, dict):
            continue
        pid = int(item.get("pid") or 0)
        started = float(item.get("t") or 0)
        if started and (now - started) > HOLDERS_STALE_SEC:
            continue
        if pid and not pid_alive(pid):
            continue
        kept.append({"pid": pid, "t": started, "priority": str(item.get("priority") or PRIORITY_BACKGROUND)})
    return kept


def _note_lock_wait(row: dict, wait_ms: float) -> None:
    wait_ms = max(0.0, float(wait_ms))
    row["lock_wait_ms"] = round(wait_ms, 3)
    prev = float(row.get("lock_wait_ms_ewma") or 0)
    if prev <= 0:
        row["lock_wait_ms_ewma"] = round(wait_ms, 3)
    else:
        row["lock_wait_ms_ewma"] = round(EWMA_ALPHA * wait_ms + (1.0 - EWMA_ALPHA) * prev, 3)
    row["lock_wait_ms_max"] = round(max(float(row.get("lock_wait_ms_max") or 0), wait_ms), 3)


def _token() -> dict:
    return {"pid": os.getpid(), "t": time.time()}


def health_snapshot() -> dict:
    """Public counters for job_status. No secrets. No holder pids."""
    venues = {}
    latest = None
    for venue in VENUES:
        row = _read_health(venue)
        holders = _prune_holders(row.get("holders") or [])
        public = {
            "venue": venue,
            "label": VENUE_LABELS.get(venue, venue),
            "interval_s": INTERVAL[venue],
            "cap": IN_FLIGHT_CAP[venue],
            "reserved": SEND_RESERVED[venue],
            "background_limit": background_limit(venue),
            "in_flight": len(holders),
            "inflight_count": len(holders),
            "inflight_cap": IN_FLIGHT_CAP[venue],
            "skipped_ticks": int(row.get("skipped_ticks") or 0),
            "granted": int(row.get("granted") or 0),
            "send_granted": int(row.get("send_granted") or 0),
            "lock_wait_ms": float(row.get("lock_wait_ms") or 0),
            "lock_wait_ms_last": float(row.get("lock_wait_ms") or 0),
            "lock_wait_ms_ewma": float(row.get("lock_wait_ms_ewma") or 0),
            "lock_wait_ms_max": float(row.get("lock_wait_ms_max") or 0),
            "updated": row.get("updated"),
        }
        venues[venue] = public
        stamp = public.get("updated")
        if stamp and (latest is None or str(stamp) > str(latest)):
            latest = stamp
    return {"venues": venues, "updated": latest}


def reset_for_tests(raw: Path | None = None) -> None:
    """Tests only. Point pace files at a temp folder and drop in-memory guards."""
    global RAW
    if raw is not None:
        RAW = Path(raw)
    RAW.mkdir(parents=True, exist_ok=True)
    for venue in INTERVAL:
        for path in (_health_path(venue), _slot_path(venue), _lock_path(venue)):
            try:
                if path.is_file():
                    path.unlink()
            except OSError:
                pass


def _grant_locked(venue: str, priority: str, wait_ms: float) -> dict | None:
    """Under FileLock. Returns holder token if granted, None if background skipped."""
    is_send = is_send_priority(priority)
    row = _read_health(venue)
    holders = _prune_holders(row.get("holders") or [])
    cap = int(IN_FLIGHT_CAP[venue])
    limit = background_limit(venue)
    _note_lock_wait(row, wait_ms)
    if is_send:
        if len(holders) >= cap:
            _write_health(venue, {**row, "holders": holders})
            return None
    elif len(holders) >= limit:
        row["skipped_ticks"] = int(row.get("skipped_ticks") or 0) + 1
        row["holders"] = holders
        _write_health(venue, row)
        return None
    token = {**_token(), "priority": PRIORITY_SEND if is_send else PRIORITY_BACKGROUND}
    holders.append(token)
    interval = float(INTERVAL[venue])
    now = time.time()
    nxt, send_nxt = _read_slots(venue)
    if is_send:
        slot = max(now, send_nxt)
        send_nxt = slot + interval
        nxt = max(nxt, slot + interval)
        row["send_granted"] = int(row.get("send_granted") or 0) + 1
    else:
        slot = max(now, nxt)
        nxt = slot + interval
    row["granted"] = int(row.get("granted") or 0) + 1
    row["holders"] = holders
    _write_slots(venue, nxt, send_nxt)
    _write_health(venue, row)
    token["slot"] = slot
    return token


def _release_locked(venue: str, token: dict | None) -> None:
    row = _read_health(venue)
    holders = _prune_holders(row.get("holders") or [])
    pid = int((token or {}).get("pid") or 0)
    started = float((token or {}).get("t") or 0)
    kept = []
    dropped = False
    for item in holders:
        if not dropped and int(item.get("pid") or 0) == pid and abs(float(item.get("t") or 0) - started) < 1e-6:
            dropped = True
            continue
        kept.append(item)
    if not dropped and pid:
        kept = [item for item in kept if int(item.get("pid") or 0) != pid]
    row["holders"] = kept
    _write_health(venue, row)


def wait_turn(venue: str, *, priority: str = PRIORITY_BACKGROUND) -> bool:
    """Reserve the next slot for this venue.

    Returns True if the caller should HTTP. Background returns False when the
    in-flight cap (minus the send reserved seat) is full — that is a skipped
    tick. Send-path never skips; it waits for a seat, including the reserved
    one, and does not sit behind a pile of catalog/leftover/C-D-E reservations.

    The in-flight seat is held until this call returns (after the slot sleep).
    release_turn is optional and idempotent. Forgotten seats also expire after
    HOLDERS_STALE_SEC or a dead pid prune.
    """
    if venue not in INTERVAL:
        return True
    guard = _thread_guard[venue]
    is_send = is_send_priority(priority)
    lock_path = _lock_path(venue)
    token = None
    while True:
        lock = FileLock(lock_path)
        try:
            with guard:
                wait_ms = lock.acquire(timeout=None if is_send else BACKGROUND_LOCK_TIMEOUT_SEC)
                try:
                    token = _grant_locked(venue, priority, wait_ms)
                finally:
                    lock.release()
        except TimeoutError:
            if is_send:
                time.sleep(SEND_RETRY_SLEEP_SEC)
                continue
            try:
                with guard:
                    skip_lock = FileLock(lock_path)
                    wait_ms = skip_lock.acquire(timeout=BACKGROUND_LOCK_TIMEOUT_SEC)
                    try:
                        row = _read_health(venue)
                        holders = _prune_holders(row.get("holders") or [])
                        row["skipped_ticks"] = int(row.get("skipped_ticks") or 0) + 1
                        row["holders"] = holders
                        _note_lock_wait(row, wait_ms)
                        _write_health(venue, row)
                    finally:
                        skip_lock.release()
            except Exception:
                pass
            return False
        if token is not None:
            break
        if not is_send:
            return False
        time.sleep(SEND_RETRY_SLEEP_SEC)
    try:
        delay = float(token.get("slot") or 0) - time.time()
        if delay > 0:
            time.sleep(delay)
        return True
    finally:
        lock = FileLock(lock_path)
        with guard:
            try:
                lock.acquire(timeout=None)
                _release_locked(venue, token)
            finally:
                lock.release()


def release_turn(venue: str) -> None:
    """Drop this process's in-flight seat. Safe if wait_turn was skipped."""
    if venue not in INTERVAL:
        return
    guard = _thread_guard[venue]
    lock = FileLock(_lock_path(venue))
    with guard:
        try:
            lock.acquire(timeout=None)
            _release_locked(venue, {"pid": os.getpid()})
        except Exception:
            pass
        finally:
            lock.release()


@contextmanager
def paced(venue: str, *, priority: str = PRIORITY_BACKGROUND):
    """wait_turn + release_turn. Yields True when the caller should HTTP."""
    ok = False
    try:
        ok = wait_turn(venue, priority=priority)
        yield ok
    finally:
        if ok:
            release_turn(venue)


@contextmanager
def hold_inflight(venue: str, *, priority: str = PRIORITY_BACKGROUND):
    """Tests: occupy an in-flight seat without sleeping the HTTP interval."""
    interval = INTERVAL[venue]
    guard = _thread_guard[venue]
    lock = FileLock(_lock_path(venue))
    token = None
    with guard:
        wait_ms = lock.acquire(timeout=None)
        try:
            token = _grant_locked(venue, priority, wait_ms)
        finally:
            lock.release()
    try:
        yield token is not None
    finally:
        if token is not None:
            lock = FileLock(_lock_path(venue))
            with guard:
                try:
                    lock.acquire(timeout=None)
                    _release_locked(venue, token)
                finally:
                    lock.release()
    _ = interval


@contextmanager
def http_turn(venue: str, *, priority: str | bool = PRIORITY_BACKGROUND):
    """Grant a paced slot. Yields True if the caller should HTTP."""
    yield wait_turn(venue, priority=priority)
