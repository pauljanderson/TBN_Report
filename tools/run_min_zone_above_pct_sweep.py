#!/usr/bin/env python3
"""Sweep BRT min_zone_above_pct holding sheet-like MarkTen baseline fixed.

Baseline mirrors stamp 260721091813 (trigger_low / stop_pct=0.921 / MarkTen 10).
Outputs under drive/experiments/min_zone_above_pct_sweep/.
"""
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT_ROOT = REPO / "drive" / "experiments" / "min_zone_above_pct_sweep"
DATA_DIR = REPO / "data" / "newdata" / "data"
STATUS_PATH = OUT_ROOT / "status.txt"

# Stamp 260721091813 universe + settings (sheet-like stop path).
SYMBOLS = "AAPL,AMD,AMZN,AU,GOOGL,META,MSFT,NFLX,NVDA,TSLA"
COMMON_V = [
    "stop_pct=0.921",
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
    "min_spy_compare_1y_at_trigger=-1000",
    "sheet_red_to_green_entry_enabled=true",
    "sheet_dw_countif_include_prior_bar_date=false",
    "growth_filter_enabled=true",
    "min_ind_score=-1",
    "compute_beta=true",
    "brt_zones=true",
    "yh_zones=false",
    "min_pivot_run_h_before_entry=0",
    "min_beta_at_trigger=0",
    "stop_loss_based=trigger_low",
]

DEFAULT_GRID = [0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10, 0.12, 0.15, 0.20]


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


def _tag(val: float) -> str:
    if abs(val) < 1e-12:
        return "0"
    s = f"{val:.4f}".rstrip("0").rstrip(".")
    return s.replace(".", "p")


def extract_metrics(outdir: Path) -> dict | None:
    report = _find_latest(outdir, "BRT_Report_*.csv")
    if report is None:
        report = _find_latest(outdir, "BRT_Audit_Report_*.csv")
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
    stamp = ""
    ts = str(row.get("Timestamp_Drive", "") or "")
    if "260" in ts:
        # hyperlink cell: ...q=STAMP...
        import re

        m = re.search(r"q=(\d{12})", ts)
        if m:
            stamp = m.group(1)
    if not stamp:
        stamp = report.name.replace("BRT_Report_", "").replace(".csv", "")
    return {
        "report_file": report.name,
        "stamp": stamp,
        "Total_Trades": total_trades,
        "Total_PNL": _safe_num(row.get("Total_PNL", 0)),
        "Aggressive_Total_PNL": _safe_num(row.get("Aggressive_Total_PNL", 0)),
        "Profit_Factor": _safe_num(row.get("Profit_Factor", 0)),
        "Max_DD": _safe_num(row.get("Max_DD", row.get("Max_Drawdown", 0))),
        "Aggressive_Max_DD": _safe_num(row.get("Aggressive_Max_DD", 0)),
        "Profit_Per_Capital_Day": _safe_num(row.get("Profit_Per_Capital_Day", 0)),
        "Ann_ROR": _safe_num(row.get("Ann_ROR", row.get("Annualized_ROR", 0))),
        "Expectancy": _safe_num(row.get("Expectancy", 0)),
        "Avg_PNL_Pct": _safe_num(row.get("Avg_PNL_Pct", 0)),
        "Wins": wins,
        "Losses": losses,
        "BE": bes,
        "Win_Rate": (100.0 * wins / total_trades) if total_trades else 0.0,
        "Win_Loss_Ratio": _safe_num(row.get("Win_Loss_Ratio", 0)),
        "min_zone_above_pct_reported": row.get("min_zone_above_pct", ""),
        "stop_loss_based": row.get("stop_loss_based", ""),
        "stop_pct": row.get("stop_pct", ""),
    }


def write_status(*, started_at: str, t0: float, current: str, done: int, total: int, note: str = "") -> None:
    elapsed = time.time() - t0
    remaining = max(0, total - done)
    eta = (
        _fmt_dur((elapsed / done) * remaining)
        if done > 0 and remaining > 0
        else ("0s (done)" if remaining == 0 else "estimating...")
    )
    pct = (100.0 * done / total) if total else 100.0
    lines = [
        "BRT min_zone_above_pct Sweep Status",
        f"started_at:     {started_at}",
        f"updated_at:     {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"elapsed:        {_fmt_dur(elapsed)}",
        f"current:        {current}",
        f"trials:         {done}/{total} ({pct:.1f}%)",
        f"eta:            {eta}",
        f"baseline:       stamp 260721091813 (trigger_low, stop_pct=0.921, MarkTen10)",
        f"note:           {note}".rstrip(),
        "",
        f"Watch: Get-Content -Wait {STATUS_PATH}",
    ]
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  [status] {_fmt_dur(elapsed)}  {done}/{total}  {current}  {note}")


def build_cmd(py: str, outdir: Path, workers: int, mza: float) -> list[str]:
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
        SYMBOLS,
    ]
    for v in COMMON_V:
        cmd.extend(["-v", v])
    cmd.extend(["-v", f"min_zone_above_pct={mza}"])
    return cmd


def run_one(py: str, mza: float, workers: int, *, skip_existing: bool) -> dict:
    tag = _tag(mza)
    outdir = OUT_ROOT / f"mza_{tag}"
    outdir.mkdir(parents=True, exist_ok=True)
    log_path = outdir / "run.log"
    if skip_existing:
        m = extract_metrics(outdir)
        if m is not None:
            return {
                "min_zone_above_pct": mza,
                "tag": tag,
                "ok": True,
                "exit_code": 0,
                "elapsed_s": 0.0,
                "skipped": True,
                "metrics": m,
                "outdir": str(outdir),
            }
    cmd = build_cmd(py, outdir, workers, mza)
    t0 = time.time()
    with open(log_path, "w", encoding="utf-8", errors="replace") as logf:
        logf.write("CMD: " + " ".join(cmd) + "\n\n")
        logf.flush()
        proc = subprocess.run(cmd, stdout=logf, stderr=subprocess.STDOUT, cwd=str(REPO))
    elapsed = time.time() - t0
    m = extract_metrics(outdir)
    return {
        "min_zone_above_pct": mza,
        "tag": tag,
        "ok": proc.returncode == 0 and m is not None,
        "exit_code": proc.returncode,
        "elapsed_s": elapsed,
        "skipped": False,
        "metrics": m,
        "outdir": str(outdir),
    }


def aggregate(results: list[dict]) -> tuple[Path, Path]:
    rows = []
    for r in results:
        m = r.get("metrics") or {}
        rows.append(
            {
                "min_zone_above_pct": r["min_zone_above_pct"],
                "tag": r["tag"],
                "ok": bool(r.get("ok")),
                "exit_code": r.get("exit_code"),
                "elapsed_s": round(float(r.get("elapsed_s", 0) or 0), 1),
                "skipped": bool(r.get("skipped")),
                "stamp": m.get("stamp", ""),
                "Total_Trades": int(m.get("Total_Trades", 0) or 0),
                "Wins": int(m.get("Wins", 0) or 0),
                "Losses": int(m.get("Losses", 0) or 0),
                "Win_Rate": round(float(m.get("Win_Rate", 0) or 0), 2),
                "Win_Loss_Ratio": round(float(m.get("Win_Loss_Ratio", 0) or 0), 3),
                "Total_PNL": round(float(m.get("Total_PNL", 0) or 0), 2),
                "Aggressive_Total_PNL": round(float(m.get("Aggressive_Total_PNL", 0) or 0), 2),
                "Avg_PNL_Pct": round(float(m.get("Avg_PNL_Pct", 0) or 0), 2),
                "Profit_Factor": round(float(m.get("Profit_Factor", 0) or 0), 3),
                "Max_DD": round(float(m.get("Max_DD", 0) or 0), 2),
                "Aggressive_Max_DD": round(float(m.get("Aggressive_Max_DD", 0) or 0), 2),
                "PPCD": round(float(m.get("Profit_Per_Capital_Day", 0) or 0), 4),
                "Ann_ROR": round(float(m.get("Ann_ROR", 0) or 0), 2),
                "Expectancy": round(float(m.get("Expectancy", 0) or 0), 2),
                "outdir": r.get("outdir", ""),
            }
        )

    csv_path = OUT_ROOT / "comparison.csv"
    md_path = OUT_ROOT / "comparison.md"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["min_zone_above_pct"])
        if rows:
            w.writeheader()
            w.writerows(rows)

    ok = [r for r in rows if r["ok"] and r["Total_Trades"] > 0]
    baseline = next((r for r in ok if abs(float(r["min_zone_above_pct"])) < 1e-12), None)

    def score(r: dict) -> tuple:
        # Primary: Total_PNL then Avg_PNL_Pct; soft-penalize tiny N and much worse DD.
        n = r["Total_Trades"]
        n_pen = 0 if (baseline is None or n >= 0.7 * baseline["Total_Trades"]) else -1e9
        dd_pen = 0.0
        if baseline is not None and r["Max_DD"] > baseline["Max_DD"] + 3.0:
            dd_pen = -1e6 * (r["Max_DD"] - baseline["Max_DD"])
        return (r["Total_PNL"] + n_pen + dd_pen, r["Avg_PNL_Pct"], r["Profit_Factor"], -r["Max_DD"])

    best = max(ok, key=score) if ok else None

    lines = [
        "# BRT `min_zone_above_pct` Sweep",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Baseline (held fixed)",
        "",
        "- Reference stamp: `260721091813`",
        "- `stop_loss_based=trigger_low` (sheet-like)",
        "- `stop_pct=0.921`, `target_pct=1.21`, MarkTen10 symbols",
        "- Only `min_zone_above_pct` varies",
        "",
        "## Results",
        "",
        "| mza | N | WR% | W/L | Total PNL $ | Agg PNL $ | Avg PNL% | PF | MaxDD | AggDD | stamp |",
        "|----:|--:|----:|----:|------------:|----------:|---------:|---:|------:|------:|------:|",
    ]
    for r in rows:
        lines.append(
            f"| {r['min_zone_above_pct']:.2f} | {r['Total_Trades']} | {r['Win_Rate']:.1f} | "
            f"{r['Win_Loss_Ratio']:.2f} | {r['Total_PNL']:.0f} | {r['Aggressive_Total_PNL']:.0f} | "
            f"{r['Avg_PNL_Pct']:.2f} | {r['Profit_Factor']:.2f} | {r['Max_DD']:.2f} | "
            f"{r['Aggressive_Max_DD']:.2f} | {r['stamp']} |"
        )

    lines.extend(["", "## Verdict", ""])
    if best and baseline:
        delta_pnl = best["Total_PNL"] - baseline["Total_PNL"]
        delta_avg = best["Avg_PNL_Pct"] - baseline["Avg_PNL_Pct"]
        delta_n = best["Total_Trades"] - baseline["Total_Trades"]
        delta_dd = best["Max_DD"] - baseline["Max_DD"]
        if abs(float(best["min_zone_above_pct"])) < 1e-12:
            lines.append(
                "**Winner: `min_zone_above_pct = 0` (off).** No tested threshold beat baseline on "
                "Total PNL / Avg PNL% without a large sample or DD penalty."
            )
        else:
            lines.append(
                f"**Winner: `min_zone_above_pct = {best['min_zone_above_pct']}`** — "
                f"Total PNL ${best['Total_PNL']:.0f} ({delta_pnl:+.0f} vs 0), "
                f"Avg PNL% {best['Avg_PNL_Pct']:.2f} ({delta_avg:+.2f}), "
                f"N={best['Total_Trades']} ({delta_n:+d}), "
                f"MaxDD {best['Max_DD']:.2f} ({delta_dd:+.2f}pp)."
            )
        lines.append("")
        lines.append(
            f"Baseline (0): PNL ${baseline['Total_PNL']:.0f}, Avg {baseline['Avg_PNL_Pct']:.2f}%, "
            f"N={baseline['Total_Trades']}, WR {baseline['Win_Rate']:.1f}%, "
            f"W/L {baseline['Win_Loss_Ratio']:.2f}, MaxDD {baseline['Max_DD']:.2f}."
        )
    elif best:
        lines.append(f"**Winner: `min_zone_above_pct = {best['min_zone_above_pct']}`** (no baseline row).")
    else:
        lines.append("No successful runs.")

    lines.extend(
        [
            "",
            "## Caveats",
            "",
            "- MarkTen-only universe (10 symbols).",
            "- Aggressive equity path; compare MaxDD / Aggressive_Max_DD before promoting.",
            "- Results folder: `drive/experiments/min_zone_above_pct_sweep/`.",
            "",
        ]
    )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return csv_path, md_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--skip-existing", action="store_true", default=True)
    ap.add_argument("--force", action="store_true", help="Re-run even if metrics exist")
    ap.add_argument(
        "--grid",
        default=",".join(str(x) for x in DEFAULT_GRID),
        help="Comma-separated min_zone_above_pct values",
    )
    args = ap.parse_args()
    grid = [float(x.strip()) for x in args.grid.split(",") if x.strip()]
    skip = False if args.force else True
    py = _resolve_python()
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    t0 = time.time()
    results: list[dict] = []
    write_status(started_at=started_at, t0=t0, current="starting", done=0, total=len(grid))
    for i, mza in enumerate(grid):
        write_status(
            started_at=started_at,
            t0=t0,
            current=f"mza={mza}",
            done=i,
            total=len(grid),
            note="running",
        )
        r = run_one(py, mza, args.workers, skip_existing=skip)
        results.append(r)
        note = "skip" if r.get("skipped") else ("ok" if r.get("ok") else f"fail exit={r.get('exit_code')}")
        write_status(
            started_at=started_at,
            t0=t0,
            current=f"mza={mza}",
            done=i + 1,
            total=len(grid),
            note=note,
        )
        m = r.get("metrics") or {}
        print(
            f"  mza={mza}: ok={r.get('ok')} N={m.get('Total_Trades')} "
            f"PNL={m.get('Total_PNL')} Avg%={m.get('Avg_PNL_Pct')} "
            f"DD={m.get('Max_DD')} stamp={m.get('stamp')} ({_fmt_dur(r.get('elapsed_s', 0))})"
        )

    csv_path, md_path = aggregate(results)
    write_status(
        started_at=started_at,
        t0=t0,
        current="done",
        done=len(grid),
        total=len(grid),
        note=f"wrote {csv_path.name}",
    )
    print(f"\nWrote {csv_path}")
    print(f"Wrote {md_path}")
    return 0 if all(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
