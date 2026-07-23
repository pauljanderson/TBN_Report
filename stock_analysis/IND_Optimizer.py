"""
IND_Optimizer: Grid-optimizes IND (indicator_buy=only) parameters via rocket_brt.run_brt_backtest_batch().

Scoring weights (baseline-relative, baseline score = 100):
  profit/day 15%, PnL 15%, drawdown 15%, profit factor 15%, expectancy 15%,
  win/loss ratio 10%, losing streak 10%, p90 days 5%.

Hard gates: >= MIN_TRADES trades, Max_DD <= MAX_DRAWDOWN_PCT.
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import fields
from datetime import datetime
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).parent.resolve()
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from rocket_brt import BRTConfig, run_brt_backtest_batch

REPO_ROOT = SCRIPT_DIR.parent
DATA_DIR = str(REPO_ROOT / "data" / "newdata" / "data")
MASTER_LOG = "IND_Optimization_Master_Log.csv"
BEST_SETTINGS_FILE = "IND_Final_Optimized_Settings.json"
GLOBAL_AUDIT_LOG = "IND_Optimization_Audit.csv"
OPTIMIZER_SUMMARY_FILE = "IND_Optimizer_Summary.csv"
PROGRESS_FILE = "IND_optimizer_progress.json"
STATUS_FILE = "IND_optimizer_status.txt"

MAX_WORKERS = 2  # parallel param sweeps (each backtest uses BACKTEST_WORKERS)
BACKTEST_WORKERS = 6  # symbol parallelism inside each backtest

MIN_TRADES = 350
MAX_DRAWDOWN_PCT = 22.0

W_PROFIT_PER_CAP_DAY = 15
W_TOTAL_PROFIT = 15
W_MAX_DRAWDOWN = 15
W_PROFIT_FACTOR = 15
W_EXPECTANCY = 15
W_WIN_LOSS_RATIO = 10
W_LOSING_STREAK = 10
W_P90_DAYS = 5

IND_CFG_COLS = [
    "target_pct", "trailing_stop_increment", "strong_pre_pivot_pct", "strong_post_pivot_pct",
    "atr_progress", "atr_days", "compute_beta", "min_avg_volume_10d_at_entry",
    "min_atr_pct_at_trigger", "max_atr_pct_at_trigger", "use_indicators", "indicator_buy",
    "indicator_diff", "indicator_sides", "transaction_type", "atr_target", "atr_stop",
    "max_ind_entry_neutral_n", "min_ind_score", "min_ind_entry_bull_n",
    "sell_ind_diff_below", "exit_ind_diff_only", "yh_zones", "brt_zones",
    "stop_pct", "aggressive", "aggressive_avg_positions", "compute_equity_metrics",
]

AUDIT_COLS_ORDER = (
    ["Timestamp_Drive"]
    + IND_CFG_COLS
    + ["Param_Name", "Param_Value"]
    + ["Total_PNL", "Wins", "Losses", "BE", "Pct_Wins", "Pct_Losses",
       "Win_Loss_Ratio", "Win_Loss_Ratio_Dollar", "Total_Trades", "Profit_Factor",
       "Avg_Win_Pct", "Avg_Loss_Pct", "Avg_PNL_Pct", "Expectancy", "Expectancy_Pct"]
    + ["Avg_Days_Held", "Median_Days_Held", "P90_Days", "Capital_Days",
       "Profit_Per_Capital_Day", "Ann_ROR"]
    + ["Max_DD", "Losing_Streak", "DD_Per_Trade"]
    + ["CES_AVG", "CES_Median", "Pct_PNL_Top10", "Pct_PNL_Bottom10", "Max_Positions"]
    + ["Score"]
)

# Baseline = prior IND_Final_Optimized_Settings winners (profitability-focused re-sweep)
current_best_params = {
    "target_pct": 1.21,
    "trailing_stop_increment": 0,
    "strong_pre_pivot_pct": 0.081,
    "strong_post_pivot_pct": 0.109,
    "atr_progress": 0,
    "atr_days": 0,
    "compute_beta": True,
    "min_avg_volume_10d_at_entry": 0,
    "min_atr_pct_at_trigger": 8.1,
    "max_atr_pct_at_trigger": 0,
    "use_indicators": True,
    "indicator_buy": "only",
    "indicator_diff": 9,
    "indicator_sides": "long",
    "transaction_type": "long",
    "atr_target": 2.0,
    "atr_stop": 1.2,
    "max_ind_entry_neutral_n": 35,
    "min_ind_score": -1,
    "yh_zones": False,
    "brt_zones": False,
    "stop_pct": 0,
    "aggressive": True,
    "aggressive_avg_positions": 25,
    "compute_equity_metrics": True,
}

# Expanded grid around prior winners + profitability levers (target / sizing)
OPTIMIZATION_PLAN = {
    "indicator_diff": (7, 8, 9, 10, 11, 12),
    "atr_target": (1.6, 1.8, 2.0, 2.2, 2.4, 2.6),
    "atr_stop": (0.9, 1.0, 1.1, 1.2, 1.3, 1.4),
    "min_atr_pct_at_trigger": (5.0, 6.0, 7.0, 8.1, 9.0, 10.0, 11.0),
    "max_ind_entry_neutral_n": (25, 30, 35, 40, 45, 50),
    "min_ind_score": (-2, -1, 0, 5, 10, 15),
    "target_pct": (1.15, 1.18, 1.21, 1.24, 1.27, 1.30),
    "aggressive_avg_positions": (15, 20, 25, 30, 35),
}


def _append_csv_schema_safe(path: str, df: pd.DataFrame, expected_cols: list[str]) -> str:
    p = Path(path)
    if not p.exists():
        df.to_csv(p, mode="w", index=False, header=True)
        return str(p)
    try:
        with open(p, "r", newline="") as f:
            existing_header = next(csv.reader(f), [])
    except Exception:
        existing_header = []
    if existing_header == list(expected_cols):
        df.to_csv(p, mode="a", index=False, header=False)
        return str(p)
    ts = datetime.now().strftime("%y%m%d%H%M%S")
    new_path = p.with_name(f"{p.stem}_{ts}{p.suffix}")
    df.to_csv(new_path, mode="w", index=False, header=True)
    print(f"[WARN] {p.name} header mismatch; wrote new audit log: {new_path.name}")
    return str(new_path)


def _cfg_dict_to_brt_config(cfg_dict: dict) -> BRTConfig:
    valid = {f.name for f in fields(BRTConfig)}
    return BRTConfig(**{k: v for k, v in cfg_dict.items() if k in valid})


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
    max_dd = max_dd_raw if (max_dd_raw is None or max_dd_raw == "N/A" or str(max_dd_raw).strip() == "N/A") else num(max_dd_raw)

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
        "Max_DD": max_dd,
        "Losing_Streak": int(metrics.get("Losing_Streak", 0)),
        "DD_Per_Trade": num(metrics.get("DD_Per_Trade", 0)),
        "CES_AVG": num(metrics.get("CES_AVG", 0)),
        "CES_Median": num(metrics.get("CES_Median", 0)),
        "Pct_PNL_Top10": num(metrics.get("Pct_PNL_Top10", 0)),
        "Pct_PNL_Bottom10": num(metrics.get("Pct_PNL_Bottom10", 0)),
        "Max_Positions": int(metrics.get("Max_Positions", 1)),
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


def _get_baseline_row(batch_results: list[dict], param_name: str, best_params: dict) -> dict | None:
    target = best_params.get(param_name)
    for row in batch_results:
        if row.get("Param_Value") == target:
            return row
    return batch_results[0] if batch_results else None


def _win_loss_ratio(row: dict) -> float:
    wins = int(row.get("Wins", 0))
    losses = int(row.get("Losses", 0))
    if losses <= 0:
        return 10.0 if wins > 0 else 1.0
    return wins / losses


def _passes_hard_gates(row: dict) -> bool:
    total_trades = int(row.get("Total_Trades", 0))
    if total_trades < MIN_TRADES:
        return False
    max_dd = _safe_num(row.get("Max_DD", 0))
    if max_dd > MAX_DRAWDOWN_PCT:
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


def run_one_param(task: tuple) -> tuple:
    cfg_dict, param_name, param_value, _task_id, data_dir, backtest_workers = task
    cfg = _cfg_dict_to_brt_config(cfg_dict)
    try:
        _, metrics = run_brt_backtest_batch(data_dir, cfg, n_workers=backtest_workers)
        row = _metrics_to_row(metrics, param_name, param_value)
        return (param_value, row)
    except Exception as e:
        print(f"  [Worker] {param_name}={param_value} failed: {e}", file=sys.stderr)
        return (param_value, None)


def sanitize_value(v):
    return v.item() if hasattr(v, "item") else v


def load_progress(initial_params: dict) -> tuple[list, dict]:
    path = SCRIPT_DIR / PROGRESS_FILE
    if path.exists():
        try:
            with open(path) as f:
                data = json.load(f)
            return data.get("completed_params", []), data.get("best_params", initial_params)
        except Exception:
            pass
    return [], initial_params


def save_progress(completed_params: list, best_params: dict) -> None:
    path = SCRIPT_DIR / PROGRESS_FILE
    with open(path, "w") as f:
        json.dump({
            "completed_params": completed_params,
            "best_params": {k: sanitize_value(v) for k, v in best_params.items()},
        }, f, indent=2)


def _fmt_dur(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    return f"{m}m {s:02d}s"


def _plan_trial_counts(completed_params: list) -> tuple[int, int]:
    """Return (already_done_trials_from_completed_params, remaining_trials)."""
    done = sum(len(OPTIMIZATION_PLAN[p]) for p in completed_params if p in OPTIMIZATION_PLAN)
    remaining = sum(
        len(vals) for p, vals in OPTIMIZATION_PLAN.items() if p not in completed_params
    )
    return done, remaining


def write_status(
    *,
    started_at: str,
    session_start: float,
    current_param: str,
    current_value,
    trials_done: int,
    trials_total: int,
    note: str = "",
) -> None:
    elapsed = time.time() - session_start
    remaining = max(0, trials_total - trials_done)
    if trials_done > 0 and remaining > 0:
        eta_sec = (elapsed / trials_done) * remaining
        eta_str = _fmt_dur(eta_sec)
    elif remaining == 0:
        eta_str = "0s (done)"
    else:
        eta_str = "estimating..."
    pct = (100.0 * trials_done / trials_total) if trials_total else 100.0
    lines = [
        "IND Optimizer Status",
        f"started_at:     {started_at}",
        f"updated_at:     {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"elapsed:        {_fmt_dur(elapsed)}",
        f"current_param:  {current_param}",
        f"current_value:  {current_value}",
        f"trials:         {trials_done}/{trials_total} ({pct:.1f}%)",
        f"eta:            {eta_str}",
        f"note:           {note}".rstrip(),
        "",
        f"Watch live: Get-Content -Wait stock_analysis\\{STATUS_FILE}",
    ]
    path = SCRIPT_DIR / STATUS_FILE
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"  [status] elapsed={_fmt_dur(elapsed)}  trials={trials_done}/{trials_total}  "
        f"ETA={eta_str}  ({current_param}={current_value})"
    )


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="IND Parameter Optimizer")
    ap.add_argument("--workers", "-w", type=int, default=MAX_WORKERS,
                    help=f"Parallel param sweeps (default {MAX_WORKERS})")
    ap.add_argument("--backtest-workers", "-b", type=int, default=BACKTEST_WORKERS,
                    help=f"Symbol workers per backtest (default {BACKTEST_WORKERS})")
    ap.add_argument("--data-dir", default=DATA_DIR, help="Data directory with ticker CSVs")
    ap.add_argument("--reset", action="store_true", help="Clear saved progress and start fresh")
    args = ap.parse_args()
    workers = max(1, args.workers)
    backtest_workers = max(1, args.backtest_workers)
    data_dir = str(Path(args.data_dir).resolve())

    if args.reset and (SCRIPT_DIR / PROGRESS_FILE).exists():
        (SCRIPT_DIR / PROGRESS_FILE).unlink()

    session_start = time.time()
    ts_start = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("\n[OK] IND OPTIMIZATION SESSION START")
    print(f"[OK] Started at: {ts_start}")
    print(f"[OK] Gates: >= {MIN_TRADES} trades, Max_DD <= {MAX_DRAWDOWN_PCT}%")
    print("=" * 60)
    os.chdir(SCRIPT_DIR)

    completed_params, best_params = load_progress(current_best_params)
    best_params = {k: sanitize_value(v) for k, v in best_params.items()}
    for k, v in current_best_params.items():
        if k not in best_params:
            best_params[k] = v
    for p_name, values in OPTIMIZATION_PLAN.items():
        if p_name not in best_params:
            best_params[p_name] = values[0]

    print(f"[OK] Data dir: {data_dir}")
    print(f"[OK] Param workers: {workers}, backtest workers: {backtest_workers}")
    print(f"[OK] Completed: {completed_params}")
    print(f"[OK] Remaining: {[p for p in OPTIMIZATION_PLAN if p not in completed_params]}")
    prior_done, remaining_trials = _plan_trial_counts(completed_params)
    trials_total = prior_done + remaining_trials
    trials_done = prior_done
    print(f"[OK] Grid trials: {trials_done}/{trials_total} already done; {remaining_trials} remaining")
    print(f"[OK] Status file: {SCRIPT_DIR / STATUS_FILE}")
    print("(Ctrl+C to stop; progress is saved so you can resume later)")
    write_status(
        started_at=ts_start,
        session_start=session_start,
        current_param="(starting)",
        current_value="",
        trials_done=trials_done,
        trials_total=trials_total,
        note="session start",
    )

    try:
        for param_name, values in OPTIMIZATION_PLAN.items():
            if param_name in completed_params:
                continue

            print(f"\n--- Optimizing {param_name} ({len(values)} values) ---")
            write_status(
                started_at=ts_start,
                session_start=session_start,
                current_param=param_name,
                current_value="(running)",
                trials_done=trials_done,
                trials_total=trials_total,
                note=f"sweeping {len(values)} values",
            )
            tasks = [
                ({**best_params, param_name: v}, param_name, v, i, data_dir, backtest_workers)
                for i, v in enumerate(values)
            ]
            batch_results = []

            with ProcessPoolExecutor(max_workers=workers) as ex:
                for future in as_completed(ex.submit(run_one_param, t) for t in tasks):
                    param_value, row = future.result()
                    trials_done += 1
                    if row:
                        cfg_full = {**best_params, param_name: sanitize_value(param_value)}
                        for k in IND_CFG_COLS:
                            row[k] = cfg_full.get(k, "")
                        batch_results.append(row)
                        print(
                            f"  done {param_name}={param_value}: trades={row['Total_Trades']} "
                            f"pnl={_safe_num(row['Total_PNL']):.0f} dd={_safe_num(row['Max_DD']):.1f}% "
                            f"pf={_safe_num(row['Profit_Factor']):.2f} "
                            f"ppcd={_safe_num(row['Profit_Per_Capital_Day']):.2f}"
                        )
                    else:
                        print(f"  fail {param_name}={param_value}")
                    write_status(
                        started_at=ts_start,
                        session_start=session_start,
                        current_param=param_name,
                        current_value=param_value,
                        trials_done=trials_done,
                        trials_total=trials_total,
                        note="trial complete",
                    )

            if not batch_results:
                print(f"  [WARN] No valid results for {param_name}")
                completed_params.append(param_name)
                save_progress(completed_params, best_params)
                continue

            df = pd.DataFrame(batch_results)
            baseline_row = _get_baseline_row(batch_results, param_name, best_params)
            df["Score"] = df.apply(lambda r: calculate_score(r.to_dict(), baseline_row), axis=1)
            df = df.sort_values("Score", ascending=False)
            winner = df.iloc[0]
            best_params[param_name] = sanitize_value(winner["Param_Value"])

            completed_params.append(param_name)
            save_progress(completed_params, best_params)

            ts = datetime.now().strftime("%y%m%d%H%M%S")

            def _drive_link(r):
                pv = str(sanitize_value(r.get("Param_Value", ""))).replace(" ", "_")
                pn = str(r.get("Param_Name", "")).replace(" ", "_")
                label = f"{ts}_{pn}_{pv}"
                return f'=hyperlink("https://drive.google.com/drive/search?q={label}","{label}")'

            df["Timestamp_Drive"] = df.apply(_drive_link, axis=1)
            ordered = [c for c in AUDIT_COLS_ORDER if c in df.columns]
            extra = [c for c in df.columns if c not in AUDIT_COLS_ORDER]
            df_audit = df[ordered + extra]

            winner_df = df.iloc[[0]].copy()
            winner_df.to_csv(MASTER_LOG, mode="a", index=False, header=not Path(MASTER_LOG).exists())
            _append_csv_schema_safe(GLOBAL_AUDIT_LOG, df_audit, list(AUDIT_COLS_ORDER))

            summary_cols = IND_CFG_COLS + ["Param_Name", "Param_Value"] + [
                "Total_PNL", "Wins", "Losses", "BE", "Total_Trades", "Profit_Factor", "Ann_ROR",
                "CES_AVG", "Expectancy", "Avg_PNL_Pct", "Avg_Days_Held", "P90_Days", "Max_DD",
                "Losing_Streak", "Capital_Days", "Max_Positions", "Profit_Per_Capital_Day", "Score",
            ]
            summary_df = df[[c for c in summary_cols if c in df.columns]].copy()
            summary_df.to_csv(
                OPTIMIZER_SUMMARY_FILE, mode="a", index=False,
                header=not Path(OPTIMIZER_SUMMARY_FILE).exists(),
            )

            print(
                f"  Winner: {param_name}={best_params[param_name]} (Score={_safe_num(winner['Score']):.2f}, "
                f"PNL={_safe_num(winner['Total_PNL']):.0f}, DD={_safe_num(winner['Max_DD']):.1f}%, "
                f"PF={_safe_num(winner['Profit_Factor']):.2f}, trades={int(winner['Total_Trades'])})"
            )

    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Saving progress...")
        save_progress(completed_params, best_params)
        final = {k: sanitize_value(v) for k, v in best_params.items()}
        with open(BEST_SETTINGS_FILE, "w") as f:
            json.dump(final, f, indent=2)
        write_status(
            started_at=ts_start,
            session_start=session_start,
            current_param="(interrupted)",
            current_value="",
            trials_done=trials_done,
            trials_total=trials_total,
            note="Ctrl+C — progress saved",
        )
        print(f"[OK] Progress saved to {PROGRESS_FILE}")
        return 130

    final = {k: sanitize_value(v) for k, v in best_params.items()}
    with open(BEST_SETTINGS_FILE, "w") as f:
        json.dump(final, f, indent=2)

    elapsed = time.time() - session_start
    write_status(
        started_at=ts_start,
        session_start=session_start,
        current_param="(complete)",
        current_value="",
        trials_done=trials_total,
        trials_total=trials_total,
        note=f"finished in {_fmt_dur(elapsed)}",
    )
    print("\n" + "=" * 60)
    print(f"[OK] IND OPTIMIZATION COMPLETE ({elapsed/60:.1f} min)")
    print(f"[OK] Settings saved to {BEST_SETTINGS_FILE}")
    print(f"[OK] Summary: {OPTIMIZER_SUMMARY_FILE}")
    try:
        subprocess.run(
            ["powershell", "-Command", "[Console]::Beep(750, 2000)"],
            check=False, capture_output=True, timeout=3,
        )
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
