"""WPBR — Pivot Break and Retest (weekly pivot zones, weekly BO + confirmation, daily retest).

``retest_mode`` (default ``stop_looking``) controls the daily-retest forward scan:

- ``stop_looking`` (DEFAULT, sheet parity): from ``next_week_start``, the first bar with
  ``Low <= upper`` AND ``Close > upper``, but ONLY before the first bar with
  ``Close < zone_lower`` (the sheet ``Daily Retest Row`` abandon-kill window). No prior
  ``Close[r-1] >= lower`` gate. Reproduces the pasted sheet formula 48/48 on META.
- ``keep_looking`` (legacy engine): unbounded forward scan + prior ``Close[r-1] >= lower``
  gate, no abandon kill.

Wire from the engine via ``-v retest_mode=stop_looking|keep_looking`` (BRTConfig field
``wpbr_retest_mode``; ``retest_mode`` / ``wpbr_retest_mode`` aliases).
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

try:
    from vec_zones import compute_volume_poc
except ImportError:
    from stock_analysis.vec_zones import compute_volume_poc

# Strength defaults (VEC-inspired; audit-only unless promoted to entry gates later).
_WPBR_POC_LOOKBACK = 60
_WPBR_POC_BIN_PCT = 0.005
_WPBR_PRIOR_WEEKS = 13
_WPBR_VOL_MEDIAN_WEEKS = 20

# Exported on zone events, closed trades, and --print-zones CSV.
WPBR_STRENGTH_FIELDS: tuple[str, ...] = (
    "wpbr_pre_rise_pct",
    "wpbr_post_rise_pct",
    "wpbr_pivot_symmetry",
    "wpbr_poc",
    "wpbr_poc_dist_pct",
    "wpbr_prior_extreme",
    "wpbr_prior_extreme_dist_pct",
    "wpbr_bo_close_margin_pct",
    "wpbr_conf_overshoot_pct",
    "wpbr_weeks_pivot_to_bo",
    "wpbr_weeks_bo_to_conf",
    "wpbr_bo_volume_ratio",
    "wpbr_conf_volume_ratio",
    "wpbr_retest_depth_pct",
    "wpbr_retest_close_margin_pct",
    "wpbr_days_conf_to_retest",
    "wpbr_signal_body_pct",
    "wpbr_zone_strength",
    "wpbr_merge_count",
)


def _to_date(ts) -> pd.Timestamp:
    return pd.Timestamp(ts).normalize()


def aggregate_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Week ending Friday OHLCV."""
    ohlc = df[["Open", "High", "Low", "Close"]].copy()
    if "Volume" in df.columns:
        ohlc["Volume"] = df["Volume"]
    w = ohlc.resample("W-FRI").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    )
    return w.dropna(subset=["Close"])


def _week_monday(week_end: pd.Timestamp) -> pd.Timestamp:
    """Monday at the start of the week ending on ``week_end`` (Friday)."""
    return _to_date(week_end) - pd.Timedelta(days=4)


def _next_week_start_after_conf(conf_week_end: pd.Timestamp) -> pd.Timestamp:
    """Monday of the calendar week after the confirmation week (spreadsheet 'Next week start date')."""
    return _week_monday(conf_week_end) + pd.Timedelta(days=7)


def _first_daily_bar_on_or_after(day: pd.Timestamp, daily_index: pd.DatetimeIndex) -> int | None:
    dates = pd.DatetimeIndex(daily_index).normalize()
    target = _to_date(day).to_numpy()
    idx = int(np.searchsorted(dates.to_numpy(), target, side="left"))
    if idx >= len(dates):
        return None
    return idx


def _effective_strong_pivot_pct_week(
    pivot_px: float,
    week_idx: int,
    atr_at_week: np.ndarray | None,
    fixed_pct: float,
    atr_mult: float,
) -> float:
    """When atr_mult > 0, threshold = (atr_mult * ATR14) / pivot_px; else fixed_pct.

    Matches rocket_brt._effective_strong_pivot_pct; ATR is daily ATR14 mapped to the
    last daily bar of the pivot week (same bar used for band_pct_atr).
    """
    if atr_mult <= 0 or atr_at_week is None:
        return float(fixed_pct)
    if week_idx < 0 or week_idx >= len(atr_at_week):
        return float(fixed_pct)
    atr = float(atr_at_week[week_idx])
    if not (np.isfinite(atr) and atr > 0 and np.isfinite(pivot_px) and pivot_px > 0):
        return float(fixed_pct)
    return float((atr_mult * atr) / pivot_px)


def _weekly_pivot_indices(
    wh: np.ndarray,
    wl: np.ndarray,
    *,
    pre_bars: int,
    post_bars: int,
    pre_pct: float,
    post_pct: float,
    pivot_mode: str,
    pre_pct_atr: float = 0.0,
    post_pct_atr: float = 0.0,
    atr_at_week: np.ndarray | None = None,
) -> list[int]:
    n = len(wh)
    out: list[int] = []
    mode = (pivot_mode or "either").strip().lower()
    for t in range(pre_bars, n - post_bars):
        h = float(wh[t])
        if not (np.isfinite(h) and h > 0):
            continue
        prev_hi = float(np.max(wh[t - pre_bars : t])) if pre_bars > 0 else -np.inf
        post_hi = float(np.max(wh[t + 1 : t + post_bars + 1])) if post_bars > 0 else -np.inf
        if h <= prev_hi or h <= post_hi:
            continue
        pre_lo = float(np.min(wl[t - pre_bars : t])) if pre_bars > 0 else np.nan
        post_lo = float(np.min(wl[t + 1 : t + post_bars + 1])) if post_bars > 0 else np.nan
        pre_thr = _effective_strong_pivot_pct_week(
            h, t, atr_at_week, float(pre_pct), float(pre_pct_atr or 0.0)
        )
        post_thr = _effective_strong_pivot_pct_week(
            h, t, atr_at_week, float(post_pct), float(post_pct_atr or 0.0)
        )
        pre_ok = bool(pre_lo > 0 and (h / pre_lo - 1.0) >= pre_thr - 1e-12)
        post_ok = bool(post_lo > 0 and (h / post_lo - 1.0) >= post_thr - 1e-12)
        if mode in ("either", "any"):
            strong = pre_ok or post_ok
        elif mode == "both":
            strong = pre_ok and post_ok
        elif mode == "pre":
            strong = pre_ok
        elif mode == "post":
            strong = post_ok
        else:
            strong = pre_ok or post_ok
        if strong:
            out.append(t)
    return out


def _half_up(price: float, dec: int = 2) -> float:
    """Sheets-like ROUND(price, dec) via Decimal HALF_UP. WPBR compare helper only."""
    from decimal import ROUND_HALF_UP, Decimal

    quant = Decimal(10) ** (-int(dec))
    return float(Decimal(str(float(price))).quantize(quant, rounding=ROUND_HALF_UP))


def _round_bounds(price: float, band_pct: float, dec: int) -> tuple[float, float, float]:
    """Sheets-like ROUND(pivot, dec) then ROUND(pivot*(1±band), dec) via Decimal HALF_UP.

    Mirrors BRT ``_sheet_tp_band_bounds`` style, but also HALF_UP-rounds the pivot
    before the band (variant C). WPBR-only; classic BRT paths are unchanged.
    """
    from decimal import ROUND_HALF_UP, Decimal

    quant = Decimal(10) ** (-int(dec))
    tp = float(Decimal(str(float(price))).quantize(quant, rounding=ROUND_HALF_UP))
    dtp = Decimal(str(tp))
    db = Decimal(str(band_pct))
    zl = float((dtp * (Decimal(1) - db)).quantize(quant, rounding=ROUND_HALF_UP))
    zh = float((dtp * (Decimal(1) + db)).quantize(quant, rounding=ROUND_HALF_UP))
    return tp, zl, zh


def _last_daily_bar_on_or_before(day: pd.Timestamp, daily_index: pd.DatetimeIndex) -> int | None:
    """Last daily bar whose date is <= ``day`` (normalized); None if none exist."""
    dates = pd.DatetimeIndex(daily_index).normalize()
    target = _to_date(day).to_numpy()
    idx = int(np.searchsorted(dates.to_numpy(), target, side="right")) - 1
    if idx < 0:
        return None
    return idx


def _default_effective_band_pct(
    tp: float,
    bar_idx: int,
    atr_arr: np.ndarray,
    band_pct_fixed: float,
    band_pct_atr_mult: float,
) -> float:
    """Match rocket_brt._effective_band_pct_tp when no callback is injected."""
    if band_pct_atr_mult <= 0:
        return float(band_pct_fixed)
    if bar_idx < 0 or bar_idx >= len(atr_arr):
        return float(band_pct_fixed)
    atr = float(atr_arr[bar_idx])
    if not (np.isfinite(atr) and atr > 0 and np.isfinite(tp) and tp > 0):
        return float(band_pct_fixed)
    return float((band_pct_atr_mult * atr) / tp)


def _default_atr_14(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    """Simple rolling-mean TR (same construction as rocket_brt._compute_atr_14_arr)."""
    n = len(high)
    tr = np.empty(n, dtype=np.float64)
    tr[0] = high[0] - low[0]
    if n > 1:
        hl = high[1:] - low[1:]
        h_pc = np.abs(high[1:] - close[:-1])
        l_pc = np.abs(low[1:] - close[:-1])
        tr[1:] = np.maximum.reduce([hl, h_pc, l_pc])
    atr = np.full(n, np.nan, dtype=np.float64)
    if n >= period:
        atr[period - 1 :] = np.convolve(
            tr, np.ones(period, dtype=np.float64) / float(period), mode="valid"
        )
    return atr


def _finite_or_nan(x: float) -> float:
    try:
        v = float(x)
        return v if np.isfinite(v) else float("nan")
    except (TypeError, ValueError):
        return float("nan")


def _pivot_strength_detail(
    wh: np.ndarray,
    wl: np.ndarray,
    t: int,
    *,
    pre_bars: int,
    post_bars: int,
) -> dict[str, float]:
    """Continuous pre/post pivot rise and symmetry (0=asymmetric, 1=balanced)."""
    h = float(wh[t])
    pre_lo = float(np.min(wl[t - pre_bars : t])) if pre_bars > 0 and t >= pre_bars else float("nan")
    post_lo = (
        float(np.min(wl[t + 1 : t + post_bars + 1]))
        if post_bars > 0 and (t + post_bars) < len(wl)
        else float("nan")
    )
    pre_rise = (h / pre_lo - 1.0) if pre_lo > 0 and np.isfinite(pre_lo) else float("nan")
    post_rise = (h / post_lo - 1.0) if post_lo > 0 and np.isfinite(post_lo) else float("nan")
    symmetry = float("nan")
    if np.isfinite(pre_rise) and np.isfinite(post_rise) and (pre_rise + post_rise) > 0:
        symmetry = 1.0 - abs(pre_rise - post_rise) / (pre_rise + post_rise)
    return {
        "wpbr_pre_rise_pct": _finite_or_nan(pre_rise),
        "wpbr_post_rise_pct": _finite_or_nan(post_rise),
        "wpbr_pivot_symmetry": _finite_or_nan(symmetry),
    }


def _weekly_volume_ratio(wv: np.ndarray, week_idx: int, *, median_weeks: int = _WPBR_VOL_MEDIAN_WEEKS) -> float:
    if week_idx < 0 or week_idx >= len(wv):
        return float("nan")
    vol = float(wv[week_idx])
    if not (np.isfinite(vol) and vol > 0):
        return float("nan")
    start = max(0, week_idx - int(median_weeks))
    hist = wv[start:week_idx]
    hist = hist[np.isfinite(hist) & (hist > 0)]
    if hist.size == 0:
        return float("nan")
    med = float(np.median(hist))
    if med <= 0:
        return float("nan")
    return vol / med


def _wpbr_poc_confluence(
    hi: np.ndarray,
    lo: np.ndarray,
    cl: np.ndarray,
    vol: np.ndarray,
    end_bar: int,
    pivot_high: float,
) -> dict[str, float]:
    poc = compute_volume_poc(hi, lo, cl, vol, end_bar, _WPBR_POC_LOOKBACK, _WPBR_POC_BIN_PCT)
    if not (np.isfinite(poc) and pivot_high > 0):
        return {"wpbr_poc": float("nan"), "wpbr_poc_dist_pct": float("nan")}
    dist = abs(float(poc) - float(pivot_high)) / float(pivot_high)
    return {"wpbr_poc": float(poc), "wpbr_poc_dist_pct": float(dist)}


def _wpbr_prior_extreme_confluence(wh: np.ndarray, wi: int, pivot_high: float, *, prior_weeks: int) -> dict[str, float]:
    if pivot_high <= 0:
        return {"wpbr_prior_extreme": float("nan"), "wpbr_prior_extreme_dist_pct": float("nan")}
    start = max(0, wi - int(prior_weeks))
    if start >= wi:
        return {"wpbr_prior_extreme": float("nan"), "wpbr_prior_extreme_dist_pct": float("nan")}
    ext = float(np.max(wh[start:wi]))
    if not (np.isfinite(ext) and ext > 0):
        return {"wpbr_prior_extreme": float("nan"), "wpbr_prior_extreme_dist_pct": float("nan")}
    dist = abs(float(pivot_high) - ext) / ext
    return {"wpbr_prior_extreme": float(ext), "wpbr_prior_extreme_dist_pct": float(dist)}


def _wpbr_breakout_strength(
    wc: np.ndarray,
    wh: np.ndarray,
    wv: np.ndarray,
    *,
    pivot_week: int,
    bo_week: int | None,
    conf_week: int | None,
    zone_upper: float,
    confirm_pct: float,
) -> dict[str, float]:
    out: dict[str, float] = {
        "wpbr_bo_close_margin_pct": float("nan"),
        "wpbr_conf_overshoot_pct": float("nan"),
        "wpbr_weeks_pivot_to_bo": float("nan"),
        "wpbr_weeks_bo_to_conf": float("nan"),
        "wpbr_bo_volume_ratio": float("nan"),
        "wpbr_conf_volume_ratio": float("nan"),
    }
    zh = float(zone_upper)
    if zh <= 0:
        return out
    if bo_week is not None:
        out["wpbr_weeks_pivot_to_bo"] = float(bo_week - pivot_week)
        out["wpbr_bo_close_margin_pct"] = _finite_or_nan(float(wc[bo_week]) / zh - 1.0)
        out["wpbr_bo_volume_ratio"] = _weekly_volume_ratio(wv, bo_week)
    if conf_week is not None:
        conf_level = zh * (1.0 + float(confirm_pct))
        if conf_level > 0:
            out["wpbr_conf_overshoot_pct"] = _finite_or_nan(float(wh[conf_week]) / conf_level - 1.0)
        out["wpbr_conf_volume_ratio"] = _weekly_volume_ratio(wv, conf_week)
        if bo_week is not None:
            out["wpbr_weeks_bo_to_conf"] = float(conf_week - bo_week)
    return out


def _wpbr_retest_strength(
    lo: np.ndarray,
    cl: np.ndarray,
    op: np.ndarray,
    *,
    retest_bar: int | None,
    signal_bar: int | None,
    conf_bar: int | None,
    zone_lower: float,
    zone_upper: float,
    daily_index: pd.DatetimeIndex,
) -> dict[str, float]:
    out: dict[str, float] = {
        "wpbr_retest_depth_pct": float("nan"),
        "wpbr_retest_close_margin_pct": float("nan"),
        "wpbr_days_conf_to_retest": float("nan"),
        "wpbr_signal_body_pct": float("nan"),
    }
    zh = float(zone_upper)
    zl = float(zone_lower)
    if retest_bar is not None and 0 <= retest_bar < len(lo) and zh > 0:
        band = max(zh - zl, zh * 1e-6)
        penetration = max(0.0, zh - float(lo[retest_bar]))
        out["wpbr_retest_depth_pct"] = _finite_or_nan(penetration / band)
        out["wpbr_retest_close_margin_pct"] = _finite_or_nan(float(cl[retest_bar]) / zh - 1.0)
        if conf_bar is not None and 0 <= conf_bar < len(daily_index):
            conf_dt = pd.Timestamp(daily_index[conf_bar]).normalize()
            ret_dt = pd.Timestamp(daily_index[retest_bar]).normalize()
            out["wpbr_days_conf_to_retest"] = float((ret_dt - conf_dt).days)
    if signal_bar is not None and 0 <= signal_bar < len(op):
        opx = float(op[signal_bar])
        if opx > 0:
            out["wpbr_signal_body_pct"] = _finite_or_nan((float(cl[signal_bar]) - opx) / opx)
    return out


def _norm_strength_component(x: float, cap: float) -> float:
    if not (np.isfinite(x) and cap > 0):
        return 0.0
    return float(min(1.0, max(0.0, x / cap)))


def _compute_wpbr_zone_strength(metrics: dict[str, float]) -> float:
    """Simple 0–1 composite for ranking zones (audit / research)."""
    pre = _norm_strength_component(metrics.get("wpbr_pre_rise_pct", float("nan")), 0.25)
    post = _norm_strength_component(metrics.get("wpbr_post_rise_pct", float("nan")), 0.25)
    poc_dist = metrics.get("wpbr_poc_dist_pct", float("nan"))
    poc_score = 1.0 - min(1.0, float(poc_dist) / 0.01) if np.isfinite(poc_dist) else 0.0
    prior_dist = metrics.get("wpbr_prior_extreme_dist_pct", float("nan"))
    prior_score = 1.0 - min(1.0, float(prior_dist) / 0.02) if np.isfinite(prior_dist) else 0.0
    conf_os = _norm_strength_component(metrics.get("wpbr_conf_overshoot_pct", float("nan")), 0.08)
    bo_vol = metrics.get("wpbr_bo_volume_ratio", float("nan"))
    bo_vol_score = min(1.0, float(bo_vol) / 2.0) if np.isfinite(bo_vol) else 0.0
    depth = metrics.get("wpbr_retest_depth_pct", float("nan"))
    retest_score = 1.0 - min(1.0, float(depth) / 0.5) if np.isfinite(depth) else 0.0
    body = _norm_strength_component(metrics.get("wpbr_signal_body_pct", float("nan")), 0.03)
    sym = metrics.get("wpbr_pivot_symmetry", float("nan"))
    sym_score = float(sym) if np.isfinite(sym) else 0.0
    score = (
        0.14 * pre
        + 0.14 * post
        + 0.08 * sym_score
        + 0.12 * poc_score
        + 0.08 * prior_score
        + 0.12 * conf_os
        + 0.10 * bo_vol_score
        + 0.12 * retest_score
        + 0.10 * body
    )
    return round(min(1.0, max(0.0, score)), 4)


def wpbr_strength_from_event(ev: dict[str, Any]) -> dict[str, float]:
    """Extract strength metrics from a zone event dict."""
    return {k: _finite_or_nan(ev.get(k, float("nan"))) for k in WPBR_STRENGTH_FIELDS}


def _find_weekly_breakout_and_confirm(
    wc: np.ndarray,
    wh: np.ndarray,
    *,
    start_week: int,
    zone_upper: float,
    confirm_pct: float,
) -> tuple[int | None, int | None]:
    """
    Stage 1: first weekly close > zone_upper.
    Stage 2: first weekly high > zone_upper * (1 + confirm_pct), on or after BO week.
    """
    bo_week: int | None = None
    conf_week: int | None = None
    conf_level = zone_upper * (1.0 + confirm_pct)
    for wj in range(start_week, len(wc)):
        c = float(wc[wj])
        h = float(wh[wj])
        if bo_week is None and c > zone_upper + 1e-12:
            bo_week = wj
        if bo_week is not None and h > conf_level + 1e-12:
            conf_week = wj
            break
    return bo_week, conf_week


def make_wpbr_zone_id(pivot_week_end: str, zone_lower: float, zone_upper: float) -> str:
    """Stable WPBR zone identity: pivot week + rounded bounds."""
    return f"{pivot_week_end}|{float(zone_lower):.4f}|{float(zone_upper):.4f}"


def wpbr_bands_overlap(a_lo: float, a_hi: float, b_lo: float, b_hi: float) -> bool:
    """Inclusive band overlap: touching endpoints count as overlap."""
    return float(a_lo) <= float(b_hi) and float(b_lo) <= float(a_hi)


def merge_overlapping_wpbr_candidates(candidates: list[dict]) -> list[dict]:
    """Cluster overlapping WPBR band candidates; expand to min low / max high.

    See ``drive/wpbr_sheet_reconcile/ZONE_MERGE_OVERLAP_REQUIREMENTS.md``.

    Overlap is inclusive (``[10,12]`` + ``[12,14]`` merge). Transitive chains
    (A overlaps B, B overlaps C) become one cluster. Identity (``wi``, pivot
    dates, ``touch``) is taken from the earliest ``pivot_week_end`` member.
    Does not mutate input dicts.
    """
    if not candidates:
        return []
    ordered = sorted(
        candidates,
        key=lambda c: (float(c["zl"]), str(c.get("pivot_week_end", "")), int(c.get("wi", 0))),
    )
    clusters: list[list[dict]] = []
    for c in ordered:
        if not clusters:
            clusters.append([c])
            continue
        last = clusters[-1]
        cl_lo = min(float(m["zl"]) for m in last)
        cl_hi = max(float(m["zh"]) for m in last)
        if wpbr_bands_overlap(cl_lo, cl_hi, float(c["zl"]), float(c["zh"])):
            last.append(c)
        else:
            clusters.append([c])

    out: list[dict] = []
    for members in clusters:
        members_by_time = sorted(
            members, key=lambda m: (str(m["pivot_week_end"]), int(m.get("wi", 0)))
        )
        earliest = members_by_time[0]
        merged = dict(earliest)
        merged["zl"] = min(float(m["zl"]) for m in members)
        merged["zh"] = max(float(m["zh"]) for m in members)
        merged["wpbr_merge_count"] = len(members)
        merged["wpbr_merge_member_pivot_week_ends"] = ",".join(
            str(m["pivot_week_end"]) for m in members_by_time
        )
        out.append(merged)
    out.sort(key=lambda c: (str(c["pivot_week_end"]), int(c.get("wi", 0))))
    return out


RETEST_MODE_STOP_LOOKING = "stop_looking"
RETEST_MODE_KEEP_LOOKING = "keep_looking"
_VALID_RETEST_MODES = (RETEST_MODE_STOP_LOOKING, RETEST_MODE_KEEP_LOOKING)


def normalize_retest_mode(mode: Any) -> str:
    """Coerce a raw retest_mode value to ``stop_looking`` (default) or ``keep_looking``."""
    m = str(mode if mode is not None else "").strip().lower()
    if m in _VALID_RETEST_MODES:
        return m
    return RETEST_MODE_STOP_LOOKING


def find_wpbr_retest_and_signal(
    lo: np.ndarray,
    cl: np.ndarray,
    op: np.ndarray,
    *,
    scan_start: int,
    zone_lower: float,
    zone_upper: float,
    max_days_after_retest: int,
    n: int,
    stop_at: int | None = None,
    retest_mode: str = RETEST_MODE_STOP_LOOKING,
) -> tuple[int | None, int | None, int | None]:
    """
    Find the next retest after ``scan_start``, then the first green close signal
    within ``max_days_after_retest`` bars (inclusive of retest bar).

    Retest core (both modes): Low <= zone_upper and Close > zone_upper.
    Signal: Close > Open and Close > zone_upper.
    Fill: next session open (signal_bar + 1), if available.

    Price compares use Decimal HALF_UP to 2 decimals (same style as ``_round_bounds``)
    so DuckDB float noise (e.g. Low 12.180000305 vs zh 12.18) matches sheet 2-dp OHLC.

    ``retest_mode`` controls how the forward scan terminates:

    - ``stop_looking`` (DEFAULT) — matches the spreadsheet ``Daily Retest Row``: the
      first bar with ``Low <= upper`` AND ``Close > upper``, but ONLY before the first
      bar (on/after ``scan_start``) with ``Close < zone_lower`` (the abandon "kill"
      window). If abandon happens before any retest, no retest is emitted (blank).
      No prior-``Close >= lower`` gate is applied — sheet parity.
    - ``keep_looking`` — legacy engine behavior: unbounded forward scan with the prior
      ``Close[r-1] >= zone_lower`` gate and no abandon kill-window.

    If ``stop_at`` is set, only consider bars ``<= stop_at`` for retest/signal.
    Returns (retest_bar, signal_bar, fill_bar).
    """
    if scan_start < 0 or scan_start >= n:
        return None, None, None
    end_scan = n - 1 if stop_at is None else min(n - 1, int(stop_at))
    if end_scan < scan_start:
        return None, None, None
    zl = _half_up(float(zone_lower))
    zh = _half_up(float(zone_upper))
    max_entry_days = max(0, int(max_days_after_retest))
    mode = normalize_retest_mode(retest_mode)
    retest_bar: int | None = None
    for di in range(scan_start, end_scan + 1):
        if di <= 0:
            continue
        lo_r = _half_up(float(lo[di]))
        cl_r = _half_up(float(cl[di]))
        if mode == RETEST_MODE_STOP_LOOKING:
            # Sheet abandon-kill: first Close < zone_lower ends the window (blank).
            if cl_r < zl:
                return None, None, None
            if lo_r <= zh and cl_r > zh:
                retest_bar = di
                break
            continue
        # keep_looking (legacy): unbounded scan + prior-close gate.
        if not (lo_r <= zh and cl_r > zh):
            continue
        if _half_up(float(cl[di - 1])) < zl:
            continue
        retest_bar = di
        break
    if retest_bar is None:
        return None, None, None
    end_di = min(end_scan, retest_bar + max_entry_days)
    for di in range(retest_bar, end_di + 1):
        cl_r = _half_up(float(cl[di]))
        op_r = _half_up(float(op[di]))
        if cl_r > op_r and cl_r > zh:
            fill = di + 1 if di + 1 < n else None
            return retest_bar, di, fill
    return retest_bar, None, None


def _ymd8(s: str) -> str:
    """Normalize YYYY-MM-DD / YYYYMMDD / mixed to 8-digit YYYYMMDD; empty if unset."""
    digits = "".join(ch for ch in str(s or "") if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else ""


def compute_wpbr_touch_stream(
    df: pd.DataFrame,
    *,
    band_pct: float = 0.015,
    band_pct_atr: float = 0.0,
    strong_pre_pivot_bars: int = 3,
    strong_pre_pivot_pct: float = 0.10,
    strong_pre_pivot_pct_atr: float = 0.0,
    strong_post_pivot_bars: int = 3,
    strong_post_pivot_pct: float = 0.10,
    strong_post_pivot_pct_atr: float = 0.0,
    strong_pivot_mode: str = "either",
    breakout_confirmation: float = 0.03,
    max_days_after_retest: int = 2,
    retest_mode: str = RETEST_MODE_STOP_LOOKING,
    zone_price_round_decimals: int = 2,
    min_pivot_date: str = "",
    merge_overlapping_zones: bool = False,
    debug_symbol: Optional[str] = None,
    effective_band_pct_fn=None,
    compute_atr_14_fn=None,
) -> dict[str, Any]:
    """
    Weekly pivot-high zones; two-stage weekly breakout (close > upper, then high > upper*(1+conf));
    daily retest/entry begins the Monday after the confirmation week.

    Zone half-width: fixed ``band_pct`` when ``band_pct_atr <= 0``; otherwise
    ``(band_pct_atr * ATR14) / pivot_high`` at the last daily bar of the pivot week
    (``band_pct`` is fallback if ATR is unavailable). Same units/semantics as BRT/YH/VEC.

    Strong-pivot thresholds: fixed ``strong_*_pivot_pct`` when the matching
    ``strong_*_pivot_pct_atr <= 0``; otherwise ``(atr_mult * ATR14) / pivot_high``
    at that same last-daily-bar-of-week (fixed pct is ATR-unavailable fallback).

    When ``merge_overlapping_zones`` is True, overlapping candidate bands are coalesced
    into one zone (min low / max high; ``wpbr_merge_count`` = member count) before
    breakout/retest. Default False preserves sheet parity (no merge).

    Emits the first retest/signal opportunity per zone. The backtest enforces zone lifecycle
    when ``wpbr_second_chance_after_win`` is enabled:
      - 1st purchase closes with pnl_pct > 0 → allow one more purchase (resume scan after exit)
      - 1st purchase closes flat/loss → retire zone
      - 2nd purchase → retire zone immediately (no further entries)
    When that flag is False (default), the zone is retired after the first purchase.

    Each zone event includes strength metrics (``WPBR_STRENGTH_FIELDS``): pivot quality,
    POC/prior-extreme confluence, breakout/confirmation power, retest quality, and
    ``wpbr_zone_strength`` composite (0–1, audit/research).

    ``min_pivot_date`` (from engine ``entry_start_date`` / ``-v start_date=``): when set, weekly
    pivots whose Monday is strictly before that date are excluded from the strategy ledger
    (no zone cloud, BO/conf, retest, or entry opportunities). Full OHLC history may still be
    passed in for weekly aggregation / indicator lookback.

    Spreadsheet mapping:
      Breakout Date  -> Monday of first weekly close > zone_upper
      Conf Date      -> Monday of first weekly high > zone_upper*(1+confirmation)
      Next week start -> Monday after confirmation week
      Rocket Buy Date -> signal day (green close); fill = next session open
    """
    n = len(df)
    daily_index = pd.DatetimeIndex(df.index)
    hi = np.asarray(df["High"].values, dtype=np.float64)
    lo = np.asarray(df["Low"].values, dtype=np.float64)
    op = np.asarray(df["Open"].values, dtype=np.float64)
    cl = np.asarray(df["Close"].values, dtype=np.float64)
    vol = (
        np.asarray(df["Volume"].values, dtype=np.float64)
        if "Volume" in df.columns
        else np.zeros(n, dtype=np.float64)
    )
    _band_fn = effective_band_pct_fn or _default_effective_band_pct
    _atr_fn = compute_atr_14_fn or _default_atr_14
    pre_atr_m = float(strong_pre_pivot_pct_atr or 0.0)
    post_atr_m = float(strong_post_pivot_pct_atr or 0.0)
    need_atr = (
        float(band_pct_atr or 0.0) > 0
        or pre_atr_m > 0
        or post_atr_m > 0
    )
    atr_14_arr = (
        _atr_fn(hi, lo, cl, 14)
        if need_atr
        else np.full(n, np.nan, dtype=np.float64)
    )

    weekly = aggregate_weekly(df)
    if weekly.empty:
        empty = np.full(n, np.nan)
        return {
            "touch_price": pd.Series(empty, index=df.index),
            "zone_center": pd.Series(empty, index=df.index),
            "zone_low": pd.Series(empty, index=df.index),
            "zone_high": pd.Series(empty, index=df.index),
            "touch_count_long": pd.Series(0, index=df.index),
            "touch_count_short": pd.Series(0, index=df.index),
            "tradeable_key_level": pd.Series(False, index=df.index),
            "matured_now": pd.Series(False, index=df.index),
            "short_candidate": pd.Series(False, index=df.index),
            "zone_touch_origin": pd.Series(0, index=df.index),
            "yh_zone_events": [],
            "wpbr_zone_events": [],
            "wpbr_entry_opportunities": [],
            "wpbr_entry_signal_bars": [],
            "wpbr_entry_fill_bars": [],
            "wpbr_audit": [],
        }

    wh = weekly["High"].to_numpy(dtype=np.float64)
    wl = weekly["Low"].to_numpy(dtype=np.float64)
    wc = weekly["Close"].to_numpy(dtype=np.float64)
    wv = (
        weekly["Volume"].to_numpy(dtype=np.float64)
        if "Volume" in weekly.columns
        else np.zeros(len(weekly), dtype=np.float64)
    )
    w_index = pd.DatetimeIndex(weekly.index)

    atr_at_week: np.ndarray | None = None
    if pre_atr_m > 0 or post_atr_m > 0:
        atr_at_week = np.full(len(weekly), np.nan, dtype=np.float64)
        for wi in range(len(weekly)):
            bar = _last_daily_bar_on_or_before(w_index[wi], daily_index)
            if bar is not None:
                atr_at_week[wi] = float(atr_14_arr[bar])

    pivots = _weekly_pivot_indices(
        wh,
        wl,
        pre_bars=int(strong_pre_pivot_bars),
        post_bars=int(strong_post_pivot_bars),
        pre_pct=float(strong_pre_pivot_pct),
        post_pct=float(strong_post_pivot_pct),
        pivot_mode=strong_pivot_mode,
        pre_pct_atr=pre_atr_m,
        post_pct_atr=post_atr_m,
        atr_at_week=atr_at_week,
    )

    dec = max(0, int(zone_price_round_decimals))
    bo_conf = max(0.0, float(breakout_confirmation))
    max_entry_days = max(0, int(max_days_after_retest))
    retest_mode_norm = normalize_retest_mode(retest_mode)
    do_merge = bool(merge_overlapping_zones)

    tp_arr = np.full(n, np.nan)
    zc_arr = np.full(n, np.nan)
    zl_arr = np.full(n, np.nan)
    zh_arr = np.full(n, np.nan)
    origin_arr = np.zeros(n, dtype=np.int8)
    matured_arr = np.zeros(n, dtype=bool)

    zone_events: list[dict] = []
    yh_events: list[dict] = []
    audit: list[dict] = []
    entry_signal_bars: list[int] = []
    entry_fill_bars: list[int] = []
    entry_opportunities: list[dict] = []

    dates_norm = daily_index.normalize()
    min_pivot8 = _ymd8(min_pivot_date)

    candidates: list[dict] = []
    for wi in pivots:
        pivot_high = float(wh[wi])
        pivot_week_end_ts = w_index[wi]
        pivot_monday = _week_monday(pivot_week_end_ts)
        # start_date / entry_start_date: exclude pre-window pivots from the ledger entirely
        # (zones, BO/conf, retests, rockets). Weekly lookback bars before this date still load.
        if min_pivot8 and pivot_monday.strftime("%Y%m%d") < min_pivot8:
            continue
        atr_bar = _last_daily_bar_on_or_before(pivot_week_end_ts, daily_index)
        if atr_bar is None:
            continue
        bp_i = float(
            _band_fn(
                float(pivot_high),
                int(atr_bar),
                atr_14_arr,
                float(band_pct),
                float(band_pct_atr or 0.0),
            )
        )
        touch, zl, zh = _round_bounds(pivot_high, bp_i, dec)
        pivot_week_end = pivot_week_end_ts.strftime("%Y-%m-%d")
        pivot_daily_start = int(
            np.searchsorted(dates_norm.to_numpy(), pivot_monday.to_numpy(), side="left")
        )
        if pivot_daily_start >= n:
            continue
        candidates.append(
            {
                "wi": int(wi),
                "touch": touch,
                "zl": zl,
                "zh": zh,
                "pivot_week_end_ts": pivot_week_end_ts,
                "pivot_week_end": pivot_week_end,
                "pivot_monday": pivot_monday,
                "pivot_daily_start": pivot_daily_start,
                "wpbr_merge_count": 1,
                "wpbr_merge_member_pivot_week_ends": pivot_week_end,
            }
        )

    if do_merge:
        candidates = merge_overlapping_wpbr_candidates(candidates)

    for cand in candidates:
        wi = int(cand["wi"])
        touch = float(cand["touch"])
        zl = float(cand["zl"])
        zh = float(cand["zh"])
        pivot_week_end_ts = cand["pivot_week_end_ts"]
        pivot_week_end = str(cand["pivot_week_end"])
        pivot_monday = cand["pivot_monday"]
        pivot_daily_start = int(cand["pivot_daily_start"])
        merge_count = int(cand.get("wpbr_merge_count", 1) or 1)
        merge_members = str(cand.get("wpbr_merge_member_pivot_week_ends", pivot_week_end) or pivot_week_end)
        zone_id = make_wpbr_zone_id(pivot_week_end, zl, zh)

        bo_week, conf_week = _find_weekly_breakout_and_confirm(
            wc, wh, start_week=wi, zone_upper=zh, confirm_pct=bo_conf,
        )

        bo_monday: pd.Timestamp | None = None
        conf_monday: pd.Timestamp | None = None
        next_week_start: pd.Timestamp | None = None
        bo_daily_end: int | None = None
        conf_daily_end: int | None = None
        scan_start_bar: int | None = None

        if bo_week is not None:
            bo_monday = _week_monday(w_index[bo_week])
            bo_daily_end = int(
                np.searchsorted(dates_norm.to_numpy(), _to_date(w_index[bo_week]).to_numpy(), side="right")
            ) - 1
            bo_daily_end = max(0, min(n - 1, bo_daily_end))
        if conf_week is not None:
            conf_monday = _week_monday(w_index[conf_week])
            next_week_start = _next_week_start_after_conf(w_index[conf_week])
            conf_daily_end = int(
                np.searchsorted(dates_norm.to_numpy(), _to_date(w_index[conf_week]).to_numpy(), side="right")
            ) - 1
            conf_daily_end = max(0, min(n - 1, conf_daily_end))

        # Zone cloud from pivot week forward (active even before confirmation)
        for di in range(pivot_daily_start, n):
            tp_arr[di] = touch
            zc_arr[di] = touch
            zl_arr[di] = zl
            zh_arr[di] = zh
            origin_arr[di] = 5
        if pivot_daily_start < n:
            matured_arr[pivot_daily_start] = True

        retest_bar: int | None = None
        entry_signal_bar: int | None = None
        entry_fill_bar: int | None = None

        if conf_week is not None and next_week_start is not None:
            scan_start_bar = _first_daily_bar_on_or_after(next_week_start, daily_index)
            if scan_start_bar is not None:
                retest_bar, entry_signal_bar, entry_fill_bar = find_wpbr_retest_and_signal(
                    lo,
                    cl,
                    op,
                    scan_start=scan_start_bar,
                    zone_lower=zl,
                    zone_upper=zh,
                    max_days_after_retest=max_entry_days,
                    n=n,
                    retest_mode=retest_mode_norm,
                )
                if entry_signal_bar is not None and entry_fill_bar is not None:
                    entry_signal_bars.append(entry_signal_bar)
                    entry_fill_bars.append(entry_fill_bar)
                    entry_opportunities.append(
                        {
                            "wpbr_zone_id": zone_id,
                            "zone_lower": zl,
                            "zone_upper": zh,
                            "zone_center": touch,
                            "retest_bar": retest_bar,
                            "entry_signal_bar": entry_signal_bar,
                            "entry_fill_bar": entry_fill_bar,
                            "opportunity_index": 0,
                            "scan_start_bar": scan_start_bar,
                            "wpbr_merge_count": merge_count,
                        }
                    )

        pivot_daily_end = int(
            np.searchsorted(dates_norm.to_numpy(), _to_date(w_index[wi]).to_numpy(), side="right")
        ) - 1
        pivot_daily_end = max(0, min(n - 1, pivot_daily_end))

        strength: dict[str, float] = {}
        strength.update(
            _pivot_strength_detail(
                wh,
                wl,
                wi,
                pre_bars=int(strong_pre_pivot_bars),
                post_bars=int(strong_post_pivot_bars),
            )
        )
        strength.update(_wpbr_poc_confluence(hi, lo, cl, vol, pivot_daily_end, touch))
        strength.update(_wpbr_prior_extreme_confluence(wh, wi, touch, prior_weeks=_WPBR_PRIOR_WEEKS))
        strength.update(
            _wpbr_breakout_strength(
                wc,
                wh,
                wv,
                pivot_week=wi,
                bo_week=bo_week,
                conf_week=conf_week,
                zone_upper=zh,
                confirm_pct=bo_conf,
            )
        )
        strength.update(
            _wpbr_retest_strength(
                lo,
                cl,
                op,
                retest_bar=retest_bar,
                signal_bar=entry_signal_bar,
                conf_bar=conf_daily_end,
                zone_lower=zl,
                zone_upper=zh,
                daily_index=daily_index,
            )
        )
        strength["wpbr_zone_strength"] = _compute_wpbr_zone_strength(strength)
        strength["wpbr_merge_count"] = float(merge_count)

        ev = {
            "wpbr_zone_id": zone_id,
            "pivot_week_end": pivot_week_end,
            "pivot_monday": pivot_monday.strftime("%Y-%m-%d"),
            "pivot_high": touch,
            "zone_lower": zl,
            "zone_upper": zh,
            "breakout_week_end": w_index[bo_week].strftime("%Y-%m-%d") if bo_week is not None else "",
            "breakout_monday": bo_monday.strftime("%Y-%m-%d") if bo_monday is not None else "",
            "breakout_bar": bo_daily_end if bo_daily_end is not None else -1,
            "conf_week_end": w_index[conf_week].strftime("%Y-%m-%d") if conf_week is not None else "",
            "conf_monday": conf_monday.strftime("%Y-%m-%d") if conf_monday is not None else "",
            "conf_bar": conf_daily_end if conf_daily_end is not None else -1,
            "next_week_start": next_week_start.strftime("%Y-%m-%d") if next_week_start is not None else "",
            "scan_start_bar": scan_start_bar if scan_start_bar is not None else -1,
            "retest_bar": retest_bar if retest_bar is not None else -1,
            "entry_signal_bar": entry_signal_bar if entry_signal_bar is not None else -1,
            "entry_fill_bar": entry_fill_bar if entry_fill_bar is not None else -1,
            "yh_bar": pivot_daily_start,
            "activation_bar": pivot_daily_start,
            "touch_price": touch,
            "zone_center": touch,
            "zone_lower_f": zl,
            "zone_upper_f": zh,
            "activation_price": touch,
            "origin": 5,
            "max_days_after_retest": max_entry_days,
            "wpbr_merge_member_pivot_week_ends": merge_members,
            **strength,
        }
        if entry_opportunities and entry_opportunities[-1].get("wpbr_zone_id") == zone_id:
            entry_opportunities[-1].update(strength)
        zone_events.append(ev)
        yh_events.append(
            {
                "yh_bar": pivot_daily_start,
                "activation_bar": pivot_daily_start,
                "touch_price": touch,
                "zone_center": touch,
                "zone_lower": zl,
                "zone_upper": zh,
                "activation_price": touch,
                "origin": 5,
                "breakout_bar": bo_daily_end if bo_daily_end is not None else -1,
                "conf_bar": conf_daily_end if conf_daily_end is not None else -1,
                "retest_bar": retest_bar if retest_bar is not None else -1,
                "wpbr_zone_id": zone_id,
                "wpbr_merge_count": merge_count,
            }
        )
        audit.append(ev)

        if debug_symbol:
            print(
                f"[WPBR] {debug_symbol} id={zone_id} pivot={pivot_monday.date()} z=({zl},{zh}) "
                f"merge={merge_count} "
                f"bo={bo_monday.date() if bo_monday else None} "
                f"conf={conf_monday.date() if conf_monday else None} "
                f"next={next_week_start.date() if next_week_start else None} "
                f"retest={retest_bar} signal={entry_signal_bar} fill={entry_fill_bar}"
            )

    tkl = matured_arr.copy()
    return {
        "touch_price": pd.Series(tp_arr, index=df.index),
        "zone_center": pd.Series(zc_arr, index=df.index),
        "zone_low": pd.Series(zl_arr, index=df.index),
        "zone_high": pd.Series(zh_arr, index=df.index),
        "touch_count_long": pd.Series(np.where(np.isfinite(zc_arr), 1, 0), index=df.index),
        "touch_count_short": pd.Series(0, index=df.index),
        "tradeable_key_level": pd.Series(tkl, index=df.index),
        "matured_now": pd.Series(matured_arr, index=df.index),
        "short_candidate": pd.Series(False, index=df.index),
        "zone_touch_origin": pd.Series(origin_arr, index=df.index),
        "yh_zone_events": yh_events,
        "wpbr_zone_events": zone_events,
        "wpbr_entry_opportunities": entry_opportunities,
        "wpbr_entry_signal_bars": sorted(set(entry_signal_bars)),
        "wpbr_entry_fill_bars": sorted(set(entry_fill_bars)),
        "wpbr_entry_bars": sorted(set(entry_signal_bars)),
        "wpbr_audit": audit,
    }
