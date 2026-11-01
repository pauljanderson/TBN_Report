"""Research only: list of lock-bot trades where we got both sides.

True lock = Yes on venue A + No on venue B (or opponent Yes on a 2-player
moneyline) for the same settlement, both legs venue-confirmed qty >= 1, not
flatten, not leftover-only, not a one-leg dump. P&L with fees.

Does not place, cancel, flatten, sell, or rest GTC. Does not start a second
live_strategy_b.py. Does not change live_lock_orders.py send logic.
Not gold. Not DailyRun.
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_lock_orders  # noqa: E402
import report_page_extras  # noqa: E402
from order_ledger import _load_jsonl, polymarket_fill  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, RAW  # noqa: E402
from write_orders_performance import (  # noqa: E402
    B_STEPS,
    C_STEPS,
    D_STEPS,
    INTENT_FULL_LOCK,
    INTENT_INCOMPLETE_LOCK,
    ORDERS,
    STOPPED,
    VENUE_FILL_PULL,
    assign_system,
    cluster_lock_attempts,
    complementary_legs,
    enrich_cluster,
    esc,
    fetch_kalshi_amounts,
    fetch_polymarket_positions,
    fill_cash_fee,
    GEMINI_PASTE,
    first_time,
    fmt_et,
    io_indexes,
    is_cfb_favorite_row,
    is_spread_t0_row,
    is_strategy_b_row,
    match_io,
    load_json,
    load_settlements,
    load_venue_fill_index,
    lock_realized,
    parse_dt,
    parse_key,
    public_http_line,
    qty_is_fill,
    score_cluster,
    table,
    ticker_result,
    venue_fills_for_leg,
    venue_holds_leg,
    venue_index_of,
)

GAME_NEEDLES = (
    ("mtufiu", "Middle Tennessee vs FIU"),
    ("mtn-fiu", "Middle Tennessee vs FIU"),
    ("dodcec", "Dodig vs Cecchinato"),
    ("matdod", "Dodig vs Cecchinato"),
    ("gofber", "Goffin vs Bertola"),
    ("davgof", "Goffin vs Bertola"),
    ("oncstr", "Onclin vs Struff"),
    ("gauonc", "Onclin vs Struff"),
    ("ruzday", "Ruzic vs Day"),
    ("antruz", "Ruzic vs Day"),
    ("malmiy", "Maloney vs Miyoshi"),
    ("patmal", "Maloney vs Miyoshi"),
    ("smisun", "Smith vs Sun"),
    ("keesmi", "Smith vs Sun"),
    ("car-cgy", "Carolina vs Calgary"),
    ("tb-cle", "Tampa Bay vs Cleveland Game 5"),
)

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "lock_both_sides_20261024.html"
EXTRACT = RAW / "lock_both_sides_extract_20261024.json"
ONE = Decimal("1")
CENT = Decimal("0.01")
FOUR = Decimal("0.0001")
NET_MAX = live_lock_orders.NET_MAX
FLATTEN_STEPS = {"flatten", "extra-flatten"}
LOCK_SEND_STEPS = {"", "simultaneous", "websocket", "book", "watch"}
PERF_LINK = "lock_both_sides_20261024.html"
PERF_ONE_LINER = (
    "True both-sides locks only (Yes on one venue + No on the other, not leftover/flatten): "
    f'<a href="{PERF_LINK}">{PERF_LINK}</a>.'
)

ASKED = (
    "Show a list of lock bot trades where we HAVE been able to get both sides. "
    "For each: sport / venue / date time / outcome / profit. How frequently do we "
    "find one when we are looking (he knows lock is frequently turned off). "
    "A true lock = Yes on venue A + No on venue B (or economic twin: opponent Yes "
    "on 2-player ML) for the same settlement, both legs venue-confirmed qty >= 1, "
    "not flatten, not leftover, not one-leg dump. Net was <= NET_MAX 0.984 all-in "
    "at send. Primary P&L WITH fees. Outcome = won/lost/void/still open (both legs "
    "should resolve together; if not, flag mismatch). Do not include Moutet "
    "leftover+flatten, Alves flatten, Ribecai one-leg, etc. Those are A-system cash "
    "but not both-sides locks. If the performance page N=44 mixes them, split: "
    "true locks vs leftover/flatten. List every row (do not hide the small +1¢ hockey ones)."
)
PLAIN = (
    "The lock bot tries to buy Yes in one shop and No in another on the same result "
    "when the two tickets plus fees still cost 98.4 cents or less. If both fill, one "
    "side pays $1 and we keep the gap. This page is only those both-sides fills — not "
    "the times we dumped a one-sided ticket on the same shop (flatten), and not the "
    "times we still hold only one side (leftover). Lock is often off after a one-leg "
    "miss: new pairs stop, leftover watch can still hunt the missed hedge. Frequency "
    "while looking uses the hours new pairs were actually allowed, from the latch file "
    "and the supervisor log — we do not invent uptime."
)


def money4(value) -> str:
    if value is None or value == "":
        return ""
    try:
        number = Decimal(str(value))
    except Exception:
        return str(value)
    return format(number.quantize(FOUR, rounding=ROUND_HALF_UP), "f")


def money_signed(value) -> str:
    if value is None:
        return ""
    number = Decimal(str(value))
    sign = "" if number >= 0 else "-"
    return f"{sign}${abs(number).quantize(CENT, rounding=ROUND_HALF_UP)}"


def market_short(market: str) -> str:
    text = str(market or "").strip().lower()
    if text in {"moneyline", "ml", "match", "game", "winner"}:
        return "ML"
    if "spread" in text:
        return "spread"
    if text in {"total", "totals", "over", "under"}:
        return "total"
    return text or "ML"


def leg_is_flatten(leg: dict) -> bool:
    step = str(leg.get("step") or "").lower()
    if step in FLATTEN_STEPS:
        return True
    note = str(leg.get("note") or "").lower()
    return "flatten" in note and "watch" not in step


def leg_is_directional(leg: dict) -> bool:
    step = str(leg.get("step") or "").lower()
    return step in B_STEPS or step in C_STEPS or step in D_STEPS or step.startswith(("b-", "c-", "d-"))


def lock_pair_fills(cluster: dict) -> list[dict]:
    found = []
    for leg in cluster.get("fill_legs") or []:
        if not qty_is_fill(leg.get("qty")):
            continue
        if leg_is_flatten(leg) or leg_is_directional(leg):
            continue
        found.append(leg)
    return found


def venues_of(legs: list[dict]) -> set[str]:
    return {str(leg.get("venue") or "").strip().lower() for leg in legs if str(leg.get("venue") or "").strip()}


def same_venue_yes_no(legs: list[dict]) -> bool:
    if len(legs) < 2:
        return False
    venues = venues_of(legs)
    insts = {str(leg.get("instrument") or "") for leg in legs}
    books = {str(leg.get("side") or "").lower() for leg in legs}
    return len(venues) == 1 and len(insts) == 1 and "yes" in books and "no" in books


def pick_two_lock_legs(legs: list[dict]) -> list[dict]:
    """Prefer one fill per venue that still form a complementary pair."""
    if len(legs) <= 2:
        return list(legs)
    by_venue: dict[str, list[dict]] = defaultdict(list)
    for leg in legs:
        by_venue[str(leg.get("venue") or "").lower()].append(leg)
    if len(by_venue) < 2:
        return list(legs[:2])
    venues = list(by_venue)
    for i, left_v in enumerate(venues):
        for right_v in venues[i + 1 :]:
            for left in by_venue[left_v]:
                for right in by_venue[right_v]:
                    if complementary_legs([left, right]):
                        return [left, right]
    first = [by_venue[v][0] for v in venues[:2]]
    return first


def all_in(legs: list[dict]) -> tuple[Decimal, Decimal, Decimal]:
    cost = Decimal("0")
    fees = Decimal("0")
    for leg in legs:
        qty = Decimal(str(leg.get("qty") or 0))
        cash = Decimal(str(leg.get("cash") or 0))
        fee = Decimal(str(leg.get("fee") or 0))
        cost += cash * qty
        fees += fee
    return cost + fees, cost, fees


def leg_when(leg: dict, cluster: dict) -> datetime | None:
    return parse_dt(leg.get("sent_at")) or first_time(cluster)


def leg_phrase(leg: dict, game: str = "", leftover_sides: dict | None = None) -> str:
    venue = str(leg.get("venue") or "?").capitalize()
    book = display_side(leg, game, leftover_sides)
    player = display_player(leg, game, leftover_sides)
    if not player:
        inst = str(leg.get("instrument") or "")
        player = inst[:28] + ("…" if len(inst) > 28 else "")
    px = money4(leg.get("cash") if leg.get("cash") not in (None, "") else leg.get("limit"))
    return f"{venue} {book.capitalize()} {player} @ {px}"


def venue_confirmed(leg: dict, fills_index: dict, venue_index: dict) -> str:
    qty = Decimal(str(leg.get("qty") or 0))
    tape = qty_is_fill(qty)
    hist = venue_fills_for_leg(leg, fills_index)
    hist_ok = False
    for row in hist:
        if qty_is_fill(row.get("qty") or row.get("count") or row.get("size") or 0):
            hist_ok = True
            break
    live = venue_holds_leg(leg, venue_index)
    venue = str(leg.get("venue") or "").lower()
    if venue == "gemini":
        if tape:
            return "order_io qty>=1 (Gemini has no positions helper; Paul paste if listed)"
        return "not confirmed qty>=1"
    parts = []
    if tape:
        parts.append("order_io qty>=1")
    if hist_ok:
        parts.append("venue fill history")
    if live:
        parts.append("live position")
    if not parts:
        return "not confirmed qty>=1"
    return " + ".join(parts)


def how_both_sides(cluster: dict, legs: list[dict], leftover_fills: set[str]) -> str:
    steps = {str(leg.get("step") or "").lower() for leg in legs}
    game = str(cluster.get("game") or "")
    if "watch" in steps or game in leftover_fills:
        return "leftover hedge (other venue filled after a one-leg)"
    if cluster.get("flatten_filled"):
        return "two-venue complementary fills (performance page also tagged flatten)"
    return "dual send both filled"


def lock_outcome(
    *,
    cluster: dict,
    legs: list[dict],
    settlements: list[dict],
    venue_index: dict,
    net: Decimal,
    leftover_sides: dict | None = None,
) -> tuple[str, Decimal | None, str]:
    """Return (outcome, profit_with_fees, note)."""
    held = [leg for leg in legs if venue_holds_leg(leg, venue_index)]
    results = [ticker_result(settlements, str(leg.get("instrument") or "")) for leg in legs]
    known = [row for row in results if row in {"yes", "no"}]
    gemini_settled = bool(cluster.get("gemini_settled") or cluster.get("paul_settled"))
    note_bits = []
    if held:
        return "still open", None, "At least one lock leg is still on a live venue position list."
    if cluster.get("void"):
        return "void", Decimal("0"), "Tape marked void (not a venue holding)."
    if len(known) == 1:
        return "mismatch", None, "Only one lock ticker has a settlement result; both legs should resolve together."
    if len(known) == 2:
        books = [str(leg.get("side") or "").lower() for leg in legs]
        pays = 0
        for book, result in zip(books, results):
            if (book == "yes" and result == "yes") or (book == "no" and result == "no"):
                pays += 1
        profit = lock_realized(legs)
        if pays == 1:
            return "won", profit, "One ticker paid $1, the other $0 — the lock identity."
        if pays == 0:
            return "lost", profit, "Neither lock ticker paid. Flag: both legs should not lose together."
        return "mismatch", profit, "Both lock tickers paid. Flag: they should not win together."
    if gemini_settled and not held:
        profit = lock_realized(legs)
        return "won", profit, "Gemini paste resolved; lock P&L is $1 minus both fill prices and fees, not the one-leg Gemini arithmetic."
    game = str(cluster.get("game") or "")
    stamped = []
    for leg in legs:
        row = dict(leg)
        row["side"] = display_side(row, game, leftover_sides)
        who = display_player(row, game, leftover_sides)
        if who:
            row["player"] = who
        stamped.append(row)
    if not held and complementary_legs(stamped):
        profit = lock_realized(legs)
        note_bits.append(
            "Not on a live Kalshi/Poly book now. Match winner is not in the settlement cache, "
            "so this treats a complementary lock as resolved (one $1, one $0) with no void. "
            "If a venue voided one leg, this would be wrong — flag unknown void."
        )
        return "won", profit, " ".join(note_bits)
    return "still open", None, "No settlement ticker result and no live position; left open/unknown."


def is_true_lock(cluster: dict, legs: list[dict], leftover_sides: dict | None = None) -> tuple[bool, str]:
    if cluster.get("is_b") or str(cluster.get("system_letter") or "") == "B":
        return False, "tennis crossover, not lock-bot"
    letter = str(cluster.get("system_letter") or "")
    if letter in {"C", "D"}:
        return False, "directional C/D, not a lock"
    if len(legs) < 2:
        return False, "fewer than 2 non-flatten fills"
    if len(venues_of(legs)) < 2:
        return False, "both fills same venue (flatten / one shop), not Yes on A + No on B"
    if same_venue_yes_no(legs):
        return False, "same-instrument Yes+No (flatten)"
    game = str(cluster.get("game") or "")
    stamped = []
    for leg in legs:
        row = dict(leg)
        row["side"] = display_side(row, game, leftover_sides)
        who = display_player(row, game, leftover_sides)
        if who:
            row["player"] = who
        stamped.append(row)
    pair = pick_two_lock_legs(stamped)
    if len(pair) < 2 or not complementary_legs(pair):
        return False, "fills are not complementary (not Yes+No same settlement / not opponent Yes)"
    for leg in pair:
        if not qty_is_fill(leg.get("qty")):
            return False, "a lock leg has qty < 1"
    return True, "two-venue complementary qty>=1"


def game_of(cluster: dict, leg: dict | None = None) -> str:
    game = str(cluster.get("game") or "").strip()
    if game:
        return game
    blob = " ".join(
        str(part or "")
        for part in (
            cluster.get("key"),
            cluster.get("side"),
            (leg or {}).get("instrument"),
            (leg or {}).get("player"),
        )
    ).lower()
    for needle, title in GAME_NEEDLES:
        if needle in blob:
            return title
    return ""


def attach_orphan_watch_fills(clusters: list[dict], orders: list[dict], by_id: dict, io_list: list[dict]) -> None:
    """Leftover-watch sends can land after a later claim flushed the cluster.

    Attach qty>=1 lock watch/simultaneous fills that are missing from fill_legs.
    Does not place an order.
    """
    seen: set[tuple] = set()
    by_key: dict[str, dict] = {}
    for cluster in clusters:
        key = str(cluster.get("key") or (cluster.get("claim") or {}).get("bet_key") or "")
        if key:
            prev = by_key.get(key)
            n_here = int(cluster.get("n_fill_legs") or 0)
            n_prev = int((prev or {}).get("n_fill_legs") or 0)
            if prev is None or n_here > n_prev:
                by_key[key] = cluster
        for leg in list(cluster.get("legs") or []) + list(cluster.get("fill_legs") or []):
            seen.add((
                str(leg.get("venue") or "").lower(),
                str(leg.get("instrument") or ""),
                str(leg.get("order_id") or ""),
            ))
    used: set[str] = set()
    for row in orders:
        if is_strategy_b_row(row) or is_cfb_favorite_row(row) or is_spread_t0_row(row):
            continue
        if str(row.get("event") or "") != "sent":
            continue
        step = str(row.get("step") or "").lower()
        if step not in LOCK_SEND_STEPS:
            continue
        key = str(row.get("bet_key") or "")
        venue = str(row.get("venue") or "").lower()
        inst = str(row.get("instrument") or "")
        oid = str(row.get("order_id") or "")
        token = (venue, inst, oid)
        if token in seen:
            continue
        cluster = by_key.get(key)
        if cluster is None:
            info = parse_key(key)
            game = ""
            blob = (key + " " + inst).lower()
            for needle, title in GAME_NEEDLES:
                if needle in blob:
                    game = title
                    break
            cluster = {
                "claim": row,
                "events": [],
                "kind": "lock",
                "game": game or str(row.get("game") or ""),
                "sport": str(info.get("sport") or row.get("sport") or ""),
                "market": str(info.get("market_type") or "moneyline"),
                "side": str(info.get("side_key") or ""),
                "is_b": False,
                "posted": True,
                "legs": [],
                "fill_legs": [],
                "key": key,
            }
            clusters.append(cluster)
            if key:
                by_key[key] = cluster
        io_row = match_io(row, cluster.get("claim") or row, by_id, io_list, used)
        cash, fee, qty = fill_cash_fee(row, io_row)
        if not qty_is_fill(qty):
            continue
        book = str(row.get("side") or "")
        player = str(row.get("side_label") or row.get("player") or cluster.get("side") or "")
        outcome_name = ""
        io_intent = ""
        if io_row and venue == "polymarket":
            payload = io_row.get("response") if isinstance(io_row.get("response"), dict) else {}
            poly = polymarket_fill(payload)
            outcome_name = str(poly.get("outcome_name") or "")
            io_intent = str(poly.get("intent") or "")
            if poly.get("side"):
                book = str(poly.get("side"))
            if outcome_name:
                player = outcome_name
        elif io_row and venue == "kalshi":
            req = io_row.get("request") if isinstance(io_row.get("request"), dict) else {}
            req_side = str(req.get("side") or req.get("action") or "").lower()
            if req_side in {"ask", "sell", "no"}:
                book = "no"
            elif req_side in {"bid", "buy", "yes"}:
                book = "yes"
        leg = {
            "venue": venue,
            "instrument": inst,
            "side": book,
            "player": player,
            "outcome_name": outcome_name,
            "io_intent": io_intent,
            "limit": row.get("limit_price"),
            "cash": cash,
            "fee": fee,
            "qty": qty,
            "http": row.get("http_status"),
            "http_line": public_http_line(row, io_row),
            "step": str(row.get("step") or ""),
            "order_id": oid,
            "sent_at": row.get("sent_at"),
            "posted": True,
            "has_io": io_row is not None,
        }
        cluster.setdefault("legs", []).append(leg)
        cluster.setdefault("fill_legs", []).append(leg)
        cluster["n_fill_legs"] = len(cluster.get("fill_legs") or [])
        cluster["posted"] = True
        seen.add(token)


def leftover_complete_games() -> set[str]:
    found: set[str] = set()
    path = RAW / "leftover_watch_stats.jsonl"
    if path.is_file():
        for row in _load_jsonl(path):
            if str(row.get("event") or "") == "ioc_filled":
                game = str(row.get("game") or "").strip()
                if game:
                    found.add(game)
    log = RAW / "live_supervisor.log"
    if log.is_file():
        with log.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if "order watch complete" in line.lower() and "orders on" in line.lower():
                    match = re.search(r"order watch complete (.+?); orders on", line, flags=re.I)
                    if match:
                        found.add(match.group(1).strip())
    return found


def leftover_ioc_sides() -> dict[str, dict]:
    """game -> last leftover IOC fill (venue/side/ask) from leftover_watch_stats."""
    found: dict[str, dict] = {}
    path = RAW / "leftover_watch_stats.jsonl"
    if not path.is_file():
        return found
    for row in _load_jsonl(path):
        if str(row.get("event") or "") != "ioc_filled":
            continue
        game = str(row.get("game") or "").strip()
        if not game:
            continue
        found[game] = {
            "venue": str(row.get("missed_venue") or row.get("venue") or "").lower(),
            "side": str(row.get("missed_side") or "").lower(),
            "ask": row.get("ask"),
            "instrument": str(row.get("missed_instrument") or row.get("instrument") or ""),
        }
    return found


def kalshi_ticker_who(instrument: str) -> str:
    inst = str(instrument or "")
    if "GOFBER-BER" in inst:
        return "Remy Bertola"
    if "GOFBER-GOF" in inst:
        return "David Goffin"
    if "ONCSTR-STR" in inst:
        return "Jan-Lennard Struff"
    if "ONCSTR-ONC" in inst:
        return "Gauthier Onclin"
    if "DODCEC-DOD" in inst:
        return "Matej Dodig"
    if "RUZDAY-DAY" in inst:
        return "Kayla Day"
    if "RUZDAY-RUZ" in inst:
        return "Antonia Ruzic"
    if "MALMIY-MAL" in inst:
        return "Patrick Maloney"
    if "SMISUN-SUN" in inst:
        return "Fajing Sun"
    return ""


def display_player(leg: dict, game: str = "", leftover_sides: dict | None = None) -> str:
    venue = str(leg.get("venue") or "").lower()
    outcome = str(leg.get("outcome_name") or "").strip()
    intent = str(leg.get("io_intent") or "")
    if venue == "polymarket" and outcome:
        return outcome
    who = kalshi_ticker_who(str(leg.get("instrument") or ""))
    if who:
        return who
    player = str(leg.get("player") or "").strip()
    if leftover_sides and game in leftover_sides:
        info = leftover_sides[game]
        if venue == info.get("venue") and info.get("side"):
            return player or who or outcome
    return player or outcome or str(leg.get("instrument") or "")[:28]


def display_side(leg: dict, game: str = "", leftover_sides: dict | None = None) -> str:
    venue = str(leg.get("venue") or "").lower()
    book = str(leg.get("side") or "").lower()
    if leftover_sides and game in leftover_sides:
        info = leftover_sides[game]
        inst = str(leg.get("instrument") or "")
        if venue == info.get("venue") and info.get("side"):
            if not info.get("instrument") or info["instrument"] in inst or inst in info["instrument"]:
                if str(leg.get("step") or "") == "watch":
                    return info["side"]
    if venue == "polymarket" and str(leg.get("io_intent") or "") == "ORDER_INTENT_BUY_LONG":
        return "yes"
    if venue == "polymarket" and str(leg.get("io_intent") or "") == "ORDER_INTENT_BUY_SHORT":
        return "no"
    return book or "?"


def parse_log_ts(line: str) -> datetime | None:
    token = line.split(" ", 1)[0].strip()
    return parse_dt(token)


def supervisor_markers() -> list[tuple[datetime, str, str]]:
    path = RAW / "live_supervisor.log"
    found: list[tuple[datetime, str, str]] = []
    if not path.is_file():
        return found
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stamp = parse_log_ts(line)
            if stamp is None:
                continue
            low = line.lower()
            text = line.strip()[:220]
            if "placing orders is off" in low:
                found.append((stamp, "off_bats", text))
            elif "order skipped; a missed pair stopped" in low:
                found.append((stamp, "off_latch", text))
            elif "order watch complete" in low and "orders on" in low:
                found.append((stamp, "on_leftover_complete", text))
            elif "latch stays on" in low:
                found.append((stamp, "off_watch_stop", text))
    return found


def reconstruct_on_windows(
    *,
    inception: datetime,
    now: datetime,
    markers: list[tuple[datetime, str, str]],
    dual_sends: list[datetime],
    stopped_at: datetime | None,
    stopped_now: bool,
) -> tuple[list[tuple[datetime, datetime, str]], str]:
    """Best-effort ON intervals for new lock pairs. Latch timestamps only; say so."""
    events: list[tuple[datetime, str, str]] = list(markers)
    for stamp in dual_sends:
        events.append((stamp, "on_dual_send", "dual lock send on tape"))
    if stopped_at:
        events.append((stopped_at, "off_stopped_file", "orders_stopped.json written"))
    events.sort(key=lambda row: row[0])
    # Seed: first evidence. Supervisor placing_off starts 18 Oct; first dual send is later.
    on_ranges: list[tuple[datetime, datetime, str]] = []
    state = "unknown"
    state_since = inception
    note = (
        "ON/OFF is reconstructed from live_supervisor.log ('placing orders is off', "
        "'missed pair stopped further orders', 'order watch complete … orders on', "
        "'latch stays on'), leftover dual-sends on orders.jsonl, leftover_watch ioc_filled, "
        "and the current orders_stopped.json timestamp. There is no complete --lock off "
        "diary (systems.json is a snapshot). Gaps with only latch-skip spam are treated as OFF."
    )

    def close(until: datetime, why: str) -> None:
        nonlocal state, state_since
        if state == "on" and until > state_since:
            on_ranges.append((state_since, until, why))
        state = "off"
        state_since = until

    def open_on(when: datetime, why: str) -> None:
        nonlocal state, state_since
        if state == "on":
            return
        state = "on"
        state_since = when

    # Before first marker, do not invent ON.
    for stamp, kind, _text in events:
        if stamp < inception or stamp > now:
            continue
        if kind.startswith("off"):
            close(stamp, kind)
        elif kind.startswith("on"):
            open_on(stamp, kind)
    if state == "on":
        if stopped_now and stopped_at and stopped_at <= now:
            close(stopped_at if stopped_at >= state_since else now, "off_stopped_file")
        else:
            close(now, "still_on_at_pull")
    elif stopped_now and stopped_at and on_ranges:
        last_on_end = on_ranges[-1][1]
        if stopped_at > last_on_end:
            pass
    merged: list[tuple[datetime, datetime, str]] = []
    for start, end, why in on_ranges:
        if end <= start:
            continue
        if merged and start <= merged[-1][1] + timedelta(seconds=2):
            prev = merged[-1]
            merged[-1] = (prev[0], max(prev[1], end), prev[2] + "," + why)
        else:
            merged.append((start, end, why))
    return merged, note


def hours_of(ranges: list[tuple[datetime, datetime, str]]) -> Decimal:
    total = Decimal("0")
    for start, end, _why in ranges:
        total += Decimal(str((end - start).total_seconds())) / Decimal("3600")
    return total


def cluster_when_fill(cluster: dict, legs: list[dict]) -> datetime | None:
    times = [leg_when(leg, cluster) for leg in legs]
    times = [row for row in times if row]
    if times:
        return min(times)
    return first_time(cluster)


def json_safe(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def load_stopped() -> tuple[bool, datetime | None, str]:
    raw = load_json(STOPPED)
    if not isinstance(raw, dict):
        return False, None, "orders_stopped.json absent (latch off now)"
    if not raw.get("stopped"):
        return False, parse_dt(raw.get("timestamp")), str(raw.get("reason") or "")
    return True, parse_dt(raw.get("timestamp")), str(raw.get("reason") or "one leg filled and the other missed")


def dual_lock_sends(lock_clusters: list[dict]) -> list[dict]:
    found = []
    for cluster in lock_clusters:
        if cluster.get("is_b"):
            continue
        legs = [
            leg
            for leg in (cluster.get("legs") or [])
            if str(leg.get("step") or "").lower() in LOCK_SEND_STEPS
            and not leg_is_flatten(leg)
            and not leg_is_directional(leg)
        ]
        venues = venues_of(legs)
        if len(legs) < 2 or len(venues) < 2:
            continue
        when = first_time(cluster) or cluster_when_fill(cluster, legs)
        found.append({
            "game": cluster.get("game"),
            "sport": cluster.get("sport"),
            "when": when,
            "n_legs": len(legs),
            "venues": sorted(venues),
            "n_fill": len(lock_pair_fills(cluster)),
        })
    return found


def in_on_window(stamp: datetime | None, windows: list[tuple[datetime, datetime, str]]) -> bool:
    if stamp is None:
        return False
    for start, end, _why in windows:
        if start <= stamp <= end:
            return True
    return False


def contrast_row(cluster: dict, why: str) -> dict:
    fills = [leg for leg in (cluster.get("fill_legs") or []) if qty_is_fill(leg.get("qty"))]
    return {
        "game": cluster.get("game") or "",
        "sport": cluster.get("sport") or "",
        "when": fmt_et(first_time(cluster)),
        "role": cluster.get("system_role") or "",
        "result": cluster.get("result") or "",
        "n_fill": len(fills),
        "venues": ", ".join(sorted(venues_of(fills))) if fills else "",
        "realized": money_signed(cluster.get("realized")),
        "why": why,
    }


def make_true_row(
    cluster: dict,
    pair: list[dict],
    *,
    leftover_games: set[str],
    leftover_sides: dict,
    settlements: list[dict],
    venue_index: dict,
    fills_index: dict,
) -> dict:
    pair = list(pair)
    pair.sort(key=lambda leg: (leg_when(leg, cluster) or datetime.max.replace(tzinfo=ET), str(leg.get("venue") or "")))
    net, _gross, fees = all_in(pair)
    when = cluster_when_fill(cluster, pair)
    outcome, profit, outcome_note = lock_outcome(
        cluster=cluster,
        legs=pair,
        settlements=settlements,
        venue_index=venue_index,
        net=net,
        leftover_sides=leftover_sides,
    )
    game = str(cluster.get("game") or "")
    conf = [venue_confirmed(leg, fills_index, venue_index) for leg in pair]
    return {
        "when": when,
        "when_et": fmt_et(when),
        "sport": cluster.get("sport") or "",
        "market": market_short(cluster.get("market") or ""),
        "game": game,
        "leg1": pair[0],
        "leg2": pair[1],
        "leg1_text": leg_phrase(pair[0], game, leftover_sides),
        "leg2_text": leg_phrase(pair[1], game, leftover_sides),
        "net": net,
        "fees": fees,
        "outcome": outcome,
        "profit": profit,
        "still_open": "yes" if outcome == "still open" else "no",
        "how": how_both_sides(cluster, pair, leftover_games),
        "over_cap": net > NET_MAX,
        "confirm1": conf[0],
        "confirm2": conf[1],
        "outcome_note": outcome_note,
        "mismatch": outcome == "mismatch",
    }


def pair_key(game: str, pair: list[dict], when: datetime | None) -> tuple:
    insts = tuple(sorted(str(leg.get("instrument") or "") for leg in pair))
    return (game, insts, fmt_et(when))


def build_true_rows(
    clusters: list[dict],
    *,
    leftover_games: set[str],
    leftover_sides: dict,
    settlements: list[dict],
    venue_index: dict,
    fills_index: dict,
) -> tuple[list[dict], list[dict]]:
    true_rows: list[dict] = []
    contrast: list[dict] = []
    seen: set[tuple] = set()
    used_ids: set[int] = set()
    for cluster in clusters:
        assign_system(cluster)
        fills = lock_pair_fills(cluster)
        ok, why_not = is_true_lock(cluster, fills, leftover_sides)
        if not ok:
            continue
        pair = pick_two_lock_legs(fills)
        row = make_true_row(
            cluster,
            pair,
            leftover_games=leftover_games,
            leftover_sides=leftover_sides,
            settlements=settlements,
            venue_index=venue_index,
            fills_index=fills_index,
        )
        key = pair_key(row["game"], pair, row["when"])
        if key in seen:
            continue
        seen.add(key)
        used_ids.add(id(cluster))
        true_rows.append(row)

    # Leftover hedge can land on a later claim than the one-leg. Pool A fills by game.
    by_game: dict[str, list[tuple[dict, dict]]] = defaultdict(list)
    for cluster in clusters:
        if str(cluster.get("system_letter") or "") != "A":
            continue
        for leg in lock_pair_fills(cluster):
            game = game_of(cluster, leg)
            if not game:
                continue
            by_game[game].append((cluster, leg))
    for game, items in by_game.items():
        legs = [leg for _c, leg in items]
        ok, _why = is_true_lock({"system_letter": "A", "game": game, "is_b": False}, legs, leftover_sides)
        if not ok:
            continue
        pair = pick_two_lock_legs(legs)
        insts = {str(leg.get("instrument") or "") for leg in pair}
        already = any(
            str(row.get("game") or "") == game
            and {str(row["leg1"].get("instrument") or ""), str(row["leg2"].get("instrument") or "")} == insts
            for row in true_rows
        )
        if already:
            continue
        cluster = next((c for c, item_leg in items if any(item_leg is leg for leg in pair)), items[0][0])
        named = dict(cluster)
        named["game"] = game
        if not named.get("sport"):
            named["sport"] = "tennis"
        if not named.get("market"):
            named["market"] = "moneyline"
        row = make_true_row(
            named,
            pair,
            leftover_games=leftover_games | {game},
            leftover_sides=leftover_sides,
            settlements=settlements,
            venue_index=venue_index,
            fills_index=fills_index,
        )
        key = pair_key(row["game"], pair, row["when"])
        if key in seen:
            continue
        seen.add(key)
        used_ids.add(id(cluster))
        true_rows.append(row)

    for cluster in clusters:
        if id(cluster) in used_ids:
            continue
        n_fill = int(cluster.get("n_fill_legs") or 0)
        if n_fill <= 0:
            continue
        if str(cluster.get("system_letter") or "") != "A":
            continue
        fills = lock_pair_fills(cluster)
        _ok, why_not = is_true_lock(cluster, fills)
        contrast.append(contrast_row(cluster, why_not))

    true_games = {str(row.get("game") or "").lower() for row in true_rows}
    for row in GEMINI_PASTE:
        game = str(row.get("game") or "")
        key = game.lower()
        if "middle tennessee" in key:
            continue
        if any(key.startswith(g) or g.startswith(key[:18]) for g in true_games if g):
            continue
        sport = "college football" if "NCAAF" in str(row.get("instrument") or "") else (
            "pro hockey" if "NHL" in str(row.get("instrument") or "") else "pro baseball"
        )
        paste = {
            "when": "",
            "sport": sport,
            "game": game,
            "role": "Gemini paste one-leg",
            "result": str(row.get("arithmetic") or "resolved Gemini Yes"),
            "n_fill": 1,
            "venues": "gemini",
            "realized": money_signed(row.get("pnl")),
            "why": "Gemini Yes only (Paul paste). No second venue qty>=1, so not a both-sides lock. Listed so the +1¢ hockey / +3¢ baseball tickets are not hidden.",
        }
        hit = next((c for c in contrast if str(c.get("game") or "").lower() == key), None)
        if hit:
            hit["role"] = paste["role"]
            hit["result"] = paste["result"]
            hit["realized"] = paste["realized"]
            hit["why"] = paste["why"]
            continue
        contrast.append(paste)
    true_rows.sort(key=lambda row: row["when"] or datetime.min.replace(tzinfo=ET))
    return true_rows, contrast


def write_page(
    *,
    true_rows: list[dict],
    contrast: list[dict],
    freq: dict,
    windows: list[tuple[datetime, datetime, str]],
    window_note: str,
    stopped: dict,
    venue_note: str,
    now: datetime,
) -> str:
    n = len(true_rows)
    wins = sum(1 for row in true_rows if row["outcome"] == "won")
    lost = sum(1 for row in true_rows if row["outcome"] == "lost")
    voids = sum(1 for row in true_rows if row["outcome"] == "void")
    open_n = sum(1 for row in true_rows if row["outcome"] == "still open")
    mismatch_n = sum(1 for row in true_rows if row["mismatch"])
    closed_profit = sum((row["profit"] or Decimal("0") for row in true_rows if row["profit"] is not None), Decimal("0"))
    headline = (
        f"{n} true both-sides lock{'s' if n != 1 else ''}, {wins} won, "
        f"net {money_signed(closed_profit)} with fees"
        + (f", {open_n} still open" if open_n else "")
        + (f", {mismatch_n} settlement mismatch" if mismatch_n else "")
        + (f", {lost} lost" if lost else "")
        + (f", {voids} void" if voids else "")
        + "."
    )
    lock_headers = [
        ("Datetime ET", "date"),
        ("Sport", "text"),
        ("Market type", "text"),
        ("Game", "text"),
        ("Leg 1 venue/side/player/price", "text"),
        ("Leg 2 venue/side/player/price", "text"),
        ("All-in net", "num"),
        ("Fees", "num"),
        ("Outcome", "text"),
        ("Profit $", "num"),
        ("Still open?", "text"),
        ("How both sides", "text"),
        ("Venue confirm", "text"),
    ]
    lock_table_rows = []
    for row in true_rows:
        lock_table_rows.append([
            row["when_et"],
            row["sport"],
            row["market"],
            row["game"],
            row["leg1_text"],
            row["leg2_text"],
            money4(row["net"]),
            money4(row["fees"]),
            row["outcome"],
            money_signed(row["profit"]) if row["profit"] is not None else "",
            row["still_open"],
            row["how"],
            f"leg1 {row['confirm1']}; leg2 {row['confirm2']}",
        ])
    total = [
        "Total",
        "",
        "",
        f"N={n}",
        "",
        "",
        "",
        "",
        f"{wins} won",
        money_signed(closed_profit),
        f"{open_n} open",
        "",
        "",
    ]
    contrast_headers = [
        ("Datetime ET", "date"),
        ("Sport", "text"),
        ("Game", "text"),
        ("Performance role", "text"),
        ("Tape result", "text"),
        ("Fill legs", "num"),
        ("Venues", "text"),
        ("Recorded P&L $", "num"),
        ("Why not a true both-sides lock", "text"),
    ]
    contrast_rows = [
        [
            row["when"],
            row["sport"],
            row["game"],
            row["role"],
            row["result"],
            row["n_fill"],
            row["venues"],
            row["realized"],
            row["why"],
        ]
        for row in contrast
    ]
    win_headers = [
        ("ON from ET", "date"),
        ("ON until ET", "date"),
        ("Hours", "num"),
        ("Why this window closed / source", "text"),
    ]
    win_rows = [
        [fmt_et(start), fmt_et(end), money4(Decimal(str((end - start).total_seconds())) / Decimal("3600")), why]
        for start, end, why in windows
    ]
    freq_headers = [
        ("Slice", "text"),
        ("N / hours", "num"),
        ("Note", "text"),
    ]
    freq_rows = [
        ["Wall-clock since first lock tape row", freq["wall_hours"], freq["wall_note"]],
        ["Hours new lock pairs were allowed (reconstructed ON)", freq["on_hours"], freq["on_note"]],
        ["Calendar days with any reconstructed ON window", freq["on_days"], "A day counts if any ON interval overlaps that ET date."],
        ["Dual lock sends (two venues, not flatten) on the tape", freq["dual_sends"], "Passed the live send path far enough to post both IOCs."],
        ["Those dual sends during reconstructed ON", freq["dual_sends_on"], "Same count if every dual send is itself evidence of ON."],
        ["True both-fill on the first dual send (while looking)", freq["true_immediate"], "Both venues qty>=1 without leftover watch."],
        ["True both-fill via leftover hedge (latch on, leftover watch still looking)", freq["true_leftover"], "Not new-pair looking; missed-hedge looking."],
        ["True both-fill / dual send", freq["true_per_dual"], "Immediate both-fill divided by dual sends."],
        ["True both-fill per ON hour", freq["true_per_on_hour"], "Immediate both-fill / reconstructed ON hours."],
        ["True both-fill per ON calendar day", freq["true_per_on_day"], "Immediate both-fill / ON days."],
        ["Leftover both-fill / dual send", freq["left_per_dual"], "The five both-sides fills were leftover hedges, not first-send both-fills."],
        ["Leftover both-fill per ON calendar day", freq["left_per_on_day"], "Leftover watch still hunts after the latch, so leftover / ON hours is not a clean rate."],
        ["Legal-lock gate rows in considerations.json", freq["consider_note_n"], freq["consider_note"]],
    ]
    summaries = []
    for row in true_rows:
        profit = money_signed(row["profit"]) if row["profit"] is not None else "n/a"
        summaries.append(
            f"{row['when_et']}: {row['sport']} {row['game']} — {row['leg1_text']} + {row['leg2_text']}; "
            f"{row['outcome']} {profit} ({row['how']})."
        )
    summary_html = "<ol>" + "".join(f"<li>{esc(line)}</li>" for line in summaries) + "</ol>" if summaries else "<p>None.</p>"
    notes = []
    for row in true_rows:
        extra = []
        if row["over_cap"]:
            extra.append(f"all-in net {money4(row['net'])} is above live NET_MAX {NET_MAX} — listed anyway if both sides filled; flag the cap.")
        if row["outcome_note"]:
            extra.append(row["outcome_note"])
        if extra:
            notes.append(f"{row['game']} ({row['when_et']}): " + " ".join(extra))
    notes_html = "<ul>" + "".join(f"<li>{esc(line)}</li>" for line in notes) + "</ul>" if notes else "<p>No extra flags.</p>"
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Both-sides lock list — 24 Oct 2026</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 16px; color: #0f172a; background: #fff; line-height: 1.45; }}
h1, h2 {{ color: #1e293b; }}
.ask, .plain, .def, .hl, .warn {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 16px; margin: 12px 0; }}
.warn {{ background: #fff7ed; border-color: #fdba74; }}
.hl {{ background: #f0fdf4; border-color: #86efac; }}
.note {{ color: #475569; font-size: 14px; }}
code {{ font-size: 13px; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Both-sides lock list</h1>
<p class="note">Written {esc(now.strftime("%Y-%m-%d %H:%M ET"))}. Research only. Not gold. Not DailyRun. Does not place or sell tickets. Click column headers to sort.</p>

<div class="ask">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="plain">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="hl">
<h2>Headline</h2>
<p><strong>{esc(headline)}</strong> Live NET_MAX is {esc(format(NET_MAX, "f"))}. Every true both-sides row is in the table, including tiny hockey-sized cents if they actually had both venues. The performance page lock bucket that prints about −$2.43 mixes flatten/leftover A-system cash with these both-sides fills — split below.</p>
</div>

<h2>True both-sides locks</h2>
<p class="note">Yes on venue A + No on venue B, or opponent Yes on a two-player moneyline, same settlement, both legs qty ≥ 1. Flatten legs stripped. Leftover-only and one-leg dumps are out. Profit is $1 minus both fill prices and fees when the pair is treated as resolved. Click headers to sort. First column sticks.</p>
{table(lock_headers, lock_table_rows, total)}

<h2>Every row in one line</h2>
{summary_html}

<h2>Flags / settlement notes</h2>
{notes_html}

<h2>Frequency while looking</h2>
<p class="note">{esc(window_note)}</p>
<p class="note">Latch now: {esc(stopped["text"])}. Lock system switch in systems.json is a snapshot (on), not a history. Leftover watch can still hunt after the latch; that is not new-pair looking.</p>
{table(freq_headers, freq_rows)}

<h2>Reconstructed ON windows (new lock pairs allowed)</h2>
<p class="note">These are latch timestamps plus dual-send evidence. Do not read them as a continuous uptime clock. {esc(freq["on_source"])}</p>
{table(win_headers, win_rows if win_rows else [["", "", "", "No ON window could be closed from latch timestamps alone."]])}

<h2>Not both-sides — leftover / flatten / one-leg (the mix)</h2>
<p class="note">The performance page counted <code>n_true_locks</code> = {esc(freq["perf_true"])} plus <code>n_incomplete</code> = {esc(freq["perf_incomplete"])} filled lock clusters ({esc(freq["perf_mix"])} together). That 18 includes same-venue Yes+No flattens labeled “true lock / flatten”. The about −$2.43 realized lock bucket is that mix, not the both-sides table above. Moutet leftover+flatten, Alves flatten, Ribecai one-leg stay here. Gemini-only Carolina vs Calgary +1¢ and Tampa Bay vs Cleveland +3¢ are in this contrast too: one Gemini Yes, no second venue qty ≥ 1, so they are not both-sides locks even though they look like tiny lock nickels.</p>
{table(contrast_headers, contrast_rows)}

<div class="def">
<h2>Definition (strict)</h2>
<ul>
<li><strong>True lock:</strong> Yes on one venue and No on the other for the same settlement, or the two-player moneyline twin (Yes on opponent A + Yes on opponent B). Both legs order_io / venue qty ≥ 1.</li>
<li><strong>Not a true lock:</strong> flatten (same shop opposite), leftover-only (one fill), one-leg dump, Strategy B dual-Yes T0, C/D directional Yes, empty HTTP 201s, opportunities diary “both filled” without qty ≥ 1.</li>
<li><strong>All-in at send:</strong> live cap NET_MAX = {esc(format(NET_MAX, "f"))} after documented fees. Leftover hedges also send only at or under that cap.</li>
<li><strong>P&amp;L:</strong> with fees. A resolved lock should collect $1 on one ticket and $0 on the other. Gemini paste “+$0.56” on Middle Tennessee is the Gemini ticket alone; lock profit uses both legs.</li>
</ul>
</div>

<div class="warn">
<h2>Live knobs unchanged</h2>
<p>This job did not start a second <code>live_strategy_b.py</code>, did not edit <code>live_lock_orders.py</code>, did not sell tickets, and did not wire GTC. Hard-leg-first send logic is owned by another agent.</p>
<p class="note">{esc(venue_note)}</p>
</div>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    return report_page_extras.inject_report_page_extras(page)


def patch_orders_performance() -> str:
    path = STAMP / "orders_performance.html"
    if not path.is_file():
        return "orders_performance.html missing; skipped link"
    text = path.read_text(encoding="utf-8")
    if PERF_LINK in text:
        return "orders_performance.html already links this page"
    needle = '<div class="ask">'
    extra = f'<p class="note">{PERF_ONE_LINER}</p>\n'
    if needle not in text:
        return "orders_performance.html ask block not found; skipped link"
    path.write_text(text.replace(needle, extra + needle, 1), encoding="utf-8")
    return "added one-liner link on orders_performance.html"


def patch_orders_performance_generator() -> str:
    path = ROOT / "tools" / "write_orders_performance.py"
    text = path.read_text(encoding="utf-8")
    marker = "lock_both_sides_20261024.html"
    if marker in text:
        return "write_orders_performance.py already has the both-sides link"
    old = '<p class="note">Generated {esc(summary[\'generated_at\'])}. Tape through the local lock-bot + Strategy B files on this PC. Does not place or sell tickets. Click column headers to sort. {report_page_extras.SWIPE_NOTE_HTML.replace(\'<p class="swipe-note">\', \'\').replace(\'</p>\', \'\')}</p>'
    new = (
        old
        + "\n<p class=\"note\">True both-sides locks only (Yes on one venue + No on the other, not leftover/flatten): "
        + '<a href="lock_both_sides_20261024.html">lock_both_sides_20261024.html</a>.</p>'
    )
    if old not in text:
        return "write_orders_performance.py generated-note string drifted; skipped generator one-liner"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return "added one-liner to write_orders_performance.py (not the by-system block)"


def main() -> int:
    now = datetime.now(ET)
    print("loading orders.jsonl", flush=True)
    orders = _load_jsonl(ORDERS)
    print("loading order_io.jsonl (large)", flush=True)
    io_all = _load_jsonl(RAW / "order_io.jsonl")
    by_id, io_list = io_indexes(io_all)
    print(f"orders {len(orders)} io {len(io_list)}", flush=True)
    lock_raw = cluster_lock_attempts(orders)
    print(f"lock clusters {len(lock_raw)}", flush=True)
    print("fetching Kalshi + Polymarket US positions (existing helpers, amounts only)", flush=True)
    kalshi_pos = fetch_kalshi_amounts(force=True)
    poly_pos = fetch_polymarket_positions()
    venue_index = venue_index_of(kalshi_pos, poly_pos)
    print(
        f"kalshi http {kalshi_pos.get('http')} n={kalshi_pos.get('n')} "
        f"poly http {poly_pos.get('http')} n={poly_pos.get('n')}",
        flush=True,
    )
    settlements = load_settlements()
    fills_index = load_venue_fill_index()
    leftover_games = leftover_complete_games()
    leftover_sides = leftover_ioc_sides()
    lock_enriched = [enrich_cluster(cluster, by_id, io_list) for cluster in lock_raw]
    attach_orphan_watch_fills(lock_enriched, orders, by_id, io_list)
    scored = [score_cluster(cluster, settlements, venue_index) for cluster in lock_enriched if cluster.get("posted") or cluster.get("n_fill_legs")]
    for cluster in scored:
        assign_system(cluster)
    true_rows, contrast = build_true_rows(
        scored,
        leftover_games=leftover_games,
        leftover_sides=leftover_sides,
        settlements=settlements,
        venue_index=venue_index,
        fills_index=fills_index,
    )
    duals = dual_lock_sends(lock_enriched)
    dual_times = [row["when"] for row in duals if row.get("when")]
    first_times = [first_time(cluster) for cluster in lock_enriched]
    first_times = [row for row in first_times if row]
    inception = min(first_times) if first_times else datetime(2026, 10, 17, tzinfo=ET)
    stopped_now, stopped_at, stopped_reason = load_stopped()
    markers = supervisor_markers()
    windows, window_note = reconstruct_on_windows(
        inception=inception,
        now=now,
        markers=markers,
        dual_sends=dual_times,
        stopped_at=stopped_at,
        stopped_now=stopped_now,
    )
    on_hours = hours_of(windows)
    wall_hours = Decimal(str((now - inception).total_seconds())) / Decimal("3600")
    on_days = sorted({start.date() for start, _end, _why in windows} | {end.date() for _start, end, _why in windows})
    dual_on = sum(1 for stamp in dual_times if in_on_window(stamp, windows))
    true_leftover = sum(1 for row in true_rows if "leftover" in str(row.get("how") or "").lower())
    true_immediate = n = len(true_rows) - true_leftover
    n_dual = len(duals)
    consider = load_json(RAW / "considerations.json") or {}
    consider_rows = consider.get("rows") if isinstance(consider, dict) else consider
    if not isinstance(consider_rows, list):
        consider_rows = []
    consider_first = consider_rows[0].get("at") if consider_rows and isinstance(consider_rows[0], dict) else ""
    consider_last = consider_rows[-1].get("at") if consider_rows and isinstance(consider_rows[-1], dict) else ""
    perf_true = sum(1 for cluster in scored if cluster.get("intent") == INTENT_FULL_LOCK)
    perf_incomplete = sum(1 for cluster in scored if cluster.get("intent") == INTENT_INCOMPLETE_LOCK)
    true_per_dual = (Decimal(true_immediate) / Decimal(n_dual)) if n_dual else Decimal("0")
    true_per_on_hour = (Decimal(true_immediate) / on_hours) if on_hours else Decimal("0")
    true_per_on_day = (Decimal(true_immediate) / Decimal(len(on_days))) if on_days else Decimal("0")
    left_per_dual = (Decimal(true_leftover) / Decimal(n_dual)) if n_dual else Decimal("0")
    left_per_on_day = (Decimal(true_leftover) / Decimal(len(on_days))) if on_days else Decimal("0")
    freq = {
        "wall_hours": money4(wall_hours),
        "wall_note": f"First lock tape row {fmt_et(inception)} through {fmt_et(now)} (orders.jsonl). Stamp folder is 17 Oct; sends start later.",
        "on_hours": money4(on_hours),
        "on_note": "Sum of reconstructed ON windows below. Not a process-uptime probe.",
        "on_days": str(len(on_days)),
        "dual_sends": str(n_dual),
        "dual_sends_on": str(dual_on),
        "true_immediate": str(true_immediate),
        "true_leftover": str(true_leftover),
        "true_per_dual": money4(true_per_dual),
        "true_per_on_hour": money4(true_per_on_hour),
        "true_per_on_day": money4(true_per_on_day),
        "left_per_dual": money4(left_per_dual),
        "left_per_on_day": money4(left_per_on_day),
        "consider_note_n": str(len(consider_rows)),
        "consider_note": (
            f"considerations.json keeps the newest 500 looks only (now {consider_first} … {consider_last}). "
            "It is not a lifetime legal-lock diary. Dual sends on orders.jsonl are the send-gate count."
        ),
        "perf_true": str(perf_true),
        "perf_incomplete": str(perf_incomplete),
        "perf_mix": str(perf_true + perf_incomplete),
        "on_source": "live_supervisor.log + leftover_watch_stats.jsonl ioc_filled + orders_stopped.json + dual sends",
    }
    stopped = {
        "text": (
            f"{'set' if stopped_now else 'not set'} — {stopped_reason or 'n/a'} — {fmt_et(stopped_at) if stopped_at else 'no timestamp'}"
        )
    }
    venue_note = (
        f"Kalshi positions GET http={kalshi_pos.get('http')} n={kalshi_pos.get('n')} at {kalshi_pos.get('pulled_at')}. "
        f"Polymarket US positions GET http={poly_pos.get('http')} n={poly_pos.get('n')} at {poly_pos.get('pulled_at')}. "
        f"Venue fill-history index keys={len(fills_index)} from {VENUE_FILL_PULL.name} (on disk, no new fill-history API). "
        "Gemini has no positions helper; Paul paste covers three resolved Gemini tickets. Amounts only; no secrets."
    )
    html = write_page(
        true_rows=true_rows,
        contrast=contrast,
        freq=freq,
        windows=windows,
        window_note=window_note,
        stopped=stopped,
        venue_note=venue_note,
        now=now,
    )
    PAGE.write_text(html, encoding="utf-8")
    print(f"wrote {PAGE}", flush=True)
    extract = {
        "written_at": now.isoformat(),
        "n_true": len(true_rows),
        "true": json_safe(true_rows),
        "contrast_n": len(contrast),
        "freq": freq,
        "windows": json_safe(windows),
        "leftover_games": sorted(leftover_games),
        "stopped": {"now": stopped_now, "at": stopped_at.isoformat() if stopped_at else None, "reason": stopped_reason},
    }
    EXTRACT.write_text(json.dumps(extract, indent=2), encoding="utf-8")
    print(f"wrote {EXTRACT}", flush=True)
    print("patch", patch_orders_performance(), flush=True)
    print("gen", patch_orders_performance_generator(), flush=True)
    print(
        "true", len(true_rows),
        "immediate", true_immediate,
        "leftover", true_leftover,
        "profit", money_signed(sum((row["profit"] or Decimal("0") for row in true_rows if row["profit"] is not None), Decimal("0"))),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
