#!/usr/bin/env python3
"""SB ImprovePriority / ImproveHints A/B suite (gold-56 production).

Control = production ``run_sb.bat`` / ``run_stockbee_burst.bat``:
  target_pct=1.097, burst_max_risk_pct=0.078, time_stop=5, no_ft=3,
  MM/vol research gates OFF, gold-56 ``drive/universes/SB_universe.csv``.

One knob (or coherent skip) per arm; ≤2 alts per hypothesis.
See ``docs/HYPOTHESIS_TEST.md`` and ``drive/paul_experiments/CANONICAL_COMPARE_METRICS.md``.

Usage (repo root)::

  python tools/sb_hint_ab.py --reuse-control 260807184031
  run_sb_hint_ab.bat
  run_sb_hint_ab.bat 260807184031
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
    / "stockbee_momentum_burst"
    / "ab_improve_hints"
)
DEFAULT_CONTROL = "260807184031"

# Production BASE matching run_stockbee_burst.bat (gold-56 @ 1.097/0.078).
SB_BASE_V = [
    "sb_mode=true",
    "brt_zones=false",
    "yh_zones=false",
    "wpbr_zones=false",
    "rl_mode=false",
    "relative_strength_enabled=false",
    "rs_mode=false",
    "mvcp_mode=false",
    "indicator_buy=off",
    "target_pct=1.097",
    "burst_time_stop_days=5",
    "burst_no_ft_days=3",
    "burst_max_risk_pct=0.078",
    "burst_size_from_stop=false",
    "burst_risk_frac=0.01",
    "max_positions=0",
    "burst_min_pct=0.04",
    "burst_dcr_min=0.70",
    "burst_range_lookback=5",
    "burst_vol_gt_prior=true",
    "burst_fill=next_open",
    "burst_mm_gate=false",
    "burst_max_prior_up_days=1",
    "burst_min_price=5",
    "burst_vol_vs_avg_mult=0",
    "burst_min_atr_pct_at_trigger=0",
    "burst_max_atr_pct_at_trigger=0",
    "symbol_reentry_cooldown_days=0",
    "rl_post_target_reentry_bars=0",
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
    univ = DRIVE / "universes" / "SB_universe.csv"
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
        raise SystemExit("empty SB_universe.csv")
    return ",".join(syms)


def build_arms() -> list[Arm]:
    """Arms from ImproveHints 260807184031 — one knob / coherent skip each."""
    return [
        Arm(
            "00_control",
            "baseline_run_sb_gold56",
            "param",
            "Production run_sb.bat: target 1.097, burst_max_risk 0.078, "
            "time_stop=5, no_ft=3, MM/vol OFF, gold-56.",
            is_control=True,
        ),
        # Parameter suggestions (ImprovePriority tension cards)
        Arm(
            "01_band_tighten_070",
            "band_pct_tension_tighten",
            "param",
            "Mixed band card lean tighten: shrink fill band via "
            "burst_max_risk_pct=0.070 (prod 0.078).",
            ["burst_max_risk_pct=0.070"],
        ),
        Arm(
            "02_band_loosen_090",
            "band_pct_tension_loosen",
            "param",
            "Mixed band opposing loosen lens: widen TOO_HIGH gate via "
            "burst_max_risk_pct=0.090.",
            ["burst_max_risk_pct=0.090"],
        ),
        Arm(
            "03_target_contract_108",
            "target_pct_tension_contract",
            "param",
            "Mixed target card lean contract: closer target_pct=1.08 (prod 1.097).",
            ["target_pct=1.08"],
        ),
        Arm(
            "04_target_expand_112",
            "target_pct_tension_expand",
            "param",
            "Mixed target opposing expand lens: target_pct=1.12.",
            ["target_pct=1.12"],
        ),
        Arm(
            "05_stop_pct_skip",
            "stop_pct_tension_expand_vs_hold",
            "skip",
            "stop_pct tension / peer wider-stop — SB stop is signal_low (LOD), "
            "not stop_pct multiplier.",
            skip=True,
            skip_reason=(
                "N/A: SB DNA stop = signal LOD; host stop_pct is unwired in "
                "rocket_stockbee_burst. Dismiss for this system (use band/max_risk "
                "or filters, not stop_pct)."
            ),
        ),
        # Taken-trade patterns
        Arm(
            "06_false_start_2024",
            "false_start_2022_2023",
            "pattern",
            "false_start_2022_2023: SB-wired regime cut entry_start_date=2024-01-01 "
            "(drops 2022–2023 STOP cluster; tradeoff: fewer early bull entries).",
            ["entry_start_date=2024-01-01"],
        ),
        Arm(
            "07_post_target_skip",
            "post_target_quick_stop",
            "skip",
            "post_target_quick_stop: rl_post_target_reentry_* / "
            "symbol_reentry_cooldown_days are host gates; SB burst path does not "
            "apply them (production already bars=0 / cd=0).",
            skip=True,
            skip_reason=(
                "N/A: SB uses dedicated burst engine (run_sb_from_brt_main); "
                "rl_post_target_reentry_* and symbol_reentry_cooldown_days are not "
                "checked on burst fills. Not a noop-under-cd=60 case (SB cd=0) — "
                "knobs simply do not bind. Needs SB-native reentry gate if pursued."
            ),
        ),
        Arm(
            "08_peer_wider_stop_skip",
            "peer_wider_stop_won_brt",
            "skip",
            "peer_learn wider stop (BRT/MVCP/RS/MTS) — same LOD geometry limit.",
            skip=True,
            skip_reason=(
                "N/A / dismiss: cannot widen SB stop via stop_pct; LOD stop is DNA. "
                "Peer overlaps are countable but not an SB -v lever."
            ),
        ),
        Arm(
            "09_mm_vol_already_dismissed",
            "prior_mm_vol_research",
            "skip",
            "Prior suites ab_mm_2lynch / ab_vol_ratio — gates lost; stay OFF.",
            skip=True,
            skip_reason=(
                "Already dismissed: MM / vol-ratio research gates lost vs gold-56 "
                "control; production burst_mm_gate=false, burst_vol_vs_avg_mult=0. "
                "Do not re-run."
            ),
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


def extract_metrics(outdir: Path) -> Optional[dict[str, Any]]:
    report = _latest(outdir, "SB_Audit_Report_*.csv") or _latest(outdir, "SB_Report_*.csv")
    if report is None:
        return None
    with report.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        row = next(csv.DictReader(f), None)
    if not row:
        return None
    stamp = ""
    m = re.search(r"_(\d{12})\.csv$", report.name)
    if m:
        stamp = m.group(1)
    closed = outdir / f"SB_Closed_{stamp}.csv" if stamp else _latest(outdir, "SB_Closed_*.csv")
    summary = outdir / f"SB_Summary_{stamp}.csv" if stamp else _latest(outdir, "SB_Summary_*.csv")
    emeta = outdir / f"SB_EquityMeta_{stamp}.csv" if stamp else _latest(outdir, "SB_EquityMeta_*.csv")
    mix = _exit_mix(closed) if closed else {}
    sag = _summary_aggs(summary) if summary else {}
    max_days_uw = 0.0
    pct_days_uw = 0.0
    if emeta and emeta.is_file():
        with emeta.open(newline="", encoding="utf-8-sig", errors="replace") as f:
            er = next(csv.DictReader(f), None) or {}
        max_days_uw = _safe_num(er.get("Max_Days_Underwater"))
        pct_days_uw = _safe_num(str(er.get("Pct_Days_Underwater", "")).replace("%", ""))
    trades = int(_safe_num(row.get("Total_Trades")))
    n_target = int(mix.get("TARGET", 0))
    n_stop = int(mix.get("STOP_LOSS", 0)) + int(mix.get("GAP_DOWN", 0))
    n_time = int(mix.get("TIME", 0))
    n_noft = int(mix.get("NO_FT", 0))
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
        "ann_ror": _safe_num(row.get("Ann_ROR")),
        "avg_days": _safe_num(row.get("Avg_Days_Held")),
        "median_days": _safe_num(row.get("Median_Days_Held")),
        "p90_days": _safe_num(row.get("P90_Days")),
        "pnl": _safe_num(row.get("Total_PNL")),
        "sheet_pnl": _safe_num(row.get("sheet_PnL") or row.get("Sheet_PNL")),
        "max_dd": _safe_num(row.get("Max_DD")),
        "pf": _safe_num(row.get("Profit_Factor")),
        "expectancy": _safe_num(row.get("Expectancy")),
        "expectancy_pct": _safe_num(row.get("Expectancy_Pct")),
        "avg_win_pct": _safe_num(row.get("Avg_Win_Pct")),
        "capital_days": _safe_num(row.get("Capital_Days")),
        "profit_per_cd": _safe_num(row.get("Profit_Per_Capital_Day")),
        "losing_streak": _safe_num(row.get("Losing_Streak")),
        "avg_pos": _safe_num(row.get("Avg_Positions")),
        "max_pos": _safe_num(row.get("Max_Positions")),
        "agg_pnl": _safe_num(row.get("Aggressive_Total_PNL")),
        "agg_dd": _safe_num(row.get("Aggressive_Max_DD")),
        "brt_cash": _safe_num(row.get("brt_cash")),
        "pct_max_sym": _safe_num(row.get("Pct_PNL_Max_Symbol")),
        "pct_max_trade": _safe_num(row.get("Pct_PNL_Max_Trade")),
        "max_days_uw": max_days_uw,
        "pct_days_uw": pct_days_uw,
        "exit_target": n_target,
        "exit_stop": n_stop,
        "exit_time": n_time,
        "exit_noft": n_noft,
        "exit_target_pct": (100.0 * n_target / trades) if trades else 0.0,
        "exit_stop_pct": (100.0 * n_stop / trades) if trades else 0.0,
        **sag,
    }


def copy_stamp_artifacts(src_dir: Path, dest: Path, stamp: str) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in src_dir.glob(f"SB_*_{stamp}.*"):
        if p.is_file():
            shutil.copy2(p, dest / p.name)
            n += 1
    return n


def build_cmd(py: str, outdir: Path, workers: int, symbols: str, extras: list[str]) -> list[str]:
    vs = list(SB_BASE_V)
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
    cmd.extend(["-s", symbols])
    return cmd


def lean_decision(r: dict[str, Any], cm: dict[str, Any]) -> tuple[str, str]:
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
        return "dismiss", f"PnL {d_pnl:+.0f} / Ann_ROR {d_ror:+.2f} — worse"
    if d_pnl > 80_000 and d_dd <= 1.5 and d_ror >= 0:
        return (
            "adopt?",
            f"PnL {d_pnl:+.0f}, Ann_ROR {d_ror:+.2f}, DD {d_dd:+.2f}, "
            f"robustFIT {d_fit_r:+.2f} — candidate (PO/ToS; do not adopt yet)",
        )
    if abs(d_pnl) < 40_000 and abs(d_ror) < 0.8 and abs(d_dd) < 0.8:
        return "hold", f"flat vs control (PnL {d_pnl:+.0f}, ROR {d_ror:+.2f}, DD {d_dd:+.2f})"
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

    # Prefer existing arm folder stamp if identical knobs already on disk
    existing = arm_dir / "STAMP.txt"
    if existing.is_file() and not os.environ.get("SB_HINT_FORCE_RERUN"):
        prev = ""
        for line in existing.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("stamp="):
                prev = line.split("=", 1)[1].strip()
        if prev and (arm_dir / f"SB_Report_{prev}.csv").is_file():
            metrics = extract_metrics(arm_dir)
            if metrics:
                result["ok"] = True
                result["metrics"] = metrics
                result["stamp"] = prev
                result["elapsed_s"] = 0.0
                result["note"] = f"reused existing arm stamp {prev}"
                return result

    cmd = build_cmd(py, drive_out, workers, symbols, arm.extras)
    log_path = arm_dir / "run.log"
    t0 = time.time()
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write("CMD: " + " ".join(cmd) + "\n\n")
        log.flush()
        proc = subprocess.run(cmd, cwd=str(REPO), stdout=log, stderr=subprocess.STDOUT)
    elapsed = time.time() - t0
    stamp = ""
    aud = _latest(drive_out, "SB_Audit_Report_*.csv") or _latest(drive_out, "SB_Report_*.csv")
    if aud:
        m = re.search(r"_(\d{12})\.csv$", aud.name)
        if m:
            stamp = m.group(1)
    n_copy = copy_stamp_artifacts(drive_out, arm_dir, stamp) if stamp else 0
    metrics = extract_metrics(arm_dir) if stamp else None
    result["ok"] = proc.returncode == 0 and metrics is not None
    result["exit_code"] = proc.returncode
    result["elapsed_s"] = elapsed
    result["stamp"] = stamp
    result["metrics"] = metrics or {}
    result["note"] = f"copied {n_copy} files" if n_copy else "no mirror"
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
        "capital_days",
        "profit_per_cd",
        "losing_streak",
        "mean_fit_robust",
        "mean_paul",
        "exit_target_pct",
        "exit_stop_pct",
        "d_pnl",
        "d_trades",
        "d_wr",
        "d_ann_ror",
        "d_max_dd",
        "d_sheet_pnl",
        "d_fit_robust",
        "lean",
        "lean_why",
        "suggestion",
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
                    "capital_days": m.get("capital_days"),
                    "profit_per_cd": m.get("profit_per_cd"),
                    "losing_streak": m.get("losing_streak"),
                    "mean_fit_robust": m.get("mean_fit_robust"),
                    "mean_paul": m.get("mean_paul"),
                    "exit_target_pct": m.get("exit_target_pct"),
                    "exit_stop_pct": m.get("exit_stop_pct"),
                    "d_pnl": (float(m.get("pnl", 0)) - float(cm.get("pnl", 0))) if cm else "",
                    "d_trades": (int(m.get("trades", 0)) - int(cm.get("trades", 0))) if cm else "",
                    "d_wr": (float(m.get("wr", 0)) - float(cm.get("wr", 0))) if cm else "",
                    "d_ann_ror": (float(m.get("ann_ror", 0)) - float(cm.get("ann_ror", 0))) if cm else "",
                    "d_max_dd": (float(m.get("max_dd", 0)) - float(cm.get("max_dd", 0))) if cm else "",
                    "d_sheet_pnl": (
                        (float(m.get("sheet_pnl", 0)) - float(cm.get("sheet_pnl", 0))) if cm else ""
                    ),
                    "d_fit_robust": (
                        (float(m.get("mean_fit_robust", 0)) - float(cm.get("mean_fit_robust", 0)))
                        if cm
                        else ""
                    ),
                    "lean": r.get("lean"),
                    "lean_why": r.get("lean_why"),
                    "suggestion": r.get("suggestion"),
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
            sortable_th("TARGET%", "num"),
            sortable_th("STOP%", "num"),
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
            f"<td>{fmt(m.get('pnl'), 0)}</td>"
            f"<td>{fmt(m.get('sheet_pnl'), 0)}</td>"
            f"<td>{fmt(m.get('max_dd'), 2)}</td>"
            f"<td>{fmt(m.get('pf'), 2)}</td>"
            f"<td>{fmt(m.get('capital_days'), 0)}</td>"
            f"<td>{fmt(m.get('profit_per_cd'), 1)}</td>"
            f"<td>{fmt(m.get('mean_fit_robust'), 2)}</td>"
            f"<td>{fmt(m.get('exit_target_pct'), 1)}</td>"
            f"<td>{fmt(m.get('exit_stop_pct'), 1)}</td>"
            f"<td>{fmt(d_pnl, 0)}</td>"
            f"<td>{fmt(d_ror, 2)}</td>"
            f"<td>{fmt(d_dd, 2)}</td>"
            f"<td{lean_cls}><strong>{html.escape(lean)}</strong></td>"
            f"<td>{html.escape(str(r.get('lean_why','')))}</td>"
            f"</tr>"
        )

    # Canonical deep table (control vs each runnable arm)
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
        ("Profit per capital day", "profit_per_cd", "num", False),
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
        ("EXIT TARGET %", "exit_target_pct", "pct", False),
        ("EXIT STOP %", "exit_stop_pct", "pct", False),
        ("EXIT TIME count", "exit_time", "num", False),
        ("EXIT NO_FT count", "exit_noft", "num", False),
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
                cells.append(f"<td>{fmt(v, 0)}</td>")
            elif kind == "pct":
                cells.append(f"<td>{fmt(v, 2)}</td>")
            else:
                cells.append(f"<td>{fmt(v, 2 if abs(v) < 1000 else 0)}</td>")
            if not r.get("is_control") and cm:
                d = v - cval
                if abs(d) > 1e-9:
                    better = (d < 0) if lower_better else (d > 0)
                    if better and best_note == "—":
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

    n_sym = len(symbols.split(",")) if symbols else 0
    html_doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>SB gold-56 ImprovePriority A/B</title>
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
<h1>SB gold-56 ImprovePriority / ImproveHints A/B</h1>
<p class="muted">Control = production <code>run_sb.bat</code> (target 1.097 /
<code>burst_max_risk_pct=0.078</code>, time_stop=5, no_ft=3, MM/vol OFF,
stamp <code>{html.escape(stamp_src)}</code>). Universe: SB_universe.csv ({n_sym} symbols).
One knob / coherent skip per arm; ≤2 alts per hypothesis
(<code>docs/HYPOTHESIS_TEST.md</code>). Click column headers to sort.</p>
<p class="muted">Output: <code>drive/paul_experiments/tbn_new_systems/stockbee_momentum_burst/ab_improve_hints/</code>
· Canonical metrics: <code>CANONICAL_COMPARE_METRICS.md</code>.</p>
<p class="muted">Lean: <strong>adopt?</strong> = candidate (PO/ToS; do not ship) ·
<strong>hold</strong> = mixed/tradeoff · <strong>dismiss</strong> = regression or N/A ·
<strong>noop</strong> = no book effect.</p>

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

<h2>Hypotheses (from ImproveHints)</h2>
<table class="sortable"><thead><tr>
{sortable_th('Arm','text')}{sortable_th('Hypothesis','text')}{sortable_th('Suggestion','text')}{sortable_th('Lean','text')}
</tr></thead><tbody>
{''.join(hyp_rows)}
</tbody></table>

<p class="muted">Lean is automated triage only — adopt needs PO sign-off + ToS + re-baseline.
<strong>Recommendation default: keep production</strong> unless an arm shows clear
adopt? with trade-diff + ToS confirmation.</p>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    html_path = out_root / "comparison.html"
    html_path.write_text(html_doc, encoding="utf-8")

    md = [
        "# SB gold-56 ImprovePriority / ImproveHints A/B",
        "",
        f"Control stamp `{stamp_src}` (target 1.097 / max_risk 0.078 / time=5). "
        f"Universe `{n_sym}` symbols.",
        "",
        "| Arm | Knob | Trades | WR% | Avg% | Ann_ROR | Sheet_PNL | Total_PNL | Max_DD | PF | MeanFIT_R | Lean | Why |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for r in rows:
        m = r.get("metrics") or {}
        if r.get("skip"):
            md.append(
                f"| `{r['arm']}` | skip | — | — | — | — | — | — | — | — | — | "
                f"**{r.get('lean')}** | {r.get('lean_why')} |"
            )
            continue
        md.append(
            f"| `{r['arm']}` | `{r.get('extras')}` | {fmt_i(m.get('trades'))} | {fmt(m.get('wr'))} | "
            f"{fmt(m.get('avg_pnl_pct'))} | {fmt(m.get('ann_ror'))} | {fmt(m.get('sheet_pnl'),0)} | "
            f"{fmt(m.get('pnl'),0)} | {fmt(m.get('max_dd'))} | {fmt(m.get('pf'))} | "
            f"{fmt(m.get('mean_fit_robust'))} | **{r.get('lean')}** | {r.get('lean_why')} |"
        )
    md.extend(
        [
            "",
            "## Decision (default)",
            "",
            "- **Keep production** (freeze `260803184014` / LatestRun control knobs) unless an arm is `adopt?` with trade-diff + ToS.",
            "- Skipped N/A: stop_pct, post_target/cooldown host gates, peer wider-stop, prior MM/vol.",
            "",
        ]
    )
    md_path = out_root / "comparison.md"
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")

    readme = out_root / "README.md"
    readme.write_text(
        "\n".join(
            [
                "# SB ImproveHints A/B (gold-56)",
                "",
                "Hypothesis tests from `SB_ImproveHints_260807184031` — not open optimization.",
                "",
                "- Driver: `tools/sb_hint_ab.py`",
                "- Bat: `run_sb_hint_ab.bat` / `SB_ImprovePriority_ab.bat`",
                "- Control: production `run_sb.bat` knobs; reuse LatestRun stamp when possible",
                "- Reports: `comparison.html` / `.csv` / `.md`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"[sb_hint_ab] wrote {csv_path}")
    print(f"[sb_hint_ab] wrote {html_path}")
    print(f"[sb_hint_ab] wrote {md_path}")
    return html_path


def patch_improve_priority(
    stamp: str,
    out_root: Path,
    rows: list[dict[str, Any]],
) -> Optional[Path]:
    prio = DRIVE / f"SB_ImprovePriority_{stamp}.html"
    if not prio.is_file():
        return None
    text = prio.read_text(encoding="utf-8", errors="replace")
    # strip prior strip
    text = re.sub(
        r'<div class="ab-strip".*?</div>\s*',
        "",
        text,
        count=1,
        flags=re.DOTALL,
    )
    rel = os.path.relpath(out_root / "comparison.html", DRIVE).replace("\\", "/")
    bat = f"run_sb_hint_ab.bat {stamp}"
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
    <span class="muted"> — one knob / skip per arm vs gold-56 production.
    Results: <a href="{html.escape(rel)}">comparison.html</a>
    · re-run <code>{html.escape(bat)}</code></span>
    <p class="muted" style="margin:.4rem 0 0">Default: <strong>keep production</strong>. Do not adopt without PO + ToS.</p>
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
    # insert after <body> or first <h1>
    if "<body>" in text:
        text = text.replace("<body>", "<body>\n" + block, 1)
    else:
        text = block + text
    prio.write_text(text, encoding="utf-8")
    print(f"[sb_hint_ab] patched {prio.name}")
    return prio


def ensure_improve_priority(stamp: str, py: str) -> Path:
    prio = DRIVE / f"SB_ImprovePriority_{stamp}.html"
    if prio.is_file():
        return prio
    print(f"[sb_hint_ab] generating ImprovePriority for {stamp} (--no-charts)...")
    cmd = [
        py,
        str(SA / "post_run_analysis.py"),
        "--system",
        "SB",
        "--stamp",
        stamp,
        "--no-charts",
        "-o",
        str(DRIVE),
    ]
    proc = subprocess.run(cmd, cwd=str(REPO))
    if proc.returncode != 0 or not prio.is_file():
        raise SystemExit(f"Failed to write {prio} (exit={proc.returncode})")
    return prio


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stamp", default="", help="ImproveHints / control stamp")
    ap.add_argument("--reuse-control", default="", help="Reuse drive SB stamp for 00_control")
    ap.add_argument("--workers", type=int, default=int(os.environ.get("SB_WORKERS", "5")))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--smoke", action="store_true", help="control + skips only")
    ap.add_argument(
        "--skip-priority",
        action="store_true",
        help="Do not generate/patch ImprovePriority HTML",
    )
    args = ap.parse_args()

    stamp = (args.stamp or args.reuse_control or DEFAULT_CONTROL).strip()
    reuse = (args.reuse_control or stamp).strip()
    symbols = os.environ.get("SB_SYMBOLS", "").strip() or load_universe_symbols()
    if args.smoke:
        symbols = ",".join(symbols.split(",")[:3])
    out_root = Path(args.out)
    if not out_root.is_absolute():
        out_root = REPO / out_root
    out_root.mkdir(parents=True, exist_ok=True)
    py = _resolve_python()

    if not args.skip_priority:
        ensure_improve_priority(stamp, py)

    arms = build_arms()
    if args.smoke:
        arms = [a for a in arms if a.is_control or a.skip]

    print(f"[sb_hint_ab] control_stamp={reuse} workers={args.workers}")
    print(f"[sb_hint_ab] symbols={len(symbols.split(','))} out={out_root}")
    if args.dry_run:
        for a in arms:
            print(
                f"  {a.arm_id}: "
                f"{'SKIP '+a.skip_reason if a.skip else ' '.join(a.extras) or '(control)'}"
            )
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
            reuse_control_stamp=reuse if arm.is_control else "",
        )
        results.append(r)
        m = r.get("metrics") or {}
        if r.get("skip"):
            print(f"  SKIP: {r.get('skip_reason')[:120]}")
        else:
            print(
                f"  stamp={r.get('stamp')} trades={m.get('trades')} "
                f"PNL={m.get('pnl')} DD={m.get('max_dd')} "
                f"elapsed={r.get('elapsed_s', 0):.0f}s ok={r.get('ok')} note={r.get('note')}"
            )

    write_comparison(out_root, results, stamp_src=reuse, symbols=symbols)
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
