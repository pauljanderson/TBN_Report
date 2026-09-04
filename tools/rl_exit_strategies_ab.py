#!/usr/bin/env python3
"""RL exit-strategy A/B — one-change arms vs frozen control (tradable 764).

Three families (never factorial-combined for a “winner”):

1. Time-stop (EXIT): `rl_exit_days` after +29% MTM (`rl_exit_percent=0.29` frozen).
   Control = 10000 (off). Required arm = 40 (prior PO CONSIDER). Reuse Closed when present.
2. System flush (EXIT): `rl_flush_days` underwater vs HWM → FLUSH_EXIT. Control = 0 (off).
3. Cut-the-losers (ENTRY filter): `rl_cut_the_losers` (prior-bar high vs SMA50).
   House = 0.25. Off = 1000.

House freeze (do not silently change): dip=1.055, expansion=1.163, stop=0.934,
target=1.20, trails off, exit_percent=0.29, flush=0 / exit_days=10000 / cut=0.25 on control.

IS = entry < 2024-01-01; OOS report-only; no OOS retune.
Research-only. Not gold. Not DailyRun.

Usage:
  python tools/rl_exit_strategies_ab.py
  python tools/rl_exit_strategies_ab.py --priority
  python tools/rl_exit_strategies_ab.py --summarize-only
  python tools/rl_exit_strategies_ab.py --skip-existing --jobs 3 --workers 12
"""
from __future__ import annotations

import argparse
import html as html_mod
import math
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
STAMP = "20260831"
OUT_DIR = DRIVE / "paul_experiments" / f"rl_exit_strategies_ab_{STAMP}"
CONTROL_SRC = (
    DRIVE / "paul_experiments" / "rl_tradable_2010_adv2m_20260828" / "runs" / "tradable"
)
DAYS40_SRC = (
    DRIVE / "paul_experiments" / "rl_time_stop_tradable_20260828" / "runs" / "days40"
)
DAYS40_STAMP = "260828184602"  # fill-fixed; VOID first Closed 260828161053
CONTROL_STAMP = "260828112205"
UNIVERSE_CSV = DRIVE / "universes" / "VZ_tradable_2010_adv2m_universe.csv"
CONTROL_ID = "control"

# House defaults documented for freeze table
HOUSE_EXIT_PERCENT = 0.29
HOUSE_CUT = 0.25
HOUSE_EXIT_DAYS = 10000
HOUSE_FLUSH = 0

sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(DRIVE / "paul_experiments"))
from be_stop_replay_ab import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402
from compare_format import filter_html_compare_columns  # noqa: E402
from rl_univ_compare_lists import (  # noqa: E402
    build_cmd as _lists_build_cmd,
    compare_row,
    fmt_n,
    load_trades,
    pack_result,
    pairwise_delta_row,
    verdict_vs_control,
    write_metrics_csv,
    _find_latest,
    _resolve_python,
)
from vz_is_paul_universe_ab import load_universe_symbols  # noqa: E402


def _arm_defs(trad: list[str], priority: bool) -> list[dict[str, Any]]:
    """One-change arms. `priority` skips optional cut0.20 / days16 / days60."""
    arms: list[dict[str, Any]] = [
        {
            "id": "control",
            "label": "Control (exit=10000, flush=0, cut=0.25)",
            "family": "control",
            "role": "control",
            "symbols": trad,
            "extra_v": [],
            "live": False,
            "reuse": "control",
        },
        {
            "id": "days40",
            "label": "Time-stop 40d after +29%",
            "family": "time_stop",
            "role": "candidate",
            "symbols": trad,
            "extra_v": ["rl_exit_days=40"],
            "live": False,
            "reuse": "days40",
            "priority": True,
        },
        {
            "id": "flush21",
            "label": "Flush 21d underwater",
            "family": "flush",
            "role": "candidate",
            "symbols": trad,
            "extra_v": ["rl_flush_days=21"],
            "live": True,
            "priority": True,
        },
        {
            "id": "flush42",
            "label": "Flush 42d underwater (classic)",
            "family": "flush",
            "role": "candidate",
            "symbols": trad,
            "extra_v": ["rl_flush_days=42"],
            "live": True,
            "priority": True,
        },
        {
            "id": "flush63",
            "label": "Flush 63d underwater",
            "family": "flush",
            "role": "candidate",
            "symbols": trad,
            "extra_v": ["rl_flush_days=63"],
            "live": True,
            "priority": True,
        },
        {
            "id": "cut015",
            "label": "Cut-the-losers 0.15 (tighter entry)",
            "family": "cut",
            "role": "candidate",
            "symbols": trad,
            "extra_v": ["rl_cut_the_losers=0.15"],
            "live": True,
            "priority": True,
        },
        {
            "id": "cut020",
            "label": "Cut-the-losers 0.20",
            "family": "cut",
            "role": "candidate",
            "symbols": trad,
            "extra_v": ["rl_cut_the_losers=0.20"],
            "live": True,
            "priority": False,
        },
        {
            "id": "cut035",
            "label": "Cut-the-losers 0.35 (looser entry)",
            "family": "cut",
            "role": "candidate",
            "symbols": trad,
            "extra_v": ["rl_cut_the_losers=0.35"],
            "live": True,
            "priority": True,
        },
        {
            "id": "cut_off",
            "label": "Cut-the-losers OFF (1000)",
            "family": "cut",
            "role": "candidate",
            "symbols": trad,
            "extra_v": ["rl_cut_the_losers=1000"],
            "live": True,
            "priority": True,
        },
    ]
    if priority:
        return [a for a in arms if a["id"] == CONTROL_ID or a.get("priority", True)]
    return arms


ARM_ORDER = {
    "control": 0,
    "days40": 1,
    "flush21": 10,
    "flush42": 11,
    "flush63": 12,
    "cut015": 20,
    "cut020": 21,
    "cut035": 22,
    "cut_off": 23,
}


def build_cmd(py: str, outdir: Path, workers: int, symbols: str, extra_v: list[str]) -> list[str]:
    cmd = _lists_build_cmd(py, outdir, workers, symbols)
    for v in extra_v:
        cmd.extend(["-v", v])
    return cmd


def _copy_artifacts(src: Path, dest: Path, stamp: str) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for pattern in (
        f"RL_Closed_{stamp}.csv",
        f"RL_Summary_{stamp}.csv",
        f"RL_EquityMeta_{stamp}.csv",
        f"RL_Report_{stamp}.csv",
    ):
        f = src / pattern
        if f.is_file():
            shutil.copy2(f, dest / f.name)


def copy_reuse(arm: dict[str, Any]) -> dict[str, Any]:
    kind = arm.get("reuse")
    if kind == "control":
        src, stamp = CONTROL_SRC, CONTROL_STAMP
    elif kind == "days40":
        src, stamp = DAYS40_SRC, DAYS40_STAMP
    else:
        return {"arm": arm, "ok": False, "skipped": True, "trades": [], "stamp": "", "closed": None}

    closed = src / f"RL_Closed_{stamp}.csv"
    if not closed.is_file():
        return {"arm": arm, "ok": False, "skipped": True, "trades": [], "stamp": stamp, "closed": None}

    dest = OUT_DIR / "runs" / arm["id"]
    _copy_artifacts(src, dest, stamp)
    trades = load_trades(closed)
    dest_closed = dest / closed.name
    return {
        "arm": arm,
        "ok": len(trades) > 0,
        "skipped": True,
        "closed": dest_closed if dest_closed.is_file() else closed,
        "trades": trades,
        "stamp": stamp,
        "summary": _find_latest(dest, "RL_Summary_*.csv") or (src / f"RL_Summary_{stamp}.csv"),
        "equity_meta": _find_latest(dest, "RL_EquityMeta_*.csv") or (src / f"RL_EquityMeta_{stamp}.csv"),
        "report": _find_latest(dest, "RL_Report_*.csv") or (src / f"RL_Report_{stamp}.csv"),
        "elapsed_s": 0.0,
        "reused_from": str(closed),
    }


def run_live(py: str, arm: dict[str, Any], workers: int, skip_existing: bool) -> dict[str, Any]:
    arm_dir = OUT_DIR / "runs" / arm["id"]
    arm_dir.mkdir(parents=True, exist_ok=True)
    closed = _find_latest(arm_dir, "RL_Closed_*.csv")
    if skip_existing and closed and closed.stat().st_size > 0:
        trades = load_trades(closed)
        if trades:
            return {
                "arm": arm,
                "ok": True,
                "skipped": True,
                "closed": closed,
                "trades": trades,
                "stamp": closed.stem.split("_")[-1],
                "summary": _find_latest(arm_dir, "RL_Summary_*.csv"),
                "equity_meta": _find_latest(arm_dir, "RL_EquityMeta_*.csv"),
                "report": _find_latest(arm_dir, "RL_Report_*.csv"),
                "elapsed_s": 0.0,
            }
    cmd = build_cmd(py, arm_dir, workers, ",".join(arm["symbols"]), arm.get("extra_v") or [])
    log_path = arm_dir / "run.log"
    t0 = time.time()
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write("CMD: " + " ".join(cmd) + "\n\n")
        log.flush()
        proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(ROOT))
    closed = _find_latest(arm_dir, "RL_Closed_*.csv")
    trades = load_trades(closed) if closed else []
    return {
        "arm": arm,
        "ok": proc.returncode == 0 and len(trades) > 0,
        "skipped": False,
        "closed": closed,
        "trades": trades,
        "stamp": closed.stem.split("_")[-1] if closed else "",
        "elapsed_s": time.time() - t0,
        "exit_code": proc.returncode,
        "summary": _find_latest(arm_dir, "RL_Summary_*.csv"),
        "equity_meta": _find_latest(arm_dir, "RL_EquityMeta_*.csv"),
        "report": _find_latest(arm_dir, "RL_Report_*.csv"),
    }


def _md_split(p: dict[str, Any], key: str) -> str:
    m = p[key]
    return (
        f"N={m['n']} WR={m['wr']:.1f}% Avg={m['avg_pnl']:.2f}% WO_MAX={m['wo_max']:.2f}% "
        f"PF={m['pf']:.2f} AnnROR={fmt_n(m['ann_ror'], 2)} MaxDD_overlay={fmt_n(m['max_dd'], 2)}"
    )


def _host_dd(p: dict[str, Any]) -> str:
    eq = p.get("eq_meta") or {}
    return fmt_n(eq.get("eq_dd"), 2)


def _exit_count(p: dict[str, Any], key: str) -> int:
    return int((p["m_full"].get("exits") or {}).get(key, 0))


def _family_verdict(
    aid: str,
    verdicts: dict[str, dict[str, tuple[str, str]]],
    packed_by: dict[str, dict[str, Any]],
) -> str:
    """Human KEEP/HOLD/DISMISS note; quality over N. Special-case days40 PO CONSIDER."""
    vis, nis = verdicts[aid]["is"]
    voos, noos = verdicts[aid]["oos"]
    p = packed_by[aid]
    ctrl = packed_by[CONTROL_ID]
    # AnnROR / host DD recycling angle (same spirit as prior 40d CONSIDER)
    ann_lift = (
        p["m_is"]["ann_ror"] - ctrl["m_is"]["ann_ror"]
        if math.isfinite(p["m_is"]["ann_ror"]) and math.isfinite(ctrl["m_is"]["ann_ror"])
        else 0.0
    )
    if aid == "days40":
        return (
            f"**`{aid}` CONSIDER** (prior PO 2026-08-28 on this Closed). House auto IS `{vis}` "
            f"({nis}); OOS `{voos}` ({noos}). AnnROR/host-DD recycling case — not adopted; "
            f"freeze still exit_days=10000. In-sample selection vs 80d on prior stamp."
        )
    if vis == "LEAN KEEP" and voos in ("LEAN KEEP", "HOLD"):
        tag = "LEAN KEEP" if voos == "LEAN KEEP" else "HOLD (OOS soft/flat)"
        return (
            f"**`{aid}` {tag}** IS `{vis}` ({nis}); OOS `{voos}` ({noos}). "
            f"Research candidate ≠ gold."
        )
    if vis == "DISMISS":
        extra = ""
        if ann_lift > 2.0:
            extra = (
                f" Note: IS AnnROR lift {ann_lift:+.1f} pts vs control — same tension as 40d "
                f"(Avg/PF down, recycling up); still DISMISS on house quality rule unless PO overrides."
            )
        return f"**`{aid}` DISMISS** IS `{vis}` ({nis}); OOS `{voos}` ({noos}).{extra}"
    return f"**`{aid}` HOLD** IS `{vis}` ({nis}); OOS `{voos}` ({noos})."


def write_compare_html(
    packed: list[dict[str, Any]],
    verdicts: dict[str, dict[str, tuple[str, str]]],
) -> Path:
    by_id = {p["arm"]["id"]: p for p in packed}
    baseline = by_id[CONTROL_ID]
    cand_ids = [p["arm"]["id"] for p in packed if p["arm"]["id"] != CONTROL_ID]
    th_cols = filter_html_compare_columns(
        [
            ("Arm", "text"),
            ("Univ N", "num"),
            ("Trades", "num"),
            ("WR%", "num"),
            ("Sheet PnL $", "num"),
            ("Total PnL $", "num"),
            ("Avg PnL%", "num"),
            ("Avg% w/o max", "num"),
            ("Avg win%", "num"),
            ("Avg loss%", "num"),
            ("PF", "num"),
            ("Ann ROR%", "num"),
            ("Max DD%", "num"),
            ("Calmar", "num"),
            ("Sharpe (full)", "num"),
            ("Expect $", "num"),
            ("Avg days", "num"),
            ("Cap days", "num"),
            ("PPCD", "num"),
            ("Lose streak", "num"),
            ("Trades/yr", "num"),
            ("Mean Paul", "num"),
            ("Mean FIT", "num"),
            ("Mean robust FIT", "num"),
            ("Max UW days", "num"),
            ("Δ Sheet $ vs ctrl", "num"),
            ("Δ Avg% vs ctrl", "num"),
            ("Δ WR vs ctrl", "num"),
            ("Δ PF vs ctrl", "num"),
            ("Δ Ann ROR vs ctrl", "num"),
            ("Δ Max DD vs ctrl", "num"),
            ("Δ Calmar vs ctrl", "num"),
            ("IS pick", "text"),
        ]
    )
    th = "".join(sortable_th(a, b) for a, b in th_cols)
    sections = []
    for split_key, title in (("m_is", "IS"), ("m_oos", "OOS (report-only)"), ("m_full", "FULL book")):
        body = "".join(compare_row(p, split_key, baseline, "", CONTROL_ID) for p in packed)
        note = (
            "Paul/FIT/Sharpe/UW from host Summary + EquityMeta. Overlay Max DD ≠ host DD."
            if split_key == "m_full"
            else "Closed overlay $47,500 / $500k. Overlay Max DD ≠ host account DD. "
            "One-change arms only — do not pick a flush×cut×time combo from this table."
        )
        sections.append(
            f'<section><h2>Exit strategies — {title}</h2>'
            f'<p class="muted">Δ vs control (exit_days=10000, flush=0, cut=0.25). '
            f"Profit gate frozen at +{HOUSE_EXIT_PERCENT:.0%}. {note} Click column headers to sort.</p>"
            f'<div class="table-wrap"><table class="sortable"><thead><tr>{th}</tr></thead>'
            f"<tbody>{body}</tbody></table></div></section>"
        )

    # Pairwise: each candidate vs control + days40 vs control already covered; add flush vs each other lightly
    pw_th = "".join(
        sortable_th(a, b)
        for a, b in filter_html_compare_columns(
            [
                ("Pair (B − A)", "text"),
                ("Δ Trades", "num"),
                ("Δ Avg%", "num"),
                ("Δ WO_MAX", "num"),
                ("Δ WR", "num"),
                ("Δ PF", "num"),
                ("Δ Sheet $", "num"),
                ("Δ Ann ROR", "num"),
                ("Δ Max DD", "num"),
            ]
        )
    )
    pairs: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for aid in cand_ids:
        pairs.append((f"{aid} − control", by_id[CONTROL_ID], by_id[aid]))
    if "days40" in by_id:
        for aid in cand_ids:
            if aid != "days40" and aid.startswith("flush"):
                pairs.append((f"{aid} − days40", by_id["days40"], by_id[aid]))
    pw_sections = []
    for split_key, title in (("m_is", "IS"), ("m_oos", "OOS"), ("m_full", "FULL")):
        rows = "".join(pairwise_delta_row(a, b, split_key, lbl) for lbl, a, b in pairs)
        pw_sections.append(
            f'<section><h2>Pairwise deltas — {title}</h2>'
            f'<p class="muted">Informative only — not a factorial bake-off. Click headers to sort.</p>'
            f'<div class="table-wrap"><table class="sortable"><thead><tr>{pw_th}</tr></thead>'
            f"<tbody>{rows}</tbody></table></div></section>"
        )

    exit_rows = []
    for p in packed:
        ex = p["m_full"]["exits"]
        tot = max(p["m_full"]["n"], 1)
        m = p["m_full"]
        exit_rows.append(
            "<tr>"
            f"<td>{html_mod.escape(p['arm']['label'])}</td>"
            f"<td>{html_mod.escape(p['arm'].get('family',''))}</td>"
            f"<td>{ex.get('TARGET', 0)} ({100*ex.get('TARGET',0)/tot:.1f}%)</td>"
            f"<td>{ex.get('STOP_LOSS', 0)} ({100*ex.get('STOP_LOSS',0)/tot:.1f}%)</td>"
            f"<td>{ex.get('RL_EXIT_DAYS', 0)}</td>"
            f"<td>{ex.get('FLUSH_EXIT', 0)}</td>"
            f"<td>{p['m_full']['n']}</td>"
            f"<td>{fmt_n(m.get('avg_days'), 1)}</td>"
            f"<td>{_host_dd(p)}</td>"
            "</tr>"
        )

    v_lis = []
    for aid in cand_ids:
        note = _family_verdict(aid, verdicts, by_id)
        v_lis.append(f"<li><strong>{html_mod.escape(aid)}</strong>: {note}</li>")

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RL exit strategies A/B — tradable {STAMP}</title>
<style>
:root {{ --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#9aa7b8; --line:#2a3545; --accent:#5b9fd4; --ctrl:#243044; }}
*{{box-sizing:border-box}}
body{{margin:0;font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.45}}
header{{padding:1.25rem 1rem 0.5rem;max-width:1400px;margin:0 auto}}
h1{{font-size:1.35rem;margin:0 0 .35rem}}
h2{{font-size:1.05rem;margin:1.25rem 0 .4rem;color:var(--accent)}}
.muted{{color:var(--muted);font-size:.92rem}}
.callout{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.75rem 1rem;margin:.75rem 0}}
main{{max-width:1400px;margin:0 auto;padding:0 1rem 2.5rem}}
section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.75rem 1rem 1rem;margin:1rem 0}}
.table-wrap{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-size:.78rem;min-width:1100px}}
th,td{{border-bottom:1px solid var(--line);padding:.35rem .4rem;text-align:right}}
th:first-child,td:first-child{{text-align:left}}
tr.ctrl-row{{background:var(--ctrl)}}
{SORTABLE_TH_CSS.replace('th.sortable-th:hover{{background:#e8e4d8}}', 'th.sortable-th:hover{{background:#2a3545}}')}
</style>
</head>
<body>
<header>
<h1>RL exit strategies — tradable 764 (one-change arms)</h1>
<p class="muted">Stamp <code>rl_exit_strategies_ab_{STAMP}</code>. Families:
time-stop (<code>rl_exit_days</code> after <code>rl_exit_percent={HOUSE_EXIT_PERCENT}</code>),
flush (<code>rl_flush_days</code>), cut-the-losers entry filter (<code>rl_cut_the_losers</code>).
Freeze: dip=1.055, expansion=1.163, stop=0.934, target=1.20, trails off.
Control: exit_days={HOUSE_EXIT_DAYS}, flush={HOUSE_FLUSH}, cut={HOUSE_CUT}.
Not gold / not DailyRun. IS = entry &lt; 2024-01-01; OOS report-only. Click column headers to sort.</p>
</header>
<main>
<div class="callout">
<strong>Design:</strong> One knob per arm vs frozen control. Do <em>not</em> combine
flush × cut × time into a single “winning” stack without labeling selection bias.
<ul>{"".join(v_lis)}</ul>
</div>
{"".join(sections)}
{"".join(pw_sections)}
<section>
<h2>Exit mix (FULL) + hold days + host Max DD</h2>
<p class="muted">Host Max DD = EquityMeta passive. Click column headers to sort.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>
{sortable_th("Arm", "text")}{sortable_th("Family", "text")}
{sortable_th("TARGET", "text")}{sortable_th("STOP_LOSS", "text")}
{sortable_th("RL_EXIT_DAYS", "num")}{sortable_th("FLUSH_EXIT", "num")}
{sortable_th("N", "num")}{sortable_th("Avg days (FULL)", "num")}
{sortable_th("Host Max DD%", "num")}
</tr></thead><tbody>{"".join(exit_rows)}</tbody></table></div>
</section>
</main>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    path = OUT_DIR / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def write_docs(packed: list[dict[str, Any]], verdicts: dict[str, dict[str, tuple[str, str]]]) -> None:
    by_id = {p["arm"]["id"]: p for p in packed}
    cand_ids = [p["arm"]["id"] for p in packed if p["arm"]["id"] != CONTROL_ID]

    freeze_lines = [
        f"# BASELINE — `rl_exit_strategies_ab_{STAMP}`",
        "",
        "**Status:** RESEARCH only. Three one-change exit/entry families vs frozen control.",
        "Not gold. Not DailyRun. Do not factorial-combine arms into a silent stack.",
        "",
        "## House freeze (identical except the single knob under test)",
        "",
        "| Knob | Control value | Notes |",
        "|------|---------------|-------|",
        "| `rl_dip_pct` | **1.055** | DailyRun / prior tradable |",
        "| `rl_expansion` | **1.163** | |",
        "| `rl_stop_pct` | **0.934** | |",
        "| `rl_target_pct` | **1.20** | |",
        "| trails | **off** (0) | |",
        f"| `rl_exit_percent` | **{HOUSE_EXIT_PERCENT}** | frozen profit gate for time-stop |",
        f"| `rl_exit_days` | **{HOUSE_EXIT_DAYS}** (off) | time-stop family changes this only |",
        f"| `rl_flush_days` | **{HOUSE_FLUSH}** (off) | flush family changes this only |",
        f"| `rl_cut_the_losers` | **{HOUSE_CUT}** | cut family changes this only; 1000 = off |",
        "| cash | **$47,500** | |",
        "",
        "## Universe / split",
        "",
        "| Field | Value |",
        "|---|---|",
        "| Universe | tradable 2010 / ADV$2m (**764**) — `VZ_tradable_2010_adv2m_universe.csv` |",
        f"| Control Closed | reuse `RL_Closed_{CONTROL_STAMP}` from `rl_tradable_2010_adv2m_20260828` |",
        f"| days40 Closed | reuse fill-fixed `RL_Closed_{DAYS40_STAMP}` from `rl_time_stop_tradable_20260828` |",
        "| Split | IS entry < 2024-01-01; OOS report-only; no OOS retune |",
        "",
        "## Arms",
        "",
        "| Arm | Family | Knob | Reused? | Stamp | N_full | Host Max DD% | OK |",
        "|-----|--------|------|---------|-------|--------|--------------|-----|",
    ]
    for p in packed:
        arm = p["arm"]
        knob = ",".join(arm.get("extra_v") or []) or "(house defaults)"
        reused = "yes" if p.get("skipped") and arm.get("reuse") else ("skip-existing" if p.get("skipped") else "live")
        freeze_lines.append(
            f"| `{arm['id']}` | {arm.get('family','')} | `{knob}` | {reused} | "
            f"`{p.get('stamp','')}` | {p['m_full']['n']} | {_host_dd(p)} | "
            f"{'yes' if p.get('ok') else 'no'} |"
        )
    freeze_lines.extend(["", "## Verdicts (vs control)", ""])
    for aid in cand_ids:
        freeze_lines.append(f"- {_family_verdict(aid, verdicts, by_id)}")
    freeze_lines.extend(
        [
            "",
            "## Selection-bias note",
            "",
            "Each family is judged separately vs control. Picking one flush level *and* one cut "
            "level *and* 40d after seeing the full table would be in-sample selection — label it "
            "if anyone stacks later. days40 was already selected on a prior stamp (vs 80d).",
            "",
        ]
    )
    (OUT_DIR / "BASELINE.md").write_text("\n".join(freeze_lines), encoding="utf-8")

    slines = [
        f"# SUMMARY — `rl_exit_strategies_ab_{STAMP}`",
        "",
        "One-change RL exit/entry A/B on tradable 764 vs control and known 40d time-stop. Research only.",
        "",
        "## Plain English",
        "",
        "- **Control** = house RL: no time-stop, no flush, cut-the-losers at 0.25.",
        "- **40d** = after a trade is +29%, clock 40 bars then exit (reused prior CONSIDER stamp).",
        "- **Flush** = portfolio underwater vs high-water mark for N days → force exit.",
        "- **Cut-the-losers** = entry filter (how extended vs SMA50); not a mid-trade kill. 1000 = off.",
        "",
        "## IS",
        "",
    ]
    for aid in [CONTROL_ID, *cand_ids]:
        slines.append(f"- **{aid}**: {_md_split(by_id[aid], 'm_is')}")
    slines.extend(["", "## OOS (report-only)", ""])
    for aid in [CONTROL_ID, *cand_ids]:
        slines.append(f"- **{aid}**: {_md_split(by_id[aid], 'm_oos')}")
    slines.extend(["", "## Host Max DD + exit rows (FULL)", ""])
    for aid in [CONTROL_ID, *cand_ids]:
        p = by_id[aid]
        slines.append(
            f"- **{aid}**: host DD={_host_dd(p)}%  "
            f"RL_EXIT_DAYS={_exit_count(p, 'RL_EXIT_DAYS')}  "
            f"FLUSH_EXIT={_exit_count(p, 'FLUSH_EXIT')}  "
            f"avg_days={fmt_n(p['m_full'].get('avg_days'), 1)}"
        )
    slines.extend(["", "## Verdicts", ""])
    for aid in cand_ids:
        slines.append(f"- {_family_verdict(aid, verdicts, by_id)}")
    slines.extend(
        [
            "",
            "## Paths",
            "",
            f"- HTML: `drive/paul_experiments/rl_exit_strategies_ab_{STAMP}/compare.html`",
            f"- BASELINE: `drive/paul_experiments/rl_exit_strategies_ab_{STAMP}/BASELINE.md`",
            "",
        ]
    )
    (OUT_DIR / "SUMMARY.md").write_text("\n".join(slines), encoding="utf-8")


def summarize(packed: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {p["arm"]["id"]: p for p in packed}
    control = by_id[CONTROL_ID]
    cand_ids = [p["arm"]["id"] for p in packed if p["arm"]["id"] != CONTROL_ID]
    verdicts = {
        aid: {
            "is": verdict_vs_control(by_id[aid], control, "m_is"),
            "oos": verdict_vs_control(by_id[aid], control, "m_oos"),
        }
        for aid in cand_ids
    }
    write_compare_html(packed, verdicts)
    write_metrics_csv(packed, "", OUT_DIR / "metrics_all.csv")
    write_docs(packed, verdicts)
    print(f"[RL-EXIT] Wrote {OUT_DIR / 'compare.html'}", flush=True)
    return {"verdicts": verdicts, "packed": packed}


def _load_arm_from_disk(arm: dict[str, Any]) -> dict[str, Any]:
    arm_dir = OUT_DIR / "runs" / arm["id"]
    if arm.get("reuse") == "control":
        src, stamp = CONTROL_SRC, CONTROL_STAMP
    elif arm.get("reuse") == "days40":
        src, stamp = DAYS40_SRC, DAYS40_STAMP
    else:
        src, stamp = arm_dir, None
    closed = None
    if stamp:
        closed = (arm_dir / f"RL_Closed_{stamp}.csv") if (arm_dir / f"RL_Closed_{stamp}.csv").is_file() else (src / f"RL_Closed_{stamp}.csv")
    if closed is None or not closed.is_file():
        closed = _find_latest(arm_dir, "RL_Closed_*.csv") or (_find_latest(src, "RL_Closed_*.csv") if src != arm_dir else None)
    if not closed or not closed.is_file():
        return {"arm": arm, "ok": False, "skipped": True, "trades": [], "stamp": ""}
    trades = load_trades(closed)
    st = closed.stem.split("_")[-1]
    return {
        "arm": arm,
        "ok": len(trades) > 0,
        "skipped": True,
        "closed": closed,
        "trades": trades,
        "stamp": st,
        "summary": _find_latest(arm_dir, "RL_Summary_*.csv") or _find_latest(src, "RL_Summary_*.csv"),
        "equity_meta": _find_latest(arm_dir, "RL_EquityMeta_*.csv") or _find_latest(src, "RL_EquityMeta_*.csv"),
        "report": _find_latest(arm_dir, "RL_Report_*.csv") or _find_latest(src, "RL_Report_*.csv"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument(
        "--priority",
        action="store_true",
        help="Run control+40d+flush{21,42,63}+cut{0.15,0.35,1000} only (skip cut0.20)",
    )
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument(
        "--only",
        type=str,
        default="",
        help="Comma-separated arm ids to run/summarize (still needs control for compare)",
    )
    args = parser.parse_args()
    skip_existing = args.skip_existing or args.summarize_only

    trad = load_universe_symbols(UNIVERSE_CSV)
    if not trad:
        print("[RL-EXIT] Missing tradable universe", flush=True)
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    arms = _arm_defs(trad, priority=args.priority)
    if args.only.strip():
        want = {x.strip() for x in args.only.split(",") if x.strip()}
        want.add(CONTROL_ID)
        arms = [a for a in arms if a["id"] in want]

    py = _resolve_python()
    runs: list[dict[str, Any]] = []

    if args.summarize_only:
        for arm in arms:
            run = _load_arm_from_disk(arm)
            print(f"[RL-EXIT] load {arm['id']} ok={run['ok']} n={len(run.get('trades') or [])}", flush=True)
            runs.append(run)
    else:
        reuse_arms = [a for a in arms if a.get("reuse")]
        live_arms = [a for a in arms if a.get("live")]
        for arm in reuse_arms:
            run = copy_reuse(arm)
            print(
                f"[RL-EXIT] reuse {arm['id']} ok={run['ok']} n={len(run.get('trades') or [])} "
                f"stamp={run.get('stamp')} from={run.get('reused_from')}",
                flush=True,
            )
            runs.append(run)
        if live_arms:
            with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
                futs = {ex.submit(run_live, py, arm, args.workers, skip_existing): arm for arm in live_arms}
                for fut in as_completed(futs):
                    arm = futs[fut]
                    run = fut.result()
                    print(
                        f"[RL-EXIT] {arm['id']} ok={run['ok']} n={len(run['trades'])} "
                        f"elapsed={run.get('elapsed_s', 0):.0f}s skipped={run.get('skipped')} "
                        f"exit={run.get('exit_code')}",
                        flush=True,
                    )
                    runs.append(run)

    runs.sort(key=lambda r: ARM_ORDER.get(r["arm"]["id"], 99))
    if not all(r.get("ok") for r in runs):
        print("[RL-EXIT] One or more arms failed", flush=True)
        for r in runs:
            print(f"  {r['arm']['id']}: ok={r.get('ok')} exit={r.get('exit_code')}", flush=True)
        # Still summarize whatever succeeded if control ok
        ok_runs = [r for r in runs if r.get("ok")]
        if not any(r["arm"]["id"] == CONTROL_ID for r in ok_runs) or len(ok_runs) < 2:
            return 1
        runs = ok_runs

    packed = [pack_result(r) for r in runs]
    result = summarize(packed)

    ntfy = ROOT / "tools" / "ntfy_job_done.py"
    if ntfy.is_file():
        bits = []
        for aid, v in result["verdicts"].items():
            bits.append(f"{aid} IS {v['is'][0]}")
        subprocess.run(
            [
                py,
                str(ntfy),
                "--path",
                str(OUT_DIR / "compare.html"),
                "-t",
                "RL exit strategies AB",
                "-m",
                " · ".join(bits[:6]) + (f" (+{len(bits)-6} more)" if len(bits) > 6 else ""),
            ],
            cwd=str(ROOT),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
