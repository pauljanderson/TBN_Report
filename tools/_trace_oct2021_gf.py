#!/usr/bin/env python3
"""Trace Oct 2021 TSLA pivot chain with user GF OHLC vs Yahoo."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stock_analysis"))
from rocket_brt import _round_zone_price, compute_sheet_brt_touch_stream  # noqa: E402

DATA = ROOT / "data" / "newdata" / "data" / "TSLA.csv"
df = pd.read_csv(DATA, parse_dates=["Date"], index_col="Date")

gf = pd.DataFrame(
    {
        "Open": [262.55, 266.98, 270.16, 271.83, 274.58, 283.93, 292.51, 288.45, 285.33, 298.50],
        "High": [267.08, 270.77, 271.80, 273.42, 281.07, 291.75, 292.65, 289.83, 300.00, 303.33],
        "Low": [261.83, 265.52, 268.59, 271.12, 274.12, 283.82, 287.50, 285.79, 285.17, 296.99],
        "Close": [263.98, 268.57, 270.36, 272.77, 281.01, 290.04, 288.09, 288.60, 298.00, 303.23],
    },
    index=pd.to_datetime(
        [
            "2021-10-11",
            "2021-10-12",
            "2021-10-13",
            "2021-10-14",
            "2021-10-15",
            "2021-10-18",
            "2021-10-19",
            "2021-10-20",
            "2021-10-21",
            "2021-10-22",
        ]
    ),
)

df2 = df.copy()
for d, row in gf.iterrows():
    if d in df2.index:
        for c in ["Open", "High", "Low", "Close"]:
            df2.at[d, c] = row[c]

d = pd.Timestamp("2021-10-18")
print("=== Yahoo vs GF Oct 18 ===")
print("Yahoo", {k: float(df.loc[d, k]) for k in ["High", "Low", "Close"]})
print("GF   ", {k: float(gf.loc[d, k]) for k in ["High", "Low", "Close"]})
print("Rounded High Yahoo", _round_zone_price(float(df.loc[d, "High"]), 2))
print("Rounded High GF   ", _round_zone_price(float(gf.loc[d, "High"]), 2))

# High values that round to 291.31
hits = [h for h in np.linspace(291.0, 292.0, 2000) if abs(_round_zone_price(h, 2) - 291.31) < 1e-9]
if hits:
    print(f"High range -> touch 291.31: {hits[0]:.6f} .. {hits[-1]:.6f}")
else:
    print("No high in [291,292] rounds to 291.31")

for label, dfx in [("yahoo", df), ("gf_patch", df2)]:
    r = compute_sheet_brt_touch_stream(dfx, band_pct=0.0154, touch_pullback_pct=0.108, maturity_lag=7)
    zones = [
        (round(e["zone_center"], 2), round(e["zone_lower"], 2), round(e["zone_upper"], 2))
        for e in r["brt_matured_zone_events"]
    ]
    near = [z for z in zones if abs(z[0] - 291.31) < 0.01 or abs(z[0] - 291.85) < 0.01]
    print(f"\n{label}: zones near 291: {near}")

print("\n=== Manual pivot trace (GF patch, Oct 11-22) ===")
hi = df2["High"].values
lo = df2["Low"].values
dates = df2.index
idx = {d: i for i, d in enumerate(dates)}
for d in gf.index:
    t = idx[d]
    w0 = max(0, t - 4)
    w1 = min(len(hi), t + 5)
    is_lh = hi[t] >= hi[w0:w1].max() - 1e-6
    post = lo[t + 1 : t + 8].min() if t + 7 < len(hi) else np.nan
    drop = (post / hi[t] - 1) if t + 7 < len(hi) else np.nan
    pre_lo = lo[max(0, t - 7) : t].min()
    pre = (hi[t] / pre_lo - 1) if pre_lo > 0 else np.nan
    touch_fwd = lo[t + 1 : t + 8].min() if t + 7 < len(hi) else np.nan
    touch_pb = (1 - touch_fwd / hi[t]) if t + 7 < len(hi) else np.nan
    print(
        f"{d.date()} H={hi[t]:.2f} LH={is_lh} post6%={drop:.3f} "
        f"pre8.1%={pre:.3f} touch10.8%={touch_pb:.3f} RHigh={_round_zone_price(hi[t], 2)}"
    )

# Search entire history for any bar whose rounded high = 291.31
print("\n=== Bars with rounded High = 291.31 (Yahoo) ===")
for i, (d, row) in enumerate(df.iterrows()):
    if abs(_round_zone_price(float(row["High"]), 2) - 291.31) < 1e-9:
        print(f"  {d.date()} raw High={float(row['High']):.6f}")

# Reverse: what touch produces bands 286.82/295.80?
tp = 291.31
print(f"\nBands from touch {tp}: {_round_zone_price(tp*0.9846,2)} / {_round_zone_price(tp*1.0154,2)}")

# Engine events near 291
print("\n=== Engine matured events near 291 ===")
r = compute_sheet_brt_touch_stream(df, band_pct=0.0154, touch_pullback_pct=0.108, maturity_lag=7)
for e in r["brt_matured_zone_events"]:
    zc = round(e["zone_center"], 2)
    if abs(zc - 291.85) < 0.02 or abs(zc - 291.31) < 0.02:
        pb = e["pivot_bar"]
        mb = e["maturity_bar"]
        print(
            f"zone {zc} pivot {df.index[pb].date()} H={df['High'].iloc[pb]:.4f} "
            f"mature {df.index[mb].date()}"
        )

# Sep-Oct 2021: any bar with raw high in [291.305, 291.315)?
print("\n=== Sep-Dec 2021 bars with raw High rounding to 291.31 ===")
sub = df[(df.index >= "2021-09-01") & (df.index <= "2021-12-31")]
for d, row in sub.iterrows():
    h = float(row["High"])
    if abs(_round_zone_price(h, 2) - 291.31) < 1e-9:
        print(f"  {d.date()} High={h:.6f}")

# All touch events 290-293
print("\n=== Full touch stream events with tp 290-293 ===")
r = compute_sheet_brt_touch_stream(df, band_pct=0.0154, touch_pullback_pct=0.108, maturity_lag=7)
tp = r["touch_price"]
for t in range(len(df)):
    v = tp.iloc[t]
    if pd.notna(v) and 290 <= v <= 293:
        d = df.index[t].date()
        h = float(df["High"].iloc[t])
        mb = t + 7
        md = df.index[mb].date() if mb < len(df) else "?"
        print(f"  TOUCH {d} tp={v:.2f} H={h:.4f} mature~{md}")
