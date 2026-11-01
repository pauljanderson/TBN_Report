"""Lock gap (A) sender. Separate Python from the merged poller and from B.

Reads per-game lock hints the poller wrote, then live_lock_orders.execute_locks.
Leftover watch lives here, not inside --poll-one and not inside the quote mux.
Does not open platform websockets. Does not start Tennis crossover (B).
"""
from __future__ import annotations

import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_game_pollers as lgp  # noqa: E402
import live_lock_orders  # noqa: E402
from prediction_paths import RAW_DIR as RAW  # noqa: E402

HINTS = RAW / "live_lock_hints"
PID_PATH = RAW / "live_lock_sender.pid"
SLEEP_SEC = 0.2


def run() -> None:
    me = os.getpid()
    lgp.write_json(PID_PATH, {"pid": me, "started_at": lgp.iso_now(), "role": "lock_sender"})
    lgp.log(f"lock sender start pid {me}")
    scan = lgp.load_scan()
    try:
        # Older leftover-IOC resume (may be absent after GTC adopt). Keep the
        # ensure_watch_ticker name for kitchen tests; GTC ticks run below.
        live_lock_orders.maybe_resume_one_leg_watch(lgp.log)
        live_lock_orders.ensure_watch_ticker(lgp.log)
    except Exception as exc:
        lgp.log(f"order watch resume {type(exc).__name__}")
    seen: dict[str, str] = {}
    while lgp.keep_running():
        try:
            try:
                live_lock_orders.tick_one_leg_gtc_watches(lgp.log)
            except Exception as exc:
                lgp.log(f"one-leg GTC watch tick {type(exc).__name__}")
            live = lgp.live_games(scan)
            live_keys = {row["key"] for row in live}
            by_key = {row["key"]: row for row in live}
            if HINTS.is_dir():
                for path in HINTS.glob("*.json"):
                    key = path.stem
                    if key not in live_keys:
                        continue
                    payload = lgp.read_json(path)
                    stamp = str(payload.get("written_at") or "")
                    if not stamp:
                        try:
                            stamp = str(path.stat().st_mtime)
                        except OSError:
                            continue
                    if seen.get(key) == stamp:
                        continue
                    seen[key] = stamp
                    spec = by_key.get(key) or {}
                    sport = payload.get("sport") or spec.get("sport") or ""
                    title = payload.get("title") or spec.get("title") or key
                    game = payload.get("game") if isinstance(payload.get("game"), dict) else spec.get("game") or {}
                    result = {"candidates": list(payload.get("candidates") or [])}
                    if not result["candidates"]:
                        continue
                    live_lock_orders.execute_locks(
                        scan, sport, title, game, result, [], lgp.log,
                    )
        except Exception as exc:
            lgp.log(f"lock sender loop {type(exc).__name__}")
        slept = 0.0
        while slept < SLEEP_SEC and lgp.keep_running():
            time.sleep(0.05)
            slept += 0.05
    lgp.log("lock sender exit")


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        try:
            lgp.log(f"lock sender crash {type(exc).__name__}: {exc}")
            lgp.log(traceback.format_exc().replace("\n", " | "))
        except Exception:
            pass
        raise
