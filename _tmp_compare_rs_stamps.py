import csv
import collections
from pathlib import Path

ROOT = Path(r"C:\Users\songg\Downloads\stockresearch")


def load_audit(path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return rows[0] if rows else {}


def load_closed(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fnum(x):
    try:
        return float(str(x).replace("%", "").replace(",", ""))
    except Exception:
        return None


cand = load_audit(ROOT / "drive/RS_Audit_Report_260731212031.csv")
ctrl = load_audit(ROOT / "drive/RS_Audit_Report_260731204706.csv")

keys_metrics = [
    "Total_PNL",
    "Wins",
    "Losses",
    "BE",
    "Pct_Wins",
    "Total_Trades",
    "Profit_Factor",
    "Avg_Win_Pct",
    "Avg_Loss_Pct",
    "Avg_PNL_Pct",
    "Expectancy",
    "Expectancy_Pct",
    "Ann_ROR",
    "Max_DD",
    "Losing_Streak",
    "Score",
    "Avg_Days_Held",
    "Median_Days_Held",
    "Capital_Days",
    "Profit_Per_Capital_Day",
    "Aggressive_Total_PNL",
    "Aggressive_Max_DD",
    "Avg_Positions",
    "Max_Positions",
    "Pct_PNL_Top10",
    "Win_Loss_Ratio",
    "Win_Loss_Ratio_Dollar",
    "CES_AVG",
    "CES_Median",
]

metric_set = set(keys_metrics) | {
    "Aggressive_Avg_Positions",
    "Aggressive_Days_AtOrBelow_Avg",
    "Aggressive_Days_In_Margin",
    "Aggressive_Days_Trimmed_Over_2xAvg",
    "Trades_With_Meteoric_Rise_History",
    "Pct_Trades_With_Meteoric_Rise_History",
    "Trades_With_Meteoric_Fall_History",
    "Pct_Trades_With_Meteoric_Fall_History",
    "Trades_Post_Entry_Gain_Hit",
    "Pct_Trades_Post_Entry_Gain_Hit",
    "Pct_PNL_Max_Symbol",
    "Pct_PNL_Max_Trade",
    "Pct_PNL_Max_Industry",
    "Pct_PNL_Bottom10",
    "DD_Per_Trade",
    "Avg_Days_Underwater",
    "P90_Days_Underwater",
    "P90_Days",
    "Pct_Losses",
    "aggressive_avg_positions_actual",
}

print("=== CONFIG DIFFS (non-metric) ===")
for k in cand:
    if k in ("Timestamp_Drive",) or k in metric_set:
        continue
    if str(cand.get(k, "")) != str(ctrl.get(k, "")):
        print(f"  {k}: cand={cand.get(k)!r}  ctrl={ctrl.get(k)!r}")

print("\n=== METRICS ===")
hdr = f"{'metric':30s} {'cand_212031':>16s} {'ctrl_204706':>16s} {'delta':>12s}"
print(hdr)
for k in keys_metrics:
    a, b = fnum(cand.get(k)), fnum(ctrl.get(k))
    if a is None and b is None:
        print(f"{k:30s} {str(cand.get(k)):>16s} {str(ctrl.get(k)):>16s}")
    else:
        d = (a - b) if (a is not None and b is not None) else None
        ds = f"{d:+.4f}" if d is not None else ""
        as_ = f"{a:.4f}" if a is not None else str(cand.get(k))
        bs_ = f"{b:.4f}" if b is not None else str(ctrl.get(k))
        print(f"{k:30s} {as_:>16s} {bs_:>16s} {ds:>12s}")


def exit_reason(r):
    for k in (
        "EXIT_REASON",
        "Exit_Reason",
        "exit_reason",
        "SELL_REASON",
        "REASON",
        "ExitReason",
    ):
        if k in r and r[k]:
            return r[k]
    return ""


def pnl_of(r):
    for k in ("PNL", "Total_PNL", "SHEET_PNL", "PnL", "pnl"):
        if k in r and r[k] not in ("", None):
            v = fnum(r[k])
            if v is not None:
                return v
    return None


def gap_stats(rows, label):
    exits = collections.Counter(exit_reason(r) for r in rows)
    print(f"\n=== {label} exit reasons ===")
    for reason, n in exits.most_common(25):
        print(f"  {n:4d}  {reason!r}")
    gd = [r for r in rows if "GAP_DOWN" in str(exit_reason(r)).upper()]
    gd_pnl = [pnl_of(r) for r in gd]
    gd_pnl = [x for x in gd_pnl if x is not None]
    print(f"  GAP_DOWN count={len(gd)}  pnl_sum={sum(gd_pnl):.2f}  avg={sum(gd_pnl)/len(gd_pnl) if gd_pnl else 0:.2f}")
    # fat-ish: look at any column mentioning FAT/GAP
    fat_cols = [c for c in rows[0] if "FAT" in c.upper() or "GAP" in c.upper()]
    print(f"  fat/gap cols: {fat_cols}")
    return gd


cc = load_closed(ROOT / "drive/RS_Closed_260731212031.csv")
ct = load_closed(ROOT / "drive/RS_Closed_260731204706.csv")
print("\nClosed cols:", list(cc[0].keys()))
gap_stats(cc, "CAND 212031")
gap_stats(ct, "CTRL 204706")

sk = "SYMBOL" if "SYMBOL" in cc[0] else "Symbol"
print("\nCand symbols:", sorted(set(r[sk] for r in cc)), "n_sym=", len(set(r[sk] for r in cc)), "trades=", len(cc))
print("Ctrl symbols:", sorted(set(r[sk] for r in ct)), "n_sym=", len(set(r[sk] for r in ct)), "trades=", len(ct))

# ImproveHints
for stamp in ("260731212031", "260731204706"):
    p = ROOT / f"drive/RS_ImproveHints_{stamp}.md"
    if p.exists():
        print(f"\n=== ImproveHints {stamp} ===")
        print(p.read_text(encoding="utf-8")[:2000])
