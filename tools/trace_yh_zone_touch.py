#!/usr/bin/env python3
"""Trace YH zone touch price at a specific activation date."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stock_analysis"))

from rocket_brt import compute_yh_touch_stream, _effective_yh_memory_mode  # noqa: E402


def load(sym: str) -> pd.DataFrame:
    df = pd.read_csv(ROOT / "data" / "newdata" / "data" / f"{sym}.csv", parse_dates=["Date"])
    return df.sort_values("Date").set_index("Date")


def trace(sym: str, act_date: str, sheet_ctr: float) -> None:
    df = load(sym)
    dates = df.index
    act = pd.Timestamp(act_date)
    if act not in dates:
        print(f"{sym}: {act_date} not in CSV")
        return

    level3 = compute_yh_touch_stream(
        df,
        band_pct=0.015,
        lookback_long=756,
        touch_threshold=5,
        zone_price_round_decimals=2,
        yh_lookback=252,
        yh_move_away_pct=0.03,
        yh_memory_mode="sheet",
        debug_symbol=sym,
    )
    events = level3.get("yh_zone_events") or []
    t = dates.get_loc(act)
    print(f"\n{'='*72}")
    print(f"{sym} activation {act_date}  bar_index={t}  excel_row={t+2}")
    print(f"Sheet center ~ ${sheet_ctr:.2f}")
    print(f"{'='*72}")

    match = [e for e in events if dates[int(e["activation_bar"])] == act]
    if match:
        e = match[0]
        print("Engine event:", e)
    else:
        print("No engine activation on this date")

    # Window OHLC
    w = df.loc[act - pd.Timedelta(days=40): act + pd.Timedelta(days=3)]
    print("\nOHLC window (last 40d before act):")
    for dt, r in w.iterrows():
        i = dates.get_loc(dt)
        mark = " <-- ACT" if dt == act else ""
        print(
            f"  i={i:4d} excel={i+2:4d} {dt.date()} "
            f"O={r['Open']:.4f} H={r['High']:.4f} L={r['Low']:.4f} C={r['Close']:.4f}{mark}"
        )

    # Manual replay of sheet-mode YH state machine
    hi_raw = df["High"].to_numpy(dtype=np.float64)
    hi = np.round(hi_raw, 2)
    yh_lb = 252
    move_pct = 0.03
    working = None
    print("\nReplay (sheet mode, rounded High, 252 lookback):")
    start_i = max(yh_lb, t - 80)
    for i in range(start_i, t + 1):
        activated = False
        if working is not None:
            yh_bar, yh_p, act_p = working
            if hi[i] >= act_p:
                mark = " *** ACTIVATE" if i == t else " ACTIVATE"
                print(
                    f"  i={i:4d} {dates[i].date()} hi={hi[i]:.2f} >= act={act_p:.2f} "
                    f"(yh_bar={yh_bar} excel={yh_bar+2} yh_p={yh_p:.2f}){mark}"
                )
                activated = True
                working = None
        prev_max = float(np.max(hi[i - yh_lb : i])) if i >= yh_lb else -1
        if i >= yh_lb and hi[i] > prev_max:
            yh_p = round(float(hi[i]), 2)
            act_p = round(yh_p * 1.03, 2)
            note = ""
            if working is not None and not activated:
                note = " (DROP: working pending)"
            elif activated:
                note = " -> new working"
            elif working is None:
                note = " -> new working"
            print(
                f"  i={i:4d} {dates[i].date()} NEW_YH hi={hi[i]:.2f} prev252max={prev_max:.2f} "
                f"cand={yh_p:.2f} act>={act_p:.2f}{note}"
            )
            if activated:
                working = [i, yh_p, act_p]
            elif working is None:
                working = [i, yh_p, act_p]

    # What high at yh_bar from engine export?
    for e in events:
        ab = int(e["activation_bar"])
        yb = int(e["yh_bar"])
        if dates[ab] == act or abs(e["zone_center"] - sheet_ctr) < 0.2:
            print(
                f"\nNearby event: act={dates[ab].date()} yh_bar={yb} excel={yb+2} "
                f"date={dates[yb].date()} raw_H={hi_raw[yb]:.4f} rnd_H={hi[yb]:.2f} "
                f"center={e['zone_center']:.2f}"
            )


def main() -> None:
    trace("AAPL", "2018-02-27", 43.81)
    trace("NVDA", "2021-11-22", 32.76)


if __name__ == "__main__":
    main()
