#!/usr/bin/env python3
"""Trendline break research system — weekly/monthly fractal lines on daily chart.

Break of a confirmed weekly or monthly support/resistance trendline → trade in
break direction. Stop = opposite-direction active trendline, **trailing daily**
as that line extends (and as last-two pivots roll within the same TF+side family).

Look-ahead: fractal pivots need ±k HTF bars; a pivot at HTF index i becomes
active only after HTF bar i+k has completed (confirmation date = that bar's
last trading day). Lines use only pivots confirmed as-of date t.

Usage:
  python tools/trendline_break_ab.py
  python tools/trendline_break_ab.py --universe drive/universes/PaulTwenty_universe.csv
  python tools/trendline_break_ab.py --symbol-summary
  python tools/trendline_break_ab.py --symbol-summary --universe drive/universes/VZ_tradable_2010_adv2m_universe.csv

Research only — not gold, not DailyRun.
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
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
    filter_html_compare_columns,
    format_money,
    overlay_ann_ror_max_dd,
)

DRIVE = ROOT / "drive"
DATA_DIR = ROOT / "data" / "newdata" / "data"
STAMP = "trendline_break_longs_trail_paul20_20260827"
OUT_DIR = DRIVE / "paul_experiments" / STAMP
PRIOR_STAMP = "trendline_break_paul20_20260827"
SYMBOL_SUMMARY_STAMP = "trendline_break_symbol_summary_20260827"
SYMBOL_SUMMARY_OUT = DRIVE / "paul_experiments" / SYMBOL_SUMMARY_STAMP
PAULTWENTY = DRIVE / "universes" / "PaulTwenty_universe.csv"
TRADABLE_UNIV = DRIVE / "universes" / "VZ_tradable_2010_adv2m_universe.csv"
IS_CUT = date(2024, 1, 1)
MIN_N_RANK = 5
MIN_N_RANK_ALT = 10

# --- Fractal knobs (match tools/gen_trendlines_tos_studies.py) ---
PIVOT_K = {"weekly": 3, "monthly": 2}
WEEK_FREQ = "W-FRI"
MONTH_FREQ = "ME"

# --- Trade freeze ---
BREAK_DEF = "close_cross"  # daily Close crosses beyond line (prior close on/inside)
ENTRY = "next_open"
TARGET_R = 1.0  # risk multiple; initial stop distance = risk (1R target fixed)
TIME_STOP_BARS = 40
MIN_PRICE = 5.0
MIN_ADV20 = 500_000.0
SHEET = 45_000.0
INIT_ACCT = DEFAULT_INITIAL_ACCOUNT
COSTS_BPS = 0.0
# Warm-up: need enough HTF bars for 2 pivots + confirmation
MIN_DAILY_BARS = 400
# Engine truth: stop trails opposite active trendline daily (YES after fix)
TRAILING_STOP = True

# Side/TF AB under trailing-stop engine (control = either_wm long+short)
# Arms: (name, role, tfs, side_mode) side_mode in {"both","long","short"}
ARMS = (
    ("either_wm", "control", ("weekly", "monthly"), "both"),
    ("longs_only", "candidate", ("weekly", "monthly"), "long"),
    ("weekly_longs_only", "candidate", ("weekly",), "long"),
    ("monthly_longs_only", "candidate", ("monthly",), "long"),
)


@dataclass(frozen=True)
class Pivot:
    kind: str  # H | L
    date: date
    price: float
    tf_bar_idx: int
    confirmed_on: date  # first date the pivot is known (end of bar i+k)


@dataclass(frozen=True)
class ActiveLine:
    timeframe: str
    side: str  # support | resistance
    d1: date
    p1: float
    d2: date
    p2: float
    active_from: date  # max(confirm of both pivots)


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
th.sortable-th { cursor: pointer; user-select: none; white-space: nowrap; }
th.sortable-th:hover { background: #e2e8f0; }
th.sortable-th .sort-ind::after { content: " \\2195"; opacity: .35; font-size: .85em; }
th.sortable-th.sort-asc .sort-ind::after { content: " \\2191"; opacity: .9; }
th.sortable-th.sort-desc .sort-ind::after { content: " \\2193"; opacity: .9; }
"""


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
    need = ("date", "open", "high", "low", "close", "volume")
    if not all(k in cols for k in need):
        return None
    out = pd.DataFrame(
        {
            "Date": pd.to_datetime(df[cols["date"]]).dt.date,
            "Open": df[cols["open"]].astype(float),
            "High": df[cols["high"]].astype(float),
            "Low": df[cols["low"]].astype(float),
            "Close": df[cols["close"]].astype(float),
            "Volume": df[cols["volume"]].astype(float),
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
    htf = pd.DataFrame(rows)
    return htf, members


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
    # Map member timestamps to daily rows via date
    member_dates = {pd.Timestamp(ts).date() for ts in gidx}
    sub = daily[daily["Date"].isin(member_dates)]
    if sub.empty:
        return pd.Timestamp(gidx[-1]).date(), float(high if kind == "H" else low)
    if kind == "H":
        j = sub["High"].idxmax()
        return sub.loc[j, "Date"], float(sub.loc[j, "High"])
    j = sub["Low"].idxmin()
    return sub.loc[j, "Date"], float(sub.loc[j, "Low"])


def confirmed_pivots_for_tf(
    daily: pd.DataFrame,
    rule: str,
    timeframe: str,
    k: int,
) -> list[Pivot]:
    """All HTF fractal pivots with confirmation dates (no look-ahead metadata)."""
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
            continue  # not yet confirmable even on full history
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


def active_line_from_pair(
    timeframe: str,
    side: str,
    a: Pivot,
    b: Pivot,
) -> ActiveLine:
    return ActiveLine(
        timeframe=timeframe,
        side=side,
        d1=a.date,
        p1=a.price,
        d2=b.date,
        p2=b.price,
        active_from=max(a.confirmed_on, b.confirmed_on),
    )


def lines_as_of(
    piv_w: list[Pivot],
    piv_m: list[Pivot],
    as_of: date,
    tfs: tuple[str, ...],
) -> list[ActiveLine]:
    """Build last-two-swing W/M support & resistance known as of as_of."""
    segs: list[ActiveLine] = []
    specs = []
    if "weekly" in tfs:
        specs.append(("weekly", piv_w))
    if "monthly" in tfs:
        specs.append(("monthly", piv_m))
    for tf, pivs in specs:
        for kind, side in (("L", "support"), ("H", "resistance")):
            pair = last_two_confirmed(pivs, kind, as_of)
            if not pair:
                continue
            a, b = pair
            line = active_line_from_pair(tf, side, a, b)
            if line.active_from <= as_of:
                segs.append(line)
    return segs


def crossed_above(prev_c: float, c: float, line_px: float) -> bool:
    return prev_c <= line_px and c > line_px


def crossed_below(prev_c: float, c: float, line_px: float) -> bool:
    return prev_c >= line_px and c < line_px


def pick_stop(
    lines: list[ActiveLine],
    side_needed: str,
    entry: float,
    as_of: date,
) -> Optional[tuple[float, ActiveLine]]:
    """Nearest opposite line on the correct side of entry. Skip if missing."""
    cands: list[tuple[float, float, ActiveLine]] = []  # (distance, stop_px, line)
    for ln in lines:
        if ln.side != side_needed or ln.active_from > as_of:
            continue
        px = line_price_at(ln.d1, ln.p1, ln.d2, ln.p2, as_of)
        if not math.isfinite(px) or px <= 0:
            continue
        if side_needed == "support":
            # long stop must be below entry
            if px >= entry:
                continue
            cands.append((entry - px, px, ln))
        else:
            # short stop must be above entry
            if px <= entry:
                continue
            cands.append((px - entry, px, ln))
    if not cands:
        return None
    cands.sort(key=lambda x: x[0])
    return cands[0][1], cands[0][2]


def resolve_trailing_stop(
    piv_w: list[Pivot],
    piv_m: list[Pivot],
    as_of: date,
    tfs: tuple[str, ...],
    stop_side: str,
    preferred_tf: str,
    ref_px: float,
) -> Optional[tuple[float, ActiveLine]]:
    """Daily stop from active opposite S/R; prefer entry TF+side family.

    Same geometric family = same timeframe + side (support for longs /
    resistance for shorts). When last-two pivots roll, the active line for
    that family updates; price = linear extension to ``as_of``.

    If the preferred family is missing, fall back to nearest opposite among
    arm TFs relative to ``ref_px`` (entry), same as entry pick rules.
    """
    lines = lines_as_of(piv_w, piv_m, as_of, tfs)
    for ln in lines:
        if ln.side != stop_side or ln.timeframe != preferred_tf:
            continue
        px = line_price_at(ln.d1, ln.p1, ln.d2, ln.p2, as_of)
        if math.isfinite(px) and px > 0:
            return px, ln
    return pick_stop(lines, stop_side, ref_px, as_of)


def simulate_symbol(
    df: pd.DataFrame,
    sym: str,
    arm: str,
    tfs: tuple[str, ...],
    side_mode: str = "both",
    trailing: bool = TRAILING_STOP,
    piv_w: Optional[list[Pivot]] = None,
    piv_m: Optional[list[Pivot]] = None,
) -> list[dict[str, Any]]:
    if len(df) < MIN_DAILY_BARS:
        return []
    if piv_w is None:
        piv_w = confirmed_pivots_for_tf(df, WEEK_FREQ, "weekly", PIVOT_K["weekly"])
    if piv_m is None:
        piv_m = confirmed_pivots_for_tf(df, MONTH_FREQ, "monthly", PIVOT_K["monthly"])
    vol = df["Volume"].astype(float)
    adv20 = vol.rolling(20, min_periods=20).mean().to_numpy()

    trades: list[dict[str, Any]] = []
    n = len(df)
    i = max(MIN_DAILY_BARS, 21)
    while i < n - 2:
        row = df.iloc[i]
        prev = df.iloc[i - 1]
        d = row["Date"]
        c = float(row["Close"])
        prev_c = float(prev["Close"])
        if c < MIN_PRICE:
            i += 1
            continue
        adv = float(adv20[i]) if math.isfinite(float(adv20[i])) else 0.0
        if adv < MIN_ADV20:
            i += 1
            continue

        lines = lines_as_of(piv_w, piv_m, d, tfs)
        long_hits: list[tuple[float, ActiveLine]] = []  # (break magnitude, line)
        short_hits: list[tuple[float, ActiveLine]] = []
        for ln in lines:
            lp = line_price_at(ln.d1, ln.p1, ln.d2, ln.p2, d)
            if not math.isfinite(lp) or lp <= 0:
                continue
            if ln.side == "resistance" and crossed_above(prev_c, c, lp):
                long_hits.append((c - lp, ln))
            elif ln.side == "support" and crossed_below(prev_c, c, lp):
                short_hits.append((lp - c, ln))

        # Side filter: longs-only ignores short conflicts (takes long if present)
        if side_mode == "long":
            if not long_hits:
                i += 1
                continue
            direction = "long"
            long_hits.sort(key=lambda x: -x[0])
            sig_line = long_hits[0][1]
        elif side_mode == "short":
            if not short_hits:
                i += 1
                continue
            direction = "short"
            short_hits.sort(key=lambda x: -x[0])
            sig_line = short_hits[0][1]
        else:
            # both: same-day both dirs → skip (conflict)
            if long_hits and short_hits:
                i += 1
                continue
            if not long_hits and not short_hits:
                i += 1
                continue
            if long_hits:
                direction = "long"
                long_hits.sort(key=lambda x: -x[0])
                sig_line = long_hits[0][1]
            else:
                direction = "short"
                short_hits.sort(key=lambda x: -x[0])
                sig_line = short_hits[0][1]

        entry_i = i + 1
        if entry_i >= n:
            break
        entry = float(df.iloc[entry_i]["Open"])
        if entry <= 0:
            i += 1
            continue

        stop_side = "support" if direction == "long" else "resistance"
        # Initial stop: nearest opposite among arm TFs at signal date / entry px
        stop_pick = pick_stop(lines, stop_side, entry, d)
        if stop_pick is None:
            i += 1
            continue
        stop_init, stop_line = stop_pick
        preferred_tf = stop_line.timeframe
        # Re-price stop on entry date (line extends one bar past signal)
        entry_date = df.iloc[entry_i]["Date"]
        if trailing:
            trail0 = resolve_trailing_stop(
                piv_w, piv_m, entry_date, tfs, stop_side, preferred_tf, entry
            )
            if trail0 is not None:
                stop_init, stop_line = trail0
        stop_px = stop_init
        risk = abs(entry - stop_init)
        if risk <= 0 or risk / entry < 1e-4:
            i += 1
            continue

        if direction == "long":
            target = entry + TARGET_R * risk
        else:
            target = entry - TARGET_R * risk

        exit_i = None
        exit_px = None
        exit_type = "TIME"
        last = min(entry_i + TIME_STOP_BARS, n - 1)
        for j in range(entry_i + 1, last + 1):
            bar = df.iloc[j]
            bar_d = bar["Date"]
            o, h, lo = float(bar["Open"]), float(bar["High"]), float(bar["Low"])
            if trailing:
                trail = resolve_trailing_stop(
                    piv_w, piv_m, bar_d, tfs, stop_side, preferred_tf, entry
                )
                if trail is not None:
                    stop_px, stop_line = trail
            if direction == "long":
                if o <= stop_px:
                    exit_i, exit_px, exit_type = j, o, "GAP_DOWN"
                    break
                if lo <= stop_px:
                    exit_i, exit_px, exit_type = j, stop_px, "STOP"
                    break
                if o >= target:
                    exit_i, exit_px, exit_type = j, o, "GAP_UP"
                    break
                if h >= target:
                    exit_i, exit_px, exit_type = j, target, "TARGET"
                    break
            else:
                if o >= stop_px:
                    exit_i, exit_px, exit_type = j, o, "GAP_UP"
                    break
                if h >= stop_px:
                    exit_i, exit_px, exit_type = j, stop_px, "STOP"
                    break
                if o <= target:
                    exit_i, exit_px, exit_type = j, o, "GAP_DOWN"
                    break
                if lo <= target:
                    exit_i, exit_px, exit_type = j, target, "TARGET"
                    break
        if exit_i is None:
            exit_i = last
            exit_px = float(df.iloc[exit_i]["Close"])
            exit_type = "TIME"
            if trailing:
                trail = resolve_trailing_stop(
                    piv_w,
                    piv_m,
                    df.iloc[exit_i]["Date"],
                    tfs,
                    stop_side,
                    preferred_tf,
                    entry,
                )
                if trail is not None:
                    stop_px, stop_line = trail

        opened = df.iloc[entry_i]["Date"]
        closed = df.iloc[exit_i]["Date"]
        if direction == "long":
            pnl_pct = (float(exit_px) - entry) / entry * 100.0
            r_mult = (float(exit_px) - entry) / risk
        else:
            pnl_pct = (entry - float(exit_px)) / entry * 100.0
            r_mult = (entry - float(exit_px)) / risk
        if COSTS_BPS:
            pnl_pct -= COSTS_BPS / 100.0
        days = max((closed - opened).days, 1)
        trades.append(
            {
                "sym": sym,
                "arm": arm,
                "direction": direction,
                "opened": opened,
                "closed": closed,
                "entry": entry,
                "stop": stop_px,
                "stop_init": stop_init,
                "target": target,
                "exit_px": float(exit_px),
                "exit": exit_type,
                "pnl": pnl_pct,
                "r": r_mult,
                "days": float(days),
                "pnl_d": pnl_pct / 100.0 * SHEET,
                "signal_date": d,
                "sig_tf": sig_line.timeframe,
                "sig_side": sig_line.side,
                "stop_tf": stop_line.timeframe,
                "stop_side": stop_line.side,
                "risk": risk,
                "trailing": trailing,
            }
        )
        i = exit_i + 1
    return trades


def book_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(trades)
    empty = {
        "n": 0,
        "wins": 0,
        "losses": 0,
        "wr": 0.0,
        "avg_pnl": 0.0,
        "avg_r": 0.0,
        "pf": 0.0,
        "sheet": 0.0,
        "pnl_d": 0.0,
        "avg_days": 0.0,
        "avg_win": float("nan"),
        "avg_loss": float("nan"),
        "wo_max": 0.0,
        "exp_pct": 0.0,
        "ann_ror": float("nan"),
        "max_dd": float("nan"),
        "calmar": float("nan"),
        "cap_days": 0.0,
        "ppcd": float("nan"),
        "exits": {},
        "syms": 0,
        "long_n": 0,
        "short_n": 0,
    }
    if n == 0:
        return empty
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gp, gl = sum(wins), abs(sum(losses))
    mx = max(pnls)
    wo = (sum(pnls) - mx) / (n - 1) if n >= 2 else pnls[0]
    ov = overlay_ann_ror_max_dd(trades, cash=SHEET, initial_account=INIT_ACCT)
    ann = ov["ann_ror"]
    dd = ov["max_dd"]
    calmar = (
        ann / abs(dd)
        if math.isfinite(ann) and math.isfinite(dd) and abs(dd) > 1e-9
        else float("nan")
    )
    cap = float(ov.get("capital_days", 0.0) or 0.0)
    sheet = sum(p / 100.0 * SHEET for p in pnls)
    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "wr": 100.0 * len(wins) / n,
        "avg_pnl": sum(pnls) / n,
        "avg_r": sum(t["r"] for t in trades) / n,
        "pf": (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0),
        "sheet": sheet,
        "pnl_d": sum(t["pnl_d"] for t in trades),
        "avg_days": sum(t["days"] for t in trades) / n,
        "avg_win": (sum(wins) / len(wins)) if wins else float("nan"),
        "avg_loss": (sum(losses) / len(losses)) if losses else float("nan"),
        "wo_max": wo,
        "exp_pct": sum(pnls) / n,
        "ann_ror": ann,
        "max_dd": dd,
        "calmar": calmar,
        "cap_days": cap,
        "ppcd": (sheet / cap) if cap > 0 else float("nan"),
        "exits": dict(Counter(str(t.get("exit") or "?") for t in trades)),
        "syms": len({t["sym"] for t in trades}),
        "long_n": sum(1 for t in trades if t["direction"] == "long"),
        "short_n": sum(1 for t in trades if t["direction"] == "short"),
    }


def split_is_oos(trades: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return (
        [t for t in trades if t["opened"] < IS_CUT],
        [t for t in trades if t["opened"] >= IS_CUT],
    )


def fmt_pct(x: float, nd: int = 2) -> str:
    if x is None or not math.isfinite(float(x)):
        return "—"
    return f"{float(x):.{nd}f}%"


def fmt_n(x: float, nd: int = 2) -> str:
    if x is None or not math.isfinite(float(x)):
        return "—"
    return f"{float(x):,.{nd}f}"


def exit_mix(d: dict) -> str:
    items = sorted(d.items(), key=lambda kv: -kv[1])
    return ", ".join(f"{k}:{v}" for k, v in items) if items else "—"


def pack_arm(name: str, role: str, trades: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    is_t, oos_t = split_is_oos(trades)
    d = {
        "name": name,
        "role": role,
        "trades": trades,
        "full": book_stats(trades),
        "is": book_stats(is_t),
        "oos": book_stats(oos_t),
        "verd": extra.get("verd", "—"),
        "note": extra.get("note", ""),
    }
    return d


def verdict_vs_control(
    ctrl_is: dict,
    cand_is: dict,
    ctrl_oos: dict,
    cand_oos: dict,
    cand_label: str = "candidate",
) -> tuple[str, str]:
    if cand_is["n"] < 10:
        return "HOLD", "Candidate N too thin for KEEP"

    def better(a: float, b: float, higher: bool = True) -> bool:
        if not (math.isfinite(a) and math.isfinite(b)):
            return False
        return a > b + 1e-9 if higher else a < b - 1e-9

    n_ratio = cand_is["n"] / max(ctrl_is["n"], 1)
    n_collapsed = n_ratio < 0.25
    is_quality_up = (
        better(cand_is["avg_pnl"], ctrl_is["avg_pnl"])
        and better(cand_is["pf"], ctrl_is["pf"])
        and (
            better(cand_is["ann_ror"], ctrl_is["ann_ror"])
            or not math.isfinite(ctrl_is["ann_ror"])
        )
    )
    is_quality_down = better(ctrl_is["avg_pnl"], cand_is["avg_pnl"]) and better(
        ctrl_is["pf"], cand_is["pf"]
    )
    oos_soft = False
    if ctrl_oos["n"] >= 5 and cand_oos["n"] >= 3:
        oos_soft = (
            cand_oos["avg_pnl"] < ctrl_oos["avg_pnl"] - 0.05
            or (
                math.isfinite(cand_oos["ann_ror"])
                and math.isfinite(ctrl_oos["ann_ror"])
                and cand_oos["ann_ror"] < ctrl_oos["ann_ror"] - 1.0
            )
        )
    if is_quality_down:
        return "DISMISS", f"IS quality worse (Avg PnL% / PF) for {cand_label} vs control"
    if oos_soft:
        return "HOLD", f"IS quality may lift but OOS softened — do not retune OOS"
    if is_quality_up and n_collapsed:
        return "HOLD", f"IS quality up but N collapsed ({cand_is['n']}/{ctrl_is['n']})"
    if is_quality_up and not n_collapsed:
        return "LEAN KEEP", "IS quality up without N collapse; OOS not softer — research only"
    return "HOLD", f"Flat / mixed quality vs control ({cand_label})"


def system_verdict(ctrl: dict[str, Any]) -> tuple[str, str]:
    is_m, oos_m = ctrl["is"], ctrl["oos"]
    if is_m["n"] < 20:
        return "HOLD", f"Control IS N={is_m['n']} too thin for KEEP/DISMISS"
    edge = is_m["avg_pnl"] > 0.05 and is_m["pf"] >= 1.05 and (
        not math.isfinite(is_m["ann_ror"]) or is_m["ann_ror"] > 0
    )
    weak = is_m["avg_pnl"] < -0.05 and is_m["pf"] < 1.0
    oos_soft = False
    if oos_m["n"] >= 8 and edge:
        oos_soft = oos_m["avg_pnl"] < -0.1 or (
            math.isfinite(oos_m["ann_ror"]) and oos_m["ann_ror"] < -5.0
        )
    if weak:
        return (
            "DISMISS",
            f"Control IS negative quality (Avg={is_m['avg_pnl']:.2f}%, PF={is_m['pf']:.2f})",
        )
    if edge and oos_soft:
        return "HOLD", "Control IS positive but OOS softened — do not retune OOS; research HOLD"
    if edge:
        return (
            "LEAN KEEP",
            "Control IS positive quality; OOS not soft — research candidate only (not gold, not DailyRun)",
        )
    return "HOLD", "Control IS flat / mixed — no KEEP"


def write_trades_csv(path: Path, trades: list[dict[str, Any]]) -> None:
    fields = [
        "SYMBOL",
        "ARM",
        "DIRECTION",
        "DATE_OPENED",
        "DATE_CLOSED",
        "ENTRY_PRICE",
        "STOP_INIT",
        "STOP_PRICE",
        "TARGET_PRICE",
        "EXIT_PRICE",
        "EXIT_TYPE",
        "PNL_PCT",
        "R_MULT",
        "DAYS_HELD",
        "PNL_DOLLARS",
        "SIGNAL_DATE",
        "SIG_TF",
        "SIG_SIDE",
        "STOP_TF",
        "STOP_SIDE",
        "RISK",
        "TRAILING",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for t in trades:
            w.writerow(
                {
                    "SYMBOL": t["sym"],
                    "ARM": t["arm"],
                    "DIRECTION": t["direction"],
                    "DATE_OPENED": t["opened"].isoformat(),
                    "DATE_CLOSED": t["closed"].isoformat(),
                    "ENTRY_PRICE": f"{t['entry']:.4f}",
                    "STOP_INIT": f"{t.get('stop_init', t['stop']):.4f}",
                    "STOP_PRICE": f"{t['stop']:.4f}",
                    "TARGET_PRICE": f"{t['target']:.4f}",
                    "EXIT_PRICE": f"{t['exit_px']:.4f}",
                    "EXIT_TYPE": t["exit"],
                    "PNL_PCT": f"{t['pnl']:.4f}",
                    "R_MULT": f"{t['r']:.4f}",
                    "DAYS_HELD": f"{t['days']:.0f}",
                    "PNL_DOLLARS": f"{t['pnl_d']:.2f}",
                    "SIGNAL_DATE": t["signal_date"].isoformat(),
                    "SIG_TF": t["sig_tf"],
                    "SIG_SIDE": t["sig_side"],
                    "STOP_TF": t["stop_tf"],
                    "STOP_SIDE": t["stop_side"],
                    "RISK": f"{t['risk']:.4f}",
                    "TRAILING": "Y" if t.get("trailing", TRAILING_STOP) else "N",
                }
            )


def metric_rows_html(arms: list[dict[str, Any]], book: str) -> str:
    headers = filter_html_compare_columns(
        [
            ("Arm", "text"),
            ("Role", "text"),
            ("N", "num"),
            ("Long", "num"),
            ("Short", "num"),
            ("Win%", "num"),
            ("Avg PnL%", "num"),
            ("AVG_PNL_PCT_WO_MAX", "num"),
            ("AvgR", "num"),
            ("PF", "num"),
            ("Sheet PnL $", "num"),
            ("Ann ROR%", "num"),
            ("Max DD%", "num"),
            ("Calmar", "num"),
            ("Expect %", "num"),
            ("Avg days", "num"),
            ("Capital days", "num"),
            ("PPCD $", "num"),
            ("Δ Avg PnL%", "num"),
            ("Δ Ann ROR%", "num"),
            ("Δ Max DD%", "num"),
            ("Δ Sheet $", "num"),
            ("Exit mix", "text"),
            ("Verdict", "text"),
        ]
    )
    th = "".join(sortable_th(a, b) for a, b in headers)
    ctrl = next((a[book] for a in arms if a["role"] == "control"), arms[0][book])
    body = []
    for a in arms:
        m = a[book]
        d_avg = m["avg_pnl"] - ctrl["avg_pnl"]
        d_ror = (
            m["ann_ror"] - ctrl["ann_ror"]
            if math.isfinite(m["ann_ror"]) and math.isfinite(ctrl["ann_ror"])
            else float("nan")
        )
        d_dd = (
            m["max_dd"] - ctrl["max_dd"]
            if math.isfinite(m["max_dd"]) and math.isfinite(ctrl["max_dd"])
            else float("nan")
        )
        cells = [
            html_mod.escape(a["name"]),
            a["role"],
            str(m["n"]),
            str(m["long_n"]),
            str(m["short_n"]),
            fmt_pct(m["wr"]),
            fmt_pct(m["avg_pnl"]),
            fmt_pct(m["wo_max"]),
            fmt_n(m["avg_r"]),
            fmt_n(m["pf"]),
            fmt_n(m["ann_ror"], 1),
            fmt_pct(m["max_dd"]),
            fmt_n(m["calmar"]),
            fmt_pct(m["exp_pct"]),
            fmt_n(m["avg_days"], 1),
            fmt_n(m["cap_days"], 0),
            format_money(m["ppcd"]) if math.isfinite(m["ppcd"]) else "—",
            f"{d_avg:+.2f}pp" if a["role"] != "control" else "—",
            f"{d_ror:+.1f}" if a["role"] != "control" and math.isfinite(d_ror) else "—",
            f"{d_dd:+.2f}pp" if a["role"] != "control" and math.isfinite(d_dd) else "—",
            html_mod.escape(exit_mix(m["exits"])),
        ]
        if a["role"] == "control":
            cells.append("CONTROL")
        else:
            cells.append(html_mod.escape(f"{a.get('verd', '—')} — {a.get('note', '')}"))
        body.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    return f"<thead><tr>{th}</tr></thead><tbody>{''.join(body)}</tbody>"


def write_html(
    path: Path,
    univ: list[str],
    arms: list[dict[str, Any]],
    sys_verd: str,
    sys_note: str,
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>Trendline break longs + trailing — {STAMP}</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 1.5rem; color: #1a1a1a; }}
h1 {{ font-size: 1.35rem; }} h2 {{ font-size: 1.1rem; margin-top: 1.5rem; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.82rem; margin: 0.5rem 0 1rem; }}
th, td {{ border: 1px solid #cbd5e1; padding: 0.35rem 0.5rem; text-align: left; }}
th {{ background: #f1f5f9; }}
.note {{ background: #fff7ed; border: 1px solid #fed7aa; padding: 0.75rem 1rem; border-radius: 6px; }}
code {{ background: #f1f5f9; padding: 0.1rem 0.3rem; border-radius: 3px; }}
{SORT_CSS}
</style></head><body>
<h1>Trendline break — PaulTwenty A/B (longs + trailing stop)</h1>
<p><strong>Stamp:</strong> <code>{html_mod.escape(STAMP)}</code> · Generated {now}</p>
<div class="note">
<strong>Research only.</strong> Not gold. Not DailyRun.
<strong>Stop trails extending opposite trendline: YES</strong> (engine fix vs prior
<code>{html_mod.escape(PRIOR_STAMP)}</code> which froze stop at entry).
Fractal swing lines: weekly k={PIVOT_K['weekly']}, monthly k={PIVOT_K['monthly']}; last two same-kind swings; extend daily.
<strong>Look-ahead:</strong> pivot at HTF bar i active only after bar i+k completes.
Break = daily Close cross beyond line. Entry next open.
Control = either_wm long+short. Candidates = longs_only / weekly_longs_only / monthly_longs_only.
Target = {TARGET_R:g}R from <em>initial</em> risk. Time stop {TIME_STOP_BARS} bars.
IS = entry &lt; 2024-01-01; OOS report-only. Side/TF selection after table = in-sample bias — labeled.
Click column headers to sort.
</div>
<p><strong>Universe:</strong> {html_mod.escape(", ".join(univ))} (N={len(univ)})</p>
<p><strong>System verdict (control either_wm + trailing):</strong>
{html_mod.escape(sys_verd)} — {html_mod.escape(sys_note)}</p>

<h2>1. Freeze</h2>
<ul>
<li><strong>Lines:</strong> weekly ({WEEK_FREQ}) / monthly ({MONTH_FREQ}) fractal swings; last two highs→resistance, lows→support.</li>
<li><strong>Break:</strong> <code>{BREAK_DEF}</code> — prior Close on/inside line, signal Close beyond.</li>
<li><strong>Signal:</strong> Close above resistance → long; Close below support → short (control). Longs-only arms ignore shorts.</li>
<li><strong>Stop (trailing YES):</strong> at entry = nearest opposite among arm TFs; each later bar = extension of same TF+side active family (last-two may roll); fallback = nearest opposite. Not a ratchet — geometric follow.</li>
<li><strong>Target / time:</strong> {TARGET_R:g}R from initial risk (fixed) / {TIME_STOP_BARS} bars. Sheet ${SHEET:,.0f} / initial ${INIT_ACCT:,.0f}.</li>
<li><strong>Control:</strong> either_wm long+short with trailing. Candidates: longs_only, weekly_longs_only, monthly_longs_only.</li>
</ul>

<h2>IS (entry &lt; 2024-01-01)</h2>
<table class="sortable"><caption>Click headers to sort</caption>{metric_rows_html(arms, "is")}</table>

<h2>OOS report-only (entry ≥ 2024-01-01)</h2>
<table class="sortable"><caption>Click headers to sort</caption>{metric_rows_html(arms, "oos")}</table>

<h2>Full book</h2>
<table class="sortable"><caption>Click headers to sort</caption>{metric_rows_html(arms, "full")}</table>

<p class="muted">Generator: <code>tools/trendline_break_ab.py</code>. Canonical compare metrics subset + overlay Ann ROR / Max DD / Calmar.</p>
{SORT_JS}
</body></html>
"""
    path.write_text(html, encoding="utf-8")


def write_baseline(
    path: Path,
    univ: list[str],
    ctrl_trail: Optional[dict[str, Any]] = None,
    ctrl_fixed: Optional[dict[str, Any]] = None,
) -> None:
    trail_note = ""
    if ctrl_trail is not None and ctrl_fixed is not None:
        ti, fi = ctrl_trail["is"], ctrl_fixed["is"]
        to, fo = ctrl_trail["oos"], ctrl_fixed["oos"]
        trail_note = f"""
## Delta vs old fixed-stop control ({PRIOR_STAMP})

Prior engine **froze** stop at entry. New engine truth = **trailing**.
Re-baseline control = `either_wm` long+short **with trailing**.

| Book | Fixed-stop either_wm | Trailing either_wm (new control) |
|------|----------------------|----------------------------------|
| IS N / Avg% / PF / AnnROR | {fi['n']} / {fi['avg_pnl']:.2f} / {fi['pf']:.2f} / {fi['ann_ror'] if math.isfinite(fi['ann_ror']) else float('nan'):.1f} | {ti['n']} / {ti['avg_pnl']:.2f} / {ti['pf']:.2f} / {ti['ann_ror'] if math.isfinite(ti['ann_ror']) else float('nan'):.1f} |
| OOS N / Avg% / PF | {fo['n']} / {fo['avg_pnl']:.2f} / {fo['pf']:.2f} | {to['n']} / {to['avg_pnl']:.2f} / {to['pf']:.2f} |
| FULL N / Avg% / PF | {ctrl_fixed['full']['n']} / {ctrl_fixed['full']['avg_pnl']:.2f} / {ctrl_fixed['full']['pf']:.2f} | {ctrl_trail['full']['n']} / {ctrl_trail['full']['avg_pnl']:.2f} / {ctrl_trail['full']['pf']:.2f} |

Δ IS Avg PnL% (trail − fixed) = {ti['avg_pnl'] - fi['avg_pnl']:+.2f}pp.
"""
    path.write_text(
        f"""# BASELINE — {STAMP}

**Research only.** Not gold. Not DailyRun. Do not wire.

## Stop trails extending opposite trendline: YES

After fix: each hold bar the stop = current price of the **active opposite-direction**
trendline (same TF+side family chosen at entry), linearly extended to that bar's
date. When last-two pivots roll, the family line updates. Not frozen at entry.

Prior stamp `{PRIOR_STAMP}` froze stop at entry (**NO** trail) — bug vs Paul intent.

## Universe

PaulTwenty (`drive/universes/PaulTwenty_universe.csv`), N={len(univ)}:

{", ".join(univ)}

Canonical top-20 market-cap names with local OHLC under `data/newdata/data`
(fundamentals_cache ranking; ATEYY excluded).

## Line construction (frozen)

Same fractal-swing algorithm as `tools/gen_trendlines_tos_studies.py` /
`drive/paul_studies/trendlines_mw_d_20260827/`:

| TF | Resample | Fractal half-window k |
|----|----------|------------------------|
| Weekly | `{WEEK_FREQ}` | {PIVOT_K['weekly']} |
| Monthly | `{MONTH_FREQ}` | {PIVOT_K['monthly']} |

- Swing **highs** → **resistance**; swing **lows** → **support**.
- Active line = **last two** confirmed same-kind swings; linear interp in calendar days; **extend** past the newer swing.
- HTF pivot date refined to the daily bar that printed the period High/Low.

## Look-ahead (critical)

A fractal pivot at HTF index `i` requires bars `[i−k … i+k]`. The pivot becomes
**active only on the end date of HTF bar `i+k`** (`confirmed_on`). The two-point
line is active from `max(confirm_a, confirm_b)`. On date `t`, only lines with
`active_from ≤ t` are used (signals and trailing stop). Incomplete current
week/month bars are not used as confirmation until their last trading day arrives.

## Break definition (frozen)

**`{BREAK_DEF}`:** daily **Close** crosses beyond the line:

- Long: prior Close ≤ line price and signal Close > line price (resistance).
- Short: prior Close ≥ line price and signal Close < line price (support).

Prefer Close (less noise than High/Low pierce). Labeled explicitly — not High/Low.

## Signal

- Close above weekly **or** monthly resistance → **long** (control `either_wm`).
- Close below weekly **or** monthly support → **short** (control).
- Control: same calendar day both long and short → **skip** (conflict).
- Longs-only arms: take long if present; ignore shorts / conflict.
- Multiple same-direction hits → take largest Close−line magnitude.
- One open trade per symbol; flat before next signal.

## Entry

**{ENTRY}** after signal Close. Filters: Close ≥ ${MIN_PRICE:.0f}, ADV20 ≥ {MIN_ADV20:,.0f}.

## Stop (trailing)

**Stop trails extending opposite trendline: YES**

1. **At entry:** nearest opposite-direction line among the **arm's TF set**:
   - Long → nearest **support** with line price **below** entry.
   - Short → nearest **resistance** with line price **above** entry.
   - Record preferred **TF+side** family (e.g. weekly support).
2. **Each later bar:** recompute stop = linear extension to that date of the
   **currently active** line for the same TF+side family (last-two pivots may
   roll when a newer swing confirms — still same family). If family missing,
   fall back to nearest opposite vs entry among arm TFs.
3. **Not a ratchet:** stop follows the geometry (can loosen if line slopes against).
4. If no valid opposite at entry → **skip** (no ATR fallback).

R-multiple and 1R target use **initial** |entry−stop| risk; exit stop may differ.

## Target / exit (research freeze)

- **Target** = `{TARGET_R:g}R` (entry ± TARGET_R × initial risk) — **fixed** after entry.
- **Time stop** = {TIME_STOP_BARS} daily bars after entry.
- Same-bar: stop checked before target (conservative). Gap through stop/target marked GAP_*.

## Control vs AB knobs

**New control:** `either_wm` — weekly OR monthly breaks, **long+short**, **trailing stop**.

**Candidates** (side and/or TF filter; trailing + break/entry/target/time frozen):

| Arm | Role | Signal TFs | Sides |
|-----|------|------------|-------|
| either_wm | control | weekly, monthly | long+short |
| longs_only | candidate | weekly, monthly | long only |
| weekly_longs_only | candidate | weekly | long only |
| monthly_longs_only | candidate | monthly | long only |

Choosing among side/TF arms after seeing the table is **in-sample selection** —
label any follow-up freeze. OOS is report-only.
{trail_note}
## IS / OOS

- IS: `entry_date < 2024-01-01`
- OOS: `entry_date >= 2024-01-01` — **report-only**; never retune on OOS.
- Judge **quality over N** (WR, AvgR, Avg PnL%, PF, Ann ROR, Max DD).

## Overlay sizing

Sheet notional ${SHEET:,.0f}; initial account ${INIT_ACCT:,.0f} for Ann ROR / Max DD overlay
(`compare_format.overlay_ann_ror_max_dd`). Costs {COSTS_BPS} bps.

## Honesty

- In-sample selection if a candidate is later adopted from this table — label any follow-up freeze.
- Research candidate ≠ gold ≠ DailyRun.
""",
        encoding="utf-8",
    )


def write_ab_plan(path: Path) -> None:
    path.write_text(
        f"""# AB_PLAN — {STAMP}

## Hypothesis

Under a **trailing** opposite-trendline stop (engine truth after fix), **longs-only**
(and especially **weekly longs**) may show better quality than long+short
`either_wm` control — validating Paul's eyeball that longs / weekly longs look good.

## Knobs (labeled)

| Arm | vs control |
|-----|------------|
| either_wm (control) | weekly OR monthly; long+short; trailing stop |
| longs_only | same TFs; **longs only**; trailing |
| weekly_longs_only | **weekly** breaks only; longs only; trailing |
| monthly_longs_only | **monthly** breaks only; longs only; trailing |

Frozen: break=`{BREAK_DEF}`, entry=`{ENTRY}`, trailing opposite-line stop,
target={TARGET_R:g}R (initial risk), time_stop={TIME_STOP_BARS}, PaulTwenty,
fractal k W={PIVOT_K['weekly']} / M={PIVOT_K['monthly']}.

Note: candidates change **side** and/or **TF** vs control — not a pure one-knob
grid. Interpret arms as labeled; any KEEP is in-sample selection among them.

## Decision rule

- KEEP / LEAN KEEP only if IS quality (Avg PnL%, PF, Ann ROR) improves vs control
  **without** N collapse (<25% of control IS N).
- OOS softens → HOLD; do not retune OOS.
- Flat → HOLD; worse IS → DISMISS.

## Out of scope

- Stop ratchet (only tighten) vs geometric trail.
- High/Low break vs Close break.
- Gold / DailyRun wire.
""",
        encoding="utf-8",
    )


def write_summary(
    path: Path,
    univ: list[str],
    arms: list[dict[str, Any]],
    sys_verd: str,
    sys_note: str,
) -> None:
    lines = [
        f"# SUMMARY — {STAMP}",
        "",
        f"**System verdict (control either_wm + trailing):** {sys_verd} — {sys_note}",
        "",
        "**Stop trails extending opposite trendline: YES**",
        "",
        f"**Universe:** PaulTwenty N={len(univ)}",
        "",
        "## Arms (IS / OOS / FULL)",
        "",
        "| Arm | Role | IS N | IS Avg% | IS PF | IS AnnROR | OOS N | OOS Avg% | OOS PF | FULL N | Verdict |",
        "|-----|------|------|---------|-------|-----------|-------|----------|--------|--------|---------|",
    ]
    for a in arms:
        is_m, oos_m, full = a["is"], a["oos"], a["full"]
        verd = "CONTROL" if a["role"] == "control" else f"{a['verd']}"
        lines.append(
            f"| {a['name']} | {a['role']} | {is_m['n']} | {is_m['avg_pnl']:.2f} | {is_m['pf']:.2f} | "
            f"{is_m['ann_ror'] if math.isfinite(is_m['ann_ror']) else float('nan'):.1f} | "
            f"{oos_m['n']} | {oos_m['avg_pnl']:.2f} | {oos_m['pf']:.2f} | {full['n']} | {verd} |"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Quality over N; OOS report-only.",
            "- Choosing side/TF after this table = in-sample selection — research only.",
            "- Research only — not gold, not DailyRun.",
            f"- Artifacts: `compare.html`, Closed CSVs per arm, BASELINE.md, AB_PLAN.md.",
            "",
        ]
    )
    for a in arms:
        if a["role"] != "control":
            lines.append(f"- **{a['name']}:** {a['verd']} — {a['note']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _sym_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Compact per-symbol book stats (full + IS/OOS)."""
    is_t, oos_t = split_is_oos(trades)
    full = book_stats(trades)
    is_m = book_stats(is_t)
    oos_m = book_stats(oos_t)

    def pack(st: dict[str, Any]) -> dict[str, Any]:
        empty = st["n"] == 0
        return {
            "N": st["n"],
            "WinRate": float("nan") if empty else st["wr"],
            "AvgPnL_pct": float("nan") if empty else st["avg_pnl"],
            "AvgR": float("nan") if empty else st["avg_r"],
            "PF": float("nan") if empty else st["pf"],
            "SumPnL_$": 0.0 if empty else st["sheet"],
            "MaxDD": float("nan") if empty else st["max_dd"],
            "IS_N": 0,  # filled below for nested; unused in pack
        }

    # Build flat dict with IS/OOS prefixes from segment packs
    fp, ip, op = pack(full), pack(is_m), pack(oos_m)
    return {
        "N": fp["N"],
        "WinRate": fp["WinRate"],
        "AvgPnL_pct": fp["AvgPnL_pct"],
        "AvgR": fp["AvgR"],
        "PF": fp["PF"],
        "SumPnL_$": fp["SumPnL_$"],
        "MaxDD": fp["MaxDD"],
        "IS_N": ip["N"],
        "IS_AvgPct": ip["AvgPnL_pct"],
        "IS_PF": ip["PF"],
        "OOS_N": op["N"],
        "OOS_AvgPct": op["AvgPnL_pct"],
        "OOS_PF": op["PF"],
    }


def _empty_sym_stats() -> dict[str, Any]:
    return {
        "N": 0,
        "WinRate": float("nan"),
        "AvgPnL_pct": float("nan"),
        "AvgR": float("nan"),
        "PF": float("nan"),
        "SumPnL_$": 0.0,
        "MaxDD": float("nan"),
        "IS_N": 0,
        "IS_AvgPct": float("nan"),
        "IS_PF": float("nan"),
        "OOS_N": 0,
        "OOS_AvgPct": float("nan"),
        "OOS_PF": float("nan"),
    }


def _label_for_row(n: int, avg: float, pf: float, min_n: int) -> str:
    if n < min_n:
        return "thin_N"
    if math.isfinite(avg) and avg > 0 and (not math.isfinite(pf) or pf >= 1.0):
        return "worked_well"
    if math.isfinite(avg) and avg < 0:
        return "soft_or_neg"
    return "flat_mixed"


def process_symbol_summary(sym: str) -> dict[str, Any]:
    """Worker: longs_only + weekly_longs_only with shared pivots."""
    df = load_ohlc(sym)
    if df is None:
        return {
            "sym": sym,
            "status": "missing_ohlc",
            "bars": 0,
            "longs": [],
            "weekly": [],
        }
    bars = len(df)
    if bars < MIN_DAILY_BARS:
        return {
            "sym": sym,
            "status": "too_short",
            "bars": bars,
            "longs": [],
            "weekly": [],
        }
    piv_w = confirmed_pivots_for_tf(df, WEEK_FREQ, "weekly", PIVOT_K["weekly"])
    piv_m = confirmed_pivots_for_tf(df, MONTH_FREQ, "monthly", PIVOT_K["monthly"])
    longs = simulate_symbol(
        df,
        sym,
        "longs_only",
        ("weekly", "monthly"),
        side_mode="long",
        trailing=True,
        piv_w=piv_w,
        piv_m=piv_m,
    )
    weekly = simulate_symbol(
        df,
        sym,
        "weekly_longs_only",
        ("weekly",),
        side_mode="long",
        trailing=True,
        piv_w=piv_w,
        piv_m=piv_m,
    )
    return {
        "sym": sym,
        "status": "ok",
        "bars": bars,
        "longs": longs,
        "weekly": weekly,
    }


def build_symbol_summary_rows(
    results: list[dict[str, Any]],
    *,
    min_n: int = MIN_N_RANK,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    rows: list[dict[str, Any]] = []
    weekly_rows: list[dict[str, Any]] = []
    skip_counts: dict[str, int] = defaultdict(int)
    for r in results:
        status = str(r.get("status") or "ok")
        if status != "ok":
            skip_counts[status] += 1
            empty = _empty_sym_stats()
            rows.append(
                {
                    "Symbol": r["sym"],
                    "Status": status,
                    "Bars": int(r.get("bars") or 0),
                    **empty,
                    "W_N": 0,
                    "W_WinRate": float("nan"),
                    "W_AvgPnL_pct": float("nan"),
                    "W_PF": float("nan"),
                    "W_IS_N": 0,
                    "W_IS_AvgPct": float("nan"),
                    "W_OOS_N": 0,
                    "W_OOS_AvgPct": float("nan"),
                    "label": "skip",
                    "rank_eligible": False,
                }
            )
            weekly_rows.append(
                {
                    "Symbol": r["sym"],
                    "Status": status,
                    "Bars": int(r.get("bars") or 0),
                    **empty,
                    "label": "skip",
                    "rank_eligible": False,
                }
            )
            continue
        ls = _sym_stats(r["longs"])
        ws = _sym_stats(r["weekly"])
        label = _label_for_row(int(ls["N"]), float(ls["AvgPnL_pct"]), float(ls["PF"]), min_n)
        rows.append(
            {
                "Symbol": r["sym"],
                "Status": "ok",
                "Bars": int(r.get("bars") or 0),
                **ls,
                "W_N": ws["N"],
                "W_WinRate": ws["WinRate"],
                "W_AvgPnL_pct": ws["AvgPnL_pct"],
                "W_PF": ws["PF"],
                "W_IS_N": ws["IS_N"],
                "W_IS_AvgPct": ws["IS_AvgPct"],
                "W_OOS_N": ws["OOS_N"],
                "W_OOS_AvgPct": ws["OOS_AvgPct"],
                "label": label,
                "rank_eligible": int(ls["N"]) >= min_n,
            }
        )
        w_label = _label_for_row(int(ws["N"]), float(ws["AvgPnL_pct"]), float(ws["PF"]), min_n)
        weekly_rows.append(
            {
                "Symbol": r["sym"],
                "Status": "ok",
                "Bars": int(r.get("bars") or 0),
                **ws,
                "label": w_label,
                "rank_eligible": int(ws["N"]) >= min_n,
            }
        )

    def _sort_key(row: dict[str, Any]) -> tuple[float, float]:
        avg = row.get("AvgPnL_pct")
        sm = row.get("SumPnL_$")
        a = float(avg) if isinstance(avg, (int, float)) and math.isfinite(avg) else -999.0
        s = float(sm) if isinstance(sm, (int, float)) and math.isfinite(sm) else 0.0
        return (a, s)

    rows.sort(key=_sort_key, reverse=True)
    weekly_rows.sort(key=_sort_key, reverse=True)
    return rows, weekly_rows, dict(skip_counts)


def write_symbol_summary_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            out = {}
            for k in fields:
                v = r.get(k)
                if isinstance(v, float):
                    out[k] = "" if not math.isfinite(v) else f"{v:.6g}"
                else:
                    out[k] = v
            w.writerow(out)


def write_symbol_summary_html(
    path: Path,
    *,
    stamp: str,
    univ_note: str,
    n_univ: int,
    skip_counts: dict[str, int],
    rows: list[dict[str, Any]],
    top: list[dict[str, Any]],
    bottom: list[dict[str, Any]],
    min_n: int,
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    def cell_num(v: Any, nd: int = 2) -> str:
        if v is None or (isinstance(v, float) and not math.isfinite(v)):
            return "<td>—</td>"
        if isinstance(v, (int, float)):
            return f"<td>{float(v):,.{nd}f}</td>"
        return f"<td>{html_mod.escape(str(v))}</td>"

    def cell_money(v: Any) -> str:
        if isinstance(v, (int, float)) and math.isfinite(v):
            return f"<td>{format_money(v)}</td>"
        return "<td>—</td>"

    def rank_table(title: str, subset: list[dict[str, Any]]) -> str:
        ths = "".join(
            [
                sortable_th("Symbol", "text"),
                sortable_th("N", "num"),
                sortable_th("WinRate", "num"),
                sortable_th("AvgPnL%", "num"),
                sortable_th("PF", "num"),
                sortable_th("SumPnL$", "num"),
                sortable_th("MaxDD%", "num"),
                sortable_th("IS_N", "num"),
                sortable_th("IS_Avg%", "num"),
                sortable_th("OOS_N", "num"),
                sortable_th("OOS_Avg%", "num"),
                sortable_th("W_N", "num"),
                sortable_th("W_Avg%", "num"),
                sortable_th("label", "text"),
            ]
        )
        body = []
        for r in subset:
            body.append(
                "<tr>"
                f"<td>{html_mod.escape(str(r['Symbol']))}</td>"
                f"{cell_num(r['N'], 0)}"
                f"{cell_num(r['WinRate'], 1)}"
                f"{cell_num(r['AvgPnL_pct'], 2)}"
                f"{cell_num(r['PF'], 2)}"
                f"{cell_money(r['SumPnL_$'])}"
                f"{cell_num(r['MaxDD'], 2)}"
                f"{cell_num(r['IS_N'], 0)}"
                f"{cell_num(r['IS_AvgPct'], 2)}"
                f"{cell_num(r['OOS_N'], 0)}"
                f"{cell_num(r['OOS_AvgPct'], 2)}"
                f"{cell_num(r['W_N'], 0)}"
                f"{cell_num(r['W_AvgPnL_pct'], 2)}"
                f"<td>{html_mod.escape(str(r.get('label') or ''))}</td>"
                "</tr>"
            )
        return (
            f"<h2>{html_mod.escape(title)}</h2>\n"
            f'<p class="small">Click column headers to sort.</p>\n'
            f'<table class="sortable"><thead><tr>{ths}</tr></thead>'
            f"<tbody>{''.join(body)}</tbody></table>"
        )

    skip_txt = ", ".join(f"{k}={v}" for k, v in sorted(skip_counts.items())) or "none"
    ok_n = sum(1 for r in rows if r.get("Status") == "ok")
    traded = sum(1 for r in rows if int(r.get("N") or 0) > 0)
    eligible = sum(1 for r in rows if r.get("rank_eligible"))

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Trendline break symbol summary — {html_mod.escape(stamp)}</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 1.5rem; color: #0f172a; background: #f8fafc; }}
h1 {{ font-size: 1.4rem; margin: 0 0 .4rem; }}
h2 {{ font-size: 1.1rem; margin: 1.4rem 0 .5rem; }}
.small {{ color: #64748b; font-size: .9rem; }}
table {{ border-collapse: collapse; width: 100%; background: #fff; margin-bottom: 1rem; font-size: .85rem; }}
th, td {{ border: 1px solid #cbd5e1; padding: .35rem .5rem; text-align: left; }}
th {{ background: #e2e8f0; }}
{SORT_CSS}
code {{ background: #e2e8f0; padding: .05rem .25rem; border-radius: 3px; }}
</style>
</head>
<body>
<h1>Trendline break — per-symbol summary (longs_only + trailing)</h1>
<p><strong>Stamp:</strong> <code>{html_mod.escape(stamp)}</code> · Generated {now}</p>
<p class="small"><strong>Research only.</strong> Not gold. Not DailyRun. Freeze matches LEAN KEEP from
<code>{html_mod.escape(STAMP)}</code>: <strong>longs_only</strong> (weekly OR monthly resistance break),
trailing opposite-trendline stop, target 1R, time stop 40.</p>
<p><strong>Universe:</strong> {html_mod.escape(univ_note)} · listed N={n_univ} ·
ok={ok_n} · with trades={traded} · rank-eligible (N≥{min_n})={eligible}</p>
<p class="small">Skips: {html_mod.escape(skip_txt)}. W_* columns = weekly_longs_only (same pass).</p>
<p class="small">IS = entry &lt; 2024-01-01; OOS = entry ≥ 2024-01-01 (report-only).</p>
{rank_table(f"Top rank-eligible (N≥{min_n}) by Avg PnL%", top)}
{rank_table(f"Bottom rank-eligible (N≥{min_n}) by Avg PnL%", bottom)}
{rank_table("All symbols (longs_only primary + weekly cols)", rows)}
{SORT_JS}
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def write_symbol_summary_baseline(
    path: Path,
    *,
    stamp: str,
    univ_path: Path,
    univ: list[str],
    skip_counts: dict[str, int],
    n_ok: int,
    n_traded: int,
) -> None:
    skip_txt = ", ".join(f"{k}={v}" for k, v in sorted(skip_counts.items())) or "none"
    path.write_text(
        f"""# BASELINE — {stamp}

**Research only.** Not gold. Not DailyRun. Do not wire.

## Purpose

Per-symbol quality table so Paul can pick which stocks the **trendline break longs**
system works well with. Freeze copied from LEAN KEEP research stamp `{STAMP}`.

## Freeze (exact)

| Knob | Value |
|------|-------|
| Arm | **longs_only** (primary) |
| Side | long only |
| Signal TFs | weekly **or** monthly resistance close-cross |
| Stop | **trailing** opposite support trendline (YES) |
| Break | `{BREAK_DEF}` |
| Entry | `{ENTRY}` |
| Target | `{TARGET_R:g}R` (initial risk; fixed after entry) |
| Time stop | {TIME_STOP_BARS} daily bars |
| Filters | Close ≥ ${MIN_PRICE:.0f}, ADV20 ≥ {MIN_ADV20:,.0f} |
| Fractal k | weekly={PIVOT_K['weekly']}, monthly={PIVOT_K['monthly']} |
| Trailing | `{TRAILING_STOP}` |

Also scored in the same pass (extra columns / second CSV): **weekly_longs_only**
(weekly resistance breaks only; same trailing stop / target / time).

## Universe

**Source:** `{univ_path.as_posix()}`

**Name:** VZ tradable 2010 / ADV$≥2M research list (broad stock-picking univ; not DualPaul survivor-cut).

- Listed symbols: **N={len(univ)}**
- OK (OHLC present + ≥{MIN_DAILY_BARS} daily bars): **{n_ok}**
- With ≥1 longs_only trade: **{n_traded}**
- Skips: {skip_txt}

OHLC root: `data/newdata/data/{{SYM}}.csv`.

## IS / OOS

- IS: `entry_date < 2024-01-01`
- OOS: `entry_date >= 2024-01-01` — **report-only**; never retune on OOS.

## Picking guidance

- Prefer **quality over N**; still require a floor: **N≥{MIN_N_RANK}** to rank top/bottom;
  **N≥{MIN_N_RANK_ALT}** is a stronger filter for shortlists.
- Labels: `worked_well` (AvgPnL%>0 and PF≥1), `soft_or_neg`, `flat_mixed`, `thin_N`, `skip`.
- Selecting a sleeve from this table is **in-sample selection** — label any follow-up freeze.

## Honesty

- Research candidate ≠ gold ≠ DailyRun.
- Prior PaulTwenty LEAN KEEP does not auto-promote any symbol here.
""",
        encoding="utf-8",
    )


def write_symbol_summary_md(
    path: Path,
    *,
    stamp: str,
    univ_path: Path,
    n_univ: int,
    n_ok: int,
    n_traded: int,
    skip_counts: dict[str, int],
    top: list[dict[str, Any]],
    bottom: list[dict[str, Any]],
    min_n: int,
    book_full: dict[str, Any],
) -> None:
    skip_txt = ", ".join(f"{k}={v}" for k, v in sorted(skip_counts.items())) or "none"

    def _avg(v: Any) -> str:
        if isinstance(v, (int, float)) and math.isfinite(v):
            return f"{float(v):.2f}"
        return "—"

    def row_line(r: dict[str, Any]) -> str:
        return (
            f"| {r['Symbol']} | {r['N']} | {r['WinRate']:.1f} | {r['AvgPnL_pct']:.2f} | "
            f"{r['PF']:.2f} | {r['SumPnL_$']:.0f} | "
            f"{r['IS_N']}/{_avg(r['IS_AvgPct'])} | "
            f"{r['OOS_N']}/{_avg(r['OOS_AvgPct'])} | "
            f"{r['W_N']}/{_avg(r['W_AvgPnL_pct'])} |"
        )

    lines = [
        f"# SUMMARY — {stamp}",
        "",
        "**Research only.** Not gold. Not DailyRun.",
        "",
        f"**Freeze:** longs_only + trailing opposite trendline stop (from `{STAMP}` LEAN KEEP).",
        "",
        f"**Universe:** `{univ_path.as_posix()}` listed N={n_univ}; ok={n_ok}; "
        f"with trades={n_traded}; skips: {skip_txt}.",
        "",
        f"**Book (longs_only, all traded symbols):** N={book_full['n']}, "
        f"WR={book_full['wr']:.1f}%, AvgPnL%={book_full['avg_pnl']:.2f}, "
        f"PF={book_full['pf']:.2f}, MaxDD={book_full['max_dd'] if math.isfinite(book_full['max_dd']) else float('nan'):.1f}%.",
        "",
        f"## Top 15 by Avg PnL% (N≥{min_n})",
        "",
        "| Symbol | N | WinRate | AvgPnL% | PF | Sum$ | IS N/Avg% | OOS N/Avg% | W N/Avg% |",
        "|--------|---|---------|---------|----|------|-----------|------------|----------|",
    ]
    for r in top[:15]:
        lines.append(row_line(r))
    lines.extend(
        [
            "",
            f"## Bottom 15 by Avg PnL% (N≥{min_n})",
            "",
            "| Symbol | N | WinRate | AvgPnL% | PF | Sum$ | IS N/Avg% | OOS N/Avg% | W N/Avg% |",
            "|--------|---|---------|---------|----|------|-----------|------------|----------|",
        ]
    )
    for r in bottom[:15]:
        lines.append(row_line(r))
    lines.extend(
        [
            "",
            "## Picking notes",
            "",
            f"- Rank filter used here: **N≥{min_n}** (also consider N≥{MIN_N_RANK_ALT}).",
            "- Primary columns = longs_only; W_* = weekly_longs_only.",
            "- OOS is report-only — do not retune from OOS soft spots.",
            "- Artifacts: `symbol_summary.csv`, `symbol_summary_weekly_longs.csv`, "
            "`symbol_summary.html`, BASELINE.md.",
            "",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_symbol_summary(
    univ: list[str],
    out_dir: Path,
    univ_path: Path,
    *,
    workers: int = 0,
    min_n: int = MIN_N_RANK,
) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = SYMBOL_SUMMARY_STAMP
    print(
        f"symbol-summary stamp={stamp} trailing={TRAILING_STOP} "
        f"symbols={len(univ)} workers={workers or 1} out={out_dir}",
        flush=True,
    )

    results: list[dict[str, Any]] = []
    if workers and workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(process_symbol_summary, sym): sym for sym in univ}
            done = 0
            for fut in as_completed(futs):
                results.append(fut.result())
                done += 1
                if done % 25 == 0 or done == len(univ):
                    print(f"  progress {done}/{len(univ)}", flush=True)
    else:
        for i, sym in enumerate(univ, 1):
            print(f"  [{i}/{len(univ)}] {sym} ...", flush=True)
            results.append(process_symbol_summary(sym))

    # Stable order by universe listing for skip accounting, then sort for tables
    by_sym = {r["sym"]: r for r in results}
    ordered = [by_sym[s] for s in univ if s in by_sym]

    rows, weekly_rows, skip_counts = build_symbol_summary_rows(ordered, min_n=min_n)
    n_ok = sum(1 for r in rows if r.get("Status") == "ok")
    n_traded = sum(1 for r in rows if int(r.get("N") or 0) > 0)

    eligible = [r for r in rows if r.get("rank_eligible")]
    eligible_sorted = sorted(
        eligible,
        key=lambda r: (
            float(r["AvgPnL_pct"])
            if isinstance(r["AvgPnL_pct"], (int, float)) and math.isfinite(r["AvgPnL_pct"])
            else -999.0
        ),
        reverse=True,
    )
    top = eligible_sorted[:15]
    bottom = list(reversed(eligible_sorted[-15:])) if eligible_sorted else []

    all_longs: list[dict[str, Any]] = []
    all_weekly: list[dict[str, Any]] = []
    for r in ordered:
        if r.get("status") == "ok":
            all_longs.extend(r["longs"])
            all_weekly.extend(r["weekly"])
    book_full = book_stats(all_longs)

    primary_fields = [
        "Symbol",
        "Status",
        "Bars",
        "N",
        "WinRate",
        "AvgPnL_pct",
        "AvgR",
        "PF",
        "SumPnL_$",
        "MaxDD",
        "IS_N",
        "IS_AvgPct",
        "IS_PF",
        "OOS_N",
        "OOS_AvgPct",
        "OOS_PF",
        "W_N",
        "W_WinRate",
        "W_AvgPnL_pct",
        "W_PF",
        "W_IS_N",
        "W_IS_AvgPct",
        "W_OOS_N",
        "W_OOS_AvgPct",
        "label",
        "rank_eligible",
    ]
    weekly_fields = [
        "Symbol",
        "Status",
        "Bars",
        "N",
        "WinRate",
        "AvgPnL_pct",
        "AvgR",
        "PF",
        "SumPnL_$",
        "MaxDD",
        "IS_N",
        "IS_AvgPct",
        "IS_PF",
        "OOS_N",
        "OOS_AvgPct",
        "OOS_PF",
        "label",
        "rank_eligible",
    ]

    write_symbol_summary_csv(out_dir / "symbol_summary.csv", rows, primary_fields)
    write_symbol_summary_csv(
        out_dir / "symbol_summary_weekly_longs.csv", weekly_rows, weekly_fields
    )
    write_trades_csv(out_dir / "Closed_longs_only.csv", all_longs)
    write_trades_csv(out_dir / "Closed_weekly_longs_only.csv", all_weekly)

    univ_note = (
        f"VZ tradable 2010 ADV$≥2M (`{univ_path.as_posix()}`)"
    )
    write_symbol_summary_html(
        out_dir / "symbol_summary.html",
        stamp=stamp,
        univ_note=univ_note,
        n_univ=len(univ),
        skip_counts=skip_counts,
        rows=rows,
        top=top,
        bottom=bottom,
        min_n=min_n,
    )
    write_symbol_summary_baseline(
        out_dir / "BASELINE.md",
        stamp=stamp,
        univ_path=univ_path,
        univ=univ,
        skip_counts=skip_counts,
        n_ok=n_ok,
        n_traded=n_traded,
    )
    write_symbol_summary_md(
        out_dir / "SUMMARY.md",
        stamp=stamp,
        univ_path=univ_path,
        n_univ=len(univ),
        n_ok=n_ok,
        n_traded=n_traded,
        skip_counts=skip_counts,
        top=top,
        bottom=bottom,
        min_n=min_n,
        book_full=book_full,
    )

    print(
        f"BOOK longs_only: N={book_full['n']} WR={book_full['wr']:.1f}% "
        f"Avg={book_full['avg_pnl']:.2f}% PF={book_full['pf']:.2f}"
    )
    print(f"ok={n_ok} traded={n_traded} skips={skip_counts}")
    print("TOP (N>=%d):" % min_n)
    for r in top[:15]:
        print(
            f"  {r['Symbol']:8s} N={r['N']:3d} WR={r['WinRate']:5.1f} "
            f"Avg={r['AvgPnL_pct']:6.2f} PF={r['PF']:5.2f}"
        )
    print("BOTTOM:")
    for r in bottom[:15]:
        print(
            f"  {r['Symbol']:8s} N={r['N']:3d} WR={r['WinRate']:5.1f} "
            f"Avg={r['AvgPnL_pct']:6.2f} PF={r['PF']:5.2f}"
        )
    print(f"wrote {out_dir}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Trendline break PaulTwenty A/B (longs + trailing)")
    ap.add_argument("--universe", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument(
        "--symbol-summary",
        action="store_true",
        help="Per-symbol longs_only (+ weekly_longs cols) on broad univ; research pick list",
    )
    ap.add_argument(
        "--workers",
        type=int,
        default=0,
        help="Process workers for --symbol-summary (0=auto: min(8, cpu))",
    )
    ap.add_argument(
        "--min-n",
        type=int,
        default=MIN_N_RANK,
        help=f"Min trades for top/bottom rank (default {MIN_N_RANK})",
    )
    args = ap.parse_args()

    if args.symbol_summary:
        univ_path = args.universe or TRADABLE_UNIV
        out_dir = args.out or SYMBOL_SUMMARY_OUT
        univ = load_universe(univ_path)
        if not univ:
            print(f"ERROR: empty universe {univ_path}", file=sys.stderr)
            return 1
        workers = args.workers
        if workers <= 0:
            try:
                import os

                workers = max(1, min(8, os.cpu_count() or 4))
            except Exception:
                workers = 4
        return run_symbol_summary(
            univ, out_dir, univ_path, workers=workers, min_n=args.min_n
        )

    univ_path = args.universe or PAULTWENTY
    out_dir = args.out or OUT_DIR
    univ = load_universe(univ_path)
    if not univ:
        print(f"ERROR: empty universe {univ_path}", file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"stamp={STAMP} trailing={TRAILING_STOP} symbols={len(univ)} out={out_dir}")
    packed: list[dict[str, Any]] = []
    for arm_name, role, tfs, side_mode in ARMS:
        all_trades: list[dict[str, Any]] = []
        missing = []
        for sym in univ:
            df = load_ohlc(sym)
            if df is None:
                missing.append(sym)
                continue
            print(f"  {arm_name} {sym} ...", flush=True)
            all_trades.extend(
                simulate_symbol(
                    df, sym, arm_name, tfs, side_mode=side_mode, trailing=True
                )
            )
        if missing:
            print(f"  WARN missing OHLC: {missing}")
        write_trades_csv(out_dir / f"Closed_{arm_name}.csv", all_trades)
        packed.append(pack_arm(arm_name, role, all_trades))
        print(
            f"  {arm_name}: N={len(all_trades)} "
            f"IS={packed[-1]['is']['n']} OOS={packed[-1]['oos']['n']}"
        )

    # Fixed-stop either_wm for BASELINE delta vs prior engine
    print("  either_wm_fixed (delta only) ...", flush=True)
    fixed_trades: list[dict[str, Any]] = []
    for sym in univ:
        df = load_ohlc(sym)
        if df is None:
            continue
        fixed_trades.extend(
            simulate_symbol(
                df,
                sym,
                "either_wm_fixed",
                ("weekly", "monthly"),
                side_mode="both",
                trailing=False,
            )
        )
    fixed_pack = pack_arm("either_wm_fixed", "ref", fixed_trades)
    write_trades_csv(out_dir / "Closed_either_wm_fixed_ref.csv", fixed_trades)
    print(
        f"  either_wm_fixed: N={len(fixed_trades)} "
        f"IS={fixed_pack['is']['n']} OOS={fixed_pack['oos']['n']}"
    )

    ctrl = next(a for a in packed if a["role"] == "control")
    for a in packed:
        if a["role"] == "control":
            continue
        verd, note = verdict_vs_control(ctrl["is"], a["is"], ctrl["oos"], a["oos"], a["name"])
        a["verd"] = verd
        a["note"] = note

    sys_verd, sys_note = system_verdict(ctrl)

    write_baseline(out_dir / "BASELINE.md", univ, ctrl_trail=ctrl, ctrl_fixed=fixed_pack)
    write_ab_plan(out_dir / "AB_PLAN.md")
    write_summary(out_dir / "SUMMARY.md", univ, packed, sys_verd, sys_note)
    write_html(out_dir / "compare.html", univ, packed, sys_verd, sys_note)

    print(f"SYSTEM: {sys_verd} — {sys_note}")
    for a in packed:
        if a["role"] != "control":
            print(f"  {a['name']}: {a['verd']} — {a['note']}")
    print(f"wrote {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
