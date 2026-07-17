"""
Sweep RL_TRAIL_* on a fixed ticker list (same universe as run_audit -s).

Matches run_audit.ps1: only passes SMA_QUAL, SKIP_TRIM, RL_INPUT_MANIFEST (+ trail + OUT_FILE).
All other parameters use portfolio_audit.awk BEGIN defaults.

Usage:
  python stock_analysis/trail_param_sweep.py
  python stock_analysis/trail_param_sweep.py --pnl   # rank by total PNL only (default)
  python stock_analysis/trail_param_sweep.py --multi # PNL + soft DD penalty

Optional: edit USER_TICKERS below.
"""
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(REPO, "data", "newdata", "data")
AWK = os.path.join(REPO, "stock_analysis", "portfolio_audit.awk")
OUT_DIR = os.path.join(REPO, "stock_analysis", "_trail_sweep_user")
GAWK_CANDIDATES = (
    r"C:\Program Files\Git\usr\bin\gawk.exe",
    r"C:\Program Files (x86)\Git\usr\bin\gawk.exe",
)

# Exact list from your run_audit -s (order preserved; SPY added first in manifest).
USER_TICKERS = [
    "TSLA", "AMD", "INTC", "XOM", "LRCX", "NFLX", "PLTR", "KLAC", "WFC", "ADI", "STX", "WDC", "ANET", "APP",
    "TOELY", "IBKR", "CRWD", "ATEYY", "NEM", "AEM", "CNQ", "FCX", "FTNT", "MPWR", "MELI", "B", "FIX", "RCL",
    "GM", "TER", "OKE", "OXY", "AU", "TRGP", "DVN", "FLEX", "CCJ", "ARGX", "F", "CLS", "IDXX", "EME", "GFI",
    "ARES", "KGC", "ESLT", "STLD", "MTZ", "TECK", "WDAY", "TWLO", "NRG", "RMD", "FOXA", "FTAI", "NTRA", "FTI",
    "MTSI", "TPR", "STRL", "CFG", "FOX", "FSLR", "ALB", "FN", "KEY", "AKAM", "TEAM", "BEP", "LEN", "CRS", "RL",
    "DKS", "AMKR", "NXT",
]

COLS = [
    "Drive", "Cash", "Qual", "Dip", "Stop", "Target", "Exp", "AccMin", "AccCnt",
    "TooHi", "TP1", "TS1", "TP2", "TS2", "AtHi", "AtLo", "SlopePd", "SlopeTh",
    "ExitDays", "ExitPct", "PartTarget", "PartPct", "PartFollow",
    "SPY_Inclusion", "RL_Flush_Days", "AVG_VOL_DAYS", "VOL_PCT_THRESHOLD",
    "PNL", "Wins", "Losses", "BE", "PctWin", "PctLoss", "WLRatio", "Profit_Factor",
    "MaxStreak", "AvgWin", "AvgLoss", "AvgPNL", "Expectancy", "OpenW", "OpenValW",
    "AvgOpenW", "OpenL", "OpenValL", "AvgOpenL", "Toggle100", "PNL100", "Wins100",
    "Losses100", "AvgDays", "MedDays", "Ann_ROR", "Max_DD",
    "Avg_CES", "MedCES", "P90_Days", "TimedExitCnt", "TotalHoldDays", "ProfitPerCapDay",
    "Pct_Time_Underwater", "Max_Consec_Underwater", "Max_Pos",
]


def find_gawk() -> str:
    for p in GAWK_CANDIDATES:
        if os.path.isfile(p):
            return p
    import shutil

    w = shutil.which("gawk")
    if w:
        return w
    raise FileNotFoundError("gawk not found")


def build_manifest(symbols: list[str]) -> str:
    spy = os.path.join(DATA_DIR, "SPY.csv")
    if not os.path.isfile(spy):
        raise FileNotFoundError(spy)
    lines = [spy.replace("\\", "/")]
    missing: list[str] = []
    for sym in symbols:
        sym = sym.strip().upper()
        if not sym or sym == "SPY":
            continue
        p = os.path.join(DATA_DIR, f"{sym}.csv")
        if os.path.isfile(p):
            lines.append(p.replace("\\", "/"))
        else:
            missing.append(sym)
    if missing:
        print(f"[WARN] Missing CSV for {len(missing)} symbols (skipped): {', '.join(missing[:20])}{'...' if len(missing) > 20 else ''}", file=sys.stderr)
    if len(lines) <= 1:
        raise RuntimeError("No ticker CSVs found for manifest (need SPY + at least one symbol).")
    os.makedirs(OUT_DIR, exist_ok=True)
    mf = os.path.join(OUT_DIR, "manifest_user_tickers.txt")
    with open(mf, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Manifest: {len(lines)} paths ({len(lines) - 1} tickers + SPY)")
    return mf.replace("\\", "/")


def run_scenario(gawk: str, manifest_unix: str, trail: dict[str, str], run_id: int) -> dict:
    """Same -v surface as run_audit.ps1 (plus OUT_FILE, RUN_TS, trail)."""
    out_path = os.path.join(OUT_DIR, f"row_{run_id}.csv").replace("\\", "/")
    run_ts = f"uswp{run_id}_{int(time.time())}"
    args = [
        gawk,
        "-f",
        AWK.replace("\\", "/"),
        "-v",
        "SMA_QUAL=1",
        "-v",
        "SKIP_TRIM=1",
        "-v",
        f"RL_TRAIL_PROFIT={trail['RL_TRAIL_PROFIT']}",
        "-v",
        f"RL_TRAIL_STOP={trail['RL_TRAIL_STOP']}",
        "-v",
        f"RL_TRAIL_PROFIT2={trail['RL_TRAIL_PROFIT2']}",
        "-v",
        f"RL_TRAIL_STOP2={trail['RL_TRAIL_STOP2']}",
        "-v",
        f"OUT_FILE={out_path}",
        "-v",
        f"RUN_TS={run_ts}",
        "-v",
        f"RL_INPUT_MANIFEST={manifest_unix}",
    ]
    subprocess.run(args, cwd=REPO, check=True, capture_output=True, text=True)
    with open(out_path.replace("/", os.sep), newline="", encoding="utf-8", errors="replace") as f:
        r = next(csv.reader(f))
    if len(r) != len(COLS):
        raise RuntimeError(f"Expected {len(COLS)} cols, got {len(r)} trail={trail}")
    row = dict(zip(COLS, r))
    row["_PNL"] = float(row["PNL"])
    row["_Max_DD"] = float(row["Max_DD"])
    row["_Ann_ROR"] = float(row["Ann_ROR"])
    row["_PF"] = float(row["Profit_Factor"])
    row["_CES"] = float(row["Avg_CES"])
    row["_multi"] = row["_PNL"] - row["_Max_DD"] * 500000.0
    return row


def scenario_grid() -> list[tuple[str, dict[str, str]]]:
    out: list[tuple[str, dict[str, str]]] = []
    z = {"RL_TRAIL_PROFIT2": "0", "RL_TRAIL_STOP2": "0"}

    out.append(("OFF_trail_0_0", {**z, "RL_TRAIL_PROFIT": "0", "RL_TRAIL_STOP": "0"}))

    tp_vals = ["0.08", "0.10", "0.12", "0.14", "0.15", "0.18"]
    ts_vals = ["-0.03", "-0.01", "0", "0.03", "0.045", "0.07"]

    for tp in tp_vals:
        for ts in ts_vals:
            label = f"S1_tp{tp}_ts{ts}".replace(".", "p")
            out.append((label, {**z, "RL_TRAIL_PROFIT": tp, "RL_TRAIL_STOP": ts}))

    # Second stage: only a tight grid around common “give back” configs (stage1 fixed mid).
    tp1, ts1 = "0.12", "0.03"
    for tp2 in ["0.28", "0.32", "0.36", "0.40"]:
        for ts2 in ["0.10", "0.14", "0.18", "0.22"]:
            label = f"S2_tp1-{tp1}_ts1-{ts1}_tp2-{tp2}_ts2-{ts2}".replace(".", "p")
            out.append(
                (
                    label,
                    {
                        "RL_TRAIL_PROFIT": tp1,
                        "RL_TRAIL_STOP": ts1,
                        "RL_TRAIL_PROFIT2": tp2,
                        "RL_TRAIL_STOP2": ts2,
                    },
                )
            )

    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--multi", action="store_true", help="rank by PNL - 500k*Max_DD")
    args = ap.parse_args()

    gawk = find_gawk()
    mf = build_manifest(USER_TICKERS)
    grid = scenario_grid()
    print(f"gawk: {gawk}\nscenarios: {len(grid)}\nOUT_DIR: {OUT_DIR}\n")

    rows: list[dict] = []
    for i, (label, trail) in enumerate(grid):
        print(f"[{i + 1}/{len(grid)}] {label} ...", flush=True)
        r = run_scenario(gawk, mf, trail, i)
        r["_label"] = label
        r["_trail"] = trail
        rows.append(r)

    baseline_pnl = next(x["_PNL"] for x in rows if x["_label"] == "OFF_trail_0_0")
    baseline_dd = next(x["_Max_DD"] for x in rows if x["_label"] == "OFF_trail_0_0")

    for r in rows:
        r["_vs_off_pnl"] = r["_PNL"] - baseline_pnl
        r["_vs_off_dd"] = r["_Max_DD"] - baseline_dd

    if args.multi:
        rows.sort(key=lambda x: x["_multi"], reverse=True)
        sort_note = "multi (PNL - 500k*Max_DD)"
    else:
        rows.sort(key=lambda x: x["_PNL"], reverse=True)
        sort_note = "PNL descending"

    rep = os.path.join(OUT_DIR, "trail_user_universe_summary.csv")
    fields = [
        "_label",
        "TP1",
        "TS1",
        "TP2",
        "TS2",
        "PNL",
        "_vs_off_pnl",
        "Max_DD",
        "_vs_off_dd",
        "Ann_ROR",
        "Profit_Factor",
        "Avg_CES",
        "Wins",
        "Losses",
        "BE",
    ]
    with open(rep, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

    print(f"\nWrote {rep}\nSorted by: {sort_note}")
    print(f"Baseline OFF: PNL={baseline_pnl:,.2f}  Max_DD={baseline_dd:.4f}\n")
    print("Top 12 by sort key:")
    for r in rows[:12]:
        pnl = float(r["PNL"])
        dpnl = float(r["_vs_off_pnl"])
        dd = float(r["Max_DD"])
        ddd = float(r["_vs_off_dd"])
        ror = float(r["Ann_ROR"])
        print(
            f"  {str(r['_label'])[:40]:40}  PNL={pnl:>14,.0f}  dPNL={dpnl:+10,.0f}  DD={dd:.4f}  dDD={ddd:+.4f}  ROR={ror:.4f}"
        )

    best = rows[0]
    if best["_label"] == "OFF_trail_0_0":
        print("\nRecommendation: **keep trails off** (0 / 0 / 0 / 0) for this universe — no grid point beat baseline PNL.")
    else:
        print(
            f"\nRecommendation (this universe only): try **RL_TRAIL_PROFIT={best['TP1']}** **RL_TRAIL_STOP={best['TS1']}** "
            f"**RL_TRAIL_PROFIT2={best['TP2']}** **RL_TRAIL_STOP2={best['TS2']}** "
            f"(PNL {best['_PNL']:,.2f} vs OFF {baseline_pnl:,.2f}, dPNL {best['_vs_off_pnl']:+,.0f})."
        )


if __name__ == "__main__":
    main()
