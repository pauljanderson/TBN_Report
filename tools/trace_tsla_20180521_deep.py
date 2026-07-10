#!/usr/bin/env python3
"""Deep trace: Final PH + Touch gates for TSLA Apr-Jun 2018."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stock_analysis"))

from rocket_brt import (  # noqa: E402
    _sheet_price_near,
    _round_zone_price,
    compute_sheet_brt_touch_stream,
)

DATA = ROOT / "data" / "newdata" / "data" / "TSLA.csv"
PIVOT_LOCAL = 4
POST_BARS = 7
PRE_BARS = 7
PRE_PCT = 0.081
TOUCH_PB = 0.108
FUTURE_DROP = 0.06
DEDUP = 0.01
WARMUP = 9


def main() -> int:
    df = pd.read_csv(DATA, parse_dates=["Date"], index_col="Date")
    hi = np.asarray(df["High"].values, dtype=np.float64)
    lo = np.asarray(df["Low"].values, dtype=np.float64)
    n = len(df)

    def local_hi(t: int) -> bool:
        w0 = max(0, t - PIVOT_LOCAL)
        w1 = min(n, t + PIVOT_LOCAL + 1)
        return bool(np.isclose(hi[t], np.max(hi[w0:w1]), rtol=0.0, atol=1e-6))

    def post_drop(t: int) -> bool:
        if t + POST_BARS >= n:
            return False
        fut_min = float(np.min(lo[t + 1 : t + POST_BARS + 1]))
        return (fut_min / hi[t] - 1.0) <= -FUTURE_DROP

    def touch_px(t: int) -> float:
        return _round_zone_price(float(hi[t]), 2)

    final_ph = np.zeros(n, dtype=bool)
    ph_px = np.full(n, np.nan)

    for t in range(n):
        if t < WARMUP:
            continue
        dup = False
        for j in range(max(0, t - PIVOT_LOCAL), t):
            if final_ph[j] and _sheet_price_near(float(ph_px[j]), touch_px(t), DEDUP):
                dup = True
                break
        if local_hi(t) and post_drop(t) and not dup:
            final_ph[t] = True
            ph_px[t] = touch_px(t)

    print("=== Final Pivot High bars 2018-01 .. 2018-07 ===")
    for d in df.loc["2018-01-01":"2018-07-31"].index:
        t = df.index.get_loc(d)
        if not final_ph[t]:
            continue
        pre_lo = float(np.min(lo[max(0, t - PRE_BARS) : t]))
        rise = (hi[t] / pre_lo - 1) * 100 if pre_lo > 0 else 0
        fut_min = float(np.min(lo[t + 1 : t + POST_BARS + 1]))
        pb = (1 - fut_min / hi[t]) * 100
        pre_ok = rise >= PRE_PCT * 100
        pb_ok = pb >= TOUCH_PB * 100
        tp = touch_px(t) if pre_ok and pb_ok else None
        print(
            f"  {d.date()} bar={t} H={hi[t]:.4f} PH={ph_px[t]:.2f}  "
            f"pre_rise={rise:.2f}%({'Y' if pre_ok else 'N'})  "
            f"pullback={pb:.2f}%({'Y' if pb_ok else 'N'})  "
            f"TP={'%.2f' % tp if tp else '-'}"
        )

    print("\n=== Why 2018-05-10 fails gates (step by step) ===")
    t = df.index.get_loc(pd.Timestamp("2018-05-10"))
    print(f"  local_hi={local_hi(t)}  post_drop(6%)={post_drop(t)}")
    for j in range(max(0, t - PIVOT_LOCAL), t):
        if final_ph[j]:
            near = _sheet_price_near(float(ph_px[j]), touch_px(t), DEDUP)
            print(f"  prior PH {df.index[j].date()} px={ph_px[j]:.2f} dup_near={near}")

    r = compute_sheet_brt_touch_stream(df, band_pct=0.0154, touch_pullback_pct=TOUCH_PB, maturity_lag=7)
    print("\n=== Sheet ladder positions ===")
    print("  Sheet #6: 25.97 (2017-09-27)")
    print("  Sheet #7: 24.92 (engine 2018-06-27) — sheet SKIPS 20.87")
    print("  Engine extra: 20.87 mature 2018-05-21")

    # Hypothesis: dup with 2018-04-09 if sheet uses unrounded high?
    print("\n=== Dup check variants for 2018-05-10 ===")
    h = hi[t]
    for dname in ("2018-04-09", "2018-05-07", "2018-05-08"):
        j = df.index.get_loc(pd.Timestamp(dname))
        for tol in (0.01, 0.015, 0.02, 0.03):
            if _sheet_price_near(float(hi[j]), touch_px(t), tol):
                print(f"  near {dname} H={hi[j]:.4f} tol={tol*100:.1f}%")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
