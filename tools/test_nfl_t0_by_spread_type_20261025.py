"""Synthetic tests for NFL T0-by-type research page.

Does not place orders. Does not start live_strategy_b.py. Does not print secrets.
Does not write the sibling all-tracked spread HTML. Does not change live D.
"""
from __future__ import annotations

from pathlib import Path

from nfl_t0_by_spread_type_20261025 import (
    PAGE,
    TRACKED_TYPES,
    team_total_number,
)
from price_memory import market_type_from
from live_game_pollers import expand_sibling_tickers
from prediction_systems import pick_spread_line
from decimal import Decimal


ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "tools" / "nfl_t0_by_spread_type_20261025.py"
SIBLING = (
    ROOT / "drive" / "paul_experiments"
    / "prediction_market_arb_exhaustive_20261017"
    / "nfl_t0_spread_buckets_all_tracked_20261025.html"
)


def test_page_is_types_not_all_tracked():
    assert PAGE.name == "nfl_t0_by_spread_type_20261025.html"
    assert PAGE.name != SIBLING.name
    text = GEN.read_text(encoding="utf-8")
    assert "nfl_t0_spread_buckets_all_tracked_20261025.html" in text
    assert "Did not overwrite" in text or "does not write the sibling" in text.lower()
    assert "orders.jsonl" in text
    assert "Does not read orders.jsonl" in text or "Did not read fills" in text
    assert "HOLD" in text
    assert "KXNFLTEAMTOTAL" in text
    assert "What you asked" in text
    assert "Sunday Oct 25 first set" in text
    assert "Type A" in text
    assert "Did not turn D NFL on" in text
    assert "N=0 settled" in text
    for kind in TRACKED_TYPES:
        assert kind in text


def test_team_total_number_keeps_teams_apart():
    assert team_total_number("chicago over", "24.5") == "chicago:24.5"
    assert team_total_number("new england under", "20.5") == "new england:20.5"
    assert team_total_number("over", "24.5") == "24.5"


def test_d_still_one_spread_when_totals_qualify():
    lines = [
        {"kind": "spread", "number": "3.5", "two_sided": True, "fav_ask": Decimal("0.62")},
        {"kind": "spread", "number": "7.5", "two_sided": True, "fav_ask": Decimal("0.71")},
        {"kind": "total", "number": "47.5", "two_sided": True, "fav_ask": Decimal("0.55")},
        {"kind": "team_total", "number": "24.5", "two_sided": True, "fav_ask": Decimal("0.58")},
    ]
    picked = pick_spread_line(lines, all_lines=True)
    assert len(picked) == 1
    assert picked[0]["kind"] == "spread"
    assert picked[0]["number"] == "3.5"


def test_siblings_add_team_total_keep_ml_spread():
    k, g = expand_sibling_tickers(
        ["KXNFLGAME-26OCT25KCLV"],
        ["NFL-2610251700-KC-LV-M"],
        "pro football",
    )
    assert "KXNFLGAME-26OCT25KCLV" in k
    assert "KXNFLSPREAD-26OCT25KCLV" in k
    assert "KXNFLTOTAL-26OCT25KCLV" in k
    assert "KXNFLTEAMTOTAL-26OCT25KCLV" in k
    assert any(t.endswith("-M") for t in g)
    assert any(t.endswith("-S") for t in g)
    assert any(t.endswith("-T") and not t.endswith("-TT") for t in g)
    assert any(t.endswith("-TT") for t in g)
    assert market_type_from("KXNFLTEAMTOTAL-26OCT25KCLV") == "team_total"
    assert market_type_from("KXNFLTOTAL-26OCT25KCLV") == "total"


if __name__ == "__main__":
    test_page_is_types_not_all_tracked()
    test_team_total_number_keeps_teams_apart()
    test_d_still_one_spread_when_totals_qualify()
    test_siblings_add_team_total_keep_ml_spread()
    print("ok")
