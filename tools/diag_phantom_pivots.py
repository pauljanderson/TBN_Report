#!/usr/bin/env python3
"""Diagnose the 3 phantom zone-creation pivots: conditions + nearest prior same-side zone."""
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

def dts(i):
    return f"{iso[i][:4]}-{iso[i][4:6]}-{iso[i][6:8]}"

# phantom pivot (creation) bars
phantom_pivbars = [276, 858, 1448]
# collect all created-zone bars
created = [i for i in range(n) if np.isfinite(tp[i]) and tp[i] > 0]

for pb in phantom_pivbars:
    org = "PH-high" if origin[pb] == 1 else "PL-low"
    print(f"\n=== PHANTOM created {dts(pb)} bar{pb} {org} tp={tp[pb]:.3f} zone {zl[pb]:.2f}-{zh[pb]:.2f} ===")
    print(f"  OHLC O{o[pb]:.3f} H{h[pb]:.3f} L{l[pb]:.3f} C{c[pb]:.3f}")
    # nearest prior created zone of SAME origin
    prior_same = [i for i in created if i < pb and origin[i] == origin[pb]]
    if prior_same:
        p = prior_same[-1]
        gap = pb - p
        pct = abs(tp[pb] - tp[p]) / tp[p] * 100
        print(f"  nearest prior SAME-origin zone: {dts(p)} bar{p} tp={tp[p]:.3f} "
              f"(gap {gap} bars, {pct:.2f}% price diff)")
    # nearest prior created zone ANY origin within 3%
    near = [(i, abs(tp[i]-tp[pb])/tp[pb]*100) for i in created if i < pb]
    near = [(i, pc) for i, pc in near if pc <= 3.0]
    near.sort(key=lambda x: x[0])
    print("  prior created zones within 3% price:")
    for i, pc in near[-5:]:
        print(f"    {dts(i)} bar{i} tp={tp[i]:.3f} zone {zl[i]:.2f}-{zh[i]:.2f} "
              f"origin={'PH' if origin[i]==1 else 'PL'} ({pc:.2f}%, {pb-i} bars before)")
    # show neighbor bars around the pivot for pivot-shape context
    print("  neighborhood (bar: O/H/L/C):")
    for i in range(max(0, pb-3), min(n, pb+4)):
        mark = " <--" if i == pb else ""
        print(f"    {dts(i)} bar{i}: {o[i]:.3f}/{h[i]:.3f}/{l[i]:.3f}/{c[i]:.3f}{mark}")
