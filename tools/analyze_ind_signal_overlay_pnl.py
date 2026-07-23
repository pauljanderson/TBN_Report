#!/usr/bin/env python3
"""IND indicator signal overlays vs closed-trade PnL on BRT/RL/MTS/WPBR/YH.

Reconstructs all IND states at the trigger bar (session before entry) for each
closed trade, then measures per-signal and pair association with trade PnL.

Also runs a secondary ticker-specific analysis with minimum-n and early/late
consistency filters.

Evidence: post-hoc screening on taken trades (not portfolio BT).
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from itertools import combinations
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

from brt_entry_indicators import (  # noqa: E402
    INDICATOR_IDS,
    _ensure_gate_arrays,
    _load_disk_cache_payload,
    aligned_bull_bear_diff,
    ind_score_at_bar,
)
from analyze_ind_diff_at_trigger_pnl import (  # noqa: E402
    _fmt_num,
    _load_brt_like,
    _load_rl,
    _trade_stats,
    spearman,
)

SYSTEMS = ["BRT", "RL", "MTS", "WPBR", "YH"]
MIN_N_SIGNAL = 40
MIN_N_PAIR = 25
MIN_N_TICKER = 12
MIN_N_HALF = 5
FOCUS_SIGNALS = ("ATR_RATIO", "VOL_SURGE", "DIAMOND", "DIAMOND_BOTTOM", "UPSIDE_BREAKOUT")


def _state_label(v: int) -> str:
    if v > 0:
        return "BULL"
    if v < 0:
        return "BEAR"
    return "NEUTRAL"


def _worker_states(args: tuple) -> list[dict[str, Any]]:
    symbol, cache_dir_s, requests = args
    cache_dir = Path(cache_dir_s)
    out: list[dict[str, Any]] = []
    try:
        payload = _load_disk_cache_payload(cache_dir, symbol)
        if not payload or "pre" not in payload:
            for req in requests:
                out.append({**req, "ok": False})
            return out
        pre = _ensure_gate_arrays(payload["pre"])
        dates = np.asarray(pre.dates, dtype=np.int64)
        date_to_i = {int(d): i for i, d in enumerate(dates)}
        for req in requests:
            entry = int(req["entry"])
            side = str(req.get("side") or "LONG")
            ei = date_to_i.get(entry)
            if ei is None or ei < 1:
                out.append({**req, "ok": False})
                continue
            ti = ei - 1
            row: dict[str, Any] = {
                **req,
                "ok": True,
                "trigger_ymd": int(dates[ti]),
                "ind_diff": float(aligned_bull_bear_diff(pre, ti, side) or np.nan),
                "ind_score": float(ind_score_at_bar(pre, ti) or np.nan),
            }
            for iid in INDICATOR_IDS:
                arr = pre.states.get(iid)
                st = int(arr[ti]) if arr is not None and ti < len(arr) else 0
                row[f"st_{iid}"] = st
                row[f"lab_{iid}"] = _state_label(st)
            out.append(row)
    except Exception as exc:  # noqa: BLE001
        for req in requests:
            out.append({**req, "ok": False, "err": str(exc)[:120]})
    return out


def enrich_states(
    trades: pd.DataFrame,
    cache_dir: Path,
    *,
    workers: int = 10,
) -> pd.DataFrame:
    need = trades.copy()
    need["_row"] = np.arange(len(need))
    groups: dict[str, list[dict[str, Any]]] = {}
    for _, r in need.iterrows():
        sym = str(r["symbol"]).upper()
        groups.setdefault(sym, []).append(
            {"_row": int(r["_row"]), "entry": int(r["entry"]), "side": str(r["side"])}
        )
    jobs = [(sym, str(cache_dir), reqs) for sym, reqs in groups.items()]
    results: list[dict[str, Any]] = []
    w = max(1, int(workers))
    if w == 1 or len(jobs) < 2:
        for job in jobs:
            results.extend(_worker_states(job))
    else:
        with ProcessPoolExecutor(max_workers=w) as ex:
            futs = {ex.submit(_worker_states, job): job[0] for job in jobs}
            for fut in as_completed(futs):
                results.extend(fut.result())

    rdf = pd.DataFrame(results)
    if rdf.empty:
        return need
    # Merge state columns onto need by _row
    rdf = rdf.set_index("_row")
    for col in rdf.columns:
        if col in ("entry", "side"):
            continue
        need.loc[rdf.index, col] = rdf[col]
    return need


def _pf(pnl: pd.Series) -> float:
    wins = pnl[pnl > 0].sum()
    losses = (-pnl[pnl < 0]).sum()
    if losses > 0:
        return float(wins / losses)
    return float("inf") if wins > 0 else float("nan")


def signal_table(df: pd.DataFrame, system: str) -> pd.DataFrame:
    base = df.dropna(subset=["pnl_pct"]).copy()
    base_avg = float(base["pnl_pct"].mean())
    base_med = float(base["pnl_pct"].median())
    base_pf = _pf(base["pnl_pct"])
    base_wr = float((base["pnl_pct"] > 0).mean())
    rows = []
    for iid in INDICATOR_IDS:
        col = f"lab_{iid}"
        if col not in base.columns:
            continue
        for lab in ("BULL", "BEAR", "NEUTRAL"):
            sub = base[base[col] == lab]
            n = len(sub)
            if n == 0:
                continue
            avg = float(sub["pnl_pct"].mean())
            med = float(sub["pnl_pct"].median())
            rows.append(
                {
                    "system": system,
                    "indicator": iid,
                    "state": lab,
                    "n": n,
                    "coverage_pct": 100.0 * n / max(1, len(base)),
                    "avg_pnl_pct": avg,
                    "median_pnl_pct": med,
                    "lift_avg_pp": avg - base_avg,
                    "lift_med_pp": med - base_med,
                    "win_rate": float((sub["pnl_pct"] > 0).mean()),
                    "win_lift_pp": 100.0 * (float((sub["pnl_pct"] > 0).mean()) - base_wr),
                    "profit_factor": _pf(sub["pnl_pct"]),
                    "total_pnl_pct": float(sub["pnl_pct"].sum()),
                    "total_pnl_dollars": float(
                        pd.to_numeric(sub.get("pnl_dollars"), errors="coerce").sum()
                    ),
                    "baseline_avg": base_avg,
                    "baseline_pf": base_pf,
                    "baseline_n": len(base),
                }
            )
    return pd.DataFrame(rows)


def pair_table(df: pd.DataFrame, system: str, focus: tuple[str, ...] | None = None) -> pd.DataFrame:
    base = df.dropna(subset=["pnl_pct"]).copy()
    base_avg = float(base["pnl_pct"].mean())
    ids = list(focus) if focus else list(INDICATOR_IDS)
    # Prefer focus pairs; also include all focus×focus
    pairs = list(combinations(ids, 2))
    rows = []
    for a, b in pairs:
        ca, cb = f"lab_{a}", f"lab_{b}"
        if ca not in base.columns or cb not in base.columns:
            continue
        for sa, sb in (("BULL", "BULL"), ("BEAR", "BEAR"), ("BULL", "BEAR")):
            sub = base[(base[ca] == sa) & (base[cb] == sb)]
            n = len(sub)
            if n < MIN_N_PAIR:
                continue
            avg = float(sub["pnl_pct"].mean())
            rows.append(
                {
                    "system": system,
                    "ind_a": a,
                    "ind_b": b,
                    "state_a": sa,
                    "state_b": sb,
                    "n": n,
                    "avg_pnl_pct": avg,
                    "lift_avg_pp": avg - base_avg,
                    "win_rate": float((sub["pnl_pct"] > 0).mean()),
                    "profit_factor": _pf(sub["pnl_pct"]),
                    "total_pnl_dollars": float(
                        pd.to_numeric(sub.get("pnl_dollars"), errors="coerce").sum()
                    ),
                }
            )
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values("lift_avg_pp", ascending=False)
    return out


def ticker_effects(df: pd.DataFrame, system: str) -> pd.DataFrame:
    """Per-symbol: BULL lift for focus signals + DIFF Spearman, with early/late check."""
    base = df.dropna(subset=["pnl_pct", "entry"]).copy()
    rows = []
    for sym, g in base.groupby("symbol"):
        if len(g) < MIN_N_TICKER:
            continue
        g = g.sort_values("entry")
        mid = len(g) // 2
        early, late = g.iloc[:mid], g.iloc[mid:]
        sp, nsp = spearman(g, "ind_diff") if "ind_diff" in g.columns else (np.nan, 0)
        row: dict[str, Any] = {
            "system": system,
            "symbol": sym,
            "n": len(g),
            "avg_pnl_pct": float(g["pnl_pct"].mean()),
            "spearman_diff": sp,
            "spearman_n": nsp,
        }
        credible = 0
        for iid in FOCUS_SIGNALS:
            col = f"lab_{iid}"
            if col not in g.columns:
                continue
            bull = g[g[col] == "BULL"]
            other = g[g[col] != "BULL"]
            if len(bull) < MIN_N_HALF or len(other) < MIN_N_HALF:
                row[f"{iid}_bull_n"] = len(bull)
                row[f"{iid}_lift"] = np.nan
                row[f"{iid}_consistent"] = False
                continue
            lift = float(bull["pnl_pct"].mean() - other["pnl_pct"].mean())
            e_bull = early[early[col] == "BULL"]
            l_bull = late[late[col] == "BULL"]
            e_other = early[early[col] != "BULL"]
            l_other = late[late[col] != "BULL"]
            cons = False
            if (
                len(e_bull) >= 2
                and len(l_bull) >= 2
                and len(e_other) >= 2
                and len(l_other) >= 2
            ):
                e_lift = float(e_bull["pnl_pct"].mean() - e_other["pnl_pct"].mean())
                l_lift = float(l_bull["pnl_pct"].mean() - l_other["pnl_pct"].mean())
                cons = (e_lift > 0 and l_lift > 0) or (e_lift < 0 and l_lift < 0)
            row[f"{iid}_bull_n"] = len(bull)
            row[f"{iid}_lift"] = lift
            row[f"{iid}_consistent"] = cons
            if cons and abs(lift) >= 2.0:
                credible += 1
        row["credible_signal_count"] = credible
        rows.append(row)
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values("credible_signal_count", ascending=False)
    return out


def _top_bottom(sig: pd.DataFrame, system: str, state: str = "BULL", k: int = 8) -> tuple[pd.DataFrame, pd.DataFrame]:
    sub = sig[(sig["system"] == system) & (sig["state"] == state) & (sig["n"] >= MIN_N_SIGNAL)].copy()
    if sub.empty:
        return sub, sub
    top = sub.sort_values("lift_avg_pp", ascending=False).head(k)
    bot = sub.sort_values("lift_avg_pp", ascending=True).head(k)
    return top, bot


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--drive", type=Path, default=_REPO / "drive")
    ap.add_argument(
        "--cache-dir",
        type=Path,
        default=_REPO / "data" / "newdata" / "data" / ".brt_indicator_cache",
    )
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--out-prefix", type=str, default="IND_Signal_Overlay_PnL")
    ap.add_argument("--reuse-states", type=Path, default=None)
    args = ap.parse_args()
    drive = args.drive
    prefix = args.out_prefix

    states_path = args.reuse_states or (drive / f"{prefix}_Trades_States.csv")
    if states_path.is_file() and args.reuse_states is not None:
        print(f"[load] states {states_path}")
        enriched = pd.read_csv(states_path, low_memory=False)
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
                continue
            frames.append(_load_rl(path) if s == "RL" else _load_brt_like(path, s))
            print(f"[load] {s}: {len(frames[-1])}")
        trades = pd.concat(frames, ignore_index=True)
        if "side" in trades.columns:
            trades = trades[trades["side"].astype(str).str.upper() != "SHORT"]
        print(f"[enrich-states] {len(trades)} trades, workers={args.workers}")
        enriched = enrich_states(trades, args.cache_dir, workers=int(args.workers))
        enriched.to_csv(states_path, index=False)
        print(f"[write] {states_path}")

    ok = enriched[enriched.get("ok", True) == True] if "ok" in enriched.columns else enriched  # noqa: E712
    print(f"[ok] {len(ok)}/{len(enriched)} with states")

    sig_parts = []
    pair_parts = []
    tick_parts = []
    md_sections = []

    for s in SYSTEMS + ["POOLED"]:
        if s == "POOLED":
            df = ok[ok["system"].isin(SYSTEMS)]
            label = "POOLED"
        else:
            df = ok[ok["system"] == s]
            label = s
        if df.empty:
            continue
        print(f"[analyze] {label} n={len(df)}")
        sig = signal_table(df, label)
        pairs = pair_table(df, label, focus=FOCUS_SIGNALS + ("SMA50_OVER_SMA200", "RSI14", "MACD_HIST", "BB_PCTB", "ADX_DI"))
        # Also broad pairs among all if POOLED for focus only already done
        ticks = ticker_effects(df, label)
        sig_parts.append(sig)
        pair_parts.append(pairs)
        tick_parts.append(ticks)

        top, bot = _top_bottom(sig, label, "BULL")
        md_sections.append(f"### {label} — top BULL lifts (n>={MIN_N_SIGNAL})")
        md_sections.append("")
        md_sections.append("| Indicator | N | Avg% | Lift pp | WR% | PF |")
        md_sections.append("|-----------|--:|-----:|--------:|----:|---:|")
        for _, r in top.iterrows():
            pf = r["profit_factor"]
            pf_s = "inf" if pf == np.inf else _fmt_num(pf)
            md_sections.append(
                f"| {r['indicator']} | {int(r['n'])} | {_fmt_num(r['avg_pnl_pct'])} | "
                f"{_fmt_num(r['lift_avg_pp'])} | {_fmt_num(100 * r['win_rate'], 1)} | {pf_s} |"
            )
        md_sections.append("")
        md_sections.append(f"### {label} — worst BULL lifts (n>={MIN_N_SIGNAL})")
        md_sections.append("")
        md_sections.append("| Indicator | N | Avg% | Lift pp | WR% | PF |")
        md_sections.append("|-----------|--:|-----:|--------:|----:|---:|")
        for _, r in bot.iterrows():
            pf = r["profit_factor"]
            pf_s = "inf" if pf == np.inf else _fmt_num(pf)
            md_sections.append(
                f"| {r['indicator']} | {int(r['n'])} | {_fmt_num(r['avg_pnl_pct'])} | "
                f"{_fmt_num(r['lift_avg_pp'])} | {_fmt_num(100 * r['win_rate'], 1)} | {pf_s} |"
            )
        md_sections.append("")

        # Focus signal spotlight
        md_sections.append(f"#### {label} — focus signals (ATR/VOL/DIAMOND/...)")
        md_sections.append("")
        md_sections.append("| Indicator | State | N | Avg% | Lift pp | PF |")
        md_sections.append("|-----------|-------|--:|-----:|--------:|---:|")
        foc = sig[sig["indicator"].isin(FOCUS_SIGNALS)].sort_values(
            ["indicator", "state"]
        )
        for _, r in foc.iterrows():
            if r["n"] < 15:
                continue
            pf = r["profit_factor"]
            pf_s = "inf" if pf == np.inf else _fmt_num(pf)
            md_sections.append(
                f"| {r['indicator']} | {r['state']} | {int(r['n'])} | "
                f"{_fmt_num(r['avg_pnl_pct'])} | {_fmt_num(r['lift_avg_pp'])} | {pf_s} |"
            )
        md_sections.append("")

        if not pairs.empty:
            md_sections.append(f"#### {label} — top BULL+BULL pairs")
            md_sections.append("")
            md_sections.append("| A | B | N | Avg% | Lift pp | PF |")
            md_sections.append("|---|---|--:|-----:|--------:|---:|")
            bb = pairs[(pairs["state_a"] == "BULL") & (pairs["state_b"] == "BULL")].head(10)
            for _, r in bb.iterrows():
                pf = r["profit_factor"]
                pf_s = "inf" if pf == np.inf else _fmt_num(pf)
                md_sections.append(
                    f"| {r['ind_a']} | {r['ind_b']} | {int(r['n'])} | "
                    f"{_fmt_num(r['avg_pnl_pct'])} | {_fmt_num(r['lift_avg_pp'])} | {pf_s} |"
                )
            md_sections.append("")

    sig_csv = drive / f"{prefix}_By_System_Signals.csv"
    pair_csv = drive / f"{prefix}_By_System_Pairs.csv"
    tick_csv = drive / f"{prefix}_By_System_Tickers.csv"
    pd.concat(sig_parts, ignore_index=True).to_csv(sig_csv, index=False)
    pd.concat(pair_parts, ignore_index=True).to_csv(pair_csv, index=False)
    pd.concat(tick_parts, ignore_index=True).to_csv(tick_csv, index=False)

    # Build candidate recommendations
    all_sig = pd.concat(sig_parts, ignore_index=True)
    rec_lines = []
    for s in SYSTEMS:
        bull = all_sig[
            (all_sig["system"] == s)
            & (all_sig["state"] == "BULL")
            & (all_sig["n"] >= MIN_N_SIGNAL)
            & (all_sig["lift_avg_pp"] >= 1.5)
        ].sort_values("lift_avg_pp", ascending=False)
        bearish = all_sig[
            (all_sig["system"] == s)
            & (all_sig["state"] == "BULL")
            & (all_sig["n"] >= MIN_N_SIGNAL)
            & (all_sig["lift_avg_pp"] <= -1.5)
        ].sort_values("lift_avg_pp", ascending=True)
        if bull.empty and bearish.empty:
            rec_lines.append(
                f"- **{s}**: no single-signal BULL overlay clears ±1.5 pp lift at n>={MIN_N_SIGNAL}."
            )
            continue
        pos = ", ".join(
            f"{r.indicator}(+{r.lift_avg_pp:.1f}pp,n={int(r.n)})" for r in bull.head(5).itertuples()
        )
        neg = ", ".join(
            f"{r.indicator}({r.lift_avg_pp:.1f}pp,n={int(r.n)})" for r in bearish.head(5).itertuples()
        )
        use = []
        for r in bull.head(3).itertuples():
            if r.indicator in FOCUS_SIGNALS or r.lift_avg_pp >= 2.5:
                use.append(f"{r.indicator} as soft rank/gate")
        rec_lines.append(
            f"- **{s}**: positive BULL candidates: {pos or '—'}. "
            f"Negative BULL (avoid-as-weight): {neg or '—'}. "
            f"Suggested use: {', '.join(use) if use else 'watchlist only; confirm OOS'}."
        )

    # Credible tickers
    all_tick = pd.concat(tick_parts, ignore_index=True)
    cred = all_tick[all_tick["credible_signal_count"] >= 1] if not all_tick.empty else all_tick
    tick_note = (
        f"{len(cred)} symbol×system rows with >=1 early/late-consistent focus-signal lift "
        f"|lift|>=2pp and n>={MIN_N_TICKER}."
        if not cred.empty
        else "No ticker passed consistency + sample filters."
    )

    md_path = drive / f"{prefix}_By_System.md"
    lines = [
        "# IND Signal Overlay vs Closed-Trade PnL (by system)",
        "",
        "## Evidence class",
        "",
        "Post-hoc association on **already taken** BRT/RL/MTS/WPBR/YH trades with "
        "IND states reconstructed at the trigger bar. Multiple-testing applies "
        f"(~{len(INDICATOR_IDS)} signals × 3 states × 5 systems). "
        "Treat ±1.5–2 pp lifts as hypothesis generators, not production proof.",
        "",
        "## Method",
        "",
        f"- Trigger bar = session before entry; states from `{args.cache_dir}`.",
        f"- Workers: {args.workers}.",
        f"- Min n (single BULL table highlights): {MIN_N_SIGNAL}; pairs: {MIN_N_PAIR}; "
        f"ticker: {MIN_N_TICKER} with early/late halves.",
        f"- Focus signals: {', '.join(FOCUS_SIGNALS)}.",
        "",
        "## Verdict — signal overlays",
        "",
    ]
    lines.extend(rec_lines)
    lines.extend(
        [
            "",
            "## Verdict — ticker-specific (secondary)",
            "",
            tick_note,
            "",
            "Only surface tickers below if `credible_signal_count>=1`. Expect noise; "
            "do not promote ticker-specific IND rules without a dedicated OOS design.",
            "",
            "## Per-system detail",
            "",
        ]
    )
    lines.extend(md_sections)

    if not cred.empty:
        lines.extend(
            [
                "## Credible ticker rows (filtered)",
                "",
                "| System | Symbol | N | Credible # | Avg PnL% | Spearman DIFF |",
                "|--------|--------|--:|-----------:|---------:|--------------:|",
            ]
        )
        for _, r in cred.head(40).iterrows():
            lines.append(
                f"| {r['system']} | {r['symbol']} | {int(r['n'])} | "
                f"{int(r['credible_signal_count'])} | {_fmt_num(r['avg_pnl_pct'])} | "
                f"{_fmt_num(r['spearman_diff'], 3)} |"
            )
        lines.append("")

    lines.extend(
        [
            "## Practical use guidance",
            "",
            "- **Gate**: only if BULL lift is large, retained n stays high, and the signal "
            "is available at decision time without look-ahead.",
            "- **Rank weight**: prefer continuous system scores; IND signal BULL can be a "
            "small additive bump after OOS confirmation.",
            "- **Sizing weight**: not supported from this screening alone.",
            "- ATR_RATIO / VOL_SURGE / DIAMOND: see focus tables; also tested in "
            "`drive/ind_weight_exp_v2/` as IND-native score weights.",
            "",
            "## Outputs",
            "",
            f"- `{md_path.name}`",
            f"- `{sig_csv.name}`",
            f"- `{pair_csv.name}`",
            f"- `{tick_csv.name}`",
            f"- `{states_path.name}`",
            "",
            f"Rerun: `python tools/analyze_ind_signal_overlay_pnl.py --workers {args.workers}`",
            "",
        ]
    )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[write] {md_path}")
    print("[done]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
