"""All-platform venue-vs-kitchen check. No network. No secrets."""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import pm_venue_kitchen_check as check  # noqa: E402

GIM = "KXATPCHALLENGERMATCH-26NOV01GIMPEN-GIM"
PEN = "KXATPCHALLENGERMATCH-26NOV01GIMPEN-PEN"

SAMPLE_HTML = """
<html><body>
<h2>By venue</h2>
<table class="sortable">
<thead><tr>
<th>Venue</th><th>Filled contracts</th><th>Fees $</th>
<th>Realized $ (share)</th><th>Open cost $</th><th>Sends</th><th>Empty 200/201</th>
</tr></thead>
<tbody>
<tr><td>gemini</td><td class="num">3</td><td>$0.03</td><td>$0.32</td><td>$0.00</td><td>1</td><td>0</td></tr>
<tr><td>kalshi</td><td class="num">143</td><td>$1.92</td><td>−$1.01</td><td>$2.35</td><td>1</td><td>0</td></tr>
<tr><td>novig</td><td class="num">9</td><td>$0.03</td><td>−$0.08</td><td>$1.73</td><td>1</td><td>0</td></tr>
<tr><td>polymarket</td><td class="num">318</td><td>$4.49</td><td>$8.92</td><td>$2.92</td><td>1</td><td>0</td></tr>
</tbody></table>
<h2>Still open</h2>
</body></html>
"""


def test_parse_kitchen_by_venue():
    got = check.parse_kitchen_by_venue(SAMPLE_HTML)
    assert got["kalshi"] == Decimal("-1.01")
    assert got["polymarket"] == Decimal("8.92")
    assert got["gemini"] == Decimal("0.32")
    assert got["novig"] == Decimal("-0.08")


def test_settled_pnl_by_venue():
    store = {
        "a": {"venue": "kalshi", "status": "lose", "pnl": "-0.50"},
        "b": {"venue": "kalshi", "status": "win", "pnl": "0.20"},
        "c": {"venue": "polymarket", "status": "win", "pnl": "1.50"},
        "d": {"venue": "gemini", "status": "win", "pnl": "0.32"},
        "e": {"venue": "novig", "status": "lose", "pnl": "-0.08"},
    }
    got = check.settled_pnl_by_venue(store)
    assert got["kalshi"] == Decimal("-0.30")
    assert got["polymarket"] == Decimal("1.50")
    # settled_pnl_store.save envelope must unwrap — otherwise every venue reads $0.
    wrapped = {"written_at": "2026-11-02T18:00:00-05:00", "n": 5, "orders": store}
    got2 = check.settled_pnl_by_venue(wrapped)
    assert got2["polymarket"] == Decimal("1.50")
    assert got2["kalshi"] == Decimal("-0.30")


def test_all_platform_attribution_gap_and_require_dumps():
    kitchen = check.parse_kitchen_by_venue(SAMPLE_HTML)
    settled = {
        "kalshi": Decimal("-1.01"),
        "polymarket": Decimal("1.00"),  # big miss vs kitchen 8.92
        "gemini": Decimal("0.32"),
        "novig": Decimal("-0.08"),
    }
    report = check.analyze(
        kitchen_by_venue=kitchen,
        settled_by_venue=settled,
        tolerance=Decimal("0.50"),
        require_all_dumps=True,
        present_dumps={"kalshi"},
    )
    assert report["ok"] is False
    assert "polymarket" in report["attribution_gap_venues"]
    assert set(report["missing_dumps"]) == {"polymarket", "gemini", "novig"}


def test_kalshi_historical_stack_warns_open_stack_fails():
    pack = {
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
        "positions": {"body": {"market_positions": []}},
    }
    kitchen = {
        "kalshi": Decimal("-1.01"),
        "polymarket": Decimal("8.92"),
        "gemini": Decimal("0.32"),
        "novig": Decimal("-0.08"),
    }
    settled = dict(kitchen)
    # Historical only (no open positions) → warn, do not fail the gate alone.
    hist = check.analyze(
        kitchen_by_venue=kitchen,
        settled_by_venue=settled,
        kalshi_pack=pack,
        venue_packs={"kalshi": pack},
        tolerance=Decimal("0.50"),
    )
    assert hist["historical_same_direction_stacks"]
    assert hist["open_same_direction_stacks"] == []
    assert hist["ok"] is True
    # Same stack still on the open book → FAIL.
    open_pack = dict(pack)
    open_pack["positions"] = {
        "body": {
            "market_positions": [
                {"ticker": GIM, "position_fp": "1.00"},
                {"ticker": PEN, "position_fp": "-1.00"},
            ]
        }
    }
    live = check.analyze(
        kitchen_by_venue=kitchen,
        settled_by_venue=settled,
        kalshi_pack=open_pack,
        venue_packs={"kalshi": open_pack},
        tolerance=Decimal("0.50"),
    )
    assert live["open_same_direction_stacks"]
    assert live["ok"] is False


def test_ok_when_all_match():
    kitchen = check.parse_kitchen_by_venue(SAMPLE_HTML)
    report = check.analyze(
        kitchen_by_venue=kitchen,
        settled_by_venue=dict(kitchen),
        require_all_dumps=True,
        present_dumps={"kalshi", "polymarket", "gemini", "novig"},
        tolerance=Decimal("0.50"),
    )
    assert report["ok"] is True
    assert report["attribution_gap_venues"] == []
    assert report["missing_dumps"] == []


def test_polymarket_open_same_direction_stack_fails_kitchen_gate():
    """Open Poly twin Yes-A + No-B must fail; fill-history-only warns."""
    poly_a = "aec-atp-gimpen-2026-11-01-gim"
    poly_b = "aec-atp-gimpen-2026-11-01-pen"
    kitchen = {
        "kalshi": Decimal("0"),
        "polymarket": Decimal("0"),
        "gemini": Decimal("0"),
        "novig": Decimal("0"),
    }
    hist_packs = {
        "polymarket": {
            "fills": {
                "fills": [
                    {"ticker": poly_a, "outcome": "yes", "venue": "polymarket"},
                    {"ticker": poly_b, "outcome": "no", "venue": "polymarket"},
                ]
            }
        }
    }
    hist = check.analyze(
        kitchen_by_venue=kitchen,
        settled_by_venue=dict(kitchen),
        venue_packs=hist_packs,
        present_dumps={"polymarket"},
        tolerance=Decimal("0.50"),
    )
    assert hist["same_direction_stacks"]
    assert hist["ok"] is True
    open_packs = {
        "polymarket": {
            "fills": hist_packs["polymarket"]["fills"],
            "positions": {
                "positions": {
                    poly_a: {"netPositionDecimal": "1"},
                    poly_b: {"netPositionDecimal": "1"},
                }
            },
        }
    }
    live = check.analyze(
        kitchen_by_venue=kitchen,
        settled_by_venue=dict(kitchen),
        venue_packs=open_packs,
        present_dumps={"polymarket"},
        tolerance=Decimal("0.50"),
    )
    assert live["open_same_direction_stacks"]
    assert live["ok"] is False


if __name__ == "__main__":
    test_parse_kitchen_by_venue()
    test_settled_pnl_by_venue()
    test_all_platform_attribution_gap_and_require_dumps()
    test_kalshi_historical_stack_warns_open_stack_fails()
    test_ok_when_all_match()
    test_polymarket_open_same_direction_stack_fails_kitchen_gate()
    print("test_pm_venue_kitchen_check ok")
