#!/usr/bin/env python3
"""RL 764 one-timer frequency + lottery-symbol overlay ABs (research-only).

Overlay filter on Closed trades — no engine rerun, no dip/stop/target retune.
Membership freeze uses **IS trade counts / IS wo_max only**, then applied to
full / IS / OOS reporting.

Usage:
  python tools/rl_764_onetimer_lottery_ab.py
"""
from __future__ import annotations

import csv
import html as html_mod
import math
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

from be_stop_replay_ab import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    sortable_th,
)
from compare_format import (  # noqa: E402
    filter_html_compare_columns,
    format_money,
)
from rl_univ_compare_lists import (  # noqa: E402
    IS_CUT,
    RL_CASH,
    book_stats,
    load_trades,
    split_is_oos,
    verdict_vs_control,
)

STAMP = "rl_764_onetimer_lottery_ab_20260830"
OUT = ROOT / "drive" / "paul_experiments" / STAMP
SRC = ROOT / "drive" / "paul_experiments" / "rl_tradable_2010_adv2m_20260828"
CLOSED = SRC / "runs" / "tradable" / "RL_Closed_260828112205.csv"
UNIV = ROOT / "drive" / "universes" / "VZ_tradable_2010_adv2m_universe.csv"

# Optional dominance arm: max IS trade > this fraction of |sum IS pnl| among ge5
DOMINANCE_FRAC = 0.60


def esc(x: object) -> str:
    return html_mod.escape("" if x is None else str(x))


def fmt_n(v: float, d: int = 2) -> str:
    if v is None or not math.isfinite(v):
        return "—"
    return f"{v:.{d}f}"


def fmt_pct(v: float, d: int = 2) -> str:
    if v is None or not math.isfinite(v):
        return "—"
    return f"{v:.{d}f}"


def load_univ(path: Path) -> list[str]:
    out: list[str] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        s = line.strip().upper()
        if not s or s.startswith("#") or s == "SYMBOL":
            continue
        out.append(s.split(",")[0].strip().upper())
    return out


def is_avg_wo_max(pnls: list[float]) -> float:
    n = len(pnls)
    if n == 0:
        return float("nan")
    if n == 1:
        return pnls[0]
    return (sum(pnls) - max(pnls)) / (n - 1)


def is_avg_pnl(pnls: list[float]) -> float:
    return sum(pnls) / len(pnls) if pnls else float("nan")


def build_is_symbol_stats(is_trades: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by: dict[str, list[float]] = defaultdict(list)
    for t in is_trades:
        by[t["sym"]].append(float(t["pnl"]))
    out: dict[str, dict[str, Any]] = {}
    for sym, pnls in by.items():
        n = len(pnls)
        mx = max(pnls)
        total = sum(pnls)
        abs_total = abs(total) if total != 0 else 1e-12
        out[sym] = {
            "sym": sym,
            "n_is": n,
            "avg_pnl": is_avg_pnl(pnls),
            "avg_wo_max": is_avg_wo_max(pnls),
            "max_pnl": mx,
            "sum_pnl": total,
            "max_share_of_sum": (mx / abs_total) if n >= 2 else 1.0,
            "wins": sum(1 for p in pnls if p > 0),
            "losses": sum(1 for p in pnls if p < 0),
        }
    return out


def filter_trades(trades: list[dict[str, Any]], keep: set[str]) -> list[dict[str, Any]]:
    return [t for t in trades if t["sym"] in keep]


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def metric_row(arm_id: str, ab: str, split: str, m: dict[str, Any], drop_n: int, keep_n: int) -> dict[str, Any]:
    return {
        "ab": ab,
        "arm": arm_id,
        "split": split,
        "n_drop_symbols": drop_n,
        "n_keep_symbols_is": keep_n,
        "n": m["n"],
        "wins": m["wins"],
        "losses": m["losses"],
        "wr": m["wr"],
        "avg_pnl": m["avg_pnl"],
        "wo_max": m["wo_max"],
        "pf": m["pf"],
        "avg_win": m["avg_win"],
        "avg_loss": m["avg_loss"],
        "avg_days": m["avg_days"],
        "med_days": m["med_days"],
        "cap_days": m["cap_days"],
        "ppc": m["ppc"],
        "ann_ror": m["ann_ror"],
        "max_dd": m["max_dd"],
        "calmar": m["calmar"],
        "exp_d": m["exp_d"],
        "lose_streak": m["lose_streak"],
        "tpy": m["tpy"],
        "sheet": m["sheet"],
        "pnl_d": m["pnl_d"],
    }


def pack_arm(
    arm_id: str,
    label: str,
    ab: str,
    rule: str,
    all_trades: list[dict[str, Any]],
    keep: set[str],
    drop_rows: list[dict[str, Any]],
    is_traded: set[str],
) -> dict[str, Any]:
    trades = filter_trades(all_trades, keep) if arm_id != "control" else list(all_trades)
    # Control: keep everyone who traded; drop empty
    if arm_id == "control":
        trades = list(all_trades)
        keep = {t["sym"] for t in all_trades}
        drop_rows = []
    is_t, oos_t = split_is_oos(trades)
    m_full = book_stats(trades)
    m_is = book_stats(is_t)
    m_oos = book_stats(oos_t)
    keep_is = sorted(keep & is_traded) if arm_id != "control" else sorted(is_traded)
    return {
        "id": arm_id,
        "label": label,
        "ab": ab,
        "rule": rule,
        "keep": keep if arm_id != "control" else set(is_traded),
        "drop_rows": drop_rows,
        "n_drop": len(drop_rows),
        "n_keep_is": len(keep_is),
        "trades": trades,
        "m_full": m_full,
        "m_is": m_is,
        "m_oos": m_oos,
        "is_t": is_t,
        "oos_t": oos_t,
    }


def exit_mix_html(m: dict[str, Any]) -> str:
    ex = m.get("exits") or {}
    if not ex:
        return "—"
    n = m["n"] or 1
    parts = [f"{k}={v} ({100.0 * v / n:.1f}%)" for k, v in sorted(ex.items(), key=lambda x: -x[1])]
    return "; ".join(parts)


def build_compare_table(
    title: str,
    arms: list[dict[str, Any]],
    control: dict[str, Any],
    split_key: str,
) -> str:
    """Book metrics + deltas vs control. Omits Total/Sheet PnL $ per compare_format."""
    cols = [
        ("Arm", "text"),
        ("N drop sym", "num"),
        ("N", "num"),
        ("WR %", "num"),
        ("Avg PnL %", "num"),
        ("WO_MAX %", "num"),
        ("PF", "num"),
        ("Avg win %", "num"),
        ("Avg loss %", "num"),
        ("Ann ROR %", "num"),
        ("Max DD %", "num"),
        ("Calmar", "num"),
        ("Avg days", "num"),
        ("Med days", "num"),
        ("Cap days", "num"),
        ("Profit / cap day", "num"),
        ("Expectancy $", "num"),
        ("Lose streak", "num"),
        ("TPY", "num"),
        ("Δ Avg %", "num"),
        ("Δ WO_MAX", "num"),
        ("Δ PF", "num"),
        ("Δ WR", "num"),
        ("Δ Ann ROR", "num"),
        ("Δ Max DD", "num"),
        ("Δ Calmar", "num"),
        ("Verdict vs ctrl", "text"),
    ]
    cols = filter_html_compare_columns(cols)

    c = control[split_key]
    rows_html = []
    for arm in arms:
        m = arm[split_key]
        if arm["id"] == "control":
            verd, vnote = "CONTROL", "baseline 764 Closed overlay"
        else:
            # verdict_vs_control expects packed dict with split keys
            packed_cand = {"m_is": arm["m_is"], "m_oos": arm["m_oos"], "m_full": arm["m_full"]}
            packed_ctrl = {"m_is": control["m_is"], "m_oos": control["m_oos"], "m_full": control["m_full"]}
            verd, vnote = verdict_vs_control(packed_cand, packed_ctrl, split_key)

        def d(a: float, b: float) -> float:
            if not math.isfinite(a) or not math.isfinite(b):
                return float("nan")
            return a - b

        d_avg = d(m["avg_pnl"], c["avg_pnl"])
        d_wo = d(m["wo_max"], c["wo_max"])
        d_pf = d(m["pf"], c["pf"])
        d_wr = d(m["wr"], c["wr"])
        d_ann = d(m["ann_ror"], c["ann_ror"])
        d_dd = d(m["max_dd"], c["max_dd"])
        d_cal = d(m["calmar"], c["calmar"])

        cells = {
            "Arm": f'<td data-sort-value="{esc(arm["id"])}">{esc(arm["label"])}</td>',
            "N drop sym": f'<td data-sort-value="{arm["n_drop"]}">{arm["n_drop"]}</td>',
            "N": f'<td data-sort-value="{m["n"]}">{m["n"]}</td>',
            "WR %": f'<td data-sort-value="{m["wr"]}">{fmt_pct(m["wr"])}</td>',
            "Avg PnL %": f'<td data-sort-value="{m["avg_pnl"]}">{fmt_pct(m["avg_pnl"])}</td>',
            "WO_MAX %": f'<td data-sort-value="{m["wo_max"]}">{fmt_pct(m["wo_max"])}</td>',
            "PF": f'<td data-sort-value="{m["pf"]}">{fmt_n(m["pf"])}</td>',
            "Avg win %": f'<td data-sort-value="{m["avg_win"]}">{fmt_pct(m["avg_win"])}</td>',
            "Avg loss %": f'<td data-sort-value="{m["avg_loss"]}">{fmt_pct(m["avg_loss"])}</td>',
            "Ann ROR %": f'<td data-sort-value="{m["ann_ror"] if math.isfinite(m["ann_ror"]) else ""}">{fmt_pct(m["ann_ror"])}</td>',
            "Max DD %": f'<td data-sort-value="{m["max_dd"] if math.isfinite(m["max_dd"]) else ""}">{fmt_pct(m["max_dd"])}</td>',
            "Calmar": f'<td data-sort-value="{m["calmar"] if math.isfinite(m["calmar"]) else ""}">{fmt_n(m["calmar"])}</td>',
            "Avg days": f'<td data-sort-value="{m["avg_days"]}">{fmt_n(m["avg_days"], 1)}</td>',
            "Med days": f'<td data-sort-value="{m["med_days"]}">{fmt_n(m["med_days"], 1)}</td>',
            "Cap days": f'<td data-sort-value="{m["cap_days"]}">{fmt_n(m["cap_days"], 0)}</td>',
            "Profit / cap day": f'<td data-sort-value="{m["ppc"] if math.isfinite(m["ppc"]) else ""}">{format_money(m["ppc"]) if math.isfinite(m["ppc"]) else "—"}</td>',
            "Expectancy $": f'<td data-sort-value="{m["exp_d"]}">{format_money(m["exp_d"])}</td>',
            "Lose streak": f'<td data-sort-value="{m["lose_streak"]}">{m["lose_streak"]}</td>',
            "TPY": f'<td data-sort-value="{m["tpy"] if math.isfinite(m["tpy"]) else ""}">{fmt_n(m["tpy"])}</td>',
            "Δ Avg %": f'<td data-sort-value="{d_avg if math.isfinite(d_avg) else ""}">{fmt_n(d_avg) if math.isfinite(d_avg) else "—"}</td>',
            "Δ WO_MAX": f'<td data-sort-value="{d_wo if math.isfinite(d_wo) else ""}">{fmt_n(d_wo) if math.isfinite(d_wo) else "—"}</td>',
            "Δ PF": f'<td data-sort-value="{d_pf if math.isfinite(d_pf) else ""}">{fmt_n(d_pf) if math.isfinite(d_pf) else "—"}</td>',
            "Δ WR": f'<td data-sort-value="{d_wr if math.isfinite(d_wr) else ""}">{fmt_n(d_wr) if math.isfinite(d_wr) else "—"}</td>',
            "Δ Ann ROR": f'<td data-sort-value="{d_ann if math.isfinite(d_ann) else ""}">{fmt_n(d_ann) if math.isfinite(d_ann) else "—"}</td>',
            "Δ Max DD": f'<td data-sort-value="{d_dd if math.isfinite(d_dd) else ""}">{fmt_n(d_dd) if math.isfinite(d_dd) else "—"}</td>',
            "Δ Calmar": f'<td data-sort-value="{d_cal if math.isfinite(d_cal) else ""}">{fmt_n(d_cal) if math.isfinite(d_cal) else "—"}</td>',
            "Verdict vs ctrl": f'<td data-sort-value="{esc(verd)}" title="{esc(vnote)}">{esc(verd)}</td>',
        }
        row = "<tr>" + "".join(cells[a] for a, _ in cols) + "</tr>"
        rows_html.append(row)

    thead = "".join(sortable_th(a, b) for a, b in cols)
    return f"""
<h3>{esc(title)}</h3>
<p class="sub">Click column headers to sort. Control = full 764 Closed overlay. No Total/Sheet PnL $ in table.</p>
<table class="sortable">
<thead><tr>{thead}</tr></thead>
<tbody>
{"".join(rows_html)}
</tbody>
</table>
"""


def write_html(
    path: Path,
    ab1_arms: list[dict[str, Any]],
    ab2_arms: list[dict[str, Any]],
    control: dict[str, Any],
    is_stats: dict[str, dict[str, Any]],
    meta: dict[str, Any],
) -> None:
    ab1_is = build_compare_table("AB1 — Frequency gate — IS (entry &lt; 2024-01-01)", ab1_arms, control, "m_is")
    ab1_oos = build_compare_table("AB1 — Frequency gate — OOS (report-only)", ab1_arms, control, "m_oos")
    ab1_full = build_compare_table("AB1 — Frequency gate — FULL", ab1_arms, control, "m_full")
    ab2_is = build_compare_table("AB2 — Lottery screen — IS", ab2_arms, control, "m_is")
    ab2_oos = build_compare_table("AB2 — Lottery screen — OOS (report-only)", ab2_arms, control, "m_oos")
    ab2_full = build_compare_table("AB2 — Lottery screen — FULL", ab2_arms, control, "m_full")

    # Drop summary mini-tables
    def drop_table(arm: dict[str, Any]) -> str:
        rows = arm["drop_rows"][:80]
        if not rows:
            return f"<p><code>{esc(arm['id'])}</code>: no drops.</p>"
        cols = list(rows[0].keys())
        thead = "".join(sortable_th(c, "num" if c not in ("sym", "reason") else "text") for c in cols)
        body = []
        for r in rows:
            tds = []
            for c in cols:
                v = r[c]
                if isinstance(v, float):
                    tds.append(f'<td data-sort-value="{v}">{fmt_n(v)}</td>')
                else:
                    tds.append(f'<td data-sort-value="{esc(v)}">{esc(v)}</td>')
            body.append("<tr>" + "".join(tds) + "</tr>")
        more = "" if len(arm["drop_rows"]) <= 80 else f"<p>Showing 80 / {len(arm['drop_rows'])} — see CSV.</p>"
        return f"""
<h4>{esc(arm["label"])} — drop list ({arm["n_drop"]} symbols)</h4>
<p class="sub">{esc(arm["rule"])}</p>
{more}
<table class="sortable"><thead><tr>{thead}</tr></thead><tbody>{"".join(body)}</tbody></table>
"""

    drop_sections = "".join(
        drop_table(a) for a in ab1_arms + ab2_arms if a["id"] != "control" and a["drop_rows"]
    )

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>RL 764 one-timer / lottery AB — {STAMP}</title>
<style>
:root {{ --bg:#f7f5ef; --ink:#1c1b19; --muted:#6a655c; --line:#d9d3c5; --fill:#fffdf8; --accent:#2f5d50; }}
body {{ font-family: "Segoe UI", system-ui, sans-serif; background:var(--bg); color:var(--ink); margin:0; padding:24px; line-height:1.45; }}
h1 {{ font-size:1.45rem; margin:0 0 8px; }}
h2 {{ font-size:1.15rem; margin:28px 0 8px; border-bottom:1px solid var(--line); padding-bottom:4px; }}
h3 {{ font-size:1.02rem; margin:20px 0 6px; color:var(--accent); }}
h4 {{ font-size:0.95rem; margin:16px 0 4px; }}
.sub, .meta {{ color:var(--muted); font-size:0.88rem; }}
.box {{ background:var(--fill); border:1px solid var(--line); padding:12px 14px; margin:12px 0; }}
table.sortable {{ border-collapse:collapse; width:100%; font-size:0.82rem; background:var(--fill); margin:8px 0 18px; }}
table.sortable th, table.sortable td {{ border:1px solid var(--line); padding:5px 7px; text-align:left; }}
table.sortable th {{ background:#efeae0; }}
{SORTABLE_TH_CSS}
code {{ background:#efeae0; padding:0.08em 0.3em; font-size:0.86em; }}
ul {{ margin:6px 0 6px 1.2em; }}
</style></head><body>
<h1>RL 764 — one-timer frequency + lottery symbol ABs</h1>
<p class="meta"><strong>Research only.</strong> Not gold. Not DailyRun. Universe/screen overlay only — house RL knobs frozen
(<code>rl_dip_pct=1.055</code>, expansion 1.163, stop 0.934, target 1.20). Closed source:
<code>{esc(str(CLOSED.relative_to(ROOT)))}</code>. Cash model ${RL_CASH:,.0f} / overlay Ann ROR + Max DD.</p>

<div class="box">
<strong>Hypothesis (two one-knob ABs)</strong>
<ol>
<li><strong>AB1 Frequency:</strong> One-timers / thin IS history dilute the 764 book. Require ≥3 or ≥5 <em>IS</em> trades to keep a symbol.</li>
<li><strong>AB2 Lottery:</strong> Among symbols with ≥5 IS trades, drop if IS leave-max-out avg PnL% ≤ 0 (mostly losers + one huge win).</li>
</ol>
<p><strong>Critical freeze:</strong> Symbol keep/drop lists frozen from <code>entry_date &lt; 2024-01-01</code> only; same lists applied to OOS / FULL.
OOS is report-only — do not retune. Selecting these screens after seeing the 764 PO pack is <strong>in-sample selection bias</strong> for PO.</p>
<ul>
<li>Universe: {meta["univ_n"]} names (<code>VZ_tradable_2010_adv2m_universe.csv</code>)</li>
<li>Closed FULL N={meta["n_full"]}; IS N={meta["n_is"]}; OOS N={meta["n_oos"]}</li>
<li>IS symbols traded: {meta["n_is_sym"]}; IS one-timers: {meta["n_is_ones"]}; never-traded (full): {meta["n_never"]}</li>
<li>AB1 drops: min3={meta["drop_min3"]}, min5={meta["drop_min5"]}</li>
<li>AB2 drops: lottery_wo_max={meta["drop_lottery"]}, dominance optional={meta["drop_dom"]}</li>
</ul>
</div>

<h2>AB1 — One-timers / frequency gate</h2>
{ab1_is}
{ab1_oos}
{ab1_full}

<h2>AB2 — Lottery symbol screen</h2>
{ab2_is}
{ab2_oos}
{ab2_full}

<h2>Symbol drop lists (preview)</h2>
<p class="sub">Full CSVs in stamp folder. IS-only freeze.</p>
{drop_sections}

<h2>Exit mix (IS control)</h2>
<p>{esc(exit_mix_html(control["m_is"]))}</p>

<p class="meta">Generated {date.today().isoformat()}. Stamp <code>{STAMP}</code>. Overlay filter — not a re-run of the engine.</p>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    path.write_text(html, encoding="utf-8")


def write_baseline(
    path: Path,
    ab1_arms: list[dict[str, Any]],
    ab2_arms: list[dict[str, Any]],
    meta: dict[str, Any],
) -> None:
    lines = [
        f"# BASELINE — `{STAMP}`",
        "",
        "**Status:** RESEARCH only. **Not gold. Not DailyRun-wired.**",
        "",
        "## Hypothesis",
        "",
        "Two **universe/screen** one-knob ABs on the RL **764 tradable** Closed book.",
        "House RL knobs frozen (dip 1.055 / expansion 1.163 / stop 0.934 / target 1.20).",
        "**Do not** retune dip/stop/target. Overlay filter on existing Closed — no engine rerun.",
        "",
        "## Source",
        "",
        f"- Universe: `drive/universes/VZ_tradable_2010_adv2m_universe.csv` ({meta['univ_n']} names)",
        f"- Closed: `{CLOSED.relative_to(ROOT).as_posix()}` (stamp `260828112205`)",
        f"- Parent stamp: `rl_tradable_2010_adv2m_20260828`",
        f"- PO context: `rl_764_po_qa_20260830`",
        "",
        "## Engine freeze (identical all arms)",
        "",
        "| Knob | Value |",
        "|------|-------|",
        "| `rl_dip_pct` | **1.055** |",
        "| `rl_expansion` | **1.163** |",
        "| `rl_stop_pct` | **0.934** |",
        "| `rl_target_pct` | **1.20** |",
        "| cash (overlay) | **$47,500** |",
        "",
        "## IS / OOS",
        "",
        "- IS = `entry_date < 2024-01-01`; OOS = `entry_date >= 2024-01-01`",
        "- **Membership freeze uses IS only**, then applied to full/IS/OOS books",
        "- OOS is **report-only** — do not retune screens on OOS",
        "",
        "## AB1 — Frequency gate (one-timers)",
        "",
        "| Arm | Rule (IS freeze) |",
        "|-----|------------------|",
        "| `control` | All Closed trades on 764 book |",
        "| `min_is_trades_3` | Keep symbol iff **IS trade count ≥ 3** |",
        "| `min_is_trades_5` | Keep symbol iff **IS trade count ≥ 5** |",
        "",
        f"- IS symbols with count==1: **{meta['n_is_ones']}**",
        f"- Dropped by min3: **{meta['drop_min3']}**; by min5: **{meta['drop_min5']}**",
        "- Symbols with 0 IS trades but OOS-only history are **dropped** by min≥N (IS count 0)",
        "",
        "## AB2 — Lottery screen",
        "",
        "| Arm | Rule (IS freeze) |",
        "|-----|------------------|",
        "| `control` | Same 764 Closed book |",
        "| `lottery_wo_max` | Among symbols with **IS n ≥ 5**, **drop** if IS `avg_pnl_wo_max ≤ 0`; symbols with IS n &lt; 5 **kept** |",
        f"| `lottery_dominance` | Among IS n ≥ 5, drop if max IS trade &gt; {DOMINANCE_FRAC:.0%} of \\|sum IS pnl\\| (optional one-knob) |",
        "",
        f"- Lottery wo_max drops: **{meta['drop_lottery']}**",
        f"- Dominance drops: **{meta['drop_dom']}**",
        "",
        "## Selection bias (PO honesty)",
        "",
        "These screens were motivated by the PO Q&A pack (113 full-history one-timers, WO_MAX mild,",
        "lottery intuition). Choosing frequency / wo_max gates **after** inspecting that pack is",
        "**in-sample selection** even when OOS rows are printed. Treat KEEP as research candidate only.",
        "No gold / DailyRun claim from this stamp.",
        "",
        "## Artifacts",
        "",
        "- `compare.html` — sortable IS/OOS/FULL for both ABs",
        "- `metrics_all.csv`",
        "- Drop CSVs: `drop_min_is_trades_3.csv`, `drop_min_is_trades_5.csv`,",
        "  `drop_lottery_wo_max.csv`, `drop_lottery_dominance.csv`",
        "- Keep CSVs: `keep_*.csv`",
        "- `SUMMARY.md`",
        "",
    ]
    # Snapshot tables
    lines.append("## Snapshot — AB1 IS")
    lines.append("")
    lines.append("| Arm | N | WR | Avg% | WO_MAX | PF | AnnROR | MaxDD |")
    lines.append("|-----|---|----|------|--------|----|--------|-------|")
    for a in ab1_arms:
        m = a["m_is"]
        lines.append(
            f"| {a['id']} | {m['n']} | {m['wr']:.1f} | {m['avg_pnl']:.2f} | {m['wo_max']:.2f} | "
            f"{m['pf']:.2f} | {fmt_n(m['ann_ror'])} | {fmt_n(m['max_dd'])} |"
        )
    lines.append("")
    lines.append("## Snapshot — AB2 IS")
    lines.append("")
    lines.append("| Arm | N | WR | Avg% | WO_MAX | PF | AnnROR | MaxDD |")
    lines.append("|-----|---|----|------|--------|----|--------|-------|")
    for a in ab2_arms:
        m = a["m_is"]
        lines.append(
            f"| {a['id']} | {m['n']} | {m['wr']:.1f} | {m['avg_pnl']:.2f} | {m['wo_max']:.2f} | "
            f"{m['pf']:.2f} | {fmt_n(m['ann_ror'])} | {fmt_n(m['max_dd'])} |"
        )
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_summary(
    path: Path,
    ab1_arms: list[dict[str, Any]],
    ab2_arms: list[dict[str, Any]],
    control: dict[str, Any],
    meta: dict[str, Any],
) -> None:
    def line_arm(a: dict[str, Any], split: str) -> str:
        m = a[split]
        return (
            f"- **{a['id']}**: N={m['n']} WR={m['wr']:.1f}% Avg={m['avg_pnl']:.2f}% "
            f"WO_MAX={m['wo_max']:.2f}% PF={m['pf']:.2f} AnnROR={fmt_n(m['ann_ror'])} "
            f"MaxDD={fmt_n(m['max_dd'])}"
        )

    def verdicts(arms: list[dict[str, Any]]) -> list[str]:
        out = []
        packed_ctrl = {"m_is": control["m_is"], "m_oos": control["m_oos"], "m_full": control["m_full"]}
        for a in arms:
            if a["id"] == "control":
                continue
            packed = {"m_is": a["m_is"], "m_oos": a["m_oos"], "m_full": a["m_full"]}
            vis, nis = verdict_vs_control(packed, packed_ctrl, "m_is")
            voos, noos = verdict_vs_control(packed, packed_ctrl, "m_oos")
            # Adopt posture: quality on IS; OOS softens → HOLD
            if vis in ("LEAN KEEP", "KEEP") and voos == "DISMISS":
                adopt = "HOLD (IS lean / OOS softens — do not retune OOS)"
            elif vis == "DISMISS":
                adopt = "DISMISS"
            elif vis in ("LEAN KEEP", "KEEP") and voos in ("LEAN KEEP", "KEEP", "HOLD"):
                adopt = "LEAN KEEP research candidate (not gold)"
            else:
                adopt = "HOLD"
            out.append(
                f"- **{a['id']}**: IS `{vis}` ({nis}); OOS `{voos}` ({noos}) → **{adopt}**"
            )
        return out

    lines = [
        f"# SUMMARY — `{STAMP}`",
        "",
        "**Research only.** Overlay symbol screens on RL 764 Closed. Not gold / not DailyRun.",
        "House knobs frozen. Selection bias labeled (screens motivated by PO pack).",
        "",
        "## Freeze",
        "",
        "`rl_dip_pct=1.055`, expansion 1.163, stop 0.934, target 1.20. Cash $47.5k overlay.",
        f"Closed `{CLOSED.name}`. IS freeze only for membership.",
        "",
        f"Drop counts: min3={meta['drop_min3']}, min5={meta['drop_min5']}, "
        f"lottery_wo_max={meta['drop_lottery']}, dominance={meta['drop_dom']}.",
        "",
        "## AB1 Frequency — IS",
        "",
    ]
    lines.extend(line_arm(a, "m_is") for a in ab1_arms)
    lines += ["", "## AB1 Frequency — OOS (report-only)", ""]
    lines.extend(line_arm(a, "m_oos") for a in ab1_arms)
    lines += ["", "## AB1 verdicts vs control", ""]
    lines.extend(verdicts(ab1_arms))
    lines += ["", "## AB2 Lottery — IS", ""]
    lines.extend(line_arm(a, "m_is") for a in ab2_arms)
    lines += ["", "## AB2 Lottery — OOS (report-only)", ""]
    lines.extend(line_arm(a, "m_oos") for a in ab2_arms)
    lines += ["", "## AB2 verdicts vs control", ""]
    lines.extend(verdicts(ab2_arms))
    lines += [
        "",
        "## Bottom line",
        "",
        "Judge **quality over N**. OOS softens → HOLD, do not retune. "
        "Research candidate ≠ gold ≠ DailyRun. "
        "Screens chosen after PO one-timer / lottery discussion = selection bias for adoption claims.",
        "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if not CLOSED.is_file():
        print(f"Missing Closed: {CLOSED}", file=sys.stderr)
        return 1

    univ = load_univ(UNIV)
    trades = load_trades(CLOSED)
    is_t, oos_t = split_is_oos(trades)
    is_stats = build_is_symbol_stats(is_t)
    is_traded = set(is_stats.keys())
    full_traded = {t["sym"] for t in trades}
    never = sorted(set(univ) - full_traded)
    is_ones = sorted(s for s, st in is_stats.items() if st["n_is"] == 1)

    # --- AB1 keeps ---
    keep3 = {s for s, st in is_stats.items() if st["n_is"] >= 3}
    keep5 = {s for s, st in is_stats.items() if st["n_is"] >= 5}
    # OOS-only symbols (0 IS) are not in keep sets → dropped
    drop3_rows = []
    for s, st in sorted(is_stats.items()):
        if st["n_is"] < 3:
            drop3_rows.append({**st, "reason": f"IS n={st['n_is']} < 3"})
    # Also note OOS-only
    oos_only = sorted(full_traded - is_traded)
    for s in oos_only:
        drop3_rows.append(
            {
                "sym": s,
                "n_is": 0,
                "avg_pnl": float("nan"),
                "avg_wo_max": float("nan"),
                "max_pnl": float("nan"),
                "sum_pnl": float("nan"),
                "max_share_of_sum": float("nan"),
                "wins": 0,
                "losses": 0,
                "reason": "OOS-only (IS n=0) < 3",
            }
        )
    drop5_rows = []
    for s, st in sorted(is_stats.items()):
        if st["n_is"] < 5:
            drop5_rows.append({**st, "reason": f"IS n={st['n_is']} < 5"})
    for s in oos_only:
        drop5_rows.append(
            {
                "sym": s,
                "n_is": 0,
                "avg_pnl": float("nan"),
                "avg_wo_max": float("nan"),
                "max_pnl": float("nan"),
                "sum_pnl": float("nan"),
                "max_share_of_sum": float("nan"),
                "wins": 0,
                "losses": 0,
                "reason": "OOS-only (IS n=0) < 5",
            }
        )

    # --- AB2 lottery ---
    # Keep: all IS-traded with n<5, plus ge5 with wo_max > 0; also keep OOS-only (not lottery-screened)
    lottery_drop_rows = []
    keep_lottery = set(full_traded)  # start all traded, then remove lottery
    for s, st in sorted(is_stats.items()):
        if st["n_is"] >= 5 and st["avg_wo_max"] <= 0:
            lottery_drop_rows.append({**st, "reason": "IS n>=5 and avg_wo_max<=0"})
            keep_lottery.discard(s)

    dom_drop_rows = []
    keep_dom = set(full_traded)
    for s, st in sorted(is_stats.items()):
        if st["n_is"] >= 5 and st["max_share_of_sum"] > DOMINANCE_FRAC:
            dom_drop_rows.append(
                {**st, "reason": f"IS n>=5 and max_share>{DOMINANCE_FRAC:.0%} of |sum|"}
            )
            keep_dom.discard(s)

    control = pack_arm(
        "control",
        "Control (764 Closed)",
        "both",
        "All trades on 764 Closed book",
        trades,
        set(),
        [],
        is_traded,
    )

    ab1_arms = [
        control,
        pack_arm(
            "min_is_trades_3",
            "min_is_trades_3",
            "ab1",
            "Keep iff IS trade count ≥ 3 (freeze IS-only)",
            trades,
            keep3,
            drop3_rows,
            is_traded,
        ),
        pack_arm(
            "min_is_trades_5",
            "min_is_trades_5",
            "ab1",
            "Keep iff IS trade count ≥ 5 (freeze IS-only)",
            trades,
            keep5,
            drop5_rows,
            is_traded,
        ),
    ]

    ab2_arms = [
        control,
        pack_arm(
            "lottery_wo_max",
            "lottery_wo_max (primary)",
            "ab2",
            "Drop if IS n≥5 and IS avg_pnl_wo_max ≤ 0; keep thin (&lt;5) and OOS-only",
            trades,
            keep_lottery,
            lottery_drop_rows,
            is_traded,
        ),
        pack_arm(
            "lottery_dominance",
            f"lottery_dominance (max>{DOMINANCE_FRAC:.0%} |sum|)",
            "ab2",
            f"Drop if IS n≥5 and max IS trade > {DOMINANCE_FRAC:.0%} of |sum IS pnl|",
            trades,
            keep_dom,
            dom_drop_rows,
            is_traded,
        ),
    ]

    meta = {
        "univ_n": len(univ),
        "n_full": len(trades),
        "n_is": len(is_t),
        "n_oos": len(oos_t),
        "n_is_sym": len(is_traded),
        "n_is_ones": len(is_ones),
        "n_never": len(never),
        "drop_min3": len(drop3_rows),
        "drop_min5": len(drop5_rows),
        "drop_lottery": len(lottery_drop_rows),
        "drop_dom": len(dom_drop_rows),
    }

    # Write drop / keep CSVs
    drop_fields = [
        "sym",
        "n_is",
        "avg_pnl",
        "avg_wo_max",
        "max_pnl",
        "sum_pnl",
        "max_share_of_sum",
        "wins",
        "losses",
        "reason",
    ]
    write_csv(OUT / "drop_min_is_trades_3.csv", drop3_rows, drop_fields)
    write_csv(OUT / "drop_min_is_trades_5.csv", drop5_rows, drop_fields)
    write_csv(OUT / "drop_lottery_wo_max.csv", lottery_drop_rows, drop_fields)
    write_csv(OUT / "drop_lottery_dominance.csv", dom_drop_rows, drop_fields)
    write_csv(
        OUT / "keep_min_is_trades_3.csv",
        [{"sym": s, "n_is": is_stats[s]["n_is"]} for s in sorted(keep3)],
        ["sym", "n_is"],
    )
    write_csv(
        OUT / "keep_min_is_trades_5.csv",
        [{"sym": s, "n_is": is_stats[s]["n_is"]} for s in sorted(keep5)],
        ["sym", "n_is"],
    )
    write_csv(
        OUT / "keep_lottery_wo_max.csv",
        [
            {
                "sym": s,
                "n_is": is_stats[s]["n_is"] if s in is_stats else 0,
                "avg_wo_max": is_stats[s]["avg_wo_max"] if s in is_stats else "",
            }
            for s in sorted(keep_lottery)
        ],
        ["sym", "n_is", "avg_wo_max"],
    )
    write_csv(
        OUT / "is_symbol_stats.csv",
        [is_stats[s] for s in sorted(is_stats.keys())],
        [
            "sym",
            "n_is",
            "avg_pnl",
            "avg_wo_max",
            "max_pnl",
            "sum_pnl",
            "max_share_of_sum",
            "wins",
            "losses",
        ],
    )
    write_csv(OUT / "is_onetimers.csv", [{"sym": s, "n_is": 1} for s in is_ones], ["sym", "n_is"])
    write_csv(OUT / "never_traded.csv", [{"sym": s} for s in never], ["sym"])

    # metrics_all
    metric_rows = []
    for a in ab1_arms + [x for x in ab2_arms if x["id"] != "control"]:
        for split, key in (("IS", "m_is"), ("OOS", "m_oos"), ("FULL", "m_full")):
            metric_rows.append(
                metric_row(a["id"], a["ab"], split, a[key], a["n_drop"], a["n_keep_is"])
            )
    # ensure control once
    write_csv(
        OUT / "metrics_all.csv",
        metric_rows,
        list(metric_rows[0].keys()) if metric_rows else [],
    )

    write_html(OUT / "compare.html", ab1_arms, ab2_arms, control, is_stats, meta)
    write_baseline(OUT / "BASELINE.md", ab1_arms, ab2_arms, meta)
    write_summary(OUT / "SUMMARY.md", ab1_arms, ab2_arms, control, meta)

    # Print console summary for parent
    print("=== META ===")
    for k, v in meta.items():
        print(f"  {k}: {v}")
    print("=== AB1 IS ===")
    for a in ab1_arms:
        m = a["m_is"]
        print(
            f"  {a['id']}: N={m['n']} WR={m['wr']:.1f} Avg={m['avg_pnl']:.2f} "
            f"WO={m['wo_max']:.2f} PF={m['pf']:.2f} Ann={fmt_n(m['ann_ror'])} DD={fmt_n(m['max_dd'])}"
        )
    print("=== AB1 OOS ===")
    for a in ab1_arms:
        m = a["m_oos"]
        print(
            f"  {a['id']}: N={m['n']} WR={m['wr']:.1f} Avg={m['avg_pnl']:.2f} "
            f"WO={m['wo_max']:.2f} PF={m['pf']:.2f} Ann={fmt_n(m['ann_ror'])} DD={fmt_n(m['max_dd'])}"
        )
    print("=== AB2 IS ===")
    for a in ab2_arms:
        m = a["m_is"]
        print(
            f"  {a['id']}: N={m['n']} WR={m['wr']:.1f} Avg={m['avg_pnl']:.2f} "
            f"WO={m['wo_max']:.2f} PF={m['pf']:.2f} Ann={fmt_n(m['ann_ror'])} DD={fmt_n(m['max_dd'])}"
        )
    print("=== AB2 OOS ===")
    for a in ab2_arms:
        m = a["m_oos"]
        print(
            f"  {a['id']}: N={m['n']} WR={m['wr']:.1f} Avg={m['avg_pnl']:.2f} "
            f"WO={m['wo_max']:.2f} PF={m['pf']:.2f} Ann={fmt_n(m['ann_ror'])} DD={fmt_n(m['max_dd'])}"
        )

    html_path = OUT / "compare.html"
    print(f"HTML: {html_path}")
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "ntfy_job_done.py"),
            "--path",
            str(html_path),
            "-t",
            "RL 764 one-timer/lottery AB",
            "-m",
            f"AB1 drops min3={meta['drop_min3']} min5={meta['drop_min5']}; "
            f"AB2 lottery={meta['drop_lottery']} dom={meta['drop_dom']}. Research only.",
        ],
        cwd=str(ROOT),
        check=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
