"""WPBR band_pct_atr extension above prior winner 1.0 (MarkTen); never edits run_wpbr.bat.

Prior opt (drive/davey_experiments/wpbr_band_opt) topped out at atr_m1p000.
This grid re-runs 1.0 baseline plus higher ATR multipliers with fallback band_pct=0.015.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from davey_experiment_common import Arm, REPO, run_job, score, write_csv

ROOT = REPO / "drive" / "davey_experiments" / "wpbr_band_opt_atr_extend"
PRIOR_ROOT = REPO / "drive" / "davey_experiments" / "wpbr_band_opt"
MARKTEN = "AAPL,AMZN,GOOGL,META,MSFT,NVDA,TSLA,AU,AMD,NFLX"

# Same parity as tools/run_wpbr_band_experiments.py / run_wpbr.bat
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

# Include prior edge winner 1.0 as baseline; extend upward
ATR_MULT = (1.00, 1.05, 1.10, 1.15, 1.20, 1.25, 1.30, 1.40)
ATR_FALLBACK_BAND = 0.015
PRIOR_BASELINE_ID = "atr_m1p000"


def build_arms() -> list[Arm]:
    arms: list[Arm] = []
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
    baseline = next((r for r in ok if r.get("id") == PRIOR_BASELINE_ID), None)
    base_sc = score(baseline.get("metrics") or {}) if baseline else float("nan")
    edge = float(max(ATR_MULT))
    best = ranked[0] if ranked else None
    best_m = None
    if best:
        try:
            best_m = float(str(best["id"]).replace("atr_m", "").replace("p", "."))
        except ValueError:
            best_m = None
    still_at_edge = bool(best_m is not None and abs(best_m - edge) < 1e-9)

    lines = [
        "# WPBR band_pct_atr extension (above 1.0)",
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
        f"- ATR extension grid: {list(ATR_MULT)} (fallback band_pct={ATR_FALLBACK_BAND})",
        f"- Prior opt dir: `{PRIOR_ROOT}` (winner was atr_m1p000)",
        "- Primary score: davey `score` = 2*PF + 0.02*PPCD - 0.03*MaxDD - 0.002*max_symbol% "
        "(requires >=30 trades); also report Total_PNL",
        "",
        "## Ranking (by score)",
        "",
        "| rank | arm | atr | trades | PNL | PF | DD | PPCD | AnnROR | score | vs_1.0 |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for i, r in enumerate(ranked, 1):
        m = r.get("metrics") or {}
        sc = score(m)
        sc_s = f"{sc:.3f}" if math.isfinite(sc) else "n/a"
        try:
            atr = float(str(r["id"]).replace("atr_m", "").replace("p", "."))
            atr_s = f"{atr:.2f}"
        except ValueError:
            atr_s = "?"
        if math.isfinite(sc) and math.isfinite(base_sc):
            delta = sc - base_sc
            vs = f"{delta:+.3f}"
        else:
            vs = "n/a" if r.get("id") != PRIOR_BASELINE_ID else "0.000"
        lines.append(
            f"| {i} | {r['id']} | {atr_s} | {int(m.get('Total_Trades', 0) or 0)} | "
            f"{float(m.get('Total_PNL', 0) or 0):.0f} | {float(m.get('Profit_Factor', 0) or 0):.2f} | "
            f"{float(m.get('Max_DD', 0) or 0):.1f} | {float(m.get('Profit_Per_Capital_Day', 0) or 0):.3f} | "
            f"{float(m.get('Ann_ROR', 0) or 0):.1f} | {sc_s} | {vs} |"
        )

    lines += ["", "## Verdict", ""]
    if best:
        arm_map = {a.id: a for a in build_arms()}
        arm = arm_map.get(best["id"])
        lines.append(
            f"- **New winner:** `{best['id']}` — {arm.label if arm else best['id']} "
            f"(score={score(best.get('metrics') or {}):.3f}, "
            f"PNL={float((best.get('metrics') or {}).get('Total_PNL', 0) or 0):.0f})."
        )
        if baseline and best["id"] != PRIOR_BASELINE_ID:
            bm = best.get("metrics") or {}
            b0 = baseline.get("metrics") or {}
            lines.append(
                f"- vs prior edge `atr_m1p000`: score "
                f"{score(bm) - base_sc:+.3f}, "
                f"PNL {float(bm.get('Total_PNL', 0) or 0) - float(b0.get('Total_PNL', 0) or 0):+.0f}."
            )
        elif best["id"] == PRIOR_BASELINE_ID:
            lines.append("- Prior edge `atr_m1p000` remains best within this extension grid.")
        if still_at_edge:
            lines.append(
                f"- **Still at grid edge** (atr={edge:.2f}). Another extension above {edge:.2f} may be needed."
            )
        else:
            lines.append(f"- Winner is interior to the grid (max tested atr={edge:.2f}).")
        lines.append("")
        lines.append("Suggested `-v` overrides (do not auto-edit run_wpbr.bat):")
        lines.append("")
        lines.append("```text")
        if arm:
            for v in arm.values:
                lines.append(f"-v {v}")
        lines.append("```")
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
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--workers", "-w", type=int, default=10)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--symbols", default=MARKTEN)
    parser.add_argument("--phase", default="markten")
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    arms = build_arms()
    grid_doc = {
        "atr_mult": list(ATR_MULT),
        "atr_fallback_band_pct": ATR_FALLBACK_BAND,
        "n_arms": len(arms),
        "symbols": args.symbols,
        "jobs": args.jobs,
        "workers": args.workers,
        "common": list(WPBR_COMMON),
        "prior_opt": str(PRIOR_ROOT),
        "started": datetime.now().isoformat(timespec="seconds"),
    }
    (ROOT / "grid.json").write_text(json.dumps(grid_doc, indent=2), encoding="utf-8")
    print(f"[wpbr_band_atr_extend] arms={len(arms)} jobs={args.jobs} workers={args.workers}", flush=True)
    print(f"[wpbr_band_atr_extend] outdir={ROOT}", flush=True)
    print(f"[wpbr_band_atr_extend] atr={list(ATR_MULT)}", flush=True)

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
