#!/usr/bin/env python3
"""Ledger of every clean break of the highest 15-minute zone.

Same buy as the preferred look on hv15m_day_zone_forward_20260925 and
hv15m_clean_break_nmax_exit_20260926:

- Zone: highest-volume 15-minute candle that starts before 15:45 ET.
- Memory: 20 trading sessions.
- Clean break: the whole bar is above that zone's high, the prior close
  was not, and it is the first time for that zone.
- Bought: next 15-minute open (blank if that bar is not in the tape).
- Sold: close of the 26th 15-minute bar from the fill (the original score).
  Blank when those bars are not in the tape yet. Not a stop.

Research ledger only. Not gold. Not DailyRun. Not the daily Volume Zone system.
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import hv15m_day_zone_forward_20260925 as base  # noqa: E402

STAMP = ROOT / "drive" / "paul_experiments" / "hv15m_clean_break_n20_signal_ledger_20260927"
CACHE = ROOT / "drive" / "paul_experiments" / "hv15m_clean_break_n20_live_20260926" / "cache_15m.parquet"
PARENT_SIGNALS = ROOT / "drive" / "paul_experiments" / "hv15m_day_zone_forward_20260925" / "signals.csv"
DB_PATH = ROOT / "data" / "ohlcv.duckdb"
YF_CACHE = ROOT / "yfinance_cache.json"
FUND_DB = ROOT / "drive" / "fundamentals_cache.duckdb"

N = 20
H1 = 26
YEAR_BARS = 252
MIN_YEAR_BARS = 20

ORIGINAL_REQUEST = (
    "for the hv15m syatem, can you show me a file of all signals when there is a "
    "clean break of the highest zone. define for me exactly what this means. "
    "show me the highest zone time of day. the distance from the yearly high, "
    "and the ohlc of the day after the signal and the open of the next day. "
    "price bought, price sold and anything else you think might be helpful, "
    "market cap, atr"
)

CSV_COLUMNS = [
    "symbol",
    "signal_date",
    "signal_time_et",
    "zone_date",
    "zone_time_et",
    "zone_age_sessions",
    "zone_high",
    "zone_low",
    "zone_volume",
    "signal_open",
    "signal_high",
    "signal_low",
    "signal_close",
    "signal_volume",
    "buy_date",
    "buy_time_et",
    "price_bought",
    "sell_date",
    "sell_bar_time_et",
    "price_sold",
    "pnl_pct",
    "status",
    "high_252d",
    "high_252d_date",
    "high_252d_lookback_days",
    "pct_below_252d_high_at_signal_close",
    "pct_below_252d_high_at_buy",
    "ytd_high",
    "ytd_high_date",
    "pct_below_ytd_high_at_buy",
    "signal_day_open",
    "signal_day_high",
    "signal_day_low",
    "signal_day_close",
    "next_day",
    "next_day_open",
    "next_day_high",
    "next_day_low",
    "next_day_close",
    "next_day_source",
    "atr14",
    "atr14_pct_of_buy",
    "market_cap_at_buy",
    "market_cap_current",
    "mcap_as_of",
    "sector",
    "industry",
    "pct_above_zone_high_at_buy",
    "risk_to_zone_low_pct",
    "mfe_pct",
    "mae_pct",
    "buy_is_next_day_open",
]


def _bkt_label(bucket: int) -> str:
    return base._bkt_label(int(bucket))


def _iso(d) -> str:
    return pd.Timestamp(d).date().isoformat()


def _f(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return float("nan")
    return v if np.isfinite(v) else float("nan")


def _zones(day, bucket, low, high, vol, sess, good_days):
    s_count = len(good_days)
    z_lo = np.full(s_count, np.nan)
    z_hi = np.full(s_count, np.nan)
    z_bkt = np.full(s_count, -1, dtype=np.int16)
    z_bar = np.full(s_count, -1, dtype=np.int32)
    z_vol = np.full(s_count, np.nan)
    for s, d in enumerate(good_days):
        idx = np.flatnonzero((day == d) & (sess == s))
        idx = idx[bucket[idx] < 25]
        if len(idx) == 0:
            continue
        best = idx[int(np.lexsort((bucket[idx], -vol[idx]))[0])]
        lo = float(low[best])
        hi = float(high[best])
        mid = 0.5 * (lo + hi)
        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo or mid <= 0:
            continue
        if (hi - lo) / mid < 0.0005:
            continue
        z_lo[s] = lo
        z_hi[s] = hi
        z_bkt[s] = int(bucket[best])
        z_bar[s] = int(best)
        z_vol[s] = float(vol[best])
    valid = np.isfinite(z_lo) & np.isfinite(z_hi) & (z_bkt >= 0)
    return z_lo, z_hi, z_bkt, z_bar, z_vol, valid


def _prior_best(z_hi, valid):
    s_count = len(z_hi)
    idx = np.full(s_count, -1, dtype=np.int32)
    best = np.full(s_count, -1e300)
    for s in range(s_count):
        s0 = s - N
        if s0 < 0:
            s0 = 0
        bhi = -1e300
        bi = -1
        for zs in range(s0, s):
            if not valid[zs] or (s - zs) > N:
                continue
            zh = float(z_hi[zs])
            if zh > bhi or (zh == bhi and zs > bi):
                bhi = zh
                bi = zs
        idx[s] = bi
        if bi >= 0:
            best[s] = bhi
    return idx, best


def scan_symbol(sym: str, g: pd.DataFrame) -> list[dict]:
    g = g.sort_values(["day", "bucket"])
    day = g["day"].to_numpy()
    bucket = g["bucket"].to_numpy(dtype=np.int16)
    o = g["open"].to_numpy(dtype=np.float64)
    h = g["high"].to_numpy(dtype=np.float64)
    l = g["low"].to_numpy(dtype=np.float64)
    c = g["close"].to_numpy(dtype=np.float64)
    v = g["volume"].to_numpy(dtype=np.float64)
    n = len(c)
    if n < 5:
        return []
    uniq = pd.unique(day)
    counts = pd.Series(day).value_counts()
    good_days = [d for d in uniq if int(counts.get(d, 0)) >= base.MIN_BARS_SESSION]
    if len(good_days) < base.MIN_SESSIONS:
        return []
    day_to_s = {d: i for i, d in enumerate(good_days)}
    sess = np.fromiter((day_to_s.get(d, -1) for d in day), dtype=np.int16, count=n)
    z_lo, z_hi, z_bkt, z_bar, z_vol, valid = _zones(day, bucket, l, h, v, sess, good_days)
    prior_i, prior_hi = _prior_best(z_hi, valid)
    clean_done = np.zeros(len(good_days), dtype=np.int8)
    rows: list[dict] = []
    for j in range(1, n):
        s = int(sess[j])
        if s < 0 or int(sess[j - 1]) < 0:
            continue
        hi_z = int(prior_i[s])
        best_hi = float(prior_hi[s]) if hi_z >= 0 else -1e300
        if valid[s] and int(bucket[j]) > int(z_bkt[s]):
            zh_today = float(z_hi[s])
            if zh_today > best_hi or (zh_today == best_hi and s > hi_z):
                hi_z = s
                best_hi = zh_today
        if hi_z < 0 or clean_done[hi_z]:
            continue
        zh = float(z_hi[hi_z])
        if not (l[j] > zh and c[j] > zh and c[j - 1] <= zh):
            continue
        clean_done[hi_z] = 1
        entry_i = j + 1
        bought = float("nan")
        buy_day = ""
        buy_time = ""
        if entry_i < n:
            bought = float(o[entry_i])
            if not np.isfinite(bought) or bought <= 0:
                bought = float("nan")
            else:
                buy_day = _iso(day[entry_i])
                buy_time = _bkt_label(int(bucket[entry_i]))
        sold = float("nan")
        sell_day = ""
        sell_time = ""
        mfe = float("nan")
        mae = float("nan")
        status = "waiting_next_open"
        if np.isfinite(bought):
            status = "open"
            end = entry_i + H1
            if end <= n:
                hold_h = h[entry_i:end]
                hold_l = l[entry_i:end]
                sold = float(c[end - 1])
                sell_i = end - 1
                sell_day = _iso(day[sell_i])
                sell_time = _bkt_label(int(bucket[sell_i]))
                status = "closed"
                if np.isfinite(sold):
                    mfe = float(np.nanmax(hold_h)) / bought - 1.0
                    mae = float(np.nanmin(hold_l)) / bought - 1.0
                else:
                    sold = float("nan")
                    status = "open"
        zb = int(z_bar[hi_z])
        pnl = sold / bought - 1.0 if np.isfinite(sold) and np.isfinite(bought) and bought > 0 else float("nan")
        above = bought / zh - 1.0 if np.isfinite(bought) and zh > 0 else float("nan")
        risk = (bought - float(z_lo[hi_z])) / bought if np.isfinite(bought) and bought > 0 else float("nan")
        buy_is_next_open = ""
        if buy_day:
            buy_is_next_open = "yes" if buy_day != _iso(day[j]) and buy_time == "09:30" else "no"
        rows.append(
            {
                "symbol": sym,
                "signal_date": _iso(day[j]),
                "signal_time_et": _bkt_label(int(bucket[j])),
                "zone_date": _iso(good_days[hi_z]),
                "zone_time_et": _bkt_label(int(z_bkt[hi_z])),
                "zone_age_sessions": int(s - hi_z),
                "zone_high": zh,
                "zone_low": float(z_lo[hi_z]),
                "zone_volume": float(z_vol[hi_z]),
                "signal_open": float(o[j]),
                "signal_high": float(h[j]),
                "signal_low": float(l[j]),
                "signal_close": float(c[j]),
                "signal_volume": float(v[j]),
                "buy_date": buy_day,
                "buy_time_et": buy_time,
                "price_bought": bought,
                "sell_date": sell_day,
                "sell_bar_time_et": sell_time,
                "price_sold": sold,
                "pnl_pct": pnl,
                "status": status,
                "zone_bar_open": float(o[zb]) if zb >= 0 else float("nan"),
                "pct_above_zone_high_at_buy": above,
                "risk_to_zone_low_pct": risk,
                "mfe_pct": mfe,
                "mae_pct": mae,
                "buy_is_next_day_open": buy_is_next_open,
            }
        )
    return rows


def session_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    ordered = df.sort_values(["symbol", "day", "bucket"])
    out = (
        ordered.groupby(["symbol", "day"], sort=False)
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
        )
        .reset_index()
    )
    out["day"] = pd.to_datetime(out["day"]).dt.date
    out["symbol"] = out["symbol"].astype(str).str.upper()
    return out


def _next_session_map(daily: pd.DataFrame) -> dict[tuple[str, str], dict]:
    """Map (symbol, session) -> that session's OHLC and the following session."""
    out: dict[tuple[str, str], dict] = {}
    for sym, g in daily.groupby("symbol", sort=False):
        g = g.sort_values("day")
        days = g["day"].tolist()
        recs = g.to_dict("records")
        for i, rec in enumerate(recs):
            nxt = recs[i + 1] if i + 1 < len(recs) else None
            out[(sym, rec["day"].isoformat())] = {"today": rec, "next": nxt}
    return out


def _wilder_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    n = len(close)
    atr = np.full(n, np.nan)
    if n == 0:
        return atr
    tr = np.empty(n, dtype=np.float64)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
    if n < 14:
        return atr
    atr[13] = float(tr[:14].mean())
    for i in range(14, n):
        atr[i] = (atr[i - 1] * 13.0 + tr[i]) / 14.0
    return atr


def load_daily(symbols: list[str]) -> dict[str, dict]:
    if not symbols or not DB_PATH.is_file():
        return {}
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        df = con.execute(
            """
            SELECT upper(symbol) AS symbol,
                   CAST(date AS DATE) AS day,
                   open, high, low, close
            FROM prices
            WHERE date >= DATE '2025-01-01'
              AND upper(symbol) IN (SELECT * FROM UNNEST(?))
            ORDER BY symbol, date
            """,
            [symbols],
        ).fetchdf()
    finally:
        con.close()
    if df.empty:
        return {}
    df["day"] = pd.to_datetime(df["day"]).dt.date
    out: dict[str, dict] = {}
    for sym, g in df.groupby("symbol", sort=False):
        g = g.sort_values("day")
        high = g["high"].to_numpy(dtype=np.float64)
        low = g["low"].to_numpy(dtype=np.float64)
        close = g["close"].to_numpy(dtype=np.float64)
        days = [d.date() if isinstance(d, pd.Timestamp) else d for d in g["day"].tolist()]
        out[str(sym)] = {
            "day": days,
            "open": g["open"].to_numpy(dtype=np.float64),
            "high": high,
            "low": low,
            "close": close,
            "atr": _wilder_atr(high, low, close),
        }
    return out


def _prior_index(days: list, signal_day) -> int:
    """Last daily bar strictly before the signal date. -1 if none."""
    target = pd.Timestamp(signal_day).date()
    lo, hi = 0, len(days)
    while lo < hi:
        mid = (lo + hi) // 2
        if days[mid] < target:
            lo = mid + 1
        else:
            hi = mid
    return lo - 1


def _window_high(days, high, i_exclusive: int, lookback: int | None, year: int | None):
    if i_exclusive < 0:
        return float("nan"), "", 0
    start = 0 if lookback is None else max(0, i_exclusive - lookback)
    if year is not None:
        # calendar-year high, still strictly before the signal day
        idxs = [k for k in range(start, i_exclusive) if days[k].year == year]
        if not idxs:
            return float("nan"), "", 0
        sl = np.array(idxs, dtype=int)
        window = high[sl]
        n_used = int(len(sl))
        mx = float(np.nanmax(window))
        if not np.isfinite(mx):
            return float("nan"), "", n_used
        rel = int(np.flatnonzero(window == mx)[-1])
        return mx, days[int(sl[rel])].isoformat(), n_used
    window = high[start:i_exclusive]
    n_used = int(len(window))
    if n_used == 0:
        return float("nan"), "", 0
    mx = float(np.nanmax(window))
    if not np.isfinite(mx):
        return float("nan"), "", n_used
    rel = int(np.flatnonzero(window == mx)[-1])
    return mx, days[start + rel].isoformat(), n_used


def _pct_below(high: float, price: float) -> float:
    if not np.isfinite(high) or high <= 0 or not np.isfinite(price):
        return float("nan")
    return (high - price) / high


def attach_daily(rows: list[dict], tape: dict, daily: dict[str, dict]) -> None:
    for rec in rows:
        slot = tape.get((rec["symbol"], rec["signal_date"]))
        if slot and slot["today"] is not None:
            t = slot["today"]
            rec["signal_day_open"] = float(t["open"])
            rec["signal_day_high"] = float(t["high"])
            rec["signal_day_low"] = float(t["low"])
            rec["signal_day_close"] = float(t["close"])
        else:
            rec["signal_day_open"] = float("nan")
            rec["signal_day_high"] = float("nan")
            rec["signal_day_low"] = float("nan")
            rec["signal_day_close"] = float("nan")
        nxt = slot["next"] if slot else None
        source = ""
        if nxt is not None:
            source = "15m"
        pack = daily.get(rec["symbol"])
        if nxt is None and pack is not None:
            i = _prior_index(pack["day"], rec["signal_date"])
            # next daily bar is the first one on or after signal_date, then the one after if that IS the signal day
            target = pd.Timestamp(rec["signal_date"]).date()
            k = i + 1
            if k < len(pack["day"]) and pack["day"][k] == target:
                k += 1
            if k < len(pack["day"]):
                nxt = {
                    "day": pack["day"][k],
                    "open": pack["open"][k],
                    "high": pack["high"][k],
                    "low": pack["low"][k],
                    "close": pack["close"][k],
                }
                source = "daily"
        if nxt is None:
            rec["next_day"] = ""
            rec["next_day_open"] = float("nan")
            rec["next_day_high"] = float("nan")
            rec["next_day_low"] = float("nan")
            rec["next_day_close"] = float("nan")
            rec["next_day_source"] = ""
        else:
            nd = nxt["day"]
            rec["next_day"] = nd.isoformat() if hasattr(nd, "isoformat") else _iso(nd)
            rec["next_day_open"] = float(nxt["open"])
            rec["next_day_high"] = float(nxt["high"])
            rec["next_day_low"] = float(nxt["low"])
            rec["next_day_close"] = float(nxt["close"])
            rec["next_day_source"] = source
        if not pack:
            rec["high_252d"] = float("nan")
            rec["high_252d_date"] = ""
            rec["high_252d_lookback_days"] = 0
            rec["pct_below_252d_high_at_signal_close"] = float("nan")
            rec["pct_below_252d_high_at_buy"] = float("nan")
            rec["ytd_high"] = float("nan")
            rec["ytd_high_date"] = ""
            rec["pct_below_ytd_high_at_buy"] = float("nan")
            rec["atr14"] = float("nan")
            rec["atr14_pct_of_buy"] = float("nan")
            continue
        i = _prior_index(pack["day"], rec["signal_date"])
        hi, hi_date, n_used = _window_high(pack["day"], pack["high"], i + 1, YEAR_BARS, None)
        if n_used < MIN_YEAR_BARS:
            hi, hi_date, n_used = float("nan"), "", n_used
        rec["high_252d"] = hi
        rec["high_252d_date"] = hi_date
        rec["high_252d_lookback_days"] = n_used
        rec["pct_below_252d_high_at_signal_close"] = _pct_below(hi, rec["signal_close"])
        buy = rec["price_bought"]
        rec["pct_below_252d_high_at_buy"] = _pct_below(hi, buy)
        year = pd.Timestamp(rec["signal_date"]).year
        yhi, ydate, _yn = _window_high(pack["day"], pack["high"], i + 1, None, year)
        rec["ytd_high"] = yhi
        rec["ytd_high_date"] = ydate
        rec["pct_below_ytd_high_at_buy"] = _pct_below(yhi, buy if np.isfinite(buy) else rec["signal_close"])
        atr = float(pack["atr"][i]) if i >= 0 else float("nan")
        rec["atr14"] = atr
        rec["atr14_pct_of_buy"] = atr / buy if np.isfinite(atr) and np.isfinite(buy) and buy > 0 else float("nan")


def _load_yf() -> dict[str, dict]:
    if not YF_CACHE.is_file():
        return {}
    try:
        raw = json.loads(YF_CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _fund_fallback(symbols: list[str]) -> dict[str, dict]:
    if not symbols or not FUND_DB.is_file():
        return {}
    try:
        con = duckdb.connect(str(FUND_DB), read_only=True)
    except Exception:
        return {}
    out: dict[str, dict] = {}
    try:
        rows = con.execute(
            """
            SELECT symbol, market_cap, raw_json
            FROM yf_symbol_info
            WHERE symbol IN (SELECT * FROM UNNEST(?))
            """,
            [symbols],
        ).fetchall()
        for sym, mc, raw in rows:
            info: dict = {}
            if raw:
                try:
                    j = json.loads(raw) if isinstance(raw, str) else raw
                except (TypeError, json.JSONDecodeError):
                    j = None
                if isinstance(j, dict):
                    if j.get("sector"):
                        info["sector"] = j["sector"]
                    if j.get("industry"):
                        info["industry"] = j["industry"]
                    if j.get("marketCap") is not None:
                        info["market_cap"] = j["marketCap"]
                    px = j.get("currentPrice") or j.get("regularMarketPrice")
                    if px is not None:
                        info["current_price"] = px
            if mc is not None and "market_cap" not in info:
                info["market_cap"] = mc
            if info:
                out[str(sym).upper()] = info
    except Exception:
        return out
    finally:
        con.close()
    return out


def attach_mcap(rows: list[dict]) -> None:
    yf = {str(k).upper(): v for k, v in _load_yf().items()}
    need = sorted({r["symbol"] for r in rows if r["symbol"] not in yf or not (yf[r["symbol"]] or {}).get("market_cap")})
    fund = _fund_fallback(need) if need else {}
    for rec in rows:
        src = yf.get(rec["symbol"]) or {}
        if not src.get("market_cap"):
            fb = fund.get(rec["symbol"]) or {}
            src = {**fb, **{k: v for k, v in src.items() if v not in (None, "")}}
        mc = _f(src.get("market_cap"))
        px = _f(src.get("current_price"))
        rec["market_cap_current"] = mc
        rec["mcap_as_of"] = str(src.get("as_of_date") or "")
        rec["sector"] = str(src.get("sector") or "")
        rec["industry"] = str(src.get("industry") or "")
        buy = rec["price_bought"]
        if np.isfinite(mc) and np.isfinite(px) and px > 0 and np.isfinite(buy) and buy > 0:
            rec["market_cap_at_buy"] = mc * (buy / px)
        else:
            rec["market_cap_at_buy"] = float("nan")


def reconcile(df: pd.DataFrame) -> str:
    if not PARENT_SIGNALS.is_file() or df.empty:
        return "Parent signal file was not compared."
    parent = pd.read_csv(PARENT_SIGNALS)
    parent = parent[
        (parent["pattern"] == "clean_break_highest")
        & (parent["zone_rule"] == "ex_last_bar")
        & (parent["N"] == 20)
    ].copy()
    closed = df[df["status"] == "closed"].copy()
    parent["key"] = (
        parent["symbol"].str.upper()
        + "|"
        + parent["day"].astype(str)
        + "|"
        + parent["entry"].round(4).astype(str)
    )
    closed["key"] = (
        closed["symbol"].str.upper()
        + "|"
        + closed["buy_date"].astype(str)
        + "|"
        + closed["price_bought"].round(4).astype(str)
    )
    both = len(set(parent["key"]) & set(closed["key"]))
    return (
        f"Parent page listed {len(parent)} completed signals (tape ended 2026-09-24, "
        f"and a signal was kept only when 26 bars existed after the buy). "
        f"This ledger matches {both} of those on symbol, buy date, and buy price."
    )


def _num(x, nd=2) -> str:
    v = _f(x)
    if not np.isfinite(v):
        return ""
    return f"{v:.{nd}f}"


def write_csv(df: pd.DataFrame, path: Path) -> None:
    out = df.copy()
    for col in CSV_COLUMNS:
        if col not in out.columns:
            out[col] = np.nan
    price_cols = [
        "zone_high", "zone_low", "signal_open", "signal_high", "signal_low", "signal_close",
        "price_bought", "price_sold", "high_252d", "ytd_high",
        "signal_day_open", "signal_day_high", "signal_day_low", "signal_day_close",
        "next_day_open", "next_day_high", "next_day_low", "next_day_close", "atr14",
    ]
    pct_cols = [
        "pnl_pct", "pct_below_252d_high_at_signal_close", "pct_below_252d_high_at_buy",
        "pct_below_ytd_high_at_buy", "atr14_pct_of_buy", "pct_above_zone_high_at_buy",
        "risk_to_zone_low_pct", "mfe_pct", "mae_pct",
    ]
    for col in price_cols:
        out[col] = out[col].map(lambda x: _num(x, 4))
    for col in pct_cols:
        out[col] = out[col].map(lambda x: _num(x, 6))
    for col in ("zone_volume", "signal_volume", "market_cap_at_buy", "market_cap_current"):
        out[col] = out[col].map(lambda x: _num(x, 2))
    out[CSV_COLUMNS].to_csv(path, index=False)


def _esc(x) -> str:
    return html.escape("" if x is None else str(x))


def _cell_px(x) -> str:
    v = _f(x)
    if not np.isfinite(v):
        return "—"
    if abs(v) >= 1:
        return f"{v:,.2f}"
    return f"{v:.4f}"


def _cell_pct(x) -> str:
    v = _f(x)
    if not np.isfinite(v):
        return "—"
    return f"{v * 100:.2f}%"


def _cell_m(x) -> str:
    v = _f(x)
    if not np.isfinite(v):
        return "—"
    return f"{v / 1_000_000:.2f}"


def _th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{html.escape(label)}<span class="sort-ind"></span></th>'
    )


SORT_SCRIPT = """
<script>
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : NaN;
    if (type === "text") return s.toUpperCase();
    if (type === "date") {
      var iso = s.match(/(\\d{4})-(\\d{2})-(\\d{2})/);
      if (iso) return parseInt(iso[1] + iso[2] + iso[3], 10);
      return NaN;
    }
    var n = s.replace(/[$,%+]/g, "").replace(/,/g, "");
    var v = parseFloat(n);
    return Number.isFinite(v) ? v : NaN;
  }
  function sortTable(table, col, type, dir) {
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var rows = Array.from(tbody.querySelectorAll("tr"));
    var pinned = rows.filter(function (r) { return r.classList.contains("total-row"); });
    var movable = rows.filter(function (r) { return !r.classList.contains("total-row"); });
    movable.sort(function (a, b) {
      var av = parseSortValue(a.cells[col] ? a.cells[col].textContent : "", type);
      var bv = parseSortValue(b.cells[col] ? b.cells[col].textContent : "", type);
      var aMiss = typeof av === "number" && !Number.isFinite(av);
      var bMiss = typeof bv === "number" && !Number.isFinite(bv);
      if (aMiss && bMiss) return 0;
      if (aMiss) return 1;
      if (bMiss) return -1;
      if (typeof av === "string" || typeof bv === "string") return dir * String(av).localeCompare(String(bv));
      return dir * (av - bv);
    });
    movable.concat(pinned).forEach(function (r) { tbody.appendChild(r); });
  }
  document.querySelectorAll("table.sortable").forEach(function (table) {
    var headers = table.querySelectorAll("th.sortable-th");
    headers.forEach(function (th, col) {
      function activate(ev) {
        if (ev.type === "keydown" && ev.key !== "Enter" && ev.key !== " ") return;
        if (ev.type === "keydown") ev.preventDefault();
        var type = th.getAttribute("data-sort") || "text";
        var dir = th.classList.contains("sort-asc") ? -1 : 1;
        headers.forEach(function (h) {
          h.classList.remove("sort-asc", "sort-desc");
          h.setAttribute("aria-sort", "none");
        });
        th.classList.add(dir === 1 ? "sort-asc" : "sort-desc");
        th.setAttribute("aria-sort", dir === 1 ? "ascending" : "descending");
        sortTable(table, col, type, dir);
      }
      th.addEventListener("click", activate);
      th.addEventListener("keydown", activate);
    });
  });
})();
</script>
"""


def _rows_html(df: pd.DataFrame) -> str:
    chunks = []
    for rec in df.itertuples(index=False):
        cells = [
            _esc(rec.symbol),
            _esc(rec.signal_date),
            _esc(rec.signal_time_et),
            _esc(rec.zone_date),
            _esc(rec.zone_time_et),
            str(int(rec.zone_age_sessions)),
            _cell_px(rec.zone_high),
            _cell_px(rec.zone_low),
            _cell_px(rec.price_bought),
            _esc(rec.buy_date),
            _esc(rec.buy_time_et),
            _cell_px(rec.price_sold),
            _esc(rec.sell_date),
            _esc(rec.sell_bar_time_et),
            _cell_pct(rec.pnl_pct),
            _esc(rec.status),
            _cell_px(rec.high_252d),
            _esc(rec.high_252d_date),
            _cell_pct(rec.pct_below_252d_high_at_buy if np.isfinite(_f(rec.pct_below_252d_high_at_buy)) else rec.pct_below_252d_high_at_signal_close),
            _cell_px(rec.ytd_high),
            _cell_pct(rec.pct_below_ytd_high_at_buy),
            _esc(rec.next_day),
            _cell_px(rec.next_day_open),
            _cell_px(rec.next_day_high),
            _cell_px(rec.next_day_low),
            _cell_px(rec.next_day_close),
            _cell_px(rec.signal_day_open),
            _cell_px(rec.signal_day_high),
            _cell_px(rec.signal_day_low),
            _cell_px(rec.signal_day_close),
            _cell_px(rec.atr14),
            _cell_pct(rec.atr14_pct_of_buy),
            _cell_m(rec.market_cap_at_buy),
            _esc(rec.sector),
            _cell_pct(rec.pct_above_zone_high_at_buy),
            _cell_pct(rec.risk_to_zone_low_pct),
            _cell_pct(rec.mfe_pct),
            _cell_pct(rec.mae_pct),
            _esc(rec.buy_is_next_day_open),
        ]
        chunks.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    return "\n".join(chunks)


def _zone_time_table(df: pd.DataFrame) -> str:
    if df.empty:
        return ""
    vc = df["zone_time_et"].value_counts()
    order = sorted(vc.index, key=lambda t: t)
    total = int(vc.sum())
    body = []
    for t in order:
        n = int(vc[t])
        body.append(f"<tr><td>{_esc(t)}</td><td>{n}</td><td>{n / total * 100:.1f}%</td></tr>")
    return f"""
<h2>What time of day the broken zone was born</h2>
<p>Each row in the file has its own zone time. This tally is how often that clock time shows up. The time is when the zone’s 15-minute candle <em>starts</em>, Eastern Time. A zone time of 15:30 is the candle from 3:30 to 3:45. The 3:45 close candle is never chosen as the zone.</p>
<div class="scroll">
<table class="sortable">
<caption>Count of clean breaks by the clock time of the highest zone they broke. Click column headers to sort.</caption>
<thead><tr>{_th("Zone time ET", "text")}{_th("Signals", "num")}{_th("Share", "num")}</tr></thead>
<tbody>
{"".join(body)}
</tbody>
</table>
</div>
"""


def write_html(df: pd.DataFrame, info: dict, check: str, path: Path) -> None:
    closed = df[df["status"] == "closed"]["pnl_pct"].dropna() if not df.empty else pd.Series(dtype=float)
    n = len(df)
    n_closed = int((df["status"] == "closed").sum()) if n else 0
    n_open = int((df["status"] == "open").sum()) if n else 0
    n_wait = int((df["status"] == "waiting_next_open").sum()) if n else 0
    n_at_open = int((df["signal_time_et"] == "09:30").sum()) if n else 0
    avg = float(closed.mean()) if len(closed) else float("nan")
    med = float(closed.median()) if len(closed) else float("nan")
    win = float((closed > 0).mean()) if len(closed) else float("nan")
    win_txt = f"{win * 100:.1f}%" if np.isfinite(win) else "—"
    headers = [
        ("Symbol", "text"), ("Signal date", "date"), ("Signal time", "text"),
        ("Zone date", "date"), ("Zone time", "text"), ("Zone age", "num"),
        ("Zone high", "num"), ("Zone low", "num"),
        ("Price bought", "num"), ("Buy date", "date"), ("Buy time", "text"),
        ("Price sold", "num"), ("Sell date", "date"), ("Sell bar", "text"),
        ("Result", "num"), ("Status", "text"),
        ("52-week high", "num"), ("52-week high date", "date"), ("% below 52-week high", "num"),
        ("Year-to-date high", "num"), ("% below YTD high", "num"),
        ("Next day", "date"), ("Next day open", "num"), ("Next day high", "num"),
        ("Next day low", "num"), ("Next day close", "num"),
        ("Signal day open", "num"), ("Signal day high", "num"), ("Signal day low", "num"),
        ("Signal day close", "num"),
        ("ATR", "num"), ("ATR % of buy", "num"), ("Mkt cap at buy ($M)", "num"),
        ("Sector", "text"), ("% above zone", "num"), ("Risk to zone low", "num"),
        ("Best print in hold", "num"), ("Worst print in hold", "num"),
        ("Buy is next-day open", "text"),
    ]
    head = "".join(_th(a, b) for a, b in headers)
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>HV15m clean break of the highest zone — every signal</title>
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 24px auto; max-width: 1280px; color: #1a1a1a; line-height: 1.45; }}
h1 {{ font-size: 1.55rem; }}
h2 {{ font-size: 1.2rem; margin-top: 1.6rem; }}
.callout {{ background: #f4f7fb; border: 1px solid #d5deea; padding: 12px 16px; margin: 12px 0; }}
.plain {{ background: #f8f6f1; }}
.note {{ color: #444; font-size: 0.95rem; }}
.scroll {{ overflow-x: auto; }}
table.sortable {{ border-collapse: collapse; width: 100%; font-size: 0.82rem; margin: 8px 0 18px; }}
th, td {{ border-bottom: 1px solid #e2e8f0; text-align: right; padding: 4px 6px; white-space: nowrap; }}
th:first-child, td:first-child, td:nth-child(16), td:nth-child(34) {{ text-align: left; }}
caption {{ text-align: left; font-weight: 600; margin-bottom: 6px; }}
th.sortable-th {{ cursor: pointer; user-select: none; }}
th.sortable-th:hover {{ background: #e2e8f0; }}
th.sortable-th .sort-ind::after {{ content: " \\2195"; opacity: .35; font-size: .85em; }}
th.sortable-th.sort-asc .sort-ind::after {{ content: " \\2191"; opacity: .9; }}
th.sortable-th.sort-desc .sort-ind::after {{ content: " \\2193"; opacity: .9; }}
code {{ background: #f1f5f9; padding: 0 4px; }}
</style>
</head>
<body>
<h1>Clean break of the highest zone — every signal</h1>
<p class="note">Research ledger only. Not gold. Not wired into DailyRun. Not the daily Volume Zone (VZ) system. Tape: {html.escape(info["date_min"])} through {html.escape(info["date_max"])}. Liquid symbols: {info["symbols_liquid"]}. Click a column header to sort.</p>

<div class="callout">
<h2 style="margin-top:0">What you asked</h2>
<p>{html.escape(ORIGINAL_REQUEST)}</p>
</div>
<div class="callout plain">
<h2 style="margin-top:0">In plain English</h2>
<p>Each day we draw one band: the low to the high of that day’s busiest 15-minute candle. We skip the last candle of the day, the one that starts at 3:45pm, because the closing auction often makes it the busiest for a reason that is not a story. A band stays usable for 20 trading days, and only after its own candle has finished. The highest band is the one whose top sits highest.</p>
<p>A signal is the first 15-minute candle that sits entirely above that top: the candle’s lowest price and its close are both higher, and the candle right before did not close above that top. The price bought is the open of the next 15-minute candle. The price sold in this file is the close 26 of those candles later, about one regular session, with no stop. The bottom of the band is listed (zone low) so you can see how far a stop at the band would have been. It is not the sold price.</p>
<p>The yearly-high distance is how far the buy sits under the highest daily high of the prior 252 trading days (about a year), counted only through the day before the signal. A negative percent means the buy is already above that high. Year-to-date is the high of the current calendar year, also through the day before the signal. If the buy is not in the tape yet, that 52-week percent uses the signal candle’s close instead. The day after the signal is the next session we have for that stock. Its open, high, low, and close are listed. The open of the next day is that same session’s open, in its own column. It equals the price bought only when the break is the last candle of the session, so the next candle is the next morning.</p>
<p>On this tape, {n_at_open} of the {n} signals are the 9:30 candle. That is an overnight gap: the day before closed at or under the zone, and the first 15 minutes of the new day stayed entirely above it. The buy is then the 9:45 open the same morning, not the next day’s open.</p>
</div>

<h2>Exactly what “clean break of the highest zone” means</h2>
<ol>
<li><strong>Session.</strong> Regular hours only, 9:30am to 4:00pm Eastern Time. A 15-minute bar is kept when it has at least 10 one-minute prints, a high above its low, and volume. A session counts only when it has at least {base.MIN_BARS_SESSION} such bars.</li>
<li><strong>The zone for a day.</strong> Among bars that start before 3:45pm (the 15:45 bar is left out), take the one with the most volume. If two bars tie, take the earlier one. The zone is that bar’s low to that bar’s high. Drop the day if that range is under 0.05% of the midpoint.</li>
<li><strong>Alive.</strong> On a later bar, a zone is still in play if it was born this session or within the prior {N} sessions, and, if it was born today, only once the current bar starts after that zone’s candle. Age 0 means the zone was born earlier the same day.</li>
<li><strong>Highest zone.</strong> Among the alive zones, the one with the highest zone-high. If two tops tie, the newer zone wins.</li>
<li><strong>Clean break.</strong> That highest zone has not already been broken this way. The current bar’s low is above the zone high, and its close is above the zone high, so the whole candle is clear of the band. The previous bar’s close is at or below that same zone high. The previous bar has to sit on a session that itself was complete.</li>
<li><strong>Once per zone.</strong> The first bar that meets that test uses the zone up. A later bar does not signal again on the same zone, even if the first one could not be filled because the tape ended.</li>
<li><strong>Price bought.</strong> Open of the next 15-minute bar. Blank, status <code>waiting_next_open</code>, when that bar is not in the file yet.</li>
<li><strong>Price sold.</strong> Close of the 26th 15-minute bar counting from the buy bar (the buy bar is bar 1). This is the original score from the first HV15m page: one regular session of bars, no stop. Blank, status <code>open</code>, when those 26 bars are not all in the tape. Status <code>closed</code> when both prices exist. The clock time on the sell is the start of the bar whose close is the sale.</li>
</ol>
<p class="note">Names in the file: at least {base.MIN_SESSIONS} complete sessions, a median session dollar volume (volume times close, summed over the session) of at least ${base.MIN_DOLLAR_VOL:,.0f}, and a median close of at least ${base.MIN_PRICE:.0f}. Average true range (ATR) is Wilder’s 14-day ATR on daily bars, through the session before the signal, so the signal day’s range is not inside it. Market cap is the local Yahoo snapshot scaled by buy price divided by the snapshot price (same shares, different price). It is not the market cap the company had on the signal date. A cell is blank when that input is missing.</p>
<p class="note">{html.escape(check)}</p>
<p class="note">Among the {n_closed} closed signals, the 26-bar result averages {_cell_pct(avg)} (median {_cell_pct(med)}, {win_txt} of them finished higher). That count includes names that can have more than one trade open at once. It is a description of this list, not a new exit and not a portfolio result. {n_open} signals are bought and not yet sold on this tape. {n_wait} broke on the last bar and have no buy price yet.</p>

<h2>Counts</h2>
<p>{n} signals, {df["symbol"].nunique() if n else 0} symbols, from {html.escape(str(df["signal_date"].min()) if n else "")} to {html.escape(str(df["signal_date"].max()) if n else "")}. Spreadsheet: <code>signals.csv</code> in this folder.</p>
{_zone_time_table(df)}

<h2>Every signal</h2>
<p class="note">Zone age is how many sessions the zone had been alive (0 = born earlier that same day). % below 52-week high uses the buy price; negative means the buy is above that high. Next day open is the open of the session after the signal. Best print and worst print are the highest high and lowest low during the 26-bar hold, measured from the buy. Click column headers to sort.</p>
<div class="scroll">
<table class="sortable">
<thead><tr>{head}</tr></thead>
<tbody>
{_rows_html(df)}
</tbody>
</table>
</div>
</body>
{SORT_SCRIPT}
</html>
"""
    path.write_text(page, encoding="utf-8")


def write_baseline(info: dict, check: str, path: Path) -> None:
    text = f"""# Clean break of the highest zone — signal ledger

Study id: `hv15m_clean_break_n20_signal_ledger_20260927`

Research only. Not gold. Not DailyRun. Not the daily Volume Zone (VZ) system.

Parent: `hv15m_day_zone_forward_20260925` and `hv15m_clean_break_nmax_exit_20260926`.

## What you asked

> {ORIGINAL_REQUEST}

## In plain English

A signal is the first 15-minute bar that sits entirely above the highest still-active high-volume zone. The zone is the busiest 15-minute candle of a day that starts before 15:45 Eastern Time, kept for 20 trading sessions. The buy is the next 15-minute open. The sell in this file is the close 26 bars later, the original one-session score, with no stop.

The yearly high is the highest daily high in the prior 252 trading days, through the day before the signal. The next day’s open, high, low, and close are the next session after the signal. The open of the next day is that same session’s open.

## Freeze

- Pattern: clean break of the highest zone. Zone source: exclude the 15:45 bar.
- Carry: 20 trading sessions, including the birth session once that candle has closed.
- Buy: next 15-minute open. Signals with no next bar are listed with a blank buy.
- Sell shown: close of the 26th bar from the fill. Zone low is shown and is not the sell.
- Universe: same liquid rules as the parent study. Tape {info["date_min"]} through {info["date_max"]}, {info["symbols_liquid"]} symbols.
- Yearly high and ATR use daily bars in `data/ohlcv.duckdb`, strictly before the signal date.
- Market cap is a current Yahoo snapshot scaled by buy / snapshot price. Not a historical cap.

## Check

{check}
"""
    path.write_text(text, encoding="utf-8")


def main() -> None:
    print(f"reading {CACHE}", flush=True)
    bars = pd.read_parquet(CACHE)
    liquid, info = base.select_universe(bars)
    print(f"scanning {liquid['symbol'].nunique()} symbols...", flush=True)
    rows: list[dict] = []
    for i, (sym, g) in enumerate(liquid.groupby("symbol", sort=False)):
        rows.extend(scan_symbol(str(sym), g))
        if (i + 1) % 400 == 0:
            print(f"  {i + 1} symbols, {len(rows)} signals", flush=True)
    print(f"signals {len(rows)}", flush=True)
    tape = _next_session_map(session_ohlc(liquid))
    symbols = sorted({r["symbol"] for r in rows})
    print(f"daily bars for {len(symbols)} symbols...", flush=True)
    daily = load_daily(symbols)
    attach_daily(rows, tape, daily)
    print("market cap...", flush=True)
    attach_mcap(rows)
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["signal_date", "signal_time_et", "symbol"]).reset_index(drop=True)
    check = reconcile(df)
    print(check, flush=True)
    STAMP.mkdir(parents=True, exist_ok=True)
    write_csv(df, STAMP / "signals.csv")
    write_html(df, info, check, STAMP / "signals.html")
    write_baseline(info, check, STAMP / "BASELINE.md")
    print(f"wrote {STAMP}", flush=True)


if __name__ == "__main__":
    main()
