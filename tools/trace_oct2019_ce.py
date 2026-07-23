#!/usr/bin/env python3
"""Trace Oct 2019 touch/CE divergence (14.27 vs 14.52)."""
from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb


def main() -> None:
    base = asdict(rb.BRTConfig())
    base.update(rb.mts_sheet_parity_overrides())
    cfg = rb.BRTConfig(**base)
    df = rb.load_csv(str(_REPO / "data" / "newdata" / "data" / "TSLA.csv"))
    dates = df.index.astype(str).tolist() if hasattr(df.index, "astype") else list(range(len(df)))

    ph, pl, php, plp = rb.compute_pivots(
        df,
        cfg.pivot_k,
        cfg.pivot_d,
        cfg.pivot_disp,
        cfg.pivot_m,
        realtime_filter_enabled=cfg.realtime_filter_enabled,
    )
    l3 = rb.build_level3_for_cfg(df, cfg, ph, pl, php, plp)
    mbh = l3["zone_low"].to_numpy(float)

    lag = rb._effective_sheet_maturity_lag_bars(cfg)
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
        touch_pullback_bars=int(cfg.strong_post_pivot_bars or 7),
        maturity_lag=lag,
        warmup_bars=int(getattr(cfg, "brt_sheet_warmup_bars", 9) or 9),
        zone_price_round_decimals=cfg.zone_price_round_decimals,
        lookback_long=cfg.lookback_long,
        lookback_short=cfg.lookback_short,
        touch_threshold=cfg.touch_threshold,
        include_pivot_low_touches=bool(cfg.mts_zone_low_touches),
    )
    tp = touch["touch_price"].to_numpy(float)
    mat = touch["matured"].to_numpy(bool) if "matured" in touch else None

    print("cfg: touch_pullback_bars=", cfg.strong_post_pivot_bars, "C15=", cfg.strong_post_pivot_pct)
    print(f"{'date':12} {'H':>7} {'L':>7} {'ph':5} {'pl':5} {'AF':>8} {'CE':>8} {'mat':5}")
    for i, d in enumerate(dates):
        if d < "2019-09-20" or d > "2019-10-15":
            continue
        ce = mbh[i]
        ce_s = f"{ce:.2f}" if np.isfinite(ce) and ce > 0 else ""
        af = tp[i]
        af_s = f"{af:.2f}" if np.isfinite(af) else ""
        m = ""
        if mat is not None and mat[i]:
            m = "Y"
        print(
            f"{d:12} {df['High'].iloc[i]:7.2f} {df['Low'].iloc[i]:7.2f} "
            f"{int(ph[i]):5} {int(pl[i]):5} {af_s:>8} {ce_s:>8} {m:5}"
        )

    print("\nAll matured events Sep-Oct 2019:")
    for ev in touch.get("brt_matured_events", []):
        t = ev["maturity_bar"]
        p = ev["pivot_bar"]
        if dates[p] >= "2019-08-01" and dates[t] <= "2019-11-01":
            print(
                f"  pivot {dates[p]} AF={ev['touch_price']:.4f} "
                f"-> CE={ev['zone_lower']:.4f} on {dates[t]}"
            )


if __name__ == "__main__":
    main()
