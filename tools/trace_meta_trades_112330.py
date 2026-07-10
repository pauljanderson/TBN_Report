#!/usr/bin/env python3
"""Trace META engine trades vs sheet log for run 260619112330."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stock_analysis"))

from rocket_brt import (  # noqa: E402
    BRTConfig,
    _cfg_min_spy_compare_1y_at_trigger,
    _rs_excess_pct_points,
    _spy_compare_1y_at_trigger_gate_blocks,
)

RUN_ID = "260619112330"

SHEET_TRADES = [
    ("2019-01-04", 137.56, "2019-01-31", 166.45, 21.00, 27, "WIN"),
    ("2019-02-04", 169.15, "2019-07-12", 204.67, 21.00, 158, "WIN"),
    ("2019-09-09", 187.44, "2019-10-02", 173.58, -7.39, 23, "LOSS"),
    ("2019-10-21", 190.00, "2020-03-09", 169.60, -10.74, 140, "LOSS"),
    ("2020-03-18", 146.62, "2020-04-14", 178.98, 22.07, 27, "WIN"),
    ("2020-04-22", 184.08, "2020-05-20", 223.50, 21.41, 28, "WIN"),
    ("2020-06-29", 220.59, "2020-08-07", 266.91, 21.00, 39, "WIN"),
    ("2020-09-21", 253.31, "2021-04-05", 306.51, 21.00, 196, "WIN"),
    ("2021-05-19", 313.58, "2021-08-30", 379.43, 21.00, 103, "WIN"),
    ("2021-10-12", 326.97, "2022-01-24", 296.42, -9.34, 104, "LOSS"),
    ("2022-03-22", 213.33, "2022-04-21", 196.31, -7.98, 30, "LOSS"),
    ("2022-05-19", 194.97, "2022-05-24", 177.09, -9.17, 5, "LOSS"),
    ("2022-06-06", 191.93, "2022-06-10", 175.97, -8.32, 4, "LOSS"),
    ("2023-03-08", 186.35, "2023-04-27", 239.89, 28.73, 50, "WIN"),
    ("2023-06-05", 270.14, "2023-10-11", 326.87, 21.00, 128, "WIN"),
    ("2023-12-04", 318.98, "2024-01-22", 387.95, 21.62, 49, "WIN"),
    ("2024-08-05", 479.00, "2024-10-01", 579.59, 21.00, 57, "WIN"),
    ("2024-11-29", 577.50, "2025-01-30", 698.78, 21.00, 62, "WIN"),
    ("2025-02-28", 673.68, "2025-03-10", 600.19, -10.91, 10, "LOSS"),
    ("2025-03-14", 607.46, "2025-03-31", 555.52, -8.55, 17, "LOSS"),
    ("2025-04-07", 543.25, "2025-05-13", 657.33, 21.00, 36, "WIN"),
    ("2025-05-30", 644.39, "2025-07-31", 779.71, 21.00, 62, "WIN"),
    ("2025-08-26", 752.30, "2025-10-06", 698.58, -7.14, 41, "LOSS"),
    ("2025-10-13", 707.78, "2025-10-30", 660.94, -6.62, 17, "LOSS"),
    ("2026-02-05", 665.49, "2026-03-13", 610.37, -8.28, 36, "LOSS"),
]


def _parse_mdy(s: str) -> str:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    s = str(s).strip()
    if not s:
        return ""
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    dt = pd.to_datetime(s, errors="coerce")
    return "" if pd.isna(dt) else dt.strftime("%Y-%m-%d")


def _load_eng() -> pd.DataFrame:
    p = ROOT / "Drive" / f"YH_Closed_{RUN_ID}.csv"
    eng = pd.read_csv(p)
    eng = eng[eng["SYMBOL"] == "META"].copy()
    eng["open_d"] = pd.to_datetime(eng["DATE_OPENED"].astype(str), format="%Y%m%d")
    eng["close_d"] = pd.to_datetime(eng["DATE_CLOSED"].astype(str), format="%Y%m%d")
    return eng


def _load_retest() -> pd.DataFrame:
    p = ROOT / "Drive" / f"YH_breakout_and_retest_{RUN_ID}.csv"
    rt = pd.read_csv(p)
    rt = rt[rt["SYMBOL"] == "META"].copy()
    rt["rt_iso"] = rt["Retest Date"].map(_parse_mdy)
    rt["bo_iso"] = rt["Breakout Date"].map(_parse_mdy)
    return rt


def _load_ohlc() -> pd.DataFrame:
    df = pd.read_csv(ROOT / "data" / "newdata" / "data" / "META.csv", parse_dates=["Date"])
    return df.sort_values("Date")


def _next_bar(iso_list: list[str], d: str) -> str:
    key = d.replace("-", "")
    if key not in iso_list:
        return ""
    i = iso_list.index(key)
    return iso_list[i + 1] if i + 1 < len(iso_list) else ""


def main() -> None:
    eng = _load_eng()
    rt = _load_retest()
    ohlc = _load_ohlc()
    iso = [d.strftime("%Y%m%d") for d in ohlc["Date"]]
    iso_d = [d.strftime("%Y-%m-%d") for d in ohlc["Date"]]

    cfg = BRTConfig(
        growth_filter_enabled=True,
        growth_bars=756,
        min_spy_compare_1y_at_trigger=50.0,
    )
    spy = pd.read_csv(ROOT / "data" / "newdata" / "data" / "SPY.csv", parse_dates=["Date"]).sort_values("Date")
    spy_cl = spy.set_index("Date")["Close"]

    print("=" * 110)
    print(f"META trade trace — sheet (25) vs engine ({len(eng)}) — run {RUN_ID}")
    print("=" * 110)

    matched_eng_idx: set[int] = set()

    for se, sp, sx, xp, pp, days, res in SHEET_TRADES:
        se_dt = pd.Timestamp(se)
        print(f"\n## SHEET {se}  entry ${sp:.2f}  exit {sx} ${xp:.2f}  {res} {pp:+.1f}%")

        # retest rows on sheet entry day
        rt_hits = rt[rt["rt_iso"] == se]
        if len(rt_hits):
            for _, r in rt_hits.head(2).iterrows():
                print(f"   retest ledger: BO {r['bo_iso']}  Z{r['Zone Lower']}-{r['Zone Upper']}  MR {r['Main Row']}")
        else:
            near = rt[rt["rt_iso"] != ""].copy()
            near["dd"] = (pd.to_datetime(near["rt_iso"]) - se_dt).dt.days.abs()
            n = near.sort_values("dd").iloc[0] if len(near) else None
            if n is not None and int(n["dd"]) <= 5:
                print(f"   retest ledger: nearest RT {n['rt_iso']} ({int(n['dd'])}d)  BO {n['bo_iso']}")
            else:
                print(f"   retest ledger: no RT on {se}")

        nb = _next_bar(iso, se.replace("-", ""))
        nb_fmt = f"{nb[:4]}-{nb[4:6]}-{nb[6:8]}" if nb else ""
        print(f"   engine entry model: next bar after retest = {nb_fmt or 'n/a'}")

        # nearest engine trade
        best = None
        for idx, r in eng.iterrows():
            delta = abs((r["open_d"] - se_dt).days)
            if best is None or delta < best[0]:
                best = (delta, idx, r)
        if best and best[0] <= 10:
            _, idx, r = best
            matched_eng_idx.add(idx)
            ed = (r["open_d"] - se_dt).days
            xd = (r["close_d"] - pd.Timestamp(sx)).days
            ep = abs(float(r["ENTRY_PRICE"]) - sp)
            print(
                f"   ENGINE MATCH: open {r['open_d'].date()} ${float(r['ENTRY_PRICE']):.2f}  "
                f"-> {r['close_d'].date()} {r['EXIT_TYPE']} {float(r['PNL_PCT'].replace('%','')):+.1f}%  "
                f"(entry {ed:+d}d vs sheet, exit {xd:+d}d, price d${ep:.2f})"
            )
            if ed == 1:
                print("   WHY entry +1d: engine fills on bar AFTER retest signal (not same-day D)")
            elif ed > 1:
                print(f"   WHY entry +{ed}d: likely SPY gate / meteoric / portfolio / no slot on earlier bars")
            if xd != 0:
                print(f"   WHY exit {xd:+d}d: gap stop/target vs close-based sheet exit")
        else:
            print(f"   ENGINE: no trade within 10d (nearest {best[0] if best else '?'}d)")

    print("\n" + "=" * 110)
    print(f"ENGINE-ONLY trades ({len(eng) - len(matched_eng_idx)})")
    print("=" * 110)
    for idx, r in eng.iterrows():
        if idx in matched_eng_idx:
            continue
        od = r["open_d"].strftime("%Y-%m-%d")
        rt_on = rt[rt["rt_iso"] == od]
        prev = (r["open_d"] - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        rt_prev = rt[rt["rt_iso"] == prev]
        print(
            f"\n  {od}  ${float(r['ENTRY_PRICE']):.2f} -> {r['close_d'].date()}  "
            f"{r['EXIT_TYPE']} {float(r['PNL_PCT'].replace('%','')):+.1f}%"
        )
        if len(rt_on):
            print(f"    retest on entry day: yes ({len(rt_on)} rows)")
        elif len(rt_prev):
            print(f"    retest prev day {prev}: yes -> next-bar entry")
        else:
            print(f"    retest on entry/prev: no — check non-retest path or delayed fill")

    # Summary buckets
    print("\n" + "=" * 110)
    print("SUMMARY")
    print("=" * 110)
    entry_deltas = []
    for se, sp, *_ in SHEET_TRADES:
        se_dt = pd.Timestamp(se)
        best = min(((abs((r["open_d"] - se_dt).days), r) for _, r in eng.iterrows()), default=(999, None))
        if best[0] <= 10 and best[1] is not None:
            entry_deltas.append((best[1]["open_d"] - se_dt).days)
    from collections import Counter
    c = Counter(entry_deltas)
    print(f"Entry offset (engine open - sheet entry) for matched: {dict(sorted(c.items()))}")
    print(f"Sheet trades with engine match within 10d: {len(entry_deltas)}/25")
    print(f"Engine-only extra trades: {len(eng) - len(matched_eng_idx)}")


if __name__ == "__main__":
    main()
