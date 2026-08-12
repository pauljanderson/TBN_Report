#!/usr/bin/env python3
"""Unit tests for WRL weekly range / swing levels and watch → buy sequence."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))

from wrl_zones import (  # noqa: E402
    attach_daily_levels,
    breakout_up_from_demand,
    close_in_demand_zone,
    compute_week_swings,
    fill_price,
    levels_for_bar,
    walk_swing_high,
    walk_swing_low,
)
from rocket_wrl import WrlConfig, backtest_symbol  # noqa: E402
from wpbr_zones import aggregate_weekly  # noqa: E402


def _week_frame(rows: list[tuple[str, float, float]]) -> pd.DataFrame:
    """rows: (friday_iso, high, low)."""
    idx = pd.to_datetime([r[0] for r in rows])
    return pd.DataFrame(
        {"Open": [r[2] for r in rows], "High": [r[1] for r in rows], "Low": [r[2] for r in rows], "Close": [r[1] for r in rows]},
        index=idx,
    )


def test_walk_swing_independent_weeks() -> None:
    # Range week (idx 3): H=100 L=90
    # Week 2: H=99 L=91  — neither swing
    # Week 1: H=105 L=92  — swing high only
    # Week 0: H=98 L=80   — swing low only
    wh = np.array([98.0, 105.0, 99.0, 100.0])
    wl = np.array([80.0, 92.0, 91.0, 90.0])
    sh_i, sh = walk_swing_high(wh, 3)
    sl_i, sl = walk_swing_low(wl, 3)
    assert sh_i == 1 and sh == 105.0
    assert sl_i == 0 and sl == 80.0


def test_compute_week_swings_skips_until_structure() -> None:
    w = _week_frame(
        [
            ("2024-01-05", 110.0, 80.0),
            ("2024-01-12", 100.0, 90.0),
            ("2024-01-19", 112.0, 91.0),
        ]
    )
    swings = compute_week_swings(w)
    assert swings[0] is None
    # Week 1 as previous week: range 100/90, swing high 110, swing low 80
    assert swings[1] is not None
    assert swings[1].range_high == 100.0
    assert swings[1].range_low == 90.0
    assert swings[1].swing_high == 110.0
    assert swings[1].swing_low == 80.0
    # Week 2 as previous: range 112/91 — no earlier high > 112, so no swing high
    assert swings[2] is None


def test_daily_maps_to_completed_week_not_in_progress() -> None:
    # Daily Mon-Fri for two full weeks + a Wednesday in week 3.
    days = pd.bdate_range("2024-01-01", "2024-01-17")  # through Wed week 3
    n = len(days)
    # Week1 (ending Fri 1/5): high 110 low 80
    # Week2 (ending Fri 1/12): high 100 low 90
    close = np.full(n, 95.0)
    high = np.full(n, 96.0)
    low = np.full(n, 94.0)
    open_ = np.full(n, 95.0)
    for i, d in enumerate(days):
        if d <= pd.Timestamp("2024-01-05"):
            high[i], low[i] = 110.0, 80.0
        elif d <= pd.Timestamp("2024-01-12"):
            high[i], low[i] = 100.0, 90.0
        else:
            high[i], low[i] = 96.0, 94.0
    df = pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": 1.0}, index=days)
    weekly, swings, week_idx = attach_daily_levels(df)
    # Wednesday 2024-01-17 should still use week ending 1/12 as previous week
    wed = int(days.get_loc(pd.Timestamp("2024-01-17")))
    lv = levels_for_bar(swings, week_idx, wed)
    assert lv is not None
    assert lv.range_week_end == pd.Timestamp("2024-01-12")
    assert lv.range_high == 100.0
    assert lv.range_low == 90.0
    assert lv.swing_high == 110.0
    assert lv.swing_low == 80.0
    # Friday 1/12 itself still uses week ending 1/5 (current week not complete).
    # That range week is the first bar, so no swing walk-back yet.
    fri = int(days.get_loc(pd.Timestamp("2024-01-12")))
    assert int(week_idx[fri]) == 0
    assert pd.Timestamp(weekly.index[int(week_idx[fri])]) == pd.Timestamp("2024-01-05")
    assert levels_for_bar(swings, week_idx, fri) is None


def test_watch_and_breakout_helpers() -> None:
    w = _week_frame([("2024-01-05", 110.0, 80.0), ("2024-01-12", 100.0, 90.0)])
    lv = compute_week_swings(w)[1]
    assert lv is not None
    assert close_in_demand_zone(90.0, lv)
    assert close_in_demand_zone(80.0, lv)
    assert close_in_demand_zone(85.0, lv)
    assert not close_in_demand_zone(90.01, lv)
    assert not close_in_demand_zone(79.99, lv)
    assert breakout_up_from_demand(85.0, 91.0, lv)
    assert breakout_up_from_demand(90.5, 91.0, lv)  # gapped out
    assert not breakout_up_from_demand(79.0, 91.0, lv)  # gapped down through swing low
    assert not breakout_up_from_demand(85.0, 90.0, lv)  # never left the zone
    assert fill_price(85.0, lv) == 90.0
    assert fill_price(91.0, lv) == 91.0


def _synth_breakout_df() -> pd.DataFrame:
    """Two complete weeks of structure, then a watch day and a breakout day."""
    # Week ending 2024-01-05: H=110 L=80
    # Week ending 2024-01-12: H=100 L=90  → range
    # Mon 1/15 close 85 (in zone) watch
    # Tue 1/16 open 86 high 92 → buy at 90, later can hit targets
    days = list(pd.bdate_range("2024-01-01", "2024-01-26"))
    rows = []
    for d in days:
        if d <= pd.Timestamp("2024-01-05"):
            o, hi, lo, cl = 95.0, 110.0, 80.0, 100.0
        elif d <= pd.Timestamp("2024-01-12"):
            o, hi, lo, cl = 95.0, 100.0, 90.0, 96.0
        elif d == pd.Timestamp("2024-01-15"):
            o, hi, lo, cl = 88.0, 89.0, 84.0, 85.0  # close in [80, 90]
        elif d == pd.Timestamp("2024-01-16"):
            o, hi, lo, cl = 86.0, 101.0, 85.5, 100.5  # break out; high tags range high
        else:
            o, hi, lo, cl = 101.0, 112.0, 100.0, 111.0  # run to swing high
        rows.append((d, o, hi, lo, cl))
    idx = pd.DatetimeIndex([r[0] for r in rows])
    return pd.DataFrame(
        {
            "Open": [r[1] for r in rows],
            "High": [r[2] for r in rows],
            "Low": [r[3] for r in rows],
            "Close": [r[4] for r in rows],
            "Volume": 1_000_000.0,
        },
        index=idx,
    )


def test_backtest_watch_then_buy_scale() -> None:
    df = _synth_breakout_df()
    closed, open_rows, watch, scanner = backtest_symbol("TEST", df, WrlConfig(wrl_target_mode="scale"))
    assert open_rows == []
    assert len(closed) == 1
    t = closed[0]
    assert t.entry_price == 90.0  # fill at range low
    assert t.range_high == 100.0
    assert t.swing_high == 110.0
    assert t.swing_low == 80.0
    # Entry bar skips exits; next open 101 gaps through T1 (50% @ 101) then High tags T2 (50% @ 110).
    assert abs(t.exit_price - 105.5) < 1e-6
    assert t.exit_type in ("TARGET2", "GAP_UP")
    assert t.pnl_pct > 0


def test_backtest_range_target_only() -> None:
    df = _synth_breakout_df()
    closed, _, _, _ = backtest_symbol("TEST", df, WrlConfig(wrl_target_mode="range"))
    assert len(closed) == 1
    t = closed[0]
    assert abs(t.exit_price - 101.0) < 1e-6
    assert t.exit_type in ("TARGET", "GAP_UP")


def test_end_of_series_watch() -> None:
    days = list(pd.bdate_range("2024-01-01", "2024-01-15"))
    rows = []
    for d in days:
        if d <= pd.Timestamp("2024-01-05"):
            o, hi, lo, cl = 95.0, 110.0, 80.0, 100.0
        elif d <= pd.Timestamp("2024-01-12"):
            o, hi, lo, cl = 95.0, 100.0, 90.0, 96.0
        else:
            o, hi, lo, cl = 88.0, 89.0, 84.0, 85.0
        rows.append((d, o, hi, lo, cl))
    idx = pd.DatetimeIndex([r[0] for r in rows])
    df = pd.DataFrame(
        {
            "Open": [r[1] for r in rows],
            "High": [r[2] for r in rows],
            "Low": [r[3] for r in rows],
            "Close": [r[4] for r in rows],
            "Volume": 1.0,
        },
        index=idx,
    )
    closed, open_rows, watch, scanner = backtest_symbol("TEST", df, WrlConfig())
    assert closed == []
    assert open_rows == []
    assert len(watch) == 1
    assert watch[0]["status"] == "CLOSE_IN_DEMAND_ZONE"
    assert len(scanner) == 1
    assert scanner[0]["range_low"] == 90.0


def test_aggregate_weekly_used() -> None:
    df = _synth_breakout_df()
    w = aggregate_weekly(df)
    assert len(w) >= 2
    assert "High" in w.columns and "Low" in w.columns


if __name__ == "__main__":
    tests = [
        test_walk_swing_independent_weeks,
        test_compute_week_swings_skips_until_structure,
        test_daily_maps_to_completed_week_not_in_progress,
        test_watch_and_breakout_helpers,
        test_backtest_watch_then_buy_scale,
        test_backtest_range_target_only,
        test_end_of_series_watch,
        test_aggregate_weekly_used,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"ok  {fn.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
            raise
    print(f"{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(failed)
