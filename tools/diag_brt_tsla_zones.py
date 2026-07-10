#!/usr/bin/env python3
"""TSLA BRT zone parity forensics (sheet ladder vs compute_sheet_brt_touch_stream)."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "stock_analysis"))
sys.path.insert(0, str(ROOT / "tools"))

from compare_brt_zones import _load_sheet_ladder, _zone_near_match  # noqa: E402
from rocket_brt import compute_sheet_brt_touch_stream  # noqa: E402

DATA = ROOT / "data" / "newdata" / "data" / "TSLA.csv"
SHEET = ROOT / "tools" / "tsla_brt_sheet_zones.txt"


def main() -> int:
    sheet = _load_sheet_ladder(SHEET)
    df = pd.read_csv(DATA, parse_dates=["Date"], index_col="Date")
    r = compute_sheet_brt_touch_stream(
        df, band_pct=0.0154, touch_pullback_pct=0.108, maturity_lag=7
    )
    events = r["brt_matured_zone_events"]
    eng = [
        (
            round(ev["zone_center"], 2),
            round(ev["zone_lower"], 2),
            round(ev["zone_upper"], 2),
        )
        for ev in events
    ]

    used = [False] * len(eng)
    sheet_only: list[tuple[float, float, float]] = []
    for s in sheet:
        hit = False
        for j, e in enumerate(eng):
            if not used[j] and _zone_near_match(s, e, 0.01):
                used[j] = True
                hit = True
                break
        if not hit:
            sheet_only.append(s)

    eng_only: list[dict] = []
    for j, (e, ev) in enumerate(zip(eng, events)):
        if used[j]:
            continue
        mb = int(ev["maturity_bar"])
        pb = int(ev["pivot_bar"])
        eng_only.append(
            {
                "zone": e,
                "maturity": str(df.index[mb].date()),
                "pivot": str(df.index[pb].date()),
                "high": float(df["High"].iloc[pb]),
            }
        )

    print("=" * 80)
    print(f"TSLA zones  sheet={len(sheet)}  engine={len(eng)}")
    print(f"Multiset exact: {sum(min(Counter(sheet)[k], Counter(eng).get(k, 0)) for k in Counter(sheet))}/{len(sheet)}")
    print("=" * 80)

    if sheet_only:
        print("\nSHEET-ONLY (engine missing):")
        for z in sheet_only:
            print(f"  {z[0]}/{z[1]}/{z[2]}")
            # Oct 2021 context for 291.31
            if abs(z[0] - 291.31) < 0.02:
                sub = df[(df.index >= "2021-10-01") & (df.index <= "2021-10-25")]
                print("    Yahoo highs Oct 2021:")
                for d, row in sub.iterrows():
                    h = float(row["High"])
                    if h > 265:
                        print(f"      {d.date()}  High={h:.4f}")

    if eng_only:
        print("\nENGINE-ONLY (not on sheet ladder):")
        for row in eng_only:
            print(
                f"  {row['zone'][0]}/{row['zone'][1]}/{row['zone'][2]}  "
                f"pivot={row['pivot']}  mature={row['maturity']}  High={row['high']:.4f}"
            )

    # Sheet has both 291.31 and 291.85
    has_old = any(abs(z[0] - 291.31) < 0.01 for z in sheet)
    has_new = any(abs(z[0] - 291.85) < 0.01 for z in sheet)
    print(f"\nSheet ladder has 291.31 zone: {has_old}  291.85 zone: {has_new}")
    print("291.31 likely needs Google Finance High on ~2021-10-18 (Yahoo=291.7533 -> 291.75).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
