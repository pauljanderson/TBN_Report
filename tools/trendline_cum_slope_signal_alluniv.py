#!/usr/bin/env python3
"""Full-universe cum-slope signal BT + collective breadth pack.

Inputs:
  - drive/paul_experiments/trendline_slopes_alluniv_20260831/daily_symbol_slope_sum.parquet
  - drive/paul_experiments/trendline_slopes_paultwenty_20260831/trendline_slopes_long.csv (PT breadth)

Signal freeze (match PaulTwenty stamp):
  Buy when slope_sum turns ≤0→>0; sell ≥0→<0; next-open; long-only; costs 0.
  Benchmark: equal-weight daily rebalanced buy-hold of same universe.

Also: optional high/low vol tercile sleeves (ATR% tercile by symbol).

Outputs under trendline_cum_slope_signal_alluniv_20260831/:
  compare.html (signal + breadth for ALL + PaulTwenty addendum)
  CSVs, SUMMARY, BASELINE

Research only — not gold, not DailyRun.

Usage:
  python tools/trendline_cum_slope_signal_alluniv.py
"""
from __future__ import annotations

import html as html_mod
import math
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "newdata" / "data"
DRIVE = ROOT / "drive"
ALL_UNIV = DRIVE / "universes" / "ALL_ohlc_universe.csv"
PAULTWENTY = DRIVE / "universes" / "PaulTwenty_universe.csv"
SLOPES_ALL = (
    DRIVE / "paul_experiments" / "trendline_slopes_alluniv_20260831" / "daily_symbol_slope_sum.parquet"
)
BREADTH_ALL = (
    DRIVE / "paul_experiments" / "trendline_slopes_alluniv_20260831" / "daily_breadth.csv"
)
SLOPES_PT = (
    DRIVE
    / "paul_experiments"
    / "trendline_slopes_paultwenty_20260831"
    / "trendline_slopes_long.csv"
)
STAMP = "trendline_cum_slope_signal_alluniv_20260831"
OUT_DIR = DRIVE / "paul_experiments" / STAMP
IS_CUTOFF = pd.Timestamp("2024-01-01")
TRADING_DAYS_PER_YEAR = 252
ATR_LOOKBACK = 20
VOL_WINDOW_DAYS = 252  # classify symbols by median ATR% over first year of overlap

SORT_CSS = """
th.sortable-th { cursor: pointer; user-select: none; white-space: nowrap; }
th.sortable-th:hover { background: #e2e8f0; }
th.sortable-th .sort-ind::after { content: " \\2195"; opacity: .35; font-size: .85em; }
th.sortable-th.sort-asc .sort-ind::after { content: " \\2191"; opacity: .9; }
th.sortable-th.sort-desc .sort-ind::after { content: " \\2193"; opacity: .9; }
body { font-family: Segoe UI, system-ui, sans-serif; margin: 1.5rem; color: #0f172a; background: #f8fafc; }
h1 { font-size: 1.45rem; margin: 0 0 .35rem; }
h2 { font-size: 1.15rem; margin: 1.6rem 0 .5rem; border-bottom: 1px solid #cbd5e1; padding-bottom: .25rem; }
h3 { font-size: 1.02rem; margin: 1.1rem 0 .4rem; }
.meta, .caveat { color: #475569; font-size: .92rem; max-width: 74rem; }
.insight { background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: .75rem 1rem; margin: .75rem 0; max-width: 74rem; }
.badge { display: inline-block; padding: .1rem .45rem; border-radius: 4px; font-size: .8rem; background: #e2e8f0; }
.up { color: #047857; font-weight: 600; }
.down { color: #b91c1c; font-weight: 600; }
table.sortable { border-collapse: collapse; background: #fff; font-size: .88rem; margin: .5rem 0 1rem; }
table.sortable th, table.sortable td { border: 1px solid #e2e8f0; padding: .35rem .55rem; text-align: left; }
table.sortable th { background: #f1f5f9; }
.chart-wrap { max-width: 74rem; margin: 1rem 0; background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: .75rem; }
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


def build_daily_signal_from_sums(sums: pd.DataFrame) -> pd.DataFrame:
    """sums: symbol, date, slope_sum, n_lines (optional)."""
    g = sums.sort_values(["symbol", "date"]).reset_index(drop=True).copy()
    g["date"] = pd.to_datetime(g["date"]).dt.normalize()
    rows = []
    for sym, sg in g.groupby("symbol", sort=False):
        sg = sg.copy()
        prev = sg["slope_sum"].shift(1)
        buy = (prev <= 0) & (sg["slope_sum"] > 0)
        sell = (prev >= 0) & (sg["slope_sum"] < 0)
        first_mask = prev.isna()
        buy = buy | (first_mask & (sg["slope_sum"] > 0))
        sell = sell | (first_mask & (sg["slope_sum"] < 0))
        signal = np.where(buy, "BUY", np.where(sell, "SELL", ""))
        pos = []
        cur = 0
        for b, s in zip(buy.to_numpy(), sell.to_numpy()):
            if b:
                cur = 1
            elif s:
                cur = 0
            pos.append(cur)
        sg["signal"] = signal
        sg["target_pos"] = pos
        rows.append(sg)
    return pd.concat(rows, ignore_index=True)


def backtest_symbol(sym: str, sig: pd.DataFrame, ohlc: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    o = ohlc.copy()
    o["Date"] = pd.to_datetime(o["Date"]).dt.normalize()
    s = sig.copy()
    s["date"] = pd.to_datetime(s["date"]).dt.normalize()
    m = o.merge(s, left_on="Date", right_on="date", how="left")
    m["slope_sum"] = m["slope_sum"].fillna(0.0)
    if "n_lines" not in m.columns:
        m["n_lines"] = 0
    m["n_lines"] = m["n_lines"].fillna(0).astype(int)
    m["signal"] = m["signal"].fillna("")
    m["target_pos"] = m["target_pos"].ffill().fillna(0).astype(int)
    m["exec_pos"] = m["target_pos"].shift(1).fillna(0).astype(int)

    close = m["Close"].to_numpy(dtype=float)
    open_ = m["Open"].to_numpy(dtype=float)
    pos = m["exec_pos"].to_numpy(dtype=int)
    n = len(m)
    strat = np.zeros(n, dtype=float)
    for i in range(1, n):
        if pos[i] == 1 and pos[i - 1] == 0:
            if open_[i] > 0 and np.isfinite(open_[i]) and np.isfinite(close[i]):
                strat[i] = close[i] / open_[i] - 1.0
        elif pos[i] == 1 and pos[i - 1] == 1:
            if close[i - 1] > 0 and np.isfinite(close[i - 1]) and np.isfinite(close[i]):
                strat[i] = close[i] / close[i - 1] - 1.0
        elif pos[i] == 0 and pos[i - 1] == 1:
            if close[i - 1] > 0 and np.isfinite(close[i - 1]) and np.isfinite(open_[i]):
                strat[i] = open_[i] / close[i - 1] - 1.0

    bh = np.zeros(n, dtype=float)
    for i in range(1, n):
        if close[i - 1] > 0 and np.isfinite(close[i - 1]) and np.isfinite(close[i]):
            bh[i] = close[i] / close[i - 1] - 1.0

    m["strat_ret"] = strat
    m["bh_ret"] = bh
    m["symbol"] = sym
    buys = int((m["signal"] == "BUY").sum())
    sells = int((m["signal"] == "SELL").sum())
    meta = {
        "symbol": sym,
        "n_days": n,
        "n_buys": buys,
        "n_sells": sells,
        "strat_total_ret": float(np.prod(1.0 + strat) - 1.0),
        "bh_total_ret": float(np.prod(1.0 + bh) - 1.0),
        "time_in_market": float(np.mean(pos > 0)) if n else float("nan"),
        "strat_max_dd": max_drawdown(np.cumprod(1.0 + strat)),
        "bh_max_dd": max_drawdown(np.cumprod(1.0 + bh)),
    }
    meta["delta_total_ret"] = meta["strat_total_ret"] - meta["bh_total_ret"]
    return m, meta


def atr_pct_median(ohlc: pd.DataFrame, lookback: int = ATR_LOOKBACK) -> float:
    """Median ATR%/close over available history (Wilder-ish TR mean then /close)."""
    if len(ohlc) < lookback + 2:
        return float("nan")
    high = ohlc["High"].to_numpy(dtype=float)
    low = ohlc["Low"].to_numpy(dtype=float)
    close = ohlc["Close"].to_numpy(dtype=float)
    prev_c = np.roll(close, 1)
    prev_c[0] = close[0]
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_c), np.abs(low - prev_c)))
    atr = pd.Series(tr).rolling(lookback, min_periods=lookback).mean().to_numpy()
    pct = atr / close * 100.0
    pct = pct[np.isfinite(pct)]
    if len(pct) < 20:
        return float("nan")
    # Use early window for classification (avoid look-ahead into OOS for sleeve label)
    # Take first VOL_WINDOW_DAYS of valid ATR% after warm-up
    early = pct[: min(len(pct), VOL_WINDOW_DAYS)]
    return float(np.median(early))


def portfolio_equal_weight(daily_by_sym: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    frames = []
    for sym, df in daily_by_sym.items():
        frames.append(
            df[["Date", "strat_ret", "bh_ret", "exec_pos", "signal", "slope_sum"]].assign(symbol=sym)
        )
    all_d = pd.concat(frames, ignore_index=True)
    port = (
        all_d.groupby("Date", as_index=False)
        .agg(
            strat_ret=("strat_ret", "mean"),
            bh_ret=("bh_ret", "mean"),
            n_symbols=("symbol", "nunique"),
            n_long=("exec_pos", "sum"),
            mean_slope_sum=("slope_sum", "mean"),
            n_buys=("signal", lambda s: int((s == "BUY").sum())),
            n_sells=("signal", lambda s: int((s == "SELL").sum())),
        )
        .sort_values("Date")
        .reset_index(drop=True)
    )
    port["position_frac"] = port["n_long"] / port["n_symbols"].clip(lower=1)
    port["strat_eq"] = (1.0 + port["strat_ret"]).cumprod()
    port["bh_eq"] = (1.0 + port["bh_ret"]).cumprod()
    return port, all_d


def count_flips_in_slice(all_d: pd.DataFrame, dates: set) -> tuple[int, int]:
    sub = all_d[all_d["Date"].isin(dates)]
    return int((sub["signal"] == "BUY").sum()), int((sub["signal"] == "SELL").sum())


def svg_equity_chart(dates: pd.Series, strat_eq: np.ndarray, bh_eq: np.ndarray, width: int = 900, height: int = 320) -> str:
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

    lab_idx = np.linspace(0, len(dates) - 1, 6).astype(int)
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
<svg class="eq" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" role="img">
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


def svg_breadth_chart(br: pd.DataFrame, col: str = "breadth_lines", width: int = 900, height: int = 220) -> str:
    if br.empty or len(br) < 2:
        return "<p class='meta'>No breadth series.</p>"
    dates = pd.to_datetime(br["date"])
    y = br[col].to_numpy(dtype=float)
    pad_l, pad_r, pad_t, pad_b = 52, 16, 16, 36
    xs = np.linspace(pad_l, width - pad_r, len(dates))
    ymin, ymax = float(np.nanmin(y)), float(np.nanmax(y))
    if ymin == ymax:
        ymax = ymin + 1.0

    def ymap(v: float) -> float:
        return pad_t + (1.0 - (v - ymin) / (ymax - ymin)) * (height - pad_t - pad_b)

    zero_y = ymap(0.0)
    pts = [f"{xs[i]:.1f},{ymap(float(y[i])):.1f}" for i in range(len(y))]
    path = "M " + " L ".join(pts)
    lab_idx = np.linspace(0, len(dates) - 1, 6).astype(int)
    labels = [
        f'<text x="{xs[i]:.1f}" y="{height - 10}" text-anchor="middle" font-size="11" fill="#64748b">'
        f'{dates.iloc[i].strftime("%Y-%m")}</text>'
        for i in lab_idx
    ]
    return f"""
<svg class="eq" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="0" width="{width}" height="{height}" fill="#fff"/>
  <line x1="{pad_l}" y1="{zero_y:.1f}" x2="{width - pad_r}" y2="{zero_y:.1f}" stroke="#94a3b8" stroke-dasharray="4 3"/>
  <path d="{path}" fill="none" stroke="#7c3aed" stroke-width="1.5"/>
  {''.join(labels)}
</svg>
"""


def breadth_stats(br: pd.DataFrame, label: str) -> dict:
    n = len(br)
    if n == 0:
        return {"universe": label, "n_days": 0}
    return {
        "universe": label,
        "n_days": n,
        "start": str(br["date"].iloc[0]),
        "end": str(br["date"].iloc[-1]),
        "pct_days_more_up_lines": float(br["more_up_lines"].mean() * 100.0),
        "pct_days_more_down_lines": float(br["more_down_lines"].mean() * 100.0),
        "pct_days_tie_lines": float((br["n_up"] == br["n_down"]).mean() * 100.0),
        "pct_days_more_up_symbols": float(br["more_up_symbols"].mean() * 100.0),
        "pct_days_more_down_symbols": float(br["more_down_symbols"].mean() * 100.0),
        "mean_pct_up_lines": float(br["pct_up_lines"].mean()),
        "mean_breadth_lines": float(br["breadth_lines"].mean()),
    }


def find_stretches(br: pd.DataFrame, flag_col: str, min_len: int = 10) -> list[dict]:
    """Long consecutive stretches where flag_col == 1."""
    flags = br[flag_col].to_numpy(dtype=int)
    dates = br["date"].astype(str).to_list()
    out = []
    i = 0
    n = len(flags)
    while i < n:
        if flags[i] != 1:
            i += 1
            continue
        j = i
        while j < n and flags[j] == 1:
            j += 1
        length = j - i
        if length >= min_len:
            out.append(
                {
                    "start": dates[i],
                    "end": dates[j - 1],
                    "n_days": length,
                    "kind": flag_col,
                }
            )
        i = j
    out.sort(key=lambda r: -r["n_days"])
    return out


def regime_highlights(br: pd.DataFrame) -> list[dict]:
    """Mean breadth in known stress windows."""
    d = br.copy()
    d["date"] = pd.to_datetime(d["date"])
    windows = [
        ("2020 COVID crash", "2020-02-15", "2020-04-15"),
        ("2020 rebound", "2020-04-16", "2020-08-31"),
        ("2022 bear", "2022-01-01", "2022-10-15"),
        ("2023–24 bull", "2023-01-01", "2024-12-31"),
        ("2025 YTD", "2025-01-01", "2026-12-31"),
    ]
    rows = []
    for name, a, b in windows:
        sub = d[(d["date"] >= a) & (d["date"] <= b)]
        if sub.empty:
            continue
        rows.append(
            {
                "window": name,
                "start": a,
                "end": min(str(sub["date"].max().date()), b),
                "n_days": len(sub),
                "pct_more_up_lines": float(sub["more_up_lines"].mean() * 100.0),
                "pct_more_down_lines": float(sub["more_down_lines"].mean() * 100.0),
                "mean_breadth_lines": float(sub["breadth_lines"].mean()),
                "mean_pct_up_lines": float(sub["pct_up_lines"].mean()),
                "pct_more_up_symbols": float(sub["more_up_symbols"].mean() * 100.0),
            }
        )
    return rows


def build_pt_breadth_from_long(path: Path) -> pd.DataFrame:
    """PaulTwenty line + symbol breadth from long slopes CSV."""
    usecols = ["symbol", "date", "slope_sign", "slope_pct_per_day"]
    long = pd.read_csv(path, usecols=usecols)
    long["date"] = pd.to_datetime(long["date"]).dt.strftime("%Y-%m-%d")
    line = (
        long.groupby("date", as_index=False)
        .agg(
            n_lines=("slope_sign", "count"),
            n_up=("slope_sign", lambda s: int((s > 0).sum())),
            n_down=("slope_sign", lambda s: int((s < 0).sum())),
            n_flat=("slope_sign", lambda s: int((s == 0).sum())),
        )
        .sort_values("date")
    )
    line["n_symbols"] = (
        long.groupby("date")["symbol"].nunique().reindex(line["date"]).to_numpy()
    )
    line["breadth_lines"] = line["n_up"] - line["n_down"]
    line["pct_up_lines"] = line["n_up"] / line["n_lines"] * 100.0
    line["more_up_lines"] = (line["n_up"] > line["n_down"]).astype(int)
    line["more_down_lines"] = (line["n_down"] > line["n_up"]).astype(int)

    sym = (
        long.groupby(["date", "symbol"], as_index=False)
        .agg(slope_sum=("slope_pct_per_day", "sum"))
    )
    sym["sym_up"] = (sym["slope_sum"] > 0).astype(int)
    sym["sym_down"] = (sym["slope_sum"] < 0).astype(int)
    sym["sym_flat"] = (sym["slope_sum"] == 0).astype(int)
    sg = sym.groupby("date", as_index=False).agg(
        n_sym_up=("sym_up", "sum"),
        n_sym_down=("sym_down", "sum"),
        n_sym_flat=("sym_flat", "sum"),
    )
    line = line.merge(sg, on="date", how="left")
    line["breadth_symbols"] = line["n_sym_up"] - line["n_sym_down"]
    line["pct_sym_up"] = line["n_sym_up"] / line["n_symbols"] * 100.0
    line["more_up_symbols"] = (line["n_sym_up"] > line["n_sym_down"]).astype(int)
    line["more_down_symbols"] = (line["n_sym_down"] > line["n_sym_up"]).astype(int)
    line["mean_slope_sum"] = (
        sym.groupby("date")["slope_sum"].mean().reindex(line["date"]).to_numpy()
    )
    line["median_slope_sum"] = (
        sym.groupby("date")["slope_sum"].median().reindex(line["date"]).to_numpy()
    )
    return line


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
        cls = ' class="total-row"' if str(r["slice"]).startswith("FULL") else ""
        body.append(
            f"<tr{cls}>"
            f"<td>{html_mod.escape(str(r['slice']))}</td>"
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


def dict_rows_table(rows: list[dict], specs: list[tuple[str, str, str]]) -> str:
    if not rows:
        return "<p><em>No rows.</em></p>"
    thead = "".join(sortable_th(lab, st) for _, lab, st in specs)
    body = []
    for r in rows:
        cells = []
        for key, _lab, st in specs:
            v = r.get(key, "")
            if st == "num" and isinstance(v, (int, float, np.floating)):
                if "pct" in key.lower() or key.startswith("mean_pct"):
                    txt = fmt_num(float(v), 1)
                else:
                    txt = fmt_num(float(v), 2 if abs(float(v)) < 1000 else 0)
            else:
                txt = "—" if v is None or (isinstance(v, float) and not np.isfinite(v)) else str(v)
            cells.append(f"<td>{html_mod.escape(txt)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (
        f'<table class="sortable"><thead><tr>{thead}</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table>'
    )


def slice_metrics_for_port(port: pd.DataFrame, all_d: pd.DataFrame, prefix: str = "") -> list[dict]:
    def one(label: str, mask) -> dict:
        sub = port.loc[mask].reset_index(drop=True)
        if sub.empty:
            return {
                "slice": f"{prefix}{label}" if prefix else label,
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
        nb, ns = count_flips_in_slice(all_d, set(sub["Date"]))
        return metrics_from_daily(
            sub["Date"],
            sub["strat_ret"].to_numpy(dtype=float),
            sub["bh_ret"].to_numpy(dtype=float),
            sub["position_frac"].to_numpy(dtype=float),
            nb,
            ns,
            f"{prefix}{label}" if prefix else label,
        )

    return [
        one("FULL", np.ones(len(port), dtype=bool)),
        one("IS", (port["Date"] < IS_CUTOFF).to_numpy()),
        one("OOS", (port["Date"] >= IS_CUTOFF).to_numpy()),
    ]


def decide_verdict(metric_rows: list[dict]) -> str:
    full = next(r for r in metric_rows if r["slice"] == "FULL" or r["slice"].endswith("FULL") and not r["slice"].startswith("HIGH") and not r["slice"].startswith("LOW"))
    # Prefer exact FULL
    fulls = [r for r in metric_rows if r["slice"] == "FULL"]
    full = fulls[0] if fulls else metric_rows[0]
    oos = next((r for r in metric_rows if r["slice"] == "OOS"), None)
    if not np.isfinite(full["delta_total_ret"]):
        return "INCONCLUSIVE — missing metrics."
    if full["delta_total_ret"] <= -0.05 and full["strat_ann_ror"] < full["bh_ann_ror"]:
        return (
            "DISMISS vs ALL-universe equal-weight buy-hold (research) — "
            "strategy trails on total/Ann return."
        )
    if full["delta_total_ret"] < 0:
        return (
            "LEAN DISMISS / HOLD — underperforms buy-hold; "
            "not interesting enough without a clear DD or OOS edge."
        )
    if oos is not None and np.isfinite(oos.get("delta_total_ret", float("nan"))) and oos["delta_total_ret"] < 0:
        return "HOLD — FULL ahead of BH but OOS softens; do not retune on OOS (research only)."
    return "INTERESTING (research candidate) — beats EW buy-hold on reported slices; still not gold / not DailyRun."


def write_html(
    path: Path,
    *,
    verdict: str,
    period: str,
    n_sym: int,
    metric_rows: list[dict],
    vol_rows: list[dict],
    port: pd.DataFrame,
    br_all: pd.DataFrame,
    br_pt: pd.DataFrame,
    stats_all: dict,
    stats_pt: dict,
    regimes_all: list[dict],
    regimes_pt: list[dict],
    stretches_all: list[dict],
    stretches_pt: list[dict],
) -> None:
    chart = svg_equity_chart(port["Date"], port["strat_eq"].to_numpy(), port["bh_eq"].to_numpy())
    br_chart = svg_breadth_chart(br_all, "breadth_lines")
    br_chart_pt = svg_breadth_chart(br_pt, "breadth_lines")

    regime_specs = [
        ("window", "Window", "text"),
        ("start", "Start", "date"),
        ("end", "End", "date"),
        ("n_days", "N", "num"),
        ("pct_more_up_lines", "% days more UP lines", "num"),
        ("pct_more_down_lines", "% days more DOWN lines", "num"),
        ("mean_breadth_lines", "Mean breadth (UP−DOWN)", "num"),
        ("mean_pct_up_lines", "Mean % UP lines", "num"),
        ("pct_more_up_symbols", "% days more UP symbols", "num"),
    ]
    stretch_specs = [
        ("kind", "Kind", "text"),
        ("start", "Start", "date"),
        ("end", "End", "date"),
        ("n_days", "N days", "num"),
    ]
    stats_specs = [
        ("universe", "Universe", "text"),
        ("n_days", "N days", "num"),
        ("start", "Start", "date"),
        ("end", "End", "date"),
        ("pct_days_more_up_lines", "% more UP lines", "num"),
        ("pct_days_more_down_lines", "% more DOWN lines", "num"),
        ("pct_days_tie_lines", "% tie lines", "num"),
        ("pct_days_more_up_symbols", "% more UP symbols", "num"),
        ("pct_days_more_down_symbols", "% more DOWN symbols", "num"),
        ("mean_pct_up_lines", "Mean % UP lines", "num"),
        ("mean_breadth_lines", "Mean line breadth", "num"),
    ]

    full = next(r for r in metric_rows if r["slice"] == "FULL")
    insights = [
        f"FULL strategy total {fmt_pct(full['strat_total_ret'])} vs EW BH {fmt_pct(full['bh_total_ret'])} "
        f"(Δ {fmt_pct_signed(full['delta_total_ret'])}); TIM {fmt_pct(full['time_in_market'], 1)}.",
        f"ALL univ line breadth: more UP than DOWN on <strong>{fmt_num(stats_all['pct_days_more_up_lines'], 1)}%</strong> of days; "
        f"more DOWN on <strong>{fmt_num(stats_all['pct_days_more_down_lines'], 1)}%</strong>.",
        f"PaulTwenty line breadth: more UP {fmt_num(stats_pt['pct_days_more_up_lines'], 1)}% of days; "
        f"more DOWN {fmt_num(stats_pt['pct_days_more_down_lines'], 1)}%.",
    ]

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>{STAMP}</title>
<style>{SORT_CSS}</style>
</head>
<body>
<h1>Cum-slope signal (ALL universe) + collective breadth</h1>
<p class="meta">
  Stamp <span class="badge">{html_mod.escape(STAMP)}</span>
  · Research only · Not gold · Not DailyRun<br/>
  <strong>TF</strong> = timeframe (daily / weekly / monthly fractal trendlines × support/resistance).<br/>
  Universe: ALL_ohlc ({n_sym} symbols with slopes+OHLC) · Period: {html_mod.escape(period)} ·
  Costs = 0 · Long-only · Next-open · EW daily-rebalanced BH.
</p>
<p class="caveat">
  Signal: each symbol-day sum <code>slope_pct_per_day</code> across active TF×side lines.
  Buy when sum turns positive; sell when turns negative. Same freeze as PaulTwenty DISMISS stamp.
  Full long TF×side CSV not stored for ALL univ — used <code>daily_symbol_slope_sum</code> aggregates.
</p>

<h2>Verdict</h2>
<div class="insight"><strong>{html_mod.escape(verdict)}</strong></div>
{''.join(f'<div class="insight">{x}</div>' for x in insights)}

<h2>Strategy vs buy-hold — ALL universe (FULL / IS / OOS)</h2>
{metrics_table_html(metric_rows)}

<h2>Equity curves (ALL FULL)</h2>
<div class="chart-wrap">{chart}</div>

<h2>Vol tercile sleeves (optional — ATR% early median)</h2>
<p class="meta">Symbols ranked by median ATR% (20-bar) over early history; high vs low tercile run same signal vs their own EW BH.
Speaks to “maybe works on more volatile stocks.” Click headers to sort.</p>
{metrics_table_html(vol_rows) if vol_rows else "<p><em>Vol sleeves unavailable.</em></p>"}

<h2>Collective breadth — summary</h2>
<p class="meta">Line breadth = count of active TF×side lines with slope_sign &gt; 0 vs &lt; 0 across the universe.
Symbol breadth = count of symbols with that day’s slope_sum &gt; 0 vs &lt; 0.</p>
{dict_rows_table([stats_all, stats_pt], stats_specs)}

<h2>ALL universe — line breadth (UP − DOWN)</h2>
<div class="chart-wrap">{br_chart}</div>
<h3>Regime windows (ALL)</h3>
{dict_rows_table(regimes_all, regime_specs)}
<h3>Longest stretches ≥10 days (ALL lines)</h3>
{dict_rows_table(stretches_all[:20], stretch_specs)}

<h2>PaulTwenty addendum — collective breadth</h2>
<div class="chart-wrap">{br_chart_pt}</div>
<h3>Regime windows (PaulTwenty)</h3>
{dict_rows_table(regimes_pt, regime_specs)}
<h3>Longest stretches ≥10 days (PaulTwenty lines)</h3>
{dict_rows_table(stretches_pt[:20], stretch_specs)}

<h2>Frozen definitions</h2>
<ul class="meta">
  <li>Cumulative (signal): same-day Σ slope_pct_per_day over TF×side.</li>
  <li>Execution: signal day t → fill open t+1.</li>
  <li>IS &lt; 2024-01-01; OOS ≥ 2024-01-01 (report-only; no retune).</li>
  <li>Slopes: trendline_slopes_alluniv_20260831 / PaulTwenty long CSV for PT breadth.</li>
</ul>
{SORT_JS}
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def main() -> int:
    t0 = time.time()
    if not SLOPES_ALL.exists():
        # fallback CSV
        csv_fb = SLOPES_ALL.with_suffix(".csv")
        if not csv_fb.exists():
            print(f"Missing slopes: {SLOPES_ALL}", file=sys.stderr)
            return 1
        print(f"Loading {csv_fb} ...")
        sums = pd.read_csv(csv_fb)
    else:
        print(f"Loading {SLOPES_ALL} ...")
        sums = pd.read_parquet(SLOPES_ALL)

    sums["symbol"] = sums["symbol"].astype(str).str.upper()
    sums["date"] = pd.to_datetime(sums["date"]).dt.normalize()
    symbols = sorted(sums["symbol"].unique().tolist())
    print(f"Symbols in slope_sum: {len(symbols)}")

    print("Building flip signals...")
    sig = build_daily_signal_from_sums(sums)

    daily_by_sym: dict[str, pd.DataFrame] = {}
    sym_metas: list[dict] = []
    atr_map: dict[str, float] = {}
    ohlc_cache: dict[str, pd.DataFrame] = {}

    for i, sym in enumerate(symbols):
        ohlc = load_ohlc(sym)
        if ohlc is None or ohlc.empty:
            continue
        s_sym = sig[sig["symbol"] == sym]
        if s_sym.empty:
            continue
        d0, d1 = s_sym["date"].min(), s_sym["date"].max()
        ohlc = ohlc[(ohlc["Date"] >= d0) & (ohlc["Date"] <= d1)].reset_index(drop=True)
        if len(ohlc) < 5:
            continue
        m, meta = backtest_symbol(sym, s_sym, ohlc)
        daily_by_sym[sym] = m
        atr_map[sym] = atr_pct_median(ohlc)
        ohlc_cache[sym] = ohlc
        sym_metas.append(meta)
        if (i + 1) % 100 == 0:
            print(f"  backtested {i+1}/{len(symbols)} ...", flush=True)

    if not daily_by_sym:
        print("No symbols backtested.", file=sys.stderr)
        return 1

    print(f"Portfolio EW over {len(daily_by_sym)} symbols...")
    port, all_d = portfolio_equal_weight(daily_by_sym)
    period = f"{port['Date'].iloc[0].date()} → {port['Date'].iloc[-1].date()}"
    metric_rows = slice_metrics_for_port(port, all_d)
    verdict = decide_verdict(metric_rows)

    # Vol terciles
    atr_s = pd.Series(atr_map).dropna()
    vol_rows: list[dict] = []
    if len(atr_s) >= 30:
        q_lo, q_hi = atr_s.quantile(1 / 3), atr_s.quantile(2 / 3)
        low_syms = set(atr_s[atr_s <= q_lo].index)
        high_syms = set(atr_s[atr_s >= q_hi].index)
        for label, subset in (("HIGH_VOL", high_syms), ("LOW_VOL", low_syms)):
            sub_daily = {s: daily_by_sym[s] for s in subset if s in daily_by_sym}
            if len(sub_daily) < 5:
                continue
            p2, a2 = portfolio_equal_weight(sub_daily)
            rows = slice_metrics_for_port(p2, a2, prefix=f"{label}_")
            vol_rows.extend(rows)
            print(f"  {label}: n={len(sub_daily)} FULL delta={rows[0]['delta_total_ret']}")

    # Breadth
    if BREADTH_ALL.exists():
        br_all = pd.read_csv(BREADTH_ALL)
    else:
        from tools.trendline_slopes_alluniv import build_breadth

        br_all = build_breadth(sums.assign(n_up=sums.get("n_up", 0), n_down=sums.get("n_down", 0), n_flat=sums.get("n_flat", 0)))

    print("PaulTwenty breadth from long CSV...")
    br_pt = build_pt_breadth_from_long(SLOPES_PT)

    stats_all = breadth_stats(br_all, "ALL_ohlc")
    stats_pt = breadth_stats(br_pt, "PaulTwenty")
    regimes_all = regime_highlights(br_all)
    regimes_pt = regime_highlights(br_pt)
    stretches_all = find_stretches(br_all, "more_up_lines", 10) + find_stretches(
        br_all, "more_down_lines", 10
    )
    stretches_all.sort(key=lambda r: -r["n_days"])
    stretches_pt = find_stretches(br_pt, "more_up_lines", 10) + find_stretches(
        br_pt, "more_down_lines", 10
    )
    stretches_pt.sort(key=lambda r: -r["n_days"])

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    port_out = port.copy()
    port_out["Date"] = port_out["Date"].dt.strftime("%Y-%m-%d")
    port_out.to_csv(OUT_DIR / "daily_equity_signals.csv", index=False)
    pd.DataFrame(metric_rows).to_csv(OUT_DIR / "compare_metrics.csv", index=False)
    if vol_rows:
        pd.DataFrame(vol_rows).to_csv(OUT_DIR / "vol_tercile_metrics.csv", index=False)
    pd.DataFrame(sym_metas).to_csv(OUT_DIR / "per_symbol_contribution.csv", index=False)
    # Top/bottom contributors only in HTML via CSV of all — keep full CSV
    br_pt.to_csv(OUT_DIR / "daily_breadth_paultwenty.csv", index=False)
    br_all.to_csv(OUT_DIR / "daily_breadth_alluniv.csv", index=False)
    pd.DataFrame([stats_all, stats_pt]).to_csv(OUT_DIR / "breadth_summary.csv", index=False)
    pd.DataFrame([{**r, "universe": "ALL"} for r in regimes_all]).to_csv(
        OUT_DIR / "breadth_regimes_alluniv.csv", index=False
    )
    pd.DataFrame([{**r, "universe": "PaulTwenty"} for r in regimes_pt]).to_csv(
        OUT_DIR / "breadth_regimes_paultwenty.csv", index=False
    )
    pd.DataFrame(stretches_all[:50]).to_csv(OUT_DIR / "breadth_stretches_alluniv.csv", index=False)
    pd.DataFrame(stretches_pt[:50]).to_csv(OUT_DIR / "breadth_stretches_paultwenty.csv", index=False)

    atr_df = pd.DataFrame([{"symbol": s, "atr_pct_median_early": atr_map[s]} for s in atr_map])
    atr_df.to_csv(OUT_DIR / "symbol_atr_pct.csv", index=False)

    # BASELINE / SUMMARY
    (OUT_DIR / "BASELINE.md").write_text(
        f"""# BASELINE — {STAMP}

Research only. Not gold. Not DailyRun. No knobs tuned on OOS.

## Hypothesis

Same cum-slope flip signal as PaulTwenty stamp, on **ALL_ohlc** universe — maybe works better on a wider / more volatile set.

## Freeze

| Knob | Value |
|------|-------|
| Signal | Buy slope_sum ≤0→>0; sell ≥0→<0 |
| Slope input | Same-day Σ `slope_pct_per_day` across TF×side |
| TF | daily (k=5), weekly W-FRI (k=3), monthly ME (k=2) |
| Execution | Next-open fill; long-only; costs 0 |
| Universe | ALL_ohlc — {len(daily_by_sym)} symbols used |
| Slopes source | `trendline_slopes_alluniv_20260831/daily_symbol_slope_sum` |
| Benchmark | EW daily-rebalanced buy-hold of same symbols |
| IS / OOS | `<` / `≥` 2024-01-01 (OOS report-only) |
| Vol sleeves | ATR% (20) early-median terciles — diagnostic only |

## Selection honesty

Fixed rules from PaulTwenty ask; no grid search; no OOS retune.
""",
        encoding="utf-8",
    )

    def _sum_line(r: dict) -> str:
        return (
            f"| {r['slice']} | {fmt_pct(r['strat_total_ret'])} | {fmt_pct(r['bh_total_ret'])} | "
            f"{fmt_pct_signed(r['delta_total_ret'])} | {fmt_pct(r['strat_ann_ror'])} | "
            f"{fmt_pct(r['bh_ann_ror'])} | {fmt_pct(r['strat_max_dd'])} | {fmt_pct(r['bh_max_dd'])} | "
            f"{fmt_num(r['strat_sharpe'])} | {fmt_pct(r['time_in_market'], 1)} | {r['n_buys']} | {r['n_sells']} |"
        )

    sum_lines = [
        f"# SUMMARY — {STAMP}",
        "",
        f"**Verdict:** {verdict}",
        "",
        f"- Symbols used: {len(daily_by_sym)}",
        f"- Period: {period}",
        f"- ALL breadth: more UP lines {stats_all['pct_days_more_up_lines']:.1f}% of days; "
        f"more DOWN {stats_all['pct_days_more_down_lines']:.1f}%",
        f"- PaulTwenty breadth: more UP lines {stats_pt['pct_days_more_up_lines']:.1f}% of days; "
        f"more DOWN {stats_pt['pct_days_more_down_lines']:.1f}%",
        "",
        "## Signal vs EW BH",
        "",
        "| Slice | Strat total | BH total | Δ total | Strat Ann ROR | BH Ann ROR | Strat MaxDD | BH MaxDD | Strat Sharpe | TIM | Buys | Sells |",
        "|-------|-------------|----------|---------|---------------|------------|-------------|----------|--------------|-----|------|-------|",
    ]
    for r in metric_rows:
        sum_lines.append(_sum_line(r))
    if vol_rows:
        sum_lines += ["", "## Vol tercile sleeves", ""]
        for r in vol_rows:
            if r["slice"].endswith("FULL"):
                sum_lines.append(_sum_line(r))
    sum_lines += ["", "Research only.", ""]
    (OUT_DIR / "SUMMARY.md").write_text("\n".join(sum_lines), encoding="utf-8")

    html_path = OUT_DIR / "compare.html"
    write_html(
        html_path,
        verdict=verdict,
        period=period,
        n_sym=len(daily_by_sym),
        metric_rows=metric_rows,
        vol_rows=vol_rows,
        port=port,
        br_all=br_all,
        br_pt=br_pt,
        stats_all=stats_all,
        stats_pt=stats_pt,
        regimes_all=regimes_all,
        regimes_pt=regimes_pt,
        stretches_all=stretches_all,
        stretches_pt=stretches_pt,
    )

    print(f"\nVerdict: {verdict}")
    print(f"HTML: {html_path}")
    print(f"Elapsed: {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
