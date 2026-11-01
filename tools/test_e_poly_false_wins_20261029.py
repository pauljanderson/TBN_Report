"""Maloney/Vismane and Lollia/Maquet: Poly last-trade px is not a win.

No network. No secrets. Does not place or sell.
"""
from __future__ import annotations

from decimal import Decimal

import open_count_sync
import settled_pnl_store
import write_orders_performance as w

MALONEY_SLUG = "aec-itfwo-elimal-danvis-2026-10-29"
LOLLIA_SLUG = "aec-itfwo-matlol-marmaq-2026-10-29"
VISMANE = {
    "order_id": "DCZRK4MG11M3",
    "venue": "polymarket",
    "instrument": MALONEY_SLUG,
    "side": "no",
    "io_intent": "ORDER_INTENT_BUY_SHORT",
    "player": "Daniela Vismane",
    "qty": "1",
    "cash": "0.3700",
    "fee": "0.0200",
    "step": "e-t0",
}
LOLLIA = {
    "order_id": "DCZSAM3011KJ",
    "venue": "polymarket",
    "instrument": LOLLIA_SLUG,
    "side": "yes",
    "io_intent": "ORDER_INTENT_BUY_LONG",
    "player": "Mathilde Lollia",
    "qty": "1",
    "cash": "0.4300",
    "fee": "0.0200",
    "step": "e-t0",
}


def test_mid_last_trade_px_is_not_a_winner():
    maloney_book = {
        "state": "MARKET_STATE_CLOSED",
        "settlementPx": {"value": "0.6700", "currency": "USD"},
        "result": "no",
        "source": "polymarket_position_resolution",
        "venue": "polymarket",
    }
    lollia_book = {
        "state": "MARKET_STATE_CLOSED",
        "settlementPx": {"value": "0.4300", "currency": "USD"},
        "result": "yes",
        "source": "polymarket_position_resolution",
        "venue": "polymarket",
    }
    assert open_count_sync._poly_payload_fields(maloney_book)["result"] == ""
    assert settled_pnl_store.result_from_market(maloney_book) == ""
    assert settled_pnl_store.result_from_market(lollia_book) == ""
    poison = [
        {
            "ticker": MALONEY_SLUG,
            "result": "no",
            "settlementPx": "0.6700",
            "source": "polymarket_position_resolution",
            "venue": "polymarket",
        },
        {
            "ticker": LOLLIA_SLUG,
            "result": "yes",
            "settlementPx": "0.4300",
            "source": "tape_rebuild",
            "venue": "polymarket",
        },
    ]
    assert w.ticker_result(poison, MALONEY_SLUG) == ""
    assert w.ticker_result(poison, LOLLIA_SLUG) == ""
    st, pnl = w.ticket_settled_pnl(VISMANE, poison, "")
    assert st == "open"
    assert pnl is None
    st, pnl = w.ticket_settled_pnl(LOLLIA, poison, "")
    assert st == "open"
    assert pnl is None


def test_binary_px_maloney_won_vismane_short_loses():
    """Official: Maloney 2-0. Poly Yes token = Maloney. E BUY_SHORT Vismane loses."""
    settlements = [
        {
            "ticker": MALONEY_SLUG,
            "result": "yes",
            "settlementPx": "1.0000",
            "source": "live_market_get",
            "venue": "polymarket",
        }
    ]
    assert w.ticker_result(settlements, MALONEY_SLUG) == "yes"
    st, pnl = w.ticket_settled_pnl(VISMANE, settlements, "")
    assert st == "lose"
    assert pnl == Decimal("-0.3900")


def test_binary_px_maquet_won_lollia_long_loses():
    """Official: Maquet 6-2 6-3. Poly Yes token = Lollia. E BUY_LONG Lollia loses."""
    settlements = [
        {
            "ticker": LOLLIA_SLUG,
            "result": "no",
            "settlementPx": "0.0000",
            "source": "live_market_get",
            "venue": "polymarket",
        }
    ]
    assert w.ticker_result(settlements, LOLLIA_SLUG) == "no"
    st, pnl = w.ticket_settled_pnl(LOLLIA, settlements, "")
    assert st == "lose"
    assert pnl == Decimal("-0.4500")


def test_result_yes_without_px_ignored_for_poly():
    assert settled_pnl_store.result_from_market(
        {"result": "yes", "venue": "polymarket", "source": "polymarket_position_resolution"}
    ) == ""
    assert w.ticker_result(
        [{"ticker": MALONEY_SLUG, "result": "yes", "venue": "polymarket", "source": "close_hook:settled"}],
        MALONEY_SLUG,
    ) == ""


def test_live_get_binary_px_beats_stored_result_no():
    poison = {"ticker": MALONEY_SLUG, "result": "no", "settlementPx": "0.6700", "source": "tape_rebuild", "venue": "polymarket"}
    live = {
        "ticker": MALONEY_SLUG,
        "result": "yes",
        "settlementPx": "1.0000",
        "source": "live_market_get",
        "venue": "polymarket",
    }
    merged = w.merge_settlement_rows([poison], [live])
    assert w.ticker_result(merged, MALONEY_SLUG) == "yes"


if __name__ == "__main__":
    test_mid_last_trade_px_is_not_a_winner()
    test_binary_px_maloney_won_vismane_short_loses()
    test_binary_px_maquet_won_lollia_long_loses()
    test_result_yes_without_px_ignored_for_poly()
    test_live_get_binary_px_beats_stored_result_no()
    print("ok")
