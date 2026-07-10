#!/usr/bin/env python3
"""Trace sheet 291.31 zone: maturity on 3/15/2021 row, pivot 7 bars earlier."""
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

MATURITY = pd.Timestamp("2021-03-15")
if MATURITY not in df.index:
    raise SystemExit(f"{MATURITY.date()} not in data")

mb = df.index.get_loc(MATURITY)
pb = mb - 7
print(f"Maturity bar: {MATURITY.date()} (index {mb})")
print(f"Pivot bar (-7): {df.index[pb].date()} (index {pb})")
pivot_row = df.iloc[pb]
print(
    f"  O={pivot_row['Open']:.4f} H={pivot_row['High']:.4f} "
    f"L={pivot_row['Low']:.4f} C={pivot_row['Close']:.4f}"
)
print(f"  Rounded High: {_round_zone_price(float(pivot_row['High']), 2)}")

r = compute_sheet_brt_touch_stream(df, band_pct=0.0154, touch_pullback_pct=0.108, maturity_lag=7)
tp = r["touch_price"]
zc = r["zone_center"]
zl = r["zone_low"]
zh = r["zone_high"]

print(f"\nEngine at pivot bar {df.index[pb].date()}:")
print(f"  touch_price={tp.iloc[pb]}  zone={zc.iloc[pb]}/{zl.iloc[pb]}/{zh.iloc[pb]}")

print(f"\nEngine at maturity bar {MATURITY.date()}:")
print(f"  matured_now={r['matured_now'].iloc[mb]}")
print(f"  touch 7 back={tp.iloc[pb]}  zone={zc.iloc[pb]}/{zl.iloc[pb]}/{zh.iloc[pb]}")

# All touch events Jan-Apr 2021
print("\n=== Touch events Jan-Apr 2021 ===")
for t in range(len(df)):
    d = df.index[t]
    if d < pd.Timestamp("2021-01-01") or d > pd.Timestamp("2021-04-30"):
        continue
    v = tp.iloc[t]
    if pd.notna(v):
        mb2 = t + 7
        md = df.index[mb2].date() if mb2 < len(df) else "?"
        print(
            f"  touch {d.date()} tp={v:.2f} H={df['High'].iloc[t]:.4f} "
            f"zl/zh={zl.iloc[t]:.2f}/{zh.iloc[t]:.2f} mature~{md}"
        )

# Matured events in that window
print("\n=== Matured zone events Jan-Apr 2021 ===")
for e in r["brt_matured_zone_events"]:
    mb3 = e["maturity_bar"]
    d = df.index[mb3]
    if d < pd.Timestamp("2021-01-01") or d > pd.Timestamp("2021-04-30"):
        continue
    pb3 = e["pivot_bar"]
    print(
        f"  mature {d.date()} zone {e['zone_center']:.2f}/"
        f"{e['zone_lower']:.2f}/{e['zone_upper']:.2f} "
        f"pivot {df.index[pb3].date()} H={df['High'].iloc[pb3]:.4f}"
    )

# Search any bar rounding to 291.31
print("\n=== Any bar with RHigh=291.31 ===")
for t, (d, row) in enumerate(df.iterrows()):
    h = float(row["High"])
    if abs(_round_zone_price(h, 2) - 291.31) < 1e-9:
        print(f"  {d.date()} H={h:.6f}")

# Pivot chain on 3/4/2021 (7 bars before 3/15)
print("\n=== Pivot gates on pivot bar (7 before 3/15) ===")
hi = df["High"].values
lo = df["Low"].values
t = pb
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
    f"  LH={is_lh} post6%={drop:.3f} pre8.1%={pre:.3f} "
    f"touch10.8%={touch_pb:.3f} RHigh={_round_zone_price(hi[t], 2)}"
)

# What date would need touch 291.31 to mature on 3/15?
print("\n=== If touch=291.31 matures 3/15, pivot is 7 bars back =", df.index[pb].date())
