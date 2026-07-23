"""Pre-registered WPBR target-vs-stop-only experiment; never edits run_wpbr.bat."""
from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path

from davey_experiment_common import Arm, REPO, run_jobs, score, write_csv

ROOT = REPO / "drive" / "davey_experiments" / "wpbr_stop_only"
WPBR_COMMON = (
    "wpbr_zones=true", "brt_zones=false", "yh_zones=false", "vec_zones=false",
    "band_pct=0.015", "strong_pre_pivot_bars=3", "strong_pre_pivot_pct=0.10",
    "strong_post_pivot_bars=3", "strong_post_pivot_pct=0.10", "strong_pivot_mode=either",
    "wpbr_breakout_confirmation=0.03", "wpbr_max_days_after_retest=2",
    "growth_filter_enabled=false", "min_spy_compare_1y_at_trigger=-1000",
    "ind_score_weights_path=", "too_high_multiplier=0", "target_pct=1.24", "stop_pct=0.927",
    "transaction_type=long", "entry_mode=zones", "liquidate_at_end=true",
)
ARMS = (
    Arm("baseline", "Current WPBR stop + 24% target", ("target_enabled=true",)),
    Arm("stop_only", "Same initial stop; no target", ("target_enabled=false",)),
    Arm("stop_trail4", "Stop-only + gain trail increment 4", ("target_enabled=false", "trailing_stop_increment=4")),
    Arm("stop_sma20", "Stop-only + SMA(20) trailing floor", ("target_enabled=false", "sma_stop_days=20")),
    Arm(
        "stop_atr_progress90",
        "Stop-only + 90d ATR progress/inaction rule",
        ("target_enabled=false", "atr_days=90", "atr_progress=1", "atr_progress_incremental_stop=true"),
    ),
    Arm("stop_time120", "Stop-only + 120 calendar-day exit", ("target_enabled=false", "atr_days=120", "atr_progress=0")),
    Arm("stop_time250", "Stop-only + 250 calendar-day exit", ("target_enabled=false", "atr_days=250", "atr_progress=0")),
)
OOS_FOLDS = (
    ("oos_2021_2022", "2021-01-01", "2022-12-31"),
    ("oos_2023_2024", "2023-01-01", "2024-12-31"),
    ("oos_2025_2026", "2025-01-01", "2026-12-31"),
)


def load_symbols() -> str:
    bat = (REPO / "run_wpbr.bat").read_text(encoding="utf-8", errors="replace")
    match = re.search(r'set "WPBR_SYMBOLS=([^"]+)"', bat)
    if not match:
        raise RuntimeError("Could not read WPBR_SYMBOLS from run_wpbr.bat")
    return match.group(1)


def spec(arm: Arm, phase: str, workers: int, symbols: str, *, start: str = "", end: str = "", skip: bool = False) -> dict:
    return {
        "root": ROOT, "prefix": "WPBR", "common_values": WPBR_COMMON, "arm": arm,
        "phase": phase, "workers": workers, "symbols": symbols, "start": start, "end": end,
        "skip_existing": skip,
    }


def write_report(results: list[dict], selected: Arm) -> None:
    write_csv(ROOT / "comparison.csv", results)
    by = {(r["phase"], r["id"]): r for r in results}
    fold_wins = 0
    valid = 0
    selected_pnl = baseline_pnl = 0.0
    for fold, _, _ in OOS_FOLDS:
        base = by.get((fold, "baseline"))
        choice = by.get((fold, selected.id))
        if not base or not choice or not base.get("ok") or not choice.get("ok"):
            continue
        valid += 1
        bm, cm = base["metrics"], choice["metrics"]
        baseline_pnl += float(bm.get("Total_PNL", 0) or 0)
        selected_pnl += float(cm.get("Total_PNL", 0) or 0)
        if (
            float(cm.get("Profit_Factor", 0) or 0) > float(bm.get("Profit_Factor", 0) or 0)
            and float(cm.get("Profit_Per_Capital_Day", 0) or 0) > float(bm.get("Profit_Per_Capital_Day", 0) or 0)
        ):
            fold_wins += 1
    robust = valid >= 2 and fold_wins >= 2 and selected_pnl > baseline_pnl
    verdict = "ROBUST PASS" if robust else "DO NOT ADOPT"
    lines = [
        "# WPBR stop-only experiment",
        "",
        f"Generated: {datetime.now():%Y-%m-%d %H:%M:%S}",
        "",
        "Pre-registered entry is the current `run_wpbr.bat` WPBR setup. Production runner was not changed.",
        "The exit matrix was selected on entries through 2020; the chosen arm was then frozen for 2021–2026 folds.",
        "",
        f"**IS-selected stop-only arm:** `{selected.id}` — {selected.label}",
        f"**OOS verdict:** {verdict} ({fold_wins}/{valid} folds beat baseline on both PF and PPCD; "
        f"aggregate PNL {selected_pnl:,.0f} vs {baseline_pnl:,.0f}).",
        "",
        "| phase | arm | trades | PNL | PF | DD | PPCD | AnnROR | avg/med/P90 hold | exp | streak | max symbol% |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|",
    ]
    for result in sorted(results, key=lambda r: (r["phase"], r["id"])):
        if result["phase"] == "feasibility":
            continue
        m = result.get("metrics") or {}
        lines.append(
            f"| {result['phase']} | {result['id']} | {int(m.get('Total_Trades', 0) or 0)} | "
            f"{float(m.get('Total_PNL', 0) or 0):.0f} | {float(m.get('Profit_Factor', 0) or 0):.2f} | "
            f"{float(m.get('Max_DD', 0) or 0):.1f} | {float(m.get('Profit_Per_Capital_Day', 0) or 0):.3f} | "
            f"{float(m.get('Ann_ROR', 0) or 0):.1f} | {float(m.get('Avg_Days_Held', 0) or 0):.0f}/"
            f"{float(m.get('Median_Days_Held', 0) or 0):.0f}/{float(m.get('P90_Days', 0) or 0):.0f} | "
            f"{float(m.get('Expectancy', 0) or 0):.0f} | {int(m.get('Losing_Streak', 0) or 0)} | "
            f"{float(m.get('Pct_PNL_Max_Symbol', 0) or 0):.1f} |"
        )
    lines += [
        "",
        "Costs are zero in the WPBR comparison to preserve parity with the production baseline. "
        "Longer-lived stop-only positions would generally be more exposed to financing and slippage.",
    ]
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--symbols", default="")
    args = parser.parse_args()
    symbols = args.symbols or load_symbols()
    feasibility_symbols = ",".join(symbols.split(",")[:8])
    ROOT.mkdir(parents=True, exist_ok=True)

    results = run_jobs(
        [spec(a, "feasibility", args.workers, feasibility_symbols, skip=args.skip_existing) for a in ARMS[:3]],
        args.jobs,
    )
    results += run_jobs(
        [spec(a, "full", args.workers, symbols, skip=args.skip_existing) for a in ARMS],
        args.jobs,
    )
    is_results = run_jobs(
        [spec(a, "is_to_2020", args.workers, symbols, end="2020-12-31", skip=args.skip_existing) for a in ARMS],
        args.jobs,
    )
    results += is_results
    eligible = [r for r in is_results if r.get("ok") and r["id"] != "baseline"]
    selected_result = max(eligible, key=lambda r: score(r.get("metrics") or {}))
    selected = next(a for a in ARMS if a.id == selected_result["id"])
    oos_specs = []
    baseline = ARMS[0]
    for fold, start, end in OOS_FOLDS:
        oos_specs += [
            spec(baseline, fold, args.workers, symbols, start=start, end=end, skip=args.skip_existing),
            spec(selected, fold, args.workers, symbols, start=start, end=end, skip=args.skip_existing),
        ]
    results += run_jobs(oos_specs, args.jobs)
    write_report(results, selected)
    print(f"[write] {ROOT / 'comparison.md'}")
    return 0 if all(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
