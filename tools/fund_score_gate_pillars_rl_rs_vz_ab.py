#!/usr/bin/env python3
"""Expanded fund-scorecard pillar gate AB on RL / RS / VZ Closed books (research-only).

Overlay filter by house scorecard pillars (one knob per arm):
  Valuation / Quality / Growth Stability / Composite × ≥60 / ≥70.

Prior stamp ``fund_score_gate_rl_rs_vz_20260831`` gated **Quality pillar only**
(``score_quality``) — not Composite. This stamp expands the other pillars while
keeping ``quality_ge_*`` arms for continuity.

Scores default to industry-peer stamp ``fund_scorecard_v1_industry_20260831``.
Snapshot overlay on historical entries = contaminated / look-ahead — labeled.
Financial Health skipped (often NA). OOS report-only. No Sheet/Total PnL $.

Usage:
  python tools/fund_score_gate_pillars_rl_rs_vz_ab.py
  python tools/fund_score_gate_pillars_rl_rs_vz_ab.py --scores path/to/scores.csv
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import math
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any, Optional

import pandas as pd

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
    book_stats,
    load_trades,
    split_is_oos,
    verdict_vs_control,
)
import rl_univ_compare_lists as _rlul  # noqa: E402

STAMP = "fund_score_gate_pillars_rl_rs_vz_20260831"
OUT = ROOT / "drive" / "paul_experiments" / STAMP
SCORES_DEFAULT = (
    ROOT / "drive" / "paul_experiments" / "fund_scorecard_v1_industry_20260831" / "scores.csv"
)
SCORES_FALLBACK = (
    ROOT / "drive" / "paul_experiments" / "fund_scorecard_v1_20260830" / "scores.csv"
)

RL_CLOSED = (
    ROOT
    / "drive"
    / "paul_experiments"
    / "rl_tradable_2010_adv2m_20260828"
    / "runs"
    / "tradable"
    / "RL_Closed_260828112205.csv"
)
RS_CLOSED = ROOT / "drive" / "RS_LatestRun_Closed.csv"
VZ_CLOSED = ROOT / "drive" / "VZ_Closed_260817212836.csv"

SYSTEMS: list[dict[str, Any]] = [
    {
        "id": "RL",
        "label": "RL 764 tradable",
        "closed": RL_CLOSED,
        "cash": 47_500.0,
        "book_note": (
            "rl_tradable_2010_adv2m_20260828 / runs/tradable / RL_Closed_260828112205.csv "
            "(764-name ADV$2m tape; prefer breadth over house 59)"
        ),
    },
    {
        "id": "RS",
        "label": "RS LatestRun",
        "closed": RS_CLOSED,
        "cash": 47_500.0,
        "book_note": "drive/RS_LatestRun_Closed.csv (production LatestRun alias)",
    },
    {
        "id": "VZ",
        "label": "VZ DualPaul78",
        "closed": VZ_CLOSED,
        "cash": 45_000.0,
        "book_note": (
            "drive/VZ_Closed_260817212836.csv — DualPaul78 live Closed "
            "(documented in vz_tradable_2010_adv2m_20260818 BASELINE; not tradable-764 slice)"
        ),
    },
]

# One-knob arms: control + each pillar × {60,70}. Skip Financial Health.
# quality_ge_* identical rule to prior stamp (Quality pillar continuity).
ARMS_SPEC = [
    {"id": "control", "label": "control (full book)", "pillar": None, "thr": None},
    {"id": "valuation_ge_60", "label": "Valuation ≥ 60", "pillar": "score_valuation", "thr": 60.0},
    {"id": "valuation_ge_70", "label": "Valuation ≥ 70", "pillar": "score_valuation", "thr": 70.0},
    {"id": "quality_ge_60", "label": "Quality ≥ 60 (pillar)", "pillar": "score_quality", "thr": 60.0},
    {"id": "quality_ge_70", "label": "Quality ≥ 70 (pillar)", "pillar": "score_quality", "thr": 70.0},
    {
        "id": "growth_stability_ge_60",
        "label": "Growth Stability ≥ 60",
        "pillar": "score_growth_stability",
        "thr": 60.0,
    },
    {
        "id": "growth_stability_ge_70",
        "label": "Growth Stability ≥ 70",
        "pillar": "score_growth_stability",
        "thr": 70.0,
    },
    {"id": "composite_ge_60", "label": "Composite ≥ 60", "pillar": "score_composite", "thr": 60.0},
    {"id": "composite_ge_70", "label": "Composite ≥ 70", "pillar": "score_composite", "thr": 70.0},
]

PILLAR_GROUPS = [
    ("valuation", "Valuation", ["valuation_ge_60", "valuation_ge_70"]),
    ("quality", "Quality pillar", ["quality_ge_60", "quality_ge_70"]),
    ("growth_stability", "Growth Stability", ["growth_stability_ge_60", "growth_stability_ge_70"]),
    ("composite", "Composite", ["composite_ge_60", "composite_ge_70"]),
]


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


def load_scores(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
    # Ensure composite exists (equal-weight of available pillars) if missing
    pillar_cols = [
        "score_valuation",
        "score_quality",
        "score_growth_stability",
        "score_financial_health",
    ]
    present = [c for c in pillar_cols if c in df.columns]
    if "score_composite" not in df.columns and present:
        df["score_composite"] = df[present].mean(axis=1, skipna=True)
    return df.set_index("symbol", drop=False)


def keep_symbols_for_arm(
    scores: pd.DataFrame,
    traded: set[str],
    pillar: Optional[str],
    thr: Optional[float],
) -> tuple[set[str], dict[str, Any]]:
    """Symbols that pass the gate. Missing pillar score → fail (cannot pass ≥ thr)."""
    if pillar is None or thr is None:
        return set(traded), {"n_pass": len(traded), "n_fail_score": 0, "n_missing": 0, "n_no_row": 0}

    pass_set: set[str] = set()
    n_fail = n_miss = n_norow = 0
    for sym in traded:
        if sym not in scores.index:
            n_norow += 1
            continue
        val = scores.at[sym, pillar] if pillar in scores.columns else float("nan")
        try:
            v = float(val)
        except (TypeError, ValueError):
            v = float("nan")
        if not math.isfinite(v):
            n_miss += 1
            continue
        if v >= thr:
            pass_set.add(sym)
        else:
            n_fail += 1
    return pass_set, {
        "n_pass": len(pass_set),
        "n_fail_score": n_fail,
        "n_missing": n_miss,
        "n_no_row": n_norow,
    }


def filter_trades(trades: list[dict[str, Any]], keep: set[str]) -> list[dict[str, Any]]:
    return [t for t in trades if t["sym"] in keep]


def stats_with_cash(trades: list[dict[str, Any]], cash: float) -> dict[str, Any]:
    prev = _rlul.RL_CASH
    try:
        _rlul.RL_CASH = cash
        return book_stats(trades)
    finally:
        _rlul.RL_CASH = prev


def pack_arm(
    spec: dict[str, Any],
    all_trades: list[dict[str, Any]],
    keep: set[str],
    cov: dict[str, Any],
    cash: float,
) -> dict[str, Any]:
    if spec["id"] == "control":
        trades = list(all_trades)
        keep = {t["sym"] for t in all_trades}
    else:
        trades = filter_trades(all_trades, keep)
    is_t, oos_t = split_is_oos(trades)
    return {
        "id": spec["id"],
        "label": spec["label"],
        "pillar": spec["pillar"],
        "thr": spec["thr"],
        "keep": keep,
        "cov": cov,
        "n_keep_sym": len(keep),
        "trades": trades,
        "m_full": stats_with_cash(trades, cash),
        "m_is": stats_with_cash(is_t, cash),
        "m_oos": stats_with_cash(oos_t, cash),
        "is_t": is_t,
        "oos_t": oos_t,
    }


def arm_verdict(arm: dict[str, Any], control: dict[str, Any]) -> tuple[str, str, str, str]:
    """Return (overall, is_v, oos_v, note). Contaminated ceiling: LEAN KEEP max."""
    packed_cand = {"m_is": arm["m_is"], "m_oos": arm["m_oos"], "m_full": arm["m_full"]}
    packed_ctrl = {
        "m_is": control["m_is"],
        "m_oos": control["m_oos"],
        "m_full": control["m_full"],
    }
    is_v, is_n = verdict_vs_control(packed_cand, packed_ctrl, "m_is")
    oos_v, oos_n = verdict_vs_control(packed_cand, packed_ctrl, "m_oos")
    tag = is_v
    note = f"IS={is_v} ({is_n}); OOS={oos_v} ({oos_n})"
    if is_v in ("KEEP", "LEAN KEEP") and oos_v == "DISMISS":
        tag = "HOLD"
        note += " → overall HOLD (OOS softens; no OOS retune)"
    elif is_v == "KEEP":
        tag = "LEAN KEEP"  # contamination ceiling
    return tag, is_v, oos_v, note


def build_compare_table(
    title: str,
    arms: list[dict[str, Any]],
    control: dict[str, Any],
    split_key: str,
) -> str:
    cols = [
        ("Arm", "text"),
        ("N keep sym", "num"),
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
    cols = [(a, b) for a, b in cols if "Sheet" not in a and "Total PnL" not in a]

    c = control[split_key]
    rows_html = []
    for arm in arms:
        m = arm[split_key]
        if arm["id"] == "control":
            verd, vnote = "CONTROL", "full Closed book"
        else:
            packed_cand = {"m_is": arm["m_is"], "m_oos": arm["m_oos"], "m_full": arm["m_full"]}
            packed_ctrl = {
                "m_is": control["m_is"],
                "m_oos": control["m_oos"],
                "m_full": control["m_full"],
            }
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
            "N keep sym": f'<td data-sort-value="{arm["n_keep_sym"]}">{arm["n_keep_sym"]}</td>',
            "N": f'<td data-sort-value="{m["n"]}">{m["n"]}</td>',
            "WR %": f'<td data-sort-value="{m["wr"]}">{fmt_pct(m["wr"])}</td>',
            "Avg PnL %": f'<td data-sort-value="{m["avg_pnl"]}">{fmt_pct(m["avg_pnl"])}</td>',
            "WO_MAX %": f'<td data-sort-value="{m["wo_max"]}">{fmt_pct(m["wo_max"])}</td>',
            "PF": f'<td data-sort-value="{m["pf"]}">{fmt_n(m["pf"])}</td>',
            "Avg win %": f'<td data-sort-value="{m["avg_win"]}">{fmt_pct(m["avg_win"])}</td>',
            "Avg loss %": f'<td data-sort-value="{m["avg_loss"]}">{fmt_pct(m["avg_loss"])}</td>',
            "Ann ROR %": (
                f'<td data-sort-value="{m["ann_ror"] if math.isfinite(m["ann_ror"]) else ""}">'
                f'{fmt_pct(m["ann_ror"])}</td>'
            ),
            "Max DD %": (
                f'<td data-sort-value="{m["max_dd"] if math.isfinite(m["max_dd"]) else ""}">'
                f'{fmt_pct(m["max_dd"])}</td>'
            ),
            "Calmar": (
                f'<td data-sort-value="{m["calmar"] if math.isfinite(m["calmar"]) else ""}">'
                f'{fmt_n(m["calmar"])}</td>'
            ),
            "Avg days": f'<td data-sort-value="{m["avg_days"]}">{fmt_n(m["avg_days"], 1)}</td>',
            "Med days": f'<td data-sort-value="{m["med_days"]}">{fmt_n(m["med_days"], 1)}</td>',
            "Cap days": f'<td data-sort-value="{m["cap_days"]}">{fmt_n(m["cap_days"], 0)}</td>',
            "Profit / cap day": (
                f'<td data-sort-value="{m["ppc"] if math.isfinite(m["ppc"]) else ""}">'
                f'{format_money(m["ppc"]) if math.isfinite(m["ppc"]) else "—"}</td>'
            ),
            "Expectancy $": f'<td data-sort-value="{m["exp_d"]}">{format_money(m["exp_d"])}</td>',
            "Lose streak": f'<td data-sort-value="{m["lose_streak"]}">{m["lose_streak"]}</td>',
            "TPY": (
                f'<td data-sort-value="{m["tpy"] if math.isfinite(m["tpy"]) else ""}">'
                f'{fmt_n(m["tpy"])}</td>'
            ),
            "Δ Avg %": (
                f'<td data-sort-value="{d_avg if math.isfinite(d_avg) else ""}">'
                f'{fmt_n(d_avg) if math.isfinite(d_avg) else "—"}</td>'
            ),
            "Δ WO_MAX": (
                f'<td data-sort-value="{d_wo if math.isfinite(d_wo) else ""}">'
                f'{fmt_n(d_wo) if math.isfinite(d_wo) else "—"}</td>'
            ),
            "Δ PF": (
                f'<td data-sort-value="{d_pf if math.isfinite(d_pf) else ""}">'
                f'{fmt_n(d_pf) if math.isfinite(d_pf) else "—"}</td>'
            ),
            "Δ WR": (
                f'<td data-sort-value="{d_wr if math.isfinite(d_wr) else ""}">'
                f'{fmt_n(d_wr) if math.isfinite(d_wr) else "—"}</td>'
            ),
            "Δ Ann ROR": (
                f'<td data-sort-value="{d_ann if math.isfinite(d_ann) else ""}">'
                f'{fmt_n(d_ann) if math.isfinite(d_ann) else "—"}</td>'
            ),
            "Δ Max DD": (
                f'<td data-sort-value="{d_dd if math.isfinite(d_dd) else ""}">'
                f'{fmt_n(d_dd) if math.isfinite(d_dd) else "—"}</td>'
            ),
            "Δ Calmar": (
                f'<td data-sort-value="{d_cal if math.isfinite(d_cal) else ""}">'
                f'{fmt_n(d_cal) if math.isfinite(d_cal) else "—"}</td>'
            ),
            "Verdict vs ctrl": (
                f'<td data-sort-value="{esc(verd)}" title="{esc(vnote)}">{esc(verd)}</td>'
            ),
        }
        rows_html.append("<tr>" + "".join(cells[a] for a, _ in cols) + "</tr>")

    thead = "".join(sortable_th(a, b) for a, b in cols)
    return f"""
<h3>{esc(title)}</h3>
<p class="sub">Click column headers to sort. No Sheet/Total PnL $ columns.
Contaminated overlay — today's pillar scores on historical entries.
Prior Quality-only stamp used <strong>Quality pillar</strong> (not Composite).</p>
<table class="sortable">
<thead><tr>{thead}</tr></thead>
<tbody>
{"".join(rows_html)}
</tbody>
</table>
"""


def coverage_table(sys_id: str, arms: list[dict[str, Any]], n_traded: int) -> str:
    cols = [
        ("Arm", "text"),
        ("N keep sym", "num"),
        ("Pass", "num"),
        ("Fail (&lt;thr)", "num"),
        ("Missing pillar", "num"),
        ("No score row", "num"),
        ("Traded univ", "num"),
    ]
    rows = []
    for a in arms:
        cov = a["cov"]
        rows.append(
            "<tr>"
            f'<td data-sort-value="{esc(a["id"])}">{esc(a["label"])}</td>'
            f'<td data-sort-value="{a["n_keep_sym"]}">{a["n_keep_sym"]}</td>'
            f'<td data-sort-value="{cov.get("n_pass", a["n_keep_sym"])}">{cov.get("n_pass", a["n_keep_sym"])}</td>'
            f'<td data-sort-value="{cov.get("n_fail_score", 0)}">{cov.get("n_fail_score", 0)}</td>'
            f'<td data-sort-value="{cov.get("n_missing", 0)}">{cov.get("n_missing", 0)}</td>'
            f'<td data-sort-value="{cov.get("n_no_row", 0)}">{cov.get("n_no_row", 0)}</td>'
            f'<td data-sort-value="{n_traded}">{n_traded}</td>'
            "</tr>"
        )
    thead = "".join(sortable_th(a, b) for a, b in cols)
    return f"""
<h3>{esc(sys_id)} — score coverage</h3>
<table class="sortable"><thead><tr>{thead}</tr></thead><tbody>{"".join(rows)}</tbody></table>
"""


def pillar_verdicts_table(sys_pack: dict[str, Any]) -> str:
    by_id = {a["id"]: a for a in sys_pack["arms"]}
    rows = []
    for _key, label, arm_ids in PILLAR_GROUPS:
        for aid in arm_ids:
            a = by_id[aid]
            av = a["arm_verdict"]
            rows.append(
                "<tr>"
                f'<td data-sort-value="{esc(label)}">{esc(label)}</td>'
                f'<td data-sort-value="{esc(aid)}">{esc(aid)}</td>'
                f'<td data-sort-value="{esc(av["overall"])}">{esc(av["overall"])}</td>'
                f'<td data-sort-value="{esc(av["is"])}">{esc(av["is"])}</td>'
                f'<td data-sort-value="{esc(av["oos"])}">{esc(av["oos"])}</td>'
                f'<td>{esc(av["note"])}</td>'
                "</tr>"
            )
    cols = [
        ("Pillar", "text"),
        ("Arm", "text"),
        ("Overall", "text"),
        ("IS", "text"),
        ("OOS", "text"),
        ("Note", "text"),
    ]
    thead = "".join(sortable_th(a, b) for a, b in cols)
    return f"""
<h3>{esc(sys_pack["id"])} — per-pillar verdicts</h3>
<p class="sub">IS quality-over-N; OOS report-only (softens → HOLD). Contaminated ceiling = LEAN KEEP.</p>
<table class="sortable"><thead><tr>{thead}</tr></thead><tbody>{"".join(rows)}</tbody></table>
"""


def system_verdict(arms: list[dict[str, Any]], control: dict[str, Any]) -> tuple[str, str, dict[str, dict]]:
    """Overall + per-arm verdicts. Contaminated overlay: never stronger than LEAN KEEP."""
    per_arm: dict[str, dict[str, str]] = {}
    notes = []
    is_tags = []
    best_id = "control"
    best_tag = "HOLD"
    for a in arms:
        if a["id"] == "control":
            continue
        tag, is_v, oos_v, note = arm_verdict(a, control)
        per_arm[a["id"]] = {"overall": tag, "is": is_v, "oos": oos_v, "note": note}
        notes.append(f"{a['id']}: {note}")
        is_tags.append(tag)
        if tag in ("LEAN KEEP", "KEEP") and best_tag not in ("LEAN KEEP", "KEEP"):
            best_tag = "LEAN KEEP"
            best_id = a["id"]
    if "LEAN KEEP" in is_tags or "KEEP" in is_tags:
        overall = "LEAN KEEP"
    elif is_tags and all(t == "DISMISS" for t in is_tags):
        overall = "DISMISS"
    else:
        overall = "HOLD"
    note = f"best_arm={best_id}. " + " | ".join(notes)
    return overall, note, per_arm


def write_metrics_csv(path: Path, packed_systems: list[dict[str, Any]]) -> None:
    fields = [
        "system",
        "arm",
        "pillar",
        "thr",
        "split",
        "n_keep_sym",
        "n",
        "wins",
        "losses",
        "wr",
        "avg_pnl",
        "wo_max",
        "pf",
        "avg_win",
        "avg_loss",
        "avg_days",
        "med_days",
        "cap_days",
        "ppc",
        "ann_ror",
        "max_dd",
        "calmar",
        "exp_d",
        "lose_streak",
        "tpy",
        "n_pass",
        "n_fail_score",
        "n_missing",
        "n_no_row",
        "verdict_overall",
        "verdict_is",
        "verdict_oos",
    ]
    rows = []
    for sys_pack in packed_systems:
        for arm in sys_pack["arms"]:
            av = arm.get("arm_verdict") or {}
            for split, key in (("FULL", "m_full"), ("IS", "m_is"), ("OOS", "m_oos")):
                m = arm[key]
                cov = arm["cov"]
                rows.append(
                    {
                        "system": sys_pack["id"],
                        "arm": arm["id"],
                        "pillar": arm.get("pillar") or "",
                        "thr": arm.get("thr") if arm.get("thr") is not None else "",
                        "split": split,
                        "n_keep_sym": arm["n_keep_sym"],
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
                        "n_pass": cov.get("n_pass", ""),
                        "n_fail_score": cov.get("n_fail_score", ""),
                        "n_missing": cov.get("n_missing", ""),
                        "n_no_row": cov.get("n_no_row", ""),
                        "verdict_overall": av.get("overall", "CONTROL" if arm["id"] == "control" else ""),
                        "verdict_is": av.get("is", ""),
                        "verdict_oos": av.get("oos", ""),
                    }
                )
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def write_keep_lists(out_dir: Path, packed_systems: list[dict[str, Any]]) -> None:
    for sys_pack in packed_systems:
        for arm in sys_pack["arms"]:
            if arm["id"] == "control":
                continue
            path = out_dir / f"{sys_pack['id'].lower()}_{arm['id']}_symbols.csv"
            with path.open("w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["symbol"])
                for s in sorted(arm["keep"]):
                    w.writerow([s])


def write_html(
    path: Path,
    packed_systems: list[dict[str, Any]],
    meta: dict[str, Any],
    scores_rel: str,
) -> None:
    sections = []
    for sys_pack in packed_systems:
        sid = sys_pack["id"]
        ctrl = sys_pack["control"]
        arms = sys_pack["arms"]
        verd, vnote = sys_pack["verdict"], sys_pack["verdict_note"]
        sections.append(
            f"""
<h2>{esc(sid)} — {esc(sys_pack['label'])}</h2>
<div class="box">
<p><strong>Book:</strong> <code>{esc(sys_pack['book_note'])}</code></p>
<p><strong>Cash overlay:</strong> ${sys_pack['cash']:,.0f} · FULL N={sys_pack['n_full']}
IS N={sys_pack['n_is']} OOS N={sys_pack['n_oos']} · traded symbols={sys_pack['n_traded']}</p>
<p><strong>System verdict (research):</strong> <code>{esc(verd)}</code> — {esc(vnote)}</p>
</div>
{pillar_verdicts_table(sys_pack)}
{coverage_table(sid, arms, sys_pack['n_traded'])}
{build_compare_table(f"{sid} — IS (entry &lt; 2024-01-01)", arms, ctrl, "m_is")}
{build_compare_table(f"{sid} — OOS (report-only)", arms, ctrl, "m_oos")}
{build_compare_table(f"{sid} — FULL", arms, ctrl, "m_full")}
"""
        )

    arm_lis = "\n".join(
        f"<li><code>{esc(a['id'])}</code> — {esc(a['label'])}"
        + (
            f" (<code>{esc(a['pillar'])} ≥ {a['thr']:.0f}</code>)"
            if a["pillar"]
            else ""
        )
        + "</li>"
        for a in ARMS_SPEC
    )

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>Fund score pillar gates RL/RS/VZ — {STAMP}</title>
<style>
:root {{ --bg:#f7f5ef; --ink:#1c1b19; --muted:#6a655c; --line:#d9d3c5; --fill:#fffdf8; --accent:#2f5d50; --warn:#8a4b1a; }}
body {{ font-family: "Segoe UI", system-ui, sans-serif; background:var(--bg); color:var(--ink); margin:0; padding:24px; line-height:1.45; }}
h1 {{ font-size:1.45rem; margin:0 0 8px; }}
h2 {{ font-size:1.15rem; margin:28px 0 8px; border-bottom:1px solid var(--line); padding-bottom:4px; }}
h3 {{ font-size:1.02rem; margin:20px 0 6px; color:var(--accent); }}
.sub, .meta {{ color:var(--muted); font-size:0.88rem; }}
.box {{ background:var(--fill); border:1px solid var(--line); padding:12px 14px; margin:12px 0; }}
.warn {{ border-left:4px solid var(--warn); }}
table.sortable {{ border-collapse:collapse; width:100%; font-size:0.82rem; background:var(--fill); margin:8px 0 18px; }}
table.sortable th, table.sortable td {{ border:1px solid var(--line); padding:5px 7px; text-align:left; }}
table.sortable th {{ background:#efeae0; }}
{SORTABLE_TH_CSS}
code {{ background:#efeae0; padding:0.08em 0.3em; font-size:0.86em; }}
ul {{ margin:6px 0 6px 1.2em; }}
</style></head><body>
<h1>House fund scorecard pillar gates — RL / RS / VZ</h1>
<p class="meta"><strong>Research only.</strong> Not gold. Not DailyRun. Overlay on Closed CSVs — no engine rerun.
Stamp <code>{STAMP}</code>. Score source <code>{esc(scores_rel)}</code>
({meta['n_scores']} symbols).</p>

<div class="box warn">
<strong>Look-ahead / contamination caveat</strong>
<ul>
<li>Scores are a <strong>point-in-time research snapshot</strong> (Yahoo / DuckDB proxies — not Fidelity / S&amp;P).</li>
<li>Joining today's pillars onto past entries is a <strong>descriptive contaminated overlay</strong>
(research upper-bound), <em>not</em> a clean historical PIT gate.</li>
<li><strong>Prior stamp clarification:</strong> <code>fund_score_gate_rl_rs_vz_20260831</code>
<code>quality_ge_60/70</code> used the <strong>Quality pillar</strong> (<code>score_quality</code>),
<strong>not</strong> Composite.</li>
<li>Arms use fixed a-priori thresholds (60 / 70); Financial Health skipped (often NA). OOS report-only.</li>
<li>Selection bias labeled; contaminated overlay cannot promote to gold / DailyRun.</li>
</ul>
</div>

<div class="box">
<strong>Hypothesis</strong>
<p>Does filtering by each house fund scorecard pillar (Valuation, Quality, Growth Stability)
or equal-weight <em>Composite</em> improve trade quality vs the full Closed book?
One knob per arm.</p>
<strong>Arms (same all systems)</strong>
<ul>
{arm_lis}
</ul>
<p>Missing pillar → fail gate. IS = entry &lt; 2024-01-01; OOS ≥ 2024-01-01. Judge quality over N.</p>
</div>

{"".join(sections)}

<p class="meta">Generated {date.today().isoformat()}. Tool <code>tools/fund_score_gate_pillars_rl_rs_vz_ab.py</code>.</p>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    path.write_text(html, encoding="utf-8")


def write_baseline(
    path: Path,
    packed_systems: list[dict[str, Any]],
    meta: dict[str, Any],
    scores_rel: str,
) -> None:
    lines = [
        f"# BASELINE — `{STAMP}`",
        "",
        "**Status:** RESEARCH only. **Not gold. Not DailyRun-wired.**",
        "",
        "## Clarification vs prior Quality-only stamp",
        "",
        "Prior `fund_score_gate_rl_rs_vz_20260831` arms `quality_ge_60` / `quality_ge_70`",
        "gated on the **Quality pillar** (`score_quality`) — **not** Composite,",
        "Valuation, or Growth Stability. This stamp keeps those Quality arms for continuity",
        "and adds Valuation / Growth Stability / Composite gates (Financial Health skipped).",
        "",
        "## Hypothesis (one theme, many one-knob arms)",
        "",
        "Does filtering entries/symbols by each house fund scorecard pillar",
        "(Valuation, Quality, Growth Stability) or equal-weight Composite improve trade quality",
        "on RL / RS / VZ Closed books vs full-book control?",
        "",
        "House proxies — **not** Fidelity / S&P Global parity. Prefer industry-peer scores from",
        "`fund_scorecard_v1_industry_20260831`.",
        "",
        "## Look-ahead honesty (critical)",
        "",
        f"- Score source: `{scores_rel}`",
        "  (snapshot as-of scorecard stamp — **not** point-in-time at entry).",
        "- Applying today's pillars to historical Closed trades = **descriptive contaminated overlay**",
        "  / research upper-bound. **Not** a clean historical gate.",
        "- Thresholds 60 / 70 chosen a priori; not retuned on OOS.",
        "- Financial Health gate skipped (often NA).",
        "",
        "## Books",
        "",
    ]
    for s in packed_systems:
        lines.append(f"- **{s['id']}:** `{s['closed_rel']}` — {s['book_note']}")
        lines.append(
            f"  - FULL N={s['n_full']}; IS N={s['n_is']}; OOS N={s['n_oos']}; "
            f"traded symbols={s['n_traded']}; cash overlay ${s['cash']:,.0f}"
        )
    lines += [
        "",
        "## Arms (identical per system; one knob each)",
        "",
        "| Arm | Rule |",
        "|-----|------|",
        "| `control` | Full Closed book |",
        "| `valuation_ge_60` | `score_valuation ≥ 60` |",
        "| `valuation_ge_70` | `score_valuation ≥ 70` |",
        "| `quality_ge_60` | **Quality pillar** `score_quality ≥ 60` (same as prior stamp) |",
        "| `quality_ge_70` | **Quality pillar** `score_quality ≥ 70` (same as prior stamp) |",
        "| `growth_stability_ge_60` | `score_growth_stability ≥ 60` |",
        "| `growth_stability_ge_70` | `score_growth_stability ≥ 70` |",
        "| `composite_ge_60` | `score_composite ≥ 60` (equal-weight mean of available pillars) |",
        "| `composite_ge_70` | `score_composite ≥ 70` |",
        "",
        "## Process",
        "",
        "- Overlay filter on Closed CSVs — **no engine re-run**",
        "- IS = `entry_date < 2024-01-01`; OOS = `entry_date >= 2024-01-01`",
        "- Judge **quality over N**; OOS report-only; no OOS retune",
        "- HTML omits Sheet / Total PnL $",
        "- Selection bias labeled; contaminated overlay cannot promote to gold / DailyRun",
        "",
        "## Artifacts",
        "",
        "- `compare.html` — per-system IS / OOS / FULL + per-pillar verdicts",
        "- `metrics_all.csv` — flat metrics",
        "- `*_ge_*_symbols.csv` — keep lists",
        "- `SUMMARY.md` — KEEP / HOLD / DISMISS by system and pillar",
        "",
        f"Score rows: **{meta['n_scores']}**. Generated {date.today().isoformat()}.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_summary(path: Path, packed_systems: list[dict[str, Any]]) -> None:
    lines = [
        f"# SUMMARY — `{STAMP}`",
        "",
        "**Research only. Contaminated overlay (snapshot scores on historical entries).**",
        "**Not gold. Not DailyRun.**",
        "",
        "Prior `quality_ge_*` = **Quality pillar** only (not Composite). This stamp expands pillars.",
        "",
        "## System verdicts (any LEAN KEEP arm → system LEAN KEEP)",
        "",
        "| System | Book | Verdict | Best arm note |",
        "|--------|------|---------|---------------|",
    ]
    for s in packed_systems:
        # shorten note
        note = s["verdict_note"].split(" | ")[0].replace("|", "/")
        lines.append(
            f"| {s['id']} | {s['label']} | **{s['verdict']}** | {note} |"
        )

    lines += ["", "## Per-pillar verdicts by system", ""]
    lines.append(
        "| System | Pillar | Arm | Overall | IS | OOS |"
    )
    lines.append("|--------|--------|-----|---------|----|-----|")
    for s in packed_systems:
        by_id = {a["id"]: a for a in s["arms"]}
        for _k, label, aids in PILLAR_GROUPS:
            for aid in aids:
                a = by_id[aid]
                av = a["arm_verdict"]
                lines.append(
                    f"| {s['id']} | {label} | `{aid}` | **{av['overall']}** | {av['is']} | {av['oos']} |"
                )

    lines += ["", "## IS / OOS snapshot (Avg PnL% / WO_MAX / PF / N)", ""]
    for s in packed_systems:
        lines.append(f"### {s['id']}")
        lines.append("")
        lines.append(
            "| Arm | IS N | IS Avg% | IS WO_MAX | IS PF | OOS N | OOS Avg% | OOS WO_MAX | OOS PF |"
        )
        lines.append(
            "|-----|------|---------|-----------|-------|-------|----------|------------|--------|"
        )
        for a in s["arms"]:
            mi, mo = a["m_is"], a["m_oos"]
            lines.append(
                f"| {a['id']} | {mi['n']} | {mi['avg_pnl']:.2f} | {mi['wo_max']:.2f} | {mi['pf']:.2f} | "
                f"{mo['n']} | {mo['avg_pnl']:.2f} | {mo['wo_max']:.2f} | {mo['pf']:.2f} |"
            )
        lines.append("")

    lines += [
        "## Interpretation",
        "",
        "- **LEAN KEEP** ⇒ pillar filter *looks* helpful on IS without OOS collapse — still research-only;",
        "  needs PIT scores / walk-forward before stronger claim.",
        "- **HOLD** ⇒ flat / mixed / OOS softens — do not adopt.",
        "- **DISMISS** ⇒ gate hurts IS quality.",
        "",
        "Do not wire DailyRun from contaminated overlays. No OOS retune.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def run_system(sys_cfg: dict[str, Any], scores: pd.DataFrame) -> dict[str, Any]:
    closed: Path = sys_cfg["closed"]
    if not closed.is_file():
        raise FileNotFoundError(closed)
    trades = load_trades(closed)
    traded = {t["sym"] for t in trades}
    is_t, oos_t = split_is_oos(trades)
    arms: list[dict[str, Any]] = []
    for spec in ARMS_SPEC:
        keep, cov = keep_symbols_for_arm(scores, traded, spec["pillar"], spec["thr"])
        arms.append(pack_arm(spec, trades, keep, cov, sys_cfg["cash"]))
    control = next(a for a in arms if a["id"] == "control")
    verd, vnote, per_arm = system_verdict(arms, control)
    for a in arms:
        if a["id"] == "control":
            a["arm_verdict"] = {
                "overall": "CONTROL",
                "is": "CONTROL",
                "oos": "CONTROL",
                "note": "full book",
            }
        else:
            a["arm_verdict"] = per_arm[a["id"]]
    try:
        closed_rel = closed.relative_to(ROOT).as_posix()
    except ValueError:
        closed_rel = str(closed)
    return {
        "id": sys_cfg["id"],
        "label": sys_cfg["label"],
        "book_note": sys_cfg["book_note"],
        "closed_rel": closed_rel,
        "cash": sys_cfg["cash"],
        "arms": arms,
        "control": control,
        "verdict": verd,
        "verdict_note": vnote,
        "n_full": len(trades),
        "n_is": len(is_t),
        "n_oos": len(oos_t),
        "n_traded": len(traded),
    }


def ntfy(paths: list[Path]) -> None:
    cmd = [sys.executable, str(ROOT / "tools" / "ntfy_job_done.py")]
    for p in paths:
        cmd.extend(["--path", str(p)])
    cmd.extend(
        ["-t", "Fund pillar gate AB done", "-m", f"{STAMP} RL/RS/VZ compare.html"]
    )
    try:
        subprocess.run(cmd, cwd=str(ROOT), check=False)
    except Exception:
        pass


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Expanded pillar fund-score gate AB (RL/RS/VZ)")
    ap.add_argument("--scores", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--skip-ntfy", action="store_true")
    args = ap.parse_args(argv)

    out_dir = args.out if args.out.is_absolute() else ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.scores is not None:
        scores_path = args.scores if args.scores.is_absolute() else ROOT / args.scores
    elif SCORES_DEFAULT.is_file():
        scores_path = SCORES_DEFAULT
    elif SCORES_FALLBACK.is_file():
        print(f"[pillars-ab] industry scores missing; fallback {SCORES_FALLBACK}")
        scores_path = SCORES_FALLBACK
    else:
        raise SystemExit(f"Missing scores: tried {SCORES_DEFAULT} and {SCORES_FALLBACK}")

    if not scores_path.is_file():
        raise SystemExit(f"Missing scores: {scores_path}")

    scores = load_scores(scores_path)
    packed = [run_system(s, scores) for s in SYSTEMS]
    meta = {"n_scores": int(len(scores))}
    try:
        scores_rel = scores_path.relative_to(ROOT).as_posix()
    except ValueError:
        scores_rel = str(scores_path)

    write_metrics_csv(out_dir / "metrics_all.csv", packed)
    write_keep_lists(out_dir, packed)
    write_html(out_dir / "compare.html", packed, meta, scores_rel)
    write_baseline(out_dir / "BASELINE.md", packed, meta, scores_rel)
    write_summary(out_dir / "SUMMARY.md", packed)

    if not args.skip_ntfy:
        ntfy([out_dir / "compare.html"])

    print(f"Wrote {out_dir}")
    print(f"Scores: {scores_rel}")
    for s in packed:
        print(f"  {s['id']}: {s['verdict']}  FULL={s['n_full']} IS={s['n_is']} OOS={s['n_oos']}")
        for a in s["arms"]:
            if a["id"] == "control":
                continue
            av = a["arm_verdict"]
            print(f"    {a['id']}: {av['overall']} (IS={av['is']} OOS={av['oos']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
