#!/usr/bin/env python3
"""RS ImprovePriority A/B from stamp 260808222610 (short-hold universe report).

Hints came from ImprovePriority on short-hold univ stamp 260808222610 (63 names),
but A/B runs on **gold-65 production** control (stamp 260807141317, stop 0.85 /
target 1.25 / time_stop 252 / cd=60) — production decision baseline. Hints are
param/pattern levers (target/stop/trail/regime), not universe-specific.

Skips: band_pct (RS unused); post_target bars=15 under cd=60 (noop); peer YH
(insufficient). Reuses prior expand65 / slow_hold arm stamps where knobs match;
runs only missing stop-expand arms.

See docs/HYPOTHESIS_TEST.md + drive/paul_experiments/CANONICAL_COMPARE_METRICS.md.

Usage (repo root)::

  python tools/rs_improve_prio_260808_ab.py --reuse-control 260807141317
  run_rs_improve_prio_260808_ab.bat
  run_rs_improve_prio_260808_ab.bat 260807141317
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
DEFAULT_OUT = DRIVE / "paul_experiments" / "rs_improve_prio_260808_ab"
DEFAULT_CONTROL = "260807141317"
HINT_STAMP = "260808222610"
EXPAND65 = DRIVE / "paul_experiments" / "rs_expand65_hint_ab"
SLOW = DRIVE / "paul_experiments" / "rs_slow_hold_hint_ab"

RS_BASE_V = [
    "rs_mode=true",
    "brt_zones=false",
    "yh_zones=false",
    "wpbr_zones=false",
    "rl_mode=false",
    "target_pct=1.25",
    "stop_pct=0.85",
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
    "time_stop_days=252",
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


@dataclass
class Arm:
    arm_id: str
    hypothesis_id: str
    family: str  # param | pattern | peer | skip
    suggestion: str
    extras: list[str] = field(default_factory=list)
    is_control: bool = False
    skip: bool = False
    skip_reason: str = ""
    # Optional prior arm stamp to reuse (same knobs, gold-65)
    reuse_stamp: str = ""
    reuse_src_dir: Optional[Path] = None


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


def build_arms() -> list[Arm]:
    """Every ImprovePriority 260808222610 lever → one-knob arm (or skip)."""
    return [
        Arm(
            "00_control",
            "baseline_run_rs_gold65",
            "param",
            f"Production gold-65 run_rs.bat stamp {DEFAULT_CONTROL}: "
            "stop 0.85 / target 1.25 / time_stop=252 / cd=60. "
            f"Hints sourced from ImprovePriority_{HINT_STAMP} (short-hold univ).",
            is_control=True,
            reuse_stamp=DEFAULT_CONTROL,
            reuse_src_dir=DRIVE,
        ),
        # --- Parameter suggestions ---
        Arm(
            "01_target_expand_130",
            "target_pct_tension_expand_vs_contract",
            "param",
            "Expand lens: TARGET exits continued ≥5% in 15 bars — widen target 1.25→1.30.",
            ["target_pct=1.30"],
            reuse_stamp="260807142732",
            reuse_src_dir=EXPAND65 / "01_target_expand_130",
        ),
        Arm(
            "02_target_contract_120",
            "target_pct_tension_contract_approach_fail",
            "param",
            "Contract lens + approach_fail: closer target 1.25→1.20 (turnover / lock gains).",
            ["target_pct=1.20"],
            reuse_stamp="260807142745",
            reuse_src_dir=EXPAND65 / "02_target_contract_120",
        ),
        Arm(
            "03_stop_expand_080",
            "stop_pct_tension_expand_peer_hold",
            "param",
            "Expand stop (mixed card A + peer_longer_hold/target_after_stop): "
            "wider stop 0.85→0.80 (mult; more room vs wick-through STOP).",
            ["stop_pct=0.80"],
            # NEW — not in prior suites
        ),
        Arm(
            "04_stop_expand_082",
            "stop_pct_tension_expand_alt",
            "param",
            "Stop expand alt (≤2): stop_pct=0.82.",
            ["stop_pct=0.82"],
        ),
        Arm(
            "05_stop_contract_088",
            "stop_pct_tension_contract",
            "param",
            "Contract stop lens / dead losers: tighten stop 0.85→0.88.",
            ["stop_pct=0.88"],
            reuse_stamp="260807142758",
            reuse_src_dir=EXPAND65 / "03_stop_contract_088",
        ),
        Arm(
            "06_stop_contract_090",
            "fat_stops_tighter_stop",
            "param",
            "fat_stops + stop contract alt: stop_pct=0.90.",
            ["stop_pct=0.90"],
            reuse_stamp="260807142812",
            reuse_src_dir=EXPAND65 / "04_stop_contract_090",
        ),
        Arm(
            "07_band_pct_skip",
            "band_tighten_weak_fill",
            "skip",
            "Tighten band/acceptance for shallow MFE fills — not an RS lever.",
            skip=True,
            skip_reason="RS does not use band_pct / zone proximity; dismiss for this system",
        ),
        # --- Taken-trade patterns ---
        Arm(
            "08_fat_atr_days_45",
            "fat_stops_atr_time",
            "pattern",
            "fat_stops alt beyond tighter stop: atr_days=45 cut schedule.",
            ["atr_days=45", "atr_progress=0"],
            reuse_stamp="260807142826",
            reuse_src_dir=EXPAND65 / "06_fat_atr_days_45",
        ),
        Arm(
            "09_target_contract_115",
            "slow_target_grind_contract",
            "pattern",
            "slow_target_grind: closer target 1.15 (recycle capital; Ann_ROR over fat tag).",
            ["target_pct=1.15"],
            reuse_stamp="260807160118",
            reuse_src_dir=SLOW / "01_target_contract_115",
        ),
        Arm(
            "10_time_stop_120",
            "slow_target_grind_shorter_time",
            "pattern",
            "slow_target_grind / early_run alt: time_stop_days 252→120.",
            ["time_stop_days=120"],
            reuse_stamp="260807160133",
            reuse_src_dir=SLOW / "02_time_stop_120",
        ),
        Arm(
            "11_trail_inc_10",
            "early_run_long_tail_trail",
            "pattern",
            "early_run_long_tail: trailing_stop_increment=10 (closest RS trail-after-+10%).",
            ["trailing_stop_increment=10"],
            reuse_stamp="260807160149",
            reuse_src_dir=SLOW / "03_trail_inc_10",
        ),
        Arm(
            "12_trail_inc_5",
            "winner_peak_giveback_trail",
            "pattern",
            "winner_peak_giveback: trailing_stop_increment=5 (tighter gain trail).",
            ["trailing_stop_increment=5"],
            reuse_stamp="260807160204",
            reuse_src_dir=SLOW / "04_trail_inc_5",
        ),
        Arm(
            "13_sma_stop_20",
            "winner_peak_giveback_sma",
            "pattern",
            "winner_peak_giveback alt: sma_stop_days=20.",
            ["sma_stop_days=20"],
            reuse_stamp="260807160220",
            reuse_src_dir=SLOW / "05_sma_stop_20",
        ),
        Arm(
            "14_pt_none_15_skip",
            "post_target_quick_stop",
            "skip",
            "post_target bars=15 mode=none — dominated by production cd=60.",
            skip=True,
            skip_reason=(
                "noop under production symbol_reentry_cooldown_days=60 "
                "(15 trading bars << 60 calendar days after any exit); prior expand65 "
                "arm 07_pt_none_15 identical to control"
            ),
        ),
        Arm(
            "15_cd_90",
            "post_target_quick_stop_cd",
            "pattern",
            "post_target alt not dominated by cd=60: longer blanket cooldown 90d.",
            ["symbol_reentry_cooldown_days=90"],
            reuse_stamp="260807142853",
            reuse_src_dir=EXPAND65 / "08_cd_90",
        ),
        Arm(
            "16_false_growth_252",
            "false_start_2022_2023_growth",
            "pattern",
            "false_start regime proxy: growth_filter_enabled + growth_bars=252.",
            ["growth_filter_enabled=true", "growth_bars=252"],
            reuse_stamp="260807142906",
            reuse_src_dir=EXPAND65 / "09_false_growth_252",
        ),
        Arm(
            "17_false_spy_int_exit",
            "false_start_2022_2023_spy_exit",
            "pattern",
            "false_start: exit_when_spy_int_turns_weak=true.",
            ["exit_when_spy_int_turns_weak=true"],
            reuse_stamp="260807142919",
            reuse_src_dir=EXPAND65 / "10_false_spy_int_exit",
        ),
        Arm(
            "18_peer_yh_skip",
            "peer_longer_hold_won_yh",
            "skip",
            "Peer YH longer-hold (1 sym / insufficient confidence).",
            skip=True,
            skip_reason="ImprovePriority confidence=insufficient (1 symbol); do not A/B",
        ),
    ]


def _col(row: dict, *names: str) -> str:
    for n in names:
        if n in row and str(row[n]).strip() != "":
            return str(row[n])
    return ""


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
    return {
        "ok": True,
        "stamp": stamp,
        "report": report.name,
        "trades": trades,
        "wins": wins,
        "losses": losses,
        "wr": _safe_num(row.get("Pct_Wins")),
        "avg_pnl_pct": _safe_num(row.get("Avg_PNL_Pct")),
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
        "brt_cash": _safe_num(row.get("brt_cash")),
        "max_pos": _safe_num(row.get("Max_Positions")),
        "avg_pos": _safe_num(row.get("Avg_Positions")),
        "agg_pnl": _safe_num(row.get("Aggressive_Total_PNL")),
        "agg_dd": _safe_num(row.get("Aggressive_Max_DD")),
        "pct_max_sym": _safe_num(row.get("Pct_PNL_Max_Symbol")),
        "pct_max_trade": _safe_num(row.get("Pct_PNL_Max_Trade")),
        "eq_max_uw": eq_max_uw,
        "eq_pct_uw": eq_pct_uw,
        "exit_target": mix.get("TARGET", 0),
        "exit_stop": mix.get("STOP", 0) + mix.get("STOP_LOSS", 0),
        "exit_time": mix.get("TIME", 0),
        "exit_gap_up": mix.get("GAP_UP", 0),
        "exit_gap_down": mix.get("GAP_DOWN", 0),
        **sag,
    }


def copy_stamp_artifacts(src_dir: Path, dest: Path, stamp: str) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    # Prefer files already in src_dir; also check DRIVE
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


def build_cmd(py: str, outdir: Path, workers: int, symbols: str, extras: list[str]) -> list[str]:
    vs = list(RS_BASE_V)
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
        "--relative-strength",
    ]
    for v in vs:
        cmd.extend(["-v", v])
    cmd.extend(["-s", symbols])
    return cmd


def lean_decision(r: dict[str, Any], cm: dict[str, Any]) -> tuple[str, str]:
    if r.get("skip"):
        return "dismiss", r.get("skip_reason") or "not applicable"
    if r.get("is_control"):
        return "hold", "baseline"
    m = r.get("metrics") or {}
    if not m or not cm:
        return "hold", "no metrics"
    d_pnl = float(m.get("pnl", 0)) - float(cm.get("pnl", 0))
    d_dd = float(m.get("max_dd", 0)) - float(cm.get("max_dd", 0))
    d_ror = float(m.get("ann_ror", 0)) - float(cm.get("ann_ror", 0))
    d_wr = float(m.get("wr", 0)) - float(cm.get("wr", 0))
    d_tr = int(m.get("trades", 0) or 0) - int(cm.get("trades", 0) or 0)
    d_ppcd = float(m.get("ppcd", 0)) - float(cm.get("ppcd", 0))
    d_days = float(m.get("avg_days", 0)) - float(cm.get("avg_days", 0))
    d_fitr = float(m.get("fitr_mean", 0)) - float(cm.get("fitr_mean", 0))
    if (
        abs(d_pnl) < 1.0
        and abs(d_ror) < 0.01
        and abs(d_dd) < 0.01
        and abs(d_wr) < 0.01
        and d_tr == 0
    ):
        return "noop", "Identical metrics vs control — no effect"
    if d_pnl < -200_000:
        return "dismiss", f"PnL {d_pnl:+.0f} vs control (large $ regression)"
    if d_pnl < -50_000 and d_ror <= 0:
        return "dismiss", f"PnL {d_pnl:+.0f} / Ann_ROR {d_ror:+.2f} vs control — worse"
    if d_pnl > 80_000 and d_dd <= 1.5 and d_ror >= 0:
        return "adopt?", f"PnL {d_pnl:+.0f}, Ann_ROR {d_ror:+.2f}, DD {d_dd:+.2f} — candidate (PO/ToS)"
    if d_days < -15 and d_ppcd > 1.0 and d_dd <= 1.0 and d_pnl > -40_000:
        return "hold", (
            f"turnover mix: days {d_days:+.1f}, $/cap-day {d_ppcd:+.2f}, "
            f"PnL {d_pnl:+.0f}, DD {d_dd:+.2f}"
        )
    if abs(d_pnl) < 40_000 and abs(d_ror) < 0.8 and abs(d_dd) < 0.8:
        note = f"flat vs control (PnL {d_pnl:+.0f}, ROR {d_ror:+.2f}, DD {d_dd:+.2f}"
        if abs(d_fitr) >= 0.05:
            note += f", FIT_R {d_fitr:+.2f}"
        return "hold", note + ")"
    if d_pnl > 0 and d_dd > 1.5:
        return "hold", f"PnL up {d_pnl:+.0f} but DD↑ {d_dd:+.2f} — tradeoff"
    if d_pnl < 0 and d_dd < -0.5 and d_wr > 1:
        return "hold", f"PnL down {d_pnl:+.0f}; quality mix (WR {d_wr:+.1f}, DD {d_dd:+.2f})"
    if d_pnl < -20_000:
        return "dismiss", f"PnL {d_pnl:+.0f} vs control"
    return "hold", f"mixed (PnL {d_pnl:+.0f}, ROR {d_ror:+.2f}, DD {d_dd:+.2f}, WR {d_wr:+.1f})"


def run_arm(
    *,
    py: str,
    arm: Arm,
    out_root: Path,
    drive_out: Path,
    workers: int,
    symbols: str,
    force_rerun: bool = False,
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

    # Reuse prior stamp when available
    if arm.reuse_stamp and not force_rerun:
        src = arm.reuse_src_dir or DRIVE
        n = copy_stamp_artifacts(src, arm_dir, arm.reuse_stamp)
        if n == 0:
            n = copy_stamp_artifacts(DRIVE, arm_dir, arm.reuse_stamp)
        metrics = extract_metrics(arm_dir, arm.reuse_stamp)
        if metrics is None:
            metrics = extract_metrics(DRIVE, arm.reuse_stamp)
            if metrics:
                copy_stamp_artifacts(DRIVE, arm_dir, arm.reuse_stamp)
        if metrics:
            result["ok"] = True
            result["metrics"] = metrics
            result["stamp"] = arm.reuse_stamp
            result["elapsed_s"] = 0.0
            result["note"] = f"reused stamp {arm.reuse_stamp} from {src} ({n} files)"
            (arm_dir / "STAMP.txt").write_text(
                f"stamp={arm.reuse_stamp}\narm={arm.arm_id}\nextra=(reuse)\n",
                encoding="utf-8",
            )
            return result
        print(f"  [warn] reuse stamp {arm.reuse_stamp} missing — will run")

    cmd = build_cmd(py, drive_out, workers, symbols, arm.extras)
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
        f"stamp={stamp}\narm={arm.arm_id}\nextra={' '.join(arm.extras)}\n",
        encoding="utf-8",
    )
    if not result["ok"]:
        result["error"] = f"exit={proc.returncode}; see {log_path}"
    return result


def write_comparison(
    out_root: Path,
    rows: list[dict[str, Any]],
    *,
    stamp_src: str,
    symbols: str,
) -> Path:
    out_root.mkdir(parents=True, exist_ok=True)
    ctrl = next((r for r in rows if r.get("arm") == "00_control"), None)
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

    csv_path = out_root / "comparison.csv"
    fields = [
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
        "ppcd",
        "capital_days",
        "losing_streak",
        "p90_days",
        "fitr_mean",
        "paul_mean",
        "tpy_mean",
        "outlier_mean",
        "exit_target",
        "exit_stop",
        "exit_time",
        "d_pnl",
        "d_sheet_pnl",
        "d_ann_ror",
        "d_max_dd",
        "d_pf",
        "d_fitr",
        "lean",
        "lean_why",
        "suggestion",
        "note",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            m = r.get("metrics") or {}
            if r.get("skip"):
                w.writerow(
                    {
                        "arm": r["arm"],
                        "family": r.get("family"),
                        "hypothesis_id": r.get("hypothesis_id"),
                        "extras": r.get("extras"),
                        "lean": r.get("lean"),
                        "lean_why": r.get("lean_why"),
                        "suggestion": r.get("suggestion"),
                        "note": r.get("note") or r.get("skip_reason"),
                    }
                )
                continue
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
                    "ppcd": m.get("ppcd"),
                    "capital_days": m.get("capital_days"),
                    "losing_streak": m.get("losing_streak"),
                    "p90_days": m.get("p90_days"),
                    "fitr_mean": m.get("fitr_mean"),
                    "paul_mean": m.get("paul_mean"),
                    "tpy_mean": m.get("tpy_mean"),
                    "outlier_mean": m.get("outlier_mean"),
                    "exit_target": m.get("exit_target"),
                    "exit_stop": m.get("exit_stop"),
                    "exit_time": m.get("exit_time"),
                    "d_pnl": (float(m.get("pnl", 0)) - float(cm.get("pnl", 0))) if cm else "",
                    "d_sheet_pnl": (
                        (float(m.get("sheet_pnl", 0)) - float(cm.get("sheet_pnl", 0))) if cm else ""
                    ),
                    "d_ann_ror": (
                        (float(m.get("ann_ror", 0)) - float(cm.get("ann_ror", 0))) if cm else ""
                    ),
                    "d_max_dd": (
                        (float(m.get("max_dd", 0)) - float(cm.get("max_dd", 0))) if cm else ""
                    ),
                    "d_pf": (float(m.get("pf", 0)) - float(cm.get("pf", 0))) if cm else "",
                    "d_fitr": (
                        (float(m.get("fitr_mean", 0)) - float(cm.get("fitr_mean", 0))) if cm else ""
                    ),
                    "lean": r.get("lean"),
                    "lean_why": r.get("lean_why"),
                    "suggestion": r.get("suggestion"),
                    "note": r.get("note"),
                }
            )

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
            sortable_th("Sheet_PnL", "num"),
            sortable_th("Total_PNL", "num"),
            sortable_th("Max_DD", "num"),
            sortable_th("PF", "num"),
            sortable_th("$/cap-day", "num"),
            sortable_th("CapDays", "num"),
            sortable_th("AvgDays", "num"),
            sortable_th("FIT_R mean", "num"),
            sortable_th("Paul mean", "num"),
            sortable_th("TPY mean", "num"),
            sortable_th("Outlier%", "num"),
            sortable_th("TARGET", "num"),
            sortable_th("STOP", "num"),
            sortable_th("TIME", "num"),
            sortable_th("Δ PnL", "num"),
            sortable_th("Δ ROR", "num"),
            sortable_th("Δ DD", "num"),
            sortable_th("Δ FIT_R", "num"),
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
                f"<td colspan='25'>{html.escape(r.get('skip_reason') or 'skipped')}</td>"
                f"<td>{html.escape(str(r.get('lean','')))}</td>"
                f"<td>{html.escape(str(r.get('lean_why','')))}</td></tr>"
            )
            continue
        d_pnl = float(m.get("pnl", 0)) - float(cm.get("pnl", 0)) if cm else 0.0
        d_ror = float(m.get("ann_ror", 0)) - float(cm.get("ann_ror", 0)) if cm else 0.0
        d_dd = float(m.get("max_dd", 0)) - float(cm.get("max_dd", 0)) if cm else 0.0
        d_fitr = float(m.get("fitr_mean", 0)) - float(cm.get("fitr_mean", 0)) if cm else 0.0
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
            f"<td>{fmt(m.get('sheet_pnl'), 0)}</td>"
            f"<td>{fmt(m.get('pnl'), 0)}</td>"
            f"<td>{fmt(m.get('max_dd'), 2)}</td>"
            f"<td>{fmt(m.get('pf'), 2)}</td>"
            f"<td>{fmt(m.get('ppcd'), 2)}</td>"
            f"<td>{fmt_i(m.get('capital_days'))}</td>"
            f"<td>{fmt(m.get('avg_days'), 1)}</td>"
            f"<td>{fmt(m.get('fitr_mean'), 2)}</td>"
            f"<td>{fmt(m.get('paul_mean'), 2)}</td>"
            f"<td>{fmt(m.get('tpy_mean'), 2)}</td>"
            f"<td>{fmt(m.get('outlier_mean'), 2)}</td>"
            f"<td>{fmt_i(m.get('exit_target'))}</td>"
            f"<td>{fmt_i(m.get('exit_stop'))}</td>"
            f"<td>{fmt_i(m.get('exit_time'))}</td>"
            f"<td>{fmt(d_pnl, 0)}</td>"
            f"<td>{fmt(d_ror, 2)}</td>"
            f"<td>{fmt(d_dd, 2)}</td>"
            f"<td>{fmt(d_fitr, 2)}</td>"
            f"<td{lean_cls}><strong>{html.escape(lean)}</strong></td>"
            f"<td>{html.escape(str(r.get('lean_why','')))}</td>"
            f"</tr>"
        )

    hyp_rows = []
    for r in rows:
        hyp_rows.append(
            "<tr>"
            f"<td>{html.escape(r['arm'])}</td>"
            f"<td><code>{html.escape(str(r.get('hypothesis_id','')))}</code></td>"
            f"<td>{html.escape(str(r.get('suggestion','')))}</td>"
            f"<td>{html.escape(str(r.get('note') or r.get('skip_reason') or ''))}</td>"
            "</tr>"
        )

    n_sym = len(symbols.split(","))
    html_doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>RS ImprovePriority {HINT_STAMP} A/B (gold-65)</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:1.5rem;color:#0f172a;background:#f8fafc}}
h1{{font-size:1.4rem;margin:0 0 .4rem}}
.muted{{color:#64748b;font-size:.92rem}}
table.sortable{{border-collapse:collapse;width:100%;background:#fff;margin:1rem 0;font-size:.82rem}}
th,td{{border:1px solid #e2e8f0;padding:.35rem .45rem;text-align:left;vertical-align:top}}
th{{background:#f1f5f9}}
tr.total-row{{background:#eff6ff;font-weight:600}}
code{{font-size:.78rem}}
{SORTABLE_TH_CSS}
</style></head><body>
<h1>RS ImprovePriority {HINT_STAMP} → gold-65 A/B</h1>
<p class="muted">Hints from <code>RS_ImprovePriority_{HINT_STAMP}.html</code> (short-hold univ report).
<strong>Control / runs = gold-65 production</strong> <code>run_rs.bat</code>
(stop 0.85 / target 1.25 / time_stop=252 / cd=60, stamp <code>{html.escape(stamp_src)}</code>,
{n_sym} symbols). Param/pattern levers are not universe-specific — gold-65 is the
production decision baseline. One knob per arm; ≤2 alts per hypothesis
(<code>docs/HYPOTHESIS_TEST.md</code>). Metrics follow
<code>CANONICAL_COMPARE_METRICS.md</code>. Click column headers to sort.</p>
<p class="muted">Output: <code>drive/paul_experiments/rs_improve_prio_260808_ab/</code>.
Prior matching expand65 / slow_hold stamps reused; only missing stop-expand arms re-run.</p>
<p class="muted">Lean: <strong>adopt?</strong> = candidate · <strong>hold</strong> = mixed/tradeoff ·
<strong>dismiss</strong> = clear regression · <strong>noop</strong> = no effect
(e.g. post_target bars=15 under cd=60 — skipped).</p>

<h2>Results vs control</h2>
<table class="sortable"><thead><tr>{ths}</tr></thead>
<tbody>
{''.join(body_rows)}
</tbody></table>

<h2>Hypotheses (from ImprovePriority {HINT_STAMP})</h2>
<table class="sortable"><thead><tr>
{sortable_th('Arm','text')}{sortable_th('Hypothesis','text')}{sortable_th('Suggestion','text')}{sortable_th('Note','text')}
</tr></thead><tbody>
{''.join(hyp_rows)}
</tbody></table>

<p class="muted">Lean is automated triage only — adopt needs PO sign-off + ToS + re-baseline.</p>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    html_path = out_root / "comparison.html"
    html_path.write_text(html_doc, encoding="utf-8")

    md = [
        f"# RS ImprovePriority {HINT_STAMP} → gold-65 A/B",
        "",
        f"Hints: `RS_ImprovePriority_{HINT_STAMP}.html` (short-hold univ). "
        f"**Control:** gold-65 stamp `{stamp_src}` (stop 0.85 / target 1.25 / time_stop=252 / cd=60).",
        "",
        "| Arm | Knob | Trades | WR% | Ann_ROR | Sheet_PnL | Total_PNL | Max_DD | PF | FIT_R | Δ PnL | Δ ROR | Δ DD | Lean | Why |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for r in rows:
        m = r.get("metrics") or {}
        if r.get("skip"):
            md.append(
                f"| `{r['arm']}` | skip | — | — | — | — | — | — | — | — | — | — | — | "
                f"**{r.get('lean')}** | {r.get('lean_why')} |"
            )
            continue
        d_pnl = float(m.get("pnl", 0)) - float(cm.get("pnl", 0)) if cm else 0.0
        d_ror = float(m.get("ann_ror", 0)) - float(cm.get("ann_ror", 0)) if cm else 0.0
        d_dd = float(m.get("max_dd", 0)) - float(cm.get("max_dd", 0)) if cm else 0.0
        md.append(
            f"| `{r['arm']}` | `{r.get('extras')}` | {fmt_i(m.get('trades'))} | {fmt(m.get('wr'))} | "
            f"{fmt(m.get('ann_ror'))} | {fmt(m.get('sheet_pnl'),0)} | {fmt(m.get('pnl'),0)} | "
            f"{fmt(m.get('max_dd'))} | {fmt(m.get('pf'))} | {fmt(m.get('fitr_mean'))} | "
            f"{fmt(d_pnl,0)} | {fmt(d_ror)} | {fmt(d_dd)} | **{r.get('lean')}** | {r.get('lean_why')} |"
        )
    md_path = out_root / "comparison.md"
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")

    hyp_md = [
        f"# HYPOTHESIS — RS ImprovePriority {HINT_STAMP}",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| System / prefix | RS |",
        f"| Hint stamp | {HINT_STAMP} (short-hold univ ImprovePriority) |",
        f"| Baseline stamp | {stamp_src} gold-65 production |",
        f"| Universe | drive/universes/RS_universe.csv ({n_sym}) |",
        "| Evidence | Parameter + taken-trade + peer cards from ImprovePriority HTML |",
        "| Process | One-knob hypothesis tests; not open optimization |",
        "",
        "See comparison.html for arms / lean / canonical metrics.",
        "",
    ]
    (out_root / "HYPOTHESIS.md").write_text("\n".join(hyp_md), encoding="utf-8")

    print(f"[rs_improve_prio_260808_ab] wrote {csv_path}")
    print(f"[rs_improve_prio_260808_ab] wrote {html_path}")
    print(f"[rs_improve_prio_260808_ab] wrote {md_path}")
    return html_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reuse-control", default=DEFAULT_CONTROL)
    ap.add_argument("--workers", type=int, default=int(os.environ.get("RS_WORKERS", "12")))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force-rerun", action="store_true", help="Ignore reuse stamps; re-run all")
    ap.add_argument("--only-new", action="store_true", help="Only arms without reuse_stamp (+ control)")
    args = ap.parse_args()

    reuse = (args.reuse_control or DEFAULT_CONTROL).strip()
    symbols = os.environ.get("RS_SYMBOLS", "").strip() or load_universe_symbols()
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    py = _resolve_python()
    arms = build_arms()
    # Patch control reuse stamp from CLI
    for a in arms:
        if a.is_control:
            a.reuse_stamp = reuse
            a.reuse_src_dir = DRIVE
    if args.only_new:
        arms = [a for a in arms if a.is_control or a.skip or not a.reuse_stamp]

    print(f"[rs_improve_prio_260808_ab] hint_stamp={HINT_STAMP} control={reuse}")
    print(f"[rs_improve_prio_260808_ab] symbols={len(symbols.split(','))} out={out_root}")
    if args.dry_run:
        for a in arms:
            if a.skip:
                print(f"  {a.arm_id}: SKIP {a.skip_reason}")
            elif a.reuse_stamp and not args.force_rerun:
                print(f"  {a.arm_id}: REUSE {a.reuse_stamp} {' '.join(a.extras) or '(control)'}")
            else:
                print(f"  {a.arm_id}: RUN {' '.join(a.extras) or '(control)'}")
        return 0

    results: list[dict[str, Any]] = []
    for i, arm in enumerate(arms, 1):
        print(f"\n========== [{i}/{len(arms)}] {arm.arm_id} ==========")
        r = run_arm(
            py=py,
            arm=arm,
            out_root=out_root,
            drive_out=DRIVE,
            workers=args.workers,
            symbols=symbols,
            force_rerun=args.force_rerun,
        )
        results.append(r)
        m = r.get("metrics") or {}
        if r.get("skip"):
            print(f"  SKIP: {r.get('skip_reason')}")
        else:
            print(
                f"  stamp={r.get('stamp')} trades={m.get('trades')} "
                f"PNL={m.get('pnl')} DD={m.get('max_dd')} "
                f"note={r.get('note')} ok={r.get('ok')}"
            )

    # If --only-new, still need full comparison: re-load all arms (reuse)
    if args.only_new:
        print("\n[rs_improve_prio_260808_ab] assembling full arm set for comparison…")
        full: list[dict[str, Any]] = []
        by_id = {r["arm"]: r for r in results}
        for arm in build_arms():
            if arm.is_control:
                arm.reuse_stamp = reuse
                arm.reuse_src_dir = DRIVE
            if arm.arm_id in by_id and by_id[arm.arm_id].get("ok"):
                full.append(by_id[arm.arm_id])
                continue
            # Prefer newly written arm dir, else reuse
            r = run_arm(
                py=py,
                arm=arm,
                out_root=out_root,
                drive_out=DRIVE,
                workers=args.workers,
                symbols=symbols,
                force_rerun=False,
            )
            full.append(r)
        results = full

    write_comparison(out_root, results, stamp_src=reuse, symbols=symbols)
    fails = sum(
        1 for r in results if not r.get("skip") and not r.get("ok") and not r.get("is_control")
    )
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
