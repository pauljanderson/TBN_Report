#!/usr/bin/env python3
"""Trace BI/DP sheet formulas vs engine for TSLA Dec 2021."""
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb

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
o, h, lo, c = [df[x].to_numpy(float) for x in "Open High Low Close".split()]
mbh, mbi = rb._precompute_mat_bh_bi_stream(
    l3["zone_low"].to_numpy(float), l3["zone_high"].to_numpy(float), 7, n
)
de, dfa, dg, ds = rb._precompute_sheet_active_zone_arrays(h, lo, mbh, mbi, n, cfg)
g = rb._precompute_mts_bi_gates(o, h, lo, c, de, dfa, dg, ds, mbh, mbi, n, cfg)

_do = np.zeros(n, dtype=bool)
for i in range(n):
    if np.isfinite(ds[i]) and (not np.isfinite(dg[i]) or i > dg[i]):
        _do[i] = True

dp = np.zeros(n, dtype=bool)
for i in range(n):
    if not _do[i]:
        continue
    if i == 0 or not _do[i - 1] or ds[i] != ds[i - 1]:
        dp[i] = True

c7 = float(cfg.tight_range_threshold_pct)
c24 = int(cfg.tight_range_lookback)
bc_raw = np.zeros(n, dtype=bool)
for i in range(n):
    s = i - c24 - 1
    if s < 0:
        continue
    wl = float(np.min(lo[s : i + 1]))
    wh = float(np.max(h[s : i + 1]))
    if wl > 0 and (wh / wl - 1.0) > c7:
        bc_raw[i] = True

bw_slack = np.zeros(n, dtype=bool)
for i in range(n):
    ago = rb._growth_ago_bar_index(i, cfg)
    if ago >= 0 and c[i] >= c[ago]:
        bw_slack[i] = True


def bi_from_parts(i, bc_arr, bw_arr):
    bc_ok = bc_arr[i] or (bc_arr[i - 1] if i >= 1 else False)
    aq_ok = g["aq"][i] or (g["aq"][i - 1] if i >= 1 else False)
    return bool(bw_arr[i] and bc_ok and g["be"][i] and g["bg"][i] and aq_ok)


print("date       row  DN  DO   DP   AW   BC  BC-1  bcR bcR-1  BW  BWs BE  BG  AQ  AQ-1  BI  BIw  BIr")
for d in (
    "2021-12-15", "2021-12-16", "2021-12-17", "2021-12-20",
    "2021-12-21", "2021-12-22", "2021-12-23",
):
    i = df.index.get_loc(d)
    row = i + 2  # sheet row if D2=first bar
    print(
        f"{d} {row:4d} {int(ds[i]):3d} "
        f"{int(_do[i])}   {int(dp[i])}   "
        f"{int(g['aw'][i])}   {int(g['bc'][i])}   {int(g['bc'][i-1]) if i else 0}    "
        f"{int(bc_raw[i])}   {int(bc_raw[i-1]) if i else 0}    "
        f"{int(g['bw'][i])}   {int(bw_slack[i])}  "
        f"{int(g['be'][i])}   {int(g['bg'][i])}   "
        f"{int(g['aq'][i])}   {int(g['aq'][i-1]) if i else 0}    "
        f"{int(g['bi'][i])}   {int(bi_from_parts(i, g['bc'], bw_slack))}   "
        f"{int(bi_from_parts(i, bc_raw, g['bw']))}"
    )

print("\n12/21 sheet BI formula check (row 1505):")
i = df.index.get_loc("2021-12-21")
parts = {
    "BW": bool(g["bw"][i]),
    "BW_slack": bool(bw_slack[i]),
    "OR_BC": bool(g["bc"][i] or g["bc"][i - 1]),
    "OR_BC_raw": bool(bc_raw[i] or bc_raw[i - 1]),
    "BE": bool(g["be"][i]),
    "BG": bool(g["bg"][i]),
    "OR_AQ": bool(g["aq"][i] or g["aq"][i - 1]),
    "DP": bool(dp[i]),
    "DO": bool(_do[i]),
    "DO_prev": bool(_do[i - 1]),
    "DN_change": ds[i] != ds[i - 1],
}
for k, v in parts.items():
    print(f"  {k}={v}")
