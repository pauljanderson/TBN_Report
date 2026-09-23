"""S&P X Diversification research: equal-weight top-X by market cap, periodic rebalance.

Not wired to DailyRun. Default writes under drive/spx_diversification/.
Stamp mode (--stamp-dir) writes IS/OOS compare + turnover ledger.

Methodology (documented in comparison.md / stamp BASELINE):
- Universe: current Wikipedia S&P 500 constituents intersected with local DuckDB OHLC
  (survivorship-biased; not true historical membership).
- Market cap: point-in-time Yahoo snapshot scaled by Close_t / Close_now
  (constant-shares approximation; no true historical free-float panel in-repo).
- Annual reconstitution: first trading day of each calendar year (SPY calendar).
- Intra-year rebalance: every N trading days, equal-weight current members.
- Fills: next open after signal day. Optional proportional costs on traded notional.
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import math
import re
import time
import urllib.request
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
DB_PATH = REPO / "data" / "ohlcv.duckdb"
YF_CACHE = REPO / "yfinance_cache.json"
OUT_ROOT = REPO / "drive" / "spx_diversification"

INITIAL_CAPITAL = 500_000.0
X_GRID = (10, 20, 30, 40, 50, 60, 75, 100)
N_GRID = (1, 3, 5, 8, 10, 11,12, 13,14,15,16,17,18,19, 20, 21, 34, 50, 55)
DEFAULT_COST_BPS = 10.0  # per side on traded notional
WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


@dataclass(frozen=True)
class BacktestResult:
    X: int
    N: int
    cost_bps: float
    ok: bool
    error: str
    start: str
    end: str
    final_equity: float
    total_return: float
    cagr: float
    max_dd: float
    sharpe: float
    ann_vol: float
    total_trades: int
    turnover: float
    n_rebalances: int
    n_reconstitutions: int
    yearly_returns: dict[str, float]
    extras: dict[str, Any] | None = None


def _fetch_sp500_tickers() -> list[str]:
    req = urllib.request.Request(WIKI_URL, headers={"User-Agent": "Mozilla/5.0 (research)"})
    html = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
    m = re.search(r'<table[^>]*id="constituents"[\s\S]*?</table>', html)
    if not m:
        raise RuntimeError("Could not find Wikipedia S&P 500 constituents table")
    tickers: list[str] = []
    for row in re.findall(r"<tr[\s\S]*?</tr>", m.group(0))[1:]:
        tds = re.findall(r"<td[^>]*>([\s\S]*?)</td>", row)
        if not tds:
            continue
        sym = re.sub(r"<[^>]+>", "", tds[0]).strip().upper().replace(".", "-")
        if sym:
            tickers.append(sym)
    # Deduplicate while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _load_yf_cache() -> dict[str, dict]:
    if not YF_CACHE.is_file():
        return {}
    try:
        return json.loads(YF_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_yf_cache(cache: dict[str, dict]) -> None:
    YF_CACHE.write_text(json.dumps(cache, indent=0), encoding="utf-8")


def _fetch_one_mcap(sym: str) -> tuple[str, dict]:
    today = pd.Timestamp.now().strftime("%Y-%m-%d")
    try:
        import yfinance as yf

        info = yf.Ticker(sym).info or {}
        return sym, {
            "market_cap": info.get("marketCap") or info.get("enterpriseValue"),
            "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "beta": info.get("beta"),
            "as_of_date": today,
        }
    except Exception as exc:  # noqa: BLE001
        return sym, {"market_cap": None, "error": str(exc), "as_of_date": today}


def refresh_market_caps(symbols: list[str], *, workers: int = 12, force: bool = False) -> dict[str, float]:
    """Return {symbol: market_cap} using cache + parallel yfinance refresh for misses/stale."""
    cache = _load_yf_cache()
    today = pd.Timestamp.now().strftime("%Y-%m-%d")
    need: list[str] = []
    for sym in symbols:
        entry = cache.get(sym) or {}
        ok = entry.get("market_cap") is not None and (force or entry.get("as_of_date") == today)
        if not ok:
            need.append(sym)
    if need:
        print(f"[spx] refreshing market caps for {len(need)} symbols ({workers} workers)...", flush=True)
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            for sym, data in ex.map(_fetch_one_mcap, need):
                if data.get("market_cap") is not None:
                    cache[sym] = {k: v for k, v in data.items() if k != "error"}
                elif sym not in cache:
                    cache[sym] = data
        _save_yf_cache(cache)
    out: dict[str, float] = {}
    for sym in symbols:
        mc = (cache.get(sym) or {}).get("market_cap")
        if mc is not None and float(mc) > 0:
            out[sym] = float(mc)
    return out


def load_price_panels(symbols: list[str], *, start: str | None = None, end: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    """Load Open/Close panels aligned to SPY calendar. Returns (open, close, spy_close)."""
    import duckdb

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        syms = ["SPY"] + [s for s in symbols if s != "SPY"]
        where = ["symbol IN (SELECT * FROM UNNEST(?::VARCHAR[]))"]
        params: list[Any] = [syms]
        if start:
            where.append("date >= ?")
            params.append(start)
        if end:
            where.append("date <= ?")
            params.append(end)
        q = f"""
            SELECT symbol, date AS Date, open AS Open, close AS Close
            FROM prices
            WHERE {' AND '.join(where)}
            ORDER BY date, symbol
        """
        df = con.execute(q, params).fetchdf()
    finally:
        con.close()

    if df.empty:
        raise RuntimeError("No price rows loaded from DuckDB")

    df["Date"] = pd.to_datetime(df["Date"])
    opens = df.pivot(index="Date", columns="symbol", values="Open").sort_index()
    closes = df.pivot(index="Date", columns="symbol", values="Close").sort_index()
    if "SPY" not in closes.columns:
        raise RuntimeError("SPY missing from DuckDB prices")
    spy = closes["SPY"].dropna()
    # Align all panels to SPY trading calendar
    opens = opens.reindex(spy.index)
    closes = closes.reindex(spy.index)
    return opens, closes, spy


def _max_dd_pct(equity: np.ndarray) -> float:
    if equity.size < 2:
        return 0.0
    peak = np.maximum.accumulate(equity)
    dd = equity / peak - 1.0
    return float(-np.min(dd) * 100.0)


def _cagr(total_return: float, start: pd.Timestamp, end: pd.Timestamp) -> float:
    years = max((end - start).days / 365.25, 1e-9)
    if total_return <= -1.0:
        return -100.0
    return ((1.0 + total_return) ** (1.0 / years) - 1.0) * 100.0


def _sharpe(daily_rets: np.ndarray) -> tuple[float, float]:
    """Daily equity returns -> (Sharpe rf=0, ann vol %). Uses 252 trading days."""
    if daily_rets.size < 2:
        return 0.0, 0.0
    mu = float(np.mean(daily_rets))
    sig = float(np.std(daily_rets, ddof=1))
    if sig <= 0:
        return 0.0, 0.0
    sharpe = mu / sig * math.sqrt(252.0)
    ann_vol = sig * math.sqrt(252.0) * 100.0
    return sharpe, ann_vol


def _parse_int_list(raw: str) -> list[int]:
    return [int(x.strip()) for x in str(raw).split(",") if x.strip()]


def metrics_from_equity(
    dates: list[str],
    equity: list[float],
    *,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    """CAGR / MaxDD / Sharpe on an equity path. ``end`` is exclusive when set."""
    empty = {
        "ok": False,
        "start": "",
        "end": "",
        "n_days": 0,
        "start_equity": 0.0,
        "final_equity": 0.0,
        "total_return": 0.0,
        "cagr": 0.0,
        "max_dd": 0.0,
        "sharpe": 0.0,
        "ann_vol": 0.0,
        "calmar": None,
    }
    if not dates or not equity or len(dates) != len(equity):
        return dict(empty)
    idx = pd.to_datetime(dates)
    eq = np.asarray(equity, dtype=float)
    mask = np.isfinite(eq) & (eq > 0)
    if start:
        mask &= idx >= pd.Timestamp(start)
    if end:
        mask &= idx < pd.Timestamp(end)
    if int(mask.sum()) < 5:
        return dict(empty)
    d = idx[mask]
    e = eq[mask]
    total_ret = float(e[-1] / e[0] - 1.0)
    cagr = _cagr(total_ret, pd.Timestamp(d[0]), pd.Timestamp(d[-1]))
    max_dd = _max_dd_pct(e)
    daily = np.diff(e) / e[:-1]
    daily = daily[np.isfinite(daily)]
    sharpe, ann_vol = _sharpe(daily)
    calmar = (cagr / max_dd) if max_dd > 1e-9 else None
    return {
        "ok": True,
        "start": str(pd.Timestamp(d[0]).date()),
        "end": str(pd.Timestamp(d[-1]).date()),
        "n_days": int(len(e)),
        "start_equity": float(e[0]),
        "final_equity": float(e[-1]),
        "total_return": total_ret * 100.0,
        "cagr": cagr,
        "max_dd": max_dd,
        "sharpe": sharpe,
        "ann_vol": ann_vol,
        "calmar": calmar,
    }


def _first_trading_days_of_year(calendar: pd.DatetimeIndex) -> set[pd.Timestamp]:
    years = calendar.year
    out: set[pd.Timestamp] = set()
    for y in sorted(set(years)):
        idx = np.where(years == y)[0]
        if len(idx):
            out.add(calendar[idx[0]])
    return out


def run_one_backtest(
    *,
    X: int,
    N: int,
    cost_bps: float,
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    mcap_now: dict[str, float],
    capital0: float = INITIAL_CAPITAL,
    min_history_days: int = 60,
    collect_extras: bool = False,
    filter_members: Any | None = None,
    allow_empty: bool = False,
) -> BacktestResult:
    """Equal-weight top-X, rebalance every N days, annual membership refresh.

    Optional research overlay (default None = identical to the frozen engine):
    ``filter_members(signal_i, proposed_idxs, current_idxs, kind) -> idxs``
    is applied on the signal close before the next-open fill. ``allow_empty``
    lets the overlay cash the book (sell all); cadence still uses the last
    reconstitution roster so the book can re-enter later.
    """
    calendar = closes.index
    if len(calendar) < min_history_days + 5:
        return BacktestResult(
            X, N, cost_bps, False, "insufficient calendar", "", "", 0, 0, 0, 0, 0, 0, 0, 0.0, 0, 0, {}
        )

    syms = [c for c in closes.columns if c != "SPY" and c in mcap_now]
    if len(syms) < X:
        return BacktestResult(
            X, N, cost_bps, False, f"only {len(syms)} symbols with mcap", "", "", 0, 0, 0, 0, 0, 0, 0, 0.0, 0, 0, {}
        )

    close_arr = closes[syms].to_numpy(dtype=float)
    open_arr = opens[syms].to_numpy(dtype=float)
    mcap_vec = np.array([mcap_now[s] for s in syms], dtype=float)
    # Reference close = last valid close per symbol
    ref_close = np.full(len(syms), np.nan)
    for j in range(len(syms)):
        col = close_arr[:, j]
        valid = np.where(np.isfinite(col) & (col > 0))[0]
        if len(valid):
            ref_close[j] = col[valid[-1]]

    recon_days = _first_trading_days_of_year(calendar)
    # Start at first reconstitution day with enough prior history, else first calendar day
    start_i = min_history_days
    for i in range(min_history_days, len(calendar)):
        if calendar[i] in recon_days:
            start_i = i
            break

    n_days = len(calendar)
    equity = np.full(n_days, np.nan)
    cash = 0.0
    shares = np.zeros(len(syms), dtype=float)
    members: list[int] = []
    roster: list[int] = []  # last recon top-X (unfiltered); used when overlay cashes
    pending: dict[str, Any] | None = None  # execute at open of day i
    held_counts: list[tuple[str, int]] = []

    total_trades = 0
    traded_notional = 0.0
    avg_equity_for_to = 0.0
    to_count = 0
    n_rebalances = 0
    n_recons = 0
    last_rebalance_i = -10**9
    cost_rate = cost_bps / 10_000.0
    ledger_events: list[dict[str, Any]] = []
    membership_events: list[dict[str, Any]] = []

    def _mcap_at(i: int) -> np.ndarray:
        px = close_arr[i]
        with np.errstate(divide="ignore", invalid="ignore"):
            approx = mcap_vec * (px / ref_close)
        approx[~np.isfinite(approx) | (px <= 0) | ~np.isfinite(px)] = np.nan
        return approx

    def _mark(i: int) -> float:
        px = close_arr[i]
        val = cash
        for j in members:
            p = px[j]
            if np.isfinite(p) and p > 0:
                val += shares[j] * p
            # if missing price, drop mark for that name (conservative)
        return float(val)

    def _schedule_equal_weight(signal_i: int, new_members: list[int], kind: str) -> None:
        nonlocal pending
        exec_i = signal_i + 1
        if exec_i >= n_days:
            return
        pending = {"exec_i": exec_i, "members": list(new_members), "kind": kind, "signal_i": signal_i}

    def _apply_filter(signal_i: int, proposed: list[int], kind: str) -> list[int]:
        if filter_members is None:
            return list(proposed)
        out = filter_members(signal_i, list(proposed), list(members), kind)
        if out is None:
            return list(proposed)
        return [int(j) for j in out]

    def _execute(i: int) -> None:
        nonlocal cash, shares, members, pending, total_trades, traded_notional
        nonlocal avg_equity_for_to, to_count, n_rebalances, n_recons, last_rebalance_i
        if pending is None or pending["exec_i"] != i:
            return
        new_members: list[int] = pending["members"]
        kind = pending["kind"]
        signal_i = pending.get("signal_i")
        pending = None
        old_member_list = list(members)
        old_held = set(members)
        old_shares = shares.copy()

        # Delta equal-weight at today's open: sell winners / buy losers (and rotate on recon).
        px = open_arr[i]
        buyable = [j for j in new_members if np.isfinite(px[j]) and px[j] > 0]
        if not buyable:
            if not allow_empty:
                return
            # Overlay cashed the book: sell all held names, hold cash.
            traded = 0.0
            equity_pre = cash
            for j in list(old_held):
                p = px[j]
                if not (np.isfinite(p) and p > 0) and i > 0:
                    c = close_arr[i - 1, j]
                    p = c if np.isfinite(c) and c > 0 else np.nan
                if np.isfinite(p) and shares[j] != 0:
                    proceeds = shares[j] * float(p)
                    cash += proceeds
                    traded += abs(proceeds)
                    equity_pre += proceeds
                    shares[j] = 0.0
                    total_trades += 1
                else:
                    shares[j] = 0.0
            if cost_rate > 0 and traded > 0:
                cash -= traded * cost_rate
            members = []
            traded_notional += traded
            if equity_pre > 0:
                avg_equity_for_to += equity_pre
                to_count += 1
            last_rebalance_i = i - 1
            if kind == "recon":
                n_recons += 1
            n_rebalances += 1
            if collect_extras:
                dropped = [syms[j] for j in old_member_list]
                sig_date = ""
                if signal_i is not None and 0 <= int(signal_i) < len(calendar):
                    sig_date = str(calendar[int(signal_i)].date())
                ledger_events.append(
                    {
                        "date": str(calendar[i].date()),
                        "signal_date": sig_date,
                        "kind": kind,
                        "equity_pre": float(equity_pre),
                        "sold": [],
                        "bought": [],
                        "dropped": dropped,
                        "added": [],
                        "held": [],
                        "members": [],
                        "cost": float(traded * cost_rate) if cost_rate > 0 and traded > 0 else 0.0,
                    }
                )
                if kind == "recon" or dropped:
                    membership_events.append(
                        {
                            "date": str(calendar[i].date()),
                            "year": int(calendar[i].year),
                            "kind": kind,
                            "added": [],
                            "dropped": dropped,
                            "held": [],
                            "members": [],
                        }
                    )
            return

        # Mark book to open (use prior close if a name gaps missing open)
        equity_pre = cash
        held = set(members)
        for j in list(held):
            p = px[j]
            if not (np.isfinite(p) and p > 0):
                c = close_arr[i - 1, j] if i > 0 else np.nan
                p = c if np.isfinite(c) and c > 0 else np.nan
            if np.isfinite(p) and shares[j] != 0:
                equity_pre += shares[j] * float(p)

        if equity_pre <= 0:
            members = []
            shares[:] = 0.0
            cash = 0.0
            return

        target_set = set(buyable)
        target_dollar = equity_pre / len(buyable)
        traded = 0.0

        # 1) Exit names leaving the book
        for j in list(held - target_set):
            p = px[j]
            if np.isfinite(p) and p > 0 and shares[j] != 0:
                proceeds = shares[j] * p
                cash += proceeds
                traded += abs(proceeds)
                shares[j] = 0.0
                total_trades += 1
            else:
                shares[j] = 0.0

        # 2) Rebalance remaining + enter new names toward equal dollar
        for j in buyable:
            p = float(px[j])
            cur_val = shares[j] * p if shares[j] != 0 else 0.0
            delta = target_dollar - cur_val
            if abs(delta) < 1e-6:
                continue
            d_shares = delta / p
            shares[j] += d_shares
            cash -= delta
            traded += abs(delta)
            total_trades += 1

        if cost_rate > 0 and traded > 0:
            cash -= traded * cost_rate

        members = buyable
        traded_notional += traded
        avg_equity_for_to += equity_pre
        to_count += 1
        last_rebalance_i = i - 1  # signal day
        if kind == "recon":
            n_recons += 1
        n_rebalances += 1

        if collect_extras:
            sold: list[dict[str, Any]] = []
            bought: list[dict[str, Any]] = []
            for j, sym in enumerate(syms):
                ds = float(shares[j] - old_shares[j])
                if abs(ds) < 1e-9:
                    continue
                p = px[j]
                if not (np.isfinite(p) and p > 0) and i > 0:
                    p = close_arr[i - 1, j]
                price = float(p) if np.isfinite(p) and p > 0 else float("nan")
                dollars = ds * price if np.isfinite(price) else 0.0
                rec = {
                    "ticker": sym,
                    "shares_delta": ds,
                    "shares_after": float(shares[j]),
                    "dollars": dollars,
                    "price": None if not np.isfinite(price) else price,
                }
                (sold if ds < 0 else bought).append(rec)
            new_set = set(members)
            dropped = [syms[j] for j in old_member_list if j not in new_set]
            added = [syms[j] for j in members if j not in old_held]
            held = [syms[j] for j in members if j in old_held]
            sig_date = ""
            if signal_i is not None and 0 <= int(signal_i) < len(calendar):
                sig_date = str(calendar[int(signal_i)].date())
            ledger_events.append(
                {
                    "date": str(calendar[i].date()),
                    "signal_date": sig_date,
                    "kind": kind,
                    "equity_pre": float(equity_pre),
                    "sold": sold,
                    "bought": bought,
                    "dropped": dropped,
                    "added": added,
                    "held": held,
                    "members": [syms[j] for j in members],
                    "cost": float(traded * cost_rate) if cost_rate > 0 and traded > 0 else 0.0,
                }
            )
            if kind == "recon" or dropped or added:
                membership_events.append(
                    {
                        "date": str(calendar[i].date()),
                        "year": int(calendar[i].year),
                        "kind": kind,
                        "added": added,
                        "dropped": dropped,
                        "held": held,
                        "members": [syms[j] for j in members],
                    }
                )

    # Seed: first reconstitution / start
    first_mcap = _mcap_at(start_i)
    order = np.argsort(-np.nan_to_num(first_mcap, nan=-1.0))
    seed = [int(j) for j in order if np.isfinite(first_mcap[j])][:X]
    if len(seed) < X:
        return BacktestResult(
            X, N, cost_bps, False, f"seed top-X incomplete ({len(seed)})", "", "", 0, 0, 0, 0, 0, 0, 0, 0.0, 0, 0, {}
        )
    cash = capital0
    members = []
    shares[:] = 0
    roster = list(seed)
    _schedule_equal_weight(start_i, _apply_filter(start_i, seed, "recon"), "recon")

    yearly_equity: dict[int, float] = {}

    for i in range(start_i, n_days):
        _execute(i)
        # Signals on close (after any open execution today)
        if i == start_i:
            # already scheduled
            pass
        elif calendar[i] in recon_days and i > start_i:
            mcap = _mcap_at(i)
            order = np.argsort(-np.nan_to_num(mcap, nan=-1.0))
            new = [int(j) for j in order if np.isfinite(mcap[j])][:X]
            if len(new) >= X:
                roster = list(new)
                _schedule_equal_weight(i, _apply_filter(i, new, "recon"), "recon")
        elif pending is None and (i - last_rebalance_i) >= N:
            # Equal-weight rebalance. Overlay uses last recon roster so a
            # cashed book can re-enter; unmodified engine still requires members.
            cadence_names = roster if filter_members is not None else members
            if cadence_names:
                _schedule_equal_weight(i, _apply_filter(i, list(cadence_names), "rebalance"), "rebalance")

        equity[i] = _mark(i)
        if collect_extras:
            held_counts.append((str(calendar[i].date()), int(len(members))))
        y = int(calendar[i].year)
        yearly_equity[y] = equity[i]

    # Build equity series from first valid mark
    valid_idx = np.where(np.isfinite(equity))[0]
    if len(valid_idx) < 5:
        return BacktestResult(
            X, N, cost_bps, False, "no equity path", "", "", 0, 0, 0, 0, 0, 0, 0, 0.0, 0, 0, {}
        )
    eq = equity.copy()
    # forward-fill leading nan before first mark with capital0 for dd calc only from first mark
    first = valid_idx[0]
    eq_path = eq[first:]
    # replace any nan with previous
    for k in range(1, len(eq_path)):
        if not np.isfinite(eq_path[k]):
            eq_path[k] = eq_path[k - 1]

    final_eq = float(eq_path[-1])
    total_ret = final_eq / capital0 - 1.0
    start_ts = calendar[first]
    end_ts = calendar[valid_idx[-1]]
    cagr = _cagr(total_ret, start_ts, end_ts)
    max_dd = _max_dd_pct(eq_path)
    daily = np.diff(eq_path) / eq_path[:-1]
    daily = daily[np.isfinite(daily)]
    sharpe, ann_vol = _sharpe(daily)

    # Yearly returns from year-end marks
    years_sorted = sorted(yearly_equity)
    yearly_returns: dict[str, float] = {}
    prev = capital0
    # Use first mark in first year as base for that year
    for yi, y in enumerate(years_sorted):
        # find last equity of year y
        end_eq = yearly_equity[y]
        if yi == 0:
            # return from start capital to first year-end
            yearly_returns[str(y)] = end_eq / capital0 - 1.0
        else:
            yearly_returns[str(y)] = end_eq / prev - 1.0
        prev = end_eq

    avg_eq = (avg_equity_for_to / to_count) if to_count else capital0
    turnover = (traded_notional / avg_eq) if avg_eq > 0 else 0.0  # sum of traded / avg book (not annualized)

    extras = None
    if collect_extras:
        eq_pairs = []
        for i in valid_idx:
            v = float(equity[i])
            if not np.isfinite(v):
                continue
            eq_pairs.append((str(calendar[i].date()), v))
        extras = {
            "equity": eq_pairs,
            "ledger": ledger_events,
            "membership": membership_events,
            "held_counts": held_counts,
        }

    return BacktestResult(
        X=X,
        N=N,
        cost_bps=cost_bps,
        ok=True,
        error="",
        start=str(start_ts.date()),
        end=str(end_ts.date()),
        final_equity=final_eq,
        total_return=total_ret * 100.0,
        cagr=cagr,
        max_dd=max_dd,
        sharpe=sharpe,
        ann_vol=ann_vol,
        total_trades=total_trades,
        turnover=turnover,
        n_rebalances=n_rebalances,
        n_reconstitutions=n_recons,
        yearly_returns=yearly_returns,
        extras=extras,
    )


def spy_buy_and_hold(
    spy: pd.Series,
    *,
    start: str,
    end: str,
    capital: float = INITIAL_CAPITAL,
    cost_bps: float = 0.0,
) -> dict[str, Any]:
    window = spy.loc[(spy.index >= pd.Timestamp(start)) & (spy.index <= pd.Timestamp(end))].dropna()
    if len(window) < 2:
        return {"ok": False, "error": "insufficient SPY history"}
    # Enter at first open approx via first close (label: close-to-close BH)
    entry = float(window.iloc[0])
    exit_px = float(window.iloc[-1])
    rets = window.pct_change().fillna(0.0).to_numpy()
    equity = capital * np.cumprod(1.0 + rets)
    # Apply one round-trip cost at start/end if requested
    if cost_bps > 0:
        equity = equity * (1.0 - 2.0 * cost_bps / 10_000.0)
    total_ret = exit_px / entry - 1.0
    if cost_bps > 0:
        total_ret = (1.0 + total_ret) * (1.0 - 2.0 * cost_bps / 10_000.0) - 1.0
    final_eq = capital * (1.0 + total_ret)
    cagr = _cagr(total_ret, window.index[0], window.index[-1])
    max_dd = _max_dd_pct(equity)
    daily = np.diff(equity) / equity[:-1]
    sharpe, ann_vol = _sharpe(daily[np.isfinite(daily)])
    # Yearly
    yearly: dict[str, float] = {}
    by_year = window.groupby(window.index.year)
    prev_close = None
    for y, s in by_year:
        if prev_close is None:
            yearly[str(y)] = float(s.iloc[-1] / s.iloc[0] - 1.0)
        else:
            yearly[str(y)] = float(s.iloc[-1] / prev_close - 1.0)
        prev_close = float(s.iloc[-1])
    return {
        "ok": True,
        "id": "SPY_BH",
        "label": "SPY buy-and-hold (close-to-close)",
        "start": str(window.index[0].date()),
        "end": str(window.index[-1].date()),
        "final_equity": final_eq,
        "total_return": total_ret * 100.0,
        "cagr": cagr,
        "max_dd": max_dd,
        "sharpe": sharpe,
        "ann_vol": ann_vol,
        "total_trades": 1,
        "turnover": 0.0,
        "yearly_returns": yearly,
    }


def _worker_payload(args: tuple) -> dict[str, Any]:
    """Process-pool worker: run one (X,N,cost) backtest from shared arrays saved to disk paths."""
    (
        X,
        N,
        cost_bps,
        opens_path,
        closes_path,
        mcap_path,
        capital0,
        collect_extras,
    ) = args
    opens = pd.read_pickle(opens_path)
    closes = pd.read_pickle(closes_path)
    with open(mcap_path, encoding="utf-8") as f:
        mcap_now = {k: float(v) for k, v in json.load(f).items()}
    r = run_one_backtest(
        X=X,
        N=N,
        cost_bps=cost_bps,
        opens=opens,
        closes=closes,
        mcap_now=mcap_now,
        capital0=capital0,
        collect_extras=bool(collect_extras),
    )
    out = {
        "X": r.X,
        "N": r.N,
        "cost_bps": r.cost_bps,
        "ok": r.ok,
        "error": r.error,
        "start": r.start,
        "end": r.end,
        "final_equity": r.final_equity,
        "total_return": r.total_return,
        "cagr": r.cagr,
        "max_dd": r.max_dd,
        "sharpe": r.sharpe,
        "ann_vol": r.ann_vol,
        "total_trades": r.total_trades,
        "turnover": r.turnover,
        "n_rebalances": r.n_rebalances,
        "n_reconstitutions": r.n_reconstitutions,
        "yearly_returns": r.yearly_returns,
    }
    if r.extras:
        out["equity"] = r.extras.get("equity") or []
        out["ledger"] = r.extras.get("ledger") or []
        out["membership"] = r.extras.get("membership") or []
    return out


def result_to_row(r: dict[str, Any], spy: dict[str, Any] | None = None) -> dict[str, Any]:
    row = {
        "X": r["X"],
        "N": r["N"],
        "cost_bps": r["cost_bps"],
        "ok": r["ok"],
        "start": r.get("start", ""),
        "end": r.get("end", ""),
        "final_equity": r.get("final_equity", 0.0),
        "total_return_pct": r.get("total_return", 0.0),
        "cagr_pct": r.get("cagr", 0.0),
        "max_dd_pct": r.get("max_dd", 0.0),
        "sharpe": r.get("sharpe", 0.0),
        "ann_vol_pct": r.get("ann_vol", 0.0),
        "total_trades": r.get("total_trades", 0),
        "turnover": r.get("turnover", 0.0),
        "n_rebalances": r.get("n_rebalances", 0),
        "n_reconstitutions": r.get("n_reconstitutions", 0),
        "error": r.get("error", ""),
    }
    if spy and spy.get("ok"):
        row["vs_spy_cagr_pp"] = row["cagr_pct"] - spy["cagr"]
        row["vs_spy_total_pp"] = row["total_return_pct"] - spy["total_return"]
        row["vs_spy_maxdd_pp"] = row["max_dd_pct"] - spy["max_dd"]
        row["spy_final_equity"] = spy["final_equity"]
        row["spy_cagr_pct"] = spy["cagr"]
        row["spy_total_return_pct"] = spy["total_return"]
        row["spy_max_dd_pct"] = spy["max_dd"]
        row["spy_sharpe"] = spy["sharpe"]
    # Flatten yearly
    for y, ret in (r.get("yearly_returns") or {}).items():
        row[f"yr_{y}"] = ret * 100.0
    return row


def write_comparison_md(
    path: Path,
    rows: list[dict[str, Any]],
    spy: dict[str, Any],
    *,
    universe_n: int,
    wiki_n: int,
    missing_n: int,
    mcap_n: int,
    cost_bps: float,
    caveats: list[str],
) -> None:
    df = pd.DataFrame(rows)
    df_ok = df[df["ok"] == True].copy()  # noqa: E712
    best_cagr = df_ok.sort_values("cagr_pct", ascending=False).head(1)
    best_sharpe = df_ok.sort_values("sharpe", ascending=False).head(1)
    ref = df_ok[(df_ok["X"] == 20) & (df_ok["N"] == 20)]

    def _fmt_row(r: pd.Series) -> str:
        return (
            f"X={int(r['X'])} N={int(r['N'])}: "
            f"CAGR {r['cagr_pct']:.2f}%, MaxDD {r['max_dd_pct']:.2f}%, "
            f"Sharpe {r['sharpe']:.2f}, Final ${r['final_equity']:,.0f}, "
            f"TotalRet {r['total_return_pct']:.1f}%"
        )

    lines: list[str] = []
    lines.append("# S&P X Diversification — Grid Results")
    lines.append("")
    lines.append(f"- **Capital:** ${INITIAL_CAPITAL:,.0f}")
    lines.append(f"- **Cost model:** {cost_bps:g} bps/side on traded notional (sell + buy legs)")
    lines.append("- **Fills:** next open after signal (rebalance / reconstitution)")
    lines.append("- **Reconstitution:** first trading day of each calendar year (SPY calendar)")
    lines.append(f"- **Universe:** Wikipedia S&P 500 ({wiki_n}) ∩ DuckDB OHLC → {universe_n} names "
                 f"({missing_n} missing locally); {mcap_n} with usable market cap")
    lines.append("")
    lines.append("## Headline")
    lines.append("")
    if spy.get("ok"):
        lines.append(
            f"- **SPY BH:** CAGR {spy['cagr']:.2f}%, MaxDD {spy['max_dd']:.2f}%, "
            f"Sharpe {spy['sharpe']:.2f}, Final ${spy['final_equity']:,.0f}, "
            f"TotalRet {spy['total_return']:.1f}% "
            f"({spy['start']} → {spy['end']})"
        )
    if len(best_cagr):
        lines.append(f"- **Best CAGR:** {_fmt_row(best_cagr.iloc[0])}")
    if len(best_sharpe):
        lines.append(f"- **Best Sharpe (risk-adjusted):** {_fmt_row(best_sharpe.iloc[0])}")
    if len(ref):
        lines.append(f"- **Reference X=20 N=20:** {_fmt_row(ref.iloc[0])}")
    lines.append("")
    lines.append("## Full grid (ranked by Sharpe)")
    lines.append("")
    show = df_ok.sort_values(["sharpe", "cagr_pct"], ascending=False)
    cols = [
        "X", "N", "cagr_pct", "total_return_pct", "max_dd_pct", "sharpe", "ann_vol_pct",
        "final_equity", "total_trades", "turnover", "vs_spy_cagr_pp",
    ]
    cols = [c for c in cols if c in show.columns]
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("| " + " | ".join(["---"] * len(cols)) + " |")
    for _, r in show.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if c in ("cagr_pct", "total_return_pct", "max_dd_pct", "ann_vol_pct", "vs_spy_cagr_pp"):
                cells.append(f"{v:.2f}")
            elif c == "sharpe":
                cells.append(f"{v:.3f}")
            elif c == "final_equity":
                cells.append(f"{v:,.0f}")
            elif c == "turnover":
                cells.append(f"{v:.2f}")
            else:
                cells.append(str(int(v) if c in ("X", "N", "total_trades") else v))
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("## Methodology caveats")
    lines.append("")
    for c in caveats:
        lines.append(f"- {c}")
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


STAMP_DEFAULT_X = (3, 5, 7, 10)
STAMP_DEFAULT_N = (21, 42, 63, 126, 252)
CONTROL_X = 10
CONTROL_N = 21
IS_CUT_DEFAULT = "2024-01-01"
ORIGINAL_REQUEST = (
    "so we tried 10, 20 and 50 stocks and 5, 13 and 21 for cadence. it turns out "
    "the lowest for # stocks and the highest for cadence was the best. can we wire "
    "together a few more AB tests using lower stock numbers and higher cadences? "
    "also, i'd like to know when we rebalance, what was sold and what was bought, "
    "and which stocks were dropped vs. which stocks were added through the years"
)
PLAIN_ENGLISH = (
    "We already tested holding the 10, 20, or 50 biggest Standard & Poor's 500 "
    "(S&P 500) names, equal-weight, and rebalancing every 5, 13, or 21 trading days. "
    "Fewer names plus a longer wait looked best. Cadence here means how long we wait "
    "between rebalances — highest cadence = least often (21 was the longest wait in "
    "that first grid). This stamp tries even fewer names (3, 5, 7, and the old 10) "
    "and even longer waits (21, 42, 63, 126, and 252 trading days — about 1, 2, 3, 6, "
    "and 12 months). Same $500k, 10 basis points cost, next-open fills, annual "
    "membership refresh. We also print a shopping list each rebalance: what was sold, "
    "what was bought, and which names entered or left the book over the years. "
    "In-sample (IS) is before 2024; 2024+ is out-of-sample (OOS) and report-only. "
    "Judge Compound Annual Growth Rate (CAGR), max drawdown, and Sharpe — not how "
    "many trades. Research only; not DailyRun."
)

SORTABLE_TH_CSS = """
th.sortable-th { cursor: pointer; user-select: none; white-space: nowrap; }
th.sortable-th:hover { background: #e2e8f0; }
.sort-ind { display: inline-block; width: 0.9em; margin-left: 4px; color: #94a3b8; font-size: 10px; }
th.sort-asc .sort-ind::after { content: "▲"; color: #334155; }
th.sort-desc .sort-ind::after { content: "▼"; color: #334155; }
"""
SORTABLE_TABLE_SCRIPT = """
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : 0;
    if (type === "text") return s.toUpperCase();
    if (type === "date") {
      var iso = s.match(/(\\d{4})-(\\d{2})-(\\d{2})/);
      if (iso) return parseInt(iso[1] + iso[2] + iso[3], 10);
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
    var pinned = rows.filter(function (r) { return r.classList.contains("total-row"); });
    var movable = rows.filter(function (r) { return !r.classList.contains("total-row"); });
    movable.sort(function (a, b) {
      var av = parseSortValue(a.cells[col] && a.cells[col].textContent, type);
      var bv = parseSortValue(b.cells[col] && b.cells[col].textContent, type);
      if (typeof av === "string" || typeof bv === "string") {
        return dir * String(av).localeCompare(String(bv));
      }
      return dir * (av - bv);
    });
    movable.concat(pinned).forEach(function (r) { tbody.appendChild(r); });
  }
  function bindSortHeader(table, th, col) {
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
  }
  document.querySelectorAll("table.sortable").forEach(function (table) {
    table.querySelectorAll("th.sortable-th").forEach(function (th, col) {
      bindSortHeader(table, th, col);
    });
  });
})();
"""


def _sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{html_mod.escape(sort_type)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _fmt_money(v: Any) -> str:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    sign = "-" if n < 0 else ""
    return f"{sign}${abs(n):,.2f}"


def _fmt_pct(v: Any, digits: int = 2) -> str:
    try:
        return f"{float(v):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_num(v: Any, digits: int = 3) -> str:
    try:
        return f"{float(v):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _arm_id(x: int, n: int) -> str:
    return f"X{int(x)}_D{int(n)}"


def _slice_pack(r: dict[str, Any], is_cut: str) -> dict[str, dict[str, Any]]:
    eq = r.get("equity") or []
    dates = [p[0] for p in eq]
    vals = [float(p[1]) for p in eq]
    return {
        "IS": metrics_from_equity(dates, vals, end=is_cut),
        "OOS": metrics_from_equity(dates, vals, start=is_cut),
        "FULL": metrics_from_equity(dates, vals),
    }


def _attach_slices(results: list[dict[str, Any]], is_cut: str) -> None:
    for r in results:
        slices = _slice_pack(r, is_cut) if r.get("ok") and r.get("equity") else {
            "IS": {"ok": False},
            "OOS": {"ok": False},
            "FULL": {"ok": False},
        }
        r["slices"] = slices


def _find_arm(results: list[dict[str, Any]], x: int, n: int) -> dict[str, Any] | None:
    for r in results:
        if int(r.get("X", -1)) == int(x) and int(r.get("N", -1)) == int(n) and r.get("ok"):
            return r
    return None


def pick_is_winner(
    results: list[dict[str, Any]],
    *,
    control_x: int,
    control_n: int,
) -> tuple[dict[str, Any] | None, str]:
    """IS winner by Sharpe, then CAGR, then lower MaxDD. Notes lottery risk if X<=3."""
    ok = [r for r in results if r.get("ok") and (r.get("slices") or {}).get("IS", {}).get("ok")]
    ok.sort(
        key=lambda r: (
            -float(r["slices"]["IS"]["sharpe"]),
            -float(r["slices"]["IS"]["cagr"]),
            float(r["slices"]["IS"]["max_dd"]),
        )
    )
    if not ok:
        return None, "no IS-ok arms"
    return ok[0], "IS rank: Sharpe, then CAGR, then lower MaxDD"


def verdict_vs_control(
    winner: dict[str, Any],
    control: dict[str, Any],
) -> tuple[str, str]:
    """KEEP only if IS quality beats control without 1-name lottery; OOS soften → HOLD."""
    w_is, c_is = winner["slices"]["IS"], control["slices"]["IS"]
    w_oos, c_oos = winner["slices"]["OOS"], control["slices"]["OOS"]
    same = int(winner["X"]) == int(control["X"]) and int(winner["N"]) == int(control["N"])
    if same:
        return "HOLD", "IS winner is the prior control (X=10 D=21). No new KEEP."
    sharpe_up = float(w_is["sharpe"]) > float(c_is["sharpe"]) + 1e-4
    cagr_ok = float(w_is["cagr"]) >= float(c_is["cagr"]) - 0.25
    dd_ok = float(w_is["max_dd"]) <= float(c_is["max_dd"]) + 2.0
    lottery = int(winner["X"]) <= 3 and (
        float(w_is["max_dd"]) > float(c_is["max_dd"]) + 5.0
        or float(w_is["ann_vol"]) > float(c_is["ann_vol"]) + 4.0
    )
    oos_soften = False
    if w_oos.get("ok") and c_oos.get("ok"):
        oos_soften = (
            float(w_oos["sharpe"]) < float(c_oos["sharpe"]) - 1e-3
            or float(w_oos["cagr"]) < float(c_oos["cagr"]) - 0.25
        )
    dd_delta = float(w_is["max_dd"]) - float(c_is["max_dd"])
    if lottery:
        return (
            "HOLD",
            "IS looks better on a 3-name book but drawdown/vol jumps — lottery risk, not KEEP.",
        )
    if sharpe_up and cagr_ok and dd_ok:
        if oos_soften:
            return "HOLD", "IS quality beats control, but OOS softened — report-only HOLD, do not retune."
        return "LEAN KEEP", "IS Sharpe/CAGR beat control without a much worse MaxDD. Research only — not gold, not DailyRun."
    if sharpe_up or (cagr_ok and float(w_is["cagr"]) > float(c_is["cagr"])):
        return (
            "HOLD",
            f"IS CAGR/Sharpe beat control, but MaxDD is worse by {dd_delta:+.1f} pp "
            f"({w_is['max_dd']:.1f}% vs {c_is['max_dd']:.1f}%) — not a clean quality win. HOLD.",
        )
    return "DISMISS", "IS quality does not beat X=10 D=21."


def _legs_text(rows: list[dict[str, Any]], *, sold: bool) -> str:
    if not rows:
        return "—"
    parts = []
    for rec in rows:
        t = rec.get("ticker", "?")
        dol = _fmt_money(rec.get("dollars"))
        sh = rec.get("shares_delta")
        try:
            sh_s = f"{abs(float(sh)):.2f}sh"
        except (TypeError, ValueError):
            sh_s = ""
        wt = ""
        parts.append(f"{t} {dol} ({sh_s})".strip())
    return "; ".join(parts)


def _join_names(names: list[str]) -> str:
    return ", ".join(names) if names else "—"


def ticker_careers(membership: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for ev in membership:
        dt = ev.get("date", "")
        year = ev.get("year")
        for t in ev.get("added") or []:
            rec = seen.setdefault(
                t,
                {
                    "ticker": t,
                    "first_in": dt,
                    "last_in": dt,
                    "times_added": 0,
                    "times_dropped": 0,
                    "years": set(),
                },
            )
            rec["times_added"] += 1
            rec["last_in"] = dt
            if year:
                rec["years"].add(int(year))
        for t in ev.get("dropped") or []:
            rec = seen.setdefault(
                t,
                {
                    "ticker": t,
                    "first_in": "",
                    "last_in": dt,
                    "times_added": 0,
                    "times_dropped": 0,
                    "years": set(),
                },
            )
            rec["times_dropped"] += 1
            rec["last_in"] = dt
        for t in ev.get("held") or []:
            rec = seen.setdefault(
                t,
                {
                    "ticker": t,
                    "first_in": dt,
                    "last_in": dt,
                    "times_added": 0,
                    "times_dropped": 0,
                    "years": set(),
                },
            )
            rec["last_in"] = dt
            if year:
                rec["years"].add(int(year))
        for t in ev.get("members") or []:
            rec = seen.setdefault(
                t,
                {
                    "ticker": t,
                    "first_in": dt,
                    "last_in": dt,
                    "times_added": 0,
                    "times_dropped": 0,
                    "years": set(),
                },
            )
            if not rec["first_in"]:
                rec["first_in"] = dt
            rec["last_in"] = dt
            if year:
                rec["years"].add(int(year))
    out = []
    for rec in seen.values():
        years = sorted(rec["years"])
        out.append(
            {
                "ticker": rec["ticker"],
                "first_in": rec["first_in"],
                "last_in": rec["last_in"],
                "times_added": rec["times_added"],
                "times_dropped": rec["times_dropped"],
                "n_years": len(years),
                "years": ",".join(str(y) for y in years),
            }
        )
    out.sort(key=lambda r: (-r["n_years"], r["ticker"]))
    return out


def write_arm_csvs(out_dir: Path, r: dict[str, Any]) -> dict[str, Path]:
    aid = _arm_id(r["X"], r["N"])
    paths: dict[str, Path] = {}
    eq = r.get("equity") or []
    eq_path = out_dir / f"equity_{aid}.csv"
    pd.DataFrame([{"date": d, "equity": v} for d, v in eq]).to_csv(eq_path, index=False)
    paths["equity"] = eq_path

    ev_rows = []
    tr_rows = []
    for ev in r.get("ledger") or []:
        ev_rows.append(
            {
                "date": ev.get("date"),
                "signal_date": ev.get("signal_date"),
                "kind": ev.get("kind"),
                "equity_pre": ev.get("equity_pre"),
                "cost": ev.get("cost"),
                "sold": _legs_text(ev.get("sold") or [], sold=True),
                "bought": _legs_text(ev.get("bought") or [], sold=False),
                "dropped": _join_names(ev.get("dropped") or []),
                "added": _join_names(ev.get("added") or []),
                "held": _join_names(ev.get("held") or []),
                "members": _join_names(ev.get("members") or []),
            }
        )
        for rec in ev.get("sold") or []:
            tr_rows.append(
                {
                    "date": ev.get("date"),
                    "kind": ev.get("kind"),
                    "action": "SELL",
                    "ticker": rec.get("ticker"),
                    "shares_delta": rec.get("shares_delta"),
                    "shares_after": rec.get("shares_after"),
                    "dollars": rec.get("dollars"),
                    "price": rec.get("price"),
                }
            )
        for rec in ev.get("bought") or []:
            tr_rows.append(
                {
                    "date": ev.get("date"),
                    "kind": ev.get("kind"),
                    "action": "BUY",
                    "ticker": rec.get("ticker"),
                    "shares_delta": rec.get("shares_delta"),
                    "shares_after": rec.get("shares_after"),
                    "dollars": rec.get("dollars"),
                    "price": rec.get("price"),
                }
            )
    led_path = out_dir / f"rebalance_ledger_{aid}.csv"
    pd.DataFrame(ev_rows).to_csv(led_path, index=False)
    paths["ledger"] = led_path
    tr_path = out_dir / f"rebalance_trades_{aid}.csv"
    pd.DataFrame(tr_rows).to_csv(tr_path, index=False)
    paths["trades"] = tr_path

    mem_rows = []
    for ev in r.get("membership") or []:
        mem_rows.append(
            {
                "date": ev.get("date"),
                "year": ev.get("year"),
                "kind": ev.get("kind"),
                "added": _join_names(ev.get("added") or []),
                "dropped": _join_names(ev.get("dropped") or []),
                "held": _join_names(ev.get("held") or []),
                "members": _join_names(ev.get("members") or []),
            }
        )
    ad_path = out_dir / f"add_drop_history_{aid}.csv"
    pd.DataFrame(mem_rows).to_csv(ad_path, index=False)
    paths["add_drop"] = ad_path
    career_path = out_dir / f"ticker_careers_{aid}.csv"
    pd.DataFrame(ticker_careers(r.get("membership") or [])).to_csv(career_path, index=False)
    paths["careers"] = career_path
    return paths


def _metric_table(results: list[dict[str, Any]], sl: str, control: dict[str, Any] | None) -> str:
    headers = [
        ("Arm", "text"),
        ("Role", "text"),
        ("X", "num"),
        ("D (trading days)", "num"),
        ("CAGR %", "num"),
        ("Δ CAGR vs ctrl", "num"),
        ("Total return %", "num"),
        ("Final equity", "num"),
        ("Max DD %", "num"),
        ("Δ Max DD vs ctrl", "num"),
        ("Sharpe", "num"),
        ("Δ Sharpe vs ctrl", "num"),
        ("Calmar", "num"),
        ("Ann vol %", "num"),
        ("N days", "num"),
        ("Start", "date"),
        ("End", "date"),
        ("Rebalances", "num"),
        ("Recons", "num"),
        ("Trades", "num"),
        ("Turnover", "num"),
        ("Equal weight %", "num"),
    ]
    th = "".join(_sortable_th(h, t) for h, t in headers)
    csl = (control or {}).get("slices", {}).get(sl, {}) if control else {}
    rows_html = []
    ordered = sorted(
        [r for r in results if r.get("ok")],
        key=lambda r: (
            -float((r.get("slices") or {}).get(sl, {}).get("sharpe") or -99),
            -float((r.get("slices") or {}).get(sl, {}).get("cagr") or -99),
        ),
    )
    for r in ordered:
        slc = (r.get("slices") or {}).get(sl) or {}
        if not slc.get("ok"):
            continue
        role = ""
        if control and int(r["X"]) == int(control["X"]) and int(r["N"]) == int(control["N"]):
            role = "CONTROL"
        d_cagr = slc["cagr"] - csl["cagr"] if csl.get("ok") else None
        d_dd = slc["max_dd"] - csl["max_dd"] if csl.get("ok") else None
        d_sh = slc["sharpe"] - csl["sharpe"] if csl.get("ok") else None
        calmar = slc.get("calmar")
        wt = 100.0 / float(r["X"]) if r.get("X") else None
        cls = ' class="ctrl-row"' if role == "CONTROL" else ""
        cells = [
            html_mod.escape(_arm_id(r["X"], r["N"])),
            role or "—",
            str(int(r["X"])),
            str(int(r["N"])),
            _fmt_pct(slc["cagr"]),
            "—" if d_cagr is None else f"{d_cagr:+.2f}",
            _fmt_pct(slc["total_return"]),
            _fmt_money(slc["final_equity"]),
            _fmt_pct(slc["max_dd"]),
            "—" if d_dd is None else f"{d_dd:+.2f}",
            _fmt_num(slc["sharpe"]),
            "—" if d_sh is None else f"{d_sh:+.3f}",
            "—" if calmar is None else _fmt_num(calmar),
            _fmt_pct(slc["ann_vol"]),
            str(int(slc.get("n_days") or 0)),
            html_mod.escape(str(slc.get("start") or "")),
            html_mod.escape(str(slc.get("end") or "")),
            str(int(r.get("n_rebalances") or 0)),
            str(int(r.get("n_reconstitutions") or 0)),
            str(int(r.get("total_trades") or 0)),
            _fmt_num(r.get("turnover") or 0, 2),
            "—" if wt is None else f"{wt:.1f}",
        ]
        rows_html.append(f"<tr{cls}>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    title = {
        "IS": "IS (equity date &lt; 2024-01-01) — pick here",
        "OOS": "OOS (equity date ≥ 2024-01-01) — report-only",
        "FULL": "FULL (all history)",
    }[sl]
    return (
        f"<h3>{title}</h3>"
        f'<p class="meta">Click column headers to sort. Sheet $ omitted. '
        f"This is a portfolio backtest (not a Closed-trade book): win%, Paul/FIT, exit mix are N/A.</p>"
        f'<table class="sortable"><thead><tr>{th}</tr></thead><tbody>'
        f"{''.join(rows_html)}</tbody></table>"
    )


def _heatmap(results: list[dict[str, Any]], sl: str, field: str, x_grid: list[int], n_grid: list[int]) -> str:
    lookup = {(int(r["X"]), int(r["N"])): r for r in results if r.get("ok")}
    th = _sortable_th("X \\ D", "text") + "".join(_sortable_th(f"D={n}", "num") for n in n_grid)
    body = []
    for x in x_grid:
        cells = [f"<td><strong>{x}</strong></td>"]
        for n in n_grid:
            r = lookup.get((x, n))
            slc = (r.get("slices") or {}).get(sl, {}) if r else {}
            if not slc.get("ok"):
                cells.append("<td>—</td>")
                continue
            v = slc.get(field)
            cells.append(f"<td>{_fmt_num(v) if field == 'sharpe' else _fmt_pct(v)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    label = {"cagr": "CAGR %", "sharpe": "Sharpe", "max_dd": "Max DD %"}[field]
    return (
        f"<h4>{html_mod.escape(sl)} {html_mod.escape(label)}</h4>"
        f'<table class="sortable"><thead><tr>{th}</tr></thead><tbody>{"".join(body)}</tbody></table>'
    )


def _ledger_table(r: dict[str, Any], *, max_rows: int | None = None) -> str:
    headers = [
        ("Date", "date"),
        ("Signal date", "date"),
        ("Kind", "text"),
        ("Equity before", "num"),
        ("Sold", "text"),
        ("Bought", "text"),
        ("Dropped", "text"),
        ("Added", "text"),
        ("Held through", "text"),
        ("Cost", "num"),
    ]
    th = "".join(_sortable_th(h, t) for h, t in headers)
    events = list(r.get("ledger") or [])
    extra = ""
    if max_rows and len(events) > max_rows:
        extra = f"<p class='meta'>Showing all {len(events)} rebalance events.</p>"
    rows = []
    for ev in events:
        rows.append(
            "<tr>"
            + "".join(
                f"<td>{c}</td>"
                for c in [
                    html_mod.escape(str(ev.get("date") or "")),
                    html_mod.escape(str(ev.get("signal_date") or "")),
                    html_mod.escape(str(ev.get("kind") or "")),
                    _fmt_money(ev.get("equity_pre")),
                    html_mod.escape(_legs_text(ev.get("sold") or [], sold=True)),
                    html_mod.escape(_legs_text(ev.get("bought") or [], sold=False)),
                    html_mod.escape(_join_names(ev.get("dropped") or [])),
                    html_mod.escape(_join_names(ev.get("added") or [])),
                    html_mod.escape(_join_names(ev.get("held") or [])),
                    _fmt_money(ev.get("cost")),
                ]
            )
            + "</tr>"
        )
    return (
        extra
        + f'<table class="sortable"><thead><tr>{th}</tr></thead><tbody>{"".join(rows)}</tbody></table>'
    )


def _add_drop_table(r: dict[str, Any]) -> str:
    headers = [
        ("Date", "date"),
        ("Year", "num"),
        ("Kind", "text"),
        ("Added", "text"),
        ("Dropped", "text"),
        ("Held through", "text"),
        ("Book after", "text"),
    ]
    th = "".join(_sortable_th(h, t) for h, t in headers)
    rows = []
    for ev in r.get("membership") or []:
        rows.append(
            "<tr>"
            + "".join(
                f"<td>{c}</td>"
                for c in [
                    html_mod.escape(str(ev.get("date") or "")),
                    str(ev.get("year") or ""),
                    html_mod.escape(str(ev.get("kind") or "")),
                    html_mod.escape(_join_names(ev.get("added") or [])),
                    html_mod.escape(_join_names(ev.get("dropped") or [])),
                    html_mod.escape(_join_names(ev.get("held") or [])),
                    html_mod.escape(_join_names(ev.get("members") or [])),
                ]
            )
            + "</tr>"
        )
    return f'<table class="sortable"><thead><tr>{th}</tr></thead><tbody>{"".join(rows)}</tbody></table>'


def _career_table(r: dict[str, Any]) -> str:
    headers = [
        ("Ticker", "text"),
        ("First in", "date"),
        ("Last in", "date"),
        ("Times added", "num"),
        ("Times dropped", "num"),
        ("Years present", "num"),
        ("Years", "text"),
    ]
    th = "".join(_sortable_th(h, t) for h, t in headers)
    rows = []
    for rec in ticker_careers(r.get("membership") or []):
        rows.append(
            "<tr>"
            + "".join(
                f"<td>{c}</td>"
                for c in [
                    html_mod.escape(str(rec["ticker"])),
                    html_mod.escape(str(rec["first_in"])),
                    html_mod.escape(str(rec["last_in"])),
                    str(rec["times_added"]),
                    str(rec["times_dropped"]),
                    str(rec["n_years"]),
                    html_mod.escape(str(rec["years"])),
                ]
            )
            + "</tr>"
        )
    return f'<table class="sortable"><thead><tr>{th}</tr></thead><tbody>{"".join(rows)}</tbody></table>'


def write_stamp_report(
    out_dir: Path,
    *,
    results: list[dict[str, Any]],
    spy: dict[str, Any],
    spy_slices: dict[str, dict[str, Any]],
    x_grid: list[int],
    n_grid: list[int],
    cost_bps: float,
    is_cut: str,
    control_x: int,
    control_n: int,
    universe_n: int,
    wiki_n: int,
    missing_n: int,
    mcap_n: int,
    caveats: list[str],
    elapsed_sec: float,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    _attach_slices(results, is_cut)
    control = _find_arm(results, control_x, control_n)
    winner, win_note = pick_is_winner(results, control_x=control_x, control_n=control_n)
    if winner is None or control is None:
        raise RuntimeError("stamp report needs CONTROL and at least one IS-ok arm")
    verdict, verdict_why = verdict_vs_control(winner, control)

    csv_rows = []
    for r in results:
        row = result_to_row(r, spy if r.get("cost_bps") == cost_bps else None)
        for sl in ("IS", "OOS", "FULL"):
            slc = (r.get("slices") or {}).get(sl) or {}
            row[f"{sl}_cagr"] = slc.get("cagr")
            row[f"{sl}_max_dd"] = slc.get("max_dd")
            row[f"{sl}_sharpe"] = slc.get("sharpe")
            row[f"{sl}_ann_vol"] = slc.get("ann_vol")
            row[f"{sl}_total_return"] = slc.get("total_return")
            row[f"{sl}_final_equity"] = slc.get("final_equity")
            row[f"{sl}_calmar"] = slc.get("calmar")
            row[f"{sl}_n_days"] = slc.get("n_days")
        csv_rows.append(row)
    pd.DataFrame(csv_rows).to_csv(out_dir / "comparison.csv", index=False)

    arm_paths: dict[str, dict[str, str]] = {}
    for r in results:
        if not r.get("ok"):
            continue
        written = write_arm_csvs(out_dir, r)
        arm_paths[_arm_id(r["X"], r["N"])] = {k: str(v.as_posix()) for k, v in written.items()}

    w_is, c_is = winner["slices"]["IS"], control["slices"]["IS"]
    w_oos, c_oos = winner["slices"]["OOS"], control["slices"]["OOS"]
    w_full, c_full = winner["slices"]["FULL"], control["slices"]["FULL"]

    def _sl_line(label: str, slc: dict[str, Any]) -> str:
        cal = slc.get("calmar")
        cal_s = "—" if cal is None else f"{cal:.3f}"
        return (
            f"- **{label}** CAGR {slc['cagr']:.2f}%  MaxDD {slc['max_dd']:.2f}%  "
            f"Sharpe {slc['sharpe']:.3f}  Calmar {cal_s}  "
            f"Final {_fmt_money(slc['final_equity'])}  ({slc['start']} → {slc['end']})"
        )

    freeze = [
        f"- **Capital:** ${INITIAL_CAPITAL:,.0f}",
        f"- **Costs:** {cost_bps:g} bps/side on traded notional",
        "- **Fills:** next open after signal",
        "- **Membership:** annual reconstitution, first trading day of each calendar year on the S&P 500 ETF (SPY) calendar",
        "- **Intra-year:** equal-weight current members every D trading days (does not re-rank mcap except on the annual refresh)",
        f"- **X grid:** {x_grid}",
        f"- **D grid:** {n_grid} trading days",
        f"- **CONTROL:** X={control_x} D={control_n} (prior IS winner among 10/20/50 × 5/13/21)",
        f"- **IS cut:** equity date < {is_cut}",
        f"- **OOS:** equity date ≥ {is_cut} (report-only; do not retune)",
        f"- **Universe:** Wikipedia S&P 500 ({wiki_n}) ∩ DuckDB → {universe_n} names "
        f"({missing_n} missing locally); {mcap_n} with usable market cap",
        "- **Not DailyRun. Not gold. Research candidate only.**",
    ]

    baseline = f"""# BASELINE — spx_x_d_extend_20260916

**Status:** Research candidate. **Not gold. Not DailyRun.** OOS report-only.

## What you asked

> {ORIGINAL_REQUEST}

## In plain English

{PLAIN_ENGLISH}

## Freeze (do not silently mutate)

{chr(10).join(freeze)}

## Honesty / selection

- Two-axis grid (X and D), 20 arms including CONTROL. That is more than a one-knob A/B; KEEP is still judged vs frozen CONTROL, not vs the whole horse-race.
- Choosing the IS winner after seeing the table is **in-sample selection**. Re-reported IS/OOS under that freeze below.
- OOS is report-only. If OOS softens, HOLD — do not retune D or X on 2024+.
- Survivorship: today's S&P 500 list projected backward. Market caps are Yahoo-now scaled by price.
- Intra-year rebalance does **not** refresh the top-X set; names enter/leave on the annual reconstitution.

## CONTROL X={control_x} D={control_n}

{_sl_line("IS", c_is)}
{_sl_line("OOS", c_oos)}
{_sl_line("FULL", c_full)}

## IS winner {_arm_id(winner["X"], winner["N"])}  (pick note: {win_note})

{_sl_line("IS", w_is)}
{_sl_line("OOS", w_oos)}
{_sl_line("FULL", w_full)}

## Verdict

- **{verdict}** — {verdict_why}
- Equal-weight at X={int(winner["X"])} is {100.0 / float(winner["X"]):.1f}% per name (not a 1-name book).

## Ledger paths

- CONTROL ledger: `rebalance_ledger_{_arm_id(control_x, control_n)}.csv`
- Winner ledger: `rebalance_ledger_{_arm_id(winner["X"], winner["N"])}.csv`
- Add/drop history + ticker careers next to those stems (`add_drop_history_*.csv`, `ticker_careers_*.csv`)
- Equity paths: `equity_X*_D*.csv`

## Caveats

{chr(10).join(f"- {c}" for c in caveats)}
"""
    (out_dir / "BASELINE.md").write_text(baseline, encoding="utf-8")

    def _spy_line(sl: str) -> str:
        slc = spy_slices.get(sl) or {}
        if not slc.get("ok"):
            return f"{sl}: n/a"
        return (
            f"{sl}: CAGR {slc['cagr']:.2f}%, MaxDD {slc['max_dd']:.2f}%, "
            f"Sharpe {slc['sharpe']:.3f}, Final {_fmt_money(slc['final_equity'])}"
        )

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>spx_x_d_extend_20260916</title>
<style>
{SORTABLE_TH_CSS}
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 1.5rem; color: #0f172a; background: #f8fafc; }}
h1 {{ font-size: 1.4rem; margin: 0 0 .35rem; }}
h2 {{ font-size: 1.12rem; margin: 1.5rem 0 .45rem; border-bottom: 1px solid #cbd5e1; padding-bottom: .25rem; }}
h3 {{ font-size: 1.02rem; margin: 1.1rem 0 .35rem; }}
.meta {{ color: #475569; font-size: .92rem; max-width: 96rem; }}
.insight {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: .75rem 1rem; margin: .75rem 0; max-width: 96rem; }}
.ask {{ background: #eff6ff; border: 1px solid #bfdbfe; }}
table.sortable {{ border-collapse: collapse; background: #fff; font-size: .78rem; margin: .5rem 0 1rem; }}
table.sortable th, table.sortable td {{ border: 1px solid #e2e8f0; padding: .32rem .5rem; vertical-align: top; }}
table.sortable th {{ background: #f1f5f9; }}
tr.ctrl-row {{ background: #f8fafc; }}
.badge {{ display: inline-block; padding: .1rem .45rem; border-radius: 4px; font-size: .8rem; background: #e2e8f0; }}
.caveat {{ color: #9a3412; font-size: .9rem; }}
blockquote.meta {{ margin: .4rem 0 0; padding-left: .8rem; border-left: 3px solid #93c5fd; }}
</style></head><body>
<h1>S&amp;P 500 top-X × cadence extend — fewer names, longer waits</h1>
<p class="badge">Research only · not gold · not DailyRun · OOS report-only</p>
<p class="meta">Stamp <code>spx_x_d_extend_20260916</code> · 2026-09-16 · click column headers to sort</p>
<div class="insight ask">
<h2 style="margin-top:0;border:0">What you asked</h2>
<blockquote class="meta">{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN_ENGLISH)}</p>
</div>
<div class="insight">
<p><strong>Verdict:</strong> {html_mod.escape(verdict)} — {html_mod.escape(verdict_why)}</p>
<p><strong>CONTROL</strong> X={control_x} D={control_n}
 (IS CAGR {c_is['cagr']:.2f}% · MaxDD {c_is['max_dd']:.2f}% · Sharpe {c_is['sharpe']:.3f})
 vs <strong>IS winner</strong> {_arm_id(winner['X'], winner['N'])}
 (IS CAGR {w_is['cagr']:.2f}% · MaxDD {w_is['max_dd']:.2f}% · Sharpe {w_is['sharpe']:.3f}).</p>
<p class="meta">SPY buy-and-hold: {_spy_line('IS')} · {_spy_line('OOS')} · {_spy_line('FULL')}</p>
<p class="caveat">Membership is today's Wikipedia S&amp;P 500 list projected backward (survivorship).
 Intra-year rebalance only equal-weights the current book; names enter/leave on the annual refresh.
 Equal-weight at X=3 is 33% each — concentrated, not a one-name lottery, but still a few-name book.</p>
</div>
<h2>Book compare (portfolio metrics)</h2>
<p class="meta">Canonical trade-book fields that need Closed fills (win%, Paul/FIT, exit mix, expectancy) are N/A.
 Shown: Compound Annual Growth Rate (CAGR), Max DD, Sharpe, Calmar (CAGR/MaxDD), vol, turnover, vs CONTROL.</p>
{_metric_table(results, "IS", control)}
{_metric_table(results, "OOS", control)}
{_metric_table(results, "FULL", control)}
<h2>Grid heatmaps</h2>
{_heatmap(results, "IS", "cagr", x_grid, n_grid)}
{_heatmap(results, "IS", "sharpe", x_grid, n_grid)}
{_heatmap(results, "IS", "max_dd", x_grid, n_grid)}
{_heatmap(results, "OOS", "cagr", x_grid, n_grid)}
{_heatmap(results, "OOS", "sharpe", x_grid, n_grid)}
<h2>Rebalance ledger — CONTROL {_arm_id(control_x, control_n)}</h2>
<p class="meta">Each row is one next-open fill. Sold/bought are dollar + share deltas. Dropped/added are names that left or entered the book (usually only on the annual reconstitution). Held through stayed in the book (may still be trimmed/added to for equal-weight). CSV: <code>rebalance_ledger_{_arm_id(control_x, control_n)}.csv</code></p>
{_ledger_table(control)}
<h3>Add / drop through the years — CONTROL</h3>
{_add_drop_table(control)}
<h3>Ticker careers — CONTROL</h3>
{_career_table(control)}
<h2>Rebalance ledger — IS winner {_arm_id(winner["X"], winner["N"])}</h2>
<p class="meta">CSV: <code>rebalance_ledger_{_arm_id(winner["X"], winner["N"])}.csv</code></p>
{_ledger_table(winner)}
<h3>Add / drop through the years — IS winner</h3>
{_add_drop_table(winner)}
<h3>Ticker careers — IS winner</h3>
{_career_table(winner)}
<h2>Freeze</h2>
<ul class="meta">{"".join(f"<li>{html_mod.escape(x[2:].replace('**', ''))}</li>" if x.startswith("- ") else f"<li>{html_mod.escape(x)}</li>" for x in freeze)}</ul>
<h2>Caveats</h2>
<ul class="meta caveat">{"".join(f"<li>{html_mod.escape(c)}</li>" for c in caveats)}</ul>
<p class="meta">Elapsed {elapsed_sec:.1f}s · equity CSVs for every arm in this folder.</p>
<script>{SORTABLE_TABLE_SCRIPT}</script>
</body></html>
"""
    (out_dir / "compare.html").write_text(html, encoding="utf-8")

    summary = {
        "stamp": "spx_x_d_extend_20260916",
        "verdict": verdict,
        "verdict_why": verdict_why,
        "control": {"X": control_x, "N": control_n, "slices": control["slices"]},
        "is_winner": {"X": winner["X"], "N": winner["N"], "slices": winner["slices"]},
        "win_note": win_note,
        "x_grid": x_grid,
        "n_grid": n_grid,
        "is_cut": is_cut,
        "arm_paths": arm_paths,
        "spy_slices": spy_slices,
        "elapsed_sec": elapsed_sec,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description="S&P X Diversification research grid")
    ap.add_argument("--workers", type=int, default=8, help="Parallel backtest workers")
    ap.add_argument("--yf-workers", type=int, default=12, help="yfinance refresh threads")
    ap.add_argument("--cost-bps", type=float, default=DEFAULT_COST_BPS, help="Per-side cost in bps")
    ap.add_argument("--also-zero-cost", action="store_true", help="Also run 0 bps sensitivity grid")
    ap.add_argument("--force-yf", action="store_true", help="Force refresh all market caps")
    ap.add_argument("--start", default="2010-01-01")
    ap.add_argument("--end", default="2026-12-31")
    ap.add_argument("--x-grid", default="", help="Comma-separated X (names). Stamp default: 3,5,7,10")
    ap.add_argument("--n-grid", default="", help="Comma-separated D trading-day cadences. Stamp default: 21,42,63,126,252")
    ap.add_argument("--stamp-dir", default="", help="If set, write IS/OOS HTML + ledger stamp here")
    ap.add_argument("--is-cut", default=IS_CUT_DEFAULT, help="OOS starts on this date (inclusive)")
    ap.add_argument("--control-x", type=int, default=CONTROL_X)
    ap.add_argument("--control-n", type=int, default=CONTROL_N)
    args = ap.parse_args()

    t0 = time.time()
    stamp_mode = bool(args.stamp_dir)
    if stamp_mode:
        out_root = Path(args.stamp_dir)
        if not out_root.is_absolute():
            out_root = REPO / out_root
        x_grid = _parse_int_list(args.x_grid) if args.x_grid else list(STAMP_DEFAULT_X)
        n_grid = _parse_int_list(args.n_grid) if args.n_grid else list(STAMP_DEFAULT_N)
        collect_extras = True
    else:
        out_root = OUT_ROOT
        x_grid = _parse_int_list(args.x_grid) if args.x_grid else list(X_GRID)
        n_grid = _parse_int_list(args.n_grid) if args.n_grid else list(N_GRID)
        collect_extras = False
    if args.control_x not in x_grid:
        x_grid = sorted(set(x_grid) | {int(args.control_x)})
    if args.control_n not in n_grid:
        n_grid = sorted(set(n_grid) | {int(args.control_n)})

    out_root.mkdir(parents=True, exist_ok=True)
    cache_dir = out_root / "_cache"
    cache_dir.mkdir(exist_ok=True)

    print("[spx] fetching Wikipedia S&P 500 list...", flush=True)
    try:
        wiki = _fetch_sp500_tickers()
    except Exception as exc:  # noqa: BLE001
        cached = OUT_ROOT / "sp500_constituents_wikipedia.txt"
        if not cached.is_file():
            raise
        wiki = [ln.strip() for ln in cached.read_text(encoding="utf-8").splitlines() if ln.strip()]
        print(f"[spx] wiki fetch failed ({exc}); using cached {len(wiki)} names", flush=True)
    (out_root / "sp500_constituents_wikipedia.txt").write_text("\n".join(wiki) + "\n", encoding="utf-8")

    import duckdb

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        db_syms = {str(r[0]).upper() for r in con.execute("SELECT DISTINCT symbol FROM prices").fetchall()}
    finally:
        con.close()

    universe = [s for s in wiki if s in db_syms]
    missing = [s for s in wiki if s not in db_syms]
    (out_root / "universe_used.txt").write_text("\n".join(universe) + "\n", encoding="utf-8")
    (out_root / "universe_missing.txt").write_text("\n".join(missing) + "\n", encoding="utf-8")
    print(f"[spx] universe {len(universe)} / wiki {len(wiki)} (missing {len(missing)})", flush=True)

    mcap = refresh_market_caps(universe, workers=args.yf_workers, force=args.force_yf)
    print(f"[spx] market caps available: {len(mcap)}", flush=True)
    # Drop dual-list clutter: if both GOOG and GOOGL present, keep Wikipedia preference (GOOGL if in wiki)
    if "GOOG" in mcap and "GOOGL" in mcap:
        drop = "GOOG" if "GOOGL" in universe else "GOOGL"
        mcap.pop(drop, None)
        print(f"[spx] dropped dual-class {drop} to avoid double-count", flush=True)

    print("[spx] loading OHLC panels from DuckDB...", flush=True)
    opens, closes, spy = load_price_panels(list(mcap.keys()), start=args.start, end=args.end)
    # Restrict columns to those with mcap
    keep = [c for c in closes.columns if c == "SPY" or c in mcap]
    opens = opens[keep]
    closes = closes[keep]

    opens_path = cache_dir / "opens.pkl"
    closes_path = cache_dir / "closes.pkl"
    mcap_path = cache_dir / "mcap.json"
    opens.to_pickle(opens_path)
    closes.to_pickle(closes_path)
    mcap_path.write_text(json.dumps(mcap), encoding="utf-8")

    cost_list = [args.cost_bps]
    if args.also_zero_cost and args.cost_bps != 0:
        cost_list.append(0.0)

    jobs = []
    for cost in cost_list:
        for X in x_grid:
            for N in n_grid:
                jobs.append(
                    (X, N, cost, str(opens_path), str(closes_path), str(mcap_path), INITIAL_CAPITAL, collect_extras)
                )

    print(f"[spx] running {len(jobs)} backtests with {args.workers} workers...", flush=True)
    results: list[dict[str, Any]] = []
    if args.workers <= 1:
        for job in jobs:
            results.append(_worker_payload(job))
            print(f"  done X={job[0]} N={job[1]} cost={job[2]}", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(_worker_payload, job): job for job in jobs}
            for fut in as_completed(futs):
                job = futs[fut]
                try:
                    results.append(fut.result())
                    print(f"  done X={job[0]} N={job[1]} cost={job[2]}", flush=True)
                except Exception as exc:  # noqa: BLE001
                    results.append({
                        "X": job[0], "N": job[1], "cost_bps": job[2], "ok": False,
                        "error": str(exc), "yearly_returns": {},
                    })
                    print(f"  FAIL X={job[0]} N={job[1]}: {exc}", flush=True)

    # SPY baseline aligned to primary grid date range
    primary = [r for r in results if r.get("ok") and r.get("cost_bps") == args.cost_bps]
    if primary:
        spy_start = min(r["start"] for r in primary)
        spy_end = max(r["end"] for r in primary)
    else:
        spy_start, spy_end = args.start, args.end
    spy_stats = spy_buy_and_hold(spy, start=spy_start, end=spy_end, capital=INITIAL_CAPITAL, cost_bps=0.0)

    rows = [result_to_row(r, spy_stats if r.get("cost_bps") == args.cost_bps else None) for r in results]
    rows_primary = [row for row in rows if row["cost_bps"] == args.cost_bps]

    csv_path = out_root / "comparison.csv"
    pd.DataFrame(rows).sort_values(["cost_bps", "sharpe", "cagr_pct"], ascending=[True, False, False]).to_csv(
        csv_path, index=False
    )

    missing_n = len(missing)
    caveats = [
        "**No historical S&P 500 membership** in this repo — universe is today's Wikipedia list "
        "projected backward (strong survivorship bias: delisted/removed names never appear).",
        f"**{missing_n} current S&P names missing** from local OHLC (e.g. BRK-B) and are excluded.",
        "**Market caps are not historical**: Yahoo point-in-time `marketCap` scaled by "
        "`Close_t / Close_now` (constant share-count approximation; ignores dilution, buybacks, "
        "secondary offerings, dual-class free-float nuances).",
        "DuckDB stores unadjusted-named Close (Yahoo split-adjusted series as ingested); "
        "dividends are not reinvested in the strategy (price appreciation only).",
        "Annual reconstitution uses the **first SPY trading day of each calendar year**.",
        f"Fills at **next open**; default costs **{args.cost_bps:g} bps/side** on traded notional.",
        "Sharpe uses daily equity returns, rf=0, ann. factor √252 — descriptive, not a forecast.",
        "Turnover is cumulative traded notional / average equity at rebalance events (not annualized).",
    ]

    write_comparison_md(
        out_root / "comparison.md",
        rows_primary,
        spy_stats,
        universe_n=len(universe),
        wiki_n=len(wiki),
        missing_n=missing_n,
        mcap_n=len(mcap),
        cost_bps=args.cost_bps,
        caveats=caveats,
    )

    # Yearly detail CSV
    yearly_rows = []
    for r in results:
        if not r.get("ok"):
            continue
        for y, ret in (r.get("yearly_returns") or {}).items():
            yearly_rows.append({"X": r["X"], "N": r["N"], "cost_bps": r["cost_bps"], "year": y, "return_pct": ret * 100.0})
    if spy_stats.get("ok"):
        for y, ret in spy_stats["yearly_returns"].items():
            yearly_rows.append({"X": 0, "N": 0, "cost_bps": 0.0, "year": y, "return_pct": ret * 100.0, "id": "SPY_BH"})
    pd.DataFrame(yearly_rows).to_csv(out_root / "yearly_returns.csv", index=False)

    # Meta
    meta = {
        "capital": INITIAL_CAPITAL,
        "cost_bps": args.cost_bps,
        "X_grid": list(x_grid),
        "N_grid": list(n_grid),
        "universe_n": len(universe),
        "wiki_n": len(wiki),
        "missing_n": len(missing),
        "mcap_n": len(mcap),
        "spy": spy_stats,
        "stamp_mode": stamp_mode,
        "is_cut": args.is_cut,
        "elapsed_sec": time.time() - t0,
    }
    (out_root / "meta.json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")

    if stamp_mode:
        spy_window = spy.loc[(spy.index >= pd.Timestamp(spy_start)) & (spy.index <= pd.Timestamp(spy_end))].dropna()
        if len(spy_window) >= 2:
            spy_eq = (INITIAL_CAPITAL * (spy_window / float(spy_window.iloc[0]))).astype(float).tolist()
            spy_dates = [str(ts.date()) for ts in spy_window.index]
            spy_slices = {
                "IS": metrics_from_equity(spy_dates, spy_eq, end=args.is_cut),
                "OOS": metrics_from_equity(spy_dates, spy_eq, start=args.is_cut),
                "FULL": metrics_from_equity(spy_dates, spy_eq),
            }
        else:
            spy_slices = {"IS": {"ok": False}, "OOS": {"ok": False}, "FULL": {"ok": False}}
        primary_ok = [r for r in results if r.get("ok") and r.get("cost_bps") == args.cost_bps]
        summary = write_stamp_report(
            out_root,
            results=primary_ok,
            spy=spy_stats,
            spy_slices=spy_slices,
            x_grid=x_grid,
            n_grid=n_grid,
            cost_bps=args.cost_bps,
            is_cut=args.is_cut,
            control_x=int(args.control_x),
            control_n=int(args.control_n),
            universe_n=len(universe),
            wiki_n=len(wiki),
            missing_n=missing_n,
            mcap_n=len(mcap),
            caveats=caveats,
            elapsed_sec=time.time() - t0,
        )
        print(
            f"STAMP {summary['verdict']}: winner X={summary['is_winner']['X']} "
            f"D={summary['is_winner']['N']} vs CONTROL X={args.control_x} D={args.control_n}",
            flush=True,
        )
        print(f"Wrote {out_root / 'compare.html'}", flush=True)
        print(f"Wrote {out_root / 'BASELINE.md'}", flush=True)

    # Console summary
    df = pd.DataFrame(rows_primary)
    df_ok = df[df["ok"] == True]  # noqa: E712
    print("\n=== S&P X Diversification summary ===", flush=True)
    if spy_stats.get("ok"):
        print(
            f"SPY BH: CAGR {spy_stats['cagr']:.2f}%  MaxDD {spy_stats['max_dd']:.2f}%  "
            f"Sharpe {spy_stats['sharpe']:.2f}  Final ${spy_stats['final_equity']:,.0f}",
            flush=True,
        )
    if len(df_ok):
        bsh = df_ok.sort_values("sharpe", ascending=False).iloc[0]
        bc = df_ok.sort_values("cagr_pct", ascending=False).iloc[0]
        ref = df_ok[(df_ok["X"] == 20) & (df_ok["N"] == 20)]
        print(f"Best Sharpe: X={int(bsh['X'])} N={int(bsh['N'])}  CAGR {bsh['cagr_pct']:.2f}%  "
              f"MaxDD {bsh['max_dd_pct']:.2f}%  Sharpe {bsh['sharpe']:.2f}  Final ${bsh['final_equity']:,.0f}", flush=True)
        print(f"Best CAGR:   X={int(bc['X'])} N={int(bc['N'])}  CAGR {bc['cagr_pct']:.2f}%  "
              f"MaxDD {bc['max_dd_pct']:.2f}%  Sharpe {bc['sharpe']:.2f}  Final ${bc['final_equity']:,.0f}", flush=True)
        if len(ref):
            r = ref.iloc[0]
            print(f"X=20 N=20:   CAGR {r['cagr_pct']:.2f}%  MaxDD {r['max_dd_pct']:.2f}%  "
                  f"Sharpe {r['sharpe']:.2f}  Final ${r['final_equity']:,.0f}", flush=True)
    print(f"Wrote {csv_path}", flush=True)
    print(f"Wrote {out_root / 'comparison.md'}", flush=True)
    print(f"Elapsed {time.time() - t0:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
