#!/usr/bin/env python3
"""List all AK support-test events 2018-2019 for NVDA MTS."""
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
o = df["Open"].to_numpy(float)
h = df["High"].to_numpy(float)
l = df["Low"].to_numpy(float)
c = df["Close"].to_numpy(float)
n = len(df)
iso = [str(x).replace("-", "")[:8] for x in df.index]
mbh, mbi = rb._precompute_mat_bh_bi_stream(
    l3["zone_low"].to_numpy(float), l3["zone_high"].to_numpy(float), 7, n
)
de, dfa, dg, ds = rb._precompute_sheet_active_zone_arrays(h, l, mbh, mbi, n, cfg)
g = rb._precompute_mts_bi_gates(o, h, l, c, de, dfa, dg, ds, mbh, mbi, n, cfg)

print("date       DN  zone              row  AK AM AQ AW BI")
for i, s in enumerate(iso):
    if s < "20180701" or s > "20191231":
        continue
    if not (g["ak"][i] or g["aw"][i] or g["bi"][i]):
        continue
    d = f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    dn = int(ds[i]) if np.isfinite(ds[i]) else -1
    z = f"${de[i]:.2f}-${dfa[i]:.2f}" if np.isfinite(de[i]) else "----"
    row = int(dg[i]) + 2 if np.isfinite(dg[i]) else -1
    print(
        f"{d} {dn:3d} {z:17s} {row:4d} "
        f"{int(g['ak'][i])}  {int(g['am'][i])}  {int(g['aq'][i])}  "
        f"{int(g['aw'][i])}  {int(g['bi'][i])}"
    )
