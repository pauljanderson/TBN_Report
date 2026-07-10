#!/usr/bin/env python3
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb

base = asdict(rb.BRTConfig())
base.update(rb.mts_sheet_parity_overrides())
cfg = rb.BRTConfig(**base)
df = rb.load_csv(str(_REPO / "data" / "newdata" / "data" / "TSLA.csv"))
iso = [str(x).replace("-", "")[:8] for x in df.index]
idx = {f"{s[:4]}-{s[4:6]}-{s[6:8]}": i for i, s in enumerate(iso)}
ph, pl, php, plp = rb.compute_pivots(
    df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
    realtime_filter_enabled=cfg.realtime_filter_enabled,
)
l3 = rb.build_level3_for_cfg(df, cfg, ph, pl, php, plp)
o, h, lo, c = [df[x].to_numpy(float) for x in "Open High Low Close".split()]
mbh, mbi = rb._precompute_mat_bh_bi_stream(
    l3["zone_low"].to_numpy(float), l3["zone_high"].to_numpy(float), 7, len(df)
)
de, dfa, dg, ds = rb._precompute_sheet_active_zone_arrays(h, lo, mbh, mbi, len(df), cfg)
g = rb._precompute_mts_bi_gates(o, h, lo, c, de, dfa, dg, ds, mbh, mbi, len(df), cfg)
c10 = int(cfg.lookback_long)

for d in [
    "2023-09-05", "2023-09-08", "2023-09-11", "2023-09-12", "2023-09-13",
    "2023-09-14", "2023-09-15", "2023-09-18", "2023-09-19", "2023-09-20",
]:
    if d not in idx:
        continue
    i = idx[d]
    dn = int(ds[i]) if np.isfinite(ds[i]) else -1
    s = max(0, i - c10)
    aks = [
        iso[k] for k in range(s, i + 1)
        if g["ak"][k] and np.isfinite(ds[k]) and int(ds[k]) == dn
    ]
    z = f"${de[i]:.2f}-${dfa[i]:.2f}" if np.isfinite(de[i]) else "----"
    print(
        f"{d} zone {z} DN{dn}  AK={int(g['ak'][i])} AM={int(g['am'][i])} "
        f"AR={int(g['ar'][i])} AW={int(g['aw'][i])} BC={int(g['bc'][i])} "
        f"BE={int(g['be'][i])} BG={int(g['bg'][i])} BI={int(g['bi'][i])}  "
        f"AK_same_DN={len(aks)} {aks[-6:]}"
    )
