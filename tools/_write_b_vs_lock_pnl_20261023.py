"""Whole live book: Strategy B vs lock bot realized cash with fees.

Truth = venue fill history + fees, matched to local order ids.
Read-only. Does not place, cancel, sell, GTC, commit, or start a second B.
Does not change D=0.25 or NET_MAX. No secrets printed.
"""
from __future__ import annotations

import html
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import gemini_private  # noqa: E402
import kalshi_private  # noqa: E402
import novig_live  # noqa: E402
import polymarket_us_live  # noqa: E402
from order_ledger import (  # noqa: E402
    ORDERS,
    ORDER_IO,
    _io_instrument,
    _load_jsonl,
    _order_id_of,
    polymarket_fill,
)
from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW  # noqa: E402
from report_page_extras import (  # noqa: E402
    CACHE_META,
    FORCE_RELOAD_SCRIPT,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "b_vs_lock_pnl_20261023.html"
EXTRACT = RAW / "b_vs_lock_pnl_extract_20261023.json"
WINDOW_START = datetime(2026, 10, 18, 0, 0, tzinfo=ET)
ONE = Decimal("1")
CENT = Decimal("0.01")
FOUR = Decimal("0.0001")
MAX_PAGES = 50
B_STEPS = {"b-t0", "b-cross", "b-leftover-yes", "b-fav"}
SECRET_NEEDLES = (
    "api_key",
    "apikey",
    "secret",
    "signature",
    "passphrase",
    "private_key",
    "authorization",
    "access_key",
    "token",
)
ASKED = (
    "in general, has Strategy B made us more than our lock gap? Whole live book, "
    "not one match. Truth = venue fill history + fees, attributed to Strategy B vs "
    "lock bot. Report WITH fees. Window: first live send through now (ET). Never "
    "count lock leftover/flatten as B. Fernandez/Alexandrova textbook B; Trungelliti "
    "duplicate extra Dodig is B (bug); Moutet T0 is B; Moutet 10:47–10:51 lock is lock. "
    "Alves/Zarate three gap+flatten is lock. Open leftovers: mark still-open separately."
)
PLAIN = (
    "Two bots can spend money on the same tennis match. Strategy B, at the first trusted "
    "start, buys one Yes on each player (a Yes pays $1 if that person wins). Later it may "
    "buy one more of the original underdog if he prints above 50¢, then one more of the "
    "original favorite when those two extras still lock about 25¢. The lock bot is separate: "
    "it tries to buy Yes in one shop and No in the other on the same result when the two "
    "prices plus fees still cost at most 98.4¢. If only one side fills, it flattens "
    "(closes the leftover). This page adds up every real fill from Kalshi, Polymarket US, "
    "Gemini, and Novig, with the fees those shops charged, from the first live send through "
    "now. It does not guess a result for a ticket that is still open."
)


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def ddec(value):
    if value is None or value == "":
        return None
    if isinstance(value, dict):
        value = value.get("value")
    try:
        return Decimal(str(value))
    except Exception:
        return None


def parse_dt(value):
    text = str(value or "").strip()
    if not text:
        return None
    if text.isdigit():
        raw = int(text)
        if raw > 10**12:
            stamp = datetime.fromtimestamp(raw / 1000, tz=timezone.utc)
        else:
            stamp = datetime.fromtimestamp(raw, tz=timezone.utc)
        return stamp.astimezone(ET)
    text = text.replace("Z", "+00:00")
    if "." in text:
        head, rest = text.split(".", 1)
        frac = ""
        tzpart = ""
        for i, ch in enumerate(rest):
            if ch.isdigit():
                frac += ch
            else:
                tzpart = rest[i:]
                break
        frac = (frac + "000000")[:6]
        text = head + "." + frac + tzpart
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=ET)
    return stamp.astimezone(ET)


def et_text(stamp) -> str:
    if stamp is None:
        return ""
    return stamp.astimezone(ET).strftime("%Y-%m-%d %H:%M:%S")


def money(value) -> str:
    if value is None:
        return "open — not invented"
    number = Decimal(str(value)).quantize(FOUR)
    if number < 0:
        return f"-${abs(number)}"
    if number > 0:
        return f"+${number}"
    return "$0.0000"


def qty_pos(qty) -> bool:
    number = ddec(qty)
    return number is not None and number > 0


def redact(obj):
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            lowered = str(key).lower().replace("-", "_")
            if any(needle in lowered for needle in SECRET_NEEDLES):
                out[key] = "[redacted]"
            else:
                out[key] = redact(value)
        return out
    if isinstance(obj, list):
        return [redact(item) for item in obj]
    return obj


def gemini_taker_fee(price: Decimal) -> Decimal:
    raw = Decimal("0.07") * price * (ONE - price)
    if raw < 0:
        raw = Decimal("0")
    return raw.quantize(CENT, rounding=ROUND_CEILING)


def amount_value(node):
    if isinstance(node, dict):
        return node.get("value")
    return node


def collect_ids(node) -> set[str]:
    found: set[str] = set()

    def keep(text: str):
        text = str(text or "").strip()
        if not text or text.lower() in {"none", "null", "true", "false"}:
            return
        if len(text) < 8 or len(text) > 80:
            return
        if "{" in text or " " in text:
            return
        found.add(text)

    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                low = str(key).lower().replace("-", "_")
                if low in {"id", "orderid", "order_id", "clientorderid", "tradeid", "trade_id", "fillid", "fill_id"} or low.endswith("orderid"):
                    keep(child)
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(node)
    return found


def blob_of(row: dict) -> str:
    return json.dumps(row, default=str).lower()


def game_norm(name: str) -> str:
    text = " ".join(str(name or "").replace("@", " vs ").split())
    return text


def named_game(blob: str) -> str:
    low = blob.lower()
    if "ferale" in low or "leyfer-ekaale" in low or ("fernandez" in low and "alexandrova" in low):
        return "Leylah Fernandez vs Ekaterina Alexandrova"
    if "trudod" in low or "martru-matdod" in low or ("trungelliti" in low and "dodig" in low):
        return "Marco Trungelliti vs Matej Dodig"
    if "moupau" in low or "cormou-tompau" in low or ("moutet" in low and "paul" in low):
        return "Corentin Moutet vs Tommy Paul"
    if "melzar" in low or "felalv-carzar" in low or ("zarate" in low and ("meligeni" in low or "alves" in low)):
        return "Felipe Meligeni Alves vs Carlos Maria Zarate"
    if "rodbue" in low or ("taverna" in low and "bueno" in low):
        return "Santiago Rodriguez Taverna vs Gonzalo Bueno"
    return ""


def kalshi_event(ticker: str) -> str:
    text = str(ticker or "")
    if text.count("-") < 2:
        return text
    head, tail = text.rsplit("-", 1)
    if 2 <= len(tail) <= 4 and tail.isalpha():
        return head
    return text


def moutet_lock_window(stamp) -> bool:
    if stamp is None:
        return False
    local = stamp.astimezone(ET)
    if local.date().isoformat() != "2026-10-23":
        return False
    clock = local.strftime("%H:%M")
    return "10:40" <= clock <= "10:56"


def moutet_t0_window(stamp) -> bool:
    if stamp is None:
        return False
    local = stamp.astimezone(ET)
    if local.date().isoformat() != "2026-10-23":
        return False
    clock = local.strftime("%H:%M")
    return "07:55" <= clock <= "08:10"


def is_b_tape(row: dict) -> bool:
    key = str(row.get("bet_key") or row.get("key") or "")
    step = str(row.get("step") or "")
    if row.get("_strategy_b") or row.get("strategy") in (True, "b", "B", "strategy_b"):
        return True
    if key.startswith("tennis-b") or step.startswith("b-") or step in B_STEPS:
        return True
    return False


def is_flatten_tape(row: dict) -> bool:
    event = str(row.get("event") or row.get("kind") or "").lower()
    intent = str(row.get("intent") or row.get("flatten") or "").lower()
    if row.get("flatten") or row.get("is_flatten"):
        return True
    if "flatten" in event or "flatten" in intent or event in {"leftover", "one_leg"}:
        return True
    return False


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
    if not body:
        body.append("<tr>" + "".join("<td></td>" for _ in headers) + "</tr>")
    return (
        f"{SWIPE_NOTE_HTML}<div class=\"table-wrap\"><table class=\"sortable\">"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def kalshi_fee(fill: dict) -> Decimal:
    for key in ("fee_cost", "taker_fee_dollars", "taker_fees", "fees", "fee"):
        number = ddec(fill.get(key))
        if number is not None and number >= 0:
            return number
    return Decimal("0")


def kalshi_row(fill: dict) -> dict:
    yes_px = ddec(fill.get("yes_price_dollars") or fill.get("yes_price"))
    no_px = ddec(fill.get("no_price_dollars") or fill.get("no_price"))
    if yes_px is not None and yes_px > 1:
        yes_px = yes_px / Decimal("100")
    if no_px is not None and no_px > 1:
        no_px = no_px / Decimal("100")
    outcome = str(fill.get("outcome_side") or fill.get("side") or "").lower()
    action = str(fill.get("action") or "").lower()
    book = str(fill.get("book_side") or "").lower()
    qty = ddec(fill.get("count_fp") or fill.get("count")) or Decimal("0")
    fee = kalshi_fee(fill)
    stamp = parse_dt(fill.get("created_time") or fill.get("ts"))
    # Kalshi side/outcome_side is Yes vs No. Sold Yes (leftover No) has side=no.
    # Cash identity: buy Yes pays yes+fee; sell Yes receives yes−fee. Flatten is that round-trip.
    sell = outcome == "no" or action == "sell" or book in {"ask", "sell"}
    if action == "buy" and outcome == "yes":
        sell = False
    if action == "buy" and outcome == "no":
        sell = True
    px = yes_px if yes_px is not None else Decimal("0")
    house_cash = no_px if sell and no_px is not None else px
    if sell:
        yes_signed = -qty
        cash = (px * qty) - fee
    else:
        yes_signed = qty
        cash = -(px * qty) - fee
    return {
        "venue": "kalshi",
        "time_et": et_text(stamp),
        "stamp": stamp.isoformat() if stamp else "",
        "ticker": str(fill.get("ticker") or fill.get("market_ticker") or ""),
        "side": outcome or action or book,
        "sell": sell,
        "action": action,
        "book_side": book,
        "qty": str(qty),
        "yes_wire": str(yes_px) if yes_px is not None else "",
        "no_price": str(no_px) if no_px is not None else "",
        "house_cash": str(house_cash) if house_cash is not None else "",
        "fee": str(fee),
        "cash_flow": str(cash),
        "yes_signed": str(yes_signed),
        "order_id": str(fill.get("order_id") or ""),
        "fill_id": str(fill.get("fill_id") or fill.get("trade_id") or ""),
        "settled_flag": fill.get("settled"),
        "ids": sorted(collect_ids(fill)),
    }


def gemini_row(order: dict) -> dict:
    qty = ddec(order.get("filledQuantity") or order.get("filled_quantity") or order.get("originalQuantity")) or Decimal("0")
    stamp = parse_dt(order.get("updatedAt") or order.get("createdAt") or order.get("timestamp"))
    meta = order.get("contractMetadata") if isinstance(order.get("contractMetadata"), dict) else {}
    price = ddec(order.get("avgExecutionPrice") or order.get("avgFillPrice") or order.get("price")) or Decimal("0")
    fee = ddec(order.get("fee") or order.get("takerFee") or order.get("commission"))
    if fee is None and price > 0:
        fee = gemini_taker_fee(price)
        fee_src = "documented 0.07×p×(1−p) ceil cent"
    else:
        fee_src = "venue field" if fee is not None else "none"
        fee = fee or Decimal("0")
    cash = -(price * qty) - fee
    side = str(order.get("side") or "").lower()
    outcome = str(order.get("outcome") or meta.get("outcome") or "").lower()
    yes_signed = qty if "no" not in outcome and side != "sell" else -qty
    if "no" in outcome or side in {"sell", "short"}:
        yes_signed = -qty
        # Gemini buy No still pays the No price.
    return {
        "venue": "gemini",
        "time_et": et_text(stamp),
        "stamp": stamp.isoformat() if stamp else "",
        "ticker": str(order.get("symbol") or ""),
        "side": side,
        "outcome": str(order.get("outcome") or meta.get("outcome") or ""),
        "qty": str(qty),
        "price": str(price),
        "fee": str(fee),
        "fee_src": fee_src,
        "cash_flow": str(cash),
        "yes_signed": str(yes_signed),
        "status": str(order.get("status") or ""),
        "order_id": str(order.get("orderId") or order.get("clientOrderId") or ""),
        "event": str(meta.get("eventName") or meta.get("eventTicker") or ""),
        "resolution": str(meta.get("resolutionSide") or ""),
        "title": str(meta.get("eventName") or ""),
        "ids": sorted(collect_ids(order)),
        "raw_keys": sorted(order.keys())[:40],
    }


def _poly_order(trade: dict) -> dict:
    for key in ("aggressorExecution", "takerExecution", "execution"):
        node = trade.get(key)
        if isinstance(node, dict) and isinstance(node.get("order"), dict):
            return node["order"]
        if isinstance(node, dict) and node.get("id"):
            return node
    return {}


def poly_row(activity: dict) -> dict:
    trade = activity.get("trade") if isinstance(activity.get("trade"), dict) else {}
    order = _poly_order(trade)
    qty = ddec(trade.get("qtyDecimal") or trade.get("qty") or order.get("cumQuantity")) or Decimal("0")
    stamp = parse_dt(
        trade.get("createTime")
        or trade.get("updateTime")
        or order.get("createTime")
        or order.get("lastTransactTime")
        or order.get("insertTime")
        or activity.get("createTime")
    )
    price = ddec(amount_value(trade.get("price")) or amount_value(order.get("avgPx")))
    cost = ddec(amount_value(trade.get("costBasis") or trade.get("cost")))
    fee = ddec(
        amount_value(trade.get("commissionNotionalCollected"))
        or amount_value(order.get("commissionNotionalTotalCollected"))
        or amount_value(order.get("commissionNotionalCollected"))
    )
    spread = ddec(amount_value(order.get("commissionSpreadPx")))
    meta = order.get("marketMetadata") if isinstance(order.get("marketMetadata"), dict) else {}
    if not meta:
        meta = trade.get("marketMetadata") if isinstance(trade.get("marketMetadata"), dict) else {}
    intent = str(order.get("intent") or trade.get("intent") or activity.get("intent") or "")
    side = str(order.get("side") or trade.get("side") or activity.get("side") or "")
    outcome = str(meta.get("outcome") or trade.get("outcome") or "")
    short = "SHORT" in intent.upper() or str(order.get("outcomeSide") or "") == "OUTCOME_SIDE_NO"
    if fee is None:
        fee = Decimal("0")
    if cost is None:
        if short and spread is not None:
            cost = (spread * qty) + fee
        elif price is not None:
            cost = (price * qty) + fee
        else:
            cost = Decimal("0")
    cash = -cost
    yes_signed = -qty if short else qty
    oid = str(order.get("id") or trade.get("orderId") or trade.get("order_id") or "")
    title = str(meta.get("title") or "")
    return {
        "venue": "polymarket",
        "time_et": et_text(stamp),
        "stamp": stamp.isoformat() if stamp else "",
        "ticker": str(trade.get("marketSlug") or order.get("marketSlug") or activity.get("marketSlug") or ""),
        "type": str(activity.get("type") or ""),
        "intent": intent,
        "side": side,
        "outcome": outcome,
        "qty": str(qty),
        "price": str(price) if price is not None else "",
        "cost": str(cost),
        "fee": str(fee),
        "cash_flow": str(cash),
        "yes_signed": str(yes_signed),
        "short": short,
        "aggressor": trade.get("isAggressor"),
        "state": str(trade.get("state") or order.get("state") or ""),
        "order_id": oid,
        "trade_id": str(trade.get("id") or ""),
        "title": title,
        "ids": sorted(collect_ids({"order": order, "trade_id": trade.get("id"), "oid": oid})),
    }


def novig_row(fill: dict) -> dict:
    native = ddec(fill.get("qty")) or Decimal("0")
    qty = (native / Decimal("100")) if native >= 50 else native
    cost = ddec(fill.get("cost")) or Decimal("0")
    fee = ddec(fill.get("fee")) or Decimal("0")
    price = None
    if native not in (None, Decimal("0")):
        price = (Decimal("100") * cost) / native if native else None
    stamp = parse_dt(fill.get("ts"))
    cash = -cost - fee
    return {
        "venue": "novig",
        "time_et": et_text(stamp),
        "stamp": stamp.isoformat() if stamp else "",
        "ticker": str(fill.get("marketId") or ""),
        "outcome_id": str(fill.get("outcomeId") or ""),
        "qty": str(qty),
        "native_qty": str(native),
        "cost": str(cost),
        "price": str(price) if price is not None else "",
        "fee": str(fee),
        "cash_flow": str(cash),
        "yes_signed": str(qty),
        "order_id": str(fill.get("orderId") or ""),
        "fill_id": str(fill.get("fillId") or ""),
        "ids": sorted(collect_ids(fill)),
    }


def pull_kalshi(now: datetime) -> dict:
    fills = []
    pages = []
    cursor = ""
    query_base = {
        "min_ts": str(int(WINDOW_START.timestamp())),
        "max_ts": str(int(now.timestamp()) + 60),
        "limit": "200",
    }
    try:
        for _ in range(MAX_PAGES):
            query = dict(query_base)
            if cursor:
                query["cursor"] = cursor
            status, text = kalshi_private.get_fills(query, timeout=30)
            page = {"http": status, "bytes": len(text or "")}
            if status != 200:
                pages.append(page | {"error": "http", "body_prefix": (text or "")[:160]})
                break
            data = json.loads(text) if text else {}
            batch = data.get("fills") if isinstance(data, dict) else None
            if not isinstance(batch, list):
                pages.append(page | {"error": "shape"})
                break
            rows = [kalshi_row(item) for item in batch if isinstance(item, dict)]
            fills.extend(rows)
            cursor = str((data or {}).get("cursor") or "")
            pages.append(page | {"n": len(rows), "cursor_next": bool(cursor)})
            if not cursor or not batch:
                break
        called = True
        note = ""
    except Exception as exc:
        called = False
        note = type(exc).__name__
        pages.append({"http": 0, "error": type(exc).__name__})
    kept = [row for row in fills if qty_pos(row.get("qty"))]
    return {
        "called": called,
        "endpoint": "GET /trade-api/v2/portfolio/fills",
        "http_pages": pages,
        "n": len(fills),
        "n_pos": len(kept),
        "note": note,
        "fills": kept,
    }


def pull_gemini(now: datetime) -> dict:
    extra = {
        "status": "filled",
        "from": int(WINDOW_START.timestamp() * 1000),
        "to": int(now.timestamp() * 1000) + 1000,
        "limit": 1000,
    }
    try:
        status, text = gemini_private.get_order_history(extra, timeout=30)
        called = True
        note = ""
    except Exception as exc:
        return {
            "called": False,
            "endpoint": "POST /v1/prediction-markets/orders/history",
            "http_pages": [{"http": 0, "error": type(exc).__name__}],
            "n": 0,
            "n_pos": 0,
            "note": type(exc).__name__,
            "fills": [],
        }
    try:
        data = json.loads(text) if text else {}
    except json.JSONDecodeError:
        data = {}
    orders = data.get("orders") if isinstance(data, dict) else None
    if not isinstance(orders, list):
        orders = []
    rows = [gemini_row(item) for item in orders if isinstance(item, dict)]
    kept = [row for row in rows if qty_pos(row.get("qty"))]
    return {
        "called": called,
        "endpoint": "POST /v1/prediction-markets/orders/history",
        "http_pages": [{"http": status, "n": len(rows), "bytes": len(text or "")}],
        "n": len(rows),
        "n_pos": len(kept),
        "note": note,
        "fills": kept,
    }


def pull_polymarket(now: datetime) -> dict:
    fills = []
    pages = []
    cursor = ""
    try:
        for _ in range(MAX_PAGES):
            query = {
                "limit": "100",
                "types": "ACTIVITY_TYPE_TRADE",
                "sortOrder": "SORT_ORDER_DESCENDING",
            }
            if cursor:
                query["cursor"] = cursor
            status, text = polymarket_us_live.get_activities(query, timeout=30)
            page = {"http": status, "bytes": len(text or "")}
            if status != 200:
                pages.append(page | {"error": "http", "body_prefix": (text or "")[:160]})
                break
            data = json.loads(text) if text else {}
            batch = data.get("activities") if isinstance(data, dict) else None
            if not isinstance(batch, list):
                pages.append(page | {"error": "shape"})
                break
            stop = False
            kept = 0
            for item in batch:
                if not isinstance(item, dict):
                    continue
                trade = item.get("trade") if isinstance(item.get("trade"), dict) else {}
                stamp = parse_dt(trade.get("createTime") or trade.get("updateTime"))
                if stamp is not None and stamp < WINDOW_START:
                    stop = True
                    continue
                if stamp is not None and stamp > now:
                    continue
                row = poly_row(item)
                if row.get("aggressor") is False:
                    continue
                fills.append(row)
                kept += 1
            cursor = str((data or {}).get("nextCursor") or "")
            eof = bool((data or {}).get("eof"))
            pages.append(page | {"n": kept, "eof": eof, "cursor_next": bool(cursor)})
            if eof or not cursor or stop or not batch:
                break
        called = True
        note = ""
    except Exception as exc:
        called = False
        note = type(exc).__name__
        pages.append({"http": 0, "error": type(exc).__name__})
    kept_rows = [row for row in fills if qty_pos(row.get("qty"))]
    return {
        "called": called,
        "endpoint": "GET /v1/portfolio/activities",
        "http_pages": pages,
        "n": len(fills),
        "n_pos": len(kept_rows),
        "note": note,
        "fills": kept_rows,
    }


def _novig_items(payload):
    if not isinstance(payload, dict):
        return [], ""
    if isinstance(payload.get("items"), list):
        return payload.get("items"), str(payload.get("next") or "")
    items = []
    next_cursor = ""
    for value in payload.values():
        if isinstance(value, dict) and isinstance(value.get("items"), list):
            items.extend(row for row in value["items"] if isinstance(row, dict))
            next_cursor = str(value.get("next") or next_cursor)
    return items, next_cursor


def pull_novig(now: datetime) -> dict:
    fills = []
    pages = []
    cursor = ""
    query_base = {
        "limit": "200",
        "startsAfter": str(int(WINDOW_START.timestamp() * 1000) - 1),
        "startsBefore": str(int(now.timestamp() * 1000) + 1000),
    }
    try:
        for _ in range(MAX_PAGES):
            query = dict(query_base)
            if cursor:
                query["after"] = cursor
            status, text = novig_live.list_fills(query, timeout=30)
            page = {"http": status, "bytes": len(text or "")}
            if status != 200:
                pages.append(page | {"error": "http", "body_prefix": (text or "")[:160]})
                break
            data = json.loads(text) if text else {}
            batch, next_cursor = _novig_items(data)
            rows = [novig_row(item) for item in batch if isinstance(item, dict)]
            fills.extend(rows)
            pages.append(page | {"n": len(rows), "cursor_next": bool(next_cursor)})
            cursor = next_cursor
            if not cursor or not batch:
                break
        called = True
        note = ""
    except Exception as exc:
        called = False
        note = type(exc).__name__
        pages.append({"http": 0, "error": type(exc).__name__})
    kept = [row for row in fills if qty_pos(row.get("qty"))]
    return {
        "called": called,
        "endpoint": "GET /v3/portfolio/fills",
        "http_pages": pages,
        "n": len(fills),
        "n_pos": len(kept),
        "note": note,
        "fills": kept,
    }


def pull_kalshi_positions() -> dict:
    try:
        status, text = kalshi_private.signed_call(
            "GET",
            "/trade-api/v2/portfolio/positions",
            query={"limit": "1000", "count_filter": "position"},
            timeout=30,
        )
        data = json.loads(text) if text and status == 200 else {}
    except Exception as exc:
        return {"http": 0, "error": type(exc).__name__, "rows": []}
    rows = []
    for item in data.get("market_positions") or []:
        if not isinstance(item, dict):
            continue
        pos = ddec(item.get("position_fp") or item.get("position")) or Decimal("0")
        if pos == 0:
            continue
        rows.append(
            {
                "ticker": item.get("ticker"),
                "position": str(pos),
                "exposure": item.get("market_exposure_dollars"),
                "fees": item.get("fees_paid_dollars"),
                "realized": item.get("realized_pnl_dollars"),
                "unrealized": item.get("unrealized_pnl_dollars"),
            }
        )
    return {"http": status, "n": len(rows), "rows": rows, "endpoint": "GET /trade-api/v2/portfolio/positions"}


def pull_kalshi_settlements() -> dict:
    rows = []
    pages = []
    cursor = ""
    try:
        for _ in range(MAX_PAGES):
            query = {"limit": "200"}
            if cursor:
                query["cursor"] = cursor
            status, text = kalshi_private.signed_call(
                "GET",
                "/trade-api/v2/portfolio/settlements",
                query=query,
                timeout=30,
            )
            page = {"http": status, "bytes": len(text or "")}
            if status != 200:
                pages.append(page | {"error": "http", "body_prefix": (text or "")[:160]})
                break
            data = json.loads(text) if text else {}
            batch = data.get("settlements") or []
            if not isinstance(batch, list):
                pages.append(page | {"error": "shape"})
                break
            for item in batch:
                if not isinstance(item, dict):
                    continue
                rows.append(
                    {
                        "ticker": item.get("ticker"),
                        "revenue": item.get("revenue"),
                        "yes_count": item.get("yes_count") or item.get("yes_count_fp"),
                        "no_count": item.get("no_count") or item.get("no_count_fp"),
                        "fee_cost": item.get("fee_cost"),
                        "market_result": item.get("market_result") or item.get("result"),
                        "settled_time": item.get("settled_time") or item.get("ts"),
                        "keys": sorted(item.keys())[:30],
                    }
                )
            cursor = str(data.get("cursor") or "")
            pages.append(page | {"n": len(batch), "cursor_next": bool(cursor)})
            if not cursor or not batch:
                break
    except Exception as exc:
        pages.append({"http": 0, "error": type(exc).__name__})
    return {
        "endpoint": "GET /trade-api/v2/portfolio/settlements",
        "http_pages": pages,
        "n": len(rows),
        "rows": rows,
    }


def pull_poly_positions() -> dict:
    try:
        status, text = polymarket_us_live.signed_json("GET", "/v1/portfolio/positions", timeout=30)
        data = json.loads(text) if text and status == 200 else {}
    except Exception as exc:
        return {"http": 0, "error": type(exc).__name__, "rows": []}
    positions = data.get("positions") or data.get("items") or []
    rows = []
    if isinstance(positions, dict):
        for slug, item in positions.items():
            if not isinstance(item, dict):
                continue
            meta = item.get("marketMetadata") if isinstance(item.get("marketMetadata"), dict) else {}
            net = ddec(item.get("netPositionDecimal") or item.get("netPosition") or item.get("quantity")) or Decimal("0")
            if net == 0:
                continue
            rows.append(
                {
                    "slug": slug,
                    "title": meta.get("title") or item.get("title") or "",
                    "outcome": meta.get("outcome") or item.get("outcome") or "",
                    "net": str(net),
                    "cost": amount_value(item.get("cost")),
                    "expired": item.get("expired"),
                }
            )
    elif isinstance(positions, list):
        for item in positions:
            if not isinstance(item, dict):
                continue
            net = ddec(item.get("netPosition") or item.get("quantity") or item.get("netPositionDecimal")) or Decimal("0")
            if net == 0:
                continue
            rows.append(
                {
                    "slug": item.get("marketSlug") or item.get("slug"),
                    "title": item.get("title") or "",
                    "outcome": item.get("outcome") or "",
                    "net": str(net),
                    "cost": amount_value(item.get("cost") or item.get("avgPx")),
                }
            )
    return {
        "http": status,
        "n": len(rows),
        "rows": rows,
        "eof": data.get("eof") if isinstance(data, dict) else None,
        "endpoint": "GET /v1/portfolio/positions",
    }


def fetch_kalshi_markets(tickers: list[str]) -> dict:
    out = {}
    for ticker in tickers:
        if not ticker or ticker in out:
            continue
        url = f"https://api.elections.kalshi.com/trade-api/v2/markets/{urllib.parse.quote(ticker)}"
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "stockresearch-read/1.0"})
            with urllib.request.urlopen(req, timeout=20) as response:
                status = response.status
                text = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            out[ticker] = {"http": exc.code, "error": "http"}
            time.sleep(0.05)
            continue
        except Exception as exc:
            out[ticker] = {"error": type(exc).__name__}
            continue
        data = json.loads(text) if text else {}
        market = data.get("market") if isinstance(data.get("market"), dict) else data
        out[ticker] = {
            "http": status,
            "status": market.get("status"),
            "result": market.get("result"),
            "title": market.get("title") or market.get("subtitle") or market.get("yes_sub_title"),
            "event_ticker": market.get("event_ticker"),
            "last_price": market.get("last_price_dollars") or market.get("last_price"),
        }
        time.sleep(0.05)
    return out


def fetch_kalshi_event_markets(event_tickers: list[str], markets: dict) -> dict:
    for event in event_tickers:
        if not event:
            continue
        url = "https://api.elections.kalshi.com/trade-api/v2/markets?limit=200&event_ticker=" + urllib.parse.quote(event)
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "stockresearch-read/1.0"})
            with urllib.request.urlopen(req, timeout=20) as response:
                text = response.read().decode("utf-8")
                data = json.loads(text) if text else {}
        except Exception:
            continue
        for market in data.get("markets") or []:
            if not isinstance(market, dict):
                continue
            ticker = str(market.get("ticker") or "")
            if not ticker:
                continue
            markets[ticker] = {
                "http": 200,
                "status": market.get("status"),
                "result": market.get("result"),
                "title": market.get("yes_sub_title") or market.get("title") or market.get("subtitle"),
                "event_ticker": market.get("event_ticker") or event,
                "last_price": market.get("last_price_dollars") or market.get("last_price"),
            }
        time.sleep(0.05)
    return markets


def _absorb_oid(by_oid: dict, oid: str, summary: dict) -> None:
    if not oid:
        return
    for key in (oid, oid.upper()):
        prev = by_oid.get(key)
        if prev is None:
            by_oid[key] = dict(summary)
            continue
        if is_b_tape(summary) and not is_b_tape(prev):
            for field in ("_strategy_b", "step", "bet_key", "strategy"):
                if summary.get(field) not in (None, ""):
                    prev[field] = summary[field]
        if summary.get("flatten"):
            prev["flatten"] = True
        if summary.get("game") and not prev.get("game"):
            prev["game"] = summary["game"]
        if summary.get("player") and not prev.get("player"):
            prev["player"] = summary["player"]
        if summary.get("event") and not prev.get("event"):
            prev["event"] = summary["event"]


def load_tape() -> dict:
    io_list = _load_jsonl(ORDER_IO)
    orders = _load_jsonl(ORDERS)
    watch = {}
    if (RAW / "strategy_b_watch.json").exists():
        try:
            watch = json.loads((RAW / "strategy_b_watch.json").read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            watch = {}
    b_log = []
    if (RAW / "strategy_b.log").exists():
        b_log = (RAW / "strategy_b.log").read_text(encoding="utf-8").splitlines()
    by_oid: dict[str, dict] = {}
    ticker_game: dict[str, str] = {}
    io_fills = []
    for row in io_list:
        req = row.get("request") if isinstance(row.get("request"), dict) else {}
        resp = row.get("response") if isinstance(row.get("response"), dict) else {}
        oid = _order_id_of(resp) or str(req.get("order_id") or req.get("client_order_id") or "")
        inst = _io_instrument(row)
        game = game_norm(row.get("game") or req.get("game") or resp.get("game") or "")
        if inst and game:
            ticker_game.setdefault(inst.lower(), game)
        summary = {
            "ts": row.get("timestamp"),
            "venue": str(row.get("venue") or "").lower(),
            "instrument": inst,
            "order_id": oid,
            "game": game,
            "player": row.get("player") or req.get("player") or req.get("outcome") or "",
            "side": row.get("side") or req.get("side") or req.get("action") or "",
            "intent": row.get("intent") or req.get("intent") or "",
            "step": row.get("step") or req.get("step") or "",
            "bet_key": row.get("bet_key") or req.get("bet_key") or "",
            "_strategy_b": row.get("_strategy_b") or req.get("_strategy_b"),
            "strategy": row.get("strategy") or req.get("strategy"),
            "flatten": row.get("flatten") or req.get("flatten") or row.get("is_flatten"),
            "kind": row.get("kind"),
            "poly": polymarket_fill(resp) if str(row.get("venue") or "").lower() == "polymarket" else {},
        }
        io_fills.append(summary)
        if oid:
            _absorb_oid(by_oid, oid, summary)
    for row in orders:
        oid = str(row.get("order_id") or "")
        inst = str(row.get("instrument") or "")
        game = game_norm(row.get("game") or "")
        if inst and game:
            ticker_game.setdefault(inst.lower(), game)
        summary = {
            "ts": row.get("ts") or row.get("timestamp") or row.get("compared_at"),
            "venue": str(row.get("venue") or "").lower(),
            "instrument": inst,
            "order_id": oid,
            "game": game,
            "player": row.get("player") or row.get("side") or "",
            "side": row.get("side") or "",
            "intent": row.get("intent") or "",
            "step": row.get("step") or "",
            "bet_key": row.get("bet_key") or "",
            "_strategy_b": row.get("_strategy_b"),
            "event": row.get("event"),
            "flatten": row.get("flatten") or ("flatten" in str(row.get("event") or "").lower()),
        }
        if oid:
            _absorb_oid(by_oid, oid, summary)
    for row in watch.get("matches") or []:
        game = game_norm(row.get("game") or row.get("title") or "")
        for spec in row.get("legs") or row.get("t0_legs") or []:
            if isinstance(spec, dict):
                inst = str(spec.get("instrument") or spec.get("ticker") or spec.get("slug") or "")
                if inst and game:
                    ticker_game.setdefault(inst.lower(), game)
        for key in ("kalshi_ticker", "slug", "instrument"):
            inst = str(row.get(key) or "")
            if inst and game:
                ticker_game.setdefault(inst.lower(), game)
    jobs_dir = RAW / "live_jobs"
    if jobs_dir.is_dir():
        for path in jobs_dir.glob("*.json"):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            title = game_norm(job.get("title") or (job.get("game") or {}).get("title") or "")
            blob = json.dumps(job, default=str)
            named = named_game(blob) or title
            if not named:
                continue
            for token in (
                job.get("kalshi_ticker"),
                (job.get("game") or {}).get("kalshi_ticker") if isinstance(job.get("game"), dict) else None,
            ):
                if token:
                    ticker_game.setdefault(str(token).lower(), named)
            low = blob.lower()
            for needle in ("kxatp", "kxwta", "gemi-", "aec-"):
                if needle in low:
                    pass
    return {
        "by_oid": by_oid,
        "io": io_fills,
        "orders": orders,
        "watch": watch,
        "b_log": b_log,
        "ticker_game": ticker_game,
    }


def match_tape(fill: dict, tape: dict) -> dict | None:
    ids = set(fill.get("ids") or [])
    oid = str(fill.get("order_id") or "")
    if oid:
        ids.add(oid)
    by_oid = tape["by_oid"]
    for item in ids:
        hit = by_oid.get(item) or by_oid.get(item.upper())
        if hit:
            return hit
    # Time+venue+instrument proximity
    inst = str(fill.get("ticker") or "").lower()
    venue = str(fill.get("venue") or "").lower()
    stamp = parse_dt(fill.get("stamp") or fill.get("time_et"))
    if not inst or stamp is None:
        return None
    best = None
    best_dt = None
    for row in tape["io"]:
        if str(row.get("venue") or "").lower() != venue:
            continue
        row_inst = str(row.get("instrument") or "").lower()
        if not row_inst or row_inst != inst:
            continue
        other = parse_dt(row.get("ts"))
        if other is None:
            continue
        delta = abs((stamp - other).total_seconds())
        if delta <= 45 and (best_dt is None or delta < best_dt):
            best = row
            best_dt = delta
    return best


def attribute(fill: dict, tape_hit: dict | None, tape: dict) -> tuple[str, str, str]:
    """Return (system, game, why). system is B, lock, or unknown."""
    blob = blob_of(fill) + blob_of(tape_hit or {})
    game = ""
    if tape_hit:
        game = game_norm(tape_hit.get("game") or "")
    if not game:
        game = named_game(blob)
    inst = str(fill.get("ticker") or "").lower()
    if not game:
        game = tape["ticker_game"].get(inst) or tape["ticker_game"].get(kalshi_event(inst).lower()) or ""
    if not game:
        game = game_norm(fill.get("title") or fill.get("event") or "")
    named = named_game(blob + " " + game + " " + inst + " " + kalshi_event(str(fill.get("ticker") or "")))
    if not game:
        game = named or kalshi_event(str(fill.get("ticker") or "")) or str(fill.get("ticker") or "unlabeled")
    if named:
        game = named
    stamp = parse_dt(fill.get("stamp") or fill.get("time_et") or (tape_hit or {}).get("ts"))

    if game.upper().startswith("KX"):
        ev = kalshi_event(game)
        for key, gname in (tape.get("ticker_game") or {}).items():
            if kalshi_event(str(key)) == ev and gname and not str(gname).upper().startswith("KX"):
                game = game_norm(gname)
                break
    if named == "Leylah Fernandez vs Ekaterina Alexandrova":
        return "B", game, "Paul: textbook B (T0 + 50-cross + favorite dip)"
    if named == "Marco Trungelliti vs Matej Dodig":
        return "B", game, "Paul: T0 both-Yes plus duplicate extra Dodig is B (bug)"
    if named == "Felipe Meligeni Alves vs Carlos Maria Zarate":
        return "lock", game, "Paul: three gap+flatten is lock; no B ticket"
    if named == "Corentin Moutet vs Tommy Paul":
        if moutet_lock_window(stamp):
            return "lock", game, "Paul: Moutet 10:47–10:51 lock leftover/flatten is lock"
        if moutet_t0_window(stamp):
            return "B", game, "Paul: Moutet T0 both-Yes is B"
        if tape_hit and is_b_tape(tape_hit) and not is_flatten_tape(tape_hit):
            return "B", game, "tape Strategy B, not lock flatten"
        if tape_hit and is_flatten_tape(tape_hit) and not is_b_tape(tape_hit):
            return "lock", game, "lock leftover/flatten on Moutet"
        if tape_hit and is_b_tape(tape_hit):
            return "B", game, "tape Strategy B"
        if tape_hit:
            return "lock", game, "matched lock-bot order id"
        return "unknown", game, "Moutet fill not matched to T0 or 10:47–10:51; ask Paul"

    if tape_hit:
        if is_flatten_tape(tape_hit) and not is_b_tape(tape_hit):
            return "lock", game or "unlabeled", "lock leftover/flatten; never count as B"
        if is_b_tape(tape_hit):
            return "B", game or "unlabeled", "tape _strategy_b / tennis-b / b-step"
        return "lock", game or "unlabeled", "matched house order id, not Strategy B"

    return "unknown", game or fill.get("ticker") or "unlabeled", "no matching order id in logs/opportunities/orders.html; ask Paul"


def kalshi_result_map(markets: dict, settlements: dict) -> dict[str, str]:
    found: dict[str, str] = {}
    for row in settlements.get("rows") or []:
        ticker = str(row.get("ticker") or "")
        result = str(row.get("market_result") or "").lower()
        if ticker and result in {"yes", "no"}:
            found[ticker] = result
    for ticker, market in markets.items():
        result = str((market or {}).get("result") or "").lower()
        if result in {"yes", "no"}:
            found[ticker] = result
    return found


def gemini_resolution(fill: dict) -> str:
    return str(fill.get("resolution") or "").lower()


def last_name(text: str) -> str:
    parts = [p for p in str(text or "").replace("-", " ").split() if p]
    return parts[-1].lower() if parts else ""


def winner_from_kalshi(game: str, results: dict[str, str], markets: dict, ticker_game: dict | None = None, fill_tickers: list[str] | None = None) -> str:
    """Winning last name from Kalshi yes results on this game, or empty."""
    g = game_norm(game).lower()
    votes: dict[str, int] = defaultdict(int)
    ticker_game = ticker_game or {}
    events = {kalshi_event(t) for t in (fill_tickers or []) if str(t).upper().startswith("KX")}
    named = named_game(game)
    for ticker, result in results.items():
        if str(result).lower() != "yes":
            continue
        mapped = game_norm(ticker_game.get(str(ticker).lower()) or "").lower()
        market = markets.get(ticker) or {}
        title = str(market.get("title") or market.get("yes_sub_title") or ticker)
        blob = f"{ticker} {title} {mapped}"
        same_event = bool(events) and kalshi_event(ticker) in events
        same_named = bool(named) and named_game(blob) == named
        same_mapped = bool(g) and mapped == g
        if not (same_event or same_named or same_mapped):
            continue
        votes[last_name(title) or last_name(game) or ticker] += 1
    if not votes:
        return ""
    return sorted(votes.items(), key=lambda kv: -kv[1])[0][0]


def apply_settlement(group: dict, results: dict[str, str], open_tickers: set[str], open_slugs: set[str], markets: dict) -> None:
    """Add payout cash for remaining inventory. Do not invent if still open and no result."""
    payout = Decimal("0")
    open_bits = []
    settled_bits = []
    unknown_bits = []
    game = str(group.get("game") or "")
    fill_tickers = [str(f.get("ticker") or "") for f in group["fills"]]
    winner = winner_from_kalshi(game, results, markets, group.get("ticker_game") or {}, fill_tickers)

    # Kalshi: net Yes by ticker, then apply that ticker's yes/no result.
    kalshi_net: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for fill in group["fills"]:
        if fill.get("venue") != "kalshi":
            continue
        ticker = str(fill.get("ticker") or "")
        kalshi_net[ticker] += ddec(fill.get("yes_signed")) or Decimal("0")
    for ticker, net in kalshi_net.items():
        if net == 0:
            continue
        still_open = ticker in open_tickers
        result = str(results.get(ticker) or "").lower()
        if still_open and result not in {"yes", "no"}:
            open_bits.append(f"kalshi {ticker} net {net}")
            continue
        if result not in {"yes", "no"}:
            unknown_bits.append(f"kalshi {ticker} net {net} no result")
            continue
        # Same identity as fill cash: sell Yes received the Yes wire, so payout is net if Yes won else 0.
        won = net if result == "yes" else Decimal("0")
        payout += won
        settled_bits.append(f"{ticker} net {net} result {result} payout {won}")

    # Polymarket: Yes of a named player (BUY_LONG or BUY_SHORT-other). Do not net them on the slug.
    poly_by_outcome: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    poly_open = False
    poly_unlabeled = Decimal("0")
    for fill in group["fills"]:
        if fill.get("venue") != "polymarket":
            continue
        slug = str(fill.get("ticker") or "")
        qty = ddec(fill.get("qty")) or Decimal("0")
        if slug.lower() in open_slugs or slug in open_slugs:
            poly_open = True
            open_bits.append(f"polymarket {slug} qty {qty} still on positions")
            continue
        outcome = str(fill.get("outcome") or "").strip()
        if not outcome:
            poly_unlabeled += qty
            continue
        poly_by_outcome[outcome] += qty
    if poly_open:
        pass
    elif poly_by_outcome or poly_unlabeled:
        names = list(poly_by_outcome.keys())
        qtys = [poly_by_outcome[n] for n in names]
        if len(names) == 2 and poly_unlabeled == 0:
            guaranteed = min(qtys)
            extra = max(qtys) - min(qtys)
            payout += guaranteed
            settled_bits.append(f"poly both-Yes guaranteed {guaranteed} ({names[0]} {qtys[0]} / {names[1]} {qtys[1]})")
            if extra > 0:
                extra_name = names[0] if poly_by_outcome[names[0]] > poly_by_outcome[names[1]] else names[1]
                if winner and (last_name(extra_name) == winner or winner in extra_name.lower()):
                    payout += extra
                    settled_bits.append(f"poly extra {extra_name} {extra} paid (winner {winner})")
                elif winner:
                    settled_bits.append(f"poly extra {extra_name} {extra} paid 0 (winner {winner})")
                else:
                    unknown_bits.append(f"poly extra {extra_name} qty {extra} need winner")
        elif len(names) == 1 and poly_unlabeled == 0:
            only = names[0]
            qty = poly_by_outcome[only]
            if winner and (last_name(only) == winner or winner in only.lower()):
                payout += qty
                settled_bits.append(f"poly leftover {only} {qty} paid")
            elif winner:
                settled_bits.append(f"poly leftover {only} {qty} paid 0")
            else:
                unknown_bits.append(f"poly leftover {only} qty {qty} need winner")
        else:
            unknown_bits.append(f"poly outcomes {dict(poly_by_outcome)} unlabeled {poly_unlabeled}")

    # Gemini: pay if resolutionSide matches the bought outcome.
    for fill in group["fills"]:
        if fill.get("venue") != "gemini":
            continue
        ticker = str(fill.get("ticker") or "")
        qty = ddec(fill.get("qty")) or Decimal("0")
        reso = str(fill.get("resolution") or "").strip()
        outcome = str(fill.get("outcome") or "").strip()
        if not reso:
            unknown_bits.append(f"gemini {ticker} qty {qty} unresolved")
            continue
        if outcome and reso.lower() == outcome.lower():
            payout += qty
            settled_bits.append(f"gemini {ticker} {outcome} resolved {reso} payout {qty}")
        elif outcome:
            settled_bits.append(f"gemini {ticker} {outcome} resolved {reso} payout 0")
        else:
            unknown_bits.append(f"gemini {ticker} qty {qty} resolution={reso} no outcome")

    # Novig: treat like leftover Yes unless we have a result mapped; leave unknown if net remains.
    novig_net: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for fill in group["fills"]:
        if fill.get("venue") != "novig":
            continue
        novig_net[str(fill.get("ticker") or "")] += ddec(fill.get("qty")) or Decimal("0")
    for ticker, net in novig_net.items():
        if net == 0:
            continue
        unknown_bits.append(f"novig {ticker} net {net} no settlement helper")

    group["payout"] = payout
    group["open_inventory"] = open_bits
    group["settle_notes"] = settled_bits
    group["unknown_settle"] = unknown_bits
    cash = sum((ddec(f.get("cash_flow")) or Decimal("0") for f in group["fills"]), Decimal("0"))
    group["cash_flow"] = cash
    if open_bits:
        group["realized"] = None
        group["status"] = "still-open"
        group["open_cost"] = -cash
        return
    if unknown_bits:
        group["realized"] = None
        group["status"] = "unknown settlement — ask Paul"
        return
    group["realized"] = cash + payout
    group["status"] = "closed"
    group["closed"] = True


def win_flag(realized) -> str:
    if realized is None:
        return ""
    if realized > 0:
        return "win"
    if realized < 0:
        return "loss"
    return "scratch"


def build_groups(fills: list[dict], tape: dict, results: dict[str, str], open_tickers: set[str], open_slugs: set[str], markets: dict):
    unknown = []
    attributed = []
    for fill in fills:
        hit = match_tape(fill, tape)
        system, game, why = attribute(fill, hit, tape)
        row = dict(fill)
        row["system"] = system
        row["game"] = game
        row["why"] = why
        if hit:
            if not row.get("outcome"):
                row["outcome"] = hit.get("player") or (hit.get("poly") or {}).get("outcome_name") or ""
            if not row.get("game"):
                row["game"] = hit.get("game") or game
        if system == "unknown":
            unknown.append(row)
        else:
            attributed.append(row)
    # Same Kalshi event as textbook B (Fernandez, Taverna T0) is B, not a second lock book.
    # Do not promote Moutet/Alves — those events have both B and lock fills.
    promote_names = {
        "Leylah Fernandez vs Ekaterina Alexandrova",
        "Santiago Rodriguez Taverna vs Gonzalo Bueno",
    }
    for row in attributed:
        if row["game"] in promote_names and row["system"] == "lock":
            row["system"] = "B"
            row["why"] = "same match as Strategy B T0/extras; not lock leftover/flatten"
    human_by_event = {}
    for row in attributed:
        ev = kalshi_event(str(row.get("ticker") or ""))
        if ev and not str(row.get("game") or "").upper().startswith("KX"):
            human_by_event[ev] = row["game"]
    for row in attributed:
        ev = kalshi_event(str(row.get("ticker") or ""))
        if str(row.get("game") or "").upper().startswith("KX") and ev in human_by_event:
            row["game"] = human_by_event[ev]
    groups = {}
    for row in attributed:
        key = (row["system"], row["game"])
        slot = groups.setdefault(
            key,
            {
                "system": row["system"],
                "game": row["game"],
                "fills": [],
                "why": row["why"],
            },
        )
        slot["fills"].append(row)
        if row["why"] not in slot["why"]:
            slot["why"] = slot["why"] + "; " + row["why"]
    for slot in groups.values():
        slot["n_tickets"] = len(slot["fills"])
        slot["venues"] = sorted({str(f.get("venue") or "") for f in slot["fills"]})
        slot["first"] = min((f.get("time_et") or "" for f in slot["fills"]), default="")
        slot["last"] = max((f.get("time_et") or "" for f in slot["fills"]), default="")
        fees = sum((ddec(f.get("fee")) or Decimal("0") for f in slot["fills"]), Decimal("0"))
        slot["fees"] = fees
        slot["ticker_game"] = tape.get("ticker_game") or {}
        apply_settlement(slot, results, open_tickers, open_slugs, markets)
        slot["win"] = win_flag(slot.get("realized"))
    return list(groups.values()), unknown, attributed


def summarize(groups: list[dict], system: str) -> dict:
    rows = [g for g in groups if g["system"] == system]
    closed = [g for g in rows if g.get("realized") is not None]
    opened = [g for g in rows if str(g.get("status") or "").startswith("still-open")]
    unknown_s = [g for g in rows if g.get("realized") is None and g not in opened]
    realized = sum((g["realized"] for g in closed), Decimal("0"))
    n_tickets = sum(g["n_tickets"] for g in rows)
    wins = sum(1 for g in closed if g.get("win") == "win")
    losses = sum(1 for g in closed if g.get("win") == "loss")
    n_closed = len(closed)
    wr = (Decimal(wins) / Decimal(n_closed) * 100) if n_closed else None
    exp = (realized / Decimal(n_closed)) if n_closed else None
    return {
        "system": system,
        "n_matches": len(rows),
        "n_closed": n_closed,
        "n_open": len(opened),
        "n_unknown_settle": len(unknown_s),
        "n_tickets": n_tickets,
        "realized": realized,
        "wins": wins,
        "losses": losses,
        "wr": wr,
        "expectancy": exp,
        "open_rows": opened,
        "closed_rows": closed,
        "all_rows": rows,
    }


def write_html(payload: dict) -> None:
    now = payload["pulled_at"]
    b = payload["b"]
    lock = payload["lock"]
    unknown = payload["unknown"]
    groups = payload["groups"]
    first_send = payload.get("first_send") or ""
    pos = payload.get("positions") or {}
    ahead = payload["ahead"]
    headers = [
        ("System", "text"),
        ("Game", "text"),
        ("Tickets", "num"),
        ("Venues", "text"),
        ("First fill ET", "date"),
        ("Last fill ET", "date"),
        ("Fees $", "num"),
        ("Realized $ with fees", "num"),
        ("Status", "text"),
        ("Win?", "text"),
        ("Why this system", "text"),
    ]
    rows = []
    for g in sorted(groups, key=lambda r: (r.get("first") or "", r["system"], r["game"])):
        realized = g.get("realized")
        rows.append(
            [
                esc(g["system"]),
                esc(g["game"]),
                esc(g["n_tickets"]),
                esc(", ".join(g.get("venues") or [])),
                esc(g.get("first")),
                esc(g.get("last")),
                esc(money(g.get("fees"))),
                esc(money(realized) if realized is not None else g.get("status")),
                esc(g.get("status")),
                esc(g.get("win") or "—"),
                esc(g.get("why")),
            ]
        )
    total_realized = (b["realized"] if b["realized"] is not None else Decimal("0")) + (
        lock["realized"] if lock["realized"] is not None else Decimal("0")
    )
    match_table = table(
        headers,
        rows,
        [
            "Combined closed",
            f"{b['n_matches'] + lock['n_matches']} matches",
            str(b["n_tickets"] + lock["n_tickets"]),
            "",
            "",
            "",
            "",
            money(total_realized),
            "unknown fills not included",
            "",
            "",
        ],
    )
    unk_rows = []
    for row in unknown:
        unk_rows.append(
            [
                esc(row.get("venue")),
                esc(row.get("time_et")),
                esc(row.get("ticker")),
                esc(row.get("qty")),
                esc(row.get("fee")),
                esc(row.get("cash_flow")),
                esc(row.get("order_id")),
                esc(row.get("why") or "unmatched"),
            ]
        )
    unk_table = table(
        [
            ("Venue", "text"),
            ("Time ET", "date"),
            ("Ticker / slug", "text"),
            ("Qty", "num"),
            ("Fee", "num"),
            ("Cash flow", "num"),
            ("Order id", "text"),
            ("Why unknown", "text"),
        ],
        unk_rows if unk_rows else [["—", "", "none — every positive-qty fill was attributed or listed", "", "", "", "", ""]],
    )
    open_rows = []
    for row in (pos.get("kalshi") or {}).get("rows") or []:
        open_rows.append(
            [
                "kalshi",
                esc(row.get("ticker")),
                esc(row.get("position")),
                esc(row.get("exposure")),
                "venue position; not marked to a guessed result",
            ]
        )
    for row in (pos.get("poly") or {}).get("rows") or []:
        open_rows.append(
            [
                "polymarket",
                esc(row.get("slug") or row.get("title")),
                esc(row.get("net")),
                esc(row.get("cost")),
                esc(row.get("outcome") or "venue position; not marked to a guessed result"),
            ]
        )
    if not open_rows:
        open_rows = [["—", "none on Kalshi GET positions or Polymarket US GET positions", "", "", "Gemini/Novig have no positions helper in the live modules; open Gemini would show as unresolved history"]]
    open_table = table(
        [
            ("Venue", "text"),
            ("Ticker / slug", "text"),
            ("Net qty", "num"),
            ("Exposure / cost", "num"),
            ("Note", "text"),
        ],
        open_rows,
    )
    wr_b = f"{float(b['wr']):.1f}%" if b["wr"] is not None else "n/a (no closed B match)"
    wr_l = f"{float(lock['wr']):.1f}%" if lock["wr"] is not None else "n/a (no closed lock match)"
    exp_b = money(b["expectancy"]) if b["expectancy"] is not None else "n/a"
    exp_l = money(lock["expectancy"]) if lock["expectancy"] is not None else "n/a"
    b_open_note = (
        f"{b['n_open']} still-open B match(es) excluded from realized"
        if b["n_open"]
        else "no still-open B inventory in the closed-book score"
    )
    lock_open_note = (
        f"{lock['n_open']} still-open lock match(es) excluded from realized"
        if lock["n_open"]
        else "no still-open lock inventory in the closed-book score"
    )
    venues = payload.get("venues") or {}
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
{CACHE_META}
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Strategy B vs lock bot — realized cash with fees — 23 Oct 2026</title>
{FORCE_RELOAD_SCRIPT}
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 24px; color: #1e293b; line-height: 1.45; }}
h1 {{ font-size: 1.7rem; margin-bottom: 0.2rem; }}
h2 {{ font-size: 1.25rem; margin-top: 1.7rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 12px 0; }}
.callout h2 {{ margin: 0 0 6px; }}
.warn {{ background: #fff7ed; border-color: #fdba74; }}
.ok {{ background: #f0fdf4; border-color: #86efac; }}
.note {{ color: #475569; font-size: 0.95rem; }}
code {{ font-size: 0.9em; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Has Strategy B made more than the lock gap?</h1>
<p class="note">Written {esc(now)}. Times are America/New_York. Research live. Not gold. Not DailyRun. Size 1. Immediate or Cancel only. Did not sell more. Did not GTC. Did not commit. No secrets. No second Strategy B. D stays 0.25. NET_MAX stays 0.984. Click column headers to sort.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="callout {'ok' if b['realized'] > 0 and b['realized'] > lock['realized'] else 'warn'}">
<h2>Verdict</h2>
<ul>
<li><strong>Strategy B realized (with fees, closed only):</strong> {esc(money(b['realized']))} on {esc(b['n_tickets'])} tickets / {esc(b['n_closed'])} closed matches ({esc(b['n_matches'])} matches with any B fill; {esc(b_open_note)}).</li>
<li><strong>Lock bot realized (with fees, closed only):</strong> {esc(money(lock['realized']))} on {esc(lock['n_tickets'])} tickets / {esc(lock['n_closed'])} closed matches ({esc(lock['n_matches'])} matches with any lock fill; {esc(lock_open_note)}).</li>
<li><strong>Combined closed:</strong> {esc(money(total_realized))}.</li>
<li><strong>Who is ahead on realized cash:</strong> {esc(ahead)}</li>
<li><strong>Win rate / expectancy</strong> (closed matches, realized &gt; 0 is a win): B {esc(wr_b)}, expectancy {esc(exp_b)} per closed match. Lock {esc(wr_l)}, expectancy {esc(exp_l)} per closed match.</li>
<li><strong>Still-open caveat:</strong> venue positions below are not marked to a guessed settlement. That cash is not in the realized totals. Matches whose fills are closed on the venue but whose winner we could not read are listed as unknown settlement — they are not in realized and are not guessed.</li>
<li><strong>Unknown fills (no order id):</strong> {esc(len(unknown))} (not dumped into B). Unknown settlement matches: B {esc(b.get('n_unknown_settle'))}, lock {esc(lock.get('n_unknown_settle'))}.</li>
</ul>
</div>

<h2>Match book (system × game)</h2>
<p class="note">One row per system per game. Realized dollars include venue fees. Flattened leftover is lock, not B. Fernandez/Alexandrova is B. Trungelliti extra Dodig is B. Moutet T0 is B. Moutet 10:47–10:51 is lock. Alves/Zarate is lock. Window first live send {esc(first_send)} through {esc(now)}.</p>
{match_table}

<h2>Still-open inventory (venue positions)</h2>
<p class="note">Kalshi GET /trade-api/v2/portfolio/positions and Polymarket US GET /v1/portfolio/positions. Zero-position rows omitted. Do not invent settlement.</p>
{open_table}

<h2>Unknown attribution (ask Paul)</h2>
<p class="note">These venue fills did not match a house order id in orders.jsonl / order_io.jsonl / orders.html, and did not hit a named Paul rule. They are not in B and not in lock totals.</p>
{unk_table}

<h2>How attribution was done</h2>
<ul>
<li><strong>B:</strong> T0 both-Yes, 50-cross extra dog, favorite dip, B leftover-yes on a missed T0 player. Named: Fernandez/Alexandrova; Trungelliti including the duplicate extra Dodig; Moutet ~08:00 T0.</li>
<li><strong>Lock:</strong> Yes one venue + No the other, leftover, flatten. Named: Alves/Zarate three gap+flatten; Moutet 10:47–10:51.</li>
<li>Order ids from Kalshi GET fills, Poly activities, Gemini order history, Novig fills were matched to local logs. Lock leftover/flatten is never counted as B.</li>
</ul>

<p class="note">Sources: Kalshi GET /trade-api/v2/portfolio/fills HTTP {(venues.get('kalshi') or {}).get('http_pages')}; GET positions {(pos.get('kalshi') or {}).get('http')}; GET settlements; public GET /trade-api/v2/markets. Polymarket US GET /v1/portfolio/activities HTTP {(venues.get('polymarket') or {}).get('http_pages')}; GET positions {(pos.get('poly') or {}).get('http')}. Gemini POST /v1/prediction-markets/orders/history {(venues.get('gemini') or {}).get('http_pages')}. Novig GET /v3/portfolio/fills {(venues.get('novig') or {}).get('http_pages')}. Local order_io.jsonl, orders.jsonl, strategy_b.log, strategy_b_watch.json. Pulled {esc(now)}. No second Strategy B. D=0.25. NET_MAX=0.984. No GTC. No secrets. Did not sell.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(page, encoding="utf-8")


def main() -> int:
    now = datetime.now(ET)
    RAW.mkdir(parents=True, exist_ok=True)
    venues = {
        "kalshi": pull_kalshi(now),
        "gemini": pull_gemini(now),
        "polymarket": pull_polymarket(now),
        "novig": pull_novig(now),
    }
    positions = {
        "kalshi": pull_kalshi_positions(),
        "poly": pull_poly_positions(),
    }
    settlements = pull_kalshi_settlements()
    tape = load_tape()
    all_fills = []
    for name in ("kalshi", "gemini", "polymarket", "novig"):
        all_fills.extend(venues[name].get("fills") or [])
    tickers = {str(f.get("ticker") or "") for f in all_fills if f.get("venue") == "kalshi" and f.get("ticker")}
    tickers.update(
        {
            "KXWTAMATCH-26OCT23FERALE-FER",
            "KXWTAMATCH-26OCT23FERALE-ALE",
            "KXATPCHALLENGERMATCH-26OCT23TRUDOD-TRU",
            "KXATPCHALLENGERMATCH-26OCT23TRUDOD-DOD",
            "KXATPMATCH-26OCT23MOUPAU-MOU",
            "KXATPMATCH-26OCT23MOUPAU-PAU",
            "KXATPCHALLENGERMATCH-26OCT23MELZAR-MEL",
            "KXATPCHALLENGERMATCH-26OCT23MELZAR-ZAR",
            "KXATPCHALLENGERMATCH-26OCT21RODBUE-ROD",
            "KXATPCHALLENGERMATCH-26OCT21RODBUE-BUE",
        }
    )
    filled_games = set()
    for f in all_fills:
        g = named_game(blob_of(f)) or tape["ticker_game"].get(str(f.get("ticker") or "").lower())
        if g:
            filled_games.add(game_norm(g).lower())
    for inst, game in (tape.get("ticker_game") or {}).items():
        up = str(inst or "").upper()
        if up.startswith("KX") and game_norm(game).lower() in filled_games:
            tickers.add(up)
    markets = fetch_kalshi_markets(sorted(t for t in tickers if t))
    events = sorted({kalshi_event(t) for t in tickers if t})
    markets = fetch_kalshi_event_markets(events, markets)
    results = kalshi_result_map(markets, settlements)
    open_tickers = {str(r.get("ticker") or "") for r in (positions["kalshi"].get("rows") or [])}
    open_slugs = {str(r.get("slug") or "").lower() for r in (positions["poly"].get("rows") or [])}
    groups, unknown, attributed = build_groups(all_fills, tape, results, open_tickers, open_slugs, markets)
    b = summarize(groups, "B")
    lock = summarize(groups, "lock")
    if b["realized"] > lock["realized"]:
        ahead = f"B is ahead by {money(b['realized'] - lock['realized'])} realized (B {money(b['realized'])} vs lock {money(lock['realized'])})"
    elif lock["realized"] > b["realized"]:
        ahead = f"Lock is ahead by {money(lock['realized'] - b['realized'])} realized (lock {money(lock['realized'])} vs B {money(b['realized'])})"
    else:
        ahead = f"Tied on realized cash at {money(b['realized'])}"
    stamps = [parse_dt(f.get("stamp") or f.get("time_et")) for f in attributed]
    stamps = [s for s in stamps if s is not None]
    first_send = et_text(min(stamps)) if stamps else ""
    payload = {
        "pulled_at": now.strftime("%Y-%m-%d %H:%M ET"),
        "first_send": first_send,
        "window_start_scan": WINDOW_START.isoformat(),
        "venues": redact(
            {
                name: {k: v for k, v in blob.items() if k != "fills"} | {"n_fills_kept": len(blob.get("fills") or [])}
                for name, blob in venues.items()
            }
        ),
        "positions": positions,
        "settlements_n": settlements.get("n"),
        "markets_n": len(markets),
        "n_fills": len(all_fills),
        "n_attributed": len(attributed),
        "n_unknown": len(unknown),
        "b": {k: (str(v) if isinstance(v, Decimal) else v) for k, v in b.items() if k not in {"open_rows", "closed_rows", "all_rows"}},
        "lock": {k: (str(v) if isinstance(v, Decimal) else v) for k, v in lock.items() if k not in {"open_rows", "closed_rows", "all_rows"}},
        "ahead": ahead,
        "groups": [
            {
                "system": g["system"],
                "game": g["game"],
                "n_tickets": g["n_tickets"],
                "venues": g.get("venues"),
                "first": g.get("first"),
                "last": g.get("last"),
                "fees": str(g.get("fees")),
                "realized": str(g["realized"]) if g.get("realized") is not None else None,
                "status": g.get("status"),
                "win": g.get("win"),
                "why": g.get("why"),
                "open_inventory": g.get("open_inventory"),
                "unknown_settle": g.get("unknown_settle"),
                "payout": str(g.get("payout") or 0),
                "cash_flow": str(g.get("cash_flow") or 0),
            }
            for g in groups
        ],
        "unknown": unknown,
        "no_sell": True,
        "no_gtc": True,
        "d": "0.25",
        "net_max": "0.984",
    }
    # Keep slim fills in extract for audit (no secrets).
    payload["fills_slim"] = [
        {
            "venue": f.get("venue"),
            "time_et": f.get("time_et"),
            "ticker": f.get("ticker"),
            "system": f.get("system"),
            "game": f.get("game"),
            "qty": f.get("qty"),
            "fee": f.get("fee"),
            "cash_flow": f.get("cash_flow"),
            "order_id": f.get("order_id"),
            "why": f.get("why"),
        }
        for f in attributed
    ]
    EXTRACT.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    html_payload = {
        "pulled_at": payload["pulled_at"],
        "first_send": first_send,
        "b": b,
        "lock": lock,
        "unknown": unknown,
        "groups": groups,
        "ahead": ahead,
        "venues": venues,
        "positions": positions,
    }
    write_html(html_payload)
    print(f"wrote {EXTRACT}")
    print(f"wrote {PAGE}")
    print("fills", len(all_fills), "attributed", len(attributed), "unknown", len(unknown))
    print("B", money(b["realized"]), "tickets", b["n_tickets"], "closed", b["n_closed"], "open", b["n_open"])
    print("lock", money(lock["realized"]), "tickets", lock["n_tickets"], "closed", lock["n_closed"], "open", lock["n_open"])
    print("ahead", ahead)
    for name, blob in venues.items():
        pages = blob.get("http_pages") or []
        print(name, [p.get("http") for p in pages], "n", blob.get("n_pos"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
