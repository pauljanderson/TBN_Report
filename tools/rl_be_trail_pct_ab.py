#!/usr/bin/env python3
"""RL Trail-1 BE overlay: one knob `rl_trail_profit` (stop=0).

Control = DailyRun off (no BE) on RL_Closed_260814183604 (LatestRun fallback).
Candidates replay the same Closed book + local OHLC:
  after first High >= entry * (1 + pct), subsequent Low <= entry → BE at entry
  (gap through BE → next/open fill — same convention as tools/be_stop_replay_ab.py).

Pre-agreed arms (not a grid): 14% (user historical), 20% (wider).
10% is a cheap reference row only (already DISMISS 20260819).

Research-only. Not DailyRun.

Usage:
  python tools/rl_be_trail_pct_ab.py
"""
from __future__ import annotations

import html as html_mod
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

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
from compare_format import format_money  # noqa: E402

STAMP = "20260819"
OUT_DIR = DRIVE / "paul_experiments" / f"rl_be_trail_pct_ab_{STAMP}"
# Prefer the PO stamp; LatestRun is only a fallback (DailyRun copy).
CLOSED = next(
    (
        p
        for p in (
            DRIVE / "RL_Closed_260814183604.csv",
            DRIVE / "RL_LatestRun_Closed.csv",
        )
        if p.is_file()
    ),
    DRIVE / "RL_Closed_260814183604.csv",
)
IS_CUT = date(2024, 1, 1)

# Control + pre-agreed candidates + cheap 10% reference (not a search grid).
ARMS: list[dict[str, Any]] = [
    {"pct": None, "key": "control", "label": "control (DailyRun off)", "role": "control"},
    {"pct": 0.10, "key": "pct10", "label": "rl_trail_profit=0.10 (ref, prior DISMISS)", "role": "reference"},
    {"pct": 0.14, "key": "pct14", "label": "rl_trail_profit=0.14 (user)", "role": "candidate"},
    {"pct": 0.20, "key": "pct20", "label": "rl_trail_profit=0.20 (wider)", "role": "candidate"},
]


def replay_be_pct(trade: dict[str, Any], ohlc: pd.DataFrame, pct: float) -> dict[str, Any]:
    """Same BE overlay as be_stop_replay_ab.replay_be, parameterized arm %.

    Fill bar: arm on High only; do not BE-stop the fill bar.
    After armed: Open <= entry → exit at Open (gap); Low <= entry → exit at entry.
    Never extends past original close.
    """
    entry = float(trade["entry"])
    arm_px = entry * (1.0 + float(pct))
    be = entry
    opened = trade["opened"]
    closed = trade["closed"]
    try:
        window = ohlc.loc[opened:closed]
    except Exception:
        return {**trade, "be_hit": False, "missing_bars": True, "armed": False}
    if window.empty:
        return {**trade, "be_hit": False, "missing_bars": True, "armed": False}
    dates = list(window.index)
    armed = False
    for i, d in enumerate(dates):
        o = float(window.loc[d, "Open"])
        h = float(window.loc[d, "High"])
        lo = float(window.loc[d, "Low"])
        if i == 0:
            if h >= arm_px:
                armed = True
            continue
        if (not armed) and h >= arm_px:
            armed = True
        if not armed:
            continue
        if o <= be:
            pnl = (o - entry) / entry * 100.0
            days = max((d - opened).days, 1)
            if abs(trade["pnl"]) > 1e-9:
                notional = trade["pnl_d"] / (trade["pnl"] / 100.0)
                pnl_d = notional * pnl / 100.0
            else:
                pnl_d = 0.0
            return {
                **trade,
                "pnl": pnl,
                "pnl_d": pnl_d,
                "days": float(days),
                "exit": "TRAIL_BE",
                "exit_px": o,
                "be_hit": True,
                "missing_bars": False,
                "armed": True,
            }
        if lo <= be:
            days = max((d - opened).days, 1)
            return {
                **trade,
                "pnl": 0.0,
                "pnl_d": 0.0,
                "days": float(days),
                "exit": "TRAIL_BE",
                "exit_px": be,
                "be_hit": True,
                "missing_bars": False,
                "armed": True,
            }
    return {**trade, "be_hit": False, "missing_bars": False, "armed": armed}


def apply_arm(ctrl: list[dict[str, Any]], pct: float | None) -> tuple[list[dict[str, Any]], int]:
    if pct is None:
        out = [{**t, "be_hit": False, "missing_bars": False, "armed": False} for t in ctrl]
        return out, 0
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
    if arm["role"] == "control":
        verd, note = "CONTROL", "DailyRun trail off (rl_trail_profit=0)"
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
        ("Avg days", "num"),
        ("BE hits", "num"),
        ("Δ Avg PnL%", "num"),
        ("Δ Win%", "num"),
        ("Δ PF", "num"),
        ("Exit mix", "text"),
        ("Verdict", "text"),
    ]
    th = "".join(sortable_th(a, b) for a, b in headers)
    ctrl_m = results[0][book_key]
    parts = []
    for r in results:
        m = r[book_key]
        d_avg = m["avg_pnl"] - ctrl_m["avg_pnl"]
        d_wr = m["wr"] - ctrl_m["wr"]
        d_pf = m["pf"] - ctrl_m["pf"]
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
            f"{m['avg_days']:.1f}",
            str(m["be_n"]),
            "—" if r["arm"]["role"] == "control" else fmt_pp(d_avg),
            "—" if r["arm"]["role"] == "control" else fmt_pp(d_wr),
            "—" if r["arm"]["role"] == "control" else f"{d_pf:+.2f}",
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


def write_html(results: list[dict]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    r14 = next(r for r in results if r["arm"]["key"] == "pct14")
    r20 = next(r for r in results if r["arm"]["key"] == "pct20")
    r10 = next(r for r in results if r["arm"]["key"] == "pct10")
    bits = (
        f"14% → {r14['verd']} · 20% → {r20['verd']} · 10% ref → {r10['verd']}"
    )
    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<title>RL BE trail pct A/B — {STAMP}</title>
<style>
:root {{ --bg:#f7f6f2; --ink:#1c1b19; --muted:#5a574f; --line:#d4d0c4; --fill:#f0eee6; --accent:#2a4a5c; }}
body {{ margin:0; font-family:"Segoe UI",Georgia,serif; font-size:15px; color:var(--ink); background:var(--bg); }}
.wrap {{ max-width:1280px; margin:0 auto; padding:32px 20px 64px; }}
h1 {{ font-size:1.55rem; margin:0 0 8px; }}
h2 {{ font-size:1.12rem; margin:28px 0 10px; border-bottom:1px solid var(--line); padding-bottom:4px; }}
.muted {{ color:var(--muted); font-size:0.9rem; }}
.callout {{ background:#e8eef2; border-left:4px solid var(--accent); padding:12px 14px; margin:14px 0; }}
.table-wrap {{ overflow-x:auto; margin:8px 0 16px; }}
table.sortable {{ border-collapse:collapse; width:100%; font-size:13px; }}
th, td {{ border:1px solid var(--line); padding:6px 8px; text-align:left; vertical-align:top; }}
thead th {{ background:var(--fill); }}
{SORTABLE_TH_CSS}
caption {{ text-align:left; font-size:0.82rem; color:var(--muted); caption-side:top; margin:0 0 6px; }}
code {{ background:var(--fill); padding:0.08em 0.3em; font-size:0.86em; }}
</style></head><body>
<div class="wrap">
<p class="muted">Twin Beacon Networks (TBN) · Relative Strength / RL · research candidate · not gold · not DailyRun</p>
<h1>RL Trail-1 breakeven — <code>rl_trail_profit</code> A/B</h1>
<p>One EXIT knob: gain that arms Trail-1 with <code>rl_trail_stop=0</code> (stop = entry).
Control = production off. Overlay on <code>RL_LatestRun_Closed.csv</code> + local OHLC.
Pre-agreed alternatives (not a grid): <strong>14%</strong> (user historical) and <strong>20%</strong> (wider, fewer BE hits).
10% is a reference row only (already DISMISS on 2026-08-19). Judge quality (WR, Avg PnL%, PF, WO_MAX), not N.
OOS soften → HOLD, do not retune.</p>
<div class="callout"><strong>Verdicts:</strong> {html_mod.escape(bits)}<br/>
<strong>14% specifically:</strong> {html_mod.escape(r14['verd'])} — {html_mod.escape(r14['note'])}</div>

<h2>Full book vs control</h2>
<p class="muted">Canonical compare set: N, Win%, Avg PnL%, AVG_PNL_PCT_WO_MAX, avg win/loss, PF, Sheet PnL, Total PnL, Ann ROR, days held, BE hits, exit mix. Dollar fields use $nnn,nnn.nn. Overlay keeps trade count fixed.</p>
<div class="table-wrap">{metric_table(results, "m_full", "Click column headers to sort. Overlay keeps N fixed.")}</div>

<h2>IS / OOS</h2>
<div class="table-wrap">{isoos_table(results)}</div>

<h2>Freeze / method</h2>
<ul>
<li><strong>System:</strong> RL (Rocket Launcher). Control stamp: <code>drive/RL_Closed_260814183604.csv</code> (fallback <code>RL_LatestRun_Closed.csv</code>).</li>
<li><strong>Knob:</strong> EXIT <code>rl_trail_profit</code> with <code>rl_trail_stop=0</code>. Frozen: entries, SMA target, stop_pct, no Trail-2.</li>
<li><strong>Convention:</strong> after first High ≥ entry×(1+pct), subsequent Low ≤ entry → BE at entry; Open gap through BE → exit at Open. Fill bar arms only; never extends past original close.</li>
<li>IS = entry_date &lt; 2024-01-01; OOS report-only. Missing local OHLC → control exit.</li>
<li>Ann ROR uses Closed PnL $ + RL cash $47,500 — not a full equity curve. Max DD / FIT not available on this overlay.</li>
<li>Not DailyRun. Selection: 14% and 20% pre-agreed; 10% not a new search.</li>
</ul>
<p class="muted">Generated {STAMP} by <code>tools/rl_be_trail_pct_ab.py</code>.</p>
</div>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    path = OUT_DIR / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def write_baseline(results: list[dict]) -> Path:
    lines = [
        "# RL Trail-1 BE pct A/B — freeze / hypothesis",
        "",
        "Research-only Closed OHLC overlay. Not DailyRun. One EXIT knob.",
        "",
        "| Field | Freeze |",
        "|---|---|",
        "| System | RL |",
        "| Control | `drive/RL_Closed_260814183604.csv` (fallback LatestRun; DailyRun `rl_trail_profit=0`) |",
        "| Knob | `rl_trail_profit` with `rl_trail_stop=0` (BE at entry) |",
        "| Frozen | entries, SMA target, stop_pct, no Trail-2 |",
        "| Arms | 14% (user), 20% (wider); 10% reference only |",
        "| Split | IS entry_date < 2024-01-01; OOS report-only |",
        "| Selection | pre-agreed, not a grid; do not retune on OOS |",
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
    print(f"[RL-BE] loading {CLOSED} ...", flush=True)
    ctrl = load_closed(CLOSED, "rl")
    print(f"[RL-BE] N={len(ctrl)}", flush=True)
    results = []
    for arm in ARMS:
        trades, missing = apply_arm(ctrl, arm["pct"])
        r = pack(ctrl, trades, arm, missing)
        results.append(r)
        print(
            f"  {arm['key']}: BE={r['m_full']['be_n']} WR={r['m_full']['wr']:.1f} "
            f"Avg={r['m_full']['avg_pnl']:.2f} PF={r['m_full']['pf']:.2f} -> {r['verd']}",
            flush=True,
        )
    html_path = write_html(results)
    write_baseline(results)
    print(f"[RL-BE] wrote {html_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
