"""Lock venue-fill + venue-settle per platform. No network. No secrets."""
from __future__ import annotations

from decimal import Decimal

import live_lock_orders
import open_count_sync
import settled_pnl_store
import venue_fill_confirm
import write_orders_performance as w


def test_kalshi_no_fill_is_confirm_house_not_yes_wire():
    spec = {
        "venue": "kalshi",
        "instrument": "KXWTACHALLENGERMATCH-26OCT25OSBHIN-OSB",
        "outcome": "no",
        "pay": "0.93",
        "limit": "0.07",
    }
    payload = venue_fill_confirm.attach(
        {
            "order_id": "01a179a7-e628-7aef-9600-afe97ae29d38",
            "fill_count": "1.00",
            "average_fill_price": "0.1100",
            "average_fee_paid": "0.0069",
            "no_price_dollars": "0.8900",
            "yes_price_dollars": "0.1100",
        },
        {
            "known": True,
            "qty": "1.00",
            "avg_price": "0.8900",
            "house_cash": "0.8900",
            "house_fill": True,
            "order_id": "01a179a7-e628-7aef-9600-afe97ae29d38",
            "venue": "kalshi",
        },
    )
    assert live_lock_orders._actual_fill_cash(spec, payload) == Decimal("0.8900")
    cash, fee, qty = w.fill_cash_fee(
        {"venue": "kalshi", "side": "no", "limit_price": "0.07", "quote_price": "0.89"},
        {"request": {"side": "no"}, "response": payload},
    )
    assert qty >= 1
    assert cash == Decimal("0.8900")
    info = {"status": "finalized", "result": "yes"}
    assert settled_pnl_store.result_from_market(info) == "yes"
    st, pnl = w.ticket_settled_pnl(
        {
            "order_id": "TEST-KALSHI-NO-NOT-LIVE",
            "venue": "kalshi",
            "instrument": spec["instrument"],
            "side": "no",
            "qty": "1",
            "cash": "0.8900",
            "fee": "0.0069",
        },
        [{"ticker": spec["instrument"], "result": "yes", "venue": "kalshi"}],
        "",
    )
    assert st == "lose"
    assert pnl == Decimal("-0.8969")


def test_gemini_buy_avg_is_house_resolution_side_is_settle():
    payload = {
        "orderId": "gem-1",
        "symbol": "GEMI-NCAAF-2610202300-MTN-FIU-T-O48",
        "side": "buy",
        "outcome": "yes",
        "filledQuantity": "1",
        "avgExecutionPrice": "0.4400",
        "status": "filled",
    }
    spec = {"venue": "gemini", "outcome": "yes", "pay": "0.44", "instrument": payload["symbol"]}
    assert live_lock_orders._actual_fill_cash(spec, payload) == Decimal("0.4400")
    cash, fee, qty = w.fill_cash_fee(
        {"venue": "gemini", "side": "yes", "limit_price": "0.44"},
        {"request": {"outcome": "yes", "symbol": payload["symbol"]}, "response": payload},
    )
    assert qty >= 1
    assert cash == Decimal("0.4400")
    row = w._contract_settlement(
        {"ticker": payload["symbol"], "resolutionSide": "yes", "status": "resolved"},
        venue="Gemini",
        game="Middle Tennessee vs FIU",
        sport="college football",
        source="test",
    )
    assert row["result"] == "yes"
    st, pnl = w.ticket_settled_pnl(
        {
            "order_id": "TEST-GEMINI-YES-NOT-LIVE",
            "venue": "gemini",
            "instrument": payload["symbol"],
            "side": "yes",
            "qty": "1",
            "cash": "0.4400",
            "fee": "0.02",
        },
        [{"ticker": payload["symbol"], "result": "yes", "venue": "gemini"}],
        "",
    )
    assert st == "win"
    assert pnl == Decimal("0.5400")


def test_novig_cost_is_house_no_invented_ticker_yes():
    fills = {
        "items": [
            {"orderId": "nov-1", "qty": "100", "cost": "0.40", "fee": "0.01"},
        ]
    }
    qty, price, note, fee = venue_fill_confirm._from_novig_fills(
        fills["items"], {"order_id": "nov-1"}
    )
    assert qty == Decimal("1.00")
    assert price == Decimal("0.40")
    assert fee == Decimal("0.01")
    assert settled_pnl_store.fetch_market_result("novig", "nov-1") == {}
    st, pnl = w.ticket_settled_pnl(
        {
            "order_id": "TEST-NOVIG-NOT-LIVE",
            "venue": "novig",
            "instrument": "nov-1",
            "side": "yes",
            "qty": "1",
            "cash": "0.40",
            "fee": None,
        },
        [{"ticker": "nov-1", "result": "yes", "venue": "novig"}],
        "",
    )
    assert st == "open"
    assert pnl is None


def test_ticker_result_scans_all_rows_for_settlement_px():
    slug = "aec-atp-yutshi-yuhhsu-2026-10-27"
    rows = [
        {"ticker": slug, "result": "yes", "source": "close_hook:removed", "venue": "polymarket"},
        {"ticker": slug, "result": "no", "settlementPx": "0.0000", "source": "live_market_get", "venue": "polymarket"},
    ]
    assert w.ticker_result(rows, slug) == "no"
    assert w.ticker_result(list(reversed(rows)), slug) == "no"


def test_live_market_get_beats_tape_rebuild_zero():
    """Pohle: stored tape_rebuild settlementPx 0 cannot beat a live GET of 1.0000."""
    slug = "aec-itfwo-vicpoh-arikos-2026-10-28"
    poison = {"ticker": slug, "result": "no", "settlementPx": "0", "source": "tape_rebuild", "venue": "polymarket"}
    live = {
        "ticker": slug,
        "result": "yes",
        "settlementPx": "1.0000",
        "source": "live_market_get",
        "venue": "polymarket",
    }
    assert w.ticker_result([poison, live], slug) == "yes"
    assert w.ticker_result([live, poison], slug) == "yes"
    merged = w.merge_settlement_rows([poison], [live])
    assert w.ticker_result(merged, slug) == "yes"
    merged_rev = w.merge_settlement_rows([live], [poison])
    assert w.ticker_result(merged_rev, slug) == "yes"


def test_poly_settlement_px_dict_beats_ticker_yes():
    book = {
        "marketData": {
            "marketSlug": "aec-atp-yutshi-yuhhsu-2026-10-27",
            "state": "MARKET_STATE_EXPIRED",
            "stats": {"settlementPx": {"value": "0.0000", "currency": "USD"}},
        }
    }
    fields = open_count_sync._poly_payload_fields(book)
    assert fields["result"] == "no"
    assert settled_pnl_store.result_from_market(book["marketData"]["stats"]) == "no"
    assert settled_pnl_store.result_from_market({"result": "yes", "settlementPx": {"value": "0.0000"}}) == "no"
    assert w.ticker_result(
        [{"ticker": "aec-atp-yutshi-yuhhsu-2026-10-27", "result": "yes", "settlementPx": "0.0000"}],
        "aec-atp-yutshi-yuhhsu-2026-10-27",
    ) == "no"


def main() -> None:
    tests = (
        test_kalshi_no_fill_is_confirm_house_not_yes_wire,
        test_gemini_buy_avg_is_house_resolution_side_is_settle,
        test_novig_cost_is_house_no_invented_ticker_yes,
        test_ticker_result_scans_all_rows_for_settlement_px,
        test_live_market_get_beats_tape_rebuild_zero,
        test_poly_settlement_px_dict_beats_ticker_yes,
    )
    failed = 0
    for fn in tests:
        try:
            fn()
            print("PASS", fn.__name__)
        except Exception as exc:
            failed += 1
            print("FAIL", fn.__name__, type(exc).__name__, exc)
    if failed:
        raise SystemExit(f"{failed} failed")
    print("test_venue_truth_platforms ok")


if __name__ == "__main__":
    main()
