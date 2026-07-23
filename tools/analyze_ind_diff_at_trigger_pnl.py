#!/usr/bin/env python3
"""IND_DIFF / IND_SCORE at trigger vs closed-trade PnL across systems.

For BRT/RL/MTS/WPBR/YH/PBR (and IND), load LatestRun Closed CSVs, resolve
trade-aligned IND_DIFF (+ IND_SCORE) at the trigger bar (session before entry),
bucket, and report PnL quality metrics.

Uses ProcessPoolExecutor (~10 workers) to load .indcache.pkl lookups in parallel.
Does not touch drive/ind_weight_exp/.
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
_SA = _REPO / "stock_analysis"
for p in (_REPO, _SA):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from brt_entry_indicators import (  # noqa: E402
    _ensure_gate_arrays,
    _load_disk_cache_payload,
    aligned_bull_bear_diff,
    ind_score_at_bar,
)

RL_CASH = 47500.0

DIFF_BUCKETS = [
    ("<=0", -np.inf, 0),
    ("1-6", 1, 6),
    ("7-10", 7, 10),
    ("11-15", 11, 15),
    ("16-20", 16, 20),
    (">20", 21, np.inf),
]

SCORE_BUCKETS = [
    ("<=-15", -np.inf, -15),
    ("-15--10", -15, -10),
    ("-10--5", -10, -5),
    ("-5-0", -5, 0),
    (">0", 0, np.inf),
]


def _pct(v: Any) -> float:
    if pd.isna(v):
        return np.nan
    s = str(v).strip().replace("%", "").replace(",", "")
    if s == "" or s.lower() == "nan":
        return np.nan
    try:
        return float(s)
    except ValueError:
        return np.nan


def _ymd8(v: Any) -> int:
    s = "".join(ch for ch in str(v).strip() if ch.isdigit())[:8]
    return int(s) if len(s) == 8 else 0


def _bucket_label(x: float, edges: list[tuple[str, float, float]]) -> str:
    if not np.isfinite(x):
        return "NA"
    for lab, lo, hi in edges:
        if lo == -np.inf:
            if x <= hi:
                return lab
        elif hi == np.inf:
            if x >= lo:
                return lab
        else:
            if lo <= x <= hi:
                return lab
    return "NA"


def _load_brt_like(path: Path, system: str) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)
    out = pd.DataFrame(
        {
            "system": system,
            "symbol": df["SYMBOL"].astype(str).str.upper().str.strip(),
            "side": df["SIDE"].astype(str).str.upper().str.strip()
            if "SIDE" in df.columns
            else "LONG",
            "entry": df["DATE_OPENED"].map(_ymd8),
            "days_held": pd.to_numeric(df["DAYS_HELD"], errors="coerce"),
            "pnl_pct": df["PNL_PCT"].map(_pct),
            "pnl_dollars": pd.to_numeric(df["PNL_DOLLARS"], errors="coerce"),
        }
    )
    if "IND_DIFF" in df.columns:
        out["ind_diff_csv"] = pd.to_numeric(df["IND_DIFF"], errors="coerce")
    else:
        out["ind_diff_csv"] = np.nan
    if "IND_SCORE" in df.columns:
        out["ind_score_csv"] = pd.to_numeric(df["IND_SCORE"], errors="coerce")
    else:
        out["ind_score_csv"] = np.nan
    if "SPY_IND_DIFF" in df.columns:
        out["spy_ind_diff"] = pd.to_numeric(df["SPY_IND_DIFF"], errors="coerce")
    else:
        out["spy_ind_diff"] = np.nan
    return out


def _load_rl(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)
    pnl = df["PNL %"].map(_pct)
    return pd.DataFrame(
        {
            "system": "RL",
            "symbol": df["SYMBOL"].astype(str).str.upper().str.strip(),
            "side": "LONG",
            "entry": df["DATE OPENED"].map(_ymd8),
            "days_held": pd.to_numeric(df["DAYS HELD"], errors="coerce"),
            "pnl_pct": pnl,
            "pnl_dollars": pnl / 100.0 * RL_CASH,
            "ind_diff_csv": np.nan,
            "ind_score_csv": np.nan,
            "spy_ind_diff": np.nan,
        }
    )


def _worker_lookup(args: tuple) -> list[dict[str, Any]]:
    """Per-symbol: map (entry_ymd, side) -> IND_DIFF/SCORE at trigger bar (entry_i - 1)."""
    symbol, cache_dir_s, requests = args
    cache_dir = Path(cache_dir_s)
    out: list[dict[str, Any]] = []
    try:
        payload = _load_disk_cache_payload(cache_dir, symbol)
        if not payload or "pre" not in payload:
            for req in requests:
                out.append({**req, "ind_diff": np.nan, "ind_score": np.nan, "ok": False})
            return out
        pre = _ensure_gate_arrays(payload["pre"])
        dates = np.asarray(pre.dates, dtype=np.int64)
        date_to_i = {int(d): i for i, d in enumerate(dates)}
        for req in requests:
            entry = int(req["entry"])
            side = str(req.get("side") or "LONG")
            ei = date_to_i.get(entry)
            if ei is None or ei < 1:
                out.append({**req, "ind_diff": np.nan, "ind_score": np.nan, "ok": False})
                continue
            ti = ei - 1  # trigger = prior bar in symbol calendar
            diff = aligned_bull_bear_diff(pre, ti, side)
            score = ind_score_at_bar(pre, ti)
            out.append(
                {
                    **req,
                    "ind_diff": float(diff) if diff is not None else np.nan,
                    "ind_score": float(score) if score is not None else np.nan,
                    "ok": diff is not None,
                    "trigger_ymd": int(dates[ti]),
                }
            )
    except Exception as exc:  # noqa: BLE001
        for req in requests:
            out.append(
                {
                    **req,
                    "ind_diff": np.nan,
                    "ind_score": np.nan,
                    "ok": False,
                    "err": str(exc)[:120],
                }
            )
    return out


def enrich_with_cache(
    trades: pd.DataFrame,
    cache_dir: Path,
    *,
    workers: int = 10,
) -> pd.DataFrame:
    """Attach ind_diff / ind_score from cache (prefer CSV stamp when present for IND)."""
    need = trades.copy()
    need["_row"] = np.arange(len(need))

    # Prefer stamped IND_DIFF when present (already at trigger).
    stamped = need["ind_diff_csv"].notna()
    need["ind_diff"] = np.nan
    need["ind_score"] = np.nan
    need.loc[stamped, "ind_diff"] = need.loc[stamped, "ind_diff_csv"]
    need.loc[stamped, "ind_score"] = need.loc[stamped, "ind_score_csv"]

    todo = need.loc[~stamped].copy()
    if todo.empty:
        need["lookup_ok"] = stamped
        return need

    groups: dict[str, list[dict[str, Any]]] = {}
    for _, r in todo.iterrows():
        sym = str(r["symbol"])
        groups.setdefault(sym, []).append(
            {
                "_row": int(r["_row"]),
                "entry": int(r["entry"]),
                "side": str(r["side"]),
            }
        )

    jobs = [(sym, str(cache_dir), reqs) for sym, reqs in groups.items()]
    results: list[dict[str, Any]] = []
    w = max(1, int(workers))
    if w == 1 or len(jobs) < 2:
        for job in jobs:
            results.extend(_worker_lookup(job))
    else:
        with ProcessPoolExecutor(max_workers=w) as ex:
            futs = {ex.submit(_worker_lookup, job): job[0] for job in jobs}
            for fut in as_completed(futs):
                results.extend(fut.result())

    if results:
        rdf = pd.DataFrame(results)
        for _, r in rdf.iterrows():
            i = int(r["_row"])
            need.at[i, "ind_diff"] = r["ind_diff"]
            need.at[i, "ind_score"] = r["ind_score"]
        need["lookup_ok"] = need["ind_diff"].notna()
    else:
        need["lookup_ok"] = stamped
    return need


def _trade_stats(df: pd.DataFrame) -> dict[str, Any]:
    n = len(df)
    if n == 0:
        return {
            "n": 0,
            "win_rate": np.nan,
            "avg_pnl_pct": np.nan,
            "median_pnl_pct": np.nan,
            "total_pnl_pct": np.nan,
            "total_pnl_dollars": np.nan,
            "profit_factor": np.nan,
            "expectancy_pct": np.nan,
            "avg_days": np.nan,
            "top_symbol_share": np.nan,
            "n_symbols": 0,
            "top_symbol": "",
        }
    pnl = df["pnl_pct"].astype(float)
    wins = pnl > 0
    losses = pnl < 0
    gp = float(pnl[wins].sum()) if wins.any() else 0.0
    gl = float((-pnl[losses]).sum()) if losses.any() else 0.0
    pf = (gp / gl) if gl > 0 else (np.inf if gp > 0 else np.nan)
    sym_counts = df["symbol"].value_counts()
    top_sym = str(sym_counts.index[0]) if len(sym_counts) else ""
    top_share = float(sym_counts.iloc[0] / n) if len(sym_counts) else np.nan
    return {
        "n": n,
        "win_rate": float(wins.mean()),
        "avg_pnl_pct": float(pnl.mean()),
        "median_pnl_pct": float(pnl.median()),
        "total_pnl_pct": float(pnl.sum()),
        "total_pnl_dollars": float(pd.to_numeric(df["pnl_dollars"], errors="coerce").sum()),
        "profit_factor": float(pf) if np.isfinite(pf) else pf,
        "expectancy_pct": float(pnl.mean()),
        "avg_days": float(pd.to_numeric(df["days_held"], errors="coerce").mean()),
        "top_symbol_share": top_share,
        "n_symbols": int(df["symbol"].nunique()),
        "top_symbol": top_sym,
    }


def bucket_table(df: pd.DataFrame, col: str, edges: list[tuple[str, float, float]]) -> pd.DataFrame:
    work = df.dropna(subset=[col, "pnl_pct"]).copy()
    work["bucket"] = work[col].map(lambda x: _bucket_label(float(x), edges))
    rows = []
    order = [e[0] for e in edges] + ["NA"]
    for lab in order:
        sub = work[work["bucket"] == lab]
        if sub.empty and lab == "NA":
            continue
        st = _trade_stats(sub)
        st["bucket"] = lab
        st["mean_feature"] = float(sub[col].mean()) if len(sub) else np.nan
        rows.append(st)
    out = pd.DataFrame(rows)
    if not out.empty:
        # keep bucket order
        out["bucket"] = pd.Categorical(out["bucket"], categories=order, ordered=True)
        out = out.sort_values("bucket")
    return out


def spearman(df: pd.DataFrame, x: str, y: str = "pnl_pct") -> tuple[float, int]:
    """Spearman rank correlation via average ranks + Pearson (no scipy required)."""
    sub = df[[x, y]].dropna()
    n = len(sub)
    if n < 5:
        return float("nan"), n
    rx = sub[x].rank(method="average")
    ry = sub[y].rank(method="average")
    r = float(rx.corr(ry, method="pearson"))
    return r, n


def year_control(df: pd.DataFrame, col: str = "ind_diff") -> pd.DataFrame:
    """Spearman within calendar year of entry."""
    work = df.dropna(subset=[col, "pnl_pct", "entry"]).copy()
    work["year"] = (work["entry"] // 10000).astype(int)
    rows = []
    for y, g in work.groupby("year"):
        r, n = spearman(g, col)
        rows.append({"year": int(y), "n": n, "spearman": r, "avg_pnl": g["pnl_pct"].mean()})
    return pd.DataFrame(rows)


def hold_control(df: pd.DataFrame, col: str = "ind_diff") -> pd.DataFrame:
    work = df.dropna(subset=[col, "pnl_pct", "days_held"]).copy()
    work["hold_bucket"] = pd.cut(
        work["days_held"],
        bins=[-np.inf, 10, 30, 60, np.inf],
        labels=["<=10d", "11-30d", "31-60d", ">60d"],
    )
    rows = []
    for lab, g in work.groupby("hold_bucket", observed=True):
        r, n = spearman(g, col)
        rows.append({"hold_bucket": str(lab), "n": n, "spearman": r, "avg_pnl": g["pnl_pct"].mean()})
    return pd.DataFrame(rows)


def gate_simulation(df: pd.DataFrame, thresholds: list[int]) -> pd.DataFrame:
    """What if we only kept trades with IND_DIFF >= T."""
    base = df.dropna(subset=["ind_diff", "pnl_pct"])
    rows = []
    st0 = _trade_stats(base)
    rows.append({"gate": "all", "min_diff": None, **st0})
    for t in thresholds:
        sub = base[base["ind_diff"] >= t]
        st = _trade_stats(sub)
        rows.append({"gate": f">={t}", "min_diff": t, **st})
    return pd.DataFrame(rows)


def _fmt_pct(x: float) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"{100.0 * x:.1f}%" if abs(x) <= 1.5 else f"{x:.2f}%"


def _fmt_num(x: float, nd: int = 2) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"{x:.{nd}f}"


def md_bucket_table(sysname: str, bt: pd.DataFrame, feature: str, spear: float, n: int) -> str:
    lines = [
        f"### {sysname} — by {feature}",
        "",
        f"Spearman({feature}, pnl_pct) = **{_fmt_num(spear, 3)}** (n={n})",
        "",
        "| Bucket | N | Win% | Avg PnL% | Med PnL% | Total $ | PF | Avg days | Top sym share |",
        "|--------|--:|-----:|---------:|---------:|--------:|---:|---------:|--------------:|",
    ]
    for _, r in bt.iterrows():
        wr = r["win_rate"]
        wr_s = f"{100*wr:.1f}%" if np.isfinite(wr) else "—"
        pf = r["profit_factor"]
        pf_s = "inf" if pf == np.inf else _fmt_num(pf)
        lines.append(
            f"| {r['bucket']} | {int(r['n'])} | {wr_s} | {_fmt_num(r['avg_pnl_pct'])} | "
            f"{_fmt_num(r['median_pnl_pct'])} | {_fmt_num(r['total_pnl_dollars'], 0)} | {pf_s} | "
            f"{_fmt_num(r['avg_days'], 1)} | {_fmt_num(100*r['top_symbol_share'], 1)}% |"
        )
    lines.append("")
    return "\n".join(lines)


def analyze_system(sysname: str, df: pd.DataFrame) -> dict[str, Any]:
    valid = df.dropna(subset=["ind_diff", "pnl_pct"]).copy()
    valid = valid[valid["side"].str.upper() != "SHORT"]  # buy/long focus
    sp_d, n_d = spearman(valid, "ind_diff")
    sp_s, n_s = spearman(valid, "ind_score")
    bt_d = bucket_table(valid, "ind_diff", DIFF_BUCKETS)
    bt_s = bucket_table(valid, "ind_score", SCORE_BUCKETS)
    gates = gate_simulation(valid, [0, 7, 10, 11, 15, 16, 20])
    years = year_control(valid)
    holds = hold_control(valid)
    overall = _trade_stats(valid)
    return {
        "system": sysname,
        "n_total": len(df),
        "n_long_with_diff": len(valid),
        "coverage": len(valid) / max(1, len(df)),
        "spearman_diff": sp_d,
        "spearman_diff_n": n_d,
        "spearman_score": sp_s,
        "spearman_score_n": n_s,
        "bucket_diff": bt_d,
        "bucket_score": bt_s,
        "gates": gates,
        "years": years,
        "holds": holds,
        "overall": overall,
        "valid": valid,
    }


def _verdict_line(res: dict[str, Any]) -> str:
    sp = res["spearman_diff"]
    n = res["n_long_with_diff"]
    if n < 40:
        strength = "too few trades"
    elif not np.isfinite(sp):
        strength = "no correlation estimate"
    elif sp >= 0.08:
        strength = "weak positive"
    elif sp >= 0.03:
        strength = "very weak positive"
    elif sp > -0.03:
        strength = "null / flat"
    elif sp > -0.08:
        strength = "very weak negative"
    else:
        strength = "weak negative"

    gates = res["gates"]
    base = gates[gates["gate"] == "all"].iloc[0]
    best = None
    for _, g in gates.iterrows():
        if g["gate"] == "all" or g["n"] < max(25, 0.15 * base["n"]):
            continue
        if best is None or g["avg_pnl_pct"] > best["avg_pnl_pct"]:
            best = g
    gate_note = ""
    if best is not None and np.isfinite(best["avg_pnl_pct"]) and np.isfinite(base["avg_pnl_pct"]):
        lift = best["avg_pnl_pct"] - base["avg_pnl_pct"]
        if lift > 0.5:
            gate_note = f"; best soft gate {best['gate']} avg {_fmt_num(best['avg_pnl_pct'])}% vs all {_fmt_num(base['avg_pnl_pct'])}% (n={int(best['n'])})"
        else:
            gate_note = f"; no useful min-diff gate (best lift {_fmt_num(lift)} pp)"
    return f"**{res['system']}**: Spearman={_fmt_num(sp, 3)} ({strength}, n={n}){gate_note}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--drive", type=Path, default=_REPO / "drive")
    ap.add_argument(
        "--cache-dir",
        type=Path,
        default=_REPO / "data" / "newdata" / "data" / ".brt_indicator_cache",
    )
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--out-prefix", type=str, default="IND_Diff_At_Trigger_PnL")
    args = ap.parse_args()

    drive: Path = args.drive
    cache_dir: Path = args.cache_dir
    workers = int(args.workers)
    prefix = args.out_prefix

    files = {
        "BRT": drive / "BRT_LatestRun_Closed.csv",
        "RL": drive / "RL_LatestRun_Closed.csv",
        "MTS": drive / "MTS_LatestRun_Closed.csv",
        "WPBR": drive / "WPBR_LatestRun_Closed.csv",
        "YH": drive / "YH_LatestRun_Closed.csv",
        "PBR": drive / "PBR_LatestRun_Closed.csv",
        "IND": drive / "IND_LatestRun_Closed.csv",
    }

    frames = []
    for sysname, path in files.items():
        if not path.exists():
            print(f"[skip] missing {path}")
            continue
        if sysname == "RL":
            frames.append(_load_rl(path))
        else:
            frames.append(_load_brt_like(path, sysname))
        print(f"[load] {sysname}: {len(frames[-1])} trades from {path.name}")

    trades = pd.concat(frames, ignore_index=True)
    print(f"[enrich] {len(trades)} trades, {trades['symbol'].nunique()} symbols, workers={workers}")
    enriched = enrich_with_cache(trades, cache_dir, workers=workers)
    miss = (~enriched["lookup_ok"]).sum()
    print(f"[enrich] done; missing IND_DIFF on {miss}/{len(enriched)} trades")

    # Persist enriched trades (for audit / reruns)
    enriched_path = drive / f"{prefix}_Trades_Enriched.csv"
    enriched.to_csv(enriched_path, index=False)
    print(f"[write] {enriched_path}")

    systems = ["BRT", "RL", "MTS", "WPBR", "YH", "PBR", "IND"]
    # Per-system stats are cheap; heavy work was the parallel cache enrich above.
    results: dict[str, Any] = {}
    for s in systems:
        if s not in enriched["system"].unique():
            continue
        r = analyze_system(s, enriched[enriched["system"] == s])
        results[s] = r
        print(f"[analyze] {s}: n={r['n_long_with_diff']} spearman_diff={r['spearman_diff']}")

    # Pooled (ex-IND, since IND already gates on DIFF)
    pooled_sys = ["BRT", "RL", "MTS", "WPBR", "YH"]
    pooled = enriched[enriched["system"].isin(pooled_sys)]
    results["POOLED_exIND"] = analyze_system("POOLED_exIND", pooled)
    print(
        f"[analyze] POOLED_exIND: n={results['POOLED_exIND']['n_long_with_diff']} "
        f"spearman_diff={results['POOLED_exIND']['spearman_diff']}"
    )

    # Write CSVs
    bucket_rows = []
    gate_rows = []
    summary_rows = []
    for s, r in results.items():
        bd = r["bucket_diff"].copy()
        bd.insert(0, "system", s)
        bd.insert(1, "feature", "IND_DIFF")
        bucket_rows.append(bd)
        bs = r["bucket_score"].copy()
        bs.insert(0, "system", s)
        bs.insert(1, "feature", "IND_SCORE")
        bucket_rows.append(bs)
        g = r["gates"].copy()
        g.insert(0, "system", s)
        gate_rows.append(g)
        summary_rows.append(
            {
                "system": s,
                "n_total": r["n_total"],
                "n_long_with_diff": r["n_long_with_diff"],
                "coverage": r["coverage"],
                "spearman_ind_diff_pnl": r["spearman_diff"],
                "spearman_ind_score_pnl": r["spearman_score"],
                "avg_pnl_pct": r["overall"]["avg_pnl_pct"],
                "win_rate": r["overall"]["win_rate"],
                "total_pnl_dollars": r["overall"]["total_pnl_dollars"],
                "profit_factor": r["overall"]["profit_factor"],
                "n_symbols": r["overall"]["n_symbols"],
                "top_symbol": r["overall"]["top_symbol"],
                "top_symbol_share": r["overall"]["top_symbol_share"],
            }
        )

    buckets_csv = drive / f"{prefix}_By_System_Buckets.csv"
    gates_csv = drive / f"{prefix}_Gate_Sim.csv"
    summary_csv = drive / f"{prefix}_Summary.csv"
    pd.concat(bucket_rows, ignore_index=True).to_csv(buckets_csv, index=False)
    pd.concat(gate_rows, ignore_index=True).to_csv(gates_csv, index=False)
    pd.DataFrame(summary_rows).to_csv(summary_csv, index=False)

    # Year / hold controls for pooled + each main system
    control_parts = []
    for s in ["BRT", "RL", "MTS", "WPBR", "YH", "POOLED_exIND"]:
        if s not in results:
            continue
        y = results[s]["years"].copy()
        y.insert(0, "system", s)
        y.insert(1, "control", "year")
        control_parts.append(y.rename(columns={"year": "slice"}))
        h = results[s]["holds"].copy()
        h.insert(0, "system", s)
        h.insert(1, "control", "hold")
        control_parts.append(h.rename(columns={"hold_bucket": "slice"}))
    controls_csv = drive / f"{prefix}_Controls.csv"
    if control_parts:
        pd.concat(control_parts, ignore_index=True).to_csv(controls_csv, index=False)

    # Markdown report
    md_path = drive / f"{prefix}_By_System.md"
    lines = [
        "# IND_DIFF at trigger vs trade PnL (by system)",
        "",
        "## Question",
        "",
        "Although IND_DIFF is not strongly associated with *unconditional* forward rises, "
        "is a **higher IND_DIFF at the system trigger** associated with **better closed-trade PnL** "
        "when used as a filter/weight on BRT / RL / MTS / WPBR / YH entries?",
        "",
        "## Method",
        "",
        f"- Closed files: `*_LatestRun_Closed.csv` under `{drive}`.",
        f"- Symbol IND_DIFF / IND_SCORE at **trigger bar** = session before `DATE_OPENED` "
        f"(matches IND closed stamps; verified on ACRS).",
        f"- Lookups from `{cache_dir}` via `{workers}` worker processes "
        "(IND uses stamped columns when present).",
        "- Long/buy trades only for primary tables; shorts excluded.",
        "- Buckets: ≤0, 1–6, 7–10, 11–15, 16–20, >20.",
        "- Metrics: N, win rate, avg/median/total PnL%, total $, profit factor, expectancy (=avg), avg days.",
        "- Confounders: top-symbol share; Spearman by entry year and holding-period bucket.",
        "- Gate sim: keep trades with IND_DIFF ≥ T (0,7,10,11,15,16,20).",
        "- PBR included as legacy WPBR peer; IND included as reference (already DIFF-gated).",
        "",
        "## Verdict (executive)",
        "",
    ]

    # Build overall verdict from pooled + per-system
    pooled_r = results.get("POOLED_exIND")
    if pooled_r:
        lines.append(_verdict_line(pooled_r))
        lines.append("")
    lines.append("Per system:")
    lines.append("")
    for s in ["BRT", "RL", "MTS", "WPBR", "YH", "PBR", "IND"]:
        if s in results:
            lines.append(f"- {_verdict_line(results[s])}")
    lines.append("")

    # Practical recommendation
    lines.extend(
        [
            "## Practical recommendation",
            "",
        ]
    )
    # Compute pooled gate lifts for recommendation text
    if pooled_r is not None:
        g = pooled_r["gates"]
        base = g[g["gate"] == "all"].iloc[0]
        useful = []
        for _, row in g.iterrows():
            if row["gate"] == "all" or row["n"] < max(40, 0.2 * base["n"]):
                continue
            lift = row["avg_pnl_pct"] - base["avg_pnl_pct"]
            useful.append((lift, row))
        useful.sort(key=lambda x: -x[0])
        sp = pooled_r["spearman_diff"]
        if not np.isfinite(sp) or abs(sp) < 0.03:
            lines.append(
                "Evidence for a **monotonic** “higher DIFF → higher PnL” relationship on "
                "system entries is **weak/null** (pooled Spearman near zero). "
                "Do **not** use IND_DIFF as a primary ranker or aggressive sizing weight "
                "on top of BRT/RL/MTS/WPBR/YH."
            )
        elif sp > 0:
            lines.append(
                f"Pooled Spearman is mildly positive ({sp:.3f}). "
                "IND_DIFF may help as a **soft secondary signal**, not a hard alpha source."
            )
        else:
            lines.append(
                f"Pooled Spearman is **negative** ({sp:.3f}): higher DIFF at trigger tends to "
                "coincide with *worse* closed PnL among system entries — consistent with the "
                "unconditional forward-return finding. Avoid min-DIFF gates that select the "
                "highest DIFF buckets."
            )
        lines.append("")
        if useful and useful[0][0] > 0.5:
            best = useful[0][1]
            lines.append(
                f"- Soft **minimum gate** candidate: `{best['gate']}` "
                f"(avg PnL {_fmt_num(best['avg_pnl_pct'])}% vs all {_fmt_num(base['avg_pnl_pct'])}%, "
                f"n={int(best['n'])}/{int(base['n'])}). Validate out-of-sample before production."
            )
        else:
            lines.append(
                "- **Minimum gate**: no clear profitable DIFF floor on pooled non-IND systems "
                "with adequate sample retention."
            )
        lines.append(
            "- **Sizing weight**: not supported — correlation magnitude is small and "
            "high-DIFF buckets are often flat or worse."
        )
        lines.append(
            "- **Ranker among same-day candidates**: weak at best; prefer system-native scores "
            "(RL watch score, WPBR zone strength, etc.)."
        )
        lines.append(
            "- **IND_SCORE**: check per-system Spearman below; if similarly flat/negative, "
            "same conclusion applies."
        )
    lines.append("")

    lines.append("## Cross-system summary")
    lines.append("")
    lines.append(
        "| System | N | Coverage | Spearman DIFF | Spearman SCORE | Avg PnL% | Win% | PF | Top sym % |"
    )
    lines.append(
        "|--------|--:|---------:|--------------:|---------------:|---------:|-----:|---:|----------:|"
    )
    for s in ["BRT", "RL", "MTS", "WPBR", "YH", "PBR", "IND", "POOLED_exIND"]:
        if s not in results:
            continue
        r = results[s]
        o = r["overall"]
        pf = o["profit_factor"]
        pf_s = "inf" if pf == np.inf else _fmt_num(pf)
        lines.append(
            f"| {s} | {r['n_long_with_diff']} | {_fmt_num(100*r['coverage'],1)}% | "
            f"{_fmt_num(r['spearman_diff'],3)} | {_fmt_num(r['spearman_score'],3)} | "
            f"{_fmt_num(o['avg_pnl_pct'])} | {_fmt_num(100*o['win_rate'],1)}% | {pf_s} | "
            f"{_fmt_num(100*o['top_symbol_share'],1)}% |"
        )
    lines.append("")

    lines.append("## Per-system bucket tables")
    lines.append("")
    for s in ["BRT", "RL", "MTS", "WPBR", "YH", "PBR", "IND", "POOLED_exIND"]:
        if s not in results:
            continue
        r = results[s]
        lines.append(md_bucket_table(s, r["bucket_diff"], "IND_DIFF", r["spearman_diff"], r["spearman_diff_n"]))
        if r["bucket_score"] is not None and len(r["bucket_score"]):
            lines.append(
                md_bucket_table(s, r["bucket_score"], "IND_SCORE", r["spearman_score"], r["spearman_score_n"])
            )
        # Gate brief
        lines.append(f"#### {s} — min IND_DIFF gate simulation")
        lines.append("")
        lines.append("| Gate | N | Win% | Avg PnL% | Total $ | PF |")
        lines.append("|------|--:|-----:|---------:|--------:|---:|")
        for _, g in r["gates"].iterrows():
            pf = g["profit_factor"]
            pf_s = "inf" if pf == np.inf else _fmt_num(pf)
            wr = g["win_rate"]
            wr_s = f"{100*wr:.1f}%" if np.isfinite(wr) else "—"
            lines.append(
                f"| {g['gate']} | {int(g['n'])} | {wr_s} | {_fmt_num(g['avg_pnl_pct'])} | "
                f"{_fmt_num(g['total_pnl_dollars'],0)} | {pf_s} |"
            )
        lines.append("")

    lines.extend(
        [
            "## Confounders (notes)",
            "",
            "- See `*_Controls.csv` for Spearman by entry year and holding-period bucket.",
            "- Bucket tables include **top symbol share**; if a high-DIFF bucket is dominated by "
            "one ticker, treat that cell cautiously.",
            "- IND rows are **already** selected with a DIFF gate in production — their DIFF "
            "distribution is truncated and not comparable to ungated systems for gate design.",
            "- Unconditional forward-return study found high DIFF → worse fwd returns; "
            "this study is **conditional on system entries** (different sample).",
            "",
            "## Outputs",
            "",
            f"- `{md_path.name}`",
            f"- `{summary_csv.name}`",
            f"- `{buckets_csv.name}`",
            f"- `{gates_csv.name}`",
            f"- `{controls_csv.name}`",
            f"- `{enriched_path.name}`",
            "",
            f"Rerun: `python tools/analyze_ind_diff_at_trigger_pnl.py --workers {workers}`",
            "",
        ]
    )

    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[write] {md_path}")
    print(f"[write] {summary_csv}")
    print(f"[write] {buckets_csv}")
    print(f"[write] {gates_csv}")
    print("[done]")
    return 0


if __name__ == "__main__":
    # Windows spawn safety
    raise SystemExit(main())
