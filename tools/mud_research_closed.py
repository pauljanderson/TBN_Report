#!/usr/bin/env python3
"""MUD (Most Up / Most Down) — research Closed producer (TBN-style).

Research only. Not DailyRun.

Default freeze (lean keep from mud_lookback_rebalance_20261005):
  lookback L = 5 trading days, rebalance R = 1 trading day.

Writes a Closed CSV with house-style fields plus MUD diagnostics:
  buy/sell percentile of lookback return, lookback return, universe size,
  volume / rel-vol / ATR / RSI / 52w distance, market cap / sector / industry.

Usage:
  python tools/mud_research_closed.py
  python tools/mud_research_closed.py --lookback 5 --rebalance 1 --workers 1
  python tools/mud_research_closed.py --limit 80   # smoke
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import json
import math
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import duckdb
import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
_PE = _REPO / "drive" / "paul_experiments"
_TOOLS = _REPO / "tools"
for _p in (_PE, _TOOLS, _REPO, _REPO / "stock_analysis"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from compare_format import DEFAULT_INITIAL_ACCOUNT, ann_ror_from_closed  # noqa: E402
from report_page_extras import (  # noqa: E402
    RESPONSIVE_TABLE_CSS,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)

# Reuse ranking helpers from the grid runner
from mud_lookback_rebalance_ab import (  # noqa: E402
    DECILE_FRAC,
    EXCLUDE_SYMBOLS,
    MIN_RANK_NAMES,
    lookback_returns,
    pick_deciles,
)

DEFAULT_DB = _REPO / "data" / "ohlcv.duckdb"
FUND_DB = _REPO / "drive" / "fundamentals_cache.duckdb"
IS_CUT = date(2024, 1, 1)
DEFAULT_L = 5
DEFAULT_R = 1
INITIAL_CAPITAL = float(DEFAULT_INITIAL_ACCOUNT)
PANEL_MIN_BARS = 60


def stamp_dir(lookback: int, rebalance: int) -> Path:
    return _PE / f"mud_system_L{lookback}_R{rebalance}_20261005"


@dataclass
class MudClosedRow:
    symbol: str
    side: str
    date_opened: date
    entry_price: float
    date_closed: date
    exit_price: float
    exit_type: str
    days_held: int
    trading_days_held: int
    pnl_pct: float
    pnl_dollars: float
    shares: float
    entry_notional: float
    lookback: int
    rebalance: int
    signal_date: date
    lookback_return_pct: float
    rank_percentile: float  # 0=most down, 100=most up among ranked names that day
    rank_index: int  # 0-based among ranked (ascending return)
    n_ranked: int
    sleeve_size: int
    # Predictive (known on signal close, before next-open fill)
    volume_at_trigger: Optional[float] = None
    avg_volume_10d_at_trigger: Optional[float] = None
    rel_vol_at_trigger: Optional[float] = None
    atr_14_at_trigger: Optional[float] = None
    atr_pct_at_trigger: Optional[float] = None
    rsi14_at_trigger: Optional[float] = None
    high_52w_at_trigger: Optional[float] = None
    dist_to_52w_high_pct_at_trigger: Optional[float] = None
    # Indicative (at entry fill bar)
    volume_at_entry: Optional[float] = None
    avg_volume_10d_at_entry: Optional[float] = None
    rel_vol_at_entry: Optional[float] = None
    atr_14_at_entry: Optional[float] = None
    atr_pct_at_entry: Optional[float] = None
    rsi14_at_entry: Optional[float] = None
    high_52w_at_entry: Optional[float] = None
    dist_to_52w_high_pct: Optional[float] = None
    market_cap: Optional[float] = None
    sector: str = ""
    industry: str = ""
    beta: Optional[float] = None
    float_shares: Optional[float] = None
    short_percent_of_float: Optional[float] = None
    max_price: Optional[float] = None
    min_price: Optional[float] = None


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
    "TRADING_DAYS_HELD",
    "PNL_PCT",
    "PNL_DOLLARS",
    "ANN_ROR_PCT",
    "SHARES",
    "ENTRY_NOTIONAL",
    "MAX_PRICE",
    "MIN_PRICE",
    "LOOKBACK",
    "REBALANCE",
    "SIGNAL_DATE",
    "LOOKBACK_RETURN_PCT",
    "RANK_PERCENTILE",
    "RANK_INDEX",
    "N_RANKED",
    "SLEEVE_SIZE",
    # Trigger / signal bar (predictive)
    "VOLUME_AT_TRIGGER",
    "AVG_VOLUME_10D_AT_TRIGGER",
    "REL_VOL_AT_TRIGGER",
    "ATR_14_AT_TRIGGER",
    "ATR_PCT_AT_TRIGGER",
    "RSI14_AT_TRIGGER",
    "HIGH_52W_AT_TRIGGER",
    "DIST_TO_52W_HIGH_PCT_AT_TRIGGER",
    # Entry / fill bar (indicative)
    "VOLUME_AT_ENTRY",
    "AVG_VOLUME_10D_AT_ENTRY",
    "REL_VOL_AT_ENTRY",
    "ATR_14_AT_ENTRY",
    "ATR_PCT_AT_ENTRY",
    "RSI14_AT_ENTRY",
    "HIGH_52W_AT_ENTRY",
    "DIST_TO_52W_HIGH_PCT",
    "MARKET_CAP",
    "SECTOR",
    "INDUSTRY",
    "BETA",
    "FLOAT_SHARES",
    "SHORT_PERCENT_OF_FLOAT",
    "SYSTEM",
]


def _wilder_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(close)
    out = np.full(n, np.nan, dtype=float)
    if n < period + 1:
        return out
    prev_c = close[:-1]
    tr = np.maximum(high[1:] - low[1:], np.maximum(np.abs(high[1:] - prev_c), np.abs(low[1:] - prev_c)))
    atr = np.full(len(tr), np.nan, dtype=float)
    if len(tr) < period:
        return out
    seed = tr[:period]
    seed = seed[np.isfinite(seed)]
    atr[period - 1] = float(np.mean(seed)) if len(seed) else np.nan
    for i in range(period, len(tr)):
        prev = atr[i - 1]
        if not np.isfinite(prev):
            sl = tr[i - period + 1 : i + 1]
            sl = sl[np.isfinite(sl)]
            atr[i] = float(np.mean(sl)) if len(sl) else np.nan
        else:
            cur = tr[i]
            if not np.isfinite(cur):
                atr[i] = prev
            else:
                atr[i] = (prev * (period - 1) + cur) / period
    out[1:] = atr
    return out


def _wilder_rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(close)
    out = np.full(n, np.nan, dtype=float)
    if n < period + 1:
        return out
    delta = np.diff(close)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_g = float(np.mean(gain[:period]))
    avg_l = float(np.mean(loss[:period]))
    if avg_l == 0:
        out[period] = 100.0 if avg_g > 0 else 50.0
    else:
        rs = avg_g / avg_l
        out[period] = 100.0 - (100.0 / (1.0 + rs))
    for i in range(period, len(delta)):
        avg_g = (avg_g * (period - 1) + gain[i]) / period
        avg_l = (avg_l * (period - 1) + loss[i]) / period
        if avg_l == 0:
            out[i + 1] = 100.0 if avg_g > 0 else 50.0
        else:
            rs = avg_g / avg_l
            out[i + 1] = 100.0 - (100.0 / (1.0 + rs))
    return out


def load_panel(
    db_path: Path,
    *,
    min_bars: int,
    limit: Optional[int] = None,
) -> tuple[pd.DatetimeIndex, dict[str, np.ndarray], list[str]]:
    con = duckdb.connect(str(db_path), read_only=True)
    df = con.execute(
        """
        SELECT symbol, date, open, high, low, close, volume
        FROM prices
        WHERE symbol IS NOT NULL
        ORDER BY date, symbol
        """
    ).fetchdf()
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    df["symbol"] = df["symbol"].astype(str).str.upper()
    df = df[~df["symbol"].isin(EXCLUDE_SYMBOLS)]
    close_w = df.pivot(index="date", columns="symbol", values="close").sort_index()
    keep = [c for c in close_w.columns if int(close_w[c].notna().sum()) >= min_bars]
    keep.sort()
    if limit is not None and limit > 0:
        keep = keep[: int(limit)]
    arrays: dict[str, np.ndarray] = {}
    for col in ("open", "high", "low", "close", "volume"):
        w = df.pivot(index="date", columns="symbol", values=col).sort_index()
        arrays[col] = w.reindex(columns=keep).to_numpy(dtype=float)
    return close_w.index, arrays, keep


def load_fundamentals(db_path: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not db_path.exists():
        return out
    import json as _json

    try:
        con = duckdb.connect(str(db_path), read_only=True)
        cols = {r[0] for r in con.execute("DESCRIBE yf_symbol_info").fetchall()}
        select_cols = ["symbol", "market_cap", "float_shares", "short_percent_of_float", "raw_json"]
        has_beta_col = "beta" in cols
        if has_beta_col:
            select_cols.append("beta")
        rows = con.execute(
            "SELECT " + ", ".join(select_cols) + " FROM yf_symbol_info"
        ).fetchall()
        con.close()
    except Exception:
        return out

    for row in rows:
        sym = str(row[0]).upper()
        mc, fl, short_pct, raw = row[1], row[2], row[3], row[4]
        beta = row[5] if has_beta_col and len(row) > 5 else None
        sector = industry = ""
        if raw:
            try:
                d = _json.loads(raw)
                sector = str(d.get("sector") or "")
                industry = str(d.get("industry") or "")
                if beta is None:
                    beta = d.get("beta")
            except Exception:
                pass

        def _f(x: Any) -> Optional[float]:
            if x is None:
                return None
            try:
                v = float(x)
            except (TypeError, ValueError):
                return None
            return v if np.isfinite(v) else None

        out[sym] = {
            "market_cap": _f(mc),
            "float_shares": _f(fl),
            "short_percent_of_float": _f(short_pct),
            "beta": _f(beta),
            "sector": sector,
            "industry": industry,
        }
    return out


def _bar_stats(
    *,
    sj: int,
    bar: int,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    atr_cache: dict[int, np.ndarray],
    rsi_cache: dict[int, np.ndarray],
    px_for_pct: Optional[float] = None,
) -> dict[str, Optional[float]]:
    """Volume / ATR / RSI / 52w at a bar. ATR% and 52w distance use px_for_pct (or bar close)."""
    vol = volume[:, sj]
    hi = high[:, sj]
    lo = low[:, sj]
    cl = close[:, sj]
    if bar < 0 or bar >= len(cl):
        return {
            "volume": None,
            "avg_volume_10d": None,
            "rel_vol": None,
            "atr_14": None,
            "atr_pct": None,
            "rsi14": None,
            "high_52w": None,
            "dist_to_52w_high_pct": None,
        }
    v_bar = float(vol[bar]) if np.isfinite(vol[bar]) else None
    start = max(0, bar - 9)
    window = vol[start : bar + 1]
    window = window[np.isfinite(window) & (window >= 0)]
    avg10 = float(np.mean(window)) if len(window) else None
    rel = (v_bar / avg10) if (v_bar is not None and avg10 and avg10 > 0) else None
    if sj not in atr_cache:
        atr_cache[sj] = _wilder_atr(hi, lo, cl)
    if sj not in rsi_cache:
        rsi_cache[sj] = _wilder_rsi(cl)
    atr = atr_cache[sj][bar]
    atr_v = float(atr) if np.isfinite(atr) else None
    px = px_for_pct
    if px is None or not (np.isfinite(px) and px > 0):
        px = float(cl[bar]) if np.isfinite(cl[bar]) and cl[bar] > 0 else None
    atr_pct = (atr_v / px * 100.0) if (atr_v is not None and px and px > 0) else None
    rsi = rsi_cache[sj][bar]
    rsi_v = float(rsi) if np.isfinite(rsi) else None
    w0 = max(0, bar - 251)
    hh = hi[w0 : bar + 1]
    hh = hh[np.isfinite(hh)]
    h52 = float(np.max(hh)) if len(hh) else None
    dist52 = ((h52 - px) / h52 * 100.0) if (h52 and h52 > 0 and px and px > 0) else None
    return {
        "volume": v_bar,
        "avg_volume_10d": avg10,
        "rel_vol": rel,
        "atr_14": atr_v,
        "atr_pct": atr_pct,
        "rsi14": rsi_v,
        "high_52w": h52,
        "dist_to_52w_high_pct": dist52,
    }


def run_mud_closed(
    *,
    cal: pd.DatetimeIndex,
    arrays: dict[str, np.ndarray],
    symbols: list[str],
    lookback: int,
    rebalance: int,
    fund: dict[str, dict[str, Any]],
    initial_capital: float = INITIAL_CAPITAL,
) -> tuple[list[MudClosedRow], list[dict[str, Any]], list[dict[str, Any]]]:
    open_ = arrays["open"]
    high = arrays["high"]
    low = arrays["low"]
    close = arrays["close"]
    volume = arrays["volume"]
    T, _S = close.shape
    half = initial_capital / 2.0
    cash = float(initial_capital)
    # holdings: sj, shares, side, entry_date, entry_px, entry_notional, signal_date,
    #           lookback_ret, rank_pct, rank_idx, n_ranked, sleeve_size, entry_ti, signal_ti
    holdings: list[tuple] = []
    closed: list[MudClosedRow] = []
    equity_rows: list[dict[str, Any]] = []
    atr_cache: dict[int, np.ndarray] = {}
    rsi_cache: dict[int, np.ndarray] = {}

    warmup = lookback + 1
    signal_idxs = list(range(warmup, T - 1, rebalance))
    fill_to_signal = {si + 1: si for si in signal_idxs if si + 1 < T}
    fill_set = set(fill_to_signal.keys())
    if not fill_set:
        return [], [], []

    def mtm(ti: int) -> float:
        eq = cash
        for h in holdings:
            sj, sh, side = h[0], h[1], h[2]
            px = close[ti, sj]
            if not (np.isfinite(px) and px > 0):
                continue
            if side == "long":
                eq += sh * px
            else:
                eq -= sh * px
        return eq

    def liquidate_all(ti: int, reason: str, use_open: bool) -> None:
        nonlocal cash, holdings
        px_row = open_[ti, :] if use_open else close[ti, :]
        kept: list[tuple] = []
        for h in holdings:
            (
                sj,
                sh,
                side,
                ed,
                ep,
                enot,
                sig_d,
                lb_ret,
                rank_pct,
                rank_idx,
                n_ranked,
                sleeve_n,
                entry_ti,
                signal_ti,
            ) = h
            px = px_row[sj]
            if not (np.isfinite(px) and px > 0):
                px = close[ti, sj]
            if not (np.isfinite(px) and px > 0):
                kept.append(h)
                continue
            fill = float(px)
            xd = cal[ti].date()
            if side == "long":
                proceeds = sh * fill
                cash += proceeds
                pnl = proceeds - enot
                pnl_pct = (fill / ep - 1.0) * 100.0 if ep else 0.0
            else:
                cost = sh * fill
                cash -= cost
                pnl = enot - cost
                pnl_pct = (ep / fill - 1.0) * 100.0 if fill else 0.0
            # max/min while held (trading bars entry_ti .. ti)
            hi_sl = high[entry_ti : ti + 1, sj]
            lo_sl = low[entry_ti : ti + 1, sj]
            hi_ok = hi_sl[np.isfinite(hi_sl)]
            lo_ok = lo_sl[np.isfinite(lo_sl)]
            max_px = float(np.max(hi_ok)) if len(hi_ok) else None
            min_px = float(np.min(lo_ok)) if len(lo_ok) else None
            # Signal close is known before the fill — use signal close for % fields.
            sig_close = (
                float(close[signal_ti, sj])
                if np.isfinite(close[signal_ti, sj]) and close[signal_ti, sj] > 0
                else None
            )
            trig = _bar_stats(
                sj=sj,
                bar=signal_ti,
                high=high,
                low=low,
                close=close,
                volume=volume,
                atr_cache=atr_cache,
                rsi_cache=rsi_cache,
                px_for_pct=sig_close,
            )
            ent = _bar_stats(
                sj=sj,
                bar=entry_ti,
                high=high,
                low=low,
                close=close,
                volume=volume,
                atr_cache=atr_cache,
                rsi_cache=rsi_cache,
                px_for_pct=ep,
            )
            f = fund.get(symbols[sj], {})
            closed.append(
                MudClosedRow(
                    symbol=symbols[sj],
                    side=side,
                    date_opened=ed,
                    entry_price=ep,
                    date_closed=xd,
                    exit_price=fill,
                    exit_type=reason,
                    days_held=max(1, (xd - ed).days),
                    trading_days_held=max(1, ti - entry_ti),
                    pnl_pct=pnl_pct,
                    pnl_dollars=pnl,
                    shares=sh,
                    entry_notional=enot,
                    lookback=lookback,
                    rebalance=rebalance,
                    signal_date=sig_d,
                    lookback_return_pct=lb_ret,
                    rank_percentile=rank_pct,
                    rank_index=rank_idx,
                    n_ranked=n_ranked,
                    sleeve_size=sleeve_n,
                    volume_at_trigger=trig["volume"],
                    avg_volume_10d_at_trigger=trig["avg_volume_10d"],
                    rel_vol_at_trigger=trig["rel_vol"],
                    atr_14_at_trigger=trig["atr_14"],
                    atr_pct_at_trigger=trig["atr_pct"],
                    rsi14_at_trigger=trig["rsi14"],
                    high_52w_at_trigger=trig["high_52w"],
                    dist_to_52w_high_pct_at_trigger=trig["dist_to_52w_high_pct"],
                    volume_at_entry=ent["volume"],
                    avg_volume_10d_at_entry=ent["avg_volume_10d"],
                    rel_vol_at_entry=ent["rel_vol"],
                    atr_14_at_entry=ent["atr_14"],
                    atr_pct_at_entry=ent["atr_pct"],
                    rsi14_at_entry=ent["rsi14"],
                    high_52w_at_entry=ent["high_52w"],
                    dist_to_52w_high_pct=ent["dist_to_52w_high_pct"],
                    market_cap=f.get("market_cap"),
                    sector=str(f.get("sector") or ""),
                    industry=str(f.get("industry") or ""),
                    beta=f.get("beta"),
                    float_shares=f.get("float_shares"),
                    short_percent_of_float=f.get("short_percent_of_float"),
                    max_price=max_px,
                    min_price=min_px,
                )
            )
        holdings = kept

    def rank_meta(scores: np.ndarray, sj: int) -> tuple[float, float, int, int]:
        """Return lookback_ret%, percentile (0=most down), rank_index, n_ranked."""
        ok = np.isfinite(scores)
        idx = np.where(ok)[0]
        if len(idx) < 2 or sj not in set(idx.tolist()):
            sc = float(scores[sj]) if np.isfinite(scores[sj]) else float("nan")
            return sc * 100.0 if np.isfinite(sc) else float("nan"), float("nan"), -1, int(len(idx))
        sc_all = scores[idx]
        order = np.argsort(sc_all)  # ascending
        # position of sj in ascending order
        pos = int(np.where(idx[order] == sj)[0][0])
        n = len(idx)
        # percentile: 0 = most down, 100 = most up
        pct = 100.0 * pos / max(1, n - 1)
        return float(scores[sj]) * 100.0, pct, pos, n

    first_fill = min(fill_set)
    for ti in range(first_fill, T):
        if ti in fill_set:
            si = fill_to_signal[ti]
            liquidate_all(ti, "rebalance", use_open=True)
            scores = lookback_returns(close, si, lookback)
            longs, shorts = pick_deciles(scores, close[si, :])
            side_budget = cash / 2.0 if cash > 0 else half
            sig_d = cal[si].date()
            for sj, _sc in longs:
                opx = open_[ti, sj]
                if not (np.isfinite(opx) and opx > 0):
                    continue
                fill = float(opx)
                dollars = side_budget / len(longs) if longs else 0.0
                shares = dollars / fill
                if shares <= 0:
                    continue
                cost = shares * fill
                if cost > cash + 1e-6:
                    shares = cash / fill
                    cost = shares * fill
                cash -= cost
                lb_ret, rank_pct, rank_idx, n_ranked = rank_meta(scores, sj)
                holdings.append(
                    (
                        sj,
                        shares,
                        "long",
                        cal[ti].date(),
                        fill,
                        cost,
                        sig_d,
                        lb_ret,
                        rank_pct,
                        rank_idx,
                        n_ranked,
                        len(longs),
                        ti,
                        si,
                    )
                )
            for sj, _sc in shorts:
                opx = open_[ti, sj]
                if not (np.isfinite(opx) and opx > 0):
                    continue
                fill = float(opx)
                dollars = side_budget / len(shorts) if shorts else 0.0
                shares = dollars / fill
                if shares <= 0:
                    continue
                proceeds = shares * fill
                cash += proceeds
                lb_ret, rank_pct, rank_idx, n_ranked = rank_meta(scores, sj)
                holdings.append(
                    (
                        sj,
                        shares,
                        "short",
                        cal[ti].date(),
                        fill,
                        proceeds,
                        sig_d,
                        lb_ret,
                        rank_pct,
                        rank_idx,
                        n_ranked,
                        len(shorts),
                        ti,
                        si,
                    )
                )
        equity_rows.append(
            {
                "date": cal[ti].date().isoformat(),
                "equity": mtm(ti),
                "cash": cash,
                "n_positions": len(holdings),
            }
        )

    open_rows: list[dict[str, Any]] = []
    if holdings:
        # Snapshot open book before final liquidate
        for h in holdings:
            (
                sj,
                sh,
                side,
                ed,
                ep,
                enot,
                sig_d,
                lb_ret,
                rank_pct,
                rank_idx,
                n_ranked,
                sleeve_n,
                entry_ti,
                signal_ti,
            ) = h
            last_ti = T - 1
            px = close[last_ti, sj]
            if not (np.isfinite(px) and px > 0):
                continue
            if side == "long":
                upnl = sh * float(px) - enot
                upnl_pct = (float(px) / ep - 1.0) * 100.0 if ep else 0.0
            else:
                upnl = enot - sh * float(px)
                upnl_pct = (ep / float(px) - 1.0) * 100.0 if px else 0.0
            open_rows.append(
                {
                    "SYMBOL": symbols[sj],
                    "SIDE": side,
                    "DATE_OPENED": ed.isoformat(),
                    "ENTRY_PRICE": round(ep, 6),
                    "LAST_PRICE": round(float(px), 6),
                    "SHARES": round(sh, 6),
                    "UNREALIZED_PNL": round(upnl, 4),
                    "UNREALIZED_PNL_PCT": round(upnl_pct, 6),
                    "LOOKBACK_RETURN_PCT": round(lb_ret, 6) if np.isfinite(lb_ret) else "",
                    "RANK_PERCENTILE": round(rank_pct, 4) if np.isfinite(rank_pct) else "",
                    "SIGNAL_DATE": sig_d.isoformat(),
                    "SYSTEM": "MUD",
                }
            )
        liquidate_all(T - 1, "end_of_backtest", use_open=False)

    return closed, open_rows, equity_rows


def _fmt_opt(v: Any, nd: int = 4) -> str:
    if v is None:
        return ""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return str(v)
    if not np.isfinite(x):
        return ""
    return f"{x:.{nd}f}"


def row_to_csv(r: MudClosedRow) -> dict[str, Any]:
    ann_s = ""
    if r.days_held and r.days_held > 0:
        try:
            base = 1.0 + r.pnl_pct / 100.0
            if base > 0:
                ann = (base ** (365.0 / r.days_held) - 1.0) * 100.0
                if np.isfinite(ann) and abs(ann) < 1e12:
                    ann_s = f"{ann:.2f}%"
        except (OverflowError, ValueError):
            ann_s = ""
    return {
        "SYMBOL": r.symbol,
        "SIDE": r.side,
        "DATE_OPENED": r.date_opened.isoformat(),
        "ENTRY_PRICE": f"{r.entry_price:.6f}",
        "STOP_PRICE": "",
        "TARGET_PRICE": "",
        "DATE_CLOSED": r.date_closed.isoformat(),
        "EXIT_PRICE": f"{r.exit_price:.6f}",
        "EXIT_TYPE": r.exit_type,
        "DAYS_HELD": r.days_held,
        "TRADING_DAYS_HELD": r.trading_days_held,
        "PNL_PCT": f"{r.pnl_pct:.6f}",
        "PNL_DOLLARS": f"{r.pnl_dollars:.4f}",
        "ANN_ROR_PCT": ann_s,
        "SHARES": f"{r.shares:.6f}",
        "ENTRY_NOTIONAL": f"{r.entry_notional:.4f}",
        "MAX_PRICE": _fmt_opt(r.max_price, 6),
        "MIN_PRICE": _fmt_opt(r.min_price, 6),
        "LOOKBACK": r.lookback,
        "REBALANCE": r.rebalance,
        "SIGNAL_DATE": r.signal_date.isoformat(),
        "LOOKBACK_RETURN_PCT": _fmt_opt(r.lookback_return_pct, 6),
        "RANK_PERCENTILE": _fmt_opt(r.rank_percentile, 4),
        "RANK_INDEX": r.rank_index,
        "N_RANKED": r.n_ranked,
        "SLEEVE_SIZE": r.sleeve_size,
        "VOLUME_AT_TRIGGER": _fmt_opt(r.volume_at_trigger, 2),
        "AVG_VOLUME_10D_AT_TRIGGER": _fmt_opt(r.avg_volume_10d_at_trigger, 2),
        "REL_VOL_AT_TRIGGER": _fmt_opt(r.rel_vol_at_trigger, 4),
        "ATR_14_AT_TRIGGER": _fmt_opt(r.atr_14_at_trigger, 6),
        "ATR_PCT_AT_TRIGGER": _fmt_opt(r.atr_pct_at_trigger, 4),
        "RSI14_AT_TRIGGER": _fmt_opt(r.rsi14_at_trigger, 4),
        "HIGH_52W_AT_TRIGGER": _fmt_opt(r.high_52w_at_trigger, 6),
        "DIST_TO_52W_HIGH_PCT_AT_TRIGGER": _fmt_opt(r.dist_to_52w_high_pct_at_trigger, 4),
        "VOLUME_AT_ENTRY": _fmt_opt(r.volume_at_entry, 2),
        "AVG_VOLUME_10D_AT_ENTRY": _fmt_opt(r.avg_volume_10d_at_entry, 2),
        "REL_VOL_AT_ENTRY": _fmt_opt(r.rel_vol_at_entry, 4),
        "ATR_14_AT_ENTRY": _fmt_opt(r.atr_14_at_entry, 6),
        "ATR_PCT_AT_ENTRY": _fmt_opt(r.atr_pct_at_entry, 4),
        "RSI14_AT_ENTRY": _fmt_opt(r.rsi14_at_entry, 4),
        "HIGH_52W_AT_ENTRY": _fmt_opt(r.high_52w_at_entry, 6),
        "DIST_TO_52W_HIGH_PCT": _fmt_opt(r.dist_to_52w_high_pct, 4),
        "MARKET_CAP": _fmt_opt(r.market_cap, 2),
        "SECTOR": r.sector,
        "INDUSTRY": r.industry,
        "BETA": _fmt_opt(r.beta, 4),
        "FLOAT_SHARES": _fmt_opt(r.float_shares, 2),
        "SHORT_PERCENT_OF_FLOAT": _fmt_opt(r.short_percent_of_float, 6),
        "SYSTEM": "MUD",
    }


def _slice_metrics(rows: list[MudClosedRow], cash: Optional[float] = None) -> dict[str, Any]:
    if not rows:
        return {"n": 0}
    wins = sum(1 for r in rows if r.pnl_pct > 0)
    total_pnl = float(sum(r.pnl_dollars for r in rows))
    avg_days = float(np.mean([r.days_held for r in rows]))
    # Match trade dollars: mean entry notional (same as mud grid), not sheet cash.
    slot = float(np.mean([r.entry_notional for r in rows])) if cash is None else float(cash)
    if not (slot > 0):
        slot = INITIAL_CAPITAL
    ann = ann_ror_from_closed(
        total_pnl=total_pnl,
        n_trades=len(rows),
        avg_days_held=avg_days,
        brt_cash=slot,
    )
    return {
        "n": len(rows),
        "wr": 100.0 * wins / len(rows),
        "avg": float(np.mean([r.pnl_pct for r in rows])),
        "avg_days": avg_days,
        "slot_cash": slot,
        "ann_ror": float(ann) if ann is not None else float("nan"),
    }


def write_report(
    *,
    out_dir: Path,
    closed_path: Path,
    open_path: Path,
    lookback: int,
    rebalance: int,
    metrics: dict[str, Any],
    n_symbols: int,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "report.html"
    ask = (
        "you are using trading days and not calendar days for these runs, correct? "
        "i would like more data. can we wire this in as a TBN research system and produce "
        "a real closed-type output file with all of the usual variables, but also, what "
        "percentile is the stock in when bought and anything else you think might be helpful "
        "in figuring out which stocks to buy and sell. volume, industry/sector market cap, etc. "
        "all the things we have in closed"
    )
    plain = (
        f"Yes — Most Up / Most Down (MUD) lookback and rebalance use <b>trading days</b>, "
        f"not calendar days. This page freezes the lean-keep research book "
        f"<b>L{lookback}_R{rebalance}</b> (5 trading-day lookback, rebalance every 1 trading day) "
        f"and writes a TBN-style Closed file with buy-rank percentile, lookback return, "
        f"volume / ATR / RSI / 52-week at <b>signal</b> (predictive) and at <b>entry</b> (indicative), "
        f"plus market cap, sector, and industry. Research only — not DailyRun."
    )
    m_f, m_is, m_oos = metrics["full"], metrics["is"], metrics["oos"]

    def _m(m: dict[str, Any]) -> str:
        if not m.get("n"):
            return "—"
        return (
            f"N={m['n']:,} · WR={m['wr']:.1f}% · avg={m['avg']:.2f}% · "
            f"days={m['avg_days']:.1f} · Ann ROR={m['ann_ror']:.2f}%"
        )

    body = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>MUD research Closed — L{lookback}_R{rebalance}</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:1.2rem;line-height:1.45;color:#222}}
.callout{{background:#f4f7fb;border-left:4px solid #2a6;padding:.8rem 1rem;margin:1rem 0}}
code,pre{{font-family:ui-monospace,Consolas,monospace}}
{SORTABLE_TH_CSS}
{RESPONSIVE_TABLE_CSS}
</style></head><body>
<h1>MUD (Most Up / Most Down) — research Closed</h1>
<div class="callout"><h2>What you asked</h2><p>{html_mod.escape(ask)}</p>
<h2>In plain English</h2><p>{plain}</p></div>
<p><b>Freeze:</b> lookback <b>{lookback} trading days</b>, rebalance every <b>{rebalance} trading day(s)</b>.
Universe ~{n_symbols} names. Slot cash ${INITIAL_CAPITAL:,.0f}. No stop/target. Exit = rebalance rotate.</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap"><table class="sortable">
<thead><tr>
{''.join([
    '<th class="sortable-th" data-sort="text" tabindex="0" role="columnheader" aria-sort="none">Slice<span class="sort-ind"></span></th>',
    '<th class="sortable-th" data-sort="text" tabindex="0" role="columnheader" aria-sort="none">Metrics<span class="sort-ind"></span></th>',
])}
</tr></thead>
<tbody>
<tr><td>Full</td><td>{html_mod.escape(_m(m_f))}</td></tr>
<tr><td>In-sample (entry &lt; 2024-01-01)</td><td>{html_mod.escape(_m(m_is))}</td></tr>
<tr><td>Out-of-sample (entry ≥ 2024-01-01)</td><td>{html_mod.escape(_m(m_oos))}</td></tr>
</tbody></table></div>
<p><b>Closed:</b> <code>{html_mod.escape(str(closed_path))}</code><br/>
<b>Open:</b> <code>{html_mod.escape(str(open_path))}</code></p>
<p>Key MUD columns: <code>RANK_PERCENTILE</code> (0 = most down / long sleeve, 100 = most up / short sleeve),
<code>LOOKBACK_RETURN_PCT</code>, <code>SIGNAL_DATE</code>.
Volume / ATR / RSI / 52w appear twice: <code>*_AT_TRIGGER</code> (signal close — predictive) and
<code>*_AT_ENTRY</code> (fill bar — indicative), plus market cap / sector / industry.</p>
<p>Research only. Not gold. Not DailyRun.</p>
<script>
(function(){{
  document.querySelectorAll('table.sortable').forEach(function(table){{
    table.querySelectorAll('th.sortable-th').forEach(function(th, col){{
      th.addEventListener('click', function(){{
        var type = th.getAttribute('data-sort') || 'text';
        var tbody = table.tBodies[0];
        var rows = Array.from(tbody.querySelectorAll('tr'));
        var dir = th.getAttribute('aria-sort') === 'ascending' ? 'desc' : 'asc';
        rows.sort(function(a,b){{
          var av=(a.cells[col]&&a.cells[col].innerText||'').trim().toUpperCase();
          var bv=(b.cells[col]&&b.cells[col].innerText||'').trim().toUpperCase();
          if(av<bv) return dir==='asc'?-1:1;
          if(av>bv) return dir==='asc'?1:-1;
          return 0;
        }});
        rows.forEach(function(r){{ tbody.appendChild(r); }});
        table.querySelectorAll('th.sortable-th').forEach(function(h){{ h.setAttribute('aria-sort','none'); }});
        th.setAttribute('aria-sort', dir==='asc'?'ascending':'descending');
      }});
    }});
  }});
}})();
</script>
</body></html>"""
    html_path.write_text(body, encoding="utf-8")
    return html_path


def main() -> int:
    ap = argparse.ArgumentParser(description="MUD research Closed producer")
    ap.add_argument("--lookback", type=int, default=DEFAULT_L)
    ap.add_argument("--rebalance", type=int, default=DEFAULT_R)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--fund-db", type=Path, default=FUND_DB)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out-dir", type=Path, default=None)
    args = ap.parse_args()
    if args.out_dir is None:
        args.out_dir = stamp_dir(int(args.lookback), int(args.rebalance))

    print(
        f"MUD research Closed L={args.lookback} R={args.rebalance} "
        f"(trading days) loading panel…",
        flush=True,
    )
    cal, arrays, symbols = load_panel(
        args.db, min_bars=max(PANEL_MIN_BARS, args.lookback + 40), limit=args.limit or None
    )
    print(f"  symbols={len(symbols)} bars={len(cal)}", flush=True)
    fund = load_fundamentals(args.fund_db)
    print(f"  fundamentals={len(fund)}", flush=True)

    closed, open_rows, _eq = run_mud_closed(
        cal=cal,
        arrays=arrays,
        symbols=symbols,
        lookback=int(args.lookback),
        rebalance=int(args.rebalance),
        fund=fund,
    )
    print(f"  closed trades={len(closed)} open={len(open_rows)}", flush=True)

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%y%m%d%H%M%S")
    closed_path = out_dir / f"MUD_Closed_{ts}.csv"
    open_path = out_dir / f"MUD_Open_{ts}.csv"
    latest_closed = _REPO / "drive" / "MUD_LatestRun_Closed.csv"
    latest_open = _REPO / "drive" / "MUD_LatestRun_Open.csv"

    with closed_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CLOSED_HEADER, extrasaction="ignore")
        w.writeheader()
        for r in closed:
            w.writerow(row_to_csv(r))

    open_header = [
        "SYMBOL",
        "SIDE",
        "DATE_OPENED",
        "ENTRY_PRICE",
        "LAST_PRICE",
        "SHARES",
        "UNREALIZED_PNL",
        "UNREALIZED_PNL_PCT",
        "LOOKBACK_RETURN_PCT",
        "RANK_PERCENTILE",
        "SIGNAL_DATE",
        "SYSTEM",
    ]
    with open_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=open_header, extrasaction="ignore")
        w.writeheader()
        for row in open_rows:
            w.writerow(row)

    # Copy latest
    latest_closed.write_bytes(closed_path.read_bytes())
    latest_open.write_bytes(open_path.read_bytes())

    is_rows = [r for r in closed if r.date_opened < IS_CUT]
    oos_rows = [r for r in closed if r.date_opened >= IS_CUT]
    metrics = {
        "full": _slice_metrics(closed),
        "is": _slice_metrics(is_rows),
        "oos": _slice_metrics(oos_rows),
        "lookback": args.lookback,
        "rebalance": args.rebalance,
        "n_symbols": len(symbols),
        "trading_days": True,
        "calendar_days_for_L_R": False,
    }
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    baseline = f"""# MUD research Closed — L{args.lookback}_R{args.rebalance}

## Trading days

**Yes.** Lookback L and rebalance R are **trading days** (sessions in the warehouse calendar), not calendar days.
`DAYS_HELD` is calendar days between entry and exit (house Closed style). `TRADING_DAYS_HELD` is the bar count.

## Freeze (research candidate)

- System: **MUD** (Most Up / Most Down)
- Lookback: **{args.lookback} trading days**
- Rebalance: every **{args.rebalance} trading day(s)** (full rotate)
- Long most-down decile / short most-up decile (10%)
- Dollar-neutral; equal-weight within sleeve
- Signal at prior close; fill next open
- No stop / target / SD band
- Commissions 0; borrow not modeled
- Universe: warehouse prices minus SPY (~{len(symbols)} names this run)
- Not DailyRun. Not gold.

## Closed path

- `{closed_path.as_posix()}`
- `drive/MUD_LatestRun_Closed.csv`

## Trigger vs entry tape fields

Volume / ATR / RSI / 52w are written at **signal** (`*_AT_TRIGGER`, known on the ranking close before the next-open fill) and again at **entry** (`*_AT_ENTRY`). Use trigger columns for predictive filters.

## Selection bias

Lean-keep L5_R1 was chosen from the lookback×rebalance grid (in-sample). This Closed is that freeze for diagnostics — OOS report-only.
"""
    (out_dir / "BASELINE.md").write_text(baseline, encoding="utf-8")
    html_path = write_report(
        out_dir=out_dir,
        closed_path=closed_path,
        open_path=open_path,
        lookback=int(args.lookback),
        rebalance=int(args.rebalance),
        metrics=metrics,
        n_symbols=len(symbols),
    )
    print(f"Wrote {closed_path}", flush=True)
    print(f"Wrote {html_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
