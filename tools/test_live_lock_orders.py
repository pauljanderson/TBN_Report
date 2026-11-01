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
    gtc = live_lock_orders.kalshi_order_body("KX-TEST", "yes", Decimal("0.40"), "cid", tif="gtc")
    assert gtc["time_in_force"] == "good_till_canceled"
    assert live_lock_orders.gemini_order_payload("GEMI", "yes", Decimal("0.40"), tif="gtc")["timeInForce"] == "good-till-cancel"
    poly = live_lock_orders.polymarket_order_body("slug", "ORDER_INTENT_BUY_LONG", Decimal("0.40"), tif="gtc")
    assert poly["tif"] == "TIME_IN_FORCE_GOOD_TILL_CANCEL"
    assert poly["synchronousExecution"] is False
    poly_ioc = live_lock_orders.polymarket_order_body("slug", "ORDER_INTENT_BUY_LONG", Decimal("0.40"), tif="ioc")
    assert poly_ioc["synchronousExecution"] is True


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
    text = live_lock_orders.one_leg_message(
        "Carolina vs Philadelphia",
        first,
        {"yes_price_dollars": "0.1100", "order_id": "abc"},
        second,
        201,
        "no message",
        {"order_id": "999"},
        gtc_resting=True,
    )
    assert text.startswith("one leg filled, other leg did not.")
    assert "Pair under $1" not in text
    assert "fill 0.1100" in text
    assert "Second leg GTC resting" in text
    assert "No repair order was sent." not in text


def test_one_leg_deadline_actions():
    cheap = live_lock_orders.one_leg_deadline_action(
        held_pay=Decimal("0.20"), gtc_filled=False, waited_sec=180
    )
    assert cheap == "exit_cheap"
    waiting = live_lock_orders.one_leg_deadline_action(
        held_pay=Decimal("0.40"), gtc_filled=False, waited_sec=60
    )
    assert waiting == "keep_waiting"
    filled = live_lock_orders.one_leg_deadline_action(
        held_pay=Decimal("0.40"), gtc_filled=True, waited_sec=10
    )
    assert filled == "done_gtc_filled"
    hold = live_lock_orders.one_leg_deadline_action(
        held_pay=Decimal("0.40"),
        gtc_filled=False,
        waited_sec=180,
        be_complete_available=False,
    )
    assert hold == "hold_to_settle"
    complete = live_lock_orders.one_leg_deadline_action(
        held_pay=Decimal("0.40"),
        gtc_filled=False,
        waited_sec=180,
        be_complete_available=True,
    )
    assert complete == "try_be_complete"


def test_choose_cheap_exit_prefers_tighter_loss():
    # flatten all-in 0.80 on a 0.20 hold → round-trip 1.00 → 0 loss; sell proceeds 0.05 → 0.15 loss
    assert (
        live_lock_orders.choose_cheap_exit(
            flatten_all_in=Decimal("0.80"),
            market_sell_proceeds=Decimal("0.05"),
            held_pay=Decimal("0.20"),
        )
        == "flatten"
    )
    assert (
        live_lock_orders.choose_cheap_exit(
            flatten_all_in=Decimal("0.95"),
            market_sell_proceeds=Decimal("0.18"),
            held_pay=Decimal("0.20"),
        )
        == "market_sell"
    )


def test_break_even_miss_pay_above_intended_l():
    # Filled 0.40 + ~1.7¢ fee → BE miss near 0.58, above a 0.53 L with edge
    be = live_lock_orders.break_even_miss_pay(Decimal("0.40"))
    assert be > Decimal("0.50")
    assert be < Decimal("0.60")


def test_send_returns_before_order_http_when_off():
    assert live_lock_orders.ORDERS_ENABLED is False
    assert live_lock_orders.orders_enabled() is False
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
        cancel_status, cancel_note = live_lock_orders._cancel(
            {"venue": "kalshi", "instrument": "KX"}, {"order_id": "abc"}
        )
        assert cancel_status == 0 and cancel_note == "placing orders is off"
    finally:
        kalshi_private.signed_call = saved[0]
        gemini_private.private_call = saved[1]
        live_lock_orders.polymarket_us_live.signed_json = saved[2]
    assert calls == []


def test_orders_enabled_env_and_stamp(tmp_path, monkeypatch=None):
    """Env LOCK_ORDERS_ENABLED and stamp files gate orders without flipping the module default."""
    import os

    saved_flag = live_lock_orders.ORDERS_ENABLED
    saved_on = live_lock_orders.ORDERS_ENABLED_STAMP_ON
    saved_off = live_lock_orders.ORDERS_ENABLED_STAMP_OFF
    saved_env = os.environ.get("LOCK_ORDERS_ENABLED")
    on = tmp_path / "orders_enabled.on"
    off = tmp_path / "orders_enabled.off"
    live_lock_orders.ORDERS_ENABLED = False
    live_lock_orders.ORDERS_ENABLED_STAMP_ON = on
    live_lock_orders.ORDERS_ENABLED_STAMP_OFF = off
    try:
        os.environ.pop("LOCK_ORDERS_ENABLED", None)
        assert live_lock_orders.orders_enabled() is False
        on.write_text("on", encoding="utf-8")
        assert live_lock_orders.orders_enabled() is True
        off.write_text("off", encoding="utf-8")
        assert live_lock_orders.orders_enabled() is False
        off.unlink()
        os.environ["LOCK_ORDERS_ENABLED"] = "0"
        assert live_lock_orders.orders_enabled() is False
        os.environ["LOCK_ORDERS_ENABLED"] = "1"
        # off stamp already gone; env on wins even without .on? .on still exists
        assert live_lock_orders.orders_enabled() is True
        on.unlink()
        os.environ["LOCK_ORDERS_ENABLED"] = "false"
        assert live_lock_orders.orders_enabled() is False
        live_lock_orders.ORDERS_ENABLED = True
        os.environ.pop("LOCK_ORDERS_ENABLED", None)
        assert live_lock_orders.orders_enabled() is True
    finally:
        live_lock_orders.ORDERS_ENABLED = saved_flag
        live_lock_orders.ORDERS_ENABLED_STAMP_ON = saved_on
        live_lock_orders.ORDERS_ENABLED_STAMP_OFF = saved_off
        if saved_env is None:
            os.environ.pop("LOCK_ORDERS_ENABLED", None)
        else:
            os.environ["LOCK_ORDERS_ENABLED"] = saved_env


def test_exit_specs_build_for_kalshi_and_gemini():
    flat = live_lock_orders.build_flatten_spec(
        venue="kalshi", instrument="KX", held_side="yes", opposite_pay=Decimal("0.80")
    )
    assert flat is not None
    assert flat["outcome"] == "no"
    assert flat["body"]["side"] == "ask"
    sell = live_lock_orders.build_market_sell_spec(venue="kalshi", instrument="KX", held_side="yes")
    assert sell is not None
    assert sell["body"]["side"] == "ask"
    assert sell["body"]["price"] == "0.0100"
    gsell = live_lock_orders.build_market_sell_spec(venue="gemini", instrument="GEMI", held_side="no")
    assert gsell is not None
    assert gsell["body"]["side"] == "sell"
    assert gsell["body"]["outcome"] == "no"


def test_tick_sends_cheap_exit_when_orders_on(tmp_path):
    import os

    saved_flag = live_lock_orders.ORDERS_ENABLED
    saved_watch = live_lock_orders.ONE_LEG_WATCH
    saved_orders = live_lock_orders.ORDERS
    saved_lock = live_lock_orders.ORDER_LOCK
    saved_on = live_lock_orders.ORDERS_ENABLED_STAMP_ON
    saved_off = live_lock_orders.ORDERS_ENABLED_STAMP_OFF
    saved_env = os.environ.get("LOCK_ORDERS_ENABLED")
    live_lock_orders.ONE_LEG_WATCH = tmp_path / "watch.jsonl"
    live_lock_orders.ORDERS = tmp_path / "orders.jsonl"
    live_lock_orders.ORDER_LOCK = tmp_path / "orders.lock"
    live_lock_orders.ORDERS_ENABLED_STAMP_ON = tmp_path / "missing.on"
    live_lock_orders.ORDERS_ENABLED_STAMP_OFF = tmp_path / "missing.off"
    live_lock_orders.ORDERS_ENABLED = True
    os.environ.pop("LOCK_ORDERS_ENABLED", None)
    sends = []
    cancels = []

    def fake_send(spec):
        sends.append(spec)
        return 200, {"status": "filled", "fill_count": "1.00", "order_id": "exit1"}, "ok"

    def fake_cancel(spec, payload):
        cancels.append((spec, payload))
        return 200, "cancelled"

    real_send = live_lock_orders._send
    real_cancel = live_lock_orders._cancel
    live_lock_orders._send = fake_send
    live_lock_orders._cancel = fake_cancel
    logs = []
    try:
        live_lock_orders._append_watch({
            "event": "second_leg_gtc_open",
            "bet_key": "b1",
            "held_venue": "kalshi",
            "held_instrument": "KX",
            "held_side": "yes",
            "held_pay": "0.20",
            "second_venue": "gemini",
            "second_instrument": "GEMI",
            "second_side": "no",
            "second_order_id": "gtc99",
            "miss_limit_l": "0.50",
            "break_even_pay": "0.78",
            "opened_at": 0.0,
        })
        actions = live_lock_orders.tick_one_leg_gtc_watches(logs.append, now=200.0)
        assert any(a.startswith("b1:exit_cheap:") for a in actions)
        assert cancels, "deadline must cancel resting GTC"
        assert sends, "cheap exit must send when orders on"
        assert sends[0]["exit"] == "market_sell" or sends[0]["outcome"] in ("yes", "no")
    finally:
        live_lock_orders._send = real_send
        live_lock_orders._cancel = real_cancel
        live_lock_orders.ORDERS_ENABLED = saved_flag
        live_lock_orders.ONE_LEG_WATCH = saved_watch
        live_lock_orders.ORDERS = saved_orders
        live_lock_orders.ORDER_LOCK = saved_lock
        live_lock_orders.ORDERS_ENABLED_STAMP_ON = saved_on
        live_lock_orders.ORDERS_ENABLED_STAMP_OFF = saved_off
        if saved_env is None:
            os.environ.pop("LOCK_ORDERS_ENABLED", None)
        else:
            os.environ["LOCK_ORDERS_ENABLED"] = saved_env


def test_spot_order_path_is_refused():
    try:
        gemini_private.private_call("/v1/order/new", {"symbol": "btcusd"}, "POST")
    except ValueError:
        return
    raise AssertionError("spot order path should be refused")


if __name__ == "__main__":
    from pathlib import Path
    import tempfile

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
    test_one_leg_deadline_actions()
    test_choose_cheap_exit_prefers_tighter_loss()
    test_break_even_miss_pay_above_intended_l()
    test_send_returns_before_order_http_when_off()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        stamps = root / "stamps"
        stamps.mkdir()
        test_orders_enabled_env_and_stamp(stamps)
        tick_dir = root / "tick"
        tick_dir.mkdir()
        test_tick_sends_cheap_exit_when_orders_on(tick_dir)
    test_exit_specs_build_for_kalshi_and_gemini()
    test_spot_order_path_is_refused()
    print("ok")
