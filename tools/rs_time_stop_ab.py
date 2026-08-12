#!/usr/bin/env python3
"""RS one-knob time_stop A/B vs production gold freeze.

Control (matches run_rs.bat / rs_baseline_260807141317 levers):
  stop_pct=0.85, target_pct=1.25, time_stop_days=252, cd=60,
  rs_spy_int_tc_not_weak=true, universe=drive/universes/RS_universe.csv (64).

Arms change **only** time_stop_days. Research-only — does not mutate gold freeze.

IS/OOS: entry DATE_OPENED < 2024-01-01 vs >= 2024-01-01 (OOS report-only).

Usage (repo root)::

  python tools/rs_time_stop_ab.py
  python tools/rs_time_stop_ab.py --grid 60,120,252
  python tools/rs_time_stop_ab.py --skip-existing
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
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))
from compare_format import (  # noqa: E402
    ann_ror_from_closed,
    format_money,
    format_money_delta,
)

SA = REPO / "stock_analysis"
DATA_DIR = REPO / "data" / "newdata" / "data"
DRIVE = REPO / "drive"
OOS_SPLIT = "20240101"  # DATE_OPENED YYYYMMDD
STOP_MULT = 0.85
TARGET_MULT = 1.25
RISK_PCT = (1.0 - STOP_MULT) * 100.0  # 15.0 — AvgR = PNL_PCT / RISK_PCT
DEFAULT_GRID = (20, 40, 60, 63, 90, 120, 180, 252)
CONTROL_TIME = 252
FREEZE_REF = "260807141317"

RS_BASE_V = [
    "rs_mode=true",
    "brt_zones=false",
    "yh_zones=false",
    "wpbr_zones=false",
    "rl_mode=false",
    f"target_pct={TARGET_MULT}",
    f"stop_pct={STOP_MULT}",
    "stop_pct_is_multiplier=true",
    "use_indicators=true",
    "indicator_buy=off",
    "rs_require_tc_strong=true",
    "growth_filter_enabled=false",
    "min_spy_compare_1y_at_trigger=0",
    "atr_days=0",
    "atr_progress=0",
    "too_high_multiplier=0",
    "rs_max_pct_below_52w_high=0",
    "rs_spy_int_tc_not_weak=true",
    "symbol_reentry_cooldown_days=60",
    f"time_stop_days={CONTROL_TIME}",
    "no_ft_days=0",
    "sell_breakdown=off",
    "rl_post_target_reentry_bars=0",
    "exit_when_spy_int_turns_weak=false",
    "max_atr_pct_at_trigger=0",
    "trailing_stop_increment=0",
    "sma_stop_days=0",
    "chandelier_enabled=false",
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


def _col(row: dict, *names: str) -> str:
    for n in names:
        if n in row and str(row[n]).strip() != "":
            return str(row[n])
    return ""


def load_universe_symbols() -> str:
    univ = DRIVE / "universes" / "RS_universe.csv"
    if not univ.is_file():
        raise SystemExit(f"missing {univ}")
    syms: list[str] = []
    with univ.open(encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            s = line.strip().split(",")[0].strip().upper()
            if not s or s.startswith("#") or s.lower() in ("symbol", "ticker"):
                continue
            if s not in syms:
                syms.append(s)
    if not syms:
        raise SystemExit("empty RS_universe.csv")
    return ",".join(syms)


def book_avg_pnl_wo_max(closed_path: Path) -> float:
    vals: list[float] = []
    if not closed_path.is_file():
        return 0.0
    with closed_path.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        for row in csv.DictReader(f):
            raw = _col(row, "PNL_PCT", "PNL %")
            if raw == "":
                continue
            try:
                vals.append(float(str(raw).replace("%", "")))
            except ValueError:
                continue
    if not vals:
        return 0.0
    mx = max(vals)
    dropped = False
    wo: list[float] = []
    for v in vals:
        if not dropped and v == mx and v > 0:
            dropped = True
            continue
        wo.append(v)
    return sum(wo) / len(wo) if wo else 0.0


def exit_mix(closed_path: Path) -> dict[str, int]:
    c: Counter[str] = Counter()
    if not closed_path.is_file():
        return {}
    with closed_path.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        for row in csv.DictReader(f):
            et = _col(row, "EXIT_TYPE", "EXIT TYPE").strip() or "UNKNOWN"
            c[et] += 1
    return dict(c)


def summary_aggs(summary_path: Path) -> dict[str, float]:
    if not summary_path.is_file():
        return {}
    paul: list[float] = []
    fit: list[float] = []
    fitr: list[float] = []
    wo: list[float] = []
    outl: list[float] = []
    tpy: list[float] = []
    with summary_path.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        for row in csv.DictReader(f):
            paul.append(_safe_num(row.get("PAUL_SCORE")))
            fit.append(_safe_num(row.get("FIT_SCORE")))
            fitr.append(_safe_num(row.get("FIT_SCORE_ROBUST")))
            wo.append(_safe_num(row.get("AVG_PNL_PCT_WO_MAX")))
            outl.append(_safe_num(row.get("OUTLIER_PCT_OF_WINS")))
            tpy.append(_safe_num(row.get("AVG_TRADES_PER_YEAR")))
    n = max(len(paul), 1)
    return {
        "paul_sum": sum(paul),
        "paul_mean": sum(paul) / n,
        "fit_sum": sum(fit),
        "fit_mean": sum(fit) / n,
        "fitr_sum": sum(fitr),
        "fitr_mean": sum(fitr) / n,
        "avg_pnl_wo_max_mean": sum(wo) / n,
        "outlier_mean": sum(outl) / n,
        "tpy_mean": sum(tpy) / n,
    }


def _parse_opened(row: dict) -> str:
    raw = _col(row, "DATE_OPENED", "DATE OPENED").strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) >= 8:
        return digits[:8]
    return ""


def load_closed_rows(closed_path: Path) -> list[dict[str, str]]:
    if not closed_path.is_file():
        return []
    with closed_path.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        return list(csv.DictReader(f))


def metrics_from_closed_rows(
    rows: list[dict[str, str]],
    *,
    brt_cash: float,
) -> dict[str, Any]:
    if not rows:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "wr": 0.0,
            "avg_pnl_pct": 0.0,
            "avg_r": 0.0,
            "ann_ror": 0.0,
            "avg_days": 0.0,
            "pnl": 0.0,
            "max_dd": 0.0,
            "pf": 0.0,
            "exit_target": 0,
            "exit_stop": 0,
            "exit_time": 0,
            "exit_gap_up": 0,
            "exit_gap_down": 0,
            "pct_time": 0.0,
            "pct_stop": 0.0,
            "pct_target": 0.0,
        }
    pnls: list[float] = []
    pcts: list[float] = []
    days: list[float] = []
    mix: Counter[str] = Counter()
    for row in rows:
        pct = _safe_num(_col(row, "PNL_PCT", "PNL %"))
        pd = _safe_num(_col(row, "PNL_DOLLARS", "PNL $", "PNL$"))
        dh = _safe_num(_col(row, "DAYS_HELD", "DAYS HELD"))
        et = _col(row, "EXIT_TYPE", "EXIT TYPE").strip() or "UNKNOWN"
        pcts.append(pct)
        pnls.append(pd)
        if dh > 0:
            days.append(dh)
        mix[et] += 1
    n = len(rows)
    wins = sum(1 for p in pcts if p > 0)
    losses = sum(1 for p in pcts if p < 0)
    total_pnl = sum(pnls)
    avg_pnl = sum(pcts) / n
    avg_r = avg_pnl / RISK_PCT if RISK_PCT > 0 else 0.0
    avg_days = (sum(days) / len(days)) if days else 0.0
    sum_w = sum(x for x in pnls if x > 0)
    sum_l = abs(sum(x for x in pnls if x < 0))
    pf = sum_w / sum_l if sum_l > 0 else (sum_w if sum_w > 0 else 0.0)
    ann = ann_ror_from_closed(
        total_pnl=total_pnl,
        n_trades=n,
        avg_days_held=avg_days,
        brt_cash=brt_cash if brt_cash > 0 else 27027.027027027027,
    )
    # Dollar peak-to-trough DD% on cumulative trade PnL (ordered by open date)
    ordered = sorted(rows, key=lambda r: (_parse_opened(r), _col(r, "SYMBOL")))
    eq = 0.0
    peak = 0.0
    max_dd = 0.0
    for row in ordered:
        eq += _safe_num(_col(row, "PNL_DOLLARS", "PNL $", "PNL$"))
        if eq > peak:
            peak = eq
        if peak > 0:
            dd = (peak - eq) / peak * 100.0
            if dd > max_dd:
                max_dd = dd
    et_t = mix.get("TARGET", 0)
    et_s = mix.get("STOP", 0) + mix.get("STOP_LOSS", 0)
    et_tm = mix.get("TIME", 0)
    et_gu = mix.get("GAP_UP", 0)
    et_gd = mix.get("GAP_DOWN", 0)
    return {
        "trades": n,
        "wins": wins,
        "losses": losses,
        "wr": 100.0 * wins / n if n else 0.0,
        "avg_pnl_pct": avg_pnl,
        "avg_r": avg_r,
        "ann_ror": float(ann or 0.0),
        "avg_days": avg_days,
        "pnl": total_pnl,
        "max_dd": max_dd,
        "pf": pf,
        "exit_target": et_t,
        "exit_stop": et_s,
        "exit_time": et_tm,
        "exit_gap_up": et_gu,
        "exit_gap_down": et_gd,
        "pct_time": 100.0 * et_tm / n if n else 0.0,
        "pct_stop": 100.0 * et_s / n if n else 0.0,
        "pct_target": 100.0 * et_t / n if n else 0.0,
    }


def is_oos_metrics(closed_path: Path, brt_cash: float) -> dict[str, Any]:
    rows = load_closed_rows(closed_path)
    is_rows = [r for r in rows if _parse_opened(r) and _parse_opened(r) < OOS_SPLIT]
    oos_rows = [r for r in rows if _parse_opened(r) and _parse_opened(r) >= OOS_SPLIT]
    return {
        "is": metrics_from_closed_rows(is_rows, brt_cash=brt_cash),
        "oos": metrics_from_closed_rows(oos_rows, brt_cash=brt_cash),
        "full_from_closed": metrics_from_closed_rows(rows, brt_cash=brt_cash),
    }


def extract_metrics(outdir: Path, stamp: str = "") -> Optional[dict[str, Any]]:
    report = None
    if stamp:
        for name in (f"RS_Audit_Report_{stamp}.csv", f"RS_Report_{stamp}.csv"):
            p = outdir / name
            if p.is_file():
                report = p
                break
    if report is None:
        report = _latest(outdir, "RS_Audit_Report_*.csv") or _latest(outdir, "RS_Report_*.csv")
    if report is None:
        return None
    with report.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        row = next(csv.DictReader(f), None)
    if not row:
        return None
    if not stamp:
        m = re.search(r"_(\d{12})\.csv$", report.name)
        stamp = m.group(1) if m else ""
    closed = outdir / f"RS_Closed_{stamp}.csv"
    summary = outdir / f"RS_Summary_{stamp}.csv"
    eq = outdir / f"RS_EquityMeta_{stamp}.csv"
    mix = exit_mix(closed)
    sag = summary_aggs(summary)
    eq_max_uw = 0.0
    eq_pct_uw = 0.0
    if eq.is_file():
        with eq.open(newline="", encoding="utf-8-sig", errors="replace") as f:
            er = next(csv.DictReader(f), None) or {}
        eq_max_uw = _safe_num(er.get("Max_Days_Underwater"))
        raw_pct = str(er.get("Pct_Days_Underwater", "")).replace("%", "")
        eq_pct_uw = _safe_num(raw_pct)
    trades = int(_safe_num(row.get("Total_Trades")))
    wins = int(_safe_num(row.get("Wins")))
    losses = int(_safe_num(row.get("Losses")))
    brt_cash = _safe_num(row.get("brt_cash"))
    if brt_cash <= 0:
        brt_cash = 27027.027027027027
    avg_pnl = _safe_num(row.get("Avg_PNL_Pct"))
    n = max(trades, 1)
    et_t = mix.get("TARGET", 0)
    et_s = mix.get("STOP", 0) + mix.get("STOP_LOSS", 0)
    et_tm = mix.get("TIME", 0)
    split = is_oos_metrics(closed, brt_cash)
    return {
        "ok": True,
        "stamp": stamp,
        "report": report.name,
        "trades": trades,
        "wins": wins,
        "losses": losses,
        "wr": _safe_num(row.get("Pct_Wins")),
        "avg_pnl_pct": avg_pnl,
        "avg_r": avg_pnl / RISK_PCT if RISK_PCT > 0 else 0.0,
        "book_avg_pnl_wo_max": book_avg_pnl_wo_max(closed),
        "ann_ror": _safe_num(row.get("Ann_ROR")),
        "avg_days": _safe_num(row.get("Avg_Days_Held")),
        "median_days": _safe_num(row.get("Median_Days_Held")),
        "pnl": _safe_num(row.get("Total_PNL")),
        "sheet_pnl": _safe_num(row.get("sheet_PnL")),
        "max_dd": _safe_num(row.get("Max_DD")),
        "pf": _safe_num(row.get("Profit_Factor")),
        "expectancy": _safe_num(row.get("Expectancy")),
        "expectancy_pct": _safe_num(row.get("Expectancy_Pct")),
        "avg_win_pct": _safe_num(row.get("Avg_Win_Pct")),
        "avg_loss_pct": _safe_num(row.get("Avg_Loss_Pct")),
        "wl_ratio": _safe_num(row.get("Win_Loss_Ratio")),
        "losing_streak": _safe_num(row.get("Losing_Streak")),
        "p90_days": _safe_num(row.get("P90_Days")),
        "avg_days_uw": _safe_num(row.get("Avg_Days_Underwater")),
        "p90_days_uw": _safe_num(row.get("P90_Days_Underwater")),
        "ppcd": _safe_num(row.get("Profit_Per_Capital_Day")),
        "capital_days": _safe_num(row.get("Capital_Days")),
        "brt_cash": brt_cash,
        "max_pos": _safe_num(row.get("Max_Positions")),
        "avg_pos": _safe_num(row.get("Avg_Positions")),
        "agg_pnl": _safe_num(row.get("Aggressive_Total_PNL")),
        "agg_dd": _safe_num(row.get("Aggressive_Max_DD")),
        "pct_max_sym": _safe_num(row.get("Pct_PNL_Max_Symbol")),
        "pct_max_trade": _safe_num(row.get("Pct_PNL_Max_Trade")),
        "eq_max_uw": eq_max_uw,
        "eq_pct_uw": eq_pct_uw,
        "exit_target": et_t,
        "exit_stop": et_s,
        "exit_time": et_tm,
        "exit_gap_up": mix.get("GAP_UP", 0),
        "exit_gap_down": mix.get("GAP_DOWN", 0),
        "pct_time": 100.0 * et_tm / n,
        "pct_stop": 100.0 * et_s / n,
        "pct_target": 100.0 * et_t / n,
        "is": split["is"],
        "oos": split["oos"],
        **sag,
    }


def copy_stamp_artifacts(src_dir: Path, dest: Path, stamp: str) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    roots = [src_dir]
    if src_dir.resolve() != DRIVE.resolve():
        roots.append(DRIVE)
    seen: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for p in root.glob(f"RS_*_{stamp}.*"):
            if not p.is_file() or p.name in seen:
                continue
            shutil.copy2(p, dest / p.name)
            seen.add(p.name)
            n += 1
    return n


def build_cmd(py: str, outdir: Path, workers: int, symbols: str, time_stop: int) -> list[str]:
    vs = list(RS_BASE_V)
    vs = [v for v in vs if not v.startswith("time_stop_days=")]
    vs.append(f"time_stop_days={time_stop}")
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
        "--relative-strength",
    ]
    for v in vs:
        cmd.extend(["-v", v])
    cmd.extend(["-s", symbols])
    return cmd


def lean_decision(r: dict[str, Any], cm: dict[str, Any]) -> tuple[str, str]:
    """KEEP / HOLD / DISMISS vs control — quality over count; Ann ROR primary."""
    if r.get("is_control"):
        return "HOLD", "control baseline (time_stop=252)"
    m = r.get("metrics") or {}
    if not m or not cm:
        return "HOLD", "no metrics"
    d_ror = float(m.get("ann_ror", 0)) - float(cm.get("ann_ror", 0))
    d_wr = float(m.get("wr", 0)) - float(cm.get("wr", 0))
    d_avg = float(m.get("avg_pnl_pct", 0)) - float(cm.get("avg_pnl_pct", 0))
    d_r = float(m.get("avg_r", 0)) - float(cm.get("avg_r", 0))
    d_dd = float(m.get("max_dd", 0)) - float(cm.get("max_dd", 0))
    d_tr = int(m.get("trades", 0) or 0) - int(cm.get("trades", 0) or 0)
    n_ctrl = max(int(cm.get("trades", 0) or 1), 1)
    n_ratio = int(m.get("trades", 0) or 0) / n_ctrl
    is_m = m.get("is") or {}
    oos_m = m.get("oos") or {}
    cis = cm.get("is") or {}
    coos = cm.get("oos") or {}
    d_is_ror = float(is_m.get("ann_ror", 0)) - float(cis.get("ann_ror", 0))
    d_oos_ror = float(oos_m.get("ann_ror", 0)) - float(coos.get("ann_ror", 0))

    if abs(d_ror) < 0.15 and abs(d_avg) < 0.15 and abs(d_wr) < 0.3 and abs(d_tr) <= 2:
        return "HOLD", f"flat vs control (ΔROR {d_ror:+.2f}, ΔAvg% {d_avg:+.2f})"

    quality_ok = d_avg >= -0.5 and d_wr >= -2.0 and d_r >= -0.05 and n_ratio >= 0.85
    quality_bad = d_avg < -1.0 or d_wr < -3.0 or n_ratio < 0.75

    if d_ror >= 1.0 and quality_ok and d_dd <= 1.5:
        note = (
            f"Ann_ROR {d_ror:+.2f}, Avg% {d_avg:+.2f}, WR {d_wr:+.1f}, "
            f"DD {d_dd:+.2f}; IS ΔROR {d_is_ror:+.2f}"
        )
        if d_oos_ror < -1.0:
            return "HOLD", note + f"; OOS softens (ΔROR {d_oos_ror:+.2f}) — do not retune"
        return "KEEP", note + f"; OOS ΔROR {d_oos_ror:+.2f} (report-only)"

    if d_ror >= 0.5 and quality_ok and d_dd <= 2.0:
        note = f"lean Ann_ROR {d_ror:+.2f}; IS {d_is_ror:+.2f}; OOS {d_oos_ror:+.2f}"
        if d_oos_ror < -1.0:
            return "HOLD", note + " — OOS softens, HOLD"
        return "LEAN KEEP", note

    if d_ror <= -1.0 or (d_ror < 0 and quality_bad):
        return "DISMISS", (
            f"worse: ΔROR {d_ror:+.2f}, ΔAvg% {d_avg:+.2f}, ΔWR {d_wr:+.1f}, "
            f"N ratio {n_ratio:.2f}"
        )

    return "HOLD", (
        f"mixed: ΔROR {d_ror:+.2f}, ΔAvg% {d_avg:+.2f}, ΔWR {d_wr:+.1f}, "
        f"ΔDD {d_dd:+.2f}, IS {d_is_ror:+.2f}, OOS {d_oos_ror:+.2f}"
    )


def run_arm(
    *,
    py: str,
    arm_id: str,
    time_stop: int,
    out_root: Path,
    drive_out: Path,
    workers: int,
    symbols: str,
    skip_existing: bool = False,
    is_control: bool = False,
) -> dict[str, Any]:
    arm_dir = out_root / arm_id
    arm_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "arm": arm_id,
        "time_stop": time_stop,
        "extras": f"time_stop_days={time_stop}",
        "is_control": is_control,
        "suggestion": (
            f"Control time_stop={CONTROL_TIME}"
            if is_control
            else f"One-change: time_stop_days {CONTROL_TIME}→{time_stop}"
        ),
    }

    if skip_existing:
        existing = _latest(arm_dir, "RS_Audit_Report_*.csv") or _latest(arm_dir, "RS_Report_*.csv")
        if existing:
            m = re.search(r"_(\d{12})\.csv$", existing.name)
            stamp = m.group(1) if m else ""
            metrics = extract_metrics(arm_dir, stamp)
            if metrics:
                result["ok"] = True
                result["metrics"] = metrics
                result["stamp"] = stamp
                result["elapsed_s"] = 0.0
                result["note"] = f"skipped existing stamp {stamp}"
                return result

    cmd = build_cmd(py, drive_out, workers, symbols, time_stop)
    log_path = arm_dir / "run.log"
    t0 = time.time()
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write("CMD: " + " ".join(cmd) + "\n\n")
        log.flush()
        proc = subprocess.run(cmd, cwd=str(REPO), stdout=log, stderr=subprocess.STDOUT)
    elapsed = time.time() - t0
    stamp = ""
    aud = _latest(drive_out, "RS_Audit_Report_*.csv")
    if aud:
        m = re.search(r"_(\d{12})\.csv$", aud.name)
        if m:
            stamp = m.group(1)
    n_copy = copy_stamp_artifacts(drive_out, arm_dir, stamp) if stamp else 0
    metrics = extract_metrics(arm_dir, stamp) if stamp else None
    result["ok"] = proc.returncode == 0 and metrics is not None
    result["exit_code"] = proc.returncode
    result["elapsed_s"] = elapsed
    result["stamp"] = stamp
    result["metrics"] = metrics or {}
    result["note"] = f"ran + copied {n_copy} files" if n_copy else "ran; no mirror"
    (arm_dir / "STAMP.txt").write_text(
        f"stamp={stamp}\narm={arm_id}\ntime_stop_days={time_stop}\n",
        encoding="utf-8",
    )
    if not result["ok"]:
        result["error"] = f"exit={proc.returncode}; see {log_path}"
    return result


def write_docs(out_root: Path, *, suite_stamp: str, n_sym: int, grid: list[int]) -> None:
    (out_root / "BASELINE.md").write_text(
        f"""# RS time_stop A/B — baseline freeze

**Research only.** Does not change production `run_rs.bat` or reconcile gold.

## Control identity (production / gold levers)

| Lever | Value | Source |
|---|---|---|
| `stop_pct` / multiplier | **{STOP_MULT}** / true | `run_rs.bat` / `rs_baseline_{FREEZE_REF}` |
| `target_pct` | **{TARGET_MULT}** | same |
| `time_stop_days` | **{CONTROL_TIME}** (control arm) | `RS_TIME_STOP` default |
| `symbol_reentry_cooldown_days` | **60** | same |
| `rs_spy_int_tc_not_weak` | true | same |
| Universe | `drive/universes/RS_universe.csv` (**{n_sym}** names) | ATEYY removed 2026-08-10 |
| Prior freeze ref | `{FREEZE_REF}` | 65-name stamp; this AB re-runs on current 64 |

## One-change rule

Arms vary **only** `time_stop_days`. Grid: {", ".join(str(g) for g in grid)} ({CONTROL_TIME} = control).

## IS / OOS

- IS = `DATE_OPENED` < 2024-01-01
- OOS = `DATE_OPENED` ≥ 2024-01-01 (report-only — **never retune** on OOS)

## Suite stamp

`{suite_stamp}` → `drive/paul_experiments/rs_time_stop_ab_{suite_stamp}/`
""",
        encoding="utf-8",
    )
    (out_root / "AB_PLAN.md").write_text(
        f"""# AB plan — RS time_stop grid

## Hypothesis

Shorter VZ-style calendar/bar time exits (if target/stop not hit) may improve **Ann ROR**
and turnover vs production `time_stop_days={CONTROL_TIME}` without collapsing trade quality
(WR / AvgR / AvgPnL%).

## Design

- One knob: `time_stop_days`
- Fixed: stop {STOP_MULT}, target {TARGET_MULT}, cd=60, RS gates as production
- Universe: RS gold CSV ({n_sym} symbols)
- Score: N, WR, AvgR (PNL%÷{RISK_PCT:.0f}), AvgPnL%, Ann ROR (house), Max DD, avg days, exit mix %
- Decision on **full-book + IS** quality; OOS report-only

## Arms

| Arm | time_stop_days |
|---|---:|
"""
        + "\n".join(
            f"| `{'00_control' if t == CONTROL_TIME else f'{i:02d}_time_{t}'}` | {t} |"
            for i, t in enumerate(grid)
        )
        + "\n",
        encoding="utf-8",
    )


def write_comparison(
    out_root: Path,
    rows: list[dict[str, Any]],
    *,
    suite_stamp: str,
    symbols: str,
    grid: list[int],
) -> Path:
    out_root.mkdir(parents=True, exist_ok=True)
    ctrl = next((r for r in rows if r.get("is_control")), None)
    cm = (ctrl or {}).get("metrics") or {}

    for r in rows:
        lean, why = lean_decision(r, cm)
        r["lean"] = lean
        r["lean_why"] = why

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

    # --- CSV ---
    csv_path = out_root / "comparison.csv"
    fields = [
        "arm",
        "time_stop",
        "stamp",
        "trades",
        "wr",
        "avg_r",
        "avg_pnl_pct",
        "book_avg_pnl_wo_max",
        "ann_ror",
        "avg_days",
        "pnl",
        "sheet_pnl",
        "max_dd",
        "pf",
        "ppcd",
        "capital_days",
        "exit_target",
        "exit_stop",
        "exit_time",
        "pct_target",
        "pct_stop",
        "pct_time",
        "is_n",
        "is_wr",
        "is_avg_r",
        "is_avg_pnl",
        "is_ann_ror",
        "is_avg_days",
        "is_max_dd",
        "oos_n",
        "oos_wr",
        "oos_avg_r",
        "oos_avg_pnl",
        "oos_ann_ror",
        "oos_avg_days",
        "oos_max_dd",
        "d_ann_ror",
        "d_wr",
        "d_avg_pnl",
        "d_max_dd",
        "d_avg_days",
        "lean",
        "lean_why",
        "note",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            m = r.get("metrics") or {}
            ism = m.get("is") or {}
            oosm = m.get("oos") or {}
            w.writerow(
                {
                    "arm": r["arm"],
                    "time_stop": r.get("time_stop"),
                    "stamp": r.get("stamp", m.get("stamp", "")),
                    "trades": m.get("trades"),
                    "wr": m.get("wr"),
                    "avg_r": m.get("avg_r"),
                    "avg_pnl_pct": m.get("avg_pnl_pct"),
                    "book_avg_pnl_wo_max": m.get("book_avg_pnl_wo_max"),
                    "ann_ror": m.get("ann_ror"),
                    "avg_days": m.get("avg_days"),
                    "pnl": m.get("pnl"),
                    "sheet_pnl": m.get("sheet_pnl"),
                    "max_dd": m.get("max_dd"),
                    "pf": m.get("pf"),
                    "ppcd": m.get("ppcd"),
                    "capital_days": m.get("capital_days"),
                    "exit_target": m.get("exit_target"),
                    "exit_stop": m.get("exit_stop"),
                    "exit_time": m.get("exit_time"),
                    "pct_target": m.get("pct_target"),
                    "pct_stop": m.get("pct_stop"),
                    "pct_time": m.get("pct_time"),
                    "is_n": ism.get("trades"),
                    "is_wr": ism.get("wr"),
                    "is_avg_r": ism.get("avg_r"),
                    "is_avg_pnl": ism.get("avg_pnl_pct"),
                    "is_ann_ror": ism.get("ann_ror"),
                    "is_avg_days": ism.get("avg_days"),
                    "is_max_dd": ism.get("max_dd"),
                    "oos_n": oosm.get("trades"),
                    "oos_wr": oosm.get("wr"),
                    "oos_avg_r": oosm.get("avg_r"),
                    "oos_avg_pnl": oosm.get("avg_pnl_pct"),
                    "oos_ann_ror": oosm.get("ann_ror"),
                    "oos_avg_days": oosm.get("avg_days"),
                    "oos_max_dd": oosm.get("max_dd"),
                    "d_ann_ror": (
                        (float(m.get("ann_ror", 0)) - float(cm.get("ann_ror", 0))) if cm else ""
                    ),
                    "d_wr": ((float(m.get("wr", 0)) - float(cm.get("wr", 0))) if cm else ""),
                    "d_avg_pnl": (
                        (float(m.get("avg_pnl_pct", 0)) - float(cm.get("avg_pnl_pct", 0)))
                        if cm
                        else ""
                    ),
                    "d_max_dd": (
                        (float(m.get("max_dd", 0)) - float(cm.get("max_dd", 0))) if cm else ""
                    ),
                    "d_avg_days": (
                        (float(m.get("avg_days", 0)) - float(cm.get("avg_days", 0))) if cm else ""
                    ),
                    "lean": r.get("lean"),
                    "lean_why": r.get("lean_why"),
                    "note": r.get("note"),
                }
            )

    # oos_split.csv (long form)
    oos_path = out_root / "oos_split.csv"
    with oos_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "arm",
                "time_stop",
                "split",
                "n",
                "wr",
                "avg_r",
                "avg_pnl_pct",
                "ann_ror",
                "avg_days",
                "max_dd",
                "pct_time",
                "pct_stop",
                "pct_target",
            ],
        )
        w.writeheader()
        for r in rows:
            m = r.get("metrics") or {}
            for label, key in (("IS_<2024-01-01", "is"), ("OOS_>=2024-01-01", "oos")):
                sm = m.get(key) or {}
                w.writerow(
                    {
                        "arm": r["arm"],
                        "time_stop": r.get("time_stop"),
                        "split": label,
                        "n": sm.get("trades"),
                        "wr": sm.get("wr"),
                        "avg_r": sm.get("avg_r"),
                        "avg_pnl_pct": sm.get("avg_pnl_pct"),
                        "ann_ror": sm.get("ann_ror"),
                        "avg_days": sm.get("avg_days"),
                        "max_dd": sm.get("max_dd"),
                        "pct_time": sm.get("pct_time"),
                        "pct_stop": sm.get("pct_stop"),
                        "pct_target": sm.get("pct_target"),
                    }
                )

    # --- HTML ---
    ths = "".join(
        [
            sortable_th("Arm", "text"),
            sortable_th("time_stop", "num"),
            sortable_th("Stamp", "text"),
            sortable_th("N", "num"),
            sortable_th("WR%", "num"),
            sortable_th("AvgR", "num"),
            sortable_th("Avg%", "num"),
            sortable_th("WO_MAX%", "num"),
            sortable_th("Ann_ROR", "num"),
            sortable_th("Max_DD", "num"),
            sortable_th("AvgDays", "num"),
            sortable_th("Sheet_PnL", "num"),
            sortable_th("Total_PNL", "num"),
            sortable_th("PF", "num"),
            sortable_th("%TARGET", "num"),
            sortable_th("%STOP", "num"),
            sortable_th("%TIME", "num"),
            sortable_th("IS_N", "num"),
            sortable_th("IS_WR", "num"),
            sortable_th("IS_AvgR", "num"),
            sortable_th("IS_AnnROR", "num"),
            sortable_th("OOS_N", "num"),
            sortable_th("OOS_WR", "num"),
            sortable_th("OOS_AvgR", "num"),
            sortable_th("OOS_AnnROR", "num"),
            sortable_th("Δ Ann_ROR", "num"),
            sortable_th("Δ WR", "num"),
            sortable_th("Δ Avg%", "num"),
            sortable_th("Δ DD", "num"),
            sortable_th("Lean", "text"),
            sortable_th("Why", "text"),
        ]
    )
    body_rows = []
    for r in rows:
        m = r.get("metrics") or {}
        ism = m.get("is") or {}
        oosm = m.get("oos") or {}
        cls = "total-row" if r.get("is_control") else ""
        d_ror = float(m.get("ann_ror", 0)) - float(cm.get("ann_ror", 0)) if cm else 0.0
        d_wr = float(m.get("wr", 0)) - float(cm.get("wr", 0)) if cm else 0.0
        d_avg = float(m.get("avg_pnl_pct", 0)) - float(cm.get("avg_pnl_pct", 0)) if cm else 0.0
        d_dd = float(m.get("max_dd", 0)) - float(cm.get("max_dd", 0)) if cm else 0.0
        lean = str(r.get("lean", ""))
        lean_cls = ""
        if lean in ("KEEP", "LEAN KEEP"):
            lean_cls = " style='background:#dcfce7'"
        elif lean == "DISMISS":
            lean_cls = " style='background:#fee2e2'"
        elif lean == "HOLD":
            lean_cls = " style='background:#fef9c3'"
        body_rows.append(
            f"<tr class='{cls}'>"
            f"<td>{html.escape(r['arm'])}</td>"
            f"<td>{fmt_i(r.get('time_stop'))}</td>"
            f"<td>{html.escape(str(r.get('stamp', m.get('stamp',''))))}</td>"
            f"<td>{fmt_i(m.get('trades'))}</td>"
            f"<td>{fmt(m.get('wr'), 2)}</td>"
            f"<td>{fmt(m.get('avg_r'), 3)}</td>"
            f"<td>{fmt(m.get('avg_pnl_pct'), 2)}</td>"
            f"<td>{fmt(m.get('book_avg_pnl_wo_max'), 2)}</td>"
            f"<td>{fmt(m.get('ann_ror'), 2)}</td>"
            f"<td>{fmt(m.get('max_dd'), 2)}</td>"
            f"<td>{fmt(m.get('avg_days'), 1)}</td>"
            f"<td>{html.escape(format_money(m.get('sheet_pnl')))}</td>"
            f"<td>{html.escape(format_money(m.get('pnl')))}</td>"
            f"<td>{fmt(m.get('pf'), 2)}</td>"
            f"<td>{fmt(m.get('pct_target'), 1)}</td>"
            f"<td>{fmt(m.get('pct_stop'), 1)}</td>"
            f"<td>{fmt(m.get('pct_time'), 1)}</td>"
            f"<td>{fmt_i(ism.get('trades'))}</td>"
            f"<td>{fmt(ism.get('wr'), 2)}</td>"
            f"<td>{fmt(ism.get('avg_r'), 3)}</td>"
            f"<td>{fmt(ism.get('ann_ror'), 2)}</td>"
            f"<td>{fmt_i(oosm.get('trades'))}</td>"
            f"<td>{fmt(oosm.get('wr'), 2)}</td>"
            f"<td>{fmt(oosm.get('avg_r'), 3)}</td>"
            f"<td>{fmt(oosm.get('ann_ror'), 2)}</td>"
            f"<td>{fmt(d_ror, 2)}</td>"
            f"<td>{fmt(d_wr, 2)}</td>"
            f"<td>{fmt(d_avg, 2)}</td>"
            f"<td>{fmt(d_dd, 2)}</td>"
            f"<td{lean_cls}><strong>{html.escape(lean)}</strong></td>"
            f"<td>{html.escape(str(r.get('lean_why','')))}</td>"
            f"</tr>"
        )

    # Verdict
    scored = [r for r in rows if r.get("metrics") and not r.get("is_control")]
    best = None
    if scored and cm:
        best = max(scored, key=lambda r: float((r.get("metrics") or {}).get("ann_ror", 0)))
    ctrl_ror = float(cm.get("ann_ror", 0)) if cm else 0.0
    best_ror = float((best.get("metrics") or {}).get("ann_ror", 0)) if best else ctrl_ror
    best_lean = (best or {}).get("lean", "HOLD")
    if best and best_lean in ("KEEP", "LEAN KEEP") and best_ror > ctrl_ror:
        verdict = (
            f"**Candidate:** adopt `time_stop_days={best.get('time_stop')}` "
            f"(Ann ROR {best_ror:.2f} vs control {ctrl_ror:.2f}). "
            f"Research-only — needs PO / reconcile before gold."
        )
        verdict_short = f"LEAN adopt time_stop={best.get('time_stop')}"
    else:
        verdict = (
            f"**HOLD production `time_stop_days={CONTROL_TIME}`** "
            f"(control Ann ROR {ctrl_ror:.2f}"
            + (
                f"; best arm {best.get('arm')} Ann ROR {best_ror:.2f} lean={best_lean}"
                if best
                else ""
            )
            + "). No clear quality+ROR win for shorter time stop."
        )
        verdict_short = f"HOLD time_stop={CONTROL_TIME}"

    (out_root / "VERDICT.md").write_text(
        f"""# Verdict — RS time_stop A/B `{suite_stamp}`

{verdict}

| | Ann ROR | Arm |
|---|---:|---|
| Control | {ctrl_ror:.2f} | time_stop={CONTROL_TIME} |
| Best Ann ROR arm | {best_ror:.2f} | {(best or {}).get('arm', '—')} (lean={(best or {}).get('lean', '—')}) |

OOS is report-only. Do not retune on OOS softens.
""",
        encoding="utf-8",
    )

    n_sym = len(symbols.split(","))
    html_doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>RS time_stop A/B {html.escape(suite_stamp)}</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:1.5rem;color:#0f172a;background:#f8fafc}}
h1{{font-size:1.4rem;margin:0 0 .4rem}}
.muted{{color:#64748b;font-size:.92rem}}
.verdict{{background:#eff6ff;border:1px solid #bfdbfe;padding:.75rem 1rem;border-radius:6px;margin:1rem 0}}
table.sortable{{border-collapse:collapse;width:100%;background:#fff;margin:1rem 0;font-size:.78rem}}
th,td{{border:1px solid #e2e8f0;padding:.35rem .45rem;text-align:left;vertical-align:top}}
th{{background:#f1f5f9}}
tr.total-row{{background:#eff6ff;font-weight:600}}
code{{font-size:.78rem}}
{SORTABLE_TH_CSS}
</style></head><body>
<h1>RS time_stop one-knob A/B — {html.escape(suite_stamp)}</h1>
<p class="muted">Control = production RS gold levers (stop <code>{STOP_MULT}</code> /
target <code>{TARGET_MULT}</code> / <code>time_stop_days={CONTROL_TIME}</code> / cd=60,
universe <code>RS_universe.csv</code> {n_sym} names). Grid: {html.escape(", ".join(str(g) for g in grid))}.
One change per arm. Metrics: <code>CANONICAL_COMPARE_METRICS.md</code>.
AvgR = AvgPnL% ÷ {RISK_PCT:.0f} (stop risk). Click column headers to sort.</p>
<p class="muted">IS = entry &lt; 2024-01-01; OOS = entry ≥ 2024-01-01
(<strong>report-only — do not retune</strong>). Research only — gold freeze unchanged.</p>
<div class="verdict"><strong>Verdict:</strong> {verdict.replace("**", "")}</div>

<h2>Full book + IS/OOS vs control</h2>
<p class="muted">Click column headers to sort. Control row pinned (blue).</p>
<table class="sortable"><thead><tr>{ths}</tr></thead>
<tbody>
{''.join(body_rows)}
</tbody></table>

<p class="muted">Lean: <strong>KEEP / LEAN KEEP</strong> = quality+Ann ROR lift ·
<strong>HOLD</strong> = flat/mixed/OOS softens · <strong>DISMISS</strong> = clear regression.
Automated triage only — adopt needs PO + re-baseline.</p>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    html_path = out_root / "comparison.html"
    html_path.write_text(html_doc, encoding="utf-8")

    # MD mirror
    md = [
        f"# RS time_stop A/B `{suite_stamp}`",
        "",
        verdict,
        "",
        f"Control Ann ROR **{ctrl_ror:.2f}** vs best **{best_ror:.2f}** "
        f"(`{(best or {}).get('arm', '—')}`).",
        "",
        f"Short: {verdict_short}",
        "",
        "See `comparison.html` / `comparison.csv` / `oos_split.csv`.",
    ]
    (out_root / "comparison.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return html_path


def main() -> int:
    ap = argparse.ArgumentParser(description="RS time_stop one-knob A/B")
    ap.add_argument(
        "--grid",
        default=",".join(str(x) for x in DEFAULT_GRID),
        help="Comma-separated time_stop_days (252=control)",
    )
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument(
        "--suite-stamp",
        default="",
        help="Override suite folder stamp (default: now YYMMDDHHMMSS)",
    )
    args = ap.parse_args()
    grid = [int(x.strip()) for x in args.grid.split(",") if x.strip()]
    if CONTROL_TIME not in grid:
        grid.append(CONTROL_TIME)
    # Unique preserve order; control first visually by arm id
    seen: set[int] = set()
    grid_u: list[int] = []
    for g in grid:
        if g not in seen:
            seen.add(g)
            grid_u.append(g)
    grid = grid_u

    suite_stamp = args.suite_stamp.strip() or datetime.now().strftime("%y%m%d%H%M%S")
    out_root = DRIVE / "paul_experiments" / f"rs_time_stop_ab_{suite_stamp}"
    out_root.mkdir(parents=True, exist_ok=True)

    py = _resolve_python()
    symbols = load_universe_symbols()
    n_sym = len(symbols.split(","))
    write_docs(out_root, suite_stamp=suite_stamp, n_sym=n_sym, grid=grid)

    print(f"[rs_time_stop_ab] suite={suite_stamp} out={out_root}")
    print(f"[rs_time_stop_ab] universe n={n_sym} grid={grid} workers={args.workers}")
    print(
        f"[rs_time_stop_ab] freeze: stop={STOP_MULT} target={TARGET_MULT} "
        f"cd=60 control_time={CONTROL_TIME}"
    )

    # Build arms: control first, then others sorted by time_stop
    arms: list[tuple[str, int, bool]] = []
    others = sorted(t for t in grid if t != CONTROL_TIME)
    arms.append(("00_control", CONTROL_TIME, True))
    for i, t in enumerate(others, start=1):
        arms.append((f"{i:02d}_time_{t}", t, False))

    results: list[dict[str, Any]] = []
    for i, (arm_id, ts, is_ctrl) in enumerate(arms, start=1):
        print(f"\n========== [{i}/{len(arms)}] {arm_id} time_stop={ts} ==========")
        r = run_arm(
            py=py,
            arm_id=arm_id,
            time_stop=ts,
            out_root=out_root,
            drive_out=DRIVE,
            workers=args.workers,
            symbols=symbols,
            skip_existing=args.skip_existing,
            is_control=is_ctrl,
        )
        results.append(r)
        m = r.get("metrics") or {}
        print(
            f"  stamp={r.get('stamp')} trades={m.get('trades')} "
            f"Ann_ROR={m.get('ann_ror')} AvgDays={m.get('avg_days')} "
            f"ok={r.get('ok')} note={r.get('note')}"
        )

    html_path = write_comparison(
        out_root, results, suite_stamp=suite_stamp, symbols=symbols, grid=grid
    )
    print(f"\n[rs_time_stop_ab] wrote {html_path}")
    print(f"[rs_time_stop_ab] verdict: {(out_root / 'VERDICT.md').read_text(encoding='utf-8')[:400]}")

    fails = sum(1 for r in results if not r.get("ok"))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
