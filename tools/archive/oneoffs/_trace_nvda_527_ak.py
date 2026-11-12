#!/usr/bin/env python3
"""NVDA 2025-05-27: why engine BG passes when sheet BG fails."""
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb

base = asdict(rb.BRTConfig())
base.update(rb.mts_sheet_parity_overrides())
cfg = rb.BRTConfig(**base)
df = rb.load_csv(str(_REPO / "data/newdata/data/NVDA.csv"))
ph, pl, php, plp = rb.compute_pivots(
    df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
    realtime_filter_enabled=cfg.realtime_filter_enabled,
)
l3 = rb.build_level3_for_cfg(df, cfg, ph, pl, php, plp)
n = len(df)
o, h, lo, c = [df[x].to_numpy(float) for x in ["Open", "High", "Low", "Close"]]
mbh, mbi = rb._precompute_mat_bh_bi_stream(
    l3["zone_low"].to_numpy(float), l3["zone_high"].to_numpy(float), 7, n
)
de, dfa, dg, ds = rb._precompute_sheet_active_zone_arrays(h, lo, mbh, mbi, n, cfg)
g = rb._precompute_mts_bi_gates(o, h, lo, c, de, dfa, dg, ds, mbh, mbi, n, cfg)


def sheet_ak(i: int) -> tuple[bool, str]:
    if i < 1:
        return False, "no prior bar"
    ip = i - 1
    if not (np.isfinite(de[i]) and np.isfinite(dfa[i]) and np.isfinite(dg[i])):
        return False, "no active zone"
    if not (i > dg[i]):
        return False, "row not past DM"
    parts = [
        f"Close[{df.index[ip].date()}]={c[ip]:.4f} > DL={dfa[i]:.4f}? {c[ip] > dfa[i]}",
        f"L={lo[i]:.4f}<=DL? {lo[i] <= dfa[i]}",
        f"H={h[i]:.4f}>=DK={de[i]:.4f}? {h[i] >= de[i]}",
    ]
    ok = c[ip] > dfa[i] and lo[i] <= dfa[i] and h[i] >= de[i]
    return bool(ok), " | ".join(parts)


for d in ["2025-05-23", "2025-05-27"]:
    i = df.index.get_loc(pd.Timestamp(d))
    ip = i - 1
    ak, detail = sheet_ak(i)
    print(f"\n=== {d} (DN={int(ds[i])}, DL={dfa[i]:.4f}) ===")
    print(f"  AK formula: {ak}")
    print(f"  {detail}")
    print(f"  engine stored AK[i]={int(g['ak'][i])}")

i = df.index.get_loc(pd.Timestamp("2025-05-27"))
ip = i - 1
print("\n=== BG on 2025-05-27 ===")
print(f"  Sheet: OR(AK[5/27], AK[5/23]) for BG gate")
print(f"  AK[5/27]={bool(g['ak'][i])}  (Close 5/23={c[ip]:.4f} vs DL[5/27]={dfa[i]:.4f})")
print(f"  AK[5/23] stored on prior bar={bool(g['ak'][ip])}  (that bar had DN={int(ds[ip])}, DL={dfa[ip]:.4f})")
print(f"  Engine OR = {bool(g['ak'][i] or g['ak'][ip])}  -> BG={bool(g['bg'][i])}  BI={bool(g['bi'][i])}")
print("\n  Sheet intent: both false -> BG false")
print("  Engine bug: AK[5/23]=TRUE from 5/23's zone (DN=8) still counts on 5/27 (DN=11)")
