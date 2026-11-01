"""Venue-confirm after order HTTP. Mock only. No live secrets. No orders."""
from __future__ import annotations

import json
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import kalshi_private  # noqa: E402
import live_lock_orders  # noqa: E402
import novig_live  # noqa: E402
import polymarket_us_live  # noqa: E402
import venue_fill_confirm  # noqa: E402

live_lock_orders._MARKET_SIZE_FETCH_ENABLED = False


def _kalshi_order(fill_count="0.00", order_id="oid-1"):
    return {
        "status": "cancelled" if str(fill_count).startswith("0") else "executed",
        "fill_count": fill_count,
        "remaining_count": "0.00",
        "order_id": order_id,
    }


def test_kalshi_201_fill_count_0_and_empty_fills_is_not_a_fill():
    tape = _kalshi_order("0.00")
    with patch.object(kalshi_private, "get_fills", return_value=(200, json.dumps({"fills": [], "cursor": ""}))):
        confirm = venue_fill_confirm.confirm_order(
            "kalshi", tape, {"venue": "kalshi", "instrument": "KX-TEST", "outcome": "no"},
            tries=1, sleep_sec=0,
        )
    assert confirm["known"] is True
    assert Decimal(confirm["qty"]) == Decimal("0")
    assert confirm["house_fill"] is False
    payload = venue_fill_confirm.attach(tape, confirm)
    assert live_lock_orders.filled_contracts(payload) == Decimal("0")
    assert live_lock_orders.leg_filled_at_least_one({"payload": payload, "status": 201, "filled": True}) is False


def test_kalshi_fills_get_qty_1_is_a_fill_even_if_tape_said_zero():
    tape = _kalshi_order("0.00")
    fills = {
        "fills": [{
            "order_id": "oid-1",
            "ticker": "KX-TEST",
            "count_fp": "1.00",
            "yes_price_dollars": "0.4700",
            "no_price_dollars": "0.5300",
            "outcome_side": "no",
        }],
        "cursor": "",
    }
    with patch.object(kalshi_private, "get_fills", return_value=(200, json.dumps(fills))):
        confirm = venue_fill_confirm.confirm_order(
            "kalshi", tape, {"venue": "kalshi", "instrument": "KX-TEST", "outcome": "no"},
            tries=1, sleep_sec=0,
        )
    assert confirm["known"] is True
    assert Decimal(confirm["qty"]) == Decimal("1.00")
    assert confirm["house_fill"] is True
    assert confirm["mismatch"] is True
    assert confirm["avg_price"] == "0.5300"
    payload = venue_fill_confirm.attach(tape, confirm)
    assert live_lock_orders.filled_contracts(payload) == Decimal("1.00")
    assert live_lock_orders.leg_filled_at_least_one({"payload": payload, "status": 201}) is True


def test_confirm_timeout_does_not_invent_a_fill():
    tape = _kalshi_order("1.00")
    with patch.object(kalshi_private, "get_fills", side_effect=TimeoutError("timed out")):
        confirm = venue_fill_confirm.confirm_order(
            "kalshi", tape, {"venue": "kalshi", "instrument": "KX-TEST", "outcome": "yes"},
            tries=2, sleep_sec=0, timeout=0.01,
        )
    assert confirm["known"] is False
    assert Decimal(confirm["qty"]) == Decimal("0")
    payload = venue_fill_confirm.attach(tape, confirm)
    assert live_lock_orders.filled_contracts(tape) == Decimal("1.00")
    assert live_lock_orders.filled_contracts(payload) == Decimal("0")
    assert live_lock_orders.leg_filled_at_least_one({"payload": payload, "status": 201, "filled": True}) is False


def test_house_fill_uses_this_order_qty():
    spec = {"venue": "polymarket", "body": {"quantity": 1}, "instrument": "aec-test"}
    assert venue_fill_confirm.house_size_of(spec) == Decimal("1")
    partial = venue_fill_confirm._known_result(
        "polymarket", Decimal("0.19"), Decimal("0.48"), "partial", 200, Decimal("0.19"),
        {"order_id": "x"}, house_size=Decimal("1"),
    )
    assert partial["house_fill"] is False
    full = venue_fill_confirm._known_result(
        "polymarket", Decimal("1"), Decimal("0.48"), "fok", 200, Decimal("1"),
        {"order_id": "y"}, house_size=Decimal("1"),
    )
    assert full["house_fill"] is True


def test_poly_partial_qty_below_1_is_not_house_fill():
    tape = {"id": "oid-partial", "cumQuantity": "0.40", "state": "FILLED"}
    activities = {
        "activities": [{
            "type": "ACTIVITY_TYPE_TRADE",
            "trade": {
                "id": "t1",
                "marketSlug": "aec-test",
                "qtyDecimal": "0.40",
                "qty": "0",
                "price": {"value": "0.41", "currency": "USD"},
                "isAggressor": True,
                "aggressor": {"id": "oid-partial"},
            },
        }],
        "eof": True,
    }
    with patch.object(polymarket_us_live, "get_activities", return_value=(200, json.dumps(activities))):
        confirm = venue_fill_confirm.confirm_order(
            "polymarket", tape,
            {"venue": "polymarket", "instrument": "aec-test", "outcome": "yes"},
            tries=1, sleep_sec=0,
        )
    assert confirm["known"] is True
    assert Decimal(confirm["qty"]) == Decimal("0.40")
    assert confirm["house_fill"] is False
    assert "not house fill" in confirm["note"]
    payload = venue_fill_confirm.attach(tape, confirm)
    assert live_lock_orders.filled_contracts(payload) == Decimal("0.40")
    assert live_lock_orders.leg_filled_at_least_one({"payload": payload, "status": 200}) is False


def _mute_send_side_effects(folder: Path):
    live_lock_orders.ORDER_IO = folder / "order_io.jsonl"
    live_lock_orders.ORDERS = folder / "orders.jsonl"
    live_lock_orders.ONE_LEG_WATCH = folder / "one_leg_watch.json"
    live_lock_orders.ORDERS_ENABLED = True
    live_lock_orders.ORDERS_STOP = folder / "orders_stopped.json"
    live_lock_orders._phone_order_placed = lambda _spec: None
    live_lock_orders._refresh_order_pages = lambda: None


def test_send_uses_empty_fills_get_not_tape():
    folder = Path(tempfile.mkdtemp())
    saved = (
        live_lock_orders.ORDER_IO,
        live_lock_orders.ORDERS,
        live_lock_orders.ONE_LEG_WATCH,
        live_lock_orders.ORDERS_ENABLED,
        live_lock_orders.ORDERS_STOP,
        live_lock_orders._phone_order_placed,
        live_lock_orders._refresh_order_pages,
        kalshi_private.signed_call,
    )
    _mute_send_side_effects(folder)
    order_body = json.dumps(_kalshi_order("0.00", "oid-empty"))

    def fake_signed(method, path, body=None, query=None, timeout=30):
        if "portfolio/fills" in str(path):
            return 200, json.dumps({"fills": [], "cursor": ""})
        return 201, order_body

    kalshi_private.signed_call = fake_signed
    spec = {
        "venue": "kalshi",
        "instrument": "KX-TEST",
        "outcome": "no",
        "limit": "0.53",
        "body": {"ticker": "KX-TEST"},
        "_attempt": 1,
        "_bet_key": "k",
        "_step": "simultaneous",
    }
    try:
        status, payload, _note = live_lock_orders._send(spec)
        outcome = {
            "posted": True,
            "status": status,
            "payload": payload,
            "spec": spec,
            "step": "simultaneous",
            "note": "cancelled",
            "fill_qty": "0",
            "filled": False,
        }
    finally:
        live_lock_orders.ORDER_IO = saved[0]
        live_lock_orders.ORDERS = saved[1]
        live_lock_orders.ONE_LEG_WATCH = saved[2]
        live_lock_orders.ORDERS_ENABLED = saved[3]
        live_lock_orders.ORDERS_STOP = saved[4]
        live_lock_orders._phone_order_placed = saved[5]
        live_lock_orders._refresh_order_pages = saved[6]
        kalshi_private.signed_call = saved[7]
    assert status == 201
    assert live_lock_orders.filled_contracts(payload) == Decimal("0")
    assert outcome["filled"] is False
    line = live_lock_orders.format_posted_leg_return(outcome)
    assert "HTTP 201" in line
    assert "confirm" in line
    assert "fills GET empty" in line


def test_send_uses_fills_get_qty_1_when_tape_is_empty():
    folder = Path(tempfile.mkdtemp())
    saved = (
        live_lock_orders.ORDER_IO,
        live_lock_orders.ORDERS,
        live_lock_orders.ONE_LEG_WATCH,
        live_lock_orders.ORDERS_ENABLED,
        live_lock_orders.ORDERS_STOP,
        live_lock_orders._phone_order_placed,
        live_lock_orders._refresh_order_pages,
        kalshi_private.signed_call,
    )
    _mute_send_side_effects(folder)
    order_body = json.dumps(_kalshi_order("0.00", "oid-real"))
    fills = json.dumps({
        "fills": [{
            "order_id": "oid-real",
            "ticker": "KX-TEST",
            "count_fp": "1.00",
            "yes_price_dollars": "0.4700",
            "no_price_dollars": "0.5300",
            "outcome_side": "no",
        }],
        "cursor": "",
    })

    def fake_signed(method, path, body=None, query=None, timeout=30):
        if "portfolio/fills" in str(path):
            return 200, fills
        return 201, order_body

    kalshi_private.signed_call = fake_signed
    spec = {
        "venue": "kalshi",
        "instrument": "KX-TEST",
        "outcome": "no",
        "limit": "0.53",
        "body": {"ticker": "KX-TEST"},
        "_attempt": 1,
        "_bet_key": "k",
        "_step": "simultaneous",
    }
    try:
        status, payload, _note = live_lock_orders._send(spec)
    finally:
        live_lock_orders.ORDER_IO = saved[0]
        live_lock_orders.ORDERS = saved[1]
        live_lock_orders.ONE_LEG_WATCH = saved[2]
        live_lock_orders.ORDERS_ENABLED = saved[3]
        live_lock_orders.ORDERS_STOP = saved[4]
        live_lock_orders._phone_order_placed = saved[5]
        live_lock_orders._refresh_order_pages = saved[6]
        kalshi_private.signed_call = saved[7]
    assert status == 201
    assert live_lock_orders.filled_contracts(payload) == Decimal("1.00")
    confirm = live_lock_orders.venue_confirm_of(payload)
    assert confirm and confirm.get("mismatch") is True
    line = live_lock_orders.format_posted_leg_return({
        "posted": True,
        "status": 201,
        "payload": payload,
        "spec": spec,
        "step": "simultaneous",
        "note": "cancelled",
        "fill_qty": "1.00",
    })
    assert "HTTP 201 fill 0" in line
    assert "using confirm qty 1" in line


def test_send_timeout_confirm_does_not_claim_tape_fill():
    folder = Path(tempfile.mkdtemp())
    saved = (
        live_lock_orders.ORDER_IO,
        live_lock_orders.ORDERS,
        live_lock_orders.ONE_LEG_WATCH,
        live_lock_orders.ORDERS_ENABLED,
        live_lock_orders.ORDERS_STOP,
        live_lock_orders._phone_order_placed,
        live_lock_orders._refresh_order_pages,
        live_lock_orders.confirm_venue_after_order,
        kalshi_private.signed_call,
    )
    _mute_send_side_effects(folder)
    order_body = json.dumps(_kalshi_order("1.00", "oid-maybe"))
    kalshi_private.signed_call = lambda *_a, **_k: (201, order_body)
    live_lock_orders.confirm_venue_after_order = lambda spec, status, payload: venue_fill_confirm.unknown_result(
        "kalshi", "confirm timeout; unknown", Decimal("1.00"),
        {"order_id": "oid-maybe", "ticker": "KX-TEST"},
    )
    spec = {
        "venue": "kalshi",
        "instrument": "KX-TEST",
        "outcome": "yes",
        "limit": "0.40",
        "body": {"ticker": "KX-TEST"},
        "_attempt": 1,
        "_bet_key": "k",
        "_step": "simultaneous",
    }
    try:
        status, payload, _note = live_lock_orders._send(spec)
    finally:
        live_lock_orders.ORDER_IO = saved[0]
        live_lock_orders.ORDERS = saved[1]
        live_lock_orders.ONE_LEG_WATCH = saved[2]
        live_lock_orders.ORDERS_ENABLED = saved[3]
        live_lock_orders.ORDERS_STOP = saved[4]
        live_lock_orders._phone_order_placed = saved[5]
        live_lock_orders._refresh_order_pages = saved[6]
        live_lock_orders.confirm_venue_after_order = saved[7]
        kalshi_private.signed_call = saved[8]
    assert status == 201
    assert live_lock_orders.filled_contracts(payload) == Decimal("0")
    assert live_lock_orders.venue_confirm_known(payload) is False


def test_poly_confirm_filters_to_our_aggressor_order():
    """Trungelliti/Dodig: LONG + SHORT on the same slug must not confirm qty 2 on the SHORT."""
    tape = {"id": "D93BDNCG11TB", "cumQuantity": "1", "state": "FILLED"}
    activities = {
        "activities": [
            {
                "type": "ACTIVITY_TYPE_TRADE",
                "trade": {
                    "id": "D93BC89G11KR",
                    "marketSlug": "aec-atp-martru-matdod-2026-10-23",
                    "qtyDecimal": "1.0000",
                    "price": {"value": "0.4100"},
                    "isAggressor": True,
                    "aggressor": {"id": "D93BC89011N2", "intent": "ORDER_INTENT_BUY_LONG"},
                },
            },
            {
                "type": "ACTIVITY_TYPE_TRADE",
                "trade": {
                    "id": "D93BDND051KP",
                    "marketSlug": "aec-atp-martru-matdod-2026-10-23",
                    "qtyDecimal": "1.0000",
                    "price": {"value": "0.3900"},
                    "isAggressor": True,
                    "aggressor": {"id": "D93BDNCG11TB", "intent": "ORDER_INTENT_BUY_SHORT"},
                },
            },
        ],
        "eof": True,
    }
    with patch.object(polymarket_us_live, "get_activities", return_value=(200, json.dumps(activities))):
        confirm = venue_fill_confirm.confirm_order(
            "polymarket",
            tape,
            {
                "venue": "polymarket",
                "instrument": "aec-atp-martru-matdod-2026-10-23",
                "outcome": "yes",
                "intent": "ORDER_INTENT_BUY_SHORT",
            },
            tries=1,
            sleep_sec=0,
        )
    assert confirm["known"] is True
    assert Decimal(confirm["qty"]) == Decimal("1.0000")
    assert confirm["avg_price"] == "0.3900"
    assert confirm["house_fill"] is True


def test_poly_confirm_without_order_id_does_not_sum_slug():
    activities = {
        "activities": [
            {
                "type": "ACTIVITY_TYPE_TRADE",
                "trade": {
                    "id": "D93BC89G11KR",
                    "marketSlug": "aec-atp-martru-matdod-2026-10-23",
                    "qtyDecimal": "1.0000",
                    "price": {"value": "0.4100"},
                    "isAggressor": True,
                    "aggressor": {"id": "D93BC89011N2"},
                },
            },
            {
                "type": "ACTIVITY_TYPE_TRADE",
                "trade": {
                    "id": "D93BDND051KP",
                    "marketSlug": "aec-atp-martru-matdod-2026-10-23",
                    "qtyDecimal": "1.0000",
                    "price": {"value": "0.3900"},
                    "isAggressor": True,
                    "aggressor": {"id": "D93BDNCG11TB"},
                },
            },
        ]
    }
    with patch.object(polymarket_us_live, "get_activities", return_value=(200, json.dumps(activities))):
        confirm = venue_fill_confirm.confirm_order(
            "polymarket",
            {},
            {
                "venue": "polymarket",
                "instrument": "aec-atp-martru-matdod-2026-10-23",
                "outcome": "yes",
                "intent": "ORDER_INTENT_BUY_SHORT",
            },
            tries=1,
            sleep_sec=0,
        )
    assert Decimal(confirm["qty"]) == Decimal("0")
    assert confirm.get("house_fill") is False


def test_poly_nanosecond_create_time_parses():
    stamp = venue_fill_confirm._parse_dt("2026-10-23T09:03:55.475059250Z")
    assert stamp is not None
    assert stamp.year == 2026
    assert stamp.month == 10
    assert stamp.day == 23
    assert stamp.hour == 9


def test_documented_endpoints_only():
    assert venue_fill_confirm.ENDPOINTS["kalshi"] == "GET /trade-api/v2/portfolio/fills"
    assert venue_fill_confirm.ENDPOINTS["gemini"] == "POST /v1/prediction-markets/orders/history"
    assert venue_fill_confirm.ENDPOINTS["polymarket"] == "GET /v1/portfolio/activities"
    assert venue_fill_confirm.ENDPOINTS["novig"] == "GET /v3/portfolio/fills"


def _guajardo_leftover_tape():
    """Alexander Guajardo leftover-yes 24 Oct 2026: HTTP cumQuantity 0.19, then EXPIRED."""
    return {
        "id": "D9ZCT3CG11KJ",
        "marketSlug": "aec-utr-guaale-bralac-2026-10-24",
        "executions": [
            {
                "id": "D9ZCT3CGF1KP",
                "order": {
                    "id": "D9ZCT3CG11KJ",
                    "marketSlug": "aec-utr-guaale-bralac-2026-10-24",
                    "cumQuantity": 0,
                    "leavesQuantity": 1,
                    "state": "ORDER_STATE_NEW",
                    "avgPx": {"value": "0.0000"},
                },
            },
            {
                "id": "D9ZCT3CGF1KR",
                "order": {
                    "id": "D9ZCT3CG11KJ",
                    "marketSlug": "aec-utr-guaale-bralac-2026-10-24",
                    "cumQuantity": 0.01,
                    "leavesQuantity": 0.99,
                    "state": "ORDER_STATE_PARTIALLY_FILLED",
                    "avgPx": {"value": "0.4700"},
                },
            },
            {
                "id": "D9ZCT3CGH1KQ",
                "order": {
                    "id": "D9ZCT3CG11KJ",
                    "marketSlug": "aec-utr-guaale-bralac-2026-10-24",
                    "cumQuantity": 0.19,
                    "leavesQuantity": 0.81,
                    "state": "ORDER_STATE_PARTIALLY_FILLED",
                    "avgPx": {"value": "0.4800"},
                },
            },
            {
                "id": "D9ZCT3CGK1KN",
                "order": {
                    "id": "D9ZCT3CG11KJ",
                    "marketSlug": "aec-utr-guaale-bralac-2026-10-24",
                    "cumQuantity": 0.19,
                    "state": "ORDER_STATE_EXPIRED",
                    "avgPx": {"value": "0.4800"},
                },
            },
        ],
    }


def test_guajardo_leftover_empty_activities_uses_this_order_cumqty():
    """Replay: Poly activities GET empty at confirm, but this order filled 0.19."""
    tape = _guajardo_leftover_tape()
    empty = {"activities": [], "eof": True}
    with patch.object(polymarket_us_live, "get_activities", return_value=(200, json.dumps(empty))):
        confirm = venue_fill_confirm.confirm_order(
            "polymarket",
            tape,
            {
                "venue": "polymarket",
                "instrument": "aec-utr-guaale-bralac-2026-10-24",
                "outcome": "yes",
                "intent": "ORDER_INTENT_BUY_LONG",
            },
            tries=1,
            sleep_sec=0,
        )
    assert confirm["known"] is True
    assert Decimal(confirm["qty"]) == Decimal("0.19")
    assert confirm["house_fill"] is False
    assert "cumQuantity" in confirm["note"]
    payload = venue_fill_confirm.attach(tape, confirm)
    assert live_lock_orders.filled_contracts(payload) == Decimal("0.19")
    assert live_lock_orders.leg_filled_at_least_one({"payload": payload, "status": 200}) is False


def test_poly_http200_cumqty_0_empty_activities_is_still_not_a_fill():
    tape = {
        "id": "oid-miss",
        "marketSlug": "aec-test",
        "qtyDecimal": "664.12",
        "executions": [
            {
                "order": {
                    "id": "oid-miss",
                    "cumQuantity": 0,
                    "leavesQuantity": 1,
                    "state": "ORDER_STATE_NEW",
                    "marketSlug": "aec-test",
                }
            },
            {
                "order": {
                    "id": "oid-miss",
                    "cumQuantity": 0,
                    "state": "ORDER_STATE_EXPIRED",
                    "marketSlug": "aec-test",
                }
            },
        ],
    }
    empty = {"activities": [], "eof": True}
    with patch.object(polymarket_us_live, "get_activities", return_value=(200, json.dumps(empty))):
        confirm = venue_fill_confirm.confirm_order(
            "polymarket",
            tape,
            {"venue": "polymarket", "instrument": "aec-test", "outcome": "yes"},
            tries=1,
            sleep_sec=0,
        )
    assert confirm["known"] is True
    assert Decimal(confirm["qty"]) == Decimal("0")
    assert confirm["house_fill"] is False
    payload = venue_fill_confirm.attach(tape, confirm)
    assert live_lock_orders.filled_contracts(payload) == Decimal("0")


def test_novig_fills_persist_venue_fee_including_uncharged_zero():
    tape = {"orderId": "n-1", "status": "FILLED", "qty": 100, "remaining": 0}
    spec = {"venue": "novig", "instrument": "m-1", "outcome": "yes", "outcome_id": "o-1"}
    charged = {
        "items": [{
            "fillId": "f1",
            "orderId": "n-1",
            "marketId": "m-1",
            "outcomeId": "o-1",
            "qty": 100,
            "cost": "0.40",
            "taker": True,
            "ts": 1,
            "fee": "0.01440",
        }],
    }
    with patch.object(novig_live, "list_fills", return_value=(200, json.dumps(charged))):
        confirm = venue_fill_confirm.confirm_order("novig", tape, spec, tries=1, sleep_sec=0)
    assert confirm["known"] is True
    assert Decimal(confirm["qty"]) == Decimal("1.00")
    assert confirm["fee"] == "0.01440"
    payload = venue_fill_confirm.attach(tape, confirm)
    assert live_lock_orders.fee_returned(payload) == Decimal("0.01440")
    spec_fee = {
        "venue": "novig",
        "fee_coefficient": "0.06",
        "fee_charged": "WHEN_LIVE",
        "event_status": "OPEN_INGAME",
        "pay": "0.40",
        "limit": "0.40",
        "outcome": "yes",
        "_bet_key": "novig-fee",
    }
    row = live_lock_orders._sent_row(spec_fee, 201, payload, "filled")
    assert row["fee"] == "0.01440"
    assert row["fee_source"] == "venue"
    assert row["after_fee"] == "0.41440"

    uncharged = {
        "items": [{
            "fillId": "f2",
            "orderId": "n-1",
            "marketId": "m-1",
            "outcomeId": "o-1",
            "qty": 100,
            "cost": "0.40",
            "taker": True,
            "ts": 1,
        }],
    }
    with patch.object(novig_live, "list_fills", return_value=(200, json.dumps(uncharged))):
        confirm0 = venue_fill_confirm.confirm_order("novig", tape, spec, tries=1, sleep_sec=0)
    assert Decimal(confirm0["fee"]) == Decimal("0")
    payload0 = venue_fill_confirm.attach(tape, confirm0)
    assert live_lock_orders.fee_returned(payload0) == Decimal("0")
    row0 = live_lock_orders._sent_row(spec_fee, 201, payload0, "filled")
    assert Decimal(row0["fee"]) == Decimal("0")
    assert row0["fee_source"] == "venue"
    assert Decimal(row0["after_fee"]) == Decimal("0.40")


def test_poly_house_cash_picks_closest_to_quote_not_nickel():
    """Kostina T0: quote 0.48, avg 0.52, spread 0.48 — keep 0.48, not Yes-wire."""
    assert venue_fill_confirm.poly_house_cash(
        avg="0.5200",
        spread="0.4800",
        quote="0.48",
        intent="ORDER_INTENT_BUY_SHORT",
    ) == Decimal("0.4800")
    assert venue_fill_confirm.poly_house_cash(
        avg="0.4800",
        spread="0.5200",
        quote="0.53",
        intent="ORDER_INTENT_BUY_SHORT",
    ) == Decimal("0.5200")
    # Varaksina: quote matches avg, do not swap onto spread.
    assert venue_fill_confirm.poly_house_cash(
        avg="0.3600",
        spread="0.6400",
        quote="0.36",
        intent="ORDER_INTENT_BUY_SHORT",
    ) == Decimal("0.3600")
    # Kuhar: kitchen Yes-ask 0.74 is not the debit; posted limit 0.26 is.
    assert venue_fill_confirm.poly_house_cash(
        avg="0.2600",
        spread="0.7400",
        quote="0.74",
        api_limit="0.26",
        intent="ORDER_INTENT_BUY_SHORT",
    ) == Decimal("0.2600")
    assert venue_fill_confirm.poly_house_cash(
        avg="0.7400",
        spread="0.2600",
        quote="0.74",
        api_limit="0.26",
        intent="ORDER_INTENT_BUY_SHORT",
    ) == Decimal("0.2600")


if __name__ == "__main__":
    test_kalshi_201_fill_count_0_and_empty_fills_is_not_a_fill()
    test_kalshi_fills_get_qty_1_is_a_fill_even_if_tape_said_zero()
    test_confirm_timeout_does_not_invent_a_fill()
    test_house_fill_uses_this_order_qty()
    test_poly_partial_qty_below_1_is_not_house_fill()
    test_send_uses_empty_fills_get_not_tape()
    test_send_uses_fills_get_qty_1_when_tape_is_empty()
    test_send_timeout_confirm_does_not_claim_tape_fill()
    test_poly_confirm_filters_to_our_aggressor_order()
    test_poly_confirm_without_order_id_does_not_sum_slug()
    test_poly_nanosecond_create_time_parses()
    test_documented_endpoints_only()
    test_guajardo_leftover_empty_activities_uses_this_order_cumqty()
    test_poly_http200_cumqty_0_empty_activities_is_still_not_a_fill()
    test_novig_fills_persist_venue_fee_including_uncharged_zero()
    test_poly_house_cash_picks_closest_to_quote_not_nickel()
    print("venue fill confirm tests ok")
