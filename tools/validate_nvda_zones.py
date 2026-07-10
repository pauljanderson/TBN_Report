"""Validate the engine's strong-pivot touch prices / matured zones for NVDA
against the STONK_DATA sheet ground truth, using the EXACT sheet parameters
(A1:C27).

Sheet touch (AF) = Final pivot (N/S) AND pre-strong (AD/AE) AND post-pullback,
so strong_pivot_mode must be "both".
"""
from __future__ import annotations

import sys
from dataclasses import asdict, replace
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))
sys.path.insert(0, str(_REPO / "tools"))

import numpy as np  # noqa: E402
from rocket_brt import (  # noqa: E402
    BRTConfig,
    build_level3_for_cfg,
    compute_pivots,
    load_csv,
    mts_sheet_parity_overrides,
)
from _nvda_matured_zone_gt import NVDA_MATURED_TOUCH as GT  # noqa: E402

# Exact sheet parameters A1:C27 for NVDA.
SHEET_PARAMS = dict(
    target_pct=1.22,            # C3 22%
    stop_pct=0.934,             # C4 6.6%
    band_pct=0.02,              # C5 2%
    touch_threshold=2,          # C6 touch points
    tight_range_threshold_pct=0.35,   # C7 35%
    level_acceptance_required=7,      # C8 close above low
    level_acceptance_window=10,       # C9 periods to check
    lookback_long=503,          # C10
    lookback_short=199,         # C11
    displacement_threshold_pct=0.09,  # C13 rolling avg displacement 9%
    strong_post_pivot_bars=7,   # C14
    strong_post_pivot_pct=0.09, # C15 9%
    breakout_bars=100,          # C16
    strong_pre_pivot_bars=7,    # C17
    strong_pre_pivot_pct=0.12,  # C18 12%
    pivot_disp=0.06,            # C21 pivot_future_move_pct
    pivot_k=4,                  # C23 pivot_local_window_bars
    tight_range_lookback=105,   # C24
    ath_filter_c25=0.3,         # C25
    ath_filter_c26=0.6,         # C26
    entry_close_min_range_position=0.00001,  # C27 midpoint fraction
)


def extract(cfg):
    df = load_csv(str(_REPO / "data" / "newdata" / "data" / "NVDA.csv"))
    ph, pl, php, plp = compute_pivots(df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m)
    l3 = build_level3_for_cfg(df, cfg, ph, pl, php, plp)
    tp = np.asarray(l3.get("touch_price"), dtype=float)
    dates = [str(d)[:10] for d in df.index]
    return [(dates[i], round(float(v), 2)) for i, v in enumerate(tp) if v == v and v > 0]


def compare(engine_touches, gt, tol=0.02):
    eng = [(d, v) for d, v in engine_touches]
    eng_vals = [v for _, v in eng]
    rem = list(eng_vals)
    matched, missing = 0, []
    for g in gt:
        best = None
        for e in rem:
            if abs(e - g) <= max(tol, g * tol) and (best is None or abs(e - g) < abs(best - g)):
                best = e
        if best is not None:
            rem.remove(best); matched += 1
        else:
            missing.append(g)
    print(f"engine touches={len(eng_vals)}  sheet={len(gt)}  matched={matched}  missing={len(missing)}  extra={len(rem)}")
    print(f"  MISSING sheet touches: {missing}")
    print(f"  EXTRA engine touches:  {sorted(rem)}")
    return matched


def main():
    base = asdict(BRTConfig())
    base.update(mts_sheet_parity_overrides())
    cfg = BRTConfig(**base)
    print("=== MTS sheet-parity preset (brt_sheet_touch + low touches) ===")
    compare(extract(cfg), GT)


if __name__ == "__main__":
    main()
