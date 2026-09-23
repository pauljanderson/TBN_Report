#!/usr/bin/env python3
"""6-arm RSI compare: existing 3 + ATR4/ATR3/ATR_2.93 no-dist overlays.

CONTROL / MINDIST_7.18 / MINDIST_7.18_NO_ATR stay live isolated stamps.
ATR4 / ATR3 / ATR_2.93 are Closed overlays on ATR0_NO_DIST (atr=0, no min_dist)
keep if ATR_PCT_AT_TRIGGER >= X. Not a DailyRun wire. House pin not stolen.
"""
from __future__ import annotations

import csv
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
    parse_number,
    slc,
    sortable_th,
    summary_pack,
    verdict,
)
from rsi_mindist52_718_3arm_compare_20260916 import _verdict_noatr  # noqa: E402

ASK1 = (
    "let's wire in min distance to 52 week high at 7.18, and run that through. "
    "send me a compare.html with the current defaults."
)
ASK2 = (
    "also do a compare with 7.18 for min DISTance to 52 week high, and remove "
    "the ATR min altogether. show these against the control"
)
ASK3 = (
    "thanks can you add atr4 and atr3 (with no min_dist) to the compare? "
    "and tell me what atr% will leave us with ~ 875 trades in the full sleeve? "
    "show that in compare too please."
)
PLAIN = (
    "Relative Strength Index (RSI) buys after a cool-off from hot. The first ask "
    "adds a distance-to-52-week-high floor of 7.18% and keeps the house Average "
    "True Range (ATR) floor of 5%. The second ask keeps that 7.18% distance floor "
    "but turns the ATR floor off (atr=0). This third ask keeps distance off and "
    "tries lower ATR floors: 4% and 3%, plus the ATR floor that leaves about 875 "
    "trades on the full 149-name house book. That hunt is an overlay on one "
    "atr=0 / no-distance run (not the 931-trade book, which still had distance "
    "7.18). DailyRun stays atr=5 + distance 7.18."
)

ATR_X = 2.93  # 1–2 decimal; overlay N closest to 875
TARGET_N = 875
ATR0_DIRNAME = "ATR0_NO_DIST"


def load_closed_atr(folder: Path, ts: str) -> list[dict[str, Any]]:
    path = folder / f"RSI_Closed_{ts}.csv"
    out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for raw in csv.DictReader(f):
            opened = None
            from rsi_mindist52_718_ab_20260916 import _parse_date, SHEET

            opened = _parse_date(raw.get("DATE_OPENED"))
            pnl = parse_number(raw.get("PNL_PCT"))
            atr = parse_number(raw.get("ATR_PCT_AT_TRIGGER"))
            if opened is None or pnl is None or atr is None:
                continue
            days = parse_number(raw.get("DAYS_HELD")) or 0.0
            pnl_d = parse_number(raw.get("PNL_DOLLARS"))
            if pnl_d is None:
                pnl_d = pnl / 100.0 * SHEET
            out.append(
                {
                    "symbol": str(raw.get("SYMBOL") or "").strip(),
                    "opened": opened,
                    "closed": _parse_date(raw.get("DATE_CLOSED")),
                    "pnl": pnl,
                    "pnl_d": pnl_d,
                    "days": days,
                    "exit": str(raw.get("EXIT_TYPE") or "").strip().upper(),
                    "atr": float(atr),
                }
            )
    return out


def overlay_atr(rows: list[dict[str, Any]], min_atr: float) -> list[dict[str, Any]]:
    return [r for r in rows if r.get("atr") is not None and float(r["atr"]) >= min_atr]


def _verdict_quality(c_full: dict, a_full: dict, c_oos: dict, a_oos: dict) -> str:
    return _verdict_noatr(c_full, a_full, c_oos, a_oos)


def _pack_as_report(st: dict) -> dict[str, Any]:
    """Closed-overlay pack → Report-shaped dict for count/quality rows only.

    Do not copy overlay Ann ROR / Max DD / Calmar / Sharpe / W/L $ into the
    host Report table — those use a different dollar-scale than live stamps.
    """
    return {
        "Total_Trades": st.get("n"),
        "Wins": st.get("wins"),
        "Losses": st.get("losses"),
        "Pct_Wins": st.get("win_pct"),
        "Avg_PNL_Pct": st.get("avg_pnl_pct"),
        "Expectancy": st.get("expectancy_d"),
        "Expectancy_Pct": st.get("expectancy_pct"),
        "Avg_Win_Pct": st.get("avg_win_pct"),
        "Avg_Loss_Pct": st.get("avg_loss_pct"),
        "Win_Loss_Ratio": st.get("wl_count"),
        "Profit_Factor": st.get("pf"),
        "Capital_Days": st.get("capital_days"),
        "Avg_Days_Held": st.get("avg_days"),
        "Median_Days_Held": st.get("median_days"),
        "P90_Days": st.get("p90_days"),
    }


def _canon_multi(
    arms: list[tuple[str, dict, dict, dict, Any]],
) -> list[tuple[str, ...]]:
    """arms[0] is control. Each: (label, report, eq, summary, wo)."""
    ctrl_label, c_rep, c_eq, c_sum, c_wo = arms[0]
    base = full_canonical_rows(
        c_rep, arms[1][1], c_eq, arms[1][2], c_sum, arms[1][3], c_wo, arms[1][4]
    )
    extras = []
    for lab, rep, eq, sm, wo in arms[2:]:
        extras.append(
            {row[0]: row for row in full_canonical_rows(c_rep, rep, c_eq, eq, c_sum, sm, c_wo, wo)}
        )
    out = []
    for label, cs, first_as, first_ds in base:
        cells = [label, cs, first_as]
        for ex in extras:
            nr = ex.get(label)
            cells.append(nr[2] if nr else "—")
        cells.append(first_ds)
        for ex in extras:
            nr = ex.get(label)
            cells.append(nr[3] if nr else "—")
        out.append(tuple(cells))
    return out


def _slice_table6(arms: list[tuple[str, str, dict]], sl: str, notes: list[str]) -> str:
    title = {
        "IS": "IS (entry &lt; 2024-01-01) — 7.18 / ATR floors shopped on full tape too",
        "OOS": "OOS (entry ≥ 2024-01-01) — report-only",
        "FULL": "FULL (all history) — overlay $10k/fill on $500k seed",
    }[sl]
    th = "".join(sortable_th(h, t) for h, t in SLICE_HEADERS)
    ctrl = arms[0][2]
    rows = []
    for (name, knob, st), note in zip(arms, notes):
        rows.append(arm_row(name, knob, st, ctrl, sl, note))
    return (
        f"<h3>{title}</h3>"
        f'<p class="meta">Click column headers to sort. Sheet $ / Total PnL $ omitted.</p>'
        f'<table class="sortable"><thead><tr>{th}</tr></thead><tbody>'
        + "".join(rows)
        + "</tbody></table>"
    )


def _exit6(arm_exits: list[tuple[str, Counter, int]]) -> str:
    keys = sorted(set().union(*(set(c) for _, c, _ in arm_exits)))
    headers = [("EXIT_TYPE", "text")]
    for name, _, _ in arm_exits:
        headers.append((f"{name} N", "num"))
        headers.append((f"{name} %", "num"))
    th = "".join(sortable_th(h, t) for h, t in headers)
    rows = []
    for k in keys:
        cells = [k]
        for _, cnt, n in arm_exits:
            c = cnt.get(k, 0)
            pct = 100.0 * c / n if n else 0.0
            cells.extend([c, f"{pct:.1f}%"])
        rows.append(
            "<tr>" + "".join(f"<td>{html_mod.escape(str(x))}</td>" for x in cells) + "</tr>"
        )
    return (
        '<table class="sortable"><thead><tr>'
        + th
        + "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _hunt_rows(atr0: list[dict[str, Any]]) -> list[tuple[float, int, float, int]]:
    pts = [2.8, 2.9, 2.93, 2.94, 3.0, 4.0, 5.0]
    out = []
    for x in pts:
        sub = overlay_atr(atr0, x)
        n = len(sub)
        avg = (sum(r["pnl"] for r in sub) / n) if n else 0.0
        out.append((x, n, avg, abs(n - TARGET_N)))
    return out


def main() -> int:
    ctrl_dir = OUT_DIR / "control"
    cand_dir = OUT_DIR / "candidate"
    noatr_dir = OUT_DIR / "MINDIST_7.18_NO_ATR"
    atr0_dir = OUT_DIR / ATR0_DIRNAME
    ctrl_ts = _latest_ts(ctrl_dir)
    cand_ts = _latest_ts(cand_dir)
    noatr_ts = _latest_ts(noatr_dir)
    atr0_ts = _latest_ts(atr0_dir)

    ctrl_all = load_closed(ctrl_dir, ctrl_ts)
    cand_all = load_closed(cand_dir, cand_ts)
    noatr_all = load_closed(noatr_dir, noatr_ts)
    atr0_raw = load_closed_atr(atr0_dir, atr0_ts)
    atr4_all = overlay_atr(atr0_raw, 4.0)
    atr3_all = overlay_atr(atr0_raw, 3.0)
    atrx_all = overlay_atr(atr0_raw, ATR_X)
    atr5_chk = overlay_atr(atr0_raw, 5.0)

    names = [
        ("CONTROL", "atr=5, dist=off", ctrl_all),
        ("MINDIST_7.18", "atr=5, dist=7.18", cand_all),
        ("MINDIST_7.18_NO_ATR", "atr=0, dist=7.18 (research)", noatr_all),
        ("ATR4_NO_DIST", "atr=4, dist=off (overlay)", atr4_all),
        ("ATR3_NO_DIST", "atr=3, dist=off (overlay)", atr3_all),
        (f"ATR_{ATR_X:g}_NO_DIST", f"atr={ATR_X:g}, dist=off (overlay ~{TARGET_N})", atrx_all),
    ]

    packs = {
        sl: [pack(slc(rows, sl)) for _, _, rows in names] for sl in ("IS", "OOS", "FULL")
    }
    c_full, a_full, n_full, a4_full, a3_full, ax_full = packs["FULL"]
    c_oos, a_oos, n_oos, a4_oos, a3_oos, ax_oos = packs["OOS"]
    c_is, a_is, n_is, a4_is, a3_is, ax_is = packs["IS"]

    research_718, wired = verdict(c_full, a_full, c_oos, a_oos, c_is, a_is)
    research_noatr = _verdict_quality(c_full, n_full, c_oos, n_oos)
    research_a4 = _verdict_quality(c_full, a4_full, c_oos, a4_oos)
    research_a3 = _verdict_quality(c_full, a3_full, c_oos, a3_oos)
    research_ax = _verdict_quality(c_full, ax_full, c_oos, ax_oos)

    notes_by_sl = {
        "IS": [
            "",
            "in-sample selection",
            "research only",
            "overlay / research",
            "overlay / research",
            "overlay / research",
        ],
        "OOS": [
            "",
            "report-only",
            "report-only / research",
            "report-only / overlay",
            "report-only / overlay",
            "report-only / overlay",
        ],
        "FULL": [
            "",
            research_718,
            research_noatr,
            research_a4,
            research_a3,
            research_ax,
        ],
    }

    c_rep = load_report(ctrl_dir, ctrl_ts)
    a_rep = load_report(cand_dir, cand_ts)
    n_rep = load_report(noatr_dir, noatr_ts)
    c_eq = load_equity_meta(ctrl_dir, ctrl_ts)
    a_eq = load_equity_meta(cand_dir, cand_ts)
    n_eq = load_equity_meta(noatr_dir, noatr_ts)
    c_sum = summary_pack(load_summary(ctrl_dir, ctrl_ts))
    a_sum = summary_pack(load_summary(cand_dir, cand_ts))
    n_sum = summary_pack(load_summary(noatr_dir, noatr_ts))
    a4_rep = _pack_as_report(a4_full)
    a3_rep = _pack_as_report(a3_full)
    ax_rep = _pack_as_report(ax_full)

    canon = _canon_multi(
        [
            ("CONTROL", c_rep, c_eq, c_sum, c_full.get("avg_wo_max")),
            ("MINDIST_7.18", a_rep, a_eq, a_sum, a_full.get("avg_wo_max")),
            ("NO_ATR", n_rep, n_eq, n_sum, n_full.get("avg_wo_max")),
            ("ATR4", a4_rep, {}, {}, a4_full.get("avg_wo_max")),
            ("ATR3", a3_rep, {}, {}, a3_full.get("avg_wo_max")),
            (f"ATR_{ATR_X:g}", ax_rep, {}, {}, ax_full.get("avg_wo_max")),
        ]
    )

    hunt = _hunt_rows(atr0_raw)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    def _line(label: str, st: dict) -> str:
        return (
            f"- **{label}** N={st['n']} WR={st['win_pct']:.2f}% "
            f"Avg%={st['avg_pnl_pct']:.2f} MaxDD={st['max_dd']:.2f}"
        )

    baseline = f"""# BASELINE — {STAMP}

**Status:** Six-arm ENTRY compare. DailyRun wired 7.18 + **atr=5**. New ATR floors are **research only** (Closed overlay on atr=0 / no-dist). **Not walk-forward gold.** OOS report-only.

## What you asked

> {ASK1}

> {ASK2}

> {ASK3}

## In plain English

{PLAIN}

## Honesty

- Live isolated stamps: CONTROL (atr=5, no dist) vs MINDIST_7.18 (atr=5, dist=7.18) vs MINDIST_7.18_NO_ATR (atr=0, dist=7.18).
- Overlay arms (same atr=0 / no-dist book `{atr0_ts}`): ATR4_NO_DIST, ATR3_NO_DIST, ATR_{ATR_X:g}_NO_DIST. Keep if `ATR_PCT_AT_TRIGGER` ≥ X. **Not** the 931 book (that one still had dist=7.18).
- Overlay ≠ live re-run if a skipped quiet fill would have freed the name for a later louder fill. Sanity: overlay ATR≥5 on this book is N={len(atr5_chk)} vs CONTROL live N={c_full['n']}.
- Freeze otherwise: ob=70 / os=30 / exit=70 / max_trigger=60 / ts=20 / next_open / house `rsi_universe.csv` 149 / full history (no `entry_end_date`).
- 7.18 and the ~875 ATR hunt are in-sample selection. OOS report-only. Do not retune on OOS.
- **DailyRun unchanged:** atr=5 + min_dist 7.18. Isolated `-o`; house pin / LatestRun not stolen (drive pin stayed `260916121011`).

## Arms

| Arm | Knob | Source | DailyRun? |
|-----|------|--------|-----------|
| CONTROL | atr=5, dist=off | live `{ctrl_ts}` | freeze before 7.18 wire |
| MINDIST_7.18 | atr=5, dist=7.18 | live `{cand_ts}` | preference wire (sibling) |
| MINDIST_7.18_NO_ATR | atr=0, dist=7.18 | live `{noatr_ts}` | **no — research only** |
| ATR4_NO_DIST | atr=4, dist=off | overlay on ATR0 `{atr0_ts}` | **no — research only** |
| ATR3_NO_DIST | atr=3, dist=off | overlay on ATR0 `{atr0_ts}` | **no — research only** |
| ATR_{ATR_X:g}_NO_DIST | atr={ATR_X:g}, dist=off (~{TARGET_N}) | overlay N={ax_full['n']} | **no — research only** |

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

### ATR4_NO_DIST — research only (overlay)
{_line("IS", a4_is)}
{_line("OOS", a4_oos)}
{_line("FULL", a4_full)}

- **Research verdict vs control:** {research_a4}

### ATR3_NO_DIST — research only (overlay)
{_line("IS", a3_is)}
{_line("OOS", a3_oos)}
{_line("FULL", a3_full)}

- **Research verdict vs control:** {research_a3}

### ATR_{ATR_X:g}_NO_DIST (~{TARGET_N} hunt) — research only (overlay)
{_line("IS", ax_is)}
{_line("OOS", ax_oos)}
{_line("FULL", ax_full)}

- **Hunt:** overlay ATR% ≥ **{ATR_X:g}** → Closed N=**{ax_full['n']}** (closest 0.01 step to {TARGET_N}; 1-decimal 2.9 → N=880).
- **Research verdict vs control:** {research_ax}
- **DailyRun:** still atr=5 + min_dist 7.18. These arms do **not** change DailyRun.
"""
    (OUT_DIR / "BASELINE.md").write_text(baseline, encoding="utf-8")

    canon_headers = [
        ("Metric", "text"),
        ("CONTROL (atr5, dist off)", "num"),
        ("MINDIST_7.18 (atr5)", "num"),
        ("MINDIST_7.18_NO_ATR (atr0, research)", "num"),
        ("ATR4_NO_DIST (overlay)", "num"),
        ("ATR3_NO_DIST (overlay)", "num"),
        (f"ATR_{ATR_X:g}_NO_DIST (overlay)", "num"),
        ("Δ 7.18−ctrl", "num"),
        ("Δ noATR−ctrl", "num"),
        ("Δ ATR4−ctrl", "num"),
        ("Δ ATR3−ctrl", "num"),
        (f"Δ ATR_{ATR_X:g}−ctrl", "num"),
    ]
    canon_th = "".join(sortable_th(h, t) for h, t in canon_headers)
    canon_body = "".join(
        "<tr>" + "".join(f"<td>{html_mod.escape(str(x))}</td>" for x in row) + "</tr>"
        for row in canon
    )

    hunt_th = "".join(
        sortable_th(h, t)
        for h, t in [
            ("ATR% floor", "num"),
            ("Overlay N", "num"),
            ("Overlay Avg%", "num"),
            ("|N−875|", "num"),
            ("Picked?", "text"),
        ]
    )
    hunt_body = "".join(
        "<tr>"
        + "".join(
            f"<td>{html_mod.escape(str(x))}</td>"
            for x in (
                f"{x:g}",
                n,
                f"{avg:.2f}%",
                d,
                "yes — closest to 875" if abs(x - ATR_X) < 1e-9 else "",
            )
        )
        + "</tr>"
        for x, n, avg, d in hunt
    )

    headline_rows = []
    knobs = [k for _, k, _ in names]
    fulls = [c_full, a_full, n_full, a4_full, a3_full, ax_full]
    iss = [c_is, a_is, n_is, a4_is, a3_is, ax_is]
    ooss = [c_oos, a_oos, n_oos, a4_oos, a3_oos, ax_oos]
    vnotes = ["", research_718, research_noatr, research_a4, research_a3, research_ax]
    for (name, _, _), knob, f, i, o, note in zip(names, knobs, fulls, iss, ooss, vnotes):
        headline_rows.append(
            "<tr>"
            + "".join(
                f"<td>{html_mod.escape(str(x))}</td>"
                for x in (
                    name,
                    knob,
                    f["n"],
                    _fmt_pct(f["avg_pnl_pct"]),
                    _fmt_pct(f.get("ann_ror")),
                    i["n"],
                    _fmt_pct(i["avg_pnl_pct"]),
                    _fmt_pct(i.get("ann_ror")),
                    o["n"],
                    _fmt_pct(o["avg_pnl_pct"]),
                    _fmt_pct(o.get("ann_ror")),
                    _delta_pct(f["avg_pnl_pct"], c_full["avg_pnl_pct"]),
                    note,
                )
            )
            + "</tr>"
        )

    slice_arms_full = [(n, k, packs["FULL"][i]) for i, (n, k, _) in enumerate(names)]
    slice_arms_is = [(n, k, packs["IS"][i]) for i, (n, k, _) in enumerate(names)]
    slice_arms_oos = [(n, k, packs["OOS"][i]) for i, (n, k, _) in enumerate(names)]

    exits = [
        ("CONTROL", Counter(c_full.get("exits") or {}), int(c_full["n"])),
        ("MINDIST_7.18", Counter(a_full.get("exits") or {}), int(a_full["n"])),
        ("NO_ATR", Counter(n_full.get("exits") or {}), int(n_full["n"])),
        ("ATR4", Counter(a4_full.get("exits") or {}), int(a4_full["n"])),
        ("ATR3", Counter(a3_full.get("exits") or {}), int(a3_full["n"])),
        (f"ATR_{ATR_X:g}", Counter(ax_full.get("exits") or {}), int(ax_full["n"])),
    ]

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>{STAMP} — 6-arm ATR floors</title>
<style>
{SORTABLE_TH_CSS}
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 1.5rem; color: #0f172a; background: #f8fafc; }}
h1 {{ font-size: 1.4rem; margin: 0 0 .35rem; }}
h2 {{ font-size: 1.12rem; margin: 1.5rem 0 .45rem; border-bottom: 1px solid #cbd5e1; padding-bottom: .25rem; }}
.meta {{ color: #475569; font-size: .92rem; max-width: 110rem; }}
.insight {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: .75rem 1rem; margin: .75rem 0; max-width: 110rem; }}
.ask {{ background: #eff6ff; border: 1px solid #bfdbfe; }}
table.sortable {{ border-collapse: collapse; background: #fff; font-size: .76rem; margin: .5rem 0 1rem; }}
table.sortable th, table.sortable td {{ border: 1px solid #e2e8f0; padding: .32rem .5rem; }}
table.sortable th {{ background: #f1f5f9; }}
.badge {{ display: inline-block; padding: .1rem .45rem; border-radius: 4px; font-size: .8rem; background: #e2e8f0; }}
.caveat {{ color: #9a3412; font-size: .9rem; }}
blockquote.meta {{ margin: .4rem 0 0; padding-left: .8rem; border-left: 3px solid #93c5fd; }}
</style></head><body>
<h1>RSI min-dist 7.18 plus ATR 4 / 3 / 2.93 (no distance) vs control</h1>
<p class="badge">Six-arm ENTRY compare · DailyRun = 7.18 + atr=5 · new ATR floors research overlay only · not walk-forward gold · OOS report-only</p>
<p class="meta">Stamp <code>{html_mod.escape(STAMP)}</code> · {html_mod.escape(now)} · Click column headers to sort</p>
<div class="insight ask">
<h2 style="margin-top:0;border:0">What you asked</h2>
<blockquote class="meta">{html_mod.escape(ASK1)}</blockquote>
<blockquote class="meta">{html_mod.escape(ASK2)}</blockquote>
<blockquote class="meta">{html_mod.escape(ASK3)}</blockquote>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN)}</p>
</div>
<div class="insight">
<p><strong>MINDIST_7.18 vs control (research):</strong> {html_mod.escape(research_718)}</p>
<p><strong>MINDIST_7.18_NO_ATR vs control (research only):</strong> {html_mod.escape(research_noatr)}</p>
<p><strong>ATR4_NO_DIST vs control (research only):</strong> {html_mod.escape(research_a4)}</p>
<p><strong>ATR3_NO_DIST vs control (research only):</strong> {html_mod.escape(research_a3)}</p>
<p><strong>ATR_{ATR_X:g}_NO_DIST vs control (research only):</strong> {html_mod.escape(research_ax)}</p>
<p><strong>~875 hunt:</strong> on the atr=0 / no-distance full sleeve (Closed N={len(atr0_raw)}),
Average True Range (ATR) % at trigger ≥ <strong>{ATR_X:g}</strong> leaves <strong>{ax_full['n']}</strong> fills
(closest 0.01 step to 875; 1-decimal 2.9 leaves 880). Overlay Avg% {html_mod.escape(_fmt_pct(ax_full['avg_pnl_pct']))}
vs control {html_mod.escape(_fmt_pct(c_full['avg_pnl_pct']))}.</p>
<p><strong>DailyRun:</strong> {html_mod.escape(wired)} ATR min stays <strong>5</strong> and min distance stays <strong>7.18</strong>.</p>
<p class="caveat"><strong>Selection honesty:</strong> 7.18 and the ~875 ATR hunt were picked after seeing the books
(in-sample selection). OOS is report-only. ATR4 / ATR3 / ATR {ATR_X:g} are Closed overlays on one
atr=0 no-distance run — not live occupancy re-runs. Overlay ATR≥5 N={len(atr5_chk)} matches CONTROL live N={c_full['n']}.</p>
<p class="meta">CONTROL <code>{html_mod.escape(ctrl_ts)}</code> · MINDIST_7.18 <code>{html_mod.escape(cand_ts)}</code> ·
NO_ATR <code>{html_mod.escape(noatr_ts)}</code> · ATR0_NO_DIST <code>{html_mod.escape(atr0_ts)}</code>
· Isolated <code>-o</code> (house pin / LatestRun not stolen).</p>
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
{"".join(headline_rows)}
</tbody></table>
<h2>ATR% hunt for ~875 trades (overlay on atr=0 / no-dist)</h2>
<p class="meta">Click column headers to sort. Same ATR0_NO_DIST Closed book. Picked ATR% = {ATR_X:g} (N={ax_full['n']}).</p>
<table class="sortable"><thead><tr>{hunt_th}</tr></thead><tbody>{hunt_body}</tbody></table>
<h2>IS / OOS / FULL (Closed overlay)</h2>
{_slice_table6(slice_arms_is, "IS", notes_by_sl["IS"])}
{_slice_table6(slice_arms_oos, "OOS", notes_by_sl["OOS"])}
{_slice_table6(slice_arms_full, "FULL", notes_by_sl["FULL"])}
<h2>FULL host Report / EquityMeta / Summary (canonical set)</h2>
<p class="meta">Click column headers to sort. Sheet $ / Total PnL $ omitted. ATR4 / ATR3 / ATR_{ATR_X:g}
use Closed-overlay pack (no separate host Report / Paul–FIT Summary).</p>
<table class="sortable"><thead><tr>{canon_th}</tr></thead><tbody>{canon_body}</tbody></table>
<h2>Exit mix (FULL Closed)</h2>
{_exit6(exits)}
<script>{SORTABLE_TABLE_SCRIPT}</script>
</body></html>
"""
    (OUT_DIR / "compare.html").write_text(html, encoding="utf-8")
    (OUT_DIR / "summary_6arm.json").write_text(
        json.dumps(
            {
                "ctrl_ts": ctrl_ts,
                "cand_ts": cand_ts,
                "noatr_ts": noatr_ts,
                "atr0_ts": atr0_ts,
                "atr_x": ATR_X,
                "atr_x_n": ax_full["n"],
                "atr0_n": len(atr0_raw),
                "overlay_atr5_n": len(atr5_chk),
                "research_718_vs_control": research_718,
                "research_noatr_vs_control": research_noatr,
                "research_atr4_vs_control": research_a4,
                "research_atr3_vs_control": research_a3,
                "research_atrx_vs_control": research_ax,
                "dailyrun": "atr=5 + min_dist=7.18 (sibling wire); new ATR floors not wired",
                "slices": {
                    k: {
                        "control": v[0],
                        "mindist_718": v[1],
                        "mindist_718_no_atr": v[2],
                        "atr4_no_dist": v[3],
                        "atr3_no_dist": v[4],
                        f"atr_{ATR_X:g}_no_dist": v[5],
                    }
                    for k, v in packs.items()
                },
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"[rsi 6arm] wrote {OUT_DIR / 'compare.html'}")
    print(f"  ATR0_NO_DIST {atr0_ts} N={len(atr0_raw)} overlay ATR>=5 N={len(atr5_chk)}")
    print(f"  ATR% for ~{TARGET_N}: {ATR_X:g} -> N={ax_full['n']} Avg%={ax_full['avg_pnl_pct']:.2f}")
    for name, sl in (
        ("CONTROL", (c_is, c_oos, c_full)),
        ("MINDIST_7.18", (a_is, a_oos, a_full)),
        ("MINDIST_7.18_NO_ATR", (n_is, n_oos, n_full)),
        ("ATR4_NO_DIST", (a4_is, a4_oos, a4_full)),
        ("ATR3_NO_DIST", (a3_is, a3_oos, a3_full)),
        (f"ATR_{ATR_X:g}_NO_DIST", (ax_is, ax_oos, ax_full)),
    ):
        i, o, f = sl
        print(
            f"  {name} FULL N={f['n']} Avg%={f['avg_pnl_pct']:.2f} | "
            f"IS N={i['n']} Avg%={i['avg_pnl_pct']:.2f} | "
            f"OOS N={o['n']} Avg%={o['avg_pnl_pct']:.2f}"
        )
    print(f"  ATR4 vs control: {research_a4}")
    print(f"  ATR3 vs control: {research_a3}")
    print(f"  ATR_{ATR_X:g} vs control: {research_ax}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
