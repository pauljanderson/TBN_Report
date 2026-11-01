#!/usr/bin/env python3
"""Merge MINDIST_7.18_NO_ATR (research) onto the sibling 7.18 compare.

CONTROL = house defaults (atr=5, no dist)
MINDIST_7.18 = min dist 7.18, atr=5 (sibling)
MINDIST_7.18_NO_ATR = min dist 7.18, atr=0 (this arm; research only)

Does not change DailyRun. Does not touch house pin / LatestRun.
"""
from __future__ import annotations

import html as html_mod
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))

from rsi_mindist52_718_ab_20260916 import (  # noqa: E402
    OUT_DIR,
    SLICE_HEADERS,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    STAMP,
    _delta_pct,
    _fmt_pct,
    _latest_ts,
    arm_row,
    full_canonical_rows,
    load_closed,
    load_equity_meta,
    load_report,
    load_summary,
    pack,
    slc,
    sortable_th,
    summary_pack,
    verdict,
)

ASK1 = (
    "let's wire in min distance to 52 week high at 7.18, and run that through. "
    "send me a compare.html with the current defaults."
)
ASK2 = (
    "also do a compare with 7.18 for min DISTance to 52 week high, and remove "
    "the ATR min altogether. show these against the control"
)
PLAIN = (
    "Relative Strength Index (RSI) buys after a cool-off from hot. The first ask "
    "adds a distance-to-52-week-high floor of 7.18% (price must sit at least that "
    "far under the high) and keeps the house Average True Range (ATR) floor of 5%. "
    "The second ask keeps that 7.18% distance floor but turns the ATR floor off "
    "(atr=0), so quieter names can also fill. All three books use the same 149-name "
    "house list, 70/30/exit70/trigger60/time-stop 20/next-open, and full history. "
    "The atr=0 book is a research look only — DailyRun stays atr=5."
)


def _verdict_noatr(c_full: dict, n_full: dict, c_oos: dict, n_oos: dict) -> str:
    """Research KEEP/HOLD/DISMISS for atr=0+7.18 vs control. Not DailyRun."""
    n_c = float(c_full.get("n") or 0)
    n_a = float(n_full.get("n") or 0)
    avg_c = float(c_full.get("avg_pnl_pct") or 0)
    avg_a = float(n_full.get("avg_pnl_pct") or 0)
    wr_c = float(c_full.get("win_pct") or 0)
    wr_a = float(n_full.get("win_pct") or 0)
    oos_c = float(c_oos.get("avg_pnl_pct") or 0) if c_oos.get("n") else None
    oos_a = float(n_oos.get("avg_pnl_pct") or 0) if n_oos.get("n") else None
    n_ratio = (n_a / n_c) if n_c else 0.0
    collapsed = n_ratio < 0.55
    d_avg = avg_a - avg_c
    d_wr = wr_a - wr_c
    oos_soft = oos_c is not None and oos_a is not None and (oos_a - oos_c) <= -0.40
    # Quality-worse is DISMISS even if OOS also softened (do not hide a worse book as HOLD).
    if d_avg <= -0.40 or d_wr <= -3.0:
        return "DISMISS (FULL quality worse vs control) — research only"
    if collapsed and d_avg < 0.3:
        return "DISMISS (N collapsed without a quality lift) — research only"
    if oos_soft:
        return "HOLD (OOS softened vs control — report-only; do not retune OOS) — research only"
    if d_avg >= 0.30 and d_wr >= -1.0 and not collapsed:
        return "LEAN KEEP (quality up, N intact) — research only; not DailyRun"
    if d_avg >= 0.15 and not collapsed:
        return "HOLD (small FULL quality lift) — research only; not DailyRun"
    return "HOLD (flat quality / mixed) — research only"


def _slice_table3(
    ctrl: dict, cand: dict, noatr: dict, sl: str, note_c: str, note_n: str
) -> str:
    title = {
        "IS": "IS (entry &lt; 2024-01-01) — 7.18 was shopped here / on the sheet",
        "OOS": "OOS (entry ≥ 2024-01-01) — report-only",
        "FULL": "FULL (all history) — overlay $10k/fill on $500k seed",
    }[sl]
    th = "".join(sortable_th(h, t) for h, t in SLICE_HEADERS)
    return (
        f"<h3>{title}</h3>"
        f'<p class="meta">Click column headers to sort. Sheet $ / Total PnL $ omitted.</p>'
        f'<table class="sortable"><thead><tr>{th}</tr></thead><tbody>'
        f"{arm_row('CONTROL', 'atr=5, dist=off', ctrl, ctrl, sl, '')}"
        f"{arm_row('MINDIST_7.18', 'atr=5, dist=7.18', cand, ctrl, sl, note_c)}"
        f"{arm_row('MINDIST_7.18_NO_ATR', 'atr=0, dist=7.18 (research)', noatr, ctrl, sl, note_n)}"
        f"</tbody></table>"
    )


def _canon3(
    c_rep: dict,
    a_rep: dict,
    n_rep: dict,
    c_eq: dict,
    a_eq: dict,
    n_eq: dict,
    c_sum: dict,
    a_sum: dict,
    n_sum: dict,
    c_wo: Any,
    a_wo: Any,
    n_wo: Any,
) -> list[tuple[str, str, str, str, str, str]]:
    """Reuse 2-arm canonical pairs, then add the third arm + Δ vs control."""
    ca = full_canonical_rows(c_rep, a_rep, c_eq, a_eq, c_sum, a_sum, c_wo, a_wo)
    cn = full_canonical_rows(c_rep, n_rep, c_eq, n_eq, c_sum, n_sum, c_wo, n_wo)
    by_n = {row[0]: row for row in cn}
    out = []
    for label, cs, as_, ds_a in ca:
        nr = by_n.get(label)
        ns = nr[2] if nr else "—"
        ds_n = nr[3] if nr else "—"
        out.append((label, cs, as_, ns, ds_a, ds_n))
    return out


def _exit3(c_ex: Counter, a_ex: Counter, n_ex: Counter, n_c: int, n_a: int, n_n: int) -> str:
    keys = sorted(set(c_ex) | set(a_ex) | set(n_ex))
    th = "".join(
        sortable_th(h, t)
        for h, t in [
            ("EXIT_TYPE", "text"),
            ("Ctrl N", "num"),
            ("Ctrl %", "num"),
            ("MINDIST_7.18 N", "num"),
            ("MINDIST_7.18 %", "num"),
            ("NO_ATR N", "num"),
            ("NO_ATR %", "num"),
        ]
    )
    rows = []
    for k in keys:
        cn, an, nn = c_ex.get(k, 0), a_ex.get(k, 0), n_ex.get(k, 0)
        cp = 100.0 * cn / n_c if n_c else 0.0
        ap = 100.0 * an / n_a if n_a else 0.0
        np_ = 100.0 * nn / n_n if n_n else 0.0
        rows.append(
            "<tr>"
            + "".join(
                f"<td>{html_mod.escape(str(x))}</td>"
                for x in (k, cn, f"{cp:.1f}%", an, f"{ap:.1f}%", nn, f"{np_:.1f}%")
            )
            + "</tr>"
        )
    return (
        '<table class="sortable"><thead><tr>'
        + th
        + "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def main() -> int:
    ctrl_dir = OUT_DIR / "control"
    cand_dir = OUT_DIR / "candidate"
    noatr_dir = OUT_DIR / "MINDIST_7.18_NO_ATR"
    ctrl_ts = _latest_ts(ctrl_dir)
    cand_ts = _latest_ts(cand_dir)
    noatr_ts = _latest_ts(noatr_dir)

    ctrl_all = load_closed(ctrl_dir, ctrl_ts)
    cand_all = load_closed(cand_dir, cand_ts)
    noatr_all = load_closed(noatr_dir, noatr_ts)

    packs = {
        sl: (
            pack(slc(ctrl_all, sl)),
            pack(slc(cand_all, sl)),
            pack(slc(noatr_all, sl)),
        )
        for sl in ("IS", "OOS", "FULL")
    }
    c_full, a_full, n_full = packs["FULL"]
    c_oos, a_oos, n_oos = packs["OOS"]
    c_is, a_is, n_is = packs["IS"]
    research_718, wired = verdict(c_full, a_full, c_oos, a_oos, c_is, a_is)
    research_noatr = _verdict_noatr(c_full, n_full, c_oos, n_oos)

    c_rep = load_report(ctrl_dir, ctrl_ts)
    a_rep = load_report(cand_dir, cand_ts)
    n_rep = load_report(noatr_dir, noatr_ts)
    c_eq = load_equity_meta(ctrl_dir, ctrl_ts)
    a_eq = load_equity_meta(cand_dir, cand_ts)
    n_eq = load_equity_meta(noatr_dir, noatr_ts)
    c_sum = summary_pack(load_summary(ctrl_dir, ctrl_ts))
    a_sum = summary_pack(load_summary(cand_dir, cand_ts))
    n_sum = summary_pack(load_summary(noatr_dir, noatr_ts))
    canon = _canon3(
        c_rep,
        a_rep,
        n_rep,
        c_eq,
        a_eq,
        n_eq,
        c_sum,
        a_sum,
        n_sum,
        c_full.get("avg_wo_max"),
        a_full.get("avg_wo_max"),
        n_full.get("avg_wo_max"),
    )
    c_ex = Counter(c_full.get("exits") or {})
    a_ex = Counter(a_full.get("exits") or {})
    n_ex = Counter(n_full.get("exits") or {})

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    def _line(label: str, st: dict) -> str:
        return (
            f"- **{label}** N={st['n']} WR={st['win_pct']:.2f}% "
            f"Avg%={st['avg_pnl_pct']:.2f} MaxDD={st['max_dd']:.2f}"
        )

    baseline = f"""# BASELINE — {STAMP}

**Status:** Three-arm ENTRY compare. DailyRun wired 7.18 + **atr=5**. atr=0 arm is **research only**. **Not walk-forward gold.** OOS report-only.

## What you asked

> {ASK1}

> {ASK2}

## In plain English

{PLAIN}

## Honesty

- Arms: CONTROL (atr=5, no dist) vs MINDIST_7.18 (atr=5, dist=7.18) vs MINDIST_7.18_NO_ATR (atr=0, dist=7.18).
- Freeze otherwise: ob=70 / os=30 / exit=70 / max_trigger=60 / ts=20 / next_open / house `rsi_universe.csv` 149 / full history (no `entry_end_date`).
- 7.18 was picked after seeing correlation / sheet — in-sample selection. OOS report-only.
- **MINDIST_7.18_NO_ATR is research only.** Do not wire DailyRun to atr=0. Isolated `-o`; house pin / LatestRun not stolen.
- KEEP only if quality improves without collapsing N; OOS soften → HOLD. Do not retune on OOS.

## Arms

| Arm | Knob | Isolated stamp | DailyRun? |
|-----|------|----------------|-----------|
| CONTROL | atr=5, dist=off | `{ctrl_ts}` | freeze before 7.18 wire |
| MINDIST_7.18 | atr=5, dist=7.18 | `{cand_ts}` | preference wire (sibling) |
| MINDIST_7.18_NO_ATR | atr=0, dist=7.18 | `{noatr_ts}` | **no — research only** |

### CONTROL
{_line("IS", c_is)}
{_line("OOS", c_oos)}
{_line("FULL", c_full)}

### MINDIST_7.18 (atr=5)
{_line("IS", a_is)}
{_line("OOS", a_oos)}
{_line("FULL", a_full)}

- **Research verdict vs control:** {research_718}

### MINDIST_7.18_NO_ATR (atr=0) — research only
{_line("IS", n_is)}
{_line("OOS", n_oos)}
{_line("FULL", n_full)}

- **Research verdict vs control:** {research_noatr}
- **DailyRun:** still atr=5 (sibling wired 7.18). This arm does **not** change DailyRun.
"""
    (OUT_DIR / "BASELINE.md").write_text(baseline, encoding="utf-8")

    canon_th = "".join(
        sortable_th(h, t)
        for h, t in [
            ("Metric", "text"),
            ("CONTROL (atr5, dist off)", "num"),
            ("MINDIST_7.18 (atr5)", "num"),
            ("MINDIST_7.18_NO_ATR (atr0, research)", "num"),
            ("Δ 7.18−ctrl", "num"),
            ("Δ noATR−ctrl", "num"),
        ]
    )
    canon_body = "".join(
        "<tr>"
        + "".join(f"<td>{html_mod.escape(str(x))}</td>" for x in row)
        + "</tr>"
        for row in canon
    )

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>{STAMP} — 3-arm</title>
<style>
{SORTABLE_TH_CSS}
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 1.5rem; color: #0f172a; background: #f8fafc; }}
h1 {{ font-size: 1.4rem; margin: 0 0 .35rem; }}
h2 {{ font-size: 1.12rem; margin: 1.5rem 0 .45rem; border-bottom: 1px solid #cbd5e1; padding-bottom: .25rem; }}
.meta {{ color: #475569; font-size: .92rem; max-width: 92rem; }}
.insight {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: .75rem 1rem; margin: .75rem 0; max-width: 92rem; }}
.ask {{ background: #eff6ff; border: 1px solid #bfdbfe; }}
table.sortable {{ border-collapse: collapse; background: #fff; font-size: .78rem; margin: .5rem 0 1rem; }}
table.sortable th, table.sortable td {{ border: 1px solid #e2e8f0; padding: .32rem .5rem; }}
table.sortable th {{ background: #f1f5f9; }}
.badge {{ display: inline-block; padding: .1rem .45rem; border-radius: 4px; font-size: .8rem; background: #e2e8f0; }}
.caveat {{ color: #9a3412; font-size: .9rem; }}
blockquote.meta {{ margin: .4rem 0 0; padding-left: .8rem; border-left: 3px solid #93c5fd; }}
</style></head><body>
<h1>RSI min-dist 7.18 vs control, plus 7.18 with ATR min off</h1>
<p class="badge">Three-arm ENTRY compare · DailyRun = 7.18 + atr=5 · atr=0 research only · not walk-forward gold · OOS report-only</p>
<p class="meta">Stamp <code>{html_mod.escape(STAMP)}</code> · {html_mod.escape(now)} · Click column headers to sort</p>
<div class="insight ask">
<h2 style="margin-top:0;border:0">What you asked</h2>
<blockquote class="meta">{html_mod.escape(ASK1)}</blockquote>
<blockquote class="meta">{html_mod.escape(ASK2)}</blockquote>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN)}</p>
</div>
<div class="insight">
<p><strong>MINDIST_7.18 vs control (research):</strong> {html_mod.escape(research_718)}</p>
<p><strong>MINDIST_7.18_NO_ATR vs control (research only):</strong> {html_mod.escape(research_noatr)}</p>
<p><strong>DailyRun:</strong> {html_mod.escape(wired)} ATR min stays <strong>5</strong> — atr=0 is not wired.</p>
<p class="caveat"><strong>Selection honesty:</strong> 7.18 was picked after seeing correlation / the sheet
(in-sample selection). OOS is report-only. The atr=0 arm is a second look after seeing 7.18 —
also in-sample selection. Control is a fresh full-history house run
(ob70/os30/exit70/max60/<strong>atr5</strong>/ts20/next_open, 149 names).</p>
<p class="meta">CONTROL <code>{html_mod.escape(ctrl_ts)}</code> · MINDIST_7.18 <code>{html_mod.escape(cand_ts)}</code> ·
NO_ATR <code>{html_mod.escape(noatr_ts)}</code> · Isolated <code>-o</code> (house pin / LatestRun not stolen).</p>
</div>
<h2>Headline N / Avg% (Closed overlay)</h2>
<p class="meta">Click column headers to sort. Ann ROR (Annualized Rate of Return) is the same Closed-overlay figure already on the slice tables (<code>overlay_ann_ror_max_dd</code>). Judge quality (Avg%, win%) not trade count. OOS report-only.</p>
<table class="sortable"><thead><tr>
{sortable_th("Arm", "text")}{sortable_th("Knob", "text")}
{sortable_th("FULL N", "num")}{sortable_th("FULL Avg%", "num")}{sortable_th("FULL Ann ROR %", "num")}
{sortable_th("IS N", "num")}{sortable_th("IS Avg%", "num")}{sortable_th("IS Ann ROR %", "num")}
{sortable_th("OOS N", "num")}{sortable_th("OOS Avg%", "num")}{sortable_th("OOS Ann ROR %", "num")}
{sortable_th("Δ FULL Avg% vs ctrl", "num")}{sortable_th("Note", "text")}
</tr></thead><tbody>
<tr><td>CONTROL</td><td>atr=5, dist=off</td><td>{c_full['n']}</td><td>{_fmt_pct(c_full['avg_pnl_pct'])}</td><td>{_fmt_pct(c_full.get('ann_ror'))}</td><td>{c_is['n']}</td><td>{_fmt_pct(c_is['avg_pnl_pct'])}</td><td>{_fmt_pct(c_is.get('ann_ror'))}</td><td>{c_oos['n']}</td><td>{_fmt_pct(c_oos['avg_pnl_pct'])}</td><td>{_fmt_pct(c_oos.get('ann_ror'))}</td><td>+0.00</td><td></td></tr>
<tr><td>MINDIST_7.18</td><td>atr=5, dist=7.18</td><td>{a_full['n']}</td><td>{_fmt_pct(a_full['avg_pnl_pct'])}</td><td>{_fmt_pct(a_full.get('ann_ror'))}</td><td>{a_is['n']}</td><td>{_fmt_pct(a_is['avg_pnl_pct'])}</td><td>{_fmt_pct(a_is.get('ann_ror'))}</td><td>{a_oos['n']}</td><td>{_fmt_pct(a_oos['avg_pnl_pct'])}</td><td>{_fmt_pct(a_oos.get('ann_ror'))}</td><td>{_delta_pct(a_full['avg_pnl_pct'], c_full['avg_pnl_pct'])}</td><td>{html_mod.escape(research_718)}</td></tr>
<tr><td>MINDIST_7.18_NO_ATR</td><td>atr=0, dist=7.18 (research)</td><td>{n_full['n']}</td><td>{_fmt_pct(n_full['avg_pnl_pct'])}</td><td>{_fmt_pct(n_full.get('ann_ror'))}</td><td>{n_is['n']}</td><td>{_fmt_pct(n_is['avg_pnl_pct'])}</td><td>{_fmt_pct(n_is.get('ann_ror'))}</td><td>{n_oos['n']}</td><td>{_fmt_pct(n_oos['avg_pnl_pct'])}</td><td>{_fmt_pct(n_oos.get('ann_ror'))}</td><td>{_delta_pct(n_full['avg_pnl_pct'], c_full['avg_pnl_pct'])}</td><td>{html_mod.escape(research_noatr)}</td></tr>
</tbody></table>
<h2>IS / OOS / FULL (Closed overlay)</h2>
{_slice_table3(c_is, a_is, n_is, "IS", "in-sample selection", "research only")}
{_slice_table3(c_oos, a_oos, n_oos, "OOS", "report-only", "report-only / research")}
{_slice_table3(c_full, a_full, n_full, "FULL", research_718, research_noatr)}
<h2>FULL host Report / EquityMeta / Summary (canonical set)</h2>
<p class="meta">Click column headers to sort. Sheet $ / Total PnL $ omitted per compare rule.</p>
<table class="sortable"><thead><tr>{canon_th}</tr></thead><tbody>{canon_body}</tbody></table>
<h2>Exit mix (FULL Closed)</h2>
{_exit3(c_ex, a_ex, n_ex, int(c_full['n']), int(a_full['n']), int(n_full['n']))}
<script>{SORTABLE_TABLE_SCRIPT}</script>
</body></html>
"""
    (OUT_DIR / "compare.html").write_text(html, encoding="utf-8")
    (OUT_DIR / "summary_3arm.json").write_text(
        json.dumps(
            {
                "ctrl_ts": ctrl_ts,
                "cand_ts": cand_ts,
                "noatr_ts": noatr_ts,
                "research_718_vs_control": research_718,
                "research_noatr_vs_control": research_noatr,
                "dailyrun": "atr=5 + min_dist=7.18 (sibling wire); atr=0 not wired",
                "slices": {
                    k: {"control": v[0], "mindist_718": v[1], "mindist_718_no_atr": v[2]}
                    for k, v in packs.items()
                },
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"[rsi 3arm] wrote {OUT_DIR / 'compare.html'}")
    for name, sl in (
        ("CONTROL", (c_is, c_oos, c_full)),
        ("MINDIST_7.18", (a_is, a_oos, a_full)),
        ("MINDIST_7.18_NO_ATR", (n_is, n_oos, n_full)),
    ):
        i, o, f = sl
        print(
            f"  {name} FULL N={f['n']} Avg%={f['avg_pnl_pct']:.2f} | "
            f"IS N={i['n']} Avg%={i['avg_pnl_pct']:.2f} | "
            f"OOS N={o['n']} Avg%={o['avg_pnl_pct']:.2f}"
        )
    print(f"  noATR vs control: {research_noatr}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
