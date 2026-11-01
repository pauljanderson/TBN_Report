#!/usr/bin/env python3
"""Scalp: per-symbol control summary + shorts-only AB vs long+short control.

Uses stamped control LOD/HOD ±0.1% book (prefer identity over setup_bar rescore).
Arm A = long+short control. Arm B = side==short only (same exits).

Usage:
  python tools/scalp_shorts_only_symbol_summary.py
  python tools/scalp_shorts_only_symbol_summary.py --stamp scalp_shorts_only_and_symbol_summary_20260827
  python tools/scalp_shorts_only_symbol_summary.py --rescan --all   # rebuild control via CLI path
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import math
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "stock_analysis"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

import scalp_open15_reversal_ab as ab  # noqa: E402
from compare_format import format_money  # noqa: E402

DRIVE = ROOT / "drive"
DEFAULT_STAMP = "scalp_shorts_only_and_symbol_summary_20260827"
CONTROL_SOURCE_STAMP = "scalp_full_levers_20260822"
CONTROL_TRADES_REL = f"paul_experiments/{CONTROL_SOURCE_STAMP}/trades_control.csv"
MIN_N_RANK = 5  # require ≥5 trades to rank top/bottom quality
MIN_N_ALT = 3  # secondary mention threshold
SYSTEM = "scalp"


def _coerce_trade(row: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = dict(row)
    for k in (
        "pnl_pct",
        "pnl_usd",
        "shares",
        "entry",
        "stop",
        "target",
        "exit",
        "r_mult",
        "lod",
        "hod",
        "setup_h",
        "setup_l",
        "atr_prior",
        "adv_prior",
        "open15_o",
        "open15_h",
        "open15_l",
        "open15_c",
        "open15_range",
        "range_vs_atr",
        "open15_body_frac",
        "open15_upper_wick_frac",
        "open15_lower_wick_frac",
    ):
        v = out.get(k)
        if v in ("", None):
            continue
        try:
            out[k] = float(v)
        except (TypeError, ValueError):
            pass
    return out


def load_control_trades(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as f:
        return [_coerce_trade(r) for r in csv.DictReader(f)]


def per_symbol_rows(trades: list[dict[str, Any]], *, min_n_rank: int) -> list[dict[str, Any]]:
    by_sym: dict[str, list[dict[str, Any]]] = {}
    for t in trades:
        by_sym.setdefault(str(t.get("symbol") or ""), []).append(t)
    rows: list[dict[str, Any]] = []
    for sym, ts in by_sym.items():
        if not sym:
            continue
        pnls = [float(x["pnl_pct"]) for x in ts]
        usds = [float(x["pnl_usd"]) for x in ts]
        n = len(ts)
        wins = sum(1 for p in pnls if p > 0)
        w_usd = [u for u in usds if u > 0]
        l_usd = [u for u in usds if u <= 0]
        gw, gl = sum(w_usd), abs(sum(l_usd))
        pf = (gw / gl) if gl > 0 else (float("inf") if gw > 0 else float("nan"))
        avg = float(sum(pnls) / n) if n else float("nan")
        n_long = sum(1 for x in ts if x.get("side") == "long")
        n_short = sum(1 for x in ts if x.get("side") == "short")
        sessions = sorted({str(x.get("session") or "")[:10] for x in ts if x.get("session")})
        thin = n < min_n_rank
        if thin:
            label = "thin_N"
        elif math.isfinite(avg) and avg > 0 and (not math.isfinite(pf) or pf >= 1.0):
            label = "worked_well"
        elif math.isfinite(avg) and avg < 0:
            label = "soft_or_neg"
        else:
            label = "flat_mixed"
        # Quality score for ranking: Avg PnL% primary, PF secondary (rankable symbols only)
        rows.append(
            {
                "symbol": sym,
                "N": n,
                "Win%": 100.0 * wins / n if n else float("nan"),
                "Avg_PnL_%": avg,
                "Sum_PnL_$": sum(usds),
                "Profit_Factor": pf,
                "n_long": n_long,
                "n_short": n_short,
                "session_min": sessions[0] if sessions else "",
                "session_max": sessions[-1] if sessions else "",
                "label": label,
                "rank_eligible": not thin,
            }
        )
    rows.sort(
        key=lambda r: (
            float(r["Avg_PnL_%"]) if isinstance(r["Avg_PnL_%"], float) and math.isfinite(r["Avg_PnL_%"]) else -999.0,
            float(r["Sum_PnL_$"]) if isinstance(r["Sum_PnL_$"], float) else 0.0,
        ),
        reverse=True,
    )
    return rows


def pick_shorts_verdict(ctrl: dict[str, Any], short: dict[str, Any]) -> str:
    """Quality over N; research only. Shorts may cut N a lot — say so."""
    cn = int(ctrl.get("N") or 0)
    sn = int(short.get("N") or 0)
    if sn < 50 or cn < 50:
        return "HOLD - shorts-only thin N on short Yahoo 1m window (research only; not DailyRun)"
    c_avg = ctrl.get("Avg_PnL_%")
    s_avg = short.get("Avg_PnL_%")
    c_pf = ctrl.get("Profit_Factor")
    s_pf = short.get("Profit_Factor")
    c_dd = ctrl.get("Max_DD_%")
    s_dd = short.get("Max_DD_%")
    if not (
        isinstance(c_avg, float)
        and isinstance(s_avg, float)
        and math.isfinite(c_avg)
        and math.isfinite(s_avg)
    ):
        return "HOLD - insufficient Avg PnL% for shorts-only compare"

    drop = (cn - sn) / cn if cn else 0.0
    dd_ok = True
    if isinstance(s_dd, float) and isinstance(c_dd, float) and math.isfinite(s_dd) and math.isfinite(c_dd):
        dd_ok = abs(s_dd) <= abs(c_dd) * 1.15 + 0.5
    pf_ok = (
        not isinstance(s_pf, float)
        or not isinstance(c_pf, float)
        or not math.isfinite(s_pf)
        or not math.isfinite(c_pf)
        or s_pf >= c_pf - 0.05
    )
    better = (s_avg > c_avg + 0.01) and pf_ok and dd_ok
    worse = s_avg < c_avg - 0.02

    note = f"N cut {drop*100:.0f}% ({cn}->{sn}); full-sample only (canonical IS/OOS N/A)."
    if worse:
        return f"DISMISS - shorts-only Avg PnL% worse than long+short control. {note} Research only."
    if better:
        return (
            f"LEAN KEEP - shorts-only improves Avg PnL% / PF / DD vs long+short on this short window. "
            f"{note} Research candidate only - not gold, not DailyRun; by-side selection bias labeled."
        )
    return f"HOLD - shorts-only flat/mixed vs long+short. {note} Research only."


def _num_cell(v: Any, nd: int = 2) -> str:
    return f"<td>{ab._fmt_num(v, nd)}</td>"


def _money_cell(v: Any) -> str:
    if isinstance(v, (int, float)) and math.isfinite(v):
        return f"<td>{format_money(v)}</td>"
    return "<td>—</td>"


def write_symbol_summary_html(
    path: Path,
    *,
    stamp: str,
    book_note: str,
    cov: str,
    rows: list[dict[str, Any]],
    min_n: int,
    top: list[dict[str, Any]],
    bottom: list[dict[str, Any]],
    ctrl_m: dict[str, Any],
) -> None:
    cols = [
        ("rank", "num"),
        ("symbol", "text"),
        ("N", "num"),
        ("Win%", "num"),
        ("Avg_PnL_%", "num"),
        ("Sum_PnL_$", "money"),
        ("Profit_Factor", "num"),
        ("n_long", "num"),
        ("n_short", "num"),
        ("session_min", "date"),
        ("session_max", "date"),
        ("label", "text"),
    ]
    head = "".join(ab.sortable_th(c, t) for c, t in cols)
    body = []
    for i, r in enumerate(rows, 1):
        cls = ""
        if r.get("label") == "worked_well":
            cls = ' class="top"'
        elif r.get("label") == "soft_or_neg" and r.get("rank_eligible"):
            cls = ' class="bot"'
        cells = [
            f"<td>{i}</td>",
            f"<td>{html_mod.escape(str(r['symbol']))}</td>",
            f"<td>{int(r['N'])}</td>",
            _num_cell(r.get("Win%"), 2),
            _num_cell(r.get("Avg_PnL_%"), 4),
            _money_cell(r.get("Sum_PnL_$")),
            _num_cell(r.get("Profit_Factor"), 2),
            f"<td>{int(r['n_long'])}</td>",
            f"<td>{int(r['n_short'])}</td>",
            f"<td>{html_mod.escape(str(r.get('session_min') or ''))}</td>",
            f"<td>{html_mod.escape(str(r.get('session_max') or ''))}</td>",
            f"<td>{html_mod.escape(str(r.get('label') or ''))}</td>",
        ]
        body.append(f"<tr{cls}>" + "".join(cells) + "</tr>")

    def _hl_table(title: str, subset: list[dict[str, Any]]) -> str:
        h = "".join(ab.sortable_th(c, t) for c, t in cols[1:])  # no rank col
        b = []
        for r in subset:
            cells = [
                f"<td>{html_mod.escape(str(r['symbol']))}</td>",
                f"<td>{int(r['N'])}</td>",
                _num_cell(r.get("Win%"), 2),
                _num_cell(r.get("Avg_PnL_%"), 4),
                _money_cell(r.get("Sum_PnL_$")),
                _num_cell(r.get("Profit_Factor"), 2),
                f"<td>{int(r['n_long'])}</td>",
                f"<td>{int(r['n_short'])}</td>",
                f"<td>{html_mod.escape(str(r.get('session_min') or ''))}</td>",
                f"<td>{html_mod.escape(str(r.get('session_max') or ''))}</td>",
                f"<td>{html_mod.escape(str(r.get('label') or ''))}</td>",
            ]
            b.append("<tr>" + "".join(cells) + "</tr>")
        return f"""<h2>{html_mod.escape(title)}</h2>
<table class="sortable">
<thead><tr>{h}</tr></thead>
<tbody>{''.join(b) or "<tr><td colspan='11'>None</td></tr>"}</tbody>
</table>"""

    metric_bits = (
        f"N={ctrl_m.get('N')} · WR%={ab._fmt_num(ctrl_m.get('Win%'))} · "
        f"AvgPnL%={ab._fmt_num(ctrl_m.get('Avg_PnL_%'), 4)} · "
        f"PF={ab._fmt_num(ctrl_m.get('Profit_Factor'))} · "
        f"PnL$={format_money(ctrl_m.get('Total_PnL_$') or 0)}"
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Scalp per-symbol summary — {html_mod.escape(stamp)}</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 1rem 1.25rem; color: #0f172a; background: #f8fafc; }}
h1,h2 {{ color: #0f172a; font-size: 1.2rem; }}
.note {{ background: #fff7ed; border-left: 4px solid #f97316; padding: .75rem 1rem; margin: 1rem 0; font-size: .92rem; }}
table {{ border-collapse: collapse; width: 100%; background: #fff; margin: .75rem 0 1.25rem; font-size: .82rem; }}
th, td {{ border: 1px solid #cbd5e1; padding: .3rem .4rem; text-align: left; }}
th {{ background: #e2e8f0; }}
tr.top {{ background: #ecfdf5; }}
tr.bot {{ background: #fef2f2; }}
{ab.SORT_CSS}
code {{ background: #e2e8f0; padding: .1rem .3rem; border-radius: 3px; }}
</style>
</head>
<body>
<h1>Scalp — which stocks work (per-symbol)</h1>
<p>Stamp <code>{html_mod.escape(stamp)}</code> · System <code>{SYSTEM}</code> · <strong>research only</strong> (not gold, not DailyRun)</p>
<p><strong>Book:</strong> {html_mod.escape(book_note)}</p>
<p><strong>Control book metrics:</strong> {html_mod.escape(metric_bits)}</p>
<div class="note">
<strong>Acronyms.</strong> LOD = Low of Day (so far through setup); HOD = High of Day (so far);
WR% = Win Rate percent; PF = Profit Factor; ATR = Average True Range; ADV$ = Average Dollar Volume;
IS/OOS = In-Sample / Out-Of-Sample.<br/>
<strong>Rank threshold:</strong> top/bottom highlights require <strong>N ≥ {min_n}</strong> trades
(thin_N otherwise). Quality primary = Avg PnL%; PF and Sum PnL$ secondary.
Click column headers to sort.<br/>
<strong>Coverage.</strong> {html_mod.escape(cov)}
</div>
{_hl_table(f"Top symbols (N≥{min_n}, by Avg PnL%)", top)}
{_hl_table(f"Bottom symbols (N≥{min_n}, by Avg PnL%)", bottom)}
<h2>All symbols</h2>
<p>Green = worked_well (N≥{min_n}, Avg PnL% &gt; 0). Red = soft_or_neg with N≥{min_n}.</p>
<table class="sortable">
<thead><tr>{head}</tr></thead>
<tbody>{''.join(body) or "<tr><td colspan='12'>No rows</td></tr>"}</tbody>
</table>
{ab.SORT_JS}
</body>
</html>"""
    path.write_text(html, encoding="utf-8")


def write_compare_html(
    path: Path,
    *,
    stamp: str,
    book_note: str,
    cov: str,
    ctrl_m: dict[str, Any],
    short_m: dict[str, Any],
    long_m: dict[str, Any],
    verdict: str,
) -> None:
    cols = [
        ("arm", "text"),
        ("N", "num"),
        ("Wins", "num"),
        ("Losses", "num"),
        ("Win%", "num"),
        ("Avg_PnL_%", "num"),
        ("AVG_PNL_PCT_WO_MAX", "num"),
        ("Profit_Factor", "num"),
        ("Total_PnL_$", "money"),
        ("Sheet_PnL_$", "money"),
        ("Expectancy_%", "num"),
        ("Max_DD_%", "num"),
        ("Ann_ROR_%", "num"),
        ("ΔN_vs_ctrl", "num"),
        ("ΔAvg_PnL_%", "num"),
        ("ΔPF", "num"),
        ("ΔMax_DD_%", "num"),
        ("verdict", "text"),
    ]

    def row_for(arm: str, m: dict[str, Any], verd: str = "") -> dict[str, Any]:
        d: dict[str, Any] = {"arm": arm, "verdict": verd}
        for k in (
            "N",
            "Wins",
            "Losses",
            "Win%",
            "Avg_PnL_%",
            "AVG_PNL_PCT_WO_MAX",
            "Profit_Factor",
            "Total_PnL_$",
            "Sheet_PnL_$",
            "Expectancy_%",
            "Max_DD_%",
            "Ann_ROR_%",
        ):
            d[k] = m.get(k)
        if arm == "A_control_long_short":
            d["ΔN_vs_ctrl"] = 0
            d["ΔAvg_PnL_%"] = 0.0
            d["ΔPF"] = 0.0
            d["ΔMax_DD_%"] = 0.0
        else:
            d["ΔN_vs_ctrl"] = int(m.get("N") or 0) - int(ctrl_m.get("N") or 0)
            for src, dst in (
                ("Avg_PnL_%", "ΔAvg_PnL_%"),
                ("Profit_Factor", "ΔPF"),
                ("Max_DD_%", "ΔMax_DD_%"),
            ):
                a, b = m.get(src), ctrl_m.get(src)
                if (
                    isinstance(a, (int, float))
                    and isinstance(b, (int, float))
                    and math.isfinite(float(a))
                    and math.isfinite(float(b))
                ):
                    d[dst] = float(a) - float(b)
                else:
                    d[dst] = float("nan")
        return d

    rows = [
        row_for("A_control_long_short", ctrl_m, "control"),
        row_for("B_shorts_only", short_m, verdict),
        row_for("descriptive_longs_only", long_m, "descriptive (not AB arm)"),
    ]
    head = "".join(ab.sortable_th(c, t) for c, t in cols)
    body = []
    for r in rows:
        cells = []
        for c, t in cols:
            v = r.get(c, "")
            if c == "arm" or c == "verdict":
                cells.append(f"<td>{html_mod.escape(str(v))}</td>")
            elif t == "money":
                cells.append(_money_cell(v))
            elif c in ("N", "Wins", "Losses", "ΔN_vs_ctrl") and isinstance(v, (int, float)):
                cells.append(f"<td>{int(v)}</td>")
            elif "PnL" in c or c.startswith("ΔAvg") or c == "Expectancy_%":
                cells.append(_num_cell(v, 4))
            else:
                cells.append(_num_cell(v, 2))
        body.append("<tr>" + "".join(cells) + "</tr>")

    # Exit mix slice
    def exit_mix_html(title: str, m: dict[str, Any]) -> str:
        em = m.get("exit_mix") or {}
        if not em:
            return f"<h2>{html_mod.escape(title)}</h2><p>No exit mix.</p>"
        h = ab.sortable_th("exit_type", "text") + ab.sortable_th("N", "num")
        b = "".join(
            f"<tr><td>{html_mod.escape(str(k))}</td><td>{int(v)}</td></tr>"
            for k, v in sorted(em.items(), key=lambda kv: -int(kv[1]))
        )
        return f"""<h2>{html_mod.escape(title)}</h2>
<table class="sortable"><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Scalp shorts-only AB — {html_mod.escape(stamp)}</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 1rem 1.25rem; color: #0f172a; background: #f8fafc; }}
h1,h2 {{ color: #0f172a; font-size: 1.2rem; }}
.note {{ background: #fff7ed; border-left: 4px solid #f97316; padding: .75rem 1rem; margin: 1rem 0; font-size: .92rem; }}
.verdict {{ font-weight: 600; margin: .5rem 0; }}
table {{ border-collapse: collapse; width: 100%; background: #fff; margin: .75rem 0 1.25rem; font-size: .82rem; }}
th, td {{ border: 1px solid #cbd5e1; padding: .3rem .4rem; text-align: left; }}
th {{ background: #e2e8f0; }}
{ab.SORT_CSS}
code {{ background: #e2e8f0; padding: .1rem .3rem; border-radius: 3px; }}
</style>
</head>
<body>
<h1>Scalp — shorts-only vs long+short control</h1>
<p>Stamp <code>{html_mod.escape(stamp)}</code> · <strong>research only</strong></p>
<p><strong>Book:</strong> {html_mod.escape(book_note)}</p>
<p class="verdict">Verdict: {html_mod.escape(verdict)}</p>
<div class="note">
<strong>Arms.</strong> A = control long+short (LOD/HOD ±0.1% stop, open-15 target, 11:30 time-stop).
B = same book filtered to <code>side=short</code> (equivalent to <code>--sides short</code> on entry gate).
Longs-only row is descriptive only.<br/>
<strong>IS/OOS:</strong> Canonical chronological split (entry &lt; 2024-01-01) is <strong>N/A</strong> —
Yahoo 1-minute history is short and entirely post-2024. Full-sample metrics only.<br/>
<strong>Coverage.</strong> {html_mod.escape(cov)}<br/>
Click column headers to sort. Quality over trade count; research ≠ gold ≠ DailyRun.
</div>
<h2>Arm compare (canonical-ish book metrics)</h2>
<table class="sortable">
<thead><tr>{head}</tr></thead>
<tbody>{''.join(body)}</tbody>
</table>
{exit_mix_html("Exit mix — control (A)", ctrl_m)}
{exit_mix_html("Exit mix — shorts-only (B)", short_m)}
{ab.SORT_JS}
</body>
</html>"""
    path.write_text(html, encoding="utf-8")


def write_baseline(
    path: Path,
    *,
    stamp: str,
    book_note: str,
    cov: str,
    ctrl_m: dict[str, Any],
    short_m: dict[str, Any],
    verdict: str,
    min_n: int,
) -> None:
    text = f"""# BASELINE — Scalp shorts-only + symbol summary — `{stamp}`

**System:** `{SYSTEM}` · research only · **not** DailyRun · **not** gold.

## Control book (identity)

| Item | Value |
|------|--------|
| Source trades | `{book_note}` |
| Prior freeze stamp | `{CONTROL_SOURCE_STAMP}` |
| Entry / exit freeze | Same as full-levers BASELINE |
| Sides (Arm A) | **long+short** |
| Stop | Long: **0.1% below LOD**; Short: **0.1% above HOD** |
| Target | open-15 opposite extreme |
| Time stop | **11:30 ET** bar open |
| Sheet | $45,000 / trade · 0 bps |

**Why not `scalp_rescore_20260827`?** That rescore uses stop arm **setup_bar_0p05**, not the
stamped control LOD/HOD identity. This stamp prefers control identity; rescore remains a
separate research book with a longer session span (through ~2026-08-26).

## Arms

| Arm | Definition |
|-----|------------|
| A_control_long_short | Full control book |
| B_shorts_only | Same trades with `side=short` only (CLI equivalent: `python tools/scalp_open15_reversal_ab.py --all --sides short`) |

## Per-symbol summary

- Rank / top-bottom highlight require **N ≥ {min_n}** (document: thin below that).
- Secondary mention threshold N ≥ {MIN_N_ALT} appears in SUMMARY only.
- Quality primary = Avg PnL%; PF / Sum PnL$ secondary.

## Coverage / IS-OOS honesty

{cov}

- Control N={ctrl_m.get('N')} · Shorts-only N={short_m.get('N')}
- Canonical IS (`entry_date < 2024-01-01`) / OOS: **N/A** (Yahoo 1m short window, all post-2024).
- Report **full-sample only**. Do not invent a fake OOS.

## Verdict

**Shorts-only vs control:** {verdict}

## Artifacts

- `symbol_summary.html` / `symbol_summary.csv`
- `compare.html` / `metrics_ab.csv`
- `trades_control.csv` (copy) / `trades_shorts_only.csv`
"""
    path.write_text(text, encoding="utf-8")


def write_summary_md(
    path: Path,
    *,
    stamp: str,
    book_note: str,
    cov: str,
    ctrl_m: dict[str, Any],
    short_m: dict[str, Any],
    long_m: dict[str, Any],
    verdict: str,
    top: list[dict[str, Any]],
    bottom: list[dict[str, Any]],
    min_n: int,
) -> None:
    def line(r: dict[str, Any]) -> str:
        return (
            f"- **{r['symbol']}** N={r['N']} WR%={ab._fmt_num(r.get('Win%'))} "
            f"AvgPnL%={ab._fmt_num(r.get('Avg_PnL_%'), 4)} PF={ab._fmt_num(r.get('Profit_Factor'))} "
            f"long={r['n_long']}/short={r['n_short']}"
        )

    text = f"""# SUMMARY — `{stamp}`

**Research only** · Scalp morning open-15 reversal · control LOD/HOD ±0.1%.

## Book used

{book_note}

Coverage: {cov}

## Shorts-only vs control

| Arm | N | WR% | Avg PnL% | PF | PnL$ | Max DD% |
|-----|---|-----|----------|----|------|---------|
| A long+short | {ctrl_m.get('N')} | {ab._fmt_num(ctrl_m.get('Win%'))} | {ab._fmt_num(ctrl_m.get('Avg_PnL_%'), 4)} | {ab._fmt_num(ctrl_m.get('Profit_Factor'))} | {format_money(ctrl_m.get('Total_PnL_$') or 0)} | {ab._fmt_num(ctrl_m.get('Max_DD_%'))} |
| B shorts-only | {short_m.get('N')} | {ab._fmt_num(short_m.get('Win%'))} | {ab._fmt_num(short_m.get('Avg_PnL_%'), 4)} | {ab._fmt_num(short_m.get('Profit_Factor'))} | {format_money(short_m.get('Total_PnL_$') or 0)} | {ab._fmt_num(short_m.get('Max_DD_%'))} |
| longs-only (desc.) | {long_m.get('N')} | {ab._fmt_num(long_m.get('Win%'))} | {ab._fmt_num(long_m.get('Avg_PnL_%'), 4)} | {ab._fmt_num(long_m.get('Profit_Factor'))} | {format_money(long_m.get('Total_PnL_$') or 0)} | {ab._fmt_num(long_m.get('Max_DD_%'))} |

**Verdict:** {verdict}

IS/OOS: canonical split N/A — full-sample only.

## Top symbols (N≥{min_n}, by Avg PnL%)

{chr(10).join(line(r) for r in top) or '_none_'}

## Bottom symbols (N≥{min_n}, by Avg PnL%)

{chr(10).join(line(r) for r in bottom) or '_none_'}

## Paths

- `drive/paul_experiments/{stamp}/symbol_summary.html`
- `drive/paul_experiments/{stamp}/symbol_summary.csv`
- `drive/paul_experiments/{stamp}/compare.html`
"""
    path.write_text(text, encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            out = {}
            for k in fieldnames:
                v = r.get(k, "")
                if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                    out[k] = "" if math.isnan(v) else ("inf" if v > 0 else "-inf")
                else:
                    out[k] = v
            w.writerow(out)


def write_trades_csv(path: Path, trades: list[dict[str, Any]]) -> None:
    if not trades:
        path.write_text("", encoding="utf-8")
        return
    keys: list[str] = []
    seen: set[str] = set()
    for t in trades:
        for k in t:
            if k not in seen:
                seen.add(k)
                keys.append(k)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for t in trades:
            w.writerow(t)


def maybe_rescan(stamp: str) -> Optional[Path]:
    """Rebuild control via open15 tool into a temp stamp, return trades.csv path."""
    tmp = f"{stamp}_rescan_ctrl"
    cmd = [
        sys.executable,
        str(ROOT / "tools" / "scalp_open15_reversal_ab.py"),
        "--all",
        "--sides",
        "both",
        "--stamp",
        tmp,
    ]
    print("Rescanning control:", " ".join(cmd), flush=True)
    rc = subprocess.call(cmd, cwd=str(ROOT))
    if rc != 0:
        print(f"Rescan failed rc={rc}", file=sys.stderr)
        return None
    p = DRIVE / "paul_experiments" / tmp / "trades.csv"
    return p if p.is_file() else None


def main() -> int:
    ap = argparse.ArgumentParser(description="Scalp symbol summary + shorts-only AB")
    ap.add_argument("--stamp", default=DEFAULT_STAMP)
    ap.add_argument(
        "--control-csv",
        default="",
        help=f"Control trades CSV (default: drive/{CONTROL_TRADES_REL})",
    )
    ap.add_argument("--min-n", type=int, default=MIN_N_RANK, help="Min N for top/bottom rank")
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--rescan", action="store_true", help="Rebuild control via --sides both scan")
    args = ap.parse_args()

    stamp = args.stamp
    out_dir = DRIVE / "paul_experiments" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.rescan:
        rescanned = maybe_rescan(stamp)
        if rescanned is None:
            return 2
        control_path = rescanned
        book_note = (
            f"Rescanned control LOD/HOD ±0.1% via scalp_open15_reversal_ab.py --all --sides both "
            f"→ {rescanned.relative_to(ROOT).as_posix()}"
        )
    else:
        control_path = (
            Path(args.control_csv)
            if args.control_csv.strip()
            else ROOT / "drive" / CONTROL_TRADES_REL
        )
        book_note = (
            f"Stamped control book `{CONTROL_SOURCE_STAMP}/trades_control.csv` "
            f"(stop_arm=control_lod_hod_0p1, time_stop=11:30, long+short)"
        )

    if not control_path.is_file():
        print(f"Missing control CSV: {control_path}", file=sys.stderr)
        return 2

    trades = load_control_trades(control_path)
    if not trades:
        print("Empty control trades", file=sys.stderr)
        return 2

    shorts = [t for t in trades if str(t.get("side") or "") == "short"]
    longs = [t for t in trades if str(t.get("side") or "") == "long"]

    ctrl_m = ab.metrics_from_trades(trades, include_slices=True)
    short_m = ab.metrics_from_trades(shorts, include_slices=True)
    long_m = ab.metrics_from_trades(longs, include_slices=False)
    verdict = pick_shorts_verdict(ctrl_m, short_m)

    sessions = sorted({str(t.get("session") or "")[:10] for t in trades if t.get("session")})
    cov = (
        f"Session span {sessions[0]} → {sessions[-1]} ({len(sessions)} distinct sessions); "
        f"{len({t.get('symbol') for t in trades})} symbols with ≥1 trade; "
        f"Yahoo 1m short retention — full-sample only."
        if sessions
        else "No session dates on trades."
    )

    sym_rows = per_symbol_rows(trades, min_n_rank=args.min_n)
    eligible = [r for r in sym_rows if r.get("rank_eligible")]
    top = eligible[: args.top_k]
    bottom = list(reversed(eligible[-args.top_k :])) if eligible else []

    # Artifacts
    write_trades_csv(out_dir / "trades_control.csv", trades)
    write_trades_csv(out_dir / "trades_shorts_only.csv", shorts)

    sym_fields = [
        "symbol",
        "N",
        "Win%",
        "Avg_PnL_%",
        "Sum_PnL_$",
        "Profit_Factor",
        "n_long",
        "n_short",
        "session_min",
        "session_max",
        "label",
        "rank_eligible",
    ]
    write_csv(out_dir / "symbol_summary.csv", sym_rows, sym_fields)

    ab_rows = []
    for arm, m, v in (
        ("A_control_long_short", ctrl_m, "control"),
        ("B_shorts_only", short_m, verdict),
        ("descriptive_longs_only", long_m, "descriptive"),
    ):
        ab_rows.append(
            {
                "arm": arm,
                "N": m.get("N"),
                "Wins": m.get("Wins"),
                "Losses": m.get("Losses"),
                "Win%": m.get("Win%"),
                "Avg_PnL_%": m.get("Avg_PnL_%"),
                "AVG_PNL_PCT_WO_MAX": m.get("AVG_PNL_PCT_WO_MAX"),
                "Profit_Factor": m.get("Profit_Factor"),
                "Total_PnL_$": m.get("Total_PnL_$"),
                "Sheet_PnL_$": m.get("Sheet_PnL_$"),
                "Expectancy_%": m.get("Expectancy_%"),
                "Max_DD_%": m.get("Max_DD_%"),
                "Ann_ROR_%": m.get("Ann_ROR_%"),
                "verdict": v,
            }
        )
    write_csv(
        out_dir / "metrics_ab.csv",
        ab_rows,
        [
            "arm",
            "N",
            "Wins",
            "Losses",
            "Win%",
            "Avg_PnL_%",
            "AVG_PNL_PCT_WO_MAX",
            "Profit_Factor",
            "Total_PnL_$",
            "Sheet_PnL_$",
            "Expectancy_%",
            "Max_DD_%",
            "Ann_ROR_%",
            "verdict",
        ],
    )

    write_symbol_summary_html(
        out_dir / "symbol_summary.html",
        stamp=stamp,
        book_note=book_note,
        cov=cov,
        rows=sym_rows,
        min_n=args.min_n,
        top=top,
        bottom=bottom,
        ctrl_m=ctrl_m,
    )
    write_compare_html(
        out_dir / "compare.html",
        stamp=stamp,
        book_note=book_note,
        cov=cov,
        ctrl_m=ctrl_m,
        short_m=short_m,
        long_m=long_m,
        verdict=verdict,
    )
    write_baseline(
        out_dir / "BASELINE.md",
        stamp=stamp,
        book_note=book_note,
        cov=cov,
        ctrl_m=ctrl_m,
        short_m=short_m,
        verdict=verdict,
        min_n=args.min_n,
    )
    write_summary_md(
        out_dir / "SUMMARY.md",
        stamp=stamp,
        book_note=book_note,
        cov=cov,
        ctrl_m=ctrl_m,
        short_m=short_m,
        long_m=long_m,
        verdict=verdict,
        top=top,
        bottom=bottom,
        min_n=args.min_n,
    )

    print(f"OUT={out_dir}", flush=True)
    print(
        f"CTRL N={ctrl_m['N']} WR%={ab._fmt_num(ctrl_m['Win%'])} "
        f"Avg={ab._fmt_num(ctrl_m['Avg_PnL_%'], 4)} PF={ab._fmt_num(ctrl_m['Profit_Factor'])}",
        flush=True,
    )
    print(
        f"SHORT N={short_m['N']} WR%={ab._fmt_num(short_m['Win%'])} "
        f"Avg={ab._fmt_num(short_m['Avg_PnL_%'], 4)} PF={ab._fmt_num(short_m['Profit_Factor'])}",
        flush=True,
    )
    print(f"Verdict: {verdict}", flush=True)
    print("TOP:", ", ".join(f"{r['symbol']}(N={r['N']})" for r in top[:10]), flush=True)
    print("BOT:", ", ".join(f"{r['symbol']}(N={r['N']})" for r in bottom[:10]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
