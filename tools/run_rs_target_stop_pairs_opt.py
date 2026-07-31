#!/usr/bin/env python3
"""RS target_pct/stop_pct risk-% pair sweep (tighten both sides from 25/12).

Mapping: target_pct = 1 + target%/100; stop_pct = 1 - risk%/100.
stop_pct_is_multiplier=true. Baseline 1.25/0.88 reuses stamp 260724113037.

Outputs: drive/paul_experiments/rs_one_flag_score_opt/target_stop_pairs_riskpct_12/
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
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

OUT_ROOT = REPO / "drive" / "paul_experiments" / "rs_one_flag_score_opt" / "target_stop_pairs_riskpct_12"
BASELINE_SRC = REPO / "drive" / "paul_experiments" / "rs_one_flag_score_opt" / "baseline"
BASELINE_STAMP = "260724113037"
DATA_DIR = REPO / "data" / "newdata" / "data"
BAT_PATH = REPO / "run_rs.bat"
TARGET_TRADES = 700.0

# (user_target_pct, user_risk_pct, target_pct, stop_pct)  stop_pct = 1 - risk%/100
PAIRS = [
    (25.0, 12.0, 1.25, 0.88),
    (22.5, 10.8, 1.225, 0.892),
    (20.0, 9.6, 1.20, 0.904),
    (17.5, 8.4, 1.175, 0.916),
    (15.0, 7.2, 1.15, 0.928),
    (12.5, 6.0, 1.125, 0.94),
    (10.0, 4.8, 1.10, 0.952),
    (7.5, 3.6, 1.075, 0.964),
    (5.0, 2.4, 1.05, 0.976),
    (2.5, 1.2, 1.025, 0.988),
]

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
    "atr_days=0",
    "atr_progress=0",
    "trailing_stop_increment=0",
    "sma_stop_days=0",
    "symbol_reentry_cooldown_days=0",
]

W = {
    "ppcd": 15.0,
    "pnl": 15.0,
    "dd": 15.0,
    "pf": 15.0,
    "exp_pct": 15.0,
    "wlr": 10.0,
    "streak": 10.0,
    "p90": 5.0,
}


def load_symbols_from_bat() -> str:
    text = BAT_PATH.read_text(encoding="utf-8", errors="replace")
    matches = re.findall(
        r'^[ \t]*if not defined RS_SYMBOLS set "RS_SYMBOLS=([^"]+)"',
        text,
        flags=re.MULTILINE,
    )
    if not matches:
        raise SystemExit(f"Could not parse RS_SYMBOLS from {BAT_PATH}")
    return matches[-1].strip()


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


def _pair_label(target_pct: float, stop_pct: float) -> str:
    def _t(v: float) -> str:
        s = f"{v:.6f}".rstrip("0").rstrip(".")
        return s.replace(".", "p")

    return f"pair_t{_t(target_pct)}_s{_t(stop_pct)}"


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
    wlr = _safe_num(row.get("Win_Loss_Ratio", 0))
    if wlr <= 0:
        wlr = (wins / losses) if losses > 0 else (10.0 if wins > 0 else 0.0)
    stamp = ""
    m = re.search(r"_(\d{12})\.csv$", report.name)
    if m:
        stamp = m.group(1)
    return {
        "report": str(report.name),
        "stamp": stamp,
        "trades": total_trades,
        "wins": wins,
        "losses": losses,
        "wr": wr,
        "wlr": wlr,
        "pf": _safe_num(row.get("Profit_Factor", 0)),
        "pnl": _safe_num(row.get("Total_PNL", 0)),
        "maxdd": abs(_safe_num(row.get("Max_DD", 0))),
        "expectancy": _safe_num(row.get("Expectancy", 0)),
        "expectancy_pct": _safe_num(row.get("Expectancy_Pct", row.get("Avg_PNL_Pct", 0))),
        "ppcd": _safe_num(row.get("Profit_Per_Capital_Day", 0)),
        "avg_days_held": _safe_num(row.get("Avg_Days_Held", 0)),
        "median_days_held": _safe_num(row.get("Median_Days_Held", 0)),
        "p90_days": _safe_num(row.get("P90_Days", 0)),
        "losing_streak": int(_safe_num(row.get("Losing_Streak", 0))),
        "ann_ror": _safe_num(row.get("Ann_ROR", 0)),
    }


def ratio_higher(v: float, b: float) -> float:
    if b == 0:
        return 1.0 if v == 0 else (2.0 if v > 0 else 0.0)
    return v / b


def ratio_lower(v: float, b: float) -> float:
    if v == 0:
        return 2.0 if b > 0 else 1.0
    if b == 0:
        return 1.0
    return b / v


def composite_score(row: dict, baseline: dict) -> float:
    s = 0.0
    s += ratio_higher(float(row.get("ppcd") or 0), float(baseline.get("ppcd") or 0)) * (W["ppcd"] / 100)
    s += ratio_higher(float(row.get("pnl") or 0), float(baseline.get("pnl") or 0)) * (W["pnl"] / 100)
    s += ratio_lower(float(row.get("maxdd") or 0), float(baseline.get("maxdd") or 0)) * (W["dd"] / 100)
    s += ratio_higher(float(row.get("pf") or 0), float(baseline.get("pf") or 0)) * (W["pf"] / 100)
    s += ratio_higher(float(row.get("expectancy_pct") or 0), float(baseline.get("expectancy_pct") or 0)) * (
        W["exp_pct"] / 100
    )
    s += ratio_higher(float(row.get("wlr") or 0), float(baseline.get("wlr") or 0)) * (W["wlr"] / 100)
    s += ratio_lower(float(row.get("losing_streak") or 0), float(baseline.get("losing_streak") or 0)) * (
        W["streak"] / 100
    )
    s += ratio_lower(float(row.get("p90_days") or 0), float(baseline.get("p90_days") or 0)) * (W["p90"] / 100)
    return s * 100.0


def trade_proximity(trades: float) -> float:
    return abs(float(trades or 0) - TARGET_TRADES)


def reuse_baseline(outdir: Path) -> Optional[dict]:
    src_report = BASELINE_SRC / f"RS_Report_{BASELINE_STAMP}.csv"
    if not src_report.is_file():
        return None
    outdir.mkdir(parents=True, exist_ok=True)
    for src in BASELINE_SRC.glob(f"*_{BASELINE_STAMP}.*"):
        dst = outdir / src.name
        if not dst.exists():
            shutil.copy2(src, dst)
    (outdir / "REUSED_BASELINE.txt").write_text(
        f"Reused stamp {BASELINE_STAMP} from {BASELINE_SRC}\n"
        "Identical flags: target_pct=1.25 stop_pct=0.88 stop_pct_is_multiplier=true "
        "(one-flag BASE_V / atr_days=0).\n",
        encoding="utf-8",
    )
    return extract_metrics(outdir)


def run_one(
    *,
    label: str,
    user_target: float,
    user_stop: float,
    target_pct: float,
    stop_pct: float,
    outdir: Path,
    py: str,
    workers: int,
    symbols: str,
    skip_existing: bool,
    reuse_baseline_stamp: bool,
) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    meta = {
        "label": label,
        "user_target": user_target,
        "user_stop": user_stop,
        "target_pct": target_pct,
        "stop_pct": stop_pct,
        "stop_pct_is_multiplier": True,
        "outdir": str(outdir),
    }

    if reuse_baseline_stamp and abs(target_pct - 1.25) < 1e-12 and abs(stop_pct - 0.88) < 1e-12:
        metrics = reuse_baseline(outdir)
        if metrics and metrics.get("trades"):
            print(f"[reuse] {label} stamp={metrics.get('stamp')} trades={metrics['trades']}", flush=True)
            return {**meta, "exit_code": 0, "elapsed_s": 0.0, "skipped": 1, "reused": 1, **metrics}

    if skip_existing:
        existing = extract_metrics(outdir)
        if existing and existing.get("trades"):
            print(f"[skip] {label} (existing trades={existing['trades']})", flush=True)
            return {**meta, "exit_code": 0, "elapsed_s": 0.0, "skipped": 1, "reused": 0, **existing}

    merged: dict[str, str] = {}
    for item in BASE_V + [f"target_pct={target_pct}", f"stop_pct={stop_pct}"]:
        if "=" not in item:
            continue
        k, v = item.split("=", 1)
        merged[k] = v

    cmd = [
        py,
        str(SA / "rocket_brt.py"),
        str(DATA_DIR),
        "-o",
        str(outdir),
        "-w",
        str(workers),
        "--no-regression",
        "--aggressive",
        "--no-yfinance",
        "--relative-strength",
        "-s",
        symbols,
    ]
    for k, v in merged.items():
        cmd.extend(["-v", f"{k}={v}"])

    t0 = time.perf_counter()
    log_path = outdir / "run.log"
    print(f"[run] {label} target={target_pct} stop={stop_pct} -> {outdir.name}", flush=True)
    with open(log_path, "w", encoding="utf-8", errors="replace") as log:
        log.write("CMD: " + " ".join(cmd) + "\n\n")
        proc = subprocess.run(cmd, cwd=str(REPO), stdout=log, stderr=subprocess.STDOUT)
    elapsed = time.perf_counter() - t0
    metrics = extract_metrics(outdir) or {}
    row = {
        **meta,
        "exit_code": proc.returncode,
        "elapsed_s": round(elapsed, 1),
        "skipped": 0,
        "reused": 0,
        **metrics,
    }
    print(
        f"[done] {label} exit={proc.returncode} {elapsed:.0f}s "
        f"trades={row.get('trades', '?')} PF={row.get('pf', '?')} "
        f"PNL={row.get('pnl', '?')} Ann_ROR={row.get('ann_ror', '?')}",
        flush=True,
    )
    return row


def write_outputs(rows: list[dict], n_sym: int) -> tuple[Path, Path]:
    baseline = next(
        (
            r
            for r in rows
            if abs(float(r.get("target_pct") or 0) - 1.25) < 1e-12
            and abs(float(r.get("stop_pct") or 0) - 0.88) < 1e-12
        ),
        None,
    )
    scored: list[dict] = []
    for r in rows:
        rr = dict(r)
        if baseline and int(r.get("exit_code", 1)) == 0 and r.get("trades") is not None:
            rr["score"] = round(composite_score(r, baseline), 4)
            rr["trade_proximity_700"] = round(trade_proximity(r.get("trades") or 0), 1)
        else:
            rr["score"] = None
            rr["trade_proximity_700"] = None
        scored.append(rr)

    def _rank_key(r: dict) -> tuple:
        sc = r.get("score")
        if sc is None:
            return (-1e18, -1e18, -1e18)
        return (float(sc), -float(r.get("trade_proximity_700") or 1e9), float(r.get("pnl") or 0))

    ranked = sorted(scored, key=_rank_key, reverse=True)

    fields = [
        "rank",
        "label",
        "user_target",
        "user_stop",
        "target_pct",
        "stop_pct",
        "stop_pct_is_multiplier",
        "score",
        "trades",
        "pf",
        "pnl",
        "maxdd",
        "expectancy_pct",
        "ppcd",
        "avg_days_held",
        "p90_days",
        "wlr",
        "losing_streak",
        "ann_ror",
        "trade_proximity_700",
        "stamp",
        "exit_code",
        "elapsed_s",
        "skipped",
        "reused",
        "report",
        "outdir",
    ]
    rank_path = OUT_ROOT / "ranking.csv"
    with open(rank_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for i, r in enumerate(ranked, 1):
            r["rank"] = i
            w.writerow(r)

    by_label = {r["label"]: r for r in scored}
    ordered = []
    for ut, us, tp, sp in PAIRS:
        lab = _pair_label(tp, sp)
        if lab in by_label:
            ordered.append(by_label[lab])

    lines = [
        "# RS target/stop pair optimization (risk-% mapping)",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        f"Universe: **{n_sym}** symbols from `run_rs.bat`.",
        "Workers: `-w 1` per job; pairs parallelized. `stop_pct_is_multiplier=true`.",
        "Mapping: `target_pct=1+target%/100`, `stop_pct=1-risk%/100` (NOT display/10).",
        f"Flags match one-flag BASE_V (atr_days=0) so baseline stamp `{BASELINE_STAMP}` is identical.",
        "",
        "Risk ratio preserved vs production: risk%/target% = 12/25 = 0.48 (both sides tighten together).",
        "",
        "## Score (baseline = 100)",
        "",
        "- 15% each: PPCD, PNL, MaxDD (lower better), Profit Factor, Expectancy_Pct",
        "- 10% each: Win_Loss_Ratio (wins/losses), Losing_Streak (lower better)",
        "- 5%: P90_Days (lower better)",
        "- Soft tie-break: trade count nearer ~700",
        "",
    ]
    if baseline:
        lines += [
            "## Baseline (first pair)",
            "",
            f"- Stamp: `{baseline.get('stamp', '')}` (reused={baseline.get('reused', 0)})",
            f"- target_pct={baseline.get('target_pct')} stop_pct={baseline.get('stop_pct')}",
            f"- Trades: {baseline.get('trades')} | PF: {baseline.get('pf')} | "
            f"PNL: {baseline.get('pnl')} | MaxDD: {baseline.get('maxdd')} | "
            f"PPCD: {baseline.get('ppcd')} | Exp%: {baseline.get('expectancy_pct')} | "
            f"Ann_ROR: {baseline.get('ann_ror')} | AvgDays: {baseline.get('avg_days_held')} | "
            f"P90: {baseline.get('p90_days')}",
            "",
        ]

    non_base = [
        r
        for r in ranked
        if not (
            abs(float(r.get("target_pct") or 0) - 1.25) < 1e-12
            and abs(float(r.get("stop_pct") or 0) - 0.88) < 1e-12
        )
        and r.get("score") is not None
    ]
    best = non_base[0] if non_base else None
    lines += ["## Recommendation", ""]
    if best:
        lines.append(
            f"- **Best pair vs baseline:** `{best['label']}` "
            f"(target%={best.get('user_target')} risk%={best.get('user_stop')}, "
            f"target_pct={best.get('target_pct')}, stop_pct={best.get('stop_pct')}) "
            f"score={best.get('score')} trades={best.get('trades')} "
            f"Ann_ROR={best.get('ann_ror')}"
        )
    else:
        lines.append("- Waiting for non-baseline arms.")

    lines += [
        "",
        "## Comparison (all pairs vs baseline)",
        "",
        "| Rank | Label | Target%+Risk% | target_pct | stop_pct | Score | Trades | PF | PNL | MaxDD | Exp% | PPCD | AvgDays | P90 | W/L | Streak | Ann_ROR |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    rank_by_label = {r["label"]: r.get("rank") for r in ranked}
    for r in ordered:
        sc = r.get("score")
        sc_s = f"{float(sc):.2f}" if sc is not None else ""
        lines.append(
            f"| {rank_by_label.get(r['label'], '')} | {r.get('label')} | "
            f"{r.get('user_target')}+{r.get('user_stop')} | "
            f"{r.get('target_pct')} | {r.get('stop_pct')} | {sc_s} | "
            f"{r.get('trades', '')} | {float(r.get('pf') or 0):.2f} | "
            f"{float(r.get('pnl') or 0):.0f} | {float(r.get('maxdd') or 0):.2f} | "
            f"{float(r.get('expectancy_pct') or 0):.2f} | {float(r.get('ppcd') or 0):.3f} | "
            f"{float(r.get('avg_days_held') or 0):.1f} | {float(r.get('p90_days') or 0):.0f} | "
            f"{float(r.get('wlr') or 0):.3f} | {r.get('losing_streak', '')} | "
            f"{float(r.get('ann_ror') or 0):.2f} |"
        )

    lines += [
        "",
        "## Notes",
        "",
        "- First pair is production-equivalent (1.25 / 0.88); metrics reused from "
        f"`{BASELINE_STAMP}` when available.",
        f"- Artifacts: `{rank_path.name}`, per-pair folders under `{OUT_ROOT}`.",
        "- Current `run_rs.bat` may set atr_days=60; this sweep keeps atr_days=0 to "
        "match the one-flag baseline stamp.",
        "",
    ]
    md_path = OUT_ROOT / "RESULTS.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return rank_path, md_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--parallel-runs", type=int, default=5)
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument("--no-reuse-baseline", action="store_true")
    ap.add_argument("--symbols", default="")
    args = ap.parse_args()

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    # Drop obsolete arms from prior incorrect pair list
    keep = {_pair_label(tp, sp) for _, _, tp, sp in PAIRS}
    for child in list(OUT_ROOT.iterdir()):
        if child.is_dir() and child.name.startswith("pair_") and child.name not in keep:
            print(f"[drop] obsolete arm dir {child.name}", flush=True)
            # leave files but exclude from RESULTS; rename aside
            aside = OUT_ROOT / "_obsolete" / child.name
            aside.parent.mkdir(parents=True, exist_ok=True)
            if not aside.exists():
                child.rename(aside)

    symbols = args.symbols.strip() or load_symbols_from_bat()
    n_sym = len([s for s in symbols.split(",") if s.strip()])
    py = _resolve_python()

    jobs = []
    for ut, us, tp, sp in PAIRS:
        lab = _pair_label(tp, sp)
        jobs.append((lab, ut, us, tp, sp, OUT_ROOT / lab))

    print(
        f"[plan] {len(jobs)} pairs | {n_sym} symbols | w={args.workers} | "
        f"parallel={args.parallel_runs} | -> {OUT_ROOT}",
        flush=True,
    )

    rows: list[dict] = []
    reuse = not args.no_reuse_baseline

    def _job(j):
        lab, ut, us, tp, sp, od = j
        return run_one(
            label=lab,
            user_target=ut,
            user_stop=us,
            target_pct=tp,
            stop_pct=sp,
            outdir=od,
            py=py,
            workers=args.workers,
            symbols=symbols,
            skip_existing=args.skip_existing,
            reuse_baseline_stamp=reuse,
        )

    if args.parallel_runs <= 1:
        for j in jobs:
            rows.append(_job(j))
            write_outputs(rows, n_sym)
    else:
        with ThreadPoolExecutor(max_workers=args.parallel_runs) as ex:
            futs = {ex.submit(_job, j): j[0] for j in jobs}
            for fut in as_completed(futs):
                rows.append(fut.result())
                write_outputs(rows, n_sym)

    rank_path, md_path = write_outputs(rows, n_sym)
    print(f"[ok] ranking={rank_path}", flush=True)
    print(f"[ok] results={md_path}", flush=True)
    failed = [r for r in rows if int(r.get("exit_code", 1)) != 0]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
