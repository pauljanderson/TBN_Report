#!/usr/bin/env python3
"""Sweep RS ATR_PCT_AT_TRIGGER min/max filters on curated 55 (run_rs.bat parity).

Uses existing engine flags (0 = off):
  -v min_atr_pct_at_trigger=X   # ATR14/close*100 on trigger bar T
  -v max_atr_pct_at_trigger=Y

Grid from Closed_260723221911 distribution (n≈963):
  P10=1.42, P25=1.80, P50=2.52, P75=3.50, P90=5.18 (+ a few absolutes).

Outputs: drive/paul_experiments/rs_atr_pct_filter/
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

OUT_ROOT = REPO / "drive" / "paul_experiments" / "rs_atr_pct_filter"
DATA_DIR = REPO / "data" / "newdata" / "data"

RS_SYMBOLS = (
    "TRV,WELL,CTAS,CASY,AFL,BDX,CW,CB,BSX,CPRT,AJG,HWM,NVDA,TJX,FISV,PRI,MCD,ATEYY,"
    "MCK,POOL,FICO,V,QQQ,ENSG,DHR,UNH,DECK,RELX,RBC,ORLY,MSCI,ROP,CAH,ADBE,BRO,MCO,"
    "COST,NFLX,BBIO,POWL,BR,LOGI,TMO,FIX,AER,CHTR,PGR,LII,EME,TDY,ETR,AXSM,SYK,AVGO,WST"
)
TARGET_PCT = 1.25
STOP_PCT = 0.88

BASE_V = [
    "rs_mode=true",
    "brt_zones=false",
    "yh_zones=false",
    "wpbr_zones=false",
    "rl_mode=false",
    f"target_pct={TARGET_PCT}",
    f"stop_pct={STOP_PCT}",
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
]

# Distribution-based grid (ATR% of price = ATR14/close*100)
MIN_GRID = [None, 1.42, 1.80, 2.00, 2.52]  # off, p10, p25, abs, p50
MAX_GRID = [None, 2.52, 3.00, 3.50, 4.00, 5.18]  # off, p50, abs, p75, abs, p90


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


def _tag(val: Optional[float]) -> str:
    if val is None:
        return "off"
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
        f"PF={row.get('pf', '?')} PNL={row.get('pnl', '?')} MaxDD={row.get('maxdd', '?')}",
        flush=True,
    )
    return row


def _score(row: dict) -> float:
    """Rank arms: PF primary, PNL secondary, lower MaxDD tertiary."""
    trades = float(row.get("trades") or 0)
    pf = float(row.get("pf") or 0)
    pnl = float(row.get("pnl") or 0)
    maxdd = abs(float(row.get("maxdd") or 0))
    if trades < 50:
        return -1e18
    return pf * 1e12 + pnl * 1e3 - maxdd * 1e6


def _parse_min_max_from_label(label: str) -> tuple[Optional[float], Optional[float]]:
    # baseline | min_1p8 | max_3p5 | both_min_1p8_max_3p5
    if label == "baseline":
        return None, None
    mn: Optional[float] = None
    mx: Optional[float] = None
    if label.startswith("min_"):
        frag = label[4:].replace("p", ".")
        mn = float(frag)
    elif label.startswith("max_"):
        frag = label[4:].replace("p", ".")
        mx = float(frag)
    elif label.startswith("both_"):
        rest = label[5:]  # min_1p8_max_3p5
        if "_max_" in rest:
            a, b = rest.split("_max_", 1)
            if a.startswith("min_"):
                mn = float(a[4:].replace("p", "."))
            mx = float(b.replace("p", "."))
    return mn, mx


def write_results_md(out_root: Path, rows: list[dict], recommendations: dict) -> Path:
    path = out_root / "RESULTS.md"

    def _tbl(title: str, subset: list[dict]) -> list[str]:
        lines = [
            f"## {title}",
            "",
            "| Label | Trades | WR% | PF | PNL | MaxDD | Expectancy |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for r in sorted(subset, key=_score, reverse=True):
            lines.append(
                f"| {r.get('label', '')} | {r.get('trades', '')} | {r.get('wr', 0):.1f} | "
                f"{r.get('pf', 0):.3f} | {r.get('pnl', 0):.0f} | {r.get('maxdd', 0):.2f} | "
                f"{r.get('expectancy', 0):.4f} |"
            )
        lines.append("")
        return lines

    baseline = next((r for r in rows if r["label"] == "baseline"), None)
    mins = [r for r in rows if r["label"].startswith("min_")]
    maxs = [r for r in rows if r["label"].startswith("max_")]
    boths = [r for r in rows if r["label"].startswith("both_")]

    lines = [
        "# RS ATR_PCT_AT_TRIGGER filter optimization",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "Universe: curated 55 (`run_rs.bat`). Target 1.25 / stop 0.88. O'Neil filters off. "
        "`min_spy_compare_1y_at_trigger=0`. Gates on **trigger bar T**.",
        "",
        "Units: `ATR_PCT_AT_TRIGGER` = ATR14 / trigger_close × 100 (percent of price).",
        "",
        "Engine flags (already exist; 0 = off): `min_atr_pct_at_trigger`, `max_atr_pct_at_trigger`.",
        "",
    ]
    if baseline:
        lines.extend(_tbl("Baseline (min=0, max=0)", [baseline]))
    lines.extend(_tbl("Min-only", mins))
    lines.extend(_tbl("Max-only", maxs))
    lines.extend(_tbl("Both (min & max)", boths))
    lines.extend(
        [
            "",
            "**Scoring:** composite = PF (primary) + PNL/1000 - MaxDD penalty. "
            "Production guard: beat baseline PF with PNL >= 85% baseline and MaxDD <= 115% baseline.",
            "",
            "## Recommendations",
            "",
            f"- **Best min-only:** `{recommendations.get('best_min')}`",
            f"- **Best max-only:** `{recommendations.get('best_max')}`",
            f"- **Best both:** `{recommendations.get('best_both')}`",
            f"- **Verdict:** {recommendations.get('verdict')}",
            "",
            f"- **Baseline:** {recommendations.get('baseline_detail', 'n/a')}",
            f"- **Best min-only (scored):** {recommendations.get('best_min_detail', 'n/a')}",
            f"- **Best max-only (scored):** {recommendations.get('best_max_detail', 'n/a')}",
            f"- **Best both (scored):** {recommendations.get('best_both_detail', 'n/a')}",
            "",
            f"Rationale: {recommendations.get('notes', '')}",
            "",
            "Artifacts: per-run folders; `summary.csv`; `posthoc_closed_filter.csv` (trade-level subset).",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workers", type=int, default=8, help="rocket_brt -w per run")
    ap.add_argument("--parallel-runs", type=int, default=3, help="Concurrent RS jobs")
    ap.add_argument(
        "--arm",
        choices=["all", "baseline", "min", "max", "both"],
        default="all",
    )
    ap.add_argument(
        "--combo-min",
        type=float,
        default=None,
        help="Override min for arm both (else pick best min-only)",
    )
    ap.add_argument(
        "--combo-max",
        type=float,
        default=None,
        help="Override max for arm both (else pick best max-only)",
    )
    args = ap.parse_args()

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    py = _resolve_python()
    jobs: list[tuple[str, Path, list[str]]] = []

    if args.arm in ("all", "baseline"):
        jobs.append(("baseline", OUT_ROOT / "baseline", []))

    if args.arm in ("all", "min"):
        for mn in MIN_GRID:
            if mn is None:
                continue  # covered by baseline
            label = f"min_{_tag(mn)}"
            jobs.append(
                (label, OUT_ROOT / label, [f"min_atr_pct_at_trigger={mn}", "max_atr_pct_at_trigger=0"])
            )

    if args.arm in ("all", "max"):
        for mx in MAX_GRID:
            if mx is None:
                continue
            label = f"max_{_tag(mx)}"
            jobs.append(
                (label, OUT_ROOT / label, ["min_atr_pct_at_trigger=0", f"max_atr_pct_at_trigger={mx}"])
            )

    rows: list[dict] = []
    stage1 = [j for j in jobs if not j[0].startswith("both_")]
    with ThreadPoolExecutor(max_workers=max(1, args.parallel_runs)) as pool:
        futs = {
            pool.submit(
                run_one, label=lab, outdir=od, extra_v=ev, py=py, workers=args.workers
            ): lab
            for lab, od, ev in stage1
        }
        for fut in as_completed(futs):
            rows.append(fut.result())

    if args.arm in ("all", "both"):
        def _best(subset: list[dict]) -> Optional[dict]:
            ok = [
                r
                for r in subset
                if int(r.get("exit_code", 1)) == 0 and r.get("trades") is not None
            ]
            return max(ok, key=_score) if ok else None

        baseline = next((r for r in rows if r["label"] == "baseline"), None)
        best_min = _best([r for r in rows if r["label"].startswith("min_")])
        best_max = _best([r for r in rows if r["label"].startswith("max_")])

        mn = args.combo_min
        mx = args.combo_max
        if mn is None and best_min is not None:
            mn, _ = _parse_min_max_from_label(best_min["label"])
        if mx is None and best_max is not None:
            _, mx = _parse_min_max_from_label(best_max["label"])

        # Fixed both pairs from posthoc + bests
        both_pairs: list[tuple[float, float]] = []
        for pair in (
            (1.42, 5.18),
            (1.80, 3.50),
            (2.00, 4.00),
            (1.50, 4.00),
            (1.80, 3.00),
            (2.00, 3.50),
        ):
            both_pairs.append(pair)
        if mn is not None and mx is not None and (mn, mx) not in both_pairs:
            both_pairs.append((mn, mx))

        d_jobs = []
        for a, b in both_pairs:
            label = f"both_min_{_tag(a)}_max_{_tag(b)}"
            d_jobs.append(
                (
                    label,
                    OUT_ROOT / label,
                    [f"min_atr_pct_at_trigger={a}", f"max_atr_pct_at_trigger={b}"],
                )
            )
        with ThreadPoolExecutor(max_workers=max(1, args.parallel_runs)) as pool:
            futs = {
                pool.submit(
                    run_one, label=lab, outdir=od, extra_v=ev, py=py, workers=args.workers
                ): lab
                for lab, od, ev in d_jobs
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

    baseline = next((r for r in rows if r["label"] == "baseline"), None)
    ba = _best([r for r in rows if r["label"].startswith("min_")])
    bb = _best([r for r in rows if r["label"].startswith("max_")])
    bc = _best([r for r in rows if r["label"].startswith("both_")])

    def _beats_baseline(cand: Optional[dict]) -> bool:
        if not cand or not baseline:
            return False
        # Prefer higher PF with MaxDD not much worse and PNL not collapsing
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

    def _fmt(r: Optional[dict]) -> str:
        if not r:
            return "n/a"
        return (
            f"{r['label']}: trades={r.get('trades')} WR={float(r.get('wr') or 0):.1f}% "
            f"PF={float(r.get('pf') or 0):.3f} PNL={float(r.get('pnl') or 0):.0f} "
            f"MaxDD={float(r.get('maxdd') or 0):.2f} exp={float(r.get('expectancy') or 0):.4f}"
        )

    verdict = "no help - keep ATR filters off (baseline)"
    if _beats_baseline(bb) and (not ba or _score(bb) >= _score(ba or {})):
        if bc and _beats_baseline(bc) and _score(bc) > _score(bb):
            verdict = f"help - prefer both: {bc['label']}"
        else:
            verdict = f"help - prefer max-only: {bb['label']}"
    elif _beats_baseline(ba):
        if bc and _beats_baseline(bc) and _score(bc) > _score(ba):
            verdict = f"help - prefer both: {bc['label']}"
        else:
            verdict = f"help - prefer min-only: {ba['label']}"
    elif bc and _beats_baseline(bc):
        verdict = f"help - prefer both: {bc['label']}"
    elif bb and baseline and float(bb.get("pf") or 0) > float(baseline.get("pf") or 0):
        verdict = (
            f"marginal - max-only {bb['label']} raises PF but fails PNL/MaxDD guard; "
            "prefer neither for production"
        )

    baseline_line = _fmt(baseline)
    notes = (
        f"baseline [{baseline_line}]; "
        f"best_min [{_fmt(ba)}]; best_max [{_fmt(bb)}]; best_both [{_fmt(bc)}]. "
        "Post-fix: filtered arms must show lower trade count than baseline when min/max > 0."
    )
    recs = {
        "best_min": ba["label"] if ba else "n/a",
        "best_max": bb["label"] if bb else "n/a",
        "best_both": bc["label"] if bc else "n/a",
        "verdict": verdict,
        "notes": notes,
        "baseline_detail": baseline_line,
        "best_min_detail": _fmt(ba),
        "best_max_detail": _fmt(bb),
        "best_both_detail": _fmt(bc),
    }
    write_results_md(OUT_ROOT, rows, recs)
    print(f"[summary] {sum_path}")
    print(f"[recs] {recs}")
    return 0 if all(int(r.get("exit_code", 1)) == 0 for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
