#!/usr/bin/env python3
"""Align engine matured-zone-lower (CE) sequence vs sheet CE list to find extras/misses."""
import sys
import difflib
from dataclasses import asdict
from pathlib import Path
import numpy as np

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb

SHEET_CE = """0.65 0.61 2.33 2.94 2.43 2.34 4.13 3.48 3.96 3.39 3.74 4.68 5.00 6.17
5.22 5.15 7.17 4.31 5.44 3.26 4.28 3.05 3.21 4.26 7.75 5.92 6.98 4.43 6.74
5.84 7.33 9.00 7.84 10.57 14.44 11.47 13.05 14.40 12.38 15.06 11.34 13.24
17.51 31.66 33.96 27.48 26.61 30.70 25.13 20.47 26.38 20.47 24.18 20.24
28.37 17.92 15.26 18.00 15.44 19.23 15.02 16.98 13.78 15.72 17.78 18.88
16.39 18.78 13.00 11.71 13.39 10.59 16.66 16.92 18.41 13.60 41.10 49.26
73.12 95.45 83.31 94.83 74.10 137.94 116.45 133.43 117.76 88.88 98.93
125.12 129.16 124.32 150.07 126.92 145.99 110.75 140.57 102.67 84.89
112.80 93.14 207.95 175.33 166.16 167.61 231.81""".split()
sheet = [f"{float(x):.2f}" for x in SHEET_CE]

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
mbh, _ = rb._precompute_mat_bh_bi_stream(
    l3["zone_low"].to_numpy(float), l3["zone_high"].to_numpy(float), 7, n
)
eng = []
eng_meta = []
for i in range(n):
    if np.isfinite(mbh[i]) and mbh[i] > 0:
        eng.append(f"{mbh[i]:.2f}")
        eng_meta.append((i, iso[i]))

print(f"Sheet CE count: {len(sheet)}   Engine CE count: {len(eng)}")

sm = difflib.SequenceMatcher(a=sheet, b=eng, autojunk=False)
print("\n--- Alignment (sheet vs engine) ---")
for tag, i1, i2, j1, j2 in sm.get_opcodes():
    if tag == "equal":
        continue
    if tag in ("replace", "delete"):
        for k in range(i1, i2):
            print(f"  SHEET-ONLY (engine missing): CE={sheet[k]}  [sheet idx {k}]")
    if tag in ("replace", "insert"):
        for k in range(j1, j2):
            b, d = eng_meta[k]
            dd = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
            print(f"  ENGINE-ONLY (extra): CE={eng[k]} matured bar{b} {dd}  [eng idx {k}]")
print(f"\nMatch ratio: {sm.ratio():.3f}")
