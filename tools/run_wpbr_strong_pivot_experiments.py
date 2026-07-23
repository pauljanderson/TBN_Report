"""WPBR strong_pre/post_pivot_pct (+ ATR multiples) MarkTen opt; never edits run_wpbr.bat.

Phases (default all):
  1. sym_fixed — pre=post=x for x in 0..0.25 step 0.01 (26 arms); atr=0
  2. atr_sym   — pre=post ATR multiples (suggested grid); fixed fallback 0.10
  3. coarse_2d — optional pre×post grid step 0.05 (6×6=36); atr=0

Modes (mirrors band_pct_atr):
  - strong_*_pivot_pct_atr <= 0 → fixed strong_*_pivot_pct
  - strong_*_pivot_pct_atr > 0  → threshold = (mult * ATR14) / pivot_high
                                  (fixed pct is ATR-unavailable fallback)

Parity: run_wpbr.bat (band_pct=0.015, band_pct_atr=0 to isolate strong-pivot).
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

ROOT = REPO / "drive" / "davey_experiments" / "wpbr_strong_pivot_opt"
MARKTEN = "AAPL,AMZN,GOOGL,META,MSFT,NVDA,TSLA,AU,AMD,NFLX"

# run_wpbr.bat parity; strong_* and atr overrides come from arms
WPBR_COMMON = (
    "wpbr_zones=true",
    "brt_zones=false",
    "yh_zones=false",
    "vec_zones=false",
    "band_pct=0.015",
    "band_pct_atr=0",
    "strong_pre_pivot_bars=3",
    "strong_post_pivot_bars=3",
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

# Symmetric fixed-%: production is 0.10/0.10 either
FIXED_SYM = tuple(round(i * 0.01, 2) for i in range(0, 26))  # 0.00 .. 0.25
# Coarse asymmetric 2D (step 0.05)
FIXED_COARSE = (0.00, 0.05, 0.10, 0.15, 0.20, 0.25)
# ATR multiples: 0=off (use fixed fallback). At ATR≈2% of price, mult≈5 ≈ 10% fixed.
# Span tight (vol-scaled) through production-equivalent (~3–6) and looser.
ATR_MULT = (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0)
ATR_FALLBACK_PCT = 0.10


def _pct_tag(x: float) -> str:
    return f"{x:.2f}".replace(".", "p")


def _atr_tag(x: float) -> str:
    return f"{x:.1f}".replace(".", "p")


def build_arms(phases: set[str]) -> list[tuple[str, Arm]]:
    """Return (phase, arm) pairs."""
    out: list[tuple[str, Arm]] = []
    if "sym_fixed" in phases:
        for x in FIXED_SYM:
            out.append(
                (
                    "sym_fixed",
                    Arm(
                        f"sym_pct{_pct_tag(x)}",
                        f"Symmetric fixed pre=post={x} (atr=0)",
                        (
                            f"strong_pre_pivot_pct={x}",
                            f"strong_post_pivot_pct={x}",
                            "strong_pre_pivot_pct_atr=0",
                            "strong_post_pivot_pct_atr=0",
                        ),
                    ),
                )
            )
    if "atr_sym" in phases:
        for m in ATR_MULT:
            out.append(
                (
                    "atr_sym",
                    Arm(
                        f"atr_m{_atr_tag(m)}",
                        f"ATR pre=post={m} (fallback pct={ATR_FALLBACK_PCT})",
                        (
                            f"strong_pre_pivot_pct={ATR_FALLBACK_PCT}",
                            f"strong_post_pivot_pct={ATR_FALLBACK_PCT}",
                            f"strong_pre_pivot_pct_atr={m}",
                            f"strong_post_pivot_pct_atr={m}",
                        ),
                    ),
                )
            )
    if "coarse_2d" in phases:
        for pre in FIXED_COARSE:
            for post in FIXED_COARSE:
                out.append(
                    (
                        "coarse_2d",
                        Arm(
                            f"pre{_pct_tag(pre)}_post{_pct_tag(post)}",
                            f"Fixed pre={pre} post={post} (atr=0)",
                            (
                                f"strong_pre_pivot_pct={pre}",
                                f"strong_post_pivot_pct={post}",
                                "strong_pre_pivot_pct_atr=0",
                                "strong_post_pivot_pct_atr=0",
                            ),
                        ),
                    )
                )
    return out


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
                "phase": r.get("phase"),
                "ok": r.get("ok"),
                "elapsed_s": r.get("elapsed_s"),
                "Total_PNL": (r.get("metrics") or {}).get("Total_PNL"),
                "Profit_Factor": (r.get("metrics") or {}).get("Profit_Factor"),
                "Profit_Per_Capital_Day": (r.get("metrics") or {}).get("Profit_Per_Capital_Day"),
                "Max_DD": (r.get("metrics") or {}).get("Max_DD"),
                "Total_Trades": (r.get("metrics") or {}).get("Total_Trades"),
                "score": score(r.get("metrics") or {}) if r.get("ok") else None,
            }
            for r in sorted(results, key=lambda x: (x.get("phase") or "", x.get("id") or ""))
        ],
    }
    (ROOT / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")


def write_report(results: list[dict]) -> Path:
    write_csv(ROOT / "comparison.csv", results)
    ok = [r for r in results if r.get("ok") and (r.get("metrics") or {}).get("Total_Trades", 0)]
    ranked = sorted(ok, key=lambda r: score(r.get("metrics") or {}), reverse=True)

    def _best_in(phase: str) -> dict | None:
        subset = [r for r in ranked if r.get("phase") == phase]
        return subset[0] if subset else None

    prod = next(
        (r for r in ok if r.get("id") == "sym_pct0p10" or r.get("id") == "atr_m0p0"),
        None,
    )
    # Prefer exact production fixed arm
    prod_fixed = next((r for r in ok if r.get("id") == "sym_pct0p10"), None)

    lines = [
        "# WPBR strong_pre/post_pivot_pct (+ ATR) MarkTen optimization",
        "",
        f"Generated: {datetime.now():%Y-%m-%d %H:%M:%S}",
        "",
        "## Setup",
        "",
        "- Universe: MarkTen (AAPL,AMZN,GOOGL,META,MSFT,NVDA,TSLA,AU,AMD,NFLX)",
        "- System: WPBR only (`wpbr_zones=true`, classic brt/yh/vec off)",
        "- Parity: target 1.22, stop 0.91, start_date 2016-01-01, SC after win, "
        "sheet_no_entry_same_bar_after_exit=false, BO conf 0.03, max_days_after_retest 2, "
        "strong pivot either 3 bars, growth off",
        "- Isolating strong-pivot: `band_pct=0.015`, `band_pct_atr=0`",
        "- Modes: fixed `strong_*_pivot_pct` (atr=0) **OR** ATR `strong_*_pivot_pct_atr>0`",
        f"- Symmetric fixed grid: {list(FIXED_SYM)}",
        f"- ATR grid: {list(ATR_MULT)} (fallback pct={ATR_FALLBACK_PCT})",
        f"- Coarse 2D fixed: {list(FIXED_COARSE)} × same",
        "- Primary score: davey `score` = 2*PF + 0.02*PPCD - 0.03*MaxDD - 0.002*max_symbol% "
        "(requires >=30 trades); also report Total_PNL",
        "",
        "## Flags / semantics",
        "",
        "- `strong_pre_pivot_pct` / `strong_post_pivot_pct`: fixed fraction of pivot price move",
        "- `strong_pre_pivot_pct_atr` / `strong_post_pivot_pct_atr`: when >0, threshold = "
        "`(mult * ATR14) / pivot_high` at last daily bar of pivot week (else fixed %)",
        "- Flags already existed on BRTConfig/CLI; WPBR path now wires them (same as band_pct_atr)",
        "",
        "## vs production 0.10/0.10",
        "",
    ]
    if prod_fixed:
        m = prod_fixed.get("metrics") or {}
        lines.append(
            f"- Production arm `sym_pct0p10`: trades={int(m.get('Total_Trades', 0) or 0)}, "
            f"PNL={float(m.get('Total_PNL', 0) or 0):.0f}, "
            f"PF={float(m.get('Profit_Factor', 0) or 0):.2f}, "
            f"score={score(m):.3f}"
        )
    else:
        lines.append("- Production arm `sym_pct0p10` not in completed results yet.")

    for phase, title in (
        ("sym_fixed", "Best symmetric fixed %"),
        ("atr_sym", "Best ATR multiple"),
        ("coarse_2d", "Best coarse 2D fixed"),
    ):
        b = _best_in(phase)
        if not b:
            lines.append(f"- {title}: (none yet)")
            continue
        m = b.get("metrics") or {}
        lines.append(
            f"- {title}: `{b['id']}` — score={score(m):.3f}, "
            f"PNL={float(m.get('Total_PNL', 0) or 0):.0f}, "
            f"trades={int(m.get('Total_Trades', 0) or 0)}"
        )

    lines += [
        "",
        "## Ranking (by score, all phases)",
        "",
        "| rank | phase | arm | trades | PNL | PF | DD | PPCD | AnnROR | score |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for i, r in enumerate(ranked, 1):
        m = r.get("metrics") or {}
        sc = score(m)
        sc_s = f"{sc:.3f}" if math.isfinite(sc) else "n/a"
        lines.append(
            f"| {i} | {r.get('phase')} | {r['id']} | {int(m.get('Total_Trades', 0) or 0)} | "
            f"{float(m.get('Total_PNL', 0) or 0):.0f} | {float(m.get('Profit_Factor', 0) or 0):.2f} | "
            f"{float(m.get('Max_DD', 0) or 0):.1f} | {float(m.get('Profit_Per_Capital_Day', 0) or 0):.3f} | "
            f"{float(m.get('Ann_ROR', 0) or 0):.1f} | {sc_s} |"
        )

    best = ranked[0] if ranked else None
    lines += ["", "## Apply winner to run_wpbr.bat", ""]
    if best:
        arm_map = {a.id: a for _, a in build_arms({"sym_fixed", "atr_sym", "coarse_2d"})}
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
                f"Best arm: `{best['id']}` ({best.get('phase')}) — {arm.label} "
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
        help="Concurrent MarkTen backtests (default 8)",
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
        "--phases",
        default="sym_fixed,atr_sym,coarse_2d",
        help="Comma phases: sym_fixed,atr_sym,coarse_2d",
    )
    args = parser.parse_args()
    phases = {p.strip() for p in args.phases.split(",") if p.strip()}
    unknown = phases - {"sym_fixed", "atr_sym", "coarse_2d"}
    if unknown:
        print(f"Unknown phases: {unknown}", file=sys.stderr)
        return 2

    ROOT.mkdir(parents=True, exist_ok=True)
    phase_arms = build_arms(phases)
    grid_doc = {
        "fixed_sym": list(FIXED_SYM),
        "fixed_coarse": list(FIXED_COARSE),
        "atr_mult": list(ATR_MULT),
        "atr_fallback_pct": ATR_FALLBACK_PCT,
        "phases": sorted(phases),
        "n_arms": len(phase_arms),
        "symbols": args.symbols,
        "jobs": args.jobs,
        "workers": args.workers,
        "common": list(WPBR_COMMON),
        "started": datetime.now().isoformat(timespec="seconds"),
        "notes": {
            "atr_range_reason": (
                "At ATR≈2% of price, mult≈5 ≈ production 10% fixed. "
                "Grid spans 0 (off) through tight vol-scaled thresholds to looser than prod."
            ),
        },
    }
    (ROOT / "grid.json").write_text(json.dumps(grid_doc, indent=2), encoding="utf-8")
    print(
        f"[wpbr_strong_pivot_opt] arms={len(phase_arms)} jobs={args.jobs} "
        f"workers={args.workers} phases={sorted(phases)}",
        flush=True,
    )
    print(f"[wpbr_strong_pivot_opt] outdir={ROOT}", flush=True)

    specs = [
        {
            "root": ROOT,
            "prefix": "WPBR",
            "common_values": WPBR_COMMON,
            "arm": arm,
            "phase": phase,
            "workers": args.workers,
            "symbols": args.symbols,
            "skip_existing": args.skip_existing,
        }
        for phase, arm in phase_arms
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
