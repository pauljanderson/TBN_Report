#!/usr/bin/env python3
"""Trace TSLA 2024-08-02 active zone: engine DN=12 vs sheet DN=1."""
from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb

SHEET = {
    "2024-08-02": (210.4158, 219.0042, 2161, 1),
    "2024-08-01": None,
    "2024-08-05": None,
}


def overlap_detail(
    i: int,
    h: np.ndarray,
    lo: np.ndarray,
    ce_all: np.ndarray,
    cf_all: np.ndarray,
    df: pd.DataFrame,
    cfg: rb.BRTConfig,
    focus_js: list[int] | None = None,
) -> None:
    zone_cmp = rb._cfg_overlap_compare_round_decimals(cfg)
    hi = float(np.round(h[i], zone_cmp) if zone_cmp >= 0 else h[i])
    li = float(np.round(lo[i], zone_cmp) if zone_cmp >= 0 else lo[i])
    print(f"\nBar i={i} date={df.index[i].date()} H={h[i]:.4f} L={lo[i]:.4f}")
    print(f"  Overlap compare H={hi} L={li} (round={zone_cmp})")

    cands = []
    for j in range(i + 1):
        if not (np.isfinite(ce_all[j]) and ce_all[j] > 0 and np.isfinite(cf_all[j])):
            continue
        ce, cf = float(ce_all[j]), float(cf_all[j])
        if zone_cmp >= 0:
            zlr, zur = round(ce, zone_cmp), round(cf, zone_cmp)
        else:
            zlr, zur = ce, cf
        ov = hi >= zlr and li <= zur
        same_bar = i <= j
        cnt = sum(
            1 for k in range(j, i + 1) if np.isfinite(ce_all[k]) and ce_all[k] > 0
        )
        low_in = zlr <= li <= zur
        if focus_js is None or j in focus_js or ov:
            cands.append((j, ce, cf, cnt, low_in, ov, same_bar))

    cands.sort(key=lambda x: x[0], reverse=True)
    print(f"  Overlapping matured zones ({sum(1 for c in cands if c[5])} with i>j enforced below):")
    print(f"  {'j':>5} {'date':12} {'CE':>10} {'CF':>10} {'DN':>3} low-in ov  i>j?")
    for j, ce, cf, cnt, low_in, ov, same_bar in cands[:15]:
        if not ov:
            continue
        i_gt_j = i > j
        mark = " <-- engine MAX" if j == int(dg[i]) else ""
        mark = mark or (" <-- sheet DM" if j == 2161 else "")
        print(
            f"  {j:5d} {str(df.index[j].date()):12} {ce:10.4f} {cf:10.4f} {cnt:3d} "
            f"{'Y' if low_in else 'N':5} {'Y' if ov else 'N':2}  {'Y' if i_gt_j else 'N':3}{mark}"
        )

    # Zones blocked by i<=j rule
    blocked = [(j, ce, cf) for j, ce, cf, _, _, ov, sb in cands if ov and i <= j]
    if blocked:
        print(f"\n  BLOCKED by engine i>j rule (overlap but i<=j): {len(blocked)}")
        for j, ce, cf in blocked[:5]:
            print(f"    j={j} {df.index[j].date()} CE={ce:.4f} CF={cf:.4f}")


def am_count(i: int, dn: int, g, ds, df, win: int = 503) -> None:
    s = max(0, i - win)
    hits = [
        (str(df.index[k].date()), int(ds[k]), int(g["ak"][k]))
        for k in range(s, i + 1)
        if g["ak"][k] and int(ds[k]) == dn
    ]
    print(f"  AM window DN={dn}: {len(hits)} hits (need 2): {hits}")


base = asdict(rb.BRTConfig())
base.update(rb.mts_sheet_parity_overrides())
cfg = rb.BRTConfig(**base)

df = rb.load_csv(str(_REPO / "data" / "newdata" / "data" / "TSLA.csv"))
ph, pl, php, plp = rb.compute_pivots(
    df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
    realtime_filter_enabled=cfg.realtime_filter_enabled,
)
l3 = rb.build_level3_for_cfg(df, cfg, ph, pl, php, plp)
n = len(df)
o, h, lo, c = [df[x].to_numpy(float) for x in ["Open", "High", "Low", "Close"]]
mbh, mbi = rb._precompute_mat_bh_bi_stream(
    l3["zone_low"].to_numpy(float), l3["zone_high"].to_numpy(float), 7, n
)
ce_all = np.asarray(mbh, dtype=np.float64)
cf_all = np.asarray(mbi, dtype=np.float64)
de, dfa, dg, ds = rb._precompute_sheet_active_zone_arrays(h, lo, mbh, mbi, n, cfg)
g = rb._precompute_mts_bi_gates(o, h, lo, c, de, dfa, dg, ds, mbh, mbi, n, cfg)

dates = ["2024-07-30", "2024-07-31", "2024-08-01", "2024-08-02", "2024-08-05"]
print("=" * 72)
print("TSLA active zone + gates around 2024-08-02")
print("=" * 72)
hdr = "Date       O      H      L      C | DK-DL (DM DN) | AK AM AQ BI"
print(hdr)
for d in dates:
    i = df.index.get_loc(pd.Timestamp(d))
    print(
        f"{d} {o[i]:6.2f} {h[i]:6.2f} {lo[i]:6.2f} {c[i]:6.2f} | "
        f"{de[i]:.2f}-{dfa[i]:.2f} ({int(dg[i])} {int(ds[i])}) | "
        f"{int(g['ak'][i])}  {int(g['am'][i])}  {int(g['aq'][i])}  {int(g['bi'][i])}"
    )

i802 = df.index.get_loc(pd.Timestamp("2024-08-02"))
sdk, sdl, sdm, sdn = SHEET["2024-08-02"]
print(f"\nSheet 2024-08-02: DK={sdk} DL={sdl} DM={sdm} DN={sdn}")
print(
    f"Engine 2024-08-02: DK={de[i802]:.4f} DL={dfa[i802]:.4f} "
    f"DM={int(dg[i802])} DN={int(ds[i802])}"
)

# CE at sheet DM row (Excel row 2161 -> bar index?)
for label, j in [("sheet DM=2161", 2160), ("sheet DM=2161 idx+1", 2161), ("engine DM", int(dg[i802]))]:
    if 0 <= j < n:
        ce = ce_all[j]
        cf = cf_all[j]
        print(
            f"  {label}: j={j} date={df.index[j].date()} "
            f"CE={ce:.4f} CF={cf:.4f} valid={np.isfinite(ce) and ce>0}"
        )

overlap_detail(i802, h, lo, ce_all, cf_all, df, cfg, focus_js=[2160, 2161, 1971, int(dg[i802])])

# Sheet zone overlap manual
print(f"\nSheet zone [{sdk}, {sdl}] overlap on 8/2?")
print(f"  H={h[i802]:.4f} >= {sdk}? {h[i802] >= sdk}")
print(f"  L={lo[i802]:.4f} <= {sdl}? {lo[i802] <= sdl}")

# AM impact on 2025-02-28
i228 = df.index.get_loc(pd.Timestamp("2025-02-28"))
print("\n" + "=" * 72)
print("AM impact on 2025-02-28 (why BI differs)")
print("=" * 72)
print(f"Engine 2/28/2025: DN={int(ds[i228])} AM={int(g['am'][i228])} BI={int(g['bi'][i228])}")
am_count(i228, int(ds[i228]), g, ds, df)
print(f"\nIf 2024-08-02 had sheet DN=1 (not {int(ds[i802])}):")
am_count(i228, 1, g, ds, df)  # wrong - would need recompute AK with different DN

# Simulate AM if 8/2 DN were 1: only count AK where dn[k]==1
s = max(0, i228 - 503)
hits_sheet_logic = [
    str(df.index[k].date())
    for k in range(s, i228 + 1)
    if g["ak"][k] and int(ds[k]) == int(ds[i228]) and k != i802
]
print(f"  Engine AK+DN=12 hits excluding 8/2/2024: {len(hits_sheet_logic)+1} total with 2/28")
hits_with_802_as_dn1 = [
    str(df.index[k].date())
    for k in range(s, i228 + 1)
    if g["ak"][k] and (int(ds[k]) == int(ds[i228]) if k != i802 else int(ds[k]) == 1)
]
# clearer: sheet AM on 2/28 counts AK true AND DN=12; 8/2 has DN=1 in sheet so excluded
hits_correct = [str(df.index[k].date()) for k in range(s, i228 + 1) if g["ak"][k] and int(ds[k]) == 12]
hits_sheet = [str(df.index[k].date()) for k in range(s, i228 + 1) if g["ak"][k] and int(ds[k]) == 12 and k != i802]
hits_sheet.append("2025-02-28") if g["ak"][i228] else None
print(f"  Engine wrong count (DN=12 incl 8/2): {hits_correct}")
print(f"  Sheet-equivalent (exclude 8/2 from DN=12): {[h for h in hits_correct if h != '2024-08-02']}")
