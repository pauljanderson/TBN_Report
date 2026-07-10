#!/usr/bin/env python3
"""Compare META YH zone activations: engine vs spreadsheet date list."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stock_analysis"))

from rocket_brt import compute_yh_touch_stream  # noqa: E402

DATA = ROOT / "data" / "newdata" / "data" / "META.csv"
ENGINE_CSV = ROOT / "drive" / "YH_ZONES_META_260613075107.csv"

# Spreadsheet "matured zones" dates pasted by user (column A only).
SHEET_DATES_RAW = """
1/17/2017
1/18/2017
1/19/2017
1/20/2017
1/23/2017
""".strip().splitlines()  # placeholder; full list loaded from file if present

SHEET_DATES_FILE = ROOT / "drive" / "meta_sheet_maturity_dates.txt"


def _norm_date(s: str) -> str:
    return pd.Timestamp(s.strip()).strftime("%Y-%m-%d")


def _load_sheet_dates() -> list[str]:
    if SHEET_DATES_FILE.is_file():
        lines = SHEET_DATES_FILE.read_text(encoding="utf-8").splitlines()
    else:
        # User paste embedded in chat — write minimal; script also accepts CLI file
        lines = []
    return [_norm_date(x) for x in lines if x.strip()]


def main() -> None:
    sheet_path = Path(sys.argv[1]) if len(sys.argv) > 1 else SHEET_DATES_FILE
    df = pd.read_csv(DATA, parse_dates=["Date"]).set_index("Date").sort_index()
    n = len(df)

    cfg = dict(
        band_pct=0.02,
        lookback_long=504,
        touch_threshold=2,
        lookback_short=105,
        band_pct_atr=0.0,
        zone_price_round_decimals=2,
        yh_lookback=252,
        yh_move_away_pct=0.03,
    )

    sheet = compute_yh_touch_stream(df, yh_memory_mode="sheet", **cfg)
    fifo = compute_yh_touch_stream(df, yh_memory_mode="fifo", **cfg)
    parallel = compute_yh_touch_stream(df, yh_memory_mode="parallel", **cfg)
    eng_file = pd.read_csv(ENGINE_CSV)
    eng_dates = [_norm_date(d) for d in eng_file["DATE"]]

    ser_dates = [_norm_date(df.index[e["activation_bar"]]) for e in sheet["yh_zone_events"]]
    fifo_dates = [_norm_date(df.index[e["activation_bar"]]) for e in fifo["yh_zone_events"]]
    par_dates = [_norm_date(df.index[e["activation_bar"]]) for e in parallel["yh_zone_events"]]

    print("=== META YH zone diagnostic ===")
    print(f"Bars in META.csv: {n} ({df.index[0].date()} .. {df.index[-1].date()})")
    print(f"252-bar warmup ends ~ bar 252: {df.index[252].date() if n > 252 else 'n/a'}")
    print()
    print(f"Engine CSV activations:     {len(eng_dates)}")
    print(f"Recomputed sheet mode:      {len(ser_dates)}")
    print(f"Recomputed fifo mode:       {len(fifo_dates)}")
    print(f"Recomputed parallel:        {len(par_dates)}")
    print(f"Sheet mode matches CSV:     {ser_dates == eng_dates}")
    print()
    print("First 5 sheet-mode activations (date, center):")
    for ev in sheet["yh_zone_events"][:5]:
        ab = ev["activation_bar"]
        print(f"  {df.index[ab].date()}  center={ev['zone_center']:.2f}  yh_bar={ev['yh_bar']}")
    print()
    print("Last 5 sheet-mode activations:")
    for ev in sheet["yh_zone_events"][-5:]:
        ab = ev["activation_bar"]
        print(f"  {df.index[ab].date()}  center={ev['zone_center']:.2f}")

    if sheet_path.is_file():
        lines = [x.strip() for x in sheet_path.read_text(encoding="utf-8").splitlines() if x.strip()]
        sheet_dates = [_norm_date(x) for x in lines]
        trading = [_norm_date(d) for d in df.index]
        ser_set = set(ser_dates)
        sheet_set = set(sheet_dates)
        print()
        print(f"Spreadsheet date list: {len(sheet_dates)} rows")
        print(f"META trading days:     {len(trading)}")
        print(f"Sheet list == all trading days (from 1st sheet date): {sheet_dates == trading[trading.index(sheet_dates[0]):][: len(sheet_dates)] if sheet_dates else False}")
        print(f"Engine activations in sheet list: {len(ser_set & sheet_set)} / {len(ser_set)}")
        print(f"Sheet dates NOT in engine activations: {len(sheet_set - ser_set)}")
        print(f"Engine activations NOT in sheet list: {len(ser_set - sheet_set)}")
        if sheet_set - ser_set:
            extra = sorted(sheet_set - ser_set)[:10]
            print(f"  Sample sheet-only dates: {extra}")
        if ser_set - sheet_set:
            print(f"  Sample engine-only dates: {sorted(ser_set - sheet_set)[:10]}")
    else:
        print()
        print(f"No sheet date file at {sheet_path}")
        print("Save spreadsheet maturity dates (one per line) and re-run:")
        print(f"  python tools/compare_meta_yh_zones.py {sheet_path}")

    # Serial queue loss estimate: parallel - serial
    par_only = set(par_dates) - set(ser_dates)
    print()
    print(f"Activations in parallel but NOT serial (filtered by queue): {len(par_only)}")
    if par_only:
        print(f"  Sample: {sorted(par_only)[:15]}")


if __name__ == "__main__":
    main()
