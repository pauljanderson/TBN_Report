#!/usr/bin/env python3
"""RL EXIT A/B: remove SMA50 envelope TARGET, test entry-MTM exits on th113_vol.

Hypothesis: SMA50 × rl_target_pct=1.20 TARGET causes long slow holds, skimpy PnL
near the envelope, and winners that would have been better taken earlier.
Disable SMA TARGET exits (rl_sma_target_off=1) while keeping rl_target_pct=1.20
for expansion-hit counting. One EXIT family per arm (not factorial-combined).

Arms (full OHLC univ, th113_vol entry freeze):
  Control: SMA TARGET ON + +29%/40d (reuse th113_vol Closed)
  hard_25: SMA OFF + hard +25% (rl_exit_percent=0.25, rl_exit_days=1)
  pct25_d30: SMA OFF + +25% then 30d
  pct20_d60: SMA OFF + +20% then 60d

Entry freeze (all arms):
  rl_too_high=1.13, rl_min_avg_vol=10000, rl_min_trigger_vol=5000,
  dip=1.055, expansion=1.163, stop=0.934, target_pct=1.20 (hits only when
  sma_target_off), cut OFF, SMA qual on, slope/ATR off.

IS = entry < 2024-01-01; OOS report-only; no OOS retune.
Research-only. Not gold. Not DailyRun.

Usage:
  python tools/rl_no_sma_target_exit_ab.py
  python tools/rl_no_sma_target_exit_ab.py --summarize-only
  python tools/rl_no_sma_target_exit_ab.py --skip-existing --jobs 3 --workers 5
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
STAMP = "20260905"
OUT_DIR = DRIVE / "paul_experiments" / f"rl_no_sma_target_exit_ab_{STAMP}"
RUNS_DIR = OUT_DIR / "runs"

CTRL_SRC = (
    DRIVE
    / "paul_experiments"
    / "rl_too_high_vol_fulluniv_29_40d_20260904"
    / "runs"
    / "th113_vol"
)

HOUSE_STOP = 0.934
HOUSE_CUT = 1000
HOUSE_DIP = 1.055
TH13 = 1.13
MIN_AVG_VOL = 10_000
MIN_TRIGGER_VOL = 5_000

CONTROL_ID = "th113_vol_sma_on_29_40d"
ARM_ORDER = {
    CONTROL_ID: 0,
    "hard_25": 1,
    "pct25_d30": 2,
    "pct20_d60": 3,
}

# User request that triggered this stamp (for report header).
REQUEST_PROMPT = """\
Can you do an AB test on the items at the end.

Remove the Moving average envelope target. I will explain in detail later. This is causing a lot of the problems that I am seeing. 1. Slower moving trades held way too long. 2. Trades that have higher entries that are closer to the target are getting sold for a low PnL and have higher Risk to reward. 3. Trades that are the highest winners do it a lot quicker than the longest holds that we have. 4. Losing trades that could have been winners if they were sold earlier.

Have more research to do, but here are the AB tests I need.

Hard 25% target
25% then 30 days
20% then 60 days

Send me closed for each and the compare report.
"""

LAYMAN_TRANSLATION = """\
We turned off the usual “sell when price hits about 20% above the 50-day moving average” exit \
(the moving-average envelope target). That rule seemed to keep slow trades open too long, \
skim profits on entries already near the line, and miss earlier sells that would have helped. \
Instead we tested three simpler profit rules vs today’s research control (envelope still on, \
plus exit after +29% and 40 days): (1) sell as soon as the trade is up 25%, (2) once up 25%, \
wait 30 more days then sell, (3) once up 20%, wait 60 more days then sell. Same entries and \
stock universe — only the sell rules change.
"""

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


def _full_univ_symbols() -> list[str]:
    if not DATA_DIR.is_dir():
        return []
    return sorted(p.stem.upper() for p in DATA_DIR.glob("*.csv"))


def _count_full_univ() -> int:
    return len(_full_univ_symbols())


def _entry_freeze_v(
    *,
    exit_pct: float,
    exit_days: int,
    sma_target_off: bool,
) -> list[str]:
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
        f"rl_sma_target_off={'1' if sma_target_off else '0'}",
        f"rl_cut_the_losers={HOUSE_CUT}",
        f"rl_exit_percent={exit_pct}",
        f"rl_exit_days={exit_days}",
        "rl_post_target_reentry_bars=0",
        f"rl_too_high={TH13}",
        f"rl_min_avg_vol={MIN_AVG_VOL}",
        f"rl_min_trigger_vol={MIN_TRIGGER_VOL}",
    ]


def _arm_defs() -> list[dict[str, Any]]:
    syms = _full_univ_symbols()
    n = len(syms)
    return [
        {
            "id": CONTROL_ID,
            "label": "Control th113_vol SMA ON +29%/40d",
            "role": "control",
            "symbols": syms,
            "univ_n": n,
            "exit_pct": 0.29,
            "exit_days": 40,
            "sma_off": False,
            "extra_v": _entry_freeze_v(exit_pct=0.29, exit_days=40, sma_target_off=False),
            "reuse": True,
        },
        {
            "id": "hard_25",
            "label": "SMA OFF + hard +25% (days=1)",
            "role": "candidate",
            "symbols": syms,
            "univ_n": n,
            "exit_pct": 0.25,
            "exit_days": 1,
            "sma_off": True,
            "extra_v": _entry_freeze_v(exit_pct=0.25, exit_days=1, sma_target_off=True),
            "reuse": False,
        },
        {
            "id": "pct25_d30",
            "label": "SMA OFF +25% then 30d",
            "role": "candidate",
            "symbols": syms,
            "univ_n": n,
            "exit_pct": 0.25,
            "exit_days": 30,
            "sma_off": True,
            "extra_v": _entry_freeze_v(exit_pct=0.25, exit_days=30, sma_target_off=True),
            "reuse": False,
        },
        {
            "id": "pct20_d60",
            "label": "SMA OFF +20% then 60d",
            "role": "candidate",
            "symbols": syms,
            "univ_n": n,
            "exit_pct": 0.20,
            "exit_days": 60,
            "sma_off": True,
            "extra_v": _entry_freeze_v(exit_pct=0.20, exit_days=60, sma_target_off=True),
            "reuse": False,
        },
    ]


def build_cmd(py: str, outdir: Path, workers: int, extra_v: list[str]) -> list[str]:
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
    for v in extra_v:
        cmd.extend(["-v", v])
    return cmd


def _copy_control_run() -> Path:
    dest = RUNS_DIR / CONTROL_ID
    dest.mkdir(parents=True, exist_ok=True)
    if not CTRL_SRC.is_dir():
        raise FileNotFoundError(f"missing control run dir: {CTRL_SRC}")
    for pat in (
        "RL_Closed_*.csv",
        "RL_Summary_*.csv",
        "RL_EquityMeta_*.csv",
        "RL_Report_*.csv",
        "RL_EquityCurve_*.csv",
    ):
        src = _find_latest(CTRL_SRC, pat)
        if src and src.is_file():
            shutil.copy2(src, dest / src.name)
    return dest


def run_live(py: str, arm: dict[str, Any], workers: int, skip_existing: bool) -> dict[str, Any]:
    arm_dir = RUNS_DIR / arm["id"]
    arm_dir.mkdir(parents=True, exist_ok=True)
    if arm.get("reuse"):
        _copy_control_run()
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
    if arm.get("reuse"):
        closed = _find_latest(arm_dir, "RL_Closed_*.csv")
        trades = load_trades(closed) if closed else []
        return {
            "arm": arm,
            "ok": len(trades) > 0,
            "skipped": True,
            "closed": closed,
            "trades": trades,
            "stamp": closed.stem.split("_")[-1] if closed else "",
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
    if arm.get("reuse") and not _find_latest(arm_dir, "RL_Closed_*.csv"):
        _copy_control_run()
    closed = _find_latest(arm_dir, "RL_Closed_*.csv")
    if not closed or not closed.is_file():
        return {"arm": arm, "ok": False, "skipped": True, "trades": [], "stamp": ""}
    trades = load_trades(closed)
    return {
        "arm": arm,
        "ok": len(trades) > 0,
        "skipped": True,
        "closed": closed,
        "trades": trades,
        "stamp": closed.stem.split("_")[-1],
        "summary": _find_latest(arm_dir, "RL_Summary_*.csv"),
        "equity_meta": _find_latest(arm_dir, "RL_EquityMeta_*.csv"),
        "report": _find_latest(arm_dir, "RL_Report_*.csv"),
    }


def _stamp_closed_copies(packed: list[dict[str, Any]]) -> list[Path]:
    closed_dir = OUT_DIR / "closed"
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


def _exit_count(p: dict[str, Any], key: str) -> int:
    return int((p["m_full"].get("exits") or {}).get(key, 0))


def _md_split(p: dict[str, Any], key: str) -> str:
    m = p[key]
    return (
        f"N={m['n']} WR={m['wr']:.1f}% Avg={m['avg_pnl']:.2f}% WO_MAX={m['wo_max']:.2f}% "
        f"PF={m['pf']:.2f} AnnROR={fmt_n(m['ann_ror'], 2)} MaxDD_overlay={fmt_n(m['max_dd'], 2)} "
        f"avg_days={m.get('avg_days', 0):.1f}"
    )


def _arm_verdict(aid: str, verdicts: dict[str, dict[str, tuple[str, str]]]) -> str:
    vis, nis = verdicts[aid]["is"]
    voos, noos = verdicts[aid]["oos"]
    if vis in ("KEEP", "LEAN KEEP") and voos in ("KEEP", "LEAN KEEP", "HOLD"):
        tag = vis if voos != "DISMISS" else "HOLD (OOS soft)"
        return f"**`{aid}` {tag}** IS `{vis}` ({nis}); OOS `{voos}` ({noos}). Research candidate != gold."
    if vis == "DISMISS":
        return f"**`{aid}` DISMISS** IS `{vis}` ({nis}); OOS `{voos}` ({noos})."
    return f"**`{aid}` HOLD** IS `{vis}` ({nis}); OOS `{voos}` ({noos})."


def write_compare_html(
    packed: list[dict[str, Any]],
    verdicts: dict[str, dict[str, tuple[str, str]]],
    *,
    paul_note: str,
) -> Path:
    by_id = {p["arm"]["id"]: p for p in packed}
    baseline = by_id[CONTROL_ID]
    th_std = "".join(
        sortable_th(a, b)
        for a, b in filter_html_compare_columns(
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
    )
    sections = []
    for split_key, split_title in (("m_is", "IS"), ("m_oos", "OOS (report-only)"), ("m_full", "FULL book")):
        body = "".join(compare_row(p, split_key, baseline, "", CONTROL_ID) for p in packed)
        note = (
            "Paul/FIT/UW from host Summary + EquityMeta. Sharpe from host EquityCurve. "
            "Overlay Max DD ≠ host DD."
            if split_key == "m_full"
            else "Closed overlay $47,500 / $500k. Sharpe from host EquityCurve calendar slice. "
            "Overlay Max DD ≠ host account DD."
        )
        sections.append(
            f'<section><h2>No-SMA-target exit AB — {split_title}</h2>'
            f'<p class="muted">Δ vs control (SMA TARGET ON +29%/40d). {note} Click column headers to sort.</p>'
            f'<div class="table-wrap"><table class="sortable"><thead><tr>{th_std}</tr></thead>'
            f"<tbody>{body}</tbody></table></div></section>"
        )

    arm_th = "".join(
        sortable_th(a, b)
        for a, b in (
            ("Arm", "text"),
            ("SMA tgt", "text"),
            ("exit%", "num"),
            ("days", "num"),
            ("TARGET exits", "num"),
            ("RL_EXIT exits", "num"),
            ("STOP exits", "num"),
            ("Avg days", "num"),
            ("N full", "num"),
        )
    )
    arm_rows = []
    for p in packed:
        arm = p["arm"]
        arm_rows.append(
            "<tr>"
            f"<td>{html_mod.escape(arm['id'])}</td>"
            f"<td>{'OFF' if arm.get('sma_off') else 'ON'}</td>"
            f"<td>{arm.get('exit_pct')}</td>"
            f"<td>{arm.get('exit_days')}</td>"
            f"<td>{_exit_count(p, 'TARGET')}</td>"
            f"<td>{_exit_count(p, 'RL_EXIT_DAYS')}</td>"
            f"<td>{_exit_count(p, 'STOP_LOSS') + _exit_count(p, 'GAP_DOWN')}</td>"
            f"<td>{p['m_full'].get('avg_days', 0):.1f}</td>"
            f"<td>{p['m_full']['n']}</td>"
            "</tr>"
        )
    exit_mix = (
        f'<section><h2>Arm knobs + exit mix (FULL)</h2>'
        f'<p class="muted">TARGET should be ~0 on SMA-OFF arms. Click headers to sort.</p>'
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{arm_th}</tr></thead>'
        f"<tbody>{''.join(arm_rows)}</tbody></table></div></section>"
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
    cand_ids = [a["id"] for a in _arm_defs() if a["id"] != CONTROL_ID]
    pairs = [(f"{cid} − {CONTROL_ID}", by_id[CONTROL_ID], by_id[cid]) for cid in cand_ids if cid in by_id]
    pw_sections = []
    for split_key, split_title in (("m_is", "IS"), ("m_oos", "OOS"), ("m_full", "FULL")):
        rows = "".join(pairwise_delta_row(a, b, split_key, lbl) for lbl, a, b in pairs)
        pw_sections.append(
            f'<section><h2>Pairwise deltas — {split_title}</h2>'
            f'<p class="muted">Click headers to sort.</p>'
            f'<div class="table-wrap"><table class="sortable"><thead><tr>{pw_th}</tr></thead>'
            f"<tbody>{rows}</tbody></table></div></section>"
        )

    n_univ = _count_full_univ()
    subtitle = (
        f"Stamp <code>rl_no_sma_target_exit_ab_{STAMP}</code>. "
        f"SMA50 envelope TARGET off on candidates (<code>rl_sma_target_off=1</code>); "
        f"<code>rl_target_pct=1.20</code> still counts expansion hits. "
        f"Entry freeze: too_high={TH13}, AVG_VOL≥{MIN_AVG_VOL:,}, TRIGGER_VOL≥{MIN_TRIGGER_VOL:,}. "
        f"Universe: full OHLC ({n_univ}). Not gold / not DailyRun."
    )
    verdict_lis = "".join(f"<li>{_arm_verdict(cid, verdicts)}</li>" for cid in cand_ids if cid in verdicts)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RL no-SMA-target exit AB — {STAMP}</title>
<style>
:root {{ --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#9aa7b8; --line:#2a3545; --accent:#5b9fd4; --ctrl:#243044; }}
*{{box-sizing:border-box}}
body{{margin:0;font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.45}}
header{{padding:1.25rem 1rem 0.5rem;max-width:1400px;margin:0 auto}}
h1{{font-size:1.35rem;margin:0 0 .35rem}}
h2{{font-size:1.05rem;margin:1.25rem 0 .4rem;color:var(--accent)}}
.muted{{color:var(--muted);font-size:.92rem}}
.callout{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.75rem 1rem;margin:.75rem 0}}
.req pre{{white-space:pre-wrap;font-family:ui-monospace,Consolas,monospace;font-size:.82rem;margin:.4rem 0 0;color:var(--text)}}
.req .layman{{margin:.55rem 0 0;font-size:.95rem}}
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
<h1>RL no-SMA-target exit AB (hard 25% / 25%→30d / 20%→60d)</h1>
<p class="muted">{subtitle}</p>
</header>
<main>
<div class="callout req">
<strong>What you asked</strong>
<pre>{html_mod.escape(REQUEST_PROMPT.strip())}</pre>
<p class="layman"><strong>In plain English:</strong> {html_mod.escape(LAYMAN_TRANSLATION.strip())}</p>
</div>
<div class="callout">
<strong>Paul note:</strong> {html_mod.escape(paul_note)}
<ul>{verdict_lis}</ul>
</div>
{exit_mix}
{"".join(sections)}
{"".join(pw_sections)}
</main>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    out_path = OUT_DIR / "compare.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path


def write_docs(
    packed: list[dict[str, Any]],
    verdicts: dict[str, dict[str, tuple[str, str]]],
    closed: list[Path],
    html_path: Path,
) -> None:
    by_id = {p["arm"]["id"]: p for p in packed}
    n_univ = _count_full_univ()
    cand_ids = [a for a in ARM_ORDER if a != CONTROL_ID]
    baseline = [
        f"# BASELINE — `rl_no_sma_target_exit_ab_{STAMP}`",
        "",
        "**Status:** RESEARCH only. SMA50 envelope TARGET off on candidates; entry-MTM exit arms.",
        "**Control:** th113_vol + SMA TARGET ON + `rl_exit_percent=0.29` / `rl_exit_days=40` (reuse).",
        "Not gold. Not DailyRun. Prod remains +40%/30d with SMA target on.",
        "",
        "## What you asked",
        "",
        "```",
        REQUEST_PROMPT.strip(),
        "```",
        "",
        "## In plain English",
        "",
        LAYMAN_TRANSLATION.strip(),
        "",
        "## Entry freeze (identical all arms)",
        "",
        "| Knob | Value |",
        "|------|-------|",
        f"| `rl_too_high` | **{TH13}** |",
        f"| `rl_min_avg_vol` | **{MIN_AVG_VOL}** |",
        f"| `rl_min_trigger_vol` | **{MIN_TRIGGER_VOL}** |",
        f"| `rl_dip_pct` | **{HOUSE_DIP}** |",
        "| `rl_expansion` | **1.163** |",
        f"| `rl_stop_pct` | **{HOUSE_STOP}** |",
        "| `rl_target_pct` | **1.20** (expansion hits; EXIT only when sma_target_off=0) |",
        f"| `rl_cut_the_losers` | **{HOUSE_CUT}** (off) |",
        "",
        "## EXIT arms",
        "",
        "| Arm | sma_target_off | exit% | days | Notes |",
        "|-----|----------------|-------|------|-------|",
        f"| `{CONTROL_ID}` | 0 (ON) | 0.29 | 40 | reuse th113_vol |",
        "| `hard_25` | 1 (OFF) | 0.25 | 1 | same-bar hard exit at +25% |",
        "| `pct25_d30` | 1 (OFF) | 0.25 | 30 | +25% then 30d |",
        "| `pct20_d60` | 1 (OFF) | 0.20 | 60 | +20% then 60d |",
        "",
        "## Universe / split",
        "",
        f"- Full OHLC pool under `data/newdata/data` (**{n_univ}**), same as `run_rl.bat ALL`",
        "- IS = entry < 2024-01-01; OOS report-only; no OOS retune",
        "",
        "## Results",
        "",
        "| Arm | Stamp | N_full | TARGET exits | OK |",
        "|-----|-------|--------|--------------|-----|",
    ]
    for p in packed:
        arm = p["arm"]
        baseline.append(
            f"| `{arm['id']}` | `{p.get('stamp','')}` | {p['m_full']['n']} | "
            f"{_exit_count(p, 'TARGET')} | {'yes' if p.get('ok') else 'no'} |"
        )
    baseline.extend(["", "## Verdict", ""])
    for cid in cand_ids:
        if cid in verdicts:
            baseline.append(f"- {_arm_verdict(cid, verdicts)}")
    baseline.extend(
        [
            "",
            "## Selection-bias note",
            "",
            "Three a-priori arms from Paul's no-envelope research ask (hard 25%, 25%→30d, 20%→60d).",
            "Not tuned on OOS. Judge quality (WR/Avg/PF) first; hold-days is the claimed mechanism.",
            "",
            "## Closed copies",
            "",
        ]
    )
    for c in closed:
        baseline.append(f"- `{c.relative_to(ROOT).as_posix()}`")
    baseline.append("")
    (OUT_DIR / "BASELINE.md").write_text("\n".join(baseline), encoding="utf-8")

    summary = [
        f"# SUMMARY — `rl_no_sma_target_exit_ab_{STAMP}`",
        "",
    ]
    for cid in cand_ids:
        if cid in verdicts:
            summary.append(f"- {_arm_verdict(cid, verdicts)}")
    summary.extend(["", "## IS", ""])
    for aid in ARM_ORDER:
        if aid in by_id:
            summary.append(f"- **{aid}**: {_md_split(by_id[aid], 'm_is')}")
    summary.extend(["", "## OOS (report-only)", ""])
    for aid in ARM_ORDER:
        if aid in by_id:
            summary.append(f"- **{aid}**: {_md_split(by_id[aid], 'm_oos')}")
    summary.extend(["", f"- HTML: `{html_path.relative_to(ROOT).as_posix()}`", ""])
    (OUT_DIR / "SUMMARY.md").write_text("\n".join(summary), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summarize-only", action="store_true")
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--jobs", type=int, default=3, help="Parallel live arms (control is reuse)")
    args = ap.parse_args()

    n_univ = _count_full_univ()
    if n_univ <= 0:
        print("[NO-SMA-EXIT] No CSVs under data/newdata/data", flush=True)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    arms = _arm_defs()
    py = _resolve_python()
    t0 = time.time()
    runs: list[dict[str, Any]] = []

    if args.summarize_only:
        for arm in arms:
            run = _load_arm_from_disk(arm)
            print(
                f"[NO-SMA-EXIT] load {arm['id']} ok={run['ok']} n={len(run.get('trades') or [])}",
                flush=True,
            )
            runs.append(run)
    else:
        print(
            f"[NO-SMA-EXIT] Full univ={n_univ} workers={args.workers} jobs={args.jobs}",
            flush=True,
        )
        # Control first (reuse), then live candidates in parallel.
        ctrl = next(a for a in arms if a["id"] == CONTROL_ID)
        live = [a for a in arms if a["id"] != CONTROL_ID]
        ctrl_run = run_live(py, ctrl, args.workers, args.skip_existing)
        print(
            f"[NO-SMA-EXIT] {ctrl['id']} ok={ctrl_run['ok']} n={len(ctrl_run.get('trades') or [])} "
            f"skipped={ctrl_run.get('skipped')}",
            flush=True,
        )
        runs.append(ctrl_run)

        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
            futs = {
                ex.submit(run_live, py, arm, args.workers, args.skip_existing): arm for arm in live
            }
            for fut in as_completed(futs):
                arm = futs[fut]
                run = fut.result()
                print(
                    f"[NO-SMA-EXIT] {arm['id']} ok={run['ok']} n={len(run.get('trades') or [])} "
                    f"elapsed={run.get('elapsed_s', 0):.0f}s skipped={run.get('skipped')} "
                    f"exit={run.get('exit_code')}",
                    flush=True,
                )
                runs.append(run)

    by_run = {r["arm"]["id"]: r for r in runs}
    ordered_ids = list(ARM_ORDER.keys())
    missing = [aid for aid in ordered_ids if aid not in by_run or not by_run[aid].get("ok")]
    if missing:
        print(f"[NO-SMA-EXIT] Missing/failed arms: {missing}", flush=True)
        return 1

    packed = [pack_result(by_run[aid]) for aid in ordered_ids]
    by_id = {p["arm"]["id"]: p for p in packed}
    control = by_id[CONTROL_ID]
    verdicts: dict[str, dict[str, tuple[str, str]]] = {}
    for cid in ordered_ids:
        if cid == CONTROL_ID:
            continue
        verdicts[cid] = {
            "is": verdict_vs_control(by_id[cid], control, "m_is"),
            "oos": verdict_vs_control(by_id[cid], control, "m_oos"),
        }
    paul_note = (
        "SMA50 envelope TARGET removed on candidates; entry-MTM exits only "
        "(hard +25% / +25%→30d / +20%→60d) vs th113_vol control with SMA ON +29%/40d. "
        "Research-only."
    )
    html_path = write_compare_html(packed, verdicts, paul_note=paul_note)
    closed = _stamp_closed_copies(packed)
    write_metrics_csv(packed, "", OUT_DIR / "metrics_all.csv")
    write_docs(packed, verdicts, closed, html_path)
    elapsed = time.time() - t0
    print(f"[NO-SMA-EXIT] Wrote {html_path}", flush=True)
    print(f"[NO-SMA-EXIT] Closed copies={len(closed)} total_s={elapsed:.0f}", flush=True)
    for cid in verdicts:
        print(f"[NO-SMA-EXIT] {_arm_verdict(cid, verdicts)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
