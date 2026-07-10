#!/usr/bin/env python3
"""Check if phantom touches fall inside a prior zone band (overlap suppression hypothesis)."""
import sys
from dataclasses import asdict
from pathlib import Path
import numpy as np

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb

PHANTOM_PIVOTS = [
    (276, "2017-02-07 PH"),
    (858, "2019-06-03 PL"),
    (1448, "2021-10-04 PL"),
]

base = asdict(rb.BRTConfig())
base.update(rb.mts_sheet_parity_overrides())
cfg = rb.BRTConfig(**base)
df = rb.load_csv(str(_REPO / "data" / "newdata" / "data" / "NVDA.csv"))
ph, pl, php, plp = rb.compute_pivots(
    df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
    realtime_filter_enabled=cfg.realtime_filter_enabled,
)
l3 = rb.build_level3_for_cfg(df, cfg, ph, pl, php, plp)
tp = l3["touch_price"].to_numpy(float)
zl = l3["zone_low"].to_numpy(float)
zh = l3["zone_high"].to_numpy(float)
band = float(cfg.band_pct)

def prior_zones(t):
    out = []
    for p in range(t):
        if np.isfinite(tp[p]) and tp[p] > 0:
            out.append((p, tp[p], zl[p], zh[p]))
    return out

for bar, label in PHANTOM_PIVOTS:
    ntp = tp[bar]
    nzl = ntp * (1 - band)
    nzh = ntp * (1 + band)
    print(f"\n{label} bar{bar} tp={ntp:.3f} band=[{nzl:.2f},{nzh:.2f}]")
    inside = []
    for p, ptp, pzl, pzh in prior_zones(bar):
        if pzl <= ntp <= pzh or (nzl <= pzh and nzh >= pzl):
            inside.append((p, ptp, pzl, pzh))
    print(f"  overlaps {len(inside)} prior zones:")
    for p, ptp, pzl, pzh in inside[-5:]:
        print(f"    piv{p} tp={ptp:.2f} [{pzl:.2f},{pzh:.2f}]")
