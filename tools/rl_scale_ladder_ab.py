#!/usr/bin/env python3
"""RL scale-out + stop-ratchet ladder A/B on tradable 764.

Not a combinatorial search. Two frozen recipes vs control (partial/trails off).

User sketch (two-step):
  +10% sell 20% of original, stop → BE
  +20% sell 30% of original, stop → +5%

Three-step adds:
  +30% sell 25% of original, stop → +10%

SMA target stays 1.20 on the stub. Stop starts at 0.934. Trails off.

Control: reuse tradable Closed 260828112205.
Research-only. Not gold. Not DailyRun.

Usage:
  python tools/rl_scale_ladder_ab.py
  python tools/rl_scale_ladder_ab.py --summarize-only
"""
from __future__ import annotations

import argparse
import csv
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
STAMP = "20260828"
OUT_DIR = DRIVE / "paul_experiments" / f"rl_scale_ladder_tradable_{STAMP}"
CONTROL_SRC = (
    DRIVE / "paul_experiments" / "rl_tradable_2010_adv2m_20260828" / "runs" / "tradable"
)
UNIVERSE_CSV = DRIVE / "universes" / "VZ_tradable_2010_adv2m_universe.csv"
CONTROL_ID = "control"
CANDIDATES = ("two", "three")
LADDER_TWO = "0.10:0.20:0|0.20:0.30:0.05"
LADDER_THREE = "0.10:0.20:0|0.20:0.30:0.05|0.30:0.25:0.10"

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

ARM_ORDER = {"control": 0, "two": 1, "three": 2}


def build_cmd(py: str, outdir: Path, workers: int, symbols: str, extra_v: list[str]) -> list[str]:
    cmd = _lists_build_cmd(py, outdir, workers, symbols)
    for v in extra_v:
        cmd.extend(["-v", v])
    return cmd


def copy_control(arm: dict[str, Any]) -> dict[str, Any]:
    src = CONTROL_SRC
    closed = _find_latest(src, "RL_Closed_*.csv")
    if not closed:
        return {"arm": arm, "ok": False, "skipped": True, "trades": [], "stamp": "", "closed": None}
    dest = OUT_DIR / "runs" / arm["id"]
    dest.mkdir(parents=True, exist_ok=True)
    stamp = closed.stem.split("_")[-1]
    for pattern in (
        f"RL_Closed_{stamp}.csv",
        f"RL_Summary_{stamp}.csv",
        f"RL_EquityMeta_{stamp}.csv",
        f"RL_Report_{stamp}.csv",
    ):
        f = src / pattern
        if f.is_file():
            shutil.copy2(f, dest / f.name)
    trades = load_trades(closed)
    return {
        "arm": arm,
        "ok": len(trades) > 0,
        "skipped": True,
        "closed": dest / closed.name if (dest / closed.name).is_file() else closed,
        "trades": trades,
        "stamp": stamp,
        "summary": _find_latest(dest, "RL_Summary_*.csv") or _find_latest(src, "RL_Summary_*.csv"),
        "equity_meta": _find_latest(dest, "RL_EquityMeta_*.csv") or _find_latest(src, "RL_EquityMeta_*.csv"),
        "report": _find_latest(dest, "RL_Report_*.csv") or _find_latest(src, "RL_Report_*.csv"),
        "elapsed_s": 0.0,
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


def count_partials(closed: Path | None) -> int:
    if not closed or not closed.is_file():
        return 0
    n = 0
    with closed.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            v = (raw.get("PARTIAL_DATE") or "").strip()
            if v and v.upper() not in ("N/A", "NONE", "0"):
                n += 1
    return n


def _md_split(p: dict[str, Any], key: str) -> str:
    m = p[key]
    return (
        f"N={m['n']} WR={m['wr']:.1f}% Avg={m['avg_pnl']:.2f}% WO_MAX={m['wo_max']:.2f}% "
        f"PF={m['pf']:.2f} AnnROR={fmt_n(m['ann_ror'], 2)} MaxDD_overlay={fmt_n(m['max_dd'], 2)}"
    )


def _host_dd(p: dict[str, Any]) -> str:
    eq = p.get("eq_meta") or {}
    return fmt_n(eq.get("eq_dd"), 2)


def _decision(verdicts: dict[str, dict[str, tuple[str, str]]]) -> str:
    vis_a, vis_b = verdicts["two"]["is"][0], verdicts["three"]["is"][0]
    voos_a, voos_b = verdicts["two"]["oos"][0], verdicts["three"]["oos"][0]
    keepish = {"KEEP", "LEAN KEEP"}
    if vis_a not in keepish and vis_b not in keepish:
        return (
            f"**DISMISS** both. IS two={vis_a}; three={vis_b}. "
            f"OOS report-only two={voos_a}; three={voos_b}. Do not combinatorial-search the steps."
        )
    if (vis_a in keepish and voos_a == "DISMISS") or (vis_b in keepish and voos_b == "DISMISS"):
        return (
            f"**HOLD**. IS two={vis_a}; three={vis_b} but OOS two={voos_a}; three={voos_b}. "
            "Do not retune OOS. Research-only."
        )
    return (
        f"IS two={vis_a}; three={vis_b}. OOS report-only two={voos_a}; three={voos_b}. "
        "Research candidate ≠ gold ≠ DailyRun."
    )


def write_compare_html(
    packed: list[dict[str, Any]],
    verdicts: dict[str, dict[str, tuple[str, str]]],
    n_partial: dict[str, int],
) -> Path:
    by_id = {p["arm"]["id"]: p for p in packed}
    baseline = by_id[CONTROL_ID]
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
            "Host Sharpe/UW from EquityMeta. Overlay Max DD can exceed 100%; use host DD below."
            if split_key == "m_full"
            else "Closed overlay $47,500 / $500k. Overlay Max DD ≠ host account DD."
        )
        sections.append(
            f'<section><h2>Scale ladder — {title}</h2>'
            f'<p class="muted">Δ vs control (ladder off). {note} Click column headers to sort.</p>'
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
    pairs = [
        ("two − control", by_id[CONTROL_ID], by_id["two"]),
        ("three − control", by_id[CONTROL_ID], by_id["three"]),
        ("three − two", by_id["two"], by_id["three"]),
    ]
    pw_sections = []
    for split_key, title in (("m_is", "IS"), ("m_oos", "OOS"), ("m_full", "FULL")):
        rows = "".join(pairwise_delta_row(a, b, split_key, lbl) for lbl, a, b in pairs)
        pw_sections.append(
            f'<section><h2>Pairwise deltas — {title}</h2>'
            f'<div class="table-wrap"><table class="sortable"><thead><tr>{pw_th}</tr></thead>'
            f"<tbody>{rows}</tbody></table></div></section>"
        )
    exit_rows = []
    for p in packed:
        ex = p["m_full"]["exits"]
        tot = max(p["m_full"]["n"], 1)
        aid = p["arm"]["id"]
        exit_rows.append(
            "<tr>"
            f"<td>{html_mod.escape(p['arm']['label'])}</td>"
            f"<td>{ex.get('TARGET', 0)} ({100*ex.get('TARGET',0)/tot:.1f}%)</td>"
            f"<td>{ex.get('STOP_LOSS', 0)} ({100*ex.get('STOP_LOSS',0)/tot:.1f}%)</td>"
            f"<td>{ex.get('TRAIL_STOP', 0)}</td>"
            f"<td>{ex.get('TRAIL_STOP2', 0)}</td>"
            f"<td>{p['m_full']['n']}</td>"
            f"<td>{n_partial.get(aid, 0)}</td>"
            f"<td>{_host_dd(p)}</td>"
            "</tr>"
        )
    v_lis = []
    for aid in CANDIDATES:
        vis, nis = verdicts[aid]["is"]
        voos, noos = verdicts[aid]["oos"]
        v_lis.append(
            f"<li><strong>{html_mod.escape(aid)}</strong> IS: {html_mod.escape(vis)} "
            f"({html_mod.escape(nis)}); OOS: {html_mod.escape(voos)} ({html_mod.escape(noos)}); "
            f"PARTIAL_DATE rows={n_partial.get(aid, 0)}</li>"
        )
    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RL scale ladder A/B — tradable {STAMP}</title>
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
<h1>RL scale-out + stop ratchet — tradable 764</h1>
<p class="muted">Stamp <code>rl_scale_ladder_tradable_{STAMP}</code>. Two frozen ladders, not a search grid.
Freeze: dip=1.055, stop=0.934, SMA target=1.20, trails off. Not gold / not DailyRun.
IS = entry &lt; 2024-01-01; OOS report-only. Click column headers to sort.</p>
</header>
<main>
<div class="callout">
<strong>Hypothesis:</strong> scale-out and stop-move work together — bank slices as MTM prints,
ratchet the stub stop (BE then +5%, optional +10%). SMA target stays 1.20 on the remainder.
<pre style="white-space:pre-wrap">two:   {html_mod.escape(LADDER_TWO)}
three: {html_mod.escape(LADDER_THREE)}</pre>
<ul>{"".join(v_lis)}</ul>
<p>{html_mod.escape(_decision(verdicts))}</p>
</div>
{"".join(sections)}
{"".join(pw_sections)}
<section>
<h2>Exit mix (FULL) + host Max DD</h2>
<p class="muted">Host Max DD = EquityMeta passive. Click column headers to sort.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>
{sortable_th("Arm", "text")}{sortable_th("TARGET", "text")}{sortable_th("STOP_LOSS", "text")}
{sortable_th("TRAIL_STOP", "num")}{sortable_th("TRAIL_STOP2", "num")}{sortable_th("N", "num")}
{sortable_th("PARTIAL rows", "num")}{sortable_th("Host Max DD%", "num")}
</tr></thead><tbody>{"".join(exit_rows)}</tbody></table></div>
</section>
</main>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    path = OUT_DIR / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def write_docs(
    packed: list[dict[str, Any]],
    verdicts: dict[str, dict[str, tuple[str, str]]],
    n_partial: dict[str, int],
) -> None:
    by_id = {p["arm"]["id"]: p for p in packed}
    hyp = f"""# HYPOTHESIS — RL scale-out + stop ratchet

| Field | Fill in |
|-------|---------|
| System / prefix | RL |
| Baseline stamp | tradable Closed `260828112205` (ladder off) |
| Universe | tradable 2010 / ADV$2m (764) |
| **Evidence** | Partial-only DISMISS on Avg (capped winners); Trail-1 BE DISMISS; leftover-run still real |
| **Hypothesis** | Scale-out and stop-move together: bank slices as MTM prints, ratchet stub stop, keep SMA target 1.20 |
| **Single knob** | `rl_scale_ladder` on vs off. Two frozen recipes, **not** a combinatorial grid |
| Frozen settings | dip=1.055, expansion=1.163, stop=0.934, SMA target=1.20, trails off, single partial off |
| Alternatives | control off; **two** `{LADDER_TWO}`; **three** `{LADDER_THREE}` |
| **Decision** | (fill after compare) |

OOS report-only. Research-only ≠ gold ≠ DailyRun.
"""
    hyp = hyp.replace("| **Decision** | (fill after compare) |", f"| **Decision** | {_decision(verdicts)} |")
    (OUT_DIR / "HYPOTHESIS.md").write_text(hyp, encoding="utf-8")
    lines = [
        f"# BASELINE — `rl_scale_ladder_tradable_{STAMP}`",
        "",
        "**Status:** RESEARCH only. Two frozen ladders (not a search grid).",
        "",
        "| Field | Value |",
        "|---|---|",
        "| Universe | tradable 2010 / ADV$2m (764) |",
        "| Control | reuse `RL_Closed_260828112205` |",
        f"| two | `{LADDER_TWO}` |",
        f"| three | `{LADDER_THREE}` |",
        "| Frozen | dip=1.055, stop=0.934, SMA target 1.20, trails off |",
        "| Split | IS entry < 2024-01-01; OOS report-only |",
        "",
        "| Arm | Stamp | N_full | PARTIAL rows | Host Max DD% | OK |",
        "|-----|-------|--------|--------------|---------------|-----|",
    ]
    for p in packed:
        aid = p["arm"]["id"]
        lines.append(
            f"| `{aid}` | `{p.get('stamp','')}` | {p['m_full']['n']} | "
            f"{n_partial.get(aid, 0)} | {_host_dd(p)} | {'yes' if p.get('ok') else 'no'} |"
        )
    lines.extend(["", "## Verdicts", ""])
    for aid in CANDIDATES:
        vis, nis = verdicts[aid]["is"]
        voos, noos = verdicts[aid]["oos"]
        lines.append(f"- **{aid}** IS `{vis}` ({nis}); OOS `{voos}` ({noos})")
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    slines = [
        f"# SUMMARY — `rl_scale_ladder_tradable_{STAMP}`",
        "",
        "Scale-out + stop ratchet on tradable 764. Two frozen recipes. Research only.",
        "",
        "## IS",
        "",
    ]
    for aid in ("control", *CANDIDATES):
        slines.append(f"- **{aid}**: {_md_split(by_id[aid], 'm_is')}")
    slines.extend(["", "## OOS (report-only)", ""])
    for aid in ("control", *CANDIDATES):
        slines.append(f"- **{aid}**: {_md_split(by_id[aid], 'm_oos')}")
    slines.extend(["", "## Host Max DD (EquityMeta passive)", ""])
    for aid in ("control", *CANDIDATES):
        slines.append(f"- **{aid}**: {_host_dd(by_id[aid])}%  PARTIAL rows={n_partial.get(aid, 0)}")
    slines.extend(["", "## Verdicts", ""])
    for aid in CANDIDATES:
        vis, nis = verdicts[aid]["is"]
        voos, noos = verdicts[aid]["oos"]
        slines.append(f"- **{aid}** IS `{vis}` ({nis}); OOS `{voos}` ({noos})")
    (OUT_DIR / "SUMMARY.md").write_text("\n".join(slines) + "\n", encoding="utf-8")


def summarize(packed: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {p["arm"]["id"]: p for p in packed}
    control = by_id[CONTROL_ID]
    verdicts = {
        aid: {
            "is": verdict_vs_control(by_id[aid], control, "m_is"),
            "oos": verdict_vs_control(by_id[aid], control, "m_oos"),
        }
        for aid in CANDIDATES
    }
    n_partial = {p["arm"]["id"]: count_partials(p.get("closed")) for p in packed}
    write_compare_html(packed, verdicts, n_partial)
    write_metrics_csv(packed, "", OUT_DIR / "metrics_all.csv")
    write_docs(packed, verdicts, n_partial)
    print(f"[RL-SL] Wrote {OUT_DIR / 'compare.html'} partials={n_partial}", flush=True)
    return {"verdicts": verdicts, "packed": packed, "n_partial": n_partial}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    skip_existing = args.skip_existing or args.summarize_only

    trad = load_universe_symbols(UNIVERSE_CSV)
    if not trad:
        print("[RL-SL] Missing tradable universe", flush=True)
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    arms = [
        {
            "id": "control",
            "label": "Control (ladder off)",
            "role": "control",
            "symbols": trad,
            "extra_v": [],
            "live": False,
        },
        {
            "id": "two",
            "label": "Two-step (10%/20%→BE, 20%/30%→+5%)",
            "role": "candidate",
            "symbols": trad,
            "extra_v": [f"rl_scale_ladder={LADDER_TWO}"],
            "live": True,
        },
        {
            "id": "three",
            "label": "Three-step (+30%/25%→+10%)",
            "role": "candidate",
            "symbols": trad,
            "extra_v": [f"rl_scale_ladder={LADDER_THREE}"],
            "live": True,
        },
    ]
    py = _resolve_python()
    runs: list[dict[str, Any]] = []
    if args.summarize_only:
        for arm in arms:
            arm_dir = OUT_DIR / "runs" / arm["id"]
            src = CONTROL_SRC if arm["id"] == CONTROL_ID else arm_dir
            closed = _find_latest(arm_dir, "RL_Closed_*.csv") or _find_latest(src, "RL_Closed_*.csv")
            if not closed:
                print(f"[RL-SL] Missing Closed for {arm['id']}", flush=True)
                return 1
            trades = load_trades(closed)
            runs.append(
                {
                    "arm": arm,
                    "ok": len(trades) > 0,
                    "skipped": True,
                    "closed": closed,
                    "trades": trades,
                    "stamp": closed.stem.split("_")[-1],
                    "summary": _find_latest(arm_dir, "RL_Summary_*.csv") or _find_latest(src, "RL_Summary_*.csv"),
                    "equity_meta": _find_latest(arm_dir, "RL_EquityMeta_*.csv")
                    or _find_latest(src, "RL_EquityMeta_*.csv"),
                    "report": _find_latest(arm_dir, "RL_Report_*.csv") or _find_latest(src, "RL_Report_*.csv"),
                }
            )
    else:
        ctrl_run = copy_control(arms[0])
        print(
            f"[RL-SL] control reuse ok={ctrl_run['ok']} n={len(ctrl_run['trades'])} stamp={ctrl_run.get('stamp')}",
            flush=True,
        )
        runs.append(ctrl_run)
        live = [a for a in arms if a.get("live")]
        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
            futs = {ex.submit(run_live, py, arm, args.workers, skip_existing): arm for arm in live}
            for fut in as_completed(futs):
                arm = futs[fut]
                run = fut.result()
                print(
                    f"[RL-SL] {arm['id']} ok={run['ok']} n={len(run['trades'])} "
                    f"elapsed={run.get('elapsed_s', 0):.0f}s skipped={run.get('skipped')}",
                    flush=True,
                )
                runs.append(run)

    runs.sort(key=lambda r: ARM_ORDER.get(r["arm"]["id"], 99))
    if not all(r.get("ok") for r in runs):
        print("[RL-SL] One or more arms failed", flush=True)
        for r in runs:
            print(f"  {r['arm']['id']}: ok={r.get('ok')} exit={r.get('exit_code')}", flush=True)
        return 1

    packed = [pack_result(r) for r in runs]
    result = summarize(packed)
    ntfy = ROOT / "tools" / "ntfy_job_done.py"
    if ntfy.is_file():
        a = next(p for p in packed if p["arm"]["id"] == "two")
        b = next(p for p in packed if p["arm"]["id"] == "three")
        subprocess.run(
            [
                py,
                str(ntfy),
                "--path",
                str(OUT_DIR / "compare.html"),
                "-t",
                "RL scale ladder tradable",
                "-m",
                (
                    f"two IS {result['verdicts']['two']['is'][0]} "
                    f"Avg={a['m_is']['avg_pnl']:.2f}% AnnROR={a['m_is']['ann_ror']:.1f} · "
                    f"three IS {result['verdicts']['three']['is'][0]} "
                    f"Avg={b['m_is']['avg_pnl']:.2f}%"
                ),
            ],
            cwd=str(ROOT),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
