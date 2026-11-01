#!/usr/bin/env python3
"""
Kristjan Kullamägi (Qullamaggie) — Episodic Pivot (EP) & High Tight Flag (HTF).

Standalone seed engine (prefix QULL_). Does **not** require rocket_tbn.py / qull_mode.
Docs: drive/paul_experiments/tbn_new_systems/qull_ep_htf/

HTF (default):
  - Prior run >= qull_prior_run_pct over qull_prior_run_bars before coil
  - Coil of qull_coil_bars with range <= qull_coil_range_pct
  - Soft: higher lows, EMA10 surf, coil volume dry-up
  - Breakout: Close > coil high + volume >= qull_bo_vol_mult * SMA20
  - Market: SPY SMA10 > SMA20 (lag-1), optional
  - Fill: next open; stop: breakout LOD (ADR-capped); trail: close < EMA10/20

EP (default OFF): gap + volume + neglect proxy; EP_CATALYST soft-fills from yfinance
earnings-date cache when within ±N trading days of the gap.
"""
from __future__ import annotations

import argparse
import csv
import shutil
import sys
from dataclasses import dataclass
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
    )
except ImportError:
    from stock_analysis.tbn_host_sizing import (  # type: ignore
        DEFAULT_AGGRESSIVE_MAX_MULTIPLE,
        DEFAULT_INITIAL_CAPITAL,
        DEFAULT_MARGIN_UTILIZATION,
        HostSizingConfig,
        apply_host_dollar_scale,
        audit_display_brt_cash,
    )

try:
    from ohlcv_store import list_csv_symbols as _list_csv_symbols
except ImportError:
    try:
        from stock_analysis.ohlcv_store import list_csv_symbols as _list_csv_symbols  # type: ignore
    except ImportError:
        _list_csv_symbols = None  # type: ignore

try:
    from fundamentals_yfinance import (
        classify_ep_catalyst,
        ensure_symbols as _fund_ensure_symbols,
    )
except ImportError:
    try:
        from stock_analysis.fundamentals_yfinance import (  # type: ignore
            classify_ep_catalyst,
            ensure_symbols as _fund_ensure_symbols,
        )
    except ImportError:
        classify_ep_catalyst = None  # type: ignore
        _fund_ensure_symbols = None  # type: ignore

FILE_PREFIX = "QULL"
DEFAULT_CASH = 47_500.0
DEFAULT_SEED_SYMBOLS = (
    "TSLA,NVDA,AMD,NET,SNOW,CRWD,SHOP,ROKU,DKNG,PLTR,SMCI,ARM,HOOD,MSTR"
)
DAYS_PER_YEAR = 365.25


def _as_bool(x: Any) -> bool:
    if isinstance(x, bool):
        return x
    return str(x).strip().lower() in ("1", "true", "yes", "on")


def _iso(d: Any) -> str:
    if hasattr(d, "strftime"):
        return d.strftime("%Y%m%d")
    s = str(d)[:10].replace("-", "")
    return s


def _ema(arr: np.ndarray, span: int) -> np.ndarray:
    return pd.Series(arr).ewm(span=span, adjust=False, min_periods=span).mean().to_numpy()


def _sma(arr: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(arr).rolling(n, min_periods=n).mean().to_numpy()


@dataclass
class QullConfig:
    qull_setup: str = "htf"  # htf | ep | both
    qull_prior_run_pct: float = 0.50
    qull_prior_run_bars: int = 42
    qull_coil_bars: int = 10
    qull_coil_range_pct: float = 0.15
    # Soft geometry gates default OFF (too sparse with simple half-window HL / vol-dry);
    # enable via CLI/AB. EMA surf stays ON as Qulla identity.
    qull_require_higher_lows: bool = False
    qull_require_ema_surf: bool = True
    qull_ema_surf_pct: float = 0.04
    qull_coil_vol_dry: bool = False
    qull_vol_dry_ratio: float = 0.85
    qull_bo_vol_mult: float = 1.5
    qull_min_price: float = 3.0
    qull_min_adv_usd: float = 2_000_000.0
    qull_adv_lookback: int = 20
    qull_market_filter: bool = True
    qull_stop_mode: str = "breakout_lod"  # breakout_lod | coil_low
    qull_max_stop_adr_mult: float = 1.0  # 0 = off
    qull_trail_ema: int = 10
    qull_partial_frac: float = 0.0
    qull_partial_days: int = 4
    qull_target_pct: float = 0.0  # multiplier; 0 = off
    qull_time_stop_days: int = 0
    qull_fill: str = "next_open"
    qull_ep_gap_pct: float = 0.10
    qull_ep_vol_mult: float = 3.0
    qull_ep_flat_max_run_pct: float = 0.30
    qull_ep_flat_bars: int = 63
    qull_ep_catalyst_window: int = 5
    qull_ep_min_surprise: float = 0.0
    qull_fundamentals_fill: bool = True
    cash: float = DEFAULT_CASH
    initial_capital: float = DEFAULT_INITIAL_CAPITAL
    aggressive_max_multiple: float = DEFAULT_AGGRESSIVE_MAX_MULTIPLE
    margin_utilization: float = DEFAULT_MARGIN_UTILIZATION
    max_positions: int = 0
    aggressive: bool = False
    aggressive_margin_interest: float = 0.10
    aggressive_avg_positions: float = 0.0
    aggressive_sizing_equity_cap: float = 10.0
    host_dollar_scale: bool = True
    entry_start_date: str = ""
    entry_end_date: str = ""


@dataclass
class QullClosedRow:
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
    trigger_date: str
    trigger_close: float
    setup: str
    prior_run_pct: float
    coil_bars: int
    coil_range_pct: float
    coil_high: float
    coil_low: float
    ema10: float
    ema20: float
    ema_surf_pct: float
    vol_ratio_bo: float
    adr_pct: float
    stop_adr_mult: float
    trail_ema: int
    market_10gt20: int
    ep_gap_pct: float
    ep_catalyst: str
    one_liner: str

    def to_csv_row(self) -> list[str]:
        return [
            self.symbol,
            self.side,
            self.date_opened,
            f"{self.entry_price:.4f}",
            f"{self.stop_price:.4f}",
            f"{self.target_price:.4f}" if self.target_price > 0 else "",
            self.date_closed,
            f"{self.exit_price:.4f}",
            self.exit_type,
            str(self.days_held),
            f"{self.pnl_pct:.4f}",
            f"{self.pnl_dollars:.2f}",
            f"{self.ann_ror_pct:.2f}",
            f"{self.max_price:.4f}",
            self.trigger_date,
            f"{self.trigger_close:.4f}",
            self.setup,
            f"{self.prior_run_pct:.4f}",
            str(self.coil_bars),
            f"{self.coil_range_pct:.4f}",
            f"{self.coil_high:.4f}",
            f"{self.coil_low:.4f}",
            f"{self.ema10:.4f}",
            f"{self.ema20:.4f}",
            f"{self.ema_surf_pct:.4f}",
            f"{self.vol_ratio_bo:.4f}",
            f"{self.adr_pct:.4f}",
            f"{self.stop_adr_mult:.4f}",
            str(self.trail_ema),
            str(self.market_10gt20),
            f"{self.ep_gap_pct:.4f}" if self.setup == "EP" else "",
            self.ep_catalyst if self.setup == "EP" else "",
            self.one_liner,
        ]


CLOSED_HEADER = [
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
    "TRIGGER_DATE",
    "TRIGGER_CLOSE",
    "SETUP",
    "PRIOR_RUN_PCT",
    "COIL_BARS",
    "COIL_RANGE_PCT",
    "COIL_HIGH",
    "COIL_LOW",
    "EMA10",
    "EMA20",
    "EMA_SURF_PCT",
    "VOL_RATIO_BO",
    "ADR_PCT",
    "STOP_ADR_MULT",
    "TRAIL_EMA",
    "MARKET_10GT20",
    "EP_GAP_PCT",
    "EP_CATALYST",
    "ONE_LINER",
]

OPEN_HEADER = [
    "SYMBOL",
    "DATE_OPENED",
    "ENTRY_PRICE",
    "CURRENT_PRICE",
    "PNL_PCT",
    "DAYS_OPEN",
    "STOP_LOSS",
    "TARGET",
    "SETUP",
    "COIL_HIGH",
    "TRAIL_EMA",
]

WATCH_HEADER = [
    "SYMBOL",
    "ASOF_DATE",
    "SETUP",
    "COIL_HIGH",
    "CLOSE",
    "DIST_TO_COIL_PCT",
    "PRIOR_RUN_PCT",
    "COIL_RANGE_PCT",
    "NOTES",
]


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
    df = df.set_index("Date")
    out = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    for c in out.columns:
        out[c] = out[c].astype(float)
    return out


def prepare_bars(df: pd.DataFrame) -> dict[str, Any]:
    df = df.sort_index()
    dates = [_iso(d) for d in df.index]
    o = df["Open"].astype(float).to_numpy()
    h = df["High"].astype(float).to_numpy()
    l = df["Low"].astype(float).to_numpy()
    c = df["Close"].astype(float).to_numpy()
    vol = df["Volume"].astype(float).to_numpy()
    ema10 = _ema(c, 10)
    ema20 = _ema(c, 20)
    vol_sma20 = _sma(vol, 20)
    rng_pct = np.where(c > 0, (h - l) / c, np.nan)
    adr20 = pd.Series(rng_pct).rolling(20, min_periods=20).mean().to_numpy()
    return {
        "dates": dates,
        "o": o,
        "h": h,
        "l": l,
        "c": c,
        "vol": vol,
        "ema10": ema10,
        "ema20": ema20,
        "vol_sma20": vol_sma20,
        "adr20": adr20,
        "n": len(dates),
    }


def _entry_date_allowed(iso: str, start: str, end: str) -> bool:
    s = (start or "").strip().replace("-", "")[:8]
    e = (end or "").strip().replace("-", "")[:8]
    if s and iso < s:
        return False
    if e and iso > e:
        return False
    return True


def _calendar_days(d1: str, d2: str) -> int:
    a = datetime.strptime(d1[:8], "%Y%m%d")
    b = datetime.strptime(d2[:8], "%Y%m%d")
    return max(0, (b - a).days)


def _ann_ror(pnl_pct: float, days_held: int) -> float:
    if days_held <= 0:
        return 0.0
    return ((1.0 + pnl_pct) ** (DAYS_PER_YEAR / days_held) - 1.0) * 100.0


def _adv_usd(bars: dict[str, Any], i: int, lookback: int) -> float:
    lo = max(0, i - lookback)
    if i <= lo:
        return 0.0
    dollar = bars["c"][lo:i] * bars["vol"][lo:i]
    return float(np.mean(dollar)) if len(dollar) else 0.0


def _market_ok(spy_ok_by_date: Optional[dict[str, bool]], date_iso: str, enabled: bool) -> bool:
    if not enabled:
        return True
    if spy_ok_by_date is None:
        return True
    # lag-1: use prior available date key if exact missing
    if date_iso in spy_ok_by_date:
        return bool(spy_ok_by_date[date_iso])
    # find latest prior
    keys = [k for k in spy_ok_by_date if k < date_iso]
    if not keys:
        return True
    return bool(spy_ok_by_date[max(keys)])


def build_spy_market_map(data_dir: Path) -> Optional[dict[str, bool]]:
    path = Path(data_dir) / "SPY.csv"
    if not path.exists():
        return None
    try:
        df = load_ohlcv_csv(path)
    except Exception:
        return None
    bars = prepare_bars(df)
    sma10 = _sma(bars["c"], 10)
    sma20 = _sma(bars["c"], 20)
    out: dict[str, bool] = {}
    for i, d in enumerate(bars["dates"]):
        if i < 1:
            continue
        a, b = sma10[i - 1], sma20[i - 1]
        if np.isfinite(a) and np.isfinite(b):
            out[d] = bool(a > b)
    return out


def detect_htf_signal(
    bars: dict[str, Any],
    i: int,
    cfg: QullConfig,
) -> Optional[dict[str, Any]]:
    coil_n = int(cfg.qull_coil_bars)
    prior_n = int(cfg.qull_prior_run_bars)
    need = prior_n + coil_n + 25
    if i < need or i >= bars["n"]:
        return None
    c = bars["c"]
    h = bars["h"]
    l = bars["l"]
    vol = bars["vol"]
    if float(c[i]) < float(cfg.qull_min_price):
        return None

    coil_end = i - 1
    coil_start = coil_end - coil_n + 1
    if coil_start < prior_n:
        return None
    prior_start = coil_start - prior_n
    prior_end = coil_start  # exclusive

    prior_h = h[prior_start:prior_end]
    prior_l = l[prior_start:prior_end]
    if len(prior_h) < prior_n:
        return None
    pmin = float(np.min(prior_l))
    pmax = float(np.max(prior_h))
    if pmin <= 0:
        return None
    prior_run = pmax / pmin - 1.0
    if prior_run < float(cfg.qull_prior_run_pct):
        return None

    coil_h = h[coil_start : coil_end + 1]
    coil_l = l[coil_start : coil_end + 1]
    coil_c = c[coil_start : coil_end + 1]
    coil_v = vol[coil_start : coil_end + 1]
    coil_high = float(np.max(coil_h))
    coil_low = float(np.min(coil_l))
    if coil_low <= 0:
        return None
    coil_range = (coil_high - coil_low) / coil_low
    if coil_range > float(cfg.qull_coil_range_pct) + 1e-12:
        return None

    if cfg.qull_require_higher_lows and coil_n >= 4:
        mid = coil_n // 2
        first_low = float(np.min(coil_l[:mid]))
        second_low = float(np.min(coil_l[mid:]))
        if second_low + 1e-12 < first_low:
            return None

    ema10 = bars["ema10"][coil_end]
    ema20 = bars["ema20"][coil_end]
    if not (np.isfinite(ema10) and ema10 > 0):
        return None
    if not (np.isfinite(ema20) and ema20 > ema10 * 0.0):
        # still require rising-ish: ema10 >= ema20 * 0.98 soft
        pass
    ema_rising = np.isfinite(bars["ema10"][coil_end - 1]) and ema10 >= bars["ema10"][coil_end - 1]
    surf = abs(float(coil_c[-1]) - float(ema10)) / float(ema10)
    if cfg.qull_require_ema_surf:
        if not ema_rising:
            return None
        if surf > float(cfg.qull_ema_surf_pct) + 1e-12:
            return None

    if cfg.qull_coil_vol_dry and prior_end > prior_start:
        prior_v = vol[prior_start:prior_end]
        if len(prior_v) and float(np.mean(prior_v)) > 0:
            if float(np.mean(coil_v)) > float(np.mean(prior_v)) * float(cfg.qull_vol_dry_ratio) + 1e-12:
                return None

    # Breakout on bar i
    if float(c[i]) <= coil_high:
        return None
    vsm = bars["vol_sma20"][i]
    if not (np.isfinite(vsm) and vsm > 0):
        return None
    vol_ratio = float(vol[i]) / float(vsm)
    if vol_ratio < float(cfg.qull_bo_vol_mult):
        return None

    if float(cfg.qull_min_adv_usd) > 0:
        adv = _adv_usd(bars, i, int(cfg.qull_adv_lookback))
        if adv < float(cfg.qull_min_adv_usd):
            return None

    adr = bars["adr20"][i]
    if not np.isfinite(adr) or adr <= 0:
        return None

    return {
        "setup": "HTF",
        "prior_run_pct": prior_run,
        "coil_bars": coil_n,
        "coil_range_pct": coil_range,
        "coil_high": coil_high,
        "coil_low": coil_low,
        "ema10": float(bars["ema10"][i]),
        "ema20": float(bars["ema20"][i]),
        "ema_surf_pct": surf,
        "vol_ratio_bo": vol_ratio,
        "adr_pct": float(adr) * 100.0,
        "ep_gap_pct": 0.0,
        "ep_catalyst": "",
        "signal_low": float(l[i]),
        "trigger_close": float(c[i]),
    }


def detect_ep_signal(
    bars: dict[str, Any],
    i: int,
    cfg: QullConfig,
) -> Optional[dict[str, Any]]:
    flat_n = int(cfg.qull_ep_flat_bars)
    if i < flat_n + 25:
        return None
    o = bars["o"]
    c = bars["c"]
    l = bars["l"]
    vol = bars["vol"]
    if float(c[i - 1]) <= 0 or float(o[i]) <= 0:
        return None
    if float(c[i]) < float(cfg.qull_min_price):
        return None
    gap = float(o[i]) / float(c[i - 1]) - 1.0
    if gap < float(cfg.qull_ep_gap_pct):
        return None
    vsm = bars["vol_sma20"][i]
    if not (np.isfinite(vsm) and vsm > 0):
        return None
    vol_ratio = float(vol[i]) / float(vsm)
    if vol_ratio < float(cfg.qull_ep_vol_mult):
        return None
    # Neglect: prior flat_n bars before gap day
    lo = i - flat_n
    hi = i
    pmin = float(np.min(l[lo:hi]))
    pmax = float(np.max(bars["h"][lo:hi]))
    if pmin <= 0:
        return None
    prior_run = pmax / pmin - 1.0
    if prior_run > float(cfg.qull_ep_flat_max_run_pct) + 1e-12:
        return None
    if float(cfg.qull_min_adv_usd) > 0:
        adv = _adv_usd(bars, i, int(cfg.qull_adv_lookback))
        if adv < float(cfg.qull_min_adv_usd):
            return None
    adr = bars["adr20"][i]
    if not np.isfinite(adr) or adr <= 0:
        return None
    return {
        "setup": "EP",
        "prior_run_pct": prior_run,
        "coil_bars": 0,
        "coil_range_pct": 0.0,
        "coil_high": float(o[i]),
        "coil_low": float(l[i]),
        "ema10": float(bars["ema10"][i]) if np.isfinite(bars["ema10"][i]) else 0.0,
        "ema20": float(bars["ema20"][i]) if np.isfinite(bars["ema20"][i]) else 0.0,
        "ema_surf_pct": 0.0,
        "vol_ratio_bo": vol_ratio,
        "adr_pct": float(adr) * 100.0,
        "ep_gap_pct": gap,
        "ep_catalyst": "UNKNOWN",
        "signal_low": float(l[i]),
        "trigger_close": float(c[i]),
    }


def _pnl_dollars(cfg: QullConfig, entry: float, exit_px: float) -> float:
    if entry <= 0:
        return 0.0
    return float(cfg.cash) * ((exit_px / entry) - 1.0)


def run_symbol_qull(
    symbol: str,
    df: pd.DataFrame,
    cfg: QullConfig,
    spy_ok_by_date: Optional[dict[str, bool]] = None,
) -> tuple[list[QullClosedRow], Optional[dict[str, Any]], Optional[dict[str, Any]], int]:
    bars = prepare_bars(df)
    n = bars["n"]
    setup_mode = str(cfg.qull_setup).strip().lower()
    do_htf = setup_mode in ("htf", "both", "all")
    do_ep = setup_mode in ("ep", "both", "all")
    trail_n = int(cfg.qull_trail_ema) if int(cfg.qull_trail_ema) in (10, 20) else 10
    trail = bars["ema10"] if trail_n == 10 else bars["ema20"]

    closed: list[QullClosedRow] = []
    open_row: Optional[dict[str, Any]] = None
    watch_row: Optional[dict[str, Any]] = None
    n_signals = 0

    in_pos = False
    entry_i = -1
    entry_px = 0.0
    stop_px = 0.0
    target_px = 0.0
    max_px = 0.0
    sig: dict[str, Any] = {}
    market_flag = 0
    partial_done = False

    i = 0
    while i < n:
        if not in_pos:
            cand: Optional[dict[str, Any]] = None
            if do_htf:
                cand = detect_htf_signal(bars, i, cfg)
            if cand is None and do_ep:
                cand = detect_ep_signal(bars, i, cfg)
            if cand is None:
                i += 1
                continue
            date_iso = bars["dates"][i]
            if not _entry_date_allowed(date_iso, cfg.entry_start_date, cfg.entry_end_date):
                i += 1
                continue
            if not _market_ok(spy_ok_by_date, date_iso, cfg.qull_market_filter):
                i += 1
                continue
            n_signals += 1
            # Fill next open
            if i + 1 >= n:
                watch_row = {
                    "symbol": symbol,
                    "asof_date": date_iso,
                    "setup": cand["setup"],
                    "coil_high": cand["coil_high"],
                    "close": cand["trigger_close"],
                    "dist_to_coil_pct": (cand["trigger_close"] / cand["coil_high"] - 1.0)
                    if cand["coil_high"] > 0
                    else 0.0,
                    "prior_run_pct": cand["prior_run_pct"],
                    "coil_range_pct": cand["coil_range_pct"],
                    "notes": "pending_next_open",
                }
                break
            fill_i = i + 1
            entry_px = float(bars["o"][fill_i])
            if entry_px <= 0:
                i += 1
                continue
            if str(cfg.qull_stop_mode).lower() == "coil_low":
                stop_px = float(cand["coil_low"])
            else:
                stop_px = float(cand["signal_low"])
            if stop_px >= entry_px:
                i = fill_i
                continue
            risk = (entry_px - stop_px) / entry_px
            adr_frac = float(bars["adr20"][i])
            stop_adr_mult = risk / adr_frac if adr_frac > 0 else 999.0
            if float(cfg.qull_max_stop_adr_mult) > 0 and stop_adr_mult > float(cfg.qull_max_stop_adr_mult) + 1e-12:
                i = fill_i
                continue
            target_px = entry_px * float(cfg.qull_target_pct) if float(cfg.qull_target_pct) > 1.0 else 0.0
            in_pos = True
            entry_i = fill_i
            max_px = entry_px
            sig = {**cand, "stop_adr_mult": stop_adr_mult, "trigger_date": date_iso}
            market_flag = 1 if _market_ok(spy_ok_by_date, date_iso, True) else 0
            partial_done = False
            i = fill_i
            continue

        # Manage open position from bar i
        hi = float(bars["h"][i])
        lo = float(bars["l"][i])
        cl = float(bars["c"][i])
        op = float(bars["o"][i])
        max_px = max(max_px, hi)
        exit_px = None
        exit_type = ""

        # Gap / intraday stop (BRT/PVH: open through stop → GAP_DOWN @open)
        if op > 0 and op <= stop_px:
            exit_px, exit_type = op, "GAP_DOWN"
        elif lo <= stop_px:
            exit_px, exit_type = stop_px, "STOP_LOSS"
        elif target_px > 0 and hi >= target_px:
            exit_px, exit_type = target_px, "TARGET"
        else:
            # Partial (simplified: book full-size reduction as separate closed row then continue)
            days_held = _calendar_days(bars["dates"][entry_i], bars["dates"][i])
            if (
                not partial_done
                and float(cfg.qull_partial_frac) > 0
                and days_held >= int(cfg.qull_partial_days)
                and cl > entry_px
            ):
                # Record partial as closed fraction via scaled cash — keep it simple: skip multi-lot;
                # move stop to breakeven instead (Qulla-style after partial).
                stop_px = max(stop_px, entry_px)
                partial_done = True
            tr = trail[i]
            if np.isfinite(tr) and cl < float(tr):
                exit_px, exit_type = cl, "TRAIL_EMA"
            elif int(cfg.qull_time_stop_days) > 0 and days_held >= int(cfg.qull_time_stop_days):
                exit_px, exit_type = cl, "TIME"

        if exit_px is not None:
            d_open = bars["dates"][entry_i]
            d_close = bars["dates"][i]
            days = max(1, _calendar_days(d_open, d_close))
            pnl_pct = exit_px / entry_px - 1.0
            row = QullClosedRow(
                symbol=symbol,
                side="LONG",
                date_opened=d_open,
                entry_price=entry_px,
                stop_price=stop_px,
                target_price=target_px,
                date_closed=d_close,
                exit_price=float(exit_px),
                exit_type=exit_type,
                days_held=days,
                pnl_pct=pnl_pct,
                pnl_dollars=_pnl_dollars(cfg, entry_px, float(exit_px)),
                ann_ror_pct=_ann_ror(pnl_pct, days),
                max_price=max_px,
                trigger_date=str(sig.get("trigger_date", d_open)),
                trigger_close=float(sig.get("trigger_close", entry_px)),
                setup=str(sig.get("setup", "HTF")),
                prior_run_pct=float(sig.get("prior_run_pct", 0.0)),
                coil_bars=int(sig.get("coil_bars", 0)),
                coil_range_pct=float(sig.get("coil_range_pct", 0.0)),
                coil_high=float(sig.get("coil_high", 0.0)),
                coil_low=float(sig.get("coil_low", 0.0)),
                ema10=float(sig.get("ema10", 0.0)),
                ema20=float(sig.get("ema20", 0.0)),
                ema_surf_pct=float(sig.get("ema_surf_pct", 0.0)),
                vol_ratio_bo=float(sig.get("vol_ratio_bo", 0.0)),
                adr_pct=float(sig.get("adr_pct", 0.0)),
                stop_adr_mult=float(sig.get("stop_adr_mult", 0.0)),
                trail_ema=trail_n,
                market_10gt20=market_flag,
                ep_gap_pct=float(sig.get("ep_gap_pct", 0.0)),
                ep_catalyst=str(sig.get("ep_catalyst", "")),
                one_liner=(
                    f"{sig.get('setup')} prior={float(sig.get('prior_run_pct', 0)):.0%} "
                    f"coil={sig.get('coil_bars')} trail=EMA{trail_n} exit={exit_type}"
                ),
            )
            closed.append(row)
            in_pos = False
            i += 1
            continue

        i += 1

    if in_pos:
        last = n - 1
        cl = float(bars["c"][last])
        d_open = bars["dates"][entry_i]
        days = max(1, _calendar_days(d_open, bars["dates"][last]))
        open_row = {
            "symbol": symbol,
            "date_opened": d_open,
            "entry_price": entry_px,
            "current_price": cl,
            "pnl_pct": cl / entry_px - 1.0,
            "days_open": days,
            "stop_loss": stop_px,
            "target": target_px,
            "setup": str(sig.get("setup", "HTF")),
            "coil_high": float(sig.get("coil_high", 0.0)),
            "trail_ema": trail_n,
        }

    # Near-coil watch if last bars tight under coil (HTF only, flat)
    if watch_row is None and do_htf and not in_pos and n > 30:
        j = n - 1
        probe = detect_htf_signal(bars, j, cfg)
        if probe is None:
            # soft: coil forming — report distance to recent 10d high
            coil_n = int(cfg.qull_coil_bars)
            if j >= coil_n:
                ch = float(np.max(bars["h"][j - coil_n + 1 : j + 1]))
                cl = float(bars["c"][j])
                if ch > 0 and cl < ch:
                    watch_row = {
                        "symbol": symbol,
                        "asof_date": bars["dates"][j],
                        "setup": "HTF",
                        "coil_high": ch,
                        "close": cl,
                        "dist_to_coil_pct": cl / ch - 1.0,
                        "prior_run_pct": 0.0,
                        "coil_range_pct": 0.0,
                        "notes": "near_coil_high",
                    }

    return closed, open_row, watch_row, n_signals


def resolve_symbols(symbols_arg: str, data_dir: Path) -> list[str]:
    s = (symbols_arg or "").strip()
    if not s or s == "*":
        if _list_csv_symbols is not None:
            return [x.upper() for x in _list_csv_symbols(data_dir, include_spy=False)]
        return sorted(
            p.stem.upper()
            for p in Path(data_dir).glob("*.csv")
            if p.stem.upper() != "SPY"
        )
    return [x.strip().upper() for x in s.split(",") if x.strip()]


def run_backtest(
    symbols: list[str],
    data_dir: Path,
    cfg: QullConfig,
) -> tuple[list[QullClosedRow], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    spy_map = build_spy_market_map(data_dir) if cfg.qull_market_filter else None
    closed: list[QullClosedRow] = []
    opens: list[dict[str, Any]] = []
    watches: list[dict[str, Any]] = []
    run_syms: list[str] = []
    skip_detail: list[str] = []
    n_signals = 0
    loaded: dict[str, pd.DataFrame] = {}

    for sym in symbols:
        path = Path(data_dir) / f"{sym}.csv"
        if not path.exists():
            skip_detail.append(f"{sym}: missing CSV")
            continue
        try:
            df = load_ohlcv_csv(path)
        except Exception as e:
            skip_detail.append(f"{sym}: load error {e}")
            continue
        if len(df) < 80:
            skip_detail.append(f"{sym}: insufficient bars ({len(df)})")
            continue
        loaded[sym] = df
        rows, op, w, sigs = run_symbol_qull(sym, df, cfg, spy_map)
        run_syms.append(sym)
        closed.extend(rows)
        if op:
            opens.append(op)
        if w:
            watches.append(w)
        n_signals += sigs

    closed.sort(key=lambda r: (r.date_opened, r.symbol))
    if bool(cfg.qull_fundamentals_fill) and classify_ep_catalyst is not None and _fund_ensure_symbols is not None:
        ep_syms = sorted({r.symbol for r in closed if str(r.setup).upper() == "EP"})
        if ep_syms:
            print(f"[QULL] EP catalyst soft-fill for {len(ep_syms)} symbols...", flush=True)
            try:
                funds = _fund_ensure_symbols(ep_syms)
                window = int(cfg.qull_ep_catalyst_window)
                min_surp = float(cfg.qull_ep_min_surprise)
                min_arg = min_surp if min_surp > 0 else None
                for r in closed:
                    if str(r.setup).upper() != "EP":
                        continue
                    bundle = funds.get(r.symbol)
                    if bundle is None:
                        r.ep_catalyst = "UNKNOWN"
                        continue
                    td = list(loaded[r.symbol].index) if r.symbol in loaded else None
                    r.ep_catalyst = classify_ep_catalyst(
                        r.trigger_date,
                        bundle.earnings_dates,
                        trading_dates=td,
                        window_trading_days=window,
                        min_surprise_pct=min_arg,
                    )
            except Exception as e:
                print(f"[QULL] EP catalyst enrich skipped: {e}", flush=True)

    wins = sum(1 for r in closed if r.pnl_pct > 0)
    exit_mix: dict[str, int] = {}
    for r in closed:
        exit_mix[r.exit_type] = exit_mix.get(r.exit_type, 0) + 1
    meta = {
        "symbols_requested": symbols,
        "symbols_run": run_syms,
        "symbols_skipped": [s for s in symbols if s not in run_syms],
        "skip_detail": skip_detail,
        "n_closed": len(closed),
        "n_open": len(opens),
        "n_signals": n_signals,
        "total_pnl": sum(r.pnl_dollars for r in closed),
        "win_rate": (100.0 * wins / len(closed)) if closed else 0.0,
        "avg_pnl_pct": float(np.mean([r.pnl_pct for r in closed])) if closed else 0.0,
        "avg_days_held": float(np.mean([r.days_held for r in closed])) if closed else 0.0,
        "exit_mix": exit_mix,
        "spy_filter_loaded": spy_map is not None,
    }
    return closed, opens, watches, meta


def write_outputs(
    output_dir: Path,
    stamp: str,
    cfg: QullConfig,
    closed: list[QullClosedRow],
    opens: list[dict[str, Any]],
    watches: list[dict[str, Any]],
    meta: dict[str, Any],
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    # Host dollar-scale
    host_meta: dict[str, Any] = {}
    if cfg.host_dollar_scale and closed:
        hcfg = HostSizingConfig(
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
        # apply_host_dollar_scale expects objects with pnl_dollars attr + optional open dicts
        adj, scale, max_pos = apply_host_dollar_scale(closed, opens, hcfg)
        cfg.cash = adj
        host_meta = {
            "host_max_positions": max_pos,
            "host_brt_cash": adj,
            "host_pnl_scale": scale,
            "host_audit_brt_cash": audit_display_brt_cash(max_pos),
        }
        meta["total_pnl"] = sum(r.pnl_dollars for r in closed)
        print(
            f"[QULL] Host dollar-scale x{scale:.6g}; cash->{adj:,.0f}; max_pos={max_pos}",
            flush=True,
        )

    closed_path = output_dir / f"{FILE_PREFIX}_Closed_{stamp}.csv"
    with closed_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CLOSED_HEADER)
        for r in closed:
            w.writerow(r.to_csv_row())
    paths["closed"] = closed_path

    open_path = output_dir / f"{FILE_PREFIX}_Open_{stamp}.csv"
    with open_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(OPEN_HEADER)
        for r in opens:
            w.writerow(
                [
                    r["symbol"],
                    r["date_opened"],
                    f"{r['entry_price']:.4f}",
                    f"{r['current_price']:.4f}",
                    f"{r['pnl_pct']:.4f}",
                    str(r["days_open"]),
                    f"{r['stop_loss']:.4f}",
                    f"{r['target']:.4f}" if r.get("target") else "",
                    r.get("setup", ""),
                    f"{r.get('coil_high', 0):.4f}",
                    str(r.get("trail_ema", "")),
                ]
            )
    paths["open"] = open_path

    watch_path = output_dir / f"{FILE_PREFIX}_Watchlist_{stamp}.csv"
    with watch_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(WATCH_HEADER)
        for r in watches:
            w.writerow(
                [
                    r["symbol"],
                    r["asof_date"],
                    r.get("setup", ""),
                    f"{r.get('coil_high', 0):.4f}",
                    f"{r.get('close', 0):.4f}",
                    f"{r.get('dist_to_coil_pct', 0):.4f}",
                    f"{r.get('prior_run_pct', 0):.4f}",
                    f"{r.get('coil_range_pct', 0):.4f}",
                    r.get("notes", ""),
                ]
            )
    paths["watchlist"] = watch_path

    # Summary
    by_sym: dict[str, list[QullClosedRow]] = {}
    for r in closed:
        by_sym.setdefault(r.symbol, []).append(r)
    summary_path = output_dir / f"{FILE_PREFIX}_Summary_{stamp}.csv"
    with summary_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "SYMBOL",
                "N_TRADES",
                "WIN_RATE_PCT",
                "TOTAL_PNL",
                "AVG_PNL_PCT",
                "PROFIT_FACTOR",
                "AVG_DAYS_HELD",
            ]
        )
        for sym in sorted(by_sym):
            rows = by_sym[sym]
            wins = sum(1 for r in rows if r.pnl_pct > 0)
            sum_wins = sum(r.pnl_dollars for r in rows if r.pnl_pct > 0)
            sum_losses = abs(sum(r.pnl_dollars for r in rows if r.pnl_pct < 0))
            pf = (sum_wins / sum_losses) if sum_losses > 0 else (sum_wins if sum_wins > 0 else 0.0)
            w.writerow(
                [
                    sym,
                    len(rows),
                    f"{100.0 * wins / len(rows):.2f}",
                    f"{sum(r.pnl_dollars for r in rows):.2f}",
                    f"{float(np.mean([r.pnl_pct for r in rows])) * 100:.4f}",
                    f"{pf:.2f}",
                    f"{float(np.mean([r.days_held for r in rows])):.2f}",
                ]
            )
        # universe total
        if closed:
            wins = sum(1 for r in closed if r.pnl_pct > 0)
            sum_wins = sum(r.pnl_dollars for r in closed if r.pnl_pct > 0)
            sum_losses = abs(sum(r.pnl_dollars for r in closed if r.pnl_pct < 0))
            pf = (sum_wins / sum_losses) if sum_losses > 0 else (sum_wins if sum_wins > 0 else 0.0)
            w.writerow(
                [
                    "ALL",
                    len(closed),
                    f"{100.0 * wins / len(closed):.2f}",
                    f"{sum(r.pnl_dollars for r in closed):.2f}",
                    f"{float(np.mean([r.pnl_pct for r in closed])) * 100:.4f}",
                    f"{pf:.2f}",
                    f"{float(np.mean([r.days_held for r in closed])):.2f}",
                ]
            )
    paths["summary"] = summary_path

    report_path = output_dir / f"{FILE_PREFIX}_Report_{stamp}.txt"
    lines = [
        f"QULL EP/HTF report {stamp}",
        f"setup={cfg.qull_setup} prior_run>={cfg.qull_prior_run_pct} coil={cfg.qull_coil_bars}/{cfg.qull_coil_range_pct}",
        f"trail=EMA{cfg.qull_trail_ema} market_filter={cfg.qull_market_filter}",
        f"symbols_run={len(meta.get('symbols_run', []))} closed={meta.get('n_closed')} open={meta.get('n_open')} signals={meta.get('n_signals')}",
        f"win_rate={meta.get('win_rate'):.2f}% avg_pnl_pct={100*float(meta.get('avg_pnl_pct') or 0):.3f}% total_pnl={meta.get('total_pnl'):.2f}",
        f"exit_mix={meta.get('exit_mix')}",
        f"spy_filter_loaded={meta.get('spy_filter_loaded')}",
        f"host_meta={host_meta}",
        f"skip_detail={meta.get('skip_detail')}",
    ]
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    paths["report"] = report_path

    # Lightweight audit stub (full wide Audit deferred until qull_mode host)
    audit_path = output_dir / f"{FILE_PREFIX}_Audit_Report_{stamp}.csv"
    with audit_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["KEY", "VALUE"])
        for k, v in [
            ("stamp", stamp),
            ("prefix", FILE_PREFIX),
            ("engine", "rocket_qull_ep_htf_standalone"),
            ("qull_setup", cfg.qull_setup),
            ("qull_prior_run_pct", cfg.qull_prior_run_pct),
            ("qull_coil_bars", cfg.qull_coil_bars),
            ("qull_coil_range_pct", cfg.qull_coil_range_pct),
            ("qull_trail_ema", cfg.qull_trail_ema),
            ("qull_bo_vol_mult", cfg.qull_bo_vol_mult),
            ("n_closed", meta.get("n_closed")),
            ("n_open", meta.get("n_open")),
            ("n_signals", meta.get("n_signals")),
            ("win_rate_pct", f"{meta.get('win_rate'):.4f}"),
            ("total_pnl", f"{meta.get('total_pnl'):.2f}"),
            ("avg_pnl_pct", f"{meta.get('avg_pnl_pct')}"),
            ("host_note", "key_value_stub_until_qull_mode"),
        ]:
            w.writerow([k, v])
        for k, v in host_meta.items():
            w.writerow([k, v])
    paths["audit"] = audit_path

    # Equity (simple cumulative; full BRT_DrawdownCalc needs ticker frames + host mode)
    equity_path = output_dir / f"{FILE_PREFIX}_EquityCurve_{stamp}.csv"
    equity_meta_path = output_dir / f"{FILE_PREFIX}_EquityMeta_{stamp}.csv"
    with equity_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["DATE", "EQUITY", "PNL"])
        eq = float(cfg.initial_capital)
        w.writerow(["START", f"{eq:.2f}", "0"])
        for r in sorted(closed, key=lambda x: x.date_closed):
            eq += r.pnl_dollars
            w.writerow([r.date_closed, f"{eq:.2f}", f"{r.pnl_dollars:.2f}"])
    paths["equity"] = equity_path
    equity_meta_path.write_text(
        "mode=simple_cumulative\n"
        f"initial_capital={cfg.initial_capital}\n"
        f"aggressive={int(bool(cfg.aggressive))}\n"
        "note=full_host_equity_when_qull_mode\n",
        encoding="utf-8",
    )
    paths["equity_meta"] = equity_meta_path
    if cfg.aggressive:
        # Mirror simple curve as Aggressive placeholder so bats expecting the file find it
        agg = output_dir / f"{FILE_PREFIX}_EquityCurve_Aggressive_{stamp}.csv"
        shutil.copy2(equity_path, agg)
        paths["equity_aggressive"] = agg

    # LatestRun mirrors
    for label, src in [
        ("Closed", closed_path),
        ("Open", open_path),
        ("Summary", summary_path),
        ("Watchlist", watch_path),
        ("Audit_Report", audit_path),
        ("EquityCurve", equity_path),
    ]:
        dst = output_dir / f"{FILE_PREFIX}_LatestRun_{label}.csv"
        shutil.copy2(src, dst)
        paths[f"latest_{label}"] = dst
    (output_dir / f"{FILE_PREFIX}_last_run_ts.txt").write_text(stamp + "\n", encoding="utf-8")
    paths["last_run_ts"] = output_dir / f"{FILE_PREFIX}_last_run_ts.txt"
    return paths


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Qullamaggie EP/HTF seed engine (QULL_*)")
    p.add_argument("data_dir", nargs="?", default="data/newdata/data")
    p.add_argument("-o", "--output-dir", default="drive")
    p.add_argument("-s", "--symbols", default=DEFAULT_SEED_SYMBOLS)
    p.add_argument("--stamp", default="")
    p.add_argument("--setup", default="htf", help="htf | ep | both")
    p.add_argument("--prior-run", type=float, default=0.50)
    p.add_argument("--prior-bars", type=int, default=42)
    p.add_argument("--coil-bars", type=int, default=10)
    p.add_argument("--coil-range", type=float, default=0.15)
    p.add_argument("--bo-vol", type=float, default=1.5)
    p.add_argument("--trail-ema", type=int, default=10)
    p.add_argument("--market-filter", type=_as_bool, default=True)
    p.add_argument("--max-stop-adr", type=float, default=1.0)
    p.add_argument("--min-price", type=float, default=3.0)
    p.add_argument("--min-adv", type=float, default=2_000_000.0)
    p.add_argument("--ep-gap", type=float, default=0.10)
    p.add_argument("--ep-vol", type=float, default=3.0)
    p.add_argument("--cash", type=float, default=DEFAULT_CASH)
    p.add_argument("--initial-capital", type=float, default=DEFAULT_INITIAL_CAPITAL)
    p.add_argument("--aggressive-max-multiple", type=float, default=DEFAULT_AGGRESSIVE_MAX_MULTIPLE)
    p.add_argument("--margin-utilization", type=float, default=DEFAULT_MARGIN_UTILIZATION)
    p.add_argument("--max-positions", type=int, default=0)
    p.add_argument("--aggressive", action="store_true")
    p.add_argument("--entry-start-date", default="")
    p.add_argument("--entry-end-date", default="")
    p.add_argument(
        "-w",
        "--workers",
        type=int,
        default=0,
        help="Parallel workers (accepted for run_*.bat parity; 0=sequential)",
    )
    return p


def cfg_from_args(ns: argparse.Namespace) -> QullConfig:
    return QullConfig(
        qull_setup=str(ns.setup),
        qull_prior_run_pct=float(ns.prior_run),
        qull_prior_run_bars=int(ns.prior_bars),
        qull_coil_bars=int(ns.coil_bars),
        qull_coil_range_pct=float(ns.coil_range),
        qull_bo_vol_mult=float(ns.bo_vol),
        qull_trail_ema=int(ns.trail_ema),
        qull_market_filter=_as_bool(ns.market_filter),
        qull_max_stop_adr_mult=float(ns.max_stop_adr),
        qull_min_price=float(ns.min_price),
        qull_min_adv_usd=float(ns.min_adv),
        qull_ep_gap_pct=float(ns.ep_gap),
        qull_ep_vol_mult=float(ns.ep_vol),
        cash=float(ns.cash),
        initial_capital=float(ns.initial_capital),
        aggressive_max_multiple=float(ns.aggressive_max_multiple),
        margin_utilization=float(ns.margin_utilization),
        max_positions=int(ns.max_positions),
        aggressive=bool(ns.aggressive),
        entry_start_date=str(ns.entry_start_date or ""),
        entry_end_date=str(ns.entry_end_date or ""),
    )


def main(argv: Optional[list[str]] = None) -> int:
    ns = build_arg_parser().parse_args(argv)
    data_dir = Path(ns.data_dir)
    out_dir = Path(ns.output_dir)
    cfg = cfg_from_args(ns)
    symbols = resolve_symbols(ns.symbols, data_dir)
    stamp = (ns.stamp or "").strip() or datetime.now().strftime("%y%m%d%H%M%S")
    print(
        f"[QULL] {len(symbols)} symbols setup={cfg.qull_setup} "
        f"prior>={cfg.qull_prior_run_pct} coil={cfg.qull_coil_bars}/{cfg.qull_coil_range_pct} "
        f"trail=EMA{cfg.qull_trail_ema} stamp={stamp}",
        flush=True,
    )
    closed, opens, watches, meta = run_backtest(symbols, data_dir, cfg)
    paths = write_outputs(out_dir, stamp, cfg, closed, opens, watches, meta)
    print(
        f"[QULL] Done closed={meta['n_closed']} open={meta['n_open']} "
        f"WR={meta['win_rate']:.1f}% pnl={meta['total_pnl']:.2f} "
        f"-> {paths.get('closed')}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
