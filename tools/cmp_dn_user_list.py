#!/usr/bin/env python3
"""Compare engine DN vs user-provided full Active zone ID column."""
import sys
from dataclasses import asdict
from pathlib import Path
import numpy as np

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb

sheet_dn = [
    int(x.strip()) for x in (_REPO / "nvda_sheet_dn_full.txt").read_text().splitlines() if x.strip()
]

base = asdict(rb.BRTConfig())
base.update(rb.mts_sheet_parity_overrides())
cfg = rb.BRTConfig(**base)
df = rb.load_csv(str(_REPO / "data" / "newdata" / "data" / "NVDA.csv"))
n = len(df)
iso = [str(x).replace("-", "")[:8] for x in df.index]
h = df["High"].to_numpy(float)
lo = df["Low"].to_numpy(float)

ph, pl, php, plp = rb.compute_pivots(
    df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
    realtime_filter_enabled=cfg.realtime_filter_enabled,
)
l3 = rb.build_level3_for_cfg(df, cfg, ph, pl, php, plp)
mbh, mbi = rb._precompute_mat_bh_bi_stream(
    l3["zone_low"].to_numpy(float), l3["zone_high"].to_numpy(float), 7, n
)
de, dfa, dg, ds = rb._precompute_sheet_active_zone_arrays(h, lo, mbh, mbi, n, cfg)

print(f"NVDA bars: {n}")
print(f"Sheet DN list length: {len(sheet_dn)}")
if len(sheet_dn) != n:
    print(f"  LENGTH MISMATCH delta={len(sheet_dn)-n}")

# Only compare bars where engine has active zone
active = [i for i in range(min(n, len(sheet_dn))) if np.isfinite(ds[i])]
tot = len(active)
dn_ok = 0
diff_hist = {}
mism = []
for i in active:
    sdn = sheet_dn[i]
    edn = int(ds[i])
    if edn == sdn:
        dn_ok += 1
    else:
        d = edn - sdn
        diff_hist[d] = diff_hist.get(d, 0) + 1
        mism.append((i, sdn, edn, de[i], dfa[i], int(dg[i]) + 2))

print(f"\nDN match on {tot} active bars: {dn_ok} ({100*dn_ok/tot:.1f}%)")
print(f"DN diff histogram: {dict(sorted(diff_hist.items()))}")

# Dec 2019 window
print("\n=== Dec 2019 DN trace (sheet vs engine) ===")
print("date        sheet_DN eng_DN  dDN  zone_lo-zone_hi")
for i in range(n):
    d = f"{iso[i][:4]}-{iso[i][4:6]}-{iso[i][6:8]}"
    if d < "2019-11-15" or d > "2019-12-20":
        continue
    if i >= len(sheet_dn):
        continue
    sdn = sheet_dn[i]
    edn = int(ds[i]) if np.isfinite(ds[i]) else None
    z = f"${de[i]:.2f}-${dfa[i]:.2f}" if np.isfinite(de[i]) else "----"
    flag = "" if edn == sdn else " *"
    print(f"{d}  {sdn:>8}  {str(edn):>6}  {str((edn-sdn) if edn else '?'):>4}  {z}{flag}")

print("\nFirst 30 DN mismatches:")
for i, sdn, edn, zl, zu, dm in mism[:30]:
    d = f"{iso[i][:4]}-{iso[i][4:6]}-{iso[i][6:8]}"
    print(f"  {d} sheet={sdn} eng={edn} d={edn-sdn}  ${zl:.2f}-${zu:.2f} DM{dm}")
