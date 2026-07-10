#!/usr/bin/env python3
"""Gate trace for early-2021 candidates that might produce touch ~291.31."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stock_analysis"))
from rocket_brt import _round_zone_price  # noqa: E402

df = pd.read_csv(ROOT / "data/newdata/data/TSLA.csv", parse_dates=["Date"], index_col="Date")
hi = df["High"].values
lo = df["Low"].values
dates = df.index

candidates = [
    "2021-01-27",
    "2021-02-02",
    "2021-02-03",
    "2021-02-08",
    "2021-02-09",
]

print("Gate trace (engine rules):")
for ds in candidates:
    t = dates.get_loc(pd.Timestamp(ds))
    w0 = max(0, t - 4)
    w1 = min(len(hi), t + 5)
    is_lh = hi[t] >= hi[w0:w1].max() - 1e-6
    post = lo[t + 1 : t + 8].min() if t + 7 < len(hi) else np.nan
    drop = (post / hi[t] - 1) if t + 7 < len(hi) else np.nan
    pre_lo = lo[max(0, t - 7) : t].min()
    pre = (hi[t] / pre_lo - 1) if pre_lo > 0 else np.nan
    touch_fwd = lo[t + 1 : t + 8].min() if t + 7 < len(hi) else np.nan
    touch_pb = (1 - touch_fwd / hi[t]) if t + 7 < len(hi) else np.nan
    rh = _round_zone_price(hi[t], 2)
    mb = dates[t + 7] if t + 7 < len(dates) else None
    ok = is_lh and drop <= -0.06 and pre >= 0.081 and touch_pb >= 0.108
    print(
        f"\n{ds} H={hi[t]:.4f} RHigh={rh} mature~{mb.date() if mb is not None else '?'}"
    )
    print(
        f"  LH={is_lh} post6%={drop:.3f} pre8.1%={pre:.3f} "
        f"touch10.8%={touch_pb:.3f} ALL={ok}"
    )
    if abs(rh - 291.31) < 0.05 or abs(rh - 292.69) < 0.05:
        zl = _round_zone_price(rh * 0.9846, 2)
        zh = _round_zone_price(rh * 1.0154, 2)
        print(f"  bands from RHigh: {zl}/{zh}")

# If Feb 3 High were 291.31, would gates pass?
print("\n=== Hypothetical Feb 3 High=291.31 ===")
t = dates.get_loc(pd.Timestamp("2021-02-03"))
h = 291.31
lo_t = lo[t]
w0 = max(0, t - 4)
w1 = min(len(hi), t + 5)
# use hypothetical high at t
hi_hyp = hi.copy()
hi_hyp[t] = h
is_lh = h >= hi_hyp[w0:w1].max() - 1e-6
post = lo[t + 1 : t + 8].min()
drop = post / h - 1
pre_lo = lo[max(0, t - 7) : t].min()
pre = h / pre_lo - 1
touch_pb = 1 - post / h
print(f"  LH={is_lh} post6%={drop:.3f} pre8.1%={pre:.3f} touch10.8%={touch_pb:.3f}")
print(f"  mature~{dates[t+7].date()}")

# Which row has matured = INDEX(AB,ROW()-7) pointing to touch 291.31 if touch on Feb 3?
touch_date = pd.Timestamp("2021-02-03")
maturity_date = dates[dates.get_loc(touch_date) + 7]
print(f"\nIf touch forms {touch_date.date()}, matures {maturity_date.date()}")

touch_date2 = pd.Timestamp("2021-02-02")
maturity_date2 = dates[dates.get_loc(touch_date2) + 7]
print(f"If touch forms {touch_date2.date()}, matures {maturity_date2.date()}")
