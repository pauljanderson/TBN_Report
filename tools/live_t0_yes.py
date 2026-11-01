"""Shared T0 directional-Yes send for systems C, D, E, F, and G.

College football moneyline favorite (C), one traditional spread per game (D),
tennis moneyline T0 dog (E), tennis spread T0 cheapest Yes in [0.20, 0.50) (F),
soccer Points Total T0 cheapest Yes in [0.20, 0.50) (G).
D does not stack extra lines or totals on the same kickoff. Directional Yes.
Hold to settlement. No Strategy B 50-cross, no dip, no NET_MAX 0.984 gate.
One contract IOC unless stake-usd covers more whole contracts. REST recheck
before every send. Venue fill-history confirm is truth. Poly FOK.

Does not start live_strategy_b.py. Does not sell. Does not wire GTC.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_game_pollers  # noqa: E402
import live_lock_orders  # noqa: E402
import novig_live  # noqa: E402
import polymarket_us_live  # noqa: E402
import prediction_systems as systems  # noqa: E402
import price_memory  # noqa: E402
import venue_pace  # noqa: E402
from prediction_paths import RAW_DIR as RAW  # noqa: E402

ET = ZoneInfo("America/New_York")
T0_LEAD_SEC = 15
T0_GRACE_SEC = 300
TICK_SEC = 1
OPEN_STAGES = {"waiting_t0", "filled", "holding", "open"}
DONE_STAGES = {"skipped", "missed", "settled", "abandoned", "window_passed"}
VENUE_LABEL = {
    "kalshi": "kalshi",
    "gemini": "gemini",
    "polymarket": "polymarket",
    "novig": "novig",
}

WATCH = {
    "cfb_favorite": RAW / "cfb_favorite_watch.json",
    "spread_t0": RAW / "spread_t0_watch.json",
    "tennis_t0_dog": RAW / "tennis_t0_dog_watch.json",
    "tennis_t0_spread": RAW / "tennis_t0_spread_watch.json",
    "soccer_t0_total": RAW / "soccer_t0_total_watch.json",
}
LOCK = {
    "cfb_favorite": RAW / "cfb_favorite.lock",
    "spread_t0": RAW / "spread_t0.lock",
    "tennis_t0_dog": RAW / "tennis_t0_dog.lock",
    "tennis_t0_spread": RAW / "tennis_t0_spread.lock",
    "soccer_t0_total": RAW / "soccer_t0_total.lock",
}
PID_FILE = {
    "cfb_favorite": RAW / "cfb_favorite.pid",
    "spread_t0": RAW / "spread_t0.pid",
    "tennis_t0_dog": RAW / "tennis_t0_dog.pid",
    "tennis_t0_spread": RAW / "tennis_t0_spread.pid",
    "soccer_t0_total": RAW / "soccer_t0_total.pid",
}
LOG = {
    "cfb_favorite": RAW / "cfb_favorite.log",
    "spread_t0": RAW / "spread_t0.log",
    "tennis_t0_dog": RAW / "tennis_t0_dog.log",
    "tennis_t0_spread": RAW / "tennis_t0_spread.log",
    "soccer_t0_total": RAW / "soccer_t0_total.log",
}
STOP = {
    "cfb_favorite": RAW / "cfb_favorite.stop",
    "spread_t0": RAW / "spread_t0.stop",
    "tennis_t0_dog": RAW / "tennis_t0_dog.stop",
    "tennis_t0_spread": RAW / "tennis_t0_spread.stop",
    "soccer_t0_total": RAW / "soccer_t0_total.stop",
}
STEP = {
    "cfb_favorite": "c-t0",
    "spread_t0": "d-t0",
    "tennis_t0_dog": "e-t0",
    "tennis_t0_spread": "f-t0",
    "soccer_t0_total": "g-t0",
}
_VS_SPLIT = re.compile(r"\s+(?:vs\.?|@)\s+", re.I)
_ROUND_JUNK = re.compile(
    r"\b(round of \d+|r16|r32|qf|sf|finals?|semifinals?|quarterfinals?)\b",
    re.I,
)
_E_DOG_LOCK = threading.Lock()
_E_HELD_DOGS: set[tuple] = set()
E_FILL_STAGES = {"filled", "holding", "open", "settled", "missed"}
BET_PREFIX = {
    "cfb_favorite": "cfb-favorite",
    "spread_t0": "spread-t0",
    "tennis_t0_dog": "tennis-t0-dog",
    "tennis_t0_spread": "tennis-t0-spread",
    "soccer_t0_total": "soccer-t0-total",
}
NFL_SPORTS = {"pro football", "nfl"}
D_SKIP_NFL_TOKEN = "d_skip_nfl_gathering"
_last_d_nfl_skip: tuple[str, ...] = ()


def now_et() -> datetime:
    return datetime.now(ET)


def iso_now() -> str:
    return now_et().isoformat(timespec="milliseconds")


def _money(value: Decimal | None) -> str:
    if value is None:
        return ""
    return format(value.normalize(), "f")


def log(sid: str, msg: str) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    line = f"{iso_now()} {msg}\n"
    with LOG[sid].open("a", encoding="utf-8") as handle:
        handle.write(line)


def is_nfl_sport(sport: str) -> bool:
    return " ".join(str(sport or "").lower().split()) in NFL_SPORTS


def _log_d_nfl_skip(titles: list[str]) -> None:
    """Log in-window NFL skips when the set changes. Does not sell."""
    global _last_d_nfl_skip
    key = tuple(titles)
    if key == _last_d_nfl_skip:
        return
    _last_d_nfl_skip = key
    log("spread_t0", f"{D_SKIP_NFL_TOKEN} n={len(titles)} " + "; ".join(titles[:12]))


def _json_dump(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def empty_status(sid: str) -> dict:
    cfg = systems.get_system(sid)
    return {
        "system": sid,
        "display": systems.DISPLAY[sid],
        "enabled": bool(cfg.on),
        "max_open": int(cfg.max_open),
        "stake_usd": format(cfg.stake_usd, "f"),
        "size": int(cfg.size),
        "currently_open": 0,
        "pid": None,
        "updated_at": "",
        "last_send": "",
        "last_action": "",
        "last_skip_reason": "",
        "stake_note": "$1 ≈ 1 contract at these prices. Whole contracts only.",
        "research_only": True,
        "gold": False,
        "dailrun": False,
        "matches": [],
        "skipped": [],
    }


def load_status(sid: str, path: Path | None = None) -> dict:
    target = path or WATCH[sid]
    if not target.exists():
        return empty_status(sid)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_status(sid)
    if not isinstance(data, dict):
        return empty_status(sid)
    base = empty_status(sid)
    base.update(data)
    if not isinstance(base.get("matches"), list):
        base["matches"] = []
    if not isinstance(base.get("skipped"), list):
        base["skipped"] = []
    return base


def save_status(sid: str, data: dict) -> None:
    cfg = systems.get_system(sid)
    data = dict(data)
    data["system"] = sid
    data["display"] = systems.DISPLAY[sid]
    data["enabled"] = bool(cfg.on)
    data["max_open"] = int(cfg.max_open)
    data["stake_usd"] = format(cfg.stake_usd, "f")
    data["size"] = int(cfg.size)
    data["updated_at"] = iso_now()
    data["currently_open"] = len(open_matches(data))
    data["pid"] = os.getpid()
    with venue_pace.FileLock(LOCK[sid]):
        _json_dump(WATCH[sid], data)


def open_matches(data: dict) -> list[dict]:
    sid = str(data.get("system") or "")
    if sid in WATCH:
        try:
            import open_count_sync

            return open_count_sync.open_rows(sid, data)
        except Exception:
            pass
    out = []
    for row in data.get("matches") or []:
        if isinstance(row, dict) and str(row.get("stage") or "") in OPEN_STAGES:
            out.append(row)
    return out


def filled_matches(data: dict) -> list[dict]:
    out = []
    for row in data.get("matches") or []:
        if isinstance(row, dict) and str(row.get("stage") or "") in {"filled", "holding", "open"}:
            out.append(row)
    return out


def last_name_token(name: str) -> str:
    bits = [t for t in re.sub(r"[^a-z0-9]+", " ", str(name or "").lower()).split() if t]
    return bits[-1] if bits else ""


def match_player_set(title: str) -> frozenset[str]:
    """Canonical tennis match identity: last names, vs/@, ignore Round of 16."""
    text = _ROUND_JUNK.sub(" ", str(title or ""))
    text = " ".join(text.replace(".", " ").split())
    parts = _VS_SPLIT.split(text, maxsplit=1)
    if len(parts) != 2:
        return frozenset()
    names = [last_name_token(part) for part in parts]
    names = [n for n in names if n]
    return frozenset(names) if len(names) == 2 else frozenset()


def same_player_last(left: str, right: str) -> bool:
    a, b = last_name_token(left), last_name_token(right)
    return bool(a) and a == b


def same_game(left: str, right: str) -> bool:
    a = " ".join(str(left or "").lower().split())
    b = " ".join(str(right or "").lower().split())
    if a and a == b:
        return True
    players = match_player_set(left)
    return bool(players) and players == match_player_set(right)


def e_hold_key(title: str, dog: str) -> tuple:
    players = tuple(sorted(match_player_set(title)))
    return (players, last_name_token(dog))


def acquire_e_dog(title: str, dog: str) -> bool:
    """In-process lock so two platforms cannot both fill the same dog."""
    key = e_hold_key(title, dog)
    if not key[0] or not key[1]:
        return True
    with _E_DOG_LOCK:
        if key in _E_HELD_DOGS:
            return False
        _E_HELD_DOGS.add(key)
        return True


def release_e_dog(title: str, dog: str) -> None:
    key = e_hold_key(title, dog)
    with _E_DOG_LOCK:
        _E_HELD_DOGS.discard(key)


def _row_filled_qty(row: dict) -> bool:
    last = row.get("last_order") if isinstance(row.get("last_order"), dict) else {}
    qty = live_lock_orders._dec(last.get("fill_qty") or last.get("confirm_qty") or row.get("fill_qty"))
    return bool(qty is not None and qty >= 1)


def e_already_filled_dog(
    status: dict | None,
    title: str,
    dog: str,
    instrument: str = "",
) -> str:
    """Skip reason if E already filled Yes {dog} on this match (any title/platform)."""
    if not isinstance(status, dict):
        return ""
    want_players = match_player_set(title)
    dog_l = last_name_token(dog)
    inst = str(instrument or "").strip().lower()
    if not dog_l and not inst:
        return ""
    for row in status.get("matches") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("stage") or "") not in E_FILL_STAGES and not _row_filled_qty(row):
            continue
        if not _row_filled_qty(row) and str(row.get("stage") or "") not in {"filled", "holding", "open", "settled"}:
            continue
        game = str(row.get("game") or "")
        row_inst = str(row.get("instrument") or (row.get("last_order") or {}).get("instrument") or "").strip().lower()
        game_hit = same_game(game, title) or (bool(want_players) and match_player_set(game) == want_players)
        inst_hit = bool(inst) and inst == row_inst
        player_hit = same_player_last(str(row.get("dog") or row.get("fav") or ""), dog)
        if not player_hit:
            continue
        if game_hit or inst_hit:
            who = str(row.get("dog") or dog)
            return f"already filled Yes {who} on this match"
    return ""


def rest_e_open_same_dog(dog: str, instrument: str = "", venue: str = "") -> bool:
    """True when a venue overlay already holds this E dog. Fail-soft. Does not trade."""
    inst = str(instrument or "").strip().lower()
    dog_l = last_name_token(dog)
    if not inst and not dog_l:
        return False
    try:
        import open_count_sync

        snap = open_count_sync.venue_snapshot()
    except Exception:
        return False
    if not isinstance(snap, dict):
        return False
    for row in snap.get("rows") or []:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or row.get("instrument") or "").strip().lower()
        if inst and ticker == inst:
            return True
        blob = " ".join(str(row.get(k) or "") for k in ("title", "game", "outcome", "side", "player")).lower()
        if dog_l and dog_l in blob:
            players = match_player_set(str(row.get("title") or row.get("game") or ""))
            if players and dog_l in players:
                return True
    _ = venue
    return False


def blocks_lock(sid: str, sport: str, title: str, data: dict | None = None) -> bool:
    """True while this system has an open/filled ticket on the same event."""
    status = data if isinstance(data, dict) else load_status(sid)
    want = " ".join(str(title or "").lower().split())
    if not want:
        return False
    for row in status.get("matches") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("stage") or "") not in OPEN_STAGES:
            continue
        if same_game(str(row.get("game") or ""), want):
            return True
        if str(row.get("key") or "") and str(row.get("key") or "") == str(sport or ""):
            return True
    return False


def occurrence_clock(gemini_events, kalshi_events) -> datetime | None:
    for ev in list(gemini_events or []) + list(kalshi_events or []):
        if not isinstance(ev, dict):
            continue
        for key in ("startTime", "occurrence_datetime", "target_datetime", "startDate"):
            raw = ev.get(key)
            dt = price_memory.parse_time(raw) if raw else None
            if dt is not None:
                return dt
    return None


def is_scheduled_listed_clock(dt: datetime | None) -> bool:
    """True for 21:30:00 lists. False for odd-second feed stamps."""
    if not isinstance(dt, datetime):
        return False
    return dt.second == 0 and dt.microsecond == 0


def start_moved_next_et_day(original: datetime | None, current: datetime | None) -> bool:
    if original is None or current is None:
        return False
    return current.astimezone(ET).date() > original.astimezone(ET).date()


def choose_trusted_t0_clock(
    occ: datetime | None,
    listed: datetime | None,
    live: datetime | None = None,
) -> tuple[datetime | None, str]:
    """Send clock: later of occurrence and a scheduled listed start.

    Kalshi occurrence can sit hours before first serve (Parks vs Birrell
    00:30 ET while listed/Polymarket gameStart was 21:30 ET). Pollers may
    spawn early for data; T0 send waits for the later clock. A delayed
    occurrence after listed still wins. Odd-second listed stamps are not
    scheduled court time unless the live start moved to a later ET day
    (Liu vs Colby: listed 14:00 28 Oct, real start next day).
    """
    cands: list[tuple[datetime, str]] = []
    if occ is not None:
        cands.append((occ, "occurrence"))
    if listed is not None and is_scheduled_listed_clock(listed):
        cands.append((listed, "listed/feed"))
    if live is not None:
        if start_moved_next_et_day(listed, live) or start_moved_next_et_day(occ, live):
            cands.append((live, "live start (next day)"))
        elif is_scheduled_listed_clock(live):
            cands.append((live, "listed/feed"))
    if not cands:
        return None, ""
    return max(cands, key=lambda item: item[0])


def trusted_t0_clock(listed_iso: str, gemini_events, kalshi_events) -> tuple[datetime | None, str]:
    """First trusted serve: later of occurrence and listed with seconds=00."""
    occ = occurrence_clock(gemini_events, kalshi_events)
    listed = price_memory.parse_time(listed_iso) if listed_iso else None
    return choose_trusted_t0_clock(occ, listed)


def t0_window(clock: datetime | None, now: datetime | None = None) -> tuple[bool, str]:
    now = now or now_et()
    if clock is None:
        return False, "no trusted clock"
    if now < clock - timedelta(seconds=T0_LEAD_SEC):
        return False, "before T0"
    if now > clock + timedelta(seconds=T0_GRACE_SEC):
        return False, "T0 window passed"
    return True, "in T0 window"


def _view_spec(venue: str, view: dict) -> dict | None:
    pay = live_lock_orders._dec(view.get("yes"))
    ident = str(view.get("ident") or "")
    if pay is None or not ident:
        return None
    side = str(view.get("side") or view.get("label") or "")
    row = {
        "venue": venue,
        "instrument": ident,
        "outcome": "yes",
        "pay": _money(pay),
        "yes": pay,
        "ask": pay,
        "side": side,
        "team": side,
        "kind": str(view.get("kind") or ""),
        "number": "" if str(view.get("kind") or "") == "moneyline" else str(view.get("number") or ""),
        "yes_size": view.get("yes_size"),
        "intent": "",
        "spec": {
            "venue": venue,
            "instrument": ident,
            "outcome": "yes",
            "intent": "",
            "outcome_id": "",
            "fee_coefficient": view.get("fee_coefficient"),
            "fee_charged": view.get("fee_charged"),
            "event_status": view.get("event_status") or view.get("status"),
            "player": side,
        },
    }
    if venue == "novig":
        yes_id = str(view.get("buy_yes_outcome") or view.get("yes_outcome_id") or view.get("outcome_id") or "")
        if not yes_id:
            return None
        row["spec"]["outcome_id"] = yes_id
        row["outcome_id"] = yes_id
    if venue == "polymarket":
        intent = str(view.get("poly_yes_intent") or view.get("intent") or "ORDER_INTENT_BUY_LONG")
        row["spec"]["intent"] = intent
        row["intent"] = intent
        row["spec"]["fee_coefficient"] = view.get("fee_coefficient")
    return row


def _poly_quotes(contracts) -> list[dict]:
    out = []
    for contract in contracts or []:
        if not isinstance(contract, dict):
            continue
        kind = str(contract.get("kind") or "moneyline")
        if kind not in ("moneyline", "spread", "total", "team_total"):
            continue
        number = "" if kind == "moneyline" else str(contract.get("number") or "")
        slug = str(contract.get("slug") or "")
        ask = live_lock_orders._dec(contract.get("yes_ask"))
        if not slug or ask is None:
            continue
        long_name = str(contract.get("long_name") or "")
        short_name = str(contract.get("short_name") or "")
        fee = contract.get("fee_coefficient")
        if long_name:
            out.append({
                "venue": "polymarket",
                "instrument": slug,
                "outcome": "yes",
                "pay": _money(ask),
                "yes": ask,
                "ask": ask,
                "side": long_name,
                "team": long_name,
                "kind": kind,
                "number": number,
                "intent": "ORDER_INTENT_BUY_LONG",
                "spec": {
                    "venue": "polymarket",
                    "instrument": slug,
                    "outcome": "yes",
                    "intent": "ORDER_INTENT_BUY_LONG",
                    "fee_coefficient": fee,
                    "player": long_name,
                },
            })
        short_ask = live_lock_orders._dec(contract.get("short_yes_ask"))
        if short_ask is None and ask is not None:
            short_ask = (Decimal("1") - ask) if ask <= 1 else None
        if short_name and short_ask is not None:
            out.append({
                "venue": "polymarket",
                "instrument": slug,
                "outcome": "yes",
                "pay": _money(short_ask),
                "yes": short_ask,
                "ask": short_ask,
                "side": short_name,
                "team": short_name,
                "kind": kind,
                "number": number,
                "intent": "ORDER_INTENT_BUY_SHORT",
                "spec": {
                    "venue": "polymarket",
                    "instrument": slug,
                    "outcome": "yes",
                    "intent": "ORDER_INTENT_BUY_SHORT",
                    "fee_coefficient": fee,
                    "player": short_name,
                },
            })
    return out


def collect_quotes(scan, game: dict, sport: str) -> tuple[list[dict], list, list, list, list]:
    k_tickers, g_tickers = live_game_pollers.tickers_for_quotes(game, scan, sport)
    gemini_events = [scan.fetch_gemini_event(t) for t in g_tickers]
    kalshi_events = [scan.fetch_kalshi_event(t) for t in k_tickers]
    numbers = live_game_pollers._listed_numbers(scan, kalshi_events, gemini_events)
    polymarket = polymarket_us_live.blank_contracts(polymarket_us_live.markets_from_search(game, numbers))
    polymarket_us_live.seed_books(polymarket)
    novig = novig_live.markets_from_game(game, numbers, sport)
    novig_live.seed_books(novig)
    quotes = []
    for venue, events in (("kalshi", kalshi_events), ("gemini", gemini_events)):
        for view in scan.load_views(events, venue):
            row = _view_spec(venue, view)
            if row:
                quotes.append(row)
    quotes.extend(_poly_quotes(polymarket))
    for contract in novig or []:
        if not isinstance(contract, dict):
            continue
        for view in novig_live.contract_views(contract):
            row = _view_spec("novig", view)
            if row:
                quotes.append(row)
    return quotes, kalshi_events, gemini_events, polymarket, novig


def group_lines(quotes: list[dict], kind: str) -> dict[tuple, list[dict]]:
    bags: dict[tuple, list[dict]] = {}
    for row in quotes:
        if str(row.get("kind") or "") != kind:
            continue
        number = "" if kind == "moneyline" else str(row.get("number") or "")
        bags.setdefault((kind, number), []).append(row)
    return bags


def two_sided_teams(rows: list[dict]) -> dict[str, list]:
    by_team: dict[str, list] = {}
    for row in rows:
        side = str(row.get("side") or "")
        if not side:
            continue
        key = None
        for existing in by_team:
            if systems.same_side(existing, side):
                key = existing
                break
        if key is None:
            key = side
            by_team[key] = []
        px = live_lock_orders._dec(row.get("yes"))
        if px is not None:
            by_team[key].append(px)
    return by_team


def primary_side_asks(rows: list[dict]) -> dict[str, Decimal]:
    by_venue: dict[str, list[dict]] = {}
    for row in rows:
        by_venue.setdefault(str(row.get("venue") or "").lower(), []).append(row)
    for venue in systems.VENUE_RANK:
        group = by_venue.get(venue) or []
        asks: dict[str, Decimal] = {}
        for row in group:
            side = str(row.get("side") or "")
            px = live_lock_orders._dec(row.get("yes"))
            if side and px is not None:
                asks[side] = px
        if len(asks) >= 2:
            return asks
    return {}


def _in_send_band(sid: str, ask) -> bool:
    if sid == "tennis_t0_dog":
        return systems.in_dog_band(ask)
    if sid == "tennis_t0_spread":
        return systems.in_f_spread_band(ask)
    if sid == "soccer_t0_total":
        return systems.in_g_total_band(ask)
    return systems.in_fav_band(ask)


def _band_note(sid: str, ask) -> str:
    if sid == "tennis_t0_dog":
        return f"ask {ask} not in (0.10, 0.50)"
    if sid == "tennis_t0_spread":
        return f"ask {ask} not in [0.20, 0.50)"
    if sid == "soccer_t0_total":
        return f"ask {ask} not in [0.20, 0.50)"
    return f"ask {ask} not in (0.50, 0.90)"


def b_holds_match(sport: str, title: str, *, b_status: dict | None = None) -> bool:
    """True when Tennis crossover already has this tennis match (absorbed / T0 sent).

    Skip-if-B-open lives in live_tennis_t0_dog so a Patel 50-cross edit of
    live_strategy_b.py is not required. C>1.05 skip on B does not block E.
    """
    import live_tennis_t0_dog

    return live_tennis_t0_dog.b_holds_match(title, sport=sport, b_status=b_status)


def choose_dog(rows: list[dict]) -> tuple[str | None, str]:
    primary = primary_side_asks(rows)
    dog = systems.pick_dog_primary(primary) if len(primary) >= 2 else None
    teams = two_sided_teams(rows)
    if len(teams) < 2:
        return None, "not two-sided"
    if dog:
        return dog, "primary dog"
    resolved = systems.resolve_dog_across_venues(teams)
    if not resolved:
        return None, "no unique dog / 50-50"
    return resolved, "venues disagreed; used lower-median dog"


def dog_line_snapshot(rows: list[dict]) -> dict | None:
    dog, why = choose_dog(rows)
    if not dog:
        return None
    best = systems.best_venue_yes(rows, dog)
    if best is None:
        return None
    px = live_lock_orders._dec(best.get("yes"))
    if px is None or not systems.in_dog_band(px):
        return None
    sides = two_sided_teams(rows)
    return {
        "dog": dog,
        "fav": dog,
        "fav_ask": px,
        "dog_ask": px,
        "why": why,
        "two_sided": len(sides) >= 2,
        "best": best,
        "kind": str((rows[0].get("kind") if rows else "") or "moneyline"),
        "number": str((rows[0].get("number") if rows else "") or ""),
    }


def cheapest_spread_snapshot(rows: list[dict]) -> dict | None:
    """F: cheapest tennis spread Yes in [0.20, 0.50). Not moneyline. Not D closest-to-50."""
    best = systems.pick_cheapest_spread_yes(rows)
    if best is None:
        return None
    px = live_lock_orders._dec(best.get("yes") if best.get("yes") is not None else best.get("ask"))
    if px is None or not systems.in_f_spread_band(px):
        return None
    side = str(best.get("side") or best.get("team") or "")
    return {
        "dog": side,
        "fav": side,
        "fav_ask": px,
        "dog_ask": px,
        "why": "cheapest spread in [0.20, 0.50)",
        "two_sided": True,
        "best": best,
        "kind": "spread",
        "number": str(best.get("number") or ""),
    }


def cheapest_total_snapshot(rows: list[dict]) -> dict | None:
    """G: cheapest soccer Points Total Yes in [0.20, 0.50). Not moneyline. Not spread."""
    best = systems.pick_cheapest_total_yes(rows)
    if best is None:
        return None
    px = live_lock_orders._dec(best.get("yes") if best.get("yes") is not None else best.get("ask"))
    if px is None or not systems.in_g_total_band(px):
        return None
    side = str(best.get("side") or best.get("team") or "")
    return {
        "dog": side,
        "fav": side,
        "fav_ask": px,
        "dog_ask": px,
        "why": "cheapest Points Total in [0.20, 0.50)",
        "two_sided": True,
        "best": best,
        "kind": "total",
        "number": str(best.get("number") or ""),
    }


def choose_favorite(rows: list[dict]) -> tuple[str | None, str]:
    primary = primary_side_asks(rows)
    fav = systems.pick_favorite_primary(primary) if len(primary) >= 2 else None
    teams = two_sided_teams(rows)
    if len(teams) < 2:
        return None, "not two-sided"
    if fav:
        return fav, "primary favorite"
    resolved = systems.resolve_favorite_across_venues(teams)
    if not resolved:
        return None, "no unique favorite / 50-50"
    return resolved, "venues disagreed; used >50 median rule"


def line_snapshot(rows: list[dict]) -> dict | None:
    fav, why = choose_favorite(rows)
    if not fav:
        return None
    best = systems.best_venue_yes(rows, fav)
    if best is None:
        return None
    px = live_lock_orders._dec(best.get("yes"))
    sides = two_sided_teams(rows)
    return {
        "fav": fav,
        "fav_ask": px,
        "why": why,
        "two_sided": len(sides) >= 2,
        "best": best,
        "kind": str((rows[0].get("kind") if rows else "") or ""),
        "number": str((rows[0].get("number") if rows else "") or ""),
    }


def send_yes(spec: dict, pay: Decimal, step: str, bet_key: str, system: str, log_fn) -> dict:
    live = dict(spec)
    live["outcome"] = "yes"
    live["_system"] = system
    live["quote_source"] = "book"
    live["quote_price"] = _money(pay)
    live["quote_seen_at"] = iso_now()
    built = live_lock_orders._spec_at_price(live, pay)
    blank = {
        "filled": False,
        "posted": False,
        "payload": None,
        "status": 0,
        "note": "price not sendable",
        "pay": _money(pay),
        "spec": live,
        "order_id": "",
        "fill_qty": "0",
        "sent_at": "",
    }
    if built is None:
        return blank
    built["_system"] = system
    built["_bet_key"] = bet_key
    built["_step"] = step
    built["game"] = spec.get("game") or live.get("game") or ""
    built["sport"] = spec.get("sport") or live.get("sport") or ""
    built["player"] = spec.get("player") or live.get("player") or ""
    built["side_label"] = built["player"]
    live_lock_orders._carry_quote_fields(live, built)
    skip = live_lock_orders.poly_size_lt_qty_skip(built)
    if skip:
        log_fn(f"{system} skip {skip}")
        live_lock_orders.record_research_row(
            {
                "event": (
                    "e" if system == "tennis_t0_dog"
                    else "f" if system == "tennis_t0_spread"
                    else "g" if system == "soccer_t0_total"
                    else system
                ),
                "action": "skip",
                "reason": skip,
                "game": built.get("game") or spec.get("game") or "",
                "venue": built.get("venue") or "",
                "instrument": built.get("instrument") or "",
                "player": built.get("player") or "",
                "quote_size": built.get("quote_size") or "",
                "quote_price": built.get("quote_price") or _money(pay),
                "step": step,
                "system": system,
            }
        )
        blank["note"] = skip
        blank["spec"] = built
        return blank
    funds = live_lock_orders._funds_block(built)
    if funds:
        named = live_lock_orders._balance_deny_from_funds(funds)
        log_fn(f"{system} skip funds {named}")
        blank["note"] = named
        return blank
    status, payload, note = live_lock_orders._post_same_limit(
        log_fn, bet_key, built, step, live_lock_orders._send, pay, None, None
    )
    filled_qty = live_lock_orders.filled_contracts(payload) if payload is not None else Decimal("0")
    if status not in (200, 201) and not live_lock_orders.venue_confirm_known(payload):
        filled_qty = Decimal("0")
    if live_lock_orders.poly_partial_unexpected(built, filled_qty):
        live_lock_orders.note_poly_fok_partial(built, filled_qty, log_fn)
    if status in (200, 201) and live_lock_orders.order_still_open(payload) and filled_qty < 1:
        cancel_status, cancel_note = live_lock_orders._cancel(built, payload)
        log_fn(f"{system} cancel venue={built.get('venue')} http={cancel_status} {cancel_note}")
    fill_px = live_lock_orders._actual_fill_cash(built, payload) if filled_qty > 0 else None
    confirm = live_lock_orders.venue_confirm_of(payload) or {}
    posted = status != 0
    return {
        "filled": filled_qty >= 1,
        "posted": posted,
        "payload": payload,
        "status": status,
        "note": note,
        "pay": built.get("pay") or _money(pay),
        "spec": built,
        "order_id": live_lock_orders._order_id(payload),
        "fill_qty": _money(filled_qty),
        "fill_px": _money(fill_px) if fill_px is not None else "",
        "sent_at": built.get("sent_at") or iso_now(),
        "http": status,
        "confirm_known": bool(confirm.get("known")),
        "confirm_qty": str(confirm.get("qty") or "0"),
        "confirm_note": str(confirm.get("note") or ""),
    }


def _maybe_perf(result: dict) -> None:
    try:
        import orders_performance_refresh

        orders_performance_refresh.maybe_after_order(result.get("payload"), status=result.get("status"))
    except Exception:
        pass


def fire(sid: str, spec_row: dict, snap: dict, cfg: systems.SystemCfg, log_fn) -> dict:
    best = snap.get("best") or {}
    send_spec = dict(best.get("spec") or {})
    send_spec["game"] = spec_row.get("title") or spec_row.get("game") or ""
    send_spec["sport"] = spec_row.get("sport") or ""
    send_spec["player"] = snap.get("dog") or snap.get("fav") or ""
    ask = live_lock_orders._dec(snap.get("dog_ask") if snap.get("dog_ask") is not None else snap.get("fav_ask"))
    if ask is None or not _in_send_band(sid, ask):
        return {"stage": "skipped", "note": _band_note(sid, ask)}
    n = systems.contracts_for_stake(ask, size=cfg.size, stake_usd=cfg.stake_usd)
    if n < 1:
        return {"stage": "skipped", "note": f"ask {ask} over stake {cfg.stake_usd}"}
    recheck, note = live_lock_orders.fetch_book_ask(send_spec, priority=True)
    if recheck is None:
        return {"stage": "missed", "note": f"recheck failed: {note}"}
    snapped = live_lock_orders.snap_pay(str(send_spec.get("venue") or ""), recheck)
    if snapped is None or not _in_send_band(sid, snapped):
        return {"stage": "skipped", "note": f"recheck {_band_note(sid, snapped)}"}
    n = systems.contracts_for_stake(snapped, size=cfg.size, stake_usd=cfg.stake_usd)
    if n < 1:
        return {"stage": "skipped", "note": f"recheck {snapped} over stake {cfg.stake_usd}"}
    game = send_spec.get("game") or ""
    key = spec_row.get("key") or ""
    filled_any = False
    last = None
    for i in range(n):
        again, _why = live_lock_orders.fetch_book_ask(send_spec, priority=True)
        if again is None:
            break
        snapped = live_lock_orders.snap_pay(str(send_spec.get("venue") or ""), again)
        if snapped is None or not _in_send_band(sid, snapped):
            break
        side = snap.get("dog") or snap.get("fav") or ""
        bet_key = f"{BET_PREFIX[sid]}\t{key}\t{side}\t{snap.get('number') or ''}\t{i+1}"
        last = send_yes(send_spec, snapped, STEP[sid], bet_key, sid, log_fn)
        _maybe_perf(last)
        if last.get("filled"):
            filled_any = True
        elif last.get("posted"):
            break
        else:
            break
    if filled_any:
        return {
            "stage": "filled",
            "note": f"filled {snap.get('dog') or snap.get('fav')} {last.get('fill_qty') if last else ''} @ {last.get('fill_px') if last else ''}",
            "last_order": last or {},
        }
    return {
        "stage": "missed",
        "note": (last or {}).get("note") or "no fill",
        "last_order": last or {},
    }


def _existing(status: dict, title: str, key: str) -> dict | None:
    for row in status.get("matches") or []:
        if not isinstance(row, dict):
            continue
        if key and str(row.get("key") or "") == key:
            return row
        if same_game(str(row.get("game") or ""), title):
            return row
    return None


def consider_game(sid: str, scan, spec: dict, status: dict, cfg: systems.SystemCfg) -> str:
    sport = str(spec.get("sport") or "")
    title = str(spec.get("title") or "")
    key = str(spec.get("key") or "")
    if sid == "cfb_favorite":
        kind = "moneyline"
        if sport.strip().lower() != "college football":
            return "not college football"
    elif sid == "tennis_t0_dog":
        kind = "moneyline"
        if sport.strip().lower() != "tennis":
            return "not tennis"
        if b_holds_match(sport, title):
            existing = _existing(status, title, key)
            if existing is not None and str(existing.get("stage") or "") == "waiting_t0":
                existing["stage"] = "skipped"
                existing["note"] = "B already on match"
                status["last_skip_reason"] = f"{title}: B already on match"
            else:
                status["last_skip_reason"] = f"{title}: B already on match"
            return "B already on match"
    elif sid == "tennis_t0_spread":
        kind = "spread"
        if sport.strip().lower() != "tennis":
            return "not tennis"
        if b_holds_match(sport, title):
            existing = _existing(status, title, key)
            if existing is not None and str(existing.get("stage") or "") == "waiting_t0":
                existing["stage"] = "skipped"
                existing["note"] = "B already on match"
                status["last_skip_reason"] = f"{title}: B already on match"
            else:
                status["last_skip_reason"] = f"{title}: B already on match"
            return "B already on match"
    elif sid == "soccer_t0_total":
        kind = "total"
        if sport.strip().lower() != "soccer":
            return "not soccer"
        import live_soccer_t0_total

        collide = live_soccer_t0_total.same_game_key_held(
            key,
            title,
            b_status=live_soccer_t0_total._load_watch(live_soccer_t0_total.B_WATCH),
            e_status=live_soccer_t0_total._load_watch(live_soccer_t0_total.E_WATCH),
            f_status=live_soccer_t0_total._load_watch(live_soccer_t0_total.F_WATCH),
        )
        if collide:
            existing = _existing(status, title, key)
            if existing is not None and str(existing.get("stage") or "") == "waiting_t0":
                existing["stage"] = "skipped"
                existing["note"] = collide
                status["last_skip_reason"] = f"{title}: {collide}"
            else:
                status["last_skip_reason"] = f"{title}: {collide}"
            return collide
    else:
        kind = "spread"
        if sid == "spread_t0" and is_nfl_sport(sport):
            existing = _existing(status, title, key)
            if existing is not None and str(existing.get("stage") or "") not in {"waiting_t0", ""}:
                return str(existing.get("stage") or "already handled")
            log(sid, f"{D_SKIP_NFL_TOKEN} {title}")
            if existing is not None and str(existing.get("stage") or "") == "waiting_t0":
                existing["stage"] = "skipped"
                existing["note"] = D_SKIP_NFL_TOKEN
            status["last_skip_reason"] = f"{title}: {D_SKIP_NFL_TOKEN}"
            return D_SKIP_NFL_TOKEN
    existing = _existing(status, title, key)
    if existing is not None and str(existing.get("stage") or "") not in {"waiting_t0"}:
        return str(existing.get("stage") or "already handled")
    listed_iso = spec.get("listed_start") or spec.get("start") or ""
    listed_clock, _listed_src = trusted_t0_clock(listed_iso, [], [])
    if listed_clock is not None:
        _ready_listed, why_listed = t0_window(listed_clock)
        if not _ready_listed:
            if why_listed == "T0 window passed":
                if existing is None:
                    status.setdefault("skipped", []).append({
                        "key": key,
                        "game": title,
                        "sport": sport,
                        "stage": "window_passed",
                        "note": why_listed,
                        "when": iso_now(),
                    })
                    status["skipped"] = status["skipped"][-40:]
                    status["last_skip_reason"] = f"{title}: {why_listed}"
                else:
                    existing["note"] = why_listed
                    existing["stage"] = "window_passed"
            return why_listed
    quotes, kalshi_events, gemini_events, _poly, _novig = collect_quotes(scan, spec.get("game") or {}, sport)
    clock, clock_src = trusted_t0_clock(
        spec.get("listed_start") or spec.get("start") or "",
        gemini_events,
        kalshi_events,
    )
    ready, why = t0_window(clock)
    bags = group_lines(quotes, kind)
    if sid == "cfb_favorite":
        rows = bags.get(("moneyline", ""), [])
        snap = line_snapshot(rows)
        snaps = [snap] if snap else []
    elif sid == "tennis_t0_dog":
        rows = bags.get(("moneyline", ""), [])
        snap = dog_line_snapshot(rows)
        snaps = [snap] if snap else []
    elif sid == "tennis_t0_spread":
        spread_rows = []
        for _key, rows in bags.items():
            spread_rows.extend(rows)
        snap = cheapest_spread_snapshot(spread_rows)
        snaps = [snap] if snap else []
    elif sid == "soccer_t0_total":
        total_rows = []
        for _key, rows in bags.items():
            total_rows.extend(rows)
        snap = cheapest_total_snapshot(total_rows)
        snaps = [snap] if snap else []
    else:
        snaps = []
        for (_k, number), rows in bags.items():
            shot = line_snapshot(rows)
            if shot:
                shot["number"] = number
                snaps.append(shot)
        picked = systems.pick_spread_line(snaps)
        snaps = picked[:1]
    if existing is None:
        if not ready:
            if why == "T0 window passed":
                skipped = {
                    "key": key,
                    "game": title,
                    "sport": sport,
                    "stage": "window_passed",
                    "note": why,
                    "when": iso_now(),
                }
                status.setdefault("skipped", []).append(skipped)
                status["skipped"] = status["skipped"][-40:]
                status["last_skip_reason"] = f"{title}: {why}"
            return why
        if len(open_matches(status)) >= int(cfg.max_open) and not existing:
            return "max_open"
        match = {
            "key": key,
            "game": title,
            "sport": sport,
            "stage": "waiting_t0",
            "opened_at": iso_now(),
            "t0_when": clock.isoformat() if clock else "",
            "t0_src": clock_src,
            "kind": kind,
            "note": why,
        }
        status.setdefault("matches", []).append(match)
        existing = match
    if not ready:
        existing["note"] = why
        if why == "T0 window passed":
            existing["stage"] = "window_passed"
        return why
    if not snaps:
        if sid == "tennis_t0_dog":
            existing["note"] = "no unique dog Yes in (0.10, 0.50)"
        elif sid == "tennis_t0_spread":
            existing["note"] = "no tennis spread Yes in [0.20, 0.50)"
        elif sid == "soccer_t0_total":
            existing["note"] = "no soccer Points Total Yes in [0.20, 0.50)"
        else:
            existing["note"] = f"no qualifying {kind} in (0.50, 0.90)"
        existing["stage"] = "skipped"
        status["last_skip_reason"] = existing["note"]
        return existing["note"]
    if sid in {"tennis_t0_dog", "tennis_t0_spread"} and b_holds_match(sport, title):
        existing["stage"] = "skipped"
        existing["note"] = "B already on match"
        status["last_skip_reason"] = existing["note"]
        return existing["note"]
    shot = snaps[0]
    if sid == "soccer_t0_total":
        import live_soccer_t0_total

        a_why = live_soccer_t0_total.a_holds_same_total(title, str(shot.get("number") or ""))
        if a_why:
            existing["stage"] = "skipped"
            existing["note"] = a_why
            status["last_skip_reason"] = f"{title}: {a_why}"
            return a_why
        why_dup = live_soccer_t0_total.already_filled_match(status, title)
        if why_dup:
            existing["stage"] = "skipped"
            existing["note"] = why_dup
            status["last_skip_reason"] = f"{title}: {why_dup}"
            return why_dup
    existing["fav"] = shot.get("dog") or shot.get("fav")
    existing["dog"] = shot.get("dog") or shot.get("fav")
    existing["fav_ask"] = _money(shot.get("fav_ask"))
    existing["dog_ask"] = _money(shot.get("dog_ask") if shot.get("dog_ask") is not None else shot.get("fav_ask"))
    existing["venue"] = (shot.get("best") or {}).get("venue")
    existing["number"] = shot.get("number") or ""
    existing["t0_src"] = clock_src
    if sid == "tennis_t0_dog":
        dog = str(shot.get("dog") or existing.get("dog") or "")
        inst = str((shot.get("best") or {}).get("instrument") or existing.get("instrument") or "")
        venue = str((shot.get("best") or {}).get("venue") or existing.get("venue") or "")
        why_dup = e_already_filled_dog(status, title, dog, inst)
        if why_dup:
            existing["stage"] = "skipped"
            existing["note"] = why_dup
            status["last_skip_reason"] = f"{title}: {why_dup}"
            return why_dup
        held = acquire_e_dog(title, dog)
        if not held:
            why_dup = f"already filled Yes {dog} on this match"
            existing["stage"] = "skipped"
            existing["note"] = why_dup
            status["last_skip_reason"] = f"{title}: {why_dup}"
            return why_dup
        if rest_e_open_same_dog(dog, inst, venue):
            why_dup = f"already filled Yes {dog} on this match"
            existing["stage"] = "skipped"
            existing["note"] = why_dup
            status["last_skip_reason"] = f"{title}: {why_dup}"
            return why_dup
        result = fire(sid, spec, shot, cfg, lambda m: log(sid, m))
        if str(result.get("stage") or "") != "filled":
            release_e_dog(title, dog)
    else:
        result = fire(sid, spec, shot, cfg, lambda m: log(sid, m))
    existing["stage"] = result.get("stage") or existing.get("stage")
    existing["note"] = result.get("note") or ""
    last = result.get("last_order") or {}
    if last:
        spec_used = last.get("spec") if isinstance(last.get("spec"), dict) else {}
        existing["last_order"] = {
            "id": last.get("order_id") or "",
            "time": last.get("sent_at") or "",
            "http": last.get("status") or last.get("http"),
            "fill_qty": last.get("fill_qty") or "0",
            "note": last.get("note") or "",
            "pay": last.get("pay") or "",
            "instrument": spec_used.get("instrument") or existing.get("instrument") or "",
            "venue": spec_used.get("venue") or existing.get("venue") or "",
            "confirm_qty": last.get("confirm_qty") or last.get("fill_qty") or "0",
            "confirm_known": last.get("confirm_known"),
        }
        existing["instrument"] = existing["last_order"]["instrument"] or existing.get("instrument") or ""
        status["last_send"] = str(last.get("sent_at") or iso_now())
        status["last_action"] = f"{existing['stage']} {title} {existing.get('dog') or existing.get('fav')} {last.get('pay')}"
    return str(existing.get("stage") or "")


def slate_near_t0(scan, sid: str) -> list[dict]:
    """Games from 15 minutes before listed start through typical length.

    live_games() starts exactly at listed start, which can miss the T0 window
    if the supervisor has not spawned the poller yet. C/D still need the clock.

    E (tennis T0 dog) and F (tennis T0 spread) read live_game_pollers.tennis_rows
    — the same tennis list Strategy B uses — not overnight sports_queue.json
    (no tennis there). G (soccer Points Total) uses iter_matched soccer only
    (EPL / MLS / UCL and other soccer leagues in the catalog). NFL and college
    football stay off E, F, and G. Send still uses t0_window (T0_LEAD_SEC=15
    before through T0_GRACE_SEC=300 after) on choose_trusted_t0_clock (later of
    occurrence and scheduled listed). Skip-if-B-open stays in consider_game
    for E/F. G does not skip-if-B by title.
    """
    moment = now_et()
    rows = []
    want_sport = ""
    skip_tennis = False
    skip_nfl = sid == "spread_t0"
    skipped_nfl: list[str] = []
    if sid == "cfb_favorite":
        want_sport = "college football"
    elif sid == "soccer_t0_total":
        want_sport = "soccer"
        skip_tennis = True
    elif sid in {"tennis_t0_dog", "tennis_t0_spread"}:
        hours = live_game_pollers.LIVE_HOURS.get("tennis", 5.0)
        for row in live_game_pollers.tennis_rows(scan):
            if not isinstance(row, dict):
                continue
            if str(row.get("sport") or "").lower() != "tennis":
                continue
            game = row.get("game") if isinstance(row.get("game"), dict) else {}
            start = live_game_pollers.listed_start("tennis", game, scan)
            if start is None:
                raw = row.get("listed_start") or row.get("start") or ""
                start = price_memory.parse_time(str(raw)) if raw else None
            if start is not None and (
                moment < start - timedelta(minutes=15)
                or moment >= start + timedelta(hours=hours)
            ):
                continue
            title = str(row.get("title") or "") or live_game_pollers.fallback_title(game, scan)
            key = str(row.get("key") or "") or live_game_pollers.game_key("tennis", game, scan)
            rows.append({
                "key": key,
                "sport": "tennis",
                "game": game,
                "title": title,
                "start": start.isoformat() if start is not None else str(row.get("start") or ""),
                "listed_start": (
                    start.isoformat()
                    if start is not None
                    else str(row.get("listed_start") or row.get("start") or "")
                ),
            })
        return rows
    else:
        skip_tennis = True
    for sport, game in live_game_pollers.iter_matched(scan):
        sport_l = str(sport).lower()
        if want_sport and sport_l != want_sport:
            continue
        if skip_tennis and sport_l == "tennis":
            continue
        hours = live_game_pollers.LIVE_HOURS.get(sport, 4.0)
        start = live_game_pollers.listed_start(sport, game, scan)
        if start is None:
            continue
        if moment < start - timedelta(minutes=15) or moment >= start + timedelta(hours=hours):
            continue
        title = live_game_pollers.fallback_title(game, scan)
        if skip_nfl and is_nfl_sport(sport):
            skipped_nfl.append(title)
            continue
        key = live_game_pollers.game_key(sport, game, scan)
        rows.append({
            "key": key,
            "sport": sport,
            "game": game,
            "title": title,
            "start": start.isoformat(),
            "listed_start": start.isoformat(),
        })
    if skip_nfl:
        _log_d_nfl_skip(skipped_nfl)
    return rows


def note_settled_holds(sid: str, status: dict, snapshot=None) -> int:
    """Mark filled/holding C/D/E tickets settled when the venue is final. Does not sell.

    Empty Polymarket positions GET while the market is still OPEN keeps the hold.
    Qty truth is fill-history on last_order / confirm.
    """
    if not isinstance(status, dict):
        return 0
    try:
        import open_count_sync
        import orders_performance_refresh
    except Exception:
        return 0
    snap = snapshot
    if snap is None:
        try:
            snap = open_count_sync.venue_snapshot()
        except Exception:
            return 0
    n = 0
    for row in status.get("matches") or []:
        if not isinstance(row, dict):
            continue
        stage = str(row.get("stage") or "")
        if stage not in {"filled", "holding", "open"}:
            continue
        try:
            item = open_count_sync.classify_match(sid, row, snap)
        except Exception:
            continue
        if not orders_performance_refresh.classified_is_venue_close(item, snapshot=snap):
            continue
        row["stage"] = "settled"
        row["settled_at"] = iso_now()
        row["note"] = str(item.get("why") or "venue settled/expired/final/void")
        if orders_performance_refresh.maybe_after_classified(item, snapshot=snap):
            n += 1
    return n


def tick(sid: str) -> dict:
    cfg = systems.get_system(sid)
    status = load_status(sid)
    status["enabled"] = bool(cfg.on)
    status["max_open"] = int(cfg.max_open)
    status["pid"] = os.getpid()
    if not cfg.on:
        status["note"] = f"{systems.DISPLAY[sid]} is off"
        save_status(sid, status)
        return status
    if sid == "spread_t0":
        status["d_skip_nfl_gathering"] = True
        status["note"] = "D on except NFL (d_skip_nfl_gathering)"
    scan = live_game_pollers.load_scan()
    live = slate_near_t0(scan, sid)
    for spec in live:
        title = str(spec.get("title") or "")
        key = str(spec.get("key") or "")
        if any(
            (
                (key and str(row.get("key") or "") == key)
                or same_game(str(row.get("game") or ""), title)
            )
            and str(row.get("stage") or "") not in {"waiting_t0"}
            for row in (status.get("matches") or [])
        ):
            continue
        try:
            consider_game(sid, scan, spec, status, cfg)
        except Exception as exc:
            log(sid, f"tick {title} {type(exc).__name__}")
            status["last_skip_reason"] = f"{title}: {type(exc).__name__}"
        if len(open_matches(status)) >= int(cfg.max_open):
            break
    try:
        note_settled_holds(sid, status)
    except Exception as exc:
        log(sid, f"settle note {type(exc).__name__}")
    save_status(sid, status)
    return status


def keep_running(sid: str) -> bool:
    return not STOP[sid].exists()


def loop(sid: str) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    _json_dump(PID_FILE[sid], {"pid": os.getpid(), "started_at": iso_now(), "system": sid})
    log(sid, f"{sid} start pid {os.getpid()}")
    if sid == "spread_t0":
        log(sid, f"{D_SKIP_NFL_TOKEN} NFL/pro football skipped until enough data; CFB and others stay on")
    while keep_running(sid):
        try:
            tick(sid)
        except KeyboardInterrupt:
            log(sid, "interrupted; continuing")
        except Exception as exc:
            log(sid, f"loop {type(exc).__name__}")
        slept = 0
        while slept < TICK_SEC and keep_running(sid):
            time.sleep(1)
            slept += 1
    log(sid, f"{sid} exit")
