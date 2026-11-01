#!/usr/bin/env python3
"""ENTRY overlay A/B: would shop buy-low B have allowed each Closed fill?

BEFORE / CONTROL = all house Closed fills as taken.
AFTER / FILTER   = only fills whose trendline as of the prior bar was BUY TODAY
                   (weekly support UP and |dist| ≤ 2%).

No lookahead: fractal pivots usable only after confirm date; price = last
complete bar strictly before DATE_OPENED. Same buy-low B rule as live
``trendlines_score_live.py``. Research overlay — not gold, not DailyRun.

Usage:
  python tools/trendline_entry_filter_ab_20260915.py
  python tools/trendline_entry_filter_ab_20260915.py --workers 8
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import math
import os
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    filter_html_compare_columns,
    format_money,
    overlay_ann_ror_max_dd,
)
from dailyrun_system_status import live_wired_systems  # noqa: E402
from trendline_slopes_paultwenty import (  # noqa: E402
    PIVOT_K,
    WEEK_FREQ,
    MONTH_FREQ,
    confirmed_pivots_daily,
    confirmed_pivots_htf,
    last_two_confirmed,
    line_price_at,
    load_ohlc,
    slope_metrics,
)
from trendlines_opens_universe import core_run_timestamp  # noqa: E402
from trendlines_score_live import PROX_PCT, apply_buy_low_b  # noqa: E402

DRIVE = ROOT / "drive"
STAMP = "trendline_entry_filter_ab_20260915"
OUT_DIR = DRIVE / "paul_experiments" / STAMP
IS_CUT = date(2024, 1, 1)
INIT_ACCT = DEFAULT_INITIAL_ACCOUNT

ORIGINAL_REQUEST = (
    "i like this report, but also can you remember to add in any sell signlas "
    "from the trendlines for any holdings I have currently? Also, can you "
    "generate a before and after of all stocks bought in all systems. which "
    "ones would we have bought if we were also doing the same analysis on "
    "them at the time of purchase? I would like to see if we improved our "
    "bottom line."
)
LAYMAN = (
    "We already took these trades. At the moment of each purchase, would the "
    "same weekly-support buy-low picture we use on the daily page have said "
    "yes? BEFORE is every fill we actually booked. AFTER keeps only the ones "
    "that looked like BUY TODAY that morning (rising weekly support and price "
    "within 2% of the line). WAIT or SKIP means we would have sat out. "
    "In-sample / out-of-sample split is calendar 2024 — we do not retune on "
    "the later years. This is a research overlay, not a live entry change."
)

SHEET_CASH: dict[str, float] = {
    "VZ": 45_000.0,
    "RSI": 10_000.0,
    "BRT": 47_500.0,
    "RL": 47_500.0,
    "YH": 47_500.0,
    "MTS": 47_500.0,
    "WPBR": 47_500.0,
    "RS": 47_500.0,
    "SB": 47_500.0,
}

SORT_CSS = """
th.sortable-th { cursor: pointer; user-select: none; white-space: nowrap; }
th.sortable-th:hover { background: #e2e8f0; }
th.sortable-th .sort-ind::after { content: " \\2195"; opacity: .35; font-size: .85em; }
th.sortable-th.sort-asc .sort-ind::after { content: " \\2191"; opacity: .9; }
th.sortable-th.sort-desc .sort-ind::after { content: " \\2193"; opacity: .9; }
body { font-family: Segoe UI, system-ui, sans-serif; margin: 1.5rem; color: #0f172a; background: #f8fafc; }
h1 { font-size: 1.45rem; margin: 0 0 .35rem; }
h2 { font-size: 1.15rem; margin: 1.6rem 0 .5rem; border-bottom: 1px solid #cbd5e1; padding-bottom: .25rem; }
.meta, .caveat { color: #475569; font-size: .92rem; max-width: 78rem; }
.callout { background: #fff; border: 1px solid #cbd5e1; border-radius: 8px; padding: .85rem 1.1rem; margin: .75rem 0; max-width: 78rem; }
.ask { border-left: 4px solid #2563eb; }
.plain { border-left: 4px solid #047857; }
.warn { border-left: 4px solid #b45309; }
.badge { display: inline-block; padding: .1rem .45rem; border-radius: 4px; font-size: .8rem; background: #e2e8f0; }
.HOLD { background: #fef3c7; }
.KEEP, .LEAN { background: #d1fae5; }
.DISMISS { background: #fee2e2; }
table.sortable { border-collapse: collapse; background: #fff; font-size: .82rem; margin: .5rem 0 1rem; }
table.sortable th, table.sortable td { border: 1px solid #e2e8f0; padding: .32rem .5rem; text-align: left; }
table.sortable th { background: #f1f5f9; }
.total-row { font-weight: 700; background: #f8fafc; }
.delta-pos { color: #047857; }
.delta-neg { color: #b91c1c; }
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
        f'<th class="sortable-th" data-sort="{html_mod.escape(sort_type)}" '
        f'tabindex="0" role="columnheader" aria-sort="none">'
        f"{html_mod.escape(label)}<span class=\"sort-ind\"></span></th>"
    )


def _parse_date(v: Any) -> Optional[date]:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    if not s or s.lower() in ("nan", "none", "nat"):
        return None
    if len(s) >= 8 and s[:8].isdigit() and "-" not in s[:8]:
        try:
            return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        except ValueError:
            return None
    try:
        return pd.to_datetime(s, errors="coerce").date()
    except Exception:
        return None


def _num(v: Any) -> float:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return float("nan")
    s = str(v).strip().replace(",", "").replace("$", "").replace("%", "")
    if not s or s.lower() in ("nan", "none"):
        return float("nan")
    try:
        x = float(s)
    except ValueError:
        return float("nan")
    return x if math.isfinite(x) else float("nan")


def _col(df: pd.DataFrame, *names: str) -> Optional[str]:
    want = {n.upper().replace("_", " ") for n in names}
    for c in df.columns:
        key = str(c).upper().replace("_", " ")
        if key in want:
            return str(c)
    return None


def resolve_closed_csv(prefix: str, drive: Path) -> tuple[Path | None, str]:
    pfx = prefix.upper()
    ts = core_run_timestamp(pfx, drive)
    cands: list[Path] = []
    if ts:
        cands.append(drive / f"{pfx}_Closed_{ts}.csv")
        if pfx == "WPBR":
            cands.append(drive / f"PBR_Closed_{ts}.csv")
    cands.append(drive / f"{pfx}_LatestRun_Closed.csv")
    path = next((p for p in cands if p.is_file()), None)
    return path, ts or "LatestRun"


def load_closed_fills(prefix: str, drive: Path) -> tuple[list[dict[str, Any]], str, str]:
    path, pin = resolve_closed_csv(prefix, drive)
    if path is None:
        return [], pin, ""
    try:
        df = pd.read_csv(path)
    except Exception:
        return [], pin, str(path)
    if df.empty:
        return [], pin, str(path)
    sym_c = _col(df, "SYMBOL")
    open_c = _col(df, "DATE_OPENED", "DATE OPENED")
    close_c = _col(df, "DATE_CLOSED", "DATE CLOSED")
    entry_c = _col(df, "ENTRY_PRICE", "ENTRY PRICE")
    pnl_c = _col(df, "PNL_PCT", "PNL %", "PNL%")
    pnl_d_c = _col(df, "PNL_DOLLARS", "PNL $", "PNL$")
    days_c = _col(df, "DAYS_HELD", "DAYS HELD")
    exit_c = _col(df, "EXIT_TYPE", "EXIT TYPE")
    side_c = _col(df, "SIDE")
    if not sym_c or not open_c:
        return [], pin, str(path)
    cash = SHEET_CASH.get(prefix.upper(), 47_500.0)
    out: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        sym = str(row.get(sym_c) or "").strip().upper()
        opened = _parse_date(row.get(open_c))
        if not sym or opened is None:
            continue
        pnl = _num(row.get(pnl_c) if pnl_c else None)
        pnl_d = _num(row.get(pnl_d_c) if pnl_d_c else None)
        if not math.isfinite(pnl_d) and math.isfinite(pnl):
            pnl_d = cash * pnl / 100.0
        if not math.isfinite(pnl) and math.isfinite(pnl_d) and cash:
            pnl = pnl_d / cash * 100.0
        days = _num(row.get(days_c) if days_c else None)
        closed = _parse_date(row.get(close_c) if close_c else None)
        if closed is None and opened is not None and math.isfinite(days) and days >= 0:
            from datetime import timedelta

            closed = opened + timedelta(days=int(round(days)))
        out.append(
            {
                "system": prefix.upper(),
                "sym": sym,
                "opened": opened,
                "closed": closed,
                "entry": _num(row.get(entry_c) if entry_c else None),
                "pnl": pnl if math.isfinite(pnl) else 0.0,
                "pnl_d": pnl_d if math.isfinite(pnl_d) else 0.0,
                "days": days if math.isfinite(days) and days > 0 else 1.0,
                "exit": str(row.get(exit_c) or "—") if exit_c else "—",
                "side": str(row.get(side_c) or "LONG").strip().upper() if side_c else "LONG",
                "cash": cash,
                "src": path.name,
            }
        )
    return out, pin, path.name


def empty_geom() -> dict[str, Any]:
    return {
        "m_sup": "",
        "w_sup": "",
        "d_sup": "",
        "d_res": "",
        "w_dist": float("nan"),
        "w_res_dist": float("nan"),
        "d_dist": float("nan"),
        "w_line": float("nan"),
        "verdict": "WAIT",
        "note": "",
        "rule": "",
        "hold_verdict": "HOLD",
        "hold_rule": "",
    }


def score_asof_from_pivots(
    piv_d: list,
    piv_w: list,
    piv_m: list,
    asof: date,
    close: float,
) -> dict[str, Any]:
    out = empty_geom()
    specs = (
        ("daily", piv_d),
        ("weekly", piv_w),
        ("monthly", piv_m),
    )
    lines: dict[tuple[str, str], dict[str, Any]] = {}
    for tf, pivs in specs:
        for kind, side in (("L", "support"), ("H", "resistance")):
            pair = last_two_confirmed(pivs, kind, asof)
            if not pair:
                continue
            a, b = pair
            if max(a.confirmed_on, b.confirmed_on) > asof:
                continue
            sm = slope_metrics(a.date, a.price, b.date, b.price)
            line_px = line_price_at(a.date, a.price, b.date, b.price, asof)
            dist = (
                (close - line_px) / line_px * 100.0
                if math.isfinite(line_px) and line_px != 0
                else float("nan")
            )
            lines[(tf, side)] = {"dir": sm["direction"], "dist": dist, "line": line_px}
    out["m_sup"] = (lines.get(("monthly", "support")) or {}).get("dir") or ""
    out["w_sup"] = (lines.get(("weekly", "support")) or {}).get("dir") or ""
    out["d_sup"] = (lines.get(("daily", "support")) or {}).get("dir") or ""
    out["d_res"] = (lines.get(("daily", "resistance")) or {}).get("dir") or ""
    wsup = lines.get(("weekly", "support"))
    wres = lines.get(("weekly", "resistance"))
    dsup = lines.get(("daily", "support"))
    out["w_dist"] = float(wsup["dist"]) if wsup else float("nan")
    out["w_res_dist"] = float(wres["dist"]) if wres else float("nan")
    out["d_dist"] = float(dsup["dist"]) if dsup else float("nan")
    out["w_line"] = float(wsup["line"]) if wsup else float("nan")
    return apply_buy_low_b(out)


def prior_bar(daily: pd.DataFrame, opened: date) -> Optional[tuple[date, float]]:
    """Last complete session strictly before DATE_OPENED (no same-day lookahead)."""
    dates = list(daily["Date"])
    closes = list(daily["Close"].astype(float))
    best_i = -1
    for i, d in enumerate(dates):
        if d < opened:
            best_i = i
        else:
            break
    if best_i < 0:
        return None
    return dates[best_i], float(closes[best_i])


def _worker(payload: tuple[str, list[str]]) -> tuple[str, dict[str, dict[str, Any]]]:
    """Score unique opened dates for one symbol. Returns opened-iso -> score."""
    sym, opened_isos = payload
    daily = load_ohlc(sym)
    out: dict[str, dict[str, Any]] = {}
    if daily is None or daily.empty:
        for iso in opened_isos:
            miss = empty_geom()
            miss["verdict"] = "NO DATA"
            miss["hold_verdict"] = "NO DATA"
            miss["note"] = "No local OHLC CSV."
            miss["asof"] = ""
            out[iso] = miss
        return sym, out
    piv_d = confirmed_pivots_daily(daily, PIVOT_K["daily"])
    piv_w = confirmed_pivots_htf(daily, WEEK_FREQ, PIVOT_K["weekly"])
    piv_m = confirmed_pivots_htf(daily, MONTH_FREQ, PIVOT_K["monthly"])
    for iso in opened_isos:
        opened = date.fromisoformat(iso)
        bar = prior_bar(daily, opened)
        if bar is None:
            miss = empty_geom()
            miss["verdict"] = "NO DATA"
            miss["hold_verdict"] = "NO DATA"
            miss["note"] = "No prior bar before DATE_OPENED."
            miss["asof"] = ""
            out[iso] = miss
            continue
        asof, close = bar
        scored = score_asof_from_pivots(piv_d, piv_w, piv_m, asof, close)
        scored["asof"] = asof.isoformat()
        scored["asof_close"] = close
        out[iso] = scored
    return sym, out


def _pctile(xs: list[float], q: float) -> float:
    if not xs:
        return float("nan")
    a = sorted(xs)
    if len(a) == 1:
        return a[0]
    idx = min(len(a) - 1, max(0, int(round(q * (len(a) - 1)))))
    return a[idx]


def book_stats(trades: list[dict[str, Any]], cash: float) -> dict[str, Any]:
    n = len(trades)
    empty = {
        "n": 0,
        "wins": 0,
        "losses": 0,
        "wr": 0.0,
        "avg_pnl": 0.0,
        "wo_max": 0.0,
        "exp_pct": 0.0,
        "avg_win": 0.0,
        "avg_loss": 0.0,
        "wl_count": 0.0,
        "wl_dollar": 0.0,
        "pf": 0.0,
        "pnl_d": 0.0,
        "avg_days": 0.0,
        "med_days": 0.0,
        "p90_days": 0.0,
        "capital_days": 0.0,
        "ppc": float("nan"),
        "ann_ror": float("nan"),
        "max_dd": float("nan"),
        "calmar": float("nan"),
        "sharpe": float("nan"),
        "losing_streak": 0,
        "exits": {},
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
    days = [float(t["days"]) for t in trades]
    avg_days = sum(days) / n
    pnl_d = sum(float(t["pnl_d"]) for t in trades)
    ov = overlay_ann_ror_max_dd(trades, cash=cash, initial_account=INIT_ACCT) or {}
    streak = 0
    best_streak = 0
    for t in sorted(trades, key=lambda x: (x.get("closed") or date.min, x["opened"], x["sym"])):
        if float(t["pnl"]) < 0:
            streak += 1
            best_streak = max(best_streak, streak)
        else:
            streak = 0
    win_d = sum(float(t["pnl_d"]) for t in trades if float(t["pnl"]) > 0)
    loss_d = abs(sum(float(t["pnl_d"]) for t in trades if float(t["pnl"]) < 0))
    cap_days = float(ov.get("capital_days") or sum(days))
    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "wr": 100.0 * len(wins) / n,
        "avg_pnl": avg,
        "wo_max": wo,
        "exp_pct": avg,
        "avg_win": (sum(wins) / len(wins)) if wins else 0.0,
        "avg_loss": (sum(losses) / len(losses)) if losses else 0.0,
        "wl_count": (len(wins) / len(losses)) if losses else (float(len(wins)) if wins else 0.0),
        "wl_dollar": (win_d / loss_d) if loss_d > 0 else (win_d if win_d > 0 else 0.0),
        "pf": (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0),
        "pnl_d": pnl_d,
        "avg_days": avg_days,
        "med_days": float(np.median(days)),
        "p90_days": _pctile(days, 0.90),
        "capital_days": cap_days,
        "ppc": (pnl_d / cap_days) if cap_days else float("nan"),
        "ann_ror": float(ov.get("ann_ror", float("nan"))),
        "max_dd": float(ov.get("max_dd", float("nan"))),
        "calmar": float(ov.get("calmar", float("nan"))),
        "sharpe": float(ov.get("sharpe", float("nan"))),
        "losing_streak": best_streak,
        "exits": dict(Counter(str(t.get("exit") or "—") for t in trades)),
    }


def split_is_oos(trades: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return [t for t in trades if t["opened"] < IS_CUT], [t for t in trades if t["opened"] >= IS_CUT]


def decide_verdict(ctrl_is: dict, filt_is: dict, ctrl_oos: dict, filt_oos: dict) -> tuple[str, str]:
    """Quality over count. OOS report-only. In-sample selection labeled."""
    notes = [
        "in-sample selection / research overlay — buy-low B was already the live buy-today rule"
    ]
    n_ctrl = ctrl_is["n"]
    n_filt = filt_is["n"]
    keep_frac = (n_filt / n_ctrl) if n_ctrl else 0.0
    n_collapse = n_ctrl >= 30 and (keep_frac < 0.30 or n_filt < 40)
    d_avg = filt_is["avg_pnl"] - ctrl_is["avg_pnl"]
    d_wo = filt_is["wo_max"] - ctrl_is["wo_max"]
    d_wr = filt_is["wr"] - ctrl_is["wr"]
    d_ann = (
        filt_is["ann_ror"] - ctrl_is["ann_ror"]
        if math.isfinite(filt_is["ann_ror"]) and math.isfinite(ctrl_is["ann_ror"])
        else float("nan")
    )
    oos_soft = False
    if ctrl_oos["n"] >= 20 and filt_oos["n"] >= 20:
        oos_soft = (filt_oos["avg_pnl"] < ctrl_oos["avg_pnl"] - 0.15) or (
            math.isfinite(filt_oos["ann_ror"])
            and math.isfinite(ctrl_oos["ann_ror"])
            and filt_oos["ann_ror"] < ctrl_oos["ann_ror"] - 1.0
        )
        notes.append(
            f"OOS ΔAvg {filt_oos['avg_pnl']-ctrl_oos['avg_pnl']:+.2f}pp"
            + (" — softened" if oos_soft else "")
        )
    else:
        notes.append("OOS thin — report-only")
    if n_collapse:
        notes.append(f"N collapsed ({n_filt}/{n_ctrl} = {100*keep_frac:.0f}% kept)")
        return "HOLD", "; ".join(notes)
    if oos_soft:
        notes.append("OOS softened — do not retune")
        return "HOLD", "; ".join(notes)
    better = (d_avg > 0.15 and d_wo > -0.05) or (
        math.isfinite(d_ann) and d_ann > 1.0 and d_avg > -0.05 and d_wr > -1.0
    )
    worse = d_avg < -0.15 and d_wo < 0
    if worse:
        return "DISMISS", "; ".join(notes)
    if better:
        notes.append("IS quality up — still research-only, not DailyRun")
        return "LEAN KEEP", "; ".join(notes)
    notes.append("flat/mixed quality")
    return "HOLD", "; ".join(notes)


def fmt_n(v: Any, d: int = 2) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(x):
        return "—"
    return f"{x:.{d}f}"


def fmt_delta(v: Any, d: int = 2) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(x):
        return "—"
    cls = "delta-pos" if x > 0 else ("delta-neg" if x < 0 else "")
    sign = "+" if x > 0 else ""
    return f'<span class="{cls}">{sign}{x:.{d}f}</span>'


def metric_rows(ctrl: dict, filt: dict) -> list[tuple[str, str, str, str]]:
    """Canonical book rows (label, ctrl, filt, delta). $ PnL omitted from HTML."""
    def dlt(a: Any, b: Any) -> Any:
        try:
            return float(b) - float(a)
        except (TypeError, ValueError):
            return float("nan")

    rows = [
        ("Total trades", str(ctrl["n"]), str(filt["n"]), str(filt["n"] - ctrl["n"])),
        ("Wins", str(ctrl["wins"]), str(filt["wins"]), str(filt["wins"] - ctrl["wins"])),
        ("Losses", str(ctrl["losses"]), str(filt["losses"]), str(filt["losses"] - ctrl["losses"])),
        ("Win %", fmt_n(ctrl["wr"]), fmt_n(filt["wr"]), fmt_delta(dlt(ctrl["wr"], filt["wr"]))),
        ("Avg PnL %", fmt_n(ctrl["avg_pnl"]), fmt_n(filt["avg_pnl"]), fmt_delta(dlt(ctrl["avg_pnl"], filt["avg_pnl"]))),
        ("Book AVG_PNL_PCT_WO_MAX", fmt_n(ctrl["wo_max"]), fmt_n(filt["wo_max"]), fmt_delta(dlt(ctrl["wo_max"], filt["wo_max"]))),
        ("Expectancy %", fmt_n(ctrl["exp_pct"]), fmt_n(filt["exp_pct"]), fmt_delta(dlt(ctrl["exp_pct"], filt["exp_pct"]))),
        ("Expectancy $", format_money(ctrl["pnl_d"] / ctrl["n"] if ctrl["n"] else None), format_money(filt["pnl_d"] / filt["n"] if filt["n"] else None), "—"),
        ("Avg win %", fmt_n(ctrl["avg_win"]), fmt_n(filt["avg_win"]), fmt_delta(dlt(ctrl["avg_win"], filt["avg_win"]))),
        ("Avg loss %", fmt_n(ctrl["avg_loss"]), fmt_n(filt["avg_loss"]), fmt_delta(dlt(ctrl["avg_loss"], filt["avg_loss"]))),
        ("Win/Loss ratio (count)", fmt_n(ctrl["wl_count"]), fmt_n(filt["wl_count"]), fmt_delta(dlt(ctrl["wl_count"], filt["wl_count"]))),
        ("Win/Loss ratio $", fmt_n(ctrl["wl_dollar"]), fmt_n(filt["wl_dollar"]), fmt_delta(dlt(ctrl["wl_dollar"], filt["wl_dollar"]))),
        ("Profit factor", fmt_n(ctrl["pf"]), fmt_n(filt["pf"]), fmt_delta(dlt(ctrl["pf"], filt["pf"]))),
        ("Ann ROR %", fmt_n(ctrl["ann_ror"]), fmt_n(filt["ann_ror"]), fmt_delta(dlt(ctrl["ann_ror"], filt["ann_ror"]))),
        ("Max DD %", fmt_n(ctrl["max_dd"]), fmt_n(filt["max_dd"]), fmt_delta(dlt(ctrl["max_dd"], filt["max_dd"]))),
        ("Calmar", fmt_n(ctrl["calmar"]), fmt_n(filt["calmar"]), fmt_delta(dlt(ctrl["calmar"], filt["calmar"]))),
        ("Sharpe", fmt_n(ctrl["sharpe"]), fmt_n(filt["sharpe"]), fmt_delta(dlt(ctrl["sharpe"], filt["sharpe"]))),
        ("Profit per capital day", format_money(ctrl["ppc"]), format_money(filt["ppc"]), "—"),
        ("Capital days", fmt_n(ctrl["capital_days"], 0), fmt_n(filt["capital_days"], 0), fmt_n(filt["capital_days"] - ctrl["capital_days"], 0)),
        ("Avg days held", fmt_n(ctrl["avg_days"], 1), fmt_n(filt["avg_days"], 1), fmt_delta(dlt(ctrl["avg_days"], filt["avg_days"]), 1)),
        ("Median days held", fmt_n(ctrl["med_days"], 1), fmt_n(filt["med_days"], 1), fmt_delta(dlt(ctrl["med_days"], filt["med_days"]), 1)),
        ("P90 days held", fmt_n(ctrl["p90_days"], 1), fmt_n(filt["p90_days"], 1), fmt_delta(dlt(ctrl["p90_days"], filt["p90_days"]), 1)),
        ("Losing streak", str(ctrl["losing_streak"]), str(filt["losing_streak"]), str(filt["losing_streak"] - ctrl["losing_streak"])),
    ]
    return rows


def dropped_table(dropped: list[dict[str, Any]], title: str, limit: int = 25) -> str:
    heads = [
        ("Symbol", "text"),
        ("System", "text"),
        ("Opened", "date"),
        ("PnL %", "num"),
        ("Verdict at purchase", "text"),
        ("W sup", "text"),
        ("W dist %", "num"),
        ("As-of bar", "date"),
        ("Dup?", "text"),
        ("Note", "text"),
    ]
    thead = "".join(sortable_th(l, t) for l, t in heads)
    body = []
    for t in dropped[:limit]:
        body.append(
            "<tr>"
            f"<td>{html_mod.escape(t['sym'])}</td>"
            f"<td>{html_mod.escape(t['system'])}</td>"
            f"<td>{t['opened'].isoformat()}</td>"
            f"<td>{fmt_n(t['pnl'])}</td>"
            f"<td>{html_mod.escape(t.get('tl_verdict') or '—')}</td>"
            f"<td>{html_mod.escape(str(t.get('w_sup') or '—'))}</td>"
            f"<td>{fmt_n(t.get('w_dist'))}</td>"
            f"<td>{html_mod.escape(str(t.get('asof') or '—'))}</td>"
            f"<td>{'YES' if t.get('dup') else ''}</td>"
            f"<td>{html_mod.escape((t.get('tl_note') or '')[:180])}</td>"
            "</tr>"
        )
    empty = "<tr><td colspan='10'>None</td></tr>"
    return (
        f"<h3>{html_mod.escape(title)}</h3>"
        f'<p class="meta">Click column headers to sort.</p>'
        f'<table class="sortable"><thead><tr>{thead}</tr></thead>'
        f"<tbody>{''.join(body) or empty}</tbody></table>"
    )


def write_baseline(
    path: Path,
    *,
    pins: dict[str, str],
    combined: dict[str, Any],
    verdict: str,
    note: str,
    n_dup: int,
) -> None:
    ctrl = combined["ctrl_full"]
    filt = combined["filt_full"]
    text = f"""# BASELINE — `{STAMP}`

**Status:** Research overlay. **Not gold. Not DailyRun.** Do not wire as a live entry gate.

## What you asked

> {ORIGINAL_REQUEST}

## In plain English

{LAYMAN}

## Frozen knobs

| Knob | Value |
|------|-------|
| Control | All Closed fills as taken (house exits unchanged) |
| Filter | Keep fill only if as-of score is **BUY TODAY** (buy-low B) |
| Buy-low B | Weekly support UP and `\\|dist_pct\\| ≤ {PROX_PCT:g}%` (`trendline_slopes_buylow_ab.py` hypothesis B) |
| As-of bar | Last complete session **strictly before** `DATE_OPENED` (no same-day close lookahead) |
| Pivots | Daily k=5, weekly W-FRI k=3, monthly ME k=2; usable only after `confirmed_on` |
| HTF honesty | Full-history weekly/monthly bars + `confirmed_on ≤ as-of` (same as truncate) |
| Universe | Wired DailyRun Closed (LatestRun / house pin). RSI house pin, not RSIN |
| IS / OOS | entry &lt; / ≥ 2024-01-01 (OOS **report-only**) |
| Overlay seed | ${INIT_ACCT:,.0f} exit-date equity for Max DD / Sharpe |
| Sheet cash | VZ $45k · RSI $10k · others $47.5k (RL same) |

## Pins

{os.linesep.join(f"- **{k}:** `{v}`" for k, v in pins.items())}

## Label honesty

- Choosing buy-low B after seeing the live buy-today page is **in-sample selection**.
- Same-symbol / same-`DATE_OPENED` on two systems is counted twice and labeled (`dup`). Double-count rows this run: **{n_dup}**.
- N will drop by construction. Judge **quality** (WR, Avg%, expectancy, Ann ROR overlay, Max DD), not trade count.
- OOS is report-only. If OOS softens or N collapses → **HOLD**. Do not retune the 2% band on OOS.
- Not adopted as a DailyRun entry gate.

## Combined book (honest double-count)

| Arm | N | WR % | Avg % | Overlay $ | Ann ROR % | Max DD % |
|-----|---|------|-------|-----------|-----------|----------|
| BEFORE / CONTROL | {ctrl['n']} | {ctrl['wr']:.2f} | {ctrl['avg_pnl']:.2f} | {ctrl['pnl_d']:,.2f} | {ctrl['ann_ror']:.2f} | {ctrl['max_dd']:.2f} |
| AFTER / FILTER | {filt['n']} | {filt['wr']:.2f} | {filt['avg_pnl']:.2f} | {filt['pnl_d']:,.2f} | {filt['ann_ror']:.2f} | {filt['max_dd']:.2f} |

**Verdict (IS quality, OOS report-only):** {verdict}

{note}

## Arms

- `CONTROL` — every Closed fill
- `FILTER` — BUY TODAY equivalent at prior bar only. WAIT / SKIP / NO DATA dropped
"""
    path.write_text(text, encoding="utf-8")


def write_html(
    path: Path,
    *,
    pins: dict[str, str],
    per_sys: list[dict[str, Any]],
    combined: dict[str, Any],
    dropped: list[dict[str, Any]],
    verdict: str,
    note: str,
    n_dup: int,
) -> None:
    def compare_table(title: str, ctrl: dict, filt: dict) -> str:
        rows = metric_rows(ctrl, filt)
        heads = [
            ("Metric", "text"),
            ("BEFORE / CONTROL", "num"),
            ("AFTER / FILTER", "num"),
            ("Δ", "num"),
        ]
        thead = "".join(sortable_th(l, t) for l, t in heads)
        body = "".join(
            f"<tr><td>{html_mod.escape(a)}</td><td>{b}</td><td>{c}</td><td>{d}</td></tr>"
            for a, b, c, d in rows
        )
        kept = filt["n"]
        tot = ctrl["n"]
        frac = (100.0 * kept / tot) if tot else 0.0
        return (
            f"<h3>{html_mod.escape(title)}</h3>"
            f'<p class="meta">Kept {kept} / {tot} ({frac:.1f}%). Overlay $ CONTROL '
            f"{html_mod.escape(format_money(ctrl['pnl_d']))} → FILTER "
            f"{html_mod.escape(format_money(filt['pnl_d']))}. "
            "Sheet / Total PnL $ omitted from the metric table (quality first). "
            "Click column headers to sort.</p>"
            f'<table class="sortable"><thead><tr>{thead}</tr></thead><tbody>{body}</tbody></table>'
        )

    sys_heads = filter_html_compare_columns(
        [
            ("System", "text"),
            ("Split", "text"),
            ("Arm", "text"),
            ("N", "num"),
            ("Win %", "num"),
            ("Avg PnL %", "num"),
            ("WO_MAX %", "num"),
            ("PF", "num"),
            ("Ann ROR %", "num"),
            ("Max DD %", "num"),
            ("Calmar", "num"),
            ("Sharpe", "num"),
            ("Avg days", "num"),
            ("Verdict", "text"),
        ]
    )
    sys_thead = "".join(sortable_th(l, t) for l, t in sys_heads)
    sys_body: list[str] = []
    for rec in per_sys:
        for split, slabel in (("full", "FULL"), ("is", "IS"), ("oos", "OOS")):
            for arm, alabel in (("ctrl", "CONTROL"), ("filt", "FILTER")):
                m = rec[f"{arm}_{split}"]
                badge = rec["verdict"] if alabel == "FILTER" and slabel == "IS" else ("CONTROL" if alabel == "CONTROL" and slabel == "FULL" else "—")
                sys_body.append(
                    "<tr>"
                    f"<td>{html_mod.escape(rec['system'])}</td>"
                    f"<td>{slabel}</td>"
                    f"<td>{alabel}</td>"
                    f"<td>{m['n']}</td>"
                    f"<td>{fmt_n(m['wr'])}</td>"
                    f"<td>{fmt_n(m['avg_pnl'])}</td>"
                    f"<td>{fmt_n(m['wo_max'])}</td>"
                    f"<td>{fmt_n(m['pf'])}</td>"
                    f"<td>{fmt_n(m['ann_ror'])}</td>"
                    f"<td>{fmt_n(m['max_dd'])}</td>"
                    f"<td>{fmt_n(m['calmar'])}</td>"
                    f"<td>{fmt_n(m['sharpe'])}</td>"
                    f"<td>{fmt_n(m['avg_days'], 1)}</td>"
                    f"<td><span class=\"badge {badge.split()[0]}\">{html_mod.escape(badge)}</span></td>"
                    "</tr>"
                )

    worst = sorted(dropped, key=lambda t: float(t["pnl"]))[:25]
    best = sorted(dropped, key=lambda t: float(t["pnl"]), reverse=True)[:25]
    pin_bits = ", ".join(f"{k} {v}" for k, v in pins.items())
    vc = combined["ctrl_full"]
    vf = combined["filt_full"]
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Trendline entry filter A/B — {STAMP}</title>
<style>{SORT_CSS}</style>
</head>
<body>
<h1>Before / after: buy-low B at time of purchase</h1>
<p class="meta">Stamp <code>{STAMP}</code> · research overlay · not gold · not DailyRun · generated {datetime.now().strftime("%Y-%m-%d %H:%M")}</p>

<div class="callout ask">
<h2 style="margin-top:0;border:0">What you asked</h2>
<p>“{html_mod.escape(ORIGINAL_REQUEST)}”</p>
</div>

<div class="callout plain">
<h2 style="margin-top:0;border:0">In plain English</h2>
<p>{html_mod.escape(LAYMAN)}</p>
</div>

<div class="callout warn">
<p><strong>Verdict:</strong> <span class="badge {verdict.split()[0]}">{html_mod.escape(verdict)}</span> — {html_mod.escape(note)}</p>
<p>Combined BEFORE N={vc['n']} WR={vc['wr']:.1f}% Avg={vc['avg_pnl']:.2f}% overlay {html_mod.escape(format_money(vc['pnl_d']))}
→ AFTER N={vf['n']} WR={vf['wr']:.1f}% Avg={vf['avg_pnl']:.2f}% overlay {html_mod.escape(format_money(vf['pnl_d']))}.
Kept {vf['n']}/{vc['n']}. Double-counted same symbol+date across systems: {n_dup}.</p>
<p>Lookahead: prior-bar close vs DATE_OPENED; fractal pivots only after confirm (±k). Same buy-low B as the live page. In-sample selection because that rule was already the discretionary buy-today overlay.</p>
</div>

<h2>How we decided</h2>
<ul>
<li><strong>BEFORE / CONTROL:</strong> every Closed fill from wired DailyRun systems (house pins).</li>
<li><strong>AFTER / FILTER:</strong> keep only fills whose reconstructed monthly/weekly/daily (M/W/D) picture at the <em>prior bar</em> is BUY TODAY — weekly support UP and |dist| ≤ {PROX_PCT:g}%.</li>
<li><strong>WAIT / SKIP / NO DATA</strong> = would not have bought.</li>
<li><strong>IS</strong> = entry &lt; 2024-01-01. <strong>OOS</strong> = entry ≥ 2024-01-01, report-only. Do not KEEP from OOS.</li>
<li>Ann ROR / Max DD / Sharpe: Closed overlay on a ${INIT_ACCT:,.0f} seed (exit-date equity). Per-system sheet cash for the slot Ann ROR. Combined uses mean sheet cash.</li>
</ul>
<p class="caveat">Acronyms: Break and ReTest (BRT); Volume Zone (VZ); Relative Strength Index (RSI); Rocket Launcher (RL); Pivot Break and Retest (WPBR); Year High (YH); StockBee (SB); Magic Touch (MTS); Relative Strength vs SPY (RS). Pins: {html_mod.escape(pin_bits)}.</p>

<h2>Combined (all systems, honest double-count)</h2>
{compare_table("IS (entry < 2024-01-01)", combined["ctrl_is"], combined["filt_is"])}
{compare_table("OOS (entry ≥ 2024-01-01) — report-only", combined["ctrl_oos"], combined["filt_oos"])}
{compare_table("FULL", combined["ctrl_full"], combined["filt_full"])}

<h2>Per system</h2>
<p class="meta">Click column headers to sort. Verdict is IS-only (OOS report-only).</p>
<table class="sortable"><thead><tr>{sys_thead}</tr></thead><tbody>{''.join(sys_body)}</tbody></table>

<h2>Dropped trades (would not have bought)</h2>
<p class="meta">{len(dropped)} fills skipped by the filter. Worst / best by Closed PnL % — sitting out a huge winner hurts; sitting out a loser helps.</p>
{dropped_table(worst, "Worst 25 skipped (hurts if we filter)")}
{dropped_table(best, "Best 25 skipped (helps if we filter)")}

<p class="caveat">Daily sell signals for current holdings live on <a href="../../paul_studies/trendlines_opens_latest/buy_today.html">buy_today.html</a>. This stamp does not change DailyRun entries or exits.</p>
{SORT_JS}
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def run(workers: int, max_symbols: int = 0) -> dict[str, Any]:
    systems = list(live_wired_systems())
    fills: list[dict[str, Any]] = []
    pins: dict[str, str] = {}
    sources: dict[str, str] = {}
    for sys_name in systems:
        rows, pin, src = load_closed_fills(sys_name, DRIVE)
        pins[sys_name] = pin
        sources[sys_name] = src
        fills.extend(rows)
        print(f"[entry_filter] {sys_name} pin={pin} n={len(rows)} src={src}")

    key_counts: Counter[tuple[str, date]] = Counter((t["sym"], t["opened"]) for t in fills)
    n_dup = sum(1 for t in fills if key_counts[(t["sym"], t["opened"])] > 1)
    for t in fills:
        t["dup"] = key_counts[(t["sym"], t["opened"])] > 1

    by_sym: dict[str, set[str]] = defaultdict(set)
    for t in fills:
        by_sym[t["sym"]].add(t["opened"].isoformat())
    payloads = [(sym, sorted(dates)) for sym, dates in sorted(by_sym.items())]
    if max_symbols and max_symbols > 0:
        keep_syms = {s for s, _ in payloads[:max_symbols]}
        payloads = [p for p in payloads if p[0] in keep_syms]
        fills = [t for t in fills if t["sym"] in keep_syms]

    scores: dict[str, dict[str, dict[str, Any]]] = {}
    print(f"[entry_filter] scoring {len(payloads)} symbols, {len(fills)} fills, workers={workers}")
    if workers <= 1:
        for p in payloads:
            sym, rec = _worker(p)
            scores[sym] = rec
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_worker, p): p[0] for p in payloads}
            done = 0
            for fut in as_completed(futs):
                sym, rec = fut.result()
                scores[sym] = rec
                done += 1
                if done % 100 == 0 or done == len(futs):
                    print(f"[entry_filter] scored {done}/{len(futs)}")

    verdict_counts: Counter[str] = Counter()
    for t in fills:
        rec = (scores.get(t["sym"]) or {}).get(t["opened"].isoformat()) or {}
        v = str(rec.get("verdict") or "NO DATA")
        t["tl_verdict"] = v
        t["tl_note"] = rec.get("note") or ""
        t["w_sup"] = rec.get("w_sup") or ""
        t["w_dist"] = rec.get("w_dist")
        t["asof"] = rec.get("asof") or ""
        t["keep"] = v == "BUY TODAY"
        verdict_counts[v] += 1

    kept = [t for t in fills if t["keep"]]
    dropped = [t for t in fills if not t["keep"]]

    per_sys: list[dict[str, Any]] = []
    for sys_name in systems:
        book = [t for t in fills if t["system"] == sys_name]
        filt = [t for t in book if t["keep"]]
        cash = SHEET_CASH.get(sys_name, 47_500.0)
        ctrl_is, ctrl_oos = split_is_oos(book)
        filt_is, filt_oos = split_is_oos(filt)
        rec = {
            "system": sys_name,
            "cash": cash,
            "pin": pins.get(sys_name, ""),
            "ctrl_full": book_stats(book, cash),
            "filt_full": book_stats(filt, cash),
            "ctrl_is": book_stats(ctrl_is, cash),
            "filt_is": book_stats(filt_is, cash),
            "ctrl_oos": book_stats(ctrl_oos, cash),
            "filt_oos": book_stats(filt_oos, cash),
        }
        v, n = decide_verdict(rec["ctrl_is"], rec["filt_is"], rec["ctrl_oos"], rec["filt_oos"])
        rec["verdict"] = v
        rec["note"] = n
        per_sys.append(rec)

    mean_cash = float(np.mean([t["cash"] for t in fills])) if fills else 47_500.0
    ctrl_is, ctrl_oos = split_is_oos(fills)
    filt_is, filt_oos = split_is_oos(kept)
    combined = {
        "ctrl_full": book_stats(fills, mean_cash),
        "filt_full": book_stats(kept, mean_cash),
        "ctrl_is": book_stats(ctrl_is, mean_cash),
        "filt_is": book_stats(filt_is, mean_cash),
        "ctrl_oos": book_stats(ctrl_oos, mean_cash),
        "filt_oos": book_stats(filt_oos, mean_cash),
        "mean_cash": mean_cash,
    }
    verdict, note = decide_verdict(
        combined["ctrl_is"], combined["filt_is"], combined["ctrl_oos"], combined["filt_oos"]
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_baseline(
        OUT_DIR / "BASELINE.md",
        pins=pins,
        combined=combined,
        verdict=verdict,
        note=note,
        n_dup=n_dup,
    )
    write_html(
        OUT_DIR / "compare.html",
        pins=pins,
        per_sys=per_sys,
        combined=combined,
        dropped=dropped,
        verdict=verdict,
        note=note,
        n_dup=n_dup,
    )
    summary = {
        "stamp": STAMP,
        "verdict": verdict,
        "note": note,
        "pins": pins,
        "sources": sources,
        "n_fills": len(fills),
        "n_kept": len(kept),
        "n_dropped": len(dropped),
        "n_dup": n_dup,
        "verdict_counts": dict(verdict_counts),
        "combined": {
            k: {kk: vv for kk, vv in rec.items() if kk != "exits"}
            for k, rec in combined.items()
            if k != "mean_cash"
        },
        "lookahead": "prior_bar_close_strictly_before_DATE_OPENED; confirmed_on<=asof",
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("verdict", "n_fills", "n_kept", "n_dropped", "n_dup", "verdict_counts")}, indent=2))
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 1))
    ap.add_argument("--max-symbols", type=int, default=0, help="Smoke cap")
    args = ap.parse_args()
    run(workers=max(1, args.workers), max_symbols=args.max_symbols)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
