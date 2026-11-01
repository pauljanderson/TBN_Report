#!/usr/bin/env python3
"""Shannon multiple-timeframe lines — new drawings plus a research book.

Does not replace the house fractal monthly / weekly / daily trendlines.

Book rules made mechanical (Brian Shannon, Technical Analysis Using Multiple
Timeframes). Where the book is silent, the freeze is labeled in BASELINE.md.

Trend, each timeframe, 5-period simple moving average (SMA):
  UP = close above the SMA and the SMA itself is rising.
Higher-timeframe bars count only after that week or month has closed.

New trendlines (not the house last-two-of-any-slope lines):
  Support counts only when the last two confirmed swing lows are rising
  (a higher low). Resistance counts only when the last two confirmed swing
  highs are falling (a lower high).

Long trigger, known at the close, fill at the next open:
  Month SMA trend UP, week SMA trend UP, day trend just turned UP,
  and a rising daily support line is already confirmed with the close above it.

Exits follow the slope of the lines that were active at the trigger.
  Stop price that day = the trigger support line extended to that date.
  Target price that day = the trigger resistance line extended to that date,
  when a falling line was overhead. A close through the stop, or a higher
  timeframe trend that is no longer UP, ends the trade. No time stop.

Research only. Paul Twenty. Not gold. Not DailyRun.

  python tools/shannon_mtf_lines_20260930.py
"""
from __future__ import annotations

import argparse
import html as html_mod
import math
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    overlay_ann_ror_max_dd,
)

DATA_DIR = ROOT / "data" / "newdata" / "data"
PAULTWENTY = ROOT / "drive" / "universes" / "PaulTwenty_universe.csv"
STAMP = "shannon_mtf_lines_20260930"
OUT_DIR = ROOT / "drive" / "paul_experiments" / STAMP

PIVOT_K = {"daily": 5, "weekly": 3, "monthly": 2}
WEEK_FREQ = "W-FRI"
MONTH_FREQ = "ME"
SMA_N = 5
IS_CUT = date(2024, 1, 1)
MIN_PRICE = 5.0
MIN_ADV20 = 500_000.0
SHEET = 45_000.0
INIT_ACCT = DEFAULT_INITIAL_ACCOUNT
MIN_DAILY_BARS = 400
CHART_BARS = 504

# Distinct from house fractal colors (violet / orange / cyan).
TF_COLOR = {
    "daily": {"support": "#2e7d32", "resistance": "#c62828"},
    "weekly": {"support": "#00897b", "resistance": "#ef6c00"},
    "monthly": {"support": "#5d4037", "resistance": "#6a1b9a"},
}

ORIGINAL_REQUEST = (
    "can we implement the books strategy into a system? can we draw new "
    "trendlines using the books rules? i dont necesarily want to replace what "
    "we have but lets draw new ones. use the book for triggers and targets and "
    "exits, which may ne dynamic as trendlines that caused a trigger are sloped"
)


@dataclass
class Pivot:
    kind: str
    date: date
    price: float
    tf_bar_idx: int
    confirmed_on: date


@dataclass
class Line:
    timeframe: str
    side: str
    d1: date
    p1: float
    d2: date
    p2: float
    confirmed_on: date

    def price_on(self, t: date) -> float:
        span = (self.d2 - self.d1).days
        if span == 0:
            return float(self.p2)
        slope = (self.p2 - self.p1) / float(span)
        return float(self.p1 + slope * (t - self.d1).days)

    def slope_pct_per_day(self) -> float:
        span = (self.d2 - self.d1).days
        if span <= 0 or self.p1 == 0:
            return 0.0
        return ((self.p2 / self.p1) - 1.0) / float(span) * 100.0


def as_date(v) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return pd.Timestamp(v).date()


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
            "Date": pd.to_datetime(df[cols["date"]]).dt.date,
            "Open": df[cols["open"]].astype(float),
            "High": df[cols["high"]].astype(float),
            "Low": df[cols["low"]].astype(float),
            "Close": df[cols["close"]].astype(float),
        }
    )
    if "volume" in cols:
        out["Volume"] = df[cols["volume"]].astype(float)
    else:
        out["Volume"] = np.nan
    return out.sort_values("Date").drop_duplicates("Date").reset_index(drop=True)


def build_htf(daily: pd.DataFrame, rule: str) -> tuple[pd.DataFrame, list]:
    tmp = daily.copy()
    tmp["_dt"] = pd.to_datetime(tmp["Date"])
    groups: list[tuple[pd.Timestamp, pd.DataFrame]] = []
    for key, g in tmp.set_index("_dt").groupby(pd.Grouper(freq=rule)):
        if g is None or g.empty:
            continue
        groups.append((pd.Timestamp(key), g))
    if not groups:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "end_date"]), []
    rows = []
    members = []
    for _key, g in groups:
        members.append(g.index)
        rows.append(
            {
                "Open": float(g["Open"].iloc[0]),
                "High": float(g["High"].max()),
                "Low": float(g["Low"].min()),
                "Close": float(g["Close"].iloc[-1]),
                "end_date": as_date(g.index[-1]),
            }
        )
    return pd.DataFrame(rows), members


def fractal_pivots(high: np.ndarray, low: np.ndarray, k: int) -> list[tuple[str, int]]:
    n = len(high)
    k = max(1, int(k))
    out: list[tuple[str, int]] = []
    for i in range(k, n - k):
        wh = high[i - k : i + k + 1]
        wl = low[i - k : i + k + 1]
        if np.isfinite(high[i]) and high[i] >= float(np.max(wh)):
            out.append(("H", i))
        if np.isfinite(low[i]) and low[i] <= float(np.min(wl)):
            out.append(("L", i))
    return out


def refine_pivot_date(daily, members, kind: str, i: int, high: float, low: float):
    gidx = members[i]
    member_dates = {pd.Timestamp(ts).date() for ts in gidx}
    sub = daily[daily["Date"].isin(member_dates)]
    if sub.empty:
        return as_date(gidx[-1]), float(high if kind == "H" else low)
    if kind == "H":
        j = sub["High"].idxmax()
        return sub.loc[j, "Date"], float(sub.loc[j, "High"])
    j = sub["Low"].idxmin()
    return sub.loc[j, "Date"], float(sub.loc[j, "Low"])


def confirmed_pivots_daily(daily: pd.DataFrame, k: int) -> list[Pivot]:
    if len(daily) < 2 * k + 1:
        return []
    high = daily["High"].to_numpy(dtype=float)
    low = daily["Low"].to_numpy(dtype=float)
    dates = list(daily["Date"])
    n = len(daily)
    pivots: list[Pivot] = []
    for kind, i in fractal_pivots(high, low, k):
        conf_i = i + k
        if conf_i >= n:
            continue
        pivots.append(
            Pivot(
                kind=kind,
                date=dates[i],
                price=float(high[i] if kind == "H" else low[i]),
                tf_bar_idx=i,
                confirmed_on=dates[conf_i],
            )
        )
    return pivots


def confirmed_pivots_htf(daily: pd.DataFrame, rule: str, k: int) -> list[Pivot]:
    htf, members = build_htf(daily, rule)
    if htf.empty or len(htf) < 2 * k + 1:
        return []
    high = htf["High"].to_numpy(dtype=float)
    low = htf["Low"].to_numpy(dtype=float)
    ends = [as_date(htf.iloc[i]["end_date"]) for i in range(len(htf))]
    n = len(htf)
    pivots: list[Pivot] = []
    for kind, i in fractal_pivots(high, low, k):
        conf_i = i + k
        if conf_i >= n:
            continue
        d, px = refine_pivot_date(daily, members, kind, i, float(high[i]), float(low[i]))
        pivots.append(
            Pivot(
                kind=kind,
                date=as_date(d),
                price=px,
                tf_bar_idx=i,
                confirmed_on=ends[conf_i],
            )
        )
    return pivots


def sma_up(close: np.ndarray) -> np.ndarray:
    sma = pd.Series(close).rolling(SMA_N, min_periods=SMA_N).mean().to_numpy()
    up = np.zeros(len(close), dtype=bool)
    for i in range(1, len(close)):
        if np.isfinite(sma[i]) and np.isfinite(sma[i - 1]):
            up[i] = bool(close[i] > sma[i] and sma[i] > sma[i - 1])
    return up, sma


def htf_up_flags(daily: pd.DataFrame, rule: str) -> list[tuple[date, bool]]:
    htf, _ = build_htf(daily, rule)
    if htf.empty:
        return []
    close = htf["Close"].to_numpy(dtype=float)
    up, _sma = sma_up(close)
    return [(as_date(htf.iloc[i]["end_date"]), bool(up[i])) for i in range(len(htf))]


def flags_on_days(flags: list[tuple[date, bool]], dates: list[date], strict_before: bool) -> np.ndarray:
    ends = [d for d, _ in flags]
    vals = [v for _, v in flags]
    out = np.zeros(len(dates), dtype=bool)
    j = -1
    for i, d in enumerate(dates):
        while j + 1 < len(ends) and (ends[j + 1] < d if strict_before else ends[j + 1] <= d):
            j += 1
        if j >= 0:
            out[i] = vals[j]
    return out


def shannon_line(pivots: list[Pivot], kind: str, as_of: date, timeframe: str, rising: bool) -> Optional[Line]:
    """Last two confirmed swings. Support must be a higher low. Resistance a lower high."""
    same = [p for p in pivots if p.kind == kind and p.confirmed_on <= as_of]
    if len(same) < 2:
        return None
    a, b = same[-2], same[-1]
    if a.date >= b.date:
        return None
    if rising and not (b.price > a.price):
        return None
    if (not rising) and not (b.price < a.price):
        return None
    side = "support" if kind == "L" else "resistance"
    return Line(
        timeframe=timeframe,
        side=side,
        d1=a.date,
        p1=a.price,
        d2=b.date,
        p2=b.price,
        confirmed_on=b.confirmed_on,
    )


def overhead_resistance(piv_d: list[Pivot], piv_w: list[Pivot], as_of: date, px: float) -> Optional[Line]:
    for pivs, tf in ((piv_d, "daily"), (piv_w, "weekly")):
        line = shannon_line(pivs, "H", as_of, tf, rising=False)
        if line is None:
            continue
        if line.price_on(as_of) > px:
            return line
    return None


def simulate(sym: str, df: pd.DataFrame, piv_d, piv_w, piv_m) -> list[dict]:
    n = len(df)
    if n < MIN_DAILY_BARS + 5:
        return []
    dates = list(df["Date"])
    o = df["Open"].to_numpy(dtype=float)
    h = df["High"].to_numpy(dtype=float)
    lo = df["Low"].to_numpy(dtype=float)
    c = df["Close"].to_numpy(dtype=float)
    daily_up, _sma = sma_up(c)
    w_flags = htf_up_flags(df, WEEK_FREQ)
    m_flags = htf_up_flags(df, MONTH_FREQ)
    w_close = flags_on_days(w_flags, dates, strict_before=False)
    m_close = flags_on_days(m_flags, dates, strict_before=False)
    w_open = flags_on_days(w_flags, dates, strict_before=True)
    m_open = flags_on_days(m_flags, dates, strict_before=True)
    vol = df["Volume"].to_numpy(dtype=float)
    adv20 = pd.Series(vol).rolling(20, min_periods=20).mean().to_numpy()

    trades: list[dict] = []
    i = MIN_DAILY_BARS
    while i < n - 1:
        if c[i] < MIN_PRICE or not (np.isfinite(adv20[i]) and adv20[i] >= MIN_ADV20):
            i += 1
            continue
        turned = bool(daily_up[i] and not daily_up[i - 1])
        if not (turned and w_close[i] and m_close[i]):
            i += 1
            continue
        d = dates[i]
        sup = shannon_line(piv_d, "L", d, "daily", rising=True)
        if sup is None:
            i += 1
            continue
        stop_sig = sup.price_on(d)
        if not math.isfinite(stop_sig) or stop_sig <= 0 or c[i] <= stop_sig:
            i += 1
            continue
        res = overhead_resistance(piv_d, piv_w, d, c[i])
        entry_i = i + 1
        entry = float(o[entry_i])
        if entry <= 0:
            i += 1
            continue
        stop_entry = sup.price_on(dates[entry_i])
        if not math.isfinite(stop_entry) or entry <= stop_entry:
            i += 1
            continue
        risk = entry - stop_entry
        if risk <= 0 or risk / entry < 1e-4:
            i += 1
            continue
        tgt_entry = None
        if res is not None:
            tgt_entry = res.price_on(dates[entry_i])
            if not math.isfinite(tgt_entry) or tgt_entry <= entry:
                res = None
                tgt_entry = None

        exit_i = None
        exit_px = None
        exit_type = "OPEN"
        for j in range(entry_i, n):
            stop_px = sup.price_on(dates[j])
            tgt_px = res.price_on(dates[j]) if res is not None else None
            if tgt_px is not None and (not math.isfinite(tgt_px) or tgt_px <= stop_px):
                tgt_px = None
            oj, hj, cj = float(o[j]), float(h[j]), float(c[j])
            tf_broken = (not w_open[j]) or (not m_open[j])
            if j > entry_i and oj <= stop_px:
                exit_i, exit_px, exit_type = j, oj, "STOP"
                break
            if j > entry_i and tf_broken:
                which = "WEEK" if not w_open[j] else "MONTH"
                exit_i, exit_px, exit_type = j, oj, f"TF_{which}"
                break
            if tgt_px is not None and oj >= tgt_px:
                exit_i, exit_px, exit_type = j, oj, "TARGET"
                break
            both = tgt_px is not None and hj >= tgt_px and cj < stop_px
            if both:
                exit_i, exit_px, exit_type = j, stop_px, "STOP"
                break
            if tgt_px is not None and hj >= tgt_px:
                exit_i, exit_px, exit_type = j, tgt_px, "TARGET"
                break
            if cj < stop_px:
                exit_i, exit_px, exit_type = j, cj, "STOP"
                break
        if exit_i is None:
            exit_i = n - 1
            exit_px = float(c[exit_i])
            exit_type = "OPEN"

        opened = dates[entry_i]
        closed = dates[exit_i]
        pnl_pct = (float(exit_px) - entry) / entry * 100.0
        r_mult = (float(exit_px) - entry) / risk
        hold = max((closed - opened).days, 1)
        stop_exit = sup.price_on(closed)
        tgt_exit = res.price_on(closed) if res is not None else float("nan")
        trades.append(
            {
                "sym": sym,
                "signal": d,
                "opened": opened,
                "closed": closed,
                "entry": entry,
                "stop_entry": stop_entry,
                "stop_exit": stop_exit,
                "target_entry": float(tgt_entry) if tgt_entry is not None else float("nan"),
                "target_exit": tgt_exit,
                "exit_px": float(exit_px),
                "exit": exit_type,
                "pnl": pnl_pct,
                "r": r_mult,
                "days": float(hold),
                "pnl_d": pnl_pct / 100.0 * SHEET,
                "stop_slope_pct_day": sup.slope_pct_per_day(),
                "tgt_slope_pct_day": res.slope_pct_per_day() if res is not None else float("nan"),
                "tgt_tf": res.timeframe if res is not None else "",
                "sup": sup,
                "res": res,
                "had_target": res is not None,
            }
        )
        i = exit_i + 1
    return trades


def book_stats(trades: list[dict]) -> dict:
    empty = {
        "n": 0,
        "wr": float("nan"),
        "avg_pnl": float("nan"),
        "avg_win": float("nan"),
        "avg_loss": float("nan"),
        "pf": float("nan"),
        "avg_r": float("nan"),
        "sheet": 0.0,
        "avg_days": float("nan"),
        "ann_ror": float("nan"),
        "max_dd": float("nan"),
        "calmar": float("nan"),
        "sharpe": float("nan"),
        "cap_days": 0.0,
        "ppcd": float("nan"),
        "with_target": 0,
        "syms": 0,
        "exits": {},
    }
    if not trades:
        return empty
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gp, gl = sum(wins), abs(sum(losses))
    ov = overlay_ann_ror_max_dd(trades, cash=SHEET, initial_account=INIT_ACCT)
    ann = float(ov.get("ann_ror", float("nan")))
    dd = float(ov.get("max_dd", float("nan")))
    calmar = ann / abs(dd) if math.isfinite(ann) and math.isfinite(dd) and abs(dd) > 1e-9 else float("nan")
    cap = float(ov.get("capital_days", 0.0) or 0.0)
    sheet = sum(t["pnl_d"] for t in trades)
    exits: dict[str, int] = {}
    for t in trades:
        exits[t["exit"]] = exits.get(t["exit"], 0) + 1
    return {
        "n": len(trades),
        "wr": 100.0 * len(wins) / len(trades),
        "avg_pnl": sum(pnls) / len(trades),
        "avg_win": (sum(wins) / len(wins)) if wins else float("nan"),
        "avg_loss": (sum(losses) / len(losses)) if losses else float("nan"),
        "pf": (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0),
        "avg_r": sum(t["r"] for t in trades) / len(trades),
        "sheet": sheet,
        "avg_days": sum(t["days"] for t in trades) / len(trades),
        "ann_ror": ann,
        "max_dd": dd,
        "calmar": calmar,
        "sharpe": float(ov.get("sharpe", float("nan"))),
        "cap_days": cap,
        "ppcd": (sheet / cap) if cap > 0 else float("nan"),
        "with_target": sum(1 for t in trades if t["had_target"]),
        "syms": len({t["sym"] for t in trades}),
        "exits": exits,
    }


def fmt_num(x, nd=2, suffix=""):
    if x is None or not math.isfinite(float(x)):
        return "—"
    return f"{float(x):.{nd}f}{suffix}"


def fmt_money(x):
    if x is None or not math.isfinite(float(x)):
        return "—"
    return f"${float(x):,.0f}"


def sortable_th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


SORT_JS = """
<script>
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : NaN;
    if (type === "text") return s.toUpperCase();
    if (type === "date") {
      var iso = s.match(/(\\d{4})-(\\d{2})-(\\d{2})/);
      if (iso) return parseInt(iso[1] + iso[2] + iso[3], 10);
      return 0;
    }
    var n = s.replace(/[$,%+]/g, "").replace(/,/g, "");
    var v = parseFloat(n);
    return Number.isFinite(v) ? v : NaN;
  }
  function sortTable(table, col, type, dir) {
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var rows = Array.from(tbody.querySelectorAll("tr"));
    rows.sort(function (a, b) {
      var av = parseSortValue(a.cells[col] && a.cells[col].textContent, type);
      var bv = parseSortValue(b.cells[col] && b.cells[col].textContent, type);
      if (typeof av === "string" || typeof bv === "string") {
        return dir * String(av).localeCompare(String(bv));
      }
      if (isNaN(av) && isNaN(bv)) return 0;
      if (isNaN(av)) return 1;
      if (isNaN(bv)) return -1;
      return dir * (av - bv);
    });
    rows.forEach(function (r) { tbody.appendChild(r); });
  }
  document.querySelectorAll("table.sortable").forEach(function (table) {
    table.querySelectorAll("th.sortable-th").forEach(function (th, col) {
      function activate() {
        var dir = th.classList.contains("sort-asc") ? -1 : 1;
        table.querySelectorAll("th.sortable-th").forEach(function (h) {
          h.classList.remove("sort-asc", "sort-desc");
          h.setAttribute("aria-sort", "none");
        });
        th.classList.add(dir === 1 ? "sort-asc" : "sort-desc");
        th.setAttribute("aria-sort", dir === 1 ? "ascending" : "descending");
        sortTable(table, col, th.getAttribute("data-sort") || "text", dir);
      }
      th.addEventListener("click", activate);
      th.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activate(); }
      });
    });
  });
})();
</script>
"""


def _plot_line(ax, line: Line, win_start: date, win_end: date, lw: float):
    y0 = line.price_on(win_start)
    y1 = line.price_on(win_end)
    color = TF_COLOR[line.timeframe][line.side]
    ls = "-" if line.side == "support" else "--"
    ax.plot(
        [pd.Timestamp(win_start), pd.Timestamp(win_end)],
        [y0, y1],
        color=color,
        lw=lw,
        ls=ls,
        solid_capstyle="round",
        zorder=4,
    )
    for dd, pp in ((line.d1, line.p1), (line.d2, line.p2)):
        if win_start <= dd <= win_end:
            ax.scatter([pd.Timestamp(dd)], [pp], s=22, color=color, zorder=5, edgecolors="white", linewidths=0.4)


def draw_chart(sym: str, df: pd.DataFrame, piv_d, piv_w, piv_m, trades: list[dict], path: Path) -> str:
    n = len(df)
    start = max(0, n - CHART_BARS)
    view = df.iloc[start:]
    dates = list(view["Date"])
    win_start, win_end = dates[0], dates[-1]
    c = view["Close"].to_numpy(dtype=float)
    h = view["High"].to_numpy(dtype=float)
    lo = view["Low"].to_numpy(dtype=float)
    _up, sma = sma_up(df["Close"].to_numpy(dtype=float))
    sma_v = sma[start:]
    x = [pd.Timestamp(d) for d in dates]

    fig, ax = plt.subplots(figsize=(12.2, 6.4), dpi=110)
    ax.fill_between(x, lo, h, color="#cfd8dc", alpha=0.55, linewidth=0, zorder=1)
    ax.plot(x, c, color="#263238", lw=1.05, zorder=2, label="Close")
    ax.plot(x, sma_v, color="#1565c0", lw=1.15, alpha=0.9, zorder=3, label="Daily SMA(5)")

    asof = dates[-1]
    lines = []
    for pivs, tf in ((piv_d, "daily"), (piv_w, "weekly"), (piv_m, "monthly")):
        sup = shannon_line(pivs, "L", asof, tf, rising=True)
        res = shannon_line(pivs, "H", asof, tf, rising=False)
        if sup:
            lines.append(sup)
        if res:
            lines.append(res)
    lw = {"daily": 1.3, "weekly": 1.7, "monthly": 2.2}
    for line in lines:
        _plot_line(ax, line, win_start, win_end, lw[line.timeframe])

    for t in trades:
        if t["closed"] < win_start or t["opened"] > win_end:
            continue
        left = max(t["opened"], win_start)
        right = min(t["closed"], win_end)
        xs = [pd.Timestamp(left), pd.Timestamp(right)]
        ax.plot(xs, [t["sup"].price_on(left), t["sup"].price_on(right)], color="#000000", lw=1.0, ls=":", zorder=6)
        if t["res"] is not None:
            ax.plot(
                xs,
                [t["res"].price_on(left), t["res"].price_on(right)],
                color="#6a1b9a",
                lw=1.0,
                ls=":",
                zorder=6,
            )
        if win_start <= t["opened"] <= win_end:
            ax.scatter([pd.Timestamp(t["opened"])], [t["entry"]], marker="^", s=46, color="#1b5e20", zorder=7)
        if win_start <= t["closed"] <= win_end:
            ax.scatter([pd.Timestamp(t["closed"])], [t["exit_px"]], marker="v", s=46, color="#b71c1c", zorder=7)

    pad_lo, pad_hi = float(np.nanmin(lo)), float(np.nanmax(h))
    span = (pad_hi - pad_lo) if pad_hi > pad_lo else abs(pad_hi) * 0.02 or 1.0
    ax.set_ylim(pad_lo - span * 0.06, pad_hi + span * 0.08)
    ax.set_xlim(x[0] - pd.Timedelta(days=2), x[-1] + pd.Timedelta(days=3))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.grid(True, alpha=0.25)
    ax.set_title(f"{sym}  —  Shannon lines (house fractal lines are not on this chart)")
    ax.set_ylabel("Price")
    handles = [
        Line2D([0], [0], color="#263238", lw=1.2, label="Close"),
        Line2D([0], [0], color="#1565c0", lw=1.2, label="Daily 5-day average"),
        Line2D([0], [0], color="#2e7d32", lw=1.5, label="Day rising support"),
        Line2D([0], [0], color="#00897b", lw=1.7, label="Week rising support"),
        Line2D([0], [0], color="#5d4037", lw=2.1, label="Month rising support"),
        Line2D([0], [0], color="#c62828", lw=1.3, ls="--", label="Day falling resistance"),
        Line2D([0], [0], color="#ef6c00", lw=1.5, ls="--", label="Week falling resistance"),
        Line2D([0], [0], color="#6a1b9a", lw=1.8, ls="--", label="Month falling resistance"),
        Line2D([0], [0], color="#000000", lw=1.0, ls=":", label="Frozen stop while in a trade"),
        Line2D([0], [0], marker="^", color="#1b5e20", lw=0, label="Entry"),
        Line2D([0], [0], marker="v", color="#b71c1c", lw=0, label="Exit"),
    ]
    ax.legend(handles=handles, loc="upper left", fontsize=8, framealpha=0.92)
    fig.autofmt_xdate()
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path.name


def snapshot_row(sym: str, df: pd.DataFrame, piv_d, piv_w, piv_m, n_trades: int) -> dict:
    asof = df["Date"].iloc[-1]
    close = float(df["Close"].iloc[-1])
    daily_up, _sma = sma_up(df["Close"].to_numpy(dtype=float))
    w_flags = htf_up_flags(df, WEEK_FREQ)
    m_flags = htf_up_flags(df, MONTH_FREQ)
    dates = list(df["Date"])
    w_up = bool(flags_on_days(w_flags, dates, False)[-1])
    m_up = bool(flags_on_days(m_flags, dates, False)[-1])
    d_up = bool(daily_up[-1])

    def slope_of(pivs, tf, kind, rising):
        line = shannon_line(pivs, kind, asof, tf, rising)
        if line is None:
            return "—", float("nan")
        return ("UP" if rising else "DOWN"), line.slope_pct_per_day()

    d_sup, d_sup_s = slope_of(piv_d, "daily", "L", True)
    d_res, d_res_s = slope_of(piv_d, "daily", "H", False)
    w_sup, w_sup_s = slope_of(piv_w, "weekly", "L", True)
    m_sup, m_sup_s = slope_of(piv_m, "monthly", "L", True)
    return {
        "sym": sym,
        "asof": asof,
        "close": close,
        "m": "UP" if m_up else "not up",
        "w": "UP" if w_up else "not up",
        "d": "UP" if d_up else "not up",
        "d_sup": d_sup,
        "d_sup_s": d_sup_s,
        "d_res": d_res,
        "d_res_s": d_res_s,
        "w_sup": w_sup,
        "w_sup_s": w_sup_s,
        "m_sup": m_sup,
        "m_sup_s": m_sup_s,
        "n": n_trades,
    }


def metrics_row(label: str, st: dict) -> str:
    exits = ", ".join(f"{k} {v}" for k, v in sorted(st["exits"].items())) or "—"
    cells = [
        label,
        str(st["n"]),
        str(st["syms"]),
        fmt_num(st["wr"], 1, "%"),
        fmt_num(st["avg_pnl"], 2, "%"),
        fmt_num(st["avg_win"], 2, "%"),
        fmt_num(st["avg_loss"], 2, "%"),
        fmt_num(st["pf"], 2),
        fmt_num(st["avg_r"], 2),
        fmt_money(st["sheet"]),
        fmt_num(st["ann_ror"], 1, "%"),
        fmt_num(st["max_dd"], 1, "%"),
        fmt_num(st["calmar"], 2),
        fmt_num(st["sharpe"], 2),
        fmt_num(st["avg_days"], 1),
        fmt_num(st["cap_days"], 0),
        fmt_money(st["ppcd"]),
        str(st["with_target"]),
        exits,
    ]
    kinds_note = cells
    return "<tr>" + "".join(f"<td>{html_mod.escape(v)}</td>" for v in kinds_note) + "</tr>"


def write_report(snaps: list[dict], trades: list[dict], charts: list[tuple[str, str]]) -> None:
    full = book_stats(trades)
    is_tr = [t for t in trades if t["opened"] < IS_CUT]
    oos_tr = [t for t in trades if t["opened"] >= IS_CUT]
    ins, oos = book_stats(is_tr), book_stats(oos_tr)

    example = ""
    climbed = [t for t in trades if t["stop_exit"] > t["stop_entry"] * 1.005]
    if climbed:
        t = climbed[0]
        example = (
            f"<p>Worked example of a moving stop: <b>{html_mod.escape(t['sym'])}</b> "
            f"signaled {t['signal'].isoformat()}. The rising support line was "
            f"${t['stop_entry']:.2f} on the entry day and ${t['stop_exit']:.2f} on "
            f"{t['closed'].isoformat()} "
            f"({t['stop_slope_pct_day']:+.3f}% per day). "
            f"Exit {html_mod.escape(t['exit'])} at ${t['exit_px']:.2f}, "
            f"PnL {t['pnl']:+.2f}%.</p>"
        )

    metric_headers = [
        ("Slice", "text"),
        ("Trades", "num"),
        ("Symbols", "num"),
        ("Win %", "num"),
        ("Avg PnL %", "num"),
        ("Avg win %", "num"),
        ("Avg loss %", "num"),
        ("Profit factor", "num"),
        ("Avg R vs entry stop", "num"),
        ("Sheet $", "num"),
        ("Ann ROR", "num"),
        ("Max DD", "num"),
        ("Calmar", "num"),
        ("Sharpe", "num"),
        ("Avg days", "num"),
        ("Capital days", "num"),
        ("$ / capital day", "num"),
        ("Trades with a sloped target", "num"),
        ("Exits", "text"),
    ]
    head = "".join(sortable_th(a, b) for a, b in metric_headers)
    body = metrics_row("Full", full) + metrics_row("IS before 2024", ins) + metrics_row("OOS 2024+", oos)

    snap_head = "".join(
        sortable_th(a, b)
        for a, b in [
            ("Symbol", "text"),
            ("As of", "date"),
            ("Last", "num"),
            ("Month trend", "text"),
            ("Week trend", "text"),
            ("Day trend", "text"),
            ("D support", "text"),
            ("D support %/day", "num"),
            ("D resistance", "text"),
            ("D resistance %/day", "num"),
            ("W support", "text"),
            ("W support %/day", "num"),
            ("M support", "text"),
            ("M support %/day", "num"),
            ("Trades", "num"),
        ]
    )
    snap_rows = []
    for s in snaps:
        vals = [
            s["sym"],
            s["asof"].isoformat(),
            f"{s['close']:.2f}",
            s["m"],
            s["w"],
            s["d"],
            s["d_sup"],
            fmt_num(s["d_sup_s"], 3),
            s["d_res"],
            fmt_num(s["d_res_s"], 3),
            s["w_sup"],
            fmt_num(s["w_sup_s"], 3),
            s["m_sup"],
            fmt_num(s["m_sup_s"], 3),
            str(s["n"]),
        ]
        snap_rows.append("<tr>" + "".join(f"<td>{html_mod.escape(v)}</td>" for v in vals) + "</tr>")

    trade_head = "".join(
        sortable_th(a, b)
        for a, b in [
            ("Symbol", "text"),
            ("Signal", "date"),
            ("Opened", "date"),
            ("Closed", "date"),
            ("Entry", "num"),
            ("Stop at entry", "num"),
            ("Stop at exit date", "num"),
            ("Target at entry", "num"),
            ("Target at exit date", "num"),
            ("Target line", "text"),
            ("Exit", "text"),
            ("Exit price", "num"),
            ("PnL %", "num"),
            ("R", "num"),
            ("Days", "num"),
            ("Stop %/day", "num"),
            ("Target %/day", "num"),
            ("Sample", "text"),
        ]
    )
    trade_rows = []
    for t in trades:
        sample = "OOS" if t["opened"] >= IS_CUT else "IS"
        vals = [
            t["sym"],
            t["signal"].isoformat(),
            t["opened"].isoformat(),
            t["closed"].isoformat(),
            f"{t['entry']:.2f}",
            f"{t['stop_entry']:.2f}",
            f"{t['stop_exit']:.2f}",
            fmt_num(t["target_entry"], 2),
            fmt_num(t["target_exit"], 2),
            t["tgt_tf"] or "—",
            t["exit"],
            f"{t['exit_px']:.2f}",
            f"{t['pnl']:.2f}",
            f"{t['r']:.2f}",
            f"{t['days']:.0f}",
            f"{t['stop_slope_pct_day']:.3f}",
            fmt_num(t["tgt_slope_pct_day"], 3),
            sample,
        ]
        trade_rows.append("<tr>" + "".join(f"<td>{html_mod.escape(v)}</td>" for v in vals) + "</tr>")

    charts_html = []
    for sym, name in charts:
        charts_html.append(
            f'<section class="chart"><h3>{html_mod.escape(sym)}</h3>'
            f'<img src="charts/{html_mod.escape(name)}" alt="{html_mod.escape(sym)} Shannon lines">'
            f"</section>"
        )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Shannon multiple-timeframe lines — {STAMP}</title>
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 1.25rem auto; max-width: 1180px;
  padding: 0 1rem 2rem; color: #1f1d1a; background: #f7f4ee; }}
h1 {{ font-size: 1.55rem; margin-bottom: 0.2rem; }}
.sub {{ color: #5c564c; font-size: 0.92rem; }}
.callout {{ background: #fff; border: 1px solid #d9d1c3; padding: 0.8rem 1rem; margin: 0.8rem 0; }}
table.sortable {{ border-collapse: collapse; width: 100%; background: #fff; font-size: 0.82rem; margin: 0.4rem 0 1.2rem; }}
th, td {{ border: 1px solid #e3dccf; padding: 0.28rem 0.4rem; text-align: left; }}
th.sortable-th {{ cursor: pointer; user-select: none; background: #ece8df; }}
th.sortable-th .sort-ind::after {{ content: " ↕"; opacity: 0.35; }}
th.sortable-th.sort-asc .sort-ind::after {{ content: " ↑"; opacity: 0.9; }}
th.sortable-th.sort-desc .sort-ind::after {{ content: " ↓"; opacity: 0.9; }}
section.chart img {{ width: 100%; max-width: 1100px; height: auto; background: #fff; border: 1px solid #e3dccf; }}
code {{ font-size: 0.86em; }}
</style>
</head>
<body>
<h1>Shannon lines — new drawings, same old fractal lines left in place</h1>
<p class="sub">Stamp <code>{STAMP}</code> · Paul Twenty · research only · not gold · not DailyRun ·
generated {datetime.now().strftime("%Y-%m-%d %H:%M")} · Click column headers to sort.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{html_mod.escape(ORIGINAL_REQUEST)}</p>
<h2>In plain English</h2>
<p>The trendlines already on the live charts stay as they are. This page adds a second set,
drawn the way Brian Shannon’s book describes a trend, and then trades off those new lines.</p>
<p>Shannon’s test is simple. On each clock — month, week, and day — a trend is up only when
price is above a rising 5-period average (a simple moving average, SMA). Separately, a support
line is drawn only through the last two swing lows if the newer low is higher. A resistance
line is drawn only through the last two swing highs if the newer high is lower. A line that
slopes the wrong way is not drawn. The live charts still draw those wrong-way lines; this set does not.</p>
<p>A buy happens only when the month and the week are already up, and the day has just turned
back up, with price still above that rising daily support line. The buy is filled at the next
morning’s open. The stop is that same support line, extended forward. Because the line slopes
up, the stop price is a little higher every day. The target, when a falling resistance line
sits overhead, is that line extended forward, so the target price moves too. If the week or
the month stops being an uptrend, the trade is closed even if the daily line has not broken.
There is no “sell after this many days” rule.</p>
<p>Out-of-sample here means entries on or after 2024-01-01. That row is a report. It was not
used to pick the rules. This is a research test on the Paul Twenty names, not a live system.</p>
</div>

<h2>Results</h2>
<p class="sub">Sheet dollars use a ${SHEET:,.0f} notional per trade so the figures can sit next to other
research books. Costs are 0. R is measured against the stop distance on the entry day, before
the line has climbed. Click column headers to sort.</p>
<table class="sortable"><thead><tr>{head}</tr></thead><tbody>
{body}
</tbody></table>
{example}

<h2>What the new lines say right now</h2>
<p class="sub">“UP” on month, week, or day means price is above a rising 5-period average on that clock.
Support is shown only when the last two lows are rising. Resistance is shown only when the
last two highs are falling. A dash means that Shannon line does not exist today.</p>
<table class="sortable"><thead><tr>{snap_head}</tr></thead><tbody>
{''.join(snap_rows)}
</tbody></table>

<h2>Trades</h2>
<p class="sub">Stop at exit date is the support line’s price on the day the trade ended, whether or not
the exit was that line. Target at exit date is the resistance line that day. OPEN means the
trade was still on at the last bar and is marked at that close.</p>
<table class="sortable"><thead><tr>{trade_head}</tr></thead><tbody>
{''.join(trade_rows)}
</tbody></table>

<h2>Charts</h2>
<p class="sub">Last {CHART_BARS} bars. Solid lines are rising Shannon support: green day, teal week,
brown month. Dashed lines are falling Shannon resistance: red day, orange week, purple month.
The blue line that hugs price is the 5-day average, not a trendline. The black dotted
segment is the frozen stop for a trade in this window. A line is omitted when the last
two swings do not slope the way the book requires. House fractal trendlines are not drawn here.</p>
{''.join(charts_html)}
{SORT_JS}
</body>
</html>
"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "report.html").write_text(page, encoding="utf-8")

    baseline = f"""# {STAMP}

Research only. Not gold. Not DailyRun. House fractal trendlines are unchanged.

## What you asked

{ORIGINAL_REQUEST}

## In plain English

A second set of trendlines. A support line exists only when the last two swing lows
are rising. A resistance line exists only when the last two swing highs are falling.
Buys require the month and the week already up on a rising 5-period average, and the
day just turning up, with price above the rising daily support line. The stop and the
target are those lines extended forward, so both prices move with the slope. A week
or month that stops being an uptrend also closes the trade.

## Freeze

| Item | Choice |
|---|---|
| Universe | `drive/universes/PaulTwenty_universe.csv` |
| OHLC | `data/newdata/data/{{SYM}}.csv` |
| Trend | 5-period SMA. UP = close above SMA and SMA rising |
| Higher-timeframe timing | Week and month count only after the bar has closed |
| Swing points | Same fractal confirm as the house lines: daily k=5, weekly k=3 (W-FRI), monthly k=2 (ME). The book says “obvious” swings and does not give a number. This k is the objective stand-in, shared so the new lines are comparable. |
| Shannon support | Last two confirmed lows, later low strictly higher |
| Shannon resistance | Last two confirmed highs, later high strictly lower |
| Trigger | Month UP and week UP at the signal close, daily SMA trend turns UP, rising daily support exists, close above that line |
| Entry | Next open. Skip if the open is already through the support line |
| Stop | Frozen trigger support line, projected each day. Gap through the line exits at the open. Otherwise a close through the line exits at the close. A wick through the line is not an exit. |
| Target | Frozen falling resistance, daily if it is overhead, else weekly. Projected each day. No target if neither line is above the entry. High touches the line, or the open gaps through it. |
| Same-bar stop and target | Stop is filled. The book’s close-break and an intrabar target can both print; which came first is unknown. |
| Higher-timeframe exit | At the next open after a completed week or month is no longer UP |
| Time stop | None |
| Side | Longs only |
| One position | Flat before the next signal on that symbol |
| Still open | Marked at the last close, exit `OPEN` |
| IS / OOS | Entry before 2024-01-01 / on or after. OOS is report-only. Rules were not picked from this table. |
| Costs | 0 |
| Sheet notional | ${SHEET:,.0f} (house compare scale, not from the book) |
| Liquidity | Close ≥ ${MIN_PRICE:.0f} and 20-day average volume ≥ {MIN_ADV20:,.0f} (house filter, not from the book) |

## Not in this freeze

Anchored volume-weighted average price is Shannon’s later book, not this one.
Shorts are the mirror image and are not run here.
"""
    (OUT_DIR / "BASELINE.md").write_text(baseline, encoding="utf-8")


def write_trades_csv(trades: list[dict]) -> None:
    cols = [
        "sym",
        "signal",
        "opened",
        "closed",
        "entry",
        "stop_entry",
        "stop_exit",
        "target_entry",
        "target_exit",
        "tgt_tf",
        "exit",
        "exit_px",
        "pnl",
        "r",
        "days",
        "stop_slope_pct_day",
        "tgt_slope_pct_day",
        "had_target",
    ]
    path = OUT_DIR / "trades.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv_writer(f)
        w.writerow(cols)
        for t in trades:
            row = []
            for k in cols:
                v = t[k]
                if isinstance(v, date):
                    v = v.isoformat()
                row.append(v)
            w.writerow(row)


def csv_writer(f):
    import csv

    return csv.writer(f)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", type=Path, default=PAULTWENTY)
    args = ap.parse_args()
    symbols = load_universe(args.universe)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    chart_dir = OUT_DIR / "charts"
    snaps = []
    trades: list[dict] = []
    charts: list[tuple[str, str]] = []
    for sym in symbols:
        df = load_ohlc(sym)
        if df is None or len(df) < MIN_DAILY_BARS:
            print(f"SKIP {sym}: no/short OHLC", file=sys.stderr)
            continue
        piv_d = confirmed_pivots_daily(df, PIVOT_K["daily"])
        piv_w = confirmed_pivots_htf(df, WEEK_FREQ, PIVOT_K["weekly"])
        piv_m = confirmed_pivots_htf(df, MONTH_FREQ, PIVOT_K["monthly"])
        sym_trades = simulate(sym, df, piv_d, piv_w, piv_m)
        trades.extend(sym_trades)
        snaps.append(snapshot_row(sym, df, piv_d, piv_w, piv_m, len(sym_trades)))
        name = draw_chart(sym, df, piv_d, piv_w, piv_m, sym_trades, chart_dir / f"{sym}.png")
        charts.append((sym, name))
        print(f"{sym}: trades {len(sym_trades)}", flush=True)
    trades.sort(key=lambda t: (t["opened"], t["sym"]))
    write_trades_csv(trades)
    write_report(snaps, trades, charts)
    st = book_stats(trades)
    print(
        f"DONE N={st['n']} WR={st['wr']:.1f}% avg={st['avg_pnl']:.2f}% "
        f"PF={st['pf']:.2f} -> {OUT_DIR / 'report.html'}",
        flush=True,
    )


if __name__ == "__main__":
    main()
