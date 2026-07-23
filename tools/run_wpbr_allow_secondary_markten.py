"""WPBR allow_secondary_entries=true on MarkTen — davey single-arm.

Parity matches run_wpbr.bat PLUS allow_secondary_entries=true.
Never edits run_wpbr.bat.
Outdir: drive/davey_experiments/wpbr_allow_secondary_markten/
"""
from __future__ import annotations

import argparse
import json
import math
import sys
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

ROOT = REPO / "drive" / "davey_experiments" / "wpbr_allow_secondary_markten"
MARKTEN = "AAPL,AMZN,GOOGL,META,MSFT,NVDA,TSLA,AU,AMD,NFLX"
MARKTEN_LIST = MARKTEN.split(",")

# run_wpbr.bat parity + allow_secondary_entries
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


def write_paste(result: dict) -> Path:
    m = result.get("metrics") or {}
    title = "allow_secondary_entries=true (MarkTen)"
    lines = [aggregate_davey_block(title, m), ""]
    outdir = Path(result.get("outdir") or "")
    closed = latest(outdir, "WPBR_Closed_*.csv") if outdir else None
    lines.append(f"=== {title} ===")
    if closed is None:
        lines.append("(no Closed CSV)")
    else:
        blocks, agg = stacked_from_closed(closed)
        lines.append("\n\n".join(blocks))
        lines.append("")
        lines.append(f"=== {title} AGG ===")
        lines.append(agg)
    # Baseline note (parity MarkTen without secondary)
    lines += [
        "",
        "=== vs baseline (allow_secondary=false, prior parity) ===",
        "baseline_trades",
        "149",
        "baseline_PNL",
        "~1708990",
        "baseline_PF",
        "2.61",
        "delta_trades",
        str(int(m.get("Total_Trades", 0) or 0) - 149),
        "delta_PNL",
        f"{float(m.get('Total_PNL', 0) or 0) - 1708990:.0f}",
        "delta_PF",
        f"{float(m.get('Profit_Factor', 0) or 0) - 2.61:.2f}",
    ]
    out = ROOT / "_paste_allow_secondary_markten.txt"
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return out


def write_report(result: dict) -> Path:
    write_csv(ROOT / "comparison.csv", [result])
    m = result.get("metrics") or {}
    sc = score(m) if result.get("ok") else float("-inf")
    sc_s = f"{sc:.3f}" if math.isfinite(sc) else "n/a"
    lines = [
        "# WPBR allow_secondary_entries MarkTen",
        "",
        f"Generated: {datetime.now():%Y-%m-%d %H:%M:%S}",
        "",
        "## Setup",
        "",
        "- Universe: MarkTen (AAPL,AMZN,GOOGL,META,MSFT,NVDA,TSLA,AU,AMD,NFLX)",
        "- System: WPBR only (`wpbr_zones=true`, classic brt/yh/vec off)",
        "- Parity: target 1.22, stop 0.91, start_date 2016-01-01, SC after win, "
        "band_pct=0.015 (atr=0), sheet_no_entry_same_bar_after_exit=false, BO conf 0.03, "
        "max_days_after_retest 2, strong pivot either 3/10%, growth off",
        "- **Arm: `allow_secondary_entries=true`** (default / run_wpbr.bat remains false)",
        "- Primary score: davey `score` = 2*PF + 0.02*PPCD - 0.03*MaxDD - 0.002*max_symbol% "
        "(requires >=30 trades)",
        "",
        "## Result",
        "",
        "| arm | trades | PNL | PF | DD | PPCD | AnnROR | Expectancy | score |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"| allow_secondary=true | {int(m.get('Total_Trades', 0) or 0)} | "
        f"{float(m.get('Total_PNL', 0) or 0):.0f} | {float(m.get('Profit_Factor', 0) or 0):.2f} | "
        f"{float(m.get('Max_DD', 0) or 0):.1f} | {float(m.get('Profit_Per_Capital_Day', 0) or 0):.3f} | "
        f"{float(m.get('Ann_ROR', 0) or 0):.1f} | {float(m.get('Expectancy', 0) or 0):.2f} | {sc_s} |",
        "",
        "## vs baseline (secondary off)",
        "",
        "| | trades | PNL | PF |",
        "|---|---:|---:|---:|",
        "| baseline (parity) | 149 | 1708990 | 2.61 |",
        f"| allow_secondary=true | {int(m.get('Total_Trades', 0) or 0)} | "
        f"{float(m.get('Total_PNL', 0) or 0):.0f} | {float(m.get('Profit_Factor', 0) or 0):.2f} |",
        f"| delta | {int(m.get('Total_Trades', 0) or 0) - 149} | "
        f"{float(m.get('Total_PNL', 0) or 0) - 1708990:.0f} | "
        f"{float(m.get('Profit_Factor', 0) or 0) - 2.61:+.2f} |",
        "",
        f"Artifacts: `{ROOT}` — `comparison.csv`, `comparison.md`, `status.json`, "
        "`_paste_allow_secondary_markten.txt`, `runs/<phase>__<arm>/`",
    ]
    out = ROOT / "comparison.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", "-w", type=int, default=10)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--symbols", default=MARKTEN)
    parser.add_argument("--phase", default="markten")
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    arm = Arm(
        "sec_on",
        "allow_secondary_entries=true",
        ("allow_secondary_entries=true",),
    )
    grid_doc = {
        "arm": arm.id,
        "symbols": args.symbols,
        "workers": args.workers,
        "common": list(WPBR_COMMON),
        "arm_values": list(arm.values),
        "started": datetime.now().isoformat(timespec="seconds"),
    }
    (ROOT / "grid.json").write_text(json.dumps(grid_doc, indent=2), encoding="utf-8")
    print(f"[wpbr_allow_secondary] outdir={ROOT}", flush=True)
    print(f"[wpbr_allow_secondary] workers={args.workers} symbols={args.symbols}", flush=True)

    result = run_job(
        root=ROOT,
        prefix="WPBR",
        common_values=WPBR_COMMON,
        arm=arm,
        phase=args.phase,
        workers=args.workers,
        symbols=args.symbols,
        skip_existing=args.skip_existing,
    )
    m = result.get("metrics") or {}
    print(
        f"[markten:sec_on] ok={result['ok']} "
        f"trades={int(m.get('Total_Trades', 0) or 0)} "
        f"pnl={float(m.get('Total_PNL', 0) or 0):.0f} "
        f"pf={float(m.get('Profit_Factor', 0) or 0):.2f} "
        f"elapsed={result.get('elapsed_s', 0)}s",
        flush=True,
    )
    status = {
        "updated": datetime.now().isoformat(timespec="seconds"),
        "ok": result.get("ok"),
        "elapsed_s": result.get("elapsed_s"),
        "metrics": {k: m.get(k) for k in (
            "Total_Trades", "Total_PNL", "Profit_Factor", "Max_DD",
            "Profit_Per_Capital_Day", "Ann_ROR", "Expectancy", "Pct_Wins",
        )},
        "score": score(m) if result.get("ok") else None,
    }
    (ROOT / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    report = write_report(result)
    paste = write_paste(result)
    print(f"[write] {report}", flush=True)
    print(f"[write] {paste}", flush=True)
    print(paste.read_text(encoding="utf-8"), flush=True)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
