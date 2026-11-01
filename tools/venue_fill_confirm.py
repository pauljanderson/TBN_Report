"""Confirm a live order against that venue's documented fill/history API.

Truth is the venue fill list, not the order HTTP tape. Read-only. Does not
place, cancel, or sell. Timeouts are bounded so leftover watch cannot hang.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import gemini_private
import kalshi_private
import novig_live
import polymarket_us_live

ONE = Decimal("1")
HUNDRED = Decimal("100")
CONFIRM_TRIES = 2
CONFIRM_TIMEOUT_SEC = 4.0
CONFIRM_SLEEP_SEC = 0.35
CONFIRM_WINDOW_SEC = 120
POLY_RECENT_SEC = 90
HOUSE_SIZE = ONE
PAYLOAD_KEY = "_venue_confirm"

ENDPOINTS = {
    "kalshi": "GET /trade-api/v2/portfolio/fills",
    "gemini": "POST /v1/prediction-markets/orders/history",
    "polymarket": "GET /v1/portfolio/activities",
    "novig": "GET /v3/portfolio/fills",
}


def _dec(value) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, dict):
        value = value.get("value")
        if value is None or value == "":
            return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def money_px(value) -> Decimal | None:
    """Venue money node: a number or ``{"value": "0.0000", "currency": "USD"}``."""
    return _dec(value)


def settlement_result_from_px(px) -> str:
    """Yes/No from a venue settlement/redeem price. Empty when it is not 0 or 1."""
    number = money_px(px)
    if number is None:
        return ""
    if number >= 1:
        return "yes"
    if number <= 0:
        return "no"
    return ""


_HOUSE_NEAR = Decimal("0.05")


def _near_px(left, right) -> bool:
    a = money_px(left)
    b = money_px(right)
    return a is not None and b is not None and abs(a - b) <= _HOUSE_NEAR


def poly_house_cash(
    *,
    avg=None,
    spread=None,
    quote=None,
    pay=None,
    api_limit=None,
    intent: str = "",
) -> Decimal | None:
    """What Polymarket charged on this fill. Per-order venue fields, not 1−p.

    BUY_SHORT posts two prices that sum to $1: avgPx is usually the Yes-wire
    (Hsu 0.45) and commissionSpreadPx the debit (0.55). Some fills are the
    other way around. Pick the venue field closest to the house quote, including
    the Yes-wire complement. Do not treat 0.48 and 0.52 as the same price just
    because they sit within a nickel (Pohle/Kostina). Never swap every SHORT
    onto spread. Kitchen Yes-ask quotes (Kuhar 0.74 vs posted debit 0.26) are
    not a hint — use the posted limit / venue debit.
    """
    avg_px = money_px(avg)
    spread_px = money_px(spread)
    quote_px = money_px(quote)
    pay_px = money_px(pay)
    api_px = money_px(api_limit)
    short = "SHORT" in str(intent or "").upper()

    def _ok(px) -> bool:
        return px is not None and Decimal("0") < px < ONE

    fields = [px for px in (avg_px, spread_px) if _ok(px)]
    candidates: list[Decimal] = []
    for px in fields:
        if px not in candidates:
            candidates.append(px)
    if short:
        for src in (avg_px, spread_px):
            if not _ok(src):
                continue
            comp = ONE - src
            if _ok(comp) and comp not in candidates:
                candidates.append(comp)
    # T0 both-Yes stores the Yes ask as quote and the SHORT limit as 1-p
    # (Kuhar 0.74 vs 0.26; Lakshmanan 0.28 vs 0.72). Debit is the cheaper.
    # Kostina 0.53 vs limit 0.47 is a nickel FOK, not that split — keep quote.
    split_yes_wire = (
        short
        and _ok(quote_px)
        and _ok(api_px)
        and _near_px(quote_px + api_px, ONE)
        and abs(quote_px - api_px) >= Decimal("0.15")
    )
    hints: list[Decimal] = []
    if split_yes_wire:
        hints.append(min(quote_px, api_px))
    elif _ok(quote_px):
        hints.append(quote_px)
    if _ok(pay_px):
        yes_wire = short and _near_px(pay_px, avg_px) and (
            (spread_px is not None and _near_px(spread_px, ONE - avg_px))
            or (api_px is not None and _near_px(pay_px, api_px))
        )
        if not yes_wire:
            hints.append(pay_px)
    if hints and candidates:
        hint = hints[0]
        venue_set = set(fields)

        def _key(px: Decimal):
            return (abs(px - hint), 0 if px in venue_set else 1)

        return min(candidates, key=_key)
    if short and _ok(spread_px):
        if avg_px is None or _near_px(spread_px, ONE - avg_px):
            return spread_px
    if _ok(avg_px):
        return avg_px
    if _ok(spread_px):
        return spread_px
    return None


def poly_prices_from_payload(payload) -> dict:
    """avgPx, commissionSpreadPx, fee, intent from a Polymarket order/execution body."""
    found = {"avg": None, "spread": None, "fee": None, "intent": "", "side": ""}
    if not isinstance(payload, (dict, list)):
        return found

    def walk(node) -> None:
        if isinstance(node, dict):
            intent = str(node.get("intent") or "")
            if "SHORT" in intent or "LONG" in intent:
                found["intent"] = intent
            outcome = str(node.get("outcomeSide") or "")
            if outcome == "OUTCOME_SIDE_NO":
                found["side"] = "no"
            elif outcome == "OUTCOME_SIDE_YES" and not found["side"]:
                found["side"] = "yes"
            avg = money_px(node.get("avgPx") or node.get("lastPx"))
            if avg is not None and avg > 0:
                found["avg"] = avg
            spread = money_px(node.get("commissionSpreadPx"))
            if spread is not None and spread > 0:
                found["spread"] = spread
            fee = money_px(node.get("commissionNotionalCollected") or node.get("commissionNotionalTotalCollected"))
            if fee is not None and fee > 0:
                found["fee"] = fee
            for child in node.values():
                if child is node.get(PAYLOAD_KEY):
                    continue
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(payload)
    confirm = from_payload(payload) if isinstance(payload, dict) else None
    if isinstance(confirm, dict):
        if found["avg"] is None:
            found["avg"] = money_px(confirm.get("avg_price"))
        if found["fee"] is None:
            found["fee"] = money_px(confirm.get("fee"))
    return found


def _walk(value):
    if isinstance(value, dict):
        yield value
        for key, child in value.items():
            if key == PAYLOAD_KEY:
                continue
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


_ORDER_QTY_KEYS = (
    "fill_count",
    "filledQuantity",
    "filled_quantity",
    "cumQuantity",
    "executedQuantity",
    "quantityFilled",
    "count_fp",
)


def tape_filled_qty(payload) -> Decimal:
    """Qty from THIS order HTTP body only. Book qtyDecimal / lastShares are not a fill.

    26 Oct 2026 TB-CAR ghost: walking nested book qty labeled HTTP 201 as fill 1
    with no order id. Kalshi fill_count and Poly cumQuantity on this order id
    are the tape fields. Confirm overlay still wins in filled_contracts.
    """
    if not isinstance(payload, (dict, list)):
        return Decimal("0")
    ids = ids_from(payload)
    oid = str(ids.get("order_id") or "").strip()
    if oid:
        best, _price = this_order_cum_qty(payload, oid)
        for node in _walk(payload):
            if not isinstance(node, dict):
                continue
            nid = node.get("id") or node.get("orderId") or node.get("order_id")
            if not _match_id(nid, oid):
                continue
            for key in _ORDER_QTY_KEYS:
                number = _dec(node.get(key))
                if number is not None and number > best:
                    best = number
            if node.get("tif") == "IOC" and node.get("orderId"):
                dollars = novig_live.filled_dollar_contracts(node)
                if dollars > best:
                    best = dollars
        return best
    nodes: list[dict] = []
    if isinstance(payload, dict):
        nodes.append(payload)
        inner = payload.get("order")
        if isinstance(inner, dict):
            nodes.append(inner)
    elif isinstance(payload, list):
        nodes.extend(item for item in payload if isinstance(item, dict))
    best = Decimal("0")
    saw = False
    for node in nodes:
        for key in _ORDER_QTY_KEYS:
            number = _dec(node.get(key))
            if number is None:
                continue
            saw = True
            if number > best:
                best = number
        if node.get("tif") == "IOC" and node.get("orderId"):
            dollars = novig_live.filled_dollar_contracts(node)
            if dollars > best:
                saw = True
                best = dollars
    return best if saw else Decimal("0")


def this_order_cum_qty(payload, order_id: str) -> tuple[Decimal, Decimal | None]:
    """Max cumQuantity on THIS order id. Ignores book qtyDecimal / lastShares.

    Guajardo leftover 24 Oct 2026: activities GET was empty at confirm, but the
    IOC body already had PARTIALLY_FILLED cumQuantity 0.19 on D9ZCT3CG11KJ.
    """
    want = str(order_id or "").strip()
    if not want or not isinstance(payload, (dict, list)):
        return Decimal("0"), None
    best = Decimal("0")
    price = None
    for node in _walk(payload):
        if not isinstance(node, dict):
            continue
        nid = node.get("id") or node.get("orderId") or node.get("order_id")
        if not _match_id(nid, want):
            continue
        number = _dec(node.get("cumQuantity"))
        if number is None:
            continue
        if number > best:
            best = number
            px = _dec(node.get("avgPx"))
            if px is not None:
                price = px
    return best, price


def ids_from(payload, spec: dict | None = None) -> dict[str, str]:
    """Order id / client order id / ticker from the HTTP response and send spec."""
    spec = spec if isinstance(spec, dict) else {}
    body = spec.get("body") if isinstance(spec.get("body"), dict) else {}
    order_id = ""
    client_id = ""
    ticker = ""
    for node in _walk(payload):
        if not order_id:
            for key in ("order_id", "orderId", "id"):
                value = node.get(key)
                if value not in (None, ""):
                    order_id = str(value)
                    break
        if not client_id:
            for key in ("client_order_id", "clientOrderId", "clientId"):
                value = node.get(key)
                if value not in (None, ""):
                    client_id = str(value)
                    break
        if not ticker:
            for key in ("ticker", "market_ticker", "symbol", "marketSlug"):
                value = node.get(key)
                if value not in (None, ""):
                    ticker = str(value)
                    break
    if not order_id:
        order_id = str(body.get("order_id") or body.get("orderId") or "")
    if not client_id:
        client_id = str(
            body.get("client_order_id")
            or body.get("clientOrderId")
            or body.get("clientId")
            or spec.get("client_order_id")
            or ""
        )
    if not ticker:
        ticker = str(
            spec.get("instrument")
            or body.get("ticker")
            or body.get("symbol")
            or body.get("marketSlug")
            or ""
        )
    return {
        "order_id": order_id,
        "client_order_id": client_id,
        "ticker": ticker,
        "outcome": str(spec.get("outcome") or "").lower(),
        "venue": str(spec.get("venue") or "").lower(),
    }


def unknown_result(venue: str, note: str, tape_qty: Decimal, ids: dict | None = None) -> dict:
    ids = ids or {}
    return {
        "known": False,
        "qty": "0",
        "avg_price": "",
        "house_fill": False,
        "note": note,
        "endpoint": ENDPOINTS.get(venue, ""),
        "http": 0,
        "mismatch": False,
        "tape_qty": format(tape_qty, "f"),
        "order_id": ids.get("order_id") or "",
        "client_order_id": ids.get("client_order_id") or "",
        "ticker": ids.get("ticker") or "",
        "venue": venue,
    }


def house_size_of(spec: dict | None) -> Decimal:
    """Whole contracts this order asked for. Default 1. Novig 100 native = $1."""
    spec = spec if isinstance(spec, dict) else {}
    body = spec.get("body") if isinstance(spec.get("body"), dict) else {}
    venue = str(spec.get("venue") or "").lower()
    raw = body.get("quantity")
    if raw in (None, ""):
        raw = body.get("count")
    number = _dec(raw)
    if number is None:
        number = _dec(spec.get("order_qty"))
    if number is None or number <= 0:
        return HOUSE_SIZE
    if venue == "novig" and number >= HUNDRED:
        return number / HUNDRED
    return number


def _known_result(
    venue: str,
    qty: Decimal,
    avg_price: Decimal | None,
    note: str,
    http: int,
    tape_qty: Decimal,
    ids: dict,
    house_size: Decimal | None = None,
    fee: Decimal | None = None,
    house_cash: Decimal | None = None,
) -> dict:
    need = house_size if house_size is not None and house_size > 0 else HOUSE_SIZE
    house = qty >= need
    tape_house = tape_qty >= need
    mismatch = (qty != tape_qty) or (house != tape_house)
    if mismatch:
        note = f"{note}; mismatch tape qty {format(tape_qty, 'f')}, using confirm"
    out = {
        "known": True,
        "qty": format(qty, "f"),
        "avg_price": format(avg_price, "f") if avg_price is not None else "",
        "house_fill": house,
        "note": note,
        "endpoint": ENDPOINTS.get(venue, ""),
        "http": http,
        "mismatch": mismatch,
        "tape_qty": format(tape_qty, "f"),
        "order_id": ids.get("order_id") or "",
        "client_order_id": ids.get("client_order_id") or "",
        "ticker": ids.get("ticker") or "",
        "venue": venue,
    }
    if fee is not None:
        out["fee"] = format(fee, "f")
    if house_cash is not None:
        out["house_cash"] = format(house_cash, "f")
        if not out.get("avg_price"):
            out["avg_price"] = format(house_cash, "f")
    return out


def attach_house_cash(confirm: dict, venue: str, spec: dict | None, payload, price) -> dict:
    """Stamp the debit the venue posted. Polymarket BUY_SHORT must not keep Yes-wire."""
    if not isinstance(confirm, dict) or not confirm.get("known"):
        return confirm
    spec = spec if isinstance(spec, dict) else {}
    house = money_px(price)
    fee = money_px(confirm.get("fee"))
    if venue == "polymarket":
        prices = poly_prices_from_payload(payload)
        intent = str(spec.get("intent") or prices.get("intent") or "")
        body = spec.get("body") if isinstance(spec.get("body"), dict) else {}
        api_limit = money_px(body.get("price"))
        if api_limit is None:
            api_limit = money_px(spec.get("limit") or spec.get("limit_price"))
        house = poly_house_cash(
            avg=prices.get("avg") or price,
            spread=prices.get("spread"),
            quote=spec.get("quote_price"),
            pay=spec.get("pay") or spec.get("quote_price"),
            api_limit=api_limit,
            intent=intent,
        )
        if fee is None:
            fee = prices.get("fee")
            if fee is not None:
                confirm["fee"] = format(fee, "f")
        if house is not None:
            confirm["avg_price"] = format(house, "f")
    if house is not None:
        confirm["house_cash"] = format(house, "f")
    return confirm


def _parse_json(text: str):
    try:
        return json.loads(text) if text else {}
    except json.JSONDecodeError:
        return None


def _retryable_http(status: int) -> bool:
    return status in (0, 429, 500, 502, 503, 504)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _parse_dt(value):
    text = str(value or "").strip()
    if not text:
        return None
    if text.isdigit():
        raw = int(text)
        if raw > 10**12:
            return datetime.fromtimestamp(raw / 1000, tz=timezone.utc)
        return datetime.fromtimestamp(raw, tz=timezone.utc)
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        # Polymarket US createTime can carry nanoseconds: 2026-10-23T09:03:55.475059250Z
        if "." not in text:
            return None
        head, rest = text.split(".", 1)
        digits = "".join(ch for ch in rest if ch.isdigit())
        tail = rest[len(digits):] if digits else rest
        try:
            stamp = datetime.fromisoformat(f"{head}.{digits[:6]}{tail}".replace("Z", "+00:00"))
        except ValueError:
            return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def _recent(stamp, window_sec: int) -> bool:
    if stamp is None:
        return True
    age = (datetime.now(timezone.utc) - stamp).total_seconds()
    return -5 <= age <= window_sec


def _match_id(left: str, right: str) -> bool:
    a = str(left or "").strip().lower()
    b = str(right or "").strip().lower()
    return bool(a) and a == b


def _kalshi_qty(fill: dict) -> Decimal:
    number = _dec(fill.get("count_fp") if fill.get("count_fp") not in (None, "") else fill.get("count"))
    return number if number is not None else Decimal("0")


def _kalshi_price(fill: dict, outcome: str) -> Decimal | None:
    yes_px = _dec(fill.get("yes_price_dollars"))
    no_px = _dec(fill.get("no_price_dollars"))
    side = str(fill.get("outcome_side") or fill.get("side") or outcome or "").lower()
    if side == "no":
        if no_px is not None:
            return no_px
        if yes_px is not None:
            return ONE - yes_px
        return None
    return yes_px if yes_px is not None else no_px


def _fetch_kalshi(ids: dict, timeout: float) -> tuple[int, Any, str]:
    query: dict[str, str] = {"limit": "100"}
    if ids.get("order_id"):
        query["order_id"] = ids["order_id"]
    if ids.get("ticker"):
        query["ticker"] = ids["ticker"]
    min_ts = int(time.time()) - CONFIRM_WINDOW_SEC
    query["min_ts"] = str(min_ts)
    status, text = kalshi_private.get_fills(query, timeout=timeout)
    data = _parse_json(text)
    if status != 200 or not isinstance(data, dict) or not isinstance(data.get("fills"), list):
        if _retryable_http(status):
            return status, None, f"kalshi fills HTTP {status}"
        return status, None, f"kalshi fills HTTP {status}"
    return status, data.get("fills") or [], ""


def _from_kalshi_fills(fills: list, ids: dict) -> tuple[Decimal, Decimal | None, str]:
    matched = []
    for fill in fills:
        if not isinstance(fill, dict):
            continue
        if ids.get("order_id"):
            if not _match_id(fill.get("order_id"), ids["order_id"]):
                continue
        elif ids.get("ticker"):
            ticker = str(fill.get("ticker") or fill.get("market_ticker") or "")
            if not _match_id(ticker, ids["ticker"]):
                continue
        else:
            continue
        matched.append(fill)
    qty = Decimal("0")
    price = None
    for fill in matched:
        qty += _kalshi_qty(fill)
        px = _kalshi_price(fill, ids.get("outcome") or "")
        if px is not None:
            price = px
    if matched:
        note = f"kalshi fills GET qty {format(qty, 'f')}"
        if price is not None:
            note = f"{note} @ {format(price, 'f')}"
        return qty, price, note
    return Decimal("0"), None, "kalshi fills GET empty"


def _fetch_gemini(ids: dict, status_filter: str, timeout: float) -> tuple[int, Any, str]:
    extra: dict[str, Any] = {
        "status": status_filter,
        "from": _now_ms() - (CONFIRM_WINDOW_SEC * 1000),
        "to": _now_ms() + 5000,
        "limit": 50,
    }
    if ids.get("ticker"):
        extra["symbol"] = ids["ticker"]
    status, text = gemini_private.get_order_history(extra, timeout=timeout)
    data = _parse_json(text)
    if status != 200 or not isinstance(data, dict) or not isinstance(data.get("orders"), list):
        return status, None, f"gemini history HTTP {status}"
    return status, data.get("orders") or [], ""


def _from_gemini_orders(orders: list, ids: dict, status_filter: str) -> tuple[Decimal, Decimal | None, str] | None:
    matched = []
    for order in orders:
        if not isinstance(order, dict):
            continue
        oid = str(order.get("orderId") or "")
        cid = str(order.get("clientOrderId") or "")
        symbol = str(order.get("symbol") or "")
        if ids.get("order_id") and not (_match_id(oid, ids["order_id"]) or _match_id(cid, ids["order_id"])):
            if not (ids.get("client_order_id") and _match_id(cid, ids["client_order_id"])):
                continue
        elif ids.get("client_order_id") and not ids.get("order_id"):
            if not _match_id(cid, ids["client_order_id"]):
                continue
        elif not ids.get("order_id") and not ids.get("client_order_id"):
            if ids.get("ticker") and not _match_id(symbol, ids["ticker"]):
                continue
        matched.append(order)
    if ids.get("order_id") or ids.get("client_order_id"):
        use = matched
    elif len(matched) == 1:
        use = matched
    elif len(matched) == 0:
        return Decimal("0"), None, f"gemini history {status_filter} empty"
    else:
        return None
    qty = Decimal("0")
    price = None
    last_status = status_filter
    for order in use:
        number = _dec(order.get("filledQuantity") if order.get("filledQuantity") not in (None, "") else order.get("filled_quantity"))
        if number is not None and number > qty:
            qty = number
        px = _dec(order.get("avgExecutionPrice"))
        if px is not None:
            price = px
        last_status = str(order.get("status") or last_status)
    note = f"gemini history {last_status} qty {format(qty, 'f')}"
    if price is not None:
        note = f"{note} @ {format(price, 'f')}"
    return qty, price, note


def _fetch_poly(ids: dict, timeout: float) -> tuple[int, Any, str]:
    query: dict[str, str] = {
        "limit": "50",
        "types": "ACTIVITY_TYPE_TRADE",
        "sortOrder": "SORT_ORDER_DESCENDING",
    }
    if ids.get("ticker"):
        query["marketSlug"] = ids["ticker"]
    status, text = polymarket_us_live.get_activities(query, timeout=timeout)
    data = _parse_json(text)
    if status != 200 or not isinstance(data, dict) or not isinstance(data.get("activities"), list):
        return status, None, f"polymarket activities HTTP {status}"
    return status, data.get("activities") or [], ""


def _poly_nested_order_id(node) -> str:
    if not isinstance(node, dict):
        return ""
    if node.get("id") not in (None, ""):
        return str(node.get("id"))
    order = node.get("order")
    if isinstance(order, dict) and order.get("id") not in (None, ""):
        return str(order.get("id"))
    return ""


def _poly_our_order_id(item: dict) -> str:
    """IOC taker order id. Do not use the passive counterparty's resting order."""
    trade = item.get("trade") if isinstance(item.get("trade"), dict) else {}
    if trade.get("isAggressor") is False:
        return _poly_nested_order_id(trade.get("passive")) or _poly_nested_order_id(
            trade.get("passiveExecution")
        )
    return _poly_nested_order_id(trade.get("aggressor")) or _poly_nested_order_id(
        trade.get("aggressorExecution")
    )


def _from_poly_activities(activities: list, ids: dict) -> tuple[Decimal, Decimal | None, str]:
    qty = Decimal("0")
    price = None
    n = 0
    want = str(ids.get("order_id") or "").strip()
    if not want:
        return Decimal("0"), None, "polymarket confirm skipped; no aggressor order id"
    for item in activities:
        if not isinstance(item, dict):
            continue
        trade = item.get("trade") if isinstance(item.get("trade"), dict) else {}
        slug = str(trade.get("marketSlug") or "")
        if ids.get("ticker") and slug and not _match_id(slug, ids["ticker"]):
            continue
        stamp = _parse_dt(trade.get("createTime") or trade.get("updateTime"))
        if not _recent(stamp, POLY_RECENT_SEC):
            continue
        if want:
            ours = _poly_our_order_id(item)
            if not ours or not _match_id(ours, want):
                continue
        number = _dec(trade.get("qtyDecimal") if trade.get("qtyDecimal") not in (None, "") else trade.get("qty"))
        if number is None:
            continue
        qty += number
        n += 1
        px = _dec(trade.get("price"))
        if px is not None:
            price = px
    if n == 0:
        return Decimal("0"), None, "polymarket activities GET empty"
    note = f"polymarket activities GET qty {format(qty, 'f')}"
    if qty < HOUSE_SIZE:
        note = f"{note} (not house fill)"
    if price is not None:
        note = f"{note} @ {format(price, 'f')}"
    return qty, price, note


def _novig_items(payload):
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("items"), list):
        return [row for row in payload["items"] if isinstance(row, dict)]
    items = []
    for value in payload.values():
        if isinstance(value, dict) and isinstance(value.get("items"), list):
            items.extend(row for row in value["items"] if isinstance(row, dict))
    return items


def _fetch_novig(ids: dict, timeout: float) -> tuple[int, Any, str]:
    query: dict[str, str] = {
        "limit": "100",
        "startsAfter": str(_now_ms() - (CONFIRM_WINDOW_SEC * 1000) - 1),
        "startsBefore": str(_now_ms() + 5000),
    }
    if ids.get("order_id"):
        query["order"] = ids["order_id"]
    status, text = novig_live.list_fills(query, timeout=timeout)
    data = _parse_json(text)
    if status != 200 or data is None:
        return status, None, f"novig fills HTTP {status}"
    return status, _novig_items(data), ""


def _from_novig_fills(fills: list, ids: dict) -> tuple[Decimal, Decimal | None, str, Decimal | None]:
    matched = []
    native = Decimal("0")
    cost = Decimal("0")
    n = 0
    for fill in fills:
        if not isinstance(fill, dict):
            continue
        if ids.get("order_id") and not _match_id(fill.get("orderId"), ids["order_id"]):
            continue
        qty_n = _dec(fill.get("qty"))
        if qty_n is None:
            continue
        native += qty_n
        n += 1
        matched.append(fill)
        add_cost = _dec(fill.get("cost"))
        if add_cost is not None:
            cost += add_cost
    if n == 0:
        return Decimal("0"), None, "novig fills GET empty", None
    dollars = (native / HUNDRED).quantize(Decimal("0.01"))
    price = None
    if native != 0 and cost != 0:
        price = (HUNDRED * cost) / native
    fee = novig_live.fee_from_fills(matched)
    note = f"novig fills GET qty {format(dollars, 'f')}"
    if price is not None:
        note = f"{note} @ {format(price, 'f')}"
    if fee is not None:
        note = f"{note} fee {format(fee, 'f')}"
    return dollars, price, note, fee


def _one_fetch(venue: str, ids: dict, timeout: float) -> tuple[bool, dict | None, str, int]:
    """One bounded read. Returns (ok_shape, known_result_or_none, retry_note, http)."""
    if venue == "kalshi":
        status, fills, err = _fetch_kalshi(ids, timeout)
        if fills is None:
            return (not _retryable_http(status), None, err, status)
        qty, price, note = _from_kalshi_fills(fills, ids)
        return True, (qty, price, note, status), "", status
    if venue == "gemini":
        status, orders, err = _fetch_gemini(ids, "filled", timeout)
        if orders is None:
            return (not _retryable_http(status), None, err, status)
        parsed = _from_gemini_orders(orders, ids, "filled")
        if parsed is None:
            return True, None, "gemini history matched more than one order", status
        qty, price, note = parsed
        if qty > 0:
            return True, (qty, price, note, status), "", status
        status2, cancelled, err2 = _fetch_gemini(ids, "cancelled", timeout)
        if cancelled is None:
            if qty == 0 and status == 200:
                return True, (Decimal("0"), None, "gemini history filled empty", status), "", status
            return (not _retryable_http(status2), None, err2, status2)
        parsed2 = _from_gemini_orders(cancelled, ids, "cancelled")
        if parsed2 is None:
            return True, (Decimal("0"), None, "gemini history filled empty", status), "", status
        qty2, price2, note2 = parsed2
        if qty2 > 0:
            return True, (qty2, price2, note2, status2), "", status2
        return True, (Decimal("0"), None, note2 if cancelled else "gemini history empty", status2 or status), "", status2 or status
    if venue == "polymarket":
        if not ids.get("ticker"):
            return True, None, "polymarket confirm needs marketSlug", 0
        status, activities, err = _fetch_poly(ids, timeout)
        if activities is None:
            return (not _retryable_http(status), None, err, status)
        qty, price, note = _from_poly_activities(activities, ids)
        return True, (qty, price, note, status), "", status
    if venue == "novig":
        status, fills, err = _fetch_novig(ids, timeout)
        if fills is None:
            return (not _retryable_http(status), None, err, status)
        qty, price, note, fee = _from_novig_fills(fills, ids)
        return True, (qty, price, note, status, fee), "", status
    return True, None, f"no confirm endpoint for {venue}", 0


def confirm_order(
    venue: str,
    payload=None,
    spec: dict | None = None,
    tape_qty: Decimal | None = None,
    tries: int | None = None,
    timeout: float | None = None,
    sleep_sec: float | None = None,
) -> dict:
    """Fetch that venue's fill/history and return qty, avg price, and a public note.

    known=False means timeout or a bad response: do not claim a fill.
    known=True and qty 0 is an empty cancel. House fill is this-order
    cumQuantity >= the qty we sent (default 1). Partial 0 < q < qty is not
    a house 1-contract fill.
    """
    venue = str(venue or "").lower()
    ids = ids_from(payload, spec)
    ids["venue"] = venue
    need = house_size_of(spec)
    tape = tape_qty if tape_qty is not None else tape_filled_qty(payload)
    if venue not in ENDPOINTS:
        return unknown_result(venue, "no confirm endpoint", tape, ids)
    attempts = max(1, int(tries if tries is not None else CONFIRM_TRIES))
    if tape >= need:
        attempts = max(attempts, CONFIRM_TRIES + 1)
    limit = float(timeout if timeout is not None else CONFIRM_TIMEOUT_SEC)
    pause = float(sleep_sec if sleep_sec is not None else CONFIRM_SLEEP_SEC)
    last_note = "confirm unknown"
    last_http = 0
    for attempt in range(attempts):
        try:
            done, parsed, err, http = _one_fetch(venue, ids, limit)
        except Exception as exc:
            last_note = f"confirm {type(exc).__name__}"
            last_http = 0
            done = False
            parsed = None
            http = 0
            err = last_note
        last_http = http or last_http
        if parsed is not None:
            qty, price, note, status = parsed[0], parsed[1], parsed[2], parsed[3]
            fee = parsed[4] if len(parsed) > 4 else None
            if venue == "polymarket" and qty == 0:
                cum, px = this_order_cum_qty(payload, ids.get("order_id") or "")
                if cum > 0:
                    extra = f"polymarket activities GET empty; this-order cumQuantity {format(cum, 'f')}"
                    if cum < need:
                        extra = f"{extra} (not house fill)"
                    if px is not None:
                        extra = f"{extra} @ {format(px, 'f')}"
                    row = _known_result(venue, cum, px, extra, status, tape, ids, house_size=need)
                    return attach_house_cash(row, venue, spec, payload, px)
            row = _known_result(venue, qty, price, note, status, tape, ids, house_size=need, fee=fee)
            return attach_house_cash(row, venue, spec, payload, price)
        last_note = err or last_note
        if done:
            return unknown_result(venue, last_note, tape, ids) | {"http": last_http}
        if attempt + 1 < attempts:
            time.sleep(pause)
    return unknown_result(venue, last_note or "confirm timeout; unknown", tape, ids) | {"http": last_http}


def attach(payload, confirm: dict):
    """Copy payload and store the confirm overlay. Does not mutate the HTTP body in place."""
    if isinstance(payload, dict):
        out = dict(payload)
        out[PAYLOAD_KEY] = confirm
        return out
    if isinstance(payload, list):
        return {"orders": payload, PAYLOAD_KEY: confirm}
    return {PAYLOAD_KEY: confirm}


def from_payload(payload) -> dict | None:
    if isinstance(payload, dict):
        row = payload.get(PAYLOAD_KEY)
        if isinstance(row, dict):
            return row
    return None


def qty_of(confirm: dict | None) -> Decimal:
    if not isinstance(confirm, dict) or not confirm.get("known"):
        return Decimal("0")
    number = _dec(confirm.get("qty"))
    return number if number is not None else Decimal("0")
