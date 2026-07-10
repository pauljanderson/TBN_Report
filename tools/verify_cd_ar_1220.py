#!/usr/bin/env python3
"""Compare CD streams and AR count for TSLA 2021-12-20 (row 1504)."""
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
n = len(df)
ph, pl, php, plp = rb.compute_pivots(
    df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
    realtime_filter_enabled=cfg.realtime_filter_enabled,
)
l3 = rb.build_level3_for_cfg(df, cfg, ph, pl, php, plp)
h, lo, c = df["High"].to_numpy(float), df["Low"].to_numpy(float), df["Close"].to_numpy(float)
zl = l3["zone_low"].to_numpy(float)
zh = l3["zone_high"].to_numpy(float)
tp = l3["touch_price"].to_numpy(float)
lag = max(0, int(rb._effective_sheet_maturity_lag_bars(cfg)))
mbh, mbi = rb._precompute_mat_bh_bi_stream(zl, zh, lag, n)
de, dfa, dg, ds = rb._precompute_sheet_active_zone_arrays(h, lo, mbh, mbi, n, cfg)

c5 = cfg.band_pct
# Engine CD in bi_gates: CE/(1-C5) where CE=mbh
cd_ce = np.where(np.isfinite(mbh) & (mbh > 0), mbh / (1.0 - c5), np.nan)
# Sheet CD = INDEX(AF, ROW()-C14): touch price at lag bar on row i
cd_af = np.full(n, np.nan)
for i in range(n):
    j = i - lag
    if j >= 0 and np.isfinite(tp[j]) and tp[j] > 0:
        cd_af[i] = tp[j]

i = df.index.get_loc("2021-12-20")
dk, dl = de[i], dfa[i]
c10 = int(cfg.lookback_long)
s = max(0, i - c10)

print(f"12/20 row {i+2}: DK={dk:.2f} DL={dl:.2f} DM={int(dg[i])+2} DN={int(ds[i])}")
print(f"Sheet formula AR window: rows {s+2}..{i+2} ({i-s+1} bars)\n")

def count_hits(cd, label):
    hits = []
    for k in range(s, i + 1):
        if np.isfinite(cd[k]) and cd[k] >= dk and cd[k] <= dl:
            hits.append((k + 2, str(df.index[k].date()), round(cd[k], 4), round(mbh[k], 4) if np.isfinite(mbh[k]) else None))
    print(f"{label}: AR={len(hits)}")
    for h in hits:
        print(f"  sheet_row={h[0]} date={h[1]} CD={h[2]} CE={h[3]}")
    return hits

count_hits(cd_ce, "CD from CE/(1-C5) [current engine]")
count_hits(cd_af, "CD from INDEX(AF,ROW()-C14) [touch_price lag]")

# Diff: rows where cd_af in band but cd_ce not
print("\nIn band for cd_af only:")
for k in range(s, i + 1):
    a = np.isfinite(cd_af[k]) and dk <= cd_af[k] <= dl
    b = np.isfinite(cd_ce[k]) and dk <= cd_ce[k] <= dl
    if a and not b:
        print(f"  row{k+2} cd_af={cd_af[k]:.4f} cd_ce={cd_ce[k]} tp={tp[k-lag] if k>=lag else None} zl={zl[k-lag] if k>=lag else None}")

# All maturities CE 283-305 in window
print("\nAll CE (mbh) in window with CD values:")
for k in range(s, i + 1):
    if np.isfinite(mbh[k]):
        cdv = mbh[k] / (1 - c5)
        print(f"  row{k+2} {df.index[k].date()} CE={mbh[k]:.2f} CD={cdv:.2f} in_band={dk<=cdv<=dl if np.isfinite(dk) else False}")

# Verify DM: sheet MAX(FILTER(ROW(CE)...)) vs engine dg
print(f"\nEngine DM bar index dg={int(dg[i])} sheet_row={int(dg[i])+2}")
print(f"Engine DK=CE[dg]={mbh[int(dg[i])]:.2f} (should match {dk:.2f})")
