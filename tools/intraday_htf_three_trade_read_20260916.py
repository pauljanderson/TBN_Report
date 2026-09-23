#!/usr/bin/env python3
"""Read three Paul-flagged 4h×1m chandelier-3 trades from tape (research).

Reconstructs XOM 2026-09-16, LLY 2026-07-29, ASML 2026-08-04 against the frozen
37-trade book. Contrast: NVDA 2026-08-28. Does not retune the chandelier freeze.

Usage:
  python tools/intraday_htf_three_trade_read_20260916.py
"""
from __future__ import annotations

import html as html_mod
import json
import math
import sys
from datetime import time
from pathlib import Path
from typing import Any, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stock_analysis"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
sys.path.insert(0, str(ROOT / "tools"))

from compare_format import overlay_ann_ror_max_dd  # noqa: E402
from intraday_1m import DEFAULT_1M_DIR, ET, read_1m  # noqa: E402
from intraday_htf_retest_20260916 import (  # noqa: E402
    ENTRY_CUTOFF,
    INIT_ACCT,
    PIVOT_K,
    RETEST_ATR_MULT,
    SESSION_CLOSE,
    SESSION_OPEN,
    SHEET,
    TIME_STOP_T,
    find_htf_breaks,
    fractal_pivots,
    metrics_from_trades,
    resample_from_rth_open,
    rth_filter,
    wilder_atr,
)
from intraday_htf_retest_charts_4h_1m_20260916 import (  # noqa: E402
    _draw_candles,
    _fmt_clock,
    _nearest_idx,
    _set_xticks,
    _ts,
    chandelier_stops,
    nearby_4h_touches,
    slice_1m,
    slice_4h,
)

PARENT_STAMP = "intraday_htf_retest_20260916"
STAMP = "intraday_htf_three_trade_read_20260916"
PARENT = ROOT / "drive" / "paul_experiments" / PARENT_STAMP
OUT = ROOT / "drive" / "paul_experiments" / STAMP
TRADES_CSV = PARENT / "trades.csv"
CHART_DIR = PARENT / "charts"
ARM = "trail_chandelier_3"
HTF = "4h"
LTF = "1m"
LATE_CUTOFF = time(15, 30)
# Freeze retest band (level ± this × HTF ATR). Not a min-break rule.
BAND_ATR = RETEST_ATR_MULT
# What-if min close-through, chosen after measuring ASML 8/4 at +0.160 × 4h ATR.
# In-sample selection. Not pre-registered. Not adopted.
MIN_BREAK_ATR_WHATIF = 0.25

FOCUS = [
    {
        "key": "xom",
        "symbol": "XOM",
        "entry_date": "2026-09-16",
        "hint_pnl": -0.098,
        "hint_exit": "STOP",
        "role": "focus",
    },
    {
        "key": "lly",
        "symbol": "LLY",
        "entry_date": "2026-07-29",
        "hint_pnl": -0.195,
        "hint_exit": "STOP",
        "role": "focus",
    },
    {
        "key": "asml",
        "symbol": "ASML",
        "entry_date": "2026-08-04",
        "hint_pnl": 0.096,
        "hint_exit": "STOP",
        "role": "focus",
    },
    {
        "key": "nvda",
        "symbol": "NVDA",
        "entry_date": "2026-08-28",
        "hint_pnl": 0.966,
        "hint_exit": "STOP",
        "role": "contrast",
    },
]

ORIGINAL_REQUEST = (
    "i don't understand how this is a break and retest\n"
    "XOM · 2026-09-16 · -0.098% · STOP\n"
    "LLY · 2026-07-29 · -0.195% · STOP should not be a trade because it is so close to the close\n"
    "how big is this break? and should it be on the longer timeframe\n"
    "ASML · 2026-08-04 · +0.096% · STOP"
)

PLAIN_ENGLISH = (
    "Paul circled three pictures from the 4-hour / 1-minute chandelier gallery and "
    "asked whether they are real break-and-retest trades. We went back to the frozen "
    "book and the 1-minute tape — not the PNG titles — and wrote down the exact high, "
    "when it broke, when it came back, the fill clock, and how big the poke was. "
    "High Time Frame (HTF) here is the 4-hour bar the swing high is drawn on. "
    "Average True Range (ATR) is a typical-bar-range measure. Regular trading hours "
    "(RTH) are 09:30–16:00 ET. Break and retest (B/R) means price closes through a "
    "prior high, then comes back to that line."
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


def sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _tod(ts: Any) -> time:
    t = _ts(ts)
    return t.time().replace(tzinfo=None)


def _hhmm(ts: Any) -> str:
    return _ts(ts).strftime("%H:%M")


def _iso_clock(ts: Any) -> str:
    return _ts(ts).strftime("%Y-%m-%d %H:%M ET")


def _finite(x: Any, default: float = float("nan")) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def load_arm_trades() -> list[dict[str, Any]]:
    df = pd.read_csv(TRADES_CSV)
    sub = df[(df["htf"] == HTF) & (df["ltf"] == LTF) & (df["arm"] == ARM)].copy()
    sub = sub.sort_values(["entry_ts", "symbol"]).reset_index(drop=True)
    return sub.to_dict(orient="records")


def find_parent_png(trade: dict[str, Any], book_index: int) -> str:
    if not CHART_DIR.is_dir():
        return ""
    sym = str(trade["symbol"]).upper()
    ed = str(trade["entry_date"])
    hhmm = _ts(trade["entry_ts"]).strftime("%H%M")
    stem = f"{book_index:02d}_{sym}_{ed}_{hhmm}.png"
    p = CHART_DIR / stem
    if p.exists():
        return f"../{PARENT_STAMP}/charts/{stem}"
    hits = sorted(CHART_DIR.glob(f"*_{sym}_{ed}_*.png"))
    if hits:
        return f"../{PARENT_STAMP}/charts/{hits[0].name}"
    return ""


def load_symbol(sym: str, cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if sym in cache:
        return cache[sym]
    raw = read_1m(sym, DEFAULT_1M_DIR)
    df1 = rth_filter(raw)
    if df1 is None or df1.empty:
        cache[sym] = {"df1": pd.DataFrame(), "htf": pd.DataFrame(), "h2": pd.DataFrame(), "daily": pd.DataFrame()}
        return cache[sym]
    df1 = df1.copy()
    df1["end_ts"] = df1["ts"] + pd.Timedelta(minutes=1)
    cache[sym] = {
        "df1": df1,
        "htf": resample_from_rth_open(df1, 240),
        "h2": resample_from_rth_open(df1, 120),
        "daily": resample_from_rth_open(df1, 390),
        "atr1": wilder_atr(
            df1["high"].to_numpy(dtype=float),
            df1["low"].to_numpy(dtype=float),
            df1["close"].to_numpy(dtype=float),
        ),
    }
    return cache[sym]


def match_break(htf: pd.DataFrame, trade: dict[str, Any]) -> Optional[dict[str, Any]]:
    if htf is None or htf.empty:
        return None
    breaks = find_htf_breaks(htf, "4h")
    level = float(trade["level"])
    want = _ts(trade["break_ts"])
    best = None
    best_d = 1e18
    for br in breaks:
        if abs(float(br["level"]) - level) > 5e-3:
            continue
        end = _ts(br["break_end_ts"])
        d = abs((end - want).total_seconds())
        if d < best_d:
            best_d = d
            best = br
    if best is None:
        for br in breaks:
            end = _ts(br["break_end_ts"])
            d = abs((end - want).total_seconds())
            if d < best_d:
                best_d = d
                best = br
    return best


def _atr_at(atr: np.ndarray, i: int, fallback: float) -> float:
    if i is None or i < 0 or i >= len(atr):
        return fallback
    v = float(atr[i])
    return v if math.isfinite(v) and v > 0 else fallback


def reconstruct(
    trade: dict[str, Any],
    cache: dict[str, dict[str, Any]],
    *,
    book_index: int,
    focus: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    sym = str(trade["symbol"]).upper()
    pack = load_symbol(sym, cache)
    df1: pd.DataFrame = pack["df1"]
    htf: pd.DataFrame = pack["htf"]
    h2: pd.DataFrame = pack["h2"]
    daily: pd.DataFrame = pack["daily"]
    level = float(trade["level"])
    htf_atr = float(trade["htf_atr"])
    if not math.isfinite(htf_atr) or htf_atr <= 0:
        htf_atr = level * 0.01
    band = RETEST_ATR_MULT * htf_atr
    entry_ts = _ts(trade["entry_ts"])
    exit_ts = _ts(trade["exit_ts"])
    retest_ts = _ts(trade["retest_ts"])
    break_end_book = _ts(trade["break_ts"])
    entry_tod = _tod(entry_ts)
    sess_close = entry_ts.normalize() + pd.Timedelta(hours=16)
    if sess_close.tzinfo is None:
        sess_close = sess_close.tz_localize(ET)
    mins_to_close = max(0.0, (sess_close - entry_ts).total_seconds() / 60.0)
    late_1530 = entry_tod >= LATE_CUTOFF
    late_1545 = entry_tod >= ENTRY_CUTOFF

    out: dict[str, Any] = {
        "symbol": sym,
        "role": (focus or {}).get("role", "book"),
        "key": (focus or {}).get("key", sym.lower()),
        "book_index": book_index,
        "entry_date": str(trade["entry_date"]),
        "split": str(trade.get("split", "")),
        "pnl_pct": float(trade["pnl_pct"]),
        "r_mult": float(trade["r_mult"]),
        "exit_type": str(trade["exit_type"]),
        "hold_min": float(trade["hold_min"]),
        "entry_px": float(trade["entry_px"]),
        "exit_px": float(trade["exit_px"]),
        "stop0": float(trade["stop0"]),
        "stop_final": float(trade["stop_final"]),
        "level": level,
        "htf_atr": htf_atr,
        "band": band,
        "zone_lo": level - band,
        "zone_hi": level + band,
        "break_end_book": _iso_clock(break_end_book),
        "retest_ts": _iso_clock(retest_ts),
        "entry_ts": _iso_clock(entry_ts),
        "exit_ts": _iso_clock(exit_ts),
        "entry_hhmm": _hhmm(entry_ts),
        "exit_hhmm": _hhmm(exit_ts),
        "retest_hhmm": _hhmm(retest_ts),
        "mins_to_1600": mins_to_close,
        "late_1530": late_1530,
        "late_1545_blocked_by_freeze": late_1545,
        "freeze_entry_cutoff": "15:45",
        "freeze_time_stop": "15:55",
        "holds_overnight": False,
        "parent_png": find_parent_png(trade, book_index),
        "empty_tape": df1.empty or htf.empty,
    }
    if df1.empty or htf.empty:
        out["error"] = "missing tape"
        return out

    br = match_break(htf, trade)
    if br is None:
        out["error"] = "could not rematch HTF break"
        return out

    piv_i = int(br["pivot_i"])
    conf_i = int(br["conf_i"])
    break_i = int(br["break_i"])
    htf_ts = pd.to_datetime(htf["ts"], utc=True).dt.tz_convert(ET)
    htf_end = pd.to_datetime(htf["end_ts"], utc=True).dt.tz_convert(ET)
    piv_ts = _ts(htf_ts.iloc[piv_i])
    conf_ts = _ts(htf_ts.iloc[conf_i])
    br_ts = _ts(htf_ts.iloc[break_i])
    br_end = _ts(htf_end.iloc[break_i])
    piv_high = float(htf["high"].iloc[piv_i])
    piv_close = float(htf["close"].iloc[piv_i])
    br_open = float(htf["open"].iloc[break_i])
    br_high = float(htf["high"].iloc[break_i])
    br_low = float(htf["low"].iloc[break_i])
    br_close = float(htf["close"].iloc[break_i])
    close_excess = br_close - level
    high_excess = br_high - level
    close_atr = close_excess / htf_atr
    high_atr = high_excess / htf_atr
    close_pct = 100.0 * close_excess / level if level else float("nan")
    high_pct = 100.0 * high_excess / level if level else float("nan")

    n_flag = max(0, break_i - piv_i)
    window = htf.iloc[piv_i : break_i + 1]
    flag_highs = window["high"].to_numpy(dtype=float)
    flag_lows = window["low"].to_numpy(dtype=float)
    n_zone_highs = int(np.sum((flag_highs >= level - band) & (flag_highs <= level + band)))
    flag_range = float(np.nanmax(flag_highs) - np.nanmin(flag_lows)) if len(window) else float("nan")
    flag_range_atr = flag_range / htf_atr if htf_atr else float("nan")

    k = PIVOT_K["4h"]
    raw_h = fractal_pivots(htf["high"].to_numpy(dtype=float), htf["low"].to_numpy(dtype=float), k)
    swing_idx = {i for kind, i in raw_h if kind == "H"}

    # 1m geometry
    ts1 = pd.to_datetime(df1["ts"], utc=True).dt.tz_convert(ET)
    hi1 = df1["high"].to_numpy(dtype=float)
    lo1 = df1["low"].to_numpy(dtype=float)
    c1 = df1["close"].to_numpy(dtype=float)
    o1 = df1["open"].to_numpy(dtype=float)

    def first_idx(mask: np.ndarray) -> Optional[int]:
        hits = np.flatnonzero(mask)
        return int(hits[0]) if len(hits) else None

    during_break = (ts1 >= br_ts) & (ts1 < br_end)
    first_wick_i = first_idx(during_break.to_numpy() & (hi1 > level))
    first_close_i = first_idx(during_break.to_numpy() & (c1 > level))
    n_1m_above_during = int(np.sum(during_break.to_numpy() & (hi1 > level)))
    n_1m_close_above_during = int(np.sum(during_break.to_numpy() & (c1 > level)))

    after_break = ts1 >= br_end
    before_retest = ts1 < retest_ts
    between = after_break.to_numpy() & before_retest.to_numpy()
    n_between = int(np.sum(between))
    left_band = bool(np.any(between & (lo1 > level + band))) if n_between else False
    max_high_between = float(np.nanmax(hi1[between])) if n_between else float("nan")
    away_atr = (max_high_between - level) / htf_atr if math.isfinite(max_high_between) else 0.0

    retest_i = _nearest_idx(ts1, retest_ts, slop_min=2.0)
    entry_i = _nearest_idx(ts1, entry_ts, slop_min=2.0)
    retest_o = float(o1[retest_i]) if retest_i is not None else float("nan")
    retest_h = float(hi1[retest_i]) if retest_i is not None else float("nan")
    retest_l = float(lo1[retest_i]) if retest_i is not None else float("nan")
    retest_c = float(c1[retest_i]) if retest_i is not None else float("nan")
    tagged_exact_high = bool(retest_i is not None and retest_l <= level <= retest_h)
    tagged_from_above = bool(retest_i is not None and retest_l > level and retest_l <= level + band)
    tagged_from_below = bool(retest_i is not None and retest_h < level and retest_h >= level - band)
    mins_break_to_retest = max(0.0, (retest_ts - br_end).total_seconds() / 60.0)
    mins_retest_to_fill = max(0.0, (entry_ts - retest_ts).total_seconds() / 60.0)

    # Daily / 2h
    daily_atr_arr = (
        wilder_atr(
            daily["high"].to_numpy(dtype=float),
            daily["low"].to_numpy(dtype=float),
            daily["close"].to_numpy(dtype=float),
        )
        if not daily.empty
        else np.array([])
    )
    daily_ts = pd.to_datetime(daily["ts"], utc=True).dt.tz_convert(ET) if not daily.empty else pd.Series(dtype="datetime64[ns, US/Eastern]")
    piv_day = piv_ts.normalize()
    br_day = br_ts.normalize()
    daily_piv_i = None
    daily_br_i = None
    for i, t in enumerate(daily_ts):
        if _ts(t).normalize() == piv_day:
            daily_piv_i = i
        if _ts(t).normalize() == br_day:
            daily_br_i = i
    daily_high_pivot_day = float(daily["high"].iloc[daily_piv_i]) if daily_piv_i is not None else float("nan")
    daily_close_break_day = float(daily["close"].iloc[daily_br_i]) if daily_br_i is not None else float("nan")
    daily_high_break_day = float(daily["high"].iloc[daily_br_i]) if daily_br_i is not None else float("nan")
    atr_i = daily_br_i if daily_br_i is not None else daily_piv_i
    daily_atr = _atr_at(
        daily_atr_arr,
        (atr_i - 1) if atr_i is not None else -1,
        level * 0.015,
    )
    daily_atr_ready = bool(
        atr_i is not None and atr_i - 1 >= 0 and atr_i - 1 < len(daily_atr_arr) and math.isfinite(daily_atr_arr[atr_i - 1])
    )
    daily_high_is_level = (
        math.isfinite(daily_high_pivot_day) and abs(daily_high_pivot_day - level) <= max(0.02, 0.05 * band)
    )
    later_daily_close_above = False
    if daily_piv_i is not None:
        later_daily_close_above = bool(np.any(daily["close"].to_numpy(dtype=float)[daily_piv_i + 1 :] > level))
    daily_swings = []
    if len(daily) >= 5:
        raw_d = fractal_pivots(daily["high"].to_numpy(dtype=float), daily["low"].to_numpy(dtype=float), 2)
        daily_swings = [i for kind, i in raw_d if kind == "H"]
    daily_is_swing = daily_piv_i in daily_swings if daily_piv_i is not None else False
    close_vs_daily_atr = close_excess / daily_atr if daily_atr else float("nan")
    high_vs_daily_atr = high_excess / daily_atr if daily_atr else float("nan")

    h2_atr_arr = (
        wilder_atr(
            h2["high"].to_numpy(dtype=float),
            h2["low"].to_numpy(dtype=float),
            h2["close"].to_numpy(dtype=float),
        )
        if not h2.empty
        else np.array([])
    )
    h2_ts = pd.to_datetime(h2["ts"], utc=True).dt.tz_convert(ET) if not h2.empty else pd.Series(dtype="datetime64[ns, US/Eastern]")
    h2_highs = h2["high"].to_numpy(dtype=float) if not h2.empty else np.array([])
    h2_match_i = None
    if len(h2_highs):
        dlt = np.abs(h2_highs - level)
        j = int(np.nanargmin(dlt))
        if dlt[j] <= max(band, 0.05):
            h2_match_i = j
    h2_is_swing = False
    if not h2.empty:
        raw2 = fractal_pivots(h2["high"].to_numpy(dtype=float), h2["low"].to_numpy(dtype=float), PIVOT_K["2h"])
        h2_sw = {i for kind, i in raw2 if kind == "H"}
        h2_is_swing = h2_match_i in h2_sw if h2_match_i is not None else False
    h2_atr = _atr_at(h2_atr_arr, h2_match_i if h2_match_i is not None else 0, htf_atr)
    close_vs_2h_atr = close_excess / h2_atr if h2_atr else float("nan")

    # Honest classifiers (display only — not used to retune)
    instant_retest = mins_break_to_retest <= 2.0 and not left_band
    micro_close = abs(close_atr) < BAND_ATR
    same_bar_noise = instant_retest and micro_close
    fill_below_level = float(trade["entry_px"]) < level
    picture_br = (
        (not instant_retest)
        and left_band
        and (not fill_below_level)
        and close_atr >= 0.25
        and mins_to_close >= 60.0
    )
    tiny_4h_poke = close_atr < 0.25
    daily_structure_break = bool(
        later_daily_close_above and daily_atr_ready and close_vs_daily_atr >= 0.50
    )

    out.update(
        {
            "pivot_i": piv_i,
            "conf_i": conf_i,
            "break_i": break_i,
            "pivot_ts": _iso_clock(piv_ts),
            "pivot_hhmm": _hhmm(piv_ts),
            "pivot_date": piv_ts.strftime("%Y-%m-%d"),
            "conf_ts": _iso_clock(conf_ts),
            "break_bar_ts": _iso_clock(br_ts),
            "break_bar_hhmm": _hhmm(br_ts),
            "break_end_ts": _iso_clock(br_end),
            "break_end_hhmm": _hhmm(br_end),
            "pivot_high": piv_high,
            "pivot_close": piv_close,
            "pivot_is_fractal_swing": piv_i in swing_idx,
            "break_open": br_open,
            "break_high": br_high,
            "break_low": br_low,
            "break_close": br_close,
            "close_excess_$": close_excess,
            "high_excess_$": high_excess,
            "close_excess_%": close_pct,
            "high_excess_%": high_pct,
            "close_excess_4h_atr": close_atr,
            "high_excess_4h_atr": high_atr,
            "tiny_break": close_atr < MIN_BREAK_ATR_WHATIF,
            "n_4h_pivot_to_break": n_flag,
            "n_4h_highs_in_band": n_zone_highs,
            "flag_range_$": flag_range,
            "flag_range_4h_atr": flag_range_atr,
            "first_1m_wick_above_in_break_bar": _iso_clock(ts1.iloc[first_wick_i]) if first_wick_i is not None else "—",
            "first_1m_close_above_in_break_bar": _iso_clock(ts1.iloc[first_close_i]) if first_close_i is not None else "—",
            "n_1m_wicks_above_in_break_bar": n_1m_above_during,
            "n_1m_closes_above_in_break_bar": n_1m_close_above_during,
            "mins_break_to_retest": mins_break_to_retest,
            "mins_retest_to_fill": mins_retest_to_fill,
            "n_1m_between_break_and_retest": n_between,
            "left_the_band_before_retest": left_band,
            "max_high_between_break_retest": max_high_between,
            "away_atr_before_retest": away_atr,
            "retest_open": retest_o,
            "retest_high": retest_h,
            "retest_low": retest_l,
            "retest_close": retest_c,
            "retest_tagged_exact_high": tagged_exact_high,
            "retest_tag_from_above_only": tagged_from_above,
            "retest_tag_from_below_only": tagged_from_below,
            "daily_high_pivot_day": daily_high_pivot_day,
            "daily_high_is_the_level": daily_high_is_level,
            "daily_high_break_day": daily_high_break_day,
            "daily_close_break_day": daily_close_break_day,
            "daily_atr": daily_atr,
            "daily_atr_warmed": daily_atr_ready,
            "daily_is_fractal_swing": daily_is_swing,
            "later_daily_close_above_level": later_daily_close_above,
            "close_excess_daily_atr": close_vs_daily_atr,
            "high_excess_daily_atr": high_vs_daily_atr,
            "h2_level_exists": h2_match_i is not None,
            "h2_is_fractal_swing": h2_is_swing,
            "h2_atr": h2_atr,
            "close_excess_2h_atr": close_vs_2h_atr,
            "instant_retest": instant_retest,
            "micro_close": micro_close,
            "same_bar_noise": same_bar_noise,
            "fill_below_level": fill_below_level,
            "same_bar_stop": float(trade["hold_min"]) <= 0.0 and str(trade["exit_type"]) == "STOP",
            "picture_br": picture_br,
            "tiny_4h_poke": tiny_4h_poke,
            "daily_structure_break": daily_structure_break,
        }
    )
    return out


def book_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for t in trades:
        et = _ts(t["entry_ts"])
        xt = _ts(t["exit_ts"])
        rows.append(t)
    m = metrics_from_trades(rows)
    pnls = [float(t["pnl_pct"]) for t in trades]
    usds = [float(t["pnl_usd"]) for t in trades]
    holds = [float(t["hold_min"]) for t in trades]
    m["Median_PnL_%"] = float(np.median(pnls)) if pnls else float("nan")
    m["P90_hold_min"] = float(np.quantile(holds, 0.90)) if holds else float("nan")
    cap_days = sum(max(0.01, (_ts(t["exit_ts"]) - _ts(t["entry_ts"])).total_seconds() / 86400.0) for t in trades)
    m["Capital_days"] = cap_days
    m["Profit_per_cap_day"] = (sum(usds) / cap_days) if cap_days else float("nan")
    w_usd = [u for u in usds if u > 0]
    l_usd = [u for u in usds if u <= 0]
    m["WL_$"] = (sum(w_usd) / abs(sum(l_usd))) if l_usd and abs(sum(l_usd)) > 0 else float("nan")
    m["WL_count"] = m.get("WL_count_ratio", float("nan"))
    mix = m.get("exit_mix") or {}
    n = max(1, int(m.get("N") or 0))
    m["STOP_%"] = 100.0 * mix.get("STOP", 0) / n
    m["TIME_%"] = 100.0 * (mix.get("TIME", 0) + mix.get("EOD_FLAT", 0)) / n
    m["HTF_FAIL_%"] = 100.0 * mix.get("HTF_FAIL", 0) / n
    # overlay already inside metrics_from_trades; keep Ann ROR as — for scalps
    return m


def fmt(v: Any, kind: str = "num") -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, str):
        return v
    try:
        x = float(v)
    except (TypeError, ValueError):
        return str(v)
    if not math.isfinite(x):
        return "—"
    if kind == "pct":
        return f"{x:+.3f}%"
    if kind == "pct0":
        return f"{x:.1f}%"
    if kind == "atr":
        return f"{x:+.3f}"
    if kind == "px":
        return f"{x:.2f}"
    if kind == "money":
        sign = "-" if x < 0 else ""
        return f"{sign}${abs(x):,.2f}"
    if kind == "min":
        return f"{x:.0f}"
    return f"{x:.3f}"


def verdict_xom(r: dict[str, Any]) -> tuple[str, str, str]:
    return (
        "Real 4h break; fake 9/16 retest",
        "NO — not a picture break-and-retest on 9/16",
        "The break is yesterday: 4-hour bar 09:30–13:30 ET on 2026-09-15 closed $169.41 vs the $167.37 high "
        "(+$2.04 / +1.22% / +0.78 × 4h ATR). That close-through is real. The 9/16 09:31 bar never traded "
        "$167.37 (high $167.29). Fill $166.84 is below the high and died on the same 1-minute bar. "
        "The generator called it a retest only because 09:31 intersected the lower band.",
    )


def verdict_lly(r: dict[str, Any]) -> tuple[str, str, str]:
    return (
        "Too late? YES",
        "YES — 15:30 would have skipped it; 15:45 freeze still took it",
        "Fill 15:33 ET, 27 minutes to the 16:00 Regular-hours close. Freeze cutoff is 15:45, so this is legal. "
        "It does not hold overnight (TIME flatten 15:55). Damage is a same-bar stop at 15:33, not an overnight gap. "
        "A 'no trade after 15:30' gate skips it. A 'no overnight' gate does not — this already is not overnight.",
    )


def verdict_asml(r: dict[str, Any]) -> tuple[str, str, str]:
    return (
        "Small 4h poke? YES",
        "NO — does not belong on daily as the reason to take it",
        "4-hour close-through is only +$9.39 / +0.55% / +0.16 × 4h ATR (band itself is $8.81). "
        "Retest is the 13:30 minute the 4-hour bar ends — never left the band. The 7/31 high is also the "
        "daily high, and 8/4’s daily close did go through it, but daily ATR is not warmed on this short tape "
        "and the fill is a 4-hour poke-and-sit, not a daily retest.",
    )


def verdict_nvda(r: dict[str, Any]) -> tuple[str, str, str]:
    return (
        "Cleaner same-book B/R",
        "YES — closer to a real leave-then-return",
        "4-hour close on 8/27 was +$6.38 / +2.86% / +1.24 × 4h ATR / +1.01 × daily ATR. "
        "Price left the band, then 8/28 10:11 tagged it and 10:12 filled above the high ($223.73 vs $222.87). "
        "That is the picture XOM/LLY/ASML are missing: a large close-through, time away, then a morning fill still above the line.",
    )


def classify_focus(r: dict[str, Any]) -> None:
    key = r.get("key")
    if key == "xom":
        r["verdict_short"], r["verdict_yn"], r["verdict_why"] = verdict_xom(r)
    elif key == "lly":
        r["verdict_short"], r["verdict_yn"], r["verdict_why"] = verdict_lly(r)
    elif key == "asml":
        r["verdict_short"], r["verdict_yn"], r["verdict_why"] = verdict_asml(r)
    elif key == "nvda":
        r["verdict_short"], r["verdict_yn"], r["verdict_why"] = verdict_nvda(r)
    else:
        r["verdict_short"], r["verdict_yn"], r["verdict_why"] = "—", "—", ""


def render_annotated(r: dict[str, Any], trade: dict[str, Any], cache: dict[str, dict[str, Any]], out_png: Path) -> Optional[str]:
    sym = r["symbol"]
    pack = load_symbol(sym, cache)
    df1 = pack["df1"]
    htf = pack["htf"]
    atr1 = pack.get("atr1")
    if df1.empty or htf.empty:
        return "empty tape"
    level = float(r["level"])
    band = float(r["band"])
    break_ts = _ts(r["break_end_ts"] if r.get("break_end_ts") else trade["break_ts"])
    # slice wants break bar start-ish; use book break_ts (end) like parent
    break_end = _ts(trade["break_ts"])
    retest_ts = _ts(trade["retest_ts"])
    entry_ts = _ts(trade["entry_ts"])
    exit_ts = _ts(trade["exit_ts"])
    left = slice_4h(htf, break_end, exit_ts)
    right = slice_1m(df1, break_ts=break_end, retest_ts=retest_ts, exit_ts=exit_ts)
    if left.empty or right.empty:
        return "not enough bars"
    full_ts = pd.to_datetime(df1["ts"], utc=True).dt.tz_convert(ET)
    r_ts = pd.to_datetime(right["ts"], utc=True).dt.tz_convert(ET)
    l_ts = pd.to_datetime(left["ts"], utc=True).dt.tz_convert(ET)
    htf_ts = pd.to_datetime(htf["ts"], utc=True).dt.tz_convert(ET)
    entry_i_full = _nearest_idx(full_ts, entry_ts, slop_min=2.0)
    exit_i_full = _nearest_idx(full_ts, exit_ts, slop_min=2.0)
    if entry_i_full is None or exit_i_full is None or atr1 is None:
        trail = np.array([])
    else:
        atr_e = float(atr1[entry_i_full]) if np.isfinite(atr1[entry_i_full]) else float(r["entry_px"]) * 0.001
        trail = chandelier_stops(
            df1["high"].to_numpy(dtype=float),
            atr1,
            entry_i_full,
            exit_i_full,
            float(r["stop0"]),
            atr_e,
        )
    touches = nearby_4h_touches(htf, level, band, break_end)
    left_i0 = _nearest_idx(htf_ts, _ts(l_ts.iloc[0]), slop_min=250.0) or 0

    fig, axes = plt.subplots(1, 2, figsize=(16.8, 8.05), facecolor="#f8fafc")
    fig.subplots_adjust(left=0.05, right=0.985, top=0.72, bottom=0.16, wspace=0.16)

    ax = axes[0]
    ax.set_facecolor("#ffffff")
    _draw_candles(
        ax,
        left["open"].to_numpy(dtype=float),
        left["high"].to_numpy(dtype=float),
        left["low"].to_numpy(dtype=float),
        left["close"].to_numpy(dtype=float),
        width=0.68,
    )
    nL = len(left)
    ax.axhspan(level - band, level + band, color="#f59e0b", alpha=0.16, zorder=1)
    ax.axhline(level, color="#b45309", lw=1.4, zorder=4)
    ax.axhline(level - band, color="#f59e0b", lw=0.7, ls="--", alpha=0.8)
    ax.axhline(level + band, color="#f59e0b", lw=0.7, ls="--", alpha=0.8)
    piv_i_pane = None
    if r.get("pivot_ts"):
        piv_i_pane = _nearest_idx(l_ts, _ts(r["pivot_ts"]), slop_min=250.0)
    if piv_i_pane is not None:
        ax.scatter([piv_i_pane], [level], marker="D", s=70, color="#7c3aed", zorder=7, edgecolors="white")
        ax.annotate(
            f"THE HIGH  {level:.2f}\n{r.get('pivot_ts', '')}",
            xy=(piv_i_pane, level),
            xytext=(10, 18),
            textcoords="offset points",
            fontsize=8,
            color="#5b21b6",
            fontweight="semibold",
            arrowprops=dict(arrowstyle="->", color="#7c3aed", lw=0.9),
            zorder=8,
        )
    br_i = _nearest_idx(l_ts, break_end, slop_min=250.0)
    if br_i is not None:
        ax.axvline(br_i, color="#7c3aed", lw=1.0, ls=":", alpha=0.85)
        ax.annotate(
            f"4h CLOSE-THROUGH\nclose {r.get('break_close', float('nan')):.2f}  "
            f"({r.get('close_excess_4h_atr', float('nan')):+.2f} ATR)",
            xy=(br_i, float(left["high"].iloc[br_i])),
            xytext=(8, 12),
            textcoords="offset points",
            fontsize=7.6,
            color="#5b21b6",
            arrowprops=dict(arrowstyle="->", color="#7c3aed", lw=0.8),
        )
    ax.set_xlim(-0.8, nL - 0.2)
    y_lo = min(float(left["low"].min()), level - band)
    y_hi = max(float(left["high"].max()), level + band)
    pad = max((y_hi - y_lo) * 0.12, 0.08)
    ax.set_ylim(y_lo - pad, y_hi + pad)
    _set_xticks(ax, list(l_ts), max_ticks=8, mode="4h")
    ax.set_ylabel("Price ($)", fontsize=9)
    ax.set_title(f"4-hour  ·  high {level:.2f}  ·  band ±{band:.3f}", fontsize=10, loc="left")
    ax.grid(True, axis="y", color="#e2e8f0", lw=0.6)

    ax = axes[1]
    ax.set_facecolor("#ffffff")
    _draw_candles(
        ax,
        right["open"].to_numpy(dtype=float),
        right["high"].to_numpy(dtype=float),
        right["low"].to_numpy(dtype=float),
        right["close"].to_numpy(dtype=float),
        width=0.72,
    )
    nR = len(right)
    ax.axhspan(level - band, level + band, color="#f59e0b", alpha=0.12, zorder=1)
    ax.axhline(level, color="#b45309", lw=1.15, zorder=4)

    def mark(ts_val: pd.Timestamp, label: str, color: str, y: float, marker: str = "v") -> None:
        i = _nearest_idx(r_ts, ts_val)
        if i is None:
            return
        ax.scatter([i], [y], marker=marker, s=50, color=color, zorder=7, edgecolors="white", linewidths=0.35)
        ax.annotate(label, xy=(i, y), xytext=(4, 9), textcoords="offset points", fontsize=7.4, color=color, zorder=8)

    rt_i = _nearest_idx(r_ts, retest_ts)
    en_i = _nearest_idx(r_ts, entry_ts)
    ex_i = _nearest_idx(r_ts, exit_ts)
    if rt_i is not None:
        ax.axvline(rt_i, color="#0284c7", lw=0.85, ls="--", alpha=0.8)
        mark(retest_ts, f"retest {_hhmm(retest_ts)}", "#0284c7", float(right["low"].iloc[rt_i]), "v")
    if en_i is not None:
        mark(entry_ts, f"FILL {_hhmm(entry_ts)}  {float(r['entry_px']):.2f}", "#15803d", float(r["entry_px"]), ">")
        ax.axhline(float(r["entry_px"]), color="#15803d", lw=0.7, ls=":", alpha=0.7)
        ax.axhline(float(r["stop0"]), color="#64748b", lw=0.95, ls="--")
        if len(trail):
            trail_x, trail_y = [], []
            for k, px in enumerate(trail):
                pane_i = en_i + k
                if 0 <= pane_i < nR:
                    trail_x.append(pane_i)
                    trail_y.append(float(px))
            if trail_x:
                ax.step(trail_x, trail_y, where="post", color="#dc2626", lw=1.6, zorder=8)
    if ex_i is not None:
        mark(exit_ts, f"exit {r['exit_type']} {_hhmm(exit_ts)}", "#0f172a", float(r["exit_px"]), "X")

    ax.set_xlim(-0.8, nR - 0.2)
    ys = [float(right["low"].min()), float(right["high"].max()), level - band, level + band, float(r["entry_px"]), float(r["stop0"])]
    y0, y1 = min(ys), max(ys)
    pad = max((y1 - y0) * 0.10, 0.04)
    ax.set_ylim(y0 - pad, y1 + pad)
    _set_xticks(ax, list(r_ts), max_ticks=9, mode="1m")
    ax.set_ylabel("Price ($)", fontsize=9)
    ax.set_title(
        f"1-minute  ·  {r.get('mins_to_1600', float('nan')):.0f} min to 16:00  ·  "
        f"retest {r.get('mins_break_to_retest', float('nan')):.0f} min after 4h close",
        fontsize=10,
        loc="left",
    )
    ax.grid(True, axis="y", color="#e2e8f0", lw=0.6)

    pnl = float(r["pnl_pct"])
    sign = "+" if pnl >= 0 else ""
    fig.suptitle(
        f"{sym}  {r['entry_date']}  ·  {r.get('verdict_short', '')}  ·  {sign}{pnl:.3f}% {r['exit_type']}",
        fontsize=13.2,
        fontweight="semibold",
        y=0.985,
    )
    def _plain(s: str) -> str:
        return str(s).replace("$", "")

    fig.text(
        0.05,
        0.905,
        _plain(
            f"HIGH {level:.2f} at {r.get('pivot_ts', '—')} (4h bar open).  "
            f"BREAK = 4h close {r.get('break_close', float('nan')):.2f} at {r.get('break_end_ts', '—')}  "
            f"({r.get('close_excess_$', float('nan')):+.3f} / {r.get('close_excess_%', float('nan')):+.3f}% / "
            f"{r.get('close_excess_4h_atr', float('nan')):+.3f}x 4h ATR)."
        ),
        fontsize=8.1,
        color="#334155",
        ha="left",
    )
    fig.text(
        0.05,
        0.868,
        _plain(
            f"ZONE {r.get('zone_lo', float('nan')):.2f}-{r.get('zone_hi', float('nan')):.2f}  "
            f"(+/-0.15x4h ATR={band:.3f}).  "
            f"RETEST {_iso_clock(retest_ts)}  low {r.get('retest_low', float('nan')):.2f}  "
            f"{'traded the high' if r.get('retest_tagged_exact_high') else 'did NOT trade the exact high'}.  "
            f"FILL {_iso_clock(entry_ts)} -> {_iso_clock(exit_ts)}."
        ),
        fontsize=8.0,
        color="#475569",
        ha="left",
    )
    fig.text(
        0.05,
        0.832,
        _plain(f"{r.get('verdict_yn', '')}  --  {r.get('verdict_why', '')}"),
        fontsize=8.0,
        color="#0f172a",
        ha="left",
    )
    handles = [
        Line2D([0], [0], color="#b45309", lw=1.4, label="HTF high"),
        Line2D([0], [0], color="#f59e0b", lw=6, alpha=0.35, label="Band ±0.15×ATR"),
        Line2D([0], [0], marker="D", color="#7c3aed", lw=0, label="4h swing high"),
        Line2D([0], [0], marker=">", color="#15803d", lw=0, label="Fill"),
        Line2D([0], [0], marker="X", color="#0f172a", lw=0, label="Exit"),
        Line2D([0], [0], color="#dc2626", lw=1.4, label="Chandelier 3×ATR"),
    ]
    fig.legend(handles=handles, loc="lower center", ncol=6, frameon=False, fontsize=8, bbox_to_anchor=(0.5, 0.012))
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=128, facecolor=fig.get_facecolor())
    plt.close(fig)
    return None


def write_baseline(focus_rows: list[dict[str, Any]], whatif: dict[str, Any], n_book: int) -> None:
    lines = []
    for r in focus_rows:
        lines.append(
            f"- **{r['symbol']} {r['entry_date']}** ({r.get('role')}): {r.get('verdict_yn')} — {r.get('verdict_why')}"
        )
    text = f"""# BASELINE — Three-trade tape read — `{STAMP}`

**System:** pattern / picture read on parent `{PARENT_STAMP}` `4h × 1m × trail_chandelier_3`. **Not** DailyRun. **Not** gold. Research only.

## What you asked

> i don't understand how this is a break and retest
> XOM · 2026-09-16 · -0.098% · STOP
> LLY · 2026-07-29 · -0.195% · STOP should not be a trade because it is so close to the close
> how big is this break? and should it be on the longer timeframe
> ASML · 2026-08-04 · +0.096% · STOP

## In plain English

{PLAIN_ENGLISH}

## Parent freeze pointer

Do not retune. Identity is the parent 37-trade book.

| Parent knob | Value |
|-------------|--------|
| Stamp | `{PARENT_STAMP}` |
| HTF / LTF / arm | 4h / 1m / `trail_chandelier_3` |
| Break | 4-hour **close** above the most recent confirmed 4-hour fractal swing high (k=2) |
| Zone / retest band | level ± **0.15 × HTF ATR** (1-minute bar range intersects the band) |
| Retest window | 3 × 4h bars after the break bar; cancel if a later 4h closes back below |
| Entry | next 1-minute open after the first retest bar; **no entry at/after 15:45 ET** |
| Overnight | **No.** TIME flatten at **15:55 ET** open (or STOP / HTF_FAIL / last-bar EOD_FLAT) |
| Stop | control initial (level − 0.50 × 1m ATR), then chandelier = prior-bar running high − 3 × 1m ATR |
| Session | Regular trading hours 09:30–16:00 ET |
| Tape | `data/intraday/1m/{{SYM}}.parquet` |
| N book | {n_book} (must stay 37) |

There is **no** “no entry after 15:30” gate in the freeze. The only clock gate is 15:45.

## How we reconstructed (not from PNG titles)

For each name: rematch `find_htf_breaks` on the 09:30-anchored 4-hour bars, then read the 1-minute Regular-hours tape around that break. Level, `break_ts`, `retest_ts`, `entry_ts` must agree with `trades.csv`.

## Verdicts (measured)

{chr(10).join(lines)}

## One-knob what-if (HOLD only — not adopted)

Two separate notes, not a combined shop. Selection labeled:

1. **No entry at/after 15:30 ET** — Paul’s clock, pre-stated. Freeze already blocks 15:45. N kept = {whatif['late']['n_keep']} / {n_book}. Avg PnL% {whatif['late']['avg_pnl']}.
2. **Min 4-hour close-through ≥ 0.25 × 4h ATR** — chosen after measuring ASML 8/4 at **+0.160 × 4h ATR** (the freeze-band 0.15 would have kept ASML). That cutoff is **in-sample selection**. N kept = {whatif['tiny']['n_keep']} / {n_book}. Avg PnL% {whatif['tiny']['avg_pnl']}.

Do not retune the chandelier. Do not wire DailyRun. If OOS (entry ≥ 2026-09-02) looks different, HOLD — XOM is OOS.

## Selection bias

The three names were chart-picked after the gallery. The 0.25 × 4h ATR min-break floor was written after seeing ASML at +0.160 × 4h ATR. That same floor would also drop LLY 2026-08-07 (+2.076%, a liked winner, close-through +0.248 × 4h ATR). Contrast NVDA 2026-08-28 was already liked in the parent EOD/AM read. Research candidate only.

## Split

Parent short-tape split (report-only): IS = `entry_date < 2026-09-02`; OOS = `entry_date >= 2026-09-02`. XOM 2026-09-16 is OOS.

## Promotion

Research candidate. **Not** gold. **Not** DailyRun. Do not change the parent freeze from this stamp.
"""
    (OUT / "BASELINE.md").write_text(text, encoding="utf-8")


def _engine_why(r: dict[str, Any]) -> str:
    return (
        f"The generator marked a break because the 4-hour bar that ended {r.get('break_end_ts', '—')} "
        f"**closed** at {fmt(r.get('break_close'), 'px')} vs the confirmed swing high "
        f"{fmt(r.get('level'), 'px')} (high printed on the 4-hour bar opening {r.get('pivot_ts', '—')}). "
        f"It marked a retest because the 1-minute bar at {r.get('retest_ts', '—')} had range "
        f"{fmt(r.get('retest_low'), 'px')}–{fmt(r.get('retest_high'), 'px')}, which intersects the band "
        f"{fmt(r.get('zone_lo'), 'px')}–{fmt(r.get('zone_hi'), 'px')} (level ± 0.15 × 4h ATR "
        f"{fmt(r.get('htf_atr'), 'px')}). Fill is the next 1-minute open. "
        f"No leave-the-zone rule. No min break size. No 15:30 gate."
    )


def write_html(
    focus_rows: list[dict[str, Any]],
    book_rows: list[dict[str, Any]],
    whatif: dict[str, Any],
    m_all: dict[str, Any],
    m_late: dict[str, Any],
    m_tiny: dict[str, Any],
    n_book: int,
) -> None:
    def ths(cols: list[tuple[str, str]]) -> str:
        return "".join(sortable_th(a, b) for a, b in cols)

    trade_cols = [
        ("Role", "text"),
        ("Symbol", "text"),
        ("Entry date", "date"),
        ("PnL %", "num"),
        ("Exit", "text"),
        ("Picture B/R?", "text"),
        ("Verdict", "text"),
        ("Fill below high?", "text"),
        ("Same-bar stop?", "text"),
        ("The high $", "num"),
        ("High 4h bar", "text"),
        ("4h close-through $", "num"),
        ("Close-through %", "num"),
        ("Close / 4h ATR", "num"),
        ("High-take / 4h ATR", "num"),
        ("Close / daily ATR", "num"),
        ("Zone lo", "num"),
        ("Zone hi", "num"),
        ("Break end", "text"),
        ("Retest", "text"),
        ("Fill ET", "text"),
        ("Min to 16:00", "num"),
        ("Min break→retest", "num"),
        ("Left the band?", "text"),
        ("Retest traded the high?", "text"),
        ("4h bars pivot→break", "num"),
        ("4h highs in band", "num"),
        ("Daily high = level?", "text"),
        ("Daily structure break?", "text"),
        ("Would 15:30 skip?", "text"),
        ("Split", "text"),
        ("Parent chart", "text"),
        ("Annotated", "text"),
    ]

    def trade_row(r: dict[str, Any]) -> str:
        cls = "contrast" if r.get("role") == "contrast" else "focus"
        if r.get("pnl_pct", 0) > 0:
            cls += " win"
        else:
            cls += " loss"
        parent = r.get("parent_png") or ""
        ann = r.get("ann_rel") or ""
        parent_cell = f'<a href="{html_mod.escape(parent)}">parent png</a>' if parent else "—"
        ann_cell = f'<a href="{html_mod.escape(ann)}">annotated</a>' if ann else "—"
        yn = r.get("verdict_yn") or ""
        cells = [
            html_mod.escape(str(r.get("role", ""))),
            html_mod.escape(r["symbol"]),
            r["entry_date"],
            f"{float(r['pnl_pct']):+.3f}%",
            html_mod.escape(str(r.get("exit_type", ""))),
            "YES" if r.get("picture_br") else "NO",
            html_mod.escape(yn),
            "YES" if r.get("fill_below_level") else "no",
            "YES" if r.get("same_bar_stop") else "no",
            fmt(r.get("level"), "px"),
            html_mod.escape(str(r.get("pivot_ts", "—"))),
            fmt(r.get("close_excess_$"), "num"),
            fmt(r.get("close_excess_%"), "pct"),
            fmt(r.get("close_excess_4h_atr"), "atr"),
            fmt(r.get("high_excess_4h_atr"), "atr"),
            fmt(r.get("close_excess_daily_atr"), "atr"),
            fmt(r.get("zone_lo"), "px"),
            fmt(r.get("zone_hi"), "px"),
            html_mod.escape(str(r.get("break_end_ts", "—"))),
            html_mod.escape(str(r.get("retest_ts", "—"))),
            html_mod.escape(str(r.get("entry_ts", "—"))),
            fmt(r.get("mins_to_1600"), "min"),
            fmt(r.get("mins_break_to_retest"), "min"),
            "yes" if r.get("left_the_band_before_retest") else "no",
            "yes" if r.get("retest_tagged_exact_high") else "no",
            fmt(r.get("n_4h_pivot_to_break"), "min"),
            fmt(r.get("n_4h_highs_in_band"), "min"),
            "yes" if r.get("daily_high_is_the_level") else "no",
            "yes" if r.get("daily_structure_break") else "no",
            "YES" if r.get("late_1530") else "no",
            html_mod.escape(str(r.get("split", ""))),
            parent_cell,
            ann_cell,
        ]
        return f'<tr class="{cls}">' + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"

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

    def book_row(name: str, m: dict[str, Any], extra: str = "") -> str:
        cls = f' class="{extra}"' if extra else ""
        cells = [
            html_mod.escape(name),
            str(m.get("N", 0)),
            str(m.get("Wins", 0)),
            str(m.get("Losses", 0)),
            fmt(m.get("Win%"), "pct0"),
            fmt(m.get("Avg_PnL_%"), "pct"),
            fmt(m.get("Median_PnL_%"), "pct"),
            fmt(m.get("AVG_PNL_PCT_WO_MAX"), "pct"),
            fmt(m.get("Avg_Win_%"), "pct"),
            fmt(m.get("Avg_Loss_%"), "pct"),
            fmt(m.get("Expectancy_%"), "pct"),
            fmt(m.get("Expectancy_$"), "money"),
            fmt(m.get("Profit_Factor"), "num"),
            fmt(m.get("WL_count"), "num"),
            fmt(m.get("WL_$"), "num"),
            fmt(m.get("Avg_min_held"), "num"),
            fmt(m.get("Med_min_held"), "num"),
            fmt(m.get("P90_hold_min"), "num"),
            fmt(m.get("Capital_days"), "num"),
            fmt(m.get("Profit_per_cap_day"), "money"),
            fmt(m.get("Ann_ROR_%"), "pct"),
            fmt(m.get("Max_DD_%"), "pct"),
            fmt(m.get("Calmar"), "num"),
            fmt(m.get("Sharpe"), "num"),
            fmt(m.get("STOP_%"), "pct0"),
            fmt(m.get("TIME_%"), "pct0"),
            fmt(m.get("HTF_FAIL_%"), "pct0"),
        ]
        return f"<tr{cls}>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"

    cards = []
    for r in focus_rows:
        pnl = float(r["pnl_pct"])
        sign = "+" if pnl >= 0 else ""
        cards.append(
            f'<div class="card {r.get("role", "")}">'
            f'<h3>{html_mod.escape(r["symbol"])} · {html_mod.escape(r["entry_date"])} · '
            f"{sign}{pnl:.3f}% · {html_mod.escape(str(r.get('exit_type', '')))}</h3>"
            f'<div class="metric">{html_mod.escape(str(r.get("verdict_yn", "")))}</div>'
            f'<p class="small">{html_mod.escape(str(r.get("verdict_why", "")))}</p>'
            f'<p class="small">Fill {html_mod.escape(str(r.get("entry_ts", "")))} · '
            f"{fmt(r.get('mins_to_1600'), 'min')} min to 16:00 · "
            f"close-through {fmt(r.get('close_excess_$'), 'num')} "
            f"({fmt(r.get('close_excess_4h_atr'), 'atr')} × 4h ATR)</p></div>"
        )

    detail_blocks = []
    for r in focus_rows:
        img = ""
        if r.get("ann_rel"):
            img = (
                f'<img src="{html_mod.escape(r["ann_rel"])}" alt="{html_mod.escape(r["symbol"])} annotated" '
                f'loading="lazy"/>'
            )
        parent_link = ""
        if r.get("parent_png"):
            parent_link = (
                f'<p class="small"><a href="{html_mod.escape(r["parent_png"])}">parent gallery PNG</a> · '
                f'<a href="../{PARENT_STAMP}/charts_4h_1m_chandelier3.html">parent 37-chart gallery</a></p>'
            )
        detail_blocks.append(
            f'<article class="detail" id="{html_mod.escape(str(r.get("key", r["symbol"])))}">'
            f'<h2>{html_mod.escape(r["symbol"])} · {html_mod.escape(r["entry_date"])}</h2>'
            f'<p><strong>{html_mod.escape(str(r.get("verdict_yn", "")))}</strong> — '
            f'{html_mod.escape(str(r.get("verdict_why", "")))}</p>'
            f"<ul>"
            f"<li><strong>The high:</strong> {fmt(r.get('level'), 'px')} on the 4-hour bar that opens "
            f"{html_mod.escape(str(r.get('pivot_ts', '—')))} "
            f"(confirmed after +2 bars at {html_mod.escape(str(r.get('conf_ts', '—')))}). "
            f"Fractal swing high: {'yes' if r.get('pivot_is_fractal_swing') else 'no'}.</li>"
            f"<li><strong>How the break printed:</strong> 4-hour close {fmt(r.get('break_close'), 'px')} "
            f"when that bar ended {html_mod.escape(str(r.get('break_end_ts', '—')))}. "
            f"Close excess {fmt(r.get('close_excess_$'), 'num')} ({fmt(r.get('close_excess_%'), 'pct')}, "
            f"{fmt(r.get('close_excess_4h_atr'), 'atr')} × 4h ATR). "
            f"Bar high excess {fmt(r.get('high_excess_$'), 'num')} "
            f"({fmt(r.get('high_excess_4h_atr'), 'atr')} × 4h ATR). "
            f"First 1-minute wick above the high during that 4-hour bar: "
            f"{html_mod.escape(str(r.get('first_1m_wick_above_in_break_bar', '—')))}; "
            f"first 1-minute close above: "
            f"{html_mod.escape(str(r.get('first_1m_close_above_in_break_bar', '—')))} "
            f"({r.get('n_1m_wicks_above_in_break_bar', 0)} wick(s), "
            f"{r.get('n_1m_closes_above_in_break_bar', 0)} close(s)).</li>"
            f"<li><strong>Retest vs fill:</strong> retest {html_mod.escape(str(r.get('retest_ts', '—')))} "
            f"(OHLC {fmt(r.get('retest_open'), 'px')} / {fmt(r.get('retest_high'), 'px')} / "
            f"{fmt(r.get('retest_low'), 'px')} / {fmt(r.get('retest_close'), 'px')}), "
            f"{fmt(r.get('mins_break_to_retest'), 'min')} min after the 4-hour close. "
            f"Fill {html_mod.escape(str(r.get('entry_ts', '—')))} "
            f"({fmt(r.get('mins_retest_to_fill'), 'min')} min later). "
            f"Left the band first? {'yes' if r.get('left_the_band_before_retest') else 'no'}.</li>"
            f"<li><strong>Zone band:</strong> {fmt(r.get('zone_lo'), 'px')} to {fmt(r.get('zone_hi'), 'px')} "
            f"(level ± 0.15 × {fmt(r.get('htf_atr'), 'px')} 4h ATR).</li>"
            f"<li><strong>Why the generator called it a retest:</strong> {_engine_why(r)}</li>"
            f"<li><strong>Clocks / size extras:</strong> {fmt(r.get('mins_to_1600'), 'min')} min to 16:00 ET. "
            f"Freeze entry cutoff is 15:45 (this fill {'would be blocked' if r.get('late_1545_blocked_by_freeze') else 'is allowed'}). "
            f"15:30 gate would {'SKIP' if r.get('late_1530') else 'keep'} it. "
            f"Does not hold overnight (15:55 TIME flatten). "
            f"Flag: {fmt(r.get('n_4h_pivot_to_break'), 'min')} 4-hour bars from high to break, "
            f"{fmt(r.get('n_4h_highs_in_band'), 'min')} highs in the band, "
            f"range {fmt(r.get('flag_range_$'), 'px')} ({fmt(r.get('flag_range_4h_atr'), 'atr')} × 4h ATR). "
            f"Daily high that day equals the level? {'yes' if r.get('daily_high_is_the_level') else 'no'}. "
            f"Later daily close above the level? {'yes' if r.get('later_daily_close_above_level') else 'no'}. "
            f"2h swing at this high? {'yes' if r.get('h2_is_fractal_swing') else 'no'}.</li>"
            f"</ul>"
            f"{img}{parent_link}</article>"
        )

    late_skipped = ", ".join(whatif.get("late_skipped_names") or []) or "none"
    tiny_skipped = ", ".join(whatif.get("tiny_skipped_names") or []) or "none"

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Three-trade B/R tape read — {html_mod.escape(STAMP)}</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 24px; color: #0f172a; background: #f8fafc; }}
h1 {{ font-size: 1.45rem; margin: 0 0 4px; }}
h2 {{ font-size: 1.12rem; margin: 1.5rem 0 .45rem; border-bottom: 1px solid #cbd5e1; padding-bottom: .2rem; }}
h3 {{ margin: 0 0 8px; font-size: 14px; color: #334155; }}
.sub, .meta, .small {{ color: #475569; font-size: .92rem; line-height: 1.5; }}
.callout {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: .85rem 1rem; margin: .75rem 0; max-width: 86rem; }}
.idea {{ background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; padding: .85rem 1rem; margin: .6rem 0; max-width: 86rem; }}
.verdict {{ background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; padding: .85rem 1rem; margin: .6rem 0; max-width: 86rem; }}
.tag {{ display: inline-block; background: #92400e; color: #fff; font-size: 11px; padding: 1px 6px; border-radius: 999px; margin-right: 6px; }}
.cards {{ display: flex; flex-wrap: wrap; gap: 12px; margin: 16px 0 8px; }}
.card {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px 16px; min-width: 240px; flex: 1 1 240px; }}
.card.contrast {{ background: #ecfdf5; border-color: #86efac; }}
.metric {{ font-size: 1.05rem; font-weight: 700; line-height: 1.35; margin-bottom: 6px; }}
.table-wrap {{ overflow-x: auto; margin: 8px 0; }}
table.sortable {{ border-collapse: collapse; background: #fff; font-size: 12px; width: 100%; }}
table.sortable th, table.sortable td {{ border: 1px solid #e2e8f0; padding: 6px 8px; text-align: left; vertical-align: top; }}
table.sortable th {{ background: #f1f5f9; }}
tr.focus.win td {{ background: #f0fdf4; }}
tr.focus.loss td {{ background: #fff1f2; }}
tr.contrast td {{ background: #ecfdf5; }}
tr.total-row td {{ background: #e0f2fe; font-weight: 600; }}
blockquote {{ margin: .4rem 0; padding-left: .8rem; border-left: 3px solid #cbd5e1; color: #334155; white-space: pre-wrap; }}
.detail {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px 16px; margin: 18px 0; max-width: 86rem; }}
.detail img {{ width: 100%; max-width: 1180px; height: auto; border: 1px solid #e2e8f0; border-radius: 6px; margin-top: 8px; }}
ul li {{ margin: .35rem 0; }}
{SORT_CSS}
</style></head><body>
<p class="small"><span class="tag">Research only</span> Not gold · not DailyRun · parent <code>{html_mod.escape(PARENT_STAMP)}</code> · stamp <code>{html_mod.escape(STAMP)}</code></p>
<h1>Are these three really break-and-retest?</h1>
<p class="sub">Tape read of three Paul-flagged trades from the frozen 37-trade 4-hour × 1-minute chandelier-3 book, plus NVDA 2026-08-28 as a cleaner contrast. Click column headers to sort.</p>

<div class="callout">
<h2 style="margin-top:0">What you asked</h2>
<blockquote>{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN_ENGLISH)}</p>
</div>

<div class="verdict">
<p><span class="tag">HOLD</span>
<strong>Do not retune the chandelier freeze from these three pictures.</strong>
XOM’s 4-hour close-through on 9/15 is real; the 9/16 “retest” is a next-open dip below the high that dies on the fill bar. LLY fills at 15:33 (27 minutes to 16:00) — the freeze allows it (15:45), a 15:30 gate would skip it, and it is not an overnight hold. ASML’s close-through is only +0.16 × 4-hour ATR and the retest is the same minute the 4-hour bar ends. A 15:30 clock or a 0.25 ATR min-break floor is a counted what-if only.</p>
</div>

<div class="cards">
{''.join(cards)}
</div>

<h2>The three (+ contrast) — reconstructed clocks and sizes</h2>
<p class="small">Click column headers to sort. High Time Frame (HTF) = 4-hour. Average True Range (ATR) = Wilder 14. Regular trading hours (RTH) = 09:30–16:00 ET. Break and retest (B/R) = 4-hour close through a confirmed swing high, then a 1-minute tag of that line.</p>
<div class="table-wrap">
<table class="sortable">
<thead><tr>{ths(trade_cols)}</tr></thead>
<tbody>
{''.join(trade_row(r) for r in focus_rows)}
</tbody>
</table>
</div>

{''.join(detail_blocks)}

<h2>One-knob what-if on the 37 (HOLD notes — not adopted)</h2>
<div class="idea">
<p>Two separate knobs. Not a shop of five thresholds. The 15:30 clock is Paul’s ask. The 0.25 × 4-hour ATR min close-through was picked after seeing ASML at +0.160 × 4h ATR (0.15 would have kept it) — <strong>in-sample selection</strong>. That same 0.25 floor also drops LLY 2026-08-07 (+2.076%, a liked winner, close-through +0.248 × 4h ATR). HOLD — do not adopt.</p>
<ul>
<li><strong>No entry at/after 15:30 ET</strong> — skips {whatif['late']['n_skip']} of {n_book} (including {html_mod.escape(late_skipped)}). Kept N={whatif['late']['n_keep']}.</li>
<li><strong>Min 4-hour close-through ≥ 0.25 × 4h ATR</strong> — skips {whatif['tiny']['n_skip']} of {n_book} (including {html_mod.escape(tiny_skipped)}). Kept N={whatif['tiny']['n_keep']}.</li>
</ul>
<p class="small">Ann ROR is omitted when average hold is under 0.5 day (these are scalps). Max DD / Sharpe use the closed-overlay seed ($45,000 sheet / $500,000 account) from the parent helper.</p>
</div>
<div class="table-wrap">
<table class="sortable">
<thead><tr>{ths(book_cols)}</tr></thead>
<tbody>
{book_row("All 37 (control freeze)", m_all, "total-row")}
{book_row("What-if: skip entry ≥ 15:30", m_late)}
{book_row("What-if: skip close-through < 0.25×4h ATR", m_tiny)}
</tbody>
</table>
</div>

<h2>Freeze reminder</h2>
<ul class="meta">
<li>Break = 4-hour <strong>close</strong> above the last confirmed 4-hour fractal swing high (k=2). A 1-minute wick through the high is not enough until that 4-hour bar closes above.</li>
<li>Retest = first 1-minute bar after that 4-hour bar ends whose range intersects level ± 0.15 × 4-hour ATR. Next 1-minute open is the fill.</li>
<li>No min break size. No “must leave the band then return.” No entry at/after 15:45. TIME flatten at 15:55. No overnight.</li>
<li>Research only. Not gold. Not DailyRun.</li>
</ul>

<p class="small">Parent gallery: <a href="../{PARENT_STAMP}/charts_4h_1m_chandelier3.html">charts_4h_1m_chandelier3.html</a> · parent freeze: <a href="../{PARENT_STAMP}/BASELINE.md">BASELINE.md</a></p>
{SORT_JS}
</body></html>
"""
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "compare.html").write_text(html, encoding="utf-8")


def match_focus(book: list[dict[str, Any]], spec: dict[str, Any]) -> tuple[Optional[dict[str, Any]], int]:
    hits = []
    for i, t in enumerate(book, start=1):
        if str(t["symbol"]).upper() != spec["symbol"]:
            continue
        if str(t["entry_date"]) != spec["entry_date"]:
            continue
        hits.append((i, t, abs(float(t["pnl_pct"]) - float(spec["hint_pnl"]))))
    if not hits:
        return None, -1
    hits.sort(key=lambda x: x[2])
    i, t, _ = hits[0]
    return t, i


def main() -> int:
    book = load_arm_trades()
    print(f"4h×1m {ARM}: N={len(book)}")
    if len(book) != 37:
        print(f"WARN expected 37, got {len(book)}")
    OUT.mkdir(parents=True, exist_ok=True)
    cache: dict[str, dict[str, Any]] = {}

    # Light reconstruct all 37 for what-if
    light: list[dict[str, Any]] = []
    for i, t in enumerate(book, start=1):
        row = reconstruct(t, cache, book_index=i)
        row["_trade"] = t
        light.append(row)
        print(
            f"  {i:02d} {row['symbol']} {row['entry_date']} {row.get('entry_hhmm')} "
            f"closeATR={row.get('close_excess_4h_atr', float('nan')):+.3f} "
            f"late={row.get('late_1530')} tiny={row.get('tiny_break')} "
            f"pnl={row.get('pnl_pct', float('nan')):+.3f}"
        )

    focus_rows: list[dict[str, Any]] = []
    for spec in FOCUS:
        t, idx = match_focus(book, spec)
        if t is None:
            print(f"MISSING {spec['symbol']} {spec['entry_date']}")
            continue
        rec = None
        for row in light:
            if row.get("book_index") == idx:
                rec = row
                break
        if rec is None:
            rec = reconstruct(t, cache, book_index=idx, focus=spec)
        rec["role"] = spec["role"]
        rec["key"] = spec["key"]
        classify_focus(rec)
        stem = f"{spec['key']}_{spec['symbol']}_{spec['entry_date']}_annotated.png"
        png = OUT / "charts" / stem
        reason = render_annotated(rec, t, cache, png)
        rec["ann_rel"] = f"charts/{stem}" if reason is None else ""
        if reason:
            print(f"  chart skip {spec['key']}: {reason}")
        else:
            print(f"  chart ok   {spec['key']}: {png.name}")
        focus_rows.append(rec)

    late_keep = [r["_trade"] for r in light if not r.get("late_1530")]
    tiny_keep = [r["_trade"] for r in light if not r.get("tiny_break")]
    late_skip = [r for r in light if r.get("late_1530")]
    tiny_skip = [r for r in light if r.get("tiny_break")]

    def names(rows: list[dict[str, Any]]) -> list[str]:
        out = []
        for r in rows:
            out.append(f"{r['symbol']} {r['entry_date']} {r.get('entry_hhmm')}")
        return out

    m_all = book_metrics(book)
    m_late = book_metrics(late_keep)
    m_tiny = book_metrics(tiny_keep)
    whatif = {
        "late": {
            "n_keep": len(late_keep),
            "n_skip": len(late_skip),
            "avg_pnl": fmt(m_late.get("Avg_PnL_%"), "pct"),
        },
        "tiny": {
            "n_keep": len(tiny_keep),
            "n_skip": len(tiny_skip),
            "avg_pnl": fmt(m_tiny.get("Avg_PnL_%"), "pct"),
        },
        "late_skipped_names": names(late_skip),
        "tiny_skipped_names": names(tiny_skip),
    }

    write_baseline(focus_rows, whatif, len(book))
    write_html(focus_rows, light, whatif, m_all, m_late, m_tiny, len(book))

    dump = []
    for r in focus_rows:
        dump.append({k: v for k, v in r.items() if k != "_trade" and not isinstance(v, (np.ndarray,))})
    (OUT / "three_trade_read.json").write_text(json.dumps(dump, indent=2, default=str), encoding="utf-8")
    (OUT / "whatif.json").write_text(json.dumps(whatif, indent=2, default=str), encoding="utf-8")
    print(f"wrote {OUT / 'compare.html'}")
    print(f"wrote {OUT / 'BASELINE.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
