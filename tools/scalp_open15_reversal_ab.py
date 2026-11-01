#!/usr/bin/env python3
"""Scalp: opening-15m reversal + 5m hammer/hanging-man / engulfing (research).

Long: open15 loser (C<O) + range>25% ATR; look BELOW open15 low for green hammer /
bullish engulf; entry next 5m open; stop 0.1% below LOD; target open15 High; time 11:30.

Short: open15 winner (C>O) + range>25% ATR; look ABOVE open15 high for red bearish hammer
(hanging-man OR shooting-star) / bearish engulf; entry next 5m open; stop 0.1% above HOD;
target open15 Low; time 11:30 (or --ext no-timestop + EOD 15:55).

entirely_out: long setup High < open15 Low; short setup Low > open15 High.

Usage:
  python tools/scalp_open15_reversal_ab.py
  python tools/scalp_open15_reversal_ab.py -s SPY,AAPL
  python tools/scalp_open15_reversal_ab.py --all --sides both --stamp scalp_longshort_20260822
  python tools/scalp_open15_reversal_ab.py --all --ext --stamp scalp_longshort_ext_20260822
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import math
import sys
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stock_analysis"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

from intraday_1m import (  # noqa: E402
    DEFAULT_1M_DIR,
    ET,
    read_1m,
    resample_ohlcv,
)
from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    format_money,
    overlay_ann_ror_max_dd,
)

DRIVE = ROOT / "drive"
DATA_DIR = ROOT / "data" / "newdata" / "data"
DEFAULT_STAMP = "scalp_fulluniv_20260822"
SYSTEM = "scalp"

# Runtime stamp / out-dir (set in main / run)
STAMP = DEFAULT_STAMP
OUT_DIR = DRIVE / "paul_experiments" / DEFAULT_STAMP

# --- Freeze (see BASELINE.md) ---
DAILY_ATR_N = 14
ATR_METHOD = "wilder"  # Wilder ATR(14) on daily OHLC
RANGE_FRAC = 0.25  # open15 (H−L) > this × prior-close daily ATR
SETUP_DEADLINE = time(11, 0)  # setups must start before 11:00 ET
TIME_STOP_T = time(11, 30)  # exit at 11:30 bar open if still open
STOP_LOD_PCT = 0.1  # long: LOD*(1-0.1%); short: HOD*(1+0.1%)
SESSION_OPEN = time(9, 30)
SHEET = 45_000.0
INIT_ACCT = DEFAULT_INITIAL_ACCOUNT
COSTS_BPS = 0.0
ADV_BARS = 20  # ADV$ = mean(Close×Volume) over prior ADV_BARS sessions

# Green hammer / red hanging-man freeze (same wick geometry; color flips)
HAMMER_LOWER_WICK_BODY = 2.0  # lower wick >= 2× body
HAMMER_UPPER_WICK_BODY = 0.5  # upper wick <= 0.5× body ("small")
HAMMER_CLOSE_UPPER_HALF = True  # long: close in upper half; short: close in lower half

# Short bearish-hammer freeze (ext 20260822): hanging-man OR shooting-star.
# Prior hanging-man-only (long lower wick) never fired above open15 high; shooting-star
# (long upper wick) is the natural rejection candle for shorts above highs.
BEARISH_HAMMER_WICK_BODY = 2.0
BEARISH_HAMMER_OPP_WICK_BODY = 0.5
BEARISH_HAMMER_CLOSE_LOWER_HALF = True
EOD_FLAT_T = time(15, 55)  # safety flat when time-stop removed

# open15 range / ATR descriptive buckets (gate still >25% ATR)
RANGE_ATR_BUCKETS = [
    ("25_40pct", 0.25, 0.40),
    ("40_60pct", 0.40, 0.60),
    ("60_100pct", 0.60, 1.00),
    ("gt_100pct", 1.00, float("inf")),
]

# Institutional ADV$ buckets (prior-close ADV$)
ADV_BUCKETS = [
    ("micro_<1m", 0.0, 1_000_000.0),
    ("small_1m_5m", 1_000_000.0, 5_000_000.0),
    ("mid_5m_20m", 5_000_000.0, 20_000_000.0),
    ("large_20m_100m", 20_000_000.0, 100_000_000.0),
    ("mega_100m+", 100_000_000.0, float("inf")),
]

# Stop-variant freezes (full levers pack)
STOP_SETUP_BUFFER_PCT = 0.05  # long below setup low; short above setup high
STOP_PRIOR_BUFFER_PCT = 0.0  # prior-day / prior-week: exact level (freeze)
OPEN15_DOJI_BODY_FRAC = 0.10  # body/range < this → doji-like
OPEN15_MARUBOZU_BODY_FRAC = 0.90  # body/range >= this → marubozu-like
OPEN15_LONG_WICK_FRAC = 0.40  # wick/range >= this → long upper/lower label


def sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


SORT_JS = r"""
<script>
(function () {
  /* Mobile-safe sort: click + touchend, suppress iOS ghost click, touch-action via CSS. */
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
        return; /* iOS ghost click after touchend */
      }
      var type = th.dataset.sort || th.getAttribute("data-sort") || "text";
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

SORT_CSS = """
th.sortable-th {
  cursor: pointer;
  user-select: none;
  -webkit-user-select: none;
  white-space: nowrap;
  padding: 12px 10px;
  min-height: 44px;
  touch-action: manipulation;
  -webkit-tap-highlight-color: rgba(15, 23, 42, 0.12);
}
th.sortable-th:hover, th.sortable-th:active { background: #e2e8f0; }
th.sortable-th .sort-ind::after { content: " \\2195"; opacity: .35; font-size: .85em; }
th.sortable-th.sort-asc .sort-ind::after { content: " \\2191"; opacity: .9; }
th.sortable-th.sort-desc .sort-ind::after { content: " \\2193"; opacity: .9; }
@media (hover: none) {
  th.sortable-th { padding: 14px 12px; }
}
"""


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


def wilder_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int) -> np.ndarray:
    prev = np.roll(close, 1)
    prev[0] = close[0]
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    atr = np.full_like(tr, np.nan, dtype=float)
    if len(tr) < n:
        return atr
    atr[n - 1] = float(np.mean(tr[:n]))
    for i in range(n, len(tr)):
        atr[i] = (atr[i - 1] * (n - 1) + tr[i]) / n
    return atr


def prior_close_atr_map(daily: pd.DataFrame) -> dict[date, float]:
    """ATR as of prior close: for session D use Wilder ATR including D-1 only."""
    atr = wilder_atr(
        daily["High"].to_numpy(dtype=float),
        daily["Low"].to_numpy(dtype=float),
        daily["Close"].to_numpy(dtype=float),
        DAILY_ATR_N,
    )
    dates = list(daily["Date"])
    out: dict[date, float] = {}
    for i in range(1, len(dates)):
        v = float(atr[i - 1])
        if math.isfinite(v) and v > 0:
            out[dates[i]] = v
    return out


def prior_close_adv_map(daily: pd.DataFrame) -> dict[date, float]:
    """ADV$ as of prior close: mean(Close×Volume) over prior ADV_BARS sessions ending D-1."""
    close = daily["Close"].to_numpy(dtype=float)
    vol = daily["Volume"].to_numpy(dtype=float)
    dv = close * vol
    dates = list(daily["Date"])
    out: dict[date, float] = {}
    for i in range(1, len(dates)):
        end = i  # exclusive; sessions 0..i-1 available; use last ADV_BARS of those
        start = end - ADV_BARS
        if start < 0:
            continue
        v = float(np.mean(dv[start:end]))
        if math.isfinite(v) and v > 0:
            out[dates[i]] = v
    return out


def adv_bucket(adv: float) -> str:
    if not math.isfinite(adv) or adv <= 0:
        return "unknown"
    for name, lo, hi in ADV_BUCKETS:
        if lo <= adv < hi:
            return name
    return "unknown"


def _is_green(o: float, c: float) -> bool:
    return c > o


def _is_red(o: float, c: float) -> bool:
    return c < o


def is_green_hammer(o: float, h: float, l: float, c: float) -> bool:
    """Green hammer: body>0, lower wick >= 2× body, upper wick <= 0.5× body,
    close in upper half of range."""
    if not _is_green(o, c):
        return False
    body = c - o
    if body <= 0:
        return False
    rng = h - l
    if rng <= 0:
        return False
    lower = min(o, c) - l
    upper = h - max(o, c)
    if lower < HAMMER_LOWER_WICK_BODY * body:
        return False
    if upper > HAMMER_UPPER_WICK_BODY * body:
        return False
    if HAMMER_CLOSE_UPPER_HALF and c < (l + h) / 2.0:
        return False
    return True


def is_red_hanging_man(o: float, h: float, l: float, c: float) -> bool:
    """Red hanging-man: classic long-lower-wick geometry (same ratios as green hammer).
    Close < Open; lower wick >= 2× body; upper wick <= 0.5× body; close in lower half."""
    if not _is_red(o, c):
        return False
    body = o - c
    if body <= 0:
        return False
    rng = h - l
    if rng <= 0:
        return False
    lower = min(o, c) - l
    upper = h - max(o, c)
    if lower < HAMMER_LOWER_WICK_BODY * body:
        return False
    if upper > HAMMER_UPPER_WICK_BODY * body:
        return False
    if HAMMER_CLOSE_UPPER_HALF and c > (l + h) / 2.0:
        return False
    return True


def is_red_shooting_star(o: float, h: float, l: float, c: float) -> bool:
    """Red shooting-star: long upper wick, small lower wick; close in lower half.
    Natural rejection candle when price is extending above open15 high."""
    if not _is_red(o, c):
        return False
    body = o - c
    if body <= 0:
        return False
    rng = h - l
    if rng <= 0:
        return False
    lower = min(o, c) - l
    upper = h - max(o, c)
    if upper < BEARISH_HAMMER_WICK_BODY * body:
        return False
    if lower > BEARISH_HAMMER_OPP_WICK_BODY * body:
        return False
    if BEARISH_HAMMER_CLOSE_LOWER_HALF and c > (l + h) / 2.0:
        return False
    return True


def is_bearish_hammer(o: float, h: float, l: float, c: float) -> bool:
    """Short setup hammer family: red hanging-man OR red shooting-star (same wick ratios)."""
    return is_red_hanging_man(o, h, l, c) or is_red_shooting_star(o, h, l, c)


def range_atr_bucket(ratio: float) -> str:
    if not math.isfinite(ratio) or ratio <= 0:
        return "unknown"
    for name, lo, hi in RANGE_ATR_BUCKETS:
        if lo <= ratio < hi or (hi == float("inf") and ratio >= lo):
            return name
    return "unknown"


def is_bullish_engulfing(
    prev_o: float,
    prev_h: float,
    prev_l: float,
    prev_c: float,
    o: float,
    h: float,
    l: float,
    c: float,
) -> bool:
    """Green candle High > prior High AND Low < prior Low; prior must be red."""
    if not _is_red(prev_o, prev_c):
        return False
    if not _is_green(o, c):
        return False
    return h > prev_h and l < prev_l


def is_bearish_engulfing(
    prev_o: float,
    prev_h: float,
    prev_l: float,
    prev_c: float,
    o: float,
    h: float,
    l: float,
    c: float,
) -> bool:
    """Red candle High > prior High AND Low < prior Low; prior must be green."""
    if not _is_green(prev_o, prev_c):
        return False
    if not _is_red(o, c):
        return False
    return h > prev_h and l < prev_l


def rth_filter(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    t = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(ET)
    tod = t.dt.time
    mask = (tod >= SESSION_OPEN) & (tod < time(16, 0))
    return df.loc[mask].copy().reset_index(drop=True)


def session_dates(df_1m: pd.DataFrame) -> list[date]:
    if df_1m.empty:
        return []
    t = pd.to_datetime(df_1m["ts"], utc=True).dt.tz_convert(ET)
    return sorted({pd.Timestamp(x).date() for x in t})


def bars_on_day(df: pd.DataFrame, d: date) -> pd.DataFrame:
    t = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(ET)
    return df.loc[t.dt.date == d].copy().reset_index(drop=True)


def _ts_time(ts: Any) -> time:
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize(ET)
    else:
        t = t.tz_convert(ET)
    return t.timetz().replace(tzinfo=None) if hasattr(t, "timetz") else t.time()


def resolve_exit(
    day5: pd.DataFrame,
    entry_i: int,
    *,
    side: str,
    entry: float,
    stop: float,
    target: float,
    time_stop: Optional[time],
    eod_flat: time,
) -> tuple[float, str, str]:
    """Walk 5m bars from entry; return (exit_px, exit_ts, exit_type)."""
    for j in range(entry_i, len(day5)):
        bar = day5.iloc[j]
        bt = _ts_time(bar["ts"])
        if time_stop is not None and bt >= time_stop:
            return float(bar["open"]), str(bar["ts"]), "TIME"
        if time_stop is None and bt >= eod_flat:
            return float(bar["open"]), str(bar["ts"]), "EOD_FLAT"
        lo = float(bar["low"])
        hi = float(bar["high"])
        if side == "long":
            if lo <= stop:
                return stop, str(bar["ts"]), "STOP"
            if hi >= target:
                return target, str(bar["ts"]), "TARGET"
        else:
            if hi >= stop:
                return stop, str(bar["ts"]), "STOP"
            if lo <= target:
                return target, str(bar["ts"]), "TARGET"
    last = day5.iloc[-1]
    return float(last["close"]), str(last["ts"]), "INCOMPLETE_EOD"


def simulate_day(
    sym: str,
    d: date,
    df5: pd.DataFrame,
    df15: pd.DataFrame,
    atr_prior: float,
    *,
    sides: set[str],
    adv_prior: float = float("nan"),
    time_stop: Optional[time] = TIME_STOP_T,
    eod_flat: time = EOD_FLAT_T,
) -> tuple[Optional[dict[str, Any]], dict[str, Any]]:
    """Return (trade_or_None, day_diag). At most one trade per symbol/day (side gated by open15)."""
    diag: dict[str, Any] = {
        "symbol": sym,
        "session": str(d),
        "atr_prior": atr_prior,
        "adv_prior": adv_prior if math.isfinite(adv_prior) else "",
        "gate": "",
        "skip_reason": "",
        "side": "",
    }
    day15 = bars_on_day(df15, d)
    day5 = bars_on_day(df5, d)
    if day15.empty or day5.empty:
        diag["skip_reason"] = "no_intraday_bars"
        return None, diag

    open15 = day15.loc[day15["ts"].map(_ts_time) == SESSION_OPEN]
    if open15.empty:
        diag["skip_reason"] = "missing_open15"
        return None, diag
    o15 = open15.iloc[0]
    o15_o, o15_h, o15_l, o15_c = float(o15["open"]), float(o15["high"]), float(o15["low"]), float(o15["close"])
    o15_rng = o15_h - o15_l
    rva = o15_rng / atr_prior if atr_prior > 0 else float("nan")
    diag.update(
        {
            "open15_o": o15_o,
            "open15_h": o15_h,
            "open15_l": o15_l,
            "open15_c": o15_c,
            "open15_range": o15_rng,
            "range_vs_atr": rva,
        }
    )

    if not (o15_rng > RANGE_FRAC * atr_prior):
        diag["gate"] = "atr_fail"
        diag["skip_reason"] = f"open15_range_not_gt_{RANGE_FRAC*100:.0f}pct_atr"
        return None, diag

    side = ""
    if o15_c < o15_o and "long" in sides:
        side = "long"
    elif o15_c > o15_o and "short" in sides:
        side = "short"
    else:
        diag["gate"] = "direction_mismatch"
        if o15_c < o15_o:
            diag["skip_reason"] = "open15_loser_long_disabled"
        elif o15_c > o15_o:
            diag["skip_reason"] = "open15_winner_short_disabled"
        else:
            diag["skip_reason"] = "open15_doji"
        return None, diag
    diag["side"] = side
    diag["gate"] = "pass"

    candidates: list[tuple[int, str, str]] = []
    for i in range(len(day5)):
        row = day5.iloc[i]
        tt = _ts_time(row["ts"])
        if tt < time(9, 45):
            continue
        if tt >= SETUP_DEADLINE:
            break
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        kind = ""
        subkind = ""
        if side == "long":
            if not (l < o15_l):
                continue
            if is_green_hammer(o, h, l, c):
                kind = "hammer"
                subkind = "hammer"
            elif i >= 1:
                prev = day5.iloc[i - 1]
                if is_bullish_engulfing(
                    float(prev["open"]),
                    float(prev["high"]),
                    float(prev["low"]),
                    float(prev["close"]),
                    o,
                    h,
                    l,
                    c,
                ):
                    kind = "engulfing"
                    subkind = "engulfing"
        else:  # short
            if not (h > o15_h):
                continue
            # Prefer shooting-star / hanging-man before engulf (first bar wins either way)
            if is_red_shooting_star(o, h, l, c):
                kind = "bearish_hammer"
                subkind = "shooting_star"
            elif is_red_hanging_man(o, h, l, c):
                kind = "bearish_hammer"
                subkind = "hanging_man"
            elif i >= 1:
                prev = day5.iloc[i - 1]
                if is_bearish_engulfing(
                    float(prev["open"]),
                    float(prev["high"]),
                    float(prev["low"]),
                    float(prev["close"]),
                    o,
                    h,
                    l,
                    c,
                ):
                    kind = "bearish_engulfing"
                    subkind = "bearish_engulfing"
        if kind:
            candidates.append((i, kind, subkind))

    if not candidates:
        diag["skip_reason"] = "no_setup"
        return None, diag

    setup_i, setup_kind, setup_subkind = candidates[0]
    setup = day5.iloc[setup_i]
    setup_h = float(setup["high"])
    setup_l = float(setup["low"])
    if side == "long":
        entirely_out = setup_h < o15_l
    else:
        entirely_out = setup_l > o15_h
    entirely_out_label = "entirely_out" if entirely_out else "partial"

    entry_i = setup_i + 1
    if entry_i >= len(day5):
        diag["skip_reason"] = "no_entry_bar"
        return None, diag
    entry_bar = day5.iloc[entry_i]
    entry_t = _ts_time(entry_bar["ts"])
    # Skip if entry is already at/after the active hard stop clock
    hard_deadline = time_stop if time_stop is not None else eod_flat
    if entry_t >= hard_deadline:
        diag["skip_reason"] = "entry_at_or_after_time_stop"
        return None, diag

    entry = float(entry_bar["open"])
    if side == "long":
        lod = float(day5.iloc[: setup_i + 1]["low"].min())
        stop = lod * (1.0 - STOP_LOD_PCT / 100.0)
        target = o15_h
        extreme = lod
    else:
        hod = float(day5.iloc[: setup_i + 1]["high"].max())
        stop = hod * (1.0 + STOP_LOD_PCT / 100.0)
        target = o15_l
        extreme = hod
        lod = float("nan")  # unused for short; keep field for CSV schema

    diag.update(
        {
            "setup_kind": setup_kind,
            "setup_subkind": setup_subkind,
            "setup_ts": str(setup["ts"]),
            "entry_ts": str(entry_bar["ts"]),
            "entry": entry,
            "lod": lod if side == "long" else "",
            "hod": extreme if side == "short" else "",
            "stop": stop,
            "target": target,
            "entirely_out": entirely_out_label,
        }
    )

    if side == "long":
        if stop >= entry:
            diag["skip_reason"] = "stop_ge_entry"
            return None, diag
        if target <= entry:
            diag["skip_reason"] = "target_le_entry"
            return None, diag
    else:
        if stop <= entry:
            diag["skip_reason"] = "stop_le_entry"
            return None, diag
        if target >= entry:
            diag["skip_reason"] = "target_ge_entry"
            return None, diag

    exit_px, exit_ts, exit_type = resolve_exit(
        day5,
        entry_i,
        side=side,
        entry=entry,
        stop=stop,
        target=target,
        time_stop=time_stop,
        eod_flat=eod_flat,
    )

    if side == "long":
        pnl_pct = (exit_px / entry - 1.0) * 100.0
        risk = entry - stop
        r_mult = (exit_px - entry) / risk if risk > 0 else float("nan")
        shares = math.floor(SHEET / entry) if entry > 0 else 0
        pnl_usd = shares * (exit_px - entry)
    else:
        # Short % return on capital: (entry - exit) / entry
        pnl_pct = (entry - exit_px) / entry * 100.0
        risk = stop - entry
        r_mult = (entry - exit_px) / risk if risk > 0 else float("nan")
        shares = math.floor(SHEET / entry) if entry > 0 else 0
        pnl_usd = shares * (entry - exit_px)

    trade = {
        "symbol": sym,
        "side": side,
        "session": str(d),
        "setup_kind": setup_kind,
        "setup_subkind": setup_subkind,
        "entirely_out": entirely_out_label,
        "setup_ts": str(setup["ts"]),
        "entry_ts": str(entry_bar["ts"]),
        "exit_ts": exit_ts,
        "entry": round(entry, 6),
        "stop": round(stop, 6),
        "target": round(target, 6),
        "lod": round(lod, 6) if side == "long" and math.isfinite(lod) else "",
        "hod": round(extreme, 6) if side == "short" else "",
        "setup_h": round(setup_h, 6),
        "setup_l": round(setup_l, 6),
        "exit": round(exit_px, 6),
        "exit_type": exit_type,
        "pnl_pct": round(pnl_pct, 6),
        "r_mult": round(r_mult, 6) if math.isfinite(r_mult) else "",
        "shares": shares,
        "pnl_usd": round(pnl_usd, 2),
        "atr_prior": round(atr_prior, 6),
        "adv_prior": round(adv_prior, 2) if math.isfinite(adv_prior) else "",
        "adv_bucket": adv_bucket(adv_prior),
        "open15_o": round(o15_o, 6),
        "open15_h": round(o15_h, 6),
        "open15_l": round(o15_l, 6),
        "open15_c": round(o15_c, 6),
        "open15_range": round(o15_rng, 6),
        "range_vs_atr": round(rva, 6) if math.isfinite(rva) else "",
        "range_atr_bucket": range_atr_bucket(rva),
        "time_stop_arm": "1130" if time_stop is not None else "none_eod1555",
        "stop_arm": "control_lod_hod_0p1",
        "win": 1 if pnl_pct > 0 else 0,
    }
    return trade, diag


def metrics_from_trades(
    trades: list[dict[str, Any]],
    *,
    include_slices: bool = True,
) -> dict[str, Any]:
    n = len(trades)
    empty = {
        "N": 0,
        "Wins": 0,
        "Losses": 0,
        "Win%": float("nan"),
        "Total_PnL_$": 0.0,
        "Sheet_PnL_$": 0.0,
        "Avg_PnL_%": float("nan"),
        "AVG_PNL_PCT_WO_MAX": float("nan"),
        "Expectancy_%": float("nan"),
        "Expectancy_$": float("nan"),
        "Avg_Win_%": float("nan"),
        "Avg_Loss_%": float("nan"),
        "WL_count_ratio": float("nan"),
        "Profit_Factor": float("nan"),
        "Ann_ROR_%": float("nan"),
        "Max_DD_%": float("nan"),
        "exit_mix": {},
        "by_setup": {},
        "by_side": {},
        "by_entirely_out": {},
        "by_adv_bucket": {},
        "by_crosstab": {},
        "by_range_atr": {},
        "by_subkind": {},
        "sessions": [],
        "session_min": "",
        "session_max": "",
    }
    if n == 0:
        return empty
    pnls = [float(t["pnl_pct"]) for t in trades]
    usds = [float(t["pnl_usd"]) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    w_usd = [u for u in usds if u > 0]
    l_usd = [u for u in usds if u <= 0]
    gross_win = sum(w_usd)
    gross_loss = abs(sum(l_usd))
    pf = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else float("nan"))

    wo_max = pnls.copy()
    if wins:
        wo_max.remove(max(pnls))
    avg_wo = float(np.mean(wo_max)) if wo_max else float("nan")

    ov_rows: list[dict[str, Any]] = []
    for t in trades:
        et = pd.Timestamp(t["entry_ts"])
        xt = pd.Timestamp(t["exit_ts"])
        hold_days = max(0.01, (xt - et).total_seconds() / 86400.0)
        ov_rows.append(
            {
                "pnl_d": float(t["pnl_usd"]),
                "pnl": float(t["pnl_pct"]),
                "days": hold_days,
                "closed": xt.date() if hasattr(xt, "date") else xt,
                "opened": et.date() if hasattr(et, "date") else et,
            }
        )
    ov = overlay_ann_ror_max_dd(ov_rows, cash=SHEET, initial_account=INIT_ACCT)
    avg_hold = float(np.mean([r["days"] for r in ov_rows])) if ov_rows else 0.0
    ann = float("nan") if avg_hold < 0.5 else ov.get("ann_ror", float("nan"))

    exit_mix: dict[str, int] = {}
    for t in trades:
        exit_mix[t["exit_type"]] = exit_mix.get(t["exit_type"], 0) + 1

    by_setup: dict[str, dict[str, Any]] = {}
    by_side: dict[str, dict[str, Any]] = {}
    by_eo: dict[str, dict[str, Any]] = {}
    by_adv: dict[str, dict[str, Any]] = {}
    by_crosstab: dict[str, dict[str, Any]] = {}
    by_range: dict[str, dict[str, Any]] = {}
    by_subkind: dict[str, dict[str, Any]] = {}
    if include_slices:
        for kind in sorted({str(t.get("setup_kind") or "") for t in trades if t.get("setup_kind")}):
            sub = [t for t in trades if t.get("setup_kind") == kind]
            by_setup[kind] = metrics_from_trades(sub, include_slices=False)
        for side in sorted({str(t.get("side") or "") for t in trades if t.get("side")}):
            sub = [t for t in trades if t.get("side") == side]
            by_side[side] = metrics_from_trades(sub, include_slices=False)
        for eo in ("entirely_out", "partial"):
            sub = [t for t in trades if t.get("entirely_out") == eo]
            if sub:
                by_eo[eo] = metrics_from_trades(sub, include_slices=False)
        for b in sorted({str(t.get("adv_bucket") or "unknown") for t in trades}):
            sub = [t for t in trades if str(t.get("adv_bucket") or "unknown") == b]
            by_adv[b] = metrics_from_trades(sub, include_slices=False)
        for side in ("long", "short"):
            for eo in ("entirely_out", "partial"):
                key = f"{eo}×{side}"
                sub = [t for t in trades if t.get("side") == side and t.get("entirely_out") == eo]
                if sub:
                    by_crosstab[key] = metrics_from_trades(sub, include_slices=False)
        for b in [x[0] for x in RANGE_ATR_BUCKETS] + ["unknown"]:
            sub = [t for t in trades if str(t.get("range_atr_bucket") or "unknown") == b]
            if sub:
                by_range[b] = metrics_from_trades(sub, include_slices=False)
        for sk in sorted({str(t.get("setup_subkind") or "") for t in trades if t.get("setup_subkind")}):
            sub = [t for t in trades if t.get("setup_subkind") == sk]
            by_subkind[sk] = metrics_from_trades(sub, include_slices=False)

    sessions = sorted({str(t.get("session")) for t in trades if t.get("session")})
    return {
        "N": n,
        "Wins": len(wins),
        "Losses": len(losses),
        "Win%": 100.0 * len(wins) / n,
        "Total_PnL_$": sum(usds),
        "Sheet_PnL_$": sum(usds),
        "Avg_PnL_%": float(np.mean(pnls)),
        "AVG_PNL_PCT_WO_MAX": avg_wo,
        "Expectancy_%": float(np.mean(pnls)),
        "Expectancy_$": float(np.mean(usds)),
        "Avg_Win_%": float(np.mean(wins)) if wins else float("nan"),
        "Avg_Loss_%": float(np.mean(losses)) if losses else float("nan"),
        "WL_count_ratio": (len(wins) / len(losses)) if losses else float("nan"),
        "Profit_Factor": pf,
        "Ann_ROR_%": ann,
        "Max_DD_%": ov.get("max_dd", float("nan")),
        "exit_mix": exit_mix,
        "by_setup": by_setup,
        "by_side": by_side,
        "by_entirely_out": by_eo,
        "by_adv_bucket": by_adv,
        "by_crosstab": by_crosstab,
        "by_range_atr": by_range,
        "by_subkind": by_subkind,
        "sessions": sessions,
        "session_min": sessions[0] if sessions else "",
        "session_max": sessions[-1] if sessions else "",
    }


def per_symbol_stats(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_sym: dict[str, list[dict[str, Any]]] = {}
    for t in trades:
        by_sym.setdefault(str(t["symbol"]), []).append(t)
    rows: list[dict[str, Any]] = []
    for sym, ts in by_sym.items():
        pnls = [float(x["pnl_pct"]) for x in ts]
        usds = [float(x["pnl_usd"]) for x in ts]
        advs = [float(x["adv_prior"]) for x in ts if x.get("adv_prior") not in ("", None)]
        n = len(ts)
        wins = sum(1 for p in pnls if p > 0)
        rows.append(
            {
                "symbol": sym,
                "N": n,
                "Wins": wins,
                "Win%": 100.0 * wins / n if n else float("nan"),
                "Avg_PnL_%": float(np.mean(pnls)),
                "Total_PnL_$": sum(usds),
                "median_adv_prior": float(np.median(advs)) if advs else float("nan"),
                "adv_bucket_mode": max(
                    {str(x.get("adv_bucket") or "unknown") for x in ts},
                    key=lambda b: sum(1 for x in ts if str(x.get("adv_bucket") or "unknown") == b),
                ),
                "n_long": sum(1 for x in ts if x.get("side") == "long"),
                "n_short": sum(1 for x in ts if x.get("side") == "short"),
                "n_entirely_out": sum(1 for x in ts if x.get("entirely_out") == "entirely_out"),
            }
        )
    rows.sort(key=lambda r: (r["Avg_PnL_%"], r["Total_PnL_$"]), reverse=True)
    return rows


def _fmt_num(v: Any, nd: int = 2) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    if isinstance(v, float) and abs(v) == float("inf"):
        return "inf"
    try:
        return f"{float(v):.{nd}f}"
    except (TypeError, ValueError):
        return str(v)


def write_baseline(
    path: Path,
    *,
    symbols: list[str],
    coverage_note: str,
    n_trades: int,
    sides: set[str],
) -> None:
    univ = (
        f"All symbols with non-empty 1m parquet under `data/intraday/1m/` "
        f"(n={len(symbols)} requested this run)"
        if len(symbols) > 10
        else ", ".join(symbols)
    )
    sides_s = "+".join(sorted(sides))
    text = f"""# BASELINE — Scalp open-15 long/short reversal — `{STAMP}`

**System:** `{SYSTEM}` (research only). **Not** DailyRun. **Not** gold.

## Freeze

Long arm matches prior `scalp_fulluniv_20260822` / `scalp_20260821` knobs. Short arm is the **geometric inverse** (one-change side add). No intentional long retune.

| Knob | Value |
|------|--------|
| Universe | {univ} |
| Sides | **{sides_s}** |
| Daily ATR | **Wilder ATR({DAILY_ATR_N})** on daily OHLC from `data/newdata/data/` |
| ATR look-ahead | **None.** For session date D, use ATR as of **prior close** (ATR series including D−1 only). |
| ADV$ | Prior-close **{ADV_BARS}d** mean(Close×Volume); institutional buckets only (not a trade filter) |
| Open 15m bar | Left-labeled **09:30 ET** (covers 09:30–09:44) via `resample_ohlcv` / `intraday_1m` |
| ATR gate | open15 (High−Low) **>** {RANGE_FRAC*100:.0f}% × prior-close daily ATR |
| Long open15 | **Loser:** Close < Open |
| Short open15 | **Winner (green):** Close > Open |
| Setup TF | **5m** (from 1m store) |
| Long setup location | setup Low **<** open15 Low |
| Short setup location | setup High **>** open15 High |
| Setup window | setup bar start **≥ 09:45** and **< 11:00 ET** (within ~90m of open) |
| Hammer (green, long) | Close > Open; lower wick ≥ {HAMMER_LOWER_WICK_BODY:g}× body; upper wick ≤ {HAMMER_UPPER_WICK_BODY:g}× body; close in upper half |
| Bearish hammer (red, short) | Close < Open; **hanging-man** (lower wick ≥ {BEARISH_HAMMER_WICK_BODY:g}× body, upper ≤ {BEARISH_HAMMER_OPP_WICK_BODY:g}× body) **OR shooting-star** (upper wick ≥ {BEARISH_HAMMER_WICK_BODY:g}× body, lower ≤ {BEARISH_HAMMER_OPP_WICK_BODY:g}× body); close in lower half. `setup_kind=bearish_hammer`; subkind hanging_man/shooting_star. Rationale: hanging-man-only never fired above open15 high. |
| Bullish engulfing | Prior red; current green; High > prior High **and** Low < prior Low |
| Bearish engulfing | Prior green; current red; High > prior High **and** Low < prior Low |
| Setup priority | First qualifying pattern (whichever appears first) |
| Entry | Open of **next** 5m bar after setup |
| Long stop | **{STOP_LOD_PCT:g}% below LOD so far** (min 5m low open→setup inclusive) |
| Short stop | **{STOP_LOD_PCT:g}% above HOD so far** (max 5m high open→setup inclusive) |
| Long target | High of opening 15m candle |
| Short target | Low of opening 15m candle |
| Time stop | Default control: if still open at **11:30 ET**, exit at **11:30 bar open**. Candidate (ext): **no 11:30 time stop**; TARGET+STOP only; safety **EOD flat at {EOD_FLAT_T.strftime('%H:%M')} ET** bar open (`EOD_FLAT`). |
| Same-bar pathing | Stop checked before target (conservative) |
| entirely_out | Long: setup High **<** open15 Low. Short: setup Low **>** open15 High. Else `partial`. |
| Frequency | One trade per symbol per day (open15 direction selects side) |
| Costs | {COSTS_BPS} bps |
| Sheet notional | ${SHEET:,.0f} / trade (floor shares) |
| Ann ROR | **Not meaningful** for same-session scalps; reported as — in compare.html. Max DD from $500k equity overlay still shown. |

## Coverage / honesty

{coverage_note}

- Trades this stamp: **N={n_trades}**.
- Research candidate bar only — **not** gold / **not** DailyRun.

## Split

Default chronological IS (`entry_date < 2024-01-01`) / OOS is **not applicable** — all 1m bars are post-2024 and the window is short (Yahoo retention). Do **not** invent a fake OOS. Full-book metrics only; by-side / entirely_out / ADV$ slices are descriptive, not holdouts.
"""
    path.write_text(text, encoding="utf-8")


def write_ab_plan(path: Path) -> None:
    text = f"""# AB_PLAN — Scalp `{STAMP}`

## Hypothesis

A wide opening 15-minute candle (range > 25% of prior-close daily ATR) sets a morning
exhaustion extreme. **Longs** buy the first green hammer / bullish engulf **below** an
open-15 loser low; **shorts** sell the first red hanging-man / bearish engulf **above**
an open-15 winner high — targeting the opposite open-15 extreme with a tight LOD/HOD stop.

**entirely_out** setups (setup bar completely outside the open-15 range) may show cleaner
reversal quality than partial overlaps.

## One-knob / smoke scope

This stamp freezes the long arm and adds the short inverse as a **side** extension (not a
knob retune of longs). Future A/Bs should change **one** knob with this BASELINE as control.

## Success criteria (pre-registered)

- Quality over count: WR, Avg PnL%, expectancy, PF, Max DD — not max single-trade PnL.
- Report by side, entirely_out vs partial, and ADV$ institutional buckets.
- KEEP only if quality is clearly positive with usable N **and** longer / walk-forward coverage.
- OOS / walk-forward required before gold; never retune on holdout.

## Verdict policy for this run

- N &lt; 20 → HOLD (insufficient).
- Soft / mixed quality on short coverage → HOLD (research only).
- Clearly negative expectancy + soft WR → DISMISS as research dead-end pending more data.
"""
    path.write_text(text, encoding="utf-8")


def _slice_table(
    title: str,
    note: str,
    key_label: str,
    slices: dict[str, dict[str, Any]],
) -> str:
    cols = [
        (key_label, "text"),
        ("N", "num"),
        ("Win%", "num"),
        ("Avg_PnL_%", "num"),
        ("Profit_Factor", "num"),
        ("Total_PnL_$", "money"),
        ("Max_DD_%", "num"),
    ]
    head = "".join(sortable_th(c, t) for c, t in cols)
    body = []
    for key, sm in sorted(slices.items()):
        cells = [
            f"<td>{html_mod.escape(str(key))}</td>",
            f"<td>{int(sm.get('N') or 0)}</td>",
            f"<td>{_fmt_num(sm.get('Win%'), 2)}</td>",
            f"<td>{_fmt_num(sm.get('Avg_PnL_%'), 4)}</td>",
            f"<td>{_fmt_num(sm.get('Profit_Factor'), 2)}</td>",
            f"<td>{format_money(sm.get('Total_PnL_$')) if isinstance(sm.get('Total_PnL_$'), (int, float)) else '—'}</td>",
            f"<td>{_fmt_num(sm.get('Max_DD_%'), 2)}</td>",
        ]
        body.append("<tr>" + "".join(cells) + "</tr>")
    if not body:
        body.append(f"<tr><td colspan='{len(cols)}'>No trades</td></tr>")
    return f"""
<h2>{html_mod.escape(title)}</h2>
<p>{html_mod.escape(note)} Click headers to sort.</p>
<table class="sortable">
<thead><tr>{head}</tr></thead>
<tbody>
{''.join(body)}
</tbody>
</table>
"""


def write_compare_html(
    path: Path,
    trades: list[dict[str, Any]],
    diags: list[dict[str, Any]],
    metrics: dict[str, Any],
    symbols: list[str],
    verdict: str,
    *,
    coverage_note: str,
    institutional_takeaway: str,
) -> None:
    m = metrics
    exit_mix = m.get("exit_mix") or {}
    exit_rows = "".join(
        f"<tr><td>{html_mod.escape(k)}</td><td>{v}</td>"
        f"<td>{_fmt_num(100.0 * v / m['N'], 1) if m['N'] else '—'}%</td></tr>"
        for k, v in sorted(exit_mix.items())
    ) or "<tr><td colspan='3'>No trades</td></tr>"

    metric_rows = [
        ("N trades", m["N"], "num"),
        ("Wins", m["Wins"], "num"),
        ("Losses", m["Losses"], "num"),
        ("Win %", m["Win%"], "num"),
        ("Total PnL $", m["Total_PnL_$"], "money"),
        ("Sheet PnL $", m["Sheet_PnL_$"], "money"),
        ("Avg PnL %", m["Avg_PnL_%"], "num"),
        ("AVG_PNL_PCT_WO_MAX", m["AVG_PNL_PCT_WO_MAX"], "num"),
        ("Expectancy %", m["Expectancy_%"], "num"),
        ("Expectancy $", m["Expectancy_$"], "money"),
        ("Avg Win %", m["Avg_Win_%"], "num"),
        ("Avg Loss %", m["Avg_Loss_%"], "num"),
        ("W/L count ratio", m["WL_count_ratio"], "num"),
        ("Profit Factor", m["Profit_Factor"], "num"),
        ("Ann ROR %", m["Ann_ROR_%"], "num"),
        ("Max DD %", m["Max_DD_%"], "num"),
        ("Trade sessions min", m.get("session_min") or "—", "text"),
        ("Trade sessions max", m.get("session_max") or "—", "text"),
    ]
    mbody = []
    for lab, val, kind in metric_rows:
        if kind == "money":
            cell = (
                format_money(val)
                if isinstance(val, (int, float)) and math.isfinite(float(val))
                else "—"
            )
        elif lab in ("Wins", "Losses", "N trades") and isinstance(val, (int, float)):
            cell = str(int(val))
        elif kind == "text":
            cell = str(val)
        else:
            cell = _fmt_num(val, 2)
        mbody.append(f"<tr><td>{html_mod.escape(lab)}</td><td>{html_mod.escape(cell)}</td></tr>")

    side_html = _slice_table(
        "By side",
        "Descriptive slice (not a holdout).",
        "side",
        m.get("by_side") or {},
    )
    eo_html = _slice_table(
        "entirely_out vs partial",
        "Long: setup High < open15 Low. Short: setup Low > open15 High.",
        "entirely_out",
        m.get("by_entirely_out") or {},
    )
    adv_html = _slice_table(
        "Institutional — by ADV$ bucket",
        f"Prior-close {ADV_BARS}d ADV$ = mean(Close×Volume). Not a trade filter.",
        "adv_bucket",
        m.get("by_adv_bucket") or {},
    )
    setup_html = _slice_table(
        "By setup_kind",
        "Descriptive slice (not a holdout). Short hammer family = bearish_hammer (hanging_man or shooting_star).",
        "setup_kind",
        m.get("by_setup") or {},
    )
    subkind_html = _slice_table(
        "By setup_subkind",
        "Hammer family detail (shooting_star vs hanging_man vs engulfing).",
        "setup_subkind",
        m.get("by_subkind") or {},
    )
    crosstab_html = _slice_table(
        "Crosstab: entirely_out × side",
        "Four cells: entirely_out/partial × long/short.",
        "cell",
        m.get("by_crosstab") or {},
    )
    range_html = _slice_table(
        "Open15 range vs ATR buckets",
        "Bucket by (open15 H−L) / prior-close ATR. Gate still requires >25% ATR.",
        "range_atr_bucket",
        m.get("by_range_atr") or {},
    )

    sym_rows = per_symbol_stats(trades)
    sym_cols = [
        ("symbol", "text"),
        ("N", "num"),
        ("Wins", "num"),
        ("Win%", "num"),
        ("Avg_PnL_%", "num"),
        ("Total_PnL_$", "money"),
        ("median_adv_prior", "num"),
        ("adv_bucket_mode", "text"),
        ("n_long", "num"),
        ("n_short", "num"),
        ("n_entirely_out", "num"),
    ]
    shead = "".join(sortable_th(c, t) for c, t in sym_cols)
    # Show top 25 + bottom 25 by Avg_PnL_% (full table capped)
    show = sym_rows
    if len(show) > 60:
        top = sym_rows[:25]
        bot = sym_rows[-25:]
        mid_note = f"<p>Showing top 25 and bottom 25 of {len(sym_rows)} symbols by Avg_PnL_% (full list in trades.csv rollup).</p>"
        show = top + bot
    else:
        mid_note = ""
    sbody = []
    for r in show:
        cells = []
        for c, _ in sym_cols:
            v = r.get(c, "")
            if c == "Total_PnL_$" and isinstance(v, (int, float)):
                cells.append(f"<td>{format_money(v)}</td>")
            elif isinstance(v, float):
                cells.append(f"<td>{_fmt_num(v, 4 if 'PnL' in c or 'adv' in c else 2)}</td>")
            else:
                cells.append(f"<td>{html_mod.escape(str(v))}</td>")
        sbody.append("<tr>" + "".join(cells) + "</tr>")
    if not sbody:
        sbody.append(f"<tr><td colspan='{len(sym_cols)}'>No trades</td></tr>")

    trade_cols = [
        ("symbol", "text"),
        ("side", "text"),
        ("session", "date"),
        ("setup_kind", "text"),
        ("entirely_out", "text"),
        ("adv_bucket", "text"),
        ("adv_prior", "num"),
        ("setup_ts", "text"),
        ("entry_ts", "text"),
        ("exit_ts", "text"),
        ("entry", "num"),
        ("stop", "num"),
        ("target", "num"),
        ("exit", "num"),
        ("exit_type", "text"),
        ("pnl_pct", "num"),
        ("r_mult", "num"),
        ("pnl_usd", "num"),
        ("win", "num"),
    ]
    thead = "".join(sortable_th(c, t) for c, t in trade_cols)
    tbody = []
    # Cap trade table for HTML size
    trade_limit = 3000
    for t in trades[:trade_limit]:
        cells = []
        for c, _ in trade_cols:
            v = t.get(c, "")
            if c == "pnl_usd" and isinstance(v, (int, float)):
                cells.append(f"<td>{format_money(v)}</td>")
            elif isinstance(v, float):
                cells.append(f"<td>{_fmt_num(v, 4)}</td>")
            else:
                cells.append(f"<td>{html_mod.escape(str(v))}</td>")
        tbody.append("<tr>" + "".join(cells) + "</tr>")
    trade_note = ""
    if len(trades) > trade_limit:
        trade_note = (
            f"<p>Showing first {trade_limit} of {len(trades)} trades "
            f"(full book in <code>trades.csv</code>).</p>"
        )
    if not tbody:
        tbody.append(f"<tr><td colspan='{len(trade_cols)}'>No trades</td></tr>")

    diag_limit = 5000
    diag_cols = [
        ("symbol", "text"),
        ("session", "date"),
        ("side", "text"),
        ("gate", "text"),
        ("skip_reason", "text"),
        ("atr_prior", "num"),
        ("open15_range", "num"),
        ("range_vs_atr", "num"),
        ("setup_kind", "text"),
        ("entirely_out", "text"),
    ]
    dhead = "".join(sortable_th(c, t) for c, t in diag_cols)
    dbody = []
    for d in diags[:diag_limit]:
        cells = []
        for c, _ in diag_cols:
            v = d.get(c, "")
            if isinstance(v, float):
                cells.append(f"<td>{_fmt_num(v, 4)}</td>")
            else:
                cells.append(f"<td>{html_mod.escape(str(v))}</td>")
        dbody.append("<tr>" + "".join(cells) + "</tr>")
    diag_note = ""
    if len(diags) > diag_limit:
        diag_note = (
            f"<p>Showing first {diag_limit} of {len(diags)} session diag rows "
            f"(full log in <code>session_diag.csv</code>).</p>"
        )

    sym_label = (
        f"{len(symbols)} symbols (--all)"
        if len(symbols) > 12
        else ", ".join(symbols)
    )
    coverage_html = html_mod.escape(coverage_note).replace("\n", "<br/>")
    inst_html = html_mod.escape(institutional_takeaway).replace("\n", "<br/>")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Scalp open15 long/short — {html_mod.escape(STAMP)}</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 1.5rem; color: #0f172a; background: #f8fafc; }}
h1,h2 {{ color: #0f172a; }}
.note {{ background: #fff7ed; border-left: 4px solid #f97316; padding: .75rem 1rem; margin: 1rem 0; }}
.takeaway {{ background: #ecfeff; border-left: 4px solid #0891b2; padding: .75rem 1rem; margin: 1rem 0; }}
.verdict {{ font-size: 1.15rem; font-weight: 600; }}
table {{ border-collapse: collapse; width: 100%; background: #fff; margin: .75rem 0 1.5rem; font-size: .9rem; }}
th, td {{ border: 1px solid #cbd5e1; padding: .35rem .5rem; text-align: left; }}
th {{ background: #e2e8f0; }}
{SORT_CSS}
code {{ background: #e2e8f0; padding: .1rem .3rem; border-radius: 3px; }}
</style>
</head>
<body>
<h1>Scalp — open15 long/short + 5m hammer/hanging-man / engulfing</h1>
<p>Stamp <code>{html_mod.escape(STAMP)}</code> · {html_mod.escape(sym_label)} ·
research only · <strong>not gold / not DailyRun</strong></p>
<p class="verdict">Verdict: {html_mod.escape(verdict)}</p>
<div class="note">
<strong>Coverage honesty.</strong> {coverage_html}<br/>
IS/OOS chronological split (2024 holdout) <strong>not applicable</strong> on this short Yahoo 1m window —
full-book metrics only. Click column headers to sort.
</div>
<div class="takeaway">
<strong>Institutional takeaway.</strong> {inst_html}
</div>

<h2>Session metrics (frozen arm)</h2>
<p>Canonical-style book metrics; sheet ${SHEET:,.0f}/trade. Ann ROR shown as — when hold &lt; 0.5d.</p>
<table class="sortable">
<thead><tr>{sortable_th("Metric", "text")}{sortable_th("Value", "num")}</tr></thead>
<tbody>
{''.join(mbody)}
</tbody>
</table>

{side_html}
{eo_html}
{crosstab_html}
{adv_html}
{setup_html}
{subkind_html}
{range_html}

<h2>Exit mix</h2>
<table class="sortable">
<thead><tr>{sortable_th("EXIT_TYPE", "text")}{sortable_th("N", "num")}{sortable_th("%", "num")}</tr></thead>
<tbody>{exit_rows}</tbody>
</table>

<h2>Per-symbol (top / bottom by Avg_PnL_%)</h2>
{mid_note}
<p>Click headers to sort.</p>
<table class="sortable">
<thead><tr>{shead}</tr></thead>
<tbody>
{''.join(sbody)}
</tbody>
</table>

<h2>Every trade</h2>
{trade_note}
<table class="sortable">
<thead><tr>{thead}</tr></thead>
<tbody>
{''.join(tbody)}
</tbody>
</table>

<h2>Per-session gate / skip log</h2>
{diag_note}
<table class="sortable">
<thead><tr>{dhead}</tr></thead>
<tbody>
{''.join(dbody)}
</tbody>
</table>

<p style="color:#64748b;font-size:.85rem">Generated {datetime.now(tz=ET).isoformat(timespec="seconds")} ·
tool <code>tools/scalp_open15_reversal_ab.py</code></p>
{SORT_JS}
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def reexit_trade(
    control_trade: dict[str, Any],
    day5: pd.DataFrame,
    *,
    time_stop: Optional[time],
    eod_flat: time,
) -> dict[str, Any]:
    """Same entry as control; re-resolve exit under a different time-stop policy."""
    entry_ts = str(control_trade["entry_ts"])
    entry_i = None
    for i in range(len(day5)):
        if str(day5.iloc[i]["ts"]) == entry_ts:
            entry_i = i
            break
    if entry_i is None:
        # fallback: match by time-of-day + session already filtered
        et = pd.Timestamp(entry_ts)
        for i in range(len(day5)):
            if pd.Timestamp(day5.iloc[i]["ts"]) == et:
                entry_i = i
                break
    if entry_i is None:
        out = dict(control_trade)
        out["time_stop_arm"] = "none_eod1555" if time_stop is None else "1130"
        out["exit_type"] = "REEXIT_MISS"
        return out

    side = str(control_trade["side"])
    entry = float(control_trade["entry"])
    stop = float(control_trade["stop"])
    target = float(control_trade["target"])
    exit_px, exit_ts, exit_type = resolve_exit(
        day5,
        entry_i,
        side=side,
        entry=entry,
        stop=stop,
        target=target,
        time_stop=time_stop,
        eod_flat=eod_flat,
    )
    if side == "long":
        pnl_pct = (exit_px / entry - 1.0) * 100.0
        risk = entry - stop
        r_mult = (exit_px - entry) / risk if risk > 0 else float("nan")
        shares = int(control_trade.get("shares") or 0)
        pnl_usd = shares * (exit_px - entry)
    else:
        pnl_pct = (entry - exit_px) / entry * 100.0
        risk = stop - entry
        r_mult = (entry - exit_px) / risk if risk > 0 else float("nan")
        shares = int(control_trade.get("shares") or 0)
        pnl_usd = shares * (entry - exit_px)

    out = dict(control_trade)
    out.update(
        {
            "exit_ts": exit_ts,
            "exit": round(exit_px, 6),
            "exit_type": exit_type,
            "pnl_pct": round(pnl_pct, 6),
            "r_mult": round(r_mult, 6) if math.isfinite(r_mult) else "",
            "pnl_usd": round(pnl_usd, 2),
            "win": 1 if pnl_pct > 0 else 0,
            "time_stop_arm": "1130" if time_stop is not None else "none_eod1555",
        }
    )
    return out


def _arm_row(label: str, m: dict[str, Any]) -> dict[str, Any]:
    return {
        "arm": label,
        "N": m.get("N"),
        "Win%": m.get("Win%"),
        "Avg_PnL_%": m.get("Avg_PnL_%"),
        "Profit_Factor": m.get("Profit_Factor"),
        "Total_PnL_$": m.get("Total_PnL_$"),
        "Max_DD_%": m.get("Max_DD_%"),
        "exit_mix": m.get("exit_mix") or {},
    }


def write_ext_compare_html(
    path: Path,
    *,
    control_m: dict[str, Any],
    candidate_m: dict[str, Any],
    control_trades: list[dict[str, Any]],
    candidate_trades: list[dict[str, Any]],
    symbols: list[str],
    coverage_note: str,
    verdicts: dict[str, str],
) -> None:
    ab_cols = [
        ("arm", "text"),
        ("N", "num"),
        ("Win%", "num"),
        ("Avg_PnL_%", "num"),
        ("Profit_Factor", "num"),
        ("Total_PnL_$", "money"),
        ("Max_DD_%", "num"),
        ("TIME/EOD_N", "num"),
        ("STOP_N", "num"),
        ("TARGET_N", "num"),
        ("verdict", "text"),
    ]
    ab_head = "".join(sortable_th(c, t) for c, t in ab_cols)
    ab_body = []
    for label, m, verd in (
        ("control_1130", control_m, verdicts.get("control", "HOLD")),
        ("candidate_no_timestop_eod1555", candidate_m, verdicts.get("candidate", "HOLD")),
    ):
        em = m.get("exit_mix") or {}
        cells = [
            f"<td>{html_mod.escape(label)}</td>",
            f"<td>{int(m.get('N') or 0)}</td>",
            f"<td>{_fmt_num(m.get('Win%'), 2)}</td>",
            f"<td>{_fmt_num(m.get('Avg_PnL_%'), 4)}</td>",
            f"<td>{_fmt_num(m.get('Profit_Factor'), 2)}</td>",
            f"<td>{format_money(m.get('Total_PnL_$')) if isinstance(m.get('Total_PnL_$'), (int, float)) else '—'}</td>",
            f"<td>{_fmt_num(m.get('Max_DD_%'), 2)}</td>",
            f"<td>{int(em.get('TIME', 0) + em.get('EOD_FLAT', 0))}</td>",
            f"<td>{int(em.get('STOP', 0))}</td>",
            f"<td>{int(em.get('TARGET', 0))}</td>",
            f"<td>{html_mod.escape(verd)}</td>",
        ]
        ab_body.append("<tr>" + "".join(cells) + "</tr>")

    # Delta row
    def _d(a, b):
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            return float("nan")
        if not math.isfinite(a) or not math.isfinite(b):
            return float("nan")
        return b - a

    d_wr = _d(control_m.get("Win%"), candidate_m.get("Win%"))
    d_avg = _d(control_m.get("Avg_PnL_%"), candidate_m.get("Avg_PnL_%"))
    d_pf = _d(control_m.get("Profit_Factor"), candidate_m.get("Profit_Factor"))
    d_pnl = _d(control_m.get("Total_PnL_$"), candidate_m.get("Total_PnL_$"))
    d_dd = _d(control_m.get("Max_DD_%"), candidate_m.get("Max_DD_%"))
    ab_body.append(
        "<tr class='total-row'>"
        f"<td>Δ candidate−control</td><td>0</td>"
        f"<td>{_fmt_num(d_wr, 2)}</td><td>{_fmt_num(d_avg, 4)}</td>"
        f"<td>{_fmt_num(d_pf, 2)}</td><td>{format_money(d_pnl) if math.isfinite(d_pnl) else '—'}</td>"
        f"<td>{_fmt_num(d_dd, 2)}</td><td>—</td><td>—</td><td>—</td>"
        f"<td>{html_mod.escape(verdicts.get('timestop_ab', 'HOLD'))}</td></tr>"
    )

    setup_html = _slice_table(
        "1) By setup_kind (control 11:30 arm)",
        "Includes bearish_hammer after freeze fix. Click headers to sort.",
        "setup_kind",
        control_m.get("by_setup") or {},
    )
    subkind_html = _slice_table(
        "1b) By setup_subkind (control)",
        "shooting_star vs hanging_man vs engulfing.",
        "setup_subkind",
        control_m.get("by_subkind") or {},
    )
    crosstab_html = _slice_table(
        "3) Crosstab entirely_out × side (control)",
        "Four cells + metrics.",
        "cell",
        control_m.get("by_crosstab") or {},
    )
    range_html = _slice_table(
        "4) Open15 range / ATR buckets (control)",
        "(open15 H−L) / ATR: 25–40%, 40–60%, 60–100%, >100%.",
        "range_atr_bucket",
        control_m.get("by_range_atr") or {},
    )
    # range × side
    range_side: dict[str, dict[str, Any]] = {}
    for t in control_trades:
        key = f"{t.get('range_atr_bucket')}×{t.get('side')}"
        range_side.setdefault(key, []).append(t)
    range_side_m = {k: metrics_from_trades(v, include_slices=False) for k, v in sorted(range_side.items())}
    range_side_html = _slice_table(
        "4b) Range/ATR × side (control)",
        "Descriptive.",
        "bucket×side",
        range_side_m,
    )

    cov = html_mod.escape(coverage_note).replace("\n", "<br/>")
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Scalp long/short extensions — {html_mod.escape(STAMP)}</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 1.5rem; color: #0f172a; background: #f8fafc; }}
h1,h2 {{ color: #0f172a; }}
.note {{ background: #fff7ed; border-left: 4px solid #f97316; padding: .75rem 1rem; margin: 1rem 0; }}
.verdict {{ font-size: 1.1rem; font-weight: 600; }}
table {{ border-collapse: collapse; width: 100%; background: #fff; margin: .75rem 0 1.5rem; font-size: .9rem; }}
th, td {{ border: 1px solid #cbd5e1; padding: .35rem .5rem; text-align: left; }}
th {{ background: #e2e8f0; }}
tr.total-row {{ font-weight: 600; background: #f1f5f9; }}
{SORT_CSS}
code {{ background: #e2e8f0; padding: .1rem .3rem; border-radius: 3px; }}
</style>
</head>
<body>
<h1>Scalp long/short extensions</h1>
<p>Stamp <code>{html_mod.escape(STAMP)}</code> · {len(symbols)} symbols · research only ·
<strong>not gold / not DailyRun</strong></p>
<p class="verdict">Time-stop A/B: {html_mod.escape(verdicts.get('timestop_ab', 'HOLD'))}</p>
<p class="verdict">Bearish hammer arm: {html_mod.escape(verdicts.get('hammer', 'HOLD'))}</p>
<div class="note">
<strong>Coverage.</strong> {cov}<br/>
Same entries for time-stop A/B (control finds setups; candidate re-exits only).
Click column headers to sort.
</div>

<h2>2) No time-stop A/B (same entries)</h2>
<p>Control = exit 11:30 bar open if still open. Candidate = TARGET+STOP only; safety EOD flat 15:55 ET.</p>
<table class="sortable">
<thead><tr>{ab_head}</tr></thead>
<tbody>{''.join(ab_body)}</tbody>
</table>

{setup_html}
{subkind_html}
{crosstab_html}
{range_html}
{range_side_html}

<p style="color:#64748b;font-size:.85rem">Generated {datetime.now(tz=ET).isoformat(timespec="seconds")} ·
tool <code>tools/scalp_open15_reversal_ab.py --ext</code></p>
{SORT_JS}
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def run_ext(
    symbols: list[str],
    *,
    stamp: str,
    coverage_note: str,
    sides: set[str],
    short_coverage: bool = True,
) -> dict[str, Any]:
    """One-pass: control 11:30 entries + candidate no-timestop re-exits; write ext stamp."""
    global STAMP, OUT_DIR
    STAMP = stamp
    OUT_DIR = DRIVE / "paul_experiments" / stamp
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    control_trades: list[dict[str, Any]] = []
    candidate_trades: list[dict[str, Any]] = []
    diags: list[dict[str, Any]] = []
    n_sym = len(symbols)

    for i, sym in enumerate(symbols, 1):
        if i == 1 or i % 50 == 0 or i == n_sym:
            print(f"[{i}/{n_sym}] {sym} … ctrl={len(control_trades)}", flush=True)
        daily = load_ohlc(sym)
        if daily is None:
            continue
        atr_map = prior_close_atr_map(daily)
        adv_map = prior_close_adv_map(daily)
        df1 = rth_filter(read_1m(sym, DEFAULT_1M_DIR))
        if df1.empty:
            continue
        df5 = resample_ohlcv(df1, "5min")
        df15 = resample_ohlcv(df1, "15min")
        for d in session_dates(df1):
            atr = atr_map.get(d)
            if atr is None or not math.isfinite(atr) or atr <= 0:
                diags.append(
                    {
                        "symbol": sym,
                        "session": str(d),
                        "skip_reason": "no_prior_atr",
                    }
                )
                continue
            adv = float(adv_map.get(d, float("nan")))
            trade, diag = simulate_day(
                sym,
                d,
                df5,
                df15,
                float(atr),
                sides=sides,
                adv_prior=adv,
                time_stop=TIME_STOP_T,
                eod_flat=EOD_FLAT_T,
            )
            diags.append(diag)
            if not trade:
                continue
            control_trades.append(trade)
            day5 = bars_on_day(df5, d)
            candidate_trades.append(
                reexit_trade(trade, day5, time_stop=None, eod_flat=EOD_FLAT_T)
            )

    control_m = metrics_from_trades(control_trades)
    candidate_m = metrics_from_trades(candidate_trades)

    # Verdicts per arm
    v_ctrl = pick_verdict(control_m, short_coverage=short_coverage)
    v_cand = pick_verdict(candidate_m, short_coverage=short_coverage)
    bh = (control_m.get("by_setup") or {}).get("bearish_hammer") or {}
    n_bh = int(bh.get("N") or 0)
    if n_bh < 20:
        v_hammer = "HOLD - bearish_hammer N too small (or still rare)"
    elif isinstance(bh.get("Avg_PnL_%"), float) and bh.get("Avg_PnL_%") < 0 and (bh.get("Win%") or 0) < 40:
        v_hammer = "DISMISS - bearish_hammer quality soft"
    elif isinstance(bh.get("Avg_PnL_%"), float) and bh.get("Avg_PnL_%") > 0 and (bh.get("Win%") or 0) >= 45:
        v_hammer = "HOLD - bearish_hammer ok on short window only (research)"
    else:
        v_hammer = "HOLD - bearish_hammer mixed (research only)"

    # Time-stop AB: KEEP only if candidate clearly better quality without worse DD blowup
    c_avg = control_m.get("Avg_PnL_%")
    k_avg = candidate_m.get("Avg_PnL_%")
    c_pf = control_m.get("Profit_Factor")
    k_pf = candidate_m.get("Profit_Factor")
    c_dd = control_m.get("Max_DD_%")
    k_dd = candidate_m.get("Max_DD_%")
    if (
        isinstance(c_avg, float)
        and isinstance(k_avg, float)
        and math.isfinite(c_avg)
        and math.isfinite(k_avg)
    ):
        better = (k_avg > c_avg + 0.01) and (
            not isinstance(k_pf, float)
            or not isinstance(c_pf, float)
            or not math.isfinite(k_pf)
            or not math.isfinite(c_pf)
            or k_pf >= c_pf - 0.05
        )
        dd_ok = (
            not isinstance(k_dd, float)
            or not isinstance(c_dd, float)
            or not math.isfinite(k_dd)
            or not math.isfinite(c_dd)
            or k_dd <= c_dd + 1.0  # Max DD % not much worse (more negative is worse if signed)
        )
        # Max_DD_% from overlay is typically negative or magnitude — treat higher abs as worse
        if isinstance(k_dd, float) and isinstance(c_dd, float) and math.isfinite(k_dd) and math.isfinite(c_dd):
            dd_ok = abs(k_dd) <= abs(c_dd) * 1.15 + 0.5
        if better and dd_ok:
            v_ab = "HOLD - no-timestop modestly better on short window (research; not KEEP)"
        elif isinstance(k_avg, float) and k_avg < c_avg - 0.02:
            v_ab = "DISMISS - removing 11:30 time stop worsens Avg PnL (research)"
        else:
            v_ab = "HOLD - no-timestop flat/mixed vs 11:30 (keep control; research only)"
    else:
        v_ab = "HOLD - insufficient for time-stop AB"

    # Write artifacts
    for name, rows in (
        ("trades_control.csv", control_trades),
        ("trades_candidate.csv", candidate_trades),
    ):
        p = OUT_DIR / name
        if rows:
            with p.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
        else:
            p.write_text("note\nno_trades\n", encoding="utf-8")

    # Also trades.csv = control for convenience
    if control_trades:
        with (OUT_DIR / "trades.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(control_trades[0].keys()))
            w.writeheader()
            w.writerows(control_trades)

    write_baseline(
        OUT_DIR / "BASELINE.md",
        symbols=symbols,
        coverage_note=coverage_note
        + "\n\n**Extension stamp** vs prior `scalp_longshort_20260822`: "
        "bearish_hammer = hanging-man OR shooting-star; "
        "time-stop A/B (same entries); crosstab; open15/ATR buckets.",
        n_trades=int(control_m.get("N") or 0),
        sides=sides,
    )
    write_ab_plan(OUT_DIR / "AB_PLAN.md")
    # Append extension notes
    ext_notes = OUT_DIR / "EXT_NOTES.md"
    ext_notes.write_text(
        f"""# EXT_NOTES — `{stamp}`

## Freeze deltas vs `scalp_longshort_20260822`

1. **Bearish hammer (shorts):** red candle with hanging-man **or** shooting-star wick geometry
   (wick ≥ {BEARISH_HAMMER_WICK_BODY:g}× body, opposite ≤ {BEARISH_HAMMER_OPP_WICK_BODY:g}× body;
   close in lower half). `setup_kind=bearish_hammer`. Prior hanging-man-only → **N=0**.
2. **Time-stop A/B:** control = 11:30 TIME exit; candidate = no arbitrary time stop,
   TARGET+STOP only, safety **EOD_FLAT at {EOD_FLAT_T.strftime('%H:%M')} ET**. **Same entries.**
3. **Crosstab:** entirely_out × side (4 cells).
4. **Range/ATR buckets:** 25–40%, 40–60%, 60–100%, >100% of prior-close ATR.

## Verdicts

| Arm | Verdict |
|-----|---------|
| Control book | {v_ctrl} |
| No-timestop candidate | {v_cand} |
| Time-stop A/B | {v_ab} |
| Bearish hammer slice | {v_hammer} |

Research only. Not gold. Not DailyRun.
""",
        encoding="utf-8",
    )

    html_path = OUT_DIR / "compare.html"
    write_ext_compare_html(
        html_path,
        control_m=control_m,
        candidate_m=candidate_m,
        control_trades=control_trades,
        candidate_trades=candidate_trades,
        symbols=symbols,
        coverage_note=coverage_note,
        verdicts={
            "control": v_ctrl,
            "candidate": v_cand,
            "timestop_ab": v_ab,
            "hammer": v_hammer,
        },
    )

    # metrics summary csv
    with (OUT_DIR / "metrics_ab.csv").open("w", newline="", encoding="utf-8") as f:
        rows = [
            _arm_row("control_1130", control_m),
            _arm_row("candidate_no_timestop_eod1555", candidate_m),
        ]
        # flatten exit_mix
        flat_rows = []
        for r in rows:
            fr = {k: v for k, v in r.items() if k != "exit_mix"}
            for ek, ev in (r.get("exit_mix") or {}).items():
                fr[f"exit_{ek}"] = ev
            flat_rows.append(fr)
        keys = sorted({k for r in flat_rows for k in r})
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(flat_rows)

    (OUT_DIR / "SUMMARY.md").write_text(
        f"""# SUMMARY — `{stamp}`

## Time-stop A/B
- Control 11:30: N={control_m.get('N')} WR%={_fmt_num(control_m.get('Win%'))} Avg={_fmt_num(control_m.get('Avg_PnL_%'), 4)} PF={_fmt_num(control_m.get('Profit_Factor'))} PnL$={format_money(control_m.get('Total_PnL_$') or 0)} MaxDD%={_fmt_num(control_m.get('Max_DD_%'))}
- Candidate no-timestop: N={candidate_m.get('N')} WR%={_fmt_num(candidate_m.get('Win%'))} Avg={_fmt_num(candidate_m.get('Avg_PnL_%'), 4)} PF={_fmt_num(candidate_m.get('Profit_Factor'))} PnL$={format_money(candidate_m.get('Total_PnL_$') or 0)} MaxDD%={_fmt_num(candidate_m.get('Max_DD_%'))}
- **{v_ab}**

## By setup_kind (control)
{chr(10).join(f"- {k}: N={v.get('N')} WR%={_fmt_num(v.get('Win%'))} Avg={_fmt_num(v.get('Avg_PnL_%'), 4)}" for k, v in sorted((control_m.get('by_setup') or {}).items()))}

## Crosstab (control)
{chr(10).join(f"- {k}: N={v.get('N')} WR%={_fmt_num(v.get('Win%'))} Avg={_fmt_num(v.get('Avg_PnL_%'), 4)}" for k, v in sorted((control_m.get('by_crosstab') or {}).items()))}

## Range/ATR (control)
{chr(10).join(f"- {k}: N={v.get('N')} WR%={_fmt_num(v.get('Win%'))} Avg={_fmt_num(v.get('Avg_PnL_%'), 4)}" for k, v in sorted((control_m.get('by_range_atr') or {}).items()))}

## Hammer verdict
{v_hammer}
""",
        encoding="utf-8",
    )
    (OUT_DIR / "symbols.txt").write_text("\n".join(symbols) + "\n", encoding="utf-8")

    return {
        "control_trades": control_trades,
        "candidate_trades": candidate_trades,
        "control_metrics": control_m,
        "candidate_metrics": candidate_m,
        "verdicts": {
            "control": v_ctrl,
            "candidate": v_cand,
            "timestop_ab": v_ab,
            "hammer": v_hammer,
        },
        "out_dir": OUT_DIR,
        "html": html_path,
    }


def pick_verdict(metrics: dict[str, Any], *, short_coverage: bool) -> str:
    n = int(metrics.get("N") or 0)
    if n < 20:
        return "HOLD - insufficient N (research only; not gold)"
    wr = metrics.get("Win%")
    avg = metrics.get("Avg_PnL_%")
    pf = metrics.get("Profit_Factor")
    if (
        isinstance(wr, float)
        and isinstance(avg, float)
        and math.isfinite(wr)
        and math.isfinite(avg)
    ):
        if avg < 0 and wr < 40:
            return "DISMISS - quality soft (research dead-end pending more data; not gold)"
        if wr >= 50 and avg > 0 and (not isinstance(pf, float) or not math.isfinite(pf) or pf >= 1.0):
            if short_coverage:
                return (
                    "HOLD - quality ok on short 1m window only "
                    "(needs longer coverage / walk-forward before KEEP; research only)"
                )
            return "LEAN KEEP - research candidate only (needs OOS / wider window)"
    if short_coverage:
        return "HOLD - short 1m coverage; research only (not gold)"
    return "HOLD - research only"


def institutional_takeaway(metrics: dict[str, Any], trades: list[dict[str, Any]]) -> str:
    by_adv = metrics.get("by_adv_bucket") or {}
    if not by_adv:
        return "No ADV$ bucket trades to summarize."
    ranked = sorted(
        by_adv.items(),
        key=lambda kv: (
            float(kv[1].get("Avg_PnL_%")) if isinstance(kv[1].get("Avg_PnL_%"), float) and math.isfinite(kv[1].get("Avg_PnL_%")) else -999,
            int(kv[1].get("N") or 0),
        ),
        reverse=True,
    )
    best_name, best = ranked[0]
    worst_name, worst = ranked[-1]
    eo = metrics.get("by_entirely_out") or {}
    eo_note = ""
    if "entirely_out" in eo and "partial" in eo:
        eo_note = (
            f" entirely_out N={eo['entirely_out'].get('N')} WR={_fmt_num(eo['entirely_out'].get('Win%'))}% "
            f"Avg={_fmt_num(eo['entirely_out'].get('Avg_PnL_%'), 4)}% vs partial "
            f"N={eo['partial'].get('N')} WR={_fmt_num(eo['partial'].get('Win%'))}% "
            f"Avg={_fmt_num(eo['partial'].get('Avg_PnL_%'), 4)}%."
        )
    return (
        f"Best ADV$ bucket by Avg PnL%: {best_name} "
        f"(N={best.get('N')}, WR={_fmt_num(best.get('Win%'))}%, "
        f"Avg={_fmt_num(best.get('Avg_PnL_%'), 4)}%). "
        f"Softest: {worst_name} "
        f"(N={worst.get('N')}, WR={_fmt_num(worst.get('Win%'))}%, "
        f"Avg={_fmt_num(worst.get('Avg_PnL_%'), 4)}%)."
        f"{eo_note}"
    )


def discover_1m_symbols(out_dir: Path = DEFAULT_1M_DIR) -> list[str]:
    syms = sorted({p.stem.upper() for p in Path(out_dir).glob("*.parquet") if p.is_file()})
    return syms


def run(
    symbols: list[str],
    *,
    stamp: str,
    coverage_note: str,
    sides: set[str],
    short_coverage: bool = True,
) -> dict[str, Any]:
    global STAMP, OUT_DIR
    STAMP = stamp
    OUT_DIR = DRIVE / "paul_experiments" / stamp
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    trades: list[dict[str, Any]] = []
    diags: list[dict[str, Any]] = []
    n_sym = len(symbols)

    for i, sym in enumerate(symbols, 1):
        if i == 1 or i % 50 == 0 or i == n_sym:
            print(f"[{i}/{n_sym}] {sym} … trades={len(trades)}", flush=True)
        daily = load_ohlc(sym)
        if daily is None:
            print(f"[warn] no daily OHLC for {sym}", flush=True)
            continue
        atr_map = prior_close_atr_map(daily)
        adv_map = prior_close_adv_map(daily)
        df1 = rth_filter(read_1m(sym, DEFAULT_1M_DIR))
        if df1.empty:
            print(f"[warn] no 1m for {sym}", flush=True)
            continue
        df5 = resample_ohlcv(df1, "5min")
        df15 = resample_ohlcv(df1, "15min")
        for d in session_dates(df1):
            atr = atr_map.get(d)
            if atr is None or not math.isfinite(atr) or atr <= 0:
                diags.append(
                    {
                        "symbol": sym,
                        "session": str(d),
                        "gate": "",
                        "skip_reason": "no_prior_atr",
                        "atr_prior": "",
                        "side": "",
                    }
                )
                continue
            adv = float(adv_map.get(d, float("nan")))
            trade, diag = simulate_day(
                sym, d, df5, df15, float(atr), sides=sides, adv_prior=adv
            )
            diags.append(diag)
            if trade:
                trades.append(trade)

    metrics = metrics_from_trades(trades)
    verdict = pick_verdict(metrics, short_coverage=short_coverage)
    inst = institutional_takeaway(metrics, trades)

    trades_path = OUT_DIR / "trades.csv"
    metrics_path = OUT_DIR / "metrics.csv"
    diags_path = OUT_DIR / "session_diag.csv"
    sym_path = OUT_DIR / "per_symbol.csv"
    if trades:
        with trades_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(trades[0].keys()))
            w.writeheader()
            w.writerows(trades)
    else:
        trades_path.write_text("symbol,session,note\n,,,no_trades\n", encoding="utf-8")

    sym_stats = per_symbol_stats(trades)
    if sym_stats:
        with sym_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(sym_stats[0].keys()))
            w.writeheader()
            w.writerows(sym_stats)

    with metrics_path.open("w", newline="", encoding="utf-8") as f:
        flat = {
            k: v
            for k, v in metrics.items()
            if k
            not in (
                "exit_mix",
                "by_setup",
                "by_side",
                "by_entirely_out",
                "by_adv_bucket",
                "by_crosstab",
                "by_range_atr",
                "by_subkind",
                "sessions",
            )
        }
        for k, v in (metrics.get("exit_mix") or {}).items():
            flat[f"exit_{k}"] = v
        for kind, sm in (metrics.get("by_setup") or {}).items():
            flat[f"setup_{kind}_N"] = sm.get("N")
            flat[f"setup_{kind}_Win%"] = sm.get("Win%")
            flat[f"setup_{kind}_Avg_PnL_%"] = sm.get("Avg_PnL_%")
            flat[f"setup_{kind}_PF"] = sm.get("Profit_Factor")
        for side, sm in (metrics.get("by_side") or {}).items():
            flat[f"side_{side}_N"] = sm.get("N")
            flat[f"side_{side}_Win%"] = sm.get("Win%")
            flat[f"side_{side}_Avg_PnL_%"] = sm.get("Avg_PnL_%")
            flat[f"side_{side}_PF"] = sm.get("Profit_Factor")
        for eo, sm in (metrics.get("by_entirely_out") or {}).items():
            flat[f"eo_{eo}_N"] = sm.get("N")
            flat[f"eo_{eo}_Win%"] = sm.get("Win%")
            flat[f"eo_{eo}_Avg_PnL_%"] = sm.get("Avg_PnL_%")
        for b, sm in (metrics.get("by_adv_bucket") or {}).items():
            flat[f"adv_{b}_N"] = sm.get("N")
            flat[f"adv_{b}_Win%"] = sm.get("Win%")
            flat[f"adv_{b}_Avg_PnL_%"] = sm.get("Avg_PnL_%")
        flat["verdict"] = verdict
        flat["n_symbols"] = len(symbols)
        flat["sides"] = "+".join(sorted(sides))
        flat["institutional_takeaway"] = inst
        w = csv.DictWriter(f, fieldnames=list(flat.keys()))
        w.writeheader()
        w.writerow(flat)

    if diags:
        keys = sorted({k for d in diags for k in d.keys()})
        with diags_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            w.writerows(diags)

    write_baseline(
        OUT_DIR / "BASELINE.md",
        symbols=symbols,
        coverage_note=coverage_note,
        n_trades=int(metrics.get("N") or 0),
        sides=sides,
    )
    write_ab_plan(OUT_DIR / "AB_PLAN.md")
    html_path = OUT_DIR / "compare.html"
    write_compare_html(
        html_path,
        trades,
        diags,
        metrics,
        symbols,
        verdict,
        coverage_note=coverage_note,
        institutional_takeaway=inst,
    )

    (OUT_DIR / "symbols.txt").write_text("\n".join(symbols) + "\n", encoding="utf-8")
    (OUT_DIR / "SUMMARY.md").write_text(
        f"""# SUMMARY — `{STAMP}`

**Verdict:** {verdict}

## Book
- N={metrics.get('N')} WR%={_fmt_num(metrics.get('Win%'))} AvgPnL%={_fmt_num(metrics.get('Avg_PnL_%'), 4)} PF={_fmt_num(metrics.get('Profit_Factor'))}

## By side
{chr(10).join(f"- {k}: N={v.get('N')} WR%={_fmt_num(v.get('Win%'))} AvgPnL%={_fmt_num(v.get('Avg_PnL_%'), 4)}" for k, v in sorted((metrics.get('by_side') or {}).items()))}

## entirely_out
{chr(10).join(f"- {k}: N={v.get('N')} WR%={_fmt_num(v.get('Win%'))} AvgPnL%={_fmt_num(v.get('Avg_PnL_%'), 4)}" for k, v in sorted((metrics.get('by_entirely_out') or {}).items()))}

## Institutional
{inst}
""",
        encoding="utf-8",
    )

    return {
        "trades": trades,
        "diags": diags,
        "metrics": metrics,
        "verdict": verdict,
        "out_dir": OUT_DIR,
        "html": html_path,
        "institutional_takeaway": inst,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Scalp open15/5m long/short reversal research AB")
    ap.add_argument("-s", "--symbols", default="", help="Comma-separated symbols")
    ap.add_argument(
        "--all",
        action="store_true",
        help="Auto-discover all symbols with 1m parquet under data/intraday/1m/",
    )
    ap.add_argument(
        "--sides",
        default="long",
        help="Comma-separated sides: long, short, or both (default long)",
    )
    ap.add_argument(
        "--stamp",
        default=DEFAULT_STAMP,
        help=f"Stamp folder name under drive/paul_experiments/ (default {DEFAULT_STAMP})",
    )
    ap.add_argument(
        "--ext",
        action="store_true",
        help="Extension stamp: bearish_hammer fix + no-timestop A/B + crosstab + range/ATR",
    )
    args = ap.parse_args()

    raw_sides = args.sides.strip().lower().replace(";", ",")
    if raw_sides in ("both", "longshort", "long+short", "all"):
        sides = {"long", "short"}
    else:
        sides = {p.strip() for p in raw_sides.split(",") if p.strip()}
        if not sides or not sides.issubset({"long", "short"}):
            print("Invalid --sides; use long, short, or both", file=sys.stderr)
            return 2

    if args.all:
        symbols = discover_1m_symbols()
    elif args.symbols.strip():
        symbols = [p.strip().upper() for p in args.symbols.replace(";", ",").split(",") if p.strip()]
    else:
        symbols = ["SPY", "AAPL"]

    if not symbols:
        print("No symbols", file=sys.stderr)
        return 2

    coverage_note = (
        "1m store (DuckDB scan): files under `data/intraday/1m/`; "
        "global bar span roughly **2026-07-23 … 2026-08-21** (symbol-dependent; "
        "many names only ~Aug 17–21). Yahoo 1m retention — short window. "
        "Incomplete sessions may yield `INCOMPLETE_EOD`."
    )

    if args.ext:
        stamp = args.stamp if args.stamp != DEFAULT_STAMP else "scalp_longshort_ext_20260822"
        if args.sides == "long":
            sides = {"long", "short"}
        result = run_ext(
            symbols,
            stamp=stamp,
            coverage_note=coverage_note,
            sides=sides,
            short_coverage=True,
        )
        cm = result["control_metrics"]
        km = result["candidate_metrics"]
        print(f"OUT={result['out_dir']}", flush=True)
        print(
            f"CTRL N={cm['N']} WR%={_fmt_num(cm['Win%'])} Avg={_fmt_num(cm['Avg_PnL_%'], 4)} "
            f"PF={_fmt_num(cm['Profit_Factor'])} PnL$={format_money(cm['Total_PnL_$']) if cm['N'] else '$0'} "
            f"MaxDD%={_fmt_num(cm['Max_DD_%'])}",
            flush=True,
        )
        print(
            f"CAND N={km['N']} WR%={_fmt_num(km['Win%'])} Avg={_fmt_num(km['Avg_PnL_%'], 4)} "
            f"PF={_fmt_num(km['Profit_Factor'])} PnL$={format_money(km['Total_PnL_$']) if km['N'] else '$0'} "
            f"MaxDD%={_fmt_num(km['Max_DD_%'])}",
            flush=True,
        )
        for kind, sm in sorted((cm.get("by_setup") or {}).items()):
            print(
                f"  setup={kind} N={sm['N']} WR%={_fmt_num(sm['Win%'])} "
                f"Avg={_fmt_num(sm['Avg_PnL_%'], 4)}",
                flush=True,
            )
        for k, v in sorted(result["verdicts"].items()):
            print(f"Verdict[{k}]: {v}", flush=True)
        print(f"HTML={result['html']}", flush=True)
        return 0

    result = run(
        symbols,
        stamp=args.stamp,
        coverage_note=coverage_note,
        sides=sides,
        short_coverage=True,
    )
    m = result["metrics"]
    print(f"OUT={result['out_dir']}", flush=True)
    print(
        f"N={m['N']} Wins={m['Wins']} Losses={m['Losses']} "
        f"WR%={_fmt_num(m['Win%'])} AvgPnL%={_fmt_num(m['Avg_PnL_%'])} "
        f"PF={_fmt_num(m['Profit_Factor'])} MaxDD%={_fmt_num(m['Max_DD_%'])} "
        f"PnL$={format_money(m['Total_PnL_$']) if m['N'] else '$0.00'}",
        flush=True,
    )
    for side, sm in sorted((m.get("by_side") or {}).items()):
        print(
            f"  side={side} N={sm['N']} WR%={_fmt_num(sm['Win%'])} "
            f"AvgPnL%={_fmt_num(sm['Avg_PnL_%'])} PF={_fmt_num(sm['Profit_Factor'])}",
            flush=True,
        )
    for eo, sm in sorted((m.get("by_entirely_out") or {}).items()):
        print(
            f"  eo={eo} N={sm['N']} WR%={_fmt_num(sm['Win%'])} "
            f"AvgPnL%={_fmt_num(sm['Avg_PnL_%'])}",
            flush=True,
        )
    for kind, sm in sorted((m.get("by_setup") or {}).items()):
        print(
            f"  setup={kind} N={sm['N']} WR%={_fmt_num(sm['Win%'])} "
            f"AvgPnL%={_fmt_num(sm['Avg_PnL_%'])} PF={_fmt_num(sm['Profit_Factor'])}",
            flush=True,
        )
    print(f"Institutional: {result['institutional_takeaway']}", flush=True)
    print(f"Verdict: {result['verdict']}", flush=True)
    print(f"HTML={result['html']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
