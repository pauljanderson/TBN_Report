#!/usr/bin/env python3
"""Validate: null the 3 phantom zone-creation bars -> re-run NVDA MTS parity."""
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path
import numpy as np

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb

base = asdict(rb.BRTConfig())
base.update(rb.mts_sheet_parity_overrides())
cfg = rb.BRTConfig(**base)
dd = _REPO / "data" / "newdata" / "data"
df = rb.load_csv(str(dd / "NVDA.csv"))
ph, pl, php, plp = rb.compute_pivots(
    df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
    realtime_filter_enabled=cfg.realtime_filter_enabled,
)
struct = rb.compute_market_structure(df, ph, pl, php, plp)
l3 = rb.build_level3_for_cfg(df, cfg, ph, pl, php, plp)

# Null the 3 phantom creation bars so they never mature.
PHANTOM_BARS = [276, 858, 1448]
for key in ("touch_price", "zone_center", "zone_low", "zone_high"):
    s = l3[key]
    for b in PHANTOM_BARS:
        s.iloc[b] = np.nan
if "zone_touch_origin" in l3:
    for b in PHANTOM_BARS:
        l3["zone_touch_origin"].iloc[b] = 0

closed, *_ = rb.run_brt_backtest(
    "NVDA", df, cfg, php, plp, struct, l3, benchmark_df=rb._load_benchmark_local(dd)
)
print("Trades after nulling 3 phantom zones:")
for i, t in enumerate(sorted(closed, key=lambda x: x.date_opened), 1):
    print(f"{i:2d} open {t.date_opened} @ {t.entry_price:8.2f}  close {t.date_closed} pnl {t.pnl_pct:+7.2f}%  {t.exit_type}")
print(f"\nTotal closed: {len(closed)} (sheet reference: 18)")
