"""Pre-registered Wilder ADX(15)<20, 10-bar stop-breakout exit experiment."""
from __future__ import annotations

import argparse
from datetime import datetime

from davey_experiment_common import Arm, REPO, run_jobs, score, write_csv

ROOT = REPO / "drive" / "davey_experiments" / "adx_channel"
COMMON = (
    "entry_mode=adx_channel", "adx_period=15", "adx_max=20", "channel_length=10",
    "pending_stop_bars=1", "stop_order_gap_fill_at_open=true",
    "brt_zones=false", "yh_zones=false", "vec_zones=false", "wpbr_zones=false",
    "growth_filter_enabled=false", "min_spy_compare_1y_at_trigger=-1000",
    "too_high_multiplier=0", "too_low_multiplier=0", "stop_pct=0", "target_pct=0",
    "liquidate_at_end=true", "max_market_cap=0", "min_market_cap=0",
)
ARMS = (
    Arm("L_S1_T2", "Long ATR stop 1 / target 2", ("transaction_type=long", "atr_stop=1", "atr_target=2", "target_enabled=true")),
    Arm("L_S15_T3", "Long ATR stop 1.5 / target 3", ("transaction_type=long", "atr_stop=1.5", "atr_target=3", "target_enabled=true")),
    Arm("L_S2_T3", "Long ATR stop 2 / target 3", ("transaction_type=long", "atr_stop=2", "atr_target=3", "target_enabled=true")),
    Arm("B_S1_T2", "Both sides ATR stop 1 / target 2", ("transaction_type=both", "atr_stop=1", "atr_target=2", "target_enabled=true")),
    Arm("B_S15_T3", "Both sides ATR stop 1.5 / target 3", ("transaction_type=both", "atr_stop=1.5", "atr_target=3", "target_enabled=true")),
    Arm("B_S2_T3", "Both sides ATR stop 2 / target 3", ("transaction_type=both", "atr_stop=2", "atr_target=3", "target_enabled=true")),
    Arm("B_S2_STOP_SMA20", "Both sides ATR stop 2, stop-only SMA20", ("transaction_type=both", "atr_stop=2", "atr_target=0", "target_enabled=false", "sma_stop_days=20")),
    Arm("B_S2_STOP_TIME250", "Both sides ATR stop 2, stop-only 250d", ("transaction_type=both", "atr_stop=2", "atr_target=0", "target_enabled=false", "atr_days=250", "atr_progress=0")),
)
REFERENCE = next(a for a in ARMS if a.id == "B_S15_T3")
OOS_FOLDS = (
    ("oos_2021_2022", "2021-01-01", "2022-12-31"),
    ("oos_2023_2024", "2023-01-01", "2024-12-31"),
    ("oos_2025_2026", "2025-01-01", "2026-12-31"),
)
FEASIBILITY_SYMBOLS = "SPY,AAPL,MSFT,AMZN,NVDA,META,JPM,XOM,UNH,CAT"


def spec(arm: Arm, phase: str, workers: int, symbols: str, *, start: str = "", end: str = "", skip: bool = False) -> dict:
    return {
        "root": ROOT, "prefix": "ADX", "common_values": COMMON, "arm": arm,
        "phase": phase, "workers": workers, "symbols": symbols, "start": start, "end": end,
        "skip_existing": skip,
    }


def write_report(results: list[dict], selected: Arm) -> None:
    write_csv(ROOT / "comparison.csv", results)
    by = {(r["phase"], r["id"]): r for r in results}
    wins = valid = 0
    choice_pnl = ref_pnl = 0.0
    for fold, _, _ in OOS_FOLDS:
        ref = by.get((fold, REFERENCE.id))
        choice = by.get((fold, selected.id))
        if not ref or not choice or not ref.get("ok") or not choice.get("ok"):
            continue
        valid += 1
        rm, cm = ref["metrics"], choice["metrics"]
        ref_pnl += float(rm.get("Total_PNL", 0) or 0)
        choice_pnl += float(cm.get("Total_PNL", 0) or 0)
        if (
            float(cm.get("Profit_Factor", 0) or 0) > float(rm.get("Profit_Factor", 0) or 0)
            and float(cm.get("Profit_Per_Capital_Day", 0) or 0) > float(rm.get("Profit_Per_Capital_Day", 0) or 0)
        ):
            wins += 1
    feasible = valid >= 2 and wins >= 2 and choice_pnl > 0
    verdict = "PROMISING, NOT PROVEN" if feasible else "NO ROBUST EDGE"
    lines = [
        "# ADX compression channel-breakout experiment",
        "",
        f"Generated: {datetime.now():%Y-%m-%d %H:%M:%S}",
        "",
        "Entry is fixed for every arm: Wilder ADX(15) below 20 on a completed signal bar, then a "
        "next-bar stop at the 10-bar channel. Exit selection used data through 2020 only.",
        "",
        f"**IS-selected arm:** `{selected.id}` — {selected.label}",
        f"**OOS verdict:** {verdict} ({wins}/{valid} folds beat the pre-registered `{REFERENCE.id}` "
        f"reference on PF and PPCD; selected aggregate PNL {choice_pnl:,.0f}).",
        "",
        "| phase | arm | trades | PNL | PF | DD | PPCD | AnnROR | avg/med/P90 hold | exp | streak | max symbol% |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
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
        "The `costs_2021_2026` row applies 10 bps slippage per side plus $2 round trip. "
        "Even that is only a coarse transaction-cost stress test; borrow availability/fees for shorts, "
        "gap liquidity, and market impact are not modeled.",
    ]
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--symbols", default="", help="Blank means the engine's full local universe")
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)

    results = run_jobs(
        [spec(a, "feasibility", args.workers, FEASIBILITY_SYMBOLS, skip=args.skip_existing) for a in ARMS[:3]],
        args.jobs,
    )
    results += run_jobs(
        [spec(a, "full", args.workers, args.symbols, skip=args.skip_existing) for a in ARMS],
        args.jobs,
    )
    is_results = run_jobs(
        [spec(a, "is_to_2020", args.workers, args.symbols, end="2020-12-31", skip=args.skip_existing) for a in ARMS],
        args.jobs,
    )
    results += is_results
    eligible = [r for r in is_results if r.get("ok") and float((r.get("metrics") or {}).get("Total_Trades", 0) or 0) > 0]
    if not eligible:
        write_csv(ROOT / "comparison.csv", results)
        (ROOT / "comparison.md").write_text(
            "# ADX compression channel-breakout experiment\n\n"
            "No successful in-sample arm completed. See run logs under `runs/`.\n",
            encoding="utf-8",
        )
        print(f"[write] {ROOT / 'comparison.md'} (no eligible IS arms)")
        return 1
    selected_result = max(eligible, key=lambda r: score(r.get("metrics") or {}))
    selected = next(a for a in ARMS if a.id == selected_result["id"])
    oos_specs = []
    for fold, start, end in OOS_FOLDS:
        for arm in {REFERENCE.id: REFERENCE, selected.id: selected}.values():
            oos_specs.append(spec(arm, fold, args.workers, args.symbols, start=start, end=end, skip=args.skip_existing))
    results += run_jobs(oos_specs, args.jobs)
    cost_arm = Arm(
        selected.id + "_COSTS",
        selected.label + " + 10bps/side + $2",
        selected.values + ("slippage_bps=10", "commission_per_trade=2"),
    )
    results += run_jobs(
        [spec(cost_arm, "costs_2021_2026", args.workers, args.symbols, start="2021-01-01", end="2026-12-31", skip=args.skip_existing)],
        1,
    )
    write_report(results, selected)
    print(f"[write] {ROOT / 'comparison.md'}")
    return 0 if all(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
