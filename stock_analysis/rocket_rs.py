#!/usr/bin/env python3
"""
Rocket RS — thin launcher for TBN relative-strength mode.

All RS logic lives in rocket_tbn.py (relative_strength_enabled / --relative-strength / -v rs_mode=true):
  Trigger bar T close: SPY_COMPARE 1Y/2Y/3Y all > 0 AND IND_TC_*_OUTLOOK all Strong
  Entry: buy at bar T+1 open (do not re-check TC/SPY_COMPARE on entry bar)
  Closed IND_TC_* / SPY_COMPARE_* snapshot trigger bar T (same as SMA*_AT_TRIGGER)
  Optional (trigger T): rs_max_pct_below_52w_high, growth_filter_enabled/growth_bars,
    rs_spy_int_tc_not_weak / block_entries_when_spy_int_weak
    (both use spy_int_tc_lag + spy_tc_weak_horizon=short|int|long; default lag=1 → outlook[T-1];
     default horizon=int; not re-checked on entry)
  Optional exit: exit_when_spy_int_turns_weak — lag-1 as of day D; exit at D open when lagged Weak turns
  Optional exit: sell_breakdown=off|breakdown_only|breakdown_both|breakdown_plus
    (default off = normal target/stop only; breakdown uses same-bar SPY_COMPARE/IND_TC as entry;
     exit next open as RS_BREAKDOWN_EXIT, or RS_BREAKDOWN_BOTH_EXIT for breakdown_both;
     only = SPY OR TC; both = SPY AND TC; plus = normal exits OR (SPY OR TC))
  Exit:  target_pct / stop_pct (same Closed-row builder as BRT/YH/MTS) unless
    breakdown_only / breakdown_both
  Prefix: RS_

Production DailyRun path: run_rs.bat → rocket_tbn.py --relative-strength.
This module preserves legacy imports and direct ``python rocket_rs.py`` entry points.
Experiment harness (kept): tools/run_spy_tc_strong_system.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_pkg = Path(__file__).resolve().parent
if str(_pkg) not in sys.path:
    sys.path.insert(0, str(_pkg))

from rocket_tbn import (  # noqa: F401
    BRTConfig as RSConfig,
    BRTTrade as RSTrade,
    load_csv,
    main as _tbn_main,
    run_relative_strength_backtest as run_rs_backtest,
    _RS_SPY_LAG_3Y,
    _align_stock_spy_close_for_rs,
    _rs_excess_pct_points,
    _rs_pass_all_horizons_vs_spy,
)


def _argv_has_rs_profile(argv: list[str]) -> bool:
    joined = " ".join(argv).lower()
    return (
        "--relative-strength" in argv
        or "relative_strength_enabled=true" in joined
        or "relative_strength_enabled=1" in joined
        or "rs_mode=true" in joined
        or "rs_mode=1" in joined
    )


def main() -> int:
    argv = list(sys.argv)
    if not _argv_has_rs_profile(argv):
        # Legacy direct rocket_rs.py invocation: inject RS profile (override with -v).
        insert_at = 1
        legacy = [
            "--relative-strength",
            "-v", "rs_mode=true",
            "-v", "brt_zones=false",
            "-v", "yh_zones=false",
            "-v", "wpbr_zones=false",
            "-v", "rl_mode=false",
            "-v", "use_indicators=true",
            "-v", "indicator_buy=off",
            "-v", "rs_require_tc_strong=true",
            "-v", "target_pct=1.25",
            "-v", "stop_pct=0.88",
            "-v", "stop_pct_is_multiplier=true",
            # Neutralize BRT zone defaults (RS already requires SPY_COMPARE > 0).
            "-v", "min_spy_compare_1y_at_trigger=0",
            "-v", "too_high_multiplier=0",
            "-v", "growth_filter_enabled=false",
        ]
        argv[insert_at:insert_at] = legacy
        sys.argv = argv
    return _tbn_main()


if __name__ == "__main__":
    raise SystemExit(main())
