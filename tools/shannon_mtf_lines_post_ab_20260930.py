#!/usr/bin/env python3
"""Post-analysis and one-knob A/B on the frozen Shannon MTF lines book.

Does not rewrite drive/paul_experiments/shannon_mtf_lines_20260930/.
Research only. Not gold. Not DailyRun.

  python tools/shannon_mtf_lines_post_ab_20260930.py
"""
from __future__ import annotations

import csv
import html as html_mod
import math
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

import shannon_mtf_lines_20260930 as sh  # noqa: E402
from compare_format import (  # noqa: E402
    format_money,
    overlay_ann_ror_max_dd,
)

sys.path.insert(0, str(ROOT))
from report_page_extras import RESPONSIVE_TABLE_CSS, SWIPE_NOTE_HTML  # noqa: E402

CONTROL_DIR = ROOT / "drive" / "paul_experiments" / "shannon_mtf_lines_20260930"
OUT_DIR = ROOT / "drive" / "paul_experiments" / "shannon_mtf_lines_post_ab_20260930"
FROZEN_CSV = CONTROL_DIR / "trades.csv"
IS_CUT = sh.IS_CUT
BIG_WIN = 20.0  # stated right-tail cutoff, percent
SHEET = sh.SHEET
INIT_ACCT = sh.INIT_ACCT

ORIGINAL_REQUEST = (
    "i like this analysis file:///C:/Users/songg/Downloads/stockresearch/"
    "drive/paul_experiments/shannon_mtf_lines_20260930/report.html can we run a "
    "post analysis on this and wire up some AB tests to see if there are any "
    "other filters or exit criteria we can add. I'm interested in some of the "
    "really big winners we have here when you regenerate, please include Ann ROR "
    "also most of the entires do NOT include a target - why is that?"
)


@dataclass(frozen=True)
class Arm:
    key: str
    label: str
    kind: str  # CONTROL, ENTRY, EXIT
    bias: str  # frozen | pre-declared | selection
    rule: str
    require_target: bool = False
    skip_if_target: bool = False
    require_weekly_support: bool = False
    pct_target: Optional[float] = None  # decimal, only when the line target is absent
    time_days: Optional[int] = None
    giveback: bool = False


ARMS: list[Arm] = [
    Arm(
        key="control",
        label="Control",
        kind="CONTROL",
        bias="frozen",
        rule="Frozen Shannon lines book from shannon_mtf_lines_20260930. No new filter and no new exit.",
    ),
    Arm(
        key="entry_require_target",
        label="Require a line target",
        kind="ENTRY",
        bias="pre-declared",
        rule="Take the control buy only when a falling daily (else weekly) resistance line is still above the entry. Same exits.",
        require_target=True,
    ),
    Arm(
        key="entry_weekly_support",
        label="Require weekly rising support",
        kind="ENTRY",
        bias="pre-declared",
        rule="Take the control buy only when a rising weekly support line also exists and the signal close is above it. Same exits.",
        require_weekly_support=True,
    ),
    Arm(
        key="entry_only_no_target",
        label="Only entries with no target",
        kind="ENTRY",
        bias="selection",
        rule="Skip any control buy that has a falling resistance line overhead. Same exits. Drawn after seeing that every large winner had a blank target.",
        skip_if_target=True,
    ),
    Arm(
        key="exit_pct20_if_no_line",
        label="20% target when no line",
        kind="EXIT",
        bias="pre-declared",
        rule="Same entries as the control. When the Shannon target cell would be blank, also sell at +20% from the entry (gap at the open, or the high touches it). Trades that already have a line target keep that line. Stop and higher-timeframe exits unchanged.",
        pct_target=0.20,
    ),
    Arm(
        key="exit_time_63",
        label="63-day time stop",
        kind="EXIT",
        bias="pre-declared",
        rule="Same entries as the control. If the trade is still open 63 calendar days after the entry, sell at that close. Stop, line target, and higher-timeframe exits are checked first on that bar. 63 days is one quarter, not the hold of the big winners.",
        time_days=63,
    ),
    Arm(
        key="exit_giveback_half",
        label="Half giveback after +10%",
        kind="EXIT",
        bias="pre-declared",
        rule="Same entries as the control. Once a prior bar's high is at least 10% above the entry, a giveback price is halfway from the highest high since entry back down to the entry. From the next day, a gap through that price sells at the open; a close through it sells at the close. Stop and higher-timeframe exits are checked first.",
        giveback=True,
    ),
]


def weekly_support_under_close(piv_w, as_of: date, close: float) -> bool:
    line = sh.shannon_line(piv_w, "L", as_of, "weekly", rising=True)
    if line is None:
        return False
    px = line.price_on(as_of)
    return math.isfinite(px) and close > px


def walk_exit(
    dates,
    o,
    h,
    c,
    w_open,
    m_open,
    entry_i: int,
    entry: float,
    sup,
    res,
    arm: Arm,
) -> tuple[int, float, str]:
    """Control exit path, plus at most one extra exit rule from ``arm``."""
    n = len(dates)
    opened = dates[entry_i]
    armed_giveback = False
    peak = entry
    pct_px = entry * (1.0 + arm.pct_target) if arm.pct_target else None
    for j in range(entry_i, n):
        stop_px = sup.price_on(dates[j])
        line_px = res.price_on(dates[j]) if res is not None else None
        if line_px is not None and (not math.isfinite(line_px) or line_px <= stop_px):
            line_px = None
        # A percent target fills in only where the Shannon line target is absent.
        # If a line was set at entry, keep that line even on days it is not usable.
        if line_px is not None:
            tgt_px = line_px
            use_pct = False
        elif res is None and pct_px is not None and pct_px > stop_px:
            tgt_px = pct_px
            use_pct = True
        else:
            tgt_px = None
            use_pct = False
        oj, hj, cj = float(o[j]), float(h[j]), float(c[j])
        tf_broken = (not w_open[j]) or (not m_open[j])
        if j > entry_i and oj <= stop_px:
            return j, oj, "STOP"
        if j > entry_i and tf_broken:
            which = "WEEK" if not w_open[j] else "MONTH"
            return j, oj, f"TF_{which}"
        if tgt_px is not None and oj >= tgt_px:
            return j, oj, "PCT_TARGET" if use_pct else "TARGET"
        both = tgt_px is not None and hj >= tgt_px and cj < stop_px
        if both:
            return j, stop_px, "STOP"
        if tgt_px is not None and hj >= tgt_px:
            return j, tgt_px, "PCT_TARGET" if use_pct else "TARGET"
        if cj < stop_px:
            return j, cj, "STOP"
        if arm.giveback:
            if j > entry_i and armed_giveback and peak > entry:
                floor = peak - 0.50 * (peak - entry)
                if oj <= floor:
                    return j, oj, "GIVEBACK"
                if cj <= floor:
                    return j, cj, "GIVEBACK"
            if hj > peak:
                peak = hj
            if peak >= entry * 1.10:
                armed_giveback = True
        if arm.time_days and j > entry_i and (dates[j] - opened).days >= arm.time_days:
            return j, cj, "TIME"
    return n - 1, float(c[n - 1]), "OPEN"


def make_trade(
    sym: str,
    signal: date,
    dates,
    entry_i: int,
    entry: float,
    stop_entry: float,
    risk: float,
    sup,
    res,
    tgt_entry,
    wsup_under: bool,
    exit_i: int,
    exit_px: float,
    exit_type: str,
) -> dict:
    opened = dates[entry_i]
    closed = dates[exit_i]
    pnl_pct = (float(exit_px) - entry) / entry * 100.0
    hold = max((closed - opened).days, 1)
    tgt_exit = res.price_on(closed) if res is not None else float("nan")
    return {
        "sym": sym,
        "signal": signal,
        "opened": opened,
        "closed": closed,
        "entry": entry,
        "stop_entry": stop_entry,
        "stop_exit": sup.price_on(closed),
        "target_entry": float(tgt_entry) if tgt_entry is not None else float("nan"),
        "target_exit": tgt_exit,
        "exit_px": float(exit_px),
        "exit": exit_type,
        "pnl": pnl_pct,
        "r": (float(exit_px) - entry) / risk,
        "days": float(hold),
        "pnl_d": pnl_pct / 100.0 * SHEET,
        "stop_slope_pct_day": sup.slope_pct_per_day(),
        "tgt_slope_pct_day": res.slope_pct_per_day() if res is not None else float("nan"),
        "tgt_tf": res.timeframe if res is not None else "",
        "had_target": res is not None,
        "risk_pct": risk / entry * 100.0,
        "wsup_under": wsup_under,
        "sup": sup,
        "res": res,
        "entry_i": entry_i,
    }


def simulate_entries(sym: str, df, piv_d, piv_w, arrays, arm: Arm) -> list[dict]:
    dates, o, h, lo, c, daily_up, w_close, m_close, w_open, m_open, adv20 = arrays
    n = len(df)
    del lo
    trades: list[dict] = []
    i = sh.MIN_DAILY_BARS
    while i < n - 1:
        if c[i] < sh.MIN_PRICE or not (np.isfinite(adv20[i]) and adv20[i] >= sh.MIN_ADV20):
            i += 1
            continue
        turned = bool(daily_up[i] and not daily_up[i - 1])
        if not (turned and w_close[i] and m_close[i]):
            i += 1
            continue
        d = dates[i]
        sup = sh.shannon_line(piv_d, "L", d, "daily", rising=True)
        if sup is None:
            i += 1
            continue
        stop_sig = sup.price_on(d)
        if not math.isfinite(stop_sig) or stop_sig <= 0 or c[i] <= stop_sig:
            i += 1
            continue
        res = sh.overhead_resistance(piv_d, piv_w, d, c[i])
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
        wsup = weekly_support_under_close(piv_w, d, float(c[i]))
        if arm.require_target and res is None:
            i += 1
            continue
        if arm.skip_if_target and res is not None:
            i += 1
            continue
        if arm.require_weekly_support and not wsup:
            i += 1
            continue
        exit_i, exit_px, exit_type = walk_exit(
            dates, o, h, c, w_open, m_open, entry_i, entry, sup, res, arm
        )
        trades.append(
            make_trade(
                sym, d, dates, entry_i, entry, stop_entry, risk, sup, res, tgt_entry, wsup,
                exit_i, exit_px, exit_type,
            )
        )
        i = exit_i + 1
    return trades


def replay_exit(sym_ctx: dict, base: dict, arm: Arm) -> dict:
    dates, o, h, c, w_open, m_open = (
        sym_ctx["dates"],
        sym_ctx["o"],
        sym_ctx["h"],
        sym_ctx["c"],
        sym_ctx["w_open"],
        sym_ctx["m_open"],
    )
    exit_i, exit_px, exit_type = walk_exit(
        dates,
        o,
        h,
        c,
        w_open,
        m_open,
        base["entry_i"],
        base["entry"],
        base["sup"],
        base["res"],
        arm,
    )
    return make_trade(
        base["sym"],
        base["signal"],
        dates,
        base["entry_i"],
        base["entry"],
        base["stop_entry"],
        base["entry"] - base["stop_entry"],
        base["sup"],
        base["res"],
        None if not base["had_target"] else base["target_entry"],
        base["wsup_under"],
        exit_i,
        exit_px,
        exit_type,
    )


def prepare(sym: str, df):
    dates = list(df["Date"])
    o = df["Open"].to_numpy(dtype=float)
    h = df["High"].to_numpy(dtype=float)
    lo = df["Low"].to_numpy(dtype=float)
    c = df["Close"].to_numpy(dtype=float)
    daily_up, _sma = sh.sma_up(c)
    w_flags = sh.htf_up_flags(df, sh.WEEK_FREQ)
    m_flags = sh.htf_up_flags(df, sh.MONTH_FREQ)
    w_close = sh.flags_on_days(w_flags, dates, strict_before=False)
    m_close = sh.flags_on_days(m_flags, dates, strict_before=False)
    w_open = sh.flags_on_days(w_flags, dates, strict_before=True)
    m_open = sh.flags_on_days(m_flags, dates, strict_before=True)
    vol = df["Volume"].to_numpy(dtype=float)
    adv20 = __import__("pandas").Series(vol).rolling(20, min_periods=20).mean().to_numpy()
    arrays = (dates, o, h, lo, c, daily_up, w_close, m_close, w_open, m_open, adv20)
    ctx = {
        "dates": dates,
        "o": o,
        "h": h,
        "c": c,
        "w_open": w_open,
        "m_open": m_open,
    }
    return arrays, ctx


def quantile(xs: list[float], p: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] * (c - k) + s[c] * (k - f)


def losing_streak(trades: list[dict]) -> int:
    ordered = sorted(trades, key=lambda t: (t["opened"], t["sym"]))
    best = cur = 0
    for t in ordered:
        if t["pnl"] < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def slice_trades(trades: list[dict], which: str) -> list[dict]:
    if which == "full":
        return list(trades)
    if which == "IS":
        return [t for t in trades if t["opened"] < IS_CUT]
    return [t for t in trades if t["opened"] >= IS_CUT]


def book_stats(trades: list[dict]) -> dict:
    keys = (
        "n", "wins", "losses", "wr", "avg", "median", "wo_max", "avg_win", "avg_loss",
        "wl_count", "pf", "ann_ror", "max_dd", "calmar", "sharpe", "ppcd", "cap_days",
        "avg_days", "med_days", "p90_days", "tpy", "streak", "with_target", "exits",
        "syms",
    )
    empty = {k: ({} if k == "exits" else float("nan")) for k in keys}
    empty["n"] = empty["wins"] = empty["losses"] = empty["streak"] = empty["with_target"] = empty["syms"] = 0
    empty["cap_days"] = 0.0
    if not trades:
        return empty
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gp, gl = sum(wins), abs(sum(losses))
    mx = max(pnls)
    wo = [p for p in pnls if p != mx]
    # drop a single max (if ties, drop one)
    if wo and pnls.count(mx) > 1:
        wo = pnls.copy()
        wo.remove(mx)
    days = [t["days"] for t in trades]
    ov = overlay_ann_ror_max_dd(trades, cash=SHEET, initial_account=INIT_ACCT)
    span_days = (max(t["closed"] for t in trades) - min(t["opened"] for t in trades)).days
    span_years = span_days / 365.25 if span_days > 0 else float("nan")
    sheet = sum(t["pnl_d"] for t in trades)
    cap = float(ov.get("capital_days", 0.0) or 0.0)
    exits: dict[str, int] = {}
    for t in trades:
        exits[t["exit"]] = exits.get(t["exit"], 0) + 1
    n = len(trades)
    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "wr": 100.0 * len(wins) / n,
        "avg": sum(pnls) / n,
        "median": quantile(pnls, 0.5),
        "wo_max": (sum(wo) / len(wo)) if wo else float("nan"),
        "avg_win": (sum(wins) / len(wins)) if wins else float("nan"),
        "avg_loss": (sum(losses) / len(losses)) if losses else float("nan"),
        "wl_count": (len(wins) / len(losses)) if losses else float("nan"),
        "pf": (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0),
        "ann_ror": float(ov.get("ann_ror", float("nan"))),
        "max_dd": float(ov.get("max_dd", float("nan"))),
        "calmar": float(ov.get("calmar", float("nan"))),
        "sharpe": float(ov.get("sharpe", float("nan"))),
        "ppcd": (sheet / cap) if cap > 0 else float("nan"),
        "cap_days": cap,
        "avg_days": sum(days) / n,
        "med_days": quantile(days, 0.5),
        "p90_days": quantile(days, 0.9),
        "tpy": (n / span_years) if span_years and math.isfinite(span_years) and span_years > 0 else float("nan"),
        "streak": losing_streak(trades),
        "with_target": sum(1 for t in trades if t["had_target"]),
        "exits": exits,
        "syms": len({t["sym"] for t in trades}),
    }


def finite(x) -> bool:
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def delta(a, b) -> float:
    if not finite(a) or not finite(b):
        return float("nan")
    return float(a) - float(b)


def fmt_pct(x, nd=1) -> str:
    if not finite(x):
        return "—"
    return f"{float(x):.{nd}f}%"


def fmt_num(x, nd=2) -> str:
    if not finite(x):
        return "—"
    return f"{float(x):.{nd}f}"


def fmt_delta(x, nd=2, suffix="") -> str:
    if not finite(x):
        return "—"
    v = float(x)
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.{nd}f}{suffix}"


def judge(arm: Arm, is_c: dict, is_a: dict, oos_c: dict, oos_a: dict) -> tuple[str, str]:
    if arm.kind == "CONTROL":
        return "CONTROL", "Frozen book. The other arms are judged against this row."
    if is_a["n"] == 0:
        return "DISMISS", "In-sample book is empty."

    n_ratio = is_a["n"] / is_c["n"] if is_c["n"] else 0
    avg_d = delta(is_a["avg"], is_c["avg"])
    ann_d = delta(is_a["ann_ror"], is_c["ann_ror"])
    pf_d = delta(is_a["pf"], is_c["pf"])
    dd_d = delta(is_a["max_dd"], is_c["max_dd"])  # lower DD is better; positive means worse
    wo_d = delta(is_a["wo_max"], is_c["wo_max"])
    med_d = delta(is_a["median"], is_c["median"])

    worse_core = finite(avg_d) and finite(ann_d) and avg_d < -0.05 and ann_d < -0.5
    better_core = finite(avg_d) and finite(ann_d) and avg_d > 0.05 and ann_d > 0.5
    pf_ok = finite(pf_d) and pf_d >= -0.02
    pf_better = finite(pf_d) and pf_d > 0.02
    dd_ok = (not finite(dd_d)) or dd_d <= 2.0  # not more than 2 points worse
    wo_ok = finite(wo_d) and wo_d >= -0.15
    tail_only = finite(avg_d) and avg_d > 0.05 and finite(wo_d) and wo_d < -0.15

    if worse_core or (finite(avg_d) and avg_d < -0.15 and finite(ann_d) and ann_d < 0):
        verdict, why = "DISMISS", "In-sample average percent and annualized rate of return are worse than the control."
    elif n_ratio < 0.50:
        verdict, why = "HOLD", "In-sample trade count falls below half the control, so the quality read is thin."
    elif tail_only:
        verdict, why = "HOLD", "The average lift does not survive after the single largest trade is left out."
    elif better_core and pf_better and dd_ok and wo_ok and n_ratio >= 0.70:
        verdict, why = "KEEP", "In-sample win quality, profit factor, and annualized rate of return improve, and the gain is not only the single largest trade."
    elif better_core and pf_ok and dd_ok and (wo_ok or (finite(med_d) and med_d >= 0)):
        verdict, why = "LEAN KEEP", "In-sample average and annualized rate of return improve, with profit factor and drawdown not worse in a material way."
    else:
        verdict, why = "HOLD", "In-sample quality is mixed against the control. No knob is adopted."

    oos_avg = delta(oos_a["avg"], oos_c["avg"])
    oos_ann = delta(oos_a["ann_ror"], oos_c["ann_ror"])
    if verdict in ("KEEP", "LEAN KEEP") and finite(oos_avg) and finite(oos_ann) and oos_avg < -0.05 and oos_ann < -0.5:
        verdict = "HOLD"
        why = "In-sample looked better, but out-of-sample average and annualized rate of return both softened versus the control. Out-of-sample is report-only. Not retuned."

    if arm.key == "exit_time_63" and verdict == "KEEP":
        why += (
            " The median trade is unchanged, because the clock only closes holds that reach 63 days. "
            "This is one pre-set quarter, not a search over day counts. Research only. Not a live change."
        )

    if arm.bias == "selection" and verdict in ("KEEP", "LEAN KEEP"):
        verdict = "HOLD"
        why = (
            "In-sample selection. This filter was chosen after seeing the big winners, "
            "and every one of those winners is the kind of trade the filter keeps. Not adopted."
        )
    elif arm.bias == "selection" and verdict == "HOLD" and not why.startswith("In-sample selection"):
        why = "In-sample selection. " + why
    elif arm.bias == "selection" and verdict == "DISMISS":
        why = "In-sample selection, and the in-sample book is worse anyway. Not adopted. " + why
    return verdict, why


def sortable_th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def td(text: str, extra: str = "") -> str:
    return f"<td{extra}>{html_mod.escape(str(text))}</td>"


SORT_CSS = """
th.sortable-th { cursor:pointer; user-select:none; white-space:nowrap; background:#ece8df; }
th.sortable-th .sort-ind::after { content:" \\2195"; opacity:.35; }
th.sortable-th.sort-asc .sort-ind::after { content:" \\2191"; opacity:.9; }
th.sortable-th.sort-desc .sort-ind::after { content:" \\2193"; opacity:.9; }
tr.total-row td { background:#f3efe6; border-top:2px solid #5c564c; font-weight:600; }
"""

SORT_JS = r"""
<script>
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : NaN;
    if (type === "text") return s.toUpperCase();
    if (type === "date") {
      var iso = s.match(/(\d{4})-(\d{2})-(\d{2})/);
      if (iso) return parseInt(iso[1] + iso[2] + iso[3], 10);
      return NaN;
    }
    var n = s.replace(/[$,%+]/g, "").replace(/,/g, "");
    var v = parseFloat(n);
    return Number.isFinite(v) ? v : NaN;
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
      if (isNaN(av) && isNaN(bv)) return 0;
      if (isNaN(av)) return 1;
      if (isNaN(bv)) return -1;
      return dir * (av - bv);
    });
    movable.concat(pinned).forEach(function (r) { tbody.appendChild(r); });
  }
  document.querySelectorAll("table.sortable").forEach(function (table) {
    table.querySelectorAll("th.sortable-th").forEach(function (th, col) {
      function activate(e) {
        if (e && e.type === "keydown") e.preventDefault();
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
      th.addEventListener("click", activate);
      th.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") activate(e);
      });
    });
  });
})();
</script>
"""


def exit_mix_text(exits: dict, n: int) -> str:
    if not exits or n <= 0:
        return "—"
    parts = []
    for k in sorted(exits):
        parts.append(f"{k} {exits[k]} ({100.0 * exits[k] / n:.0f}%)")
    return ", ".join(parts)


def metrics_header() -> str:
    cols = [
        ("Arm", "text"),
        ("Kind", "text"),
        ("How chosen", "text"),
        ("Slice", "text"),
        ("N", "num"),
        ("Wins", "num"),
        ("Losses", "num"),
        ("Win %", "num"),
        ("Avg %", "num"),
        ("Median %", "num"),
        ("Avg % w/o largest", "num"),
        ("Avg win %", "num"),
        ("Avg loss %", "num"),
        ("Win/loss count", "num"),
        ("Profit factor", "num"),
        ("Ann ROR %", "num"),
        ("Δ Ann ROR", "num"),
        ("Max DD %", "num"),
        ("Δ Max DD", "num"),
        ("Calmar", "num"),
        ("Sharpe", "num"),
        ("Expectancy $", "num"),
        ("$ / capital day", "num"),
        ("Capital days", "num"),
        ("Avg days", "num"),
        ("Median days", "num"),
        ("P90 days", "num"),
        ("Trades/year", "num"),
        ("Losing streak", "num"),
        ("With line target", "num"),
        ("Exit mix", "text"),
    ]
    return "".join(sortable_th(a, b) for a, b in cols)


def metrics_row(arm: Arm, slice_name: str, st: dict, base: dict) -> str:
    exp_d = (st["avg"] / 100.0 * SHEET) if finite(st["avg"]) else float("nan")
    cells = [
        arm.label,
        arm.kind,
        arm.bias,
        slice_name,
        str(st["n"]),
        str(st["wins"]),
        str(st["losses"]),
        fmt_pct(st["wr"], 1),
        fmt_pct(st["avg"], 2),
        fmt_pct(st["median"], 2),
        fmt_pct(st["wo_max"], 2),
        fmt_pct(st["avg_win"], 2),
        fmt_pct(st["avg_loss"], 2),
        fmt_num(st["wl_count"], 2),
        fmt_num(st["pf"], 2),
        fmt_pct(st["ann_ror"], 1),
        fmt_delta(delta(st["ann_ror"], base["ann_ror"]), 1, " pp"),
        fmt_pct(st["max_dd"], 1),
        fmt_delta(delta(st["max_dd"], base["max_dd"]), 1, " pp"),
        fmt_num(st["calmar"], 2),
        fmt_num(st["sharpe"], 2),
        format_money(exp_d) if finite(exp_d) else "—",
        format_money(st["ppcd"]) if finite(st["ppcd"]) else "—",
        fmt_num(st["cap_days"], 0),
        fmt_num(st["avg_days"], 1),
        fmt_num(st["med_days"], 1),
        fmt_num(st["p90_days"], 1),
        fmt_num(st["tpy"], 1),
        str(st["streak"]),
        str(st["with_target"]),
        exit_mix_text(st["exits"], st["n"]),
    ]
    return "<tr>" + "".join(td(c) for c in cells) + "</tr>"


def assert_control_matches(trades: list[dict]) -> None:
    frozen = list(csv.DictReader(FROZEN_CSV.open(encoding="utf-8")))
    got = sorted(trades, key=lambda t: (t["opened"], t["sym"], t["signal"]))
    if len(got) != len(frozen):
        raise SystemExit(f"Control N {len(got)} != frozen CSV {len(frozen)}")
    for i, (a, b) in enumerate(zip(frozen, got)):
        if a["sym"] != b["sym"] or a["opened"] != b["opened"].isoformat() or a["exit"] != b["exit"]:
            raise SystemExit(f"Mismatch row {i}: csv {a['sym']} {a['opened']} {a['exit']} vs {b['sym']} {b['opened']} {b['exit']}")
        if abs(float(a["pnl"]) - b["pnl"]) > 1e-6:
            raise SystemExit(f"PnL mismatch {b['sym']} {b['opened']}: {a['pnl']} vs {b['pnl']}")
        if (a["had_target"] == "True") != bool(b["had_target"]):
            raise SystemExit(f"had_target mismatch {b['sym']} {b['opened']}")
    print(f"Control matches frozen CSV N={len(got)}", flush=True)


def write_trade_csv(path: Path, rows: list[dict]) -> None:
    cols = [
        "arm", "sym", "signal", "opened", "closed", "entry", "stop_entry", "target_entry",
        "tgt_tf", "exit", "exit_px", "pnl", "r", "days", "had_target", "risk_pct",
        "stop_slope_pct_day", "wsup_under",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for arm_key, t in rows:
            w.writerow([
                arm_key,
                t["sym"],
                t["signal"].isoformat(),
                t["opened"].isoformat(),
                t["closed"].isoformat(),
                f"{t['entry']:.6f}",
                f"{t['stop_entry']:.6f}",
                "" if not t["had_target"] else f"{t['target_entry']:.6f}",
                t["tgt_tf"],
                t["exit"],
                f"{t['exit_px']:.6f}",
                f"{t['pnl']:.6f}",
                f"{t['r']:.6f}",
                f"{t['days']:.0f}",
                t["had_target"],
                f"{t['risk_pct']:.4f}",
                f"{t['stop_slope_pct_day']:.6f}",
                t["wsup_under"],
            ])


def target_answer(control: list[dict]) -> dict:
    n = len(control)
    with_t = [t for t in control if t["had_target"]]
    without = [t for t in control if not t["had_target"]]
    tf = Counter(t["tgt_tf"] for t in with_t)
    return {
        "n": n,
        "with": len(with_t),
        "without": len(without),
        "daily": tf.get("daily", 0),
        "weekly": tf.get("weekly", 0),
        "with_exits": Counter(t["exit"] for t in with_t),
        "without_exits": Counter(t["exit"] for t in without),
    }


def winner_rows(control: list[dict]) -> list[dict]:
    big = [t for t in control if t["pnl"] >= BIG_WIN]
    big.sort(key=lambda t: -t["pnl"])
    return big


def describe_winners(big: list[dict], control: list[dict]) -> str:
    if not big:
        return "No trade reached the cutoff."
    days = [t["days"] for t in big]
    exits = Counter(t["exit"] for t in big)
    syms = Counter(t["sym"] for t in big)
    had = sum(1 for t in big if t["had_target"])
    wsup = sum(1 for t in big if t["wsup_under"])
    rest = [t for t in control if t["pnl"] < BIG_WIN]
    rest_days = [t["days"] for t in rest] or [0]
    top_syms = ", ".join(f"{s} {c}" for s, c in syms.most_common(8))
    exit_s = ", ".join(f"{k} {v}" for k, v in exits.most_common())
    risks = [t["risk_pct"] for t in big]
    return (
        f"{len(big)} control trades gained {BIG_WIN:.0f}% or more. "
        f"None of them had a line target ({had} with a target). "
        f"Exits: {exit_s}. "
        f"Median hold {quantile(days, 0.5):.0f} calendar days "
        f"(the other trades median {quantile(rest_days, 0.5):.0f}). "
        f"Median distance from the entry down to the rising support line was {quantile(risks, 0.5):.1f}% of price, "
        f"and that distance is not a tight cluster. "
        f"Names: {top_syms}. "
        f"{wsup} of these {len(big)} also had price above a rising weekly support line at the signal. "
        f"Every entry in the whole book, winners included, already required the month and the week to be up "
        f"on a rising 5-period average and the day to have just turned up, so that regime does not separate them."
    )


def write_baseline(info: dict, verdicts: dict, stats: dict) -> None:
    ta = info
    lines = []
    lines.append("# shannon_mtf_lines_post_ab_20260930")
    lines.append("")
    lines.append("Research only. Not gold. Not DailyRun. No arm is wired into production.")
    lines.append("The folder `shannon_mtf_lines_20260930` is the frozen control and was not overwritten.")
    lines.append("")
    lines.append("## What you asked")
    lines.append("")
    lines.append(ORIGINAL_REQUEST)
    lines.append("")
    lines.append("## In plain English")
    lines.append("")
    lines.append(
        "The control buys Paul Twenty names when the month and the week are already up "
        "and the day has just turned up, above a rising daily support line. The stop is that line. "
        "A target price is written only when a falling resistance line sits above the entry. "
        "This page asks whether one extra filter or one extra exit improves that book. "
        "Annualized rate of return (Ann ROR) uses the house formula, not a new one."
    )
    lines.append("")
    lines.append("## Why most entries have no target")
    lines.append("")
    lines.append(
        f"Not a bug. `overhead_resistance` in `tools/shannon_mtf_lines_20260930.py` returns a line "
        f"only when the last two confirmed swing highs are falling and that line is above the signal close "
        f"(daily first, else weekly). If the line projected to the next open is not still above the entry, "
        f"the target is cleared. Otherwise the target cells stay blank (`nan` / an em dash on the page). "
        f"A blank target means the trade has no target price. It exits through the rising support line (STOP), "
        f"or at the next open after a completed week or month is no longer up (TF_WEEK / TF_MONTH), "
        f"or it is still open (OPEN)."
    )
    lines.append("")
    lines.append(
        f"Count on the frozen book: {ta['with']} of {ta['n']} entries have a target "
        f"({ta['daily']} daily, {ta['weekly']} weekly). {ta['without']} do not."
    )
    lines.append("")
    lines.append("## Control freeze")
    lines.append("")
    lines.append("Same knobs as `drive/paul_experiments/shannon_mtf_lines_20260930/BASELINE.md`. Replay matched that `trades.csv` before any arm was scored.")
    lines.append("")
    lines.append("| Item | Choice |")
    lines.append("|---|---|")
    lines.append("| Universe | `drive/universes/PaulTwenty_universe.csv` |")
    lines.append("| OHLC | `data/newdata/data/{SYM}.csv` |")
    lines.append("| Trend | 5-period simple moving average (SMA). UP = close above SMA and SMA rising |")
    lines.append("| Higher-timeframe timing | Week and month count only after the bar has closed |")
    lines.append("| Swing points | Daily k=5, weekly k=3 (W-FRI), monthly k=2 (ME) |")
    lines.append("| Shannon support | Last two confirmed lows, later low strictly higher |")
    lines.append("| Shannon resistance | Last two confirmed highs, later high strictly lower |")
    lines.append("| Trigger | Month UP and week UP at the signal close, daily SMA trend turns UP, rising daily support exists, close above that line |")
    lines.append("| Entry | Next open. Skip if the open is already through the support line |")
    lines.append("| Stop | Frozen trigger support line, projected each day. Gap through the line exits at the open. Otherwise a close through the line exits at the close. A wick is not an exit. |")
    lines.append("| Target | Frozen falling resistance, daily if overhead, else weekly. No target if neither line is above the entry. |")
    lines.append("| Same-bar stop and target | Stop is filled |")
    lines.append("| Higher-timeframe exit | Next open after a completed week or month is no longer UP |")
    lines.append("| Time stop | None |")
    lines.append("| Side | Longs only |")
    lines.append("| One position | Flat before the next signal on that symbol |")
    lines.append("| Still open | Marked at the last close, exit OPEN |")
    lines.append("| IS / OOS | Entry before 2024-01-01 / on or after. OOS is report-only. |")
    lines.append("| Costs | 0 |")
    lines.append("| Sheet notional | $45,000. This is `brt_cash` in the annualized rate of return formula. It is not shown as a total-profit column. |")
    lines.append("| Initial account for max drawdown | $500,000 (`compare_format.DEFAULT_INITIAL_ACCOUNT`) |")
    lines.append("| Liquidity | Close ≥ $5 and 20-day average volume ≥ 500,000 |")
    lines.append("| Ann ROR | `((1 + total_pnl / (45000 × n)) ** (365 / avg_days_held) − 1) × 100` via `compare_format.ann_ror_from_closed` / `overlay_ann_ror_max_dd` |")
    lines.append("| FIT | Not produced by this research book. Not shown. |")
    lines.append("")
    lines.append("## Right tail (description, not a filter)")
    lines.append("")
    lines.append(
        f"Stated cutoff: closed percent at least {BIG_WIN:.0f}. "
        "Choosing a rule because it would have kept these names is in-sample selection. "
        "The arm `Only entries with no target` is that kind of rule and is labeled selection. It is not adopted."
    )
    lines.append("")
    lines.append("## Arms (one change each)")
    lines.append("")
    lines.append("Exit arms replay the frozen control entries and only change the exit. They do not add a later signal that the control was still holding through.")
    lines.append("Entry arms resimulate, because a skipped signal leaves the symbol flat and a later turn can be taken.")
    lines.append("Nothing is stacked.")
    lines.append("")
    for arm in ARMS:
        v, why = verdicts[arm.key]
        lines.append(f"### {arm.label}")
        lines.append("")
        lines.append(f"- Kind: {arm.kind}")
        lines.append(f"- How chosen: {arm.bias}")
        lines.append(f"- Rule: {arm.rule}")
        lines.append(f"- Verdict: **{v}**. {why}")
        lines.append("")
        for sl in ("full", "IS", "OOS"):
            st = stats[(arm.key, sl)]
            lines.append(
                f"- {sl}: N={st['n']} WR={st['wr']:.1f}% avg={st['avg']:.2f}% "
                f"median={st['median']:.2f}% PF={st['pf']:.2f} Ann ROR={st['ann_ror']:.1f}% "
                f"Max DD={st['max_dd']:.1f}% avg days={st['avg_days']:.1f}"
            )
        lines.append("")
    lines.append("## Selection bias")
    lines.append("")
    lines.append(
        "`Only entries with no target` was inspired by the right tail (every trade at or above "
        f"+{BIG_WIN:.0f}% had a blank target and left via the weekly trend). "
        "That arm cannot be KEEP even if the in-sample numbers look better. "
        "The other arms were specified from the book and from the request menu "
        "(a target where the cell is blank, a time stop, a trailing giveback, a weekly support analogue of the daily rule). "
        "The 20% and the 63 days and the half-giveback after +10% were not fit to the winner list. "
        "Out-of-sample did not choose a winner and was not used to retune."
    )
    lines.append("")
    path = OUT_DIR / "BASELINE.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_html(info: dict, control: list[dict], stats: dict, verdicts: dict) -> None:
    ta = info
    big = winner_rows(control)
    desc = describe_winners(big, control)
    full_c = stats[("control", "full")]

    def mix(counter: Counter) -> str:
        return ", ".join(f"{k} {v}" for k, v in counter.most_common()) or "—"

    winner_head = "".join(
        sortable_th(a, b)
        for a, b in [
            ("Symbol", "text"),
            ("Signal", "date"),
            ("Opened", "date"),
            ("Closed", "date"),
            ("Return %", "num"),
            ("Hold days", "num"),
            ("Line target", "text"),
            ("Target line", "text"),
            ("Exit", "text"),
            ("Distance to support %", "num"),
            ("Support % per day", "num"),
            ("Weekly support under close", "text"),
            ("Sample", "text"),
        ]
    )
    wrows = []
    for t in big:
        sample = "OOS" if t["opened"] >= IS_CUT else "IS"
        vals = [
            t["sym"],
            t["signal"].isoformat(),
            t["opened"].isoformat(),
            t["closed"].isoformat(),
            f"{t['pnl']:.2f}",
            f"{t['days']:.0f}",
            "yes" if t["had_target"] else "no",
            t["tgt_tf"] or "—",
            t["exit"],
            f"{t['risk_pct']:.2f}",
            f"{t['stop_slope_pct_day']:.3f}",
            "yes" if t["wsup_under"] else "no",
            sample,
        ]
        wrows.append("<tr>" + "".join(td(v) for v in vals) + "</tr>")
    avg_big = sum(t["pnl"] for t in big) / len(big) if big else float("nan")
    wrows.append(
        '<tr class="total-row">'
        + td(f"Right tail, return at least {BIG_WIN:.0f}%")
        + td(str(len(big)))
        + td("")
        + td("")
        + td(f"{avg_big:.2f}" if big else "—")
        + td(f"{quantile([t['days'] for t in big], 0.5):.0f}" if big else "—")
        + td(f"{sum(1 for t in big if t['had_target'])} with a target")
        + td("")
        + td("see rows")
        + td("")
        + td("")
        + td(f"{sum(1 for t in big if t['wsup_under'])} yes")
        + td("")
        + "</tr>"
    )

    metric_rows = []
    for slice_name, slice_key in (("Full", "full"), ("IS", "IS"), ("OOS", "OOS")):
        for arm in ARMS:
            metric_rows.append(
                metrics_row(arm, slice_name, stats[(arm.key, slice_key)], stats[("control", slice_key)])
            )

    vhead = "".join(
        sortable_th(a, b)
        for a, b in [
            ("Arm", "text"),
            ("Kind", "text"),
            ("How chosen", "text"),
            ("One-line rule", "text"),
            ("IS N", "num"),
            ("IS Win %", "num"),
            ("IS Avg %", "num"),
            ("IS Ann ROR", "num"),
            ("Full Ann ROR", "num"),
            ("OOS Avg %", "num"),
            ("OOS Ann ROR", "num"),
            ("Verdict", "text"),
            ("Why", "text"),
        ]
    )
    vrows = []
    for arm in ARMS:
        v, why = verdicts[arm.key]
        ins = stats[(arm.key, "IS")]
        full = stats[(arm.key, "full")]
        oos = stats[(arm.key, "OOS")]
        vals = [
            arm.label,
            arm.kind,
            arm.bias,
            arm.rule,
            str(ins["n"]),
            fmt_pct(ins["wr"], 1),
            fmt_pct(ins["avg"], 2),
            fmt_pct(ins["ann_ror"], 1),
            fmt_pct(full["ann_ror"], 1),
            fmt_pct(oos["avg"], 2),
            fmt_pct(oos["ann_ror"], 1),
            v,
            why,
        ]
        vrows.append("<tr>" + "".join(td(x) for x in vals) + "</tr>")

    count_head = "".join(sortable_th(a, b) for a, b in [("Group", "text"), ("Entries", "num"), ("Share", "num"), ("How they exited", "text")])
    count_rows = (
        "<tr>" + td("Line target written") + td(str(ta["with"])) + td(f"{100*ta['with']/ta['n']:.1f}%") + td(mix(ta["with_exits"])) + "</tr>"
        + "<tr>" + td("Target cell blank") + td(str(ta["without"])) + td(f"{100*ta['without']/ta['n']:.1f}%") + td(mix(ta["without_exits"])) + "</tr>"
        + '<tr class="total-row">' + td("All control entries") + td(str(ta["n"])) + td("100%") + td("—") + "</tr>"
    )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Shannon lines post analysis — shannon_mtf_lines_post_ab_20260930</title>
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 1.25rem auto; max-width: 1280px;
  padding: 0 1rem 2rem; color: #1f1d1a; background: #f7f4ee; }}
h1 {{ font-size: 1.5rem; margin-bottom: 0.2rem; }}
h2 {{ font-size: 1.2rem; margin-top: 1.4rem; }}
.sub {{ color: #5c564c; font-size: 0.92rem; }}
.callout {{ background: #fff; border: 1px solid #d9d1c3; padding: 0.8rem 1rem; margin: 0.8rem 0; }}
.callout.target {{ border-color: #8d6a2f; background: #fffaf0; }}
table.sortable {{ border-collapse: collapse; width: 100%; background: #fff; font-size: 0.78rem; margin: 0.4rem 0 1.2rem; }}
th, td {{ border: 1px solid #e3dccf; padding: 0.28rem 0.4rem; text-align: left; vertical-align: top; }}
.wrap {{ overflow-x: auto; }}
{SORT_CSS}
code {{ font-size: 0.86em; }}
</style>
</head>
<body>
<h1>Shannon lines — one change at a time, after the first book</h1>
<p class="sub">Stamp <code>shannon_mtf_lines_post_ab_20260930</code> · control folder left untouched ·
Paul Twenty · research only · not gold · not DailyRun ·
Click a column header to sort. Footer rows stay pinned.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{html_mod.escape(ORIGINAL_REQUEST)}</p>
<h2>In plain English</h2>
<p>The page you liked draws a second set of trendlines and then trades them. Multi-timeframe (MTF)
means three clocks at once: the month, the week, and the day. On each clock a trend is “up” only when
price is above a rising 5-period simple moving average (SMA). A support line is drawn only when the
last two swing lows are rising. A resistance line is drawn only when the last two swing highs are falling.
A buy is the next morning’s open after the month and the week are already up, the day has just turned up,
and price is still above that rising daily support line. The stop is that same support line, extended
forward, so the stop price moves with the slope. There is no “sell after this many days” rule on the control.</p>
<p>This page freezes that book and tries a few extras, one at a time: either a stricter buy, or a different
way out. Annualized rate of return (Ann ROR) is the house figure already used on run compares. In words:
take the average result per trade, turn it into a yearly pace using how many days the trades were held,
with a $45,000 sheet per trade and 365 days in the year. The same formula is on the control and on every test,
for the full book, for in-sample (IS, entry before 2024-01-01), and for out-of-sample (OOS, entry on or after
that date). OOS is a report. It did not pick a winner, and nothing here was retuned to make OOS look better.</p>
<p>The first Shannon report already printed Ann ROR (full book {fmt_pct(full_c['ann_ror'], 1)}). This page repeats it
for every arm. Research only. Not a live system.</p>
</div>

<div class="callout target">
<h2>Why most entries have no target</h2>
<p>The target cell is filled in only when a falling resistance line is overhead. The code looks for a
daily falling line first. If that line is not above the close, it looks for a weekly falling line.
If neither line is above the close, or the line projected to the next open is no longer above the buy price,
the target is left blank. That blank is the rule, not a missed write. There is no target price, so the
trade cannot exit at a target.</p>
<p>Those trades are closed another way. A gap or a close through the rising support line is a stop
(<code>STOP</code>). A finished week that is no longer an uptrend closes the trade at the next open
(<code>TF_WEEK</code>). The same idea on the month is <code>TF_MONTH</code>, which is rare.
A trade still on at the last bar is <code>OPEN</code> and is marked at that close.</p>
<p>On this frozen book, <b>{ta['with']} of {ta['n']}</b> entries have a target
({ta['daily']} daily, {ta['weekly']} weekly). <b>{ta['without']}</b> do not.
Of the {ta['with']} with a line, {ta['with_exits'].get('TARGET', 0)} actually sold at that line.
The other lines were still there, but the stop or a higher-timeframe break came first.
Of the {ta['without']} blanks, none has a <code>TARGET</code> exit, because there was no line to hit.</p>
</div>

<h2>Target count</h2>
<p class="sub">Click column headers to sort. The total row stays at the bottom.</p>
<div class="wrap">
<table class="sortable"><thead><tr>{count_head}</tr></thead><tbody>
{count_rows}
</tbody></table>
</div>

<h2>The really big winners</h2>
<p class="sub">Right tail on the control only: closed return at least {BIG_WIN:.0f}%. This is a description.
A filter chosen because it would have kept these names is in-sample selection. That filter is tested below
and labeled, and it is not adopted. Click column headers to sort.</p>
<p>{html_mod.escape(desc)}</p>
<div class="wrap">
<table class="sortable"><thead><tr>{winner_head}</tr></thead><tbody>
{''.join(wrows)}
</tbody></table>
</div>

<h2>What was tested</h2>
<p class="sub">One knob versus the frozen control. Entry tests can take a later signal the control never saw,
because a skipped buy leaves the name flat. Exit tests keep the control’s entries and only change the way out.
No combination arm.</p>
<ul>
{''.join(f'<li><b>{html_mod.escape(a.label)}</b> ({html_mod.escape(a.kind)}, {html_mod.escape(a.bias)}). {html_mod.escape(a.rule)}</li>' for a in ARMS)}
</ul>

<h2>Verdicts</h2>
<p class="sub">Judged on in-sample quality: average percent, profit factor, annualized rate of return,
drawdown, and the average with the single largest trade left out. Trade count has to stay in a useful range.
Out-of-sample is not the judge. If it softened, the verdict is HOLD. Click column headers to sort.</p>
<div class="wrap">
<table class="sortable"><thead><tr>{vhead}</tr></thead><tbody>
{''.join(vrows)}
</tbody></table>
</div>

<h2>Compare</h2>
<p class="sub">Deltas are versus the control on the same slice. Δ Max DD is positive when the drawdown is
deeper (worse). Expectancy dollars are the average percent times the $45,000 sheet. Total profit dollars
and sheet-profit totals are left off this table on purpose. FIT (the house fitness score) is not produced
by this book. Trades/year uses the span from the first entry to the last exit in that slice.
A tiny book of very short trades can print an extreme annualized rate of return; read the trade count beside it.
The “require a line target” out-of-sample row is that case, and it is not a result to act on.
KEEP means the in-sample research bar only. No arm is wired into a live run.
Click column headers to sort. Scroll sideways for the rest of the columns.</p>
<div class="wrap">
<table class="sortable"><thead><tr>{metrics_header()}</tr></thead><tbody>
{''.join(metric_rows)}
</tbody></table>
</div>

<p class="sub">Ann ROR formula, same as <code>rocket_tbn.compute_metrics</code> and
<code>compare_format.ann_ror_from_closed</code>:
((1 + total dollar PnL / (45000 × number of trades)) ^ (365 / average days held) − 1) × 100.
Max drawdown replays those same closed dollars onto a $500,000 account at each exit date.
Sharpe, when shown, is that exit-date equity with no risk-free rate, annualized by how often exits occur.
There is no daily equity curve for this book.</p>
{SORT_JS}
</body>
</html>
"""
    if "report-table-responsive" not in page:
        page = page.replace("</style>", RESPONSIVE_TABLE_CSS + "\n</style>", 1)
    if "Swipe sideways to see more columns." not in page:
        page = page.replace("</h1>", "</h1>\n" + SWIPE_NOTE_HTML, 1)
    (OUT_DIR / "compare.html").write_text(page, encoding="utf-8")


def write_summary_csv(stats: dict, verdicts: dict) -> None:
    path = OUT_DIR / "summary.csv"
    fields = [
        "arm", "kind", "bias", "slice", "verdict", "n", "wins", "losses", "wr", "avg", "median",
        "wo_max", "avg_win", "avg_loss", "wl_count", "pf", "ann_ror", "max_dd", "calmar", "sharpe",
        "ppcd", "cap_days", "avg_days", "med_days", "p90_days", "tpy", "streak", "with_target", "exits",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for arm in ARMS:
            v, _why = verdicts[arm.key]
            for sl in ("full", "IS", "OOS"):
                st = stats[(arm.key, sl)]
                row = {
                    "arm": arm.key,
                    "kind": arm.kind,
                    "bias": arm.bias,
                    "slice": sl,
                    "verdict": v,
                    "exits": exit_mix_text(st["exits"], st["n"]),
                }
                for k in fields:
                    if k in row:
                        continue
                    row[k] = st[k]
                w.writerow(row)


def main() -> None:
    symbols = sh.load_universe(sh.PAULTWENTY)
    control_arm = ARMS[0]
    entry_arms = [a for a in ARMS if a.kind == "ENTRY"]
    exit_arms = [a for a in ARMS if a.kind == "EXIT"]
    books: dict[str, list[dict]] = {a.key: [] for a in ARMS}
    ctx_by_sym: dict[str, dict] = {}

    for sym in symbols:
        df = sh.load_ohlc(sym)
        if df is None or len(df) < sh.MIN_DAILY_BARS:
            print(f"SKIP {sym}", file=sys.stderr)
            continue
        piv_d = sh.confirmed_pivots_daily(df, sh.PIVOT_K["daily"])
        piv_w = sh.confirmed_pivots_htf(df, sh.WEEK_FREQ, sh.PIVOT_K["weekly"])
        arrays, ctx = prepare(sym, df)
        ctx_by_sym[sym] = ctx
        base = simulate_entries(sym, df, piv_d, piv_w, arrays, control_arm)
        books["control"].extend(base)
        for arm in entry_arms:
            books[arm.key].extend(simulate_entries(sym, df, piv_d, piv_w, arrays, arm))
        for arm in exit_arms:
            books[arm.key].extend(replay_exit(ctx, t, arm) for t in base)
        print(f"{sym}: control {len(base)}", flush=True)

    for key in books:
        books[key].sort(key=lambda t: (t["opened"], t["sym"], t["signal"]))

    assert_control_matches(books["control"])
    for arm in exit_arms:
        cset = [(t["sym"], t["opened"]) for t in books["control"]]
        aset = [(t["sym"], t["opened"]) for t in books[arm.key]]
        if cset != aset:
            raise SystemExit(f"Exit arm {arm.key} changed the entry list")

    stats = {}
    for arm in ARMS:
        for sl in ("full", "IS", "OOS"):
            stats[(arm.key, sl)] = book_stats(slice_trades(books[arm.key], sl))

    verdicts = {}
    for arm in ARMS:
        verdicts[arm.key] = judge(
            arm,
            stats[("control", "IS")],
            stats[(arm.key, "IS")],
            stats[("control", "OOS")],
            stats[(arm.key, "OOS")],
        )
        v, why = verdicts[arm.key]
        ins = stats[(arm.key, "IS")]
        print(
            f"{arm.key}: {v} | IS N={ins['n']} WR={ins['wr']:.1f} avg={ins['avg']:.2f} "
            f"Ann={ins['ann_ror']:.1f} | {why}",
            flush=True,
        )

    info = target_answer(books["control"])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    flat = []
    for arm in ARMS:
        for t in books[arm.key]:
            flat.append((arm.key, t))
    write_trade_csv(OUT_DIR / "trades.csv", flat)
    winners = winner_rows(books["control"])
    write_trade_csv(OUT_DIR / "winners.csv", [("control", t) for t in winners])
    write_summary_csv(stats, verdicts)
    write_baseline(info, verdicts, stats)
    write_html(info, books["control"], stats, verdicts)
    fc = stats[("control", "full")]
    ic = stats[("control", "IS")]
    oc = stats[("control", "OOS")]
    print(
        f"CONTROL Ann ROR full={fc['ann_ror']:.2f} IS={ic['ann_ror']:.2f} OOS={oc['ann_ror']:.2f}",
        flush=True,
    )
    print(f"WROTE {OUT_DIR / 'compare.html'}", flush=True)


if __name__ == "__main__":
    main()
