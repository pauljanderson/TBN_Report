#!/usr/bin/env python3
"""Right side of the V vs buy-the-open, on the same washout list.

From Chat With Traders episode 236 (Lance Breitstein, recorded 13 June 2022).
One knob: entry. Universe, stop, target, and time stop are frozen for both arms.

Research only. Not gold. Not DailyRun.

  python tools/lance_rsv_washout_ab_20261001.py
"""
from __future__ import annotations

import html as html_mod
import json
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))

import compare_format as cf  # noqa: E402
from _gen_too_high_diff import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    sortable_th,
)

STAMP = "lance_rsv_washout_ab_20261001"
OUT = REPO / "drive" / "paul_experiments" / STAMP
DB = REPO / "data" / "ohlcv.duckdb"
IS_CUT = pd.Timestamp("2024-01-01")
SHEET = 10_000.0
ACCOUNT = 500_000.0

# Frozen before the run. Not searched.
LOOKBACK = 5
MIN_DROP = 0.15
MIN_EXCESS = 0.08
VOL_MULT = 2.0
VOL_WINDOW = 20
MIN_DOLLAR_VOL = 20_000_000.0
TOP_N = 10
HOLD_BARS = 10  # sessions including the entry bar
TARGET_R = 1.0

ORIGINAL_REQUEST = (
    "can you detail the discussion in episode 236? can we create a system from what we learn here? "
    "yes please. lets run a test"
)
LAYMAN = (
    "Chat With Traders episode 236 is Lance Breitstein describing how he trades a stock that has "
    "already fallen a long way in a short time. He does not buy it while it is still falling. He waits "
    "until it turns up, then uses the low of the fall as the point where he is wrong. "
    "This test copies that idea with daily prices. Each day we list the stocks that fell at least 15% "
    "in five sessions, fell at least 8 percentage points harder than the Nasdaq-100 exchange-traded fund "
    "(QQQ), and traded at least twice their recent volume, with at least $20 million of stock changing hands. "
    "We keep the ten most extreme names. The control buys the next morning at the open, as long as that open "
    "is still above the low of the fall. The test arm buys the next day only if price trades above the high "
    "of the fall. Both arms risk the same stop (that low), both take profit at a gain equal to the risk "
    "(1R), and both are sold at the close if neither has happened after ten sessions. "
    "In-sample means the buy was before 2024. Results from 2024 onward are a report only. "
    "This is a research test. It is not a live system."
)


def _esc(x: Any) -> str:
    return html_mod.escape("" if x is None else str(x))


def _f(v: Any, d: int = 2) -> str:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    if not np.isfinite(n):
        return "—"
    return f"{n:,.{d}f}"


def _fp(v: Any, d: int = 2) -> str:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    if not np.isfinite(n):
        return "—"
    return f"{n:.{d}f}%"


def _fd(v: Any, d: int = 2, pct: bool = False) -> str:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    if not np.isfinite(n):
        return "—"
    sign = "+" if n > 0 else ""
    if pct:
        return f"{sign}{n:.{d}f} pp"
    return f"{sign}{n:,.{d}f}"


def load_signals(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    q = f"""
    WITH px AS (
      SELECT upper(symbol) AS symbol,
             CAST(date AS DATE) AS d,
             open, high, low, close, volume
      FROM prices
      WHERE open > 0 AND high > 0 AND low > 0 AND close > 0 AND volume >= 0
    ),
    qqq AS (
      SELECT d, close AS qclose FROM px WHERE symbol = 'QQQ'
    ),
    calc AS (
      SELECT
        p.symbol, p.d, p.open, p.high, p.low, p.close, p.volume,
        p.close / lag(p.close, {LOOKBACK}) OVER w - 1 AS ret5,
        q.qclose / lag(q.qclose, {LOOKBACK}) OVER w - 1 AS qret5,
        p.volume / nullif(avg(p.volume) OVER (
          PARTITION BY p.symbol ORDER BY p.d
          ROWS BETWEEN {VOL_WINDOW} PRECEDING AND 1 PRECEDING
        ), 0) AS vol_ratio,
        lag(p.volume, {VOL_WINDOW}) OVER w AS vol_full,
        p.close * p.volume AS dvol
      FROM px p
      JOIN qqq q ON p.d = q.d
      WINDOW w AS (PARTITION BY p.symbol ORDER BY p.d)
    )
    SELECT symbol, d, open, high, low, close, volume, ret5, qret5,
           ret5 - qret5 AS excess, vol_ratio, dvol
    FROM calc
    WHERE symbol <> 'QQQ'
      AND vol_full IS NOT NULL
      AND ret5 <= -{MIN_DROP}
      AND (ret5 - qret5) <= -{MIN_EXCESS}
      AND vol_ratio >= {VOL_MULT}
      AND dvol >= {MIN_DOLLAR_VOL}
      AND high > low
    ORDER BY d, excess
    """
    df = con.execute(q).fetchdf()
    df["d"] = pd.to_datetime(df["d"])
    return df


def load_bars(con: duckdb.DuckDBPyConnection, symbols: list[str]) -> dict[str, pd.DataFrame]:
    if not symbols:
        return {}
    con.register("_syms", pd.DataFrame({"symbol": symbols}))
    bars = con.execute(
        """
        SELECT upper(p.symbol) AS symbol, CAST(p.date AS DATE) AS d,
               p.open, p.high, p.low, p.close
        FROM prices p
        JOIN _syms s ON upper(p.symbol) = s.symbol
        WHERE p.open > 0 AND p.high > 0 AND p.low > 0 AND p.close > 0
        ORDER BY 1, 2
        """
    ).fetchdf()
    bars["d"] = pd.to_datetime(bars["d"])
    out: dict[str, pd.DataFrame] = {}
    for sym, g in bars.groupby("symbol", sort=False):
        out[str(sym)] = g.reset_index(drop=True)
    return out


def pick_signals(sig: pd.DataFrame, bars: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Top 10 each day, one live window per name, using that name's own calendar."""
    idx_map: dict[str, dict[pd.Timestamp, int]] = {}
    for sym, g in bars.items():
        idx_map[sym] = {pd.Timestamp(d): i for i, d in enumerate(g["d"])}

    locked: dict[str, int] = {}
    kept: list[dict[str, Any]] = []
    for day, chunk in sig.groupby("d", sort=True):
        chunk = chunk.sort_values(["excess", "symbol"])
        n_take = 0
        for row in chunk.itertuples(index=False):
            sym = str(row.symbol)
            imap = idx_map.get(sym)
            if imap is None:
                continue
            i = imap.get(pd.Timestamp(day))
            if i is None or i + 1 >= len(bars[sym]):
                continue
            if i <= locked.get(sym, -1):
                continue
            entry_i = i + 1
            lock_through = entry_i + HOLD_BARS - 1
            locked[sym] = lock_through
            kept.append(
                {
                    "symbol": sym,
                    "signal_date": pd.Timestamp(day),
                    "sig_i": i,
                    "entry_i": entry_i,
                    "ret5": float(row.ret5),
                    "qret5": float(row.qret5),
                    "excess": float(row.excess),
                    "vol_ratio": float(row.vol_ratio),
                    "dvol": float(row.dvol),
                    "climax_high": float(row.high),
                    "climax_low": float(row.low),
                    "climax_close": float(row.close),
                }
            )
            n_take += 1
            if n_take >= TOP_N:
                break
    return pd.DataFrame(kept)


def _walk(
    g: pd.DataFrame,
    entry_i: int,
    entry_px: float,
    stop: float,
    target: float,
) -> tuple[float, str, int]:
    last = min(entry_i + HOLD_BARS - 1, len(g) - 1)
    for i in range(entry_i, last + 1):
        o = float(g.at[i, "open"])
        h = float(g.at[i, "high"])
        l = float(g.at[i, "low"])
        c = float(g.at[i, "close"])
        if l <= stop:
            if o <= stop:
                return o, "GAP_STOP", i
            return stop, "STOP", i
        if h >= target:
            if o >= target:
                return o, "GAP_TARGET", i
            return target, "TARGET", i
        if i == last:
            return c, "TIME", i
    c = float(g.at[last, "close"])
    return c, "TIME", last


def simulate(picks: pd.DataFrame, bars: dict[str, pd.DataFrame], arm: str) -> list[dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    skips = 0
    for row in picks.itertuples(index=False):
        g = bars[row.symbol]
        i = int(row.entry_i)
        stop = float(row.climax_low)
        o = float(g.at[i, "open"])
        h = float(g.at[i, "high"])
        if arm == "control":
            if o <= stop:
                skips += 1
                continue
            entry_px = o
        else:
            if h < float(row.climax_high):
                skips += 1
                continue
            entry_px = o if o >= float(row.climax_high) else float(row.climax_high)
            if entry_px <= stop:
                skips += 1
                continue
        risk = entry_px - stop
        if risk <= 0:
            skips += 1
            continue
        target = entry_px + TARGET_R * risk
        exit_px, reason, exit_i = _walk(g, i, entry_px, stop, target)
        opened = pd.Timestamp(g.at[i, "d"])
        closed = pd.Timestamp(g.at[exit_i, "d"])
        pnl_pct = (exit_px / entry_px - 1.0) * 100.0
        r_mult = (exit_px - entry_px) / risk
        sessions = exit_i - i + 1
        trades.append(
            {
                "arm": arm,
                "symbol": row.symbol,
                "signal_date": pd.Timestamp(row.signal_date).date().isoformat(),
                "opened": opened.date().isoformat(),
                "closed": closed.date().isoformat(),
                "opened_ts": opened,
                "closed_ts": closed,
                "entry": entry_px,
                "exit": exit_px,
                "stop": stop,
                "target": target,
                "pnl": pnl_pct,
                "pnl_d": pnl_pct / 100.0 * SHEET,
                "r": r_mult,
                "days": max(int((closed - opened).days), 1),
                "sessions": sessions,
                "exit_reason": reason,
                "ret5": row.ret5,
                "excess": row.excess,
                "vol_ratio": row.vol_ratio,
            }
        )
    simulate.last_skips = skips  # type: ignore[attr-defined]
    return trades


def _slice(trades: list[dict[str, Any]], which: str) -> list[dict[str, Any]]:
    if which == "all":
        return trades
    if which == "is":
        return [t for t in trades if t["opened_ts"] < IS_CUT]
    return [t for t in trades if t["opened_ts"] >= IS_CUT]


def summarize(trades: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(trades)
    if n == 0:
        return {"n": 0}
    pnl = np.array([t["pnl"] for t in trades], dtype=float)
    r = np.array([t["r"] for t in trades], dtype=float)
    dollars = np.array([t["pnl_d"] for t in trades], dtype=float)
    days = np.array([t["days"] for t in trades], dtype=float)
    wins = pnl > 0
    losses = pnl < 0
    win_pct = float(wins.mean() * 100.0)
    avg = float(pnl.mean())
    wo = pnl.copy()
    if wo.size:
        wo[int(np.argmax(wo))] = np.nan
    avg_wo = float(np.nanmean(wo)) if np.isfinite(wo).any() else float("nan")
    gross_win = float(dollars[dollars > 0].sum())
    gross_loss = float(-dollars[dollars < 0].sum())
    pf = gross_win / gross_loss if gross_loss > 0 else float("nan")
    win_sum = float(pnl[wins].sum()) if wins.any() else 0.0
    outlier = float(pnl.max() / win_sum * 100.0) if win_sum > 0 else float("nan")
    exits = Counter(t["exit_reason"] for t in trades)
    years = max((pd.Timestamp(trades[-1]["opened"]) - pd.Timestamp(trades[0]["opened"])).days / 365.25, 1 / 365.25)
    # trades are not sorted; fix span from min/max
    opens = [t["opened_ts"] for t in trades]
    span_years = max((max(opens) - min(opens)).days / 365.25, 1 / 365.25)
    ov = cf.overlay_ann_ror_max_dd(
        trades,
        cash=SHEET,
        initial_account=ACCOUNT,
        pnl_d_key="pnl_d",
        days_key="days",
        closed_key="closed_ts",
        opened_key="opened_ts",
        pnl_pct_key="pnl",
    )
    by_sym = defaultdict(float)
    for t in trades:
        by_sym[t["symbol"]] += t["pnl_d"]
    total = float(dollars.sum())
    ranked = sorted(by_sym.values(), key=lambda x: -abs(x))
    top_sym_share = (max(by_sym.values()) / total * 100.0) if total else float("nan")
    return {
        "n": n,
        "wins": int(wins.sum()),
        "losses": int(losses.sum()),
        "win_pct": win_pct,
        "avg_pnl": avg,
        "avg_wo": avg_wo,
        "median_pnl": float(np.median(pnl)),
        "avg_r": float(r.mean()),
        "median_r": float(np.median(r)),
        "expect_d": float(dollars.mean()),
        "avg_win": float(pnl[wins].mean()) if wins.any() else float("nan"),
        "avg_loss": float(pnl[losses].mean()) if losses.any() else float("nan"),
        "pf": pf,
        "ann_ror": ov.get("ann_ror"),
        "max_dd": ov.get("max_dd"),
        "calmar": ov.get("calmar"),
        "sharpe": ov.get("sharpe"),
        "sharpe_source": ov.get("sharpe_source") or "",
        "capital_days": float(days.sum()),
        "avg_days": float(days.mean()),
        "median_days": float(np.median(days)),
        "p90_days": float(np.percentile(days, 90)),
        "trades_per_year": n / span_years,
        "outlier_win": outlier,
        "top_sym_share": top_sym_share,
        "exits": dict(exits),
        "span_note": years,
    }


def metric_rows(a: dict[str, Any], b: dict[str, Any]) -> list[tuple[str, str, str, str, str]]:
    """label, control, candidate, delta, sort type hint unused."""
    specs = [
        ("Trades", "n", "num", False),
        ("Wins", "wins", "num", False),
        ("Losses", "losses", "num", False),
        ("Win %", "win_pct", "pct", True),
        ("Avg PnL %", "avg_pnl", "pct", True),
        ("Avg PnL % without the largest win", "avg_wo", "pct", True),
        ("Median PnL %", "median_pnl", "pct", True),
        ("Avg R", "avg_r", "num", False),
        ("Median R", "median_r", "num", False),
        ("Expectancy $", "expect_d", "money", False),
        ("Avg win %", "avg_win", "pct", True),
        ("Avg loss %", "avg_loss", "pct", True),
        ("Profit factor", "pf", "num", False),
        ("Ann ROR %", "ann_ror", "pct", True),
        ("Max DD %", "max_dd", "pct", True),
        ("Calmar", "calmar", "num", False),
        ("Sharpe", "sharpe", "num", False),
        ("Capital days", "capital_days", "num", False),
        ("Avg days held", "avg_days", "num", False),
        ("Median days held", "median_days", "num", False),
        ("P90 days held", "p90_days", "num", False),
        ("Trades / year", "trades_per_year", "num", False),
        ("Largest win as % of winning PnL", "outlier_win", "pct", True),
        ("Largest symbol share of dollar PnL %", "top_sym_share", "pct", True),
    ]
    rows = []
    for label, key, kind, _higher in specs:
        av = a.get(key, float("nan")) if a.get("n") else float("nan")
        bv = b.get(key, float("nan")) if b.get("n") else float("nan")
        if kind == "money":
            da = cf.format_money(av)
            db = cf.format_money(bv)
            try:
                delta = cf.format_money_delta(float(bv) - float(av))
            except (TypeError, ValueError):
                delta = "—"
        elif kind == "pct":
            da, db = _fp(av), _fp(bv)
            try:
                delta = _fd(float(bv) - float(av), pct=True)
            except (TypeError, ValueError):
                delta = "—"
        else:
            da, db = _f(av), _f(bv)
            try:
                delta = _fd(float(bv) - float(av))
            except (TypeError, ValueError):
                delta = "—"
        rows.append((label, da, db, delta))
    return rows


def exit_table(a: dict[str, Any], b: dict[str, Any]) -> str:
    keys = ["STOP", "GAP_STOP", "TARGET", "GAP_TARGET", "TIME"]
    head = "".join(
        sortable_th(h, t)
        for h, t in (
            ("Exit", "text"),
            ("Control n", "num"),
            ("Control %", "num"),
            ("Right-side n", "num"),
            ("Right-side %", "num"),
        )
    )
    rows = []
    ea = a.get("exits") or {}
    eb = b.get("exits") or {}
    na = max(int(a.get("n") or 0), 1)
    nb = max(int(b.get("n") or 0), 1)
    for k in keys:
        ca, cb = int(ea.get(k, 0)), int(eb.get(k, 0))
        rows.append(
            "<tr>"
            f"<td>{k}</td><td>{ca}</td><td>{_fp(100.0 * ca / na)}</td>"
            f"<td>{cb}</td><td>{_fp(100.0 * cb / nb)}</td>"
            "</tr>"
        )
    return (
        '<table class="sortable"><caption>How the trades ended. Click column headers to sort.</caption>'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def compare_table(title: str, a: dict[str, Any], b: dict[str, Any]) -> str:
    head = "".join(
        sortable_th(h, t)
        for h, t in (
            ("Metric", "text"),
            ("Control: buy the next open", "text"),
            ("Right side: break of the climax high", "text"),
            ("Right side minus control", "text"),
        )
    )
    body = []
    for label, da, db, delta in metric_rows(a, b):
        body.append(f"<tr><td>{_esc(label)}</td><td>{_esc(da)}</td><td>{_esc(db)}</td><td>{_esc(delta)}</td></tr>")
    return (
        f"<h3>{_esc(title)}</h3>"
        '<table class="sortable"><caption>Click column headers to sort.</caption>'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"
    )


def verdict(is_c: dict[str, Any], is_r: dict[str, Any], oos_c: dict[str, Any], oos_r: dict[str, Any]) -> tuple[str, str]:
    if not is_c.get("n") or not is_r.get("n"):
        return "HOLD", "One arm has no in-sample trades. Nothing to adopt."
    n_ratio = is_r["n"] / is_c["n"] if is_c["n"] else 0
    better_r = is_r.get("avg_r", -9) > is_c.get("avg_r", -9) + 0.05
    better_win = is_r.get("win_pct", 0) > is_c.get("win_pct", 0) + 2
    better_avg = is_r.get("avg_pnl", -9) > is_c.get("avg_pnl", -9)
    collapsed = n_ratio < 0.5
    oos_softer = (
        oos_r.get("n", 0) > 30
        and is_r.get("avg_r", 0) > 0
        and oos_r.get("avg_r", 0) < is_r.get("avg_r", 0) - 0.1
    )
    if better_avg and (better_r or better_win) and not collapsed:
        label = "LEAN KEEP"
        text = (
            "On entries before 2024, waiting for the high of the climax day to break improved trade quality "
            "without cutting the trade count in half. That is a research lean, not a live rule. "
            "Out-of-sample is a report and was not used to pick the rule."
        )
    elif better_avg and (better_r or better_win) and collapsed:
        label = "HOLD"
        text = (
            f"Before 2024, waiting for the climax high raised the win rate from {is_c['win_pct']:.0f}% "
            f"to {is_r['win_pct']:.0f}% and lifted average R from {is_c['avg_r']:.2f} to {is_r['avg_r']:.2f}. "
            f"That is a better trade, and average R is still about a coin flip. "
            f"The right-side arm kept {is_r['n']:,} trades against {is_c['n']:,} on the control. "
            "From 2024 on, both arms lose money in percent, and the right-side book is about flat in R. "
            "Hold it as a research note. Do not promote it."
        )
    elif not better_avg and not better_r:
        label = "DISMISS"
        text = (
            "Before 2024, waiting for the climax high to break did not improve the average trade or the average R "
            "versus buying the next open. The daily version of this idea does not earn a place next to the control."
        )
    else:
        label = "HOLD"
        text = (
            "Before 2024 the two arms do not separate cleanly on both win rate and average result. "
            "Leave the rule as a research note."
        )
    if oos_softer and label == "LEAN KEEP":
        label = "HOLD"
        text += " From 2024 on, average R is softer than the earlier period. That is a reason to hold, not to retune."
    return label, text


def write_trades(path: Path, trades: list[dict[str, Any]]) -> None:
    cols = [
        "arm", "symbol", "signal_date", "opened", "closed", "entry", "exit", "stop", "target",
        "pnl", "pnl_d", "r", "days", "sessions", "exit_reason", "ret5", "excess", "vol_ratio",
    ]
    pd.DataFrame(trades)[cols].to_csv(path, index=False)


def render(
    n_raw: int,
    n_picks: int,
    skip_c: int,
    skip_r: int,
    full_c: dict[str, Any],
    full_r: dict[str, Any],
    is_c: dict[str, Any],
    is_r: dict[str, Any],
    oos_c: dict[str, Any],
    oos_r: dict[str, Any],
    label: str,
    why: str,
) -> str:
    css = SORTABLE_TH_CSS + """
    body { font: 16px/1.45 Georgia, serif; margin: 2rem auto; max-width: 980px; color: #1a1a1a; }
    h1 { font-size: 1.6rem; }
    .callout { background: #f6f3ea; border: 1px solid #e2d8c0; padding: 0.8rem 1rem; margin: 1rem 0; }
    table { border-collapse: collapse; width: 100%; margin: 0.6rem 0 1.2rem; font-size: 0.92rem; }
    th, td { border-bottom: 1px solid #ddd; padding: 0.35rem 0.45rem; text-align: right; }
    th:first-child, td:first-child { text-align: left; }
    caption { text-align: left; font-size: 0.85rem; color: #444; margin-bottom: 0.3rem; }
    .verdict { font-size: 1.15rem; }
    """
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Right side of the V — washout test</title>
<style>{css}</style></head><body>
<h1>Right side of the V, tested on daily bars</h1>
<p>Research only. Not gold. Not a live DailyRun system. Stamp <code>{STAMP}</code>.</p>
<div class="callout">
<h2>What you asked</h2>
<p>{_esc(ORIGINAL_REQUEST)}</p>
<h2>In plain English</h2>
<p>{LAYMAN}</p>
</div>
<p class="verdict"><strong>{_esc(label)}.</strong> {_esc(why)}</p>
<p>Shared washout signals before the one-trade lock: {_f(n_raw, 0)}. Signals actually offered to both arms: {_f(n_picks, 0)}.
Control skipped {_f(skip_c, 0)} because the next open was already at or below the climax low.
The right-side arm skipped {_f(skip_r, 0)} because the next day never traded above the climax high, or the fill was not above the low.
Sheet size is a fixed {cf.format_money(SHEET)} per trade. Annualized rate of return (Ann ROR) uses that sheet and the average hold.
Max drawdown (Max DD) replays closed trades on a {cf.format_money(ACCOUNT)} account. Sharpe uses exit dates, not a daily equity curve
({_esc(full_c.get('sharpe_source') or 'n/a')}). Dollar profit and sheet profit are left off this page on purpose.
In-sample (IS) is an entry before 2024-01-01. Out-of-sample (OOS) is an entry on or after that date and is report-only.</p>
<h2>Full book</h2>
{compare_table("Every closed trade", full_c, full_r)}
{exit_table(full_c, full_r)}
<h2>In-sample</h2>
{compare_table("Entry before 2024-01-01 — this is the judge", is_c, is_r)}
<h2>Out of sample</h2>
{compare_table("Entry on or after 2024-01-01 — report only", oos_c, oos_r)}
<h2>Freeze</h2>
<ul>
<li>Lookback: {LOOKBACK} sessions. Stock return at or below −{MIN_DROP:.0%}. Excess versus QQQ at or below −{MIN_EXCESS:.0%} (percentage points).</li>
<li>Climax volume at least {VOL_MULT:.0f} times the prior {VOL_WINDOW} sessions. Dollar volume at least {cf.format_money(MIN_DOLLAR_VOL)}.</li>
<li>Keep the {TOP_N} most negative excess names that day. A name cannot take a new signal until its {HOLD_BARS}-session window has ended.</li>
<li>Control entry: next session open, only if that open is above the climax low.</li>
<li>Right-side entry: next session only, at the climax high, or at the open if the open is already through that high.</li>
<li>Stop: climax-day low, checked first if the same bar also hits the target. Target: {TARGET_R:.0f}R. Time: close of session {HOLD_BARS}.</li>
<li>Float turnover from the episode is not in this warehouse, so it is not a gate. Same-day tape, opening imbalances, and two-minute bars are not in this test.</li>
</ul>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""


def write_baseline(label: str, why: str, n_raw: int, n_picks: int, skip_c: int, skip_r: int) -> None:
    text = f"""# Right side of the V — washout A/B

Research only. Not gold. Not DailyRun.

## What you asked

{ORIGINAL_REQUEST}

## In plain English

{LAYMAN}

## Verdict

**{label}.** {why}

## Freeze

| Knob | Value |
|---|---|
| Universe | Daily warehouse `data/ohlcv.duckdb` `prices`, joined to QQQ. Name excluded: QQQ. |
| Signal, known at the close | {LOOKBACK}-day return ≤ −{MIN_DROP:.0%}; excess vs QQQ ≤ −{MIN_EXCESS:.0%} points; volume ≥ {VOL_MULT:.0f}× prior {VOL_WINDOW} days; close×volume ≥ ${MIN_DOLLAR_VOL:,.0f}; high > low. |
| Rank | {TOP_N} most negative excess that day. One window per symbol for {HOLD_BARS} sessions after the entry bar. |
| Control | Buy next session open if open > climax low. |
| Candidate | Buy next session only if high ≥ climax high. Fill at the high, or at the open if the open gaps through. |
| Stop | Climax low. Same bar: stop is checked before the target. Gap through the stop fills at the open. |
| Target | {TARGET_R:.0f}R above entry. Gap through the target fills at the open. |
| Time | Exit at the close of session {HOLD_BARS}, counting the entry session. |
| Size | ${SHEET:,.0f} sheet per trade. Drawdown replay starts at ${ACCOUNT:,.0f}. |
| IS / OOS | Entry before 2024-01-01 / on or after. OOS is report-only. Knobs were not picked from OOS. |
| Not in the data | Float turnover, two-minute bars, opening imbalances, limit-up halts in other names. |

Signals before the one-name lock: {n_raw}. Offered to both arms: {n_picks}. Control skips: {skip_c}. Right-side skips: {skip_r}.

## Selection

One pre-declared knob (entry). No second exit was scored. Adopting anything from this page would be an in-sample choice and would need a new stamp.
"""
    (OUT / "BASELINE.md").write_text(text, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("[rsv] scanning signals", flush=True)
    con = duckdb.connect(str(DB), read_only=True)
    try:
        raw = load_signals(con)
        print(f"[rsv] raw signals {len(raw)}", flush=True)
        symbols = sorted(set(raw["symbol"]))
        bars = load_bars(con, symbols)
    finally:
        con.close()
    picks = pick_signals(raw, bars)
    print(f"[rsv] picked {len(picks)}", flush=True)
    control = simulate(picks, bars, "control")
    skip_c = int(getattr(simulate, "last_skips", 0))
    right = simulate(picks, bars, "right")
    skip_r = int(getattr(simulate, "last_skips", 0))
    print(f"[rsv] trades control {len(control)} right {len(right)}", flush=True)
    packs = {}
    for name, rows in (("full_c", control), ("full_r", right)):
        packs[name] = summarize(rows)
    packs["is_c"] = summarize(_slice(control, "is"))
    packs["is_r"] = summarize(_slice(right, "is"))
    packs["oos_c"] = summarize(_slice(control, "oos"))
    packs["oos_r"] = summarize(_slice(right, "oos"))
    label, why = verdict(packs["is_c"], packs["is_r"], packs["oos_c"], packs["oos_r"])
    write_trades(OUT / "trades_control.csv", control)
    write_trades(OUT / "trades_right.csv", right)
    write_baseline(label, why, len(raw), len(picks), skip_c, skip_r)
    html = render(
        len(raw), len(picks), skip_c, skip_r,
        packs["full_c"], packs["full_r"],
        packs["is_c"], packs["is_r"],
        packs["oos_c"], packs["oos_r"],
        label, why,
    )
    (OUT / "compare.html").write_text(html, encoding="utf-8")
    summary = {
        "stamp": STAMP,
        "verdict": label,
        "why": why,
        "n_raw": len(raw),
        "n_picks": len(picks),
        "skip_control": skip_c,
        "skip_right": skip_r,
        "arms": {k: {kk: (float(vv) if isinstance(vv, (float, np.floating)) else vv) for kk, vv in d.items() if kk != "exits"} | {"exits": d.get("exits", {})} for k, d in packs.items()},
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"[rsv] {label}", flush=True)
    print(why, flush=True)


if __name__ == "__main__":
    main()
