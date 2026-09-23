#!/usr/bin/env python3
"""2-hour volume-zone write window vs 2-minute buy + chandelier exit (research pictures).

Volume Zone (VZ) analog on Regular Trading Hours (RTH) 2h bars: the trailing
available-history max-volume 2h bar writes a High–Low band. Buy the first 2m
retest from above after price has left the band. Exit: chandelier 3× Average
True Range (ATR) on 2m (one freeze).

Research only. Not gold. Not DailyRun. Does not mutate house VZ or the HTF
chandelier freeze.

Usage:
  python tools/vz2h_2m_zonewrite_20260916.py
"""
from __future__ import annotations

import html as html_mod
import json
import math
import sys
from datetime import date, time
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
sys.path.insert(0, str(ROOT / "tools"))

from intraday_1m import DEFAULT_1M_DIR, ET, read_1m  # noqa: E402
from intraday_htf_retest_20260916 import (  # noqa: E402
    CHANDELIER_N,
    ENTRY_CUTOFF,
    EXTRA_UNIVERSE,
    SESSION_CLOSE,
    SESSION_OPEN,
    TIME_STOP_T,
    load_paultwenty,
    resample_from_rth_open,
    rth_filter,
    wilder_atr,
)

STAMP_NAME = "vz2h_2m_zonewrite_20260916"
STAMP = ROOT / "drive" / "paul_experiments" / STAMP_NAME
CHART_DIR = STAMP / "charts"
GALLERY = STAMP / "compare.html"
DAILY_DIR = ROOT / "data" / "newdata" / "data"

# --- Freeze ---
HTF_MINUTES = 120
LTF_MINUTES = 2
TARGET_LOOKBACK_SESSIONS = 63  # ~3 months of sessions
MIN_WRITE_SESSIONS = 20  # warmup before first zone identity
DAILY_LOOKBACK_SESSIONS = 63
CHANDELIER_MULT = CHANDELIER_N  # 3.0 — rhyme with HTF 4h×1m gallery
INIT_STOP_ATR_MULT = 0.50  # used only if zone.lo sits at/above the fill
MIN_STOP_PCT = 0.0005
ENTRY_CUTOFF_T = ENTRY_CUTOFF
TIME_FLAT_T = TIME_STOP_T
MAX_CHARTS = 20
SHEET = 45_000.0
SHORT_TAPE_OOS = date(2026, 9, 2)

ORIGINAL_REQUEST = (
    "also show me how the 2hr zone-writing window affects the 2m candle buy + exit"
)

PLAIN_ENGLISH = (
    "The left pane is the slower 2-hour chart: the Regular Trading Hours (RTH) "
    "2-hour bar that wrote the zone — the highest-volume 2-hour bar we have in "
    "the trailing tape — and the High–Low band that bar left behind. The right "
    "pane is the 2-minute tape: after price leaves that band, it comes back and "
    "taps it (a bounce / retest); we buy the next 2-minute open and walk a "
    "chandelier stop (highest high since the fill minus 3 typical 2-minute "
    "ranges). The point of the pair is to see whether the 2-hour write window "
    "and the 2-minute fill agree, or whether the tape already traded while the "
    "2-hour bar was still forming."
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


def _ts(val: Any) -> pd.Timestamp:
    t = pd.Timestamp(val)
    if t.tzinfo is None:
        return t.tz_localize(ET)
    return t.tz_convert(ET)


def _fmt_clock(t: pd.Timestamp) -> str:
    return _ts(t).strftime("%Y-%m-%d %H:%M ET")


def _tod(ts: Any) -> time:
    return _ts(ts).time().replace(tzinfo=None)


def universe() -> list[str]:
    out: list[str] = []
    for s in load_paultwenty() + list(EXTRA_UNIVERSE):
        u = str(s).strip().upper()
        if u and u not in out:
            out.append(u)
    return out


def load_daily(sym: str) -> pd.DataFrame:
    path = DAILY_DIR / f"{sym}.csv"
    if not path.is_file():
        return pd.DataFrame()
    df = pd.read_csv(path)
    if df.empty or "Date" not in df.columns or "Volume" not in df.columns:
        return pd.DataFrame()
    out = df.copy()
    out["Date"] = pd.to_datetime(out["Date"]).dt.normalize()
    out["Volume"] = pd.to_numeric(out["Volume"], errors="coerce")
    return out.dropna(subset=["Date", "Volume"]).sort_values("Date").reset_index(drop=True)


def daily_maxvol_context(daily: pd.DataFrame, asof: pd.Timestamp) -> dict[str, Any]:
    empty = {
        "daily_63d_maxvol_date": "",
        "daily_63d_maxvol": "",
        "write_day_is_daily_63d_max": "",
        "daily_63d_max_on_tape": "",
    }
    if daily is None or daily.empty:
        return empty
    asof_d = pd.Timestamp(_ts(asof).date())
    hist = daily.loc[daily["Date"] <= asof_d]
    if hist.empty:
        return empty
    win = hist.tail(DAILY_LOOKBACK_SESSIONS)
    if win.empty:
        return empty
    i = int(win["Volume"].to_numpy(dtype=float).argmax())
    row = win.iloc[i]
    max_d = pd.Timestamp(row["Date"]).date().isoformat()
    return {
        "daily_63d_maxvol_date": max_d,
        "daily_63d_maxvol": int(row["Volume"]),
        "write_day_is_daily_63d_max": "yes" if max_d == asof_d.date().isoformat() else "no",
        "daily_63d_max_on_tape": "",  # filled later
    }


def _draw_candles(ax, opens, highs, lows, closes, width: float = 0.62) -> None:
    n = len(opens)
    xs = np.arange(n, dtype=float)
    up = closes >= opens
    wick = np.where(up, "#2e7d32", "#c62828")
    ax.vlines(xs, lows, highs, color=wick, linewidth=0.7, zorder=2)
    body_lo = np.minimum(opens, closes)
    height = np.maximum(np.abs(closes - opens), np.maximum(np.abs(closes) * 1e-4, 1e-4))
    for i in range(n):
        color = "#2e7d32" if up[i] else "#c62828"
        ax.add_patch(
            Rectangle(
                (xs[i] - width / 2.0, body_lo[i]),
                width,
                height[i],
                facecolor=color,
                edgecolor=color,
                linewidth=0.25,
                alpha=0.92,
                zorder=3,
            )
        )


def _set_xticks(ax, times: list[pd.Timestamp], *, max_ticks: int, mode: str) -> None:
    n = len(times)
    if n == 0:
        return
    step = max(1, int(np.ceil(n / max_ticks)))
    idxs = list(range(0, n, step))
    if idxs[-1] != n - 1:
        idxs.append(n - 1)
    labels = []
    for i in idxs:
        t = _ts(times[i])
        if mode == "2h":
            labels.append(t.strftime("%b %d\n%H:%M"))
        else:
            labels.append(t.strftime("%H:%M"))
    ax.set_xticks(idxs)
    ax.set_xticklabels(labels, fontsize=8)


def _nearest_idx(times: Any, target: pd.Timestamp, *, slop_min: float = 6.0) -> Optional[int]:
    if times is None or len(times) == 0:
        return None
    tgt_s = _ts(target).timestamp()
    best_i = 0
    best_d = float("inf")
    for i, x in enumerate(times):
        d = abs(_ts(x).timestamp() - tgt_s)
        if d < best_d:
            best_d = d
            best_i = i
    if best_d > slop_min * 60.0:
        return None
    return int(best_i)


def first_index_with_sessions(htf: pd.DataFrame, n_sessions: int) -> int:
    days = pd.to_datetime(htf["ts"], utc=True).dt.tz_convert(ET).dt.normalize()
    seen: set[Any] = set()
    for i, d in enumerate(days):
        seen.add(pd.Timestamp(d))
        if len(seen) >= n_sessions:
            return i
    return max(0, len(htf) - 1)


def build_2h_zones(htf: pd.DataFrame) -> list[dict[str, Any]]:
    """House VZ identity on 2h: unique expanding-window max-volume winners → HL zone."""
    if htf is None or htf.empty:
        return []
    vol = htf["volume"].to_numpy(dtype=float)
    n = len(htf)
    start_i = first_index_with_sessions(htf, MIN_WRITE_SESSIONS)
    if start_i < 8 or n < start_i + 2:
        return []
    ts = pd.to_datetime(htf["ts"], utc=True).dt.tz_convert(ET)
    end_ts = pd.to_datetime(htf["end_ts"], utc=True).dt.tz_convert(ET)
    sessions = ts.dt.normalize()
    n_sess_total = int(sessions.nunique())
    lookback_sessions = min(n_sess_total, TARGET_LOOKBACK_SESSIONS)
    zones: list[dict[str, Any]] = []
    seen: set[int] = set()
    for t in range(start_i, n):
        # Expanding available history (tape is shorter than 63 sessions).
        winner = int(np.argmax(vol[: t + 1]))
        if winner in seen:
            continue
        seen.add(winner)
        lo = float(htf["low"].iloc[winner])
        hi = float(htf["high"].iloc[winner])
        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
            continue
        write_ts = _ts(ts.iloc[winner])
        write_end = _ts(end_ts.iloc[winner])
        known_ts = _ts(end_ts.iloc[t])
        zones.append(
            {
                "write_i": winner,
                "known_i": t,
                "write_ts": write_ts,
                "write_end_ts": write_end,
                "known_ts": known_ts,
                "zone_lo": lo,
                "zone_hi": hi,
                "write_volume": float(vol[winner]),
                "write_open": float(htf["open"].iloc[winner]),
                "write_close": float(htf["close"].iloc[winner]),
                "lookback_sessions": lookback_sessions,
                "lookback_label": (
                    f"expanding 2h history after {MIN_WRITE_SESSIONS} sessions "
                    f"(~{lookback_sessions} sessions on tape; target {TARGET_LOOKBACK_SESSIONS})"
                ),
                "write_eq_known": bool(winner == t),
            }
        )
    return zones


def timing_class(write_end: pd.Timestamp, fill_ts: pd.Timestamp, next_2h_end: Optional[pd.Timestamp]) -> str:
    we = _ts(write_end)
    ft = _ts(fill_ts)
    if ft < we:
        return "DURING_WRITE"
    if next_2h_end is not None and ft < _ts(next_2h_end):
        return "NEXT_2H"
    if ft.date() == we.date():
        return "LATER_SAME_DAY"
    return "LATER_DAY"


def simulate_chandelier(
    ltf: pd.DataFrame,
    atr: np.ndarray,
    *,
    entry_i: int,
    entry_px: float,
    zone_lo: float,
) -> Optional[dict[str, Any]]:
    n = len(ltf)
    if entry_i < 0 or entry_i >= n:
        return None
    atr_e = float(atr[entry_i]) if entry_i < len(atr) and np.isfinite(atr[entry_i]) else float("nan")
    if not np.isfinite(atr_e) or atr_e <= 0:
        atr_e = entry_px * 0.001
    stop0 = float(zone_lo)
    if stop0 >= entry_px:
        stop0 = entry_px - INIT_STOP_ATR_MULT * atr_e
    if entry_px <= 0 or (entry_px - stop0) / entry_px < MIN_STOP_PCT:
        return None
    r_dist = entry_px - stop0
    stop = stop0
    run_high = float(ltf["high"].iloc[entry_i])
    ts = pd.to_datetime(ltf["ts"], utc=True).dt.tz_convert(ET)
    highs = ltf["high"].to_numpy(dtype=float)
    lows = ltf["low"].to_numpy(dtype=float)
    opens = ltf["open"].to_numpy(dtype=float)
    closes = ltf["close"].to_numpy(dtype=float)

    for j in range(entry_i, n):
        t = _ts(ts.iloc[j])
        tod = t.time().replace(tzinfo=None)
        if j > entry_i:
            prev_h = float(highs[j - 1])
            if np.isfinite(prev_h):
                run_high = max(run_high, prev_h)
            atr_j = float(atr[j - 1]) if np.isfinite(atr[j - 1]) else atr_e
            stop = max(stop, run_high - CHANDELIER_MULT * atr_j)
        if tod >= TIME_FLAT_T:
            exit_px = float(opens[j])
            return _fill_row(ltf, ts, entry_i, j, entry_px, exit_px, stop0, stop, "TIME", r_dist)
        if float(lows[j]) <= stop:
            return _fill_row(ltf, ts, entry_i, j, entry_px, stop, stop0, stop, "STOP", r_dist)
    last = n - 1
    return _fill_row(
        ltf, ts, entry_i, last, entry_px, float(closes[last]), stop0, stop, "EOD_FLAT", r_dist
    )


def _fill_row(
    ltf: pd.DataFrame,
    ts: pd.Series,
    entry_i: int,
    exit_i: int,
    entry_px: float,
    exit_px: float,
    stop0: float,
    stop_final: float,
    exit_type: str,
    r_dist: float,
) -> dict[str, Any]:
    et = _ts(ts.iloc[entry_i])
    xt = _ts(ts.iloc[exit_i])
    pnl_pct = (exit_px / entry_px - 1.0) * 100.0
    shares = math.floor(SHEET / entry_px) if entry_px > 0 else 0
    return {
        "entry_i": entry_i,
        "exit_i": exit_i,
        "entry_px": float(entry_px),
        "exit_px": float(exit_px),
        "stop0": float(stop0),
        "stop_final": float(stop_final),
        "exit_type": exit_type,
        "pnl_pct": float(pnl_pct),
        "r_mult": float((exit_px - entry_px) / r_dist) if r_dist > 0 else float("nan"),
        "entry_ts": et,
        "exit_ts": xt,
        "hold_min": max(0.0, (xt - et).total_seconds() / 60.0),
        "shares": shares,
        "pnl_usd": shares * (exit_px - entry_px),
    }


def chandelier_path(
    highs: np.ndarray,
    atr: np.ndarray,
    entry_i: int,
    exit_i: int,
    stop0: float,
    atr_fallback: float,
) -> np.ndarray:
    n = exit_i - entry_i + 1
    out = np.full(n, np.nan, dtype=float)
    stop = float(stop0)
    run_high = float(highs[entry_i])
    for j in range(entry_i, exit_i + 1):
        if j > entry_i:
            prev_h = float(highs[j - 1])
            if np.isfinite(prev_h):
                run_high = max(run_high, prev_h)
            atr_j = float(atr[j - 1]) if np.isfinite(atr[j - 1]) else atr_fallback
            stop = max(stop, run_high - CHANDELIER_MULT * atr_j)
        out[j - entry_i] = stop
    return out


def scan_symbol(sym: str) -> dict[str, Any]:
    raw = read_1m(sym, DEFAULT_1M_DIR)
    df1 = rth_filter(raw)
    empty = {
        "symbol": sym,
        "events": [],
        "n_1m": 0,
        "n_sessions": 0,
        "tape_first": "",
        "tape_last": "",
        "n_2h": 0,
        "n_zones": 0,
        "skip": "no 1m bars" if raw is None or raw.empty else "empty after RTH filter",
    }
    if df1 is None or df1.empty:
        return empty
    df1 = df1.copy()
    if "end_ts" not in df1.columns:
        df1["end_ts"] = df1["ts"] + pd.Timedelta(minutes=1)
    htf = resample_from_rth_open(df1, HTF_MINUTES)
    ltf = resample_from_rth_open(df1, LTF_MINUTES)
    if htf.empty or ltf.empty:
        empty["skip"] = "resample empty"
        empty["n_1m"] = int(len(df1))
        return empty
    ts1 = pd.to_datetime(df1["ts"], utc=True).dt.tz_convert(ET)
    n_sess = int(ts1.dt.normalize().nunique())
    pack = {
        "symbol": sym,
        "events": [],
        "n_1m": int(len(df1)),
        "n_sessions": n_sess,
        "tape_first": _fmt_clock(_ts(ts1.iloc[0])),
        "tape_last": _fmt_clock(_ts(ts1.iloc[-1])),
        "n_2h": int(len(htf)),
        "n_zones": 0,
        "skip": "",
        "df1": df1,
        "htf": htf,
        "ltf": ltf,
    }
    atr2 = wilder_atr(
        ltf["high"].to_numpy(dtype=float),
        ltf["low"].to_numpy(dtype=float),
        ltf["close"].to_numpy(dtype=float),
    )
    daily = load_daily(sym)
    zones = build_2h_zones(htf)
    pack["n_zones"] = len(zones)
    htf_end = pd.to_datetime(htf["end_ts"], utc=True).dt.tz_convert(ET)
    ltf_ts = pd.to_datetime(ltf["ts"], utc=True).dt.tz_convert(ET)
    ltf_end = pd.to_datetime(ltf["end_ts"], utc=True).dt.tz_convert(ET)
    tape_first_d = _ts(ts1.iloc[0]).date().isoformat()
    tape_last_d = _ts(ts1.iloc[-1]).date().isoformat()

    for z in zones:
        dctx = daily_maxvol_context(daily, z["write_ts"])
        max_d = str(dctx.get("daily_63d_maxvol_date") or "")
        if max_d:
            dctx["daily_63d_max_on_tape"] = (
                "yes" if tape_first_d <= max_d <= tape_last_d else "no"
            )
        known = _ts(z["known_ts"])
        write_end = _ts(z["write_end_ts"])
        zone_lo = float(z["zone_lo"])
        zone_hi = float(z["zone_hi"])
        next_2h_end = None
        if int(z["write_i"]) + 1 < len(htf):
            next_2h_end = _ts(htf_end.iloc[int(z["write_i"]) + 1])

        # Search 2m only after the zone is known (2h write/known close). No look-ahead.
        start_known = max(known, write_end)
        left_i: Optional[int] = None
        for i in range(len(ltf)):
            t = _ts(ltf_ts.iloc[i])
            if t < start_known:
                continue
            if float(ltf["close"].iloc[i]) > zone_hi:
                left_i = i
                break
        if left_i is None:
            ev = _event_base(sym, z, dctx, n_sess)
            ev.update(
                {
                    "kind": "NO_LEAVE",
                    "outcome": "price never closed above the 2h zone after it was known",
                }
            )
            pack["events"].append(ev)
            continue

        fail_i: Optional[int] = None
        retest_i: Optional[int] = None
        for i in range(left_i + 1, len(ltf)):
            lo = float(ltf["low"].iloc[i])
            hi = float(ltf["high"].iloc[i])
            cl = float(ltf["close"].iloc[i])
            if not (lo <= zone_hi and hi >= zone_lo):
                continue
            if cl < zone_lo:
                fail_i = i
                break
            retest_i = i
            break

        if fail_i is not None:
            ev = _event_base(sym, z, dctx, n_sess)
            ev.update(
                {
                    "kind": "FAIL_RETEST",
                    "leave_ts": _ts(ltf_ts.iloc[left_i]),
                    "retest_ts": _ts(ltf_ts.iloc[fail_i]),
                    "outcome": "2m tagged the zone then closed through the low — no buy",
                    "timing_class": timing_class(write_end, _ts(ltf_ts.iloc[fail_i]), next_2h_end),
                    "mins_after_write_close": (
                        _ts(ltf_ts.iloc[fail_i]) - write_end
                    ).total_seconds()
                    / 60.0,
                }
            )
            pack["events"].append(ev)
            continue
        if retest_i is None:
            ev = _event_base(sym, z, dctx, n_sess)
            ev.update(
                {
                    "kind": "NO_RETEST",
                    "leave_ts": _ts(ltf_ts.iloc[left_i]),
                    "outcome": "left the zone; no 2m tag before tape end",
                }
            )
            pack["events"].append(ev)
            continue

        entry_i = retest_i + 1
        if entry_i >= len(ltf):
            ev = _event_base(sym, z, dctx, n_sess)
            ev.update(
                {
                    "kind": "NO_FILL",
                    "leave_ts": _ts(ltf_ts.iloc[left_i]),
                    "retest_ts": _ts(ltf_ts.iloc[retest_i]),
                    "outcome": "retest on last 2m bar — no next open",
                }
            )
            pack["events"].append(ev)
            continue
        entry_ts = _ts(ltf_ts.iloc[entry_i])
        if _tod(entry_ts) >= ENTRY_CUTOFF_T:
            ev = _event_base(sym, z, dctx, n_sess)
            ev.update(
                {
                    "kind": "CUTOFF",
                    "leave_ts": _ts(ltf_ts.iloc[left_i]),
                    "retest_ts": _ts(ltf_ts.iloc[retest_i]),
                    "outcome": "retest after 15:45 ET — no entry",
                    "timing_class": timing_class(write_end, entry_ts, next_2h_end),
                }
            )
            pack["events"].append(ev)
            continue

        sim = simulate_chandelier(
            ltf,
            atr2,
            entry_i=entry_i,
            entry_px=float(ltf["open"].iloc[entry_i]),
            zone_lo=zone_lo,
        )
        ev = _event_base(sym, z, dctx, n_sess)
        ev.update(
            {
                "kind": "TRADE",
                "leave_ts": _ts(ltf_ts.iloc[left_i]),
                "retest_ts": _ts(ltf_ts.iloc[retest_i]),
                "retest_low": float(ltf["low"].iloc[retest_i]),
            }
        )
        if sim is None:
            ev.update({"kind": "NO_FILL", "outcome": "stop distance too tight"})
            pack["events"].append(ev)
            continue
        fill_loc = _fill_vs_zone(float(sim["entry_px"]), zone_lo, zone_hi)
        ev.update(
            {
                **sim,
                "outcome": "filled",
                "fill_vs_zone": fill_loc,
                "timing_class": timing_class(write_end, sim["entry_ts"], next_2h_end),
                "mins_after_write_close": (
                    _ts(sim["entry_ts"]) - write_end
                ).total_seconds()
                / 60.0,
                "write_still_forming_at_fill": bool(_ts(sim["entry_ts"]) < write_end),
                "entry_date": _ts(sim["entry_ts"]).date().isoformat(),
                "split": (
                    "OOS"
                    if _ts(sim["entry_ts"]).date() >= SHORT_TAPE_OOS
                    else "IS"
                ),
            }
        )
        pack["events"].append(ev)
    return pack


def _fill_vs_zone(px: float, lo: float, hi: float) -> str:
    if px < lo:
        return "below_zone"
    if px > hi:
        return "above_zone"
    return "inside_zone"


def _event_base(sym: str, z: dict[str, Any], dctx: dict[str, Any], n_sess: int) -> dict[str, Any]:
    return {
        "symbol": sym,
        "kind": "",
        "write_ts": z["write_ts"],
        "write_end_ts": z["write_end_ts"],
        "known_ts": z["known_ts"],
        "write_i": z["write_i"],
        "known_i": z["known_i"],
        "zone_lo": z["zone_lo"],
        "zone_hi": z["zone_hi"],
        "write_volume": z["write_volume"],
        "write_open": z["write_open"],
        "write_close": z["write_close"],
        "lookback_sessions": z["lookback_sessions"],
        "lookback_label": z["lookback_label"],
        "write_eq_known": z["write_eq_known"],
        "n_sessions_on_tape": n_sess,
        "leave_ts": "",
        "retest_ts": "",
        "retest_low": "",
        "entry_ts": "",
        "exit_ts": "",
        "entry_px": "",
        "exit_px": "",
        "stop0": "",
        "stop_final": "",
        "exit_type": "",
        "pnl_pct": "",
        "r_mult": "",
        "hold_min": "",
        "timing_class": "",
        "mins_after_write_close": "",
        "fill_vs_zone": "",
        "write_still_forming_at_fill": "",
        "outcome": "",
        "entry_date": "",
        "split": "",
        **dctx,
    }


def pick_chart_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    trades = [e for e in events if e.get("kind") == "TRADE"]
    fails = [e for e in events if e.get("kind") == "FAIL_RETEST"]
    trades = sorted(trades, key=lambda e: (_ts(e["entry_ts"]), e["symbol"]))
    fails = sorted(fails, key=lambda e: (_ts(e.get("retest_ts") or e["write_ts"]), e["symbol"]))

    wins = [e for e in trades if float(e.get("pnl_pct") or 0) > 0]
    losses = [e for e in trades if float(e.get("pnl_pct") or 0) <= 0]

    def diversify(pool: list[dict[str, Any]], k: int) -> list[dict[str, Any]]:
        if k <= 0 or not pool:
            return []
        by_sym: dict[str, list[dict[str, Any]]] = {}
        for e in pool:
            by_sym.setdefault(str(e["symbol"]), []).append(e)
        out: list[dict[str, Any]] = []
        used: set[int] = set()
        # round-robin symbols so one name cannot own the gallery
        keys = list(by_sym.keys())
        idx = {s: 0 for s in keys}
        while len(out) < k:
            progressed = False
            for s in keys:
                bucket = by_sym[s]
                i = idx[s]
                if i >= len(bucket):
                    continue
                ev = bucket[i]
                idx[s] += 1
                eid = id(ev)
                if eid in used:
                    continue
                used.add(eid)
                out.append(ev)
                progressed = True
                if len(out) >= k:
                    break
            if not progressed:
                break
        return out

    n_trade_slots = min(len(trades), 16 if fails else MAX_CHARTS)
    n_win = min(len(wins), max(4, n_trade_slots // 2))
    n_loss = min(len(losses), n_trade_slots - n_win)
    # If one side is short, give leftover slots to the other.
    if n_win + n_loss < n_trade_slots:
        extra = n_trade_slots - n_win - n_loss
        if len(wins) > n_win:
            n_win = min(len(wins), n_win + extra)
            extra = n_trade_slots - n_win - n_loss
        if extra and len(losses) > n_loss:
            n_loss = min(len(losses), n_loss + extra)

    chosen = diversify(wins, n_win) + diversify(losses, n_loss)
    # Prefer a mix of timing classes if we still have room among leftover trades.
    have_ids = {id(e) for e in chosen}
    leftover = [e for e in trades if id(e) not in have_ids]
    need = min(MAX_CHARTS - len(chosen) - min(4, len(fails)), len(leftover))
    if need > 0:
        chosen.extend(diversify(leftover, need))

    fail_slots = min(len(fails), max(0, MAX_CHARTS - len(chosen)), 6)
    chosen.extend(diversify(fails, fail_slots))
    # No 2m close-through fails printed on this tape. Show no-buy outcomes so
    # the gallery is not fills-only (zone written, 2m never came back / never left).
    have_ids = {id(e) for e in chosen}
    no_buy = [
        e
        for e in events
        if e.get("kind") in ("NO_RETEST", "NO_LEAVE") and id(e) not in have_ids
    ]
    leftover_slots = max(0, MAX_CHARTS - len(chosen))
    chosen.extend(diversify(no_buy, leftover_slots))
    chosen = sorted(
        chosen,
        key=lambda e: (
            _ts(e.get("entry_ts") or e.get("retest_ts") or e.get("leave_ts") or e["write_ts"]),
            e["symbol"],
        ),
    )
    return chosen[:MAX_CHARTS]


def slice_2h(htf: pd.DataFrame, write_ts: pd.Timestamp, end_ts: pd.Timestamp) -> pd.DataFrame:
    ts = pd.to_datetime(htf["ts"], utc=True).dt.tz_convert(ET)
    wr = ts.searchsorted(_ts(write_ts), side="left")
    if wr >= len(htf):
        wr = len(htf) - 1
    lo = max(0, int(wr) - 16)
    ex = ts.searchsorted(_ts(end_ts), side="right")
    hi = min(len(htf), max(int(wr) + 6, int(ex) + 2))
    return htf.iloc[lo:hi].reset_index(drop=True)


def slice_2m(
    ltf: pd.DataFrame,
    *,
    write_end: pd.Timestamp,
    retest_ts: pd.Timestamp,
    exit_ts: pd.Timestamp,
) -> pd.DataFrame:
    ts = pd.to_datetime(ltf["ts"], utc=True).dt.tz_convert(ET)
    start = _ts(retest_ts) - pd.Timedelta(minutes=40)
    we = _ts(write_end)
    if we >= start - pd.Timedelta(minutes=30) and we <= _ts(exit_ts) + pd.Timedelta(minutes=10):
        start = min(start, we - pd.Timedelta(minutes=8))
    end = _ts(exit_ts) + pd.Timedelta(minutes=10)
    mask = (ts >= start) & (ts <= end)
    return ltf.loc[mask].reset_index(drop=True)


def render_event(ev: dict[str, Any], pack: dict[str, Any], out_png: Path) -> Optional[str]:
    htf: pd.DataFrame = pack["htf"]
    ltf: pd.DataFrame = pack["ltf"]
    zone_lo = float(ev["zone_lo"])
    zone_hi = float(ev["zone_hi"])
    write_ts = _ts(ev["write_ts"])
    write_end = _ts(ev["write_end_ts"])
    known_ts = _ts(ev["known_ts"])
    kind = str(ev.get("kind") or "")
    if ev.get("retest_ts"):
        retest_ts = _ts(ev["retest_ts"])
    elif ev.get("leave_ts"):
        retest_ts = _ts(ev["leave_ts"])
    else:
        retest_ts = known_ts
    if ev.get("exit_ts"):
        end_anchor = _ts(ev["exit_ts"])
    elif ev.get("retest_ts"):
        end_anchor = _ts(ev["retest_ts"]) + pd.Timedelta(minutes=20)
    elif ev.get("leave_ts"):
        end_anchor = _ts(ev["leave_ts"]) + pd.Timedelta(minutes=40)
    else:
        end_anchor = known_ts + pd.Timedelta(hours=4)

    left = slice_2h(htf, write_ts, end_anchor)
    right = slice_2m(ltf, write_end=write_end, retest_ts=retest_ts, exit_ts=end_anchor)
    if left.empty or len(left) < 3:
        return "not enough 2h bars around the write"
    if right.empty or len(right) < 3:
        return "not enough 2m bars around the retest"

    l_ts = pd.to_datetime(left["ts"], utc=True).dt.tz_convert(ET)
    r_ts = pd.to_datetime(right["ts"], utc=True).dt.tz_convert(ET)
    atr2_full = wilder_atr(
        ltf["high"].to_numpy(dtype=float),
        ltf["low"].to_numpy(dtype=float),
        ltf["close"].to_numpy(dtype=float),
    )
    full_ts = pd.to_datetime(ltf["ts"], utc=True).dt.tz_convert(ET)

    fig, axes = plt.subplots(1, 2, figsize=(16.6, 7.55), facecolor="#f8fafc")
    fig.subplots_adjust(left=0.055, right=0.985, top=0.76, bottom=0.18, wspace=0.18)

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
    ax.axhspan(zone_lo, zone_hi, color="#f59e0b", alpha=0.18, zorder=1)
    ax.axhline(zone_hi, color="#b45309", lw=1.2, zorder=4)
    ax.axhline(zone_lo, color="#b45309", lw=1.2, zorder=4)
    wr_i = _nearest_idx(l_ts, write_ts, slop_min=130.0)
    if wr_i is not None:
        ax.axvspan(wr_i - 0.45, wr_i + 0.45, color="#7c3aed", alpha=0.12, zorder=0)
        ax.axvline(wr_i, color="#7c3aed", lw=1.15, ls=":", alpha=0.9, zorder=4)
        ax.annotate(
            "2h write window",
            xy=(wr_i, float(left["high"].iloc[wr_i])),
            xytext=(8, 12),
            textcoords="offset points",
            fontsize=8,
            color="#5b21b6",
            arrowprops=dict(arrowstyle="->", color="#7c3aed", lw=0.8),
            zorder=7,
        )
    kn_i = _nearest_idx(l_ts, known_ts, slop_min=130.0)
    if kn_i is not None and (wr_i is None or kn_i != wr_i):
        ax.axvline(kn_i, color="#0369a1", lw=0.9, ls="--", alpha=0.8, zorder=4)
        ax.annotate(
            "zone known",
            xy=(kn_i, float(left["low"].iloc[kn_i])),
            xytext=(6, -16),
            textcoords="offset points",
            fontsize=7.5,
            color="#0369a1",
            zorder=7,
        )
    ax.set_xlim(-0.8, nL - 0.2)
    y_lo = min(float(left["low"].min()), zone_lo)
    y_hi = max(float(left["high"].max()), zone_hi)
    pad = max((y_hi - y_lo) * 0.12, 0.08)
    ax.set_ylim(y_lo - pad, y_hi + pad)
    _set_xticks(ax, list(l_ts), max_ticks=8, mode="2h")
    ax.set_ylabel("Price ($)", fontsize=9)
    mid = (zone_lo + zone_hi) / 2.0
    ax.set_title(
        f"2-hour RTH  ·  write-window HL zone  {zone_lo:.2f}–{zone_hi:.2f}  (mid {mid:.2f})",
        fontsize=10,
        loc="left",
        pad=6,
    )
    ax.grid(True, axis="y", color="#e2e8f0", lw=0.6)
    ax.tick_params(axis="y", labelsize=8)

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
    ax.axhspan(zone_lo, zone_hi, color="#f59e0b", alpha=0.14, zorder=1)
    ax.axhline(zone_hi, color="#b45309", lw=1.05, zorder=4)
    ax.axhline(zone_lo, color="#b45309", lw=1.05, zorder=4)

    def mark(ts_val: pd.Timestamp, label: str, color: str, y: float, marker: str = "v") -> None:
        i = _nearest_idx(r_ts, ts_val, slop_min=8.0)
        if i is None:
            return
        ax.scatter(
            [i], [y], marker=marker, s=46, color=color, zorder=7, edgecolors="white", linewidths=0.35
        )
        ax.annotate(
            label, xy=(i, y), xytext=(4, 8), textcoords="offset points", fontsize=7.5, color=color, zorder=8
        )

    we_r = _nearest_idx(r_ts, write_end, slop_min=10.0)
    if we_r is not None:
        ax.axvline(we_r, color="#7c3aed", lw=0.95, ls=":", alpha=0.85, zorder=4)
        mark(write_end, "2h close / zone known", "#7c3aed", float(right["high"].iloc[we_r]), marker="^")
    else:
        ax.text(
            0.01,
            0.97,
            f"2h write close off-pane: {_fmt_clock(write_end)}",
            transform=ax.transAxes,
            fontsize=7.2,
            color="#5b21b6",
            va="top",
        )

    if ev.get("leave_ts"):
        lv = _ts(ev["leave_ts"])
        li = _nearest_idx(r_ts, lv, slop_min=8.0)
        if li is not None:
            ax.axvline(li, color="#a16207", lw=0.7, ls="--", alpha=0.7, zorder=4)
            mark(lv, "left zone", "#a16207", float(right["high"].iloc[li]), marker="^")
    if ev.get("retest_ts"):
        rt = _ts(ev["retest_ts"])
        ri = _nearest_idx(r_ts, rt, slop_min=8.0)
        if ri is not None:
            ax.axvline(ri, color="#0284c7", lw=0.8, ls="--", alpha=0.75, zorder=4)
            mark(rt, "2m retest", "#0284c7", float(right["low"].iloc[ri]), marker="v")

    trail = np.array([])
    if kind == "TRADE" and ev.get("entry_ts"):
        entry_ts = _ts(ev["entry_ts"])
        exit_ts = _ts(ev["exit_ts"])
        entry_px = float(ev["entry_px"])
        exit_px = float(ev["exit_px"])
        stop0 = float(ev["stop0"])
        en_i = _nearest_idx(r_ts, entry_ts, slop_min=8.0)
        ex_i = _nearest_idx(r_ts, exit_ts, slop_min=8.0)
        en_full = _nearest_idx(full_ts, entry_ts, slop_min=4.0)
        ex_full = _nearest_idx(full_ts, exit_ts, slop_min=4.0)
        if en_i is not None:
            mark(entry_ts, f"fill {entry_px:.2f}", "#15803d", entry_px, marker=">")
            ax.axhline(entry_px, color="#15803d", lw=0.7, ls=":", alpha=0.7, zorder=4)
            ax.axhline(stop0, color="#64748b", lw=0.95, ls="--", zorder=5)
        if en_full is not None and ex_full is not None:
            atr_e = (
                float(atr2_full[en_full])
                if np.isfinite(atr2_full[en_full])
                else entry_px * 0.001
            )
            trail = chandelier_path(
                ltf["high"].to_numpy(dtype=float),
                atr2_full,
                en_full,
                ex_full,
                stop0,
                atr_e,
            )
            if en_i is not None:
                trail_x, trail_y = [], []
                for k, px in enumerate(trail):
                    pane_i = en_i + k
                    if 0 <= pane_i < nR:
                        trail_x.append(pane_i)
                        trail_y.append(float(px))
                if trail_x:
                    ax.step(trail_x, trail_y, where="post", color="#dc2626", lw=1.7, zorder=8)
        if ex_i is not None:
            mark(
                exit_ts,
                f"exit {ev.get('exit_type')} {exit_px:.2f}",
                "#0f172a",
                exit_px,
                marker="X",
            )
            ax.axvline(ex_i, color="#0f172a", lw=0.7, ls=":", alpha=0.55, zorder=4)

    ax.set_xlim(-0.8, nR - 0.2)
    ys = [float(right["low"].min()), float(right["high"].max()), zone_lo, zone_hi]
    if ev.get("entry_px") not in ("", None):
        ys.extend([float(ev["entry_px"]), float(ev.get("stop0") or zone_lo), float(ev.get("exit_px") or 0)])
    if len(trail):
        ys.extend([float(np.nanmin(trail)), float(np.nanmax(trail))])
    y0, y1 = min(ys), max(ys)
    pad = max((y1 - y0) * 0.10, 0.04)
    ax.set_ylim(y0 - pad, y1 + pad)
    _set_xticks(ax, list(r_ts), max_ticks=9, mode="2m")
    ax.set_ylabel("Price ($)", fontsize=9)
    ax.set_title(
        f"2-minute  ·  chandelier {CHANDELIER_MULT:g}×ATR  ·  {kind.replace('_', ' ').lower()}",
        fontsize=10,
        loc="left",
        pad=6,
    )
    ax.grid(True, axis="y", color="#e2e8f0", lw=0.6)
    ax.tick_params(axis="y", labelsize=8)

    sym = str(ev["symbol"])
    pnl = ev.get("pnl_pct")
    if pnl not in ("", None):
        sign = "+" if float(pnl) >= 0 else ""
        pnl_bit = f"   PnL {sign}{float(pnl):.3f}%   {ev.get('exit_type')}"
    else:
        pnl_bit = f"   {kind.replace('_', ' ')}"
    fig.suptitle(
        f"{sym}   {write_ts.strftime('%Y-%m-%d')}   2h zone-write × 2m chandelier {CHANDELIER_MULT:g}×ATR"
        f"{pnl_bit}",
        fontsize=13.2,
        fontweight="semibold",
        color="#0f172a",
        y=0.985,
    )
    fig.text(
        0.055,
        0.915,
        "Same unit on both Y-axes (dollars), not the same time scale. "
        "Left = 2-hour RTH candles (09:30-anchored; three 2h bars + a 30m close bar per session). "
        "Right = 2-minute candles from before the retest through the exit.",
        fontsize=8.2,
        color="#334155",
        ha="left",
        va="top",
    )
    hold = ev.get("hold_min")
    hold_s = f"{float(hold):.0f} min" if hold not in ("", None) else "—"
    fig.text(
        0.055,
        0.882,
        f"Write window {_fmt_clock(write_ts)} → {_fmt_clock(write_end)}  ·  "
        f"known {_fmt_clock(known_ts)}  ·  "
        f"timing {ev.get('timing_class') or '—'}  ·  "
        f"fill→exit hold {hold_s}  ·  "
        "chandelier ratchets after the 2m bar closes.",
        fontsize=8.0,
        color="#475569",
        ha="left",
        va="top",
    )
    handles = [
        Line2D([0], [0], color="#7c3aed", lw=1.4, label="2h write window"),
        Line2D([0], [0], color="#f59e0b", lw=6, alpha=0.35, label="2h High–Low zone"),
        Line2D([0], [0], color="#0284c7", lw=1, ls="--", label="2m retest"),
        Line2D([0], [0], color="#64748b", lw=1, ls="--", label="Initial stop (zone low)"),
        Line2D([0], [0], color="#dc2626", lw=1.4, label="Chandelier 3×ATR"),
        Line2D([0], [0], marker=">", color="#15803d", lw=0, label="Fill"),
        Line2D([0], [0], marker="X", color="#0f172a", lw=0, label="Exit / fail"),
    ]
    fig.legend(
        handles=handles, loc="lower center", ncol=7, frameon=False, fontsize=8, bbox_to_anchor=(0.5, 0.012)
    )
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=128, facecolor=fig.get_facecolor())
    plt.close(fig)
    return None


def _iso(val: Any) -> str:
    if val in ("", None):
        return ""
    try:
        return _ts(val).isoformat()
    except Exception:
        return str(val)


def write_events_csv(events: list[dict[str, Any]], path: Path) -> None:
    cols = [
        "symbol",
        "kind",
        "write_ts",
        "write_end_ts",
        "known_ts",
        "zone_lo",
        "zone_hi",
        "write_volume",
        "lookback_sessions",
        "leave_ts",
        "retest_ts",
        "entry_ts",
        "exit_ts",
        "entry_px",
        "exit_px",
        "stop0",
        "stop_final",
        "exit_type",
        "pnl_pct",
        "r_mult",
        "hold_min",
        "timing_class",
        "mins_after_write_close",
        "fill_vs_zone",
        "write_still_forming_at_fill",
        "write_eq_known",
        "split",
        "outcome",
        "daily_63d_maxvol_date",
        "daily_63d_maxvol",
        "write_day_is_daily_63d_max",
        "daily_63d_max_on_tape",
    ]
    rows = []
    for e in events:
        rec = {c: e.get(c, "") for c in cols}
        for k in ("write_ts", "write_end_ts", "known_ts", "leave_ts", "retest_ts", "entry_ts", "exit_ts"):
            rec[k] = _iso(e.get(k))
        rows.append(rec)
    pd.DataFrame(rows, columns=cols).to_csv(path, index=False)


def _book_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {"n": 0, "wins": 0, "wr": None, "avg": None, "pf": None}
    pnls = [float(t["pnl_pct"]) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gp = sum(wins)
    gl = abs(sum(losses))
    return {
        "n": len(trades),
        "wins": len(wins),
        "wr": 100.0 * len(wins) / len(pnls),
        "avg": float(np.mean(pnls)),
        "pf": (gp / gl) if gl > 0 else None,
    }


def pick_stories(
    trades: list[dict[str, Any]],
    fails: list[dict[str, Any]],
    events: Optional[list[dict[str, Any]]] = None,
) -> list[str]:
    stories: list[str] = []
    if not trades and not fails:
        return ["No 2m fills or failed retests printed on this tape under the freeze."]

    def fmt_trade(t: dict[str, Any]) -> str:
        sign = "+" if float(t["pnl_pct"]) >= 0 else ""
        return (
            f"{t['symbol']}: 2h write {_fmt_clock(_ts(t['write_ts']))} "
            f"(zone {float(t['zone_lo']):.2f}–{float(t['zone_hi']):.2f}) → "
            f"2m fill {_fmt_clock(_ts(t['entry_ts']))} at {float(t['entry_px']):.2f} "
            f"({t.get('fill_vs_zone')}, {t.get('timing_class')}, "
            f"{float(t.get('mins_after_write_close') or 0):.0f} min after the 2h close) → "
            f"{t.get('exit_type')} {_fmt_clock(_ts(t['exit_ts']))} "
            f"{sign}{float(t['pnl_pct']):.3f}% in {float(t['hold_min']):.0f} min."
        )

    # Prefer concrete spread: next-2h win, later-day, fail, during-write if any.
    ranked = sorted(
        trades,
        key=lambda t: (
            0 if t.get("timing_class") == "NEXT_2H" else 1,
            0 if float(t.get("pnl_pct") or 0) > 0 else 1,
            _ts(t["entry_ts"]),
        ),
    )
    seen_sym: set[str] = set()
    for t in ranked:
        if t["symbol"] in seen_sym and len(stories) >= 2:
            continue
        stories.append(fmt_trade(t))
        seen_sym.add(str(t["symbol"]))
        if len(stories) >= 3:
            break
    # Add a loser if we only have winners so far.
    if trades and all(float(t["pnl_pct"]) > 0 for t in trades[:1]) and any(
        float(t["pnl_pct"]) <= 0 for t in trades
    ):
        loss = min(trades, key=lambda t: float(t["pnl_pct"]))
        line = fmt_trade(loss)
        if line not in stories:
            stories.append(line)
    if fails:
        f = fails[0]
        stories.append(
            f"{f['symbol']}: 2h write {_fmt_clock(_ts(f['write_ts']))} "
            f"(zone {float(f['zone_lo']):.2f}–{float(f['zone_hi']):.2f}) → "
            f"2m tagged at {_fmt_clock(_ts(f['retest_ts']))} then closed through the zone low "
            f"({f.get('timing_class') or 'timing n/a'}) — no buy."
        )
    evs = events or []
    for kind, label in (
        ("NO_RETEST", "left the zone after it was known; 2m never tagged it again — no buy"),
        ("NO_LEAVE", "price never closed above the 2h zone after it was known — no 2m setup"),
    ):
        hit = next((e for e in evs if e.get("kind") == kind), None)
        if hit is None:
            continue
        stories.append(
            f"{hit['symbol']}: 2h write {_fmt_clock(_ts(hit['write_ts']))} "
            f"(zone {float(hit['zone_lo']):.2f}–{float(hit['zone_hi']):.2f}, "
            f"known {_fmt_clock(_ts(hit['known_ts']))}) — {label}."
        )
        if len(stories) >= 5:
            break
    return stories[:5]


def write_docs(
    *,
    cov: list[dict[str, Any]],
    events: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    stories: list[str],
    n_charts: int,
) -> None:
    book = _book_stats(trades)
    is_tr = [t for t in trades if t.get("split") == "IS"]
    oos_tr = [t for t in trades if t.get("split") == "OOS"]
    is_b = _book_stats(is_tr)
    oos_b = _book_stats(oos_tr)
    n_zones = sum(int(c.get("n_zones") or 0) for c in cov)
    kinds: dict[str, int] = {}
    for e in events:
        kinds[str(e.get("kind") or "?")] = kinds.get(str(e.get("kind") or "?"), 0) + 1
    timing: dict[str, int] = {}
    for t in trades:
        timing[str(t.get("timing_class") or "?")] = timing.get(str(t.get("timing_class") or "?"), 0) + 1
    forming = sum(1 for t in trades if t.get("write_still_forming_at_fill") in (True, "True", "yes"))
    daily_match = sum(1 for e in events if e.get("write_day_is_daily_63d_max") == "yes")
    daily_off = sum(1 for e in events if e.get("daily_63d_max_on_tape") == "no")

    pf_s = f"{book['pf']:.2f}" if book["pf"] is not None else "—"
    wr_s = f"{book['wr']:.1f}%" if book["wr"] is not None else "—"
    avg_s = f"{book['avg']:.3f}%" if book["avg"] is not None else "—"

    baseline = f"""# BASELINE — 2h zone-write × 2m chandelier — `{STAMP_NAME}`

**System:** Volume Zone (**VZ**) analog on 2-hour Regular Trading Hours (**RTH**) bars + 2-minute execution (research pictures). **Not** DailyRun. **Not** gold. Does **not** mutate house VZ or `intraday_htf_retest_20260916`.

This is **not** the High Time Frame (**HTF**) pivot-break book on the same stamp family (`intraday_htf_retest_20260916` 2h×2m is break-of-high, not a volume zone).

## What you asked

> {ORIGINAL_REQUEST}

## In plain English

{PLAIN_ENGLISH}

## Freeze (one definition — do not shop)

| Knob | Value |
|------|--------|
| Zone writer | 2h RTH bars, 09:30-anchored left-label (three 2h bars + a 30-minute 15:30–16:00 close bar) |
| Volume identity | House VZ-style unique **expanding** max-volume 2h winner (first time a 2h bar is the highest volume in available history) |
| Target lookback | ~3 months = **{TARGET_LOOKBACK_SESSIONS} sessions**. Yahoo 1m tape is shorter — see Coverage |
| Warmup | First **{MIN_WRITE_SESSIONS} sessions** seed the first identity; no zone before that |
| Zone band | That 2h bar **High–Low** (house VZ HL; no padding / no Open–Close band) |
| Known-at | Close of the 2h bar when that winner first becomes the expanding max. No 2m signal until then |
| Leave | First 2m **close above** zone high after known-at |
| Buy | First later 2m bar whose range tags the zone from above; fill = **next 2m open** |
| Fail / no buy | 2m tags the zone and **closes below** zone low |
| Frequency | First retest (or first fail) per zone |
| Entry cutoff | No fill at/after 15:45 ET |
| Initial stop | Zone low (if that sits at/above the fill: fill − {INIT_STOP_ATR_MULT} × 2m ATR) |
| Exit | **`trail_chandelier_3` on 2m** — `max(initial, prior-bar running high − {CHANDELIER_MULT:g} × 2m ATR)`. Never down. TIME flatten at 15:55 ET open; else STOP; else last-bar EOD_FLAT |
| Side | Long only |
| Costs | 0 bps (research, no slippage) |
| Universe | PaulTwenty ∩ stored 1m, plus UNH if present |
| Daily context (not a knob) | Trailing {DAILY_LOOKBACK_SESSIONS}-session **daily** max-volume date from `data/newdata/data` — report-only honesty vs true ~3-month daily volume |

## Coverage (honest)

Yahoo 1-minute parquet under `data/intraday/1m/` is typically **~Jul 23–Sep 16 2026 (~{min((c.get('n_sessions') or 0) for c in cov) if cov else 0}–{max((c.get('n_sessions') or 0) for c in cov) if cov else 0} sessions)** — **short of 63 sessions**. There is no 1h store. So a true 3-month **2h** max-volume identity cannot be computed from 1m alone.

What we did: write the zone from **best available 2h history** (expanding window on the 1m-resampled 2h tape) and **label the lookback**. Daily {DAILY_LOOKBACK_SESSIONS}-session max-volume is a side column: {daily_match} zone-write day(s) equal the daily 63-session max-vol day; {daily_off} event(s) have that daily max-vol day **off** the 1m tape.

| Symbol | 1m bars | Sessions | 2h bars | Zones | First | Last |
|--------|--------:|---------:|--------:|------:|-------|------|
"""
    for c in cov:
        baseline += (
            f"| {c['symbol']} | {c.get('n_1m', 0)} | {c.get('n_sessions', 0)} | "
            f"{c.get('n_2h', 0)} | {c.get('n_zones', 0)} | {c.get('tape_first', '')} | {c.get('tape_last', '')} |\n"
        )

    baseline += f"""
## Event counts

- Zones written: **{n_zones}**
- Event kinds: {", ".join(f"{k}={v}" for k, v in sorted(kinds.items()))}
- Filled trades: **{book['n']}** · wins {book['wins']} · WR {wr_s} · Avg PnL% {avg_s} · PF {pf_s}
- Fill timing vs 2h close: {", ".join(f"{k}={v}" for k, v in sorted(timing.items())) or "—"}
- Fills while the 2h write bar was still forming: **{forming}** (should be 0 — we gate on the 2h close)

## Split

Canonical shop IS (`entry_date < 2024-01-01`) is **N/A** — Yahoo 1m here is Jul–Sep 2026 only.

Short-tape chronological split (labeled, not silent): **IS** = `entry_date < 2026-09-02`; **OOS** = `entry_date >= 2026-09-02`. OOS is report-only. If OOS softens vs IS → **HOLD**, do not retune.

| Slice | N | WR | Avg PnL% |
|-------|--:|----|----------|
| IS | {is_b['n']} | {f"{is_b['wr']:.1f}%" if is_b['wr'] is not None else "—"} | {f"{is_b['avg']:.3f}%" if is_b['avg'] is not None else "—"} |
| OOS | {oos_b['n']} | {f"{oos_b['wr']:.1f}%" if oos_b['wr'] is not None else "—"} | {f"{oos_b['avg']:.3f}%" if oos_b['avg'] is not None else "—"} |

## Selection bias

Chart picks are a **stratified** mix of winners, losers, and failed retests (not winners-only). Judging KEEP/DISMISS from this short tape + after seeing the table is still in-sample. Research pictures only.

## Promotion

Research candidate. **Not** gold. **Not** DailyRun. {n_charts} gallery pictures.
"""
    (STAMP / "BASELINE.md").write_text(baseline, encoding="utf-8")

    hyp = f"""# HYPOTHESIS — `{STAMP_NAME}`

**Product owner (PO)–aligned process:** pictures + a light event list, not a DailyRun adopt.

| Field | Fill in |
|-------|---------|
| System / prefix | VZ analog (2h write / 2m execute) — research only |
| Baseline stamp | `{STAMP_NAME}` |
| Universe | PaulTwenty ∩ 1m store + UNH |
| **Evidence** | Paul ask: show how the 2-hour zone-writing window affects the 2-minute buy + exit. Sibling 4h 3-month high-volume pictures live in a **different** folder (`vz4h_3m_highvol_20260916`) and were not edited. |
| **Hypothesis** | The 2h bar that writes the High–Low Volume Zone (VZ) band is visible on the left; the 2m bounce / retest and chandelier exit on the right will often disagree in **time** (late vs next 2h vs later day) even when the **price** fill sits near the band. |
| **Single knob** | Timeframe pair + zone definition frozen (2h max-vol HL → 2m retest). Not an exit horse-race. |
| Frozen settings | See `BASELINE.md`. Exit = chandelier 3× Average True Range (ATR) on 2m. |
| Alternatives | None shopped. |
| Candidate stamps | `{STAMP_NAME}` (pictures) |
| Metrics | Light book on filled events only (N, WR, Avg PnL%, PF) plus IS/OOS rows. Quality over count. Not max single-trade PnL. |
| **Trade-diff HTML** | N/A — one freeze, no control-vs-candidate Closed pair |
| ToS before / after | N/A |
| **Decision** | Research pictures. No KEEP / gold / DailyRun. |
| Reviewer | |
| PO sign-off | no |
| Reconcile freeze / re-baseline done | no |

## Decision checklist

- [x] Evidence was a real Paul ask (see request block)
- [x] Only one freeze (no exit shopping)
- [ ] Trade-diff HTML — N/A (not a Closed A/B)
- [x] Charts meant to look like write-window → 2m fill/exit
- [ ] Drawdown / reconcile — not a promotion candidate
- [ ] Adopt: no

## Stories from this run

"""
    for s in stories:
        hyp += f"- {s}\n"
    (STAMP / "HYPOTHESIS.md").write_text(hyp, encoding="utf-8")


def write_gallery(
    *,
    rows: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    events: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    cov: list[dict[str, Any]],
    stories: list[str],
) -> None:
    book = _book_stats(trades)
    kinds: dict[str, int] = {}
    for e in events:
        kinds[str(e.get("kind") or "?")] = kinds.get(str(e.get("kind") or "?"), 0) + 1
    timing: dict[str, int] = {}
    for t in trades:
        timing[str(t.get("timing_class") or "?")] = timing.get(str(t.get("timing_class") or "?"), 0) + 1
    forming = sum(1 for t in trades if t.get("write_still_forming_at_fill") in (True, "True", "yes"))
    fill_loc: dict[str, int] = {}
    for t in trades:
        fill_loc[str(t.get("fill_vs_zone") or "?")] = fill_loc.get(str(t.get("fill_vs_zone") or "?"), 0) + 1

    n_ok = sum(1 for r in rows if r.get("png"))
    head_cols = [
        ("#", "num"),
        ("symbol", "text"),
        ("kind", "text"),
        ("zone-write 2h", "date"),
        ("2h close / known", "date"),
        ("2m fill", "date"),
        ("exit", "text"),
        ("PnL%", "num"),
        ("hold min", "num"),
        ("timing vs 2h", "text"),
        ("mins after 2h close", "num"),
        ("fill vs zone", "text"),
        ("zone lo", "num"),
        ("zone hi", "num"),
        ("daily 63d max-vol day", "date"),
        ("write = daily 63d max?", "text"),
        ("daily max on 1m tape?", "text"),
        ("split", "text"),
        ("chart", "text"),
    ]
    ths = "".join(sortable_th(lab, typ) for lab, typ in head_cols)
    body = []
    for r in rows:
        e = r["event"]
        link = (
            f'<a href="#{html_mod.escape(r["anchor"])}">view</a> · '
            f'<a href="{html_mod.escape(r["rel"])}">png</a>'
            if r.get("png")
            else "skipped"
        )
        pnl = e.get("pnl_pct")
        if pnl not in ("", None):
            cls = "win" if float(pnl) > 0 else "loss"
            pnl_s = f"{float(pnl):.3f}"
        else:
            cls = "flat"
            pnl_s = "—"
        hold = e.get("hold_min")
        hold_s = f"{float(hold):.0f}" if hold not in ("", None) else "—"
        mins = e.get("mins_after_write_close")
        mins_s = f"{float(mins):.0f}" if mins not in ("", None) else "—"
        body.append(
            "<tr class='{cls}'>"
            "<td>{n}</td><td>{sym}</td><td>{kind}</td>"
            "<td>{w}</td><td>{k}</td><td>{f}</td><td>{xt}</td>"
            "<td>{pnl}</td><td>{hm}</td><td>{tc}</td><td>{mn}</td>"
            "<td>{fv}</td><td>{lo:.2f}</td><td>{hi:.2f}</td>"
            "<td>{dd}</td><td>{dm}</td><td>{ot}</td><td>{sp}</td><td>{link}</td></tr>".format(
                cls=cls,
                n=r["n"],
                sym=html_mod.escape(str(e["symbol"])),
                kind=html_mod.escape(str(e.get("kind") or "")),
                w=html_mod.escape(_fmt_clock(_ts(e["write_ts"]))),
                k=html_mod.escape(_fmt_clock(_ts(e["known_ts"]))),
                f=html_mod.escape(_fmt_clock(_ts(e["entry_ts"])) if e.get("entry_ts") else "—"),
                xt=html_mod.escape(str(e.get("exit_type") or e.get("kind") or "—")),
                pnl=pnl_s,
                hm=hold_s,
                tc=html_mod.escape(str(e.get("timing_class") or "—")),
                mn=mins_s,
                fv=html_mod.escape(str(e.get("fill_vs_zone") or "—")),
                lo=float(e["zone_lo"]),
                hi=float(e["zone_hi"]),
                dd=html_mod.escape(str(e.get("daily_63d_maxvol_date") or "—")),
                dm=html_mod.escape(str(e.get("write_day_is_daily_63d_max") or "—")),
                ot=html_mod.escape(str(e.get("daily_63d_max_on_tape") or "—")),
                sp=html_mod.escape(str(e.get("split") or "—")),
                link=link,
            )
        )

    all_head = [
        ("symbol", "text"),
        ("kind", "text"),
        ("zone-write 2h", "date"),
        ("2m fill", "date"),
        ("exit", "text"),
        ("PnL%", "num"),
        ("hold min", "num"),
        ("timing vs 2h", "text"),
        ("mins after 2h close", "num"),
        ("fill vs zone", "text"),
        ("split", "text"),
        ("outcome", "text"),
    ]
    all_ths = "".join(sortable_th(lab, typ) for lab, typ in all_head)
    all_body = []
    for e in events:
        pnl = e.get("pnl_pct")
        pnl_s = f"{float(pnl):.3f}" if pnl not in ("", None) else "—"
        if pnl not in ("", None):
            cls = "win" if float(pnl) > 0 else "loss"
        else:
            cls = "flat"
        hold = e.get("hold_min")
        hold_s = f"{float(hold):.0f}" if hold not in ("", None) else "—"
        mins = e.get("mins_after_write_close")
        mins_s = f"{float(mins):.0f}" if mins not in ("", None) else "—"
        all_body.append(
            "<tr class='{cls}'><td>{sym}</td><td>{kind}</td><td>{w}</td><td>{f}</td>"
            "<td>{xt}</td><td>{pnl}</td><td>{hm}</td><td>{tc}</td><td>{mn}</td>"
            "<td>{fv}</td><td>{sp}</td><td>{oc}</td></tr>".format(
                cls=cls,
                sym=html_mod.escape(str(e["symbol"])),
                kind=html_mod.escape(str(e.get("kind") or "")),
                w=html_mod.escape(_fmt_clock(_ts(e["write_ts"]))),
                f=html_mod.escape(_fmt_clock(_ts(e["entry_ts"])) if e.get("entry_ts") else "—"),
                xt=html_mod.escape(str(e.get("exit_type") or "—")),
                pnl=pnl_s,
                hm=hold_s,
                tc=html_mod.escape(str(e.get("timing_class") or "—")),
                mn=mins_s,
                fv=html_mod.escape(str(e.get("fill_vs_zone") or "—")),
                sp=html_mod.escape(str(e.get("split") or "—")),
                oc=html_mod.escape(str(e.get("outcome") or "")),
            )
        )

    skip_html = ""
    if skipped:
        items = "".join(
            f"<li><code>{html_mod.escape(s['id'])}</code> — {html_mod.escape(s['reason'])}</li>"
            for s in skipped
        )
        skip_html = f"<h2>Skipped charts</h2><ul>{items}</ul>"

    cards = []
    for r in rows:
        if not r.get("png"):
            continue
        e = r["event"]
        pnl = e.get("pnl_pct")
        if pnl not in ("", None):
            sign = "+" if float(pnl) >= 0 else ""
            title_bit = f"{sign}{float(pnl):.3f}% · {html_mod.escape(str(e.get('exit_type') or ''))}"
        else:
            title_bit = html_mod.escape(str(e.get("kind") or ""))
        cards.append(
            f'<article class="card" id="{html_mod.escape(r["anchor"])}">'
            f"<h3>{html_mod.escape(str(e['symbol']))} · "
            f"{html_mod.escape(_ts(e['write_ts']).strftime('%Y-%m-%d'))} · {title_bit}</h3>"
            f'<p class="cap">Write {_fmt_clock(_ts(e["write_ts"]))} → known {_fmt_clock(_ts(e["known_ts"]))} · '
            f"zone {float(e['zone_lo']):.2f}–{float(e['zone_hi']):.2f} · "
            f"timing {html_mod.escape(str(e.get('timing_class') or '—'))}</p>"
            f'<img src="{html_mod.escape(r["rel"])}" alt="{html_mod.escape(r["anchor"])}" loading="lazy"/>'
            f'<p class="cap"><a href="#top">back to table</a></p></article>'
        )

    wr_s = f"{book['wr']:.1f}%" if book["wr"] is not None else "—"
    avg_s = f"{book['avg']:.3f}%" if book["avg"] is not None else "—"
    pf_s = f"{book['pf']:.2f}" if book["pf"] is not None else "—"
    story_html = "".join(f"<li>{html_mod.escape(s)}</li>" for s in stories)
    cov_note = (
        f"{len(cov)} names · 1m typically Jul–Sep 2026 · "
        f"zones use expanding 2h history after {MIN_WRITE_SESSIONS} sessions "
        f"(target {TARGET_LOOKBACK_SESSIONS} sessions / ~3 months; tape is shorter)."
    )
    kind_s = ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())) or "—"
    timing_s = ", ".join(f"{k}={v}" for k, v in sorted(timing.items())) or "—"
    loc_s = ", ".join(f"{k}={v}" for k, v in sorted(fill_loc.items())) or "—"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>2h zone-write × 2m chandelier — {STAMP_NAME}</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:24px;color:#0f172a;background:#f8fafc;line-height:1.45}}
h1{{font-size:1.4rem;margin:0 0 8px}}
h2{{font-size:1.12rem;margin:28px 0 10px}}
h3{{font-size:1.02rem;margin:0 0 6px}}
.ask,.plain{{max-width:980px;padding:12px 14px;border-radius:8px;margin:12px 0}}
.ask{{background:#fff7ed;border:1px solid #fdba74}}
.plain{{background:#ecfeff;border:1px solid #67e8f9}}
.badge{{display:inline-block;background:#fef3c7;color:#92400e;padding:2px 8px;border-radius:4px;font-size:.85rem;font-weight:600}}
table.sortable{{border-collapse:collapse;width:100%;background:#fff;margin:8px 0 16px;font-size:.86rem}}
table.sortable th,table.sortable td{{border:1px solid #e2e8f0;padding:8px 10px;text-align:left}}
table.sortable th{{background:#f1f5f9}}
tr.win td{{background:#f0fdf4}}
tr.loss td{{background:#fff1f2}}
.note,.meta{{font-size:.92rem;color:#475569;max-width:980px}}
.card{{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:12px 14px;margin:22px 0}}
.card img{{width:100%;max-width:1180px;height:auto;border:1px solid #e2e8f0;border-radius:6px}}
.cap{{font-size:.86rem;color:#475569;margin:4px 0 8px}}
{SORT_CSS}
</style>
</head>
<body>
<p id="top" class="badge">Research only · not gold · not DailyRun</p>
<h1>2-hour zone-write window × 2-minute buy + chandelier exit</h1>
<p class="meta">Stamp <code>{html_mod.escape(STAMP_NAME)}</code> · {html_mod.escape(cov_note)}
Rendered {n_ok} of {len(rows)} gallery rows. Sibling 4-hour 3-month pictures were left in
<code>vz4h_3m_highvol_20260916</code> and were not edited.</p>

<div class="ask">
<strong>What you asked</strong>
<blockquote>{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
</div>
<div class="plain">
<strong>In plain English</strong>
<p>{html_mod.escape(PLAIN_ENGLISH)}</p>
<p>Volume Zone (<strong>VZ</strong>) here is the house analog: a high-volume bar writes a
High–Low band. Regular Trading Hours (<strong>RTH</strong>) = 09:30–16:00 ET.
Average True Range (<strong>ATR</strong>) = typical-bar-range (Wilder 14). The chandelier sits
<code>highest high since entry − 3 × 2m ATR</code> and never moves down.
This is <em>not</em> the High Time Frame (HTF) pivot-break 2h×2m book — that one breaks a swing high.</p>
</div>

<h2>How the 2h write maps onto the 2m tape</h2>
<p class="note">Filled trades N={book['n']} · WR {html_mod.escape(wr_s)} · Avg PnL% {html_mod.escape(avg_s)} ·
PF {html_mod.escape(pf_s)} (light event book, not a DailyRun reconcile).
Event mix: {html_mod.escape(kind_s)}.
Fill timing vs 2h close: {html_mod.escape(timing_s)}.
Fill location vs zone: {html_mod.escape(loc_s)}.
Fills while the 2h write bar was still forming: <strong>{forming}</strong> (gated on the 2h close — should be 0).
Yahoo 1m is ~2 months, so “3-month high volume” on 2h is the <em>available</em> 2h history, labeled as such.
The trailing 63-session <em>daily</em> max-volume date is a honesty column — often that day is off this 1m tape.
Many first zones share a <strong>known</strong> stamp near the 20-session warmup (often 2026-08-19 11:30 ET):
the 2h write bar already printed in late July, but we do not hunt a 2m buy until that identity exists.
New volume-record 2h bars (<code>write_eq_known</code>) are the clean same-day write → next-2h fill stories.
No 2m close-through failed retests printed under this freeze — the no-buy rows are leave-without-tag or never-left.</p>
<ul>{story_html}</ul>

<p class="note">Click column headers to sort. Gallery rows are a stratified mix of bounce-and-go,
stopped-out, and failed retests — not winners only. Both Y-axes are dollars on different time scales.</p>

<h2>Gallery trades / fails</h2>
<table class="sortable">
<thead><tr>{ths}</tr></thead>
<tbody>
{''.join(body)}
</tbody>
</table>

{skip_html}

<h2>Charts</h2>
{''.join(cards)}

<h2>Full event list</h2>
<p class="note">Every zone on the universe, including no-leave / no-retest. Click headers to sort.</p>
<table class="sortable">
<thead><tr>{all_ths}</tr></thead>
<tbody>
{''.join(all_body)}
</tbody>
</table>

{SORT_JS}
</body>
</html>
"""
    GALLERY.write_text(html, encoding="utf-8")


def main() -> int:
    STAMP.mkdir(parents=True, exist_ok=True)
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    syms = universe()
    print(f"{STAMP_NAME} universe N={len(syms)}: {', '.join(syms)}")
    cov: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    packs: dict[str, dict[str, Any]] = {}
    for sym in syms:
        pack = scan_symbol(sym)
        evs = list(pack.get("events") or [])
        events.extend(evs)
        cov.append({k: pack.get(k) for k in (
            "symbol", "n_1m", "n_sessions", "tape_first", "tape_last", "n_2h", "n_zones", "skip"
        )})
        packs[sym] = pack
        print(
            f"  {sym}: 1m={pack.get('n_1m')} sess={pack.get('n_sessions')} "
            f"2h={pack.get('n_2h')} zones={pack.get('n_zones')} events={len(evs)} "
            f"{pack.get('skip') or ''}".rstrip()
        )

    trades = [e for e in events if e.get("kind") == "TRADE"]
    fails = [e for e in events if e.get("kind") == "FAIL_RETEST"]
    stories = pick_stories(trades, fails, events)
    chosen = pick_chart_events(events)
    print(f"events={len(events)} trades={len(trades)} fails={len(fails)} charts={len(chosen)}")

    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for i, ev in enumerate(chosen, start=1):
        sym = str(ev["symbol"]).upper()
        anchor_ts = ev.get("entry_ts") or ev.get("retest_ts") or ev["write_ts"]
        ed = _ts(anchor_ts).strftime("%Y-%m-%d")
        hhmm = _ts(anchor_ts).strftime("%H%M")
        stem = f"{i:02d}_{sym}_{ed}_{hhmm}"
        png = CHART_DIR / f"{stem}.png"
        reason = None
        pack = packs.get(sym)
        if not pack or pack.get("htf") is None:
            reason = "missing bars for chart"
        else:
            reason = render_event(ev, pack, png)
        rec = {
            "n": i,
            "event": ev,
            "anchor": stem,
            "rel": f"charts/{stem}.png",
            "png": None if reason else png.name,
        }
        if reason:
            skipped.append({"id": stem, "reason": reason})
            print(f"  SKIP {stem}: {reason}")
            if png.exists():
                try:
                    png.unlink()
                except OSError:
                    pass
        else:
            print(f"  OK   {stem}")
        rows.append(rec)

    write_events_csv(events, STAMP / "events.csv")
    write_docs(
        cov=cov,
        events=events,
        trades=trades,
        stories=stories,
        n_charts=sum(1 for r in rows if r.get("png")),
    )
    write_gallery(
        rows=rows,
        skipped=skipped,
        events=events,
        trades=trades,
        cov=cov,
        stories=stories,
    )
    manifest = {
        "stamp": STAMP_NAME,
        "n_symbols": len(syms),
        "n_events": len(events),
        "n_trades": len(trades),
        "n_fail_retest": len(fails),
        "n_rendered": sum(1 for r in rows if r.get("png")),
        "n_skipped": len(skipped),
        "gallery": str(GALLERY.as_posix()),
        "exit": f"trail_chandelier_{CHANDELIER_MULT:g}",
        "stories": stories,
        "skipped": skipped,
    }
    (STAMP / "summary.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(f"gallery {GALLERY}")
    print(f"rendered {manifest['n_rendered']} / {len(rows)}; skipped {len(skipped)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
