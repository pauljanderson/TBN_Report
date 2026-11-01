#!/usr/bin/env python3
"""PaulTwenty cumulative trendline-slope signal backtest.

Signal (primary):
  For each symbol×day, sum slope_pct_per_day across all active fractal lines
  (up to 6 = daily/weekly/monthly × support/resistance). That cross-sectional
  sum is the 'cumulative' input Paul asked for (NOT a running sum over history).

  Buy  when sum turns positive: prior day ≤ 0 and today > 0
  Sell when sum turns negative: prior day ≥ 0 and today < 0
  Long-only; flat days earn 0. Transaction costs = 0.

Execution: next-open fill after signal day (look-ahead safe vs same-day close).
Benchmark: equal-weight daily total return of PaulTwenty (daily rebalance).

Research only — not gold, not DailyRun.

Usage:
  python tools/trendline_cum_slope_signal_bt.py
"""
from __future__ import annotations

import html as html_mod
import math
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "newdata" / "data"
DRIVE = ROOT / "drive"
PAULTWENTY = DRIVE / "universes" / "PaulTwenty_universe.csv"
SLOPES_CSV = (
    DRIVE
    / "paul_experiments"
    / "trendline_slopes_paultwenty_20260831"
    / "trendline_slopes_long.csv"
)
STAMP = "trendline_cum_slope_signal_paultwenty_20260831"
OUT_DIR = DRIVE / "paul_experiments" / STAMP
IS_CUTOFF = pd.Timestamp("2024-01-01")
TRADING_DAYS_PER_YEAR = 252

SORT_CSS = """
th.sortable-th { cursor: pointer; user-select: none; white-space: nowrap; }
th.sortable-th:hover { background: #e2e8f0; }
th.sortable-th .sort-ind::after { content: " \\2195"; opacity: .35; font-size: .85em; }
th.sortable-th.sort-asc .sort-ind::after { content: " \\2191"; opacity: .9; }
th.sortable-th.sort-desc .sort-ind::after { content: " \\2193"; opacity: .9; }
body { font-family: Segoe UI, system-ui, sans-serif; margin: 1.5rem; color: #0f172a; background: #f8fafc; }
h1 { font-size: 1.45rem; margin: 0 0 .35rem; }
h2 { font-size: 1.15rem; margin: 1.6rem 0 .5rem; border-bottom: 1px solid #cbd5e1; padding-bottom: .25rem; }
.meta, .caveat { color: #475569; font-size: .92rem; max-width: 72rem; }
.insight { background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: .75rem 1rem; margin: .75rem 0; max-width: 72rem; }
.badge { display: inline-block; padding: .1rem .45rem; border-radius: 4px; font-size: .8rem; background: #e2e8f0; }
.up { color: #047857; font-weight: 600; }
.down { color: #b91c1c; font-weight: 600; }
table.sortable { border-collapse: collapse; background: #fff; font-size: .88rem; margin: .5rem 0 1rem; }
table.sortable th, table.sortable td { border: 1px solid #e2e8f0; padding: .35rem .55rem; text-align: left; }
table.sortable th { background: #f1f5f9; }
.chart-wrap { max-width: 72rem; margin: 1rem 0; background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: .75rem; }
svg.eq { width: 100%; height: auto; display: block; }
"""

SORT_JS = r"""
<script>
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : 0;
    if (type === "text") return s.toUpperCase();
    if (type === "date") {
      var iso = s.match(/(\d{4})-(\d{2})-(\d{2})/);
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
</script>
"""


def sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def load_universe(path: Path) -> list[str]:
    out: list[str] = []
    with path.open(encoding="utf-8-sig") as f:
        for line in f:
            s = line.strip().upper()
            if not s or s.startswith("#") or s == "SYMBOL":
                continue
            out.append(s.split(",")[0].strip())
    return out


def load_ohlc(sym: str) -> Optional[pd.DataFrame]:
    path = DATA_DIR / f"{sym}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path)
    cols = {str(c).lower(): c for c in df.columns}
    need = ("date", "open", "high", "low", "close")
    if not all(k in cols for k in need):
        return None
    out = pd.DataFrame(
        {
            "Date": pd.to_datetime(df[cols["date"]]).dt.normalize(),
            "Open": df[cols["open"]].astype(float),
            "High": df[cols["high"]].astype(float),
            "Low": df[cols["low"]].astype(float),
            "Close": df[cols["close"]].astype(float),
        }
    )
    return out.sort_values("Date").drop_duplicates("Date").reset_index(drop=True)


def max_drawdown(equity: np.ndarray) -> float:
    if len(equity) == 0:
        return float("nan")
    peak = np.maximum.accumulate(equity)
    dd = equity / peak - 1.0
    return float(dd.min())


def ann_ror_from_total(total_ret: float, n_days: int) -> float:
    if n_days <= 0 or not np.isfinite(total_ret) or total_ret <= -1.0:
        return float("nan")
    years = n_days / TRADING_DAYS_PER_YEAR
    if years <= 0:
        return float("nan")
    return float((1.0 + total_ret) ** (1.0 / years) - 1.0)


def sharpe_from_daily(rets: np.ndarray) -> float:
    r = rets[np.isfinite(rets)]
    if len(r) < 2:
        return float("nan")
    sd = float(np.std(r, ddof=1))
    if sd <= 0:
        return float("nan")
    return float(np.mean(r) / sd * math.sqrt(TRADING_DAYS_PER_YEAR))


def metrics_from_daily(
    dates: pd.Series,
    strat_ret: np.ndarray,
    bh_ret: np.ndarray,
    position: np.ndarray,
    n_buys: int,
    n_sells: int,
    label: str,
) -> dict:
    strat_eq = np.cumprod(1.0 + strat_ret)
    bh_eq = np.cumprod(1.0 + bh_ret)
    strat_total = float(strat_eq[-1] - 1.0) if len(strat_eq) else float("nan")
    bh_total = float(bh_eq[-1] - 1.0) if len(bh_eq) else float("nan")
    n = len(strat_ret)
    # position may be 0/1 flags or a portfolio fraction in [0,1]
    tim = float(np.mean(position)) if n else float("nan")
    return {
        "slice": label,
        "start": str(dates.iloc[0].date()) if n else "",
        "end": str(dates.iloc[-1].date()) if n else "",
        "n_days": n,
        "strat_total_ret": strat_total,
        "bh_total_ret": bh_total,
        "delta_total_ret": strat_total - bh_total if np.isfinite(strat_total) and np.isfinite(bh_total) else float("nan"),
        "strat_ann_ror": ann_ror_from_total(strat_total, n),
        "bh_ann_ror": ann_ror_from_total(bh_total, n),
        "delta_ann_ror": (
            ann_ror_from_total(strat_total, n) - ann_ror_from_total(bh_total, n)
            if np.isfinite(strat_total) and np.isfinite(bh_total)
            else float("nan")
        ),
        "strat_max_dd": max_drawdown(strat_eq),
        "bh_max_dd": max_drawdown(bh_eq),
        "delta_max_dd": (
            max_drawdown(strat_eq) - max_drawdown(bh_eq)
            if len(strat_eq) and len(bh_eq)
            else float("nan")
        ),
        "strat_sharpe": sharpe_from_daily(strat_ret),
        "bh_sharpe": sharpe_from_daily(bh_ret),
        "delta_sharpe": (
            sharpe_from_daily(strat_ret) - sharpe_from_daily(bh_ret)
            if len(strat_ret) and len(bh_ret)
            else float("nan")
        ),
        "time_in_market": tim,
        "n_buys": n_buys,
        "n_sells": n_sells,
    }


def fmt_pct(x: float, digits: int = 2) -> str:
    if x is None or not np.isfinite(x):
        return "—"
    return f"{100.0 * x:.{digits}f}%"


def fmt_pct_signed(x: float, digits: int = 2) -> str:
    if x is None or not np.isfinite(x):
        return "—"
    return f"{100.0 * x:+.{digits}f}%"


def fmt_num(x: float, digits: int = 2) -> str:
    if x is None or not np.isfinite(x):
        return "—"
    return f"{x:.{digits}f}"


def svg_equity_chart(
    dates: pd.Series,
    strat_eq: np.ndarray,
    bh_eq: np.ndarray,
    width: int = 900,
    height: int = 320,
) -> str:
    if len(dates) < 2:
        return "<p class='meta'>Not enough points for chart.</p>"
    pad_l, pad_r, pad_t, pad_b = 52, 16, 16, 36
    xs = np.linspace(pad_l, width - pad_r, len(dates))
    y_all = np.concatenate([strat_eq, bh_eq])
    ymin, ymax = float(np.nanmin(y_all)), float(np.nanmax(y_all))
    if ymin == ymax:
        ymax = ymin + 1e-6
    def ymap(v: float) -> float:
        return pad_t + (1.0 - (v - ymin) / (ymax - ymin)) * (height - pad_t - pad_b)

    def path(eq: np.ndarray) -> str:
        pts = [f"{xs[i]:.1f},{ymap(float(eq[i])):.1f}" for i in range(len(eq))]
        return "M " + " L ".join(pts)

    # sparse x labels
    n_lab = 6
    lab_idx = np.linspace(0, len(dates) - 1, n_lab).astype(int)
    labels = []
    for i in lab_idx:
        labels.append(
            f'<text x="{xs[i]:.1f}" y="{height - 10}" text-anchor="middle" '
            f'font-size="11" fill="#64748b">{dates.iloc[i].strftime("%Y-%m")}</text>'
        )
    y_ticks = np.linspace(ymin, ymax, 5)
    ylabs = []
    for v in y_ticks:
        ylabs.append(
            f'<text x="{pad_l - 6}" y="{ymap(float(v)) + 4:.1f}" text-anchor="end" '
            f'font-size="11" fill="#64748b">{v:.2f}</text>'
            f'<line x1="{pad_l}" y1="{ymap(float(v)):.1f}" x2="{width - pad_r}" '
            f'y2="{ymap(float(v)):.1f}" stroke="#e2e8f0" stroke-width="1"/>'
        )
    return f"""
<svg class="eq" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Equity curves">
  <rect x="0" y="0" width="{width}" height="{height}" fill="#fff"/>
  {''.join(ylabs)}
  <path d="{path(bh_eq)}" fill="none" stroke="#94a3b8" stroke-width="2"/>
  <path d="{path(strat_eq)}" fill="none" stroke="#0369a1" stroke-width="2.25"/>
  {''.join(labels)}
  <rect x="{width - 210}" y="12" width="12" height="12" fill="#0369a1"/>
  <text x="{width - 194}" y="22" font-size="12" fill="#334155">Strategy</text>
  <rect x="{width - 120}" y="12" width="12" height="12" fill="#94a3b8"/>
  <text x="{width - 104}" y="22" font-size="12" fill="#334155">Buy&amp;hold EW</text>
</svg>
"""


def build_daily_signal(slopes: pd.DataFrame) -> pd.DataFrame:
    """Sum slope_pct_per_day across TF×side per symbol×date; emit flip signals."""
    g = (
        slopes.groupby(["symbol", "date"], as_index=False)
        .agg(
            slope_sum=("slope_pct_per_day", "sum"),
            n_lines=("slope_pct_per_day", "count"),
        )
        .sort_values(["symbol", "date"])
        .reset_index(drop=True)
    )
    g["date"] = pd.to_datetime(g["date"]).dt.normalize()
    rows = []
    for sym, sg in g.groupby("symbol", sort=False):
        sg = sg.copy()
        prev = sg["slope_sum"].shift(1)
        # Buy: was ≤0, now >0; Sell: was ≥0, now <0
        buy = (prev <= 0) & (sg["slope_sum"] > 0)
        sell = (prev >= 0) & (sg["slope_sum"] < 0)
        # First day: if positive treat as buy (enter), if negative stay flat
        first_mask = prev.isna()
        buy = buy | (first_mask & (sg["slope_sum"] > 0))
        sell = sell | (first_mask & (sg["slope_sum"] < 0))
        signal = np.where(buy, "BUY", np.where(sell, "SELL", ""))
        # Position target after signal (held until opposite flip)
        pos = []
        cur = 0
        for b, s, ss in zip(buy.to_numpy(), sell.to_numpy(), sg["slope_sum"].to_numpy()):
            if b:
                cur = 1
            elif s:
                cur = 0
            # else hold prior; also if no flip but sum positive and never entered — stay flat until buy
            pos.append(cur)
        sg["signal"] = signal
        sg["target_pos"] = pos  # desired position after signal day (filled next open)
        sg["run_cum_slope_sum"] = sg["slope_sum"].cumsum()
        rows.append(sg)
    return pd.concat(rows, ignore_index=True)


def backtest_symbol(
    sym: str,
    sig: pd.DataFrame,
    ohlc: pd.DataFrame,
) -> tuple[pd.DataFrame, dict]:
    """Next-open execution: signal on day t → position from open[t+1] through close[t+1] ... until exit."""
    o = ohlc.copy()
    o["Date"] = pd.to_datetime(o["Date"]).dt.normalize()
    s = sig.copy()
    s["date"] = pd.to_datetime(s["date"]).dt.normalize()
    m = o.merge(s, left_on="Date", right_on="date", how="left")
    m["slope_sum"] = m["slope_sum"].fillna(0.0)
    m["n_lines"] = m["n_lines"].fillna(0).astype(int)
    m["signal"] = m["signal"].fillna("")
    m["target_pos"] = m["target_pos"].ffill().fillna(0).astype(int)

    # Execution position: lag target by 1 day (next open)
    m["exec_pos"] = m["target_pos"].shift(1).fillna(0).astype(int)
    # Daily strategy return: when long overnight into today, earn open→close? Prefer close-to-close
    # while in position. Standard: position decided before open → earn today's open-to-open or close-to-close.
    # Documented: enter next open; while long, use close-to-close returns for days fully in market;
    # entry day: open→close; exit day: prior close→open (sell at open).
    close = m["Close"].to_numpy(dtype=float)
    open_ = m["Open"].to_numpy(dtype=float)
    pos = m["exec_pos"].to_numpy(dtype=int)
    n = len(m)
    strat = np.zeros(n, dtype=float)
    for i in range(1, n):
        if pos[i] == 1 and pos[i - 1] == 0:
            # entry at today's open → open to close
            if open_[i] > 0 and np.isfinite(open_[i]) and np.isfinite(close[i]):
                strat[i] = close[i] / open_[i] - 1.0
        elif pos[i] == 1 and pos[i - 1] == 1:
            # hold: close-to-close
            if close[i - 1] > 0 and np.isfinite(close[i - 1]) and np.isfinite(close[i]):
                strat[i] = close[i] / close[i - 1] - 1.0
        elif pos[i] == 0 and pos[i - 1] == 1:
            # exit at today's open → prior close to open
            if close[i - 1] > 0 and np.isfinite(close[i - 1]) and np.isfinite(open_[i]):
                strat[i] = open_[i] / close[i - 1] - 1.0
        # else flat: 0

    # Buy-hold: close-to-close always
    bh = np.zeros(n, dtype=float)
    for i in range(1, n):
        if close[i - 1] > 0 and np.isfinite(close[i - 1]) and np.isfinite(close[i]):
            bh[i] = close[i] / close[i - 1] - 1.0

    m["strat_ret"] = strat
    m["bh_ret"] = bh
    m["symbol"] = sym

    buys = int(((m["signal"] == "BUY")).sum())
    sells = int(((m["signal"] == "SELL")).sum())
    # Per-symbol contribution proxy: total strat return vs bh
    strat_total = float(np.prod(1.0 + strat) - 1.0)
    bh_total = float(np.prod(1.0 + bh) - 1.0)
    meta = {
        "symbol": sym,
        "n_days": n,
        "n_buys": buys,
        "n_sells": sells,
        "strat_total_ret": strat_total,
        "bh_total_ret": bh_total,
        "delta_total_ret": strat_total - bh_total,
        "time_in_market": float(np.mean(pos > 0)) if n else float("nan"),
        "strat_max_dd": max_drawdown(np.cumprod(1.0 + strat)),
        "bh_max_dd": max_drawdown(np.cumprod(1.0 + bh)),
    }
    return m, meta


def portfolio_equal_weight(daily_by_sym: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Equal-weight across symbols present that day (strategy & BH)."""
    frames = []
    for sym, df in daily_by_sym.items():
        frames.append(
            df[["Date", "strat_ret", "bh_ret", "exec_pos", "signal", "slope_sum", "n_lines", "run_cum_slope_sum"]].assign(
                symbol=sym
            )
        )
    all_d = pd.concat(frames, ignore_index=True)
    # Portfolio daily: mean of available symbol returns that day
    port = (
        all_d.groupby("Date", as_index=False)
        .agg(
            strat_ret=("strat_ret", "mean"),
            bh_ret=("bh_ret", "mean"),
            n_symbols=("symbol", "nunique"),
            n_long=("exec_pos", "sum"),
            mean_slope_sum=("slope_sum", "mean"),
            mean_n_lines=("n_lines", "mean"),
            n_buys=("signal", lambda s: int((s == "BUY").sum())),
            n_sells=("signal", lambda s: int((s == "SELL").sum())),
        )
        .sort_values("Date")
        .reset_index(drop=True)
    )
    port["position_frac"] = port["n_long"] / port["n_symbols"].clip(lower=1)
    port["strat_eq"] = (1.0 + port["strat_ret"]).cumprod()
    port["bh_eq"] = (1.0 + port["bh_ret"]).cumprod()
    port["run_cum_mean_slope"] = port["mean_slope_sum"].cumsum()
    return port, all_d


def count_flips_in_slice(all_d: pd.DataFrame, mask: pd.Series) -> tuple[int, int]:
    sub = all_d.loc[mask]
    return int((sub["signal"] == "BUY").sum()), int((sub["signal"] == "SELL").sum())


def write_baseline(path: Path, period: str, n_sym: int) -> None:
    text = f"""# BASELINE — {STAMP}

Research only. Not gold. Not DailyRun. No knobs tuned on OOS.

## Hypothesis

Cross-sectional sum of active fractal trendline `slope_pct_per_day` (all timeframes × sides) carries a timing signal: go long when the sum **turns positive**, exit when it **turns negative**.

## Cumulative definition (primary signal input)

**Sum across TF × side on that day** for each symbol — i.e. sum of up to 6 active lines' `slope_pct_per_day` values on date *t*.

- This is **not** a running cumulative sum over history for the signal.
- Missing lines on a day: sum what is available (0 if none).
- Secondary diagnostic only: running cumulative sum of that daily aggregate over time (charts/CSV column `run_cum_*`); **not** used for buys/sells.

## TF (timeframe)

Mentioned once here: **TF** = timeframe. Lines come from daily / weekly / monthly fractal trendlines × support / resistance (from `trendline_slopes_paultwenty_20260831`).

## Signal rules

| Event | Rule |
|-------|------|
| BUY | Prior day slope_sum ≤ 0 and today > 0 (or first day with sum > 0) |
| SELL | Prior day slope_sum ≥ 0 and today < 0 (or first day with sum < 0) |
| Hold long | After BUY until SELL |
| Flat | Cash; 0 return that day |

Long-only. No shorts. Transaction costs = **0**.

## Execution

**Next-open fill** after the signal day (look-ahead safe vs same-bar close):

- Signal on close of day *t* → enter/exit at open of day *t+1*.
- Entry day return: open→close; hold days: close→close; exit day: prior close→open.

## Universe / period

- Universe: PaulTwenty (`drive/universes/PaulTwenty_universe.csv`) — {n_sym} symbols.
- Slopes source: `drive/paul_experiments/trendline_slopes_paultwenty_20260831/trendline_slopes_long.csv`
- Backtest period (intersection of slopes + OHLC): {period}

## Benchmark

Equal-weight **daily** total return of PaulTwenty (mean of available symbol close-to-close returns each day = daily rebalanced EW basket). Same calendar as strategy.

## IS / OOS

- IS: dates `< 2024-01-01`
- OOS: dates `≥ 2024-01-01` (report-only; no retune)

## Selection honesty

Fixed rules from Paul's ask; no grid search, no OOS-driven knob pick. Research candidate only.
"""
    path.write_text(text, encoding="utf-8")


def write_summary(path: Path, rows: list[dict], verdict: str) -> None:
    lines = [
        f"# SUMMARY — {STAMP}",
        "",
        f"**Verdict:** {verdict}",
        "",
        "Research only. TF = timeframe (daily/weekly/monthly).",
        "",
        "## Key numbers",
        "",
        "| Slice | Strat total | BH total | Δ total | Strat Ann ROR | BH Ann ROR | Strat MaxDD | BH MaxDD | Strat Sharpe | TIM | Buys | Sells |",
        "|-------|-------------|----------|---------|---------------|------------|-------------|----------|--------------|-----|------|-------|",
    ]
    for r in rows:
        lines.append(
            "| {slice} | {st} | {bh} | {dt} | {sa} | {ba} | {sd} | {bd} | {ss} | {tim} | {nb} | {ns} |".format(
                slice=r["slice"],
                st=fmt_pct(r["strat_total_ret"]),
                bh=fmt_pct(r["bh_total_ret"]),
                dt=fmt_pct_signed(r["delta_total_ret"]),
                sa=fmt_pct(r["strat_ann_ror"]),
                ba=fmt_pct(r["bh_ann_ror"]),
                sd=fmt_pct(r["strat_max_dd"]),
                bd=fmt_pct(r["bh_max_dd"]),
                ss=fmt_num(r["strat_sharpe"]),
                tim=fmt_pct(r["time_in_market"], 1),
                nb=r["n_buys"],
                ns=r["n_sells"],
            )
        )
    lines += [
        "",
        "## Signal (plain English)",
        "",
        "Each day, add up every active trendline's slope (% per day) for that stock — daily/weekly/monthly × support/resistance. "
        "When that day's sum flips from non-positive to positive → buy next open. When it flips from non-negative to negative → sell next open. "
        "Otherwise hold the prior stance (long or cash).",
        "",
        f"Stamp: `drive/paul_experiments/{STAMP}/`",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def metrics_table_html(rows: list[dict]) -> str:
    headers = [
        ("Slice", "text"),
        ("Start", "date"),
        ("End", "date"),
        ("N days", "num"),
        ("Strat total", "num"),
        ("BH total", "num"),
        ("Δ total", "num"),
        ("Strat Ann ROR", "num"),
        ("BH Ann ROR", "num"),
        ("Δ Ann ROR", "num"),
        ("Strat Max DD", "num"),
        ("BH Max DD", "num"),
        ("Δ Max DD", "num"),
        ("Strat Sharpe", "num"),
        ("BH Sharpe", "num"),
        ("Δ Sharpe", "num"),
        ("Time in mkt", "num"),
        ("# Buys", "num"),
        ("# Sells", "num"),
    ]
    thead = "".join(sortable_th(h, t) for h, t in headers)
    body = []
    for r in rows:
        cls = ' class="total-row"' if r["slice"] == "FULL" else ""
        body.append(
            f"<tr{cls}>"
            f"<td>{html_mod.escape(r['slice'])}</td>"
            f"<td>{html_mod.escape(r['start'])}</td>"
            f"<td>{html_mod.escape(r['end'])}</td>"
            f"<td>{r['n_days']}</td>"
            f"<td>{fmt_pct(r['strat_total_ret'])}</td>"
            f"<td>{fmt_pct(r['bh_total_ret'])}</td>"
            f"<td>{fmt_pct_signed(r['delta_total_ret'])}</td>"
            f"<td>{fmt_pct(r['strat_ann_ror'])}</td>"
            f"<td>{fmt_pct(r['bh_ann_ror'])}</td>"
            f"<td>{fmt_pct_signed(r['delta_ann_ror'])}</td>"
            f"<td>{fmt_pct(r['strat_max_dd'])}</td>"
            f"<td>{fmt_pct(r['bh_max_dd'])}</td>"
            f"<td>{fmt_pct_signed(r['delta_max_dd'])}</td>"
            f"<td>{fmt_num(r['strat_sharpe'])}</td>"
            f"<td>{fmt_num(r['bh_sharpe'])}</td>"
            f"<td>{fmt_num(r['delta_sharpe'])}</td>"
            f"<td>{fmt_pct(r['time_in_market'], 1)}</td>"
            f"<td>{r['n_buys']}</td>"
            f"<td>{r['n_sells']}</td>"
            f"</tr>"
        )
    return (
        '<p class="meta">Click column headers to sort.</p>'
        f'<table class="sortable"><thead><tr>{thead}</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table>'
    )


def symbol_table_html(sym_rows: list[dict]) -> str:
    headers = [
        ("Symbol", "text"),
        ("N days", "num"),
        ("Buys", "num"),
        ("Sells", "num"),
        ("TIM", "num"),
        ("Strat total", "num"),
        ("BH total", "num"),
        ("Δ total", "num"),
        ("Strat MaxDD", "num"),
        ("BH MaxDD", "num"),
    ]
    thead = "".join(sortable_th(h, t) for h, t in headers)
    body = []
    for r in sorted(sym_rows, key=lambda x: x["delta_total_ret"]):
        dcls = "up" if r["delta_total_ret"] > 0 else ("down" if r["delta_total_ret"] < 0 else "")
        body.append(
            "<tr>"
            f"<td>{html_mod.escape(r['symbol'])}</td>"
            f"<td>{r['n_days']}</td>"
            f"<td>{r['n_buys']}</td>"
            f"<td>{r['n_sells']}</td>"
            f"<td>{fmt_pct(r['time_in_market'], 1)}</td>"
            f"<td>{fmt_pct(r['strat_total_ret'])}</td>"
            f"<td>{fmt_pct(r['bh_total_ret'])}</td>"
            f"<td class='{dcls}'>{fmt_pct_signed(r['delta_total_ret'])}</td>"
            f"<td>{fmt_pct(r['strat_max_dd'])}</td>"
            f"<td>{fmt_pct(r['bh_max_dd'])}</td>"
            "</tr>"
        )
    return (
        '<p class="meta">Per-symbol long-only book vs that symbol\'s buy-hold (close-to-close). '
        "Click headers to sort.</p>"
        f'<table class="sortable"><thead><tr>{thead}</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table>'
    )


def write_html(
    path: Path,
    metric_rows: list[dict],
    sym_rows: list[dict],
    port: pd.DataFrame,
    verdict: str,
    period: str,
) -> None:
    full = next(r for r in metric_rows if r["slice"] == "FULL")
    chart = svg_equity_chart(port["Date"], port["strat_eq"].to_numpy(), port["bh_eq"].to_numpy())
    insights = []
    if full["delta_total_ret"] < 0 and full["strat_max_dd"] > full["bh_max_dd"]:
        insights.append(
            "Strategy underperforms equal-weight buy-hold on total return and does not improve Max DD — "
            "timing from the cross-TF slope sum does not beat simply owning the basket."
        )
    elif full["delta_total_ret"] < 0:
        insights.append(
            "Strategy trails buy-hold on total return; Max DD may differ — see table. "
            "Cash time reduces participation in the PaulTwenty bull path."
        )
    elif full["delta_ann_ror"] > 0 and full["strat_max_dd"] >= full["bh_max_dd"] * 0.95:
        insights.append(
            "Strategy beats buy-hold on return metrics without a clear DD win — still research-only; check OOS."
        )
    else:
        insights.append(
            "Compare FULL vs IS/OOS rows: if OOS softens, treat as HOLD/investigate — do not retune on OOS."
        )
    insights.append(
        f"Time in market FULL = {fmt_pct(full['time_in_market'], 1)}; "
        f"buys/sells (symbol-days) = {full['n_buys']}/{full['n_sells']}."
    )
    insights.append(
        "Primary cumulative = <strong>same-day sum across TF×side</strong>; "
        "running cumsum of that daily sum is diagnostic only."
    )
    insight_html = "".join(f"<div class='insight'>{x}</div>" for x in insights)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>{STAMP}</title>
<style>{SORT_CSS}</style>
</head>
<body>
<h1>Cumulative trendline slope signal — PaulTwenty</h1>
<p class="meta">
  Stamp <span class="badge">{html_mod.escape(STAMP)}</span>
  · Research only · Not gold · Not DailyRun<br/>
  <strong>TF</strong> = timeframe (daily / weekly / monthly fractal trendlines × support/resistance).<br/>
  Period: {html_mod.escape(period)} · Costs = 0 · Long-only · Next-open fills · EW daily-rebalanced BH benchmark.
</p>
<p class="caveat">
  Signal: for each stock each day, sum <code>slope_pct_per_day</code> across active lines (up to 6).
  Buy when that sum turns positive; sell when it turns negative. Hold long / sit in cash otherwise.
</p>

<h2>Verdict</h2>
<div class="insight"><strong>{html_mod.escape(verdict)}</strong></div>
{insight_html}

<h2>Strategy vs buy-hold (FULL / IS / OOS)</h2>
{metrics_table_html(metric_rows)}

<h2>Equity curves (FULL)</h2>
<div class="chart-wrap">{chart}</div>

<h2>Per-symbol contribution</h2>
{symbol_table_html(sym_rows)}

<h2>Frozen definitions</h2>
<ul class="meta">
  <li>Cumulative (signal): same-day Σ slope_pct_per_day over TF×side.</li>
  <li>Execution: signal day t → fill open t+1.</li>
  <li>IS &lt; 2024-01-01; OOS ≥ 2024-01-01 (report-only).</li>
  <li>Source slopes: trendline_slopes_paultwenty_20260831/trendline_slopes_long.csv</li>
</ul>
{SORT_JS}
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def main() -> int:
    if not SLOPES_CSV.exists():
        print(f"Missing slopes CSV: {SLOPES_CSV}", file=sys.stderr)
        return 1
    symbols = load_universe(PAULTWENTY)
    print(f"Loading slopes for {len(symbols)} symbols...")
    slopes = pd.read_csv(
        SLOPES_CSV,
        usecols=["symbol", "date", "timeframe", "side", "slope_pct_per_day"],
    )
    slopes["symbol"] = slopes["symbol"].astype(str).str.upper()
    slopes = slopes[slopes["symbol"].isin(symbols)]
    slopes["date"] = pd.to_datetime(slopes["date"]).dt.normalize()

    print("Building daily cross-TF×side slope sums + flip signals...")
    sig = build_daily_signal(slopes)

    daily_by_sym: dict[str, pd.DataFrame] = {}
    sym_metas: list[dict] = []
    for sym in symbols:
        ohlc = load_ohlc(sym)
        if ohlc is None or ohlc.empty:
            print(f"  skip {sym}: no OHLC")
            continue
        s_sym = sig[sig["symbol"] == sym]
        if s_sym.empty:
            print(f"  skip {sym}: no slopes")
            continue
        # Restrict OHLC to slope coverage intersection
        d0, d1 = s_sym["date"].min(), s_sym["date"].max()
        ohlc = ohlc[(ohlc["Date"] >= d0) & (ohlc["Date"] <= d1)].reset_index(drop=True)
        if len(ohlc) < 5:
            continue
        m, meta = backtest_symbol(sym, s_sym, ohlc)
        # Align run_cum from signal frame
        if "run_cum_slope_sum" not in m.columns:
            m["run_cum_slope_sum"] = np.nan
        daily_by_sym[sym] = m
        sym_metas.append(meta)
        print(f"  {sym}: days={meta['n_days']} buys={meta['n_buys']} sells={meta['n_sells']} "
              f"strat={meta['strat_total_ret']*100:.1f}% bh={meta['bh_total_ret']*100:.1f}%")

    if not daily_by_sym:
        print("No symbols backtested.", file=sys.stderr)
        return 1

    port, all_d = portfolio_equal_weight(daily_by_sym)
    period = f"{port['Date'].iloc[0].date()} → {port['Date'].iloc[-1].date()}"

    def slice_metrics(label: str, mask: np.ndarray) -> dict:
        sub = port.loc[mask].reset_index(drop=True)
        if sub.empty:
            return {
                "slice": label,
                "start": "",
                "end": "",
                "n_days": 0,
                "strat_total_ret": float("nan"),
                "bh_total_ret": float("nan"),
                "delta_total_ret": float("nan"),
                "strat_ann_ror": float("nan"),
                "bh_ann_ror": float("nan"),
                "delta_ann_ror": float("nan"),
                "strat_max_dd": float("nan"),
                "bh_max_dd": float("nan"),
                "delta_max_dd": float("nan"),
                "strat_sharpe": float("nan"),
                "bh_sharpe": float("nan"),
                "delta_sharpe": float("nan"),
                "time_in_market": float("nan"),
                "n_buys": 0,
                "n_sells": 0,
            }
        # Recompute equity within slice from daily rets
        nb, ns = count_flips_in_slice(all_d, all_d["Date"].isin(set(sub["Date"])))
        return metrics_from_daily(
            sub["Date"],
            sub["strat_ret"].to_numpy(dtype=float),
            sub["bh_ret"].to_numpy(dtype=float),
            sub["position_frac"].to_numpy(dtype=float),
            nb,
            ns,
            label,
        )

    full_mask = np.ones(len(port), dtype=bool)
    is_mask = port["Date"] < IS_CUTOFF
    oos_mask = port["Date"] >= IS_CUTOFF
    metric_rows = [
        slice_metrics("FULL", full_mask),
        slice_metrics("IS", is_mask.to_numpy()),
        slice_metrics("OOS", oos_mask.to_numpy()),
    ]

    full = metric_rows[0]
    # Verdict vs buy-hold
    if not np.isfinite(full["delta_total_ret"]):
        verdict = "INCONCLUSIVE — missing metrics."
    elif full["delta_total_ret"] <= -0.05 and full["strat_ann_ror"] < full["bh_ann_ror"]:
        verdict = "DISMISS vs PaulTwenty equal-weight buy-hold (research) — strategy trails on total/Ann return."
    elif full["delta_total_ret"] < 0:
        verdict = "LEAN DISMISS / HOLD — underperforms buy-hold; not interesting enough to pursue without a clear DD or OOS edge."
    elif full["delta_total_ret"] > 0 and metric_rows[2]["delta_total_ret"] < 0:
        verdict = "HOLD — FULL ahead of BH but OOS softens; do not retune on OOS (research only)."
    else:
        verdict = "INTERESTING (research candidate) — beats EW buy-hold on reported slices; still not gold / not DailyRun."

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Daily portfolio CSV
    port_out = port.copy()
    port_out["Date"] = port_out["Date"].dt.strftime("%Y-%m-%d")
    port_csv = OUT_DIR / "daily_equity_signals.csv"
    port_out.to_csv(port_csv, index=False)

    # Per-symbol daily detail (compact)
    detail_cols = [
        "symbol", "Date", "Open", "Close", "slope_sum", "n_lines", "run_cum_slope_sum",
        "signal", "target_pos", "exec_pos", "strat_ret", "bh_ret",
    ]
    detail_frames = []
    for sym, df in daily_by_sym.items():
        d = df.copy()
        d["Date"] = pd.to_datetime(d["Date"]).dt.strftime("%Y-%m-%d")
        for c in detail_cols:
            if c not in d.columns:
                d[c] = np.nan
        detail_frames.append(d[detail_cols])
    detail = pd.concat(detail_frames, ignore_index=True)
    detail_csv = OUT_DIR / "daily_per_symbol_signals.csv"
    detail.to_csv(detail_csv, index=False)

    # Metrics CSV
    metrics_df = pd.DataFrame(metric_rows)
    metrics_csv = OUT_DIR / "compare_metrics.csv"
    metrics_df.to_csv(metrics_csv, index=False)

    sym_csv = OUT_DIR / "per_symbol_contribution.csv"
    pd.DataFrame(sym_metas).to_csv(sym_csv, index=False)

    write_baseline(OUT_DIR / "BASELINE.md", period, len(daily_by_sym))
    write_summary(OUT_DIR / "SUMMARY.md", metric_rows, verdict)
    html_path = OUT_DIR / "compare.html"
    write_html(html_path, metric_rows, sym_metas, port, verdict, period)

    print("\n=== FULL ===")
    for k in ("strat_total_ret", "bh_total_ret", "delta_total_ret", "strat_ann_ror", "bh_ann_ror",
              "strat_max_dd", "bh_max_dd", "strat_sharpe", "time_in_market", "n_buys", "n_sells"):
        print(f"  {k}: {full[k]}")
    print(f"\nVerdict: {verdict}")
    print(f"HTML: {html_path}")
    print(f"CSV:  {port_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
