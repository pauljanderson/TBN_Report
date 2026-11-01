"""Local settled_pnl.json: price filled tickets, do not invent Novig fees."""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import settled_pnl_store as store
import write_orders_performance as w


def test_upsert_prices_kalshi_yes():
    blob = {}
    leg = {
        "order_id": "oid-yes",
        "venue": "kalshi",
        "instrument": "KX-TEST-YES",
        "side": "yes",
        "qty": "1",
        "cash": "0.4600",
        "fee": "0.0174",
    }
    row = store.upsert_leg(leg, result="yes", source="test", store=blob, game="Yas vs Vol")
    assert row is not None
    assert row["status"] == "win"
    assert Decimal(row["pnl"]) > 0
    assert blob["oid-yes"]["wire"] == "0.4600"
    assert blob["oid-yes"]["source"] == "test"


def test_poly_commission_zero_is_fee_zero():
    payload = {
        "order": {
            "id": "DAC6VQZG11M3",
            "commissionNotionalTotalCollected": {"value": "0.0000", "currency": "USD"},
        }
    }
    assert store.poly_fee_from_order(payload) == Decimal("0")
    assert store.poly_fee_from_order({"order": {}}) is None
    blob = {}
    leg = {
        "order_id": "DAC6VQZG11M3",
        "venue": "polymarket",
        "instrument": "aec-atp-omajas-taekim-2026-10-25",
        "side": "no",
        "qty": "1",
        "cash": "0.0700",
        "fee": "0.0000",
    }
    row = store.upsert_leg(leg, result="no", source="test", store=blob, game="Jasika vs Kim")
    assert row is not None
    assert row["fee"] == "0.0000"
    assert row["status"] == "win"
    assert Decimal(row["pnl"]) == Decimal("0.9300")


def test_novig_fee_unknown_not_zero():
    blob = {}
    leg = {
        "order_id": "novig-1",
        "venue": "novig",
        "instrument": "NOV-1",
        "side": "yes",
        "qty": "1",
        "cash": "0.40",
        "fee": None,
    }
    row = store.upsert_leg(leg, result="yes", source="test", store=blob)
    assert row is not None
    assert row["result"] == "yes"
    assert row["fee"] is None
    assert row["pnl"] is None
    assert row["after_fee"] == "fee unknown"
    status, pnl = store.apply_to_leg(leg, blob)
    assert status == "open"
    assert pnl is None


def test_postponed_kind_does_not_store():
    n = store.note_game_settled(kind="postponed", title="Rain vs Delay", instruments=[("kalshi", "KX-RAIN")])
    assert n == 0


def test_ticker_result_settlement_px_and_case():
    rows = [{"ticker": "aec-Hong-Wu", "settlementPx": "1", "venue": "Polymarket"}]
    assert w.ticker_result(rows, "AEC-HONG-WU") == "yes"
    rows2 = [{"ticker": "KX-ABC", "result": "NO"}]
    assert w.ticker_result(rows2, "kx-abc") == "no"


def test_restrict_uses_store_order_id():
    saved = store._CACHE
    store._CACHE = {
        "poly-1": {
            "order_id": "poly-1",
            "instrument": "aec-priced",
            "result": "yes",
            "status": "win",
            "pnl": "0.5100",
        }
    }
    cluster = {
        "game": "Priced vs Match",
        "fill_legs": [{
            "order_id": "poly-1",
            "venue": "polymarket",
            "instrument": "aec-priced",
            "qty": 1,
            "side": "yes",
            "cash": "0.48",
            "fee": "0.01",
        }],
        "n_fill_legs": 1,
        "realized": w.Decimal("0"),
        "status_unknown": True,
        "notes": [],
    }
    try:
        w.restrict_realized([cluster], [])
        assert cluster["status_unknown"] is False
        assert Decimal(str(cluster["realized"])) > 0
    finally:
        store._CACHE = saved


def test_persist_skips_postponed():
    blob_before = dict(store.load())
    cluster = {
        "game": "Llanes vs Rain",
        "postponed": True,
        "venue_paid": False,
        "void": False,
        "fill_legs": [{
            "order_id": "should-not-persist-postponed",
            "venue": "polymarket",
            "instrument": "aec-rain",
            "qty": 1,
            "side": "yes",
            "cash": "0.40",
            "fee": "0.01",
            "settle_result": "yes",
        }],
    }
    w.persist_settled_pnl([cluster], [], source="test")
    after = store.load()
    assert "should-not-persist-postponed" not in after
    store._CACHE = blob_before
    store.save(blob_before)


def test_flatten_net_two_pairs_pays_two_dollars():
    """Langmo 2026-11-01: T0 Yes+No + stack Yes+No flatten must not book −$1.13."""
    legs = [
        {"side": "yes", "qty": "1", "cash": "0.6400", "fee": "0.0200", "step": "b-t0"},
        {"side": "no", "qty": "1", "cash": "0.3300", "fee": "0.0200", "step": "b-t0"},
        {"side": "no", "qty": "1", "cash": "0.1300", "fee": "0.0100", "step": "b-t0"},
        {"side": "yes", "qty": "1", "cash": "0.9800", "fee": "0.0000", "step": "flatten"},
    ]
    # Old bug: min(qty)=1 − sum(costs)=2.13 → −1.13. True: 2 − 2.13 → −0.13.
    net = store.flatten_net_from_legs(legs)
    assert net is not None
    assert net == Decimal("-0.1300")
    assert store.flatten_matched_qty(legs) == Decimal("2")
    assert w.lock_realized(legs) == Decimal("-0.1300")


def test_flatten_net_one_pair_unchanged():
    legs = [
        {"side": "yes", "qty": "1", "cash": "0.6400", "fee": "0.0200"},
        {"side": "no", "qty": "1", "cash": "0.3300", "fee": "0.0200"},
    ]
    net = store.flatten_net_from_legs(legs)
    assert net == Decimal("1") - Decimal("0.6600") - Decimal("0.3500")
    assert net == Decimal("-0.0100")


def main() -> None:
    test_upsert_prices_kalshi_yes()
    test_poly_commission_zero_is_fee_zero()
    test_novig_fee_unknown_not_zero()
    test_postponed_kind_does_not_store()
    test_ticker_result_settlement_px_and_case()
    test_restrict_uses_store_order_id()
    test_persist_skips_postponed()
    test_flatten_net_two_pairs_pays_two_dollars()
    test_flatten_net_one_pair_unchanged()
    print("test_settled_pnl_store ok")


if __name__ == "__main__":
    main()
