"""Rewrite orders.html when an order is posted or a one-leg result is saved.

Earlier sent rows stay on the page. New sends are appended from orders.jsonl.
Polymarket short fills are read from the order response: average price, cash
price, and fee. This module does not send an order and does not clear the stop latch.
"""
from __future__ import annotations

import html
import json
import re
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import venue_pace  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW  # noqa: E402
from report_page_extras import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, SWIPE_NOTE_HTML  # noqa: E402
PAGE = STAMP / "orders.html"
ORDERS = RAW / "orders.jsonl"
ORDER_IO = RAW / "order_io.jsonl"
SUPERVISOR_LOG = RAW / "live_supervisor.log"
PAGE_LOCK = RAW / "orders_page.lock"
ET = ZoneInfo("America/New_York")
ONE = Decimal("1")

ASKED = (
    "Paul: “you have the wrong winner here again. can you go back and make sure all of the matches "
    "have the correct winner? Now we need to go back and regenerate all the reports again” "
    "Prior: does this page only show orders for system A? can it show all and tell what system it is in the table?"
)
ASKED_PRIOR = (
    "I need detailed accounting in html of every trade made. What was filled. "
    "What its pair was, and whether that pair was or was not filled. "
    "We have 19 yeses on this for filled, but only 1 fill price and fee. "
    "We should also have fill price and fee and limit price on the other side of the pair too."
)
ASKED_LATEST = (
    "cool. we made our first polymarket buy! but boo, we didn't make the other pair. "
    "the order did NOT update this html, and it should. "
    "the opportunity did not update the opportunities sheet, and it should."
)
PLAIN = (
    "We showed the wrong player as the winner on some Polymarket tennis games, so P&L was backwards; "
    "we checked every settled game against the platform and rebuilt the pages. "
    "This page lists every order we actually sent across all five live systems, not only lock gap. "
    "The System column says which one: A Lock gap (buy Yes on one venue and No on the other when the pair is cheap enough), "
    "B Tennis crossover (Yes on the tennis dog after it crosses 50, and related tennis Yes tickets), "
    "C CFB favorite (college football favorite Yes at T0), "
    "D T0 spreads (one spread Yes at T0), "
    "or E Tennis T0 dog (tennis dog Yes at T0). "
    "A lock pair is two bets on the same game meant to be bought together so the $1 payout covers the cost. "
    "If only one side fills, that cash is at risk and the other side was not bought. "
    "B, C, D, and E are one-Yes tickets, so the pair columns say not sent — that is not a missed hedge. "
    "Each filled order shows the wire fill, the fee the venue charged, and after-fee (all-in = wire + fee). "
    "Wire alone is not after-fee. Missing fee is fee unknown, not 0. "
    "If a side was sent and did not fill, the limit is shown and fill/fee/after-fee are blank — not zero. "
    "On a No bet, the limit column is the No price we were willing to pay. "
    "Kalshi was sent a Yes sell at one minus that price. "
    "A Polymarket short is a No. Its fill price is the average price on the order response. "
    "The first table is every order that was actually sent (filled or attempted). "
    "Quote source, quote price, quote time, send time, and lag show which websocket or book print "
    "the limit came from, and how many seconds later the order left. "
    "The second table is chances skipped before anything was sent. "
    "Nothing on this page places an order."
)
SENT_LINE = re.compile(
    r"^(?P<ts>\S+) order sent venue=(?P<venue>\S+) instrument=(?P<inst>\S+) "
    r"side=(?P<side>\S+) limit=(?P<limit>\S+) size=\S+ http=(?P<http>\d+)"
)
COLUMNS = (
    ("Pair", "num"),
    ("System", "text"),
    ("Game", "text"),
    ("Market", "text"),
    ("Side", "text"),
    ("Venue", "text"),
    ("Instrument", "text"),
    ("Limit price", "num"),
    ("Fill price (wire)", "num"),
    ("Fee", "num"),
    ("Size", "num"),
    ("Filled", "text"),
    ("HTTP", "num"),
    ("Pair venue", "text"),
    ("Pair instrument", "text"),
    ("Pair side", "text"),
    ("Pair limit price", "num"),
    ("Pair fill price (wire)", "num"),
    ("Pair fee", "num"),
    ("Pair filled", "text"),
    ("Outcome", "text"),
    ("Time", "date"),
    ("Order id", "text"),
    ("Note", "text"),
    ("Quote source", "text"),
    ("Quote price", "num"),
    ("Quote seen", "date"),
    ("Lag seconds", "num"),
    ("Trigger", "text"),
    ("After-fee (all-in)", "num"),
    ("Pair after-fee (all-in)", "num"),
)

COL = {name: i for i, (name, _kind) in enumerate(COLUMNS)}
COL_COUNT = len(COLUMNS)
SYSTEM_LABELS = {
    "lock": "A Lock gap",
    "tennis_crossover": "B Tennis crossover",
    "cfb_favorite": "C CFB favorite",
    "spread_t0": "D T0 spreads",
    "tennis_t0_dog": "E Tennis T0 dog",
    "tennis_t0_spread": "F Tennis spread",
    "soccer_t0_total": "G Soccer total",
}
SYSTEM_LABEL_SET = set(SYSTEM_LABELS.values())
B_ALIASES = {"b", "strategy_b", "strategy-b", "tennis_crossover", "tennis-crossover"}


def _decorate_sports_cells(cells: list[str]) -> list[str]:
    """Replace Kalshi sports tickers in Game/Side with team names. Tennis MATCH unchanged."""
    row = _pad_cells(list(cells))
    try:
        import kalshi_ticker_decode as ktd
    except Exception:
        return row
    inst = str(row[COL["Instrument"]] or "")
    if not ktd.is_sports_ticker(inst):
        return row
    side_raw = str(row[COL["Side"]] or "").strip()
    pay = ktd.pay_from_garbled_bet(side_raw) or ("no" if side_raw.lower().startswith("no") else "yes")
    decoded = ktd.decode_kalshi_ticker(inst, pay=pay)
    if not decoded.kind:
        return row
    if decoded.game:
        row[COL["Game"]] = decoded.game
    market = str(row[COL["Market"]] or "")
    if (
        not market.strip()
        or market.lower() in {"yes", "no", "ml", "moneyline", "spread", "total"}
        or ktd.looks_like_ticker(market)
        or "wins by" in market.lower()
        or market.lower().startswith("total")
    ):
        row[COL["Market"]] = decoded.market or market
    if ktd.is_yes_no_token(side_raw) or not side_raw or side_raw.lower() in {decoded.yes_code.lower(), (decoded.yes_name or "").lower()}:
        row[COL["Side"]] = ktd.kitchen_phrase(decoded, pay)
    return row


def _pad_cells(cells: list[str]) -> list[str]:
    row = list(cells)
    if len(row) < COL_COUNT:
        row.extend([""] * (COL_COUNT - len(row)))
    return row[:COL_COUNT]


def _esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _now() -> str:
    return datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")


def _system_id(row: dict | None) -> str:
    """lock / tennis_crossover / cfb_favorite / spread_t0 / tennis_t0_dog / tennis_t0_spread / soccer_t0_total."""
    row = row or {}
    key = str(row.get("bet_key") or "")
    step = str(row.get("step") or "")
    system = str(row.get("system") or row.get("_system") or "").strip().lower().replace(" ", "_")
    if system in {"cfb_favorite", "c", "cfb-favorite"} or key.startswith("cfb-favorite") or step.startswith("c-"):
        return "cfb_favorite"
    if system in {"spread_t0", "d", "spread-t0"} or key.startswith("spread-t0") or step.startswith("d-"):
        return "spread_t0"
    if system in {"tennis_t0_dog", "e", "tennis-t0-dog"} or key.startswith("tennis-t0-dog") or step.startswith("e-"):
        return "tennis_t0_dog"
    if system in {"tennis_t0_spread", "f", "tennis-t0-spread"} or key.startswith("tennis-t0-spread") or step.startswith("f-"):
        return "tennis_t0_spread"
    if system in {"soccer_t0_total", "g", "soccer-t0-total"} or key.startswith("soccer-t0-total") or step.startswith("g-"):
        return "soccer_t0_total"
    if system in B_ALIASES or key.startswith("tennis-b") or step.startswith("b-") or row.get("_strategy_b"):
        return "tennis_crossover"
    return "lock"


def _system_label(row: dict | None) -> str:
    return SYSTEM_LABELS[_system_id(row)]


def _game_from_bet_key(key: str, system_id: str) -> str:
    parts = str(key or "").split("\t")
    if system_id == "tennis_crossover" and len(parts) >= 3:
        return parts[2]
    return ""


def _side_from_bet_key(key: str, system_id: str) -> str:
    parts = str(key or "").split("\t")
    if system_id == "tennis_crossover" and len(parts) >= 5:
        return parts[4]
    if system_id in {"cfb_favorite", "spread_t0", "tennis_t0_dog", "tennis_t0_spread", "soccer_t0_total"} and len(parts) >= 3:
        return parts[2]
    return ""


def _market_from_attempt(context: dict, sent: dict, system_id: str) -> str:
    market_type = str(context.get("market_type") or "")
    side = str(context.get("side") or sent.get("side_label") or sent.get("player") or "")
    if not market_type:
        if system_id in {"spread_t0", "tennis_t0_spread"}:
            market_type = "spread"
            parts = str(sent.get("bet_key") or context.get("bet_key") or "").split("\t")
            number = parts[3] if len(parts) >= 4 else str(context.get("number") or "")
            if number:
                market_type = f"spread {number}"
        elif system_id == "soccer_t0_total":
            market_type = "total"
            parts = str(sent.get("bet_key") or context.get("bet_key") or "").split("\t")
            number = parts[3] if len(parts) >= 4 else str(context.get("number") or "")
            if number:
                market_type = f"total {number}"
        elif system_id in {"tennis_crossover", "cfb_favorite", "tennis_t0_dog"}:
            market_type = "moneyline"
        else:
            market_type = str(sent.get("market_type") or "")
    if not side:
        side = _side_from_bet_key(str(sent.get("bet_key") or context.get("bet_key") or ""), system_id)
    return " ".join(part for part in (market_type, side) if part)


def _attempt_context(claim: dict, events: list[dict]) -> dict:
    sent = next((item for item in events if item.get("event") == "sent"), {}) or {}
    sid = _system_id(sent) if sent else _system_id(claim)
    ctx = dict(claim or {})
    if not str(ctx.get("game") or ""):
        ctx["game"] = sent.get("game") or _game_from_bet_key(
            str(sent.get("bet_key") or ctx.get("bet_key") or ""), sid
        )
    if not str(ctx.get("bet_key") or ""):
        ctx["bet_key"] = sent.get("bet_key") or ""
    ctx["_system_id"] = sid
    ctx["_system_label"] = SYSTEM_LABELS[sid]
    return ctx


def _system_from_legacy_note(note: str) -> str:
    match = re.search(r"Step ([^\s,]+)", str(note or ""))
    step = match.group(1) if match else ""
    return _system_label({"step": step})


def _coerce_existing_row(cells: list[str]) -> list[str]:
    """Old pages had no System column. Insert it at index 1 when col 1 is not a label."""
    row = list(cells)
    if row and row[0] == "Pair":
        return _pad_cells(row)
    if len(row) > 1 and row[1] in SYSTEM_LABEL_SET:
        return _pad_cells(row)
    note = row[22] if len(row) > 22 else ""
    label = _system_from_legacy_note(note)
    if len(row) >= COL_COUNT and row[1] == "":
        row[1] = label
    else:
        row = [row[0], label] + row[1:]
    return _pad_cells(row)


def _dec(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace("$", "").replace(",", "").strip())
    except Exception:
        return None


def _money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.0001")), "f")


def _four(value) -> str:
    """After-fee / fee at least four decimal places. Never round to cents."""
    number = _dec(value)
    if number is None:
        return ""
    text = format(number, "f")
    if "." not in text:
        return text + ".0000"
    frac = text.split(".", 1)[1]
    if len(frac) < 4:
        text = text + ("0" * (4 - len(frac)))
    return text


def _fee_cell(filled: bool, fee) -> str:
    if not filled:
        return ""
    if _dec(fee) is None:
        return "fee unknown"
    return _four(fee)


def _after_fee_cell(filled: bool, wire, fee) -> str:
    """All-in. Wire alone is not after-fee. Missing fee → fee unknown, not 0."""
    if not filled:
        return ""
    cash = _dec(wire)
    paid = _dec(fee)
    if cash is None:
        return ""
    if paid is None:
        return "fee unknown"
    return _four(cash + paid)


def _formula_fee(venue: str, price, sent: dict | None = None) -> str:
    """Documented taker fee when the fill body did not name one. Empty = unknown, not 0."""
    if sent:
        stored = sent.get("fee") or sent.get("fee_estimate")
        if _dec(stored) is not None:
            return _four(stored)
        if str(sent.get("after_fee") or "") and _dec(sent.get("wire")) is not None and _dec(price) is not None:
            after = _dec(sent.get("after_fee"))
            wire = _dec(sent.get("wire"))
            if after is not None and wire is not None:
                return _four(after - wire)
    cash = _dec(price)
    if cash is None:
        text = str(price or "")
        if "cash" in text:
            cash = _dec(text.rsplit("cash", 1)[-1].strip(" )"))
    if cash is None:
        return ""
    try:
        import live_lock_orders
        spec = {
            "venue": str(venue or "").lower(),
            "fee_coefficient": (sent or {}).get("fee_coefficient"),
            "fee_charged": (sent or {}).get("fee_charged"),
            "event_status": (sent or {}).get("event_status"),
        }
        fee = live_lock_orders.leg_fee(spec, cash)
    except Exception:
        fee = None
    if fee is None:
        return ""
    return _four(fee)


def _wire_of(fill_price: str, sent: dict, fill: dict | None) -> str:
    if sent.get("wire") not in (None, ""):
        return str(sent.get("wire"))
    if fill and fill.get("cash"):
        return str(fill.get("cash"))
    number = _dec(fill_price)
    if number is not None:
        return str(number)
    text = str(fill_price or "")
    if "cash" in text:
        cash = _dec(text.rsplit("cash", 1)[-1].strip(" )"))
        if cash is not None:
            return format(cash, "f")
    return ""


def _poly_money(value) -> Decimal | None:
    if isinstance(value, dict):
        value = value.get("value")
    return _dec(value)


def polymarket_fill(payload, *, quote=None, pay=None, api_limit=None) -> dict:
    """Average price, house cash the venue charged, fee, and No/Yes from a Polymarket order response."""
    found = {
        "side": "",
        "avg": "",
        "cash": "",
        "spread": "",
        "fee": "",
        "filled": False,
        "intent": "",
        "outcome_name": "",
    }

    def walk(value) -> None:
        if isinstance(value, dict):
            state = str(value.get("state") or "")
            cum = _dec(value.get("cumQuantity"))
            if "FILLED" in state or (cum is not None and cum > 0):
                found["filled"] = True
            outcome = str(value.get("outcomeSide") or "")
            if outcome == "OUTCOME_SIDE_NO":
                found["side"] = "no"
            elif outcome == "OUTCOME_SIDE_YES":
                found["side"] = "yes"
            intent = str(value.get("intent") or "")
            if "SHORT" in intent:
                found["side"] = "no"
                found["intent"] = intent
            elif "LONG" in intent:
                found["intent"] = intent
                if not found["side"]:
                    found["side"] = "yes"
            meta = value.get("marketMetadata")
            if isinstance(meta, dict) and meta.get("outcome"):
                found["outcome_name"] = str(meta.get("outcome"))
            avg = _poly_money(value.get("avgPx"))
            if avg not in (None, Decimal("0")):
                found["avg"] = str(value.get("avgPx", {}).get("value") if isinstance(value.get("avgPx"), dict) else avg)
            last = _poly_money(value.get("lastPx"))
            if last not in (None, Decimal("0")) and not found["avg"]:
                found["avg"] = str(value.get("lastPx", {}).get("value") if isinstance(value.get("lastPx"), dict) else last)
            spread = _poly_money(value.get("commissionSpreadPx"))
            if spread not in (None, Decimal("0")):
                found["spread"] = str(
                    value.get("commissionSpreadPx", {}).get("value")
                    if isinstance(value.get("commissionSpreadPx"), dict)
                    else spread
                )
            fee = value.get("commissionNotionalCollected") or value.get("commissionNotionalTotalCollected")
            fee_n = _poly_money(fee)
            if fee_n not in (None, Decimal("0")):
                found["fee"] = str(fee.get("value") if isinstance(fee, dict) else fee_n)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)
    try:
        import venue_fill_confirm

        cash = venue_fill_confirm.poly_house_cash(
            avg=found.get("avg"),
            spread=found.get("spread"),
            quote=quote,
            pay=pay,
            api_limit=api_limit,
            intent=found.get("intent") or "",
        )
        if cash is not None:
            found["cash"] = format(cash, "f")
        elif found.get("avg"):
            found["cash"] = found["avg"]
    except Exception:
        found["cash"] = found.get("spread") or found.get("avg") or ""
    confirm = None
    if isinstance(payload, dict):
        try:
            import venue_fill_confirm as _vfc

            confirm = _vfc.from_payload(payload)
        except Exception:
            confirm = payload.get("_venue_confirm") if isinstance(payload.get("_venue_confirm"), dict) else None
    if isinstance(confirm, dict) and confirm.get("house_cash") and not found.get("cash"):
        found["cash"] = str(confirm.get("house_cash"))
    return found


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _order_id_of(response) -> str:
    if not isinstance(response, dict):
        return ""
    inner = response.get("order") if isinstance(response.get("order"), dict) else None
    for node in (response, inner):
        if not isinstance(node, dict):
            continue
        for key in ("order_id", "orderId", "id"):
            value = node.get(key)
            if value not in (None, ""):
                return str(value)
    return ""


def _io_instrument(row: dict) -> str:
    request = row.get("request") if isinstance(row.get("request"), dict) else {}
    response = row.get("response") if isinstance(row.get("response"), dict) else {}
    inner = response.get("order") if isinstance(response.get("order"), dict) else response
    for src in (request, inner if isinstance(inner, dict) else {}):
        for key in ("ticker", "marketSlug", "symbol"):
            value = src.get(key)
            if value not in (None, ""):
                return str(value)
    return ""


def _ts_delta_seconds(left, right) -> float | None:
    try:
        first = datetime.fromisoformat(str(left or "").replace("Z", "+00:00"))
        second = datetime.fromisoformat(str(right or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if first.tzinfo is None:
        first = first.replace(tzinfo=ET)
    if second.tzinfo is None:
        second = second.replace(tzinfo=ET)
    return abs((first - second).total_seconds())


def _io_fill_for_sent(sent: dict, context: dict, io_by_id: dict[str, dict], io_list: list[dict], used_ids: set[str]) -> dict | None:
    """Match a send to order_io, including pending rows that never got the order id.

    21 Oct 2026 Kalshi Landaluce No stayed HTTP pending after a Drive replace
    error. The 201 fill_count 1 body was only in order_io.
    """
    order_id = str(sent.get("order_id") or "")
    if order_id and order_id in io_by_id:
        used_ids.add(order_id)
        return io_by_id[order_id]
    venue = str(sent.get("venue") or "")
    instrument = str(sent.get("instrument") or "")
    claim_ts = str(context.get("compared_at") or "")
    best_id = ""
    best_delta = None
    for row in io_list:
        if str(row.get("kind") or "") != "order":
            continue
        if str(row.get("venue") or "") != venue:
            continue
        if _io_instrument(row) != instrument:
            continue
        found_id = _order_id_of(row.get("response"))
        if not found_id or found_id in used_ids or found_id not in io_by_id:
            continue
        delta = _ts_delta_seconds(row.get("timestamp") or "", claim_ts)
        if delta is None or delta > 30:
            continue
        if best_delta is None or delta < best_delta:
            best_delta = delta
            best_id = found_id
    if best_id:
        used_ids.add(best_id)
        return io_by_id[best_id]
    return None


def _io_status() -> dict[str, dict]:
    """Order id to fill flag, average price, and fee when the saved response has them."""
    found: dict[str, dict] = {}
    for row in _load_jsonl(ORDER_IO):
        if str(row.get("kind") or "") != "order":
            continue
        response = row.get("response")
        order_id = _order_id_of(response)
        if not order_id:
            continue
        if str(row.get("venue") or "") == "polymarket":
            fill = polymarket_fill(response)
            request = row.get("request") if isinstance(row.get("request"), dict) else {}
            if "SHORT" in str(request.get("intent") or ""):
                fill["side"] = "no"
            fill["evidence"] = bool(fill.get("filled") or fill.get("avg") or fill.get("side"))
            found[order_id] = fill
            continue
        qty = Decimal("0")
        price = ""
        fee = ""
        status = ""
        evidence = False

        def walk(value) -> None:
            nonlocal qty, price, fee, status, evidence
            if isinstance(value, dict):
                seen = str(value.get("status") or value.get("state") or "")
                if seen:
                    status = seen
                    evidence = True
                number = _dec(value.get("filledQuantity") or value.get("filled_quantity") or value.get("cumQuantity") or value.get("fill_count"))
                if number is not None:
                    evidence = True
                    if number > qty:
                        qty = number
                for key in ("avgExecutionPrice", "avgPx", "averagePrice", "average_fill_price"):
                    raw = value.get(key)
                    if isinstance(raw, dict):
                        raw = raw.get("value")
                    if _dec(raw) not in (None, Decimal("0")):
                        price = str(raw)
                        evidence = True
                paid = value.get("average_fee_paid")
                if _dec(paid) not in (None, Decimal("0")):
                    fee = str(paid)
                    evidence = True
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(response)
        venue = str(row.get("venue") or "").lower()
        filled = qty > 0 if venue in {"polymarket", "poly"} else (qty >= 1 or "filled" in status.lower())
        if "cancel" in status.lower() and qty < 1:
            filled = False
        cash = ""
        request = row.get("request") if isinstance(row.get("request"), dict) else {}
        if str(row.get("venue") or "") == "kalshi" and str(request.get("side") or "").lower() == "ask":
            wire = _dec(price)
            if wire is not None:
                cash = format(ONE - wire, "f")
        found[order_id] = {"filled": filled, "avg": price, "fee": fee, "side": "", "cash": cash, "evidence": evidence}
    return found


def _send_times() -> dict[tuple, list[str]]:
    found: dict[tuple, list[str]] = {}
    if not SUPERVISOR_LOG.exists():
        return found
    for line in SUPERVISOR_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        match = SENT_LINE.match(line.strip())
        if not match:
            continue
        key = (
            match.group("venue"),
            match.group("inst"),
            match.group("side"),
            match.group("limit"),
            match.group("http"),
        )
        found.setdefault(key, []).append(match.group("ts"))
    return found


def _cells(row_html: str) -> list[str]:
    return [html.unescape(re.sub(r"<[^>]+>", "", cell)).strip() for cell in re.findall(r"<td>(.*?)</td>", row_html, flags=re.S)]


def _existing_sent(page: str) -> list[list[str]]:
    marker = page.find("<h2>Sent orders</h2>")
    if marker < 0:
        return []
    stopped = page.find("<h2>Skipped before send</h2>", marker)
    chunk = page[marker:stopped if stopped >= 0 else None]
    rows = []
    for row_html in re.findall(r"<tr>(.*?)</tr>", chunk, flags=re.S):
        cells = _cells(row_html)
        if len(cells) >= 23 and cells[0] != "Pair":
            rows.append(_coerce_existing_row(cells))
    return rows


def _skipped_html(page: str) -> str:
    marker = page.find("<h2>Skipped before send</h2>")
    if marker < 0:
        return (
            "<h2>Skipped before send</h2>"
            '<p class="note">These rows were not sent. They are separate from the sent-order table above.</p>'
            '<div class="table-wrap"><table class="sortable"><tbody>'
            '<tr><td colspan="5">No skipped rows saved on the previous page.</td></tr>'
            "</tbody></table></div>"
        )
    end = page.find("<script", marker)
    if end < 0:
        end = page.find("</body>", marker)
    return page[marker:end].strip()


def _method_notes(page: str) -> str:
    match = re.search(
        r'(<p class="note">orders.jsonl.*?</p>\s*<p class="note">The ledger also.*?</p>)',
        page,
        flags=re.S,
    )
    return match.group(1) if match else ""


def _row_key(cells: list[str]) -> tuple:
    order_id = cells[COL["Order id"]]
    if order_id:
        return ("id", order_id)
    return ("leg", cells[COL["Venue"]], cells[COL["Instrument"]], cells[COL["HTTP"]], cells[COL["Time"]])


def _collapse_same_send(rows: list[list[str]]) -> list[list[str]]:
    """Drop a second copy of the same send.

    A page rewrite used to keep an older copy when the same venue, instrument,
    limit, HTTP status, time, and order id were already on the page. The three
    Kalshi shard retries stay, because each one has its own time.
    """
    kept: list[list[str]] = []
    index_by: dict[tuple, int] = {}
    for cells in rows:
        when = cells[COL["Time"]] if len(cells) > COL["Time"] else ""
        order_id = cells[COL["Order id"]] if len(cells) > COL["Order id"] else ""
        if not when and not order_id:
            kept.append(list(cells))
            continue
        key = (
            cells[COL["Game"]],
            cells[COL["Venue"]],
            cells[COL["Instrument"]],
            cells[COL["Limit price"]],
            cells[COL["HTTP"]],
            when,
            order_id,
        )
        prior = index_by.get(key)
        if prior is None:
            index_by[key] = len(kept)
            kept.append(list(cells))
            continue
        if len(cells[COL["Note"]]) >= len(kept[prior][COL["Note"]]):
            number = kept[prior][0]
            kept[prior] = list(cells)
            kept[prior][0] = number
    for index, cells in enumerate(kept, start=1):
        cells[0] = str(index)
    return kept


def _apply_fresh_rows(existing: list[list[str]], fresh: list[list[str]]) -> list[list[str]]:
    """Keep earlier sent rows. A new result replaces the same order instead of adding a second line.

    A row written while the request is in flight has HTTP pending. The venue result
    (fill, zero fill, or 404) replaces that line. The same order id replaces its
    earlier line so a one-leg result updates the row already on the page.
    """
    rows = [_coerce_existing_row(list(cells)) for cells in existing]
    used: set[int] = set()

    def take(match) -> int | None:
        for index, cells in enumerate(rows):
            if index in used:
                continue
            if match(cells):
                return index
        return None

    added: list[list[str]] = []
    for raw in fresh:
        cells = _coerce_existing_row(list(raw))
        order_id = cells[COL["Order id"]]
        index = None
        if order_id:
            index = take(lambda old, order_id=order_id: old[COL["Order id"]] == order_id)
        if index is None and cells[COL["HTTP"]] != "pending":
            index = take(
                lambda old, cells=cells: (
                    old[COL["HTTP"]] == "pending"
                    and old[COL["Venue"]] == cells[COL["Venue"]]
                    and old[COL["Instrument"]] == cells[COL["Instrument"]]
                    and old[COL["Limit price"]] == cells[COL["Limit price"]]
                )
            )
        if index is None:
            index = take(
                lambda old, cells=cells: (
                    not old[COL["Order id"]]
                    and not cells[COL["Order id"]]
                    and old[COL["Venue"]] == cells[COL["Venue"]]
                    and old[COL["Instrument"]] == cells[COL["Instrument"]]
                    and old[COL["Limit price"]] == cells[COL["Limit price"]]
                    and old[COL["HTTP"]] == cells[COL["HTTP"]]
                    and (
                        old[COL["Time"]] == cells[COL["Time"]]
                        or old[COL["Time"]] == ""
                        or cells[COL["Time"]] == ""
                    )
                )
            )
        if index is None:
            added.append(list(cells))
            continue
        used.add(index)
        number = rows[index][0]
        rows[index] = list(cells)
        rows[index][0] = number
    start = 0
    for cells in rows:
        number = _dec(cells[0])
        if number is not None:
            start = max(start, int(number))
    for offset, cells in enumerate(added, start=1):
        cells[0] = str(start + offset)
        rows.append(cells)
    return rows


def _shown_limit(venue: str, side: str, limit: str) -> str:
    number = _dec(limit)
    if number is None:
        return limit
    if venue == "kalshi" and side == "no":
        return _money(ONE - number)
    return str(limit)


def _attempts(rows: list[dict]) -> list[tuple[dict, list[dict]]]:
    """Group sent legs by bet_key so B/C/D/E are not glued onto the prior lock claim."""
    claims: dict[str, dict] = {}
    buckets: dict[str, list[dict]] = {}
    order: list[str] = []
    anon = 0

    def take(key: str) -> list[dict]:
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        return buckets[key]

    for row in rows:
        event = row.get("event")
        key = str(row.get("bet_key") or "")
        if event == "claim":
            if not key:
                anon += 1
                key = f"anon-claim-{anon}"
            claims[key] = row
            take(key)
            continue
        if event in {"sent", "filled", "both_unfilled", "one_leg"}:
            if not key:
                anon += 1
                key = f"anon-sent-{anon}"
            take(key).append(row)
    out: list[tuple[dict, list[dict]]] = []
    for key in order:
        bucket = buckets.get(key) or []
        if not any(item.get("event") == "sent" for item in bucket):
            continue
        out.append((_attempt_context(claims.get(key) or {}, bucket), bucket))
    return out


def _fill_text(fill: dict) -> tuple[str, str, str]:
    if not fill or not fill.get("filled"):
        return "", "", "no"
    avg = fill.get("avg") or ""
    cash = fill.get("cash") or ""
    fee = fill.get("fee") or ""
    shown = avg
    if avg and cash:
        shown = f"{_four(avg)} (cash {_four(cash)})" if _dec(avg) is not None and _dec(cash) is not None else f"{avg} (cash {cash})"
    elif _dec(avg) is not None:
        shown = _four(avg)
    if _dec(fee) is not None:
        fee = _four(fee)
    elif fill.get("filled"):
        fee = ""
    return shown, fee, "yes"


def _new_sent_rows(existing: list[list[str]]) -> list[list[str]]:
    known = {_row_key(cells) for cells in existing}
    io_rows = _io_status()
    io_list = [row for row in _load_jsonl(ORDER_IO) if str(row.get("kind") or "") == "order"]
    times = _send_times()
    used_times: dict[tuple, int] = {}
    built: list[list[str]] = []
    claims = _load_jsonl(ORDERS)
    for context, events in _attempts(claims):
        sends = [item for item in events if item.get("event") == "sent"]
        terminal = next((item for item in reversed(events) if item.get("event") in {"one_leg", "both_unfilled"}), None)
        filled_keys = {
            (str(item.get("venue") or ""), str(item.get("instrument") or ""))
            for item in events
            if item.get("event") == "filled"
        }
        used_io: set[str] = set()
        send_fills = [_io_fill_for_sent(item, context, io_rows, io_list, used_io) for item in sends]
        for item, fill in zip(sends, send_fills):
            if fill and fill.get("filled"):
                filled_keys.add((str(item.get("venue") or ""), str(item.get("instrument") or "")))
        system_id = str(context.get("_system_id") or _system_id(sends[0] if sends else {}))
        system_label = str(context.get("_system_label") or SYSTEM_LABELS[system_id])
        if terminal and terminal.get("event") == "one_leg":
            filled_keys.add((str(terminal.get("venue") or ""), str(terminal.get("instrument") or "")))
            outcome = "one leg"
        elif len(filled_keys) >= 2:
            outcome = "both filled"
        elif len(filled_keys) == 1:
            outcome = "one leg"
        else:
            outcome = "neither filled"
        if system_id != "lock":
            outcome = "filled" if filled_keys else "not filled"
        game = str(context.get("game") or "")
        market = _market_from_attempt(context, sends[0] if sends else {}, system_id)
        filled_fee = ""
        second_venue = ""
        for item in events:
            if item.get("event") == "one_leg":
                second_venue = str(item.get("second_venue") or second_venue)
        poly_limit = ""
        for item, fill in zip(sends, send_fills):
            if str(item.get("venue") or "") == "polymarket" and item.get("limit_price") and not poly_limit:
                poly_limit = str(item.get("limit_price"))
            if fill and fill.get("filled"):
                filled_fee = str(fill.get("fee") or "0")
        cap_text = ""
        if second_venue and poly_limit and filled_fee != "":
            try:
                import live_lock_orders

                cap = live_lock_orders.max_leg_price(
                    second_venue,
                    Decimal(poly_limit),
                    Decimal(filled_fee),
                )
            except Exception:
                cap = None
            if cap is not None:
                second_sends = [
                    item for item in sends if str(item.get("venue") or "") == second_venue
                ]
                same_limits = {str(item.get("limit_price") or "") for item in second_sends}
                walked = "repeated the same price" if len(same_limits) <= 1 else "sent more than one price"
                no_only = second_venue == "kalshi" and {str(item.get("side") or "") for item in second_sends} == {"no"}
                if no_only:
                    asks = ", ".join(sorted(same_limits))
                    costs = []
                    for raw in sorted(same_limits):
                        number = _dec(raw)
                        costs.append(_money(ONE - number) if number is not None else raw)
                    cap_text = (
                        f"Kalshi No was sent as an ask ({asks}), which is a No cost of {', '.join(costs)}. "
                        f"Profit cap on that No cost is {format(cap, 'f')}. "
                        f"The pair {walked}. It did not walk the No cost up to the cap. "
                        "Kalshi fee is 0.07 × p × (1 − p) until POST average_fee_paid overwrites it."
                    )
                else:
                    cap_text = (
                        f"Profit cap on the {second_venue} price is {format(cap, 'f')} "
                        f"(the two prices stay under $1 and at or under ${live_lock_orders.send_line()} after the Polymarket fee "
                        f"on the sent price {poly_limit}). The pair {walked}. "
                        "It did not walk the price up to the cap. "
                        "Kalshi fee is 0.07 × p × (1 − p) until POST average_fee_paid overwrites it."
                    )
        for index, sent in enumerate(sends):
            venue = str(sent.get("venue") or "")
            instrument = str(sent.get("instrument") or "")
            json_side = str(sent.get("side") or "")
            http = str(sent.get("http_status") or "")
            order_id = str(sent.get("order_id") or "")
            limit = str(sent.get("limit_price") or "")
            time_key = (venue, instrument, json_side, limit, http)
            slots = times.get(time_key) or []
            cursor = used_times.get(time_key, 0)
            when = slots[cursor] if cursor < len(slots) else ""
            used_times[time_key] = cursor + 1
            poly = send_fills[index] if index < len(send_fills) else None
            if poly is None and order_id:
                poly = io_rows.get(order_id)
            if poly and poly.get("filled") and not order_id:
                order_id = str(next((key for key, item in io_rows.items() if item is poly), "") or "")
            if poly and poly.get("filled") and http in {"", "pending"}:
                http = "201"
            side = json_side
            if poly and poly.get("side"):
                side = poly["side"]
            display_limit = limit
            if venue == "kalshi" and json_side == "no":
                display_limit = _shown_limit("kalshi", "no", limit)
            if poly and poly.get("evidence"):
                this_filled = bool(poly.get("filled"))
            else:
                later_same = any(
                    str(later.get("venue") or "") == venue
                    and str(later.get("instrument") or "") == instrument
                    and later_i > index
                    for later_i, later in enumerate(sends)
                )
                this_filled = (venue, instrument) in filled_keys and not later_same
            fill_price, fee, filled_word = ("", "", "no")
            note_bits = []
            if this_filled and poly and poly.get("cash") and venue == "polymarket":
                fill_price, fee, filled_word = _fill_text(poly)
                short = side == "no" or "SHORT" in str(poly.get("intent") or "")
                kind = "Polymarket buy short / No" if short else "Polymarket buy long / Yes"
                who = str(poly.get("outcome_name") or "")
                who_bit = f" Outcome {who}." if who else ""
                note_bits.append(
                    f"{kind}.{who_bit} Average price {poly.get('avg')}. "
                    f"Cash/spread {poly.get('cash')}. Fee {fee or 'fee unknown'}."
                )
            elif this_filled:
                filled_word = "yes"
                if poly and poly.get("avg"):
                    if venue == "kalshi" and json_side == "no" and poly.get("cash"):
                        fill_price = f"{poly.get('avg')} (cash {poly.get('cash')})"
                    else:
                        fill_price = str(poly.get("avg"))
                else:
                    matched = next(
                        (
                            item for item in events
                            if item.get("event") == "filled"
                            and str(item.get("venue") or "") == venue
                            and str(item.get("instrument") or "") == instrument
                        ),
                        None,
                    )
                    if matched and matched.get("price"):
                        fill_price = str(matched.get("price"))
                if sent.get("fee") not in (None, ""):
                    fee = str(sent.get("fee"))
                elif poly and poly.get("fee"):
                    fee = str(poly.get("fee"))
                else:
                    fee = _formula_fee(venue, fill_price or sent.get("wire") or display_limit, sent)
            sent_note = str(sent.get("note") or "")
            step = str(sent.get("step") or "")
            attempt = sent.get("attempt")
            if step or attempt:
                note_bits.append(
                    f"Step {step or 'unknown'}, attempt {attempt or 1}."
                )
            if http not in {"", "200", "201"} and sent_note and sent_note != "no message":
                note_bits.append(sent_note)
            if cap_text and str(sent.get("venue") or "") == second_venue:
                note_bits.append(cap_text)
            if outcome == "one leg":
                note_bits.append("The pair did not both fill.")
            elif outcome == "neither filled":
                note_bits.append("Neither leg filled.")
            elif outcome == "both filled":
                note_bits.append("Both legs filled.")
            others = [
                other for other_i, other in enumerate(sends)
                if other_i != index and str(other.get("venue") or "") != venue
            ]
            if not others:
                others = [other for other_i, other in enumerate(sends) if other_i != index]
            if others:
                other = others[-1]
                other_venue = str(other.get("venue") or "")
                other_side = str(other.get("side") or "")
                other_limit = str(other.get("limit_price") or "")
                other_id = str(other.get("order_id") or "")
                other_index = sends.index(other) if other in sends else -1
                other_poly = send_fills[other_index] if 0 <= other_index < len(send_fills) else None
                if other_poly is None and other_id:
                    other_poly = io_rows.get(other_id)
                if other_poly and other_poly.get("side"):
                    other_side = other_poly["side"]
                pair_limit = _shown_limit(other_venue, "no" if other_venue == "kalshi" and str(other.get("side") or "") == "no" else other_side, other_limit)
                if other_venue == "kalshi" and str(other.get("side") or "") == "no":
                    pair_limit = _shown_limit("kalshi", "no", other_limit)
                    note_bits.append(f"Kalshi No price {pair_limit} was sent as ask {other_limit}.")
                pair_fill, pair_fee, pair_filled = ("", "", "no")
                if other_poly and other_poly.get("evidence") and other_poly.get("filled"):
                    if other_poly.get("cash"):
                        pair_fill, pair_fee, pair_filled = _fill_text(other_poly)
                    else:
                        pair_filled = "yes"
                        pair_fill = str(other_poly.get("avg") or "")
                        pair_fee = str(other.get("fee") or other_poly.get("fee") or "") or _formula_fee(
                            other_venue, pair_fill or other.get("wire") or pair_limit, other
                        )
                elif other_poly and other_poly.get("evidence") and not other_poly.get("filled"):
                    pair_filled = "no"
                elif (other_venue, str(other.get("instrument") or "")) in filled_keys:
                    pair_filled = "yes"
                    if other.get("fee") not in (None, ""):
                        pair_fee = str(other.get("fee"))
                    else:
                        pair_fee = _formula_fee(other_venue, other.get("wire") or pair_limit, other)
                pair_http = str(other.get("http_status") or "")
                if pair_filled != "yes":
                    note_bits.append(f"{other_venue} HTTP {pair_http} not filled.")
                pair_cells = [
                    other_venue,
                    str(other.get("instrument") or ""),
                    other_side,
                    pair_limit,
                    pair_fill,
                    _fee_cell(pair_filled == "yes", pair_fee),
                    pair_filled,
                ]
            else:
                pair_cells = ["", "", "", "not sent", "", "", "no"]
                if system_id == "lock":
                    note_bits.append("Pair leg was not sent.")
                else:
                    note_bits.append("One-Yes system; no opposite lock pair.")
                other = None
                other_poly = None
            if venue == "kalshi" and json_side == "no":
                note_bits.append(f"Kalshi No price {display_limit} was sent as ask {limit}. HTTP {http}.")
            trigger_bits = [
                str(sent.get("trigger_venue") or context.get("trigger_venue") or ""),
                str(sent.get("trigger_side") or context.get("trigger_side") or ""),
                str(sent.get("trigger_price") or context.get("trigger_price") or ""),
                str(sent.get("trigger_seen_at") or context.get("trigger_seen_at") or ""),
            ]
            trigger_text = " ".join(part for part in trigger_bits if part)
            quote_seen = str(sent.get("quote_seen_at") or "")
            sent_at = str(sent.get("sent_at") or when)
            if sent_at:
                when = sent_at
            filled_yes = filled_word == "yes"
            fee_shown = _fee_cell(filled_yes, fee)
            if filled_yes and sent.get("after_fee") not in (None, ""):
                after = _four(sent.get("after_fee"))
            else:
                after = _after_fee_cell(filled_yes, _wire_of(fill_price, sent, poly), fee)
            pair_after = ""
            if other is not None and pair_cells[6] == "yes":
                if other.get("after_fee") not in (None, ""):
                    pair_after = _four(other.get("after_fee"))
                else:
                    pair_after = _after_fee_cell(
                        True,
                        _wire_of(pair_cells[4], other, other_poly),
                        pair_fee if pair_fee not in (None, "", "fee unknown") else pair_cells[5],
                    )
            cells = _pad_cells([
                "",
                system_label,
                game,
                market,
                side,
                venue,
                instrument,
                display_limit,
                fill_price,
                fee_shown,
                str(sent.get("size") or "1"),
                filled_word,
                http,
                *pair_cells,
                outcome,
                when,
                order_id,
                " ".join(bit for bit in note_bits if bit),
                str(sent.get("quote_source") or sent.get("step") or ""),
                str(sent.get("quote_price") or display_limit),
                quote_seen,
                str(sent.get("lag_seconds") or ""),
                trigger_text,
                after,
                pair_after,
            ])
            key = _row_key(cells)
            if key in known:
                continue
            known.add(key)
            built.append(cells)
    return built


def _summarize(rows: list[list[str]]) -> dict[str, int]:
    filled = sum(1 for cells in rows if cells[COL["Filled"]] == "yes")
    neither = sum(1 for cells in rows if cells[COL["Outcome"]] == "neither filled")
    one_keys = set()
    both_keys = set()
    by_system: dict[str, int] = {label: 0 for label in SYSTEM_LABELS.values()}
    for cells in rows:
        label = cells[COL["System"]] if len(cells) > COL["System"] else ""
        if label in by_system:
            by_system[label] += 1
        elif label:
            by_system[label] = by_system.get(label, 0) + 1
        key = (
            cells[COL["Game"]],
            cells[COL["Market"]],
            frozenset(part for part in (cells[COL["Instrument"]], cells[COL["Pair instrument"]]) if part),
        )
        if cells[COL["Outcome"]] == "one leg":
            one_keys.add(key)
        elif cells[COL["Outcome"]] == "both filled":
            both_keys.add(key)
    return {
        "pairs": neither + len(one_keys) + len(both_keys),
        "both": len(both_keys),
        "one": len(one_keys),
        "neither": neither,
        "sent": len(rows),
        "filled": filled,
        "unfilled": len(rows) - filled,
        "by_system": by_system,
    }


def _th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" aria-sort="none">'
        f"{_esc(label)}<span class=\"sort-ind\"></span></th>"
    )


def _tr(cells: list[str]) -> str:
    return "<tr>" + "".join(f"<td>{_esc(cell)}</td>" for cell in cells) + "</tr>"


def write_page() -> Path:
    """Refresh orders.html. Keeps prior sent rows and appends posted orders that are missing."""
    with venue_pace.FileLock(PAGE_LOCK):
        previous = PAGE.read_text(encoding="utf-8") if PAGE.exists() else ""
        existing = [
            row for row in _existing_sent(previous)
            if row[COL["System"]] in SYSTEM_LABEL_SET
        ]
        sent = [
            _decorate_sports_cells(row)
            for row in _collapse_same_send(_apply_fresh_rows(existing, _new_sent_rows([])))
        ]
        summary = _summarize(sent)
        notes = _method_notes(previous)
        extra = (
            '<p class="note">A posted order rewrites this page. '
            "This table is every sent order from A–E, not lock-only. "
            "System is A Lock gap, B Tennis crossover, C CFB favorite, D T0 spreads, or E Tennis T0 dog. "
            "Polymarket short fills use the order response: average price, cash/spread price, and fee. "
            "After-fee (all-in) is wire plus fee. Kalshi POST average_fee_paid overwrites the 0.07 × p × (1 − p) estimate. "
            "If we only have a wire, that cell says fee unknown, not 0. "
            "A one-leg result stays on the row, including a Kalshi HTTP 404. "
            "The stop latch is not cleared from this page.</p>"
        )
        if "every sent order from A–E" not in notes:
            notes = f"{notes}\n{extra}" if notes else extra
        skipped = _skipped_html(previous)
        skip_count = max(skipped.count("<tr>") - 1, 0)
        by_system = summary.get("by_system") or {}
        system_line = ", ".join(
            f"{_esc(label)} {int(by_system.get(label) or 0)}"
            for label in SYSTEM_LABELS.values()
        )
        table = (
            '<div class="table-wrap"><table class="sortable"><thead><tr>'
            + "".join(_th(label, kind) for label, kind in COLUMNS)
            + "</tr></thead><tbody>"
            + "".join(_tr(cells) for cells in sent)
            + "</tbody></table></div>"
        )
        body = f"""
<h1>Order ledger</h1>
<p class="note">America/New_York. Read at {_esc(_now())}. This page does not send orders.</p>
<div class="callout"><h2>What you asked</h2><p>{_esc(ASKED)}</p><p>{_esc(ASKED_PRIOR)}</p><p>{_esc(ASKED_LATEST)}</p></div>
<div class="callout"><h2>In plain English</h2><p>{_esc(PLAIN)}</p></div>
<h2>Summary</h2>
<ul>
<li>Sent orders by system: {system_line}</li>
<li>Pairs attempted (lock A, sent at least one order): {summary['pairs']}</li>
<li>Both filled: {summary['both']}</li>
<li>One leg: {summary['one']}</li>
<li>Neither filled: {summary['neither']}</li>
<li>Sent orders: {summary['sent']} ({summary['filled']} filled, {summary['unfilled']} not filled)</li>
<li>Skipped before send: {skip_count} (not in the sent table)</li>
</ul>
{notes}
<p class="note">Click column headers to sort.</p>
{SWIPE_NOTE_HTML}
<h2>Sent orders</h2>
{table}
{skipped}
"""
        page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Order ledger</title>
<style>
body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 1.2rem; color: #1e293b; background: #fff; }}
h1 {{ font-size: 1.45rem; margin-bottom: 0.3rem; }}
h2 {{ font-size: 1.05rem; margin: 1.2rem 0 0.4rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 0 0 12px; }}
.callout h2 {{ margin: 0 0 6px; }}
.note {{ color: #475569; font-size: 14px; }}
ul {{ margin-top: 0.3rem; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
{body}
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
        PAGE.parent.mkdir(parents=True, exist_ok=True)
        tmp = PAGE.with_suffix(".html.tmp")
        tmp.write_text(page, encoding="utf-8")
        tmp.replace(PAGE)
        return PAGE
