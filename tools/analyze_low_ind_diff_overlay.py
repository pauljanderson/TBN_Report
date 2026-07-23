#!/usr/bin/env python3
"""Low / negative IND_DIFF overlay gates for BRT/RL/MTS/WPBR/YH (screening).

Tests *upper-bound* DIFF gates (DIFF <= T) and inverse-rank / inverse-weight
heuristics on closed trades with trigger-aligned IND_DIFF.

Evidence class: post-hoc trade screening (not a portfolio capital backtest).
Does not modify production run_*.bat settings.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
_TOOLS = _REPO / "tools"
_SA = _REPO / "stock_analysis"
for p in (_REPO, _SA, _TOOLS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from analyze_ind_diff_at_trigger_pnl import (  # noqa: E402
    _fmt_num,
    _load_brt_like,
    _load_rl,
    _trade_stats,
    enrich_with_cache,
    spearman,
)

UPPER_GATES = [0, 3, 6, 10]
SYSTEMS = ["BRT", "RL", "MTS", "WPBR", "YH"]


def _approx_max_dd_pct(df: pd.DataFrame) -> float:
    """Chronological cumulative $ PnL peak-to-trough as % of peak equity proxy.

    Screening approximation only: equal-notional chronological stack, not margin/equity.
    """
    if df.empty or "pnl_dollars" not in df.columns:
        return float("nan")
    work = df.dropna(subset=["pnl_dollars"]).copy()
    if work.empty:
        return float("nan")
    if "entry" in work.columns:
        work = work.sort_values(["entry", "symbol"])
    eq = work["pnl_dollars"].astype(float).cumsum()
    peak = eq.cummax()
    # Use peak+seed so early negative path is defined
    seed = float(np.nanmax(np.abs(work["pnl_dollars"].to_numpy()))) or 1.0
    base = peak.replace(0, np.nan).fillna(seed)
    dd = (eq - peak) / base.replace(0, np.nan)
    return float((-dd.min()) * 100.0) if len(dd) else float("nan")


def _gate_row(base: pd.DataFrame, sub: pd.DataFrame, gate: str) -> dict[str, Any]:
    st0 = _trade_stats(base)
    st = _trade_stats(sub)
    n0 = max(1, int(st0["n"]))
    return {
        "gate": gate,
        "n": st["n"],
        "retained_pct": 100.0 * st["n"] / n0,
        "win_rate": st["win_rate"],
        "avg_pnl_pct": st["avg_pnl_pct"],
        "median_pnl_pct": st["median_pnl_pct"],
        "total_pnl_pct": st["total_pnl_pct"],
        "total_pnl_dollars": st["total_pnl_dollars"],
        "profit_factor": st["profit_factor"],
        "expectancy_pct": st["expectancy_pct"],
        "avg_days": st["avg_days"],
        "top_symbol_share": st["top_symbol_share"],
        "n_symbols": st["n_symbols"],
        "top_symbol": st["top_symbol"],
        "approx_max_dd_pct": _approx_max_dd_pct(sub),
        "avg_lift_pp": (
            st["avg_pnl_pct"] - st0["avg_pnl_pct"]
            if np.isfinite(st["avg_pnl_pct"]) and np.isfinite(st0["avg_pnl_pct"])
            else np.nan
        ),
        "pf_lift": (
            st["profit_factor"] - st0["profit_factor"]
            if np.isfinite(st["profit_factor"]) and np.isfinite(st0["profit_factor"])
            else np.nan
        ),
        "baseline_n": st0["n"],
        "baseline_avg_pnl_pct": st0["avg_pnl_pct"],
        "baseline_pf": st0["profit_factor"],
    }


def upper_bound_gates(df: pd.DataFrame) -> pd.DataFrame:
    base = df.dropna(subset=["ind_diff", "pnl_pct"]).copy()
    rows = [_gate_row(base, base, "all (baseline)")]
    for t in UPPER_GATES:
        sub = base[base["ind_diff"] <= t]
        rows.append(_gate_row(base, sub, f"DIFF<={t}"))
    return pd.DataFrame(rows)


def inverse_weight_sim(df: pd.DataFrame) -> pd.DataFrame:
    """Compare equal-weight vs inverse-DIFF size weights (screening, not capital BT)."""
    base = df.dropna(subset=["ind_diff", "pnl_pct"]).copy()
    if base.empty:
        return pd.DataFrame()
    # Weight = 1 / (1 + max(DIFF, 0)); negative DIFF gets weight 1.0
    w = 1.0 / (1.0 + np.maximum(base["ind_diff"].astype(float).to_numpy(), 0.0))
    w = w / w.mean()  # normalize mean weight = 1
    pnl = base["pnl_pct"].astype(float).to_numpy()
    eq_avg = float(np.mean(pnl))
    w_avg = float(np.average(pnl, weights=w))
    # Rank within calendar day: lower DIFF = better rank (1=best)
    base = base.copy()
    base["_w"] = w
    base["day_rank"] = base.groupby("entry")["ind_diff"].rank(method="average", ascending=True)
    day_n = base.groupby("entry")["ind_diff"].transform("count")
    # Keep top half of each day by low DIFF (ties included via rank <= n/2)
    keep_half = base[base["day_rank"] <= (day_n + 1) / 2.0]
    # Keep best (lowest DIFF) per day when day has >=2 trades
    best = base.loc[base.groupby("entry")["ind_diff"].idxmin()]
    rows = [
        {
            "scheme": "equal_weight (baseline)",
            "n": len(base),
            "avg_pnl_pct": eq_avg,
            "weighted_avg_pnl_pct": eq_avg,
            "lift_pp": 0.0,
            "note": "screening equal weight",
        },
        {
            "scheme": "inverse_diff_weight",
            "n": len(base),
            "avg_pnl_pct": eq_avg,
            "weighted_avg_pnl_pct": w_avg,
            "lift_pp": w_avg - eq_avg,
            "note": "w=1/(1+max(DIFF,0)); same trade set, reweighted avg",
        },
        {
            "scheme": "same_day_keep_lower_half_diff",
            "n": len(keep_half),
            "avg_pnl_pct": float(keep_half["pnl_pct"].mean()) if len(keep_half) else np.nan,
            "weighted_avg_pnl_pct": float(keep_half["pnl_pct"].mean()) if len(keep_half) else np.nan,
            "lift_pp": (
                float(keep_half["pnl_pct"].mean()) - eq_avg if len(keep_half) else np.nan
            ),
            "note": "among same-day candidates, keep lower-DIFF half",
        },
        {
            "scheme": "same_day_keep_lowest_diff",
            "n": len(best),
            "avg_pnl_pct": float(best["pnl_pct"].mean()) if len(best) else np.nan,
            "weighted_avg_pnl_pct": float(best["pnl_pct"].mean()) if len(best) else np.nan,
            "lift_pp": float(best["pnl_pct"].mean()) - eq_avg if len(best) else np.nan,
            "note": "among same-day candidates, keep single lowest DIFF",
        },
    ]
    return pd.DataFrame(rows)


def _recommend(sysname: str, gates: pd.DataFrame, inv: pd.DataFrame) -> str:
    base = gates[gates["gate"].str.startswith("all")].iloc[0]
    cands = []
    for _, g in gates.iterrows():
        if str(g["gate"]).startswith("all"):
            continue
        if g["n"] < max(30, 0.15 * base["n"]):
            continue
        # Prefer lift in avg AND not collapsing PF badly
        score = float(g["avg_lift_pp"] or 0) + 0.5 * float(g["pf_lift"] or 0)
        if g["avg_lift_pp"] > 0.5 and (g["pf_lift"] is None or g["pf_lift"] > -0.15):
            cands.append((score, g))
    inv_note = ""
    if inv is not None and len(inv):
        iw = inv[inv["scheme"] == "inverse_diff_weight"]
        if len(iw) and float(iw.iloc[0]["lift_pp"]) > 0.3:
            inv_note = (
                f"; inverse-weight lift +{float(iw.iloc[0]['lift_pp']):.2f} pp "
                "(reweighting only)"
            )
    if not cands:
        return (
            f"**{sysname}**: no upper-bound DIFF gate clears +0.5 pp avg lift "
            f"with >=15% retention{inv_note}. Screening only — not worth a dedicated "
            "prospective BT unless packaged with other filters."
        )
    cands.sort(key=lambda x: -x[0])
    best = cands[0][1]
    strength = "modest" if best["avg_lift_pp"] < 1.5 else "material"
    return (
        f"**{sysname}**: best screening gate `{best['gate']}` "
        f"(n={int(best['n'])}, retain {best['retained_pct']:.0f}%, "
        f"avg {best['avg_pnl_pct']:.2f}% vs {base['avg_pnl_pct']:.2f}%, "
        f"PF {best['profit_factor']:.2f} vs {base['baseline_pf']:.2f}) — "
        f"{strength} post-hoc lift{inv_note}. "
        "Worth a **true prospective backtest** only if same-day ranking is implementable."
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--drive", type=Path, default=_REPO / "drive")
    ap.add_argument(
        "--cache-dir",
        type=Path,
        default=_REPO / "data" / "newdata" / "data" / ".brt_indicator_cache",
    )
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--out-prefix", type=str, default="Low_IND_Diff_Overlay_PnL")
    ap.add_argument(
        "--enriched",
        type=Path,
        default=None,
        help="Optional prebuilt enriched trades CSV (from analyze_ind_diff_at_trigger_pnl)",
    )
    args = ap.parse_args()
    drive: Path = args.drive
    prefix = args.out_prefix

    enriched_path = args.enriched or (drive / "IND_Diff_At_Trigger_PnL_Trades_Enriched.csv")
    if enriched_path.is_file():
        print(f"[load] enriched {enriched_path}")
        enriched = pd.read_csv(enriched_path, low_memory=False)
    else:
        files = {
            "BRT": drive / "BRT_LatestRun_Closed.csv",
            "RL": drive / "RL_LatestRun_Closed.csv",
            "MTS": drive / "MTS_LatestRun_Closed.csv",
            "WPBR": drive / "WPBR_LatestRun_Closed.csv",
            "YH": drive / "YH_LatestRun_Closed.csv",
        }
        frames = []
        for s, path in files.items():
            if not path.exists():
                print(f"[skip] missing {path}")
                continue
            frames.append(_load_rl(path) if s == "RL" else _load_brt_like(path, s))
        trades = pd.concat(frames, ignore_index=True)
        print(f"[enrich] {len(trades)} trades workers={args.workers}")
        enriched = enrich_with_cache(trades, args.cache_dir, workers=int(args.workers))
        out_en = drive / f"{prefix}_Trades_Enriched.csv"
        enriched.to_csv(out_en, index=False)
        print(f"[write] {out_en}")

    # Long only
    enriched = enriched.copy()
    if "side" in enriched.columns:
        enriched = enriched[enriched["side"].astype(str).str.upper() != "SHORT"]

    gate_parts = []
    inv_parts = []
    recs = []
    results: dict[str, Any] = {}

    for s in SYSTEMS + ["POOLED"]:
        if s == "POOLED":
            df = enriched[enriched["system"].isin(SYSTEMS)]
            label = "POOLED"
        else:
            if s not in set(enriched["system"].astype(str)):
                continue
            df = enriched[enriched["system"] == s]
            label = s
        valid = df.dropna(subset=["ind_diff", "pnl_pct"])
        sp, nsp = spearman(valid, "ind_diff")
        gates = upper_bound_gates(valid)
        inv = inverse_weight_sim(valid)
        gates.insert(0, "system", label)
        inv.insert(0, "system", label)
        gate_parts.append(gates)
        inv_parts.append(inv)
        rec = _recommend(label, gates, inv)
        recs.append(rec)
        results[label] = {
            "spearman": sp,
            "n": len(valid),
            "gates": gates,
            "inv": inv,
            "rec": rec,
        }
        print(f"[analyze] {label}: n={len(valid)} spearman={sp:.4f}")

    gates_csv = drive / f"{prefix}_Gates.csv"
    inv_csv = drive / f"{prefix}_InverseRank.csv"
    pd.concat(gate_parts, ignore_index=True).to_csv(gates_csv, index=False)
    pd.concat(inv_parts, ignore_index=True).to_csv(inv_csv, index=False)

    md_path = drive / f"{prefix}_By_System.md"
    lines = [
        "# Low / Negative IND_DIFF Overlay vs Closed-Trade PnL",
        "",
        "## Evidence class (read first)",
        "",
        "This is **post-hoc screening** on already-taken closed trades with "
        "trigger-aligned `IND_DIFF`. It is **not** a portfolio capital backtest "
        "(no position caps, no same-day capital contention, no PPCD/Ann ROR from "
        "a live equity curve). Approximate Max DD is a chronological $ stack only.",
        "",
        "Implementable next step (if warranted): same-day **rank/filter among "
        "candidates before entry**, then a true system backtest.",
        "",
        "## Question",
        "",
        "Prior pooled bucket `DIFF<=0` looked strong (avg ~7.6%, PF ~2.76). "
        "Does an **upper-bound** low-DIFF gate or inverse-DIFF ranker help "
        "**per system**, or was that system-mix confounding?",
        "",
        "## Method",
        "",
        f"- Closed trades: BRT/RL/MTS/WPBR/YH LatestRun under `{drive}`.",
        "- Trigger IND_DIFF from prior analysis enrich / indicator cache.",
        f"- Upper-bound gates: DIFF <= {', '.join(str(x) for x in UPPER_GATES)}.",
        "- Inverse schemes: continuous inverse weight; same-day keep lower-DIFF half; "
        "same-day keep lowest DIFF.",
        f"- Workers used for enrich (if rebuilt): {args.workers}.",
        "",
        "## Verdict (executive)",
        "",
    ]
    for r in recs:
        lines.append(f"- {r}")
    lines.append("")

    # Cross-system gate summary table for DIFF<=0 and DIFF<=6
    lines.extend(
        [
            "## Cross-system upper-bound gate summary",
            "",
            "| System | N all | Avg all | PF all | Gate | N | Retain% | Avg | PF | Lift pp | Approx DD% | TopSym% |",
            "|--------|------:|--------:|-------:|------|--:|--------:|----:|---:|--------:|-----------:|--------:|",
        ]
    )
    for s, r in results.items():
        g = r["gates"]
        base = g[g["gate"].str.startswith("all")].iloc[0]
        for gate_name in ["DIFF<=0", "DIFF<=3", "DIFF<=6", "DIFF<=10"]:
            sub = g[g["gate"] == gate_name]
            if sub.empty:
                continue
            row = sub.iloc[0]
            pf = row["profit_factor"]
            pf_s = "inf" if pf == np.inf else _fmt_num(pf)
            bpf = base["profit_factor"]
            bpf_s = "inf" if bpf == np.inf else _fmt_num(bpf)
            lines.append(
                f"| {s} | {int(base['n'])} | {_fmt_num(base['avg_pnl_pct'])} | {bpf_s} | "
                f"{gate_name} | {int(row['n'])} | {_fmt_num(row['retained_pct'], 1)} | "
                f"{_fmt_num(row['avg_pnl_pct'])} | {pf_s} | {_fmt_num(row['avg_lift_pp'])} | "
                f"{_fmt_num(row['approx_max_dd_pct'], 1)} | "
                f"{_fmt_num(100 * row['top_symbol_share'], 1)} |"
            )
    lines.append("")

    lines.extend(["## Inverse rank / weight (screening)", ""])
    for s, r in results.items():
        inv = r["inv"]
        lines.append(f"### {s}")
        lines.append("")
        lines.append("| Scheme | N | Eq/Avg PnL% | Weighted avg% | Lift pp | Note |")
        lines.append("|--------|--:|------------:|--------------:|--------:|------|")
        for _, row in inv.iterrows():
            lines.append(
                f"| {row['scheme']} | {int(row['n'])} | {_fmt_num(row['avg_pnl_pct'])} | "
                f"{_fmt_num(row['weighted_avg_pnl_pct'])} | {_fmt_num(row['lift_pp'])} | "
                f"{row['note']} |"
            )
        lines.append("")

    lines.extend(
        [
            "## Per-system full gate tables",
            "",
        ]
    )
    for s, r in results.items():
        g = r["gates"]
        lines.append(f"### {s} (Spearman DIFF vs PnL = {_fmt_num(r['spearman'], 3)}, n={r['n']})")
        lines.append("")
        lines.append(
            "| Gate | N | Retain% | Win% | Avg% | Med% | Total $ | PF | ApproxDD% | TopSym% | Lift pp |"
        )
        lines.append(
            "|------|--:|--------:|-----:|-----:|-----:|--------:|---:|----------:|--------:|--------:|"
        )
        for _, row in g.iterrows():
            wr = row["win_rate"]
            wr_s = f"{100 * wr:.1f}%" if np.isfinite(wr) else "—"
            pf = row["profit_factor"]
            pf_s = "inf" if pf == np.inf else _fmt_num(pf)
            lines.append(
                f"| {row['gate']} | {int(row['n'])} | {_fmt_num(row['retained_pct'], 1)} | "
                f"{wr_s} | {_fmt_num(row['avg_pnl_pct'])} | {_fmt_num(row['median_pnl_pct'])} | "
                f"{_fmt_num(row['total_pnl_dollars'], 0)} | {pf_s} | "
                f"{_fmt_num(row['approx_max_dd_pct'], 1)} | "
                f"{_fmt_num(100 * row['top_symbol_share'], 1)} | {_fmt_num(row['avg_lift_pp'])} |"
            )
        lines.append("")

    # Prospective BT recommendation
    lines.extend(
        [
            "## Prospective backtest recommendation",
            "",
        ]
    )
    worth = []
    for s, r in results.items():
        if s == "POOLED":
            continue
        g = r["gates"]
        base = g[g["gate"].str.startswith("all")].iloc[0]
        best = None
        for _, row in g.iterrows():
            if str(row["gate"]).startswith("all"):
                continue
            if row["n"] < max(40, 0.2 * base["n"]):
                continue
            if row["avg_lift_pp"] > 1.0 and row["pf_lift"] > -0.1:
                if best is None or row["avg_lift_pp"] > best["avg_lift_pp"]:
                    best = row
        if best is not None:
            worth.append((s, best))
    if worth:
        lines.append(
            "Systems with **screening** lift large enough to justify a true "
            "same-day rank/filter backtest:"
        )
        lines.append("")
        for s, best in worth:
            lines.append(
                f"- **{s}**: try `{best['gate']}` as a soft pre-entry filter "
                f"(or inverse-DIFF rank among same-day candidates)."
            )
    else:
        lines.append(
            "No system shows a large, well-retained upper-bound DIFF lift that clearly "
            "justifies a dedicated prospective backtest on its own. Prefer system-native "
            "scores; treat low-DIFF as a weak secondary only if paired with other gates."
        )
    lines.extend(
        [
            "",
            "## Outputs",
            "",
            f"- `{md_path.name}`",
            f"- `{gates_csv.name}`",
            f"- `{inv_csv.name}`",
            "",
            f"Rerun: `python tools/analyze_low_ind_diff_overlay.py --workers {args.workers}`",
            "",
        ]
    )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[write] {md_path}")
    print(f"[write] {gates_csv}")
    print(f"[write] {inv_csv}")
    print("[done]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
