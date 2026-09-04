#!/usr/bin/env python3
"""Paper-style MOM2–12 monthly ranks on liquid ~763 — research AB.

MOM2–12 = 12-month total return skipping the most recent month
(Asness / Moskowitz / Pedersen, “Value and Momentum Everywhere,” JoF 2013).

Control: equal-weight liquid-universe buy-hold (monthly rebalance to EW).
Candidate: long top quintile by MOM2–12, equal-weight, monthly rebalance.
Diagnostic: long–short top−bottom quintile (cash-neutral factor sleeve).
Secondary reference (not a same-construction control): Clenow MOM metrics from
``mom_baseline_liquid_20260829/metrics.json`` when present.

Research-only. No DailyRun wire.

Usage:
  python tools/mom_mom212_paper_ab.py
  python tools/mom_mom212_paper_ab.py --limit 80
  python tools/mom_mom212_paper_ab.py --out drive/paul_experiments/mom_mom212_liquid763_20260904
"""
from __future__ import annotations

import argparse
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
for _p in (_PE, _TOOLS, _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    format_money,
    is_excluded_html_compare_label,
)

STAMP_DATE = "20260904"
STAMP = f"mom_mom212_liquid763_{STAMP_DATE}"
OUT_DIR = _PE / STAMP
DEFAULT_DB = _REPO / "data" / "ohlcv.duckdb"
DEFAULT_UNIV = _REPO / "drive" / "universes" / "MOM_universe.csv"
CLENOW_METRICS = _PE / "mom_baseline_liquid_20260829" / "metrics.json"
IS_CUT = date(2024, 1, 1)

# --- Frozen knobs (document in BASELINE.md) ---
SKIP_BARS = 21  # ~1 calendar month of trading days skipped
LOOKBACK_BARS = 252  # ~12 months total window; skip most recent SKIP_BARS
# MOM2–12 return uses closes[t - LOOKBACK_BARS] → closes[t - SKIP_BARS]
TOP_FRAC = 0.20  # quintile (aligns with house Clenow top 20%)
SLIPPAGE_BPS = 10.0  # one-way; research cost assumption
INITIAL_CAPITAL = DEFAULT_INITIAL_ACCOUNT
MIN_NAMES_FOR_RANK = 50  # skip rebalance month if too few ranked names


def _sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


SORTABLE_TH_CSS = """
  th.sortable-th { cursor:pointer; user-select:none; white-space:nowrap; }
  th.sortable-th:hover { background:#e8e6df; }
  th.sortable-th .sort-ind::after { content:" \\u2195"; opacity:0.35; font-size:0.85em; }
  th.sortable-th.sort-asc .sort-ind::after { content:" \\u25B2"; opacity:0.9; }
  th.sortable-th.sort-desc .sort-ind::after { content:" \\u25BC"; opacity:0.9; }
"""

SORT_JS = r"""
<script>
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : 0;
    if (type === "text") return s.toUpperCase();
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
      var av = parseSortValue(a.cells[col] ? a.cells[col].innerText : "", type);
      var bv = parseSortValue(b.cells[col] ? b.cells[col].innerText : "", type);
      var cmp = av < bv ? -1 : av > bv ? 1 : 0;
      return dir === "asc" ? cmp : -cmp;
    });
    movable.concat(pinned).forEach(function (r) { tbody.appendChild(r); });
  }
  function bind(table, th, col) {
    function onActivate(e) {
      if (e.type === "touchend") e.preventDefault();
      var type = th.getAttribute("data-sort") || "text";
      var cur = th.getAttribute("aria-sort");
      var dir = cur === "ascending" ? "desc" : "asc";
      table.querySelectorAll("th.sortable-th").forEach(function (h) {
        h.setAttribute("aria-sort", "none");
        h.classList.remove("sort-asc", "sort-desc");
      });
      th.setAttribute("aria-sort", dir === "asc" ? "ascending" : "descending");
      th.classList.add(dir === "asc" ? "sort-asc" : "sort-desc");
      sortTable(table, col, type, dir);
    }
    th.addEventListener("click", onActivate);
    th.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); onActivate(ev); }
    });
    th.addEventListener("touchend", onActivate, { passive: false });
  }
  document.querySelectorAll("table.sortable").forEach(function (table) {
    Array.from(table.tHead ? table.tHead.rows[0].cells : []).forEach(function (th, col) {
      if (th.classList.contains("sortable-th")) bind(table, th, col);
    });
  });
})();
</script>
"""


def load_universe(path: Path) -> list[str]:
    syms: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.split("#", 1)[0].strip().upper()
        if not s or s in {"SYMBOL", "*", "ALL"}:
            continue
        for tok in s.replace(",", " ").split():
            t = tok.strip().upper()
            if t and t not in syms:
                syms.append(t)
    return syms


def _slip_buy(px: float) -> float:
    return px * (1.0 + SLIPPAGE_BPS / 10_000.0)


def _slip_sell(px: float) -> float:
    return px * (1.0 - SLIPPAGE_BPS / 10_000.0)


def load_ohlc_panel(
    db_path: Path,
    symbols: list[str],
    *,
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> tuple[pd.DatetimeIndex, np.ndarray, np.ndarray, list[str]]:
    """Return calendar, close[T,S], open[T,S], symbol list (aligned columns)."""
    need = sorted(set(symbols))
    con = duckdb.connect(str(db_path), read_only=True)
    placeholders = ",".join("?" for _ in need)
    q = f"""
      SELECT symbol, date, open, close
      FROM prices
      WHERE symbol IN ({placeholders})
      ORDER BY date, symbol
    """
    df = con.execute(q, need).fetchdf()
    con.close()
    if df.empty:
        raise RuntimeError("No OHLC rows for universe")
    df["date"] = pd.to_datetime(df["date"])
    if start:
        df = df[df["date"] >= pd.Timestamp(start)]
    if end:
        df = df[df["date"] <= pd.Timestamp(end)]
    close_w = df.pivot(index="date", columns="symbol", values="close").sort_index()
    open_w = df.pivot(index="date", columns="symbol", values="open").sort_index()
    # Keep symbols with enough history for MOM2–12
    min_bars = LOOKBACK_BARS + 5
    keep = [c for c in close_w.columns if close_w[c].notna().sum() >= min_bars]
    close_w = close_w[keep]
    open_w = open_w.reindex(columns=keep)
    cal = close_w.index
    return cal, close_w.to_numpy(dtype=float), open_w.to_numpy(dtype=float), list(keep)


def month_end_indices(cal: pd.DatetimeIndex) -> list[int]:
    """Last trading-day index of each calendar month."""
    months = cal.to_period("M")
    out: list[int] = []
    for i in range(len(cal)):
        if i == len(cal) - 1 or months[i] != months[i + 1]:
            out.append(i)
    return out


def mom212_at(close: np.ndarray, t: int) -> np.ndarray:
    """Vector of MOM2–12 returns at bar t for all symbols. NaN if missing."""
    # need t - LOOKBACK_BARS and t - SKIP_BARS
    if t < LOOKBACK_BARS:
        return np.full(close.shape[1], np.nan)
    p0 = close[t - LOOKBACK_BARS, :]
    p1 = close[t - SKIP_BARS, :]
    out = np.full(close.shape[1], np.nan)
    ok = np.isfinite(p0) & np.isfinite(p1) & (p0 > 0) & (p1 > 0)
    out[ok] = p1[ok] / p0[ok] - 1.0
    return out


@dataclass
class Trade:
    symbol: str
    entry_date: date
    exit_date: date
    entry_px: float
    exit_px: float
    shares: float
    pnl_dollars: float
    pnl_pct: float
    days_held: int
    exit_reason: str
    entry_score: float
    arm: str


def _max_dd_pct(equity: pd.Series) -> float:
    if equity.empty:
        return float("nan")
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(-dd.min() * 100.0)


def _ann_ror(eq0: float, eq1: float, start: date, end: date) -> float:
    if eq0 <= 0:
        return float("nan")
    years = max((end - start).days / 365.25, 1e-9)
    total = eq1 / eq0 - 1.0
    if total <= -1.0:
        return -100.0
    return ((1.0 + total) ** (1.0 / years) - 1.0) * 100.0


def equity_slice_metrics(eq_df: pd.DataFrame, start: date, end: date, label: str) -> dict[str, Any]:
    sub = eq_df[(eq_df["d"] >= start) & (eq_df["d"] <= end)].copy()
    if len(sub) < 2:
        return {
            "label": label,
            "n_days": len(sub),
            "ann_ror": float("nan"),
            "max_dd": float("nan"),
            "total_ret_pct": float("nan"),
            "sharpe": float("nan"),
            "calmar": float("nan"),
        }
    e0 = float(sub["equity"].iloc[0])
    e1 = float(sub["equity"].iloc[-1])
    rets = sub["equity"].pct_change().dropna()
    sharpe = float("nan")
    if len(rets) > 2 and float(rets.std(ddof=1)) > 0:
        sharpe = float(rets.mean() / rets.std(ddof=1) * math.sqrt(252.0))
    ann = _ann_ror(e0, e1, sub["d"].iloc[0], sub["d"].iloc[-1])
    mdd = _max_dd_pct(sub["equity"])
    calmar = (
        (ann / abs(mdd))
        if (np.isfinite(ann) and np.isfinite(mdd) and abs(mdd) > 1e-9)
        else float("nan")
    )
    return {
        "label": label,
        "n_days": len(sub),
        "start": sub["d"].iloc[0].isoformat(),
        "end": sub["d"].iloc[-1].isoformat(),
        "start_equity": e0,
        "end_equity": e1,
        "total_ret_pct": (e1 / e0 - 1.0) * 100.0 if e0 else float("nan"),
        "ann_ror": ann,
        "max_dd": mdd,
        "sharpe": sharpe,
        "calmar": calmar,
    }


def trade_metrics(trades: list[Trade]) -> dict[str, Any]:
    if not trades:
        return {
            "n": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": float("nan"),
            "avg_pnl_pct": float("nan"),
            "avg_pnl_pct_wo_max": float("nan"),
            "avg_days": float("nan"),
            "median_days": float("nan"),
            "profit_factor": float("nan"),
            "expectancy_pct": float("nan"),
            "avg_win_pct": float("nan"),
            "avg_loss_pct": float("nan"),
            "capital_days": 0,
            "profit_per_cap_day": float("nan"),
            "total_pnl_dollars": 0.0,
        }
    pnls = np.array([t.pnl_pct for t in trades], dtype=float)
    dollars = np.array([t.pnl_dollars for t in trades], dtype=float)
    days = np.array([t.days_held for t in trades], dtype=float)
    wins_m = pnls > 0
    losses_m = ~wins_m
    gross_win = float(dollars[dollars > 0].sum()) if np.any(dollars > 0) else 0.0
    gross_loss = float(abs(dollars[dollars < 0].sum())) if np.any(dollars < 0) else 0.0
    pf = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else float("nan"))
    wo = pnls.copy()
    if len(wo) > 1:
        wo = np.delete(wo, int(np.argmax(wo)))
    cap_days = float(days.sum())
    total_pnl = float(dollars.sum())
    return {
        "n": len(trades),
        "wins": int(wins_m.sum()),
        "losses": int(losses_m.sum()),
        "win_rate": 100.0 * float(wins_m.mean()),
        "avg_pnl_pct": float(pnls.mean()),
        "avg_pnl_pct_wo_max": float(wo.mean()) if len(wo) else float("nan"),
        "avg_days": float(days.mean()),
        "median_days": float(np.median(days)),
        "profit_factor": pf,
        "expectancy_pct": float(pnls.mean()),
        "avg_win_pct": float(pnls[wins_m].mean()) if wins_m.any() else float("nan"),
        "avg_loss_pct": float(pnls[losses_m].mean()) if losses_m.any() else float("nan"),
        "capital_days": int(cap_days),
        "profit_per_cap_day": (total_pnl / cap_days) if cap_days > 0 else float("nan"),
        "total_pnl_dollars": total_pnl,
    }


def pack_metrics(eq_rows: list[dict], trades: list[Trade]) -> dict[str, Any]:
    eq_df = pd.DataFrame(eq_rows)
    eq_df["d"] = pd.to_datetime(eq_df["date"]).dt.date
    full_m = equity_slice_metrics(eq_df, eq_df["d"].iloc[0], eq_df["d"].iloc[-1], "full_book")
    is_m = equity_slice_metrics(eq_df, eq_df["d"].iloc[0], date(2023, 12, 31), "IS_equity")
    oos_m = equity_slice_metrics(eq_df, IS_CUT, eq_df["d"].iloc[-1], "OOS_equity")
    is_trades = [t for t in trades if t.entry_date < IS_CUT]
    oos_trades = [t for t in trades if t.entry_date >= IS_CUT]
    return {
        "eq_df": eq_df,
        "full_m": full_m,
        "is_m": is_m,
        "oos_m": oos_m,
        "tm_all": trade_metrics(trades),
        "tm_is": trade_metrics(is_trades),
        "tm_oos": trade_metrics(oos_trades),
        "trades": trades,
    }


def _next_open_i(cal: pd.DatetimeIndex, signal_i: int) -> Optional[int]:
    if signal_i + 1 >= len(cal):
        return None
    return signal_i + 1


def run_long_sleeve(
    *,
    arm: str,
    cal: pd.DatetimeIndex,
    close: np.ndarray,
    open_: np.ndarray,
    symbols: list[str],
    me_idx: list[int],
    pick_fn,
    initial_capital: float = INITIAL_CAPITAL,
    bt_start_i: int = 0,
) -> dict[str, Any]:
    """Monthly long equal-weight sleeve.

    Signal at month-end close; fill at next open (+slip). Liquidate / rotate at
    next month's fill open. Mark-to-market daily on close (no slip on marks).
    """
    T, S = close.shape
    cash = float(initial_capital)
    # holdings: list of (sym_i, shares, entry_date, entry_px, entry_score, cost_basis)
    holdings: list[tuple[int, float, date, float, float, float]] = []
    trades: list[Trade] = []
    equity_rows: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    n_pos_hist: list[int] = []

    # Map signal month-end → fill index
    rebal_pairs: list[tuple[int, int]] = []  # (signal_i, fill_i)
    for si in me_idx:
        if si < bt_start_i:
            continue
        fi = _next_open_i(cal, si)
        if fi is None:
            continue
        rebal_pairs.append((si, fi))

    fill_to_signal = {fi: si for si, fi in rebal_pairs}
    fill_set = set(fill_to_signal.keys())

    def mtm_equity(ti: int) -> float:
        eq = cash
        for si, sh, *_rest in holdings:
            px = close[ti, si]
            if np.isfinite(px) and px > 0:
                eq += sh * px
        return eq

    def liquidate_all(ti: int, reason: str) -> None:
        nonlocal cash, holdings
        px_row = open_[ti, :] if reason != "end_of_backtest" else close[ti, :]
        new_holdings: list[tuple[int, float, date, float, float, float]] = []
        for si, sh, ed, ep, score, basis in holdings:
            px = px_row[si]
            if not (np.isfinite(px) and px > 0):
                # try close
                px = close[ti, si]
            if not (np.isfinite(px) and px > 0):
                new_holdings.append((si, sh, ed, ep, score, basis))
                continue
            fill = _slip_sell(float(px))
            proceeds = sh * fill
            cash += proceeds
            pnl = proceeds - basis
            pnl_pct = (fill / ep - 1.0) * 100.0 if ep else 0.0
            xd = cal[ti].date()
            trades.append(
                Trade(
                    symbol=symbols[si],
                    entry_date=ed,
                    exit_date=xd,
                    entry_px=ep,
                    exit_px=fill,
                    shares=sh,
                    pnl_dollars=pnl,
                    pnl_pct=pnl_pct,
                    days_held=(xd - ed).days,
                    exit_reason=reason,
                    entry_score=score,
                    arm=arm,
                )
            )
            events.append(
                {
                    "signal_date": xd.isoformat(),
                    "fill_date": xd.isoformat(),
                    "action": "SELL",
                    "symbol": symbols[si],
                    "shares": -sh,
                    "price": fill,
                    "reason": reason,
                    "score": score,
                    "arm": arm,
                }
            )
        holdings = new_holdings

    first_fill = rebal_pairs[0][1] if rebal_pairs else bt_start_i
    for ti in range(first_fill, T):
        if ti in fill_set:
            si = fill_to_signal[ti]
            # Rotate: sell all at this open, then buy new basket
            liquidate_all(ti, "month_rebalance")
            scores = mom212_at(close, si)
            picks = pick_fn(scores, close[si, :])
            if picks:
                # Equal-weight dollars
                eq_pre = cash  # fully in cash after liquidate
                n = len(picks)
                per = eq_pre / n if n else 0.0
                for sj, score in picks:
                    opx = open_[ti, sj]
                    if not (np.isfinite(opx) and opx > 0):
                        continue
                    fill = _slip_buy(float(opx))
                    shares = per / fill
                    if shares <= 0:
                        continue
                    cost = shares * fill
                    if cost > cash + 1e-6:
                        shares = cash / fill
                        cost = shares * fill
                    cash -= cost
                    ed = cal[ti].date()
                    holdings.append((sj, shares, ed, fill, float(score), cost))
                    events.append(
                        {
                            "signal_date": cal[si].date().isoformat(),
                            "fill_date": ed.isoformat(),
                            "action": "BUY",
                            "symbol": symbols[sj],
                            "shares": shares,
                            "price": fill,
                            "reason": "month_rebalance",
                            "score": float(score),
                            "arm": arm,
                        }
                    )

        eq = mtm_equity(ti)
        n_pos_hist.append(len(holdings))
        equity_rows.append(
            {
                "date": cal[ti].date().isoformat(),
                "equity": eq,
                "cash": cash,
                "n_positions": len(holdings),
            }
        )

    # End-of-book liquidation at last close
    if holdings:
        liquidate_all(T - 1, "end_of_backtest")
        # refresh last equity row
        if equity_rows:
            equity_rows[-1]["equity"] = cash
            equity_rows[-1]["cash"] = cash
            equity_rows[-1]["n_positions"] = 0

    packed = pack_metrics(equity_rows, trades)
    packed["arm"] = arm
    packed["events"] = events
    packed["equity_rows"] = equity_rows
    packed["n_pos_avg"] = float(np.mean(n_pos_hist)) if n_pos_hist else 0.0
    packed["n_pos_max"] = int(max(n_pos_hist)) if n_pos_hist else 0
    packed["final_equity"] = float(equity_rows[-1]["equity"]) if equity_rows else initial_capital
    packed["initial_capital"] = initial_capital
    return packed


def pick_top_quintile(scores: np.ndarray, closes_today: np.ndarray) -> list[tuple[int, float]]:
    ok = np.isfinite(scores) & np.isfinite(closes_today) & (closes_today > 0)
    idx = np.where(ok)[0]
    if len(idx) < MIN_NAMES_FOR_RANK:
        return []
    sc = scores[idx]
    order = np.argsort(-sc)  # descending
    n_top = max(1, int(math.floor(len(idx) * TOP_FRAC)))
    chosen = idx[order[:n_top]]
    return [(int(j), float(scores[j])) for j in chosen]


def pick_all_ew(scores: np.ndarray, closes_today: np.ndarray) -> list[tuple[int, float]]:
    """Control: all names with a finite close today (score unused / NaN ok)."""
    ok = np.isfinite(closes_today) & (closes_today > 0)
    idx = np.where(ok)[0]
    if len(idx) < MIN_NAMES_FOR_RANK:
        return []
    return [(int(j), float(scores[j]) if np.isfinite(scores[j]) else float("nan")) for j in idx]


def run_long_short_factor(
    *,
    cal: pd.DatetimeIndex,
    close: np.ndarray,
    me_idx: list[int],
    bt_start_i: int,
) -> dict[str, Any]:
    """Cash-neutral top−bottom quintile daily marked factor (gross 1 long + 1 short).

    No share trades — pure return series for diagnostic Sharpe/AnnROR/DD.
    Costs: approximate 10 bps one-way on each monthly turnover half (long+short).
    """
    T, _S = close.shape
    # Daily simple returns
    rets = np.full_like(close, np.nan)
    rets[1:, :] = close[1:, :] / close[:-1, :] - 1.0

    # Build weight matrix over time (piecewise constant from fill day after signal)
    w_long = np.zeros((T, close.shape[1]))
    w_short = np.zeros((T, close.shape[1]))
    for k, si in enumerate(me_idx):
        if si < bt_start_i:
            continue
        fi = _next_open_i(cal, si)
        if fi is None:
            continue
        # hold until next fill or end
        next_fi = T
        for si2 in me_idx:
            if si2 <= si:
                continue
            fi2 = _next_open_i(cal, si2)
            if fi2 is not None:
                next_fi = fi2
                break
        scores = mom212_at(close, si)
        ok = np.isfinite(scores) & np.isfinite(close[si, :]) & (close[si, :] > 0)
        idx = np.where(ok)[0]
        if len(idx) < MIN_NAMES_FOR_RANK:
            continue
        sc = scores[idx]
        order = np.argsort(-sc)
        n_q = max(1, int(math.floor(len(idx) * TOP_FRAC)))
        top = idx[order[:n_q]]
        bot = idx[order[-n_q:]]
        wl = np.zeros(close.shape[1])
        ws = np.zeros(close.shape[1])
        wl[top] = 1.0 / len(top)
        ws[bot] = 1.0 / len(bot)
        w_long[fi:next_fi, :] = wl
        w_short[fi:next_fi, :] = ws

    # Portfolio daily return = long ret − short ret; subtract turnover cost at fills
    port = np.zeros(T)
    for ti in range(1, T):
        rl = np.nansum(w_long[ti, :] * rets[ti, :])
        rs = np.nansum(w_short[ti, :] * rets[ti, :])
        port[ti] = rl - rs

    # Turnover cost on rebalance fills: sum |Δw| * slip for long and short sleeves
    slip = SLIPPAGE_BPS / 10_000.0
    for si in me_idx:
        if si < bt_start_i:
            continue
        fi = _next_open_i(cal, si)
        if fi is None or fi == 0:
            continue
        d_long = np.abs(w_long[fi, :] - w_long[fi - 1, :]).sum()
        d_short = np.abs(w_short[fi, :] - w_short[fi - 1, :]).sum()
        port[fi] -= (d_long + d_short) * slip

    # Equity from compounded factor returns (start after first non-zero weight day)
    start_i = next((i for i in range(T) if w_long[i].sum() > 0), None)
    if start_i is None:
        return {"arm": "mom212_ls_q", "equity_rows": [], "trades": [], "full_m": {}, "error": "no weights"}

    eq = INITIAL_CAPITAL
    rows: list[dict[str, Any]] = []
    for ti in range(start_i, T):
        if ti > start_i:
            eq *= 1.0 + port[ti]
        rows.append(
            {
                "date": cal[ti].date().isoformat(),
                "equity": eq,
                "cash": 0.0,
                "n_positions": int((w_long[ti] > 0).sum() + (w_short[ti] > 0).sum()),
            }
        )
    packed = pack_metrics(rows, [])
    packed["arm"] = "mom212_ls_q"
    packed["equity_rows"] = rows
    packed["final_equity"] = float(rows[-1]["equity"]) if rows else INITIAL_CAPITAL
    packed["initial_capital"] = INITIAL_CAPITAL
    packed["n_pos_avg"] = float(np.mean([r["n_positions"] for r in rows])) if rows else 0.0
    packed["n_pos_max"] = int(max(r["n_positions"] for r in rows)) if rows else 0
    return packed


def _fmt(x: Any, nd: int = 2) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if not np.isfinite(v):
        return "—"
    return f"{v:.{nd}f}"


def load_clenow_ref() -> Optional[dict[str, Any]]:
    if not CLENOW_METRICS.exists():
        return None
    return json.loads(CLENOW_METRICS.read_text(encoding="utf-8"))


def verdict_from_is(ctrl: dict[str, Any], cand: dict[str, Any]) -> tuple[str, str]:
    """IS quality KEEP/HOLD/DISMISS vs EW control. OOS not used for decision."""
    c_ann = float(ctrl["is_m"].get("ann_ror", float("nan")))
    a_ann = float(cand["is_m"].get("ann_ror", float("nan")))
    c_sh = float(ctrl["is_m"].get("sharpe", float("nan")))
    a_sh = float(cand["is_m"].get("sharpe", float("nan")))
    c_cal = float(ctrl["is_m"].get("calmar", float("nan")))
    a_cal = float(cand["is_m"].get("calmar", float("nan")))
    c_dd = float(ctrl["is_m"].get("max_dd", float("nan")))
    a_dd = float(cand["is_m"].get("max_dd", float("nan")))
    c_avg = float(ctrl["tm_is"].get("avg_pnl_pct", float("nan")))
    a_avg = float(cand["tm_is"].get("avg_pnl_pct", float("nan")))

    lifts = []
    if np.isfinite(a_ann) and np.isfinite(c_ann):
        lifts.append(a_ann - c_ann)
    if np.isfinite(a_sh) and np.isfinite(c_sh):
        lifts.append(a_sh - c_sh)
    if np.isfinite(a_cal) and np.isfinite(c_cal):
        lifts.append(a_cal - c_cal)

    better = sum(1 for x in lifts if x > 0)
    worse = sum(1 for x in lifts if x < 0)
    # Quality: require Ann ROR lift and (Sharpe or Calmar) lift, DD not collapsing badly
    dd_ok = True
    if np.isfinite(a_dd) and np.isfinite(c_dd) and c_dd > 0:
        dd_ok = a_dd <= c_dd * 1.25  # allow modest DD increase

    note = (
        f"IS AnnROR {_fmt(a_ann)} vs ctrl {_fmt(c_ann)}; "
        f"Sharpe {_fmt(a_sh)} vs {_fmt(c_sh)}; "
        f"Calmar {_fmt(a_cal)} vs {_fmt(c_cal)}; "
        f"MaxDD {_fmt(a_dd)} vs {_fmt(c_dd)}; "
        f"AvgPnL% {_fmt(a_avg)} vs {_fmt(c_avg)}"
    )

    if (
        np.isfinite(a_ann)
        and np.isfinite(c_ann)
        and a_ann > c_ann + 0.5
        and better >= 2
        and dd_ok
    ):
        return "KEEP", note
    if worse >= 2 and (not np.isfinite(a_ann) or not np.isfinite(c_ann) or a_ann < c_ann - 0.5):
        return "DISMISS", note
    return "HOLD", note


def write_closed_csv(path: Path, trades: list[Trade]) -> None:
    rows = [
        {
            "ARM": t.arm,
            "SYMBOL": t.symbol,
            "ENTRY_DATE": t.entry_date.isoformat(),
            "EXIT_DATE": t.exit_date.isoformat(),
            "ENTRY_PX": round(t.entry_px, 6),
            "EXIT_PX": round(t.exit_px, 6),
            "SHARES": round(t.shares, 6),
            "PNL_DOLLARS": round(t.pnl_dollars, 4),
            "PNL_PCT": round(t.pnl_pct, 6),
            "DAYS_HELD": t.days_held,
            "EXIT_TYPE": t.exit_reason,
            "ENTRY_SCORE": t.entry_score,
        }
        for t in trades
    ]
    pd.DataFrame(rows).to_csv(path, index=False)


def write_stamp(
    out: Path,
    *,
    univ_path: Path,
    univ_n: int,
    symbols_used: int,
    ctrl: dict[str, Any],
    long_q: dict[str, Any],
    ls: dict[str, Any],
    clenow: Optional[dict[str, Any]],
    verdict: str,
    verdict_note: str,
    bt_start: date,
    bt_end: date,
) -> Path:
    out.mkdir(parents=True, exist_ok=True)

    # CSVs
    write_closed_csv(out / "MOM212_Closed_control_ew.csv", ctrl["trades"])
    write_closed_csv(out / "MOM212_Closed_long_q.csv", long_q["trades"])
    pd.DataFrame(ctrl["equity_rows"]).to_csv(out / "MOM212_Equity_control_ew.csv", index=False)
    pd.DataFrame(long_q["equity_rows"]).to_csv(out / "MOM212_Equity_long_q.csv", index=False)
    if ls.get("equity_rows"):
        pd.DataFrame(ls["equity_rows"]).to_csv(out / "MOM212_Equity_ls_q.csv", index=False)

    metrics = {
        "stamp": STAMP,
        "universe": str(univ_path).replace("\\", "/"),
        "n_univ": univ_n,
        "n_symbols_with_ohlc": symbols_used,
        "bt_start": bt_start.isoformat(),
        "bt_end": bt_end.isoformat(),
        "knobs": {
            "signal": "MOM2-12",
            "skip_bars": SKIP_BARS,
            "lookback_bars": LOOKBACK_BARS,
            "top_frac": TOP_FRAC,
            "rebalance": "month_end_close_signal_next_open_fill",
            "slippage_bps_one_way": SLIPPAGE_BPS,
            "weighting": "equal_weight",
            "initial_capital": INITIAL_CAPITAL,
        },
        "control_ew": {
            "full": ctrl["full_m"],
            "is": ctrl["is_m"],
            "oos": ctrl["oos_m"],
            "tm_all": ctrl["tm_all"],
            "tm_is": ctrl["tm_is"],
            "tm_oos": ctrl["tm_oos"],
        },
        "mom212_long_q": {
            "full": long_q["full_m"],
            "is": long_q["is_m"],
            "oos": long_q["oos_m"],
            "tm_all": long_q["tm_all"],
            "tm_is": long_q["tm_is"],
            "tm_oos": long_q["tm_oos"],
        },
        "mom212_ls_q": {
            "full": ls.get("full_m", {}),
            "is": ls.get("is_m", {}),
            "oos": ls.get("oos_m", {}),
        },
        "clenow_ref": clenow,
        "verdict": verdict,
        "verdict_note": verdict_note,
    }
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")

    # BASELINE
    baseline = f"""# BASELINE — `{STAMP}`

**Status:** RESEARCH only. **Not gold. Not DailyRun-wired.**

**Parent map:** `value_momentum_everywhere_20260904` (feasibility recommended first experiment).

**Paper signal:** MOM2–12 = past **12-month** return **skipping the most recent month**
(Asness / Moskowitz / Pedersen, *Value and Momentum Everywhere*, JoF 2013).

## Universe (frozen)

- File: `{univ_path.as_posix()}` (= liquid ADV$2m / `VZ_tradable_2010_adv2m_universe.csv`)
- **N = {univ_n}** symbols listed; **{symbols_used}** with enough OHLC for MOM2–12
- Static membership (first bar ≤2010 / ADV$ traits) — **not** PIT large-cap / CRSP; survivorship labeled
- OHLC: `data/ohlcv.duckdb` table `prices`
- Window: **{bt_start.isoformat()} → {bt_end.isoformat()}**

## Control (primary)

- **Equal-weight liquid-universe buy-hold**, monthly rebalance to EW
- Same fill / slip / calendar as candidate (fair cost model)
- Identity: `control_ew`

## Candidate (primary)

- Rank all names with finite MOM2–12 at month-end close
- Hold **top {TOP_FRAC:.0%}** (quintile) **equal-weight**
- Identity: `mom212_long_q`

## Diagnostic (not KEEP arm)

- Long–short top−bottom quintile, cash-neutral daily marked factor (`mom212_ls_q`)
- Approximate turnover slip only; no share book / trade metrics

## Secondary reference (not same-construction control)

- Clenow weekly MOM sleeve metrics from `mom_baseline_liquid_20260829` (90d vol-adj slope×R²,
  ATR sizing, SMA100 exit, SPY SMA200 gate) — different signal, cadence, sizing, exits.
  Shown for context only; KEEP/DISMISS judged vs **EW control**.

## Signal math (frozen)

- Trading-day approximation: `MOM2–12(t) = Close[t−{SKIP_BARS}] / Close[t−{LOOKBACK_BARS}] − 1`
  ({LOOKBACK_BARS}≈12m, skip most recent {SKIP_BARS}≈1m)
- Month-end = last session of calendar month on SPY/universe calendar
- **Signal** at month-end **close**; **fill** at **next session open**
- Slippage: **{SLIPPAGE_BPS:.0f} bps** one-way (research)
- Initial capital: **${INITIAL_CAPITAL:,.0f}**
- Weighting: **equal-weight** within sleeve (paper used value-weight in liquid large-cap — labeled delta)

## IS / OOS

- **IS** = equity / entry_date **&lt; 2024-01-01**; **OOS** = **≥ 2024-01-01**
- OOS is **report-only** — do not retune on OOS
- Verdict on **IS quality vs EW control** only

## How to re-run

```bash
python tools/mom_mom212_paper_ab.py --out drive/paul_experiments/{STAMP}
```

## Promotion

Research candidate ≠ gold ≠ DailyRun. Do not wire DailyRun from this stamp.
"""
    (out / "BASELINE.md").write_text(baseline, encoding="utf-8")

    # SUMMARY
    ls_full = ls.get("full_m") or {}
    ls_is = ls.get("is_m") or {}
    ls_oos = ls.get("oos_m") or {}
    summary = f"""# SUMMARY — `{STAMP}`

Paper-style **MOM2–12** monthly long top-quintile on liquid **{univ_n}** — research only.

## Control

Equal-weight liquid-universe buy-hold (monthly EW rebalance). Same OHLC / slip / fills as candidate.

## Verdict (IS vs EW control): **{verdict}**

{verdict_note}

OOS report-only — not used for KEEP/DISMISS.

## Equity (full / IS / OOS)

| Arm | Full Ann ROR % | Full Max DD % | Full Sharpe | IS Ann ROR % | IS Max DD % | IS Sharpe | OOS Ann ROR % | OOS Max DD % | OOS Sharpe |
|-----|----------------|---------------|-------------|--------------|-------------|-----------|---------------|--------------|------------|
| control_ew | {_fmt(ctrl['full_m'].get('ann_ror'))} | {_fmt(ctrl['full_m'].get('max_dd'))} | {_fmt(ctrl['full_m'].get('sharpe'))} | {_fmt(ctrl['is_m'].get('ann_ror'))} | {_fmt(ctrl['is_m'].get('max_dd'))} | {_fmt(ctrl['is_m'].get('sharpe'))} | {_fmt(ctrl['oos_m'].get('ann_ror'))} | {_fmt(ctrl['oos_m'].get('max_dd'))} | {_fmt(ctrl['oos_m'].get('sharpe'))} |
| mom212_long_q | {_fmt(long_q['full_m'].get('ann_ror'))} | {_fmt(long_q['full_m'].get('max_dd'))} | {_fmt(long_q['full_m'].get('sharpe'))} | {_fmt(long_q['is_m'].get('ann_ror'))} | {_fmt(long_q['is_m'].get('max_dd'))} | {_fmt(long_q['is_m'].get('sharpe'))} | {_fmt(long_q['oos_m'].get('ann_ror'))} | {_fmt(long_q['oos_m'].get('max_dd'))} | {_fmt(long_q['oos_m'].get('sharpe'))} |
| mom212_ls_q | {_fmt(ls_full.get('ann_ror'))} | {_fmt(ls_full.get('max_dd'))} | {_fmt(ls_full.get('sharpe'))} | {_fmt(ls_is.get('ann_ror'))} | {_fmt(ls_is.get('max_dd'))} | {_fmt(ls_is.get('sharpe'))} | {_fmt(ls_oos.get('ann_ror'))} | {_fmt(ls_oos.get('max_dd'))} | {_fmt(ls_oos.get('sharpe'))} |
"""
    if clenow:
        c_full = clenow.get("full") or {}
        c_is = clenow.get("is") or {}
        c_oos = clenow.get("oos") or {}
        summary += f"""
## Clenow reference (`mom_baseline_liquid_20260829`) — different construction

| Slice | Ann ROR % | Max DD % | Sharpe | Calmar |
|-------|-----------|----------|--------|--------|
| Full | {_fmt(c_full.get('ann_ror'))} | {_fmt(c_full.get('max_dd'))} | {_fmt(c_full.get('sharpe'))} | {_fmt(c_full.get('calmar'))} |
| IS | {_fmt(c_is.get('ann_ror'))} | {_fmt(c_is.get('max_dd'))} | {_fmt(c_is.get('sharpe'))} | {_fmt(c_is.get('calmar'))} |
| OOS | {_fmt(c_oos.get('ann_ror'))} | {_fmt(c_oos.get('max_dd'))} | {_fmt(c_oos.get('sharpe'))} | {_fmt(c_oos.get('calmar'))} |
"""
    summary += f"""
## Trade-level (long sleeves; by entry_date)

| Arm / slice | N | Win% | Avg PnL% | AvgPnL% w/o max | Avg days | PF |
|-------------|---|------|----------|-----------------|----------|-----|
| control_ew full | {ctrl['tm_all']['n']} | {_fmt(ctrl['tm_all'].get('win_rate'))} | {_fmt(ctrl['tm_all'].get('avg_pnl_pct'))} | {_fmt(ctrl['tm_all'].get('avg_pnl_pct_wo_max'))} | {_fmt(ctrl['tm_all'].get('avg_days'))} | {_fmt(ctrl['tm_all'].get('profit_factor'))} |
| control_ew IS | {ctrl['tm_is']['n']} | {_fmt(ctrl['tm_is'].get('win_rate'))} | {_fmt(ctrl['tm_is'].get('avg_pnl_pct'))} | {_fmt(ctrl['tm_is'].get('avg_pnl_pct_wo_max'))} | {_fmt(ctrl['tm_is'].get('avg_days'))} | {_fmt(ctrl['tm_is'].get('profit_factor'))} |
| control_ew OOS | {ctrl['tm_oos']['n']} | {_fmt(ctrl['tm_oos'].get('win_rate'))} | {_fmt(ctrl['tm_oos'].get('avg_pnl_pct'))} | {_fmt(ctrl['tm_oos'].get('avg_pnl_pct_wo_max'))} | {_fmt(ctrl['tm_oos'].get('avg_days'))} | {_fmt(ctrl['tm_oos'].get('profit_factor'))} |
| mom212_long_q full | {long_q['tm_all']['n']} | {_fmt(long_q['tm_all'].get('win_rate'))} | {_fmt(long_q['tm_all'].get('avg_pnl_pct'))} | {_fmt(long_q['tm_all'].get('avg_pnl_pct_wo_max'))} | {_fmt(long_q['tm_all'].get('avg_days'))} | {_fmt(long_q['tm_all'].get('profit_factor'))} |
| mom212_long_q IS | {long_q['tm_is']['n']} | {_fmt(long_q['tm_is'].get('win_rate'))} | {_fmt(long_q['tm_is'].get('avg_pnl_pct'))} | {_fmt(long_q['tm_is'].get('avg_pnl_pct_wo_max'))} | {_fmt(long_q['tm_is'].get('avg_days'))} | {_fmt(long_q['tm_is'].get('profit_factor'))} |
| mom212_long_q OOS | {long_q['tm_oos']['n']} | {_fmt(long_q['tm_oos'].get('win_rate'))} | {_fmt(long_q['tm_oos'].get('avg_pnl_pct'))} | {_fmt(long_q['tm_oos'].get('avg_pnl_pct_wo_max'))} | {_fmt(long_q['tm_oos'].get('avg_days'))} | {_fmt(long_q['tm_oos'].get('profit_factor'))} |

## Blockers / caveats

1. Static liquid tape — not PIT large-cap membership (paper ≈ largest 20% mcap).
2. Equal-weight (not paper value-weight within liquid large-cap).
3. Trading-day 252/21 skip approx of calendar 12m/1m.
4. Value leg / true ValMom combo still blocked (no PIT BE/ME) — see feasibility stamp.
5. Clenow compare is cross-construction reference only.
6. Not gold / not DailyRun.

## Artifacts

- `compare.html` — sortable control vs candidate
- `BASELINE.md` / `SUMMARY.md` / `metrics.json`
- Closed + equity CSVs for control and long-Q
"""
    (out / "SUMMARY.md").write_text(summary, encoding="utf-8")

    html_path = write_html(
        out,
        univ_n=univ_n,
        symbols_used=symbols_used,
        ctrl=ctrl,
        long_q=long_q,
        ls=ls,
        clenow=clenow,
        verdict=verdict,
        verdict_note=verdict_note,
        bt_start=bt_start,
        bt_end=bt_end,
    )
    return html_path


def write_html(
    out: Path,
    *,
    univ_n: int,
    symbols_used: int,
    ctrl: dict[str, Any],
    long_q: dict[str, Any],
    ls: dict[str, Any],
    clenow: Optional[dict[str, Any]],
    verdict: str,
    verdict_note: str,
    bt_start: date,
    bt_end: date,
) -> Path:
    def cell(v: Any, nd: int = 2, money: bool = False) -> str:
        if money:
            return format_money(v)
        return _fmt(v, nd)

    # Compare rows: metric × arms (full / IS / OOS for primary arms)
    def row_triplet(label: str, getter) -> list[Any]:
        return [
            label,
            getter(ctrl, "full_m"),
            getter(ctrl, "is_m"),
            getter(ctrl, "oos_m"),
            getter(long_q, "full_m"),
            getter(long_q, "is_m"),
            getter(long_q, "oos_m"),
            getter(ls, "full_m"),
            getter(ls, "is_m"),
            getter(ls, "oos_m"),
        ]

    def eg(arm: dict, key: str, field: str) -> Any:
        return arm.get(key, {}).get(field)

    def tg(arm: dict, key: str, field: str) -> Any:
        return arm.get(key, {}).get(field)

    book_specs = [
        ("Ann ROR %", lambda a, k: eg(a, k, "ann_ror")),
        ("Max DD %", lambda a, k: eg(a, k, "max_dd")),
        ("Calmar", lambda a, k: eg(a, k, "calmar")),
        ("Sharpe (rf=0)", lambda a, k: eg(a, k, "sharpe")),
        ("Total return %", lambda a, k: eg(a, k, "total_ret_pct")),
        ("Equity days", lambda a, k: eg(a, k, "n_days")),
    ]
    trade_specs = [
        ("Closed trades N", "n", False),
        ("Wins", "wins", False),
        ("Losses", "losses", False),
        ("Win %", "win_rate", False),
        ("Avg PnL %", "avg_pnl_pct", False),
        ("Book AVG_PNL_PCT_WO_MAX", "avg_pnl_pct_wo_max", False),
        ("Expectancy %", "expectancy_pct", False),
        ("Avg win %", "avg_win_pct", False),
        ("Avg loss %", "avg_loss_pct", False),
        ("Profit factor", "profit_factor", False),
        ("Avg days held", "avg_days", False),
        ("Median days held", "median_days", False),
        ("Capital days", "capital_days", False),
        ("Profit / capital day", "profit_per_cap_day", True),
    ]

    head = (
        _sortable_th("Metric", "text")
        + _sortable_th("EW full", "num")
        + _sortable_th("EW IS", "num")
        + _sortable_th("EW OOS", "num")
        + _sortable_th("MOM212 long-Q full", "num")
        + _sortable_th("MOM212 long-Q IS", "num")
        + _sortable_th("MOM212 long-Q OOS", "num")
        + _sortable_th("MOM212 L/S full", "num")
        + _sortable_th("MOM212 L/S IS", "num")
        + _sortable_th("MOM212 L/S OOS", "num")
    )

    body_rows = []
    for label, getter in book_specs:
        if is_excluded_html_compare_label(label):
            continue
        vals = row_triplet(label, getter)
        body_rows.append(
            "<tr>"
            + "".join(f"<td>{html_mod.escape(str(vals[0]))}</td>")
            + "".join(f"<td>{cell(v)}</td>" for v in vals[1:])
            + "</tr>"
        )

    # Trade metrics: only EW + long-Q (L/S has no share trades)
    for label, field, money in trade_specs:
        if is_excluded_html_compare_label(label):
            continue
        vals = [
            label,
            tg(ctrl, "tm_all", field),
            tg(ctrl, "tm_is", field),
            tg(ctrl, "tm_oos", field),
            tg(long_q, "tm_all", field),
            tg(long_q, "tm_is", field),
            tg(long_q, "tm_oos", field),
            "—",
            "—",
            "—",
        ]
        body_rows.append(
            "<tr>"
            + f"<td>{html_mod.escape(label)}</td>"
            + "".join(
                f"<td>{cell(v, money=money) if v != '—' else '—'}</td>" for v in vals[1:]
            )
            + "</tr>"
        )

    # Deltas IS long-Q − EW
    def delta_row(label: str, a: Any, b: Any) -> str:
        try:
            da, db = float(a), float(b)
            d = da - db if np.isfinite(da) and np.isfinite(db) else float("nan")
        except (TypeError, ValueError):
            d = float("nan")
        return (
            f"<tr><td>{html_mod.escape(label)}</td>"
            f"<td>{cell(a)}</td><td>{cell(b)}</td><td>{cell(d)}</td></tr>"
        )

    d_head = (
        _sortable_th("IS metric", "text")
        + _sortable_th("MOM212 long-Q", "num")
        + _sortable_th("EW control", "num")
        + _sortable_th("Δ (cand−ctrl)", "num")
    )
    d_body = "".join(
        [
            delta_row("Ann ROR %", long_q["is_m"].get("ann_ror"), ctrl["is_m"].get("ann_ror")),
            delta_row("Max DD %", long_q["is_m"].get("max_dd"), ctrl["is_m"].get("max_dd")),
            delta_row("Calmar", long_q["is_m"].get("calmar"), ctrl["is_m"].get("calmar")),
            delta_row("Sharpe", long_q["is_m"].get("sharpe"), ctrl["is_m"].get("sharpe")),
            delta_row("Avg PnL %", long_q["tm_is"].get("avg_pnl_pct"), ctrl["tm_is"].get("avg_pnl_pct")),
            delta_row(
                "AVG_PNL_PCT_WO_MAX",
                long_q["tm_is"].get("avg_pnl_pct_wo_max"),
                ctrl["tm_is"].get("avg_pnl_pct_wo_max"),
            ),
            delta_row("Win %", long_q["tm_is"].get("win_rate"), ctrl["tm_is"].get("win_rate")),
            delta_row("Profit factor", long_q["tm_is"].get("profit_factor"), ctrl["tm_is"].get("profit_factor")),
        ]
    )

    clenow_html = "<p class=\"caption\">Clenow metrics.json not found — skipped.</p>"
    if clenow:
        ch = (
            _sortable_th("Slice", "text")
            + _sortable_th("Ann ROR %", "num")
            + _sortable_th("Max DD %", "num")
            + _sortable_th("Sharpe", "num")
            + _sortable_th("Calmar", "num")
            + _sortable_th("Avg PnL % (trades)", "num")
        )
        cb = ""
        for key, tkey in (("full", "tm_all"), ("is", "tm_is"), ("oos", "tm_oos")):
            m = clenow.get(key, {})
            tm = clenow.get(tkey, {})
            cb += (
                f"<tr><td>{key}</td><td>{cell(m.get('ann_ror'))}</td>"
                f"<td>{cell(m.get('max_dd'))}</td><td>{cell(m.get('sharpe'))}</td>"
                f"<td>{cell(m.get('calmar'))}</td><td>{cell(tm.get('avg_pnl_pct'))}</td></tr>"
            )
        clenow_html = f"""
<table class="sortable">
<thead><tr>{ch}</tr></thead>
<tbody>{cb}</tbody>
</table>
<p class="caption">Different construction (weekly Clenow) — reference only, not KEEP control.</p>
"""

    vclass = {"KEEP": "ok", "HOLD": "warn", "DISMISS": "bad"}.get(verdict, "warn")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate"/>
<title>MOM2–12 paper AB — {html_mod.escape(STAMP)}</title>
<style>
  :root {{
    --bg: #f7f6f2; --ink: #1c1b19; --muted: #5a574f; --line: #d4d0c4;
    --card: #ffffff; --accent: #2a4a5c; --accent-soft: #e8eef2;
    --ok: #2d6a4f; --ok-bg: #e8f2ec; --warn: #8a5a12; --warn-bg: #f7efe0;
    --bad: #9b2226; --bad-bg: #fdecea;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; font-family: "Segoe UI", "Helvetica Neue", sans-serif;
    color: var(--ink); background: linear-gradient(180deg, #efece4 0%, var(--bg) 160px);
    line-height: 1.45;
  }}
  main {{ max-width: 1180px; margin: 0 auto; padding: 28px 18px 64px; }}
  h1 {{ font-size: 1.45rem; margin: 0 0 6px; letter-spacing: -0.02em; }}
  h2 {{ font-size: 1.1rem; margin: 26px 0 8px; border-bottom: 1px solid var(--line); padding-bottom: 4px; }}
  .sub {{ color: var(--muted); margin: 0 0 16px; font-size: 0.95rem; }}
  .badge {{
    display: inline-block; font-size: 0.72rem; font-weight: 650; letter-spacing: 0.04em;
    text-transform: uppercase; padding: 2px 8px; border-radius: 3px;
    background: var(--warn-bg); color: var(--warn); border: 1px solid #e2c9a8;
    margin-bottom: 10px;
  }}
  .verdict {{
    background: var(--card); border: 1px solid var(--line); border-left: 4px solid var(--accent);
    padding: 12px 14px; margin: 0 0 18px;
  }}
  .verdict.ok {{ border-left-color: var(--ok); }}
  .verdict.warn {{ border-left-color: var(--warn); }}
  .verdict.bad {{ border-left-color: var(--bad); }}
  .note {{
    background: #f0eee6; border-left: 3px solid var(--accent);
    padding: 10px 12px; margin: 10px 0 16px; font-size: 0.92rem;
  }}
  table.sortable {{
    width: 100%; border-collapse: collapse; font-size: 0.84rem;
    background: var(--card); margin: 6px 0 8px;
  }}
  table.sortable th, table.sortable td {{
    border: 1px solid var(--line); padding: 6px 8px; text-align: left; vertical-align: top;
  }}
  table.sortable thead th {{ background: #ebe7dc; }}
  table.sortable tbody tr:nth-child(even) {{ background: #fbfaf7; }}
  .caption {{ color: var(--muted); font-size: 0.8rem; margin: 0 0 14px; }}
  code {{ font-size: 0.86em; background: #efece4; padding: 1px 4px; }}
  {SORTABLE_TH_CSS}
</style>
</head>
<body>
<main>
<span class="badge">Research AB · not gold · not DailyRun</span>
<h1>MOM2–12 monthly ranks — liquid {univ_n}</h1>
<p class="sub">
  Stamp <code>{html_mod.escape(STAMP)}</code> ·
  {bt_start.isoformat()} → {bt_end.isoformat()} ·
  symbols with OHLC {symbols_used}/{univ_n} ·
  Parent: <code>value_momentum_everywhere_20260904</code> feasibility path #1.
</p>

<div class="verdict {vclass}">
  <strong>Verdict (IS vs EW control): {html_mod.escape(verdict)}</strong><br/>
  {html_mod.escape(verdict_note)}
  <div style="margin-top:8px;font-size:0.9rem;color:var(--muted)">
    OOS is report-only. No DailyRun wire. No OOS retune.
  </div>
</div>

<div class="note">
  <strong>Control:</strong> equal-weight liquid-universe buy-hold (monthly EW rebalance).<br/>
  <strong>Candidate:</strong> MOM2–12 long top quintile ({TOP_FRAC:.0%}) EW, month-end signal → next open fill,
  {SLIPPAGE_BPS:.0f} bps one-way slip.<br/>
  <strong>Diagnostic:</strong> long–short top−bottom quintile factor sleeve.<br/>
  IS cut = <code>2024-01-01</code>. Click column headers to sort.
</div>

<h2>Book + trade metrics (canonical set)</h2>
<p class="caption">Click column headers to sort. Total/Sheet PnL $ omitted per house HTML compare filter.</p>
<table class="sortable">
<thead><tr>{head}</tr></thead>
<tbody>
{''.join(body_rows)}
</tbody>
</table>

<h2>IS deltas — long-Q vs EW control</h2>
<table class="sortable">
<thead><tr>{d_head}</tr></thead>
<tbody>{d_body}</tbody>
</table>

<h2>Clenow MOM reference (cross-construction)</h2>
{clenow_html}

<h2>Freeze / caveats</h2>
<ul>
  <li>Signal: <code>Close[t−{SKIP_BARS}] / Close[t−{LOOKBACK_BARS}] − 1</code> (trading-day MOM2–12).</li>
  <li>Universe: static liquid ADV$2m ({univ_n}) — not PIT paper large-cap; EW not value-weight.</li>
  <li>Value / ValMom combo still blocked (no PIT BE/ME) — OHLC momentum leg only.</li>
  <li>Research candidate ≠ gold ≠ DailyRun.</li>
</ul>
<p class="caption">Re-run: <code>python tools/mom_mom212_paper_ab.py --out drive/paul_experiments/{STAMP}</code></p>
</main>
{SORT_JS}
</body>
</html>
"""
    path = out / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description="Paper MOM2–12 monthly AB on liquid 763")
    ap.add_argument("--universe", type=Path, default=DEFAULT_UNIV)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    ap.add_argument("--start", type=str, default="2010-01-04")
    ap.add_argument("--end", type=str, default=None)
    ap.add_argument("--limit", type=int, default=0, help="Smoke: first N symbols")
    args = ap.parse_args()

    univ = load_universe(args.universe)
    if args.limit and args.limit > 0:
        univ = univ[: args.limit]
    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date() if args.end else None

    print(f"Universe {len(univ)} from {args.universe}")
    print(f"Loading OHLC from {args.db} ...")
    cal, close, open_, symbols = load_ohlc_panel(args.db, univ, start=start, end=end)
    print(f"Panel: {len(cal)} days x {len(symbols)} symbols ({cal[0].date()} -> {cal[-1].date()})")

    me = month_end_indices(cal)
    # First usable month-end needs LOOKBACK_BARS history
    bt_start_i = next((i for i in me if i >= LOOKBACK_BARS), None)
    if bt_start_i is None:
        raise RuntimeError("No month-end after MOM2–12 warmup")
    print(f"Month-ends: {len(me)}; first usable signal i={bt_start_i} ({cal[bt_start_i].date()})")

    print("Running control EW ...")
    ctrl = run_long_sleeve(
        arm="control_ew",
        cal=cal,
        close=close,
        open_=open_,
        symbols=symbols,
        me_idx=me,
        pick_fn=pick_all_ew,
        bt_start_i=bt_start_i,
    )
    print(
        f"  control final={ctrl['final_equity']:.2f} "
        f"IS AnnROR={_fmt(ctrl['is_m'].get('ann_ror'))} "
        f"trades={ctrl['tm_all']['n']}"
    )

    print("Running MOM2-12 long quintile ...")
    long_q = run_long_sleeve(
        arm="mom212_long_q",
        cal=cal,
        close=close,
        open_=open_,
        symbols=symbols,
        me_idx=me,
        pick_fn=pick_top_quintile,
        bt_start_i=bt_start_i,
    )
    print(
        f"  long_q final={long_q['final_equity']:.2f} "
        f"IS AnnROR={_fmt(long_q['is_m'].get('ann_ror'))} "
        f"trades={long_q['tm_all']['n']}"
    )

    print("Running MOM2-12 long-short quintile factor ...")
    ls = run_long_short_factor(cal=cal, close=close, me_idx=me, bt_start_i=bt_start_i)
    print(
        f"  ls final={ls.get('final_equity', float('nan')):.2f} "
        f"IS AnnROR={_fmt(ls.get('is_m', {}).get('ann_ror'))}"
    )

    clenow = load_clenow_ref()
    verdict, note = verdict_from_is(ctrl, long_q)
    print(f"Verdict: {verdict} - {note}")

    bt_start = date.fromisoformat(ctrl["full_m"]["start"])
    bt_end = date.fromisoformat(ctrl["full_m"]["end"])
    html_path = write_stamp(
        args.out,
        univ_path=args.universe,
        univ_n=len(load_universe(args.universe)) if not args.limit else len(univ),
        symbols_used=len(symbols),
        ctrl=ctrl,
        long_q=long_q,
        ls=ls,
        clenow=clenow,
        verdict=verdict,
        verdict_note=note,
        bt_start=bt_start,
        bt_end=bt_end,
    )
    print(f"Wrote {args.out}")
    print(f"HTML {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
