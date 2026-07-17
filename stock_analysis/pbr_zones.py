"""PBR — Pivot Break and Retest (weekly pivot zones, weekly BO + confirmation, daily retest)."""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

try:
    from vec_zones import compute_volume_poc
except ImportError:
    from stock_analysis.vec_zones import compute_volume_poc

# Strength defaults (VEC-inspired; audit-only unless promoted to entry gates later).
_PBR_POC_LOOKBACK = 60
_PBR_POC_BIN_PCT = 0.005
_PBR_PRIOR_WEEKS = 13
_PBR_VOL_MEDIAN_WEEKS = 20

# Exported on zone events, closed trades, and --print-zones CSV.
PBR_STRENGTH_FIELDS: tuple[str, ...] = (
    "pbr_pre_rise_pct",
    "pbr_post_rise_pct",
    "pbr_pivot_symmetry",
    "pbr_poc",
    "pbr_poc_dist_pct",
    "pbr_prior_extreme",
    "pbr_prior_extreme_dist_pct",
    "pbr_bo_close_margin_pct",
    "pbr_conf_overshoot_pct",
    "pbr_weeks_pivot_to_bo",
    "pbr_weeks_bo_to_conf",
    "pbr_bo_volume_ratio",
    "pbr_conf_volume_ratio",
    "pbr_retest_depth_pct",
    "pbr_retest_close_margin_pct",
    "pbr_days_conf_to_retest",
    "pbr_signal_body_pct",
    "pbr_zone_strength",
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


def _weekly_pivot_indices(
    wh: np.ndarray,
    wl: np.ndarray,
    *,
    pre_bars: int,
    post_bars: int,
    pre_pct: float,
    post_pct: float,
    pivot_mode: str,
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
        pre_ok = bool(pre_lo > 0 and (h / pre_lo - 1.0) >= pre_pct - 1e-12)
        post_ok = bool(post_lo > 0 and (h / post_lo - 1.0) >= post_pct - 1e-12)
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


def _round_bounds(price: float, band_pct: float, dec: int) -> tuple[float, float, float]:
    tp = float(price)
    zl = round(tp * (1.0 - band_pct), dec)
    zh = round(tp * (1.0 + band_pct), dec)
    return tp, zl, zh


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
        "pbr_pre_rise_pct": _finite_or_nan(pre_rise),
        "pbr_post_rise_pct": _finite_or_nan(post_rise),
        "pbr_pivot_symmetry": _finite_or_nan(symmetry),
    }


def _weekly_volume_ratio(wv: np.ndarray, week_idx: int, *, median_weeks: int = _PBR_VOL_MEDIAN_WEEKS) -> float:
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


def _pbr_poc_confluence(
    hi: np.ndarray,
    lo: np.ndarray,
    cl: np.ndarray,
    vol: np.ndarray,
    end_bar: int,
    pivot_high: float,
) -> dict[str, float]:
    poc = compute_volume_poc(hi, lo, cl, vol, end_bar, _PBR_POC_LOOKBACK, _PBR_POC_BIN_PCT)
    if not (np.isfinite(poc) and pivot_high > 0):
        return {"pbr_poc": float("nan"), "pbr_poc_dist_pct": float("nan")}
    dist = abs(float(poc) - float(pivot_high)) / float(pivot_high)
    return {"pbr_poc": float(poc), "pbr_poc_dist_pct": float(dist)}


def _pbr_prior_extreme_confluence(wh: np.ndarray, wi: int, pivot_high: float, *, prior_weeks: int) -> dict[str, float]:
    if pivot_high <= 0:
        return {"pbr_prior_extreme": float("nan"), "pbr_prior_extreme_dist_pct": float("nan")}
    start = max(0, wi - int(prior_weeks))
    if start >= wi:
        return {"pbr_prior_extreme": float("nan"), "pbr_prior_extreme_dist_pct": float("nan")}
    ext = float(np.max(wh[start:wi]))
    if not (np.isfinite(ext) and ext > 0):
        return {"pbr_prior_extreme": float("nan"), "pbr_prior_extreme_dist_pct": float("nan")}
    dist = abs(float(pivot_high) - ext) / ext
    return {"pbr_prior_extreme": float(ext), "pbr_prior_extreme_dist_pct": float(dist)}


def _pbr_breakout_strength(
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
        "pbr_bo_close_margin_pct": float("nan"),
        "pbr_conf_overshoot_pct": float("nan"),
        "pbr_weeks_pivot_to_bo": float("nan"),
        "pbr_weeks_bo_to_conf": float("nan"),
        "pbr_bo_volume_ratio": float("nan"),
        "pbr_conf_volume_ratio": float("nan"),
    }
    zh = float(zone_upper)
    if zh <= 0:
        return out
    if bo_week is not None:
        out["pbr_weeks_pivot_to_bo"] = float(bo_week - pivot_week)
        out["pbr_bo_close_margin_pct"] = _finite_or_nan(float(wc[bo_week]) / zh - 1.0)
        out["pbr_bo_volume_ratio"] = _weekly_volume_ratio(wv, bo_week)
    if conf_week is not None:
        conf_level = zh * (1.0 + float(confirm_pct))
        if conf_level > 0:
            out["pbr_conf_overshoot_pct"] = _finite_or_nan(float(wh[conf_week]) / conf_level - 1.0)
        out["pbr_conf_volume_ratio"] = _weekly_volume_ratio(wv, conf_week)
        if bo_week is not None:
            out["pbr_weeks_bo_to_conf"] = float(conf_week - bo_week)
    return out


def _pbr_retest_strength(
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
        "pbr_retest_depth_pct": float("nan"),
        "pbr_retest_close_margin_pct": float("nan"),
        "pbr_days_conf_to_retest": float("nan"),
        "pbr_signal_body_pct": float("nan"),
    }
    zh = float(zone_upper)
    zl = float(zone_lower)
    if retest_bar is not None and 0 <= retest_bar < len(lo) and zh > 0:
        band = max(zh - zl, zh * 1e-6)
        penetration = max(0.0, zh - float(lo[retest_bar]))
        out["pbr_retest_depth_pct"] = _finite_or_nan(penetration / band)
        out["pbr_retest_close_margin_pct"] = _finite_or_nan(float(cl[retest_bar]) / zh - 1.0)
        if conf_bar is not None and 0 <= conf_bar < len(daily_index):
            conf_dt = pd.Timestamp(daily_index[conf_bar]).normalize()
            ret_dt = pd.Timestamp(daily_index[retest_bar]).normalize()
            out["pbr_days_conf_to_retest"] = float((ret_dt - conf_dt).days)
    if signal_bar is not None and 0 <= signal_bar < len(op):
        opx = float(op[signal_bar])
        if opx > 0:
            out["pbr_signal_body_pct"] = _finite_or_nan((float(cl[signal_bar]) - opx) / opx)
    return out


def _norm_strength_component(x: float, cap: float) -> float:
    if not (np.isfinite(x) and cap > 0):
        return 0.0
    return float(min(1.0, max(0.0, x / cap)))


def _compute_pbr_zone_strength(metrics: dict[str, float]) -> float:
    """Simple 0–1 composite for ranking zones (audit / research)."""
    pre = _norm_strength_component(metrics.get("pbr_pre_rise_pct", float("nan")), 0.25)
    post = _norm_strength_component(metrics.get("pbr_post_rise_pct", float("nan")), 0.25)
    poc_dist = metrics.get("pbr_poc_dist_pct", float("nan"))
    poc_score = 1.0 - min(1.0, float(poc_dist) / 0.01) if np.isfinite(poc_dist) else 0.0
    prior_dist = metrics.get("pbr_prior_extreme_dist_pct", float("nan"))
    prior_score = 1.0 - min(1.0, float(prior_dist) / 0.02) if np.isfinite(prior_dist) else 0.0
    conf_os = _norm_strength_component(metrics.get("pbr_conf_overshoot_pct", float("nan")), 0.08)
    bo_vol = metrics.get("pbr_bo_volume_ratio", float("nan"))
    bo_vol_score = min(1.0, float(bo_vol) / 2.0) if np.isfinite(bo_vol) else 0.0
    depth = metrics.get("pbr_retest_depth_pct", float("nan"))
    retest_score = 1.0 - min(1.0, float(depth) / 0.5) if np.isfinite(depth) else 0.0
    body = _norm_strength_component(metrics.get("pbr_signal_body_pct", float("nan")), 0.03)
    sym = metrics.get("pbr_pivot_symmetry", float("nan"))
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


def pbr_strength_from_event(ev: dict[str, Any]) -> dict[str, float]:
    """Extract strength metrics from a zone event dict."""
    return {k: _finite_or_nan(ev.get(k, float("nan"))) for k in PBR_STRENGTH_FIELDS}


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


def make_pbr_zone_id(pivot_week_end: str, zone_lower: float, zone_upper: float) -> str:
    """Stable PBR zone identity: pivot week + rounded bounds."""
    return f"{pivot_week_end}|{float(zone_lower):.4f}|{float(zone_upper):.4f}"


def find_pbr_retest_and_signal(
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
) -> tuple[int | None, int | None, int | None]:
    """
    Find the next retest after ``scan_start``, then the first green close signal
    within ``max_days_after_retest`` bars (inclusive of retest bar).

    Retest: Low <= zone_upper and Close > zone_upper, prior Close >= zone_lower.
    Signal: Close > Open and Close > zone_upper.
    Fill: next session open (signal_bar + 1), if available.

    If ``stop_at`` is set, only consider bars ``<= stop_at`` for retest/signal.
    Returns (retest_bar, signal_bar, fill_bar).
    """
    if scan_start < 0 or scan_start >= n:
        return None, None, None
    end_scan = n - 1 if stop_at is None else min(n - 1, int(stop_at))
    if end_scan < scan_start:
        return None, None, None
    zl = float(zone_lower)
    zh = float(zone_upper)
    max_entry_days = max(0, int(max_days_after_retest))
    retest_bar: int | None = None
    for di in range(scan_start, end_scan + 1):
        if di <= 0:
            continue
        if not (lo[di] <= zh + 1e-9 and cl[di] > zh + 1e-9):
            continue
        if cl[di - 1] < zl - 1e-9:
            continue
        retest_bar = di
        break
    if retest_bar is None:
        return None, None, None
    end_di = min(end_scan, retest_bar + max_entry_days)
    for di in range(retest_bar, end_di + 1):
        if cl[di] > op[di] + 1e-12 and cl[di] > zh + 1e-9:
            fill = di + 1 if di + 1 < n else None
            return retest_bar, di, fill
    return retest_bar, None, None


def compute_pbr_touch_stream(
    df: pd.DataFrame,
    *,
    band_pct: float = 0.015,
    strong_pre_pivot_bars: int = 3,
    strong_pre_pivot_pct: float = 0.10,
    strong_post_pivot_bars: int = 3,
    strong_post_pivot_pct: float = 0.10,
    strong_pivot_mode: str = "either",
    breakout_confirmation: float = 0.03,
    max_days_after_retest: int = 2,
    zone_price_round_decimals: int = 2,
    debug_symbol: Optional[str] = None,
) -> dict[str, Any]:
    """
    Weekly pivot-high zones; two-stage weekly breakout (close > upper, then high > upper*(1+conf));
    daily retest/entry begins the Monday after the confirmation week.

    Emits the first retest/signal opportunity per zone. The backtest enforces zone lifecycle
    when ``pbr_second_chance_after_win`` is enabled:
      - 1st purchase closes with pnl_pct > 0 → allow one more purchase (resume scan after exit)
      - 1st purchase closes flat/loss → retire zone
      - 2nd purchase → retire zone immediately (no further entries)
    When that flag is False (default), the zone is retired after the first purchase.

    Each zone event includes strength metrics (``PBR_STRENGTH_FIELDS``): pivot quality,
    POC/prior-extreme confluence, breakout/confirmation power, retest quality, and
    ``pbr_zone_strength`` composite (0–1, audit/research).

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
            "pbr_zone_events": [],
            "pbr_entry_opportunities": [],
            "pbr_entry_signal_bars": [],
            "pbr_entry_fill_bars": [],
            "pbr_audit": [],
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

    pivots = _weekly_pivot_indices(
        wh,
        wl,
        pre_bars=int(strong_pre_pivot_bars),
        post_bars=int(strong_post_pivot_bars),
        pre_pct=float(strong_pre_pivot_pct),
        post_pct=float(strong_post_pivot_pct),
        pivot_mode=strong_pivot_mode,
    )

    dec = max(0, int(zone_price_round_decimals))
    bo_conf = max(0.0, float(breakout_confirmation))
    max_entry_days = max(0, int(max_days_after_retest))

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

    for wi in pivots:
        pivot_high = float(wh[wi])
        touch, zl, zh = _round_bounds(pivot_high, band_pct, dec)
        pivot_week_end = w_index[wi].strftime("%Y-%m-%d")
        zone_id = make_pbr_zone_id(pivot_week_end, zl, zh)
        pivot_monday = _week_monday(w_index[wi])
        pivot_daily_start = int(
            np.searchsorted(dates_norm.to_numpy(), pivot_monday.to_numpy(), side="left")
        )
        if pivot_daily_start >= n:
            continue

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
                retest_bar, entry_signal_bar, entry_fill_bar = find_pbr_retest_and_signal(
                    lo,
                    cl,
                    op,
                    scan_start=scan_start_bar,
                    zone_lower=zl,
                    zone_upper=zh,
                    max_days_after_retest=max_entry_days,
                    n=n,
                )
                if entry_signal_bar is not None and entry_fill_bar is not None:
                    entry_signal_bars.append(entry_signal_bar)
                    entry_fill_bars.append(entry_fill_bar)
                    entry_opportunities.append(
                        {
                            "pbr_zone_id": zone_id,
                            "zone_lower": zl,
                            "zone_upper": zh,
                            "zone_center": touch,
                            "retest_bar": retest_bar,
                            "entry_signal_bar": entry_signal_bar,
                            "entry_fill_bar": entry_fill_bar,
                            "opportunity_index": 0,
                            "scan_start_bar": scan_start_bar,
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
        strength.update(_pbr_poc_confluence(hi, lo, cl, vol, pivot_daily_end, touch))
        strength.update(_pbr_prior_extreme_confluence(wh, wi, touch, prior_weeks=_PBR_PRIOR_WEEKS))
        strength.update(
            _pbr_breakout_strength(
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
            _pbr_retest_strength(
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
        strength["pbr_zone_strength"] = _compute_pbr_zone_strength(strength)

        ev = {
            "pbr_zone_id": zone_id,
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
            **strength,
        }
        if entry_opportunities and entry_opportunities[-1].get("pbr_zone_id") == zone_id:
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
                "pbr_zone_id": zone_id,
            }
        )
        audit.append(ev)

        if debug_symbol:
            print(
                f"[PBR] {debug_symbol} id={zone_id} pivot={pivot_monday.date()} z=({zl},{zh}) "
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
        "pbr_zone_events": zone_events,
        "pbr_entry_opportunities": entry_opportunities,
        "pbr_entry_signal_bars": sorted(set(entry_signal_bars)),
        "pbr_entry_fill_bars": sorted(set(entry_fill_bars)),
        "pbr_entry_bars": sorted(set(entry_signal_bars)),
        "pbr_audit": audit,
    }
