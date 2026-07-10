#!/usr/bin/env python3
"""Grid-test AM threshold (2 vs 3) x phantom-removal for NVDA MTS parity."""
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path
import numpy as np

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb

SHEET_ENTRIES = [
    date(2019,4,29), date(2019,6,4), date(2019,9,17), date(2020,3,18), date(2021,5,11),
    date(2022,3,8), date(2022,4,13), date(2022,5,25), date(2022,6,14), date(2022,7,8),
    date(2022,8,8), date(2022,10,25), date(2023,1,31), date(2023,5,5), date(2024,8,8),
    date(2025,1,28), date(2025,3,14), date(2025,6,2),
]
PHANTOM_BARS = [276, 858, 1448]
dd = _REPO / "data" / "newdata" / "data"

def ymd(s):
    s = str(s).replace("-", "")[:8]
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))

def run(am_min, remove_phantom):
    base = asdict(rb.BRTConfig())
    base.update(rb.mts_sheet_parity_overrides())
    base["mts_support_evidence_min"] = am_min
    cfg = rb.BRTConfig(**base)
    df = rb.load_csv(str(dd / "NVDA.csv"))
    ph, pl, php, plp = rb.compute_pivots(
        df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
        realtime_filter_enabled=cfg.realtime_filter_enabled,
    )
    struct = rb.compute_market_structure(df, ph, pl, php, plp)
    l3 = rb.build_level3_for_cfg(df, cfg, ph, pl, php, plp)
    if remove_phantom:
        for key in ("touch_price", "zone_center", "zone_low", "zone_high"):
            for b in PHANTOM_BARS:
                l3[key].iloc[b] = np.nan
        for b in PHANTOM_BARS:
            l3["zone_touch_origin"].iloc[b] = 0
    closed, *_ = rb.run_brt_backtest("NVDA", df, cfg, php, plp, struct, l3,
                                     benchmark_df=rb._load_benchmark_local(dd))
    entries = sorted(ymd(t.date_opened) for t in closed)
    # count matches within +/-3 trading-ish days
    matched = 0
    for se in SHEET_ENTRIES:
        if any(abs((e - se).days) <= 5 for e in entries):
            matched += 1
    extras = len(entries) - matched
    return len(entries), matched, extras

print(f"{'am_min':>6} {'phantom':>8} | {'trades':>6} {'matched/18':>10} {'extras':>6}")
for am_min in (2, 3):
    for rp in (False, True):
        tot, m, ex = run(am_min, rp)
        print(f"{am_min:>6} {str(rp):>8} | {tot:>6} {m:>10} {ex:>6}")
