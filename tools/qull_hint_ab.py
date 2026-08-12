#!/usr/bin/env python3
"""QULL ImprovePriority A/B suite (stamp 260810110101 / full universe).

Control = production ``run_qull.bat`` / ``run_qullamaggie_htf.bat`` knobs:
  qull_setup=htf, prior_run=0.50, coil=10/0.15, trail_ema=10, vol_bo=1.5,
  market_filter=true, cooldown=5, max_positions=0, SMA gates OFF.

One knob (or coherent skip) per arm; ≤2 alts per hypothesis.
See ``docs/HYPOTHESIS_TEST.md`` and ``drive/paul_experiments/CANONICAL_COMPARE_METRICS.md``.

ImprovePriority → QULL lever map:
  stop_pct expand     → qull_max_stop_adr_mult (widen ADR gate) / qull_stop_under=coil_low
  band_pct tighten    → qull_coil_range_pct (tighter coil)
  winner_peak_giveback→ qull_trail_ema=20
  false_start_2022-23 → entry_start_date=2024-01-01
  peer longer/target  → skip (insufficient / overlaps trail)
  chart SMA50         → qull_require_above_sma50 / qull_require_sma50_rising
  chart SMA20/SMA10   → qull_require_above_sma20 / qull_require_above_sma10
  loosen levers       → prior_run↓, coil_range↑, coil_bars↓, vol_bo↓,
                        market_filter off, ema_surf off, ADR gate↑

SMA defs (documented in comparison.html):
  above  = fill/entry price ≥ SMAn on fill bar (also signal close ≥ SMAn)
  rising = SMA50[signal] > SMA50[signal − N], N=qull_sma50_slope_bars (default 10);
           flat or down fails (strict).

Usage (repo root)::

  python tools/qull_hint_ab.py --reuse-control 260810110101
  run_qull_hint_ab.bat
  run_qull_hint_ab.bat 260810110101
"""
from __future__ import annotations

import argparse
import csv
import html
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
SA = REPO / "stock_analysis"
DATA_DIR = REPO / "data" / "newdata" / "data"
DRIVE = REPO / "drive"
DEFAULT_OUT = (
    DRIVE
    / "paul_experiments"
    / "tbn_new_systems"
    / "qull_ep_htf"
    / "ab_improve_prio_260810"
)
DEFAULT_CONTROL = "260810110101"
sys.path.insert(0, str(DRIVE / "paul_experiments"))
try:
    from compare_format import format_money, format_money_delta  # type: ignore
except ImportError:
    def format_money(value: Any, *, blank: str = "—") -> str:
        try:
            n = float(str(value).replace(",", "").replace("$", ""))
        except (TypeError, ValueError):
            return blank
        sign = "-" if n < 0 else ""
        return f"{sign}${abs(n):,.2f}"

    def format_money_delta(value: Any, *, blank: str = "—") -> str:
        try:
            n = float(str(value).replace(",", "").replace("$", ""))
        except (TypeError, ValueError):
            return blank
        sign = "+" if n >= 0 else "-"
        return f"{sign}${abs(n):,.2f}"

# Production BASE matching run_qullamaggie_htf.bat
QULL_BASE_V = [
    "qull_mode=true",
    "brt_zones=false",
    "yh_zones=false",
    "wpbr_zones=false",
    "rl_mode=false",
    "relative_strength_enabled=false",
    "rs_mode=false",
    "indicator_buy=off",
    "sb_mode=false",
    "mvcp_mode=false",
    "qull_setup=htf",
    "qull_prior_run_pct=0.50",
    "qull_coil_bars=10",
    "qull_coil_range_pct=0.15",
    "qull_trail_ema=10",
    "qull_vol_breakout_mult=1.5",
    "qull_market_filter=true",
    "qull_require_above_sma50=false",
    "qull_require_sma50_rising=false",
    "qull_sma50_slope_bars=10",
    "qull_require_above_sma20=false",
    "qull_require_above_sma10=false",
    "symbol_reentry_cooldown_days=5",
    "max_positions=0",
]

SORTABLE_TH_CSS = """
th.sortable-th{cursor:pointer;user-select:none;white-space:nowrap}
th.sortable-th:hover{background:#e2e8f0}
th.sortable-th .sort-ind::after{content:" \\2195";opacity:.35;font-size:.85em}
th.sortable-th.sort-asc .sort-ind::after{content:" \\2191";opacity:.9}
th.sortable-th.sort-desc .sort-ind::after{content:" \\2193";opacity:.9}
"""

SORTABLE_TABLE_SCRIPT = """
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
      var av = parseSortValue(a.cells[col] && a.cells[col].textContent, type);
      var bv = parseSortValue(b.cells[col] && b.cells[col].textContent, type);
      if (typeof av === "string" || typeof bv === "string") {
        return dir * String(av).localeCompare(String(bv));
      }
      return dir * (av - bv);
    });
    movable.concat(pinned).forEach(function (r) { tbody.appendChild(r); });
  }
  function bind(table) {
    var ths = table.querySelectorAll("th.sortable-th");
    ths.forEach(function (th, idx) {
      function activate() {
        var type = th.getAttribute("data-sort") || "text";
        var asc = !th.classList.contains("sort-asc");
        ths.forEach(function (x) {
          x.classList.remove("sort-asc", "sort-desc");
          x.setAttribute("aria-sort", "none");
        });
        th.classList.add(asc ? "sort-asc" : "sort-desc");
        th.setAttribute("aria-sort", asc ? "ascending" : "descending");
        sortTable(table, idx, type, asc ? 1 : -1);
      }
      th.addEventListener("click", activate);
      th.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activate(); }
      });
    });
  }
  document.querySelectorAll("table.sortable").forEach(bind);
})();
</script>
"""


def sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{html.escape(sort_type)}" '
        f'tabindex="0" role="columnheader" aria-sort="none">'
        f"{html.escape(label)}<span class=\"sort-ind\"></span></th>"
    )


@dataclass
class Arm:
    arm_id: str
    hypothesis_id: str
    family: str  # param | pattern | peer | chart | skip
    suggestion: str
    extras: list[str] = field(default_factory=list)
    is_control: bool = False
    skip: bool = False
    skip_reason: str = ""


def _resolve_python() -> str:
    env_py = os.environ.get("PY", "").strip()
    if env_py and Path(env_py).is_file():
        return env_py
    return sys.executable


def _safe_num(x: Any) -> float:
    if x is None or x == "" or str(x).strip().upper() == "N/A":
        return 0.0
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).replace("%", "").replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def _latest(outdir: Path, pattern: str) -> Optional[Path]:
    files = sorted(outdir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def build_arms() -> list[Arm]:
    """Arms from QULL_ImprovePriority_260810110101 + chart SMA + loosen levers."""
    return [
        Arm(
            "00_control",
            "baseline_run_qull_110101",
            "param",
            "Production run_qull.bat: HTF, prior=0.50, coil=10/0.15, trail=10, "
            "vol_bo=1.5, market_filter ON, cooldown=5, SMA gates OFF. Full universe.",
            is_control=True,
        ),
        Arm(
            "01_stop_expand_adr_15",
            "stop_pct_tension_expand_vs_hold",
            "param",
            "stop_pct expand mapped to QULL ADR gate: qull_max_stop_adr_mult=1.5 "
            "(prod 1.0) - allows wider stop distance vs ADR.",
            ["qull_max_stop_adr_mult=1.5"],
        ),
        Arm(
            "02_band_coil_tighten_10",
            "band_tighten_weak_fill",
            "param",
            "band_pct tighten -> tighter coil: qull_coil_range_pct=0.10 (prod 0.15).",
            ["qull_coil_range_pct=0.10"],
        ),
        Arm(
            "03_trail_ema_20",
            "winner_peak_giveback",
            "pattern",
            "winner_peak_giveback: slower trail qull_trail_ema=20 (prod 10) to lock less giveback.",
            ["qull_trail_ema=20"],
        ),
        Arm(
            "04_false_start_2024",
            "false_start_2022_2023",
            "pattern",
            "false_start_2022_2023: entry_start_date=2024-01-01 (drops 2022-23 STOP cluster).",
            ["entry_start_date=2024-01-01"],
        ),
        Arm(
            "05_peer_wider_stop_coil",
            "peer_wider_stop_won_rs",
            "peer",
            "peer wider stop: geometric wider stop via qull_stop_under=coil_low (prod breakout_low).",
            ["qull_stop_under=coil_low"],
        ),
        Arm(
            "06_peer_longer_hold_skip",
            "peer_longer_hold_won_rs",
            "skip",
            "peer longer hold / target-after-stop - insufficient confidence; overlaps trail_ema arm.",
            skip=True,
            skip_reason=(
                "Insufficient confidence (4 / 3 overlaps). Longer-hold lever already tested "
                "as 03_trail_ema_20. Skip duplicate; do not invent target_pct (QULL DNA is "
                "STOP/GAP -> TRAIL_EMA, no fixed target)."
            ),
        ),
        Arm(
            "07_host_stop_pct_skip",
            "stop_pct_host_noop",
            "skip",
            "Literal host stop_pct / target_pct are unwired in rocket_qull_htf DNA.",
            skip=True,
            skip_reason=(
                "N/A / noop: QULL stop = breakout_low|coil_low + ADR gate; host stop_pct "
                "does not move QULL stops. Use arms 01 / 05 instead."
            ),
        ),
        Arm(
            "08_sma50_above",
            "chart_entry_above_sma50",
            "chart",
            "Chart: losers when entry below SMA50 -> require entry >= SMA50 "
            "(qull_require_above_sma50=true).",
            ["qull_require_above_sma50=true"],
        ),
        Arm(
            "09_sma50_rising",
            "chart_sma50_rising",
            "chart",
            "Chart: losers when SMA50 flat/down -> require SMA50 rising over 10 bars "
            "(qull_require_sma50_rising=true, slope_bars=10).",
            ["qull_require_sma50_rising=true", "qull_sma50_slope_bars=10"],
        ),
        Arm(
            "10_sma50_above_and_rising",
            "chart_sma50_above_and_rising",
            "chart",
            "Combined: above SMA50 AND rising (both gates ON).",
            [
                "qull_require_above_sma50=true",
                "qull_require_sma50_rising=true",
                "qull_sma50_slope_bars=10",
            ],
        ),
        # --- Loosen levers (expect MORE trades) ---
        Arm(
            "11_loosen_prior_run_40",
            "loosen_prior_run_pct",
            "param",
            "Loosen prior-run: qull_prior_run_pct=0.40 (prod 0.50). Expect more HTF setups.",
            ["qull_prior_run_pct=0.40"],
        ),
        Arm(
            "12_loosen_prior_run_30",
            "loosen_prior_run_pct",
            "param",
            "Loosen prior-run alt: qull_prior_run_pct=0.30 (prod 0.50). Expect still more trades.",
            ["qull_prior_run_pct=0.30"],
        ),
        Arm(
            "13_loosen_coil_range_20",
            "loosen_coil_range",
            "param",
            "Widen coil: qull_coil_range_pct=0.20 (prod 0.15). Expect more coil-pass setups.",
            ["qull_coil_range_pct=0.20"],
        ),
        Arm(
            "14_loosen_coil_range_25",
            "loosen_coil_range",
            "param",
            "Widen coil alt: qull_coil_range_pct=0.25 (prod 0.15). Expect more trades.",
            ["qull_coil_range_pct=0.25"],
        ),
        Arm(
            "15_loosen_coil_bars_7",
            "loosen_coil_bars",
            "param",
            "Shorter coil window: qull_coil_bars=7 (prod 10). Expect more / earlier breakouts.",
            ["qull_coil_bars=7"],
        ),
        Arm(
            "16_loosen_vol_bo_12",
            "loosen_vol_breakout",
            "param",
            "Lower breakout vol mult: qull_vol_breakout_mult=1.2 (prod 1.5). Expect more trades.",
            ["qull_vol_breakout_mult=1.2"],
        ),
        Arm(
            "17_loosen_market_filter_off",
            "loosen_spy_market_filter",
            "param",
            "Relax SPY filter: qull_market_filter=false (prod true). Expect more trades.",
            ["qull_market_filter=false"],
        ),
        Arm(
            "18_loosen_ema_surf_off",
            "loosen_ema_surf",
            "param",
            "Relax EMA surf: qull_require_ema_surf=false (prod true). Expect more trades.",
            ["qull_require_ema_surf=false"],
        ),
        # --- Tighten SMA20 / SMA10 (mirror SMA50 above) ---
        Arm(
            "19_sma20_above",
            "chart_entry_above_sma20",
            "chart",
            "Tighten: require entry >= SMA20 (qull_require_above_sma20=true). Expect fewer trades.",
            ["qull_require_above_sma20=true"],
        ),
        Arm(
            "20_sma10_above",
            "chart_entry_above_sma10",
            "chart",
            "Tighten: require entry >= SMA10 (qull_require_above_sma10=true). Expect fewer trades.",
            ["qull_require_above_sma10=true"],
        ),
    ]


def _exit_mix(closed: Path) -> dict[str, int]:
    c: Counter[str] = Counter()
    if not closed.is_file():
        return {}
    with closed.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        for row in csv.DictReader(f):
            et = (row.get("EXIT_TYPE") or row.get("Exit_Type") or "").strip() or "?"
            c[et] += 1
    return dict(c)


def _summary_aggs(summary: Path) -> dict[str, float]:
    out = {
        "mean_paul": 0.0,
        "sum_paul": 0.0,
        "mean_fit": 0.0,
        "sum_fit": 0.0,
        "mean_fit_robust": 0.0,
        "sum_fit_robust": 0.0,
        "mean_avg_pnl_wo_max": 0.0,
        "mean_outlier_pct": 0.0,
        "mean_tpy": 0.0,
        "mean_max_win": 0.0,
        "n_sym": 0.0,
    }
    if not summary.is_file():
        return out
    rows = list(csv.DictReader(summary.open(encoding="utf-8-sig", errors="replace")))
    if not rows:
        return out
    n = float(len(rows))
    out["n_sym"] = n

    def mean(col: str) -> float:
        vals = [_safe_num(r.get(col)) for r in rows]
        return sum(vals) / n if n else 0.0

    def ssum(col: str) -> float:
        return sum(_safe_num(r.get(col)) for r in rows)

    out["mean_paul"] = mean("PAUL_SCORE")
    out["sum_paul"] = ssum("PAUL_SCORE")
    out["mean_fit"] = mean("FIT_SCORE")
    out["sum_fit"] = ssum("FIT_SCORE")
    out["mean_fit_robust"] = mean("FIT_SCORE_ROBUST")
    out["sum_fit_robust"] = ssum("FIT_SCORE_ROBUST")
    out["mean_avg_pnl_wo_max"] = mean("AVG_PNL_PCT_WO_MAX")
    out["mean_outlier_pct"] = mean("OUTLIER_PCT_OF_WINS")
    out["mean_tpy"] = mean("AVG_TRADES_PER_YEAR")
    out["mean_max_win"] = mean("MAX_WIN_PCT")
    return out


def _book_avg_pnl_wo_max(closed: Path) -> float:
    if not closed.is_file():
        return 0.0
    pnls = []
    with closed.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        for row in csv.DictReader(f):
            pnls.append(_safe_num(row.get("PNL_PCT")))
    if len(pnls) < 2:
        return sum(pnls) / len(pnls) if pnls else 0.0
    mx = max(pnls)
    rest = [p for p in pnls if p != mx]
    if len(rest) == len(pnls):
        rest = pnls[:-1]
    return sum(rest) / len(rest) if rest else 0.0


def _recompute_ann_ror(closed: Path, brt_cash: float) -> float:
    if not closed.is_file() or brt_cash <= 0:
        return 0.0
    pnls: list[float] = []
    days: list[float] = []
    with closed.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        for row in csv.DictReader(f):
            pnls.append(_safe_num(row.get("PNL_DOLLARS")))
            days.append(_safe_num(row.get("DAYS_HELD")))
    n = len(pnls)
    if n < 1:
        return 0.0
    total = sum(pnls)
    avg_days = sum(days) / n if n else 0.0
    if avg_days <= 0:
        return 0.0
    denom = brt_cash * n
    if denom <= 0:
        return 0.0
    try:
        return ((1.0 + total / denom) ** (365.0 / avg_days) - 1.0) * 100.0
    except (OverflowError, ValueError, ZeroDivisionError):
        return 0.0


def _pf_from_closed(closed: Path) -> float:
    if not closed.is_file():
        return 0.0
    gw = 0.0
    gl = 0.0
    with closed.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        for row in csv.DictReader(f):
            p = _safe_num(row.get("PNL_DOLLARS"))
            if p >= 0:
                gw += p
            else:
                gl += abs(p)
    return (gw / gl) if gl > 1e-9 else (999.0 if gw > 0 else 0.0)


def extract_metrics(outdir: Path) -> Optional[dict[str, Any]]:
    report = _latest(outdir, "QULL_Audit_Report_*.csv") or _latest(outdir, "QULL_Report_*.csv")
    if report is None:
        return None
    stamp = ""
    m = re.search(r"_(\d{12})\.csv$", report.name)
    if m:
        stamp = m.group(1)

    row: dict[str, Any] = {}
    if "Audit_Report" in report.name:
        with report.open(newline="", encoding="utf-8-sig", errors="replace") as f:
            row = next(csv.DictReader(f), {}) or {}
    else:
        # key/value Report
        with report.open(newline="", encoding="utf-8-sig", errors="replace") as f:
            for r in csv.reader(f):
                if len(r) >= 2 and r[0] != "metric":
                    row[r[0]] = r[1]
        # normalize names
        row.setdefault("Total_Trades", row.get("trades"))
        row.setdefault("Wins", row.get("wins"))
        row.setdefault("Losses", row.get("losses"))
        row.setdefault("Pct_Wins", row.get("pct_wins"))
        row.setdefault("Total_PNL", row.get("total_pnl_dollars"))
        row.setdefault("Avg_PNL_Pct", row.get("avg_pnl_pct"))

    if not row:
        return None

    closed = outdir / f"QULL_Closed_{stamp}.csv" if stamp else _latest(outdir, "QULL_Closed_*.csv")
    summary = outdir / f"QULL_Summary_{stamp}.csv" if stamp else _latest(outdir, "QULL_Summary_*.csv")
    emeta = (
        outdir / f"QULL_EquityMeta_{stamp}.csv" if stamp else _latest(outdir, "QULL_EquityMeta_*.csv")
    )
    kv_report = outdir / f"QULL_Report_{stamp}.csv" if stamp else _latest(outdir, "QULL_Report_*.csv")

    mix = _exit_mix(closed) if closed else {}
    sag = _summary_aggs(summary) if summary else {}
    max_days_uw = 0.0
    pct_days_uw = 0.0
    if emeta and emeta.is_file():
        with emeta.open(newline="", encoding="utf-8-sig", errors="replace") as f:
            er = next(csv.DictReader(f), None) or {}
        max_days_uw = _safe_num(er.get("Max_Days_Underwater"))
        pct_days_uw = _safe_num(er.get("Pct_Days_Underwater"))

    trades = int(_safe_num(row.get("Total_Trades") or row.get("trades")))
    if trades <= 0 and closed and closed.is_file():
        with closed.open(newline="", encoding="utf-8-sig", errors="replace") as f:
            trades = sum(1 for _ in csv.DictReader(f))

    # Prefer Closed-sum / Report dollars for book PnL when Audit is 1M-scaled display
    report_pnl = 0.0
    if kv_report and kv_report.is_file():
        with kv_report.open(newline="", encoding="utf-8-sig", errors="replace") as f:
            for r in csv.reader(f):
                if len(r) >= 2 and r[0] == "total_pnl_dollars":
                    report_pnl = _safe_num(r[1])
    closed_pnl = 0.0
    avg_days = _safe_num(row.get("Avg_Days_Held"))
    median_days = _safe_num(row.get("Median_Days_Held"))
    p90_days = _safe_num(row.get("P90_Days"))
    if closed and closed.is_file():
        days = []
        with closed.open(newline="", encoding="utf-8-sig", errors="replace") as f:
            for r in csv.DictReader(f):
                closed_pnl += _safe_num(r.get("PNL_DOLLARS"))
                days.append(_safe_num(r.get("DAYS_HELD")))
        if days:
            days_sorted = sorted(days)
            if avg_days <= 0:
                avg_days = sum(days) / len(days)
            if median_days <= 0:
                median_days = days_sorted[len(days_sorted) // 2]
            if p90_days <= 0:
                p90_days = days_sorted[int(0.9 * (len(days_sorted) - 1))]

    pnl = report_pnl if abs(report_pnl) > 1e-9 else (
        closed_pnl if abs(closed_pnl) > 1e-9 else _safe_num(row.get("Total_PNL"))
    )
    sheet_pnl = _safe_num(row.get("sheet_PnL") or row.get("Sheet_PNL") or row.get("sheet_pnl"))
    if abs(sheet_pnl) < 1e-9:
        sheet_pnl = pnl

    brt_cash = _safe_num(row.get("brt_cash"))
    if brt_cash <= 0 and kv_report and kv_report.is_file():
        with kv_report.open(newline="", encoding="utf-8-sig", errors="replace") as f:
            for r in csv.reader(f):
                if len(r) >= 2 and r[0] == "brt_cash":
                    brt_cash = _safe_num(r[1])

    ann_ror = _safe_num(row.get("Ann_ROR"))
    if abs(ann_ror) < 1e-12 and closed:
        ann_ror = _recompute_ann_ror(closed, brt_cash if brt_cash > 0 else 35294.12)

    pf = _safe_num(row.get("Profit_Factor"))
    if abs(pf) < 1e-12 and closed:
        pf = _pf_from_closed(closed)

    n_target = int(mix.get("TARGET", 0))
    n_stop = (
        int(mix.get("STOP_LOSS", 0))
        + int(mix.get("GAP_DOWN", 0))
        + int(mix.get("STOP", 0))
    )
    n_trail = sum(v for k, v in mix.items() if str(k).startswith("TRAIL"))
    n_time = int(mix.get("TIME", 0))

    capital_days = _safe_num(row.get("Capital_Days"))
    if capital_days <= 0 and avg_days > 0 and trades:
        capital_days = avg_days * trades
    profit_per_cd = _safe_num(row.get("Profit_Per_Capital_Day"))
    if abs(profit_per_cd) < 1e-12 and capital_days > 0:
        profit_per_cd = pnl / capital_days

    return {
        "ok": True,
        "stamp": stamp,
        "report": report.name,
        "trades": trades,
        "wins": int(_safe_num(row.get("Wins"))),
        "losses": int(_safe_num(row.get("Losses"))),
        "wr": _safe_num(row.get("Pct_Wins")),
        "avg_pnl_pct": _safe_num(row.get("Avg_PNL_Pct")),
        "book_avg_pnl_wo_max": _book_avg_pnl_wo_max(closed) if closed else 0.0,
        "ann_ror": ann_ror,
        "avg_days": avg_days,
        "median_days": median_days,
        "p90_days": p90_days,
        "pnl": pnl,
        "sheet_pnl": sheet_pnl,
        "max_dd": _safe_num(row.get("Max_DD")),
        "pf": pf,
        "expectancy": _safe_num(row.get("Expectancy")),
        "expectancy_pct": _safe_num(row.get("Expectancy_Pct")),
        "avg_win_pct": _safe_num(row.get("Avg_Win_Pct")),
        "capital_days": capital_days,
        "profit_per_cd": profit_per_cd,
        "losing_streak": _safe_num(row.get("Losing_Streak")),
        "avg_pos": _safe_num(row.get("Avg_Positions")),
        "max_pos": _safe_num(row.get("Max_Positions")),
        "agg_pnl": _safe_num(row.get("Aggressive_Total_PNL")),
        "agg_dd": _safe_num(str(row.get("Aggressive_Max_DD", "")).replace("%", "")),
        "brt_cash": brt_cash,
        "pct_max_sym": _safe_num(row.get("Pct_PNL_Max_Symbol")),
        "pct_max_trade": _safe_num(row.get("Pct_PNL_Max_Trade")),
        "max_days_uw": max_days_uw,
        "pct_days_uw": pct_days_uw,
        "exit_target": n_target,
        "exit_stop": n_stop,
        "exit_trail": n_trail,
        "exit_time": n_time,
        "exit_target_pct": (100.0 * n_target / trades) if trades else 0.0,
        "exit_stop_pct": (100.0 * n_stop / trades) if trades else 0.0,
        "exit_trail_pct": (100.0 * n_trail / trades) if trades else 0.0,
        **sag,
    }


def copy_stamp_artifacts(src_dir: Path, dest: Path, stamp: str) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in src_dir.glob(f"QULL_*_{stamp}.*"):
        if p.is_file():
            shutil.copy2(p, dest / p.name)
            n += 1
    # Charts folder optional
    charts = src_dir / f"QULL_Charts_{stamp}"
    if charts.is_dir():
        dest_c = dest / charts.name
        if not dest_c.exists():
            try:
                shutil.copytree(charts, dest_c)
            except OSError:
                pass
    return n


def build_cmd(py: str, outdir: Path, workers: int, extras: list[str]) -> list[str]:
    """Full universe = omit -s (same as run_qull.bat ALL / *)."""
    vs = list(QULL_BASE_V)
    for ex in extras:
        key = ex.split("=", 1)[0]
        vs = [v for v in vs if not v.startswith(key + "=")]
        vs.append(ex)
    cmd = [
        py,
        str(SA / "rocket_tbn.py"),
        str(DATA_DIR),
        "-o",
        str(outdir),
        "-w",
        str(workers),
        "--no-regression",
        "--aggressive",
        "--initial-capital",
        "500000",
        "--aggressive-max-multiple",
        "2.0",
        "--margin-utilization",
        "0.6",
    ]
    for v in vs:
        cmd.extend(["-v", v])
    return cmd


def lean_decision(r: dict[str, Any], cm: dict[str, Any]) -> tuple[str, str]:
    """Lean thresholds scaled for QULL ~$15k Closed book (not SB $100k+)."""
    if r.get("skip"):
        return "dismiss", r.get("skip_reason") or "not applicable"
    if r.get("is_control"):
        return "hold", "baseline / keep production"
    m = r.get("metrics") or {}
    if not m or not cm:
        return "hold", "no metrics"
    d_pnl = float(m.get("pnl", 0)) - float(cm.get("pnl", 0))
    d_dd = float(m.get("max_dd", 0)) - float(cm.get("max_dd", 0))
    d_ror = float(m.get("ann_ror", 0)) - float(cm.get("ann_ror", 0))
    d_wr = float(m.get("wr", 0)) - float(cm.get("wr", 0))
    d_tr = int(m.get("trades", 0) or 0) - int(cm.get("trades", 0) or 0)
    d_fit_r = float(m.get("mean_fit_robust", 0)) - float(cm.get("mean_fit_robust", 0))
    d_pf = float(m.get("pf", 0)) - float(cm.get("pf", 0))
    if (
        abs(d_pnl) < 1.0
        and abs(d_ror) < 0.01
        and abs(d_dd) < 0.01
        and abs(d_wr) < 0.01
        and d_tr == 0
    ):
        return "noop", "Identical metrics vs control - no effect"
    if d_pnl < -8_000 and d_ror <= 0:
        return "dismiss", f"PnL {d_pnl:+.0f} / Ann_ROR {d_ror:+.2f} - worse"
    if d_pnl > 4_000 and d_dd <= 3.0 and (d_ror >= 0 or d_pf > 0.05):
        return (
            "adopt?",
            f"PnL {d_pnl:+.0f}, Ann_ROR {d_ror:+.2f}, DD {d_dd:+.2f}, "
            f"robustFIT {d_fit_r:+.2f} - candidate (PO/ToS; seed ToS still pending)",
        )
    if abs(d_pnl) < 2_000 and abs(d_ror) < 1.0 and abs(d_dd) < 2.0:
        return "hold", f"flat vs control (PnL {d_pnl:+.0f}, ROR {d_ror:+.2f}, DD {d_dd:+.2f})"
    if d_pnl > 0 and d_dd > 3.0:
        return "hold", f"PnL up {d_pnl:+.0f} but DD up {d_dd:+.2f} - tradeoff"
    if d_pnl < 0 and d_dd < -1.0 and d_wr > 1:
        return "hold", f"PnL down {d_pnl:+.0f}; quality mix (WR {d_wr:+.1f}, DD {d_dd:+.2f})"
    if d_pnl < -3_000:
        return "dismiss", f"PnL {d_pnl:+.0f} vs control"
    return "hold", f"mixed (PnL {d_pnl:+.0f}, ROR {d_ror:+.2f}, DD {d_dd:+.2f}, WR {d_wr:+.1f})"


def run_arm(
    *,
    py: str,
    arm: Arm,
    out_root: Path,
    drive_out: Path,
    workers: int,
    reuse_control_stamp: str = "",
    reuse_arm_stamp: str = "",
) -> dict[str, Any]:
    arm_dir = out_root / arm.arm_id
    arm_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "arm": arm.arm_id,
        "hypothesis_id": arm.hypothesis_id,
        "family": arm.family,
        "suggestion": arm.suggestion,
        "extras": " ".join(arm.extras) if arm.extras else "(none)",
        "skip": arm.skip,
        "skip_reason": arm.skip_reason,
        "is_control": arm.is_control,
    }
    if arm.skip:
        result["ok"] = False
        result["note"] = arm.skip_reason
        lean, why = lean_decision(result, {})
        result["lean"] = lean
        result["lean_why"] = why
        return result

    reuse = reuse_control_stamp if arm.is_control else reuse_arm_stamp
    if reuse:
        n = copy_stamp_artifacts(DRIVE, arm_dir, reuse)
        metrics = extract_metrics(arm_dir) or (
            extract_metrics(DRIVE) if arm.is_control else None
        )
        result["ok"] = bool(metrics)
        result["metrics"] = metrics or {}
        result["stamp"] = reuse
        result["elapsed_s"] = 0.0
        result["note"] = f"reused drive stamp {reuse} ({n} files)"
        (arm_dir / "STAMP.txt").write_text(
            f"stamp={reuse}\narm={arm.arm_id}\nextra=(reuse)\n",
            encoding="utf-8",
        )
        return result

    existing = arm_dir / "STAMP.txt"
    if existing.is_file() and not os.environ.get("QULL_HINT_FORCE_RERUN"):
        prev = ""
        for line in existing.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("stamp="):
                prev = line.split("=", 1)[1].strip()
        if prev and (arm_dir / f"QULL_Report_{prev}.csv").is_file():
            metrics = extract_metrics(arm_dir)
            if metrics:
                result["ok"] = True
                result["metrics"] = metrics
                result["stamp"] = prev
                result["elapsed_s"] = 0.0
                result["note"] = f"reused existing arm stamp {prev}"
                return result

    cmd = build_cmd(py, drive_out, workers, arm.extras)
    log_path = arm_dir / "run.log"
    t0 = time.time()
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write("CMD: " + " ".join(cmd) + "\n\n")
        log.flush()
        proc = subprocess.run(cmd, cwd=str(REPO), stdout=log, stderr=subprocess.STDOUT)
    elapsed = time.time() - t0
    stamp = ""
    ts_file = DRIVE / "QULL_last_run_ts.txt"
    if ts_file.is_file():
        stamp = ts_file.read_text(encoding="utf-8", errors="replace").strip().splitlines()[0].strip()
    if stamp:
        copy_stamp_artifacts(DRIVE, arm_dir, stamp)
        (arm_dir / "STAMP.txt").write_text(
            f"stamp={stamp}\narm={arm.arm_id}\nextra={' '.join(arm.extras)}\n",
            encoding="utf-8",
        )
    metrics = extract_metrics(arm_dir) if stamp else None
    result["ok"] = proc.returncode == 0 and bool(metrics)
    result["metrics"] = metrics or {}
    result["stamp"] = stamp
    result["elapsed_s"] = elapsed
    result["note"] = f"rc={proc.returncode}"
    if proc.returncode != 0:
        result["note"] += f" (see {log_path.name})"
    return result


def analyze_sma50_control(closed: Path, data_dir: Path, slope_bars: int = 10) -> dict[str, Any]:
    """Empirical SMA50 vs win/loss on control Closed (chart hypothesis check)."""
    import numpy as np
    import pandas as pd

    out: dict[str, Any] = {
        "n": 0,
        "below_n": 0,
        "below_wr": 0.0,
        "below_avg": 0.0,
        "above_flat_n": 0,
        "above_flat_wr": 0.0,
        "above_flat_avg": 0.0,
        "above_up_n": 0,
        "above_up_wr": 0.0,
        "above_up_avg": 0.0,
        "note": "",
    }
    if not closed.is_file():
        out["note"] = "no closed"
        return out
    rows = list(csv.DictReader(closed.open(encoding="utf-8-sig", errors="replace")))
    cache: dict[str, pd.DataFrame] = {}

    def load(sym: str) -> Optional[pd.DataFrame]:
        if sym in cache:
            return cache[sym]
        p = data_dir / f"{sym}.csv"
        if not p.is_file():
            cache[sym] = None  # type: ignore
            return None
        df = pd.read_csv(p, parse_dates=True, index_col=0).sort_index()
        c = df["Close"].astype(float)
        df = df.copy()
        df["_sma50"] = c.rolling(50, min_periods=50).mean()
        cache[sym] = df
        return df

    buckets = {
        "below": [],
        "above_flat": [],
        "above_up": [],
    }
    for r in rows:
        sym = (r.get("SYMBOL") or "").strip().upper()
        entry = _safe_num(r.get("ENTRY_PRICE"))
        pnl = _safe_num(r.get("PNL_PCT"))
        opened = (r.get("DATE_OPENED") or "").strip().replace("-", "")
        if len(opened) >= 8:
            opened = f"{opened[:4]}-{opened[4:6]}-{opened[6:8]}"
        df = load(sym)
        if df is None or entry <= 0 or not opened:
            continue
        try:
            # match open date
            idx = df.index
            hit = None
            for d in idx:
                if str(d)[:10] == opened[:10]:
                    hit = d
                    break
            if hit is None:
                continue
            i = list(idx).index(hit)
            sma = float(df["_sma50"].iloc[i])
            if not np.isfinite(sma) or sma <= 0:
                continue
            j = i - slope_bars
            rising = False
            if j >= 0:
                s0 = float(df["_sma50"].iloc[j])
                rising = np.isfinite(s0) and s0 > 0 and sma > s0
            if entry < sma:
                buckets["below"].append(pnl)
            elif rising:
                buckets["above_up"].append(pnl)
            else:
                buckets["above_flat"].append(pnl)
        except Exception:
            continue

    def pack(key: str, dest_prefix: str) -> None:
        xs = buckets[key]
        out["n"] += len(xs)
        out[f"{dest_prefix}_n"] = len(xs)
        if xs:
            wins = sum(1 for x in xs if x > 0)
            out[f"{dest_prefix}_wr"] = 100.0 * wins / len(xs)
            out[f"{dest_prefix}_avg"] = sum(xs) / len(xs)

    pack("below", "below")
    pack("above_flat", "above_flat")
    pack("above_up", "above_up")
    out["note"] = (
        f"Entry vs SMA50@{slope_bars}d: below n={out['below_n']} WR={out['below_wr']:.1f}% "
        f"avg={out['below_avg']:.2f}%; above+flat/down n={out['above_flat_n']} "
        f"WR={out['above_flat_wr']:.1f}% avg={out['above_flat_avg']:.2f}%; "
        f"above+rising n={out['above_up_n']} WR={out['above_up_wr']:.1f}% "
        f"avg={out['above_up_avg']:.2f}%"
    )
    return out


def write_comparison(
    out_root: Path,
    rows: list[dict[str, Any]],
    stamp_src: str,
    sma50_note: str = "",
) -> Path:
    cm = {}
    for r in rows:
        if r.get("is_control"):
            cm = r.get("metrics") or {}
            break
    for r in rows:
        lean, why = lean_decision(r, cm)
        r["lean"] = lean
        r["lean_why"] = why

    csv_path = out_root / "comparison.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "arm",
                "family",
                "hypothesis_id",
                "extras",
                "stamp",
                "trades",
                "wr",
                "avg_pnl_pct",
                "book_avg_pnl_wo_max",
                "ann_ror",
                "avg_days",
                "pnl",
                "sheet_pnl",
                "max_dd",
                "pf",
                "capital_days",
                "profit_per_cd",
                "mean_fit_robust",
                "mean_paul",
                "exit_stop_pct",
                "exit_trail_pct",
                "d_pnl",
                "d_ann_ror",
                "d_max_dd",
                "lean",
                "lean_why",
                "suggestion",
                "skip",
                "skip_reason",
            ],
        )
        w.writeheader()
        for r in rows:
            m = r.get("metrics") or {}
            w.writerow(
                {
                    "arm": r["arm"],
                    "family": r.get("family"),
                    "hypothesis_id": r.get("hypothesis_id"),
                    "extras": r.get("extras"),
                    "stamp": r.get("stamp", m.get("stamp", "")),
                    "trades": m.get("trades"),
                    "wr": m.get("wr"),
                    "avg_pnl_pct": m.get("avg_pnl_pct"),
                    "book_avg_pnl_wo_max": m.get("book_avg_pnl_wo_max"),
                    "ann_ror": m.get("ann_ror"),
                    "avg_days": m.get("avg_days"),
                    "pnl": m.get("pnl"),
                    "sheet_pnl": m.get("sheet_pnl"),
                    "max_dd": m.get("max_dd"),
                    "pf": m.get("pf"),
                    "capital_days": m.get("capital_days"),
                    "profit_per_cd": m.get("profit_per_cd"),
                    "mean_fit_robust": m.get("mean_fit_robust"),
                    "mean_paul": m.get("mean_paul"),
                    "exit_stop_pct": m.get("exit_stop_pct"),
                    "exit_trail_pct": m.get("exit_trail_pct"),
                    "d_pnl": (float(m.get("pnl", 0)) - float(cm.get("pnl", 0))) if cm and not r.get("skip") else "",
                    "d_ann_ror": (float(m.get("ann_ror", 0)) - float(cm.get("ann_ror", 0))) if cm and not r.get("skip") else "",
                    "d_max_dd": (float(m.get("max_dd", 0)) - float(cm.get("max_dd", 0))) if cm and not r.get("skip") else "",
                    "lean": r.get("lean"),
                    "lean_why": r.get("lean_why"),
                    "suggestion": r.get("suggestion"),
                    "skip": r.get("skip"),
                    "skip_reason": r.get("skip_reason"),
                }
            )

    def fmt(v: Any, nd: int = 2) -> str:
        if v is None or v == "":
            return "—"
        try:
            return f"{float(v):,.{nd}f}"
        except (TypeError, ValueError):
            return str(v)

    def fmt_i(v: Any) -> str:
        if v is None or v == "":
            return "—"
        try:
            return f"{int(float(v))}"
        except (TypeError, ValueError):
            return str(v)

    ths = "".join(
        [
            sortable_th("Arm", "text"),
            sortable_th("Family", "text"),
            sortable_th("Knob", "text"),
            sortable_th("Stamp", "text"),
            sortable_th("Trades", "num"),
            sortable_th("WR%", "num"),
            sortable_th("Avg%", "num"),
            sortable_th("WO_MAX%", "num"),
            sortable_th("Ann_ROR", "num"),
            sortable_th("AvgDays", "num"),
            sortable_th("Total_PNL", "num"),
            sortable_th("Sheet_PNL", "num"),
            sortable_th("Max_DD", "num"),
            sortable_th("PF", "num"),
            sortable_th("CapDays", "num"),
            sortable_th("$/CapDay", "num"),
            sortable_th("MeanFIT_R", "num"),
            sortable_th("STOP%", "num"),
            sortable_th("TRAIL%", "num"),
            sortable_th("Δ PnL", "num"),
            sortable_th("Δ ROR", "num"),
            sortable_th("Δ DD", "num"),
            sortable_th("Lean", "text"),
            sortable_th("Why", "text"),
        ]
    )
    body_rows = []
    for r in rows:
        m = r.get("metrics") or {}
        cls = "total-row" if r.get("is_control") else ""
        if r.get("skip"):
            body_rows.append(
                f"<tr class='{cls}'><td>{html.escape(r['arm'])}</td>"
                f"<td>{html.escape(str(r.get('family','')))}</td>"
                f"<td colspan='20'>{html.escape(r.get('skip_reason') or 'skipped')}</td>"
                f"<td>{html.escape(str(r.get('lean','')))}</td>"
                f"<td>{html.escape(str(r.get('lean_why','')))}</td></tr>"
            )
            continue
        d_pnl = float(m.get("pnl", 0)) - float(cm.get("pnl", 0)) if cm else 0.0
        d_ror = float(m.get("ann_ror", 0)) - float(cm.get("ann_ror", 0)) if cm else 0.0
        d_dd = float(m.get("max_dd", 0)) - float(cm.get("max_dd", 0)) if cm else 0.0
        lean = str(r.get("lean", ""))
        lean_cls = ""
        if lean.startswith("adopt"):
            lean_cls = " style='background:#dcfce7'"
        elif lean == "dismiss":
            lean_cls = " style='background:#fee2e2'"
        elif lean == "noop":
            lean_cls = " style='background:#e2e8f0'"
        elif lean == "hold":
            lean_cls = " style='background:#fef9c3'"
        body_rows.append(
            f"<tr class='{cls}'>"
            f"<td>{html.escape(r['arm'])}</td>"
            f"<td>{html.escape(str(r.get('family','')))}</td>"
            f"<td><code>{html.escape(str(r.get('extras','')))}</code></td>"
            f"<td>{html.escape(str(r.get('stamp', m.get('stamp',''))))}</td>"
            f"<td>{fmt_i(m.get('trades'))}</td>"
            f"<td>{fmt(m.get('wr'), 2)}</td>"
            f"<td>{fmt(m.get('avg_pnl_pct'), 2)}</td>"
            f"<td>{fmt(m.get('book_avg_pnl_wo_max'), 2)}</td>"
            f"<td>{fmt(m.get('ann_ror'), 2)}</td>"
            f"<td>{fmt(m.get('avg_days'), 1)}</td>"
            f"<td>{format_money(m.get('pnl'))}</td>"
            f"<td>{format_money(m.get('sheet_pnl'))}</td>"
            f"<td>{fmt(m.get('max_dd'), 2)}</td>"
            f"<td>{fmt(m.get('pf'), 2)}</td>"
            f"<td>{fmt(m.get('capital_days'), 0)}</td>"
            f"<td>{format_money(m.get('profit_per_cd'))}</td>"
            f"<td>{fmt(m.get('mean_fit_robust'), 2)}</td>"
            f"<td>{fmt(m.get('exit_stop_pct'), 1)}</td>"
            f"<td>{fmt(m.get('exit_trail_pct'), 1)}</td>"
            f"<td>{format_money_delta(d_pnl)}</td>"
            f"<td>{fmt(d_ror, 2)}</td>"
            f"<td>{fmt(d_dd, 2)}</td>"
            f"<td{lean_cls}><strong>{html.escape(lean)}</strong></td>"
            f"<td>{html.escape(str(r.get('lean_why','')))}</td>"
            f"</tr>"
        )

    canon_rows = []
    metric_specs = [
        ("Total trades", "trades", "num", False),
        ("Win %", "wr", "pct", False),
        ("Total PnL $", "pnl", "money", False),
        ("Sheet PnL $", "sheet_pnl", "money", False),
        ("Avg PnL %", "avg_pnl_pct", "pct", False),
        ("Book AVG_PNL_PCT_WO_MAX", "book_avg_pnl_wo_max", "pct", False),
        ("Profit factor", "pf", "num", False),
        ("Ann ROR %", "ann_ror", "pct", False),
        ("Max DD %", "max_dd", "pct", True),
        ("Profit per capital day", "profit_per_cd", "money", False),
        ("Capital days", "capital_days", "num", True),
        ("Avg days held", "avg_days", "num", True),
        ("Median days held", "median_days", "num", True),
        ("P90 days held", "p90_days", "num", True),
        ("Losing streak", "losing_streak", "num", True),
        ("Max positions", "max_pos", "num", False),
        ("Aggressive Total PnL $", "agg_pnl", "money", False),
        ("Aggressive Max DD %", "agg_dd", "pct", True),
        ("Mean Paul Score", "mean_paul", "num", False),
        ("Mean FIT Score", "mean_fit", "num", False),
        ("Mean FIT Score Robust", "mean_fit_robust", "num", False),
        ("Mean AVG_PNL_PCT_WO_MAX", "mean_avg_pnl_wo_max", "pct", False),
        ("Mean OUTLIER_PCT_OF_WINS", "mean_outlier_pct", "pct", True),
        ("Mean AVG_TRADES_PER_YEAR", "mean_tpy", "num", False),
        ("EXIT STOP %", "exit_stop_pct", "pct", True),
        ("EXIT TRAIL %", "exit_trail_pct", "pct", False),
        ("EXIT TIME count", "exit_time", "num", False),
    ]
    runnable = [r for r in rows if not r.get("skip")]
    arm_ids = [r["arm"] for r in runnable]
    canon_th = sortable_th("Metric", "text") + "".join(
        sortable_th(a, "num") for a in arm_ids
    ) + sortable_th("Δ best vs ctrl", "text")
    for label, key, kind, lower_better in metric_specs:
        cells = [f"<td>{html.escape(label)}</td>"]
        cval = float(cm.get(key, 0) or 0) if cm else 0.0
        best_note = "—"
        for r in runnable:
            m = r.get("metrics") or {}
            v = float(m.get(key, 0) or 0)
            if kind == "money":
                cells.append(f"<td>{format_money(v)}</td>")
            elif kind == "pct":
                cells.append(f"<td>{fmt(v, 2)}</td>")
            else:
                cells.append(f"<td>{fmt(v, 2 if abs(v) < 1000 else 0)}</td>")
            if not r.get("is_control") and cm:
                d = v - cval
                if abs(d) > 1e-9:
                    better = (d < 0) if lower_better else (d > 0)
                    if better and best_note == "—":
                        if kind == "money":
                            best_note = f"{r['arm']}: {format_money_delta(d)}"
                        else:
                            best_note = f"{r['arm']}: {d:+.2f}"
        cells.append(f"<td>{html.escape(best_note)}</td>")
        canon_rows.append("<tr>" + "".join(cells) + "</tr>")

    hyp_rows = []
    for r in rows:
        hyp_rows.append(
            "<tr>"
            f"<td>{html.escape(r['arm'])}</td>"
            f"<td><code>{html.escape(str(r.get('hypothesis_id','')))}</code></td>"
            f"<td>{html.escape(str(r.get('suggestion','')))}</td>"
            f"<td><strong>{html.escape(str(r.get('lean','')))}</strong></td>"
            "</tr>"
        )

    # Recommendation: prefer SMA tighten quality over loosen volume unless quality holds
    adopt = [r for r in rows if str(r.get("lean", "")).startswith("adopt")]
    loosen = [
        r
        for r in rows
        if str(r.get("arm", "")).startswith(("11_", "12_", "13_", "14_", "15_", "16_", "17_", "18_"))
        and not r.get("skip")
    ]
    sma_new = [
        r
        for r in rows
        if str(r.get("arm", "")).startswith(("19_", "20_")) and not r.get("skip")
    ]
    loosen_up = []
    for r in loosen:
        m = r.get("metrics") or {}
        if cm and int(m.get("trades", 0) or 0) > int(cm.get("trades", 0) or 0):
            d_tr = int(m.get("trades", 0) or 0) - int(cm.get("trades", 0) or 0)
            d_pnl = float(m.get("pnl", 0) or 0) - float(cm.get("pnl", 0) or 0)
            loosen_up.append(
                f"{r['arm']} (+{d_tr} trades, PnL {d_pnl:+.0f}, lean={r.get('lean')})"
            )
    sma_bits = []
    for r in sma_new:
        m = r.get("metrics") or {}
        if cm:
            d_tr = int(m.get("trades", 0) or 0) - int(cm.get("trades", 0) or 0)
            d_pnl = float(m.get("pnl", 0) or 0) - float(cm.get("pnl", 0) or 0)
            sma_bits.append(
                f"{r['arm']} ({d_tr:+d} trades, PnL {d_pnl:+.0f}, lean={r.get('lean')})"
            )
    if adopt:
        rec = (
            f"Best candidate(s): {', '.join(a['arm'] for a in adopt)}. "
            "Do <strong>not</strong> adopt yet — seed Thinkorswim (ToS) still pending; "
            "need trade-diff + ToS before PO sign-off."
        )
    else:
        rec = (
            "<strong>Keep production</strong> (stamp 260810110101 knobs). "
            "No arm cleared automated adopt? triage. Seed ToS still needed before any adopt."
        )
    if loosen_up:
        rec += (
            "<br/><br/><strong>Loosen trade-count check:</strong> "
            + "; ".join(loosen_up)
            + ". Prefer only if quality (PnL / Ann_ROR / Max DD / PF) holds vs control."
        )
    else:
        rec += (
            "<br/><br/><strong>Loosen trade-count check:</strong> "
            "no new loosen arm raised trades vs control (or metrics missing)."
        )
    if sma_bits:
        rec += (
            "<br/><br/><strong>SMA10/20 tighten:</strong> "
            + "; ".join(sma_bits)
            + ". Compare to prior SMA50 arms (08–10) for quality vs count."
        )

    html_doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>QULL ImprovePriority A/B — 260810110101</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:1.5rem;color:#0f172a;background:#f8fafc}}
h1{{font-size:1.4rem;margin:0 0 .4rem}}
h2{{font-size:1.15rem;margin:1.4rem 0 .5rem}}
.muted{{color:#64748b;font-size:.92rem}}
table.sortable{{border-collapse:collapse;width:100%;background:#fff;margin:1rem 0;font-size:.85rem}}
th,td{{border:1px solid #e2e8f0;padding:.35rem .5rem;text-align:left;vertical-align:top}}
th{{background:#f1f5f9}}
tr.total-row{{background:#eff6ff;font-weight:600}}
code{{font-size:.8rem}}
{SORTABLE_TH_CSS}
</style></head><body>
<h1>QULL ImprovePriority A/B — stamp {html.escape(stamp_src)}</h1>
<p class="muted">Control = production <code>run_qull.bat</code> (HTF prior=0.50 coil=10/0.15
trail=10 vol_bo=1.5 market_filter ON cooldown=5). Universe: <strong>full</strong>
(omit <code>-s</code>, same as control 234 symbols / 301 trades).
One knob / coherent skip per arm (<code>docs/HYPOTHESIS_TEST.md</code>).
Click column headers to sort. Dollar fields use <code>$nnn,nnn.nn</code>.</p>
<p class="muted">Output: <code>drive/paul_experiments/tbn_new_systems/qull_ep_htf/ab_improve_prio_260810/</code>
· Canonical metrics: <code>CANONICAL_COMPARE_METRICS.md</code>.
· Seed Thinkorswim (ToS) still <strong>pending</strong> before any adopt.
Arms 00–10 = original ImprovePriority + SMA50; arms 11–18 = loosen levers (expect ↑ trades);
arms 19–20 = SMA20 / SMA10 tighten.</p>
<p class="muted">Lean: <strong>adopt?</strong> = candidate (PO/ToS; do not ship) ·
<strong>hold</strong> = mixed/tradeoff · <strong>dismiss</strong> = regression or N/A ·
<strong>noop</strong> = no book effect.</p>

<h2>SMA knob definitions</h2>
<ul class="muted">
<li><code>qull_require_above_sma50</code> / <code>sma20</code> / <code>sma10</code> — signal close ≥ SMAn
<em>and</em> fill/entry price ≥ SMAn on fill bar.</li>
<li><code>qull_require_sma50_rising</code> — SMA50[signal] &gt; SMA50[signal − N] with
<code>qull_sma50_slope_bars=N</code> (default 10). Strict: flat or down fails.</li>
<li>Combined SMA50 arm turns both SMA50 gates ON.</li>
</ul>
<p class="muted"><strong>Control Closed empirical (SMA50):</strong> {html.escape(sma50_note or 'n/a')}</p>

<h2>Loosen levers (expected ↑ trades)</h2>
<ul class="muted">
<li><code>qull_prior_run_pct</code> 0.50→0.40 / 0.30 — easier prior-run threshold</li>
<li><code>qull_coil_range_pct</code> 0.15→0.20 / 0.25 — wider coil allowed</li>
<li><code>qull_coil_bars</code> 10→7 — shorter coil window</li>
<li><code>qull_vol_breakout_mult</code> 1.5→1.2 — weaker breakout volume OK</li>
<li><code>qull_market_filter=false</code> — drop SPY SMA10&gt;SMA20 gate</li>
<li><code>qull_require_ema_surf=false</code> — drop EMA10 surf proximity gate</li>
</ul>

<h2>Results vs control</h2>
<table class="sortable"><thead><tr>{ths}</tr></thead>
<tbody>
{''.join(body_rows)}
</tbody></table>

<h2>Canonical metrics (absolute + deltas)</h2>
<p class="muted">Full book / Summary / exit mix per
<code>drive/paul_experiments/CANONICAL_COMPARE_METRICS.md</code>. Do not judge primarily on max single-trade PnL.</p>
<table class="sortable"><thead><tr>{canon_th}</tr></thead>
<tbody>
{''.join(canon_rows)}
</tbody></table>

<h2>Hypotheses (ImprovePriority + chart)</h2>
<table class="sortable"><thead><tr>
{sortable_th('Arm','text')}{sortable_th('Hypothesis','text')}{sortable_th('Suggestion','text')}{sortable_th('Lean','text')}
</tr></thead><tbody>
{''.join(hyp_rows)}
</tbody></table>

<h2>Recommendation</h2>
<p>{rec}</p>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    html_path = out_root / "comparison.html"
    html_path.write_text(html_doc, encoding="utf-8")

    md = [
        "# QULL ImprovePriority A/B — 260810110101",
        "",
        f"Control stamp `{stamp_src}` (production QULL HTF). Full universe.",
        "",
        "## SMA defs",
        "",
        "- `qull_require_above_sma50` / `sma20` / `sma10`: signal close ≥ SMAn and fill ≥ SMAn",
        "- `qull_require_sma50_rising`: SMA50[i] > SMA50[i-10] (strict)",
        "",
        f"Empirical: {sma50_note}",
        "",
        "## Loosen levers (expect ↑ trades)",
        "",
        "- prior_run 0.40 / 0.30; coil_range 0.20 / 0.25; coil_bars 7;",
        "- vol_bo 1.2; market_filter off; ema_surf off",
        "",
        "| Arm | Knob | Trades | WR% | Avg% | Ann_ROR | Total_PNL | Max_DD | PF | Lean | Why |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for r in rows:
        m = r.get("metrics") or {}
        if r.get("skip"):
            md.append(
                f"| `{r['arm']}` | skip | — | — | — | — | — | — | — | "
                f"**{r.get('lean')}** | {r.get('lean_why')} |"
            )
            continue
        md.append(
            f"| `{r['arm']}` | `{r.get('extras')}` | {fmt_i(m.get('trades'))} | {fmt(m.get('wr'))} | "
            f"{fmt(m.get('avg_pnl_pct'))} | {fmt(m.get('ann_ror'))} | {format_money(m.get('pnl'))} | "
            f"{fmt(m.get('max_dd'))} | {fmt(m.get('pf'))} | **{r.get('lean')}** | {r.get('lean_why')} |"
        )
    md.extend(
        [
            "",
            "## Recommendation",
            "",
            "- Default: **keep production** unless an arm is `adopt?` with trade-diff + ToS.",
            "- Seed Thinkorswim (ToS) still needed before any adopt.",
            "",
        ]
    )
    (out_root / "comparison.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    (out_root / "README.md").write_text(
        "\n".join(
            [
                "# QULL ImprovePriority A/B (260810110101)",
                "",
                "Hypothesis tests from `QULL_ImprovePriority_260810110101.html` + chart SMA50 arms.",
                "",
                "- Driver: `tools/qull_hint_ab.py`",
                "- Bat: `run_qull_hint_ab.bat`",
                "- Control: production `run_qull.bat` knobs; reuse stamp when possible",
                "- Reports: `comparison.html` / `.csv` / `.md`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"[qull_hint_ab] wrote {csv_path}")
    print(f"[qull_hint_ab] wrote {html_path}")
    return html_path


def patch_improve_priority(
    stamp: str,
    out_root: Path,
    rows: list[dict[str, Any]],
) -> Optional[Path]:
    prio = DRIVE / f"QULL_ImprovePriority_{stamp}.html"
    if not prio.is_file():
        return None
    text = prio.read_text(encoding="utf-8", errors="replace")
    text = re.sub(
        r'<div class="ab-strip".*?</div>\s*',
        "",
        text,
        count=1,
        flags=re.DOTALL,
    )
    rel = os.path.relpath(out_root / "comparison.html", DRIVE).replace("\\", "/")
    bat = f"run_qull_hint_ab.bat {stamp}"
    lean_rows = []
    for r in rows:
        if r.get("is_control"):
            continue
        lean_rows.append(
            "<tr>"
            f"<td>{html.escape(r['arm'])}</td>"
            f"<td><code>{html.escape(str(r.get('hypothesis_id','')))}</code></td>"
            f"<td><code>{html.escape(str(r.get('extras','')))}</code></td>"
            f"<td><strong>{html.escape(str(r.get('lean','')))}</strong></td>"
            f"<td>{html.escape(str(r.get('lean_why',''))[:220])}</td>"
            "</tr>"
        )
    block = f"""
  <div class="ab-strip" style="background:#eef3f8;border:1px solid #c5d0dc;padding:12px 14px;margin:12px 0 8px;border-radius:4px;">
    <strong>ImprovePriority A/B (hypothesis test)</strong>
    <span class="muted"> — one knob / skip per arm vs QULL production {html.escape(stamp)}.
    Results: <a href="{html.escape(rel)}">comparison.html</a>
    · re-run <code>{html.escape(bat)}</code></span>
    <p class="muted" style="margin:.4rem 0 0">Default: <strong>keep production</strong>.
    Seed Thinkorswim (ToS) still pending — do not adopt without PO + ToS.</p>
    <table class="sortable" style="margin-top:8px"><thead><tr>
      <th class="sortable-th" data-sort="text" tabindex="0" role="columnheader" aria-sort="none">Arm<span class="sort-ind"></span></th>
      <th class="sortable-th" data-sort="text" tabindex="0" role="columnheader" aria-sort="none">Hypothesis<span class="sort-ind"></span></th>
      <th class="sortable-th" data-sort="text" tabindex="0" role="columnheader" aria-sort="none">Knob<span class="sort-ind"></span></th>
      <th class="sortable-th" data-sort="text" tabindex="0" role="columnheader" aria-sort="none">Lean<span class="sort-ind"></span></th>
      <th class="sortable-th" data-sort="text" tabindex="0" role="columnheader" aria-sort="none">Why<span class="sort-ind"></span></th>
    </tr></thead><tbody>
{''.join(lean_rows)}
    </tbody></table>
  </div>
"""
    if "<body>" in text:
        text = text.replace("<body>", "<body>\n" + block, 1)
    else:
        text = block + text
    prio.write_text(text, encoding="utf-8")
    print(f"[qull_hint_ab] patched {prio.name}")
    return prio


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stamp", default="", help="ImprovePriority / control stamp")
    ap.add_argument("--reuse-control", default="", help="Reuse drive QULL stamp for 00_control")
    ap.add_argument("--workers", type=int, default=int(os.environ.get("QULL_WORKERS", "12")))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--smoke", action="store_true", help="control + skips only")
    ap.add_argument("--skip-priority", action="store_true")
    args = ap.parse_args()

    stamp = (args.stamp or args.reuse_control or DEFAULT_CONTROL).strip()
    reuse = (args.reuse_control or stamp).strip()
    out_root = Path(args.out)
    if not out_root.is_absolute():
        out_root = REPO / out_root
    out_root.mkdir(parents=True, exist_ok=True)
    py = _resolve_python()

    arms = build_arms()
    if args.smoke:
        arms = [a for a in arms if a.is_control or a.skip]

    print(f"[qull_hint_ab] control_stamp={reuse} workers={args.workers}")
    print(f"[qull_hint_ab] universe=FULL (omit -s) out={out_root}")
    if args.dry_run:
        for a in arms:
            print(
                f"  {a.arm_id}: "
                f"{'SKIP '+a.skip_reason if a.skip else ' '.join(a.extras) or '(control)'}"
            )
        return 0

    # SMA50 empirical on control Closed (before / parallel with runs)
    sma50_note = ""
    ctrl_closed = DRIVE / f"QULL_Closed_{reuse}.csv"
    if ctrl_closed.is_file():
        try:
            sma = analyze_sma50_control(ctrl_closed, DATA_DIR, slope_bars=10)
            sma50_note = sma.get("note") or ""
            print(f"[qull_hint_ab] SMA50 empirical: {sma50_note}")
            (out_root / "sma50_empirical.json").write_text(
                __import__("json").dumps(sma, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            sma50_note = f"empirical failed: {e}"
            print(f"[qull_hint_ab] SMA50 empirical failed: {e}")

    results: list[dict[str, Any]] = []
    for i, arm in enumerate(arms, 1):
        print(f"\n========== [{i}/{len(arms)}] {arm.arm_id} ==========")
        r = run_arm(
            py=py,
            arm=arm,
            out_root=out_root,
            drive_out=DRIVE,
            workers=args.workers,
            reuse_control_stamp=reuse if arm.is_control else "",
        )
        results.append(r)
        m = r.get("metrics") or {}
        if r.get("skip"):
            print(f"  SKIP: {str(r.get('skip_reason'))[:120]}")
        else:
            print(
                f"  stamp={r.get('stamp')} trades={m.get('trades')} "
                f"PNL={m.get('pnl')} DD={m.get('max_dd')} "
                f"elapsed={r.get('elapsed_s', 0):.0f}s ok={r.get('ok')} note={r.get('note')}"
            )

    write_comparison(out_root, results, stamp_src=reuse, sma50_note=sma50_note)
    if not args.skip_priority:
        patch_improve_priority(stamp, out_root, results)

    fails = sum(
        1
        for r in results
        if not r.get("skip") and not r.get("ok") and not r.get("is_control")
    )
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
