#!/usr/bin/env python3
"""TSLA 10/09 and 2/28 gate deep-dive (why sheet skips BI)."""
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb

base = asdict(rb.BRTConfig())
base.update(rb.mts_sheet_parity_overrides())
cfg = rb.BRTConfig(**base)
df = rb.load_csv(str(_REPO / "data/newdata/data/TSLA.csv"))
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
de, dfa, dg, ds = rb._precompute_sheet_active_zone_arrays(h, lo, mbh, mbi, n, cfg)
g = rb._precompute_mts_bi_gates(o, h, lo, c, de, dfa, dg, ds, mbh, mbi, n, cfg)
am_win = max(1, int(getattr(cfg, "mts_support_evidence_window_bars", 0) or 0) or cfg.lookback_long)
c6 = int(cfg.touch_threshold)

_do = np.zeros(n, dtype=bool)
for i in range(n):
    if np.isfinite(ds[i]) and (not np.isfinite(dg[i]) or i > dg[i]):
        _do[i] = True
dp = np.zeros(n, dtype=bool)
for i in range(n):
    if _do[i] and (i == 0 or not _do[i - 1] or ds[i] != ds[i - 1]):
        dp[i] = True


def detail(d: str) -> None:
    i = df.index.get_loc(pd.Timestamp(d))
    s = max(0, i - am_win)
    ak_hits = [df.index[k].date() for k in range(s, i + 1) if g["ak"][k] and ds[k] == ds[i]]
    print(f"\n=== {d} ===")
    print(f"OHLC {o[i]:.2f}/{h[i]:.2f}/{lo[i]:.2f}/{c[i]:.2f}")
    print(f"Zone DN={int(ds[i])} DK={de[i]:.4f} DL={dfa[i]:.4f} DM={int(dg[i])}")
    print(f"DO={int(_do[i])} DP={int(dp[i])} DN[-1]={int(ds[i-1]) if i else -1}")
    print(
        f"AK={int(g['ak'][i])} AM={int(g['am'][i])} ({len(ak_hits)} AK w/same DN, need {c6})"
    )
    if ak_hits:
        print(f"  AK same-DN hits: {ak_hits[-5:]}")
    print(
        f"AR={int(g['ar'][i])} AW={int(g['aw'][i])} BC={int(g['bc'][i])} BC[-1]={int(g['bc'][i-1])}"
    )
    akt = g["ak"][i]
    aky = g["ak"][i - 1] if i else False
    anchor = de[i] if akt else de[i - 1]
    s2 = max(0, i - 9)
    cnt = int(np.sum(c[s2 : i + 1] > anchor))
    print(
        f"BG: AK|AK[-1]={akt}|{aky} anchor={anchor:.4f} count={cnt} => BG={int(g['bg'][i])}"
    )
    bc_ok = g["bc"][i] or g["bc"][i - 1]
    aq_ok = g["aq"][i] or g["aq"][i - 1]
    print(
        f"BW={int(g['bw'][i])} BE={int(g['be'][i])} BC_ok={bc_ok} AQ_ok={aq_ok} BI={int(g['bi'][i])}"
    )


for d in ["2019-10-07", "2019-10-08", "2019-10-09", "2019-10-10", "2019-10-21", "2019-10-22"]:
    detail(d)

print("\n" + "=" * 60)
for d in ["2025-02-26", "2025-02-27", "2025-02-28", "2025-03-03", "2025-03-04"]:
    detail(d)
