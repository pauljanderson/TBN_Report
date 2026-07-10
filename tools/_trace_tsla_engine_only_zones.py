#!/usr/bin/env python3
"""Why engine has 239.28 and 20.87 zones but sheet ladder omits them."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stock_analysis"))
from rocket_brt import _round_zone_price, compute_sheet_brt_touch_stream  # noqa: E402

df = pd.read_csv(ROOT / "data/newdata/data/TSLA.csv", parse_dates=["Date"], index_col="Date")
r = compute_sheet_brt_touch_stream(df, band_pct=0.0154, touch_pullback_pct=0.108, maturity_lag=7)

targets = {
    "20.87": ("2018-05-10", "2018-05-21"),
    "239.28": ("2021-03-10", "2021-03-19"),
    "291.31": ("2021-03-04", "2021-03-15"),  # sheet only (needs H patch)
    "231.67": ("2020-12-18", "2020-12-30"),
    "233.33": ("2021-07-14", "2021-07-23"),
    "237.40": ("2022-10-27", "2022-11-07"),
}

print("=== Engine matured events for key TSLA zones ===")
for e in r["brt_matured_zone_events"]:
    zc = round(e["zone_center"], 2)
    for label in targets:
        if abs(zc - float(label)) < 0.02:
            pb, mb = e["pivot_bar"], e["maturity_bar"]
            print(
                f"  {zc}: pivot {df.index[pb].date()} H={df['High'].iloc[pb]:.4f} "
                f"-> mature {df.index[mb].date()}"
            )

# Gate trace for 239.28 pivot 2021-03-10
print("\n=== Gate trace 2021-03-10 (239.28 pivot) ===")
t = df.index.get_loc(pd.Timestamp("2021-03-10"))
hi = df["High"].values
lo = df["Low"].values
w0, w1 = max(0, t - 4), min(len(hi), t + 5)
is_lh = hi[t] >= hi[w0:w1].max() - 1e-6
post = lo[t + 1 : t + 8].min()
drop = post / hi[t] - 1
pre_lo = lo[max(0, t - 7) : t].min()
pre = hi[t] / pre_lo - 1
touch_pb = 1 - post / hi[t]
print(
    f"  LH={is_lh} post6%={drop:.3f} pre8.1%={pre:.3f} "
    f"touch10.8%={touch_pb:.3f} RHigh={_round_zone_price(hi[t], 2)}"
)

# Gate trace 2018-05-10 (20.87)
print("\n=== Gate trace 2018-05-10 (20.87 pivot) ===")
t2 = df.index.get_loc(pd.Timestamp("2018-05-10"))
is_lh2 = hi[t2] >= hi[max(0, t2 - 4) : t2 + 5].max() - 1e-6
post2 = lo[t2 + 1 : t2 + 8].min()
drop2 = post2 / hi[t2] - 1
pre_lo2 = lo[max(0, t2 - 7) : t2].min()
pre2 = hi[t2] / pre_lo2 - 1
touch_pb2 = 1 - post2 / hi[t2]
print(
    f"  LH={is_lh2} post6%={drop2:.3f} pre8.1%={pre2:.3f} "
    f"touch10.8%={touch_pb2:.3f} RHigh={_round_zone_price(hi[t2], 2)}"
)

# Ladder context from sheet file
sheet_path = ROOT / "tools/tsla_brt_sheet_zones.txt"
lines = [ln.strip().split("\t") for ln in sheet_path.read_text().splitlines() if ln.strip()]
print("\n=== Sheet ladder around 231-300-291-260 ===")
for i, parts in enumerate(lines):
    ctr = float(parts[0])
    if 19 <= ctr <= 25 or 228 <= ctr <= 300:
        print(f"  row {i+1}: {parts[0]}/{parts[1]}/{parts[2]}")

# On 4/13/2021 BO: which zones are matured and crossed?
print("\n=== Zones matured before 2021-04-13 (BO date) ===")
bo = pd.Timestamp("2021-04-13")
for e in r["brt_matured_zone_events"]:
    mb = e["maturity_bar"]
    if df.index[mb] > bo:
        continue
    zc = round(e["zone_center"], 2)
    zl, zh = round(e["zone_lower"], 2), round(e["zone_upper"], 2)
    if zc >= 200:
        print(f"  mature {df.index[mb].date()}  {zc}  bands {zl}/{zh}")
