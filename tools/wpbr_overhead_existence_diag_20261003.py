#!/usr/bin/env python3
"""WPBR overhead-existence diagnostic on the 22% control book.

Classification only. Two groups: no qualifying overhead zone vs nearest
qualifying overhead zone farther than the live 22% exclusion (gap > 0.22).
Uses engine prior_overhead_nearest_gap. Writes drive/mark_experiments/.
"""
from __future__ import annotations

import csv
import html as html_mod
import importlib.util
import math
import os
import subprocess
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
sys.path.insert(0, str(ROOT / "stock_analysis"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from compare_format import calmar_ratio, format_money  # noqa: E402
from report_page_extras import (  # noqa: E402
    CACHE_META,
    FORCE_RELOAD_SCRIPT,
    RESPONSIVE_TABLE_CSS,
    SORTABLE_TABLE_SCRIPT,
    SWIPE_NOTE_HTML,
    inject_report_page_extras,
)
from _gen_too_high_diff import SORTABLE_TH_CSS, sortable_th  # noqa: E402
from rocket_tbn import prior_overhead_nearest_gap  # noqa: E402
from wpbr_zones import compute_wpbr_touch_stream  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "wpbr_struct_diag",
    ROOT / "tools" / "wpbr_structure_prior_overhead_diag_20261003.py",
)
_st = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_st)

CLOSED = _st.CLOSED
REPORT = _st.REPORT
WPBR_KW = _st.WPBR_KW
IS_CUT = _st.IS_CUT
load_closed = _st.load_closed
load_prices = _st.load_prices
load_report_cash = _st.load_report_cash
metrics_for = _st.metrics_for
slice_years = _st.slice_years
fmt_n = _st.fmt_n
fmt_num = _st.fmt_num
fmt_pct = _st.fmt_pct

OUT = ROOT / "drive" / "mark_experiments" / "wpbr_overhead_existence_diag_20261003"
OH_BAND = 0.22
G1 = "NO_OVERHEAD"
G2 = "OVERHEAD_GE22"
LEAK = "OVERHEAD_LT22_LEAK"
UNCL = "UNCLASSIFIED"
GROUP_LABELS = {
    G1: "GROUP 1 — NO OVERHEAD ZONE",
    G2: "GROUP 2 — OVERHEAD ZONE ≥22%",
    LEAK: "LEAK — overhead gap ≤22% (should be empty)",
    UNCL: "UNCLASSIFIED",
}

REQUEST_QUOTE = (
    "Run a WPBR overhead-existence diagnostic on the current control system. This is "
    "classification/reporting only. Do not change any entry, exit, target, stop, overhead "
    "exclusion, sizing, or execution logic.\n"
    "Use the current WPBR control population with the existing 22% overhead-zone exclusion.\n"
    "For every closed trade that survives the existing 22% overhead rule, classify it into "
    "exactly one of two mutually exclusive groups:\n"
    "GROUP 1 — NO OVERHEAD ZONE: No qualifying prior WPBR overhead zone exists anywhere "
    "above the active WPBR zone.\n"
    "GROUP 2 — OVERHEAD ZONE ≥22%: At least one qualifying prior WPBR overhead zone exists "
    "above the active WPBR zone, but the nearest qualifying overhead zone is at least 22% "
    "above the active zone and therefore does not trigger the existing 22% exclusion.\n"
    "Use the existing WPBR definition of a qualifying overhead zone. Do not create a new "
    "zone definition.\n"
    "Report IS / OOS / FULL separately for both groups. Also report holding-duration "
    "percentiles. Reconcile NO OVERHEAD + OVERHEAD ≥22% = all current control trades.\n"
    "Do not create distance bins. Do not change the target or stop. Do not optimize the 22% "
    "threshold."
)

WORKERS = min(32, os.cpu_count() or 8)


def _iso(d: date | None) -> str:
    return d.isoformat() if d else ""


def _bar_index(df: pd.DataFrame, d: date | None) -> int | None:
    if df is None or df.empty or d is None:
        return None
    ts = pd.Timestamp(d)
    idx = df.index
    if ts in idx:
        return int(idx.get_loc(ts))
    loc = idx.searchsorted(ts)
    if loc < len(idx) and idx[loc] == ts:
        return int(loc)
    return None


def _events_for_df(sym: str, df: pd.DataFrame) -> tuple[str, list[dict[str, Any]]]:
    if df is None or df.empty:
        return sym, []
    stream = compute_wpbr_touch_stream(df, **WPBR_KW)
    events: list[dict[str, Any]] = []
    for ev in stream.get("wpbr_zone_events") or []:
        act = ev.get("activation_bar")
        try:
            act_i = int(act) if act is not None else -1
        except (TypeError, ValueError):
            act_i = -1
        try:
            lo = float(ev.get("zone_lower") if ev.get("zone_lower") is not None else np.nan)
        except (TypeError, ValueError):
            lo = float("nan")
        events.append(
            {
                "wpbr_zone_id": str(ev.get("wpbr_zone_id") or ""),
                "activation_bar": act_i,
                "zone_lower": lo,
            }
        )
    return sym, events


def build_zone_inventory(prices: dict[str, pd.DataFrame]) -> dict[str, list[dict[str, Any]]]:
    inv: dict[str, list[dict[str, Any]]] = {}
    items = list(prices.items())
    n = len(items)
    t0 = time.perf_counter()
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = [pool.submit(_events_for_df, sym, df) for sym, df in items]
        for fut in as_completed(futs):
            sym, events = fut.result()
            inv[sym] = events
            done += 1
            if done % 50 == 0 or done == n:
                print(f"  zones {done}/{n}  {time.perf_counter() - t0:.1f}s", flush=True)
    return inv


def pack_symbol(events: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray, list[str]]:
    ids = [str(e.get("wpbr_zone_id") or "") for e in events]
    born = np.array([int(e.get("activation_bar") if e.get("activation_bar") is not None else -1) for e in events], dtype=np.int32)
    lo = np.array([float(e.get("zone_lower", np.nan)) for e in events], dtype=np.float64)
    return born, lo, ids


def classify_trade(
    t: dict[str, Any],
    prices: dict[str, pd.DataFrame],
    packed: dict[str, tuple[np.ndarray, np.ndarray, list[str]]],
) -> dict[str, Any]:
    opened = t.get("opened")
    sl = "IS" if opened and opened < IS_CUT else "OOS"
    out = {**t, "slice": sl, "group": UNCL, "nearest_gap": None, "unclassified_reason": ""}
    sym = t.get("symbol") or ""
    df = prices.get(sym)
    zid = t.get("wpbr_zone_id") or ""
    upper = t.get("zone_top")
    if df is None or df.empty:
        out["unclassified_reason"] = "no_prices"
        return out
    if not np.isfinite(upper) or float(upper) <= 0:
        out["unclassified_reason"] = "no_zone_top"
        return out
    opened_i = _bar_index(df, opened)
    if opened_i is None:
        out["unclassified_reason"] = "open_date_not_in_bars"
        return out
    trigger_bar = int(opened_i) - 1
    if trigger_bar < 0:
        out["unclassified_reason"] = "no_trigger_bar"
        return out
    born, lo, ids = packed.get(sym, (np.zeros(0, dtype=np.int32), np.zeros(0, dtype=np.float64), []))
    gap = prior_overhead_nearest_gap(
        born,
        lo,
        ids,
        active_id=zid,
        active_upper=float(upper),
        trigger_bar=trigger_bar,
    )
    out["nearest_gap"] = gap
    out["trigger_bar"] = trigger_bar
    if gap is None:
        out["group"] = G1
        return out
    if float(gap) > OH_BAND:
        out["group"] = G2
        return out
    out["group"] = LEAK
    out["unclassified_reason"] = f"gap_{float(gap):.6f}_le_{OH_BAND}"
    return out


def duration_stats(trades: list[dict[str, Any]]) -> dict[str, float]:
    days = [float(t["days"]) for t in trades if np.isfinite(t.get("days", np.nan))]
    empty = {k: float("nan") for k in ("p25", "p50", "p75", "p90", "p95", "max", "n")}
    empty["n"] = 0.0
    if not days:
        return empty
    a = np.asarray(days, dtype=np.float64)
    return {
        "n": float(a.size),
        "p25": float(np.percentile(a, 25)),
        "p50": float(np.percentile(a, 50)),
        "p75": float(np.percentile(a, 75)),
        "p90": float(np.percentile(a, 90)),
        "p95": float(np.percentile(a, 95)),
        "max": float(np.max(a)),
    }


def _fix_calmar(m: dict[str, Any]) -> dict[str, Any]:
    ann = m.get("ann_ror")
    dd = m.get("max_dd")
    cal = calmar_ratio(ann, dd) if calmar_ratio is not None else None
    m = dict(m)
    m["calmar"] = float(cal) if cal is not None else float("nan")
    return m


METRIC_SPECS = [
    ("N", "n", "n"),
    ("% of slice closed trades", "pct_of_slice", "pct"),
    ("WR", "wr", "pct"),
    ("Avg P&L %", "avg_pnl_pct", "pct"),
    ("PF", "pf", "num2"),
    ("Avg Winner %", "avg_win_pct", "pct"),
    ("Avg Loser %", "avg_loss_pct", "pct"),
    ("Max DD", "max_dd", "pct"),
    ("Ann ROR", "ann_ror", "pct"),
    ("Calmar", "calmar", "num2"),
    ("Sharpe", "sharpe", "num2"),
    ("Avg Days Held", "avg_days", "num1"),
    ("Median Days Held", "median_days", "num1"),
    ("Capital Days", "capital_days", "n"),
    ("PPCD", "ppcd", "money"),
    ("Trades/Year", "trades_per_year", "num2"),
]


def cell(m: dict[str, Any], key: str, kind: str) -> str:
    v = m.get(key)
    if kind == "n":
        return fmt_n(v)
    if kind == "pct":
        return fmt_pct(v)
    if kind == "num1":
        return fmt_num(v, 1)
    if kind == "num2":
        return fmt_num(v, 2)
    if kind == "money":
        if v is None or (isinstance(v, float) and not math.isfinite(v)):
            return "—"
        return format_money(v)
    return fmt_num(v, 2)


def table_metrics(title: str, cols: list[tuple[str, dict[str, Any]]]) -> str:
    head = "".join([sortable_th("Metric", "text"), *[sortable_th(name, "num") for name, _ in cols]])
    body = []
    for label, key, kind in METRIC_SPECS:
        tds = [f"<td>{html_mod.escape(label)}</td>"]
        for _, m in cols:
            tds.append(f"<td>{cell(m, key, kind)}</td>")
        body.append("<tr>" + "".join(tds) + "</tr>")
    return (
        f"<h2>{title}</h2>{SWIPE_NOTE_HTML}"
        f"<p class=\"sub\">Click column headers to sort.</p>"
        f"<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def table_hold(title: str, rows: list[tuple[str, dict[str, float]]]) -> str:
    keys = [
        ("N with days", "n", "n"),
        ("P25", "p25", "num1"),
        ("P50", "p50", "num1"),
        ("P75", "p75", "num1"),
        ("P90", "p90", "num1"),
        ("P95", "p95", "num1"),
        ("Max Days Held", "max", "num1"),
    ]
    head = "".join([sortable_th("Group", "text"), *[sortable_th(lab, "num") for lab, _, _ in keys]])
    body = []
    for name, st in rows:
        tds = [f"<td>{html_mod.escape(name)}</td>"]
        for _, k, kind in keys:
            tds.append(f"<td>{cell(st, k, kind)}</td>")
        body.append("<tr>" + "".join(tds) + "</tr>")
    return (
        f"<h2>{title}</h2>{SWIPE_NOTE_HTML}"
        f"<p class=\"sub\">Days Held is the closed-file calendar DAYS_HELD. Click headers to sort.</p>"
        f"<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def table_recon(title: str, rows: list[tuple[str, int, int]]) -> str:
    head = (
        sortable_th("Bucket", "text")
        + sortable_th("N", "num")
        + sortable_th("% of slice", "num")
    )
    body = []
    for name, n, den in rows:
        pct = (100.0 * n / den) if den else 0.0
        cls = " class=\"total-row\"" if name.lower().startswith("sum") else ""
        body.append(
            f"<tr{cls}><td>{html_mod.escape(name)}</td><td>{n}</td><td>{pct:.2f}%</td></tr>"
        )
    return (
        f"<h2>{title}</h2>{SWIPE_NOTE_HTML}"
        f"<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def write_outputs(
    classified: list[dict[str, Any]],
    *,
    brt_cash: float,
    initial_account: float,
) -> None:
    n_closed = len(classified)
    OUT.mkdir(parents=True, exist_ok=True)

    def pick(sl: str, group: str | None) -> list[dict[str, Any]]:
        rows = classified if sl == "FULL" else [t for t in classified if t.get("slice") == sl]
        if group:
            rows = [t for t in rows if t.get("group") == group]
        return rows

    years = {
        "FULL": slice_years(classified),
        "IS": slice_years([t for t in classified if t.get("slice") == "IS"]),
        "OOS": slice_years([t for t in classified if t.get("slice") == "OOS"]),
    }
    blocks: dict[str, dict[str, dict[str, Any]]] = {}
    holds: dict[str, dict[str, dict[str, float]]] = {}
    for g in (G1, G2, LEAK, UNCL, "ALL"):
        blocks[g] = {}
        holds[g] = {}
        for sl in ("FULL", "IS", "OOS"):
            slice_all = pick(sl, None)
            rows = slice_all if g == "ALL" else pick(sl, g)
            m = metrics_for(
                rows,
                brt_cash=brt_cash,
                initial_account=initial_account,
                pct_base=len(slice_all) or 1,
                slice_span_years=years[sl],
            )
            blocks[g][sl] = _fix_calmar(m)
            holds[g][sl] = duration_stats(rows)

    recon: dict[str, dict[str, int]] = {}
    for sl in ("FULL", "IS", "OOS"):
        bucket = pick(sl, None)
        c = defaultdict(int)
        for t in bucket:
            c[t["group"]] += 1
        recon[sl] = {
            G1: c[G1],
            G2: c[G2],
            LEAK: c[LEAK],
            UNCL: c[UNCL],
            "SUM12": c[G1] + c[G2],
            "SUM_ALL": c[G1] + c[G2] + c[LEAK] + c[UNCL],
            "ALL": len(bucket),
        }
    recon_ok = recon["FULL"]["SUM12"] == n_closed and recon["FULL"][LEAK] == 0 and recon["FULL"][UNCL] == 0

    with (OUT / "classified_trades.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "symbol", "opened", "slice", "group", "nearest_gap_frac",
                "nearest_gap_pct", "pnl", "exit", "days_held", "pnl_dollars",
                "zone_top", "wpbr_zone_id", "trigger_bar", "unclassified_reason", "closed",
            ],
        )
        w.writeheader()
        for t in classified:
            g = t.get("nearest_gap")
            w.writerow({
                "symbol": t.get("symbol"),
                "opened": _iso(t.get("opened")),
                "slice": t.get("slice"),
                "group": t.get("group"),
                "nearest_gap_frac": "" if g is None else g,
                "nearest_gap_pct": "" if g is None else 100.0 * float(g),
                "pnl": t.get("pnl_pct"),
                "exit": t.get("exit"),
                "days_held": t.get("days"),
                "pnl_dollars": t.get("pnl_d"),
                "zone_top": t.get("zone_top"),
                "wpbr_zone_id": t.get("wpbr_zone_id"),
                "trigger_bar": t.get("trigger_bar"),
                "unclassified_reason": t.get("unclassified_reason"),
                "closed": _iso(t.get("closed")),
            })

    with (OUT / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        keys = [k for _, k, _ in METRIC_SPECS] + ["p25", "p50", "p75", "p90", "p95", "max_days"]
        w = csv.DictWriter(f, fieldnames=["group", "slice", *keys])
        w.writeheader()
        for g in (G1, G2, LEAK, UNCL, "ALL"):
            for sl in ("FULL", "IS", "OOS"):
                row = {"group": g, "slice": sl}
                row.update({k: blocks[g][sl].get(k) for _, k, _ in METRIC_SPECS})
                d = holds[g][sl]
                row["p25"] = d["p25"]
                row["p50"] = d["p50"]
                row["p75"] = d["p75"]
                row["p90"] = d["p90"]
                row["p95"] = d["p95"]
                row["max_days"] = d["max"]
                w.writerow(row)

    (OUT / "BASELINE.md").write_text(
        "\n".join([
            "# WPBR overhead-existence diagnostic (22% control)",
            "",
            "## What you asked",
            REQUEST_QUOTE,
            "",
            "## In plain English",
            "The live book already skips a buy when an older weekly Pivot Break and Retest (WPBR) ",
            "band sits within 22% overhead. This page only splits the trades that were actually taken: ",
            "clear sky (no older WPBR band above at all) vs a WPBR band above that is far enough ",
            "(gap > 22%) that the skip did not fire. No new filter.",
            "",
            "## Freeze",
            f"- Closed: `{CLOSED}`",
            "- Qualifying overhead = engine `prior_overhead_nearest_gap`: earlier zone ",
            "  (`activation_bar` < trigger bar), `zone_lower` strictly above active `ZONE_TOP`, ",
            "  gap = (lower − upper) / upper.",
            "- Live exclusion blocks when that count inside `max_gap=0.22` is > 0, i.e. gap **≤ 22%**.",
            "- Group 2 is therefore nearest gap **> 22%** (does not trigger the skip).",
            "- Trigger bar = session before `DATE_OPENED` (next-open fill).",
            "- IS = entry before 2024-01-01. OOS report-only.",
            f"- Ann ROR house formula, `capacity_brt_cash={brt_cash}`.",
            "- Max DD / Sharpe: closed overlay (exit-date equity), not the full-book EquityCurve.",
            "",
            f"- Closed N: {n_closed}",
            f"- Group1+Group2 = closed: {'YES' if recon_ok else 'NO'}",
            f"- Leak gap≤22%: {recon['FULL'][LEAK]}",
            f"- Unclassified: {recon['FULL'][UNCL]}",
            "",
            "Not gold. Not DailyRun. No 22% retune.",
            "",
        ]),
        encoding="utf-8",
    )

    g1f, g2f = blocks[G1]["FULL"], blocks[G2]["FULL"]
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
{CACHE_META}
<title>WPBR overhead existence diagnostic</title>
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 16px; color: #1e293b; background: #f8fafc; }}
h1 {{ font-size: 22px; }}
.callout {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px 14px; margin: 12px 0 18px; }}
.callout pre {{ white-space: pre-wrap; font-family: Georgia, serif; font-size: 13px; }}
.sub {{ color: #64748b; font-size: 13px; }}
table.sortable {{ border-collapse: collapse; background: #fff; font-size: 13px; }}
th, td {{ border: 1px solid #e2e8f0; padding: 5px 8px; text-align: right; }}
th:first-child, td:first-child {{ text-align: left; }}
tr.total-row {{ font-weight: 700; background: #f1f5f9; }}
{SORTABLE_TH_CSS}{RESPONSIVE_TABLE_CSS}
</style>
{FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>Pivot Break and Retest (WPBR) — overhead existence on the 22% control book</h1>
<p class="sub">Classification only. Stamp 261002172253. Not a filter. Not DailyRun.</p>
<div class="callout">
<h2>What you asked</h2>
<pre>{html_mod.escape(REQUEST_QUOTE)}</pre>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>Weekly Pivot Break and Retest (WPBR) already refuses a buy when an older weekly band sits within 22% overhead. This page does not change that. It only splits the trades the book actually took into two piles: <strong>no older WPBR band above at all</strong>, versus <strong>an older WPBR band above, but far enough (&gt;22%) that the skip did not fire</strong>. Then we ask whether those two piles hold for different lengths of time and make different quality trades, on the full book, before 2024 (in-sample), and from 2024 on (out-of-sample).</p>
<p>A qualifying overhead zone is the live definition: an earlier WPBR zone whose lower edge is strictly above this zone’s upper edge. Distance is (lower − upper) / upper. The live skip fires at gap ≤ 22%, so Group 2 is nearest gap <strong>&gt; 22%</strong>. No extra distance bins.</p>
</div>
<div class="callout">
<p>Closed N = {n_closed}. Group 1 + Group 2 = closed book: <strong>{"YES" if recon_ok else "NO"}</strong>
(leak gap≤22% = {recon["FULL"][LEAK]}, unclassified = {recon["FULL"][UNCL]}).</p>
<p>FULL: no-overhead N={g1f["n"]:,} avg days {fmt_num(g1f["avg_days"],1)} vs overhead&gt;22% N={g2f["n"]:,} avg days {fmt_num(g2f["avg_days"],1)}.
Avg P&amp;L {fmt_pct(g1f["avg_pnl_pct"])} vs {fmt_pct(g2f["avg_pnl_pct"])}.
Ann ROR {fmt_pct(g1f["ann_ror"])} vs {fmt_pct(g2f["ann_ror"])}.</p>
<p>Annualized rate of return (Ann ROR) uses the house formula and Report capacity slot cash. Max DD / Sharpe are group overlay curves from exit dates, not the full-book EquityCurve.</p>
</div>
{table_metrics("FULL", [(GROUP_LABELS[G1], blocks[G1]["FULL"]), (GROUP_LABELS[G2], blocks[G2]["FULL"]), ("All closed", blocks["ALL"]["FULL"])])}
{table_metrics("IS (entry before 2024-01-01)", [(GROUP_LABELS[G1], blocks[G1]["IS"]), (GROUP_LABELS[G2], blocks[G2]["IS"]), ("All IS", blocks["ALL"]["IS"])])}
{table_metrics("OOS (entry on/after 2024-01-01) — report only", [(GROUP_LABELS[G1], blocks[G1]["OOS"]), (GROUP_LABELS[G2], blocks[G2]["OOS"]), ("All OOS", blocks["ALL"]["OOS"])])}
{table_hold("Holding duration — FULL", [(GROUP_LABELS[G1], holds[G1]["FULL"]), (GROUP_LABELS[G2], holds[G2]["FULL"]), ("All closed", holds["ALL"]["FULL"])])}
{table_hold("Holding duration — IS", [(GROUP_LABELS[G1], holds[G1]["IS"]), (GROUP_LABELS[G2], holds[G2]["IS"])])}
{table_hold("Holding duration — OOS", [(GROUP_LABELS[G1], holds[G1]["OOS"]), (GROUP_LABELS[G2], holds[G2]["OOS"])])}
{table_recon("Reconciliation — FULL", [
    (GROUP_LABELS[G1], recon["FULL"][G1], n_closed),
    (GROUP_LABELS[G2], recon["FULL"][G2], n_closed),
    (GROUP_LABELS[LEAK], recon["FULL"][LEAK], n_closed),
    (GROUP_LABELS[UNCL], recon["FULL"][UNCL], n_closed),
    ("Sum Group 1 + Group 2 (should equal closed book)", recon["FULL"]["SUM12"], n_closed),
    ("Closed book", n_closed, n_closed),
])}
{table_recon("Reconciliation — IS", [
    (GROUP_LABELS[G1], recon["IS"][G1], recon["IS"]["ALL"]),
    (GROUP_LABELS[G2], recon["IS"][G2], recon["IS"]["ALL"]),
    ("Sum G1+G2", recon["IS"]["SUM12"], recon["IS"]["ALL"]),
    ("IS closed", recon["IS"]["ALL"], recon["IS"]["ALL"]),
])}
{table_recon("Reconciliation — OOS", [
    (GROUP_LABELS[G1], recon["OOS"][G1], recon["OOS"]["ALL"]),
    (GROUP_LABELS[G2], recon["OOS"][G2], recon["OOS"]["ALL"]),
    ("Sum G1+G2", recon["OOS"]["SUM12"], recon["OOS"]["ALL"]),
    ("OOS closed", recon["OOS"]["ALL"], recon["OOS"]["ALL"]),
])}
<p class="sub">Artifacts in this folder: BASELINE.md, summary.csv, classified_trades.csv.</p>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    html_path = OUT / "compare.html"
    html_path.write_text(inject_report_page_extras(html), encoding="utf-8")
    print(f"recon_ok={recon_ok} g1={recon['FULL'][G1]} g2={recon['FULL'][G2]} leak={recon['FULL'][LEAK]} uncl={recon['FULL'][UNCL]}", flush=True)
    print(f"wrote {html_path}", flush=True)
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "ntfy_job_done.py"),
            "--path",
            str(html_path),
            "-t",
            "WPBR overhead existence",
        ],
        cwd=str(ROOT),
        check=False,
    )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print("loading closed + report", flush=True)
    trades = load_closed(CLOSED)
    brt_cash, initial_account = load_report_cash(REPORT)
    print(f"closed={len(trades)} cash={brt_cash} workers={WORKERS}", flush=True)
    symbols = sorted({t["symbol"] for t in trades if t["symbol"]})
    t0 = time.perf_counter()
    prices = load_prices(symbols)
    print(f"prices {len(prices)}/{len(symbols)} in {time.perf_counter()-t0:.1f}s", flush=True)
    print("rebuilding WPBR zone inventories", flush=True)
    t1 = time.perf_counter()
    inventory = build_zone_inventory(prices)
    packed = {sym: pack_symbol(ev) for sym, ev in inventory.items()}
    print(f"zones done {time.perf_counter()-t1:.1f}s", flush=True)
    classified = [classify_trade(t, prices, packed) for t in trades]
    write_outputs(classified, brt_cash=brt_cash, initial_account=initial_account)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
