#!/usr/bin/env python3
"""RL too-high + volume A/B on FULL universe under NEW exit freeze 29%/40d.

Exit freeze (ALL arms — NEW research freeze, NOT prod 40%/30d):
  rl_exit_percent=0.29, rl_exit_days=40, rl_cut_the_losers=1000 (OFF).

Universe: full OHLC pool = all CSVs under data/newdata/data (~1123), same as
run_rl.bat ALL. NOT house 59, NOT tradable 764.

Experiment 1 — too_high fill gate:
  Control: rl_too_high=0
  Arm A:   rl_too_high=1.13  ("too high >=13" → house multiplier unit)
  Arm B:   rl_too_high=1.14  ("too high >=14")
  Fill gate when on: next_open <= signal_low × rl_too_high × rl_stop_pct (0.934)

Experiment 2 — too_high@1.13 + dual volume:
  Control: reuse th113 (too_high=1.13, no vol gates)
  Candidate: too_high=1.13 + rl_min_avg_vol=10000 + rl_min_trigger_vol=5000
             (BOTH must pass; avg_vol window = default rl_avg_vol_days=50)
  Also reports deltas vs Exp1 control (too_high OFF) for context.

House knobs otherwise match run_rl.bat (dip 1.055, SMA qual on, slope/ATR off, …).

IS = entry < 2024-01-01; OOS report-only; no OOS retune.
Research-only. Not gold. Not DailyRun.

Usage:
  python tools/rl_too_high_vol_fulluniv_29_40d.py
  python tools/rl_too_high_vol_fulluniv_29_40d.py --summarize-only
  python tools/rl_too_high_vol_fulluniv_29_40d.py --skip-existing --jobs 2 --workers 5
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
DATA_DIR = ROOT / "data" / "newdata" / "data"
STAMP = "20260904"
OUT_DIR = DRIVE / "paul_experiments" / f"rl_too_high_vol_fulluniv_29_40d_{STAMP}"
EXP1_DIR = OUT_DIR / "too_high_ab"
EXP2_DIR = OUT_DIR / "too_high13_vol_ab"
RUNS_DIR = OUT_DIR / "runs"

HOUSE_STOP = 0.934
HOUSE_CUT = 1000  # off
HOUSE_EXIT_PCT = 0.29  # NEW freeze (prod is 0.40)
HOUSE_EXIT_DAYS = 40  # NEW freeze (prod is 30)
HOUSE_DIP = 1.055
TH13 = 1.13
TH14 = 1.14
MIN_AVG_VOL = 10_000
MIN_TRIGGER_VOL = 5_000

CONTROL_ID = "control"
TH113_ID = "th113"
TH114_ID = "th114"
TH113_VOL_ID = "th113_vol"

ARM_ORDER = {CONTROL_ID: 0, TH113_ID: 1, TH114_ID: 2, TH113_VOL_ID: 3}

sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(DRIVE / "paul_experiments"))
from be_stop_replay_ab import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402
from compare_format import filter_html_compare_columns  # noqa: E402
from rl_univ_compare_lists import (  # noqa: E402
    PER_SYMBOL,
    SA,
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


def _effective_cap(th: float) -> float:
    return th * HOUSE_STOP


def _full_univ_symbols() -> list[str]:
    if not DATA_DIR.is_dir():
        return []
    return sorted(p.stem.upper() for p in DATA_DIR.glob("*.csv"))


def _count_full_univ() -> int:
    return len(_full_univ_symbols())


def _freeze_base() -> list[str]:
    return [
        "rl_mode=true",
        "brt_zones=false",
        "yh_zones=false",
        "wpbr_zones=false",
        "indicator_buy=off",
        "rl_sma_qual=1",
        "ATR_LOW=off",
        "ATR_HIGH=off",
        "rl_slope_threshold=0",
        f"rl_dip_pct={HOUSE_DIP}",
        "rl_expansion=1.163",
        f"rl_stop_pct={HOUSE_STOP}",
        "rl_target_pct=1.2",
        f"rl_cut_the_losers={HOUSE_CUT}",
        f"rl_exit_percent={HOUSE_EXIT_PCT}",
        f"rl_exit_days={HOUSE_EXIT_DAYS}",
        "rl_post_target_reentry_bars=0",
    ]


def _arm_defs(symbols: list[str] | None = None) -> list[dict[str, Any]]:
    syms = list(symbols) if symbols is not None else _full_univ_symbols()
    n = len(syms)
    return [
        {
            "id": CONTROL_ID,
            "label": f"Control (too_high=0, +{HOUSE_EXIT_PCT:.0%}/{HOUSE_EXIT_DAYS}d)",
            "role": "control",
            "symbols": syms,
            "univ_n": n,
            "too_high": 0.0,
            "effective_cap": None,
            "extra_v": ["rl_too_high=0"],
        },
        {
            "id": TH113_ID,
            "label": (
                f"too_high={TH13:.2f} (≥13% raw knob; "
                f"cap≈{_effective_cap(TH13):.3f}× low)"
            ),
            "role": "candidate",
            "symbols": syms,
            "univ_n": n,
            "too_high": TH13,
            "effective_cap": _effective_cap(TH13),
            "extra_v": [f"rl_too_high={TH13}"],
        },
        {
            "id": TH114_ID,
            "label": (
                f"too_high={TH14:.2f} (≥14% raw knob; "
                f"cap≈{_effective_cap(TH14):.3f}× low)"
            ),
            "role": "candidate",
            "symbols": syms,
            "univ_n": n,
            "too_high": TH14,
            "effective_cap": _effective_cap(TH14),
            "extra_v": [f"rl_too_high={TH14}"],
        },
        {
            "id": TH113_VOL_ID,
            "label": (
                f"too_high={TH13:.2f} + AVG_VOL≥{MIN_AVG_VOL:,} "
                f"+ TRIGGER_VOL≥{MIN_TRIGGER_VOL:,}"
            ),
            "role": "candidate",
            "symbols": syms,
            "univ_n": n,
            "too_high": TH13,
            "effective_cap": _effective_cap(TH13),
            "min_avg_vol": MIN_AVG_VOL,
            "min_trigger_vol": MIN_TRIGGER_VOL,
            "extra_v": [
                f"rl_too_high={TH13}",
                f"rl_min_avg_vol={MIN_AVG_VOL}",
                f"rl_min_trigger_vol={MIN_TRIGGER_VOL}",
            ],
        },
    ]


def build_cmd(py: str, outdir: Path, workers: int, extra_v: list[str]) -> list[str]:
    """Full universe = omit -s (same as run_rl.bat ALL)."""
    cmd = [
        py,
        str(SA / "rocket_tbn.py"),
        str(DATA_DIR),
        "-o",
        str(outdir),
        "-w",
        str(workers),
        "--aggressive",
        "--use-duckdb",
        "--no-regression",
    ]
    if PER_SYMBOL.is_file():
        cmd.extend(["--per-symbol-settings", str(PER_SYMBOL)])
    for v in _freeze_base() + list(extra_v):
        cmd.extend(["-v", v])
    return cmd


def run_live(py: str, arm: dict[str, Any], workers: int, skip_existing: bool) -> dict[str, Any]:
    arm_dir = RUNS_DIR / arm["id"]
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
    cmd = build_cmd(py, arm_dir, workers, arm.get("extra_v") or [])
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
    arm_dir = RUNS_DIR / arm["id"]
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


def _stamp_closed_copies(packed: list[dict[str, Any]], dest_dir: Path) -> list[Path]:
    """Copy Closed CSVs into experiment subfolder with arm-prefixed names."""
    closed_dir = dest_dir / "closed"
    closed_dir.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    for p in packed:
        src = p.get("closed")
        if not src or not Path(src).is_file():
            continue
        src = Path(src)
        dest = closed_dir / f"{p['arm']['id']}_{src.name}"
        shutil.copy2(src, dest)
        out.append(dest)
    return out


def _md_split(p: dict[str, Any], key: str) -> str:
    m = p[key]
    return (
        f"N={m['n']} WR={m['wr']:.1f}% Avg={m['avg_pnl']:.2f}% WO_MAX={m['wo_max']:.2f}% "
        f"PF={m['pf']:.2f} AnnROR={fmt_n(m['ann_ror'], 2)} MaxDD_overlay={fmt_n(m['max_dd'], 2)}"
    )


def _host_dd(p: dict[str, Any]) -> str:
    eq = p.get("eq_meta") or {}
    return fmt_n(eq.get("eq_dd"), 2)


def _arm_verdict(aid: str, verdicts: dict[str, dict[str, tuple[str, str]]]) -> str:
    vis, nis = verdicts[aid]["is"]
    voos, noos = verdicts[aid]["oos"]
    if vis in ("KEEP", "LEAN KEEP") and voos in ("KEEP", "LEAN KEEP", "HOLD"):
        tag = vis if voos != "DISMISS" else "HOLD (OOS soft)"
        return f"**`{aid}` {tag}** IS `{vis}` ({nis}); OOS `{voos}` ({noos}). Research candidate ≠ gold."
    if vis == "DISMISS":
        return f"**`{aid}` DISMISS** IS `{vis}` ({nis}); OOS `{voos}` ({noos})."
    return f"**`{aid}` HOLD** IS `{vis}` ({nis}); OOS `{voos}` ({noos})."


def _th_cols() -> list[tuple[str, str]]:
    return filter_html_compare_columns(
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


def write_compare_html(
    packed: list[dict[str, Any]],
    verdicts: dict[str, dict[str, tuple[str, str]]],
    *,
    control_id: str,
    out_path: Path,
    title: str,
    subtitle: str,
    paul_note: str,
    gate_section_html: str = "",
) -> Path:
    by_id = {p["arm"]["id"]: p for p in packed}
    baseline = by_id[control_id]
    cand_ids = [p["arm"]["id"] for p in packed if p["arm"]["id"] != control_id]
    th = "".join(sortable_th(a, b) for a, b in _th_cols())
    sections = []
    for split_key, split_title in (("m_is", "IS"), ("m_oos", "OOS (report-only)"), ("m_full", "FULL book")):
        body = "".join(compare_row(p, split_key, baseline, "", control_id) for p in packed)
        note = (
            "Paul/FIT/UW from host Summary + EquityMeta. Sharpe from host EquityCurve "
            "(Equity_Regular when present; IS/OOS = calendar slices). Overlay Max DD ≠ host DD."
            if split_key == "m_full"
            else "Closed overlay $47,500 / $500k. Sharpe from host EquityCurve calendar slice. "
            "Overlay Max DD ≠ host account DD."
        )
        sections.append(
            f'<section><h2>{html_mod.escape(title)} — {split_title}</h2>'
            f'<p class="muted">Δ vs control. {note} Click column headers to sort.</p>'
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
                ("Δ Sheet $", "num"),
                ("Δ Ann ROR", "num"),
                ("Δ Max DD", "num"),
            ]
        )
    )
    pairs = [(f"{aid} − {control_id}", by_id[control_id], by_id[aid]) for aid in cand_ids]
    pw_sections = []
    for split_key, split_title in (("m_is", "IS"), ("m_oos", "OOS"), ("m_full", "FULL")):
        rows = "".join(pairwise_delta_row(a, b, split_key, lbl) for lbl, a, b in pairs)
        pw_sections.append(
            f'<section><h2>Pairwise deltas — {split_title}</h2>'
            f'<p class="muted">Click headers to sort.</p>'
            f'<div class="table-wrap"><table class="sortable"><thead><tr>{pw_th}</tr></thead>'
            f"<tbody>{rows}</tbody></table></div></section>"
        )

    v_lis = [f"<li>{_arm_verdict(aid, verdicts)}</li>" for aid in cand_ids]

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{html_mod.escape(title)}</title>
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
<h1>{html_mod.escape(title)}</h1>
<p class="muted">{subtitle}</p>
</header>
<main>
<div class="callout">
<strong>Paul note:</strong> {html_mod.escape(paul_note)}
<ul>{"".join(v_lis)}</ul>
</div>
{"".join(sections)}
{"".join(pw_sections)}
{gate_section_html}
</main>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path


def _gate_section_exp1(packed: list[dict[str, Any]]) -> str:
    rows = []
    for p in packed:
        arm = p["arm"]
        th_val = arm.get("too_high", 0)
        cap = arm.get("effective_cap") if th_val else None
        rows.append(
            "<tr>"
            f"<td>{html_mod.escape(arm['label'])}</td>"
            f"<td>{th_val if th_val else '0 (off)'}</td>"
            f"<td>{HOUSE_STOP}</td>"
            f"<td>{fmt_n(cap, 4) if cap else '—'}</td>"
            f"<td>{p['m_full']['n']}</td>"
            f"<td>{_host_dd(p)}</td>"
            "</tr>"
        )
    return f"""<section>
<h2>Fill gate levels (effective cap vs signal low)</h2>
<p class="muted">User "≥13 / ≥14" → house multiplier <code>rl_too_high=1.13 / 1.14</code>.
Effective cap = rl_too_high × rl_stop_pct. Plain English: next open may not exceed
signal_low × too_high × stop. Click column headers to sort.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>
{sortable_th("Arm", "text")}{sortable_th("rl_too_high", "num")}{sortable_th("rl_stop_pct", "num")}
{sortable_th("Effective cap×low", "num")}{sortable_th("N (FULL)", "num")}{sortable_th("Host Max DD%", "num")}
</tr></thead><tbody>{"".join(rows)}</tbody></table></div>
</section>"""


def _best_too_high(packed: list[dict[str, Any]], verdicts: dict[str, dict[str, tuple[str, str]]]) -> str:
    cands = [p for p in packed if p["arm"]["id"] != CONTROL_ID]
    keepish = {"KEEP", "LEAN KEEP"}
    winners = [
        p
        for p in cands
        if verdicts[p["arm"]["id"]]["is"][0] in keepish
        and verdicts[p["arm"]["id"]]["oos"][0] != "DISMISS"
    ]
    if not winners:
        by_avg = sorted(cands, key=lambda p: p["m_is"]["avg_pnl"], reverse=True)
        best = by_avg[0]
        return (
            f"No arm earns KEEP/LEAN KEEP vs control. Best IS Avg% is "
            f"**{best['arm']['id']}** ({best['m_is']['avg_pnl']:.2f}%, N={best['m_is']['n']}) "
            f"but verdict is {verdicts[best['arm']['id']]['is'][0]} — research HOLD/DISMISS."
        )
    winners.sort(key=lambda p: (p["m_is"]["avg_pnl"], p["m_is"]["pf"]), reverse=True)
    best = winners[0]
    return (
        f"**`{best['arm']['id']}`** best on IS quality "
        f"(Avg={best['m_is']['avg_pnl']:.2f}%, PF={best['m_is']['pf']:.2f}, N={best['m_is']['n']}). "
        f"Verdict {verdicts[best['arm']['id']]['is'][0]} IS / {verdicts[best['arm']['id']]['oos'][0]} OOS. "
        f"Research-only; NEW exit freeze 29%/40d — not prod 40%/30d."
    )


def write_exp1(by_id: dict[str, dict[str, Any]]) -> tuple[Path, list[Path], dict[str, tuple[str, str]]]:
    packed = [by_id[CONTROL_ID], by_id[TH113_ID], by_id[TH114_ID]]
    control = by_id[CONTROL_ID]
    verdicts = {
        aid: {
            "is": verdict_vs_control(by_id[aid], control, "m_is"),
            "oos": verdict_vs_control(by_id[aid], control, "m_oos"),
        }
        for aid in (TH113_ID, TH114_ID)
    }
    n_univ = _count_full_univ()
    subtitle = (
        f"Stamp <code>rl_too_high_vol_fulluniv_29_40d_{STAMP}/too_high_ab</code>. "
        f"One knob: <code>rl_too_high</code>. "
        f"<strong>NEW exit freeze:</strong> <code>rl_exit_percent={HOUSE_EXIT_PCT}</code>, "
        f"<code>rl_exit_days={HOUSE_EXIT_DAYS}</code>, cut OFF ({HOUSE_CUT}). "
        f"Universe: full OHLC pool ({n_univ} CSVs under <code>data/newdata/data</code>) = "
        f"<code>run_rl.bat ALL</code>. "
        f"Fill gate when on: next_open ≤ signal_low × too_high × stop ({HOUSE_STOP}). "
        f"Dip={HOUSE_DIP}, expansion=1.163, SMA qual on, slope/ATR off. "
        f"Not gold / not DailyRun. IS = entry &lt; 2024-01-01; OOS report-only. "
        f"Click column headers to sort."
    )
    html_path = write_compare_html(
        packed,
        verdicts,
        control_id=CONTROL_ID,
        out_path=EXP1_DIR / "compare.html",
        title=f"RL too_high A/B — full univ +{HOUSE_EXIT_PCT:.0%}/{HOUSE_EXIT_DAYS}d",
        subtitle=subtitle,
        paul_note=_best_too_high(packed, verdicts),
        gate_section_html=_gate_section_exp1(packed),
    )
    closed = _stamp_closed_copies(packed, EXP1_DIR)
    write_metrics_csv(packed, "", EXP1_DIR / "metrics_all.csv")

    freeze = [
        f"# BASELINE — `rl_too_high_vol_fulluniv_29_40d_{STAMP}/too_high_ab`",
        "",
        "**Status:** RESEARCH only. One ENTRY fill-gate knob (`rl_too_high`) vs control.",
        f"**Exit freeze (NEW):** `rl_exit_percent={HOUSE_EXIT_PCT}` (+29% entry MTM) then "
        f"`rl_exit_days={HOUSE_EXIT_DAYS}`. Prod/DailyRun remains +40%/30d — do not confuse.",
        "Not gold. Not DailyRun.",
        "",
        "## House freeze (identical except rl_too_high)",
        "",
        "| Knob | Value | Notes |",
        "|------|-------|-------|",
        f"| `rl_dip_pct` | **{HOUSE_DIP}** | match `run_rl.bat` |",
        "| `rl_expansion` | **1.163** | |",
        f"| `rl_stop_pct` | **{HOUSE_STOP}** | |",
        "| `rl_target_pct` | **1.20** | SMA50 |",
        "| trails | **off** | |",
        f"| `rl_exit_percent` | **{HOUSE_EXIT_PCT}** | NEW freeze (+29% MTM) |",
        f"| `rl_exit_days` | **{HOUSE_EXIT_DAYS}** | NEW freeze (after profit gate) |",
        f"| `rl_cut_the_losers` | **{HOUSE_CUT}** (off) | all arms |",
        "| `rl_too_high` | **0** on control | candidates 1.13 / 1.14 |",
        "| `rl_sma_qual` | **1** | on |",
        "| `rl_slope_threshold` | **0** | off |",
        "| ATR_LOW / ATR_HIGH | **off** | |",
        "| cash | **$47,500** | |",
        "",
        "## Fill gate (when too_high > 0)",
        "",
        "`next_open <= signal_low × rl_too_high × rl_stop_pct`",
        "",
        "User wording \"too high ≥13 / ≥14\" → house multiplier unit **1.13 / 1.14** "
        "(prior ABs used 1.10–1.16; not integer 13 and not 0.13).",
        "",
        "| rl_too_high | Plain English | Effective cap vs signal low |",
        "|-------------|----------------|----------------------------|",
        "| 0 | off (no fill cap) | — |",
        f"| {TH13:.2f} | next open ≤ signal_low × {TH13} × {HOUSE_STOP} | "
        f"**{_effective_cap(TH13):.4f}×** low |",
        f"| {TH14:.2f} | next open ≤ signal_low × {TH14} × {HOUSE_STOP} | "
        f"**{_effective_cap(TH14):.4f}×** low |",
        "",
        "## Universe / split",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Universe | **Full** — all CSVs under `data/newdata/data` (**{n_univ}**), "
        "same as `run_rl.bat ALL`. NOT house 59, NOT tradable 764 |",
        "| Split | IS entry < 2024-01-01; OOS report-only; no OOS retune |",
        "",
        "## Arms",
        "",
        "| Arm | rl_too_high | Effective cap | Stamp | N_full | Host Max DD% | OK |",
        "|-----|-------------|---------------|-------|--------|--------------|-----|",
    ]
    for p in packed:
        arm = p["arm"]
        th = arm.get("too_high", 0)
        cap = fmt_n(arm.get("effective_cap"), 4) if th else "—"
        freeze.append(
            f"| `{arm['id']}` | {th if th else '0 (off)'} | {cap} | "
            f"`{p.get('stamp','')}` | {p['m_full']['n']} | {_host_dd(p)} | "
            f"{'yes' if p.get('ok') else 'no'} |"
        )
    freeze.extend(["", "## Verdicts (vs control, quality over N)", ""])
    for aid in (TH113_ID, TH114_ID):
        freeze.append(f"- {_arm_verdict(aid, verdicts)}")
    freeze.extend(
        [
            "",
            "## Selection-bias note",
            "",
            "Levels 1.13 / 1.14 pre-agreed from user request (neighborhood of prior 1.10–1.16 sweeps). "
            "Do not pick after seeing OOS. Exit freeze is research-only.",
            "",
            "## Closed copies",
            "",
        ]
    )
    for c in closed:
        freeze.append(f"- `{c.relative_to(ROOT).as_posix()}`")
    freeze.append("")
    (EXP1_DIR / "BASELINE.md").write_text("\n".join(freeze), encoding="utf-8")

    slines = [
        f"# SUMMARY — too_high_ab (full univ 29%/40d)",
        "",
        _best_too_high(packed, verdicts),
        "",
        "## IS",
        "",
    ]
    for aid in (CONTROL_ID, TH113_ID, TH114_ID):
        slines.append(f"- **{aid}**: {_md_split(by_id[aid], 'm_is')}")
    slines.extend(["", "## OOS (report-only)", ""])
    for aid in (CONTROL_ID, TH113_ID, TH114_ID):
        slines.append(f"- **{aid}**: {_md_split(by_id[aid], 'm_oos')}")
    slines.extend(["", "## Verdicts", ""])
    for aid in (TH113_ID, TH114_ID):
        slines.append(f"- {_arm_verdict(aid, verdicts)}")
    slines.extend(
        [
            "",
            f"- HTML: `{html_path.relative_to(ROOT).as_posix()}`",
            "",
        ]
    )
    (EXP1_DIR / "SUMMARY.md").write_text("\n".join(slines), encoding="utf-8")
    return html_path, closed, {aid: verdicts[aid]["is"] for aid in verdicts}


def write_exp2(by_id: dict[str, dict[str, Any]]) -> tuple[Path, list[Path], dict[str, tuple[str, str]]]:
    # Primary control = th113 (same too_high, no vol). Also include Exp1 control for context.
    packed = [by_id[TH113_ID], by_id[TH113_VOL_ID], by_id[CONTROL_ID]]
    # Reorder: primary control first for compare_row baseline styling
    packed_primary = [by_id[TH113_ID], by_id[TH113_VOL_ID]]
    control = by_id[TH113_ID]
    off_ctrl = by_id[CONTROL_ID]
    verdicts = {
        TH113_VOL_ID: {
            "is": verdict_vs_control(by_id[TH113_VOL_ID], control, "m_is"),
            "oos": verdict_vs_control(by_id[TH113_VOL_ID], control, "m_oos"),
        },
        # contextual vs too_high OFF
        f"{TH113_VOL_ID}_vs_off": {
            "is": verdict_vs_control(by_id[TH113_VOL_ID], off_ctrl, "m_is"),
            "oos": verdict_vs_control(by_id[TH113_VOL_ID], off_ctrl, "m_oos"),
        },
    }
    # For HTML arm verdicts list, only primary candidate
    html_verdicts = {TH113_VOL_ID: verdicts[TH113_VOL_ID]}
    n_univ = _count_full_univ()
    v_is, n_is = verdicts[TH113_VOL_ID]["is"]
    v_oos, n_oos = verdicts[TH113_VOL_ID]["oos"]
    v_off, _ = verdicts[f"{TH113_VOL_ID}_vs_off"]["is"]
    paul = (
        f"Dual volume on top of too_high={TH13}: IS `{v_is}` ({n_is}) vs th113 control; "
        f"OOS `{v_oos}` ({n_oos}). Vs too_high OFF control: IS `{v_off}`. "
        f"Both floors required: AVG_VOL≥{MIN_AVG_VOL:,} (rl_min_avg_vol over default 50d) AND "
        f"TRIGGER_VOL≥{MIN_TRIGGER_VOL:,} (rl_min_trigger_vol). Research-only."
    )
    subtitle = (
        f"Stamp <code>rl_too_high_vol_fulluniv_29_40d_{STAMP}/too_high13_vol_ab</code>. "
        f"Knobs: dual volume on frozen <code>rl_too_high={TH13}</code>. "
        f"<strong>NEW exit freeze:</strong> +{HOUSE_EXIT_PCT:.0%}/{HOUSE_EXIT_DAYS}d, cut OFF. "
        f"Universe: full OHLC ({n_univ}). "
        f"Primary control = th113 (same too_high, no vol). "
        f"too_high OFF control included for context. "
        f"Not gold / not DailyRun. Click column headers to sort."
    )
    # Build HTML with th113 as control; append off-control row via packed_primary + off
    # compare_row needs control in packed — use th113 as baseline_id
    # Include CONTROL_ID as extra candidate vs th113 for visibility
    packed_html = [by_id[TH113_ID], by_id[TH113_VOL_ID], by_id[CONTROL_ID]]
    # Extra verdict for control-off vs th113 so HTML list is clean — only vol candidate
    html_path = write_compare_html(
        packed_html,
        {
            TH113_VOL_ID: verdicts[TH113_VOL_ID],
            CONTROL_ID: {
                "is": verdict_vs_control(off_ctrl, control, "m_is"),
                "oos": verdict_vs_control(off_ctrl, control, "m_oos"),
            },
        },
        control_id=TH113_ID,
        out_path=EXP2_DIR / "compare.html",
        title=f"RL too_high@1.13 + dual vol — full univ +{HOUSE_EXIT_PCT:.0%}/{HOUSE_EXIT_DAYS}d",
        subtitle=subtitle,
        paul_note=paul,
        gate_section_html=f"""<section>
<h2>Volume + fill gate knobs</h2>
<p class="muted">Trade must pass <strong>both</strong> volume floors. Click headers to sort.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>
{sortable_th("Arm", "text")}{sortable_th("rl_too_high", "num")}
{sortable_th("rl_min_avg_vol", "num")}{sortable_th("rl_min_trigger_vol", "num")}
{sortable_th("N (FULL)", "num")}
</tr></thead><tbody>
<tr><td>th113 (control)</td><td>{TH13}</td><td>0 (off)</td><td>0 (off)</td><td>{by_id[TH113_ID]['m_full']['n']}</td></tr>
<tr><td>th113_vol</td><td>{TH13}</td><td>{MIN_AVG_VOL}</td><td>{MIN_TRIGGER_VOL}</td><td>{by_id[TH113_VOL_ID]['m_full']['n']}</td></tr>
<tr><td>control (too_high off)</td><td>0</td><td>0</td><td>0</td><td>{by_id[CONTROL_ID]['m_full']['n']}</td></tr>
</tbody></table></div>
</section>""",
    )
    closed = _stamp_closed_copies(packed_primary + [by_id[CONTROL_ID]], EXP2_DIR)
    write_metrics_csv(packed_html, "", EXP2_DIR / "metrics_all.csv")

    freeze = [
        f"# BASELINE — `rl_too_high_vol_fulluniv_29_40d_{STAMP}/too_high13_vol_ab`",
        "",
        "**Status:** RESEARCH only. Dual volume gate on frozen `rl_too_high=1.13`.",
        f"**Exit freeze (NEW):** `rl_exit_percent={HOUSE_EXIT_PCT}`, `rl_exit_days={HOUSE_EXIT_DAYS}`. "
        "Not gold. Not DailyRun.",
        "",
        "## Arms",
        "",
        "| Arm | Role | Knobs |",
        "|-----|------|-------|",
        f"| `th113` | **primary control** | too_high={TH13}, no vol floors |",
        f"| `th113_vol` | candidate | too_high={TH13}, "
        f"`rl_min_avg_vol={MIN_AVG_VOL}`, `rl_min_trigger_vol={MIN_TRIGGER_VOL}` |",
        "| `control` | context | too_high=0 (from Exp1) |",
        "",
        "## Volume rule (BOTH required)",
        "",
        f"- **AVG_VOL** on trigger ≥ **{MIN_AVG_VOL:,}** shares via `rl_min_avg_vol` "
        f"(window = default `rl_avg_vol_days=50`).",
        f"- **TRIGGER_VOL** (signal-bar volume) ≥ **{MIN_TRIGGER_VOL:,}** shares via "
        f"`rl_min_trigger_vol` (new research knob; default 0=off in production).",
        "",
        "## Universe / split",
        "",
        f"| Full universe | `{n_univ}` CSVs = `run_rl.bat ALL` |",
        "| Split | IS entry < 2024-01-01; OOS report-only |",
        "",
        "## Verdicts",
        "",
        f"- {_arm_verdict(TH113_VOL_ID, html_verdicts)}",
        f"- vs too_high OFF: IS `{v_off}` (context only)",
        "",
        "## Closed copies",
        "",
    ]
    for c in closed:
        freeze.append(f"- `{c.relative_to(ROOT).as_posix()}`")
    freeze.append("")
    (EXP2_DIR / "BASELINE.md").write_text("\n".join(freeze), encoding="utf-8")

    slines = [
        f"# SUMMARY — too_high13_vol_ab",
        "",
        paul,
        "",
        "## IS",
        "",
        f"- **th113 (ctrl)**: {_md_split(by_id[TH113_ID], 'm_is')}",
        f"- **th113_vol**: {_md_split(by_id[TH113_VOL_ID], 'm_is')}",
        f"- **control (off)**: {_md_split(by_id[CONTROL_ID], 'm_is')}",
        "",
        "## OOS (report-only)",
        "",
        f"- **th113 (ctrl)**: {_md_split(by_id[TH113_ID], 'm_oos')}",
        f"- **th113_vol**: {_md_split(by_id[TH113_VOL_ID], 'm_oos')}",
        f"- **control (off)**: {_md_split(by_id[CONTROL_ID], 'm_oos')}",
        "",
        f"- HTML: `{html_path.relative_to(ROOT).as_posix()}`",
        "",
    ]
    (EXP2_DIR / "SUMMARY.md").write_text("\n".join(slines), encoding="utf-8")
    return html_path, closed, {TH113_VOL_ID: verdicts[TH113_VOL_ID]["is"]}


def write_root_baseline(n_univ: int) -> None:
    text = f"""# BASELINE — `rl_too_high_vol_fulluniv_29_40d_{STAMP}`

**Status:** RESEARCH only. Not gold. Not DailyRun.

## Shared exit freeze (ALL arms — NEW)

| Knob | Value | Notes |
|------|-------|-------|
| `rl_exit_percent` | **{HOUSE_EXIT_PCT}** | +29% entry MTM (prod/`run_rl.bat` is **0.40**) |
| `rl_exit_days` | **{HOUSE_EXIT_DAYS}** | after profit gate (prod is **30**) |
| `rl_cut_the_losers` | **{HOUSE_CUT}** (OFF) | |

## Universe

Full OHLC pool = all CSVs under `data/newdata/data` (**{n_univ}**), same as `run_rl.bat ALL`.
NOT house 59, NOT tradable 764.

## Sub-experiments

1. `too_high_ab/` — control vs too_high 1.13 vs 1.14
2. `too_high13_vol_ab/` — th113 vs th113+dual volume (AVG≥10k AND TRIGGER≥5k)

## Knob mapping (plain English)

| User wording | Engine knob | Meaning |
|--------------|-------------|---------|
| too high ≥13 | `rl_too_high=1.13` | next open ≤ signal_low × 1.13 × {HOUSE_STOP} (≈{_effective_cap(TH13):.4f}× low) |
| too high ≥14 | `rl_too_high=1.14` | next open ≤ signal_low × 1.14 × {HOUSE_STOP} (≈{_effective_cap(TH14):.4f}× low) |
| AVG_VOL ≥ 10,000 | `rl_min_avg_vol=10000` | 50d avg volume on trigger ≥ 10k shares |
| TRIGGER_VOL ≥ 5,000 | `rl_min_trigger_vol=5000` | signal-bar volume ≥ 5k shares |

## Split

IS = entry_date < 2024-01-01; OOS = entry_date ≥ 2024-01-01 (report-only; no OOS retune).
"""
    (OUT_DIR / "BASELINE.md").write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument(
        "--only",
        type=str,
        default="",
        help="Comma-separated arm ids",
    )
    args = parser.parse_args()
    skip_existing = args.skip_existing or args.summarize_only

    n_univ = _count_full_univ()
    if n_univ <= 0:
        print("[RL-TH-VOL] No CSVs under data/newdata/data", flush=True)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    EXP1_DIR.mkdir(parents=True, exist_ok=True)
    EXP2_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    write_root_baseline(n_univ)

    full_syms = _full_univ_symbols()
    arms = _arm_defs(full_syms)
    if args.only.strip():
        want = {x.strip() for x in args.only.split(",") if x.strip()}
        arms = [a for a in arms if a["id"] in want]

    py = _resolve_python()
    runs: list[dict[str, Any]] = []
    t0 = time.time()

    if args.summarize_only:
        for arm in arms:
            run = _load_arm_from_disk(arm)
            print(f"[RL-TH-VOL] load {arm['id']} ok={run['ok']} n={len(run.get('trades') or [])}", flush=True)
            runs.append(run)
    else:
        print(
            f"[RL-TH-VOL] Full univ={n_univ} arms={len(arms)} jobs={args.jobs} workers={args.workers} "
            f"exit={HOUSE_EXIT_PCT}/{HOUSE_EXIT_DAYS}d",
            flush=True,
        )
        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
            futs = {ex.submit(run_live, py, arm, args.workers, skip_existing): arm for arm in arms}
            for fut in as_completed(futs):
                arm = futs[fut]
                run = fut.result()
                print(
                    f"[RL-TH-VOL] {arm['id']} ok={run['ok']} n={len(run['trades'])} "
                    f"elapsed={run.get('elapsed_s', 0):.0f}s skipped={run.get('skipped')} "
                    f"exit={run.get('exit_code')}",
                    flush=True,
                )
                runs.append(run)

    needed = {CONTROL_ID, TH113_ID, TH114_ID, TH113_VOL_ID}
    by_run = {r["arm"]["id"]: r for r in runs}
    arm_by_id = {a["id"]: a for a in _arm_defs(full_syms)}
    missing = [aid for aid in needed if aid not in by_run or not by_run[aid].get("ok")]
    if missing:
        # Try load missing from disk (e.g. --only partial)
        for aid in list(missing):
            arm = arm_by_id.get(aid)
            if arm is None:
                continue
            loaded = _load_arm_from_disk(arm)
            if loaded.get("ok"):
                by_run[aid] = loaded
                print(f"[RL-TH-VOL] recovered {aid} from disk n={len(loaded['trades'])}", flush=True)
        missing = [aid for aid in needed if aid not in by_run or not by_run[aid].get("ok")]
    if missing:
        print(f"[RL-TH-VOL] Missing/failed arms: {missing}", flush=True)
        return 1

    # Ensure arm metadata (incl. symbols) is the canonical def even if recovered.
    for aid, run in by_run.items():
        run["arm"] = arm_by_id[aid]

    packed_all = [pack_result(by_run[aid]) for aid in (CONTROL_ID, TH113_ID, TH114_ID, TH113_VOL_ID)]
    by_id = {p["arm"]["id"]: p for p in packed_all}

    html1, closed1, v1 = write_exp1(by_id)
    html2, closed2, v2 = write_exp2(by_id)
    elapsed = time.time() - t0
    print(f"[RL-TH-VOL] Wrote {html1}", flush=True)
    print(f"[RL-TH-VOL] Wrote {html2}", flush=True)
    print(f"[RL-TH-VOL] Closed copies exp1={len(closed1)} exp2={len(closed2)} total_s={elapsed:.0f}", flush=True)

    ntfy = ROOT / "tools" / "ntfy_job_done.py"
    if ntfy.is_file():
        bits = [f"{aid} IS {v[0]}" for aid, v in {**v1, **v2}.items()]
        subprocess.run(
            [
                py,
                str(ntfy),
                "--path",
                str(html1),
                "--path",
                str(html2),
                "-t",
                "RL too_high+vol fulluniv 29/40d",
                "-m",
                " · ".join(bits) + f" · univ={n_univ} · {elapsed/60:.0f}m",
            ],
            cwd=str(ROOT),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
