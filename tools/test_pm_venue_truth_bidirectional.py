"""Post-send confirm + same-direction scoring + venue→tape ingest. No network."""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import kalshi_same_direction as ksd  # noqa: E402
import live_lock_orders  # noqa: E402
import pm_venue_miss_ingest as miss  # noqa: E402
import venue_fill_confirm  # noqa: E402
import write_orders_performance as w  # noqa: E402

GIM = "KXATPCHALLENGERMATCH-26NOV01GIMPEN-GIM"
PEN = "KXATPCHALLENGERMATCH-26NOV01GIMPEN-PEN"


def test_filled_contracts_prefers_confirm_overlay():
    payload = {
        "order_id": "abc",
        "fill_count": "0.00",
        "status": "executed",
        venue_fill_confirm.PAYLOAD_KEY: {
            "known": True,
            "qty": "1",
            "avg_price": "0.41",
            "note": "kalshi fills confirm 1",
            "tape_qty": "0",
        },
    }
    # Old thin walker would treat status=executed as qty 1 even with fill_count 0,
    # and ignore confirm. Confirm-aware path must use overlay qty.
    assert live_lock_orders.filled_contracts(payload) == Decimal("1")
    empty = {
        "order_id": "abc",
        "status": "filled",
        venue_fill_confirm.PAYLOAD_KEY: {
            "known": True,
            "qty": "0",
            "note": "confirm empty",
            "tape_qty": "0",
        },
    }
    assert live_lock_orders.filled_contracts(empty) == Decimal("0")


def test_with_venue_confirm_attaches_overlay():
    spec = {
        "venue": "kalshi",
        "instrument": GIM,
        "outcome": "yes",
        "pay": "0.41",
        "body": {"ticker": GIM},
    }
    tape = {"order_id": "oid-1", "fill_count": "0.00", "status": "executed"}

    def fake_confirm(venue, payload=None, spec=None, tape_qty=None, **kwargs):
        return {
            "known": True,
            "qty": "1",
            "avg_price": "0.41",
            "house_cash": "0.41",
            "note": "kalshi fills GET 1 @ 0.41",
            "tape_qty": str(tape_qty or 0),
            "venue": venue,
        }

    with patch.object(venue_fill_confirm, "confirm_order", side_effect=fake_confirm):
        out = live_lock_orders._with_venue_confirm(spec, 201, tape)
    assert live_lock_orders.venue_confirm_known(out)
    assert live_lock_orders.filled_contracts(out) == Decimal("1")
    assert live_lock_orders._actual_fill_cash(spec, out) == Decimal("0.41")


def test_score_cluster_same_direction_not_lock_realized():
    legs = [
        {
            "venue": "kalshi",
            "instrument": GIM,
            "side": "yes",
            "qty": 1,
            "cash": "0.41",
            "fee": "0.017",
            "settle_result": "no",
            "player": "Gima",
        },
        {
            "venue": "kalshi",
            "instrument": PEN,
            "side": "no",
            "qty": 1,
            "cash": "0.41",
            "fee": "0.017",
            "settle_result": "yes",
            "player": "Peniston",
        },
    ]
    assert ksd.legs_are_same_direction_double(legs)[0] is True
    cluster = {
        "game": "Gima vs Peniston",
        "fill_legs": legs,
        "legs": legs,
        "complementary": True,  # wrongly labeled — must be cleared
        "intent": w.INTENT_FULL_LOCK,
        "flatten_filled": False,
    }
    settlements = [
        {"ticker": GIM, "result": "no", "venue": "kalshi", "status": "settled"},
        {"ticker": PEN, "result": "yes", "venue": "kalshi", "status": "settled"},
    ]
    scored = w.score_cluster(cluster, settlements, venue_index={}, market_index={})
    assert scored.get("complementary") is False or cluster.get("complementary") is False
    assert cluster.get("same_direction_double") is True
    # Directional: both legs lose ≈ -0.41-0.017 each ≈ -0.854
    realized = Decimal(str(scored.get("realized") or cluster.get("realized") or 0))
    # score_cluster returns the cluster dict mutated
    realized = Decimal(str(cluster.get("realized") or 0))
    assert realized <= Decimal("-0.80"), realized
    assert realized >= Decimal("-0.90"), realized
    # Must NOT be the false lock_realized (+0.15-ish).
    assert realized < 0


def test_miss_ingest_adds_unbooked_settlement():
    store: dict = {}
    rows = [
        {
            "ticker": GIM,
            "market_result": "no",
            "yes_count_fp": "1.00",
            "no_count_fp": "0.00",
            "yes_total_cost_dollars": "0.410000",
            "no_total_cost_dollars": "0.000000",
            "revenue": 0,
            "fee_cost": "0.017000",
            "settled_time": "2026-11-01T14:12:23Z",
        }
    ]
    report = miss.ingest_kalshi_settlements(store, rows, persist=False)
    assert report["added"] >= 1
    assert any(str(v.get("instrument") or "") == GIM for v in store.values())
    # Second pass should skip duplicates.
    again = miss.ingest_kalshi_settlements(store, rows, persist=False)
    assert again["added"] == 0


def test_public_helpers_exist_for_page_rebuild():
    assert callable(live_lock_orders.public_venue_note)
    assert callable(live_lock_orders._scrub_public_text)
    assert callable(live_lock_orders._actual_fill_cash)
    assert callable(live_lock_orders.leg_fee)
    assert callable(live_lock_orders._post_same_limit)
    note = live_lock_orders.public_venue_note({"message": "ok"}, "")
    assert "ok" in note


if __name__ == "__main__":
    test_filled_contracts_prefers_confirm_overlay()
    test_with_venue_confirm_attaches_overlay()
    test_score_cluster_same_direction_not_lock_realized()
    test_miss_ingest_adds_unbooked_settlement()
    test_public_helpers_exist_for_page_rebuild()
    print("test_pm_venue_truth_bidirectional ok")
