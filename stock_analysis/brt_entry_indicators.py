"""
Point-in-time technical snapshot at BRT entry (uses only bars <= entry bar).

Populates BRT_Closed / BRT_Open columns IND_* / IND_*_LAST / IND_*_COUNT plus summary counts.
States are BULL / BEAR / NEUTRAL relative to **price strength** (not Recognia).
IND_<id>_COUNT = number of price-bullish bars for that signal in the trailing lookback window.
IND_ENTRY_BULL_N = trade-aligned count of indicator *types* bullish at the entry bar (max 47).
Summary counts IND_ENTRY_* are **trade-aligned**: for LONG, BULL=price-bullish;
for SHORT, BULL=price-bearish (favorable to the short).
"""

from __future__ import annotations

import hashlib
import json
import os
import pickle
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

INDICATOR_CACHE_VERSION = 3
# Rolling/pattern lookback slack when extending cache after new daily bars are appended.
_INDICATOR_EXTEND_WARMUP_BARS = 350
# Trailing bars for IND_<id>_COUNT (price-bullish firings of that signal in the window).
INDICATOR_COUNT_LOOKBACK_BARS = 120

# Each id produces columns IND_<id> and IND_<id>_LAST (YYYYMMDD)
INDICATOR_IDS: tuple[str, ...] = (
    # Trend / moving averages
    "SMA20_OVER_SMA50",
    "SMA50_OVER_SMA200",
    "PRICE_OVER_SMA20",
    "PRICE_OVER_SMA50",
    "PRICE_OVER_SMA200",
    "EMA12_OVER_EMA26",
    # Oscillators / momentum
    "RSI14",
    "MACD_HIST",
    "MACD_LINE_OVER_SIGNAL",
    "STOCH_K_OVER_D",
    "WILLR14",
    "CCI20",
    "MFI14",
    "ROC10",
    "CMO14",
    # Trend strength
    "ADX_DI",
    # Volatility / bands
    "BB_PCTB",
    "ATR_RATIO",  # ATR14 / close vs its 60d median — expansion vs compression
    # Volume
    "OBV_SLOPE10",
    "VOL_SURGE",  # vol vs 20d SMA
    # Classic pattern heuristics (rough; not Recognia)
    "DOUBLE_BOTTOM",
    "DOUBLE_TOP",
    "HEAD_SHOULDERS_BOTTOM",
    "HEAD_SHOULDERS_TOP",
    "SYMMETRICAL_TRI",
    "WEDGE_FALLING_CONT",
    "WEDGE_RISING_CONT",
    "FLAG_CONT",
    "MEGAPHONE",
    "DIAMOND",
    "TRI_ASCENDING",
    "TRI_DESCENDING",
    "UPSIDE_BREAKOUT",
    "DIAMOND_BOTTOM",
    "DIAMOND_TOP",
    "BOTTOM_TRI",
    "TOP_TRI",
    "PENNANT_CONT",
    # Candlestick / multi-bar (last formation date in lookback)
    "CANDLE_HAMMER",
    "CANDLE_SHOOTING_STAR",
    "CANDLE_BULL_ENGULF",
    "CANDLE_BEAR_ENGULF",
    "CANDLE_MORNING_STAR",
    "CANDLE_EVENING_STAR",
    "CANDLE_THREE_SOLDIERS",
    "CANDLE_THREE_CROWS",
    "CANDLE_DOJI",
)

_LEGACY_IND_SCORE_WEIGHTS_PATH = Path(__file__).with_name("ind_score_weights.json")
_IND_SCORE_WEIGHTS_STEM = "ind_score_weights"
_IND_SCORE_ENABLED = True
_IND_SCORE_WEIGHTS_PATH_OVERRIDE: Optional[str] = None
_IND_SCORE_WEIGHTS_CACHE: Optional[dict[str, float]] = None


def ind_score_weights_storage_dir() -> Path:
    """Directory containing ``ind_score_weights*.json`` files."""
    return Path(__file__).resolve().parent


def list_timestamped_ind_score_weights_files() -> list[Path]:
    """All ``ind_score_weights_<stamp>.json`` files (excludes bare ``ind_score_weights.json``)."""
    out: list[Path] = []
    for p in ind_score_weights_storage_dir().glob(f"{_IND_SCORE_WEIGHTS_STEM}_*.json"):
        if p.is_file() and p.name != _LEGACY_IND_SCORE_WEIGHTS_PATH.name:
            out.append(p)
    return out


def ind_score_weights_content_hash(path: Path) -> str:
    """Stable SHA-256 of weights JSON (sorted keys) for deduplication."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def resolve_default_ind_score_weights_path() -> Optional[Path]:
    """
    Default weights file: canonical path for the newest weights *content*.

    Among all ``ind_score_weights_*.json`` files, group by content hash, pick the group
    whose newest mtime is latest (most recently built weights), then return the
    earliest filename in that group so identical weights always resolve to one file.
    Falls back to legacy ``ind_score_weights.json`` if no stamped files exist.
    """
    stamped = list_timestamped_ind_score_weights_files()
    if stamped:
        by_hash: dict[str, list[Path]] = {}
        for p in stamped:
            try:
                by_hash.setdefault(ind_score_weights_content_hash(p), []).append(p)
            except (OSError, json.JSONDecodeError, TypeError):
                continue
        if by_hash:
            latest_group = max(
                by_hash.values(),
                key=lambda files: max(f.stat().st_mtime for f in files),
            )
            return min(latest_group, key=lambda p: p.name)
    if _LEGACY_IND_SCORE_WEIGHTS_PATH.is_file():
        return _LEGACY_IND_SCORE_WEIGHTS_PATH.resolve()
    return None


def default_ind_score_weights_path() -> Path:
    """Path used when no override is set (latest timestamped file, else legacy JSON)."""
    resolved = resolve_default_ind_score_weights_path()
    if resolved is not None:
        return Path(resolved)
    return _LEGACY_IND_SCORE_WEIGHTS_PATH


def default_new_ind_score_weights_output_path() -> Path:
    """Path for a newly built weights file (wall-clock stamp in the filename)."""
    from datetime import datetime

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return ind_score_weights_storage_dir() / f"{_IND_SCORE_WEIGHTS_STEM}_{stamp}.json"


def configure_ind_score(
    *,
    enabled: bool = True,
    weights_path: Optional[str | Path] = None,
) -> None:
    """Enable/disable IND_SCORE and optionally override the weights JSON path."""
    global _IND_SCORE_ENABLED, _IND_SCORE_WEIGHTS_PATH_OVERRIDE, _IND_SCORE_WEIGHTS_CACHE
    _IND_SCORE_ENABLED = bool(enabled)
    _IND_SCORE_WEIGHTS_PATH_OVERRIDE = (
        str(weights_path).strip() if weights_path is not None and str(weights_path).strip() else None
    )
    _IND_SCORE_WEIGHTS_CACHE = None


def load_ind_score_weights(path: Optional[str | Path] = None) -> dict[str, float]:
    """Load per-indicator weights (mean PNL_PCT when IND_<id> is BULL at entry)."""
    global _IND_SCORE_WEIGHTS_CACHE
    if _IND_SCORE_WEIGHTS_CACHE is not None and path is None and _IND_SCORE_WEIGHTS_PATH_OVERRIDE is None:
        return _IND_SCORE_WEIGHTS_CACHE
    if path is not None:
        p = Path(path)
    elif _IND_SCORE_WEIGHTS_PATH_OVERRIDE:
        p = Path(_IND_SCORE_WEIGHTS_PATH_OVERRIDE)
    else:
        p = default_ind_score_weights_path()
    if not p.is_file():
        return {}
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    raw = payload.get("weights") if isinstance(payload, dict) else payload
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for iid in INDICATOR_IDS:
        v = raw.get(iid)
        if v is None:
            continue
        try:
            out[iid] = float(v)
        except (TypeError, ValueError):
            continue
    if path is None and _IND_SCORE_WEIGHTS_PATH_OVERRIDE is None:
        _IND_SCORE_WEIGHTS_CACHE = out
    return out


_DEFAULT_MANDATORY_IND_STATES_PATH = Path(__file__).with_name("mandatory_ind_states.json")
_MANDATORY_IND_STATES_CACHE: Optional[tuple[str, float, dict[str, str]]] = None
_VALID_IND_STATES = frozenset({"BULL", "BEAR", "NEUTRAL"})


def resolve_mandatory_ind_states_path(raw: Optional[str | Path] = None) -> Optional[Path]:
    """Resolve mandatory IND states JSON (cwd, stock_analysis/, repo root). Blank = disabled."""
    s = str(raw or "").strip()
    if not s:
        return None
    p = Path(s)
    if p.is_file():
        return p.resolve()
    script_dir = Path(__file__).resolve().parent
    for base in (Path.cwd(), script_dir, script_dir.parent):
        candidate = (base / s).resolve()
        if candidate.is_file():
            return candidate
    return None


def load_mandatory_ind_states(path: Optional[str | Path] = None) -> dict[str, str]:
    """Load {indicator_id: BULL|BEAR|NEUTRAL} from JSON (``rules`` object or top-level map)."""
    global _MANDATORY_IND_STATES_CACHE
    resolved = resolve_mandatory_ind_states_path(path)
    if resolved is None:
        return {}
    key = str(resolved)
    mtime = resolved.stat().st_mtime
    if _MANDATORY_IND_STATES_CACHE is not None:
        cached_key, cached_mtime, cached_rules = _MANDATORY_IND_STATES_CACHE
        if cached_key == key and cached_mtime == mtime:
            return dict(cached_rules)
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    raw_rules: Any = payload
    if isinstance(payload, dict) and isinstance(payload.get("rules"), dict):
        raw_rules = payload["rules"]
    if not isinstance(raw_rules, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw_rules.items():
        iid = str(k or "").strip().upper()
        if iid.startswith("IND_"):
            iid = iid[4:]
        if iid.endswith("_LAST"):
            continue
        if iid not in INDICATOR_IDS:
            continue
        state = str(v or "").strip().upper()
        if state not in _VALID_IND_STATES:
            continue
        out[iid] = state
    _MANDATORY_IND_STATES_CACHE = (key, mtime, dict(out))
    return out


def mandatory_ind_states_passes(
    pre: Optional["_Precomputed"],
    bar_i: int,
    side: str,
    rules: dict[str, str],
) -> bool:
    """True when every rule matches IND_<id> on bar_i (raw price state labels)."""
    if not rules:
        return True
    if pre is None or bar_i < 0:
        return False
    snap = snapshot_for_entry(pre, bar_i, side)
    for iid, req in rules.items():
        actual = str(snap.get(f"IND_{iid}", "NEUTRAL")).strip().upper()
        if actual != str(req).strip().upper():
            return False
    return True


def mandatory_ind_states_first_miss(
    pre: Optional["_Precomputed"],
    bar_i: int,
    side: str,
    rules: dict[str, str],
) -> Optional[tuple[str, str, str]]:
    """Return (indicator_id, required, actual) for the first failing rule, or None if all pass."""
    if not rules:
        return None
    if pre is None or bar_i < 0:
        return ("__precompute__", "available", "missing")
    snap = snapshot_for_entry(pre, bar_i, side)
    for iid, req in rules.items():
        actual = str(snap.get(f"IND_{iid}", "NEUTRAL")).strip().upper()
        req_u = str(req).strip().upper()
        if actual != req_u:
            return (iid, req_u, actual)
    return None


def ind_score_at_bar(
    pre: Optional["_Precomputed"],
    bar_i: int,
    weights: Optional[dict[str, float]] = None,
) -> Optional[float]:
    """IND_SCORE at bar ``bar_i`` (sum weights for price-BULL indicators; no snapshot dict needed)."""
    if pre is None or bar_i < 0 or bar_i >= len(pre.dates):
        return None
    pre = _ensure_gate_arrays(pre)
    w = weights if weights is not None else load_ind_score_weights()
    if not w:
        return None
    total = 0.0
    for iid in INDICATOR_IDS:
        arr = pre.states.get(iid)
        if arr is not None and bar_i < len(arr) and int(arr[bar_i]) > 0:
            total += float(w.get(iid, 0.0))
    return total


def compute_ind_score(
    entry_indicators: Optional[dict[str, str]],
    weights: Optional[dict[str, float]] = None,
) -> Optional[float]:
    """Sum weights for each IND_<id> column that reads BULL at entry."""
    if not entry_indicators:
        return None
    w = weights if weights is not None else load_ind_score_weights()
    if not w:
        return None
    total = 0.0
    for iid in INDICATOR_IDS:
        if entry_indicators.get(f"IND_{iid}") == "BULL":
            total += float(w.get(iid, 0.0))
    return total


def apply_ind_score_to_entry_indicators(
    entry_indicators: dict[str, str],
    *,
    weights: Optional[dict[str, float]] = None,
) -> None:
    """Set IND_SCORE on ``entry_indicators`` when scoring is enabled and weights exist."""
    if not _IND_SCORE_ENABLED or not entry_indicators:
        return
    sc = compute_ind_score(entry_indicators, weights=weights)
    if sc is None:
        return
    entry_indicators["IND_SCORE"] = f"{sc:.2f}"


def entry_indicator_csv_headers() -> list[str]:
    cols: list[str] = []
    for iid in INDICATOR_IDS:
        cols.append(f"IND_{iid}")
        cols.append(f"IND_{iid}_LAST")
        cols.append(f"IND_{iid}_COUNT")
    cols.extend(
        [
            "IND_ENTRY_BULL_N",
            "IND_ENTRY_BEAR_N",
            "IND_DIFF",
            "IND_ENTRY_NEUTRAL_N",
            "IND_SCORE",
        ]
    )
    return cols


def _ymd(ts: Any) -> str:
    if ts is None:
        return ""
    t = pd.Timestamp(ts)
    return t.strftime("%Y%m%d")


def _ema(x: np.ndarray, span: int) -> np.ndarray:
    n = len(x)
    out = np.full(n, np.nan, dtype=np.float64)
    if n == 0 or span <= 0:
        return out
    alpha = 2.0 / (span + 1.0)
    out[0] = x[0]
    for i in range(1, n):
        if np.isnan(x[i]):
            out[i] = out[i - 1]
        else:
            out[i] = alpha * x[i] + (1.0 - alpha) * (out[i - 1] if not np.isnan(out[i - 1]) else x[i])
    return out


def _sma(x: np.ndarray, w: int) -> np.ndarray:
    return pd.Series(x).rolling(w, min_periods=w).mean().to_numpy(dtype=np.float64)


def _rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(close)
    out = np.zeros(n, dtype=np.float64)
    if n < period + 1:
        return out
    delta = np.diff(close, prepend=close[0])
    gain = np.maximum(delta, 0.0)
    loss = np.maximum(-delta, 0.0)
    ag = pd.Series(gain).ewm(alpha=1.0 / period, adjust=False).mean().to_numpy()
    al = pd.Series(loss).ewm(alpha=1.0 / period, adjust=False).mean().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.where(al > 1e-12, ag / al, np.where(ag > 1e-12, np.inf, 0.0))
        rsi = 100.0 - (100.0 / (1.0 + rs))
    out = np.where(np.isfinite(rsi), rsi, 50.0)
    return out


def _macd(close: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    ema12 = _ema(close, 12)
    ema26 = _ema(close, 26)
    line = ema12 - ema26
    signal = _ema(line, 9)
    hist = line - signal
    return line, signal, hist


def _stoch(high: np.ndarray, low: np.ndarray, close: np.ndarray, k: int = 14, d: int = 3) -> tuple[np.ndarray, np.ndarray]:
    lowest = pd.Series(low).rolling(k, min_periods=k).min().to_numpy()
    highest = pd.Series(high).rolling(k, min_periods=k).max().to_numpy()
    rng = highest - lowest
    kf = np.zeros_like(close, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        kf = np.where(rng > 1e-12, (close - lowest) / rng * 100.0, 50.0)
    df = pd.Series(kf).rolling(d, min_periods=d).mean().to_numpy()
    return kf, df


def _williams_r(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    hh = pd.Series(high).rolling(period, min_periods=period).max().to_numpy()
    ll = pd.Series(low).rolling(period, min_periods=period).min().to_numpy()
    rng = hh - ll
    out = np.full_like(close, np.nan, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(rng > 1e-12, (hh - close) / rng * (-100.0), np.nan)
    return out


def _cci(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 20) -> np.ndarray:
    tp = (high + low + close) / 3.0
    n = len(tp)
    sma = pd.Series(tp).rolling(period, min_periods=period).mean().to_numpy()
    mad = np.zeros(n, dtype=np.float64)
    for i in range(period - 1, n):
        w = tp[i - period + 1 : i + 1]
        mw = float(np.mean(w))
        mad[i] = float(np.mean(np.abs(w - mw)))
    out = np.zeros_like(close, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(mad > 1e-12, (tp - sma) / (0.015 * mad), 0.0)
    return out


def _mfi(high: np.ndarray, low: np.ndarray, close: np.ndarray, vol: np.ndarray, period: int = 14) -> np.ndarray:
    tp = (high + low + close) / 3.0
    raw = tp * np.maximum(vol, 0.0)
    pmf = np.zeros_like(close)
    nmf = np.zeros_like(close)
    for i in range(1, len(close)):
        if tp[i] > tp[i - 1]:
            pmf[i] = raw[i]
        elif tp[i] < tp[i - 1]:
            nmf[i] = raw[i]
    roll_p = pd.Series(pmf).rolling(period, min_periods=period).sum().to_numpy()
    roll_n = pd.Series(nmf).rolling(period, min_periods=period).sum().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        mfr = np.where(roll_n > 1e-12, roll_p / roll_n, 1.0)
    return 100.0 - (100.0 / (1.0 + mfr))


def _cmo(close: np.ndarray, period: int = 14) -> np.ndarray:
    delta = np.diff(close, prepend=close[0])
    su = pd.Series(np.maximum(delta, 0.0)).rolling(period, min_periods=period).sum().to_numpy()
    sd = pd.Series(np.maximum(-delta, 0.0)).rolling(period, min_periods=period).sum().to_numpy()
    tot = su + sd
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(tot > 1e-12, (su - sd) / tot * 100.0, 0.0)


def _adx_dmi(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = len(close)
    tr = np.zeros(n)
    pdm = np.zeros(n)
    mdm = np.zeros(n)
    for i in range(1, n):
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i - 1])
        lc = abs(low[i] - close[i - 1])
        tr[i] = max(hl, hc, lc)
        up = high[i] - high[i - 1]
        dn = low[i - 1] - low[i]
        pdm[i] = up if up > dn and up > 0 else 0.0
        mdm[i] = dn if dn > up and dn > 0 else 0.0
    atr = pd.Series(tr).ewm(alpha=1.0 / period, adjust=False).mean().to_numpy()
    pdi = 100.0 * pd.Series(pdm).ewm(alpha=1.0 / period, adjust=False).mean().to_numpy() / np.maximum(atr, 1e-12)
    mdi = 100.0 * pd.Series(mdm).ewm(alpha=1.0 / period, adjust=False).mean().to_numpy() / np.maximum(atr, 1e-12)
    with np.errstate(divide="ignore", invalid="ignore"):
        dx = np.where((pdi + mdi) > 1e-12, np.abs(pdi - mdi) / (pdi + mdi) * 100.0, 0.0)
    adx = pd.Series(dx).ewm(alpha=1.0 / period, adjust=False).mean().to_numpy()
    return adx, pdi, mdi


def _obv(close: np.ndarray, vol: np.ndarray) -> np.ndarray:
    obv = np.zeros_like(close, dtype=np.float64)
    for i in range(1, len(close)):
        if close[i] > close[i - 1]:
            obv[i] = obv[i - 1] + vol[i]
        elif close[i] < close[i - 1]:
            obv[i] = obv[i - 1] - vol[i]
        else:
            obv[i] = obv[i - 1]
    return obv


def _state_tri(x: np.ndarray, bull: np.ndarray, bear: np.ndarray) -> np.ndarray:
    """1 bull, -1 bear, 0 neutral."""
    s = np.zeros(len(x), dtype=np.int8)
    s[bull & ~bear] = 1
    s[bear & ~bull] = -1
    s[bull & bear] = 0
    return s


def _last_dir_idx(state: np.ndarray) -> np.ndarray:
    n = len(state)
    out = np.full(n, -1, dtype=np.int32)
    last_j = -1
    for i in range(n):
        if state[i] != 0:
            last_j = i
        out[i] = last_j
    return out


def _bull_direction_count_series(state: np.ndarray, lookback: int) -> np.ndarray:
    """Trailing-window count of bars where this signal is price-bullish (state > 0)."""
    n = len(state)
    out = np.zeros(n, dtype=np.int16)
    if n == 0 or lookback <= 0:
        return out
    pos = (state > 0).astype(np.int32)
    cs = np.zeros(n + 1, dtype=np.int32)
    cs[1:] = np.cumsum(pos)
    for i in range(n):
        j0 = max(0, i - lookback + 1)
        out[i] = int(cs[i + 1] - cs[j0])
    return out


def _build_bull_count_dict(
    states: dict[str, np.ndarray],
    n: int,
    lookback: int = INDICATOR_COUNT_LOOKBACK_BARS,
) -> dict[str, np.ndarray]:
    counts: dict[str, np.ndarray] = {}
    for iid in INDICATOR_IDS:
        arr = states.get(iid)
        if arr is None or len(arr) != n:
            counts[iid] = np.zeros(n, dtype=np.int16)
        else:
            counts[iid] = _bull_direction_count_series(arr, lookback)
    return counts


def _local_min_idx(low: np.ndarray, i: int, w: int = 2) -> bool:
    if i < w or i >= len(low) - w:
        return False
    return low[i] == np.min(low[i - w : i + w + 1])


def _local_max_idx(high: np.ndarray, i: int, w: int = 2) -> bool:
    if i < w or i >= len(high) - w:
        return False
    return high[i] == np.max(high[i - w : i + w + 1])


def _double_bottom_state(low: np.ndarray, high: np.ndarray, close: np.ndarray, n: int, look: int = 80) -> np.ndarray:
    s = np.zeros(n, dtype=np.int8)
    tol = 0.015
    for i in range(40, n):
        a0 = max(0, i - look)
        lows_idx = [j for j in range(a0, i - 10) if _local_min_idx(low, j)]
        if len(lows_idx) < 2:
            continue
        j1, j2 = lows_idx[-2], lows_idx[-1]
        if j2 <= j1 + 5:
            continue
        l1, l2 = low[j1], low[j2]
        if abs(l1 - l2) / max(l1, 1e-12) > tol:
            continue
        mid = int((j1 + j2) / 2)
        peak = np.max(high[j1 : j2 + 1])
        trough = min(l1, l2)
        if peak < trough * (1.0 + 0.02):
            continue
        if close[i] > peak * 0.998:
            s[i] = 1
    return s


def _double_top_state(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int, look: int = 80) -> np.ndarray:
    s = np.zeros(n, dtype=np.int8)
    tol = 0.015
    for i in range(40, n):
        a0 = max(0, i - look)
        highs_idx = [j for j in range(a0, i - 10) if _local_max_idx(high, j)]
        if len(highs_idx) < 2:
            continue
        j1, j2 = highs_idx[-2], highs_idx[-1]
        if j2 <= j1 + 5:
            continue
        h1, h2 = high[j1], high[j2]
        if abs(h1 - h2) / max(h1, 1e-12) > tol:
            continue
        mid_lo = np.min(low[j1 : j2 + 1])
        if mid_lo > min(h1, h2) * 0.995:
            continue
        if close[i] < mid_lo * 1.002:
            s[i] = -1
    return s


def _hs_bottom_state(low: np.ndarray, high: np.ndarray, close: np.ndarray, n: int) -> np.ndarray:
    s = np.zeros(n, dtype=np.int8)
    for i in range(60, n):
        lows = [j for j in range(i - 60, i - 5) if _local_min_idx(low, j)]
        if len(lows) < 3:
            continue
        jL, jH, jR = lows[-3], lows[-2], lows[-1]
        if not (low[jH] < low[jL] * 0.998 and low[jH] < low[jR] * 0.998):
            continue
        neckline = max(high[jL:jH].max(), high[jH:jR].max()) if jR > jH else 0
        if neckline <= 0:
            continue
        if close[i] > neckline * 1.0:
            s[i] = 1
    return s


def _hs_top_state(low: np.ndarray, high: np.ndarray, close: np.ndarray, n: int) -> np.ndarray:
    s = np.zeros(n, dtype=np.int8)
    for i in range(60, n):
        highs = [j for j in range(i - 60, i - 5) if _local_max_idx(high, j)]
        if len(highs) < 3:
            continue
        jL, jH, jR = highs[-3], highs[-2], highs[-1]
        if not (high[jH] > high[jL] * 1.002 and high[jH] > high[jR] * 1.002):
            continue
        neckline = min(low[jL:jH].min(), low[jH:jR].min()) if jR > jH else 0
        if neckline <= 0:
            continue
        if close[i] < neckline * 1.0:
            s[i] = -1
    return s


def _range_contract(high: np.ndarray, low: np.ndarray, i: int, w1: int = 20, w2: int = 10) -> bool:
    if i < w1 + w2:
        return False
    r1 = np.mean(high[i - w1 - w2 : i - w2] - low[i - w1 - w2 : i - w2])
    r2 = np.mean(high[i - w2 : i] - low[i - w2 : i])
    return r2 < r1 * 0.85 if r1 > 1e-12 else False


def _symmetrical_tri_state(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int) -> np.ndarray:
    s = np.zeros(n, dtype=np.int8)
    for i in range(40, n):
        if not _range_contract(high, low, i):
            continue
        hh = pd.Series(high[: i + 1]).rolling(15, min_periods=15).max().iloc[-1]
        ll = pd.Series(low[: i + 1]).rolling(15, min_periods=15).min().iloc[-1]
        mid = (hh + ll) / 2.0
        if close[i] > mid * 1.002:
            s[i] = 1
        elif close[i] < mid * 0.998:
            s[i] = -1
    return s


def _wedge_falling_cont(high: np.ndarray, low: np.ndarray, close: np.ndarray, sma50: np.ndarray, n: int) -> np.ndarray:
    """Bullish continuation: both slopes down, converging, price above SMA50."""
    s = np.zeros(n, dtype=np.int8)
    w = 15
    for i in range(w + 5, n):
        if not np.isfinite(sma50[i]) or close[i] < sma50[i]:
            continue
        h0, h1 = high[i - w], high[i]
        l0, l1 = low[i - w], low[i]
        if h1 >= h0 or l1 >= l0:
            continue
        if (h0 - h1) > (l0 - l1) * 1.05:
            s[i] = 1
    return s


def _wedge_rising_cont(high: np.ndarray, low: np.ndarray, close: np.ndarray, sma50: np.ndarray, n: int) -> np.ndarray:
    s = np.zeros(n, dtype=np.int8)
    w = 15
    for i in range(w + 5, n):
        if not np.isfinite(sma50[i]) or close[i] > sma50[i]:
            continue
        h0, h1 = high[i - w], high[i]
        l0, l1 = low[i - w], low[i]
        if h1 <= h0 or l1 <= l0:
            continue
        if (l1 - l0) > (h1 - h0) * 1.05:
            s[i] = -1
    return s


def _flag_cont(close: np.ndarray, high: np.ndarray, low: np.ndarray, n: int) -> np.ndarray:
    s = np.zeros(n, dtype=np.int8)
    for i in range(25, n):
        pole = (close[i - 20] - close[i - 25]) / max(close[i - 25], 1e-12)
        if pole < 0.05:
            continue
        box_hi = np.max(high[i - 10 : i + 1])
        box_lo = np.min(low[i - 10 : i + 1])
        if (box_hi - box_lo) / max(close[i], 1e-12) > 0.06:
            continue
        if close[i] > box_hi * 0.998:
            s[i] = 1
        elif close[i] < box_lo * 1.002:
            s[i] = -1
    return s


def _megaphone_state(high: np.ndarray, low: np.ndarray, n: int) -> np.ndarray:
    s = np.zeros(n, dtype=np.int8)
    w = 25
    for i in range(w, n):
        hh_slope = high[i] - high[i - w]
        ll_slope = low[i - w] - low[i]
        if hh_slope > 0 and ll_slope > 0 and (high[i] - low[i]) > (high[i - w] - low[i - w]) * 1.1:
            s[i] = -1
    return s


def _diamond_state(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int) -> np.ndarray:
    s = np.zeros(n, dtype=np.int8)
    for i in range(40, n):
        w = 20
        r_early = np.mean(high[i - 40 : i - 20] - low[i - 40 : i - 20])
        r_late = np.mean(high[i - 20 : i] - low[i - 20 : i])
        if r_early < 1e-12:
            continue
        if r_late < r_early * 0.75:
            mid = (np.max(high[i - 5 : i + 1]) + np.min(low[i - 5 : i + 1])) / 2.0
            if close[i] > mid * 1.01:
                s[i] = 1
            elif close[i] < mid * 0.99:
                s[i] = -1
    return s


def _tri_ascending(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int) -> np.ndarray:
    s = np.zeros(n, dtype=np.int8)
    w = 20
    for i in range(w, n):
        hi_flat = abs(high[i] - np.mean(high[i - w : i + 1])) / max(high[i], 1e-12) < 0.02
        lo_up = low[i] > low[i - w] * 1.02
        if hi_flat and lo_up and close[i] > np.max(high[i - w : i]) * 0.999:
            s[i] = 1
    return s


def _tri_descending(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int) -> np.ndarray:
    s = np.zeros(n, dtype=np.int8)
    w = 20
    for i in range(w, n):
        lo_flat = abs(low[i] - np.mean(low[i - w : i + 1])) / max(low[i], 1e-12) < 0.02
        hi_dn = high[i] < high[i - w] * 0.98
        if lo_flat and hi_dn and close[i] < np.min(low[i - w : i]) * 1.001:
            s[i] = -1
    return s


def _upside_breakout(close: np.ndarray, high: np.ndarray, n: int) -> np.ndarray:
    s = np.zeros(n, dtype=np.int8)
    for i in range(30, n):
        res = np.max(high[i - 30 : i])
        if close[i] > res * 1.002 and close[i] > close[i - 1]:
            s[i] = 1
    return s


def _candle_scan(
    o: np.ndarray,
    h: np.ndarray,
    l: np.ndarray,
    c: np.ndarray,
    kind: str,
    i: int,
) -> bool:
    if i < 2:
        return False
    body = abs(c[i] - o[i])
    rng = h[i] - l[i]
    if rng <= 1e-12:
        return False
    if kind == "DOJI":
        return body / rng < 0.1
    if kind == "HAMMER":
        lower = min(o[i], c[i]) - l[i]
        upper = h[i] - max(o[i], c[i])
        return lower > 2 * body and upper < body * 0.5 and c[i] > o[i] - body
    if kind == "SHOOTING_STAR":
        upper = h[i] - max(o[i], c[i])
        lower = min(o[i], c[i]) - l[i]
        return upper > 2 * body and lower < body * 0.5
    if kind == "BULL_ENGULF":
        return c[i] > o[i] and c[i - 1] < o[i - 1] and c[i] >= o[i - 1] and o[i] <= c[i - 1]
    if kind == "BEAR_ENGULF":
        return c[i] < o[i] and c[i - 1] > o[i - 1] and c[i] <= o[i - 1] and o[i] >= c[i - 1]
    if kind == "MORNING_STAR":
        if i < 2:
            return False
        mid = i - 1
        return (
            c[i - 2] < o[i - 2]
            and abs(c[mid] - o[mid]) / (h[mid] - l[mid] + 1e-12) < 0.35
            and c[i] > o[i]
            and c[i] > (o[i - 2] + c[i - 2]) / 2.0
        )
    if kind == "EVENING_STAR":
        mid = i - 1
        return (
            c[i - 2] > o[i - 2]
            and abs(c[mid] - o[mid]) / (h[mid] - l[mid] + 1e-12) < 0.35
            and c[i] < o[i]
            and c[i] < (o[i - 2] + c[i - 2]) / 2.0
        )
    if kind == "THREE_SOLDIERS":
        if i < 2:
            return False
        return all(c[i - k] > o[i - k] for k in range(3)) and c[i] > c[i - 1] > c[i - 2]
    if kind == "THREE_CROWS":
        if i < 2:
            return False
        return all(c[i - k] < o[i - k] for k in range(3)) and c[i] < c[i - 1] < c[i - 2]
    return False


def _candle_state_series(
    o: np.ndarray, h: np.ndarray, l: np.ndarray, c: np.ndarray, kind: str, bull: int, bear: int
) -> np.ndarray:
    n = len(c)
    s = np.zeros(n, dtype=np.int8)
    for i in range(2, n):
        if _candle_scan(o, h, l, c, kind, i):
            s[i] = bull if bull != 0 else bear
    return s


@dataclass
class _Precomputed:
    dates: np.ndarray  # int64 YYYYMMDD
    states: dict[str, np.ndarray]  # id -> int8 state per bar
    last_idx: dict[str, np.ndarray]  # id -> last directional bar index
    bull_counts: Optional[dict[str, np.ndarray]] = None  # id -> price-bullish count in lookback window
    # Trade-aligned bull-bear diff per bar (O(1) indicator_buy gate; INDICATOR_CACHE_VERSION >= 2).
    diff_long: Optional[np.ndarray] = None  # int16: sum(bullish states) - sum(bearish) for LONG
    diff_short: Optional[np.ndarray] = None  # int16: inverted alignment for SHORT
    bull_long: Optional[np.ndarray] = None  # int16: trade-aligned IND_ENTRY_BULL_N for LONG
    bull_short: Optional[np.ndarray] = None  # int16: trade-aligned IND_ENTRY_BULL_N for SHORT
    neutral_n: Optional[np.ndarray] = None  # int16: IND_ENTRY_NEUTRAL_N (side-independent)


_CACHE_LOCK = threading.Lock()
_MEM_CACHE: dict[tuple[str, str], _Precomputed] = {}
_CACHE_STATS: dict[str, int] = {
    "mem_hit": 0,
    "disk_hit": 0,
    "extend": 0,
    "miss": 0,
    "save": 0,
}


def get_indicator_cache_stats() -> dict[str, int]:
    with _CACHE_LOCK:
        return dict(_CACHE_STATS)


def format_indicator_cache_stats(stats: Optional[dict[str, int]] = None) -> str:
    s = stats if stats is not None else get_indicator_cache_stats()
    parts = []
    if s.get("mem_hit"):
        parts.append(f"mem={s['mem_hit']}")
    if s.get("disk_hit"):
        parts.append(f"disk={s['disk_hit']}")
    if s.get("extend"):
        parts.append(f"extended={s['extend']}")
    if s.get("miss"):
        parts.append(f"built={s['miss']}")
    if s.get("save"):
        parts.append(f"saved={s['save']}")
    if s.get("upgrade"):
        parts.append(f"upgraded={s['upgrade']}")
    return ", ".join(parts) if parts else "no activity"


def reset_indicator_cache_stats() -> None:
    with _CACHE_LOCK:
        for k in _CACHE_STATS:
            _CACHE_STATS[k] = 0


def resolve_indicator_cache_dir(
    cache_dir: Optional[str | Path] = None,
    *,
    repo_root: Optional[str | Path] = None,
    data_dir: Optional[str | Path] = None,
) -> Path:
    if cache_dir:
        p = Path(cache_dir)
        if not p.is_absolute() and repo_root is not None:
            p = Path(repo_root) / p
        p.mkdir(parents=True, exist_ok=True)
        return p
    if data_dir is not None:
        p = Path(data_dir) / ".brt_indicator_cache"
        p.mkdir(parents=True, exist_ok=True)
        return p
    if repo_root is not None:
        p = Path(repo_root) / "cache" / "indicators"
        p.mkdir(parents=True, exist_ok=True)
        return p
    p = Path("cache") / "indicators"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _dates_from_df(df: pd.DataFrame) -> np.ndarray:
    return np.array([int(pd.Timestamp(x).strftime("%Y%m%d")) for x in df.index], dtype=np.int64)


def ohlcv_fingerprint(df: pd.DataFrame) -> str:
    """Stable hash of OHLCV series (detects revisions, not just append)."""
    if df is None or df.empty:
        return ""
    c = df["Close"].to_numpy(dtype=np.float64, copy=False)
    n = len(c)
    d = _dates_from_df(df)
    h = hashlib.blake2b(digest_size=16)
    h.update(str(n).encode())
    h.update(d[: min(5, n)].tobytes())
    h.update(d[-min(5, n) :].tobytes())
    h.update(c[: min(32, n)].tobytes())
    h.update(c[-min(32, n) :].tobytes())
    if "Volume" in df.columns:
        v = df["Volume"].to_numpy(dtype=np.float64, copy=False)
        h.update(v[-min(32, n) :].tobytes())
    if "Open" in df.columns:
        o = df["Open"].to_numpy(dtype=np.float64, copy=False)
        h.update(o[-min(16, n) :].tobytes())
    return h.hexdigest()


def _cache_path(cache_dir: Path, symbol: str) -> Path:
    sym = (symbol or "UNKNOWN").strip().upper()
    return cache_dir / f"{sym}.indcache.pkl"


def _ensure_gate_arrays(pre: _Precomputed) -> _Precomputed:
    """Add diff/bull/neutral count arrays from cached states (v1 caches) without full indicator rebuild."""
    n = len(pre.dates)
    if pre.bull_counts is None:
        pre.bull_counts = _build_bull_count_dict(pre.states, n)
    if pre.diff_long is None or pre.diff_short is None:
        pre.diff_long = _trade_aligned_diff_series(pre.states, n, for_short=False)
        pre.diff_short = _trade_aligned_diff_series(pre.states, n, for_short=True)
    if pre.bull_long is None or pre.bull_short is None:
        pre.bull_long = _trade_aligned_bull_series(pre.states, n, for_short=False)
        pre.bull_short = _trade_aligned_bull_series(pre.states, n, for_short=True)
    if pre.neutral_n is None:
        pre.neutral_n = _neutral_count_series(pre.states, n)
    return pre


def _ensure_diff_arrays(pre: _Precomputed) -> _Precomputed:
    """Backward-compatible alias for ``_ensure_gate_arrays``."""
    return _ensure_gate_arrays(pre)


def _load_disk_cache_payload(cache_dir: Path, symbol: str) -> Optional[dict[str, Any]]:
    path = _cache_path(cache_dir, symbol)
    if not path.is_file():
        return None
    try:
        with open(path, "rb") as f:
            payload = pickle.load(f)
    except (OSError, pickle.UnpicklingError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if int(payload.get("version", 0)) < 1:
        return None
    pre = payload.get("pre")
    if not isinstance(pre, _Precomputed):
        return None
    return payload


def _load_disk_cache(cache_dir: Path, symbol: str, fingerprint: str) -> Optional[_Precomputed]:
    payload = _load_disk_cache_payload(cache_dir, symbol)
    if payload is None:
        return None
    if str(payload.get("fingerprint", "")) != fingerprint:
        return None
    pre = payload.get("pre")
    if not isinstance(pre, _Precomputed):
        return None
    pre = _ensure_diff_arrays(pre)
    if int(payload.get("version", 0)) != INDICATOR_CACHE_VERSION:
        _save_disk_cache(cache_dir, symbol, fingerprint, pre)
        with _CACHE_LOCK:
            _CACHE_STATS["upgrade"] = _CACHE_STATS.get("upgrade", 0) + 1
    return pre


def _save_disk_cache(cache_dir: Path, symbol: str, fingerprint: str, pre: _Precomputed) -> bool:
    """Write indicator cache atomically. Returns False on failure (e.g. concurrent worker on Windows)."""
    path = _cache_path(cache_dir, symbol)
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": INDICATOR_CACHE_VERSION,
        "fingerprint": fingerprint,
        "n_bars": int(len(pre.dates)),
        "last_date": int(pre.dates[-1]) if len(pre.dates) else 0,
        "pre": pre,
    }
    for attempt in range(10):
        tmp = path.with_name(f"{path.stem}.{os.getpid()}.{attempt}.tmp")
        try:
            with open(tmp, "wb") as f:
                pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, path)
            return True
        except OSError:
            try:
                if tmp.is_file():
                    tmp.unlink()
            except OSError:
                pass
            if attempt >= 9:
                return False
            time.sleep(0.05 * (attempt + 1))
    return False


def _extend_precomputed(cached: _Precomputed, df: pd.DataFrame) -> Optional[_Precomputed]:
    """Reuse cached prefix when only new bars were appended (typical daily update)."""
    n_old = len(cached.dates)
    n_new = len(df)
    if n_new < n_old:
        return None
    dates_new = _dates_from_df(df)
    if n_new == n_old:
        if np.array_equal(cached.dates, dates_new):
            return cached
        return None
    if not np.array_equal(cached.dates, dates_new[:n_old]):
        return None
    start = max(0, n_old - _INDICATOR_EXTEND_WARMUP_BARS)
    tail_df = df.iloc[start:].copy()
    tail_pre = _build_precomputed(tail_df)
    if tail_pre is None:
        return None
    tail_n = len(tail_pre.dates)
    off = n_old - start
    if off < 0 or off > tail_n:
        return None
    merged_states: dict[str, np.ndarray] = {}
    merged_last: dict[str, np.ndarray] = {}
    for iid in INDICATOR_IDS:
        if iid not in cached.states or iid not in tail_pre.states:
            return None
        old_st = cached.states[iid]
        tail_st = tail_pre.states[iid]
        new_st = np.zeros(n_new, dtype=np.int8)
        new_st[:n_old] = old_st[:n_old]
        new_st[n_old:] = tail_st[off:]
        merged_states[iid] = new_st
        merged_last[iid] = _last_dir_idx(new_st)
    diff_long = _trade_aligned_diff_series(merged_states, n_new, for_short=False)
    diff_short = _trade_aligned_diff_series(merged_states, n_new, for_short=True)
    bull_long = _trade_aligned_bull_series(merged_states, n_new, for_short=False)
    bull_short = _trade_aligned_bull_series(merged_states, n_new, for_short=True)
    neutral_n = _neutral_count_series(merged_states, n_new)
    bull_counts = _build_bull_count_dict(merged_states, n_new)
    return _Precomputed(
        dates=dates_new,
        states=merged_states,
        last_idx=merged_last,
        bull_counts=bull_counts,
        diff_long=diff_long,
        diff_short=diff_short,
        bull_long=bull_long,
        bull_short=bull_short,
        neutral_n=neutral_n,
    )


def _trade_aligned_diff_series(
    states: dict[str, np.ndarray],
    n: int,
    *,
    for_short: bool,
) -> np.ndarray:
    """Per-bar trade-aligned IND_DIFF (matches ``snapshot_for_entry`` / ``aligned_bull_bear_diff``)."""
    pos = np.zeros(n, dtype=np.int32)
    neg = np.zeros(n, dtype=np.int32)
    for iid in INDICATOR_IDS:
        arr = states.get(iid)
        if arr is None or len(arr) != n:
            continue
        pos += (arr > 0).astype(np.int32)
        neg += (arr < 0).astype(np.int32)
    if for_short:
        return (neg - pos).astype(np.int16)
    return (pos - neg).astype(np.int16)


def _trade_aligned_bull_series(
    states: dict[str, np.ndarray],
    n: int,
    *,
    for_short: bool,
) -> np.ndarray:
    """Per-bar trade-aligned IND_ENTRY_BULL_N (matches ``snapshot_for_entry``)."""
    bull = np.zeros(n, dtype=np.int16)
    for iid in INDICATOR_IDS:
        arr = states.get(iid)
        if arr is None or len(arr) != n:
            continue
        if for_short:
            bull += (arr < 0).astype(np.int16)
        else:
            bull += (arr > 0).astype(np.int16)
    return bull


def _neutral_count_series(states: dict[str, np.ndarray], n: int) -> np.ndarray:
    """Per-bar IND_ENTRY_NEUTRAL_N (side-independent)."""
    neut = np.zeros(n, dtype=np.int16)
    for iid in INDICATOR_IDS:
        arr = states.get(iid)
        if arr is None or len(arr) != n:
            continue
        neut += (arr == 0).astype(np.int16)
    return neut


def _build_precomputed(df: pd.DataFrame) -> Optional[_Precomputed]:
    if df is None or len(df) < 220:
        return None
    if not all(c in df.columns for c in ("Open", "High", "Low", "Close", "Volume")):
        return None
    o = df["Open"].to_numpy(dtype=np.float64)
    h = df["High"].to_numpy(dtype=np.float64)
    l = df["Low"].to_numpy(dtype=np.float64)
    c = df["Close"].to_numpy(dtype=np.float64)
    v = df["Volume"].to_numpy(dtype=np.float64)
    n = len(c)
    dates = np.array([int(pd.Timestamp(x).strftime("%Y%m%d")) for x in df.index], dtype=np.int64)

    sma20 = _sma(c, 20)
    sma50 = _sma(c, 50)
    sma200 = _sma(c, 200)
    ema12 = _ema(c, 12)
    ema26 = _ema(c, 26)
    macd_line, macd_sig, macd_hist = _macd(c)
    rsi = _rsi(c, 14)
    sk, sd = _stoch(h, l, c, 14, 3)
    wr = _williams_r(h, l, c, 14)
    cci = _cci(h, l, c, 20)
    mfi = _mfi(h, l, c, v, 14)
    roc = np.zeros(n)
    roc[10:] = (c[10:] - c[:-10]) / np.maximum(c[:-10], 1e-12) * 100.0
    cmo = _cmo(c, 14)
    adx, pdi, mdi = _adx_dmi(h, l, c, 14)
    bb_mid = _sma(c, 20)
    bb_std = pd.Series(c).rolling(20, min_periods=20).std().to_numpy()
    bb_up = bb_mid + 2.0 * bb_std
    bb_lo = bb_mid - 2.0 * bb_std
    pctb = (c - bb_lo) / np.maximum(bb_up - bb_lo, 1e-12)
    atr = pd.concat(
        [
            pd.Series(h - l),
            (pd.Series(h) - pd.Series(c).shift(1)).abs(),
            (pd.Series(l) - pd.Series(c).shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1).rolling(14, min_periods=14).mean().to_numpy()
    atr_ratio = atr / np.maximum(c, 1e-12)
    atr_med = pd.Series(atr_ratio).rolling(60, min_periods=60).median().to_numpy()
    obv = _obv(c, v)
    obv_slope = pd.Series(obv).diff(10).to_numpy()
    vol_ma = pd.Series(v).rolling(20, min_periods=20).mean().to_numpy()
    vol_surge = v / np.maximum(vol_ma, 1e-12)

    z = np.zeros(n, dtype=np.int8)
    built: dict[str, np.ndarray] = {}

    built["SMA20_OVER_SMA50"] = _state_tri(z, sma20 > sma50, sma20 < sma50)
    built["SMA50_OVER_SMA200"] = _state_tri(z, sma50 > sma200, sma50 < sma200)
    built["PRICE_OVER_SMA20"] = _state_tri(z, c > sma20, c < sma20)
    built["PRICE_OVER_SMA50"] = _state_tri(z, c > sma50, c < sma50)
    built["PRICE_OVER_SMA200"] = _state_tri(z, c > sma200, c < sma200)
    built["EMA12_OVER_EMA26"] = _state_tri(z, ema12 > ema26, ema12 < ema26)
    rsif = np.nan_to_num(rsi, nan=50.0)
    built["RSI14"] = _state_tri(z, rsif > 55, rsif < 45)
    built["MACD_HIST"] = _state_tri(z, macd_hist > 0, macd_hist < 0)
    built["MACD_LINE_OVER_SIGNAL"] = _state_tri(z, macd_line > macd_sig, macd_line < macd_sig)
    built["STOCH_K_OVER_D"] = _state_tri(z, sk > sd, sk < sd)
    wrf = np.nan_to_num(wr, nan=0.0)
    built["WILLR14"] = _state_tri(z, wrf > -50, wrf < -50)
    built["CCI20"] = _state_tri(z, cci > 0, cci < 0)
    built["MFI14"] = _state_tri(z, mfi > 50, mfi < 50)
    built["ROC10"] = _state_tri(z, roc > 0, roc < 0)
    built["CMO14"] = _state_tri(z, cmo > 0, cmo < 0)
    built["ADX_DI"] = _state_tri(z, (pdi > mdi) & (adx > 20), (mdi > pdi) & (adx > 20))
    built["BB_PCTB"] = _state_tri(z, pctb > 0.8, pctb < 0.2)
    built["ATR_RATIO"] = _state_tri(z, atr_ratio > atr_med * 1.15, atr_ratio < atr_med * 0.85)
    built["OBV_SLOPE10"] = _state_tri(z, obv_slope > 0, obv_slope < 0)
    built["VOL_SURGE"] = _state_tri(z, vol_surge > 1.5, vol_surge < 0.6)

    built["DOUBLE_BOTTOM"] = _double_bottom_state(l, h, c, n, 80)
    built["DOUBLE_TOP"] = _double_top_state(h, l, c, n, 80)
    built["HEAD_SHOULDERS_BOTTOM"] = _hs_bottom_state(l, h, c, n)
    built["HEAD_SHOULDERS_TOP"] = _hs_top_state(l, h, c, n)
    built["SYMMETRICAL_TRI"] = _symmetrical_tri_state(h, l, c, n)
    built["WEDGE_FALLING_CONT"] = _wedge_falling_cont(h, l, c, sma50, n)
    built["WEDGE_RISING_CONT"] = _wedge_rising_cont(h, l, c, sma50, n)
    built["FLAG_CONT"] = _flag_cont(c, h, l, n)
    built["MEGAPHONE"] = _megaphone_state(h, l, n)
    built["DIAMOND"] = _diamond_state(h, l, c, n)
    tri_a = _tri_ascending(h, l, c, n)
    tri_d = _tri_descending(h, l, c, n)
    built["TRI_ASCENDING"] = tri_a.astype(np.int8)
    built["TRI_DESCENDING"] = tri_d.astype(np.int8)
    built["UPSIDE_BREAKOUT"] = _upside_breakout(c, h, n)
    db = np.zeros(n, dtype=np.int8)
    for i in range(n):
        if built["DIAMOND"][i] == 1 and c[i] < np.median(c[max(0, i - 40) : i + 1]):
            db[i] = 1
    built["DIAMOND_BOTTOM"] = np.maximum(db, built["DOUBLE_BOTTOM"]).astype(np.int8)
    dt = np.zeros(n, dtype=np.int8)
    for i in range(n):
        if built["DIAMOND"][i] == -1 and c[i] > np.median(c[max(0, i - 40) : i + 1]):
            dt[i] = -1
        if built["DOUBLE_TOP"][i] == -1:
            dt[i] = -1
    built["DIAMOND_TOP"] = dt.astype(np.int8)
    built["BOTTOM_TRI"] = np.where(tri_a > 0, np.int8(1), np.int8(0)).astype(np.int8)
    built["TOP_TRI"] = tri_d.astype(np.int8)
    built["PENNANT_CONT"] = _flag_cont(c, h, l, n)  # reuse small coil
    built["CANDLE_HAMMER"] = _candle_state_series(o, h, l, c, "HAMMER", 1, 0)
    built["CANDLE_SHOOTING_STAR"] = _candle_state_series(o, h, l, c, "SHOOTING_STAR", 0, -1)
    built["CANDLE_BULL_ENGULF"] = _candle_state_series(o, h, l, c, "BULL_ENGULF", 1, 0)
    built["CANDLE_BEAR_ENGULF"] = _candle_state_series(o, h, l, c, "BEAR_ENGULF", 0, -1)
    built["CANDLE_MORNING_STAR"] = _candle_state_series(o, h, l, c, "MORNING_STAR", 1, 0)
    built["CANDLE_EVENING_STAR"] = _candle_state_series(o, h, l, c, "EVENING_STAR", 0, -1)
    built["CANDLE_THREE_SOLDIERS"] = _candle_state_series(o, h, l, c, "THREE_SOLDIERS", 1, 0)
    built["CANDLE_THREE_CROWS"] = _candle_state_series(o, h, l, c, "THREE_CROWS", 0, -1)
    built["CANDLE_DOJI"] = _candle_state_series(o, h, l, c, "DOJI", 0, 0)

    last_idx: dict[str, np.ndarray] = {}
    for iid, arr in built.items():
        last_idx[iid] = _last_dir_idx(arr)

    diff_long = _trade_aligned_diff_series(built, n, for_short=False)
    diff_short = _trade_aligned_diff_series(built, n, for_short=True)
    bull_long = _trade_aligned_bull_series(built, n, for_short=False)
    bull_short = _trade_aligned_bull_series(built, n, for_short=True)
    neutral_n = _neutral_count_series(built, n)
    bull_counts = _build_bull_count_dict(built, n)
    return _Precomputed(
        dates=dates,
        states=built,
        last_idx=last_idx,
        bull_counts=bull_counts,
        diff_long=diff_long,
        diff_short=diff_short,
        bull_long=bull_long,
        bull_short=bull_short,
        neutral_n=neutral_n,
    )


def _state_label(v: int) -> str:
    if v > 0:
        return "BULL"
    if v < 0:
        return "BEAR"
    return "NEUTRAL"


def format_indicator_csv_row(entry_indicators: dict[str, str]) -> list[str]:
    """Flat cell list matching entry_indicator_csv_headers()."""
    if not entry_indicators:
        row: list[str] = []
        for _iid in INDICATOR_IDS:
            row.extend(["NEUTRAL", "", "0"])
        row.extend(["0", "0", "0", str(len(INDICATOR_IDS)), ""])
        return row
    apply_ind_score_to_entry_indicators(entry_indicators)
    row = []
    for iid in INDICATOR_IDS:
        row.append(entry_indicators.get(f"IND_{iid}", "NEUTRAL"))
        row.append(entry_indicators.get(f"IND_{iid}_LAST", ""))
        row.append(entry_indicators.get(f"IND_{iid}_COUNT", "0"))
    row.append(entry_indicators.get("IND_ENTRY_BULL_N", "0"))
    row.append(entry_indicators.get("IND_ENTRY_BEAR_N", "0"))
    row.append(entry_indicators.get("IND_DIFF", "0"))
    row.append(entry_indicators.get("IND_ENTRY_NEUTRAL_N", str(len(INDICATOR_IDS))))
    row.append(entry_indicators.get("IND_SCORE", ""))
    return row


def snapshot_for_entry(pre: _Precomputed, entry_i: int, side: str) -> dict[str, str]:
    out: dict[str, str] = {}
    if entry_i < 0 or entry_i >= len(pre.dates):
        return out
    pre = _ensure_gate_arrays(pre)
    is_short = str(side or "LONG").upper() == "SHORT"
    bull_n = bear_n = neut_n = 0
    for iid in INDICATOR_IDS:
        st = int(pre.states[iid][entry_i]) if iid in pre.states else 0
        out[f"IND_{iid}"] = _state_label(st)
        lj = int(pre.last_idx.get(iid, np.full(len(pre.dates), -1))[entry_i])
        if lj >= 0:
            out[f"IND_{iid}_LAST"] = str(int(pre.dates[lj]))
        else:
            out[f"IND_{iid}_LAST"] = ""
        cnt_arr = (pre.bull_counts or {}).get(iid)
        if cnt_arr is not None and entry_i < len(cnt_arr):
            out[f"IND_{iid}_COUNT"] = str(int(cnt_arr[entry_i]))
        else:
            out[f"IND_{iid}_COUNT"] = "1" if st > 0 else "0"
        if st == 0:
            neut_n += 1
        elif st > 0:
            if is_short:
                bear_n += 1
            else:
                bull_n += 1
        else:
            if is_short:
                bull_n += 1
            else:
                bear_n += 1
    out["IND_ENTRY_BULL_N"] = str(bull_n)
    out["IND_ENTRY_BEAR_N"] = str(bear_n)
    out["IND_DIFF"] = str(bull_n - bear_n)
    out["IND_ENTRY_NEUTRAL_N"] = str(neut_n)
    apply_ind_score_to_entry_indicators(out)
    return out


def _trade_date_to_ymd(date_s: str) -> Optional[int]:
    """Parse BRTTrade DATE_OPENED (YYYY-MM-DD or YYYYMMDD) to int YYYYMMDD."""
    if not date_s or not str(date_s).strip():
        return None
    s = str(date_s).strip()
    if len(s) >= 10 and s[4] == "-":
        ymd = s[:10].replace("-", "")
    else:
        ymd = "".join(ch for ch in s if ch.isdigit())[:8]
    if len(ymd) != 8:
        return None
    return int(ymd)


@dataclass
class SpyIndDiffByDate:
    """SPY IND_DIFF (bull-bear count) keyed by calendar day for O(1) entry lookups."""

    long_by_date: dict[int, int]
    short_by_date: dict[int, int]

    def at_entry(self, date_s: str, side: str = "LONG") -> Optional[int]:
        ymd = _trade_date_to_ymd(date_s)
        if ymd is None:
            return None
        m = self.short_by_date if str(side or "LONG").upper() == "SHORT" else self.long_by_date
        return m.get(ymd)


def build_spy_ind_diff_by_date(
    df: pd.DataFrame,
    *,
    cache_dir: Optional[str | Path] = None,
    use_cache: bool = True,
) -> Optional[SpyIndDiffByDate]:
    """Precompute SPY IND_DIFF per bar; return date-keyed maps for trade entry enrichment."""
    pre = build_entry_indicator_precompute(
        df, symbol="SPY", cache_dir=cache_dir, use_cache=use_cache,
    )
    if pre is None:
        return None
    pre = _ensure_gate_arrays(pre)
    if pre.diff_long is None or pre.diff_short is None:
        return None
    long_map: dict[int, int] = {}
    short_map: dict[int, int] = {}
    for i, d in enumerate(pre.dates):
        ymd = int(d)
        long_map[ymd] = int(pre.diff_long[i])
        short_map[ymd] = int(pre.diff_short[i])
    return SpyIndDiffByDate(long_by_date=long_map, short_by_date=short_map)


def aligned_bull_bear_diff(pre: Optional[_Precomputed], entry_i: int, side: str) -> Optional[int]:
    """Trade-aligned bull count minus bear count at ``entry_i`` (same as IND_ENTRY_* snapshot). None if invalid."""
    if pre is None or entry_i < 0 or entry_i >= len(pre.dates):
        return None
    pre = _ensure_gate_arrays(pre)
    is_short = str(side or "LONG").upper() == "SHORT"
    arr = pre.diff_short if is_short else pre.diff_long
    if arr is not None and entry_i < len(arr):
        return int(arr[entry_i])
    snap = snapshot_for_entry(pre, entry_i, side)
    if not snap:
        return None
    try:
        if "IND_DIFF" in snap:
            return int(snap["IND_DIFF"])
        return int(snap["IND_ENTRY_BULL_N"]) - int(snap["IND_ENTRY_BEAR_N"])
    except (KeyError, ValueError):
        return None


def entry_bull_n(pre: Optional[_Precomputed], entry_i: int, side: str) -> Optional[int]:
    """Trade-aligned IND_ENTRY_BULL_N at ``entry_i`` (None if invalid or precompute unavailable)."""
    if pre is None or entry_i < 0 or entry_i >= len(pre.dates):
        return None
    pre = _ensure_gate_arrays(pre)
    is_short = str(side or "LONG").upper() == "SHORT"
    arr = pre.bull_short if is_short else pre.bull_long
    if arr is not None and entry_i < len(arr):
        return int(arr[entry_i])
    snap = snapshot_for_entry(pre, entry_i, side)
    if not snap:
        return None
    try:
        return int(snap["IND_ENTRY_BULL_N"])
    except (KeyError, ValueError):
        return None


def entry_neutral_n(pre: Optional[_Precomputed], entry_i: int, side: str = "LONG") -> Optional[int]:
    """IND_ENTRY_NEUTRAL_N at ``entry_i`` (side-independent; None if invalid)."""
    del side  # neutral count does not depend on trade side
    if pre is None or entry_i < 0 or entry_i >= len(pre.dates):
        return None
    pre = _ensure_gate_arrays(pre)
    arr = pre.neutral_n
    if arr is not None and entry_i < len(arr):
        return int(arr[entry_i])
    snap = snapshot_for_entry(pre, entry_i, "LONG")
    if not snap:
        return None
    try:
        return int(snap["IND_ENTRY_NEUTRAL_N"])
    except (KeyError, ValueError):
        return None


def build_entry_indicator_precompute(
    df: pd.DataFrame,
    *,
    symbol: Optional[str] = None,
    cache_dir: Optional[str | Path] = None,
    use_cache: bool = True,
) -> Optional[_Precomputed]:
    """Build indicator state grids for gating or CSV enrichment (None if history too short or missing Volume).

    When ``use_cache`` and ``symbol`` are set, loads/saves per-symbol disk cache under ``cache_dir``.
    If only new bars were appended since the last cache, recomputes the tail window only.
    """
    if df is None or len(df) < 220:
        return None
    if not all(c in df.columns for c in ("Open", "High", "Low", "Close", "Volume")):
        return None

    sym_key = (symbol or "").strip().upper()
    fp = ohlcv_fingerprint(df)
    mem_key = (sym_key, fp) if sym_key else ("", fp)

    if use_cache and sym_key:
        with _CACHE_LOCK:
            hit = _MEM_CACHE.get(mem_key)
        if hit is not None:
            with _CACHE_LOCK:
                _CACHE_STATS["mem_hit"] += 1
            return hit

        if cache_dir is not None:
            cdir = Path(cache_dir)
            disk_pre = _load_disk_cache(cdir, sym_key, fp)
            if disk_pre is not None and len(disk_pre.dates) == len(df):
                with _CACHE_LOCK:
                    _MEM_CACHE[mem_key] = disk_pre
                    _CACHE_STATS["disk_hit"] += 1
                return disk_pre
            payload = _load_disk_cache_payload(cdir, sym_key)
            if payload is not None:
                partial = payload.get("pre")
                if isinstance(partial, _Precomputed) and len(partial.dates) < len(df):
                    extended = _extend_precomputed(partial, df)
                    if extended is not None:
                        if _save_disk_cache(cdir, sym_key, fp, extended):
                            with _CACHE_LOCK:
                                _CACHE_STATS["extend"] += 1
                        with _CACHE_LOCK:
                            _MEM_CACHE[mem_key] = extended
                        return extended

    with _CACHE_LOCK:
        _CACHE_STATS["miss"] += 1
    pre = _build_precomputed(df)
    if pre is None:
        return None

    if use_cache and sym_key and cache_dir is not None:
        if _save_disk_cache(Path(cache_dir), sym_key, fp, pre):
            with _CACHE_LOCK:
                _CACHE_STATS["save"] += 1
        with _CACHE_LOCK:
            _MEM_CACHE[mem_key] = pre
    return pre


def _enrich_symbol_entry_indicators(
    sym: str,
    tlist: list[Any],
    df: Optional[pd.DataFrame],
    *,
    cache_dir: Optional[str | Path] = None,
    use_cache: bool = True,
) -> str:
    """Apply indicator snapshot to all trades for one symbol (one precompute per symbol)."""
    if df is None or df.empty:
        for t in tlist:
            t.entry_indicators = {}
        return sym
    needs = [t for t in tlist if not trade_has_entry_indicators(t)]
    if not needs:
        return sym
    pre = build_entry_indicator_precompute(
        df, symbol=sym, cache_dir=cache_dir, use_cache=use_cache
    )
    for t in needs:
        if pre is None:
            t.entry_indicators = {}
            continue
        ei = int(getattr(t, "entry_bar_index", -1) or -1)
        if ei < 0 or ei >= len(pre.dates):
            t.entry_indicators = {}
            continue
        t.entry_indicators = snapshot_for_entry(pre, ei, getattr(t, "side", "LONG") or "LONG")
    return sym


def trade_has_entry_indicators(t: Any) -> bool:
    ei = getattr(t, "entry_indicators", None) or {}
    return isinstance(ei, dict) and "IND_DIFF" in ei and "IND_ENTRY_BULL_N" in ei


def trades_need_indicator_enrichment(trades: list[Any]) -> bool:
    return any(not trade_has_entry_indicators(t) for t in trades)


def enrich_trades_entry_indicators(
    trades: list[Any],
    tickers: dict[str, pd.DataFrame],
    use_indicators: bool,
    progress_callback: Optional[Any] = None,
    workers: int = 0,
    *,
    cache_dir: Optional[str | Path] = None,
    use_cache: bool = True,
) -> None:
    for t in trades:
        if not hasattr(t, "entry_indicators"):
            t.entry_indicators = {}
    if not use_indicators or not trades:
        for t in trades:
            t.entry_indicators = {}
        return
    if not trades_need_indicator_enrichment(trades):
        return
    by_sym: dict[str, list[Any]] = {}
    for t in trades:
        by_sym.setdefault(t.symbol, []).append(t)
    n_sym = len(by_sym)
    n_workers = max(0, int(workers or 0))
    if n_workers > 1 and n_sym > 1:
        n_workers = min(n_workers, n_sym, 16)
        done = 0
        with ThreadPoolExecutor(max_workers=n_workers) as ex:
            futs = {
                ex.submit(
                    _enrich_symbol_entry_indicators,
                    sym,
                    tlist,
                    tickers.get(sym),
                    cache_dir=cache_dir,
                    use_cache=use_cache,
                ): sym
                for sym, tlist in by_sym.items()
            }
            for fut in as_completed(futs):
                sym = fut.result()
                done += 1
                if progress_callback is not None:
                    progress_callback(done, n_sym, sym)
        return
    for sym_i, (sym, tlist) in enumerate(by_sym.items(), start=1):
        _enrich_symbol_entry_indicators(
            sym, tlist, tickers.get(sym), cache_dir=cache_dir, use_cache=use_cache
        )
        if progress_callback is not None and n_sym > 0:
            progress_callback(sym_i, n_sym, sym)
