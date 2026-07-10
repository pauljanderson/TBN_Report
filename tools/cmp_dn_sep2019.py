#!/usr/bin/env python3
"""Compare engine DN vs sheet DN for NVDA Sep-Oct 2019 and inspect maturity stream."""
import sys
from dataclasses import asdict
from pathlib import Path
import numpy as np

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb

# Sheet ground truth: date -> (DK, DL, DM_row, DN, AK, AW, BI)
SHEET = {
    "2019-09-03": (3.96, 4.12, 377, 16, True, True, False),
    "2019-09-04": (4.13, 4.29, 370, 18, False, False, False),
    "2019-09-05": (4.26, 4.44, 887, 1, False, True, False),
    "2019-09-06": (4.26, 4.44, 887, 1, True, True, False),
    "2019-09-09": (None, None, None, None, None, None, False),
    "2019-09-10": (4.31, 4.49, 720, 7, True, False, False),
    "2019-09-11": (None, None, None, None, None, None, False),
    "2019-09-12": (4.68, 4.88, 439, 13, False, True, False),
    "2019-09-13": (None, None, None, None, None, None, False),
    "2019-09-16": (4.31, 4.49, 720, 7, True, False, False),
    "2019-09-17": (4.31, 4.49, 720, 7, True, True, True),
    "2019-09-18": (4.26, 4.44, 887, 1, True, True, False),
    "2019-09-19": (4.26, 4.44, 887, 1, True, True, False),
    "2019-09-20": (4.26, 4.44, 887, 1, False, True, False),
    "2019-09-23": (4.26, 4.44, 887, 1, False, True, False),
    "2019-09-24": (4.26, 4.44, 887, 1, False, True, False),
    "2019-09-25": (4.26, 4.44, 887, 1, False, True, False),
    "2019-09-26": (4.26, 4.44, 887, 1, True, True, False),
    "2019-09-27": (4.26, 4.44, 887, 1, False, True, False),
    "2019-09-30": (4.26, 4.44, 887, 1, False, True, False),
    "2019-10-01": (4.26, 4.44, 887, 1, False, True, False),
    "2019-10-02": (4.26, 4.44, 887, 1, False, True, False),
    "2019-10-03": (4.26, 4.44, 887, 1, False, True, False),
    "2019-10-04": (4.31, 4.49, 720, 7, True, True, True),
    "2019-10-07": (4.68, 4.88, 439, 13, False, True, False),
    "2019-10-08": (4.26, 4.44, 887, 1, True, True, False),
    "2019-10-09": (4.31, 4.49, 720, 7, False, True, True),
    "2019-10-10": (None, None, None, None, None, None, False),
    "2019-10-11": (4.68, 4.88, 439, 13, False, True, False),
    "2019-10-14": (None, None, None, None, None, None, False),
    "2019-10-15": (4.68, 4.88, 439, 13, False, True, False),
}

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

print("date        | sheet: DK-DL   DMr DN AK AW BI | engine: DK-DL   DMr DN AK AW BI | dDN dDK")
print("-" * 105)
for d, (sdk, sdl, sdm, sdn, sak, saw, sbi) in SHEET.items():
    if d not in idx:
        print(f"{d} NOT IN DATA")
        continue
    i = idx[d]
    edk = de[i] if np.isfinite(de[i]) else None
    edl = dfa[i] if np.isfinite(dfa[i]) else None
    edmr = int(dg[i]) + 2 if np.isfinite(dg[i]) else None
    edn = int(ds[i]) if np.isfinite(ds[i]) else None
    eak, eaw, ebi = bool(g["ak"][i]), bool(g["aw"][i]), bool(g["bi"][i])
    s_z = f"{sdk:.2f}-{sdl:.2f}" if sdk else "----"
    e_z = f"{edk:.2f}-{edl:.2f}" if edk else "----"
    ddn = (edn - sdn) if (edn is not None and sdn is not None) else "?"
    ddk_flag = "" if (edk is None and sdk is None) or (edk and sdk and abs(edk - sdk) < 0.01) else "*"
    bi_flag = "" if ebi == bool(sbi) else " <-BI!"
    print(
        f"{d} | {s_z:10s} {str(sdm):>4} {str(sdn):>2} {int(bool(sak)) if sak is not None else '-'}  "
        f"{int(bool(saw)) if saw is not None else '-'}  {int(bool(sbi))}  | "
        f"{e_z:10s} {str(edmr):>4} {str(edn):>2} {int(eak)}  {int(eaw)}  {int(ebi)}  | "
        f"{str(ddn):>3} {ddk_flag}{bi_flag}"
    )

# Inspect matured-zone stream around DM=720 for 9/17
i917 = idx["2019-09-17"]
best_j = int(dg[i917])
print(f"\n9/17 bar={i917} sheet_row={i917+2} DM_bar={best_j} DM_row={best_j+2}")
print(f"engine DN={int(ds[i917])} sheet DN=7")
print(f"\nMatured zones (CE>0) in [DM_bar={best_j} .. current={i917}]:")
cnt = 0
for k in range(best_j, i917 + 1):
    if np.isfinite(mbh[k]) and mbh[k] > 0:
        cnt += 1
        print(f"  #{cnt} bar{k} row{k+2} CE={mbh[k]:.3f} CF={mbi[k]:.3f}  ({iso[k][:4]}-{iso[k][4:6]}-{iso[k][6:8]})")
print(f"Total matured zones in range = {cnt} (engine DN); sheet DN=7")
