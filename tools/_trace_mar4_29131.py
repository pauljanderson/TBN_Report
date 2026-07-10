#!/usr/bin/env python3
"""Verify sheet claim: 3/4/2021 pivot High=291.31 produces matured zone on 3/15."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stock_analysis"))
from rocket_brt import _round_zone_price, compute_sheet_brt_touch_stream  # noqa: E402

df = pd.read_csv(ROOT / "data/newdata/data/TSLA.csv", parse_dates=["Date"], index_col="Date")

# Sheet GF Feb 3 (matches Yahoo)
feb3 = pd.Timestamp("2021-02-03")
print("Feb 3 Yahoo:", df.loc[feb3, ["Open", "High", "Low", "Close"]].to_dict())
print("Feb 3 Sheet: O=292.34 H=292.69 L=284.35 C=284.9")

mar4 = pd.Timestamp("2021-03-04")
mar15 = pd.Timestamp("2021-03-15")
print("\nMar 4 Yahoo:", df.loc[mar4, ["Open", "High", "Low", "Close"]].to_dict())
print("Mar 4 Sheet: O=218.60 H=291.31 L=200 C=207.15  (H is sheet pivot value, not Yahoo OHLC)")

# Patch only Mar 4 High to sheet pivot high 291.31
df_patch = df.copy()
df_patch.at[mar4, "High"] = 291.31

hi = df_patch["High"].values
lo = df_patch["Low"].values
dates = df_patch.index
t = dates.get_loc(mar4)

w0 = max(0, t - 4)
w1 = min(len(hi), t + 5)
is_lh = hi[t] >= hi[w0:w1].max() - 1e-6
post = lo[t + 1 : t + 8].min()
drop = post / hi[t] - 1
pre_lo = lo[max(0, t - 7) : t].min()
pre = hi[t] / pre_lo - 1
touch_pb = 1 - post / hi[t]
rh = _round_zone_price(hi[t], 2)

print("\n=== Gates on 3/4/2021 with patched High=291.31 ===")
print(f"  RHigh={rh}  LH={is_lh}  post6%={drop:.3f}  pre8.1%={pre:.3f}  touch10.8%={touch_pb:.3f}")
print(f"  post6 pass={drop <= -0.06}  pre pass={pre >= 0.081}  touch pass={touch_pb >= 0.108}")

# Show window highs around 3/4
print("\n  Highs in ±4 window:")
for j in range(w0, w1):
    print(f"    {dates[j].date()}  H={hi[j]:.2f}")

r = compute_sheet_brt_touch_stream(
    df_patch, band_pct=0.0154, touch_pullback_pct=0.108, maturity_lag=7
)
tp = r["touch_price"]
print(f"\nEngine touch at 3/4: {tp.loc[mar4]}")
print(f"Engine matured at 3/15: {r['matured_now'].loc[mar15]}")
if r["matured_now"].loc[mar15]:
    p = dates.get_loc(mar15) - 7
    print(
        f"  zone {_round_zone_price(tp.iloc[p],2)} / "
        f"{_round_zone_price(tp.iloc[p]*0.9846,2)} / "
        f"{_round_zone_price(tp.iloc[p]*1.0154,2)}"
    )

zones = [
    (round(e["zone_center"], 2), round(e["zone_lower"], 2), round(e["zone_upper"], 2))
    for e in r["brt_matured_zone_events"]
]
hit = [z for z in zones if abs(z[0] - 291.31) < 0.01]
print(f"\n291.31 zone in patched engine: {hit}")

# Does Feb 3 alone produce touch with relaxed threshold?
print("\n=== Feb 3 touch gate sensitivity ===")
t2 = dates.get_loc(feb3)
h2 = 292.69
post2 = lo[t2 + 1 : t2 + 8].min()
touch_pb2 = 1 - post2 / h2
print(f"  touch pullback = {touch_pb2:.4f}  (need 0.108)")

# Could 291.31 be ROUND(Feb3_high * factor)?
for factor in [0.995, 0.9953, 0.99528, 1 - 0.00472]:
    v = _round_zone_price(292.69 * factor, 2)
    print(f"  292.69 * {factor:.5f} -> {v}")
