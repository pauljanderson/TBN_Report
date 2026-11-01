"""Persistent tennis moneyline snapshots at T-2h and T0.

Research only. Writes raw/odds_snapshots.jsonl. Does not place, cancel, or
amend orders. Does not print secrets. Does not touch orders_stopped.json or
one_leg_watch.json. Fail-soft: a bad quote or missing start skips that row.
"""
from __future__ import annotations

import csv
import json
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import venue_pace
from odds_cross_winrate_20261020 import as_float, game_norm, parse_dt
from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW
from price_memory import LAST, load_last, parse_time, to_et
SNAPSHOTS = RAW / "odds_snapshots.jsonl"
PENDING = RAW / "odds_snapshot_pending.json"
REBUILD_STAMP = RAW / "odds_snapshots_rebuild.json"
SEED_CSV = RAW / "tennis_decade_at_start_20261020.csv"
LOCK = RAW / "odds_snapshots.lock"
ET = ZoneInfo("America/New_York")
VENUES = ("Polymarket", "Kalshi", "Gemini", "Novig")
SNAP_T2 = "tminus2h"
SNAP_T0 = "t0"
GRACE_MIN = 30
REBUILD_EVERY_SEC = 15 * 60
T2_HOURS = 2.0

_rebuild_thread: threading.Thread | None = None
_rebuild_lock = threading.Lock()


def now_et() -> datetime:
    return datetime.now(ET)


def iso_now() -> str:
    return now_et().isoformat()


def _log(log, msg: str) -> None:
    if log is None:
        return
    try:
        log(msg)
    except Exception:
        pass


def identity(sport: str, game: str, player: str, venue: str, snapshot: str) -> str:
    return "|".join(
        [
            (sport or "tennis").lower(),
            game_norm(game),
            game_norm(player),
            str(venue or ""),
            str(snapshot or ""),
        ]
    )


def is_clocked(text) -> bool:
    raw = str(text or "").strip()
    if not raw or len(raw) <= 10:
        return False
    return parse_dt(raw) is not None


def _load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_snapshot_rows() -> list[dict]:
    if not SNAPSHOTS.is_file():
        return []
    rows = []
    try:
        with SNAPSHOTS.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict):
                    rows.append(rec)
    except OSError:
        return []
    return rows


def latest_by_identity(rows: list[dict] | None = None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in rows if rows is not None else load_snapshot_rows():
        key = row.get("key") or identity(
            row.get("sport") or "tennis",
            row.get("game") or "",
            row.get("player") or "",
            row.get("venue") or "",
            row.get("snapshot") or "",
        )
        out[key] = row
    return out


def _append_rows(rows: list[dict]) -> int:
    if not rows:
        return 0
    RAW.mkdir(parents=True, exist_ok=True)
    with venue_pace.FileLock(LOCK):
        with SNAPSHOTS.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    return len(rows)


def _write_pending(pending: dict) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    tmp = PENDING.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(pending, indent=2, default=str), encoding="utf-8")
    tmp.replace(PENDING)


def seed_from_csv() -> int:
    """Copy already-computed T0 / T-2h / T-24h rows into the growing log once."""
    if not SEED_CSV.is_file():
        return 0
    written = []
    with SEED_CSV.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for rec in reader:
            label = str(rec.get("snapshot") or "")
            snapshot = {"t0": SNAP_T0, "t2": SNAP_T2, "t24": "tminus24h"}.get(label)
            if not snapshot:
                continue
            price = as_float(rec.get("price"))
            if price is None:
                continue
            game = rec.get("game") or ""
            player = rec.get("side") or ""
            venue = rec.get("venue") or ""
            row = {
                "at": rec.get("seen_at") or "",
                "sport": "tennis",
                "game": game,
                "player": player,
                "venue": venue,
                "yes_price": price,
                "opponent_yes": None,
                "start": rec.get("game_start") or "",
                "snapshot": snapshot,
                "source": rec.get("price_src") or "seed",
                "start_source": rec.get("start_source") or "",
                "settlement": rec.get("official") or "",
                "settlement_source": rec.get("official_source") or "",
                "pair_sum": rec.get("pair_sum"),
                "key": identity("tennis", game, player, venue, snapshot),
                "written_at": iso_now(),
                "seed": True,
            }
            written.append(row)
    if not written:
        return 0
    RAW.mkdir(parents=True, exist_ok=True)
    with venue_pace.FileLock(LOCK):
        if SNAPSHOTS.is_file() and SNAPSHOTS.stat().st_size > 0:
            return 0
        with SNAPSHOTS.open("a", encoding="utf-8") as handle:
            for row in written:
                handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    return len(written)


def _match_starts() -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        import polymarket_us_live
        matches = polymarket_us_live.load_tennis_matches()
        clocked = 0
        for match in (matches or [])[:12]:
            if polymarket_us_live.match_listed_start(match) is not None:
                clocked += 1
        if (matches or []) and clocked == 0:
            matches = polymarket_us_live.load_tennis_matches(force=True)
    except Exception:
        matches = []
    for match in matches or []:
        start = ""
        try:
            import polymarket_us_live
            dt = polymarket_us_live.match_listed_start(match)
            if dt is not None:
                start = to_et(dt).isoformat()
        except Exception:
            start = ""
        if not start:
            for key in ("startTime", "gameStartTime", "occurrence_datetime", "start", "listed_start"):
                raw = match.get(key) or ""
                if is_clocked(raw):
                    start = str(raw)
                    break
        if not start:
            continue
        titles = [
            match.get("title") or "",
            match.get("event_title") or "",
            f"{match.get('long_name') or ''} vs {match.get('short_name') or ''}",
        ]
        for title in titles:
            g = game_norm(title)
            if g:
                out.setdefault(g, start)
    return out


def _tennis_yes(last: dict) -> list[dict]:
    rows = []
    for key, rec in last.items():
        if not isinstance(rec, dict):
            continue
        if str(rec.get("sport") or "").lower() != "tennis":
            continue
        if str(rec.get("market_type") or "moneyline") not in ("moneyline", ""):
            continue
        if str(rec.get("pay") or "yes").lower() != "yes":
            continue
        venue = str(rec.get("venue") or "")
        if venue not in VENUES:
            continue
        price = as_float(rec.get("price"))
        if price is None or price <= 0.0 or price >= 1.0:
            continue
        game = rec.get("game") or ""
        player = rec.get("side") or rec.get("side_label") or ""
        if not game or not player:
            continue
        rows.append(
            {
                "mem_key": key,
                "game": game,
                "player": player,
                "venue": venue,
                "yes_price": price,
                "seen_at": rec.get("seen_at") or "",
                "game_start": rec.get("game_start") or "",
            }
        )
    return rows


def _prefer_start(*candidates: str) -> str:
    for raw in candidates:
        if is_clocked(raw):
            return str(raw)
    return ""


def _update_candidate(slot: dict, seen_at: str, price: float) -> None:
    prev_seen = slot.get("at") or ""
    if not prev_seen or seen_at >= prev_seen:
        slot["at"] = seen_at
        slot["yes_price"] = price


def _freeze_ok(now: datetime, start_dt: datetime, snapshot: str) -> bool:
    if snapshot == SNAP_T2:
        return now >= start_dt - timedelta(hours=T2_HOURS)
    if snapshot == SNAP_T0:
        return now >= start_dt
    return False


def _quote_ok(seen_at: str, start_dt: datetime, snapshot: str) -> bool:
    seen = parse_dt(seen_at)
    if seen is None:
        return False
    seen = to_et(seen)
    if snapshot == SNAP_T2:
        return seen <= start_dt - timedelta(hours=T2_HOURS)
    if snapshot == SNAP_T0:
        if seen <= start_dt:
            return True
        return seen <= start_dt + timedelta(minutes=GRACE_MIN)
    return False


def _source_for(seen_at: str, start_dt: datetime, snapshot: str) -> str:
    seen = parse_dt(seen_at)
    if seen is None:
        return snapshot
    seen = to_et(seen)
    if snapshot == SNAP_T2:
        return SNAP_T2
    if seen <= start_dt:
        return "pre-start"
    return f"grace+{GRACE_MIN}m"


def collect_new_rows(log=None) -> list[dict]:
    last = load_last()
    if not isinstance(last, dict):
        last = {}
    quotes = _tennis_yes(last)
    starts = _match_starts()
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in quotes:
        groups[(row["venue"], game_norm(row["game"]))].append(row)

    pending = _load_json(PENDING)
    existing = latest_by_identity()
    now = now_et()
    fresh = []

    for (venue, gnorm), members in groups.items():
        start_text = ""
        for row in members:
            start_text = _prefer_start(start_text, row.get("game_start") or "", starts.get(gnorm, ""))
        if not start_text:
            continue
        start_dt = parse_dt(start_text)
        if start_dt is None:
            continue
        start_dt = to_et(start_dt)
        start_iso = start_dt.isoformat()
        for row in members:
            others = [m for m in members if game_norm(m["player"]) != game_norm(row["player"])]
            opp = others[0] if others else None
            opp_yes = opp["yes_price"] if opp else None
            if opp is not None and not _quote_ok(opp.get("seen_at") or "", start_dt, SNAP_T0):
                # opponent_yes is "if known" at the same snapshot; keep latest other Yes anyway
                pass
            pid = identity("tennis", row["game"], row["player"], venue, "pending")
            slot = pending.get(pid) if isinstance(pending.get(pid), dict) else {}
            slot.update(
                {
                    "game": row["game"],
                    "player": row["player"],
                    "venue": venue,
                    "start": start_iso,
                }
            )
            seen = row.get("seen_at") or ""
            price = row["yes_price"]
            t2 = slot.get(SNAP_T2) if isinstance(slot.get(SNAP_T2), dict) else {}
            t0 = slot.get(SNAP_T0) if isinstance(slot.get(SNAP_T0), dict) else {}
            if seen and _quote_ok(seen, start_dt, SNAP_T2):
                _update_candidate(t2, seen, price)
                if opp_yes is not None:
                    t2["opponent_yes"] = opp_yes
                    t2["opponent"] = opp["player"] if opp else ""
            if seen and _quote_ok(seen, start_dt, SNAP_T0):
                _update_candidate(t0, seen, price)
                if opp_yes is not None:
                    t0["opponent_yes"] = opp_yes
                    t0["opponent"] = opp["player"] if opp else ""
            slot[SNAP_T2] = t2
            slot[SNAP_T0] = t0
            pending[pid] = slot

            for snapshot, cand in ((SNAP_T2, t2), (SNAP_T0, t0)):
                if not cand.get("at") or cand.get("yes_price") is None:
                    continue
                if not _freeze_ok(now, start_dt, snapshot):
                    continue
                key = identity("tennis", row["game"], row["player"], venue, snapshot)
                if key in existing:
                    continue
                rec = {
                    "at": cand.get("at"),
                    "sport": "tennis",
                    "game": row["game"],
                    "player": row["player"],
                    "venue": venue,
                    "yes_price": cand.get("yes_price"),
                    "opponent_yes": cand.get("opponent_yes"),
                    "opponent": cand.get("opponent") or (opp["player"] if opp else ""),
                    "start": start_iso,
                    "snapshot": snapshot,
                    "source": _source_for(cand.get("at"), start_dt, snapshot),
                    "start_source": "feed" if is_clocked(row.get("game_start")) else "catalog",
                    "settlement": "",
                    "settlement_source": "",
                    "key": key,
                    "written_at": iso_now(),
                    "seed": False,
                }
                fresh.append(rec)
                existing[key] = rec

    try:
        _write_pending(pending)
    except OSError as exc:
        _log(log, f"odds snapshots pending {type(exc).__name__}")
    return fresh


def fill_settlements(log=None) -> int:
    """Append an updated line when a stored snapshot later has a win/loss."""
    try:
        from polymarket_tennis_no_90plus_20261020 import load_settlements
        from odds_cross_winrate_20261020 import attach_results, build_index
    except Exception as exc:
        _log(log, f"odds snapshots settle import {type(exc).__name__}")
        return 0
    latest = latest_by_identity()
    pending_rows = [r for r in latest.values() if r.get("settlement") not in ("win", "loss")]
    if not pending_rows:
        return 0
    try:
        settlements = load_settlements()
        index = build_index(settlements)
    except Exception as exc:
        _log(log, f"odds snapshots settle load {type(exc).__name__}")
        return 0
    last = {}
    try:
        stored = load_last()
        if isinstance(stored, dict):
            last = stored
    except Exception:
        last = {}
    crosses = []
    for row in pending_rows:
        price = as_float(row.get("yes_price"))
        crosses.append(
            {
                "key": row.get("mem_key") or row.get("key") or "",
                "sport": "tennis",
                "game": row.get("game") or "",
                "market_type": "moneyline",
                "side": row.get("player") or "",
                "side_key": game_norm(row.get("player") or ""),
                "number": "",
                "venue": row.get("venue") or "",
                "game_start": row.get("start") or "",
                "cross_time": row.get("at") or "",
                "price": price,
            }
        )
    attach_results(crosses, last, settlements, index)
    updates = []
    for rec, cross in zip(pending_rows, crosses):
        official = cross.get("official") or ""
        if official not in ("win", "loss"):
            continue
        if rec.get("settlement") == official and rec.get("settlement_source") == (cross.get("official_source") or ""):
            continue
        updated = dict(rec)
        updated["settlement"] = official
        updated["settlement_source"] = cross.get("official_source") or ""
        updated["written_at"] = iso_now()
        updates.append(updated)
    return _append_rows(updates)


def tick(log=None) -> dict:
    """Supervisor/catalog hook. Writes due T-2h and T0 rows. Never sends an order."""
    out = {"seeded": 0, "wrote": 0, "settled": 0}
    try:
        out["seeded"] = seed_from_csv()
    except Exception as exc:
        _log(log, f"odds snapshots seed {type(exc).__name__}")
    try:
        fresh = collect_new_rows(log)
        out["wrote"] = _append_rows(fresh)
    except Exception as exc:
        _log(log, f"odds snapshots collect {type(exc).__name__}")
    try:
        out["settled"] = fill_settlements(log)
    except Exception as exc:
        _log(log, f"odds snapshots fill {type(exc).__name__}")
    if out["seeded"] or out["wrote"] or out["settled"]:
        _log(
            log,
            f"odds snapshots seed={out['seeded']} wrote={out['wrote']} settled={out['settled']}",
        )
    return out


def _rebuild_due() -> bool:
    stamp = _load_json(REBUILD_STAMP)
    last = parse_time(str(stamp.get("written_at") or ""))
    if last is None:
        return True
    return (now_et() - to_et(last)).total_seconds() >= REBUILD_EVERY_SEC


def rebuild_html(log=None) -> str:
    """Cheap rebuild from snapshots + settlement cache. Does not scan price_memory.jsonl."""
    try:
        from tennis_decade_at_start_20261020 import rebuild_from_snapshots
        path = rebuild_from_snapshots()
    except Exception as exc:
        _log(log, f"odds snapshots rebuild {type(exc).__name__}")
        return ""
    try:
        RAW.mkdir(parents=True, exist_ok=True)
        REBUILD_STAMP.write_text(
            json.dumps({"written_at": iso_now(), "page": str(path)}, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass
    _log(log, f"odds snapshots rebuilt {path}")
    return str(path)


def maybe_rebuild(log=None) -> None:
    """At most once per 15 minutes. Fail-soft background thread."""
    global _rebuild_thread
    if not _rebuild_due():
        return
    with _rebuild_lock:
        if _rebuild_thread is not None and _rebuild_thread.is_alive():
            return

        def _run() -> None:
            rebuild_html(log)

        _rebuild_thread = threading.Thread(target=_run, name="odds-snap-rebuild", daemon=True)
        _rebuild_thread.start()


def main() -> int:
    stats = tick()
    print(
        f"odds_snapshots seed={stats['seeded']} wrote={stats['wrote']} "
        f"settled={stats['settled']} file={SNAPSHOTS}",
        flush=True,
    )
    path = rebuild_html()
    print(f"rebuilt {path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
