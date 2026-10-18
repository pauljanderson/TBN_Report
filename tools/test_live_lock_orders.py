"""Rules for the one-contract lock orders. No network. No secrets."""
from decimal import Decimal, ROUND_CEILING

import gemini_private
import kalshi_private
import live_lock_orders


class Scan:
    def gemini_fee(self, price: Decimal) -> Decimal:
        raw = Decimal("0.07") * price * (Decimal("1") - price)
        if raw < 0:
            raw = Decimal("0")
        return raw.quantize(Decimal("0.01"), rounding=ROUND_CEILING)

    def gemini_no_rejection(self, cand: dict):
        if cand.get("no_flipped_yes_bid"):
            return "flipped Yes bid"
        return None

    def _trade_bet_key(self, sport, game, cand):
        return "bet"


def _pair(**extra):
    row = {
        "market_type": "spread",
        "side": "Tennessee",
        "number": "3.5",
        "yes_venue": "kalshi",
        "no_venue": "gemini",
        "yes_price": "0.40",
        "no_price": "0.53",
        "yes_size": "2",
        "no_size": "2",
        "kalshi_ticker": "KX-TEST",
        "gemini_symbol": "GEMI-TEST",
        "no_flipped_yes_bid": False,
    }
    row.update(extra)
    return row


def test_net_at_095_qualifies():
    ok, reason = live_lock_orders.qualifies(Scan(), _pair(), "Some Game", {})
    assert ok, reason
    assert "0.95" in reason


def test_net_above_095_stays_alert_only():
    ok, reason = live_lock_orders.qualifies(Scan(), _pair(no_price="0.54"), "Some Game", {})
    assert not ok
    assert "above 0.95" in reason


def test_size_cap_needs_one_whole_contract():
    ok, _reason = live_lock_orders.qualifies(Scan(), _pair(yes_size="0.5"), "Some Game", {})
    assert not ok


def test_tennessee_13_5_is_blocked():
    cand = _pair(number="13.5", side="Tennessee", market_type="spread")
    ok, reason = live_lock_orders.qualifies(Scan(), cand, "Tennessee vs Indianapolis", {"title_kalshi": "Tennessee vs Indianapolis"})
    assert not ok
    assert "Tennessee" in reason


def test_flipped_gemini_no_is_blocked():
    ok, _reason = live_lock_orders.qualifies(Scan(), _pair(no_flipped_yes_bid=True), "Some Game", {})
    assert not ok


def test_missing_moves_send_kalshi_first():
    order = live_lock_orders.ordered_outcomes(_pair(), [])
    assert order == ["yes", "no"]
    fresh = [
        {"venue": "Gemini", "pay": "no", "market_type": "spread", "number": "3.5", "move": "0.20"},
        {"venue": "Kalshi", "pay": "yes", "market_type": "spread", "number": "3.5", "move": "-0.04"},
    ]
    assert live_lock_orders.ordered_outcomes(_pair(), fresh) == ["no", "yes"]


def test_kalshi_no_is_a_yes_ask_at_one_minus_price():
    body = live_lock_orders.kalshi_order_body("KX-TEST", "no", Decimal("0.40"), "cid")
    assert body["side"] == "ask"
    assert body["price"] == "0.6000"
    assert body["count"] == "1.00"
    assert body["time_in_force"] == "immediate_or_cancel"
    yes = live_lock_orders.kalshi_order_body("KX-TEST", "yes", Decimal("0.40"), "cid")
    assert yes["side"] == "bid"
    assert yes["price"] == "0.4000"


def test_polymarket_short_price_does_not_pay_more():
    price = live_lock_orders.polymarket_api_price("ORDER_INTENT_BUY_SHORT", Decimal("0.830"))
    assert price == Decimal("0.170")
    long_price = live_lock_orders.polymarket_api_price("ORDER_INTENT_BUY_LONG", Decimal("0.8314"))
    assert long_price == Decimal("0.831")


def test_filled_and_blocked():
    assert live_lock_orders.filled_contracts({"fill_count": "1.00", "remaining_count": "0.00"}) == Decimal("1.00")
    assert live_lock_orders.filled_contracts({"status": "cancelled"}) == Decimal("0")
    rows = [
        {"bet_key": "a", "event": "claim", "pid": 1},
        {"bet_key": "a", "event": "sent"},
        {"bet_key": "a", "event": "filled"},
        {"bet_key": "a", "event": "one_leg"},
    ]
    assert live_lock_orders.bet_blocked(rows, "a", lambda _pid: False)
    clear = [{"bet_key": "a", "event": "claim", "pid": 9}, {"bet_key": "a", "event": "sent"}, {"bet_key": "a", "event": "both_unfilled"}]
    assert not live_lock_orders.bet_blocked(clear, "a", lambda _pid: True)


def test_one_leg_message_is_separate_from_the_under_1_ping():
    first = {"venue": "kalshi", "outcome": "yes", "instrument": "KX-TEST", "pay": "0.36"}
    second = {"venue": "gemini", "outcome": "no", "instrument": "GEMI-TEST", "pay": "0.34"}
    text = live_lock_orders.one_leg_message("Carolina vs Philadelphia", first, {"yes_price_dollars": "0.1100", "order_id": "abc"}, second, 201, "no message", {"order_id": "999"})
    assert text.startswith("one leg filled, other leg did not.")
    assert "Pair under $1" not in text
    assert "fill 0.1100" in text
    assert "No repair order was sent." in text


def test_send_returns_before_order_http_when_off():
    assert live_lock_orders.ORDERS_ENABLED is False
    calls = []

    def boom(*_args, **_kwargs):
        calls.append("http")
        raise AssertionError("order http was called")

    saved = (
        kalshi_private.signed_call,
        gemini_private.private_call,
        live_lock_orders.polymarket_us_live.signed_json,
    )
    kalshi_private.signed_call = boom
    gemini_private.private_call = boom
    live_lock_orders.polymarket_us_live.signed_json = boom
    try:
        for venue in ("kalshi", "gemini", "polymarket"):
            status, payload, note = live_lock_orders._send({"venue": venue, "body": {}})
            assert status == 0 and payload is None
            assert note == "placing orders is off"
        preview_ok, preview_note = live_lock_orders._preview({"venue": "polymarket", "body": {}})
        assert preview_ok is False
        assert preview_note == "placing orders is off"
    finally:
        kalshi_private.signed_call = saved[0]
        gemini_private.private_call = saved[1]
        live_lock_orders.polymarket_us_live.signed_json = saved[2]
    assert calls == []


def test_spot_order_path_is_refused():
    try:
        gemini_private.private_call("/v1/order/new", {"symbol": "btcusd"}, "POST")
    except ValueError:
        return
    raise AssertionError("spot order path should be refused")


if __name__ == "__main__":
    test_net_at_095_qualifies()
    test_net_above_095_stays_alert_only()
    test_size_cap_needs_one_whole_contract()
    test_tennessee_13_5_is_blocked()
    test_flipped_gemini_no_is_blocked()
    test_missing_moves_send_kalshi_first()
    test_kalshi_no_is_a_yes_ask_at_one_minus_price()
    test_polymarket_short_price_does_not_pay_more()
    test_filled_and_blocked()
    test_one_leg_message_is_separate_from_the_under_1_ping()
    test_send_returns_before_order_http_when_off()
    test_spot_order_path_is_refused()
    print("ok")
