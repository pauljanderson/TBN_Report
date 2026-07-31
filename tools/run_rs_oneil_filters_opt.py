#!/usr/bin/env python3
"""Optimize RS O'Neil-style filters on the curated 55-symbol universe (run_rs.bat).

Arms:
  A) rs_max_pct_below_52w_high sweep
  B) growth_bars sweep (growth_filter_enabled)
  C) rs_spy_int_tc_not_weak on/off
  D) optional combo of best near-high + market filter

Outputs under drive/paul_experiments/rs_oneil_filters/
Also writes SPY_INT_TC_REGIME.csv (SPY IND_TC_INT Strong/Neutral/Weak ranges).
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

OUT_ROOT = REPO / "drive" / "paul_experiments" / "rs_oneil_filters"
DATA_DIR = REPO / "data" / "newdata" / "data"

# Same curated 55 as run_rs.bat
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
    # BRT default min_spy_compare_1y=50 is NOT an RS/O'Neil rule; keep off for baseline parity.
    "min_spy_compare_1y_at_trigger=0",
    "too_high_multiplier=0",
    "rs_max_pct_below_52w_high=0",
    "rs_spy_int_tc_not_weak=false",
]

NEAR_HIGH_GRID = [None, 0.02, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30]  # None = disabled
GROWTH_BARS_GRID = [None, 126, 252, 378, 504, 756]  # None = filter off
# 126≈6m, 252≈1Y, 378≈1.5Y, 504≈2Y, 756≈3Y


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


def _tag_frac(val: Optional[float]) -> str:
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


def write_spy_int_tc_regime(out_path: Path) -> Path:
    """Daily + contiguous ranges for SPY IND_TC_INT_OUTLOOK."""
    from rocket_brt import _load_benchmark_local
    from brt_entry_indicators import (
        _ensure_gate_arrays,
        _tc_outlook_label,
        build_entry_indicator_precompute,
        resolve_indicator_cache_dir,
    )

    spy = _load_benchmark_local(DATA_DIR)
    if spy is None or spy.empty:
        raise SystemExit(f"SPY.csv not found under {DATA_DIR}")
    cache_dir = resolve_indicator_cache_dir(None, repo_root=REPO, data_dir=DATA_DIR)
    pre = build_entry_indicator_precompute(
        spy, symbol="SPY", cache_dir=str(cache_dir), use_cache=True
    )
    if pre is None:
        raise SystemExit("Failed to precompute SPY indicators")
    pre = _ensure_gate_arrays(pre)
    if getattr(pre, "tc_int_sum", None) is None:
        raise SystemExit("SPY tc_int_sum missing")

    daily_path = out_path
    rows: list[dict] = []
    for i, d in enumerate(pre.dates):
        ymd = int(d)
        label = _tc_outlook_label(int(pre.tc_int_sum[i]))
        iso = f"{ymd // 10000:04d}-{(ymd // 100) % 100:02d}-{ymd % 100:02d}"
        rows.append({"date": iso, "ymd": ymd, "IND_TC_INT_OUTLOOK": label, "IND_TC_INT_SUM": int(pre.tc_int_sum[i])})

    daily_path.parent.mkdir(parents=True, exist_ok=True)
    with open(daily_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["date", "ymd", "IND_TC_INT_OUTLOOK", "IND_TC_INT_SUM"])
        w.writeheader()
        w.writerows(rows)

    # Contiguous regime ranges
    ranges_path = out_path.with_name("SPY_INT_TC_REGIME_RANGES.csv")
    ranges: list[dict] = []
    if rows:
        start = rows[0]
        cur = rows[0]["IND_TC_INT_OUTLOOK"]
        for r in rows[1:]:
            if r["IND_TC_INT_OUTLOOK"] != cur:
                ranges.append(
                    {
                        "outlook": cur,
                        "start_date": start["date"],
                        "end_date": rows[rows.index(r) - 1]["date"],
                        "n_days": rows.index(r) - rows.index(start),
                    }
                )
                start = r
                cur = r["IND_TC_INT_OUTLOOK"]
        ranges.append(
            {
                "outlook": cur,
                "start_date": start["date"],
                "end_date": rows[-1]["date"],
                "n_days": len(rows) - rows.index(start),
            }
        )
    # Fix n_days properly without fragile index
    ranges = []
    if rows:
        seg_start = 0
        for i in range(1, len(rows) + 1):
            if i == len(rows) or rows[i]["IND_TC_INT_OUTLOOK"] != rows[seg_start]["IND_TC_INT_OUTLOOK"]:
                ranges.append(
                    {
                        "outlook": rows[seg_start]["IND_TC_INT_OUTLOOK"],
                        "start_date": rows[seg_start]["date"],
                        "end_date": rows[i - 1]["date"],
                        "n_days": i - seg_start,
                    }
                )
                seg_start = i
    with open(ranges_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["outlook", "start_date", "end_date", "n_days"])
        w.writeheader()
        w.writerows(ranges)

    # Compact markdown summary of long Weak/Strong stretches
    md_path = out_path.with_name("SPY_INT_TC_REGIME.md")
    by_lab = {"Strong": 0, "Neutral": 0, "Weak": 0}
    for r in rows:
        by_lab[r["IND_TC_INT_OUTLOOK"]] = by_lab.get(r["IND_TC_INT_OUTLOOK"], 0) + 1
    long_ranges = [r for r in ranges if r["n_days"] >= 10]
    lines = [
        "# SPY IND_TC_INT_OUTLOOK regime",
        "",
        f"Source: SPY indicators through `{rows[-1]['date'] if rows else 'n/a'}` ({len(rows)} sessions).",
        "",
        "## Session counts",
        "",
        f"- Strong: {by_lab.get('Strong', 0)}",
        f"- Neutral: {by_lab.get('Neutral', 0)}",
        f"- Weak: {by_lab.get('Weak', 0)}",
        "",
        "RS filter `rs_spy_int_tc_not_weak=true` allows Strong + Neutral (blocks Weak only).",
        "",
        "## Contiguous ranges (≥10 sessions)",
        "",
        "| Outlook | Start | End | Days |",
        "|---|---|---|---|",
    ]
    for r in long_ranges:
        lines.append(f"| {r['outlook']} | {r['start_date']} | {r['end_date']} | {r['n_days']} |")
    lines.append("")
    lines.append(f"Daily: `{daily_path.name}` · Ranges: `{ranges_path.name}`")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[regime] wrote {daily_path} ({len(rows)} days), {ranges_path}, {md_path}")
    return daily_path


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
        f"PF={row.get('pf', '?')} PNL={row.get('pnl', '?')}",
        flush=True,
    )
    return row


def _score(row: dict) -> float:
    """Rank by profit factor then PNL (prefer enough trades)."""
    trades = float(row.get("trades") or 0)
    pf = float(row.get("pf") or 0)
    pnl = float(row.get("pnl") or 0)
    if trades < 5:
        return -1e18
    return pf * 1e6 + pnl


def write_results_md(out_root: Path, rows: list[dict], recommendations: dict) -> Path:
    path = out_root / "RESULTS.md"
    arms = {
        "A_near_high": [r for r in rows if r["label"].startswith("A_")],
        "B_growth": [r for r in rows if r["label"].startswith("B_")],
        "C_spy_int": [r for r in rows if r["label"].startswith("C_")],
        "D_combo": [r for r in rows if r["label"].startswith("D_")],
    }

    def _tbl(title: str, subset: list[dict]) -> list[str]:
        lines = [f"## {title}", "", "| Label | Trades | WR% | PF | PNL | MaxDD | Expectancy |", "|---|---:|---:|---:|---:|---:|---:|"]
        for r in subset:
            lines.append(
                f"| {r.get('label','')} | {r.get('trades','')} | {r.get('wr',0):.1f} | "
                f"{r.get('pf',0):.3f} | {r.get('pnl',0):.0f} | {r.get('maxdd',0):.2f} | "
                f"{r.get('expectancy',0):.4f} |"
            )
        lines.append("")
        return lines

    lines = [
        "# RS O'Neil-style filter optimization",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "Universe: curated 55 from `run_rs.bat`. Target 1.25 / stop 0.88. All gates on **trigger bar T**.",
        "",
        "## Flags",
        "",
        "| Flag | Meaning | Disable |",
        "|---|---|---|",
        "| `rs_max_pct_below_52w_high=X` | Close_T ≥ 52w_high_T×(1−X); X=0.15 ≈ within 15% of high | `≤0` |",
        "| `growth_filter_enabled` + `growth_bars=N` | Close_T ≥ Close_{T−N} | `growth_filter_enabled=false` |",
        "| `rs_spy_int_tc_not_weak=true` | SPY IND_TC_INT_OUTLOOK ≠ Weak on T | `false` |",
        "",
        "### O'Neil mapping",
        "",
        "IBD/O'Neil often cite buying within ~15% of 52-week highs; classic breakouts use pivot + $0.10 "
        "with volume confirmation. This experiment approximates **proximity to the 52w high** only "
        "(rolling max High over 252 bars as of T) — not full cup-with-handle / pivot patterns.",
        "",
    ]
    for title, key in (
        ("A) Near 52w high (X)", "A_near_high"),
        ("B) Growth bars (N)", "B_growth"),
        ("C) SPY INT TC not Weak", "C_spy_int"),
        ("D) Combo", "D_combo"),
    ):
        lines.extend(_tbl(title, arms[key]))

    lines.extend(
        [
            "## Recommendations",
            "",
            f"- **Near-high X:** `{recommendations.get('near_high')}`",
            f"- **Growth bars N:** `{recommendations.get('growth_bars')}`",
            f"- **SPY INT TC not Weak:** `{recommendations.get('spy_int')}`",
            f"- **Suggested combo:** `{recommendations.get('combo')}`",
            "",
            f"Rationale: {recommendations.get('notes', '')}",
            "",
            "Artifacts: per-run folders under this directory; `summary.csv`; `SPY_INT_TC_REGIME.csv`.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--regime-only", action="store_true", help="Only write SPY_INT_TC_REGIME files")
    ap.add_argument("--skip-regime", action="store_true")
    ap.add_argument("--workers", type=int, default=8, help="rocket_brt -w per run")
    ap.add_argument("--parallel-runs", type=int, default=3, help="Concurrent RS jobs")
    ap.add_argument("--arm", choices=["all", "A", "B", "C", "D"], default="all")
    ap.add_argument("--combo-x", type=float, default=None, help="Override near-high X for arm D")
    args = ap.parse_args()

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    if not args.skip_regime:
        write_spy_int_tc_regime(OUT_ROOT / "SPY_INT_TC_REGIME.csv")
    if args.regime_only:
        return 0

    py = _resolve_python()
    jobs: list[tuple[str, Path, list[str]]] = []

    if args.arm in ("all", "A"):
        for x in NEAR_HIGH_GRID:
            tag = _tag_frac(x)
            label = f"A_near_{tag}"
            extra = [] if x is None else [f"rs_max_pct_below_52w_high={x}"]
            jobs.append((label, OUT_ROOT / label, extra))

    if args.arm in ("all", "B"):
        for n in GROWTH_BARS_GRID:
            if n is None:
                label = "B_growth_off"
                extra = ["growth_filter_enabled=false"]
            else:
                label = f"B_growth_{n}"
                extra = ["growth_filter_enabled=true", f"growth_bars={n}"]
            jobs.append((label, OUT_ROOT / label, extra))

    if args.arm in ("all", "C"):
        jobs.append(("C_spy_int_off", OUT_ROOT / "C_spy_int_off", ["rs_spy_int_tc_not_weak=false"]))
        jobs.append(("C_spy_int_on", OUT_ROOT / "C_spy_int_on", ["rs_spy_int_tc_not_weak=true"]))

    rows: list[dict] = []
    # Run A/B/C first (possibly D later after picking best X)
    stage1 = [j for j in jobs if not j[0].startswith("D_")]
    with ThreadPoolExecutor(max_workers=max(1, args.parallel_runs)) as pool:
        futs = {
            pool.submit(
                run_one, label=lab, outdir=od, extra_v=ev, py=py, workers=args.workers
            ): lab
            for lab, od, ev in stage1
        }
        for fut in as_completed(futs):
            rows.append(fut.result())

    # Arm D: best near-high × spy_int on
    if args.arm in ("all", "D"):
        a_rows = [r for r in rows if r["label"].startswith("A_") and int(r.get("exit_code", 1)) == 0]
        best_a = max(a_rows, key=_score) if a_rows else None
        x_best = args.combo_x
        if x_best is None and best_a is not None:
            # parse from label A_near_0p15 or A_near_off
            lab = best_a["label"]
            if lab == "A_near_off":
                x_best = None
            else:
                frag = lab.replace("A_near_", "").replace("p", ".")
                try:
                    x_best = float(frag)
                except ValueError:
                    x_best = 0.15
        if x_best is None:
            x_best = 0.15
        d_jobs = [
            (
                f"D_near_{_tag_frac(x_best)}_spy_int_on",
                OUT_ROOT / f"D_near_{_tag_frac(x_best)}_spy_int_on",
                [f"rs_max_pct_below_52w_high={x_best}", "rs_spy_int_tc_not_weak=true"],
            ),
            (
                f"D_near_{_tag_frac(x_best)}_spy_int_off",
                OUT_ROOT / f"D_near_{_tag_frac(x_best)}_spy_int_off",
                [f"rs_max_pct_below_52w_high={x_best}", "rs_spy_int_tc_not_weak=false"],
            ),
        ]
        with ThreadPoolExecutor(max_workers=max(1, min(2, args.parallel_runs))) as pool:
            futs = {
                pool.submit(
                    run_one, label=lab, outdir=od, extra_v=ev, py=py, workers=args.workers
                ): lab
                for lab, od, ev in d_jobs
            }
            for fut in as_completed(futs):
                rows.append(fut.result())

    # Persist summary
    rows.sort(key=lambda r: r.get("label", ""))
    sum_path = OUT_ROOT / "summary.csv"
    fields = [
        "label", "trades", "wr", "pf", "pnl", "maxdd", "expectancy", "ann_ror",
        "exit_code", "elapsed_s", "extra_v", "report", "outdir",
    ]
    with open(sum_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

    def _best(subset: list[dict]) -> Optional[dict]:
        ok = [r for r in subset if int(r.get("exit_code", 1)) == 0 and r.get("trades") is not None]
        return max(ok, key=_score) if ok else None

    ba = _best([r for r in rows if r["label"].startswith("A_")])
    bb = _best([r for r in rows if r["label"].startswith("B_")])
    bc = _best([r for r in rows if r["label"].startswith("C_")])
    bd = _best([r for r in rows if r["label"].startswith("D_")])

    # Prefer on vs off for C by comparing PF/PNL when both exist
    c_off = next((r for r in rows if r["label"] == "C_spy_int_off"), None)
    c_on = next((r for r in rows if r["label"] == "C_spy_int_on"), None)
    spy_rec = "false"
    if c_on and c_off and _score(c_on) > _score(c_off):
        spy_rec = "true"

    near_rec = "off (0)"
    if ba:
        near_rec = ba["label"].replace("A_near_", "")
        if near_rec != "off":
            near_rec = near_rec.replace("p", ".")

    growth_rec = "off"
    if bb:
        growth_rec = bb["label"].replace("B_growth_", "")

    combo_rec = bd["label"] if bd else "n/a"
    notes = (
        f"Best A={ba['label'] if ba else 'n/a'} (PF={ba.get('pf') if ba else 'n/a'}); "
        f"Best B={bb['label'] if bb else 'n/a'}; "
        f"C on vs off -> recommend spy_int={spy_rec}; "
        f"Best D={combo_rec}."
    )
    recs = {
        "near_high": near_rec,
        "growth_bars": growth_rec,
        "spy_int": spy_rec,
        "combo": combo_rec,
        "notes": notes,
    }
    write_results_md(OUT_ROOT, rows, recs)
    print(f"[summary] {sum_path}")
    print(f"[recs] {recs}")
    return 0 if all(int(r.get("exit_code", 1)) == 0 for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
