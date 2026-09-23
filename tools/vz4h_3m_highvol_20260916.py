#!/usr/bin/env python3
"""4h Regular Trading Hours Volume Zone analog — 3-month high-volume bar pictures.

Research pictures only. Does not mutate DailyRun Volume Zone (VZ) or the
High Tight Flag (HTF) chandelier freeze.

House VZ (tools/vol_zone_break_retest.py) elects the max-volume daily bar in a
rolling 126-day window and turns that bar's High–Low into a persistent HL zone.
After a close above the zone, it buys the first from-above retest.

This stamp does the same engine on 4-hour RTH bars: lookback 126 4h bars
(~63 sessions / ~3 calendar months), HL-only, first_retest, eps=0.005, rw=63,
next_open. No atr4 / s025 / r15 / ts20 / chandelier.

1m parquet under data/intraday/1m/ is only ~Jul–Sep 2026 (~39 sessions) and is
NOT used as the 3-month source. 4h bars are resampled from Yahoo 1h (RTH),
cached under the stamp.

Usage:
  python tools/vz4h_3m_highvol_20260916.py
"""
from __future__ import annotations

import html as html_mod
import json
import sys
import time
from dataclasses import replace
from datetime import time as dtime
from pathlib import Path
from typing import Any, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "stock_analysis"))
sys.path.insert(0, str(ROOT / "tools"))

from intraday_1m import ET, _normalize_bars, to_yahoo  # noqa: E402
from intraday_htf_retest_20260916 import (  # noqa: E402
    EXTRA_UNIVERSE,
    load_paultwenty,
    resample_from_rth_open,
    rth_filter,
)
from vol_zone_break_retest import (  # noqa: E402
    RESEARCH_CANDIDATE_V2_RW63,
    atr14,
    build_zones,
    detect_breaks,
    detect_touches,
    generate_signals,
)

STAMP_NAME = "vz4h_3m_highvol_20260916"
STAMP = ROOT / "drive" / "paul_experiments" / STAMP_NAME
CHART_DIR = STAMP / "charts"
CACHE_1H = STAMP / "cache_1h"
YF_START = "2025-09-01"
YF_END = "2026-09-17"
LOOKBACK_4H = 126  # ~63 RTH sessions / ~3 calendar months
RETEST_WINDOW_4H = 63
RETEST_EPS = 0.005
BAR_MINUTES = 240
MIN_4H_BARS = LOOKBACK_4H + 8
PLOT_BARS = 180
PAD_BEFORE = 16

ORIGINAL_REQUEST = (
    "can you draw me some 4hr graphs where the 3-month high volume acts like "
    "the VZ system. it creates a zone that can be bounced off of and retested "
    "for a buy."
)

PLAIN_ENGLISH = (
    "The Volume Zone (VZ) system marks a price band from a high-volume area and "
    "looks for a later bounce / retest as a buy. Here we do the same idea on "
    "4-hour Regular Trading Hours (RTH) charts: find the highest-volume 4h bar "
    "over the last ~3 months, turn that bar’s range into a zone, and draw later "
    "touches / bounces / retests."
)

PARAMS = replace(
    RESEARCH_CANDIDATE_V2_RW63,
    lookback_days=LOOKBACK_4H,
    retest_window=RETEST_WINDOW_4H,
    retest_eps_pct=RETEST_EPS,
    first_retest_only=True,
    min_touches_before_entry=1,
    entry_on="next_open",
    zone_kinds=("HL",),
    break_pct=0.0,
    break_atr=0.0,
    require_hvn_overlap=False,
    trade_side="long",
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


def frozen_universe() -> list[str]:
    names = load_paultwenty()
    for extra in EXTRA_UNIVERSE:
        if extra not in names:
            names.append(extra)
    return names


def fetch_1h(symbol: str) -> pd.DataFrame:
    """Yahoo 1h → stamp cache. Shop 1m is too short for a real 3-month window."""
    path = CACHE_1H / f"{symbol}.parquet"
    if path.is_file():
        df = pd.read_parquet(path)
        if not df.empty:
            df = df.copy()
            df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(ET)
            return df.sort_values("ts").drop_duplicates(subset=["ts"], keep="last").reset_index(drop=True)

    import yfinance as yf

    raw = yf.download(
        to_yahoo(symbol),
        start=YF_START,
        end=YF_END,
        interval="1h",
        progress=False,
        auto_adjust=False,
        threads=False,
        prepost=False,
    )
    out = _normalize_bars(raw, symbol)
    CACHE_1H.mkdir(parents=True, exist_ok=True)
    if not out.empty:
        save = out.copy()
        save["ts"] = pd.to_datetime(save["ts"], utc=True)
        save.to_parquet(path, index=False)
    return out


def to_vz_frame(htf: pd.DataFrame) -> pd.DataFrame:
    ts = pd.to_datetime(htf["ts"], utc=True).dt.tz_convert(ET)
    return pd.DataFrame(
        {
            "Date": ts.dt.tz_localize(None),
            "Open": htf["open"].to_numpy(dtype=float),
            "High": htf["high"].to_numpy(dtype=float),
            "Low": htf["low"].to_numpy(dtype=float),
            "Close": htf["close"].to_numpy(dtype=float),
            "Volume": htf["volume"].to_numpy(dtype=float),
        }
    )


def fmt_ts(ts: Any) -> str:
    t = pd.Timestamp(ts)
    if t.tzinfo is not None:
        t = t.tz_convert(ET).tz_localize(None)
    return t.strftime("%Y-%m-%d %H:%M")


def fmt_day(ts: Any) -> str:
    t = pd.Timestamp(ts)
    return t.strftime("%Y-%m-%d")


def _draw_candles_idx(ax, idx: np.ndarray, o, h, l, c) -> None:
    up = c >= o
    ax.vlines(idx, l, h, color="#64748b", lw=0.55, zorder=2)
    body_lo = np.minimum(o, c)
    body_hi = np.maximum(o, c)
    if np.any(up):
        ax.vlines(idx[up], body_lo[up], body_hi[up], color="#2ca02c", lw=2.0, zorder=3)
    if np.any(~up):
        ax.vlines(idx[~up], body_lo[~up], body_hi[~up], color="#d62728", lw=2.0, zorder=3)


def current_maxvol_idx(df: pd.DataFrame) -> int:
    """As-of last 4h bar: the single max-volume bar in the trailing 126-bar window."""
    n = len(df)
    w0 = max(0, n - LOOKBACK_4H)
    vol = df["Volume"].to_numpy(dtype=np.float64)
    return int(w0 + int(np.argmax(vol[w0:n])))


def pick_display_zone(
    zone_rows: list[dict[str, Any]], current_idx: int
) -> Optional[dict[str, Any]]:
    """Show the *current* 3-month max-vol 4h bar (Paul's ask), not an old lucky bounce.

    Skip winners elected before the tape had a real ~3-month lookback unless that
    bar is still the current window's max-vol (then the as-of window is full).
    """
    if not zone_rows:
        return None
    for r in zone_rows:
        r["is_current_3m"] = int(r["max_vol_idx"]) == int(current_idx)
    current = [r for r in zone_rows if r["is_current_3m"]]
    if current:
        return current[-1]
    # Synthesize-friendly fallback: latest zone whose own lookback was ≥80 calendar days
    real = [r for r in zone_rows if int(r["lookback_cal_days"]) >= 80]
    if real:
        return real[-1]
    return zone_rows[-1]


def analyze_symbol(symbol: str) -> dict[str, Any]:
    raw = fetch_1h(symbol)
    if raw.empty:
        return {"symbol": symbol, "ok": False, "reason": "no 1h bars"}
    rth = rth_filter(raw)
    htf = resample_from_rth_open(rth, BAR_MINUTES)
    if htf is None or len(htf) < MIN_4H_BARS:
        n = 0 if htf is None else len(htf)
        return {"symbol": symbol, "ok": False, "reason": f"only {n} 4h bars (need {MIN_4H_BARS})"}

    df = to_vz_frame(htf)
    first = pd.Timestamp(df["Date"].iloc[0])
    last = pd.Timestamp(df["Date"].iloc[-1])
    cal_days = (last.normalize() - first.normalize()).days
    n_sess = int(pd.Series(df["Date"]).dt.normalize().nunique())
    if cal_days < 80:
        return {
            "symbol": symbol,
            "ok": False,
            "reason": f"4h span only {cal_days} calendar days (need ~3 months)",
            "n_4h": int(len(df)),
            "first": fmt_ts(first),
            "last": fmt_ts(last),
        }

    zones = [z for z in build_zones(df, LOOKBACK_4H) if z.kind == "HL"]
    atr = atr14(df)
    zone_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    for z in zones:
        touches = detect_touches(df, z, PARAMS.approach_lookback, eps_pct=PARAMS.retest_eps_pct)
        breaks = detect_breaks(
            df, z, atr, PARAMS.break_pct, PARAMS.break_atr, PARAMS.break_window
        )
        ups = [b for b in breaks if b.direction == "up"]
        sigs = generate_signals(df, z, touches, breaks, PARAMS, "vz4h_3m")
        failed = [
            t
            for t in touches
            if t.approach == "from_above"
            and t.broke
            and (not ups or t.bar_idx > ups[0].bar_idx)
        ]
        bounce_holds = [
            t
            for t in touches
            if t.approach == "from_above"
            and t.is_hold
            and (not ups or t.bar_idx > ups[0].bar_idx)
        ]
        lookback_start = max(0, z.max_vol_idx - LOOKBACK_4H + 1)
        lookback_cal = (
            pd.Timestamp(df["Date"].iloc[z.max_vol_idx]).normalize()
            - pd.Timestamp(df["Date"].iloc[lookback_start]).normalize()
        ).days
        row = {
            "symbol": symbol,
            "zone_id": z.zone_id,
            "max_vol_idx": int(z.max_vol_idx),
            "max_vol_ts": fmt_ts(z.max_vol_date),
            "max_vol_day": fmt_day(z.max_vol_date),
            "created_on": fmt_ts(z.created_on),
            "zone_lo": float(z.lo),
            "zone_hi": float(z.hi),
            "volume": int(z.volume),
            "lookback_cal_days": int(lookback_cal),
            "broke_up": bool(ups),
            "break_ts": fmt_ts(ups[0].date) if ups else "",
            "retest_buy": bool(sigs),
            "retest_ts": fmt_ts(sigs[0].signal_date) if sigs else "",
            "entry_ts": fmt_ts(sigs[0].entry_date) if sigs else "",
            "entry_price": float(sigs[0].entry_price) if sigs else "",
            "n_failed_tags": len(failed),
            "n_hold_bounces": len(bounce_holds),
            "n_4h": int(len(df)),
            "first_4h": fmt_ts(first),
            "last_4h": fmt_ts(last),
            "n_sessions": n_sess,
            "cal_span_days": int(cal_days),
            "is_current_3m": False,
            "_zone": z,
            "_sigs": sigs,
            "_ups": ups,
            "_failed": failed,
            "_holds": bounce_holds,
            "_df": df,
        }
        zone_rows.append(row)
        for s in sigs:
            event_rows.append(
                {
                    "symbol": symbol,
                    "zone_id": z.zone_id,
                    "max_vol_ts": fmt_ts(z.max_vol_date),
                    "zone_lo": float(z.lo),
                    "zone_hi": float(z.hi),
                    "volume": int(z.volume),
                    "break_ts": fmt_ts(s.break_date),
                    "signal_ts": fmt_ts(s.signal_date),
                    "entry_ts": fmt_ts(s.entry_date),
                    "entry_price": float(s.entry_price),
                    "bars_after_break": int(s.bars_after_break),
                    "kind": "retest_buy",
                }
            )
        for t in failed:
            event_rows.append(
                {
                    "symbol": symbol,
                    "zone_id": z.zone_id,
                    "max_vol_ts": fmt_ts(z.max_vol_date),
                    "zone_lo": float(z.lo),
                    "zone_hi": float(z.hi),
                    "volume": int(z.volume),
                    "break_ts": fmt_ts(ups[0].date) if ups else "",
                    "signal_ts": fmt_ts(t.date),
                    "entry_ts": "",
                    "entry_price": "",
                    "bars_after_break": int(t.bar_idx - ups[0].bar_idx) if ups else "",
                    "kind": "failed_tag",
                }
            )

    current_idx = current_maxvol_idx(df)
    chosen = pick_display_zone(zone_rows, current_idx)
    if chosen is None:
        # Last-window winner with no Zone object (should be rare): synthesize HL from the bar.
        w = current_idx
        chosen = {
            "symbol": symbol,
            "zone_id": f"HL_{fmt_day(df['Date'].iloc[w])}",
            "max_vol_idx": int(w),
            "max_vol_ts": fmt_ts(df["Date"].iloc[w]),
            "max_vol_day": fmt_day(df["Date"].iloc[w]),
            "created_on": fmt_ts(df["Date"].iloc[w]),
            "zone_lo": float(df["Low"].iloc[w]),
            "zone_hi": float(df["High"].iloc[w]),
            "volume": int(df["Volume"].iloc[w]),
            "lookback_cal_days": int(
                (
                    pd.Timestamp(df["Date"].iloc[w]).normalize()
                    - pd.Timestamp(df["Date"].iloc[max(0, w - LOOKBACK_4H + 1)]).normalize()
                ).days
            ),
            "broke_up": False,
            "break_ts": "",
            "retest_buy": False,
            "retest_ts": "",
            "entry_ts": "",
            "entry_price": "",
            "n_failed_tags": 0,
            "n_hold_bounces": 0,
            "n_4h": int(len(df)),
            "first_4h": fmt_ts(first),
            "last_4h": fmt_ts(last),
            "n_sessions": n_sess,
            "cal_span_days": int(cal_days),
            "is_current_3m": True,
            "_zone": None,
            "_sigs": [],
            "_ups": [],
            "_failed": [],
            "_holds": [],
            "_df": df,
            "_synth": True,
        }
    return {
        "symbol": symbol,
        "ok": True,
        "n_4h": int(len(df)),
        "n_sessions": n_sess,
        "cal_span_days": int(cal_days),
        "first_4h": fmt_ts(first),
        "last_4h": fmt_ts(last),
        "n_hl_zones": len(zone_rows),
        "n_retest_buys": sum(1 for r in zone_rows if r["retest_buy"]),
        "n_breaks": sum(1 for r in zone_rows if r["broke_up"]),
        "zone_rows": zone_rows,
        "event_rows": event_rows,
        "chosen": chosen,
        "df": df,
    }


def plot_zone(pack: dict[str, Any], out_path: Path) -> None:
    row = pack["chosen"]
    df: pd.DataFrame = pack["df"]
    z = row["_zone"]
    if z is None:
        # Minimal stand-in so the current bar still draws.
        class _Z:
            pass

        z = _Z()
        z.max_vol_idx = int(row["max_vol_idx"])
        z.lo = float(row["zone_lo"])
        z.hi = float(row["zone_hi"])
        z.max_vol_date = pd.Timestamp(df["Date"].iloc[z.max_vol_idx])
    n = len(df)
    left = max(0, z.max_vol_idx - PAD_BEFORE)
    right = n
    if row["_sigs"]:
        right = max(right, min(n, int(row["_sigs"][0].entry_idx) + 12))
    span = right - left
    if span > PLOT_BARS:
        # Prefer the latest tape so the current 3-month shelf is in context.
        left = max(0, n - PLOT_BARS)
        right = n
        if z.max_vol_idx < left:
            left = max(0, z.max_vol_idx - PAD_BEFORE)
            right = min(n, left + PLOT_BARS)

    sl = df.iloc[left:right].reset_index(drop=True)
    idx = np.arange(len(sl))
    o = sl["Open"].to_numpy()
    h = sl["High"].to_numpy()
    l = sl["Low"].to_numpy()
    c = sl["Close"].to_numpy()
    v = sl["Volume"].to_numpy()
    dates = sl["Date"]

    fig, (ax, axv) = plt.subplots(
        2,
        1,
        figsize=(16.5, 8.4),
        sharex=True,
        gridspec_kw={"height_ratios": [3.15, 1.0], "hspace": 0.04},
    )
    _draw_candles_idx(ax, idx, o, h, l, c)

    z0 = z.max_vol_idx - left
    if 0 <= z0 < len(sl):
        width = 1.15
        ax.add_patch(
            Rectangle(
                (z0 - width / 2, z.lo),
                width,
                z.hi - z.lo,
                linewidth=1.6,
                edgecolor="#ff7f0e",
                facecolor="#ff7f0e",
                alpha=0.22,
                zorder=4,
            )
        )
        ax.axvline(z0, color="#ff7f0e", ls="--", lw=1.15, alpha=0.9, zorder=1)

    if z0 < len(sl):
        xs = np.arange(max(0, z0), len(sl))
        if len(xs):
            ax.fill_between(xs, z.lo, z.hi, color="#9467bd", alpha=0.18, zorder=0)
    ax.axhline(z.hi, color="#9467bd", lw=0.9, alpha=0.85)
    ax.axhline(z.lo, color="#9467bd", lw=0.9, alpha=0.85)

    first_br = True
    for br in row["_ups"]:
        x = br.bar_idx - left
        if 0 <= x < len(sl):
            ax.scatter(
                [x],
                [br.close],
                marker="^",
                s=92,
                color="#2ca02c",
                edgecolors="black",
                linewidths=0.4,
                zorder=6,
                label="Break up (close > zone high)" if first_br else None,
            )
            first_br = False

    first_buy = True
    for s in row["_sigs"]:
        x = s.entry_idx - left
        if 0 <= x < len(sl):
            ax.scatter(
                [x],
                [s.entry_price],
                marker="o",
                s=70,
                color="#e377c2",
                edgecolors="white",
                linewidths=0.6,
                zorder=7,
                label="Retest buy (next 4h open)" if first_buy else None,
            )
            ax.annotate(
                f"buy {fmt_ts(s.entry_date)[5:]}",
                xy=(x, s.entry_price),
                xytext=(8, 12),
                textcoords="offset points",
                fontsize=8,
                color="#9d174d",
                arrowprops=dict(arrowstyle="->", color="0.45", lw=0.7),
            )
            first_buy = False
        xs = s.signal_idx - left
        if 0 <= xs < len(sl):
            ax.scatter(
                [xs],
                [float(sl["Low"].iloc[xs])],
                marker="v",
                s=42,
                color="#e377c2",
                edgecolors="white",
                linewidths=0.4,
                zorder=6,
            )

    first_fail = True
    for t in row["_failed"]:
        x = t.bar_idx - left
        if 0 <= x < len(sl):
            ax.scatter(
                [x],
                [t.low],
                marker="x",
                s=42,
                color="#7f1d1d",
                zorder=6,
                label="Failed tag (closed below zone low)" if first_fail else None,
            )
            first_fail = False

    tagged = "YES" if row["retest_buy"] else "NO"
    ax.set_title(
        f"{pack['symbol']}  4h RTH  ·  zone {row['max_vol_ts']}  ·  "
        f"HL {row['zone_lo']:.2f}–{row['zone_hi']:.2f}  ·  retest-buy: {tagged}",
        fontsize=12,
        loc="left",
        pad=8,
    )
    ax.set_ylabel("Price")
    ax.grid(True, alpha=0.22)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:,.2f}"))
    handles, labels = ax.get_legend_handles_labels()
    extra = [
        plt.Line2D([0], [0], color="#ff7f0e", ls="--", lw=1.2, label="3-month max-vol 4h bar"),
        plt.Rectangle((0, 0), 1, 1, fc="#9467bd", alpha=0.25, label="HL zone (bar High–Low)"),
    ]
    ax.legend(handles=extra + handles, loc="upper left", fontsize=8, framealpha=0.92)

    colors = np.where(c >= o, "#2ca02c", "#d62728")
    axv.bar(idx, v, color=colors, width=0.82, alpha=0.55, zorder=2)
    if 0 <= z0 < len(sl):
        axv.bar([z0], [v[z0]], color="#ff7f0e", width=0.9, zorder=3)
        axv.axvline(z0, color="#ff7f0e", ls="--", lw=1.0, alpha=0.85)
    lb0 = max(0, (z.max_vol_idx - LOOKBACK_4H + 1) - left)
    lb1 = min(len(sl) - 1, z0)
    if lb1 >= lb0:
        axv.axvspan(lb0 - 0.5, lb1 + 0.5, color="#ffedd5", alpha=0.55, zorder=0)
    axv.set_ylabel("Volume")
    axv.grid(True, alpha=0.18)
    axv.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x/1e6:.1f}M" if x >= 1e6 else f"{x/1e3:.0f}k"))

    tick_n = max(6, min(12, len(sl) // 12 or 6))
    tick_pos = np.linspace(0, max(len(sl) - 1, 0), tick_n, dtype=int)
    axv.set_xticks(tick_pos)
    axv.set_xticklabels([dates.iloc[i].strftime("%m-%d %H:%M") for i in tick_pos], rotation=30, ha="right")
    axv.set_xlabel("4h RTH bar start (ET)")

    fig.savefig(out_path, dpi=130, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def write_baseline(universe: list[str], coverage: list[dict[str, Any]]) -> None:
    lines = [
        f"# BASELINE — 4h 3-month high-volume Volume Zone (VZ) analog — `{STAMP_NAME}`",
        "",
        "**System:** visual analog of house VZ on 4-hour Regular Trading Hours (RTH) bars. "
        "**Research pictures only. Not gold. Not DailyRun.**",
        "Does not mutate `run_vz.bat` / `rocket_vz.py` or `intraday_htf_retest_20260916`.",
        "",
        "## What you asked",
        "",
        f"> {ORIGINAL_REQUEST}",
        "",
        "## In plain English",
        "",
        PLAIN_ENGLISH,
        "",
        "Volume Zone (**VZ**) = house daily system: rolling max-volume day → High–Low band → "
        "break-up → from-above retest buy.",
        "Regular Trading Hours (**RTH**) = 09:30–16:00 ET.",
        "Average True Range (**ATR**) is **not** used to pad the 4h zone (house VZ zone is also "
        "raw High–Low, not mid ± k×ATR). House DailyRun still has an atr4 *entry floor* and "
        "s025 stop; those exits are **off** here (picture job).",
        "",
        "## How house VZ is born (do not invent)",
        "",
        "From `tools/vol_zone_break_retest.build_zones` / `docs/systems/vz.html`:",
        "",
        "- Each bar after `lookback_days`, the **single max-volume bar** in the trailing window "
        "becomes a persistent zone when it first wins.",
        "- Adopted freeze is **HL-only**: zone = that bar’s High–Low. No ATR padding. "
        "Open–Close (OC) zones exist in the engine but are off in the house pin.",
        "- **Break-up:** close > zone.hi (break_pct=0, break_atr=0), having been at/below the top prior.",
        "- **Retest buy:** within `retest_window` bars after the break, a bar intersects the band "
        "(or near-miss within `retest_eps_pct` of zone.hi), approach `from_above`, close still "
        "≥ zone.lo. Signal known at that bar’s close; house fill is **next open**.",
        "- Quality gates: `first_retest_only=True`, `min_touches_before_entry ≥ 1`. High-volume "
        "node (HVN) overlap is **off**.",
        "",
        "Daily house lookback is **126 trading days** (~6 months). The 4h analog keeps the "
        "**same bar-count (126)** so the calendar window is ~3 months (two RTH 4h bars per session).",
        "",
        "## Freeze (one definition — not shopped)",
        "",
        "| Knob | Value |",
        "|------|--------|",
        f"| Universe | PaulTwenty + UNH (same HTF 4h list): {', '.join(universe)} |",
        "| Session | RTH 09:30–16:00 ET |",
        "| 4h source | Yahoo **1h** (`interval=1h`, `prepost=False`), RTH-filtered, "
        "session-anchored resample at 09:30 ET, 240 minutes (shop `resample_from_rth_open`). "
        f"Cache `{STAMP_NAME}/cache_1h/`. Window {YF_START} → {YF_END}. |",
        "| Why not 1m | Shop `data/intraday/1m/` is ~2026-07-23 → 2026-09-16 (~39 sessions). "
        "That is **not** 3 months. Not used as the lookback source. |",
        "| Why not daily | Daily OHLC exists under `data/newdata/data` but cannot draw 4h candles. |",
        f"| Lookback | **{LOOKBACK_4H} 4h bars** (~63 sessions / ~3 calendar months) |",
        "| Anchor | Single 4h bar with **max volume** in that window (same as VZ, not vol-vs-average) |",
        "| Zone | That bar’s **High–Low** (HL). Label `HL_YYYY-MM-DD`. No ATR pad. |",
        "| Break | 4h close > zone.hi |",
        f"| Retest window | **{RETEST_WINDOW_4H}** 4h bars after the break (~31 sessions) |",
        f"| Bounce / retest | House `generate_signals`: from_above intersect or eps={RETEST_EPS} "
        "near-miss of zone.hi; close ≥ zone.lo; first_retest_only; min_touches≥1 |",
        "| Buy mark | Next 4h open after the signal bar (house `entry_on=next_open`) |",
        "| Failed tag | Post-break from-above touch that **closes below** zone.lo |",
        "| Colors | House VZ charts: HL band `#9467bd`, max-vol `#ff7f0e` dashed, "
        "break-up green triangle, HL retest buy `#e377c2` |",
        "| Exits | **None** (no chandelier, no s025/r15/ts20, no atr4 floor) |",
        "| Status | Research pictures + event list. Not gold. Not DailyRun. |",
        "",
        "## Split",
        "",
        "No KEEP/DISMISS book. If a later AB is run, default shop IS is `entry_date < 2024-01-01`; "
        "OOS report-only. This stamp is pictures on 2025-09 → 2026-09 1h tape.",
        "",
        "## Coverage (4h from 1h)",
        "",
        "| Symbol | 4h bars | Sessions | Calendar days | First | Last | HL zones | Retest buys |",
        "|--------|--------:|---------:|--------------:|-------|------|---------:|------------:|",
    ]
    for c in coverage:
        if not c.get("ok"):
            lines.append(
                f"| {c['symbol']} | — | — | — | — | — | — | — |"
            )
            continue
        lines.append(
            f"| {c['symbol']} | {c['n_4h']} | {c['n_sessions']} | {c['cal_span_days']} | "
            f"{c['first_4h']} | {c['last_4h']} | {c['n_hl_zones']} | {c['n_retest_buys']} |"
        )
    lines.extend(
        [
            "",
            "## Chart pick",
            "",
            "One PNG per symbol: the **current** 3-month max-volume 4h bar as of the last 1h→4h "
            "print (argmax volume in the trailing 126 4h bars). That is Paul’s “3-month high "
            "volume,” not a hunt for an older zone that already bounced. House VZ still keeps "
            "older winners as persistent zones; those show up in `events.csv`, not as the "
            "headline picture.",
            "",
        ]
    )
    (STAMP / "BASELINE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_hypothesis() -> None:
    text = f"""# HYPOTHESIS — `{STAMP_NAME}`

**Visual analog only. Not a KEEP / gold / DailyRun claim.**

## What you asked

> {ORIGINAL_REQUEST}

## In plain English

{PLAIN_ENGLISH}

## Hypothesis (pictures, not a book)

If a 4-hour Regular Trading Hours (RTH) bar is the highest-volume print in the
trailing ~3 months, its High–Low band should behave like a daily Volume Zone
(VZ) node: after price accepts above it, a later tag from above is a bounce /
retest buy location.

This stamp **does not** claim expectancy, win rate, or promotion. It asks
whether the pictures look like house VZ (purple HL band, orange max-vol bar,
pink retest buy).

## One knob

Timeframe only: same VZ birth / break / first-retest rules, on 4h bars, with
lookback bar-count kept at 126 so the calendar window is ~3 months.

No exit horse-race. No atr4 floor. No chandelier.

## Falsify / HOLD

- Zones sit in the middle of nowhere and later tags do not bounce.
- Max-vol 4h bar is usually an earnings/news spike whose High–Low is too wide
  to act as a shelf.
- 1h→4h volume is a poor cousin of daily VZ volume (session split, Yahoo gaps).

If a later quality A/B is wanted: freeze this definition, report IS/OOS, do not
retune on OOS.
"""
    (STAMP / "HYPOTHESIS.md").write_text(text, encoding="utf-8")


def write_html(
    *,
    universe: list[str],
    coverage: list[dict[str, Any]],
    chart_rows: list[dict[str, Any]],
    event_rows: list[dict[str, Any]],
) -> Path:
    n_charts = len(chart_rows)
    n_buy = sum(1 for r in chart_rows if r["retest_buy"])
    n_break = sum(1 for r in chart_rows if r["broke_up"])
    n_ev_buy = sum(1 for e in event_rows if e["kind"] == "retest_buy")
    n_ev_fail = sum(1 for e in event_rows if e["kind"] == "failed_tag")

    cov_rows = []
    for c in coverage:
        if not c.get("ok"):
            cov_rows.append(
                f"<tr><td>{html_mod.escape(c['symbol'])}</td><td colspan='7'>"
                f"{html_mod.escape(str(c.get('reason', 'failed')))}</td></tr>"
            )
            continue
        cov_rows.append(
            "<tr>"
            f"<td>{html_mod.escape(c['symbol'])}</td>"
            f"<td>{c['n_4h']}</td><td>{c['n_sessions']}</td><td>{c['cal_span_days']}</td>"
            f"<td>{html_mod.escape(c['first_4h'])}</td><td>{html_mod.escape(c['last_4h'])}</td>"
            f"<td>{c['n_hl_zones']}</td><td>{c['n_retest_buys']}</td>"
            "</tr>"
        )

    chart_tbl = []
    gallery = []
    for r in chart_rows:
        rel = html_mod.escape(r["rel"])
        tagged = "YES" if r["retest_buy"] else "NO"
        current = "YES" if r.get("is_current_3m") else "NO"
        chart_tbl.append(
            "<tr>"
            f"<td><a href=\"#{html_mod.escape(r['anchor'])}\">{html_mod.escape(r['symbol'])}</a></td>"
            f"<td>{html_mod.escape(r['max_vol_ts'])}</td>"
            f"<td>{r['zone_lo']:.2f}</td><td>{r['zone_hi']:.2f}</td>"
            f"<td>{r['volume']:,}</td>"
            f"<td>{r['lookback_cal_days']}</td>"
            f"<td>{current}</td>"
            f"<td>{'YES' if r['broke_up'] else 'NO'}</td>"
            f"<td>{html_mod.escape(r['break_ts'] or '—')}</td>"
            f"<td>{tagged}</td>"
            f"<td>{html_mod.escape(r['retest_ts'] or '—')}</td>"
            f"<td>{html_mod.escape(r['entry_ts'] or '—')}</td>"
            f"<td>{r['n_hold_bounces']}</td>"
            f"<td>{r['n_failed_tags']}</td>"
            f"<td><a href=\"{rel}\">PNG</a></td>"
            "</tr>"
        )
        gallery.append(
            f"<figure class='card' id='{html_mod.escape(r['anchor'])}'>"
            f"<figcaption><strong>{html_mod.escape(r['symbol'])}</strong> · zone "
            f"{html_mod.escape(r['max_vol_ts'])} · retest-buy {tagged}</figcaption>"
            f"<a href='{rel}'><img src='{rel}' alt='{html_mod.escape(r['symbol'])} 4h VZ analog'/></a>"
            "</figure>"
        )

    ev_tbl = []
    for e in event_rows:
        px = f"{float(e['entry_price']):.2f}" if e["entry_price"] != "" else "—"
        ev_tbl.append(
            "<tr>"
            f"<td>{html_mod.escape(e['symbol'])}</td>"
            f"<td>{html_mod.escape(e['kind'])}</td>"
            f"<td>{html_mod.escape(e['max_vol_ts'])}</td>"
            f"<td>{e['zone_lo']:.2f}</td><td>{e['zone_hi']:.2f}</td>"
            f"<td>{html_mod.escape(str(e['break_ts'] or '—'))}</td>"
            f"<td>{html_mod.escape(str(e['signal_ts'] or '—'))}</td>"
            f"<td>{html_mod.escape(str(e['entry_ts'] or '—'))}</td>"
            f"<td>{px}</td>"
            f"<td>{e['bars_after_break'] if e['bars_after_break'] != '' else '—'}</td>"
            "</tr>"
        )

    n_current = sum(1 for r in chart_rows if r.get("is_current_3m"))
    read = (
        f"Each of the {n_charts} pictures is the name’s current 3-month max-volume 4h bar "
        f"({n_current} confirmed as-of last print). {n_buy} of those current shelves already "
        f"printed a house-style first retest-buy; {n_break} had already closed above the zone. "
        f"Older persistent VZ-style winners (not the current shelf) add the rest of the "
        f"{n_ev_buy} retest-buys / {n_ev_fail} failed tags in the event table. Pictures, "
        f"not a book — no KEEP."
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>4h 3-month high-volume VZ analog — {STAMP_NAME}</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:24px;color:#0f172a;background:#f8fafc;line-height:1.45}}
h1{{font-size:1.45rem;margin:0 0 8px}}
h2{{font-size:1.15rem;margin:28px 0 10px}}
.ask,.plain{{max-width:980px;padding:12px 14px;border-radius:8px;margin:12px 0}}
.ask{{background:#fff7ed;border:1px solid #fdba74}}
.plain{{background:#ecfeff;border:1px solid #67e8f9}}
.badge{{display:inline-block;background:#fef3c7;color:#92400e;padding:2px 8px;border-radius:4px;font-size:.85rem;font-weight:600}}
.meta,.note{{font-size:.92rem;color:#475569;max-width:980px}}
.cards{{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}}
.stat{{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:12px 14px;min-width:160px}}
.stat h3{{margin:0 0 6px;font-size:12px;color:#64748b}}
.stat .n{{font-size:1.25rem;font-weight:700}}
table.sortable{{border-collapse:collapse;width:100%;background:#fff;margin:8px 0 16px;font-size:.88rem}}
table.sortable th,table.sortable td{{border:1px solid #e2e8f0;padding:8px 10px;text-align:left}}
table.sortable th{{background:#f1f5f9}}
.gallery{{display:grid;grid-template-columns:1fr;gap:22px;margin:18px 0}}
figure.card{{margin:0;background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:10px}}
figure.card img{{width:100%;height:auto;border:1px solid #e2e8f0}}
figure.card figcaption{{margin:0 0 8px;font-size:.92rem}}
{SORT_CSS}
</style>
</head>
<body>
<p class="badge">Research pictures only · not gold · not DailyRun</p>
<h1>4-hour 3-month high-volume zone — VZ analog</h1>

<div class="ask">
<strong>What you asked</strong>
<blockquote>{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
</div>
<div class="plain">
<strong>In plain English</strong>
<p>{html_mod.escape(PLAIN_ENGLISH)}</p>
<p>Volume Zone (<strong>VZ</strong>) = house daily system that turns a rolling max-volume
bar into a High–Low support band, then buys a bounce / retest after price has broken above it.
Regular Trading Hours (<strong>RTH</strong>) = 09:30–16:00 ET.
Average True Range (<strong>ATR</strong>) is <em>not</em> used to fatten the 4h band
(house VZ zones are also raw High–Low). High Time Frame (<strong>HTF</strong>) here just
means the 4h chart — this is not the HTF chandelier stamp.</p>
</div>

<p class="meta">Stamp <code>{STAMP_NAME}</code> · universe PaulTwenty + UNH
({len(universe)} names) · {n_charts} charts.
4h bars resampled from Yahoo 1h (RTH), not from the ~39-session 1m store.
Click column headers to sort.</p>

<div class="cards">
<div class="stat"><h3>Charts</h3><div class="n">{n_charts}</div></div>
<div class="stat"><h3>Charted zones with retest-buy</h3><div class="n">{n_buy}</div></div>
<div class="stat"><h3>Charted zones that broke up</h3><div class="n">{n_break}</div></div>
<div class="stat"><h3>All-zone retest buys</h3><div class="n">{n_ev_buy}</div></div>
<div class="stat"><h3>All-zone failed tags</h3><div class="n">{n_ev_fail}</div></div>
</div>

<h2>One-line read</h2>
<p class="meta">{html_mod.escape(read)}</p>

<h2>How the 4h zone is defined vs house VZ</h2>
<p class="note">Same engine functions (<code>build_zones</code>, <code>detect_breaks</code>,
<code>generate_signals</code>). House daily lookback is 126 <em>days</em> (~6 months).
Here lookback is 126 <em>4h bars</em> (~63 sessions / ~3 calendar months) so “3-month
high-volume 4h bar” is the analog of VZ’s volume trigger. Zone = that bar’s High–Low.
Break = 4h close above the high. Buy = first from-above retest, next 4h open.
House DailyRun exits (atr4 floor, stop at zone.lo − 0.25×ATR, 1.5R, 20-bar time stop)
are <strong>not</strong> applied — pictures only.</p>

<h2>Charts</h2>
<p class="note">Click column headers to sort. One picture per name: the current 3-month
max-volume 4h bar (not an older lucky bounce).</p>
<table class="sortable">
<caption>Displayed 4h zones. Click column headers to sort.</caption>
<thead><tr>
{sortable_th("symbol", "text")}
{sortable_th("zone / max-vol 4h", "date")}
{sortable_th("zone lo", "num")}
{sortable_th("zone hi", "num")}
{sortable_th("volume", "num")}
{sortable_th("lookback calendar days", "num")}
{sortable_th("current 3m max-vol", "text")}
{sortable_th("broke up", "text")}
{sortable_th("break 4h", "date")}
{sortable_th("retest-buy", "text")}
{sortable_th("signal 4h", "date")}
{sortable_th("entry 4h", "date")}
{sortable_th("hold bounces", "num")}
{sortable_th("failed tags", "num")}
{sortable_th("chart", "text")}
</tr></thead>
<tbody>
{''.join(chart_tbl)}
</tbody>
</table>

<h2>Bounce / retest events (all HL zones)</h2>
<p class="note">Every first retest-buy and every post-break failed tag the engine marked
on this 1h→4h tape. Not a portfolio A/B. Click headers to sort.</p>
<table class="sortable">
<caption>Event list. Click column headers to sort.</caption>
<thead><tr>
{sortable_th("symbol", "text")}
{sortable_th("kind", "text")}
{sortable_th("zone max-vol", "date")}
{sortable_th("zone lo", "num")}
{sortable_th("zone hi", "num")}
{sortable_th("break", "date")}
{sortable_th("signal / tag", "date")}
{sortable_th("entry", "date")}
{sortable_th("entry px", "num")}
{sortable_th("bars after break", "num")}
</tr></thead>
<tbody>
{''.join(ev_tbl) if ev_tbl else '<tr><td colspan="10">No events.</td></tr>'}
</tbody>
</table>

<h2>4h coverage (Yahoo 1h → RTH 4h)</h2>
<p class="note">Need &gt;80 calendar days so the 3-month lookback is real. Shop 1m is
Jul–Sep 2026 only and was not used.</p>
<table class="sortable">
<caption>Data coverage. Click column headers to sort.</caption>
<thead><tr>
{sortable_th("symbol", "text")}
{sortable_th("4h bars", "num")}
{sortable_th("sessions", "num")}
{sortable_th("calendar days", "num")}
{sortable_th("first", "date")}
{sortable_th("last", "date")}
{sortable_th("HL zones", "num")}
{sortable_th("retest buys", "num")}
</tr></thead>
<tbody>
{''.join(cov_rows)}
</tbody>
</table>

<h2>Gallery</h2>
<p class="note">Orange dashed = 3-month max-volume 4h bar. Purple band = that bar’s
High–Low, extended forward. Green triangle = break-up. Pink circle = retest buy at
the next 4h open. Pink down-triangle = the signal bar’s low tag. Red X = failed tag
(closed through the zone low).</p>
<div class="gallery">
{''.join(gallery)}
</div>

{SORT_JS}
</body>
</html>
"""
    path = STAMP / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def main() -> int:
    STAMP.mkdir(parents=True, exist_ok=True)
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_1H.mkdir(parents=True, exist_ok=True)

    universe = frozen_universe()
    if not universe:
        raise SystemExit("PaulTwenty universe missing")

    coverage: list[dict[str, Any]] = []
    chart_rows: list[dict[str, Any]] = []
    all_events: list[dict[str, Any]] = []
    packs: list[dict[str, Any]] = []

    for i, sym in enumerate(universe):
        print(f"[{i+1}/{len(universe)}] {sym}", flush=True)
        try:
            pack = analyze_symbol(sym)
        except Exception as exc:  # noqa: BLE001 — surface per-name, keep gallery going
            pack = {"symbol": sym, "ok": False, "reason": str(exc)}
        slim = {k: v for k, v in pack.items() if k not in ("df", "zone_rows", "event_rows", "chosen")}
        if pack.get("ok"):
            slim.update(
                {
                    "n_4h": pack["n_4h"],
                    "n_sessions": pack["n_sessions"],
                    "cal_span_days": pack["cal_span_days"],
                    "first_4h": pack["first_4h"],
                    "last_4h": pack["last_4h"],
                    "n_hl_zones": pack["n_hl_zones"],
                    "n_retest_buys": pack["n_retest_buys"],
                    "n_breaks": pack["n_breaks"],
                }
            )
            all_events.extend(
                {k: v for k, v in e.items()} for e in pack["event_rows"]
            )
            packs.append(pack)
        coverage.append(slim)
        if i + 1 < len(universe):
            time.sleep(0.35)

    n = 0
    for pack in packs:
        chosen = pack.get("chosen")
        if not chosen:
            continue
        n += 1
        stem = f"{n:02d}_{pack['symbol']}_{chosen['max_vol_day'].replace('-', '')}"
        png = CHART_DIR / f"{stem}.png"
        plot_zone(pack, png)
        chart_rows.append(
            {
                **{k: v for k, v in chosen.items() if not k.startswith("_")},
                "rel": f"charts/{png.name}",
                "anchor": stem,
                "png": str(png),
            }
        )
        print(f"  chart {png.name} retest={chosen['retest_buy']}", flush=True)

    write_baseline(universe, coverage)
    write_hypothesis()

    ev_path = STAMP / "events.csv"
    if all_events:
        pd.DataFrame(all_events).to_csv(ev_path, index=False)
    else:
        pd.DataFrame(
            columns=[
                "symbol",
                "kind",
                "max_vol_ts",
                "zone_lo",
                "zone_hi",
                "volume",
                "break_ts",
                "signal_ts",
                "entry_ts",
                "entry_price",
                "bars_after_break",
            ]
        ).to_csv(ev_path, index=False)

    chart_csv_cols = [
        "symbol",
        "zone_id",
        "max_vol_ts",
        "zone_lo",
        "zone_hi",
        "volume",
        "lookback_cal_days",
        "broke_up",
        "break_ts",
        "retest_buy",
        "retest_ts",
        "entry_ts",
        "entry_price",
        "n_hold_bounces",
        "n_failed_tags",
        "is_current_3m",
        "rel",
    ]
    pd.DataFrame([{k: r.get(k, "") for k in chart_csv_cols} for r in chart_rows]).to_csv(
        STAMP / "charts.csv", index=False
    )

    html_path = write_html(
        universe=universe,
        coverage=coverage,
        chart_rows=chart_rows,
        event_rows=all_events,
    )
    summary = {
        "stamp": STAMP_NAME,
        "n_charts": len(chart_rows),
        "n_universe": len(universe),
        "n_ok": sum(1 for c in coverage if c.get("ok")),
        "n_chart_current_3m": sum(1 for r in chart_rows if r.get("is_current_3m")),
        "n_chart_retest_buy": sum(1 for r in chart_rows if r["retest_buy"]),
        "n_events_retest_buy": sum(1 for e in all_events if e["kind"] == "retest_buy"),
        "n_events_failed_tag": sum(1 for e in all_events if e["kind"] == "failed_tag"),
        "lookback_4h": LOOKBACK_4H,
        "retest_window_4h": RETEST_WINDOW_4H,
        "source": "yahoo_1h_rth_resample_4h",
        "html": str(html_path),
    }
    (STAMP / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return 0 if chart_rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
