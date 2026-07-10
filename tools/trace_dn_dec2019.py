#!/usr/bin/env python3
"""Trace DN count: list CE maturities from DM to bar for Dec-2019 mismatch."""
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
n = len(df)
iso = [str(x).replace("-", "")[:8] for x in df.index]
h, lo = df["High"].to_numpy(float), df["Low"].to_numpy(float)
ph, pl, php, plp = rb.compute_pivots(
    df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
    realtime_filter_enabled=cfg.realtime_filter_enabled,
)
l3 = rb.build_level3_for_cfg(df, cfg, ph, pl, php, plp)
zl = l3["zone_low"].to_numpy(float)
zh = l3["zone_high"].to_numpy(float)
mbh, mbi = rb._precompute_mat_bh_bi_stream(zl, zh, 7, n)
de, dfa, dg, ds = rb._precompute_sheet_active_zone_arrays(h, lo, mbh, mbi, n, cfg)

idx = {f"{iso[i][:4]}-{iso[i][4:6]}-{iso[i][6:8]}": i for i in range(n)}

for d in ("2019-12-02", "2019-12-04"):
    i = idx[d]
    dm = int(dg[i])
    print(f"\n=== {d} bar{i} sheet_row={i+2} ===")
    print(f"active zone ${de[i]:.2f}-${dfa[i]:.2f}  DM_bar={dm} DM_row={dm+2}  engine_DN={int(ds[i])}")
    print(f"Matured zones (CE>0) in [DM={dm} .. {i}]:")
    ces = []
    for k in range(dm, i + 1):
        if np.isfinite(mbh[k]) and mbh[k] > 0:
            dd = f"{iso[k][:4]}-{iso[k][4:6]}-{iso[k][6:8]}"
            tp = l3["touch_price"].iloc[k - 7] if k >= 7 else np.nan  # creation bar = maturity - lag
            ces.append((k, dd, mbh[k], mbi[k], k - 7))
    for n_, dd, ce, cf, piv in ces:
        pdd = f"{iso[piv][:4]}-{iso[piv][4:6]}-{iso[piv][6:8]}" if piv >= 0 else "?"
        print(f"  mat_row={n_+2} {dd}  CE={ce:.2f} CF={cf:.2f}  piv_row={piv+2} {pdd}")
    print(f"  COUNT = {len(ces)} (engine DN); sheet expects 9")

# All +1 mismatches: how many trace to phantom creation bars?
PHANTOMS = {276: "2017-02-07 PH", 858: "2019-06-03 PL", 1448: "2021-10-04 PL"}
mat_phantom = {b + 7: name for b, name in PHANTOMS.items()}  # maturity bar approx

user_dn = [int(x.strip()) for x in (_REPO / "nvda_sheet_dn_full.txt").read_text().splitlines() if x.strip()]
gt = (_REPO / "nvda_active_zones_unlimited.tsv").read_text().splitlines()
gt_bars = []
for bar0, ln in enumerate(gt[1:]):
    f = ln.split("\t")
    if len(f) >= 4 and f[3].strip():
        gt_bars.append(bar0)

plus1 = 0
phantom_in_window = 0
for k, bar in enumerate(gt_bars):
    sdn = user_dn[k]
    edn = int(ds[bar]) if np.isfinite(ds[bar]) else None
    if edn is None or edn != sdn + 1:
        continue
    plus1 += 1
    dm = int(dg[bar])
    for mbar, name in mat_phantom.items():
        if dm <= mbar <= bar:
            phantom_in_window += 1
            break

print(f"\n+1 mismatches: {plus1}, those with phantom maturity in [DM..bar]: {phantom_in_window}")
