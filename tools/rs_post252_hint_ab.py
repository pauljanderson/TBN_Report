#!/usr/bin/env python3
"""RS post-TIME=252 ImprovePriority / pattern A/B suite.

Control = production run_rs.bat (time_stop_days=252, stop 0.88, target 1.25,
spy_int + cd=60). One knob (or coherent gate) per arm; <=2 alts per hypothesis.
See docs/HYPOTHESIS_TEST.md.

Usage (repo root)::

  python tools/rs_post252_hint_ab.py --reuse-control 260807114545
  run_rs_post252_hint_ab.bat
  run_rs_post252_hint_ab.bat 260807114545
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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
SA = REPO / "stock_analysis"
DATA_DIR = REPO / "data" / "newdata" / "data"
DRIVE = REPO / "drive"
DEFAULT_OUT = DRIVE / "paul_experiments" / "rs_post252_hint_ab"
DEFAULT_CONTROL = "260807114545"

# Production BASE matching run_rs.bat after TIME=252 adopt
RS_BASE_V = [
    "rs_mode=true",
    "brt_zones=false",
    "yh_zones=false",
    "wpbr_zones=false",
    "rl_mode=false",
    "target_pct=1.25",
    "stop_pct=0.88",
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
    family: str  # param | pattern | skip
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
    """Arms from ImproveHints 260807114545 — one knob / coherent gate each."""
    return [
        Arm(
            "00_control",
            "baseline_run_rs_time252",
            "param",
            "Production run_rs.bat: time_stop=252, stop 0.88, target 1.25, spy_int + cd=60.",
            is_control=True,
        ),
        # Parameter suggestions
        Arm(
            "01_target_expand_130",
            "target_pct_tension_expand",
            "param",
            "Mixed target card expand lens: TARGET exits that continued higher — widen target to 1.30.",
            ["target_pct=1.30"],
        ),
        Arm(
            "02_target_contract_120",
            "target_pct_tension_contract",
            "param",
            "Mixed target card contract lens: near-miss then STOP/TIME — closer target 1.20.",
            ["target_pct=1.20"],
        ),
        Arm(
            "03_stop_contract_090",
            "stop_pct_tension_contract_fat_stops",
            "param",
            "Stop tension lean contract + fat_stops tighter stop: 0.90 (higher mult = tighter).",
            ["stop_pct=0.90"],
        ),
        Arm(
            "04_stop_expand_085",
            "stop_pct_tension_expand",
            "param",
            "Stop tension expand lens (wick-through rebound): widen stop to 0.85.",
            ["stop_pct=0.85"],
        ),
        Arm(
            "05_band_pct_skip",
            "band_tighten_weak_fill",
            "skip",
            "band_pct / pivot proximity — not an RS entry lever (zones off).",
            skip=True,
            skip_reason="RS does not use band_pct; dismiss for this system",
        ),
        # Taken-trade patterns
        Arm(
            "06_fat_atr_days_45",
            "fat_stops_atr_time",
            "pattern",
            "fat_stops alt beyond tighter stop: atr_days=45 cut schedule (TIME=252 already on).",
            ["atr_days=45", "atr_progress=0"],
        ),
        Arm(
            "07_pt_none_15",
            "post_target_quick_stop",
            "pattern",
            "post_target_quick_stop: rl_post_target_reentry_bars=15 mode=none (TARGET-only CD).",
            [
                "rl_post_target_reentry_bars=15",
                "rl_post_target_reentry_mode=none",
            ],
        ),
        Arm(
            "08_pt_usma_15_03",
            "post_target_quick_stop_usma",
            "pattern",
            "post_target_quick_stop alt: bars=15 under_sma_limit 0.03.",
            [
                "rl_post_target_reentry_bars=15",
                "rl_post_target_reentry_mode=under_sma_limit",
                "rl_post_target_under_sma20=0.03",
            ],
        ),
        Arm(
            "09_false_growth_252",
            "false_start_2022_2023_growth",
            "pattern",
            "false_start regime proxy: growth_filter 252 bars.",
            ["growth_filter_enabled=true", "growth_bars=252"],
        ),
        Arm(
            "10_false_spy_int_exit",
            "false_start_2022_2023_spy_exit",
            "pattern",
            "false_start: exit when SPY IND_TC_INT turns Weak (entry gate already on).",
            ["exit_when_spy_int_turns_weak=true"],
        ),
    ]


def extract_metrics(outdir: Path) -> Optional[dict[str, Any]]:
    report = _latest(outdir, "RS_Audit_Report_*.csv") or _latest(outdir, "RS_Report_*.csv")
    if report is None:
        return None
    with report.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        row = next(csv.DictReader(f), None)
    if not row:
        return None
    trades = int(_safe_num(row.get("Total_Trades")))
    stamp = ""
    m = re.search(r"_(\d{12})\.csv$", report.name)
    if m:
        stamp = m.group(1)
    return {
        "ok": True,
        "stamp": stamp,
        "report": report.name,
        "trades": trades,
        "wr": _safe_num(row.get("Pct_Wins")),
        "avg_pnl_pct": _safe_num(row.get("Avg_PNL_Pct")),
        "ann_ror": _safe_num(row.get("Ann_ROR")),
        "avg_days": _safe_num(row.get("Avg_Days_Held")),
        "pnl": _safe_num(row.get("Total_PNL")),
        "max_dd": _safe_num(row.get("Max_DD")),
        "losing_streak": _safe_num(row.get("Losing_Streak")),
        "p90_days": _safe_num(row.get("P90_Days")),
        "brt_cash": _safe_num(row.get("brt_cash")),
        "max_pos": _safe_num(row.get("Max_Positions")),
        "pf": _safe_num(row.get("Profit_Factor")),
    }


def copy_stamp_artifacts(src_dir: Path, dest: Path, stamp: str) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in src_dir.glob(f"RS_*_{stamp}.*"):
        if p.is_file():
            shutil.copy2(p, dest / p.name)
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
    """Return (lean, why) vs control metrics."""
    if r.get("skip"):
        return "dismiss", r.get("skip_reason") or "not applicable"
    m = r.get("metrics") or {}
    if not m or not cm:
        return "hold", "no metrics"
    d_pnl = float(m.get("pnl", 0)) - float(cm.get("pnl", 0))
    d_dd = float(m.get("max_dd", 0)) - float(cm.get("max_dd", 0))
    d_ror = float(m.get("ann_ror", 0)) - float(cm.get("ann_ror", 0))
    d_wr = float(m.get("wr", 0)) - float(cm.get("wr", 0))
    # Soft adopt: material PnL lift without DD blow-up; dismiss clear regressions
    if d_pnl < -200_000:
        return "dismiss", f"PnL {d_pnl:+.0f} vs control (large $ regression; ignore ROR noise)"
    if d_pnl < -50_000 and d_ror <= 0:
        return "dismiss", f"PnL {d_pnl:+.0f} / Ann_ROR {d_ror:+.2f} vs control — worse"
    if d_pnl > 80_000 and d_dd <= 1.5 and d_ror >= 0:
        return "adopt?", f"PnL {d_pnl:+.0f}, Ann_ROR {d_ror:+.2f}, DD {d_dd:+.2f} — candidate (PO/ToS)"
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

    if arm.is_control and reuse_control_stamp:
        n = copy_stamp_artifacts(DRIVE, arm_dir, reuse_control_stamp)
        metrics = extract_metrics(arm_dir) or extract_metrics(DRIVE)
        if metrics and metrics.get("stamp") != reuse_control_stamp:
            # Prefer exact stamp from drive
            copy_stamp_artifacts(DRIVE, arm_dir, reuse_control_stamp)
            metrics = extract_metrics(arm_dir)
        result["ok"] = bool(metrics)
        result["metrics"] = metrics or {}
        result["stamp"] = reuse_control_stamp
        result["elapsed_s"] = 0.0
        result["note"] = f"reused drive stamp {reuse_control_stamp} ({n} files)"
        (arm_dir / "STAMP.txt").write_text(
            f"stamp={reuse_control_stamp}\narm={arm.arm_id}\nextra=(reuse)\n",
            encoding="utf-8",
        )
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
    aud = _latest(drive_out, "RS_Audit_Report_*.csv")
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

    # CSV
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
        "ann_ror",
        "avg_days",
        "pnl",
        "max_dd",
        "losing_streak",
        "p90_days",
        "brt_cash",
        "max_pos",
        "d_pnl",
        "d_trades",
        "d_wr",
        "d_ann_ror",
        "d_max_dd",
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
                    "ann_ror": m.get("ann_ror"),
                    "avg_days": m.get("avg_days"),
                    "pnl": m.get("pnl"),
                    "max_dd": m.get("max_dd"),
                    "losing_streak": m.get("losing_streak"),
                    "p90_days": m.get("p90_days"),
                    "brt_cash": m.get("brt_cash"),
                    "max_pos": m.get("max_pos"),
                    "d_pnl": (float(m.get("pnl", 0)) - float(cm.get("pnl", 0))) if cm else "",
                    "d_trades": (int(m.get("trades", 0)) - int(cm.get("trades", 0))) if cm else "",
                    "d_wr": (float(m.get("wr", 0)) - float(cm.get("wr", 0))) if cm else "",
                    "d_ann_ror": (float(m.get("ann_ror", 0)) - float(cm.get("ann_ror", 0))) if cm else "",
                    "d_max_dd": (float(m.get("max_dd", 0)) - float(cm.get("max_dd", 0))) if cm else "",
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
            sortable_th("Ann_ROR", "num"),
            sortable_th("AvgDays", "num"),
            sortable_th("Total_PNL", "num"),
            sortable_th("Max_DD", "num"),
            sortable_th("LoseStreak", "num"),
            sortable_th("P90", "num"),
            sortable_th("brt_cash", "num"),
            sortable_th("MaxPos", "num"),
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
                f"<td colspan='16'>{html.escape(r.get('skip_reason') or 'skipped')}</td>"
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
        body_rows.append(
            f"<tr class='{cls}'>"
            f"<td>{html.escape(r['arm'])}</td>"
            f"<td>{html.escape(str(r.get('family','')))}</td>"
            f"<td><code>{html.escape(str(r.get('extras','')))}</code></td>"
            f"<td>{html.escape(str(r.get('stamp', m.get('stamp',''))))}</td>"
            f"<td>{fmt_i(m.get('trades'))}</td>"
            f"<td>{fmt(m.get('wr'), 2)}</td>"
            f"<td>{fmt(m.get('avg_pnl_pct'), 2)}</td>"
            f"<td>{fmt(m.get('ann_ror'), 2)}</td>"
            f"<td>{fmt(m.get('avg_days'), 1)}</td>"
            f"<td>{fmt(m.get('pnl'), 0)}</td>"
            f"<td>{fmt(m.get('max_dd'), 2)}</td>"
            f"<td>{fmt_i(m.get('losing_streak'))}</td>"
            f"<td>{fmt(m.get('p90_days'), 0)}</td>"
            f"<td>{fmt(m.get('brt_cash'), 0)}</td>"
            f"<td>{fmt_i(m.get('max_pos'))}</td>"
            f"<td>{fmt(d_pnl, 0)}</td>"
            f"<td>{fmt(d_ror, 2)}</td>"
            f"<td>{fmt(d_dd, 2)}</td>"
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
            "</tr>"
        )

    html_doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>RS post-252 ImprovePriority A/B</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:1.5rem;color:#0f172a;background:#f8fafc}}
h1{{font-size:1.4rem;margin:0 0 .4rem}}
.muted{{color:#64748b;font-size:.92rem}}
table.sortable{{border-collapse:collapse;width:100%;background:#fff;margin:1rem 0;font-size:.85rem}}
th,td{{border:1px solid #e2e8f0;padding:.35rem .5rem;text-align:left;vertical-align:top}}
th{{background:#f1f5f9}}
tr.total-row{{background:#eff6ff;font-weight:600}}
code{{font-size:.8rem}}
{SORTABLE_TH_CSS}
</style></head><body>
<h1>RS post-TIME=252 ImprovePriority / pattern A/B</h1>
<p class="muted">Control = production <code>run_rs.bat</code> with <code>time_stop_days=252</code>
(stamp <code>{html.escape(stamp_src)}</code>). Universe: RS_universe.csv
({html.escape(str(len(symbols.split(','))))} symbols). One knob / coherent gate per arm;
≤2 alts per hypothesis (<code>docs/HYPOTHESIS_TEST.md</code>). Click column headers to sort.</p>
<p class="muted">Output: <code>drive/paul_experiments/rs_post252_hint_ab/</code></p>

<h2>Results vs control</h2>
<table class="sortable"><thead><tr>{ths}</tr></thead>
<tbody>
{''.join(body_rows)}
</tbody></table>

<h2>Hypotheses (from ImproveHints)</h2>
<table class="sortable"><thead><tr>
{sortable_th('Arm','text')}{sortable_th('Hypothesis','text')}{sortable_th('Suggestion','text')}
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
        "# RS post-TIME=252 ImprovePriority / pattern A/B",
        "",
        f"Control stamp `{stamp_src}`. Universe `{symbols}`.",
        "",
        "| Arm | Knob | Trades | WR% | Avg% | Ann_ROR | AvgDays | Total_PNL | Max_DD | LoseStreak | P90 | brt_cash | MaxPos | Lean | Why |",
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
        md.append(
            f"| `{r['arm']}` | `{r.get('extras')}` | {fmt_i(m.get('trades'))} | {fmt(m.get('wr'))} | "
            f"{fmt(m.get('avg_pnl_pct'))} | {fmt(m.get('ann_ror'))} | {fmt(m.get('avg_days'),1)} | "
            f"{fmt(m.get('pnl'),0)} | {fmt(m.get('max_dd'))} | {fmt_i(m.get('losing_streak'))} | "
            f"{fmt(m.get('p90_days'),0)} | {fmt(m.get('brt_cash'),0)} | {fmt_i(m.get('max_pos'))} | "
            f"**{r.get('lean')}** | {r.get('lean_why')} |"
        )
        _ = d_pnl
    md_path = out_root / "comparison.md"
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"[rs_post252_hint_ab] wrote {csv_path}")
    print(f"[rs_post252_hint_ab] wrote {html_path}")
    print(f"[rs_post252_hint_ab] wrote {md_path}")
    return html_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stamp", default="", help="ImproveHints / control stamp")
    ap.add_argument("--reuse-control", default="", help="Reuse drive RS stamp for 00_control")
    ap.add_argument("--workers", type=int, default=int(os.environ.get("RS_WORKERS", "12")))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--smoke", action="store_true", help="control only")
    args = ap.parse_args()

    stamp = (args.stamp or args.reuse_control or DEFAULT_CONTROL).strip()
    reuse = (args.reuse_control or stamp).strip()
    symbols = os.environ.get("RS_SYMBOLS", "").strip() or load_universe_symbols()
    if args.smoke:
        symbols = ",".join(symbols.split(",")[:3])
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    py = _resolve_python()
    arms = build_arms()
    if args.smoke:
        arms = [a for a in arms if a.is_control or a.skip][:2]

    print(f"[rs_post252_hint_ab] control_stamp={reuse} workers={args.workers}")
    print(f"[rs_post252_hint_ab] symbols={len(symbols.split(','))} out={out_root}")
    if args.dry_run:
        for a in arms:
            print(f"  {a.arm_id}: {'SKIP '+a.skip_reason if a.skip else ' '.join(a.extras) or '(control)'}")
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
            print(f"  SKIP: {r.get('skip_reason')}")
        else:
            print(
                f"  stamp={r.get('stamp')} trades={m.get('trades')} "
                f"PNL={m.get('pnl')} DD={m.get('max_dd')} ok={r.get('ok')}"
            )

    write_comparison(out_root, results, stamp_src=reuse, symbols=symbols)
    fails = sum(1 for r in results if not r.get("skip") and not r.get("ok") and not r.get("is_control"))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
