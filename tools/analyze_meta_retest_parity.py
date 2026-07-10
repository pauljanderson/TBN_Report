#!/usr/bin/env python3
"""Deep analysis: sheet trade entry dates vs engine breakout/retest pipeline."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stock_analysis"))

from stock_analysis.compare_brt_breakout_sheet_program import _audit_first_retest  # noqa: E402

SHEET_TRADES = [
    ("2019-01-04", 137.56),
    ("2019-02-04", 169.15),
    ("2019-09-09", 187.44),
    ("2019-10-21", 190.00),
    ("2020-03-18", 146.62),
    ("2020-04-22", 184.08),
    ("2020-06-29", 220.59),
    ("2020-09-21", 253.31),
    ("2021-05-19", 313.58),
    ("2021-10-12", 326.97),
    ("2022-03-22", 213.33),
    ("2022-05-19", 194.97),
    ("2022-06-06", 191.93),
    ("2023-03-08", 186.35),
    ("2023-06-05", 270.14),
    ("2023-12-04", 318.98),
    ("2024-08-05", 479.00),
    ("2024-11-29", 577.50),
    ("2025-02-28", 673.68),
    ("2025-03-14", 607.46),
    ("2025-04-07", 543.25),
    ("2025-05-30", 644.39),
    ("2025-08-26", 752.30),
    ("2025-10-13", 707.78),
    ("2026-02-05", 665.49),
]


def _mdy_to_iso(s: str) -> str:
    return datetime.strptime(s, "%m/%d/%Y").strftime("%Y-%m-%d")


def _parse_rt_date(s: str) -> str:
    if not isinstance(s, str) or not s.strip():
        return ""
    dt = pd.to_datetime(s, errors="coerce")
    return "" if pd.isna(dt) else dt.strftime("%Y-%m-%d")


def _replay_retest(
    ohlc: pd.DataFrame,
    breakout_iso: str,
    zl: float,
    zu: float,
    scan_delta: int,
    rd: int = 2,
) -> tuple[str, int]:
    dates = ohlc["iso"].tolist()
    if breakout_iso not in dates:
        return "", -1
    b = dates.index(breakout_iso)
    zlr, zur = (round(zl, rd), round(zu, rd)) if rd >= 0 else (zl, zu)
    start = b + max(1, int(scan_delta))
    for k in range(start, len(ohlc)):
        lo = float(ohlc.iloc[k]["Low"])
        hi = float(ohlc.iloc[k]["High"])
        if rd >= 0:
            lo, hi = round(lo, rd), round(hi, rd)
        if lo <= zur and hi >= zlr:
            return dates[k], k - b
    return "", -1


def main() -> None:
    run_id = sys.argv[1] if len(sys.argv) > 1 else "260619083217"
    rt_path = ROOT / "Drive" / f"YH_breakout_and_retest_{run_id}.csv"
    ohlc_path = ROOT / "data" / "newdata" / "data" / "META.csv"

    rt = pd.read_csv(rt_path)
    rt = rt[rt["SYMBOL"] == "META"].copy()
    rt["bo_iso"] = rt["Breakout Date"].map(_parse_rt_date)
    rt["rt_iso"] = rt["Retest Date"].map(_parse_rt_date)
    rt["zl"] = rt["Zone Lower"].astype(str).str.replace("$", "", regex=False).astype(float)
    rt["zu"] = rt["Zone Upper"].astype(float)

    ohlc = pd.read_csv(ohlc_path, parse_dates=["Date"]).sort_values("Date")
    ohlc["iso"] = ohlc["Date"].dt.strftime("%Y-%m-%d")

    print("=" * 100)
    print("META: sheet trade log entry date vs engine breakout/retest export")
    print("Sheet buy AH uses COUNTIF(BO,D)>0 — entry day D must appear in column BO (Retest Date)")
    print("=" * 100)
    print()

    categories: dict[str, list[str]] = {
        "retest_exact": [],
        "breakout_exact_not_retest": [],
        "near_retest_1_5d": [],
        "near_retest_6_10d": [],
        "missing_retest": [],
    }

    for ed, px in SHEET_TRADES:
        row = ohlc[ohlc["iso"] == ed]
        close = float(row.iloc[0]["Close"]) if len(row) else float("nan")
        open_ = float(row.iloc[0]["Open"]) if len(row) else float("nan")

        exact_rt = rt[rt["rt_iso"] == ed]
        exact_bo = rt[rt["bo_iso"] == ed]

        # nearest retest row
        rt2 = rt[rt["rt_iso"] != ""].copy()
        rt2["delta"] = (pd.to_datetime(rt2["rt_iso"]) - pd.Timestamp(ed)).dt.days.abs()
        near = rt2.sort_values("delta").iloc[0] if len(rt2) else None

        print(f"## {ed}  sheet entry ${px:.2f}  close=${close:.2f} open=${open_:.2f}")
        if len(exact_rt):
            categories["retest_exact"].append(ed)
            r = exact_rt.iloc[0]
            print(f"   MATCH: engine Retest Date = entry ({len(exact_rt)} row(s))")
            print(
                f"   breakout={r['bo_iso']}  maturity={_parse_rt_date(str(r['Maturity Date']))}  "
                f"zone ${r['zl']:.2f}-${r['zu']:.2f}  MR={r['Main Row']}"
            )
        elif len(exact_bo):
            categories["breakout_exact_not_retest"].append(ed)
            r = exact_bo.iloc[0]
            print(f"   MISMATCH TYPE A: entry date = engine Breakout Date (not Retest Date)")
            print(
                f"   breakout={r['bo_iso']}  engine retest={r['rt_iso']}  "
                f"lag={(pd.Timestamp(r['rt_iso']) - pd.Timestamp(ed)).days if r['rt_iso'] else '?'}d  "
                f"zone ${r['zl']:.2f}-${r['zu']:.2f}"
            )
            # replay with delta 2 vs 3
            for sd in (2, 3):
                sim, bars = _replay_retest(ohlc, r["bo_iso"], r["zl"], r["zu"], sd)
                print(f"   OHLC replay first overlap (scan_delta={sd}): {sim} (+{bars} bars from BO)")
        elif near is not None and near["delta"] <= 10:
            d = int(near["delta"])
            bucket = "near_retest_1_5d" if d <= 5 else "near_retest_6_10d"
            categories[bucket].append(ed)
            print(f"   MISMATCH TYPE B: nearest engine retest {near['rt_iso']} ({d}d from entry)")
            print(
                f"   linked breakout={near['bo_iso']}  zone ${near['zl']:.2f}-${near['zu']:.2f}  "
                f"MR={near['Main Row']}"
            )
            if near["bo_iso"]:
                for sd in (2, 3):
                    sim, bars = _replay_retest(ohlc, near["bo_iso"], near["zl"], near["zu"], sd)
                    mark = " <-- engine" if sim == near["rt_iso"] else ""
                    print(f"   OHLC replay scan_delta={sd}: {sim} (+{bars} bars){mark}")
        else:
            categories["missing_retest"].append(ed)
            print(f"   MISMATCH TYPE C: no engine retest within 10d (nearest {near['rt_iso'] if near is not None else 'none'} "
                  f"{int(near['delta']) if near is not None else ''}d)")

        # Does sheet entry price look like close on entry day?
        if np.isfinite(close):
            print(f"   price check: |entry-close|={abs(px-close):.2f}  |entry-open|={abs(px-open_):.2f}")
        print()

    print("=" * 100)
    print("SUMMARY")
    print("=" * 100)
    for k, v in categories.items():
        print(f"  {k}: {len(v)}  {v}")

    print()
    print("ENGINE CONFIG (run audit):")
    print("  sheet_breakout_scan_start_row_delta = 2  (Scan Start = Main Row + 2, sheet C19)")
    print("  overlap rule: Low <= ZoneUpper AND High >= ZoneLower (same as sheet BQ/BN INDEX)")
    print("  breakout (BM/DI): prior_px < zone_upper AND current_px >= zone_upper (close-based)")


if __name__ == "__main__":
    main()
