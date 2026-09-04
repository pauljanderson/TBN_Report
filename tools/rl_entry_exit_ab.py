#!/usr/bin/env python3
"""RL entry-MTM exit A/B vs Paul 40d@29% control (tradable 764).

Hypothesis family: change `rl_exit_percent` / `rl_exit_days` (and for V8/V9
stacked knobs) while keeping SMA50 × 1.20 target live. Profit gates are **% above
entry** (high MTM), not vs SMA50.

Control freeze (from rl_cutoff_40d_control_20260831 — do not change other knobs):
  cut=1000 (OFF), exit_days=40, exit_percent=0.29, dip=1.055, expansion=1.163,
  stop=0.934, target=1.20, too_high=0, flush=0, trails off.

Arms:
  control      — reuse Closed 260831202006
  cut_off_only — context; reuse 260831200847 (no time stop)
  hard_40      — +40% entry MTM, days=1 (same-bar hard exit; days=0 equiv)
  40_30d       — +40% then 30d gate
  V5           — +30% / 60d
  V6           — +32% / 14d
  V7           — +27% / 14d
  V8           — stacked: V7 + rl_entry_target_pct=0.29 (entry×1.29 races SMA target)
  V9           — stacked: V8 + rl_stop_pct=0.95 (tighter stop)

Engine: curr_profit_pct = (high − entry) / entry. V8 uses new rl_entry_target_pct
hook (EXIT_TYPE=ENTRY_TARGET). V8/V9 are stacked — selection bias labeled; no
single-knob KEEP claim for V9.

IS = entry < 2024-01-01; OOS report-only. Research-only. Not DailyRun.

Usage:
  python tools/rl_entry_exit_ab.py
  python tools/rl_entry_exit_ab.py --summarize-only
  python tools/rl_entry_exit_ab.py --skip-existing --jobs 2 --workers 12
"""
from __future__ import annotations

import argparse
import html as html_mod
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
OUT_DIR = DRIVE / "paul_experiments" / f"rl_entry_exit_ab_{STAMP}"
UNIVERSE_CSV = DRIVE / "universes" / "VZ_tradable_2010_adv2m_universe.csv"

CONTROL_SRC = (
    DRIVE / "paul_experiments" / f"rl_cutoff_40d_control_{STAMP}" / "runs" / "new_control"
)
CONTROL_STAMP = "260831202006"
CUT_OFF_SRC = (
    DRIVE / "paul_experiments" / f"rl_cutoff_40d_control_{STAMP}" / "runs" / "cut_off"
)
CUT_OFF_STAMP = "260831200847"

CONTROL_ID = "control"
HOUSE_CUT = 1000
HOUSE_STOP = 0.934
HOUSE_EXIT_PCT = 0.29
HOUSE_EXIT_DAYS = 40
V9_STOP = 0.95  # tighter vs house 0.934 (~5% below signal low)

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


def _base_v(exit_pct: float, exit_days: int, **extra: Any) -> list[str]:
    out = [
        f"rl_cut_the_losers={HOUSE_CUT}",
        f"rl_exit_percent={exit_pct}",
        f"rl_exit_days={exit_days}",
    ]
    for k, v in extra.items():
        out.append(f"{k}={v}")
    return out


def _arm_defs(trad: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "id": CONTROL_ID,
            "label": "Control 40d@29% (Paul freeze)",
            "role": "control",
            "family": "control",
            "stacked": False,
            "symbols": trad,
            "extra_v": _base_v(HOUSE_EXIT_PCT, HOUSE_EXIT_DAYS),
            "live": False,
            "reuse": "control",
            "exit_pct": HOUSE_EXIT_PCT,
            "exit_days": HOUSE_EXIT_DAYS,
            "entry_tgt": 0.0,
            "stop": HOUSE_STOP,
        },
        {
            "id": "cut_off_only",
            "label": "Cut OFF only (no time stop)",
            "role": "context",
            "family": "context",
            "stacked": False,
            "symbols": trad,
            "extra_v": _base_v(HOUSE_EXIT_PCT, 10000),
            "live": False,
            "reuse": "cut_off",
            "exit_pct": HOUSE_EXIT_PCT,
            "exit_days": 10000,
            "entry_tgt": 0.0,
            "stop": HOUSE_STOP,
        },
        {
            "id": "hard_40",
            "label": "hard_40 (+40% same-bar, days=1)",
            "role": "candidate",
            "family": "exit_gate",
            "stacked": False,
            "symbols": trad,
            "extra_v": _base_v(0.40, 1),
            "live": True,
            "exit_pct": 0.40,
            "exit_days": 1,
            "entry_tgt": 0.0,
            "stop": HOUSE_STOP,
            "note": "days=1 → same-bar hard exit (time_counter hits 1 on gate bar; days=0 equivalent)",
        },
        {
            "id": "40_30d",
            "label": "40_30d (+40% then 30d)",
            "role": "candidate",
            "family": "exit_gate",
            "stacked": False,
            "symbols": trad,
            "extra_v": _base_v(0.40, 30),
            "live": True,
            "exit_pct": 0.40,
            "exit_days": 30,
            "entry_tgt": 0.0,
            "stop": HOUSE_STOP,
        },
        {
            "id": "V5",
            "label": "V5 (+30% / 60d)",
            "role": "candidate",
            "family": "exit_gate",
            "stacked": False,
            "symbols": trad,
            "extra_v": _base_v(0.30, 60),
            "live": True,
            "exit_pct": 0.30,
            "exit_days": 60,
            "entry_tgt": 0.0,
            "stop": HOUSE_STOP,
        },
        {
            "id": "V6",
            "label": "V6 (+32% / 14d)",
            "role": "candidate",
            "family": "exit_gate",
            "stacked": False,
            "symbols": trad,
            "extra_v": _base_v(0.32, 14),
            "live": True,
            "exit_pct": 0.32,
            "exit_days": 14,
            "entry_tgt": 0.0,
            "stop": HOUSE_STOP,
        },
        {
            "id": "V7",
            "label": "V7 (+27% / 14d)",
            "role": "candidate",
            "family": "exit_gate",
            "stacked": False,
            "symbols": trad,
            "extra_v": _base_v(0.27, 14),
            "live": True,
            "exit_pct": 0.27,
            "exit_days": 14,
            "entry_tgt": 0.0,
            "stop": HOUSE_STOP,
        },
        {
            "id": "V8",
            "label": "V8 stacked (V7 + entry tgt +29%)",
            "role": "candidate",
            "family": "stacked",
            "stacked": True,
            "symbols": trad,
            "extra_v": _base_v(0.27, 14, rl_entry_target_pct=0.29),
            "live": True,
            "exit_pct": 0.27,
            "exit_days": 14,
            "entry_tgt": 0.29,
            "stop": HOUSE_STOP,
            "note": "True dual-target: SMA50×1.20 + entry×1.29 via rl_entry_target_pct (not approximation)",
        },
        {
            "id": "V9",
            "label": f"V9 stacked (V8 + stop={V9_STOP})",
            "role": "candidate",
            "family": "stacked",
            "stacked": True,
            "symbols": trad,
            "extra_v": _base_v(0.27, 14, rl_entry_target_pct=0.29, rl_stop_pct=V9_STOP),
            "live": True,
            "exit_pct": 0.27,
            "exit_days": 14,
            "entry_tgt": 0.29,
            "stop": V9_STOP,
            "note": f"Stacked: V8 + tighter stop {HOUSE_STOP}→{V9_STOP}; selection bias — no single-knob KEEP",
        },
    ]


ARM_ORDER = {
    CONTROL_ID: 0,
    "cut_off_only": 1,
    "hard_40": 2,
    "40_30d": 3,
    "V5": 4,
    "V6": 5,
    "V7": 6,
    "V8": 7,
    "V9": 8,
}


def build_cmd(py: str, outdir: Path, workers: int, symbols: str, extra_v: list[str]) -> list[str]:
    cmd = _lists_build_cmd(py, outdir, workers, symbols)
    strip_prefixes = (
        "rl_cut_the_losers=",
        "rl_exit_percent=",
        "rl_exit_days=",
        "rl_entry_target_pct=",
        "rl_stop_pct=",
    )
    out: list[str] = []
    i = 0
    while i < len(cmd):
        if cmd[i] == "-v" and i + 1 < len(cmd) and any(
            cmd[i + 1].startswith(p) for p in strip_prefixes
        ):
            i += 2
            continue
        out.append(cmd[i])
        i += 1
    # Always re-emit house stop unless arm overrides via extra_v
    if not any(v.startswith("rl_stop_pct=") for v in extra_v):
        out.extend(["-v", f"rl_stop_pct={HOUSE_STOP}"])
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
    if kind == "control":
        src, stamp = CONTROL_SRC, CONTROL_STAMP
    elif kind == "cut_off":
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
        f"Calmar={fmt_n(m.get('calmar'), 2)}"
    )


def _host_dd(p: dict[str, Any]) -> str:
    eq = p.get("eq_meta") or {}
    return fmt_n(eq.get("eq_dd"), 2)


def _exit_count(p: dict[str, Any], key: str) -> int:
    return int((p["m_full"].get("exits") or {}).get(key, 0))


def _plain_english(
    packed: list[dict[str, Any]],
    verdicts: dict[str, dict[str, tuple[str, str]]],
) -> str:
    by_id = {p["arm"]["id"]: p for p in packed}
    ctrl = by_id[CONTROL_ID]
    lines = [
        "Profit thresholds are **% above entry** (high MTM). SMA50×1.20 target stays live; "
        "whichever fires first wins (stop, SMA target, entry target, or timed exit).",
        "",
        f"**Control** = Paul freeze: cut OFF + 40d after +{HOUSE_EXIT_PCT:.0%} entry MTM "
        f"(reuse `{CONTROL_STAMP}`). IS Avg {ctrl['m_is']['avg_pnl']:.2f}%, "
        f"AnnROR {fmt_n(ctrl['m_is']['ann_ror'], 1)}, host DD {_host_dd(ctrl)}%.",
        "",
        "### One-family arms (exit_percent / exit_days only)",
        "",
    ]
    for aid in ("hard_40", "40_30d", "V5", "V6", "V7"):
        if aid not in by_id:
            continue
        p = by_id[aid]
        vis, nis = verdicts.get(aid, {}).get("is", ("?", ""))
        voos, noos = verdicts.get(aid, {}).get("oos", ("?", ""))
        lines.append(
            f"- **{aid}**: IS `{vis}` ({nis}); OOS `{voos}` ({noos}). "
            f"FULL Avg {p['m_full']['avg_pnl']:.2f}% AnnROR {fmt_n(p['m_full']['ann_ror'], 1)} "
            f"RL_EXIT={_exit_count(p, 'RL_EXIT_DAYS')} avg_days={p['m_full'].get('avg_days', 0):.1f}."
        )
    lines.extend(["", "### Stacked (selection bias — not single-knob KEEP)", ""])
    for aid in ("V8", "V9"):
        if aid not in by_id:
            continue
        p = by_id[aid]
        vis, nis = verdicts.get(aid, {}).get("is", ("?", ""))
        voos, noos = verdicts.get(aid, {}).get("oos", ("?", ""))
        et = _exit_count(p, "ENTRY_TARGET")
        lines.append(
            f"- **{aid}**: IS `{vis}` ({nis}); OOS `{voos}` ({noos}). "
            f"ENTRY_TARGET rows={et}; RL_EXIT={_exit_count(p, 'RL_EXIT_DAYS')}; "
            f"stop={p['arm'].get('stop')}. Stacked — research context only."
        )
    if "cut_off_only" in by_id:
        co = by_id["cut_off_only"]
        lines.extend(
            [
                "",
                f"**cut_off_only** context (no time stop): FULL Avg {co['m_full']['avg_pnl']:.2f}% "
                f"AnnROR {fmt_n(co['m_full']['ann_ror'], 1)} host DD {_host_dd(co)}%.",
            ]
        )
    lines.extend(
        [
            "",
            "**V8 implementation:** real `rl_entry_target_pct=0.29` hook — full exit when "
            "high ≥ entry×1.29, racing SMA50×1.20 (exit type `ENTRY_TARGET`). Not an approximation.",
            f"**V9 implementation:** V8 + `rl_stop_pct={V9_STOP}` (house {HOUSE_STOP} → tighter).",
            "",
            "Research-only — not gold, not DailyRun.",
        ]
    )
    return "\n".join(lines)


def write_compare_html(
    packed: list[dict[str, Any]],
    verdicts: dict[str, dict[str, tuple[str, str]]],
) -> Path:
    by_id = {p["arm"]["id"]: p for p in packed}
    baseline = by_id[CONTROL_ID]
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
            ("RL_EXIT_DAYS", "num"),
            ("Δ Avg% vs ctrl", "num"),
            ("Δ WR vs ctrl", "num"),
            ("Δ PF vs ctrl", "num"),
            ("Δ Ann ROR vs ctrl", "num"),
            ("Δ Max DD vs ctrl", "num"),
            ("Δ Calmar vs ctrl", "num"),
        ]
    )
    th = "".join(sortable_th(a, b) for a, b in th_cols)
    sections = []
    for split_key, title in (("m_is", "IS"), ("m_oos", "OOS (report-only)"), ("m_full", "FULL book")):
        body = ""
        for p in packed:
            row = compare_row(p, split_key, baseline, "", CONTROL_ID)
            if p["arm"].get("stacked") and p["arm"]["id"] != CONTROL_ID:
                row = row.replace('<tr class="">', '<tr class="stacked">', 1)
            body += row
        note = (
            "Δ vs Paul control (40d@29%, cut OFF). Stacked arms shaded. Click headers to sort."
            if split_key != "m_full"
            else "Paul/FIT/Sharpe from host. Overlay Max DD ≠ host DD."
        )
        sections.append(
            f'<section><h2>Entry-MTM exit AB — {title}</h2>'
            f'<p class="muted">{note}</p>'
            f'<div class="table-wrap"><table class="sortable"><thead><tr>{th}</tr></thead>'
            f"<tbody>{body}</tbody></table></div></section>"
        )

    # Verdict table
    v_th = "".join(
        sortable_th(a, b)
        for a, b in [
            ("Arm", "text"),
            ("Family", "text"),
            ("IS verdict", "text"),
            ("IS note", "text"),
            ("OOS verdict", "text"),
            ("OOS note", "text"),
        ]
    )
    v_rows = []
    for p in packed:
        aid = p["arm"]["id"]
        if aid in (CONTROL_ID, "cut_off_only"):
            continue
        vis, nis = verdicts.get(aid, {}).get("is", ("", ""))
        voos, noos = verdicts.get(aid, {}).get("oos", ("", ""))
        fam = "stacked" if p["arm"].get("stacked") else "exit_gate"
        v_rows.append(
            "<tr>"
            f"<td>{html_mod.escape(p['arm']['label'])}</td>"
            f"<td>{fam}</td>"
            f"<td>{html_mod.escape(vis)}</td>"
            f"<td>{html_mod.escape(nis)}</td>"
            f"<td>{html_mod.escape(voos)}</td>"
            f"<td>{html_mod.escape(noos)}</td>"
            "</tr>"
        )

    freeze_rows = []
    for p in packed:
        arm = p["arm"]
        freeze_rows.append(
            "<tr>"
            f"<td>{html_mod.escape(arm['label'])}</td>"
            f"<td>{arm.get('exit_pct')}</td>"
            f"<td>{arm.get('exit_days')}</td>"
            f"<td>{arm.get('entry_tgt') or '—'}</td>"
            f"<td>{arm.get('stop')}</td>"
            f"<td>{'stacked' if arm.get('stacked') else arm.get('family')}</td>"
            f"<td>{p.get('stamp', '')}</td>"
            f"<td>{p['m_full']['n']}</td>"
            f"<td>{_exit_count(p, 'RL_EXIT_DAYS')}</td>"
            f"<td>{_exit_count(p, 'ENTRY_TARGET')}</td>"
            f"<td>{_exit_count(p, 'TARGET')}</td>"
            f"<td>{_host_dd(p)}</td>"
            f"<td>{p['m_full'].get('avg_days', 0):.1f}</td>"
            "</tr>"
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
    pairs = []
    for aid in ("hard_40", "40_30d", "V5", "V6", "V7", "V8", "V9"):
        if aid in by_id:
            pairs.append((f"{aid} − control", baseline, by_id[aid]))
    if "cut_off_only" in by_id:
        pairs.append(("control − cut_off_only", by_id["cut_off_only"], baseline))
    pw_sections = []
    for split_key, title in (("m_is", "IS"), ("m_oos", "OOS"), ("m_full", "FULL")):
        rows = "".join(pairwise_delta_row(a, b, split_key, lbl) for lbl, a, b in pairs)
        pw_sections.append(
            f'<section><h2>Pairwise deltas — {title}</h2>'
            f'<p class="muted">Click headers to sort.</p>'
            f'<div class="table-wrap"><table class="sortable"><thead><tr>{pw_th}</tr></thead>'
            f"<tbody>{rows}</tbody></table></div></section>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RL entry-MTM exit AB — {STAMP}</title>
<style>
:root {{ --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#9aa7b8; --line:#2a3545; --accent:#5b9fd4; --ctrl:#243044; --stack:#2a2438; }}
*{{box-sizing:border-box}}
body{{margin:0;font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.45}}
header{{padding:1.25rem 1rem 0.5rem;max-width:1500px;margin:0 auto}}
h1{{font-size:1.35rem;margin:0 0 .35rem}}
h2{{font-size:1.05rem;margin:1.25rem 0 .4rem;color:var(--accent)}}
.muted{{color:var(--muted);font-size:.92rem}}
.callout{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.75rem 1rem;margin:.75rem 0}}
main{{max-width:1500px;margin:0 auto;padding:0 1rem 2.5rem}}
.table-wrap{{overflow-x:auto;border:1px solid var(--line);border-radius:8px}}
table{{width:100%;border-collapse:collapse;font-size:.88rem}}
th,td{{padding:.45rem .55rem;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}}
th:first-child,td:first-child{{text-align:left}}
thead th{{background:var(--card);position:sticky;top:0;cursor:pointer}}
tr.ctrl-row td{{background:var(--ctrl);font-weight:600}}
tr.stacked td{{background:var(--stack)}}
{SORTABLE_TH_CSS}
</style></head><body>
<header>
<h1>RL entry-MTM exit AB vs Paul 40d@29% control</h1>
<p class="muted">Stamp <code>rl_entry_exit_ab_{STAMP}</code>. Tradable 764. IS entry &lt; 2024-01-01. Profit gates = %% above entry (not SMA50).</p>
<div class="callout">
<strong>Control</strong>: cut OFF + <code>rl_exit_days=40</code> after <code>rl_exit_percent={HOUSE_EXIT_PCT}</code>
(entry MTM). House dip=1.055, expansion=1.163, stop={HOUSE_STOP}, SMA target=1.20, trails/flush/too_high off.
Reuse Closed <code>{CONTROL_STAMP}</code>.
</div>
<div class="callout">
<strong>V8</strong>: true <code>rl_entry_target_pct=0.29</code> (exit type ENTRY_TARGET) + V7 timed gate; races SMA×1.20.
<strong>V9</strong>: V8 + stop {V9_STOP} (stacked — selection bias).
</div>
</header>
<main>
<section><h2>Freeze table</h2>
<p class="muted">Click column headers to sort.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>
{sortable_th("Arm", "text")}{sortable_th("exit_pct", "num")}{sortable_th("exit_days", "num")}
{sortable_th("entry_tgt", "num")}{sortable_th("stop", "num")}{sortable_th("Family", "text")}
{sortable_th("Stamp", "text")}{sortable_th("N full", "num")}
{sortable_th("RL_EXIT", "num")}{sortable_th("ENTRY_TGT", "num")}{sortable_th("SMA TARGET", "num")}
{sortable_th("Host Max DD%", "num")}{sortable_th("Avg days", "num")}
</tr></thead><tbody>{"".join(freeze_rows)}</tbody></table></div></section>
<section><h2>Verdicts vs control</h2>
<div class="table-wrap"><table class="sortable"><thead><tr>{v_th}</tr></thead>
<tbody>{"".join(v_rows)}</tbody></table></div></section>
{"".join(sections)}
{"".join(pw_sections)}
</main>
{SORTABLE_TABLE_SCRIPT}
</body></html>"""
    path = OUT_DIR / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def write_docs(
    packed: list[dict[str, Any]],
    verdicts: dict[str, dict[str, tuple[str, str]]],
) -> None:
    by_id = {p["arm"]["id"]: p for p in packed}
    freeze_lines = [
        f"# BASELINE — `rl_entry_exit_ab_{STAMP}`",
        "",
        "**Status:** RESEARCH — entry-MTM exit AB vs Paul 40d@29% control. Not gold. Not DailyRun.",
        "",
        "## Engine: profit gate is vs entry (MTM)",
        "",
        "Verified in `rocket_rl.py`:",
        "",
        "```text",
        "curr_profit_pct = (high − entry_price) / entry_price",
        "has_hit_time when curr_profit_pct >= rl_exit_percent",
        "RL_EXIT_DAYS when time_counter >= rl_exit_days",
        "```",
        "",
        "Control 40d@29% is already **entry MTM**, not vs SMA50. SMA50×`rl_target_pct` remains a separate TARGET.",
        "",
        "Hard immediate exit: on the bar that first hits the gate, `time_counter` becomes 1, so",
        "`rl_exit_days=1` (and `=0`) both fire same-bar. This stamp uses **days=1** for `hard_40`.",
        "",
        "## Paul control freeze (unchanged house knobs)",
        "",
        "| Knob | Value | Notes |",
        "|------|-------|-------|",
        f"| `rl_cut_the_losers` | **{HOUSE_CUT}** | OFF |",
        f"| `rl_exit_days` | **{HOUSE_EXIT_DAYS}** | after profit gate |",
        f"| `rl_exit_percent` | **{HOUSE_EXIT_PCT}** | % above **entry** |",
        "| `rl_dip_pct` | **1.055** | |",
        "| `rl_expansion` | **1.163** | |",
        f"| `rl_stop_pct` | **{HOUSE_STOP}** | V9 only → {V9_STOP} |",
        "| `rl_target_pct` | **1.20** | SMA50 envelope — stays live all arms |",
        "| `rl_entry_target_pct` | **0** (off) | V8/V9 → 0.29 |",
        "| trails / flush / too_high | **off** | |",
        "| cash | **$47,500** | |",
        "| Universe | tradable 764 | |",
        "| Split | IS entry < 2024-01-01; OOS report-only | |",
        "",
        "## Arms",
        "",
        "| Arm | exit_pct | exit_days | entry_tgt | stop | Family | Source |",
        "|-----|----------|-----------|-----------|------|--------|--------|",
        f"| `control` | {HOUSE_EXIT_PCT} | {HOUSE_EXIT_DAYS} | 0 | {HOUSE_STOP} | control | reuse `{CONTROL_STAMP}` |",
        f"| `cut_off_only` | {HOUSE_EXIT_PCT} | 10000 | 0 | {HOUSE_STOP} | context | reuse `{CUT_OFF_STAMP}` |",
        "| `hard_40` | 0.40 | 1 | 0 | 0.934 | one-change | live |",
        "| `40_30d` | 0.40 | 30 | 0 | 0.934 | one-change | live |",
        "| `V5` | 0.30 | 60 | 0 | 0.934 | one-change | live |",
        "| `V6` | 0.32 | 14 | 0 | 0.934 | one-change | live |",
        "| `V7` | 0.27 | 14 | 0 | 0.934 | one-change | live |",
        "| `V8` | 0.27 | 14 | **0.29** | 0.934 | **stacked** | live — true entry target hook |",
        f"| `V9` | 0.27 | 14 | **0.29** | **{V9_STOP}** | **stacked** | live — V8 + tighter stop |",
        "",
        "## V8 / V9 implementation honesty",
        "",
        "- **V8:** Implemented `rl_entry_target_pct` on `RLConfig` / `BRTConfig` and exit race in",
        "  `rocket_rl.py`. Exit type `ENTRY_TARGET` when high ≥ entry×1.29; races SMA TARGET and",
        "  timed RL_EXIT_DAYS (lowest hit price wins same bar). **Not** an exit_percent approximation.",
        f"- **V9:** V8 + `rl_stop_pct={V9_STOP}` (house {HOUSE_STOP} → less room below signal low).",
        "  Stacked — do **not** claim single-knob KEEP for V9.",
        "",
        "## Run results",
        "",
        "| Arm | Stamp | N_full | RL_EXIT | ENTRY_TGT | SMA TARGET | Host DD% | Avg days | OK |",
        "|-----|-------|--------|---------|-----------|------------|----------|----------|-----|",
    ]
    for p in packed:
        arm = p["arm"]
        freeze_lines.append(
            f"| `{arm['id']}` | `{p.get('stamp', '')}` | {p['m_full']['n']} | "
            f"{_exit_count(p, 'RL_EXIT_DAYS')} | {_exit_count(p, 'ENTRY_TARGET')} | "
            f"{_exit_count(p, 'TARGET')} | {_host_dd(p)} | "
            f"{p['m_full'].get('avg_days', 0):.1f} | {'yes' if p.get('ok') else 'no'} |"
        )
    freeze_lines.extend(
        [
            "",
            "## Verdicts vs control (IS quality; OOS report-only)",
            "",
        ]
    )
    for aid in ("hard_40", "40_30d", "V5", "V6", "V7", "V8", "V9"):
        if aid not in verdicts:
            continue
        vis, nis = verdicts[aid]["is"]
        voos, noos = verdicts[aid]["oos"]
        tag = " STACKED" if by_id.get(aid, {}).get("arm", {}).get("stacked") else ""
        freeze_lines.append(f"- `{aid}`{tag}: IS `{vis}` ({nis}); OOS `{voos}` ({noos})")
    freeze_lines.extend(
        [
            "",
            "## Selection-bias note",
            "",
            "V5–V7 are one-family (exit_percent/days). V8/V9 are stacked on V7; picking among",
            "the table after seeing results is in-sample selection. OOS is report-only — do not retune.",
            "",
        ]
    )
    (OUT_DIR / "BASELINE.md").write_text("\n".join(freeze_lines), encoding="utf-8")

    slines = [
        f"# SUMMARY — `rl_entry_exit_ab_{STAMP}`",
        "",
        "Entry-MTM exit AB vs Paul 40d@29% control on tradable 764. Research only.",
        "",
        "## Plain English (Paul)",
        "",
        _plain_english(packed, verdicts),
        "",
        "## FULL",
        "",
    ]
    for p in packed:
        slines.append(f"- **{p['arm']['id']}**: {_md_split(p, 'm_full')}")
    slines.extend(["", "## IS", ""])
    for p in packed:
        slines.append(f"- **{p['arm']['id']}**: {_md_split(p, 'm_is')}")
    slines.extend(["", "## OOS (report-only)", ""])
    for p in packed:
        slines.append(f"- **{p['arm']['id']}**: {_md_split(p, 'm_oos')}")
    slines.extend(["", "## Exit mix (FULL)", ""])
    for p in packed:
        ex = p["m_full"].get("exits") or {}
        slines.append(
            f"- **{p['arm']['id']}**: RL_EXIT={ex.get('RL_EXIT_DAYS', 0)} "
            f"ENTRY_TGT={ex.get('ENTRY_TARGET', 0)} TARGET={ex.get('TARGET', 0)} "
            f"STOP={ex.get('STOP_LOSS', 0)} GAP={ex.get('GAP_DOWN', 0)} "
            f"hostDD={_host_dd(p)}% avg_days={p['m_full'].get('avg_days', 0):.1f}"
        )
    slines.extend(
        [
            "",
            "## Paths",
            "",
            f"- HTML: `drive/paul_experiments/rl_entry_exit_ab_{STAMP}/compare.html`",
            f"- BASELINE: `drive/paul_experiments/rl_entry_exit_ab_{STAMP}/BASELINE.md`",
            f"- Tool: `tools/rl_entry_exit_ab.py`",
            "",
        ]
    )
    (OUT_DIR / "SUMMARY.md").write_text("\n".join(slines), encoding="utf-8")


def summarize(packed: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {p["arm"]["id"]: p for p in packed}
    ctrl = by_id[CONTROL_ID]
    verdicts: dict[str, dict[str, tuple[str, str]]] = {}
    for p in packed:
        aid = p["arm"]["id"]
        if aid in (CONTROL_ID, "cut_off_only"):
            continue
        verdicts[aid] = {
            "is": verdict_vs_control(p, ctrl, "m_is"),
            "oos": verdict_vs_control(p, ctrl, "m_oos"),
        }
    write_compare_html(packed, verdicts)
    write_metrics_csv(packed, "", OUT_DIR / "metrics_all.csv")
    write_docs(packed, verdicts)
    print(f"[RL-EE] Wrote {OUT_DIR / 'compare.html'}", flush=True)
    return {"verdicts": verdicts, "packed": packed}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument(
        "--arms",
        type=str,
        default="",
        help="Comma-separated arm ids to run (default: all)",
    )
    args = parser.parse_args()
    skip_existing = args.skip_existing or args.summarize_only

    trad = load_universe_symbols(UNIVERSE_CSV)
    if not trad:
        print("[RL-EE] Missing tradable universe", flush=True)
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    arms = _arm_defs(trad)
    if args.arms.strip():
        want = {a.strip() for a in args.arms.split(",") if a.strip()}
        arms = [a for a in arms if a["id"] in want or a["id"] == CONTROL_ID]
    py = _resolve_python()
    runs: list[dict[str, Any]] = []

    if args.summarize_only:
        for arm in arms:
            run = _load_arm_from_disk(arm)
            print(f"[RL-EE] load {arm['id']} ok={run['ok']} n={len(run.get('trades') or [])}", flush=True)
            runs.append(run)
    else:
        reuse_arms = [a for a in arms if not a.get("live")]
        live_arms = [a for a in arms if a.get("live")]
        for arm in reuse_arms:
            run = copy_reuse(arm)
            print(
                f"[RL-EE] {arm['id']} ok={run['ok']} n={len(run.get('trades') or [])} "
                f"reused stamp={run.get('stamp', '')}",
                flush=True,
            )
            runs.append(run)

        if live_arms:
            with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
                futs = {
                    ex.submit(run_live, py, arm, args.workers, skip_existing): arm
                    for arm in live_arms
                }
                for fut in as_completed(futs):
                    arm = futs[fut]
                    run = fut.result()
                    print(
                        f"[RL-EE] {arm['id']} ok={run['ok']} n={len(run.get('trades') or [])} "
                        f"elapsed={run.get('elapsed_s', 0):.0f}s skipped={run.get('skipped')} "
                        f"stamp={run.get('stamp', '')}",
                        flush=True,
                    )
                    runs.append(run)

    runs.sort(key=lambda r: ARM_ORDER.get(r["arm"]["id"], 99))
    ok_runs = [r for r in runs if r.get("ok")]
    if not any(r["arm"]["id"] == CONTROL_ID for r in ok_runs):
        print("[RL-EE] Control missing", flush=True)
        return 1
    if len(ok_runs) < 2:
        print("[RL-EE] Too few arms", flush=True)
        return 1

    packed = [pack_result(r) for r in ok_runs]
    result = summarize(packed)

    ntfy = ROOT / "tools" / "ntfy_job_done.py"
    if ntfy.is_file():
        # Short verdict digest for phone
        bits = []
        for aid in ("hard_40", "V5", "V6", "V7", "V8", "V9"):
            if aid in result["verdicts"]:
                bits.append(f"{aid}={result['verdicts'][aid]['is'][0]}")
        subprocess.run(
            [
                py,
                str(ntfy),
                "--path",
                str(OUT_DIR / "compare.html"),
                "-t",
                "RL entry-MTM exit AB",
                "-m",
                "vs 40d@29%: " + "; ".join(bits) if bits else "compare ready",
            ],
            cwd=str(ROOT),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
