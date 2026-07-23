"""WPBR require_no_zone_above on full duckdb universe → profitable subset rerun.

1) Full-universe (no -s) with require_no_zone_above=true
2) Select symbols with TOTAL_PNL>0 and TRADES>=min_trades from Summary
3) Rerun subset with flag on (and optionally flag off)
Never edits run_wpbr.bat.
Outdir: drive/davey_experiments/wpbr_require_no_zone_above_universe/
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from davey_experiment_common import (
    Arm,
    REPO,
    latest,
    run_job,
    score,
    write_csv,
)

ROOT = REPO / "drive" / "davey_experiments" / "wpbr_require_no_zone_above_universe"

# run_wpbr.bat parity; require_no_zone_above overridden per arm
WPBR_COMMON = (
    "wpbr_zones=true",
    "brt_zones=false",
    "yh_zones=false",
    "vec_zones=false",
    "band_pct=0.015",
    "band_pct_atr=0",
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

# MarkTen require_no_zone_above compare (same parity) for verdict context
MARKTEN_REF = {
    "baseline_off": {"trades": 149, "pnl": 1708990, "pf": 2.61, "dd": 17.3, "score": 7.859},
    "require_on": {"trades": 29, "pnl": 573695, "pf": 4.16, "dd": 13.0, "score": None},
}


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
    return results


def _fp(x) -> float | None:
    if x is None:
        return None
    t = str(x).replace("%", "").replace(",", "").replace("$", "").strip()
    if not t or t.upper() == "N/A":
        return None
    try:
        return float(t)
    except ValueError:
        return None


def select_profitable(
    summary: Path,
    *,
    min_trades: int,
    min_pnl: float = 0.0,
) -> list[dict]:
    """Return rows from Summary with TOTAL_PNL>min_pnl and TRADES>=min_trades."""
    rows: list[dict] = []
    with summary.open(newline="", encoding="utf-8", errors="replace") as handle:
        for row in csv.DictReader(handle):
            sym = str(row.get("SYMBOL") or "").strip().upper()
            if not sym:
                continue
            trades = int(_fp(row.get("TRADES")) or 0)
            pnl = float(_fp(row.get("TOTAL_PNL")) or 0.0)
            if pnl > min_pnl and trades >= min_trades:
                rows.append(
                    {
                        "symbol": sym,
                        "trades": trades,
                        "total_pnl": pnl,
                        "wins": int(_fp(row.get("WINS")) or 0),
                        "losses": int(_fp(row.get("LOSSES")) or 0),
                        "avg_pnl_pct": row.get("AVG_PNL_PCT", ""),
                        "pct_of_total_pnl": row.get("PCT_OF_TOTAL_PNL", ""),
                    }
                )
    rows.sort(key=lambda r: r["total_pnl"], reverse=True)
    return rows


def stacked_from_closed(closed: Path, symbols: list[str] | None = None) -> tuple[list[str], str]:
    import pandas as pd

    df = pd.read_csv(closed)
    cols = {c.upper(): c for c in df.columns}

    def col(*names: str) -> str | None:
        for n in names:
            if n.upper() in cols:
                return cols[n.upper()]
        return None

    sym_c = col("SYMBOL")
    pnl_c = col("PNL_DOLLARS", "PNL", "PROFIT", "PNL_DOLLAR", "DOLLAR_PNL", "TOTAL_PNL", "PNL_USD")
    pct_c = col("PNL_PCT", "PROFIT_PCT", "PCT", "RETURN_PCT")
    days_c = col("DAYS_HELD", "DAYS", "DAYS_IN_TRADE", "HOLD_DAYS", "BARS_HELD")
    if symbols is None:
        symbols = sorted(df[sym_c].astype(str).str.upper().unique().tolist()) if sym_c else []

    blocks: list[str] = []
    tot_n = 0
    tot_dol = 0.0
    all_pcts: list[float] = []
    all_days: list[float] = []
    for sym in symbols:
        s = df[df[sym_c].astype(str).str.upper() == sym]
        n = len(s)
        tot_n += n
        pcts = [_fp(x) for x in s[pct_c]] if pct_c else []
        pcts = [p for p in pcts if p is not None]
        if pcts and (sum(abs(p) for p in pcts) / len(pcts) < 1.5):
            pcts = [p * 100 for p in pcts]
        all_pcts.extend(pcts)
        wins = [p for p in pcts if p > 0]
        losses = [p for p in pcts if p < 0]
        wr = 100.0 * len(wins) / n if n else 0.0
        avg = sum(pcts) / len(pcts) if pcts else 0.0
        aw = sum(wins) / len(wins) if wins else 0.0
        al = sum(losses) / len(losses) if losses else 0.0
        if losses and aw:
            wl = aw / abs(al)
        elif wins:
            wl = float("inf")
        else:
            wl = 0.0
        days: list[float] = []
        if days_c:
            for x in s[days_c]:
                v = _fp(x)
                if v is not None:
                    days.append(v)
        all_days.extend(days)
        avgd = sum(days) / len(days) if days else float("nan")
        dol = 0.0
        if pnl_c:
            for x in s[pnl_c]:
                v = _fp(x)
                if v is not None:
                    dol += v
        tot_dol += dol
        wl_s = f"{wl:.2f}" if wl != float("inf") else "inf"
        blocks.append(f"{sym}\n{n}\n{wr:.1f}%\n{avg:.1f}%\n{wl_s}\n{avgd:.1f}\n${dol:,.2f}")
    wins = [p for p in all_pcts if p > 0]
    losses = [p for p in all_pcts if p < 0]
    wr = 100.0 * len(wins) / tot_n if tot_n else 0.0
    avg = sum(all_pcts) / len(all_pcts) if all_pcts else 0.0
    aw = sum(wins) / len(wins) if wins else 0.0
    al = sum(losses) / len(losses) if losses else 0.0
    wl = (aw / abs(al)) if losses and aw else (float("inf") if wins else 0.0)
    avgd = sum(all_days) / len(all_days) if all_days else float("nan")
    wl_s = f"{wl:.2f}" if wl != float("inf") else "inf"
    agg = f"ALL\n{tot_n}\n{wr:.1f}%\n{avg:.1f}%\n{wl_s}\n{avgd:.1f}\n${tot_dol:,.2f}"
    return blocks, agg


def aggregate_davey_block(title: str, metrics: dict) -> str:
    sc = score(metrics) if metrics else float("-inf")
    sc_s = f"{sc:.3f}" if math.isfinite(sc) else "n/a"
    lines = [
        title,
        "score",
        sc_s,
        "trades",
        str(int(metrics.get("Total_Trades", 0) or 0)),
        "PNL",
        f"{float(metrics.get('Total_PNL', 0) or 0):.0f}",
        "PF",
        f"{float(metrics.get('Profit_Factor', 0) or 0):.2f}",
        "MaxDD",
        f"{float(metrics.get('Max_DD', 0) or 0):.2f}",
        "PPCD",
        f"{float(metrics.get('Profit_Per_Capital_Day', 0) or 0):.3f}",
        "AnnROR",
        f"{float(metrics.get('Ann_ROR', 0) or 0):.2f}",
        "AvgDays",
        f"{float(metrics.get('Avg_Days_Held', 0) or 0):.1f}",
        "MedDays",
        f"{float(metrics.get('Median_Days_Held', 0) or 0):.1f}",
        "P90Days",
        f"{float(metrics.get('P90_Days', 0) or 0):.1f}",
        "Expectancy",
        f"{float(metrics.get('Expectancy', 0) or 0):.2f}",
        "LoseStreak",
        str(int(metrics.get("Losing_Streak", 0) or 0)),
        "Win%",
        f"{float(metrics.get('Pct_Wins', 0) or 0):.2f}",
        "MaxSym%",
        f"{float(metrics.get('Pct_PNL_Max_Symbol', 0) or 0):.1f}",
        "MaxTrade%",
        f"{float(metrics.get('Pct_PNL_Max_Trade', 0) or 0):.1f}",
        "Top10%",
        f"{float(metrics.get('Pct_PNL_Top10', 0) or 0):.1f}",
        "AggPNL",
        f"{float(metrics.get('Aggressive_Total_PNL', 0) or 0):.2f}",
        "AggMaxDD",
        f"{float(metrics.get('Aggressive_Max_DD', 0) or 0):.2f}",
    ]
    return "\n".join(lines)


def write_paste(
    results: list[dict],
    *,
    selected: list[str],
    stack_limit: int = 80,
) -> Path:
    by_id = {r["id"]: r for r in results}
    order = [
        ("full_require_on", "Full universe (require_no_zone_above=on)"),
        ("subset_require_on", "Profitable subset (require_no_zone_above=on)"),
        ("subset_require_off", "Profitable subset (require_no_zone_above=off)"),
    ]
    lines: list[str] = []
    for arm_id, title in order:
        r = by_id.get(arm_id)
        if not r:
            continue
        lines.append(aggregate_davey_block(title, r.get("metrics") or {}))
        lines.append("")

    for arm_id, title in order:
        r = by_id.get(arm_id)
        if not r:
            continue
        outdir = Path(r.get("outdir") or "")
        closed = latest(outdir, "WPBR_Closed_*.csv") if outdir else None
        lines.append(f"=== {title} ===")
        if closed is None:
            lines.append("(no Closed CSV)")
            lines.append("")
            continue
        # Full-universe stacks are huge — only stack subset arms (or capped)
        if arm_id == "full_require_on":
            lines.append(f"(per-symbol stacks omitted for full universe; n_selected={len(selected)})")
            lines.append("")
            continue
        syms = selected if len(selected) <= stack_limit else selected[:stack_limit]
        blocks, agg = stacked_from_closed(closed, syms)
        if len(selected) > stack_limit:
            lines.append(f"(showing first {stack_limit} of {len(selected)} symbols by selection order)")
        lines.append("\n\n".join(blocks))
        lines.append("")
        lines.append(f"=== {title} AGG ===")
        lines.append(agg)
        lines.append("")
    out = ROOT / "_paste_require_no_zone_above_universe.txt"
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return out


def write_report(
    results: list[dict],
    *,
    selected_rows: list[dict],
    min_trades: int,
    universe_note: str,
) -> Path:
    write_csv(ROOT / "comparison.csv", results)
    by_id = {r["id"]: r for r in results}
    ok = [r for r in results if r.get("ok") and (r.get("metrics") or {}).get("Total_Trades", 0)]
    ranked = sorted(ok, key=lambda r: score(r.get("metrics") or {}), reverse=True)
    sel_syms = [r["symbol"] for r in selected_rows]

    lines = [
        "# WPBR require_no_zone_above full-universe → profitable subset",
        "",
        f"Generated: {datetime.now():%Y-%m-%d %H:%M:%S}",
        "",
        "## Setup",
        "",
        f"- Universe screen: {universe_note}",
        "- System: WPBR only (`wpbr_zones=true`, classic brt/yh/vec off)",
        "- Parity: target 1.22, stop 0.91, start_date 2016-01-01, SC after win, "
        "band_pct=0.015 (atr=0), sheet_no_entry_same_bar_after_exit=false, BO conf 0.03, "
        "max_days_after_retest 2, strong pivot either 3/10%, growth off",
        "- Screen arm: `require_no_zone_above=true` on full universe",
        f"- Selection: Summary TOTAL_PNL > 0 and TRADES >= {min_trades}",
        f"- Selected symbols: **{len(sel_syms)}**",
        "",
        "## Caveat (selection bias)",
        "",
        "Symbols are picked from the **same** in-sample history used for the subset rerun. "
        "This **overfits** — treat subset results as an exploratory upper bound "
        "(\"if we only traded clear-runway symbols that looked good historically\"), "
        "not as a deployable edge estimate.",
        "",
        "## Selected symbols",
        "",
        "```",
        ",".join(sel_syms),
        "```",
        "",
        "| symbol | trades | TOTAL_PNL |",
        "|---|---:|---:|",
    ]
    for row in selected_rows:
        lines.append(f"| {row['symbol']} | {row['trades']} | {row['total_pnl']:.0f} |")

    lines += [
        "",
        "## Ranking (by score)",
        "",
        "| rank | arm | trades | PNL | PF | DD | PPCD | AnnROR | score |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for i, r in enumerate(ranked, 1):
        m = r.get("metrics") or {}
        sc = score(m)
        sc_s = f"{sc:.3f}" if math.isfinite(sc) else "n/a"
        lines.append(
            f"| {i} | {r['id']} | {int(m.get('Total_Trades', 0) or 0)} | "
            f"{float(m.get('Total_PNL', 0) or 0):.0f} | {float(m.get('Profit_Factor', 0) or 0):.2f} | "
            f"{float(m.get('Max_DD', 0) or 0):.1f} | {float(m.get('Profit_Per_Capital_Day', 0) or 0):.3f} | "
            f"{float(m.get('Ann_ROR', 0) or 0):.1f} | {sc_s} |"
        )

    # Verdict vs MarkTen
    full = by_id.get("full_require_on", {}).get("metrics") or {}
    sub_on = by_id.get("subset_require_on", {}).get("metrics") or {}
    sub_off = by_id.get("subset_require_off", {}).get("metrics") or {}
    mt_on = MARKTEN_REF["require_on"]
    mt_off = MARKTEN_REF["baseline_off"]

    lines += [
        "",
        "## Verdict vs MarkTen-only treatment",
        "",
        f"- MarkTen flag-on: trades={mt_on['trades']}, PNL={mt_on['pnl']}, PF={mt_on['pf']}, "
        f"DD={mt_on['dd']} (score n/a; <30 trades)",
        f"- MarkTen flag-off: trades={mt_off['trades']}, PNL={mt_off['pnl']}, PF={mt_off['pf']}, "
        f"DD={mt_off['dd']}, score={mt_off['score']}",
        f"- Full-universe flag-on: trades={int(full.get('Total_Trades', 0) or 0)}, "
        f"PNL={float(full.get('Total_PNL', 0) or 0):.0f}, "
        f"PF={float(full.get('Profit_Factor', 0) or 0):.2f}, "
        f"DD={float(full.get('Max_DD', 0) or 0):.1f}",
        f"- Profitable-subset flag-on: trades={int(sub_on.get('Total_Trades', 0) or 0)}, "
        f"PNL={float(sub_on.get('Total_PNL', 0) or 0):.0f}, "
        f"PF={float(sub_on.get('Profit_Factor', 0) or 0):.2f}, "
        f"DD={float(sub_on.get('Max_DD', 0) or 0):.1f}",
    ]
    if sub_off:
        lines.append(
            f"- Profitable-subset flag-off: trades={int(sub_off.get('Total_Trades', 0) or 0)}, "
            f"PNL={float(sub_off.get('Total_PNL', 0) or 0):.0f}, "
            f"PF={float(sub_off.get('Profit_Factor', 0) or 0):.2f}, "
            f"DD={float(sub_off.get('Max_DD', 0) or 0):.1f}"
        )

    full_pnl = float(full.get("Total_PNL", 0) or 0)
    sub_pnl = float(sub_on.get("Total_PNL", 0) or 0)
    if full_pnl and sub_pnl:
        lines.append(
            f"- Subset captures {100.0 * sub_pnl / full_pnl:.1f}% of full-universe flag-on PNL "
            f"on {len(sel_syms)} symbols (in-sample selected)."
        )
    lines += [
        "",
        "Plain read: MarkTen flag-on **cuts** trade count hard vs flag-off while lifting PF; "
        "full-universe screening finds whether that filter has a broader profitable pocket. "
        "Subset rerun is **not** OOS validation.",
        "",
        f"Artifacts: `{ROOT}` — `comparison.csv`, `comparison.md`, "
        "`selected_symbols.csv`, `_paste_require_no_zone_above_universe.txt`",
    ]
    out = ROOT / "comparison.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", "-w", type=int, default=24)
    parser.add_argument("--jobs", type=int, default=2, help="Parallel jobs for subset arms")
    parser.add_argument("--min-trades", type=int, default=5)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument(
        "--skip-subset-off",
        action="store_true",
        help="Skip profitable-subset flag-off baseline",
    )
    parser.add_argument(
        "--symbols",
        default="",
        help="Optional comma list; empty = full duckdb/CSV universe (no -s)",
    )
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)

    universe_note = (
        f"explicit -s ({len(args.symbols.split(','))} symbols)"
        if args.symbols.strip()
        else "full duckdb/CSV universe (no -s filter; ~1068 symbols in ohlcv.duckdb)"
    )
    grid_doc = {
        "common": list(WPBR_COMMON),
        "workers": args.workers,
        "jobs": args.jobs,
        "min_trades": args.min_trades,
        "symbols": args.symbols or "(full universe)",
        "started": datetime.now().isoformat(timespec="seconds"),
    }
    (ROOT / "grid.json").write_text(json.dumps(grid_doc, indent=2), encoding="utf-8")
    print(
        f"[wpbr_require_no_zone_above_universe] workers={args.workers} "
        f"min_trades={args.min_trades} universe={universe_note}",
        flush=True,
    )
    print(f"[wpbr_require_no_zone_above_universe] outdir={ROOT}", flush=True)

    # Phase 1: full universe flag on
    full_arm = Arm(
        "full_require_on",
        "Full universe require_no_zone_above=true",
        ("require_no_zone_above=true",),
    )
    full_results = run_jobs_uncapped(
        [
            {
                "root": ROOT,
                "prefix": "WPBR",
                "common_values": WPBR_COMMON,
                "arm": full_arm,
                "phase": "screen",
                "workers": args.workers,
                "symbols": args.symbols.strip(),
                "skip_existing": args.skip_existing,
            }
        ],
        jobs=1,
    )
    full = full_results[0]
    if not full.get("ok"):
        print(f"[error] full-universe run failed: {full.get('error')}", flush=True)
        (ROOT / "status.json").write_text(json.dumps({"full": full}, indent=2, default=str), encoding="utf-8")
        return 1

    outdir = Path(full["outdir"])
    summary = latest(outdir, "WPBR_Summary_*.csv")
    if summary is None:
        print(f"[error] no Summary in {outdir}", flush=True)
        return 1

    selected_rows = select_profitable(summary, min_trades=args.min_trades)
    sel_syms = [r["symbol"] for r in selected_rows]
    sel_csv = ROOT / "selected_symbols.csv"
    with sel_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["symbol", "trades", "total_pnl", "wins", "losses", "avg_pnl_pct", "pct_of_total_pnl"],
        )
        writer.writeheader()
        writer.writerows(selected_rows)
    (ROOT / "selected_symbols.txt").write_text(",".join(sel_syms) + "\n", encoding="utf-8")
    print(
        f"[select] {len(sel_syms)} symbols with TOTAL_PNL>0 and TRADES>={args.min_trades} "
        f"from {summary.name}",
        flush=True,
    )
    if not sel_syms:
        write_report(
            full_results,
            selected_rows=[],
            min_trades=args.min_trades,
            universe_note=universe_note,
        )
        print("[warn] no symbols passed selection; skipping subset reruns", flush=True)
        return 0

    # Phase 2: subset on (+ optional off)
    subset_arms = [
        Arm(
            "subset_require_on",
            "Profitable subset require_no_zone_above=true",
            ("require_no_zone_above=true",),
        )
    ]
    if not args.skip_subset_off:
        subset_arms.append(
            Arm(
                "subset_require_off",
                "Profitable subset require_no_zone_above=false",
                ("require_no_zone_above=false",),
            )
        )
    subset_specs = [
        {
            "root": ROOT,
            "prefix": "WPBR",
            "common_values": WPBR_COMMON,
            "arm": arm,
            "phase": "subset",
            "workers": min(args.workers, max(4, len(sel_syms))),
            "symbols": ",".join(sel_syms),
            "skip_existing": args.skip_existing,
        }
        for arm in subset_arms
    ]
    subset_results = run_jobs_uncapped(subset_specs, jobs=min(args.jobs, len(subset_specs)))
    all_results = full_results + subset_results

    report = write_report(
        all_results,
        selected_rows=selected_rows,
        min_trades=args.min_trades,
        universe_note=universe_note,
    )
    paste = write_paste(all_results, selected=sel_syms)
    status = {
        "updated": datetime.now().isoformat(timespec="seconds"),
        "min_trades": args.min_trades,
        "selected_count": len(sel_syms),
        "selected": sel_syms,
        "completed": len(all_results),
        "ok": sum(1 for r in all_results if r.get("ok")),
        "results": [
            {
                "id": r.get("id"),
                "ok": r.get("ok"),
                "elapsed_s": r.get("elapsed_s"),
                "Total_PNL": (r.get("metrics") or {}).get("Total_PNL"),
                "Profit_Factor": (r.get("metrics") or {}).get("Profit_Factor"),
                "Max_DD": (r.get("metrics") or {}).get("Max_DD"),
                "Total_Trades": (r.get("metrics") or {}).get("Total_Trades"),
                "score": score(r.get("metrics") or {}) if r.get("ok") else None,
            }
            for r in sorted(all_results, key=lambda x: x.get("id") or "")
        ],
    }
    (ROOT / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    print(f"[write] {report}", flush=True)
    print(f"[write] {paste}", flush=True)
    print(f"[write] {sel_csv}", flush=True)
    print(paste.read_text(encoding="utf-8"), flush=True)
    return 0 if all(r.get("ok") for r in all_results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
