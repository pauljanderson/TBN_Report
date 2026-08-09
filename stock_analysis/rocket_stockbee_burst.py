#!/usr/bin/env python3
"""
StockBee Momentum Burst — TBN mode ``sb_mode`` (prefix SB_).

Host: ``rocket_tbn.py`` via ``run_sb_from_brt_main`` (``run_sb.bat`` → ``-v sb_mode=true``).
Standalone CLI still works for research; writers match the host path.

Theory: drive/paul_experiments/tbn_new_systems/stockbee_momentum_burst/10_theory.md
Plan:   .../40_engine_plan.md

Entry (signal bar T, all must pass):
  - Close_T / Close_{T-1} >= burst_min_pct (+4% default)
  - Volume_T > Volume_{T-1} (optional)
  - Range_T > each of prior burst_range_lookback daily ranges
  - DCR = (C-L)/(H-L) >= burst_dcr_min
  - Start-of-swing: count of consecutive large-up days immediately before T
    <= burst_max_prior_up_days (default 1 → reject if >=2 already into T)
  - Price_T >= burst_min_price
  - Optional ADV$ floor (off when burst_min_adv_usd <= 0)

Fill: next open (T+1). Reject if open <= signal_low (LOD), or if
      risk=(open-LOD)/open > burst_max_risk_pct (bat default 0.08).
      Watchlist buy band: MUST_OPEN_ABOVE=LOD (strict), MUST_OPEN_AT_OR_BELOW=LOD/(1-r).
      Rejected fills → ``SB_RejectedFills_<ts>.csv`` (+ HTML twin) with
      REJECT_REASON TOO_LOW | TOO_HIGH; Audit counters ``sb_rejected_*``.

Exits (priority): LOD stop (gap → GAP_DOWN @open; else STOP_LOSS @stop)
  → +target_pct → NO_FT → TIME stop.
  Burst DNA is preserved — not remapped to BRT zones.

Sizing (default = host parity with YH/BRT/RS):
  Fixed notional, then post-run dollar-scale via tbn_host_sizing:
    deployable = initial_capital × aggressive_max_multiple × margin_utilization
    per_trade  = deployable / max_positions
  Defaults: 500_000 × 2 × 0.6 / max_positions (= 600_000 / max_positions).
  Optional --burst-size-from-stop: risk $R = cash * burst_risk_frac; shares = R / (entry-stop)
  (Seed-opt $100R research path; skips host dollar-scale).

Outputs: Closed/Open via BRT writers (+ burst DNA columns spliced);
  Closed/Open burst DNA: SIGNAL_DATE, PCT_DAY, DCR, RANGE_EXP, VOL_RATIO
  (Volume_T / Volume_{T−1}), VOL_VS_50 (Volume_T / mean prior 50d volume),
  SIGNAL_LOW (signal-bar LOD), RISK_PCT. Correlation includes the numeric
  predictors among these (SIGNAL_DATE excluded as a date stamp).
  RejectedFills CSV/HTML for pending signals not taken at next open;
  Audit/Report via unified ``write_brt_audit_report`` / ``write_brt_report`` schema;
  Summary/Watchlist keep burst EXIT_* / MUST_OPEN_* DNA; EquityCurve via host aggressive path.

--aggressive: same BRT_DrawdownCalc overlay as rocket_tbn (EquityCurve_Aggressive_*).
Optional Market Monitor breadth gate (burst_mm_gate, default false) via rocket_stockbee_mm.
Optional 2Lynch T−1 narrow/down (burst_require_t1_narrow_or_down, default false).
Optional vol-vs-50d-avg gate (burst_vol_vs_avg_mult, default 0 = off).
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from dataclasses import dataclass, field, fields, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

try:
    from tbn_host_sizing import (
        DEFAULT_AGGRESSIVE_MAX_MULTIPLE,
        DEFAULT_INITIAL_CAPITAL,
        DEFAULT_MARGIN_UTILIZATION,
        HostSizingConfig,
        apply_host_dollar_scale,
        audit_display_brt_cash,
        compute_and_write_host_equity,
        resolve_max_positions,
    )
except ImportError:
    from stock_analysis.tbn_host_sizing import (  # type: ignore
        DEFAULT_AGGRESSIVE_MAX_MULTIPLE,
        DEFAULT_INITIAL_CAPITAL,
        DEFAULT_MARGIN_UTILIZATION,
        HostSizingConfig,
        apply_host_dollar_scale,
        audit_display_brt_cash,
        compute_and_write_host_equity,
        resolve_max_positions,
    )

try:
    from ohlcv_store import list_csv_symbols as _list_csv_symbols
except ImportError:
    try:
        from stock_analysis.ohlcv_store import list_csv_symbols as _list_csv_symbols  # type: ignore
    except ImportError:
        _list_csv_symbols = None  # type: ignore

FILE_PREFIX = "SB"
# Burst DNA columns spliced onto BRT Closed/Open (not zone remaps).
# SIGNAL_LOW = signal-bar low of day (LOD); also used as stop for filled trades.
_BURST_DNA_CLOSED_COLS = (
    "SIGNAL_DATE",
    "PCT_DAY",
    "DCR",
    "RANGE_EXP",
    "VOL_RATIO",
    "VOL_VS_50",
    "SIGNAL_LOW",
    "RISK_PCT",
    "MM_RATIO",
    "T1_NARROW",
    "T1_DOWN",
    "T1_RANGE",
)
_BURST_DNA_OPEN_COLS = _BURST_DNA_CLOSED_COLS
# Research / seed-stage reference list (not production default).
# Production / DailyRun default universe is GOLD_UNIVERSE.csv via run_sb.bat
# (drive/paul_experiments/tbn_new_systems/stockbee_momentum_burst/).
# Empty -s still means all data/newdata/data/*.csv (excl. SPY); bats pass gold when unset.
DEFAULT_SEED_SYMBOLS = (
    "NVDA,TSLA,AMD,SMCI,CELH,PLTR,APP,ARM,CRWD,NET,"
    "AXON,SNOW,HOOD,MSTR,COIN,ROKU,DKNG,TXRH"
)
DAYS_PER_YEAR = 365.25
# Engine placeholder notional before host dollar-scale (matches BRTConfig.brt_cash default).
DEFAULT_CASH = 47_500.0
DEFAULT_RISK_FRAC = 0.01  # 1% of cash risked per trade when size-from-stop ON


def _as_bool(x: Any) -> bool:
    if isinstance(x, bool):
        return x
    return str(x).strip().lower() in ("1", "true", "yes", "on")


def _pnl_dollars(cfg: "BurstConfig", entry_px: float, stop_px: float, exit_px: float) -> float:
    """Dollar PnL: size-from-stop (risk-normalized) or fixed notional."""
    if entry_px <= 0:
        return 0.0
    if cfg.burst_size_from_stop:
        stop_dist = entry_px - stop_px
        if stop_dist <= 1e-12:
            return 0.0
        risk_dollars = cfg.cash * cfg.burst_risk_frac
        shares = risk_dollars / stop_dist
        return shares * (exit_px - entry_px)
    return cfg.cash * ((exit_px / entry_px) - 1.0)


@dataclass
class BurstConfig:
    burst_min_pct: float = 0.04
    burst_vol_gt_prior: bool = True
    burst_range_lookback: int = 5
    burst_dcr_min: float = 0.70
    burst_max_prior_up_days: int = 1
    burst_fill: str = "next_open"  # only next_open in v1
    burst_max_risk_pct: float = 0.03
    target_pct: float = 1.10  # multiplier (+10%)
    burst_time_stop_days: int = 5
    burst_no_ft_days: int = 3  # 0 disables
    burst_mm_gate: bool = False
    burst_mm_min_ratio: float = 2.0
    # Market Monitor membership / liquidity (used when building MM series).
    mm_min_shares: float = 1000.0
    mm_min_adv_usd: float = 250_000.0  # 0 = disable $ filter
    mm_min_price: float = 5.0
    mm_move_pct: float = 0.04
    mm_lookback: int = 10
    mm_force_rebuild: bool = False
    # 2Lynch T−1 narrow/down (“N”); default OFF.
    burst_require_t1_narrow_or_down: bool = False
    burst_t1_narrow_mode: str = "median"  # median | mean | max
    burst_min_price: float = 5.0
    burst_min_adv_usd: float = 0.0  # 0 = off
    burst_adv_lookback: int = 20
    # Optional trigger-bar gates (0 = off). ATR% = ATR14/close*100; DIST = % below 52w high.
    burst_min_atr_pct_at_trigger: float = 0.0
    burst_max_atr_pct_at_trigger: float = 0.0
    burst_min_dist_to_52w_high_pct: float = 0.0
    burst_max_dist_to_52w_high_pct: float = 0.0
    # Vol ≥ k× prior-N avg (exclude signal bar). 0 = off. DNA: VOL_VS_50.
    burst_vol_vs_avg_mult: float = 0.0
    burst_vol_avg_lookback: int = 50
    cash: float = DEFAULT_CASH
    # Default OFF → host fixed-notional + dollar-scale (YH/BRT/RS parity).
    burst_size_from_stop: bool = False
    burst_risk_frac: float = DEFAULT_RISK_FRAC
    entry_start_date: str = ""  # YYYY-MM-DD or YYYYMMDD; empty = all
    entry_end_date: str = ""
    # Host sizing / aggressive (shared with rocket_tbn via tbn_host_sizing)
    initial_capital: float = DEFAULT_INITIAL_CAPITAL
    aggressive_max_multiple: float = DEFAULT_AGGRESSIVE_MAX_MULTIPLE
    margin_utilization: float = DEFAULT_MARGIN_UTILIZATION
    max_positions: int = 0  # 0 = auto peak concurrent
    aggressive: bool = False
    aggressive_margin_interest: float = 0.10
    aggressive_avg_positions: float = 0.0
    aggressive_sizing_equity_cap: float = 10.0
    host_dollar_scale: bool = True  # ignored when burst_size_from_stop


@dataclass
class BurstClosedRow:
    symbol: str
    side: str
    date_opened: str
    entry_price: float
    stop_price: float
    target_price: float
    date_closed: str
    exit_price: float
    exit_type: str
    days_held: int
    pnl_pct: float
    pnl_dollars: float
    ann_ror_pct: float
    max_price: float
    signal_date: str
    pct_day: float
    dcr: float
    range_exp: float
    vol_ratio: float
    signal_low: float
    risk_pct: float
    mm_ratio: float = float("nan")
    t1_narrow: int = 0
    t1_down: int = 0
    t1_range: float = float("nan")
    vol_vs_50: float = float("nan")
    one_liner: str = ""


@dataclass
class BurstOpenRow:
    symbol: str
    side: str
    date_opened: str
    entry_price: float
    stop_price: float
    target_price: float
    current_price: float
    days_held: int
    pnl_pct: float
    pnl_dollars: float
    max_price: float
    signal_date: str
    pct_day: float
    dcr: float
    range_exp: float
    vol_ratio: float
    signal_low: float
    risk_pct: float
    mm_ratio: float = float("nan")
    t1_narrow: int = 0
    t1_down: int = 0
    t1_range: float = float("nan")
    vol_vs_50: float = float("nan")


@dataclass
class BurstWatchRow:
    symbol: str
    asof_date: str
    signal_date: str
    pct_day: float
    dcr: float
    range_exp: float
    vol_ratio: float
    signal_low: float
    must_open_above: float
    must_open_at_or_below: float
    max_risk_pct: float
    notes: str
    mm_ratio: float = float("nan")
    t1_narrow: int = 0
    t1_down: int = 0
    t1_range: float = float("nan")
    vol_vs_50: float = float("nan")


@dataclass
class BurstRejectedFillRow:
    """Pending signal rejected at next-open fill (open outside buy band)."""

    symbol: str
    signal_date: str
    fill_date: str
    signal_low: float
    fill_open: float
    must_open_above: float
    must_open_at_or_below: float
    max_risk_pct: float
    reject_reason: str  # TOO_LOW | TOO_HIGH | OTHER
    risk_pct: float


def buy_open_band(signal_low: float, max_risk_pct: float) -> tuple[float, float]:
    """Fill-day open window: open > signal_low and risk=(O-L)/O <= max_risk_pct.

    Returns (must_open_above, must_open_at_or_below) where
    must_open_above = L (strictly greater) and must_open_at_or_below = L/(1-r).
    """
    lod = float(signal_low)
    r = float(max_risk_pct)
    if lod <= 0 or r >= 1.0 or r < 0:
        return lod, float("nan")
    return lod, lod / (1.0 - r)


@dataclass
class BurstSymbolResult:
    closed: list[BurstClosedRow] = field(default_factory=list)
    open_row: Optional[BurstOpenRow] = None
    watch_row: Optional[BurstWatchRow] = None
    rejected_fills: list[BurstRejectedFillRow] = field(default_factory=list)
    bars: int = 0
    signals: int = 0
    rejected_risk: int = 0
    rejected_too_low: int = 0
    rejected_too_high: int = 0
    rejected_atr: int = 0
    rejected_dist52: int = 0
    rejected_mm: int = 0
    rejected_t1_n: int = 0
    rejected_vol_vs_avg: int = 0
    skipped_reason: str = ""


def _iso(d: Any) -> str:
    if hasattr(d, "strftime"):
        return d.strftime("%Y%m%d")
    s = str(d)[:10].replace("-", "")
    return s


def _parse_ymd(s: str) -> str:
    s = (s or "").strip().replace("-", "")
    return s


_WEEK52_LOOKBACK = 252  # trading days (~52 weeks); match rocket_tbn


def _atr14_arr(h: np.ndarray, l: np.ndarray, c: np.ndarray, period: int = 14) -> np.ndarray:
    """Simple rolling mean of true range (matches rocket_tbn._compute_atr_14_arr)."""
    n = len(h)
    tr = np.empty(n, dtype=np.float64)
    tr[0] = h[0] - l[0]
    if n > 1:
        hl = h[1:] - l[1:]
        h_pc = np.abs(h[1:] - c[:-1])
        l_pc = np.abs(l[1:] - c[:-1])
        tr[1:] = np.maximum.reduce([hl, h_pc, l_pc])
    atr = np.full(n, np.nan, dtype=np.float64)
    if n >= period:
        atr[period - 1 :] = np.convolve(tr, np.ones(period, dtype=np.float64) / float(period), mode="valid")
    return atr


def _atr_pct_at_bar(atr: np.ndarray, c: np.ndarray, i: int) -> Optional[float]:
    if i < 0 or i >= len(atr) or i >= len(c):
        return None
    a14 = float(atr[i])
    px = float(c[i])
    if not (np.isfinite(a14) and np.isfinite(px) and px > 0):
        return None
    return (a14 / px) * 100.0


def _dist_to_52w_high_pct(h: np.ndarray, price: float, i: int) -> Optional[float]:
    """% below 52w high through bar i: 0 at the high, larger when further below."""
    if i < 0 or i >= len(h) or price <= 0 or not np.isfinite(price):
        return None
    start = max(0, i - _WEEK52_LOOKBACK + 1)
    seg = h[start : i + 1]
    if seg.size == 0:
        return None
    hi_52 = float(np.nanmax(seg))
    if not np.isfinite(hi_52) or hi_52 <= 0:
        return None
    return max(0.0, (hi_52 - price) / hi_52 * 100.0)


def _atr_gate_blocks(cfg: BurstConfig, atr_pct: Optional[float]) -> bool:
    """True when ATR% fails min/max (0 = off). Missing ATR fails an active gate."""
    mn = float(cfg.burst_min_atr_pct_at_trigger or 0.0)
    mx = float(cfg.burst_max_atr_pct_at_trigger or 0.0)
    if mn <= 0.0 and mx <= 0.0:
        return False
    if atr_pct is None or not np.isfinite(float(atr_pct)):
        return True
    v = float(atr_pct)
    if mn > 0.0 and v < mn:
        return True
    if mx > 0.0 and v > mx:
        return True
    return False


def _dist52_gate_blocks(cfg: BurstConfig, dist: Optional[float]) -> bool:
    """True when DIST-to-52w-high fails min/max (0 = off). Missing DIST fails an active gate."""
    mn = float(cfg.burst_min_dist_to_52w_high_pct or 0.0)
    mx = float(cfg.burst_max_dist_to_52w_high_pct or 0.0)
    if mn <= 0.0 and mx <= 0.0:
        return False
    if dist is None or not np.isfinite(float(dist)):
        return True
    v = float(dist)
    if mn > 0.0 and v < mn:
        return True
    if mx > 0.0 and v > mx:
        return True
    return False


def _vol_vs_avg_at(v: np.ndarray, i: int, lookback: int) -> Optional[float]:
    """Volume_T / mean(Volume of prior ``lookback`` sessions). Exclude bar i. None if undefined."""
    lb = int(lookback)
    if lb <= 0 or i < lb or i >= len(v):
        return None
    seg = v[i - lb : i]
    if seg.size < lb:
        return None
    ma = float(np.mean(seg))
    if not np.isfinite(ma) or ma <= 0.0:
        return None
    cur = float(v[i])
    if not np.isfinite(cur):
        return None
    return cur / ma


def _vol_vs_avg_gate_blocks(cfg: BurstConfig, vol_vs_50: Optional[float]) -> bool:
    """True when burst_vol_vs_avg_mult > 0 and ratio fails. Missing MA fails closed."""
    mult = float(cfg.burst_vol_vs_avg_mult or 0.0)
    if mult <= 0.0:
        return False
    if vol_vs_50 is None or not np.isfinite(float(vol_vs_50)):
        return True
    return float(vol_vs_50) < mult


def _t1_narrow_or_down(
    i: int,
    h: np.ndarray,
    l: np.ndarray,
    c: np.ndarray,
    cfg: BurstConfig,
) -> tuple[bool, dict[str, float]]:
    """2Lynch T−1 N: narrow OR down on completed bar i-1. Returns (pass, diag)."""
    lookback = int(cfg.burst_range_lookback)
    empty = {"t1_narrow": 0.0, "t1_down": 0.0, "t1_range": float("nan")}
    if i < lookback + 2:
        return False, empty
    rng_t1 = float(h[i - 1] - l[i - 1])
    prior = [float(h[i - 1 - k] - l[i - 1 - k]) for k in range(1, lookback + 1)]
    if not prior or not np.isfinite(rng_t1):
        return False, empty
    mode = str(cfg.burst_t1_narrow_mode or "median").strip().lower()
    if mode == "mean":
        narrow = rng_t1 < float(np.mean(prior))
    elif mode == "max":
        narrow = rng_t1 < float(np.max(prior))
    else:
        narrow = rng_t1 <= float(np.median(prior))
    down = float(c[i - 1]) < float(c[i - 2])
    diag = {
        "t1_narrow": 1.0 if narrow else 0.0,
        "t1_down": 1.0 if down else 0.0,
        "t1_range": rng_t1,
    }
    return bool(narrow or down), diag


def _mm_gate_blocks(
    cfg: BurstConfig,
    signal_i: int,
    dates: list[str],
    mm_ratio_by_ymd: Optional[dict[str, float]],
) -> tuple[bool, float]:
    """True when MM gate ON and mm_ratio[T−1] < min (or missing). Returns (blocks, ratio)."""
    if not cfg.burst_mm_gate:
        ratio = float("nan")
        if mm_ratio_by_ymd and signal_i >= 1:
            ratio = float(mm_ratio_by_ymd.get(dates[signal_i - 1], float("nan")))
        return False, ratio
    if signal_i < 1 or not mm_ratio_by_ymd:
        return True, float("nan")
    ratio = mm_ratio_by_ymd.get(dates[signal_i - 1])
    if ratio is None or not np.isfinite(float(ratio)):
        return True, float("nan")
    r = float(ratio)
    if r < float(cfg.burst_mm_min_ratio or 0.0):
        return True, r
    return False, r


def _ann_ror(pnl_pct: float, days_held: int) -> float:
    """Annualized ROR % from trade pnl_pct (already in percent points) and calendar-ish days."""
    if days_held <= 0:
        return 0.0
    r = 1.0 + pnl_pct / 100.0
    if r <= 0:
        return -100.0
    return (r ** (DAYS_PER_YEAR / days_held) - 1.0) * 100.0


def _meta_mm_t1(meta: dict[str, float]) -> tuple[float, int, int, float]:
    """Unpack MM / 2Lynch T−1 DNA from signal meta."""
    mm = float(meta.get("mm_ratio", float("nan")))
    t1n = int(meta.get("t1_narrow", 0) or 0)
    t1d = int(meta.get("t1_down", 0) or 0)
    t1r = float(meta.get("t1_range", float("nan")))
    return mm, t1n, t1d, t1r


def load_ohlcv_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)
    if "Date" not in df.columns:
        raise ValueError(f"No Date column in {path}")
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date", ignore_index=True)
    for c in ("Open", "High", "Low", "Close", "Volume"):
        if c not in df.columns:
            lower = {str(x).lower(): x for x in df.columns}
            src = lower.get(c.lower())
            if src is None and c == "Volume":
                df["Volume"] = 0.0
            elif src is not None:
                df[c] = df[src]
            else:
                raise ValueError(f"Missing {c} in {path}")
    # Keep precomputed SMA20/50/100 when present (SMA*_AT_TRIGGER report cols).
    lower_map = {str(x).strip().lower(): x for x in df.columns}
    sma_keep: list[str] = []
    for sma_name in ("SMA20", "SMA50", "SMA100"):
        src = lower_map.get(sma_name.lower())
        if src is not None:
            if src != sma_name:
                df[sma_name] = df[src]
            sma_keep.append(sma_name)
    df = df.set_index("Date")
    cols = ["Open", "High", "Low", "Close", "Volume"] + sma_keep
    out = df[cols].copy()
    for c in ("Open", "High", "Low", "Close", "Volume"):
        out[c] = out[c].astype(float)
    for c in sma_keep:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    return out


def _is_large_up(c: float, c_prev: float, min_pct: float) -> bool:
    if c_prev <= 0:
        return False
    return (c / c_prev) >= (1.0 + min_pct)


def _signal_at(
    i: int,
    o: np.ndarray,
    h: np.ndarray,
    l: np.ndarray,
    c: np.ndarray,
    v: np.ndarray,
    cfg: BurstConfig,
) -> Optional[dict[str, float]]:
    """Return signal metrics dict if bar i is a valid burst signal, else None."""
    lookback = int(cfg.burst_range_lookback)
    if i < lookback + 1:
        return None
    if c[i - 1] <= 0 or c[i] <= 0:
        return None
    pct_day = c[i] / c[i - 1] - 1.0
    if pct_day < cfg.burst_min_pct:
        return None
    if cfg.burst_vol_gt_prior and not (v[i] > v[i - 1]):
        return None
    rng = h[i] - l[i]
    if rng <= 0:
        return None
    # Strict: larger than each of prior N ranges
    for k in range(1, lookback + 1):
        prior_rng = h[i - k] - l[i - k]
        if rng <= prior_rng:
            return None
    dcr = (c[i] - l[i]) / rng
    if dcr < cfg.burst_dcr_min:
        return None
    # Start-of-swing: consecutive large-up days ending at i-1
    prior_ups = 0
    j = i - 1
    while j >= 1 and _is_large_up(c[j], c[j - 1], cfg.burst_min_pct):
        prior_ups += 1
        j -= 1
    if prior_ups > cfg.burst_max_prior_up_days:
        return None
    if c[i] < cfg.burst_min_price:
        return None
    if cfg.burst_min_adv_usd > 0:
        lb = max(1, int(cfg.burst_adv_lookback))
        start = max(0, i - lb + 1)
        adv = float(np.mean(v[start : i + 1] * c[start : i + 1]))
        if adv < cfg.burst_min_adv_usd:
            return None
    # T1 N diagnostics (hard gate applied after _signal_at so Audit can count rejects).
    t1_diag = {"t1_narrow": 0.0, "t1_down": 0.0, "t1_range": float("nan")}
    if i >= int(cfg.burst_range_lookback) + 2:
        _, t1_diag = _t1_narrow_or_down(i, h, l, c, cfg)
    vol_ratio = (v[i] / v[i - 1]) if v[i - 1] > 0 else float("nan")
    # VOL_VS_50 = V[T] / mean(V[T-lookback..T-1]); hard gate after _signal_at (reject counter).
    vol_vs = _vol_vs_avg_at(v, i, int(cfg.burst_vol_avg_lookback or 50))
    vol_vs_50 = float(vol_vs) if vol_vs is not None else float("nan")
    return {
        "pct_day": float(pct_day),
        "dcr": float(dcr),
        "range_exp": float(rng),
        "vol_ratio": float(vol_ratio),
        "vol_vs_50": float(vol_vs_50),
        "signal_low": float(l[i]),
        "signal_close": float(c[i]),
        "t1_narrow": float(t1_diag.get("t1_narrow", 0.0)),
        "t1_down": float(t1_diag.get("t1_down", 0.0)),
        "t1_range": float(t1_diag.get("t1_range", float("nan"))),
    }


def run_symbol_burst(
    symbol: str,
    df: pd.DataFrame,
    cfg: BurstConfig,
    mm_ratio_by_ymd: Optional[dict[str, float]] = None,
) -> BurstSymbolResult:
    if df is None or df.empty:
        return BurstSymbolResult(skipped_reason="empty_df")
    df = df.sort_index()
    o = df["Open"].to_numpy(dtype=np.float64)
    h = df["High"].to_numpy(dtype=np.float64)
    l = df["Low"].to_numpy(dtype=np.float64)
    c = df["Close"].to_numpy(dtype=np.float64)
    v = df["Volume"].to_numpy(dtype=np.float64) if "Volume" in df.columns else np.zeros(len(df))
    dates = [_iso(d) for d in df.index]
    n = len(dates)
    entry_start = _parse_ymd(cfg.entry_start_date)
    entry_end = _parse_ymd(cfg.entry_end_date)
    atr_arr = _atr14_arr(h, l, c, 14)
    atr_gate_on = (
        float(cfg.burst_min_atr_pct_at_trigger or 0.0) > 0.0
        or float(cfg.burst_max_atr_pct_at_trigger or 0.0) > 0.0
    )
    dist_gate_on = (
        float(cfg.burst_min_dist_to_52w_high_pct or 0.0) > 0.0
        or float(cfg.burst_max_dist_to_52w_high_pct or 0.0) > 0.0
    )
    vol_vs_gate_on = float(cfg.burst_vol_vs_avg_mult or 0.0) > 0.0

    res = BurstSymbolResult(bars=n)
    pos = False
    entry_idx = -1
    entry_px = 0.0
    stop_px = 0.0
    target_px = 0.0
    signal_idx = -1
    signal_meta: dict[str, float] = {}
    max_px = 0.0
    saw_ft = False
    pending_signal: Optional[tuple[int, dict[str, float]]] = None  # (signal_i, meta)

    for i in range(n):
        # --- manage open position ---
        if pos:
            max_px = max(max_px, float(h[i]))
            if c[i] > entry_px:
                saw_ft = True
            held = i - entry_idx
            exit_type = ""
            exit_px = 0.0

            # 1) Stop: gap through → GAP_DOWN @open; else intraday STOP_LOSS @stop
            if o[i] <= stop_px:
                exit_type = "GAP_DOWN"
                exit_px = float(o[i])
            elif l[i] <= stop_px:
                exit_type = "STOP_LOSS"
                exit_px = float(stop_px)
            # 2) Target
            elif h[i] >= target_px:
                exit_type = "TARGET"
                exit_px = float(target_px)
            # 3) No follow-through
            elif (
                cfg.burst_no_ft_days > 0
                and held >= cfg.burst_no_ft_days
                and not saw_ft
            ):
                exit_type = "NO_FT"
                exit_px = float(c[i])
            # 4) Time stop
            elif held >= cfg.burst_time_stop_days:
                exit_type = "TIME"
                exit_px = float(c[i])

            if exit_type:
                pnl_pct = (exit_px / entry_px - 1.0) * 100.0
                pnl_d = _pnl_dollars(cfg, entry_px, stop_px, exit_px)
                # calendar days for ann
                try:
                    d0 = datetime.strptime(dates[entry_idx], "%Y%m%d")
                    d1 = datetime.strptime(dates[i], "%Y%m%d")
                    cal_days = max(1, (d1 - d0).days)
                except Exception:
                    cal_days = max(1, held)
                mm_r, t1n, t1d, t1r = _meta_mm_t1(signal_meta)
                row = BurstClosedRow(
                    symbol=symbol,
                    side="LONG",
                    date_opened=dates[entry_idx],
                    entry_price=entry_px,
                    stop_price=stop_px,
                    target_price=target_px,
                    date_closed=dates[i],
                    exit_price=exit_px,
                    exit_type=exit_type,
                    days_held=held,
                    pnl_pct=pnl_pct,
                    pnl_dollars=pnl_d,
                    ann_ror_pct=_ann_ror(pnl_pct, cal_days),
                    max_price=max_px,
                    signal_date=dates[signal_idx],
                    pct_day=float(signal_meta.get("pct_day", 0.0)),
                    dcr=float(signal_meta.get("dcr", 0.0)),
                    range_exp=float(signal_meta.get("range_exp", 0.0)),
                    vol_ratio=float(signal_meta.get("vol_ratio", float("nan"))),
                    signal_low=float(signal_meta.get("signal_low", stop_px)),
                    risk_pct=(entry_px - stop_px) / entry_px if entry_px > 0 else 0.0,
                    mm_ratio=mm_r,
                    t1_narrow=t1n,
                    t1_down=t1d,
                    t1_range=t1r,
                    vol_vs_50=float(signal_meta.get("vol_vs_50", float("nan"))),
                    one_liner=(
                        f"{symbol} | IN {dates[entry_idx]} @ {entry_px:.2f} -> "
                        f"OUT {dates[i]} @ {exit_px:.2f} | {exit_type} {pnl_pct:+.1f}% | {held}d"
                    ),
                )
                res.closed.append(row)
                pos = False
                pending_signal = None
                continue

        # --- fill pending signal at this open ---
        if (not pos) and pending_signal is not None:
            sig_i, meta = pending_signal
            pending_signal = None
            if cfg.burst_fill != "next_open":
                continue
            fill = float(o[i])
            lod = float(meta["signal_low"])
            above, at_or_below = buy_open_band(lod, cfg.burst_max_risk_pct)
            if fill <= 0:
                continue
            risk = (fill - lod) / fill
            reject_reason = ""
            if fill <= lod or risk < 0:
                # open at/below LOD (gap through stop) — too low
                reject_reason = "TOO_LOW"
            elif risk > cfg.burst_max_risk_pct + 1e-12:
                # risk=(O-L)/O above max — open too high
                reject_reason = "TOO_HIGH"
            if reject_reason:
                res.rejected_risk += 1
                if reject_reason == "TOO_LOW":
                    res.rejected_too_low += 1
                elif reject_reason == "TOO_HIGH":
                    res.rejected_too_high += 1
                res.rejected_fills.append(
                    BurstRejectedFillRow(
                        symbol=symbol,
                        signal_date=dates[sig_i],
                        fill_date=dates[i],
                        signal_low=lod,
                        fill_open=fill,
                        must_open_above=above,
                        must_open_at_or_below=at_or_below,
                        max_risk_pct=float(cfg.burst_max_risk_pct),
                        reject_reason=reject_reason,
                        risk_pct=risk,
                    )
                )
                continue
            # entry date window on fill date
            if entry_start and dates[i] < entry_start:
                continue
            if entry_end and dates[i] > entry_end:
                continue
            pos = True
            entry_idx = i
            entry_px = fill
            stop_px = lod
            target_px = fill * cfg.target_pct
            signal_idx = sig_i
            signal_meta = meta
            max_px = max(fill, float(h[i]))
            saw_ft = c[i] > entry_px
            # same-bar exit possible after fill
            held = 0
            exit_type = ""
            exit_px = 0.0
            if o[i] <= stop_px or l[i] <= stop_px:
                # opened through stop shouldn't happen (rejected above); intraday stop
                if l[i] <= stop_px and fill > stop_px:
                    exit_type = "STOP_LOSS"
                    exit_px = float(stop_px)
            if not exit_type and h[i] >= target_px:
                exit_type = "TARGET"
                exit_px = float(target_px)
            if exit_type:
                pnl_pct = (exit_px / entry_px - 1.0) * 100.0
                pnl_d = _pnl_dollars(cfg, entry_px, stop_px, exit_px)
                mm_r, t1n, t1d, t1r = _meta_mm_t1(signal_meta)
                row = BurstClosedRow(
                    symbol=symbol,
                    side="LONG",
                    date_opened=dates[entry_idx],
                    entry_price=entry_px,
                    stop_price=stop_px,
                    target_price=target_px,
                    date_closed=dates[i],
                    exit_price=exit_px,
                    exit_type=exit_type,
                    days_held=0,
                    pnl_pct=pnl_pct,
                    pnl_dollars=pnl_d,
                    ann_ror_pct=0.0,
                    max_price=max(max_px, float(h[i])),
                    signal_date=dates[signal_idx],
                    pct_day=float(signal_meta.get("pct_day", 0.0)),
                    dcr=float(signal_meta.get("dcr", 0.0)),
                    range_exp=float(signal_meta.get("range_exp", 0.0)),
                    vol_ratio=float(signal_meta.get("vol_ratio", float("nan"))),
                    signal_low=float(signal_meta.get("signal_low", stop_px)),
                    risk_pct=(entry_px - stop_px) / entry_px,
                    mm_ratio=mm_r,
                    t1_narrow=t1n,
                    t1_down=t1d,
                    t1_range=t1r,
                    vol_vs_50=float(signal_meta.get("vol_vs_50", float("nan"))),
                    one_liner=(
                        f"{symbol} | IN {dates[entry_idx]} @ {entry_px:.2f} -> "
                        f"OUT {dates[i]} @ {exit_px:.2f} | {exit_type} {pnl_pct:+.1f}% | 0d"
                    ),
                )
                res.closed.append(row)
                pos = False
            continue

        # --- scan for new signal (only when flat; no pending) ---
        if pos or pending_signal is not None:
            continue
        meta = _signal_at(i, o, h, l, c, v, cfg)
        if meta is None:
            continue
        if cfg.burst_require_t1_narrow_or_down:
            ok_t1 = (float(meta.get("t1_narrow", 0.0)) > 0.0) or (
                float(meta.get("t1_down", 0.0)) > 0.0
            )
            # Insufficient history for T−1 N → fail closed when gate ON
            if i < int(cfg.burst_range_lookback) + 2 or not ok_t1:
                res.rejected_t1_n += 1
                continue
        blocks_mm, mm_ratio = _mm_gate_blocks(cfg, i, dates, mm_ratio_by_ymd)
        meta["mm_ratio"] = float(mm_ratio)
        if blocks_mm:
            res.rejected_mm += 1
            continue
        if atr_gate_on:
            atr_pct = _atr_pct_at_bar(atr_arr, c, i)
            if _atr_gate_blocks(cfg, atr_pct):
                res.rejected_atr += 1
                continue
        if dist_gate_on:
            dist = _dist_to_52w_high_pct(h, float(c[i]), i)
            if _dist52_gate_blocks(cfg, dist):
                res.rejected_dist52 += 1
                continue
        if vol_vs_gate_on:
            vs = meta.get("vol_vs_50", float("nan"))
            vs_f = float(vs) if vs is not None and np.isfinite(float(vs)) else None
            if _vol_vs_avg_gate_blocks(cfg, vs_f):
                res.rejected_vol_vs_avg += 1
                continue
        res.signals += 1
        # queue fill for next bar
        if i + 1 < n:
            pending_signal = (i, meta)
        else:
            # last bar signal → watchlist only
            above, at_or_below = buy_open_band(meta["signal_low"], cfg.burst_max_risk_pct)
            res.watch_row = BurstWatchRow(
                symbol=symbol,
                asof_date=dates[i],
                signal_date=dates[i],
                pct_day=meta["pct_day"],
                dcr=meta["dcr"],
                range_exp=meta["range_exp"],
                vol_ratio=meta["vol_ratio"],
                signal_low=meta["signal_low"],
                must_open_above=above,
                must_open_at_or_below=at_or_below,
                max_risk_pct=float(cfg.burst_max_risk_pct),
                notes="signal_on_last_bar_no_fill",
                mm_ratio=float(meta.get("mm_ratio", float("nan"))),
                t1_narrow=int(meta.get("t1_narrow", 0) or 0),
                t1_down=int(meta.get("t1_down", 0) or 0),
                t1_range=float(meta.get("t1_range", float("nan"))),
                vol_vs_50=float(meta.get("vol_vs_50", float("nan"))),
            )

    if pos:
        i = n - 1
        held = i - entry_idx
        pnl_pct = (c[i] / entry_px - 1.0) * 100.0
        mm_r, t1n, t1d, t1r = _meta_mm_t1(signal_meta)
        res.open_row = BurstOpenRow(
            symbol=symbol,
            side="LONG",
            date_opened=dates[entry_idx],
            entry_price=entry_px,
            stop_price=stop_px,
            target_price=target_px,
            current_price=float(c[i]),
            days_held=held,
            pnl_pct=pnl_pct,
            pnl_dollars=_pnl_dollars(cfg, entry_px, stop_px, float(c[i])),
            max_price=max_px,
            signal_date=dates[signal_idx],
            pct_day=float(signal_meta.get("pct_day", 0.0)),
            dcr=float(signal_meta.get("dcr", 0.0)),
            range_exp=float(signal_meta.get("range_exp", 0.0)),
            vol_ratio=float(signal_meta.get("vol_ratio", float("nan"))),
            signal_low=float(signal_meta.get("signal_low", stop_px)),
            risk_pct=(entry_px - stop_px) / entry_px if entry_px > 0 else 0.0,
            mm_ratio=mm_r,
            t1_narrow=t1n,
            t1_down=t1d,
            t1_range=t1r,
            vol_vs_50=float(signal_meta.get("vol_vs_50", float("nan"))),
        )
    return res


CLOSED_FIELDS = [
    "SYMBOL",
    "SIDE",
    "DATE_OPENED",
    "ENTRY_PRICE",
    "STOP_PRICE",
    "TARGET_PRICE",
    "DATE_CLOSED",
    "EXIT_PRICE",
    "EXIT_TYPE",
    "DAYS_HELD",
    "PNL_PCT",
    "PNL_DOLLARS",
    "ANN_ROR_PCT",
    "MAX_PRICE",
    "SIGNAL_DATE",
    "PCT_DAY",
    "DCR",
    "RANGE_EXP",
    "VOL_RATIO",
    "VOL_VS_50",
    "SIGNAL_LOW",
    "RISK_PCT",
    "MM_RATIO",
    "T1_NARROW",
    "T1_DOWN",
    "T1_RANGE",
    "ONE_LINER",
]

OPEN_FIELDS = [
    "SYMBOL",
    "SIDE",
    "DATE_OPENED",
    "ENTRY_PRICE",
    "STOP_PRICE",
    "TARGET_PRICE",
    "CURRENT_PRICE",
    "DAYS_HELD",
    "PNL_PCT",
    "PNL_DOLLARS",
    "MAX_PRICE",
    "SIGNAL_DATE",
    "PCT_DAY",
    "DCR",
    "RANGE_EXP",
    "VOL_RATIO",
    "VOL_VS_50",
    "SIGNAL_LOW",
    "RISK_PCT",
    "MM_RATIO",
    "T1_NARROW",
    "T1_DOWN",
    "T1_RANGE",
]

WATCH_FIELDS = [
    "SYMBOL",
    "ASOF_DATE",
    "SIGNAL_DATE",
    "PCT_DAY",
    "DCR",
    "RANGE_EXP",
    "VOL_RATIO",
    "VOL_VS_50",
    "SIGNAL_LOW",
    "MUST_OPEN_ABOVE",
    "MUST_OPEN_AT_OR_BELOW",
    "MAX_RISK_PCT",
    "NOTES",
    "MM_RATIO",
    "T1_NARROW",
    "T1_DOWN",
    "T1_RANGE",
]

REJECTED_FILL_FIELDS = [
    "SYMBOL",
    "SIGNAL_DATE",
    "FILL_DATE",
    "SIGNAL_LOW",
    "FILL_OPEN",
    "MUST_OPEN_ABOVE",
    "MUST_OPEN_AT_OR_BELOW",
    "MAX_RISK_PCT",
    "REJECT_REASON",
    "RISK_PCT",
]

SUMMARY_FIELDS = [
    "SYMBOL",
    "TRADES",
    "WINS",
    "LOSSES",
    "BEs",
    "PCT_WINS",
    "TOTAL_PNL",
    "SHEET_PNL",
    "AVG_PNL_PCT",
    "PCT_OF_TOTAL_PNL",
    # Same names/order as BRT/YH/RS write_brt_summary (filled by write_analysis_artifacts).
    "CURRENT_MARKET_CAP",
    "SECTOR",
    "INDUSTRY",
    "FIRST_DATA_DATE",
    "AVG_TRADES_PER_YEAR",
    "AVG_DAYS_HELD",
    "MAX_WIN_PCT",
    "MEDIAN_PNL_PCT",
    "EXIT_STOP",
    "EXIT_TARGET",
    "EXIT_TIME",
    "EXIT_NO_FT",
]


def _fmt_pct(x: float) -> str:
    return f"{x:.2f}%"


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _fmt_mm_t1_fields(r: Any) -> dict[str, Any]:
    mm = getattr(r, "mm_ratio", float("nan"))
    t1r = getattr(r, "t1_range", float("nan"))
    vs = getattr(r, "vol_vs_50", float("nan"))
    return {
        "VOL_VS_50": f"{float(vs):.4f}" if vs is not None and math.isfinite(float(vs)) else "",
        "MM_RATIO": f"{float(mm):.4f}" if mm is not None and math.isfinite(float(mm)) else "",
        "T1_NARROW": int(getattr(r, "t1_narrow", 0) or 0),
        "T1_DOWN": int(getattr(r, "t1_down", 0) or 0),
        "T1_RANGE": f"{float(t1r):.4f}" if t1r is not None and math.isfinite(float(t1r)) else "",
    }


def closed_to_dict(r: BurstClosedRow) -> dict[str, Any]:
    out = {
        "SYMBOL": r.symbol,
        "SIDE": r.side,
        "DATE_OPENED": r.date_opened,
        "ENTRY_PRICE": f"{r.entry_price:.4f}",
        "STOP_PRICE": f"{r.stop_price:.4f}",
        "TARGET_PRICE": f"{r.target_price:.4f}",
        "DATE_CLOSED": r.date_closed,
        "EXIT_PRICE": f"{r.exit_price:.4f}",
        "EXIT_TYPE": r.exit_type,
        "DAYS_HELD": r.days_held,
        "PNL_PCT": _fmt_pct(r.pnl_pct),
        "PNL_DOLLARS": f"{r.pnl_dollars:.2f}",
        "ANN_ROR_PCT": f"{r.ann_ror_pct:.2f}",
        "MAX_PRICE": f"{r.max_price:.4f}",
        "SIGNAL_DATE": r.signal_date,
        "PCT_DAY": f"{r.pct_day:.4f}",
        "DCR": f"{r.dcr:.4f}",
        "RANGE_EXP": f"{r.range_exp:.4f}",
        "VOL_RATIO": f"{r.vol_ratio:.4f}" if math.isfinite(r.vol_ratio) else "",
        "SIGNAL_LOW": f"{r.signal_low:.4f}",
        "RISK_PCT": f"{r.risk_pct:.4f}",
        "ONE_LINER": r.one_liner,
    }
    out.update(_fmt_mm_t1_fields(r))
    return out


def open_to_dict(r: BurstOpenRow) -> dict[str, Any]:
    out = {
        "SYMBOL": r.symbol,
        "SIDE": r.side,
        "DATE_OPENED": r.date_opened,
        "ENTRY_PRICE": f"{r.entry_price:.4f}",
        "STOP_PRICE": f"{r.stop_price:.4f}",
        "TARGET_PRICE": f"{r.target_price:.4f}",
        "CURRENT_PRICE": f"{r.current_price:.4f}",
        "DAYS_HELD": r.days_held,
        "PNL_PCT": _fmt_pct(r.pnl_pct),
        "PNL_DOLLARS": f"{r.pnl_dollars:.2f}",
        "MAX_PRICE": f"{r.max_price:.4f}",
        "SIGNAL_DATE": r.signal_date,
        "PCT_DAY": f"{r.pct_day:.4f}",
        "DCR": f"{r.dcr:.4f}",
        "RANGE_EXP": f"{r.range_exp:.4f}",
        "VOL_RATIO": f"{r.vol_ratio:.4f}" if math.isfinite(r.vol_ratio) else "",
        "SIGNAL_LOW": f"{r.signal_low:.4f}",
        "RISK_PCT": f"{r.risk_pct:.4f}",
    }
    out.update(_fmt_mm_t1_fields(r))
    return out


def watch_to_dict(r: BurstWatchRow) -> dict[str, Any]:
    below = (
        f"{r.must_open_at_or_below:.4f}"
        if math.isfinite(r.must_open_at_or_below)
        else ""
    )
    out = {
        "SYMBOL": r.symbol,
        "ASOF_DATE": r.asof_date,
        "SIGNAL_DATE": r.signal_date,
        "PCT_DAY": f"{r.pct_day:.4f}",
        "DCR": f"{r.dcr:.4f}",
        "RANGE_EXP": f"{r.range_exp:.4f}",
        "VOL_RATIO": f"{r.vol_ratio:.4f}" if math.isfinite(r.vol_ratio) else "",
        "SIGNAL_LOW": f"{r.signal_low:.4f}",
        # Buy next open only if MUST_OPEN_ABOVE < open <= MUST_OPEN_AT_OR_BELOW
        "MUST_OPEN_ABOVE": f"{r.must_open_above:.4f}",
        "MUST_OPEN_AT_OR_BELOW": below,
        "MAX_RISK_PCT": f"{r.max_risk_pct:.4f}",
        "NOTES": r.notes,
    }
    out.update(_fmt_mm_t1_fields(r))
    return out


def rejected_fill_to_dict(r: BurstRejectedFillRow) -> dict[str, Any]:
    below = (
        f"{r.must_open_at_or_below:.4f}"
        if math.isfinite(r.must_open_at_or_below)
        else ""
    )
    risk = f"{r.risk_pct:.4f}" if math.isfinite(r.risk_pct) else ""
    return {
        "SYMBOL": r.symbol,
        "SIGNAL_DATE": r.signal_date,
        "FILL_DATE": r.fill_date,
        "SIGNAL_LOW": f"{r.signal_low:.4f}",
        "FILL_OPEN": f"{r.fill_open:.4f}",
        "MUST_OPEN_ABOVE": f"{r.must_open_above:.4f}",
        "MUST_OPEN_AT_OR_BELOW": below,
        "MAX_RISK_PCT": f"{r.max_risk_pct:.4f}",
        "REJECT_REASON": r.reject_reason,
        "RISK_PCT": risk,
    }


_REJECTED_HTML_SORT_SCRIPT = """
<script>
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : 0;
    if (type === "text") return s.toUpperCase();
    if (type === "date") {
      var d = s.replace(/-/g, "");
      if (/^\\d{8}$/.test(d)) return parseInt(d, 10);
      return 0;
    }
    var n = s.replace(/[$,%+]/g, "").replace(/,/g, "");
    var v = parseFloat(n);
    return Number.isFinite(v) ? v : 0;
  }
  function sortTable(table, col, type, dir) {
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var rows = Array.from(tbody.querySelectorAll("tr"));
    rows.sort(function (a, b) {
      var av = parseSortValue(a.cells[col] && a.cells[col].textContent, type);
      var bv = parseSortValue(b.cells[col] && b.cells[col].textContent, type);
      if (typeof av === "string" || typeof bv === "string") {
        return dir * String(av).localeCompare(String(bv));
      }
      return dir * (av - bv);
    });
    rows.forEach(function (r) { tbody.appendChild(r); });
  }
  document.querySelectorAll("table.sortable").forEach(function (table) {
    table.querySelectorAll("th.sortable-th").forEach(function (th, col) {
      function onActivate(e) {
        if (e.type === "touchend") e.preventDefault();
        var type = th.dataset.sort || "text";
        var dir = th.dataset.dir === "asc" ? -1 : 1;
        table.querySelectorAll("th.sortable-th").forEach(function (h) {
          h.dataset.dir = "";
          h.classList.remove("sort-asc", "sort-desc");
          h.setAttribute("aria-sort", "none");
        });
        th.dataset.dir = dir === 1 ? "asc" : "desc";
        th.classList.add(dir === 1 ? "sort-asc" : "sort-desc");
        th.setAttribute("aria-sort", dir === 1 ? "ascending" : "descending");
        sortTable(table, col, type, dir);
      }
      th.addEventListener("click", onActivate);
      th.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onActivate(e); }
      });
      th.addEventListener("touchend", onActivate, { passive: false });
    });
  });
})();
</script>
"""


def _sortable_th(label: str, sort_type: str) -> str:
    import html as html_mod

    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def write_rejected_fills_html(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    stamp: str,
    n_too_low: int,
    n_too_high: int,
    n_other: int = 0,
) -> None:
    """Simple HTML twin of RejectedFills CSV (sortable table)."""
    import html as html_mod

    total = len(rows)
    cols = [
        ("SYMBOL", "text"),
        ("SIGNAL_DATE", "date"),
        ("FILL_DATE", "date"),
        ("SIGNAL_LOW", "num"),
        ("FILL_OPEN", "num"),
        ("MUST_OPEN_ABOVE", "num"),
        ("MUST_OPEN_AT_OR_BELOW", "num"),
        ("MAX_RISK_PCT", "num"),
        ("REJECT_REASON", "text"),
        ("RISK_PCT", "num"),
    ]
    thead = "".join(_sortable_th(c, t) for c, t in cols)
    body_parts: list[str] = []
    for r in rows:
        tds = "".join(
            f"<td>{html_mod.escape(str(r.get(c, '') or ''))}</td>" for c, _ in cols
        )
        reason = str(r.get("REJECT_REASON", "") or "")
        cls = ""
        if reason == "TOO_LOW":
            cls = ' class="too-low"'
        elif reason == "TOO_HIGH":
            cls = ' class="too-high"'
        body_parts.append(f"<tr{cls}>{tds}</tr>")
    body = "\n".join(body_parts) if body_parts else "<tr><td colspan='10'>No rejected fills</td></tr>"
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>SB Rejected Fills {html_mod.escape(stamp)}</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 1.25rem; color: #0f172a; background: #f8fafc; }}
h1 {{ font-size: 1.25rem; margin: 0 0 0.35rem; }}
.sub {{ color: #64748b; font-size: 0.9rem; margin-bottom: 1rem; }}
.counts {{ display: flex; flex-wrap: wrap; gap: 0.75rem; margin-bottom: 1rem; }}
.counts span {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 6px; padding: 0.35rem 0.7rem; font-size: 0.9rem; }}
.counts .too-low {{ border-color: #93c5fd; background: #eff6ff; }}
.counts .too-high {{ border-color: #fca5a5; background: #fef2f2; }}
table.sortable {{ border-collapse: collapse; width: 100%; background: #fff; font-size: 0.85rem; }}
th, td {{ border: 1px solid #e2e8f0; padding: 0.35rem 0.5rem; text-align: left; }}
th.sortable-th {{ cursor: pointer; user-select: none; white-space: nowrap; background: #f1f5f9; }}
th.sortable-th:hover {{ background: #e2e8f0; }}
.sort-ind {{ display: inline-block; width: 0.9em; margin-left: 4px; color: #94a3b8; font-size: 10px; }}
th.sort-asc .sort-ind::after {{ content: "▲"; color: #334155; }}
th.sort-desc .sort-ind::after {{ content: "▼"; color: #334155; }}
tr.too-low {{ background: #f8fbff; }}
tr.too-high {{ background: #fffafa; }}
caption {{ caption-side: top; text-align: left; margin-bottom: 0.4rem; color: #64748b; font-size: 0.85rem; }}
</style>
</head>
<body>
<h1>StockBee Rejected Fills</h1>
<p class="sub">stamp={html_mod.escape(stamp)} — pending signals not taken because next open was outside the buy band (MUST_OPEN_ABOVE &lt; open ≤ MUST_OPEN_AT_OR_BELOW). Click column headers to sort.</p>
<div class="counts">
  <span>Total: <strong>{total}</strong></span>
  <span class="too-low">TOO_LOW (open ≤ SIGNAL_LOW): <strong>{n_too_low}</strong></span>
  <span class="too-high">TOO_HIGH (risk &gt; max): <strong>{n_too_high}</strong></span>
  {"<span>OTHER: <strong>" + str(n_other) + "</strong></span>" if n_other else ""}
</div>
<table class="sortable">
<caption>Rejected next-open fills</caption>
<thead><tr>{thead}</tr></thead>
<tbody>
{body}
</tbody>
</table>
{_REJECTED_HTML_SORT_SCRIPT}
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def build_summary(
    closed: list[BurstClosedRow],
    first_dates: dict[str, str],
) -> list[dict[str, Any]]:
    by_sym: dict[str, list[BurstClosedRow]] = {}
    for r in closed:
        by_sym.setdefault(r.symbol, []).append(r)
    total_pnl = sum(r.pnl_dollars for r in closed) or 0.0
    rows: list[dict[str, Any]] = []
    for sym in sorted(by_sym):
        trades = by_sym[sym]
        wins = sum(1 for t in trades if t.pnl_pct > 1e-9)
        losses = sum(1 for t in trades if t.pnl_pct < -1e-9)
        bes = len(trades) - wins - losses
        pnl = sum(t.pnl_dollars for t in trades)
        pcts = [t.pnl_pct for t in trades]
        avg_pct = float(np.mean(pcts)) if pcts else 0.0
        med_pct = float(np.median(pcts)) if pcts else 0.0
        max_win = max(pcts) if pcts else 0.0
        first = first_dates.get(sym, "")
        years = 0.0
        if first and trades:
            try:
                d0 = datetime.strptime(first.replace("-", "")[:8], "%Y%m%d")
                d1 = datetime.strptime(trades[-1].date_closed, "%Y%m%d")
                years = max((d1 - d0).days / DAYS_PER_YEAR, 1e-6)
            except Exception:
                years = 1.0
        elif first:
            try:
                d0 = datetime.strptime(first.replace("-", "")[:8], "%Y%m%d")
                years = max((datetime.now() - d0).days / DAYS_PER_YEAR, 1e-6)
            except Exception:
                years = 1.0
        else:
            years = 1.0
        rows.append(
            {
                "SYMBOL": sym,
                "TRADES": len(trades),
                "WINS": wins,
                "LOSSES": losses,
                "BEs": bes,
                "PCT_WINS": f"{(100.0 * wins / len(trades)) if trades else 0.0:.1f}%",
                "TOTAL_PNL": f"{pnl:.2f}",
                "SHEET_PNL": f"{pnl:.2f}",
                "AVG_PNL_PCT": f"{avg_pct:.2f}%",
                "PCT_OF_TOTAL_PNL": f"{(100.0 * pnl / total_pnl) if total_pnl else 0.0:.1f}%",
                "CURRENT_MARKET_CAP": "",
                "SECTOR": "",
                "INDUSTRY": "",
                "FIRST_DATA_DATE": first,
                "AVG_TRADES_PER_YEAR": f"{(len(trades) / years):.2f}",
                "AVG_DAYS_HELD": (
                    f"{(sum(int(t.days_held or 0) for t in trades) / len(trades)):.1f}"
                    if trades
                    else ""
                ),
                "MAX_WIN_PCT": f"{max_win:.2f}%",
                "MEDIAN_PNL_PCT": f"{med_pct:.2f}",
                "EXIT_STOP": sum(1 for t in trades if t.exit_type == "STOP_LOSS"),
                "EXIT_GAP_DOWN": sum(1 for t in trades if t.exit_type == "GAP_DOWN"),
                "EXIT_TARGET": sum(1 for t in trades if t.exit_type == "TARGET"),
                "EXIT_TIME": sum(1 for t in trades if t.exit_type == "TIME"),
                "EXIT_NO_FT": sum(1 for t in trades if t.exit_type == "NO_FT"),
            }
        )
    return rows


def write_report(path: Path, cfg: BurstConfig, meta: dict[str, Any]) -> None:
    lines = [
        "StockBee Momentum Burst — Seed Engine Report",
        f"stamp={meta.get('stamp')}",
        f"prefix={FILE_PREFIX}",
        f"symbols_requested={meta.get('symbols_requested')}",
        f"symbols_run={meta.get('symbols_run')}",
        f"symbols_skipped={meta.get('symbols_skipped')}",
        f"closed_trades={meta.get('n_closed')}",
        f"open_trades={meta.get('n_open')}",
        f"signals={meta.get('n_signals')}",
        f"rejected_risk={meta.get('n_rejected_risk')}",
        f"rejected_too_low={meta.get('n_rejected_too_low')}",
        f"rejected_too_high={meta.get('n_rejected_too_high')}",
        f"total_pnl_dollars={meta.get('total_pnl'):.2f}",
        f"win_rate={meta.get('win_rate'):.1f}%",
        f"avg_pnl_pct={meta.get('avg_pnl_pct'):.2f}%",
        f"avg_days_held={meta.get('avg_days_held'):.2f}",
        "",
        "Config (Theory defaults unless overridden):",
        f"  burst_min_pct={cfg.burst_min_pct}",
        f"  burst_vol_gt_prior={cfg.burst_vol_gt_prior}",
        f"  burst_range_lookback={cfg.burst_range_lookback}",
        f"  burst_dcr_min={cfg.burst_dcr_min}",
        f"  burst_max_prior_up_days={cfg.burst_max_prior_up_days}",
        f"  burst_fill={cfg.burst_fill}",
        f"  burst_max_risk_pct={cfg.burst_max_risk_pct}",
        f"  target_pct={cfg.target_pct}",
        f"  burst_time_stop_days={cfg.burst_time_stop_days}",
        f"  burst_no_ft_days={cfg.burst_no_ft_days}",
        f"  burst_mm_gate={cfg.burst_mm_gate}",
        f"  burst_mm_min_ratio={cfg.burst_mm_min_ratio}",
        f"  mm_min_shares={cfg.mm_min_shares}",
        f"  mm_min_adv_usd={cfg.mm_min_adv_usd}",
        f"  mm_min_price={cfg.mm_min_price}",
        f"  burst_require_t1_narrow_or_down={cfg.burst_require_t1_narrow_or_down}",
        f"  burst_t1_narrow_mode={cfg.burst_t1_narrow_mode}",
        f"  burst_min_price={cfg.burst_min_price}",
        f"  burst_min_adv_usd={cfg.burst_min_adv_usd}",
        f"  burst_min_atr_pct_at_trigger={cfg.burst_min_atr_pct_at_trigger}",
        f"  burst_max_atr_pct_at_trigger={cfg.burst_max_atr_pct_at_trigger}",
        f"  burst_min_dist_to_52w_high_pct={cfg.burst_min_dist_to_52w_high_pct}",
        f"  burst_max_dist_to_52w_high_pct={cfg.burst_max_dist_to_52w_high_pct}",
        f"  burst_vol_vs_avg_mult={cfg.burst_vol_vs_avg_mult}",
        f"  burst_vol_avg_lookback={cfg.burst_vol_avg_lookback}",
        f"  cash={cfg.cash}",
        f"  burst_size_from_stop={cfg.burst_size_from_stop}",
        f"  burst_risk_frac={cfg.burst_risk_frac}",
        f"  initial_capital={cfg.initial_capital}",
        f"  aggressive_max_multiple={cfg.aggressive_max_multiple}",
        f"  margin_utilization={cfg.margin_utilization}",
        f"  max_positions={cfg.max_positions}",
        f"  aggressive={cfg.aggressive}",
        f"  host_dollar_scale={cfg.host_dollar_scale and not cfg.burst_size_from_stop}",
        "",
        "Skipped symbols:",
    ]
    for item in meta.get("skip_detail", []):
        lines.append(f"  - {item}")
    lines.append("")
    lines.append("Exit mix:")
    for k, v in sorted((meta.get("exit_mix") or {}).items()):
        lines.append(f"  {k}: {v}")
    if meta.get("host_max_positions") is not None:
        lines.append("")
        lines.append("Host sizing:")
        lines.append(f"  Max_Positions={meta.get('host_max_positions')}")
        lines.append(f"  brt_cash_closed={meta.get('host_brt_cash')}")
        lines.append(f"  audit_brt_cash_1m={meta.get('host_audit_brt_cash')}")
        lines.append(f"  dollar_scale={meta.get('host_pnl_scale')}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def burst_config_from_brt(cfg: Any) -> BurstConfig:
    """Map host BRTConfig / -v fields onto BurstConfig."""
    return BurstConfig(
        burst_min_pct=float(getattr(cfg, "burst_min_pct", 0.04) or 0.04),
        burst_vol_gt_prior=_as_bool(getattr(cfg, "burst_vol_gt_prior", True)),
        burst_range_lookback=int(getattr(cfg, "burst_range_lookback", 5) or 5),
        burst_dcr_min=float(getattr(cfg, "burst_dcr_min", 0.70) or 0.70),
        burst_max_prior_up_days=int(getattr(cfg, "burst_max_prior_up_days", 1) or 1),
        burst_fill=str(getattr(cfg, "burst_fill", "next_open") or "next_open"),
        burst_max_risk_pct=float(getattr(cfg, "burst_max_risk_pct", 0.08) or 0.08),
        target_pct=float(getattr(cfg, "target_pct", 1.10) or 1.10),
        burst_time_stop_days=int(getattr(cfg, "burst_time_stop_days", 5) or 5),
        burst_no_ft_days=int(getattr(cfg, "burst_no_ft_days", 3) or 3),
        burst_mm_gate=_as_bool(getattr(cfg, "burst_mm_gate", False)),
        burst_mm_min_ratio=float(getattr(cfg, "burst_mm_min_ratio", 2.0) or 2.0),
        mm_min_shares=float(getattr(cfg, "mm_min_shares", 1000.0) or 1000.0),
        mm_min_adv_usd=float(getattr(cfg, "mm_min_adv_usd", 250_000.0) or 0.0),
        mm_min_price=float(getattr(cfg, "mm_min_price", 5.0) or 5.0),
        mm_move_pct=float(getattr(cfg, "mm_move_pct", 0.04) or 0.04),
        mm_lookback=int(getattr(cfg, "mm_lookback", 10) or 10),
        mm_force_rebuild=_as_bool(getattr(cfg, "mm_force_rebuild", False)),
        burst_require_t1_narrow_or_down=_as_bool(
            getattr(cfg, "burst_require_t1_narrow_or_down", False)
        ),
        burst_t1_narrow_mode=str(getattr(cfg, "burst_t1_narrow_mode", "median") or "median"),
        burst_min_price=float(getattr(cfg, "burst_min_price", 5.0) or 5.0),
        burst_min_adv_usd=float(getattr(cfg, "burst_min_adv_usd", 0.0) or 0.0),
        burst_adv_lookback=int(getattr(cfg, "burst_adv_lookback", 20) or 20),
        burst_min_atr_pct_at_trigger=float(getattr(cfg, "burst_min_atr_pct_at_trigger", 0.0) or 0.0),
        burst_max_atr_pct_at_trigger=float(getattr(cfg, "burst_max_atr_pct_at_trigger", 0.0) or 0.0),
        burst_min_dist_to_52w_high_pct=float(getattr(cfg, "burst_min_dist_to_52w_high_pct", 0.0) or 0.0),
        burst_max_dist_to_52w_high_pct=float(getattr(cfg, "burst_max_dist_to_52w_high_pct", 0.0) or 0.0),
        burst_vol_vs_avg_mult=float(getattr(cfg, "burst_vol_vs_avg_mult", 0.0) or 0.0),
        burst_vol_avg_lookback=int(getattr(cfg, "burst_vol_avg_lookback", 50) or 50),
        cash=float(getattr(cfg, "brt_cash", DEFAULT_CASH) or DEFAULT_CASH),
        burst_size_from_stop=_as_bool(getattr(cfg, "burst_size_from_stop", False)),
        burst_risk_frac=float(getattr(cfg, "burst_risk_frac", DEFAULT_RISK_FRAC) or DEFAULT_RISK_FRAC),
        entry_start_date=str(getattr(cfg, "entry_start_date", "") or ""),
        entry_end_date=str(getattr(cfg, "entry_end_date", "") or ""),
        initial_capital=float(getattr(cfg, "initial_capital", DEFAULT_INITIAL_CAPITAL) or DEFAULT_INITIAL_CAPITAL),
        aggressive_max_multiple=float(
            getattr(cfg, "aggressive_max_multiple", DEFAULT_AGGRESSIVE_MAX_MULTIPLE)
            or DEFAULT_AGGRESSIVE_MAX_MULTIPLE
        ),
        margin_utilization=float(
            getattr(cfg, "margin_utilization", DEFAULT_MARGIN_UTILIZATION) or DEFAULT_MARGIN_UTILIZATION
        ),
        max_positions=int(getattr(cfg, "max_positions", 0) or 0),
        aggressive=_as_bool(getattr(cfg, "aggressive", False)),
        aggressive_margin_interest=float(getattr(cfg, "aggressive_margin_interest", 0.10) or 0.10),
        aggressive_avg_positions=float(getattr(cfg, "aggressive_avg_positions", 0.0) or 0.0),
        aggressive_sizing_equity_cap=float(getattr(cfg, "aggressive_sizing_equity_cap", 10.0) or 10.0),
        host_dollar_scale=True,
    )


def brt_config_from_burst(bcfg: BurstConfig) -> Any:
    """Minimal BRTConfig for unified Audit/Report writers from standalone BurstConfig."""
    try:
        from rocket_tbn import BRTConfig
    except ImportError:
        from stock_analysis.rocket_tbn import BRTConfig  # type: ignore

    return BRTConfig(
        sb_mode=True,
        brt_zones=False,
        yh_zones=False,
        wpbr_zones=False,
        rl_mode="false",
        relative_strength_enabled=False,
        mvcp_mode=False,
        brt_cash=float(bcfg.cash),
        target_pct=float(bcfg.target_pct),
        initial_capital=float(bcfg.initial_capital),
        aggressive=bool(bcfg.aggressive),
        aggressive_max_multiple=float(bcfg.aggressive_max_multiple),
        margin_utilization=float(bcfg.margin_utilization),
        max_positions=int(bcfg.max_positions),
        aggressive_margin_interest=float(bcfg.aggressive_margin_interest),
        aggressive_avg_positions=float(bcfg.aggressive_avg_positions),
        aggressive_sizing_equity_cap=float(bcfg.aggressive_sizing_equity_cap),
        burst_min_pct=float(bcfg.burst_min_pct),
        burst_vol_gt_prior=bool(bcfg.burst_vol_gt_prior),
        burst_range_lookback=int(bcfg.burst_range_lookback),
        burst_dcr_min=float(bcfg.burst_dcr_min),
        burst_max_prior_up_days=int(bcfg.burst_max_prior_up_days),
        burst_fill=str(bcfg.burst_fill),
        burst_max_risk_pct=float(bcfg.burst_max_risk_pct),
        burst_time_stop_days=int(bcfg.burst_time_stop_days),
        burst_no_ft_days=int(bcfg.burst_no_ft_days),
        burst_mm_gate=bool(bcfg.burst_mm_gate),
        burst_mm_min_ratio=float(bcfg.burst_mm_min_ratio),
        mm_min_shares=float(bcfg.mm_min_shares),
        mm_min_adv_usd=float(bcfg.mm_min_adv_usd),
        mm_min_price=float(bcfg.mm_min_price),
        mm_move_pct=float(bcfg.mm_move_pct),
        mm_lookback=int(bcfg.mm_lookback),
        mm_force_rebuild=bool(bcfg.mm_force_rebuild),
        burst_require_t1_narrow_or_down=bool(bcfg.burst_require_t1_narrow_or_down),
        burst_t1_narrow_mode=str(bcfg.burst_t1_narrow_mode),
        burst_min_price=float(bcfg.burst_min_price),
        burst_min_adv_usd=float(bcfg.burst_min_adv_usd),
        burst_adv_lookback=int(bcfg.burst_adv_lookback),
        burst_min_atr_pct_at_trigger=float(bcfg.burst_min_atr_pct_at_trigger),
        burst_max_atr_pct_at_trigger=float(bcfg.burst_max_atr_pct_at_trigger),
        burst_min_dist_to_52w_high_pct=float(bcfg.burst_min_dist_to_52w_high_pct),
        burst_max_dist_to_52w_high_pct=float(bcfg.burst_max_dist_to_52w_high_pct),
        burst_vol_vs_avg_mult=float(bcfg.burst_vol_vs_avg_mult),
        burst_vol_avg_lookback=int(bcfg.burst_vol_avg_lookback),
        burst_size_from_stop=bool(bcfg.burst_size_from_stop),
        burst_risk_frac=float(bcfg.burst_risk_frac),
        host_dollar_scale=bool(bcfg.host_dollar_scale),
        sb_gold_universe="",
        entry_start_date=str(bcfg.entry_start_date or ""),
        entry_end_date=str(bcfg.entry_end_date or ""),
    )


def burst_closed_to_brt_trade(r: BurstClosedRow) -> Any:
    try:
        from rocket_tbn import BRTTrade
    except ImportError:
        from stock_analysis.rocket_tbn import BRTTrade  # type: ignore

    t = BRTTrade(
        symbol=r.symbol,
        date_opened=r.date_opened,
        entry_price=float(r.entry_price),
        stop_price=float(r.stop_price),
        target_price=float(r.target_price),
        date_closed=r.date_closed,
        exit_price=float(r.exit_price),
        exit_type=r.exit_type,
        days_held=int(r.days_held),
        pnl_pct=float(r.pnl_pct),
        pnl_dollars=float(r.pnl_dollars),
        max_price=float(r.max_price or r.entry_price),
        side=str(r.side or "LONG"),
    )
    # Signal bar for OHLC post-enrich (ATR_PCT_AT_TRIGGER etc.); not a BRTTrade field.
    t.signal_date = str(r.signal_date or "")
    return t


def burst_open_to_brt_trade(r: BurstOpenRow) -> Any:
    try:
        from rocket_tbn import BRTTrade
    except ImportError:
        from stock_analysis.rocket_tbn import BRTTrade  # type: ignore

    t = BRTTrade(
        symbol=r.symbol,
        date_opened=r.date_opened,
        entry_price=float(r.entry_price),
        stop_price=float(r.stop_price),
        target_price=float(r.target_price),
        days_held=int(r.days_held),
        pnl_pct=float(r.pnl_pct),
        pnl_dollars=float(r.pnl_dollars),
        max_price=float(r.max_price or r.entry_price),
        side=str(r.side or "LONG"),
    )
    t.signal_date = str(r.signal_date or "")
    return t


def _burst_dna_closed_dict(r: BurstClosedRow) -> dict[str, str]:
    out = {
        "SIGNAL_DATE": r.signal_date,
        "PCT_DAY": f"{r.pct_day:.4f}",
        "DCR": f"{r.dcr:.4f}",
        "RANGE_EXP": f"{r.range_exp:.4f}",
        "VOL_RATIO": f"{r.vol_ratio:.4f}" if math.isfinite(r.vol_ratio) else "",
        "SIGNAL_LOW": f"{r.signal_low:.4f}",
        "RISK_PCT": f"{r.risk_pct:.4f}",
    }
    out.update({k: str(v) for k, v in _fmt_mm_t1_fields(r).items()})
    return out


def _burst_dna_open_dict(r: BurstOpenRow) -> dict[str, str]:
    out = {
        "SIGNAL_DATE": r.signal_date,
        "PCT_DAY": f"{r.pct_day:.4f}",
        "DCR": f"{r.dcr:.4f}",
        "RANGE_EXP": f"{r.range_exp:.4f}",
        "VOL_RATIO": f"{r.vol_ratio:.4f}" if math.isfinite(r.vol_ratio) else "",
        "SIGNAL_LOW": f"{r.signal_low:.4f}",
        "RISK_PCT": f"{r.risk_pct:.4f}",
    }
    out.update({k: str(v) for k, v in _fmt_mm_t1_fields(r).items()})
    return out


def _splice_burst_dna_columns(
    path: Path,
    dna_by_key: dict[tuple[str, str, str], dict[str, str]],
    dna_cols: tuple[str, ...],
    *,
    open_mode: bool = False,
) -> None:
    """Append burst DNA columns onto a BRT Closed/Open CSV without remapping zones."""
    if not path.is_file():
        return
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    if not fieldnames:
        return
    for c in dna_cols:
        if c not in fieldnames:
            fieldnames.append(c)
    for row in rows:
        sym = str(row.get("SYMBOL", "") or "").strip().upper()
        opened = str(row.get("DATE_OPENED", "") or "").strip()
        closed = "" if open_mode else str(row.get("DATE_CLOSED", "") or "").strip()
        dna = dna_by_key.get((sym, opened, closed)) or dna_by_key.get((sym, opened, ""))
        if not dna:
            for c in dna_cols:
                row.setdefault(c, "")
            continue
        for c in dna_cols:
            row[c] = dna.get(c, "")
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def write_audit_report(
    path: Path,
    stamp: str,
    cfg: BurstConfig,
    meta: dict[str, Any],
    *,
    drive_link: str = "",
    host_cfg: Any = None,
    brt_closed: Optional[list[Any]] = None,
) -> None:
    """Unified wide-row Audit (same columns as YH/BRT/RS via write_brt_audit_report)."""
    try:
        from rocket_tbn import compute_metrics, write_brt_audit_report
    except ImportError:
        from stock_analysis.rocket_tbn import compute_metrics, write_brt_audit_report  # type: ignore

    report_cfg = host_cfg if host_cfg is not None else brt_config_from_burst(cfg)
    # Ensure sb_mode + burst levers are on the cfg used for Audit fill.
    try:
        report_cfg = replace(
            report_cfg,
            sb_mode=True,
            brt_cash=float(getattr(report_cfg, "brt_cash", cfg.cash) or cfg.cash),
            target_pct=float(cfg.target_pct),
            burst_min_pct=float(cfg.burst_min_pct),
            burst_vol_gt_prior=bool(cfg.burst_vol_gt_prior),
            burst_range_lookback=int(cfg.burst_range_lookback),
            burst_dcr_min=float(cfg.burst_dcr_min),
            burst_max_prior_up_days=int(cfg.burst_max_prior_up_days),
            burst_fill=str(cfg.burst_fill),
            burst_max_risk_pct=float(cfg.burst_max_risk_pct),
            burst_time_stop_days=int(cfg.burst_time_stop_days),
            burst_no_ft_days=int(cfg.burst_no_ft_days),
            burst_mm_gate=bool(cfg.burst_mm_gate),
            burst_mm_min_ratio=float(cfg.burst_mm_min_ratio),
            mm_min_shares=float(cfg.mm_min_shares),
            mm_min_adv_usd=float(cfg.mm_min_adv_usd),
            mm_min_price=float(cfg.mm_min_price),
            mm_move_pct=float(cfg.mm_move_pct),
            mm_lookback=int(cfg.mm_lookback),
            mm_force_rebuild=bool(cfg.mm_force_rebuild),
            burst_require_t1_narrow_or_down=bool(cfg.burst_require_t1_narrow_or_down),
            burst_t1_narrow_mode=str(cfg.burst_t1_narrow_mode),
            burst_min_price=float(cfg.burst_min_price),
            burst_min_adv_usd=float(cfg.burst_min_adv_usd),
            burst_adv_lookback=int(cfg.burst_adv_lookback),
            burst_min_atr_pct_at_trigger=float(cfg.burst_min_atr_pct_at_trigger),
            burst_max_atr_pct_at_trigger=float(cfg.burst_max_atr_pct_at_trigger),
            burst_min_dist_to_52w_high_pct=float(cfg.burst_min_dist_to_52w_high_pct),
            burst_max_dist_to_52w_high_pct=float(cfg.burst_max_dist_to_52w_high_pct),
            burst_vol_vs_avg_mult=float(cfg.burst_vol_vs_avg_mult),
            burst_vol_avg_lookback=int(cfg.burst_vol_avg_lookback),
            burst_size_from_stop=bool(cfg.burst_size_from_stop),
            burst_risk_frac=float(cfg.burst_risk_frac),
            host_dollar_scale=bool(cfg.host_dollar_scale),
            sb_gold_universe=str(meta.get("sb_gold_universe") or ""),
            initial_capital=float(cfg.initial_capital),
            aggressive=bool(cfg.aggressive),
            aggressive_max_multiple=float(cfg.aggressive_max_multiple),
            margin_utilization=float(cfg.margin_utilization),
            max_positions=int(cfg.max_positions),
        )
    except TypeError:
        pass

    trades = list(brt_closed or [])
    if not trades:
        trades = []  # metrics empty path
    metrics = compute_metrics(trades, report_cfg)
    if meta.get("host_max_positions") is not None:
        metrics["Max_Positions"] = int(meta["host_max_positions"])
    if meta.get("max_dd_pct") not in (None, ""):
        metrics["Max_Drawdown"] = meta.get("max_dd_pct")
    if meta.get("aggressive_total_pnl") not in (None, ""):
        metrics["Aggressive_Total_PNL"] = meta.get("aggressive_total_pnl")
    if meta.get("aggressive_max_dd") not in (None, ""):
        metrics["Aggressive_Max_Drawdown"] = meta.get("aggressive_max_dd")
    if meta.get("aggressive_avg_positions") not in (None, ""):
        metrics["Aggressive_Avg_Positions"] = meta.get("aggressive_avg_positions")
    if meta.get("aggressive_days_at_or_below_avg") not in (None, ""):
        metrics["Aggressive_Days_AtOrBelow_Avg"] = meta.get("aggressive_days_at_or_below_avg")
    if meta.get("aggressive_days_in_margin") not in (None, ""):
        metrics["Aggressive_Days_In_Margin"] = meta.get("aggressive_days_in_margin")
    if meta.get("aggressive_days_trimmed_over_2xavg") not in (None, ""):
        metrics["Aggressive_Days_Trimmed_Over_2xAvg"] = meta.get(
            "aggressive_days_trimmed_over_2xavg"
        )
    # SB rejected-fill / signal counters (blank on non-SB via _fill_sb_mode_audit)
    if meta.get("n_signals") is not None:
        metrics["sb_signals_total"] = int(meta.get("n_signals") or 0)
    if meta.get("n_rejected_risk") is not None:
        metrics["sb_rejected_fills_total"] = int(meta.get("n_rejected_risk") or 0)
    if meta.get("n_rejected_too_low") is not None:
        metrics["sb_rejected_too_low"] = int(meta.get("n_rejected_too_low") or 0)
    if meta.get("n_rejected_too_high") is not None:
        metrics["sb_rejected_too_high"] = int(meta.get("n_rejected_too_high") or 0)
    if meta.get("n_rejected_mm") is not None:
        metrics["sb_rejected_mm"] = int(meta.get("n_rejected_mm") or 0)
    if meta.get("n_rejected_t1_n") is not None:
        metrics["sb_rejected_t1_n"] = int(meta.get("n_rejected_t1_n") or 0)
    if meta.get("n_rejected_vol_vs_avg") is not None:
        metrics["sb_rejected_vol_vs_avg"] = int(meta.get("n_rejected_vol_vs_avg") or 0)

    out_dir = path.parent
    write_brt_audit_report(
        report_cfg,
        metrics,
        str(out_dir),
        stamp,
        drive_link=drive_link,
        file_prefix=FILE_PREFIX,
    )
    # write_brt_audit_report names the file; ensure path caller expects exists
    written = out_dir / f"{FILE_PREFIX}_Audit_Report_{stamp}.csv"
    if written.exists() and written.resolve() != path.resolve():
        path.write_bytes(written.read_bytes())


def _ymd_to_iso(s: str) -> str:
    s = (s or "").strip().replace("-", "")
    if len(s) >= 8 and s[:8].isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def write_equity_curve_from_closed(
    path: Path,
    meta_path: Path,
    closed: list[BurstClosedRow],
    *,
    initial_cash: float,
) -> tuple[float, float]:
    """Simple realized-ledger equity: cash + cumulative PNL_DOLLARS by DATE_CLOSED.

    Returns (max_dd_fraction, max_dd_pct). Not a full portfolio sim (no concurrent
    mark-to-market) — matches experimental-system parity needs.
    """
    by_date: dict[str, float] = {}
    for r in closed:
        d = _ymd_to_iso(r.date_closed)
        if not d:
            continue
        by_date[d] = by_date.get(d, 0.0) + float(r.pnl_dollars)
    dates = sorted(by_date)
    equity = float(initial_cash)
    peak = equity
    max_dd = 0.0
    rows: list[dict[str, Any]] = []
    for d in dates:
        equity += by_date[d]
        if equity > peak:
            peak = equity
        dd = ((peak - equity) / peak) if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
        rows.append({"Date": d, "Equity": equity, "Positions": ""})
    if not rows:
        rows.append({"Date": "", "Equity": initial_cash, "Positions": ""})
        max_dd = 0.0
    pd.DataFrame(rows).to_csv(path, index=False)
    max_dd_pct = max_dd * 100.0
    pd.DataFrame(
        [
            {
                "Initial_Account_Size": initial_cash,
                "Max_Drawdown_fraction": max_dd,
                "Max_Drawdown_pct": f"{max_dd_pct:.2f}%",
                "Max_Days_Underwater": "",
                "Pct_Days_Underwater": "",
                "Aggressive": False,
                "Curve_Kind": "realized_pnl_by_exit_date",
            }
        ]
    ).to_csv(meta_path, index=False)
    return max_dd, max_dd_pct


def parse_symbols(s: str) -> list[str]:
    return [x.strip().upper() for x in (s or "").replace(";", ",").split(",") if x.strip()]


def list_data_dir_symbols(data_dir: Path) -> list[str]:
    """All ticker CSVs under data_dir (skip SPY) — same empty--s universe as rocket_tbn."""
    if _list_csv_symbols is not None:
        return list(_list_csv_symbols(data_dir, include_spy=False))
    if not data_dir.is_dir():
        return []
    return sorted(
        p.stem.upper()
        for p in data_dir.glob("*.csv")
        if p.is_file() and p.stem.upper() != "SPY"
    )


def resolve_run_symbols(symbols_arg: str | None, data_dir: Path) -> list[str]:
    """Whitelist from ``-s``, or full ``data_dir/*.csv`` when empty/None (rocket_tbn parity)."""
    parsed = parse_symbols(symbols_arg or "")
    if parsed:
        return parsed
    return list_data_dir_symbols(data_dir)


def cfg_from_args(ns: argparse.Namespace) -> BurstConfig:
    return BurstConfig(
        burst_min_pct=float(ns.burst_min_pct),
        burst_vol_gt_prior=bool(ns.burst_vol_gt_prior),
        burst_range_lookback=int(ns.burst_range_lookback),
        burst_dcr_min=float(ns.burst_dcr_min),
        burst_max_prior_up_days=int(ns.burst_max_prior_up_days),
        burst_fill=str(ns.burst_fill),
        burst_max_risk_pct=float(ns.burst_max_risk_pct),
        target_pct=float(ns.target_pct),
        burst_time_stop_days=int(ns.burst_time_stop_days),
        burst_no_ft_days=int(ns.burst_no_ft_days),
        burst_mm_gate=bool(ns.burst_mm_gate),
        burst_mm_min_ratio=float(getattr(ns, "burst_mm_min_ratio", 2.0) or 2.0),
        mm_min_shares=float(getattr(ns, "mm_min_shares", 1000.0) or 1000.0),
        mm_min_adv_usd=float(getattr(ns, "mm_min_adv_usd", 250_000.0) or 0.0),
        mm_min_price=float(getattr(ns, "mm_min_price", 5.0) or 5.0),
        mm_move_pct=float(getattr(ns, "mm_move_pct", 0.04) or 0.04),
        mm_lookback=int(getattr(ns, "mm_lookback", 10) or 10),
        mm_force_rebuild=_as_bool(getattr(ns, "mm_force_rebuild", False)),
        burst_require_t1_narrow_or_down=_as_bool(
            getattr(ns, "burst_require_t1_narrow_or_down", False)
        ),
        burst_t1_narrow_mode=str(getattr(ns, "burst_t1_narrow_mode", "median") or "median"),
        burst_min_price=float(ns.burst_min_price),
        burst_min_adv_usd=float(ns.burst_min_adv_usd),
        burst_vol_vs_avg_mult=float(getattr(ns, "burst_vol_vs_avg_mult", 0.0) or 0.0),
        burst_vol_avg_lookback=int(getattr(ns, "burst_vol_avg_lookback", 50) or 50),
        cash=float(ns.cash),
        burst_size_from_stop=_as_bool(ns.burst_size_from_stop),
        burst_risk_frac=float(ns.burst_risk_frac),
        entry_start_date=str(ns.entry_start_date or ""),
        entry_end_date=str(ns.entry_end_date or ""),
        initial_capital=float(ns.initial_capital),
        aggressive_max_multiple=float(ns.aggressive_max_multiple),
        margin_utilization=float(ns.margin_utilization),
        max_positions=int(ns.max_positions),
        aggressive=bool(ns.aggressive),
        aggressive_margin_interest=float(ns.aggressive_margin_interest),
        aggressive_avg_positions=float(ns.aggressive_avg_positions),
        aggressive_sizing_equity_cap=float(ns.aggressive_sizing_equity_cap),
        host_dollar_scale=_as_bool(getattr(ns, "host_dollar_scale", True)),
    )


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="StockBee Momentum Burst seed engine (SB_*)")
    p.add_argument("data_dir", nargs="?", default="data/newdata/data", help="OHLCV CSV directory")
    p.add_argument("-o", "--output-dir", default="drive", help="Output directory")
    p.add_argument(
        "-s",
        "--symbols",
        default="",
        help="Comma-separated symbols (empty = all *.csv in data_dir, excluding SPY). "
        "Production bats default to GOLD_UNIVERSE.csv (56 names) when SB_SYMBOLS unset.",
    )
    p.add_argument("--stamp", default="", help="Override output stamp (default YYMMDDHHMMSS)")
    p.add_argument("--cash", type=float, default=DEFAULT_CASH,
                   help="Placeholder per-trade notional before host dollar-scale (default 47500)")
    p.add_argument("--burst-min-pct", type=float, default=0.04)
    p.add_argument("--burst-vol-gt-prior", type=_as_bool, default=True)
    p.add_argument("--burst-range-lookback", type=int, default=5)
    p.add_argument("--burst-dcr-min", type=float, default=0.70)
    p.add_argument("--burst-max-prior-up-days", type=int, default=1)
    p.add_argument("--burst-fill", default="next_open")
    p.add_argument("--burst-max-risk-pct", type=float, default=0.03)
    p.add_argument("--target-pct", type=float, default=1.10)
    p.add_argument("--burst-time-stop-days", type=int, default=5)
    p.add_argument("--burst-no-ft-days", type=int, default=3)
    p.add_argument("--burst-mm-gate", type=_as_bool, default=False)
    p.add_argument("--burst-mm-min-ratio", type=float, default=2.0)
    p.add_argument("--mm-min-shares", type=float, default=1000.0)
    p.add_argument("--mm-min-adv-usd", type=float, default=250_000.0)
    p.add_argument("--mm-min-price", type=float, default=5.0)
    p.add_argument("--mm-move-pct", type=float, default=0.04)
    p.add_argument("--mm-lookback", type=int, default=10)
    p.add_argument("--mm-force-rebuild", type=_as_bool, default=False)
    p.add_argument("--burst-require-t1-narrow-or-down", type=_as_bool, default=False)
    p.add_argument(
        "--burst-t1-narrow-mode",
        default="median",
        help="T−1 narrow compare: median | mean | max",
    )
    p.add_argument("--burst-min-price", type=float, default=5.0)
    p.add_argument("--burst-min-adv-usd", type=float, default=0.0)
    p.add_argument(
        "--burst-vol-vs-avg-mult",
        type=float,
        default=0.0,
        help="Require Volume_T >= mult * mean(prior lookback volumes). 0 = off (default).",
    )
    p.add_argument(
        "--burst-vol-avg-lookback",
        type=int,
        default=50,
        help="Sessions for vol avg lookback excluding signal bar (default 50).",
    )
    p.add_argument(
        "--burst-size-from-stop",
        type=_as_bool,
        default=False,
        help="If true: shares=(cash*risk_frac)/(entry-stop) Seed-opt path; skips host dollar-scale. "
        "Default false = host fixed notional + dollar-scale",
    )
    p.add_argument(
        "--burst-risk-frac",
        type=float,
        default=DEFAULT_RISK_FRAC,
        help="Fraction of cash risked per trade when size-from-stop ON (default 0.01)",
    )
    p.add_argument("--initial-capital", type=float, default=DEFAULT_INITIAL_CAPITAL)
    p.add_argument("--aggressive-max-multiple", type=float, default=DEFAULT_AGGRESSIVE_MAX_MULTIPLE)
    p.add_argument("--margin-utilization", type=float, default=DEFAULT_MARGIN_UTILIZATION)
    p.add_argument(
        "--max-positions",
        type=int,
        default=0,
        help="Slot divisor for host notional (0=auto peak concurrent closed trades)",
    )
    p.add_argument(
        "--aggressive",
        action="store_true",
        help="Host aggressive equity overlay (EquityCurve_Aggressive_*; same as rocket_tbn)",
    )
    p.add_argument("--aggressive-margin-interest", type=float, default=0.10)
    p.add_argument("--aggressive-avg-positions", type=float, default=0.0)
    p.add_argument("--aggressive-sizing-equity-cap", type=float, default=10.0)
    p.add_argument(
        "--host-dollar-scale",
        type=_as_bool,
        default=True,
        help="Apply host deployable/max_positions dollar-scale when size-from-stop is off",
    )
    p.add_argument("--entry-start-date", default="")
    p.add_argument("--entry-end-date", default="")
    return p


def _load_mm_lookup_for_run(
    cfg: BurstConfig,
    data_dir: Path,
    output_dir: Optional[Path] = None,
) -> Optional[dict[str, float]]:
    """Build/load Market Monitor series when MM gate is ON (or force rebuild)."""
    if not (cfg.burst_mm_gate or cfg.mm_force_rebuild):
        return None
    try:
        from rocket_stockbee_mm import build_or_load_mm_series, mm_cfg_from_burst
    except ImportError:
        from stock_analysis.rocket_stockbee_mm import (  # type: ignore
            build_or_load_mm_series,
            mm_cfg_from_burst,
        )
    cache = Path(output_dir or "drive") / "SB_MM_Series_latest.csv"
    force = bool(cfg.mm_force_rebuild)
    print(
        f"[SB] {'Rebuilding' if force else 'Loading/building'} Market Monitor series "
        f"(gate_min_ratio={cfg.burst_mm_min_ratio}, cache={cache}) …",
        flush=True,
    )
    _frame, lookup, path = build_or_load_mm_series(
        Path(data_dir),
        cfg=mm_cfg_from_burst(cfg),
        cache_path=cache,
        force_rebuild=force,
    )
    print(f"[SB] MM series ready: {path} days={len(lookup)}", flush=True)
    return lookup


def run_backtest(
    symbols: list[str],
    data_dir: Path,
    cfg: BurstConfig,
    *,
    output_dir: Optional[Path] = None,
    mm_ratio_by_ymd: Optional[dict[str, float]] = None,
) -> tuple[
    list[BurstClosedRow],
    list[BurstOpenRow],
    list[BurstWatchRow],
    list[BurstRejectedFillRow],
    dict[str, Any],
    dict[str, pd.DataFrame],
]:
    closed: list[BurstClosedRow] = []
    opens: list[BurstOpenRow] = []
    watches: list[BurstWatchRow] = []
    rejected: list[BurstRejectedFillRow] = []
    tickers: dict[str, pd.DataFrame] = {}
    first_dates: dict[str, str] = {}
    run_syms: list[str] = []
    skip_detail: list[str] = []
    n_signals = 0
    n_rejected = 0
    n_rejected_too_low = 0
    n_rejected_too_high = 0
    n_rejected_atr = 0
    n_rejected_dist52 = 0
    n_rejected_mm = 0
    n_rejected_t1_n = 0
    n_rejected_vol_vs_avg = 0

    if mm_ratio_by_ymd is None:
        mm_ratio_by_ymd = _load_mm_lookup_for_run(cfg, Path(data_dir), output_dir)

    for sym in symbols:
        path = data_dir / f"{sym}.csv"
        if not path.exists():
            skip_detail.append(f"{sym}: missing CSV {path}")
            continue
        try:
            df = load_ohlcv_csv(path)
        except Exception as e:
            skip_detail.append(f"{sym}: load error {e}")
            continue
        if df.empty or len(df) < cfg.burst_range_lookback + 3:
            skip_detail.append(f"{sym}: insufficient bars ({len(df)})")
            continue
        # Critical OHLC sanity
        if df[["Open", "High", "Low", "Close"]].isna().any().any():
            skip_detail.append(f"{sym}: NaN in OHLC — skipped")
            continue
        first_dates[sym] = _iso(df.index[0])
        if len(first_dates[sym]) == 8:
            first_dates[sym] = f"{first_dates[sym][:4]}-{first_dates[sym][4:6]}-{first_dates[sym][6:]}"
        result = run_symbol_burst(sym, df, cfg, mm_ratio_by_ymd=mm_ratio_by_ymd)
        run_syms.append(sym)
        tickers[sym] = df
        closed.extend(result.closed)
        if result.open_row:
            opens.append(result.open_row)
        if result.watch_row:
            watches.append(result.watch_row)
        rejected.extend(result.rejected_fills)
        n_signals += result.signals
        n_rejected += result.rejected_risk
        n_rejected_too_low += result.rejected_too_low
        n_rejected_too_high += result.rejected_too_high
        n_rejected_atr += result.rejected_atr
        n_rejected_dist52 += result.rejected_dist52
        n_rejected_mm += result.rejected_mm
        n_rejected_t1_n += result.rejected_t1_n
        n_rejected_vol_vs_avg += result.rejected_vol_vs_avg

    closed.sort(key=lambda r: (r.symbol, r.date_opened, r.date_closed))
    opens.sort(key=lambda r: r.symbol)
    watches.sort(key=lambda r: r.symbol)
    rejected.sort(key=lambda r: (r.symbol, r.signal_date, r.fill_date))

    exit_mix: dict[str, int] = {}
    for r in closed:
        exit_mix[r.exit_type] = exit_mix.get(r.exit_type, 0) + 1
    wins = sum(1 for r in closed if r.pnl_pct > 0)
    meta = {
        "symbols_requested": symbols,
        "symbols_run": run_syms,
        "symbols_skipped": [s for s in symbols if s not in run_syms],
        "skip_detail": skip_detail,
        "n_closed": len(closed),
        "n_open": len(opens),
        "n_signals": n_signals,
        "n_rejected_risk": n_rejected,
        "n_rejected_too_low": n_rejected_too_low,
        "n_rejected_too_high": n_rejected_too_high,
        "n_rejected_atr": n_rejected_atr,
        "n_rejected_dist52": n_rejected_dist52,
        "n_rejected_mm": n_rejected_mm,
        "n_rejected_t1_n": n_rejected_t1_n,
        "n_rejected_vol_vs_avg": n_rejected_vol_vs_avg,
        "total_pnl": sum(r.pnl_dollars for r in closed),
        "win_rate": (100.0 * wins / len(closed)) if closed else 0.0,
        "avg_pnl_pct": float(np.mean([r.pnl_pct for r in closed])) if closed else 0.0,
        "avg_days_held": float(np.mean([r.days_held for r in closed])) if closed else 0.0,
        "exit_mix": exit_mix,
        "first_dates": first_dates,
    }
    return closed, opens, watches, rejected, meta, tickers


def write_outputs(
    output_dir: Path,
    stamp: str,
    cfg: BurstConfig,
    closed: list[BurstClosedRow],
    opens: list[BurstOpenRow],
    watches: list[BurstWatchRow],
    meta: dict[str, Any],
    tickers: Optional[dict[str, pd.DataFrame]] = None,
    *,
    rejected_fills: Optional[list[BurstRejectedFillRow]] = None,
    host_cfg: Any = None,
    no_yfinance: bool = False,
    drive_link: str = "",
    data_dir: Optional[Path] = None,
) -> dict[str, Path]:
    """Write SB_* artifacts via BRT Closed/Open/Audit/Report writers + burst DNA splice."""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    closed_path = output_dir / f"{FILE_PREFIX}_Closed_{stamp}.csv"
    open_path = output_dir / f"{FILE_PREFIX}_Open_{stamp}.csv"
    summary_path = output_dir / f"{FILE_PREFIX}_Summary_{stamp}.csv"
    watch_path = output_dir / f"{FILE_PREFIX}_Watchlist_{stamp}.csv"
    rejected_path = output_dir / f"{FILE_PREFIX}_RejectedFills_{stamp}.csv"
    rejected_html_path = output_dir / f"{FILE_PREFIX}_RejectedFills_{stamp}.html"
    report_txt_path = output_dir / f"{FILE_PREFIX}_Report_{stamp}.txt"
    audit_path = output_dir / f"{FILE_PREFIX}_Audit_Report_{stamp}.csv"
    equity_path = output_dir / f"{FILE_PREFIX}_EquityCurve_{stamp}.csv"
    equity_meta_path = output_dir / f"{FILE_PREFIX}_EquityMeta_{stamp}.csv"
    corr_path = output_dir / f"{FILE_PREFIX}_Correlation_{stamp}.csv"
    meta = {**meta, "stamp": stamp}
    rejected_list = list(rejected_fills or [])
    if meta.get("n_rejected_too_low") is None:
        meta["n_rejected_too_low"] = sum(1 for r in rejected_list if r.reject_reason == "TOO_LOW")
    if meta.get("n_rejected_too_high") is None:
        meta["n_rejected_too_high"] = sum(1 for r in rejected_list if r.reject_reason == "TOO_HIGH")
    if meta.get("n_rejected_risk") is None:
        meta["n_rejected_risk"] = len(rejected_list)

    try:
        from rocket_tbn import (
            compute_metrics,
            write_brt_closed,
            write_brt_open,
            write_brt_report,
            _enrich_trades_yfinance,
            _enrich_post_entry_gain_hit,
            _enrich_trades_ohlc_features,
            _enrich_trades_entry_indicators,
        )
    except ImportError:
        from stock_analysis.rocket_tbn import (  # type: ignore
            compute_metrics,
            write_brt_closed,
            write_brt_open,
            write_brt_report,
            _enrich_trades_yfinance,
            _enrich_post_entry_gain_hit,
            _enrich_trades_ohlc_features,
            _enrich_trades_entry_indicators,
        )

    report_cfg = host_cfg if host_cfg is not None else brt_config_from_burst(cfg)
    try:
        report_cfg = replace(
            report_cfg,
            sb_mode=True,
            brt_cash=float(cfg.cash),
            target_pct=float(cfg.target_pct),
            burst_min_pct=float(cfg.burst_min_pct),
            burst_vol_gt_prior=bool(cfg.burst_vol_gt_prior),
            burst_range_lookback=int(cfg.burst_range_lookback),
            burst_dcr_min=float(cfg.burst_dcr_min),
            burst_max_prior_up_days=int(cfg.burst_max_prior_up_days),
            burst_fill=str(cfg.burst_fill),
            burst_max_risk_pct=float(cfg.burst_max_risk_pct),
            burst_time_stop_days=int(cfg.burst_time_stop_days),
            burst_no_ft_days=int(cfg.burst_no_ft_days),
            burst_mm_gate=bool(cfg.burst_mm_gate),
            burst_mm_min_ratio=float(cfg.burst_mm_min_ratio),
            mm_min_shares=float(cfg.mm_min_shares),
            mm_min_adv_usd=float(cfg.mm_min_adv_usd),
            mm_min_price=float(cfg.mm_min_price),
            mm_move_pct=float(cfg.mm_move_pct),
            mm_lookback=int(cfg.mm_lookback),
            mm_force_rebuild=bool(cfg.mm_force_rebuild),
            burst_require_t1_narrow_or_down=bool(cfg.burst_require_t1_narrow_or_down),
            burst_t1_narrow_mode=str(cfg.burst_t1_narrow_mode),
            burst_min_price=float(cfg.burst_min_price),
            burst_min_adv_usd=float(cfg.burst_min_adv_usd),
            burst_adv_lookback=int(cfg.burst_adv_lookback),
            burst_min_atr_pct_at_trigger=float(cfg.burst_min_atr_pct_at_trigger),
            burst_max_atr_pct_at_trigger=float(cfg.burst_max_atr_pct_at_trigger),
            burst_min_dist_to_52w_high_pct=float(cfg.burst_min_dist_to_52w_high_pct),
            burst_max_dist_to_52w_high_pct=float(cfg.burst_max_dist_to_52w_high_pct),
            burst_vol_vs_avg_mult=float(cfg.burst_vol_vs_avg_mult),
            burst_vol_avg_lookback=int(cfg.burst_vol_avg_lookback),
            burst_size_from_stop=bool(cfg.burst_size_from_stop),
            burst_risk_frac=float(cfg.burst_risk_frac),
            initial_capital=float(cfg.initial_capital),
            aggressive=bool(cfg.aggressive),
            aggressive_max_multiple=float(cfg.aggressive_max_multiple),
            margin_utilization=float(cfg.margin_utilization),
            max_positions=int(cfg.max_positions),
            brt_zones=False,
            yh_zones=False,
            wpbr_zones=False,
            rl_mode="false",
            relative_strength_enabled=False,
            mvcp_mode=False,
        )
    except TypeError:
        pass

    brt_closed = [burst_closed_to_brt_trade(r) for r in closed]
    brt_open = [burst_open_to_brt_trade(r) for r in opens]

    # Thin burst→BRTTrade dicts skip BRT backtest feature build; fill OHLC peers here
    # (ATR_PCT_AT_TRIGGER, VOLUME_*, SMA*_AT_TRIGGER, HIGH_52W_*, SPY_COMPARE_*, …).
    try:
        _enrich_trades_ohlc_features(
            brt_closed + brt_open,
            tickers or {},
            report_cfg,
            data_dir=data_dir,
        )
    except Exception as e:
        print(f"[SB] OHLC feature enrich skipped: {e}", flush=True)
    try:
        _enrich_trades_entry_indicators(brt_closed + brt_open, tickers or {}, report_cfg)
    except Exception as e:
        print(f"[SB] entry_indicators enrich skipped: {e}", flush=True)
    if not no_yfinance and (brt_closed or brt_open):
        try:
            _enrich_trades_yfinance(brt_closed, brt_open)
        except Exception as e:
            print(f"[SB] yfinance enrich skipped: {e}", flush=True)
    try:
        _enrich_post_entry_gain_hit(brt_closed + brt_open, tickers or {}, report_cfg)
    except Exception as e:
        print(f"[SB] post_entry enrich skipped: {e}", flush=True)

    write_brt_closed(brt_closed, str(closed_path), cfg=report_cfg)
    _splice_burst_dna_columns(
        closed_path,
        {
            (r.symbol.upper(), r.date_opened, r.date_closed): _burst_dna_closed_dict(r)
            for r in closed
        },
        _BURST_DNA_CLOSED_COLS,
    )
    write_brt_open(
        brt_open,
        str(open_path),
        tickers=tickers,
        brt_cash=float(cfg.cash),
        closed=brt_closed,
        cfg=report_cfg,
    )
    _splice_burst_dna_columns(
        open_path,
        {(r.symbol.upper(), r.date_opened, ""): _burst_dna_open_dict(r) for r in opens},
        _BURST_DNA_OPEN_COLS,
        open_mode=True,
    )

    summary_rows = build_summary(closed, meta.get("first_dates") or {})
    by_sym_meta: dict[str, Any] = {}
    for t in brt_closed:
        if t.symbol not in by_sym_meta:
            by_sym_meta[t.symbol] = t
    for row in summary_rows:
        t = by_sym_meta.get(row["SYMBOL"])
        if t is None:
            continue
        mc = getattr(t, "market_cap_current", None)
        if mc is not None:
            try:
                row["CURRENT_MARKET_CAP"] = f"{float(mc):.0f}"
            except (TypeError, ValueError):
                pass
        if getattr(t, "sector", None):
            row["SECTOR"] = str(t.sector).replace(",", " ")
        if getattr(t, "industry", None):
            row["INDUSTRY"] = str(t.industry).replace(",", " ")
    _write_csv(summary_path, SUMMARY_FIELDS, summary_rows)
    _write_csv(watch_path, WATCH_FIELDS, [watch_to_dict(r) for r in watches])
    rejected_dicts = [rejected_fill_to_dict(r) for r in rejected_list]
    _write_csv(rejected_path, REJECTED_FILL_FIELDS, rejected_dicts)
    n_other = sum(1 for r in rejected_list if r.reject_reason not in ("TOO_LOW", "TOO_HIGH"))
    write_rejected_fills_html(
        rejected_html_path,
        rejected_dicts,
        stamp=stamp,
        n_too_low=int(meta.get("n_rejected_too_low") or 0),
        n_too_high=int(meta.get("n_rejected_too_high") or 0),
        n_other=n_other,
    )
    write_report(report_txt_path, cfg, meta)

    host_equity_written = False
    sizing_cfg = HostSizingConfig(
        brt_cash=float(cfg.cash),
        initial_capital=float(cfg.initial_capital),
        aggressive_max_multiple=float(cfg.aggressive_max_multiple),
        margin_utilization=float(cfg.margin_utilization),
        max_positions=int(cfg.max_positions),
        aggressive=bool(cfg.aggressive),
        aggressive_margin_interest=float(cfg.aggressive_margin_interest),
        aggressive_avg_positions=float(cfg.aggressive_avg_positions),
        aggressive_sizing_equity_cap=float(cfg.aggressive_sizing_equity_cap),
    )
    if tickers and (cfg.aggressive or bool(meta.get("use_host_equity"))):
        equity = compute_and_write_host_equity(
            output_dir=output_dir,
            ts=stamp,
            file_prefix=FILE_PREFIX,
            closed=closed,
            open_trades=opens,
            tickers=tickers,
            cfg=sizing_cfg,
        )
        if equity:
            host_equity_written = True
            md = equity.get("Max_Drawdown", "")
            meta["max_dd_pct"] = md
            try:
                meta["max_dd_fraction"] = f"{float(str(md).replace('%', '').strip()) / 100.0:.6f}"
            except (TypeError, ValueError):
                meta["max_dd_fraction"] = ""
            if equity.get("_aggressive"):
                meta["aggressive_total_pnl"] = f"{float(equity.get('_equity_total_pnl', 0) or 0):.2f}"
                meta["aggressive_max_dd"] = equity.get("Aggressive_Max_Drawdown", "")
                meta["aggressive_avg_positions"] = equity.get("Aggressive_Avg_Positions", 0)
                meta["aggressive_days_at_or_below_avg"] = equity.get("Aggressive_Days_AtOrBelow_Avg", 0)
                meta["aggressive_days_in_margin"] = equity.get("Aggressive_Days_In_Margin", 0)
                meta["aggressive_days_trimmed_over_2xavg"] = equity.get(
                    "Aggressive_Days_Trimmed_Over_2xAvg", 0
                )
            agg_path = output_dir / f"{FILE_PREFIX}_EquityCurve_Aggressive_{stamp}.csv"
            if agg_path.exists():
                paths["equity_aggressive"] = agg_path

    if not host_equity_written:
        max_dd, max_dd_pct = write_equity_curve_from_closed(
            equity_path, equity_meta_path, closed, initial_cash=float(cfg.cash)
        )
        meta["max_dd_fraction"] = f"{max_dd:.6f}"
        meta["max_dd_pct"] = f"{max_dd_pct:.2f}"

    metrics = compute_metrics(brt_closed, report_cfg)
    if meta.get("host_max_positions") is not None:
        metrics["Max_Positions"] = int(meta["host_max_positions"])
    if meta.get("max_dd_pct") not in (None, ""):
        metrics["Max_Drawdown"] = meta.get("max_dd_pct")
    if meta.get("aggressive_total_pnl") not in (None, ""):
        metrics["Aggressive_Total_PNL"] = meta.get("aggressive_total_pnl")
    if meta.get("aggressive_max_dd") not in (None, ""):
        metrics["Aggressive_Max_Drawdown"] = meta.get("aggressive_max_dd")
    if meta.get("aggressive_avg_positions") not in (None, ""):
        metrics["Aggressive_Avg_Positions"] = meta.get("aggressive_avg_positions")
    if meta.get("aggressive_days_at_or_below_avg") not in (None, ""):
        metrics["Aggressive_Days_AtOrBelow_Avg"] = meta.get("aggressive_days_at_or_below_avg")
    if meta.get("aggressive_days_in_margin") not in (None, ""):
        metrics["Aggressive_Days_In_Margin"] = meta.get("aggressive_days_in_margin")
    if meta.get("aggressive_days_trimmed_over_2xavg") not in (None, ""):
        metrics["Aggressive_Days_Trimmed_Over_2xAvg"] = meta.get(
            "aggressive_days_trimmed_over_2xavg"
        )
    if meta.get("n_signals") is not None:
        metrics["sb_signals_total"] = int(meta.get("n_signals") or 0)
    if meta.get("n_rejected_risk") is not None:
        metrics["sb_rejected_fills_total"] = int(meta.get("n_rejected_risk") or 0)
    if meta.get("n_rejected_too_low") is not None:
        metrics["sb_rejected_too_low"] = int(meta.get("n_rejected_too_low") or 0)
    if meta.get("n_rejected_too_high") is not None:
        metrics["sb_rejected_too_high"] = int(meta.get("n_rejected_too_high") or 0)
    if meta.get("n_rejected_mm") is not None:
        metrics["sb_rejected_mm"] = int(meta.get("n_rejected_mm") or 0)
    if meta.get("n_rejected_t1_n") is not None:
        metrics["sb_rejected_t1_n"] = int(meta.get("n_rejected_t1_n") or 0)
    if meta.get("n_rejected_vol_vs_avg") is not None:
        metrics["sb_rejected_vol_vs_avg"] = int(meta.get("n_rejected_vol_vs_avg") or 0)

    write_brt_report(
        report_cfg,
        metrics,
        str(output_dir),
        stamp,
        drive_link=drive_link,
        file_prefix=FILE_PREFIX,
    )
    write_audit_report(
        audit_path,
        stamp,
        cfg,
        meta,
        drive_link=drive_link,
        host_cfg=report_cfg,
        brt_closed=brt_closed,
    )

    # Correlation sweeps numeric Closed cols after burst DNA splice (PCT_DAY, DCR,
    # RANGE_EXP, VOL_RATIO, SIGNAL_LOW, RISK_PCT) plus OHLC peers (ATR_PCT_AT_TRIGGER, …).
    # SIGNAL_DATE stays on Closed but is excluded from corr predictors (date stamp).
    try:
        _sa = Path(__file__).resolve().parent
        if str(_sa) not in sys.path:
            sys.path.insert(0, str(_sa))
        from correlate_brt_closed import run_correlation_report

        run_correlation_report(str(closed_path), str(corr_path))
        if corr_path.exists():
            paths["correlation"] = corr_path
        pairs = output_dir / f"{FILE_PREFIX}_Correlation_Pairs_{stamp}.csv"
        if pairs.exists():
            paths["correlation_pairs"] = pairs
    except Exception as e:
        print(f"[SB] Correlation skipped: {e}", flush=True)

    try:
        _sa = Path(__file__).resolve().parent
        if str(_sa) not in sys.path:
            sys.path.insert(0, str(_sa))
        try:
            from rocket_post_analysis import write_analysis_artifacts
        except ImportError:
            from stock_analysis.rocket_post_analysis import write_analysis_artifacts  # type: ignore
        write_analysis_artifacts(
            cfg=report_cfg,
            tickers=tickers or {},
            output_dir=output_dir,
            ts=stamp,
            closed_path=closed_path,
            summary_path=summary_path,
            open_path=open_path,
            prefix=FILE_PREFIX,
            no_yfinance=bool(no_yfinance),
        )
    except Exception as e:
        print(f"[SB] analysis artifacts skipped: {e}", flush=True)

    for label, src in (
        ("Closed", closed_path),
        ("Open", open_path),
        ("Summary", summary_path),
        ("Watchlist", watch_path),
        ("RejectedFills", rejected_path),
        ("Audit_Report", audit_path),
        ("EquityCurve", equity_path),
    ):
        if not src.exists():
            continue
        dst = output_dir / f"{FILE_PREFIX}_LatestRun_{label}.csv"
        dst.write_bytes(src.read_bytes())
        paths[f"latest_{label.lower()}"] = dst

    latest_rej_html = output_dir / f"{FILE_PREFIX}_LatestRun_RejectedFills.html"
    if rejected_html_path.exists():
        latest_rej_html.write_bytes(rejected_html_path.read_bytes())
        paths["latest_rejectedfills_html"] = latest_rej_html

    paths.update(
        {
            "closed": closed_path,
            "open": open_path,
            "summary": summary_path,
            "watchlist": watch_path,
            "rejected_fills": rejected_path,
            "rejected_fills_html": rejected_html_path,
            "report": report_txt_path,
            "audit": audit_path,
            "equity_curve": equity_path,
            "equity_meta": equity_meta_path,
        }
    )
    (output_dir / f"{FILE_PREFIX}_last_run_ts.txt").write_text(stamp + "\n", encoding="utf-8")
    (output_dir / "last_run_ts.txt").write_text(stamp, encoding="utf-8")
    return paths


def run_sb_from_brt_main(
    *,
    cfg: Any,
    tickers: dict[str, pd.DataFrame],
    ticker_list: list[str],
    output_dir: Path,
    ts: str,
    data_dir: Path,
    load_symbol_fn: Any,
    workers: int = 0,
    drive_link: str = "",
    no_yfinance: bool = False,
) -> int:
    """TBN host entry (``sb_mode=true``) — burst DNA + BRT writers / unified Audit."""
    del workers  # sequential burst path v1
    bcfg = burst_config_from_brt(cfg)
    if bcfg.burst_fill != "next_open":
        print(f"[SB] WARNING: burst_fill={bcfg.burst_fill} not implemented; using next_open", flush=True)
        bcfg = replace(bcfg, burst_fill="next_open")

    print(
        f"[SB] StockBee Momentum Burst on {len(ticker_list)} symbols "
        f"(min_pct={bcfg.burst_min_pct}, max_risk={bcfg.burst_max_risk_pct}, "
        f"target={bcfg.target_pct}, time={bcfg.burst_time_stop_days}, no_ft={bcfg.burst_no_ft_days}, "
        f"mm_gate={bcfg.burst_mm_gate}, t1_n={bcfg.burst_require_t1_narrow_or_down}, "
        f"vol_vs_avg={bcfg.burst_vol_vs_avg_mult})",
        flush=True,
    )
    print("[SB] Exit priority: STOP/GAP -> TARGET -> NO_FT -> TIME (burst DNA; not BRT zones)", flush=True)

    mm_lookup = _load_mm_lookup_for_run(bcfg, Path(data_dir), Path(output_dir))

    symbols: list[str] = []
    loaded: dict[str, pd.DataFrame] = {}
    for sym in ticker_list:
        df = tickers.get(sym) if tickers else None
        if df is None or (hasattr(df, "empty") and df.empty):
            if load_symbol_fn is not None:
                try:
                    df = load_symbol_fn(sym, data_dir)
                except Exception as e:
                    print(f"[SB] skip {sym}: load failed ({e})", flush=True)
                    continue
        if df is None or len(df) < bcfg.burst_range_lookback + 3:
            print(f"[SB] skip {sym}: insufficient bars ({0 if df is None else len(df)})", flush=True)
            continue
        if df[["Open", "High", "Low", "Close"]].isna().any().any():
            print(f"[SB] skip {sym}: NaN in OHLC", flush=True)
            continue
        symbols.append(sym)
        loaded[sym] = df

    closed: list[BurstClosedRow] = []
    opens: list[BurstOpenRow] = []
    watches: list[BurstWatchRow] = []
    rejected: list[BurstRejectedFillRow] = []
    first_dates: dict[str, str] = {}
    n_signals = 0
    n_rejected = 0
    n_rejected_too_low = 0
    n_rejected_too_high = 0
    n_rejected_atr = 0
    n_rejected_dist52 = 0
    n_rejected_mm = 0
    n_rejected_t1_n = 0
    n_rejected_vol_vs_avg = 0
    for sym in symbols:
        df = loaded[sym]
        first = _iso(df.index[0])
        if len(first) == 8:
            first = f"{first[:4]}-{first[4:6]}-{first[6:]}"
        first_dates[sym] = first
        result = run_symbol_burst(sym, df, bcfg, mm_ratio_by_ymd=mm_lookup)
        closed.extend(result.closed)
        if result.open_row:
            opens.append(result.open_row)
        if result.watch_row:
            watches.append(result.watch_row)
        rejected.extend(result.rejected_fills)
        n_signals += result.signals
        n_rejected += result.rejected_risk
        n_rejected_too_low += result.rejected_too_low
        n_rejected_too_high += result.rejected_too_high
        n_rejected_atr += result.rejected_atr
        n_rejected_dist52 += result.rejected_dist52
        n_rejected_mm += result.rejected_mm
        n_rejected_t1_n += result.rejected_t1_n
        n_rejected_vol_vs_avg += result.rejected_vol_vs_avg
    closed.sort(key=lambda r: (r.symbol, r.date_opened, r.date_closed))
    opens.sort(key=lambda r: r.symbol)
    watches.sort(key=lambda r: r.symbol)
    rejected.sort(key=lambda r: (r.symbol, r.signal_date, r.fill_date))
    exit_mix: dict[str, int] = {}
    for r in closed:
        exit_mix[r.exit_type] = exit_mix.get(r.exit_type, 0) + 1
    wins = sum(1 for r in closed if r.pnl_pct > 0)
    meta: dict[str, Any] = {
        "symbols_requested": list(ticker_list),
        "symbols_run": symbols,
        "symbols_skipped": [s for s in ticker_list if s not in symbols],
        "skip_detail": [],
        "n_closed": len(closed),
        "n_open": len(opens),
        "n_signals": n_signals,
        "n_rejected_risk": n_rejected,
        "n_rejected_too_low": n_rejected_too_low,
        "n_rejected_too_high": n_rejected_too_high,
        "n_rejected_atr": n_rejected_atr,
        "n_rejected_dist52": n_rejected_dist52,
        "n_rejected_mm": n_rejected_mm,
        "n_rejected_t1_n": n_rejected_t1_n,
        "n_rejected_vol_vs_avg": n_rejected_vol_vs_avg,
        "total_pnl": sum(r.pnl_dollars for r in closed),
        "win_rate": (100.0 * wins / len(closed)) if closed else 0.0,
        "avg_pnl_pct": float(np.mean([r.pnl_pct for r in closed])) if closed else 0.0,
        "avg_days_held": float(np.mean([r.days_held for r in closed])) if closed else 0.0,
        "exit_mix": exit_mix,
        "first_dates": first_dates,
        "use_host_equity": True,
    }

    host_meta: dict[str, Any] = {}
    hcfg = HostSizingConfig(
        brt_cash=float(bcfg.cash),
        initial_capital=float(bcfg.initial_capital),
        aggressive_max_multiple=float(bcfg.aggressive_max_multiple),
        margin_utilization=float(bcfg.margin_utilization),
        max_positions=int(bcfg.max_positions),
        aggressive=bool(bcfg.aggressive),
        aggressive_margin_interest=float(bcfg.aggressive_margin_interest),
        aggressive_avg_positions=float(bcfg.aggressive_avg_positions),
        aggressive_sizing_equity_cap=float(bcfg.aggressive_sizing_equity_cap),
    )
    if bcfg.host_dollar_scale and not bcfg.burst_size_from_stop and closed:
        adj, scale, max_pos = apply_host_dollar_scale(closed, opens, hcfg)
        bcfg = replace(bcfg, cash=adj)
        meta["total_pnl"] = sum(r.pnl_dollars for r in closed)
        meta["host_max_positions"] = max_pos
        meta["host_brt_cash"] = adj
        meta["host_pnl_scale"] = scale
        meta["host_audit_brt_cash"] = audit_display_brt_cash(max_pos)
        audit_cash = float(meta["host_audit_brt_cash"])
        audit_pnl = meta["total_pnl"] * (audit_cash / adj) if adj > 0 else meta["total_pnl"]
        meta["total_pnl_audit_1m"] = f"{audit_pnl:.2f}"
        host_meta = {
            "host_max_positions": max_pos,
            "host_brt_cash": adj,
            "host_pnl_scale": scale,
            "host_audit_brt_cash": meta["host_audit_brt_cash"],
            "total_pnl_audit_1m": meta["total_pnl_audit_1m"],
        }
        try:
            cfg = replace(cfg, brt_cash=adj, max_positions=max_pos, sb_mode=True)
        except TypeError:
            pass
        print(
            f"[SB] Host dollar-scale: PNL_DOLLARS × {scale:.6g}; "
            f"brt_cash -> {adj:,.0f} (deployable/Max_Positions={max_pos}; "
            f"audit_label 1M/mp={audit_cash:,.0f})",
            flush=True,
        )
    elif bcfg.burst_size_from_stop:
        print("[SB] size-from-stop ON — skipping host dollar-scale (Seed-opt risk path)", flush=True)

    paths = write_outputs(
        Path(output_dir),
        ts,
        bcfg,
        closed,
        opens,
        watches,
        meta,
        tickers=loaded,
        rejected_fills=rejected,
        host_cfg=cfg,
        no_yfinance=bool(no_yfinance),
        drive_link=drive_link,
        data_dir=Path(data_dir) if data_dir is not None else None,
    )
    print(
        f"[SB] Closed: {paths['closed']} ({len(closed)} trades, "
        f"{wins}W/{len(closed) - wins}L, PnL=${meta['total_pnl']:.2f})",
        flush=True,
    )
    print(f"[SB] Open: {paths['open']} ({len(opens)} positions)", flush=True)
    print(f"[SB] Summary: {paths['summary']}", flush=True)
    print(
        f"[SB] RejectedFills: {paths['rejected_fills']} "
        f"(total={meta['n_rejected_risk']} too_low={meta['n_rejected_too_low']} "
        f"too_high={meta['n_rejected_too_high']})",
        flush=True,
    )
    print(f"[SB] Audit: {paths['audit']}", flush=True)
    agg = Path(output_dir) / f"{FILE_PREFIX}_EquityCurve_Aggressive_{ts}.csv"
    if agg.exists():
        print(f"[SB] Equity Aggressive: {agg}", flush=True)
    if host_meta:
        print(f"[SB] Host sizing Max_Positions={host_meta.get('host_max_positions')}", flush=True)
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    cfg = cfg_from_args(args)
    if cfg.burst_fill != "next_open":
        print(f"[SB] WARNING: burst_fill={cfg.burst_fill} not implemented; using next_open", flush=True)
        cfg = replace(cfg, burst_fill="next_open")

    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    symbols = resolve_run_symbols(args.symbols, data_dir)
    stamp = (args.stamp or "").strip() or datetime.now().strftime("%y%m%d%H%M%S")
    if not symbols:
        print(f"[SB] ERROR: no symbols resolved under {data_dir}", flush=True)
        return 1
    universe_mode = "whitelist" if parse_symbols(args.symbols) else "full CSV universe"

    print(
        f"[SB] StockBee Burst run: {len(symbols)} symbols ({universe_mode}) "
        f"-> {output_dir} stamp={stamp} "
        f"mm_gate={cfg.burst_mm_gate} t1_n={cfg.burst_require_t1_narrow_or_down} "
        f"vol_vs_avg={cfg.burst_vol_vs_avg_mult}",
        flush=True,
    )
    closed, opens, watches, rejected, meta, tickers = run_backtest(
        symbols, data_dir, cfg, output_dir=output_dir
    )

    # Host dollar-scale (YH/BRT/RS Closed parity). Skip when size-from-stop research path.
    if cfg.host_dollar_scale and not cfg.burst_size_from_stop and closed:
        host_cfg = HostSizingConfig(
            brt_cash=float(cfg.cash),
            initial_capital=float(cfg.initial_capital),
            aggressive_max_multiple=float(cfg.aggressive_max_multiple),
            margin_utilization=float(cfg.margin_utilization),
            max_positions=int(cfg.max_positions),
            aggressive=bool(cfg.aggressive),
        )
        adj, scale, max_pos = apply_host_dollar_scale(closed, opens, host_cfg)
        cfg = replace(cfg, cash=adj)
        meta["total_pnl"] = sum(r.pnl_dollars for r in closed)
        meta["host_max_positions"] = max_pos
        meta["host_brt_cash"] = adj
        meta["host_pnl_scale"] = scale
        meta["host_audit_brt_cash"] = audit_display_brt_cash(max_pos)
        # Same Audit-row rescale as rocket_tbn write_brt_audit_report (1M / max_pos vs Closed cash)
        audit_cash = float(meta["host_audit_brt_cash"])
        audit_pnl = meta["total_pnl"] * (audit_cash / adj) if adj > 0 else meta["total_pnl"]
        meta["total_pnl_audit_1m"] = f"{audit_pnl:.2f}"
        print(
            f"[SB] Host dollar-scale: PNL_DOLLARS × {scale:.6g}; "
            f"brt_cash -> {adj:,.0f} (deployable/Max_Positions={max_pos}; "
            f"audit_label 1M/mp={audit_cash:,.0f})",
            flush=True,
        )
    elif cfg.burst_size_from_stop:
        print("[SB] size-from-stop ON — skipping host dollar-scale (Seed-opt risk path)", flush=True)

    paths = write_outputs(
        output_dir,
        stamp,
        cfg,
        closed,
        opens,
        watches,
        meta,
        tickers=tickers,
        rejected_fills=rejected,
        data_dir=data_dir,
    )

    print(
        f"[SB] Done. closed={meta['n_closed']} open={meta['n_open']} "
        f"signals={meta['n_signals']} rejected_risk={meta['n_rejected_risk']} "
        f"too_low={meta.get('n_rejected_too_low')} too_high={meta.get('n_rejected_too_high')} "
        f"skipped={len(meta['symbols_skipped'])} "
        f"PnL=${meta['total_pnl']:.2f} WR={meta['win_rate']:.1f}%",
        flush=True,
    )
    for s in meta["skip_detail"]:
        print(f"[SB] SKIP {s}", flush=True)
    print(f"[SB] Closed: {paths['closed']}", flush=True)
    print(f"[SB] Summary: {paths['summary']}", flush=True)
    print(f"[SB] Audit: {paths['audit']}", flush=True)
    print(f"[SB] Equity: {paths['equity_curve']}", flush=True)
    if paths.get("equity_aggressive"):
        print(f"[SB] Equity Aggressive: {paths['equity_aggressive']}", flush=True)
    print(f"[SB] Report: {paths['report']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
