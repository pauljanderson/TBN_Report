#!/usr/bin/env python3
"""NVDA BG/BI step-by-step on mismatch dates."""
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb


def bg_detail(df, g, de, c, d: str) -> None:
    i = df.index.get_loc(pd.Timestamp(d))
    akt = bool(g["ak"][i])
    aky = bool(g["ak"][i - 1]) if i >= 1 else False
    anchor = de[i] if akt else (de[i - 1] if i >= 1 else np.nan)
    s = max(0, i - 9)
    cnt = int(np.sum(c[s : i + 1] > anchor))
    print(f"=== {d} BG detail ===")
    print(f"AK={akt} AK[-1]={aky} (prior bar {df.index[i-1].date()})")
    print(
        f"anchor DK={anchor:.4f} "
        f"(from {'today' if akt else df.index[i-1].date()})"
    )
    print(f"closes > {anchor:.4f} in last 10 bars: count={cnt} (need 7)")
    for j in range(s, i + 1):
        print(
            f"  {df.index[j].date()} close={c[j]:.2f} "
            f"> {anchor:.4f}? {c[j] > anchor}"
        )
    print(
        f"BG={bool(g['bg'][i])} BI={bool(g['bi'][i])} "
        f"BC={int(g['bc'][i])} BC[-1]={int(g['bc'][i-1])} "
        f"AQ={int(g['aq'][i])} AQ[-1]={int(g['aq'][i-1])}"
    )
    print()


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
o, h, lo, c = [df[x].to_numpy(float) for x in ["Open", "High", "Low", "Close"]]
mbh, mbi = rb._precompute_mat_bh_bi_stream(
    l3["zone_low"].to_numpy(float), l3["zone_high"].to_numpy(float), 7, n
)
de, dfa, dg, ds = rb._precompute_sheet_active_zone_arrays(h, lo, mbh, mbi, n, cfg)
g = rb._precompute_mts_bi_gates(o, h, lo, c, de, dfa, dg, ds, mbh, mbi, n, cfg)

for d in ["2025-05-23", "2025-05-27", "2025-05-30", "2025-06-02"]:
    bg_detail(df, g, de, c, d)

# What if sheet BG=FALSE on 5/27 — test if AK[-1] should use prior row with SAME zone DN
i = df.index.get_loc(pd.Timestamp("2025-05-27"))
print("=== 5/27 AK[-1] uses de[i-1] from 5/23 zone ===")
print(f"5/23 DK={de[i-1]:.4f} (DN={int(ds[i-1])})")
print(f"5/27 DK={de[i]:.4f} (DN={int(ds[i])})")
print("Sheet LA=FALSE implies BG=FALSE — engine uses AK[-1] from 5/23 on 5/23 zone anchor")
print("If anchor were 5/27 DK (129.16) instead of 5/23 DK (126.92), count would be:")
anchor27 = de[i]
s = max(0, i - 9)
print(f"  count={int(np.sum(c[s:i+1] > anchor27))} (need 7 for BG)")
