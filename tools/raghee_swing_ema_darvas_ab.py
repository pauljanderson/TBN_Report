#!/usr/bin/env python3
"""Raghee-derived daily swing A/B: 34 EMA pullback vs + Darvas box context.

One-knob ENTRY A/B (System A1). Long-only. Same exit both arms.
Research-only — not gold, not DailyRun. No VScore / GRaB / Propulsion Dots.

Usage:
  python tools/raghee_swing_ema_darvas_ab.py
  python tools/raghee_swing_ema_darvas_ab.py --universe SPY,QQQ
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import math
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    format_money,
    overlay_ann_ror_max_dd,
)

DRIVE = ROOT / "drive"
DATA_DIR = ROOT / "data" / "newdata" / "data"
STAMP = "20260821"
OUT_DIR = DRIVE / "paul_experiments" / f"raghee_swing_ema_darvas_{STAMP}"
PAULTWENTY = DRIVE / "universes" / "PaulTwenty_universe.csv"
IS_CUT = date(2024, 1, 1)

# --- Freeze (also stamped in BASELINE.md) ---
EMA_SPAN = 34
EMA_SLOPE_N = 5
BOX_LOOKBACK = 20
BOX_MAX_WIDTH_PCT = 15.0  # consolidation width vs mid
ATR_N = 14
STOP_ATR_MULT = 1.5
TARGET_R = 1.5
TIME_STOP_BARS = 40
MIN_PRICE = 10.0
MIN_ADV20 = 1_000_000.0
SHEET = 45_000.0
INIT_ACCT = DEFAULT_INITIAL_ACCOUNT
COSTS_BPS = 0.0  # research: 0 bps


def sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


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
    table.querySelectorAll("th.sortable-th").forEach(function (th, col) {
      bind(table, th, col);
    });
  });
})();
</script>
"""

SORT_CSS = """
th.sortable-th { cursor: pointer; user-select: none; white-space: nowrap; }
th.sortable-th:hover { background: #e2e8f0; }
th.sortable-th .sort-ind::after { content: " \\2195"; opacity: .35; font-size: .85em; }
th.sortable-th.sort-asc .sort-ind::after { content: " \\2191"; opacity: .9; }
th.sortable-th.sort-desc .sort-ind::after { content: " \\2193"; opacity: .9; }
"""


def load_universe(path: Path) -> list[str]:
    out: list[str] = []
    with path.open(encoding="utf-8-sig") as f:
        for line in f:
            s = line.strip().upper()
            if not s or s.startswith("#") or s == "SYMBOL":
                continue
            out.append(s.split(",")[0].strip())
    return out


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


def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int) -> np.ndarray:
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


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    vol = df["Volume"].astype(float)
    ema = close.ewm(span=EMA_SPAN, adjust=False).mean()
    slope = ema - ema.shift(EMA_SLOPE_N)
    adv20 = vol.rolling(20, min_periods=20).mean()
    atr = _atr(high.to_numpy(), low.to_numpy(), close.to_numpy(), ATR_N)
    out = df.copy()
    out["ema34"] = ema
    out["ema_slope"] = slope
    out["adv20"] = adv20
    out["atr"] = atr
    # Prior-bar box (no look-ahead into signal bar)
    box_h = high.shift(1).rolling(BOX_LOOKBACK, min_periods=BOX_LOOKBACK).max()
    box_l = low.shift(1).rolling(BOX_LOOKBACK, min_periods=BOX_LOOKBACK).min()
    mid = (box_h + box_l) / 2.0
    width_pct = (box_h - box_l) / mid.replace(0, np.nan) * 100.0
    out["box_high"] = box_h
    out["box_low"] = box_l
    out["box_width_pct"] = width_pct
    out["box_l8"] = box_l + 0.125 * (box_h - box_l)
    out["box_active"] = (
        (width_pct <= BOX_MAX_WIDTH_PCT)
        & (mid > ema)
        & box_h.notna()
        & box_l.notna()
    )
    return out


def signal_control(row: pd.Series, prev: pd.Series) -> bool:
    """Pullback to 34 EMA: touch/cross from above in rising-EMA uptrend."""
    if not (
        row["Close"] > row["ema34"]
        and row["ema_slope"] >= 0
        and prev["Close"] > prev["ema34"]
        and row["Low"] <= row["ema34"]
        and row["Close"] >= MIN_PRICE
        and row["adv20"] >= MIN_ADV20
        and math.isfinite(float(row["atr"]))
        and float(row["atr"]) > 0
    ):
        return False
    return True


def signal_darvas(row: pd.Series, prev: pd.Series) -> bool:
    """Control signal + lower-eighth support test of active Darvas box."""
    if not signal_control(row, prev):
        return False
    if not bool(row["box_active"]):
        return False
    # Lower-eighth support test: low probes L8 zone; close holds above box low
    return float(row["Low"]) <= float(row["box_l8"]) and float(row["Close"]) >= float(row["box_low"])


def simulate_symbol(df: pd.DataFrame, sym: str, arm: str) -> list[dict[str, Any]]:
    prep = prepare(df)
    trades: list[dict[str, Any]] = []
    i = max(EMA_SPAN + EMA_SLOPE_N + BOX_LOOKBACK + ATR_N, 40)
    n = len(prep)
    while i < n - 2:
        row = prep.iloc[i]
        prev = prep.iloc[i - 1]
        ok = signal_darvas(row, prev) if arm == "darvas" else signal_control(row, prev)
        if not ok:
            i += 1
            continue
        entry_i = i + 1
        if entry_i >= n:
            break
        entry_row = prep.iloc[entry_i]
        entry = float(entry_row["Open"])
        atr_sig = float(row["atr"])
        if entry <= 0 or not math.isfinite(atr_sig) or atr_sig <= 0:
            i += 1
            continue
        stop = entry - STOP_ATR_MULT * atr_sig
        risk = entry - stop
        if risk <= 0:
            i += 1
            continue
        target = entry + TARGET_R * risk
        exit_i = None
        exit_px = None
        exit_type = "TIME"
        last = min(entry_i + TIME_STOP_BARS, n - 1)
        for j in range(entry_i + 1, last + 1):
            bar = prep.iloc[j]
            o, h, lo = float(bar["Open"]), float(bar["High"]), float(bar["Low"])
            # Gap through stop
            if o <= stop:
                exit_i, exit_px, exit_type = j, o, "GAP_DOWN"
                break
            # Stop then target same bar: stop first (conservative)
            if lo <= stop:
                exit_i, exit_px, exit_type = j, stop, "STOP"
                break
            if o >= target:
                exit_i, exit_px, exit_type = j, o, "GAP_UP"
                break
            if h >= target:
                exit_i, exit_px, exit_type = j, target, "TARGET"
                break
        if exit_i is None:
            exit_i = last
            exit_px = float(prep.iloc[exit_i]["Close"])
            exit_type = "TIME"
        opened = prep.iloc[entry_i]["Date"]
        closed = prep.iloc[exit_i]["Date"]
        pnl_pct = (float(exit_px) - entry) / entry * 100.0
        if COSTS_BPS:
            pnl_pct -= COSTS_BPS / 100.0
        r_mult = (float(exit_px) - entry) / risk
        days = max((closed - opened).days, 1)
        trades.append(
            {
                "sym": sym,
                "arm": arm,
                "opened": opened,
                "closed": closed,
                "entry": entry,
                "stop": stop,
                "target": target,
                "exit_px": float(exit_px),
                "exit": exit_type,
                "pnl": pnl_pct,
                "r": r_mult,
                "days": float(days),
                "pnl_d": pnl_pct / 100.0 * SHEET,
                "signal_date": row["Date"],
                "box_high": float(row["box_high"]) if math.isfinite(float(row["box_high"])) else "",
                "box_low": float(row["box_low"]) if math.isfinite(float(row["box_low"])) else "",
            }
        )
        i = exit_i + 1  # one position; resume after exit
    return trades


def book_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(trades)
    empty = {
        "n": 0,
        "wins": 0,
        "losses": 0,
        "wr": 0.0,
        "avg_pnl": 0.0,
        "avg_r": 0.0,
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
        "cap_days": 0.0,
        "exits": {},
        "syms": 0,
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
    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "wr": 100.0 * len(wins) / n,
        "avg_pnl": sum(pnls) / n,
        "avg_r": sum(t["r"] for t in trades) / n,
        "pf": (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0),
        "sheet": sum(p / 100.0 * SHEET for p in pnls),
        "pnl_d": sum(t["pnl_d"] for t in trades),
        "avg_days": sum(t["days"] for t in trades) / n,
        "avg_win": (sum(wins) / len(wins)) if wins else float("nan"),
        "avg_loss": (sum(losses) / len(losses)) if losses else float("nan"),
        "wo_max": wo,
        "exp_pct": sum(pnls) / n,
        "ann_ror": ov["ann_ror"],
        "max_dd": ov["max_dd"],
        "cap_days": ov.get("capital_days", 0.0),
        "exits": dict(Counter(str(t.get("exit") or "?") for t in trades)),
        "syms": len({t["sym"] for t in trades}),
    }


def split_is_oos(trades: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return (
        [t for t in trades if t["opened"] < IS_CUT],
        [t for t in trades if t["opened"] >= IS_CUT],
    )


def fmt_pct(x: float, nd: int = 2) -> str:
    if x is None or not math.isfinite(float(x)):
        return "—"
    return f"{float(x):.{nd}f}%"


def fmt_n(x: float, nd: int = 2) -> str:
    if x is None or not math.isfinite(float(x)):
        return "—"
    return f"{float(x):,.{nd}f}"


def exit_mix(d: dict) -> str:
    items = sorted(d.items(), key=lambda kv: -kv[1])
    return ", ".join(f"{k}:{v}" for k, v in items) if items else "—"


def verdict(ctrl_is: dict, cand_is: dict, ctrl_oos: dict, cand_oos: dict) -> tuple[str, str]:
    """Quality over N. OOS softens → HOLD. Never retune on OOS."""
    if cand_is["n"] < 10:
        return "HOLD", "Candidate N too thin for KEEP"

    def better(a: float, b: float, higher: bool = True) -> bool:
        if not (math.isfinite(a) and math.isfinite(b)):
            return False
        return a > b + 1e-9 if higher else a < b - 1e-9

    n_ratio = cand_is["n"] / max(ctrl_is["n"], 1)
    n_collapsed = n_ratio < 0.25

    is_quality_up = (
        better(cand_is["avg_pnl"], ctrl_is["avg_pnl"])
        and better(cand_is["pf"], ctrl_is["pf"])
        and (
            better(cand_is["ann_ror"], ctrl_is["ann_ror"])
            or not math.isfinite(ctrl_is["ann_ror"])
        )
    )
    is_quality_down = better(ctrl_is["avg_pnl"], cand_is["avg_pnl"]) and better(
        ctrl_is["pf"], cand_is["pf"]
    )
    oos_soft = False
    if ctrl_oos["n"] >= 5 and cand_oos["n"] >= 3:
        oos_soft = (
            cand_oos["avg_pnl"] < ctrl_oos["avg_pnl"] - 0.05
            or (
                math.isfinite(cand_oos["ann_ror"])
                and math.isfinite(ctrl_oos["ann_ror"])
                and cand_oos["ann_ror"] < ctrl_oos["ann_ror"] - 1.0
            )
        )
    if is_quality_down:
        return "DISMISS", "IS quality worse (Avg PnL% / PF)"
    if oos_soft:
        extra = f"; IS N {cand_is['n']}/{ctrl_is['n']}" if n_collapsed else ""
        return "HOLD", f"IS quality may lift but OOS softened — do not retune OOS{extra}"
    if is_quality_up and n_collapsed:
        return "HOLD", f"IS quality up but N collapsed ({cand_is['n']}/{ctrl_is['n']}) — not KEEP"
    if is_quality_up and not n_collapsed:
        return "LEAN KEEP", "IS quality up without N collapse; OOS not softer — research only"
    return "HOLD", "Flat / mixed quality vs control"


def write_trades_csv(path: Path, trades: list[dict[str, Any]]) -> None:
    fields = [
        "SYMBOL",
        "ARM",
        "DATE_OPENED",
        "DATE_CLOSED",
        "ENTRY_PRICE",
        "STOP_PRICE",
        "TARGET_PRICE",
        "EXIT_PRICE",
        "EXIT_TYPE",
        "PNL_PCT",
        "R_MULT",
        "DAYS_HELD",
        "PNL_DOLLARS",
        "SIGNAL_DATE",
        "BOX_HIGH",
        "BOX_LOW",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for t in trades:
            w.writerow(
                {
                    "SYMBOL": t["sym"],
                    "ARM": t["arm"],
                    "DATE_OPENED": t["opened"].isoformat(),
                    "DATE_CLOSED": t["closed"].isoformat(),
                    "ENTRY_PRICE": f"{t['entry']:.4f}",
                    "STOP_PRICE": f"{t['stop']:.4f}",
                    "TARGET_PRICE": f"{t['target']:.4f}",
                    "EXIT_PRICE": f"{t['exit_px']:.4f}",
                    "EXIT_TYPE": t["exit"],
                    "PNL_PCT": f"{t['pnl']:.4f}",
                    "R_MULT": f"{t['r']:.4f}",
                    "DAYS_HELD": f"{t['days']:.0f}",
                    "PNL_DOLLARS": f"{t['pnl_d']:.2f}",
                    "SIGNAL_DATE": t["signal_date"].isoformat()
                    if hasattr(t["signal_date"], "isoformat")
                    else t["signal_date"],
                    "BOX_HIGH": t.get("box_high", ""),
                    "BOX_LOW": t.get("box_low", ""),
                }
            )


def pack_arm(name: str, role: str, trades: list[dict[str, Any]]) -> dict[str, Any]:
    is_t, oos_t = split_is_oos(trades)
    return {
        "name": name,
        "role": role,
        "trades": trades,
        "full": book_stats(trades),
        "is": book_stats(is_t),
        "oos": book_stats(oos_t),
    }


def metric_rows_html(arms: list[dict[str, Any]], book: str) -> str:
    headers = [
        ("Arm", "text"),
        ("Role", "text"),
        ("N", "num"),
        ("Win%", "num"),
        ("Avg PnL%", "num"),
        ("AVG_PNL_PCT_WO_MAX", "num"),
        ("AvgR", "num"),
        ("PF", "num"),
        ("Sheet PnL $", "num"),
        ("Ann ROR%", "num"),
        ("Max DD%", "num"),
        ("Avg days", "num"),
        ("Capital days", "num"),
        ("Δ Avg PnL%", "num"),
        ("Δ Ann ROR%", "num"),
        ("Δ Max DD%", "num"),
        ("Exit mix", "text"),
        ("Verdict", "text"),
    ]
    th = "".join(sortable_th(a, b) for a, b in headers)
    ctrl = arms[0][book]
    verd, note = arms[1].get("verd", "—"), arms[1].get("note", "")
    body = []
    for a in arms:
        m = a[book]
        d_avg = m["avg_pnl"] - ctrl["avg_pnl"]
        d_ror = (
            m["ann_ror"] - ctrl["ann_ror"]
            if math.isfinite(m["ann_ror"]) and math.isfinite(ctrl["ann_ror"])
            else float("nan")
        )
        d_dd = (
            m["max_dd"] - ctrl["max_dd"]
            if math.isfinite(m["max_dd"]) and math.isfinite(ctrl["max_dd"])
            else float("nan")
        )
        vcell = "CONTROL" if a["role"] == "control" else f"{verd}"
        cells = [
            html_mod.escape(a["name"]),
            a["role"],
            str(m["n"]),
            fmt_pct(m["wr"]),
            fmt_pct(m["avg_pnl"]),
            fmt_pct(m["wo_max"]),
            fmt_n(m["avg_r"]),
            fmt_n(m["pf"]),
            format_money(m["sheet"]),
            fmt_n(m["ann_ror"], 1),
            fmt_pct(m["max_dd"]),
            fmt_n(m["avg_days"], 1),
            fmt_n(m["cap_days"], 0),
            f"{d_avg:+.2f}pp" if a["role"] != "control" else "—",
            f"{d_ror:+.1f}" if a["role"] != "control" and math.isfinite(d_ror) else "—",
            f"{d_dd:+.2f}pp" if a["role"] != "control" and math.isfinite(d_dd) else "—",
            html_mod.escape(exit_mix(m["exits"])),
            html_mod.escape(vcell if a["role"] == "control" else f"{verd} — {note}"),
        ]
        body.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    return f"<thead><tr>{th}</tr></thead><tbody>{''.join(body)}</tbody>"


def write_html(path: Path, arms: list[dict[str, Any]], univ: list[str], verd: str, note: str) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>Raghee swing EMA vs Darvas — {STAMP}</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 1.5rem; color: #1a1a1a; }}
h1 {{ font-size: 1.35rem; }} h2 {{ font-size: 1.1rem; margin-top: 1.5rem; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.85rem; margin: 0.5rem 0 1rem; }}
th, td {{ border: 1px solid #cbd5e1; padding: 0.35rem 0.5rem; text-align: left; }}
th {{ background: #f1f5f9; }}
.note {{ background: #fff7ed; border: 1px solid #fed7aa; padding: 0.75rem 1rem; border-radius: 6px; }}
code {{ background: #f1f5f9; padding: 0.1rem 0.3rem; border-radius: 3px; }}
{SORT_CSS}
</style></head><body>
<h1>Raghee swing — 34 EMA pullback vs + Darvas box (System A1)</h1>
<p><strong>Stamp:</strong> <code>raghee_swing_ema_darvas_{STAMP}</code> · Generated {now}</p>
<div class="note">
<strong>Research only.</strong> Not gold. Not DailyRun. No VScore / GRaB / Propulsion Dots.
One-knob ENTRY A/B; same exit both arms. IS = entry &lt; 2024-01-01; OOS report-only — do not retune.
Click column headers to sort.
</div>
<p><strong>Universe:</strong> {html_mod.escape(", ".join(univ))} (N={len(univ)})</p>
<p><strong>Verdict:</strong> {html_mod.escape(verd)} — {html_mod.escape(note)}</p>

<h2>1. Freeze</h2>
<ul>
<li><strong>Control:</strong> close &gt; rising 34 EMA (slope ≥ 0 over {EMA_SLOPE_N}d); prior close &gt; EMA; signal low touches/crosses EMA from above; entry next open.</li>
<li><strong>Candidate:</strong> same + active prior-{BOX_LOOKBACK} bar Darvas box (width ≤ {BOX_MAX_WIDTH_PCT:.0f}% of mid, mid &gt; EMA) and <em>lower-eighth support test</em> (low ≤ box_low+0.125·height; close ≥ box_low).</li>
<li><strong>Exit (both):</strong> stop = entry − {STOP_ATR_MULT}·ATR({ATR_N}); target = +{TARGET_R}R; time {TIME_STOP_BARS} bars; stop-first same bar; costs {COSTS_BPS} bps.</li>
<li><strong>Liquidity:</strong> Close ≥ ${MIN_PRICE:.0f}, ADV20 ≥ {MIN_ADV20:,.0f}.</li>
</ul>

<h2>2. Full book</h2>
<table class="sortable">{metric_rows_html(arms, "full")}</table>

<h2>3. In-sample (entry &lt; 2024-01-01)</h2>
<table class="sortable">{metric_rows_html(arms, "is")}</table>

<h2>4. Out-of-sample (entry ≥ 2024-01-01) — report only</h2>
<table class="sortable">{metric_rows_html(arms, "oos")}</table>

<h2>5. Honesty</h2>
<ul>
<li>Box definition / L8 rule chosen before seeing this table (documented freeze) — still label any later knob hunt as selection bias.</li>
<li>Ann ROR / Max DD via Closed overlay (<code>compare_format.overlay_ann_ror_max_dd</code>) with sheet ${SHEET:,.0f} / initial ${INIT_ACCT:,.0f}.</li>
<li>Research ≠ gold ≠ DailyRun.</li>
</ul>
{SORT_JS}
</body></html>
"""
    path.write_text(html, encoding="utf-8")


def write_baseline(
    path: Path,
    univ: list[str],
    arms: list[dict[str, Any]],
    verd: str,
    note: str,
) -> None:
    c, d = arms[0], arms[1]
    lines = [
        f"# BASELINE — Raghee swing 34 EMA vs Darvas — `raghee_swing_ema_darvas_{STAMP}`",
        "",
        "**Status:** research candidate only. **Not gold. Not DailyRun.** No VScore / GRaB.",
        "",
        "## Freeze",
        "",
        "| Item | Value |",
        "|------|-------|",
        f"| Side | Long-only |",
        f"| Universe | PaulTwenty / listed ({len(univ)}): {', '.join(univ)} |",
        f"| Control | Pullback to 34 EMA (touch/cross from above; close > EMA; EMA slope ≥ 0 over {EMA_SLOPE_N}d); entry next open |",
        f"| Candidate knob | + active prior-{BOX_LOOKBACK} bar Darvas box (width ≤ {BOX_MAX_WIDTH_PCT:.0f}% mid, mid > EMA) + lower-eighth support test |",
        f"| Exit (both) | Stop entry−{STOP_ATR_MULT}·ATR({ATR_N}); target +{TARGET_R}R; time {TIME_STOP_BARS} bars |",
        f"| Liquidity | Close ≥ ${MIN_PRICE:.0f}; ADV20 ≥ {MIN_ADV20:,.0f} |",
        f"| Costs | {COSTS_BPS} bps |",
        f"| IS / OOS | IS entry < {IS_CUT.isoformat()}; OOS ≥ cut (report-only) |",
        f"| Sheet / Initial | ${SHEET:,.0f} / ${INIT_ACCT:,.0f} |",
        "",
        "## Verdict",
        "",
        f"**{verd}** — {note}",
        "",
        "## Headline IS / OOS",
        "",
        "| Arm | Split | N | WR% | Avg PnL% | AvgR | PF | Ann ROR% | Max DD% | Sheet PnL |",
        "|-----|-------|---|-----|----------|------|----|----------|---------|-----------|",
    ]
    for a in arms:
        for split in ("is", "oos", "full"):
            m = a[split]
            lines.append(
                f"| {a['name']} | {split.upper()} | {m['n']} | {m['wr']:.1f} | {m['avg_pnl']:.2f} | "
                f"{m['avg_r']:.2f} | {m['pf']:.2f} | "
                f"{m['ann_ror']:.1f}" if math.isfinite(m["ann_ror"]) else f"| {a['name']} | {split.upper()} | {m['n']} | {m['wr']:.1f} | {m['avg_pnl']:.2f} | "
                f"{m['avg_r']:.2f} | {m['pf']:.2f} | —"
            )
    # Fix the broken f-string logic above — rewrite cleanly
    path.write_text("PLACEHOLDER", encoding="utf-8")  # will overwrite below
    _write_baseline_clean(path, univ, arms, verd, note)


def _write_baseline_clean(
    path: Path,
    univ: list[str],
    arms: list[dict[str, Any]],
    verd: str,
    note: str,
) -> None:
    rows = [
        f"# BASELINE — Raghee swing 34 EMA vs Darvas — `raghee_swing_ema_darvas_{STAMP}`",
        "",
        "**Status:** research candidate only. **Not gold. Not DailyRun.** No VScore / GRaB / Propulsion Dots.",
        "",
        "Parent plan: `drive/paul_experiments/raghee_horner_research_20260821/AB_PLAN.md` (System A1).",
        "",
        "## Freeze",
        "",
        "| Item | Value |",
        "|------|-------|",
        "| Side | Long-only |",
        f"| Universe | {len(univ)} names: {', '.join(univ)} |",
        f"| Control | Pullback to 34 EMA — prior close > EMA; signal low ≤ EMA; close still > EMA; EMA slope ≥ 0 over {EMA_SLOPE_N}d; entry next open |",
        f"| Candidate (one knob) | Same + active prior-{BOX_LOOKBACK} bar Darvas box (high/low of bars [t−{BOX_LOOKBACK}, t−1]; width ≤ {BOX_MAX_WIDTH_PCT:.0f}% of mid; mid > EMA) **and** lower-eighth support test (low ≤ box_low + 0.125·height; close ≥ box_low) |",
        f"| Exit (identical both arms) | Stop = entry − {STOP_ATR_MULT}·ATR({ATR_N} at signal); target = +{TARGET_R}R; time stop {TIME_STOP_BARS} bars; gap fills at open; stop-first same bar |",
        f"| Liquidity | Close ≥ ${MIN_PRICE:.0f}; ADV20 ≥ {MIN_ADV20:,.0f} |",
        f"| Costs | {COSTS_BPS} bps (research) |",
        f"| IS / OOS | IS = entry_date < {IS_CUT.isoformat()}; OOS ≥ cut — **report-only, never retune** |",
        f"| Overlay cash | Sheet ${SHEET:,.0f}; Initial_Account ${INIT_ACCT:,.0f} |",
        "",
        "## Verdict",
        "",
        f"**{verd}** — {note}",
        "",
        "Research ≠ gold ≠ DailyRun. Do not wire DailyRun from this stamp.",
        "",
        "## Headline IS / OOS",
        "",
        "| Arm | Split | N | WR% | Avg PnL% | AvgR | PF | Ann ROR% | Max DD% | Sheet PnL |",
        "|-----|-------|---|-----|----------|------|----|----------|---------|-----------|",
    ]
    for a in arms:
        for split, label in (("is", "IS"), ("oos", "OOS"), ("full", "FULL")):
            m = a[split]
            ror = f"{m['ann_ror']:.1f}" if math.isfinite(m["ann_ror"]) else "—"
            dd = f"{m['max_dd']:.2f}" if math.isfinite(m["max_dd"]) else "—"
            rows.append(
                f"| {a['name']} | {label} | {m['n']} | {m['wr']:.1f} | {m['avg_pnl']:.2f} | "
                f"{m['avg_r']:.2f} | {m['pf']:.2f} | {ror} | {dd} | {format_money(m['sheet'])} |"
            )
    rows += [
        "",
        "## Selection bias",
        "",
        "Freeze chosen before the compare table for this run. Any later change to box width / L8 / ATR mult after seeing results = in-sample selection — new stamp required.",
        "",
        "## Artifacts",
        "",
        "- `compare.html` — sortable control vs candidate (FULL / IS / OOS)",
        "- `metrics.csv` — numeric mirror",
        "- `closed_control.csv` / `closed_darvas.csv` — trade logs",
        "",
    ]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def write_metrics_csv(path: Path, arms: list[dict[str, Any]], verd: str, note: str) -> None:
    fields = [
        "arm",
        "role",
        "split",
        "n",
        "wr",
        "avg_pnl",
        "wo_max",
        "avg_r",
        "pf",
        "sheet",
        "ann_ror",
        "max_dd",
        "avg_days",
        "cap_days",
        "verdict",
        "note",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for a in arms:
            for split in ("full", "is", "oos"):
                m = a[split]
                w.writerow(
                    {
                        "arm": a["name"],
                        "role": a["role"],
                        "split": split,
                        "n": m["n"],
                        "wr": round(m["wr"], 4),
                        "avg_pnl": round(m["avg_pnl"], 4),
                        "wo_max": round(m["wo_max"], 4),
                        "avg_r": round(m["avg_r"], 4),
                        "pf": round(m["pf"], 4),
                        "sheet": round(m["sheet"], 2),
                        "ann_ror": m["ann_ror"] if math.isfinite(m["ann_ror"]) else "",
                        "max_dd": m["max_dd"] if math.isfinite(m["max_dd"]) else "",
                        "avg_days": round(m["avg_days"], 2),
                        "cap_days": round(m["cap_days"], 1),
                        "verdict": verd if a["role"] != "control" else "CONTROL",
                        "note": note if a["role"] != "control" else "",
                    }
                )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--universe",
        default="",
        help="Comma symbols or path to CSV (default: PaulTwenty)",
    )
    args = ap.parse_args()
    if args.universe and Path(args.universe).exists():
        univ = load_universe(Path(args.universe))
    elif args.universe:
        univ = [s.strip().upper() for s in args.universe.split(",") if s.strip()]
    else:
        univ = load_universe(PAULTWENTY)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ctrl_trades: list[dict[str, Any]] = []
    darv_trades: list[dict[str, Any]] = []
    missing: list[str] = []
    for sym in univ:
        df = load_ohlc(sym)
        if df is None or len(df) < 200:
            missing.append(sym)
            continue
        ctrl_trades.extend(simulate_symbol(df, sym, "control"))
        darv_trades.extend(simulate_symbol(df, sym, "darvas"))

    arms = [
        pack_arm("EMA pullback only", "control", ctrl_trades),
        pack_arm("EMA + Darvas L8", "candidate", darv_trades),
    ]
    verd, note = verdict(arms[0]["is"], arms[1]["is"], arms[0]["oos"], arms[1]["oos"])
    arms[1]["verd"] = verd
    arms[1]["note"] = note

    write_trades_csv(OUT_DIR / "closed_control.csv", ctrl_trades)
    write_trades_csv(OUT_DIR / "closed_darvas.csv", darv_trades)
    write_metrics_csv(OUT_DIR / "metrics.csv", arms, verd, note)
    write_html(OUT_DIR / "compare.html", arms, univ, verd, note)
    write_baseline(OUT_DIR / "BASELINE.md", univ, arms, verd, note)

    # AB_PLAN pointer
    (OUT_DIR / "AB_PLAN.md").write_text(
        "\n".join(
            [
                f"# AB_PLAN — pointer — `raghee_swing_ema_darvas_{STAMP}`",
                "",
                "Implements **System A1** from `../raghee_horner_research_20260821/AB_PLAN.md`.",
                "",
                "Knob: require Darvas lower-eighth support context on top of 34 EMA pullback.",
                "Same exit both arms. See `BASELINE.md` for freeze + verdict.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(f"stamp={OUT_DIR}")
    print(f"universe={len(univ)} missing={missing}")
    for a in arms:
        for split in ("is", "oos", "full"):
            m = a[split]
            print(
                f"{a['name']:20s} {split:4s} N={m['n']:4d} WR={m['wr']:5.1f} "
                f"AvgPnL={m['avg_pnl']:6.2f} PF={m['pf']:5.2f} "
                f"AnnROR={m['ann_ror'] if math.isfinite(m['ann_ror']) else float('nan'):7.1f} "
                f"MaxDD={m['max_dd'] if math.isfinite(m['max_dd']) else float('nan'):6.2f}"
            )
    print(f"VERDICT={verd} — {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
