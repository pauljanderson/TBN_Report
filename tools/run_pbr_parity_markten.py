#!/usr/bin/env python3
"""Compare PBR zone/BO/entry output to TOS reference tables (tos/gen_*_ts.py)."""
from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "stock_analysis"))
sys.path.insert(0, str(REPO / "tools"))

import pandas as pd
from pbr_compare_filter import SHEET_COMPARE_MIN_DATE, filter_pbr_output_for_compare
from pbr_zones import compute_pbr_touch_stream

MARKTEN = ["AMZN", "AMD", "AU", "GOOGL", "META", "TSLA"]
DATA = REPO / "data" / "newdata" / "data"
TOS = REPO / "tos"


def load_ref(sym: str) -> tuple[list[tuple], list[int], list[int]]:
    path = TOS / f"gen_{sym.lower()}_ts.py"
    if not path.is_file():
        raise FileNotFoundError(path)
    text = path.read_text(encoding="utf-8")
    zones = [
        (int(p), float(lo), float(hi), int(bo))
        for p, lo, hi, bo in re.findall(r"\((\d+),\s*([\d.]+),\s*([\d.]+),\s*(\d+)\)", text)
    ]
    em = re.search(r"entries\s*=\s*\[(.*?)\]", text, re.S)
    entries = [int(x.strip()) for x in em.group(1).split(",") if x.strip().isdigit()] if em else []
    xm = re.search(r"exits\s*=\s*\[(.*?)\]", text, re.S)
    exits = [int(x.strip()) for x in xm.group(1).split(",") if x.strip().isdigit()] if xm else []
    return zones, entries, exits


def run_pbr(sym: str, *, band_pct: float, breakout_confirmation: float, min_date: str) -> tuple[dict, pd.DataFrame]:
    df = pd.read_csv(DATA / f"{sym}.csv", index_col=0, parse_dates=True)
    out = filter_pbr_output_for_compare(
        compute_pbr_touch_stream(
            df,
            band_pct=band_pct,
            strong_pre_pivot_bars=3,
            strong_pre_pivot_pct=0.10,
            strong_post_pivot_bars=3,
            strong_post_pivot_pct=0.10,
            strong_pivot_mode="either",
            breakout_confirmation=breakout_confirmation,
            max_days_after_retest=2,
            zone_price_round_decimals=2,
        ),
        df,
        min_date=min_date,
    )
    return out, df


def main() -> int:
    ap = argparse.ArgumentParser(description="PBR parity vs TOS gen_*_ts reference")
    ap.add_argument("symbols", nargs="*", default=MARKTEN)
    ap.add_argument("--band-pct", type=float, default=0.015)
    ap.add_argument("--breakout-confirmation", type=float, default=0.03,
                    help="Weekly close > zone_upper * (1+this). Default 3%%.")
    ap.add_argument("--ref-bo-zero", action="store_true",
                    help="Compare BO dates with 0%% confirmation (legacy ref tables)")
    ap.add_argument(
        "--min-date",
        default=SHEET_COMPARE_MIN_DATE,
        help="Ignore engine zones/entries before this date when comparing.",
    )
    args = ap.parse_args()

    bc = 0.0 if args.ref_bo_zero else args.breakout_confirmation
    total_zone_match = 0
    total_zone_ref = 0
    total_bo_match = 0
    total_entry_match = 0
    total_entry_ref = 0

    for sym in args.symbols:
        sym = sym.upper()
        try:
            ref_z, ref_e, _ref_x = load_ref(sym)
        except FileNotFoundError:
            print(f"{sym}: no reference gen_*_ts.py — skip")
            continue
        out, df = run_pbr(sym, band_pct=args.band_pct, breakout_confirmation=bc, min_date=args.min_date)
        pbr_map = {ev["pivot_monday"].replace("-", ""): ev for ev in out["pbr_zone_events"]}

        zone_ok = 0
        bo_ok = 0
        for pivot, lo, hi, bo in ref_z:
            ev = pbr_map.get(str(pivot))
            if not ev:
                print(f"  {sym} MISS pivot {pivot}")
                continue
            bounds_ok = abs(ev["zone_lower"] - lo) < 0.02 and abs(ev["zone_upper"] - hi) < 0.02
            bo_date = ev["breakout_monday"].replace("-", "") if ev["breakout_monday"] else ""
            if bo == 0:
                bo_match = True  # cloud-only in reference — no BO marker required
            else:
                bo_match = str(bo) == bo_date
            if bounds_ok:
                zone_ok += 1
            if bo_match:
                bo_ok += 1
            if not (bounds_ok and bo_match):
                print(
                    f"  {sym} pivot {pivot} bounds={'OK' if bounds_ok else 'DIFF'} "
                    f"ref=({lo},{hi}) pbr=({ev['zone_lower']},{ev['zone_upper']}) "
                    f"bo ref={bo} pbr={bo_date}"
                )

        signals = sorted(int(df.index[b].strftime("%Y%m%d")) for b in out.get("pbr_entry_signal_bars") or [])
        fills = sorted(int(df.index[b].strftime("%Y%m%d")) for b in out.get("pbr_entry_fill_bars") or [])
        entry_hit = [e for e in ref_e if e in fills]
        entry_near = [e for e in ref_e if e in fills or e in signals]

        print(
            f"{sym}: zones {zone_ok}/{len(ref_z)} BO {bo_ok}/{len(ref_z)} "
            f"entries {len(entry_hit)}/{len(ref_e)} fill dates "
            f"(pbr zones since {args.min_date}: {len(out['pbr_zone_events'])}, bc={bc})"
        )
        if entry_hit != ref_e:
            print(f"  ref entries (fill dates) {ref_e}")
            print(f"  pbr fill dates {fills}")
            if entry_near != ref_e:
                print(f"  pbr signal dates {signals}")

        total_zone_match += zone_ok
        total_zone_ref += len(ref_z)
        total_bo_match += bo_ok
        total_entry_ref += len(ref_e)
        total_entry_match += len(entry_hit)

    print(
        f"\nTOTAL zones {total_zone_match}/{total_zone_ref} "
        f"BO {total_bo_match}/{total_zone_ref} entries {total_entry_match}/{total_entry_ref} "
        f"(bc={bc})"
    )
    return 0 if total_zone_match == total_zone_ref and total_bo_match == total_zone_ref else 1


if __name__ == "__main__":
    raise SystemExit(main())
