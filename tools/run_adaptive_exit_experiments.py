"""
Pre-registered adaptive-exit OOS experiments (Chandelier + detrended z-score).

Does NOT modify run_*.bat / DailyRun. Outputs under drive/adaptive_exit_exp/.
Select on entries through 2020; freeze and test OOS folds 2021-22, 2023-24, 2025-26.
"""
from __future__ import annotations

import argparse
import csv
import re
from datetime import datetime
from pathlib import Path

from davey_experiment_common import Arm, REPO, run_jobs, score, write_csv

ROOT = REPO / "drive" / "adaptive_exit_exp"
OOS_FOLDS = (
    ("oos_2021_2022", "2021-01-01", "2022-12-31"),
    ("oos_2023_2024", "2023-01-01", "2024-12-31"),
    ("oos_2025_2026", "2025-01-01", "2026-12-31"),
)

SYSTEMS: dict[str, dict] = {
    "BRT": {
        "prefix": "BRT",
        "bat": "run_brt.bat",
        "symbols_var": "BRT_SYMBOLS",
        "extra_args": (),
        "common": (
            "stop_pct=0.934", "target_pct=1.21", "too_high_multiplier=0",
            "band_pct=0.0154", "strong_pre_pivot_pct=0.081", "strong_post_pivot_pct=0.108",
            "strong_pre_pivot_bars=7", "strong_post_pivot_bars=7", "breakout_bars=100",
            "tight_range_threshold_pct=0.35", "tight_range_lookback=105",
            "sheet_breakout_scan_start_row_delta=2",
            "brt_sheet_touch=true", "min_spy_compare_1y_at_trigger=-12",
            "sheet_red_to_green_entry_enabled=true", "sheet_dw_countif_include_prior_bar_date=false",
            "growth_filter_enabled=true", "min_ind_score=-1", "compute_beta=true",
            "brt_zones=true", "yh_zones=false", "min_pivot_run_h_before_entry=0",
            "min_beta_at_trigger=0", "transaction_type=long", "liquidate_at_end=true",
        ),
    },
    "WPBR": {
        "prefix": "WPBR",
        "bat": "run_wpbr.bat",
        "symbols_var": "WPBR_SYMBOLS",
        "extra_args": (),
        "common": (
            "wpbr_zones=true", "brt_zones=false", "yh_zones=false", "vec_zones=false",
            "band_pct=0.015", "strong_pre_pivot_bars=3", "strong_pre_pivot_pct=0.10",
            "strong_post_pivot_bars=3", "strong_post_pivot_pct=0.10", "strong_pivot_mode=either",
            "wpbr_breakout_confirmation=0.03", "wpbr_max_days_after_retest=2",
            "growth_filter_enabled=false", "min_spy_compare_1y_at_trigger=-1000",
            "ind_score_weights_path=", "too_high_multiplier=0", "target_pct=1.24", "stop_pct=0.927",
            "transaction_type=long", "entry_mode=zones", "liquidate_at_end=true",
        ),
    },
    "MTS": {
        "prefix": "MTS",
        "bat": "run_mts.bat",
        "symbols_var": "MTS_SYMBOLS",
        "extra_args": ("--mts-sheet-parity",),
        "common": (
            "band_pct=0.018", "touch_threshold=2", "strong_post_pivot_bars=7",
            "strong_post_pivot_pct=0.06", "strong_pre_pivot_bars=7", "strong_pre_pivot_pct=0.12",
            "target_pct=1.22", "stop_pct=0.934", "stop_pct_is_multiplier=true",
            "stop_loss_based=trigger_low", "symbol_reentry_cooldown_days=20",
            "min_upper_wick_atr_at_trigger=0.25", "min_dist_to_52w_high_pct_at_trigger=25",
            "transaction_type=long", "liquidate_at_end=true",
        ),
    },
}


def load_symbols(system: str) -> str:
    meta = SYSTEMS[system]
    bat = (REPO / meta["bat"]).read_text(encoding="utf-8", errors="replace")
    match = re.search(rf'set "{meta["symbols_var"]}=([^"]+)"', bat)
    if not match:
        raise RuntimeError(f"Could not read {meta['symbols_var']} from {meta['bat']}")
    return match.group(1)


def chandelier_arms() -> list[Arm]:
    arms = [
        Arm("baseline_tgt", "Production stop + target", ("target_enabled=true", "chandelier_enabled=false")),
        Arm("baseline_stoponly", "Protective stop only", ("target_enabled=false", "chandelier_enabled=false")),
    ]
    for n in (14, 20):
        for k in (2.5, 3.5):
            for tgt, tag in ((True, "tgt"), (False, "so")):
                arms.append(
                    Arm(
                        f"chand_n{n}_k{str(k).replace('.', 'p')}_{tag}",
                        f"Chandelier N={n} k={k} target={'on' if tgt else 'off'}",
                        (
                            f"target_enabled={'true' if tgt else 'false'}",
                            "chandelier_enabled=true",
                            f"chandelier_atr_period={n}",
                            f"chandelier_atr_mult={k}",
                        ),
                    )
                )
    return arms


def zscore_arms() -> list[Arm]:
    arms = [
        Arm("baseline_tgt", "Production stop + target", ("target_enabled=true", "zscore_exit_enabled=false")),
        Arm("baseline_stoponly", "Protective stop only", ("target_enabled=false", "zscore_exit_enabled=false")),
    ]
    for n in (20, 40, 60):
        for k in (2.0, 2.5):
            for tgt, tag in ((True, "tgt"), (False, "so")):
                arms.append(
                    Arm(
                        f"z_n{n}_k{str(k).replace('.', 'p')}_{tag}",
                        f"Z-score N={n} k={k} target={'on' if tgt else 'off'}",
                        (
                            f"target_enabled={'true' if tgt else 'false'}",
                            "zscore_exit_enabled=true",
                            f"zscore_exit_lookback={n}",
                            f"zscore_exit_k={k}",
                        ),
                    )
                )
    return arms


def right_tail_guards(baseline_outdir: Path, selected_outdir: Path, prefix: str) -> dict:
    """Compare closed ledgers for truncated +20% winners and concentration."""
    def _load(outdir: Path) -> list[dict]:
        files = sorted(outdir.glob(f"{prefix}_Closed_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            return []
        with files[0].open(newline="", encoding="utf-8", errors="replace") as handle:
            return list(csv.DictReader(handle))

    base = _load(baseline_outdir)
    sel = _load(selected_outdir)
    if not base:
        return {}

    def _pnl(row: dict) -> float:
        for key in ("PNL_DOLLARS", "PNL_$", "PNL", "pnl_dollars"):
            if key in row and str(row[key]).strip():
                try:
                    return float(str(row[key]).replace(",", "").replace("$", ""))
                except ValueError:
                    pass
        return 0.0

    def _pct(row: dict) -> float:
        for key in ("PNL_PCT", "PNL_%", "pnl_pct"):
            if key in row and str(row[key]).strip():
                try:
                    return float(str(row[key]).replace("%", "").replace(",", ""))
                except ValueError:
                    pass
        return 0.0

    def _key(row: dict) -> tuple[str, str]:
        return (str(row.get("SYMBOL") or row.get("symbol") or ""), str(row.get("DATE_OPENED") or row.get("date_opened") or ""))

    base_big = { _key(r): _pct(r) for r in base if _pct(r) >= 20.0 }
    sel_map = { _key(r): _pct(r) for r in sel }
    trunc_count = 0
    trunc_pnl_lost = 0.0
    for k, bp in base_big.items():
        sp = sel_map.get(k)
        if sp is None or sp + 1e-9 < bp:
            trunc_count += 1
            trunc_pnl_lost += max(0.0, bp - (sp or 0.0))

    base_pnls = sorted((_pnl(r) for r in base), reverse=True)
    sel_pnls = sorted((_pnl(r) for r in sel), reverse=True)
    base_total = sum(base_pnls) or 1.0
    sel_total = sum(sel_pnls) or 1.0
    return {
        "baseline_top10_share": 100.0 * sum(base_pnls[:10]) / base_total,
        "selected_top10_share": 100.0 * sum(sel_pnls[:10]) / sel_total if sel else 0.0,
        "baseline_winners_gt20": len(base_big),
        "truncated_gt20_count": trunc_count,
        "truncated_gt20_pnl_pct_sum": trunc_pnl_lost,
    }


def oos_verdict(by: dict, selected_id: str, baseline_id: str = "baseline_tgt") -> tuple[str, int, int, float, float]:
    fold_wins = 0
    valid = 0
    selected_pnl = 0.0
    baseline_pnl = 0.0
    dd_ok = True
    trade_ok = True
    for fold, _, _ in OOS_FOLDS:
        base = by.get((fold, baseline_id))
        choice = by.get((fold, selected_id))
        if not base or not choice or not base.get("ok") or not choice.get("ok"):
            continue
        valid += 1
        bm, cm = base["metrics"], choice["metrics"]
        baseline_pnl += float(bm.get("Total_PNL", 0) or 0)
        selected_pnl += float(cm.get("Total_PNL", 0) or 0)
        if float(cm.get("Max_DD", 0) or 0) > float(bm.get("Max_DD", 0) or 0) + 2.0:
            dd_ok = False
        btr = float(bm.get("Total_Trades", 0) or 0)
        ctr = float(cm.get("Total_Trades", 0) or 0)
        if btr > 0 and ctr < 0.8 * btr:
            trade_ok = False
        if (
            float(cm.get("Profit_Factor", 0) or 0) > float(bm.get("Profit_Factor", 0) or 0)
            and float(cm.get("Profit_Per_Capital_Day", 0) or 0) > float(bm.get("Profit_Per_Capital_Day", 0) or 0)
        ):
            fold_wins += 1
    robust = (
        valid >= 2
        and fold_wins >= 2
        and selected_pnl > baseline_pnl
        and dd_ok
        and trade_ok
    )
    return ("ROBUST PASS" if robust else "DO NOT ADOPT"), fold_wins, valid, selected_pnl, baseline_pnl


def write_report(
    *,
    system: str,
    family: str,
    results: list[dict],
    selected: Arm,
    root: Path,
) -> None:
    write_csv(root / "comparison.csv", results)
    by = {(r["phase"], r["id"]): r for r in results}
    verdict, fold_wins, valid, sel_pnl, base_pnl = oos_verdict(by, selected.id)
    base_is = by.get(("is_to_2020", "baseline_tgt"))
    sel_is = by.get(("is_to_2020", selected.id))
    guards = {}
    if base_is and sel_is:
        guards = right_tail_guards(Path(base_is["outdir"]), Path(sel_is["outdir"]), SYSTEMS[system]["prefix"])
    lines = [
        f"# Adaptive exit experiment — {system} / {family}",
        "",
        f"Generated: {datetime.now():%Y-%m-%d %H:%M:%S}",
        "",
        "Pre-registered grid from `drive/Adaptive_Exit_Strategy_Ideas.md`. Production runners unchanged.",
        "IS selection on entries through 2020; OOS folds frozen independently.",
        "",
        f"**IS-selected arm:** `{selected.id}` — {selected.label}",
        f"**OOS verdict:** {verdict} ({fold_wins}/{valid} folds beat baseline_tgt on both PF and PPCD; "
        f"aggregate PNL {sel_pnl:,.0f} vs {base_pnl:,.0f}).",
        "",
    ]
    if guards:
        lines += [
            "**Right-tail guards (IS closed ledgers):**",
            f"- Baseline top-10 PnL share: {guards.get('baseline_top10_share', 0):.1f}%",
            f"- Selected top-10 PnL share: {guards.get('selected_top10_share', 0):.1f}%",
            f"- Baseline winners ≥+20%: {guards.get('baseline_winners_gt20', 0)}",
            f"- Truncated/weakened ≥+20% winners: {guards.get('truncated_gt20_count', 0)} "
            f"(sum Δpnl% {guards.get('truncated_gt20_pnl_pct_sum', 0):.1f})",
            "",
        ]
    lines += [
        "| phase | arm | trades | PNL | PF | DD | PPCD | AnnROR | avg/med/P90 hold | top10% | max symbol% |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|---:|---:|",
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
            f"{float(m.get('Pct_PNL_Top10', 0) or 0):.1f} | {float(m.get('Pct_PNL_Max_Symbol', 0) or 0):.1f} |"
        )
    root.mkdir(parents=True, exist_ok=True)
    (root / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_family(
    system: str,
    family: str,
    arms: list[Arm],
    *,
    jobs: int,
    workers: int,
    symbols: str,
    skip_existing: bool,
) -> tuple[list[dict], Arm]:
    meta = SYSTEMS[system]
    root = ROOT / system.lower() / family
    root.mkdir(parents=True, exist_ok=True)
    common = meta["common"]
    extra = list(meta.get("extra_args") or ())
    feasibility_symbols = ",".join(symbols.split(",")[:6])

    def spec(arm: Arm, phase: str, syms: str, *, start: str = "", end: str = "") -> dict:
        return {
            "root": root,
            "prefix": meta["prefix"],
            "common_values": common,
            "arm": arm,
            "phase": phase,
            "workers": workers,
            "symbols": syms,
            "start": start,
            "end": end,
            "skip_existing": skip_existing,
            "extra_args": extra,
        }

    results = run_jobs(
        [spec(a, "feasibility", feasibility_symbols) for a in arms[:3]],
        jobs,
    )
    is_results = run_jobs(
        [spec(a, "is_to_2020", symbols, end="2020-12-31") for a in arms],
        jobs,
    )
    results += is_results
    eligible = [
        r for r in is_results
        if r.get("ok") and r["id"] not in ("baseline_tgt", "baseline_stoponly")
    ]
    if not eligible:
        selected = arms[0]
    else:
        selected_result = max(eligible, key=lambda r: score(r.get("metrics") or {}))
        selected = next(a for a in arms if a.id == selected_result["id"])

    oos_specs = []
    baseline = next(a for a in arms if a.id == "baseline_tgt")
    for fold, start, end in OOS_FOLDS:
        oos_specs += [
            spec(baseline, fold, symbols, start=start, end=end),
            spec(selected, fold, symbols, start=start, end=end),
        ]
    results += run_jobs(oos_specs, jobs)
    write_report(system=system, family=family, results=results, selected=selected, root=root)
    print(f"[write] {root / 'comparison.md'}")
    return results, selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--systems", default="BRT,WPBR,MTS")
    parser.add_argument("--families", default="chandelier,zscore")
    parser.add_argument("--symbols", default="")
    args = parser.parse_args()

    ROOT.mkdir(parents=True, exist_ok=True)
    summary_lines: list[str] = []
    detail_lines: list[str] = []
    all_ok = True
    for system in [s.strip().upper() for s in args.systems.split(",") if s.strip()]:
        if system not in SYSTEMS:
            print(f"[skip] unknown system {system}")
            continue
        symbols = args.symbols or load_symbols(system)
        for family in [f.strip().lower() for f in args.families.split(",") if f.strip()]:
            if family == "chandelier":
                arms = chandelier_arms()
            elif family == "zscore":
                arms = zscore_arms()
            else:
                print(f"[skip] unknown family {family}")
                continue
            results, selected = run_family(
                system,
                family,
                arms,
                jobs=args.jobs,
                workers=args.workers,
                symbols=symbols,
                skip_existing=args.skip_existing,
            )
            by = {(r["phase"], r["id"]): r for r in results}
            verdict, fold_wins, valid, sel_pnl, base_pnl = oos_verdict(by, selected.id)
            summary_lines.append(
                f"| {system} | {family} | `{selected.id}` | {verdict} | {fold_wins}/{valid} | "
                f"{sel_pnl - base_pnl:+,.0f} |"
            )
            detail_lines.append(
                f"- **{system} × {family}**: selected `{selected.id}` → **{verdict}** "
                f"({fold_wins}/{valid} PF+PPCD folds; OOS PnL Δ {sel_pnl - base_pnl:+,.0f})"
            )
            if not all(r.get("ok") for r in results if r["phase"] != "feasibility"):
                all_ok = False

    header = [
        "# Adaptive exit OOS summary",
        "",
        f"Generated: {datetime.now():%Y-%m-%d %H:%M:%S}",
        "",
        "Pre-registered first-stage grids from `drive/Adaptive_Exit_Strategy_Ideas.md`.",
        "IS cutoff: entries through 2020. OOS folds: 2021–22, 2023–24, 2025–26 (frozen).",
        "Primary pass rule: ≥2/3 folds beat `baseline_tgt` on PF and PPCD, positive aggregate OOS PnL lift,",
        "no material DD increase (+2pp), ≥80% baseline trade count.",
        "",
        "| system | family | selected | verdict | folds | OOS PnL Δ |",
        "|---|---|---|---|---:|---:|",
    ]
    body = [
        "",
        "## Per-cell notes",
        "",
        *detail_lines,
        "",
        "RL skipped (separate exit engine in `rocket_rl.py`; not wired in this stage).",
        "Full tables: `drive/adaptive_exit_exp/<system>/<family>/comparison.md`.",
        "",
    ]
    (ROOT / "SUMMARY.md").write_text("\n".join(header + summary_lines + body), encoding="utf-8")
    print(f"[write] {ROOT / 'SUMMARY.md'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
