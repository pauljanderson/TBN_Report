"""Gibson vs Oliynykova 2026-11-03: real +$0.01 lock gap, NOT a 1.67 mistake.

Venue truth (recon / screenshots):
- Kalshi KXWTAMATCH-26NOV01GIBOLI-OLI No @ 0.82 fee 0.0104 → after-fee 0.8304, win +$0.17
- Poly DG3S450G32VX BUY_SHORT ORDER_SIDE_SELL @ 0.84 Yes-wire → house cost 0.16, loss −$0.16
- Pair all-in ≈ 0.99, realized +$0.01

Dashboard bug: booked Poly wire/after-fee 0.84 and P&L −$0.84 (false C≈1.67).
Earlier assistant wrongly told Paul it was a 1.67 buy mistake — reporting only.

No network. No secrets.
"""
from __future__ import annotations

from decimal import Decimal

import live_lock_orders
import venue_fill_confirm
import write_orders_performance as w
from order_ledger import polymarket_fill

ONE = Decimal("1")
SLUG = "aec-wta-talgib-oleoli-2026-11-01"
KALSHI = "KXWTAMATCH-26NOV01GIBOLI-OLI"
POLY_OID = "DG3S450G32VX"


def _gibson_poly_payload() -> dict:
    """Passive BUY_SHORT SELL fill: avgPx=commissionSpreadPx=0.84 Yes-wire."""
    return {
        "id": POLY_OID,
        "marketSlug": SLUG,
        "side": "ORDER_SIDE_SELL",
        "type": "ORDER_TYPE_LIMIT",
        "price": {"value": "0.84", "currency": "USD"},
        "quantity": 1,
        "cumQuantity": 1,
        "leavesQuantity": 0,
        "intent": "ORDER_INTENT_BUY_SHORT",
        "state": "ORDER_STATE_FILLED",
        "avgPx": {"value": "0.8400", "currency": "USD"},
        "commissionNotionalTotalCollected": {"value": "0.0000", "currency": "USD"},
        "outcomeSide": "OUTCOME_SIDE_NO",
        "action": "ORDER_ACTION_BUY",
        "marketMetadata": {
            "slug": SLUG,
            "title": "Talia Gibson vs. Oleksandra Oliynykova",
            "outcome": "Oleksandra Oliynykova",
        },
    }


def test_poly_house_cash_gibson_sell_yes_wire_is_cost_0_16_not_0_84():
    """BUY_SHORT SELL @ 0.84 with spread echoed as 0.84 → debit 0.16, never 0.84."""
    cash = venue_fill_confirm.poly_house_cash(
        avg="0.8400",
        spread="0.8400",
        intent="ORDER_INTENT_BUY_SHORT",
        order_side="ORDER_SIDE_SELL",
        outcome_side="OUTCOME_SIDE_NO",
    )
    assert cash == Decimal("0.1600")
    # Same when spread is missing (activities order node has no commissionSpreadPx).
    cash2 = venue_fill_confirm.poly_house_cash(
        avg="0.8400",
        spread=None,
        intent="ORDER_INTENT_BUY_SHORT",
        order_side="ORDER_SIDE_SELL",
        outcome_side="OUTCOME_SIDE_NO",
    )
    assert cash2 == Decimal("0.1600")


def test_polymarket_fill_and_fill_cash_fee_gibson_not_1_67():
    payload = _gibson_poly_payload()
    poly = polymarket_fill(payload)
    assert poly["intent"] == "ORDER_INTENT_BUY_SHORT"
    assert Decimal(str(poly["avg"])) == Decimal("0.8400")
    assert Decimal(str(poly["cash"])) == Decimal("0.1600")
    assert poly["side"] == "no"

    cash, fee, qty = w.fill_cash_fee(
        {
            "venue": "polymarket",
            "side": "yes",  # lock yes-leg stamp (dashboard mislabel path)
            "limit_price": "0.84",
            "house_cash": "0.84",  # wrongly stamped Yes-wire
            "wire": "0.84",
            "after_fee": "0.84",
            "fee": "0",
            "confirm_known": True,
            "confirm_qty": "1",
            "intent": "ORDER_INTENT_BUY_SHORT",
            "order_side": "ORDER_SIDE_SELL",
            "outcome_side": "OUTCOME_SIDE_NO",
        },
        {
            "request": {
                "intent": "ORDER_INTENT_BUY_SHORT",
                "price": {"value": "0.84"},
            },
            "response": payload,
        },
    )
    assert qty == ONE
    assert cash == Decimal("0.1600")
    assert cash != Decimal("0.8400")


def test_gibson_cluster_is_corrected_lock_plus_0_01_not_1_67_mistake():
    """Kalshi No win +0.17 + Poly cost 0.16 loss −0.16 → pair +0.01. Not C≈1.67 / −0.84."""
    kalshi = {
        "venue": "kalshi",
        "instrument": KALSHI,
        "side": "no",
        "player": "Oleksandra Oliynykova",
        "qty": "1",
        "cash": "0.8200",
        "fee": "0.0104",
        "order_id": "01a1a01b-gibson-kalshi-test",
    }
    poly = {
        "venue": "polymarket",
        "instrument": SLUG,
        "side": "yes",
        "player": "Oleksandra Oliynykova",
        "outcome_name": "Oleksandra Oliynykova",
        "io_intent": "ORDER_INTENT_BUY_SHORT",
        "qty": "1",
        "cash": "0.1600",
        "fee": "0",
        "order_id": POLY_OID,
    }
    # Wrong cash (Yes-wire) must be flagged, not booked as a lock.
    bad_poly = dict(poly, cash="0.8400")
    bad = {
        "game": "Gibson vs Oliynykova",
        "sport": "tennis",
        "system_letter": "A",
        "intent": w.INTENT_FULL_LOCK,
        "complementary": True,
        "fill_legs": [kalshi, bad_poly],
        "n_fill_legs": 2,
        "notes": [],
    }
    assert w.flag_lock_all_in_over_one(bad) is True
    assert bad.get("lock_all_in_mistake") is True
    assert bad.get("complementary") is False
    all_in_bad = w.fill_legs_after_fee_all_in([kalshi, bad_poly])
    assert all_in_bad is not None and all_in_bad > ONE
    assert all_in_bad != Decimal("0.99")

    settlements = [
        {"ticker": KALSHI, "result": "no", "venue": "kalshi"},
        {"ticker": SLUG, "result": "no", "settlementPx": "0.0000", "venue": "polymarket"},
    ]
    cluster = {
        "game": "Talia Gibson vs Oleksandra Oliynykova",
        "sport": "tennis",
        "system_letter": "A",
        "system_name": "Lock gap",
        "intent": w.INTENT_FULL_LOCK,
        "complementary": True,
        "fill_legs": [kalshi, poly],
        "n_fill_legs": 2,
        "legs": [kalshi, poly],
        "notes": [],
    }
    scored = w.score_cluster(cluster, settlements)
    realized = Decimal(str(scored.get("realized") or 0))
    assert abs(realized - Decimal("0.01")) <= Decimal("0.0001") or abs(
        realized - (ONE - Decimal("0.8304") - Decimal("0.1600"))
    ) <= Decimal("0.0001")
    assert realized != Decimal("-0.67")  # would be 1 - 1.67
    lock_pnl = w.lock_realized([kalshi, poly])
    assert abs(lock_pnl - Decimal("0.0096")) <= Decimal("0.0001")

    st_k, pnl_k = w.ticket_settled_pnl(kalshi, settlements, "Talia Gibson")
    st_p, pnl_p = w.ticket_settled_pnl(poly, settlements, "Talia Gibson")
    assert st_k == "win" and pnl_k is not None
    assert abs(pnl_k - Decimal("0.1696")) <= Decimal("0.0001")
    assert st_p == "lose" and pnl_p is not None
    assert pnl_p == Decimal("-0.1600")
    assert pnl_p != Decimal("-0.8400")
    assert abs((pnl_k + pnl_p) - Decimal("0.0096")) <= Decimal("0.0001")

    w.apply_paul_history([cluster], [])
    note_blob = " ".join(cluster.get("notes") or [])
    assert "Corrected Gibson/Oliynykova lock" in note_blob
    assert "1.67" in note_blob
    assert "+$0.01" in note_blob or "+0.01" in note_blob


def test_pair_net_kalshi_fee_blocks_after_fee_over_net_max():
    """Send-line uses after-fee C; Kalshi fee must count (pair_net no longer skips it)."""

    class Scan:
        def gemini_fee(self, price: Decimal) -> Decimal:
            return Decimal("0")

        def gemini_no_rejection(self, cand: dict):
            return None

        def _trade_bet_key(self, *a):
            return "bet"

    # Wire 0.40+0.52+Poly0.02=0.94 ≤ 0.95; + Kalshi fee(0.40)=0.0168 → 0.9568 > 0.95
    cand = {
        "market_type": "moneyline",
        "yes_venue": "kalshi",
        "no_venue": "polymarket",
        "yes_price": "0.40",
        "no_price": "0.52",
        "yes_size": "1",
        "no_size": "1",
        "polymarket_fee": "0.02",
        "kalshi_ticker": KALSHI,
        "polymarket_slug": SLUG,
    }
    net = live_lock_orders.pair_net(Scan(), cand)
    assert net is not None
    assert net > live_lock_orders.effective_net_max()
    wire_only = Decimal("0.40") + Decimal("0.52") + Decimal("0.02")
    assert wire_only <= live_lock_orders.effective_net_max()


if __name__ == "__main__":
    test_poly_house_cash_gibson_sell_yes_wire_is_cost_0_16_not_0_84()
    test_polymarket_fill_and_fill_cash_fee_gibson_not_1_67()
    test_gibson_cluster_is_corrected_lock_plus_0_01_not_1_67_mistake()
    test_pair_net_kalshi_fee_blocks_after_fee_over_net_max()
    print("gibson oliynykova lock-gap reporting tests ok")
