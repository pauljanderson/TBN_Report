"""Same-direction Kalshi double is not a lock. No network. No secrets."""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import kalshi_same_direction as ksd  # noqa: E402
import kalshi_venue_kitchen_check as check  # noqa: E402
import live_lock_orders  # noqa: E402
from test_live_lock_orders import Scan, _pair  # noqa: E402

GIM = "KXATPCHALLENGERMATCH-26NOV01GIMPEN-GIM"
PEN = "KXATPCHALLENGERMATCH-26NOV01GIMPEN-PEN"
TAG = "KXWTAMATCH-26NOV01TAGDAR-TAG"
DAR = "KXWTAMATCH-26NOV01TAGDAR-DAR"


def test_event_prefix_and_complementary():
    assert ksd.kalshi_event_prefix(GIM) == "KXATPCHALLENGERMATCH-26NOV01GIMPEN"
    assert ksd.kalshi_market_code(GIM) == "GIM"
    assert ksd.complementary_kalshi_markets(GIM, PEN)
    assert not ksd.complementary_kalshi_markets(GIM, GIM)
    assert not ksd.complementary_kalshi_markets(GIM, TAG)


def test_yes_a_no_b_is_same_direction_double():
    yes = {"instrument": GIM, "outcome": "yes"}
    no = {"instrument": PEN, "outcome": "no"}
    assert ksd.is_same_direction_kalshi_double(yes, no)
    assert "same-direction" in ksd.same_direction_reason(yes, no)
    # Dual-Yes (Strategy B) is intentional, not this failure class.
    assert not ksd.is_same_direction_kalshi_double(
        {"instrument": GIM, "outcome": "yes"},
        {"instrument": PEN, "outcome": "yes"},
    )
    # True lock: Yes+No same ticker.
    assert not ksd.is_same_direction_kalshi_double(
        {"instrument": GIM, "outcome": "yes"},
        {"instrument": GIM, "outcome": "no"},
    )


def test_qualifies_blocks_complementary_kalshi_yes_no():
    cand = _pair(
        market_type="moneyline",
        side="Sebastian Gima",
        number="",
        yes_venue="kalshi",
        no_venue="kalshi",
        yes_price="0.41",
        no_price="0.41",
        yes_size="1",
        no_size="1",
        kalshi_ticker=GIM,
        kalshi_yes_ticker=GIM,
        kalshi_no_ticker=PEN,
        gemini_symbol="",
    )
    ok, why = live_lock_orders.qualifies(Scan(), cand, "Gima vs Peniston", {})
    assert ok is False
    assert "same-direction" in why


def test_true_same_ticker_kalshi_yes_no_still_ok_on_direction_gate():
    cand = _pair(
        market_type="moneyline",
        side="Sebastian Gima",
        yes_venue="kalshi",
        no_venue="gemini",
        yes_price="0.40",
        no_price="0.53",
        kalshi_ticker=GIM,
        gemini_symbol="GEMI-GIM",
    )
    bad, why = __import__("kalshi_same_direction").candidate_is_same_direction_double(cand)
    assert bad is False
    assert why == ""


def test_leg_spec_uses_per_outcome_kalshi_ticker():
    cand = _pair(
        yes_venue="kalshi",
        no_venue="kalshi",
        kalshi_yes_ticker=GIM,
        kalshi_no_ticker=PEN,
        kalshi_ticker=GIM,
    )
    yes = live_lock_orders._leg_spec(cand, "yes")
    no = live_lock_orders._leg_spec(cand, "no")
    assert yes is not None and no is not None
    assert yes["instrument"] == GIM
    assert no["instrument"] == PEN
    bad, _why = ksd.legs_are_same_direction_double([yes, no])
    assert bad is True


def test_settlement_pnl_cents_and_infer():
    # revenue 0, held Yes, market_result no → full loss of cost+fee
    lost = {
        "ticker": GIM,
        "market_result": "no",
        "yes_count_fp": "1.00",
        "no_count_fp": "0.00",
        "yes_total_cost_dollars": "0.410000",
        "no_total_cost_dollars": "0.000000",
        "revenue": 0,
        "fee_cost": "0.017000",
    }
    assert ksd.settlement_pnl_usd(lost) == Decimal("-0.43")
    # revenue 100 cents = $1 win
    won = {
        "ticker": DAR,
        "market_result": "yes",
        "yes_count_fp": "1.00",
        "no_count_fp": "0.00",
        "yes_total_cost_dollars": "0.140000",
        "no_total_cost_dollars": "0.000000",
        "revenue": 100,
        "fee_cost": "0.008500",
    }
    assert ksd.settlement_pnl_usd(won) == Decimal("0.85")


def test_find_stacks_from_gimpen_settlements():
    rows = [
        {
            "ticker": GIM,
            "market_result": "no",
            "yes_count_fp": "1.00",
            "no_count_fp": "0.00",
        },
        {
            "ticker": PEN,
            "market_result": "yes",
            "yes_count_fp": "0.00",
            "no_count_fp": "1.00",
        },
    ]
    found = ksd.find_same_direction_stacks(rows)
    assert len(found) == 1
    assert "GIMPEN" in found[0]["event"]


def test_venue_kitchen_check_flags_gap_and_stack():
    pack = {
        "written_at": "2026-11-01T09:21:37-05:00",
        "days": 3,
        "settlements": {
            "settlements": [
                {
                    "ticker": GIM,
                    "settled_time": "2026-11-01T14:12:23Z",
                    "market_result": "no",
                    "yes_count_fp": "1.00",
                    "no_count_fp": "0.00",
                    "yes_total_cost_dollars": "0.410000",
                    "no_total_cost_dollars": "0.000000",
                    "revenue": 0,
                    "fee_cost": "0.017000",
                },
                {
                    "ticker": PEN,
                    "settled_time": "2026-11-01T14:12:23Z",
                    "market_result": "yes",
                    "yes_count_fp": "0.00",
                    "no_count_fp": "1.00",
                    "yes_total_cost_dollars": "0.000000",
                    "no_total_cost_dollars": "0.410000",
                    "revenue": 0,
                    "fee_cost": "0.017000",
                },
            ]
        },
        "fills": {"fills": []},
    }
    report = check.analyze(pack, kitchen_pnl=Decimal("-0.10"), tolerance=Decimal("0.50"))
    assert report["ok"] is False
    assert report["gap_over_tolerance"] is True
    assert report["same_direction_stacks"]
    assert "GIMPEN" in report["same_direction_stacks"][0]["event"]


def test_same_settlement_candidate_restored():
    ok, why = live_lock_orders.same_settlement_candidate(
        {
            "market_type": "total",
            "kalshi_ticker": "KXNFLTEAMTOTAL-26NOV01TENCIN-CIN30",
        }
    )
    assert ok is False
    assert "settlement" in why


def test_settle_reconcile_warns_gimpen_class():
    import live_pm_settle_reconcile as rec

    rows = [
        {"venue": "kalshi", "instrument": GIM, "outcome": "yes", "side": "yes"},
        {"venue": "kalshi", "instrument": PEN, "outcome": "no", "side": "no"},
    ]
    found = rec.warn_same_direction_kalshi(rows)
    assert found
    assert "GIMPEN" in found[0]["event"]


if __name__ == "__main__":
    test_event_prefix_and_complementary()
    test_yes_a_no_b_is_same_direction_double()
    test_qualifies_blocks_complementary_kalshi_yes_no()
    test_true_same_ticker_kalshi_yes_no_still_ok_on_direction_gate()
    test_leg_spec_uses_per_outcome_kalshi_ticker()
    test_settlement_pnl_cents_and_infer()
    test_find_stacks_from_gimpen_settlements()
    test_venue_kitchen_check_flags_gap_and_stack()
    test_same_settlement_candidate_restored()
    test_settle_reconcile_warns_gimpen_class()
    print("test_kalshi_same_direction ok")
