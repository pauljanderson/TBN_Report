"""Duhan vs Lakshmanan 28 Oct 2026: Poly trades vs kitchen. No network. No secrets."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import live_pm_settle_reconcile as rec
import settled_pnl_store
import write_orders_performance as w

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tools" / "fixtures" / "duhan_lakshmanan_poly_20261028.json"
SLUG = "aec-itfme-chiduh-arylak-2026-10-28"


def _blob():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_official_lakshmanan_won():
    blob = _blob()
    assert blob["official_winner"] == "Aryan Lakshmanan"
    assert blob["poly_settlement"]["result"] == "no"
    assert blob["poly_settlement"]["yes_outcome"] == "Chirag Duhan"
    assert settled_pnl_store.result_from_market(blob["poly_settlement"]) == "no"


def test_poly_lists_0_02_not_the_zero_fok():
    blob = _blob()
    fills = rec.fills_by_order(blob.get("trades") or [])
    assert fills["DC9R5HV011TB"]["qty"] == Decimal("0.0200")
    assert Decimal(str(fills["DC9R5HV011TB"]["price"])) == Decimal("0.4800")
    assert "DC9FDBMG11N6" not in fills
    assert fills["DC8MDRS011R3"]["qty"] == Decimal("1.0000")
    assert fills["DC8MDY5011TB"]["qty"] == Decimal("1.0000")
    res = (blob.get("resolutions") or [{}])[0]
    after = res.get("after") or {}
    assert str(after.get("qtyBoughtDecimal") or "") == "1.0200"
    assert str(after.get("qtySoldDecimal") or "") == "1.0200"


def test_0_02_is_ledger_fill_not_missed_send():
    assert w.qty_is_fill(Decimal("0.02")) is True
    assert w.qty_is_house_fill(Decimal("0.02")) is False
    assert w.is_empty_http_fill(200, Decimal("0.02")) is False
    assert w.is_empty_http_fill(200, Decimal("0")) is True


def test_venue_true_book():
    store = {}
    market = {
        "venue": "polymarket",
        "settlementPx": "0.0000",
        "result": "no",
    }
    rec.apply_row(
        {
            "order_id": "DC8MDRS011R3",
            "venue": "polymarket",
            "instrument": SLUG,
            "side": "yes",
            "quote_price": "0.73",
            "limit_price": "0.73",
            "confirm_qty": "1",
            "http_status": 200,
            "game": "Chirag Duhan vs. Aryan Lakshmanan",
        },
        venue_fill={"qty": "1", "price": "0.73", "intent": "ORDER_INTENT_BUY_LONG", "fee": "0.01"},
        market=market,
        store=store,
    )
    rec.apply_row(
        {
            "order_id": "DC8MDY5011TB",
            "venue": "polymarket",
            "instrument": SLUG,
            "side": "no",
            "quote_price": "0.28",
            "limit_price": "0.72",
            "confirm_qty": "1",
            "http_status": 200,
            "game": "Chirag Duhan vs. Aryan Lakshmanan",
        },
        venue_fill={"qty": "1", "price": "0.72", "intent": "ORDER_INTENT_BUY_SHORT", "fee": "0.01"},
        market=market,
        store=store,
    )
    rec.apply_row(
        {
            "order_id": "DC9R5HV011TB",
            "venue": "polymarket",
            "instrument": SLUG,
            "side": "no",
            "quote_price": "0.52",
            "limit_price": "0.48",
            "confirm_qty": "0.02",
            "http_status": 200,
            "game": "Chirag Duhan vs. Aryan Lakshmanan",
        },
        venue_fill={"qty": "0.02", "price": "0.48", "intent": "ORDER_INTENT_BUY_SHORT", "fee": "0"},
        market=market,
        store=store,
    )
    rec.apply_row(
        {
            "order_id": "DC9FDBMG11N6",
            "venue": "polymarket",
            "instrument": SLUG,
            "side": "no",
            "confirm_qty": "0",
            "http_status": 200,
        },
        venue_fill=None,
        market=market,
        store=store,
    )
    assert store["DC8MDRS011R3"]["status"] == "lose"
    assert store["DC8MDY5011TB"]["status"] == "win"
    assert store["DC9R5HV011TB"]["status"] == "win"
    assert Decimal(str(store["DC9R5HV011TB"]["qty"])) == Decimal("0.0200")
    assert "DC9FDBMG11N6" not in store
    net = (
        Decimal(str(store["DC8MDRS011R3"]["pnl"]))
        + Decimal(str(store["DC8MDY5011TB"]["pnl"]))
        + Decimal(str(store["DC9R5HV011TB"]["pnl"]))
    )
    assert net == Decimal("-0.0196")


def main() -> None:
    tests = (
        test_official_lakshmanan_won,
        test_poly_lists_0_02_not_the_zero_fok,
        test_0_02_is_ledger_fill_not_missed_send,
        test_venue_true_book,
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
        raise SystemExit(1)
    print("ok")


if __name__ == "__main__":
    main()
