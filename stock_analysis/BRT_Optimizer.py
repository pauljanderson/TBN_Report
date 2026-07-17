"""
BRT_Optimizer: Grid-optimizes Rocket BRT parameters by running rocket_brt.run_brt_backtest_batch()
with different configs, scoring on CES/ROR/ProfitFactor/trades, and ratcheting risk baselines.

Similar to RocketOptimizer but for the BRT (Key Level) system. Uses ProcessPoolExecutor for
parallel runs across parameter values. Each worker runs a full backtest over all tickers.
"""
from __future__ import annotations

import json
import os
import csv
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import pandas as pd

# Add parent for imports
SCRIPT_DIR = Path(__file__).parent.resolve()
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from rocket_brt import BRTConfig, run_brt_backtest_batch

# --- CONFIGURATION ---
REPO_ROOT = SCRIPT_DIR.parent
DATA_DIR = str(REPO_ROOT / "data" / "newdata" / "data")
MASTER_LOG = "BRT_Optimization_Master_Log.csv"
BEST_SETTINGS_FILE = "BRT_Final_Optimized_Settings.json"
GLOBAL_AUDIT_LOG = "BRT_Optimization_Audit.csv"
OPTIMIZER_SUMMARY_FILE = "BRT_Optimizer_Summary.csv"  # Primary file: inputs + outputs per run (like BRT_Report)
ALL_RUNS_FILE = "BRT_Optimizer_All_Runs.csv"
PROGRESS_FILE = "BRT_optimizer_progress.json"


def _append_csv_schema_safe(path: str, df: pd.DataFrame, expected_cols: list[str]) -> str:
    """
    Append df to path, but ensure the existing header matches expected_cols.
    If the file exists with a different header (schema drift), write to a new file
    `stem_<timestamp>.csv` with the correct header to avoid silent misalignment.
    Returns the actual path written.
    """
    p = Path(path)
    if not p.exists():
        df.to_csv(p, mode="w", index=False, header=True)
        return str(p)

    try:
        with open(p, "r", newline="") as f:
            reader = csv.reader(f)
            existing_header = next(reader, [])
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

# Config columns for summary (inputs) — must match rocket_brt._AUDIT_CFG_COLS
CFG_COLS = [
    "pivot_k", "pivot_d", "pivot_disp", "pivot_m", "band_pct", "lookback_long", "touch_threshold",
    "strong_pivots_enabled",
    "strong_pre_pivot_bars", "strong_pre_pivot_pct",
    "strong_post_pivot_bars", "strong_post_pivot_pct", "strong_pivot_mode",
    "zone_include_pre_strong_pivot_lows",
    "zones_from_pivot_lows_enabled",
    "brt_zones",
    "yh_zones",
    "yh_lookback",
    "yh_move_away_pct",
    "yh_memory_mode",
    "yh_serial_memory",
    "close_above_window", "row_local_eval_ttl_bars_after_first_eval", "level_acceptance_window", "level_acceptance_required",
    "support_test_enabled", "breakout_bars",
    "tight_range_enabled", "tight_range_threshold_pct", "tight_range_lookback",
    "tradeable_key_level_enabled", "lookback_short",
    "min_touch_count", "max_touch_count_minor",
    "min_pivot_run_l_before_entry", "min_pivot_run_h_before_entry", "min_rel_vol_at_entry",
    "min_market_cap",
    "max_market_cap",
    "min_hist_ann_ror_avg",
    "min_avg_volume_10d_at_entry",
    "min_atr_pct_at_trigger",
    "max_atr_pct_at_trigger",
    "min_dist_to_52w_high_pct_at_trigger",
    "max_dist_to_52w_high_pct_at_trigger",
    "min_spy_compare_1y_at_trigger",
    "max_spy_compare_1y_at_trigger",
    "min_spy_compare_2y_at_trigger",
    "min_spy_compare_3y_at_trigger",
    "pivot_switch_h_to_l_filter",
    "entry_filter_major_pivot", "entry_filter_is_20bar_high_at_trigger",
    "growth_filter_enabled", "growth_bars", "entry_close_min_range_position",
    "sheet_maturity_lag_bars",
    "entry_retest_bullish_growth_only",
    "displacement_filter_enabled", "displacement_rolling_bars", "displacement_threshold_pct",
    "consolidation_blocker_enabled", "cb_max_box_width_pct",
    "brt_cash", "stop_pct", "stop_pct_is_multiplier", "target_pct",
    "atr_target", "atr_stop", "trailing_stop_increment", "atr_progress", "atr_days",
    # Realtime predictive filter config + weights (inputs)
    "realtime_filter_enabled", "realtime_filter_threshold", "realtime_filter_use_zscore",
    "weight_touch_count_minor", "weight_zone_cluster_density", "weight_nearby_zones_above",
    "weight_touch_count_major", "weight_pct_entry_to_bottom_zone_above",
    "weight_z_score_at_trigger", "weight_pivot_run_l_before_entry",
    "weight_nearby_zones_below", "weight_pct_drop_to_top_zone_below",
    "weight_rel_vol_at_entry", "weight_displacement_pct_at_entry",
    "weight_lower_wick_atr_at_trigger", "weight_growth_pct_over_period", "weight_beta_at_entry",
    "meteoric_rise_pct", "meteoric_rise_lookback", "meteoric_fall_pct", "meteoric_fall_lookback",
    "post_entry_gain_pct", "post_entry_gain_calendar_days",
    "days_per_year", "exit_at_close_when_stopped", "compute_equity_metrics",
]

# BRT_Optimization_Audit column order — same as BRT_Report / BRT_Audit (single source: brt_audit_columns.py)
try:
    from brt_audit_columns import get_brt_audit_column_order

    AUDIT_COLS_ORDER = get_brt_audit_column_order()
except ImportError:
    AUDIT_COLS_ORDER = (
        ["Timestamp_Drive"]
        + CFG_COLS
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

# Workers for parallel param-value testing (each runs full backtest)
MAX_WORKERS = 5  # Tune based on CPU cores; each run loads all tickers

# Min trades to accept a run
MIN_TRADES = 1000

# --- Hard Gate Thresholds (Optimization 2.0) ---
GATE_PROFIT_RETENTION = 0.80   # Total PnL ≥ 90% of baseline
GATE_EXPECTANCY_RETENTION = 0   # Expectancy ≥ 90% of baseline
GATE_TRADE_COUNT_CAP = 1.25    # Total Trades ≤ 125% of baseline
GATE_MIN_AVG_DAYS = 0         # Avg Days Held ≥ 15

# --- Optimization Scoring Model 2.0 Weights (sum = 100%) ---
# Tier 1 — Primary Objective (50%)
W_PROFIT_PER_CAP_DAY = 15
W_TOTAL_PROFIT = 15
W_MAX_DRAWDOWN = 15
# Tier 2 — Structural Edge Quality (30%)
W_PROFIT_FACTOR = 15
W_EXPECTANCY = 10
W_WIN_LOSS_RATIO = 10
# Tier 3 — Stability & Robustness (20%)
W_TRADE_COUNT_STABILITY = 10
W_LOSING_STREAK = 10
W_P90_DAYS = 5


def _cfg_dict_to_brt_config(cfg_dict: dict) -> BRTConfig:
    """Build BRTConfig from dict, using only valid field names."""
    # Back-compat: old strong_pivot_bars/pct → post-pivot fields
    d = dict(cfg_dict)
    if "atr_increment" in d and "trailing_stop_increment" not in d:
        d["trailing_stop_increment"] = d["atr_increment"]
    d.pop("atr_increment", None)
    if "strong_pivot_bars" in d and "strong_post_pivot_bars" not in d:
        d["strong_post_pivot_bars"] = d["strong_pivot_bars"]
    if "strong_pivot_pct" in d and "strong_post_pivot_pct" not in d:
        d["strong_post_pivot_pct"] = d["strong_pivot_pct"]
    valid = {
        "pivot_k", "pivot_d", "pivot_disp", "pivot_m", "band_pct", "lookback_long", "touch_threshold",
        "strong_pivots_enabled",
        "strong_pre_pivot_bars", "strong_pre_pivot_pct",
        "strong_post_pivot_bars", "strong_post_pivot_pct", "strong_pivot_mode",
        "zone_include_pre_strong_pivot_lows",
        "zones_from_pivot_lows_enabled",
        "brt_zones",
        "yh_zones",
        "yh_lookback",
        "yh_move_away_pct",
        "close_above_window", "row_local_eval_ttl_bars_after_first_eval", "level_acceptance_window", "level_acceptance_required",
        "tight_range_enabled", "tight_range_threshold_pct", "tight_range_lookback",
        "tradeable_key_level_enabled", "lookback_short",
        "min_touch_count", "max_touch_count_minor",
        "min_pivot_run_l_before_entry", "min_pivot_run_h_before_entry", "min_rel_vol_at_entry",
        "min_market_cap",
        "max_market_cap",
        "min_hist_ann_ror_avg",
        "min_avg_volume_10d_at_entry",
        "min_atr_pct_at_trigger",
        "max_atr_pct_at_trigger",
        "min_dist_to_52w_high_pct_at_trigger",
        "max_dist_to_52w_high_pct_at_trigger",
        "min_spy_compare_1y_at_trigger",
        "max_spy_compare_1y_at_trigger",
        "min_spy_compare_2y_at_trigger",
        "min_spy_compare_3y_at_trigger",
        "pivot_switch_h_to_l_filter",
        "growth_filter_enabled", "growth_bars", "entry_close_min_range_position",
        "sheet_maturity_lag_bars",
        "entry_retest_bullish_growth_only",
        "displacement_filter_enabled", "displacement_rolling_bars", "displacement_threshold_pct",
        "brt_cash", "stop_pct", "stop_pct_is_multiplier", "target_pct",
        "atr_target", "atr_stop", "trailing_stop_increment", "atr_progress", "atr_days",
        "days_per_year", "exit_at_close_when_stopped", "compute_equity_metrics",
    }
    filtered = {k: v for k, v in d.items() if k in valid}
    return BRTConfig(**filtered)


def _metrics_to_row(metrics: dict, param_name: str, param_value) -> dict:
    """Convert BRT metrics dict to a row with numeric values for scoring."""
    def num(x):
        if x is None or x == "N/A":
            return 0.0
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).replace("%", "").strip()
        try:
            return float(s)
        except ValueError:
            return 0.0

    total_pnl = num(metrics.get("Total_PNL", 0))
    ann_ror = num(metrics.get("Annualized_ROR", 0))
    ces = num(metrics.get("CES_AVG", 0))
    pf = num(metrics.get("Profit_Factor", 0))
    wins = int(metrics.get("Wins", 0))
    losses = int(metrics.get("Losses", 0))
    bes = int(metrics.get("BEs", 0))
    total_trades = wins + losses + bes
    pct_wins = (wins / total_trades * 100) if total_trades else 0.0
    pct_losses = (losses / total_trades * 100) if total_trades else 0.0
    win_loss_ratio = (wins / losses) if losses else (float(wins) if wins else 0.0)
    win_loss_ratio_dollar = num(metrics.get("Win_Loss_Ratio_Dollar", 0))
    p90 = num(metrics.get("P90_Days", 0))
    median_days = num(metrics.get("Median_Days_Held", 0))
    max_dd_raw = metrics.get("Max_Drawdown", "N/A")
    max_dd = max_dd_raw if (max_dd_raw is None or max_dd_raw == "N/A" or str(max_dd_raw).strip() == "N/A") else num(max_dd_raw)
    dd_per_trade_raw = metrics.get("DD_Per_Trade", "N/A")
    dd_per_trade = dd_per_trade_raw if (dd_per_trade_raw is None or dd_per_trade_raw == "N/A" or str(dd_per_trade_raw).strip() == "N/A") else num(dd_per_trade_raw)
    expectancy = num(metrics.get("Expectancy", 0))
    avg_pnl_pct = num(metrics.get("Avg_PNL_Pct", 0))
    avg_win_pct = num(metrics.get("Avg_Win_Pct", 0))
    avg_loss_pct = num(metrics.get("Avg_Loss_Pct", 0))
    profit_per_cap_day = num(metrics.get("Profit_Per_Capital_Day", 0))
    avg_days = num(metrics.get("Avg_Days_Held", 0))
    capital_days = int(metrics.get("Capital_Days", 0))
    max_positions = int(metrics.get("Max_Positions", 1))
    losing_streak = int(metrics.get("Losing_Streak", 0))
    ces_median = num(metrics.get("CES_Median", 0))
    pct_pnl_top10 = num(metrics.get("Pct_PNL_Top10", 0))
    pct_pnl_bottom10 = num(metrics.get("Pct_PNL_Bottom10", 0))

    return {
        "Param_Name": param_name,
        "Param_Value": param_value,
        # 1. Trade Outcome Block
        "Total_PNL": total_pnl,
        "Wins": wins,
        "Losses": losses,
        "BE": bes,
        "Pct_Wins": pct_wins,
        "Pct_Losses": pct_losses,
        "Win_Loss_Ratio": win_loss_ratio,
        "Win_Loss_Ratio_Dollar": win_loss_ratio_dollar,
        "Total_Trades": total_trades,
        "Profit_Factor": pf,
        "Avg_Win_Pct": avg_win_pct,
        "Avg_Loss_Pct": avg_loss_pct,
        "Avg_PNL_Pct": avg_pnl_pct,
        "Expectancy": expectancy,
        "Expectancy_Pct": avg_pnl_pct,
        # 2. Duration & Capital Efficiency
        "Avg_Days_Held": avg_days,
        "Median_Days_Held": median_days,
        "P90_Days": p90,
        "Capital_Days": capital_days,
        "Profit_Per_Capital_Day": profit_per_cap_day,
        "Ann_ROR": ann_ror,
        # 3. Risk Block
        "Max_DD": max_dd,
        "Losing_Streak": losing_streak,
        "DD_Per_Trade": dd_per_trade,
        # 4. Distribution & Stability
        "CES_AVG": ces,
        "CES_Median": ces_median,
        "Pct_PNL_Top10": pct_pnl_top10,
        "Pct_PNL_Bottom10": pct_pnl_bottom10,
        "Max_Positions": max_positions,
    }


def _safe_num(x) -> float:
    """Convert to float; treat None, 'N/A' as 0."""
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
    """Find baseline row: Param_Value matches best_params[param_name]. Fallback: first row."""
    target = best_params.get(param_name)
    for row in batch_results:
        if row.get("Param_Value") == target:
            return row
    return batch_results[0] if batch_results else None


def _passes_hard_gates(row: dict, baseline_row: dict) -> bool:
    """Hard-Gate Optimization Framework: all gates must pass or Score = 0."""
    b_pnl = _safe_num(baseline_row.get("Total_PNL", 0))
    b_exp = _safe_num(baseline_row.get("Expectancy", 0))
    b_trades = int(baseline_row.get("Total_Trades", 0))
    v_pnl = _safe_num(row.get("Total_PNL", 0))
    v_exp = _safe_num(row.get("Expectancy", 0))
    v_trades = int(row.get("Total_Trades", 0))
    v_avg_days = _safe_num(row.get("Avg_Days_Held", 0))

    if b_pnl > 0 and v_pnl < GATE_PROFIT_RETENTION * b_pnl:
        return False
    if b_exp > 0 and v_exp < GATE_EXPECTANCY_RETENTION * b_exp:
        return False
    if b_trades > 0 and v_trades > GATE_TRADE_COUNT_CAP * b_trades:
        return False
    if v_avg_days < GATE_MIN_AVG_DAYS:
        return False
    return True


def _win_loss_ratio(row: dict) -> float:
    """Wins / Losses; higher is better. Handles edge cases."""
    wins = int(row.get("Wins", 0))
    losses = int(row.get("Losses", 0))
    if losses <= 0:
        return 10.0 if wins > 0 else 1.0
    return wins / losses


def calculate_score(row: dict, baseline_row: dict | None) -> float:
    """
    Optimization Scoring Model 2.0: weighted score relative to baseline.
    Baseline score = 100. Higher is better. Fails hard gates → 0.
    """
    if baseline_row is None:
        return 0.0
    if not _passes_hard_gates(row, baseline_row):
        return 0.0

    total_trades = int(row.get("Total_Trades", 0))
    if total_trades < MIN_TRADES:
        return 0.0

    def ratio_higher(v: float, b: float) -> float:
        if b == 0:
            return 1.0 if v == 0 else (2.0 if v > 0 else 0.0)
        return v / b

    def ratio_lower(v: float, b: float) -> float:
        """Lower is better: Baseline ÷ Variant."""
        if v == 0:
            return 2.0 if b > 0 else 1.0  # variant wins (e.g. 0 streak)
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
    v_trades = int(row.get("Total_Trades", 0))
    b_trades = int(baseline_row.get("Total_Trades", 0))
    v_streak = int(row.get("Losing_Streak", 0))
    b_streak = int(baseline_row.get("Losing_Streak", 0))
    v_p90 = _safe_num(row.get("P90_Days", 0))
    b_p90 = _safe_num(baseline_row.get("P90_Days", 0))

    # Max DD: use 1.0 if both N/A/0 (no equity data)
    if v_dd <= 0 and b_dd <= 0:
        r_dd = 1.0
    else:
        r_dd = ratio_lower(v_dd, b_dd) if (v_dd > 0 and b_dd > 0) else 1.0

    # Trade Count Stability: penalize if variant drops >25% from baseline
    if b_trades > 0:
        t_ratio = v_trades / b_trades
        if t_ratio < 0.75:
            r_trades = 0.0
        elif t_ratio <= 1.0:
            r_trades = (t_ratio - 0.75) / 0.25  # linear 0→1 from 75% to 100%
        else:
            r_trades = 1.0  # cap at 1.0 (no extra reward for more trades)
    else:
        r_trades = 1.0

    s = 0.0
    s += ratio_higher(v_ppcd, b_ppcd) * (W_PROFIT_PER_CAP_DAY / 100)
    s += ratio_higher(v_pnl, b_pnl) * (W_TOTAL_PROFIT / 100)
    s += r_dd * (W_MAX_DRAWDOWN / 100)
    s += ratio_higher(v_pf, b_pf) * (W_PROFIT_FACTOR / 100)
    s += ratio_higher(v_exp, b_exp) * (W_EXPECTANCY / 100)
    s += ratio_higher(v_wlr, b_wlr) * (W_WIN_LOSS_RATIO / 100)
    s += r_trades * (W_TRADE_COUNT_STABILITY / 100)
    s += ratio_lower(float(v_streak), float(b_streak)) * (W_LOSING_STREAK / 100)
    s += ratio_lower(v_p90, b_p90) * (W_P90_DAYS / 100)

    return s * 100  # Baseline = 100


def run_one_param(task: tuple) -> tuple:
    """Worker: run backtest with given config. Picklable for ProcessPoolExecutor."""
    cfg_dict, param_name, param_value, task_id, data_dir = task
    cfg = _cfg_dict_to_brt_config(cfg_dict)
    try:
        _, metrics = run_brt_backtest_batch(data_dir, cfg, n_workers=0)
        row = _metrics_to_row(metrics, param_name, param_value)
        return (param_value, row)
    except Exception as e:
        print(f"  [Worker] {param_name}={param_value} failed: {e}", file=sys.stderr)
        return (param_value, None)


def sanitize_value(v):
    """Convert NumPy types to native Python."""
    return v.item() if hasattr(v, "item") else v


def load_progress(initial_params: dict) -> tuple[list, dict]:
    """Load progress from JSON if present."""
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


# --- BRT PARAMETER PLAN ---
# Map BRTConfig field names to tuples of values to try (one param optimized at a time)
OPTIMIZATION_PLAN = {
    #"band_pct": (0.015, 0.016, 0.017, 0.018, 0.019, 0.02, 0.021, 0.022, 0.023, 0.024, 0.025, 0.026, 0.027, 0.028, 0.029, 0.030, 0.031, 0.032, 0.033, 0.034, 0.035),
    #"stop_pct": (0.91, 0.92, 0.93, 0.934, 0.94, 0.945, 0.95, 0.955, 0.96, 0.965, 0.97, 0.975),
    #"min_touch_count": (4, 5, 6, 7),
    #"max_touch_count_minor": (0, 1, 2, 3),
    #"target_pct": (1.17, 1.18, 1.19, 1.2, 1.21, 1.22, 1.23, 1.24, 1.25, 1.26, 1.27, 1.28, 1.29, 1.30, 1.31, 1.32, 1.33, 1.34, 1.35),
    #"close_above_window": (0, 1, 2),
    #"level_acceptance_required": (5, 6, 7, 8),
    #"level_acceptance_window": (8, 10, 12),
    #"pivot_k": (2, 3, 4, 5, 6, 7, 8, 9, 10),
    #"atr_target": (2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 3.0),
    #"pivot_m": (5, 6, 7, 8),
    #"lookback_long": (378, 504, 630),
    #"touch_threshold": (5, 6, 7),
    #"tight_range_threshold_pct": (0.31, 0.32, 0.33, 0.34, 0.35, 0.36, 0.37, 0.38, 0.39),
    #"tight_range_lookback": (140, 141, 142, 143, 144, 145, 146, 147, 148, 149, 150, 151, 152, 153, 154, 155, 156, 157, 158, 159, 160, 161, 162, 163, 164, 165, 166, 167, 168),
    #"tight_range_enabled": (True, False),
    #"exit_at_close_when_stopped": (True, False),
}
# Defaults (used as base; optimizer overrides one at a time)
current_best_params = {
    #"pivot_k": 4,
    #"pivot_d": 7,
    #"pivot_disp": 0.06,
    #"pivot_m": 4,
    #"band_pct": 0.31,
    #"lookback_long": 504,
    #"touch_threshold": 6,
    #"strong_pivots_enabled": True,
    #"strong_pre_pivot_bars": 7,
    #"strong_pre_pivot_pct": 0.12,
    #"strong_post_pivot_bars": 7,
    #"strong_post_pivot_pct": 0.09,
    #"strong_pivot_mode": "pre",
    #"close_above_window": 1,
    #"level_acceptance_window": 10,
    #"level_acceptance_required": 7,
    #"tight_range_enabled": True,
    #"tight_range_threshold_pct": 0.35,
    #"tight_range_lookback": 105,
    #"tradeable_key_level_enabled": True,
    #"lookback_short": 105,
    #"min_touch_count": 0,
    #"max_touch_count_minor": 100,
    #"min_pivot_run_l_before_entry": 0,
    #"min_pivot_run_h_before_entry": 0,
    #"min_rel_vol_at_entry": -2.0,
    #"min_market_cap": 0.0,
    #"min_hist_ann_ror_avg": -100.0,
    #"pivot_switch_h_to_l_filter": -1,
    #"growth_filter_enabled": True,
    #"growth_bars": 756,
    #"displacement_filter_enabled": False,
    #"displacement_rolling_bars": 100,
    #"displacement_threshold_pct": 0.10,
    #"brt_cash": 47500,
    #"stop_pct": 0,
    #"stop_pct_is_multiplier": True,
    #"target_pct": 0,
    #"atr_target": 10,
    #"atr_stop": 3,
    #"trailing_stop_increment": 5,
    #"days_per_year": 365.0,
    #"exit_at_close_when_stopped": False,
    #"compute_equity_metrics": True,  # Always compute Max_DD etc. via equity reconstruction
}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="BRT Parameter Optimizer")
    ap.add_argument("--workers", "-w", type=int, default=MAX_WORKERS,
                    help=f"Parallel workers (default {MAX_WORKERS})")
    ap.add_argument("--data-dir", default=DATA_DIR, help="Data directory with ticker CSVs")
    args = ap.parse_args()
    workers = max(1, args.workers)
    data_dir = str(Path(args.data_dir).resolve())

    session_start = time.time()
    ts_start = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("\n[OK] BRT OPTIMIZATION SESSION START")
    print(f"[OK] Started at: {ts_start}")
    print("=" * 60)
    os.chdir(SCRIPT_DIR)

    completed_params, best_params = load_progress(current_best_params)
    best_params = {k: sanitize_value(v) for k, v in best_params.items()}
    # Ensure any new config keys (e.g. displacement_*) from defaults are present after loading old progress
    for k, v in current_best_params.items():
        if k not in best_params:
            best_params[k] = v

    for p_name, values in OPTIMIZATION_PLAN.items():
        if p_name not in best_params:
            best_params[p_name] = values[0]

    print(f"[OK] Data dir: {data_dir}")
    print(f"[OK] Workers: {workers}")
    print(f"[OK] {len(completed_params)} params already optimized. Remaining: {[p for p in OPTIMIZATION_PLAN if p not in completed_params]}")
    print("(Ctrl+C to stop; progress is saved so you can resume later)")

    try:
        for param_name, values in OPTIMIZATION_PLAN.items():
            if param_name in completed_params:
                continue

            print(f"\n--- Optimizing {param_name} ({len(values)} values, {workers} workers) ---")
            if param_name in ("atr_target", "atr_stop"):
                print("  (Forcing stop_pct=0, target_pct=0 for ATR stop/target mode)")
            # When optimizing atr_target / atr_stop, force stop_pct=0 and target_pct=0 so those ATR fields apply.
            # If atr_target is swept while atr_stop stays 0, rocket_brt used to set stop_price=0 (no stop-loss);
            # engine now falls back to default low×0.934 unless you set atr_stop>0 in best_params (see atr_stop=3 in comments).
            # trailing_stop_increment is optimized separately and may be used with percent or ATR exits.
            def _cfg_for_task(v):
                cfg = {**best_params, param_name: v}
                if param_name in ("atr_target", "atr_stop"):
                    cfg["stop_pct"] = 0
                    cfg["target_pct"] = 0
                return cfg
            tasks = [
                (_cfg_for_task(v), param_name, v, i, data_dir)
                for i, v in enumerate(values)
            ]
            batch_results = []

            with ProcessPoolExecutor(max_workers=workers) as ex:
                for future in as_completed(ex.submit(run_one_param, t) for t in tasks):
                    param_value, row = future.result()
                    if row:
                        # Add full config (inputs) to row for summary
                        cfg_full = {**best_params, param_name: sanitize_value(param_value)}
                        if param_name in ("atr_target", "atr_stop"):
                            cfg_full["stop_pct"] = 0
                            cfg_full["target_pct"] = 0
                        for k in CFG_COLS:
                            row[k] = cfg_full.get(k, "")
                        batch_results.append(row)

            if not batch_results:
                print(f"  [WARN] No valid results for {param_name}")
                completed_params.append(param_name)
                save_progress(completed_params, best_params)
                continue

            df = pd.DataFrame(batch_results)
            baseline_row = _get_baseline_row(batch_results, param_name, best_params)

            df["Score"] = df.apply(
                lambda r: calculate_score(r.to_dict(), baseline_row),
                axis=1,
            )
            df = df.sort_values("Score", ascending=False)
            winner = df.iloc[0]
            best_params[param_name] = sanitize_value(winner["Param_Value"])

            completed_params.append(param_name)
            save_progress(completed_params, best_params)

            # Append to logs (unique link per row: timestamp_paramname_paramvalue)
            ts = datetime.now().strftime("%y%m%d%H%M%S")
            def _drive_link(r):
                pv = str(sanitize_value(r.get("Param_Value", ""))).replace(" ", "_")
                pn = str(r.get("Param_Name", "")).replace(" ", "_")
                label = f"{ts}_{pn}_{pv}"
                return f'=hyperlink("https://drive.google.com/drive/search?q={label}","{label}")'
            df["Timestamp_Drive"] = df.apply(_drive_link, axis=1)
            ordered = [c for c in AUDIT_COLS_ORDER if c in df.columns]
            extra = [c for c in df.columns if c not in AUDIT_COLS_ORDER]
            audit_cols = ordered + extra
            df_audit = df[audit_cols]

            winner_df = df.iloc[[0]].copy()
            winner_df.to_csv(MASTER_LOG, mode="a", index=False, header=not Path(MASTER_LOG).exists())
            _append_csv_schema_safe(GLOBAL_AUDIT_LOG, df_audit, AUDIT_COLS_ORDER)

            # Primary summary: inputs + outputs per run (like BRT_Report)
            summary_cols = CFG_COLS + ["Param_Name", "Param_Value"] + [
                "Total_PNL", "Wins", "Losses", "BE", "Total_Trades", "Profit_Factor", "Ann_ROR",
                "CES_AVG", "Expectancy", "Avg_PNL_Pct", "Avg_Days_Held", "P90_Days", "Max_DD",
                "Losing_Streak", "Capital_Days", "Max_Positions", "Profit_Per_Capital_Day", "Score",
            ]
            summary_df = df[[c for c in summary_cols if c in df.columns]].copy()
            summary_df.to_csv(OPTIMIZER_SUMMARY_FILE, mode="a", index=False, header=not Path(OPTIMIZER_SUMMARY_FILE).exists())

            print(f"  Winner: {param_name}={best_params[param_name]} (Score={winner['Score']:.4f}, "
                  f"PNL={winner['Total_PNL']:.0f}, ROR={winner['Ann_ROR']:.1f}, PF={winner['Profit_Factor']:.2f})")

    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Ctrl+C received. Saving progress...")
        save_progress(completed_params, best_params)
        final = {k: sanitize_value(v) for k, v in best_params.items()}
        with open(BEST_SETTINGS_FILE, "w") as f:
            json.dump(final, f, indent=2)
        print(f"[OK] Progress saved. Run again to resume (remaining: {[p for p in OPTIMIZATION_PLAN if p not in completed_params]})")
        return 130

    # Final settings
    final = {k: sanitize_value(v) for k, v in best_params.items()}
    with open(BEST_SETTINGS_FILE, "w") as f:
        json.dump(final, f, indent=2)

    elapsed = time.time() - session_start
    print("\n" + "=" * 60)
    print(f"[OK] BRT OPTIMIZATION COMPLETE ({elapsed/60:.1f} min)")
    print(f"[OK] Settings saved to {BEST_SETTINGS_FILE}")
    print(f"[OK] Summary (inputs + outputs): {OPTIMIZER_SUMMARY_FILE}")
    try:
        subprocess.run(
            ["powershell", "-Command", "[Console]::Beep(750, 2000)"],
            check=False,
            capture_output=True,
            timeout=3,
        )
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
