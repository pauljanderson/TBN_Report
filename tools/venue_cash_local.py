"""Shared local venue cash slip for live senders.

Paul: store the cash locally; each time a bet is made and confirmed, update
it; confirm from the venue once an hour. Shared by lock children and B/C/D/E
so they do not each GET the wallet.

File is under local raw (not Drive, not git). Amounts and timestamps only.
No secrets. Research live only. Not gold. Not DailyRun.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from prediction_paths import RAW_DIR as RAW

try:
    import venue_pace
except Exception:  # pragma: no cover
    venue_pace = None

VENUES = ("kalshi", "gemini", "polymarket", "novig")
CASH_FILE = RAW / "venue_cash_local.json"
_PROD_CASH = CASH_FILE
LEGACY_BALANCES = RAW / "balances.json"
DRIFT_LOG = RAW / "venue_cash_drift.jsonl"
CONFIRM_TTL_SEC = 3600.0
BACKOFF_SEC = {401: 300.0, 429: 60.0, 500: 30.0, 502: 30.0, 503: 30.0}
DEFAULT_BACKOFF_SEC = 60.0
_RECENT_IDS = 24
ET = ZoneInfo("America/New_York")


def reset_for_tests(path: Path | None = None) -> Path:
    """Tests only. Point the slip at a temp file."""
    global CASH_FILE
    if path is None:
        import tempfile

        path = Path(tempfile.mkdtemp()) / "venue_cash_local.json"
    CASH_FILE = path
    return path


def _is_prod() -> bool:
    try:
        return CASH_FILE.resolve() == _PROD_CASH.resolve()
    except OSError:
        return False


def _dec(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError, ArithmeticError):
        return None
    return number


def _iso_now() -> str:
    return datetime.now(ET).replace(microsecond=0).isoformat(timespec="seconds")


def _empty_row() -> dict:
    return {
        "cash": None,
        "last_venue_confirm_ts": 0.0,
        "last_local_debit_ts": 0.0,
        "last_order_id": "",
        "recent_order_ids": [],
        "last_confirm_http": 0,
        "backoff_until": 0.0,
        "last_drift": "",
    }


def _normalize_row(raw) -> dict:
    row = _empty_row()
    if not isinstance(raw, dict):
        return row
    cash = _dec(raw.get("cash"))
    row["cash"] = None if cash is None else format(cash, "f")
    try:
        row["last_venue_confirm_ts"] = float(raw.get("last_venue_confirm_ts") or 0)
    except (TypeError, ValueError):
        row["last_venue_confirm_ts"] = 0.0
    try:
        row["last_local_debit_ts"] = float(raw.get("last_local_debit_ts") or 0)
    except (TypeError, ValueError):
        row["last_local_debit_ts"] = 0.0
    row["last_order_id"] = str(raw.get("last_order_id") or "")
    ids = raw.get("recent_order_ids")
    if isinstance(ids, list):
        row["recent_order_ids"] = [str(item) for item in ids if item not in (None, "")][-_RECENT_IDS:]
    try:
        row["last_confirm_http"] = int(raw.get("last_confirm_http") or 0)
    except (TypeError, ValueError):
        row["last_confirm_http"] = 0
    try:
        row["backoff_until"] = float(raw.get("backoff_until") or 0)
    except (TypeError, ValueError):
        row["backoff_until"] = 0.0
    row["last_drift"] = str(raw.get("last_drift") or "")
    return row


def _blank_store() -> dict:
    return {
        "timestamp": _iso_now(),
        **{venue: None for venue in VENUES},
        "venues": {venue: _empty_row() for venue in VENUES},
    }


def _lock(path: Path):
    if venue_pace is None:
        return None
    try:
        return venue_pace.FileLock(path.with_suffix(path.suffix + ".lock"))
    except Exception:
        return None


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    last_err: OSError | None = None
    for attempt in range(6):
        try:
            tmp.replace(path)
            return
        except OSError as exc:
            last_err = exc
            time.sleep(0.05 * (attempt + 1))
    if last_err is not None:
        raise last_err


def _dump(store: dict) -> None:
    store = dict(store)
    store["timestamp"] = _iso_now()
    venues = store.get("venues") if isinstance(store.get("venues"), dict) else {}
    for venue in VENUES:
        row = _normalize_row(venues.get(venue))
        venues[venue] = row
        store[venue] = row.get("cash")
    store["venues"] = venues
    text = json.dumps(store, indent=2) + "\n"
    _atomic_write(CASH_FILE, text)
    if not _is_prod():
        return
    try:
        _atomic_write(LEGACY_BALANCES, json.dumps(
            {"timestamp": store["timestamp"], **{venue: store.get(venue) for venue in VENUES}},
            indent=2,
        ) + "\n")
    except OSError:
        pass


def _append_drift(row: dict) -> None:
    if not _is_prod():
        return
    try:
        RAW.mkdir(parents=True, exist_ok=True)
        line = json.dumps(row, default=str) + "\n"
        with DRIFT_LOG.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        return


def _seed_legacy_into(store: dict) -> dict:
    try:
        data = json.loads(LEGACY_BALANCES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return store
    if not isinstance(data, dict):
        return store
    stamp = str(data.get("timestamp") or "")
    epoch = 0.0
    if stamp:
        try:
            parsed = datetime.fromisoformat(stamp)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=ET)
            epoch = parsed.timestamp()
        except ValueError:
            epoch = 0.0
    venues = store.setdefault("venues", {})
    for venue in VENUES:
        if venue not in data:
            continue
        cash = _dec(data.get(venue))
        if cash is None:
            continue
        row = _normalize_row(venues.get(venue))
        if row.get("cash") not in (None, ""):
            continue
        row["cash"] = format(cash, "f")
        if epoch and not row.get("last_venue_confirm_ts"):
            row["last_venue_confirm_ts"] = epoch
        venues[venue] = row
        store[venue] = row["cash"]
    if stamp and not store.get("timestamp"):
        store["timestamp"] = stamp
    return store


def load_unlocked() -> dict:
    try:
        data = json.loads(CASH_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        data = None
    if not isinstance(data, dict):
        data = _blank_store()
        if _is_prod():
            data = _seed_legacy_into(data)
    venues = data.get("venues") if isinstance(data.get("venues"), dict) else {}
    data["venues"] = {venue: _normalize_row(venues.get(venue)) for venue in VENUES}
    for venue in VENUES:
        row = data["venues"][venue]
        if row.get("cash") in (None, "") and data.get(venue) not in (None, ""):
            cash = _dec(data.get(venue))
            if cash is not None:
                row["cash"] = format(cash, "f")
        data[venue] = row.get("cash")
    return data


def load() -> dict:
    lock = _lock(CASH_FILE)
    if lock is None:
        return load_unlocked()
    with lock:
        return load_unlocked()


def cash_of(store: dict | None, venue: str) -> Decimal | None:
    if not isinstance(store, dict):
        return None
    venues = store.get("venues") if isinstance(store.get("venues"), dict) else {}
    row = venues.get(venue) if isinstance(venues.get(venue), dict) else {}
    number = _dec(row.get("cash")) if row else None
    if number is None:
        number = _dec(store.get(venue))
    return number


def confirm_due(store: dict | None, venue: str, now: float | None = None) -> bool:
    """True when this process may GET the wallet. Shared across children."""
    now = time.time() if now is None else now
    if not isinstance(store, dict):
        return True
    venues = store.get("venues") if isinstance(store.get("venues"), dict) else {}
    row = venues.get(venue) if isinstance(venues.get(venue), dict) else _empty_row()
    try:
        backoff_until = float(row.get("backoff_until") or 0)
    except (TypeError, ValueError):
        backoff_until = 0.0
    if backoff_until > now:
        return False
    cash = cash_of(store, venue)
    try:
        confirmed = float(row.get("last_venue_confirm_ts") or 0)
    except (TypeError, ValueError):
        confirmed = 0.0
    if cash is None or confirmed <= 0:
        return True
    return (now - confirmed) >= CONFIRM_TTL_SEC


def _write_unlocked(store: dict) -> dict:
    _dump(store)
    return store


def apply_delta(venue: str, delta: Decimal, *, order_id: str = "", reason: str = "") -> Decimal | None:
    """Add delta to local cash. Negative = buy debit. Same order_id is a no-op."""
    venue = str(venue or "").strip().lower()
    if venue not in VENUES:
        return None
    try:
        change = Decimal(str(delta))
    except (InvalidOperation, ValueError, TypeError, ArithmeticError):
        return None
    if change == 0:
        return cash_of(load(), venue)
    oid = str(order_id or "").strip()

    def _apply(store: dict) -> Decimal | None:
        row = _normalize_row((store.get("venues") or {}).get(venue))
        ids = list(row.get("recent_order_ids") or [])
        if oid and (oid == row.get("last_order_id") or oid in ids):
            return cash_of(store, venue)
        current = cash_of(store, venue)
        if current is None:
            return None
        updated = current + change
        row["cash"] = format(updated, "f")
        row["last_local_debit_ts"] = time.time()
        if oid:
            row["last_order_id"] = oid
            ids.append(oid)
            row["recent_order_ids"] = ids[-_RECENT_IDS:]
        store.setdefault("venues", {})[venue] = row
        store[venue] = row["cash"]
        _write_unlocked(store)
        _append_drift({
            "at": _iso_now(),
            "venue": venue,
            "event": "debit" if change < 0 else "credit",
            "reason": str(reason or "")[:80],
            "order_id": oid,
            "delta": format(change, "f"),
            "cash": row["cash"],
        })
        return updated

    lock = _lock(CASH_FILE)
    if lock is None:
        return _apply(load_unlocked())
    with lock:
        return _apply(load_unlocked())


def confirm_from_venue(
    venue: str,
    fetch,
    *,
    force: bool = False,
    http_status: int | None = None,
) -> Decimal | None:
    """Overwrite local cash with venue truth at most once per hour.

    fetch() returns a Decimal or None. Optional http_status is used for backoff
    when fetch failed (429 keeps local cash; no extra GET).
    """
    venue = str(venue or "").strip().lower()
    if venue not in VENUES:
        return None

    def _run(store: dict) -> Decimal | None:
        now = time.time()
        if not force and not confirm_due(store, venue, now=now):
            return cash_of(store, venue)
        amount = None
        try:
            amount = fetch()
        except Exception:
            amount = None
        row = _normalize_row((store.get("venues") or {}).get(venue))
        if amount is not None:
            prior = cash_of(store, venue)
            drift = "" if prior is None else format(amount - prior, "f")
            row["cash"] = format(amount, "f")
            row["last_venue_confirm_ts"] = now
            row["last_confirm_http"] = 200 if http_status in (None, 0) else int(http_status)
            row["backoff_until"] = 0.0
            row["last_drift"] = drift
            store.setdefault("venues", {})[venue] = row
            store[venue] = row["cash"]
            _write_unlocked(store)
            _append_drift({
                "at": _iso_now(),
                "venue": venue,
                "event": "confirm",
                "http": row["last_confirm_http"],
                "drift": drift,
                "cash": row["cash"],
            })
            return amount
        status = 0 if http_status is None else int(http_status)
        wait = BACKOFF_SEC.get(status, DEFAULT_BACKOFF_SEC)
        row["last_confirm_http"] = status
        row["backoff_until"] = now + wait
        store.setdefault("venues", {})[venue] = row
        store[venue] = row.get("cash")
        _write_unlocked(store)
        _append_drift({
            "at": _iso_now(),
            "venue": venue,
            "event": "confirm_fail",
            "http": status,
        })
        return cash_of(store, venue)

    lock = _lock(CASH_FILE)
    if lock is None:
        return _run(load_unlocked())
    with lock:
        return _run(load_unlocked())


def ensure_cash(venue: str, fetch, *, force: bool = False) -> Decimal | None:
    """Local cash for a send. GET only when missing or the hourly confirm is due."""
    store = load()
    if not force and not confirm_due(store, venue):
        return cash_of(store, venue)
    return confirm_from_venue(venue, fetch, force=force)


def sync_memory(amounts: dict, confirm_at: dict | None = None) -> dict:
    """Write in-process dollars into the slip without treating it as a venue GET."""
    lock = _lock(CASH_FILE)
    confirm_at = confirm_at or {}

    def _run(store: dict) -> dict:
        venues = store.setdefault("venues", {})
        for venue in VENUES:
            if venue not in amounts:
                continue
            row = _normalize_row(venues.get(venue))
            number = amounts.get(venue)
            if number is None:
                row["cash"] = None
            else:
                cash = _dec(number)
                row["cash"] = None if cash is None else format(cash, "f")
            stamp = confirm_at.get(venue)
            if stamp:
                try:
                    row["last_venue_confirm_ts"] = float(stamp)
                except (TypeError, ValueError):
                    pass
            venues[venue] = row
            store[venue] = row.get("cash")
        _write_unlocked(store)
        return store

    if lock is None:
        return _run(load_unlocked())
    with lock:
        return _run(load_unlocked())
