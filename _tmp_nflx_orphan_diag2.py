#!/usr/bin/env python3
"""Deeper NFLX orphan forensics: May-12 as re-arm rocket; Oct re-entry; BRT vs WPBR."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
sys.path.insert(0, str(REPO / "stock_analysis"))
from wpbr_zones import compute_wpbr_touch_stream, find_wpbr_retest_and_signal  # noqa: E402

DATA = REPO / "data" / "newdata" / "data" / "NFLX.csv"
ZONES = REPO / "drive" / "wpbr_sheet_reconcile" / "NFLX" / "zones.tsv"
STAMP = REPO / "drive" / "wpbr_sheet_reconcile" / "_markten_variantC_2016_20260722134127"
CLOSED = STAMP / "WPBR_Closed_260722134152.csv"
# Prefer a zones dump if present under stamp or proxy
PROXY = REPO / "drive" / "wpbr_sheet_reconcile" / "_markten_start2019_20260722125713"


def nd(s):
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None
    s = str(s).strip().replace("$", "").replace(",", "")
    if s in {"", "#N/A", "None", "#DIV/0!", "nan", "NaT"}:
        return None
    try:
        return pd.Timestamp(s).strftime("%Y-%m-%d")
    except Exception:
        return None


def nf(s):
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None
    s = str(s).replace("$", "").replace(",", "").strip()
    if s in {"", "#N/A", "None", "#DIV/0!", "nan"}:
        return None
    try:
        return float(s)
    except Exception:
        return None


def main():
    df = pd.read_csv(DATA, index_col=0, parse_dates=True).sort_index()
    idx = df.index
    lo = df["Low"].to_numpy(float)
    cl = df["Close"].to_numpy(float)
    op = df["Open"].to_numpy(float)

    print("=== 1) May 12 2022 vs zone 16.44-16.94 (2017 pivot already rocketed) ===")
    d = pd.Timestamp("2022-05-12")
    r = df.loc[d]
    zl, zh = 16.44, 16.94
    print(f"OHLC {d.date()}: O={r.Open} H={r.High} L={r.Low} C={r.Close}")
    print(f"retest core Low<=zh & C>zh: {float(r.Low)<=zh and float(r.Close)>zh}")
    print(f"rocket green C>O & C>zh: {float(r.Close)>float(r.Open) and float(r.Close)>zh}")
    print(f"next open fill 2022-05-13: {df.loc[pd.Timestamp('2022-05-13')].Open}")

    print("\n=== 2) Scan ALL sheet zones: would 2022-05-12 be a valid rocket bar? ===")
    zdf = pd.read_csv(ZONES, sep="\t", dtype=str)
    for _, zr in zdf.iterrows():
        zl = nf(zr["Zone Lower"])
        zh = nf(zr["Zone Upper"])
        if zl is None or zh is None:
            continue
        if float(r.Low) <= zh + 1e-9 and float(r.Close) > zh + 1e-9 and float(r.Close) > float(r.Open):
            print(
                f"  YES piv={nd(zr['Pivot Date'])} {zl}-{zh} "
                f"bo={nd(zr['Breakout Date'])} retest={nd(zr['Daily Retest Date'])} "
                f"rocket={nd(zr['Rocket Buy Date'])} conf={nd(zr['Conf Week Date'])} next={nd(zr['Next week start date'])}"
            )

    print("\n=== 3) Same for 2023-10-13 (Fri before orphan Mon entry) and 2023-10-12 ===")
    for ds in ("2023-10-12", "2023-10-13"):
        rr = df.loc[pd.Timestamp(ds)]
        print(f"\n{ds}: O={rr.Open} H={rr.High} L={rr.Low} C={rr.Close} green={float(rr.Close)>float(rr.Open)}")
        for _, zr in zdf.iterrows():
            zl = nf(zr["Zone Lower"])
            zh = nf(zr["Zone Upper"])
            if zl is None or zh is None:
                continue
            if float(rr.Low) <= zh + 1e-9 and float(rr.Close) > zh + 1e-9 and float(rr.Close) > float(rr.Open):
                print(
                    f"  rocket-capable piv={nd(zr['Pivot Date'])} {zl}-{zh} "
                    f"retest={nd(zr['Daily Retest Date'])} rocket={nd(zr['Rocket Buy Date'])}"
                )

    print("\n=== 4) Live WPBR opportunities with fills in 2022-04..2022-08 and 2023-09..2023-12 ===")
    out = compute_wpbr_touch_stream(
        df,
        band_pct=0.015,
        strong_pre_pivot_bars=3,
        strong_pre_pivot_pct=0.10,
        strong_post_pivot_bars=3,
        strong_post_pivot_pct=0.10,
        strong_pivot_mode="either",
        breakout_confirmation=0.03,
        max_days_after_retest=2,
        retest_mode="stop_looking",
        zone_price_round_decimals=2,
    )
    for opp in out.get("wpbr_entry_opportunities") or []:
        fb = opp.get("entry_fill_bar")
        sb = opp.get("entry_signal_bar")
        rb = opp.get("retest_bar")
        if fb is None or int(fb) < 0:
            continue
        fd = pd.Timestamp(idx[int(fb)]).strftime("%Y-%m-%d")
        if not (
            ("2022-04-01" <= fd <= "2022-08-01")
            or ("2023-09-01" <= fd <= "2023-12-01")
        ):
            continue
        sd = pd.Timestamp(idx[int(sb)]).strftime("%Y-%m-%d") if sb is not None and int(sb) >= 0 else None
        rd = pd.Timestamp(idx[int(rb)]).strftime("%Y-%m-%d") if rb is not None and int(rb) >= 0 else None
        print(
            f"  fill={fd} signal={sd} retest={rd} "
            f"zl={opp['zone_lower']:.2f}-{opp['zone_upper']:.2f} id={opp.get('wpbr_zone_id')}"
        )

    print("\n=== 5) Force re-scan zone 16.44-16.94 from 2022-05-01 (as if not retired) ===")
    # Find bar index for 2022-05-01
    start = int(np.searchsorted(idx.values, np.datetime64("2022-05-01")))
    rt, sig, fill = find_wpbr_retest_and_signal(
        lo, cl, op, scan_start=start, zone_lower=16.44, zone_upper=16.94,
        max_days_after_retest=2, n=len(df), retest_mode="stop_looking",
    )
    def bd(b):
        return None if b is None else pd.Timestamp(idx[int(b)]).strftime("%Y-%m-%d")
    print(f"  from 2022-05-01: retest={bd(rt)} signal={bd(sig)} fill={bd(fill)}")

    # Also from next_week after a hypothetical re-confirm — try scan from 2022-01-01
    start2 = int(np.searchsorted(idx.values, np.datetime64("2022-01-01")))
    rt, sig, fill = find_wpbr_retest_and_signal(
        lo, cl, op, scan_start=start2, zone_lower=16.44, zone_upper=16.94,
        max_days_after_retest=2, n=len(df), retest_mode="stop_looking",
    )
    print(f"  from 2022-01-01: retest={bd(rt)} signal={bd(sig)} fill={bd(fill)}")

    print("\n=== 6) Zone 34.45-35.50 (May 2023 rocket) — second chance after win? ===")
    # Sheet had May win then Aug loss then Oct orphan. Engine May win then Aug then no Oct.
    # If sheet allowed 2nd purchase after WIN on 34.45 zone:
    start3 = int(np.searchsorted(idx.values, np.datetime64("2023-06-15")))  # after May exit
    rt, sig, fill = find_wpbr_retest_and_signal(
        lo, cl, op, scan_start=start3, zone_lower=34.45, zone_upper=35.50,
        max_days_after_retest=2, n=len(df), retest_mode="stop_looking",
    )
    print(f"  re-scan 34.45-35.50 from 2023-06-15: retest={bd(rt)} signal={bd(sig)} fill={bd(fill)}")
    # Also check Oct 13 specifically
    for ds in ("2023-10-12", "2023-10-13", "2023-10-16"):
        rr = df.loc[pd.Timestamp(ds)]
        touch = float(rr.Low) <= 35.50 and float(rr.High) >= 34.45
        print(
            f"  {ds}: O={rr.Open:.3f} L={rr.Low:.3f} H={rr.High:.3f} C={rr.Close:.3f} "
            f"overlap_band={touch} C>zh={float(rr.Close)>35.50} green={float(rr.Close)>float(rr.Open)}"
        )

    print("\n=== 7) Zone 39.05-40.24 after Aug trade stop — second chance after LOSS? ===")
    start4 = int(np.searchsorted(idx.values, np.datetime64("2023-10-14")))
    rt, sig, fill = find_wpbr_retest_and_signal(
        lo, cl, op, scan_start=start4, zone_lower=39.05, zone_upper=40.24,
        max_days_after_retest=2, n=len(df), retest_mode="stop_looking",
    )
    print(f"  re-scan 39.05-40.24 from 2023-10-14: retest={bd(rt)} signal={bd(sig)} fill={bd(fill)}")

    print("\n=== 8) What price action on 2023-10-13 could look like a rocket for ep=35.62 fill? ===")
    # Entry at open means signal was prior session. Prior = 2023-10-13.
    prev = df.loc[pd.Timestamp("2023-10-13")]
    print(f"signal candidate 10/13: O={prev.Open} H={prev.High} L={prev.Low} C={prev.Close}")
    print(f"green={float(prev.Close)>float(prev.Open)}")
    # Which zh would Close clear?
    for _, zr in zdf.iterrows():
        zh = nf(zr["Zone Upper"])
        zl = nf(zr["Zone Lower"])
        if zh is None:
            continue
        if float(prev.Close) > zh and float(prev.Low) <= zh:
            print(
                f"  Low<=zh<C: piv={nd(zr['Pivot Date'])} {zl}-{zh} "
                f"rocket_col={nd(zr['Rocket Buy Date'])} retest_col={nd(zr['Daily Retest Date'])}"
            )

    print("\n=== 9) Engine closed full NFLX list ===")
    cl = pd.read_csv(CLOSED, dtype=str)
    cl = cl[cl["SYMBOL"].str.upper() == "NFLX"]
    for _, r in cl.iterrows():
        print(
            f"  {nd(r['DATE_OPENED'])} -> {nd(r['DATE_CLOSED'])} "
            f"@ {r['ENTRY_PRICE']} {r.get('EXIT_TYPE')} {r.get('PNL_PCT')} "
            f"zone={r.get('WPBR_ZONE_ID','')}"
        )

    print("\n=== 10) Check proxy WPBR_ZONES for HAS_TRADE / ENTRY on crash-era zones ===")
    for p in sorted(PROXY.glob("WPBR_ZONES_NFLX_*.csv"))[:1]:
        print(f"file {p.name}")
        ez = pd.read_csv(p, dtype=str)
        for _, r in ez.iterrows():
            piv = nd(r.get("PIVOT_MONDAY") or r.get("DATE"))
            zl = nf(r.get("ZONE_LOW"))
            zh = nf(r.get("ZONE_HIGH"))
            if piv and piv in ("2017-06-05", "2017-10-16", "2022-06-06", "2023-04-03", "2022-03-28", "2022-04-01"):
                print(
                    dict(
                        piv=piv,
                        zl=zl,
                        zh=zh,
                        retest=r.get("RETEST_BAR"),
                        sig=r.get("ENTRY_SIGNAL_BAR"),
                        fill=r.get("ENTRY_FILL_BAR"),
                        has=r.get("HAS_TRADE"),
                        bo=r.get("BREAKOUT_MONDAY"),
                    )
                )
        # also any with fill bars near orphans
        for _, r in ez.iterrows():
            fb = r.get("ENTRY_FILL_BAR")
            try:
                fbi = int(float(fb))
            except Exception:
                continue
            if fbi < 0:
                continue
            fd = pd.Timestamp(idx[fbi]).strftime("%Y-%m-%d")
            if fd in ("2022-05-13", "2023-10-16") or abs((pd.Timestamp(fd) - pd.Timestamp("2022-05-13")).days) < 3:
                print("NEAR ORPHAN FILL ROW", r.to_dict())


if __name__ == "__main__":
    main()
