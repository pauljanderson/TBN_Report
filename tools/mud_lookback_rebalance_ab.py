#!/usr/bin/env python3
"""MUD (Most Up / Most Down) — Thorp short-term reversal lookback×rebalance grid.

Research-only. No DailyRun wire. No commit.

Rules (frozen in stamp BASELINE.md):
  - Rank by split/div-adjusted % return over lookback L trading days.
  - Long most-down decile; short most-up decile (top/bottom 10% by count).
  - Market-neutral: equal dollar long vs short; equal-weight within each side.
  - Rebalance every R trading days (full rotate to target sleeves).
  - No stop / target / SD band. Zero commissions; borrow ignored.

Usage:
  python tools/mud_lookback_rebalance_ab.py
  python tools/mud_lookback_rebalance_ab.py --workers 4
  python tools/mud_lookback_rebalance_ab.py --limit 200   # smoke
  python tools/mud_lookback_rebalance_ab.py --lookbacks 6,7,8,9 --merge --workers 4
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
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
    ann_ror_from_closed,
)
from report_page_extras import (  # noqa: E402
    RESPONSIVE_TABLE_CSS,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)

STAMP = "mud_lookback_rebalance_20261005"
OUT_DIR = _PE / STAMP
DEFAULT_DB = _REPO / "data" / "ohlcv.duckdb"
IS_CUT = date(2024, 1, 1)

# Full research grid: L=1..5,6..9,10,15,20 (merge adds; do not recompute kept cells).
LOOKBACKS = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20)
REBALANCES = (1, 2, 3, 5, 10)  # include R=3 (cheap)
# Keep warehouse filter stable vs original L<=20 run (do not shrink min_bars on subset merges).
PANEL_MIN_BARS = max(LOOKBACKS) + 40
DECILE_FRAC = 0.10
INITIAL_CAPITAL = float(DEFAULT_INITIAL_ACCOUNT)  # 500k; half long / half short
MIN_RANK_NAMES = 40
EXCLUDE_SYMBOLS = frozenset({"SPY"})
COMMISSIONS = 0.0  # research start; document
BORROW_MODELED = False


# ---------------------------------------------------------------------------
# Sortable table helpers (monthly-report pattern)
# ---------------------------------------------------------------------------
def sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


SORTABLE_TABLE_SCRIPT = r"""
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


@dataclass
class Trade:
    symbol: str
    side: str  # long | short
    entry_date: date
    exit_date: date
    entry_px: float
    exit_px: float
    shares: float
    pnl_dollars: float
    pnl_pct: float
    days_held: int
    exit_reason: str
    entry_notional: float
    lookback: int
    rebalance: int


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def load_panel(
    db_path: Path,
    *,
    min_bars: int,
    limit: Optional[int] = None,
    start: Optional[date] = None,
) -> tuple[pd.DatetimeIndex, np.ndarray, np.ndarray, list[str]]:
    con = duckdb.connect(str(db_path), read_only=True)
    df = con.execute(
        """
        SELECT symbol, date, open, close
        FROM prices
        WHERE symbol IS NOT NULL
        ORDER BY date, symbol
        """
    ).fetchdf()
    con.close()
    if df.empty:
        raise RuntimeError(f"No rows in {db_path}")
    df["date"] = pd.to_datetime(df["date"])
    df["symbol"] = df["symbol"].astype(str).str.upper()
    df = df[~df["symbol"].isin(EXCLUDE_SYMBOLS)]
    if start is not None:
        df = df[df["date"] >= pd.Timestamp(start)]

    close_w = df.pivot(index="date", columns="symbol", values="close").sort_index()
    open_w = df.pivot(index="date", columns="symbol", values="open").sort_index()
    keep = [c for c in close_w.columns if int(close_w[c].notna().sum()) >= min_bars]
    keep.sort()
    if limit is not None and limit > 0:
        keep = keep[: int(limit)]
    close_w = close_w[keep]
    open_w = open_w.reindex(columns=keep)
    return close_w.index, close_w.to_numpy(dtype=float), open_w.to_numpy(dtype=float), keep


def lookback_returns(close: np.ndarray, t: int, L: int) -> np.ndarray:
    """% return over L trading days ending at bar t (signal close)."""
    out = np.full(close.shape[1], np.nan, dtype=float)
    if t < L:
        return out
    p0 = close[t - L, :]
    p1 = close[t, :]
    ok = np.isfinite(p0) & np.isfinite(p1) & (p0 > 0) & (p1 > 0)
    out[ok] = p1[ok] / p0[ok] - 1.0
    return out


def pick_deciles(
    scores: np.ndarray, px: np.ndarray
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Return (longs=most-down, shorts=most-up) as (sym_i, score) lists."""
    ok = np.isfinite(scores) & np.isfinite(px) & (px > 0)
    idx = np.where(ok)[0]
    if len(idx) < MIN_RANK_NAMES:
        return [], []
    sc = scores[idx]
    order = np.argsort(sc)  # ascending: most down first
    n = max(1, int(math.floor(len(idx) * DECILE_FRAC)))
    downs = idx[order[:n]]
    ups = idx[order[-n:]]
    longs = [(int(j), float(scores[j])) for j in downs]
    shorts = [(int(j), float(scores[j])) for j in ups]
    return longs, shorts


# ---------------------------------------------------------------------------
# Backtest one (L, R) cell
# ---------------------------------------------------------------------------
def run_mud_cell(
    *,
    cal: pd.DatetimeIndex,
    close: np.ndarray,
    open_: np.ndarray,
    symbols: list[str],
    lookback: int,
    rebalance: int,
    initial_capital: float = INITIAL_CAPITAL,
) -> dict[str, Any]:
    """Dollar-neutral MUD sleeve. Signal close → fill next open. Full rotate every R."""
    T, _S = close.shape
    arm = f"L{lookback}_R{rebalance}"
    half = initial_capital / 2.0
    cash = float(initial_capital)
    # holdings: (sym_i, shares, side, entry_date, entry_px, entry_notional)
    holdings: list[tuple[int, float, str, date, float, float]] = []
    trades: list[Trade] = []
    equity_rows: list[dict[str, Any]] = []

    # Rebalance signal bars: every R days after warmup
    warmup = lookback + 1
    signal_idxs = list(range(warmup, T - 1, rebalance))  # need next open for fill
    fill_to_signal = {si + 1: si for si in signal_idxs if si + 1 < T}
    fill_set = set(fill_to_signal.keys())
    if not fill_set:
        return {"arm": arm, "lookback": lookback, "rebalance": rebalance, "error": "no fills"}

    def mtm(ti: int) -> float:
        eq = cash
        for sj, sh, side, *_rest in holdings:
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
        kept: list[tuple[int, float, str, date, float, float]] = []
        for sj, sh, side, ed, ep, enot in holdings:
            px = px_row[sj]
            if not (np.isfinite(px) and px > 0):
                px = close[ti, sj]
            if not (np.isfinite(px) and px > 0):
                kept.append((sj, sh, side, ed, ep, enot))
                continue
            fill = float(px)  # 0 commission / 0 slip
            xd = cal[ti].date()
            if side == "long":
                proceeds = sh * fill
                cash += proceeds
                pnl = proceeds - enot
                pnl_pct = (fill / ep - 1.0) * 100.0 if ep else 0.0
            else:
                # cover short: pay fill; short opened with +enot cash
                cost = sh * fill
                cash -= cost
                pnl = enot - cost
                pnl_pct = (ep / fill - 1.0) * 100.0 if fill else 0.0
            trades.append(
                Trade(
                    symbol=symbols[sj],
                    side=side,
                    entry_date=ed,
                    exit_date=xd,
                    entry_px=ep,
                    exit_px=fill,
                    shares=sh,
                    pnl_dollars=pnl,
                    pnl_pct=pnl_pct,
                    days_held=max(1, (xd - ed).days),
                    exit_reason=reason,
                    entry_notional=enot,
                    lookback=lookback,
                    rebalance=rebalance,
                )
            )
        holdings = kept

    first_fill = min(fill_set)
    for ti in range(first_fill, T):
        if ti in fill_set:
            si = fill_to_signal[ti]
            liquidate_all(ti, "rebalance", use_open=True)
            scores = lookback_returns(close, si, lookback)
            longs, shorts = pick_deciles(scores, close[si, :])
            # Rebuild cash-neutral sleeves from current cash (should ~ initial after flat)
            # After full liquidate, cash ≈ equity; split half/half of mtm cash.
            side_budget = cash / 2.0 if cash > 0 else half
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
                holdings.append((sj, shares, "long", cal[ti].date(), fill, cost))
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
                holdings.append((sj, shares, "short", cal[ti].date(), fill, proceeds))

        equity_rows.append(
            {
                "date": cal[ti].date().isoformat(),
                "equity": mtm(ti),
                "cash": cash,
                "n_positions": len(holdings),
            }
        )

    if holdings:
        liquidate_all(T - 1, "end_of_backtest", use_open=False)
        if equity_rows:
            equity_rows[-1]["equity"] = cash
            equity_rows[-1]["cash"] = cash
            equity_rows[-1]["n_positions"] = 0

    return pack_cell(arm, lookback, rebalance, equity_rows, trades, initial_capital)


def _max_dd_pct(equity: pd.Series) -> float:
    if equity.empty:
        return float("nan")
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(-dd.min() * 100.0)


def _equity_sharpe(equity: pd.Series) -> float:
    rets = equity.pct_change().dropna()
    if len(rets) < 3 or float(rets.std(ddof=1)) <= 0:
        return float("nan")
    return float(rets.mean() / rets.std(ddof=1) * math.sqrt(252.0))


def trade_slice_metrics(trades: list[Trade]) -> dict[str, Any]:
    if not trades:
        return {
            "n": 0,
            "win_rate": float("nan"),
            "avg_pnl_pct": float("nan"),
            "avg_days": float("nan"),
            "profit_factor": float("nan"),
            "total_pnl": 0.0,
            "slot_cash": float("nan"),
            "ann_ror": float("nan"),
            "n_long": 0,
            "n_short": 0,
        }
    pnls = np.array([t.pnl_pct for t in trades], dtype=float)
    dollars = np.array([t.pnl_dollars for t in trades], dtype=float)
    days = np.array([t.days_held for t in trades], dtype=float)
    notionals = np.array([t.entry_notional for t in trades], dtype=float)
    slot = float(np.mean(notionals))
    gross_win = float(dollars[dollars > 0].sum()) if np.any(dollars > 0) else 0.0
    gross_loss = float(abs(dollars[dollars < 0].sum())) if np.any(dollars < 0) else 0.0
    pf = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else float("nan"))
    total = float(dollars.sum())
    avg_days = float(days.mean())
    ann = ann_ror_from_closed(
        total_pnl=total,
        n_trades=len(trades),
        avg_days_held=avg_days,
        brt_cash=slot,
    )
    return {
        "n": len(trades),
        "win_rate": 100.0 * float((pnls > 0).mean()),
        "avg_pnl_pct": float(pnls.mean()),
        "avg_days": avg_days,
        "profit_factor": pf,
        "total_pnl": total,
        "slot_cash": slot,
        "ann_ror": float(ann) if ann is not None else float("nan"),
        "n_long": sum(1 for t in trades if t.side == "long"),
        "n_short": sum(1 for t in trades if t.side == "short"),
    }


def equity_slice(eq_df: pd.DataFrame, start: date, end: date) -> dict[str, Any]:
    sub = eq_df[(eq_df["d"] >= start) & (eq_df["d"] <= end)].copy()
    if len(sub) < 2:
        return {
            "n_days": len(sub),
            "max_dd": float("nan"),
            "sharpe": float("nan"),
            "total_ret_pct": float("nan"),
            "end_equity": float("nan"),
        }
    e0 = float(sub["equity"].iloc[0])
    e1 = float(sub["equity"].iloc[-1])
    return {
        "n_days": len(sub),
        "max_dd": _max_dd_pct(sub["equity"]),
        "sharpe": _equity_sharpe(sub["equity"]),
        "total_ret_pct": (e1 / e0 - 1.0) * 100.0 if e0 else float("nan"),
        "end_equity": e1,
        "start": sub["d"].iloc[0].isoformat(),
        "end": sub["d"].iloc[-1].isoformat(),
    }


def pack_cell(
    arm: str,
    lookback: int,
    rebalance: int,
    equity_rows: list[dict],
    trades: list[Trade],
    initial_capital: float,
) -> dict[str, Any]:
    eq_df = pd.DataFrame(equity_rows)
    if eq_df.empty:
        return {
            "arm": arm,
            "lookback": lookback,
            "rebalance": rebalance,
            "error": "empty equity",
            "tm_full": trade_slice_metrics([]),
            "tm_is": trade_slice_metrics([]),
            "tm_oos": trade_slice_metrics([]),
        }
    eq_df["d"] = pd.to_datetime(eq_df["date"]).dt.date
    is_trades = [t for t in trades if t.entry_date < IS_CUT]
    oos_trades = [t for t in trades if t.entry_date >= IS_CUT]
    tm_full = trade_slice_metrics(trades)
    tm_is = trade_slice_metrics(is_trades)
    tm_oos = trade_slice_metrics(oos_trades)
    eq_full = equity_slice(eq_df, eq_df["d"].iloc[0], eq_df["d"].iloc[-1])
    eq_is = equity_slice(eq_df, eq_df["d"].iloc[0], date(2023, 12, 31))
    eq_oos = equity_slice(eq_df, IS_CUT, eq_df["d"].iloc[-1])
    return {
        "arm": arm,
        "lookback": lookback,
        "rebalance": rebalance,
        "initial_capital": initial_capital,
        "n_trades_total": len(trades),
        "tm_full": tm_full,
        "tm_is": tm_is,
        "tm_oos": tm_oos,
        "eq_full": eq_full,
        "eq_is": eq_is,
        "eq_oos": eq_oos,
        "final_equity": float(eq_df["equity"].iloc[-1]),
        "trades": trades,
        "equity_rows": equity_rows,
    }


# Worker entry (picklable): receives paths + cell knobs, reloads panel (or uses shared via fork — Windows spawn)
_WORKER_STATE: dict[str, Any] = {}


def _init_worker(payload: dict[str, Any]) -> None:
    _WORKER_STATE.clear()
    _WORKER_STATE.update(payload)


def _run_cell_worker(args: tuple[int, int]) -> dict[str, Any]:
    L, R = args
    cal = _WORKER_STATE["cal"]
    close = _WORKER_STATE["close"]
    open_ = _WORKER_STATE["open"]
    symbols = _WORKER_STATE["symbols"]
    print(f"  start {L=} {R=}", flush=True)
    out = run_mud_cell(
        cal=cal,
        close=close,
        open_=open_,
        symbols=symbols,
        lookback=L,
        rebalance=R,
    )
    # Drop heavy arrays before IPC
    trades = out.pop("trades", [])
    out.pop("equity_rows", None)
    out["trade_rows"] = [
        {
            "ARM": f"L{t.lookback}_R{t.rebalance}",
            "SYMBOL": t.symbol,
            "SIDE": t.side,
            "ENTRY_DATE": t.entry_date.isoformat(),
            "EXIT_DATE": t.exit_date.isoformat(),
            "ENTRY_PX": round(t.entry_px, 6),
            "EXIT_PX": round(t.exit_px, 6),
            "SHARES": round(t.shares, 6),
            "PNL_DOLLARS": round(t.pnl_dollars, 4),
            "PNL_PCT": round(t.pnl_pct, 6),
            "DAYS_HELD": t.days_held,
            "EXIT_TYPE": t.exit_reason,
            "ENTRY_NOTIONAL": round(t.entry_notional, 4),
            "LOOKBACK": t.lookback,
            "REBALANCE": t.rebalance,
        }
        for t in trades
    ]
    print(
        f"  done L{L}_R{R} N={out['tm_full']['n']} "
        f"IS AnnROR={_fmt(out['tm_is'].get('ann_ror'))} "
        f"OOS AnnROR={_fmt(out['tm_oos'].get('ann_ror'))}",
        flush=True,
    )
    return out


def _fmt(x: Any, nd: int = 2) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if not np.isfinite(v):
        return "—"
    if abs(v) >= 1000:
        return f"{v:,.{nd}f}"
    return f"{v:.{nd}f}"


def _fmt_pf(x: Any) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if not np.isfinite(v):
        return "—"
    if math.isinf(v):
        return "∞"
    return f"{v:.2f}"


# ---------------------------------------------------------------------------
# Verdict (IS quality only; OOS report-only)
# ---------------------------------------------------------------------------
def _safe_float(x: Any, default: float = float("nan")) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return v if np.isfinite(v) else default


def verdict_grid(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Label KEEP/HOLD/DISMISS vs grid median IS Ann ROR — one-knob caution."""
    is_ann = []
    for r in rows:
        fv = _safe_float((r.get("tm_is") or {}).get("ann_ror"))
        if np.isfinite(fv):
            is_ann.append(fv)
    med = float(np.median(is_ann)) if is_ann else float("nan")
    # Top IS Ann ROR among cells with N_is >= 200 and PF>1 as quality filter
    ranked = sorted(
        rows,
        key=lambda r: _safe_float((r.get("tm_is") or {}).get("ann_ror"), -1e18),
        reverse=True,
    )
    best_arm = ranked[0]["arm"] if ranked else None
    out = []
    for r in rows:
        tm_is = r.get("tm_is") or {}
        tm_oos = r.get("tm_oos") or {}
        a = _safe_float(tm_is.get("ann_ror"))
        n_is = int(tm_is.get("n") or 0)
        pf = _safe_float(tm_is.get("profit_factor"))
        oos = _safe_float(tm_oos.get("ann_ror"))
        note_parts = [f"IS AnnROR={_fmt(a)} vs grid median {_fmt(med)}; N_is={n_is}"]
        if np.isfinite(oos):
            note_parts.append(f"OOS AnnROR={_fmt(oos)} (report-only)")
        # Selection-bias aware: at most one LEAN KEEP for best IS cell if quality ok
        if r["arm"] == best_arm and n_is >= 200 and np.isfinite(a) and a > 0 and (
            not np.isfinite(pf) or pf >= 1.0
        ):
            # Soften if OOS collapses hard
            if np.isfinite(oos) and oos < -5.0:
                verd = "HOLD"
                note_parts.append("best IS but OOS soft → HOLD (no OOS retune)")
            else:
                verd = "LEAN KEEP"
                note_parts.append(
                    "best IS Ann ROR in grid; research candidate only — "
                    "in-sample selection across L×R; not gold / not DailyRun"
                )
        elif n_is < 50 or (np.isfinite(a) and a < -10):
            verd = "DISMISS"
        elif np.isfinite(a) and a > med + 2 and n_is >= 100:
            verd = "HOLD"
            note_parts.append("above median IS but not unique favorite")
        else:
            verd = "HOLD"
        r2 = dict(r)
        r2["verdict"] = verd
        r2["verdict_note"] = "; ".join(note_parts)
        out.append(r2)
    return out


def _parse_int_list(s: str, default: tuple[int, ...]) -> tuple[int, ...]:
    if not s or not str(s).strip():
        return default
    vals = []
    for part in str(s).split(","):
        part = part.strip()
        if not part:
            continue
        vals.append(int(part))
    if not vals:
        return default
    return tuple(vals)


def load_existing_metrics(out: Path) -> list[dict[str, Any]]:
    path = out / "metrics.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return []
    return data


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------
ORIGINAL_REQUEST = (
    "awesome - let's do 6 through 9"
)

PRIOR_REQUEST_L1_4 = (
    "great - thanks. I would like to try again this time with a one day lookback. "
    "so let's do 1 through 5 (we already have 5, so add 1, 2, 3, and 4, please)"
)

PRIOR_REQUEST = (
    "OK great - let's run this through as a system, and show me the results. "
    "maybe we try different windows to look back on, 5-day, 10-day, 15-day, 20-day. "
    "and different intervals to re-balance: daily, every 2 days, etc. "
    "Let's look at in sample results and then OOS and full book. we call this system MUD"
)

PLAIN_ENGLISH = (
    "MUD is a short-term reversal book: buy the names that fell the most recently, "
    "short the ones that rose the most, and keep the two sides the same size in dollars. "
    "Prior cells on this stamp (lookbacks 1–5, 10, 15, 20) are kept as-is. This pass fills "
    "the gap with lookbacks 6 / 7 / 8 / 9 trading days and the same rebalance every "
    "1 / 2 / 3 / 5 / 10 trading days. Below: full book, in-sample (entry before 2024-01-01), "
    "and out-of-sample (entry on/after that date). Annualized rate of return (Ann ROR) uses "
    "the house closed-trade formula with slot cash = mean entry notional (matches trade dollars). "
    "Judge new cells against the prior lean keep L5_R1 on IS quality; OOS is report-only."
)


def write_baseline(out: Path, *, univ_n: int, db_path: Path, cells: list[dict]) -> None:
    lean = [c for c in cells if c.get("verdict") == "LEAN KEEP"]
    lean_txt = lean[0]["arm"] if lean else "(none — HOLD grid)"
    lines = [
        f"# BASELINE — MUD (Most Up / Most Down) `{STAMP}`",
        "",
        "## What you asked",
        "",
        f"> {ORIGINAL_REQUEST}",
        "",
        "Prior ask (same stamp, L=1–4 added; earlier cells kept):",
        "",
        f"> {PRIOR_REQUEST_L1_4}",
        "",
        "Earlier ask (same stamp, L=5/10/15/20 grid kept):",
        "",
        f"> {PRIOR_REQUEST}",
        "",
        "## In plain English",
        "",
        PLAIN_ENGLISH,
        "",
        "## Freeze",
        "",
        "| Knob | Value |",
        "|---|---|",
        "| System | MUD (Most Up / Most Down) — Thorp short-term reversal |",
        "| Rank | Split/div-adjusted close-to-close % return over L trading days |",
        "| Long sleeve | Most-down decile (bottom 10% by count) |",
        "| Short sleeve | Most-up decile (top 10% by count) |",
        f"| Neutrality | Equal dollar long vs short; EW within side; seed ${INITIAL_CAPITAL:,.0f} |",
        "| Entry | Signal at close of rebalance bar; fill next open |",
        "| Exit / rebalance | Full rotate every R trading days; no stop/target/SD |",
        f"| Lookbacks L | {', '.join(str(x) for x in LOOKBACKS)} |",
        f"| Rebalance R | {', '.join(str(x) for x in REBALANCES)} (includes R=3) |",
        f"| Universe | Full `prices` warehouse minus SPY; min bars ≥ {PANEL_MIN_BARS}; N={univ_n} |",
        f"| Price DB | `{db_path.as_posix()}` (~2010→latest) |",
        f"| Commissions | {COMMISSIONS} (research start; no house pairs fee applied) |",
        f"| Borrow / short realism | {'modeled' if BORROW_MODELED else 'ignored (research)'} |",
        "| Shares | Fractional OK for neutrality (document); whole-share rounding not forced |",
        "| IS cut | `entry_date < 2024-01-01` |",
        "| OOS cut | `entry_date >= 2024-01-01` |",
        "| DailyRun | **NOT wired** — research stamp only |",
        "",
        "## Selection bias label",
        "",
        "Choosing a favorite cell from this L×R table is **in-sample selection** on the "
        "same universe/history. OOS is **report-only** — do not retune L or R from OOS. "
        "Prior provisional lean was **L5_R1**; re-score the full merged grid after adding L=6..9. "
        f"Provisional IS lean (if any): **{lean_txt}**. Research candidate ≠ gold ≠ DailyRun.",
        "",
        "## Ann ROR",
        "",
        "House formula `compare_format.ann_ror_from_closed` with "
        "`brt_cash` = mean entry notional of closed trades in that slice "
        "(matches trade dollars; not a sheet $47,500 bug).",
        "",
        "## Grid verdicts (IS quality)",
        "",
    ]
    for c in sorted(cells, key=lambda x: (x["lookback"], x["rebalance"])):
        lines.append(
            f"- `{c['arm']}`: **{c.get('verdict', 'HOLD')}** — {c.get('verdict_note', '')}"
        )
    lines.append("")
    (out / "BASELINE.md").write_text("\n".join(lines), encoding="utf-8")


def write_summary_csv(out: Path, cells: list[dict]) -> Path:
    rows = []
    for c in cells:
        for slice_name, tm, eq in (
            ("full", c["tm_full"], c["eq_full"]),
            ("IS", c["tm_is"], c["eq_is"]),
            ("OOS", c["tm_oos"], c["eq_oos"]),
        ):
            rows.append(
                {
                    "arm": c["arm"],
                    "lookback": c["lookback"],
                    "rebalance": c["rebalance"],
                    "slice": slice_name,
                    "N": tm.get("n"),
                    "WR_pct": tm.get("win_rate"),
                    "avg_pnl_pct": tm.get("avg_pnl_pct"),
                    "avg_days": tm.get("avg_days"),
                    "PF": tm.get("profit_factor"),
                    "total_pnl": tm.get("total_pnl"),
                    "slot_cash": tm.get("slot_cash"),
                    "ann_ror": tm.get("ann_ror"),
                    "max_dd": eq.get("max_dd"),
                    "sharpe": eq.get("sharpe"),
                    "equity_total_ret_pct": eq.get("total_ret_pct"),
                    "verdict": c.get("verdict"),
                }
            )
    path = out / "summary_grid.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def write_compare_html(out: Path, cells: list[dict], *, univ_n: int) -> Path:
    cells_s = sorted(cells, key=lambda c: (c["lookback"], c["rebalance"]))
    # Heat-style body rows
    body_rows = []
    for c in cells_s:
        tm_f, tm_i, tm_o = c["tm_full"], c["tm_is"], c["tm_oos"]
        eq_f, eq_i, eq_o = c["eq_full"], c["eq_is"], c["eq_oos"]
        verd = c.get("verdict", "HOLD")
        cls = "lean" if verd == "LEAN KEEP" else ("dismiss" if verd == "DISMISS" else "")
        body_rows.append(
            "<tr class='{cls}'>"
            "<td>{arm}</td><td>{L}</td><td>{R}</td><td>{verd}</td>"
            "<td>{ann_f}</td><td>{ann_i}</td><td>{ann_o}</td>"
            "<td>{n_f}</td><td>{n_i}</td><td>{n_o}</td>"
            "<td>{wr_i}</td><td>{avg_i}</td><td>{days_i}</td>"
            "<td>{pf_i}</td><td>{dd_i}</td><td>{sh_i}</td>"
            "<td>{wr_o}</td><td>{avg_o}</td><td>{dd_o}</td><td>{sh_o}</td>"
            "<td>{slot}</td>"
            "</tr>".format(
                cls=cls,
                arm=html_mod.escape(c["arm"]),
                L=c["lookback"],
                R=c["rebalance"],
                verd=html_mod.escape(verd),
                ann_f=_fmt(tm_f.get("ann_ror")),
                ann_i=_fmt(tm_i.get("ann_ror")),
                ann_o=_fmt(tm_o.get("ann_ror")),
                n_f=tm_f.get("n", 0),
                n_i=tm_i.get("n", 0),
                n_o=tm_o.get("n", 0),
                wr_i=_fmt(tm_i.get("win_rate")),
                avg_i=_fmt(tm_i.get("avg_pnl_pct")),
                days_i=_fmt(tm_i.get("avg_days")),
                pf_i=_fmt_pf(tm_i.get("profit_factor")),
                dd_i=_fmt(eq_i.get("max_dd")),
                sh_i=_fmt(eq_i.get("sharpe")),
                wr_o=_fmt(tm_o.get("win_rate")),
                avg_o=_fmt(tm_o.get("avg_pnl_pct")),
                dd_o=_fmt(eq_o.get("max_dd")),
                sh_o=_fmt(eq_o.get("sharpe")),
                slot=_fmt(tm_f.get("slot_cash"), 0),
            )
        )

    # Best IS cells (top 5 by IS Ann ROR)
    by_is = sorted(
        cells_s,
        key=lambda c: float(c["tm_is"].get("ann_ror") or float("-inf")),
        reverse=True,
    )
    highlights = []
    for c in by_is[:5]:
        highlights.append(
            f"<li><code>{html_mod.escape(c['arm'])}</code> — IS Ann ROR {_fmt(c['tm_is'].get('ann_ror'))}%, "
            f"N_is={c['tm_is'].get('n')}, WR {_fmt(c['tm_is'].get('win_rate'))}%, "
            f"PF {_fmt_pf(c['tm_is'].get('profit_factor'))}; "
            f"OOS Ann ROR {_fmt(c['tm_oos'].get('ann_ror'))}% (report-only); "
            f"verdict <strong>{html_mod.escape(c.get('verdict', 'HOLD'))}</strong></li>"
        )

    headers = "".join(
        [
            sortable_th("Arm", "text"),
            sortable_th("L", "num"),
            sortable_th("R", "num"),
            sortable_th("Verdict", "text"),
            sortable_th("Ann ROR full %", "num"),
            sortable_th("Ann ROR IS %", "num"),
            sortable_th("Ann ROR OOS %", "num"),
            sortable_th("N full", "num"),
            sortable_th("N IS", "num"),
            sortable_th("N OOS", "num"),
            sortable_th("WR IS %", "num"),
            sortable_th("Avg% IS", "num"),
            sortable_th("Days IS", "num"),
            sortable_th("PF IS", "num"),
            sortable_th("MaxDD IS %", "num"),
            sortable_th("Sharpe IS", "num"),
            sortable_th("WR OOS %", "num"),
            sortable_th("Avg% OOS", "num"),
            sortable_th("MaxDD OOS %", "num"),
            sortable_th("Sharpe OOS", "num"),
            sortable_th("Slot $", "num"),
        ]
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>MUD lookback × rebalance — {STAMP}</title>
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 16px; color: #1a1a1a; background: #faf9f7; line-height: 1.45; }}
h1 {{ font-size: 1.45rem; margin: 0 0 8px; }}
h2 {{ font-size: 1.15rem; margin: 22px 0 8px; }}
.callout {{ background: #eef3f8; border-left: 4px solid #3b6ea5; padding: 10px 14px; margin: 12px 0; }}
.callout h2 {{ margin-top: 0; }}
.note {{ color: #444; font-size: 0.95rem; }}
.meta {{ color: #555; font-size: 0.9rem; margin-bottom: 12px; }}
table.sortable {{ border-collapse: collapse; background: #fff; font-size: 13px; }}
table.sortable th, table.sortable td {{ border: 1px solid #d0d0d0; padding: 5px 8px; text-align: right; }}
table.sortable th:first-child, table.sortable td:first-child {{ text-align: left; }}
table.sortable thead th {{ background: #f0eee8; }}
tr.lean {{ background: #e8f5e9; }}
tr.dismiss {{ background: #fce8e6; }}
code {{ background: #f0eee8; padding: 1px 4px; }}
{SORTABLE_TH_CSS}
{RESPONSIVE_TABLE_CSS}
</style>
</head>
<body>
<h1>MUD (Most Up / Most Down) — lookback × rebalance grid</h1>
<p class="meta">Stamp <code>{html_mod.escape(STAMP)}</code> · Research only · Not DailyRun · Universe N={univ_n} (warehouse minus SPY) · Commissions={COMMISSIONS} · Borrow ignored</p>

<div class="callout">
<h2>What you asked</h2>
<p>{html_mod.escape(ORIGINAL_REQUEST)}</p>
<p class="note">Prior ask (L=1–4 added; earlier cells kept): {html_mod.escape(PRIOR_REQUEST_L1_4)}</p>
<p class="note">Earlier ask (L=5/10/15/20 kept): {html_mod.escape(PRIOR_REQUEST)}</p>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN_ENGLISH)}</p>
</div>

<p class="note">Click column headers to sort. {SWIPE_NOTE_HTML.replace('<p class="swipe-note">', '').replace('</p>', '')}</p>
{SWIPE_NOTE_HTML}

<h2>IS quality highlights (top Ann ROR)</h2>
<ul>
{"".join(highlights)}
</ul>
<p class="note">OOS is report-only. Do not retune L or R from OOS. Choosing a favorite from this table is in-sample selection. LEAN KEEP (if any) = research candidate only — not gold, not DailyRun.</p>

<h2>Full L × R grid</h2>
{SWIPE_NOTE_HTML}
<div class="table-wrap">
<table class="sortable">
<thead><tr>{headers}</tr></thead>
<tbody>
{"".join(body_rows)}
</tbody>
</table>
</div>

<h2>Method freeze</h2>
<ul>
<li>Rank by L-day close-to-close % return; long bottom decile / short top decile.</li>
<li>Signal at close; fill next open; full rotate every R trading days.</li>
<li>Dollar-neutral EW sleeves; seed ${INITIAL_CAPITAL:,.0f}.</li>
<li>IS = entry_date &lt; 2024-01-01; OOS = entry_date ≥ 2024-01-01.</li>
<li>Ann ROR: <code>compare_format.ann_ror_from_closed</code> with <code>brt_cash</code> = mean entry notional of that slice.</li>
<li>Max DD / Sharpe from marked equity path (not exit-date overlay only).</li>
</ul>

<p class="note">See <code>BASELINE.md</code> and <code>summary_grid.csv</code> in this stamp folder.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    path = out / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def write_trades(out: Path, cells: list[dict]) -> None:
    tdir = out / "trades"
    tdir.mkdir(parents=True, exist_ok=True)
    for c in cells:
        rows = c.get("trade_rows") or []
        if not rows:
            continue
        pd.DataFrame(rows).to_csv(tdir / f"{c['arm']}_closed.csv", index=False)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="MUD lookback × rebalance research grid")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0, help="Cap symbols for smoke tests")
    ap.add_argument("--start", type=str, default="2010-01-01")
    ap.add_argument(
        "--lookbacks",
        type=str,
        default="",
        help="Comma-separated L list (default: full grid 1..10,15,20)",
    )
    ap.add_argument(
        "--rebalances",
        type=str,
        default="",
        help="Comma-separated R list (default: 1,2,3,5,10)",
    )
    ap.add_argument(
        "--merge",
        action="store_true",
        help="Merge new cells into existing metrics.json; skip arms already present",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="With --merge, recompute requested arms even if already present",
    )
    ap.add_argument(
        "--min-bars",
        type=int,
        default=PANEL_MIN_BARS,
        help=f"Warehouse min bars filter (default {PANEL_MIN_BARS} = max full-grid L + 40)",
    )
    args = ap.parse_args()

    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    lookbacks = _parse_int_list(args.lookbacks, LOOKBACKS)
    rebalances = _parse_int_list(args.rebalances, REBALANCES)
    min_bars = int(args.min_bars)
    start = date.fromisoformat(args.start)

    existing: list[dict[str, Any]] = []
    existing_by_arm: dict[str, dict[str, Any]] = {}
    if args.merge:
        existing = load_existing_metrics(out)
        existing_by_arm = {str(c.get("arm")): c for c in existing if c.get("arm")}
        print(f"Merge: loaded {len(existing_by_arm)} existing arms from metrics.json", flush=True)

    grid = [(L, R) for L in lookbacks for R in rebalances]
    if args.merge and not args.force:
        skip = [pair for pair in grid if f"L{pair[0]}_R{pair[1]}" in existing_by_arm]
        grid = [pair for pair in grid if f"L{pair[0]}_R{pair[1]}" not in existing_by_arm]
        if skip:
            print(
                f"Skipping {len(skip)} existing arms: "
                + ", ".join(f"L{L}_R{R}" for L, R in skip),
                flush=True,
            )

    print(f"Loading panel from {args.db} (min_bars={min_bars}) ...", flush=True)
    cal, close, open_, symbols = load_panel(
        args.db,
        min_bars=min_bars,
        limit=args.limit or None,
        start=start,
    )
    print(
        f"Panel: {len(symbols)} symbols x {len(cal)} days "
        f"({cal[0].date()} .. {cal[-1].date()})",
        flush=True,
    )
    print(f"Grid cells to run: {len(grid)}  workers={args.workers}", flush=True)

    # Serialize calendar as ISO strings for worker (DatetimeIndex pickles OK usually)
    payload = {
        "cal": cal,
        "close": close,
        "open": open_,
        "symbols": symbols,
    }

    new_cells: list[dict[str, Any]] = []
    if grid:
        workers = max(1, min(int(args.workers), 8, len(grid)))
        if workers == 1:
            _init_worker(payload)
            for pair in grid:
                new_cells.append(_run_cell_worker(pair))
        else:
            # Windows spawn: pass arrays via initializer
            with ProcessPoolExecutor(
                max_workers=workers,
                initializer=_init_worker,
                initargs=(payload,),
            ) as ex:
                futs = {ex.submit(_run_cell_worker, pair): pair for pair in grid}
                for fut in as_completed(futs):
                    pair = futs[fut]
                    try:
                        new_cells.append(fut.result())
                    except Exception as exc:  # noqa: BLE001
                        print(f"FAIL L{pair[0]}_R{pair[1]}: {exc}", flush=True)
                        new_cells.append(
                            {
                                "arm": f"L{pair[0]}_R{pair[1]}",
                                "lookback": pair[0],
                                "rebalance": pair[1],
                                "error": str(exc),
                                "tm_full": trade_slice_metrics([]),
                                "tm_is": trade_slice_metrics([]),
                                "tm_oos": trade_slice_metrics([]),
                                "eq_full": {},
                                "eq_is": {},
                                "eq_oos": {},
                                "verdict": "DISMISS",
                                "verdict_note": f"run error: {exc}",
                                "trade_rows": [],
                            }
                        )
    else:
        print("No new cells to run (merge skip).", flush=True)

    # Merge by arm: new overwrites when --force; else append/replace only new
    by_arm: dict[str, dict[str, Any]] = dict(existing_by_arm) if args.merge else {}
    for c in new_cells:
        by_arm[str(c["arm"])] = c
    # If not merge and we ran a subset, still write only what we have unless merge
    cells = list(by_arm.values()) if args.merge else new_cells
    cells = verdict_grid(cells)
    write_trades(out, new_cells if args.merge else cells)
    # Strip trade_rows from metrics json
    metrics = []
    for c in cells:
        m = {k: v for k, v in c.items() if k not in {"trade_rows", "trades", "equity_rows"}}
        metrics.append(m)
    metrics.sort(key=lambda m: (int(m.get("lookback") or 0), int(m.get("rebalance") or 0)))
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")
    write_summary_csv(out, cells)
    write_baseline(out, univ_n=len(symbols), db_path=args.db, cells=cells)
    html_path = write_compare_html(out, cells, univ_n=len(symbols))
    print(f"Wrote {html_path}", flush=True)
    print(f"Stamp: {out}", flush=True)
    print(f"Arms in stamp: {len(cells)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
