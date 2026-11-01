"""Synthetic tests for NFL T0 spread buckets.

Does not place orders. Does not start live_strategy_b.py. Does not print secrets.
Does not write sports_queue. Does not change live D.
"""
from __future__ import annotations

from decimal import Decimal

from nfl_t0_spread_buckets_20261025 import (
    bucket_of,
    in_d_band,
    is_nfl,
    is_unique_fav,
    pick_one_per_game,
    pick_primary_line,
    sample_note,
)
from t0_fav_lt90_baseline_20261024 import fav_yes_pnl
from write_t0_band_from_stay_above import documented_leg_fee


def test_buckets_match_living_dashboard():
    assert bucket_of(0.91) == ">90"
    assert bucket_of(0.90) == "80-89"
    assert bucket_of(0.80) == "80-89"
    assert bucket_of(0.79) == "70-79"
    assert bucket_of(0.60) == "60-69"
    assert bucket_of(0.59) == "50-59"
    assert bucket_of(0.501) == "50-59"
    assert bucket_of(0.50) == "50-50"


def test_d_band_excludes_edges():
    assert in_d_band(0.50) is False
    assert in_d_band(0.90) is False
    assert in_d_band(0.501) is True
    assert in_d_band(0.899) is True
    assert is_unique_fav(0.50) is False
    assert is_unique_fav(0.501) is True


def test_nfl_sport_aliases():
    assert is_nfl("pro football")
    assert is_nfl("NFL")
    assert not is_nfl("college football")
    assert not is_nfl("tennis")


def test_pick_one_line_closest_to_50():
    books = [
        {"game_n": "dalphi", "number": "7.5", "t0_fav": 0.72, "venue": "Kalshi"},
        {"game_n": "dalphi", "number": "3.5", "t0_fav": 0.58, "venue": "Kalshi"},
        {"game_n": "dalphi", "number": "10.5", "t0_fav": 0.81, "venue": "Gemini"},
        {"game_n": "nygwas", "number": "2.5", "t0_fav": 0.91, "venue": "Kalshi"},
    ]
    picked = pick_one_per_game(books)
    by_game = {row["game_n"]: row for row in picked}
    assert by_game["dalphi"]["number"] == "3.5"
    assert by_game["nygwas"]["number"] == "2.5"
    assert by_game["dalphi"]["_n_lines"] == 3


def test_pick_primary_cheapest_documented_venue():
    books = [
        {"game_n": "dalphi", "number": "3.5", "t0_fav": 0.62, "venue": "Kalshi"},
        {"game_n": "dalphi", "number": "3.5", "t0_fav": 0.58, "venue": "Gemini"},
    ]
    picked = pick_primary_line(books)
    assert len(picked) == 1
    assert picked[0]["venue"] == "Gemini"
    assert picked[0]["t0_fav"] == 0.58


def test_buy_spread_fav_pnl_includes_fee():
    ask = Decimal("0.72")
    fee = documented_leg_fee("kalshi", ask)
    assert fee is not None and fee > 0
    assert fav_yes_pnl(ask, fee, won=True) == Decimal("1") - ask - fee
    assert fav_yes_pnl(ask, fee, won=False) == -ask - fee


def test_sample_note_says_n_zero():
    assert "N=0" in sample_note(0)
    assert "tiny" in sample_note(3)


if __name__ == "__main__":
    test_buckets_match_living_dashboard()
    test_d_band_excludes_edges()
    test_nfl_sport_aliases()
    test_pick_one_line_closest_to_50()
    test_pick_primary_cheapest_documented_venue()
    test_buy_spread_fav_pnl_includes_fee()
    test_sample_note_says_n_zero()
    print("ok")
