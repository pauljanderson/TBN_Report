#!/usr/bin/env python3
"""Test BG: AK[-1] cross-zone allowed only when AW[i]=False."""
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb

SYMS = ["AAPL", "AMZN", "META", "GOOGL", "MSFT", "NFLX", "NVDA", "TSLA"]
KEY = {
    "NFLX": ["2019-10-14", "2019-10-21"],
    "NVDA": ["2025-05-27", "2025-06-02"],
    "TSLA": ["2019-10-09", "2019-10-22", "2025-02-28", "2025-03-04"],
}


def gates(df, cfg):
    n = len(df)
    o, h, lo, c = [df[x].to_numpy(float) for x in ["Open", "High", "Low", "Close"]]
    ph, pl, php, plp = rb.compute_pivots(
        df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
        realtime_filter_enabled=cfg.realtime_filter_enabled,
    )
    l3 = rb.build_level3_for_cfg(df, cfg, ph, pl, php, plp)
    mbh, mbi = rb._precompute_mat_bh_bi_stream(
        l3["zone_low"].to_numpy(float), l3["zone_high"].to_numpy(float), 7, n
    )
    de, dfa, dg, ds = rb._precompute_sheet_active_zone_arrays(h, lo, mbh, mbi, n, cfg)
    g = rb._precompute_mts_bi_gates(o, h, lo, c, de, dfa, dg, ds, mbh, mbi, n, cfg)
    la_req = int(cfg.level_acceptance_required)
    la_win = int(cfg.level_acceptance_window)
    bi_alt = np.zeros(n, dtype=bool)
    for i in range(n):
        akt = g["ak"][i]
        aky = False
        if i >= 1 and g["ak"][i - 1]:
            if ds[i - 1] == ds[i] or not g["aw"][i]:
                aky = True
        if akt or aky:
            anchor = de[i] if akt else de[i - 1]
            s = max(0, i - (la_win - 1))
            bg = int(np.sum(c[s : i + 1] > anchor)) >= la_req
        else:
            bg = False
        bc_ok = g["bc"][i] or (g["bc"][i - 1] if i >= 1 else False)
        aq_ok = g["aq"][i] or (g["aq"][i - 1] if i >= 1 else False)
        if g["bw"][i] and bc_ok and g["be"][i] and bg and aq_ok:
            bi_alt[i] = True
    return g["bi"], bi_alt


base = asdict(rb.BRTConfig())
base.update(rb.mts_sheet_parity_overrides())
cfg = rb.BRTConfig(**base)

for sym, dates in KEY.items():
    df = rb.load_csv(str(_REPO / "data" / "newdata" / "data" / f"{sym}.csv"))
    bi, alt = gates(df, cfg)
    print(f"\n{sym} (cross-zone AK[-1] blocked when AW=1):")
    for d in dates:
        i = df.index.get_loc(pd.Timestamp(d))
        print(f"  {d}: BI={int(bi[i])} alt={int(alt[i])}")

print("\n=== BI diffs per symbol ===")
for sym in SYMS:
    df = rb.load_csv(str(_REPO / "data" / "newdata" / "data" / f"{sym}.csv"))
    bi, alt = gates(df, cfg)
    print(f"  {sym}: {int(np.sum(bi != alt))} bars differ")
