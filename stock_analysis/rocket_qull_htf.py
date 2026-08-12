"""Qullamaggie High Tight Flag (HTF) + Episodic Pivot (EP) proxy — TBN ``qull_mode``.

Host: ``rocket_tbn.py``. Outputs: ``drive/QULL_*_<stamp>.csv``.

Theory freeze: ``drive/paul_experiments/tbn_new_systems/qull_ep_htf/RESEARCH.md``.
HTF is primary (default). EP is a price/volume proxy; EP_CATALYST soft-fills from
yfinance DuckDB cache when earnings dates fall near the gap (default OFF via setup=htf).
"""
from __future__ import annotations

import csv
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

try:
    from tbn_host_sizing import (
        HostSizingConfig,
        apply_host_dollar_scale,
        audit_display_brt_cash,
        compute_and_write_host_equity,
    )
except ImportError:
    from stock_analysis.tbn_host_sizing import (  # type: ignore
        HostSizingConfig,
        apply_host_dollar_scale,
        audit_display_brt_cash,
        compute_and_write_host_equity,
    )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class QullConfig:
    qull_mode: bool = True
    # htf | ep | both  (ep default off via setup=htf)
    qull_setup: str = "htf"
    # HTF geometry
    qull_prior_run_bars: int = 42
    qull_prior_run_pct: float = 0.50
    qull_coil_bars: int = 10
    qull_coil_range_pct: float = 0.15
    qull_ema_surf_pct: float = 0.04
    qull_require_ema_surf: bool = True
    qull_vol_dry_ratio: float = 0.85
    qull_vol_dry_soft: bool = True
    qull_vol_breakout_mult: float = 1.5
    qull_min_price: float = 3.0
    qull_min_adv_usd: float = 2_000_000.0
    qull_adv_lookback: int = 20
    # Market filter (SPY SMA10 > SMA20 lag-1)
    qull_market_filter: bool = True
    # EP proxy (catalyst soft-fill from yfinance earnings dates when available)
    qull_ep_gap_pct: float = 0.10
    qull_ep_vol_mult: float = 3.0
    qull_ep_require_flat_prior: bool = True
    qull_ep_flat_lookback: int = 63
    qull_ep_flat_max_run_pct: float = 0.30
    qull_ep_catalyst_window: int = 5  # ± trading days around gap
    qull_ep_min_surprise: float = 0.0  # 0 = any earnings proximity; else fraction e.g. 0.05
    qull_fundamentals_fill: bool = True
    # Risk / exit
    qull_stop_under: str = "breakout_low"  # breakout_low | coil_low
    qull_max_stop_adr_mult: float = 1.0
    qull_adr_lookback: int = 20
    qull_trail_ema: int = 10  # 10 or 20
    qull_partial_days: int = 0  # 0 = off
    qull_partial_frac: float = 0.33
    qull_fill: str = "next_open"  # next_open | signal_close
    # SMA entry filters (default OFF = production)
    # above: fill/entry price >= SMAn on fill bar (also signal close >= SMAn)
    # rising: SMA50[signal] > SMA50[signal - qull_sma50_slope_bars] (strict; flat/down fails)
    qull_require_above_sma50: bool = False
    qull_require_sma50_rising: bool = False
    qull_sma50_slope_bars: int = 10
    qull_require_above_sma20: bool = False
    qull_require_above_sma10: bool = False
    symbol_reentry_cooldown_days: int = 5
    entry_start_date: str = ""
    entry_end_date: str = ""
    brt_cash: float = 19_350.0


def qull_config_from_brt(cfg: Any) -> QullConfig:
    kw: dict[str, Any] = {}
    for f in fields(QullConfig):
        if hasattr(cfg, f.name):
            kw[f.name] = getattr(cfg, f.name)
    return QullConfig(**kw)


def _qull_cfg_dict(cfg: QullConfig) -> dict[str, Any]:
    return {f.name: getattr(cfg, f.name) for f in fields(QullConfig)}


# ---------------------------------------------------------------------------
# Rows / headers
# ---------------------------------------------------------------------------


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
    market_10gt20: str
    ep_gap_pct: float
    ep_catalyst: str
    trigger_date: str
    trigger_close: float
    one_liner: str

    def to_csv_row(self) -> list[str]:
        return [
            self.symbol,
            self.side,
            self.date_opened,
            f"{self.entry_price:.4f}",
            f"{self.stop_price:.4f}",
            f"{self.target_price:.4f}",
            self.date_closed,
            f"{self.exit_price:.4f}",
            self.exit_type,
            str(self.days_held),
            f"{self.pnl_pct:.4f}",
            f"{self.pnl_dollars:.2f}",
            f"{self.ann_ror_pct:.2f}",
            f"{self.max_price:.4f}",
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
            self.market_10gt20,
            f"{self.ep_gap_pct:.4f}",
            self.ep_catalyst,
            self.trigger_date,
            f"{self.trigger_close:.4f}",
            self.one_liner,
        ]


QULL_CLOSED_HEADER = [
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
    "TRIGGER_DATE",
    "TRIGGER_CLOSE",
    "ONE_LINER",
]

QULL_OPEN_HEADER = [
    "SYMBOL",
    "DATE_OPENED",
    "ENTRY_PRICE",
    "CURRENT_PRICE",
    "PNL_PCT",
    "DAYS_OPEN",
    "STOP_LOSS",
    "SETUP",
    "COIL_HIGH",
    "TRAIL_EMA",
]

QULL_WATCHLIST_HEADER = [
    "SYMBOL",
    "ASOF_DATE",
    "SETUP",
    "COIL_HIGH",
    "CLOSE",
    "DIST_TO_COIL_HIGH_PCT",
    "PRIOR_RUN_PCT",
    "COIL_RANGE_PCT",
    "NOTES",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iso(d: Any) -> str:
    if hasattr(d, "strftime"):
        return d.strftime("%Y%m%d")
    s = str(d)[:10].replace("-", "")
    return s


def _entry_date_allowed(iso: str, start: str, end: str) -> bool:
    s = (start or "").strip().replace("-", "")[:8]
    e = (end or "").strip().replace("-", "")[:8]
    if s and iso < s:
        return False
    if e and iso > e:
        return False
    return True


def _calendar_days(d1: str, d2: str) -> int:
    def _ep(d: str) -> int:
        t = time.struct_time((int(d[:4]), int(d[4:6]), int(d[6:8]), 0, 0, 0, 0, 0, -1))
        return int(time.mktime(t))

    return int((_ep(d2) - _ep(d1)) / 86400)


def _ema(arr: np.ndarray, span: int) -> np.ndarray:
    return pd.Series(arr).ewm(span=span, adjust=False).mean().to_numpy()


def prepare_bars(df: pd.DataFrame) -> dict[str, Any]:
    df = df.sort_index()
    dates = [_iso(d) for d in df.index]
    o = df["Open"].astype(float).to_numpy()
    h = df["High"].astype(float).to_numpy()
    l = df["Low"].astype(float).to_numpy()
    c = df["Close"].astype(float).to_numpy()
    vol = df["Volume"].astype(float).to_numpy() if "Volume" in df.columns else np.zeros(len(df))
    ema10 = _ema(c, 10)
    ema20 = _ema(c, 20)
    close_s = pd.Series(c)
    sma10 = close_s.rolling(10, min_periods=10).mean().to_numpy()
    sma20 = close_s.rolling(20, min_periods=20).mean().to_numpy()
    sma50 = close_s.rolling(50, min_periods=50).mean().to_numpy()
    vol_sma20 = pd.Series(vol).rolling(20, min_periods=20).mean().to_numpy()
    # ADR% = mean((H-L)/C) over lookback
    rng = np.where(c > 0, (h - l) / c, np.nan)
    adr20 = pd.Series(rng).rolling(20, min_periods=10).mean().to_numpy()
    return {
        "dates": dates,
        "o": o,
        "h": h,
        "l": l,
        "c": c,
        "vol": vol,
        "ema10": ema10,
        "ema20": ema20,
        "sma10": sma10,
        "sma20": sma20,
        "sma50": sma50,
        "vol_sma20": vol_sma20,
        "adr20": adr20,
        "n": len(dates),
    }


def _sma50_rising_ok(bars: dict[str, Any], i: int, cfg: QullConfig) -> bool:
    """True when SMA50[i] > SMA50[i - slope_bars] (strict up; flat/down fail)."""
    sma = bars.get("sma50")
    if sma is None or i < 0 or i >= len(sma):
        return False
    n = max(1, int(getattr(cfg, "qull_sma50_slope_bars", 10) or 10))
    j = i - n
    if j < 0:
        return False
    s1 = float(sma[i])
    s0 = float(sma[j])
    if not (np.isfinite(s1) and np.isfinite(s0) and s0 > 0 and s1 > 0):
        return False
    return s1 > s0


def _above_sma_ok(bars: dict[str, Any], i: int, key: str, price: float) -> bool:
    """True when price >= bars[key][i] (finite positive SMA)."""
    sma = bars.get(key)
    if sma is None or i < 0 or i >= len(sma):
        return False
    s = float(sma[i])
    if not (np.isfinite(s) and s > 0):
        return False
    return float(price) >= s


def _sma_entry_signal_ok(bars: dict[str, Any], i: int, cfg: QullConfig) -> bool:
    """Signal-bar SMA filters (rising checked here; above also checked at fill)."""
    need_rising = bool(getattr(cfg, "qull_require_sma50_rising", False))
    need50 = bool(getattr(cfg, "qull_require_above_sma50", False))
    need20 = bool(getattr(cfg, "qull_require_above_sma20", False))
    need10 = bool(getattr(cfg, "qull_require_above_sma10", False))
    if not need_rising and not need50 and not need20 and not need10:
        return True
    close = float(bars["c"][i])
    if need50 and not _above_sma_ok(bars, i, "sma50", close):
        return False
    if need20 and not _above_sma_ok(bars, i, "sma20", close):
        return False
    if need10 and not _above_sma_ok(bars, i, "sma10", close):
        return False
    if need_rising and not _sma50_rising_ok(bars, i, cfg):
        return False
    return True


def _sma_entry_fill_ok(bars: dict[str, Any], i: int, cfg: QullConfig, fill_px: float) -> bool:
    """Fill-bar above-SMA gates (mirrors signal gates for entry price)."""
    if bool(getattr(cfg, "qull_require_above_sma50", False)):
        if not _above_sma_ok(bars, i, "sma50", fill_px):
            return False
    if bool(getattr(cfg, "qull_require_above_sma20", False)):
        if not _above_sma_ok(bars, i, "sma20", fill_px):
            return False
    if bool(getattr(cfg, "qull_require_above_sma10", False)):
        if not _above_sma_ok(bars, i, "sma10", fill_px):
            return False
    return True


# Back-compat alias used by older call sites / tests
_sma50_signal_ok = _sma_entry_signal_ok


def load_spy_market_ok(data_dir: Path, load_symbol_fn: Any = None) -> dict[str, bool]:
    """Map YYYYMMDD -> SPY SMA10 > SMA20 (same-day; caller lag-1)."""
    spy = None
    for name in ("SPY", "spy"):
        p = Path(data_dir) / f"{name}.csv"
        if p.exists():
            try:
                spy = pd.read_csv(p, parse_dates=True, index_col=0)
            except Exception:
                spy = None
            break
    if spy is None and load_symbol_fn is not None:
        try:
            spy = load_symbol_fn("SPY", data_dir)
        except Exception:
            spy = None
    if spy is None or len(spy) < 30:
        return {}
    spy = spy.sort_index()
    c = spy["Close"].astype(float)
    s10 = c.ewm(span=10, adjust=False).mean()
    # Use SMA for market filter (classic 10>20 SMA); keep simple SMA
    sma10 = c.rolling(10, min_periods=10).mean()
    sma20 = c.rolling(20, min_periods=20).mean()
    out: dict[str, bool] = {}
    for d, a, b in zip(spy.index, sma10, sma20):
        if pd.isna(a) or pd.isna(b):
            continue
        out[_iso(d)] = bool(float(a) > float(b))
    return out


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HtfSignal:
    i: int
    prior_run_pct: float
    coil_range_pct: float
    coil_high: float
    coil_low: float
    ema_surf_pct: float
    vol_ratio: float
    adr_pct: float


@dataclass(frozen=True)
class EpSignal:
    i: int
    gap_pct: float
    vol_ratio: float
    prior_run_pct: float


def detect_htf_signal(bars: dict[str, Any], i: int, cfg: QullConfig) -> HtfSignal | None:
    coil = int(cfg.qull_coil_bars)
    prior_n = int(cfg.qull_prior_run_bars)
    if i < coil + prior_n + 5:
        return None
    if float(bars["c"][i]) < float(cfg.qull_min_price):
        return None

    coil_lo = i - coil
    coil_hi = i  # exclusive end = i → bars coil_lo .. i-1
    if coil_lo < 0:
        return None
    prior_lo = coil_lo - prior_n
    prior_hi = coil_lo
    if prior_lo < 0:
        return None

    h = bars["h"]
    l = bars["l"]
    c = bars["c"]
    vol = bars["vol"]

    prior_max = float(np.max(h[prior_lo:prior_hi]))
    prior_min = float(np.min(l[prior_lo:prior_hi]))
    if prior_min <= 0:
        return None
    prior_run = (prior_max / prior_min) - 1.0
    if prior_run < float(cfg.qull_prior_run_pct):
        return None

    coil_closes = c[coil_lo:coil_hi]
    coil_high = float(np.max(h[coil_lo:coil_hi]))
    coil_low = float(np.min(l[coil_lo:coil_hi]))
    c_max = float(np.max(coil_closes))
    c_min = float(np.min(coil_closes))
    if c_min <= 0:
        return None
    coil_range = (c_max / c_min) - 1.0
    if coil_range > float(cfg.qull_coil_range_pct):
        return None

    # Breakout: close clears coil high
    if float(c[i]) <= coil_high:
        return None

    vma = bars["vol_sma20"][i]
    if not np.isfinite(vma) or vma <= 0:
        return None
    vol_ratio = float(vol[i]) / float(vma)
    if vol_ratio < float(cfg.qull_vol_breakout_mult):
        return None

    # Volume dry soft check on coil
    if bool(cfg.qull_vol_dry_soft):
        coil_vol = float(np.mean(vol[coil_lo:coil_hi])) if coil_hi > coil_lo else 0.0
        prior_vol = float(np.mean(vol[prior_lo:prior_hi])) if prior_hi > prior_lo else 0.0
        if prior_vol > 0 and coil_vol > float(cfg.qull_vol_dry_ratio) * prior_vol:
            # soft: still allow if breakout vol is strong (>= 2x)
            if vol_ratio < max(2.0, float(cfg.qull_vol_breakout_mult)):
                return None

    ema10 = float(bars["ema10"][i - 1]) if i >= 1 else float("nan")
    surf = float("nan")
    if np.isfinite(ema10) and ema10 > 0:
        surf = abs(float(c[i - 1]) - ema10) / ema10
        ema10_rising = float(bars["ema10"][i - 1]) > float(bars["ema10"][max(0, i - 2)])
        if bool(cfg.qull_require_ema_surf):
            if (not np.isfinite(surf)) or surf > float(cfg.qull_ema_surf_pct) or not ema10_rising:
                return None

    # ADV$
    adv_n = int(cfg.qull_adv_lookback)
    if i >= adv_n and float(cfg.qull_min_adv_usd) > 0:
        adv = float(np.mean(vol[i - adv_n : i] * c[i - adv_n : i]))
        if adv < float(cfg.qull_min_adv_usd):
            return None

    adr = float(bars["adr20"][i]) if np.isfinite(bars["adr20"][i]) else float("nan")
    return HtfSignal(
        i=i,
        prior_run_pct=prior_run,
        coil_range_pct=coil_range,
        coil_high=coil_high,
        coil_low=coil_low,
        ema_surf_pct=float(surf) if np.isfinite(surf) else 0.0,
        vol_ratio=vol_ratio,
        adr_pct=adr * 100.0 if np.isfinite(adr) else 0.0,
    )


def detect_ep_signal(bars: dict[str, Any], i: int, cfg: QullConfig) -> EpSignal | None:
    """Price/volume EP proxy — catalyst filled post-run when earnings cache hits."""
    if i < 65:
        return None
    o = float(bars["o"][i])
    prev_c = float(bars["c"][i - 1])
    if prev_c <= 0 or o <= 0:
        return None
    gap = (o / prev_c) - 1.0
    if gap < float(cfg.qull_ep_gap_pct):
        return None
    vma = bars["vol_sma20"][i]
    if not np.isfinite(vma) or vma <= 0:
        return None
    vol_ratio = float(bars["vol"][i]) / float(vma)
    if vol_ratio < float(cfg.qull_ep_vol_mult):
        return None
    if float(bars["c"][i]) < float(cfg.qull_min_price):
        return None

    flat_n = int(cfg.qull_ep_flat_lookback)
    prior_run = 0.0
    if bool(cfg.qull_ep_require_flat_prior) and i >= flat_n + 1:
        lo = i - flat_n
        hi = i  # exclude gap day
        mx = float(np.max(bars["h"][lo:hi]))
        mn = float(np.min(bars["l"][lo:hi]))
        if mn > 0:
            prior_run = (mx / mn) - 1.0
            if prior_run > float(cfg.qull_ep_flat_max_run_pct):
                return None

    adv_n = int(cfg.qull_adv_lookback)
    if i >= adv_n and float(cfg.qull_min_adv_usd) > 0:
        adv = float(np.mean(bars["vol"][i - adv_n : i] * bars["c"][i - adv_n : i]))
        if adv < float(cfg.qull_min_adv_usd):
            return None

    return EpSignal(i=i, gap_pct=gap, vol_ratio=vol_ratio, prior_run_pct=prior_run)


def _enrich_qull_ep_catalyst(
    closed: list[QullClosedRow],
    *,
    tickers: Optional[dict[str, pd.DataFrame]] = None,
    cfg: QullConfig,
    no_yfinance: bool = False,
) -> None:
    """Soft-fill EP_CATALYST from yfinance DuckDB earnings dates (in-place)."""
    if not bool(getattr(cfg, "qull_fundamentals_fill", True)):
        return
    ep_syms = sorted({r.symbol for r in closed if str(r.setup).upper() == "EP"})
    if not ep_syms:
        return
    try:
        from fundamentals_yfinance import (
            classify_ep_catalyst,
            ensure_symbols,
            yfinance_disabled,
        )
    except ImportError:
        try:
            from stock_analysis.fundamentals_yfinance import (  # type: ignore
                classify_ep_catalyst,
                ensure_symbols,
                yfinance_disabled,
            )
        except ImportError:
            print("[QULL] fundamentals module missing — EP_CATALYST stays UNKNOWN", flush=True)
            return
    if no_yfinance or yfinance_disabled():
        # Still try cache-only (NO_YFINANCE inside ensure)
        pass
    print(f"[QULL] EP catalyst soft-fill for {len(ep_syms)} symbols...", flush=True)
    funds = ensure_symbols(ep_syms)
    window = int(getattr(cfg, "qull_ep_catalyst_window", 5) or 5)
    min_surp = float(getattr(cfg, "qull_ep_min_surprise", 0.0) or 0.0)
    min_arg = min_surp if min_surp > 0 else None
    for r in closed:
        if str(r.setup).upper() != "EP":
            continue
        bundle = funds.get(r.symbol)
        if bundle is None:
            r.ep_catalyst = "UNKNOWN"
            continue
        td = None
        if tickers and r.symbol in tickers:
            df = tickers[r.symbol]
            if df is not None and len(df):
                idx = df.index if hasattr(df, "index") else None
                if idx is not None:
                    td = list(idx)
        r.ep_catalyst = classify_ep_catalyst(
            r.trigger_date,
            bundle.earnings_dates,
            trading_dates=td,
            window_trading_days=window,
            min_surprise_pct=min_arg,
        )


# ---------------------------------------------------------------------------
# Backtest per symbol
# ---------------------------------------------------------------------------


@dataclass
class QullSymbolResult:
    symbol: str
    closed: list[QullClosedRow]
    open_rows: list[dict[str, Any]]
    watch: list[dict[str, Any]]
    skip_reason: str = ""


def backtest_symbol(
    symbol: str,
    df: pd.DataFrame,
    cfg: QullConfig,
    market_ok_by_date: Optional[dict[str, bool]] = None,
) -> QullSymbolResult:
    if df is None or len(df) < 80:
        return QullSymbolResult(symbol, [], [], [], skip_reason="insufficient_bars")
    bars = prepare_bars(df)
    setup_mode = str(cfg.qull_setup or "htf").strip().lower()
    do_htf = setup_mode in ("htf", "both", "all")
    do_ep = setup_mode in ("ep", "both", "all")
    trail_n = 10 if int(cfg.qull_trail_ema) <= 10 else 20
    return _backtest_symbol_two_pass(symbol, bars, cfg, market_ok_by_date, do_htf, do_ep, trail_n)


def _backtest_symbol_two_pass(
    symbol: str,
    bars: dict[str, Any],
    cfg: QullConfig,
    market_ok_by_date: Optional[dict[str, bool]],
    do_htf: bool,
    do_ep: bool,
    trail_n: int,
) -> QullSymbolResult:
    n = bars["n"]
    closed: list[QullClosedRow] = []
    watch: list[dict[str, Any]] = []
    open_pos: Optional[dict[str, Any]] = None
    pending: Optional[dict[str, Any]] = None
    last_exit_iso = ""

    for i in range(n):
        iso = bars["dates"][i]

        # Fill pending at open
        if pending is not None and open_pos is None and i == int(pending["fill_i"]):
            fill_px = float(bars["o"][i]) if str(cfg.qull_fill) == "next_open" else float(pending["trigger_close"])
            if fill_px <= 0:
                pending = None
            else:
                stop_px = float(pending["stop_price"])
                if stop_px >= fill_px:
                    pending = None
                else:
                    adr = float(pending["adr_pct"]) / 100.0 if pending["adr_pct"] else 0.0
                    stop_dist = (fill_px - stop_px) / fill_px
                    stop_adr_mult = (stop_dist / adr) if adr > 1e-9 else 99.0
                    reject = False
                    if float(cfg.qull_max_stop_adr_mult) > 0 and stop_adr_mult > float(cfg.qull_max_stop_adr_mult):
                        reject = True
                    elif not _sma_entry_fill_ok(bars, i, cfg, fill_px):
                        reject = True
                    if reject:
                        pending = None
                    else:
                        open_pos = {
                            **pending,
                            "entry_i": i,
                            "date_opened": iso,
                            "entry_price": fill_px,
                            "init_stop": stop_px,
                            "stop_price": stop_px,
                            "max_price": fill_px,
                            "stop_adr_mult": stop_adr_mult,
                            "partial_done": False,
                        }
                        pending = None

        # Manage open
        if open_pos is not None and i > int(open_pos["entry_i"]):
            entry_px = float(open_pos["entry_price"])
            stop_px = float(open_pos["stop_price"])
            max_px = max(float(open_pos["max_price"]), float(bars["h"][i]))
            open_pos["max_price"] = max_px
            exit_px = None
            exit_type = ""

            if float(bars["l"][i]) <= stop_px:
                if float(bars["o"][i]) <= stop_px:
                    exit_px = float(bars["o"][i])
                    exit_type = "GAP_DOWN"
                else:
                    exit_px = stop_px
                    exit_type = "STOP_LOSS"

            if (
                exit_px is None
                and int(cfg.qull_partial_days) > 0
                and not open_pos.get("partial_done")
                and (i - int(open_pos["entry_i"])) >= int(cfg.qull_partial_days)
            ):
                open_pos["partial_done"] = True
                open_pos["stop_price"] = max(stop_px, entry_px)

            if exit_px is None:
                trail = float(bars["ema10"][i] if trail_n <= 10 else bars["ema20"][i])
                if np.isfinite(trail) and float(bars["c"][i]) < trail:
                    exit_px = float(bars["c"][i])
                    exit_type = f"TRAIL_EMA{trail_n}"

            if exit_px is not None:
                pnl_pct = (exit_px / entry_px - 1.0) * 100.0
                pnl_dollars = pnl_pct / 100.0 * 10_000.0
                days = _calendar_days(open_pos["date_opened"], iso)
                ann = (pnl_pct / max(days, 1)) * 365.0 if days > 0 else 0.0
                closed.append(
                    QullClosedRow(
                        symbol=symbol,
                        side="LONG",
                        date_opened=open_pos["date_opened"],
                        entry_price=entry_px,
                        stop_price=float(open_pos["init_stop"]),
                        target_price=0.0,
                        date_closed=iso,
                        exit_price=exit_px,
                        exit_type=exit_type,
                        days_held=max(days, 0),
                        pnl_pct=pnl_pct,
                        pnl_dollars=pnl_dollars,
                        ann_ror_pct=ann,
                        max_price=max_px,
                        setup=str(open_pos["setup"]),
                        prior_run_pct=float(open_pos["prior_run_pct"]),
                        coil_bars=int(open_pos["coil_bars"]),
                        coil_range_pct=float(open_pos["coil_range_pct"]),
                        coil_high=float(open_pos["coil_high"]),
                        coil_low=float(open_pos["coil_low"]),
                        ema10=float(open_pos.get("ema10", 0)),
                        ema20=float(open_pos.get("ema20", 0)),
                        ema_surf_pct=float(open_pos["ema_surf_pct"]),
                        vol_ratio_bo=float(open_pos["vol_ratio"]),
                        adr_pct=float(open_pos["adr_pct"]),
                        stop_adr_mult=float(open_pos["stop_adr_mult"]),
                        trail_ema=trail_n,
                        market_10gt20=str(open_pos["market_10gt20"]),
                        ep_gap_pct=float(open_pos["ep_gap_pct"]),
                        ep_catalyst=str(open_pos["ep_catalyst"]),
                        trigger_date=open_pos["trigger_date"],
                        trigger_close=float(open_pos["trigger_close"]),
                        one_liner="",
                    )
                )
                last_exit_iso = iso
                open_pos = None

        if open_pos is not None or pending is not None:
            continue

        if last_exit_iso and _calendar_days(last_exit_iso, iso) < int(cfg.symbol_reentry_cooldown_days):
            continue
        if not _entry_date_allowed(iso, cfg.entry_start_date, cfg.entry_end_date):
            continue

        mkt = "NA"
        if bool(cfg.qull_market_filter) and market_ok_by_date:
            prev_iso = bars["dates"][i - 1] if i >= 1 else ""
            ok = market_ok_by_date.get(prev_iso)
            if ok is False:
                continue
            if ok is True:
                mkt = "true"
            elif ok is None and market_ok_by_date:
                continue
        elif bool(cfg.qull_market_filter):
            mkt = "nofeed"

        sig_payload = None
        if do_htf:
            htf = detect_htf_signal(bars, i, cfg)
            if htf is not None and _sma_entry_signal_ok(bars, i, cfg):
                if str(cfg.qull_stop_under).lower() == "coil_low":
                    stop_px = float(htf.coil_low)
                else:
                    stop_px = float(bars["l"][i])
                sig_payload = {
                    "setup": "HTF",
                    "trigger_date": iso,
                    "trigger_close": float(bars["c"][i]),
                    "stop_price": stop_px,
                    "prior_run_pct": htf.prior_run_pct,
                    "coil_bars": int(cfg.qull_coil_bars),
                    "coil_range_pct": htf.coil_range_pct,
                    "coil_high": htf.coil_high,
                    "coil_low": htf.coil_low,
                    "ema_surf_pct": htf.ema_surf_pct,
                    "vol_ratio": htf.vol_ratio,
                    "adr_pct": htf.adr_pct,
                    "ema10": float(bars["ema10"][i]),
                    "ema20": float(bars["ema20"][i]),
                    "market_10gt20": mkt,
                    "ep_gap_pct": 0.0,
                    "ep_catalyst": "",
                    "fill_i": i + 1 if str(cfg.qull_fill) == "next_open" else i,
                }
        if sig_payload is None and do_ep:
            ep = detect_ep_signal(bars, i, cfg)
            if ep is not None and _sma_entry_signal_ok(bars, i, cfg):
                stop_px = float(bars["l"][i])
                sig_payload = {
                    "setup": "EP",
                    "trigger_date": iso,
                    "trigger_close": float(bars["c"][i]),
                    "stop_price": stop_px,
                    "prior_run_pct": ep.prior_run_pct,
                    "coil_bars": 0,
                    "coil_range_pct": 0.0,
                    "coil_high": float(bars["h"][i]),
                    "coil_low": stop_px,
                    "ema_surf_pct": 0.0,
                    "vol_ratio": ep.vol_ratio,
                    "adr_pct": float(bars["adr20"][i]) * 100.0 if np.isfinite(bars["adr20"][i]) else 0.0,
                    "ema10": float(bars["ema10"][i]),
                    "ema20": float(bars["ema20"][i]),
                    "market_10gt20": mkt,
                    "ep_gap_pct": ep.gap_pct,
                    "ep_catalyst": "UNKNOWN",
                    "fill_i": i + 1 if str(cfg.qull_fill) == "next_open" else i,
                }

        if sig_payload is not None:
            if int(sig_payload["fill_i"]) >= n:
                # can't fill — watchlist only
                watch.append(
                    {
                        "symbol": symbol,
                        "asof": iso,
                        "setup": sig_payload["setup"],
                        "coil_high": sig_payload["coil_high"],
                        "close": sig_payload["trigger_close"],
                        "dist": 0.0,
                        "prior_run_pct": sig_payload["prior_run_pct"],
                        "coil_range_pct": sig_payload["coil_range_pct"],
                        "notes": "signal_no_fill_bar",
                    }
                )
            else:
                pending = sig_payload

        # Near-coil watch (HTF approaching)
        if do_htf and i >= int(cfg.qull_coil_bars) + int(cfg.qull_prior_run_bars) + 5:
            coil = int(cfg.qull_coil_bars)
            coil_high = float(np.max(bars["h"][i - coil : i]))
            close = float(bars["c"][i])
            if coil_high > 0:
                dist = (coil_high - close) / coil_high * 100.0
                if 0 < dist <= 3.0:
                    watch.append(
                        {
                            "symbol": symbol,
                            "asof": iso,
                            "setup": "HTF_NEAR",
                            "coil_high": coil_high,
                            "close": close,
                            "dist": dist,
                            "prior_run_pct": 0.0,
                            "coil_range_pct": 0.0,
                            "notes": "within_3pct_coil_high",
                        }
                    )

    open_rows: list[dict[str, Any]] = []
    if open_pos is not None:
        last_i = n - 1
        entry_px = float(open_pos["entry_price"])
        cur = float(bars["c"][last_i])
        open_rows.append(
            {
                "symbol": symbol,
                "date_opened": open_pos["date_opened"],
                "entry_price": entry_px,
                "current_price": cur,
                "pnl_pct": (cur / entry_px - 1.0) * 100.0,
                "days_open": _calendar_days(open_pos["date_opened"], bars["dates"][last_i]),
                "stop": float(open_pos["stop_price"]),
                "setup": open_pos["setup"],
                "coil_high": float(open_pos["coil_high"]),
                "trail_ema": trail_n,
            }
        )

    # Keep last few watch rows only
    if len(watch) > 5:
        watch = watch[-5:]
    return QullSymbolResult(symbol, closed, open_rows, watch)


def _worker_backtest(args: tuple[str, pd.DataFrame, dict[str, Any], dict[str, bool]]) -> QullSymbolResult:
    sym, df, cfg_d, mkt = args
    cfg = QullConfig(**cfg_d)
    return backtest_symbol(sym, df, cfg, mkt)


def _run_qull_symbol_tasks(
    tasks: list[tuple[str, pd.DataFrame, dict[str, Any], dict[str, bool]]],
    n_workers: int,
) -> list[QullSymbolResult]:
    if n_workers <= 0 or len(tasks) <= 1:
        return [_worker_backtest(t) for t in tasks]
    out: list[QullSymbolResult] = []
    with ProcessPoolExecutor(max_workers=n_workers) as ex:
        futs = [ex.submit(_worker_backtest, t) for t in tasks]
        for fut in as_completed(futs):
            out.append(fut.result())
    return out


# ---------------------------------------------------------------------------
# Writers + host
# ---------------------------------------------------------------------------


def write_qull_outputs(
    output_dir: Path,
    ts: str,
    closed: list[QullClosedRow],
    open_rows: list[dict[str, Any]],
    watch_rows: list[dict[str, Any]],
    cfg: QullConfig,
    *,
    host_meta: Optional[dict[str, Any]] = None,
    tickers: Optional[dict[str, pd.DataFrame]] = None,
    host_cfg: Any = None,
    no_yfinance: bool = False,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    host_meta = host_meta or {}
    closed_path = output_dir / f"QULL_Closed_{ts}.csv"
    open_path = output_dir / f"QULL_Open_{ts}.csv"
    watch_path = output_dir / f"QULL_Watchlist_{ts}.csv"
    summary_path = output_dir / f"QULL_Summary_{ts}.csv"
    report_path = output_dir / f"QULL_Report_{ts}.csv"
    audit_path = output_dir / f"QULL_Audit_Report_{ts}.csv"

    with closed_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(QULL_CLOSED_HEADER)
        for r in closed:
            w.writerow(r.to_csv_row())

    with open_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(QULL_OPEN_HEADER)
        for r in open_rows:
            w.writerow(
                [
                    r["symbol"],
                    r["date_opened"],
                    f"{r['entry_price']:.4f}",
                    f"{r['current_price']:.4f}",
                    f"{r['pnl_pct']:.4f}",
                    r["days_open"],
                    f"{r['stop']:.4f}",
                    r["setup"],
                    f"{r['coil_high']:.4f}",
                    r["trail_ema"],
                ]
            )

    with watch_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(QULL_WATCHLIST_HEADER)
        for r in watch_rows:
            w.writerow(
                [
                    r["symbol"],
                    r["asof"],
                    r["setup"],
                    f"{r['coil_high']:.4f}",
                    f"{r['close']:.4f}",
                    f"{r['dist']:.2f}",
                    f"{r['prior_run_pct']:.4f}",
                    f"{r['coil_range_pct']:.4f}",
                    r["notes"],
                ]
            )

    by_sym: dict[str, list[QullClosedRow]] = {}
    for r in closed:
        by_sym.setdefault(r.symbol, []).append(r)
    total_pnl_all = sum(r.pnl_dollars for r in closed) or 0.0
    days_per_year = 365.25

    def _first_data_date(sym: str) -> str:
        if not tickers or sym not in tickers:
            return ""
        df = tickers[sym]
        if df is None or len(df) == 0:
            return ""
        try:
            if isinstance(df.index, pd.DatetimeIndex) and len(df.index):
                d0 = df.index[0]
            elif "Date" in df.columns:
                d0 = pd.to_datetime(df["Date"].iloc[0])
            else:
                return ""
            return pd.Timestamp(d0).strftime("%Y-%m-%d")
        except Exception:
            return ""

    with summary_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
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
                "CURRENT_MARKET_CAP",
                "SECTOR",
                "INDUSTRY",
                "FIRST_DATA_DATE",
                "AVG_TRADES_PER_YEAR",
                "MAX_WIN_PCT",
                "MEDIAN_PNL_PCT",
                "AVG_DAYS_HELD",
            ]
        )
        for sym in sorted(by_sym):
            rows = by_sym[sym]
            wins = sum(1 for r in rows if r.pnl_pct > 1e-9)
            losses = sum(1 for r in rows if r.pnl_pct < -1e-9)
            bes = len(rows) - wins - losses
            pnls = [r.pnl_pct for r in rows]
            pnl = sum(r.pnl_dollars for r in rows)
            avg_pct = (sum(pnls) / len(pnls)) if pnls else 0.0
            med_pct = float(np.median(pnls)) if pnls else 0.0
            max_win = max(pnls) if pnls else 0.0
            first = _first_data_date(sym)
            years = 1.0
            if first and rows:
                try:
                    d0 = datetime.strptime(first.replace("-", "")[:8], "%Y%m%d")
                    d1 = datetime.strptime(str(rows[-1].date_closed).replace("-", "")[:8], "%Y%m%d")
                    years = max((d1 - d0).days / days_per_year, 1e-6)
                except Exception:
                    years = 1.0
            w.writerow(
                [
                    sym,
                    len(rows),
                    wins,
                    losses,
                    bes,
                    f"{(100.0 * wins / len(rows)) if rows else 0.0:.1f}%",
                    f"{pnl:.2f}",
                    f"{pnl:.2f}",
                    f"{avg_pct:.2f}%",
                    f"{(100.0 * pnl / total_pnl_all) if total_pnl_all else 0.0:.1f}%",
                    "",
                    "",
                    "",
                    first,
                    f"{(len(rows) / years):.2f}",
                    f"{max_win:.2f}%",
                    f"{med_pct:+.2f}%",
                    f"{(sum(r.days_held for r in rows) / len(rows)) if rows else 0.0:.1f}",
                ]
            )

    n_tr = len(closed)
    wins = sum(1 for r in closed if r.pnl_pct > 0)
    total_pnl = sum(r.pnl_dollars for r in closed)
    avg_pnl = (sum(r.pnl_pct for r in closed) / n_tr) if n_tr else 0.0
    exit_counts: dict[str, int] = {}
    for r in closed:
        exit_counts[r.exit_type] = exit_counts.get(r.exit_type, 0) + 1
    with report_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["metric", "value"])
        w.writerow(["stamp", ts])
        w.writerow(["trades", n_tr])
        w.writerow(["wins", wins])
        w.writerow(["losses", n_tr - wins])
        w.writerow(["pct_wins", f"{(100.0 * wins / n_tr) if n_tr else 0:.2f}"])
        w.writerow(["total_pnl_dollars", f"{total_pnl:.2f}"])
        w.writerow(["avg_pnl_pct", f"{avg_pnl:.2f}"])
        w.writerow(["open_positions", len(open_rows)])
        w.writerow(["Max_Positions", host_meta.get("host_max_positions", "")])
        w.writerow(["brt_cash", host_meta.get("host_brt_cash", getattr(cfg, "brt_cash", ""))])
        w.writerow(["qull_setup", cfg.qull_setup])
        w.writerow(["ep_catalyst_note", "EP_CATALYST=EARNINGS|EARNINGS_SURPRISE|UNKNOWN from yfinance cache (±window)"])
        for k, v in sorted(exit_counts.items()):
            w.writerow([f"exit_{k}", v])

    equity_path = output_dir / f"QULL_EquityCurve_{ts}.csv"
    equity_meta_path = output_dir / f"QULL_EquityMeta_{ts}.csv"
    max_dd = 0.0
    max_dd_pct = 0.0
    aggressive_total = ""
    aggressive_max_dd = ""
    host_equity_written = False
    if tickers is not None and host_cfg is not None and (
        bool(getattr(host_cfg, "aggressive", False)) or bool(host_meta.get("use_host_equity"))
    ):
        equity = compute_and_write_host_equity(
            output_dir=output_dir,
            ts=ts,
            file_prefix="QULL",
            closed=closed,
            open_trades=open_rows,
            tickers=tickers,
            cfg=host_cfg,
        )
        if equity:
            host_equity_written = True
            md = equity.get("Max_Drawdown", "")
            try:
                max_dd_pct = float(str(md).replace("%", "").strip())
                max_dd = max_dd_pct / 100.0
            except (TypeError, ValueError):
                pass
            if equity.get("_aggressive"):
                aggressive_total = f"{float(equity.get('_equity_total_pnl', 0) or 0):.2f}"
                aggressive_max_dd = str(equity.get("Aggressive_Max_Drawdown", "") or "")

    if not host_equity_written:
        by_date: dict[str, float] = {}
        for r in closed:
            d = str(r.date_closed or "").strip().replace("-", "")
            if len(d) >= 8 and d[:8].isdigit():
                iso = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
            else:
                iso = str(r.date_closed or "").strip()
            if not iso:
                continue
            by_date[iso] = by_date.get(iso, 0.0) + float(r.pnl_dollars)
        init_cash = float(host_meta.get("host_brt_cash") or getattr(cfg, "brt_cash", 0) or 47500.0)
        equity_val = init_cash
        peak = equity_val
        max_dd = 0.0
        eq_rows: list[dict[str, Any]] = []
        for d in sorted(by_date):
            equity_val += by_date[d]
            if equity_val > peak:
                peak = equity_val
            dd = ((peak - equity_val) / peak) if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
            eq_rows.append({"Date": d, "Equity": equity_val, "Positions": ""})
        if not eq_rows:
            eq_rows.append({"Date": "", "Equity": init_cash, "Positions": ""})
        pd.DataFrame(eq_rows).to_csv(equity_path, index=False)
        max_dd_pct = max_dd * 100.0
        pd.DataFrame(
            [
                {
                    "Initial_Account_Size": init_cash,
                    "Max_Drawdown_fraction": max_dd,
                    "Max_Drawdown_pct": f"{max_dd_pct:.2f}%",
                    "Aggressive": False,
                    "Curve_Kind": "realized_pnl_by_exit_date",
                }
            ]
        ).to_csv(equity_meta_path, index=False)

    try:
        from brt_audit_columns import empty_audit_row, write_wide_audit_csv
    except ImportError:
        from stock_analysis.brt_audit_columns import empty_audit_row, write_wide_audit_csv  # type: ignore

    link = f"https://drive.google.com/drive/search?q={ts}"
    row = empty_audit_row()
    row["Timestamp_Drive"] = f'=hyperlink("{link}","{ts}")'
    row["qull_mode"] = "true"
    row["mvcp_mode"] = "false"
    row["sb_mode"] = "false"
    row["rs_mode"] = "false"
    row["rl_mode"] = "false"
    row["mts_mode"] = "false"
    for fdef in fields(QullConfig):
        if fdef.name in row:
            row[fdef.name] = getattr(cfg, fdef.name)
    if host_cfg is not None:
        for k in (
            "initial_capital",
            "aggressive",
            "aggressive_max_multiple",
            "margin_utilization",
            "max_positions",
            "aggressive_margin_interest",
            "aggressive_avg_positions",
            "aggressive_sizing_equity_cap",
        ):
            if hasattr(host_cfg, k) and k in row:
                row[k] = getattr(host_cfg, k)
    losses = n_tr - wins
    row["Total_Trades"] = n_tr
    row["Wins"] = wins
    row["Losses"] = losses
    row["BE"] = 0
    row["Pct_Wins"] = f"{(100.0 * wins / n_tr) if n_tr else 0:.2f}"
    row["Pct_Losses"] = f"{(100.0 * losses / n_tr) if n_tr else 0:.2f}"
    row["Total_PNL"] = host_meta.get("total_pnl_audit_1m", f"{total_pnl:.2f}")
    row["Avg_PNL_Pct"] = f"{avg_pnl:.2f}"
    row["Max_Positions"] = host_meta.get("host_max_positions", "")
    row["brt_cash"] = host_meta.get(
        "host_audit_brt_cash", host_meta.get("host_brt_cash", getattr(cfg, "brt_cash", ""))
    )
    row["Aggressive_Total_PNL"] = aggressive_total or host_meta.get("aggressive_total_pnl", "")
    row["Aggressive_Max_DD"] = aggressive_max_dd or host_meta.get("aggressive_max_dd", "")
    row["Max_DD"] = f"{max_dd_pct:.2f}"
    write_wide_audit_csv(audit_path, row)

    corr_path = output_dir / f"QULL_Correlation_{ts}.csv"
    try:
        import sys

        _sa = Path(__file__).resolve().parent
        if str(_sa) not in sys.path:
            sys.path.insert(0, str(_sa))
        from correlate_brt_closed import run_correlation_report

        run_correlation_report(str(closed_path), str(corr_path))
    except Exception as e:
        print(f"[QULL] Correlation skipped: {e}", flush=True)

    try:
        import sys

        _sa = Path(__file__).resolve().parent
        if str(_sa) not in sys.path:
            sys.path.insert(0, str(_sa))
        try:
            from rocket_post_analysis import write_analysis_artifacts
        except ImportError:
            from stock_analysis.rocket_post_analysis import write_analysis_artifacts  # type: ignore
        write_analysis_artifacts(
            cfg=None,
            tickers=tickers or {},
            output_dir=output_dir,
            ts=ts,
            closed_path=closed_path,
            summary_path=summary_path,
            open_path=open_path,
            prefix="QULL",
            no_yfinance=bool(no_yfinance),
        )
    except Exception as e:
        print(f"[QULL] analysis artifacts skipped: {e}", flush=True)

    for src, name in (
        (closed_path, "QULL_LatestRun_Closed.csv"),
        (open_path, "QULL_LatestRun_Open.csv"),
        (summary_path, "QULL_LatestRun_Summary.csv"),
        (watch_path, "QULL_LatestRun_Watchlist.csv"),
        (audit_path, "QULL_LatestRun_Audit_Report.csv"),
        (equity_path, "QULL_LatestRun_EquityCurve.csv"),
    ):
        (output_dir / name).write_bytes(src.read_bytes())

    (output_dir / "QULL_last_run_ts.txt").write_text(ts + "\n", encoding="utf-8")
    (output_dir / "last_run_ts.txt").write_text(ts, encoding="utf-8")
    return {
        "closed": closed_path,
        "open": open_path,
        "watchlist": watch_path,
        "summary": summary_path,
        "report": report_path,
        "audit": audit_path,
        "equity_curve": equity_path,
        "equity_meta": equity_meta_path,
    }


def run_qull_from_brt_main(
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
    del drive_link
    qcfg = qull_config_from_brt(cfg)
    n_workers = max(0, int(workers or 0))
    print(
        f"[QULL] Qullamaggie HTF/EP on {len(ticker_list)} symbols "
        f"(setup={qcfg.qull_setup}, prior_run>={qcfg.qull_prior_run_pct:.0%}, "
        f"coil_range<={qcfg.qull_coil_range_pct:.0%}, trail_ema={qcfg.qull_trail_ema}, "
        f"workers={n_workers})",
        flush=True,
    )
    print(
        "[QULL] HTF primary; EP proxy gap/volume + optional EP_CATALYST from yfinance cache. "
        "Exit: STOP/GAP -> TRAIL_EMA.",
        flush=True,
    )

    market_ok = {}
    if bool(qcfg.qull_market_filter):
        market_ok = load_spy_market_ok(Path(data_dir), load_symbol_fn)
        print(f"[QULL] SPY market filter bars={len(market_ok)}", flush=True)

    all_closed: list[QullClosedRow] = []
    all_open: list[dict[str, Any]] = []
    all_watch: list[dict[str, Any]] = []
    loaded: dict[str, pd.DataFrame] = {}
    skipped: list[str] = []
    cfg_d = _qull_cfg_dict(qcfg)
    tasks: list[tuple[str, pd.DataFrame, dict[str, Any], dict[str, bool]]] = []

    for sym in ticker_list:
        if str(sym).upper() == "SPY":
            continue
        df = tickers.get(sym) if tickers else None
        if df is None or (hasattr(df, "empty") and df.empty):
            if load_symbol_fn is not None:
                try:
                    df = load_symbol_fn(sym, data_dir)
                except Exception as e:
                    print(f"[QULL] skip {sym}: load failed ({e})", flush=True)
                    skipped.append(sym)
                    continue
        if df is None or len(df) < 80:
            skipped.append(sym)
            continue
        loaded[sym] = df
        tasks.append((sym, df, cfg_d, market_ok))

    t_bt = time.time()
    results = _run_qull_symbol_tasks(tasks, n_workers)
    for res in results:
        if res.skip_reason:
            skipped.append(res.symbol)
            continue
        all_closed.extend(res.closed)
        all_open.extend(res.open_rows)
        all_watch.extend(res.watch)
    print(f"[QULL] Symbol backtest {time.time() - t_bt:.1f}s (workers={n_workers})", flush=True)

    all_closed.sort(key=lambda r: (r.date_opened, r.symbol))
    try:
        _enrich_qull_ep_catalyst(
            all_closed, tickers=loaded, cfg=qcfg, no_yfinance=bool(no_yfinance)
        )
    except Exception as e:
        print(f"[QULL] EP catalyst enrich skipped: {e}", flush=True)

    host_meta: dict[str, Any] = {}
    hcfg = HostSizingConfig(
        brt_cash=float(getattr(cfg, "brt_cash", qcfg.brt_cash) or qcfg.brt_cash),
        initial_capital=float(getattr(cfg, "initial_capital", 500_000) or 500_000),
        aggressive_max_multiple=float(getattr(cfg, "aggressive_max_multiple", 2.0) or 2.0),
        margin_utilization=float(getattr(cfg, "margin_utilization", 0.6) or 0.6),
        max_positions=int(getattr(cfg, "max_positions", 0) or 0),
        aggressive=bool(getattr(cfg, "aggressive", False)),
        aggressive_margin_interest=float(getattr(cfg, "aggressive_margin_interest", 0.10) or 0.10),
        aggressive_avg_positions=float(getattr(cfg, "aggressive_avg_positions", 0) or 0),
        aggressive_sizing_equity_cap=float(getattr(cfg, "aggressive_sizing_equity_cap", 10.0) or 10.0),
        aggressive_sell=str(getattr(cfg, "aggressive_sell", "false") or "false"),
        equity_fast_aggressive=bool(getattr(cfg, "equity_fast_aggressive", False)),
    )
    if all_closed:
        adj, scale, max_pos = apply_host_dollar_scale(all_closed, all_open, hcfg)
        qcfg.brt_cash = adj
        host_meta = {
            "host_max_positions": max_pos,
            "host_brt_cash": adj,
            "host_pnl_scale": scale,
            "host_audit_brt_cash": audit_display_brt_cash(max_pos),
        }
        audit_cash = float(host_meta["host_audit_brt_cash"])
        closed_pnl = sum(r.pnl_dollars for r in all_closed)
        audit_pnl = closed_pnl * (audit_cash / adj) if adj > 0 else closed_pnl
        host_meta["total_pnl_audit_1m"] = f"{audit_pnl:.2f}"
        print(
            f"[QULL] Host dollar-scale: PNL_DOLLARS × {scale:.6g}; "
            f"brt_cash -> {adj:,.0f} (max_pos={max_pos})",
            flush=True,
        )

    paths = write_qull_outputs(
        Path(output_dir),
        ts,
        all_closed,
        all_open,
        all_watch,
        qcfg,
        host_meta=host_meta,
        tickers=loaded,
        host_cfg=hcfg,
        no_yfinance=bool(no_yfinance),
    )
    wins = sum(1 for r in all_closed if r.pnl_pct > 0)
    losses = sum(1 for r in all_closed if r.pnl_pct <= 0)
    total_pnl = sum(r.pnl_dollars for r in all_closed)
    print(
        f"[QULL] Closed: {paths['closed']} ({len(all_closed)} trades, {wins}W/{losses}L, "
        f"PnL=${total_pnl:.2f})",
        flush=True,
    )
    print(f"[QULL] Open: {paths['open']} ({len(all_open)} positions)", flush=True)
    print(f"[QULL] Summary: {paths['summary']}", flush=True)
    if skipped:
        print(f"[QULL] Skipped symbols: {','.join(skipped[:40])}{'...' if len(skipped) > 40 else ''}", flush=True)
    return 0
