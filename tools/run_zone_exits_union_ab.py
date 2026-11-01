#!/usr/bin/env python3
"""Zone-exits union A/B: static vs own-zone vs union-zone inventory (+ RR gates).

Hypothesis (phase 2): does a *union* of BRT+YH+WPBR+VEC matured zone DNA as
target/stop beat production static knobs — or beat each system's own-zone exits?

Arms per system:
  control | zone_exits (own) | zone_union | zone_union_rr2 | zone_union_rr3 | zone_union_rr4

Reuses phase-1 stamps under ``zone_exits_ab/runs/`` for control + own-zone when present.

Usage (repo root)::

  python tools/run_zone_exits_union_ab.py
  python tools/run_zone_exits_union_ab.py --systems BRT,YH,WPBR,MTS --jobs 2
  python tools/run_zone_exits_union_ab.py --skip-existing
  run_zone_exits_union_ab.bat

Writes under ``drive/paul_experiments/zone_exits_union_ab/``.
"""
from __future__ import annotations

import argparse
import csv
import html
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
SA = REPO / "stock_analysis"
DATA_DIR = REPO / "data" / "newdata" / "data"
DRIVE = REPO / "drive"
OUT_ROOT = DRIVE / "paul_experiments" / "zone_exits_union_ab"
PHASE1_ROOT = DRIVE / "paul_experiments" / "zone_exits_ab"
ENGINE = SA / "rocket_tbn.py"

sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(OUT_ROOT.parent))
from davey_experiment_common import (  # noqa: E402
    Arm,
    extract_metrics,
    resolve_python,
    safe_num,
)
from compare_format import format_money, format_money_delta  # noqa: E402

MARKTEN = "AAPL,AMZN,GOOGL,META,MSFT,NVDA,TSLA,AU,AMD,NFLX"

# Production-parity commons (mirror run_zone_exits_ab / run_*.bat).
SYSTEM_COMMON: dict[str, tuple[str, ...]] = {
    "BRT": (
        "brt_zones=true",
        "yh_zones=false",
        "wpbr_zones=false",
        "vec_zones=false",
        "stop_pct=0.934",
        "target_pct=1.21",
        "too_high_multiplier=0",
        "band_pct=0.0154",
        "strong_pre_pivot_pct=0.1",
        "strong_post_pivot_pct=0.1",
        "strong_pre_pivot_bars=7",
        "strong_post_pivot_bars=7",
        "breakout_bars=100",
        "tight_range_threshold_pct=0.35",
        "tight_range_lookback=105",
        "sheet_breakout_scan_start_row_delta=2",
        "brt_sheet_touch=true",
        "min_spy_compare_1y_at_trigger=-1000",
        "sheet_red_to_green_entry_enabled=true",
        "sheet_dw_countif_include_prior_bar_date=false",
        "growth_filter_enabled=true",
        "min_ind_score=-1",
        "compute_beta=true",
        "min_pivot_run_h_before_entry=0",
        "min_beta_at_trigger=0",
        "max_market_cap=0",
        "min_market_cap=0",
        "liquidate_at_end=true",
    ),
    "YH": (
        "yh_zones=true",
        "brt_zones=false",
        "wpbr_zones=false",
        "rl_mode=false",
        "band_pct=0.015",
        "yh_move_away_pct=0.03",
        "yh_lookback=252",
        "yh_memory_mode=sheet",
        "strong_pre_pivot_bars=7",
        "strong_pre_pivot_pct=0.12",
        "strong_post_pivot_bars=7",
        "strong_post_pivot_pct=0.109",
        "strong_pivot_mode=off",
        "target_pct=1.21",
        "stop_pct=0.934",
        "stop_pct_is_multiplier=true",
        "stop_compare_round_decimals=-1",
        "too_high_multiplier=0",
        "max_spy_compare_1y_at_trigger=0",
        "min_spy_compare_1y_at_trigger=0",
        "min_atr_pct_at_trigger=0",
        "max_atr_pct_at_trigger=0",
        "max_market_cap=0",
        "min_market_cap=0",
        "growth_filter_enabled=true",
        "growth_bars=756",
        "use_indicators=false",
        "indicator_buy=off",
        "ind_score_weights_path=",
        "min_ind_score=0",
        "liquidate_at_end=true",
    ),
    "WPBR": (
        "wpbr_zones=true",
        "brt_zones=false",
        "yh_zones=false",
        "vec_zones=false",
        "band_pct=0.015",
        "strong_pre_pivot_bars=3",
        "strong_pre_pivot_pct=0.10",
        "strong_post_pivot_bars=3",
        "strong_post_pivot_pct=0.10",
        "strong_pivot_mode=either",
        "wpbr_breakout_confirmation=0.03",
        "wpbr_max_days_after_retest=2",
        "wpbr_second_chance_after_win=true",
        "growth_filter_enabled=false",
        "min_spy_compare_1y_at_trigger=-1000",
        "ind_score_weights_path=",
        "too_high_multiplier=0",
        "target_pct=1.22",
        "stop_pct=0.91",
        "sheet_no_entry_same_bar_after_exit=false",
        "use_indicators=true",
        "max_market_cap=0",
        "min_market_cap=0",
        "start_date=2016-01-01",
        "liquidate_at_end=true",
    ),
    "MTS": (
        "mts_mode=true",
        "band_pct=0.018",
        "touch_threshold=2",
        "strong_post_pivot_bars=7",
        "strong_post_pivot_pct=0.06",
        "strong_pre_pivot_bars=7",
        "strong_pre_pivot_pct=0.12",
        "target_pct=1.22",
        "stop_pct=0.934",
        "stop_pct_is_multiplier=true",
        "stop_loss_based=trigger_low",
        "min_upper_wick_atr_at_trigger=0.25",
        "min_dist_to_52w_high_pct_at_trigger=25",
        "symbol_reentry_cooldown_days=20",
        "liquidate_at_end=true",
    ),
}

ARMS: list[Arm] = [
    Arm("control", "Production static target%/stop%", ()),
    Arm("zone_exits", "Own-system nearest zone target/stop", ("zone_exits=true",)),
    Arm("zone_union", "Union BRT+YH+WPBR+VEC nearest zone target/stop", ("zone_exits_union=true",)),
    Arm("zone_union_rr2", "Union exits + RR>2", ("zone_exits_union=true", "zone_rr_min=2")),
    Arm("zone_union_rr3", "Union exits + RR>3", ("zone_exits_union=true", "zone_rr_min=3")),
    Arm("zone_union_rr4", "Union exits + RR>4", ("zone_exits_union=true", "zone_rr_min=4")),
]

ARM_ORDER = [a.id for a in ARMS]

# Map phase-1 job ids we can reuse without re-running.
PHASE1_REUSE = {
    "control": "control",
    "zone_exits": "zone_exits",
}

COMPARE_COLS: list[tuple[str, str, str]] = [
    ("Total_Trades", "Total trades", "int"),
    ("Pct_Wins", "Win %", "pct"),
    ("Total_PNL", "Total PnL $", "money"),
    ("Profit_Factor", "Profit factor", "num"),
    ("Ann_ROR", "Ann ROR %", "pct"),
    ("Max_DD", "Max DD %", "pct"),
    ("Profit_Per_Capital_Day", "Profit / capital day", "money"),
    ("Avg_Days_Held", "Avg days held", "num"),
    ("Median_Days_Held", "Median days held", "num"),
    ("Expectancy", "Expectancy $", "money"),
    ("Losing_Streak", "Losing streak", "int"),
    ("Aggressive_Total_PNL", "Aggressive Total PnL $", "money"),
    ("Aggressive_Max_DD", "Aggressive Max DD %", "pct"),
]

SORTABLE_TH_CSS = """
th.sortable-th{cursor:pointer;user-select:none;white-space:nowrap}
th.sortable-th:hover{background:#e8e8e0}
th.sortable-th .sort-ind{opacity:.45;margin-left:.25em;font-size:.85em}
th.sortable-th.sort-asc .sort-ind::after{content:"▲";opacity:1}
th.sortable-th.sort-desc .sort-ind::after{content:"▼";opacity:1}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.better{color:#166534;font-weight:600}
.worse{color:#991b1b}
.note{color:#64748b;font-size:.92em}
"""

SORTABLE_TABLE_SCRIPT = """
<script>
(function(){
  function parseCell(td, type){
    var t=(td.textContent||"").trim().replace(/[$,%+]/g,"").replace(/,/g,"");
    if(type==="num"||type==="date"||type==="month"){var n=parseFloat(t); return isNaN(n)?null:n;}
    return t.toLowerCase();
  }
  function bind(table){
    var ths=table.querySelectorAll("th.sortable-th");
    ths.forEach(function(th, colIdx){
      function activate(e){
        if(e && e.type==="touchend") e.preventDefault();
        var type=th.getAttribute("data-sort")||"text";
        var asc=!th.classList.contains("sort-asc");
        ths.forEach(function(x){x.classList.remove("sort-asc","sort-desc"); x.setAttribute("aria-sort","none");});
        th.classList.add(asc?"sort-asc":"sort-desc");
        th.setAttribute("aria-sort", asc?"ascending":"descending");
        var tbody=table.tBodies[0]; if(!tbody) return;
        var rows=[].slice.call(tbody.querySelectorAll("tr")).filter(function(r){return !r.classList.contains("total-row");});
        rows.sort(function(a,b){
          var av=parseCell(a.children[colIdx], type), bv=parseCell(b.children[colIdx], type);
          if(av==null&&bv==null) return 0;
          if(av==null) return 1; if(bv==null) return -1;
          if(av<bv) return asc?-1:1; if(av>bv) return asc?1:-1; return 0;
        });
        rows.forEach(function(r){tbody.appendChild(r);});
      }
      th.addEventListener("click", activate);
      th.addEventListener("keydown", function(e){ if(e.key==="Enter"||e.key===" "){e.preventDefault(); activate(e);} });
      th.addEventListener("touchend", activate, {passive:false});
    });
  }
  document.querySelectorAll("table.sortable").forEach(bind);
})();
</script>
"""


def sortable_th(label: str, sort_type: str = "num") -> str:
    return (
        f'<th class="sortable-th" data-sort="{html.escape(sort_type)}" '
        f'tabindex="0" role="columnheader" aria-sort="none">'
        f"{html.escape(label)}<span class=\"sort-ind\"></span></th>"
    )


def _exit_mix(closed: Optional[Path]) -> dict[str, int]:
    counts: dict[str, int] = {}
    if closed is None or not closed.is_file():
        return counts
    with closed.open(newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            cols = {k.upper(): k for k in row}
            key = cols.get("EXIT_TYPE") or cols.get("EXIT TYPE") or cols.get("EXIT")
            if not key:
                continue
            et = str(row.get(key, "") or "").strip().upper() or "UNKNOWN"
            counts[et] = counts.get(et, 0) + 1
    return counts


def _latest(outdir: Path, pattern: str) -> Optional[Path]:
    files = sorted(outdir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _prefix_for(system: str) -> str:
    return system.upper()


def _try_reuse_phase1(system: str, arm_id: str, outdir: Path) -> Optional[dict[str, Any]]:
    """Copy metrics from phase-1 control / own-zone stamps when available."""
    p1_arm = PHASE1_REUSE.get(arm_id)
    if not p1_arm:
        return None
    src = PHASE1_ROOT / "runs" / f"{system.lower()}__{p1_arm}"
    if not src.is_dir():
        return None
    prefix = _prefix_for(system)
    metrics = extract_metrics(src, prefix)
    if not metrics or safe_num(metrics.get("Total_Trades")) <= 0:
        return None
    outdir.mkdir(parents=True, exist_ok=True)
    # Lightweight pointer so compare paths stay under OUT_ROOT.
    note = outdir / "REUSED_FROM_PHASE1.txt"
    note.write_text(f"Reused metrics from {src}\n", encoding="utf-8")
    closed = _latest(src, f"{prefix}_Closed_*.csv")
    return {
        "system": system,
        "id": arm_id,
        "label": next((a.label for a in ARMS if a.id == arm_id), arm_id),
        "ok": True,
        "skipped": True,
        "reused_phase1": True,
        "metrics": metrics,
        "outdir": str(src),
        "exit_mix": _exit_mix(closed),
        "elapsed_s": 0.0,
    }


def run_one(
    *,
    system: str,
    arm: Arm,
    symbols: str,
    workers: int,
    skip_existing: bool,
    extra_v: list[str],
    reuse_phase1: bool,
) -> dict[str, Any]:
    prefix = _prefix_for(system)
    job_id = f"{system.lower()}__{arm.id}"
    outdir = OUT_ROOT / "runs" / job_id
    outdir.mkdir(parents=True, exist_ok=True)

    existing = extract_metrics(outdir, prefix)
    if skip_existing and existing and existing.get("Total_Trades", 0) > 0:
        closed = _latest(outdir, f"{prefix}_Closed_*.csv")
        return {
            "system": system,
            "id": arm.id,
            "label": arm.label,
            "ok": True,
            "skipped": True,
            "metrics": existing,
            "outdir": str(outdir),
            "exit_mix": _exit_mix(closed),
            "elapsed_s": 0.0,
        }

    if reuse_phase1 and arm.id in PHASE1_REUSE:
        reused = _try_reuse_phase1(system, arm.id, outdir)
        if reused:
            return reused

    common = list(SYSTEM_COMMON[system]) + list(extra_v)
    values = common + list(arm.values)
    cmd = [
        resolve_python(),
        str(ENGINE),
        str(DATA_DIR),
        "-o",
        str(outdir),
        "-w",
        str(workers),
        "--aggressive",
        "--use-duckdb",
        "--no-regression",
    ]
    if system == "MTS":
        cmd.append("--mts-sheet-parity")
    for v in values:
        cmd.extend(["-v", v])
    if symbols:
        cmd.extend(["-s", symbols])

    log = outdir / "run.log"
    t0 = time.time()
    with log.open("w", encoding="utf-8", errors="replace") as handle:
        handle.write("CMD: " + subprocess.list2cmdline(cmd) + "\n\n")
        handle.flush()
        proc = subprocess.run(cmd, cwd=str(REPO), stdout=handle, stderr=subprocess.STDOUT)
    metrics = extract_metrics(outdir, prefix) or {}
    closed = _latest(outdir, f"{prefix}_Closed_*.csv")
    ok = proc.returncode == 0 and bool(metrics)
    return {
        "system": system,
        "id": arm.id,
        "label": arm.label,
        "ok": ok,
        "skipped": False,
        "exit_code": proc.returncode,
        "elapsed_s": round(time.time() - t0, 1),
        "metrics": metrics,
        "outdir": str(outdir),
        "exit_mix": _exit_mix(closed),
        "error": "" if ok else f"see {log}",
    }


def _fmt_cell(fmt: str, value: Any) -> str:
    if value is None or value == "":
        return "—"
    n = safe_num(value)
    if fmt == "money":
        return format_money(n)
    if fmt == "pct":
        return f"{n:.2f}%"
    if fmt == "int":
        return str(int(round(n)))
    return f"{n:.3f}" if abs(n) < 10 else f"{n:.2f}"


def _delta_class(key: str, delta: float) -> str:
    lower_better = key in ("Max_DD", "Aggressive_Max_DD", "Losing_Streak", "Avg_Days_Held", "Median_Days_Held")
    if abs(delta) < 1e-12:
        return ""
    good = (delta < 0) if lower_better else (delta > 0)
    return "better" if good else "worse"


def recommend_r(rows: list[dict[str, Any]]) -> str:
    """Per-system best arm vs control on Ann_ROR then Total_PNL; aggregate vote."""
    by_sys: dict[str, list[dict]] = {}
    for r in rows:
        if not r.get("ok"):
            continue
        by_sys.setdefault(r["system"], []).append(r)
    votes: dict[str, int] = {aid: 0 for aid in ARM_ORDER}
    details: list[str] = []
    for sys, arms in sorted(by_sys.items()):
        by_id = {a["id"]: a for a in arms}
        ctrl = by_id.get("control")
        if not ctrl:
            continue
        c_ror = safe_num((ctrl.get("metrics") or {}).get("Ann_ROR"))
        c_pnl = safe_num((ctrl.get("metrics") or {}).get("Total_PNL"))
        best_id = "control"
        best_ror = c_ror
        best_pnl = c_pnl
        for aid in ARM_ORDER:
            if aid == "control":
                continue
            a = by_id.get(aid)
            if not a:
                continue
            m = a.get("metrics") or {}
            ror = safe_num(m.get("Ann_ROR"))
            pnl = safe_num(m.get("Total_PNL"))
            if (ror > best_ror + 1e-9) or (abs(ror - best_ror) < 1e-9 and pnl > best_pnl):
                best_id, best_ror, best_pnl = aid, ror, pnl
        votes[best_id] = votes.get(best_id, 0) + 1
        details.append(f"{sys}: best={best_id} (AnnROR={best_ror:.2f}, PnL={best_pnl:.0f})")
    # Prefer union / RR that beats control; else own-zone; else none.
    ranked = sorted(
        ((aid, votes.get(aid, 0)) for aid in ARM_ORDER if aid != "control"),
        key=lambda x: (-x[1], ARM_ORDER.index(x[0])),
    )
    top_id, top_votes = ranked[0] if ranked else ("control", 0)
    if top_votes > 0 and top_votes >= votes.get("control", 0):
        return f"{top_id} - {'; '.join(details)}"
    return f"none beat control - {'; '.join(details)}"


def write_html(rows: list[dict[str, Any]], path: Path, recommendation: str) -> None:
    systems = sorted({r["system"] for r in rows})
    sections: list[str] = []
    for system in systems:
        arms = {r["id"]: r for r in rows if r["system"] == system}
        ctrl = arms.get("control")
        ctrl_m = (ctrl or {}).get("metrics") or {}
        own = arms.get("zone_exits")
        own_m = (own or {}).get("metrics") or {}
        head = (
            "<tr>"
            + sortable_th("Arm", "text")
            + "".join(sortable_th(lab, "num") for _, lab, _ in COMPARE_COLS)
            + "".join(sortable_th(f"Δ vs ctrl {lab}", "num") for _, lab, _ in COMPARE_COLS)
            + "".join(sortable_th(f"Δ vs own {lab}", "num") for _, lab, _ in COMPARE_COLS)
            + "</tr>"
        )
        body_rows: list[str] = []
        for aid in ARM_ORDER:
            r = arms.get(aid)
            if not r:
                continue
            m = r.get("metrics") or {}
            cells = [f"<td>{html.escape(aid)}</td>"]
            for key, _lab, fmt in COMPARE_COLS:
                cells.append(f'<td class="num">{_fmt_cell(fmt, m.get(key))}</td>')
            for key, _lab, fmt in COMPARE_COLS:
                if not ctrl or aid == "control":
                    cells.append('<td class="num">—</td>')
                    continue
                d = safe_num(m.get(key)) - safe_num(ctrl_m.get(key))
                cls = _delta_class(key, d)
                if fmt == "money":
                    txt = format_money_delta(d)
                elif fmt == "pct":
                    txt = f"{d:+.2f}%"
                elif fmt == "int":
                    txt = f"{int(round(d)):+d}"
                else:
                    txt = f"{d:+.3f}"
                cells.append(f'<td class="num {cls}">{txt}</td>')
            for key, _lab, fmt in COMPARE_COLS:
                if not own or aid in ("control", "zone_exits"):
                    cells.append('<td class="num">—</td>')
                    continue
                d = safe_num(m.get(key)) - safe_num(own_m.get(key))
                cls = _delta_class(key, d)
                if fmt == "money":
                    txt = format_money_delta(d)
                elif fmt == "pct":
                    txt = f"{d:+.2f}%"
                elif fmt == "int":
                    txt = f"{int(round(d)):+d}"
                else:
                    txt = f"{d:+.3f}"
                cells.append(f'<td class="num {cls}">{txt}</td>')
            body_rows.append("<tr>" + "".join(cells) + "</tr>")
        mix_bits = []
        for aid in ARM_ORDER:
            r = arms.get(aid)
            if not r:
                continue
            mix = r.get("exit_mix") or {}
            if mix:
                parts = ", ".join(f"{k}={v}" for k, v in sorted(mix.items()))
                mix_bits.append(f"<li><code>{aid}</code>: {html.escape(parts)}</li>")
        sections.append(
            f"<h2>{html.escape(system)}</h2>"
            f'<p class="note">Click column headers to sort. Deltas vs control and vs own-zone.</p>'
            f'<table class="sortable"><thead>{head}</thead><tbody>'
            + "".join(body_rows)
            + "</tbody></table>"
            + ("<h3>Exit mix</h3><ul>" + "".join(mix_bits) + "</ul>" if mix_bits else "")
        )

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>Zone exits union A/B</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:24px;max-width:1600px;color:#1e293b}}
table{{border-collapse:collapse;width:100%;margin:12px 0 28px;font-size:12px}}
th,td{{border:1px solid #d4d4d4;padding:5px 7px}}
th{{background:#f4f4ef;text-align:left}}
h1{{margin-bottom:4px}}
{SORTABLE_TH_CSS}
</style></head><body>
<h1>Zone exits union A/B</h1>
<p>Control = static target%/stop%. Own = <code>-v zone_exits=true</code>.
Union = <code>-v zone_exits_union=true</code> (BRT+YH+WPBR+VEC DNA pool).
Optional <code>-v zone_rr_min</code> on union. Generated {html.escape(stamp)}.</p>
<p><strong>Recommendation:</strong> {html.escape(recommendation)}</p>
<p class="note">Decision log: <code>drive/paul_experiments/zone_exits_union_ab/DECISION_LOG.md</code></p>
<p class="note">Fallback: missing zone above/below → keep static target/stop. RR gate missing either side → skip trade.</p>
{"".join(sections)}
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    path.write_text(doc, encoding="utf-8")


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    fields = [
        "system",
        "id",
        "label",
        "ok",
        "skipped",
        "reused_phase1",
        "elapsed_s",
        "outdir",
        "error",
    ] + [k for k, _, _ in COMPARE_COLS]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            row = {k: r.get(k) for k in fields}
            m = r.get("metrics") or {}
            for k, _, _ in COMPARE_COLS:
                row[k] = m.get(k)
            w.writerow(row)


def write_decision_log(recommendation: str, rows: list[dict[str, Any]]) -> None:
    path = OUT_ROOT / "DECISION_LOG.md"
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# Zone exits union A/B — decision log",
        "",
        "**Hypothesis:** nearest matured zones from the *union* of BRT+YH+WPBR+VEC DNA may beat",
        "static target/stop (and/or each system's own-zone exits) when used as exit levels.",
        "",
        "See `docs/HYPOTHESIS_TEST.md`.",
        "",
        "## Flags",
        "",
        "| Knob | Behavior |",
        "|------|----------|",
        "| `-v zone_exits=true` | Own-system DNA nearest above=target / below=stop |",
        "| `-v zone_exits_union=true` or `-v zone_exits=union` | Union DNA pool for nearest target/stop (entry toggles unchanged) |",
        "| `-v zone_rr_min=R` | Entry gate on reward/risk from that inventory; missing side → skip |",
        "",
        "### Fallback",
        "",
        "- **zone_exits / zone_exits_union:** missing or wrong-side level → keep static target/stop; trade still taken.",
        "- **zone_rr_min>0:** missing either side → skip trade.",
        "",
        "## Arms",
        "",
        "| Arm | Knobs |",
        "|-----|-------|",
        "| control | Production static |",
        "| zone_exits | `zone_exits=true` (own) |",
        "| zone_union | `zone_exits_union=true` |",
        "| zone_union_rr2/3/4 | union + `zone_rr_min=2/3/4` |",
        "",
        f"## Run results ({stamp})",
        "",
        f"**Recommendation:** {recommendation}",
        "",
    ]
    for r in sorted(rows, key=lambda x: (x.get("system", ""), ARM_ORDER.index(x["id"]) if x.get("id") in ARM_ORDER else 99)):
        m = r.get("metrics") or {}
        reuse = " reused_p1" if r.get("reused_phase1") else ""
        lines.append(
            f"- `{r.get('system')}` / `{r.get('id')}`: ok={r.get('ok')}{reuse} "
            f"trades={int(safe_num(m.get('Total_Trades')))} "
            f"PnL={format_money(m.get('Total_PNL'))} AnnROR={safe_num(m.get('Ann_ROR')):.2f}% "
            f"PF={safe_num(m.get('Profit_Factor')):.2f} MaxDD={safe_num(m.get('Max_DD')):.2f}%"
        )
    lines.extend(
        [
            "",
            "## Paths",
            "",
            "- Runner: `tools/run_zone_exits_union_ab.py` / `run_zone_exits_union_ab.bat`",
            "- Compare: `drive/paul_experiments/zone_exits_union_ab/comparison.html`",
            "- Phase-1 own-zone: `drive/paul_experiments/zone_exits_ab/`",
            "",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Zone exits union A/B across zone systems")
    ap.add_argument("--systems", default="BRT,YH,WPBR,MTS", help="Comma list: BRT,YH,WPBR,MTS")
    ap.add_argument("--symbols", default=MARKTEN)
    ap.add_argument("--jobs", type=int, default=2, help="Parallel system×arm jobs")
    ap.add_argument("--workers", type=int, default=8, help="Engine -w per job")
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument("--no-reuse-phase1", action="store_true", help="Do not reuse zone_exits_ab control/own stamps")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--extra-v", action="append", default=[], help="Extra -v KEY=VALUE for all arms")
    ap.add_argument(
        "--arms",
        default="",
        help="Optional comma subset of arm ids (default: all)",
    )
    args = ap.parse_args()

    systems = [s.strip().upper() for s in args.systems.split(",") if s.strip()]
    for s in systems:
        if s not in SYSTEM_COMMON:
            print(f"Unknown system {s}; choose from {sorted(SYSTEM_COMMON)}", file=sys.stderr)
            return 2

    arms = list(ARMS)
    if args.arms.strip():
        want = {a.strip() for a in args.arms.split(",") if a.strip()}
        arms = [a for a in ARMS if a.id in want]
        if not arms:
            print(f"No arms matched {want}", file=sys.stderr)
            return 2

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    (OUT_ROOT / "runs").mkdir(parents=True, exist_ok=True)

    specs: list[tuple[str, Arm]] = [(s, a) for s in systems for a in arms]
    if args.dry_run:
        for s, a in specs:
            print(f"DRY {s} {a.id}: {list(a.values)}")
        return 0

    results: list[dict[str, Any]] = []
    jobs = max(1, int(args.jobs))
    reuse_p1 = not bool(args.no_reuse_phase1)
    print(
        f"[zone_exits_union_ab] systems={systems} arms={len(arms)} jobs={jobs} "
        f"symbols={args.symbols} reuse_phase1={reuse_p1}",
        flush=True,
    )

    def _submit(sys_name: str, arm: Arm) -> dict[str, Any]:
        return run_one(
            system=sys_name,
            arm=arm,
            symbols=args.symbols,
            workers=int(args.workers),
            skip_existing=bool(args.skip_existing),
            extra_v=list(args.extra_v or []),
            reuse_phase1=reuse_p1,
        )

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futs = [pool.submit(_submit, s, a) for s, a in specs]
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r)
            m = r.get("metrics") or {}
            print(
                f"[{r['system']}:{r['id']}] ok={r['ok']} skip={r.get('skipped')} "
                f"reuse={r.get('reused_phase1')} "
                f"trades={int(safe_num(m.get('Total_Trades')))} "
                f"pnl={safe_num(m.get('Total_PNL')):.0f} "
                f"ann={safe_num(m.get('Ann_ROR')):.2f} "
                f"elapsed={r.get('elapsed_s')}s",
                flush=True,
            )

    recommendation = recommend_r(results)
    write_csv(results, OUT_ROOT / "comparison.csv")
    write_html(results, OUT_ROOT / "comparison.html", recommendation)
    write_decision_log(recommendation, results)
    (OUT_ROOT / "README.md").write_text(
        "\n".join(
            [
                "# Zone exits union A/B",
                "",
                "See `DECISION_LOG.md` for flags, arms, and fallback policy.",
                "",
                f"**Recommendation:** {recommendation}",
                "",
                "Artifacts:",
                "- `comparison.html` (sortable)",
                "- `comparison.csv`",
                "- `runs/<system>__<arm>/`",
                "",
                "Re-run: `python tools/run_zone_exits_union_ab.py` or `run_zone_exits_union_ab.bat`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"[zone_exits_union_ab] recommendation: {recommendation}", flush=True)
    print(f"[zone_exits_union_ab] wrote {OUT_ROOT / 'comparison.html'}", flush=True)
    return 0 if all(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
