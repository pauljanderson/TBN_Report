#!/usr/bin/env python3
"""Weekly ATR(14) wide-range down-day reversal — exit A/B (research only).

Signal: daily (High−Low) ≥ 25% of last-completed 14-week ATR, and down day
(Close < Open). Entry next open. Long-only. Stops/targets in frozen weekly ATR.

Usage:
  python tools/weekly_atr_reversal_ab.py
  python tools/weekly_atr_reversal_ab.py --universe SPY,QQQ,AAPL
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
OUT_DIR = DRIVE / "paul_experiments" / f"weekly_atr_reversal_{STAMP}"
PAULTWENTY = DRIVE / "universes" / "PaulTwenty_universe.csv"
IS_CUT = date(2024, 1, 1)

# --- Freeze ---
WEEKLY_ATR_N = 14
RANGE_FRAC = 0.25  # daily H−L ≥ this × weekly ATR
# Down-day: Close < Open (bearish session candle). Documented in BASELINE.
DOWN_DAY = "close_lt_open"
TARGET_MULTS = (1.0, 1.5, 2.0)
STOP_MULTS = (0.5, 1.0, 1.5)
# Sequential control (mid grid)
CTRL_TARGET = 1.5
CTRL_STOP = 1.0
# Candidate exit (same entry): target = signal-day High; stop = 0.5% below entry
BOX_STOP_PCT = 0.5  # stop = entry * (1 - BOX_STOP_PCT/100)
BOX_ARM = "sig_high_stop05pct"
TIME_STOP_BARS = 40
MIN_PRICE = 5.0
MIN_ADV20 = 500_000.0
SHEET = 45_000.0
INIT_ACCT = DEFAULT_INITIAL_ACCOUNT
COSTS_BPS = 0.0
WEEK_FREQ = "W-FRI"  # calendar week ending Friday


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


def _wilder_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int) -> np.ndarray:
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


def weekly_atr_series(df: pd.DataFrame) -> pd.DataFrame:
    """Weekly OHLC (W-FRI) + Wilder ATR(14). Index = week-end date."""
    tmp = df.copy()
    tmp["dt"] = pd.to_datetime(tmp["Date"])
    w = (
        tmp.set_index("dt")
        .resample(WEEK_FREQ)
        .agg(
            {
                "Open": "first",
                "High": "max",
                "Low": "min",
                "Close": "last",
                "Volume": "sum",
            }
        )
        .dropna(subset=["Open", "High", "Low", "Close"])
    )
    atr = _wilder_atr(
        w["High"].to_numpy(dtype=float),
        w["Low"].to_numpy(dtype=float),
        w["Close"].to_numpy(dtype=float),
        WEEKLY_ATR_N,
    )
    w = w.copy()
    w["watr"] = atr
    w["week_end"] = w.index.date
    return w.reset_index(drop=True)


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Attach last-completed weekly ATR to each daily bar (no look-ahead).

    merge_asof backward on Date vs week_end: for mid-week dates the current
    Friday week-end is still in the future, so ATR is prior completed week.
    On Friday EOD, week_end == Date and that week is complete — allowed.
    """
    out = df.copy()
    vol = out["Volume"].astype(float)
    out["adv20"] = vol.rolling(20, min_periods=20).mean()
    out["range"] = out["High"].astype(float) - out["Low"].astype(float)
    out["down"] = out["Close"].astype(float) < out["Open"].astype(float)

    w = weekly_atr_series(df)
    daily = pd.DataFrame({"Date": out["Date"]}).sort_values("Date")
    weekly = w[["week_end", "watr"]].rename(columns={"week_end": "Date"}).sort_values("Date")
    merged = pd.merge_asof(
        daily.assign(Date=pd.to_datetime(daily["Date"])),
        weekly.assign(Date=pd.to_datetime(weekly["Date"])),
        on="Date",
        direction="backward",
    )
    out["watr"] = merged["watr"].to_numpy()
    return out


def arm_name(tgt: float, stop: float) -> str:
    return f"tgt{tgt:g}_stop{stop:g}"


def signal_at(row: pd.Series) -> bool:
    c = float(row["Close"])
    if c < MIN_PRICE:
        return False
    adv = float(row["adv20"]) if math.isfinite(float(row["adv20"])) else 0.0
    if adv < MIN_ADV20:
        return False
    watr = float(row["watr"]) if math.isfinite(float(row["watr"])) else float("nan")
    if not math.isfinite(watr) or watr <= 0:
        return False
    rng = float(row["range"])
    if not math.isfinite(rng) or rng < RANGE_FRAC * watr:
        return False
    if not bool(row["down"]):
        return False
    return True


def simulate_symbol(
    df: pd.DataFrame,
    sym: str,
    tgt_mult: float,
    stop_mult: float,
) -> list[dict[str, Any]]:
    prep = prepare(df)
    trades: list[dict[str, Any]] = []
    # Need ~14 weeks + ADV warm-up
    i = max(20, WEEKLY_ATR_N * 5 + 5)
    n = len(prep)
    arm = arm_name(tgt_mult, stop_mult)
    while i < n - 2:
        row = prep.iloc[i]
        if not signal_at(row):
            i += 1
            continue
        entry_i = i + 1
        if entry_i >= n:
            break
        entry = float(prep.iloc[entry_i]["Open"])
        watr = float(row["watr"])
        if entry <= 0 or not math.isfinite(watr) or watr <= 0:
            i += 1
            continue
        stop = entry - stop_mult * watr
        target = entry + tgt_mult * watr
        risk = entry - stop
        if risk <= 0 or target <= entry:
            i += 1
            continue

        exit_i = None
        exit_px = None
        exit_type = "TIME"
        last = min(entry_i + TIME_STOP_BARS, n - 1)
        for j in range(entry_i + 1, last + 1):
            bar = prep.iloc[j]
            o, h, lo = float(bar["Open"]), float(bar["High"]), float(bar["Low"])
            # Stop first (conservative same-bar)
            if o <= stop:
                exit_i, exit_px, exit_type = j, o, "GAP_DOWN"
                break
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
                "tgt_mult": tgt_mult,
                "stop_mult": stop_mult,
                "opened": opened,
                "closed": closed,
                "entry": entry,
                "stop": stop,
                "target": target,
                "watr": watr,
                "signal_high": float(row["High"]),
                "exit_px": float(exit_px),
                "exit": exit_type,
                "pnl": pnl_pct,
                "r": r_mult,
                "days": float(days),
                "pnl_d": pnl_pct / 100.0 * SHEET,
                "signal_date": row["Date"],
                "signal_range": float(row["range"]),
            }
        )
        i = exit_i + 1
    return trades


def simulate_symbol_sig_high(df: pd.DataFrame, sym: str) -> tuple[list[dict[str, Any]], int]:
    """Same entry freeze; exit = signal-day High target / 0.5% stop below entry.

    If next open already >= signal High, **skip** (target not above entry).
    Returns (trades, n_skipped_entry_ge_signal_high).
    """
    prep = prepare(df)
    trades: list[dict[str, Any]] = []
    skipped = 0
    i = max(20, WEEKLY_ATR_N * 5 + 5)
    n = len(prep)
    while i < n - 2:
        row = prep.iloc[i]
        if not signal_at(row):
            i += 1
            continue
        entry_i = i + 1
        if entry_i >= n:
            break
        entry = float(prep.iloc[entry_i]["Open"])
        watr = float(row["watr"])
        sig_hi = float(row["High"])
        if entry <= 0 or not math.isfinite(watr) or watr <= 0 or not math.isfinite(sig_hi):
            i += 1
            continue
        if entry >= sig_hi:
            # Target already at/below entry — skip (documented; not immediate TP)
            skipped += 1
            i += 1
            continue
        stop = entry * (1.0 - BOX_STOP_PCT / 100.0)
        target = sig_hi
        risk = entry - stop
        if risk <= 0:
            i += 1
            continue

        exit_i = None
        exit_px = None
        exit_type = "TIME"
        last = min(entry_i + TIME_STOP_BARS, n - 1)
        for j in range(entry_i + 1, last + 1):
            bar = prep.iloc[j]
            o, h, lo = float(bar["Open"]), float(bar["High"]), float(bar["Low"])
            if o <= stop:
                exit_i, exit_px, exit_type = j, o, "GAP_DOWN"
                break
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
                "arm": BOX_ARM,
                "tgt_mult": float("nan"),
                "stop_mult": float("nan"),
                "opened": opened,
                "closed": closed,
                "entry": entry,
                "stop": stop,
                "target": target,
                "watr": watr,
                "signal_high": sig_hi,
                "exit_px": float(exit_px),
                "exit": exit_type,
                "pnl": pnl_pct,
                "r": r_mult,
                "days": float(days),
                "pnl_d": pnl_pct / 100.0 * SHEET,
                "signal_date": row["Date"],
                "signal_range": float(row["range"]),
            }
        )
        i = exit_i + 1
    return trades, skipped


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


def pack_arm(name: str, role: str, trades: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    is_t, oos_t = split_is_oos(trades)
    d = {
        "name": name,
        "role": role,
        "trades": trades,
        "full": book_stats(trades),
        "is": book_stats(is_t),
        "oos": book_stats(oos_t),
        "verd": extra.get("verd", "—"),
        "note": extra.get("note", ""),
    }
    d.update({k: v for k, v in extra.items() if k not in ("verd", "note")})
    return d


def verdict_vs_control(
    ctrl_is: dict,
    cand_is: dict,
    ctrl_oos: dict,
    cand_oos: dict,
    cand_label: str = "candidate",
) -> tuple[str, str]:
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
        return "DISMISS", f"IS quality worse (Avg PnL% / PF) for {cand_label} vs control"
    if oos_soft:
        extra = f"; IS N {cand_is['n']}/{ctrl_is['n']}" if n_collapsed else ""
        return "HOLD", f"IS quality may lift but OOS softened — do not retune OOS{extra}"
    if is_quality_up and n_collapsed:
        return "HOLD", f"IS quality up but N collapsed ({cand_is['n']}/{ctrl_is['n']}) — not KEEP"
    if is_quality_up and not n_collapsed:
        return "LEAN KEEP", "IS quality up without N collapse; OOS not softer — research only"
    return "HOLD", f"Flat / mixed quality vs control ({cand_label})"


def system_verdict(ctrl: dict[str, Any]) -> tuple[str, str]:
    """Judge the frozen control exit as a system research candidate."""
    is_m, oos_m = ctrl["is"], ctrl["oos"]
    if is_m["n"] < 20:
        return "HOLD", f"Control IS N={is_m['n']} too thin for KEEP/DISMISS"
    edge = is_m["avg_pnl"] > 0.05 and is_m["pf"] >= 1.05 and (
        not math.isfinite(is_m["ann_ror"]) or is_m["ann_ror"] > 0
    )
    weak = is_m["avg_pnl"] < -0.05 and is_m["pf"] < 1.0
    oos_soft = False
    if oos_m["n"] >= 8 and edge:
        oos_soft = oos_m["avg_pnl"] < -0.1 or (
            math.isfinite(oos_m["ann_ror"]) and oos_m["ann_ror"] < -5.0
        )
    if weak:
        return (
            "DISMISS",
            f"Control IS negative quality (Avg={is_m['avg_pnl']:.2f}%, PF={is_m['pf']:.2f})",
        )
    if edge and oos_soft:
        return "HOLD", "Control IS positive but OOS softened — do not retune OOS; research HOLD"
    if edge:
        return (
            "LEAN KEEP",
            "Control IS positive quality; OOS not soft — research candidate only (not gold, not DailyRun)",
        )
    return "HOLD", "Control IS flat / mixed — no KEEP"


def write_trades_csv(path: Path, trades: list[dict[str, Any]]) -> None:
    fields = [
        "SYMBOL",
        "ARM",
        "TGT_MULT",
        "STOP_MULT",
        "DATE_OPENED",
        "DATE_CLOSED",
        "ENTRY_PRICE",
        "STOP_PRICE",
        "TARGET_PRICE",
        "SIGNAL_HIGH",
        "WATR",
        "EXIT_PRICE",
        "EXIT_TYPE",
        "PNL_PCT",
        "R_MULT",
        "DAYS_HELD",
        "PNL_DOLLARS",
        "SIGNAL_DATE",
        "SIGNAL_RANGE",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for t in trades:
            sh = t.get("signal_high", float("nan"))
            tm = t.get("tgt_mult", float("nan"))
            sm = t.get("stop_mult", float("nan"))
            w.writerow(
                {
                    "SYMBOL": t["sym"],
                    "ARM": t["arm"],
                    "TGT_MULT": f"{tm:.4f}" if math.isfinite(float(tm)) else "",
                    "STOP_MULT": f"{sm:.4f}" if math.isfinite(float(sm)) else "",
                    "DATE_OPENED": t["opened"].isoformat(),
                    "DATE_CLOSED": t["closed"].isoformat(),
                    "ENTRY_PRICE": f"{t['entry']:.4f}",
                    "STOP_PRICE": f"{t['stop']:.4f}",
                    "TARGET_PRICE": f"{t['target']:.4f}",
                    "SIGNAL_HIGH": f"{float(sh):.4f}" if math.isfinite(float(sh)) else "",
                    "WATR": f"{t['watr']:.4f}",
                    "EXIT_PRICE": f"{t['exit_px']:.4f}",
                    "EXIT_TYPE": t["exit"],
                    "PNL_PCT": f"{t['pnl']:.4f}",
                    "R_MULT": f"{t['r']:.4f}",
                    "DAYS_HELD": f"{t['days']:.0f}",
                    "PNL_DOLLARS": f"{t['pnl_d']:.2f}",
                    "SIGNAL_DATE": t["signal_date"].isoformat()
                    if hasattr(t["signal_date"], "isoformat")
                    else t["signal_date"],
                    "SIGNAL_RANGE": f"{t['signal_range']:.4f}",
                }
            )


def metric_rows_html(arms: list[dict[str, Any]], book: str, show_verdict: bool = True) -> str:
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
    ]
    if show_verdict:
        headers.append(("Verdict", "text"))
    th = "".join(sortable_th(a, b) for a, b in headers)
    ctrl = next((a[book] for a in arms if a["role"] == "control"), arms[0][book])
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
        ]
        if show_verdict:
            if a["role"] == "control":
                cells.append("CONTROL")
            else:
                cells.append(
                    html_mod.escape(f"{a.get('verd', '—')} — {a.get('note', '')}")
                )
        body.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    return f"<thead><tr>{th}</tr></thead><tbody>{''.join(body)}</tbody>"


def write_html(
    path: Path,
    univ: list[str],
    matrix: list[dict[str, Any]],
    tgt_arms: list[dict[str, Any]],
    stop_arms: list[dict[str, Any]],
    sys_verd: str,
    sys_note: str,
    freeze_tgt: float,
    freeze_stop: float,
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>Weekly ATR reversal — exit A/B — {STAMP}</title>
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
<h1>Weekly ATR(14) wide-range down-day reversal — exit A/B</h1>
<p><strong>Stamp:</strong> <code>weekly_atr_reversal_{STAMP}</code> · Generated {now}</p>
<div class="note">
<strong>Research only.</strong> Not gold. Not DailyRun.
ATR for signal / stop / target = <strong>14-week Wilder ATR</strong> (weekly bars, {WEEK_FREQ}),
<strong>frozen at signal</strong> (price units). No look-ahead: last completed week via merge_asof.
Down-day = <code>Close &lt; Open</code>. Entry next open. Time stop {TIME_STOP_BARS} bars.
IS = entry &lt; 2024-01-01; OOS report-only. Full 3×3 matrix = selection-bias labeled;
primary judgment = sequential one-knob + system control.
Click column headers to sort.
</div>
<p><strong>Universe:</strong> {html_mod.escape(", ".join(univ))} (N={len(univ)})</p>
<p><strong>System verdict (control {html_mod.escape(arm_name(freeze_tgt, freeze_stop))}):</strong>
{html_mod.escape(sys_verd)} — {html_mod.escape(sys_note)}</p>

<h2>1. Freeze</h2>
<ul>
<li><strong>Weekly ATR:</strong> Wilder ATR({WEEKLY_ATR_N}) on {WEEK_FREQ} OHLC; mapped to daily with last completed week (no look-ahead).</li>
<li><strong>Signal:</strong> daily High−Low ≥ {RANGE_FRAC*100:.0f}% of weekly ATR; down day Close &lt; Open; Close ≥ ${MIN_PRICE:.0f}; ADV20 ≥ {MIN_ADV20:,.0f}.</li>
<li><strong>Entry:</strong> next session open. Long-only. One position / symbol (flat before next).</li>
<li><strong>Stop / target:</strong> stop = entry − k×ATR; target = entry + m×ATR; ATR frozen at signal.</li>
<li><strong>Control exit:</strong> target {CTRL_TARGET}× / stop {CTRL_STOP}×. Time stop {TIME_STOP_BARS} bars. Costs {COSTS_BPS} bps.</li>
<li><strong>Overlay:</strong> sheet ${SHEET:,.0f} / initial ${INIT_ACCT:,.0f} (Ann ROR + Max DD).</li>
</ul>

<h2>A. Sequential knob 1 — Target (stop frozen {CTRL_STOP}×)</h2>
<table class="sortable"><caption>IS — click headers to sort</caption>{metric_rows_html(tgt_arms, "is")}</table>
<table class="sortable"><caption>OOS report-only — click headers to sort</caption>{metric_rows_html(tgt_arms, "oos")}</table>
<table class="sortable"><caption>Full book — click headers to sort</caption>{metric_rows_html(tgt_arms, "full")}</table>

<h2>B. Sequential knob 2 — Stop (target frozen {freeze_tgt:g}× after knob 1)</h2>
<table class="sortable"><caption>IS — click headers to sort</caption>{metric_rows_html(stop_arms, "is")}</table>
<table class="sortable"><caption>OOS report-only — click headers to sort</caption>{metric_rows_html(stop_arms, "oos")}</table>
<table class="sortable"><caption>Full book — click headers to sort</caption>{metric_rows_html(stop_arms, "full")}</table>

<h2>C. Full exit matrix (selection bias — informational)</h2>
<p class="note">Picking a cell from this 3×3 after seeing IS results is in-sample selection.
Sequential knobs above are the primary path; matrix is for transparency only.</p>
<table class="sortable"><caption>IS matrix — click headers to sort</caption>{metric_rows_html(matrix, "is", show_verdict=False)}</table>
<table class="sortable"><caption>OOS matrix — report only</caption>{metric_rows_html(matrix, "oos", show_verdict=False)}</table>

<h2>Honesty</h2>
<ul>
<li>OOS is report-only — never retune on OOS.</li>
<li>Ann ROR / Max DD via <code>compare_format.overlay_ann_ror_max_dd</code>.</li>
<li>Research != gold != DailyRun. Do not judge on max single-trade PnL.</li>
</ul>
{SORT_JS}
</body></html>
"""
    path.write_text(html, encoding="utf-8")


def _headline_rows(arms: list[dict[str, Any]]) -> list[str]:
    rows: list[str] = []
    for a in arms:
        for split, label in (("is", "IS"), ("oos", "OOS"), ("full", "FULL")):
            m = a[split]
            ror = f"{m['ann_ror']:.1f}" if math.isfinite(m["ann_ror"]) else "—"
            dd = f"{m['max_dd']:.2f}" if math.isfinite(m["max_dd"]) else "—"
            rows.append(
                f"| {a['name']} | {label} | {m['n']} | {m['wr']:.1f} | {m['avg_pnl']:.2f} | "
                f"{m['avg_r']:.2f} | {m['pf']:.2f} | {ror} | {dd} | {format_money(m['sheet'])} |"
            )
    return rows


def write_baseline(
    path: Path,
    univ: list[str],
    matrix: list[dict[str, Any]],
    tgt_arms: list[dict[str, Any]],
    stop_arms: list[dict[str, Any]],
    sys_verd: str,
    sys_note: str,
    freeze_tgt: float,
    freeze_stop: float,
    tgt_notes: list[str],
    stop_notes: list[str],
) -> None:
    rows = [
        f"# BASELINE — Weekly ATR reversal — `weekly_atr_reversal_{STAMP}`",
        "",
        "**Status:** research candidate only. **Not gold. Not DailyRun.**",
        "",
        "Parent plan: `AB_PLAN.md` in this stamp folder.",
        "",
        "## Freeze",
        "",
        "| Item | Value |",
        "|------|-------|",
        "| Side | Long-only |",
        f"| Universe | PaulTwenty ({len(univ)}): {', '.join(univ)} |",
        f"| Weekly ATR | Wilder ATR({WEEKLY_ATR_N}) on **weekly** bars ({WEEK_FREQ} OHLC). Same ATR used for **signal threshold, stop, and target** — frozen at signal in **price units**. |",
        "| ATR look-ahead | **None.** Daily bars get ATR via merge_asof backward onto week-end date = last **completed** week. Mid-week → prior Friday week. Friday EOD may use that Friday’s completed week. |",
        f"| Range gate | daily (High−Low) ≥ {RANGE_FRAC*100:.0f}% × weekly ATR |",
        f"| Down-day | **`{DOWN_DAY}`** = Close &lt; Open (bearish candle). Alternative Close &lt; prior Close **not** used. |",
        "| Entry | Next open (t+1) |",
        f"| Control exit | target {CTRL_TARGET}× ATR / stop {CTRL_STOP}× ATR below entry |",
        f"| Exit grid | targets {list(TARGET_MULTS)}; stops {list(STOP_MULTS)} (ATR frozen at signal) |",
        f"| Time stop | {TIME_STOP_BARS} bars (backstop) |",
        f"| Liquidity | Close ≥ ${MIN_PRICE:.0f}; ADV20 ≥ {MIN_ADV20:,.0f} |",
        f"| Costs | {COSTS_BPS} bps |",
        f"| IS / OOS | IS = entry_date &lt; {IS_CUT.isoformat()}; OOS ≥ cut — **report-only, never retune** |",
        f"| Overlay cash | Sheet ${SHEET:,.0f}; Initial_Account ${INIT_ACCT:,.0f} |",
        "",
        "## Ambiguities resolved",
        "",
        "1. **ATR for stop/target** = same 14-week ATR frozen at signal (not daily ATR, not rolling while in trade).",
        "2. **Down-day** = Close < Open (documented); not Close < prior Close.",
        "3. **No weekly ATR look-ahead** = last completed week only (merge_asof).",
        "4. **Same-bar** = stop-first before target (conservative).",
        "",
        "## System verdict",
        "",
        f"**{sys_verd}** — {sys_note}",
        "",
        f"Recommended freeze after sequential knobs: **target {freeze_tgt:g}× / stop {freeze_stop:g}×** "
        "(still research-only).",
        "",
        "## Sequential knob notes",
        "",
        "### Target (stop frozen at 1.0×)",
        "",
    ]
    rows += [f"- {n}" for n in tgt_notes] or ["- (none)"]
    rows += ["", "### Stop (target frozen after knob 1)", ""]
    rows += [f"- {n}" for n in stop_notes] or ["- (none)"]
    rows += [
        "",
        "## Headline — Target knob",
        "",
        "| Arm | Split | N | WR% | Avg PnL% | AvgR | PF | Ann ROR% | Max DD% | Sheet PnL |",
        "|-----|-------|---|-----|----------|------|----|----------|---------|-----------|",
    ]
    rows += _headline_rows(tgt_arms)
    rows += [
        "",
        "## Headline — Stop knob",
        "",
        "| Arm | Split | N | WR% | Avg PnL% | AvgR | PF | Ann ROR% | Max DD% | Sheet PnL |",
        "|-----|-------|---|-----|----------|------|----|----------|---------|-----------|",
    ]
    rows += _headline_rows(stop_arms)
    rows += [
        "",
        "## Full matrix (selection bias — informational)",
        "",
        "| Arm | Split | N | WR% | Avg PnL% | AvgR | PF | Ann ROR% | Max DD% | Sheet PnL |",
        "|-----|-------|---|-----|----------|------|----|----------|---------|-----------|",
    ]
    rows += _headline_rows(matrix)
    rows += [
        "",
        "## Selection bias",
        "",
        "Full 3×3 exit matrix is reported for transparency. Choosing a cell after seeing "
        "the table is **in-sample selection**. Primary path = sequential one-knob "
        "(target with stop=1.0× frozen, then stop with chosen target frozen). "
        "OOS never used to retune.",
        "",
        "## Artifacts",
        "",
        "- `compare.html` — sortable sequential + matrix (FULL / IS / OOS)",
        "- `metrics.csv` — numeric mirror",
        "- `closed_*.csv` — per-arm trade logs",
        "- `AB_PLAN.md` — hypothesis",
        "",
    ]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def write_ab_plan(path: Path) -> None:
    text = f"""# AB_PLAN — Weekly ATR reversal `{STAMP}`

## Hypothesis

Wide daily range (≥ 25% of 14-week ATR) on a **down day** (Close &lt; Open) marks
capitulation / exhaustion; buying the **next open** with weekly-ATR stops/targets
can show positive expectancy on liquid mega-caps (PaulTwenty).

## One-change discipline

1. **Entry freeze** held constant across all exit arms.
2. **Knob 1:** target mult (1 / 1.5 / 2) with stop frozen at 1.0×.
3. **Knob 2:** stop mult (0.5 / 1 / 1.5) with target frozen after knob 1.
4. Full 3×3 matrix = informational only (selection-bias labeled).
5. **Exit A/B (20260821 add):** control ATR tgt1.5/stop1.0 vs candidate
   target = signal-day High / stop = 0.5% below entry.

## Keep rule

Quality over N (Avg PnL%, PF, Ann ROR). OOS softens → HOLD, do not retune.
Research != gold != DailyRun.
"""
    path.write_text(text, encoding="utf-8")


def write_exit_sig_high_html(
    path: Path,
    univ: list[str],
    arms: list[dict[str, Any]],
    verd: str,
    note: str,
    n_skipped: int,
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>Weekly ATR reversal — signal-high exit A/B — {STAMP}</title>
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
<h1>Weekly ATR reversal — EXIT A/B: ATR control vs signal-high / 0.5% stop</h1>
<p><strong>Stamp:</strong> <code>weekly_atr_reversal_{STAMP}</code> · Generated {now}</p>
<div class="note">
<strong>Research only.</strong> Not gold. Not DailyRun. <strong>Same entry freeze</strong>
(14-week ATR, H−L ≥ 25%, Close &lt; Open, next open). One-knob EXIT compare.
<strong>Control:</strong> target 1.5× / stop 1.0× weekly ATR (frozen at signal).
<strong>Candidate:</strong> target = signal-day High; stop = entry × (1 − {BOX_STOP_PCT/100:.3f}).
If next open ≥ signal High → <strong>skip</strong> (not immediate TP). Skipped: {n_skipped}.
IS = entry &lt; 2024-01-01; OOS report-only. Click column headers to sort.
</div>
<p><strong>Universe:</strong> {html_mod.escape(", ".join(univ))} (N={len(univ)})</p>
<p><strong>Verdict:</strong> {html_mod.escape(verd)} — {html_mod.escape(note)}</p>

<h2>In-sample (entry &lt; 2024-01-01)</h2>
<table class="sortable"><caption>IS — click headers to sort</caption>{metric_rows_html(arms, "is")}</table>
<h2>Out-of-sample (entry ≥ 2024-01-01) — report only</h2>
<table class="sortable"><caption>OOS report-only — click headers to sort</caption>{metric_rows_html(arms, "oos")}</table>
<h2>Full book</h2>
<table class="sortable"><caption>Full — click headers to sort</caption>{metric_rows_html(arms, "full")}</table>

<h2>Honesty</h2>
<ul>
<li>Entry freeze identical; only exit geometry changes.</li>
<li>Candidate N may be slightly lower due to skip when entry ≥ signal High.</li>
<li>OOS softens → HOLD — never retune on OOS.</li>
<li>Ann ROR / Max DD via <code>compare_format.overlay_ann_ror_max_dd</code>
  sheet ${SHEET:,.0f} / initial ${INIT_ACCT:,.0f}.</li>
</ul>
{SORT_JS}
</body></html>
"""
    path.write_text(html, encoding="utf-8")


def write_exit_sig_high_baseline_append(
    path: Path,
    arms: list[dict[str, Any]],
    verd: str,
    note: str,
    n_skipped: int,
) -> None:
    """Append / rewrite EXIT A/B section into BASELINE.md."""
    block = [
        "",
        "## EXIT A/B — signal-high / 0.5% stop vs ATR control",
        "",
        "**One-knob EXIT** on the same entry freeze.",
        "",
        "| Item | Control | Candidate |",
        "|------|---------|-----------|",
        f"| Target | entry + {CTRL_TARGET}× weekly ATR | **signal-day High** |",
        f"| Stop | entry − {CTRL_STOP}× weekly ATR | **entry × (1 − {BOX_STOP_PCT/100:.3f})** ({BOX_STOP_PCT}% below) |",
        f"| Entry ≥ signal High | n/a (ATR target usually above) | **skip** (count={n_skipped}); not immediate TP |",
        f"| Time stop | {TIME_STOP_BARS} bars | {TIME_STOP_BARS} bars |",
        "",
        f"**Verdict: {verd}** — {note}",
        "",
        "| Arm | Split | N | WR% | Avg PnL% | AvgR | PF | Ann ROR% | Max DD% | Sheet PnL |",
        "|-----|-------|---|-----|----------|------|----|----------|---------|-----------|",
    ]
    block += _headline_rows(arms)
    block += [
        "",
        "Artifact: `exit_sig_high_ab.html`. Research only.",
        "",
    ]
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    marker = "## EXIT A/B — signal-high"
    if marker in text:
        text = text.split(marker)[0].rstrip() + "\n"
    path.write_text(text + "\n".join(block), encoding="utf-8")


def write_metrics_csv(
    path: Path,
    matrix: list[dict[str, Any]],
    tgt_arms: list[dict[str, Any]],
    stop_arms: list[dict[str, Any]],
    sys_verd: str,
    sys_note: str,
) -> None:
    fields = [
        "knob",
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
        for knob, arms in (
            ("system_control", [a for a in matrix if a.get("is_control")]),
            ("target_knob", tgt_arms),
            ("stop_knob", stop_arms),
            ("full_matrix", matrix),
        ):
            for a in arms:
                for split in ("full", "is", "oos"):
                    m = a[split]
                    verd = a.get("verd", "")
                    note = a.get("note", "")
                    if knob == "system_control":
                        verd, note = sys_verd, sys_note
                    w.writerow(
                        {
                            "knob": knob,
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
                            "verdict": verd if a["role"] != "control" or knob == "system_control" else "CONTROL",
                            "note": note if a["role"] != "control" or knob == "system_control" else "",
                        }
                    )


def _pick_best_tgt(tgt_arms: list[dict[str, Any]]) -> float:
    """Adopt a target candidate only on LEAN KEEP; else keep control (no OOS retune)."""
    ctrl = next(a for a in tgt_arms if a["tgt"] == CTRL_TARGET)
    best = ctrl
    for a in tgt_arms:
        if a["role"] != "candidate":
            continue
        if a.get("verd") != "LEAN KEEP":
            continue
        if a["is"]["n"] < 10:
            continue
        if a["is"]["avg_pnl"] > best["is"]["avg_pnl"] + 0.02 and a["is"]["pf"] >= best["is"]["pf"] - 0.02:
            best = a
    return float(best["tgt"])


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

    # Load once
    frames: dict[str, pd.DataFrame] = {}
    missing: list[str] = []
    for sym in univ:
        df = load_ohlc(sym)
        if df is None or len(df) < 400:
            missing.append(sym)
            continue
        frames[sym] = df

    # Full matrix trades
    grid_trades: dict[tuple[float, float], list[dict[str, Any]]] = {
        (t, s): [] for t in TARGET_MULTS for s in STOP_MULTS
    }
    for sym, df in frames.items():
        for t in TARGET_MULTS:
            for s in STOP_MULTS:
                grid_trades[(t, s)].extend(simulate_symbol(df, sym, t, s))

    matrix: list[dict[str, Any]] = []
    for t in TARGET_MULTS:
        for s in STOP_MULTS:
            name = arm_name(t, s)
            role = "control" if (t == CTRL_TARGET and s == CTRL_STOP) else "grid"
            p = pack_arm(name, role, grid_trades[(t, s)], tgt=t, stop=s, is_control=(role == "control"))
            matrix.append(p)

    ctrl_pack = next(a for a in matrix if a.get("is_control"))
    sys_verd, sys_note = system_verdict(ctrl_pack)

    # Sequential knob 1: target, stop=1.0
    tgt_arms: list[dict[str, Any]] = []
    for t in TARGET_MULTS:
        role = "control" if t == CTRL_TARGET else "candidate"
        p = pack_arm(arm_name(t, CTRL_STOP), role, grid_trades[(t, CTRL_STOP)], tgt=t, stop=CTRL_STOP)
        if role == "candidate":
            v, n = verdict_vs_control(
                ctrl_pack["is"],
                p["is"],
                ctrl_pack["oos"],
                p["oos"],
                cand_label=p["name"],
            )
            p["verd"], p["note"] = v, n
        tgt_arms.append(p)

    freeze_tgt = _pick_best_tgt(tgt_arms)
    tgt_notes = [
        f"{a['name']}: {a.get('verd', 'CONTROL')} — {a.get('note', 'control')}"
        for a in tgt_arms
    ]
    tgt_notes.append(
        f"Frozen target after knob 1 (LEAN KEEP only; else control): {freeze_tgt:g}×"
    )

    # Sequential knob 2: stop, target=freeze_tgt
    stop_ctrl_trades = grid_trades[(freeze_tgt, CTRL_STOP)]
    stop_ctrl = pack_arm(
        arm_name(freeze_tgt, CTRL_STOP),
        "control",
        stop_ctrl_trades,
        tgt=freeze_tgt,
        stop=CTRL_STOP,
    )
    stop_arms: list[dict[str, Any]] = [stop_ctrl]
    stop_notes: list[str] = []
    freeze_stop = CTRL_STOP
    best_stop_arm = stop_ctrl
    for s in STOP_MULTS:
        if s == CTRL_STOP:
            continue
        p = pack_arm(
            arm_name(freeze_tgt, s),
            "candidate",
            grid_trades[(freeze_tgt, s)],
            tgt=freeze_tgt,
            stop=s,
        )
        v, n = verdict_vs_control(
            stop_ctrl["is"],
            p["is"],
            stop_ctrl["oos"],
            p["oos"],
            cand_label=p["name"],
        )
        p["verd"], p["note"] = v, n
        stop_arms.append(p)
        stop_notes.append(f"{p['name']}: {v} — {n}")
        # Adopt only LEAN KEEP (OOS-soft HOLD stays on control — no OOS retune)
        if (
            v == "LEAN KEEP"
            and p["is"]["n"] >= 10
            and p["is"]["avg_pnl"] > best_stop_arm["is"]["avg_pnl"] + 0.02
            and p["is"]["pf"] >= best_stop_arm["is"]["pf"] - 0.02
        ):
            best_stop_arm = p
            freeze_stop = float(s)
    stop_notes.append(
        f"Frozen stop after knob 2 (LEAN KEEP only; else control): {freeze_stop:g}×"
    )

    # Write artifacts
    for (t, s), trades in grid_trades.items():
        write_trades_csv(OUT_DIR / f"closed_{arm_name(t, s)}.csv", trades)

    write_metrics_csv(
        OUT_DIR / "metrics.csv",
        matrix,
        tgt_arms,
        stop_arms,
        sys_verd,
        sys_note,
    )
    write_html(
        OUT_DIR / "compare.html",
        univ,
        matrix,
        tgt_arms,
        stop_arms,
        sys_verd,
        sys_note,
        freeze_tgt,
        freeze_stop,
    )
    write_baseline(
        OUT_DIR / "BASELINE.md",
        univ,
        matrix,
        tgt_arms,
        stop_arms,
        sys_verd,
        sys_note,
        freeze_tgt,
        freeze_stop,
        tgt_notes,
        stop_notes,
    )
    write_ab_plan(OUT_DIR / "AB_PLAN.md")

    # --- EXIT A/B: signal-high / 0.5% stop vs ATR control ---
    box_trades: list[dict[str, Any]] = []
    n_skipped = 0
    for sym, df in frames.items():
        tlist, sk = simulate_symbol_sig_high(df, sym)
        box_trades.extend(tlist)
        n_skipped += sk
    box_arms = [
        pack_arm(arm_name(CTRL_TARGET, CTRL_STOP), "control", grid_trades[(CTRL_TARGET, CTRL_STOP)]),
        pack_arm(BOX_ARM, "candidate", box_trades),
    ]
    box_verd, box_note = verdict_vs_control(
        box_arms[0]["is"],
        box_arms[1]["is"],
        box_arms[0]["oos"],
        box_arms[1]["oos"],
        cand_label=BOX_ARM,
    )
    box_arms[1]["verd"] = box_verd
    box_arms[1]["note"] = box_note
    write_trades_csv(OUT_DIR / f"closed_{BOX_ARM}.csv", box_trades)
    write_exit_sig_high_html(
        OUT_DIR / "exit_sig_high_ab.html",
        univ,
        box_arms,
        box_verd,
        box_note,
        n_skipped,
    )
    write_exit_sig_high_baseline_append(
        OUT_DIR / "BASELINE.md",
        box_arms,
        box_verd,
        box_note,
        n_skipped,
    )
    # Append metrics rows
    with (OUT_DIR / "metrics.csv").open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "knob",
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
            ],
        )
        for a in box_arms:
            for split in ("full", "is", "oos"):
                m = a[split]
                w.writerow(
                    {
                        "knob": "exit_sig_high",
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
                        "verdict": box_verd if a["role"] != "control" else "CONTROL",
                        "note": box_note if a["role"] != "control" else f"skipped_entry_ge_sig_high={n_skipped}",
                    }
                )

    print(f"stamp={OUT_DIR}")
    print(f"universe={len(univ)} loaded={len(frames)} missing={missing}")
    print(f"SYSTEM_VERDICT={sys_verd} — {sys_note}")
    print(f"RECOMMENDED_FREEZE=tgt{freeze_tgt:g}_stop{freeze_stop:g}")
    print("--- TARGET KNOB (stop=1.0) ---")
    for a in tgt_arms:
        for split in ("is", "oos"):
            m = a[split]
            print(
                f"{a['name']:18s} {split:4s} N={m['n']:4d} WR={m['wr']:5.1f} "
                f"Avg={m['avg_pnl']:6.2f} PF={m['pf']:5.2f} "
                f"AnnROR={m['ann_ror'] if math.isfinite(m['ann_ror']) else float('nan'):8.1f} "
                f"MaxDD={m['max_dd'] if math.isfinite(m['max_dd']) else float('nan'):6.2f}"
            )
    print("--- STOP KNOB ---")
    for a in stop_arms:
        for split in ("is", "oos"):
            m = a[split]
            print(
                f"{a['name']:18s} {split:4s} N={m['n']:4d} WR={m['wr']:5.1f} "
                f"Avg={m['avg_pnl']:6.2f} PF={m['pf']:5.2f} "
                f"AnnROR={m['ann_ror'] if math.isfinite(m['ann_ror']) else float('nan'):8.1f} "
                f"MaxDD={m['max_dd'] if math.isfinite(m['max_dd']) else float('nan'):6.2f}"
            )
    print("--- FULL MATRIX IS ---")
    for a in matrix:
        m = a["is"]
        print(
            f"{a['name']:18s} IS   N={m['n']:4d} WR={m['wr']:5.1f} "
            f"Avg={m['avg_pnl']:6.2f} PF={m['pf']:5.2f} "
            f"AnnROR={m['ann_ror'] if math.isfinite(m['ann_ror']) else float('nan'):8.1f}"
        )
    print(f"--- EXIT SIG_HIGH (skipped={n_skipped}) ---")
    for a in box_arms:
        for split in ("is", "oos", "full"):
            m = a[split]
            print(
                f"{a['name']:22s} {split:4s} N={m['n']:4d} WR={m['wr']:5.1f} "
                f"Avg={m['avg_pnl']:6.2f} PF={m['pf']:5.2f} "
                f"AnnROR={m['ann_ror'] if math.isfinite(m['ann_ror']) else float('nan'):8.1f} "
                f"MaxDD={m['max_dd'] if math.isfinite(m['max_dd']) else float('nan'):6.2f}"
            )
    print(f"EXIT_SIG_HIGH_VERDICT={box_verd} — {box_note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
