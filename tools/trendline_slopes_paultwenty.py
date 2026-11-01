#!/usr/bin/env python3
"""PaulTwenty day-by-day fractal trendline slope tracker.

Look-ahead-safe confirmation (match tools/trendline_break_ab.py):
  fractal pivots need ±k bars; pivot at TF index i is usable only after
  TF bar i+k completes (confirmed_on = that bar's last trading day).

Timeframes: daily (k=5), weekly W-FRI (k=3), monthly ME (k=2).
Sides: support = last two swing lows; resistance = last two swing highs.

Slope definitions (documented in stamp BASELINE.md):
  slope_per_day     = (p2 - p1) / (d2 - d1).days          # price units / calendar day
  slope_pct_per_day = ((p2 / p1) - 1) / days * 100        # % of p1 per calendar day
  slope_deg         = atan(slope_per_day) * 180/pi        # relative to (price_unit, day) axes
  slope_sign        = +1 / -1 / 0 (flat if |slope_per_day| < 1e-12)

Research only — not gold, not DailyRun.

Usage:
  python tools/trendline_slopes_paultwenty.py
  python tools/trendline_slopes_paultwenty.py --stamp trendline_slopes_paultwenty_20260831
"""
from __future__ import annotations

import argparse
import html as html_mod
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "newdata" / "data"
DRIVE = ROOT / "drive"
PAULTWENTY = DRIVE / "universes" / "PaulTwenty_universe.csv"
DEFAULT_STAMP = "trendline_slopes_paultwenty_20260831"

PIVOT_K = {"daily": 5, "weekly": 3, "monthly": 2}
WEEK_FREQ = "W-FRI"
MONTH_FREQ = "ME"
FLAT_EPS = 1e-12

SORT_CSS = """
th.sortable-th { cursor: pointer; user-select: none; white-space: nowrap; }
th.sortable-th:hover { background: #e2e8f0; }
th.sortable-th .sort-ind::after { content: " \\2195"; opacity: .35; font-size: .85em; }
th.sortable-th.sort-asc .sort-ind::after { content: " \\2191"; opacity: .9; }
th.sortable-th.sort-desc .sort-ind::after { content: " \\2193"; opacity: .9; }
body { font-family: Segoe UI, system-ui, sans-serif; margin: 1.5rem; color: #0f172a; background: #f8fafc; }
h1 { font-size: 1.45rem; margin: 0 0 .35rem; }
h2 { font-size: 1.15rem; margin: 1.6rem 0 .5rem; border-bottom: 1px solid #cbd5e1; padding-bottom: .25rem; }
.meta, .caveat { color: #475569; font-size: .92rem; max-width: 70rem; }
.insight { background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: .75rem 1rem; margin: .75rem 0; max-width: 70rem; }
table.sortable { border-collapse: collapse; background: #fff; font-size: .88rem; margin: .5rem 0 1rem; }
table.sortable th, table.sortable td { border: 1px solid #e2e8f0; padding: .35rem .55rem; text-align: left; }
table.sortable th { background: #f1f5f9; }
.up { color: #047857; font-weight: 600; }
.down { color: #b91c1c; font-weight: 600; }
.flat { color: #64748b; }
.badge { display: inline-block; padding: .1rem .45rem; border-radius: 4px; font-size: .8rem; background: #e2e8f0; }
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


@dataclass(frozen=True)
class Pivot:
    kind: str  # H | L
    date: date
    price: float
    tf_bar_idx: int
    confirmed_on: date


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
            "Date": pd.to_datetime(df[cols["date"]]).dt.date,
            "Open": df[cols["open"]].astype(float),
            "High": df[cols["high"]].astype(float),
            "Low": df[cols["low"]].astype(float),
            "Close": df[cols["close"]].astype(float),
        }
    )
    if "volume" in cols:
        out["Volume"] = df[cols["volume"]].astype(float)
    return out.sort_values("Date").drop_duplicates("Date").reset_index(drop=True)


def build_htf(daily: pd.DataFrame, rule: str) -> tuple[pd.DataFrame, list[pd.DatetimeIndex]]:
    tmp = daily.copy()
    tmp["_dt"] = pd.to_datetime(tmp["Date"])
    groups: list[tuple[pd.Timestamp, pd.DataFrame]] = []
    for key, g in tmp.set_index("_dt").groupby(pd.Grouper(freq=rule)):
        if g is None or g.empty:
            continue
        groups.append((pd.Timestamp(key), g))
    if not groups:
        empty = pd.DataFrame(columns=["Open", "High", "Low", "Close", "end_date"])
        return empty, []
    rows = []
    members: list[pd.DatetimeIndex] = []
    for _key, g in groups:
        members.append(g.index)
        rows.append(
            {
                "Open": float(g["Open"].iloc[0]),
                "High": float(g["High"].max()),
                "Low": float(g["Low"].min()),
                "Close": float(g["Close"].iloc[-1]),
                "end_date": pd.Timestamp(g.index[-1]).date(),
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


def refine_pivot_date(
    daily: pd.DataFrame,
    members: list[pd.DatetimeIndex],
    kind: str,
    i: int,
    high: float,
    low: float,
) -> tuple[date, float]:
    gidx = members[i]
    member_dates = {pd.Timestamp(ts).date() for ts in gidx}
    sub = daily[daily["Date"].isin(member_dates)]
    if sub.empty:
        return pd.Timestamp(gidx[-1]).date(), float(high if kind == "H" else low)
    if kind == "H":
        j = sub["High"].idxmax()
        return sub.loc[j, "Date"], float(sub.loc[j, "High"])
    j = sub["Low"].idxmin()
    return sub.loc[j, "Date"], float(sub.loc[j, "Low"])


def confirmed_pivots_daily(daily: pd.DataFrame, k: int) -> list[Pivot]:
    """Daily fractal pivots; confirmed_on = date of bar i+k."""
    if len(daily) < 2 * k + 1:
        return []
    high = daily["High"].to_numpy(dtype=float)
    low = daily["Low"].to_numpy(dtype=float)
    dates = list(daily["Date"])
    raw = fractal_pivots(high, low, k=k)
    n = len(daily)
    pivots: list[Pivot] = []
    for kind, i in raw:
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


def confirmed_pivots_htf(
    daily: pd.DataFrame,
    rule: str,
    k: int,
) -> list[Pivot]:
    htf, members = build_htf(daily, rule)
    if htf.empty or len(htf) < 2 * k + 1:
        return []
    high = htf["High"].to_numpy(dtype=float)
    low = htf["Low"].to_numpy(dtype=float)
    ends = [htf.iloc[i]["end_date"] for i in range(len(htf))]
    raw = fractal_pivots(high, low, k=k)
    n = len(htf)
    pivots: list[Pivot] = []
    for kind, i in raw:
        conf_i = i + k
        if conf_i >= n:
            continue
        d, px = refine_pivot_date(daily, members, kind, i, float(high[i]), float(low[i]))
        pivots.append(
            Pivot(
                kind=kind,
                date=d,
                price=px,
                tf_bar_idx=i,
                confirmed_on=ends[conf_i],
            )
        )
    return pivots


def last_two_confirmed(pivots: list[Pivot], kind: str, as_of: date) -> Optional[tuple[Pivot, Pivot]]:
    same = [p for p in pivots if p.kind == kind and p.confirmed_on <= as_of]
    if len(same) < 2:
        return None
    a, b = same[-2], same[-1]
    if a.date >= b.date:
        return None
    return a, b


def line_price_at(d1: date, p1: float, d2: date, p2: float, t: date) -> float:
    days_total = (d2 - d1).days
    if days_total == 0:
        return float(p2)
    slope = (p2 - p1) / float(days_total)
    return float(p1 + slope * (t - d1).days)


def slope_metrics(d1: date, p1: float, d2: date, p2: float) -> dict:
    days = (d2 - d1).days
    if days <= 0 or not (math.isfinite(p1) and math.isfinite(p2)) or p1 == 0:
        return {
            "slope_per_day": 0.0,
            "slope_pct_per_day": 0.0,
            "slope_deg": 0.0,
            "slope_sign": 0,
            "direction": "FLAT",
        }
    slope_per_day = (p2 - p1) / float(days)
    slope_pct_per_day = ((p2 / p1) - 1.0) / float(days) * 100.0
    slope_deg = math.degrees(math.atan(slope_per_day))
    if abs(slope_per_day) < FLAT_EPS:
        sign = 0
        direction = "FLAT"
    elif slope_per_day > 0:
        sign = 1
        direction = "UP"
    else:
        sign = -1
        direction = "DOWN"
    return {
        "slope_per_day": slope_per_day,
        "slope_pct_per_day": slope_pct_per_day,
        "slope_deg": slope_deg,
        "slope_sign": sign,
        "direction": direction,
    }


def rows_for_symbol(sym: str, df: pd.DataFrame) -> list[dict]:
    piv_d = confirmed_pivots_daily(df, PIVOT_K["daily"])
    piv_w = confirmed_pivots_htf(df, WEEK_FREQ, PIVOT_K["weekly"])
    piv_m = confirmed_pivots_htf(df, MONTH_FREQ, PIVOT_K["monthly"])
    specs = (
        ("daily", piv_d),
        ("weekly", piv_w),
        ("monthly", piv_m),
    )
    rows: list[dict] = []
    dates = list(df["Date"])
    closes = list(df["Close"].astype(float))
    for di, as_of in enumerate(dates):
        close = closes[di]
        for tf, pivs in specs:
            for kind, side in (("L", "support"), ("H", "resistance")):
                pair = last_two_confirmed(pivs, kind, as_of)
                if not pair:
                    continue
                a, b = pair
                active_from = max(a.confirmed_on, b.confirmed_on)
                if active_from > as_of:
                    continue
                sm = slope_metrics(a.date, a.price, b.date, b.price)
                line_px = line_price_at(a.date, a.price, b.date, b.price, as_of)
                dist_pct = (
                    (close - line_px) / line_px * 100.0
                    if math.isfinite(line_px) and line_px != 0
                    else float("nan")
                )
                rows.append(
                    {
                        "symbol": sym,
                        "date": as_of.isoformat(),
                        "timeframe": tf,
                        "side": side,
                        "slope_sign": sm["slope_sign"],
                        "slope_per_day": sm["slope_per_day"],
                        "slope_pct_per_day": sm["slope_pct_per_day"],
                        "slope_deg": sm["slope_deg"],
                        "direction": sm["direction"],
                        "d1": a.date.isoformat(),
                        "p1": a.price,
                        "d2": b.date.isoformat(),
                        "p2": b.price,
                        "active_from": active_from.isoformat(),
                        "line_price_at_asof": line_px,
                        "close": close,
                        "dist_pct": dist_pct,
                    }
                )
    return rows


def build_summary(long_df: pd.DataFrame) -> pd.DataFrame:
    """Latest as-of per symbol × TF × side + direction counts over full history."""
    if long_df.empty:
        return pd.DataFrame()
    latest_date = long_df.groupby("symbol")["date"].transform("max")
    latest = long_df[long_df["date"] == latest_date].copy()
    latest = latest.sort_values(["symbol", "timeframe", "side"]).reset_index(drop=True)
    return latest


def direction_counts(df: pd.DataFrame, *, latest_only: bool = False) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    work = df
    if latest_only:
        # Snapshot = rows on the global max trading date present in the book
        work = df[df["date"] == df["date"].max()]
    rows = []
    for (tf, side), g in work.groupby(["timeframe", "side"]):
        c = g["direction"].value_counts()
        rows.append(
            {
                "timeframe": tf,
                "side": side,
                "n_rows": int(len(g)),
                "UP": int(c.get("UP", 0)),
                "DOWN": int(c.get("DOWN", 0)),
                "FLAT": int(c.get("FLAT", 0)),
                "mean_abs_slope_per_day": float(g["slope_per_day"].abs().mean()),
                "mean_abs_slope_pct_per_day": float(g["slope_pct_per_day"].abs().mean()),
            }
        )
    order = {"daily": 0, "weekly": 1, "monthly": 2}
    out = pd.DataFrame(rows)
    out["_o"] = out["timeframe"].map(order)
    out["_s"] = out["side"].map({"support": 0, "resistance": 1})
    return out.sort_values(["_o", "_s"]).drop(columns=["_o", "_s"]).reset_index(drop=True)


def channel_patterns(latest: pd.DataFrame) -> list[dict]:
    """Symbols where both support & resistance slope same way on a TF (rising/falling channel)."""
    out = []
    if latest.empty:
        return out
    for (sym, tf), g in latest.groupby(["symbol", "timeframe"]):
        sides = {r["side"]: r for _, r in g.iterrows()}
        if "support" not in sides or "resistance" not in sides:
            continue
        s_dir = sides["support"]["direction"]
        r_dir = sides["resistance"]["direction"]
        if s_dir == "UP" and r_dir == "UP":
            pattern = "rising_channel"
        elif s_dir == "DOWN" and r_dir == "DOWN":
            pattern = "falling_channel"
        elif s_dir == "UP" and r_dir == "DOWN":
            pattern = "converging"
        elif s_dir == "DOWN" and r_dir == "UP":
            pattern = "diverging"
        else:
            continue
        out.append(
            {
                "symbol": sym,
                "timeframe": tf,
                "pattern": pattern,
                "support_slope_pct_per_day": sides["support"]["slope_pct_per_day"],
                "resistance_slope_pct_per_day": sides["resistance"]["slope_pct_per_day"],
                "asof": sides["support"]["date"],
            }
        )
    return out


def steepest(
    latest: pd.DataFrame,
    *,
    timeframe: str,
    side: str,
    direction: str,
    n: int = 5,
) -> pd.DataFrame:
    if latest.empty:
        return pd.DataFrame()
    g = latest[
        (latest["timeframe"] == timeframe)
        & (latest["side"] == side)
        & (latest["direction"] == direction)
    ].copy()
    if g.empty:
        return g
    g["abs_pct"] = g["slope_pct_per_day"].abs()
    return g.nlargest(n, "abs_pct")


def fmt_num(x: float, nd: int = 4) -> str:
    if x is None or not math.isfinite(float(x)):
        return "—"
    return f"{float(x):.{nd}f}"


def df_to_sortable_html(df: pd.DataFrame, col_specs: list[tuple[str, str, str]]) -> str:
    """col_specs: (col_key, header_label, sort_type)."""
    if df is None or df.empty:
        return "<p><em>No rows.</em></p>"
    ths = "".join(sortable_th(lab, st) for _, lab, st in col_specs)
    body_rows = []
    for _, r in df.iterrows():
        cells = []
        for key, _lab, st in col_specs:
            v = r.get(key, "")
            if st == "num" and isinstance(v, (int, float, np.floating)):
                txt = fmt_num(float(v), 6 if abs(float(v)) < 0.01 else 4)
            else:
                txt = "—" if (v is None or (isinstance(v, float) and not math.isfinite(v))) else str(v)
            cls = ""
            if key == "direction":
                cls = f' class="{html_mod.escape(str(v).lower())}"'
            cells.append(f"<td{cls}>{html_mod.escape(txt)}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    return (
        '<table class="sortable"><thead><tr>'
        + ths
        + "</tr></thead><tbody>"
        + "".join(body_rows)
        + "</tbody></table>"
    )


def write_html(
    out_path: Path,
    *,
    stamp: str,
    n_symbols: int,
    n_long: int,
    full_counts: pd.DataFrame,
    snap_counts: pd.DataFrame,
    latest: pd.DataFrame,
    channels: list[dict],
    global_max: str,
) -> None:
    insights: list[str] = []
    if not full_counts.empty:
        for _, r in full_counts.iterrows():
            insights.append(
                f"<li><strong>{html_mod.escape(r['timeframe'])} {html_mod.escape(r['side'])}</strong> "
                f"(full book): UP={int(r['UP']):,} DOWN={int(r['DOWN']):,} FLAT={int(r['FLAT']):,} "
                f"| mean |slope_pct/day|={fmt_num(r['mean_abs_slope_pct_per_day'], 4)}%</li>"
            )
    chan_df = pd.DataFrame(channels) if channels else pd.DataFrame()
    n_rising = int((chan_df["pattern"] == "rising_channel").sum()) if not chan_df.empty else 0
    n_falling = int((chan_df["pattern"] == "falling_channel").sum()) if not chan_df.empty else 0

    steep_sections = []
    for tf in ("weekly", "monthly"):
        for side in ("support", "resistance"):
            up = steepest(latest, timeframe=tf, side=side, direction="UP", n=5)
            dn = steepest(latest, timeframe=tf, side=side, direction="DOWN", n=5)
            specs = [
                ("symbol", "Symbol", "text"),
                ("direction", "Dir", "text"),
                ("slope_pct_per_day", "slope_%/day", "num"),
                ("slope_per_day", "slope_$/day", "num"),
                ("slope_deg", "slope_deg", "num"),
                ("d1", "d1", "date"),
                ("d2", "d2", "date"),
                ("dist_pct", "dist_%", "num"),
                ("date", "asof", "date"),
            ]
            steep_sections.append(
                f"<h3>{html_mod.escape(tf.title())} {html_mod.escape(side)} — steepest UP</h3>"
                + df_to_sortable_html(up, specs)
                + f"<h3>{html_mod.escape(tf.title())} {html_mod.escape(side)} — steepest DOWN</h3>"
                + df_to_sortable_html(dn, specs)
            )

    count_specs = [
        ("timeframe", "TF", "text"),
        ("side", "Side", "text"),
        ("n_rows", "N", "num"),
        ("UP", "UP", "num"),
        ("DOWN", "DOWN", "num"),
        ("FLAT", "FLAT", "num"),
        ("mean_abs_slope_per_day", "mean_|$/day|", "num"),
        ("mean_abs_slope_pct_per_day", "mean_|%/day|", "num"),
    ]
    chan_specs = [
        ("symbol", "Symbol", "text"),
        ("timeframe", "TF", "text"),
        ("pattern", "Pattern", "text"),
        ("support_slope_pct_per_day", "sup_%/day", "num"),
        ("resistance_slope_pct_per_day", "res_%/day", "num"),
        ("asof", "asof", "date"),
    ]
    latest_specs = [
        ("symbol", "Symbol", "text"),
        ("date", "asof", "date"),
        ("timeframe", "TF", "text"),
        ("side", "Side", "text"),
        ("direction", "Dir", "text"),
        ("slope_sign", "sign", "num"),
        ("slope_pct_per_day", "%/day", "num"),
        ("slope_per_day", "$/day", "num"),
        ("slope_deg", "deg", "num"),
        ("d1", "d1", "date"),
        ("p1", "p1", "num"),
        ("d2", "d2", "date"),
        ("p2", "p2", "num"),
        ("line_price_at_asof", "line", "num"),
        ("close", "close", "num"),
        ("dist_pct", "dist_%", "num"),
    ]

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Trendline slopes — PaulTwenty — {html_mod.escape(stamp)}</title>
<style>{SORT_CSS}</style>
</head>
<body>
<h1>PaulTwenty day-by-day trendline slopes</h1>
<p class="meta">Stamp <span class="badge">{html_mod.escape(stamp)}</span> ·
{n_symbols} symbols · {n_long:,} long rows · latest snapshot date
<strong>{html_mod.escape(global_max)}</strong>.
Research only — not gold, not DailyRun. Click column headers to sort.</p>

<div class="insight">
<strong>Plain-English takeaways</strong>
<ul>
{''.join(insights)}
<li>Latest snapshot channel patterns: <strong>{n_rising}</strong> rising (support UP + resistance UP),
<strong>{n_falling}</strong> falling (both DOWN) across daily/weekly/monthly.</li>
</ul>
</div>

<p class="caveat"><strong>Caveats:</strong> Fractal last-two-swing lines with look-ahead-safe confirmation
(pivot at TF index i usable only after bar i+k completes). Not discretionary drawings.
<code>slope_deg = atan(price_change_per_calendar_day)</code> — relative to (price unit, day) axes,
not chart-pixel angles. <code>slope_pct_per_day</code> uses p1 as base:
<code>((p2/p1)-1)/days*100</code>.</p>

<h2>Direction counts — FULL book (all symbol×days)</h2>
{df_to_sortable_html(full_counts, count_specs)}

<h2>Direction counts — latest day snapshot ({html_mod.escape(global_max)})</h2>
{df_to_sortable_html(snap_counts, count_specs)}

<h2>Steepest weekly / monthly (latest per symbol)</h2>
{''.join(steep_sections)}

<h2>Channel / wedge patterns (latest asof per symbol×TF)</h2>
{df_to_sortable_html(chan_df, chan_specs)}

<h2>Latest snapshot — all active lines</h2>
{df_to_sortable_html(latest, latest_specs)}

{SORT_JS}
</body>
</html>
"""
    out_path.write_text(html, encoding="utf-8")


def write_baseline(path: Path, stamp: str) -> None:
    path.write_text(
        f"""# BASELINE — {stamp}

Research-only day-by-day fractal trendline slope tracker for **PaulTwenty**.

## Freeze

| Knob | Value |
|------|-------|
| Universe | `drive/universes/PaulTwenty_universe.csv` |
| OHLC | `data/newdata/data/{{SYM}}.csv` |
| Algorithm | Fractal last-two swings (match `gen_trendlines_tos_studies.py` / `trendline_break_ab.py`) |
| Look-ahead | Confirmed pivots only (`confirmed_on` = end of TF bar i+k) |
| Timeframes | daily (k=5), weekly W-FRI (k=3), monthly ME (k=2) |
| Sides | support = last two Lows; resistance = last two Highs |
| As-of cadence | Each trading day with OHLC where an active line exists |

## Slope definitions

- `slope_per_day` = `(p2 - p1) / (d2 - d1).days` — price units per **calendar** day
- `slope_pct_per_day` = `((p2 / p1) - 1) / days * 100` — percent of **p1** per calendar day
- `slope_deg` = `atan(slope_per_day) * 180/π` — angle on (price unit, day) axes; **not** chart-pixel degrees
- `slope_sign` = +1 / −1 / 0; FLAT when `|slope_per_day| < 1e-12`
- `line_price_at_asof` = linear extension of the two-point line to the as-of date
- `dist_pct` = `(close - line) / line * 100`

## Scope

- Not gold. Not DailyRun-wired.
- Objective fractal geometry only — not discretionary trendlines.
""",
        encoding="utf-8",
    )


def write_summary(
    path: Path,
    *,
    stamp: str,
    n_symbols: int,
    n_long: int,
    full_counts: pd.DataFrame,
    channels: list[dict],
    global_max: str,
) -> None:
    lines = [
        f"# SUMMARY — {stamp}",
        "",
        f"- Universe: PaulTwenty ({n_symbols} symbols with OHLC)",
        f"- Long CSV rows: {n_long:,}",
        f"- Latest calendar as-of in book: {global_max}",
        "",
        "## Full-book UP vs DOWN by TF × side",
        "",
    ]
    if not full_counts.empty:
        lines.append("| TF | Side | UP | DOWN | FLAT | mean_|%/day| |")
        lines.append("|----|------|----|------|------|-------------|")
        for _, r in full_counts.iterrows():
            lines.append(
                f"| {r['timeframe']} | {r['side']} | {int(r['UP'])} | {int(r['DOWN'])} | "
                f"{int(r['FLAT'])} | {r['mean_abs_slope_pct_per_day']:.4f} |"
            )
    n_rising = sum(1 for c in channels if c["pattern"] == "rising_channel")
    n_falling = sum(1 for c in channels if c["pattern"] == "falling_channel")
    lines += [
        "",
        f"## Latest channel patterns: {n_rising} rising, {n_falling} falling",
        "",
        "See HTML for steepest weekly/monthly slopes and sortable tables.",
        "",
        "Research only.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stamp", default=DEFAULT_STAMP)
    ap.add_argument("--universe", type=Path, default=PAULTWENTY)
    args = ap.parse_args()

    out_dir = DRIVE / "paul_experiments" / args.stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    symbols = load_universe(args.universe)
    all_rows: list[dict] = []
    used: list[str] = []
    missing: list[str] = []
    for sym in symbols:
        df = load_ohlc(sym)
        if df is None or len(df) < 50:
            missing.append(sym)
            print(f"SKIP {sym}: no/short OHLC", file=sys.stderr)
            continue
        rows = rows_for_symbol(sym, df)
        all_rows.extend(rows)
        used.append(sym)
        print(f"{sym}: {len(rows):,} rows ({df['Date'].iloc[0]} -> {df['Date'].iloc[-1]})")

    long_df = pd.DataFrame(all_rows)
    if long_df.empty:
        print("No rows produced.", file=sys.stderr)
        return 1

    long_path = out_dir / "trendline_slopes_long.csv"
    long_df.to_csv(long_path, index=False)

    latest = build_summary(long_df)
    latest_path = out_dir / "trendline_slopes_latest.csv"
    latest.to_csv(latest_path, index=False)

    full_counts = direction_counts(long_df, latest_only=False)
    snap_counts = direction_counts(long_df, latest_only=True)
    counts_path = out_dir / "trendline_slopes_direction_counts.csv"
    counts_all = pd.concat(
        [
            full_counts.assign(scope="full_book"),
            snap_counts.assign(scope="latest_day"),
        ],
        ignore_index=True,
    )
    counts_all.to_csv(counts_path, index=False)

    channels = channel_patterns(latest)
    chan_path = out_dir / "trendline_slopes_channel_patterns.csv"
    pd.DataFrame(channels).to_csv(chan_path, index=False)

    global_max = str(long_df["date"].max())
    html_path = out_dir / "trendline_slopes_insights.html"
    write_html(
        html_path,
        stamp=args.stamp,
        n_symbols=len(used),
        n_long=len(long_df),
        full_counts=full_counts,
        snap_counts=snap_counts,
        latest=latest,
        channels=channels,
        global_max=global_max,
    )
    write_baseline(out_dir / "BASELINE.md", args.stamp)
    write_summary(
        out_dir / "SUMMARY.md",
        stamp=args.stamp,
        n_symbols=len(used),
        n_long=len(long_df),
        full_counts=full_counts,
        channels=channels,
        global_max=global_max,
    )

    print(f"\nWrote {out_dir}")
    print(f"  long CSV: {long_path} ({len(long_df):,} rows)")
    print(f"  latest:   {latest_path} ({len(latest):,} rows)")
    print(f"  HTML:     {html_path}")
    if missing:
        print(f"  missing:  {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
