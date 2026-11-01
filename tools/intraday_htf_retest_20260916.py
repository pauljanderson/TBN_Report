#!/usr/bin/env python3
"""HTF fractal pivot break + LTF retest on stored 1m bars (research).

Draw confirmed swing highs on 30m / 2h / 4h (resampled from 1m). Buy the first
1m or 2m retest of that broken high. Compare initial-stop vs trail / breakeven.

Research only. Not gold. Not DailyRun.

Usage:
  python tools/intraday_htf_retest_20260916.py
  python tools/intraday_htf_retest_20260916.py -s AAPL,MSFT,NVDA
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import math
import sys
from datetime import date, time
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
    overlay_ann_ror_max_dd,
)
from intraday_1m import DEFAULT_1M_DIR, ET, read_1m  # noqa: E402

DRIVE = ROOT / "drive"
PAULTWENTY_CSV = DRIVE / "universes" / "PaulTwenty_universe.csv"
DEFAULT_STAMP = "intraday_htf_retest_20260916"
SYSTEM = "intraday_htf_retest"

# --- Freeze (see BASELINE.md) ---
SESSION_OPEN = time(9, 30)
SESSION_CLOSE = time(16, 0)
ENTRY_CUTOFF = time(15, 45)
TIME_STOP_T = time(15, 55)
SHEET = 45_000.0
INIT_ACCT = DEFAULT_INITIAL_ACCOUNT
COSTS_BPS = 0.0
ATR_N = 14
# Shop fractal: same rule as tools/trendline_slopes_paultwenty.fractal_pivots
PIVOT_K = {"30m": 3, "2h": 2, "4h": 2}
LTF_SWING_K = {"1m": 3, "2m": 2}
HTF_MINUTES = {"30m": 30, "2h": 120, "4h": 240}
LTF_MINUTES = {"1m": 1, "2m": 2}
RETEST_HTF_BARS = {"30m": 8, "2h": 4, "4h": 3}
RETEST_ATR_MULT = 0.15  # LTF bar must intersect level ± 0.15 × HTF ATR
INIT_STOP_ATR_MULT = 0.50  # control: stop = HTF level − 0.50 × LTF ATR
SWING_STOP_PAD_ATR = 0.10
CHANDELIER_N = 3.0
MIN_STOP_PCT = 0.0005  # skip if R/entry < 5 bps
SHORT_TAPE_OOS = date(2026, 9, 2)  # not the shop 2024 cut — tape is ~2 months
HTF_LIST = ("30m", "2h", "4h")
LTF_LIST = ("1m", "2m")
CONTROL_ARM = "control_init_only"
STOP_ARMS = (
    CONTROL_ARM,  # initial stop only, no trail
    "init_retest_swing",  # initial = retest/LTF swing low (one knob: initial location)
    "trail_ltf_swing",  # control initial + trail to confirmed LTF swing low
    "trail_chandelier_3",  # control initial + chandelier 3× LTF ATR
    "be_after_1R",  # control initial + move to entry after +1R close
)
EXTRA_UNIVERSE = ("UNH",)  # Paul asked for UNH in the mega-cap list

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

ORIGINAL_REQUEST = (
    'can you run some tests running using our 1m data? let\'s draw some pivots '
    'using 4hr, 2hr, and 30m candle, and then some buys based on a break and retest '
    'of those longer-term candles with a 1m and 2m candle? what kind of returns will '
    'we get? how can we set our stops and stop losses as the stock price moves on '
    'the 1-2m candles?'
)

PLAIN_ENGLISH = (
    "Use the 1-minute tape. Mark swing highs/lows on 4-hour, 2-hour, and 30-minute "
    "bars. Buy when price breaks that level and comes back to retest it, timed on a "
    "1-minute or 2-minute bar. Report what the book would have made, and how a stop "
    "can sit and then trail as those short bars print."
)


def sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def load_paultwenty() -> list[str]:
    if not PAULTWENTY_CSV.exists():
        return []
    out: list[str] = []
    for line in PAULTWENTY_CSV.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        out.append(s.upper())
    return out


def fractal_pivots(high: np.ndarray, low: np.ndarray, k: int) -> list[tuple[str, int]]:
    """Shop fractal: high/low extreme vs ±k neighbors (trendline_slopes_paultwenty)."""
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


def wilder_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int = ATR_N) -> np.ndarray:
    nbar = len(close)
    atr = np.full(nbar, np.nan, dtype=float)
    if nbar == 0:
        return atr
    tr = np.empty(nbar, dtype=float)
    tr[0] = float(high[0] - low[0]) if np.isfinite(high[0]) and np.isfinite(low[0]) else np.nan
    for i in range(1, nbar):
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i - 1])
        lc = abs(low[i] - close[i - 1])
        tr[i] = max(hl, hc, lc)
    if nbar < n:
        return atr
    atr[n - 1] = float(np.nanmean(tr[:n]))
    for i in range(n, nbar):
        prev = atr[i - 1]
        if not np.isfinite(prev):
            atr[i] = float(np.nanmean(tr[i - n + 1 : i + 1]))
        else:
            atr[i] = (prev * (n - 1) + tr[i]) / n
    return atr


def rth_filter(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume", "symbol"])
    t = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(ET)
    tod = t.dt.time
    mask = (tod >= SESSION_OPEN) & (tod < SESSION_CLOSE)
    out = df.loc[mask].copy()
    out["ts"] = t.loc[mask]
    return out.sort_values("ts").drop_duplicates(subset=["ts"], keep="last").reset_index(drop=True)


def _tod(ts: Any) -> time:
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize(ET)
    else:
        t = t.tz_convert(ET)
    return t.time().replace(tzinfo=None)


def resample_from_rth_open(df: pd.DataFrame, bar_minutes: int) -> pd.DataFrame:
    """Left-labeled RTH bars anchored at 09:30 ET (shop left-label idea, session-aligned)."""
    if df is None or df.empty:
        return pd.DataFrame(columns=["ts", "end_ts", "open", "high", "low", "close", "volume"])
    work = df.copy()
    ts = pd.to_datetime(work["ts"], utc=True).dt.tz_convert(ET)
    open_m = 9 * 60 + 30
    mins = ts.dt.hour * 60 + ts.dt.minute
    bucket = ((mins - open_m) // int(bar_minutes)).clip(lower=0)
    day = ts.dt.normalize()
    work = work.assign(
        _day=day,
        _bucket=bucket.astype(int),
        ts=ts,
    )
    rows: list[dict[str, Any]] = []
    for (d0, b0), g in work.groupby(["_day", "_bucket"], sort=True):
        g = g.sort_values("ts")
        start = pd.Timestamp(d0) + pd.Timedelta(minutes=int(open_m + int(b0) * bar_minutes))
        if start.tzinfo is None:
            start = start.tz_localize(ET)
        end = start + pd.Timedelta(minutes=int(bar_minutes))
        sess_end = pd.Timestamp(d0) + pd.Timedelta(hours=16)
        if sess_end.tzinfo is None:
            sess_end = sess_end.tz_localize(ET)
        if end > sess_end:
            end = sess_end
        rows.append(
            {
                "ts": start,
                "end_ts": end,
                "open": float(g["open"].iloc[0]),
                "high": float(g["high"].max()),
                "low": float(g["low"].min()),
                "close": float(g["close"].iloc[-1]),
                "volume": float(g["volume"].sum()) if "volume" in g.columns else 0.0,
            }
        )
    return pd.DataFrame(rows)


def _as_arrays(df: pd.DataFrame) -> dict[str, Any]:
    ts = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(ET)
    end = pd.to_datetime(df["end_ts"], utc=True).dt.tz_convert(ET) if "end_ts" in df.columns else None
    return {
        "ts": ts.to_numpy(),
        "end": end.to_numpy() if end is not None else None,
        "o": df["open"].to_numpy(dtype=float),
        "h": df["high"].to_numpy(dtype=float),
        "l": df["low"].to_numpy(dtype=float),
        "c": df["close"].to_numpy(dtype=float),
    }


def find_htf_breaks(htf: pd.DataFrame, htf_name: str) -> list[dict[str, Any]]:
    """Confirmed HTF swing-high breaks (close above), look-ahead safe at bar completion."""
    if htf is None or len(htf) < 2 * PIVOT_K[htf_name] + 1:
        return []
    k = PIVOT_K[htf_name]
    win = RETEST_HTF_BARS[htf_name]
    a = _as_arrays(htf)
    atr = wilder_atr(a["h"], a["l"], a["c"])
    raw = fractal_pivots(a["h"], a["l"], k=k)
    highs = [(i, i + k, float(a["h"][i])) for kind, i in raw if kind == "H" and i + k < len(a["c"])]
    highs.sort(key=lambda x: x[0])
    breaks: list[dict[str, Any]] = []
    hi_ptr = 0
    last: Optional[tuple[int, int, float]] = None  # pivot_i, conf_i, price
    consumed: set[int] = set()
    n = len(a["c"])
    for j in range(n):
        while hi_ptr < len(highs) and highs[hi_ptr][1] <= j:
            last = highs[hi_ptr]
            hi_ptr += 1
        if last is None:
            continue
        piv_i, conf_i, price = last
        if piv_i in consumed or j <= conf_i:
            continue
        if not np.isfinite(a["c"][j]) or a["c"][j] <= price:
            continue
        atr_j = float(atr[j]) if j < len(atr) and np.isfinite(atr[j]) else float("nan")
        if not np.isfinite(atr_j) or atr_j <= 0:
            # fallback: 0.1% of price so the band still exists
            atr_j = price * 0.01
        inv_j = None
        end_j = min(n - 1, j + win)
        for k2 in range(j + 1, end_j + 1):
            if a["c"][k2] < price:
                inv_j = k2
                break
        window_end = a["end"][inv_j] if inv_j is not None else a["end"][end_j]
        breaks.append(
            {
                "level": price,
                "pivot_i": piv_i,
                "conf_i": conf_i,
                "break_i": j,
                "break_ts": a["ts"][j],
                "break_end_ts": a["end"][j],
                "window_end_ts": window_end,
                "htf_atr": atr_j,
                "invalidate": inv_j is not None,
            }
        )
        consumed.add(piv_i)
        last = None
    return breaks


def first_retest_idx(
    ltf: dict[str, Any],
    *,
    start_ts: Any,
    end_ts: Any,
    level: float,
    band: float,
) -> Optional[int]:
    ts = ltf["ts"]
    lo = ltf["l"]
    hi = ltf["h"]
    start = pd.Timestamp(start_ts)
    end = pd.Timestamp(end_ts)
    lo_b = level - band
    hi_b = level + band
    n = len(ts)
    for i in range(n):
        t = pd.Timestamp(ts[i])
        if t.tzinfo is None:
            t = t.tz_localize(ET)
        if t < start:
            continue
        if t >= end:
            break
        if lo[i] <= hi_b and hi[i] >= lo_b:
            return i
    return None


def confirmed_swing_lows(low: np.ndarray, k: int) -> list[tuple[int, float, int]]:
    """(pivot_i, price, conf_i)."""
    raw = fractal_pivots(np.full_like(low, -np.inf), low, k=k)
    out: list[tuple[int, float, int]] = []
    n = len(low)
    for kind, i in raw:
        if kind != "L":
            continue
        conf = i + k
        if conf >= n:
            continue
        out.append((i, float(low[i]), conf))
    return out


def last_swing_low_before(swings: list[tuple[int, float, int]], before_i: int) -> Optional[float]:
    best = None
    best_i = -1
    for i, px, conf in swings:
        if conf < before_i and i > best_i:
            best = px
            best_i = i
    return best


def simulate_trade(
    ltf: dict[str, Any],
    ltf_atr: np.ndarray,
    swings: list[tuple[int, float, int]],
    *,
    entry_i: int,
    entry_px: float,
    level: float,
    retest_low: float,
    arm: str,
    htf_fail_ts: Optional[Any],
) -> Optional[dict[str, Any]]:
    n = len(ltf["c"])
    if entry_i < 0 or entry_i >= n:
        return None
    atr_e = float(ltf_atr[entry_i]) if entry_i < len(ltf_atr) and np.isfinite(ltf_atr[entry_i]) else float("nan")
    if not np.isfinite(atr_e) or atr_e <= 0:
        atr_e = entry_px * 0.001

    if arm == "init_retest_swing":
        swing = last_swing_low_before(swings, entry_i)
        base = min(retest_low, swing) if swing is not None else retest_low
        stop0 = base - SWING_STOP_PAD_ATR * atr_e
    else:
        stop0 = level - INIT_STOP_ATR_MULT * atr_e
    if stop0 >= entry_px:
        stop0 = entry_px - INIT_STOP_ATR_MULT * atr_e
    if entry_px <= 0 or (entry_px - stop0) / entry_px < MIN_STOP_PCT:
        return None

    r_dist = entry_px - stop0
    stop = stop0
    run_high = float(ltf["h"][entry_i])
    be_armed = False
    trail_px = stop0

    fail_ts = pd.Timestamp(htf_fail_ts) if htf_fail_ts is not None else None
    if fail_ts is not None and fail_ts.tzinfo is None:
        fail_ts = fail_ts.tz_localize(ET)

    for j in range(entry_i, n):
        t = pd.Timestamp(ltf["ts"][j])
        if t.tzinfo is None:
            t = t.tz_localize(ET)
        tod = t.time().replace(tzinfo=None)

        # Trail / BE update uses information through bar j-1 (no same-bar ratchet).
        if j > entry_i:
            prev_h = float(ltf["h"][j - 1])
            prev_c = float(ltf["c"][j - 1])
            if np.isfinite(prev_h):
                run_high = max(run_high, prev_h)
            atr_j = float(ltf_atr[j - 1]) if np.isfinite(ltf_atr[j - 1]) else atr_e
            if arm == "trail_ltf_swing":
                for _i, px, conf in swings:
                    if conf == j - 1 and px > trail_px:
                        trail_px = px - SWING_STOP_PAD_ATR * atr_j
                stop = max(stop, trail_px)
            elif arm == "trail_chandelier_3":
                ch = run_high - CHANDELIER_N * atr_j
                stop = max(stop, ch)
            elif arm == "be_after_1R":
                if (not be_armed) and np.isfinite(prev_c) and prev_c >= entry_px + r_dist:
                    be_armed = True
                    stop = max(stop, entry_px)

        if tod >= TIME_STOP_T:
            exit_px = float(ltf["o"][j])
            return _fill(entry_i, j, entry_px, exit_px, stop0, stop, "TIME", ltf, r_dist)

        if fail_ts is not None and t >= fail_ts:
            exit_px = float(ltf["c"][j])
            return _fill(entry_i, j, entry_px, exit_px, stop0, stop, "HTF_FAIL", ltf, r_dist)

        lo = float(ltf["l"][j])
        if lo <= stop:
            return _fill(entry_i, j, entry_px, stop, stop0, stop, "STOP", ltf, r_dist)

    last = n - 1
    return _fill(entry_i, last, entry_px, float(ltf["c"][last]), stop0, stop, "EOD_FLAT", ltf, r_dist)


def _fill(
    entry_i: int,
    exit_i: int,
    entry_px: float,
    exit_px: float,
    stop0: float,
    stop_final: float,
    exit_type: str,
    ltf: dict[str, Any],
    r_dist: float,
) -> dict[str, Any]:
    pnl_pct = (exit_px / entry_px - 1.0) * 100.0
    r_mult = (exit_px - entry_px) / r_dist if r_dist > 0 else float("nan")
    et = pd.Timestamp(ltf["ts"][entry_i])
    xt = pd.Timestamp(ltf["ts"][exit_i])
    hold_min = max(0.0, (xt - et).total_seconds() / 60.0)
    shares = math.floor(SHEET / entry_px) if entry_px > 0 else 0
    pnl_usd = shares * (exit_px - entry_px)
    return {
        "entry_i": entry_i,
        "exit_i": exit_i,
        "entry_px": entry_px,
        "exit_px": exit_px,
        "stop0": stop0,
        "stop_final": stop_final,
        "exit_type": exit_type,
        "pnl_pct": pnl_pct,
        "r_mult": r_mult,
        "entry_ts": et,
        "exit_ts": xt,
        "hold_min": hold_min,
        "shares": shares,
        "pnl_usd": pnl_usd,
    }


def scan_symbol(sym: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    raw = read_1m(sym, DEFAULT_1M_DIR)
    df1 = rth_filter(raw)
    cov = {
        "symbol": sym,
        "n_1m": int(len(df1)),
        "min_ts": str(df1["ts"].min()) if not df1.empty else "",
        "max_ts": str(df1["ts"].max()) if not df1.empty else "",
        "n_sessions": int(pd.to_datetime(df1["ts"]).dt.date.nunique()) if not df1.empty else 0,
    }
    if df1.empty or len(df1) < 200:
        return [], cov

    frames: dict[str, pd.DataFrame] = {"1m": df1.copy()}
    frames["1m"]["end_ts"] = frames["1m"]["ts"] + pd.Timedelta(minutes=1)
    for name, mins in {**HTF_MINUTES, "2m": 2}.items():
        frames[name] = resample_from_rth_open(df1, mins)

    ltf_pack: dict[str, tuple[dict[str, Any], np.ndarray, list[tuple[int, float, int]]]] = {}
    for ltf_name in LTF_LIST:
        f = frames[ltf_name]
        if f.empty:
            continue
        arr = _as_arrays(f)
        atr = wilder_atr(arr["h"], arr["l"], arr["c"])
        swings = confirmed_swing_lows(arr["l"], LTF_SWING_K[ltf_name])
        ltf_pack[ltf_name] = (arr, atr, swings)

    trades: list[dict[str, Any]] = []
    for htf_name in HTF_LIST:
        htf = frames.get(htf_name)
        if htf is None or htf.empty:
            continue
        breaks = find_htf_breaks(htf, htf_name)
        for br in breaks:
            band = RETEST_ATR_MULT * float(br["htf_atr"])
            fail_ts = br["window_end_ts"] if br["invalidate"] else None
            for ltf_name, (arr, atr, swings) in ltf_pack.items():
                ri = first_retest_idx(
                    arr,
                    start_ts=br["break_end_ts"],
                    end_ts=br["window_end_ts"],
                    level=float(br["level"]),
                    band=band,
                )
                if ri is None or ri + 1 >= len(arr["c"]):
                    continue
                ei = ri + 1
                et = pd.Timestamp(arr["ts"][ei])
                if et.tzinfo is None:
                    et = et.tz_localize(ET)
                if _tod(et) < SESSION_OPEN or _tod(et) >= ENTRY_CUTOFF:
                    continue
                entry_px = float(arr["o"][ei])
                if not np.isfinite(entry_px) or entry_px <= 0:
                    continue
                retest_low = float(arr["l"][ri])
                # One event identity shared across stop arms (same entry).
                for arm in STOP_ARMS:
                    sim = simulate_trade(
                        arr,
                        atr,
                        swings,
                        entry_i=ei,
                        entry_px=entry_px,
                        level=float(br["level"]),
                        retest_low=retest_low,
                        arm=arm,
                        htf_fail_ts=fail_ts,
                    )
                    if sim is None:
                        continue
                    trades.append(
                        {
                            "symbol": sym,
                            "htf": htf_name,
                            "ltf": ltf_name,
                            "arm": arm,
                            "level": float(br["level"]),
                            "htf_atr": float(br["htf_atr"]),
                            "break_ts": str(pd.Timestamp(br["break_end_ts"])),
                            "retest_ts": str(pd.Timestamp(arr["ts"][ri])),
                            "entry_date": et.date().isoformat(),
                            "session": et.date().isoformat(),
                            "split": "OOS" if et.date() >= SHORT_TAPE_OOS else "IS",
                            **{k: sim[k] for k in sim if k not in {"entry_i", "exit_i"}},
                            "entry_ts": str(sim["entry_ts"]),
                            "exit_ts": str(sim["exit_ts"]),
                            "win": 1 if sim["pnl_pct"] > 0 else 0,
                        }
                    )
    cov["n_trades_all_arms"] = len(trades)
    return trades, cov


def _finite(xs: list[float]) -> list[float]:
    return [x for x in xs if x is not None and math.isfinite(x)]


def metrics_from_trades(trades: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(trades)
    empty = {
        "N": 0,
        "Wins": 0,
        "Losses": 0,
        "Win%": float("nan"),
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
        "Calmar": float("nan"),
        "Sharpe": float("nan"),
        "Avg_min_held": float("nan"),
        "Med_min_held": float("nan"),
        "stop_out_%": float("nan"),
        "n_symbols": 0,
        "exit_mix": {},
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
    wo = pnls.copy()
    if wins:
        wo.remove(max(pnls))
    ov_rows = []
    holds = []
    for t in trades:
        et = pd.Timestamp(t["entry_ts"])
        xt = pd.Timestamp(t["exit_ts"])
        hold_days = max(0.01, (xt - et).total_seconds() / 86400.0)
        holds.append(float(t.get("hold_min") or hold_days * 1440.0))
        ov_rows.append(
            {
                "pnl_d": float(t["pnl_usd"]),
                "pnl": float(t["pnl_pct"]),
                "days": hold_days,
                "closed": xt.date(),
                "opened": et.date(),
            }
        )
    ov = overlay_ann_ror_max_dd(ov_rows, cash=SHEET, initial_account=INIT_ACCT)
    avg_hold_d = float(np.mean([r["days"] for r in ov_rows]))
    ann = float("nan") if avg_hold_d < 0.5 else ov.get("ann_ror", float("nan"))
    calmar = ov.get("calmar", float("nan")) if math.isfinite(ann) else float("nan")
    exit_mix: dict[str, int] = {}
    for t in trades:
        exit_mix[str(t["exit_type"])] = exit_mix.get(str(t["exit_type"]), 0) + 1
    n_stop = exit_mix.get("STOP", 0)
    return {
        "N": n,
        "Wins": len(wins),
        "Losses": len(losses),
        "Win%": 100.0 * len(wins) / n,
        "Avg_PnL_%": float(np.mean(pnls)),
        "AVG_PNL_PCT_WO_MAX": float(np.mean(wo)) if wo else float("nan"),
        "Expectancy_%": float(np.mean(pnls)),
        "Expectancy_$": float(np.mean(usds)),
        "Avg_Win_%": float(np.mean(wins)) if wins else float("nan"),
        "Avg_Loss_%": float(np.mean(losses)) if losses else float("nan"),
        "WL_count_ratio": (len(wins) / len(losses)) if losses else float("nan"),
        "Profit_Factor": pf,
        "Ann_ROR_%": ann,
        "Max_DD_%": ov.get("max_dd", float("nan")),
        "Calmar": calmar,
        "Sharpe": ov.get("sharpe", float("nan")),
        "Avg_min_held": float(np.mean(holds)) if holds else float("nan"),
        "Med_min_held": float(np.median(holds)) if holds else float("nan"),
        "stop_out_%": 100.0 * n_stop / n,
        "n_symbols": len({t["symbol"] for t in trades}),
        "exit_mix": exit_mix,
    }


def fmt_num(v: Any, nd: int = 2) -> str:
    if v is None:
        return "—"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return str(v)
    if not math.isfinite(x):
        return "—"
    if abs(x) == float("inf"):
        return "inf"
    return f"{x:.{nd}f}"


def fmt_delta(cur: Any, base: Any, nd: int = 2) -> str:
    try:
        a = float(cur)
        b = float(base)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(a) or not math.isfinite(b):
        return "—"
    d = a - b
    return f"{d:+.{nd}f}"


def quality_score(m: dict[str, Any]) -> tuple[float, float, float]:
    """Sort key: Avg% , PF (capped), WR. Quality over count."""
    avg = m.get("Avg_PnL_%")
    pf = m.get("Profit_Factor")
    wr = m.get("Win%")
    a = float(avg) if avg is not None and math.isfinite(float(avg)) else -999.0
    p = float(pf) if pf is not None and math.isfinite(float(pf)) else 0.0
    p = min(p, 10.0)
    w = float(wr) if wr is not None and math.isfinite(float(wr)) else 0.0
    return (a, p, w)


def judge_vs_control(cand: dict[str, Any], ctrl: dict[str, Any], *, oos_soft: bool) -> str:
    if oos_soft:
        return "HOLD"
    if cand.get("N", 0) < 8 or ctrl.get("N", 0) < 8:
        return "HOLD"
    ca, _, _ = quality_score(cand)
    ba, _, _ = quality_score(ctrl)
    n_ratio = cand["N"] / max(1, ctrl["N"])
    if n_ratio < 0.4:
        return "HOLD"
    pf_c = cand.get("Profit_Factor")
    pf_b = ctrl.get("Profit_Factor")
    try:
        pf_ok = math.isfinite(float(pf_c)) and math.isfinite(float(pf_b)) and float(pf_c) >= float(pf_b) * 0.95
    except (TypeError, ValueError):
        pf_ok = False
    if ca > ba + 0.02 and pf_ok:
        # Do not LEAN KEEP a still-losing book (PF<1 and Avg%<=0) just because it lost less.
        if ca <= 0 and (not math.isfinite(float(pf_c or 0)) or float(pf_c) < 1.0):
            return "HOLD"
        return "LEAN KEEP"
    if ca < ba - 0.02:
        return "DISMISS"
    return "HOLD"


def write_baseline(
    path: Path,
    *,
    stamp: str,
    symbols: list[str],
    coverage_rows: list[dict[str, Any]],
    n_trades: int,
) -> None:
    cov_lines = [
        "| Symbol | 1m bars | Sessions | First | Last |",
        "|--------|--------:|---------:|-------|------|",
    ]
    for r in coverage_rows:
        cov_lines.append(
            f"| {r['symbol']} | {r['n_1m']} | {r['n_sessions']} | {r['min_ts']} | {r['max_ts']} |"
        )
    text = f"""# BASELINE — Intraday HTF break + LTF retest — `{stamp}`

**System:** `{SYSTEM}` (research only). **Not** DailyRun. **Not** gold.

## What you asked

> {ORIGINAL_REQUEST}

## In plain English

{PLAIN_ENGLISH}

High Time Frame (**HTF**) = the 30-minute / 2-hour / 4-hour candles we draw pivots on.
Low Time Frame (**LTF**) = the 1-minute / 2-minute candles we time the buy and the stop on.
Average True Range (**ATR**) = a typical-bar-range measure (Wilder 14) used for the retest band and stop distance.

## User mapping

Break of a **prior confirmed HTF swing high**, then first LTF **retest** of that line, long only.

## Freeze

| Knob | Value |
|------|--------|
| Universe | PaulTwenty ∩ stored 1m, plus UNH if present: {", ".join(symbols)} |
| Session | Regular trading hours 09:30–16:00 ET |
| 1m store | `data/intraday/1m/{{SYM}}.parquet` (Yahoo via shop helper; not ticks) |
| Resample | Session-anchored at 09:30 ET, left-labeled; 2m from 1m |
| Pivots | Shop fractal (`trendline_slopes_paultwenty.fractal_pivots`); confirmed after +k HTF bars |
| Fractal k | 30m **k=3**; 2h **k=2**; 4h **k=2** |
| Break | HTF **close** above the most recent confirmed HTF resistance (swing high) |
| Retest band | LTF bar range intersects level ± **{RETEST_ATR_MULT} × HTF ATR** |
| Retest window | {RETEST_HTF_BARS['30m']} × 30m / {RETEST_HTF_BARS['2h']} × 2h / {RETEST_HTF_BARS['4h']} × 4h after the break bar; cancel if HTF closes back below |
| Entry | **Next LTF bar open** after the first retest bar; no entry at/after {ENTRY_CUTOFF.strftime('%H:%M')} ET |
| Side | Long only |
| Frequency | First retest per HTF break; same entry reused across stop arms |
| Control stop | HTF level − **{INIT_STOP_ATR_MULT} × LTF ATR**; no trail |
| `init_retest_swing` | Stop = min(retest low, last confirmed LTF swing low) − {SWING_STOP_PAD_ATR} × LTF ATR; no trail |
| `trail_ltf_swing` | Control initial; ratchet up to confirmed LTF swing low − {SWING_STOP_PAD_ATR}×ATR (k={LTF_SWING_K['1m']} on 1m, k={LTF_SWING_K['2m']} on 2m). Updates after the confirmation bar closes. Never down. |
| `trail_chandelier_3` | Control initial; trail = prior-bar running high − **{CHANDELIER_N:g} × LTF ATR**. Never down. |
| `be_after_1R` | Control initial; after a **prior bar close ≥ entry + 1R**, stop = entry |
| Exit | STOP, HTF_FAIL (HTF close back below the level), TIME at {TIME_STOP_T.strftime('%H:%M')} ET open, or last bar EOD_FLAT |
| Costs | {COSTS_BPS:g} bps (research, no slippage) |
| Sheet / overlay | ${SHEET:,.0f} / trade floor-shares; Max DD on ${INIT_ACCT:,.0f} seed |
| Ann ROR | Shown only when avg hold ≥ 0.5 day (scalps usually —) |

## How stops move (numbers)

1. **Park it (control).** At the fill, measure LTF ATR. Put the stop at `broken_HTF_high − 0.50 × LTF_ATR`. Leave it there until TIME / HTF_FAIL / the stop prints.
2. **Ratchet on 1–2m swings.** Each time a new LTF swing low confirms (1m: 3 bars each side; 2m: 2 bars each side), raise the stop to that low minus `0.10 × LTF_ATR` if that is higher than the current stop.
3. **Chandelier.** After each completed LTF bar, `stop = max(initial, highest_high_since_entry − 3 × LTF_ATR)` using the prior bar’s high/ATR (no same-bar raise).
4. **Breakeven after +1R.** R = entry − initial stop. When a completed LTF bar closes at least +1R, the next bar’s stop is the entry price.

## Split

Canonical shop IS (`entry_date < 2024-01-01`) is **N/A** — Yahoo 1m here is Jul–Sep 2026 only.

Short-tape chronological split (labeled, not silent): **IS** = `entry_date < {SHORT_TAPE_OOS.isoformat()}`; **OOS** = `entry_date >= {SHORT_TAPE_OOS.isoformat()}`. OOS is report-only. If OOS softens vs IS → **HOLD**, do not retune.

## Coverage

{chr(10).join(cov_lines)}

Closed trades this stamp (all HTF × LTF × stop arms): **N={n_trades}**.

## Selection bias

Stop arms and HTF/LTF pairs are judged on the **same** short tape. That is in-sample selection even with an OOS row. Research candidate only.

## Promotion

Research candidate. **Not** gold. **Not** DailyRun.
"""
    path.write_text(text, encoding="utf-8")


def _metric_cells(m: dict[str, Any]) -> list[str]:
    return [
        str(int(m.get("N") or 0)),
        str(int(m.get("n_symbols") or 0)),
        fmt_num(m.get("Win%"), 1),
        fmt_num(m.get("Avg_PnL_%"), 3),
        fmt_num(m.get("AVG_PNL_PCT_WO_MAX"), 3),
        fmt_num(m.get("Expectancy_%"), 3),
        fmt_num(m.get("Expectancy_$"), 2),
        fmt_num(m.get("Avg_Win_%"), 3),
        fmt_num(m.get("Avg_Loss_%"), 3),
        fmt_num(m.get("Profit_Factor"), 2),
        fmt_num(m.get("Ann_ROR_%"), 1),
        fmt_num(m.get("Max_DD_%"), 2),
        fmt_num(m.get("Calmar"), 2),
        fmt_num(m.get("Sharpe"), 2),
        fmt_num(m.get("Avg_min_held"), 1),
        fmt_num(m.get("Med_min_held"), 1),
        fmt_num(m.get("stop_out_%"), 1),
    ]


METRIC_COLS = [
    ("N", "num"),
    ("n_symbols", "num"),
    ("Win%", "num"),
    ("Avg PnL %", "num"),
    ("Avg% w/o max", "num"),
    ("Expectancy %", "num"),
    ("Expectancy $", "num"),
    ("Avg win %", "num"),
    ("Avg loss %", "num"),
    ("PF", "num"),
    ("Ann ROR %", "num"),
    ("Max DD %", "num"),
    ("Calmar", "num"),
    ("Sharpe", "num"),
    ("Avg min held", "num"),
    ("Med min held", "num"),
    ("Stop-out %", "num"),
]


def write_html(
    path: Path,
    *,
    stamp: str,
    symbols: list[str],
    coverage_rows: list[dict[str, Any]],
    books: list[dict[str, Any]],
    sample_trades: list[dict[str, Any]],
    verdict_note: str,
    best_line: str,
    coverage_note: str,
) -> None:
    id_cols = [
        ("book", "text"),
        ("htf", "text"),
        ("ltf", "text"),
        ("arm", "text"),
        ("split", "text"),
        ("verdict", "text"),
    ]
    head = "".join(sortable_th(c, t) for c, t in id_cols + METRIC_COLS)
    extra = ("Δ Avg% vs ctrl", "num"), ("Δ PF vs ctrl", "num"), ("Δ WR vs ctrl", "num")
    head_ab = "".join(sortable_th(c, t) for c, t in id_cols + METRIC_COLS + list(extra))

    def row_html(b: dict[str, Any], *, deltas: bool = False) -> str:
        cells = [
            html_mod.escape(str(b.get("book", ""))),
            html_mod.escape(str(b.get("htf", ""))),
            html_mod.escape(str(b.get("ltf", ""))),
            html_mod.escape(str(b.get("arm", ""))),
            html_mod.escape(str(b.get("split", ""))),
            html_mod.escape(str(b.get("verdict", ""))),
        ]
        cells.extend(_metric_cells(b["m"]))
        if deltas:
            cells.extend(
                [
                    html_mod.escape(str(b.get("d_avg", "—"))),
                    html_mod.escape(str(b.get("d_pf", "—"))),
                    html_mod.escape(str(b.get("d_wr", "—"))),
                ]
            )
        return "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"

    tf_books = [b for b in books if b.get("table") == "tf_control"]
    stop_books = [b for b in books if b.get("table") == "stop_ab"]
    split_books = [b for b in books if b.get("table") == "split"]

    cov_head = "".join(
        sortable_th(c, t)
        for c, t in (
            ("symbol", "text"),
            ("1m bars", "num"),
            ("sessions", "num"),
            ("first", "date"),
            ("last", "date"),
        )
    )
    cov_rows = []
    for r in coverage_rows:
        cov_rows.append(
            "<tr>"
            f"<td>{html_mod.escape(r['symbol'])}</td>"
            f"<td>{r['n_1m']}</td><td>{r['n_sessions']}</td>"
            f"<td>{html_mod.escape(str(r['min_ts'])[:19])}</td>"
            f"<td>{html_mod.escape(str(r['max_ts'])[:19])}</td>"
            "</tr>"
        )

    ev_cols = [
        ("symbol", "text"),
        ("htf", "text"),
        ("ltf", "text"),
        ("arm", "text"),
        ("split", "text"),
        ("session", "date"),
        ("level", "num"),
        ("entry_px", "num"),
        ("exit_px", "num"),
        ("stop0", "num"),
        ("pnl_pct", "num"),
        ("r_mult", "num"),
        ("hold_min", "num"),
        ("exit_type", "text"),
    ]
    ehead = "".join(sortable_th(c, t) for c, t in ev_cols)
    erows = []
    for t in sample_trades[:400]:
        cells = []
        for c, typ in ev_cols:
            v = t.get(c, "")
            if typ == "num":
                cells.append(f"<td>{html_mod.escape(fmt_num(v if v != '' else None, 3))}</td>")
            else:
                cells.append(f"<td>{html_mod.escape(str(v))}</td>")
        erows.append("<tr>" + "".join(cells) + "</tr>")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>HTF break + LTF retest — {html_mod.escape(stamp)}</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:24px;color:#0f172a;background:#f8fafc;line-height:1.45}}
h1{{font-size:1.45rem;margin:0 0 8px}}
h2{{font-size:1.15rem;margin:28px 0 10px}}
.ask,.plain{{max-width:960px;padding:12px 14px;border-radius:8px;margin:12px 0}}
.ask{{background:#fff7ed;border:1px solid #fdba74}}
.plain{{background:#ecfeff;border:1px solid #67e8f9}}
.badge{{display:inline-block;background:#fef3c7;color:#92400e;padding:2px 8px;border-radius:4px;font-size:.85rem;font-weight:600}}
table.sortable{{border-collapse:collapse;width:100%;background:#fff;margin:8px 0 16px;font-size:.88rem}}
table.sortable th,table.sortable td{{border:1px solid #e2e8f0;padding:8px 10px;text-align:left}}
table.sortable th{{background:#f1f5f9}}
.note,.meta{{font-size:.92rem;color:#475569;max-width:980px}}
.stopbox{{max-width:960px;background:#fff;border:1px solid #cbd5e1;border-radius:8px;padding:12px 14px}}
{SORT_CSS}
</style>
</head>
<body>
<p class="badge">Research only · not gold · not DailyRun</p>
<h1>HTF pivot break + 1m/2m retest</h1>

<div class="ask">
<strong>What you asked</strong>
<blockquote>{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
</div>
<div class="plain">
<strong>In plain English</strong>
<p>{html_mod.escape(PLAIN_ENGLISH)}</p>
<p>High Time Frame (<strong>HTF</strong>) = 30-minute / 2-hour / 4-hour candles used to mark the swing high.
Low Time Frame (<strong>LTF</strong>) = 1-minute / 2-minute candles used to time the buy and walk the stop.
Average True Range (<strong>ATR</strong>) = typical bar range (Wilder 14) for the retest band and stop distance.</p>
</div>

<p class="meta">Stamp <code>{html_mod.escape(stamp)}</code> · {len(symbols)} names ·
{html_mod.escape(coverage_note)}<br/>
Sheet ${SHEET:,.0f}/trade · Max DD on ${INIT_ACCT:,.0f} overlay · Ann ROR blank when avg hold &lt; 0.5d.
Click column headers to sort. Total / sheet PnL $ omitted from tables (quality %, PF, DD).</p>

<h2>Bottom line</h2>
<p class="meta">{html_mod.escape(best_line)}</p>
<p class="meta">{html_mod.escape(verdict_note)}</p>

<h2>How stops move</h2>
<div class="stopbox">
<ol>
<li><strong>Park it (control).</strong> Stop = broken HTF high − <strong>0.50 × LTF ATR</strong> at entry. It does not move. Exit also on HTF close back below the line, or 15:55 ET.</li>
<li><strong>Ratchet on 1–2m swings.</strong> After a new LTF swing low confirms (1m fractal k=3; 2m k=2), raise the stop to that low − 0.10×ATR if higher. Never lower it.</li>
<li><strong>Chandelier.</strong> <code>stop = max(initial, highest high since entry − 3 × LTF ATR)</code>, using the <em>prior</em> bar so a spike cannot lift the stop on the same print.</li>
<li><strong>Breakeven after +1R.</strong> R = entry − initial stop. When a completed LTF bar closes ≥ entry+1R, the next bar’s stop is the entry.</li>
</ol>
<p class="note">Trail updates after the confirmation bar <em>closes</em> — no same-bar peek. Intrabar: if the low tags the stop, you are out at the stop (conservative vs stop+target same bar).</p>
</div>

<h2>Data coverage</h2>
<p class="note">Yahoo 1m store under <code>data/intraday/1m/</code>. Not ticks. Gaps happen. Canonical 2024 IS/OOS is N/A; short-tape cut is {SHORT_TAPE_OOS.isoformat()} (OOS report-only).</p>
<table class="sortable">
<thead><tr>{cov_head}</tr></thead>
<tbody>
{''.join(cov_rows)}
</tbody>
</table>

<h2>Timeframe grid — control stop only</h2>
<p class="note">Same initial-stop freeze on every HTF × LTF pair. Judge quality (Avg %, PF, WR), not trade count.</p>
<table class="sortable">
<thead><tr>{head}</tr></thead>
<tbody>
{''.join(row_html(b) for b in tf_books)}
</tbody>
</table>

<h2>Stop A/B (one knob vs control)</h2>
<p class="note">Each HTF × LTF keeps the same entries; only the stop rule changes. Δ vs that pair’s control. Full sample unless split column says IS/OOS.</p>
<table class="sortable">
<thead><tr>{head_ab}</tr></thead>
<tbody>
{''.join(row_html(b, deltas=True) for b in stop_books)}
</tbody>
</table>

<h2>Short-tape IS / OOS</h2>
<p class="note">IS = entry before {SHORT_TAPE_OOS.isoformat()}; OOS = on/after. If OOS Avg% or PF softens vs IS on the same arm → HOLD, do not retune OOS.</p>
<table class="sortable">
<thead><tr>{head}</tr></thead>
<tbody>
{''.join(row_html(b) for b in split_books)}
</tbody>
</table>

<h2>Trades (first {min(400, len(sample_trades))} of {len(sample_trades)})</h2>
<table class="sortable">
<thead><tr>{ehead}</tr></thead>
<tbody>
{''.join(erows)}
</tbody>
</table>

<p class="note">Full book: <code>trades.csv</code>. Freeze: <code>BASELINE.md</code>. Research candidate only.</p>
{SORT_JS}
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def write_trades_csv(path: Path, trades: list[dict[str, Any]]) -> None:
    if not trades:
        path.write_text("", encoding="utf-8")
        return
    keys = list(trades[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for t in trades:
            row = dict(t)
            for k, v in row.items():
                if isinstance(v, float):
                    row[k] = f"{v:.6f}" if math.isfinite(v) else ""
            w.writerow(row)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stamp", default=DEFAULT_STAMP)
    ap.add_argument("-s", "--symbols", default="", help="Comma override")
    args = ap.parse_args()
    stamp = args.stamp
    out_dir = DRIVE / "paul_experiments" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.symbols.strip():
        symbols = [x.strip().upper() for x in args.symbols.split(",") if x.strip()]
    else:
        symbols = load_paultwenty()
        for extra in EXTRA_UNIVERSE:
            if extra not in symbols:
                symbols.append(extra)

    usable: list[str] = []
    for s in symbols:
        if (DEFAULT_1M_DIR / f"{s}.parquet").is_file():
            usable.append(s)
    symbols = usable
    print(f"stamp={stamp} symbols={len(symbols)} {symbols}", flush=True)

    all_trades: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    for i, sym in enumerate(symbols, 1):
        print(f"[{i}/{len(symbols)}] {sym} …", flush=True)
        tr, cov = scan_symbol(sym)
        coverage_rows.append(cov)
        all_trades.extend(tr)
        print(f"    1m={cov['n_1m']} sess={cov['n_sessions']} trades+arms={len(tr)}", flush=True)

    def subset(*, htf: Optional[str] = None, ltf: Optional[str] = None, arm: Optional[str] = None, split: Optional[str] = None) -> list[dict[str, Any]]:
        rows = all_trades
        if htf:
            rows = [t for t in rows if t["htf"] == htf]
        if ltf:
            rows = [t for t in rows if t["ltf"] == ltf]
        if arm:
            rows = [t for t in rows if t["arm"] == arm]
        if split:
            rows = [t for t in rows if t["split"] == split]
        return rows

    books: list[dict[str, Any]] = []
    # Timeframe grid under control
    for htf in HTF_LIST:
        for ltf in LTF_LIST:
            rows = subset(htf=htf, ltf=ltf, arm=CONTROL_ARM)
            books.append(
                {
                    "table": "tf_control",
                    "book": f"{htf}×{ltf} control",
                    "htf": htf,
                    "ltf": ltf,
                    "arm": CONTROL_ARM,
                    "split": "FULL",
                    "verdict": "control",
                    "m": metrics_from_trades(rows),
                }
            )

    # Stop AB per HTF×LTF
    for htf in HTF_LIST:
        for ltf in LTF_LIST:
            ctrl_rows = subset(htf=htf, ltf=ltf, arm=CONTROL_ARM)
            ctrl_m = metrics_from_trades(ctrl_rows)
            for arm in STOP_ARMS:
                rows = subset(htf=htf, ltf=ltf, arm=arm)
                m = metrics_from_trades(rows)
                is_m = metrics_from_trades(subset(htf=htf, ltf=ltf, arm=arm, split="IS"))
                oos_m = metrics_from_trades(subset(htf=htf, ltf=ltf, arm=arm, split="OOS"))
                oos_soft = False
                if is_m["N"] >= 8 and oos_m["N"] >= 5:
                    if (oos_m["Avg_PnL_%"] or 0) < (is_m["Avg_PnL_%"] or 0) - 0.01:
                        oos_soft = True
                    pf_is = is_m.get("Profit_Factor")
                    pf_oos = oos_m.get("Profit_Factor")
                    if (
                        pf_is is not None
                        and pf_oos is not None
                        and math.isfinite(float(pf_is))
                        and math.isfinite(float(pf_oos))
                        and float(pf_oos) < float(pf_is) * 0.85
                    ):
                        oos_soft = True
                verdict = "control" if arm == CONTROL_ARM else judge_vs_control(m, ctrl_m, oos_soft=oos_soft)
                books.append(
                    {
                        "table": "stop_ab",
                        "book": f"{htf}×{ltf} {arm}",
                        "htf": htf,
                        "ltf": ltf,
                        "arm": arm,
                        "split": "FULL",
                        "verdict": verdict + (" · OOS soft" if oos_soft and arm != CONTROL_ARM else ""),
                        "m": m,
                        "d_avg": "—" if arm == CONTROL_ARM else fmt_delta(m.get("Avg_PnL_%"), ctrl_m.get("Avg_PnL_%"), 3),
                        "d_pf": "—" if arm == CONTROL_ARM else fmt_delta(m.get("Profit_Factor"), ctrl_m.get("Profit_Factor"), 2),
                        "d_wr": "—" if arm == CONTROL_ARM else fmt_delta(m.get("Win%"), ctrl_m.get("Win%"), 1),
                    }
                )
                books.append(
                    {
                        "table": "split",
                        "book": f"{htf}×{ltf} {arm} IS",
                        "htf": htf,
                        "ltf": ltf,
                        "arm": arm,
                        "split": "IS",
                        "verdict": "",
                        "m": is_m,
                    }
                )
                books.append(
                    {
                        "table": "split",
                        "book": f"{htf}×{ltf} {arm} OOS",
                        "htf": htf,
                        "ltf": ltf,
                        "arm": arm,
                        "split": "OOS",
                        "verdict": "HOLD" if oos_soft else "",
                        "m": oos_m,
                    }
                )

    # Best control TF + best stop vs its control (full sample, N>=8)
    tf_ctrl = [b for b in books if b["table"] == "tf_control" and b["m"]["N"] >= 1]
    best_tf = max(tf_ctrl, key=lambda b: quality_score(b["m"])) if tf_ctrl else None
    stop_cands = [
        b
        for b in books
        if b["table"] == "stop_ab" and b["arm"] != CONTROL_ARM and b["m"]["N"] >= 8
    ]
    best_stop = max(stop_cands, key=lambda b: quality_score(b["m"])) if stop_cands else None
    if best_tf and best_stop:
        best_line = (
            f"Best control timeframe: {best_tf['htf']}×{best_tf['ltf']} "
            f"N={best_tf['m']['N']} WR={fmt_num(best_tf['m']['Win%'],1)}% "
            f"Avg={fmt_num(best_tf['m']['Avg_PnL_%'],3)}% PF={fmt_num(best_tf['m']['Profit_Factor'],2)}. "
            f"Best stop arm vs its pair: {best_stop['book']} "
            f"N={best_stop['m']['N']} WR={fmt_num(best_stop['m']['Win%'],1)}% "
            f"Avg={fmt_num(best_stop['m']['Avg_PnL_%'],3)}% PF={fmt_num(best_stop['m']['Profit_Factor'],2)} "
            f"dAvg={best_stop.get('d_avg')} ({best_stop.get('verdict')})."
        )
    elif best_tf:
        best_line = (
            f"Best control timeframe: {best_tf['htf']}×{best_tf['ltf']} "
            f"N={best_tf['m']['N']} Avg={fmt_num(best_tf['m']['Avg_PnL_%'],3)}%. "
            "Stop arms too thin to rank."
        )
    else:
        best_line = "No trades — check coverage / freeze."

    any_oos_soft = any("OOS soft" in str(b.get("verdict")) for b in books if b.get("table") == "stop_ab")
    verdict_note = (
        "Short Yahoo 1m window (all post-2024). "
        + ("OOS softened on at least one arm → HOLD, do not retune. " if any_oos_soft else "")
        + "Research candidate only; not gold; not DailyRun."
    )
    n_1m = sum(int(r["n_1m"]) for r in coverage_rows)
    n_sess = max((int(r["n_sessions"]) for r in coverage_rows), default=0)
    coverage_note = (
        f"{len(symbols)} symbols, {n_1m:,} RTH 1m bars, up to {n_sess} sessions "
        f"in store (typical mega-cap ~Jul 23–Sep 16 2026; AAPL shorter)."
    )

    write_trades_csv(out_dir / "trades.csv", all_trades)
    # Cheap exit-date equity for the headline control (2h×1m) and 30m×1m control.
    for htf_e, ltf_e, tag in (("2h", "1m", "2h_1m_control"), ("30m", "1m", "30m_1m_control")):
        eq_rows = subset(htf=htf_e, ltf=ltf_e, arm=CONTROL_ARM)
        eq_path = out_dir / f"equity_{tag}.csv"
        by_d: dict[str, float] = {}
        for t in eq_rows:
            by_d[str(t["session"])] = by_d.get(str(t["session"]), 0.0) + float(t["pnl_usd"])
        eq = INIT_ACCT
        peak = INIT_ACCT
        with eq_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "day_pnl_usd", "equity", "dd_pct"])
            for d in sorted(by_d):
                eq += by_d[d]
                peak = max(peak, eq)
                dd = (peak - eq) / peak * 100.0 if peak else 0.0
                w.writerow([d, f"{by_d[d]:.2f}", f"{eq:.2f}", f"{dd:.4f}"])
    write_baseline(
        out_dir / "BASELINE.md",
        stamp=stamp,
        symbols=symbols,
        coverage_rows=coverage_rows,
        n_trades=len(all_trades),
    )
    # Prefer 30m×1m control trades in the HTML sample, then the rest
    sample = [t for t in all_trades if t["htf"] == "30m" and t["ltf"] == "1m"]
    if len(sample) < 80:
        sample = all_trades
    write_html(
        out_dir / "compare.html",
        stamp=stamp,
        symbols=symbols,
        coverage_rows=coverage_rows,
        books=books,
        sample_trades=sample,
        verdict_note=verdict_note,
        best_line=best_line,
        coverage_note=coverage_note,
    )
    books_path = out_dir / "books.csv"
    with books_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "table",
                "book",
                "htf",
                "ltf",
                "arm",
                "split",
                "verdict",
                "N",
                "Win%",
                "Avg_PnL_%",
                "PF",
                "Max_DD_%",
                "Avg_min_held",
                "stop_out_%",
            ]
        )
        for b in books:
            m = b["m"]
            w.writerow(
                [
                    b.get("table"),
                    b.get("book"),
                    b.get("htf"),
                    b.get("ltf"),
                    b.get("arm"),
                    b.get("split"),
                    b.get("verdict"),
                    m.get("N"),
                    m.get("Win%"),
                    m.get("Avg_PnL_%"),
                    m.get("Profit_Factor"),
                    m.get("Max_DD_%"),
                    m.get("Avg_min_held"),
                    m.get("stop_out_%"),
                ]
            )

    print(best_line, flush=True)
    print(f"wrote {out_dir / 'compare.html'}", flush=True)
    print(f"trades={len(all_trades)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
