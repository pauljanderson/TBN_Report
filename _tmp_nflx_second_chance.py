#!/usr/bin/env python3
"""Prove NFLX orphans = second-chance re-arm of already-traded WPBR zones."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
sys.path.insert(0, str(REPO / "stock_analysis"))
import rocket_brt as rb  # noqa: E402
from wpbr_zones import find_wpbr_retest_and_signal  # noqa: E402

DATA = REPO / "data" / "newdata" / "data" / "NFLX.csv"


def bd(idx, b):
    if b is None or int(b) < 0:
        return None
    return pd.Timestamp(idx[int(b)]).strftime("%Y-%m-%d")


def main():
    df = pd.read_csv(DATA, index_col=0, parse_dates=True).sort_index()
    idx = df.index
    lo = df["Low"].to_numpy(float)
    cl = df["Close"].to_numpy(float)
    op = df["Open"].to_numpy(float)

    print("=== A) Zone 16.44-16.94 second-chance resume after 2018-01-05 exit ===")
    # After first WIN exit 2018-01-05, resume next bar
    start = int(np.searchsorted(idx.values, np.datetime64("2018-01-08")))
    rt, sig, fill = find_wpbr_retest_and_signal(
        lo, cl, op, scan_start=start, zone_lower=16.44, zone_upper=16.94,
        max_days_after_retest=2, n=len(df), retest_mode="stop_looking",
    )
    print(f"  resume 2018-01-08: retest={bd(idx,rt)} signal={bd(idx,sig)} fill={bd(idx,fill)}")
    # Did abandon kill happen? Find first Close < 16.44 on/after start before May 12
    kill = None
    for i in range(start, len(df)):
        if cl[i] < 16.44 - 1e-9:
            kill = bd(idx, i)
            break
        if pd.Timestamp(idx[i]) >= pd.Timestamp("2022-05-13"):
            break
    print(f"  first Close<16.44 after resume (before orphan): {kill}")

    print("\n=== B) Zone 34.45-35.50 second-chance resume after 2023-06-14 exit ===")
    start2 = int(np.searchsorted(idx.values, np.datetime64("2023-06-15")))
    rt, sig, fill = find_wpbr_retest_and_signal(
        lo, cl, op, scan_start=start2, zone_lower=34.45, zone_upper=35.50,
        max_days_after_retest=2, n=len(df), retest_mode="stop_looking",
    )
    print(f"  resume 2023-06-15: retest={bd(idx,rt)} signal={bd(idx,sig)} fill={bd(idx,fill)}")
    kill2 = None
    for i in range(start2, len(df)):
        if cl[i] < 34.45 - 1e-9:
            kill2 = bd(idx, i)
            break
        if pd.Timestamp(idx[i]) >= pd.Timestamp("2023-10-17"):
            break
    print(f"  first Close<34.45 after resume (before orphan): {kill2}")

    print("\n=== C) Engine run NFLX with wpbr_second_chance_after_win=True ===")
    cfg = rb.BRTConfig(
        wpbr_zones=True,
        brt_zones=False,
        yh_zones=False,
        vec_zones=False,
        band_pct=0.015,
        strong_pre_pivot_bars=3,
        strong_pre_pivot_pct=0.10,
        strong_post_pivot_bars=3,
        strong_post_pivot_pct=0.10,
        strong_pivot_mode="either",
        wpbr_breakout_confirmation=0.03,
        wpbr_max_days_after_retest=2,
        wpbr_retest_mode="stop_looking",
        wpbr_second_chance_after_win=True,
        growth_filter_enabled=False,
        min_spy_compare_1y_at_trigger=-1000.0,
        ind_score_weights_path="",
        too_high_multiplier=0.0,
        target_pct=1.22,
        stop_pct=0.89,
        stop_pct_is_multiplier=True,
        entry_start_date="2016-01-01",
        use_indicators=False,
        indicator_buy="off",
        zone_price_round_decimals=2,
        max_market_cap=0,
    )
    # Apply variant C round bounds if available
    if hasattr(rb, "_round_bounds"):
        pass
    closed, open_tr, *_rest = rb.run_brt_backtest("NFLX", df, cfg)
    # closed may be list of trades or dataframe
    entries = []
    if isinstance(closed, pd.DataFrame):
        for _, r in closed.iterrows():
            entries.append(
                (
                    str(r.get("DATE_OPENED") or r.get("date_opened") or ""),
                    float(r.get("ENTRY_PRICE") or r.get("entry_price") or 0),
                    str(r.get("DATE_CLOSED") or r.get("date_closed") or ""),
                    str(r.get("WPBR_ZONE_ID") or r.get("wpbr_zone_id") or ""),
                )
            )
    else:
        for t in closed:
            d_o = getattr(t, "date_opened", None) or getattr(t, "DATE_OPENED", None)
            d_c = getattr(t, "date_closed", None) or getattr(t, "DATE_CLOSED", None)
            if hasattr(d_o, "strftime"):
                d_o = d_o.strftime("%Y-%m-%d")
            if hasattr(d_c, "strftime"):
                d_c = d_c.strftime("%Y-%m-%d")
            entries.append(
                (
                    str(d_o),
                    float(getattr(t, "entry_price", 0) or 0),
                    str(d_c),
                    str(getattr(t, "wpbr_zone_id", "") or ""),
                )
            )

    print(f"  closed count={len(entries)}")
    for e in entries:
        mark = ""
        if e[0].replace("-", "") in ("20220513", "20231016") or "2022-05-13" in e[0] or "2023-10-16" in e[0]:
            mark = "  <== ORPHAN"
        # normalize dates
        try:
            eo = pd.Timestamp(str(int(float(e[0]))) if str(e[0]).isdigit() or (str(e[0]).replace(".0","").isdigit()) else e[0]).strftime("%Y-%m-%d")
        except Exception:
            try:
                eo = pd.Timestamp(e[0]).strftime("%Y-%m-%d")
            except Exception:
                eo = str(e[0])
        print(f"  {eo} @ {e[1]:.2f} -> {e[2]} zone={e[3]}{mark}")

    orphan_hits = []
    for e in entries:
        try:
            eo = pd.Timestamp(str(int(float(e[0]))) if str(e[0]).replace(".0", "").isdigit() else e[0]).strftime("%Y-%m-%d")
        except Exception:
            eo = str(e[0])[:10]
        if eo in ("2022-05-13", "2023-10-16"):
            orphan_hits.append((eo, e[1], e[3]))
    print(f"\n  ORPHAN HITS with second_chance=True: {orphan_hits}")

    print("\n=== D) Control: same run with second_chance=False ===")
    cfg.wpbr_second_chance_after_win = False
    closed2, *_ = rb.run_brt_backtest("NFLX", df, cfg)
    entries2 = []
    src = closed2 if not isinstance(closed2, pd.DataFrame) else [closed2.iloc[i] for i in range(len(closed2))]
    if isinstance(closed2, pd.DataFrame):
        for _, r in closed2.iterrows():
            d = r.get("DATE_OPENED") or r.get("date_opened")
            try:
                d = pd.Timestamp(str(int(float(d))) if str(d).replace(".0","").isdigit() else d).strftime("%Y-%m-%d")
            except Exception:
                d = str(d)
            entries2.append(d)
    else:
        for t in closed2:
            d = getattr(t, "date_opened", None)
            if hasattr(d, "strftime"):
                d = d.strftime("%Y-%m-%d")
            else:
                try:
                    d = pd.Timestamp(str(int(float(d))) if str(d).replace(".0","").isdigit() else d).strftime("%Y-%m-%d")
                except Exception:
                    d = str(d)
            entries2.append(d)
    print(f"  closed count={len(entries2)}")
    print(f"  has 2022-05-13? {('2022-05-13' in entries2)}")
    print(f"  has 2023-10-16? {('2023-10-16' in entries2)}")


if __name__ == "__main__":
    main()
