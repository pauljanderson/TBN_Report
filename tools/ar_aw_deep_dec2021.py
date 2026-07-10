#!/usr/bin/env python3
"""Deep AR/AW trace for TSLA Dec 2021 row 1504."""
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
ph, pl, php, plp = rb.compute_pivots(
    df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
    realtime_filter_enabled=cfg.realtime_filter_enabled,
)
l3 = rb.build_level3_for_cfg(df, cfg, ph, pl, php, plp)
n = len(df)
h, lo = df["High"].to_numpy(float), df["Low"].to_numpy(float)
mbh, mbi = rb._precompute_mat_bh_bi_stream(
    l3["zone_low"].to_numpy(float), l3["zone_high"].to_numpy(float), 7, n
)
de, dfa, dg, ds = rb._precompute_sheet_active_zone_arrays(h, lo, mbh, mbi, n, cfg)
c5 = cfg.band_pct
cd = np.full(n, np.nan)
for j in range(n):
    if np.isfinite(mbh[j]) and mbh[j] > 0:
        cd[j] = mbh[j] / (1.0 - c5)

c10 = int(cfg.lookback_long)
c6 = int(cfg.touch_threshold)

dates = [
    "2021-12-13", "2021-12-14", "2021-12-15", "2021-12-16", "2021-12-17",
    "2021-12-20", "2021-12-21",
]
for d in dates:
    i = df.index.get_loc(d)
    dk, dl = de[i], dfa[i]
    s = max(0, i - c10)
    hits = []
    for k in range(s, i + 1):
        if np.isfinite(cd[k]) and np.isfinite(dk) and cd[k] >= dk and cd[k] <= dl:
            hits.append((str(df.index[k].date()), round(cd[k], 2)))
    prev_dn = int(ds[i - 1]) if i > 0 and np.isfinite(ds[i - 1]) else -1
    ar = len(hits)
    aw = ar >= c6 and (i == 0 or ar < c6 or (np.isfinite(ds[i]) and ds[i] != ds[i - 1]))
    # proper AW
    prev_ar = 0
    if i > 0 and np.isfinite(de[i - 1]):
        ps = max(0, i - 1 - c10)
        prev_ar = sum(
            1 for k in range(ps, i)
            if np.isfinite(cd[k]) and np.isfinite(de[i - 1])
            and cd[k] >= de[i - 1] and cd[k] <= dfa[i - 1]
        )
    zone_chg = i > 0 and np.isfinite(ds[i]) and np.isfinite(ds[i - 1]) and ds[i] != ds[i - 1]
    aw2 = ar >= c6 and (prev_ar < c6 or zone_chg)
    print(
        f"{d} row{i+2} DN={int(ds[i])} prevDN={prev_dn} "
        f"DK={dk:.2f} DL={dl:.2f} AR={ar} prevAR={prev_ar} zoneChg={zone_chg} AW={aw2}"
    )
    print(f"  CD hits ({len(hits)}): {hits[-8:]}")

# AR using prior bar zone band on zone-change day?
print("\n--- AR if using PREVIOUS bar DK/DL on zone-change days ---")
for d in dates:
    i = df.index.get_loc(d)
    if i == 0:
        continue
    dk = de[i - 1] if np.isfinite(de[i - 1]) else de[i]
    dl = dfa[i - 1] if np.isfinite(dfa[i - 1]) else dfa[i]
    zone_chg = np.isfinite(ds[i]) and np.isfinite(ds[i - 1]) and ds[i] != ds[i - 1]
    if not zone_chg:
        continue
    s = max(0, i - c10)
    hits = [
        (str(df.index[k].date()), round(cd[k], 2))
        for k in range(s, i + 1)
        if np.isfinite(cd[k]) and np.isfinite(dk) and cd[k] >= dk and cd[k] <= dl
    ]
    print(f"{d} zoneChg: AR_prev_band={len(hits)} hits={hits[-6:]}")
