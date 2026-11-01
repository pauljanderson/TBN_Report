#!/usr/bin/env python3
"""EXIT overlay: fractal trendline crossover as early sell once already in a trade.

Replays each system's LatestRun Closed book. Does not re-run entries.
Control = original house exit. Candidates exit early on Close crossover of an
active support (long) / resistance (short) trendline:

  tl_daily   — daily fractal support/resistance only
  tl_weekly  — weekly only
  tl_monthly — monthly only
  tl_any     — earliest of daily / weekly / monthly

Look-ahead: fractal pivots need ±k bars; a pivot is usable only after the
confirming bar's date (same discipline as tools/trendline_break_ab.py).

Usage:
  python tools/trendline_exit_overlay_ab.py
  python tools/trendline_exit_overlay_ab.py --systems RL,RS,VZ
  python tools/trendline_exit_overlay_ab.py --max-trades-per-system 200   # smoke

Research only — not gold, not DailyRun.
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import json
import math
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    ann_ror_from_closed,
    filter_html_compare_columns,
    overlay_ann_ror_max_dd,
)

DRIVE = ROOT / "drive"
DATA_DIR = ROOT / "data" / "newdata" / "data"
STAMP = "trendline_exit_overlay_20260831"
OUT_DIR = DRIVE / "paul_experiments" / STAMP
IS_CUT = date(2024, 1, 1)
SHEET = 45_000.0
INIT_ACCT = DEFAULT_INITIAL_ACCOUNT

PIVOT_K = {"daily": 5, "weekly": 3, "monthly": 2}
WEEK_FREQ = "W-FRI"
MONTH_FREQ = "ME"

ARMS = (
    ("control", "control", ()),
    ("tl_daily", "candidate", ("daily",)),
    ("tl_weekly", "candidate", ("weekly",)),
    ("tl_monthly", "candidate", ("monthly",)),
    ("tl_any", "candidate", ("daily", "weekly", "monthly")),
)

DEFAULT_SYSTEMS = [
    "BRT",
    "RL",
    "RS",
    "VZ",
    "YH",
    "WPBR",
    "MVCP",
    "SB",
    "MTS",
    "IND",
    "QULL",
    "CS",
    "KELL",
    "WRL",
    "PBR",
]

CASH_BY_SYSTEM: dict[str, float] = {
    "VZ": 45_000.0,
    "RS": 47_500.0,
    "RL": 47_500.0,
    "BRT": 47_500.0,
}


@dataclass(frozen=True)
class Pivot:
    kind: str
    date: date
    price: float
    tf_bar_idx: int
    confirmed_on: date


@dataclass(frozen=True)
class ActiveLine:
    timeframe: str
    side: str
    d1: date
    p1: float
    d2: date
    p2: float
    active_from: date


def sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


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
        h.classList.remove("sort-asc", "sort-desc");
        h.setAttribute("aria-sort", "none");
      });
      th.classList.add(dir === "asc" ? "sort-asc" : "sort-desc");
      th.setAttribute("aria-sort", dir === "asc" ? "ascending" : "descending");
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
      bind(table, th, col);
    });
  });
})();
</script>
"""

SORT_CSS = """
th.sortable-th{cursor:pointer;user-select:none;white-space:nowrap}
th.sortable-th .sort-ind::after{content:" \\2195";opacity:.35;font-size:.85em}
th.sortable-th.sort-asc .sort-ind::after{content:" \\25B2";opacity:.85}
th.sortable-th.sort-desc .sort-ind::after{content:" \\25BC";opacity:.85}
tr.control-row{background:#f0f9ff;font-weight:600}
.delta-pos{color:#166534}.delta-neg{color:#991b1b}
body{font-family:Segoe UI,system-ui,sans-serif;margin:24px;color:#111;background:#fafafa}
h1{font-size:1.45rem;margin:0 0 .35rem}h2{font-size:1.15rem;margin:1.6rem 0 .4rem}
h3{font-size:1.02rem;margin:1.1rem 0 .35rem}
.sub,.muted{color:#555;font-size:.92rem}table.sortable{border-collapse:collapse;width:100%;background:#fff;margin:.5rem 0 1.2rem}
th,td{border:1px solid #ddd;padding:6px 8px;font-size:.86rem;text-align:right}
th:first-child,td:first-child,th:nth-child(2),td:nth-child(2),th:nth-child(3),td:nth-child(3){text-align:left}
caption{text-align:left;font-size:.85rem;color:#555;margin-bottom:.35rem}
.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:.8rem;font-weight:600}
.KEEP,.LEAN{background:#dcfce7;color:#166534}.HOLD{background:#fef9c3;color:#854d0e}
.DISMISS{background:#fee2e2;color:#991b1b}
"""


def _f(v: Any, default: float = 0.0) -> float:
    if v is None or v == "":
        return default
    s = str(v).strip().replace("%", "").replace(",", "").replace("$", "")
    if not s:
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _parse_d(s: Any) -> Optional[date]:
    s = str(s or "").strip()
    if not s:
        return None
    compact = s.replace("-", "").replace("/", "")[:8]
    for cand, fmt in ((s[:10], "%Y-%m-%d"), (compact, "%Y%m%d"), (s[:10], "%m/%d/%Y")):
        try:
            return datetime.strptime(cand, fmt).date()
        except ValueError:
            continue
    return None


def _row_get(row: dict, *names: str) -> str:
    for n in names:
        if n in row and row[n] not in (None, ""):
            return str(row[n]).strip()
        for k, v in row.items():
            if str(k).strip() == n and v not in (None, ""):
                return str(v).strip()
    return ""


def load_closed(path: Path, cash: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened = _parse_d(_row_get(raw, "DATE OPENED", "DATE_OPENED"))
            closed = _parse_d(_row_get(raw, "DATE CLOSED", "DATE_CLOSED"))
            entry = _f(_row_get(raw, "ENTRY PRICE", "ENTRY_PRICE"))
            exit_px = _f(_row_get(raw, "EXIT PRICE", "EXIT_PRICE", "AVG EXIT PRICE"))
            pnl = _f(_row_get(raw, "PNL %", "PNL_PCT"))
            # PNL % sometimes stored as fraction (e.g. -0.0977) vs percent (-9.77)
            if abs(pnl) <= 1.5 and abs(pnl) > 0:
                # Heuristic: if |pnl| small and looks like fraction from RL-style files
                sample = _row_get(raw, "PNL %", "PNL_PCT")
                if "%" not in sample and abs(pnl) < 1.0:
                    pnl = pnl * 100.0
            days = _f(_row_get(raw, "DAYS HELD", "DAYS_HELD"))
            pnl_d = _f(_row_get(raw, "PNL_DOLLARS"))
            if pnl_d == 0.0 and pnl != 0.0:
                pnl_d = cash * pnl / 100.0
            xt = _row_get(raw, "EXIT TYPE", "EXIT_TYPE") or "UNKNOWN"
            side_raw = _row_get(raw, "SIDE", "DIRECTION", "LONG_SHORT").upper()
            if side_raw in ("S", "SHORT", "SELL"):
                side = "short"
            else:
                side = "long"
            sym = _row_get(raw, "SYMBOL").upper()
            if not sym or opened is None or closed is None or entry <= 0:
                continue
            if closed < opened:
                continue
            rows.append(
                {
                    "sym": sym,
                    "opened": opened,
                    "closed": closed,
                    "entry": entry,
                    "exit_px": exit_px if exit_px > 0 else entry,
                    "pnl": pnl,
                    "days": days if days > 0 else max((closed - opened).days, 1),
                    "pnl_d": pnl_d,
                    "exit": xt,
                    "side": side,
                }
            )
    return rows


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
    if daily.empty or len(daily) < 2 * k + 1:
        return []
    high = daily["High"].to_numpy(dtype=float)
    low = daily["Low"].to_numpy(dtype=float)
    dates = list(daily["Date"])
    raw = fractal_pivots(high, low, k=k)
    out: list[Pivot] = []
    n = len(daily)
    for kind, i in raw:
        conf_i = i + k
        if conf_i >= n:
            continue
        out.append(
            Pivot(
                kind=kind,
                date=dates[i],
                price=float(high[i] if kind == "H" else low[i]),
                tf_bar_idx=i,
                confirmed_on=dates[conf_i],
            )
        )
    return out


def confirmed_pivots_for_tf(
    daily: pd.DataFrame,
    rule: str,
    timeframe: str,
    k: int,
) -> list[Pivot]:
    htf, members = build_htf(daily, rule)
    if htf.empty or len(htf) < 2 * k + 1:
        return []
    high = htf["High"].to_numpy(dtype=float)
    low = htf["Low"].to_numpy(dtype=float)
    ends = [htf.iloc[i]["end_date"] for i in range(len(htf))]
    raw = fractal_pivots(high, low, k=k)
    pivots: list[Pivot] = []
    n = len(htf)
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


def line_price_at(d1: date, p1: float, d2: date, p2: float, t: date) -> float:
    days_total = (d2 - d1).days
    if days_total == 0:
        return float(p2)
    slope = (p2 - p1) / float(days_total)
    return float(p1 + slope * (t - d1).days)


def last_two_confirmed(pivots: list[Pivot], kind: str, as_of: date) -> Optional[tuple[Pivot, Pivot]]:
    same = [p for p in pivots if p.kind == kind and p.confirmed_on <= as_of]
    if len(same) < 2:
        return None
    a, b = same[-2], same[-1]
    if a.date >= b.date:
        return None
    return a, b


def active_support_or_resistance(
    pivots: list[Pivot],
    timeframe: str,
    side: str,
    as_of: date,
) -> Optional[ActiveLine]:
    kind = "L" if side == "support" else "H"
    pair = last_two_confirmed(pivots, kind, as_of)
    if not pair:
        return None
    a, b = pair
    active_from = max(a.confirmed_on, b.confirmed_on)
    if active_from > as_of:
        return None
    return ActiveLine(
        timeframe=timeframe,
        side=side,
        d1=a.date,
        p1=a.price,
        d2=b.date,
        p2=b.price,
        active_from=active_from,
    )


def build_pivot_pack(daily: pd.DataFrame) -> dict[str, list[Pivot]]:
    return {
        "daily": confirmed_pivots_daily(daily, PIVOT_K["daily"]),
        "weekly": confirmed_pivots_for_tf(daily, WEEK_FREQ, "weekly", PIVOT_K["weekly"]),
        "monthly": confirmed_pivots_for_tf(daily, MONTH_FREQ, "monthly", PIVOT_K["monthly"]),
    }


def crossed_below(prev_c: float, c: float, line_px: float) -> bool:
    return prev_c >= line_px and c < line_px


def crossed_above(prev_c: float, c: float, line_px: float) -> bool:
    return prev_c <= line_px and c > line_px


def replay_tl_exit(
    trade: dict[str, Any],
    ohlc: pd.DataFrame,
    pivots: dict[str, list[Pivot]],
    tfs: tuple[str, ...],
) -> dict[str, Any]:
    """If Close crosses the active TF line before house exit, exit that day."""
    if not tfs:
        return {**trade, "tl_hit": False, "missing_bars": False, "tl_tf": ""}

    opened = trade["opened"]
    closed = trade["closed"]
    entry = float(trade["entry"])
    side = trade["side"]
    line_side = "support" if side == "long" else "resistance"

    sub = ohlc[(ohlc["Date"] >= opened) & (ohlc["Date"] <= closed)].reset_index(drop=True)
    if len(sub) < 2:
        return {**trade, "tl_hit": False, "missing_bars": True, "tl_tf": ""}

    # Start checking the day AFTER entry fill
    for i in range(1, len(sub)):
        d = sub.loc[i, "Date"]
        prev_c = float(sub.loc[i - 1, "Close"])
        o = float(sub.loc[i, "Open"])
        c = float(sub.loc[i, "Close"])
        hit_tfs: list[str] = []
        hit_px: Optional[float] = None
        for tf in tfs:
            ln = active_support_or_resistance(pivots[tf], tf, line_side, d)
            if ln is None:
                continue
            line_px = line_price_at(ln.d1, ln.p1, ln.d2, ln.p2, d)
            if not math.isfinite(line_px) or line_px <= 0:
                continue
            # Gap through: open already beyond line → fill at open
            if side == "long":
                if o < line_px or crossed_below(prev_c, c, line_px):
                    hit_tfs.append(tf)
                    fill = o if o < line_px else c
                    if hit_px is None:
                        hit_px = fill
            else:
                if o > line_px or crossed_above(prev_c, c, line_px):
                    hit_tfs.append(tf)
                    fill = o if o > line_px else c
                    if hit_px is None:
                        hit_px = fill
        if not hit_tfs or hit_px is None:
            continue
        # Prefer the first TF in arm order that hit (daily before weekly before monthly for tl_any)
        tf_used = hit_tfs[0]
        if side == "long":
            pnl = (hit_px - entry) / entry * 100.0
        else:
            pnl = (entry - hit_px) / entry * 100.0
        days = max((d - opened).days, 1)
        if abs(trade["pnl"]) > 1e-9:
            notional = trade["pnl_d"] / (trade["pnl"] / 100.0)
            pnl_d = notional * pnl / 100.0
        else:
            pnl_d = 0.0
        return {
            **trade,
            "pnl": pnl,
            "pnl_d": pnl_d,
            "days": float(days),
            "exit": f"TL_{tf_used.upper()}",
            "exit_px": hit_px,
            "tl_hit": True,
            "missing_bars": False,
            "tl_tf": tf_used,
            "closed": d,
        }

    return {**trade, "tl_hit": False, "missing_bars": False, "tl_tf": ""}


def book_stats(trades: list[dict[str, Any]], cash: float) -> dict[str, Any]:
    n = len(trades)
    empty = {
        "n": 0,
        "wins": 0,
        "losses": 0,
        "wr": 0.0,
        "avg_pnl": 0.0,
        "avg_win": 0.0,
        "avg_loss": 0.0,
        "pf": 0.0,
        "sheet": 0.0,
        "pnl_d": 0.0,
        "avg_days": 0.0,
        "ann_ror": 0.0,
        "max_dd": 0.0,
        "wo_max": 0.0,
        "exits": {},
        "tl_n": 0,
        "tl_rate": 0.0,
    }
    if n == 0:
        return empty
    pnls = [float(t["pnl"]) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gp = sum(wins)
    gl = abs(sum(losses))
    avg = sum(pnls) / n
    wo = (sum(pnls) - max(pnls)) / (n - 1) if n >= 2 else avg
    avg_days = sum(float(t["days"]) for t in trades) / n
    pnl_d = sum(float(t["pnl_d"]) for t in trades)
    sheet = sum(p / 100.0 * SHEET for p in pnls)
    ann = ann_ror_from_closed(total_pnl=pnl_d, n_trades=n, avg_days_held=avg_days, brt_cash=cash) or 0.0
    ov = overlay_ann_ror_max_dd(trades, cash=cash, initial_account=INIT_ACCT) or {}
    tl_n = sum(1 for t in trades if t.get("tl_hit"))
    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "wr": 100.0 * len(wins) / n,
        "avg_pnl": avg,
        "avg_win": (sum(wins) / len(wins)) if wins else 0.0,
        "avg_loss": (sum(losses) / len(losses)) if losses else 0.0,
        "pf": (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0),
        "sheet": sheet,
        "pnl_d": pnl_d,
        "avg_days": avg_days,
        "ann_ror": float(ov.get("ann_ror", ann) or ann),
        "max_dd": float(ov.get("max_dd", 0.0) or 0.0),
        "wo_max": wo,
        "exits": dict(Counter(str(t["exit"]) for t in trades)),
        "tl_n": tl_n,
        "tl_rate": 100.0 * tl_n / n,
    }


def split_is_oos(trades: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return [t for t in trades if t["opened"] < IS_CUT], [t for t in trades if t["opened"] >= IS_CUT]


def verdict(ctrl: dict, cand: dict, oos_c: dict, oos_a: dict) -> tuple[str, str]:
    d_avg = cand["avg_pnl"] - ctrl["avg_pnl"]
    d_wr = cand["wr"] - ctrl["wr"]
    d_pf = cand["pf"] - ctrl["pf"]
    d_wo = cand["wo_max"] - ctrl["wo_max"]
    d_ann = cand["ann_ror"] - ctrl["ann_ror"]
    is_better = (d_avg > 0.05 and d_wo > -0.05) or (d_ann > 0.5 and d_avg > -0.05)
    is_worse = d_avg < -0.05 and d_wo < 0 and d_pf <= 0
    oos_soft = False
    oos_note = "OOS n/a"
    if oos_c["n"] >= 20 and oos_a["n"] >= 20:
        oos_soft = (oos_a["avg_pnl"] < oos_c["avg_pnl"] - 0.15) or (oos_a["ann_ror"] < oos_c["ann_ror"] - 1.0)
        oos_note = (
            f"OOS ΔAvg {oos_a['avg_pnl']-oos_c['avg_pnl']:+.2f}pp, "
            f"ΔAnnROR {oos_a['ann_ror']-oos_c['ann_ror']:+.2f}"
        )
        if oos_soft:
            oos_note += " — softened"
    if is_worse:
        return "DISMISS", oos_note
    if is_better and oos_soft:
        return "HOLD", oos_note + " (IS up, do not retune OOS)"
    if is_better and not oos_soft:
        return "LEAN KEEP", oos_note + " — research-only, not DailyRun"
    return "HOLD", oos_note + " (flat/mixed quality)"


def fmt_n(v: float, d: int = 2) -> str:
    if v is None or not math.isfinite(float(v)):
        return "—"
    return f"{float(v):.{d}f}"


def fmt_delta(v: float, d: int = 2) -> str:
    if v is None or not math.isfinite(float(v)):
        return "—"
    x = float(v)
    cls = "delta-pos" if x > 0 else ("delta-neg" if x < 0 else "")
    sign = "+" if x > 0 else ""
    return f'<span class="{cls}">{sign}{x:.{d}f}</span>'


def _worker_symbol(payload: tuple[str, list[dict], tuple]) -> tuple[str, dict[str, list[dict]]]:
    """Process one symbol: return arm -> list of replayed trades for that symbol."""
    sym, trades, arm_tfs = payload
    daily = load_ohlc(sym)
    out: dict[str, list[dict]] = {name: [] for name, _, _ in ARMS}
    if daily is None or daily.empty:
        for t in trades:
            for name, _, _ in ARMS:
                out[name].append({**t, "tl_hit": False, "missing_bars": True, "tl_tf": ""})
        return sym, out
    pivots = build_pivot_pack(daily)
    for t in trades:
        out["control"].append({**t, "tl_hit": False, "missing_bars": False, "tl_tf": ""})
        for name, role, tfs in ARMS:
            if name == "control":
                continue
            out[name].append(replay_tl_exit(t, daily, pivots, tfs))
    return sym, out


def run_system(
    sys_name: str,
    trades: list[dict[str, Any]],
    cash: float,
    workers: int,
) -> dict[str, Any]:
    by_sym: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        by_sym[t["sym"]].append(t)

    arm_books: dict[str, list[dict]] = {name: [] for name, _, _ in ARMS}
    payloads = [(sym, rows, ()) for sym, rows in by_sym.items()]

    if workers <= 1:
        for p in payloads:
            _sym, books = _worker_symbol(p)
            for arm, rows in books.items():
                arm_books[arm].extend(rows)
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(_worker_symbol, p) for p in payloads]
            for fut in as_completed(futs):
                _sym, books = fut.result()
                for arm, rows in books.items():
                    arm_books[arm].extend(rows)

    results: dict[str, Any] = {"system": sys_name, "cash": cash, "arms": {}}
    ctrl_full = book_stats(arm_books["control"], cash)
    ctrl_is, ctrl_oos = split_is_oos(arm_books["control"])
    ctrl_is_s = book_stats(ctrl_is, cash)
    ctrl_oos_s = book_stats(ctrl_oos, cash)

    for name, role, tfs in ARMS:
        book = arm_books[name]
        full = book_stats(book, cash)
        is_t, oos_t = split_is_oos(book)
        is_s = book_stats(is_t, cash)
        oos_s = book_stats(oos_t, cash)
        if name == "control":
            v, note = "CONTROL", "house Closed exits"
        else:
            v, note = verdict(ctrl_is_s, is_s, ctrl_oos_s, oos_s)
        results["arms"][name] = {
            "role": role,
            "tfs": list(tfs),
            "full": full,
            "is": is_s,
            "oos": oos_s,
            "verdict": v,
            "note": note,
            "delta_full": {
                "avg_pnl": full["avg_pnl"] - ctrl_full["avg_pnl"],
                "wr": full["wr"] - ctrl_full["wr"],
                "pf": full["pf"] - ctrl_full["pf"],
                "wo_max": full["wo_max"] - ctrl_full["wo_max"],
                "ann_ror": full["ann_ror"] - ctrl_full["ann_ror"],
                "avg_days": full["avg_days"] - ctrl_full["avg_days"],
                "tl_rate": full["tl_rate"],
            },
        }
    return results


def write_baseline(path: Path) -> None:
    text = f"""# BASELINE — `{STAMP}`

## Hypothesis (EXIT overlay)

Once already in a house-system trade, does a **fractal trendline Close crossover**
improve exit quality vs the system's original stop/target/time exits?

## Freeze

| Knob | Value |
|------|-------|
| Entries | frozen from each `*_LatestRun_Closed.csv` (no re-entry) |
| Control | original Closed exit (date / price / PnL) |
| Signal | daily Close crosses beyond active trendline (`close_cross`) |
| Long stop line | active **support** (last two confirmed swing lows) |
| Short stop line | active **resistance** (last two confirmed swing highs) |
| Fill | gap beyond line → Open; else Close of crossover day |
| Check window | day after entry through original exit date |
| Pivot confirm | ±k bars; usable only after confirm date (no look-ahead) |
| k daily / weekly / monthly | {PIVOT_K['daily']} / {PIVOT_K['weekly']} / {PIVOT_K['monthly']} |
| IS / OOS | entry &lt; / ≥ 2024-01-01 (OOS report-only) |

## Arms (one TF family each)

| Arm | TFs |
|-----|-----|
| control | — |
| tl_daily | daily |
| tl_weekly | weekly |
| tl_monthly | monthly |
| tl_any | earliest of daily, weekly, monthly |

## Label honesty

Selecting among D/W/M/any after seeing the table is **in-sample selection**.
Report all arms; do not retune on OOS. Research-only — not gold / not DailyRun.
"""
    path.write_text(text, encoding="utf-8")


def write_html(path: Path, all_results: list[dict[str, Any]]) -> None:
    cols = filter_html_compare_columns(
        [
            ("System", "text"),
            ("Arm", "text"),
            ("Split", "text"),
            ("N", "num"),
            ("WR %", "num"),
            ("Avg PnL %", "num"),
            ("WO_MAX %", "num"),
            ("PF", "num"),
            ("Ann ROR %", "num"),
            ("Avg days", "num"),
            ("TL hit %", "num"),
            ("Δ Avg vs ctrl", "num"),
            ("Δ WR vs ctrl", "num"),
            ("Δ PF vs ctrl", "num"),
            ("Δ AnnROR vs ctrl", "num"),
            ("Δ days vs ctrl", "num"),
            ("Verdict", "text"),
        ]
    )
    head = "".join(sortable_th(lab, typ) for lab, typ in cols)

    def row_cells(sys_name: str, arm: str, split: str, m: dict, d: dict, verdict: str, is_ctrl: bool) -> str:
        cls = ' class="control-row"' if is_ctrl else ""
        badge = f'<span class="badge {verdict.split()[0]}">{html_mod.escape(verdict)}</span>'
        vals = [
            html_mod.escape(sys_name),
            html_mod.escape(arm),
            html_mod.escape(split),
            str(m["n"]),
            fmt_n(m["wr"]),
            fmt_n(m["avg_pnl"]),
            fmt_n(m["wo_max"]),
            fmt_n(m["pf"]),
            fmt_n(m["ann_ror"]),
            fmt_n(m["avg_days"], 1),
            fmt_n(m["tl_rate"], 1) if not is_ctrl else "—",
            "—" if is_ctrl else fmt_delta(d["avg_pnl"]),
            "—" if is_ctrl else fmt_delta(d["wr"]),
            "—" if is_ctrl else fmt_delta(d["pf"]),
            "—" if is_ctrl else fmt_delta(d["ann_ror"]),
            "—" if is_ctrl else fmt_delta(d["avg_days"], 1),
            badge if split == "IS" or (split == "FULL" and not is_ctrl) else ("—" if is_ctrl else badge),
        ]
        # For control FULL show CONTROL badge on FULL only
        if is_ctrl and split == "FULL":
            vals[-1] = '<span class="badge HOLD">CONTROL</span>'
        elif is_ctrl:
            vals[-1] = "—"
        return f"<tr{cls}>" + "".join(f"<td>{v}</td>" for v in vals) + "</tr>"

    body: list[str] = []
    for res in all_results:
        sys_name = res["system"]
        ctrl = res["arms"]["control"]
        for arm_name, _, _ in ARMS:
            arm = res["arms"][arm_name]
            is_ctrl = arm_name == "control"
            for split_key, label in (("full", "FULL"), ("is", "IS"), ("oos", "OOS")):
                m = arm[split_key]
                # deltas vs control same split
                c = ctrl[split_key]
                d = {
                    "avg_pnl": m["avg_pnl"] - c["avg_pnl"],
                    "wr": m["wr"] - c["wr"],
                    "pf": m["pf"] - c["pf"],
                    "ann_ror": m["ann_ror"] - c["ann_ror"],
                    "avg_days": m["avg_days"] - c["avg_days"],
                }
                body.append(row_cells(sys_name, arm_name, label, m, d, arm["verdict"], is_ctrl))

    # Per-system summary cards
    cards: list[str] = []
    for res in all_results:
        sys_name = res["system"]
        lines = [f"<h3>{html_mod.escape(sys_name)}</h3><ul>"]
        ctrl_is = res["arms"]["control"]["is"]
        for arm_name, _, tfs in ARMS:
            if arm_name == "control":
                continue
            a = res["arms"][arm_name]
            d = a["delta_full"]
            lines.append(
                "<li><strong>{}</strong> ({}) FULL ΔAvg {:+.2f}pp, ΔAnnROR {:+.2f}, "
                "TL hit {:.0f}% — IS verdict <span class=\"badge {}\">{}</span> — {}</li>".format(
                    arm_name,
                    ",".join(tfs) or "—",
                    d["avg_pnl"],
                    d["ann_ror"],
                    d["tl_rate"],
                    a["verdict"].split()[0],
                    html_mod.escape(a["verdict"]),
                    html_mod.escape(a["note"]),
                )
            )
        lines.append(
            f"<li class=\"muted\">Control IS: N={ctrl_is['n']}, Avg={ctrl_is['avg_pnl']:.2f}%, "
            f"AnnROR={ctrl_is['ann_ror']:.2f}%</li></ul>"
        )
        cards.append("\n".join(lines))

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>Trendline exit overlay — {STAMP}</title>
<style>{SORT_CSS}</style></head>
<body>
<main>
<h1>Trendline crossover as EXIT overlay — all systems</h1>
<p class="sub">Control = original house Closed exit. Candidates exit early when daily Close
crosses the active fractal <strong>support</strong> (longs) / <strong>resistance</strong> (shorts)
trendline. Arms: daily only, weekly only, monthly only, or <em>any</em> (earliest).
IS = entry &lt; 2024-01-01; OOS report-only. Click column headers to sort.
Research-only — not gold / not DailyRun.</p>

<h2>Master compare (vs control)</h2>
<table class="sortable"><caption>Click headers to sort. Control rows highlighted.</caption>
<thead><tr>{head}</tr></thead>
<tbody>
{''.join(body)}
</tbody></table>

<h2>Per-system readout</h2>
{''.join(cards)}

<h2>Notes</h2>
<ul>
<li>Same look-ahead-safe fractal pivots as <code>trendline_break_ab.py</code> / holdings ToS studies.</li>
<li>Overlay keeps entry set fixed; early TL exits change PnL/days only when the line is hit before the house exit.</li>
<li>Selecting the best TF after seeing the table is in-sample selection — freeze before promotion claims.</li>
</ul>
</main>
{SORT_JS}
</body></html>
"""
    path.write_text(html, encoding="utf-8")


def write_summary(path: Path, all_results: list[dict[str, Any]]) -> None:
    lines = [
        f"# SUMMARY — `{STAMP}`",
        "",
        "EXIT overlay: fractal trendline Close crossover vs house Closed exits.",
        "IS/OOS cut = 2024-01-01. Verdicts on IS quality; OOS report-only.",
        "",
        "| System | Arm | FULL ΔAvg | FULL ΔAnnROR | TL hit% | IS verdict | Note |",
        "|--------|-----|-----------|--------------|---------|------------|------|",
    ]
    for res in all_results:
        for arm_name, _, _ in ARMS:
            if arm_name == "control":
                continue
            a = res["arms"][arm_name]
            d = a["delta_full"]
            lines.append(
                f"| {res['system']} | {arm_name} | {d['avg_pnl']:+.2f} | {d['ann_ror']:+.2f} | "
                f"{d['tl_rate']:.0f} | {a['verdict']} | {a['note']} |"
            )
    lines.extend(
        [
            "",
            "## How to read",
            "- **Positive ΔAvg / ΔAnnROR** = early TL stop helped vs sitting to house exit.",
            "- **High TL hit%** with worse Avg = stop chopped winners (common).",
            "- **tl_any** fires on the earliest of D/W/M — usually most aggressive.",
            "",
            "Research-only. Do not wire DailyRun from this stamp.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--systems", default=",".join(DEFAULT_SYSTEMS))
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--max-trades-per-system", type=int, default=0)
    ap.add_argument("--stamp-dir", type=Path, default=None)
    args = ap.parse_args(argv)

    out_dir = Path(args.stamp_dir) if args.stamp_dir else OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    systems = [s.strip().upper() for s in args.systems.split(",") if s.strip()]
    all_results: list[dict[str, Any]] = []

    for sys_name in systems:
        path = DRIVE / f"{sys_name}_LatestRun_Closed.csv"
        if not path.is_file():
            print(f"[skip] missing {path.name}", flush=True)
            continue
        cash = CASH_BY_SYSTEM.get(sys_name, 47_500.0)
        trades = load_closed(path, cash)
        if args.max_trades_per_system > 0:
            trades = trades[: args.max_trades_per_system]
        if not trades:
            print(f"[skip] empty {sys_name}", flush=True)
            continue
        print(f"[run] {sys_name}: {len(trades)} trades, cash={cash:.0f}", flush=True)
        res = run_system(sys_name, trades, cash, workers=max(1, args.workers))
        all_results.append(res)
        for arm_name, _, _ in ARMS:
            if arm_name == "control":
                continue
            a = res["arms"][arm_name]
            d = a["delta_full"]
            print(
                f"  {arm_name:12s} dAvg={d['avg_pnl']:+.2f} dAnn={d['ann_ror']:+.2f} "
                f"TLhit={d['tl_rate']:.0f}% -> {a['verdict']}",
                flush=True,
            )

    write_baseline(out_dir / "BASELINE.md")
    write_summary(out_dir / "SUMMARY.md", all_results)
    html_path = out_dir / "compare.html"
    write_html(html_path, all_results)
    (out_dir / "results.json").write_text(json.dumps(all_results, indent=2, default=str), encoding="utf-8")

    # Flat CSV
    flat_rows: list[dict[str, Any]] = []
    for res in all_results:
        for arm_name, role, tfs in ARMS:
            a = res["arms"][arm_name]
            for split in ("full", "is", "oos"):
                m = a[split]
                c = res["arms"]["control"][split]
                flat_rows.append(
                    {
                        "system": res["system"],
                        "arm": arm_name,
                        "role": role,
                        "tfs": "|".join(tfs),
                        "split": split.upper(),
                        "n": m["n"],
                        "wr": m["wr"],
                        "avg_pnl": m["avg_pnl"],
                        "wo_max": m["wo_max"],
                        "pf": m["pf"],
                        "ann_ror": m["ann_ror"],
                        "avg_days": m["avg_days"],
                        "tl_rate": m["tl_rate"],
                        "d_avg": m["avg_pnl"] - c["avg_pnl"],
                        "d_wr": m["wr"] - c["wr"],
                        "d_pf": m["pf"] - c["pf"],
                        "d_ann": m["ann_ror"] - c["ann_ror"],
                        "d_days": m["avg_days"] - c["avg_days"],
                        "verdict": a["verdict"],
                        "note": a["note"],
                    }
                )
    with (out_dir / "metrics.csv").open("w", newline="", encoding="utf-8") as f:
        if flat_rows:
            w = csv.DictWriter(f, fieldnames=list(flat_rows[0].keys()))
            w.writeheader()
            w.writerows(flat_rows)

    print(f"[ok] {html_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
