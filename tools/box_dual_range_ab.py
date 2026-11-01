#!/usr/bin/env python3
"""Dual-range box A/B: prior-day + 5-day buy zone; quarter vs eighth + BE nest.

Long-only research engine.
  Knob 1 (fraction): lower/upper quarter (control) vs eighth (candidate).
  Knob 2 (nested on quarter freeze): BE-off (control) vs BE-on (candidate).
BE-on: after entry, when High touches/exceeds frozen prior-day box high
(lower-box top), raise stop to entry (break-even). Initial stop remains
1% below frozen 5-day box low until then. TP still top fraction of 5-day box.

Usage:
  python tools/box_dual_range_ab.py
  python tools/box_dual_range_ab.py --universe SPY,QQQ,AAPL
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
OUT_DIR = DRIVE / "paul_experiments" / f"box_dual_range_{STAMP}"
PAULTWENTY = DRIVE / "universes" / "PaulTwenty_universe.csv"
IS_CUT = date(2024, 1, 1)

# --- Freeze ---
BOX5_N = 5
STOP_BELOW_PCT = 1.0  # 1% below frozen 5-day box low
TIME_STOP_BARS = 60
MIN_PRICE = 5.0
MIN_ADV20 = 500_000.0
SHEET = 45_000.0
INIT_ACCT = DEFAULT_INITIAL_ACCOUNT
COSTS_BPS = 0.0
# Fraction arms: control = quarter, candidate = eighth
FRAC_QUARTER = 0.25
FRAC_EIGHTH = 0.125
# BE fill: exact entry; tiny eps only if needed for fill identity
BE_EPS = 0.0


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


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Prior-day and 5-day boxes ending prior bar (no look-ahead into signal bar)."""
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    vol = df["Volume"].astype(float)
    out = df.copy()
    # Prior-day box = previous session H/L
    out["pd_high"] = high.shift(1)
    out["pd_low"] = low.shift(1)
    # 5-day box = HH/LL of bars [t-5 .. t-1]
    out["w_high"] = high.shift(1).rolling(BOX5_N, min_periods=BOX5_N).max()
    out["w_low"] = low.shift(1).rolling(BOX5_N, min_periods=BOX5_N).min()
    out["adv20"] = vol.rolling(20, min_periods=20).mean()
    return out


def in_lower_frac(close: float, box_lo: float, box_hi: float, frac: float) -> bool:
    h = box_hi - box_lo
    if not (math.isfinite(h) and h > 0 and math.isfinite(close)):
        return False
    return box_lo <= close <= (box_lo + frac * h)


def top_frac_level(box_lo: float, box_hi: float, frac: float) -> float:
    """Price level where top fraction begins (box_hi - frac*height)."""
    return box_hi - frac * (box_hi - box_lo)


def signal_at(row: pd.Series, frac: float) -> bool:
    c = float(row["Close"])
    if c < MIN_PRICE:
        return False
    adv = float(row["adv20"]) if math.isfinite(float(row["adv20"])) else 0.0
    if adv < MIN_ADV20:
        return False
    pd_h, pd_l = float(row["pd_high"]), float(row["pd_low"])
    w_h, w_l = float(row["w_high"]), float(row["w_low"])
    if not all(math.isfinite(x) for x in (pd_h, pd_l, w_h, w_l)):
        return False
    return in_lower_frac(c, pd_l, pd_h, frac) and in_lower_frac(c, w_l, w_h, frac)


def simulate_symbol(
    df: pd.DataFrame,
    sym: str,
    arm: str,
    frac: float,
    be_on: bool = False,
) -> list[dict[str, Any]]:
    """Simulate one arm. be_on: raise stop to entry when High >= frozen prior-day high.

    Lower box = prior-day H–L (signal-frozen). BE trigger = High touches/exceeds
    prior-day box high. Same-bar: stop-first with pre-BE stop before arming BE
    (conservative; no intrabar path). AvgR uses initial risk (entry − stop0).
    """
    prep = prepare(df)
    trades: list[dict[str, Any]] = []
    i = max(BOX5_N + 1, 25)
    n = len(prep)
    while i < n - 2:
        row = prep.iloc[i]
        if not signal_at(row, frac):
            i += 1
            continue
        entry_i = i + 1
        if entry_i >= n:
            break
        entry_row = prep.iloc[entry_i]
        entry = float(entry_row["Open"])
        w_hi = float(row["w_high"])
        w_lo = float(row["w_low"])
        pd_hi = float(row["pd_high"])
        pd_lo = float(row["pd_low"])
        if entry <= 0 or not math.isfinite(w_hi) or not math.isfinite(w_lo) or w_hi <= w_lo:
            i += 1
            continue
        if not math.isfinite(pd_hi):
            i += 1
            continue
        stop0 = w_lo * (1.0 - STOP_BELOW_PCT / 100.0)
        be_stop = entry - BE_EPS
        target = top_frac_level(w_lo, w_hi, frac)
        risk = entry - stop0
        if risk <= 0:
            # Entry already at/below stop — skip
            i += 1
            continue
        if target <= entry:
            # Target not above entry (box already compressed / close near top of lower zone) — skip
            i += 1
            continue

        # If entry already clears lower-box top, arm BE immediately at fill
        be_armed = bool(be_on and entry >= pd_hi)
        stop = be_stop if be_armed else stop0

        exit_i = None
        exit_px = None
        exit_type = "TIME"
        last = min(entry_i + TIME_STOP_BARS, n - 1)
        for j in range(entry_i + 1, last + 1):
            bar = prep.iloc[j]
            o, h, lo = float(bar["Open"]), float(bar["High"]), float(bar["Low"])
            if o <= stop:
                exit_i, exit_px, exit_type = j, o, ("GAP_DOWN_BE" if be_armed else "GAP_DOWN")
                break
            if lo <= stop:
                tag = "STOP_BE" if be_armed else "STOP"
                exit_i, exit_px, exit_type = j, stop, tag
                break
            if o >= target:
                exit_i, exit_px, exit_type = j, o, "GAP_UP"
                break
            if h >= target:
                exit_i, exit_px, exit_type = j, target, "TARGET"
                break
            # Arm BE after stop/target checks on this bar (BE applies next bar+)
            if be_on and not be_armed and h >= pd_hi:
                be_armed = True
                stop = be_stop
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
                "stop": stop0,
                "stop_final": stop,
                "be_armed": int(be_armed),
                "target": target,
                "exit_px": float(exit_px),
                "exit": exit_type,
                "pnl": pnl_pct,
                "r": r_mult,
                "days": float(days),
                "pnl_d": pnl_pct / 100.0 * SHEET,
                "signal_date": row["Date"],
                "pd_high": pd_hi,
                "pd_low": pd_lo,
                "w_high": w_hi,
                "w_low": w_lo,
                "frac": frac,
                "be_on": int(be_on),
            }
        )
        i = exit_i + 1
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


def verdict(
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


def write_trades_csv(path: Path, trades: list[dict[str, Any]]) -> None:
    fields = [
        "SYMBOL",
        "ARM",
        "DATE_OPENED",
        "DATE_CLOSED",
        "ENTRY_PRICE",
        "STOP_PRICE",
        "STOP_FINAL",
        "BE_ARMED",
        "BE_ON",
        "TARGET_PRICE",
        "EXIT_PRICE",
        "EXIT_TYPE",
        "PNL_PCT",
        "R_MULT",
        "DAYS_HELD",
        "PNL_DOLLARS",
        "SIGNAL_DATE",
        "PD_HIGH",
        "PD_LOW",
        "W_HIGH",
        "W_LOW",
        "FRAC",
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
                    "STOP_FINAL": f"{t.get('stop_final', t['stop']):.4f}",
                    "BE_ARMED": t.get("be_armed", 0),
                    "BE_ON": t.get("be_on", 0),
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
                    "PD_HIGH": f"{t['pd_high']:.4f}",
                    "PD_LOW": f"{t['pd_low']:.4f}",
                    "W_HIGH": f"{t['w_high']:.4f}",
                    "W_LOW": f"{t['w_low']:.4f}",
                    "FRAC": f"{t['frac']:.4f}",
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


def write_html(
    path: Path,
    frac_arms: list[dict[str, Any]],
    be_arms: list[dict[str, Any]],
    univ: list[str],
    frac_verd: str,
    frac_note: str,
    be_verd: str,
    be_note: str,
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>Box dual-range — fraction + BE nest — {STAMP}</title>
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
<h1>Dual-range box — prior-day + 5-day (fraction A/B + BE nest on quarter)</h1>
<p><strong>Stamp:</strong> <code>box_dual_range_{STAMP}</code> · Generated {now}</p>
<div class="note">
<strong>Research only.</strong> Not gold. Not DailyRun.
<strong>Knob 1:</strong> fraction quarter vs eighth (entry + matching exit).
<strong>Knob 2 (nested on quarter freeze):</strong> Break-Even (BE) off vs on —
when High ≥ frozen prior-day (lower) box high → stop = entry; initial stop stays
{STOP_BELOW_PCT:.0f}% below frozen 5-day low until then. Weekly box = trailing 5 sessions.
IS = entry &lt; 2024-01-01; OOS report-only — do not retune.
Click column headers to sort.
</div>
<p><strong>Universe:</strong> {html_mod.escape(", ".join(univ))} (N={len(univ)})</p>
<p><strong>Fraction verdict:</strong> {html_mod.escape(frac_verd)} — {html_mod.escape(frac_note)}</p>
<p><strong>BE nest verdict (quarter freeze):</strong> {html_mod.escape(be_verd)} — {html_mod.escape(be_note)}</p>

<h2>1. Freeze</h2>
<ul>
<li><strong>Prior-day (lower) box:</strong> High–Low of session t−1. BE trigger = High touches/exceeds this High.</li>
<li><strong>5-day (“weekly”) box:</strong> HH/LL of sessions t−5 … t−1 (ending prior bar; no look-ahead).</li>
<li><strong>Buy:</strong> Close of t in lower fraction of <em>both</em> boxes; entry next open.</li>
<li><strong>Fraction control:</strong> 1/4. <strong>Fraction candidate:</strong> 1/8. Exit fraction matches entry arm.</li>
<li><strong>Take profit:</strong> price reaches top same fraction of <em>frozen</em> 5-day box.</li>
<li><strong>Initial stop:</strong> cross {STOP_BELOW_PCT:.0f}% below frozen 5-day box low; stop-first same bar; time {TIME_STOP_BARS} bars.</li>
<li><strong>BE-on (nested):</strong> after High ≥ frozen prior-day high, working stop = entry (BE_EPS={BE_EPS}). Same-bar: stop-first before arming BE. If entry open already ≥ prior-day high, arm at fill.</li>
<li><strong>Liquidity:</strong> Close ≥ ${MIN_PRICE:.0f}, ADV20 ≥ {MIN_ADV20:,.0f}. Long-only. Costs {COSTS_BPS} bps.</li>
</ul>

<h2>A. Fraction A/B — Full book</h2>
<table class="sortable"><caption>Click column headers to sort</caption>{metric_rows_html(frac_arms, "full")}</table>
<h2>A. Fraction — In-sample (entry &lt; 2024-01-01)</h2>
<table class="sortable"><caption>IS — click headers to sort</caption>{metric_rows_html(frac_arms, "is")}</table>
<h2>A. Fraction — Out-of-sample (entry ≥ 2024-01-01) — report only</h2>
<table class="sortable"><caption>OOS report-only — click headers to sort</caption>{metric_rows_html(frac_arms, "oos")}</table>

<h2>B. BE nest on quarter — Full book</h2>
<table class="sortable"><caption>BE-off vs BE-on (quarter freeze) — click headers to sort</caption>{metric_rows_html(be_arms, "full")}</table>
<h2>B. BE nest — In-sample</h2>
<table class="sortable"><caption>IS — click headers to sort</caption>{metric_rows_html(be_arms, "is")}</table>
<h2>B. BE nest — Out-of-sample — report only</h2>
<table class="sortable"><caption>OOS report-only — click headers to sort</caption>{metric_rows_html(be_arms, "oos")}</table>

<h2>Honesty</h2>
<ul>
<li>Fraction arms frozen before judging; BE nest is a separate one-knob on the quarter freeze (winning/control fraction after eighth DISMISS).</li>
<li>OOS is report-only — never retune on OOS.</li>
<li>Ann ROR / Max DD via Closed overlay (<code>compare_format.overlay_ann_ror_max_dd</code>) sheet ${SHEET:,.0f} / initial ${INIT_ACCT:,.0f}.</li>
<li>Research ≠ gold ≠ DailyRun.</li>
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
    frac_arms: list[dict[str, Any]],
    be_arms: list[dict[str, Any]],
    frac_verd: str,
    frac_note: str,
    be_verd: str,
    be_note: str,
) -> None:
    rows = [
        f"# BASELINE — Dual-range box (prior-day + 5-day) — `box_dual_range_{STAMP}`",
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
        "| Prior-day (lower) box | High/Low of session t−1 |",
        f"| 5-day (“weekly”) box | HH/LL of sessions t−5 … t−1 (trailing {BOX5_N} completed days ending prior bar). **Choice:** use 5-day range, not calendar-week HH/LL — cleaner, no weekday alignment, matches “5-day box” wording. |",
        "| Signal | Close(t) in lower fraction of **both** boxes |",
        "| Entry | Next open (t+1) — Trading by Numbers (TBN) style |",
        f"| Fraction control | Fraction = {FRAC_QUARTER} (quarter): buy lower 1/4; TP top 1/4 of frozen 5-day box |",
        f"| Fraction candidate | Fraction = {FRAC_EIGHTH} (eighth): buy lower 1/8; TP top 1/8 of frozen 5-day box |",
        "| Exit fraction | **Matches entry arm** (one-knob honesty) |",
        f"| Initial stop | Cross {STOP_BELOW_PCT:.0f}% below **frozen** 5-day box low (signal-time); stop-first same bar |",
        "| BE nest (on quarter) | **BE-off** = control (initial stop only). **BE-on** = when High ≥ frozen prior-day box high → working stop = entry (break-even). Entry open ≥ prior-day high arms at fill. Same-bar: stop-first before arming BE. |",
        "| Target / stop boxes | Frozen at signal (not rolled while in trade) |",
        f"| Time stop | {TIME_STOP_BARS} bars (research safety) |",
        f"| Liquidity | Close ≥ ${MIN_PRICE:.0f}; Average Daily Volume 20 (ADV20) ≥ {MIN_ADV20:,.0f} |",
        f"| Costs | {COSTS_BPS} bps |",
        f"| IS / OOS | IS = entry_date < {IS_CUT.isoformat()}; OOS ≥ cut — **report-only, never retune** |",
        f"| Overlay cash | Sheet ${SHEET:,.0f}; Initial_Account ${INIT_ACCT:,.0f} |",
        "",
        "## Ambiguities resolved",
        "",
        "1. **Weekly box** = trailing 5-session HH/LL (documented above), not ISO calendar week.",
        "2. **Buy “price in zone”** = signal **Close** inside lower fraction (not Low-probe).",
        "3. **Exit fraction** matches entry arm (not a frozen single exit fraction across arms).",
        "4. **Stop/target geometry** frozen at signal bar (not rolling 5-day during hold).",
        "5. **Lower box for BE** = prior-day High–Low; trigger = High touches/exceeds prior-day High (not Close).",
        "6. **BE same-bar** = stop-first with pre-BE stop; BE arms for subsequent bars only (unless entry already cleared prior-day high).",
        "",
        "## Verdict — fraction (quarter vs eighth)",
        "",
        f"**{frac_verd}** — {frac_note}",
        "",
        "## Verdict — BE nest (quarter freeze, BE-off vs BE-on)",
        "",
        f"**{be_verd}** — {be_note}",
        "",
        "Research ≠ gold ≠ DailyRun. Do not wire DailyRun from this stamp.",
        "",
        "## Headline IS / OOS — Fraction",
        "",
        "| Arm | Split | N | WR% | Avg PnL% | AvgR | PF | Ann ROR% | Max DD% | Sheet PnL |",
        "|-----|-------|---|-----|----------|------|----|----------|---------|-----------|",
    ]
    rows += _headline_rows(frac_arms)
    rows += [
        "",
        "## Headline IS / OOS — BE nest (quarter)",
        "",
        "| Arm | Split | N | WR% | Avg PnL% | AvgR | PF | Ann ROR% | Max DD% | Sheet PnL |",
        "|-----|-------|---|-----|----------|------|----|----------|---------|-----------|",
    ]
    rows += _headline_rows(be_arms)
    rows += [
        "",
        "## Selection bias",
        "",
        "Fraction freeze written before that compare. BE nest added after eighth DISMISS, nested on quarter (control/winning fraction) as a separate one-knob — labeled; not an OOS retune. Further post-hoc knob changes after seeing BE results = new stamp.",
        "",
        "## Artifacts",
        "",
        "- `compare.html` — sortable fraction + BE nest (FULL / IS / OOS)",
        "- `metrics.csv` — numeric mirror (both knobs)",
        "- `closed_quarter.csv` / `closed_eighth.csv` / `closed_quarter_be.csv` — trade logs",
        "- `AB_PLAN.md` — hypothesis",
        "",
    ]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def write_metrics_csv(
    path: Path,
    frac_arms: list[dict[str, Any]],
    be_arms: list[dict[str, Any]],
    frac_verd: str,
    frac_note: str,
    be_verd: str,
    be_note: str,
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
        for knob, arms, verd, note in (
            ("fraction", frac_arms, frac_verd, frac_note),
            ("be_nest_quarter", be_arms, be_verd, be_note),
        ):
            for a in arms:
                for split in ("full", "is", "oos"):
                    m = a[split]
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

    q_trades: list[dict[str, Any]] = []
    e_trades: list[dict[str, Any]] = []
    q_be_trades: list[dict[str, Any]] = []
    missing: list[str] = []
    for sym in univ:
        df = load_ohlc(sym)
        if df is None or len(df) < 80:
            missing.append(sym)
            continue
        q_trades.extend(simulate_symbol(df, sym, "quarter", FRAC_QUARTER, be_on=False))
        e_trades.extend(simulate_symbol(df, sym, "eighth", FRAC_EIGHTH, be_on=False))
        q_be_trades.extend(
            simulate_symbol(df, sym, "quarter_be", FRAC_QUARTER, be_on=True)
        )

    frac_arms = [
        pack_arm("Quarter (1/4)", "control", q_trades),
        pack_arm("Eighth (1/8)", "candidate", e_trades),
    ]
    frac_verd, frac_note = verdict(
        frac_arms[0]["is"],
        frac_arms[1]["is"],
        frac_arms[0]["oos"],
        frac_arms[1]["oos"],
        cand_label="eighth",
    )
    frac_arms[1]["verd"] = frac_verd
    frac_arms[1]["note"] = frac_note

    be_arms = [
        pack_arm("Quarter BE-off", "control", q_trades),
        pack_arm("Quarter BE-on", "candidate", q_be_trades),
    ]
    be_verd, be_note = verdict(
        be_arms[0]["is"],
        be_arms[1]["is"],
        be_arms[0]["oos"],
        be_arms[1]["oos"],
        cand_label="BE-on",
    )
    be_arms[1]["verd"] = be_verd
    be_arms[1]["note"] = be_note

    write_trades_csv(OUT_DIR / "closed_quarter.csv", q_trades)
    write_trades_csv(OUT_DIR / "closed_eighth.csv", e_trades)
    write_trades_csv(OUT_DIR / "closed_quarter_be.csv", q_be_trades)
    write_metrics_csv(
        OUT_DIR / "metrics.csv",
        frac_arms,
        be_arms,
        frac_verd,
        frac_note,
        be_verd,
        be_note,
    )
    write_html(
        OUT_DIR / "compare.html",
        frac_arms,
        be_arms,
        univ,
        frac_verd,
        frac_note,
        be_verd,
        be_note,
    )
    write_baseline(
        OUT_DIR / "BASELINE.md",
        univ,
        frac_arms,
        be_arms,
        frac_verd,
        frac_note,
        be_verd,
        be_note,
    )

    print(f"stamp={OUT_DIR}")
    print(f"universe={len(univ)} missing={missing}")
    print("--- FRACTION ---")
    for a in frac_arms:
        for split in ("is", "oos", "full"):
            m = a[split]
            print(
                f"{a['name']:16s} {split:4s} N={m['n']:4d} WR={m['wr']:5.1f} "
                f"Avg={m['avg_pnl']:6.2f} PF={m['pf']:5.2f} "
                f"AnnROR={m['ann_ror'] if math.isfinite(m['ann_ror']) else float('nan'):8.1f} "
                f"MaxDD={m['max_dd'] if math.isfinite(m['max_dd']) else float('nan'):6.2f}"
            )
    print(f"FRACTION_VERDICT={frac_verd} — {frac_note}")
    print("--- BE NEST (quarter) ---")
    for a in be_arms:
        for split in ("is", "oos", "full"):
            m = a[split]
            print(
                f"{a['name']:16s} {split:4s} N={m['n']:4d} WR={m['wr']:5.1f} "
                f"Avg={m['avg_pnl']:6.2f} PF={m['pf']:5.2f} "
                f"AnnROR={m['ann_ror'] if math.isfinite(m['ann_ror']) else float('nan'):8.1f} "
                f"MaxDD={m['max_dd'] if math.isfinite(m['max_dd']) else float('nan'):6.2f}"
            )
    print(f"BE_VERDICT={be_verd} — {be_note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
