#!/usr/bin/env python3
"""Chronological OOS sanity for BRT VOL_SURGE exclude-BULL vs baseline.

Split at median DATE_OPENED of full-history C0_baseline closed trades.
Runs IS (entry_end_date=split) and OOS (entry_start_date=day after split)
for C0_baseline and X_BULL with 2 jobs x 10 workers (4 runs).
"""
from __future__ import annotations

import csv
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "tools"))

from run_brt_vol_surge_experiments import (  # noqa: E402
    CANDIDATES,
    OUT_ROOT,
    extract_metrics,
    run_candidate,
    _resolve_python,
)

from concurrent.futures import ThreadPoolExecutor, as_completed


def _split_ymd() -> str:
    closed = sorted((OUT_ROOT / "C0_baseline").glob("BRT_Closed_*.csv"))[-1]
    df = pd.read_csv(closed, usecols=["DATE_OPENED"])
    d = pd.to_datetime(df["DATE_OPENED"].astype(str), format="%Y%m%d", errors="coerce")
    return d.median().strftime("%Y%m%d")


def _next_ymd(ymd: str) -> str:
    dt = datetime.strptime(ymd, "%Y%m%d") + timedelta(days=1)
    return dt.strftime("%Y%m%d")


def main() -> int:
    py = _resolve_python()
    split = _split_ymd()
    oos_start = _next_ymd(split)
    print(f"[oos] split_ymd={split}  IS: entry_end_date={split}  OOS: entry_start_date={oos_start}")

    by_id = {c["id"]: c for c in CANDIDATES}
    jobs_spec = [
        ("C0_IS", by_id["C0_baseline"], None, split),
        ("X_BULL_IS", by_id["X_BULL"], None, split),
        ("C0_OOS", by_id["C0_baseline"], oos_start, None),
        ("X_BULL_OOS", by_id["X_BULL"], oos_start, None),
    ]

    results = []
    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = {}
        for folder, cand, start, end in jobs_spec:
            fut = ex.submit(
                run_candidate,
                py,
                cand,
                10,
                skip_existing=False,
                entry_start=start,
                entry_end=end,
                out_subdir=folder,
            )
            futs[fut] = folder
        for fut in as_completed(futs):
            folder = futs[fut]
            r = fut.result()
            r["folder"] = folder
            results.append(r)
            print(f"  [{folder}] ok={r.get('ok')} trades={(r.get('metrics') or {}).get('Total_Trades')}")

    rows = []
    for r in sorted(results, key=lambda x: x["folder"]):
        m = r.get("metrics") or {}
        rows.append(
            {
                "run": r["folder"],
                "id": r["id"],
                "ok": r.get("ok"),
                "Total_Trades": int(m.get("Total_Trades", 0) or 0),
                "Total_PNL": round(float(m.get("Total_PNL", 0) or 0), 2),
                "Profit_Factor": round(float(m.get("Profit_Factor", 0) or 0), 3),
                "Max_DD": round(float(m.get("Max_DD", 0) or 0), 2),
                "PPCD": round(float(m.get("Profit_Per_Capital_Day", 0) or 0), 4),
                "Ann_ROR": round(float(m.get("Ann_ROR", 0) or 0), 2),
                "Expectancy": round(float(m.get("Expectancy", 0) or 0), 2),
                "Pct_PNL_Max_Symbol": round(float(m.get("Pct_PNL_Max_Symbol", 0) or 0), 1),
            }
        )

    csv_path = OUT_ROOT / "oos_comparison.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    by = {r["run"]: r for r in rows}

    def lift(a: str, b: str, key: str) -> str:
        if a not in by or b not in by:
            return "n/a"
        return f"{by[a][key] - by[b][key]:+.2f}"

    lines = [
        "# BRT VOL_SURGE — Chronological OOS (exclude BULL)",
        "",
        f"Split at median baseline entry date **{split}**.",
        f"- In-sample: `entry_end_date={split}`",
        f"- Out-of-sample: `entry_start_date={oos_start}`",
        "",
        "| run | trades | PNL | PF | MaxDD | PPCD | AnnROR | MaxSym% |",
        "|-----|-------:|----:|---:|------:|-----:|-------:|--------:|",
    ]
    for r in rows:
        lines.append(
            f"| {r['run']} | {r['Total_Trades']} | {r['Total_PNL']:.0f} | {r['Profit_Factor']:.3f} | "
            f"{r['Max_DD']:.1f} | {r['PPCD']:.2f} | {r['Ann_ROR']:.1f} | {r['Pct_PNL_Max_Symbol']:.1f} |"
        )

    oos_ok = False
    if "X_BULL_OOS" in by and "C0_OOS" in by:
        xb, c0 = by["X_BULL_OOS"], by["C0_OOS"]
        oos_ok = (
            xb["Total_PNL"] > c0["Total_PNL"]
            and xb["Profit_Factor"] >= c0["Profit_Factor"]
            and xb["PPCD"] > c0["PPCD"]
            and xb["Max_DD"] <= c0["Max_DD"] + 1.0
        )
        lines.extend(
            [
                "",
                "## OOS delta (X_BULL − C0)",
                "",
                f"- PNL: {lift('X_BULL_OOS', 'C0_OOS', 'Total_PNL')}",
                f"- PF: {lift('X_BULL_OOS', 'C0_OOS', 'Profit_Factor')}",
                f"- PPCD: {lift('X_BULL_OOS', 'C0_OOS', 'PPCD')}",
                f"- MaxDD: {lift('X_BULL_OOS', 'C0_OOS', 'Max_DD')}",
                "",
                f"**OOS multi-metric pass:** {'YES' if oos_ok else 'NO'}.",
            ]
        )
    if "X_BULL_IS" in by and "C0_IS" in by:
        lines.extend(
            [
                "",
                "## IS delta (X_BULL − C0)",
                "",
                f"- PNL: {lift('X_BULL_IS', 'C0_IS', 'Total_PNL')}",
                f"- PF: {lift('X_BULL_IS', 'C0_IS', 'Profit_Factor')}",
                f"- PPCD: {lift('X_BULL_IS', 'C0_IS', 'PPCD')}",
                f"- MaxDD: {lift('X_BULL_IS', 'C0_IS', 'Max_DD')}",
            ]
        )

    md_path = OUT_ROOT / "oos_comparison.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[oos] wrote {csv_path}")
    print(f"[oos] wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
