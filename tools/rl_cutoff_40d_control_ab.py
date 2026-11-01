#!/usr/bin/env python3
"""Paul control freeze: cut-the-losers OFF + 40d time-stop on tradable 764.

New control (Paul ask):
  rl_cut_the_losers=1000 (OFF), rl_exit_days=40, house rl_exit_percent=0.29 frozen.

Compare vs:
  1. cut OFF only (no time stop) — reuse exit_strategies cut_off if present
  2. old house (cut=0.25, exit_days=10000) — reuse RL_Closed_260828112205

Prior fill-fixed 40d Closed (260828184602) had cut=0.25 — must re-run for cut OFF.

IS = entry < 2024-01-01; OOS report-only. Research-only. Not DailyRun.

Usage:
  python tools/rl_cutoff_40d_control_ab.py
  python tools/rl_cutoff_40d_control_ab.py --summarize-only
  python tools/rl_cutoff_40d_control_ab.py --skip-existing --workers 12
"""
from __future__ import annotations

import argparse
import html as html_mod
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
STAMP = "20260831"
OUT_DIR = DRIVE / "paul_experiments" / f"rl_cutoff_40d_control_{STAMP}"
UNIVERSE_CSV = DRIVE / "universes" / "VZ_tradable_2010_adv2m_universe.csv"

# Reuse sources
OLD_HOUSE_SRC = (
    DRIVE / "paul_experiments" / "rl_tradable_2010_adv2m_20260828" / "runs" / "tradable"
)
OLD_HOUSE_STAMP = "260828112205"
CUT_OFF_SRC = (
    DRIVE / "paul_experiments" / "rl_exit_strategies_ab_20260831" / "runs" / "cut_off"
)
CUT_OFF_STAMP = "260831182637"
TOO_HIGH_CTRL_SRC = DRIVE / "paul_experiments" / f"rl_too_high_ab_{STAMP}" / "runs" / "control"

NEW_CONTROL_ID = "new_control"
DELTA_BASELINE_ID = "cut_off"  # Δ vs cut OFF only (40d is the only diff)

HOUSE_STOP = 0.934
HOUSE_EXIT_PERCENT = 0.29
HOUSE_CUT_OFF = 1000
HOUSE_CUT_ON = 0.25
HOUSE_EXIT_DAYS_OFF = 10000

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

ARM_ORDER = {NEW_CONTROL_ID: 0, "cut_off": 1, "old_house": 2}


def _arm_defs(trad: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "id": NEW_CONTROL_ID,
            "label": "Paul control (cut OFF + 40d)",
            "role": "control",
            "symbols": trad,
            "extra_v": [f"rl_cut_the_losers={HOUSE_CUT_OFF}", "rl_exit_days=40"],
            "live": True,
        },
        {
            "id": "cut_off",
            "label": "Cut OFF only (no time stop)",
            "role": "baseline",
            "symbols": trad,
            "extra_v": [f"rl_cut_the_losers={HOUSE_CUT_OFF}"],
            "live": False,
            "reuse": "cut_off",
        },
        {
            "id": "old_house",
            "label": f"Old house (cut={HOUSE_CUT_ON}, exit={HOUSE_EXIT_DAYS_OFF})",
            "role": "context",
            "symbols": trad,
            "extra_v": [],
            "live": False,
            "reuse": "old_house",
        },
    ]


def build_cmd(py: str, outdir: Path, workers: int, symbols: str, extra_v: list[str]) -> list[str]:
    cmd = _lists_build_cmd(py, outdir, workers, symbols)
    out: list[str] = []
    i = 0
    while i < len(cmd):
        if cmd[i] == "-v" and i + 1 < len(cmd) and (
            cmd[i + 1].startswith("rl_cut_the_losers=") or cmd[i + 1].startswith("rl_exit_days=")
        ):
            i += 2
            continue
        out.append(cmd[i])
        i += 1
    for v in extra_v:
        out.extend(["-v", v])
    return out


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
    if kind == "old_house":
        src, stamp = OLD_HOUSE_SRC, OLD_HOUSE_STAMP
    elif kind == "cut_off":
        # Prefer rl_too_high_ab control (same freeze) if present
        th_closed = _find_latest(TOO_HIGH_CTRL_SRC, "RL_Closed_*.csv") if TOO_HIGH_CTRL_SRC.is_dir() else None
        if th_closed and th_closed.is_file() and th_closed.stat().st_size > 0:
            src = TOO_HIGH_CTRL_SRC
            stamp = th_closed.stem.split("_")[-1]
        else:
            src, stamp = CUT_OFF_SRC, CUT_OFF_STAMP
    else:
        return {"arm": arm, "ok": False, "skipped": True, "trades": [], "stamp": "", "closed": None}

    closed = src / f"RL_Closed_{stamp}.csv"
    if not closed.is_file():
        closed = _find_latest(src, "RL_Closed_*.csv")
    if not closed or not closed.is_file():
        return {"arm": arm, "ok": False, "skipped": True, "trades": [], "stamp": "", "closed": None}

    stamp = closed.stem.split("_")[-1]
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


def _load_arm_from_disk(arm: dict[str, Any]) -> dict[str, Any]:
    arm_dir = OUT_DIR / "runs" / arm["id"]
    closed = _find_latest(arm_dir, "RL_Closed_*.csv")
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
        "summary": _find_latest(arm_dir, "RL_Summary_*.csv"),
        "equity_meta": _find_latest(arm_dir, "RL_EquityMeta_*.csv"),
        "report": _find_latest(arm_dir, "RL_Report_*.csv"),
    }


def _md_split(p: dict[str, Any], key: str) -> str:
    m = p[key]
    return (
        f"N={m['n']} WR={m['wr']:.1f}% Avg={m['avg_pnl']:.2f}% WO_MAX={m['wo_max']:.2f}% "
        f"PF={m['pf']:.2f} AnnROR={fmt_n(m['ann_ror'], 2)} MaxDD_overlay={fmt_n(m['max_dd'], 2)} "
        f"Calmar={fmt_n(m.get('calmar'), 2)} Sharpe={fmt_n(m.get('sharpe'), 2)}"
    )


def _host_dd(p: dict[str, Any]) -> str:
    eq = p.get("eq_meta") or {}
    return fmt_n(eq.get("eq_dd"), 2)


def _exit_count(p: dict[str, Any], key: str) -> int:
    return int((p["m_full"].get("exits") or {}).get(key, 0))


def _plain_english(packed: list[dict[str, Any]], verdicts: dict[str, dict[str, tuple[str, str]]]) -> str:
    by_id = {p["arm"]["id"]: p for p in packed}
    nc = by_id[NEW_CONTROL_ID]
    co = by_id["cut_off"]
    oh = by_id["old_house"]
    vis, nis = verdicts.get("new_control_vs_cut_off", {}).get("is", ("", ""))
    voos, noos = verdicts.get("new_control_vs_cut_off", {}).get("oos", ("", ""))

    ann_is = nc["m_is"]["ann_ror"] - co["m_is"]["ann_ror"]
    dd_is = nc["m_is"]["max_dd"] - co["m_is"]["max_dd"]
    avg_is = nc["m_is"]["avg_pnl"] - co["m_is"]["avg_pnl"]

    lines = [
        f"**Paul's proposed control** = cut-the-losers OFF (`1000`) + **40d time-stop** after "
        f"+{HOUSE_EXIT_PERCENT:.0%} profit gate (`rl_exit_percent={HOUSE_EXIT_PERCENT}`). "
        f"House dip/expansion/stop/target unchanged; trails off; too_high off.",
        "",
        f"vs **cut OFF only** (no time stop): IS AnnROR {ann_is:+.1f} pts, overlay Max DD "
        f"{dd_is:+.1f} pts, Avg% {avg_is:+.2f} — same recycling trade-off as prior 40d stamp "
        f"(faster turns, lower per-trade Avg%, higher AnnROR / lower DD). Verdict IS `{vis}` "
        f"({nis}); OOS `{voos}` ({noos}).",
        "",
        f"vs **old house** (cut={HOUSE_CUT_ON}, no time stop): cut OFF alone is flat (prior "
        f"exit_strategies HOLD); the **40d** knob drives the book change. Old house IS Avg "
        f"{oh['m_is']['avg_pnl']:.2f}% vs new control {nc['m_is']['avg_pnl']:.2f}%.",
        "",
        "Research candidate for future A/Bs — not gold, not DailyRun wired.",
    ]
    return "\n".join(lines)


def write_compare_html(
    packed: list[dict[str, Any]],
    verdicts: dict[str, dict[str, tuple[str, str]]],
) -> Path:
    by_id = {p["arm"]["id"]: p for p in packed}
    delta_base = by_id[DELTA_BASELINE_ID]
    th_cols = filter_html_compare_columns(
        [
            ("Arm", "text"),
            ("Univ N", "num"),
            ("Trades", "num"),
            ("WR%", "num"),
            ("Avg PnL%", "num"),
            ("Avg% w/o max", "num"),
            ("Avg win%", "num"),
            ("Avg loss%", "num"),
            ("PF", "num"),
            ("Ann ROR%", "num"),
            ("Max DD%", "num"),
            ("Calmar", "num"),
            ("Sharpe", "num"),
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
            ("RL_EXIT_DAYS", "num"),
            ("Δ Avg% vs cut OFF", "num"),
            ("Δ WR vs cut OFF", "num"),
            ("Δ PF vs cut OFF", "num"),
            ("Δ Ann ROR vs cut OFF", "num"),
            ("Δ Max DD vs cut OFF", "num"),
            ("Δ Calmar vs cut OFF", "num"),
        ]
    )
    th = "".join(sortable_th(a, b) for a, b in th_cols)
    sections = []
    for split_key, title in (("m_is", "IS"), ("m_oos", "OOS (report-only)"), ("m_full", "FULL book")):
        body = ""
        for p in packed:
            row = compare_row(p, split_key, delta_base, "", DELTA_BASELINE_ID)
            if p["arm"]["id"] == NEW_CONTROL_ID:
                row = row.replace("<tr>", '<tr class="ctrl-row">', 1)
            body += row
        note = (
            "Δ vs cut OFF only (no time stop). Paul control row highlighted."
            if split_key != "m_full"
            else "Paul/FIT/Sharpe from host. Overlay Max DD ≠ host DD."
        )
        sections.append(
            f'<section><h2>Cut OFF + 40d control — {title}</h2>'
            f'<p class="muted">{note} Click column headers to sort.</p>'
            f'<div class="table-wrap"><table class="sortable"><thead><tr>{th}</tr></thead>'
            f"<tbody>{body}</tbody></table></div></section>"
        )

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
                ("Δ Ann ROR", "num"),
                ("Δ Max DD", "num"),
            ]
        )
    )
    pairs = [
        ("new_control − cut OFF", delta_base, by_id[NEW_CONTROL_ID]),
        ("new_control − old house", by_id["old_house"], by_id[NEW_CONTROL_ID]),
        ("cut OFF − old house", by_id["old_house"], by_id["cut_off"]),
    ]
    pw_sections = []
    for split_key, title in (("m_is", "IS"), ("m_oos", "OOS"), ("m_full", "FULL")):
        rows = "".join(pairwise_delta_row(a, b, split_key, lbl) for lbl, a, b in pairs)
        pw_sections.append(
            f'<section><h2>Pairwise deltas — {title}</h2>'
            f'<p class="muted">Click headers to sort.</p>'
            f'<div class="table-wrap"><table class="sortable"><thead><tr>{pw_th}</tr></thead>'
            f"<tbody>{rows}</tbody></table></div></section>"
        )

    freeze_rows = []
    for p in packed:
        arm = p["arm"]
        cut = HOUSE_CUT_OFF if arm["id"] != "old_house" else HOUSE_CUT_ON
        exd = 40 if arm["id"] == NEW_CONTROL_ID else HOUSE_EXIT_DAYS_OFF
        freeze_rows.append(
            "<tr>"
            f"<td>{html_mod.escape(arm['label'])}</td>"
            f"<td>{cut}</td>"
            f"<td>{exd}</td>"
            f"<td>{HOUSE_EXIT_PERCENT}</td>"
            f"<td>{p.get('stamp', '')}</td>"
            f"<td>{p['m_full']['n']}</td>"
            f"<td>{_exit_count(p, 'RL_EXIT_DAYS')}</td>"
            f"<td>{_host_dd(p)}</td>"
            f"<td>{p['m_full'].get('avg_days', 0):.1f}</td>"
            "</tr>"
        )

    v = verdicts.get("new_control_vs_cut_off", {})
    vis, nis = v.get("is", ("", ""))
    voos, noos = v.get("oos", ("", ""))

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RL cut OFF + 40d control — tradable {STAMP}</title>
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
.table-wrap{{overflow-x:auto;border:1px solid var(--line);border-radius:8px}}
table{{width:100%;border-collapse:collapse;font-size:.88rem}}
th,td{{padding:.45rem .55rem;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}}
th:first-child,td:first-child{{text-align:left}}
thead th{{background:var(--card);position:sticky;top:0;cursor:pointer}}
tr.ctrl-row td{{background:var(--ctrl);font-weight:600}}
{SORTABLE_TH_CSS}
</style></head><body>
<header>
<h1>RL control freeze — cut OFF + 40d time-stop</h1>
<p class="muted">Stamp <code>rl_cutoff_40d_control_{STAMP}</code>. Tradable 764. IS entry &lt; 2024-01-01.</p>
<div class="callout">
<strong>Paul control</strong>: <code>rl_cut_the_losers=1000</code> (OFF) + <code>rl_exit_days=40</code>
after <code>rl_exit_percent={HOUSE_EXIT_PERCENT}</code> profit gate. House dip=1.055, expansion=1.163,
stop={HOUSE_STOP}, target=1.20, trails off, flush off, too_high=0.
Prior 40d Closed <code>260828184602</code> had cut=0.25 — re-run required.
</div>
<div class="callout">
<strong>40d vs cut OFF</strong>: IS verdict <code>{vis}</code> ({nis}); OOS <code>{voos}</code> ({noos}).
Research-only — not DailyRun.
</div>
</header>
<main>
<section><h2>Freeze table</h2>
<div class="table-wrap"><table class="sortable"><thead><tr>
{sortable_th("Arm", "text")}{sortable_th("cut_the_losers", "num")}{sortable_th("exit_days", "num")}
{sortable_th("exit_percent", "num")}{sortable_th("Stamp", "text")}{sortable_th("N full", "num")}
{sortable_th("RL_EXIT rows", "num")}{sortable_th("Host Max DD%", "num")}{sortable_th("Avg days", "num")}
</tr></thead><tbody>{"".join(freeze_rows)}</tbody></table></div></section>
{"".join(sections)}
{"".join(pw_sections)}
</main>
{SORTABLE_TABLE_SCRIPT}
</body></html>"""
    path = OUT_DIR / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def write_docs(packed: list[dict[str, Any]], verdicts: dict[str, dict[str, tuple[str, str]]]) -> None:
    by_id = {p["arm"]["id"]: p for p in packed}
    v = verdicts.get("new_control_vs_cut_off", {})
    vis, nis = v.get("is", ("", ""))
    voos, noos = v.get("oos", ("", ""))

    freeze_lines = [
        f"# BASELINE — `rl_cutoff_40d_control_{STAMP}`",
        "",
        "**Status:** RESEARCH — Paul's proposed control freeze (cut OFF + 40d). Not gold. Not DailyRun.",
        "",
        "## Paul control (new freeze)",
        "",
        "| Knob | Value | Notes |",
        "|------|-------|-------|",
        f"| `rl_cut_the_losers` | **{HOUSE_CUT_OFF}** | OFF — Paul drop cut |",
        "| `rl_exit_days` | **40** | after profit gate |",
        f"| `rl_exit_percent` | **{HOUSE_EXIT_PERCENT}** | engine default; profit gate for timed exit |",
        "| `rl_dip_pct` | **1.055** | |",
        "| `rl_expansion` | **1.163** | |",
        f"| `rl_stop_pct` | **{HOUSE_STOP}** | |",
        "| `rl_target_pct` | **1.20** | |",
        "| trails | **off** | |",
        "| `rl_flush_days` | **0** (off) | |",
        "| `rl_too_high` | **0** (off) | |",
        "| cash | **$47,500** | |",
        "",
        "## Baselines compared",
        "",
        "| Arm | cut | exit_days | Source |",
        "|-----|-----|-----------|--------|",
        f"| `new_control` | {HOUSE_CUT_OFF} | 40 | **live rerun** (prior 40d had cut=0.25) |",
        f"| `cut_off` | {HOUSE_CUT_OFF} | {HOUSE_EXIT_DAYS_OFF} | reuse exit_strategies `260831182637` or too_high control |",
        f"| `old_house` | {HOUSE_CUT_ON} | {HOUSE_EXIT_DAYS_OFF} | reuse `RL_Closed_{OLD_HOUSE_STAMP}` |",
        "",
        "## Universe / split",
        "",
        "| Field | Value |",
        "|---|---|",
        "| Universe | tradable 2010 / ADV$2m (**764**) |",
        "| Split | IS entry < 2024-01-01; OOS report-only; no OOS retune |",
        "",
        "## Arms",
        "",
        "| Arm | Stamp | N_full | RL_EXIT rows | Host Max DD% | Avg days | OK |",
        "|-----|-------|--------|--------------|--------------|----------|-----|",
    ]
    for p in packed:
        arm = p["arm"]
        freeze_lines.append(
            f"| `{arm['id']}` | `{p.get('stamp', '')}` | {p['m_full']['n']} | "
            f"{_exit_count(p, 'RL_EXIT_DAYS')} | {_host_dd(p)} | "
            f"{p['m_full'].get('avg_days', 0):.1f} | {'yes' if p.get('ok') else 'no'} |"
        )
    freeze_lines.extend(
        [
            "",
            "## Verdict (new_control vs cut OFF only)",
            "",
            f"- IS `{vis}` ({nis})",
            f"- OOS `{voos}` ({noos})",
            "",
            "## Selection-bias note",
            "",
            "40d was CONSIDER on prior stamp with cut=0.25. This stamp re-freezes cut OFF per Paul",
            "and re-runs 40d — do not retune from OOS.",
            "",
        ]
    )
    (OUT_DIR / "BASELINE.md").write_text("\n".join(freeze_lines), encoding="utf-8")

    slines = [
        f"# SUMMARY — `rl_cutoff_40d_control_{STAMP}`",
        "",
        "Paul control: cut-the-losers OFF + 40d time-stop on tradable 764. Research only.",
        "",
        "## Plain English (Paul)",
        "",
        _plain_english(packed, verdicts),
        "",
        "## FULL",
        "",
    ]
    for aid in [NEW_CONTROL_ID, "cut_off", "old_house"]:
        slines.append(f"- **{aid}**: {_md_split(by_id[aid], 'm_full')}")
    slines.extend(["", "## IS", ""])
    for aid in [NEW_CONTROL_ID, "cut_off", "old_house"]:
        slines.append(f"- **{aid}**: {_md_split(by_id[aid], 'm_is')}")
    slines.extend(["", "## OOS (report-only)", ""])
    for aid in [NEW_CONTROL_ID, "cut_off", "old_house"]:
        slines.append(f"- **{aid}**: {_md_split(by_id[aid], 'm_oos')}")
    slines.extend(
        [
            "",
            "## Exit mix (FULL)",
            "",
        ]
    )
    for aid in [NEW_CONTROL_ID, "cut_off", "old_house"]:
        ex = by_id[aid]["m_full"].get("exits") or {}
        slines.append(
            f"- **{aid}**: RL_EXIT_DAYS={ex.get('RL_EXIT_DAYS', 0)} "
            f"TARGET={ex.get('TARGET', 0)} STOP={ex.get('STOP_LOSS', 0)} "
            f"host DD={_host_dd(by_id[aid])}% avg_days={by_id[aid]['m_full'].get('avg_days', 0):.1f}"
        )
    slines.extend(
        [
            "",
            "## Paths",
            "",
            f"- HTML: `drive/paul_experiments/rl_cutoff_40d_control_{STAMP}/compare.html`",
            f"- BASELINE: `drive/paul_experiments/rl_cutoff_40d_control_{STAMP}/BASELINE.md`",
            "",
        ]
    )
    (OUT_DIR / "SUMMARY.md").write_text("\n".join(slines), encoding="utf-8")


def summarize(packed: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {p["arm"]["id"]: p for p in packed}
    cut_off = by_id[DELTA_BASELINE_ID]
    new_ctrl = by_id[NEW_CONTROL_ID]
    verdicts = {
        "new_control_vs_cut_off": {
            "is": verdict_vs_control(new_ctrl, cut_off, "m_is"),
            "oos": verdict_vs_control(new_ctrl, cut_off, "m_oos"),
        },
    }
    write_compare_html(packed, verdicts)
    write_metrics_csv(packed, "", OUT_DIR / "metrics_all.csv")
    write_docs(packed, verdicts)
    print(f"[RL-C40] Wrote {OUT_DIR / 'compare.html'}", flush=True)
    return {"verdicts": verdicts, "packed": packed}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    skip_existing = args.skip_existing or args.summarize_only

    trad = load_universe_symbols(UNIVERSE_CSV)
    if not trad:
        print("[RL-C40] Missing tradable universe", flush=True)
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    arms = _arm_defs(trad)
    py = _resolve_python()
    runs: list[dict[str, Any]] = []

    if args.summarize_only:
        for arm in arms:
            run = _load_arm_from_disk(arm)
            print(f"[RL-C40] load {arm['id']} ok={run['ok']} n={len(run.get('trades') or [])}", flush=True)
            runs.append(run)
    else:
        for arm in arms:
            if arm.get("live"):
                run = run_live(py, arm, args.workers, skip_existing)
            else:
                run = copy_reuse(arm)
            print(
                f"[RL-C40] {arm['id']} ok={run['ok']} n={len(run.get('trades') or [])} "
                f"elapsed={run.get('elapsed_s', 0):.0f}s skipped={run.get('skipped')} "
                f"stamp={run.get('stamp', '')}",
                flush=True,
            )
            runs.append(run)

    runs.sort(key=lambda r: ARM_ORDER.get(r["arm"]["id"], 99))
    if not all(r.get("ok") for r in runs):
        ok_runs = [r for r in runs if r.get("ok")]
        if len(ok_runs) < 2 or not any(r["arm"]["id"] == NEW_CONTROL_ID for r in ok_runs):
            print("[RL-C40] Required arms missing", flush=True)
            for r in runs:
                print(f"  {r['arm']['id']}: ok={r.get('ok')}", flush=True)
            return 1
        runs = ok_runs

    packed = [pack_result(r) for r in runs]
    result = summarize(packed)

    ntfy = ROOT / "tools" / "ntfy_job_done.py"
    if ntfy.is_file():
        v = result["verdicts"]["new_control_vs_cut_off"]
        subprocess.run(
            [
                py,
                str(ntfy),
                "--path",
                str(OUT_DIR / "compare.html"),
                "-t",
                "RL cut OFF + 40d control",
                "-m",
                f"Paul control IS {v['is'][0]} OOS {v['oos'][0]} · cut OFF + 40d vs cut OFF only",
            ],
            cwd=str(ROOT),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
