#!/usr/bin/env python3
"""Side-by-side 4h zone + 1m chandelier charts for the frozen HTF-retest stamp.

Research only. Does not change the backtest freeze. Reads trades.csv and
replays trail_chandelier_3 with the same engine helpers.

Usage:
  python tools/intraday_htf_retest_charts_4h_1m_20260916.py
"""
from __future__ import annotations

import html as html_mod
import json
import sys
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
    PIVOT_K,
    RETEST_ATR_MULT,
    fractal_pivots,
    resample_from_rth_open,
    rth_filter,
    wilder_atr,
)

STAMP = ROOT / "drive" / "paul_experiments" / "intraday_htf_retest_20260916"
TRADES_CSV = STAMP / "trades.csv"
CHART_DIR = STAMP / "charts"
GALLERY = STAMP / "charts_4h_1m_chandelier3.html"
ARM = "trail_chandelier_3"
HTF = "4h"
LTF = "1m"

ORIGINAL_REQUEST = (
    "draw me some side by side charts showing the 4hr charts with multi-touch "
    "zones and the 1m charts with the break and retest using trail_chandelier_3 "
    "maybe all 37 charts if possible"
)

PLAIN_ENGLISH = (
    "Each picture is one trade from the 4-hour × 1-minute chandelier book. "
    "The left pane is the slower 4-hour chart: the broken swing-high line and "
    "the band around it that price poked more than once (a multi-touch zone). "
    "The right pane is the 1-minute tape: price breaks that line, comes back "
    "to tap it (retest), we buy the next minute’s open, and the stop walks up "
    "as a chandelier — highest high since entry minus 3 typical 1-minute ranges, "
    "only after a bar closes. Research pictures only; the backtest numbers were "
    "not changed."
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
    t = _ts(t)
    return t.strftime("%Y-%m-%d %H:%M ET")


def load_arm_trades() -> list[dict[str, Any]]:
    df = pd.read_csv(TRADES_CSV)
    sub = df[(df["htf"] == HTF) & (df["ltf"] == LTF) & (df["arm"] == ARM)].copy()
    sub = sub.sort_values(["entry_ts", "symbol"]).reset_index(drop=True)
    return sub.to_dict(orient="records")


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
        if mode == "4h":
            labels.append(t.strftime("%b %d\n%H:%M"))
        else:
            labels.append(t.strftime("%H:%M"))
    ax.set_xticks(idxs)
    ax.set_xticklabels(labels, fontsize=8)


def chandelier_stops(
    highs: np.ndarray,
    atr: np.ndarray,
    entry_i: int,
    exit_i: int,
    stop0: float,
    atr_fallback: float,
) -> np.ndarray:
    """Per-bar chandelier stop (updates after prior bar close). Same as engine."""
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
            stop = max(stop, run_high - CHANDELIER_N * atr_j)
        out[j - entry_i] = stop
    return out


def nearby_4h_touches(
    htf: pd.DataFrame,
    level: float,
    band: float,
    break_ts: pd.Timestamp,
) -> list[dict[str, Any]]:
    """Confirmed 4h swing highs plus any 4h bar high that tagged the zone."""
    if htf is None or htf.empty:
        return []
    highs = htf["high"].to_numpy(dtype=float)
    lows = htf["low"].to_numpy(dtype=float)
    ts = pd.to_datetime(htf["ts"], utc=True).dt.tz_convert(ET)
    k = PIVOT_K["4h"]
    raw = fractal_pivots(highs, lows, k=k)
    piv_idx = {i for kind, i in raw if kind == "H"}
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for i, (h, t) in enumerate(zip(highs, ts)):
        if not np.isfinite(h):
            continue
        if abs(h - level) > band * 1.25 and not (level - band <= h <= level + band * 2):
            # still keep a bar whose high is inside the zone
            if not (level - band <= h <= level + band):
                continue
        if not (level - band * 1.5 <= h <= level + band * 1.5):
            continue
        if pd.Timestamp(t) > break_ts + pd.Timedelta(hours=8):
            continue
        kind = "swing" if i in piv_idx else "tag"
        if i in seen:
            continue
        seen.add(i)
        out.append({"i": i, "ts": pd.Timestamp(t), "px": float(h), "kind": kind})
    return out


def slice_4h(htf: pd.DataFrame, break_ts: pd.Timestamp, exit_ts: pd.Timestamp) -> pd.DataFrame:
    ts = pd.to_datetime(htf["ts"], utc=True).dt.tz_convert(ET)
    br = ts.searchsorted(break_ts, side="left")
    if br >= len(htf):
        br = len(htf) - 1
    # enough history for multi-touch; 4h has 2 bars/session
    lo = max(0, int(br) - 22)
    ex = ts.searchsorted(exit_ts, side="right")
    hi = min(len(htf), max(int(br) + 4, int(ex) + 2))
    return htf.iloc[lo:hi].reset_index(drop=True)


def slice_1m(
    df1: pd.DataFrame,
    *,
    break_ts: pd.Timestamp,
    retest_ts: pd.Timestamp,
    exit_ts: pd.Timestamp,
) -> pd.DataFrame:
    ts = pd.to_datetime(df1["ts"], utc=True).dt.tz_convert(ET)
    start = retest_ts - pd.Timedelta(minutes=35)
    if break_ts >= retest_ts - pd.Timedelta(minutes=120):
        start = min(start, break_ts - pd.Timedelta(minutes=15))
    end = exit_ts + pd.Timedelta(minutes=8)
    mask = (ts >= start) & (ts <= end)
    return df1.loc[mask].reset_index(drop=True)


def _nearest_idx(times: Any, target: pd.Timestamp, *, slop_min: float = 6.0) -> Optional[int]:
    """Nearest bar by clock time. Avoids ns-vs-us .asi8 mismatches."""
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


def render_trade(
    trade: dict[str, Any],
    cache: dict[str, dict[str, Any]],
    out_png: Path,
) -> Optional[str]:
    """Return skip reason or None on success."""
    sym = str(trade["symbol"]).upper()
    if sym not in cache:
        raw = read_1m(sym, DEFAULT_1M_DIR)
        df1 = rth_filter(raw)
        if df1 is None or df1.empty:
            return "no 1m bars in store"
        df1 = df1.copy()
        df1["end_ts"] = df1["ts"] + pd.Timedelta(minutes=1)
        htf = resample_from_rth_open(df1, 240)
        arr_h = df1["high"].to_numpy(dtype=float)
        arr_l = df1["low"].to_numpy(dtype=float)
        arr_c = df1["close"].to_numpy(dtype=float)
        atr1 = wilder_atr(arr_h, arr_l, arr_c)
        cache[sym] = {"df1": df1, "htf": htf, "atr1": atr1}
    pack = cache[sym]
    df1: pd.DataFrame = pack["df1"]
    htf: pd.DataFrame = pack["htf"]
    atr1: np.ndarray = pack["atr1"]
    if df1.empty:
        return "empty 1m after RTH filter"

    level = float(trade["level"])
    htf_atr = float(trade["htf_atr"])
    band = RETEST_ATR_MULT * htf_atr if htf_atr > 0 else level * 0.002
    break_ts = _ts(trade["break_ts"])
    retest_ts = _ts(trade["retest_ts"])
    entry_ts = _ts(trade["entry_ts"])
    exit_ts = _ts(trade["exit_ts"])
    entry_px = float(trade["entry_px"])
    exit_px = float(trade["exit_px"])
    stop0 = float(trade["stop0"])
    stop_final = float(trade["stop_final"])
    pnl = float(trade["pnl_pct"])
    exit_type = str(trade["exit_type"])

    left = slice_4h(htf, break_ts, exit_ts)
    right = slice_1m(df1, break_ts=break_ts, retest_ts=retest_ts, exit_ts=exit_ts)
    if right.empty or len(right) < 3:
        return f"missing 1m bars around retest/exit ({_fmt_clock(retest_ts)})"
    if left.empty or len(left) < 3:
        return "not enough 4h bars around the break"

    full_ts = pd.to_datetime(df1["ts"], utc=True).dt.tz_convert(ET)
    r_ts = pd.to_datetime(right["ts"], utc=True).dt.tz_convert(ET)
    entry_i_full = _nearest_idx(full_ts, entry_ts, slop_min=2.0)
    exit_i_full = _nearest_idx(full_ts, exit_ts, slop_min=2.0)
    if entry_i_full is None:
        return f"entry bar missing on 1m ({_fmt_clock(entry_ts)})"
    if exit_i_full is None:
        return f"exit bar missing on 1m ({_fmt_clock(exit_ts)})"

    atr_e = float(atr1[entry_i_full]) if np.isfinite(atr1[entry_i_full]) else entry_px * 0.001
    trail = chandelier_stops(
        df1["high"].to_numpy(dtype=float),
        atr1,
        entry_i_full,
        exit_i_full,
        stop0,
        atr_e,
    )

    touches = nearby_4h_touches(htf, level, band, break_ts)
    l_ts = pd.to_datetime(left["ts"], utc=True).dt.tz_convert(ET)
    htf_ts = pd.to_datetime(htf["ts"], utc=True).dt.tz_convert(ET)
    left_i0 = _nearest_idx(htf_ts, _ts(l_ts.iloc[0]), slop_min=250.0) or 0

    fig, axes = plt.subplots(1, 2, figsize=(16.6, 7.55), facecolor="#f8fafc")
    fig.subplots_adjust(left=0.055, right=0.985, top=0.76, bottom=0.18, wspace=0.18)

    # ---- left 4h ----
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
    ax.axhline(level, color="#b45309", lw=1.35, zorder=4)
    ax.axhline(level - band, color="#f59e0b", lw=0.7, ls="--", alpha=0.8, zorder=4)
    ax.axhline(level + band, color="#f59e0b", lw=0.7, ls="--", alpha=0.8, zorder=4)
    for tch in touches:
        xi = tch["i"] - left_i0
        if 0 <= xi < nL:
            marker = "D" if tch["kind"] == "swing" else "o"
            ax.scatter(
                [xi],
                [tch["px"]],
                marker=marker,
                s=42 if tch["kind"] == "swing" else 28,
                color="#7c3aed" if tch["kind"] == "swing" else "#a78bfa",
                zorder=6,
                edgecolors="white",
                linewidths=0.4,
            )
    br_i = _nearest_idx(l_ts, break_ts, slop_min=250.0)
    if br_i is not None:
        ax.axvline(br_i, color="#7c3aed", lw=1.0, ls=":", alpha=0.85, zorder=4)
        y_ann = float(left["high"].iloc[br_i])
        ax.annotate(
            "HTF break",
            xy=(br_i, y_ann),
            xytext=(8, 10),
            textcoords="offset points",
            fontsize=8,
            color="#5b21b6",
            arrowprops=dict(arrowstyle="->", color="#7c3aed", lw=0.8),
            zorder=7,
        )
    ax.set_xlim(-0.8, nL - 0.2)
    recent = left.iloc[max(0, nL - 14) :]
    y_lo = min(float(recent["low"].min()), level - band)
    y_hi = max(float(recent["high"].max()), level + band)
    for tch in touches:
        xi = tch["i"] - left_i0
        if 0 <= xi < nL:
            y_lo = min(y_lo, tch["px"])
            y_hi = max(y_hi, tch["px"])
    pad = max((y_hi - y_lo) * 0.12, 0.08)
    ax.set_ylim(y_lo - pad, y_hi + pad)
    _set_xticks(ax, list(l_ts), max_ticks=8, mode="4h")
    ax.set_ylabel("Price ($)", fontsize=9)
    ax.set_title(
        f"4-hour  ·  zone {level:.2f} ± {band:.2f}  ({RETEST_ATR_MULT:g}× HTF ATR)",
        fontsize=10,
        loc="left",
        pad=6,
    )
    ax.grid(True, axis="y", color="#e2e8f0", lw=0.6)
    ax.tick_params(axis="y", labelsize=8)
    n_swing = sum(1 for tch in touches if tch["kind"] == "swing")
    n_tag = sum(1 for tch in touches if tch["kind"] == "tag")

    # ---- right 1m ----
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
        ax.scatter([i], [y], marker=marker, s=46, color=color, zorder=7, edgecolors="white", linewidths=0.35)
        ax.annotate(label, xy=(i, y), xytext=(4, 8), textcoords="offset points", fontsize=7.5, color=color, zorder=8)

    br_r = _nearest_idx(r_ts, break_ts)
    rt_i = _nearest_idx(r_ts, retest_ts)
    en_i = _nearest_idx(r_ts, entry_ts)
    ex_i = _nearest_idx(r_ts, exit_ts)
    if br_r is not None:
        ax.axvline(br_r, color="#7c3aed", lw=0.9, ls=":", alpha=0.8, zorder=4)
        mark(break_ts, "break", "#7c3aed", float(right["high"].iloc[br_r]), marker="^")
    else:
        ax.text(
            0.01,
            0.97,
            f"HTF break off-pane: {_fmt_clock(break_ts)}",
            transform=ax.transAxes,
            fontsize=7.2,
            color="#5b21b6",
            va="top",
        )
    if rt_i is not None:
        ax.axvline(rt_i, color="#0284c7", lw=0.8, ls="--", alpha=0.75, zorder=4)
        mark(retest_ts, "retest", "#0284c7", float(right["low"].iloc[rt_i]), marker="v")
    if en_i is not None:
        mark(entry_ts, f"fill {entry_px:.2f}", "#15803d", entry_px, marker=">")
        ax.axhline(entry_px, color="#15803d", lw=0.7, ls=":", alpha=0.7, zorder=4)
        ax.axhline(stop0, color="#64748b", lw=0.95, ls="--", zorder=5)
        trail_x = []
        trail_y = []
        if en_i is not None:
            for k, px in enumerate(trail):
                pane_i = en_i + k
                if 0 <= pane_i < nR:
                    trail_x.append(pane_i)
                    trail_y.append(float(px))
        if trail_x:
            ax.step(trail_x, trail_y, where="post", color="#dc2626", lw=1.7, zorder=8)
    if ex_i is not None:
        mark(exit_ts, f"exit {exit_type} {exit_px:.2f}", "#0f172a", exit_px, marker="X")
        ax.axvline(ex_i, color="#0f172a", lw=0.7, ls=":", alpha=0.55, zorder=4)

    ax.set_xlim(-0.8, nR - 0.2)
    ys = [
        float(right["low"].min()),
        float(right["high"].max()),
        level - band,
        level + band,
        entry_px,
        stop0,
        stop_final,
        exit_px,
        *([float(np.nanmin(trail))] if len(trail) else []),
        *([float(np.nanmax(trail))] if len(trail) else []),
    ]
    y0, y1 = min(ys), max(ys)
    pad = max((y1 - y0) * 0.10, 0.04)
    ax.set_ylim(y0 - pad, y1 + pad)
    _set_xticks(ax, list(r_ts), max_ticks=9, mode="1m")
    ax.set_ylabel("Price ($)", fontsize=9)
    ax.set_title(
        f"1-minute  ·  chandelier 3×ATR  ·  init stop {stop0:.2f} → final {stop_final:.2f}",
        fontsize=10,
        loc="left",
        pad=6,
    )
    ax.grid(True, axis="y", color="#e2e8f0", lw=0.6)
    ax.tick_params(axis="y", labelsize=8)

    sign = "+" if pnl >= 0 else ""
    fig.suptitle(
        f"{sym}   {entry_ts.strftime('%Y-%m-%d')}   4h × 1m chandelier 3×ATR   "
        f"PnL {sign}{pnl:.3f}%   {exit_type}",
        fontsize=13.5,
        fontweight="semibold",
        color="#0f172a",
        y=0.985,
    )
    fig.text(
        0.055,
        0.915,
        "Same unit on both Y-axes (dollars), not the same time scale. "
        "Left = 4-hour RTH candles (09:30-anchored; two bars per session). "
        "Right = 1-minute candles from before the retest through the exit.",
        fontsize=8.2,
        color="#334155",
        ha="left",
        va="top",
    )
    fig.text(
        0.055,
        0.882,
        f"Broken HTF high {level:.2f}  ·  fill {_fmt_clock(entry_ts)} → {_fmt_clock(exit_ts)} "
        f"({float(trade['hold_min']):.0f} min)  ·  "
        f"4h multi-touch: {n_swing} swing high(s) + {n_tag} other 4h high(s) in the band  ·  "
        "chandelier ratchets after the 1m bar closes.",
        fontsize=8.0,
        color="#475569",
        ha="left",
        va="top",
    )
    handles = [
        Line2D([0], [0], color="#b45309", lw=1.4, label="HTF level"),
        Line2D([0], [0], color="#f59e0b", lw=6, alpha=0.35, label="Multi-touch / retest band"),
        Line2D([0], [0], marker="D", color="#7c3aed", lw=0, label="4h swing high in band"),
        Line2D([0], [0], color="#64748b", lw=1, ls="--", label="Initial stop"),
        Line2D([0], [0], color="#dc2626", lw=1.4, label="Chandelier 3×ATR"),
        Line2D([0], [0], marker=">", color="#15803d", lw=0, label="Fill"),
        Line2D([0], [0], marker="X", color="#0f172a", lw=0, label="Exit"),
    ]
    fig.legend(handles=handles, loc="lower center", ncol=7, frameon=False, fontsize=8, bbox_to_anchor=(0.5, 0.012))

    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=128, facecolor=fig.get_facecolor())
    plt.close(fig)
    return None


def write_gallery(rows: list[dict[str, Any]], skipped: list[dict[str, Any]]) -> None:
    n_ok = sum(1 for r in rows if r.get("png"))
    head_cols = [
        ("#", "num"),
        ("symbol", "text"),
        ("entry date", "date"),
        ("split", "text"),
        ("PnL%", "num"),
        ("R", "num"),
        ("exit", "text"),
        ("hold min", "num"),
        ("level", "num"),
        ("entry", "num"),
        ("stop0", "num"),
        ("trail final", "num"),
        ("exit px", "num"),
        ("chart", "text"),
    ]
    ths = "".join(sortable_th(lab, typ) for lab, typ in head_cols)
    body = []
    for r in rows:
        link = (
            f'<a href="#{html_mod.escape(r["anchor"])}">view</a> · '
            f'<a href="{html_mod.escape(r["rel"])}">png</a>'
            if r.get("png")
            else "skipped"
        )
        pnl = float(r["trade"]["pnl_pct"])
        cls = "win" if pnl > 0 else ("flat" if pnl == 0 else "loss")
        t = r["trade"]
        body.append(
            "<tr class='{cls}'>"
            "<td>{n}</td><td>{sym}</td><td>{ed}</td><td>{sp}</td>"
            "<td>{pnl:.3f}</td><td>{rm:.2f}</td><td>{xt}</td><td>{hm:.0f}</td>"
            "<td>{lv:.2f}</td><td>{ep:.2f}</td><td>{s0:.2f}</td><td>{sf:.2f}</td>"
            "<td>{xp:.2f}</td><td>{link}</td></tr>".format(
                cls=cls,
                n=r["n"],
                sym=html_mod.escape(str(t["symbol"])),
                ed=html_mod.escape(str(t["entry_date"])),
                sp=html_mod.escape(str(t.get("split", ""))),
                pnl=pnl,
                rm=float(t["r_mult"]),
                xt=html_mod.escape(str(t["exit_type"])),
                hm=float(t["hold_min"]),
                lv=float(t["level"]),
                ep=float(t["entry_px"]),
                s0=float(t["stop0"]),
                sf=float(t["stop_final"]),
                xp=float(t["exit_px"]),
                link=link,
            )
        )
    skip_html = ""
    if skipped:
        items = "".join(
            f"<li><code>{html_mod.escape(s['id'])}</code> — {html_mod.escape(s['reason'])}</li>"
            for s in skipped
        )
        skip_html = f"<h2>Skipped</h2><ul>{items}</ul>"
    else:
        skip_html = "<h2>Skipped</h2><p class='note'>None. All 37 trades had 1m bars through the exit.</p>"

    cards = []
    for r in rows:
        if not r.get("png"):
            continue
        t = r["trade"]
        pnl = float(t["pnl_pct"])
        sign = "+" if pnl >= 0 else ""
        cards.append(
            f'<article class="card" id="{html_mod.escape(r["anchor"])}">'
            f"<h3>{html_mod.escape(str(t['symbol']))} · {html_mod.escape(str(t['entry_date']))} · "
            f"{sign}{pnl:.3f}% · {html_mod.escape(str(t['exit_type']))}</h3>"
            f'<p class="cap">Fill {_fmt_clock(_ts(t["entry_ts"]))} → {_fmt_clock(_ts(t["exit_ts"]))} · '
            f"level {float(t['level']):.2f} · stop {float(t['stop0']):.2f} → {float(t['stop_final']):.2f}</p>"
            f'<img src="{html_mod.escape(r["rel"])}" alt="{html_mod.escape(r["anchor"])}" loading="lazy"/>'
            f'<p class="cap"><a href="#top">back to table</a></p></article>'
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>4h zone + 1m chandelier charts — intraday_htf_retest_20260916</title>
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
<h1>4-hour multi-touch + 1-minute chandelier charts</h1>
<p class="meta">Stamp <code>intraday_htf_retest_20260916</code> · arm <strong>4h × 1m trail_chandelier_3</strong> ·
rendered {n_ok} of {len(rows)} · freeze unchanged.</p>

<div class="ask">
<strong>What you asked</strong>
<blockquote>{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
<p class="note">Parent test ask (same stamp): draw 4-hour / 2-hour / 30-minute pivots, buy a 1–2 minute break-and-retest, and walk the stop on those short bars.</p>
</div>
<div class="plain">
<strong>In plain English</strong>
<p>{html_mod.escape(PLAIN_ENGLISH)}</p>
<p>High Time Frame (<strong>HTF</strong>) = the 4-hour candles we drew the broken swing high on.
Low Time Frame (<strong>LTF</strong>) = the 1-minute candles we used to time the buy and the chandelier stop.
Average True Range (<strong>ATR</strong>) = a typical-bar-range measure (Wilder 14). The chandelier sits
<code>highest high since entry − 3 × 1m ATR</code> and never moves down.</p>
</div>

<p class="note">Click column headers to sort. Each row jumps to that trade’s picture. Left pane = 4-hour
RTH candles (09:30-anchored; two bars per session). Right pane = 1-minute candles. Both Y-axes are
dollars, independently scaled so the candles fill the pane — they are <em>not</em> the same time scale.</p>

<h2>Trades</h2>
<table class="sortable">
<thead><tr>{ths}</tr></thead>
<tbody>
{''.join(body)}
</tbody>
</table>

{skip_html}

<h2>Charts</h2>
{''.join(cards)}

{SORT_JS}
</body>
</html>
"""
    GALLERY.write_text(html, encoding="utf-8")


def main() -> int:
    trades = load_arm_trades()
    print(f"4h×1m {ARM}: N={len(trades)}")
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    cache: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for i, t in enumerate(trades, start=1):
        sym = str(t["symbol"]).upper()
        ed = str(t["entry_date"])
        hhmm = _ts(t["entry_ts"]).strftime("%H%M")
        stem = f"{i:02d}_{sym}_{ed}_{hhmm}"
        png = CHART_DIR / f"{stem}.png"
        reason = render_trade(t, cache, png)
        rec = {
            "n": i,
            "trade": t,
            "anchor": stem,
            "rel": f"charts/{stem}.png",
            "png": None if reason else png.name,
        }
        if reason:
            rec["png"] = None
            skipped.append({"id": stem, "reason": reason, "symbol": sym, "entry_ts": str(t["entry_ts"])})
            print(f"  SKIP {stem}: {reason}")
            if png.exists():
                try:
                    png.unlink()
                except OSError:
                    pass
        else:
            print(f"  OK   {stem}")
        rows.append(rec)
    write_gallery(rows, skipped)
    manifest = {
        "arm": f"{HTF}x{LTF} {ARM}",
        "n_book": len(trades),
        "n_rendered": len(trades) - len(skipped),
        "n_skipped": len(skipped),
        "gallery": str(GALLERY.as_posix()),
        "skipped": skipped,
    }
    (STAMP / "charts_4h_1m_chandelier3_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(f"gallery {GALLERY}")
    print(f"rendered {manifest['n_rendered']} / {len(trades)}; skipped {len(skipped)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
