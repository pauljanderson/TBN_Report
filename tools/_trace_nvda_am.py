#!/usr/bin/env python3
"""NVDA 5/27 vs 6/2: why engine BI early; verify AM/AQ/BG/DP pending."""
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb


def am_detail(i, ak, dn, am_win, c6):
    s = max(0, i - am_win)
    hits = [(k, dn[k]) for k in range(s, i + 1) if ak[k] and np.isfinite(dn[k]) and dn[k] == dn[i]]
    return hits


base = asdict(rb.BRTConfig())
base.update(rb.mts_sheet_parity_overrides())
cfg = rb.BRTConfig(**base)
df = rb.load_csv(str(_REPO / "data/newdata/data/NVDA.csv"))
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

for d in ["2025-05-23", "2025-05-27", "2025-05-28", "2025-05-30", "2025-06-02"]:
    i = df.index.get_loc(pd.Timestamp(d))
    hits = am_detail(i, g["ak"], ds, am_win, c6)
    print(f"\n=== {d} DN={int(ds[i])} ===")
    print(f"AK={int(g['ak'][i])} AM={int(g['am'][i])} AQ={int(g['aq'][i])} DP={int(dp[i])}")
    print(f"AM window AK hits with DN={int(ds[i])}: {len(hits)} (need {c6})")
    for k, dn in hits[-5:]:
        print(f"  bar {df.index[k].date()} AK=1 DN={int(dn)}")
    print(
        f"BG={int(g['bg'][i])} BC={int(g['bc'][i])} BC[-1]={int(g['bc'][i-1])} "
        f"BE={int(g['be'][i])} BI={int(g['bi'][i])}"
    )

# Test alternate BG: require AK[-1] zone DN == current DN
print("\n=== Alternate BG: AK[-1] only counts if dn[i-1]==dn[i] ===")
for d in ["2025-05-27", "2025-06-02"]:
    i = df.index.get_loc(pd.Timestamp(d))
    akt = g["ak"][i]
    aky = g["ak"][i - 1] and ds[i - 1] == ds[i]
    print(f"{d}: AK={akt} AK[-1]_sameDN={aky} => BG_alt would use OR={akt or aky}")

# Run backtest snippet for trade dates
trades = rb.run_brt_backtest(df, cfg, symbol="NVDA")
mts = [t for t in trades if getattr(t, "strategy", "") == "MTS" or "mts" in str(getattr(t, "entry_reason", "")).lower()]
print("\nNVDA MTS trades near Jun 2025:")
for t in trades:
    do = str(getattr(t, "date_opened", ""))
    if "202505" in do or "202506" in do:
        print(f"  opened {do} @ {getattr(t,'entry_price',0):.2f} trig={getattr(t,'close_above_date','')}")
