#!/usr/bin/env python3
"""Compare engine DN vs user DN list on the 1408 active-zone bars (aligned to gt TSV)."""
import sys
from dataclasses import asdict
from pathlib import Path
import numpy as np

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb

user_dn = [
    int(x.strip()) for x in (_REPO / "nvda_sheet_dn_full.txt").read_text().splitlines() if x.strip()
]
gt = (_REPO / "nvda_active_zones_unlimited.tsv").read_text().splitlines()
gt_bars = []
for bar0, ln in enumerate(gt[1:]):
    f = ln.split("\t")
    if len(f) >= 4 and f[3].strip():
        try:
            gt_bars.append(bar0)
        except ValueError:
            pass

print(f"user_dn={len(user_dn)} gt_active_bars={len(gt_bars)}")
if len(user_dn) != len(gt_bars):
    print("WARNING: length mismatch between user list and gt active bars")

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
mbh, mbi = rb._precompute_mat_bh_bi_stream(
    l3["zone_low"].to_numpy(float), l3["zone_high"].to_numpy(float), 7, n
)
de, dfa, dg, ds = rb._precompute_sheet_active_zone_arrays(h, lo, mbh, mbi, n, cfg)

# Pair user_dn[k] with gt_bars[k]
tot = len(user_dn)
user_eng_ok = user_gt_ok = eng_gt_ok = all3 = 0
diff_hist = {}
mism = []
for k, bar in enumerate(user_dn):
    if k >= len(gt_bars):
        break
    i = gt_bars[k]
    sdn = user_dn[k]
    edn = int(ds[i]) if np.isfinite(ds[i]) else None
    # read gt from tsv
    f = gt[i + 1].split("\t")
    gdn = int(float(f[3])) if len(f) >= 4 and f[3].strip() else None

    if edn == sdn:
        user_eng_ok += 1
    if gdn == sdn:
        user_gt_ok += 1
    if edn == gdn:
        eng_gt_ok += 1
    if edn == sdn == gdn:
        all3 += 1
    if edn is not None and edn != sdn:
        d = edn - sdn
        diff_hist[d] = diff_hist.get(d, 0) + 1
        mism.append((i, sdn, edn, gdn, de[i], dfa[i], int(dg[i]) + 2))

print(f"\nOn {tot} active-zone bars:")
print(f"  user == engine : {user_eng_ok} ({100*user_eng_ok/tot:.1f}%)")
print(f"  user == gt_tsv : {user_gt_ok} ({100*user_gt_ok/tot:.1f}%)")
print(f"  engine == gt   : {eng_gt_ok} ({100*eng_gt_ok/tot:.1f}%)")
print(f"  all three      : {all3}")
print(f"\nengine - user histogram: {dict(sorted(diff_hist.items()))}")

print("\n=== Dec 2019 (user DN) ===")
print("date        user  eng  gt  dDN  zone")
for k, bar in enumerate(gt_bars):
    d = f"{iso[bar][:4]}-{iso[bar][4:6]}-{iso[bar][6:8]}"
    if d < "2019-11-25" or d > "2019-12-10":
        continue
    sdn = user_dn[k]
    edn = int(ds[bar]) if np.isfinite(ds[bar]) else None
    f = gt[bar + 1].split("\t")
    gdn = int(float(f[3])) if f[3].strip() else None
    z = f"${de[bar]:.2f}-${dfa[bar]:.2f}" if np.isfinite(de[bar]) else "----"
    flag = "" if edn == sdn else " *"
    print(f"{d}  {sdn:>4}  {str(edn):>4}  {str(gdn):>4}  {str(edn-sdn if edn else '?'):>4}  {z}{flag}")

print("\nFirst 20 user!=engine mismatches:")
for i, sdn, edn, gdn, zl, zu, dm in mism[:20]:
    d = f"{iso[i][:4]}-{iso[i][4:6]}-{iso[i][6:8]}"
    print(f"  {d} user={sdn} eng={edn} gt={gdn} d={edn-sdn} ${zl:.2f}-${zu:.2f} DM{dm}")
