"""S&P X Diversification research: equal-weight top-X by market cap, periodic rebalance.

Not wired to DailyRun. Writes results under drive/spx_diversification/.

Methodology (documented in comparison.md):
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
) -> BacktestResult:
    """Equal-weight top-X, rebalance every N days, annual membership refresh."""
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
    pending: dict[str, Any] | None = None  # execute at open of day i

    total_trades = 0
    traded_notional = 0.0
    avg_equity_for_to = 0.0
    to_count = 0
    n_rebalances = 0
    n_recons = 0
    last_rebalance_i = -10**9
    cost_rate = cost_bps / 10_000.0

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

    def _execute(i: int) -> None:
        nonlocal cash, shares, members, pending, total_trades, traded_notional
        nonlocal avg_equity_for_to, to_count, n_rebalances, n_recons, last_rebalance_i
        if pending is None or pending["exec_i"] != i:
            return
        new_members: list[int] = pending["members"]
        kind = pending["kind"]
        pending = None

        # Delta equal-weight at today's open: sell winners / buy losers (and rotate on recon).
        px = open_arr[i]
        buyable = [j for j in new_members if np.isfinite(px[j]) and px[j] > 0]
        if not buyable:
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
    _schedule_equal_weight(start_i, seed, "recon")

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
                _schedule_equal_weight(i, new, "recon")
        elif members and (i - last_rebalance_i) >= N and pending is None:
            # Equal-weight rebalance of current members (N measured in trading days since last signal)
            _schedule_equal_weight(i, list(members), "rebalance")

        equity[i] = _mark(i)
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
    ) = args
    opens = pd.read_pickle(opens_path)
    closes = pd.read_pickle(closes_path)
    with open(mcap_path, encoding="utf-8") as f:
        mcap_now = {k: float(v) for k, v in json.load(f).items()}
    r = run_one_backtest(
        X=X, N=N, cost_bps=cost_bps, opens=opens, closes=closes, mcap_now=mcap_now, capital0=capital0
    )
    return {
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


def main() -> int:
    ap = argparse.ArgumentParser(description="S&P X Diversification research grid")
    ap.add_argument("--workers", type=int, default=8, help="Parallel backtest workers")
    ap.add_argument("--yf-workers", type=int, default=12, help="yfinance refresh threads")
    ap.add_argument("--cost-bps", type=float, default=DEFAULT_COST_BPS, help="Per-side cost in bps")
    ap.add_argument("--also-zero-cost", action="store_true", help="Also run 0 bps sensitivity grid")
    ap.add_argument("--force-yf", action="store_true", help="Force refresh all market caps")
    ap.add_argument("--start", default="2010-01-01")
    ap.add_argument("--end", default="2026-12-31")
    args = ap.parse_args()

    t0 = time.time()
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    cache_dir = OUT_ROOT / "_cache"
    cache_dir.mkdir(exist_ok=True)

    print("[spx] fetching Wikipedia S&P 500 list...", flush=True)
    wiki = _fetch_sp500_tickers()
    (OUT_ROOT / "sp500_constituents_wikipedia.txt").write_text("\n".join(wiki) + "\n", encoding="utf-8")

    import duckdb

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        db_syms = {str(r[0]).upper() for r in con.execute("SELECT DISTINCT symbol FROM prices").fetchall()}
    finally:
        con.close()

    universe = [s for s in wiki if s in db_syms]
    missing = [s for s in wiki if s not in db_syms]
    (OUT_ROOT / "universe_used.txt").write_text("\n".join(universe) + "\n", encoding="utf-8")
    (OUT_ROOT / "universe_missing.txt").write_text("\n".join(missing) + "\n", encoding="utf-8")
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
        for X in X_GRID:
            for N in N_GRID:
                jobs.append((X, N, cost, str(opens_path), str(closes_path), str(mcap_path), INITIAL_CAPITAL))

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

    csv_path = OUT_ROOT / "comparison.csv"
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
        OUT_ROOT / "comparison.md",
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
    pd.DataFrame(yearly_rows).to_csv(OUT_ROOT / "yearly_returns.csv", index=False)

    # Meta
    meta = {
        "capital": INITIAL_CAPITAL,
        "cost_bps": args.cost_bps,
        "X_grid": list(X_GRID),
        "N_grid": list(N_GRID),
        "universe_n": len(universe),
        "wiki_n": len(wiki),
        "missing_n": len(missing),
        "mcap_n": len(mcap),
        "spy": spy_stats,
        "elapsed_sec": time.time() - t0,
    }
    (OUT_ROOT / "meta.json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")

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
    print(f"Wrote {OUT_ROOT / 'comparison.md'}", flush=True)
    print(f"Elapsed {time.time() - t0:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
