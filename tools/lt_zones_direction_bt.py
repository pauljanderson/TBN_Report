#!/usr/bin/env python3
"""Historical backtest of LT-zones direction score (research).

Reuses scoring components from tools/lt_zones_direction_watch.py with daily-only
price (no 15m tilt) and as-of zones (weekly refresh, no lookahead).

Entry: next daily open after signal-bar close when |net_score| >= 50.
Exit arms: score thresholds 45/40/35/30, flip±50, and exit_40_ts40.

Research only — NOT financial advice, NOT KEEP/gold, NOT DailyRun.

Example:
  python tools/lt_zones_direction_bt.py
  python tools/lt_zones_direction_bt.py --limit 40 --workers 4
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import math
import os
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

import duckdb
import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
_TOOLS = Path(__file__).resolve().parent
_SA = _REPO / "stock_analysis"
_PE = _REPO / "drive" / "paul_experiments"
for _p in (_SA, _REPO, _TOOLS, _PE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import lt_zones_daily_to_15m as lt  # noqa: E402
import lt_zones_direction_watch as watch  # noqa: E402
from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    format_money,
    overlay_ann_ror_max_dd,
)

STAMP = "lt_zones_direction_bt_20260824"
DEFAULT_OUT = _PE / STAMP
DEFAULT_DB = _REPO / "data" / "ohlcv.duckdb"
IS_CUT = date(2024, 1, 1)

NEAR_PCT = 0.02
ENTRY_THRESH = 50.0
ZONE_REFRESH = 5  # trading days between zone recomputes
WARMUP = 260
MIN_BARS = 300
SHEET = 45_000.0
INIT_ACCT = DEFAULT_INITIAL_ACCOUNT
COSTS_BPS = 0.0
CONTROL_ARM = "exit_40"

EXIT_ARMS = [
    "exit_45",
    "exit_40",
    "exit_35",
    "exit_30",
    "flip_50",
    "exit_40_ts40",
]


def _sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


SORTABLE_TH_CSS = """
  th.sortable-th { cursor:pointer; user-select:none; white-space:nowrap; }
  th.sortable-th:hover { background:#e8e6df; }
  th.sortable-th .sort-ind::after { content:" \\u2195"; opacity:0.35; font-size:0.85em; }
  th.sortable-th.sort-asc .sort-ind::after { content:" \\u25B2"; opacity:0.9; }
  th.sortable-th.sort-desc .sort-ind::after { content:" \\u25BC"; opacity:0.9; }
"""

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
    Array.from(table.tHead ? table.tHead.rows[0].cells : []).forEach(function (th, col) {
      if (th.classList.contains("sortable-th")) bind(table, th, col);
    });
  });
})();
</script>
"""


def score_bar_daily(
    *,
    price: float,
    d_open: float,
    d_high: float,
    d_low: float,
    d_close: float,
    p_high: float,
    p_low: float,
    p_close: float,
    zones: list,
    near_pct: float = NEAR_PCT,
) -> float:
    """Daily-only net_score (mirrors watch.score_symbol without 15m tilt)."""
    if not np.isfinite(price) or price <= 0 or not zones:
        return float("nan")

    day_range = max(d_high - d_low, 1e-9)
    day_loc = (d_close - d_low) / day_range
    day_ret = (d_close - p_close) / max(p_close, 1e-9)

    yl = next((z for z in zones if z.zone_type == "yearly_low"), None)
    yh = next((z for z in zones if z.zone_type == "yearly_high"), None)
    poc = next((z for z in zones if z.zone_type == "poc"), None)

    yl_mid = float(yl.mid) if yl else float("nan")
    yh_mid = float(yh.mid) if yh else float("nan")
    poc_mid = float(poc.mid) if poc else float("nan")

    if np.isfinite(yl_mid) and np.isfinite(yh_mid) and yh_mid > yl_mid:
        yr_pos = float(np.clip((price - yl_mid) / (yh_mid - yl_mid), 0.0, 1.0))
        dist_yl = (price - yl_mid) / price
        dist_yh = (yh_mid - price) / price
    else:
        yr_pos = 0.5
        dist_yl = dist_yh = float("nan")

    up = 0.0
    down = 0.0

    sup, d_sup = watch._nearest_side(price, zones, side="support", near_pct=near_pct)
    if sup is not None and d_sup <= near_pct and price >= float(sup.lo) * 0.999:
        w = watch.TYPE_W.get(sup.zone_type, 0.4)
        prox = 1.0 - (d_sup / max(near_pct, 1e-9))
        pts = 42.0 * w * max(prox, 0.15)
        if getattr(sup, "confluence", None):
            pts *= 1.15
        up += pts

    res, d_res = watch._nearest_side(price, zones, side="resistance", near_pct=near_pct)
    if res is not None and d_res <= near_pct and price <= float(res.hi) * 1.001:
        w = watch.TYPE_W.get(res.zone_type, 0.4)
        prox = 1.0 - (d_res / max(near_pct, 1e-9))
        pts = 42.0 * w * max(prox, 0.15)
        if getattr(res, "confluence", None):
            pts *= 1.15
        failing = day_loc < 0.45 or price < float(res.mid)
        if failing:
            pts *= 1.1
        down += pts

    if poc is not None and np.isfinite(poc_mid):
        above_poc = price >= poc_mid
        prior_above = p_close >= poc_mid
        if above_poc and not prior_above:
            up += 14.0
        elif (not above_poc) and prior_above:
            down += 14.0
        elif above_poc:
            up += 6.0
        else:
            down += 6.0

    hvns = [z for z in zones if z.zone_type == "hvn"]
    if hvns:
        below = [z for z in hvns if z.mid <= price]
        above = [z for z in hvns if z.mid >= price]
        if below:
            zb = min(below, key=lambda z: watch._dist_to_zone(price, z))
            db = watch._dist_to_zone(price, zb)
            if db <= near_pct:
                up += 8.0 * (1.0 - db / near_pct)
        if above:
            za = min(above, key=lambda z: watch._dist_to_zone(price, z))
            da = watch._dist_to_zone(price, za)
            if da <= near_pct:
                down += 8.0 * (1.0 - da / near_pct)

    if np.isfinite(dist_yl) and np.isfinite(dist_yh):
        up += (1.0 - yr_pos) * 12.0
        down += yr_pos * 12.0
        if dist_yl <= near_pct:
            up += 18.0 * (1.0 - dist_yl / near_pct)
        if dist_yh <= near_pct:
            down += 18.0 * (1.0 - dist_yh / near_pct)

    if day_loc >= 0.70:
        up += 7.0
    elif day_loc <= 0.30:
        down += 7.0

    if price > p_high:
        up += 10.0
    elif price < p_low:
        down += 10.0

    if d_open > p_high:
        up += 4.0
    elif d_open < p_low:
        down += 4.0

    up += max(0.0, day_ret) * 180.0
    down += max(0.0, -day_ret) * 180.0

    # Historical BT: no 15m session tilt (live watch may add ±5).
    return float(up - down)


def _arm_exit_thresh(arm: str) -> Optional[float]:
    if arm.startswith("exit_") and not arm.endswith("_ts40"):
        return float(arm.split("_", 1)[1])
    if arm == "exit_40_ts40":
        return 40.0
    if arm == "flip_50":
        return None
    raise ValueError(arm)


def _arm_time_stop(arm: str) -> Optional[int]:
    if arm == "exit_40_ts40":
        return 40
    return None


def load_symbol_df(con: duckdb.DuckDBPyConnection, symbol: str) -> pd.DataFrame:
    df = con.execute(
        """
        SELECT date AS Date, open AS Open, high AS High, low AS Low,
               close AS Close, volume AS Volume
        FROM prices
        WHERE symbol = ?
        ORDER BY date
        """,
        [symbol],
    ).df()
    if df.empty:
        return df
    df["Date"] = pd.to_datetime(df["Date"]).dt.normalize()
    for c in ("Open", "High", "Low", "Close", "Volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=["Open", "High", "Low", "Close"]).reset_index(drop=True)


def build_net_scores(
    df: pd.DataFrame,
    symbol: str,
    *,
    near_pct: float = NEAR_PCT,
    zone_refresh: int = ZONE_REFRESH,
    warmup: int = WARMUP,
) -> np.ndarray:
    n = len(df)
    scores = np.full(n, np.nan, dtype=float)
    if n < warmup + 2:
        return scores

    opens = df["Open"].to_numpy(float)
    highs = df["High"].to_numpy(float)
    lows = df["Low"].to_numpy(float)
    closes = df["Close"].to_numpy(float)

    zones: list = []
    last_z = -10**9
    for i in range(warmup, n):
        if (i - last_z) >= zone_refresh or not zones:
            zones = lt.compute_lt_zones(
                df.iloc[: i + 1],
                symbol,
                include_lvn=False,
                max_swing=6,
            )
            last_z = i
        if not zones:
            continue
        scores[i] = score_bar_daily(
            price=closes[i],
            d_open=opens[i],
            d_high=highs[i],
            d_low=lows[i],
            d_close=closes[i],
            p_high=highs[i - 1],
            p_low=lows[i - 1],
            p_close=closes[i - 1],
            zones=zones,
            near_pct=near_pct,
        )
    return scores


def simulate_arm(
    df: pd.DataFrame,
    scores: np.ndarray,
    symbol: str,
    arm: str,
    *,
    entry_thresh: float = ENTRY_THRESH,
) -> list[dict[str, Any]]:
    n = len(df)
    exit_thr = _arm_exit_thresh(arm)
    time_stop = _arm_time_stop(arm)
    trades: list[dict[str, Any]] = []

    dates = df["Date"].tolist()
    opens = df["Open"].to_numpy(float)
    closes = df["Close"].to_numpy(float)

    i = WARMUP
    while i < n - 2:
        net = scores[i]
        if not np.isfinite(net):
            i += 1
            continue
        side = 0
        if net >= entry_thresh:
            side = 1
        elif net <= -entry_thresh:
            side = -1
        else:
            i += 1
            continue

        entry_i = i + 1
        if entry_i >= n:
            break
        entry_px = float(opens[entry_i])
        if not np.isfinite(entry_px) or entry_px <= 0:
            i += 1
            continue

        signal_net = float(net)
        signal_date = dates[i]
        opened = dates[entry_i]
        exit_i = None
        exit_px = None
        exit_type = "SCORE"
        last = n - 1
        if time_stop is not None:
            last = min(entry_i + time_stop, n - 1)

        for j in range(entry_i, last + 1):
            # evaluate exit on bar j close (score uses close); fill next open when possible
            sj = scores[j]
            if not np.isfinite(sj):
                continue
            hit = False
            if exit_thr is not None:
                if side > 0 and sj < exit_thr:
                    hit = True
                    exit_type = "SCORE"
                elif side < 0 and sj > -exit_thr:
                    hit = True
                    exit_type = "SCORE"
            else:
                # flip_50: opposite extreme
                if side > 0 and sj <= -entry_thresh:
                    hit = True
                    exit_type = "FLIP"
                elif side < 0 and sj >= entry_thresh:
                    hit = True
                    exit_type = "FLIP"

            if hit:
                # exit next open after signal close; same-bar open if last bar
                if j + 1 < n:
                    exit_i = j + 1
                    exit_px = float(opens[exit_i])
                else:
                    exit_i = j
                    exit_px = float(closes[j])
                    exit_type = "EOD"
                break

            if time_stop is not None and j >= entry_i + time_stop:
                exit_i = j
                exit_px = float(closes[j])
                exit_type = "TIME"
                break

        if exit_i is None:
            exit_i = last
            exit_px = float(closes[exit_i])
            exit_type = "EOD" if exit_i == n - 1 else "TIME"

        if not np.isfinite(exit_px) or exit_px <= 0:
            i = max(exit_i, i + 1)
            continue

        closed = dates[exit_i]
        if side > 0:
            pnl_pct = (exit_px - entry_px) / entry_px * 100.0
        else:
            pnl_pct = (entry_px - exit_px) / entry_px * 100.0
        if COSTS_BPS:
            pnl_pct -= COSTS_BPS / 100.0

        days = max(int((closed - opened).days), 1)
        entry_d = opened.date() if hasattr(opened, "date") else opened
        slice_tag = "IS" if entry_d < IS_CUT else "OOS"

        trades.append(
            {
                "sym": symbol,
                "arm": arm,
                "side": "LONG" if side > 0 else "SHORT",
                "opened": opened,
                "closed": closed,
                "entry": entry_px,
                "exit_px": float(exit_px),
                "exit": exit_type,
                "pnl": float(pnl_pct),
                "days": float(days),
                "pnl_d": float(pnl_pct) / 100.0 * SHEET,
                "signal_date": signal_date,
                "signal_net": signal_net,
                "exit_net": float(scores[exit_i]) if np.isfinite(scores[min(exit_i, n - 1)]) else float("nan"),
                "slice": slice_tag,
            }
        )
        i = exit_i + 1
    return trades


def process_symbol_chunk(
    args: tuple[str, list[str], str, float, int, int],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    db_path, symbols, _unused, near_pct, zone_refresh, warmup = args
    con = duckdb.connect(db_path, read_only=True)
    all_trades: list[dict[str, Any]] = []
    meta = {"ok": 0, "skip_short": 0, "skip_empty": 0, "errors": 0, "scored_bars": 0}
    try:
        for sym in symbols:
            try:
                df = load_symbol_df(con, sym)
                if df.empty:
                    meta["skip_empty"] += 1
                    continue
                if len(df) < MIN_BARS:
                    meta["skip_short"] += 1
                    continue
                scores = build_net_scores(
                    df,
                    sym,
                    near_pct=near_pct,
                    zone_refresh=zone_refresh,
                    warmup=warmup,
                )
                meta["scored_bars"] += int(np.isfinite(scores).sum())
                for arm in EXIT_ARMS:
                    all_trades.extend(
                        simulate_arm(df, scores, sym, arm, entry_thresh=ENTRY_THRESH)
                    )
                meta["ok"] += 1
            except Exception:
                meta["errors"] += 1
    finally:
        con.close()
    return all_trades, meta


def book_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(trades)
    empty = {
        "n": 0,
        "wins": 0,
        "losses": 0,
        "wr": 0.0,
        "avg_pnl": 0.0,
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
    calmar = float("nan")
    if (
        math.isfinite(ov.get("ann_ror", float("nan")))
        and math.isfinite(ov.get("max_dd", float("nan")))
        and abs(ov["max_dd"]) > 1e-9
    ):
        calmar = ov["ann_ror"] / abs(ov["max_dd"])
    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "wr": 100.0 * len(wins) / n,
        "avg_pnl": float(np.mean(pnls)),
        "pf": (gp / gl) if gl > 0 else (gp if gp > 0 else 0.0),
        "sheet": sum(t["pnl_d"] for t in trades),
        "pnl_d": sum(t["pnl_d"] for t in trades),
        "avg_days": float(np.mean([t["days"] for t in trades])),
        "avg_win": float(np.mean(wins)) if wins else float("nan"),
        "avg_loss": float(np.mean(losses)) if losses else float("nan"),
        "wo_max": float(wo),
        "exp_pct": float(np.mean(pnls)),
        "ann_ror": ov.get("ann_ror", float("nan")),
        "max_dd": ov.get("max_dd", float("nan")),
        "calmar": calmar,
        "cap_days": ov.get("capital_days", 0.0),
        "exits": dict(Counter(t["exit"] for t in trades)),
        "syms": len({t["sym"] for t in trades}),
        "long_n": sum(1 for t in trades if t["side"] == "LONG"),
        "short_n": sum(1 for t in trades if t["side"] == "SHORT"),
    }


def _fmt(v: Any, kind: str = "num") -> str:
    if v is None:
        return "—"
    if isinstance(v, float) and not math.isfinite(v):
        return "—"
    if kind == "money":
        return format_money(v)
    if kind == "pct":
        return f"{float(v):.2f}%"
    if kind == "int":
        return str(int(v))
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def write_closed_csv(path: Path, trades: list[dict[str, Any]]) -> None:
    cols = [
        "SYMBOL",
        "ARM",
        "SIDE",
        "SIGNAL_DATE",
        "ENTRY_DATE",
        "EXIT_DATE",
        "ENTRY_PX",
        "EXIT_PX",
        "EXIT_TYPE",
        "SIGNAL_NET",
        "PNL_PCT",
        "PNL_DOLLARS",
        "DAYS_HELD",
        "SLICE",
    ]
    rows = []
    for t in trades:
        rows.append(
            {
                "SYMBOL": t["sym"],
                "ARM": t["arm"],
                "SIDE": t["side"],
                "SIGNAL_DATE": pd.Timestamp(t["signal_date"]).date().isoformat(),
                "ENTRY_DATE": pd.Timestamp(t["opened"]).date().isoformat(),
                "EXIT_DATE": pd.Timestamp(t["closed"]).date().isoformat(),
                "ENTRY_PX": f"{t['entry']:.4f}",
                "EXIT_PX": f"{t['exit_px']:.4f}",
                "EXIT_TYPE": t["exit"],
                "SIGNAL_NET": f"{t['signal_net']:.2f}",
                "PNL_PCT": f"{t['pnl']:.4f}",
                "PNL_DOLLARS": f"{t['pnl_d']:.2f}",
                "DAYS_HELD": f"{t['days']:.0f}",
                "SLICE": t["slice"],
            }
        )
    pd.DataFrame(rows, columns=cols).to_csv(path, index=False)


def write_summary_csv(path: Path, trades: list[dict[str, Any]], arm: str) -> None:
    sub = [t for t in trades if t["arm"] == arm]
    if not sub:
        pd.DataFrame().to_csv(path, index=False)
        return
    rows = []
    for sym, g in pd.DataFrame(sub).groupby("sym"):
        pnls = g["pnl"].astype(float).tolist()
        n = len(pnls)
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        gp, gl = sum(wins), abs(sum(losses))
        rows.append(
            {
                "SYMBOL": sym,
                "N": n,
                "WR": round(100.0 * len(wins) / n, 2) if n else 0.0,
                "AVG_PNL_PCT": round(float(np.mean(pnls)), 4),
                "PF": round((gp / gl) if gl > 0 else (gp if gp > 0 else 0.0), 3),
                "SHEET_PNL": round(float(g["pnl_d"].sum()), 2),
                "AVG_DAYS": round(float(g["days"].mean()), 1),
                "LONG_N": int((g["side"] == "LONG").sum()),
                "SHORT_N": int((g["side"] == "SHORT").sum()),
                "IS_N": int((g["slice"] == "IS").sum()),
                "OOS_N": int((g["slice"] == "OOS").sum()),
            }
        )
    pd.DataFrame(rows).sort_values("SHEET_PNL", ascending=False).to_csv(path, index=False)


def write_metrics_csv(path: Path, by_arm_slice: dict[str, dict[str, dict]]) -> None:
    rows = []
    for arm in EXIT_ARMS:
        for sl in ("ALL", "IS", "OOS"):
            s = by_arm_slice[arm][sl]
            rows.append(
                {
                    "ARM": arm,
                    "SLICE": sl,
                    "N": s["n"],
                    "SYMS": s["syms"],
                    "WR": round(s["wr"], 2),
                    "AVG_PNL_PCT": round(s["avg_pnl"], 4),
                    "PF": round(s["pf"], 3),
                    "SHEET_PNL": round(s["sheet"], 2),
                    "AVG_DAYS": round(s["avg_days"], 2),
                    "AVG_PNL_PCT_WO_MAX": round(s["wo_max"], 4),
                    "ANN_ROR": None if not math.isfinite(s["ann_ror"]) else round(s["ann_ror"], 2),
                    "MAX_DD": None if not math.isfinite(s["max_dd"]) else round(s["max_dd"], 2),
                    "CALMAR": None if not math.isfinite(s["calmar"]) else round(s["calmar"], 3),
                    "LONG_N": s["long_n"],
                    "SHORT_N": s["short_n"],
                    "EXITS": json.dumps(s["exits"]),
                }
            )
    pd.DataFrame(rows).to_csv(path, index=False)


def write_compare_html(
    path: Path,
    by_arm_slice: dict[str, dict[str, dict]],
    meta: dict,
) -> None:
    headers = [
        ("Arm", "text"),
        ("Slice", "text"),
        ("N", "num"),
        ("Syms", "num"),
        ("WR%", "num"),
        ("Avg PnL%", "num"),
        ("PF", "num"),
        ("Sheet PnL $", "num"),
        ("Avg days", "num"),
        ("WO max Avg%", "num"),
        ("Ann ROR%", "num"),
        ("Max DD%", "num"),
        ("Calmar", "num"),
        ("Long N", "num"),
        ("Short N", "num"),
    ]
    ths = "".join(_sortable_th(h, t) for h, t in headers)
    body_rows = []
    for arm in EXIT_ARMS:
        for sl in ("IS", "OOS", "ALL"):
            s = by_arm_slice[arm][sl]
            ctrl = " control" if arm == CONTROL_ARM and sl == "ALL" else ""
            cells = [
                arm,
                sl,
                _fmt(s["n"], "int"),
                _fmt(s["syms"], "int"),
                _fmt(s["wr"], "pct"),
                _fmt(s["avg_pnl"]),
                _fmt(s["pf"]),
                _fmt(s["sheet"], "money"),
                _fmt(s["avg_days"]),
                _fmt(s["wo_max"]),
                _fmt(s["ann_ror"], "pct") if math.isfinite(s["ann_ror"]) else "—",
                _fmt(s["max_dd"], "pct") if math.isfinite(s["max_dd"]) else "—",
                _fmt(s["calmar"]) if math.isfinite(s["calmar"]) else "—",
                _fmt(s["long_n"], "int"),
                _fmt(s["short_n"], "int"),
            ]
            tds = "".join(f"<td>{html_mod.escape(str(c))}</td>" for c in cells)
            body_rows.append(f'<tr class="{sl.lower()}{ctrl}">{tds}</tr>')

    # Wide IS+OOS side-by-side for control vs exits
    wide_headers = [
        ("Arm", "text"),
        ("IS N", "num"),
        ("IS WR%", "num"),
        ("IS Avg%", "num"),
        ("IS PF", "num"),
        ("IS Sheet $", "num"),
        ("IS AnnROR%", "num"),
        ("IS MaxDD%", "num"),
        ("OOS N", "num"),
        ("OOS WR%", "num"),
        ("OOS Avg%", "num"),
        ("OOS PF", "num"),
        ("OOS Sheet $", "num"),
        ("OOS AnnROR%", "num"),
        ("OOS MaxDD%", "num"),
    ]
    wths = "".join(_sortable_th(h, t) for h, t in wide_headers)
    wide_rows = []
    for arm in EXIT_ARMS:
        isi, oos = by_arm_slice[arm]["IS"], by_arm_slice[arm]["OOS"]
        cells = [
            arm + (" *" if arm == CONTROL_ARM else ""),
            _fmt(isi["n"], "int"),
            _fmt(isi["wr"], "pct"),
            _fmt(isi["avg_pnl"]),
            _fmt(isi["pf"]),
            _fmt(isi["sheet"], "money"),
            _fmt(isi["ann_ror"], "pct") if math.isfinite(isi["ann_ror"]) else "—",
            _fmt(isi["max_dd"], "pct") if math.isfinite(isi["max_dd"]) else "—",
            _fmt(oos["n"], "int"),
            _fmt(oos["wr"], "pct"),
            _fmt(oos["avg_pnl"]),
            _fmt(oos["pf"]),
            _fmt(oos["sheet"], "money"),
            _fmt(oos["ann_ror"], "pct") if math.isfinite(oos["ann_ror"]) else "—",
            _fmt(oos["max_dd"], "pct") if math.isfinite(oos["max_dd"]) else "—",
        ]
        tds = "".join(f"<td>{html_mod.escape(str(c))}</td>" for c in cells)
        wide_rows.append(f"<tr>{tds}</tr>")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>{STAMP} — exit compare</title>
<style>
  body {{ font-family: Georgia, 'Times New Roman', serif; margin: 24px; background:#f7f6f2; color:#1a1a1a; }}
  h1 {{ font-size: 1.45rem; margin-bottom: 0.2rem; }}
  .sub {{ color:#555; margin-bottom: 1.2rem; }}
  table.sortable {{ border-collapse: collapse; width: 100%; background:#fff; margin: 1rem 0 2rem; font-size: 0.92rem; }}
  th, td {{ border: 1px solid #ddd; padding: 6px 8px; text-align: left; }}
  th {{ background:#eeeae2; }}
  tr.control {{ background:#eef6ee; }}
  tr.oos {{ background:#fff8f0; }}
  .note {{ max-width: 920px; line-height: 1.45; }}
  {SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>LT zones direction score — historical BT exit compare</h1>
<p class="sub">Stamp <code>{STAMP}</code> · as-of {html_mod.escape(meta.get('asof',''))} ·
symbols scored {meta.get('n_ok')} / {meta.get('n_universe')} ·
zone refresh {meta.get('zone_refresh')} bars · entry next open · |net|≥{ENTRY_THRESH:g} ·
sheet {format_money(SHEET)} · IS cut {IS_CUT.isoformat()} · research only · click headers to sort</p>
<p class="note">Control arm for freeze discussion: <strong>{CONTROL_ARM}</strong> (middle of score-exit grid).
Do not KEEP from IS cherry-pick. OOS is report-only. Daily-only score (no 15m tilt). Weekly zone refresh — no lookahead.</p>
<h2>IS vs OOS by exit arm</h2>
<table class="sortable"><thead><tr>{wths}</tr></thead><tbody>
{''.join(wide_rows)}
</tbody></table>
<h2>Full book (IS / OOS / ALL)</h2>
<table class="sortable"><thead><tr>{ths}</tr></thead><tbody>
{''.join(body_rows)}
</tbody></table>
{SORT_JS}
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def _mfmt(v: float, nd: int = 1) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    return f"{float(v):.{nd}f}"


def write_baseline(path: Path, meta: dict, by_arm_slice: dict) -> None:
    ctrl = by_arm_slice[CONTROL_ARM]

    def _row(sl: str) -> str:
        s = ctrl[sl]
        return (
            f"| {sl} | {s['n']} | {s['wr']:.1f} | {s['avg_pnl']:.2f} | {s['pf']:.2f} | "
            f"{s['sheet']:,.0f} | {_mfmt(s['ann_ror'])} | {_mfmt(s['max_dd'])} |"
        )

    path.write_text(
        f"""# BASELINE — LT zones direction score historical BT (research)

**Stamp:** `{STAMP}`  
**As-of:** {meta.get('asof')}  
**Status:** research heuristic backtest only — **not** financial advice, **not** gold, **not** DailyRun-wired.

## Hypothesis

Does the live LT-zones **direction score** (|net| ≥ 50 lean) have any forward predictive value when traded historically with score-based exits?

## Freeze

| Knob | Value |
|------|-------|
| Entry | **Next daily open** after signal-bar close |
| Long | `net_score >= {ENTRY_THRESH:g}` |
| Short | `net_score <= -{ENTRY_THRESH:g}` |
| Score engine | Same components as `tools/lt_zones_direction_watch.score_symbol` |
| Price / context | **Daily close only** (15m tilt **omitted** vs live watch) |
| Zones | `lt.compute_lt_zones(..., include_lvn=False, max_swing=6)` on as-of history |
| Zone refresh | Every **{ZONE_REFRESH}** trading days (stale between refreshes; **no lookahead**) |
| Near % | {NEAR_PCT * 100:.1f}% |
| Warmup | {WARMUP} bars before first score |
| Sizing | Sheet ${SHEET:,.0f} per trade; Initial_Account ${INIT_ACCT:,.0f} for Max DD overlay |
| Costs | {COSTS_BPS} bps |
| One position | Per symbol; resume after exit |
| Control arm | `{CONTROL_ARM}` (not selected from OOS) |

### Exit arms (grid — label selection bias if crowning a winner)

| Arm | Rule |
|-----|------|
| `exit_45` / `40` / `35` / `30` | Long exit when net &lt; thr; short when net &gt; −thr; fill next open |
| `flip_50` | Hold until opposite ±50 signal |
| `exit_40_ts40` | Score exit 40 **or** time-stop 40 bars (close) |

## Universe / data

| Item | Value |
|------|-------|
| Source | `data/ohlcv.duckdb` table `prices` |
| Symbols attempted | {meta.get('n_universe')} |
| Symbols scored | {meta.get('n_ok')} |
| Skipped short / empty / err | {meta.get('skip_short')} / {meta.get('skip_empty')} / {meta.get('errors')} |
| Date range (data) | {meta.get('date_min')} → {meta.get('date_max')} |
| IS / OOS | entry_date &lt; {IS_CUT.isoformat()} vs ≥ |

## Control book snapshot (`{CONTROL_ARM}`)

| Slice | N | WR% | Avg PnL% | PF | Sheet PnL | Ann ROR% | Max DD% |
|-------|---|-----|----------|----|-----------|----------|---------|
{_row('IS')}
{_row('OOS')}
{_row('ALL')}

## Anti-overfit

- OOS is **report-only** — do not retune entry/exit on OOS.
- Picking the best exit from this grid is **in-sample selection bias** even if OOS is printed afterward.
- Quality over trade count; if OOS softens vs IS → **HOLD**.
- Research candidate ≠ gold ≠ DailyRun.

## Disclaimer

Educational / research only. Not trade instructions.
""",
        encoding="utf-8",
    )


def write_summary_md(
    path: Path,
    by_arm_slice: dict,
    meta: dict,
    verdict: str,
    verdict_note: str,
) -> None:
    lines = [
        f"# SUMMARY — `{STAMP}`",
        "",
        f"**Verdict:** **{verdict}** — {verdict_note}",
        "",
        "Research only. Not advice. Not DailyRun.",
        "",
        f"- Symbols scored: **{meta.get('n_ok')}** / {meta.get('n_universe')}",
        f"- Data: `{meta.get('date_min')}` → `{meta.get('date_max')}`",
        f"- Entry: next open after |net|≥{ENTRY_THRESH:g}; daily-only score; zone refresh {ZONE_REFRESH}d",
        f"- Control: `{CONTROL_ARM}`",
        "",
        "## Exit grid (IS / OOS)",
        "",
        "| Arm | IS N | IS WR | IS Avg% | IS PF | IS Sheet | OOS N | OOS WR | OOS Avg% | OOS PF | OOS Sheet |",
        "|-----|------|-------|---------|-------|----------|-------|--------|----------|--------|-----------|",
    ]
    for arm in EXIT_ARMS:
        isi, oos = by_arm_slice[arm]["IS"], by_arm_slice[arm]["OOS"]
        mark = " *" if arm == CONTROL_ARM else ""
        lines.append(
            f"| `{arm}`{mark} | {isi['n']} | {isi['wr']:.1f}% | {isi['avg_pnl']:.2f} | {isi['pf']:.2f} | "
            f"{format_money(isi['sheet'])} | {oos['n']} | {oos['wr']:.1f}% | {oos['avg_pnl']:.2f} | "
            f"{oos['pf']:.2f} | {format_money(oos['sheet'])} |"
        )
    lines.extend(
        [
            "",
            "## Files",
            "",
            f"- `compare.html` — sortable exit compare",
            f"- `LTDZ_Closed_{STAMP[-8:]}.csv` — all arms trades",
            f"- `LTDZ_Metrics_{STAMP[-8:]}.csv` — book metrics by arm×slice",
            f"- `LTDZ_Summary_{CONTROL_ARM}_{STAMP[-8:]}.csv` — per-symbol (control)",
            f"- `BASELINE.md`",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def decide_verdict(by_arm_slice: dict) -> tuple[str, str]:
    """Quality-first; no KEEP from IS cherry-pick; OOS soften → HOLD."""
    ctrl = by_arm_slice[CONTROL_ARM]
    isi, oos = ctrl["IS"], ctrl["OOS"]
    if isi["n"] < 30 or oos["n"] < 15:
        return "HOLD", "Insufficient trade count on control for a KEEP claim."

    # Predictive value: WR>50 with PF>1 and positive avg on both slices is a soft bar;
    # still HOLD unless OOS quality holds without being a cherry-picked exit.
    is_ok = isi["avg_pnl"] > 0 and isi["pf"] > 1.0 and isi["wr"] >= 50.0
    oos_ok = oos["avg_pnl"] > 0 and oos["pf"] > 1.0 and oos["wr"] >= 48.0

    if not is_ok:
        return "DISMISS", (
            f"Control `{CONTROL_ARM}` IS quality weak "
            f"(WR {isi['wr']:.1f}%, Avg {isi['avg_pnl']:.2f}%, PF {isi['pf']:.2f})."
        )

    if is_ok and not oos_ok:
        return "HOLD", (
            f"IS looked usable but OOS softened "
            f"(WR {oos['wr']:.1f}%, Avg {oos['avg_pnl']:.2f}%, PF {oos['pf']:.2f}) — do not retune on OOS."
        )

    # Both positive — still research-only HOLD/LEAN; never KEEP from single freeze grid.
    best_is = max(EXIT_ARMS, key=lambda a: by_arm_slice[a]["IS"]["avg_pnl"])
    if best_is != CONTROL_ARM:
        return "HOLD", (
            f"Control and OOS both positive on quality, but best IS arm is `{best_is}` "
            f"— selection bias risk; treat as research candidate only (not KEEP)."
        )
    return "HOLD", (
        "Control quality positive IS+OOS but single-study / research-only — "
        "not KEEP; needs walk-forward / wider confirmation before any promotion talk."
    )


def chunked(xs: list[str], n_chunks: int) -> list[list[str]]:
    n_chunks = max(1, min(n_chunks, len(xs) or 1))
    out: list[list[str]] = [[] for _ in range(n_chunks)]
    for i, x in enumerate(xs):
        out[i % n_chunks].append(x)
    return [c for c in out if c]


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--limit", type=int, default=0, help="Cap symbols (0=all)")
    ap.add_argument("--workers", type=int, default=max(1, min(8, (os.cpu_count() or 4))))
    ap.add_argument("--zone-refresh", type=int, default=ZONE_REFRESH)
    ap.add_argument("--near-pct", type=float, default=NEAR_PCT)
    args = ap.parse_args(argv)

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    asof = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    stamp_tail = STAMP[-8:]

    con = duckdb.connect(str(args.db), read_only=True)
    try:
        syms = [
            str(r[0]).strip().upper()
            for r in con.execute(
                """
                SELECT symbol FROM prices
                GROUP BY symbol
                HAVING COUNT(*) >= ?
                ORDER BY symbol
                """,
                [MIN_BARS],
            ).fetchall()
            if str(r[0]).strip()
        ]
        dr = con.execute("SELECT MIN(date), MAX(date) FROM prices").fetchone()
        date_min, date_max = str(dr[0]), str(dr[1])
    finally:
        con.close()

    if args.limit and args.limit > 0:
        syms = syms[: args.limit]

    n_univ = len(syms)
    print(f"[lt_dir_bt] symbols={n_univ} workers={args.workers} out={out_dir}", flush=True)
    t0 = time.perf_counter()

    chunks = chunked(syms, args.workers)
    tasks = [
        (str(args.db), ch, "", float(args.near_pct), int(args.zone_refresh), WARMUP)
        for ch in chunks
    ]

    all_trades: list[dict[str, Any]] = []
    agg_meta = Counter()
    if args.workers <= 1 or len(tasks) == 1:
        for task in tasks:
            trades, m = process_symbol_chunk(task)
            all_trades.extend(trades)
            for k, v in m.items():
                agg_meta[k] += v
            print(f"  done chunk n={len(task[1])} ok={m['ok']}", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(process_symbol_chunk, t): t for t in tasks}
            for fut in as_completed(futs):
                trades, m = fut.result()
                all_trades.extend(trades)
                for k, v in m.items():
                    agg_meta[k] += v
                print(f"  chunk done ok={m['ok']} trades+={len(trades)}", flush=True)

    elapsed = time.perf_counter() - t0
    print(
        f"[lt_dir_bt] scored_syms={agg_meta['ok']} trades={len(all_trades)} "
        f"elapsed={elapsed:.1f}s",
        flush=True,
    )

    by_arm_slice: dict[str, dict[str, dict]] = {}
    for arm in EXIT_ARMS:
        arm_trades = [t for t in all_trades if t["arm"] == arm]
        by_arm_slice[arm] = {
            "ALL": book_stats(arm_trades),
            "IS": book_stats([t for t in arm_trades if t["slice"] == "IS"]),
            "OOS": book_stats([t for t in arm_trades if t["slice"] == "OOS"]),
        }

    meta = {
        "asof": asof,
        "n_universe": n_univ,
        "n_ok": int(agg_meta["ok"]),
        "skip_short": int(agg_meta["skip_short"]),
        "skip_empty": int(agg_meta["skip_empty"]),
        "errors": int(agg_meta["errors"]),
        "date_min": date_min,
        "date_max": date_max,
        "zone_refresh": int(args.zone_refresh),
        "elapsed_sec": round(elapsed, 1),
        "workers": args.workers,
        "entry": "next_open",
        "entry_thresh": ENTRY_THRESH,
        "near_pct": args.near_pct,
        "sheet": SHEET,
        "control_arm": CONTROL_ARM,
    }

    closed_path = out_dir / f"LTDZ_Closed_{stamp_tail}.csv"
    metrics_path = out_dir / f"LTDZ_Metrics_{stamp_tail}.csv"
    summary_path = out_dir / f"LTDZ_Summary_{CONTROL_ARM}_{stamp_tail}.csv"
    html_path = out_dir / "compare.html"

    write_closed_csv(closed_path, all_trades)
    write_metrics_csv(metrics_path, by_arm_slice)
    write_summary_csv(summary_path, all_trades, CONTROL_ARM)
    write_compare_html(html_path, by_arm_slice, meta)

    verdict, note = decide_verdict(by_arm_slice)
    write_baseline(out_dir / "BASELINE.md", meta, by_arm_slice)
    write_summary_md(out_dir / "SUMMARY.md", by_arm_slice, meta, verdict, note)
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"[lt_dir_bt] verdict={verdict} — {note}", flush=True)
    print(f"[lt_dir_bt] wrote {html_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
