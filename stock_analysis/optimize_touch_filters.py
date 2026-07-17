#!/usr/bin/env python3
"""
Find optimal combination of TOUCH_COUNT_MAJOR, TOUCH_COUNT_MINOR, TOUCH_COUNT, MAJ_RATIO
filters on BRT_Closed data, using Optimization 2.0 scoring and Hard-Gate framework.

Usage: python optimize_touch_filters.py [BRT_Closed_<timestamp>.csv]
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).parent.resolve()
DEFAULT_PATH = SCRIPT_DIR.parent / "Drive" / "BRT_Closed_260302153815.csv"

# Hard Gate Thresholds (Optimization 2.0)
GATE_PROFIT_RETENTION = 0.90
GATE_EXPECTANCY_RETENTION = 0.90
GATE_TRADE_COUNT_CAP = 1.25
GATE_MIN_AVG_DAYS = 15
MIN_TRADES = 10

# Optimization Scoring Model 2.0 Weights
W_PROFIT_PER_CAP_DAY = 25
W_TOTAL_PROFIT = 15
W_MAX_DRAWDOWN = 10
W_PROFIT_FACTOR = 15
W_EXPECTANCY = 10
W_WIN_LOSS_RATIO = 5
W_TRADE_COUNT_STABILITY = 8
W_LOSING_STREAK = 7
W_P90_DAYS = 5

INITIAL_CAPITAL = 47500 * 12  # brt_cash * 12


def load_brt(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip() for c in df.columns]
    df["PNL_PCT_NUM"] = df["PNL_PCT"].astype(str).str.replace("%", "").astype(float)
    df["PNL_DOLLARS_NUM"] = df["PNL_DOLLARS"].astype(str).str.replace(",", "").astype(float)
    df["MAJ_RATIO"] = np.where(
        df["TOUCH_COUNT"] > 0,
        df["TOUCH_COUNT_MAJOR"] / df["TOUCH_COUNT"],
        0.0,
    )
    return df


def compute_metrics(g: pd.DataFrame) -> dict:
    """Compute optimization metrics from filtered trade subset."""
    n = len(g)
    if n < MIN_TRADES:
        return None
    total_pnl = g["PNL_DOLLARS_NUM"].sum()
    wins = (g["PNL_PCT_NUM"] > 0).sum()
    losses = (g["PNL_PCT_NUM"] < 0).sum()
    bes = (g["PNL_PCT_NUM"] == 0).sum()
    sum_wins = g.loc[g["PNL_PCT_NUM"] > 0, "PNL_DOLLARS_NUM"].sum()
    sum_losses = abs(g.loc[g["PNL_PCT_NUM"] < 0, "PNL_DOLLARS_NUM"].sum())
    pf = sum_wins / sum_losses if sum_losses > 0 else (sum_wins if sum_wins > 0 else 0)
    expectancy = total_pnl / n if n else 0
    capital_days = g["DAYS_HELD"].sum()
    ppcd = total_pnl / capital_days if capital_days > 0 else 0
    avg_days = g["DAYS_HELD"].mean() if n else 0
    days_list = sorted(g["DAYS_HELD"].dropna())
    p90 = days_list[int(len(days_list) * 0.9) - 1] if len(days_list) >= 10 else (max(days_list) if days_list else 0)
    # Win/Loss ratio (count)
    wlr = wins / losses if losses else (float(wins) if wins else 0)
    # Losing streak
    streak = 0
    cur = 0
    for _, r in g.sort_values("DATE_CLOSED").iterrows():
        if r["PNL_PCT_NUM"] < 0:
            cur += 1
            streak = max(streak, cur)
        else:
            cur = 0
    # Max DD from realized equity curve (simplified)
    g_sorted = g.sort_values("DATE_CLOSED").reset_index(drop=True)
    equity = INITIAL_CAPITAL + g_sorted["PNL_DOLLARS_NUM"].cumsum()
    hwm = equity.cummax()
    dd = (hwm - equity) / np.where(hwm > 0, hwm, 1)
    max_dd = float(dd.max()) if len(dd) else 0
    return {
        "Total_PNL": total_pnl,
        "Wins": wins,
        "Losses": losses,
        "BE": bes,
        "Total_Trades": n,
        "Profit_Factor": pf,
        "Expectancy": expectancy,
        "Profit_Per_Capital_Day": ppcd,
        "Avg_Days_Held": avg_days,
        "Capital_Days": capital_days,
        "P90_Days": p90,
        "Win_Loss_Ratio": wlr,
        "Losing_Streak": streak,
        "Max_DD": max_dd,
    }


def passes_hard_gates(metrics: dict, baseline: dict) -> bool:
    if metrics is None:
        return False
    b_pnl = baseline.get("Total_PNL", 0)
    b_exp = baseline.get("Expectancy", 0)
    b_trades = baseline.get("Total_Trades", 1)
    v_pnl = metrics.get("Total_PNL", 0)
    v_exp = metrics.get("Expectancy", 0)
    v_trades = metrics.get("Total_Trades", 0)
    v_avg_days = metrics.get("Avg_Days_Held", 0)
    if b_pnl > 0 and v_pnl < GATE_PROFIT_RETENTION * b_pnl:
        return False
    if b_exp > 0 and v_exp < GATE_EXPECTANCY_RETENTION * b_exp:
        return False
    if v_trades > GATE_TRADE_COUNT_CAP * b_trades:
        return False
    if v_avg_days < GATE_MIN_AVG_DAYS:
        return False
    return True


def _safe(x):
    return float(x) if x is not None and not (isinstance(x, str) and x == "N/A") else 0.0


def calculate_score(row: dict, baseline: dict) -> float:
    def ratio_higher(v, b):
        if b == 0:
            return 1.0 if v == 0 else (2.0 if v > 0 else 0.0)
        return v / b

    def ratio_lower(v, b):
        if v == 0:
            return 2.0 if b > 0 else 1.0
        if b == 0:
            return 1.0
        return b / v

    v_ppcd = _safe(row.get("Profit_Per_Capital_Day"))
    b_ppcd = _safe(baseline.get("Profit_Per_Capital_Day"))
    v_pnl = _safe(row.get("Total_PNL"))
    b_pnl = _safe(baseline.get("Total_PNL"))
    v_dd = _safe(row.get("Max_DD"))
    b_dd = _safe(baseline.get("Max_DD"))
    v_pf = _safe(row.get("Profit_Factor"))
    b_pf = _safe(baseline.get("Profit_Factor"))
    v_exp = _safe(row.get("Expectancy"))
    b_exp = _safe(baseline.get("Expectancy"))
    v_wlr = _safe(row.get("Win_Loss_Ratio"))
    b_wlr = _safe(baseline.get("Win_Loss_Ratio"))
    v_trades = int(row.get("Total_Trades", 0))
    b_trades = int(baseline.get("Total_Trades", 1))
    v_streak = int(row.get("Losing_Streak", 0))
    b_streak = int(baseline.get("Losing_Streak", 0))
    v_p90 = _safe(row.get("P90_Days"))
    b_p90 = _safe(baseline.get("P90_Days"))

    r_dd = ratio_lower(v_dd, b_dd) if (v_dd > 0 and b_dd > 0) else 1.0
    if b_trades > 0:
        t_ratio = v_trades / b_trades
        r_trades = 0.0 if t_ratio < 0.75 else ((t_ratio - 0.75) / 0.25 if t_ratio <= 1.0 else 1.0)
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
    return s * 100


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PATH
    if not path.is_absolute():
        path = SCRIPT_DIR / path
    if not path.exists():
        print(f"File not found: {path}")
        return 1

    print(f"Loading: {path}")
    df = load_brt(path)
    if "TOUCH_COUNT_MAJOR" not in df.columns or "TOUCH_COUNT_MINOR" not in df.columns:
        print("TOUCH_COUNT_MAJOR or TOUCH_COUNT_MINOR not found. Run backtest with latest rocket_brt.")
        return 1

    baseline = compute_metrics(df)
    if baseline is None:
        print("Baseline has too few trades.")
        return 1

    print("\n" + "=" * 70)
    print("BASELINE (all trades)")
    print("=" * 70)
    print(f"  Total_Trades: {baseline['Total_Trades']}")
    print(f"  Total_PNL: ${baseline['Total_PNL']:,.0f}")
    print(f"  Profit_Per_Capital_Day: ${baseline['Profit_Per_Capital_Day']:.2f}")
    print(f"  Expectancy: ${baseline['Expectancy']:.2f}")
    print(f"  Profit_Factor: {baseline['Profit_Factor']:.2f}")
    print(f"  Max_DD: {baseline['Max_DD']:.2%}")
    print(f"  Avg_Days_Held: {baseline['Avg_Days_Held']:.1f}")
    print()

    # Grid search over filter combinations
    filters = []
    # TC_MAJOR: min 0, 1, 2
    # TC_MINOR: max None, 1, 2, 3
    # TC: min None, 4, 5
    # MAJ_RATIO: min None, 0.25, 0.5, 0.75
    for tc_maj_min in [0, 1, 2]:
        for tc_min_max in [None, 1, 2, 3]:
            for tc_min in [None, 4, 5]:
                for maj_ratio_min in [None, 0.25, 0.5, 0.75]:
                    m = df["TOUCH_COUNT_MAJOR"] >= tc_maj_min
                    if tc_min_max is not None:
                        m = m & (df["TOUCH_COUNT_MINOR"] <= tc_min_max)
                    if tc_min is not None:
                        m = m & (df["TOUCH_COUNT"] >= tc_min)
                    if maj_ratio_min is not None:
                        m = m & (df["MAJ_RATIO"] >= maj_ratio_min)
                    g = df[m]
                    if len(g) < MIN_TRADES:
                        continue
                    metrics = compute_metrics(g)
                    if metrics is None:
                        continue
                    passes = passes_hard_gates(metrics, baseline)
                    score = calculate_score(metrics, baseline)  # always score (gates optional)
                    label = f"TC_MAJ>={tc_maj_min}"
                    if tc_min_max is not None:
                        label += f" TC_MIN<={tc_min_max}"
                    if tc_min is not None:
                        label += f" TC>={tc_min}"
                    if maj_ratio_min is not None:
                        label += f" MAJ_RATIO>={maj_ratio_min}"
                    filters.append({
                        "label": label,
                        "n": len(g),
                        "score": score,
                        "passes": passes,
                        "metrics": metrics,
                    })

    # Sort by score descending
    filters.sort(key=lambda x: x["score"], reverse=True)

    print("=" * 70)
    print("TOP 15 FILTER COMBINATIONS (by Optimization Score 2.0)")
    print("=" * 70)
    print(f"{'Rank':<5} {'Score':<8} {'Pass':<6} {'n':<7} {'PPCD':<10} {'PNL':<12} {'PF':<6} {'Exp':<8} {'Filter'}")
    print("-" * 70)
    for i, f in enumerate(filters[:15], 1):
        m = f["metrics"]
        ppcd = m["Profit_Per_Capital_Day"]
        pnl = m["Total_PNL"]
        pf = m["Profit_Factor"]
        exp = m["Expectancy"]
        print(f"{i:<5} {f['score']:<8.1f} {'Yes' if f['passes'] else 'No':<6} {f['n']:<7} ${ppcd:<9.2f} ${pnl:<11,.0f} {pf:<6.2f} ${exp:<7.2f} {f['label']}")

    best = filters[0]

    print("\n" + "=" * 70)
    print("OPTIMAL FILTER (Optimization 2.0 scoring, gates IGNORED)")
    print("=" * 70)
    print(f"  Optimal: {best['label']}")
    print(f"  Trades: {best['n']} (baseline {baseline['Total_Trades']})")
    print(f"  Score: {best['score']:.1f}")
    m = best["metrics"]
    print(f"  PPCD: ${m['Profit_Per_Capital_Day']:.2f}  PNL: ${m['Total_PNL']:,.0f}  PF: {m['Profit_Factor']:.2f}  Exp: ${m['Expectancy']:.2f}")
    print()
    print("  Core filter: TOUCH_COUNT_MINOR <= 1, TOUCH_COUNT >= 5")
    print("  (Zones with few minor touches and 5+ total = quality-tested levels)")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
