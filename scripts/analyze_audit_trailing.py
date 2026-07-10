"""Analyze audit reports and closed trades for trailing-stop effectiveness."""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

DRIVE = Path(r"C:\Users\songg\Downloads\stockresearch\Drive")
TRAIL_PARAMS = {
    "trailing_stop_increment",
    "atr_progress",
    "atr_days",
    "atr_stop",
    "atr_target",
    "sell_ind_diff_below",
    "exit_ind_diff_only",
}


def pnl_pct_series(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace("%", "", regex=False), errors="coerce")


def analyze_closed() -> None:
    files = {
        "BRT": DRIVE / "BRT_Closed_260526180517.csv",
        "IND": DRIVE / "IND_Closed_260526180541.csv",
        "RL": DRIVE / "BRT_Closed_RL_260526180422.csv",
    }
    print("=== EXIT_TYPE by system (latest DailyRun closed files) ===")
    for name, fp in files.items():
        if not fp.exists():
            print(f"{name}: missing {fp.name}")
            continue
        df = pd.read_csv(fp)
        print(f"\n{name} ({len(df)} trades) — config from matching audit row:")
        et = df["EXIT_TYPE"].value_counts()
        for k, v in et.items():
            print(f"  {k}: {v} ({100 * v / len(df):.1f}%)")
        pnl = pnl_pct_series(df["PNL_PCT"])
        wins = df[pnl > 0]
        losses = df[pnl <= 0]
        print(f"  Avg win %: {pnl_pct_series(wins['PNL_PCT']).mean():.2f}")
        print(f"  Avg loss %: {pnl_pct_series(losses['PNL_PCT']).mean():.2f}")
        print(f"  Median days held: {df['DAYS_HELD'].median():.0f}")


def analyze_audit_sweeps(max_files: int = 120) -> None:
    audits = sorted(DRIVE.glob("*_Audit_Report_*.csv"))
    audits = [p for p in audits if "RL" not in p.name or p.name.startswith("IND")]
    audits = [p for p in audits if not p.name.endswith("_RL.csv")]
    audits = audits[-max_files:]

    print(f"\n=== Trailing-related Param_Name sweeps (last {len(audits)} audit CSVs) ===")
    param_reports: dict[tuple[str, str], list] = defaultdict(list)

    for fp in audits:
        prefix = "IND" if fp.name.startswith("IND") else "BRT"
        try:
            df = pd.read_csv(fp)
        except Exception:
            continue
        if "Param_Name" not in df.columns:
            continue
        pn = df["Param_Name"].fillna("").astype(str)
        for p in TRAIL_PARAMS:
            sub = df[pn == p]
            if len(sub) < 2:
                continue
            sub = sub.copy()
            sub["Total_PNL"] = pd.to_numeric(sub["Total_PNL"], errors="coerce")
            sub["Max_DD"] = pd.to_numeric(sub.get("Max_DD"), errors="coerce")
            sub["Profit_Factor"] = pd.to_numeric(sub.get("Profit_Factor"), errors="coerce")
            if not sub["Total_PNL"].notna().any():
                continue
            best = sub.loc[sub["Total_PNL"].idxmax()]
            baseline = sub[sub["Param_Value"].astype(str).isin(["0", "0.0", "False", "false"])]
            base_pnl = (
                float(baseline["Total_PNL"].iloc[0])
                if len(baseline) and pd.notna(baseline["Total_PNL"].iloc[0])
                else None
            )
            param_reports[(prefix, p)].append(
                {
                    "file": fp.name,
                    "n": len(sub),
                    "best_val": best["Param_Value"],
                    "best_pnl": float(best["Total_PNL"]),
                    "best_dd": float(best["Max_DD"]) if pd.notna(best["Max_DD"]) else None,
                    "best_pf": float(best["Profit_Factor"]) if pd.notna(best.get("Profit_Factor")) else None,
                    "base_pnl": base_pnl,
                    "trail_inc": df["trailing_stop_increment"].iloc[0]
                    if "trailing_stop_increment" in df.columns
                    else None,
                    "atr_prog": df["atr_progress"].iloc[0] if "atr_progress" in df.columns else None,
                }
            )

    for (prefix, p), rows in sorted(param_reports.items()):
        print(f"\n{prefix} — sweep param: {p} ({len(rows)} reports with multi-value sweep)")
        # aggregate: how often is best value != 0/off
        best_vals = [str(r["best_val"]) for r in rows]
        non_zero = sum(1 for v in best_vals if v not in ("0", "0.0", "False", "false", ""))
        print(f"  Best value non-zero/off in {non_zero}/{len(rows)} reports")
        for r in rows[-2:]:
            uplift = ""
            if r["base_pnl"] is not None and r["base_pnl"] != 0:
                uplift = f" vs baseline PNL {r['base_pnl']:.0f} ({100*(r['best_pnl']/r['base_pnl']-1):+.1f}%)"
            print(
                f"  {r['file']}: best={r['best_val']} PNL={r['best_pnl']:.0f} "
                f"DD={r['best_dd']} PF={r['best_pf']}{uplift} "
                f"[cfg trail_inc={r['trail_inc']} atr_prog={r['atr_prog']}]"
            )


def config_snapshot() -> None:
    print("\n=== Config snapshot (latest per-system audit, Param_Name empty row) ===")
    for prefix, pattern in [("BRT", "BRT_Audit_Report_260526180517.csv"), ("IND", "IND_Audit_Report_260526180541.csv")]:
        fp = DRIVE / pattern
        if not fp.exists():
            continue
        df = pd.read_csv(fp)
        row = df[df["Param_Name"].fillna("").astype(str) == ""].iloc[0]
        keys = [
            "stop_pct",
            "target_pct",
            "atr_target",
            "atr_stop",
            "trailing_stop_increment",
            "atr_progress",
            "atr_days",
            "indicator_buy",
            "indicator_diff",
            "sell_ind_diff_below",
            "min_ind_score",
            "min_atr_pct_at_entry",
        ]
        print(f"\n{prefix} ({pattern}):")
        for k in keys:
            if k in row.index:
                print(f"  {k}: {row[k]}")


def compare_trailing_increment_runs() -> None:
    """Find closed files / audits where trailing_stop_increment > 0."""
    print("\n=== Reports with trailing_stop_increment > 0 in config row ===")
    found = 0
    for fp in sorted(DRIVE.glob("*_Audit_Report_*.csv"))[-200:]:
        try:
            df = pd.read_csv(fp, nrows=5)
        except Exception:
            continue
        if "trailing_stop_increment" not in df.columns:
            continue
        v = pd.to_numeric(df["trailing_stop_increment"].iloc[0], errors="coerce")
        if pd.notna(v) and float(v) > 0:
            found += 1
            pnl = pd.to_numeric(df["Total_PNL"].iloc[0], errors="coerce")
            print(f"  {fp.name}: trailing_stop_increment={v}, Total_PNL={pnl}")
    if found == 0:
        print("  (none in last 200 audit files)")


if __name__ == "__main__":
    analyze_closed()
    config_snapshot()
    compare_trailing_increment_runs()
    analyze_audit_sweeps()
