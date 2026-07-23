"""WPBR band_pct vs band_pct_atr grid on MarkTen; never edits run_wpbr.bat.

Modes are mutually exclusive in-engine:
  - band_pct_atr <= 0  → fixed ±band_pct of pivot high
  - band_pct_atr > 0   → half-width = (band_pct_atr * ATR14) / pivot_high
                         (band_pct is ATR-unavailable fallback only)

Parity baseline matches run_wpbr.bat (target 1.22 / stop 0.91 / start 2016 / SC on).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from davey_experiment_common import (
    Arm,
    REPO,
    extract_metrics,
    run_job,
    score,
    write_csv,
)

ROOT = REPO / "drive" / "davey_experiments" / "wpbr_band_opt"
MARKTEN = "AAPL,AMZN,GOOGL,META,MSFT,NVDA,TSLA,AU,AMD,NFLX"

# run_wpbr.bat parity (band_* overridden per arm)
WPBR_COMMON = (
    "wpbr_zones=true",
    "brt_zones=false",
    "yh_zones=false",
    "vec_zones=false",
    "strong_pre_pivot_bars=3",
    "strong_pre_pivot_pct=0.10",
    "strong_post_pivot_bars=3",
    "strong_post_pivot_pct=0.10",
    "strong_pivot_mode=either",
    "wpbr_breakout_confirmation=0.03",
    "wpbr_max_days_after_retest=2",
    "wpbr_second_chance_after_win=true",
    "growth_filter_enabled=false",
    "min_spy_compare_1y_at_trigger=-1000",
    "ind_score_weights_path=",
    "too_high_multiplier=0",
    "target_pct=1.22",
    "stop_pct=0.91",
    "start_date=2016-01-01",
    "sheet_no_entry_same_bar_after_exit=false",
    "transaction_type=long",
    "entry_mode=zones",
    "liquidate_at_end=true",
)

# Fixed-% mode: band_pct_atr=0
FIXED_BAND_PCT = (0.010, 0.012, 0.014, 0.015, 0.016, 0.018, 0.020, 0.022, 0.025)
# ATR mode: band_pct kept as fallback (production 0.015); sweep ATR multiplier
# (runall.bat historically used ~0.466 on classic BRT)
ATR_MULT = (0.20, 0.30, 0.40, 0.466, 0.55, 0.65, 0.80, 1.00)
ATR_FALLBACK_BAND = 0.015


def build_arms() -> list[Arm]:
    arms: list[Arm] = []
    for bp in FIXED_BAND_PCT:
        tag = f"{bp:.3f}".replace(".", "p")
        arms.append(
            Arm(
                f"fixed_bp{tag}",
                f"Fixed band_pct={bp}",
                (f"band_pct={bp}", "band_pct_atr=0"),
            )
        )
    for m in ATR_MULT:
        tag = f"{m:.3f}".replace(".", "p")
        arms.append(
            Arm(
                f"atr_m{tag}",
                f"ATR band_pct_atr={m} (fallback band_pct={ATR_FALLBACK_BAND})",
                (f"band_pct={ATR_FALLBACK_BAND}", f"band_pct_atr={m}"),
            )
        )
    return arms


def run_jobs_uncapped(specs: list[dict], jobs: int) -> list[dict]:
    """Like davey run_jobs but allows full --jobs concurrency (not capped at 3)."""
    results: list[dict] = []
    n = max(1, int(jobs))
    with ThreadPoolExecutor(max_workers=n) as pool:
        futures = [pool.submit(run_job, **spec) for spec in specs]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            metrics = result.get("metrics") or {}
            print(
                f"[{result['phase']}:{result['id']}] ok={result['ok']} "
                f"trades={int(metrics.get('Total_Trades', 0) or 0)} "
                f"pnl={float(metrics.get('Total_PNL', 0) or 0):.0f} "
                f"pf={float(metrics.get('Profit_Factor', 0) or 0):.2f} "
                f"elapsed={result.get('elapsed_s', 0)}s",
                flush=True,
            )
            _write_progress(results)
    return results


def _write_progress(results: list[dict]) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    write_csv(ROOT / "comparison.csv", results)
    status = {
        "updated": datetime.now().isoformat(timespec="seconds"),
        "completed": len(results),
        "ok": sum(1 for r in results if r.get("ok")),
        "results": [
            {
                "id": r.get("id"),
                "ok": r.get("ok"),
                "elapsed_s": r.get("elapsed_s"),
                "Total_PNL": (r.get("metrics") or {}).get("Total_PNL"),
                "Profit_Factor": (r.get("metrics") or {}).get("Profit_Factor"),
                "Profit_Per_Capital_Day": (r.get("metrics") or {}).get("Profit_Per_Capital_Day"),
                "Max_DD": (r.get("metrics") or {}).get("Max_DD"),
                "Total_Trades": (r.get("metrics") or {}).get("Total_Trades"),
                "score": score(r.get("metrics") or {}) if r.get("ok") else None,
            }
            for r in sorted(results, key=lambda x: x.get("id") or "")
        ],
    }
    (ROOT / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")


def write_report(results: list[dict]) -> Path:
    write_csv(ROOT / "comparison.csv", results)
    ok = [r for r in results if r.get("ok") and (r.get("metrics") or {}).get("Total_Trades", 0)]
    ranked = sorted(ok, key=lambda r: score(r.get("metrics") or {}), reverse=True)
    lines = [
        "# WPBR band_pct / band_pct_atr MarkTen optimization",
        "",
        f"Generated: {datetime.now():%Y-%m-%d %H:%M:%S}",
        "",
        "## Setup",
        "",
        "- Universe: MarkTen (AAPL,AMZN,GOOGL,META,MSFT,NVDA,TSLA,AU,AMD,NFLX)",
        "- System: WPBR only (`wpbr_zones=true`, classic brt/yh/vec off)",
        "- Parity: target 1.22, stop 0.91, start_date 2016-01-01, SC after win, "
        "sheet_no_entry_same_bar_after_exit=false, BO conf 0.03, max_days_after_retest 2, "
        "strong pivot either 3/10%, growth off",
        "- Modes: fixed `band_pct` (atr=0) **OR** ATR `band_pct_atr>0` (mutually exclusive)",
        f"- Fixed grid: {list(FIXED_BAND_PCT)}",
        f"- ATR grid: {list(ATR_MULT)} (fallback band_pct={ATR_FALLBACK_BAND})",
        "- Primary score: davey `score` = 2*PF + 0.02*PPCD - 0.03*MaxDD - 0.002*max_symbol% "
        "(requires >=30 trades); also report Total_PNL",
        "",
        "## Ranking (by score)",
        "",
        "| rank | arm | mode | trades | PNL | PF | DD | PPCD | AnnROR | score |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for i, r in enumerate(ranked, 1):
        m = r.get("metrics") or {}
        mode = "ATR" if str(r["id"]).startswith("atr_") else "fixed"
        sc = score(m)
        sc_s = f"{sc:.3f}" if math.isfinite(sc) else "n/a"
        lines.append(
            f"| {i} | {r['id']} | {mode} | {int(m.get('Total_Trades', 0) or 0)} | "
            f"{float(m.get('Total_PNL', 0) or 0):.0f} | {float(m.get('Profit_Factor', 0) or 0):.2f} | "
            f"{float(m.get('Max_DD', 0) or 0):.1f} | {float(m.get('Profit_Per_Capital_Day', 0) or 0):.3f} | "
            f"{float(m.get('Ann_ROR', 0) or 0):.1f} | {sc_s} |"
        )
    best = ranked[0] if ranked else None
    lines += ["", "## Apply winner to run_wpbr.bat", ""]
    if best:
        arm_map = {a.id: a for a in build_arms()}
        arm = arm_map.get(best["id"])
        if arm:
            lines.append("Replace / add these `-v` overrides on the rocket_brt line in `run_wpbr.bat`:")
            lines.append("")
            lines.append("```text")
            for v in arm.values:
                lines.append(f"-v {v}")
            lines.append("```")
            lines.append("")
            lines.append(
                f"Best arm: `{best['id']}` — {arm.label} "
                f"(score={score(best.get('metrics') or {}):.3f}, "
                f"PNL={float((best.get('metrics') or {}).get('Total_PNL', 0) or 0):.0f})."
            )
        else:
            lines.append(f"Best arm id: `{best['id']}` (see comparison.csv).")
    else:
        lines.append("No successful runs yet.")
    lines += [
        "",
        f"Artifacts: `{ROOT}` — `comparison.csv`, `comparison.md`, `status.json`, `runs/<phase>__<arm>/`",
    ]
    out = ROOT / "comparison.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--jobs",
        type=int,
        default=8,
        help="Concurrent MarkTen backtests (default 8; use up to 24 for full parallel)",
    )
    parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=10,
        help="rocket_brt -w symbol workers per backtest (MarkTen has 10 symbols)",
    )
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--symbols", default=MARKTEN)
    parser.add_argument(
        "--phase",
        default="markten",
        help="Phase label for run directories (default markten)",
    )
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    arms = build_arms()
    grid_doc = {
        "fixed_band_pct": list(FIXED_BAND_PCT),
        "atr_mult": list(ATR_MULT),
        "atr_fallback_band_pct": ATR_FALLBACK_BAND,
        "n_arms": len(arms),
        "symbols": args.symbols,
        "jobs": args.jobs,
        "workers": args.workers,
        "common": list(WPBR_COMMON),
        "started": datetime.now().isoformat(timespec="seconds"),
    }
    (ROOT / "grid.json").write_text(json.dumps(grid_doc, indent=2), encoding="utf-8")
    print(f"[wpbr_band_opt] arms={len(arms)} jobs={args.jobs} workers={args.workers}", flush=True)
    print(f"[wpbr_band_opt] outdir={ROOT}", flush=True)
    print(f"[wpbr_band_opt] fixed={list(FIXED_BAND_PCT)}", flush=True)
    print(f"[wpbr_band_opt] atr={list(ATR_MULT)}", flush=True)

    specs = [
        {
            "root": ROOT,
            "prefix": "WPBR",
            "common_values": WPBR_COMMON,
            "arm": arm,
            "phase": args.phase,
            "workers": args.workers,
            "symbols": args.symbols,
            "skip_existing": args.skip_existing,
        }
        for arm in arms
    ]
    results = run_jobs_uncapped(specs, args.jobs)
    report = write_report(results)
    _write_progress(results)
    print(f"[write] {report}", flush=True)
    print(f"[write] {ROOT / 'comparison.csv'}", flush=True)
    print(f"[write] {ROOT / 'status.json'}", flush=True)
    return 0 if all(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
