#!/usr/bin/env python3
"""
MTS_Optimizer: Grid-optimize MTS parameters on the official MTS universe (mts_universe.py).

Scoring: same baseline-relative formula as IND_Optimizer (baseline score = 100).
Hard gates: MIN_TRADES, Max_DD <= MAX_DRAWDOWN_PCT.

Outputs (same pattern as IND_Optimizer / BRT_Optimizer):
  MTS_Optimization_Master_Log.csv   — winner per parameter sweep
  MTS_Optimization_Audit.csv        — full grid per sweep
  MTS_Optimizer_Summary.csv         — winner summary rows
  MTS_Final_Optimized_Settings.json — best params + baseline/optimized metrics
  MTS_MarkTen_Benchmark.json        — benchmark snapshot

Daily backtest outputs (via rocket_brt --mts-sheet-parity):
  drive\\MTS_Closed|Open|Scanner|Watchlist|Report|Summary_<ts>.csv
  drive\\MTS_LatestRun_*.csv        — stable copies from Copy-LatestRunOutputs.ps1

Usage:
  python MTS_Optimizer.py --benchmark-only   # baseline metrics only
  python MTS_Optimizer.py --reset              # fresh full sweep from starting values
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
from collections import OrderedDict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, fields, replace
from datetime import datetime
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).parent.resolve()
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from rocket_brt import (  # noqa: E402
    BRTConfig,
    BRTTrade,
    build_level3_for_cfg,
    compute_market_structure,
    compute_metrics,
    compute_pivots,
    load_csv,
    mts_sheet_parity_overrides,
    run_brt_backtest,
)

REPO_ROOT = SCRIPT_DIR.parent
DATA_DIR = REPO_ROOT / "data" / "newdata" / "data"

from mts_universe import MTS_SYMBOLS, MTS_SYMBOLS_CSV

MARKTEN = MTS_SYMBOLS  # legacy name; official MTS universe

MASTER_LOG = "MTS_Optimization_Master_Log.csv"
BEST_SETTINGS_FILE = "MTS_Final_Optimized_Settings.json"
GLOBAL_AUDIT_LOG = "MTS_Optimization_Audit.csv"
OPTIMIZER_SUMMARY_FILE = "MTS_Optimizer_Summary.csv"
PROGRESS_FILE = "MTS_optimizer_progress.json"
BENCHMARK_FILE = "MTS_MarkTen_Benchmark.json"

MAX_WORKERS = 2
BACKTEST_WORKERS = 4

MIN_TRADES = 40
MAX_DRAWDOWN_PCT = 22.0

W_PROFIT_PER_CAP_DAY = 15
W_TOTAL_PROFIT = 15
W_MAX_DRAWDOWN = 15
W_PROFIT_FACTOR = 15
W_EXPECTANCY = 15
W_WIN_LOSS_RATIO = 10
W_LOSING_STREAK = 10
W_P90_DAYS = 5

# Starting values from user sheet (used as baseline + seed for sequential tuning).
current_best_params = {
    "band_pct": 0.02,
    "touch_threshold": 2,
    "strong_post_pivot_bars": 7,
    "strong_post_pivot_pct": 0.09,
    "strong_pre_pivot_bars": 7,
    "strong_pre_pivot_pct": 0.12,
    "target_pct": 1.22,          # +22% target exit
    "stop_pct": 0.934,           # signal low × 0.934 ≈ 6.6% stop
    "stop_pct_is_multiplier": True,
    "stop_loss_based": "trigger_low",
    "stop_anchor": "signal_low",  # legacy alias of trigger_low
    "compute_equity_metrics": True,
    "brt_cash": 47500,
}

# Tune order: band → touch → post-pivot bars/% → pre-pivot bars/% → target → stop
OPTIMIZATION_PLAN = OrderedDict([
    ("band_pct", (
        0.015, 0.016, 0.017, 0.018, 0.019, 0.02, 0.021, 0.022, 0.023, 0.024, 0.025,
    )),
    ("touch_threshold", (2, 3, 4, 5, 6)),
    ("strong_post_pivot_bars", (5, 6, 7, 8, 9)),
    ("strong_post_pivot_pct", (0.06, 0.07, 0.08, 0.09, 0.10, 0.11)),
    ("strong_pre_pivot_bars", (5, 6, 7, 8, 9)),
    ("strong_pre_pivot_pct", (0.08, 0.10, 0.12, 0.14, 0.16)),
    ("target_pct", (1.18, 1.19, 1.20, 1.21, 1.22, 1.23, 1.24, 1.25, 1.26)),
    ("stop_pct", (0.91, 0.92, 0.93, 0.934, 0.94, 0.945, 0.95)),
])

MTS_CFG_COLS = [
    "band_pct", "touch_threshold",
    "strong_post_pivot_bars", "strong_post_pivot_pct",
    "strong_pre_pivot_bars", "strong_pre_pivot_pct",
    "target_pct", "stop_pct",
    "stop_loss_based", "stop_anchor", "compute_equity_metrics",
]

AUDIT_COLS_ORDER = (
    ["Timestamp_Drive"]
    + MTS_CFG_COLS
    + ["Param_Name", "Param_Value"]
    + ["Total_PNL", "Wins", "Losses", "BE", "Pct_Wins", "Pct_Losses",
       "Win_Loss_Ratio", "Win_Loss_Ratio_Dollar", "Total_Trades", "Profit_Factor",
       "Avg_Win_Pct", "Avg_Loss_Pct", "Avg_PNL_Pct", "Expectancy", "Expectancy_Pct"]
    + ["Avg_Days_Held", "Median_Days_Held", "P90_Days", "Capital_Days",
       "Profit_Per_Capital_Day", "Ann_ROR"]
    + ["Max_DD", "Losing_Streak", "DD_Per_Trade"]
    + ["Score"]
)


def _cfg_dict_to_brt_config(cfg_dict: dict) -> BRTConfig:
    base = asdict(BRTConfig())
    base.update(mts_sheet_parity_overrides())
    base.update({k: v for k, v in cfg_dict.items() if k in {f.name for f in fields(BRTConfig)}})
    return BRTConfig(**base)


def _metrics_to_row(metrics: dict, param_name: str, param_value) -> dict:
    def num(x):
        if x is None or x == "N/A":
            return 0.0
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).replace("%", "").replace("$", "").replace(",", "").strip()
        try:
            return float(s)
        except ValueError:
            return 0.0

    wins = int(metrics.get("Wins", 0))
    losses = int(metrics.get("Losses", 0))
    bes = int(metrics.get("BEs", 0))
    total_trades = wins + losses + bes
    pct_wins = (wins / total_trades * 100) if total_trades else 0.0
    pct_losses = (losses / total_trades * 100) if total_trades else 0.0
    win_loss_ratio = (wins / losses) if losses else (float(wins) if wins else 0.0)
    max_dd_raw = metrics.get("Max_Drawdown", "N/A")

    return {
        "Param_Name": param_name,
        "Param_Value": param_value,
        "Total_PNL": num(metrics.get("Total_PNL", 0)),
        "Wins": wins,
        "Losses": losses,
        "BE": bes,
        "Pct_Wins": pct_wins,
        "Pct_Losses": pct_losses,
        "Win_Loss_Ratio": win_loss_ratio,
        "Win_Loss_Ratio_Dollar": num(metrics.get("Win_Loss_Ratio_Dollar", 0)),
        "Total_Trades": total_trades,
        "Profit_Factor": num(metrics.get("Profit_Factor", 0)),
        "Avg_Win_Pct": num(metrics.get("Avg_Win_Pct", 0)),
        "Avg_Loss_Pct": num(metrics.get("Avg_Loss_Pct", 0)),
        "Avg_PNL_Pct": num(metrics.get("Avg_PNL_Pct", 0)),
        "Expectancy": num(metrics.get("Expectancy", 0)),
        "Expectancy_Pct": num(metrics.get("Avg_PNL_Pct", 0)),
        "Avg_Days_Held": num(metrics.get("Avg_Days_Held", 0)),
        "Median_Days_Held": num(metrics.get("Median_Days_Held", 0)),
        "P90_Days": num(metrics.get("P90_Days", 0)),
        "Capital_Days": int(metrics.get("Capital_Days", 0)),
        "Profit_Per_Capital_Day": num(metrics.get("Profit_Per_Capital_Day", 0)),
        "Ann_ROR": num(metrics.get("Annualized_ROR", 0)),
        "Max_DD": max_dd_raw,
        "Losing_Streak": int(metrics.get("Losing_Streak", 0)),
        "DD_Per_Trade": num(metrics.get("DD_Per_Trade", 0)),
    }


def _safe_num(x) -> float:
    if x is None or x == "N/A" or (isinstance(x, str) and str(x).strip() == "N/A"):
        return 0.0
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def _win_loss_ratio(row: dict) -> float:
    wins = int(row.get("Wins", 0))
    losses = int(row.get("Losses", 0))
    if losses <= 0:
        return 10.0 if wins > 0 else 1.0
    return wins / losses


def _passes_hard_gates(row: dict) -> bool:
    if int(row.get("Total_Trades", 0)) < MIN_TRADES:
        return False
    if _safe_num(row.get("Max_DD", 0)) > MAX_DRAWDOWN_PCT:
        return False
    return True


def calculate_score(row: dict, baseline_row: dict | None) -> float:
    if baseline_row is None or not _passes_hard_gates(row):
        return 0.0

    def ratio_higher(v: float, b: float) -> float:
        if b == 0:
            return 1.0 if v == 0 else (2.0 if v > 0 else 0.0)
        return v / b

    def ratio_lower(v: float, b: float) -> float:
        if v == 0:
            return 2.0 if b > 0 else 1.0
        if b == 0:
            return 1.0
        return b / v

    v_ppcd = _safe_num(row.get("Profit_Per_Capital_Day", 0))
    b_ppcd = _safe_num(baseline_row.get("Profit_Per_Capital_Day", 0))
    v_pnl = _safe_num(row.get("Total_PNL", 0))
    b_pnl = _safe_num(baseline_row.get("Total_PNL", 0))
    v_dd = _safe_num(row.get("Max_DD", 0))
    b_dd = _safe_num(baseline_row.get("Max_DD", 0))
    v_pf = _safe_num(row.get("Profit_Factor", 0))
    b_pf = _safe_num(baseline_row.get("Profit_Factor", 0))
    v_exp = _safe_num(row.get("Expectancy", 0))
    b_exp = _safe_num(baseline_row.get("Expectancy", 0))
    v_wlr = _win_loss_ratio(row)
    b_wlr = _win_loss_ratio(baseline_row)
    v_streak = int(row.get("Losing_Streak", 0))
    b_streak = int(baseline_row.get("Losing_Streak", 0))
    v_p90 = _safe_num(row.get("P90_Days", 0))
    b_p90 = _safe_num(baseline_row.get("P90_Days", 0))

    r_dd = ratio_lower(v_dd, b_dd) if (v_dd > 0 and b_dd > 0) else 1.0

    s = 0.0
    s += ratio_higher(v_ppcd, b_ppcd) * (W_PROFIT_PER_CAP_DAY / 100)
    s += ratio_higher(v_pnl, b_pnl) * (W_TOTAL_PROFIT / 100)
    s += r_dd * (W_MAX_DRAWDOWN / 100)
    s += ratio_higher(v_pf, b_pf) * (W_PROFIT_FACTOR / 100)
    s += ratio_higher(v_exp, b_exp) * (W_EXPECTANCY / 100)
    s += ratio_higher(v_wlr, b_wlr) * (W_WIN_LOSS_RATIO / 100)
    s += ratio_lower(float(v_streak), float(b_streak)) * (W_LOSING_STREAK / 100)
    s += ratio_lower(v_p90, b_p90) * (W_P90_DAYS / 100)
    return s * 100


def _run_one_symbol(args: tuple) -> list[BRTTrade]:
    sym, csv_path, cfg_dict = args
    cfg = _cfg_dict_to_brt_config(cfg_dict)
    df = load_csv(csv_path)
    ph, pl, php, plp = compute_pivots(
        df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
        realtime_filter_enabled=cfg.realtime_filter_enabled,
    )
    struct = compute_market_structure(df, ph, pl, php, plp)
    l3 = build_level3_for_cfg(df, cfg, ph, pl, php, plp)
    closed, *_ = run_brt_backtest(sym, df, cfg, php, plp, struct, l3)
    return closed


def run_markten_mts_batch(cfg_dict: dict, data_dir: Path, n_workers: int = 0) -> tuple[list[BRTTrade], dict]:
    cfg = _cfg_dict_to_brt_config(cfg_dict)
    symbols = [s for s in MTS_SYMBOLS if (data_dir / f"{s}.csv").exists()]
    missing = [s for s in MTS_SYMBOLS if s not in symbols]
    if missing:
        print(f"[WARN] Missing CSV for: {missing}", file=sys.stderr)

    tasks = [(sym, str(data_dir / f"{sym}.csv"), cfg_dict) for sym in symbols]
    all_closed: list[BRTTrade] = []

    if n_workers > 0 and len(tasks) > 1:
        nw = min(n_workers, len(tasks), os.cpu_count() or 4)
        with ProcessPoolExecutor(max_workers=nw) as ex:
            for fut in as_completed(ex.submit(_run_one_symbol, t) for t in tasks):
                all_closed.extend(fut.result())
    else:
        for t in tasks:
            all_closed.extend(_run_one_symbol(t))

    metrics = compute_metrics(all_closed, cfg)
    return all_closed, metrics


def benchmark_summary(row: dict) -> dict:
    return {
        "total_trades": int(row.get("Total_Trades", 0)),
        "win_rate_pct": round(float(row.get("Pct_Wins", 0)), 2),
        "avg_profit_pct": round(float(row.get("Avg_PNL_Pct", 0)), 2),
        "win_loss_ratio": round(float(row.get("Win_Loss_Ratio", 0)), 3),
        "avg_days_in_trade": round(float(row.get("Avg_Days_Held", 0)), 1),
        "total_profit": round(float(row.get("Total_PNL", 0)), 2),
        "wins": int(row.get("Wins", 0)),
        "losses": int(row.get("Losses", 0)),
        "profit_factor": round(float(row.get("Profit_Factor", 0)), 3),
        "max_drawdown_pct": row.get("Max_DD", "N/A"),
    }


def run_one_param(task: tuple) -> tuple:
    cfg_dict, param_name, param_value, data_dir, backtest_workers = task
    try:
        _, metrics = run_markten_mts_batch(cfg_dict, Path(data_dir), n_workers=backtest_workers)
        row = _metrics_to_row(metrics, param_name, param_value)
        return (param_value, row)
    except Exception as e:
        print(f"  [Worker] {param_name}={param_value} failed: {e}", file=sys.stderr)
        return (param_value, None)


def _append_csv_schema_safe(path: Path, df: pd.DataFrame, expected_cols: list[str]) -> str:
    if not path.exists():
        df.to_csv(path, index=False)
        return str(path)
    with open(path, "r", newline="") as f:
        header = next(csv.reader(f), [])
    if header == list(expected_cols):
        df.to_csv(path, mode="a", index=False, header=False)
        return str(path)
    ts = datetime.now().strftime("%y%m%d%H%M%S")
    alt = path.with_name(f"{path.stem}_{ts}{path.suffix}")
    df.to_csv(alt, index=False)
    print(f"[WARN] {path.name} header mismatch; wrote {alt.name}")
    return str(alt)


def _row_with_cfg_cols(row: dict, cfg: dict) -> dict:
    out = {k: cfg.get(k, "") for k in MTS_CFG_COLS}
    out.update(row)
    return out


def _write_param_outputs(
    batch_results: list[dict],
    param_name: str,
    best_params: dict,
    baseline_row: dict,
    sweep_ts: str,
) -> None:
    if not batch_results:
        return

    for row in batch_results:
        if "Score" not in row:
            row["Score"] = calculate_score(row, baseline_row)

    batch_results.sort(key=lambda r: r.get("Score", 0), reverse=True)
    winner = batch_results[0]

    rows_out = []
    for row in batch_results:
        r = _row_with_cfg_cols(row, best_params)
        r["Timestamp_Drive"] = sweep_ts
        rows_out.append(r)

    df = pd.DataFrame(rows_out)
    for col in AUDIT_COLS_ORDER:
        if col not in df.columns:
            df[col] = ""
    df = df[AUDIT_COLS_ORDER]

    winner_df = df.iloc[[0]].copy()
    master_path = SCRIPT_DIR / MASTER_LOG
    winner_df.to_csv(master_path, mode="a", index=False, header=not master_path.exists())
    _append_csv_schema_safe(SCRIPT_DIR / GLOBAL_AUDIT_LOG, df, list(AUDIT_COLS_ORDER))

    summary_cols = MTS_CFG_COLS + [
        "Param_Name", "Param_Value", "Total_PNL", "Wins", "Losses", "BE", "Total_Trades",
        "Profit_Factor", "Ann_ROR", "Expectancy", "Avg_PNL_Pct", "Avg_Days_Held", "P90_Days",
        "Max_DD", "Losing_Streak", "Capital_Days", "Profit_Per_Capital_Day", "Score",
    ]
    summary_df = df[[c for c in summary_cols if c in df.columns]].copy()
    summary_path = SCRIPT_DIR / OPTIMIZER_SUMMARY_FILE
    summary_df.to_csv(summary_path, mode="a", index=False, header=not summary_path.exists())

    print(
        f"  Winner: {param_name}={winner['Param_Value']} "
        f"(Score={float(winner.get('Score', 0)):.1f}, PNL={float(winner.get('Total_PNL', 0)):.0f}, "
        f"trades={int(winner.get('Total_Trades', 0))})"
    )


def _append_csv(path: Path, df: pd.DataFrame, expected_cols: list[str]) -> None:
    _append_csv_schema_safe(path, df, expected_cols)


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="MTS MarkTen parameter optimizer")
    ap.add_argument("--benchmark-only", action="store_true", help="Run baseline only")
    ap.add_argument("--workers", "-w", type=int, default=MAX_WORKERS)
    ap.add_argument("--backtest-workers", "-b", type=int, default=BACKTEST_WORKERS)
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    ap.add_argument("--reset", action="store_true", help="Clear progress and re-run full sweep")
    args = ap.parse_args()

    os.chdir(SCRIPT_DIR)
    data_dir = Path(args.data_dir).resolve()
    opt_plan = OPTIMIZATION_PLAN
    progress_file = PROGRESS_FILE

    if args.reset and (SCRIPT_DIR / progress_file).exists():
        (SCRIPT_DIR / progress_file).unlink()

    print("\n[OK] MTS OPTIMIZER")
    print(f"[OK] Tune order: {', '.join(opt_plan.keys())}")
    print(f"[OK] Grid points: {sum(len(v) for v in opt_plan.values())}")
    print(f"[OK] Universe: {len(MTS_SYMBOLS)} symbols (mts_universe.py)")
    print(f"[OK] Gates: >= {MIN_TRADES} trades, Max_DD <= {MAX_DRAWDOWN_PCT}%")
    t0 = time.time()

    best_params = dict(current_best_params)
    _, metrics = run_markten_mts_batch(best_params, data_dir, n_workers=args.backtest_workers)
    baseline_row = _metrics_to_row(metrics, "baseline", "baseline")
    bench = benchmark_summary(baseline_row)
    bench["params"] = dict(best_params)
    bench["symbols"] = [s for s in MTS_SYMBOLS if (data_dir / f"{s}.csv").exists()]

    with open(SCRIPT_DIR / BENCHMARK_FILE, "w") as f:
        json.dump(bench, f, indent=2)

    print("\n=== MarkTen MTS BASELINE ===")
    for k, v in bench.items():
        if k not in ("params", "symbols"):
            print(f"  {k}: {v}")
    print(f"  (saved {BENCHMARK_FILE})")

    if args.benchmark_only:
        print(f"\n[OK] Done in {time.time() - t0:.1f}s")
        return 0

    completed: list[str] = []
    if (SCRIPT_DIR / progress_file).exists():
        try:
            prog = json.loads((SCRIPT_DIR / progress_file).read_text())
            completed = prog.get("completed_params", [])
            if prog.get("best_params"):
                best_params.update(prog["best_params"])
        except Exception:
            completed = []

    for param_name, values in opt_plan.items():
        if param_name in completed:
            continue
        print(f"\n--- Optimizing {param_name} ({len(values)} values) ---")
        batch_results = []
        tasks = []
        for val in values:
            trial = dict(best_params)
            trial[param_name] = val
            tasks.append((trial, param_name, val, str(data_dir), args.backtest_workers))

        if args.workers > 1:
            with ProcessPoolExecutor(max_workers=args.workers) as ex:
                futs = [ex.submit(run_one_param, t) for t in tasks]
                for fut in as_completed(futs):
                    val, row = fut.result()
                    if row:
                        batch_results.append(row)
                        print(f"  {param_name}={val}: trades={row['Total_Trades']} pnl={row['Total_PNL']:.0f}")
        else:
            for t in tasks:
                val, row = run_one_param(t)
                if row:
                    batch_results.append(row)
                    print(f"  {param_name}={val}: trades={row['Total_Trades']} pnl={row['Total_PNL']:.0f}")

        if batch_results:
            for row in batch_results:
                row["Score"] = calculate_score(row, baseline_row)
            batch_results.sort(key=lambda r: r.get("Score", 0), reverse=True)
            best_val = batch_results[0]["Param_Value"]
            if batch_results[0]["Score"] > 0:
                best_params[param_name] = best_val
            sweep_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            _write_param_outputs(batch_results, param_name, best_params, baseline_row, sweep_ts)

        completed.append(param_name)
        with open(SCRIPT_DIR / progress_file, "w") as f:
            json.dump({"completed_params": completed, "best_params": best_params}, f, indent=2)

    # Final optimized benchmark
    _, final_metrics = run_markten_mts_batch(best_params, data_dir, n_workers=args.backtest_workers)
    final_row = _metrics_to_row(final_metrics, "final", "final")
    optimized_bench = benchmark_summary(final_row)
    optimized_bench["params"] = dict(best_params)

    with open(SCRIPT_DIR / BEST_SETTINGS_FILE, "w") as f:
        json.dump({"best_params": best_params, "baseline": bench, "optimized": optimized_bench}, f, indent=2)

    with open(SCRIPT_DIR / BENCHMARK_FILE, "w") as f:
        json.dump({"baseline": bench, "optimized": optimized_bench}, f, indent=2)

    print(f"\n[OK] Best params: {best_params}")
    print("\n=== MarkTen MTS OPTIMIZED ===")
    for k, v in optimized_bench.items():
        if k != "params":
            print(f"  {k}: {v}")
    print(f"[OK] Wrote {MASTER_LOG}, {GLOBAL_AUDIT_LOG}, {OPTIMIZER_SUMMARY_FILE}, {BEST_SETTINGS_FILE}")
    print(f"[OK] Total elapsed: {(time.time() - t0) / 60:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
