#!/usr/bin/env python3
"""ENTRY overlay A/B: alternative *readings* of the same as-of trendline.

Control = all house Closed fills as taken (no chart filter).
Candidates = one-change keep/skip rules on the **same** prior-bar geometry
used by ``trendline_entry_filter_ab_20260915`` / live ``trendlines_score_live``.

Does not change DailyRun, entry/exit freezes, or live buy-today (still 2% B).
Features are computed once; arms are scored in a second pass.

Usage:
  python tools/trendline_read_ab_20260915.py
  python tools/trendline_read_ab_20260915.py --workers 8
  python tools/trendline_read_ab_20260915.py --features-only
  python tools/trendline_read_ab_20260915.py --from-features
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import math
import os
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    filter_html_compare_columns,
    format_money,
    format_money_delta,
)
from dailyrun_system_status import live_wired_systems  # noqa: E402
from trendline_entry_filter_ab_20260915 import (  # noqa: E402
    SORT_CSS,
    SORT_JS,
    _worker,
    book_stats,
    empty_geom,
    fmt_delta,
    fmt_n,
    load_closed_fills,
    sortable_th,
    split_is_oos,
)
from trendlines_score_live import PROX_PCT  # noqa: E402

DRIVE = ROOT / "drive"
STAMP = "trendline_read_ab_20260915"
OUT_DIR = DRIVE / "paul_experiments" / STAMP
IS_CUT = date(2024, 1, 1)
INIT_ACCT = DEFAULT_INITIAL_ACCOUNT
FILL_CASH = 10_000.0  # size-aware overlay: $10k / fill
PRIOR_STAMP = "trendline_entry_filter_ab_20260915"

ORIGINAL_REQUEST = (
    "can you run some AB tests to make your reading of the charts better "
    "so that we can see them add value to our existing process?"
)
LAYMAN = (
    "The last overlay (buy only if weekly support is rising and price is "
    "within 2% of the line) sat out 96% of fills and did not improve Avg%. "
    "Paul wants different readings of the same charts — one change at a "
    "time — to find a filter that actually helps the book we already take, "
    "not a second system. Control is every fill as booked. Each candidate "
    "keeps or skips that same fill using only the trendline picture at the "
    "last complete bar before the open (no peeking at the purchase day). "
    "In-sample is entries before 2024; later years are a check only — we "
    "do not retune on them. This is research, not a live DailyRun gate."
)

# style: veto = skip only the ugly ones (missing line / no data → keep)
#        keep  = require a positive reading (missing / no data → sit out)
KeepFn = Callable[[dict[str, Any]], bool]


def _finite(v: Any) -> bool:
    try:
        return v is not None and math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def keep_skip_broken_weekly(f: dict[str, Any]) -> bool:
    """Skip if weekly support DOWN or close >2% through support. Else keep."""
    if f.get("nodata"):
        return True
    if str(f.get("w_sup") or "").upper() == "DOWN":
        return False
    if _finite(f.get("w_dist")) and float(f["w_dist"]) < -PROX_PCT:
        return False
    return True


def keep_skip_through_support(f: dict[str, Any]) -> bool:
    """Skip if close is through weekly support (any slope). Else keep."""
    if f.get("nodata"):
        return True
    if _finite(f.get("w_dist")) and float(f["w_dist"]) < 0.0:
        return False
    return True


def keep_weekly_up(f: dict[str, Any]) -> bool:
    if f.get("nodata"):
        return False
    return str(f.get("w_sup") or "").upper() == "UP"


def keep_prox(band: float) -> KeepFn:
    def _fn(f: dict[str, Any]) -> bool:
        if f.get("nodata"):
            return False
        if str(f.get("w_sup") or "").upper() != "UP":
            return False
        if not _finite(f.get("w_dist")):
            return False
        return abs(float(f["w_dist"])) <= band

    return _fn


def keep_daily_up(f: dict[str, Any]) -> bool:
    if f.get("nodata"):
        return False
    return str(f.get("d_sup") or "").upper() == "UP"


def keep_skip_extended(band: float) -> KeepFn:
    def _fn(f: dict[str, Any]) -> bool:
        if f.get("nodata"):
            return True
        if _finite(f.get("w_dist")) and float(f["w_dist"]) > band:
            return False
        return True

    return _fn


ARMS: list[tuple[str, str, KeepFn, str]] = [
    (
        "SKIP_broken_weekly",
        "veto",
        keep_skip_broken_weekly,
        "Skip only if weekly support is DOWN or close is more than 2% through "
        "weekly support. Inverse of buy-low B (veto the ugly ones; keep the rest).",
    ),
    (
        "SKIP_through_support",
        "veto",
        keep_skip_through_support,
        "Skip only if close is through weekly support (distance < 0), any slope.",
    ),
    (
        "KEEP_weekly_up",
        "keep",
        keep_weekly_up,
        "Keep if weekly support is UP; drop the 2% proximity band.",
    ),
    (
        "KEEP_prox5",
        "keep",
        keep_prox(5.0),
        "Buy-low B with a 5% band: weekly support UP and |dist| ≤ 5%.",
    ),
    (
        "KEEP_prox8",
        "keep",
        keep_prox(8.0),
        "Buy-low B with an 8% band: weekly support UP and |dist| ≤ 8%.",
    ),
    (
        "KEEP_daily_up",
        "keep",
        keep_daily_up,
        "Keep if daily support is UP (not weekly). One-timeframe change.",
    ),
    (
        "SKIP_extended10",
        "veto",
        keep_skip_extended(10.0),
        "Skip if close is more than 10% above weekly support (do not chase).",
    ),
]


def attach_overlay_dollars(fills: list[dict[str, Any]]) -> None:
    for t in fills:
        pnl = float(t.get("pnl") or 0.0)
        t["pnl_d"] = FILL_CASH * pnl / 100.0
        t["cash"] = FILL_CASH


def features_path() -> Path:
    return OUT_DIR / "features.csv"


def dump_features(fills: list[dict[str, Any]]) -> None:
    rows = []
    for t in fills:
        rows.append(
            {
                "system": t["system"],
                "sym": t["sym"],
                "opened": t["opened"].isoformat() if t.get("opened") else "",
                "closed": t["closed"].isoformat() if t.get("closed") else "",
                "entry": t.get("entry"),
                "pnl": t.get("pnl"),
                "pnl_d": t.get("pnl_d"),
                "days": t.get("days"),
                "exit": t.get("exit"),
                "side": t.get("side"),
                "dup": int(bool(t.get("dup"))),
                "asof": t.get("asof") or "",
                "asof_close": t.get("asof_close"),
                "w_sup": t.get("w_sup") or "",
                "d_sup": t.get("d_sup") or "",
                "m_sup": t.get("m_sup") or "",
                "w_dist": t.get("w_dist"),
                "d_dist": t.get("d_dist"),
                "w_res_dist": t.get("w_res_dist"),
                "live_verdict": t.get("live_verdict") or "",
                "nodata": int(bool(t.get("nodata"))),
            }
        )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(features_path(), index=False)


def load_features_csv() -> list[dict[str, Any]]:
    path = features_path()
    df = pd.read_csv(path)
    out: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        opened = pd.to_datetime(row.get("opened"), errors="coerce")
        closed = pd.to_datetime(row.get("closed"), errors="coerce")
        rec = {
            "system": str(row.get("system") or "").strip().upper(),
            "sym": str(row.get("sym") or "").strip().upper(),
            "opened": opened.date() if pd.notna(opened) else None,
            "closed": closed.date() if pd.notna(closed) else None,
            "entry": float(row["entry"]) if _finite(row.get("entry")) else float("nan"),
            "pnl": float(row["pnl"]) if _finite(row.get("pnl")) else 0.0,
            "days": float(row["days"]) if _finite(row.get("days")) else 1.0,
            "exit": str(row.get("exit") or "—"),
            "side": str(row.get("side") or "LONG"),
            "dup": bool(int(row.get("dup") or 0)),
            "asof": "" if pd.isna(row.get("asof")) else str(row.get("asof") or ""),
            "asof_close": float(row["asof_close"]) if _finite(row.get("asof_close")) else float("nan"),
            "w_sup": "" if pd.isna(row.get("w_sup")) else str(row.get("w_sup") or ""),
            "d_sup": "" if pd.isna(row.get("d_sup")) else str(row.get("d_sup") or ""),
            "m_sup": "" if pd.isna(row.get("m_sup")) else str(row.get("m_sup") or ""),
            "w_dist": float(row["w_dist"]) if _finite(row.get("w_dist")) else float("nan"),
            "d_dist": float(row["d_dist"]) if _finite(row.get("d_dist")) else float("nan"),
            "w_res_dist": float(row["w_res_dist"]) if _finite(row.get("w_res_dist")) else float("nan"),
            "live_verdict": "" if pd.isna(row.get("live_verdict")) else str(row.get("live_verdict") or ""),
            "nodata": bool(int(row.get("nodata") or 0)),
            "cash": FILL_CASH,
        }
        rec["pnl_d"] = FILL_CASH * rec["pnl"] / 100.0
        if rec["opened"] is None or not rec["sym"]:
            continue
        out.append(rec)
    return out


def score_fills(fills: list[dict[str, Any]], workers: int, max_symbols: int = 0) -> None:
    by_sym: dict[str, set[str]] = defaultdict(set)
    for t in fills:
        by_sym[t["sym"]].add(t["opened"].isoformat())
    payloads = [(sym, sorted(dates)) for sym, dates in sorted(by_sym.items())]
    if max_symbols and max_symbols > 0:
        keep_syms = {s for s, _ in payloads[:max_symbols]}
        payloads = [p for p in payloads if p[0] in keep_syms]
        fills[:] = [t for t in fills if t["sym"] in keep_syms]

    scores: dict[str, dict[str, dict[str, Any]]] = {}
    print(f"[read_ab] scoring {len(payloads)} symbols, {len(fills)} fills, workers={workers}")
    if workers <= 1:
        for p in payloads:
            sym, rec = _worker(p)
            scores[sym] = rec
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_worker, p): p[0] for p in payloads}
            done = 0
            for fut in as_completed(futs):
                sym, rec = fut.result()
                scores[sym] = rec
                done += 1
                if done % 50 == 0 or done == len(futs):
                    print(f"[read_ab] scored {done}/{len(futs)}", flush=True)

    for t in fills:
        rec = (scores.get(t["sym"]) or {}).get(t["opened"].isoformat()) or empty_geom()
        t["asof"] = rec.get("asof") or ""
        t["asof_close"] = rec.get("asof_close")
        t["w_sup"] = rec.get("w_sup") or ""
        t["d_sup"] = rec.get("d_sup") or ""
        t["m_sup"] = rec.get("m_sup") or ""
        t["w_dist"] = rec.get("w_dist")
        t["d_dist"] = rec.get("d_dist")
        t["w_res_dist"] = rec.get("w_res_dist")
        v = str(rec.get("verdict") or "NO DATA")
        t["live_verdict"] = v
        t["nodata"] = v in ("NO DATA", "NO CHART")


def decide_verdict(ctrl_is: dict, filt_is: dict, ctrl_oos: dict, filt_oos: dict) -> tuple[str, str]:
    """Quality over count. OOS report-only. Picking a winner here is IS selection."""
    notes = [
        "in-sample selection if this arm is picked from the new table — research overlay"
    ]
    n_ctrl = ctrl_is["n"]
    n_filt = filt_is["n"]
    keep_frac = (n_filt / n_ctrl) if n_ctrl else 0.0
    n_collapse = n_ctrl >= 30 and (keep_frac < 0.30 or n_filt < 40)
    d_avg = filt_is["avg_pnl"] - ctrl_is["avg_pnl"]
    d_wo = filt_is["wo_max"] - ctrl_is["wo_max"]
    d_wr = filt_is["wr"] - ctrl_is["wr"]
    d_ann = (
        filt_is["ann_ror"] - ctrl_is["ann_ror"]
        if math.isfinite(filt_is["ann_ror"]) and math.isfinite(ctrl_is["ann_ror"])
        else float("nan")
    )
    oos_soft = False
    if ctrl_oos["n"] >= 20 and filt_oos["n"] >= 20:
        oos_soft = (filt_oos["avg_pnl"] < ctrl_oos["avg_pnl"] - 0.15) or (
            math.isfinite(filt_oos["ann_ror"])
            and math.isfinite(ctrl_oos["ann_ror"])
            and filt_oos["ann_ror"] < ctrl_oos["ann_ror"] - 1.0
        )
        notes.append(
            f"OOS ΔAvg {filt_oos['avg_pnl'] - ctrl_oos['avg_pnl']:+.2f}pp"
            + (" — softened" if oos_soft else "")
        )
    else:
        notes.append("OOS thin — report-only")
    notes.append(f"IS kept {n_filt}/{n_ctrl} ({100 * keep_frac:.0f}%) ΔAvg {d_avg:+.2f}pp")
    if n_collapse:
        notes.append("N collapsed — cannot KEEP a reading that sits out most of the book")
        return "HOLD", "; ".join(notes)
    if oos_soft:
        notes.append("OOS softened — do not retune")
        return "HOLD", "; ".join(notes)
    better = (d_avg > 0.15 and d_wo > -0.05) or (
        math.isfinite(d_ann) and d_ann > 1.0 and d_avg > -0.05 and d_wr > -1.0
    )
    worse = d_avg < -0.15 and d_wo < 0
    if worse:
        return "DISMISS", "; ".join(notes)
    if better:
        notes.append("IS quality up without N collapse — still research-only, not DailyRun")
        return "LEAN KEEP", "; ".join(notes)
    notes.append("flat/mixed quality")
    return "HOLD", "; ".join(notes)


def metric_rows_multi(
    ctrl: dict[str, Any],
    arms: list[tuple[str, dict[str, Any]]],
) -> list[list[str]]:
    """Rows of [metric, control, arm1, Δ1, arm2, Δ2, ...]."""

    def dlt(a: Any, b: Any) -> Any:
        try:
            return float(b) - float(a)
        except (TypeError, ValueError):
            return float("nan")

    specs: list[tuple[str, str, Any]] = [
        ("Total trades", "n", "int"),
        ("Wins", "wins", "int"),
        ("Losses", "losses", "int"),
        ("Win %", "wr", "num"),
        ("Avg PnL %", "avg_pnl", "num"),
        ("Book AVG_PNL_PCT_WO_MAX", "wo_max", "num"),
        ("Expectancy %", "exp_pct", "num"),
        ("Avg win %", "avg_win", "num"),
        ("Avg loss %", "avg_loss", "num"),
        ("Win/Loss ratio (count)", "wl_count", "num"),
        ("Win/Loss ratio $", "wl_dollar", "num"),
        ("Profit factor", "pf", "num"),
        ("Ann ROR %", "ann_ror", "num"),
        ("Max DD %", "max_dd", "num"),
        ("Calmar", "calmar", "num"),
        ("Sharpe", "sharpe", "num"),
        ("Capital days", "capital_days", "int"),
        ("Avg days held", "avg_days", "num1"),
        ("Median days held", "med_days", "num1"),
        ("P90 days held", "p90_days", "num1"),
        ("Losing streak", "losing_streak", "int"),
    ]
    rows: list[list[str]] = []
    for label, key, kind in specs:
        cv = ctrl[key]
        if kind == "int":
            cells = [label, str(int(cv) if _finite(cv) else 0)]
        elif kind == "num1":
            cells = [label, fmt_n(cv, 1)]
        else:
            cells = [label, fmt_n(cv)]
        for _name, st in arms:
            av = st[key]
            if kind == "int":
                cells.append(str(int(av) if _finite(av) else 0))
                cells.append(str(int(av - cv) if _finite(av) and _finite(cv) else 0))
            elif kind == "num1":
                cells.append(fmt_n(av, 1))
                cells.append(fmt_delta(dlt(cv, av), 1))
            else:
                cells.append(fmt_n(av))
                cells.append(fmt_delta(dlt(cv, av)))
        rows.append(cells)

    # Money rows (absolute + delta via helpers; Total/Sheet PnL omitted)
    exp_c = (ctrl["pnl_d"] / ctrl["n"]) if ctrl["n"] else None
    cells = ["Expectancy $", format_money(exp_c)]
    for _name, st in arms:
        exp_a = (st["pnl_d"] / st["n"]) if st["n"] else None
        cells.append(format_money(exp_a))
        cells.append(format_money_delta((exp_a or 0) - (exp_c or 0) if exp_a is not None and exp_c is not None else None))
    rows.append(cells)

    cells = ["Profit per capital day", format_money(ctrl["ppc"])]
    for _name, st in arms:
        cells.append(format_money(st["ppc"]))
        cells.append(
            format_money_delta(
                (st["ppc"] - ctrl["ppc"])
                if _finite(st["ppc"]) and _finite(ctrl["ppc"])
                else None
            )
        )
    rows.append(cells)

    cells = ["Overlay $ (10k/fill)", format_money(ctrl["pnl_d"])]
    for _name, st in arms:
        cells.append(format_money(st["pnl_d"]))
        cells.append(format_money_delta(st["pnl_d"] - ctrl["pnl_d"]))
    rows.append(cells)
    return rows


def write_baseline(
    path: Path,
    *,
    pins: dict[str, str],
    sources: dict[str, str],
    combined: dict[str, Any],
    arm_results: list[dict[str, Any]],
    n_dup: int,
    n_nodata: int,
    n_wrl: int,
) -> None:
    ctrl = combined["ctrl_full"]
    lines = [
        f"# BASELINE — `{STAMP}`",
        "",
        "**Status:** Research overlay. **Not gold. Not DailyRun.** Do not wire as a live entry gate.",
        "",
        "## What you asked",
        "",
        f"> {ORIGINAL_REQUEST}",
        "",
        "## In plain English",
        "",
        LAYMAN,
        "",
        "## Why the last rule failed",
        "",
        f"`{PRIOR_STAMP}`: BEFORE N=8239 Avg% 5.90 → AFTER N=287 Avg% 5.37. **HOLD.** "
        "Too tight (buy-low B: weekly support UP and |dist| ≤ 2%). OOS also softened "
        "(ΔAvg −0.22pp). That rule sat out 96% of fills. This stamp tests *other* "
        "readings of the same as-of chart — one knob each.",
        "",
        "## Frozen knobs",
        "",
        "| Knob | Value |",
        "|------|-------|",
        "| Control | All Closed fills as taken (house exits unchanged) |",
        "| Geometry | Same as-of score as the prior stamp / live `trendlines_score_live.py` |",
        "| As-of bar | Last complete session **strictly before** `DATE_OPENED` |",
        "| Pivots | Daily k=5, weekly W-FRI k=3, monthly ME k=2; usable only after `confirmed_on` |",
        "| Live buy-today | Unchanged: weekly support UP and `|dist| ≤ 2%` (not an arm here) |",
        "| Universe | Wired DailyRun Closed (house pin for RSI / VZ). Not RSIN_PaulScore5_IS |",
        "| WRL | Research Weekly Range / Swing excluded from the book and from verdicts |",
        "| Overlay | **$10,000 per fill** (size-aware). Seed $500,000 for Max DD / Sharpe |",
        "| IS / OOS | entry < / ≥ 2024-01-01 (OOS **report-only**) |",
        "| Exit overlay | Not run (would need intra-hold rescoring; not cheap) |",
        "",
        "## Arms (one hypothesis, one knob)",
        "",
        "| Arm | Style | Rule |",
        "|-----|-------|------|",
        "| CONTROL | — | No chart filter |",
    ]
    for name, style, _fn, desc in ARMS:
        lines.append(f"| `{name}` | {style} | {desc} |")
    lines += [
        "",
        "## Pins",
        "",
    ]
    for k, v in pins.items():
        src = sources.get(k, "")
        lines.append(f"- **{k}:** `{v}` (`{src}`)")
    lines += [
        "",
        "## Label honesty",
        "",
        "- Choosing any winner from this table is **in-sample selection**, even if an OOS row is printed.",
        "- After a freeze, re-report IS/OOS under that freeze before any stronger claim.",
        "- Same-symbol / same-`DATE_OPENED` on two systems is counted twice and labeled (`dup`). "
        f"Double-count rows this run: **{n_dup}**.",
        f"- No-OHLC / no-prior-bar rows: **{n_nodata}**. Veto arms keep them; KEEP arms sit them out.",
        f"- Weekly Range / Swing (WRL) fills in this load: **{n_wrl}** (excluded).",
        "- Judge **quality** (WR, Avg%, expectancy, Ann ROR overlay, Max DD), not trade count.",
        "- KEEP / LEAN KEEP only if quality improves **without collapsing N** (<30% kept or IS N<40 → HOLD).",
        "- OOS softens → HOLD. Do not retune proximity bands on OOS.",
        "- Research candidate ≠ gold ≠ DailyRun. A LEAN KEEP would still need a new freeze, "
        "walk-forward or multi-universe confirmation, and an explicit DailyRun wire later.",
        "",
        "## Combined book ($10k/fill, honest double-count)",
        "",
        "| Arm | Verdict | N FULL | % kept | WR % | Avg % | ΔAvg FULL | N IS | ΔAvg IS | N OOS | ΔAvg OOS | Ann ROR % | Max DD % |",
        "|-----|---------|--------|--------|------|-------|-----------|------|---------|-------|----------|-----------|----------|",
        f"| CONTROL | — | {ctrl['n']} | 100 | {ctrl['wr']:.2f} | {ctrl['avg_pnl']:.2f} | — | "
        f"{combined['ctrl_is']['n']} | — | {combined['ctrl_oos']['n']} | — | "
        f"{ctrl['ann_ror']:.2f} | {ctrl['max_dd']:.2f} |",
    ]
    for rec in arm_results:
        cf, cis, coos = rec["full"], rec["is"], rec["oos"]
        d_full = cf["avg_pnl"] - ctrl["avg_pnl"]
        d_is = cis["avg_pnl"] - combined["ctrl_is"]["avg_pnl"]
        d_oos = coos["avg_pnl"] - combined["ctrl_oos"]["avg_pnl"]
        kept = (100.0 * cf["n"] / ctrl["n"]) if ctrl["n"] else 0.0
        lines.append(
            f"| `{rec['name']}` | **{rec['verdict']}** | {cf['n']} | {kept:.1f} | "
            f"{cf['wr']:.2f} | {cf['avg_pnl']:.2f} | {d_full:+.2f} | "
            f"{cis['n']} | {d_is:+.2f} | {coos['n']} | {d_oos:+.2f} | "
            f"{cf['ann_ror']:.2f} | {cf['max_dd']:.2f} |"
        )
    lines += [
        "",
        "### Notes (IS quality, OOS report-only)",
        "",
    ]
    for rec in arm_results:
        lines.append(f"- `{rec['name']}` **{rec['verdict']}**: {rec['note']}")
    lines += [
        "",
        "## What DailyRun would need later (if any arm LEAN KEEPs)",
        "",
        "Not wired. A later DailyRun gate would need: explicit freeze of the winning "
        "reading, reconcile / parity on the same Closed pins, walk-forward or a second "
        "universe, and a DailyRun.bat + registry change. Research stamps alone are not enough.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_html(
    path: Path,
    *,
    pins: dict[str, str],
    combined: dict[str, Any],
    arm_results: list[dict[str, Any]],
    per_sys: list[dict[str, Any]],
    n_dup: int,
    n_nodata: int,
    feat_counts: dict[str, Any],
) -> None:
    ctrl_full = combined["ctrl_full"]
    pin_bits = ", ".join(f"{k} {v}" for k, v in pins.items())

    score_heads = [
        ("Arm", "text"),
        ("Verdict", "text"),
        ("Split", "text"),
        ("N", "num"),
        ("% kept", "num"),
        ("Win %", "num"),
        ("Avg PnL %", "num"),
        ("Δ Avg %", "num"),
        ("WO_MAX %", "num"),
        ("Δ WO_MAX", "num"),
        ("PF", "num"),
        ("Ann ROR %", "num"),
        ("Δ Ann ROR", "num"),
        ("Max DD %", "num"),
        ("Δ Max DD", "num"),
        ("Calmar", "num"),
        ("Sharpe", "num"),
        ("Expectancy $", "num"),
        ("Avg days", "num"),
    ]
    score_heads = filter_html_compare_columns(score_heads)
    score_thead = "".join(sortable_th(l, t) for l, t in score_heads)
    score_body: list[str] = []

    def add_score_row(name: str, verdict: str, split: str, ctrl: dict, st: dict, is_ctrl: bool) -> None:
        tot = ctrl["n"]
        kept = (100.0 * st["n"] / tot) if tot else 0.0
        badge = verdict.split()[0] if verdict and verdict != "—" else "CONTROL"
        d_avg = st["avg_pnl"] - ctrl["avg_pnl"]
        d_wo = st["wo_max"] - ctrl["wo_max"]
        d_ann = (
            st["ann_ror"] - ctrl["ann_ror"]
            if math.isfinite(st["ann_ror"]) and math.isfinite(ctrl["ann_ror"])
            else float("nan")
        )
        d_dd = (
            st["max_dd"] - ctrl["max_dd"]
            if math.isfinite(st["max_dd"]) and math.isfinite(ctrl["max_dd"])
            else float("nan")
        )
        exp = (st["pnl_d"] / st["n"]) if st["n"] else None
        score_body.append(
            "<tr>"
            f"<td>{html_mod.escape(name)}</td>"
            f"<td><span class=\"badge {html_mod.escape(badge)}\">{html_mod.escape(verdict)}</span></td>"
            f"<td>{split}</td>"
            f"<td>{st['n']}</td>"
            f"<td>{'100.0' if is_ctrl else f'{kept:.1f}'}</td>"
            f"<td>{fmt_n(st['wr'])}</td>"
            f"<td>{fmt_n(st['avg_pnl'])}</td>"
            f"<td>{'—' if is_ctrl else fmt_delta(d_avg)}</td>"
            f"<td>{fmt_n(st['wo_max'])}</td>"
            f"<td>{'—' if is_ctrl else fmt_delta(d_wo)}</td>"
            f"<td>{fmt_n(st['pf'])}</td>"
            f"<td>{fmt_n(st['ann_ror'])}</td>"
            f"<td>{'—' if is_ctrl else fmt_delta(d_ann)}</td>"
            f"<td>{fmt_n(st['max_dd'])}</td>"
            f"<td>{'—' if is_ctrl else fmt_delta(d_dd)}</td>"
            f"<td>{fmt_n(st['calmar'])}</td>"
            f"<td>{fmt_n(st['sharpe'])}</td>"
            f"<td>{html_mod.escape(format_money(exp))}</td>"
            f"<td>{fmt_n(st['avg_days'], 1)}</td>"
            "</tr>"
        )

    for split, slabel, ckey in (
        ("is", "IS", "ctrl_is"),
        ("oos", "OOS", "ctrl_oos"),
        ("full", "FULL", "ctrl_full"),
    ):
        add_score_row("CONTROL", "—", slabel, combined[ckey], combined[ckey], True)
        for rec in arm_results:
            add_score_row(rec["name"], rec["verdict"] if slabel == "IS" else "—", slabel, combined[ckey], rec[split], False)

    def multi_table(title: str, ckey: str, akey: str) -> str:
        arms = [(r["name"], r[akey]) for r in arm_results]
        rows = metric_rows_multi(combined[ckey], arms)
        heads = [("Metric", "text"), ("CONTROL", "num")]
        for r in arm_results:
            heads.append((r["name"], "num"))
            heads.append((f"Δ {r['name']}", "num"))
        thead = "".join(sortable_th(l, t) for l, t in heads)
        body = "".join(
            "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows
        )
        return (
            f"<h3>{html_mod.escape(title)}</h3>"
            f'<p class="meta">Click column headers to sort. Overlay is $10,000/fill. '
            "Sheet / Total PnL $ omitted from the quality table (canonical rule).</p>"
            f'<table class="sortable"><thead><tr>{thead}</tr></thead><tbody>{body}</tbody></table>'
        )

    sys_heads = filter_html_compare_columns(
        [
            ("System", "text"),
            ("Arm", "text"),
            ("Split", "text"),
            ("N", "num"),
            ("% kept", "num"),
            ("Win %", "num"),
            ("Avg PnL %", "num"),
            ("Δ Avg %", "num"),
            ("WO_MAX %", "num"),
            ("PF", "num"),
            ("Ann ROR %", "num"),
            ("Max DD %", "num"),
            ("Verdict", "text"),
        ]
    )
    sys_thead = "".join(sortable_th(l, t) for l, t in sys_heads)
    sys_body: list[str] = []
    for rec in per_sys:
        for split, slabel in (("is", "IS"), ("oos", "OOS"), ("full", "FULL")):
            ctrl = rec[f"ctrl_{split}"]
            sys_body.append(
                "<tr>"
                f"<td>{html_mod.escape(rec['system'])}</td>"
                "<td>CONTROL</td>"
                f"<td>{slabel}</td>"
                f"<td>{ctrl['n']}</td>"
                "<td>100.0</td>"
                f"<td>{fmt_n(ctrl['wr'])}</td>"
                f"<td>{fmt_n(ctrl['avg_pnl'])}</td>"
                "<td>—</td>"
                f"<td>{fmt_n(ctrl['wo_max'])}</td>"
                f"<td>{fmt_n(ctrl['pf'])}</td>"
                f"<td>{fmt_n(ctrl['ann_ror'])}</td>"
                f"<td>{fmt_n(ctrl['max_dd'])}</td>"
                "<td>—</td>"
                "</tr>"
            )
            for arm_name, arm in rec["arms"].items():
                st = arm[split]
                kept = (100.0 * st["n"] / ctrl["n"]) if ctrl["n"] else 0.0
                d_avg = st["avg_pnl"] - ctrl["avg_pnl"]
                badge = arm["verdict"] if slabel == "IS" else "—"
                sys_body.append(
                    "<tr>"
                    f"<td>{html_mod.escape(rec['system'])}</td>"
                    f"<td>{html_mod.escape(arm_name)}</td>"
                    f"<td>{slabel}</td>"
                    f"<td>{st['n']}</td>"
                    f"<td>{kept:.1f}</td>"
                    f"<td>{fmt_n(st['wr'])}</td>"
                    f"<td>{fmt_n(st['avg_pnl'])}</td>"
                    f"<td>{fmt_delta(d_avg)}</td>"
                    f"<td>{fmt_n(st['wo_max'])}</td>"
                    f"<td>{fmt_n(st['pf'])}</td>"
                    f"<td>{fmt_n(st['ann_ror'])}</td>"
                    f"<td>{fmt_n(st['max_dd'])}</td>"
                    f"<td><span class=\"badge {html_mod.escape(badge.split()[0] if badge != '—' else 'CONTROL')}\">{html_mod.escape(badge)}</span></td>"
                    "</tr>"
                )

    lean = [r for r in arm_results if r["verdict"].startswith("LEAN") or r["verdict"] == "KEEP"]
    dismiss = [r for r in arm_results if r["verdict"] == "DISMISS"]
    hold = [r for r in arm_results if r["verdict"] == "HOLD"]
    if lean:
        headline = (
            "LEAN KEEP (research-only): "
            + ", ".join(r["name"] for r in lean)
            + ". Not gold. Not DailyRun."
        )
        hclass = "LEAN"
    elif dismiss and not hold:
        headline = "All candidate readings DISMISS vs control on IS quality."
        hclass = "DISMISS"
    else:
        headline = (
            "No reading LEAN KEEPs. "
            + (", ".join(r["name"] for r in hold) + " HOLD. " if hold else "")
            + (", ".join(r["name"] for r in dismiss) + " DISMISS." if dismiss else "")
        )
        hclass = "HOLD"

    feat_bits = (
        f"weekly support UP {feat_counts.get('w_up', 0)}, DOWN {feat_counts.get('w_down', 0)}, "
        f"missing {feat_counts.get('w_miss', 0)}; daily UP {feat_counts.get('d_up', 0)}; "
        f"through weekly support {feat_counts.get('through', 0)}; "
        f"broken (&lt;−2%) {feat_counts.get('broken', 0)}; "
        f"extended (&gt;10%) {feat_counts.get('ext10', 0)}; "
        f"live BUY TODAY {feat_counts.get('buy_today', 0)}; no data {n_nodata}."
    )

    arm_list = "".join(
        f"<li><code>{html_mod.escape(n)}</code> ({html_mod.escape(s)}): {html_mod.escape(d)}</li>"
        for n, s, _fn, d in ARMS
    )
    notes_list = "".join(
        f"<li><code>{html_mod.escape(r['name'])}</code> "
        f"<span class=\"badge {html_mod.escape(r['verdict'].split()[0])}\">{html_mod.escape(r['verdict'])}</span> "
        f"— {html_mod.escape(r['note'])}</li>"
        for r in arm_results
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Trendline chart-reading A/B — {STAMP}</title>
<style>{SORT_CSS}</style>
</head>
<body>
<h1>Do other chart readings add value to the book we already take?</h1>
<p class="meta">Stamp <code>{STAMP}</code> · research overlay · not gold · not DailyRun · generated {datetime.now().strftime("%Y-%m-%d %H:%M")}</p>

<div class="callout ask">
<h2 style="margin-top:0;border:0">What you asked</h2>
<p>“{html_mod.escape(ORIGINAL_REQUEST)}”</p>
</div>

<div class="callout plain">
<h2 style="margin-top:0;border:0">In plain English</h2>
<p>{html_mod.escape(LAYMAN)}</p>
</div>

<div class="callout warn">
<p><strong>Why the last rule failed:</strong> <code>{PRIOR_STAMP}</code> buy-low B
(weekly support UP and |dist| ≤ 2%) kept 287 / 8239 (4%) and Avg% went
<strong>5.90 → 5.37</strong>. HOLD. Too tight. Out-of-sample (OOS) also softened.
Picking a winner from <em>this</em> new table is still in-sample selection.</p>
<p><strong>Headline:</strong> <span class="badge {hclass}">{html_mod.escape(headline)}</span></p>
<p>Control FULL N={ctrl_full['n']} WR={ctrl_full['wr']:.1f}% Avg={ctrl_full['avg_pnl']:.2f}%
overlay {html_mod.escape(format_money(ctrl_full['pnl_d']))} ($10k/fill).
Double-counted same symbol+date across systems: {n_dup}. {feat_bits}</p>
</div>

<h2>How we decided</h2>
<ul>
<li><strong>CONTROL:</strong> every Closed fill from wired DailyRun systems (house pins). Relative Strength Index (RSI) uses the house pin, not RSIN_PaulScore5_IS. Weekly Range / Swing (WRL) is excluded.</li>
<li><strong>As-of picture:</strong> last complete bar <em>strictly before</em> DATE_OPENED; fractal pivots only after confirm. Same geometry as the live page and the prior stamp. Features computed once, then each arm applied.</li>
<li><strong>Veto arms</strong> skip only the ugly cases and keep the rest (no-data kept). <strong>KEEP arms</strong> require a positive reading (no-data sat out).</li>
<li><strong>IS</strong> = entry &lt; 2024-01-01. <strong>OOS</strong> = entry ≥ 2024-01-01, report-only. Do not KEEP from OOS. OOS softens → HOLD.</li>
<li>Judge quality (win rate, Avg%, leave-max-out, expectancy, Ann ROR, Max DD), not trade count. KEEP / LEAN KEEP only if quality improves without collapsing N (&lt;30% kept → HOLD).</li>
<li>Ann ROR / Max DD / Sharpe: Closed overlay at $10,000/fill on a ${INIT_ACCT:,.0f} seed (exit-date equity).</li>
<li>Exit overlay (sell when the live holdings rule fires mid-hold) was <strong>not</strong> run — it needs intra-hold rescoring and is not cheap.</li>
</ul>
<ul>{arm_list}</ul>
<p class="caveat">Acronyms: Break and ReTest (BRT); Volume Zone (VZ); Relative Strength Index (RSI); Rocket Launcher (RL); Pivot Break and Retest (WPBR); Year High (YH); StockBee (SB); Magic Touch (MTS); Relative Strength vs SPY (RS); Weekly Range / Swing (WRL). Pins: {html_mod.escape(pin_bits)}.</p>

<h2>Verdicts</h2>
<ul>{notes_list}</ul>
<p class="caveat">If an arm LEAN KEEPs it is still research-only. DailyRun would later need an explicit freeze, reconcile/parity on these pins, walk-forward or a second universe, and a bat/registry wire. This stamp does none of that.</p>

<h2>Scorecard (combined, $10k/fill)</h2>
<p class="meta">Click column headers to sort. Verdict column is IS-only; OOS and FULL verdict cells are blank on purpose.</p>
<table class="sortable"><thead><tr>{score_thead}</tr></thead><tbody>{''.join(score_body)}</tbody></table>

<h2>Canonical book metrics — combined</h2>
{multi_table("IS (entry < 2024-01-01)", "ctrl_is", "is")}
{multi_table("OOS (entry ≥ 2024-01-01) — report-only", "ctrl_oos", "oos")}
{multi_table("FULL", "ctrl_full", "full")}

<h2>Per system</h2>
<p class="meta">Click column headers to sort. Verdict is IS-only (OOS report-only). Same $10k/fill overlay.</p>
<table class="sortable"><thead><tr>{sys_thead}</tr></thead><tbody>{''.join(sys_body)}</tbody></table>

<p class="caveat">Live buy-today is unchanged (still the 2% weekly-support rule). Charts and DailyRun step 13c are not modified. See also <a href="../{PRIOR_STAMP}/compare.html">{PRIOR_STAMP}</a>.</p>
{SORT_JS}
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def feature_counts(fills: list[dict[str, Any]]) -> dict[str, int]:
    w_up = sum(1 for t in fills if str(t.get("w_sup") or "").upper() == "UP")
    w_down = sum(1 for t in fills if str(t.get("w_sup") or "").upper() == "DOWN")
    w_miss = sum(1 for t in fills if not str(t.get("w_sup") or "").strip())
    d_up = sum(1 for t in fills if str(t.get("d_sup") or "").upper() == "UP")
    through = sum(1 for t in fills if _finite(t.get("w_dist")) and float(t["w_dist"]) < 0)
    broken = sum(1 for t in fills if _finite(t.get("w_dist")) and float(t["w_dist"]) < -PROX_PCT)
    ext10 = sum(1 for t in fills if _finite(t.get("w_dist")) and float(t["w_dist"]) > 10)
    buy_today = sum(1 for t in fills if str(t.get("live_verdict") or "") == "BUY TODAY")
    return {
        "w_up": w_up,
        "w_down": w_down,
        "w_miss": w_miss,
        "d_up": d_up,
        "through": through,
        "broken": broken,
        "ext10": ext10,
        "buy_today": buy_today,
    }


def run_arms(fills: list[dict[str, Any]], systems: list[str]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    attach_overlay_dollars(fills)
    ctrl_is, ctrl_oos = split_is_oos(fills)
    combined = {
        "ctrl_full": book_stats(fills, FILL_CASH),
        "ctrl_is": book_stats(ctrl_is, FILL_CASH),
        "ctrl_oos": book_stats(ctrl_oos, FILL_CASH),
    }
    arm_results: list[dict[str, Any]] = []
    kept_by_arm: dict[str, list[dict[str, Any]]] = {}
    for name, _style, fn, _desc in ARMS:
        kept = [t for t in fills if fn(t)]
        kept_by_arm[name] = kept
        k_is, k_oos = split_is_oos(kept)
        rec = {
            "name": name,
            "full": book_stats(kept, FILL_CASH),
            "is": book_stats(k_is, FILL_CASH),
            "oos": book_stats(k_oos, FILL_CASH),
        }
        v, note = decide_verdict(combined["ctrl_is"], rec["is"], combined["ctrl_oos"], rec["oos"])
        rec["verdict"] = v
        rec["note"] = note
        arm_results.append(rec)
        print(
            f"[read_ab] {name}: FULL {rec['full']['n']}/{len(fills)} "
            f"Avg {rec['full']['avg_pnl']:.2f} (ctrl {combined['ctrl_full']['avg_pnl']:.2f}) "
            f"IS {rec['is']['n']} dAvg {rec['is']['avg_pnl']-combined['ctrl_is']['avg_pnl']:+.2f} "
            f"-> {v}",
            flush=True,
        )

    per_sys: list[dict[str, Any]] = []
    for sys_name in systems:
        book = [t for t in fills if t["system"] == sys_name]
        if not book:
            continue
        b_is, b_oos = split_is_oos(book)
        rec: dict[str, Any] = {
            "system": sys_name,
            "ctrl_full": book_stats(book, FILL_CASH),
            "ctrl_is": book_stats(b_is, FILL_CASH),
            "ctrl_oos": book_stats(b_oos, FILL_CASH),
            "arms": {},
        }
        for name, _style, fn, _desc in ARMS:
            kept = [t for t in book if fn(t)]
            k_is, k_oos = split_is_oos(kept)
            arm = {
                "full": book_stats(kept, FILL_CASH),
                "is": book_stats(k_is, FILL_CASH),
                "oos": book_stats(k_oos, FILL_CASH),
            }
            v, note = decide_verdict(rec["ctrl_is"], arm["is"], rec["ctrl_oos"], arm["oos"])
            arm["verdict"] = v
            arm["note"] = note
            rec["arms"][name] = arm
        per_sys.append(rec)
    return combined, arm_results, per_sys


def load_books() -> tuple[list[dict[str, Any]], dict[str, str], dict[str, str], list[str], int]:
    systems = [s for s in live_wired_systems() if s.upper() != "WRL"]
    fills: list[dict[str, Any]] = []
    pins: dict[str, str] = {}
    sources: dict[str, str] = {}
    n_wrl = 0
    for sys_name in systems:
        rows, pin, src = load_closed_fills(sys_name, DRIVE)
        pins[sys_name] = pin
        sources[sys_name] = src
        fills.extend(rows)
        print(f"[read_ab] {sys_name} pin={pin} n={len(rows)} src={src}", flush=True)
    # Belt-and-suspenders: drop WRL if a sibling loader ever includes it.
    n_wrl = sum(1 for t in fills if t["system"] == "WRL")
    fills = [t for t in fills if t["system"] != "WRL"]
    key_counts: Counter[tuple[str, date]] = Counter((t["sym"], t["opened"]) for t in fills)
    for t in fills:
        t["dup"] = key_counts[(t["sym"], t["opened"])] > 1
    return fills, pins, sources, systems, n_wrl


def run(workers: int, max_symbols: int, from_features: bool, features_only: bool) -> dict[str, Any]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pins: dict[str, str] = {}
    sources: dict[str, str] = {}
    systems = [s for s in live_wired_systems() if s.upper() != "WRL"]
    n_wrl = 0

    if from_features and features_path().is_file():
        print(f"[read_ab] loading features {features_path()}", flush=True)
        _, pins, sources, systems, n_wrl = load_books()
        fills = load_features_csv()
        systems = [s for s in systems if any(t["system"] == s for t in fills)]
    else:
        fills, pins, sources, systems, n_wrl = load_books()
        attach_overlay_dollars(fills)
        score_fills(fills, workers=workers, max_symbols=max_symbols)
        dump_features(fills)

    if features_only:
        print(f"[read_ab] features-only wrote {features_path()} n={len(fills)}")
        return {"n_fills": len(fills), "features": str(features_path())}

    attach_overlay_dollars(fills)
    n_dup = sum(1 for t in fills if t.get("dup"))
    n_nodata = sum(1 for t in fills if t.get("nodata"))
    feats = feature_counts(fills)
    combined, arm_results, per_sys = run_arms(fills, systems)

    write_baseline(
        OUT_DIR / "BASELINE.md",
        pins=pins,
        sources=sources,
        combined=combined,
        arm_results=arm_results,
        n_dup=n_dup,
        n_nodata=n_nodata,
        n_wrl=n_wrl,
    )
    write_html(
        OUT_DIR / "compare.html",
        pins=pins,
        combined=combined,
        arm_results=arm_results,
        per_sys=per_sys,
        n_dup=n_dup,
        n_nodata=n_nodata,
        feat_counts=feats,
    )

    def slim(st: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in st.items() if k != "exits"}

    summary = {
        "stamp": STAMP,
        "original_request": ORIGINAL_REQUEST,
        "pins": pins,
        "sources": sources,
        "n_fills": len(fills),
        "n_dup": n_dup,
        "n_nodata": n_nodata,
        "n_wrl_excluded": n_wrl,
        "feature_counts": feats,
        "overlay_cash_per_fill": FILL_CASH,
        "lookahead": "prior_bar_close_strictly_before_DATE_OPENED; confirmed_on<=asof",
        "control": {
            "full": slim(combined["ctrl_full"]),
            "is": slim(combined["ctrl_is"]),
            "oos": slim(combined["ctrl_oos"]),
        },
        "arms": [
            {
                "name": r["name"],
                "verdict": r["verdict"],
                "note": r["note"],
                "full": slim(r["full"]),
                "is": slim(r["is"]),
                "oos": slim(r["oos"]),
            }
            for r in arm_results
        ],
        "selection_bias": "picking a winner from this table is in-sample selection",
        "dailyrun": "not wired",
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(json.dumps({r["name"]: r["verdict"] for r in arm_results}, indent=2))
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 1))
    ap.add_argument("--max-symbols", type=int, default=0, help="Smoke cap")
    ap.add_argument("--from-features", action="store_true", help="Skip OHLC; score arms from features.csv")
    ap.add_argument("--features-only", action="store_true", help="Dump features.csv and stop")
    args = ap.parse_args()
    run(
        workers=max(1, args.workers),
        max_symbols=args.max_symbols,
        from_features=args.from_features,
        features_only=args.features_only,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
