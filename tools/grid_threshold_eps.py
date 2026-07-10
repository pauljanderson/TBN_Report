#!/usr/bin/env python3
"""Grid-test tiny threshold epsilons (pre-pivot% / post-pivot%) for NVDA parity."""
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
dd = _REPO / "data" / "newdata" / "data"

def ymd(s):
    s = str(s).replace("-", "")[:8]
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))

def run(pre_pct, post_pct):
    base = asdict(rb.BRTConfig())
    base.update(rb.mts_sheet_parity_overrides())
    base["strong_pre_pivot_pct"] = pre_pct
    base["strong_post_pivot_pct"] = post_pct
    cfg = rb.BRTConfig(**base)
    df = rb.load_csv(str(dd / "NVDA.csv"))
    ph, pl, php, plp = rb.compute_pivots(
        df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
        realtime_filter_enabled=cfg.realtime_filter_enabled,
    )
    struct = rb.compute_market_structure(df, ph, pl, php, plp)
    l3 = rb.build_level3_for_cfg(df, cfg, ph, pl, php, plp)
    closed, *_ = rb.run_brt_backtest("NVDA", df, cfg, php, plp, struct, l3,
                                     benchmark_df=rb._load_benchmark_local(dd))
    entries = sorted(ymd(t.date_opened) for t in closed)
    matched = sum(1 for se in SHEET_ENTRIES if any(abs((e - se).days) <= 5 for e in entries))
    return len(entries), matched, len(entries) - matched

print(f"{'pre%':>6} {'post%':>6} | {'trades':>6} {'matched/18':>10} {'extras':>6}")
for pre in (0.120, 0.121, 0.122):
    for post in (0.090, 0.091, 0.092):
        tot, m, ex = run(pre, post)
        print(f"{pre:>6.3f} {post:>6.3f} | {tot:>6} {m:>10} {ex:>6}")
