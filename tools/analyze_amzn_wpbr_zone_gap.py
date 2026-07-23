#!/usr/bin/env python3
"""AMZN WPBR zone gap: categorize engine-only vs sheet."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "stock_analysis"))
sys.path.insert(0, str(REPO / "tools"))

import pandas as pd
from wpbr_compare_filter import SHEET_COMPARE_MIN_DATE, filter_wpbr_output_for_compare
from wpbr_sheet_ground_truth import load_wpbr_ground_truth
from wpbr_zones import compute_wpbr_touch_stream

SHEET_START = int(pd.Timestamp(SHEET_COMPARE_MIN_DATE).strftime("%Y%m%d"))


def main() -> None:
    df = pd.read_csv(REPO / "data/newdata/data/AMZN.csv", index_col=0, parse_dates=True)
    raw = compute_wpbr_touch_stream(df, band_pct=0.015, breakout_confirmation=0.03)
    out = filter_wpbr_output_for_compare(raw, df, min_date=SHEET_COMPARE_MIN_DATE)
    sheet = load_wpbr_ground_truth()["AMZN"].zones
    engine = out["wpbr_zone_events"]
    engine_raw_count = len(raw["wpbr_zone_events"])

    sheet_pivots = {z.pivot_date for z in sheet}
    engine_by_pivot = {ev["pivot_monday"].replace("-", ""): ev for ev in engine}

    pre_sheet = [
        ev for ev in raw["wpbr_zone_events"]
        if int(ev["pivot_monday"].replace("-", "")) < SHEET_START
    ]
    post_sheet_extra = []
    for ev in engine:
        pm = ev["pivot_monday"].replace("-", "")
        if pm not in sheet_pivots:
            post_sheet_extra.append(ev)

    print("AMZN zone accounting")
    print("=" * 60)
    print(f"Engine total (unfiltered): {engine_raw_count}")
    print(f"Engine total (since {SHEET_COMPARE_MIN_DATE}): {len(engine)}")
    print(f"Sheet total:      {len(sheet)}")
    print(f"Gap (filtered):   {len(engine) - len(sheet)}")
    print()
    print(f"Engine pivots BEFORE {SHEET_COMPARE_MIN_DATE}: {len(pre_sheet)}")
    print(f"Engine pivots AFTER sheet start but NOT in sheet:        {len(post_sheet_extra)}")
    print(f"Sheet pivots all found in engine (by date):              {sum(1 for z in sheet if z.pivot_date in engine_by_pivot)}/{len(sheet)}")
    print()

    print("Pre-2016 engine-only zones (spreadsheet omits these):")
    for ev in pre_sheet:
        pm = ev["pivot_monday"].replace("-", "")
        bo = (ev.get("breakout_monday") or "")[:10]
        conf = (ev.get("conf_monday") or "")[:10]
        sig = ev.get("entry_signal_bar", -1)
        print(f"  {pm}  z=({ev['zone_lower']},{ev['zone_upper']})  bo={bo}  conf={conf}  signal={sig}")

    if post_sheet_extra:
        print()
        print("Post-2016 engine-only (unexpected):")
        for ev in post_sheet_extra:
            pm = ev["pivot_monday"].replace("-", "")
            print(f"  {pm}  z=({ev['zone_lower']},{ev['zone_upper']})")

    # Rounding: sheet vs engine same pivot
    print()
    print("Sheet zones with same pivot date as engine (rounding deltas):")
    tol = 0.02
    for z in sorted(sheet, key=lambda x: x.pivot_date):
        ev = engine_by_pivot.get(z.pivot_date)
        if not ev:
            print(f"  MISSING pivot {z.pivot_date}")
            continue
        zl_ok = abs(ev["zone_lower"] - z.zone_lower) < tol
        zh_ok = abs(ev["zone_upper"] - z.zone_upper) < tol
        if not (zl_ok and zh_ok):
            print(
                f"  {z.pivot_date}  sheet=({z.zone_lower},{z.zone_upper})  "
                f"engine=({ev['zone_lower']},{ev['zone_upper']})  "
                f"high={ev['pivot_high']:.4f}"
            )

    # gen_amzn count
    gen_path = REPO / "tos" / "gen_amzn_ts.py"
    if gen_path.is_file():
        import re
        text = gen_path.read_text()
        gen_zones = re.findall(r"\((\d+),\s*([\d.]+),\s*([\d.]+),\s*(\d+)\)", text)
        print()
        print(f"TOS gen_amzn_ts.py zones: {len(gen_zones)}")
        gen_pivots = {p for p, _, _, _ in gen_zones}
        print(f"  gen pivots not in sheet: {sorted(gen_pivots - sheet_pivots)}")
        print(f"  sheet pivots not in gen: {sorted(sheet_pivots - gen_pivots)}")


if __name__ == "__main__":
    main()
