#!/usr/bin/env python3
"""Export breakout/retest rows for one symbol (fast parity check vs sheet ledger)."""
from __future__ import annotations

import csv
import sys
from dataclasses import asdict, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stock_analysis.rocket_brt import (  # noqa: E402
    BRTConfig,
    _process_symbol,
    write_brt_breakout_and_retest,
)


def main() -> int:
    sym = (sys.argv[1] if len(sys.argv) > 1 else "META").upper()
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "Drive" / f"_parity_{sym}_breakout_retest.csv"
    csv_path = ROOT / "data" / "newdata" / "data" / f"{sym}.csv"
    if not csv_path.is_file():
        print(f"ERROR: missing OHLC: {csv_path}", file=sys.stderr)
        return 2

    cfg = BRTConfig(
        yh_zones=True,
        brt_zones=False,
        yh_memory_mode="sheet",
        band_pct=0.015,
        yh_lookback=252,
        yh_move_away_pct=0.03,
        sheet_breakout_scan_start_row_delta=2,
        zone_maturity_model="sheet_lag",
        sheet_maturity_lag_bars=0,
        sheet_di_breakout_price="close",
        sheet_di_max_history_bars=0,
        zone_compare_round_decimals=2,
        entry_from_retest_only=True,
        growth_filter_enabled=True,
        growth_bars=756,
    )
    cfg_dict = asdict(cfg)

    result = _process_symbol((sym, str(csv_path), cfg_dict, None, False))
    timing = result[7] if len(result) > 7 else {}
    print(f"bars={timing.get('bars', '?')} backtest_s={timing.get('t_backtest', 0):.1f}")
    rows = result[10] if len(result) > 10 else []
    write_brt_breakout_and_retest(rows, str(out))
    print(f"Wrote {len(rows)} rows for {sym} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
