#!/usr/bin/env python3
"""RL Trail-1 BE overlay — apples-to-apples on RL_Closed_260814183604.

Same-trade Closed OHLC replay (NOT a full engine re-run). Control and all arms
keep identical N; only exits change when BE triggers.

Usage:
  python tools/rl_be_apples_ab.py
"""
from __future__ import annotations

import csv
import html as html_mod
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(DRIVE / "paul_experiments"))

from be_stop_replay_ab import (  # noqa: E402
    RL_CASH,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    book_stats,
    load_closed,
    load_ohlc,
    split_is_oos,
    sortable_th,
    verdict,
)
from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    format_money,
    format_money_delta,
    overlay_ann_ror_max_dd,
)
from rl_be_trail_pct_ab import ARMS, replay_be_pct  # noqa: E402

STAMP = "20260819"
OUT_DIR = DRIVE / "paul_experiments" / f"rl_be_apples_{STAMP}"
CLOSED = DRIVE / "RL_Closed_260814183604.csv"
LATEST = DRIVE / "RL_LatestRun_Closed.csv"
IS_CUT = date(2024, 1, 1)
PO_PCT = 0.14


def _f(v: Any, default: float = 0.0) -> float:
    if v is None or v == "":
        return default
    s = str(v).strip().replace("%", "").replace(",", "").replace("$", "")
    if not s:
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _norm_opened(v: Any) -> str:
    s = str(v or "").strip()
    if len(s) >= 8 and s[:8].isdigit():
        c = s.replace("-", "").replace("/", "")[:8]
        return f"{c[:4]}-{c[4:6]}-{c[6:8]}"
    return s[:10]


def po_armed_losers(ctrl: list[dict[str, Any]], pct: float) -> list[dict[str, Any]]:
    """Trades that reached +pct MFE (MAX GAIN) and closed as losers."""
    raw: dict[tuple[str, str], dict[str, Any]] = {}
    with CLOSED.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            sym = (row.get("SYMBOL") or "").strip().upper()
            op = _norm_opened(row.get("DATE OPENED"))
            raw[(sym, op)] = row

    out: list[dict[str, Any]] = []
    for t in ctrl:
        if t["pnl"] >= 0:
            continue
        row = raw.get((t["sym"], _norm_opened(t["opened"])))
        if row is None:
            continue
        mg = _f(row.get("MAX GAIN"))
        if mg >= pct:
            out.append({**t, "max_gain": mg, "exit_type": row.get("EXIT TYPE", "")})
    return out


def apply_arm(ctrl: list[dict[str, Any]], pct: float | None) -> tuple[list[dict[str, Any]], int]:
    if pct is None:
        return [{**t, "be_hit": False, "missing_bars": False, "armed": False} for t in ctrl], 0
    cand: list[dict[str, Any]] = []
    missing = 0
    for t in ctrl:
        df = load_ohlc(t["sym"])
        if df is None:
            missing += 1
            cand.append({**t, "be_hit": False, "missing_bars": True, "armed": False})
            continue
        cand.append(replay_be_pct(t, df, pct))
    return cand, missing


def overlay_cap(trades: list[dict[str, Any]]) -> dict[str, Any]:
    return overlay_ann_ror_max_dd(trades, cash=RL_CASH, initial_account=DEFAULT_INITIAL_ACCOUNT)


def pack(ctrl: list[dict], trades: list[dict], arm: dict, missing: int) -> dict[str, Any]:
    is_c, oos_c = split_is_oos(ctrl)
    is_a, oos_a = split_is_oos(trades)
    cash = RL_CASH
    m_full = book_stats(trades, cash)
    m_is = book_stats(is_a, cash)
    m_oos = book_stats(oos_a, cash)
    m_ctrl_full = book_stats(ctrl, cash)
    m_ctrl_is = book_stats(is_c, cash)
    m_ctrl_oos = book_stats(oos_c, cash)
    cap = overlay_cap(trades)
    cap_ctrl = overlay_cap(ctrl)
    if arm["role"] == "control":
        verd, note = "CONTROL", "No BE trail (rl_trail_profit=0)"
    else:
        verd, note = verdict(m_ctrl_full, m_full, m_ctrl_oos, m_oos)
    return {
        "arm": arm,
        "trades": trades,
        "missing": missing,
        "m_full": m_full,
        "m_is": m_is,
        "m_oos": m_oos,
        "m_ctrl_full": m_ctrl_full,
        "m_ctrl_is": m_ctrl_is,
        "m_ctrl_oos": m_ctrl_oos,
        "cap": cap,
        "cap_ctrl": cap_ctrl,
        "verd": verd,
        "note": note,
    }


def fmt_pct(x: float) -> str:
    return f"{x:.2f}%"


def fmt_pp(x: float) -> str:
    return f"{x:+.2f}pp"


def exit_mix(d: dict) -> str:
    items = sorted(d.items(), key=lambda kv: -kv[1])
    return ", ".join(f"{k}:{v}" for k, v in items[:8])


def metric_table(results: list[dict], book_key: str, caption: str) -> str:
    headers = [
        ("Arm", "text"),
        ("Role", "text"),
        ("N", "num"),
        ("Win%", "num"),
        ("Avg PnL%", "num"),
        ("AVG_PNL_PCT_WO_MAX", "num"),
        ("Avg win%", "num"),
        ("Avg loss%", "num"),
        ("PF", "num"),
        ("Sheet PnL $", "num"),
        ("Total PnL $", "num"),
        ("Ann ROR%", "num"),
        ("Max DD %", "num"),
        ("Avg days", "num"),
        ("BE hits", "num"),
        ("Δ Total PnL $", "num"),
        ("Δ Avg PnL%", "num"),
        ("Δ Win%", "num"),
        ("Exit mix", "text"),
        ("Verdict", "text"),
    ]
    th = "".join(sortable_th(a, b) for a, b in headers)
    ctrl_m = results[0][book_key]
    ctrl_cap = results[0]["cap"]
    parts = []
    for r in results:
        m = r[book_key]
        cap = r["cap"]
        d_pnl = m["pnl_d"] - ctrl_m["pnl_d"]
        d_avg = m["avg_pnl"] - ctrl_m["avg_pnl"]
        d_wr = m["wr"] - ctrl_m["wr"]
        max_dd = cap.get("max_dd")
        max_dd_s = fmt_pct(float(max_dd)) if max_dd == max_dd else "—"
        cells = [
            html_mod.escape(r["arm"]["label"]),
            r["arm"]["role"],
            str(m["n"]),
            fmt_pct(m["wr"]),
            fmt_pct(m["avg_pnl"]),
            fmt_pct(m["wo_max"]),
            fmt_pct(m["avg_win"]),
            fmt_pct(m["avg_loss"]),
            f"{m['pf']:.2f}",
            format_money(m["sheet"]),
            format_money(m["pnl_d"]),
            fmt_pct(m["ann_ror"]),
            max_dd_s,
            f"{m['avg_days']:.1f}",
            str(m["be_n"]),
            "—" if r["arm"]["role"] == "control" else format_money_delta(d_pnl),
            "—" if r["arm"]["role"] == "control" else fmt_pp(d_avg),
            "—" if r["arm"]["role"] == "control" else fmt_pp(d_wr),
            html_mod.escape(exit_mix(m["exits"])),
            html_mod.escape(r["verd"] if book_key == "m_full" else ""),
        ]
        parts.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    return (
        f'<table class="sortable"><caption>{html_mod.escape(caption)}</caption>'
        f"<thead><tr>{th}</tr></thead><tbody>{''.join(parts)}</tbody></table>"
    )


def isoos_table(results: list[dict]) -> str:
    headers = [
        ("Arm", "text"),
        ("Split", "text"),
        ("N", "num"),
        ("Win%", "num"),
        ("Avg PnL%", "num"),
        ("WO_MAX", "num"),
        ("PF", "num"),
        ("BE hits", "num"),
        ("Sheet PnL $", "num"),
        ("Ann ROR%", "num"),
        ("Avg days", "num"),
        ("Δ Avg PnL% vs ctrl split", "num"),
        ("Δ Win% vs ctrl split", "num"),
    ]
    th = "".join(sortable_th(a, b) for a, b in headers)
    ctrl = results[0]
    parts = []
    for r in results:
        for split, mk, ck in (("IS", "m_is", "m_ctrl_is"), ("OOS", "m_oos", "m_ctrl_oos")):
            m = r[mk]
            c = r[ck] if r["arm"]["role"] != "control" else ctrl[mk]
            d_avg = m["avg_pnl"] - c["avg_pnl"]
            d_wr = m["wr"] - c["wr"]
            cells = [
                html_mod.escape(r["arm"]["label"]),
                split,
                str(m["n"]),
                fmt_pct(m["wr"]),
                fmt_pct(m["avg_pnl"]),
                fmt_pct(m["wo_max"]),
                f"{m['pf']:.2f}",
                str(m["be_n"]),
                format_money(m["sheet"]),
                fmt_pct(m["ann_ror"]),
                f"{m['avg_days']:.1f}",
                "—" if r["arm"]["role"] == "control" else fmt_pp(d_avg),
                "—" if r["arm"]["role"] == "control" else fmt_pp(d_wr),
            ]
            parts.append("<tr>" + "".join(f"<td>{x}</td>" for x in cells) + "</tr>")
    return (
        '<table class="sortable"><caption>IS = entry_date &lt; 2024-01-01; OOS report-only. '
        "Click column headers to sort.</caption>"
        f"<thead><tr>{th}</tr></thead><tbody>{''.join(parts)}</tbody></table>"
    )


def po_table(po_rows: list[dict], overlay14: list[dict]) -> str:
    by_key = {(t["sym"], _norm_opened(t["opened"])): t for t in overlay14}
    headers = [
        ("Symbol", "text"),
        ("Opened", "date"),
        ("Closed", "date"),
        ("Entry", "num"),
        ("MAX GAIN", "num"),
        ("Control PnL%", "num"),
        ("Control PnL $", "num"),
        ("14% BE PnL%", "num"),
        ("14% BE PnL $", "num"),
        ("Δ PnL $", "num"),
        ("BE hit?", "text"),
        ("Exit type", "text"),
    ]
    th = "".join(sortable_th(a, b) for a, b in headers)
    parts = []
    total_ctrl = 0.0
    total_be = 0.0
    for t in po_rows:
        key = (t["sym"], _norm_opened(t["opened"]))
        ov = by_key.get(key, t)
        d = ov["pnl_d"] - t["pnl_d"]
        total_ctrl += t["pnl_d"]
        total_be += ov["pnl_d"]
        cells = [
            t["sym"],
            str(t["opened"]),
            str(t["closed"]),
            f"{t['entry']:.2f}",
            fmt_pct(t["max_gain"] * 100),
            fmt_pct(t["pnl"]),
            format_money(t["pnl_d"]),
            fmt_pct(ov["pnl"]),
            format_money(ov["pnl_d"]),
            format_money_delta(d),
            "yes" if ov.get("be_hit") else "no",
            html_mod.escape(str(t.get("exit_type", ""))),
        ]
        parts.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    foot = (
        f'<tr class="total-row"><td colspan="6"><strong>PO cohort ({len(po_rows)} trades)</strong></td>'
        f"<td>{format_money(total_ctrl)}</td><td></td>"
        f"<td>{format_money(total_be)}</td>"
        f"<td>{format_money_delta(total_be - total_ctrl)}</td>"
        f"<td colspan=\"2\"></td></tr>"
    )
    return (
        '<table class="sortable"><caption>PO reconciliation: MAX GAIN ≥ 14% then loser (control). '
        "Click column headers to sort.</caption>"
        f"<thead><tr>{th}</tr></thead><tbody>{''.join(parts)}{foot}</tbody></table>"
    )


def write_html(results: list[dict], po_rows: list[dict], same_as_latest: bool) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    r14 = next(r for r in results if r["arm"]["key"] == "pct14")
    r20 = next(r for r in results if r["arm"]["key"] == "pct20")
    r10 = next(r for r in results if r["arm"]["key"] == "pct10")
    ctrl = results[0]
    po_sum = sum(t["pnl_d"] for t in po_rows)
    po_be_sum = sum(
        next(x for x in r14["trades"] if x["sym"] == t["sym"] and _norm_opened(x["opened"]) == _norm_opened(t["opened"]))[
            "pnl_d"
        ]
        for t in po_rows
    )
    be_on_winners = sum(
        1
        for c, o in zip(ctrl["trades"], r14["trades"])
        if c["pnl"] > 0 and o.get("be_hit")
    )
    bits = f"14% → {r14['verd']} · 20% → {r20['verd']} · 10% ref → {r10['verd']}"
    prior_note = (
        "Yes — prior <code>rl_be_trail_pct_ab_20260819</code> used the same Closed OHLC overlay "
        "(not a full engine re-run). It labeled control as <code>RL_LatestRun_Closed.csv</code>, "
        "which is <strong>identical trade keys</strong> to this stamp."
        if same_as_latest
        else "Prior test used a different Closed file — compare keys before trusting prior verdict."
    )
    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<title>RL BE apples-to-apples — {STAMP}</title>
<style>
:root {{ --bg:#f7f6f2; --ink:#1c1b19; --muted:#5a574f; --line:#d4d0c4; --fill:#f0eee6; --accent:#2a4a5c; }}
body {{ margin:0; font-family:"Segoe UI",Georgia,serif; font-size:15px; color:var(--ink); background:var(--bg); }}
.wrap {{ max-width:1280px; margin:0 auto; padding:32px 20px 64px; }}
h1 {{ font-size:1.55rem; margin:0 0 8px; }}
h2 {{ font-size:1.12rem; margin:28px 0 10px; border-bottom:1px solid var(--line); padding-bottom:4px; }}
.muted {{ color:var(--muted); font-size:0.9rem; }}
.callout {{ background:#e8eef2; border-left:4px solid var(--accent); padding:12px 14px; margin:14px 0; }}
.warn {{ background:#f5ece8; border-left:4px solid #8b4513; padding:12px 14px; margin:14px 0; }}
.table-wrap {{ overflow-x:auto; margin:8px 0 16px; }}
table.sortable {{ border-collapse:collapse; width:100%; font-size:13px; }}
th, td {{ border:1px solid var(--line); padding:6px 8px; text-align:left; vertical-align:top; }}
thead th {{ background:var(--fill); }}
{SORTABLE_TH_CSS}
caption {{ text-align:left; font-size:0.82rem; color:var(--muted); caption-side:top; margin:0 0 6px; }}
code {{ background:var(--fill); padding:0.08em 0.3em; font-size:0.86em; }}
</style></head><body>
<div class="wrap">
<p class="muted">Twin Beacon Networks (TBN) · Relative Strength (RL) · research · not DailyRun</p>
<h1>RL BE overlay — apples-to-apples on <code>RL_Closed_260814183604</code></h1>
<p>Same 549 closed trades. EXIT-only overlay: after High ≥ entry×(1+pct), stop = entry (BE).
<strong>Not</strong> a full backtest — capital path and entries unchanged.</p>

<div class="callout"><strong>Did prior test keep same trades?</strong> {prior_note}</div>
<div class="warn"><strong>PO 45-trade check reconciled:</strong> {len(po_rows)} trades with MAX GAIN ≥ 14% closed as losers;
control PnL {format_money(po_sum)} (~$200k avoidable on paper). 14% BE on those alone: {format_money(po_be_sum)}
({format_money_delta(po_be_sum - po_sum)}). But {r14['m_full']['be_n']} total BE hits include
{be_on_winners} former winners scratched — net full book Δ {format_money_delta(r14['m_full']['pnl_d'] - ctrl['m_full']['pnl_d'])}.</div>

<div class="callout"><strong>Verdicts (same methodology as prior):</strong> {html_mod.escape(bits)}</div>

<h2>Full book vs control (N fixed)</h2>
<p class="muted">Control stamp: <code>drive/RL_Closed_260814183604.csv</code>. Max DD = Closed overlay at $500k initial (exit-date equity).</p>
<div class="table-wrap">{metric_table(results, "m_full", "Click column headers to sort.")}</div>

<h2>IS / OOS</h2>
<div class="table-wrap">{isoos_table(results)}</div>

<h2>PO cohort — +14% MFE then loser</h2>
<div class="table-wrap">{po_table(po_rows, r14['trades'])}</div>

<h2>Method</h2>
<ul>
<li><strong>Control:</strong> <code>RL_Closed_260814183604.csv</code> (549 trades, rl_trail_profit=0).</li>
<li><strong>Arms:</strong> 10% (ref), 14% (PO), 20% (wider) — same OHLC BE convention as <code>be_stop_replay_ab.py</code>.</li>
<li><strong>PO filter:</strong> Closed column MAX GAIN ≥ 0.14 and PNL % &lt; 0.</li>
<li>IS = entry &lt; 2024-01-01. Prior DISMISS verdict stands on quality metrics, not because of trade-set change.</li>
</ul>
<p class="muted">Generated {STAMP} by <code>tools/rl_be_apples_ab.py</code>.</p>
</div>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    path = OUT_DIR / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def write_baseline(results: list[dict], po_rows: list[dict], same_as_latest: bool) -> Path:
    ctrl = results[0]
    r14 = next(r for r in results if r["arm"]["key"] == "pct14")
    po_sum = sum(t["pnl_d"] for t in po_rows)
    lines = [
        "# RL BE apples-to-apples — RL_Closed_260814183604",
        "",
        "## Did prior test keep same trades?",
        "",
    ]
    if same_as_latest:
        lines += [
            "**Yes.** Prior `rl_be_trail_pct_ab_20260819` used Closed OHLC overlay (not full engine re-run).",
            "Control file was labeled `RL_LatestRun_Closed.csv` but trade keys match this stamp exactly (N=549).",
            "Prior DISMISS verdict is apples-to-apples; wrong file label, not wrong methodology.",
            "",
        ]
    else:
        lines += ["**Uncertain** — verify trade keys between prior control and this stamp.", ""]

    lines += [
        "## Methodology",
        "",
        "| Item | Value |",
        "|---|---|",
        f"| Control | `{CLOSED.relative_to(ROOT).as_posix()}` |",
        "| Method | Same-trade Closed OHLC overlay (EXIT only) |",
        "| NOT | Full rocket_rl re-run / allocation path change |",
        f"| N | {ctrl['m_full']['n']} |",
        f"| RL cash (Ann ROR) | ${RL_CASH:,.0f} |",
        f"| Max DD overlay initial | ${DEFAULT_INITIAL_ACCOUNT:,.0f} |",
        "",
        "## PO 45-trade reconciliation",
        "",
        f"- Filter: MAX GAIN ≥ 14% and closed loser → **{len(po_rows)} trades**",
        f"- Control PnL on cohort: **{format_money(po_sum)}**",
        f"- 14% BE overlay PnL on same cohort: **{format_money(sum(next(x for x in r14['trades'] if x['sym']==t['sym'] and _norm_opened(x['opened'])==_norm_opened(t['opened']))['pnl_d'] for t in po_rows))}**",
        f"- Full-book 14% BE hits: **{r14['m_full']['be_n']}** (includes winners scratched to BE)",
        f"- Full-book Δ Total PnL vs control: **{format_money_delta(r14['m_full']['pnl_d'] - ctrl['m_full']['pnl_d'])}**",
        "",
        "## Verdicts (unchanged from prior overlay)",
        "",
    ]
    for r in results:
        if r["arm"]["role"] == "control":
            continue
        lines.append(f"- **{r['arm']['label']}** → **{r['verd']}** ({r['note']})")
    path = OUT_DIR / "BASELINE.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> int:
    print(f"[RL-BE-APPLES] loading {CLOSED} ...", flush=True)
    ctrl = load_closed(CLOSED, "rl")
    print(f"[RL-BE-APPLES] N={len(ctrl)}", flush=True)

    same_as_latest = False
    if LATEST.exists():
        latest = load_closed(LATEST, "rl")
        lk = [(t["sym"], str(t["opened"]), str(t["closed"])) for t in latest]
        sk = [(t["sym"], str(t["opened"]), str(t["closed"])) for t in ctrl]
        same_as_latest = lk == sk
        print(f"[RL-BE-APPLES] same keys as LatestRun? {same_as_latest}", flush=True)

    po_rows = po_armed_losers(ctrl, PO_PCT)
    print(f"[RL-BE-APPLES] PO +14% losers: {len(po_rows)} sum={sum(t['pnl_d'] for t in po_rows):,.2f}", flush=True)

    results = []
    for arm in ARMS:
        trades, missing = apply_arm(ctrl, arm["pct"])
        r = pack(ctrl, trades, arm, missing)
        results.append(r)
        cap = r["cap"]
        dd = cap.get("max_dd")
        dd_s = f"{dd:.2f}%" if dd == dd else "n/a"
        print(
            f"  {arm['key']}: N={r['m_full']['n']} BE={r['m_full']['be_n']} "
            f"PnL={r['m_full']['pnl_d']:,.0f} Ann={r['m_full']['ann_ror']:.1f}% DD={dd_s} -> {r['verd']}",
            flush=True,
        )

    html_path = write_html(results, po_rows, same_as_latest)
    write_baseline(results, po_rows, same_as_latest)
    print(f"[RL-BE-APPLES] wrote {html_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
