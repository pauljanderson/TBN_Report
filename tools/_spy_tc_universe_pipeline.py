#!/usr/bin/env python3
"""Merge SPY+TC Strong universe shards → rank → curate ~1000 trades → write selection docs."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
BASE = REPO / "drive" / "davey_experiments" / "spy_tc_strong_system" / "universe_then_curated"
SHARDS = BASE / "shards"
NORM_NOTIONAL = 100_000.0  # normalize $ metrics to $100k/slot (MaxPos=10)
MIN_TRADES = 5
TARGET_CUM_TRADES = 1000
CUM_LO, CUM_HI = 900, 1100


def _shard_closed(shard_dir: Path) -> Path | None:
    hits = sorted(shard_dir.glob("*Closed*.csv"))
    return hits[0] if hits else None


def merge_closed() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for i in range(20):
        d = SHARDS / f"shard_{i:02d}"
        p = _shard_closed(d)
        if p is None:
            raise SystemExit(f"Missing Closed CSV in {d}")
        df = pd.read_csv(p)
        df["SHARD"] = f"shard_{i:02d}"
        frames.append(df)
        print(f"[MERGE] {d.name}: {len(df)} trades from {p.name}")
    out = pd.concat(frames, ignore_index=True)
    n_raw = len(out)
    # Some symbols appear in adjacent shards (overlap); drop exact trade dupes.
    dedupe_keys = [
        "SYMBOL",
        "DATE_SIGNAL",
        "DATE_OPENED",
        "DATE_CLOSED",
        "ENTRY_PRICE",
        "EXIT_PRICE",
        "EXIT_TYPE",
        "PNL_PCT",
    ]
    out = out.sort_values(["SYMBOL", "DATE_OPENED", "SHARD"]).drop_duplicates(
        subset=dedupe_keys, keep="first"
    )
    out_path = BASE / "UNIVERSE_Closed_merged.csv"
    out.to_csv(out_path, index=False)
    print(
        f"[MERGE] Wrote {out_path} ({len(out)} trades after dedupe, "
        f"dropped {n_raw - len(out)} dups; {out['SYMBOL'].nunique()} symbols)"
    )
    return out


def _pf(pnls: np.ndarray) -> float:
    wins = pnls[pnls > 0].sum()
    losses = pnls[pnls < 0].sum()
    if losses == 0:
        return float("inf") if wins > 0 else 0.0
    return float(wins / abs(losses))


def per_symbol_rank(merged: pd.DataFrame) -> pd.DataFrame:
    """Rank by quality_score = PF * sqrt(trades), min_trades floor.

    Dollar columns are normalized to NORM_NOTIONAL via PNL_PCT so shards with
    different MaxPos/notional remain comparable. Raw PNL_DOLLARS sum is kept
    as total_pnl_raw_shard_notional for audit only.
    """
    rows = []
    for sym, g in merged.groupby("SYMBOL", sort=True):
        pct = g["PNL_PCT"].astype(float).to_numpy()
        # PNL_PCT is stored as percent points (25.0 = +25%)
        pnl_norm = pct / 100.0 * NORM_NOTIONAL
        n = len(g)
        wins = int((pct > 0).sum())
        wr = 100.0 * wins / n if n else 0.0
        pf = _pf(pnl_norm)
        total = float(pnl_norm.sum())
        exp = float(pnl_norm.mean()) if n else 0.0
        # Cap PF for scoring so 100%-WR names don't dominate via inf PF.
        pf_for_score = min(pf, 20.0) if np.isfinite(pf) else 20.0
        score = pf_for_score * np.sqrt(n) if n >= MIN_TRADES else -1e9
        rows.append(
            {
                "symbol": sym,
                "trades": n,
                "wr": round(wr, 2),
                "pf": round(pf, 4) if np.isfinite(pf) else None,
                "total_pnl": round(total, 2),
                "expectancy": round(exp, 2),
                "quality_score": round(float(score), 4) if score > -1e8 else None,
                "total_pnl_raw_shard_notional": round(float(g["PNL_DOLLARS"].sum()), 2),
                "shards": ",".join(sorted(g["SHARD"].unique())),
            }
        )
    rank = pd.DataFrame(rows)
    rank = rank.sort_values(
        by=["quality_score", "total_pnl", "trades"],
        ascending=[False, False, False],
        na_position="last",
    ).reset_index(drop=True)
    rank.insert(0, "rank", np.arange(1, len(rank) + 1))
    out_path = BASE / "per_symbol_rank.csv"
    rank.to_csv(out_path, index=False)
    print(f"[RANK] Wrote {out_path} ({len(rank)} symbols); rule=min(PF,20)*sqrt(trades), min_trades={MIN_TRADES}, $ norm=${NORM_NOTIONAL:,.0f}/slot via PNL_PCT")
    return rank


def curate(rank: pd.DataFrame) -> tuple[list[str], pd.DataFrame]:
    eligible = rank[rank["trades"] >= MIN_TRADES].copy()
    chosen: list[str] = []
    cum = 0
    selected_rows = []
    for _, row in eligible.iterrows():
        if cum >= TARGET_CUM_TRADES and CUM_LO <= cum <= CUM_HI:
            break
        if cum >= CUM_HI:
            break
        # If adding would overshoot hard, stop unless still below LO
        nxt = cum + int(row["trades"])
        if cum >= CUM_LO and nxt > CUM_HI:
            break
        chosen.append(str(row["symbol"]))
        cum = nxt
        selected_rows.append(row)
        if CUM_LO <= cum <= CUM_HI and cum >= TARGET_CUM_TRADES:
            break
    # If still under LO, keep adding
    if cum < CUM_LO:
        for _, row in eligible.iterrows():
            if str(row["symbol"]) in chosen:
                continue
            chosen.append(str(row["symbol"]))
            cum += int(row["trades"])
            selected_rows.append(row)
            if cum >= CUM_LO:
                break

    sel = pd.DataFrame(selected_rows)
    sym_path = BASE / "CURATED_SYMBOLS.txt"
    sym_path.write_text("\n".join(chosen) + "\n", encoding="utf-8")

    lines = [
        "# Curated symbol selection — SPY+TC Strong universe",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Ranking rule",
        "",
        f"- Per-symbol stats from merged Closed rows across all 20 shards "
        f"(exact trade duplicates from overlapping shard memberships removed).",
        f"- Dollar metrics **normalized** to ${NORM_NOTIONAL:,.0f}/slot via `PNL_PCT` "
        f"(shards used different MaxPos/notional; raw `$` is not comparable).",
        f"- `quality_score = min(PF, 20) * sqrt(trades)` with `min_trades >= {MIN_TRADES}` "
        f"(PF capped so 100% win-rate names do not dominate).",
        f"- Symbols with fewer than {MIN_TRADES} trades get score = null and are skipped.",
        f"- Tie-break: higher normalized `total_pnl`, then more trades.",
        "",
        "## Greedy curation",
        "",
        f"- Walk rank order; accumulate trades until cumulative ≈ {TARGET_CUM_TRADES} "
        f"(accept band {CUM_LO}–{CUM_HI}).",
        f"- Selected **{len(chosen)}** symbols, **{cum}** universe-shard trades "
        f"(per-symbol trade counts from shard runs; re-run will recompute under one MaxPos).",
        "",
        "## Selected symbols (rank order)",
        "",
        "| Rank | Symbol | Trades | WR% | PF | Total PNL (norm $) | Expectancy | Score |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for _, r in sel.iterrows():
        lines.append(
            f"| {int(r['rank'])} | {r['symbol']} | {int(r['trades'])} | {r['wr']} | "
            f"{r['pf']} | {r['total_pnl']} | {r['expectancy']} | {r['quality_score']} |"
        )
    lines.extend(
        [
            "",
            f"- `CURATED_SYMBOLS.txt`: {sym_path}",
            f"- `per_symbol_rank.csv`: {BASE / 'per_symbol_rank.csv'}",
            "",
        ]
    )
    sel_md = BASE / "SELECTION.md"
    sel_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"[CURATE] {len(chosen)} symbols, {cum} trades -> {sym_path}")
    print(f"[CURATE] Wrote {sel_md}")
    return chosen, sel


def universe_headline(merged: pd.DataFrame, rank: pd.DataFrame) -> dict:
    pct = merged["PNL_PCT"].astype(float).to_numpy()
    pnl_norm = pct / 100.0 * NORM_NOTIONAL
    n = len(merged)
    wins = int((pct > 0).sum())
    return {
        "symbols": int(merged["SYMBOL"].nunique()),
        "trades": n,
        "wr": round(100.0 * wins / n, 2) if n else 0.0,
        "pf": round(_pf(pnl_norm), 4),
        "total_pnl_norm": round(float(pnl_norm.sum()), 2),
        "expectancy_norm": round(float(pnl_norm.mean()), 2) if n else 0.0,
        "note": (
            "Universe $ totals use PNL_PCT-normalized $100k/slot; "
            "shard MaxPos differed so raw PNL_DOLLARS sum is not portfolio-comparable."
        ),
        "rankable_symbols": int((rank["trades"] >= MIN_TRADES).sum()),
    }


def main() -> int:
    BASE.mkdir(parents=True, exist_ok=True)
    merged = merge_closed()
    rank = per_symbol_rank(merged)
    chosen, sel = curate(rank)
    headline = universe_headline(merged, rank)
    meta = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "ranking_rule": f"min(PF,20) * sqrt(trades), min_trades>={MIN_TRADES}, $ via PNL_PCT*{NORM_NOTIONAL}, deduped overlaps",
        "curated_symbols": chosen,
        "curated_n_symbols": len(chosen),
        "curated_universe_trades": int(sel["trades"].sum()) if len(sel) else 0,
        "universe": headline,
        "max_positions_for_rerun": min(20, len(chosen)),
    }
    meta_path = BASE / "pipeline_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2))
    print(f"[META] Wrote {meta_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
