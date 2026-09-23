#!/usr/bin/env python3
"""Top-50 (ever) 42% pullback from yearly high → exit on new yearly high.

Research trade ledger. Not DailyRun. Not gold.

Universe = same family as ``top50_ath_drawdown_20260916`` (ever annual top-50
approx market cap on S&P 500 ∩ DuckDB). Reference high = **252-trading-day
rolling Close max** (52-week / yearly high on closes) — **not** sample ATH.

Usage:
    python tools/top50_yhigh42_newhigh_20260921.py
"""
from __future__ import annotations

import html as html_mod
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))

import compare_format as cf  # noqa: E402
import run_spx_diversification as spx  # noqa: E402
import top50_ath_drawdown_20260916 as ath  # noqa: E402

STAMP_ID = "top50_yhigh42_newhigh_20260921"
STAMP_DIR = REPO / "drive" / "paul_experiments" / STAMP_ID
REPORT_HTML = STAMP_DIR / "report.html"
COMPARE_HTML = STAMP_DIR / "compare.html"

LOOKBACK_TD = 252  # ~52 trading weeks / "yearly" high on closes
DROP_PCT = 42.0
DROP_FRAC = DROP_PCT / 100.0  # buy when close ≤ (1 - 0.42) × yearly_high
ENTRY_MULT = 1.0 - DROP_FRAC  # 0.58
SHEET_CASH = 10_000.0
INITIAL_ACCOUNT = 500_000.0
IS_CUT = pd.Timestamp("2024-01-01")

ORIGINAL_REQUEST = (
    "what if i bought every top-50 market cap stock when it pulled bavk 42% off "
    "its yearly high and sold when it hit a new one?"
)
LAYMAN = (
    "We took every stock that showed up at least once in the annual list of the 50 "
    "largest Standard & Poor's 500 (S&P 500) names (size approximated the same way "
    "as the other top-50 stamps). This is not the older all-time high (ATH) "
    "pullback study — here “yearly high” means the highest closing price over the "
    "prior 252 trading days (about one year). Paper-trade rule: buy at the close "
    "on the first day the close is down 42% or more from that then-current yearly "
    "high (close ≤ 58% of the 252-day high). Hold one position per stock. Sell at "
    "the close on the first later day that close makes a brand-new 252-day high. "
    "If still holding at the end of the chart, we mark the trade to the last close "
    "and label it open. In-sample (IS) = entries before 2024; 2024+ is "
    "out-of-sample (OOS) and report-only. Research only — not DailyRun."
)


def _esc(x: Any) -> str:
    return html_mod.escape("" if x is None else str(x))


def _mean(vals: Any) -> float | None:
    arr = np.asarray(list(vals), dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return None
    return float(np.mean(arr))


def _median(vals: Any) -> float | None:
    arr = np.asarray(list(vals), dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return None
    return float(np.median(arr))


def _pctl(vals: Any, q: float) -> float | None:
    arr = np.asarray(list(vals), dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return None
    return float(np.percentile(arr, q))


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


def _th(label: str, sort_type: str) -> str:
    return spx._sortable_th(label, sort_type)


def _rate(num: int, den: int) -> float | None:
    if den <= 0:
        return None
    return 100.0 * float(num) / float(den)


def _prep_ohlc(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    df = frame.dropna(subset=["Close"]).copy()
    close = df["Close"].to_numpy(dtype=float)
    ok = np.isfinite(close) & (close > 0)
    df = df.loc[ok]
    dates = pd.to_datetime(df["Date"]).to_numpy()
    close = df["Close"].to_numpy(dtype=float)
    return dates, close


def _rolling_yhigh(close: np.ndarray, window: int = LOOKBACK_TD) -> np.ndarray:
    """252-td rolling max of Close, inclusive of today. NaN until warmup complete."""
    s = pd.Series(np.asarray(close, dtype=float))
    return s.rolling(window, min_periods=window).max().to_numpy(dtype=float)


def _is_new_yhigh(close: np.ndarray, i: int, window: int = LOOKBACK_TD) -> bool:
    """True if close[i] strictly exceeds max of prior (window-1) closes in the lookback."""
    if i < window - 1:
        return False
    prior = close[i - window + 1 : i]
    if prior.size == 0:
        return False
    px = float(close[i])
    return np.isfinite(px) and px > float(np.max(prior))


def _trades_for_symbol(
    symbol: str,
    frame: pd.DataFrame,
    *,
    years_top50: list[int],
) -> list[dict[str, Any]]:
    """One position at a time: buy first close ≤ 58% of 252d close-high; sell on new 252d close-high."""
    dates, close = _prep_ohlc(frame)
    n = len(close)
    if n < LOOKBACK_TD + 1:
        return []

    yhigh = _rolling_yhigh(close, LOOKBACK_TD)
    years = ",".join(str(y) for y in years_top50)
    n_years = len(years_top50)
    first_y = years_top50[0] if years_top50 else None
    last_y = years_top50[-1] if years_top50 else None
    ohlc_start = str(pd.Timestamp(dates[0]).date())
    ohlc_end = str(pd.Timestamp(dates[-1]).date())

    trades: list[dict[str, Any]] = []
    in_pos = False
    entry_i = -1
    entry_px = 0.0
    entry_yhigh = 0.0
    trade_seq = 0

    for i in range(LOOKBACK_TD - 1, n):
        yh = float(yhigh[i])
        px = float(close[i])
        if not np.isfinite(yh) or yh <= 0 or not np.isfinite(px) or px <= 0:
            continue

        if not in_pos:
            # Entry: first day close ≤ ENTRY_MULT × then-current yearly high
            if px <= yh * ENTRY_MULT:
                in_pos = True
                entry_i = i
                entry_px = px
                entry_yhigh = yh
                trade_seq += 1
            continue

        # In position: exit on first *later* day that prints a new 252d close high.
        # Same-bar entry day cannot exit (need j > entry_i).
        if i <= entry_i:
            continue
        if _is_new_yhigh(close, i, LOOKBACK_TD):
            t_en = pd.Timestamp(dates[entry_i])
            t_ex = pd.Timestamp(dates[i])
            pnl_pct = (px / entry_px - 1.0) * 100.0
            trades.append(
                {
                    "symbol": symbol,
                    "trade_seq": trade_seq,
                    "entry_date": t_en,
                    "exit_date": t_ex,
                    "entry": entry_px,
                    "exit": px,
                    "entry_yhigh": entry_yhigh,
                    "entry_drop_pct": (1.0 - entry_px / entry_yhigh) * 100.0 if entry_yhigh > 0 else None,
                    "exit_yhigh": float(yhigh[i]) if np.isfinite(yhigh[i]) else px,
                    "pnl_pct": pnl_pct,
                    "pnl_d": SHEET_CASH * pnl_pct / 100.0,
                    "cal_days_held": int((t_ex - t_en).days),
                    "td_days_held": int(i - entry_i),
                    "exit_type": "TARGET",
                    "closed": 1,
                    "is_oos": int(t_en >= IS_CUT),
                    "years_in_top50": years,
                    "n_years_top50": n_years,
                    "first_top50_year": first_y,
                    "last_top50_year": last_y,
                    "ohlc_start": ohlc_start,
                    "ohlc_end": ohlc_end,
                }
            )
            in_pos = False
            entry_i = -1

    if in_pos and entry_i >= 0:
        t_en = pd.Timestamp(dates[entry_i])
        t_ex = pd.Timestamp(dates[-1])
        px = float(close[-1])
        pnl_pct = (px / entry_px - 1.0) * 100.0
        trades.append(
            {
                "symbol": symbol,
                "trade_seq": trade_seq,
                "entry_date": t_en,
                "exit_date": t_ex,
                "entry": entry_px,
                "exit": px,
                "entry_yhigh": entry_yhigh,
                "entry_drop_pct": (1.0 - entry_px / entry_yhigh) * 100.0 if entry_yhigh > 0 else None,
                "exit_yhigh": float(yhigh[-1]) if np.isfinite(yhigh[-1]) else px,
                "pnl_pct": pnl_pct,
                "pnl_d": SHEET_CASH * pnl_pct / 100.0,
                "cal_days_held": int((t_ex - t_en).days),
                "td_days_held": int(n - 1 - entry_i),
                "exit_type": "OPEN",
                "closed": 0,
                "is_oos": int(t_en >= IS_CUT),
                "years_in_top50": years,
                "n_years_top50": n_years,
                "first_top50_year": first_y,
                "last_top50_year": last_y,
                "ohlc_start": ohlc_start,
                "ohlc_end": ohlc_end,
            }
        )
    return trades


def _book_metrics(trades: list[dict[str, Any]] | pd.DataFrame, *, label: str, note: str) -> dict[str, Any]:
    if isinstance(trades, pd.DataFrame):
        rows = trades.to_dict("records")
    else:
        rows = list(trades)
    n = len(rows)
    empty = {
        "arm": label,
        "note": note,
        "n_trades": 0,
        "n_wins": 0,
        "n_losses": 0,
        "win_pct": None,
        "avg_pnl_pct": None,
        "median_pnl_pct": None,
        "avg_pnl_pct_wo_max": None,
        "expectancy_pct": None,
        "expectancy_d": None,
        "avg_win_pct": None,
        "avg_loss_pct": None,
        "win_loss_count_ratio": None,
        "profit_factor": None,
        "ann_ror": None,
        "max_dd": None,
        "calmar": None,
        "sharpe": None,
        "sharpe_source": "",
        "profit_per_capital_day": None,
        "capital_days": 0.0,
        "avg_days_held": None,
        "median_days_held": None,
        "p90_days_held": None,
        "avg_td_days_held": None,
        "median_td_days_held": None,
        "n_target": 0,
        "n_open": 0,
        "pct_target": None,
        "pct_open": None,
        "overlay_note": "no trades",
    }
    if n <= 0:
        return empty
    pnls = [float(t["pnl_pct"]) for t in rows]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    days = [float(t["cal_days_held"]) for t in rows]
    td_days = [float(t["td_days_held"]) for t in rows]
    dollars = [float(t["pnl_d"]) for t in rows]
    n_w, n_l = len(wins), len(losses)
    wo = None
    if len(pnls) >= 2:
        i_max = int(np.argmax(pnls))
        rest = [p for i, p in enumerate(pnls) if i != i_max]
        wo = float(np.mean(rest)) if rest else None
    elif pnls:
        wo = float(pnls[0])
    sum_w = float(sum(wins)) if wins else 0.0
    sum_l = float(sum(losses)) if losses else 0.0
    pf = (sum_w / abs(sum_l)) if abs(sum_l) > 1e-12 else None
    cap_days = float(sum(max(d, 0.0) for d in days))
    total_d = float(sum(dollars))
    exits = [str(t.get("exit_type") or "") for t in rows]
    n_target = exits.count("TARGET")
    n_open = exits.count("OPEN")
    dated = []
    for t in rows:
        td = t.get("exit_date")
        if td is None or pd.isna(td):
            continue
        dated.append(
            {
                "pnl_d": t["pnl_d"],
                "pnl_pct": t["pnl_pct"],
                "days": t["cal_days_held"],
                "closed": pd.Timestamp(td),
                "opened": pd.Timestamp(t["entry_date"]),
            }
        )
    ov = cf.overlay_ann_ror_max_dd(
        dated,
        cash=SHEET_CASH,
        initial_account=INITIAL_ACCOUNT,
        pnl_d_key="pnl_d",
        days_key="days",
        closed_key="closed",
        opened_key="opened",
        pnl_pct_key="pnl_pct",
    )
    return {
        "arm": label,
        "note": note,
        "n_trades": n,
        "n_wins": n_w,
        "n_losses": n_l,
        "win_pct": _rate(n_w, n),
        "avg_pnl_pct": _mean(pnls),
        "median_pnl_pct": _median(pnls),
        "avg_pnl_pct_wo_max": wo,
        "expectancy_pct": _mean(pnls),
        "expectancy_d": _mean(dollars),
        "avg_win_pct": _mean(wins),
        "avg_loss_pct": _mean(losses),
        "win_loss_count_ratio": (float(n_w) / float(n_l)) if n_l else None,
        "profit_factor": pf,
        "ann_ror": ov.get("ann_ror"),
        "max_dd": ov.get("max_dd"),
        "calmar": ov.get("calmar"),
        "sharpe": ov.get("sharpe"),
        "sharpe_source": ov.get("sharpe_source") or "",
        "profit_per_capital_day": (total_d / cap_days) if cap_days > 0 else None,
        "capital_days": cap_days,
        "avg_days_held": _mean(days),
        "median_days_held": _median(days),
        "p90_days_held": _pctl(days, 90),
        "avg_td_days_held": _mean(td_days),
        "median_td_days_held": _median(td_days),
        "n_target": n_target,
        "n_open": n_open,
        "pct_target": _rate(n_target, n),
        "pct_open": _rate(n_open, n),
        "overlay_note": ov.get("note") or "",
    }


def _stock_summary(trades: pd.DataFrame, years_by_sym: dict[str, list[int]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if trades.empty:
        return pd.DataFrame(rows)
    for sym, g in trades.groupby("symbol", sort=True):
        pnls = g["pnl_pct"].astype(float)
        closed = g[g["exit_type"] == "TARGET"]
        years = years_by_sym.get(str(sym), [])
        rows.append(
            {
                "symbol": sym,
                "n_trades": int(len(g)),
                "n_closed": int(len(closed)),
                "n_open": int((g["exit_type"] == "OPEN").sum()),
                "win_pct": _rate(int((pnls > 0).sum()), int(len(g))),
                "avg_pnl_pct": _mean(pnls),
                "median_pnl_pct": _median(pnls),
                "avg_days_held": _mean(g["cal_days_held"]),
                "median_days_held": _median(g["cal_days_held"]),
                "avg_entry_drop_pct": _mean(g["entry_drop_pct"]),
                "n_years_top50": len(years),
                "first_top50_year": years[0] if years else None,
                "last_top50_year": years[-1] if years else None,
            }
        )
    return pd.DataFrame(rows)


def _table(df: pd.DataFrame, cols: list[tuple[str, str, str]]) -> str:
    if df is None or df.empty:
        return '<p class="small muted">None.</p>'
    head = "".join(_th(lab, typ) for lab, typ, _ in cols)
    body = []
    money_keys = {"expectancy_d", "profit_per_capital_day"}
    pct_keys = {
        "win_pct",
        "avg_pnl_pct",
        "median_pnl_pct",
        "avg_pnl_pct_wo_max",
        "expectancy_pct",
        "avg_win_pct",
        "avg_loss_pct",
        "ann_ror",
        "max_dd",
        "pct_target",
        "pct_open",
        "avg_entry_drop_pct",
    }
    ratio_keys = {"calmar", "sharpe", "profit_factor", "win_loss_count_ratio"}
    int_keys = {
        "n_trades",
        "n_wins",
        "n_losses",
        "n_target",
        "n_open",
        "n_closed",
        "n_years_top50",
        "first_top50_year",
        "last_top50_year",
        "trade_seq",
    }
    for _, r in df.iterrows():
        tds = []
        for _lab, typ, key in cols:
            v = r.get(key)
            if typ == "num" and key in money_keys:
                tds.append(f"<td>{cf.format_money(v)}</td>")
            elif typ == "num" and key in pct_keys:
                tds.append(f"<td>{_fmt_pct(v)}</td>")
            elif typ == "num" and key in ratio_keys:
                tds.append(f"<td>{_fmt_num(v, 2)}</td>")
            elif typ == "num" and key in int_keys:
                tds.append(f"<td>{_fmt_int(v)}</td>")
            elif typ == "num":
                tds.append(f"<td>{_fmt_num(v, 1 if 'days' in key or key == 'capital_days' else 2)}</td>")
            else:
                tds.append(f"<td>{_esc(v)}</td>")
        cls = ' class="total-row"' if str(r.get("arm") or r.get("symbol") or "").startswith("FULL") or str(
            r.get("symbol") or ""
        ).startswith("OVERALL") else ""
        if str(r.get("arm") or "") in ("strategy_FULL", "strategy_IS", "strategy_OOS", "strategy_CLOSED"):
            cls = ""
        if str(r.get("symbol") or "") == "OVERALL (trade-equal)":
            cls = ' class="total-row"'
        body.append(f"<tr{cls}>" + "".join(tds) + "</tr>")
    return (
        '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def _write_baseline(
    path: Path,
    *,
    books: pd.DataFrame,
    ohlc_start: str,
    ohlc_end: str,
    n_names: int,
    n_trades: int,
    membership_years: list[int],
) -> None:
    def _row(arm: str) -> dict[str, Any]:
        sub = books[books["arm"] == arm]
        return sub.iloc[0].to_dict() if len(sub) else {}

    full = _row("strategy_FULL")
    closed = _row("strategy_CLOSED")
    is_r = _row("strategy_IS")
    oos_r = _row("strategy_OOS")
    path.write_text(
        f"""# BASELINE — {STAMP_ID}

**Status:** Research trade ledger. **Not gold. Not DailyRun.** No adopt.

## What you asked

> {ORIGINAL_REQUEST}

## In plain English

{LAYMAN}

## Freeze (do not silently mutate)

- **Universe:** same family as `top50_ath_drawdown_20260916` — names ever in the annual approx-mcap top 50 on today's Wikipedia Standard & Poor's 500 (S&P 500) ∩ local DuckDB, membership years from {min(membership_years) if membership_years else "?"} onward (helpers reused; survivorship + scaled-now mcaps inherited).
- **NOT sample ATH:** prior stamps use local all-time closing high since ~2010. This stamp uses **yearly / 52-week high** only.
- **Yearly high:** rolling max of **Close** over **{LOOKBACK_TD} trading days** ending today (inclusive). Labeled `yhigh_basis=Close_252td`. Daily High is not used for the reference high.
- **Entry:** first day (after warmup) where `Close ≤ {ENTRY_MULT:.2f} × yearly_high` (i.e. ≥{DROP_PCT:.0f}% off the then-current 252d close-high). Fill = **Close** that day. One position per symbol (no pyramiding). Re-arm after exit.
- **Exit:** first day **after** entry where Close makes a **new** 252d high (`Close > max(prior {LOOKBACK_TD - 1} closes in window)`). Fill = **Close**. Exit type `TARGET`.
- **Open at sample end:** still-held positions marked to last Close; exit type `OPEN` (included in FULL book; CLOSED arm excludes them).
- **Costs / slippage:** 0 (research).
- **Sheet notional:** ${SHEET_CASH:,.0f}/trade; Max DD / Sharpe seed ${INITIAL_ACCOUNT:,.0f} via `compare_format.overlay_ann_ror_max_dd`.
- **OHLC window:** {ohlc_start} → {ohlc_end}.
- **IS / OOS:** IS = `entry_date < 2024-01-01`; OOS = `entry_date ≥ 2024-01-01` (**report-only; do not retune 42% or exit on OOS**).
- **Single frozen hypothesis:** {DROP_PCT:.0f}% pullback + new yearly-high exit. Not a sweep.

## Counts

- Ever top-50 names scored: **{n_names}**
- Trades (FULL, incl. OPEN MTM): **{n_trades}**

## Headline (equal-weight trades)

- FULL (incl. OPEN): N={full.get("n_trades")} WR={full.get("win_pct")} AvgPnL%={full.get("avg_pnl_pct")} MedHoldCal={full.get("median_days_held")} AnnROR={full.get("ann_ror")} MaxDD={full.get("max_dd")}
- CLOSED only (TARGET): N={closed.get("n_trades")} WR={closed.get("win_pct")} AvgPnL%={closed.get("avg_pnl_pct")} MedHoldCal={closed.get("median_days_held")}
- IS: N={is_r.get("n_trades")} WR={is_r.get("win_pct")} AvgPnL%={is_r.get("avg_pnl_pct")} AnnROR={is_r.get("ann_ror")} MaxDD={is_r.get("max_dd")}
- OOS (report-only): N={oos_r.get("n_trades")} WR={oos_r.get("win_pct")} AvgPnL%={oos_r.get("avg_pnl_pct")} AnnROR={oos_r.get("ann_ror")} MaxDD={oos_r.get("max_dd")}

## Honesty / selection

- Single pre-declared 42% + new-yearly-high recipe — not chosen after a grid.
- OOS softens → HOLD / investigate; **do not retune** the 42% or exit on 2024+.
- Survivorship (today's Wikipedia ∩ local panel); approx mcap from latest Yahoo scaled by close; dividends ignored; close fills optimistic vs intraday.
- Yearly-high ≠ sample ATH — do not compare raw stats to `top50_ath_*` without that label.
- OPEN MTM trades can drag FULL quality; judge CLOSED and IS/OOS separately.

## Verdict

**Research only.** Frozen what-if ledger. **Not KEEP. Not DailyRun.**
""",
        encoding="utf-8",
    )


def _write_html(
    path: Path,
    *,
    books: pd.DataFrame,
    stocks: pd.DataFrame,
    trades: pd.DataFrame,
    ohlc_start: str,
    ohlc_end: str,
    n_names: int,
) -> None:
    full = books[books["arm"] == "strategy_FULL"]
    full_r = full.iloc[0].to_dict() if len(full) else {}
    cards = [
        ("N trades (FULL)", _fmt_int(full_r.get("n_trades")), f"{_fmt_int(n_names)} ever top-50 names · incl. OPEN MTM"),
        ("Win %", _fmt_pct(full_r.get("win_pct")), f"Closed TARGET {_fmt_int(full_r.get('n_target'))} · OPEN {_fmt_int(full_r.get('n_open'))}"),
        ("Avg / med PnL %", f"{_fmt_pct(full_r.get('avg_pnl_pct'))} / {_fmt_pct(full_r.get('median_pnl_pct'))}", f"AVG_PNL_PCT_WO_MAX {_fmt_pct(full_r.get('avg_pnl_pct_wo_max'))}"),
        ("Med / avg hold (cal d)", f"{_fmt_num(full_r.get('median_days_held'), 1)} / {_fmt_num(full_r.get('avg_days_held'), 1)}", f"Med trading days {_fmt_num(full_r.get('median_td_days_held'), 1)}"),
        ("Ann ROR % / Max DD %", f"{_fmt_pct(full_r.get('ann_ror'))} / {_fmt_pct(full_r.get('max_dd'))}", f"Calmar {_fmt_num(full_r.get('calmar'), 2)} · Sharpe {_fmt_num(full_r.get('sharpe'), 2)}"),
        ("Profit factor", _fmt_num(full_r.get("profit_factor"), 2), f"Expectancy {_fmt_pct(full_r.get('expectancy_pct'))} · {cf.format_money(full_r.get('expectancy_d'))}/trade"),
    ]
    card_html = "".join(
        f'<div class="card"><h3>{_esc(t)}</h3><div class="metric">{m}</div><div class="small">{_esc(n)}</div></div>'
        for t, m, n in cards
    )

    book_cols = [
        ("Arm", "text", "arm"),
        ("N trades", "num", "n_trades"),
        ("Wins", "num", "n_wins"),
        ("Losses", "num", "n_losses"),
        ("Win %", "num", "win_pct"),
        ("Avg PnL %", "num", "avg_pnl_pct"),
        ("Med PnL %", "num", "median_pnl_pct"),
        ("AVG_PNL_PCT_WO_MAX", "num", "avg_pnl_pct_wo_max"),
        ("Expectancy %", "num", "expectancy_pct"),
        ("Expectancy $", "num", "expectancy_d"),
        ("Avg win %", "num", "avg_win_pct"),
        ("Avg loss %", "num", "avg_loss_pct"),
        ("W/L count", "num", "win_loss_count_ratio"),
        ("Profit factor", "num", "profit_factor"),
        ("Ann ROR %", "num", "ann_ror"),
        ("Max DD %", "num", "max_dd"),
        ("Calmar", "num", "calmar"),
        ("Sharpe", "num", "sharpe"),
        ("Profit / capital day", "num", "profit_per_capital_day"),
        ("Capital days", "num", "capital_days"),
        ("Avg days held", "num", "avg_days_held"),
        ("Med days held", "num", "median_days_held"),
        ("P90 days held", "num", "p90_days_held"),
        ("Med TD held", "num", "median_td_days_held"),
        ("N TARGET", "num", "n_target"),
        ("% TARGET", "num", "pct_target"),
        ("N OPEN", "num", "n_open"),
        ("% OPEN", "num", "pct_open"),
        ("Note", "text", "note"),
    ]
    stock_cols = [
        ("Symbol", "text", "symbol"),
        ("N trades", "num", "n_trades"),
        ("N closed", "num", "n_closed"),
        ("N open", "num", "n_open"),
        ("Win %", "num", "win_pct"),
        ("Avg PnL %", "num", "avg_pnl_pct"),
        ("Med PnL %", "num", "median_pnl_pct"),
        ("Avg days held", "num", "avg_days_held"),
        ("Med days held", "num", "median_days_held"),
        ("Avg entry drop %", "num", "avg_entry_drop_pct"),
        ("Years in top 50", "num", "n_years_top50"),
        ("First top-50 year", "num", "first_top50_year"),
        ("Last top-50 year", "num", "last_top50_year"),
    ]

    overall_stock = {
        "symbol": "OVERALL (trade-equal)",
        "n_trades": full_r.get("n_trades"),
        "n_closed": full_r.get("n_target"),
        "n_open": full_r.get("n_open"),
        "win_pct": full_r.get("win_pct"),
        "avg_pnl_pct": full_r.get("avg_pnl_pct"),
        "median_pnl_pct": full_r.get("median_pnl_pct"),
        "avg_days_held": full_r.get("avg_days_held"),
        "median_days_held": full_r.get("median_days_held"),
        "avg_entry_drop_pct": _mean(trades["entry_drop_pct"]) if len(trades) else None,
        "n_years_top50": None,
        "first_top50_year": None,
        "last_top50_year": None,
    }
    stocks_show = pd.concat([pd.DataFrame([overall_stock]), stocks.sort_values("symbol")], ignore_index=True)

    tr_head = "".join(
        [
            _th("Symbol", "text"),
            _th("Seq", "num"),
            _th("Entry date", "date"),
            _th("Exit date", "date"),
            _th("Entry", "num"),
            _th("Exit", "num"),
            _th("Entry yhigh", "num"),
            _th("Entry drop %", "num"),
            _th("PnL %", "num"),
            _th("Cal d held", "num"),
            _th("TD held", "num"),
            _th("Exit type", "text"),
            _th("IS/OOS", "text"),
        ]
    )
    tr_body = []
    show = trades.sort_values(["symbol", "trade_seq"]) if len(trades) else trades
    for _, e in show.iterrows():
        cls = "open" if str(e.get("exit_type")) == "OPEN" else ""
        slice_lab = "OOS" if int(e.get("is_oos") or 0) else "IS"
        tr_body.append(
            f'<tr class="{cls}" data-sym="{_esc(e["symbol"])}">'
            f"<td>{_esc(e['symbol'])}</td>"
            f"<td>{_fmt_int(e['trade_seq'])}</td>"
            f"<td>{_esc(pd.Timestamp(e['entry_date']).date())}</td>"
            f"<td>{_esc(pd.Timestamp(e['exit_date']).date())}</td>"
            f"<td>{_fmt_num(e['entry'], 2)}</td>"
            f"<td>{_fmt_num(e['exit'], 2)}</td>"
            f"<td>{_fmt_num(e['entry_yhigh'], 2)}</td>"
            f"<td>{_fmt_pct(e['entry_drop_pct'])}</td>"
            f"<td>{_fmt_pct(e['pnl_pct'])}</td>"
            f"<td>{_fmt_int(e['cal_days_held'])}</td>"
            f"<td>{_fmt_int(e['td_days_held'])}</td>"
            f"<td>{_esc(e['exit_type'])}</td>"
            f"<td>{slice_lab}</td>"
            "</tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>42% off yearly high → new yearly high — {STAMP_ID}</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 24px; color: #0f172a; background: #f8fafc; }}
h1 {{ font-size: 1.45rem; margin: 0 0 4px; }}
h2 {{ font-size: 1.15rem; margin: 1.6rem 0 .5rem; border-bottom: 1px solid #cbd5e1; padding-bottom: .25rem; }}
.sub, .meta {{ color: #475569; font-size: .92rem; max-width: 74rem; line-height: 1.5; }}
.callout {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: .85rem 1rem; margin: .75rem 0; max-width: 74rem; }}
.cards {{ display: flex; flex-wrap: wrap; gap: 12px; margin: 16px 0 24px; }}
.card {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px 16px; min-width: 200px; flex: 1 1 210px; }}
.card h3 {{ margin: 0 0 8px; font-size: 13px; color: #475569; }}
.metric {{ font-size: 1.25rem; font-weight: 700; line-height: 1.25; }}
.small {{ font-size: 12px; color: #64748b; }}
.muted {{ color: #94a3b8; }}
.table-wrap {{ overflow-x: auto; margin: 8px 0; }}
table.sortable {{ border-collapse: collapse; background: #fff; font-size: 12px; width: 100%; }}
table.sortable th, table.sortable td {{ border: 1px solid #e2e8f0; padding: 6px 8px; text-align: left; vertical-align: top; }}
table.sortable th {{ background: #f1f5f9; }}
tr.open td {{ background: #fff7ed; }}
tr.total-row td {{ background: #e0f2fe; font-weight: 600; }}
input.filter {{ padding: 6px 10px; border: 1px solid #cbd5e1; border-radius: 6px; min-width: 220px; }}
{spx.SORTABLE_TH_CSS}
</style></head><body>
<h1>Buy 42% off yearly high, sell on new yearly high — 2026-09-21</h1>
<p class="sub">Research trade ledger. Not gold. Not DailyRun. Stamp <code>{STAMP_ID}</code>.
Yearly high = 252-trading-day rolling <em>Close</em> max (not sample all-time high / ATH).
OHLC {_esc(ohlc_start)} → {_esc(ohlc_end)}. Click column headers to sort.</p>
<div class="callout">
<h2 style="margin-top:0">What you asked</h2>
<p>{_esc(ORIGINAL_REQUEST)}</p>
<h2>In plain English</h2>
<p>{_esc(LAYMAN)}</p>
</div>
<div class="cards">{card_html}</div>

<h2>Book metrics (canonical-style absolutes)</h2>
<p class="meta">Equal-weight trade book with ${SHEET_CASH:,.0f} sheet notional per trade.
IS = entry before 2024-01-01; OOS = entry on/after 2024-01-01 (report-only).
FULL includes OPEN mark-to-market; CLOSED = TARGET exits only. Max drawdown (DD) /
Annualized rate of return (Ann ROR) / Calmar / Sharpe from closed-overlay replay.</p>
{_table(books, book_cols)}

<h2>Per-symbol summary</h2>
<p class="meta">Click headers to sort. OVERALL row is trade-equal (pinned).</p>
{_table(stocks_show, stock_cols)}

<h2 id="trades">Trade ledger</h2>
<p class="meta">
<input class="filter" id="symFilter" type="search" placeholder="Filter symbol…"/>
<span class="small"> OPEN rows highlighted. {len(trades):,} trades.</span>
</p>
<div class="table-wrap"><table class="sortable" id="tradeTable"><thead><tr>{tr_head}</tr></thead>
<tbody>{''.join(tr_body)}</tbody></table></div>

<h2>Freeze reminder</h2>
<ul class="meta">
<li>Entry: first Close ≤ 58% of then-current 252d Close high; fill Close; one position / symbol.</li>
<li>Exit: first later Close that is a new 252d high; fill Close. End-of-sample → OPEN MTM.</li>
<li>Distinct from <code>top50_ath_*</code> sample ATH stamps. Research only — do not retune on OOS.</li>
</ul>
<script>{spx.SORTABLE_TABLE_SCRIPT}</script>
<script>
(function(){{
  var input = document.getElementById("symFilter");
  var table = document.getElementById("tradeTable");
  if (!input || !table) return;
  function apply(){{
    var q = (input.value || "").trim().toUpperCase();
    table.tBodies[0].querySelectorAll("tr").forEach(function(tr){{
      var sym = (tr.getAttribute("data-sym") || "").toUpperCase();
      tr.style.display = (!q || sym.indexOf(q) >= 0) ? "" : "none";
    }});
  }}
  input.addEventListener("input", apply);
}})();
</script>
</body></html>
"""
    path.write_text(html, encoding="utf-8")


def _write_failure_html(path: Path, err: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><title>FAILED — {STAMP_ID}</title>
<style>body{{font-family:Segoe UI,system-ui,sans-serif;margin:24px;color:#0f172a}}
.err{{background:#fef2f2;border:1px solid #fecaca;padding:1rem;border-radius:8px;white-space:pre-wrap}}</style>
</head><body>
<h1>FAILED — {STAMP_ID}</h1>
<div class="callout"><h2>What you asked</h2><p>{_esc(ORIGINAL_REQUEST)}</p>
<h2>In plain English</h2><p>{_esc(LAYMAN)}</p></div>
<p>Job failed before a complete trade ledger could be written.</p>
<div class="err">{_esc(err)}</div>
</body></html>"""
    path.write_text(html, encoding="utf-8")


def _load_universe() -> tuple[list[str], dict[str, list[int]], pd.DataFrame, pd.DataFrame, list[str]]:
    """Reuse ath helpers for wiki / mcap / OHLC / annual top-50 membership."""
    print("[y42] loading Wikipedia S&P 500 list + mcaps...", flush=True)
    wiki = ath._load_wiki()
    import duckdb

    con = duckdb.connect(str(ath.DB_PATH), read_only=True)
    try:
        db_syms = {str(r[0]).upper() for r in con.execute("SELECT DISTINCT symbol FROM prices").fetchall()}
    finally:
        con.close()
    universe = [s for s in wiki if s in db_syms]
    missing = [s for s in wiki if s not in db_syms]
    mcap = ath._load_mcaps(universe)
    if "GOOG" in mcap and "GOOGL" in mcap:
        mcap.pop("GOOG", None)
        print("[y42] dropped dual-class GOOG", flush=True)
    print(
        f"[y42] wiki {len(wiki)} universe {len(universe)} mcap {len(mcap)} missing {len(missing)}",
        flush=True,
    )
    load_syms = sorted(set(list(mcap.keys()) + ["SPY"]))
    print(f"[y42] loading OHLC for {len(load_syms)} symbols...", flush=True)
    raw = ath._load_ohlc(load_syms)
    closes = raw.pivot(index="Date", columns="symbol", values="Close").sort_index()
    if "SPY" in closes.columns:
        spy = closes["SPY"].dropna()
        closes = closes.reindex(spy.index)
    membership, years_by_sym = ath._annual_top_x(
        closes, mcap, x=ath.TOP_X, start_year=ath.MEMBERSHIP_START_YEAR
    )
    ever = sorted(years_by_sym)
    if not ever:
        raise RuntimeError("No top-50 members found")
    print(f"[y42] ever top {ath.TOP_X}: {len(ever)} names, {len(membership)} membership rows", flush=True)
    return ever, years_by_sym, membership, raw, missing


def main() -> int:
    t0 = time.time()
    STAMP_DIR.mkdir(parents=True, exist_ok=True)

    ever, years_by_sym, membership, raw, missing = _load_universe()
    raw_by = {s: g for s, g in raw.groupby("symbol", sort=False)}

    trades: list[dict[str, Any]] = []
    for i, sym in enumerate(ever, 1):
        frame = raw_by.get(sym)
        if frame is None or frame.empty:
            print(f"[y42] skip {sym}: no OHLC", flush=True)
            continue
        tlist = _trades_for_symbol(sym, frame, years_top50=years_by_sym.get(sym, []))
        trades.extend(tlist)
        if i % 20 == 0 or i == len(ever):
            print(f"[y42] scored {i}/{len(ever)} names, {len(trades)} trades", flush=True)

    if not trades:
        raise RuntimeError("No trades generated (check OHLC / lookback)")

    trade_df = pd.DataFrame(trades)
    stocks = _stock_summary(trade_df, years_by_sym)

    is_tr = [t for t in trades if pd.Timestamp(t["entry_date"]) < IS_CUT]
    oos_tr = [t for t in trades if pd.Timestamp(t["entry_date"]) >= IS_CUT]
    closed_tr = [t for t in trades if str(t.get("exit_type")) == "TARGET"]

    books = pd.DataFrame(
        [
            _book_metrics(
                trades,
                label="strategy_FULL",
                note="42% off 252d Close-high → sell new 252d Close-high. Incl. OPEN MTM. All years.",
            ),
            _book_metrics(
                closed_tr,
                label="strategy_CLOSED",
                note="Same rule; TARGET exits only (excludes end-of-sample OPEN).",
            ),
            _book_metrics(
                is_tr,
                label="strategy_IS",
                note="Same rule. entry_date < 2024-01-01 (incl. OPEN if still open).",
            ),
            _book_metrics(
                oos_tr,
                label="strategy_OOS",
                note="Same rule. entry_date ≥ 2024-01-01 (report-only; do not retune).",
            ),
        ]
    )

    ohlc_start = str(pd.Timestamp(raw["Date"].min()).date())
    ohlc_end = str(pd.Timestamp(raw["Date"].max()).date())
    membership_years = sorted({int(y) for y in membership["year"]})

    out_tr = trade_df.copy()
    out_tr["entry_date"] = pd.to_datetime(out_tr["entry_date"]).dt.strftime("%Y-%m-%d")
    out_tr["exit_date"] = pd.to_datetime(out_tr["exit_date"]).dt.strftime("%Y-%m-%d")
    out_tr.to_csv(STAMP_DIR / "trades.csv", index=False)
    stocks.to_csv(STAMP_DIR / "stock_summary.csv", index=False)
    books.to_csv(STAMP_DIR / "book_metrics.csv", index=False)
    membership.to_csv(STAMP_DIR / "membership_annual_top50.csv", index=False)
    (STAMP_DIR / "universe_ever_top50.txt").write_text("\n".join(ever) + "\n", encoding="utf-8")
    (STAMP_DIR / "universe_missing.txt").write_text("\n".join(missing) + "\n", encoding="utf-8")

    _write_baseline(
        STAMP_DIR / "BASELINE.md",
        books=books,
        ohlc_start=ohlc_start,
        ohlc_end=ohlc_end,
        n_names=len(ever),
        n_trades=len(trades),
        membership_years=membership_years,
    )
    _write_html(
        REPORT_HTML,
        books=books,
        stocks=stocks,
        trades=trade_df,
        ohlc_start=ohlc_start,
        ohlc_end=ohlc_end,
        n_names=len(ever),
    )
    COMPARE_HTML.write_text(REPORT_HTML.read_text(encoding="utf-8"), encoding="utf-8")

    full = books[books["arm"] == "strategy_FULL"].iloc[0].to_dict()
    summary = {
        "stamp": STAMP_ID,
        "yhigh_basis": "Close_252td",
        "entry": f"Close <= {ENTRY_MULT} * yhigh (first touch; fill Close)",
        "exit": "new 252td Close high after entry (fill Close); OPEN=MTM at last Close",
        "drop_pct": DROP_PCT,
        "lookback_td": LOOKBACK_TD,
        "n_names": len(ever),
        "n_trades": len(trades),
        "ohlc_start": ohlc_start,
        "ohlc_end": ohlc_end,
        "membership_years": membership_years,
        "book": books.to_dict("records"),
        "headline_full": {
            "n_trades": full.get("n_trades"),
            "win_pct": full.get("win_pct"),
            "avg_pnl_pct": full.get("avg_pnl_pct"),
            "median_days_held": full.get("median_days_held"),
            "ann_ror": full.get("ann_ror"),
            "max_dd": full.get("max_dd"),
        },
        "elapsed_sec": time.time() - t0,
        "not_dailyrun": True,
        "not_sample_ath": True,
    }
    (STAMP_DIR / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary["headline_full"], indent=2), flush=True)
    print(f"[y42] wrote {STAMP_DIR} in {time.time() - t0:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        err = traceback.format_exc()
        print(err, flush=True)
        try:
            STAMP_DIR.mkdir(parents=True, exist_ok=True)
            fail_path = STAMP_DIR / "report.html"
            _write_failure_html(fail_path, err)
            print(f"[y42] wrote failure HTML {fail_path}", flush=True)
        except Exception:
            pass
        raise SystemExit(1) from exc
