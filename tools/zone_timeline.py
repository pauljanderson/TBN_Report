#!/usr/bin/env python3
"""Chronological zone stream with pivot dates for gap analysis."""
from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb

GT = _REPO / "sheet_ce_ground_truth"


def zone_timeline(sym: str, lo: int = 0, hi: int = 999) -> None:
    base = asdict(rb.BRTConfig())
    base.update(rb.mts_sheet_parity_overrides())
    cfg = rb.BRTConfig(**base)
    lag = rb._effective_sheet_maturity_lag_bars(cfg)
    df = rb.load_csv(str(_REPO / "data" / "newdata" / "data" / f"{sym}.csv"))
    dates = df.index.strftime("%Y-%m-%d").tolist()
    touch = rb.compute_sheet_brt_touch_stream(
        df,
        band_pct=cfg.band_pct,
        pivot_local_window=cfg.pivot_k,
        post_pivot_bars=cfg.strong_post_pivot_bars,
        pivot_future_move_pct=cfg.pivot_disp,
        dedup_tol_pct=rb._PIVOT_DEDUP_EPS,
        pre_pivot_bars=cfg.strong_pre_pivot_bars,
        pre_pivot_pct=cfg.strong_pre_pivot_pct,
        touch_pullback_pct=cfg.strong_post_pivot_pct,
        touch_pullback_bars=int(cfg.sheet_touch_pullback_bars or 10),
        maturity_lag=lag,
        warmup_bars=9,
        zone_price_round_decimals=cfg.zone_price_round_decimals,
        lookback_long=cfg.lookback_long,
        lookback_short=cfg.lookback_short,
        touch_threshold=cfg.touch_threshold,
        include_pivot_low_touches=bool(cfg.mts_zone_low_touches),
    )
    tp = touch["touch_price"].to_numpy(float)
    l3 = rb.build_level3_for_cfg(
        df, cfg,
        *rb.compute_pivots(
            df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
            realtime_filter_enabled=cfg.realtime_filter_enabled,
        ),
    )
    zl = l3["zone_low"].to_numpy(float)
    sheet = [float(x) for x in (GT / f"{sym}_ce.txt").read_text().splitlines() if x.strip()]

    prev = None
    n = 0
    print(f"\n{sym} zone timeline (sheet vs engine):")
    for i, d in enumerate(dates):
        v = zl[i]
        if not (np.isfinite(v) and v > 0 and v != prev):
            continue
        n += 1
        if n - 1 < lo or n - 1 > hi:
            prev = v
            continue
        p = i - lag
        af = float(tp[p]) if p >= 0 and np.isfinite(tp[p]) else float("nan")
        sh = sheet[n - 1] if n - 1 < len(sheet) else float("nan")
        flag = "" if abs(v - sh) < 0.001 else f"  <-- MISMATCH sheet={sh:.2f}"
        piv = dates[p] if 0 <= p < len(dates) else "?"
        h = float(df["High"].iloc[p]) if 0 <= p < len(df) else float("nan")
        print(f"  #{n:2d} pivot={piv} AF={af:.2f} H={h:.4f}  mature={d}  eng_zl={v:.2f}{flag}")
        prev = v


if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "NFLX"
    lo = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    hi = int(sys.argv[3]) if len(sys.argv) > 3 else 18
    zone_timeline(sym, lo, hi)
