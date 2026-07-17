#!/usr/bin/env python3
"""
Grid-search atr_target × atr_stop × trailing_stop_increment for rocket_brt using the same
backtest and scoring model as BRT_Optimizer (calculate_score, hard gates).

Uses a full BRTConfig baseline (defaults aligned with typical BRT_Report runs),
forces stop_pct=0 and target_pct=0 so ATR exit mode is active.

Example:
  python BRT_ATR_grid.py --quick -w 4
  python BRT_ATR_grid.py --data-dir ../data/newdata/data -w 6
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).parent.resolve()
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from BRT_Optimizer import (  # noqa: E402
    CFG_COLS,
    MIN_TRADES,
    calculate_score,
    sanitize_value,
    _metrics_to_row,
)
from rocket_brt import BRTConfig, run_brt_backtest_batch  # noqa: E402


def _baseline_config() -> BRTConfig:
    """Baseline BRT settings (typical production-style row); ATR mode via stop/target = 0."""
    return replace(
        BRTConfig(),
        band_pct=0.016,
        lookback_long=504,
        touch_threshold=2,
        lookback_short=199,
        close_above_window=1,
        pending_max_bars=252,
        entry_eval_mode="row_local",
        row_local_eval_touch_same_bar=False,
        row_local_require_active_context_match=False,
        brt_cash=62500.0,
        stop_pct=0.0,
        stop_pct_is_multiplier=True,
        target_pct=0.0,
        atr_target=2.2,
        atr_stop=3.0,
        trailing_stop_increment=5.0,
        min_touch_count=0,
        max_touch_count_minor=100,
        tradeable_key_level_enabled=True,
        consolidation_blocker_enabled=True,
        cb_max_box_width_pct=0.35,
        entry_filter_major_pivot="true",
        entry_filter_is_20bar_high_at_trigger="false",
        growth_filter_enabled=True,
        growth_bars=756,
        entry_close_min_range_position=1e-05,
        compute_equity_metrics=False,
        aggressive=False,
    )


def _grid_quick() -> list[tuple[float, float, float]]:
    """8 combos for a fast pass."""
    targets = (2.0, 2.5)
    stops = (3.0, 4.0)
    incs = (0.0, 5.0)
    out: list[tuple[float, float, float]] = []
    for a in targets:
        for b in stops:
            for c in incs:
                out.append((a, b, c))
    return out


def _grid_full() -> list[tuple[float, float, float]]:
    """Larger search space (64 runs)."""
    targets = (1.8, 2.0, 2.2, 2.5)
    stops = (2.5, 3.0, 3.5, 4.0)
    incs = (0.0, 3.0, 5.0, 7.0)
    out: list[tuple[float, float, float]] = []
    for a in targets:
        for b in stops:
            for c in incs:
                out.append((a, b, c))
    return out


def _run_one(task: tuple[Any, ...]) -> dict | None:
    at, ast, ainc, data_dir, ticker_workers = task
    base = _baseline_config()
    cfg = replace(
        base,
        atr_target=at,
        atr_stop=ast,
        trailing_stop_increment=ainc,
        stop_pct=0.0,
        target_pct=0.0,
    )
    try:
        _, metrics = run_brt_backtest_batch(data_dir, cfg, n_workers=int(ticker_workers))
        row = _metrics_to_row(metrics, "atr_grid", f"{at}_{ast}_{ainc}")
        row["atr_target"] = at
        row["atr_stop"] = ast
        row["trailing_stop_increment"] = ainc
        return row
    except Exception as e:
        print(f"  [ERR] atr_target={at} atr_stop={ast} trailing_stop_increment={ainc}: {e}", file=sys.stderr)
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Grid-search ATR params for rocket_brt")
    ap.add_argument("--data-dir", default=str(SCRIPT_DIR.parent / "data" / "newdata" / "data"))
    ap.add_argument(
        "-w",
        "--workers",
        type=int,
        default=2,
        help="Parallel grid workers (each runs one full backtest; keep low if --ticker-workers is high)",
    )
    ap.add_argument(
        "--ticker-workers",
        type=int,
        default=max(0, min(8, (os.cpu_count() or 4) - 2)),
        help="Workers inside run_brt_backtest_batch per combo (0=all tickers serial; default ~CPU-2)",
    )
    ap.add_argument("--quick", action="store_true", help="8 combinations instead of 64")
    ap.add_argument("-o", "--output", default="", help="Output CSV path (default: Drive/BRT_ATR_Grid_<ts>.csv)")
    args = ap.parse_args()

    data_dir = str(Path(args.data_dir).resolve())
    grid = _grid_quick() if args.quick else _grid_full()
    workers = max(1, int(args.workers))
    tw = max(0, int(args.ticker_workers))

    ts = datetime.now().strftime("%y%m%d%H%M%S")
    out_path = args.output or str(SCRIPT_DIR.parent / "Drive" / f"BRT_ATR_Grid_{ts}.csv")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    print(f"[OK] Data: {data_dir}")
    print(
        f"[OK] Grid: {len(grid)} combos ({'quick' if args.quick else 'full'}), "
        f"grid_workers={workers}, ticker_workers={tw}"
    )
    print(f"[OK] Baseline for scoring: first grid triple {grid[0]}")

    tasks = [(at, ast, ainc, data_dir, tw) for at, ast, ainc in grid]
    results: list[dict] = []

    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_run_one, t): t for t in tasks}
        for fut in as_completed(futs):
            row = fut.result()
            if row:
                results.append(row)
                print(
                    f"  done atr_target={row.get('atr_target')} atr_stop={row.get('atr_stop')} "
                    f"trailing_stop_increment={row.get('trailing_stop_increment')} "
                    f"PNL={row.get('Total_PNL', 0):.0f} trades={row.get('Total_Trades', 0)}"
                )

    if not results:
        print("[ERR] No successful runs.", file=sys.stderr)
        return 1

    baseline_key = grid[0]
    by_key = {
        (float(r["atr_target"]), float(r["atr_stop"]), float(r["trailing_stop_increment"])): r
        for r in results
    }
    baseline_row = by_key.get(baseline_key)
    if baseline_row is None:
        baseline_row = next(iter(results), None)
    for r in results:
        r["Score"] = calculate_score(r, baseline_row)

    df = pd.DataFrame(results)
    df = df.sort_values("Score", ascending=False)

    # Flatten config columns for audit-style alignment
    base = _baseline_config()
    cfg_dict = {k: sanitize_value(v) for k, v in base.__dict__.items() if not k.startswith("_")}
    for k in CFG_COLS:
        if k not in df.columns and k in cfg_dict:
            df[k] = cfg_dict[k]

    df.to_csv(out_path, index=False)
    best = df.iloc[0]
    print("\n" + "=" * 60)
    print(f"[OK] Wrote {out_path}")
    print(
        f"[OK] Best: atr_target={best.get('atr_target')} atr_stop={best.get('atr_stop')} "
        f"trailing_stop_increment={best.get('trailing_stop_increment')}  Score={best.get('Score', 0):.2f}  "
        f"Total_PNL={best.get('Total_PNL', 0):.0f}  Ann_ROR={best.get('Ann_ROR', 0):.2f}  "
        f"Max_DD={best.get('Max_DD', 0)}  Trades={int(best.get('Total_Trades', 0))}"
    )
    if int(best.get("Total_Trades", 0)) < MIN_TRADES:
        print(
            f"[WARN] Best run has Total_Trades={int(best.get('Total_Trades', 0))} < MIN_TRADES={MIN_TRADES}; "
            f"optimizer score may be 0 for all rows (BRT_Optimizer rule)."
        )
    return 0


if __name__ == "__main__":
    os.chdir(SCRIPT_DIR)
    sys.exit(main())
