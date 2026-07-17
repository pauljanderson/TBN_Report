"""
RL_Optimizer: Grid-optimizes Rocket Launcher (50-SMA) parameters via rocket_rl.run_rl_backtest_batch().

Same scoring model as IND_Optimizer (baseline-relative score = 100):
  profit/day 15%, PnL 15%, drawdown 15%, profit factor 15%, expectancy 15%,
  win/loss ratio 10%, losing streak 10%, p90 days 5%.

Hard gates: >= MIN_TRADES closed trades, Max_DD <= MAX_DRAWDOWN_PCT.
Default universe: data/rl_gold_universe.txt (75 symbols, AWK parity set).
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
from dataclasses import fields
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

SCRIPT_DIR = Path(__file__).parent.resolve()
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from rocket_brt import (  # noqa: E402
    BRTConfig,
    BRTTrade,
    HAS_EQUITY_METRICS,
    _compute_equity_metrics,
    compute_metrics,
    load_all_tickers,
)
from rocket_rl import RLClosedRow, RLOpenRow, run_rl_backtest_batch  # noqa: E402
from rocket_rl_config import RLConfig  # noqa: E402

DATA_DIR = str(REPO_ROOT / "data" / "newdata" / "data")
GOLD_UNIVERSE = REPO_ROOT / "data" / "rl_gold_universe.txt"
MASTER_LOG = "RL_Optimization_Master_Log.csv"
BEST_SETTINGS_FILE = "RL_Final_Optimized_Settings.json"
GLOBAL_AUDIT_LOG = "RL_Optimization_Audit.csv"
OPTIMIZER_SUMMARY_FILE = "RL_Optimizer_Summary.csv"
PROGRESS_FILE = "RL_optimizer_progress.json"

MAX_WORKERS = 1  # sequential param sweeps (avoid nested ProcessPool on Windows)
BACKTEST_WORKERS = 5

MIN_TRADES = 150
MAX_DRAWDOWN_PCT = 20.0

W_PROFIT_PER_CAP_DAY = 15
W_TOTAL_PROFIT = 15
W_MAX_DRAWDOWN = 15
W_PROFIT_FACTOR = 15
W_EXPECTANCY = 15
W_WIN_LOSS_RATIO = 10
W_LOSING_STREAK = 10
W_P90_DAYS = 5

# AWK portfolio_audit.awk BEGIN defaults (sequential one-at-a-time grid)
current_best_params: dict[str, Any] = {
    "rl_cash": 47_500.0,
    "rl_dip_pct": 1.024,
    "rl_50_sma_lookback": 4,
    "rl_stop_pct": 0.934,
    "rl_target_pct": 1.20,
    "rl_too_high": 1.14,
    "rl_expansion": 1.163,
    "rl_acc_min": 8,
    "rl_acc_count": 10,
    "rl_expansion_lookback_days": 10,
    "rl_cut_the_losers": 0.25,
    "rl_atr_low_percent": 0.0244,
    "rl_atr_high_percent": 0.0848,
    "rl_atr_high_value": 200.0,
    "rl_low_price": 0.000001,
    "rl_peak_threshold_max": 2.0,
    "rl_slope_period": 30,
    "rl_slope_threshold": 0.0643,
    "rl_shock_threshold": 0.0,
    "rl_exit_percent": 0.29,
    "rl_flush_days": 0,
    "rl_spy_inclusion": False,
    "rl_avg_vol_days": 50,
    "rl_vol_pct_threshold": 0.0,
}

RL_CFG_COLS = list(current_best_params.keys())

OPTIMIZATION_PLAN: dict[str, tuple[Any, ...]] = {
    "rl_dip_pct": (1.018, 1.020, 1.022, 1.024, 1.026, 1.028),
    "rl_stop_pct": (0.920, 0.927, 0.934, 0.940, 0.945),
    "rl_target_pct": (1.15, 1.18, 1.20, 1.22, 1.25),
    "rl_expansion": (1.14, 1.15, 1.163, 1.17, 1.18),
    "rl_acc_min": (6, 7, 8, 9, 10),
    "rl_cut_the_losers": (0.15, 0.20, 0.25, 0.30, 0.35),
    "rl_atr_low_percent": (0.020, 0.0244, 0.028),
    "rl_atr_high_percent": (0.075, 0.0848, 0.095),
    "rl_slope_threshold": (0.0, 0.05, 0.0643, 0.08),
    "rl_exit_percent": (0.25, 0.29, 0.33, 0.35),
}

AUDIT_COLS_ORDER = (
    ["Timestamp_Drive"]
    + RL_CFG_COLS
    + ["Param_Name", "Param_Value"]
    + [
        "Total_PNL", "Wins", "Losses", "BE", "Pct_Wins", "Pct_Losses",
        "Win_Loss_Ratio", "Win_Loss_Ratio_Dollar", "Total_Trades", "Profit_Factor",
        "Avg_Win_Pct", "Avg_Loss_Pct", "Avg_PNL_Pct", "Expectancy", "Expectancy_Pct",
        "Avg_Days_Held", "Median_Days_Held", "P90_Days", "Capital_Days",
        "Profit_Per_Capital_Day", "Ann_ROR",
        "Max_DD", "Losing_Streak", "DD_Per_Trade", "Score",
    ]
)


def load_symbol_list(path: Path) -> list[str]:
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        t = line.strip()
        if not t or t.startswith("#"):
            continue
        out.append(t.upper())
    return out


def _rl_cfg_from_dict(d: dict[str, Any]) -> RLConfig:
    base = {f.name: getattr(RLConfig(), f.name) for f in fields(RLConfig)}
    key_map = {
        "rl_expansion_lookback_days": "expansion_lookback_days",
        "rl_peak_threshold_max": "peak_threshold_max",
        "rl_spy_inclusion": "spy_inclusion",
        "rl_avg_vol_days": "avg_vol_days",
        "rl_vol_pct_threshold": "vol_pct_threshold",
    }
    for k, v in d.items():
        if k in key_map:
            base[key_map[k]] = v
        elif k.startswith("rl_"):
            base[k] = v
        elif hasattr(RLConfig, k):
            base[k] = v
    return RLConfig(**base)


def _closed_to_trade(row: RLClosedRow, cash: float) -> BRTTrade:
    dollars = (cash / row.entry_price) * (row.exit_price - row.entry_price) if row.entry_price > 0 else 0.0
    return BRTTrade(
        symbol=row.symbol,
        date_opened=row.entry_iso,
        entry_price=row.entry_price,
        stop_price=row.original_stop,
        target_price=row.original_target,
        date_closed=row.exit_iso,
        exit_price=row.exit_price,
        exit_type=row.exit_type,
        days_held=row.hold_days,
        pnl_pct=row.pnl_pct,
        pnl_dollars=dollars,
        max_price=row.max_price,
    )


def _open_to_trade(row: RLOpenRow, cash: float) -> BRTTrade:
    cur = row.current_price if row.current_price > 0 else row.entry_price * (1.0 + row.pnl_pct / 100.0)
    dollars = (cash / row.entry_price) * (cur - row.entry_price) if row.entry_price > 0 else 0.0
    return BRTTrade(
        symbol=row.symbol,
        date_opened=row.entry_iso,
        entry_price=row.entry_price,
        stop_price=row.stop,
        target_price=row.target,
        pnl_pct=row.pnl_pct,
        pnl_dollars=dollars,
        max_price=row.entry_price,
    )


def _metrics_from_rl_results(
    closed: list[RLClosedRow],
    open_rows: list[RLOpenRow],
    tickers: dict[str, pd.DataFrame],
    cash: float,
) -> dict[str, Any]:
    trades = [_closed_to_trade(r, cash) for r in closed]
    opens = [_open_to_trade(r, cash) for r in open_rows]
    cfg = BRTConfig(brt_cash=cash, compute_equity_metrics=True)
    metrics = dict(compute_metrics(trades, cfg))
    if HAS_EQUITY_METRICS and trades and tickers and _compute_equity_metrics:
        try:
            equity = _compute_equity_metrics(
                trades,
                opens,
                tickers,
                cash,
                initial_capital=cfg.initial_capital,
                aggressive=False,
            )
            metrics["Max_Drawdown"] = equity["Max_Drawdown"]
            metrics["Max_Days_Underwater"] = equity.get("Max_Days_Underwater", 0)
            metrics["Pct_Days_Underwater"] = equity.get("Pct_Days_Underwater", 0)
            md = equity["Max_Drawdown"]
            if md and str(md).strip() != "N/A":
                try:
                    pct_val = float(str(md).replace("%", "").strip()) / 100
                    metrics["DD_Per_Trade"] = f"{(pct_val / len(trades)):.4f}" if trades else "N/A"
                except (ValueError, TypeError):
                    metrics["DD_Per_Trade"] = "N/A"
        except Exception as e:
            print(f"[WARN] RL equity metrics: {e}", file=sys.stderr)
    return metrics


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
    if int(row.get("Total_Trades", 0)) < MIN_TRADES:
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


def sanitize_value(v):
    return v.item() if hasattr(v, "item") else v


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


# Set once in main(); run_one_param reads these (no nested ProcessPool for param sweeps).
_WORK_SYMBOLS: list[str] = []
_WORK_TICKERS: dict[str, pd.DataFrame] = {}
_WORK_SPY_DF: pd.DataFrame | None = None
_WORK_DATA_DIR: str = ""


def _init_worker(symbols, tickers, spy_df, data_dir):
    global _WORK_SYMBOLS, _WORK_TICKERS, _WORK_SPY_DF, _WORK_DATA_DIR
    _WORK_SYMBOLS = list(symbols)
    _WORK_TICKERS = tickers
    _WORK_SPY_DF = spy_df
    _WORK_DATA_DIR = data_dir


def run_one_param(task: tuple) -> tuple:
    cfg_dict, param_name, param_value, _task_id = task
    try:
        rl_cfg = _rl_cfg_from_dict(cfg_dict)
        closed, open_rows, _, _ = run_rl_backtest_batch(
            _WORK_SYMBOLS or [],
            _WORK_TICKERS or {},
            rl_cfg,
            spy_df=_WORK_SPY_DF,
            workers=BACKTEST_WORKERS,
            data_dir=Path(_WORK_DATA_DIR),
        )
        metrics = _metrics_from_rl_results(closed, open_rows, _WORK_TICKERS or {}, rl_cfg.rl_cash)
        row = _metrics_to_row(metrics, param_name, param_value)
        return (param_value, row)
    except Exception as e:
        print(f"  [Worker] {param_name}={param_value} failed: {e}", file=sys.stderr)
        return (param_value, None)


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
        json.dump(
            {
                "completed_params": completed_params,
                "best_params": {k: sanitize_value(v) for k, v in best_params.items()},
            },
            f,
            indent=2,
        )


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Rocket Launcher (RL) parameter optimizer")
    ap.add_argument("--workers", "-w", type=int, default=MAX_WORKERS)
    ap.add_argument("--symbols-file", default=str(GOLD_UNIVERSE))
    ap.add_argument("--data-dir", default=DATA_DIR)
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()
    workers = max(1, args.workers)
    data_dir = str(Path(args.data_dir).resolve())
    symbols = load_symbol_list(Path(args.symbols_file))
    if not symbols:
        print("[ERROR] No symbols loaded.", file=sys.stderr)
        return 1

    if args.reset and (SCRIPT_DIR / PROGRESS_FILE).exists():
        (SCRIPT_DIR / PROGRESS_FILE).unlink()

    os.chdir(SCRIPT_DIR)
    session_start = time.time()
    print("\n[OK] RL OPTIMIZATION SESSION START")
    print(f"[OK] Universe: {len(symbols)} symbols from {args.symbols_file}")
    print(f"[OK] Gates: >= {MIN_TRADES} trades, Max_DD <= {MAX_DRAWDOWN_PCT}%")
    print(f"[OK] Param workers: {workers}, backtest workers: {BACKTEST_WORKERS}")
    print("=" * 60)

    sym_set = set(symbols)
    tickers = load_all_tickers(data_dir, symbols_filter=sym_set)
    spy_path = Path(data_dir) / "SPY.csv"
    spy_df = pd.read_csv(spy_path) if spy_path.is_file() else None
    if spy_df is not None and "SPY" not in tickers:
        tickers["SPY"] = spy_df

    completed_params, best_params = load_progress(current_best_params)
    best_params = {k: sanitize_value(v) for k, v in best_params.items()}
    for k, v in current_best_params.items():
        if k not in best_params:
            best_params[k] = v
    for p_name, values in OPTIMIZATION_PLAN.items():
        if p_name not in best_params:
            best_params[p_name] = values[0]

    print(f"[OK] Completed dimensions: {completed_params}")
    print(f"[OK] Remaining: {[p for p in OPTIMIZATION_PLAN if p not in completed_params]}")

    try:
        for param_name, values in OPTIMIZATION_PLAN.items():
            if param_name in completed_params:
                continue

            print(f"\n--- Optimizing {param_name} ({len(values)} values) ---")
            tasks = [
                ({**best_params, param_name: v}, param_name, v, i)
                for i, v in enumerate(values)
            ]
            batch_results: list[dict] = []
            _init_worker(symbols, tickers, spy_df, data_dir)

            for t in tasks:
                param_value, row = run_one_param(t)
                if row:
                    cfg_full = {**best_params, param_name: sanitize_value(param_value)}
                    for k in RL_CFG_COLS:
                        row[k] = cfg_full.get(k, "")
                    batch_results.append(row)
                    print(
                        f"  done {param_name}={param_value}: trades={row['Total_Trades']} "
                        f"pnl={_safe_num(row['Total_PNL']):.0f} dd={_safe_num(row['Max_DD']):.1f}% "
                        f"pf={_safe_num(row['Profit_Factor']):.2f} "
                        f"ppcd={_safe_num(row['Profit_Per_Capital_Day']):.2f} "
                        f"score_gate={'PASS' if _passes_hard_gates(row) else 'FAIL'}",
                        flush=True,
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

            df.iloc[[0]].to_csv(MASTER_LOG, mode="a", index=False, header=not Path(MASTER_LOG).exists())
            _append_csv_schema_safe(GLOBAL_AUDIT_LOG, df_audit, list(AUDIT_COLS_ORDER))

            summary_cols = RL_CFG_COLS + ["Param_Name", "Param_Value"] + [
                "Total_PNL", "Wins", "Losses", "BE", "Total_Trades", "Profit_Factor", "Ann_ROR",
                "Expectancy", "Avg_PNL_Pct", "Avg_Days_Held", "P90_Days", "Max_DD",
                "Losing_Streak", "Capital_Days", "Profit_Per_Capital_Day", "Score",
            ]
            summary_df = df[[c for c in summary_cols if c in df.columns]].copy()
            summary_df.to_csv(
                OPTIMIZER_SUMMARY_FILE,
                mode="a",
                index=False,
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
        return 130

    final = {k: sanitize_value(v) for k, v in best_params.items()}
    with open(BEST_SETTINGS_FILE, "w") as f:
        json.dump(final, f, indent=2)

    elapsed = time.time() - session_start
    print("\n" + "=" * 60)
    print(f"[OK] RL OPTIMIZATION COMPLETE ({elapsed/60:.1f} min)")
    print(f"[OK] Best settings: {BEST_SETTINGS_FILE}")
    print(json.dumps(final, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
