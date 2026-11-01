#!/usr/bin/env python3
"""Top-50 (ever) closing-ATH drawdown / recovery ledger.

Research only. Not DailyRun. Not gold.

Universe = names that were ever in the annual approx-mcap top 50 on the
Standard & Poor's 500 (S&P 500) Wikipedia ∩ DuckDB panel used by
``tools/run_spx_diversification.py`` (~2011 through latest local OHLC).

Usage:
    python tools/top50_ath_drawdown_20260916.py
"""
from __future__ import annotations

import html as html_mod
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import run_spx_diversification as spx  # noqa: E402

STAMP_ID = "top50_ath_drawdown_20260916"
STAMP_DIR = REPO / "drive" / "paul_experiments" / STAMP_ID
SPX_DIR = REPO / "drive" / "spx_diversification"
DB_PATH = REPO / "data" / "ohlcv.duckdb"

MEMBERSHIP_START_YEAR = 2011
TOP_X = 50
ORIGINAL_REQUEST = (
    "for all stocks with top 50 market cap through the years can you list each stock, "
    "and a full list of new highs along with lowest low after the new high along with "
    "# days, and then from each of the lowest lows how long to a new high? and then "
    "I'd like an aggregate including averages and medians for each stock and across "
    "all stocks please."
)
LAYMAN = (
    "We took every name that showed up at least once in the annual list of the 50 "
    "largest Standard & Poor's 500 (S&P 500) stocks (size approximated the same way "
    "as the S&P diversification stamp: today's market cap scaled by that day's close "
    "versus the latest close). For each of those names we walked the local daily "
    "chart from the first bar we have. A new high is a closing all-time high (ATH) "
    "in that sample — the close is the highest close so far, not a 52-week high. "
    "After each ATH we record the lowest low printed before the next ATH (or until "
    "the chart ends), how many calendar and trading days that took, how far price "
    "fell from the ATH close to that low, and then how long from that low until a "
    "close beat the old ATH. If the stock has not made a new high yet, that last "
    "leg is marked open / not yet and is left out of the recovery averages. "
    "Averages and medians are shown per stock, then two ways across stocks: "
    "equal-weight every ATH event, and equal-weight each stock. Research ledger "
    "only — not a trading rule and not DailyRun."
)


def _esc(x: Any) -> str:
    return html_mod.escape("" if x is None else str(x))


def _mean(vals: list[float] | np.ndarray) -> float | None:
    arr = np.asarray(list(vals), dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return None
    return float(np.mean(arr))


def _median(vals: list[float] | np.ndarray) -> float | None:
    arr = np.asarray(list(vals), dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return None
    return float(np.median(arr))


def _fmt_num(v: Any, digits: int = 2) -> str:
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "—"
    try:
        return f"{float(v):,.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_int(v: Any) -> str:
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "—"
    try:
        return f"{int(v):,}"
    except (TypeError, ValueError):
        return "—"


def _fmt_pct(v: Any, digits: int = 2) -> str:
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "—"
    try:
        return f"{float(v):.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def _load_wiki() -> list[str]:
    cached = SPX_DIR / "sp500_constituents_wikipedia.txt"
    try:
        wiki = spx._fetch_sp500_tickers()
        if wiki:
            return wiki
    except Exception:
        pass
    if cached.is_file():
        return [ln.strip().upper() for ln in cached.read_text(encoding="utf-8").splitlines() if ln.strip()]
    raise RuntimeError("No Wikipedia S&P 500 list (fetch failed and cache missing)")


def _load_mcaps(symbols: list[str]) -> dict[str, float]:
    """Reuse cached Yahoo / stamp mcaps. No forced refresh."""
    out: dict[str, float] = {}
    yf = spx._load_yf_cache()
    for sym in symbols:
        mc = (yf.get(sym) or {}).get("market_cap")
        if mc is not None and float(mc) > 0:
            out[sym] = float(mc)
    stamp_mcap = SPX_DIR / "_cache" / "mcap.json"
    if stamp_mcap.is_file():
        try:
            extra = json.loads(stamp_mcap.read_text(encoding="utf-8"))
        except Exception:
            extra = {}
        for sym in symbols:
            if sym in out:
                continue
            mc = extra.get(sym)
            if mc is not None and float(mc) > 0:
                out[sym] = float(mc)
    return out


def _load_ohlc(symbols: list[str]) -> pd.DataFrame:
    import duckdb

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        df = con.execute(
            """
            SELECT symbol, date AS Date, open AS Open, high AS High, low AS Low, close AS Close
            FROM prices
            WHERE symbol IN (SELECT * FROM UNNEST(?::VARCHAR[]))
            ORDER BY symbol, date
            """,
            [symbols],
        ).fetchdf()
    finally:
        con.close()
    if df.empty:
        raise RuntimeError("No OHLC rows loaded")
    df["Date"] = pd.to_datetime(df["Date"])
    df["symbol"] = df["symbol"].astype(str).str.upper()
    return df


def _annual_top_x(
    closes: pd.DataFrame,
    mcap_now: dict[str, float],
    *,
    x: int,
    start_year: int,
) -> tuple[pd.DataFrame, dict[str, list[int]]]:
    """First SPY trading day of each calendar year → top-X by approx mcap."""
    if "SPY" not in closes.columns:
        raise RuntimeError("SPY missing from close panel")
    calendar = closes.index
    recon = sorted(d for d in spx._first_trading_days_of_year(calendar) if d.year >= start_year)
    syms = [c for c in closes.columns if c != "SPY" and c in mcap_now]
    close_arr = closes[syms].to_numpy(dtype=float)
    mcap_vec = np.array([mcap_now[s] for s in syms], dtype=float)
    ref_close = np.full(len(syms), np.nan)
    for j in range(len(syms)):
        col = close_arr[:, j]
        valid = np.where(np.isfinite(col) & (col > 0))[0]
        if len(valid):
            ref_close[j] = col[valid[-1]]

    date_to_i = {d: i for i, d in enumerate(calendar)}
    rows: list[dict[str, Any]] = []
    years_by_sym: dict[str, list[int]] = {s: [] for s in syms}
    for d in recon:
        i = date_to_i[d]
        px = close_arr[i]
        with np.errstate(divide="ignore", invalid="ignore"):
            approx = mcap_vec * (px / ref_close)
        approx[~np.isfinite(approx) | (px <= 0) | ~np.isfinite(px)] = np.nan
        order = np.argsort(-np.nan_to_num(approx, nan=-np.inf))
        rank = 0
        for j in order:
            if not np.isfinite(approx[j]):
                continue
            rank += 1
            if rank > x:
                break
            sym = syms[j]
            years_by_sym[sym].append(int(d.year))
            rows.append(
                {
                    "recon_date": str(d.date()),
                    "year": int(d.year),
                    "rank": rank,
                    "symbol": sym,
                    "approx_mcap": float(approx[j]),
                    "close": float(px[j]),
                }
            )
    years_by_sym = {s: ys for s, ys in years_by_sym.items() if ys}
    return pd.DataFrame(rows), years_by_sym


def _ath_events_for_symbol(
    symbol: str,
    frame: pd.DataFrame,
    *,
    years_top50: list[int],
) -> list[dict[str, Any]]:
    """Closing ATHs from first available bar; trough = lowest Low in (T0, T_next]."""
    df = frame.dropna(subset=["Close"]).copy()
    df = df[np.isfinite(df["Close"].to_numpy(dtype=float)) & (df["Close"] > 0)]
    if df.empty:
        return []
    dates = pd.to_datetime(df["Date"]).to_numpy()
    close = df["Close"].to_numpy(dtype=float)
    raw_low = df["Low"].to_numpy(dtype=float)
    low_ok = np.isfinite(raw_low) & (raw_low > 0)
    low = np.where(low_ok, raw_low, close)
    low_filled = ~low_ok

    n = len(close)
    if n < 1:
        return []
    is_ath = np.zeros(n, dtype=bool)
    is_ath[0] = True
    if n > 1:
        prior_max = np.maximum.accumulate(close)[:-1]
        is_ath[1:] = close[1:] > prior_max
    ath_idx = np.flatnonzero(is_ath)
    years = ",".join(str(y) for y in years_top50)
    n_years = len(years_top50)
    first_y = years_top50[0] if years_top50 else None
    last_y = years_top50[-1] if years_top50 else None
    ohlc_start = str(pd.Timestamp(dates[0]).date())
    ohlc_end = str(pd.Timestamp(dates[-1]).date())

    events: list[dict[str, Any]] = []
    for k, i in enumerate(ath_idx):
        t0 = pd.Timestamp(dates[i])
        p0 = float(close[i])
        next_i = int(ath_idx[k + 1]) if k + 1 < len(ath_idx) else None
        seq = k + 1
        base = {
            "symbol": symbol,
            "ath_seq": seq,
            "ath_date": str(t0.date()),
            "ath_close": p0,
            "ohlc_start": ohlc_start,
            "ohlc_end": ohlc_end,
            "years_in_top50": years,
            "n_years_top50": n_years,
            "first_top50_year": first_y,
            "last_top50_year": last_y,
        }
        if i >= n - 1:
            events.append(
                {
                    **base,
                    "status": "at_sample_ath",
                    "trough_date": "",
                    "trough_low": None,
                    "pct_drop": None,
                    "cal_days_high_to_low": None,
                    "td_days_high_to_low": None,
                    "low_source": "Low",
                    "trough_above_ath_close": 0,
                    "next_ath_date": "",
                    "next_ath_close": None,
                    "cal_days_low_to_new_high": None,
                    "td_days_low_to_new_high": None,
                    "recovered": 0,
                    "last_close": float(close[-1]),
                    "last_date": str(pd.Timestamp(dates[-1]).date()),
                    "pct_off_ath_last_close": 0.0,
                    "cal_days_since_ath": 0,
                }
            )
            continue

        scan_end = next_i if next_i is not None else n - 1
        window = np.arange(i + 1, scan_end + 1)
        trough_rel = int(np.argmin(low[window]))
        trough = int(window[trough_rel])
        t_low = pd.Timestamp(dates[trough])
        p_low = float(low[trough])
        raw_drop = (p0 - p_low) / p0 * 100.0 if p0 > 0 else None
        trough_above = int(raw_drop is not None and raw_drop < 0)
        pct_drop = 0.0 if trough_above else raw_drop
        cal_hl = int((t_low - t0).days)
        td_hl = int(trough - i)
        src = "Close_fallback" if low_filled[trough] else "Low"
        last_close = float(close[-1])
        last_date = str(pd.Timestamp(dates[-1]).date())
        pct_off_last = (p0 - last_close) / p0 * 100.0 if p0 > 0 else None
        cal_since_ath = int((pd.Timestamp(dates[-1]) - t0).days)

        rec_j = None
        for j in range(trough, n):
            if close[j] > p0:
                rec_j = j
                break
        if rec_j is None:
            events.append(
                {
                    **base,
                    "status": "open_unrecovered",
                    "trough_date": str(t_low.date()),
                    "trough_low": p_low,
                    "pct_drop": pct_drop,
                    "cal_days_high_to_low": cal_hl,
                    "td_days_high_to_low": td_hl,
                    "low_source": src,
                    "trough_above_ath_close": trough_above,
                    "next_ath_date": "",
                    "next_ath_close": None,
                    "cal_days_low_to_new_high": None,
                    "td_days_low_to_new_high": None,
                    "recovered": 0,
                    "last_close": last_close,
                    "last_date": last_date,
                    "pct_off_ath_last_close": pct_off_last,
                    "cal_days_since_ath": cal_since_ath,
                }
            )
            continue

        t_rec = pd.Timestamp(dates[rec_j])
        events.append(
            {
                **base,
                "status": "recovered",
                "trough_date": str(t_low.date()),
                "trough_low": p_low,
                "pct_drop": pct_drop,
                "cal_days_high_to_low": cal_hl,
                "td_days_high_to_low": td_hl,
                "low_source": src,
                "trough_above_ath_close": trough_above,
                "next_ath_date": str(t_rec.date()),
                "next_ath_close": float(close[rec_j]),
                "cal_days_low_to_new_high": int((t_rec - t_low).days),
                "td_days_low_to_new_high": int(rec_j - trough),
                "recovered": 1,
                "last_close": last_close,
                "last_date": last_date,
                "pct_off_ath_last_close": None,
                "cal_days_since_ath": None,
            }
        )
    return events


def _stock_aggregates(events: list[dict[str, Any]], years_by_sym: dict[str, list[int]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    by_sym: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        by_sym.setdefault(ev["symbol"], []).append(ev)
    for sym in sorted(by_sym):
        evs = by_sym[sym]
        trough = [e for e in evs if e["status"] != "at_sample_ath"]
        rec = [e for e in evs if e["status"] == "recovered"]
        open_u = [e for e in evs if e["status"] == "open_unrecovered"]
        at_ath = [e for e in evs if e["status"] == "at_sample_ath"]
        years = years_by_sym.get(sym, [])
        n_t = len(trough)
        ge5 = [e for e in trough if e.get("pct_drop") is not None and e["pct_drop"] >= 5]
        ge5_rec = [e for e in ge5 if e["status"] == "recovered"]
        ge10 = [e for e in trough if e.get("pct_drop") is not None and e["pct_drop"] >= 10]
        ge10_rec = [e for e in ge10 if e["status"] == "recovered"]
        rows.append(
            {
                "symbol": sym,
                "n_highs": len(evs),
                "n_with_trough": n_t,
                "n_recovered": len(rec),
                "n_open_unrecovered": len(open_u),
                "n_at_sample_ath": len(at_ath),
                "pct_never_recovered": (len(open_u) / n_t * 100.0) if n_t else None,
                "avg_cal_days_high_to_low": _mean([e["cal_days_high_to_low"] for e in trough]),
                "median_cal_days_high_to_low": _median([e["cal_days_high_to_low"] for e in trough]),
                "avg_td_days_high_to_low": _mean([e["td_days_high_to_low"] for e in trough]),
                "median_td_days_high_to_low": _median([e["td_days_high_to_low"] for e in trough]),
                "avg_pct_drop": _mean([e["pct_drop"] for e in trough]),
                "median_pct_drop": _median([e["pct_drop"] for e in trough]),
                "avg_cal_days_low_to_new_high": _mean([e["cal_days_low_to_new_high"] for e in rec]),
                "median_cal_days_low_to_new_high": _median([e["cal_days_low_to_new_high"] for e in rec]),
                "avg_td_days_low_to_new_high": _mean([e["td_days_low_to_new_high"] for e in rec]),
                "median_td_days_low_to_new_high": _median([e["td_days_low_to_new_high"] for e in rec]),
                "n_drop_ge5": len(ge5),
                "median_cal_days_high_to_low_ge5": _median([e["cal_days_high_to_low"] for e in ge5]),
                "median_pct_drop_ge5": _median([e["pct_drop"] for e in ge5]),
                "median_cal_days_low_to_new_high_ge5": _median([e["cal_days_low_to_new_high"] for e in ge5_rec]),
                "n_drop_ge10": len(ge10),
                "median_cal_days_high_to_low_ge10": _median([e["cal_days_high_to_low"] for e in ge10]),
                "median_pct_drop_ge10": _median([e["pct_drop"] for e in ge10]),
                "median_cal_days_low_to_new_high_ge10": _median([e["cal_days_low_to_new_high"] for e in ge10_rec]),
                "n_years_top50": len(years),
                "first_top50_year": years[0] if years else None,
                "last_top50_year": years[-1] if years else None,
                "years_in_top50": ",".join(str(y) for y in years),
                "ohlc_start": evs[0].get("ohlc_start"),
                "ohlc_end": evs[0].get("ohlc_end"),
            }
        )
    return pd.DataFrame(rows)


def _slice_metrics(sub: pd.DataFrame) -> dict[str, Any]:
    trough = sub[sub["status"] != "at_sample_ath"]
    rec = sub[sub["status"] == "recovered"]
    open_u = sub[sub["status"] == "open_unrecovered"]
    return {
        "n_events": int(len(sub)),
        "n_with_trough": int(len(trough)),
        "n_recovered": int(len(rec)),
        "n_open_unrecovered": int(len(open_u)),
        "pct_never_recovered": (float(len(open_u) / len(trough) * 100.0) if len(trough) else None),
        "avg_cal_days_high_to_low": _mean(trough["cal_days_high_to_low"]) if len(trough) else None,
        "median_cal_days_high_to_low": _median(trough["cal_days_high_to_low"]) if len(trough) else None,
        "avg_td_days_high_to_low": _mean(trough["td_days_high_to_low"]) if len(trough) else None,
        "median_td_days_high_to_low": _median(trough["td_days_high_to_low"]) if len(trough) else None,
        "avg_pct_drop": _mean(trough["pct_drop"]) if len(trough) else None,
        "median_pct_drop": _median(trough["pct_drop"]) if len(trough) else None,
        "avg_cal_days_low_to_new_high": _mean(rec["cal_days_low_to_new_high"]) if len(rec) else None,
        "median_cal_days_low_to_new_high": _median(rec["cal_days_low_to_new_high"]) if len(rec) else None,
        "avg_td_days_low_to_new_high": _mean(rec["td_days_low_to_new_high"]) if len(rec) else None,
        "median_td_days_low_to_new_high": _median(rec["td_days_low_to_new_high"]) if len(rec) else None,
    }


def _cross_aggregates(events: pd.DataFrame, stocks: pd.DataFrame) -> pd.DataFrame:
    def pack(scope: str, weight: str, note: str, **metrics: float | None) -> dict[str, Any]:
        row = {"scope": scope, "weighting": weight, "note": note}
        row.update(metrics)
        return row

    pause = events[events["td_days_high_to_low"].fillna(0) >= 2]
    ge5 = events[events["pct_drop"].fillna(0) >= 5]
    ge10 = events[events["pct_drop"].fillna(0) >= 10]
    n_names = int(stocks["symbol"].nunique()) if not stocks.empty else 0

    rows = [
        pack(
            "all_events",
            "event_equal",
            "Every closing ATH counts once, including next-day stair-steps (most events). Unrecovered legs excluded from recovery averages.",
            n_names=n_names,
            **_slice_metrics(events),
        ),
        pack(
            "pause_2plus_td",
            "event_equal",
            "Only events whose trough is at least 2 trading days after the ATH (skips next-session stair-steps).",
            n_names=n_names,
            **_slice_metrics(pause),
        ),
        pack(
            "drop_ge_5pct",
            "event_equal",
            "ATH events whose lowest Low was at least 5% below the ATH close.",
            n_names=n_names,
            **_slice_metrics(ge5),
        ),
        pack(
            "drop_ge_10pct",
            "event_equal",
            "ATH events whose lowest Low was at least 10% below the ATH close.",
            n_names=n_names,
            **_slice_metrics(ge10),
        ),
        pack(
            "across_stocks",
            "stock_equal_of_stock_medians",
            "Each stock counts once. Metrics are the mean/median of that stock's all-event medians.",
            n_names=int(len(stocks)),
            n_events=int(len(events)),
            n_with_trough=int(stocks["n_with_trough"].sum()) if not stocks.empty else 0,
            n_recovered=int(stocks["n_recovered"].sum()) if not stocks.empty else 0,
            n_open_unrecovered=int(stocks["n_open_unrecovered"].sum()) if not stocks.empty else 0,
            pct_never_recovered=_median(stocks["pct_never_recovered"]),
            avg_cal_days_high_to_low=_mean(stocks["median_cal_days_high_to_low"]),
            median_cal_days_high_to_low=_median(stocks["median_cal_days_high_to_low"]),
            avg_td_days_high_to_low=_mean(stocks["median_td_days_high_to_low"]),
            median_td_days_high_to_low=_median(stocks["median_td_days_high_to_low"]),
            avg_pct_drop=_mean(stocks["median_pct_drop"]),
            median_pct_drop=_median(stocks["median_pct_drop"]),
            avg_cal_days_low_to_new_high=_mean(stocks["median_cal_days_low_to_new_high"]),
            median_cal_days_low_to_new_high=_median(stocks["median_cal_days_low_to_new_high"]),
            avg_td_days_low_to_new_high=_mean(stocks["median_td_days_low_to_new_high"]),
            median_td_days_low_to_new_high=_median(stocks["median_td_days_low_to_new_high"]),
        ),
        pack(
            "across_stocks",
            "stock_equal_of_stock_means",
            "Each stock counts once. Metrics are the mean/median of that stock's all-event averages.",
            n_names=int(len(stocks)),
            n_events=int(len(events)),
            n_with_trough=int(stocks["n_with_trough"].sum()) if not stocks.empty else 0,
            n_recovered=int(stocks["n_recovered"].sum()) if not stocks.empty else 0,
            n_open_unrecovered=int(stocks["n_open_unrecovered"].sum()) if not stocks.empty else 0,
            pct_never_recovered=_mean(stocks["pct_never_recovered"]),
            avg_cal_days_high_to_low=_mean(stocks["avg_cal_days_high_to_low"]),
            median_cal_days_high_to_low=_median(stocks["avg_cal_days_high_to_low"]),
            avg_td_days_high_to_low=_mean(stocks["avg_td_days_high_to_low"]),
            median_td_days_high_to_low=_median(stocks["avg_td_days_high_to_low"]),
            avg_pct_drop=_mean(stocks["avg_pct_drop"]),
            median_pct_drop=_median(stocks["avg_pct_drop"]),
            avg_cal_days_low_to_new_high=_mean(stocks["avg_cal_days_low_to_new_high"]),
            median_cal_days_low_to_new_high=_median(stocks["avg_cal_days_low_to_new_high"]),
            avg_td_days_low_to_new_high=_mean(stocks["avg_td_days_low_to_new_high"]),
            median_td_days_low_to_new_high=_median(stocks["avg_td_days_low_to_new_high"]),
        ),
        pack(
            "across_stocks_ge5",
            "stock_equal_of_stock_medians",
            "Each stock once, using that stock's median among 5%+ drop events only.",
            n_names=int(len(stocks)),
            n_events=int(stocks["n_drop_ge5"].sum()) if not stocks.empty else 0,
            n_with_trough=int(stocks["n_drop_ge5"].sum()) if not stocks.empty else 0,
            n_recovered=None,
            n_open_unrecovered=None,
            pct_never_recovered=None,
            avg_cal_days_high_to_low=_mean(stocks["median_cal_days_high_to_low_ge5"]),
            median_cal_days_high_to_low=_median(stocks["median_cal_days_high_to_low_ge5"]),
            avg_td_days_high_to_low=None,
            median_td_days_high_to_low=None,
            avg_pct_drop=_mean(stocks["median_pct_drop_ge5"]),
            median_pct_drop=_median(stocks["median_pct_drop_ge5"]),
            avg_cal_days_low_to_new_high=_mean(stocks["median_cal_days_low_to_new_high_ge5"]),
            median_cal_days_low_to_new_high=_median(stocks["median_cal_days_low_to_new_high_ge5"]),
            avg_td_days_low_to_new_high=None,
            median_td_days_low_to_new_high=None,
        ),
    ]
    return pd.DataFrame(rows)


def _write_baseline(
    path: Path,
    *,
    n_names: int,
    n_events: int,
    names: list[str],
    membership_years: list[int],
    ohlc_start: str,
    ohlc_end: str,
    wiki_n: int,
    universe_n: int,
    mcap_n: int,
    missing_n: int,
    event_med: dict[str, Any],
    n_open: int,
    n_at_ath: int,
) -> None:
    names_txt = ", ".join(names)
    year_span = f"{min(membership_years)}–{max(membership_years)}" if membership_years else "n/a"
    path.write_text(
        f"""# BASELINE — {STAMP_ID}

**Status:** Research ledger. **Not gold. Not DailyRun.** No trading adopt.

## What you asked

> {ORIGINAL_REQUEST}

## In plain English

{LAYMAN}

## Freeze (do not silently mutate)

- **Universe construction:** same as `tools/run_spx_diversification.py` / `drive/spx_diversification/`.
  Today's Wikipedia S&P 500 list ∩ local DuckDB OHLC; dual-class GOOG dropped when GOOGL is present.
- **Top 50 membership:** annual reconstitution on the **first S&P 500 ETF (SPY) trading day of each calendar year**, years **{year_span}**. Ranked by **approx market cap** = Yahoo-now `marketCap` × `Close_t / Close_now` (constant-share approximation). A name is included if it was in that top {TOP_X} **at least once**.
- **OHLC window for ATH events:** first available DuckDB bar through latest local bar (**{ohlc_start} → {ohlc_end}**). Local prices start 2010-01-04 — this is a **sample ATH**, not a pre-2010 true all-time high, and **not a 52-week high**.
- **New high / ATH:** new **closing** high in the sample. First valid close is ATH #1. Strictly greater than the prior running max close. Consecutive-day ATHs are still recorded.
- **Lowest low after:** lowest **Low** (daily bar low; if Low is missing/non-positive, fall back to that day's Close and label `Close_fallback`) in **(T0, T_next_high]** — exclusive of the ATH bar, inclusive of the next ATH bar (or last sample bar if never recovered).
- **# days high → low:** **calendar days** (`trough_date − ath_date`) and **trading days** (count of valid-close bars between them). Headline medians use calendar days unless labeled `td_`.
- **Low → new high:** calendar and trading days from the **trough date** to the next close that **exceeds** the ATH close P0. Same-day recovery (wide-range next-ATH bar) = 0 days. If never recovered: **open / not yet** (`open_unrecovered`). Last-bar ATH with no forward window: `at_sample_ath`.
- **% drop:** `(ATH_close − trough_low) / ATH_close × 100` (positive = how far price fell).
- **Recovery averages:** recovered events only. Open / at-ATH legs excluded from recovery stats; at-ATH also excluded from trough / % drop stats.
- **Cross-stock weights (labeled):**
  - `event_equal` — every ATH event once.
  - `stock_equal_of_stock_medians` — each stock once, using that stock's event medians.
  - `stock_equal_of_stock_means` — each stock once, using that stock's event means.
- **Not DailyRun. Not gold.** Research ledger only.

## Counts

- Wikipedia S&P 500 names: {wiki_n}
- Local OHLC ∩ wiki: {universe_n} ({missing_n} missing locally)
- Usable market cap: {mcap_n}
- Ever in annual top {TOP_X}: **{n_names}** names
- Closing ATH events: **{n_events}**
- Open / not yet recovered (last trough, no new high yet): **{n_open}**
- Currently sitting on the sample ATH (no forward bar): **{n_at_ath}**

## Headline (event-equal, all closing ATHs)

These medians are **small** because mega-caps print many next-day stair-step ATHs (trough often the next session; recovery often the same bar). Also report 5%+ / 10%+ slices in `cross_stock_aggregates.csv` and the HTML cards.

- Median calendar days high → low: {event_med.get("median_cal_days_high_to_low")}
- Median % drop (high close → trough low): {event_med.get("median_pct_drop")}
- Median calendar days low → new high (recovered only): {event_med.get("median_cal_days_low_to_new_high")}

Open / not yet = each name's **latest** sample ATH (every earlier ATH recovered when the next one printed).

## Names (ever top {TOP_X})

{names_txt}

## Honesty / selection

- Survivorship: today's S&P 500 list projected backward; delisted/removed names never appear.
- Market caps are not a true historical free-float panel.
- Sample ATH from 2010 (or IPO), not a 52-week high and not a pre-2010 true ATH.
- Choosing any "typical" recovery time from this table is descriptive, not a trading edge. Event-equal medians are dominated by consecutive-day ATHs; use the 5%+ / 10%+ slices for material pullbacks.
- Gap-up next bar (Low still above the ATH close) stores % drop as 0.
- No IS/OOS retune. No DailyRun wire.

## Verdict

**Research ledger only.** No KEEP / adopt. Do not wire DailyRun.
""",
        encoding="utf-8",
    )


def _th(label: str, sort_type: str) -> str:
    return spx._sortable_th(label, sort_type)


def _write_html(
    path: Path,
    *,
    events: pd.DataFrame,
    stocks: pd.DataFrame,
    cross: pd.DataFrame,
    open_rows: pd.DataFrame,
    at_ath_rows: pd.DataFrame,
    n_names: int,
    n_events: int,
    ohlc_start: str,
    ohlc_end: str,
    membership_years: list[int],
) -> None:
    ev_row = cross[(cross["scope"] == "all_events") & (cross["weighting"] == "event_equal")].iloc[0].to_dict()
    ge5_row = cross[cross["scope"] == "drop_ge_5pct"].iloc[0].to_dict()
    ge10_row = cross[cross["scope"] == "drop_ge_10pct"].iloc[0].to_dict()
    st_med = cross[
        (cross["scope"] == "across_stocks") & (cross["weighting"] == "stock_equal_of_stock_medians")
    ].iloc[0].to_dict()
    year_span = f"{min(membership_years)}–{max(membership_years)}" if membership_years else "n/a"

    def cards() -> str:
        items = [
            ("Names (ever top 50)", _fmt_int(n_names), "Annual approx-mcap top 50 at least once"),
            ("ATH events", _fmt_int(n_events), f"Closing sample ATHs {ohlc_start} → {ohlc_end}"),
            ("Median days high → low (all)", _fmt_num(ev_row.get("median_cal_days_high_to_low"), 1), "Event-equal; next-day stair-steps dominate"),
            ("Median % drop (all)", _fmt_pct(ev_row.get("median_pct_drop")), "ATH close to trough Low"),
            ("Median days low → high (all)", _fmt_num(ev_row.get("median_cal_days_low_to_new_high"), 1), "Recovered events only; 0 = same-day recover"),
            ("Open / not yet", _fmt_int(ev_row.get("n_open_unrecovered")), "Each name's latest ATH is still unmatched"),
            ("Median days high → low (5%+)", _fmt_num(ge5_row.get("median_cal_days_high_to_low"), 1), "Only events that fell 5%+ from the ATH close"),
            ("Median % drop (5%+)", _fmt_pct(ge5_row.get("median_pct_drop")), f"N={_fmt_int(ge5_row.get('n_events'))} material pullbacks"),
            ("Median days low → high (5%+)", _fmt_num(ge5_row.get("median_cal_days_low_to_new_high"), 1), "Recovered 5%+ events only"),
        ]
        out = []
        for title, metric, note in items:
            out.append(
                f'<div class="card"><h3>{_esc(title)}</h3>'
                f'<div class="metric">{metric}</div>'
                f'<div class="small">{_esc(note)}</div></div>'
            )
        return "".join(out)

    cross_head = "".join(
        [
            _th("Scope", "text"),
            _th("Weighting", "text"),
            _th("N names", "num"),
            _th("N events", "num"),
            _th("N with trough", "num"),
            _th("N recovered", "num"),
            _th("N open", "num"),
            _th("% never recovered", "num"),
            _th("Avg cal d high→low", "num"),
            _th("Med cal d high→low", "num"),
            _th("Avg td high→low", "num"),
            _th("Med td high→low", "num"),
            _th("Avg % drop", "num"),
            _th("Med % drop", "num"),
            _th("Avg cal d low→high", "num"),
            _th("Med cal d low→high", "num"),
            _th("Avg td low→high", "num"),
            _th("Med td low→high", "num"),
            _th("Note", "text"),
        ]
    )
    cross_body = []
    for _, r in cross.iterrows():
        cross_body.append(
            "<tr>"
            f"<td>{_esc(r['scope'])}</td>"
            f"<td>{_esc(r['weighting'])}</td>"
            f"<td>{_fmt_int(r['n_names'])}</td>"
            f"<td>{_fmt_int(r['n_events'])}</td>"
            f"<td>{_fmt_int(r['n_with_trough'])}</td>"
            f"<td>{_fmt_int(r['n_recovered'])}</td>"
            f"<td>{_fmt_int(r['n_open_unrecovered'])}</td>"
            f"<td>{_fmt_pct(r['pct_never_recovered'])}</td>"
            f"<td>{_fmt_num(r['avg_cal_days_high_to_low'], 1)}</td>"
            f"<td>{_fmt_num(r['median_cal_days_high_to_low'], 1)}</td>"
            f"<td>{_fmt_num(r['avg_td_days_high_to_low'], 1)}</td>"
            f"<td>{_fmt_num(r['median_td_days_high_to_low'], 1)}</td>"
            f"<td>{_fmt_pct(r['avg_pct_drop'])}</td>"
            f"<td>{_fmt_pct(r['median_pct_drop'])}</td>"
            f"<td>{_fmt_num(r['avg_cal_days_low_to_new_high'], 1)}</td>"
            f"<td>{_fmt_num(r['median_cal_days_low_to_new_high'], 1)}</td>"
            f"<td>{_fmt_num(r['avg_td_days_low_to_new_high'], 1)}</td>"
            f"<td>{_fmt_num(r['median_td_days_low_to_new_high'], 1)}</td>"
            f"<td class=\"small\">{_esc(r['note'])}</td>"
            "</tr>"
        )

    stock_head = "".join(
        [
            _th("Symbol", "text"),
            _th("N highs", "num"),
            _th("N with trough", "num"),
            _th("N recovered", "num"),
            _th("N open", "num"),
            _th("% never recovered", "num"),
            _th("Avg cal d high→low", "num"),
            _th("Med cal d high→low", "num"),
            _th("Avg td high→low", "num"),
            _th("Med td high→low", "num"),
            _th("Avg % drop", "num"),
            _th("Med % drop", "num"),
            _th("Avg cal d low→high", "num"),
            _th("Med cal d low→high", "num"),
            _th("Avg td low→high", "num"),
            _th("Med td low→high", "num"),
            _th("N drop ≥5%", "num"),
            _th("Med cal d high→low ≥5%", "num"),
            _th("Med % drop ≥5%", "num"),
            _th("Med cal d low→high ≥5%", "num"),
            _th("Years in top 50", "num"),
            _th("First top-50 year", "num"),
            _th("Last top-50 year", "num"),
            _th("OHLC start", "date"),
            _th("OHLC end", "date"),
            _th("CSV", "text"),
        ]
    )
    stock_body = []
    for _, r in stocks.sort_values("symbol").iterrows():
        sym = str(r["symbol"])
        stock_body.append(
            "<tr>"
            f'<td><a class="sym" href="#sym-{_esc(sym)}" data-filter="{_esc(sym)}">{_esc(sym)}</a></td>'
            f"<td>{_fmt_int(r['n_highs'])}</td>"
            f"<td>{_fmt_int(r['n_with_trough'])}</td>"
            f"<td>{_fmt_int(r['n_recovered'])}</td>"
            f"<td>{_fmt_int(r['n_open_unrecovered'])}</td>"
            f"<td>{_fmt_pct(r['pct_never_recovered'])}</td>"
            f"<td>{_fmt_num(r['avg_cal_days_high_to_low'], 1)}</td>"
            f"<td>{_fmt_num(r['median_cal_days_high_to_low'], 1)}</td>"
            f"<td>{_fmt_num(r['avg_td_days_high_to_low'], 1)}</td>"
            f"<td>{_fmt_num(r['median_td_days_high_to_low'], 1)}</td>"
            f"<td>{_fmt_pct(r['avg_pct_drop'])}</td>"
            f"<td>{_fmt_pct(r['median_pct_drop'])}</td>"
            f"<td>{_fmt_num(r['avg_cal_days_low_to_new_high'], 1)}</td>"
            f"<td>{_fmt_num(r['median_cal_days_low_to_new_high'], 1)}</td>"
            f"<td>{_fmt_num(r['avg_td_days_low_to_new_high'], 1)}</td>"
            f"<td>{_fmt_num(r['median_td_days_low_to_new_high'], 1)}</td>"
            f"<td>{_fmt_int(r['n_drop_ge5'])}</td>"
            f"<td>{_fmt_num(r['median_cal_days_high_to_low_ge5'], 1)}</td>"
            f"<td>{_fmt_pct(r['median_pct_drop_ge5'])}</td>"
            f"<td>{_fmt_num(r['median_cal_days_low_to_new_high_ge5'], 1)}</td>"
            f"<td>{_fmt_int(r['n_years_top50'])}</td>"
            f"<td>{_fmt_int(r['first_top50_year'])}</td>"
            f"<td>{_fmt_int(r['last_top50_year'])}</td>"
            f"<td>{_esc(r['ohlc_start'])}</td>"
            f"<td>{_esc(r['ohlc_end'])}</td>"
            f'<td><a href="events/{_esc(sym)}.csv">{_esc(sym)}.csv</a></td>'
            "</tr>"
        )

    ev_head = "".join(
        [
            _th("Symbol", "text"),
            _th("ATH #", "num"),
            _th("ATH date", "date"),
            _th("ATH close", "num"),
            _th("Trough date", "date"),
            _th("Trough low", "num"),
            _th("% drop", "num"),
            _th("Cal d high→low", "num"),
            _th("Td high→low", "num"),
            _th("Low source", "text"),
            _th("New-high date", "date"),
            _th("New-high close", "num"),
            _th("Cal d low→high", "num"),
            _th("Td low→high", "num"),
            _th("Status", "text"),
        ]
    )
    ev_body = []
    show = events.sort_values(["symbol", "ath_seq"])
    for _, e in show.iterrows():
        status = str(e["status"])
        cls = "open" if status == "open_unrecovered" else ("ath" if status == "at_sample_ath" else "")
        drop = e.get("pct_drop")
        drop_f = float(drop) if drop is not None and pd.notna(drop) else 0.0
        ev_body.append(
            f'<tr class="{cls}" data-sym="{_esc(e["symbol"])}" data-status="{_esc(status)}" data-drop="{drop_f:.4f}">'
            f"<td>{_esc(e['symbol'])}</td>"
            f"<td>{_fmt_int(e['ath_seq'])}</td>"
            f"<td>{_esc(e['ath_date'])}</td>"
            f"<td>{_fmt_num(e['ath_close'], 2)}</td>"
            f"<td>{_esc(e['trough_date'])}</td>"
            f"<td>{_fmt_num(e['trough_low'], 2)}</td>"
            f"<td>{_fmt_pct(e['pct_drop'])}</td>"
            f"<td>{_fmt_num(e['cal_days_high_to_low'], 0)}</td>"
            f"<td>{_fmt_num(e['td_days_high_to_low'], 0)}</td>"
            f"<td>{_esc(e['low_source'])}</td>"
            f"<td>{_esc(e['next_ath_date'])}</td>"
            f"<td>{_fmt_num(e['next_ath_close'], 2)}</td>"
            f"<td>{_fmt_num(e['cal_days_low_to_new_high'], 0)}</td>"
            f"<td>{_fmt_num(e['td_days_low_to_new_high'], 0)}</td>"
            f"<td>{_esc(status)}</td>"
            "</tr>"
        )

    def _simple_table(df: pd.DataFrame, cols: list[tuple[str, str, str]]) -> str:
        if df is None or df.empty:
            return '<p class="small muted">None.</p>'
        head = "".join(_th(lab, typ) for lab, typ, _ in cols)
        body = []
        for _, r in df.iterrows():
            tds = []
            for _lab, typ, key in cols:
                v = r.get(key)
                if typ == "num" and "pct" in key:
                    tds.append(f"<td>{_fmt_pct(v)}</td>")
                elif typ == "num" and key in ("ath_close", "trough_low", "next_ath_close", "last_close"):
                    tds.append(f"<td>{_fmt_num(v, 2)}</td>")
                elif typ == "num":
                    tds.append(f"<td>{_fmt_num(v, 0) if key.endswith('days') or key in ('ath_seq',) else _fmt_num(v, 1)}</td>")
                else:
                    tds.append(f"<td>{_esc(v)}</td>")
            body.append("<tr>" + "".join(tds) + "</tr>")
        return (
            '<div class="table-wrap"><table class="sortable"><thead><tr>'
            + head
            + "</tr></thead><tbody>"
            + "".join(body)
            + "</tbody></table></div>"
        )

    open_html = _simple_table(
        open_rows,
        [
            ("Symbol", "text", "symbol"),
            ("ATH #", "num", "ath_seq"),
            ("ATH date", "date", "ath_date"),
            ("ATH close", "num", "ath_close"),
            ("Trough date", "date", "trough_date"),
            ("Trough low", "num", "trough_low"),
            ("% drop to trough", "num", "pct_drop"),
            ("% off ATH (last close)", "num", "pct_off_ath_last_close"),
            ("Last close", "num", "last_close"),
            ("Cal d high→low", "num", "cal_days_high_to_low"),
            ("Cal d since ATH", "num", "cal_days_since_ath"),
            ("Td high→low", "num", "td_days_high_to_low"),
            ("Status", "text", "status"),
        ],
    )
    at_ath_html = _simple_table(
        at_ath_rows,
        [
            ("Symbol", "text", "symbol"),
            ("ATH #", "num", "ath_seq"),
            ("ATH date", "date", "ath_date"),
            ("ATH close", "num", "ath_close"),
            ("Status", "text", "status"),
        ],
    )

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Top-50 ATH drawdowns — {STAMP_ID}</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 24px; color: #0f172a; background: #f8fafc; }}
h1 {{ font-size: 1.45rem; margin: 0 0 4px; }}
h2 {{ font-size: 1.15rem; margin: 1.6rem 0 .5rem; border-bottom: 1px solid #cbd5e1; padding-bottom: .25rem; }}
.sub, .meta {{ color: #475569; font-size: .92rem; max-width: 72rem; line-height: 1.5; }}
.callout {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: .85rem 1rem; margin: .75rem 0; max-width: 72rem; }}
.cards {{ display: flex; flex-wrap: wrap; gap: 12px; margin: 16px 0 24px; }}
.card {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px 16px; min-width: 200px; flex: 1 1 200px; }}
.card h3 {{ margin: 0 0 8px; font-size: 13px; color: #475569; }}
.metric {{ font-size: 1.35rem; font-weight: 700; line-height: 1.2; }}
.small {{ font-size: 12px; color: #64748b; }}
.muted {{ color: #94a3b8; }}
.table-wrap {{ overflow-x: auto; margin: 8px 0; }}
table.sortable {{ border-collapse: collapse; background: #fff; font-size: 12px; width: 100%; }}
table.sortable th, table.sortable td {{ border: 1px solid #e2e8f0; padding: 6px 8px; text-align: left; vertical-align: top; }}
table.sortable th {{ background: #f1f5f9; }}
tr.open td {{ background: #fff7ed; }}
tr.ath td {{ background: #f0fdf4; }}
a.sym {{ color: #1d4ed8; text-decoration: none; font-weight: 600; }}
a.sym:hover {{ text-decoration: underline; }}
input.filter {{ padding: 6px 10px; border: 1px solid #cbd5e1; border-radius: 6px; min-width: 220px; }}
{spx.SORTABLE_TH_CSS}
</style></head><body>
<h1>Top-50 closing ATH drawdowns — 2026-09-16</h1>
<p class="sub">Research ledger only. Not gold. Not DailyRun. Stamp <code>{STAMP_ID}</code>.
OHLC { _esc(ohlc_start) } → { _esc(ohlc_end) }. Membership years { _esc(year_span) }.
Click column headers to sort.</p>
<div class="callout">
<h2 style="margin-top:0">What you asked</h2>
<p>{_esc(ORIGINAL_REQUEST)}</p>
<h2>In plain English</h2>
<p>{_esc(LAYMAN)}</p>
</div>
<div class="cards">{cards()}</div>

<h2>Cross-stock aggregates</h2>
<p class="small">Two weightings: <strong>event-equal</strong> (every all-time high (ATH) once) and <strong>stock-equal</strong> (each name once, from that name's own average or median). Recovery columns ignore open / not-yet legs. Trough / % drop ignore last-bar ATHs with no forward window. Calendar days = date difference; td = trading days (valid-close bars).</p>
<div class="table-wrap"><table class="sortable"><thead><tr>{cross_head}</tr></thead><tbody>{''.join(cross_body)}</tbody></table></div>
<p class="small">Stock-equal median of stock medians (all events) — calendar days high→low {_fmt_num(st_med.get('median_cal_days_high_to_low'), 1)}, % drop {_fmt_pct(st_med.get('median_pct_drop'))}, days low→new high {_fmt_num(st_med.get('median_cal_days_low_to_new_high'), 1)}.
Event-equal 10%+ drop slice — days high→low {_fmt_num(ge10_row.get('median_cal_days_high_to_low'), 1)}, % drop {_fmt_pct(ge10_row.get('median_pct_drop'))}, days low→new high {_fmt_num(ge10_row.get('median_cal_days_low_to_new_high'), 1)} (N={_fmt_int(ge10_row.get('n_events'))}).
Most raw events are the next session: a new closing ATH, a tiny (or gap-up) low, then another ATH. Use the 5%+ / 10%+ rows when you want “real” pullbacks.</p>

<h2 id="stocks">Per-stock summary</h2>
<p class="small">Click a ticker to filter the events table. Full per-name lists also live in <code>events/SYMBOL.csv</code>. % never recovered = open legs / highs that had a trough window (usually the current ATH only).</p>
<div class="table-wrap"><table class="sortable"><thead><tr>{stock_head}</tr></thead><tbody>{''.join(stock_body)}</tbody></table></div>

<h2 id="open">Still open — never made a new high after the last trough</h2>
<p class="small">By construction this is each name's <em>latest</em> sample ATH (every earlier ATH recovered when the next one printed). Sorted by % drop to the trough. “% off ATH (last close)” is where the latest close sits versus that high — it can be above the trough if the stock bounced. Excluded from recovery averages.</p>
{open_html}

<h2 id="at-ath">Currently at the sample ATH</h2>
<p class="small">Last bar in the file is itself a new closing high — no later low to measure yet.</p>
{at_ath_html}

<h2 id="events">All ATH events</h2>
<p class="small">Full list. Filter by ticker (also set by the stock-summary links). Combined CSV: <a href="all_events.csv">all_events.csv</a>.</p>
<p><label class="small">Filter symbol <input class="filter" id="symFilter" type="search" placeholder="e.g. AAPL" /></label>
<button type="button" class="filter" data-slice="all">All</button>
<button type="button" class="filter" data-slice="open">Open only</button>
<button type="button" class="filter" data-slice="ge5">Drop ≥5%</button>
<button type="button" class="filter" data-slice="ge10">Drop ≥10%</button>
<span class="small" id="filterCount"></span></p>
<div class="table-wrap"><table class="sortable" id="eventsTable"><thead><tr>{ev_head}</tr></thead><tbody>{''.join(ev_body)}</tbody></table></div>

<h2>Definitions</h2>
<ul class="meta">
<li><strong>ATH</strong> — all-time high: new <em>closing</em> high in the local sample (first DuckDB bar, usually 2010-01-04 or the IPO). Not a 52-week high.</li>
<li><strong>S&amp;P 500</strong> — Standard &amp; Poor's 500. Membership here is today's Wikipedia list projected backward (survivorship), then annual top 50 by approx market cap.</li>
<li><strong>Lowest low after</strong> — lowest daily <em>Low</em> in (ATH date, next ATH] (or through the last bar if still open).</li>
<li><strong>Days</strong> — calendar days and trading days are both stored. Headline numbers are calendar unless labeled td.</li>
<li><strong>Recovery</strong> — first later close that exceeds the ATH close. Open / not yet if that has not happened. Every non-final ATH recovers by definition (the next ATH is that close).</li>
<li><strong>Gap-up / stair-step</strong> — if the next bar's Low is still above the ATH close, % drop is stored as 0 (no trade below the high).</li>
</ul>
<p class="meta">Caveats: survivorship; scaled-now market caps; sample starts 2010; dividends ignored. See <a href="BASELINE.md">BASELINE.md</a>.</p>
<script>
{spx.SORTABLE_TABLE_SCRIPT}
(function(){{
  var input = document.getElementById("symFilter");
  var table = document.getElementById("eventsTable");
  var count = document.getElementById("filterCount");
  var slice = "all";
  function apply(sym){{
    var q = (sym || "").trim().toUpperCase();
    if (input && input.value.toUpperCase() !== q) input.value = q;
    var rows = table ? table.tBodies[0].querySelectorAll("tr") : [];
    var shown = 0;
    rows.forEach(function(r){{
      var ok = !q || (r.getAttribute("data-sym") || "") === q;
      var st = r.getAttribute("data-status") || "";
      var drop = parseFloat(r.getAttribute("data-drop") || "0");
      if (slice === "open") ok = ok && st === "open_unrecovered";
      if (slice === "ge5") ok = ok && drop >= 5;
      if (slice === "ge10") ok = ok && drop >= 10;
      r.style.display = ok ? "" : "none";
      if (ok) shown++;
    }});
    if (count) count.textContent = "showing " + shown + " events" + (q ? (" for " + q) : "") + (slice !== "all" ? (" [" + slice + "]") : "");
  }}
  if (input) input.addEventListener("input", function(){{ apply(input.value); }});
  document.querySelectorAll("a.sym[data-filter]").forEach(function(a){{
    a.addEventListener("click", function(){{ apply(a.getAttribute("data-filter")); }});
  }});
  document.querySelectorAll("button[data-slice]").forEach(function(b){{
    b.addEventListener("click", function(){{ slice = b.getAttribute("data-slice") || "all"; apply(input ? input.value : ""); }});
  }});
  function fromHash(){{
    var h = (location.hash || "").replace("#sym-","").replace("#","");
    if (h) apply(h);
    else apply(input ? input.value : "");
  }}
  window.addEventListener("hashchange", fromHash);
  fromHash();
}})();
</script>
</body></html>
"""
    path.write_text(html, encoding="utf-8")


def main() -> int:
    t0 = time.time()
    STAMP_DIR.mkdir(parents=True, exist_ok=True)
    (STAMP_DIR / "events").mkdir(exist_ok=True)

    print("[ath] loading Wikipedia S&P 500 list + mcaps...", flush=True)
    wiki = _load_wiki()
    import duckdb

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        db_syms = {str(r[0]).upper() for r in con.execute("SELECT DISTINCT symbol FROM prices").fetchall()}
    finally:
        con.close()
    universe = [s for s in wiki if s in db_syms]
    missing = [s for s in wiki if s not in db_syms]
    mcap = _load_mcaps(universe)
    if "GOOG" in mcap and "GOOGL" in mcap:
        mcap.pop("GOOG", None)
        print("[ath] dropped dual-class GOOG", flush=True)
    print(f"[ath] wiki {len(wiki)} universe {len(universe)} mcap {len(mcap)} missing {len(missing)}", flush=True)

    load_syms = sorted(set(list(mcap.keys()) + ["SPY"]))
    print(f"[ath] loading OHLC for {len(load_syms)} symbols...", flush=True)
    raw = _load_ohlc(load_syms)
    closes = raw.pivot(index="Date", columns="symbol", values="Close").sort_index()
    if "SPY" in closes.columns:
        spy = closes["SPY"].dropna()
        closes = closes.reindex(spy.index)

    membership, years_by_sym = _annual_top_x(closes, mcap, x=TOP_X, start_year=MEMBERSHIP_START_YEAR)
    ever = sorted(years_by_sym)
    if not ever:
        raise RuntimeError("No top-50 members found")
    print(f"[ath] ever top {TOP_X}: {len(ever)} names, {len(membership)} membership rows", flush=True)

    events: list[dict[str, Any]] = []
    raw_by = {s: g for s, g in raw.groupby("symbol", sort=False)}
    for i, sym in enumerate(ever, 1):
        frame = raw_by.get(sym)
        if frame is None or frame.empty:
            print(f"[ath] skip {sym}: no OHLC", flush=True)
            continue
        evs = _ath_events_for_symbol(sym, frame, years_top50=years_by_sym.get(sym, []))
        events.extend(evs)
        if i % 20 == 0 or i == len(ever):
            print(f"[ath] scored {i}/{len(ever)} names, {len(events)} events", flush=True)

    ev_df = pd.DataFrame(events)
    stocks = _stock_aggregates(events, years_by_sym)
    cross = _cross_aggregates(ev_df, stocks)
    open_rows = ev_df[ev_df["status"] == "open_unrecovered"].sort_values(
        ["pct_drop", "symbol"], ascending=[False, True]
    )
    at_ath_rows = ev_df[ev_df["status"] == "at_sample_ath"].sort_values(["symbol", "ath_seq"])

    ev_cols = [
        "symbol",
        "ath_seq",
        "ath_date",
        "ath_close",
        "trough_date",
        "trough_low",
        "pct_drop",
        "cal_days_high_to_low",
        "td_days_high_to_low",
        "low_source",
        "trough_above_ath_close",
        "next_ath_date",
        "next_ath_close",
        "cal_days_low_to_new_high",
        "td_days_low_to_new_high",
        "status",
        "recovered",
        "last_close",
        "last_date",
        "pct_off_ath_last_close",
        "cal_days_since_ath",
        "years_in_top50",
        "n_years_top50",
        "first_top50_year",
        "last_top50_year",
        "ohlc_start",
        "ohlc_end",
    ]
    ev_df = ev_df[ev_cols].sort_values(["symbol", "ath_seq"])
    ev_df.to_csv(STAMP_DIR / "all_events.csv", index=False)
    for sym, g in ev_df.groupby("symbol", sort=True):
        g.to_csv(STAMP_DIR / "events" / f"{sym}.csv", index=False)
    stocks.to_csv(STAMP_DIR / "stock_aggregates.csv", index=False)
    cross.to_csv(STAMP_DIR / "cross_stock_aggregates.csv", index=False)
    open_rows.to_csv(STAMP_DIR / "open_unrecovered.csv", index=False)
    at_ath_rows.to_csv(STAMP_DIR / "at_sample_ath.csv", index=False)
    membership.to_csv(STAMP_DIR / "membership_annual_top50.csv", index=False)
    (STAMP_DIR / "universe_ever_top50.txt").write_text("\n".join(ever) + "\n", encoding="utf-8")
    (STAMP_DIR / "universe_missing.txt").write_text("\n".join(missing) + "\n", encoding="utf-8")

    ohlc_start = str(pd.Timestamp(raw["Date"].min()).date())
    ohlc_end = str(pd.Timestamp(raw["Date"].max()).date())
    ev_med = cross[(cross["scope"] == "all_events") & (cross["weighting"] == "event_equal")].iloc[0].to_dict()
    _write_baseline(
        STAMP_DIR / "BASELINE.md",
        n_names=len(ever),
        n_events=len(ev_df),
        names=ever,
        membership_years=sorted({int(y) for y in membership["year"]}),
        ohlc_start=ohlc_start,
        ohlc_end=ohlc_end,
        wiki_n=len(wiki),
        universe_n=len(universe),
        mcap_n=len(mcap),
        missing_n=len(missing),
        event_med=ev_med,
        n_open=int(len(open_rows)),
        n_at_ath=int(len(at_ath_rows)),
    )
    _write_html(
        STAMP_DIR / "report.html",
        events=ev_df,
        stocks=stocks,
        cross=cross,
        open_rows=open_rows,
        at_ath_rows=at_ath_rows,
        n_names=len(ever),
        n_events=len(ev_df),
        ohlc_start=ohlc_start,
        ohlc_end=ohlc_end,
        membership_years=sorted({int(y) for y in membership["year"]}),
    )
    # Alias requested as compare.html or report.html
    (STAMP_DIR / "compare.html").write_text(
        (STAMP_DIR / "report.html").read_text(encoding="utf-8"), encoding="utf-8"
    )

    summary = {
        "stamp": STAMP_ID,
        "n_names": len(ever),
        "n_events": int(len(ev_df)),
        "n_open_unrecovered": int(len(open_rows)),
        "n_at_sample_ath": int(len(at_ath_rows)),
        "ohlc_start": ohlc_start,
        "ohlc_end": ohlc_end,
        "membership_years": sorted({int(y) for y in membership["year"]}),
        "event_equal": {k: ev_med[k] for k in ev_med if k not in ("note",)},
        "elapsed_sec": time.time() - t0,
        "not_dailyrun": True,
    }
    (STAMP_DIR / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("n_names", "n_events", "n_open_unrecovered", "n_at_sample_ath")}, indent=2))
    print(f"[ath] wrote {STAMP_DIR} in {time.time() - t0:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
