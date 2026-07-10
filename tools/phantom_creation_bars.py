#!/usr/bin/env python3
"""Show engine phantom zone CREATION bars (maturity bar - lag) with OHLC context."""
import sys
from dataclasses import asdict
from pathlib import Path
import numpy as np

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb

base = asdict(rb.BRTConfig())
base.update(rb.mts_sheet_parity_overrides())
cfg = rb.BRTConfig(**base)
df = rb.load_csv(str(_REPO / "data" / "newdata" / "data" / "NVDA.csv"))
ph, pl, php, plp = rb.compute_pivots(
    df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
    realtime_filter_enabled=cfg.realtime_filter_enabled,
)
l3 = rb.build_level3_for_cfg(df, cfg, ph, pl, php, plp)
n = len(df)
iso = [str(x).replace("-", "")[:8] for x in df.index]
o, h, l, c = [df[x].to_numpy(float) for x in "Open High Low Close".split()]
tp = l3["touch_price"].to_numpy(float)
zl = l3["zone_low"].to_numpy(float)
zh = l3["zone_high"].to_numpy(float)
origin = l3["zone_touch_origin"].to_numpy(int)

# phantom maturity rows (sheet-row space) from diff_maturity_rows.py
phantom_mat_rows = [37, 285, 759, 867, 1067, 1079, 1115, 1311, 1457, 1492,
                    1716, 1768, 2096, 2169, 2337, 2346]
lag = 7
print("creation_date  matbar  pivbar  origin  TouchPx  zone_lo-zone_hi   (O/H/L/C at pivot bar)")
for mr in phantom_mat_rows:
    matbar = mr - 2
    pivbar = matbar - lag
    d = iso[pivbar]
    dd = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    org = {0: "none", 1: "PH-high", 2: "PL-low"}.get(int(origin[pivbar]), "?")
    print(
        f"{dd}   {matbar:5d}  {pivbar:5d}  {org:7s} {tp[pivbar]:8.3f}  "
        f"{zl[pivbar]:.2f}-{zh[pivbar]:.2f}   "
        f"O{o[pivbar]:.2f}/H{h[pivbar]:.2f}/L{l[pivbar]:.2f}/C{c[pivbar]:.2f}"
    )
