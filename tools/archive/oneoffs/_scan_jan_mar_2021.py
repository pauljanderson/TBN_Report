#!/usr/bin/env python3
"""Scan Jan-Mar 2021 for near-miss 291.31 touch candidates."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stock_analysis"))
from rocket_brt import _round_zone_price  # noqa: E402

df = pd.read_csv(ROOT / "data/newdata/data/TSLA.csv", parse_dates=["Date"], index_col="Date")
hi = df["High"].values
lo = df["Low"].values
dates = df.index

print("Days passing post6+pre8, sorted by touch pullback gap to 10.8%:")
rows = []
for t in range(len(df)):
    d = dates[t]
    if d < pd.Timestamp("2021-01-20") or d > pd.Timestamp("2021-03-20"):
        continue
    w0 = max(0, t - 4)
    w1 = min(len(hi), t + 5)
    is_lh = hi[t] >= hi[w0:w1].max() - 1e-6
    if t + 7 >= len(hi):
        continue
    post = lo[t + 1 : t + 8].min()
    drop = post / hi[t] - 1
    pre_lo = lo[max(0, t - 7) : t].min()
    pre = hi[t] / pre_lo - 1
    touch_pb = 1 - post / hi[t]
    rh = _round_zone_price(hi[t], 2)
    if drop <= -0.06 and pre >= 0.081:
        gap = 0.108 - touch_pb
        rows.append((gap, d, rh, is_lh, drop, pre, touch_pb, hi[t]))

rows.sort(key=lambda x: abs(x[0]))
for gap, d, rh, is_lh, drop, pre, touch_pb, raw_h in rows[:15]:
    zl = _round_zone_price(291.31 * 0.9846, 2)
    match = "MATCH" if abs(rh - 291.31) < 0.01 else ""
    near = "NEAR-291" if abs(rh - 291.31) < 1.5 else ""
    print(
        f"{d.date()} RHigh={rh} LH={is_lh} touch={touch_pb:.4f} gap={gap:+.4f} "
        f"rawH={raw_h:.4f} {near} {match}"
    )

print("\nIf touch uses RHigh=292.69 but ladder stores 291.31 - band mismatch:")
rh = 292.69
print(f"  bands from 292.69: {_round_zone_price(rh*0.9846,2)}/{_round_zone_price(rh*1.0154,2)}")
