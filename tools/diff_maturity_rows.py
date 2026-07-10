#!/usr/bin/env python3
"""Diff engine matured-zone rows vs sheet ground-truth DM set (NVDA unlimited zones)."""
import sys
from dataclasses import asdict
from pathlib import Path
import numpy as np

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb

# Sheet ground-truth active zones: DK DL DM DN per data row (row index = line# in file body).
gt = (_REPO / "nvda_active_zones_unlimited.tsv").read_text().splitlines()
sheet_dm = set()
sheet_dm_examples = {}
for ln in gt[1:]:
    f = ln.split("\t")
    if len(f) < 4 or not f[2].strip():
        continue
    try:
        dm = int(float(f[2]))
    except ValueError:
        continue
    sheet_dm.add(dm)
    if dm not in sheet_dm_examples:
        sheet_dm_examples[dm] = (f[0].strip(), f[1].strip())

# Engine maturities.
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
mbh, mbi = rb._precompute_mat_bh_bi_stream(
    l3["zone_low"].to_numpy(float), l3["zone_high"].to_numpy(float), 7, n
)
# Engine matured rows (sheet-row space = bar + 2).
eng_dm = {}
for i in range(n):
    if np.isfinite(mbh[i]) and mbh[i] > 0:
        eng_dm[i + 2] = (mbh[i], mbi[i], iso[i])

eng_rows = set(eng_dm)
print(f"Sheet unique maturity rows: {len(sheet_dm)}")
print(f"Engine matured rows       : {len(eng_rows)}")

only_eng = sorted(eng_rows - sheet_dm)
only_sheet = sorted(sheet_dm - eng_rows)
print(f"\nEngine-only maturities (spurious, inflate DN): {len(only_eng)}")
for r in only_eng:
    ce, cf, d = eng_dm[r]
    dd = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    print(f"  row{r} bar{r-2} {dd} CE={ce:.3f} CF={cf:.3f}")

print(f"\nSheet-only maturities (engine missed): {len(only_sheet)}")
for r in only_sheet[:60]:
    ex = sheet_dm_examples.get(r, ("", ""))
    print(f"  row{r} bar{r-2} sheet_zone {ex[0]}-{ex[1]}")
