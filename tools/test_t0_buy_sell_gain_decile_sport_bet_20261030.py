"""Unit tests for T0 buy then sell-at-G. No live orders. No hist pull."""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import _write_t0_buy_sell_gain_decile_sport_bet_20261030 as w
from write_t0_band_from_stay_above import documented_leg_fee


def test_decile_and_dist():
    assert w.decile_of(0.00) == "0-9"
    assert w.decile_of(0.09) == "0-9"
    assert w.decile_of(0.10) == "10-19"
    assert w.decile_of(0.49) == "40-49"
    assert w.decile_of(0.50) == "50-59"
    assert w.decile_of(0.59) == "50-59"
    assert w.decile_of(0.90) == "90-99"
    assert w.decile_of(0.99) == "90-99"
    assert w.dist50_band(0.50) == "0-9"
    assert w.dist50_band(0.45) == "0-9"
    assert w.dist50_band(0.55) == "0-9"
    assert w.dist50_band(0.40) == "10-19"
    assert w.dist50_band(0.09) == "40-50"
    assert w.dist50_band(0.91) == "40-50"


def test_gain_fill_open_through_and_limit():
    t0, ts = 0.40, 1000
    ticks = [(1010, 0.41), (1020, 0.45), (1030, 0.50)]
    hit = w.first_gain_fill(t0, ts, ticks, 0.45)
    assert hit is not None
    assert hit["how"] == "print_at_or_above_target"
    assert abs(hit["fill_px"] - 0.45) < 1e-12

    through = w.first_gain_fill(t0, ts, [(1010, 0.60)], 0.45)
    assert through["how"] == "open_through_first_print"
    assert abs(through["fill_px"] - 0.60) < 1e-12

    gap = w.first_gain_fill(t0, ts, [(1010, 0.41), (1020, 0.60)], 0.45)
    assert gap["how"] == "traded_through_fill_at_target"
    assert abs(gap["fill_px"] - 0.45) < 1e-12

    miss = w.first_gain_fill(t0, ts, [(1010, 0.41), (1020, 0.42)], 0.45)
    assert miss is None


def test_kalshi_both_leg_fees_not_doubled():
    entry, fill = 0.40, 0.45
    buy_fee = documented_leg_fee("kalshi", entry)
    sell_fee = documented_leg_fee("kalshi", fill)
    assert buy_fee is not None and sell_fee is not None
    rec = w.gain_pnl("kalshi", entry, fill, won=True, hit=True)
    buy_cash = float(Decimal(str(entry)) + buy_fee)
    proceeds = float(Decimal(str(fill)) - sell_fee)
    assert abs(rec["pnl"] - (proceeds - buy_cash)) < 1e-9
    assert rec["buy_fee"] == float(buy_fee)
    assert rec["sell_fee"] == float(sell_fee)
    miss = w.gain_pnl("kalshi", entry, None, won=False, hit=False)
    assert abs(miss["pnl"] - (-buy_cash)) < 1e-9
    win_hold = w.gain_pnl("kalshi", entry, None, won=True, hit=False)
    assert abs(win_hold["pnl"] - (1.0 - buy_cash)) < 1e-9
    novig = w.gain_pnl("novig", entry, fill, won=True, hit=True)
    assert novig is None


def test_identities_cheaper_and_nearest():
    a = w._side(sport="tennis", game_n="m1", kind="moneyline", number="",
                t0_px=0.42, letter="a", name="Dog")
    b = w._side(sport="tennis", game_n="m1", kind="moneyline", number="",
                t0_px=0.58, letter="b", name="Fav")
    cheap = w.pick_cheaper([a, b])
    near = w.pick_nearest_50([a, b])
    named = w.pick_named_yes([a, b])
    assert len(cheap) == 1 and cheap[0]["t0_px"] == 0.42
    assert cheap[0]["slice"] == "cheaper_yes"
    assert len(near) == 1 and near[0]["t0_px"] == 0.42
    assert near[0]["slice"] == "nearest_50"
    assert len(named) == 2
    far_a = dict(a, t0_px=0.08)
    far_b = dict(b, t0_px=0.92)
    near2 = w.pick_nearest_50([far_a, far_b])
    assert abs(near2[0]["t0_px"] - 0.08) < 1e-12
    cheap2 = w.pick_cheaper([far_a, far_b])
    assert cheap2[0]["t0_px"] == 0.08


def test_move_stats():
    rec = w.move_stats(0.40, [(1, 0.41), (2, 0.52), (3, 0.30)])
    assert abs(rec["max_up"] - 0.12) < 1e-12
    assert abs(rec["max_down"] - 0.10) < 1e-12
    assert abs(rec["range"] - 0.22) < 1e-12
    empty = w.move_stats(0.40, [])
    assert empty["n_post"] == 0


def main() -> int:
    test_decile_and_dist()
    test_gain_fill_open_through_and_limit()
    test_kalshi_both_leg_fees_not_doubled()
    test_identities_cheaper_and_nearest()
    test_move_stats()
    print("test_t0_buy_sell_gain_decile_sport_bet_20261030 ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
