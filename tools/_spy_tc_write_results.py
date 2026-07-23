#!/usr/bin/env python3
"""Write universe_then_curated/RESULTS.md from pipeline + curated re-run outputs."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parents[1] / "drive" / "davey_experiments" / "spy_tc_strong_system" / "universe_then_curated"


def shard_maxpos() -> list[tuple[str, int, float]]:
    rows = []
    for i in range(20):
        d = BASE / "shards" / f"shard_{i:02d}"
        js = list(d.glob("*Summary*.json"))
        if js:
            m = json.loads(js[0].read_text(encoding="utf-8"))
            rows.append((f"shard_{i:02d}", int(m["Max_Positions"]), float(m["Notional_Per_Slot"])))
            continue
        closed = sorted(d.glob("*Closed*.csv"))[0]
        df = pd.read_csv(closed)
        df = df[df["PNL_PCT"].abs() > 1e-9]
        row = df.iloc[0]
        notional = float(row["PNL_DOLLARS"]) / (float(row["PNL_PCT"]) / 100.0)
        rows.append((f"shard_{i:02d}", int(round(1_000_000 / notional)), round(notional, 2)))
    return rows


def main() -> int:
    meta = json.loads((BASE / "pipeline_meta.json").read_text(encoding="utf-8"))
    rank = pd.read_csv(BASE / "per_symbol_rank.csv")
    curated = [s.strip() for s in (BASE / "CURATED_SYMBOLS.txt").read_text(encoding="utf-8").splitlines() if s.strip()]
    summary_path = sorted((BASE / "curated_rerun").glob("SPY_TC_STRONG_Summary_curated*.json"))[-1]
    cur = json.loads(summary_path.read_text(encoding="utf-8"))
    closed_path = Path(cur["closed_csv"])
    u = meta["universe"]
    maxpos_rows = shard_maxpos()
    mp_counts: dict[int, int] = {}
    for _, mp, _ in maxpos_rows:
        mp_counts[mp] = mp_counts.get(mp, 0) + 1

    top15 = rank.head(15)
    lines = [
        "# SPY+TC Strong — universe then curated",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "Settings: **target=1.25**, **stop=0.88**. Entry: SPY_COMPARE 1Y/2Y/3Y > 0 AND all IND_TC_*_OUTLOOK = Strong; buy next open.",
        "",
        "## Pipeline outputs",
        "",
        "| Artifact | Path |",
        "| --- | --- |",
        f"| Merged Closed | `UNIVERSE_Closed_merged.csv` ({u['trades']} trades, {u['symbols']} symbols; 767 cross-shard dupes dropped) |",
        f"| Per-symbol rank | `per_symbol_rank.csv` |",
        f"| Curated symbols | `CURATED_SYMBOLS.txt` ({len(curated)} names) |",
        f"| Selection notes | `SELECTION.md` |",
        f"| Curated re-run | `curated_rerun/` |",
        "",
        "## Ranking / curation rule",
        "",
        "- Per-symbol stats from deduped Closed rows (`PNL_PCT`-normalized to **$100k/slot** so shard MaxPos differences do not bias `$` metrics).",
        "- **quality_score = min(PF, 20) × √trades**, requiring **≥5 trades**.",
        "- Greedy: take best symbols in rank order until cumulative trades ≈ **1000** (band 900–1100) → **55 symbols / 1001 trades**.",
        "",
        "## Shard MaxPos caveat",
        "",
        f"Shard MaxPos was **not uniform**: {dict(sorted(mp_counts.items()))} "
        "(most shards used MaxPos=10 → $100k/slot; at least one used `len(shard)`). "
        "**Do not compare raw universe aggregate `$` across shards as a portfolio.** "
        "Ranking uses trade-level `PNL_PCT`; curated re-run uses one consistent MaxPos.",
        "",
        "## Universe vs curated (apples-to-apples note)",
        "",
        "| Metric | Universe (deduped, $ norm $100k) | Curated re-run (MaxPos=20, $50k/slot) |",
        "| --- | --- | --- |",
        f"| Symbols | {u['symbols']} | {len(curated)} |",
        f"| Trades | {u['trades']} | {cur['Total_Trades']} |",
        f"| Win rate % | {u['wr']} | {cur['Win_Rate_Pct']} |",
        f"| Profit factor | {u['pf']} | {cur['Profit_Factor']} |",
        f"| Total PNL ($) | {u['total_pnl_norm']:,.0f} *(norm)* | {cur['Total_PNL']:,.2f} |",
        f"| Expectancy ($) | {u['expectancy_norm']:,.2f} *(norm)* | {cur['Expectancy']:,.2f} |",
        f"| Max DD % | n/a (not portfolio-simmed) | {cur['Max_DD_Pct']} |",
        f"| Avg days held | — | {cur['Avg_Days_Held']} |",
        f"| Target / Stop / EOD | — | {cur['Target_Exits']} / {cur['Stop_Exits']} / {cur['EOD_Exits']} |",
        "",
        f"Curated re-run: **MaxPos = min(20, n_symbols) = 20** (55 symbols) → notional **$50,000**/slot. "
        f"Closed CSV: `{closed_path.name}`.",
        "",
        "## Curated symbols (rank order)",
        "",
        "```",
        " ".join(curated),
        "```",
        "",
        ", ".join(curated),
        "",
        "## Top 15 by quality_score",
        "",
        "| Rank | Symbol | Trades | WR% | PF | Total PNL (norm $) | Expectancy | Score |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for _, r in top15.iterrows():
        pf = r["pf"] if pd.notna(r["pf"]) else "inf"
        lines.append(
            f"| {int(r['rank'])} | {r['symbol']} | {int(r['trades'])} | {r['wr']} | "
            f"{pf} | {r['total_pnl']} | {r['expectancy']} | {r['quality_score']} |"
        )

    lines.extend(
        [
            "",
            "## Filter ideas (not implemented)",
            "",
            "1. **Min trade floor / avoid one-shot winners** — Drop names with `<10` trades even if PF is high "
            "(e.g. TRV 6/6, MCD/ETR at 5). Reduces small-sample bias in the curated basket.",
            "2. **Expectancy or total_pnl floor after PF×√n** — Require normalized expectancy ≳ $10k "
            "(or total_pnl ≳ $150k) so high-WR low-activity names do not crowd out compounders like NVDA/AVGO/FIX.",
            "3. **Sector / mega-cap concentration cap** — Cap mega-tech + ETF exposure (NVDA, AVGO, NFLX, ADBE, QQQ, …) "
            "to a fixed share of curated trades to leave room for quieter compounders (insurance, healthcare, industrials).",
            "",
            "## Caveats",
            "",
            "- Experiment-only; shard MaxPos differed — universe `$` aggregates are illustrative only.",
            "- Curated metrics above are from a single consistent re-run (MaxPos=20).",
            "- No slippage/commission; EOD liquidate if still open.",
            "",
        ]
    )
    out = BASE / "RESULTS.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out}")
    print(f"MaxPos counts: {mp_counts}")
    print(f"Curated: {len(curated)} symbols, {cur['Total_Trades']} trades, WR={cur['Win_Rate_Pct']}, PF={cur['Profit_Factor']}, PNL={cur['Total_PNL']}, MaxDD={cur['Max_DD_Pct']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
