#!/usr/bin/env python3
"""
Rank BRT optimizer runs using investment-size adjustment.
Primary metric: Profit_Per_Capital_Day (PnL per $1 of capital deployed per day).
Secondary: Ann_ROR, Max_DD (lower is better for risk).

Input: comma-delimited (CSV). Pass a file path or paste CSV with header.
  python rank_optimizer_runs.py
  python rank_optimizer_runs.py BRT_Optimizer_Summary.csv
"""
import csv
import io
import re
import sys

# Column indices (fallback when no header); use header-based detection when available.
# 62-col CSV: Total_Trades at 41; 63-col tab: Total_Trades at 42.
IDX_TOTAL_PNL = 33
IDX_CAPITAL_DAYS = 52
IDX_PROFIT_PER_CAPITAL_DAY = 53
IDX_ANN_ROR = 54
IDX_MAX_DD = 55
IDX_TOTAL_TRADES = 41

# Sample CSV (comma-delimited). Quote Total_PNL so commas in numbers are one field.
ROWS_CSV = """
Timestamp_Drive,pivot_k,pivot_m,pivot_d,band_pct,lookback_long,touch_threshold,close_above_window,level_acceptance_window,level_acceptance_required,tight_range_enabled,tight_range_threshold_pct,tight_range_lookback,tradeable_key_level_enabled,lookback_short,min_touch_count,max_touch_count_minor,growth_filter_enabled,growth_bars,displacement_filter_enabled,displacement_rolling_bars,displacement_threshold_pct,brt_cash,stop_pct,stop_pct_is_multiplier,target_pct,days_per_year,exit_at_close_when_stopped,compute_equity_metrics,,,Param_Name,Param_Value,Total_PNL,Wins,Losses,BE,Pct_Wins,Pct_Losses,Win_Loss_Ratio,Win_Loss_Ratio_Dollar,Total_Trades,Profit_Factor,Avg_Win_Pct,Avg_Loss_Pct,Avg_PNL_Pct,Expectancy,Expectancy_Pct,Avg_Days_Held,Median_Days_Held,P90_Days,Capital_Days,Profit_Per_Capital_Day,Ann_ROR,Max_DD,Losing_Streak,DD_Per_Trade,CES_AVG,CES_Median,Pct_PNL_Top10,Pct_PNL_Bottom10,Max_Positions
260305212812,4,7,0.06,0.02,504,4,1,10,7,FALSE,0.35,105,TRUE,105,4,1,FALSE,756,FALSE,100,0.1,47500,0.934,TRUE,1.29,365,FALSE,TRUE,,,,,"$23,124,068.20",2588,2613,5,49.71187092,50.19208605,0.9904324531,2.8,5206,2.78,29.4,-10.49,9.35,4441.81,9.35,128.3,87,285,665669,34.74,28.96,25.34,13,0,0.1663,-0.0096,1,-0.8,307
260305214533,4,7,0.06,0.02,504,6,1,10,7,FALSE,0.35,105,TRUE,105,6,100,TRUE,756,TRUE,100,0.1,47500,0.934,TRUE,1.29,365,FALSE,TRUE,,,,,"$4,096,381.10",548,706,0,43.70015949,56.29984051,0.776203966,2.73,1254,2.12,29.79,-10.91,6.88,3266.65,6.88,98.2,62,223,123063,33.29,28.04,38.72,13,0.0003,0.0538,-0.0642,6.7,-2.4,120
260305220548,4,7,0.06,0.02,504,4,1,10,7,FALSE,0.35,105,TRUE,105,4,1,TRUE,756,TRUE,100,0.1,47500,0.934,TRUE,1.29,365,FALSE,TRUE,,,,,"$3,235,223.38",373,374,0,49.9330656,50.0669344,0.9973262032,2.65,747,2.65,29.36,-11.07,9.12,4330.95,9.12,104.8,70,229,78149,41.4,35.53,24.19,6,0.0003,0.2361,0.0417,5.5,-3.5,61
260305221655,4,7,0.06,0.02,504,4,1,10,7,FALSE,0.35,105,TRUE,105,4,1,TRUE,756,FALSE,100,0.1,47500,0.934,TRUE,1.29,365,FALSE,TRUE,,,,,"$12,919,755.82",1482,1558,3,48.70193888,51.1994742,0.9512195122,2.8,3043,2.67,29.37,-10.48,8.94,4245.73,8.94,131.1,92,286,397440,32.51,26.91,54.91,9,0.0002,0.1429,-0.0221,1.6,-1.1,271
260305222925,4,7,0.06,0.02,504,4,1,10,7,FALSE,0.35,105,TRUE,105,4,1,FALSE,756,TRUE,100,0.1,47500,0.934,TRUE,1.29,365,FALSE,TRUE,,,,,"$5,570,716.53",644,640,0,50.15576324,49.84423676,1.00625,2.61,1284,2.63,29.41,-11.27,9.13,4338.56,9.13,102.8,66,231,131839,42.25,36.37,17.02,9,0.0001,0.3002,0.0406,3.5,-2.4,84
260306104440,4,7,0.06,0.02,504,4,1,10,7,TRUE,0.35,105,TRUE,105,4,1,TRUE,756,FALSE,100,0.1,47500,0.934,TRUE,1.29,365,FALSE,TRUE,,,,,"$8,550,025.78",912,792,0,53.52112676,46.47887324,1.151515152,2.66,1704,3.06,29.32,-11.04,10.56,5017.62,10.56,106.7,74,241,181565,47.09,41,35.76,6,0.0002,0.26,0.1003,2.2,-1.6,133
""".strip()

def parse_pnl(s: str) -> float:
    cleaned = re.sub(r"[$,\s]", "", str(s or ""))
    return float(cleaned) if cleaned else 0.0

def _col_idx(header_parts: list[str], name: str, alt_names: list[str] | None = None) -> int:
    """Return index of column with given name (or any of alt_names). Case-insensitive."""
    names = [name] + (list(alt_names) if alt_names else [])
    for i, h in enumerate(header_parts):
        hc = h.strip()
        for n in names:
            if hc == n or hc.lower() == n.lower():
                return i
    return -1


def _read_csv_rows(source: str | None):
    """Yield rows (lists) from CSV: from file path, or from embedded string if source is None."""
    if source:
        with open(source, newline="", encoding="utf-8-sig") as f:
            yield from csv.reader(f)
    else:
        yield from csv.reader(io.StringIO(ROWS_CSV))


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else None
    rows = list(_read_csv_rows(source))
    if not rows:
        return
    header_parts = rows[0]
    has_header = header_parts[0].strip() == "Timestamp_Drive"
    if has_header:
        idx_pnl = _col_idx(header_parts, "Total_PNL")
        idx_cap = _col_idx(header_parts, "Capital_Days")
        idx_ppcd = _col_idx(header_parts, "Profit_Per_Capital_Day")
        idx_ror = _col_idx(header_parts, "Ann_ROR")
        idx_dd = _col_idx(header_parts, "Max_DD", ["Max_Drawdown", "Max DD"])
        idx_trades = _col_idx(header_parts, "Total_Trades", ["Total Trades", "Trades", "Number_of_Trades"])
        if idx_trades < 0:
            idx_trades = IDX_TOTAL_TRADES  # fallback by position when header name not found
        data_rows = rows[1:]
    else:
        idx_pnl, idx_cap, idx_ppcd = IDX_TOTAL_PNL, IDX_CAPITAL_DAYS, IDX_PROFIT_PER_CAPITAL_DAY
        idx_ror, idx_dd, idx_trades = IDX_ANN_ROR, IDX_MAX_DD, IDX_TOTAL_TRADES
        data_rows = rows

    runs = []
    for parts in data_rows:
        if len(parts) <= max(idx_dd, idx_ppcd, idx_cap):
            continue
        ts = parts[0].strip()
        total_pnl = parse_pnl(parts[idx_pnl])
        if total_pnl == 0 and not (parts[idx_pnl].strip() if idx_pnl < len(parts) else ""):
            continue  # skip header or malformed row
        total_trades = int(float(parts[idx_trades]))
        capital_days = int(float(parts[idx_cap]))
        profit_per_cap_day = float(parts[idx_ppcd])
        ann_ror = float(parts[idx_ror])
        max_dd = float(parts[idx_dd])
        line_str = ",".join(parts)  # for MonkeyTrader check
        label = "MonkeyTrader" if "MonkeyTrader" in line_str else ts
        runs.append({
            "ts": ts,
            "label": label,
            "Total_PNL": total_pnl,
            "Capital_Days": capital_days,
            "Profit_Per_Capital_Day": profit_per_cap_day,
            "Ann_ROR": ann_ror,
            "Max_DD": max_dd,
            "Total_Trades": total_trades,
        })

    # Investment-size-adjusted ranking: Profit_Per_Capital_Day (PnL per $1 capital-day)
    # Risk-adjusted: Profit_Per_Capital_Day / (1 + Max_DD/100) to penalize drawdown
    REF_CAPITAL_DAYS = 100_000  # Normalize to 100k capital-days for "Adjusted_PNL"
    for r in runs:
        r["Adjusted_PNL_100k"] = r["Profit_Per_Capital_Day"] * REF_CAPITAL_DAYS
        r["Risk_Adj_Score"] = r["Profit_Per_Capital_Day"] / (1 + r["Max_DD"] / 100)

    # Rank by Profit_Per_Capital_Day (investment-size-adjusted return)
    by_profit_per_cap = sorted(runs, key=lambda x: x["Profit_Per_Capital_Day"], reverse=True)
    # Rank by risk-adjusted (penalize high DD)
    by_risk_adj = sorted(runs, key=lambda x: x["Risk_Adj_Score"], reverse=True)

    print("=" * 80)
    print("RANKING BY PROFIT PER CAPITAL DAY (investment-size-adjusted)")
    print("  = Total_PNL / Capital_Days — return per $1 of capital deployed per day")
    print("=" * 80)
    for i, r in enumerate(by_profit_per_cap, 1):
        print(f"{i:2}. {r['label']:15}  Profit/CapDay={r['Profit_Per_Capital_Day']:6.2f}  "
              f"Ann_ROR={r['Ann_ROR']:5.2f}%  Max_DD={r['Max_DD']:5.2f}%  "
              f"Trades={r['Total_Trades']:4}  Adj_PNL_100k=${r['Adjusted_PNL_100k']:,.0f}")

    print()
    print("=" * 80)
    print("RANKING BY RISK-ADJUSTED SCORE (Profit/CapDay ÷ (1 + Max_DD%))")
    print("  Penalizes high drawdown")
    print("=" * 80)
    for i, r in enumerate(by_risk_adj, 1):
        print(f"{i:2}. {r['label']:15}  RiskAdj={r['Risk_Adj_Score']:5.2f}  "
              f"Profit/CapDay={r['Profit_Per_Capital_Day']:6.2f}  Max_DD={r['Max_DD']:5.2f}%  "
              f"Ann_ROR={r['Ann_ROR']:5.2f}%")

if __name__ == "__main__":
    main()
