#!/usr/bin/env python3
"""Full bar-by-bar DN/DK/DL/DM parity: engine vs sheet ground truth (NVDA unlimited)."""
import sys
from dataclasses import asdict
from pathlib import Path
import numpy as np

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb

gt = (_REPO / "nvda_active_zones_unlimited.tsv").read_text().splitlines()
# Ground-truth rows are aligned to sheet data rows; row r (1-based body) -> bar r-1.
gt_dk, gt_dl, gt_dm, gt_dn = {}, {}, {}, {}
for bar0, ln in enumerate(gt[1:]):
    f = ln.split("\t")
    if len(f) < 4 or not f[0].strip():
        continue
    try:
        gt_dk[bar0] = float(f[0].replace("$", ""))
        gt_dl[bar0] = float(f[1].replace("$", ""))
        gt_dm[bar0] = int(float(f[2]))
        gt_dn[bar0] = int(float(f[3]))
    except ValueError:
        continue

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
h = df["High"].to_numpy(float)
lo = df["Low"].to_numpy(float)
mbh, mbi = rb._precompute_mat_bh_bi_stream(
    l3["zone_low"].to_numpy(float), l3["zone_high"].to_numpy(float), 7, n
)
de, dfa, dg, ds = rb._precompute_sheet_active_zone_arrays(h, lo, mbh, mbi, n, cfg)

# Align: sheet body row index vs engine bar. Test both 0 and offset by matching a known date.
# From prior work sheet_row = bar + 2, i.e., body-row (1-based) = bar + 1 -> bar0 index = bar.
active_bars = [b for b in gt_dn if b < n]
tot = len(active_bars)
dk_ok = dl_ok = dm_ok = dn_ok = all_ok = 0
dn_diff_hist = {}
mism = []
for b in active_bars:
    e_dk = de[b] if np.isfinite(de[b]) else None
    e_dl = dfa[b] if np.isfinite(dfa[b]) else None
    e_dm = int(dg[b]) + 2 if np.isfinite(dg[b]) else None
    e_dn = int(ds[b]) if np.isfinite(ds[b]) else None
    dkm = e_dk is not None and abs(e_dk - gt_dk[b]) < 0.01
    dlm = e_dl is not None and abs(e_dl - gt_dl[b]) < 0.01
    dmm = e_dm is not None and e_dm == gt_dm[b]
    dnm = e_dn is not None and e_dn == gt_dn[b]
    dk_ok += dkm; dl_ok += dlm; dm_ok += dmm; dn_ok += dnm
    if dkm and dlm and dmm and dnm:
        all_ok += 1
    if e_dn is not None:
        d = e_dn - gt_dn[b]
        dn_diff_hist[d] = dn_diff_hist.get(d, 0) + 1
    if not (dkm and dnm):
        mism.append((b, gt_dk[b], gt_dl[b], gt_dm[b], gt_dn[b], e_dk, e_dl, e_dm, e_dn))

print(f"Active sheet bars compared: {tot}")
print(f"DK match: {dk_ok} ({100*dk_ok/tot:.1f}%)")
print(f"DL match: {dl_ok} ({100*dl_ok/tot:.1f}%)")
print(f"DM match: {dm_ok} ({100*dm_ok/tot:.1f}%)")
print(f"DN match: {dn_ok} ({100*dn_ok/tot:.1f}%)")
print(f"ALL match: {all_ok} ({100*all_ok/tot:.1f}%)")
print(f"\nDN diff histogram (engine-sheet): {dict(sorted(dn_diff_hist.items()))}")
print(f"\nFirst 25 DK/DN mismatches:")
for b, gdk, gdl, gdm, gdn, edk, edl, edm, edn in mism[:25]:
    d = f"{iso[b][:4]}-{iso[b][4:6]}-{iso[b][6:8]}"
    es = f"${edk:.2f}-${edl:.2f} DM{edm} DN{edn}" if edk else "----"
    print(f"  {d} bar{b} sheet ${gdk:.2f}-${gdl:.2f} DM{gdm} DN{gdn} | eng {es}")
