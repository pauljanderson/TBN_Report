"""Background rewrite of orders_performance.html after a real venue fill or a closed trade.

Does not place, cancel, or sell. Does not print secrets. Does not start Strategy B.
Leftover watch (WATCH_TICK_SEC=1) and IOC send stay on the foreground; this module
only queues a daemon timer. Bursts of fills and closes coalesce into one generator
run (five systems settling the same second do not stampede; the last close still
lands). Phone ping is one ntfy per rewrite batch, and at most once per several minutes.

Closed trade = venue-confirmed settle / flatten close / void / final / expired.
Qty truth is fill-history. An empty Polymarket positions GET must not drop a
confirmed fill while the market is still OPEN. Settled / expired / final / void
never count as open.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import threading
import time
from decimal import Decimal
from pathlib import Path

from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW, ROOT
import win_hidden

PAGE = STAMP / "orders_performance.html"
GENERATOR = ROOT / "tools" / "write_orders_performance.py"
NTFY = ROOT / "tools" / "ntfy_job_done.py"
LOG = RAW / "live_supervisor.log"

DEBOUNCE_SEC = 4.0
NTFY_MIN_SEC = 180.0
REBUILD_TIMEOUT_SEC = 180.0

COMPLETE_KINDS = frozenset({
    "settled",
    "closed",
    "void",
    "resolved",
    "removed",
    "postponed",
    "completed",
    "absorbed",
    "flatten",
    "final",
    "expired",
    "finalized",
    "determined",
    "inactive",
})

_CLOSE_WHY_NEEDLES = (
    "settled/expired/final/void",
    "treated as settled",
    "settlementpx=",
    "result=yes",
    "result=no",
    "result=void",
)
_KEEP_OPEN_WHY_NEEDLES = (
    "positions list empty",
    "activities qty",
    "book unreadable",
    "no positions book; local confirm fill kept",
    "positions book may lag",
)

_lock = threading.Lock()
_timer: threading.Timer | None = None
_pending = False
_running = False
_pending_reasons: list[str] = []
_completed_keys: set[str] = set()
_last_ntfy_at = 0.0
_last_fingerprint = ""


def reset_for_tests() -> None:
    """Clear debounce/ntfy state. Tests only. Does not touch live jobs."""
    global _timer, _pending, _running, _last_ntfy_at, _last_fingerprint
    with _lock:
        if _timer is not None:
            try:
                _timer.cancel()
            except Exception:
                pass
            _timer = None
        _pending = False
        _running = False
        _pending_reasons.clear()
        _completed_keys.clear()
        _last_ntfy_at = 0.0
        _last_fingerprint = ""


def _dec(value) -> Decimal:
    try:
        return Decimal(str(value if value is not None else 0))
    except Exception:
        return Decimal("0")


def confirm_qty(payload) -> Decimal:
    """Venue-confirm qty when present; otherwise the order-tape fill qty. Unknown is 0."""
    try:
        import live_lock_orders
        return live_lock_orders.filled_contracts(payload) if payload is not None else Decimal("0")
    except Exception:
        return Decimal("0")


def should_rebuild_on_fill(
    payload=None,
    *,
    qty=None,
    status=None,
    skipped: bool = False,
    denied: bool = False,
) -> bool:
    """True when a venue ticket actually filled (qty > 0). False on deny/skip/empty 201."""
    if skipped or denied:
        return False
    try:
        code = int(status) if status is not None and str(status) not in {"", "pending"} else None
    except (TypeError, ValueError):
        code = None
    if code == 0 and payload is None and qty is None:
        return False
    if qty is None:
        qty = confirm_qty(payload)
    return _dec(qty) > 0


def should_rebuild_on_game_complete(kind: str, *, we_touched: bool = True) -> bool:
    """True when a game we already bought on settles, voids, completes, or leaves the books."""
    if not we_touched:
        return False
    return str(kind or "").strip().lower() in COMPLETE_KINDS


def watch_stop_is_game_complete(reason: str) -> bool:
    """Leftover-watch stop that means the market resolved. Miss / never-profitable is false."""
    text = str(reason or "").lower()
    if "market closed" in text or "resolved" in text or "settled" in text:
        return True
    if "void" in text:
        return True
    return False


def _norm(text: str) -> str:
    return " ".join(str(text or "").lower().replace("_", " ").replace("\t", " ").split())


def _names_hit(text: str, needles: list[str]) -> bool:
    blob = _norm(text)
    if not blob:
        return False
    return any(n in blob or blob in n for n in needles)


def b_match_touched(match: dict | None) -> bool:
    """True when Strategy B already has a real venue ticket on this match."""
    if not isinstance(match, dict):
        return False
    t0 = match.get("t0_yes") or {}
    if not isinstance(t0, dict):
        t0 = {}
    for which in ("a", "b"):
        row = t0.get(which) or {}
        if not isinstance(row, dict):
            continue
        if row.get("filled"):
            return True
        if _dec(row.get("fill_qty")) > 0:
            return True
    last = match.get("last_order") or {}
    if isinstance(last, dict) and _dec(last.get("fill_qty")) > 0:
        return True
    extra = match.get("cross_fill")
    if extra not in (None, "") and _dec(extra) > 0:
        return True
    return False


def game_was_touched(
    title: str = "",
    game_key: str = "",
    *,
    watches=None,
    matches=None,
    orders=None,
) -> bool:
    """True when we already have a real ticket on this game (watch, B, or tape fill)."""
    needles = [_norm(item) for item in (title, game_key) if _norm(item)]
    if not needles:
        return False
    watch_rows = watches
    if watch_rows is None:
        try:
            import live_lock_orders
            watch_rows = live_lock_orders.load_all_watches()
        except Exception:
            watch_rows = []
    for watch in watch_rows or []:
        if not isinstance(watch, dict):
            continue
        if not (_names_hit(watch.get("game") or "", needles) or _names_hit(watch.get("bet_key") or "", needles)):
            continue
        if str(watch.get("filled_venue") or "").strip() or str(watch.get("filled_instrument") or "").strip():
            return True
        if _dec(watch.get("fill_px")) > 0:
            return True
    match_rows = matches
    if match_rows is None:
        try:
            import live_strategy_b
            match_rows = (live_strategy_b.load_status() or {}).get("matches") or []
        except Exception:
            match_rows = []
    for match in match_rows or []:
        if not isinstance(match, dict):
            continue
        if not (_names_hit(match.get("game") or "", needles) or _names_hit(match.get("key") or "", needles)):
            continue
        if b_match_touched(match):
            return True
    tape = orders
    if tape is None:
        try:
            import live_lock_orders
            tape = live_lock_orders._read_orders()[-400:]
        except Exception:
            tape = []
    for row in tape or []:
        if not isinstance(row, dict):
            continue
        if not (_names_hit(row.get("game") or "", needles) or _names_hit(row.get("bet_key") or "", needles)):
            continue
        event = str(row.get("event") or "")
        if event in {"filled", "one_leg", "flatten_filled", "flatten_miss"}:
            return True
        if _dec(row.get("confirm_qty")) > 0:
            return True
    return False


def maybe_after_order(payload=None, status=None, *, skipped: bool = False, denied: bool = False) -> bool:
    """Schedule a rebuild when venue-confirm qty > 0. Never raises. Never blocks."""
    if not should_rebuild_on_fill(
        payload, status=status, skipped=skipped, denied=denied,
    ):
        return False
    return schedule_rebuild("fill")


def maybe_after_game_complete(
    kind: str,
    *,
    game_key: str = "",
    title: str = "",
    we_touched=None,
) -> bool:
    """Schedule when a touched game settles / completes / voids / leaves the books."""
    touched = we_touched
    if touched is None:
        touched = game_was_touched(title=title, game_key=game_key)
    if not should_rebuild_on_game_complete(kind, we_touched=bool(touched)):
        return False
    token = _norm(game_key or title or kind)
    with _lock:
        if token and token in _completed_keys:
            return False
        if token:
            _completed_keys.add(token)
    try:
        import settled_pnl_store

        settled_pnl_store.note_game_settled(
            kind=str(kind or ""),
            title=str(title or ""),
            game_key=str(game_key or ""),
        )
    except Exception:
        pass
    return schedule_rebuild(f"game_complete:{kind}")


def maybe_after_watch_stop(reason: str, watch: dict | None = None) -> bool:
    """Leftover watch stopped because the market resolved. Not a miss."""
    if not watch_stop_is_game_complete(reason):
        return False
    row = watch if isinstance(watch, dict) else {}
    return maybe_after_game_complete(
        "closed",
        game_key=str(row.get("bet_key") or ""),
        title=str(row.get("game") or ""),
        we_touched=True,
    )


def maybe_after_b_stage(match: dict | None, prev: str, now_stage: str) -> bool:
    """Strategy B left an open stage for done / absorbed / postponed / abandoned-with-fills."""
    now_stage = str(now_stage or "").strip().lower()
    prev = str(prev or "").strip().lower()
    if now_stage == prev:
        return False
    kind = {
        "done": "completed",
        "absorbed": "absorbed",
        "abandoned": "removed",
        "postponed": "postponed",
        "settled": "settled",
    }.get(now_stage)
    if kind is None:
        return False
    row = match if isinstance(match, dict) else {}
    if not b_match_touched(row):
        return False
    return maybe_after_game_complete(
        kind,
        game_key=str(row.get("key") or row.get("game") or ""),
        title=str(row.get("game") or ""),
        we_touched=True,
    )


def maybe_after_flatten(title: str = "", game_key: str = "", *, filled: bool = False) -> bool:
    """Flatten of a leftover is a closed trade when the opposite fill landed."""
    if not filled:
        return False
    return maybe_after_game_complete(
        "flatten",
        game_key=game_key,
        title=title,
        we_touched=True,
    )


def classified_is_venue_close(item: dict | None, snapshot=None) -> bool:
    """True on settle / expired / final / void. False on empty Poly GET while OPEN."""
    if not isinstance(item, dict):
        return False
    if item.get("real"):
        return False
    why = str(item.get("why") or "").lower()
    if any(needle in why for needle in _KEEP_OPEN_WHY_NEEDLES):
        return False
    live = item.get("row") if isinstance(item.get("row"), dict) else {}
    touched = False
    try:
        import open_count_sync
        t0 = live.get("t0_yes") if isinstance(live.get("t0_yes"), dict) else {}
        last = live.get("last_order") if isinstance(live.get("last_order"), dict) else {}
        evidence = open_count_sync.fill_evidence(live, open_count_sync._qty(last.get("fill_qty")), t0)
        touched = evidence > 0 or b_match_touched(live)
        insts = open_count_sync.instruments_from_row(live)
        if snapshot is not None and insts:
            closed, _closed_why = open_count_sync.instruments_are_final(snapshot, insts)
            if closed and touched:
                return True
    except Exception:
        last = live.get("last_order") if isinstance(live.get("last_order"), dict) else {}
        touched = _dec(last.get("fill_qty") or last.get("confirm_qty")) > 0 or b_match_touched(live)
    if not touched:
        return False
    if any(needle in why for needle in _CLOSE_WHY_NEEDLES):
        return True
    return False


def maybe_after_classified(item: dict | None, snapshot=None) -> bool:
    """Schedule when classify_match says this holding settled / expired / voided / finalized."""
    if not classified_is_venue_close(item, snapshot=snapshot):
        return False
    row = item.get("row") if isinstance(item, dict) and isinstance(item.get("row"), dict) else {}
    why = str((item or {}).get("why") or "settled")
    kind = "settled"
    low = why.lower()
    if "void" in low:
        kind = "void"
    elif "expired" in low:
        kind = "expired"
    elif "final" in low:
        kind = "final"
    return maybe_after_game_complete(
        kind,
        game_key=str((item or {}).get("key") or row.get("key") or ""),
        title=str((item or {}).get("game") or row.get("game") or ""),
        we_touched=True,
    )


def note_snapshot_closes(snapshot=None, *, watches=None, tape=None) -> int:
    """Scan B/C/D/E + lock leftover watches for venue-final closes. Does not mutate. Does not sell.

    Job-status (reloaded about once a minute) and live ticks both call this. Debounce
    plus _completed_keys keep five systems closing the same second to one rewrite.
    """
    try:
        import open_count_sync
    except Exception:
        return 0
    snap = snapshot
    if snap is None:
        try:
            snap = open_count_sync._read_cache()
        except Exception:
            return 0
    if not isinstance(snap, dict) or not snap:
        return 0
    n = 0
    watch_map = watches if isinstance(watches, dict) else None
    for sid in ("tennis_crossover", "cfb_favorite", "spread_t0", "tennis_t0_dog"):
        status = None
        if watch_map is not None:
            status = watch_map.get(sid)
        if not isinstance(status, dict):
            try:
                status = open_count_sync.load_watch(sid)
            except Exception:
                status = {}
        if not isinstance(status, dict):
            continue
        try:
            classified = open_count_sync.classify_system(sid, status, snap, tape=tape)
        except Exception:
            continue
        for item in classified:
            if maybe_after_classified(item, snapshot=snap):
                n += 1
    try:
        import live_lock_orders
        for watch in live_lock_orders.load_all_watches() or []:
            if not isinstance(watch, dict):
                continue
            if watch.get("stopped"):
                continue
            venue = str(watch.get("filled_venue") or "").lower()
            ident = str(watch.get("filled_instrument") or "").strip()
            if not venue or not ident:
                continue
            closed, why = open_count_sync.instruments_are_final(snap, [(venue, ident)])
            if not closed:
                continue
            if maybe_after_game_complete(
                "settled",
                game_key=str(watch.get("bet_key") or ""),
                title=str(watch.get("game") or ""),
                we_touched=True,
            ):
                n += 1
            _ = why
    except Exception:
        pass
    return n


def schedule_rebuild(reason: str) -> bool:
    """Debounce then rewrite in a daemon thread. Returns True if a rewrite is queued."""
    global _timer, _pending
    text = str(reason or "refresh")
    with _lock:
        _pending = True
        _pending_reasons.append(text)
        if _timer is not None:
            try:
                _timer.cancel()
            except Exception:
                pass
        _timer = threading.Timer(float(DEBOUNCE_SEC), _kick)
        _timer.daemon = True
        _timer.name = "orders-perf-refresh"
        _timer.start()
    return True


def flush_for_test() -> None:
    """Run the pending rewrite now. Tests only."""
    global _timer, _pending
    with _lock:
        if _timer is not None:
            try:
                _timer.cancel()
            except Exception:
                pass
            _timer = None
        pending = _pending
        _pending = False
    if pending:
        _run_once()


def _kick() -> None:
    global _running, _pending, _timer
    with _lock:
        _timer = None
        if _running:
            _pending = True
            return
        if not _pending:
            return
        _pending = False
        _running = True
    try:
        _run_once()
    finally:
        again = False
        with _lock:
            _running = False
            if _pending:
                again = True
        if again:
            schedule_rebuild("coalesce")


def _run_once() -> None:
    with _lock:
        _pending_reasons.clear()
    before = _fingerprint(PAGE)
    try:
        path = run_rebuild()
    except Exception as exc:
        _log(f"orders performance rebuild {type(exc).__name__}")
        return
    if not path:
        return
    after = _fingerprint(PAGE)
    changed = after != before and after != ""
    if changed:
        _maybe_ntfy()


def run_rebuild() -> str:
    """Subprocess the generator. Tests replace this. Live path must not import the generator here."""
    return _spawn_generator()


def _spawn_generator() -> str:
    if not GENERATOR.is_file():
        _log("orders performance generator missing")
        return ""
    try:
        proc = win_hidden.run(
            [sys.executable, "-u", str(GENERATOR)],
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=float(REBUILD_TIMEOUT_SEC),
            check=False,
        )
    except Exception as exc:
        _log(f"orders performance rebuild spawn {type(exc).__name__}")
        return ""
    code = getattr(proc, "returncode", 1)
    try:
        code = int(code)
    except (TypeError, ValueError):
        code = 1
    if code != 0:
        _log(f"orders performance rebuild exit {code}")
        return ""
    _log(f"orders performance rebuilt {PAGE.name}")
    return str(PAGE)


def _fingerprint(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _maybe_ntfy() -> None:
    """One phone ping per rebuild batch. Skip if we pinged recently."""
    global _last_ntfy_at, _last_fingerprint
    now = time.time()
    with _lock:
        if _last_ntfy_at and (now - _last_ntfy_at) < float(NTFY_MIN_SEC):
            return
        _last_ntfy_at = now
        _last_fingerprint = _fingerprint(PAGE)
    _phone_ntfy()


def _phone_ntfy() -> None:
    """Detached ntfy. Does not wait. Drive path routes to Paul's topic."""
    if not NTFY.is_file():
        return
    try:
        win_hidden.popen(
            [
                sys.executable, "-u", str(NTFY),
                "--path", str(PAGE),
                "-t", "Orders performance updated",
                "-m", "orders_performance.html rebuilt after a venue fill or a closed trade.",
            ],
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            new_group=True,
        )
    except Exception:
        pass


def _log(message: str) -> None:
    try:
        RAW.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(message.rstrip() + "\n")
    except Exception:
        pass
