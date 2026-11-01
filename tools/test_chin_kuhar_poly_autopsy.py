"""Chin vs Kuhar 28 Oct 2026: Kuhar won; kitchen Yes-wire is not venue debit."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import live_pm_settle_reconcile as rec
import settled_pnl_store
import venue_fill_confirm
import write_orders_performance as w

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tools" / "fixtures" / "chin_kuhar_poly_20261028.json"
SLUG = "aec-itfme-johchi-matkuh-2026-10-28"


def _blob():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_official_kuhar_won_yes_chin_is_zero():
    blob = _blob()
    assert blob["official_winner"] == "Matt Kuhar"
    assert blob["official_score"] == "4-6 6-1 6-1"
    px = blob["poly_settlement"]
    assert px["yes_outcome"] == "John Chin"
    assert px["settlementPx"] == "0.0000"
    assert settled_pnl_store.result_from_market(px) == "no"


def test_kuhar_short_cash_is_debit_0_26_not_yes_wire_0_74():
    kuhar = _blob()["legs"]["t0_kuhar"]
    assert kuhar["intent"] == "ORDER_INTENT_BUY_SHORT"
    assert Decimal(str(kuhar["yes_wire"])) == Decimal("0.7400")
    cash = venue_fill_confirm.poly_house_cash(
        avg=kuhar["trade_px"],
        quote=kuhar["quote_price"],
        api_limit=kuhar["limit_price"],
        intent=kuhar["intent"],
    )
    assert cash == Decimal("0.2600")
    chin = _blob()["legs"]["t0_chin"]
    cash_chin = venue_fill_confirm.poly_house_cash(
        avg=chin["trade_px"],
        quote=chin["quote_price"],
        api_limit=chin["limit_price"],
        intent=chin["intent"],
    )
    assert cash_chin == Decimal("0.2700")


def test_venue_true_pnl_kuhar_won():
    settlements = [
        {
            "ticker": SLUG,
            "result": "no",
            "settlementPx": "0.0000",
            "venue": "polymarket",
            "source": "live_market_get",
        }
    ]
    chin = {
        "order_id": "TEST-CHIN-T0-NOT-LIVE",
        "venue": "polymarket",
        "instrument": SLUG,
        "side": "yes",
        "qty": "1",
        "cash": "0.2700",
        "fee": "0.0100",
        "player": "John Chin",
    }
    kuhar = {
        "order_id": "TEST-KUHAR-T0-NOT-LIVE",
        "venue": "polymarket",
        "instrument": SLUG,
        "side": "no",
        "qty": "1",
        "cash": "0.2600",
        "fee": "0.0100",
        "player": "Matt Kuhar",
    }
    st_c, pnl_c = w.ticket_settled_pnl(chin, settlements, "")
    st_k, pnl_k = w.ticket_settled_pnl(kuhar, settlements, "")
    assert st_c == "lose" and pnl_c == Decimal("-0.2800")
    assert st_k == "win" and pnl_k == Decimal("0.7300")
    kitchen_kuhar = Decimal("0.2500")
    assert pnl_k - kitchen_kuhar == Decimal("0.4800")
    assert pnl_c + pnl_k == Decimal("0.4500")


def test_yes_wire_kitchen_understates_kuhar_win():
    settlements = [
        {"ticker": SLUG, "result": "no", "settlementPx": "0.0000", "venue": "polymarket"}
    ]
    kitchen = {
        "order_id": "TEST-KUHAR-WIRE-NOT-LIVE",
        "venue": "polymarket",
        "instrument": SLUG,
        "side": "no",
        "qty": "1",
        "cash": "0.7400",
        "fee": "0.0100",
    }
    st, pnl = w.ticket_settled_pnl(kitchen, settlements, "")
    assert st == "win" and pnl == Decimal("0.2500")


def test_reconciler_maps_chin_kuhar_trades():
    blob = _blob()
    by_id = rec.fills_by_order(blob["trades"])
    assert by_id["DCCWHAK011MM"]["qty"] == Decimal("1.0000")
    assert by_id["DCCWHE2G11M3"]["qty"] == Decimal("1.0000")
    assert w.qty_is_fill("1") is True
    assert w.qty_is_house_fill("1") is True


def main() -> None:
    tests = (
        test_official_kuhar_won_yes_chin_is_zero,
        test_kuhar_short_cash_is_debit_0_26_not_yes_wire_0_74,
        test_venue_true_pnl_kuhar_won,
        test_yes_wire_kitchen_understates_kuhar_win,
        test_reconciler_maps_chin_kuhar_trades,
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
    print("test_chin_kuhar_poly_autopsy ok")


if __name__ == "__main__":
    main()
