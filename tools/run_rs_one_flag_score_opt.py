#!/usr/bin/env python3
"""One-flag-at-a-time RS score optimization (run_rs.bat parity).

Baseline: current run_rs.bat universe + flags, -w 1, sequential runs.
Each arm changes exactly one -v flag (or one boolean gate) around a center
(median from Closed_260723221911 when sensible, else bat constant).

Composite score (relative to baseline; baseline=100):
  15% each: PPCD, PNL, MaxDD (lower better), Profit Factor, Expectancy_Pct
  10% each: Win_Loss_Ratio (wins/losses), Losing_Streak (lower better)
  5%: P90_Days (lower better)
Soft tie-break: prefer trade count nearer ~700.

Outputs: drive/paul_experiments/rs_one_flag_score_opt/
  summary.csv, ranking.csv, RESULTS.md, per-arm folders
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
SA = REPO / "stock_analysis"
for p in (REPO, SA):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

OUT_ROOT = REPO / "drive" / "paul_experiments" / "rs_one_flag_score_opt"
DATA_DIR = REPO / "data" / "newdata" / "data"
BAT_PATH = REPO / "run_rs.bat"

TARGET_PCT = 1.25
STOP_PCT = 0.88
TARGET_TRADES = 700.0

# Soft defaults matching run_rs.bat (O'Neil off; spy_compare min neutralized).
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
    "atr_target=0",
    "atr_stop=0",
    "atr_days=0",
    "atr_progress=0",
    "trailing_stop_increment=0",
    "sma_stop_days=0",
    "symbol_reentry_cooldown_days=0",
]

# Weights sum to 100.
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
    # Prefer the last active (non-rem) RS_SYMBOLS assignment.
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


def _tag(val: Any) -> str:
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, float):
        s = f"{val:.4f}".rstrip("0").rstrip(".")
        return s.replace(".", "p").replace("-", "m")
    return str(val).replace(".", "p").replace("-", "m")


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
    # Prefer Report Win_Loss_Ratio (= wins/losses); fall back.
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
    """Baseline-relative weighted score; baseline returns 100."""
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
    """0 = at 700; larger = farther (for soft tie-break)."""
    return abs(float(trades or 0) - TARGET_TRADES)


def run_one(
    *,
    label: str,
    flag: str,
    value: Any,
    outdir: Path,
    override_v: list[str],
    py: str,
    workers: int,
    symbols: str,
    skip_existing: bool,
) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    if skip_existing:
        existing = extract_metrics(outdir)
        if existing and existing.get("trades"):
            print(f"[skip] {label} (existing trades={existing['trades']})", flush=True)
            return {
                "label": label,
                "flag": flag,
                "value": value,
                "outdir": str(outdir),
                "exit_code": 0,
                "elapsed_s": 0.0,
                "skipped": 1,
                **existing,
                "extra_v": ";".join(override_v),
            }

    # Merge BASE_V with overrides (last key wins).
    merged: dict[str, str] = {}
    for item in BASE_V + override_v:
        if "=" not in item:
            continue
        k, v = item.split("=", 1)
        merged[k] = v
    # growth_filter_enabled must be true when sweeping growth_bars
    if flag == "growth_bars" and float(merged.get("growth_bars", 0) or 0) > 0:
        merged["growth_filter_enabled"] = "true"

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
        "--relative-strength",
        "-s",
        symbols,
    ]
    for k, v in merged.items():
        cmd.extend(["-v", f"{k}={v}"])

    t0 = time.perf_counter()
    log_path = outdir / "run.log"
    print(f"[run] {label} -> {outdir.name}", flush=True)
    with open(log_path, "w", encoding="utf-8", errors="replace") as log:
        log.write("CMD: " + " ".join(cmd) + "\n\n")
        proc = subprocess.run(cmd, cwd=str(REPO), stdout=log, stderr=subprocess.STDOUT)
    elapsed = time.perf_counter() - t0
    metrics = extract_metrics(outdir) or {}
    row = {
        "label": label,
        "flag": flag,
        "value": value,
        "outdir": str(outdir),
        "exit_code": proc.returncode,
        "elapsed_s": round(elapsed, 1),
        "skipped": 0,
        **metrics,
        "extra_v": ";".join(override_v),
    }
    print(
        f"[done] {label} exit={proc.returncode} {elapsed:.0f}s "
        f"trades={row.get('trades', '?')} PF={row.get('pf', '?')} "
        f"PNL={row.get('pnl', '?')} DD={row.get('maxdd', '?')} "
        f"days={row.get('avg_days_held', '?')} p90={row.get('p90_days', '?')}",
        flush=True,
    )
    return row


def build_jobs(arm_filter: str) -> list[tuple[str, str, Any, Path, list[str]]]:
    """Return (label, flag, value, outdir, override_v)."""
    jobs: list[tuple[str, str, Any, Path, list[str]]] = []

    def add(flag: str, value: Any, overrides: list[str]) -> None:
        lab = f"{flag}_{_tag(value)}" if flag != "baseline" else "baseline"
        if arm_filter not in ("all", flag, lab):
            return
        jobs.append((lab, flag, value, OUT_ROOT / lab, overrides))

    add("baseline", "bat", [])

    # Exits — fixed target/stop around bat constants
    for t in (1.15, 1.20, 1.30, 1.40):
        add("target_pct", t, [f"target_pct={t}"])
    for s in (0.85, 0.90, 0.92):
        add("stop_pct", s, [f"stop_pct={s}"])

    # Hold-time: timed exit only (atr_progress=0). Center ~ median DAYS_HELD 119.
    for d in (10, 20, 25, 30, 45, 60, 90, 120, 150, 180):
        add("atr_days", d, [f"atr_days={d}", "atr_progress=0"])

    # ATR exits one-at-a-time (other atr_*=0 → fixed counterpart remains)
    for at in (4.0, 6.0, 8.0, 10.0):
        add("atr_target", at, [f"atr_target={at}", "atr_stop=0"])
    for ast in (2.0, 3.0, 4.0, 5.0):
        add("atr_stop", ast, [f"atr_stop={ast}", "atr_target=0"])

    # Trailing / SMA probes
    for n in (3.0, 4.0, 5.0, 8.0):
        add("trailing_stop_increment", n, [f"trailing_stop_increment={n}"])
    for n in (8, 20, 50):
        add("sma_stop_days", n, [f"sma_stop_days={n}"])

    # ATR% gates — Closed median ATR%≈2.52 (p10/p25/p50/p75/p90)
    for v in (1.42, 1.80, 2.00, 2.52):
        add("min_atr_pct_at_trigger", v, [f"min_atr_pct_at_trigger={v}"])
    for v in (3.50, 4.00, 5.18):
        add("max_atr_pct_at_trigger", v, [f"max_atr_pct_at_trigger={v}"])

    # Near 52w high (fraction below). Median DIST%≈2.33 → most already tight; O'Neil-style band.
    for v in (0.05, 0.10, 0.15, 0.20, 0.25):
        add("rs_max_pct_below_52w_high", v, [f"rs_max_pct_below_52w_high={v}"])

    # SPY_COMPARE mins — Closed median 1Y≈26.7, 2Y≈50
    for v in (10.0, 20.0, 27.0, 40.0):
        add("min_spy_compare_1y_at_trigger", v, [f"min_spy_compare_1y_at_trigger={v}"])
    for v in (20.0, 40.0, 50.0):
        add("min_spy_compare_2y_at_trigger", v, [f"min_spy_compare_2y_at_trigger={v}"])

    # O'Neil growth + SPY INT TC
    for v in (126, 252, 504):
        add("growth_bars", v, [f"growth_filter_enabled=true", f"growth_bars={v}"])
    add("rs_spy_int_tc_not_weak", True, ["rs_spy_int_tc_not_weak=true"])

    # Cooldown
    for v in (5, 10, 20):
        add("symbol_reentry_cooldown_days", v, [f"symbol_reentry_cooldown_days={v}"])

    return jobs


def write_outputs(rows: list[dict], symbols: str, n_sym: int) -> tuple[Path, Path, Path]:
    baseline = next((r for r in rows if r.get("label") == "baseline"), None)
    scored: list[dict] = []
    for r in rows:
        rr = dict(r)
        if baseline and int(r.get("exit_code", 1)) == 0 and r.get("trades") is not None:
            rr["score"] = round(composite_score(r, baseline), 4)
            rr["trade_proximity_700"] = round(trade_proximity(r.get("trades") or 0), 1)
            rr["delta_avg_days"] = round(
                float(r.get("avg_days_held") or 0) - float(baseline.get("avg_days_held") or 0), 1
            )
            rr["delta_p90"] = round(
                float(r.get("p90_days") or 0) - float(baseline.get("p90_days") or 0), 1
            )
        else:
            rr["score"] = None
            rr["trade_proximity_700"] = None
            rr["delta_avg_days"] = None
            rr["delta_p90"] = None
        scored.append(rr)

    # Rank: score desc, then nearer 700, then higher PNL
    def _rank_key(r: dict) -> tuple:
        sc = r.get("score")
        if sc is None:
            return (-1e18, -1e18, -1e18)
        return (float(sc), -float(r.get("trade_proximity_700") or 1e9), float(r.get("pnl") or 0))

    ranked = sorted(scored, key=_rank_key, reverse=True)

    fields = [
        "rank",
        "label",
        "flag",
        "value",
        "score",
        "trades",
        "trade_proximity_700",
        "ppcd",
        "pnl",
        "maxdd",
        "pf",
        "expectancy_pct",
        "wlr",
        "losing_streak",
        "p90_days",
        "avg_days_held",
        "median_days_held",
        "delta_avg_days",
        "delta_p90",
        "wr",
        "ann_ror",
        "stamp",
        "exit_code",
        "elapsed_s",
        "skipped",
        "extra_v",
        "report",
        "outdir",
    ]
    sum_path = OUT_ROOT / "summary.csv"
    rank_path = OUT_ROOT / "ranking.csv"
    with open(sum_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for i, r in enumerate(ranked, 1):
            r["rank"] = i
            w.writerow(r)
    with open(rank_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for i, r in enumerate(ranked, 1):
            r["rank"] = i
            w.writerow(r)

    # Best non-baseline
    non_base = [r for r in ranked if r.get("label") != "baseline" and r.get("score") is not None]
    best = non_base[0] if non_base else None
    # Best hold-time improver among positive score delta
    hold_cands = [
        r
        for r in non_base
        if float(r.get("avg_days_held") or 0) < float(baseline.get("avg_days_held") or 1e9) * 0.85
        and float(r.get("score") or 0) >= 95.0
    ]
    best_hold = max(hold_cands, key=lambda r: float(r.get("score") or 0)) if hold_cands else None

    # Per-flag best
    by_flag: dict[str, dict] = {}
    for r in non_base:
        fl = str(r.get("flag") or "")
        if fl not in by_flag or float(r.get("score") or 0) > float(by_flag[fl].get("score") or 0):
            by_flag[fl] = r
    flag_rank = sorted(by_flag.values(), key=_rank_key, reverse=True)

    lines = [
        "# RS one-flag score optimization",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        f"Universe: **{n_sym}** symbols from current `run_rs.bat` (not curated 55).",
        f"Workers: `-w 1`, parallel-runs=1, `--aggressive`, soft defaults "
        f"(min_spy_compare_1y=0, too_high=0, rs_require_tc_strong=true, O'Neil off).",
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
            "## Baseline",
            "",
            f"- Stamp: `{baseline.get('stamp', '')}`",
            f"- Trades: {baseline.get('trades')} | PF: {baseline.get('pf')} | "
            f"PNL: {baseline.get('pnl')} | MaxDD: {baseline.get('maxdd')} | "
            f"PPCD: {baseline.get('ppcd')} | Exp%: {baseline.get('expectancy_pct')} | "
            f"W/L: {baseline.get('wlr')} | Streak: {baseline.get('losing_streak')} | "
            f"AvgDays: {baseline.get('avg_days_held')} | P90: {baseline.get('p90_days')}",
            f"- Report: `{baseline.get('report', '')}`",
            "",
        ]
    lines += [
        "## Recommendation",
        "",
    ]
    if best:
        lines.append(
            f"- **Best single-flag change:** `{best['label']}` "
            f"(flag=`{best['flag']}`, value=`{best['value']}`) "
            f"score={best['score']} trades={best.get('trades')} "
            f"avg_days={best.get('avg_days_held')} (Δ{best.get('delta_avg_days')}) "
            f"p90={best.get('p90_days')} (Δ{best.get('delta_p90')})"
        )
    else:
        lines.append("- No successful non-baseline arms yet.")
    if best_hold:
        lines.append(
            f"- **Best shorter-hold (≥95 score, avg days ≤85% of baseline):** `{best_hold['label']}` "
            f"score={best_hold['score']} avg_days={best_hold.get('avg_days_held')} "
            f"trades={best_hold.get('trades')}"
        )
    lines += ["", "## Top 15 by composite score", "", "| Rank | Label | Score | Trades | PF | PNL | DD | PPCD | Exp% | W/L | Streak | AvgDays | P90 |", "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in ranked[:15]:
        sc = r.get("score")
        sc_s = f"{sc:.2f}" if sc is not None else ""
        lines.append(
            f"| {r.get('rank')} | {r.get('label')} | {sc_s} | {r.get('trades', '')} | "
            f"{float(r.get('pf') or 0):.2f} | {float(r.get('pnl') or 0):.0f} | "
            f"{float(r.get('maxdd') or 0):.2f} | {float(r.get('ppcd') or 0):.3f} | "
            f"{float(r.get('expectancy_pct') or 0):.2f} | {float(r.get('wlr') or 0):.3f} | "
            f"{r.get('losing_streak', '')} | {float(r.get('avg_days_held') or 0):.1f} | "
            f"{float(r.get('p90_days') or 0):.0f} |"
        )
    lines += ["", "## Best value per flag", "", "| Flag | Best label | Score | Trades | AvgDays | P90 |", "|---|---|---:|---:|---:|---:|"]
    for r in flag_rank:
        lines.append(
            f"| {r.get('flag')} | {r.get('label')} | {float(r.get('score') or 0):.2f} | "
            f"{r.get('trades', '')} | {float(r.get('avg_days_held') or 0):.1f} | "
            f"{float(r.get('p90_days') or 0):.0f} |"
        )
    lines += [
        "",
        "## Notes",
        "",
        "- Centers: Closed_260723221911 medians ATR%≈2.52, DIST_TO_52W≈2.33pp, SPY_COMPARE_1Y≈26.7, DAYS_HELD≈119.",
        "- Zone-only flags ignored. `too_high_multiplier` kept at 0.",
        f"- Artifacts: `{sum_path.name}`, `{rank_path.name}`, per-arm folders under `{OUT_ROOT}`.",
        "",
    ]
    md_path = OUT_ROOT / "RESULTS.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return sum_path, rank_path, md_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workers", type=int, default=1, help="rocket_brt -w (default 1)")
    ap.add_argument(
        "--parallel-runs",
        type=int,
        default=6,
        help="Concurrent single-worker RS jobs across arms (default 6; each job still -w 1)",
    )
    ap.add_argument(
        "--arm",
        default="all",
        help="all | baseline | flag name | exact label (e.g. atr_days_120)",
    )
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument("--symbols", default="", help="Override comma symbols (default: run_rs.bat)")
    args = ap.parse_args()

    if args.workers != 1:
        print(f"[warn] workers={args.workers} (requested default is 1)", flush=True)
    if args.parallel_runs != 1:
        print(f"[info] parallel-runs={args.parallel_runs} (each job -w {args.workers})", flush=True)

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    symbols = args.symbols.strip() or load_symbols_from_bat()
    n_sym = len([s for s in symbols.split(",") if s.strip()])
    py = _resolve_python()
    jobs = build_jobs(args.arm)
    # Ensure baseline first when present
    jobs.sort(key=lambda j: (0 if j[0] == "baseline" else 1, j[0]))
    print(f"[plan] {len(jobs)} arms | {n_sym} symbols | w={args.workers} | -> {OUT_ROOT}", flush=True)

    rows: list[dict] = []
    # Sequential by default; optional tiny pool if parallel-runs>1
    if args.parallel_runs <= 1:
        for lab, flag, val, od, ov in jobs:
            rows.append(
                run_one(
                    label=lab,
                    flag=flag,
                    value=val,
                    outdir=od,
                    override_v=ov,
                    py=py,
                    workers=args.workers,
                    symbols=symbols,
                    skip_existing=args.skip_existing,
                )
            )
            # Incremental write after each arm so RESULTS stay usable mid-run
            write_outputs(rows, symbols, n_sym)
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=max(1, args.parallel_runs)) as pool:
            futs = {
                pool.submit(
                    run_one,
                    label=lab,
                    flag=flag,
                    value=val,
                    outdir=od,
                    override_v=ov,
                    py=py,
                    workers=args.workers,
                    symbols=symbols,
                    skip_existing=args.skip_existing,
                ): lab
                for lab, flag, val, od, ov in jobs
            }
            for fut in as_completed(futs):
                rows.append(fut.result())
                write_outputs(rows, symbols, n_sym)

    sum_path, rank_path, md_path = write_outputs(rows, symbols, n_sym)
    print(f"[summary] {sum_path}", flush=True)
    print(f"[ranking] {rank_path}", flush=True)
    print(f"[results] {md_path}", flush=True)
    ok = all(int(r.get("exit_code", 1)) == 0 for r in rows)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
