#!/usr/bin/env python3
"""Re-trace Dec-2019 AM after nulling the 3 phantom creation bars."""
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
n = len(df)
iso = [str(x).replace("-", "")[:8] for x in df.index]
o, h, l, c = [df[x].to_numpy(float) for x in "Open High Low Close".split()]

zl = l3["zone_low"].to_numpy(float).copy()
zh = l3["zone_high"].to_numpy(float).copy()
for b in (276, 858, 1448):
    zl[b] = np.nan
    zh[b] = np.nan

mbh, mbi = rb._precompute_mat_bh_bi_stream(zl, zh, 7, n)
de, dfa, dg, ds = rb._precompute_sheet_active_zone_arrays(h, l, mbh, mbi, n, cfg)
g = rb._precompute_mts_bi_gates(o, h, l, c, de, dfa, dg, ds, mbh, mbi, n, cfg)
idx = {f"{s[:4]}-{s[4:6]}-{s[6:8]}": i for i, s in enumerate(iso)}
c10 = max(1, int(getattr(cfg, "lookback_long", 503)))

print("Dec 2019 window after phantom removal:")
for d in ("2019-12-02","2019-12-03","2019-12-04","2019-12-05","2019-12-06"):
    i = idx[d]
    z = f"${de[i]:.2f}-${dfa[i]:.2f}" if np.isfinite(de[i]) else "----"
    dn = int(ds[i]) if np.isfinite(ds[i]) else -1
    print(f"  {d} {z} DN{dn} AK{int(g['ak'][i])} AM{int(g['am'][i])} AQ{int(g['aq'][i])} "
          f"AW{int(g['aw'][i])} BE{int(g['be'][i])} BI{int(g['bi'][i])}")

# which day BI true and its AM contributors
for d in ("2019-12-02","2019-12-03"):
    i = idx[d]
    if not g["bi"][i]:
        continue
    dn_i = int(ds[i])
    s = max(0, i - c10)
    print(f"\n{d} BI=TRUE. AM contributors (AK & DN=={dn_i}):")
    for k in range(s, i + 1):
        if g["ak"][k] and np.isfinite(ds[k]) and int(ds[k]) == dn_i:
            dd = f"{iso[k][:4]}-{iso[k][4:6]}-{iso[k][6:8]}"
            print(f"  {dd} bar{k} DN{int(ds[k])} zone ${de[k]:.2f}-${dfa[k]:.2f} DMrow{int(dg[k])+2}")
