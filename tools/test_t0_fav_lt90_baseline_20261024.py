"""Synthetic tests for T0-favorite <90¢ baseline and stay-above completeness.

Does not place orders. Does not start Strategy B. Does not print secrets.
"""
from __future__ import annotations

from decimal import Decimal

from t0_all_games_stats import analyze_favorite_path
from t0_fav_lt90_baseline_20261024 import fav_yes_pnl
from write_t0_band_from_stay_above import documented_leg_fee, score_pair

T0_TS = 1_000


def test_favorite_stays_above_then_settles_win():
    ticks = [(T0_TS + 60, 0.72), (T0_TS + 120, 0.80), (T0_TS + 180, 0.96)]
    got = analyze_favorite_path(0.70, T0_TS, ticks, T0_TS + 240, fav_won=True)
    assert got["stay_above"] is True
    assert got["dipped"] is False
    pair = {
        "t0_a": 0.70,
        "t0_b": 0.32,
        "t0_ts": T0_TS,
        "yes_a": [(T0_TS, 0.70)] + ticks,
        "yes_b": [(T0_TS, 0.32), (T0_TS + 180, 0.04)],
        "side_a": "Fav",
        "side_b": "Dog",
        "winner": "a",
        "settled": True,
        "sport": "soccer",
        "game": "Fav vs Dog",
        "venue": "Kalshi",
        "market_type": "moneyline",
        "actual_source": "occurrence",
    }
    scored = score_pair(pair)
    assert scored is not None
    assert scored["stay_above"] is True
    assert scored["fav_won"] is True


def test_last_tick_080_lose_is_not_stay_above():
    ticks = [(T0_TS + 30, 0.82), (T0_TS + 90, 0.80)]
    got = analyze_favorite_path(0.85, T0_TS, ticks, T0_TS + 120, fav_won=False)
    assert got["stay_above"] is False
    assert got["path_status"] == "path_incomplete"
    assert got["missing_crash"] is True
    pair = {
        "t0_a": 0.80,
        "t0_b": 0.28,
        "t0_ts": T0_TS,
        "yes_a": [(T0_TS, 0.80), (T0_TS + 90, 0.80)],
        "yes_b": [(T0_TS, 0.28), (T0_TS + 90, 0.22)],
        "side_a": "Fav",
        "side_b": "Dog",
        "winner": "b",
        "settled": True,
        "sport": "college football",
        "game": "Fav vs Dog",
        "venue": "Kalshi",
        "market_type": "spread",
        "actual_source": "occurrence",
    }
    scored = score_pair(pair)
    assert scored is not None
    assert scored["stay_above"] is False
    assert scored["fav_won"] is False
    assert scored["missing_crash"] is True


def test_buy_080_win_pnl_is_one_minus_ask_minus_fee():
    ask = Decimal("0.80")
    fee = documented_leg_fee("kalshi", ask)
    assert fee is not None and fee > 0
    pnl = fav_yes_pnl(ask, fee, won=True)
    assert pnl == Decimal("1") - ask - fee


def test_buy_080_lose_pnl_is_minus_ask_minus_fee():
    ask = Decimal("0.80")
    fee = documented_leg_fee("kalshi", ask)
    assert fee is not None and fee > 0
    pnl = fav_yes_pnl(ask, fee, won=False)
    assert pnl == -ask - fee


if __name__ == "__main__":
    test_favorite_stays_above_then_settles_win()
    test_last_tick_080_lose_is_not_stay_above()
    test_buy_080_win_pnl_is_one_minus_ask_minus_fee()
    test_buy_080_lose_pnl_is_minus_ask_minus_fee()
    print("ok")
