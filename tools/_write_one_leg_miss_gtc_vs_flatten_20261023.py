"""Research only: one-leg miss GTC vs flatten, with fees.

Reads lock-bot tape, order_io, venue fills, in-match ticks. Does not place,
cancel, or rest GTC. Cancel-on-resolve is still missing. Not gold. Not DailyRun.
"""
from __future__ import annotations

import html
import json
import re
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_lock_orders  # noqa: E402
import polymarket_us_live  # noqa: E402
import price_memory  # noqa: E402
import report_page_extras  # noqa: E402
from order_ledger import _io_instrument, _order_id_of  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, RAW  # noqa: E402
from write_orders_performance import (  # noqa: E402
    VENUE_FILL_PULL,
    ddec,
    fill_cash_fee,
    game_norm,
    last_name,
    load_json,
    load_venue_fill_index,
    opposite_pay,
    parse_dt,
    parse_key,
    qty_is_fill,
    same_player,
    sport_of,
    tennis_pay_key,
)

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "one_leg_miss_gtc_vs_flatten_20261023.html"
MOUTET_PAGE = STAMP / "moutet_paul_t0_20261023.html"
ONE = Decimal("1")
CENT = Decimal("0.01")
POLY_THETA = Decimal("0.0695")
RECOVERY_STEPS = {"websocket", "book", "midway", "recovery", "watch"}
ABSORB_LO = Decimal("0.05")
ABSORB_HI = Decimal("0.95")

ASKED = (
    "Poly Yes Moutet D988YSS011N2 HTTP 200, qty 0, then cancel 200. He asks: "
    "200 is success, shouldn't qty be 1? Confirm: not a fill. Poly 200 = HTTP OK; "
    "fill is cumQuantity. 0 + cancel = empty IOC. Kalshi No HTTP 201. He thinks "
    "201 = fail. Correct: Kalshi POST 201 Created is success. fill_count 1 = fill; "
    "fill_count 0 = empty IOC cancel (the old false-fill bug). This row filled qty 1 "
    "No at 84c (UI Sold Yes 16c). Flatten buy Yes 19c / 20.08c all-in. He thinks they "
    "spent 0.06c to get out of a 0.13c Poly bet that didn't match. Wrong economics: "
    "Poly 13c never filled. Leftover is Kalshi No 84c. Flatten buys Yes 19c to close "
    "that No. Round-trip 84+19+fees = $1.0503 → −5.03c. Not exiting a 13c ticket. "
    "He would rather GTC the missed Poly Yes at 13c than flatten. Ask: historically, "
    "if we miss one lock leg, what are the odds that missed leg comes back and would "
    "fill eventually?"
)


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def table(headers: list[tuple[str, str]], rows: list[list[str]], total: list[str] | None = None) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        cells = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr>{cells}</tr>")
    if total:
        cells = "".join(f"<td>{cell}</td>" for cell in total)
        body.append(f'<tr class="total-row">{cells}</tr>')
    return (
        '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def money4(value) -> str:
    if value is None or value == "":
        return "—"
    try:
        number = Decimal(str(value))
    except Exception:
        return esc(value)
    return format(number.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP), "f")


def cents(value) -> str:
    if value is None or value == "":
        return "—"
    try:
        number = Decimal(str(value))
    except Exception:
        return esc(value)
    return f"{format((number * Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), 'f')}¢"


def clock(value) -> str:
    stamp = parse_dt(value) if not isinstance(value, datetime) else value
    if stamp is None:
        return ""
    return stamp.astimezone(ET).strftime("%Y-%m-%d %H:%M:%S")


def venue_label(name: str | None) -> str:
    low = str(name or "").strip().lower()
    return {
        "kalshi": "Kalshi",
        "polymarket": "Polymarket US",
        "gemini": "Gemini",
        "novig": "Novig",
    }.get(low, str(name or ""))


def is_lock_bot(row: dict) -> bool:
    key = str(row.get("bet_key") or "")
    step = str(row.get("step") or "")
    if key.startswith("tennis-b") or row.get("_strategy_b"):
        return False
    if step.startswith("b-"):
        return False
    return True


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    if not path.is_file():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def event_time(row: dict, fallback: datetime | None = None) -> datetime | None:
    for key in ("sent_at", "quote_seen_at", "compared_at", "at", "timestamp", "ts", "time"):
        stamp = parse_dt(row.get(key))
        if stamp is not None:
            return stamp
    return fallback


def confirm_qty(sent: dict, io_row: dict | None, fills: list[dict]) -> Decimal:
    http = str(sent.get("http_status") or "").lower()
    confirmed = str(sent.get("confirm_known") or "").lower() in {"true", "1"}
    if http in {"pending", "0", ""} and not confirmed:
        return Decimal("0")
    if str(sent.get("confirm_known") or "").lower() in {"true", "1"}:
        qty = ddec(sent.get("confirm_qty"))
        if qty is not None:
            return qty
    if fills:
        best = Decimal("0")
        for row in fills:
            qty = ddec(row.get("qty") or row.get("count") or row.get("contracts"))
            if qty is not None and qty > best:
                best = qty
        if best > 0:
            return best
    if io_row:
        qty = live_lock_orders.filled_contracts(io_row.get("response"))
        if qty is not None:
            return qty
    tape = ddec(sent.get("tape_qty"))
    if tape is not None:
        return tape
    return Decimal("0")


def confirm_note_cash(sent: dict) -> Decimal | None:
    note = str(sent.get("confirm_note") or "")
    match = re.search(r"@\s*([0-9]*\.?[0-9]+)", note)
    if not match:
        return None
    return ddec(match.group(1))


def pay_cash(sent: dict, io_row: dict | None) -> Decimal | None:
    cash, _fee, qty = fill_cash_fee(sent, io_row)
    noted = confirm_note_cash(sent)
    quote = ddec(sent.get("quote_price"))
    limit = ddec(sent.get("limit_price"))
    side = str(sent.get("side") or "").lower()
    venue = str(sent.get("venue") or "").lower()
    if venue == "kalshi" and side == "no":
        if quote is not None and limit is not None and abs(quote + limit - ONE) <= Decimal("0.02"):
            return quote
        if quote is not None and Decimal("0") < quote < ONE:
            return quote
        if noted is not None and Decimal("0") < noted < ONE:
            if limit is not None and abs(noted + limit - ONE) <= Decimal("0.02"):
                return noted
            if cash is not None and cash < Decimal("0.5") and noted >= Decimal("0.5"):
                return cash
            return noted
        if cash is not None and Decimal("0") < cash < ONE:
            return cash
        if limit is not None and limit < Decimal("0.5"):
            return ONE - limit
        return limit
    if qty_is_fill(qty) and cash is not None:
        return cash
    if noted is not None:
        return noted
    if quote is not None and Decimal("0") < quote < ONE:
        return quote
    if limit is not None and Decimal("0") < limit < ONE:
        return limit
    return cash


def gtc_limit_of(sent: dict) -> Decimal | None:
    quote = ddec(sent.get("quote_price"))
    limit = ddec(sent.get("limit_price"))
    side = str(sent.get("side") or "").lower()
    venue = str(sent.get("venue") or "").lower()
    if venue == "kalshi" and side == "no":
        if quote is not None and quote >= Decimal("0.5"):
            return quote
        if limit is not None and limit < Decimal("0.5"):
            return ONE - limit
        if limit is not None and limit >= Decimal("0.5"):
            return limit
        if quote is not None and Decimal("0") < quote < ONE:
            return quote
    if venue == "polymarket" and side == "no" and quote is not None and limit is not None:
        if abs((ONE - limit) - quote) <= Decimal("0.02"):
            return quote
    if quote is not None and Decimal("0") < quote < ONE:
        return quote
    if limit is not None and Decimal("0") < limit < ONE:
        return limit
    return None


def payload_fee(payload) -> Decimal | None:
    if not isinstance(payload, (dict, list)):
        return None
    keys = ("fee_cost", "taker_fees", "taker_fee_dollars", "average_fee_paid", "fees", "fee")
    for node in live_lock_orders._walk(payload):
        for key in keys:
            if key not in node or node.get(key) in (None, ""):
                continue
            number = ddec(node.get(key))
            if number is not None and number >= 0:
                return number
    return None


def fee_of(sent: dict, io_row: dict | None, cash: Decimal | None, fills: list[dict] | None = None) -> Decimal:
    if fills:
        for row in fills:
            number = ddec(row.get("fee") or row.get("fee_cost") or row.get("taker_fees"))
            if number is not None and number > 0:
                return number
    payload = io_row.get("response") if io_row else None
    billed = payload_fee(payload)
    if billed is not None and billed > 0:
        return billed
    _cash, fee, qty = fill_cash_fee(sent, io_row)
    if qty_is_fill(qty) and fee and fee > 0:
        return fee
    if cash is None:
        return Decimal("0")
    spec = {
        "venue": str(sent.get("venue") or ""),
        "outcome": str(sent.get("side") or ""),
        "pay": cash,
        "intent": "",
        "fee_coefficient": sent.get("fee_coefficient"),
    }
    if io_row:
        req = io_row.get("request") if isinstance(io_row.get("request"), dict) else {}
        spec["intent"] = str(req.get("intent") or "")
        spec["fee_coefficient"] = spec["fee_coefficient"] or req.get("feeRateBps") or req.get("fee_coefficient")
    return estimate_fee(spec, cash)


def estimate_fee(spec: dict, price: Decimal) -> Decimal:
    venue = str(spec.get("venue") or "").lower()
    if venue == "gemini":
        return live_lock_orders.gemini_taker_fee(price)
    if venue == "kalshi":
        return live_lock_orders.kalshi_fee_amount(price)
    if venue == "polymarket":
        theta = spec.get("fee_coefficient") or POLY_THETA
        fee = polymarket_us_live.taker_fee(price, theta)
        return fee if fee is not None else Decimal("0")
    if venue == "novig":
        fee = live_lock_orders.leg_fee(spec, price)
        return fee if fee is not None else Decimal("0")
    return Decimal("0")


def http_of(sent: dict, io_row: dict | None) -> str:
    status = sent.get("http_status")
    if status in (None, "", "pending") and io_row:
        status = io_row.get("http_status") or io_row.get("status")
    return str(status or "")


def load_io_by_id(wanted: set[str]) -> dict[str, dict]:
    path = RAW / "order_io.jsonl"
    found: dict[str, dict] = {}
    if not path.is_file() or not wanted:
        return found
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if '"kind": "order"' not in line and '"kind":"order"' not in line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict) or str(row.get("kind") or "") != "order":
                continue
            oid = _order_id_of(row.get("response"))
            if oid and oid in wanted and oid not in found:
                found[oid] = row
            if len(found) >= len(wanted):
                break
    return found


def claim_for(events: list[dict], index: int, key: str) -> dict:
    for j in range(index, -1, -1):
        row = events[j]
        if row.get("event") == "claim" and str(row.get("bet_key") or "") == key:
            return row
    return {}


def pair_simultaneous(events: list[dict]) -> list[dict]:
    pairs = []
    i = 0
    n = len(events)
    while i < n:
        row = events[i]
        if (
            row.get("event") == "sent"
            and str(row.get("step") or "") == "simultaneous"
            and is_lock_bot(row)
        ):
            key = str(row.get("bet_key") or "")
            start = event_time(row)
            legs = [row]
            j = i + 1
            while j < n:
                other = events[j]
                if str(other.get("bet_key") or "") != key:
                    if other.get("event") in {"claim"}:
                        break
                    j += 1
                    continue
                if other.get("event") == "sent" and str(other.get("step") or "") == "simultaneous":
                    other_t = event_time(other, start)
                    if start and other_t and abs((other_t - start).total_seconds()) > 8:
                        break
                    legs.append(other)
                    j += 1
                    continue
                if other.get("event") == "sent" and str(other.get("step") or "") in RECOVERY_STEPS | {"flatten"}:
                    break
                if other.get("event") in {"claim"}:
                    break
                j += 1
            if len(legs) >= 2:
                seen = set()
                unique = []
                for leg in legs:
                    mark = (str(leg.get("venue") or ""), str(leg.get("instrument") or ""), str(leg.get("order_id") or ""))
                    if mark in seen:
                        continue
                    seen.add(mark)
                    unique.append(leg)
                if len(unique) == 2:
                    pairs.append({
                        "index": i,
                        "end_index": j,
                        "key": key,
                        "legs": unique,
                        "claim": claim_for(events, i, key),
                    })
            i = max(i + 1, j)
            continue
        i += 1
    return pairs


def later_sends(events: list[dict], start: int, key: str, until: datetime | None) -> list[dict]:
    out = []
    for row in events[start:]:
        if str(row.get("bet_key") or "") != key:
            if row.get("event") == "claim":
                break
            continue
        if row.get("event") == "claim":
            break
        if row.get("event") != "sent":
            if row.get("event") in {"flatten_filled", "flatten_miss", "one_leg", "both_unfilled"}:
                out.append(row)
            continue
        stamp = event_time(row)
        if until and stamp and stamp > until:
            break
        out.append(row)
    return out


def tick_venue(name: str) -> str:
    return {
        "kalshi": "Kalshi",
        "polymarket": "Polymarket",
        "gemini": "Gemini",
        "novig": "Novig",
    }.get(str(name or "").lower(), str(name or ""))


def game_tokens(game: str) -> set[str]:
    text = game_norm(game)
    parts = re.split(r"\bvs\.?\b", text)
    tokens = set()
    for part in parts:
        last = last_name(part)
        if last and len(last) >= 3:
            tokens.add(last)
    if not tokens:
        last = last_name(text)
        if last:
            tokens.add(last)
    return tokens


def ticker_player(instrument: str, game: str) -> str:
    inst = str(instrument or "")
    suffix = inst.rsplit("-", 1)[-1].strip().lower()
    if not suffix or suffix.startswith("aec"):
        return ""
    for tok in game_tokens(game):
        if tok.startswith(suffix[:3]) or suffix.startswith(tok[:3]):
            return tok
    return ""


def tick_target(miss: dict, player: str, game: str) -> tuple[str, str]:
    """Book side + player the GTC would rest on (pay you wanted, not the inverted wire)."""
    side = str(miss.get("side") or "").lower()
    venue = str(miss.get("venue") or "").lower()
    quote = miss.get("quote")
    limit = miss.get("limit")
    named = ticker_player(str(miss.get("instrument") or ""), game) or player
    inverted = (
        quote is not None
        and limit is not None
        and abs((ONE - limit) - quote) <= Decimal("0.02")
    )
    if inverted and venue == "polymarket":
        return "yes", player or named
    return side, named or player


def tick_matches_leg(tick: dict, game: str, market: str, number: str, venue: str, pay: str, player: str) -> bool:
    if str(tick.get("venue") or "") != tick_venue(venue):
        return False
    if str(tick.get("pay") or "").lower() != str(pay or "").lower():
        return False
    tick_game = str(tick.get("game") or "")
    want = game_tokens(game)
    have = game_tokens(tick_game)
    if want and have and not (want & have):
        return False
    market_t = str(tick.get("market_type") or "").lower()
    market_w = str(market or "").lower()
    if market_w and market_t and market_w not in {market_t, ""} and market_t not in {market_w, ""}:
        if market_w not in market_t and market_t not in market_w:
            return False
    num_w = str(number or "").strip()
    num_t = str(tick.get("number") or "").strip()
    if num_w and num_t and num_w != num_t:
        return False
    if player and str(pay or "").lower() in {"yes", "no"}:
        tick_side = str(tick.get("side") or "")
        if not same_player(player, tick_side) and last_name(player) not in game_norm(tick_side):
            return False
    return True


def first_touch(ticks: list[dict], after: datetime, until: datetime | None, limit: Decimal) -> tuple[datetime | None, Decimal | None, str]:
    best_t = None
    best_px = None
    for tick in ticks:
        seen = parse_dt(tick.get("seen_at"))
        if seen is None or seen <= after:
            continue
        if until and seen > until:
            continue
        price = ddec(tick.get("price"))
        if price is None:
            continue
        if price <= limit:
            return seen, price, "ask at or through limit"
    return best_t, best_px, "never touched"


def absorb_time(ticks: list[dict], after: datetime) -> datetime | None:
    for tick in ticks:
        if str(tick.get("pay") or "").lower() != "yes":
            continue
        seen = parse_dt(tick.get("seen_at"))
        if seen is None or seen <= after:
            continue
        price = ddec(tick.get("price"))
        if price is None:
            continue
        if price <= ABSORB_LO or price >= ABSORB_HI:
            return seen
    return None


def load_ticks(sport: str, game: str, day: str | None) -> list[dict]:
    rows = []
    tokens = [tok for tok in game_tokens(game) if len(tok) >= 3]
    needle = max(tokens, key=len) if tokens else (last_name(game) or game_norm(game))
    for row in price_memory.iter_ticks(sport=sport or None, game=needle or None, day=day):
        if tokens and not (set(tokens) & game_tokens(str(row.get("game") or ""))):
            continue
        rows.append(row)
    return rows


def cents_delta(value: Decimal | None) -> Decimal | None:
    return value


def build_events() -> tuple[list[dict], dict]:
    events = load_jsonl(RAW / "orders.jsonl")
    fills_index = load_venue_fill_index()
    pairs = pair_simultaneous(events)
    wanted_ids: set[str] = set()
    for pair in pairs:
        for leg in pair["legs"]:
            oid = str(leg.get("order_id") or "")
            if oid:
                wanted_ids.add(oid)
        later = later_sends(events, pair["end_index"], pair["key"], None)
        for row in later:
            oid = str(row.get("order_id") or "")
            if oid:
                wanted_ids.add(oid)
    io_by_id = load_io_by_id(wanted_ids)
    counts = {
        "n_simultaneous_pairs": len(pairs),
        "n_both_filled": 0,
        "n_both_unfilled": 0,
        "n_one_leg": 0,
        "n_unknown_qty": 0,
    }
    misses = []
    for pair in pairs:
        claim = pair["claim"]
        key = pair["key"]
        info = parse_key(key)
        legs_out = []
        for sent in pair["legs"]:
            oid = str(sent.get("order_id") or "")
            io_row = io_by_id.get(oid)
            inst = str(sent.get("instrument") or "")
            vfills = list(fills_index.get((str(sent.get("venue") or "").lower(), inst.lower()), []))
            qty = confirm_qty(sent, io_row, vfills)
            cash = pay_cash(sent, io_row)
            fee = fee_of(sent, io_row, cash, vfills)
            if io_row and not sent.get("sent_at"):
                sent = dict(sent)
                sent["timestamp"] = io_row.get("timestamp")
            legs_out.append({
                "sent": sent,
                "io": io_row,
                "qty": qty,
                "cash": cash,
                "fee": fee,
                "http": http_of(sent, io_row),
                "venue": str(sent.get("venue") or ""),
                "side": str(sent.get("side") or ""),
                "instrument": inst,
                "limit": ddec(sent.get("limit_price")),
                "quote": ddec(sent.get("quote_price")),
                "gtc_limit": gtc_limit_of(sent),
                "order_id": oid,
                "confirm_note": str(sent.get("confirm_note") or ""),
                "confirm_known": str(sent.get("confirm_known") or ""),
            })
        later = later_sends(events, pair["end_index"], key, None)
        recovery = [
            row for row in later
            if row.get("event") == "sent" and str(row.get("step") or "") in RECOVERY_STEPS
        ]
        flatten_sents = [
            row for row in later
            if row.get("event") == "sent" and str(row.get("step") or "") in {"flatten", "extra-flatten"}
        ]
        flatten_events = [row for row in later if row.get("event") in {"flatten_filled", "flatten_miss"}]
        filled = [leg for leg in legs_out if qty_is_fill(leg["qty"])]
        missed = [leg for leg in legs_out if not qty_is_fill(leg["qty"])]
        recovered = []
        for row in recovery:
            oid = str(row.get("order_id") or "")
            io_row = io_by_id.get(oid)
            inst = str(row.get("instrument") or "")
            vfills = list(fills_index.get((str(row.get("venue") or "").lower(), inst.lower()), []))
            qty = confirm_qty(row, io_row, vfills)
            recovered.append((row, qty))
        still_missed = list(missed)
        if recovered:
            for rec, qty in recovered:
                if qty_is_fill(qty):
                    still_missed = [
                        leg for leg in still_missed
                        if str(leg.get("venue") or "") != str(rec.get("venue") or "")
                        or str(leg.get("instrument") or "") != str(rec.get("instrument") or "")
                    ]
        if len(filled) >= 2:
            counts["n_both_filled"] += 1
            continue
        if len(filled) == 0:
            counts["n_both_unfilled"] += 1
            continue
        if len(filled) != 1 or len(still_missed) != 1:
            counts["n_unknown_qty"] += 1
            continue
        counts["n_one_leg"] += 1
        fill_leg = filled[0]
        miss_leg = still_missed[0]
        flatten_row = flatten_sents[0] if flatten_sents else None
        flatten_filled = False
        flatten_cash = None
        flatten_fee = Decimal("0")
        flatten_qty = Decimal("0")
        flatten_http = ""
        if flatten_row:
            oid = str(flatten_row.get("order_id") or "")
            io_row = io_by_id.get(oid)
            inst = str(flatten_row.get("instrument") or "")
            vfills = list(fills_index.get((str(flatten_row.get("venue") or "").lower(), inst.lower()), []))
            flatten_qty = confirm_qty(flatten_row, io_row, vfills)
            flatten_cash = pay_cash(flatten_row, io_row)
            flatten_fee = fee_of(flatten_row, io_row, flatten_cash, vfills)
            flatten_http = http_of(flatten_row, io_row)
            flatten_filled = qty_is_fill(flatten_qty)
        elif flatten_events:
            flatten_filled = any(row.get("event") == "flatten_filled" for row in flatten_events)
        fill_allin = (fill_leg["cash"] or Decimal("0")) + (fill_leg["fee"] or Decimal("0"))
        flatten_allin = None
        flatten_pnl = None
        if flatten_filled and flatten_cash is not None:
            flatten_allin = flatten_cash + flatten_fee
            flatten_pnl = ONE - fill_allin - flatten_allin
        start = event_time(fill_leg["sent"]) or event_time(miss_leg["sent"]) or event_time(claim)
        game = str(claim.get("game") or "")
        player = str(claim.get("side") or info.get("side_key") or "")
        misses.append({
            "pair": pair,
            "claim": claim,
            "key": key,
            "info": info,
            "game": game,
            "sport": sport_of(claim, key),
            "market": str(claim.get("market_type") or info.get("market_type") or ""),
            "number": str(claim.get("number") or info.get("number") or ""),
            "player": player,
            "start": start,
            "fill": fill_leg,
            "miss": miss_leg,
            "recovery_n": len(recovery),
            "flatten_filled": flatten_filled,
            "flatten_http": flatten_http,
            "flatten_cash": flatten_cash,
            "flatten_fee": flatten_fee,
            "flatten_pnl": flatten_pnl,
            "flatten_allin": flatten_allin,
            "fill_allin": fill_allin,
        })
    counts["n_one_leg"] = len(misses)
    return misses, counts


def attach_ticks(misses: list[dict]) -> None:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in misses:
        start = row["start"]
        day = start.astimezone(ET).strftime("%Y-%m-%d") if start else ""
        sport = str(row.get("sport") or "")
        if sport.startswith("tennis"):
            sport = "tennis"
        row["_day"] = day
        row["_sport"] = sport
        groups[(sport, day)].append(row)
    cache: dict[tuple[str, str], list[dict]] = {}
    for (sport, day), group in groups.items():
        if not day:
            cache[(sport, day)] = []
            print(f"ticks {sport} {day or '(no day)'} skipped — no send time", flush=True)
            continue
        needles = set()
        for row in group:
            needles.update(tok for tok in game_tokens(str(row.get("game") or "")) if len(tok) >= 3)
        ticks = []
        for tick in price_memory.iter_ticks(sport=sport or None, day=day or None):
            blob = str(tick.get("game") or "").lower()
            if needles and not any(tok in blob for tok in needles):
                continue
            ticks.append(tick)
        cache[(sport, day)] = ticks
        print(f"ticks {sport} {day} kept {len(ticks)} / needles {len(needles)}", flush=True)
    for row in misses:
        start = row["start"]
        sport = row.get("_sport") or ""
        day = row.get("_day") or ""
        game = str(row.get("game") or "")
        ticks = cache.get((sport, day), [])
        miss = row["miss"]
        limit = miss.get("gtc_limit")
        venue = miss.get("venue")
        player = str(row.get("player") or "")
        pay, tick_player = tick_target(miss, player, game)
        miss["tick_pay"] = pay
        miss["tick_player"] = tick_player
        matched = [
            tick for tick in ticks
            if tick_matches_leg(tick, game, row["market"], row["number"], venue, pay, tick_player)
        ]
        if not matched:
            matched = [
                tick for tick in ticks
                if tick_matches_leg(tick, game, row["market"], row["number"], venue, pay, "")
            ]
        row["ticks_n"] = len(matched)
        row["ticks_game_n"] = len(ticks)
        if not ticks:
            row["tick_status"] = "unknown — no ticks for this game/day"
            row["gtc_fill"] = None
            continue
        if not matched:
            row["tick_status"] = "unknown — ticks exist for the game, not this venue/side/pay"
            row["gtc_fill"] = None
            continue
        if start is None or limit is None:
            row["tick_status"] = "unknown — missing miss time or GTC limit"
            row["gtc_fill"] = None
            continue
        until = absorb_time(ticks, start)
        last_seen = None
        for tick in matched:
            seen = parse_dt(tick.get("seen_at"))
            if seen and (last_seen is None or seen > last_seen):
                last_seen = seen
        window_end = until or last_seen
        touch_t, touch_px, why = first_touch(matched, start, window_end, limit)
        row["absorb_at"] = until
        row["window_end"] = window_end
        row["touch_at"] = touch_t
        row["touch_px"] = touch_px
        row["touch_why"] = why
        if touch_t is None:
            row["gtc_fill"] = False
            row["delay_s"] = None
            row["tick_status"] = "no touch through GTC limit before absorb/last tick"
        else:
            row["gtc_fill"] = True
            row["delay_s"] = (touch_t - start).total_seconds()
            row["tick_status"] = why
        miss_fee = estimate_fee(
            {
                "venue": venue,
                "outcome": pay,
                "pay": limit,
                "fee_coefficient": (miss.get("sent") or {}).get("fee_coefficient"),
            },
            limit,
        )
        if miss.get("io"):
            req = miss["io"].get("request") if isinstance(miss["io"].get("request"), dict) else {}
            miss_fee = estimate_fee(
                {
                    "venue": venue,
                    "outcome": pay,
                    "pay": limit,
                    "fee_coefficient": req.get("feeRateBps") or req.get("fee_coefficient"),
                    "fee_charged": req.get("fee_charged"),
                    "event_status": req.get("event_status"),
                },
                limit,
            )
        row["gtc_fee"] = miss_fee
        fill = row["fill"]
        fill_key = tennis_pay_key(str(fill.get("side") or ""), str(row.get("player") or ""), str(fill.get("instrument") or ""))
        miss_key = tennis_pay_key(str(pay or ""), str(tick_player or ""), str(miss.get("instrument") or ""))
        same_ticker = str(fill.get("instrument") or "") == str(miss.get("instrument") or "")
        complementary = opposite_pay(fill_key, miss_key) or (
            same_ticker and {str(fill.get("side") or "").lower(), str(pay or "").lower()} == {"yes", "no"}
        )
        row["complementary"] = complementary
        if row["gtc_fill"] and complementary:
            row["gtc_pnl"] = ONE - row["fill_allin"] - limit - miss_fee
        else:
            row["gtc_pnl"] = None
            if row["gtc_fill"] and not complementary:
                row["tick_status"] = "ask touched; not a complementary $1 pair"


def summarize(misses: list[dict]) -> dict:
    known = [row for row in misses if row.get("gtc_fill") is not None]
    fills = [row for row in known if row.get("gtc_fill")]
    delays = [row["delay_s"] for row in fills if row.get("delay_s") is not None]
    flatten_pnls = [row["flatten_pnl"] for row in misses if row.get("flatten_pnl") is not None]
    gtc_pnls = [row["gtc_pnl"] for row in fills if row.get("gtc_pnl") is not None]
    both = [
        row for row in misses
        if row.get("flatten_pnl") is not None and row.get("gtc_pnl") is not None
    ]
    delta = [
        (row["gtc_pnl"] - row["flatten_pnl"])
        for row in both
    ]
    moutet = [row for row in misses if "moutet" in str(row.get("game") or "").lower()]
    return {
        "n": len(misses),
        "n_known": len(known),
        "n_unknown": len(misses) - len(known),
        "n_would_fill": len(fills),
        "pct_known": (Decimal(len(fills)) / Decimal(len(known)) * 100) if known else None,
        "pct_all": (Decimal(len(fills)) / Decimal(len(misses)) * 100) if misses else None,
        "median_delay_s": statistics.median(delays) if delays else None,
        "sum_flatten": sum(flatten_pnls, Decimal("0")) if flatten_pnls else Decimal("0"),
        "n_flatten": len(flatten_pnls),
        "sum_gtc": sum(gtc_pnls, Decimal("0")) if gtc_pnls else Decimal("0"),
        "n_gtc": len(gtc_pnls),
        "sum_delta": sum(delta, Decimal("0")) if delta else Decimal("0"),
        "n_both": len(both),
        "n_moutet": len(moutet),
        "moutet": moutet,
    }


def write_html(misses: list[dict], counts: dict, summary: dict) -> None:
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    pct_known = (
        f"{format(summary['pct_known'].quantize(Decimal('0.1')), 'f')}%"
        if summary["pct_known"] is not None
        else "—"
    )
    pct_all = (
        f"{format(summary['pct_all'].quantize(Decimal('0.1')), 'f')}%"
        if summary["pct_all"] is not None
        else "—"
    )
    med = summary["median_delay_s"]
    med_txt = f"{med / 60:.1f} min ({int(med)} s)" if med is not None else "—"
    headers = [
        ("When ET", "date"),
        ("Game", "text"),
        ("Filled", "text"),
        ("Missed", "text"),
        ("Flatten?", "text"),
        ("Flatten P&L", "num"),
        ("GTC limit", "num"),
        ("Would GTC fill?", "text"),
        ("Delay", "num"),
        ("First touch ask", "num"),
        ("GTC lock P&L", "num"),
        ("GTC − flatten", "num"),
        ("Ticks", "text"),
        ("Order ids", "text"),
    ]
    rows = []
    for row in misses:
        fill = row["fill"]
        miss = row["miss"]
        delay = row.get("delay_s")
        delay_cell = "" if delay is None else f"{delay:.0f}"
        gtc_pnl = row.get("gtc_pnl")
        flatten_pnl = row.get("flatten_pnl")
        delta = None
        if gtc_pnl is not None and flatten_pnl is not None:
            delta = gtc_pnl - flatten_pnl
        fill_txt = (
            f"{esc(venue_label(fill['venue']))} {esc(fill['side'])} "
            f"{money4(fill['cash'])} fee {money4(fill['fee'])} HTTP {esc(fill['http'])}"
        )
        miss_txt = (
            f"{esc(venue_label(miss['venue']))} {esc(miss['side'])} "
            f"limit {money4(miss.get('limit'))} recheck {money4(miss.get('quote'))} "
            f"HTTP {esc(miss['http'])} qty 0"
        )
        would = {True: "yes", False: "no", None: "unknown"}[row.get("gtc_fill")]
        rows.append([
            esc(clock(row.get("start"))),
            esc(row.get("game") or ""),
            fill_txt,
            miss_txt,
            "yes" if row.get("flatten_filled") else "no",
            cents(flatten_pnl),
            money4(miss.get("gtc_limit")),
            would,
            delay_cell,
            money4(row.get("touch_px")),
            cents(gtc_pnl),
            cents(delta),
            esc(row.get("tick_status") or ""),
            f"{esc(fill.get('order_id'))} / {esc(miss.get('order_id'))}",
        ])
    total = [
        f"N={summary['n']}",
        "",
        "",
        "",
        f"{sum(1 for r in misses if r.get('flatten_filled'))} flattened",
        cents(summary["sum_flatten"]),
        "",
        f"{summary['n_would_fill']} fill / {summary['n_known']} known",
        med_txt,
        "",
        cents(summary["sum_gtc"]),
        cents(summary["sum_delta"]),
        f"{summary['n_unknown']} unknown ticks",
        "",
    ]
    moutet_bits = []
    for row in summary["moutet"]:
        miss = row["miss"]
        fill = row["fill"]
        moutet_bits.append(
            f"{esc(clock(row.get('start')))}: filled {esc(venue_label(fill['venue']))} "
            f"{esc(fill['side'])} {money4(fill['cash'])}, missed {esc(venue_label(miss['venue']))} "
            f"{esc(miss['side'])} GTC {money4(miss.get('gtc_limit'))}, flatten "
            f"{cents(row.get('flatten_pnl'))}, GTC would fill="
            f"{ {True: 'yes', False: 'no', None: 'unknown'}[row.get('gtc_fill')] }, "
            f"GTC lock {cents(row.get('gtc_pnl'))}."
        )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
{report_page_extras.CACHE_META}
{report_page_extras.FORCE_RELOAD_SCRIPT}
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>One-leg miss: GTC vs flatten — 23 Oct 2026</title>
<style>
body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 1.2rem; color: #1e293b; background: #fff; }}
h1 {{ font-size: 1.45rem; margin-bottom: 0.3rem; }}
h2 {{ font-size: 1.05rem; margin: 1.2rem 0 0.4rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 0 0 12px; }}
.callout h2 {{ margin: 0 0 6px; }}
.warn {{ background: #fff7ed; border-color: #fdba74; }}
.ok {{ background: #f0fdf4; border-color: #86efac; }}
.note {{ color: #475569; font-size: 14px; }}
.hl {{ font-size: 1.15rem; }}
ul {{ margin-top: 0.3rem; }}
code {{ font-size: 0.9em; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>One-leg miss: rest GTC vs flatten</h1>
<p class="note">Written {esc(now)}. America/New_York. Research only. Not gold. Not DailyRun. One contract. Fees included. Did not wire leftover GTC. Cancel-on-resolve is still missing. D stays 0.25. NET_MAX stays 0.984. No second Strategy B. Did not sell. Did not commit. Click column headers to sort.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>A lock is supposed to buy both sides of the same bet so $1 of payout covers the cost. Both sides are sent at once as Immediate-or-Cancel (IOC) — fill now or cancel. Sometimes only one side fills. House rule today: immediately flatten (buy the opposite on the same shop) so you are not left holding a one-sided bet. You would rather rest a Good-Till-Cancel (GTC) on the missed shop at the same price, and wait to see if that price comes back.</p>
<p>This page does not turn GTC on. It looks at every true one-leg miss on the lock-bot tape and asks the books: after we missed, did that missed price print again before the match was effectively over? If yes, a resting GTC <em>might</em> have filled and locked the original pair. A later last/ask print is not a guaranteed queue fill.</p>
</div>

<div class="callout warn">
<h2>HTTP glossary — 200 and 201 are not fill/fail</h2>
<ul>
<li><strong>Polymarket HTTP 200</strong> means the request was accepted (OK). It is not a fill. The fill is <code>cumQuantity</code> (and the activities GET). Qty 0 then cancel HTTP 200 is an empty IOC: posted, matched nobody, canceled. <code>D988YSS011N2</code> is that case. 200 ≠ “you own 1 contract.”</li>
<li><strong>Kalshi HTTP 201</strong> means Created — the order was accepted. It is success, not a fail. The fill is <code>fill_count</code>. <code>fill_count</code> 1 = you bought 1. <code>fill_count</code> 0 = empty IOC cancel. That 0-with-201 was the old false-fill bug. Tonight’s leftover was <code>fill_count</code> 1.00: real No at 84¢. Kalshi prints that as Sold Yes 16¢ on the Yes page because buying No is posted as selling Yes.</li>
<li><strong>Empty IOC cancel</strong> = Immediate-or-Cancel that did not match. HTTP can still be 200 or 201. Qty is the fill, not the status code.</li>
</ul>
</div>

<div class="callout">
<h2>Tonight’s 10:47 leftover was 84¢ No, not a 13¢ Yes</h2>
<p>Polymarket Yes Moutet at 13¢ never filled. The ticket you held was Kalshi <strong>No Moutet at 84¢</strong> (Sold Yes 16¢ on the Yes page). Flatten bought Yes Moutet at 19¢ + 1.08¢ fee = 20.08¢ to close that No. Round-trip 84¢ + 19¢ + 2.03¢ fees = $1.0503 → <strong>−5.03¢</strong>. That is not “spending 0.06¢ to exit a 13¢ Poly bet.” Detail: <a href="moutet_paul_t0_20261023.html">moutet_paul_t0_20261023.html</a>.</p>
</div>

<div class="callout ok">
<h2>Headline</h2>
<p class="hl"><strong>{esc(summary['n'])} true one-leg misses</strong> (simultaneous IOC, venue-confirm qty ≥ 1 on one shop and qty 0 on the other after recovery). Among {esc(summary['n_known'])} with later ticks on the missed book, the missed limit came back <strong>{esc(summary['n_would_fill'])} times ({esc(pct_known)} of known)</strong>. Median time-to-touch: {esc(med_txt)}. {esc(summary['n_unknown'])} row has no usable ticks (unknown, not a “no”).</p>
<p>Flatten, with fees, on {esc(summary['n_flatten'])} flattened leftovers: <strong>{esc(cents(summary['sum_flatten']))}</strong>. If we had instead rested a 1-contract GTC and it had filled as a true Yes+No (or dual-Yes) lock, those {esc(summary['n_gtc'])} complementary come-backs would have been <strong>{esc(cents(summary['sum_gtc']))}</strong>. On the {esc(summary['n_both'])} rows that have both a flatten P&amp;L and a complementary GTC lock P&amp;L, GTC minus flatten is <strong>{esc(cents(summary['sum_delta']))}</strong>. A come-back that is not a complementary pair is counted in the {esc(pct_known)} but is not given a $1-lock P&amp;L.</p>
<p>Not wired. Cancel-on-resolve still missing, so a live leftover GTC could still be open after the match ends.</p>
</div>

<h2>How a one-leg miss is counted</h2>
<ul>
<li>Lock-bot simultaneous IOC pair only (not Strategy B, not sequential first-leg-then-other).</li>
<li>Venue-confirm qty ≥ 1 on one venue and qty 0 on the other after recovery posts (websocket / book / midway / watch on the missed shop before flatten). Confirm qty wins over HTTP. Kalshi 201 with fill_count 0 is not a fill. Poly 200 with cumQuantity 0 is not a fill.</li>
<li>GTC counterfactual: rest 1 contract on the missed venue at the IOC pay (last recheck ask if present, else the posted limit) until the first absorbing Yes (≤5¢ or ≥95¢) or the last in-match tick. Fill = last/ask traded at or through that limit. P&amp;L uses the GTC limit plus documented fees, plus the leftover fill that actually happened, versus $1. Flatten P&amp;L is leftover all-in plus flatten all-in versus $1.</li>
</ul>
<p class="note">Caveat: a later ask print is not a guaranteed GTC fill. We do not invent queue priority. If ticks are missing, the row is unknown, not “would not fill.” Kalshi send-cap still treats Kalshi fee as $0; this page puts Kalshi GET fee_cost / average_fee_paid on the P&amp;L when the body has one, otherwise the 0.07 × price × (1 − price) formula. Simultaneous pairs in the tape: {esc(counts.get('n_simultaneous_pairs'))}. Both filled {esc(counts.get('n_both_filled'))}. Both empty {esc(counts.get('n_both_unfilled'))}. One-leg {esc(counts.get('n_one_leg'))}. Ambiguous qty {esc(counts.get('n_unknown_qty'))}.</p>

<h2>Moutet vs Paul on this rule</h2>
<p>{'<br>'.join(moutet_bits) if moutet_bits else 'No Moutet one-leg row matched the simultaneous definition.'}</p>

<h2>Every one-leg miss</h2>
<p class="note">Click column headers to sort. P&amp;L is dollars per 1-contract pair, shown in cents. Swipe sideways to see more columns.</p>
{report_page_extras.SWIPE_NOTE_HTML}
{table(headers, rows, total)}

<h2>What this does not do</h2>
<ul>
<li>Does not rest GTC. Cancel-on-resolve is still missing.</li>
<li>Does not change D=0.25 or NET_MAX 0.984.</li>
<li>Does not start a second Strategy B, sell, commit, or print secrets.</li>
</ul>
<p class="note">Sources: local orders.jsonl (simultaneous / flatten / confirm_qty), order_io.jsonl HTTP bodies, venue fill-history pull when present, price_memory in-match ticks (dated shards plus archive before the 21 Oct 11:34 ET split). House fees: Kalshi GET fee when present else 0.07×p×(1−p); Polymarket theta×p×(1−p) banker's cent (ticket coefficient, else standard 0.0695); Gemini 0.07×p×(1−p) ceiled to a cent. Pulled {esc(now)}.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    print(f"wrote {PAGE}")


def patch_moutet() -> None:
    if not MOUTET_PAGE.is_file():
        print(f"missing {MOUTET_PAGE}")
        return
    text = MOUTET_PAGE.read_text(encoding="utf-8")
    marker = "one_leg_miss_gtc_vs_flatten_20261023.html"
    title = "Addendum — 200/201, leftover 84¢ No, GTC vs flatten"
    block = f"""
<div class="callout warn">
<h2>{title}</h2>
<p><strong>Poly HTTP 200 is not a fill.</strong> <code>D988YSS011N2</code> HTTP 200, cumQuantity 0, then cancel 200 is an empty Immediate-or-Cancel. Success of the HTTP call ≠ qty 1.</p>
<p><strong>Kalshi HTTP 201 is not a fail.</strong> 201 Created means the order was accepted. The fill is <code>fill_count</code>. This leftover was fill_count 1.00 No at 84¢ (UI Sold Yes 16¢). fill_count 0 on a 201 is an empty IOC — that was the old false-fill bug; it is not this row.</p>
<p><strong>Wrong economics:</strong> they did not spend 0.06¢ to exit a 13¢ Poly Yes. That 13¢ never filled. The leftover was Kalshi No 84¢. Flatten bought Yes 19¢ + 1.08¢ fee = 20.08¢. Round-trip 84+19+fees = $1.0503 → <strong>−5.03¢</strong>.</p>
<p>You would rather rest GTC on the missed Poly Yes at 13¢ than flatten. That is research-only. Historical one-leg misses, whether the missed price came back, and flatten vs hypothetical GTC dollars (with fees): <a href="{marker}">{marker}</a>. Not wired. Cancel-on-resolve still missing. D stays 0.25. NET_MAX stays 0.984.</p>
</div>
"""
    if title in text:
        text = re.sub(
            r'<div class="callout warn">\s*<h2>Addendum — 200/201, leftover 84¢ No, GTC vs flatten</h2>.*?</div>',
            block.strip(),
            text,
            count=1,
            flags=re.S,
        )
    else:
        needle = '<div class="callout">\n<h2>What flatten is</h2>'
        if needle in text:
            text = text.replace(needle, block + needle, 1)
        else:
            text = text.replace("</h1>", "</h1>\n" + block, 1)
    MOUTET_PAGE.write_text(text, encoding="utf-8")
    print(f"patched {MOUTET_PAGE}")


def main() -> None:
    misses, counts = build_events()
    attach_ticks(misses)
    summary = summarize(misses)
    write_html(misses, counts, summary)
    patch_moutet()
    print(
        json.dumps(
            {
                "n": summary["n"],
                "known": summary["n_known"],
                "would_fill": summary["n_would_fill"],
                "unknown": summary["n_unknown"],
                "pairs": counts.get("n_simultaneous_pairs"),
                "flatten_cents": str(summary["sum_flatten"]),
                "gtc_cents": str(summary["sum_gtc"]),
                "delta": str(summary["sum_delta"]),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
