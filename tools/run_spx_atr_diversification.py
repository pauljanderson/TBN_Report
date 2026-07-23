"""S&P ATR Diversification research: top-P by mcap → O lowest ATR% → equal-weight.

Not wired to DailyRun. Writes results under drive/spx_atr_diversification/.

Rule (continuous membership refresh — preferred for this variant):
  Every R trading days, on the signal close:
    1. Rank universe by approx market cap; take top P names.
    2. Among those P, select the O with smallest ATR% = ATR(14)/Close.
    3. Schedule equal-weight into those O names at the next open.
  There is no separate annual reconstitution — mcap pool and ATR filter
  both refresh every rebalance so the rule stays coherent.

ATR definition:
  Same construction as rocket_brt / NewHigh: TR = max(H-L, |H-Cprev|, |L-Cprev|),
  ATR14 = simple rolling mean of TR over 14 bars (project's "Wilder-style" ATR14).
  Primary selection metric: ATR% = ATR14 / Close (apples-to-apples across price levels).
  Optional sensitivity: raw ATR dollars (--atr-mode raw).

Methodology caveats match the SPX diversifier (survivorship, approx caps, etc.).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

from run_spx_diversification import (  # noqa: E402
    INITIAL_CAPITAL,
    DEFAULT_COST_BPS,
    DB_PATH,
    _cagr,
    _fetch_sp500_tickers,
    _first_trading_days_of_year,
    _max_dd_pct,
    _sharpe,
    refresh_market_caps,
    run_one_backtest as run_spx_x_backtest,
    spy_buy_and_hold,
)

OUT_ROOT = REPO / "drive" / "spx_atr_diversification"
ATR_PERIOD = 14

# Primary grid (manageable)
P_GRID = (30, 50, 100)
O_GRID = (5, 10, 15, 20)
R_GRID = (5, 10, 20, 50)
# User-stated case extras: P=50 O=10 also needs R=1
USER_CASE_R = (1, 5, 10, 20, 50)


@dataclass(frozen=True)
class AtrBacktestResult:
    P: int
    O: int
    R: int
    cost_bps: float
    atr_mode: str
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
    yearly_returns: dict[str, float]


def load_ohlc_panels(
    symbols: list[str], *, start: str | None = None, end: str | None = None
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.Series]:
    """Load Open/High/Low/Close panels aligned to SPY calendar."""
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
            SELECT symbol, date AS Date,
                   open AS Open, high AS High, low AS Low, close AS Close
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
    highs = df.pivot(index="Date", columns="symbol", values="High").sort_index()
    lows = df.pivot(index="Date", columns="symbol", values="Low").sort_index()
    closes = df.pivot(index="Date", columns="symbol", values="Close").sort_index()
    if "SPY" not in closes.columns:
        raise RuntimeError("SPY missing from DuckDB prices")
    spy = closes["SPY"].dropna()
    opens = opens.reindex(spy.index)
    highs = highs.reindex(spy.index)
    lows = lows.reindex(spy.index)
    closes = closes.reindex(spy.index)
    return opens, highs, lows, closes, spy


def compute_atr14_panel(
    highs: pd.DataFrame, lows: pd.DataFrame, closes: pd.DataFrame, *, period: int = ATR_PERIOD
) -> pd.DataFrame:
    """ATR14 panel: SMA of True Range (same as rocket_brt._compute_atr_14_arr)."""
    cols = [c for c in closes.columns if c in highs.columns and c in lows.columns]
    h = highs[cols].to_numpy(dtype=float)
    l = lows[cols].to_numpy(dtype=float)
    c = closes[cols].to_numpy(dtype=float)
    n, m = h.shape
    tr = np.full((n, m), np.nan, dtype=np.float64)
    tr[0] = h[0] - l[0]
    if n > 1:
        hl = h[1:] - l[1:]
        h_pc = np.abs(h[1:] - c[:-1])
        l_pc = np.abs(l[1:] - c[:-1])
        tr[1:] = np.maximum.reduce([hl, h_pc, l_pc])
        # Invalidate TR where any of H/L/C (or prior C) is missing
        bad = ~(
            np.isfinite(h[1:]) & np.isfinite(l[1:]) & np.isfinite(c[1:]) & np.isfinite(c[:-1])
        )
        tr[1:][bad] = np.nan
    if not (np.isfinite(h[0]) & np.isfinite(l[0])).all():
        tr[0, ~np.isfinite(h[0]) | ~np.isfinite(l[0])] = np.nan
    # Rolling SMA of TR (min_periods=period → NaN until warm)
    atr = (
        pd.DataFrame(tr, index=closes.index, columns=cols)
        .rolling(window=period, min_periods=period)
        .mean()
    )
    return atr


def run_one_atr_backtest(
    *,
    P: int,
    O: int,
    R: int,
    cost_bps: float,
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    atr: pd.DataFrame,
    mcap_now: dict[str, float],
    atr_mode: str = "pct",
    capital0: float = INITIAL_CAPITAL,
    min_history_days: int = 60,
) -> AtrBacktestResult:
    """Equal-weight O lowest-ATR names from top-P mcap; rebalance every R days.

    Membership (mcap pool + ATR filter) is recomputed every rebalance — not annual-only.
    """
    if O > P:
        return AtrBacktestResult(
            P, O, R, cost_bps, atr_mode, False, f"O={O} > P={P}", "", "", 0, 0, 0, 0, 0, 0, 0, 0.0, 0, {}
        )

    calendar = closes.index
    if len(calendar) < min_history_days + ATR_PERIOD + 5:
        return AtrBacktestResult(
            P, O, R, cost_bps, atr_mode, False, "insufficient calendar",
            "", "", 0, 0, 0, 0, 0, 0, 0, 0.0, 0, {},
        )

    syms = [c for c in closes.columns if c != "SPY" and c in mcap_now and c in atr.columns]
    if len(syms) < P:
        return AtrBacktestResult(
            P, O, R, cost_bps, atr_mode, False, f"only {len(syms)} symbols with mcap+atr",
            "", "", 0, 0, 0, 0, 0, 0, 0, 0.0, 0, {},
        )

    close_arr = closes[syms].to_numpy(dtype=float)
    open_arr = opens[syms].to_numpy(dtype=float)
    atr_arr = atr[syms].to_numpy(dtype=float)
    mcap_vec = np.array([mcap_now[s] for s in syms], dtype=float)

    ref_close = np.full(len(syms), np.nan)
    for j in range(len(syms)):
        col = close_arr[:, j]
        valid = np.where(np.isfinite(col) & (col > 0))[0]
        if len(valid):
            ref_close[j] = col[valid[-1]]

    # Start once ATR is warm enough (and after min history)
    start_i = max(min_history_days, ATR_PERIOD + 5)
    # Align start to first trading day of a year (same as SPX diversifier) for period comparability
    recon_days = _first_trading_days_of_year(calendar)
    for i in range(start_i, len(calendar)):
        if calendar[i] in recon_days:
            start_i = i
            break

    n_days = len(calendar)
    equity = np.full(n_days, np.nan)
    cash = 0.0
    shares = np.zeros(len(syms), dtype=float)
    members: list[int] = []
    pending: dict[str, Any] | None = None

    total_trades = 0
    traded_notional = 0.0
    avg_equity_for_to = 0.0
    to_count = 0
    n_rebalances = 0
    last_rebalance_i = -10**9
    cost_rate = cost_bps / 10_000.0

    def _mcap_at(i: int) -> np.ndarray:
        px = close_arr[i]
        with np.errstate(divide="ignore", invalid="ignore"):
            approx = mcap_vec * (px / ref_close)
        approx[~np.isfinite(approx) | (px <= 0) | ~np.isfinite(px)] = np.nan
        return approx

    def _atr_metric_at(i: int) -> np.ndarray:
        a = atr_arr[i]
        px = close_arr[i]
        if atr_mode == "raw":
            m = a.copy()
        else:
            with np.errstate(divide="ignore", invalid="ignore"):
                m = a / px
        m[~np.isfinite(m) | (a <= 0) | ~np.isfinite(a) | (px <= 0) | ~np.isfinite(px)] = np.nan
        return m

    def _select(i: int) -> list[int] | None:
        mcap = _mcap_at(i)
        order = np.argsort(-np.nan_to_num(mcap, nan=-1.0))
        pool = [int(j) for j in order if np.isfinite(mcap[j])][:P]
        if len(pool) < P:
            return None
        metric = _atr_metric_at(i)
        # Among pool, smallest ATR metric; require finite metric
        scored = [(metric[j], j) for j in pool if np.isfinite(metric[j])]
        if len(scored) < O:
            return None
        scored.sort(key=lambda t: t[0])
        return [j for _, j in scored[:O]]

    def _mark(i: int) -> float:
        px = close_arr[i]
        val = cash
        for j in members:
            p = px[j]
            if np.isfinite(p) and p > 0:
                val += shares[j] * p
        return float(val)

    def _schedule(signal_i: int, new_members: list[int]) -> None:
        nonlocal pending
        exec_i = signal_i + 1
        if exec_i >= n_days:
            return
        pending = {"exec_i": exec_i, "members": list(new_members), "signal_i": signal_i}

    def _execute(i: int) -> None:
        nonlocal cash, shares, members, pending, total_trades, traded_notional
        nonlocal avg_equity_for_to, to_count, n_rebalances, last_rebalance_i
        if pending is None or pending["exec_i"] != i:
            return
        new_members: list[int] = pending["members"]
        pending = None

        px = open_arr[i]
        buyable = [j for j in new_members if np.isfinite(px[j]) and px[j] > 0]
        if not buyable:
            return

        equity_pre = cash
        held = set(members)
        for j in list(held):
            p = px[j]
            if not (np.isfinite(p) and p > 0):
                cprev = close_arr[i - 1, j] if i > 0 else np.nan
                p = cprev if np.isfinite(cprev) and cprev > 0 else np.nan
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

        for j in buyable:
            p = float(px[j])
            cur_val = shares[j] * p if shares[j] != 0 else 0.0
            delta = target_dollar - cur_val
            if abs(delta) < 1e-6:
                continue
            shares[j] += delta / p
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
        n_rebalances += 1

    seed = _select(start_i)
    if seed is None or len(seed) < O:
        return AtrBacktestResult(
            P, O, R, cost_bps, atr_mode, False, "seed selection incomplete", "", "", 0, 0, 0, 0, 0, 0, 0, 0.0, 0, {}
        )
    cash = capital0
    members = []
    shares[:] = 0
    _schedule(start_i, seed)

    yearly_equity: dict[int, float] = {}

    for i in range(start_i, n_days):
        _execute(i)
        if i == start_i:
            pass
        elif members and (i - last_rebalance_i) >= R and pending is None:
            sel = _select(i)
            if sel is not None and len(sel) >= O:
                _schedule(i, sel)

        equity[i] = _mark(i)
        y = int(calendar[i].year)
        yearly_equity[y] = equity[i]

    valid_idx = np.where(np.isfinite(equity))[0]
    if len(valid_idx) < 5:
        return AtrBacktestResult(
            P, O, R, cost_bps, atr_mode, False, "no equity path", "", "", 0, 0, 0, 0, 0, 0, 0, 0.0, 0, {}
        )
    first = valid_idx[0]
    eq_path = equity[first:].copy()
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

    years_sorted = sorted(yearly_equity)
    yearly_returns: dict[str, float] = {}
    prev = capital0
    for yi, y in enumerate(years_sorted):
        end_eq = yearly_equity[y]
        if yi == 0:
            yearly_returns[str(y)] = end_eq / capital0 - 1.0
        else:
            yearly_returns[str(y)] = end_eq / prev - 1.0
        prev = end_eq

    avg_eq = (avg_equity_for_to / to_count) if to_count else capital0
    turnover = (traded_notional / avg_eq) if avg_eq > 0 else 0.0

    return AtrBacktestResult(
        P=P,
        O=O,
        R=R,
        cost_bps=cost_bps,
        atr_mode=atr_mode,
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
        yearly_returns=yearly_returns,
    )


def _result_to_dict(r: AtrBacktestResult) -> dict[str, Any]:
    return {
        "P": r.P,
        "O": r.O,
        "R": r.R,
        "cost_bps": r.cost_bps,
        "atr_mode": r.atr_mode,
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
        "yearly_returns": r.yearly_returns,
        "id": f"ATR_P{r.P}_O{r.O}_R{r.R}",
        "label": f"top-P={r.P} → lowest-ATR O={r.O}, R={r.R}",
    }


def _worker_payload(args: tuple) -> dict[str, Any]:
    (
        P,
        O,
        R,
        cost_bps,
        atr_mode,
        opens_path,
        closes_path,
        atr_path,
        mcap_path,
        capital0,
    ) = args
    opens = pd.read_pickle(opens_path)
    closes = pd.read_pickle(closes_path)
    atr = pd.read_pickle(atr_path)
    with open(mcap_path, encoding="utf-8") as f:
        mcap_now = {k: float(v) for k, v in json.load(f).items()}
    r = run_one_atr_backtest(
        P=P,
        O=O,
        R=R,
        cost_bps=cost_bps,
        opens=opens,
        closes=closes,
        atr=atr,
        mcap_now=mcap_now,
        atr_mode=atr_mode,
        capital0=capital0,
    )
    return _result_to_dict(r)


def _spx_baseline_worker(args: tuple) -> dict[str, Any]:
    X, N, cost_bps, opens_path, closes_path, mcap_path, capital0 = args
    opens = pd.read_pickle(opens_path)
    closes = pd.read_pickle(closes_path)
    with open(mcap_path, encoding="utf-8") as f:
        mcap_now = {k: float(v) for k, v in json.load(f).items()}
    r = run_spx_x_backtest(
        X=X, N=N, cost_bps=cost_bps, opens=opens, closes=closes, mcap_now=mcap_now, capital0=capital0
    )
    return {
        "P": X,
        "O": X,
        "R": N,
        "cost_bps": r.cost_bps,
        "atr_mode": "n/a",
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
        "yearly_returns": r.yearly_returns,
        "id": f"SPX_X{X}_N{N}",
        "label": f"SPX-X equal-weight X={X} N={N} (no ATR filter)",
    }


def result_to_row(r: dict[str, Any], spy: dict[str, Any] | None = None) -> dict[str, Any]:
    row = {
        "id": r.get("id", ""),
        "label": r.get("label", ""),
        "P": r.get("P"),
        "O": r.get("O"),
        "R": r.get("R"),
        "atr_mode": r.get("atr_mode", ""),
        "cost_bps": r.get("cost_bps", 0.0),
        "ok": r.get("ok"),
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
    for y, ret in (r.get("yearly_returns") or {}).items():
        row[f"yr_{y}"] = ret * 100.0
    return row


def write_comparison_md(
    path: Path,
    rows: list[dict[str, Any]],
    spy: dict[str, Any],
    baselines: list[dict[str, Any]],
    *,
    universe_n: int,
    wiki_n: int,
    missing_n: int,
    mcap_n: int,
    cost_bps: float,
    atr_mode: str,
    caveats: list[str],
) -> None:
    df = pd.DataFrame(rows)
    atr_df = df[df["id"].astype(str).str.startswith("ATR_") & (df["ok"] == True)].copy()  # noqa: E712

    def _fmt(r: pd.Series | dict) -> str:
        if isinstance(r, dict):
            return (
                f"{r.get('id', '')}: CAGR {r.get('cagr_pct', r.get('cagr', 0)):.2f}%, "
                f"MaxDD {r.get('max_dd_pct', r.get('max_dd', 0)):.2f}%, "
                f"Sharpe {r.get('sharpe', 0):.2f}, Final ${r.get('final_equity', 0):,.0f}"
            )
        return (
            f"P={int(r['P'])} O={int(r['O'])} R={int(r['R'])}: "
            f"CAGR {r['cagr_pct']:.2f}%, MaxDD {r['max_dd_pct']:.2f}%, "
            f"Sharpe {r['sharpe']:.2f}, Final ${r['final_equity']:,.0f}, "
            f"TotalRet {r['total_return_pct']:.1f}%"
        )

    lines: list[str] = []
    lines.append("# S&P ATR Diversification — Grid Results")
    lines.append("")
    lines.append("## Plain-English rule")
    lines.append("")
    lines.append(
        "Every **R** trading days: take the **P** largest S&P names by (approx) market cap, "
        "keep the **O** with the **lowest ATR%** (14-day average true range ÷ close), "
        "and equal-weight invest $500k across those O names. On each rebalance, refresh both "
        "the market-cap pool and the ATR ranking, then equalize weights. Fills at next open; "
        f"{cost_bps:g} bps/side on traded notional."
    )
    lines.append("")
    lines.append("### Variables")
    lines.append("")
    lines.append("| Symbol | Meaning | Default (user example) |")
    lines.append("| --- | --- | --- |")
    lines.append("| **P** | Market-cap pool size (top P by mcap) | 50 |")
    lines.append("| **O** | Number selected by smallest ATR% | 10 |")
    lines.append("| **R** | Rebalance period in trading days | 5 / 10 / 20 / … |")
    lines.append("")
    lines.append("### Membership refresh choice")
    lines.append("")
    lines.append(
        "**Chosen: continuous (every rebalance).** Market-cap top-P and ATR ranking are both "
        "recomputed on every R-day signal. This keeps the rule coherent (low-vol filter always "
        "applies to the *current* mega-cap pool)."
    )
    lines.append("")
    lines.append(
        "Contrast with the prior SPX-X diversifier, which refreshes the top-X mcap *membership* "
        "only annually and equal-weights those fixed members every N days. An annual-only mcap "
        "pool with intra-year ATR re-ranking would be a middle ground; not used here."
    )
    lines.append("")
    lines.append("### ATR definition")
    lines.append("")
    lines.append(
        f"- **ATR(14):** True Range = max(H−L, |H−Cprev|, |L−Cprev|); ATR14 = **SMA of TR over 14 bars** "
        f"(same construction as `rocket_brt._compute_atr_14_arr` / NewHigh — project's Wilder-style ATR)."
    )
    lines.append(
        f"- **Primary metric (this run):** **ATR% = ATR14 / Close** (`atr_mode={atr_mode}`). "
        "Preferred so a $20 stock and a $800 stock are comparable."
    )
    lines.append(
        "- **Optional sensitivity:** raw ATR in dollars (`--atr-mode raw`) — can bias toward "
        "low-priced names; run separately if needed."
    )
    lines.append("")
    lines.append(f"- **Capital:** ${INITIAL_CAPITAL:,.0f}")
    lines.append(f"- **Cost model:** {cost_bps:g} bps/side on traded notional")
    lines.append("- **Fills:** next open after signal")
    lines.append(
        f"- **Universe:** Wikipedia S&P 500 ({wiki_n}) ∩ DuckDB OHLC → {universe_n} names "
        f"({missing_n} missing locally); {mcap_n} with usable market cap"
    )
    lines.append("")
    lines.append("## Headline")
    lines.append("")
    if spy.get("ok"):
        lines.append(
            f"- **SPY BH:** CAGR {spy['cagr']:.2f}%, MaxDD {spy['max_dd']:.2f}%, "
            f"Sharpe {spy['sharpe']:.2f}, Final ${spy['final_equity']:,.0f}, "
            f"TotalRet {spy['total_return']:.1f}% ({spy['start']} → {spy['end']})"
        )
    for b in baselines:
        if b.get("ok"):
            lines.append(f"- **{b.get('label')}:** {_fmt(b)}")

    if len(atr_df):
        best_cagr = atr_df.sort_values("cagr_pct", ascending=False).iloc[0]
        best_sharpe = atr_df.sort_values("sharpe", ascending=False).iloc[0]
        lines.append(f"- **Best ATR CAGR:** {_fmt(best_cagr)}")
        lines.append(f"- **Best ATR Sharpe:** {_fmt(best_sharpe)}")
        user = atr_df[(atr_df["P"] == 50) & (atr_df["O"] == 10)].sort_values("R")
        if len(user):
            lines.append("")
            lines.append("### User case P=50 / O=10 across R")
            lines.append("")
            lines.append("| R | CAGR % | MaxDD % | Sharpe | Final $ | TotalRet % | Trades | vs SPY CAGR pp |")
            lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
            for _, r in user.iterrows():
                vs = r["vs_spy_cagr_pp"] if "vs_spy_cagr_pp" in r and pd.notna(r["vs_spy_cagr_pp"]) else float("nan")
                vs_s = f"{vs:.2f}" if np.isfinite(vs) else ""
                lines.append(
                    f"| {int(r['R'])} | {r['cagr_pct']:.2f} | {r['max_dd_pct']:.2f} | "
                    f"{r['sharpe']:.3f} | {r['final_equity']:,.0f} | {r['total_return_pct']:.1f} | "
                    f"{int(r['total_trades'])} | {vs_s} |"
                )
    lines.append("")
    lines.append("## Full ATR grid (ranked by Sharpe)")
    lines.append("")
    if len(atr_df):
        show = atr_df.sort_values(["sharpe", "cagr_pct"], ascending=False)
        cols = [
            "P", "O", "R", "cagr_pct", "total_return_pct", "max_dd_pct", "sharpe", "ann_vol_pct",
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
                    cells.append(f"{v:.2f}" if pd.notna(v) else "")
                elif c == "sharpe":
                    cells.append(f"{v:.3f}")
                elif c == "final_equity":
                    cells.append(f"{v:,.0f}")
                elif c == "turnover":
                    cells.append(f"{v:.2f}")
                else:
                    cells.append(str(int(v) if c in ("P", "O", "R", "total_trades") else v))
            lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("## Methodology caveats")
    lines.append("")
    for c in caveats:
        lines.append(f"- {c}")
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_job_list(cost_bps: float, atr_mode: str, paths: dict[str, str]) -> list[tuple]:
    jobs: list[tuple] = []
    seen: set[tuple[int, int, int]] = set()
    # Full primary grid
    for P in P_GRID:
        for O in O_GRID:
            if O > P:
                continue
            for R in R_GRID:
                seen.add((P, O, R))
                jobs.append(
                    (P, O, R, cost_bps, atr_mode, paths["opens"], paths["closes"], paths["atr"], paths["mcap"], INITIAL_CAPITAL)
                )
    # Ensure user case P=50 O=10 includes R=1
    for R in USER_CASE_R:
        key = (50, 10, R)
        if key not in seen:
            seen.add(key)
            jobs.append(
                (50, 10, R, cost_bps, atr_mode, paths["opens"], paths["closes"], paths["atr"], paths["mcap"], INITIAL_CAPITAL)
            )
    return jobs


def main() -> int:
    ap = argparse.ArgumentParser(description="S&P ATR Diversification research grid")
    ap.add_argument("--workers", type=int, default=max(1, (os_cpu := __import__("os").cpu_count() or 8) - 1))
    ap.add_argument("--yf-workers", type=int, default=12)
    ap.add_argument("--cost-bps", type=float, default=DEFAULT_COST_BPS)
    ap.add_argument("--atr-mode", choices=("pct", "raw"), default="pct", help="ATR% (preferred) or raw ATR$")
    ap.add_argument("--also-raw", action="store_true", help="Also run raw-ATR sensitivity on P=50 O=10 R grid")
    ap.add_argument("--force-yf", action="store_true")
    ap.add_argument("--start", default="2010-01-01")
    ap.add_argument("--end", default="2026-12-31")
    ap.add_argument("--skip-baselines", action="store_true", help="Skip re-running SPX X=10/20 baselines")
    args = ap.parse_args()

    t0 = time.time()
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    cache_dir = OUT_ROOT / "_cache"
    cache_dir.mkdir(exist_ok=True)

    # Reuse SPX diversifier cache if present (same universe/mcap)
    spx_cache = REPO / "drive" / "spx_diversification" / "_cache"

    print("[atr] fetching Wikipedia S&P 500 list...", flush=True)
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
    print(f"[atr] universe {len(universe)} / wiki {len(wiki)} (missing {len(missing)})", flush=True)

    # Prefer fresh refresh; fall back to SPX cache mcap
    mcap = refresh_market_caps(universe, workers=args.yf_workers, force=args.force_yf)
    if "GOOG" in mcap and "GOOGL" in mcap:
        drop = "GOOG" if "GOOGL" in universe else "GOOGL"
        mcap.pop(drop, None)
        print(f"[atr] dropped dual-class {drop}", flush=True)
    print(f"[atr] market caps available: {len(mcap)}", flush=True)

    print("[atr] loading OHLC panels from DuckDB...", flush=True)
    opens, highs, lows, closes, spy = load_ohlc_panels(list(mcap.keys()), start=args.start, end=args.end)
    keep = [c for c in closes.columns if c == "SPY" or c in mcap]
    opens, highs, lows, closes = opens[keep], highs[keep], lows[keep], closes[keep]

    print("[atr] computing ATR14 panel...", flush=True)
    atr = compute_atr14_panel(highs, lows, closes)
    # Drop SPY from atr selection universe (keep in closes for calendar)
    if "SPY" in atr.columns:
        atr = atr.drop(columns=["SPY"])

    opens_path = cache_dir / "opens.pkl"
    closes_path = cache_dir / "closes.pkl"
    atr_path = cache_dir / "atr14.pkl"
    highs_path = cache_dir / "highs.pkl"
    lows_path = cache_dir / "lows.pkl"
    mcap_path = cache_dir / "mcap.json"
    opens.to_pickle(opens_path)
    closes.to_pickle(closes_path)
    atr.to_pickle(atr_path)
    highs.to_pickle(highs_path)
    lows.to_pickle(lows_path)
    mcap_path.write_text(json.dumps(mcap), encoding="utf-8")

    paths = {
        "opens": str(opens_path),
        "closes": str(closes_path),
        "atr": str(atr_path),
        "mcap": str(mcap_path),
    }

    jobs = _build_job_list(args.cost_bps, args.atr_mode, paths)
    if args.also_raw and args.atr_mode == "pct":
        for R in USER_CASE_R:
            jobs.append(
                (50, 10, R, args.cost_bps, "raw", paths["opens"], paths["closes"], paths["atr"], paths["mcap"], INITIAL_CAPITAL)
            )

    print(f"[atr] running {len(jobs)} ATR backtests with {args.workers} workers...", flush=True)
    results: list[dict[str, Any]] = []
    if args.workers <= 1:
        for job in jobs:
            results.append(_worker_payload(job))
            print(f"  done P={job[0]} O={job[1]} R={job[2]} mode={job[4]}", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(_worker_payload, job): job for job in jobs}
            for fut in as_completed(futs):
                job = futs[fut]
                try:
                    results.append(fut.result())
                    print(f"  done P={job[0]} O={job[1]} R={job[2]} mode={job[4]}", flush=True)
                except Exception as exc:  # noqa: BLE001
                    results.append({
                        "P": job[0], "O": job[1], "R": job[2], "cost_bps": job[3],
                        "atr_mode": job[4], "ok": False, "error": str(exc),
                        "yearly_returns": {}, "id": f"ATR_P{job[0]}_O{job[1]}_R{job[2]}",
                        "label": "",
                    })
                    print(f"  FAIL P={job[0]} O={job[1]} R={job[2]}: {exc}", flush=True)

    baselines: list[dict[str, Any]] = []
    if not args.skip_baselines:
        # Re-run SPX X=10 N=5 and X=20 N=20 on same panels for apples-to-apples dates
        base_jobs = [
            (10, 5, args.cost_bps, str(opens_path), str(closes_path), str(mcap_path), INITIAL_CAPITAL),
            (20, 20, args.cost_bps, str(opens_path), str(closes_path), str(mcap_path), INITIAL_CAPITAL),
        ]
        print("[atr] running SPX-X baselines (X=10 N=5, X=20 N=20)...", flush=True)
        for bj in base_jobs:
            try:
                baselines.append(_spx_baseline_worker(bj))
                print(f"  baseline X={bj[0]} N={bj[1]} ok={baselines[-1].get('ok')}", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"  baseline FAIL X={bj[0]}: {exc}", flush=True)
                # Fall back to prior comparison.csv if available
                prior_csv = REPO / "drive" / "spx_diversification" / "comparison.csv"
                if prior_csv.is_file():
                    pdf = pd.read_csv(prior_csv)
                    hit = pdf[(pdf["X"] == bj[0]) & (pdf["N"] == bj[1]) & (pdf["cost_bps"] == args.cost_bps)]
                    if len(hit):
                        r = hit.iloc[0]
                        baselines.append({
                            "P": bj[0], "O": bj[0], "R": bj[1], "cost_bps": args.cost_bps,
                            "atr_mode": "n/a", "ok": True, "error": "",
                            "start": r.get("start", ""), "end": r.get("end", ""),
                            "final_equity": float(r["final_equity"]),
                            "total_return": float(r["total_return_pct"]),
                            "cagr": float(r["cagr_pct"]), "max_dd": float(r["max_dd_pct"]),
                            "sharpe": float(r["sharpe"]), "ann_vol": float(r.get("ann_vol_pct", 0)),
                            "total_trades": int(r.get("total_trades", 0)),
                            "turnover": float(r.get("turnover", 0)),
                            "n_rebalances": int(r.get("n_rebalances", 0)),
                            "yearly_returns": {},
                            "id": f"SPX_X{bj[0]}_N{bj[1]}",
                            "label": f"SPX-X equal-weight X={bj[0]} N={bj[1]} (from prior CSV)",
                        })

    primary = [r for r in results if r.get("ok")]
    if primary:
        spy_start = min(r["start"] for r in primary)
        spy_end = max(r["end"] for r in primary)
    else:
        spy_start, spy_end = args.start, args.end
    spy_stats = spy_buy_and_hold(spy, start=spy_start, end=spy_end, capital=INITIAL_CAPITAL, cost_bps=0.0)

    all_for_csv = results + baselines
    rows = [result_to_row(r, spy_stats) for r in all_for_csv]
    # Normalize baseline rows for markdown helper
    baseline_rows = [result_to_row(b, spy_stats) for b in baselines]

    csv_path = OUT_ROOT / "comparison.csv"
    pd.DataFrame(rows).sort_values(
        ["atr_mode", "sharpe", "cagr_pct"], ascending=[True, False, False]
    ).to_csv(csv_path, index=False)

    caveats = [
        "**No historical S&P 500 membership** — today's Wikipedia list projected backward "
        "(survivorship bias: delisted/removed names never appear).",
        f"**{len(missing)} current S&P names missing** from local OHLC and are excluded.",
        "**Market caps are not historical**: Yahoo point-in-time `marketCap` scaled by "
        "`Close_t / Close_now` (constant share-count approximation).",
        "**Membership refresh:** every rebalance recomputes top-P mcap **and** lowest-O ATR% "
        "(not annual-only). See report section above.",
        "DuckDB Close is split-adjusted as ingested; dividends are not reinvested "
        "(price appreciation only).",
        f"ATR uses SMA-of-TR(14) matching rocket_brt; primary rank metric is ATR% "
        f"(atr_mode={args.atr_mode}).",
        f"Fills at **next open**; costs **{args.cost_bps:g} bps/side** on traded notional.",
        "Sharpe uses daily equity returns, rf=0, ann. factor √252 — descriptive, not a forecast.",
        "Turnover is cumulative traded notional / average equity at rebalance events (not annualized).",
        "This is the **ATR-filter** strategy; a separate 'top 10 market cap only' ask is a different experiment.",
    ]

    # Primary ATR% rows for markdown
    atr_primary_rows = [
        row for row in rows
        if str(row.get("id", "")).startswith("ATR_") and row.get("atr_mode") == args.atr_mode
    ]
    write_comparison_md(
        OUT_ROOT / "comparison.md",
        atr_primary_rows + baseline_rows,
        spy_stats,
        baseline_rows,
        universe_n=len(universe),
        wiki_n=len(wiki),
        missing_n=len(missing),
        mcap_n=len(mcap),
        cost_bps=args.cost_bps,
        atr_mode=args.atr_mode,
        caveats=caveats,
    )

    yearly_rows = []
    for r in all_for_csv:
        if not r.get("ok"):
            continue
        for y, ret in (r.get("yearly_returns") or {}).items():
            yearly_rows.append({
                "id": r.get("id"), "P": r.get("P"), "O": r.get("O"), "R": r.get("R"),
                "atr_mode": r.get("atr_mode"), "cost_bps": r.get("cost_bps"),
                "year": y, "return_pct": ret * 100.0,
            })
    if spy_stats.get("ok"):
        for y, ret in spy_stats["yearly_returns"].items():
            yearly_rows.append({
                "id": "SPY_BH", "P": 0, "O": 0, "R": 0, "atr_mode": "n/a",
                "cost_bps": 0.0, "year": y, "return_pct": ret * 100.0,
            })
    pd.DataFrame(yearly_rows).to_csv(OUT_ROOT / "yearly_returns.csv", index=False)

    meta = {
        "capital": INITIAL_CAPITAL,
        "cost_bps": args.cost_bps,
        "atr_mode": args.atr_mode,
        "atr_period": ATR_PERIOD,
        "P_grid": list(P_GRID),
        "O_grid": list(O_GRID),
        "R_grid": list(R_GRID),
        "user_case": {"P": 50, "O": 10, "R": list(USER_CASE_R)},
        "membership_refresh": "every_rebalance",
        "universe_n": len(universe),
        "wiki_n": len(wiki),
        "missing_n": len(missing),
        "mcap_n": len(mcap),
        "spy": spy_stats,
        "baselines": [{k: v for k, v in b.items() if k != "yearly_returns"} for b in baselines],
        "elapsed_sec": time.time() - t0,
        "note": "ATR-filter strategy (distinct from top-10 mcap-only ask).",
    }
    (OUT_ROOT / "meta.json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")

    # Console summary
    print("\n=== S&P ATR Diversification summary ===", flush=True)
    if spy_stats.get("ok"):
        print(
            f"SPY BH: CAGR {spy_stats['cagr']:.2f}%  MaxDD {spy_stats['max_dd']:.2f}%  "
            f"Sharpe {spy_stats['sharpe']:.2f}  Final ${spy_stats['final_equity']:,.0f}",
            flush=True,
        )
    for b in baseline_rows:
        if b.get("ok"):
            print(
                f"{b['id']}: CAGR {b['cagr_pct']:.2f}%  MaxDD {b['max_dd_pct']:.2f}%  "
                f"Sharpe {b['sharpe']:.2f}  Final ${b['final_equity']:,.0f}",
                flush=True,
            )
    adf = pd.DataFrame(atr_primary_rows)
    adf = adf[adf["ok"] == True]  # noqa: E712
    if len(adf):
        user = adf[(adf["P"] == 50) & (adf["O"] == 10)].sort_values("R")
        print("\nP=50 O=10 by R:", flush=True)
        for _, r in user.iterrows():
            print(
                f"  R={int(r['R']):>3}: CAGR {r['cagr_pct']:6.2f}%  MaxDD {r['max_dd_pct']:5.2f}%  "
                f"Sharpe {r['sharpe']:.3f}  Final ${r['final_equity']:>12,.0f}",
                flush=True,
            )
        bsh = adf.sort_values("sharpe", ascending=False).iloc[0]
        bc = adf.sort_values("cagr_pct", ascending=False).iloc[0]
        print(
            f"\nBest Sharpe: P={int(bsh['P'])} O={int(bsh['O'])} R={int(bsh['R'])}  "
            f"CAGR {bsh['cagr_pct']:.2f}%  MaxDD {bsh['max_dd_pct']:.2f}%  "
            f"Sharpe {bsh['sharpe']:.2f}  Final ${bsh['final_equity']:,.0f}",
            flush=True,
        )
        print(
            f"Best CAGR:   P={int(bc['P'])} O={int(bc['O'])} R={int(bc['R'])}  "
            f"CAGR {bc['cagr_pct']:.2f}%  MaxDD {bc['max_dd_pct']:.2f}%  "
            f"Sharpe {bc['sharpe']:.2f}  Final ${bc['final_equity']:,.0f}",
            flush=True,
        )
    print(f"Wrote {csv_path}", flush=True)
    print(f"Wrote {OUT_ROOT / 'comparison.md'}", flush=True)
    print(f"Elapsed {time.time() - t0:.1f}s", flush=True)
    # silence unused
    _ = spx_cache
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
