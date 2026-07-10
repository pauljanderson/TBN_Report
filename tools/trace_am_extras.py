#!/usr/bin/env python3
"""Trace AM contributors for the Dec-2019 and Dec-2022 Python extra entries."""
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
o, h, l, c = [df[x].to_numpy(float) for x in "Open High Low Close".split()]
n = len(df)
iso = [str(x).replace("-", "")[:8] for x in df.index]
mbh, mbi = rb._precompute_mat_bh_bi_stream(
    l3["zone_low"].to_numpy(float), l3["zone_high"].to_numpy(float), 7, n
)
de, dfa, dg, ds = rb._precompute_sheet_active_zone_arrays(h, l, mbh, mbi, n, cfg)
g = rb._precompute_mts_bi_gates(o, h, l, c, de, dfa, dg, ds, mbh, mbi, n, cfg)
idx = {f"{s[:4]}-{s[4:6]}-{s[6:8]}": i for i, s in enumerate(iso)}
c10 = max(1, int(getattr(cfg, "lookback_long", 503)))

def trace(day: str):
    i = idx[day]
    dn_i = int(ds[i]) if np.isfinite(ds[i]) else -1
    print(f"\n=== {day} bar{i} sheet_row{i+2} ===")
    print(f"engine DK-DL ${de[i]:.2f}-${dfa[i]:.2f} DM_row {int(dg[i])+2} DN {dn_i} "
          f"AK {int(g['ak'][i])} AM {int(g['am'][i])} AQ {int(g['aq'][i])} BI {int(g['bi'][i])}")
    s = max(0, i - c10)
    print(f"AK=TRUE with engine DN=={dn_i} in [{s}..{i}]:")
    cnt = 0
    for k in range(s, i + 1):
        if g["ak"][k] and np.isfinite(ds[k]) and int(ds[k]) == dn_i:
            cnt += 1
            d = f"{iso[k][:4]}-{iso[k][4:6]}-{iso[k][6:8]}"
            print(f"  #{cnt} {d} bar{k} DN={int(ds[k])} zone ${de[k]:.2f}-${dfa[k]:.2f} DM_row{int(dg[k])+2}")
    print(f"engine AM count={cnt} (need >={int(getattr(cfg,'touch_threshold',2))})")

for day in ("2019-12-03", "2022-08-04", "2022-12-29"):
    if day in idx:
        trace(day)
# also show the BI=TRUE bar preceding each extra
print("\n\nBI=TRUE days near extras:")
for lo, hi in (("2019-12-01","2019-12-06"),("2022-08-01","2022-08-12"),("2022-12-27","2022-12-31")):
    for i, sdt in enumerate(iso):
        d = f"{sdt[:4]}-{sdt[4:6]}-{sdt[6:8]}"
        if lo <= d <= hi and g["bi"][i]:
            print(f"  {d} BI=TRUE zone ${de[i]:.2f}-${dfa[i]:.2f} DN{int(ds[i])}")
