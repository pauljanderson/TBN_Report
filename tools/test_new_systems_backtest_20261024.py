"""Synthetic tests for new-system proposal backtest helpers.

Does not place orders. Does not start Strategy B. Does not print secrets.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from new_systems_backtest_20261024 import (
    directional_trades,
    first_cross_from_below,
    gtc_policy_trades,
    in_open_band,
    in_skip_coin_band,
    judge,
    pick_one_closest_50,
    tennis_dog_cross_trade,
    tennis_dog_t0_trade,
)
from t0_fav_lt90_baseline_20261024 import fav_yes_pnl
from write_t0_band_from_stay_above import documented_leg_fee

ET = ZoneInfo("America/New_York")
T0 = 1_700_000_000


def _book(**kwargs) -> dict:
    base = {
        "sport": "soccer",
        "kind": "moneyline",
        "venue": "Kalshi",
        "game": "A vs B",
        "game_n": "avsb",
        "number": "",
        "t0_a": 0.62,
        "t0_b": 0.40,
        "t0_fav": 0.62,
        "t0_dog": 0.40,
        "t0_ts": T0,
        "end_ts": T0 + 3600,
        "fav": "a",
        "dog": "b",
        "winner": "a",
        "fav_won": True,
        "settled": True,
        "void": False,
        "two_sided": True,
        "skip": "",
        "side_a": "A",
        "side_b": "B",
        "yes_a": [(T0, 0.62), (T0 + 60, 0.70)],
        "yes_b": [(T0, 0.40), (T0 + 60, 0.32)],
        "_grain": "match",
    }
    base.update(kwargs)
    return base


def test_bands():
    assert in_open_band(0.51)
    assert in_open_band(0.89)
    assert not in_open_band(0.50)
    assert not in_open_band(0.90)
    assert in_skip_coin_band(0.70)
    assert in_skip_coin_band(0.89)
    assert not in_skip_coin_band(0.69)
    assert not in_skip_coin_band(0.90)


def test_fav_yes_pnl_matches_house_fee():
    ask = Decimal("0.80")
    fee = documented_leg_fee("kalshi", ask)
    assert fee is not None and fee > 0
    assert fav_yes_pnl(ask, fee, won=True) == Decimal("1") - ask - fee
    assert fav_yes_pnl(ask, fee, won=False) == -ask - fee


def test_pick_one_total_closest_to_50():
    books = [
        _book(kind="total", number="45.5", t0_fav=0.72, game_n="g1"),
        _book(kind="total", number="47.5", t0_fav=0.55, game_n="g1"),
        _book(kind="total", number="41.5", t0_fav=0.80, game_n="g2"),
    ]
    picked = pick_one_closest_50(books)
    by_game = {b["game_n"]: b["number"] for b in picked}
    assert by_game["g1"] == "47.5"
    assert by_game["g2"] == "41.5"
    assert len(picked) == 2


def test_c_band_skips_ninety():
    books = [_book(t0_fav=0.91, fav_won=True), _book(t0_fav=0.72, fav_won=True, game_n="other")]
    always = directional_trades(books, "always", band="always")
    band = directional_trades(books, "c_band", band="c_band")
    assert len(always) == 2
    assert len(band) == 1
    assert band[0]["t0_fav"] == 0.72


def test_dog_cross_fills_first_from_below_and_skips_when_none():
    hit = _book(
        sport="tennis",
        kind="moneyline",
        fav="a",
        dog="b",
        winner="b",
        t0_fav=0.62,
        t0_dog=0.40,
        t0_a=0.62,
        t0_b=0.40,
        yes_b=[(T0, 0.40), (T0 + 30, 0.48), (T0 + 40, 0.53), (T0 + 80, 0.70)],
    )
    miss = _book(
        sport="tennis",
        kind="moneyline",
        game_n="no-cross",
        fav="a",
        dog="b",
        winner="a",
        t0_fav=0.70,
        t0_dog=0.32,
        t0_a=0.70,
        t0_b=0.32,
        yes_b=[(T0, 0.32), (T0 + 30, 0.28), (T0 + 90, 0.22)],
    )
    crossed = tennis_dog_cross_trade(hit)
    skipped = tennis_dog_cross_trade(miss)
    t0_dog = tennis_dog_t0_trade(hit)
    assert skipped is None
    assert crossed is not None
    assert abs(crossed["ask"] - 0.53) < 1e-12
    assert crossed["won"] is True
    assert t0_dog is not None
    assert abs(t0_dog["ask"] - 0.40) < 1e-12


def test_trungelliti_rewind_waits_for_reset():
    ticks = [(T0 + 10, 0.56), (T0 + 20, 0.49), (T0 + 30, 0.52)]
    got = first_cross_from_below(ticks, T0, T0 + 100, 0.56)
    assert got is not None
    assert abs(got["px"] - 0.52) < 1e-12
    assert got["t0_already_above"] is True


def test_gtc_policy_uses_hit_pnl_else_actual():
    start = datetime(2026, 10, 20, 12, 0, tzinfo=ET)
    hit = {
        "game_status": "settled",
        "gtc_hit": True,
        "gtc_pnl": Decimal("0.05"),
        "legal_lock": True,
        "sport": "tennis",
        "game": "Hit",
        "start": start,
        "window_until": start,
        "fill": {"venue": "kalshi"},
        "flatten_filled": True,
        "flatten_pnl": Decimal("-0.06"),
        "hold": {},
        "watch": {},
    }
    miss = {
        "game_status": "settled",
        "gtc_hit": False,
        "gtc_pnl": None,
        "legal_lock": True,
        "sport": "tennis",
        "game": "Miss",
        "start": start,
        "window_until": start,
        "fill": {"venue": "kalshi"},
        "flatten_filled": True,
        "flatten_pnl": Decimal("0.40"),
        "hold": {},
        "watch": {},
    }
    control, candidate, stats = gtc_policy_trades([hit, miss])
    assert stats["n_scored"] == 2
    assert stats["n_gtc_used"] == 1
    assert abs(control[0]["pnl_d"] + 0.06) < 1e-9
    assert abs(candidate[0]["pnl_d"] - 0.05) < 1e-9
    assert abs(control[1]["pnl_d"] - 0.40) < 1e-9
    assert abs(candidate[1]["pnl_d"] - 0.40) < 1e-9


def test_judge_dismisses_worse_mean():
    control = {"n": 20, "mean": 0.10, "win_pct": 70.0, "pf": 1.4, "avg_pnl_pct_wo_max": 8.0}
    cand = {"n": 18, "mean": -0.02, "win_pct": 60.0, "pf": 0.9, "avg_pnl_pct_wo_max": -1.0}
    verdict, _why = judge(control, cand)
    assert verdict == "DISMISS"


def test_judge_hold_on_n_collapse():
    control = {"n": 40, "mean": 0.05, "win_pct": 60.0, "pf": 1.2, "avg_pnl_pct_wo_max": 4.0}
    cand = {"n": 4, "mean": 0.20, "win_pct": 75.0, "pf": 2.0, "avg_pnl_pct_wo_max": 18.0}
    verdict, _why = judge(control, cand)
    assert verdict == "HOLD"


def test_judge_hold_perfect_tiny_week():
    control = {"n": 13, "mean": 0.03, "win_pct": 77.0, "pf": 1.2, "avg_pnl_pct_wo_max": 0.0, "n_loss": 3}
    cand = {"n": 6, "mean": 0.16, "win_pct": 100.0, "pf": 0.95, "avg_pnl_pct_wo_max": 16.0, "n_loss": 0}
    verdict, _why = judge(control, cand)
    assert verdict == "HOLD"


def test_judge_keep_on_large_quality_lift():
    control = {"n": 91, "mean": -0.27, "win_pct": 43.0, "pf": 0.4, "avg_pnl_pct_wo_max": -30.0, "n_loss": 52}
    cand = {"n": 91, "mean": 0.23, "win_pct": 57.0, "pf": 2.77, "avg_pnl_pct_wo_max": 65.0, "n_loss": 39}
    verdict, _why = judge(control, cand)
    assert verdict == "KEEP (research only)"


if __name__ == "__main__":
    test_bands()
    test_fav_yes_pnl_matches_house_fee()
    test_pick_one_total_closest_to_50()
    test_c_band_skips_ninety()
    test_dog_cross_fills_first_from_below_and_skips_when_none()
    test_trungelliti_rewind_waits_for_reset()
    test_gtc_policy_uses_hit_pnl_else_actual()
    test_judge_dismisses_worse_mean()
    test_judge_hold_on_n_collapse()
    test_judge_hold_perfect_tiny_week()
    test_judge_keep_on_large_quality_lift()
    print("ok")
