"""Shared process/report helpers for the Davey experiment runners."""
from __future__ import annotations

import csv
import math
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

REPO = Path(__file__).resolve().parents[1]
ENGINE = REPO / "stock_analysis" / "rocket_brt.py"
DATA_DIR = REPO / "data" / "newdata" / "data"


@dataclass(frozen=True)
class Arm:
    id: str
    label: str
    values: tuple[str, ...]


def resolve_python() -> str:
    env_py = os.environ.get("PY", "").strip()
    return env_py if env_py and Path(env_py).is_file() else sys.executable


def latest(path: Path, pattern: str) -> Path | None:
    files = sorted(path.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def safe_num(value: object) -> float:
    text = str(value or "").replace(",", "").replace("$", "").replace("%", "").strip()
    if not text or text.upper() == "N/A":
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


METRICS = (
    "Total_Trades", "Total_PNL", "Profit_Factor", "Max_DD", "Profit_Per_Capital_Day",
    "Ann_ROR", "Avg_Days_Held", "Median_Days_Held", "P90_Days", "Expectancy",
    "Losing_Streak", "Pct_PNL_Max_Symbol", "Pct_PNL_Max_Trade", "Pct_PNL_Top10",
    "Pct_Wins", "Aggressive_Total_PNL", "Aggressive_Max_DD",
)


def extract_metrics(outdir: Path, prefix: str) -> dict[str, float] | None:
    """Read completed-run metrics from the engine Report/Audit CSV only.

    Closed-only fallbacks are intentionally avoided: interrupted post-processing can leave a
    Closed file without a finished Report, and that snapshot is unsafe for skip/selection.
    """
    report = latest(outdir, f"{prefix}_Report_*.csv") or latest(outdir, f"{prefix}_Audit_Report_*.csv")
    if report is None:
        return None
    with report.open(newline="", encoding="utf-8", errors="replace") as handle:
        row = next(csv.DictReader(handle), None)
    if not row:
        return None
    result = {key: safe_num(row.get(key)) for key in METRICS}
    result["report_file"] = report.name  # type: ignore[assignment]
    return result


def run_job(
    *,
    root: Path,
    prefix: str,
    common_values: Iterable[str],
    arm: Arm,
    phase: str,
    workers: int,
    symbols: str,
    start: str = "",
    end: str = "",
    skip_existing: bool = False,
    extra_args: Iterable[str] | None = None,
) -> dict:
    job_id = f"{phase}__{arm.id}"
    outdir = root / "runs" / job_id
    outdir.mkdir(parents=True, exist_ok=True)
    existing = extract_metrics(outdir, prefix)
    if skip_existing and existing and existing.get("Total_Trades", 0) > 0:
        return {"id": arm.id, "label": arm.label, "phase": phase, "ok": True, "metrics": existing, "outdir": str(outdir)}

    cmd = [
        resolve_python(), str(ENGINE), str(DATA_DIR), "-o", str(outdir), "-w", str(workers),
        "--aggressive", "--use-duckdb", "--no-regression", "--no-yfinance",
    ]
    if extra_args:
        cmd.extend(list(extra_args))
    values = list(common_values) + list(arm.values)
    if start:
        values.append(f"entry_start_date={start}")
    if end:
        values.append(f"entry_end_date={end}")
        values.append(f"backtest_end_date={end}")
    for value in values:
        cmd.extend(["-v", value])
    if symbols:
        cmd.extend(["-s", symbols])
    log = outdir / "run.log"
    t0 = time.time()
    with log.open("w", encoding="utf-8", errors="replace") as handle:
        handle.write("CMD: " + subprocess.list2cmdline(cmd) + "\n\n")
        handle.flush()
        proc = subprocess.run(cmd, cwd=str(REPO), stdout=handle, stderr=subprocess.STDOUT)
    metrics = extract_metrics(outdir, prefix)
    return {
        "id": arm.id,
        "label": arm.label,
        "phase": phase,
        "start": start,
        "end": end,
        "ok": proc.returncode == 0 and metrics is not None,
        "exit_code": proc.returncode,
        "elapsed_s": round(time.time() - t0, 1),
        "metrics": metrics or {},
        "outdir": str(outdir),
        "error": "" if proc.returncode == 0 and metrics is not None else f"see {log}",
    }


def run_jobs(specs: list[dict], jobs: int) -> list[dict]:
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, min(3, jobs))) as pool:
        futures = [pool.submit(run_job, **spec) for spec in specs]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            metrics = result.get("metrics") or {}
            print(
                f"[{result['phase']}:{result['id']}] ok={result['ok']} "
                f"trades={int(metrics.get('Total_Trades', 0) or 0)} "
                f"elapsed={result.get('elapsed_s', 0)}s",
                flush=True,
            )
    return results


def score(metrics: dict) -> float:
    """Coarse IS selector emphasizing PF/PPCD with DD and concentration penalties."""
    trades = float(metrics.get("Total_Trades", 0) or 0)
    if trades < 30:
        return -math.inf
    return (
        2.0 * float(metrics.get("Profit_Factor", 0) or 0)
        + 0.02 * float(metrics.get("Profit_Per_Capital_Day", 0) or 0)
        - 0.03 * float(metrics.get("Max_DD", 0) or 0)
        - 0.002 * float(metrics.get("Pct_PNL_Max_Symbol", 0) or 0)
    )


def flatten(result: dict) -> dict:
    metrics = result.get("metrics") or {}
    row = {k: v for k, v in result.items() if k != "metrics"}
    row.update({key: metrics.get(key, 0) for key in METRICS})
    return row


def write_csv(path: Path, results: list[dict]) -> None:
    rows = [flatten(r) for r in results]
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
