#!/usr/bin/env python3
"""Sweep RS ATR-based exits (atr_target × atr_stop) vs fixed target_pct/stop_pct.

Semantics (rocket_brt BRTConfig / entry path):
  ATR_PCT_AT_ENTRY = ATR14[entry_bar] / entry_price * 100   (percent of price)
  atr_target = N  →  long target = entry * (1 + ATR_PCT * N / 100)  = entry + N×ATR
  atr_stop   = M  →  long stop   = entry * (1 - ATR_PCT * M / 100)  = entry − M×ATR
  atr_* = 0 falls back to target_pct / stop_pct (multiplier form when stop_pct_is_multiplier).

Universe: curated 55 (run_rs.bat). O'Neil filters off. min_spy_compare_1y_at_trigger=0.
Fixed control: target_pct=1.25, stop_pct=0.88.

Outputs: drive/paul_experiments/rs_atr_exits/
"""
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
SA = REPO / "stock_analysis"
for p in (REPO, SA):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

OUT_ROOT = REPO / "drive" / "paul_experiments" / "rs_atr_exits"
DATA_DIR = REPO / "data" / "newdata" / "data"

RS_SYMBOLS = (
    "TRV,WELL,CTAS,CASY,AFL,BDX,CW,CB,BSX,CPRT,AJG,HWM,NVDA,TJX,FISV,PRI,MCD,,"
    "MCK,POOL,FICO,V,QQQ,ENSG,DHR,UNH,DECK,RELX,RBC,ORLY,MSCI,ROP,CAH,ADBE,BRO,MCO,"
    "COST,NFLX,BBIO,POWL,BR,LOGI,TMO,FIX,AER,CHTR,PGR,LII,EME,TDY,ETR,AXSM,SYK,AVGO,WST"
)
TARGET_PCT = 1.25
STOP_PCT = 0.88

# Shared RS gates (parity with run_rs.bat / prior davey RS sweeps).
BASE_V = [
    "rs_mode=true",
    "brt_zones=false",
    "yh_zones=false",
    "wpbr_zones=false",
    "rl_mode=false",
    "stop_pct_is_multiplier=true",
    "use_indicators=true",
    "indicator_buy=off",
    "rs_require_tc_strong=true",
    "growth_filter_enabled=false",
    "min_spy_compare_1y_at_trigger=0",
    "too_high_multiplier=0",
    "rs_max_pct_below_52w_high=0",
    "rs_spy_int_tc_not_weak=false",
    "min_atr_pct_at_trigger=0",
    "max_atr_pct_at_trigger=0",
    "atr_target=0",
    "atr_stop=0",
]

# ATR multiples of ATR14 at entry (not percent). Median ATR%≈2.5 →
# atr_target=10 ≈ +25% (fixed target), atr_stop=5 ≈ −12.5% (fixed stop).
ATR_TARGET_GRID = [2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]
ATR_STOP_GRID = [1.5, 2.0, 2.5, 3.0, 4.0, 5.0]

# Extra fixed (target_pct, stop_pct multiplier) arms for cheap comparison.
FIXED_EXTRA = [
    (1.15, 0.88),
    (1.20, 0.90),
    (1.25, 0.90),
    (1.30, 0.85),
    (1.40, 0.88),
]


def _resolve_python() -> str:
    env_py = os.environ.get("PY", "").strip()
    if env_py and Path(env_py).is_file():
        return env_py
    for p in (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Python/Python310/python.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Python/Python311/python.exe",
    ):
        if p.is_file():
            return str(p)
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


def _find_latest(outdir: Path, pattern: str) -> Optional[Path]:
    files = sorted(outdir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _tag(val: float) -> str:
    s = f"{val:.4f}".rstrip("0").rstrip(".")
    return s.replace(".", "p")


def extract_metrics(outdir: Path) -> Optional[dict]:
    report = _find_latest(outdir, "RS_Report_*.csv")
    if report is None:
        report = _find_latest(outdir, "RS_Audit_Report_*.csv")
    if report is None:
        report = _find_latest(outdir, "BRT_Report_*.csv")
    if report is None:
        return None
    with open(report, newline="", encoding="utf-8", errors="replace") as f:
        row = next(csv.DictReader(f), None)
    if not row:
        return None
    wins = int(_safe_num(row.get("Wins", 0)))
    losses = int(_safe_num(row.get("Losses", 0)))
    bes = int(_safe_num(row.get("BE", row.get("BEs", 0))))
    total_trades = int(_safe_num(row.get("Total_Trades", 0)))
    if total_trades <= 0:
        total_trades = wins + losses + bes
    wr = (100.0 * wins / total_trades) if total_trades else 0.0
    return {
        "report": str(report.name),
        "trades": total_trades,
        "wins": wins,
        "losses": losses,
        "wr": wr,
        "pf": _safe_num(row.get("Profit_Factor", 0)),
        "pnl": _safe_num(row.get("Total_PNL", 0)),
        "maxdd": _safe_num(row.get("Max_DD", 0)),
        "expectancy": _safe_num(row.get("Expectancy", row.get("Expectancy_Pct", 0))),
        "avg_days_held": _safe_num(row.get("Avg_Days_Held", 0)),
        "ann_ror": _safe_num(row.get("Ann_ROR", 0)),
    }


def run_one(
    *,
    label: str,
    outdir: Path,
    extra_v: list[str],
    py: str,
    workers: int,
) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    cmd = [
        py,
        str(SA / "rocket_brt.py"),
        str(DATA_DIR),
        "-o",
        str(outdir),
        "-w",
        str(workers),
        "--no-regression",
        "--relative-strength",
        "-s",
        RS_SYMBOLS,
    ]
    for v in BASE_V + extra_v:
        cmd.extend(["-v", v])
    t0 = time.perf_counter()
    log_path = outdir / "run.log"
    print(f"[run] {label} -> {outdir.name}", flush=True)
    with open(log_path, "w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.run(cmd, cwd=str(REPO), stdout=log, stderr=subprocess.STDOUT)
    elapsed = time.perf_counter() - t0
    metrics = extract_metrics(outdir) or {}
    row = {
        "label": label,
        "outdir": str(outdir),
        "exit_code": proc.returncode,
        "elapsed_s": round(elapsed, 1),
        **metrics,
        "extra_v": ";".join(extra_v),
    }
    print(
        f"[done] {label} exit={proc.returncode} {elapsed:.0f}s "
        f"trades={row.get('trades', '?')} WR={row.get('wr', '?')} "
        f"PF={row.get('pf', '?')} PNL={row.get('pnl', '?')} "
        f"MaxDD={row.get('maxdd', '?')} days={row.get('avg_days_held', '?')}",
        flush=True,
    )
    return row


def _score(row: dict) -> float:
    trades = float(row.get("trades") or 0)
    pf = float(row.get("pf") or 0)
    pnl = float(row.get("pnl") or 0)
    if trades < 50:
        return -1e18
    return pf * 1e9 + pnl


def _beats_baseline(cand: Optional[dict], baseline: Optional[dict]) -> bool:
    if not cand or not baseline:
        return False
    b_pf = float(baseline.get("pf") or 0)
    b_pnl = float(baseline.get("pnl") or 0)
    b_dd = abs(float(baseline.get("maxdd") or 0))
    c_pf = float(cand.get("pf") or 0)
    c_pnl = float(cand.get("pnl") or 0)
    c_dd = abs(float(cand.get("maxdd") or 0))
    if c_pf <= b_pf:
        return False
    if b_pnl > 0 and c_pnl < 0.85 * b_pnl:
        return False
    if b_dd > 0 and c_dd > 1.15 * b_dd:
        return False
    return True


def write_results_md(out_root: Path, rows: list[dict], recommendations: dict) -> Path:
    path = out_root / "RESULTS.md"

    def _tbl(title: str, subset: list[dict], limit: Optional[int] = None) -> list[str]:
        lines = [
            f"## {title}",
            "",
            "| Label | Trades | WR% | PF | PNL | MaxDD | Expectancy | AvgDays |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        ordered = sorted(subset, key=_score, reverse=True)
        if limit is not None:
            ordered = ordered[:limit]
        for r in ordered:
            lines.append(
                f"| {r.get('label', '')} | {r.get('trades', '')} | {r.get('wr', 0):.1f} | "
                f"{r.get('pf', 0):.3f} | {r.get('pnl', 0):.0f} | {r.get('maxdd', 0):.2f} | "
                f"{r.get('expectancy', 0):.4f} | {r.get('avg_days_held', 0):.1f} |"
            )
        lines.append("")
        return lines

    baseline = next((r for r in rows if r["label"] == "fixed_1p25_0p88"), None)
    atr_rows = [r for r in rows if r["label"].startswith("atr_")]
    fixed_rows = [r for r in rows if r["label"].startswith("fixed_")]

    lines = [
        "# RS ATR exits optimization (atr_target × atr_stop)",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "Universe: curated 55 (`run_rs.bat`). O'Neil filters off. `min_spy_compare_1y_at_trigger=0`.",
        "",
        "## Flag semantics",
        "",
        "- `ATR_PCT_AT_ENTRY` = ATR14 / entry_price × 100 (percent of price at entry bar).",
        "- `atr_target=N` → long target = `entry × (1 + ATR_PCT × N / 100)` = **+N × ATR** from entry.",
        "- `atr_stop=M` → long stop = `entry × (1 - ATR_PCT × M / 100)` = **−M × ATR** from entry.",
        "- `atr_*=0` → use fixed `target_pct` / `stop_pct` (multiplier when `stop_pct_is_multiplier=true`).",
        "- Units: **ATR multiples** (not percent). Example: ATR%=2.5 and atr_target=4 → +10% target.",
        "",
        "Approx map to fixed 1.25/0.88 at median ATR%~2.5: atr_target≈10 (+25%), atr_stop≈5 (−12.5%).",
        "",
    ]
    if baseline:
        lines.extend(_tbl("Fixed control (target=1.25, stop=0.88)", [baseline]))
    lines.extend(_tbl("Fixed extras", [r for r in fixed_rows if r["label"] != "fixed_1p25_0p88"]))
    lines.extend(_tbl("ATR grid (all)", atr_rows))
    lines.extend(_tbl("ATR grid (top 15 by PF then PNL)", atr_rows, limit=15))
    lines.extend(
        [
            "## Recommendations",
            "",
            f"- **Best ATR pair:** `{recommendations.get('best_atr')}`",
            f"- **Best fixed:** `{recommendations.get('best_fixed')}`",
            f"- **Verdict:** {recommendations.get('verdict')}",
            "",
            f"Rationale: {recommendations.get('notes', '')}",
            "",
            "Artifacts: per-run folders; `summary.csv`.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def build_jobs(arm: str) -> list[tuple[str, Path, list[str]]]:
    jobs: list[tuple[str, Path, list[str]]] = []

    if arm in ("all", "fixed"):
        label = "fixed_1p25_0p88"
        jobs.append(
            (
                label,
                OUT_ROOT / label,
                [
                    f"target_pct={TARGET_PCT}",
                    f"stop_pct={STOP_PCT}",
                    "atr_target=0",
                    "atr_stop=0",
                ],
            )
        )
        for t, s in FIXED_EXTRA:
            lab = f"fixed_{_tag(t)}_{_tag(s)}"
            jobs.append(
                (
                    lab,
                    OUT_ROOT / lab,
                    [
                        f"target_pct={t}",
                        f"stop_pct={s}",
                        "atr_target=0",
                        "atr_stop=0",
                    ],
                )
            )

    if arm in ("all", "atr"):
        for at in ATR_TARGET_GRID:
            for ast in ATR_STOP_GRID:
                lab = f"atr_t{_tag(at)}_s{_tag(ast)}"
                jobs.append(
                    (
                        lab,
                        OUT_ROOT / lab,
                        [
                            # Keep fixed values present but unused when atr_*>0.
                            f"target_pct={TARGET_PCT}",
                            f"stop_pct={STOP_PCT}",
                            f"atr_target={at}",
                            f"atr_stop={ast}",
                        ],
                    )
                )
    return jobs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workers", type=int, default=8, help="rocket_brt -w per run")
    ap.add_argument("--parallel-runs", type=int, default=4, help="Concurrent RS jobs")
    ap.add_argument("--arm", choices=["all", "fixed", "atr"], default="all")
    args = ap.parse_args()

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    py = _resolve_python()
    jobs = build_jobs(args.arm)
    print(f"[plan] {len(jobs)} arms -> {OUT_ROOT}", flush=True)

    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, args.parallel_runs)) as pool:
        futs = {
            pool.submit(
                run_one, label=lab, outdir=od, extra_v=ev, py=py, workers=args.workers
            ): lab
            for lab, od, ev in jobs
        }
        for fut in as_completed(futs):
            rows.append(fut.result())

    rows.sort(key=lambda r: r.get("label", ""))
    sum_path = OUT_ROOT / "summary.csv"
    fields = [
        "label",
        "trades",
        "wr",
        "pf",
        "pnl",
        "maxdd",
        "expectancy",
        "avg_days_held",
        "ann_ror",
        "exit_code",
        "elapsed_s",
        "extra_v",
        "report",
        "outdir",
    ]
    with open(sum_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

    def _best(subset: list[dict]) -> Optional[dict]:
        ok = [
            r
            for r in subset
            if int(r.get("exit_code", 1)) == 0 and r.get("trades") is not None
        ]
        return max(ok, key=_score) if ok else None

    baseline = next((r for r in rows if r["label"] == "fixed_1p25_0p88"), None)
    best_atr = _best([r for r in rows if r["label"].startswith("atr_")])
    best_fixed = _best([r for r in rows if r["label"].startswith("fixed_")])

    # Prefer control unless ATR clearly wins the PF+PNL+MaxDD guard with a material edge.
    # Wider fixed arms can post higher PF with much worse MaxDD — do not auto-prefer them.
    verdict = "mixed / near-parity — keep fixed 1.25/0.88 for RS production"
    if best_atr and baseline and _beats_baseline(best_atr, baseline):
        a_pf = float(best_atr.get("pf") or 0)
        b_pf = float(baseline.get("pf") or 0)
        a_pnl = float(best_atr.get("pnl") or 0)
        b_pnl = float(baseline.get("pnl") or 0)
        if a_pf >= b_pf + 0.25 and a_pnl >= 1.05 * b_pnl:
            verdict = f"ATR better — prefer {best_atr['label']} over fixed 1.25/0.88"
        else:
            verdict = (
                f"mixed / near-parity — best ATR {best_atr['label']} slightly beats control "
                "but keep fixed 1.25/0.88 for simplicity"
            )
    elif best_atr and baseline:
        b_pf = float(baseline.get("pf") or 0)
        a_pf = float(best_atr.get("pf") or 0)
        if a_pf > b_pf:
            verdict = (
                f"marginal — best ATR {best_atr['label']} raises PF but fails PNL/MaxDD guard; "
                "keep fixed 1.25/0.88 for production"
            )
        elif a_pf < b_pf * 0.95:
            verdict = "worse — ATR exits underperform fixed; keep target_pct=1.25 / stop_pct=0.88"
        else:
            verdict = "mixed — ATR near parity with fixed; keep fixed 1.25/0.88 for simplicity"

    notes = (
        f"baseline PF={baseline.get('pf') if baseline else 'n/a'} "
        f"PNL={baseline.get('pnl') if baseline else 'n/a'} "
        f"MaxDD={baseline.get('maxdd') if baseline else 'n/a'} "
        f"days={baseline.get('avg_days_held') if baseline else 'n/a'}; "
        f"best_atr={best_atr['label'] if best_atr else 'n/a'} "
        f"PF={best_atr.get('pf') if best_atr else 'n/a'} "
        f"PNL={best_atr.get('pnl') if best_atr else 'n/a'} "
        f"MaxDD={best_atr.get('maxdd') if best_atr else 'n/a'} "
        f"days={best_atr.get('avg_days_held') if best_atr else 'n/a'}; "
        f"best_fixed={best_fixed['label'] if best_fixed else 'n/a'} "
        f"PF={best_fixed.get('pf') if best_fixed else 'n/a'}."
    )
    recs = {
        "best_atr": best_atr["label"] if best_atr else "n/a",
        "best_fixed": best_fixed["label"] if best_fixed else "n/a",
        "verdict": verdict,
        "notes": notes,
    }
    write_results_md(OUT_ROOT, rows, recs)
    print(f"[summary] {sum_path}", flush=True)
    print(f"[recs] {recs}", flush=True)
    return 0 if all(int(r.get("exit_code", 1)) == 0 for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
