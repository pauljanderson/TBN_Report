"""Send a 1-contract lock when the live compare nets $0.95 or less.

Paul authorized this on 2026-10-18: execute when the locked profit is at least
$0.05 a contract. Research only. Not gold. Not DailyRun. The size cap stays 1.

A lock is Yes on one venue and No on the other for the same settlement. The
fee is the documented fee on the charging leg only. Kalshi is not given a fee.
The closed Tennessee vs Indianapolis 13.5 trade is never sent.

Secrets stay in secrets/. This module logs status, instrument, side, limit, and
size. It does not log keys, signatures, or auth headers.

Paul turned placing orders off for now (2026-10-18). The send code stays.
ORDERS_ENABLED must be True before any venue order call.
"""
from __future__ import annotations

import json
import os
import uuid
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN
from pathlib import Path

import gemini_private
import kalshi_private
import polymarket_us_live
import venue_pace

# Hard switch. False: log a skip and return before any venue order HTTP.
ORDERS_ENABLED = False

ROOT = Path(__file__).resolve().parents[1]
STAMP = ROOT / "drive" / "paul_experiments" / "prediction_market_arb_exhaustive_20261017"
RAW = STAMP / "raw"
ORDERS = RAW / "orders.jsonl"
ORDER_LOCK = RAW / "orders.lock"
ONE = Decimal("1")
CENT = Decimal("0.01")
NET_MAX = Decimal("0.95")
SIZE = Decimal("1")
KALSHI_TICK = Decimal("0.0001")
POLY_TICK = Decimal("0.001")
CLOSED = {"closed", "settled", "determined", "finalized", "inactive"}
_capability: dict[str, tuple[float, bool, str]] = {}


def _money(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text


def _dec(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace("$", "").replace(",", ""))
    except Exception:
        return None


def _public_note(body: str) -> str:
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return "response was not json"
    if not isinstance(data, dict):
        return "response was not an object"
    text = str(data.get("message") or data.get("reason") or data.get("error") or data.get("code") or "")
    text = " ".join(text.split())[:240]
    lowered = text.lower()
    if any(word in lowered for word in ("signature", "secret", "bearer", "api key", "apikey")):
        return "rejected"
    return text or "no message"


def historical_tennessee_13_5(title: str, game: dict, cand: dict) -> bool:
    """The already-closed Tennessee vs Indianapolis 13.5. Never send it."""
    blob = " ".join(
        str(part)
        for part in (
            title,
            game.get("title_gemini") if isinstance(game, dict) else "",
            game.get("title_kalshi") if isinstance(game, dict) else "",
            game.get("codes") if isinstance(game, dict) else "",
            cand.get("side"),
            cand.get("number"),
            cand.get("kalshi_ticker"),
            cand.get("gemini_symbol"),
            cand.get("market_type"),
        )
    ).lower()
    teams = ("tennessee" in blob or "titans" in blob) and ("indianapolis" in blob or "colts" in blob)
    line = str(cand.get("number") or "") in ("13.5", "13.50") or "13.5" in blob
    return bool(teams and line)


def whole_size(value) -> bool:
    number = _dec(value)
    return number is not None and number >= SIZE


def pair_net(scan, cand: dict) -> Decimal | None:
    """Gross plus the documented fee on each charging leg. None when a fee is unknown."""
    yes = _dec(cand.get("yes_price"))
    no = _dec(cand.get("no_price"))
    if yes is None or no is None:
        return None
    fee = Decimal("0")
    for venue, price in ((str(cand.get("yes_venue") or "").lower(), yes), (str(cand.get("no_venue") or "").lower(), no)):
        if venue == "kalshi":
            continue
        if venue == "gemini":
            fee += scan.gemini_fee(price)
            continue
        if venue == "polymarket":
            part = polymarket_us_live.taker_fee(price, cand.get("fee_coefficient"))
            if part is None:
                saved = _dec(cand.get("polymarket_fee"))
                if saved is None:
                    return None
                part = saved
            fee += part
            continue
        return None
    return yes + no + fee


def qualifies(scan, cand: dict, title: str, game: dict) -> tuple[bool, str]:
    if historical_tennessee_13_5(title, game, cand):
        return False, "closed Tennessee vs Indianapolis 13.5 is not sent"
    if scan.gemini_no_rejection(cand):
        return False, "Gemini No is not a buyable offer"
    for field in ("kalshi_status", "gemini_status"):
        if str(cand.get(field) or "").lower() in CLOSED:
            return False, "contract is closed"
    if not whole_size(cand.get("yes_size")) or not whole_size(cand.get("no_size")):
        return False, "both books need at least 1 contract"
    net = pair_net(scan, cand)
    if net is None:
        return False, "fee unknown"
    if net > NET_MAX:
        return False, f"net {_money(net)} is above 0.95"
    return True, f"net {_money(net)}"


def _norm_num(value) -> str:
    number = _dec(value)
    if number is None:
        return ""
    if number == number.to_integral():
        return str(int(number))
    return format(number.normalize(), "f")


def leg_moves(fresh: list[dict], cand: dict) -> tuple[Decimal | None, Decimal | None]:
    """Absolute move since the last check for the Yes leg and the No leg."""
    found = {"yes": None, "no": None}
    kind = str(cand.get("market_type") or "")
    number = _norm_num(cand.get("number"))
    for outcome, venue_key in (("yes", "yes_venue"), ("no", "no_venue")):
        venue = str(cand.get(venue_key) or "").lower()
        best: Decimal | None = None
        seen = False
        for row in fresh or []:
            if str(row.get("venue") or "").lower() != venue:
                continue
            if str(row.get("pay") or "").lower() != outcome:
                continue
            if str(row.get("market_type") or "") != kind:
                continue
            if _norm_num(row.get("number")) != number:
                continue
            move = _dec(row.get("move"))
            if move is None:
                continue
            seen = True
            size = abs(move)
            if best is None or size > best:
                best = size
        found[outcome] = best if seen else None
    return found["yes"], found["no"]


def ordered_outcomes(cand: dict, fresh: list[dict]) -> list[str]:
    """Yes or No labels in send order. Missing moves send Kalshi first."""
    yes_move, no_move = leg_moves(fresh, cand)
    venues = {
        "yes": str(cand.get("yes_venue") or "").lower(),
        "no": str(cand.get("no_venue") or "").lower(),
    }
    if yes_move is None or no_move is None:
        if "kalshi" in venues.values():
            first = "yes" if venues["yes"] == "kalshi" else "no"
            return [first, "no" if first == "yes" else "yes"]
        return ["yes", "no"]
    if yes_move > no_move:
        return ["yes", "no"]
    if no_move > yes_move:
        return ["no", "yes"]
    if venues["yes"] == "kalshi":
        return ["yes", "no"]
    if venues["no"] == "kalshi":
        return ["no", "yes"]
    return ["yes", "no"]


def kalshi_order_body(ticker: str, outcome: str, pay: Decimal, client_order_id: str) -> dict:
    """V2 event order. bid buys Yes. ask sells Yes, which buys No at 1 - price."""
    if outcome == "yes":
        price = pay.quantize(KALSHI_TICK, rounding=ROUND_DOWN)
        side = "bid"
    elif outcome == "no":
        price = (ONE - pay).quantize(KALSHI_TICK, rounding=ROUND_CEILING)
        side = "ask"
    else:
        raise ValueError("outcome")
    return {
        "ticker": ticker,
        "client_order_id": client_order_id,
        "side": side,
        "count": "1.00",
        "price": format(price, "f"),
        "time_in_force": "immediate_or_cancel",
        "self_trade_prevention_type": "taker_at_cross",
        "post_only": False,
    }


def gemini_order_payload(symbol: str, outcome: str, pay: Decimal) -> dict:
    price = pay.quantize(KALSHI_TICK, rounding=ROUND_DOWN)
    return {
        "symbol": symbol,
        "orderType": "limit",
        "side": "buy",
        "quantity": "1",
        "price": format(price, "f"),
        "outcome": outcome,
        "timeInForce": "immediate-or-cancel",
    }


def polymarket_api_price(intent: str, pay: Decimal) -> Decimal:
    """Long-side price. A short buy at `pay` is sent as 1 - pay, rounded so we do not pay more."""
    if intent in ("ORDER_INTENT_BUY_LONG", "ORDER_INTENT_SELL_LONG"):
        return pay.quantize(POLY_TICK, rounding=ROUND_DOWN)
    if intent in ("ORDER_INTENT_BUY_SHORT", "ORDER_INTENT_SELL_SHORT"):
        return (ONE - pay).quantize(POLY_TICK, rounding=ROUND_CEILING)
    raise ValueError("intent")


def polymarket_order_body(slug: str, intent: str, api_price: Decimal) -> dict:
    return {
        "marketSlug": slug,
        "type": "ORDER_TYPE_LIMIT",
        "price": {"value": format(api_price, "f"), "currency": "USD"},
        "quantity": 1,
        "tif": "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL",
        "intent": intent,
        "participateDontInitiate": False,
        "manualOrderIndicator": "MANUAL_ORDER_INDICATOR_AUTOMATIC",
        "synchronousExecution": True,
        "maxBlockTime": "3",
    }


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def filled_contracts(payload) -> Decimal:
    """Contracts filled, from the fields the three venues return. Zero when unknown."""
    if not isinstance(payload, (dict, list)):
        return Decimal("0")
    qty_keys = ("fill_count", "filledQuantity", "filled_quantity", "cumQuantity", "executedQuantity", "quantityFilled")
    best = Decimal("0")
    for node in _walk(payload):
        status = str(node.get("status") or node.get("state") or node.get("orderState") or "").lower()
        if status in ("filled", "executed", "complete", "completed"):
            best = max(best, SIZE)
        for key in qty_keys:
            number = _dec(node.get(key))
            if number is not None and number > best:
                best = number
    return best


def order_still_open(payload) -> bool:
    if not isinstance(payload, (dict, list)):
        return False
    for node in _walk(payload):
        status = str(node.get("status") or node.get("state") or node.get("orderState") or "").lower()
        remaining = _dec(node.get("remaining_count") or node.get("remainingQuantity") or node.get("leavesQuantity"))
        if status in ("open", "resting", "new", "accepted", "pending"):
            return True
        if remaining is not None and remaining > 0 and status not in ("canceled", "cancelled", "expired", "rejected"):
            return True
    return False


def bet_blocked(rows: list[dict], bet_key: str, pid_alive) -> bool:
    """True when this bet is open, filled, or claimed by a process that is still alive."""
    phase = "clear"
    claim_pid = None
    for row in rows:
        if row.get("bet_key") != bet_key:
            continue
        event = row.get("event")
        if event == "claim":
            if phase != "position":
                phase = "working"
                claim_pid = row.get("pid")
        elif event == "sent":
            if phase != "position":
                phase = "sent"
        elif event in ("filled", "one_leg"):
            phase = "position"
        elif event == "both_unfilled" and phase != "position":
            phase = "clear"
        elif event == "preflight_skip" and phase == "working":
            phase = "clear"
    if phase in ("position", "sent"):
        return True
    if phase == "working":
        try:
            return bool(claim_pid) and bool(pid_alive(int(claim_pid)))
        except (TypeError, ValueError):
            return True
    return False


def _read_orders() -> list[dict]:
    if not ORDERS.exists():
        return []
    rows = []
    for line in ORDERS.read_text(encoding="utf-8").splitlines():
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


def _append_unlocked(row: dict) -> None:
    ORDERS.parent.mkdir(parents=True, exist_ok=True)
    with ORDERS.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def _append(row: dict) -> None:
    with venue_pace.FileLock(ORDER_LOCK):
        _append_unlocked(row)


def _leg_spec(cand: dict, outcome: str) -> dict | None:
    venue = str(cand.get(f"{outcome}_venue") or "").lower()
    pay = _dec(cand.get(f"{outcome}_price"))
    if pay is None or pay <= 0 or pay >= 1:
        return None
    if venue == "kalshi":
        ticker = str(cand.get("kalshi_ticker") or "")
        if not ticker:
            return None
        body = kalshi_order_body(ticker, outcome, pay, str(uuid.uuid4()))
        return {"venue": "kalshi", "instrument": ticker, "outcome": outcome, "pay": format(pay, "f"), "limit": body["price"], "body": body}
    if venue == "gemini":
        symbol = str(cand.get("gemini_symbol") or "")
        if not symbol:
            return None
        payload = gemini_order_payload(symbol, outcome, pay)
        return {"venue": "gemini", "instrument": symbol, "outcome": outcome, "pay": format(pay, "f"), "limit": payload["price"], "body": payload}
    if venue == "polymarket":
        slug = str(cand.get("polymarket_slug") or "")
        intent = str(cand.get("polymarket_intent") or "")
        if not slug or not intent:
            return None
        try:
            api_price = polymarket_api_price(intent, pay)
        except ValueError:
            return None
        if api_price < Decimal("0.01") or api_price > Decimal("0.99"):
            return None
        body = polymarket_order_body(slug, intent, api_price)
        return {"venue": "polymarket", "instrument": slug, "outcome": outcome, "pay": format(pay, "f"), "limit": body["price"]["value"], "body": body}
    return None


def _capability_ok(venue: str, now: float) -> tuple[bool, str]:
    cached = _capability.get(venue)
    if cached and now - cached[0] < 300:
        return cached[1], cached[2]
    ok, reason = _probe(venue)
    _capability[venue] = (now, ok, reason)
    return ok, reason


def _probe(venue: str) -> tuple[bool, str]:
    try:
        if venue == "kalshi":
            status, usd = kalshi_private.balance_usd()
            if status == 200 and usd is not None:
                return True, f"kalshi balance {usd}"
            return False, f"kalshi balance http {status}"
        if venue == "gemini":
            status, body = gemini_private.private_call("/v1/prediction-markets/terms/status", None, "GET")
            if status != 200:
                status, body = gemini_private.private_call("/v1/prediction-markets/terms/status", None, "POST")
            if status != 200:
                return False, f"gemini terms http {status} {_public_note(body)}"
            data = json.loads(body)
            if data.get("hasAcceptedLatest") is True:
                return True, "gemini terms accepted"
            return False, "gemini prediction-market terms are not accepted"
        if venue == "polymarket":
            status, body = polymarket_us_live.signed_json("GET", "/v1/account/balances")
            if status != 200:
                return False, f"polymarket balance http {status} {_public_note(body)}"
            return True, "polymarket balance read"
    except Exception as exc:
        return False, type(exc).__name__
    return False, "unknown venue"


def _affordable(spec: dict, balances: dict[str, Decimal]) -> bool:
    cash = balances.get(spec["venue"])
    pay = _dec(spec["pay"])
    if cash is None or pay is None:
        return False
    return cash >= pay


def _read_balances() -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    try:
        status, usd = kalshi_private.balance_usd()
        if status == 200 and usd is not None:
            out["kalshi"] = Decimal(usd)
    except Exception:
        pass
    try:
        status, body = gemini_private.private_call("/v1/balances", None, "POST")
        if status == 200:
            data = json.loads(body)
            if isinstance(data, list):
                for row in data:
                    if isinstance(row, dict) and str(row.get("currency") or "").upper() == "USD":
                        number = _dec(row.get("available"))
                        if number is not None:
                            out["gemini"] = number
    except Exception:
        pass
    try:
        status, body = polymarket_us_live.signed_json("GET", "/v1/account/balances")
        if status == 200:
            data = json.loads(body)
            for row in data.get("balances") or []:
                if isinstance(row, dict) and str(row.get("currency") or "USD").upper() == "USD":
                    number = _dec(row.get("buyingPower"))
                    if number is not None:
                        out["polymarket"] = number
    except Exception:
        pass
    return out


def _preview(spec: dict) -> tuple[bool, str]:
    if not ORDERS_ENABLED:
        return False, "placing orders is off"
    if spec["venue"] != "polymarket":
        return True, "no preview endpoint"
    status, body = polymarket_us_live.signed_json("POST", "/v1/order/preview", {"request": spec["body"]})
    if status == 200:
        return True, "preview 200"
    return False, f"preview http {status} {_public_note(body)}"


def _send(spec: dict) -> tuple[int, dict | None, str]:
    if not ORDERS_ENABLED:
        return 0, None, "placing orders is off"
    if spec["venue"] == "kalshi":
        status, body = kalshi_private.signed_call("POST", "/trade-api/v2/portfolio/events/orders", spec["body"])
    elif spec["venue"] == "gemini":
        status, body = gemini_private.private_call("/v1/prediction-markets/order", spec["body"], "POST")
    elif spec["venue"] == "polymarket":
        status, body = polymarket_us_live.signed_json("POST", "/v1/orders", spec["body"])
    else:
        return 0, None, "unknown venue"
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        payload = None
    return status, payload if isinstance(payload, (dict, list)) else None, _public_note(body)


def _order_id(payload) -> str:
    if not isinstance(payload, (dict, list)):
        return ""
    for node in _walk(payload):
        for key in ("order_id", "orderId", "id"):
            value = node.get(key)
            if value not in (None, ""):
                return str(value)
    return ""


def _cancel(spec: dict, payload) -> tuple[int, str]:
    order_id = _order_id(payload)
    if not order_id:
        return 0, "no order id"
    if spec["venue"] == "kalshi":
        status, body = kalshi_private.signed_call(
            "DELETE",
            f"/trade-api/v2/portfolio/events/orders/{order_id}",
            query={"market_ticker": spec["instrument"]},
        )
        return status, _public_note(body)
    if spec["venue"] == "gemini":
        try:
            gid = int(order_id)
        except ValueError:
            return 0, "gemini order id was not an integer"
        status, body = gemini_private.private_call("/v1/prediction-markets/order/cancel", {"orderId": gid}, "POST")
        return status, _public_note(body)
    if spec["venue"] == "polymarket":
        status, body = polymarket_us_live.signed_json(
            "POST",
            f"/v1/order/{order_id}/cancel",
            {"marketSlug": spec["instrument"]},
        )
        return status, _public_note(body)
    return 0, "unknown venue"


def _log_sent(log, spec: dict, status: int) -> None:
    log(
        f"order sent venue={spec['venue']} instrument={spec['instrument']} side={spec['outcome']} "
        f"limit={spec['limit']} size=1 http={status}"
    )


def _log_one_leg(log, spec: dict) -> None:
    log(
        f"ONE LEG venue={spec['venue']} contract={spec['instrument']} side={spec['outcome']} "
        f"size=1 price={spec['pay']}"
    )


def _execution_price(payload, outcome: str) -> str:
    """Fill price from the venue response, when it sent one. Empty when it did not."""
    if not isinstance(payload, (dict, list)):
        return ""
    preferred = "yes_price_dollars" if outcome == "yes" else "no_price_dollars"
    found = ""
    for node in _walk(payload):
        if node.get(preferred) not in (None, ""):
            found = str(node.get(preferred))
        elif not found:
            for key in ("avg_price", "averagePrice", "filledPrice"):
                if node.get(key) not in (None, ""):
                    found = str(node.get(key))
                    break
    return found


def one_leg_message(title: str, first: dict, first_payload, second: dict, status2: int, note2: str, second_payload) -> str:
    """Phone and log text. Separate from the under-$1 opportunity ping."""
    fill = _execution_price(first_payload, str(first.get("outcome") or ""))
    price = f"fill {fill}" if fill else f"limit {first.get('pay')}"
    order_id = _order_id(first_payload)
    order_bit = f" order {order_id}" if order_id else ""
    other_id = _order_id(second_payload)
    other_bit = f" order {other_id}" if other_id else ""
    return (
        "one leg filled, other leg did not. "
        f"{title}. Filled {first.get('venue')} {first.get('outcome')} {first.get('instrument')} "
        f"{price} size 1{order_bit}. "
        f"Other leg {second.get('venue')} {second.get('outcome')} {second.get('instrument')} "
        f"http {status2} {note2}{other_bit}. No repair order was sent."
    )


def alert_one_leg(log, title: str, first: dict, first_payload, second: dict, status2: int, note2: str, second_payload) -> None:
    """Supervisor log, a durable HTML note, and one phone attempt. Does not send an order."""
    message = one_leg_message(title, first, first_payload, second, status2, note2, second_payload)
    log(message)
    row = {
        "seen_at": "",
        "game": title,
        "filled_venue": first.get("venue"),
        "contract": first.get("instrument"),
        "side": first.get("outcome"),
        "price": _execution_price(first_payload, str(first.get("outcome") or "")) or str(first.get("pay") or ""),
        "order_id": _order_id(first_payload),
        "other_venue": second.get("venue"),
        "other_contract": second.get("instrument"),
        "other_side": second.get("outcome"),
        "other_result": f"http {status2} {note2}",
        "other_order_id": _order_id(second_payload),
        "note": "one leg filled, other leg did not. No repair order was sent.",
    }
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        row["seen_at"] = datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds")
    except Exception:
        row["seen_at"] = ""
    try:
        import stream_health

        stream_health.append_one_leg_alert(row)
    except Exception as exc:
        log(f"one leg note failed {type(exc).__name__}")
    _phone_one_leg(log, message)


def _phone_one_leg(log, message: str) -> None:
    """One ntfy attempt. The helper retries a timeout. This does not place an order."""
    try:
        import ntfy_job_done

        url = f"{ntfy_job_done.NTFY_BASE}/{ntfy_job_done.PAUL_TOPIC}"
        status = ntfy_job_done._post(url, message, "One leg filled")
    except Exception as exc:
        log(f"one leg phone alert failed {type(exc).__name__}")
        return
    if status and 200 <= status < 300:
        log(f"one leg phone alert http {status}")
    else:
        log(f"one leg phone alert failed http {status or 'timeout'}")


_orders_off_logged: set[str] = set()


def _note_orders_off(log, key: str) -> None:
    """One skip line per bet. Does not call a venue."""
    if key in _orders_off_logged:
        return
    with venue_pace.FileLock(ORDER_LOCK):
        already = any(
            row.get("bet_key") == key and row.get("event") == "orders_off"
            for row in _read_orders()
        )
        if already:
            _orders_off_logged.add(key)
            return
        _append_unlocked({
            "event": "orders_off",
            "bet_key": key,
            "note": "placing orders is off",
        })
    _orders_off_logged.add(key)
    log("order skipped; placing orders is off")


def execute_locks(scan, sport: str, title: str, game: dict, result: dict, fresh: list[dict], log) -> None:
    """Send qualifying pairs. Pairs under $1 but above $0.95 stay alerts only."""
    if result.get("closed"):
        return
    candidates = [row for row in (result.get("candidates") or []) if isinstance(row, dict)]
    ready = []
    for cand in candidates:
        ok, reason = qualifies(scan, cand, title, game if isinstance(game, dict) else {})
        if ok:
            ready.append((cand, reason))
    if not ready:
        return
    if not ORDERS_ENABLED:
        for cand, _reason in ready:
            key = scan._trade_bet_key(sport, game, cand)
            _note_orders_off(log, key)
        return
    import time
    now = time.time()
    for cand, reason in ready:
        key = scan._trade_bet_key(sport, game, cand)
        outcomes = ordered_outcomes(cand, fresh)
        legs = []
        for outcome in outcomes:
            spec = _leg_spec(cand, outcome)
            if spec is None:
                log(f"order skip {title} {reason} missing order fields for {outcome}")
                legs = []
                break
            legs.append(spec)
        if len(legs) != 2:
            continue
        venues = [leg["venue"] for leg in legs]
        blocked_reason = ""
        for venue in venues:
            ok, why = _capability_ok(venue, now)
            if not ok:
                blocked_reason = why
                break
        if blocked_reason:
            log(f"order skip both legs {title} {blocked_reason}")
            continue
        balances = _read_balances()
        balance_note = " ".join(f"{name}={_money(amount)}" for name, amount in sorted(balances.items()))
        log(f"balances before send {balance_note or 'none parsed'}")
        if any(venue not in balances for venue in venues) or any(not _affordable(leg, balances) for leg in legs):
            log(f"order skip both legs {title} balance does not cover 1 contract")
            continue
        preview_reason = ""
        for leg in legs:
            ok, why = _preview(leg)
            if not ok:
                preview_reason = why
                break
        if preview_reason:
            log(f"order skip both legs {title} {preview_reason}")
            continue
        with venue_pace.FileLock(ORDER_LOCK):
            if bet_blocked(_read_orders(), key, _pid_alive):
                log(f"order skip duplicate {title} {cand.get('market_type')} {cand.get('side')} {cand.get('number')}")
                continue
            _append_unlocked({
                "event": "claim",
                "bet_key": key,
                "sport": sport,
                "game": title,
                "market_type": cand.get("market_type"),
                "side": cand.get("side"),
                "number": cand.get("number"),
                "net": reason,
                "pid": os.getpid(),
            })
        _send_pair(log, key, title, legs)


def _send_pair(log, key: str, title: str, legs: list[dict]) -> None:
    first, second = legs
    status, payload, note = _send(first)
    first_payload = payload
    _log_sent(log, first, status)
    _append({
        "event": "sent",
        "bet_key": key,
        "venue": first["venue"],
        "instrument": first["instrument"],
        "side": first["outcome"],
        "limit_price": first["limit"],
        "size": "1",
        "http_status": status,
        "note": note,
        "order_id": _order_id(payload),
    })
    filled = filled_contracts(payload) if status in (200, 201) else Decimal("0")
    if status in (200, 201) and order_still_open(payload) and filled < SIZE:
        cancel_status, cancel_note = _cancel(first, payload)
        log(f"order cancel venue={first['venue']} instrument={first['instrument']} http={cancel_status} {cancel_note}")
        filled = Decimal("0")
    if filled < SIZE:
        log(f"order first leg not filled {title} {first['venue']} {first['outcome']}; second leg not sent")
        _append({"event": "both_unfilled", "bet_key": key, "venue": first["venue"], "http_status": status, "note": note})
        return
    _append({"event": "filled", "bet_key": key, "venue": first["venue"], "instrument": first["instrument"], "side": first["outcome"], "size": "1", "price": first["pay"]})
    status2, payload2, note2 = _send(second)
    _log_sent(log, second, status2)
    _append({
        "event": "sent",
        "bet_key": key,
        "venue": second["venue"],
        "instrument": second["instrument"],
        "side": second["outcome"],
        "limit_price": second["limit"],
        "size": "1",
        "http_status": status2,
        "note": note2,
        "order_id": _order_id(payload2),
    })
    filled2 = filled_contracts(payload2) if status2 in (200, 201) else Decimal("0")
    if status2 in (200, 201) and order_still_open(payload2) and filled2 < SIZE:
        cancel_status, cancel_note = _cancel(second, payload2)
        log(f"order cancel venue={second['venue']} instrument={second['instrument']} http={cancel_status} {cancel_note}")
        filled2 = Decimal("0")
    if filled2 >= SIZE:
        _append({"event": "filled", "bet_key": key, "venue": second["venue"], "instrument": second["instrument"], "side": second["outcome"], "size": "1", "price": second["pay"]})
        log(f"order both legs filled {title}")
        return
    _log_one_leg(log, first)
    _append({
        "event": "one_leg",
        "bet_key": key,
        "venue": first["venue"],
        "instrument": first["instrument"],
        "side": first["outcome"],
        "size": "1",
        "price": first["pay"],
        "second_venue": second["venue"],
        "second_http": status2,
        "note": note2,
    })
    alert_one_leg(log, title, first, first_payload, second, status2, note2, payload2)


def _pid_alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x1000, False, int(pid))
        if not handle:
            return False
        kernel.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def smoke() -> dict:
    """Balance reads and Gemini terms. Does not place an order."""
    report = {}
    try:
        status, usd = kalshi_private.balance_usd()
        report["kalshi_http"] = status
        report["kalshi_usd"] = usd
    except Exception as exc:
        report["kalshi_http"] = type(exc).__name__
    try:
        status, body = gemini_private.private_call("/v1/balances", None, "POST")
        report["gemini_balance_http"] = status
        if status == 200:
            data = json.loads(body)
            usd = None
            if isinstance(data, list):
                for row in data:
                    if isinstance(row, dict) and str(row.get("currency") or "").upper() == "USD":
                        usd = row.get("available")
            report["gemini_usd"] = usd
        else:
            report["gemini_balance_note"] = _public_note(body)
    except Exception as exc:
        report["gemini_balance_http"] = type(exc).__name__
    try:
        status, body = gemini_private.private_call("/v1/prediction-markets/terms/status", None, "GET")
        if status != 200:
            status, body = gemini_private.private_call("/v1/prediction-markets/terms/status", None, "POST")
        report["gemini_terms_http"] = status
        if status == 200:
            data = json.loads(body)
            report["gemini_terms_accepted"] = bool(data.get("hasAcceptedLatest"))
        else:
            report["gemini_terms_note"] = _public_note(body)
    except Exception as exc:
        report["gemini_terms_http"] = type(exc).__name__
    try:
        status, body = polymarket_us_live.signed_json("GET", "/v1/account/balances")
        report["polymarket_http"] = status
        if status == 200:
            data = json.loads(body)
            power = None
            for row in data.get("balances") or []:
                if isinstance(row, dict):
                    power = row.get("buyingPower")
            report["polymarket_buying_power"] = power
        else:
            report["polymarket_note"] = _public_note(body)
    except Exception as exc:
        report["polymarket_http"] = type(exc).__name__
    report["orders_sent"] = 0
    return report


if __name__ == "__main__":
    import sys
    if "--smoke" in sys.argv:
        print(json.dumps(smoke(), default=str))
    else:
        print("Pass --smoke to read balances. This command does not place an order.")
