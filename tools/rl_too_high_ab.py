#!/usr/bin/env python3
"""RL too-high fill gate A/B — one knob vs frozen control (tradable 764).

Paul: cut-the-losers OFF for entire test; sweep rl_too_high only.

Control: rl_too_high=0 (off), rl_cut_the_losers=1000 (off).
Candidates: rl_too_high in {1.10, 1.12, 1.14, 1.16} (AWK/optimizer neighborhood).
Fill gate when on: next_open <= signal_low × rl_too_high × rl_stop_pct (0.934).

House freeze otherwise: dip=1.055, expansion=1.163, stop=0.934, target=1.20,
trails off, flush=0, exit_days=10000, cut=1000 (all arms).

IS = entry < 2024-01-01; OOS report-only; no OOS retune.
Research-only. Not gold. Not DailyRun. All arms full reruns (prior control had cut=0.25).

Usage:
  python tools/rl_too_high_ab.py
  python tools/rl_too_high_ab.py --summarize-only
  python tools/rl_too_high_ab.py --skip-existing --jobs 3 --workers 12
"""
from __future__ import annotations

import argparse
import html as html_mod
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
STAMP = "20260831"
OUT_DIR = DRIVE / "paul_experiments" / f"rl_too_high_ab_{STAMP}"
UNIVERSE_CSV = DRIVE / "universes" / "VZ_tradable_2010_adv2m_universe.csv"
CONTROL_ID = "control"

HOUSE_STOP = 0.934
HOUSE_CUT = 1000  # off
TOO_HIGH_LEVELS = (1.10, 1.12, 1.14, 1.16)

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

ARM_ORDER = {"control": 0, "th110": 1, "th112": 2, "th114": 3, "th116": 4}


def _effective_cap(th: float) -> float:
    return th * HOUSE_STOP


def _arm_defs(trad: list[str]) -> list[dict[str, Any]]:
    arms: list[dict[str, Any]] = [
        {
            "id": CONTROL_ID,
            "label": "Control (too_high=0 off, cut off)",
            "role": "control",
            "symbols": trad,
            "extra_v": ["rl_too_high=0", f"rl_cut_the_losers={HOUSE_CUT}"],
        },
    ]
    for th in TOO_HIGH_LEVELS:
        cap = _effective_cap(th)
        aid = f"th{int(round(th * 100)):03d}"  # th110, th112, ...
        arms.append(
            {
                "id": aid,
                "label": f"too_high={th:.2f} (cap≈{cap:.3f}× low)",
                "role": "candidate",
                "symbols": trad,
                "too_high": th,
                "effective_cap": cap,
                "extra_v": [f"rl_too_high={th}", f"rl_cut_the_losers={HOUSE_CUT}"],
            }
        )
    return arms


def build_cmd(py: str, outdir: Path, workers: int, symbols: str, extra_v: list[str]) -> list[str]:
    cmd = _lists_build_cmd(py, outdir, workers, symbols)
    out: list[str] = []
    i = 0
    while i < len(cmd):
        if cmd[i] == "-v" and i + 1 < len(cmd) and (
            cmd[i + 1].startswith("rl_too_high=") or cmd[i + 1].startswith("rl_cut_the_losers=")
        ):
            i += 2
            continue
        out.append(cmd[i])
        i += 1
    for v in extra_v:
        out.extend(["-v", v])
    return out


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


def _best_candidate(packed: list[dict[str, Any]], verdicts: dict[str, dict[str, tuple[str, str]]]) -> str:
    """Plain-English pick for Paul — quality over N."""
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
        th = best["arm"].get("too_high", "?")
        return (
            f"No arm earns KEEP/LEAN KEEP vs control (cut OFF). Best IS Avg% is "
            f"**too_high={th}** ({best['m_is']['avg_pnl']:.2f}%, N={best['m_is']['n']}) "
            f"but verdict is {verdicts[best['arm']['id']]['is'][0]} — **stay off (0)** for prod."
        )
    winners.sort(key=lambda p: (p["m_is"]["avg_pnl"], p["m_is"]["pf"]), reverse=True)
    best = winners[0]
    th = best["arm"].get("too_high")
    return (
        f"With cut-the-losers OFF everywhere, **`rl_too_high={th}`** looks best on IS quality "
        f"(Avg={best['m_is']['avg_pnl']:.2f}%, PF={best['m_is']['pf']:.2f}, N={best['m_is']['n']}). "
        f"Verdict {verdicts[best['arm']['id']]['is'][0]} IS / {verdicts[best['arm']['id']]['oos'][0]} OOS. "
        f"Research-only until wider confirm."
    )


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
    th = "".join(sortable_th(a, b) for a, b in th_cols)
    sections = []
    for split_key, title in (("m_is", "IS"), ("m_oos", "OOS (report-only)"), ("m_full", "FULL book")):
        body = "".join(compare_row(p, split_key, baseline, "", CONTROL_ID) for p in packed)
        note = (
            "Paul/FIT/UW from host Summary + EquityMeta. Sharpe from host EquityCurve "
            "(Equity_Regular when present; IS/OOS = calendar slices). Overlay Max DD ≠ host DD."
            if split_key == "m_full"
            else "Closed overlay $47,500 / $500k. Sharpe from host EquityCurve calendar slice. "
            "Overlay Max DD ≠ host account DD."
        )
        sections.append(
            f'<section><h2>Too-high fill gate — {title}</h2>'
            f'<p class="muted">Δ vs control (too_high=0, cut off). {note} Click column headers to sort.</p>'
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
    pairs = [(f"{aid} − control", by_id[CONTROL_ID], by_id[aid]) for aid in cand_ids]
    pw_sections = []
    for split_key, title in (("m_is", "IS"), ("m_oos", "OOS"), ("m_full", "FULL")):
        rows = "".join(pairwise_delta_row(a, b, split_key, lbl) for lbl, a, b in pairs)
        pw_sections.append(
            f'<section><h2>Pairwise deltas — {title}</h2>'
            f'<p class="muted">One knob only. Click headers to sort.</p>'
            f'<div class="table-wrap"><table class="sortable"><thead><tr>{pw_th}</tr></thead>'
            f"<tbody>{rows}</tbody></table></div></section>"
        )

    gate_rows = []
    for p in packed:
        arm = p["arm"]
        th_val = arm.get("too_high", 0)
        cap = arm.get("effective_cap") if th_val else None
        gate_rows.append(
            "<tr>"
            f"<td>{html_mod.escape(arm['label'])}</td>"
            f"<td>{th_val if th_val else '0 (off)'}</td>"
            f"<td>{HOUSE_STOP}</td>"
            f"<td>{fmt_n(cap, 4) if cap else '—'}</td>"
            f"<td>{p['m_full']['n']}</td>"
            f"<td>{_host_dd(p)}</td>"
            "</tr>"
        )

    v_lis = [f"<li>{_arm_verdict(aid, verdicts)}</li>" for aid in cand_ids]
    paul_note = html_mod.escape(_best_candidate(packed, verdicts))

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RL too_high A/B — tradable {STAMP}</title>
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
<h1>RL too_high fill gate — tradable 764 (ENTRY fill filter)</h1>
<p class="muted">Stamp <code>rl_too_high_ab_{STAMP}</code>. One knob: <code>rl_too_high</code>.
<strong>Cut-the-losers OFF (1000) on every arm</strong> per Paul — prior RL ABs had cut=0.25 on control; all arms re-run.
Fill gate when on: next_open ≤ signal_low × too_high × stop_pct ({HOUSE_STOP}).
Freeze: dip=1.055, expansion=1.163, target=1.20, trails off, flush=0, exit_days=10000.
Not gold / not DailyRun. IS = entry &lt; 2024-01-01; OOS report-only. Click column headers to sort.</p>
</header>
<main>
<div class="callout">
<strong>Paul note:</strong> {paul_note}
<ul>{"".join(v_lis)}</ul>
</div>
{"".join(sections)}
{"".join(pw_sections)}
<section>
<h2>Fill gate levels (effective cap vs signal low)</h2>
<p class="muted">Effective cap = rl_too_high × rl_stop_pct. Historical prod/optimizer used 1.14 (~1.065× low). Click column headers to sort.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>
{sortable_th("Arm", "text")}{sortable_th("rl_too_high", "num")}{sortable_th("rl_stop_pct", "num")}
{sortable_th("Effective cap×low", "num")}{sortable_th("N (FULL)", "num")}{sortable_th("Host Max DD%", "num")}
</tr></thead><tbody>{"".join(gate_rows)}</tbody></table></div>
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

    cap_lines = [
        f"| {th:.2f} | {th} × {HOUSE_STOP} = **{_effective_cap(th):.4f}×** low |"
        for th in TOO_HIGH_LEVELS
    ]
    freeze_lines = [
        f"# BASELINE — `rl_too_high_ab_{STAMP}`",
        "",
        "**Status:** RESEARCH only. One ENTRY fill-gate knob (`rl_too_high`) vs control.",
        "**Cut-the-losers OFF (1000) on every arm** — dropped per Paul; do not compare to prior cut=0.25 control.",
        "Not gold. Not DailyRun.",
        "",
        "## House freeze (identical except rl_too_high)",
        "",
        "| Knob | Value | Notes |",
        "|------|-------|-------|",
        "| `rl_dip_pct` | **1.055** | |",
        "| `rl_expansion` | **1.163** | |",
        f"| `rl_stop_pct` | **{HOUSE_STOP}** | |",
        "| `rl_target_pct` | **1.20** | |",
        "| trails | **off** | |",
        "| `rl_flush_days` | **0** (off) | not in this stamp |",
        "| `rl_exit_days` | **10000** (off) | not in this stamp |",
        f"| `rl_cut_the_losers` | **{HOUSE_CUT}** (off) | **all arms** — Paul drop cut |",
        "| `rl_too_high` | **0** on control | candidates sweep only |",
        "| cash | **$47,500** | |",
        "",
        "## Fill gate (when too_high > 0)",
        "",
        "`next_open <= signal_low × rl_too_high × rl_stop_pct`",
        "",
        "| rl_too_high | Effective cap vs signal low |",
        "|-------------|----------------------------|",
        "| 0 | off (no gate) |",
        *cap_lines,
        "",
        "## Universe / split",
        "",
        "| Field | Value |",
        "|---|---|",
        "| Universe | tradable 2010 / ADV$2m (**764**) — `VZ_tradable_2010_adv2m_universe.csv` |",
        "| Reruns | **All arms live** — prior stamps had cut=0.25 on control |",
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
        freeze_lines.append(
            f"| `{arm['id']}` | {th if th else '0 (off)'} | {cap} | "
            f"`{p.get('stamp','')}` | {p['m_full']['n']} | {_host_dd(p)} | "
            f"{'yes' if p.get('ok') else 'no'} |"
        )
    freeze_lines.extend(["", "## Verdicts (vs control, quality over N)", ""])
    for aid in cand_ids:
        freeze_lines.append(f"- {_arm_verdict(aid, verdicts)}")
    freeze_lines.extend(
        [
            "",
            "## Selection-bias note",
            "",
            "Arms pre-agreed (1.10–1.16 neighborhood). Do not pick a level after seeing OOS.",
            "Cut-the-losers is frozen OFF — not re-tested here.",
            "",
        ]
    )
    (OUT_DIR / "BASELINE.md").write_text("\n".join(freeze_lines), encoding="utf-8")

    slines = [
        f"# SUMMARY — `rl_too_high_ab_{STAMP}`",
        "",
        "RL too_high fill gate A/B on tradable 764. Cut-the-losers OFF everywhere. Research only.",
        "",
        "## Plain English (Paul)",
        "",
        _best_candidate(packed, verdicts),
        "",
        "- **Control** = too_high off (0), cut off (1000). Baseline for this stamp.",
        "- **Candidates** = reject fills when next open gaps above signal_low × too_high × stop.",
        "- **Cut is OFF for the entire test** — not comparing cut=0.25 prior control.",
        "",
        "## IS",
        "",
    ]
    for aid in [CONTROL_ID, *cand_ids]:
        slines.append(f"- **{aid}**: {_md_split(by_id[aid], 'm_is')}")
    slines.extend(["", "## OOS (report-only)", ""])
    for aid in [CONTROL_ID, *cand_ids]:
        slines.append(f"- **{aid}**: {_md_split(by_id[aid], 'm_oos')}")
    slines.extend(["", "## Host Max DD (FULL)", ""])
    for aid in [CONTROL_ID, *cand_ids]:
        slines.append(f"- **{aid}**: {_host_dd(by_id[aid])}%")
    slines.extend(["", "## Verdicts", ""])
    for aid in cand_ids:
        slines.append(f"- {_arm_verdict(aid, verdicts)}")
    slines.extend(
        [
            "",
            "## Paths",
            "",
            f"- HTML: `drive/paul_experiments/rl_too_high_ab_{STAMP}/compare.html`",
            f"- BASELINE: `drive/paul_experiments/rl_too_high_ab_{STAMP}/BASELINE.md`",
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
    print(f"[RL-TH] Wrote {OUT_DIR / 'compare.html'}", flush=True)
    return {"verdicts": verdicts, "packed": packed}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument(
        "--only",
        type=str,
        default="",
        help="Comma-separated arm ids (control always included for compare)",
    )
    args = parser.parse_args()
    skip_existing = args.skip_existing or args.summarize_only

    trad = load_universe_symbols(UNIVERSE_CSV)
    if not trad:
        print("[RL-TH] Missing tradable universe", flush=True)
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    arms = _arm_defs(trad)
    if args.only.strip():
        want = {x.strip() for x in args.only.split(",") if x.strip()}
        want.add(CONTROL_ID)
        arms = [a for a in arms if a["id"] in want]

    py = _resolve_python()
    runs: list[dict[str, Any]] = []

    if args.summarize_only:
        for arm in arms:
            run = _load_arm_from_disk(arm)
            print(f"[RL-TH] load {arm['id']} ok={run['ok']} n={len(run.get('trades') or [])}", flush=True)
            runs.append(run)
    else:
        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
            futs = {ex.submit(run_live, py, arm, args.workers, skip_existing): arm for arm in arms}
            for fut in as_completed(futs):
                arm = futs[fut]
                run = fut.result()
                print(
                    f"[RL-TH] {arm['id']} ok={run['ok']} n={len(run['trades'])} "
                    f"elapsed={run.get('elapsed_s', 0):.0f}s skipped={run.get('skipped')} "
                    f"exit={run.get('exit_code')}",
                    flush=True,
                )
                runs.append(run)

    runs.sort(key=lambda r: ARM_ORDER.get(r["arm"]["id"], 99))
    if not all(r.get("ok") for r in runs):
        print("[RL-TH] One or more arms failed", flush=True)
        for r in runs:
            print(f"  {r['arm']['id']}: ok={r.get('ok')} exit={r.get('exit_code')}", flush=True)
        ok_runs = [r for r in runs if r.get("ok")]
        if not any(r["arm"]["id"] == CONTROL_ID for r in ok_runs) or len(ok_runs) < 2:
            return 1
        runs = ok_runs

    packed = [pack_result(r) for r in runs]
    result = summarize(packed)

    ntfy = ROOT / "tools" / "ntfy_job_done.py"
    if ntfy.is_file():
        bits = [f"{aid} IS {v['is'][0]}" for aid, v in result["verdicts"].items()]
        subprocess.run(
            [
                py,
                str(ntfy),
                "--path",
                str(OUT_DIR / "compare.html"),
                "-t",
                "RL too_high AB (cut off)",
                "-m",
                " · ".join(bits) + " · cut OFF all arms",
            ],
            cwd=str(ROOT),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
