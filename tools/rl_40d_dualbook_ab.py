#!/usr/bin/env python3
"""Dual-book 40d time-stop vs control: Core 764 + Expanded soft-history (~973).

Freeze (same as rl_cutoff_40d_control_20260831):
  Control: rl_cut_the_losers=1000 (OFF) + rl_exit_days=10000 (time stop OFF)
  40d:     cut OFF + rl_exit_days=40, rl_exit_percent=0.29 (engine default)
  House:   dip 1.055, expansion 1.163, stop 0.934, target 1.20,
           too_high/flush/trails off

Expanded universe: core ∪ soft first-bar ≤2021-08-31 + $5/ADV$2m as-of 2023-12-29
  (includes CRWD/APP/ZM class; ~973). Design: rl_newer_univ_isoos_design_20260831.

IS = entry < 2024-01-01; OOS report-only. Research-only. Not DailyRun.

Usage:
  python tools/rl_40d_dualbook_ab.py
  python tools/rl_40d_dualbook_ab.py --summarize-only
  python tools/rl_40d_dualbook_ab.py --skip-existing --workers 12
  python tools/rl_40d_dualbook_ab.py --build-univ-only
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import math
import shutil
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
STAMP = "20260831"
OUT_DIR = DRIVE / "paul_experiments" / f"rl_40d_dualbook_{STAMP}"
CORE_CSV = DRIVE / "universes" / "VZ_tradable_2010_adv2m_universe.csv"
EXPANDED_CSV = DRIVE / "universes" / "VZ_tradable_soft20210831_adv2m_universe.csv"
MEMBERSHIP_CSV = (
    DRIVE / "paul_experiments" / "rl_newer_univ_isoos_design_20260831" / "membership_counts.csv"
)
SOFT_GATE_LABEL = "first<=2021-08-31_5y_before_end"
SOFT_FIRST_MAX = date(2021, 8, 31)
IS_CUT = date(2024, 1, 1)

# Exact-match reuse from Paul control stamp (764, same freeze)
CORE_CTRL_SRC = (
    DRIVE / "paul_experiments" / f"rl_cutoff_40d_control_{STAMP}" / "runs" / "cut_off"
)
CORE_CTRL_STAMP = "260831200847"
CORE_40D_SRC = (
    DRIVE / "paul_experiments" / f"rl_cutoff_40d_control_{STAMP}" / "runs" / "new_control"
)
CORE_40D_STAMP = "260831202006"

HOUSE_STOP = 0.934
HOUSE_EXIT_PERCENT = 0.29
HOUSE_CUT_OFF = 1000
HOUSE_EXIT_DAYS_OFF = 10000
HOUSE_EXIT_DAYS_40 = 40

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
    verdict_vs_control,
    write_metrics_csv,
    _find_latest,
    _resolve_python,
)
from vz_is_paul_universe_ab import load_universe_symbols  # noqa: E402

BOOKS = ("core", "expanded")
ARM_ORDER = {
    "core_control": 0,
    "core_40d": 1,
    "expanded_control": 2,
    "expanded_40d": 3,
}


def _parse_d(s: object) -> Optional[date]:
    t = str(s or "").strip()[:10]
    if not t:
        return None
    try:
        return datetime.strptime(t, "%Y-%m-%d").date()
    except ValueError:
        return None


def build_expanded_universe() -> dict[str, Any]:
    """Core 764 ∪ soft ≤2021-08-31 liquid extras from design membership CSV."""
    core = load_universe_symbols(CORE_CSV)
    if not core:
        raise SystemExit(f"Missing core universe: {CORE_CSV}")
    if not MEMBERSHIP_CSV.is_file():
        raise SystemExit(f"Missing membership CSV: {MEMBERSHIP_CSV}")

    extras: list[dict[str, str]] = []
    with MEMBERSHIP_CSV.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("gate") != SOFT_GATE_LABEL:
                continue
            sym = str(row.get("SYMBOL") or "").strip().upper()
            if not sym or sym in core:
                continue
            extras.append(
                {
                    "SYMBOL": sym,
                    "first_bar": str(row.get("first_bar") or ""),
                    "asof_close": str(row.get("asof_close") or ""),
                    "adv20_usd": str(row.get("adv20_usd") or ""),
                    "sleeve": "soft_extra",
                }
            )
    extras.sort(key=lambda r: r["SYMBOL"])
    expanded = sorted(set(core) | {e["SYMBOL"] for e in extras})

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    EXPANDED_CSV.parent.mkdir(parents=True, exist_ok=True)
    header_lines = [
        "# VZ tradable EXPANDED soft-history — RESEARCH (not gold / not DailyRun)",
        f"# Soft first_bar <= {SOFT_FIRST_MAX.isoformat()} + Close>=$5 + ADV$2m as-of 2023-12-29",
        f"# = core 2010 tradable ({len(core)}) ∪ soft extras ({len(extras)}) → {len(expanded)}",
        "# Gate chosen to include CRWD/APP/ZM class (2018 soft ~923 excludes those IPOs).",
        "# Design: drive/paul_experiments/rl_newer_univ_isoos_design_20260831/",
        "SYMBOL",
    ]
    body = "\n".join(header_lines + expanded) + "\n"
    EXPANDED_CSV.write_text(body, encoding="utf-8")
    stamp_csv = OUT_DIR / "VZ_tradable_soft20210831_adv2m_universe.csv"
    stamp_csv.write_text(body, encoding="utf-8")

    # Membership detail for stamp
    meta_path = OUT_DIR / "expanded_membership.csv"
    with meta_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["SYMBOL", "sleeve", "first_bar", "asof_close", "adv20_usd", "has_is_history"],
        )
        w.writeheader()
        for s in core:
            w.writerow(
                {
                    "SYMBOL": s,
                    "sleeve": "core_2010",
                    "first_bar": "",
                    "asof_close": "",
                    "adv20_usd": "",
                    "has_is_history": "Y",
                }
            )
        no_is = 0
        for e in extras:
            fb = _parse_d(e["first_bar"])
            has_is = "Y" if fb is not None and fb < IS_CUT else "N"
            if has_is == "N":
                no_is += 1
            w.writerow({**e, "has_is_history": has_is})

    notes = OUT_DIR / "universe_notes.md"
    notes.write_text(
        "\n".join(
            [
                f"# Expanded universe — `rl_40d_dualbook_{STAMP}`",
                "",
                f"- Soft gate: first bar ≤ **{SOFT_FIRST_MAX.isoformat()}** + $5 / ADV$2m as-of 2023-12-29",
                f"- Core N = **{len(core)}** (`VZ_tradable_2010_adv2m_universe.csv`)",
                f"- Soft extras N = **{len(extras)}** (from design `{SOFT_GATE_LABEL}`)",
                f"- Expanded N = **{len(expanded)}**",
                f"- Path: `{EXPANDED_CSV.as_posix()}`",
                f"- Stamp copy: `{stamp_csv.as_posix()}`",
                "",
                "## Why not ≤2018-12-29 (~923)?",
                "",
                "Design ~923 soft sleeve **excludes** CRWD / APP / ZM (IPOs 2019–2021).",
                "Paul/PO ask for those class names → freeze **≤2021-08-31** (~973).",
                "",
                "## IS history",
                "",
                f"Primary IS cut: entry < {IS_CUT.isoformat()}. Soft extras with first_bar ≥ IS cut: "
                f"**{no_is}** (expect 0). Newer listings still have shorter pre-IS tapes — "
                "document, do not invent fake IS depth.",
                "",
                "Example soft extras: CRWD, APP, ZM, DOCN, HUBS, SHOP, PANW, VEEV, NTRA, LMND.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return {
        "core": core,
        "extras": extras,
        "expanded": expanded,
        "no_is_extras": no_is,
        "path": EXPANDED_CSV,
    }


def _arm_defs(core: list[str], expanded: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "id": "core_control",
            "label": "Core control (cut OFF, no TS)",
            "book": "core",
            "role": "control",
            "symbols": core,
            "extra_v": [f"rl_cut_the_losers={HOUSE_CUT_OFF}"],
            "live": False,
            "reuse": "core_control",
        },
        {
            "id": "core_40d",
            "label": "Core 40d (cut OFF + 40d)",
            "book": "core",
            "role": "candidate",
            "symbols": core,
            "extra_v": [f"rl_cut_the_losers={HOUSE_CUT_OFF}", f"rl_exit_days={HOUSE_EXIT_DAYS_40}"],
            "live": False,
            "reuse": "core_40d",
        },
        {
            "id": "expanded_control",
            "label": "Expanded control (cut OFF, no TS)",
            "book": "expanded",
            "role": "control",
            "symbols": expanded,
            "extra_v": [f"rl_cut_the_losers={HOUSE_CUT_OFF}"],
            "live": True,
        },
        {
            "id": "expanded_40d",
            "label": "Expanded 40d (cut OFF + 40d)",
            "book": "expanded",
            "role": "candidate",
            "symbols": expanded,
            "extra_v": [f"rl_cut_the_losers={HOUSE_CUT_OFF}", f"rl_exit_days={HOUSE_EXIT_DAYS_40}"],
            "live": True,
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
        f"RL_EquityCurve_{stamp}.csv",
        f"RL_EquityCurve_Regular_{stamp}.csv",
    ):
        f = src / pattern
        if f.is_file():
            shutil.copy2(f, dest / f.name)


def copy_reuse(arm: dict[str, Any]) -> dict[str, Any]:
    kind = arm.get("reuse")
    if kind == "core_control":
        src, stamp = CORE_CTRL_SRC, CORE_CTRL_STAMP
    elif kind == "core_40d":
        src, stamp = CORE_40D_SRC, CORE_40D_STAMP
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


def _exit_count(p: dict[str, Any], key: str) -> int:
    return int((p["m_full"].get("exits") or {}).get(key, 0))


def _host_dd(p: dict[str, Any]) -> str:
    eq = p.get("eq_meta") or {}
    return fmt_n(eq.get("eq_dd"), 2)


def _md_split(p: dict[str, Any], key: str) -> str:
    m = p[key]
    return (
        f"N={m['n']} WR={m['wr']:.1f}% Avg={m['avg_pnl']:.2f}% WO_MAX={m['wo_max']:.2f}% "
        f"PF={m['pf']:.2f} AnnROR={fmt_n(m['ann_ror'], 2)} MaxDD_overlay={fmt_n(m['max_dd'], 2)} "
        f"Calmar={fmt_n(m.get('calmar'), 2)} Sharpe={fmt_n(m.get('sharpe'), 2)}"
    )


def _th_cols() -> list[tuple[str, str]]:
    return filter_html_compare_columns(
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
            ("Δ Avg% vs control", "num"),
            ("Δ WR vs control", "num"),
            ("Δ PF vs control", "num"),
            ("Δ Ann ROR vs control", "num"),
            ("Δ Max DD vs control", "num"),
            ("Δ Calmar vs control", "num"),
            ("Note", "text"),
        ]
    )


def write_compare_html(
    packed: list[dict[str, Any]],
    verdicts: dict[str, dict[str, tuple[str, str]]],
    meta: dict[str, Any],
) -> Path:
    by_id = {p["arm"]["id"]: p for p in packed}
    th = "".join(sortable_th(a, b) for a, b in _th_cols())
    panels = []
    for book, title, n_univ in (
        ("core", "Core tradable 764", len(meta["core"])),
        ("expanded", f"Expanded soft ≤{SOFT_FIRST_MAX.isoformat()} ({len(meta['expanded'])})", len(meta["expanded"])),
    ):
        ctrl = by_id[f"{book}_control"]
        cand = by_id[f"{book}_40d"]
        vis, nis = verdicts[book]["is"]
        voos, noos = verdicts[book]["oos"]
        sections = []
        for split_key, stitle in (("m_is", "IS"), ("m_oos", "OOS (report-only)"), ("m_full", "FULL book")):
            body = "".join(
                compare_row(p, split_key, ctrl, "", f"{book}_control") for p in (ctrl, cand)
            )
            sections.append(
                f"<h3>{stitle}</h3>"
                f'<p class="muted">Δ vs book control (cut OFF, no time stop). Click headers to sort.</p>'
                f'<div class="table-wrap"><table class="sortable"><thead><tr>{th}</tr></thead>'
                f"<tbody>{body}</tbody></table></div>"
            )
        panels.append(
            f'<section class="panel"><h2>{title}</h2>'
            f'<p class="muted">Univ N={n_univ}. 40d vs control: IS <code>{vis}</code> ({html_mod.escape(nis)}); '
            f"OOS <code>{voos}</code> ({html_mod.escape(noos)}).</p>"
            + "".join(sections)
            + "</section>"
        )

    freeze_rows = []
    for aid in ("core_control", "core_40d", "expanded_control", "expanded_40d"):
        p = by_id[aid]
        arm = p["arm"]
        exd = HOUSE_EXIT_DAYS_40 if "40d" in aid else HOUSE_EXIT_DAYS_OFF
        freeze_rows.append(
            "<tr>"
            f"<td>{html_mod.escape(arm['label'])}</td>"
            f"<td>{arm['book']}</td>"
            f"<td>{len(arm['symbols'])}</td>"
            f"<td>{HOUSE_CUT_OFF}</td>"
            f"<td>{exd}</td>"
            f"<td>{HOUSE_EXIT_PERCENT}</td>"
            f"<td>{p.get('stamp', '')}</td>"
            f"<td>{p['m_full']['n']}</td>"
            f"<td>{_exit_count(p, 'RL_EXIT_DAYS')}</td>"
            f"<td>{_host_dd(p)}</td>"
            f"<td>{p['m_full'].get('avg_days', 0):.1f}</td>"
            "</tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RL 40d dual-book — {STAMP}</title>
<style>
:root {{ --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#9aa7b8; --line:#2a3545; --accent:#5b9fd4; --ctrl:#243044; }}
*{{box-sizing:border-box}}
body{{margin:0;font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.45}}
header{{padding:1.25rem 1rem 0.5rem;max-width:1600px;margin:0 auto}}
h1{{font-size:1.35rem;margin:0 0 .35rem}}
h2{{font-size:1.1rem;margin:0 0 .4rem;color:var(--accent)}}
h3{{font-size:1rem;margin:1rem 0 .35rem;color:var(--text)}}
.muted{{color:var(--muted);font-size:.92rem}}
.callout{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.75rem 1rem;margin:.75rem 0}}
main{{max-width:1600px;margin:0 auto;padding:0 1rem 2.5rem}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:1rem}}
@media (max-width:1100px){{.grid{{grid-template-columns:1fr}}}}
.panel{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.75rem 1rem}}
.table-wrap{{overflow-x:auto;border:1px solid var(--line);border-radius:8px;margin-bottom:.75rem}}
table{{width:100%;border-collapse:collapse;font-size:.82rem}}
th,td{{padding:.4rem .5rem;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}}
th:first-child,td:first-child{{text-align:left}}
thead th{{background:#152030;position:sticky;top:0;cursor:pointer}}
tr.ctrl-row td{{background:var(--ctrl);font-weight:600}}
{SORTABLE_TH_CSS}
</style></head><body>
<header>
<h1>RL dual-book — 40d time-stop vs control</h1>
<p class="muted">Stamp <code>rl_40d_dualbook_{STAMP}</code>. IS entry &lt; 2024-01-01. Research-only — not DailyRun.</p>
<div class="callout">
<strong>Freeze:</strong> cut OFF (<code>rl_cut_the_losers={HOUSE_CUT_OFF}</code>).
Control = time stop OFF (<code>rl_exit_days={HOUSE_EXIT_DAYS_OFF}</code>).
40d arm = <code>rl_exit_days={HOUSE_EXIT_DAYS_40}</code> after <code>rl_exit_percent={HOUSE_EXIT_PERCENT}</code>.
House dip=1.055, expansion=1.163, stop={HOUSE_STOP}, target=1.20; trails/flush/too_high off.
</div>
<div class="callout">
<strong>Dual-book read:</strong> win on <em>both</em> core + expanded = stronger evidence.
Expanded-only lift = newer-name effect (do not promote from expanded alone).
Core: {len(meta['core'])} · Expanded: {len(meta['expanded'])} (soft ≤{SOFT_FIRST_MAX.isoformat()}, includes CRWD/APP/ZM).
</div>
<div class="callout">
<strong>Verdicts (40d vs control):</strong>
Core IS <code>{verdicts['core']['is'][0]}</code> / OOS <code>{verdicts['core']['oos'][0]}</code>;
Expanded IS <code>{verdicts['expanded']['is'][0]}</code> / OOS <code>{verdicts['expanded']['oos'][0]}</code>.
</div>
</header>
<main>
<section><h2>Freeze table</h2>
<div class="table-wrap"><table class="sortable"><thead><tr>
{sortable_th("Arm", "text")}{sortable_th("Book", "text")}{sortable_th("Univ N", "num")}
{sortable_th("cut_the_losers", "num")}{sortable_th("exit_days", "num")}
{sortable_th("exit_percent", "num")}{sortable_th("Stamp", "text")}{sortable_th("N full", "num")}
{sortable_th("RL_EXIT rows", "num")}{sortable_th("Host Max DD%", "num")}{sortable_th("Avg days", "num")}
</tr></thead><tbody>{"".join(freeze_rows)}</tbody></table></div></section>
<div class="grid">
{"".join(panels)}
</div>
</main>
{SORTABLE_TABLE_SCRIPT}
</body></html>"""
    path = OUT_DIR / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def _plain_english(
    packed: list[dict[str, Any]],
    verdicts: dict[str, dict[str, tuple[str, str]]],
    meta: dict[str, Any],
) -> str:
    by_id = {p["arm"]["id"]: p for p in packed}
    lines = [
        "Same house freeze as Paul control stamp `rl_cutoff_40d_control_20260831`: "
        "cut-the-losers OFF, then **one knob** — 40d time-stop after +29% profit gate vs no time stop.",
        "",
        f"**Core book** ({len(meta['core'])} names, 2010 tradable): IS `{verdicts['core']['is'][0]}` "
        f"({verdicts['core']['is'][1]}); OOS `{verdicts['core']['oos'][0]}` "
        f"({verdicts['core']['oos'][1]}).",
        "",
        f"**Expanded book** ({len(meta['expanded'])} names, soft first ≤{SOFT_FIRST_MAX.isoformat()} "
        f"+ $5/ADV$2m — includes CRWD/APP/ZM): IS `{verdicts['expanded']['is'][0]}` "
        f"({verdicts['expanded']['is'][1]}); OOS `{verdicts['expanded']['oos'][0]}` "
        f"({verdicts['expanded']['oos'][1]}).",
        "",
    ]
    c_is = verdicts["core"]["is"][0]
    e_is = verdicts["expanded"]["is"][0]
    keepish = {"LEAN KEEP", "KEEP"}
    dismissish = {"DISMISS"}
    if c_is in keepish and e_is in keepish:
        lines.append(
            "**Dual-book read:** 40d wins (or leans) on **both** books → stronger research signal "
            "(still not gold / not DailyRun)."
        )
    elif c_is in dismissish and e_is in dismissish:
        lines.append(
            "**Dual-book read:** 40d loses quality on **both** books → do not adopt 40d as control "
            "from this AB (same quality-over-count rule as core-only stamp)."
        )
    elif c_is in dismissish and e_is in keepish:
        lines.append(
            "**Dual-book read:** Expanded-only improvement → treat as **newer-name effect**, "
            "not a core-control change."
        )
    elif c_is in keepish and e_is in dismissish:
        lines.append(
            "**Dual-book read:** Core-only lean / expanded softens → HOLD; do not retune on OOS "
            "or expand-only."
        )
    else:
        lines.append(
            "**Dual-book read:** Mixed / HOLD across books → stay provisional; do not wire DailyRun."
        )

    for book in BOOKS:
        ctrl = by_id[f"{book}_control"]
        cand = by_id[f"{book}_40d"]
        d_ann = cand["m_is"]["ann_ror"] - ctrl["m_is"]["ann_ror"]
        d_avg = cand["m_is"]["avg_pnl"] - ctrl["m_is"]["avg_pnl"]
        d_dd = cand["m_is"]["max_dd"] - ctrl["m_is"]["max_dd"]
        lines.extend(
            [
                "",
                f"- {book.title()} IS deltas (40d − control): AnnROR {d_ann:+.1f} pts, "
                f"Avg% {d_avg:+.2f}, overlay MaxDD {d_dd:+.1f}; "
                f"avg days {ctrl['m_is'].get('avg_days', 0):.1f} → {cand['m_is'].get('avg_days', 0):.1f}.",
            ]
        )
    lines.extend(
        [
            "",
            "Research-only dual report. Core Closed reused from exact-match control stamp; "
            "expanded arms re-run. Not gold. Not DailyRun.",
        ]
    )
    return "\n".join(lines)


def write_docs(
    packed: list[dict[str, Any]],
    verdicts: dict[str, dict[str, tuple[str, str]]],
    meta: dict[str, Any],
) -> None:
    by_id = {p["arm"]["id"]: p for p in packed}
    freeze_lines = [
        f"# BASELINE — `rl_40d_dualbook_{STAMP}`",
        "",
        "**Status:** RESEARCH — dual-book 40d vs control. Not gold. Not DailyRun.",
        "",
        "## Hypothesis (one knob)",
        "",
        "On each book separately: does **40d time-stop** (cut OFF) improve quality vs "
        "**cut OFF + no time stop**? Dual-book is a **report sleeve**, not a merged headline.",
        "",
        "## Freeze (both books)",
        "",
        "| Knob | Control | 40d arm |",
        "|------|---------|---------|",
        f"| `rl_cut_the_losers` | **{HOUSE_CUT_OFF}** (OFF) | **{HOUSE_CUT_OFF}** (OFF) |",
        f"| `rl_exit_days` | **{HOUSE_EXIT_DAYS_OFF}** (OFF) | **{HOUSE_EXIT_DAYS_40}** |",
        f"| `rl_exit_percent` | **{HOUSE_EXIT_PERCENT}** | **{HOUSE_EXIT_PERCENT}** |",
        "| `rl_dip_pct` | **1.055** | same |",
        "| `rl_expansion` | **1.163** | same |",
        f"| `rl_stop_pct` | **{HOUSE_STOP}** | same |",
        "| `rl_target_pct` | **1.20** | same |",
        "| trails / flush / too_high | **off** | same |",
        "| cash | **$47,500** | same |",
        "",
        "## Universes",
        "",
        "| Book | N | Path / notes |",
        "|------|--:|-------------|",
        f"| Core | **{len(meta['core'])}** | `drive/universes/VZ_tradable_2010_adv2m_universe.csv` |",
        f"| Expanded | **{len(meta['expanded'])}** | `{EXPANDED_CSV.as_posix()}` — soft first ≤"
        f"{SOFT_FIRST_MAX.isoformat()} + $5/ADV$2m; extras={len(meta['extras'])}; "
        "includes CRWD/APP/ZM (2018 soft ~923 does not) |",
        "",
        "## Split",
        "",
        f"- IS: entry_date < {IS_CUT.isoformat()}",
        "- OOS: entry_date ≥ that cut — **report-only**; no OOS retune",
        f"- Soft extras with first_bar ≥ IS cut: **{meta.get('no_is_extras', 0)}** "
        "(expect 0; shorter tapes still labeled)",
        "",
        "## Dual-book read rules",
        "",
        "1. Judge **quality** (Avg%, WO_MAX, PF, WR) — not trade count alone.",
        "2. **Win on both** core + expanded IS → stronger research candidate.",
        "3. **Expanded-only** win → newer-name effect; do not change core control from that alone.",
        "4. Core DISMISS + expanded soft → stay with control / HOLD.",
        "5. OOS softens → HOLD; never retune OOS.",
        "",
        "## Run sources",
        "",
        "| Arm | Source |",
        "|-----|--------|",
        f"| `core_control` | reuse `rl_cutoff_40d_control_{STAMP}` / `cut_off` `{CORE_CTRL_STAMP}` |",
        f"| `core_40d` | reuse `rl_cutoff_40d_control_{STAMP}` / `new_control` `{CORE_40D_STAMP}` |",
        "| `expanded_control` | **live** this stamp |",
        "| `expanded_40d` | **live** this stamp |",
        "",
        "## Arms",
        "",
        "| Arm | Stamp | N_full | RL_EXIT | Host DD% | Avg days | OK |",
        "|-----|-------|--------|---------|----------|----------|-----|",
    ]
    for aid in ARM_ORDER:
        p = by_id[aid]
        freeze_lines.append(
            f"| `{aid}` | `{p.get('stamp', '')}` | {p['m_full']['n']} | "
            f"{_exit_count(p, 'RL_EXIT_DAYS')} | {_host_dd(p)} | "
            f"{p['m_full'].get('avg_days', 0):.1f} | {'yes' if p.get('ok') else 'no'} |"
        )
    freeze_lines.extend(
        [
            "",
            "## Verdicts (40d vs book control)",
            "",
            f"- Core IS `{verdicts['core']['is'][0]}` ({verdicts['core']['is'][1]})",
            f"- Core OOS `{verdicts['core']['oos'][0]}` ({verdicts['core']['oos'][1]})",
            f"- Expanded IS `{verdicts['expanded']['is'][0]}` ({verdicts['expanded']['is'][1]})",
            f"- Expanded OOS `{verdicts['expanded']['oos'][0]}` ({verdicts['expanded']['oos'][1]})",
            "",
            "## Selection-bias note",
            "",
            "40d was already scored on core in `rl_cutoff_40d_control_20260831`. This stamp "
            "adds expanded dual-report only — do not pick knobs from OOS or merge books into one score.",
            "",
        ]
    )
    (OUT_DIR / "BASELINE.md").write_text("\n".join(freeze_lines), encoding="utf-8")

    slines = [
        f"# SUMMARY — `rl_40d_dualbook_{STAMP}`",
        "",
        "Dual-book 40d time-stop vs control (cut OFF). Research only.",
        "",
        "## Plain English (Paul / PO)",
        "",
        _plain_english(packed, verdicts, meta),
        "",
    ]
    for book in BOOKS:
        slines.extend([f"## {book.title()} FULL", ""])
        for role in ("control", "40d"):
            aid = f"{book}_{role}"
            slines.append(f"- **{aid}**: {_md_split(by_id[aid], 'm_full')}")
        slines.extend(["", f"## {book.title()} IS", ""])
        for role in ("control", "40d"):
            aid = f"{book}_{role}"
            slines.append(f"- **{aid}**: {_md_split(by_id[aid], 'm_is')}")
        slines.extend(["", f"## {book.title()} OOS (report-only)", ""])
        for role in ("control", "40d"):
            aid = f"{book}_{role}"
            slines.append(f"- **{aid}**: {_md_split(by_id[aid], 'm_oos')}")
        slines.append("")
    slines.extend(
        [
            "## Exit mix (FULL)",
            "",
        ]
    )
    for aid in ARM_ORDER:
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
            f"- HTML: `drive/paul_experiments/rl_40d_dualbook_{STAMP}/compare.html`",
            f"- BASELINE: `drive/paul_experiments/rl_40d_dualbook_{STAMP}/BASELINE.md`",
            f"- Expanded univ: `{EXPANDED_CSV.as_posix()}`",
            "",
        ]
    )
    (OUT_DIR / "SUMMARY.md").write_text("\n".join(slines), encoding="utf-8")


def summarize(packed: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
    by_id = {p["arm"]["id"]: p for p in packed}
    verdicts: dict[str, dict[str, tuple[str, str]]] = {}
    for book in BOOKS:
        ctrl = by_id[f"{book}_control"]
        cand = by_id[f"{book}_40d"]
        verdicts[book] = {
            "is": verdict_vs_control(cand, ctrl, "m_is"),
            "oos": verdict_vs_control(cand, ctrl, "m_oos"),
        }
    write_compare_html(packed, verdicts, meta)
    write_metrics_csv(packed, "", OUT_DIR / "metrics_all.csv")
    write_docs(packed, verdicts, meta)
    print(f"[RL-40D-DUAL] Wrote {OUT_DIR / 'compare.html'}", flush=True)
    return {"verdicts": verdicts, "packed": packed}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--build-univ-only", action="store_true")
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    skip_existing = args.skip_existing or args.summarize_only

    meta = build_expanded_universe()
    print(
        f"[RL-40D-DUAL] univ core={len(meta['core'])} expanded={len(meta['expanded'])} "
        f"extras={len(meta['extras'])} path={meta['path']}",
        flush=True,
    )
    if args.build_univ_only:
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    arms = _arm_defs(meta["core"], meta["expanded"])
    py = _resolve_python()
    runs: list[dict[str, Any]] = []

    if args.summarize_only:
        for arm in arms:
            run = _load_arm_from_disk(arm)
            print(
                f"[RL-40D-DUAL] load {arm['id']} ok={run['ok']} n={len(run.get('trades') or [])}",
                flush=True,
            )
            runs.append(run)
    else:
        for arm in arms:
            if arm.get("live"):
                run = run_live(py, arm, args.workers, skip_existing)
            else:
                run = copy_reuse(arm)
            print(
                f"[RL-40D-DUAL] {arm['id']} ok={run['ok']} n={len(run.get('trades') or [])} "
                f"elapsed={run.get('elapsed_s', 0):.0f}s skipped={run.get('skipped')} "
                f"stamp={run.get('stamp', '')}",
                flush=True,
            )
            runs.append(run)

    runs.sort(key=lambda r: ARM_ORDER.get(r["arm"]["id"], 99))
    if not all(r.get("ok") for r in runs) or len(runs) < 4:
        print("[RL-40D-DUAL] Required arms missing", flush=True)
        for r in runs:
            print(f"  {r['arm']['id']}: ok={r.get('ok')}", flush=True)
        return 1

    packed = [pack_result(r) for r in runs]
    result = summarize(packed, meta)

    ntfy = ROOT / "tools" / "ntfy_job_done.py"
    if ntfy.is_file():
        v = result["verdicts"]
        subprocess.run(
            [
                py,
                str(ntfy),
                "--path",
                str(OUT_DIR / "compare.html"),
                "-t",
                "RL 40d dual-book",
                "-m",
                f"Core IS {v['core']['is'][0]} OOS {v['core']['oos'][0]} · "
                f"Expanded IS {v['expanded']['is'][0]} OOS {v['expanded']['oos'][0]} · "
                f"N={len(meta['core'])}/{len(meta['expanded'])}",
            ],
            cwd=str(ROOT),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
