"""WPBR second_chance_after_win on vs off — MarkTen parity compare.

Fair capital A/B: only flip wpbr_second_chance_after_win; everything else matches
run_wpbr.bat baseline (band 0.015, target 1.22, stop 0.91, start 2016, secondary off).
Never edits run_wpbr.bat. Outdir: drive/davey_experiments/wpbr_sc_on_off_markten/
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

ROOT = REPO / "drive" / "davey_experiments" / "wpbr_sc_on_off_markten"
MARKTEN = "AAPL,AMZN,GOOGL,META,MSFT,NVDA,TSLA,AU,AMD,NFLX"
MARKTEN_LIST = MARKTEN.split(",")

# run_wpbr.bat parity; wpbr_second_chance_after_win overridden per arm
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
    "growth_filter_enabled=false",
    "min_spy_compare_1y_at_trigger=-1000",
    "ind_score_weights_path=",
    "too_high_multiplier=0",
    "target_pct=1.22",
    "stop_pct=0.91",
    "start_date=2016-01-01",
    "sheet_no_entry_same_bar_after_exit=false",
    "allow_secondary_entries=false",
    "use_indicators=true",
    "transaction_type=long",
    "entry_mode=zones",
    "liquidate_at_end=true",
)


def build_arms() -> list[Arm]:
    return [
        Arm(
            "sc_off",
            "wpbr_second_chance_after_win=false",
            ("wpbr_second_chance_after_win=false",),
        ),
        Arm(
            "sc_on",
            "wpbr_second_chance_after_win=true (run_wpbr.bat default)",
            ("wpbr_second_chance_after_win=true",),
        ),
    ]


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


def enrich_report_fields(result: dict) -> dict:
    """Pull Wins / Max_Positions from Report (not in davey METRICS list)."""
    outdir = Path(result.get("outdir") or "")
    report = latest(outdir, "WPBR_Report_*.csv") or latest(outdir, "WPBR_Audit_Report_*.csv")
    metrics = dict(result.get("metrics") or {})
    if report is None:
        result["metrics"] = metrics
        return result
    with report.open(newline="", encoding="utf-8", errors="replace") as handle:
        row = next(csv.DictReader(handle), None) or {}
    for key in ("Wins", "Losses", "Max_Positions", "Win_Loss_Ratio", "Expectancy"):
        if key in row and row[key] not in (None, ""):
            try:
                metrics[key] = float(str(row[key]).replace(",", "").replace("$", "").strip())
            except ValueError:
                pass
    result["metrics"] = metrics
    return result


def stacked_from_closed(closed: Path) -> tuple[list[str], str]:
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
    blocks: list[str] = []
    tot_n = 0
    tot_dol = 0.0
    all_pcts: list[float] = []
    all_days: list[float] = []
    for sym in MARKTEN_LIST:
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


def isolate_sc_trades(closed_on: Path) -> dict:
    """Second+ purchase per (SYMBOL, WPBR_ZONE_ID) by DATE_OPENED = true SC entries."""
    import pandas as pd

    df = pd.read_csv(closed_on)
    cols = {c.upper(): c for c in df.columns}
    sym_c = cols.get("SYMBOL")
    zid_c = cols.get("WPBR_ZONE_ID")
    open_c = cols.get("DATE_OPENED")
    pnl_c = cols.get("PNL_DOLLARS") or cols.get("PNL")
    pct_c = cols.get("PNL_PCT")
    if not sym_c or not zid_c or not open_c:
        return {"n": 0, "wins": 0, "losses": 0, "wr": 0.0, "pnl": 0.0, "note": "missing columns"}

    work = df.copy()
    work["_open"] = pd.to_datetime(work[open_c], errors="coerce")
    work = work.sort_values(["_open", open_c], kind="mergesort")
    sc_rows = []
    for _, g in work.groupby([sym_c, zid_c], dropna=False):
        if len(g) < 2:
            continue
        sc_rows.append(g.iloc[1:])
    if not sc_rows:
        return {"n": 0, "wins": 0, "losses": 0, "wr": 0.0, "pnl": 0.0, "avg_pct": 0.0}
    sc = pd.concat(sc_rows, ignore_index=True)
    pcts = [_fp(x) for x in sc[pct_c]] if pct_c else []
    pcts = [p for p in pcts if p is not None]
    if pcts and (sum(abs(p) for p in pcts) / len(pcts) < 1.5):
        pcts = [p * 100 for p in pcts]
    wins = [p for p in pcts if p > 0]
    losses = [p for p in pcts if p < 0]
    dol = 0.0
    if pnl_c:
        for x in sc[pnl_c]:
            v = _fp(x)
            if v is not None:
                dol += v
    n = len(sc)
    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "wr": 100.0 * len(wins) / n if n else 0.0,
        "pnl": dol,
        "avg_pct": sum(pcts) / len(pcts) if pcts else 0.0,
    }


def aggregate_davey_block(title: str, metrics: dict) -> str:
    sc = score(metrics) if metrics else float("-inf")
    sc_s = f"{sc:.3f}" if math.isfinite(sc) else "n/a"
    wins = int(metrics.get("Wins", 0) or 0)
    trades = int(metrics.get("Total_Trades", 0) or 0)
    losses = int(metrics.get("Losses", 0) or 0) or max(0, trades - wins)
    lines = [
        title,
        "score",
        sc_s,
        "trades",
        str(trades),
        "wins",
        str(wins),
        "losses",
        str(losses),
        "WR%",
        f"{float(metrics.get('Pct_Wins', 0) or 0):.2f}",
        "PNL",
        f"{float(metrics.get('Total_PNL', 0) or 0):.0f}",
        "PF",
        f"{float(metrics.get('Profit_Factor', 0) or 0):.2f}",
        "Expectancy",
        f"{float(metrics.get('Expectancy', 0) or 0):.2f}",
        "MaxDD",
        f"{float(metrics.get('Max_DD', 0) or 0):.2f}",
        "MaxPos",
        str(int(metrics.get("Max_Positions", 0) or 0)),
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
        "LoseStreak",
        str(int(metrics.get("Losing_Streak", 0) or 0)),
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


def _row_metrics(r: dict) -> dict:
    return r.get("metrics") or {}


def verdict_sentence(by_id: dict) -> str:
    on = _row_metrics(by_id.get("sc_on") or {})
    off = _row_metrics(by_id.get("sc_off") or {})
    pnl_on = float(on.get("Total_PNL", 0) or 0)
    pnl_off = float(off.get("Total_PNL", 0) or 0)
    delta = pnl_on - pnl_off
    # Flat if within ~1% of |off| PNL or <$5k absolute when off is tiny
    denom = max(abs(pnl_off), 1.0)
    if abs(delta) / denom < 0.01 and abs(delta) < 25000:
        return (
            f"Verdict: SC is flat on MarkTen baseline "
            f"(ΔPNL ${delta:,.0f}: on ${pnl_on:,.0f} vs off ${pnl_off:,.0f})."
        )
    if delta > 0:
        return (
            f"Verdict: SC helps on MarkTen baseline "
            f"(+${delta:,.0f} Closed $: on ${pnl_on:,.0f} vs off ${pnl_off:,.0f})."
        )
    return (
        f"Verdict: SC hurts on MarkTen baseline "
        f"(${delta:,.0f} Closed $: on ${pnl_on:,.0f} vs off ${pnl_off:,.0f})."
    )


def write_paste(results: list[dict], sc_iso: dict) -> Path:
    by_id = {r["id"]: r for r in results}
    titles = {
        "sc_off": "SC OFF (wpbr_second_chance_after_win=false)",
        "sc_on": "SC ON (wpbr_second_chance_after_win=true)",
    }
    lines: list[str] = []
    for arm_id, title in titles.items():
        r = by_id.get(arm_id) or {}
        m = r.get("metrics") or {}
        lines.append(aggregate_davey_block(title, m))
        lines.append("")
    lines.append("=== True SC trades (SC-on only: 2nd+ purchase per zone) ===")
    lines.append(
        f"n={sc_iso.get('n', 0)} wins={sc_iso.get('wins', 0)} losses={sc_iso.get('losses', 0)} "
        f"WR={sc_iso.get('wr', 0):.1f}% PNL=${sc_iso.get('pnl', 0):,.2f} "
        f"avg_pct={sc_iso.get('avg_pct', 0):.1f}%"
    )
    lines.append("")
    lines.append(verdict_sentence(by_id))
    lines.append("")
    for arm_id, title in titles.items():
        r = by_id.get(arm_id) or {}
        outdir = Path(r.get("outdir") or "")
        closed = latest(outdir, "WPBR_Closed_*.csv") if outdir else None
        lines.append(f"=== {title} ===")
        if closed is None:
            lines.append("(no Closed CSV)")
            lines.append("")
            continue
        blocks, agg = stacked_from_closed(closed)
        lines.append("\n\n".join(blocks))
        lines.append("")
        lines.append(f"=== {title} AGG ===")
        lines.append(agg)
        lines.append("")
    out = ROOT / "_paste_wpbr_sc_on_off.txt"
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return out


def write_report(results: list[dict], sc_iso: dict) -> Path:
    write_csv(ROOT / "comparison.csv", results)
    by_id = {r["id"]: r for r in results}
    ok = [r for r in results if r.get("ok") and (r.get("metrics") or {}).get("Total_Trades", 0)]
    ranked = sorted(ok, key=lambda r: score(r.get("metrics") or {}), reverse=True)
    lines = [
        "# WPBR second_chance_after_win — MarkTen on vs off",
        "",
        f"Generated: {datetime.now():%Y-%m-%d %H:%M:%S}",
        "",
        "## Setup",
        "",
        "- Universe: MarkTen (AAPL,AMZN,GOOGL,META,MSFT,NVDA,TSLA,AU,AMD,NFLX)",
        "- System: WPBR only (`wpbr_zones=true`, classic brt/yh/vec off)",
        "- Parity: target 1.22, stop 0.91, start_date 2016-01-01, band_pct=0.015, "
        "sheet_no_entry_same_bar_after_exit=false, allow_secondary_entries=false, "
        "use_indicators=true, BO conf 0.03, max_days_after_retest 2, strong pivot either 3/10%, growth off",
        "- Arms: `wpbr_second_chance_after_win=false` vs `true` (only flip)",
        "- `run_wpbr.bat` not modified (production remains SC on)",
        "",
        "## Summary table",
        "",
        "| arm | trades | wins | losses | WR% | Closed $ | PF | Expectancy | MaxDD | Max_Positions |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm_id in ("sc_off", "sc_on"):
        r = by_id.get(arm_id) or {}
        m = r.get("metrics") or {}
        trades = int(m.get("Total_Trades", 0) or 0)
        wins = int(m.get("Wins", 0) or 0)
        losses = int(m.get("Losses", 0) or 0) or max(0, trades - wins)
        lines.append(
            f"| {arm_id} | {trades} | {wins} | {losses} | "
            f"{float(m.get('Pct_Wins', 0) or 0):.1f} | "
            f"{float(m.get('Total_PNL', 0) or 0):.0f} | "
            f"{float(m.get('Profit_Factor', 0) or 0):.2f} | "
            f"{float(m.get('Expectancy', 0) or 0):.0f} | "
            f"{float(m.get('Max_DD', 0) or 0):.1f} | "
            f"{int(m.get('Max_Positions', 0) or 0)} |"
        )
    lines += [
        "",
        "## True SC trades (SC-on arm only)",
        "",
        "Definition: within SC-on Closed, 2nd+ entry chronologically for the same "
        "`(SYMBOL, WPBR_ZONE_ID)` — these only exist because second-chance after a win.",
        "",
        f"- Count: **{sc_iso.get('n', 0)}**",
        f"- Wins/Losses: {sc_iso.get('wins', 0)} / {sc_iso.get('losses', 0)}",
        f"- WR: **{sc_iso.get('wr', 0):.1f}%**",
        f"- Isolated Closed $: **${sc_iso.get('pnl', 0):,.2f}**",
        f"- Avg PNL%: {sc_iso.get('avg_pct', 0):.1f}%",
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
    lines += [
        "",
        f"**{verdict_sentence(by_id)}**",
        "",
        f"Artifacts: `{ROOT}` — `comparison.csv`, `comparison.md`, `_paste_wpbr_sc_on_off.txt`, `runs/`",
    ]
    out = ROOT / "comparison.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=2, help="Concurrent arms (default 2)")
    parser.add_argument("--workers", "-w", type=int, default=10, help="rocket_brt -w per arm")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--symbols", default=MARKTEN)
    parser.add_argument("--phase", default="markten")
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    arms = build_arms()
    grid_doc = {
        "arms": [{"id": a.id, "label": a.label, "values": list(a.values)} for a in arms],
        "symbols": args.symbols,
        "jobs": args.jobs,
        "workers": args.workers,
        "common": list(WPBR_COMMON),
        "started": datetime.now().isoformat(timespec="seconds"),
        "note": "only flip wpbr_second_chance_after_win; allow_secondary_entries=false",
    }
    (ROOT / "grid.json").write_text(json.dumps(grid_doc, indent=2), encoding="utf-8")
    print(
        f"[wpbr_sc_on_off] arms={len(arms)} jobs={args.jobs} workers={args.workers}",
        flush=True,
    )
    print(f"[wpbr_sc_on_off] outdir={ROOT}", flush=True)

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
    results = [enrich_report_fields(r) for r in run_jobs_uncapped(specs, args.jobs)]

    sc_iso: dict = {"n": 0, "wins": 0, "losses": 0, "wr": 0.0, "pnl": 0.0, "avg_pct": 0.0}
    by_id = {r["id"]: r for r in results}
    on = by_id.get("sc_on") or {}
    on_outdir = Path(on.get("outdir") or "")
    closed_on = latest(on_outdir, "WPBR_Closed_*.csv") if on_outdir else None
    if closed_on is not None:
        sc_iso = isolate_sc_trades(closed_on)

    report = write_report(results, sc_iso)
    paste = write_paste(results, sc_iso)
    status = {
        "updated": datetime.now().isoformat(timespec="seconds"),
        "completed": len(results),
        "ok": sum(1 for r in results if r.get("ok")),
        "sc_isolated": sc_iso,
        "verdict": verdict_sentence(by_id),
        "results": [
            {
                "id": r.get("id"),
                "ok": r.get("ok"),
                "elapsed_s": r.get("elapsed_s"),
                "Total_PNL": (r.get("metrics") or {}).get("Total_PNL"),
                "Profit_Factor": (r.get("metrics") or {}).get("Profit_Factor"),
                "Max_DD": (r.get("metrics") or {}).get("Max_DD"),
                "Max_Positions": (r.get("metrics") or {}).get("Max_Positions"),
                "Total_Trades": (r.get("metrics") or {}).get("Total_Trades"),
                "Pct_Wins": (r.get("metrics") or {}).get("Pct_Wins"),
                "Expectancy": (r.get("metrics") or {}).get("Expectancy"),
                "score": score(r.get("metrics") or {}) if r.get("ok") else None,
            }
            for r in sorted(results, key=lambda x: x.get("id") or "")
        ],
    }
    (ROOT / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    print(f"[write] {report}", flush=True)
    print(f"[write] {paste}", flush=True)
    print(paste.read_text(encoding="utf-8"), flush=True)
    return 0 if all(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
