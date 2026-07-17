"""Volume + prior-period extreme confluence zones (VEC system).

Produces resistance-style zones where rolling volume POC aligns with a prior-period
high (default: prior week). Zones feed the same BH/BI → DI breakout → BY retest entry
pipeline as YH/BRT in rocket_brt.py.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def _typical_price(high: float, low: float, close: float) -> float:
    return (float(high) + float(low) + float(close)) / 3.0


def compute_volume_poc(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    end_bar: int,
    lookback: int,
    bin_pct: float,
) -> float:
    """Point-in-time POC over ``[end_bar - lookback + 1, end_bar]`` inclusive."""
    lb = max(1, int(lookback))
    start = max(0, int(end_bar) - lb + 1)
    end = int(end_bar) + 1
    if start >= end:
        return float("nan")

    seg_hi = high[start:end]
    seg_lo = low[start:end]
    seg_cl = close[start:end]
    seg_vol = volume[start:end]
    mask = np.isfinite(seg_vol) & (seg_vol > 0)
    if not np.any(mask):
        return float("nan")

    tp = (seg_hi + seg_lo + seg_cl) / 3.0
    tp = tp[mask]
    vol = seg_vol[mask]
    ref = float(np.nanmedian(tp))
    if not (np.isfinite(ref) and ref > 0):
        return float("nan")

    bp = max(1e-6, float(bin_pct))
    bin_w = ref * bp
    lo_edge = float(np.min(tp))
    hi_edge = float(np.max(tp))
    if hi_edge <= lo_edge:
        return float(tp[np.argmax(vol)])

    n_bins = max(1, int(np.ceil((hi_edge - lo_edge) / bin_w)) + 1)
    hist = np.zeros(n_bins, dtype=np.float64)
    for price, v in zip(tp, vol):
        idx = int((float(price) - lo_edge) / bin_w)
        idx = min(max(idx, 0), n_bins - 1)
        hist[idx] += float(v)
    best = int(np.argmax(hist))
    return float(lo_edge + (best + 0.5) * bin_w)


def prior_period_extreme(
    high: np.ndarray,
    low: np.ndarray,
    end_bar: int,
    prior_bars: int,
    side: str = "high",
) -> float:
    """Prior-period extreme ending the bar before ``end_bar`` (exclusive of current bar)."""
    pb = max(1, int(prior_bars))
    end = int(end_bar)
    start = max(0, end - pb)
    if start >= end:
        return float("nan")
    if str(side).strip().lower() == "low":
        return float(np.min(low[start:end]))
    return float(np.max(high[start:end]))


def compute_vec_touch_stream(
    df: pd.DataFrame,
    band_pct: float,
    lookback_long: int,
    touch_threshold: int,
    lookback_short: int = 105,
    *,
    band_pct_atr: float = 0.0,
    zone_price_round_decimals: int = 2,
    vec_vp_lookback: int = 60,
    vec_vp_bin_pct: float = 0.005,
    vec_prior_bars: int = 5,
    vec_prior_side: str = "high",
    vec_confluence_pct: float = 0.0075,
    vec_move_away_pct: float = 0.02,
    vec_min_bars_between: int = 20,
    debug_symbol: Optional[str] = None,
    effective_band_pct_fn=None,
    round_zone_price_fn=None,
    compute_atr_14_fn=None,
) -> dict:
    """
    Build VEC zones: confluence of volume POC and prior-period extreme.

    Activation:
    - ``vec_move_away_pct > 0``: zone activates when High crosses center×(1+pct) after confluence.
    - ``vec_move_away_pct == 0``: activates on the confluence bar.

    Returns the same level3 keys as ``compute_yh_touch_stream``; events live in
    ``yh_zone_events`` with ``origin=4`` for DI/retest parity.
    """
    n = len(df)
    hi_raw = np.asarray(df["High"].values, dtype=np.float64)
    lo_arr = np.asarray(df["Low"].values, dtype=np.float64)
    close_arr = np.asarray(df["Close"].values, dtype=np.float64)
    vol_arr = np.asarray(df["Volume"].values, dtype=np.float64)

    if compute_atr_14_fn is not None:
        atr_14_arr = compute_atr_14_fn(hi_raw, lo_arr, close_arr, 14)
    else:
        atr_14_arr = np.full(n, np.nan, dtype=np.float64)

    _dec = int(zone_price_round_decimals)
    _rnd = round_zone_price_fn or (lambda x, d: round(float(x), max(0, d)))
    _band = effective_band_pct_fn or (lambda tp, bar, atr, bp, bpa: float(bp))

    tp_arr = np.full(n, np.nan, dtype=np.float64)
    origin_arr = np.zeros(n, dtype=np.int8)
    zc_arr = np.full(n, np.nan, dtype=np.float64)
    zl_arr = np.full(n, np.nan, dtype=np.float64)
    zh_arr = np.full(n, np.nan, dtype=np.float64)
    matured_arr = np.zeros(n, dtype=bool)
    zone_events: list[dict] = []

    vp_lb = max(5, int(vec_vp_lookback))
    prior_bars = max(1, int(vec_prior_bars))
    conf_pct = max(0.0, float(vec_confluence_pct))
    move_pct = max(0.0, float(vec_move_away_pct))
    min_gap = max(0, int(vec_min_bars_between))
    prior_side = str(vec_prior_side or "high").strip().lower()
    warmup = max(vp_lb, prior_bars) + 1

    pending: Optional[dict] = None
    last_activation_bar = -10_000
    last_center = float("nan")

    for t in range(warmup, n):
        poc = compute_volume_poc(
            hi_raw, lo_arr, close_arr, vol_arr, t, vp_lb, float(vec_vp_bin_pct)
        )
        ext = prior_period_extreme(hi_raw, lo_arr, t, prior_bars, prior_side)
        if not (np.isfinite(poc) and np.isfinite(ext) and ext > 0):
            continue

        dist_pct = abs(float(poc) - float(ext)) / float(ext)
        if dist_pct > conf_pct:
            pending = None
            continue

        center = _rnd((float(poc) + float(ext)) / 2.0, _dec)
        if center <= 0:
            continue

        if pending is not None and abs(float(pending["center"]) - center) / center <= conf_pct:
            cand = pending
        else:
            cand = {
                "confluence_bar": int(t),
                "center": float(center),
                "poc": float(poc),
                "extreme": float(ext),
                "dist_pct": float(dist_pct),
                "activated": False,
            }
            pending = cand

        if cand["activated"]:
            continue

        activate_now = move_pct <= 0.0 or float(hi_raw[t]) >= float(center) * (1.0 + move_pct)
        if not activate_now:
            continue

        if min_gap > 0 and (t - last_activation_bar) < min_gap:
            if np.isfinite(last_center) and abs(center - last_center) / center <= conf_pct:
                continue

        _bp_i = _band(float(center), int(t), atr_14_arr, band_pct, band_pct_atr)
        zl = _rnd(float(center) * (1.0 - _bp_i), _dec)
        zh = _rnd(float(center) * (1.0 + _bp_i), _dec)
        act_px = _rnd(float(center) * (1.0 + move_pct), _dec) if move_pct > 0 else float(center)

        zone_events.append(
            {
                "yh_bar": int(cand["confluence_bar"]),
                "activation_bar": int(t),
                "touch_price": float(center),
                "zone_center": float(center),
                "zone_lower": zl,
                "zone_upper": zh,
                "activation_price": float(act_px),
                "origin": 4,
                "vec_poc": float(cand["poc"]),
                "vec_prior_extreme": float(cand["extreme"]),
                "vec_confluence_dist_pct": float(cand["dist_pct"]),
            }
        )
        cand["activated"] = True
        matured_arr[t] = True
        tp_arr[t] = float(center)
        origin_arr[t] = 4
        zc_arr[t] = float(center)
        zl_arr[t] = zl
        zh_arr[t] = zh
        last_activation_bar = int(t)
        last_center = float(center)

    tc_long_arr = np.zeros(n, dtype=np.int32)
    tc_short_arr = np.zeros(n, dtype=np.int32)
    tkl_arr = np.zeros(n, dtype=bool)
    short_candidate_arr = np.zeros(n, dtype=bool)

    return {
        "touch_price": pd.Series(tp_arr, index=df.index),
        "zone_center": pd.Series(zc_arr, index=df.index),
        "zone_low": pd.Series(zl_arr, index=df.index),
        "zone_high": pd.Series(zh_arr, index=df.index),
        "touch_count_long": pd.Series(tc_long_arr, index=df.index),
        "touch_count_short": pd.Series(tc_short_arr, index=df.index),
        "tradeable_key_level": pd.Series(tkl_arr, index=df.index),
        "matured_now": pd.Series(matured_arr, index=df.index),
        "short_candidate": pd.Series(short_candidate_arr, index=df.index),
        "zone_touch_origin": pd.Series(origin_arr, index=df.index),
        "yh_zone_events": zone_events,
        "vec_zone_events": zone_events,
    }
