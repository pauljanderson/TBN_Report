#!/usr/bin/env python3
"""Forensics for TSLA sheet vs engine zone-swap breakouts (same date, different band)."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stock_analysis"))

from rocket_brt import _sheet_breakout_zone_bounds_long  # noqa: E402


def _pm(s) -> str:
    s = str(s).strip() if pd.notna(s) else ""
    if not s or s.lower() == "nan":
        return ""
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def main() -> int:
    sheet = pd.read_csv(ROOT / "tools/tsla_sheet_breakout_retest.tsv", sep="\t", dtype=str)
    eng = pd.read_csv(ROOT / "drive/YH_breakout_and_retest_260621072339.csv")
    sheet = sheet[sheet["Breakout Active"].astype(str).str.strip() == "1"]
    for df in (sheet, eng):
        df["bo"] = df["Breakout Date"].map(_pm)
        df["zl"] = df["Zone Lower"].str.replace("$", "", regex=False).astype(float).round(2)
        df["zu"] = df["Zone Upper"].astype(float).round(2)
        df["key"] = list(zip(df["bo"], df["zl"], df["zu"]))

    s_only = set(sheet["key"]) - set(eng["key"])
    e_only = set(eng["key"]) - set(sheet["key"])
    dates = sorted({k[0] for k in s_only})

    ohlc = pd.read_csv(ROOT / "data/newdata/data/TSLA.csv", parse_dates=["Date"]).sort_values("Date")
    ohlc = ohlc.reset_index(drop=True)
    iso = [d.strftime("%Y%m%d") for d in ohlc["Date"]]
    iso_to_i = {s: i for i, s in enumerate(iso)}

    zones = pd.read_csv(ROOT / "drive/YH_ZONES_TSLA_260621071957.csv", parse_dates=["DATE"])
    zlo_col, zhi_col = "ZONE_LOW", "ZONE_HIGH"

    print(f"Zone-swap dates: {len(dates)}\n")
    print(
        f"{'Date':<12} {'gap%':>6} {'spr%':>6}  "
        f"{'sheet zu':>8} {'eng zu':>8}  pick_max_would_fix"
    )

    fix_max = fix_gap8 = 0
    for d in dates:
        sk = next(k for k in s_only if k[0] == d)
        ek = next(k for k in e_only if k[0] == d)
        sr = sheet[sheet["key"] == sk].iloc[0]
        er = eng[eng["key"] == ek].iloc[0]

        bo_iso = d.replace("-", "")
        i = iso_to_i.get(bo_iso)
        if i is None or i < 1:
            continue
        prev_c = float(ohlc.iloc[i - 1]["Close"])
        op = float(ohlc.iloc[i]["Open"])
        cl = float(ohlc.iloc[i]["Close"])
        gap = (op - prev_c) / prev_c if prev_c > 0 else 0.0
        spread = (sk[2] - ek[2]) / ek[2] if ek[2] > 0 else 0.0

        # Qualifying YH zones on this bar (activation_bar <= i)
        hp, hc = round(prev_c, 2), round(cl, 2)
        quals = []
        for _, z in zones[zones["DATE"] <= ohlc.iloc[i]["Date"]].iterrows():
            zu = round(float(z[zhi_col]), 2)
            zl = round(float(z[zlo_col]), 2)
            if zu > hp and zu <= hc:
                quals.append((zl, zu))
        min_zu = min(q[1] for q in quals) if quals else float("nan")
        max_zu = max(q[1] for q in quals) if quals else float("nan")
        max_fix = abs(max_zu - sk[2]) < 0.02
        gap_fix = gap > 0.08 and spread > 0.08
        if max_fix:
            fix_max += 1
        if gap_fix:
            fix_gap8 += 1

        print(
            f"{d:<12} {gap*100:6.1f} {spread*100:6.1f}  "
            f"{sk[2]:8.2f} {ek[2]:8.2f}  max_zu={max_zu:.2f} min_zu={min_zu:.2f}  "
            f"{'YES' if max_fix else 'no'}"
        )

    print(f"\nIf engine always picked MAX crossed zu: {fix_max}/{len(dates)} would match sheet")
    print(f"If engine gap>8% AND spread>8% rule:     {fix_gap8}/{len(dates)} would match sheet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
