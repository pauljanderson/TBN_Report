#!/usr/bin/env python3
"""MOM (Momentum) — Andreas Clenow *Stocks on the Move* research backtest.

House sleeve name: **MOM** (Momentum). Classic weekly volatility-adjusted
momentum rank + ATR risk sizing. Research candidate only — not gold, not DailyRun.

Usage:
  python tools/mom_clenow_ab.py
  python tools/mom_clenow_ab.py --start 2012-01-01 --end 2026-08-28
  python tools/mom_clenow_ab.py --limit 80   # smoke test
  python tools/mom_clenow_ab.py --out drive/paul_experiments/mom_baseline_liquid_20260829
  # One-knob universe AB (same MOM freeze):
  python tools/mom_clenow_ab.py --universe-b drive/universes/MOM_universe_adv5m.csv \\
      --out drive/paul_experiments/mom_univ_adv2m_vs_adv5m_20260829 \\
      --label "ADV$2m" --label-b "ADV$5m"

Stamp: drive/paul_experiments/mom_baseline_YYYYMMDD/ (or --out)
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import math
import sys
from dataclasses import dataclass, field
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

STAMP_DATE = "20260829"
STAMP = f"mom_baseline_liquid_{STAMP_DATE}"
OUT_DIR = _PE / STAMP
DEFAULT_DB = _REPO / "data" / "ohlcv.duckdb"
DEFAULT_UNIV = _REPO / "drive" / "universes" / "MOM_universe.csv"
IS_CUT = date(2024, 1, 1)

# --- Frozen knobs (document in BASELINE.md) ---
MOM_LOOKBACK = 90  # trading days for momentum regression
SMA_STOCK = 100
SMA_INDEX = 200
ATR_N = 20
GAP_LOOKBACK = 90
GAP_MAX = 0.15  # 15% single-day move disqualifies
TOP_FRAC = 0.20
RISK_FRAC = 0.001  # 10 bps of equity per ATR unit
REVIEW_WEEKDAY = 2  # Wednesday (Mon=0)
RESIZE_EVERY_N_REVIEWS = 2  # every other weekly review
INDEX_SYM = "SPY"
SLIPPAGE_BPS = 10.0  # one-way; research cost assumption
WARMUP_BARS = 220
MIN_BARS = 250


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


def _wilder_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int) -> np.ndarray:
    """Wilder ATR; NaN until warmup complete."""
    m = len(close)
    tr = np.full(m, np.nan)
    atr = np.full(m, np.nan)
    if m < 2:
        return atr
    tr[0] = high[0] - low[0]
    for i in range(1, m):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
    if m < n:
        return atr
    atr[n - 1] = float(np.nanmean(tr[:n]))
    for i in range(n, m):
        atr[i] = (atr[i - 1] * (n - 1) + tr[i]) / n
    return atr


def _sma(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    csum = np.cumsum(np.where(np.isfinite(x), x, 0.0))
    csum = np.insert(csum, 0, 0.0)
    for i in range(n - 1, len(x)):
        window = x[i - n + 1 : i + 1]
        if np.all(np.isfinite(window)):
            out[i] = (csum[i + 1] - csum[i + 1 - n]) / n
    return out


def momentum_score(closes: np.ndarray) -> float:
    """Annualized log-regression slope × R² over ``closes`` (length MOM_LOOKBACK).

    ``ln(P) = a + b·t``; annualized = exp(b·252) − 1; score = annualized × R².
    Requires strictly positive finite closes.
    """
    y = np.asarray(closes, dtype=float)
    if len(y) < MOM_LOOKBACK or not np.all(np.isfinite(y)) or np.any(y <= 0):
        return float("nan")
    y = np.log(y[-MOM_LOOKBACK:])
    x = np.arange(MOM_LOOKBACK, dtype=float)
    x_mean = x.mean()
    y_mean = y.mean()
    xd = x - x_mean
    yd = y - y_mean
    den = float(np.dot(xd, xd))
    if den <= 0:
        return float("nan")
    b = float(np.dot(xd, yd) / den)
    y_hat = y_mean + b * xd
    ss_res = float(np.dot(yd - b * xd, yd - b * xd))
    ss_tot = float(np.dot(yd, yd))
    if ss_tot <= 0:
        return float("nan")
    r2 = 1.0 - ss_res / ss_tot
    if not np.isfinite(r2) or r2 < 0:
        r2 = 0.0
    ann = math.exp(b * 252.0) - 1.0
    return ann * r2


def gap_shock(closes: np.ndarray, lookback: int = GAP_LOOKBACK, max_move: float = GAP_MAX) -> bool:
    """True if any single-day |return| > max_move in the past ``lookback`` days (fails filter)."""
    if len(closes) < lookback + 1:
        return True  # insufficient history → fail closed
    window = closes[-(lookback + 1) :]
    if not np.all(np.isfinite(window)) or np.any(window[:-1] <= 0):
        return True
    rets = np.abs(np.diff(window) / window[:-1])
    return bool(np.any(rets > max_move))


@dataclass
class SymSeries:
    symbol: str
    dates: np.ndarray  # datetime64[D]
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    sma50: np.ndarray
    sma100: np.ndarray
    atr20: np.ndarray
    date_to_i: dict[Any, int] = field(default_factory=dict)

    def idx(self, d: date) -> Optional[int]:
        return self.date_to_i.get(d)


def load_panel(
    db_path: Path,
    symbols: list[str],
    *,
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> dict[str, SymSeries]:
    need = sorted(set(symbols) | {INDEX_SYM})
    con = duckdb.connect(str(db_path), read_only=True)
    # Parameterized IN list
    placeholders = ",".join("?" for _ in need)
    q = f"""
      SELECT symbol, date, open, high, low, close, volume
      FROM prices
      WHERE symbol IN ({placeholders})
      ORDER BY symbol, date
    """
    df = con.execute(q, need).fetchdf()
    con.close()
    if df.empty:
        return {}
    df["date"] = pd.to_datetime(df["date"]).dt.date
    if start:
        df = df[df["date"] >= start]
    if end:
        df = df[df["date"] <= end]
    out: dict[str, SymSeries] = {}
    for sym, g in df.groupby("symbol", sort=False):
        g = g.sort_values("date")
        dates = g["date"].to_numpy()
        o = g["open"].to_numpy(dtype=float)
        h = g["high"].to_numpy(dtype=float)
        l = g["low"].to_numpy(dtype=float)
        c = g["close"].to_numpy(dtype=float)
        vol = g["volume"].to_numpy(dtype=float) if "volume" in g.columns else np.full(len(c), np.nan)
        if len(c) < MIN_BARS:
            continue
        sma50 = _sma(c, 50)
        sma = _sma(c, SMA_STOCK)
        atr = _wilder_atr(h, l, c, ATR_N)
        d2i = {d: i for i, d in enumerate(dates)}
        out[str(sym)] = SymSeries(
            symbol=str(sym),
            dates=dates,
            open=o,
            high=h,
            low=l,
            close=c,
            volume=vol,
            sma50=sma50,
            sma100=sma,
            atr20=atr,
            date_to_i=d2i,
        )
    return out


@dataclass
class Position:
    shares: int
    entry_date: date
    entry_px: float
    entry_rank: float
    cost_basis: float  # dollars including entry slip


@dataclass
class Trade:
    symbol: str
    entry_date: date
    exit_date: date
    entry_px: float
    exit_px: float
    shares: int
    pnl_dollars: float
    pnl_pct: float
    days_held: int
    exit_reason: str
    entry_score: float


@dataclass
class RebalanceEvent:
    signal_date: date
    fill_date: date
    action: str  # BUY / SELL / RESIZE
    symbol: str
    shares: int
    price: float
    reason: str
    score: float
    rank: int
    cash_after: float
    equity_after: float
    n_positions: int


def _slip_buy(px: float) -> float:
    return px * (1.0 + SLIPPAGE_BPS / 10_000.0)


def _slip_sell(px: float) -> float:
    return px * (1.0 - SLIPPAGE_BPS / 10_000.0)


def review_dates(calendar: list[date], start_i: int) -> list[date]:
    """Wednesdays on the trading calendar (or next session if holiday week misses Wed)."""
    out: list[date] = []
    seen_weeks: set[tuple[int, int]] = set()
    for d in calendar[start_i:]:
        # ISO week key
        iso = d.isocalendar()
        key = (iso.year, iso.week)
        if key in seen_weeks:
            continue
        # Prefer Wednesday in this ISO week; else first session of week if Wed already passed / missing
        week_sessions = [
            x
            for x in calendar[start_i:]
            if x.isocalendar().year == iso.year and x.isocalendar().week == iso.week
        ]
        wed = next((x for x in week_sessions if x.weekday() == REVIEW_WEEKDAY), None)
        pick = wed or week_sessions[0]
        seen_weeks.add(key)
        out.append(pick)
    return out


def run_backtest(
    panel: dict[str, SymSeries],
    univ: list[str],
    *,
    initial_capital: float = DEFAULT_INITIAL_ACCOUNT,
    bt_start: Optional[date] = None,
    bt_end: Optional[date] = None,
    sma_exit_n: int = 100,
    stop_pct: Optional[float] = None,
    max_ext_sma50: Optional[float] = None,
    max_ext_sma100: Optional[float] = None,
    sma_band_exit_n: Optional[int] = None,
    sma_band_exit_pct: Optional[float] = None,
) -> dict[str, Any]:
    """Run MOM backtest.

    Exit knobs (research ABs; defaults = classic freeze):
    - ``sma_exit_n``: weekly close below this SMA length exits (100 control, 50 arm).
      Entry filter remains close > SMA100.
    - ``stop_pct``: if set (e.g. 0.05), fixed stop from entry — daily close below
      ``entry_px * (1 - stop_pct)`` queues sell for next open (not trailing).

    Entry extension knobs (research ABs; default = none):
    - ``max_ext_sma50``: if set (e.g. 0.12), require (Close/SMA50 - 1) ≤ threshold
      in addition to Close > SMA100 (eligibility).
    - ``max_ext_sma100``: if set (e.g. 0.25), require (Close/SMA100 - 1) ≤ threshold.

    Optional band exit (distinct from SMA-cross; research only):
    - ``sma_band_exit_n`` + ``sma_band_exit_pct``: weekly exit when
      Close < SMA_n * (1 - pct) e.g. 12% below SMA50. Do not combine with
      other one-knob arms without labeling two-knob.
    """
    if INDEX_SYM not in panel:
        raise RuntimeError(f"Index {INDEX_SYM} missing from OHLC panel")
    if sma_exit_n not in (50, 100):
        raise ValueError(f"sma_exit_n must be 50 or 100, got {sma_exit_n}")
    if stop_pct is not None and not (0.0 < float(stop_pct) < 1.0):
        raise ValueError(f"stop_pct must be in (0,1) or None, got {stop_pct}")
    for name, val in (("max_ext_sma50", max_ext_sma50), ("max_ext_sma100", max_ext_sma100)):
        if val is not None and not (0.0 < float(val) < 2.0):
            raise ValueError(f"{name} must be in (0,2) or None, got {val}")
    if (sma_band_exit_n is None) != (sma_band_exit_pct is None):
        raise ValueError("sma_band_exit_n and sma_band_exit_pct must be set together")
    if sma_band_exit_n is not None and sma_band_exit_n not in (50, 100):
        raise ValueError(f"sma_band_exit_n must be 50 or 100, got {sma_band_exit_n}")
    if sma_band_exit_pct is not None and not (0.0 < float(sma_band_exit_pct) < 1.0):
        raise ValueError(f"sma_band_exit_pct must be in (0,1) or None, got {sma_band_exit_pct}")

    spy = panel[INDEX_SYM]
    spy_sma200 = _sma(spy.close, SMA_INDEX)
    stop_reason = f"stop_{int(round(float(stop_pct) * 100))}pct" if stop_pct else None
    sma_exit_reason = f"below_sma{sma_exit_n}"
    band_exit_reason: Optional[str] = None
    if sma_band_exit_n is not None and sma_band_exit_pct is not None:
        band_exit_reason = (
            f"below_sma{sma_band_exit_n}_by_{int(round(float(sma_band_exit_pct) * 100))}pct"
        )
    calendar = [d for d in spy.dates.tolist()]
    if bt_start:
        calendar = [d for d in calendar if d >= bt_start]
    if bt_end:
        calendar = [d for d in calendar if d <= bt_end]
    if len(calendar) < WARMUP_BARS + 50:
        raise RuntimeError("Insufficient calendar length after date filters")

    # Align start after warmup on SPY
    start_i = WARMUP_BARS
    while start_i < len(calendar) and not np.isfinite(spy_sma200[spy.idx(calendar[start_i]) or 0]):
        start_i += 1

    revs = review_dates(calendar, start_i)
    cal_set = set(calendar)
    cal_index = {d: i for i, d in enumerate(calendar)}

    def next_session(d: date) -> Optional[date]:
        i = cal_index.get(d)
        if i is None or i + 1 >= len(calendar):
            return None
        return calendar[i + 1]

    cash = float(initial_capital)
    positions: dict[str, Position] = {}
    trades: list[Trade] = []
    events: list[RebalanceEvent] = []
    equity_rows: list[dict[str, Any]] = []

    def mark_equity(d: date) -> float:
        eq = cash
        for sym, pos in positions.items():
            ser = panel.get(sym)
            if ser is None:
                continue
            i = ser.idx(d)
            if i is None:
                continue
            px = float(ser.close[i])
            if np.isfinite(px):
                eq += pos.shares * px
        return eq

    def record_equity(d: date) -> None:
        eq = mark_equity(d)
        equity_rows.append(
            {
                "date": d.isoformat(),
                "equity": round(eq, 2),
                "cash": round(cash, 2),
                "n_positions": len(positions),
                "invested_pct": round(100.0 * (1.0 - cash / eq), 2) if eq > 0 else 0.0,
            }
        )

    # Daily MTM between reviews
    rev_set = set(revs)
    pending_orders: list[dict[str, Any]] = []

    def flush_orders(fill_date: date) -> None:
        nonlocal cash
        # Process sells first, then resizes (sell side), then buys / resize buys
        sells = [o for o in pending_orders if o["side"] == "SELL"]
        buys = [o for o in pending_orders if o["side"] == "BUY"]
        pending_orders.clear()

        for o in sells:
            sym = o["symbol"]
            ser = panel.get(sym)
            if ser is None or sym not in positions:
                continue
            i = ser.idx(fill_date)
            if i is None:
                # try same-day close if open missing session
                continue
            px = float(ser.open[i]) if np.isfinite(ser.open[i]) else float(ser.close[i])
            if not np.isfinite(px) or px <= 0:
                continue
            fill_px = _slip_sell(px)
            pos = positions.pop(sym)
            shares = min(o["shares"], pos.shares) if o["shares"] > 0 else pos.shares
            proceeds = shares * fill_px
            cash += proceeds
            pnl = proceeds - pos.cost_basis * (shares / pos.shares if pos.shares else 1.0)
            # Full exit assumed for classic MOM
            if shares < pos.shares:
                # partial — keep remainder (resize)
                remain = pos.shares - shares
                remain_basis = pos.cost_basis * (remain / pos.shares)
                positions[sym] = Position(
                    shares=remain,
                    entry_date=pos.entry_date,
                    entry_px=pos.entry_px,
                    entry_rank=pos.entry_rank,
                    cost_basis=remain_basis,
                )
                # partial not a closed trade
                events.append(
                    RebalanceEvent(
                        signal_date=o["signal_date"],
                        fill_date=fill_date,
                        action="RESIZE",
                        symbol=sym,
                        shares=-shares,
                        price=fill_px,
                        reason=o["reason"],
                        score=o.get("score", float("nan")),
                        rank=o.get("rank", -1),
                        cash_after=cash,
                        equity_after=mark_equity(fill_date),
                        n_positions=len(positions),
                    )
                )
            else:
                days = (fill_date - pos.entry_date).days
                pnl_pct = (fill_px / pos.entry_px - 1.0) * 100.0 if pos.entry_px else 0.0
                trades.append(
                    Trade(
                        symbol=sym,
                        entry_date=pos.entry_date,
                        exit_date=fill_date,
                        entry_px=pos.entry_px,
                        exit_px=fill_px,
                        shares=shares,
                        pnl_dollars=pnl,
                        pnl_pct=pnl_pct,
                        days_held=days,
                        exit_reason=o["reason"],
                        entry_score=pos.entry_rank,
                    )
                )
                events.append(
                    RebalanceEvent(
                        signal_date=o["signal_date"],
                        fill_date=fill_date,
                        action="SELL",
                        symbol=sym,
                        shares=-shares,
                        price=fill_px,
                        reason=o["reason"],
                        score=o.get("score", float("nan")),
                        rank=o.get("rank", -1),
                        cash_after=cash,
                        equity_after=mark_equity(fill_date),
                        n_positions=len(positions),
                    )
                )

        eq_for_size = mark_equity(fill_date)
        for o in buys:
            sym = o["symbol"]
            ser = panel.get(sym)
            if ser is None:
                continue
            i = ser.idx(fill_date)
            if i is None:
                continue
            px = float(ser.open[i]) if np.isfinite(ser.open[i]) else float(ser.close[i])
            atr = float(ser.atr20[i]) if np.isfinite(ser.atr20[i]) else float("nan")
            if not np.isfinite(px) or px <= 0 or not np.isfinite(atr) or atr <= 0:
                continue
            fill_px = _slip_buy(px)
            target_shares = int((eq_for_size * RISK_FRAC) / atr)
            if target_shares < 1:
                continue
            if o["action"] == "RESIZE" and sym in positions:
                cur = positions[sym].shares
                delta = target_shares - cur
                if delta == 0:
                    continue
                if delta < 0:
                    # sell excess — already handled if we queued as SELL; skip
                    continue
                cost = delta * fill_px
                if cost > cash:
                    delta = int(cash // fill_px)
                    cost = delta * fill_px
                if delta < 1:
                    continue
                pos = positions[sym]
                positions[sym] = Position(
                    shares=pos.shares + delta,
                    entry_date=pos.entry_date,
                    entry_px=pos.entry_px,
                    entry_rank=pos.entry_rank,
                    cost_basis=pos.cost_basis + cost,
                )
                cash -= cost
                events.append(
                    RebalanceEvent(
                        signal_date=o["signal_date"],
                        fill_date=fill_date,
                        action="RESIZE",
                        symbol=sym,
                        shares=delta,
                        price=fill_px,
                        reason=o["reason"],
                        score=o.get("score", float("nan")),
                        rank=o.get("rank", -1),
                        cash_after=cash,
                        equity_after=mark_equity(fill_date),
                        n_positions=len(positions),
                    )
                )
                continue

            # New buy
            if sym in positions:
                continue
            shares = target_shares
            cost = shares * fill_px
            if cost > cash:
                shares = int(cash // fill_px)
                cost = shares * fill_px
            if shares < 1:
                continue
            cash -= cost
            positions[sym] = Position(
                shares=shares,
                entry_date=fill_date,
                entry_px=fill_px,
                entry_rank=float(o.get("score", float("nan"))),
                cost_basis=cost,
            )
            events.append(
                RebalanceEvent(
                    signal_date=o["signal_date"],
                    fill_date=fill_date,
                    action="BUY",
                    symbol=sym,
                    shares=shares,
                    price=fill_px,
                    reason=o["reason"],
                    score=o.get("score", float("nan")),
                    rank=o.get("rank", -1),
                    cash_after=cash,
                    equity_after=mark_equity(fill_date),
                    n_positions=len(positions),
                )
            )
            eq_for_size = mark_equity(fill_date)

    review_i = 0
    for d in calendar[start_i:]:
        # Execute pending fills from prior signal
        if pending_orders:
            flush_orders(d)

        # Daily fixed stop (from entry) — signal at close, fill next open
        if stop_pct is not None and stop_reason is not None:
            already = {o["symbol"] for o in pending_orders if o["side"] == "SELL"}
            for sym in list(positions.keys()):
                if sym in already:
                    continue
                ser = panel.get(sym)
                if ser is None:
                    continue
                i = ser.idx(d)
                if i is None:
                    continue
                c = ser.close[i]
                entry_px = positions[sym].entry_px
                if not (np.isfinite(c) and np.isfinite(entry_px) and entry_px > 0):
                    continue
                if c < entry_px * (1.0 - float(stop_pct)):
                    pending_orders.append(
                        {
                            "side": "SELL",
                            "action": "SELL",
                            "symbol": sym,
                            "shares": positions[sym].shares,
                            "signal_date": d,
                            "reason": stop_reason,
                            "score": float("nan"),
                            "rank": -1,
                        }
                    )

        if d in rev_set:
            # --- Signal at Wednesday close (no look-ahead beyond today's close) ---
            spy_i = spy.idx(d)
            index_ok = False
            if spy_i is not None and np.isfinite(spy_sma200[spy_i]) and np.isfinite(spy.close[spy_i]):
                index_ok = bool(spy.close[spy_i] > spy_sma200[spy_i])

            scored: list[tuple[str, float, int]] = []  # sym, score, local_i
            for sym in univ:
                ser = panel.get(sym)
                if ser is None:
                    continue
                i = ser.idx(d)
                if i is None or i < MOM_LOOKBACK + 5:
                    continue
                c = ser.close[i]
                sma = ser.sma100[i]
                atr = ser.atr20[i]
                if not (np.isfinite(c) and np.isfinite(sma) and np.isfinite(atr) and c > 0 and atr > 0):
                    continue
                if c <= sma:
                    continue
                if max_ext_sma100 is not None:
                    ext100 = c / sma - 1.0
                    if not np.isfinite(ext100) or ext100 > float(max_ext_sma100):
                        continue
                if max_ext_sma50 is not None:
                    sma50 = ser.sma50[i]
                    if not np.isfinite(sma50) or sma50 <= 0:
                        continue
                    ext50 = c / sma50 - 1.0
                    if not np.isfinite(ext50) or ext50 > float(max_ext_sma50):
                        continue
                if gap_shock(ser.close[: i + 1]):
                    continue
                sc = momentum_score(ser.close[: i + 1])
                if not np.isfinite(sc):
                    continue
                scored.append((sym, float(sc), i))

            scored.sort(key=lambda t: t[1], reverse=True)
            n_elig = len(scored)
            top_n = max(1, int(round(TOP_FRAC * n_elig))) if n_elig else 0
            top_set = {s for s, _, _ in scored[:top_n]}
            rank_map = {s: r + 1 for r, (s, _, _) in enumerate(scored)}
            score_map = {s: sc for s, sc, _ in scored}

            pending_sell_syms = {o["symbol"] for o in pending_orders if o["side"] == "SELL"}

            # Sells
            for sym in list(positions.keys()):
                if sym in pending_sell_syms:
                    continue
                ser = panel.get(sym)
                reason = None
                if ser is None:
                    reason = "left_universe_no_data"
                else:
                    i = ser.idx(d)
                    if i is None:
                        reason = "left_universe_no_bar"
                    else:
                        c = ser.close[i]
                        sma_arr = ser.sma50 if sma_exit_n == 50 else ser.sma100
                        sma = sma_arr[i]
                        if np.isfinite(c) and np.isfinite(sma) and c < sma:
                            reason = sma_exit_reason
                        elif (
                            band_exit_reason is not None
                            and sma_band_exit_n is not None
                            and sma_band_exit_pct is not None
                        ):
                            band_arr = ser.sma50 if sma_band_exit_n == 50 else ser.sma100
                            band_sma = band_arr[i]
                            if (
                                np.isfinite(c)
                                and np.isfinite(band_sma)
                                and band_sma > 0
                                and c < band_sma * (1.0 - float(sma_band_exit_pct))
                            ):
                                reason = band_exit_reason
                            elif sym not in top_set:
                                reason = "rank_exit_top20pct"
                        elif sym not in top_set:
                            reason = "rank_exit_top20pct"
                if reason:
                    pending_orders.append(
                        {
                            "side": "SELL",
                            "action": "SELL",
                            "symbol": sym,
                            "shares": positions[sym].shares,
                            "signal_date": d,
                            "reason": reason,
                            "score": score_map.get(sym, float("nan")),
                            "rank": rank_map.get(sym, -1),
                        }
                    )

            do_resize = (review_i % RESIZE_EVERY_N_REVIEWS) == 1  # every other review after first
            # After processing sells conceptually, queue resizes for survivors
            if do_resize:
                for sym in list(positions.keys()):
                    if any(o["symbol"] == sym and o["side"] == "SELL" for o in pending_orders):
                        continue
                    ser = panel.get(sym)
                    if ser is None:
                        continue
                    i = ser.idx(d)
                    if i is None or not np.isfinite(ser.atr20[i]):
                        continue
                    eq = mark_equity(d)
                    tgt = int((eq * RISK_FRAC) / float(ser.atr20[i]))
                    cur = positions[sym].shares
                    if tgt < 1:
                        pending_orders.append(
                            {
                                "side": "SELL",
                                "action": "SELL",
                                "symbol": sym,
                                "shares": cur,
                                "signal_date": d,
                                "reason": "resize_to_zero",
                                "score": score_map.get(sym, float("nan")),
                                "rank": rank_map.get(sym, -1),
                            }
                        )
                    elif tgt < cur:
                        pending_orders.append(
                            {
                                "side": "SELL",
                                "action": "RESIZE",
                                "symbol": sym,
                                "shares": cur - tgt,
                                "signal_date": d,
                                "reason": "resize_down",
                                "score": score_map.get(sym, float("nan")),
                                "rank": rank_map.get(sym, -1),
                            }
                        )
                    elif tgt > cur:
                        pending_orders.append(
                            {
                                "side": "BUY",
                                "action": "RESIZE",
                                "symbol": sym,
                                "shares": tgt - cur,
                                "signal_date": d,
                                "reason": "resize_up",
                                "score": score_map.get(sym, float("nan")),
                                "rank": rank_map.get(sym, -1),
                            }
                        )

            # New buys if index regime OK — fill from top of rank
            if index_ok and top_n > 0:
                for r, (sym, sc, _) in enumerate(scored[:top_n]):
                    if sym in positions:
                        continue
                    if any(o["symbol"] == sym and o["side"] == "SELL" for o in pending_orders):
                        continue
                    pending_orders.append(
                        {
                            "side": "BUY",
                            "action": "BUY",
                            "symbol": sym,
                            "shares": 0,  # sized at fill
                            "signal_date": d,
                            "reason": "rank_entry",
                            "score": sc,
                            "rank": r + 1,
                        }
                    )

            review_i += 1

        record_equity(d)

    # Flush any orders still pending from the last review (no next session left)
    if pending_orders and calendar:
        flush_orders(calendar[-1])

    # Liquidate leftover open positions at last close (research book close)
    if positions and calendar:
        cash, positions = liquidate_all(positions, panel, cash, trades, events, calendar[-1])

    final_eq = float(cash)

    return {
        "trades": trades,
        "events": events,
        "equity": equity_rows,
        "final_equity": final_eq,
        "final_cash": cash,
        "n_reviews": review_i,
        "calendar_start": calendar[start_i],
        "calendar_end": calendar[-1],
        "initial_capital": initial_capital,
        "sma_exit_n": sma_exit_n,
        "stop_pct": stop_pct,
        "max_ext_sma50": max_ext_sma50,
        "max_ext_sma100": max_ext_sma100,
        "sma_band_exit_n": sma_band_exit_n,
        "sma_band_exit_pct": sma_band_exit_pct,
    }


def liquidate_all(
    positions: dict[str, Position],
    panel: dict[str, SymSeries],
    cash: float,
    trades: list[Trade],
    events: list[RebalanceEvent],
    last: date,
) -> tuple[float, dict[str, Position]]:
    for sym in list(positions.keys()):
        ser = panel.get(sym)
        pos = positions.pop(sym)
        if ser is None:
            continue
        i = ser.idx(last)
        if i is None:
            continue
        px = float(ser.close[i])
        if not np.isfinite(px) or px <= 0:
            continue
        fill_px = _slip_sell(px)
        proceeds = pos.shares * fill_px
        cash += proceeds
        pnl = proceeds - pos.cost_basis
        pnl_pct = (fill_px / pos.entry_px - 1.0) * 100.0 if pos.entry_px else 0.0
        trades.append(
            Trade(
                symbol=sym,
                entry_date=pos.entry_date,
                exit_date=last,
                entry_px=pos.entry_px,
                exit_px=fill_px,
                shares=pos.shares,
                pnl_dollars=pnl,
                pnl_pct=pnl_pct,
                days_held=(last - pos.entry_date).days,
                exit_reason="end_of_backtest",
                entry_score=pos.entry_rank,
            )
        )
        events.append(
            RebalanceEvent(
                signal_date=last,
                fill_date=last,
                action="SELL",
                symbol=sym,
                shares=-pos.shares,
                price=fill_px,
                reason="end_of_backtest",
                score=float("nan"),
                rank=-1,
                cash_after=cash,
                equity_after=cash,
                n_positions=len(positions),
            )
        )
    return cash, positions


# ---------------------------------------------------------------------------
# Metrics / stamp writers
# ---------------------------------------------------------------------------


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


def trade_metrics(trades: list[Trade]) -> dict[str, Any]:
    if not trades:
        return {
            "n": 0,
            "win_rate": float("nan"),
            "avg_pnl_pct": float("nan"),
            "avg_days": float("nan"),
            "profit_factor": float("nan"),
            "expectancy_pct": float("nan"),
        }
    pnls = [t.pnl_pct for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_win = sum(t.pnl_dollars for t in trades if t.pnl_dollars > 0)
    gross_loss = abs(sum(t.pnl_dollars for t in trades if t.pnl_dollars < 0))
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf") if gross_win > 0 else float("nan")
    return {
        "n": len(trades),
        "win_rate": 100.0 * len(wins) / len(trades),
        "avg_pnl_pct": float(np.mean(pnls)),
        "avg_days": float(np.mean([t.days_held for t in trades])),
        "profit_factor": pf,
        "expectancy_pct": float(np.mean(pnls)),
        "median_pnl_pct": float(np.median(pnls)),
        "avg_win_pct": float(np.mean(wins)) if wins else float("nan"),
        "avg_loss_pct": float(np.mean(losses)) if losses else float("nan"),
    }


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
    calmar = (ann / abs(mdd)) if (np.isfinite(ann) and np.isfinite(mdd) and abs(mdd) > 1e-9) else float("nan")
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


def _fmt_metric(x: Any, nd: int = 2) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if not np.isfinite(v):
        return "—"
    return f"{v:.{nd}f}"


def pack_metrics(result: dict[str, Any]) -> dict[str, Any]:
    """Build full / IS / OOS equity + trade metrics from a backtest result."""
    trades: list[Trade] = result["trades"]
    eq_df = pd.DataFrame(result["equity"])
    eq_df["d"] = pd.to_datetime(eq_df["date"]).dt.date
    full_m = equity_slice_metrics(eq_df, eq_df["d"].iloc[0], eq_df["d"].iloc[-1], "full_book")
    is_m = equity_slice_metrics(eq_df, eq_df["d"].iloc[0], date(2023, 12, 31), "IS_equity")
    oos_m = equity_slice_metrics(eq_df, IS_CUT, eq_df["d"].iloc[-1], "OOS_equity")
    is_trades = [t for t in trades if t.entry_date < IS_CUT]
    oos_trades = [t for t in trades if t.entry_date >= IS_CUT]
    exit_counts: dict[str, int] = {}
    for t in trades:
        exit_counts[t.exit_reason] = exit_counts.get(t.exit_reason, 0) + 1
    return {
        "eq_df": eq_df,
        "full_m": full_m,
        "is_m": is_m,
        "oos_m": oos_m,
        "tm_all": trade_metrics(trades),
        "tm_is": trade_metrics(is_trades),
        "tm_oos": trade_metrics(oos_trades),
        "exit_counts": exit_counts,
        "trades": trades,
    }


def _write_trade_csvs(out: Path, result: dict[str, Any], prefix: str = "MOM") -> list[Path]:
    written: list[Path] = []
    trades: list[Trade] = result["trades"]
    events: list[RebalanceEvent] = result["events"]

    closed_path = out / f"{prefix}_Closed.csv"
    with closed_path.open("w", encoding="utf-8", newline="") as f:
        f.write(
            "SYMBOL,ENTRY_DATE,EXIT_DATE,ENTRY_PX,EXIT_PX,SHARES,PNL_PCT,PNL_DOLLARS,"
            "DAYS_HELD,EXIT_REASON,ENTRY_SCORE\n"
        )
        for t in trades:
            f.write(
                f"{t.symbol},{t.entry_date.isoformat()},{t.exit_date.isoformat()},"
                f"{t.entry_px:.4f},{t.exit_px:.4f},{t.shares},{t.pnl_pct:.4f},"
                f"{t.pnl_dollars:.2f},{t.days_held},{t.exit_reason},{t.entry_score:.6f}\n"
            )
    written.append(closed_path)

    events_path = out / f"{prefix}_RebalanceEvents.csv"
    with events_path.open("w", encoding="utf-8", newline="") as f:
        f.write(
            "SIGNAL_DATE,FILL_DATE,ACTION,SYMBOL,SHARES,PRICE,REASON,SCORE,RANK,"
            "CASH_AFTER,EQUITY_AFTER,N_POSITIONS\n"
        )
        for e in events:
            sc = "" if not np.isfinite(e.score) else f"{e.score:.6f}"
            f.write(
                f"{e.signal_date.isoformat()},{e.fill_date.isoformat()},{e.action},"
                f"{e.symbol},{e.shares},{e.price:.4f},{e.reason},{sc},{e.rank},"
                f"{e.cash_after:.2f},{e.equity_after:.2f},{e.n_positions}\n"
            )
    written.append(events_path)

    eq_path = out / f"{prefix}_EquityCurve.csv"
    pd.DataFrame(result["equity"]).to_csv(eq_path, index=False)
    written.append(eq_path)
    return written


def write_stamp(
    result: dict[str, Any],
    univ: list[str],
    univ_path: Path,
    out: Path,
    *,
    stamp: Optional[str] = None,
    title: str = "MOM (Momentum) — Clenow Stocks on the Move liquid baseline",
    univ_note: Optional[str] = None,
) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    stamp = stamp or out.name
    written: list[Path] = []
    written.extend(_write_trade_csvs(out, result, prefix="MOM"))

    pack = pack_metrics(result)
    full_m, is_m, oos_m = pack["full_m"], pack["is_m"], pack["oos_m"]
    tm_all, tm_is, tm_oos = pack["tm_all"], pack["tm_is"], pack["tm_oos"]
    exit_counts = pack["exit_counts"]
    trades: list[Trade] = pack["trades"]

    holdings_path = out / "MOM_TopHoldings_by_pnl.csv"
    by_sym: dict[str, list[Trade]] = {}
    for t in trades:
        by_sym.setdefault(t.symbol, []).append(t)
    hold_rows = []
    for sym, ts in by_sym.items():
        hold_rows.append(
            {
                "symbol": sym,
                "n_trades": len(ts),
                "total_pnl_pct_sum": sum(x.pnl_pct for x in ts),
                "avg_pnl_pct": float(np.mean([x.pnl_pct for x in ts])),
                "win_rate": 100.0 * sum(1 for x in ts if x.pnl_pct > 0) / len(ts),
                "avg_days": float(np.mean([x.days_held for x in ts])),
            }
        )
    hold_df = pd.DataFrame(hold_rows).sort_values("total_pnl_pct_sum", ascending=False)
    hold_df.to_csv(holdings_path, index=False)
    written.append(holdings_path)

    univ_copy = out / "MOM_universe.csv"
    univ_copy.write_text(univ_path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    written.append(univ_copy)

    if univ_note is None:
        univ_note = (
            f"- File: `{univ_path.as_posix()}` (= `VZ_tradable_2010_adv2m_universe.csv` / liquid ADV$2m)\n"
            f"- **N = {len(univ)}** symbols (static membership list)\n"
            "- Traits (parent freeze as-of **2023-12-29**): first bar ≤ 2010-01-04; Close ≥ $5; "
            "20-day Average Dollar Volume (ADV$) ≥ **$2,000,000**\n"
            "- **This stamp supersedes `mom_baseline_20260828` ALL_ohlc (N≈1118) as the research freeze universe.** "
            "Prior ALL_ohlc run ended 2023-12-29 (no real OOS). Liquid tape through current end date so IS and OOS both exist.\n"
            "- **Not** point-in-time S&P 500 membership (blocker — see SUMMARY)\n"
            "- OHLC: `data/ohlcv.duckdb` table `prices`; index = **SPY**"
        )

    baseline = f"""# BASELINE — `{stamp}`

**Status:** RESEARCH candidate only. **Not gold. Not DailyRun-wired.**

**Name:** **MOM** = **Momentum** (Andreas Clenow *Stocks on the Move* classic rules, public reconstructions).

**Rules source:** `drive/paul_experiments/clenow_rules_summary_20260828/` + `mom_baseline_20260828` knob freeze (no retune).

## Universe

{univ_note}

## Buy (frozen)

1. In MOM universe with enough history
2. Close **above** 100-day Simple Moving Average (SMA)
3. **Gap filter (included):** no single-day |return| > **15%** in past **90** trading days
4. Rank by **90-day volatility-adjusted momentum** = annualized slope of log regression of closes × R² (coefficient of determination); higher better
5. Candidate pool = **top 20%** of *eligible* (passed filters) ranked names that day
6. **New buys only** if SPY close **above** its **200-day SMA**
7. Position size: `shares ≈ (portfolio_equity × 0.001) / 20-day Average True Range (ATR)` (Wilder); fill from top of rank until cash used
8. **Weekly review = Wednesday** (ISO week; if no Wednesday session, first session of that week). Signal at review **close**; fills at **next session open** (+10 bps one-way slip research assumption)
9. **Re-size every other weekly review** (book cadence)

## Sell (frozen)

1. Falls out of top ~20% on weekly review → sell
2. Close **below** 100-day SMA on weekly review → sell
3. Leaves usable data / universe → sell
4. **No classic hard stop / profit target** (risk via ATR sizing + rank/SMA exits)
5. End-of-backtest liquidation (research book close)

## Look-ahead

- SMA / ATR / momentum / gap filters use data **through signal-date close only**
- Fills at **next open** — no same-bar open fill using that bar’s range for entry decisions

## Costs / capital

- Initial account: **${result['initial_capital']:,.0f}** (house EquityMeta seed)
- Slippage: **{SLIPPAGE_BPS:g} bps** one-way (research); no commission line-item

## IS / OOS

- Default chronological split: **IS** = entry_date / equity before **2024-01-01**; **OOS** = on/after
- OOS is **report-only** — do not retune knobs on OOS

## How to re-run

```bash
python tools/mom_clenow_ab.py --out drive/paul_experiments/{stamp} --end 2026-08-28
```

## Promotion

Research candidate ≠ gold ≠ DailyRun. Do not wire DailyRun from this stamp alone.
"""
    bp = out / "BASELINE.md"
    bp.write_text(baseline, encoding="utf-8")
    written.append(bp)

    summary = f"""# SUMMARY — `{stamp}`

**MOM (Momentum)** Clenow weekly rank sleeve — research only. Liquid ADV$2m freeze.

## Universe

- `{univ_path.as_posix()}` → **N={len(univ)}**
- Supersedes ALL_ohlc research freeze univ (`mom_baseline_20260828`)
- Index: SPY · Review: Wednesday · Top frac: {TOP_FRAC:.0%} · Risk: {RISK_FRAC} / ATR{ATR_N}

## Full-book equity ({full_m.get('start')} → {full_m.get('end')})

| Metric | Value |
|--------|-------|
| Start equity | {format_money(full_m.get('start_equity'))} |
| End equity | {format_money(full_m.get('end_equity'))} |
| Total return % | {_fmt_metric(full_m.get('total_ret_pct'))} |
| Ann ROR % | {_fmt_metric(full_m.get('ann_ror'))} |
| Max DD % | {_fmt_metric(full_m.get('max_dd'))} |
| Calmar | {_fmt_metric(full_m.get('calmar'))} |
| Sharpe (rf=0) | {_fmt_metric(full_m.get('sharpe'))} |
| Closed trades N | {tm_all['n']} |
| Win rate % | {_fmt_metric(tm_all.get('win_rate'))} |
| Avg PnL % | {_fmt_metric(tm_all.get('avg_pnl_pct'))} |
| Avg days held | {_fmt_metric(tm_all.get('avg_days'))} |
| Profit factor | {_fmt_metric(tm_all.get('profit_factor'))} |

## IS / OOS — equity curve method

Equity marked daily; slices by calendar date (not a re-tuned book).

| Slice | Start | End | Ann ROR % | Max DD % | Total ret % | Sharpe | Calmar | Days |
|-------|-------|-----|-----------|----------|-------------|--------|--------|------|
| IS equity (<2024) | {is_m.get('start','—')} | {is_m.get('end','—')} | {_fmt_metric(is_m.get('ann_ror'))} | {_fmt_metric(is_m.get('max_dd'))} | {_fmt_metric(is_m.get('total_ret_pct'))} | {_fmt_metric(is_m.get('sharpe'))} | {_fmt_metric(is_m.get('calmar'))} | {is_m.get('n_days')} |
| OOS equity (≥2024) | {oos_m.get('start','—')} | {oos_m.get('end','—')} | {_fmt_metric(oos_m.get('ann_ror'))} | {_fmt_metric(oos_m.get('max_dd'))} | {_fmt_metric(oos_m.get('total_ret_pct'))} | {_fmt_metric(oos_m.get('sharpe'))} | {_fmt_metric(oos_m.get('calmar'))} | {oos_m.get('n_days')} |

## IS / OOS — trade-level (by entry_date)

| Slice | N | Win% | Avg PnL% | Avg days | PF |
|-------|---|------|----------|----------|-----|
| IS entries | {tm_is['n']} | {_fmt_metric(tm_is.get('win_rate'))} | {_fmt_metric(tm_is.get('avg_pnl_pct'))} | {_fmt_metric(tm_is.get('avg_days'))} | {_fmt_metric(tm_is.get('profit_factor'))} |
| OOS entries | {tm_oos['n']} | {_fmt_metric(tm_oos.get('win_rate'))} | {_fmt_metric(tm_oos.get('avg_pnl_pct'))} | {_fmt_metric(tm_oos.get('avg_days'))} | {_fmt_metric(tm_oos.get('profit_factor'))} |

## Exit mix

{chr(10).join(f'- `{k}`: {v}' for k, v in sorted(exit_counts.items(), key=lambda kv: -kv[1]))}

## Blockers / caveats

1. **No point-in-time S&P 500 membership** — static liquid tradable tape (survivorship / membership bias vs classic Clenow).
2. Gap filter included (some public summaries omit it) — labeled in BASELINE.
3. ATR = Wilder 20; risk factor 10 bps — common reconstruction, not a book PDF in-repo.
4. OOS report-only — do not retune on OOS.
5. Not gold / not DailyRun.

## Artifacts

- `compare.html` — sortable summary
- `MOM_Closed.csv` — closed trades
- `MOM_RebalanceEvents.csv` — buy/sell/resize events
- `MOM_EquityCurve.csv`
- `BASELINE.md` / `SUMMARY.md`
"""
    sp = out / "SUMMARY.md"
    sp.write_text(summary, encoding="utf-8")
    written.append(sp)

    metrics_json = {
        "stamp": stamp,
        "universe": univ_path.as_posix(),
        "n_univ": len(univ),
        "full": {k: v for k, v in full_m.items() if k != "label"},
        "is": {k: v for k, v in is_m.items() if k != "label"},
        "oos": {k: v for k, v in oos_m.items() if k != "label"},
        "tm_all": tm_all,
        "tm_is": tm_is,
        "tm_oos": tm_oos,
        "exit_counts": exit_counts,
    }
    mj = out / "metrics.json"
    mj.write_text(json.dumps(metrics_json, indent=2, default=str), encoding="utf-8")
    written.append(mj)

    html_path = write_html(
        out,
        stamp=stamp,
        title=title,
        univ_n=len(univ),
        full_m=full_m,
        is_m=is_m,
        oos_m=oos_m,
        tm_all=tm_all,
        tm_is=tm_is,
        tm_oos=tm_oos,
        exit_counts=exit_counts,
        hold_df=hold_df.head(40),
        trades=trades[:200],
        result=result,
    )
    written.append(html_path)
    return written


def write_html(
    out: Path,
    *,
    stamp: str,
    title: str,
    univ_n: int,
    full_m: dict[str, Any],
    is_m: dict[str, Any],
    oos_m: dict[str, Any],
    tm_all: dict[str, Any],
    tm_is: dict[str, Any],
    tm_oos: dict[str, Any],
    exit_counts: dict[str, int],
    hold_df: pd.DataFrame,
    trades: list[Trade],
    result: dict[str, Any],
) -> Path:
    def fmt_num(x: Any, nd: int = 2) -> str:
        return _fmt_metric(x, nd)

    # Metric table — omit Sheet/Total PnL $ per house filter
    metric_rows = [
        ("Ann ROR %", full_m.get("ann_ror"), is_m.get("ann_ror"), oos_m.get("ann_ror")),
        ("Max DD %", full_m.get("max_dd"), is_m.get("max_dd"), oos_m.get("max_dd")),
        ("Calmar", full_m.get("calmar"), is_m.get("calmar"), oos_m.get("calmar")),
        ("Sharpe (rf=0)", full_m.get("sharpe"), is_m.get("sharpe"), oos_m.get("sharpe")),
        ("Total return %", full_m.get("total_ret_pct"), is_m.get("total_ret_pct"), oos_m.get("total_ret_pct")),
        ("Closed trades N", tm_all.get("n"), tm_is.get("n"), tm_oos.get("n")),
        ("Win rate %", tm_all.get("win_rate"), tm_is.get("win_rate"), tm_oos.get("win_rate")),
        ("Avg PnL %", tm_all.get("avg_pnl_pct"), tm_is.get("avg_pnl_pct"), tm_oos.get("avg_pnl_pct")),
        ("Avg days held", tm_all.get("avg_days"), tm_is.get("avg_days"), tm_oos.get("avg_days")),
        ("Profit factor", tm_all.get("profit_factor"), tm_is.get("profit_factor"), tm_oos.get("profit_factor")),
    ]
    metric_rows = [r for r in metric_rows if not is_excluded_html_compare_label(r[0])]

    m_head = (
        _sortable_th("Metric", "text")
        + _sortable_th("Full book", "num")
        + _sortable_th("IS", "num")
        + _sortable_th("OOS", "num")
    )
    m_body = "".join(
        f"<tr><td>{html_mod.escape(a)}</td><td>{fmt_num(b)}</td><td>{fmt_num(c)}</td><td>{fmt_num(d)}</td></tr>"
        for a, b, c, d in metric_rows
    )

    exit_head = _sortable_th("Exit reason", "text") + _sortable_th("N", "num")
    exit_body = "".join(
        f"<tr><td>{html_mod.escape(k)}</td><td>{v}</td></tr>"
        for k, v in sorted(exit_counts.items(), key=lambda kv: -kv[1])
    )

    h_head = (
        _sortable_th("Symbol", "text")
        + _sortable_th("N trades", "num")
        + _sortable_th("Sum PnL %", "num")
        + _sortable_th("Avg PnL %", "num")
        + _sortable_th("Win %", "num")
        + _sortable_th("Avg days", "num")
    )
    h_body = ""
    for _, r in hold_df.iterrows():
        h_body += (
            f"<tr><td>{html_mod.escape(str(r['symbol']))}</td>"
            f"<td>{int(r['n_trades'])}</td>"
            f"<td>{fmt_num(r['total_pnl_pct_sum'])}</td>"
            f"<td>{fmt_num(r['avg_pnl_pct'])}</td>"
            f"<td>{fmt_num(r['win_rate'])}</td>"
            f"<td>{fmt_num(r['avg_days'])}</td></tr>"
        )

    t_head = (
        _sortable_th("Symbol", "text")
        + _sortable_th("Entry", "date")
        + _sortable_th("Exit", "date")
        + _sortable_th("PnL %", "num")
        + _sortable_th("Days", "num")
        + _sortable_th("Reason", "text")
    )
    t_body = "".join(
        f"<tr><td>{html_mod.escape(t.symbol)}</td>"
        f"<td>{t.entry_date.isoformat()}</td><td>{t.exit_date.isoformat()}</td>"
        f"<td>{fmt_num(t.pnl_pct)}</td><td>{t.days_held}</td>"
        f"<td>{html_mod.escape(t.exit_reason)}</td></tr>"
        for t in trades
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate"/>
<title>MOM (Momentum) baseline — {html_mod.escape(stamp)}</title>
<style>
  :root {{
    --bg: #f7f6f2; --ink: #1c1b19; --muted: #5a574f; --line: #d4d0c4;
    --card: #ffffff; --accent: #2a4a5c; --accent-soft: #e8eef2;
    --ok: #2d6a4f; --ok-bg: #e8f2ec; --warn: #8a5a12; --warn-bg: #f7efe0;
    --fill: #f0eee6; --bad: #9b2226; --bad-bg: #fdecea;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: "Segoe UI", "Helvetica Neue", Georgia, serif;
    font-size: 15px; line-height: 1.55; color: var(--ink);
    background:
      radial-gradient(ellipse 80% 50% at 10% -10%, #e4ebe8 0%, transparent 55%),
      radial-gradient(ellipse 60% 40% at 100% 0%, #ebe6dc 0%, transparent 50%),
      var(--bg);
  }}
  .wrap {{ max-width: 1100px; margin: 0 auto; padding: 36px 24px 64px; }}
  header.doc-head {{ border-bottom: 2px solid var(--ink); padding-bottom: 14px; margin-bottom: 22px; }}
  .eyebrow {{
    font-size: 0.72rem; letter-spacing: 0.14em; text-transform: uppercase;
    color: var(--accent); font-weight: 650; margin: 0 0 6px;
  }}
  h1 {{ font-size: 1.55rem; margin: 0 0 6px; letter-spacing: -0.02em; line-height: 1.2; }}
  h2 {{ font-size: 1.12rem; margin: 26px 0 10px; padding-bottom: 5px; border-bottom: 1px solid var(--line); }}
  .lede {{ margin: 0; color: var(--muted); max-width: 72ch; }}
  .badge {{
    display: inline-block; font-size: 0.75rem; font-weight: 700;
    letter-spacing: 0.04em; padding: 2px 8px; margin: 10px 0 0;
  }}
  .badge-warn {{ background: var(--warn-bg); color: var(--warn); }}
  .badge-bad {{ background: var(--bad-bg); color: var(--bad); }}
  p, li {{ margin: 0 0 10px; }}
  ul {{ padding-left: 1.25rem; }}
  a {{ color: var(--accent); }}
  code {{ font-family: Consolas, "Cascadia Mono", monospace; font-size: 0.86em; background: var(--fill); padding: 0.08em 0.3em; }}
  .callout {{ background: var(--warn-bg); border-left: 4px solid var(--warn); padding: 12px 14px; margin: 14px 0 18px; }}
  .callout.bad {{ background: var(--bad-bg); border-left-color: var(--bad); }}
  .table-wrap {{ overflow-x: auto; margin: 8px 0 16px; }}
  table.sortable {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  th, td {{ border: 1px solid var(--line); padding: 7px 8px; text-align: left; }}
  thead th {{ background: var(--fill); }}
  {SORTABLE_TH_CSS}
  caption {{ text-align: left; font-size: 0.82rem; color: var(--muted); margin: 0 0 6px; caption-side: top; }}
  footer {{ margin-top: 28px; font-size: 0.8rem; color: var(--muted); border-top: 1px solid var(--line); padding-top: 12px; }}
</style>
</head>
<body>
<div class="wrap">
  <header class="doc-head">
    <p class="eyebrow">Paul experiments · research candidate</p>
    <h1>{html_mod.escape(title)}</h1>
    <p class="lede">Weekly volatility-adjusted momentum rank + Average True Range (ATR) sizing.
    Stamp <code>{html_mod.escape(stamp)}</code>. Universe N={univ_n}. Review=Wednesday. Index=SPY.
    Liquid ADV$2m supersedes ALL_ohlc as research freeze univ.</p>
    <span class="badge badge-bad">NOT GOLD</span>
    <span class="badge badge-warn">NOT DailyRun</span>
  </header>

  <div class="callout bad">
    <strong>Research candidate only.</strong> Static liquid tradable tape (not point-in-time S&amp;P 500).
    Sheet/Total PnL $ omitted from compare tables (quality metrics only).
  </div>

  <h2>System summary (click headers to sort)</h2>
  <div class="table-wrap">
  <table class="sortable">
    <caption>Full book vs IS (equity/trades before 2024-01-01) vs OOS (on/after). Equity slices use daily mark-to-market; trade rows use entry_date. Click column headers to sort.</caption>
    <thead><tr>{m_head}</tr></thead>
    <tbody>{m_body}</tbody>
  </table>
  </div>

  <h2>Exit mix</h2>
  <div class="table-wrap">
  <table class="sortable">
    <thead><tr>{exit_head}</tr></thead>
    <tbody>{exit_body}</tbody>
  </table>
  </div>

  <h2>Top symbols by sum PnL % (closed)</h2>
  <div class="table-wrap">
  <table class="sortable">
    <caption>Click column headers to sort.</caption>
    <thead><tr>{h_head}</tr></thead>
    <tbody>{h_body}</tbody>
  </table>
  </div>

  <h2>Recent / sample closed trades (first 200 by time)</h2>
  <div class="table-wrap">
  <table class="sortable">
    <thead><tr>{t_head}</tr></thead>
    <tbody>{t_body}</tbody>
  </table>
  </div>

  <h2>Freeze knobs</h2>
  <ul>
    <li>Momentum lookback {MOM_LOOKBACK}d · stock SMA{SMA_STOCK} · index SMA{SMA_INDEX} · ATR{ATR_N}</li>
    <li>Gap filter {GAP_MAX:.0%} / {GAP_LOOKBACK}d · top {TOP_FRAC:.0%} · risk {RISK_FRAC} · slip {SLIPPAGE_BPS:g} bps</li>
    <li>Calendar: {result['calendar_start']} → {result['calendar_end']} · reviews≈{result['n_reviews']}</li>
  </ul>

  <div class="callout">
    Re-run: <code>python tools/mom_clenow_ab.py --out drive/paul_experiments/{html_mod.escape(stamp)}</code>
  </div>

  <footer>drive/paul_experiments/{html_mod.escape(stamp)}/compare.html · {datetime.now().strftime("%Y-%m-%d %H:%M")}</footer>
</div>
{SORT_JS}
</body>
</html>
"""
    path = out / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def _delta(a: Any, b: Any) -> float:
    try:
        return float(b) - float(a)
    except (TypeError, ValueError):
        return float("nan")


def write_univ_ab_stamp(
    *,
    out: Path,
    control: dict[str, Any],
    candidate: dict[str, Any],
    control_univ: list[str],
    candidate_univ: list[str],
    control_path: Path,
    candidate_path: Path,
    label_a: str,
    label_b: str,
) -> list[Path]:
    """One-knob universe AB: same MOM freeze, only ADV$ cut differs."""
    out.mkdir(parents=True, exist_ok=True)
    stamp = out.name
    written: list[Path] = []

    a_dir = out / "control_adv2m"
    b_dir = out / "candidate_adv5m"
    written.extend(
        write_stamp(
            control,
            control_univ,
            control_path,
            a_dir,
            stamp=f"{stamp}__control",
            title=f"MOM control — {label_a}",
        )
    )
    written.extend(
        write_stamp(
            candidate,
            candidate_univ,
            candidate_path,
            b_dir,
            stamp=f"{stamp}__candidate",
            title=f"MOM candidate — {label_b}",
            univ_note=(
                f"- File: `{candidate_path.as_posix()}`\n"
                f"- **N = {len(candidate_univ)}** symbols\n"
                "- Same VZ tradable methodology as ADV$2m (`tools/vz_build_tradable_universe.py`): "
                "first bar ≤ 2010-01-04; Close ≥ $5 as-of **2023-12-29**; "
                "20-day ADV$ ≥ **$5,000,000** (one-knob lift from $2m)\n"
                "- Not PIT S&P 500"
            ),
        )
    )

    pa, pb = pack_metrics(control), pack_metrics(candidate)

    # IS pick on quality (Ann ROR, Avg PnL%, WR, PF, Max DD lower better) — no OOS in pick
    def _is_score(p: dict[str, Any]) -> tuple[float, float, float, float, float]:
        # higher better except max_dd (negate)
        is_m, tm = p["is_m"], p["tm_is"]
        return (
            float(is_m.get("ann_ror") or float("nan")),
            float(tm.get("avg_pnl_pct") or float("nan")),
            float(tm.get("win_rate") or float("nan")),
            float(tm.get("profit_factor") or float("nan")),
            -float(is_m.get("max_dd") or float("nan")),
        )

    score_a, score_b = _is_score(pa), _is_score(pb)
    # Lexicographic quality: prefer better Ann ROR then AvgPnL then WR then PF then lower DD
    is_pick = label_b if score_b > score_a else label_a

    # OOS validation: if candidate picked and OOS softens on Ann ROR or Avg PnL → HOLD
    oos_a_ann = float(pa["oos_m"].get("ann_ror") or float("nan"))
    oos_b_ann = float(pb["oos_m"].get("ann_ror") or float("nan"))
    oos_a_avg = float(pa["tm_oos"].get("avg_pnl_pct") or float("nan"))
    oos_b_avg = float(pb["tm_oos"].get("avg_pnl_pct") or float("nan"))
    oos_softens = False
    if is_pick == label_b:
        if (np.isfinite(oos_a_ann) and np.isfinite(oos_b_ann) and oos_b_ann < oos_a_ann - 0.25) or (
            np.isfinite(oos_a_avg) and np.isfinite(oos_b_avg) and oos_b_avg < oos_a_avg - 0.15
        ):
            oos_softens = True
    if is_pick == label_a:
        # control already preferred on IS; still note if candidate OOS is worse (expected)
        oos_softens = False
    verdict = "HOLD" if (is_pick == label_b and oos_softens) else (
        "LEAN KEEP candidate" if is_pick == label_b else "KEEP control (ADV$2m)"
    )
    if is_pick == label_b and not oos_softens:
        # Check flat / tiny lift
        if abs(score_b[0] - score_a[0]) < 0.15 and abs(score_b[1] - score_a[1]) < 0.1:
            verdict = "HOLD (IS flat)"

    dropped = sorted(set(control_univ) - set(candidate_univ))

    rows_spec = [
        ("Universe N", len(control_univ), len(candidate_univ), "num"),
        ("IS Ann ROR %", pa["is_m"].get("ann_ror"), pb["is_m"].get("ann_ror"), "num"),
        ("IS Max DD %", pa["is_m"].get("max_dd"), pb["is_m"].get("max_dd"), "num"),
        ("IS Calmar", pa["is_m"].get("calmar"), pb["is_m"].get("calmar"), "num"),
        ("IS Sharpe", pa["is_m"].get("sharpe"), pb["is_m"].get("sharpe"), "num"),
        ("IS Total ret %", pa["is_m"].get("total_ret_pct"), pb["is_m"].get("total_ret_pct"), "num"),
        ("IS trades N", pa["tm_is"].get("n"), pb["tm_is"].get("n"), "num"),
        ("IS Win rate %", pa["tm_is"].get("win_rate"), pb["tm_is"].get("win_rate"), "num"),
        ("IS Avg PnL %", pa["tm_is"].get("avg_pnl_pct"), pb["tm_is"].get("avg_pnl_pct"), "num"),
        ("IS Avg days", pa["tm_is"].get("avg_days"), pb["tm_is"].get("avg_days"), "num"),
        ("IS Profit factor", pa["tm_is"].get("profit_factor"), pb["tm_is"].get("profit_factor"), "num"),
        ("OOS Ann ROR %", pa["oos_m"].get("ann_ror"), pb["oos_m"].get("ann_ror"), "num"),
        ("OOS Max DD %", pa["oos_m"].get("max_dd"), pb["oos_m"].get("max_dd"), "num"),
        ("OOS Calmar", pa["oos_m"].get("calmar"), pb["oos_m"].get("calmar"), "num"),
        ("OOS Sharpe", pa["oos_m"].get("sharpe"), pb["oos_m"].get("sharpe"), "num"),
        ("OOS Total ret %", pa["oos_m"].get("total_ret_pct"), pb["oos_m"].get("total_ret_pct"), "num"),
        ("OOS trades N", pa["tm_oos"].get("n"), pb["tm_oos"].get("n"), "num"),
        ("OOS Win rate %", pa["tm_oos"].get("win_rate"), pb["tm_oos"].get("win_rate"), "num"),
        ("OOS Avg PnL %", pa["tm_oos"].get("avg_pnl_pct"), pb["tm_oos"].get("avg_pnl_pct"), "num"),
        ("OOS Avg days", pa["tm_oos"].get("avg_days"), pb["tm_oos"].get("avg_days"), "num"),
        ("OOS Profit factor", pa["tm_oos"].get("profit_factor"), pb["tm_oos"].get("profit_factor"), "num"),
        ("Full Ann ROR %", pa["full_m"].get("ann_ror"), pb["full_m"].get("ann_ror"), "num"),
        ("Full Max DD %", pa["full_m"].get("max_dd"), pb["full_m"].get("max_dd"), "num"),
        ("Full Calmar", pa["full_m"].get("calmar"), pb["full_m"].get("calmar"), "num"),
        ("Full Sharpe", pa["full_m"].get("sharpe"), pb["full_m"].get("sharpe"), "num"),
        ("Full trades N", pa["tm_all"].get("n"), pb["tm_all"].get("n"), "num"),
        ("Full Win rate %", pa["tm_all"].get("win_rate"), pb["tm_all"].get("win_rate"), "num"),
        ("Full Avg PnL %", pa["tm_all"].get("avg_pnl_pct"), pb["tm_all"].get("avg_pnl_pct"), "num"),
        ("Full Profit factor", pa["tm_all"].get("profit_factor"), pb["tm_all"].get("profit_factor"), "num"),
    ]
    rows_spec = [r for r in rows_spec if not is_excluded_html_compare_label(r[0])]

    head = (
        _sortable_th("Metric", "text")
        + _sortable_th(label_a, "num")
        + _sortable_th(label_b, "num")
        + _sortable_th("Δ (B−A)", "num")
    )
    body = ""
    for name, va, vb, _st in rows_spec:
        d = _delta(va, vb)
        body += (
            f"<tr><td>{html_mod.escape(name)}</td>"
            f"<td>{_fmt_metric(va)}</td><td>{_fmt_metric(vb)}</td>"
            f"<td>{_fmt_metric(d)}</td></tr>"
        )

    baseline = f"""# BASELINE — `{stamp}`

**Status:** RESEARCH only. **Not gold. Not DailyRun.** One-knob **universe** AB (ENTRY univ cut). Exit / MOM knobs frozen.

## Hypothesis

Raising the liquid ADV$ floor from **$2m → $5m** (same as-of methodology) improves MOM quality without collapsing N.

## Control vs candidate

| Arm | Label | Universe | N |
|-----|-------|----------|---|
| Control | {label_a} | `{control_path.as_posix()}` | {len(control_univ)} |
| Candidate | {label_b} | `{candidate_path.as_posix()}` | {len(candidate_univ)} |

### ADV$5m cut (exact)

- Same builder methodology as `tools/vz_build_tradable_universe.py`
- first_bar ≤ **2010-01-04**
- as-of **2023-12-29** (last session on/before): Close ≥ **$5**; 20-session ADV$ = mean(Close×Volume) ≥ **$5,000,000**
- Built by filtering the ADV$2m screen reject/pass table (`vz_tradable_2010_adv2m_20260818/universe_rejects.csv`) to `pass=Y` and `adv20_usd >= 5e6`
- Symbols dropped vs ADV$2m (N={len(dropped)}): `{', '.join(dropped)}`

## Frozen MOM knobs (unchanged)

Same as `mom_baseline_liquid_20260829` / `mom_baseline_20260828`: SMA100 exit, SPY SMA200 new buys, 90d vol-adj mom × R², top 20%, gap 15%/90d, ATR sizing 0.001, Wednesday review + biweekly resize, no hard stop.

## IS / OOS policy

- **IS pick** on quality (Ann ROR, Avg PnL%, WR, PF, Max DD) — not trade count
- **OOS report-only**; if OOS softens vs control → **HOLD** (do not retune)
- Split: IS entry/equity `< 2024-01-01`; OOS `≥ 2024-01-01`

## Selection / verdict (frozen after this stamp)

- **IS pick:** {is_pick}
- **OOS softens (if candidate picked):** {oos_softens}
- **Verdict:** **{verdict}**
- Research candidate ≠ gold ≠ DailyRun

## Blockers

1. No point-in-time S&P 500 membership (static liquid tape / survivorship vs classic Clenow)
2. Thin univ delta (only {len(dropped)} names between $2m and $5m on this tape) — power limited
"""
    (out / "BASELINE.md").write_text(baseline, encoding="utf-8")
    written.append(out / "BASELINE.md")

    summary = f"""# SUMMARY — `{stamp}`

One-knob MOM universe AB: **{label_a}** (control) vs **{label_b}** (candidate). Same MOM freeze.

## Verdict

- **IS pick:** {is_pick}
- **OOS softens:** {oos_softens}
- **Final:** **{verdict}**
- Research only — not gold / not DailyRun

## Headlines

| Slice | {label_a} Ann ROR | {label_b} Ann ROR | {label_a} AvgPnL% | {label_b} AvgPnL% |
|-------|-------------------|-------------------|-------------------|-------------------|
| IS | {_fmt_metric(pa['is_m'].get('ann_ror'))} | {_fmt_metric(pb['is_m'].get('ann_ror'))} | {_fmt_metric(pa['tm_is'].get('avg_pnl_pct'))} | {_fmt_metric(pb['tm_is'].get('avg_pnl_pct'))} |
| OOS | {_fmt_metric(pa['oos_m'].get('ann_ror'))} | {_fmt_metric(pb['oos_m'].get('ann_ror'))} | {_fmt_metric(pa['tm_oos'].get('avg_pnl_pct'))} | {_fmt_metric(pb['tm_oos'].get('avg_pnl_pct'))} |

## Artifacts

- `compare.html` — sortable control vs candidate
- `control_adv2m/` / `candidate_adv5m/` — full single-arm stamps
- `BASELINE.md` / `SUMMARY.md`
"""
    (out / "SUMMARY.md").write_text(summary, encoding="utf-8")
    written.append(out / "SUMMARY.md")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate"/>
<title>MOM univ AB ADV$2m vs ADV$5m — {html_mod.escape(stamp)}</title>
<style>
  :root {{
    --bg: #f7f6f2; --ink: #1c1b19; --muted: #5a574f; --line: #d4d0c4;
    --accent: #2a4a5c; --warn: #8a5a12; --warn-bg: #f7efe0;
    --fill: #f0eee6; --bad: #9b2226; --bad-bg: #fdecea; --ok: #2d6a4f; --ok-bg: #e8f2ec;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; font-family: "Segoe UI", "Helvetica Neue", Georgia, serif;
    font-size: 15px; line-height: 1.55; color: var(--ink);
    background:
      radial-gradient(ellipse 80% 50% at 10% -10%, #e4ebe8 0%, transparent 55%),
      radial-gradient(ellipse 60% 40% at 100% 0%, #ebe6dc 0%, transparent 50%),
      var(--bg);
  }}
  .wrap {{ max-width: 1100px; margin: 0 auto; padding: 36px 24px 64px; }}
  header.doc-head {{ border-bottom: 2px solid var(--ink); padding-bottom: 14px; margin-bottom: 22px; }}
  .eyebrow {{ font-size: 0.72rem; letter-spacing: 0.14em; text-transform: uppercase; color: var(--accent); font-weight: 650; margin: 0 0 6px; }}
  h1 {{ font-size: 1.55rem; margin: 0 0 6px; letter-spacing: -0.02em; }}
  h2 {{ font-size: 1.12rem; margin: 26px 0 10px; padding-bottom: 5px; border-bottom: 1px solid var(--line); }}
  .lede {{ margin: 0; color: var(--muted); max-width: 72ch; }}
  .badge {{ display: inline-block; font-size: 0.75rem; font-weight: 700; letter-spacing: 0.04em; padding: 2px 8px; margin: 10px 4px 0 0; }}
  .badge-warn {{ background: var(--warn-bg); color: var(--warn); }}
  .badge-bad {{ background: var(--bad-bg); color: var(--bad); }}
  .badge-ok {{ background: var(--ok-bg); color: var(--ok); }}
  .callout {{ background: var(--warn-bg); border-left: 4px solid var(--warn); padding: 12px 14px; margin: 14px 0 18px; }}
  .callout.bad {{ background: var(--bad-bg); border-left-color: var(--bad); }}
  .table-wrap {{ overflow-x: auto; margin: 8px 0 16px; }}
  table.sortable {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  th, td {{ border: 1px solid var(--line); padding: 7px 8px; text-align: left; }}
  thead th {{ background: var(--fill); }}
  {SORTABLE_TH_CSS}
  caption {{ text-align: left; font-size: 0.82rem; color: var(--muted); margin: 0 0 6px; caption-side: top; }}
  footer {{ margin-top: 28px; font-size: 0.8rem; color: var(--muted); border-top: 1px solid var(--line); padding-top: 12px; }}
  code {{ font-family: Consolas, monospace; font-size: 0.86em; background: var(--fill); padding: 0.08em 0.3em; }}
</style>
</head>
<body>
<div class="wrap">
  <header class="doc-head">
    <p class="eyebrow">Paul experiments · one-knob universe AB</p>
    <h1>MOM — ADV$2m vs ADV$5m</h1>
    <p class="lede">Same Momentum / Clenow freeze; only liquid ADV$ floor changes.
    Stamp <code>{html_mod.escape(stamp)}</code>. Dropped vs $2m: {len(dropped)} names.</p>
    <span class="badge badge-bad">NOT GOLD</span>
    <span class="badge badge-warn">NOT DailyRun</span>
    <span class="badge badge-ok">{html_mod.escape(verdict)}</span>
  </header>

  <div class="callout">
    <strong>IS pick:</strong> {html_mod.escape(is_pick)}.
    <strong>OOS softens:</strong> {oos_softens}.
    OOS is report-only — do not retune. Sheet/Total PnL $ omitted.
  </div>

  <h2>Control vs candidate (click headers to sort)</h2>
  <div class="table-wrap">
  <table class="sortable">
    <caption>IS for pick; OOS validation only. Click column headers to sort.</caption>
    <thead><tr>{head}</tr></thead>
    <tbody>{body}</tbody>
  </table>
  </div>

  <h2>Cut documentation</h2>
  <ul>
    <li>as-of 2023-12-29 · first_bar ≤ 2010-01-04 · Close ≥ $5</li>
    <li>Control ADV$ ≥ $2,000,000 · Candidate ADV$ ≥ $5,000,000</li>
    <li>Dropped: {html_mod.escape(', '.join(dropped))}</li>
  </ul>

  <div class="callout bad">
    Blockers: no PIT S&amp;P 500; static liquid tape / survivorship vs classic Clenow.
  </div>

  <footer>drive/paul_experiments/{html_mod.escape(stamp)}/compare.html · {datetime.now().strftime("%Y-%m-%d %H:%M")}</footer>
</div>
{SORT_JS}
</body>
</html>
"""
    hp = out / "compare.html"
    hp.write_text(html, encoding="utf-8")
    written.append(hp)

    meta = {
        "stamp": stamp,
        "is_pick": is_pick,
        "oos_softens": oos_softens,
        "verdict": verdict,
        "dropped": dropped,
        "label_a": label_a,
        "label_b": label_b,
        "n_a": len(control_univ),
        "n_b": len(candidate_univ),
    }
    (out / "ab_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    written.append(out / "ab_meta.json")
    return written


def _run_one(
    *,
    db: Path,
    univ: list[str],
    start: Optional[date],
    end: Optional[date],
    capital: float,
    tag: str,
) -> tuple[dict[str, Any], list[str]]:
    print(f"[MOM:{tag}] Loading panel for {len(univ)} + {INDEX_SYM} from {db} ...")
    panel = load_panel(db, univ, start=start, end=end)
    loaded = [s for s in univ if s in panel]
    missing = [s for s in univ if s not in panel]
    print(
        f"[MOM:{tag}] Loaded {len(loaded)} / {len(univ)}; "
        f"SPY={'yes' if INDEX_SYM in panel else 'NO'}; missing={len(missing)}"
    )
    if missing[:8]:
        print(f"[MOM:{tag}] Missing sample: {', '.join(missing[:8])}...")
    print(f"[MOM:{tag}] Running backtest ...")
    result = run_backtest(panel, loaded, initial_capital=capital, bt_start=start, bt_end=end)
    print(
        f"[MOM:{tag}] Done. Trades={len(result['trades'])} events={len(result['events'])} "
        f"final_eq={result['final_equity']:.2f}"
    )
    return result, loaded


def main() -> int:
    ap = argparse.ArgumentParser(description="MOM (Momentum) Clenow research backtest")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--universe", type=Path, default=DEFAULT_UNIV)
    ap.add_argument(
        "--universe-b",
        type=Path,
        default=None,
        help="If set, run one-knob universe AB vs --universe (control)",
    )
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    ap.add_argument("--label", type=str, default="ADV$2m", help="Control arm label")
    ap.add_argument("--label-b", type=str, default="ADV$5m", help="Candidate arm label")
    ap.add_argument("--start", type=str, default="2010-01-04")
    ap.add_argument("--end", type=str, default=None)
    ap.add_argument("--limit", type=int, default=0, help="Limit universe size (smoke test)")
    ap.add_argument("--capital", type=float, default=DEFAULT_INITIAL_ACCOUNT)
    args = ap.parse_args()

    univ = load_universe(args.universe)
    if args.limit and args.limit > 0:
        univ = univ[: args.limit]
        print(f"[MOM] smoke limit -> {len(univ)} symbols")

    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None

    if args.universe_b is None:
        result, _loaded = _run_one(
            db=args.db, univ=univ, start=start, end=end, capital=args.capital, tag="A"
        )
        written = write_stamp(result, univ, args.universe, args.out, stamp=args.out.name)
        print(f"[MOM] Wrote {len(written)} artifacts under {args.out}")
        for p in written:
            try:
                print(f"  {p.relative_to(_REPO)}")
            except ValueError:
                print(f"  {p}")
        return 0

    univ_b = load_universe(args.universe_b)
    if args.limit and args.limit > 0:
        univ_b = [s for s in univ_b if s in set(univ)][: args.limit]
        print(f"[MOM] smoke limit B -> {len(univ_b)} symbols")

    # Load once for union to save I/O when B ⊂ A
    union = sorted(set(univ) | set(univ_b))
    print(f"[MOM:AB] Loading union panel N={len(union)} ...")
    panel = load_panel(args.db, union, start=start, end=end)
    loaded_a = [s for s in univ if s in panel]
    loaded_b = [s for s in univ_b if s in panel]
    print(f"[MOM:AB] A loaded {len(loaded_a)}/{len(univ)}; B loaded {len(loaded_b)}/{len(univ_b)}")

    print("[MOM:AB] Running control ...")
    control = run_backtest(panel, loaded_a, initial_capital=args.capital, bt_start=start, bt_end=end)
    print(
        f"[MOM:AB] Control done trades={len(control['trades'])} final_eq={control['final_equity']:.2f}"
    )
    print("[MOM:AB] Running candidate ...")
    candidate = run_backtest(panel, loaded_b, initial_capital=args.capital, bt_start=start, bt_end=end)
    print(
        f"[MOM:AB] Candidate done trades={len(candidate['trades'])} final_eq={candidate['final_equity']:.2f}"
    )

    written = write_univ_ab_stamp(
        out=args.out,
        control=control,
        candidate=candidate,
        control_univ=univ,
        candidate_univ=univ_b,
        control_path=args.universe,
        candidate_path=args.universe_b,
        label_a=args.label,
        label_b=args.label_b,
    )
    print(f"[MOM:AB] Wrote {len(written)} artifacts under {args.out}")
    for p in written:
        try:
            print(f"  {p.relative_to(_REPO)}")
        except ValueError:
            print(f"  {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
