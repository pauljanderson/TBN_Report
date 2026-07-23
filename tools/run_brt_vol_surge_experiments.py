#!/usr/bin/env python3
"""True BRT capital backtests for VOL_SURGE state-exclusion gates.

Runs production BRT settings (from run_brt.bat, without editing it) with optional
exclude_ind_states_path gates. Default concurrency: 3 jobs x 10 workers.

Outputs under drive/brt_vol_surge_exp/
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
OUT_ROOT = REPO / "drive" / "brt_vol_surge_exp"
STATUS_PATH = OUT_ROOT / "status.txt"
DATA_DIR = REPO / "data" / "newdata" / "data"
PS_SETTINGS = REPO / "stock_analysis" / "Per_Symbol_Optimized_Settings_Approved_Latest.json"

# Mirror run_brt.bat (do not edit run_brt.bat). Skip --print-zones for speed.
BRT_SYMBOLS = (
    "AAPL,ABBV,ACN,ADBE,ADI,AMAT,AMD,AMZN,AU,AVGO,BABA,BAC,CDNS,CI,CRM,CRWD,"
    "GOOG,GOOGL,HD,JPM,KR,LYV,META,MPC,MSFT,MU,NEM,NFLX,NVDA,ORCL,PFE,PG,PPTA,"
    "SHOP,TMUS,TSLA,TSM,UNH,V,WFC,WMT,XOM"
)

COMMON_V = [
    "stop_pct=0.934",
    "target_pct=1.21",
    "too_high_multiplier=0",
    "band_pct=0.0154",
    "strong_pre_pivot_pct=0.081",
    "strong_post_pivot_pct=0.108",
    "strong_pre_pivot_bars=7",
    "strong_post_pivot_bars=7",
    "breakout_bars=100",
    "tight_range_threshold_pct=0.35",
    "tight_range_lookback=105",
    "sheet_breakout_scan_start_row_delta=2",
    "brt_sheet_touch=true",
    "min_spy_compare_1y_at_trigger=-12",
    "sheet_red_to_green_entry_enabled=true",
    "sheet_dw_countif_include_prior_bar_date=false",
    "growth_filter_enabled=true",
    "min_ind_score=-1",
    "compute_beta=true",
    "brt_zones=true",
    "yh_zones=false",
    "min_pivot_run_h_before_entry=0",
    "min_beta_at_trigger=0",
]

CANDIDATES = [
    {
        "id": "C0_baseline",
        "label": "Production BRT baseline (no VOL_SURGE gate)",
        "exclude": None,
    },
    {
        "id": "X_BULL",
        "label": "Exclude VOL_SURGE=BULL (= require non-BULL)",
        "exclude": "exclude_ind_states_vol_surge_bull.json",
    },
    {
        "id": "X_BEAR",
        "label": "Exclude VOL_SURGE=BEAR",
        "exclude": "exclude_ind_states_vol_surge_bear.json",
    },
    {
        "id": "X_NEUTRAL",
        "label": "Exclude VOL_SURGE=NEUTRAL",
        "exclude": "exclude_ind_states_vol_surge_neutral.json",
    },
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
        "BRT VOL_SURGE Exclude-Gate Experiment Status",
        f"started_at:     {started_at}",
        f"updated_at:     {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"elapsed:        {_fmt_dur(elapsed)}",
        f"current:        {current_id}",
        f"trials:         {done}/{total} ({pct:.1f}%)",
        f"eta:            {eta}",
        f"concurrency:    {jobs} concurrent jobs x -w {workers}",
        f"note:           {note}".rstrip(),
        "",
        "Watch live: Get-Content -Wait drive\\brt_vol_surge_exp\\status.txt",
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
    report = _find_latest(outdir, "BRT_Report_*.csv")
    if report is None:
        report = _find_latest(outdir, "BRT_Audit_Report_*.csv")
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
        "Max_DD": _safe_num(row.get("Max_DD", row.get("Max_Drawdown", 0))),
        "Profit_Per_Capital_Day": _safe_num(row.get("Profit_Per_Capital_Day", 0)),
        "Ann_ROR": _safe_num(row.get("Ann_ROR", row.get("Annualized_ROR", 0))),
        "Expectancy": _safe_num(row.get("Expectancy", 0)),
        "Avg_PNL_Pct": _safe_num(row.get("Avg_PNL_Pct", 0)),
        "Wins": wins,
        "Losses": losses,
        "BE": bes,
        "Win_Rate": (100.0 * wins / total_trades) if total_trades else 0.0,
        "Pct_PNL_Max_Symbol": _safe_num(row.get("Pct_PNL_Max_Symbol", 0)),
        "Capital_Days": int(_safe_num(row.get("Capital_Days", 0))),
    }


def build_cmd(
    py: str,
    cand: dict,
    outdir: Path,
    workers: int,
    *,
    entry_start: str | None = None,
    entry_end: str | None = None,
) -> list[str]:
    cmd = [
        py,
        str(REPO / "stock_analysis" / "rocket_brt.py"),
        str(DATA_DIR),
        "-o",
        str(outdir),
        "-w",
        str(workers),
        "--aggressive",
        "--no-regression",
        "-s",
        BRT_SYMBOLS,
    ]
    if PS_SETTINGS.is_file():
        cmd.extend(["--per-symbol-settings", str(PS_SETTINGS)])
    for v in COMMON_V:
        cmd.extend(["-v", v])
    if cand.get("exclude"):
        excl = EXP_DIR / cand["exclude"]
        cmd.extend(["-v", f"exclude_ind_states_path={excl}"])
    if entry_start:
        cmd.extend(["-v", f"entry_start_date={entry_start}"])
    if entry_end:
        cmd.extend(["-v", f"entry_end_date={entry_end}"])
    return cmd


def run_candidate(
    py: str,
    cand: dict,
    workers: int,
    *,
    skip_existing: bool = True,
    entry_start: str | None = None,
    entry_end: str | None = None,
    out_subdir: str | None = None,
) -> dict:
    cid = cand["id"]
    folder = out_subdir or cid
    outdir = OUT_ROOT / folder
    outdir.mkdir(parents=True, exist_ok=True)
    log_path = outdir / "run.log"
    if skip_existing and extract_metrics(outdir) is not None:
        m = extract_metrics(outdir)
        return {
            "id": cid,
            "label": cand.get("label", ""),
            "ok": True,
            "exit_code": 0,
            "elapsed_s": 0.0,
            "skipped": True,
            "metrics": m,
            "outdir": str(outdir),
        }
    cmd = build_cmd(
        py, cand, outdir, workers, entry_start=entry_start, entry_end=entry_end
    )
    t0 = time.time()
    with open(log_path, "w", encoding="utf-8", errors="replace") as logf:
        logf.write("CMD: " + " ".join(cmd) + "\n\n")
        logf.flush()
        proc = subprocess.run(
            cmd,
            stdout=logf,
            stderr=subprocess.STDOUT,
            cwd=str(REPO),
        )
    elapsed = time.time() - t0
    m = extract_metrics(outdir)
    return {
        "id": cid,
        "label": cand.get("label", ""),
        "ok": proc.returncode == 0 and m is not None,
        "exit_code": proc.returncode,
        "elapsed_s": elapsed,
        "skipped": False,
        "metrics": m,
        "outdir": str(outdir),
    }


def aggregate(results: list[dict], *, jobs: int, workers: int) -> tuple[Path, Path]:
    by_id = {r["id"]: r for r in results}
    c0 = by_id.get("C0_baseline")
    rows = []
    for r in results:
        m = r.get("metrics") or {}
        trades = int(m.get("Total_Trades", 0) or 0)
        beat = ""
        if c0 and c0.get("metrics") and m and int(c0["metrics"].get("Total_Trades", 0) or 0) > 0:
            c0m = c0["metrics"]
            beat = (
                "Y"
                if (
                    trades > 0
                    and float(m.get("Profit_Per_Capital_Day", 0))
                    > float(c0m.get("Profit_Per_Capital_Day", 0))
                    and float(m.get("Total_PNL", 0)) > float(c0m.get("Total_PNL", 0))
                    and float(m.get("Profit_Factor", 0)) >= float(c0m.get("Profit_Factor", 0))
                    and float(m.get("Max_DD", 99)) <= float(c0m.get("Max_DD", 0)) + 1.0
                )
                else "N"
            )
        rows.append(
            {
                "id": r["id"],
                "label": r.get("label", ""),
                "ok": bool(r.get("ok")),
                "exit_code": r.get("exit_code"),
                "elapsed_s": round(float(r.get("elapsed_s", 0) or 0), 1),
                "skipped": bool(r.get("skipped")),
                "Total_Trades": trades,
                "Total_PNL": round(float(m.get("Total_PNL", 0) or 0), 2),
                "Profit_Factor": round(float(m.get("Profit_Factor", 0) or 0), 3),
                "Max_DD": round(float(m.get("Max_DD", 0) or 0), 2),
                "PPCD": round(float(m.get("Profit_Per_Capital_Day", 0) or 0), 4),
                "Ann_ROR": round(float(m.get("Ann_ROR", 0) or 0), 2),
                "Expectancy": round(float(m.get("Expectancy", 0) or 0), 2),
                "Avg_PNL_Pct": round(float(m.get("Avg_PNL_Pct", 0) or 0), 2),
                "Win_Rate": round(float(m.get("Win_Rate", 0) or 0), 1),
                "Pct_PNL_Max_Symbol": round(float(m.get("Pct_PNL_Max_Symbol", 0) or 0), 1),
                "beat_baseline": beat,
            }
        )

    csv_path = OUT_ROOT / "comparison.csv"
    md_path = OUT_ROOT / "comparison.md"
    if rows:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    ok_rows = [r for r in rows if r["ok"] and r["Total_Trades"] > 0]
    # Prefer multi-metric beat of baseline; else fall back to total PNL (not raw PPCD).
    beaters = [r for r in ok_rows if r.get("beat_baseline") == "Y"]
    if beaters:
        best = max(beaters, key=lambda r: (r["PPCD"], r["Total_PNL"], r["Profit_Factor"]))
    elif ok_rows:
        best = max(ok_rows, key=lambda r: (r["Total_PNL"], r["Profit_Factor"], r["PPCD"]))
    else:
        best = None
    c0r = next((r for r in rows if r["id"] == "C0_baseline"), None)

    lines = [
        "# BRT VOL_SURGE Exclude-Gate — True Capital Backtests",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Concurrency: **{jobs} jobs × {workers} workers**.",
        "Settings: production `run_brt.bat` equivalents (no bat edits).",
        "Gate: optional `exclude_ind_states_path` at trigger bar.",
        "",
        "## Evidence class",
        "",
        "**True portfolio capital backtest** (aggressive equity path). "
        "Distinct from post-hoc closed-trade VOL_SURGE screens.",
        "",
        "## Beat-baseline rule",
        "",
        "Y if PPCD↑ and Total_PNL↑ and PF≥ baseline and MaxDD ≤ baseline+1pp. "
        "High PPCD alone (e.g. after cutting most trades) does **not** win.",
        "",
        "## Results",
        "",
        "| id | trades | PNL | PF | MaxDD | PPCD | AnnROR | Exp | WR% | MaxSym% | beat BL |",
        "|----|-------:|----:|---:|------:|-----:|-------:|----:|----:|--------:|--------:|",
    ]
    for r in rows:
        lines.append(
            f"| {r['id']} | {r['Total_Trades']} | {r['Total_PNL']:.0f} | {r['Profit_Factor']:.3f} | "
            f"{r['Max_DD']:.1f} | {r['PPCD']:.2f} | {r['Ann_ROR']:.1f} | {r['Expectancy']:.2f} | "
            f"{r['Win_Rate']:.1f} | {r['Pct_PNL_Max_Symbol']:.1f} | {r['beat_baseline']} |"
        )

    lines.extend(["", "## Verdict", ""])
    if best and c0r:
        if best.get("beat_baseline") == "Y" and best["id"] != "C0_baseline":
            lines.append(
                f"**Winner: `{best['id']}`** ({best['label']}) — "
                f"PPCD {best['PPCD']:.2f} vs baseline {c0r['PPCD']:.2f}; "
                f"PNL {best['Total_PNL']:.0f} vs {c0r['Total_PNL']:.0f}; "
                f"PF {best['Profit_Factor']:.3f} vs {c0r['Profit_Factor']:.3f}; "
                f"MaxDD {best['Max_DD']:.1f} vs {c0r['Max_DD']:.1f}."
            )
            harmful = best["id"].replace("X_", "")
        else:
            lines.append(
                "**Winner: baseline.** No VOL_SURGE exclusion beat production on the multi-metric rule."
            )
            harmful = "BULL (post-hoc only; BT inconclusive)"
        xn = next((r for r in rows if r["id"] == "X_NEUTRAL"), None)
        if xn and xn["PPCD"] > c0r["PPCD"] and xn.get("beat_baseline") != "Y":
            lines.append(
                f"Note: `X_NEUTRAL` PPCD looks high ({xn['PPCD']:.2f}) but fails beat rule "
                f"(PNL {xn['Total_PNL']:.0f}≪{c0r['Total_PNL']:.0f}, PF {xn['Profit_Factor']:.3f}, "
                f"MaxDD {xn['Max_DD']:.1f}, MaxSym% {xn['Pct_PNL_Max_Symbol']:.1f})."
            )
        lines.append("")
        lines.append(f"**Harmful state (true BT + post-hoc):** **{harmful}**.")
    lines.append("")
    lines.append("Do **not** change `run_brt.bat` unless OOS also confirms.")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return csv_path, md_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--workers", "-w", type=int, default=10)
    ap.add_argument("--no-skip", action="store_true")
    ap.add_argument("--ids", type=str, default="", help="Comma subset of candidate ids")
    args = ap.parse_args()
    jobs = max(1, int(args.jobs))
    workers = max(1, int(args.workers))
    py = _resolve_python()
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    cands = CANDIDATES
    if args.ids.strip():
        want = {x.strip() for x in args.ids.split(",") if x.strip()}
        cands = [c for c in CANDIDATES if c["id"] in want]

    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    t0 = time.time()
    write_status(
        started_at=started_at,
        session_start=t0,
        current_id="starting",
        done=0,
        total=len(cands),
        note="queued",
        jobs=jobs,
        workers=workers,
    )
    (OUT_ROOT / "manifest.json").write_text(
        json.dumps({"candidates": cands, "common_v": COMMON_V, "symbols": BRT_SYMBOLS}, indent=2),
        encoding="utf-8",
    )

    results: list[dict] = []
    done = 0
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        futs = {
            ex.submit(
                run_candidate, py, cand, workers, skip_existing=not args.no_skip
            ): cand
            for cand in cands
        }
        for fut in as_completed(futs):
            cand = futs[fut]
            try:
                r = fut.result()
            except Exception as exc:  # noqa: BLE001
                r = {
                    "id": cand["id"],
                    "label": cand.get("label", ""),
                    "ok": False,
                    "exit_code": -1,
                    "elapsed_s": 0.0,
                    "metrics": None,
                    "error": str(exc),
                }
            results.append(r)
            done += 1
            note = "ok" if r.get("ok") else f"FAIL exit={r.get('exit_code')}"
            if r.get("skipped"):
                note = "skipped (existing)"
            write_status(
                started_at=started_at,
                session_start=t0,
                current_id=cand["id"],
                done=done,
                total=len(cands),
                note=note,
                jobs=jobs,
                workers=workers,
            )

    results.sort(key=lambda r: r["id"])
    csv_path, md_path = aggregate(results, jobs=jobs, workers=workers)
    write_status(
        started_at=started_at,
        session_start=t0,
        current_id="done",
        done=len(cands),
        total=len(cands),
        note=f"wrote {csv_path.name}",
        jobs=jobs,
        workers=workers,
    )
    print(f"[done] {csv_path}")
    print(f"[done] {md_path}")
    return 0 if all(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
