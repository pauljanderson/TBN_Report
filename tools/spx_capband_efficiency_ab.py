#!/usr/bin/env python3
"""X/D efficiency grid inside each market-cap bucket.

Same name counts and rebalance waits as spx_x_d_extend_20260916, restricted
each January to one size bucket (same bands as spx_trend_capband_ab_20261009).

No trendline overlays. Research only. Not gold. Not DailyRun.
"""
from __future__ import annotations

import html as html_mod
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
TOOLS = REPO / "tools"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from report_page_extras import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
    inject_report_page_extras,
)
from run_spx_diversification import (  # noqa: E402
    INITIAL_CAPITAL,
    _slice_pack,
    load_price_panels,
    metrics_from_equity,
    run_one_backtest,
    verdict_vs_control,
)
from run_spx_trend_capband_ab import (  # noqa: E402
    BANDS,
    IS_CUT,
    drop_dual_class,
    load_mcap,
)

STAMP = REPO / "drive" / "paul_experiments" / "spx_capband_efficiency_ab_20261009"
X_GRID = (3, 5, 7, 10)
N_GRID = (21, 42, 63, 126, 252)
CONTROL_X = 10
CONTROL_N = 21
COST_BPS = 10.0
PARENT_GRID = "spx_x_d_extend_20260916"
PARENT_BANDS = "spx_trend_capband_ab_20261009"

ORIGINAL_REQUEST = (
    "thank you. can you run the efficiency runs on all buckets please"
)

LAYMAN = (
    "The last page froze one recipe — own five stocks and reshuffle about twice "
    "a year — and then tested chart lines. This page goes back to the older "
    "question: how many stocks, and how often to reshuffle, works best inside "
    "each company-size group. We try 3, 5, 7, or 10 names, and we wait 21, 42, "
    "63, 126, or 252 trading days between reshuffles (about one month through "
    "one year). Each January the list is the largest names still inside that "
    "size bucket. Mega-cap is $200 billion and up. Large-cap is $10 billion up "
    "to $200 billion. Mid-cap is $2 billion up to $10 billion. Small-cap is "
    "$300 million up to $2 billion. Micro-cap is $50 million up to $300 million. "
    "If a bucket has fewer names than we asked for, we hold however many qualify. "
    "More efficient means, in the practice years before 2024, more growth for "
    "the day-to-day bumpiness (a higher Sharpe ratio). Ties go to higher growth, "
    "then a smaller worst drop. From 2024 on is the exam. We do not change the "
    "recipe to fit the exam. The comparison inside each bucket is against holding "
    "10 names and reshuffling every 21 trading days, which was the old control. "
    "Research only."
)

_STATE: dict[str, Any] = {}


def _esc(s: Any) -> str:
    return html_mod.escape("" if s is None else str(s))


def sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{_esc(sort_type)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{_esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _fmt(v: Any, nd: int = 2) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    if not np.isfinite(x):
        return "—"
    return f"{x:.{nd}f}"


def _money(v: Any) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    if not np.isfinite(x):
        return "—"
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):,.2f}"


def _dlt(a: Any, b: Any) -> float | None:
    try:
        av, bv = float(a), float(b)
    except (TypeError, ValueError):
        return None
    if not (np.isfinite(av) and np.isfinite(bv)):
        return None
    return av - bv


def _fmt_dlt(a: Any, b: Any) -> str:
    d = _dlt(a, b)
    if d is None:
        return "—"
    return f"{d:+.2f}"


def _init_worker(opens_path: str, closes_path: str, mcap_path: str) -> None:
    _STATE["opens"] = pd.read_pickle(opens_path)
    _STATE["closes"] = pd.read_pickle(closes_path)
    _STATE["mcap"] = {k: float(v) for k, v in json.loads(Path(mcap_path).read_text(encoding="utf-8")).items()}


def _roster(events: list[dict[str, Any]], which: str) -> str:
    recon = [e for e in events if e.get("kind") == "recon" and e.get("members")]
    if not recon:
        recon = [e for e in events if e.get("members")]
    if not recon:
        return ""
    ev = recon[0] if which == "first" else recon[-1]
    return ", ".join(ev.get("members") or [])


def _run_job(job: dict[str, Any]) -> dict[str, Any]:
    band = job["band"]
    t0 = time.time()
    r = run_one_backtest(
        X=int(job["X"]),
        N=int(job["N"]),
        cost_bps=COST_BPS,
        opens=_STATE["opens"],
        closes=_STATE["closes"],
        mcap_now=_STATE["mcap"],
        capital0=INITIAL_CAPITAL,
        collect_extras=True,
        allow_empty=True,
        mcap_lo=float(band["lo"]),
        mcap_hi=None if band["hi"] is None else float(band["hi"]),
        allow_partial_book=True,
    )
    held = []
    events: list[dict[str, Any]] = []
    slices = {"IS": {"ok": False}, "OOS": {"ok": False}, "FULL": {"ok": False}}
    if r.ok and r.extras:
        eq = r.extras.get("equity") or []
        slices = _slice_pack({"equity": eq}, IS_CUT)
        held = [int(c) for _, c in (r.extras.get("held_counts") or [])]
        events = list(r.extras.get("membership") or [])
    out = {
        "band": band["id"],
        "X": r.X,
        "N": r.N,
        "ok": r.ok,
        "error": r.error,
        "start": r.start,
        "end": r.end,
        "final_equity": r.final_equity,
        "cagr": r.cagr,
        "max_dd": r.max_dd,
        "sharpe": r.sharpe,
        "ann_vol": r.ann_vol,
        "total_trades": r.total_trades,
        "turnover": r.turnover,
        "n_rebalances": r.n_rebalances,
        "avg_held": float(np.mean(held)) if held else None,
        "min_held": int(min(held)) if held else None,
        "first_roster": _roster(events, "first"),
        "last_roster": _roster(events, "last"),
        "slices": slices,
        "seconds": time.time() - t0,
    }
    print(
        f"  {band['id']} X={r.X} D={r.N} ok={r.ok} "
        f"cagr={r.cagr:.2f} {out['seconds']:.1f}s",
        flush=True,
    )
    return out


def _rank_key(row: dict[str, Any]) -> tuple[float, float, float]:
    sl = (row.get("slices") or {}).get("IS") or {}
    if not sl.get("ok"):
        return (1e9, 1e9, 1e9)
    return (-float(sl["sharpe"]), -float(sl["cagr"]), float(sl["max_dd"]))


def _spy_slices(spy: pd.Series, start: str, end: str) -> dict[str, dict[str, Any]]:
    window = spy.loc[(spy.index >= pd.Timestamp(start)) & (spy.index <= pd.Timestamp(end))].dropna()
    equity = (INITIAL_CAPITAL * (window / float(window.iloc[0]))).astype(float)
    dates = [str(pd.Timestamp(d).date()) for d in equity.index]
    vals = [float(v) for v in equity.to_numpy()]
    return {
        "IS": metrics_from_equity(dates, vals, end=IS_CUT),
        "OOS": metrics_from_equity(dates, vals, start=IS_CUT),
        "FULL": metrics_from_equity(dates, vals),
    }


def _metric_cells(sl: dict[str, Any]) -> list[str]:
    return [
        _fmt(sl.get("cagr")),
        _fmt(sl.get("max_dd")),
        _fmt(sl.get("sharpe"), 3),
        _fmt(sl.get("calmar"), 3),
        _fmt(sl.get("ann_vol")),
    ]


def write_reports(
    rows: list[dict[str, Any]],
    *,
    spy_stats: dict[str, dict[str, Any]],
    cache_asof: str,
    n_universe: int,
    dropped: list[str],
    elapsed: float,
) -> None:
    STAMP.mkdir(parents=True, exist_ok=True)
    by_band: dict[str, list[dict[str, Any]]] = {b["id"]: [] for b in BANDS}
    for row in rows:
        by_band[row["band"]].append(row)

    summaries: list[dict[str, Any]] = []
    for band in BANDS:
        arms = [r for r in by_band[band["id"]] if r.get("ok")]
        control = next((r for r in arms if r["X"] == CONTROL_X and r["N"] == CONTROL_N), None)
        ranked = sorted(arms, key=_rank_key)
        winner = ranked[0] if ranked and (ranked[0].get("slices") or {}).get("IS", {}).get("ok") else None
        if control is None or winner is None:
            verdict, why = "FAIL", "missing control or in-sample path"
        else:
            verdict, why = verdict_vs_control(
                {"X": winner["X"], "N": winner["N"], "slices": winner["slices"]},
                {"X": control["X"], "N": control["N"], "slices": control["slices"]},
            )
        summaries.append(
            {
                "band": band,
                "control": control,
                "winner": winner,
                "verdict": verdict,
                "why": why,
            }
        )

    ok_all = [r for r in rows if r.get("ok") and (r.get("slices") or {}).get("IS", {}).get("ok")]
    overall = sorted(ok_all, key=_rank_key)[0] if ok_all else None
    overall_band = next(b for b in BANDS if overall and b["id"] == overall["band"]) if overall else None

    def _bit(row: dict[str, Any] | None, band_label: str) -> str:
        if not row:
            return f"{band_label} failed"
        sl = row["slices"]["IS"]
        return (
            f"{band_label} X={row['X']} D={row['N']} "
            f"(Sharpe {_fmt(sl.get('sharpe'), 3)}, CAGR {_fmt(sl.get('cagr'))}%, "
            f"max drawdown {_fmt(sl.get('max_dd'))}%)"
        )

    answer_parts = []
    if overall and overall_band:
        sl = overall["slices"]["IS"]
        oos = overall["slices"]["OOS"]
        answer_parts.append(
            f"On the practice years before 2024, the most efficient setting in this grid is "
            f"{overall_band['label']} with {overall['X']} names, reshuffled every {overall['N']} "
            f"trading days: Sharpe {_fmt(sl.get('sharpe'), 3)}, CAGR {_fmt(sl.get('cagr'))}%, "
            f"max drawdown {_fmt(sl.get('max_dd'))}%. "
            f"The 2024+ path on that same freeze is CAGR {_fmt(oos.get('cagr'))}% and "
            f"max drawdown {_fmt(oos.get('max_dd'))}% (report-only)."
        )
    answer_parts.append(
        "Inside each bucket the in-sample pick is "
        + "; ".join(_bit(s["winner"], s["band"]["label"]) for s in summaries)
        + "."
    )
    answer_parts.append(
        "That pick is in-sample selection across 100 settings (5 buckets × 4 name counts × 5 waits). "
        "It is not a promotion. Not gold. Not DailyRun."
    )
    spy_is = spy_stats["IS"]
    answer_parts.append(
        f"SPY buy-and-hold over the same window was in-sample CAGR {_fmt(spy_is.get('cagr'))}% "
        f"with max drawdown {_fmt(spy_is.get('max_dd'))}% and Sharpe {_fmt(spy_is.get('sharpe'), 3)}."
    )
    answer = " ".join(answer_parts)

    flat = []
    for row in rows:
        rec = {
            "band": row["band"],
            "X": row["X"],
            "N": row["N"],
            "ok": row["ok"],
            "error": row.get("error") or "",
            "start": row.get("start"),
            "end": row.get("end"),
            "final_equity": row.get("final_equity"),
            "avg_held": row.get("avg_held"),
            "min_held": row.get("min_held"),
            "ann_vol": row.get("ann_vol"),
            "turnover": row.get("turnover"),
            "total_trades": row.get("total_trades"),
            "first_roster": row.get("first_roster"),
            "last_roster": row.get("last_roster"),
        }
        ctrl = next(
            (s["control"] for s in summaries if s["band"]["id"] == row["band"]),
            None,
        )
        for sl_name in ("IS", "OOS", "FULL"):
            sl = (row.get("slices") or {}).get(sl_name) or {}
            rec[f"{sl_name}_cagr"] = sl.get("cagr")
            rec[f"{sl_name}_max_dd"] = sl.get("max_dd")
            rec[f"{sl_name}_sharpe"] = sl.get("sharpe")
            rec[f"{sl_name}_calmar"] = sl.get("calmar")
            rec[f"{sl_name}_ann_vol"] = sl.get("ann_vol")
            rec[f"{sl_name}_ok"] = sl.get("ok")
            csl = ((ctrl or {}).get("slices") or {}).get(sl_name) or {}
            rec[f"{sl_name}_cagr_delta"] = _dlt(sl.get("cagr"), csl.get("cagr"))
            rec[f"{sl_name}_max_dd_delta"] = _dlt(sl.get("max_dd"), csl.get("max_dd"))
            rec[f"{sl_name}_sharpe_delta"] = _dlt(sl.get("sharpe"), csl.get("sharpe"))
        flat.append(rec)
    pd.DataFrame(flat).to_csv(STAMP / "comparison.csv", index=False)

    head_sum = "".join(
        sortable_th(h, t)
        for h, t in (
            ("Bucket", "text"),
            ("Role", "text"),
            ("Names (X)", "num"),
            ("Wait days (D)", "num"),
            ("Verdict", "text"),
            ("IS CAGR %", "num"),
            ("IS max DD %", "num"),
            ("IS Sharpe", "num"),
            ("IS Calmar", "num"),
            ("Δ IS CAGR", "num"),
            ("Δ IS max DD", "num"),
            ("Δ IS Sharpe", "num"),
            ("OOS CAGR %", "num"),
            ("OOS max DD %", "num"),
            ("OOS Sharpe", "num"),
            ("Full CAGR %", "num"),
            ("Full max DD %", "num"),
            ("Full Sharpe", "num"),
            ("Ending equity", "num"),
            ("Avg names held", "num"),
        )
    )
    body_sum = []
    for s in summaries:
        for role, row in (("Control X=10 D=21", s["control"]), ("IS-best", s["winner"])):
            if row is None:
                continue
            if role.startswith("IS-best") and s["control"] and row["X"] == CONTROL_X and row["N"] == CONTROL_N:
                continue
            ctrl = s["control"] or {}
            cis = (ctrl.get("slices") or {}).get("IS") or {}
            iss, oos, full = row["slices"]["IS"], row["slices"]["OOS"], row["slices"]["FULL"]
            verdict = "CONTROL" if role.startswith("Control") else s["verdict"]
            body_sum.append(
                "<tr>"
                + "".join(
                    f"<td>{x}</td>"
                    for x in (
                        _esc(s["band"]["label"]),
                        _esc(role),
                        str(row["X"]),
                        str(row["N"]),
                        _esc(verdict),
                        *_metric_cells(iss)[:4],
                        _fmt_dlt(iss.get("cagr"), cis.get("cagr")),
                        _fmt_dlt(iss.get("max_dd"), cis.get("max_dd")),
                        _fmt_dlt(iss.get("sharpe"), cis.get("sharpe")),
                        *_metric_cells(oos)[:3],
                        *_metric_cells(full)[:3],
                        _money(row.get("final_equity")),
                        _fmt(row.get("avg_held")),
                    )
                )
                + "</tr>"
            )

    head_grid = "".join(
        sortable_th(h, t)
        for h, t in (
            ("Bucket", "text"),
            ("Names (X)", "num"),
            ("Wait days (D)", "num"),
            ("IS CAGR %", "num"),
            ("IS max DD %", "num"),
            ("IS Sharpe", "num"),
            ("IS Calmar", "num"),
            ("IS vol %", "num"),
            ("Δ IS CAGR vs control", "num"),
            ("Δ IS max DD vs control", "num"),
            ("Δ IS Sharpe vs control", "num"),
            ("OOS CAGR %", "num"),
            ("OOS max DD %", "num"),
            ("OOS Sharpe", "num"),
            ("Full CAGR %", "num"),
            ("Full max DD %", "num"),
            ("Full Sharpe", "num"),
            ("Full Calmar", "num"),
            ("Ending equity", "num"),
            ("Avg names held", "num"),
            ("Min names held", "num"),
            ("Trades", "num"),
            ("Turnover", "num"),
            ("First January roster", "text"),
            ("Latest January roster", "text"),
        )
    )
    body_grid = []
    order = {b["id"]: i for i, b in enumerate(BANDS)}
    for row in sorted(rows, key=lambda r: (order.get(r["band"], 9), r["X"], r["N"])):
        iss = (row.get("slices") or {}).get("IS") or {}
        oos = (row.get("slices") or {}).get("OOS") or {}
        full = (row.get("slices") or {}).get("FULL") or {}
        ctrl = next(s["control"] for s in summaries if s["band"]["id"] == row["band"])
        cis = ((ctrl or {}).get("slices") or {}).get("IS") or {}
        label = next(b["label"] for b in BANDS if b["id"] == row["band"])
        body_grid.append(
            "<tr>"
            + "".join(
                f"<td>{x}</td>"
                for x in (
                    _esc(label),
                    str(row["X"]),
                    str(row["N"]),
                    *_metric_cells(iss),
                    _fmt_dlt(iss.get("cagr"), cis.get("cagr")),
                    _fmt_dlt(iss.get("max_dd"), cis.get("max_dd")),
                    _fmt_dlt(iss.get("sharpe"), cis.get("sharpe")),
                    *_metric_cells(oos)[:3],
                    *_metric_cells(full)[:4],
                    _money(row.get("final_equity")),
                    _fmt(row.get("avg_held")),
                    "" if row.get("min_held") is None else str(row["min_held"]),
                    str(row.get("total_trades") or ""),
                    _fmt(row.get("turnover")),
                    _esc(row.get("first_roster") or "—"),
                    _esc(row.get("last_roster") or "—"),
                )
            )
            + "</tr>"
        )

    why_lines = "".join(
        f"<li><strong>{_esc(s['band']['label'])} — {_esc(s['verdict'])}.</strong> {_esc(s['why'])}</li>"
        for s in summaries
    )
    spy_full = spy_stats["FULL"]
    spy_oos = spy_stats["OOS"]
    band_rules = "".join(f"<li>{_esc(b['label'])}: {_esc(b['plain'])}</li>" for b in BANDS)

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Cap-bucket efficiency grid — spx_capband_efficiency_ab_20261009</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #1e293b; line-height: 1.45; }}
h1 {{ font-size: 1.35rem; }}
h2 {{ font-size: 1.1rem; margin-top: 1.6rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0.8rem 0 1rem; }}
.meta {{ color: #475569; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Which name count and wait is most efficient in each size bucket</h1>
<p class="meta">Research only. Not gold. Not DailyRun. Same grid as <code>{PARENT_GRID}</code>, same buckets as <code>{PARENT_BANDS}</code>. Stamp <code>spx_capband_efficiency_ab_20261009</code>.</p>
<div class="callout">
<h2>What you asked</h2>
<p>{_esc(ORIGINAL_REQUEST)}</p>
<p>Earlier note this follows: redo the old runs for each of the buckets to see what is most efficient, rather than freezing five names and a 126-day wait and testing trend lines.</p>
<h2>In plain English</h2>
<p>{_esc(LAYMAN)}</p>
</div>
<h2>What the numbers say</h2>
<p>{_esc(answer)}</p>
<p class="meta">Click column headers to sort.</p>
{SWIPE_NOTE_HTML}
<h2>Control vs in-sample best, by bucket</h2>
<p class="meta">Control in every bucket is 10 names, reshuffle every 21 trading days. Deltas are the in-sample best minus that control. A positive max-drawdown delta is a deeper hole. Calmar here is compound annual growth rate divided by max drawdown. The closed-trade annualized rate of return does not apply: this is one continuous account, not a list of closed trades. The growth number is the equity-path compound annual growth rate (CAGR).</p>
<div class="table-wrap"><table class="sortable"><thead><tr>{head_sum}</tr></thead><tbody>
{"".join(body_sum)}
</tbody></table></div>
<h2>Why each bucket landed there</h2>
<ul>{why_lines}</ul>
<h2>SPY buy-and-hold</h2>
<p>Full period CAGR {_fmt(spy_full.get("cagr"))}% , max drawdown {_fmt(spy_full.get("max_dd"))}% , Sharpe {_fmt(spy_full.get("sharpe"), 3)}. In-sample CAGR {_fmt(spy_is.get("cagr"))}% , max drawdown {_fmt(spy_is.get("max_dd"))}% , Sharpe {_fmt(spy_is.get("sharpe"), 3)}. From 2024 CAGR {_fmt(spy_oos.get("cagr"))}% , max drawdown {_fmt(spy_oos.get("max_dd"))}% , Sharpe {_fmt(spy_oos.get("sharpe"), 3)}. Ending equity {_money(spy_full.get("final_equity"))}.</p>
<h2>Full grid</h2>
<p class="meta">Twenty settings in each bucket. Sorted here by bucket, then names, then wait. Click a header to rank the whole table. In-sample is before 2024-01-01. From 2024 on is report-only.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>{head_grid}</tr></thead><tbody>
{"".join(body_grid)}
</tbody></table></div>
<h2>Freeze</h2>
<ul>
<li>Capital $500,000. Costs 10 basis points per side on traded notional. Fills at the next open.</li>
<li>Membership refreshes on the first trading day of each year. Between those dates the book equal-weights the current names every D trading days. It does not re-rank size until January.</li>
<li>Name counts: 3, 5, 7, 10. Waits: 21, 42, 63, 126, 252 trading days.</li>
<li>Control: X=10, D=21, inside the same bucket.</li>
<li>Scaled market cap = Yahoo market cap now × close on that day / latest close. Cache as-of {_esc(cache_asof)}. Names with a market cap that also have prices: {n_universe}.</li>
</ul>
<p>Size rules</p>
<ul>
{band_rules}
</ul>
<ul>
<li>Partial book when the bucket has fewer names than X. Cash when it has zero.</li>
<li>Dual-class shares dropped: {_esc(", ".join(dropped) if dropped else "none")}.</li>
<li>In-sample is an equity date before 2024-01-01. Out-of-sample is on or after that date, report-only.</li>
<li>Annualized rate of return (the closed-trade house formula) cannot be computed. There is no closed-trade ledger. CAGR is the equity-path compound annual growth rate. Calmar on this page is CAGR / max drawdown.</li>
</ul>
<h2>Honesty</h2>
<ul>
<li>The universe is every symbol with a cached market cap and local prices, not today's S&amp;P 500 list alone. Small-cap and micro-cap are mostly outside that index. Survivors only: names that later died are missing.</li>
<li>Market cap is not a historical filing. It is today's size scaled by the price change.</li>
<li>Picking the best cell after seeing all 100 is in-sample selection. Out-of-sample does not get to choose a new name count or wait.</li>
<li>A three-name book can look efficient and still be a concentrated bet. The verdict rule holds those when the drawdown or volatility jumps versus the 10-name control.</li>
</ul>
<p class="meta">Elapsed {elapsed:.0f}s.</p>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    html_path = STAMP / "compare.html"
    html_path.write_text(inject_report_page_extras(page), encoding="utf-8")

    baseline = [
        "# BASELINE — spx_capband_efficiency_ab_20261009",
        "",
        "**Status:** Research. **Not gold. Not DailyRun.** OOS report-only.",
        "",
        "## What you asked",
        "",
        f"> {ORIGINAL_REQUEST}",
        "",
        "Follows the note to redo the old name-count and rebalance-wait runs inside each size bucket.",
        "",
        "## In plain English",
        "",
        LAYMAN,
        "",
        "## What the numbers say",
        "",
        answer,
        "",
        "## Verdicts vs X=10 D=21 inside the same bucket",
        "",
    ]
    for s in summaries:
        w = s["winner"]
        baseline.append(
            f"- **{s['band']['label']}** {s['verdict']}: "
            f"IS-best X={w['X'] if w else '—'} D={w['N'] if w else '—'}. {s['why']}"
        )
    baseline += [
        "",
        "## Freeze",
        "",
        "- Capital $500,000. Costs 10 bps/side. Next-open fills.",
        "- X grid [3, 5, 7, 10]. D grid [21, 42, 63, 126, 252].",
        "- CONTROL inside each bucket: X=10 D=21.",
        f"- IS equity date < {IS_CUT}. OOS >= {IS_CUT}, report-only.",
        f"- Universe with market cap and prices: {n_universe}. Cache as-of {cache_asof}.",
        "- Same cap bands as spx_trend_capband_ab_20261009. Partial book allowed.",
        "- Closed-trade annualized rate of return does not apply (continuous book). CAGR is the equity-path rate. Calmar = CAGR / max drawdown.",
        "",
        "## Honesty",
        "",
        "- 100-arm grid. Choosing the top cell after seeing the table is in-sample selection.",
        "- Not gold. Not DailyRun.",
        "",
    ]
    (STAMP / "BASELINE.md").write_text("\n".join(baseline) + "\n", encoding="utf-8")
    summary = {
        "stamp": "spx_capband_efficiency_ab_20261009",
        "answer": answer,
        "overall": None
        if not overall
        else {"band": overall["band"], "X": overall["X"], "N": overall["N"], "slices": overall["slices"]},
        "by_band": [
            {
                "band": s["band"]["id"],
                "verdict": s["verdict"],
                "why": s["why"],
                "winner": None if not s["winner"] else {"X": s["winner"]["X"], "N": s["winner"]["N"]},
            }
            for s in summaries
        ],
        "elapsed_sec": elapsed,
    }
    (STAMP / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(answer, flush=True)


def main() -> None:
    t0 = time.time()
    mcap, cache_asof = load_mcap()
    dropped = drop_dual_class(mcap)
    print(f"[eff] mcap {len(mcap)} cache {cache_asof} dropped {dropped}", flush=True)
    opens, closes, spy = load_price_panels(sorted(mcap), start="2010-01-01")
    have = {c for c in closes.columns if c != "SPY"}
    mcap = {s: v for s, v in mcap.items() if s in have}
    print(f"[eff] panel {len(closes)} days × {len(mcap)} names", flush=True)
    cache = STAMP / "_cache"
    cache.mkdir(parents=True, exist_ok=True)
    opens_path = cache / "opens.pkl"
    closes_path = cache / "closes.pkl"
    mcap_path = cache / "mcap.json"
    opens.to_pickle(opens_path)
    closes.to_pickle(closes_path)
    mcap_path.write_text(json.dumps(mcap), encoding="utf-8")
    jobs = [
        {"band": band, "X": x, "N": n}
        for band in BANDS
        for x in X_GRID
        for n in N_GRID
    ]
    print(f"[eff] {len(jobs)} backtests", flush=True)
    workers = 6
    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=_init_worker,
        initargs=(str(opens_path), str(closes_path), str(mcap_path)),
    ) as pool:
        rows = list(pool.map(_run_job, jobs))
    start = min(r["start"] for r in rows if r.get("start"))
    end = max(r["end"] for r in rows if r.get("end"))
    spy_stats = _spy_slices(spy, start, end)
    elapsed = time.time() - t0
    write_reports(
        rows,
        spy_stats=spy_stats,
        cache_asof=cache_asof,
        n_universe=len(mcap),
        dropped=dropped,
        elapsed=elapsed,
    )
    print(f"[eff] done in {elapsed:.1f}s -> {STAMP}", flush=True)


if __name__ == "__main__":
    main()
