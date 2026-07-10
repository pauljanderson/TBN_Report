#!/usr/bin/env python3
"""Focused traces for TSLA's 5 critical mismatch clusters."""
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
df = rb.load_csv(str(_REPO / "data" / "newdata" / "data" / "TSLA.csv"))
iso = [str(x).replace("-", "")[:8] for x in df.index]
idx = {f"{s[:4]}-{s[4:6]}-{s[6:8]}": i for i, s in enumerate(iso)}
ph, pl, php, plp = rb.compute_pivots(
    df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
    realtime_filter_enabled=cfg.realtime_filter_enabled,
)
l3 = rb.build_level3_for_cfg(df, cfg, ph, pl, php, plp)
n = len(df)
o, h, lo, c = [df[x].to_numpy(float) for x in "Open High Low Close".split()]
mbh, mbi = rb._precompute_mat_bh_bi_stream(
    l3["zone_low"].to_numpy(float), l3["zone_high"].to_numpy(float), 7, n
)
de, dfa, dg, ds = rb._precompute_sheet_active_zone_arrays(h, lo, mbh, mbi, n, cfg)
g = rb._precompute_mts_bi_gates(o, h, lo, c, de, dfa, dg, ds, mbh, mbi, n, cfg)
growth_bars = 756

def row(d):
    i = idx[d]
    dn = int(ds[i]) if np.isfinite(ds[i]) else "-"
    z = f"${de[i]:.2f}-${dfa[i]:.2f}" if np.isfinite(de[i]) else "----"
    dm = int(dg[i]) + 2 if np.isfinite(dg[i]) else "-"
    gb = i - growth_bars
    g3 = bool(c[i] >= c[gb]) if gb >= 0 else False
    print(
        f"{d}  O{c[i]:.2f} C{c[i]:.2f}  zone {z} DM{dm} DN{dn}  "
        f"AK={int(g['ak'][i])} AM={int(g['am'][i])} AW={int(g['aw'][i])} "
        f"BC={int(g['bc'][i])} BE={int(g['be'][i])} BG={int(g['bg'][i])} "
        f"BW={int(g['bw'][i])} BI={int(g['bi'][i])}  g3y={g3} close756={c[gb]:.2f}"
    )

clusters = [
    ("CLUSTER A: Jan-2019 (sheet 1/2 vs py 1/7)", [
        "2019-01-02", "2019-01-03", "2019-01-04", "2019-01-07", "2019-01-08",
    ]),
    ("CLUSTER B: Feb-2019 extra (py 2/6 entry)", [
        "2019-02-04", "2019-02-05", "2019-02-06", "2019-02-07", "2019-02-11",
    ]),
    ("CLUSTER C: Dec-2021 WIN miss (sheet 12/21)", [
        "2021-12-17", "2021-12-20", "2021-12-21", "2021-12-22", "2021-12-23",
        "2022-01-03", "2022-01-04",
    ]),
    ("CLUSTER D: Sep-2023 double (sheet 9/19 + 9/26)", [
        "2023-09-15", "2023-09-18", "2023-09-19", "2023-09-20", "2023-09-21",
        "2023-09-22", "2023-09-25", "2023-09-26", "2023-09-27",
    ]),
    ("CLUSTER E: Mar-2025 extra (py 3/3)", [
        "2025-02-26", "2025-02-27", "2025-02-28", "2025-03-03", "2025-03-04",
        "2025-10-22", "2025-10-23",
    ]),
]

for title, dates in clusters:
    print(f"\n{'='*72}\n{title}\n")
    for d in dates:
        if d in idx:
            row(d)

# CE gaps: locate sheet-only zones by value
print(f"\n{'='*72}\nCE GAP LOCATIONS (sheet-only values)\n")
sheet_only = [285.48, 308.38, 176.46, 180.56]
for target in sheet_only:
    # find nearest engine maturity
    best = None
    for i in range(n):
        if np.isfinite(mbh[i]) and mbh[i] > 0:
            diff = abs(mbh[i] - target)
            if best is None or diff < best[0]:
                best = (diff, i, mbh[i])
    if best:
        d = f"{iso[best[1]][:4]}-{iso[best[1]][4:6]}-{iso[best[1]][6:8]}"
        print(f"  sheet CE={target:.2f}  nearest engine CE={best[2]:.2f} on {d} (diff={best[0]:.2f})")
