#!/usr/bin/env python3
"""SPY INT Weak lag-1 A/B for RL (experiment-only; does not modify run_rl.bat).

Arms:
  baseline       — production RL
  no_entry_weak  — block_entries_when_spy_int_weak + spy_int_tc_lag=1
  exit_on_weak   — exit_when_spy_int_turns_weak + block entries + lag=1

Writes drive/paul_experiments/spy_int_weak_system_ab/RL/partial_RL.csv
"""
from __future__ import annotations

import csv
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SA = REPO / "stock_analysis"
OUT_ROOT = REPO / "drive" / "paul_experiments" / "spy_int_weak_system_ab" / "RL"
DATA_DIR = REPO / "data" / "newdata" / "data"
PER_SYMBOL = SA / "Per_Symbol_Optimized_Settings_Approved_Latest.json"

RL_COMMON_V = [
    "rl_mode=true",
    "brt_zones=false",
    "yh_zones=false",
    "indicator_buy=off",
]

ARMS: list[tuple[str, list[str]]] = [
    ("baseline", []),
    (
        "no_entry_weak",
        ["block_entries_when_spy_int_weak=true", "spy_int_tc_lag=1"],
    ),
    (
        "exit_on_weak",
        # GRID_PLAN: exit-only (entries still allowed while Weak; exit when lag turns Weak).
        ["exit_when_spy_int_turns_weak=true", "spy_int_tc_lag=1"],
    ),
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


def load_rl_symbols() -> str:
    env = os.environ.get("RL_SYMBOLS", "").strip()
    if env:
        return env
    bat = (REPO / "run_rl.bat").read_text(encoding="utf-8", errors="replace")
    m = re.search(r'set "RL_SYMBOLS=([^"]+)"', bat)
    if not m:
        raise RuntimeError("Could not parse RL_SYMBOLS from run_rl.bat")
    return m.group(1).strip()


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
    report = _find_latest(outdir, "RL_Report_*.csv")
    if report is None:
        report = _find_latest(outdir, "RL_Audit_Report_*.csv")
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
    if "Pct_Wins" in row and str(row.get("Pct_Wins", "")).strip():
        wr = _safe_num(row.get("Pct_Wins"))
    return {
        "arm": outdir.name,
        "report_file": report.name,
        "Total_Trades": total_trades,
        "WR": wr,
        "Profit_Factor": _safe_num(row.get("Profit_Factor", 0)),
        "Total_PNL": _safe_num(row.get("Total_PNL", 0)),
        "Max_DD": _safe_num(row.get("Max_DD", 0)),
        "Expectancy": _safe_num(row.get("Expectancy", 0)),
        "Wins": wins,
        "Losses": losses,
        "BE": bes,
        "Ann_ROR": _safe_num(row.get("Ann_ROR", 0)),
        "Aggressive_Total_PNL": _safe_num(row.get("Aggressive_Total_PNL", 0)),
        "Aggressive_Max_DD": _safe_num(row.get("Aggressive_Max_DD", 0)),
    }


def build_cmd(py: str, outdir: Path, workers: int, symbols: str, extra_v: list[str]) -> list[str]:
    cmd = [
        py,
        str(SA / "rocket_brt.py"),
        str(DATA_DIR),
        "-o",
        str(outdir),
        "-w",
        str(workers),
        "--no-regression",
        "-s",
        symbols,
    ]
    if PER_SYMBOL.is_file():
        cmd.extend(["--per-symbol-settings", str(PER_SYMBOL)])
    for v in RL_COMMON_V + extra_v:
        cmd.extend(["-v", v])
    return cmd


def write_partial(rows: list[dict]) -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    path = OUT_ROOT / "partial_RL.csv"
    cols = [
        "arm",
        "Total_Trades",
        "WR",
        "Profit_Factor",
        "Total_PNL",
        "Max_DD",
        "Expectancy",
        "Wins",
        "Losses",
        "BE",
        "Ann_ROR",
        "report_file",
        "rc",
        "elapsed_s",
        "note",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"[partial] wrote {path} ({len(rows)} rows)", flush=True)


def run_arm(
    label: str,
    extra_v: list[str],
    *,
    py: str,
    symbols: str,
    workers: int,
) -> dict:
    outdir = OUT_ROOT / label
    outdir.mkdir(parents=True, exist_ok=True)
    log_path = outdir / "run.log"
    cmd = build_cmd(py, outdir, workers, symbols, extra_v)
    print(f"[{label}] START {' '.join(cmd[-12:])}", flush=True)
    t0 = time.time()
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
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
    metrics = extract_metrics(outdir) or {
        "arm": label,
        "Total_Trades": 0,
        "WR": 0.0,
        "Profit_Factor": 0.0,
        "Total_PNL": 0.0,
        "Max_DD": 0.0,
        "Expectancy": 0.0,
        "Wins": 0,
        "Losses": 0,
        "BE": 0,
        "Ann_ROR": 0.0,
        "report_file": "",
    }
    metrics["rc"] = proc.returncode
    metrics["elapsed_s"] = round(elapsed, 1)
    metrics["note"] = "" if proc.returncode == 0 else f"rc={proc.returncode} see {log_path.name}"
    print(
        f"[{label}] DONE rc={proc.returncode} trades={metrics.get('Total_Trades')} "
        f"PNL={metrics.get('Total_PNL')} ({elapsed:.0f}s)",
        flush=True,
    )
    return metrics


def main() -> int:
    py = _resolve_python()
    symbols = load_rl_symbols()
    workers = int(os.environ.get("RL_ARM_WORKERS", "5"))
    jobs = int(os.environ.get("RL_ARM_JOBS", "3"))
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    (OUT_ROOT / "NOTES.md").write_text(
        "\n".join(
            [
                "# RL SPY INT Weak lag-1 arms",
                "",
                f"- Started: {datetime.now().isoformat(timespec='seconds')}",
                "- Production defaults from `run_rl.bat` (`rl_mode=true`, per-symbol settings, `-w 5`).",
                "- Flags: `spy_int_tc_lag=1`, `block_entries_when_spy_int_weak`, `exit_when_spy_int_turns_weak`.",
                "- Timing: block_entries uses **trigger** bar T with lag-1 (`outlook[T-1]`); not re-checked on entry T+1.",
                "- RL exit-on-weak: exit at open as `SPY_INT_TC_WEAK_EXIT` when lagged outlook *turns* Weak",
                "  (lag-1 as of that day; same semantics as BRT).",
                "- See `TRIGGER_VS_ENTRY.md` in this experiment folder.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"symbols={len(symbols.split(','))} workers/arm={workers} parallel_jobs={jobs}", flush=True)
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        futs = {
            ex.submit(run_arm, label, extra, py=py, symbols=symbols, workers=workers): label
            for label, extra in ARMS
        }
        for fut in as_completed(futs):
            results.append(fut.result())
            results.sort(key=lambda r: ["baseline", "no_entry_weak", "exit_on_weak"].index(r["arm"]))
            write_partial(results)
    write_partial(results)
    # Markdown table for humans
    md = OUT_ROOT / "RESULTS.md"
    lines = [
        "# RL SPY INT Weak lag-1 — results",
        "",
        "| arm | trades | WR% | PF | PNL | MaxDD | Expectancy |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        lines.append(
            f"| {r['arm']} | {r['Total_Trades']} | {r['WR']:.1f} | {r['Profit_Factor']:.3f} | "
            f"{r['Total_PNL']:.0f} | {r['Max_DD']:.2f} | {r['Expectancy']:.2f} |"
        )
    lines.append("")
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(md.read_text(encoding="utf-8"))
    return 0 if all(int(r.get("rc", 1)) == 0 for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
