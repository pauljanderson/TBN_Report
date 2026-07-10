#!/usr/bin/env python3
"""Gate-by-gate AF test for 2019-09-25 vs 2019-10-03 pivot lows."""
from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb


def gate_trace(df, cfg, t: int) -> dict:
    n = len(df)
    hi = df["High"].to_numpy(float)
    lo = df["Low"].to_numpy(float)
    k = cfg.pivot_k
    post_bars = cfg.strong_post_pivot_bars
    disp = cfg.pivot_disp
    dedup = rb._PIVOT_DEDUP_EPS
    pre_bars = cfg.strong_pre_pivot_bars
    pre_pct = cfg.strong_pre_pivot_pct
    tp_bars = int(cfg.sheet_touch_pullback_bars or 10)
    c15 = cfg.strong_post_pivot_pct
    warmup = int(getattr(cfg, "brt_sheet_warmup_bars", 9) or 9)
    dec = cfg.zone_price_round_decimals

    def local_lo(tt):
        w0, w1 = max(0, tt - k), min(n, tt + k + 1)
        return bool(np.isclose(lo[tt], np.min(lo[w0:w1]), rtol=0, atol=1e-6))

    def local_hi(tt):
        w0, w1 = max(0, tt - k), min(n, tt + k + 1)
        return bool(np.isclose(hi[tt], np.max(hi[w0:w1]), rtol=0, atol=1e-6))

    def fut_rise(tt):
        if tt + post_bars >= n:
            return False, np.nan
        fut_max = float(np.max(hi[tt + 1 : tt + post_bars + 1]))
        return (fut_max / lo[tt] - 1.0) >= disp, fut_max

    def post_drop(tt):
        if tt + post_bars >= n:
            return False, np.nan
        fut_min = float(np.min(lo[tt + 1 : tt + post_bars + 1]))
        return (fut_min / hi[tt] - 1.0) <= -disp, fut_min

    rise_ok, fut_max = fut_rise(t)
    drop_ok, fut_min = post_drop(t)
    pre_hi = float(np.max(hi[max(0, t - pre_bars) : t])) if t > 0 else 0.0
    ae = pre_hi > 0 and (1.0 - lo[t] / pre_hi) >= pre_pct
    if t + tp_bars >= n:
        fwd_max, fwd_ok = np.nan, False
    else:
        fwd_max = float(np.max(hi[t + 1 : t + tp_bars + 1]))
        fwd_ok = (fwd_max / lo[t] - 1.0) >= c15

    tp = rb._round_zone_price(lo[t], dec) if dec >= 0 else lo[t]
    ce = rb._round_zone_price(tp * (1.0 - cfg.band_pct), dec)

    return {
        "warmup_ok": t >= warmup,
        "local_lo": local_lo(t),
        "local_hi": local_hi(t),
        "fut_rise_ok": rise_ok,
        "fut_max": fut_max,
        "disp_need": disp,
        "post_drop_ok": drop_ok,
        "pre_hi": pre_hi,
        "ae_ok": ae,
        "pre_pct_need": pre_pct,
        "fwd_max": fwd_max,
        "fwd_ok": fwd_ok,
        "c15_need": c15,
        "tp_bars": tp_bars,
        "tp": tp,
        "ce": ce,
    }


def main() -> None:
    base = asdict(rb.BRTConfig())
    base.update(rb.mts_sheet_parity_overrides())
    cfg = rb.BRTConfig(**base)
    df = rb.load_csv(str(_REPO / "data" / "newdata" / "data" / "TSLA.csv"))
    dates = df.index.strftime("%Y-%m-%d").tolist()

    for d in ["2019-09-25", "2019-10-03", "2019-09-27"]:
        t = dates.index(d)
        g = gate_trace(df, cfg, t)
        print(f"\n=== {d} H={df['High'].iloc[t]:.2f} L={df['Low'].iloc[t]:.2f} ===")
        for k, v in g.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
