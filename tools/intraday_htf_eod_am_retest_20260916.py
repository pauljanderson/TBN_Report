#!/usr/bin/env python3
"""EOD-approach + next-AM-retest pattern check on the frozen 4h×1m chandelier-3 book.

Parent: drive/paul_experiments/intraday_htf_retest_20260916
Stamp:  drive/paul_experiments/intraday_htf_eod_am_retest_20260916

Research only. Does not retune the chandelier freeze. One frozen boolean.

Usage:
  python tools/intraday_htf_eod_am_retest_20260916.py
"""
from __future__ import annotations

import csv
import html as html_mod
import json
import math
import sys
from collections import Counter
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stock_analysis"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
sys.path.insert(0, str(ROOT / "tools"))

from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    format_money,
    overlay_ann_ror_max_dd,
)
from intraday_1m import DEFAULT_1M_DIR, ET, read_1m  # noqa: E402
from intraday_htf_retest_20260916 import (  # noqa: E402
    RETEST_ATR_MULT,
    SESSION_CLOSE,
    SESSION_OPEN,
    rth_filter,
)

PARENT_STAMP = "intraday_htf_retest_20260916"
STAMP = "intraday_htf_eod_am_retest_20260916"
PARENT_DIR = ROOT / "drive" / "paul_experiments" / PARENT_STAMP
OUT_DIR = ROOT / "drive" / "paul_experiments" / STAMP
TRADES_CSV = PARENT_DIR / "trades.csv"
CHART_DIR = PARENT_DIR / "charts"

HTF = "4h"
LTF = "1m"
ARM = "trail_chandelier_3"
SHEET = 45_000.0
INIT_ACCT = DEFAULT_INITIAL_ACCOUNT

# --- Frozen pattern (locked before scoring lift) ---
EOD_START = time(15, 0)
EOD_END = time(16, 0)
AM_START = time(9, 30)
AM_END = time(10, 30)
ZONE_ATR_MULT = RETEST_ATR_MULT  # 0.15 × HTF ATR — parent retest band
NOON = time(12, 0)

# Sensitivity (report-only HOLD notes; not used for the boolean)
EOD_START_LATE = time(15, 30)
AM_END_EARLY = time(10, 0)

# Paul's liked set: symbol + session date. PnL% is a check, not the key.
LIKED_HINTS: list[tuple[str, date, float, str]] = [
    ("LLY", date(2026, 8, 7), 2.076, "STOP"),
    ("ASML", date(2026, 8, 17), 0.359, "STOP"),
    ("MA", date(2026, 8, 19), 1.316, "STOP"),
    ("TSLA", date(2026, 8, 19), 0.458, "STOP"),
    ("TSLA", date(2026, 8, 24), 1.063, "STOP"),
    ("NVDA", date(2026, 8, 28), 0.966, "STOP"),
    ("META", date(2026, 9, 2), 0.460, "STOP"),
    ("AAPL", date(2026, 9, 14), 0.684, "STOP"),
]

ORIGINAL_REQUEST = (
    "I like the following. are there any patterns in these trades that "
    "preceeed the gains that the other charts don't have?\n"
    "LLY · 2026-08-07 · +2.076% · STOP\n"
    "ASML · 2026-08-17 · +0.359% · STOP\n"
    "MA · 2026-08-19 · +1.316% · STOP\n"
    "TSLA · 2026-08-19 · +0.458% · STOP\n"
    "TSLA · 2026-08-24 · +1.063% · STOP\n"
    "NVDA · 2026-08-28 · +0.966% · STOP\n"
    "there's a lot that i'm seeing that dip close to the zone for a retest "
    "near the end of the day and then at the beginning of the next day if "
    "the retest happens, then we're off\n"
    "i don't know if that's true. but please check\n"
    "META · 2026-09-02 · +0.460% · STOP\n"
    "AAPL · 2026-09-14 · +0.684% · STOP"
)

PLAIN_ENGLISH = (
    "Paul picked eight green chandelier-3 trades from the 4-hour / 1-minute "
    "gallery and asked whether a late-day dip toward the broken high, followed "
    "by a next-morning retest, is what those eight have and the other charts "
    "lack. High Time Frame (HTF) here means the 4-hour bars the swing-high "
    "line is drawn on (not High Tight Flag). Low Time Frame (LTF) is the "
    "1-minute tape. Average True Range (ATR) is the typical-bar-range used "
    "for the zone band (level ± 0.15 × 4-hour ATR). We froze one yes/no rule "
    "before looking at whether it 'works': on the session before the fill, "
    "did a 1-minute low tag that zone between 15:00 and 16:00 ET, AND on the "
    "fill session did a 1-minute bar tag it again between 09:30 and 10:30 ET? "
    "The honest test is that rule on all 37 trades, not just the eight he liked. "
    "These are same-session scalps — they do not hold overnight — so the story "
    "has to be a setup before the fill, not a dip after we are already in. "
    "Research only; not a live filter."
)

SORT_CSS = """
th.sortable-th {
  cursor: pointer;
  user-select: none;
  -webkit-user-select: none;
  white-space: nowrap;
  padding: 12px 10px;
  min-height: 44px;
  touch-action: manipulation;
}
th.sortable-th:hover, th.sortable-th:active { background: #e2e8f0; }
th.sortable-th .sort-ind::after { content: " \\2195"; opacity: .35; font-size: .85em; }
th.sortable-th.sort-asc .sort-ind::after { content: " \\2191"; opacity: .9; }
th.sortable-th.sort-desc .sort-ind::after { content: " \\2193"; opacity: .9; }
"""

SORT_JS = r"""
<script>
(function () {
  var lastTouchTs = 0;
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
      var av = parseSortValue(a.cells[col] ? a.cells[col].textContent : "", type);
      var bv = parseSortValue(b.cells[col] ? b.cells[col].textContent : "", type);
      if (typeof av === "string" || typeof bv === "string") {
        return dir * String(av).localeCompare(String(bv));
      }
      return dir * (av - bv);
    });
    movable.concat(pinned).forEach(function (r) { tbody.appendChild(r); });
  }
  function bindSortHeader(table, th, col) {
    function onActivate(e) {
      if (e.type === "touchend") {
        lastTouchTs = Date.now();
        e.preventDefault();
      } else if (e.type === "click" && Date.now() - lastTouchTs < 500) {
        return;
      }
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


def _ts_et(ts: Any) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        return t.tz_localize(ET)
    return t.tz_convert(ET)


def _tod(ts: Any) -> time:
    return _ts_et(ts).time().replace(tzinfo=None)


def _sess_date(ts: Any) -> date:
    return _ts_et(ts).date()


def _hhmm(ts: Any) -> str:
    t = _ts_et(ts)
    return f"{t.hour:02d}:{t.minute:02d}"


def _intersects(lo: float, hi: float, level: float, band: float) -> bool:
    if not (np.isfinite(lo) and np.isfinite(hi) and np.isfinite(level) and np.isfinite(band)):
        return False
    return bool(lo <= level + band and hi >= level - band)


def _bar_at_or_after(day_df: pd.DataFrame, clock: time) -> Optional[pd.Series]:
    if day_df is None or day_df.empty:
        return None
    tod = day_df["ts"].map(_tod)
    hit = day_df.loc[tod >= clock]
    if hit.empty:
        return day_df.iloc[-1]
    return hit.iloc[0]


def _window_mask(day_df: pd.DataFrame, start: time, end: time) -> pd.Series:
    tod = day_df["ts"].map(_tod)
    return (tod >= start) & (tod < end)


def _window_stats(day_df: pd.DataFrame, start: time, end: time, level: float, band: float, atr: float) -> dict[str, Any]:
    empty = {
        "n_bars": 0,
        "tagged": False,
        "tag_ts": "",
        "min_low": float("nan"),
        "min_dist_atr": float("nan"),
        "min_dist_pct": float("nan"),
        "close_enough_low": False,
    }
    if day_df is None or day_df.empty:
        return empty
    w = day_df.loc[_window_mask(day_df, start, end)]
    if w.empty:
        return empty
    tagged = False
    tag_ts = ""
    for rec in w.itertuples(index=False):
        if _intersects(float(rec.low), float(rec.high), level, band):
            tagged = True
            tag_ts = str(rec.ts)
            break
    min_low = float(np.nanmin(w["low"].to_numpy(dtype=float)))
    min_dist_atr = (min_low - level) / atr if atr and np.isfinite(atr) and atr > 0 else float("nan")
    min_dist_pct = (min_low - level) / level * 100.0 if level else float("nan")
    close_enough_low = bool(np.isfinite(min_dist_atr) and min_dist_atr <= ZONE_ATR_MULT)
    return {
        "n_bars": int(len(w)),
        "tagged": tagged,
        "tag_ts": tag_ts,
        "min_low": min_low,
        "min_dist_atr": min_dist_atr,
        "min_dist_pct": min_dist_pct,
        "close_enough_low": close_enough_low,
    }


def _clock_dist(day_df: pd.DataFrame, clock: time, level: float, band: float, atr: float) -> dict[str, Any]:
    bar = _bar_at_or_after(day_df, clock)
    if bar is None:
        return {
            "ts": "",
            "low": float("nan"),
            "dist_atr": float("nan"),
            "dist_pct": float("nan"),
            "in_band": False,
        }
    lo = float(bar["low"])
    hi = float(bar["high"])
    dist_atr = (lo - level) / atr if atr and np.isfinite(atr) and atr > 0 else float("nan")
    dist_pct = (lo - level) / level * 100.0 if level else float("nan")
    return {
        "ts": str(bar["ts"]),
        "low": lo,
        "dist_atr": dist_atr,
        "dist_pct": dist_pct,
        "in_band": _intersects(lo, hi, level, band),
    }


def _tod_bucket(ts: Any) -> str:
    t = _tod(ts)
    if t < NOON:
        return "morning"
    return "afternoon"


def load_chandelier_book() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with TRADES_CSV.open(newline="", encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            if (
                raw.get("htf") != HTF
                or raw.get("ltf") != LTF
                or raw.get("arm") != ARM
            ):
                continue
            entry_d = date.fromisoformat(str(raw["entry_date"])[:10])
            rows.append(
                {
                    "symbol": str(raw["symbol"]).strip().upper(),
                    "htf": HTF,
                    "ltf": LTF,
                    "arm": ARM,
                    "level": float(raw["level"]),
                    "htf_atr": float(raw["htf_atr"]),
                    "break_ts": raw["break_ts"],
                    "retest_ts": raw["retest_ts"],
                    "entry_date": entry_d,
                    "session": str(raw.get("session", "")),
                    "split": str(raw.get("split", "")),
                    "entry_px": float(raw["entry_px"]),
                    "exit_px": float(raw["exit_px"]),
                    "exit_type": str(raw["exit_type"]),
                    "pnl_pct": float(raw["pnl_pct"]),
                    "r_mult": float(raw["r_mult"]),
                    "entry_ts": raw["entry_ts"],
                    "exit_ts": raw["exit_ts"],
                    "hold_min": float(raw["hold_min"]),
                    "shares": float(raw["shares"]),
                    "pnl_usd": float(raw["pnl_usd"]),
                    "win": int(float(raw["win"])),
                }
            )
    rows.sort(key=lambda r: (r["entry_ts"], r["symbol"]))
    return rows


def match_liked(book: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    notes: list[dict[str, Any]] = []
    liked_keys: set[tuple[str, date]] = set()
    used: set[int] = set()
    for sym, d, hint_pnl, hint_exit in LIKED_HINTS:
        cands = [
            (i, r)
            for i, r in enumerate(book)
            if r["symbol"] == sym and r["entry_date"] == d and i not in used
        ]
        if not cands:
            notes.append(
                {
                    "symbol": sym,
                    "date": d.isoformat(),
                    "status": "MISSING",
                    "hint_pnl": hint_pnl,
                    "hint_exit": hint_exit,
                    "note": "no 4h×1m chandelier-3 row on this date",
                }
            )
            continue
        # Prefer the row whose PnL is closest to Paul's print.
        i, r = min(cands, key=lambda x: abs(x[1]["pnl_pct"] - hint_pnl))
        used.add(i)
        liked_keys.add((sym, d))
        pnl_off = abs(r["pnl_pct"] - hint_pnl)
        exit_off = r["exit_type"] != hint_exit
        status = "exact"
        note = ""
        if pnl_off > 0.02:
            status = "pnl_off"
            note = f"book PnL {r['pnl_pct']:+.3f}% vs Paul {hint_pnl:+.3f}%"
        elif pnl_off > 0.0005:
            status = "pnl_round"
            note = f"book {r['pnl_pct']:+.4f}% vs listed {hint_pnl:+.3f}%"
        if exit_off:
            status = "exit_off"
            note = (note + "; " if note else "") + f"exit {r['exit_type']} vs {hint_exit}"
        notes.append(
            {
                "symbol": sym,
                "date": d.isoformat(),
                "status": status,
                "hint_pnl": hint_pnl,
                "hint_exit": hint_exit,
                "book_pnl": r["pnl_pct"],
                "book_exit": r["exit_type"],
                "note": note,
            }
        )
        r["liked"] = True
        r["liked_match"] = status
    for r in book:
        r.setdefault("liked", False)
        r.setdefault("liked_match", "")
    return book, notes


def measure_trade(row: dict[str, Any], rth: pd.DataFrame) -> dict[str, Any]:
    level = float(row["level"])
    atr = float(row["htf_atr"])
    band = ZONE_ATR_MULT * atr if atr and atr > 0 else abs(level) * 0.0015
    entry_d = row["entry_date"]
    break_d = _sess_date(row["break_ts"])
    retest_d = _sess_date(row["retest_ts"])
    sessions = sorted({_sess_date(t) for t in rth["ts"]})
    s1 = entry_d
    s0 = None
    for d in sessions:
        if d < s1:
            s0 = d
        else:
            break
    day_s0 = rth.loc[rth["ts"].map(_sess_date) == s0].copy() if s0 else pd.DataFrame()
    day_s1 = rth.loc[rth["ts"].map(_sess_date) == s1].copy()
    next_d = None
    for d in sessions:
        if d > s1:
            next_d = d
            break
    day_next = rth.loc[rth["ts"].map(_sess_date) == next_d].copy() if next_d else pd.DataFrame()

    break_same_day = break_d == s1
    fill_kind = "same_day" if break_same_day else "overnight"
    # EOD approach is only a post-break retest-approach if the break is on/before S0.
    eod_eligible = bool(s0 is not None and break_d <= s0)
    eod = _window_stats(day_s0, EOD_START, EOD_END, level, band, atr) if eod_eligible else {
        "n_bars": 0,
        "tagged": False,
        "tag_ts": "",
        "min_low": float("nan"),
        "min_dist_atr": float("nan"),
        "min_dist_pct": float("nan"),
        "close_enough_low": False,
    }
    am = _window_stats(day_s1, AM_START, AM_END, level, band, atr)
    retest_in_am = AM_START <= _tod(row["retest_ts"]) < AM_END and retest_d == s1
    entry_in_am = AM_START <= _tod(row["entry_ts"]) < AM_END
    am_retest = bool(am["tagged"] or retest_in_am)
    pattern = bool(eod_eligible and eod["tagged"] and am_retest)

    # Sensitivity (not the freeze)
    eod_1530 = _window_stats(day_s0, EOD_START_LATE, EOD_END, level, band, atr) if eod_eligible else {"tagged": False}
    am_1000 = _window_stats(day_s1, AM_START, AM_END_EARLY, level, band, atr)
    pattern_tight = bool(eod_eligible and eod_1530.get("tagged") and (am_1000["tagged"] or retest_in_am))

    # Diagnostic: EOD of the fill day (after a same-day fill this is not "precede")
    eod_s1 = _window_stats(day_s1, EOD_START, EOD_END, level, band, atr)
    am_next = _window_stats(day_next, AM_START, AM_END, level, band, atr) if next_d else {
        "tagged": False, "min_dist_atr": float("nan")
    }

    clocks_s0 = {
        "1500": _clock_dist(day_s0, time(15, 0), level, band, atr) if eod_eligible else {},
        "1530": _clock_dist(day_s0, time(15, 30), level, band, atr) if eod_eligible else {},
        "1555": _clock_dist(day_s0, time(15, 55), level, band, atr) if eod_eligible else {},
    }
    clocks_s1 = {
        "0930": _clock_dist(day_s1, time(9, 30), level, band, atr),
        "1000": _clock_dist(day_s1, time(10, 0), level, band, atr),
    }

    out = dict(row)
    out.update(
        {
            "zone_lo": level - band,
            "zone_hi": level + band,
            "band": band,
            "break_date": break_d.isoformat(),
            "retest_date": retest_d.isoformat(),
            "s0": s0.isoformat() if s0 else "",
            "s1": s1.isoformat(),
            "s0_exists": bool(s0),
            "eod_eligible": eod_eligible,
            "fill_kind": fill_kind,
            "break_tod": _tod_bucket(row["break_ts"]),
            "retest_tod": _tod_bucket(row["retest_ts"]),
            "entry_tod": _tod_bucket(row["entry_ts"]),
            "break_hhmm": _hhmm(row["break_ts"]),
            "retest_hhmm": _hhmm(row["retest_ts"]),
            "entry_hhmm": _hhmm(row["entry_ts"]),
            "exit_hhmm": _hhmm(row["exit_ts"]),
            "eod_tagged": bool(eod["tagged"]),
            "eod_tag_ts": eod["tag_ts"],
            "eod_min_dist_atr": eod["min_dist_atr"],
            "eod_min_dist_pct": eod["min_dist_pct"],
            "eod_close_enough_low": bool(eod["close_enough_low"]),
            "eod_n_bars": eod["n_bars"],
            "am_tagged": bool(am["tagged"]),
            "am_tag_ts": am["tag_ts"],
            "am_min_dist_atr": am["min_dist_atr"],
            "am_min_dist_pct": am["min_dist_pct"],
            "am_retest": am_retest,
            "retest_in_am_window": retest_in_am,
            "entry_in_am_window": entry_in_am,
            "pattern": pattern,
            "pattern_tight_sens": pattern_tight,
            "eod_s1_tagged": bool(eod_s1["tagged"]),
            "eod_s1_min_dist_atr": eod_s1["min_dist_atr"],
            "am_next_tagged": bool(am_next.get("tagged")),
            "s0_1500_dist_atr": clocks_s0["1500"].get("dist_atr", float("nan")),
            "s0_1530_dist_atr": clocks_s0["1530"].get("dist_atr", float("nan")),
            "s0_1555_dist_atr": clocks_s0["1555"].get("dist_atr", float("nan")),
            "s1_0930_dist_atr": clocks_s1["0930"].get("dist_atr", float("nan")),
            "s1_1000_dist_atr": clocks_s1["1000"].get("dist_atr", float("nan")),
            "s0_1500_in_band": bool(clocks_s0["1500"].get("in_band", False)),
            "s0_1530_in_band": bool(clocks_s0["1530"].get("in_band", False)),
            "s0_1555_in_band": bool(clocks_s0["1555"].get("in_band", False)),
            "s1_0930_in_band": bool(clocks_s1["0930"].get("in_band", False)),
            "s1_1000_in_band": bool(clocks_s1["1000"].get("in_band", False)),
        }
    )
    return out


def _mean(xs: list[float]) -> float:
    return float(np.mean(xs)) if xs else float("nan")


def _median(xs: list[float]) -> float:
    return float(np.median(xs)) if xs else float("nan")


def book_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {"N": 0}
    pnls = [float(r["pnl_pct"]) for r in rows]
    usd = [float(r["pnl_usd"]) for r in rows]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    flats = [p for p in pnls if p == 0]
    win_usd = [u for u, p in zip(usd, pnls) if p > 0]
    loss_usd = [u for u, p in zip(usd, pnls) if p < 0]
    wo_max = sorted(pnls)
    avg_wo_max = _mean(wo_max[:-1]) if n >= 2 else float("nan")
    pf = (sum(win_usd) / abs(sum(loss_usd))) if loss_usd and sum(loss_usd) != 0 else (float("inf") if win_usd else float("nan"))
    holds = [float(r["hold_min"]) for r in rows]
    days = [float(r["hold_min"]) / (24.0 * 60.0) for r in rows]
    exits = Counter(str(r["exit_type"]) for r in rows)
    overlay_rows = [
        {
            "pnl_d": float(r["pnl_usd"]),
            "pnl": float(r["pnl_pct"]),
            "days": float(r["hold_min"]) / (24.0 * 60.0),
            "opened": _sess_date(r["entry_ts"]),
            "closed": _sess_date(r["exit_ts"]),
        }
        for r in rows
    ]
    ov = overlay_ann_ror_max_dd(
        overlay_rows,
        cash=SHEET,
        initial_account=INIT_ACCT,
        pnl_d_key="pnl_d",
        days_key="days",
        closed_key="closed",
        opened_key="opened",
        pnl_pct_key="pnl",
    )
    avg_hold_day = _mean(days)
    # Parent freeze: Ann ROR only when avg hold ≥ 0.5 day (these are scalps).
    ann_ror = ov["ann_ror"] if avg_hold_day >= 0.5 and math.isfinite(ov["ann_ror"]) else float("nan")
    expectancy_usd = _mean(usd)
    wl_count = (len(wins) / len(losses)) if losses else float("nan")
    wl_usd = (abs(_mean(win_usd)) / abs(_mean(loss_usd))) if win_usd and loss_usd and _mean(loss_usd) != 0 else float("nan")
    return {
        "N": n,
        "Wins": len(wins),
        "Losses": len(losses),
        "Flats": len(flats),
        "Win%": 100.0 * len(wins) / n,
        "Avg_PnL_%": _mean(pnls),
        "Median_PnL_%": _median(pnls),
        "AVG_PNL_PCT_WO_MAX": avg_wo_max,
        "Avg_win_%": _mean(wins),
        "Avg_loss_%": _mean(losses),
        "Expectancy_%": _mean(pnls),
        "Expectancy_$": expectancy_usd,
        "Profit_factor": pf,
        "WL_count": wl_count,
        "WL_$": wl_usd,
        "Avg_hold_min": _mean(holds),
        "Median_hold_min": _median(holds),
        "P90_hold_min": float(np.percentile(holds, 90)) if holds else float("nan"),
        "Avg_days_held": avg_hold_day,
        "Ann_ROR_%": ann_ror,
        "Max_DD_%": ov["max_dd"],
        "Calmar": ov["calmar"] if math.isfinite(ann_ror) and math.isfinite(ov["calmar"]) else float("nan"),
        "Sharpe": ov["sharpe"],
        "sharpe_source": ov.get("sharpe_source", ""),
        "overlay_note": ov.get("note", ""),
        "Profit_per_cap_day": (sum(usd) / sum(days)) if sum(days) > 0 else float("nan"),
        "Capital_days": sum(days),
        "exit_mix": dict(exits),
        "STOP_%": 100.0 * exits.get("STOP", 0) / n,
        "TIME_%": 100.0 * (exits.get("TIME", 0) + exits.get("EOD_FLAT", 0)) / n,
        "HTF_FAIL_%": 100.0 * exits.get("HTF_FAIL", 0) / n,
    }


def _fmt(v: Any, kind: str = "num") -> str:
    if v is None:
        return "—"
    if isinstance(v, float) and not math.isfinite(v):
        return "—"
    if kind == "pct":
        return f"{float(v):+.3f}%"
    if kind == "pct0":
        return f"{float(v):.1f}%"
    if kind == "atr":
        return f"{float(v):+.2f}"
    if kind == "num":
        if isinstance(v, float) and abs(v) >= 100:
            return f"{v:.2f}"
        if isinstance(v, float):
            return f"{v:.3f}"
        return str(v)
    if kind == "yn":
        return "YES" if v else "NO"
    if kind == "money":
        return format_money(v)
    return str(v)


def _sortable_th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{html_mod.escape(kind)}" '
        f'tabindex="0" role="columnheader" aria-sort="none">'
        f"{html_mod.escape(label)}<span class=\"sort-ind\"></span></th>"
    )


def _rate(rows: list[dict[str, Any]], key: str = "pattern") -> tuple[int, int, float]:
    n = len(rows)
    k = sum(1 for r in rows if r.get(key))
    return k, n, (100.0 * k / n if n else float("nan"))


def find_chart(symbol: str, entry_d: date, entry_hhmm: str) -> str:
    if not CHART_DIR.is_dir():
        return ""
    needle = f"_{symbol}_{entry_d.isoformat()}_"
    hits = sorted(CHART_DIR.glob(f"*{needle}*.png"))
    if not hits:
        return ""
    # Prefer filename time matching entry.
    hhmm = entry_hhmm.replace(":", "")
    for p in hits:
        if hhmm in p.name:
            return p.as_posix()
    return hits[0].as_posix()


def write_baseline(
    liked_notes: list[dict[str, Any]],
    n_book: int,
    *,
    verdict: str = "",
    verdict_why: str = "",
) -> None:
    liked_lines = "\n".join(
        f"- {n['symbol']} {n['date']}: match={n['status']}"
        + (f" ({n['note']})" if n.get("note") else "")
        for n in liked_notes
    )
    text = f"""# BASELINE — EOD approach + next-AM retest on chandelier-3 — `{STAMP}`

**System:** pattern slice on parent `{PARENT_STAMP}` `4h × 1m × trail_chandelier_3`. **Not** DailyRun. **Not** gold. Research only.

## What you asked

> I like the following. are there any patterns in these trades that preceeed the gains that the other charts don't have?
>
> LLY · 2026-08-07 · +2.076% · STOP
> ASML · 2026-08-17 · +0.359% · STOP
> MA · 2026-08-19 · +1.316% · STOP
> TSLA · 2026-08-19 · +0.458% · STOP
> TSLA · 2026-08-24 · +1.063% · STOP
> NVDA · 2026-08-28 · +0.966% · STOP
>
> there's a lot that i'm seeing that dip close to the zone for a retest near the end of the day and then at the beginning of the next day if the retest happens, then we're off
> i don't know if that's true. but please check
> META · 2026-09-02 · +0.460% · STOP
> AAPL · 2026-09-14 · +0.684% · STOP

## In plain English

Paul liked eight green trades in the 4-hour / 1-minute chandelier gallery. He thinks many of them dip toward the zone late in the day, then retest the next morning — and that is when the trade takes off. We checked whether that setup actually happens on those eight, and whether the other charts lack it. High Time Frame (**HTF**) here is the 4-hour bar the swing high is drawn on (parent expansion: High Time Frame, not High Tight Flag). Low Time Frame (**LTF**) is the 1-minute tape. Average True Range (**ATR**) sets the zone width.

## Parent freeze pointer

Do not retune. Identity is the parent 37-trade book:

| Parent knob | Value |
|-------------|--------|
| Stamp | `{PARENT_STAMP}` |
| HTF / LTF / arm | 4h / 1m / `trail_chandelier_3` |
| Zone / retest band | level ± **0.15 × HTF ATR** (bar range intersects the band) |
| Entry | next 1m open after first retest; no entry at/after 15:45 ET |
| Stop | control initial, then chandelier = prior-bar running high − 3 × LTF ATR |
| Session | Regular trading hours 09:30–16:00 ET |
| Tape | `data/intraday/1m/{{SYM}}.parquet` |
| N book | {n_book} (must stay 37) |

## Frozen pattern (locked before scoring lift)

One boolean. Not shopped.

- **Zone tag:** a 1-minute bar’s range intersects `[level − 0.15 × HTF_ATR, level + 0.15 × HTF_ATR]` — the same geometry as the parent retest.
- **S1** = Regular-hours session of the frozen fill (`entry_date`).
- **S0** = the immediately previous Regular-hours session on that symbol’s 1-minute tape.
- **EOD-eligible:** the HTF break session is on or before S0. If the break and the fill are the **same** session, there is no post-break late-day-then-next-morning story — EOD approach is **false**.
- **EOD approach:** EOD-eligible AND at least one zone tag during **15:00–16:00 ET on S0**.
- **Next-AM retest:** at least one zone tag during **09:30–10:30 ET on S1**, OR the frozen retest bar itself sits in that window.
- **Pattern = EOD approach AND next-AM retest.**

These chandelier trades flatten the same session (TIME 15:55 / stop / HTF fail). They do **not** hold overnight. The pattern is a **pre-fill** setup, not an after-entry dip.

## Sensitivity (HOLD notes only — not a second freeze)

1. Tighter windows: EOD 15:30–16:00 and AM 09:30–10:00 (`pattern_tight_sens`).
2. “Low within 0.15 ATR of the level” without requiring the high to complete the intersection (`eod_close_enough_low`). On this tape that almost always matches the tag.

Do not pick a winner between these after seeing the table.

## Liked-8 match

Matched on **symbol + entry date** against the frozen 37. PnL listed by Paul is a check.

{liked_lines}

## Selection bias

The eight names were picked **after** looking at the gallery. Any “pattern the winners have” is in-sample chart-picking. The honest test is pattern-yes vs pattern-no on the **full 37**. Liked-8 rates are descriptive only.

## Split

Parent short-tape split (report-only): IS = `entry_date < 2026-09-02`; OOS = `entry_date >= 2026-09-02`. This slice is not a new portfolio. Ann ROR is omitted when average hold is under 0.5 day (scalps).

## Result (measured after the freeze above — not used to change the boolean)

**{verdict or "pending"}.** {verdict_why}

See `compare.html`. Liked-8 pattern rate and full-37 pattern-yes vs pattern-no are the scored numbers. Sensitivity windows were not adopted.

## Promotion

Research candidate. **Not** gold. **Not** DailyRun. Do not wire a filter from this stamp.
"""
    (OUT_DIR / "BASELINE.md").write_text(text, encoding="utf-8")


def write_hypothesis() -> None:
    text = f"""# HYPOTHESIS — `{STAMP}`

| Field | Fill in |
|-------|---------|
| System / prefix | `intraday_htf_retest` pattern slice (4h × 1m × `trail_chandelier_3`) |
| Baseline stamp | Parent `{PARENT_STAMP}`; this stamp `{STAMP}` |
| Universe | Same PaulTwenty ∩ stored 1m as parent (plus UNH if present) |
| **Evidence** | Paul chart-picked 8 green STOP trades from the 37-chart gallery and described an end-of-day zone dip then next-morning retest |
| **Hypothesis** | An EOD zone approach on S0 plus a next-morning zone retest on S1 precedes the gains in the liked-8 and is absent (or rarer) on the other chandelier-3 charts |
| **Single knob** | Pattern filter (boolean) on an unchanged entry/stop freeze — **not** a new stop or zone width |
| Frozen settings | Parent 4h/1m chandelier-3 identity; zone = level ± 0.15 × HTF ATR; EOD 15:00–16:00 S0; AM 09:30–10:30 S1; same-day break+fill ⇒ pattern false |
| Alternatives | Baseline = no filter (all 37). Candidate = keep only pattern-yes. One sensitivity pair recorded, not scored as a shop |
| Candidate stamps | `{STAMP}` (measure-only; chandelier knobs unchanged) |
| Metrics | Pattern rate liked-8 vs other-29 vs winners vs losers; Avg PnL% / win% / PF / expectancy / hold / exit mix / Max DD on pattern-yes vs pattern-no. Not max single-trade PnL. Ann ROR omitted (scalps) |
| **Trade-diff HTML** | Not a Closed-vs-Closed engine A/B. Compare is `compare.html` (pattern slice of the same 37) |
| ToS before path | Parent gallery `charts_4h_1m_chandelier3.html` |
| ToS after path | n/a — no new fills |
| **Decision** | see compare.html verdict (HOLD or DISMISS expected; not KEEP / not gold) |
| Reviewer | research agent 2026-09-16 |
| PO sign-off | no |
| Reconcile freeze / re-baseline done | no |

## Decision checklist

- [x] Evidence was a counted chart-pick (N=8 of 37), labeled as selection
- [x] Only one knob (the frozen boolean) differed in the slice
- [x] No chandelier retune
- [ ] Charts still look like a *filter* we would trade — verdict in HTML
- [ ] Drawdown / reconcile acceptable — n/a (not adopting)
- [ ] If adopt: PO signed off — **do not adopt from this stamp**
"""
    (OUT_DIR / "HYPOTHESIS.md").write_text(text, encoding="utf-8")


def _dist_words(atr_dist: float) -> str:
    if not math.isfinite(atr_dist):
        return "no S0 tape"
    if atr_dist <= ZONE_ATR_MULT:
        return f"tagged / within the 0.15 ATR band (closest low {atr_dist:+.2f} ATR vs the level)"
    return f"stayed {atr_dist:+.2f} ATR above the level (outside the 0.15 band)"


def _english_row(r: dict[str, Any]) -> str:
    liked = "liked" if r["liked"] else "other"
    win = "win" if r["pnl_pct"] > 0 else ("flat" if r["pnl_pct"] == 0 else "loss")
    if r["fill_kind"] == "same_day":
        fill = (
            f"same-afternoon fill: 4-hour break {r['break_hhmm']} and 1-minute retest "
            f"{r['retest_hhmm']} on {r['s1']}, entry {r['entry_hhmm']}"
        )
    else:
        fill = (
            f"overnight fill: 4-hour break {r['break_date']} {r['break_hhmm']}, "
            f"1-minute retest {r['retest_date']} {r['retest_hhmm']}, entry {r['entry_hhmm']}"
        )
    if r["pattern"]:
        pat = "MATCHES the frozen end-of-day then next-morning pattern"
    elif r["fill_kind"] == "same_day":
        pat = (
            "does NOT match — break and retest are the same session, so there is no "
            "late-day-then-next-morning setup"
        )
    elif not r["eod_eligible"]:
        pat = "does NOT match — no eligible prior session after the break"
    elif not r["eod_tagged"]:
        pat = (
            "does NOT match — morning retest/fill is real, but the prior session "
            f"15:00-16:00 {_dist_words(r['eod_min_dist_atr'])}"
        )
    elif not r["am_retest"]:
        pat = "does NOT match — prior end-of-day tagged, but no 09:30-10:30 tag or fill"
    else:
        pat = "does NOT match"
    return (
        f"{r['symbol']} {r['s1']} ({liked}, {win} {r['pnl_pct']:+.3f}% {r['exit_type']}, "
        f"{r['hold_min']:.0f} min): {fill}. {pat}."
    )


def write_html(
    measured: list[dict[str, Any]],
    liked_notes: list[dict[str, Any]],
    metrics: dict[str, dict[str, Any]],
    rates: dict[str, Any],
    verdict: str,
    verdict_why: str,
    english_liked: list[str],
    english_counter: list[str],
) -> None:
    def ths(cols: list[tuple[str, str]]) -> str:
        return "".join(_sortable_th(a, b) for a, b in cols)

    def rate_row(label: str, rec: dict[str, Any]) -> str:
        return (
            f"<tr><td>{html_mod.escape(label)}</td>"
            f"<td>{rec['k']}</td><td>{rec['n']}</td>"
            f"<td>{rec['pct']:.1f}%</td></tr>"
        )

    book_cols = [
        ("Slice", "text"),
        ("N", "num"),
        ("Wins", "num"),
        ("Losses", "num"),
        ("Win %", "num"),
        ("Avg PnL %", "num"),
        ("Median PnL %", "num"),
        ("AVG_PNL_PCT_WO_MAX", "num"),
        ("Avg win %", "num"),
        ("Avg loss %", "num"),
        ("Expectancy %", "num"),
        ("Expectancy $", "num"),
        ("Profit factor", "num"),
        ("Win/Loss count", "num"),
        ("Win/Loss $", "num"),
        ("Avg hold min", "num"),
        ("Median hold min", "num"),
        ("P90 hold min", "num"),
        ("Capital days", "num"),
        ("Profit / capital day", "num"),
        ("Ann ROR %", "num"),
        ("Max DD %", "num"),
        ("Calmar", "num"),
        ("Sharpe", "num"),
        ("STOP %", "num"),
        ("TIME/EOD %", "num"),
        ("HTF_FAIL %", "num"),
    ]

    def book_row(name: str, m: dict[str, Any], extra_class: str = "") -> str:
        cls = f' class="{extra_class}"' if extra_class else ""
        cells = [
            html_mod.escape(name),
            str(m.get("N", 0)),
            str(m.get("Wins", 0)),
            str(m.get("Losses", 0)),
            _fmt(m.get("Win%"), "pct0"),
            _fmt(m.get("Avg_PnL_%"), "pct"),
            _fmt(m.get("Median_PnL_%"), "pct"),
            _fmt(m.get("AVG_PNL_PCT_WO_MAX"), "pct"),
            _fmt(m.get("Avg_win_%"), "pct"),
            _fmt(m.get("Avg_loss_%"), "pct"),
            _fmt(m.get("Expectancy_%"), "pct"),
            _fmt(m.get("Expectancy_$"), "money"),
            _fmt(m.get("Profit_factor"), "num"),
            _fmt(m.get("WL_count"), "num"),
            _fmt(m.get("WL_$"), "num"),
            _fmt(m.get("Avg_hold_min"), "num"),
            _fmt(m.get("Median_hold_min"), "num"),
            _fmt(m.get("P90_hold_min"), "num"),
            _fmt(m.get("Capital_days"), "num"),
            _fmt(m.get("Profit_per_cap_day"), "money"),
            _fmt(m.get("Ann_ROR_%"), "pct"),
            _fmt(m.get("Max_DD_%"), "pct"),
            _fmt(m.get("Calmar"), "num"),
            _fmt(m.get("Sharpe"), "num"),
            _fmt(m.get("STOP_%"), "pct0"),
            _fmt(m.get("TIME_%"), "pct0"),
            _fmt(m.get("HTF_FAIL_%"), "pct0"),
        ]
        return f"<tr{cls}>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"

    trade_cols = [
        ("Liked", "text"),
        ("Pattern", "text"),
        ("Symbol", "text"),
        ("Entry date", "date"),
        ("PnL %", "num"),
        ("Win", "text"),
        ("Exit", "text"),
        ("Hold min", "num"),
        ("Fill kind", "text"),
        ("Break", "text"),
        ("Retest", "text"),
        ("Entry", "text"),
        ("S0", "date"),
        ("EOD tag S0", "text"),
        ("EOD min dist ATR", "num"),
        ("AM retest S1", "text"),
        ("AM min dist ATR", "num"),
        ("S0 15:00 ATR", "num"),
        ("S0 15:30 ATR", "num"),
        ("S0 15:55 ATR", "num"),
        ("S1 09:30 ATR", "num"),
        ("S1 10:00 ATR", "num"),
        ("Break session", "text"),
        ("Split", "text"),
        ("Chart", "text"),
    ]

    def trade_row(r: dict[str, Any]) -> str:
        cls = "liked" if r["liked"] else ("pattern" if r["pattern"] else "")
        chart = r.get("chart_rel") or ""
        chart_cell = (
            f'<a href="{html_mod.escape(chart)}">png</a>' if chart else "—"
        )
        cells = [
            "YES" if r["liked"] else "",
            "YES" if r["pattern"] else "no",
            html_mod.escape(r["symbol"]),
            r["s1"],
            f"{r['pnl_pct']:+.3f}%",
            "W" if r["pnl_pct"] > 0 else ("F" if r["pnl_pct"] == 0 else "L"),
            html_mod.escape(r["exit_type"]),
            f"{r['hold_min']:.0f}",
            html_mod.escape(r["fill_kind"]),
            f"{r['break_date']} {r['break_hhmm']}",
            f"{r['retest_date']} {r['retest_hhmm']}",
            r["entry_hhmm"],
            r["s0"] or "—",
            "YES" if r["eod_tagged"] else ("n/a" if not r["eod_eligible"] else "no"),
            _fmt(r["eod_min_dist_atr"], "atr"),
            "YES" if r["am_retest"] else "no",
            _fmt(r["am_min_dist_atr"], "atr"),
            _fmt(r["s0_1500_dist_atr"], "atr"),
            _fmt(r["s0_1530_dist_atr"], "atr"),
            _fmt(r["s0_1555_dist_atr"], "atr"),
            _fmt(r["s1_0930_dist_atr"], "atr"),
            _fmt(r["s1_1000_dist_atr"], "atr"),
            html_mod.escape(r["break_tod"]),
            html_mod.escape(r["split"]),
            chart_cell,
        ]
        return f'<tr class="{cls}">' + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"

    match_rows = []
    for n in liked_notes:
        match_rows.append(
            "<tr>"
            f"<td>{html_mod.escape(n['symbol'])}</td>"
            f"<td>{html_mod.escape(n['date'])}</td>"
            f"<td>{html_mod.escape(n['status'])}</td>"
            f"<td>{n['hint_pnl']:+.3f}%</td>"
            f"<td>{_fmt(n.get('book_pnl'), 'pct')}</td>"
            f"<td>{html_mod.escape(n.get('hint_exit', ''))}</td>"
            f"<td>{html_mod.escape(n.get('book_exit', ''))}</td>"
            f"<td>{html_mod.escape(n.get('note') or '')}</td>"
            "</tr>"
        )

    liked_ul = "".join(f"<li>{html_mod.escape(s)}</li>" for s in english_liked)
    counter_ul = "".join(f"<li>{html_mod.escape(s)}</li>" for s in english_counter)
    chart_notes = [
        "LLY 8/7 (liked, +2.08%): 4-hour pane shows the break late on 8/5, then a full 8/6 session that stays above the band. The 1-minute pane starts at the 09:35 fill and runs. That is a morning retest after a quiet prior day — not a late-day tag.",
        "ASML 8/17 (liked, +0.36%): 1-minute pane is an afternoon break at 13:30 and an immediate retest. No next morning.",
        "MA 8/19 (liked, +1.32%): overnight morning fill at 09:31 that runs. Prior session 15:00-16:00 stayed +0.44 ATR above the level.",
        "TSLA 8/19 (liked, +0.46%): same-afternoon 13:31 retest after the 13:30 break. Classic same-day, not overnight.",
        "TSLA 8/24 (liked, +1.06%): Monday 09:39 fill after Friday 13:30 break. Friday close was +1.18 ATR above the zone — nowhere near. The 1-minute dip you see is the Monday morning retest itself.",
        "NVDA 8/28 (liked, +0.97%): 1-minute pane shows a same-morning fade from ~09:36 into the band at 10:12, then it runs. That is the fill, not yesterday’s close. Prior day 15:00-16:00 stayed +0.53 ATR above.",
        "META 9/2 (liked, +0.46%): afternoon break 13:30, retest 14:47, done by 15:01. Same session.",
        "AAPL 9/14 (liked, +0.68%): Monday 09:36 fill after Friday 13:30 break. Closest prior-close approach in the liked set (+0.22 ATR) — still outside the 0.15 band. HOLD note only; do not widen the band after seeing this.",
        "MSFT 8/7 (other, +0.04%): this one DOES match EOD tag + next-morning fill. Tiny winner, not in the liked list.",
        "AMD 8/26 (other, +0.68%): also matches. Green, not in the liked list — so the pattern is not exclusive to the pictures he circled.",
        "LLY 8/11 and V 8/14 (other, both red): also match, then stop out on the first 1-minute bar. The geometry he described shows up on losers.",
        "AMD 8/5 (other, −0.51%): related near-story — 15:59 retest on 8/4, next-open fill, immediate stop. End-of-day tag then morning fill can fail hard when it gaps through.",
    ]
    chart_ul = "".join(f"<li>{html_mod.escape(s)}</li>" for s in chart_notes)

    same_day_liked = sum(1 for r in measured if r["liked"] and r["fill_kind"] == "same_day")
    overnight_liked = sum(1 for r in measured if r["liked"] and r["fill_kind"] == "overnight")
    pattern_liked = sum(1 for r in measured if r["liked"] and r["pattern"])

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>EOD dip + next-morning retest — {html_mod.escape(STAMP)}</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 24px; color: #0f172a; background: #f8fafc; }}
h1 {{ font-size: 1.45rem; margin: 0 0 4px; }}
h2 {{ font-size: 1.15rem; margin: 1.6rem 0 .5rem; border-bottom: 1px solid #cbd5e1; padding-bottom: .25rem; }}
.sub, .meta {{ color: #475569; font-size: .92rem; max-width: 78rem; line-height: 1.5; }}
.callout {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: .85rem 1rem; margin: .75rem 0; max-width: 78rem; }}
.idea {{ background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; padding: .85rem 1rem; margin: .6rem 0; max-width: 78rem; }}
.verdict {{ background: #f1f5f9; border: 1px solid #94a3b8; border-radius: 8px; padding: .85rem 1rem; margin: .6rem 0; max-width: 78rem; }}
.verdict.dismiss {{ background: #fef2f2; border-color: #fecaca; }}
.verdict.hold {{ background: #fffbeb; border-color: #fde68a; }}
.tag {{ display: inline-block; background: #92400e; color: #fff; font-size: 11px; padding: 1px 6px; border-radius: 999px; margin-right: 6px; }}
.cards {{ display: flex; flex-wrap: wrap; gap: 12px; margin: 16px 0 24px; }}
.card {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px 16px; min-width: 180px; flex: 1 1 180px; }}
.card h3 {{ margin: 0 0 8px; font-size: 13px; color: #475569; }}
.metric {{ font-size: 1.25rem; font-weight: 700; line-height: 1.25; }}
.small {{ font-size: 12px; color: #64748b; }}
.table-wrap {{ overflow-x: auto; margin: 8px 0; }}
table.sortable {{ border-collapse: collapse; background: #fff; font-size: 12px; width: 100%; }}
table.sortable th, table.sortable td {{ border: 1px solid #e2e8f0; padding: 6px 8px; text-align: left; vertical-align: top; }}
table.sortable th {{ background: #f1f5f9; }}
tr.liked td {{ background: #ecfdf5; }}
tr.pattern td {{ background: #eff6ff; }}
tr.liked.pattern td {{ background: #d1fae5; }}
tr.total-row td {{ background: #e0f2fe; font-weight: 600; }}
blockquote {{ margin: .4rem 0; padding-left: .8rem; border-left: 3px solid #cbd5e1; color: #334155; }}
ul.meta li {{ margin: .25rem 0; }}
{SORT_CSS}
</style></head><body>
<h1>Late-day dip, then next-morning retest?</h1>
<p class="sub">Research pattern check on the frozen 37-trade 4-hour × 1-minute <code>trail_chandelier_3</code> book.
Parent <code>{html_mod.escape(PARENT_STAMP)}</code>. Stamp <code>{html_mod.escape(STAMP)}</code>.
Not gold. Not DailyRun. Click column headers to sort.</p>

<div class="callout">
<h2 style="margin-top:0">What you asked</h2>
<blockquote>{html_mod.escape(ORIGINAL_REQUEST).replace(chr(10), '<br/>')}</blockquote>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN_ENGLISH)}</p>
</div>

<div class="verdict {html_mod.escape(verdict.lower())}">
<p><span class="tag">{html_mod.escape(verdict)}</span>
<strong>{html_mod.escape(verdict_why)}</strong></p>
<p class="small">N=37 total, N=8 selected after looking at charts. In-sample chart-picking.
Do not retune the chandelier freeze. Do not wire DailyRun.</p>
</div>

<div class="cards">
<div class="card"><h3>Liked-8 that match EOD→AM</h3><div class="metric">{pattern_liked} / 8</div><div class="small">Frozen boolean</div></div>
<div class="card"><h3>Liked-8 same-day fills</h3><div class="metric">{same_day_liked} / 8</div><div class="small">Overnight fills: {overnight_liked}</div></div>
<div class="card"><h3>Pattern rate liked-8</h3><div class="metric">{rates['liked']['pct']:.0f}%</div><div class="small">{rates['liked']['k']} of {rates['liked']['n']}</div></div>
<div class="card"><h3>Pattern rate other-29</h3><div class="metric">{rates['other']['pct']:.0f}%</div><div class="small">{rates['other']['k']} of {rates['other']['n']}</div></div>
<div class="card"><h3>Pattern rate all winners</h3><div class="metric">{rates['winners']['pct']:.0f}%</div><div class="small">{rates['winners']['k']} of {rates['winners']['n']}</div></div>
<div class="card"><h3>Pattern rate all losers</h3><div class="metric">{rates['losers']['pct']:.0f}%</div><div class="small">{rates['losers']['k']} of {rates['losers']['n']}</div></div>
<div class="card"><h3>Full-37 pattern-yes Avg PnL</h3><div class="metric">{_fmt(metrics['pattern_yes'].get('Avg_PnL_%'), 'pct')}</div><div class="small">N={metrics['pattern_yes'].get('N', 0)} · WR {_fmt(metrics['pattern_yes'].get('Win%'), 'pct0')}</div></div>
<div class="card"><h3>Full-37 pattern-no Avg PnL</h3><div class="metric">{_fmt(metrics['pattern_no'].get('Avg_PnL_%'), 'pct')}</div><div class="small">N={metrics['pattern_no'].get('N', 0)} · WR {_fmt(metrics['pattern_no'].get('Win%'), 'pct0')}</div></div>
</div>

<div class="idea">
<h2 style="margin-top:0">Frozen rule (one boolean)</h2>
<ul class="meta">
<li><strong>Zone tag</strong> — 1-minute bar intersects the parent band (level ± 0.15 × HTF ATR).</li>
<li><strong>EOD approach</strong> — a tag in 15:00–16:00 ET on S0, and the 4-hour break was on or before S0.</li>
<li><strong>Next-AM retest</strong> — a tag in 09:30–10:30 ET on S1, or the frozen fill’s retest bar is in that window.</li>
<li><strong>Pattern</strong> — both. Same-day break + retest ⇒ pattern is no (there is no “next morning after a late-day dip”).</li>
</ul>
</div>

<h2>Did we find Paul’s eight?</h2>
<p class="small">Matched on symbol + entry date. PnL listed by Paul is a check — nothing was silently dropped.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>
{ths([("Symbol","text"),("Date","date"),("Match","text"),("Paul PnL","num"),("Book PnL","num"),("Paul exit","text"),("Book exit","text"),("Note","text")])}
</tr></thead><tbody>
{''.join(match_rows)}
</tbody></table></div>

<h2>His eight, in English</h2>
<ul class="meta">{liked_ul}</ul>

<h2>What the pictures actually show</h2>
<p class="small">Parent gallery PNGs, plus the 1-minute tape. Several liked 1-minute panes only start at the retest — a dip into the band on that pane is the fill, not yesterday’s close.</p>
<ul class="meta">{chart_ul}</ul>

<h2>Counterexamples (why the story fails as a filter)</h2>
<ul class="meta">{counter_ul}</ul>

<h2>Pattern rate by group</h2>
<p class="small">Click headers to sort. Liked-8 is a selected sample. Full-37 is the honest test.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>
{ths([("Group","text"),("Pattern yes","num"),("N","num"),("Rate","num")])}
</tr></thead><tbody>
{rate_row("Liked-8 (chart-picked)", rates["liked"])}
{rate_row("Other 29", rates["other"])}
{rate_row("All winners (PnL% &gt; 0)", rates["winners"])}
{rate_row("All losers (PnL% &lt; 0)", rates["losers"])}
{rate_row("All 37", rates["all"])}
{rate_row("Overnight fills only", rates["overnight"])}
{rate_row("Same-day fills only", rates["same_day"])}
{rate_row("Tight windows (HOLD note)", rates["tight"])}
</tbody></table></div>

<h2>Pattern-yes vs pattern-no (full 37 — honest test)</h2>
<p class="small">Slice of the same 37 chandelier trades, not a new portfolio. Ann ROR is blank because average hold is minutes, not ≥ 0.5 day (parent rule). Max DD is an exit-date $ replay on a $500,000 seed with $45,000 sheet notional — descriptive only. Click headers to sort.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>
{ths(book_cols)}
</tr></thead><tbody>
{book_row("All 37 (no filter)", metrics["all"])}
{book_row("Pattern yes", metrics["pattern_yes"])}
{book_row("Pattern no", metrics["pattern_no"])}
{book_row("Liked-8 (selected)", metrics["liked"])}
{book_row("Other 29", metrics["other"])}
{book_row("Winners", metrics["winners"])}
{book_row("Losers", metrics["losers"])}
</tbody></table></div>
<p class="small">Overlay note (pattern yes): {html_mod.escape(str(metrics['pattern_yes'].get('overlay_note') or '—'))}.
Sharpe source: {html_mod.escape(str(metrics['pattern_yes'].get('sharpe_source') or '—'))}.</p>

<h2>Every trade</h2>
<p class="small">Green rows = liked-8. Distance columns are (1-minute Low − level) / HTF ATR at that clock (or the next bar). Negative = low already through the level. Click headers to sort. Chart links go to the parent gallery PNGs.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>
{ths(trade_cols)}
</tr></thead><tbody>
{''.join(trade_row(r) for r in measured)}
</tbody></table></div>

<h2>Honesty</h2>
<ul class="meta">
<li>N=37 is small. N=8 was chosen after seeing the pictures. That is selection bias even if an out-of-sample row is printed.</li>
<li>Parent out-of-sample cut is <code>entry_date &gt;= 2026-09-02</code> (short Yahoo tape). OOS is report-only. We did not retune on it.</li>
<li>Sensitivity (tighter 15:30 / 10:00 windows) is a HOLD note, not a second candidate.</li>
<li>Research only. Not gold. Not DailyRun.</li>
</ul>
<p class="small">Parent gallery: <a href="../intraday_htf_retest_20260916/charts_4h_1m_chandelier3.html">charts_4h_1m_chandelier3.html</a>.</p>
{SORT_JS}
</body></html>
"""
    (OUT_DIR / "compare.html").write_text(html, encoding="utf-8")
    (OUT_DIR / "report.html").write_text(html, encoding="utf-8")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    book = load_chandelier_book()
    if len(book) != 37:
        print(f"WARN: expected 37 chandelier 4h×1m trades, got {len(book)}")
    book, liked_notes = match_liked(book)
    cache: dict[str, pd.DataFrame] = {}
    measured: list[dict[str, Any]] = []
    for row in book:
        sym = row["symbol"]
        if sym not in cache:
            cache[sym] = rth_filter(read_1m(sym, DEFAULT_1M_DIR))
        m = measure_trade(row, cache[sym])
        chart = find_chart(sym, row["entry_date"], m["entry_hhmm"])
        m["chart_path"] = chart
        m["chart_rel"] = (
            f"../{PARENT_STAMP}/charts/{Path(chart).name}" if chart else ""
        )
        measured.append(m)

    liked = [r for r in measured if r["liked"]]
    other = [r for r in measured if not r["liked"]]
    winners = [r for r in measured if r["pnl_pct"] > 0]
    losers = [r for r in measured if r["pnl_pct"] < 0]
    overnight = [r for r in measured if r["fill_kind"] == "overnight"]
    same_day = [r for r in measured if r["fill_kind"] == "same_day"]
    yes = [r for r in measured if r["pattern"]]
    no = [r for r in measured if not r["pattern"]]

    def rec(rows: list[dict[str, Any]], key: str = "pattern") -> dict[str, Any]:
        k, n, pct = _rate(rows, key)
        return {"k": k, "n": n, "pct": pct if n else 0.0}

    rates = {
        "liked": rec(liked),
        "other": rec(other),
        "winners": rec(winners),
        "losers": rec(losers),
        "all": rec(measured),
        "overnight": rec(overnight),
        "same_day": rec(same_day),
        "tight": rec(measured, "pattern_tight_sens"),
    }
    metrics = {
        "all": book_metrics(measured),
        "pattern_yes": book_metrics(yes),
        "pattern_no": book_metrics(no),
        "liked": book_metrics(liked),
        "other": book_metrics(other),
        "winners": book_metrics(winners),
        "losers": book_metrics(losers),
    }

    english_liked = [_english_row(r) for r in liked]
    # Counterexamples: pattern-yes losers, liked same-day, other winners that match, other overnight that miss
    counters: list[str] = []
    for r in measured:
        if r["pattern"] and r["pnl_pct"] < 0:
            counters.append(_english_row(r))
    for r in liked:
        if r["fill_kind"] == "same_day":
            counters.append(
                f"COUNTER (liked but same-day): {_english_row(r)}"
            )
    for r in other:
        if r["pattern"] and r["pnl_pct"] > 0:
            counters.append(
                f"COUNTER (other winner with the pattern): {_english_row(r)}"
            )
    # A couple of clean overnight misses among others
    miss_ov = [r for r in other if r["fill_kind"] == "overnight" and not r["pattern"]]
    for r in miss_ov[:3]:
        counters.append(f"COUNTER (overnight but no EOD→AM): {_english_row(r)}")
    # Dedup while preserving order
    seen: set[str] = set()
    english_counter = []
    for s in counters:
        if s not in seen:
            seen.add(s)
            english_counter.append(s)

    # Verdict from the honest 37-row test + whether liked-8 are mostly same-day.
    liked_pat = rates["liked"]["k"]
    other_pat = rates["other"]["pct"]
    win_pat = rates["winners"]["pct"]
    lose_pat = rates["losers"]["pct"]
    yes_n = metrics["pattern_yes"]["N"]
    no_n = metrics["pattern_no"]["N"]
    yes_avg = metrics["pattern_yes"].get("Avg_PnL_%", float("nan"))
    no_avg = metrics["pattern_no"].get("Avg_PnL_%", float("nan"))
    same_day_liked_n = sum(1 for r in liked if r["fill_kind"] == "same_day")

    if liked_pat <= 2 and same_day_liked_n >= 3:
        verdict = "DISMISS"
        verdict_why = (
            f"The late-day dip then next-morning retest story is not true for these eight "
            f"and is not missing from the other charts. {same_day_liked_n} of 8 are "
            f"same-afternoon break+retest (no overnight). The other "
            f"{8 - same_day_liked_n} are next-morning fills, but none tagged the zone "
            f"in 15:00-16:00 the session before. Frozen pattern hits {liked_pat} of 8 "
            f"liked vs {other_pat:.0f}% of the other 29. Losers print it at {lose_pat:.0f}% "
            f"vs winners {win_pat:.0f}%. On the full 37, pattern-yes Avg PnL "
            f"{yes_avg:+.3f}% (N={yes_n}) does not beat pattern-no {no_avg:+.3f}% (N={no_n})."
        )
    elif yes_n >= 3 and math.isfinite(yes_avg) and math.isfinite(no_avg) and yes_avg <= no_avg + 0.02:
        verdict = "DISMISS"
        verdict_why = (
            f"On the full 37, pattern-yes (N={yes_n}, Avg PnL {yes_avg:+.3f}%) does not "
            f"beat pattern-no (N={no_n}, Avg PnL {no_avg:+.3f}%). Losers also print the "
            f"pattern ({lose_pat:.0f}%) at a similar rate to winners ({win_pat:.0f}%). "
            f"Not a filter."
        )
    elif lose_pat + 5 >= win_pat and liked_pat < 5:
        verdict = "DISMISS"
        verdict_why = (
            f"The pattern is not distinctive of the liked set ({liked_pat}/8) and is "
            f"about as common in losers ({lose_pat:.0f}%) as in winners ({win_pat:.0f}%)."
        )
    else:
        verdict = "HOLD"
        verdict_why = (
            f"Some overnight liked trades do print S0 EOD + S1 AM ({liked_pat}/8), "
            f"but N is tiny, the eight were chart-picked, and same-day fills "
            f"({same_day_liked_n}/8) are a different story. Do not adopt a filter."
        )

    write_baseline(
        liked_notes,
        len(book),
        verdict=verdict,
        verdict_why=verdict_why,
    )
    write_hypothesis()

    fieldnames = [
        "liked", "pattern", "symbol", "s1", "pnl_pct", "exit_type", "hold_min",
        "fill_kind", "break_date", "break_hhmm", "retest_date", "retest_hhmm",
        "entry_hhmm", "exit_hhmm", "s0", "eod_eligible", "eod_tagged",
        "eod_min_dist_atr", "am_retest", "am_tagged", "am_min_dist_atr",
        "retest_in_am_window", "entry_in_am_window", "pattern_tight_sens",
        "s0_1500_dist_atr", "s0_1530_dist_atr", "s0_1555_dist_atr",
        "s1_0930_dist_atr", "s1_1000_dist_atr", "break_tod", "retest_tod",
        "split", "level", "htf_atr", "entry_px", "exit_px", "pnl_usd", "r_mult",
        "eod_s1_tagged", "am_next_tagged", "chart_rel", "liked_match",
    ]
    with (OUT_DIR / "pattern_trades.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in measured:
            w.writerow(r)

    book_fields = [
        "slice", "N", "Wins", "Losses", "Win%", "Avg_PnL_%", "Median_PnL_%",
        "AVG_PNL_PCT_WO_MAX", "Avg_win_%", "Avg_loss_%", "Expectancy_%",
        "Expectancy_$", "Profit_factor", "Avg_hold_min", "Max_DD_%", "STOP_%",
    ]
    with (OUT_DIR / "books.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=book_fields, extrasaction="ignore")
        w.writeheader()
        for name, m in metrics.items():
            row = {"slice": name}
            row.update(m)
            w.writerow(row)

    summary = {
        "stamp": STAMP,
        "parent": PARENT_STAMP,
        "n_book": len(measured),
        "n_liked": len(liked),
        "liked_notes": liked_notes,
        "rates": rates,
        "verdict": verdict,
        "verdict_why": verdict_why,
        "metrics": {
            k: {kk: vv for kk, vv in v.items() if kk != "exit_mix"}
            for k, v in metrics.items()
        },
    }
    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )

    write_html(
        measured,
        liked_notes,
        metrics,
        rates,
        verdict,
        verdict_why,
        english_liked,
        english_counter,
    )

    print(f"book N={len(measured)} liked={len(liked)}")
    print("liked matches:")
    for n in liked_notes:
        print(f"  {n}")
    print("rates:", json.dumps(rates))
    print("verdict:", verdict)
    print(verdict_why.encode("ascii", "replace").decode("ascii"))
    print("liked English:")
    for s in english_liked:
        print(" -", s)
    print("wrote", OUT_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
