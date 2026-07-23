"""
Run IND ATR_RATIO / VOL_SURGE / DIAMOND weight experiment matrix.

Queue policy (default): up to 3 concurrent backtests, each with -w 10
(~30 symbol workers total) to utilize CPU. Override with --jobs / --workers.

Reads experiments/ind_weight_exp_manifest.json produced by setup_ind_weight_experiments.py.

Outputs under drive/ind_weight_exp/<candidate_id>/
Status:    drive/ind_weight_exp/status.txt
Results:   drive/ind_weight_exp/comparison.csv
           drive/ind_weight_exp/comparison.md
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP_DIR = REPO / "experiments"
OUT_ROOT = REPO / "drive" / "ind_weight_exp"
STATUS_PATH = OUT_ROOT / "status.txt"
MANIFEST_PATH = EXP_DIR / "ind_weight_exp_manifest.json"
MIN_TRADES = 350
MAX_DD = 22.0

# Frozen IND settings matching run_ind.bat / IND_Final_Optimized_Settings.json
COMMON_V = [
    "target_pct=1.24",
    "trailing_stop_increment=0",
    "strong_pre_pivot_pct=0.081",
    "strong_post_pivot_pct=0.109",
    "atr_progress=0",
    "atr_days=0",
    "compute_beta=true",
    "min_avg_volume_10d_at_entry=0",
    "min_atr_pct_at_trigger=8.1",
    "max_atr_pct_at_trigger=0",
    "use_indicators=true",
    "use_ind_score=true",
    "indicator_buy=only",
    "indicator_diff=7",
    "indicator_sides=long",
    "transaction_type=long",
    "atr_target=2.2",
    "atr_stop=1.4",
    "max_ind_entry_neutral_n=30",
    "yh_zones=false",
    "aggressive_avg_positions=20",
]


def _resolve_python() -> str:
    env_py = os.environ.get("PY", "").strip()
    if env_py and Path(env_py).is_file():
        return env_py
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Python/Python310/python.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Python/Python311/python.exe",
        Path(r"C:\Program Files\WindowsApps\PythonSoftwareFoundation.Python.3.10_3.10.3056.0_x64__qbz5n2kfra8p0\python3.10.exe"),
    ]
    for p in candidates:
        if p.is_file():
            return str(p)
    return sys.executable


def _fmt_dur(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    return f"{m}m {s:02d}s"


def write_status(
    *,
    started_at: str,
    session_start: float,
    current_id: str,
    done: int,
    total: int,
    note: str = "",
    jobs: int = 3,
    workers: int = 10,
) -> None:
    elapsed = time.time() - session_start
    remaining = max(0, total - done)
    if done > 0 and remaining > 0:
        eta = _fmt_dur((elapsed / done) * remaining)
    elif remaining == 0:
        eta = "0s (done)"
    else:
        eta = "estimating..."
    pct = (100.0 * done / total) if total else 100.0
    lines = [
        "IND Weight Experiment Status",
        f"started_at:     {started_at}",
        f"updated_at:     {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"elapsed:        {_fmt_dur(elapsed)}",
        f"current:        {current_id}",
        f"trials:         {done}/{total} ({pct:.1f}%)",
        f"eta:            {eta}",
        f"concurrency:    {jobs} concurrent jobs x -w {workers} "
        f"(~{jobs * workers} symbol workers)",
        f"note:           {note}".rstrip(),
        "",
        "Watch live: Get-Content -Wait drive\\ind_weight_exp\\status.txt",
    ]
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  [status] {_fmt_dur(elapsed)}  {done}/{total}  {current_id}  {note}")


def _safe_num(x) -> float:
    if x is None or x == "" or str(x).strip().upper() == "N/A":
        return 0.0
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).replace("%", "").replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def _find_latest(outdir: Path, pattern: str) -> Path | None:
    files = sorted(outdir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def extract_metrics(outdir: Path) -> dict | None:
    """Prefer IND_Report_*.csv; fall back to IND_Audit_Report_*.csv."""
    report = _find_latest(outdir, "IND_Report_*.csv")
    if report is None:
        report = _find_latest(outdir, "IND_Audit_Report_*.csv")
    if report is None:
        return None
    with open(report, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        row = next(reader, None)
    if not row:
        return None
    wins = int(_safe_num(row.get("Wins", 0)))
    losses = int(_safe_num(row.get("Losses", 0)))
    bes = int(_safe_num(row.get("BE", row.get("BEs", 0))))
    total_trades = int(_safe_num(row.get("Total_Trades", 0)))
    if total_trades <= 0:
        total_trades = wins + losses + bes
    return {
        "report_file": report.name,
        "Total_Trades": total_trades,
        "Total_PNL": _safe_num(row.get("Total_PNL", 0)),
        "Profit_Factor": _safe_num(row.get("Profit_Factor", 0)),
        "Max_DD": _safe_num(row.get("Max_DD", 0)),
        "Profit_Per_Capital_Day": _safe_num(row.get("Profit_Per_Capital_Day", 0)),
        "Expectancy": _safe_num(row.get("Expectancy", 0)),
        "Avg_PNL_Pct": _safe_num(row.get("Avg_PNL_Pct", 0)),
        "Wins": wins,
        "Losses": losses,
        "BE": bes,
        "Win_Loss_Ratio_Dollar": _safe_num(row.get("Win_Loss_Ratio_Dollar", 0)),
        "Capital_Days": int(_safe_num(row.get("Capital_Days", 0))),
        "P90_Days": _safe_num(row.get("P90_Days", 0)),
        "Losing_Streak": int(_safe_num(row.get("Losing_Streak", 0))),
        "Max_Positions": int(_safe_num(row.get("Max_Positions", 0))),
    }


def build_cmd(
    py: str,
    cand: dict,
    outdir: Path,
    workers: int,
) -> list[str]:
    weights = EXP_DIR / cand["weights"]
    cmd = [
        py,
        str(REPO / "stock_analysis" / "rocket_brt.py"),
        str(REPO / "data" / "newdata" / "data"),
        "-o",
        str(outdir),
        "-w",
        str(workers),
        "--aggressive",
        "--use-duckdb",
        "--no-regression",
    ]
    for v in COMMON_V:
        cmd.extend(["-v", v])
    cmd.extend(["-v", f"ind_score_weights_path={weights}"])
    cmd.extend(["-v", f"min_ind_score={cand['min_ind_score']}"])
    if cand.get("mandatory"):
        cmd.extend(["-v", f"mandatory_ind_states_path={EXP_DIR / cand['mandatory']}"])
    return cmd


def aggregate(
    results: list[dict],
    *,
    jobs: int = 3,
    workers: int = 10,
) -> tuple[Path, Path]:
    by_id = {r["id"]: r for r in results}
    c0 = by_id.get("C0")
    c1 = by_id.get("C1")

    rows = []
    for r in results:
        m = r.get("metrics") or {}
        trades = int(m.get("Total_Trades", 0) or 0)
        dd = float(m.get("Max_DD", 0) or 0)
        gate_ok = trades >= MIN_TRADES and dd <= MAX_DD and r.get("ok")
        beat_c0 = ""
        beat_c1 = ""
        if c0 and c0.get("metrics") and m and int(c0["metrics"].get("Total_Trades", 0) or 0) > 0:
            beat_c0 = "Y" if (
                trades > 0
                and float(m.get("Profit_Per_Capital_Day", 0)) > float(c0["metrics"].get("Profit_Per_Capital_Day", 0))
                and float(m.get("Total_PNL", 0)) > float(c0["metrics"].get("Total_PNL", 0))
                and float(m.get("Profit_Factor", 0)) >= float(c0["metrics"].get("Profit_Factor", 0))
            ) else "N"
        if c1 and c1.get("metrics") and m and int(c1["metrics"].get("Total_Trades", 0) or 0) > 0:
            beat_c1 = "Y" if (
                trades > 0
                and float(m.get("Profit_Per_Capital_Day", 0)) > float(c1["metrics"].get("Profit_Per_Capital_Day", 0))
                and float(m.get("Total_PNL", 0)) > float(c1["metrics"].get("Total_PNL", 0))
                and float(m.get("Profit_Factor", 0)) >= float(c1["metrics"].get("Profit_Factor", 0))
            ) else "N"
        rows.append({
            "id": r["id"],
            "label": r.get("label", ""),
            "ok": bool(r.get("ok")),
            "exit_code": r.get("exit_code"),
            "elapsed_s": round(float(r.get("elapsed_s", 0) or 0), 1),
            "Total_Trades": trades,
            "Total_PNL": round(float(m.get("Total_PNL", 0) or 0), 2),
            "Profit_Factor": round(float(m.get("Profit_Factor", 0) or 0), 3),
            "Max_DD": round(dd, 2),
            "PPCD": round(float(m.get("Profit_Per_Capital_Day", 0) or 0), 4),
            "Expectancy": round(float(m.get("Expectancy", 0) or 0), 2),
            "Avg_PNL_Pct": round(float(m.get("Avg_PNL_Pct", 0) or 0), 3),
            "gate_pass": "PASS" if gate_ok else "FAIL",
            "beat_C0": beat_c0,
            "beat_C1": beat_c1,
            "min_ind_score": r.get("min_ind_score"),
            "weights": r.get("weights"),
            "mandatory": r.get("mandatory") or "",
            "outdir": r.get("outdir", ""),
            "error": r.get("error", ""),
        })

    csv_path = OUT_ROOT / "comparison.csv"
    md_path = OUT_ROOT / "comparison.md"
    if rows:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    lines = [
        "# IND Weight Experiment Comparison",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"Hard gates: trades >= {MIN_TRADES}, Max_DD <= {MAX_DD}%",
        "",
        f"Concurrency: **{jobs} concurrent job(s)** x `-w {workers}` "
        f"(~{jobs * workers} symbol workers). "
        "Runner default going forward: 3 jobs x -w 10.",
        "",
        "| id | trades | PNL | PF | Max_DD | PPCD | Exp | gate | vsC0 | vsC1 |",
        "|---|---:|---:|---:|---:|---:|---:|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['id']} | {r['Total_Trades']} | {r['Total_PNL']:.0f} | {r['Profit_Factor']:.3f} | "
            f"{r['Max_DD']:.1f} | {r['PPCD']:.4f} | {r['Expectancy']:.2f} | {r['gate_pass']} | "
            f"{r['beat_C0']} | {r['beat_C1']} |"
        )

    # Recommendation
    lines.extend(["", "## Recommendation", ""])
    eligible = [
        r for r in rows
        if r["gate_pass"] == "PASS" and r["id"] not in ("C0", "C1") and r["ok"]
    ]
    # Prefer beating both C0 and C1 on PPCD+PNL+PF; else beat C0; else none
    winners = [r for r in eligible if r["beat_C0"] == "Y" and r["beat_C1"] == "Y"]
    if not winners:
        winners = [r for r in eligible if r["beat_C0"] == "Y"]
    if winners:
        best = max(winners, key=lambda r: (r["PPCD"], r["Total_PNL"], r["Profit_Factor"]))
        lines.append(
            f"**Best candidate: `{best['id']}`** — PPCD={best['PPCD']}, "
            f"PNL={best['Total_PNL']:.0f}, PF={best['Profit_Factor']}, "
            f"DD={best['Max_DD']}%, trades={best['Total_Trades']}, "
            f"beat_C0={best['beat_C0']}, beat_C1={best['beat_C1']}."
        )
        lines.append("")
        lines.append(
            "Do **not** update `run_ind.bat` until this winner is confirmed and you explicitly approve."
        )
    else:
        lines.append(
            "No candidate clearly beats C0 (and preferably C1) while passing hard gates. "
            "Keep production settings; no `run_ind.bat` change recommended."
        )

    zero_score = [r["id"] for r in rows if r["Total_Trades"] == 0 and float(r.get("min_ind_score") or 0) > 0]
    if zero_score:
        lines.extend([
            "",
            "## Notes",
            "",
            "Score-gated candidates with `min_ind_score > 0` produced **0 trades**. "
            "Active control weights are correlation-scaled near **-0.5** for most indicators "
            "(including ATR_RATIO / VOL_SURGE / DIAMOND before overrides), so `IND_SCORE` stays "
            "strongly negative and never clears thresholds like 0.5 / 1.0 / 1.5. "
            "A follow-up should either calibrate thresholds to the observed score distribution "
            "or use a positive mean-PNL weight file.",
            "",
            f"Zero-trade score-gated ids: {', '.join(zero_score)}",
        ])

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return csv_path, md_path


def run_candidate(
    py: str,
    cand: dict,
    workers: int,
    skip_existing: bool,
) -> dict:
    cid = cand["id"]
    outdir = OUT_ROOT / cid
    outdir.mkdir(parents=True, exist_ok=True)
    result = {
        "id": cid,
        "label": cand.get("label", ""),
        "min_ind_score": cand.get("min_ind_score"),
        "weights": cand.get("weights"),
        "mandatory": cand.get("mandatory"),
        "outdir": str(outdir),
    }

    existing = extract_metrics(outdir)
    if skip_existing and existing is not None:
        result["ok"] = True
        result["exit_code"] = 0
        result["elapsed_s"] = 0.0
        result["metrics"] = existing
        result["skipped"] = True
        return result

    cmd = build_cmd(py, cand, outdir, workers)
    log_path = outdir / "run.log"
    t0 = time.time()
    print(f"\n=== RUN {cid} ===")
    print(" ".join(cmd))
    with open(log_path, "w", encoding="utf-8", errors="replace") as log:
        log.write("CMD: " + " ".join(cmd) + "\n\n")
        log.flush()
        proc = subprocess.run(
            cmd,
            cwd=str(REPO),
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
    elapsed = time.time() - t0
    result["elapsed_s"] = elapsed
    result["exit_code"] = proc.returncode
    result["ok"] = proc.returncode == 0
    result["skipped"] = False
    metrics = extract_metrics(outdir)
    result["metrics"] = metrics
    if metrics is None and proc.returncode == 0:
        result["ok"] = False
        result["error"] = "no IND_Report/Audit found"
    elif proc.returncode != 0:
        result["error"] = f"exit {proc.returncode}; see {log_path}"
    print(
        f"=== DONE {cid} exit={proc.returncode} "
        f"elapsed={_fmt_dur(elapsed)} "
        f"trades={(metrics or {}).get('Total_Trades')} "
        f"pnl={(metrics or {}).get('Total_PNL')} ==="
    )
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--workers", "-w", type=int, default=10,
        help="Symbol workers per backtest job (default 10)",
    )
    ap.add_argument(
        "--jobs", "-j", type=int, default=3,
        help="Max concurrent backtest jobs (default 3)",
    )
    ap.add_argument("--only", nargs="*", help="Optional candidate ids to run")
    ap.add_argument("--no-skip", action="store_true", help="Re-run even if report exists")
    ap.add_argument("--setup-only", action="store_true", help="Only ensure setup; do not run")
    args = ap.parse_args()
    jobs = max(1, int(args.jobs))
    workers = max(1, int(args.workers))

    setup = REPO / "tools" / "setup_ind_weight_experiments.py"
    print(f"Running setup: {setup}")
    rc = subprocess.call([_resolve_python(), str(setup)], cwd=str(REPO))
    if rc != 0:
        return rc
    if not MANIFEST_PATH.is_file():
        print(f"ERROR: missing {MANIFEST_PATH}", file=sys.stderr)
        return 1
    if args.setup_only:
        print("setup-only: done")
        return 0

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    candidates = manifest["candidates"]
    if args.only:
        want = set(args.only)
        candidates = [c for c in candidates if c["id"] in want]
        missing = want - {c["id"] for c in candidates}
        if missing:
            print(f"ERROR: unknown ids: {sorted(missing)}", file=sys.stderr)
            return 1

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    py = _resolve_python()
    print(f"python={py}")
    print(f"control_source={manifest.get('control_source')}")
    print(
        f"candidates={len(candidates)}  jobs={jobs}  workers/job={workers}  "
        f"~{jobs * workers} symbol workers"
    )
    print(
        f"Concurrency: {jobs} concurrent IND backtests, each with -w {workers}."
    )

    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    session_start = time.time()
    results: list[dict] = []
    total = len(candidates)
    progress_path = OUT_ROOT / "progress.json"
    results_by_id: dict[str, dict] = {}

    write_status(
        started_at=started_at,
        session_start=session_start,
        current_id="(starting)",
        done=0,
        total=total,
        note="session start",
        jobs=jobs,
        workers=workers,
    )

    pending = list(candidates)
    done_n = 0
    in_flight: dict = {}

    with ThreadPoolExecutor(max_workers=jobs) as ex:
        while pending or in_flight:
            while pending and len(in_flight) < jobs:
                cand = pending.pop(0)
                fut = ex.submit(
                    run_candidate, py, cand, workers, skip_existing=not args.no_skip
                )
                in_flight[fut] = cand["id"]
                running = ", ".join(sorted(in_flight.values()))
                write_status(
                    started_at=started_at,
                    session_start=session_start,
                    current_id=running or cand["id"],
                    done=done_n,
                    total=total,
                    note=f"running ({len(in_flight)}/{jobs} slots)",
                    jobs=jobs,
                    workers=workers,
                )

            for fut in as_completed(list(in_flight.keys()), timeout=None):
                cid = in_flight.pop(fut)
                r = fut.result()
                results_by_id[r["id"]] = r
                done_n += 1
                # Preserve manifest order in results
                results = [
                    results_by_id[c["id"]]
                    for c in candidates
                    if c["id"] in results_by_id
                ]
                progress_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
                aggregate(results, jobs=jobs, workers=workers)
                running = ", ".join(sorted(in_flight.values())) or "(idle)"
                write_status(
                    started_at=started_at,
                    session_start=session_start,
                    current_id=running,
                    done=done_n,
                    total=total,
                    note=f"finished {cid}" + (" (skipped)" if r.get("skipped") else ""),
                    jobs=jobs,
                    workers=workers,
                )
                break  # refill slots from pending

    # Final ordered results
    results = [results_by_id[c["id"]] for c in candidates if c["id"] in results_by_id]
    csv_path, md_path = aggregate(results, jobs=jobs, workers=workers)
    write_status(
        started_at=started_at,
        session_start=session_start,
        current_id="(complete)",
        done=total,
        total=total,
        note=f"finished in {_fmt_dur(time.time() - session_start)}",
        jobs=jobs,
        workers=workers,
    )
    print(f"\nComparison CSV: {csv_path}")
    print(f"Comparison MD:  {md_path}")
    print(md_path.read_text(encoding="utf-8"))
    failed = [r["id"] for r in results if not r.get("ok")]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
