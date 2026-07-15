#!/usr/bin/env python3
"""Compare PBR engine output to spreadsheet ground truth (zones + trades)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "stock_analysis"))
sys.path.insert(0, str(REPO / "tools"))

import pandas as pd
from pbr_compare_filter import SHEET_COMPARE_MIN_DATE, filter_pbr_output_for_compare
from pbr_sheet_ground_truth import load_pbr_ground_truth
from pbr_zones import compute_pbr_touch_stream

DATA = REPO / "data" / "newdata" / "data"


def _ymd(ts: pd.Timestamp) -> str:
    return ts.strftime("%Y%m%d")


def _match_zone(engine_ev: dict, sheet_row) -> bool:
    return (
        abs(engine_ev["zone_lower"] - sheet_row.zone_lower) < 0.02
        and abs(engine_ev["zone_upper"] - sheet_row.zone_upper) < 0.02
    )


def _find_engine_zone(events: list[dict], sheet_row) -> dict | None:
    for ev in events:
        if _match_zone(ev, sheet_row):
            return ev
    pivot = sheet_row.pivot_date
    for ev in events:
        pm = ev.get("pivot_monday", "").replace("-", "")
        if pm == pivot and _match_zone(ev, sheet_row):
            return ev
    return None


def _date_field(ev: dict, key: str) -> str:
    v = ev.get(key) or ""
    return v.replace("-", "") if v else ""


def compare_symbol(
    sym: str, gt, *, band_pct: float, breakout_confirmation: float, min_date: str,
) -> dict:
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
    events = out["pbr_zone_events"]
    sheet_zones = [z for z in gt.zones if z.create_breakout_record]

    stats = {
        "zone_bounds": 0,
        "breakout_date": 0,
        "breakout_expected": 0,
        "conf_date": 0,
        "conf_expected": 0,
        "next_week_start": 0,
        "next_week_expected": 0,
        "retest_date": 0,
        "retest_expected": 0,
        "rocket_buy_date": 0,
        "rocket_expected": 0,
        "sheet_zones": len(sheet_zones),
        "engine_zones": len(events),
        "missing_pivot": [],
        "mismatches": [],
    }

    for sz in sheet_zones:
        ev = _find_engine_zone(events, sz)
        if not ev:
            stats["missing_pivot"].append(sz.pivot_date)
            continue
        stats["zone_bounds"] += 1

        def chk(sheet_d: str | None, eng_key: str, counter: str, expected_key: str) -> None:
            if not sheet_d:
                return
            stats[expected_key] += 1
            eng_d = _date_field(ev, eng_key)
            if eng_d == sheet_d:
                stats[counter] += 1
            else:
                stats["mismatches"].append(
                    f"pivot {sz.pivot_date} {counter}: sheet={sheet_d} engine={eng_d or '—'}"
                )

        chk(sz.breakout_date, "breakout_monday", "breakout_date", "breakout_expected")
        chk(sz.conf_date, "conf_monday", "conf_date", "conf_expected")
        chk(sz.next_week_start, "next_week_start", "next_week_start", "next_week_expected")
        if sz.retest_date:
            stats["retest_expected"] += 1
            rb = ev.get("retest_bar", -1)
            eng_d = _ymd(df.index[rb]) if rb is not None and rb >= 0 else ""
            if eng_d == sz.retest_date:
                stats["retest_date"] += 1
            else:
                stats["mismatches"].append(
                    f"pivot {sz.pivot_date} retest_date: sheet={sz.retest_date} engine={eng_d or '—'}"
                )
        if sz.rocket_buy_date:
            stats["rocket_expected"] += 1
            sb = ev.get("entry_signal_bar", -1)
            eng_d = _ymd(df.index[sb]) if sb is not None and sb >= 0 else ""
            if eng_d == sz.rocket_buy_date:
                stats["rocket_buy_date"] += 1
            else:
                stats["mismatches"].append(
                    f"pivot {sz.pivot_date} rocket_buy: sheet={sz.rocket_buy_date} engine={eng_d or '—'}"
                )

    # Trades: entry date = fill (next day open after signal)
    fills = sorted(_ymd(df.index[b]) for b in out.get("pbr_entry_fill_bars") or [])
    trade_hits = 0
    trade_miss: list[str] = []
    for tr in gt.trades:
        if tr.entry_date in fills:
            trade_hits += 1
        else:
            trade_miss.append(tr.entry_date)

    stats["trade_fills"] = trade_hits
    stats["trade_total"] = len(gt.trades)
    stats["trade_miss"] = trade_miss
    stats["engine_fills"] = fills
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description="PBR parity vs spreadsheet ground truth")
    ap.add_argument("symbols", nargs="*", default=["AAPL", "AMZN", "META", "MSFT"])
    ap.add_argument("--paste", type=Path, default=None)
    ap.add_argument("--band-pct", type=float, default=0.015)
    ap.add_argument("--breakout-confirmation", type=float, default=0.03)
    ap.add_argument(
        "--min-date",
        default=SHEET_COMPARE_MIN_DATE,
        help="Ignore engine zones/entries before this date when comparing (default: spreadsheet start).",
    )
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    gt_all = load_pbr_ground_truth(args.paste)
    exit_code = 0

    for sym in args.symbols:
        sym = sym.upper()
        if sym not in gt_all:
            print(f"{sym}: not in ground truth paste — skip")
            continue
        st = compare_symbol(
            sym, gt_all[sym],
            band_pct=args.band_pct,
            breakout_confirmation=args.breakout_confirmation,
            min_date=args.min_date,
        )
        sz = st["sheet_zones"]
        print(
            f"\n{sym}: sheet zones={sz} engine zones={st['engine_zones']} "
            f"(since {args.min_date}) missing pivot match={len(st['missing_pivot'])}"
        )
        print(
            f"  bounds {st['zone_bounds']}/{sz}  "
            f"BO {st['breakout_date']}/{st['breakout_expected']}  "
            f"conf {st['conf_date']}/{st['conf_expected']}  "
            f"next_wk {st['next_week_start']}/{st['next_week_expected']}  "
            f"retest {st['retest_date']}/{st['retest_expected']}  "
            f"rocket {st['rocket_buy_date']}/{st['rocket_expected']}"
        )
        print(f"  trades fill {st['trade_fills']}/{st['trade_total']}")
        if st["missing_pivot"]:
            print(f"  missing pivots (first 10): {st['missing_pivot'][:10]}")
        if args.verbose or st["mismatches"]:
            for mm in st["mismatches"][:25]:
                print(f"  MISMATCH {mm}")
            if len(st["mismatches"]) > 25:
                print(f"  ... {len(st['mismatches']) - 25} more mismatches")
        if st["trade_miss"]:
            print(f"  trade misses: {st['trade_miss']}")
            print(f"  engine fills: {st['engine_fills']}")
        if st["zone_bounds"] < sz or st["trade_fills"] < st["trade_total"]:
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
