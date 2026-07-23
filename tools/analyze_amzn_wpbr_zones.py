#!/usr/bin/env python3
"""Forensics: AMZN WPBR engine zones vs spreadsheet ground truth."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "stock_analysis"))
sys.path.insert(0, str(REPO / "tools"))

import pandas as pd
from wpbr_compare_filter import SHEET_COMPARE_MIN_DATE, filter_wpbr_output_for_compare
from wpbr_sheet_ground_truth import load_wpbr_ground_truth
from wpbr_zones import aggregate_weekly, compute_wpbr_touch_stream, _weekly_pivot_indices


def _key(zl: float, zh: float) -> tuple[float, float]:
    return (round(zl, 2), round(zh, 2))


def main() -> int:
    df = pd.read_csv(REPO / "data/newdata/data/AMZN.csv", index_col=0, parse_dates=True)
    out = filter_wpbr_output_for_compare(
        compute_wpbr_touch_stream(df, band_pct=0.015, breakout_confirmation=0.03),
        df,
        min_date=SHEET_COMPARE_MIN_DATE,
    )
    gt = load_wpbr_ground_truth()["AMZN"]
    sheet = gt.zones
    engine = out["wpbr_zone_events"]

    sheet_by_key = {_key(z.zone_lower, z.zone_upper): z for z in sheet}
    engine_by_key = {_key(ev["zone_lower"], ev["zone_upper"]): ev for ev in engine}

    only_engine = [ev for ev in engine if _key(ev["zone_lower"], ev["zone_upper"]) not in sheet_by_key]
    only_sheet = [z for z in sheet if _key(z.zone_lower, z.zone_upper) not in engine_by_key]

    print(f"Sheet zones: {len(sheet)}")
    print(f"Engine zones: {len(engine)}")
    print(f"Matched by (zone_lower, zone_upper): {len(engine) - len(only_engine)}")
    print(f"Engine-only: {len(only_engine)}")
    print(f"Sheet-only (no engine bounds match): {len(only_sheet)}")
    print()

    # Weekly pivot audit
    weekly = aggregate_weekly(df)
    wh = weekly["High"].to_numpy(dtype=float)
    wl = weekly["Low"].to_numpy(dtype=float)
    w_index = pd.DatetimeIndex(weekly.index)
    pivots = _weekly_pivot_indices(
        wh, wl, pre_bars=3, post_bars=3, pre_pct=0.10, post_pct=0.10, pivot_mode="either"
    )

    def week_monday(we: pd.Timestamp) -> str:
        return (pd.Timestamp(we).normalize() - pd.Timedelta(days=4)).strftime("%Y-%m-%d")

    print(f"Raw weekly pivot indices (strong 3/10% either): {len(pivots)}")
    print()

    print("=== ALL ENGINE-ONLY ZONES (by pivot date) ===")
    for ev in sorted(only_engine, key=lambda e: e["pivot_monday"]):
        bo = ev.get("breakout_monday") or "—"
        conf = ev.get("conf_monday") or "—"
        ret = ev.get("retest_bar", -1)
        sig = ev.get("entry_signal_bar", -1)
        has_bo = bool(ev.get("breakout_monday"))
        has_conf = bool(ev.get("conf_monday"))
        has_trade = sig is not None and sig >= 0
        print(
            f"  pivot={ev['pivot_monday']}  z=({ev['zone_lower']},{ev['zone_upper']})  "
            f"high={ev['pivot_high']:.2f}  bo={bo}  conf={conf}  "
            f"retest={ret}  signal={sig}  "
            f"[bo={has_bo} conf={has_conf} trade={has_trade}]"
        )

    # Check if sheet pivot dates are subset of engine pivot mondays
    engine_pivot_mondays = {ev["pivot_monday"].replace("-", "") for ev in engine}
    sheet_pivot_dates = {z.pivot_date for z in sheet}
    engine_only_pivots = sorted(engine_pivot_mondays - sheet_pivot_dates)
    sheet_only_pivots = sorted(sheet_pivot_dates - engine_pivot_mondays)

    print()
    print(f"Engine pivot mondays not in sheet Pivot Date: {len(engine_only_pivots)}")
    for p in engine_only_pivots[:15]:
        ev = next(e for e in engine if e["pivot_monday"].replace("-", "") == p)
        print(f"  {p}  z=({ev['zone_lower']},{ev['zone_upper']})")
    if len(engine_only_pivots) > 15:
        print(f"  ... {len(engine_only_pivots) - 15} more")

    print()
    print(f"Sheet pivot dates not in engine: {len(sheet_only_pivots)}")
    for p in sheet_only_pivots:
        z = next(z for z in sheet if z.pivot_date == p)
        print(f"  {p}  z=({z.zone_lower},{z.zone_upper})")

    # Overlap: same pivot week, different zone bounds?
    print()
    print("=== Sheet rows: pivot date match in engine but different bounds? ===")
    engine_by_pivot = {}
    for ev in engine:
        engine_by_pivot.setdefault(ev["pivot_monday"].replace("-", ""), []).append(ev)
    for z in sheet:
        p = z.pivot_date
        cands = engine_by_pivot.get(p, [])
        if not cands:
            continue
        if any(_key(ev["zone_lower"], ev["zone_upper"]) == _key(z.zone_lower, z.zone_upper) for ev in cands):
            continue
        print(f"  sheet pivot {p} z=({z.zone_lower},{z.zone_upper})  engine at same pivot:")
        for ev in cands:
            print(f"    -> ({ev['zone_lower']},{ev['zone_upper']}) high={ev['pivot_high']}")

    # Dedup hypothesis: overlapping zones - keep only highest pivot per period?
    print()
    print("=== Engine-only zones WITH breakout (might be suppressed in sheet) ===")
    with_bo = [ev for ev in only_engine if ev.get("breakout_monday")]
    without_bo = [ev for ev in only_engine if not ev.get("breakout_monday")]
    print(f"  with BO: {len(with_bo)}  without BO: {len(without_bo)}")

    # Check nested/overlapping zones
    print()
    print("=== For each engine-only zone: nearest sheet zone by pivot proximity ===")
    sheet_sorted = sorted(sheet, key=lambda z: z.pivot_date)
    for ev in sorted(only_engine, key=lambda e: e["pivot_monday"])[:24]:
        pm = ev["pivot_monday"].replace("-", "")
        # find closest sheet pivot by date
        best = min(sheet_sorted, key=lambda z: abs(int(z.pivot_date) - int(pm)))
        print(
            f"  engine {pm} ({ev['zone_lower']},{ev['zone_upper']})  "
            f"nearest sheet {best.pivot_date} ({best.zone_lower},{best.zone_upper})  "
            f"delta_days~{abs(int(best.pivot_date)-int(pm))//10000*365 + (int(best.pivot_date)%10000-int(pm)%10000)}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
