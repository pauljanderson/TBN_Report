#!/usr/bin/env python3
"""
Rocket MTS — thin launcher and compatibility shim for rocket_brt.

All MTS sheet-parity logic lives in rocket_brt.py (mts_mode / --mts-sheet-parity).
This module preserves legacy imports and runmts.bat entry points.
"""
from __future__ import annotations

import sys
from pathlib import Path

_pkg = Path(__file__).resolve().parent
if str(_pkg) not in sys.path:
    sys.path.insert(0, str(_pkg))

from rocket_brt import (  # noqa: F401
    BRTConfig as MTSConfig,
    BRTTrade as MTSTrade,
    build_level3_for_cfg,
    compute_market_structure,
    compute_pivots,
    compute_touch_stream,
    load_csv,
    main as _brt_main,
    mts_sheet_parity_overrides,
    run_brt_backtest as run_mts_backtest,
    _load_benchmark_local,
)


def _argv_has_mts_profile(argv: list[str]) -> bool:
    joined = " ".join(argv).lower()
    return (
        "--mts-sheet-parity" in argv
        or "--sheet-parity" in argv
        or "mts_mode=true" in joined
        or "mts_mode=1" in joined
    )


def main() -> int:
    argv = list(sys.argv)
    if not _argv_has_mts_profile(argv):
        # Legacy runmts.bat: pivot-zone MTS outputs without full BI gate stack (override with -v).
        insert_at = 1
        legacy = [
            "-v", "mts_mode=true",
            "-v", "brt_zones=true",
            "-v", "yh_zones=false",
            "-v", "entry_from_retest_only=false",
            "-v", "indicator_buy=off",
            "-v", "band_pct=0.02",
            "-v", "lookback_long=503",
            "-v", "lookback_short=199",
        ]
        argv[insert_at:insert_at] = legacy
        sys.argv = argv
    return _brt_main()


if __name__ == "__main__":
    raise SystemExit(main())
