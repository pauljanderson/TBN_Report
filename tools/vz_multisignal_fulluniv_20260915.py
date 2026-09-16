#!/usr/bin/env python3
"""Full-universe VZ: first-fill vs only-multi-signal-day overlay.

Research stamp only. Does not mutate house pin / VZ_LatestRun_*.
"""
from __future__ import annotations

import csv
import html as html_mod
import json
import math
import re
import shutil
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "tools") not in sys.path:
    sys.path.insert(0, str(REPO / "tools"))
_CF = REPO / "drive" / "paul_experiments"
if str(_CF) not in sys.path:
    sys.path.insert(0, str(_CF))

from compare_format import (  # noqa: E402
    filter_html_compare_metric_rows,
    format_money_delta,
)
from dup_buy_while_held_20260915 import (  # noqa: E402
    CANONICAL_ROWS,
    _SORTABLE_TABLE_SCRIPT,
    _esc,
    _fmt_n,
    _fmt_num,
    _fmt_pct,
    _metric_cell,
    _sortable_th,
    overlay_book,
    split_is_oos,
)

STAMP = "vz_multisignal_fulluniv_20260915"
OUT = REPO / "drive" / "paul_experiments" / STAMP
ENGINE_OUT = OUT / "engine_out"
IS_CUT = date(2024, 1, 1)
VZ_CASH = 45_000.0
VZ_INIT = 500_000.0
HOUSE_PIN = "260915175013"

ASK = (
    "can we add a field to VZ_Closed that shows us whether a stock had more "
    "than one buy signal on any given day?\n"
    "Also, can you run VZ against the full universe and report back on how "
    "the system would have done if it bought ONLY when there was >1 signal "
    "on a given day?"
)
LAYMAN = (
    "1) On each Closed row, show if that name had two or more buy signals "
    "that day (two Volatility Zone bands, like GOLD 2020-05-06).\n"
    "2) Replay Volatility Zone (VZ) on the full ticker tape. Keep a fill "
    "only when that day had more than one signal. One position per name "
    "(the new gate stays). Did that “agreement” filter help vs taking "
    "every first fill?"
)

SORTABLE_TH_CSS = """
th.sortable-th{cursor:pointer;user-select:none;white-space:nowrap}
th.sortable-th:hover{background:#e8e4d8}
.sort-ind{display:inline-block;width:0.9em;margin-left:4px;color:#9a9588;font-size:10px}
th.sort-asc .sort-ind::after{content:"▲";color:#1c1b19}
th.sort-desc .sort-ind::after{content:"▼";color:#1c1b19}
"""


def _ymd(raw: object) -> str:
    text = str(raw or "").strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return ""
    compact = re.sub(r"\D", "", text)
    return compact[:8] if len(compact) >= 8 else ""


def _date(raw: object) -> Optional[date]:
    ymd = _ymd(raw)
    if len(ymd) != 8:
        return None
    try:
        return date(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8]))
    except ValueError:
        return None


def _finite(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    return x


def _pct(raw: object) -> Optional[float]:
    s = str(raw or "").strip().replace("%", "").replace(",", "")
    return _finite(s)


def _int(raw: object, default: int = 0) -> int:
    x = _finite(raw)
    return int(x) if x is not None else default


def find_research_closed() -> Path:
    pinned = OUT / "VZ_Closed_FULLUNIV_RESEARCH.csv"
    if pinned.is_file():
        return pinned
    hits = sorted(ENGINE_OUT.glob("VZ_Closed_*.csv"), key=lambda p: p.stat().st_mtime)
    if hits:
        return hits[-1]
    raise FileNotFoundError(f"No research Closed under {ENGINE_OUT}")


def load_closed(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for i, r in enumerate(csv.DictReader(f)):
            opened = _date(r.get("DATE_OPENED"))
            if opened is None:
                continue
            n_sig = _int(r.get("N_SIGNALS_THAT_DAY"), 0)
            multi = str(r.get("MULTI_SIGNAL_DAY") or "").strip().upper()
            if not multi:
                multi = "YES" if n_sig >= 2 else "NO"
            if n_sig <= 0:
                n_sig = 2 if multi == "YES" else 1
            rows.append(
                {
                    "i": i,
                    "symbol": str(r.get("SYMBOL") or "").strip().upper(),
                    "opened": opened,
                    "closed": _date(r.get("DATE_CLOSED")),
                    "pnl_pct": _pct(r.get("PNL_PCT")),
                    "pnl_d": _finite(r.get("PNL_DOLLARS")),
                    "days": _int(r.get("DAYS_HELD"), 0),
                    "exit": str(r.get("EXIT_TYPE") or "").strip().upper(),
                    "exit_type": str(r.get("EXIT_TYPE") or "").strip().upper(),
                    "industry": str(r.get("INDUSTRY") or "").strip(),
                    "n_signals": n_sig,
                    "multi": multi,
                    "zone_id": str(r.get("ZONE_ID") or "").strip(),
                }
            )
    return rows


def score_scopes(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    is_rows, oos_rows = split_is_oos(rows)
    return {
        "FULL": overlay_book(rows),
        "IS": overlay_book(is_rows),
        "OOS": overlay_book(oos_rows),
    }


def verdict(ctrl: dict[str, dict[str, Any]], cand: dict[str, dict[str, Any]]) -> dict[str, Any]:
    cf, of_ = ctrl["FULL"], cand["FULL"]
    ci, oi = ctrl["IS"], cand["IS"]
    co, oo = ctrl["OOS"], cand["OOS"]
    n_c = int(cf.get("n") or 0)
    n_a = int(of_.get("n") or 0)
    n_ratio = (n_a / n_c) if n_c else 0.0
    n_collapse = n_ratio < 0.50
    d_avg = None
    if ci.get("avg_pct") is not None and oi.get("avg_pct") is not None:
        d_avg = float(oi["avg_pct"]) - float(ci["avg_pct"])
    d_wo = None
    if ci.get("wo_max") is not None and oi.get("wo_max") is not None:
        d_wo = float(oi["wo_max"]) - float(ci["wo_max"])
    d_wr = None
    if ci.get("win_pct") is not None and oi.get("win_pct") is not None:
        d_wr = float(oi["win_pct"]) - float(ci["win_pct"])
    quality_up = (
        d_avg is not None
        and d_avg > 0.05
        and (d_wo is None or d_wo > -0.05)
    ) or (
        d_avg is not None
        and d_avg > -0.05
        and d_wr is not None
        and d_wr > 0.5
        and (d_wo is None or d_wo > -0.10)
    )
    quality_down = d_avg is not None and d_avg < -0.05 and (d_wo is None or d_wo < 0)
    oos_soft = False
    oos_note = "OOS n/a"
    if int(co.get("n") or 0) >= 20 and int(oo.get("n") or 0) >= 20:
        d_oos = None
        if co.get("avg_pct") is not None and oo.get("avg_pct") is not None:
            d_oos = float(oo["avg_pct"]) - float(co["avg_pct"])
        d_oos_wr = None
        if co.get("win_pct") is not None and oo.get("win_pct") is not None:
            d_oos_wr = float(oo["win_pct"]) - float(co["win_pct"])
        oos_soft = (d_oos is not None and d_oos < -0.15) or (
            d_oos_wr is not None and d_oos_wr < -1.0
        )
        oos_note = (
            f"OOS ΔAvg% {d_oos:+.2f}pp" if d_oos is not None else "OOS ΔAvg% n/a"
        )
        if d_oos_wr is not None:
            oos_note += f", ΔWR {d_oos_wr:+.1f}pp"
        if oos_soft:
            oos_note += " — softened"
    if quality_down:
        label = "DISMISS"
        why = "IS quality worse than CONTROL (Avg% / leave-max-out)."
    elif quality_up and n_collapse:
        label = "HOLD"
        why = (
            "IS quality up but N collapsed "
            f"({n_a:,} / {n_c:,} = {100.0 * n_ratio:.1f}%). "
            "KEEP needs quality without collapsing count."
        )
    elif quality_up and oos_soft:
        label = "HOLD"
        why = "IS quality up but OOS softened — do not retune OOS."
    elif quality_up:
        label = "KEEP"
        why = "IS quality improved without collapsing N. Research-only — not DailyRun."
    else:
        label = "HOLD"
        why = "Flat / mixed IS quality vs CONTROL."
    return {
        "verdict": label,
        "why": why,
        "n_ratio": n_ratio,
        "n_collapse": n_collapse,
        "quality_up": quality_up,
        "quality_down": quality_down,
        "oos_soft": oos_soft,
        "oos_note": oos_note,
        "d_avg_is": d_avg,
        "d_wo_is": d_wo,
        "d_wr_is": d_wr,
        "research_only": True,
    }


def _canon_table(
    scores: dict[str, dict[str, dict[str, Any]]],
    scope: str,
    arms: list[tuple[str, str]],
) -> str:
    rows = filter_html_compare_metric_rows(CANONICAL_ROWS, label_index=0)
    head = _sortable_th("Metric", "text") + "".join(
        _sortable_th(label, "num") for _key, label in arms
    )
    head += _sortable_th("Δ ONLY − CONTROL", "num")
    body = ""
    for label, key, kind in rows:
        ctrl = scores[arms[0][0]][scope]
        cand = scores[arms[1][0]][scope] if len(arms) > 1 else {}
        body += f"<tr><td>{_esc(label)}</td>"
        for arm_key, _lab in arms:
            body += f"<td>{_metric_cell(scores[arm_key][scope], key, kind)}</td>"
        cv, av = ctrl.get(key), cand.get(key)
        if kind in {"int", "num0", "num1", "num2", "pct", "money"} and cv is not None and av is not None:
            try:
                delta = float(av) - float(cv)
            except (TypeError, ValueError):
                delta = None
        else:
            delta = None
        if delta is None:
            body += "<td>—</td>"
        elif kind == "money":
            body += f"<td>{format_money_delta(delta)}</td>"
        elif kind == "pct":
            body += f"<td>{delta:+.2f}pp</td>"
        elif kind == "int":
            body += f"<td>{delta:+,.0f}</td>"
        else:
            body += f"<td>{delta:+,.2f}</td>"
        body += "</tr>"
    return (
        f'<table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table>"
    )


def _exit_table(
    scores: dict[str, dict[str, dict[str, Any]]],
    scope: str,
    arms: list[tuple[str, str]],
) -> str:
    keys: set[str] = set()
    for arm_key, _lab in arms:
        keys.update(scores[arm_key][scope].get("exit_mix") or {})
    order = ["TARGET", "STOP", "STOP_LOSS", "TIME", "GAP_UP", "GAP_DOWN"]
    rest = sorted(k for k in keys if k not in order)
    head = _sortable_th("Exit", "text") + "".join(
        _sortable_th(label, "num") for _k, label in arms
    )
    body = ""
    for ex in [k for k in order if k in keys] + rest:
        body += f"<tr><td>{_esc(ex)}</td>"
        for arm_key, _lab in arms:
            mix = scores[arm_key][scope].get("exit_mix") or {}
            n = scores[arm_key][scope].get("n") or 0
            c = mix.get(ex, 0)
            pct = (100.0 * c / n) if n else None
            body += f"<td>{_fmt_n(c)} ({_fmt_pct(pct)})</td>"
        body += "</tr>"
    return (
        f'<table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table>"
    )


def _md_row(scope: str, key: str, lab: str, scores: dict[str, dict[str, dict[str, Any]]]) -> str:
    m = scores[key][scope]
    avg = f"{m['avg_pct']:.2f}" if m.get("avg_pct") is not None else "—"
    wr = f"{m['win_pct']:.2f}" if m.get("win_pct") is not None else "—"
    wo = f"{m['wo_max']:.2f}" if m.get("wo_max") is not None else "—"
    pf = f"{m['pf']:.2f}" if m.get("pf") is not None else "—"
    ann = f"{m['ann_ror']:.2f}" if m.get("ann_ror") is not None else "—"
    dd = f"{m['max_dd']:.2f}" if m.get("max_dd") is not None else "—"
    return f"| {lab} | {scope} | {m['n']} | {avg} | {wr} | {wo} | {pf} | {ann} | {dd} |\n"


def write_baseline(
    *,
    closed_name: str,
    n_full_syms: int,
    scores: dict[str, dict[str, dict[str, Any]]],
    verd: dict[str, Any],
    house_ok: bool,
    n_multi_days: int,
    n_solo_days: int,
) -> None:
    cf = scores["CONTROL_FULLUNIV_FIRST"]["FULL"]
    of_ = scores["ONLY_MULTI_SIGNAL"]["FULL"]
    ci = scores["CONTROL_FULLUNIV_FIRST"]["IS"]
    oi = scores["ONLY_MULTI_SIGNAL"]["IS"]
    co = scores["CONTROL_FULLUNIV_FIRST"]["OOS"]
    oo = scores["ONLY_MULTI_SIGNAL"]["OOS"]
    text = f"""# VZ multi-signal day — full universe (research only)

**Stamp:** `{STAMP}`  
**Status:** Research candidate. Not gold. Not DailyRun-wired.

## What you asked

{ASK}

## In plain English

{LAYMAN}

## Arms

| Arm | Meaning |
|-----|---------|
| CONTROL_FULLUNIV_FIRST | Full tape, live VZ freeze, one position per name, every first fill |
| ONLY_MULTI_SIGNAL | Same book, keep a fill only if that symbol-day had `N_SIGNALS_THAT_DAY` ≥ 2 |

One-position gate stays (no GOLD double lot). Count of signals is **before** the skip, so GOLD still shows 2 on the kept row.

## Freeze (same as live VZ — do not retune)

| Knob | Value |
|------|-------|
| lookback_days | 126 |
| zone_kinds | HL only |
| first_retest_only | True |
| min_touches_before_entry | 1 |
| retest_eps_pct | 0.005 |
| retest_window | 63 |
| entry_on | next_open |
| Primary exit | `EXIT_atr4_s025_r15_ts20` (atr4 = 14-day Average True Range ≥ 4.0% of trigger close, not a 4-ATR stop; s025 = zone.lo − 0.25·ATR; r15 = 1.5R; ts20 = 20-bar time stop) |
| min_atr_pct_at_entry | 0.0 (off) |
| min_atr_pct_at_trigger | 4.0 |
| require_hvn_overlap | False |
| cooldown_after_target_days | 10 |
| trade_side | long |
| Universe | Full `data/newdata/data` tape ({n_full_syms} names with enough bars). Not Paul78.142 house. |
| Sheet notional | $45,000 / trade |
| Overlay seed | $500,000 Initial_Account_Size (Ann ROR / Max DD / Sharpe) |

## Chronologic split

In-sample (IS) = entry_date < 2024-01-01. Out-of-sample (OOS) = entry_date ≥ 2024-01-01. **OOS is report-only — do not retune.**

## Selection honesty

Closed overlay after one full-universe engine run (not two host runs). ONLY_MULTI is a slice of CONTROL. Choosing this filter after seeing the table is in-sample selection — labeled here.

Prior extras A/B (`dup_buy_while_held_20260915`): extras-only Avg% 8.89 vs first 4.27, but **FIRST_ON_MULTI was below SOLO**. This arm is *first fill on multi-signal days only* (the extra lot is still dropped). It may **not** match extras-only quality. Judge quality over count.

## Closed field (Task A)

Future `run_vz.bat` / `rocket_vz.enrich_trade_rows` writes:

- `N_SIGNALS_THAT_DAY` — count of Volatility Zone (VZ) buy signals on that symbol’s `DATE_OPENED`, **before** the one-position skip
- `MULTI_SIGNAL_DAY` — `YES` / `NO` (`YES` when count ≥ 2)

House LatestRun is **not** backfilled (old pin has no column until the next house `run_vz.bat`).

## House LatestRun guard

House pin at job start: `{HOUSE_PIN}` (142-name Paul78.142 book, N=2170). Research wrote under `{ENGINE_OUT.as_posix()}` — not `drive/VZ_LatestRun_*`. House LatestRun still the house book after this job: **{'yes' if house_ok else 'NO — INVESTIGATE'}**.

## Headline

| Arm | Scope | N | Avg% | Win% | WO_MAX | PF | Ann ROR | Max DD |
|---|---|---:|---:|---:|---:|---:|---:|---:|
"""
    for scope in ("FULL", "IS", "OOS"):
        for key, lab in (
            ("CONTROL_FULLUNIV_FIRST", "CONTROL_FULLUNIV_FIRST"),
            ("ONLY_MULTI_SIGNAL", "ONLY_MULTI_SIGNAL"),
        ):
            text += _md_row(scope, key, lab, scores)
    text += f"""
**Verdict:** {verd['verdict']} — {verd['why']}  
OOS note: {verd['oos_note']}  
N ratio ONLY/CONTROL FULL = {100.0 * verd['n_ratio']:.1f}% ({of_['n']} / {cf['n']}).  
Symbol-days with N_SIGNALS≥2 (CONTROL fills): {n_multi_days}. Solo-signal fills: {n_solo_days}.

CONTROL FULL Avg% {cf.get('avg_pct'):.2f} · ONLY FULL Avg% {of_.get('avg_pct'):.2f} · IS CONTROL {ci.get('avg_pct'):.2f} vs ONLY {oi.get('avg_pct'):.2f} · OOS CONTROL {co.get('avg_pct'):.2f} vs ONLY {oo.get('avg_pct'):.2f}.

## Artifacts

- Research Closed: `{closed_name}`
- Engine out: `engine_out/` (not house LatestRun)
- `compare.html` (sortable)

Research only. Do not wire DailyRun from this stamp.
"""
    (OUT / "BASELINE.md").write_text(text, encoding="utf-8")


def write_html(
    *,
    closed_name: str,
    n_full_syms: int,
    scores: dict[str, dict[str, dict[str, Any]]],
    verd: dict[str, Any],
    house_ok: bool,
    n_multi_days: int,
    n_solo_days: int,
) -> Path:
    arms = [
        ("CONTROL_FULLUNIV_FIRST", "CONTROL (all first fills)"),
        ("ONLY_MULTI_SIGNAL", "ONLY_MULTI_SIGNAL"),
    ]
    cf = scores["CONTROL_FULLUNIV_FIRST"]["FULL"]
    of_ = scores["ONLY_MULTI_SIGNAL"]["FULL"]
    ci = scores["CONTROL_FULLUNIV_FIRST"]["IS"]
    oi = scores["ONLY_MULTI_SIGNAL"]["IS"]
    co = scores["CONTROL_FULLUNIV_FIRST"]["OOS"]
    oo = scores["ONLY_MULTI_SIGNAL"]["OOS"]
    badge = verd["verdict"]
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>VZ multi-signal full universe — {STAMP}</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:24px;max-width:1180px;color:#1c1b19;line-height:1.45}}
h1{{font-size:1.45rem;margin:0 0 .35em}}
h2{{font-size:1.15rem;margin:1.4em 0 .4em;border-bottom:1px solid #e5e1d6;padding-bottom:.25em}}
h3{{font-size:1.02rem;margin:1.1em 0 .35em}}
.meta{{color:#64748b;font-size:13px}}
.ask{{background:#eff6ff;border-left:4px solid #3b82f6;padding:12px 16px;margin:14px 0}}
.insight{{background:#f8fafc;border-left:4px solid #64748b;padding:12px 16px;margin:14px 0}}
.caveat{{background:#fff7ed;border-left:4px solid #f59e0b;padding:10px 14px;margin:12px 0}}
blockquote.meta{{margin:8px 0;padding-left:12px;border-left:3px solid #93c5fd}}
table{{border-collapse:collapse;width:100%;font-size:13px;margin:12px 0}}
th,td{{border:1px solid #cbd5e1;padding:6px 8px;text-align:left}}
thead{{background:#f1f5f9}}
.badge{{display:inline-block;background:#1e293b;color:#fff;padding:2px 8px;border-radius:4px;font-size:12px}}
code{{background:#f4f4f5;padding:1px 5px;border-radius:3px;font-size:12px}}
{SORTABLE_TH_CSS}
</style></head><body>
<h1>VZ — buy only on multi-signal days (full universe)</h1>
<p class="meta">Stamp <code>{_esc(STAMP)}</code> · research only · not gold · not DailyRun</p>

<div class="ask">
<h2 style="margin-top:0;border:0">What you asked</h2>
<blockquote class="meta">{_esc(ASK)}</blockquote>
<h2>In plain English</h2>
<p>{_esc(LAYMAN).replace(chr(10), "<br/>")}</p>
</div>

<div class="insight">
<h2 style="margin-top:0;border:0">Verdict</h2>
<p><span class="badge">{_esc(badge)}</span> {_esc(verd["why"])}</p>
<p>CONTROL FULL N={_fmt_n(cf.get("n"))} Avg%={_fmt_pct(cf.get("avg_pct"))} · ONLY_MULTI N={_fmt_n(of_.get("n"))} Avg%={_fmt_pct(of_.get("avg_pct"))} ({100.0 * verd["n_ratio"]:.1f}% of CONTROL).</p>
<p>IS CONTROL Avg%={_fmt_pct(ci.get("avg_pct"))} vs ONLY {_fmt_pct(oi.get("avg_pct"))} · OOS (report-only) CONTROL {_fmt_pct(co.get("avg_pct"))} vs ONLY {_fmt_pct(oo.get("avg_pct"))}. {_esc(verd["oos_note"])}</p>
<p class="meta">House LatestRun still the Paul78.142 house book (pin {HOUSE_PIN}): <strong>{"yes" if house_ok else "NO"}</strong>. Research Closed: <code>{_esc(closed_name)}</code>.</p>
</div>

<div class="caveat">
<p><strong>Honesty vs the extras A/B.</strong> Prior <code>dup_buy_while_held_20260915</code>: extras-only Avg% 8.89 vs first 4.27, but first-on-multi was <em>below</em> solo. This arm keeps the <em>first</em> fill on days that had ≥2 signals — the extra lot is still dropped. It is not the extras-only book. Quality over count. OOS is report-only; do not retune.</p>
</div>

<h2>Arms</h2>
<p class="meta">Same live Volatility Zone (VZ) freeze. One position per name. Click column headers to sort.</p>
<table class="sortable"><thead><tr>
{_sortable_th("Arm", "text")}{_sortable_th("What it keeps", "text")}
</tr></thead><tbody>
<tr><td>CONTROL_FULLUNIV_FIRST</td><td>Full tape, every first fill (one lot / name)</td></tr>
<tr><td>ONLY_MULTI_SIGNAL</td><td>Same fills, only when <code>N_SIGNALS_THAT_DAY</code> ≥ 2</td></tr>
</tbody></table>
<p class="meta">Full-universe names with enough bars: {n_full_syms}. CONTROL fills on multi-signal days: {n_multi_days}. Solo-signal fills: {n_solo_days}. Sheet $45,000 · overlay seed $500,000 · IS = entry &lt; 2024-01-01 · OOS report-only. Paul / FIT Summary scores are N/A on this Closed overlay.</p>

<h2>FULL — canonical book</h2>
<p class="meta">Click column headers to sort. Sheet / Total PnL $ omitted. Ann ROR / Max DD / Calmar / Sharpe from Closed overlay (exit-date equity).</p>
{_canon_table(scores, "FULL", arms)}

<h2>IS (entry &lt; 2024-01-01) — quality decision</h2>
<p class="meta">Click column headers to sort. KEEP/DISMISS uses this split. OOS is not for picking the filter.</p>
{_canon_table(scores, "IS", arms)}

<h2>OOS (entry ≥ 2024-01-01) — report-only</h2>
<p class="meta">Click column headers to sort. Report-only — do not retune knobs from this table.</p>
{_canon_table(scores, "OOS", arms)}

<h2>Exit mix</h2>
<p class="meta">Closed <code>EXIT_TYPE</code> counts and %. Click headers to sort.</p>
<h3>FULL</h3>
{_exit_table(scores, "FULL", arms)}
<h3>IS</h3>
{_exit_table(scores, "IS", arms)}
<h3>OOS</h3>
{_exit_table(scores, "OOS", arms)}

<h2>Freeze (live VZ — not retuned)</h2>
<table class="sortable"><thead><tr>{_sortable_th("Knob", "text")}{_sortable_th("Value", "text")}</tr></thead>
<tbody>
<tr><td>lookback / retest window</td><td>126 / 63</td></tr>
<tr><td>zone_kinds / first_retest / min_touches</td><td>HL / true / 1</td></tr>
<tr><td>retest_eps_pct</td><td>0.005</td></tr>
<tr><td>entry_on</td><td>next_open</td></tr>
<tr><td>exit</td><td>EXIT_atr4_s025_r15_ts20 (atr4 = ATR ≥ 4% of trigger close, not a 4-ATR stop)</td></tr>
<tr><td>High Volume Node (HVN) overlap</td><td>false</td></tr>
<tr><td>cooldown after TARGET</td><td>10 calendar days</td></tr>
<tr><td>one-position gate</td><td>on (no GOLD double lot)</td></tr>
<tr><td>Closed field</td><td>N_SIGNALS_THAT_DAY + MULTI_SIGNAL_DAY (count before skip)</td></tr>
</tbody></table>

<p class="meta">Engine wrote under <code>engine_out/</code> so <code>drive/VZ_LatestRun_*</code> stays the house pin. Next house <code>run_vz.bat</code> will include the new Closed columns.</p>
{_SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    path = OUT / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def house_latest_is_house_book() -> bool:
    pin_p = REPO / "drive" / "VZ_house_last_run_ts.txt"
    latest = REPO / "drive" / "VZ_LatestRun_Closed.csv"
    house_closed = REPO / "drive" / f"VZ_Closed_{HOUSE_PIN}.csv"
    if not pin_p.is_file() or not latest.is_file() or not house_closed.is_file():
        return False
    pin = pin_p.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    if pin != HOUSE_PIN:
        return False
    return latest.stat().st_size == house_closed.stat().st_size


def publish_research_closed(src: Path) -> Path:
    dest = OUT / "VZ_Closed_FULLUNIV_RESEARCH.csv"
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    return dest


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    src = find_research_closed()
    dest = publish_research_closed(src)
    rows = load_closed(dest)
    if not rows:
        raise SystemExit(f"empty Closed: {dest}")
    missing = sum(1 for r in rows if r["n_signals"] <= 0)
    if missing:
        print(f"[WARN] {missing} rows missing N_SIGNALS_THAT_DAY", flush=True)
    control = rows
    only = [r for r in rows if r["n_signals"] >= 2 or r["multi"] == "YES"]
    scores = {
        "CONTROL_FULLUNIV_FIRST": score_scopes(control),
        "ONLY_MULTI_SIGNAL": score_scopes(only),
    }
    verd = verdict(scores["CONTROL_FULLUNIV_FIRST"], scores["ONLY_MULTI_SIGNAL"])
    house_ok = house_latest_is_house_book()
    n_syms = len({r["symbol"] for r in rows})
    # Engine scanned 1118 names; n_syms is names with ≥1 Closed fill.
    n_multi = sum(1 for r in rows if r["n_signals"] >= 2)
    n_solo = len(rows) - n_multi
    write_baseline(
        closed_name=dest.as_posix().replace("\\", "/"),
        n_full_syms=n_syms,
        scores=scores,
        verd=verd,
        house_ok=house_ok,
        n_multi_days=n_multi,
        n_solo_days=n_solo,
    )
    html_path = write_html(
        closed_name=dest.name,
        n_full_syms=n_syms,
        scores=scores,
        verd=verd,
        house_ok=house_ok,
        n_multi_days=n_multi,
        n_solo_days=n_solo,
    )
    summary = {
        "stamp": STAMP,
        "closed": dest.as_posix(),
        "n_control": scores["CONTROL_FULLUNIV_FIRST"]["FULL"]["n"],
        "n_only": scores["ONLY_MULTI_SIGNAL"]["FULL"]["n"],
        "avg_control": scores["CONTROL_FULLUNIV_FIRST"]["FULL"]["avg_pct"],
        "avg_only": scores["ONLY_MULTI_SIGNAL"]["FULL"]["avg_pct"],
        "is_avg_control": scores["CONTROL_FULLUNIV_FIRST"]["IS"]["avg_pct"],
        "is_avg_only": scores["ONLY_MULTI_SIGNAL"]["IS"]["avg_pct"],
        "oos_avg_control": scores["CONTROL_FULLUNIV_FIRST"]["OOS"]["avg_pct"],
        "oos_avg_only": scores["ONLY_MULTI_SIGNAL"]["OOS"]["avg_pct"],
        "verdict": verd,
        "house_latest_is_house_book": house_ok,
        "html": html_path.as_posix(),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str), flush=True)
    print(f"[OK] {html_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
