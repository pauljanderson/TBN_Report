#!/usr/bin/env python3
"""RL slope-gate A/B on tradable 764 tape (ENTRY).

Evidence: ImprovePriority 260828112205 shallow_entry_sma50_fail (dip tighten
HOLD/DISMISS) and false_start_2022_2023. Leftover lever: require SMA50 slope.

One ENTRY knob: turn on `rl_slope_threshold` (30-bar SMA50 rise).
Prod freeze is 0 = filter off. Do not move dip / cut_the_losers / sma_qual.

Control: 0 (off) reuse tradable Closed 260828112205.
Candidates (pre-agreed, not a grid): 0.05 and 0.0643 (config default).

Research-only. Not gold. Not DailyRun. Do not overwrite RL_universe.csv.

Usage:
  python tools/rl_slope_gate_ab.py
  python tools/rl_slope_gate_ab.py --summarize-only
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
STAMP = "20260828"
OUT_DIR = DRIVE / "paul_experiments" / f"rl_slope_gate_tradable_{STAMP}"
CONTROL_SRC = (
    DRIVE / "paul_experiments" / "rl_tradable_2010_adv2m_20260828" / "runs" / "tradable"
)
UNIVERSE_CSV = DRIVE / "universes" / "VZ_tradable_2010_adv2m_universe.csv"
CONTROL_ID = "control"
CANDIDATES = ("slope05", "slope064")

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

ARM_ORDER = {"control": 0, "slope05": 1, "slope064": 2}


def build_cmd(py: str, outdir: Path, workers: int, symbols: str, extra_v: list[str]) -> list[str]:
    cmd = _lists_build_cmd(py, outdir, workers, symbols)
    out: list[str] = []
    i = 0
    while i < len(cmd):
        if cmd[i] == "-v" and i + 1 < len(cmd) and cmd[i + 1].startswith("rl_slope_threshold="):
            i += 2
            continue
        out.append(cmd[i])
        i += 1
    for v in extra_v:
        out.extend(["-v", v])
    return out


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
    # PO 2026-08-28: dismiss both (including house LEAN KEEP on 0.05). Freeze stays 0.
    _ = verdicts
    return (
        "**DISMISS** both. PO call 2026-08-28: do not adopt the slope gate. "
        "House auto LEAN KEEP on 0.05 was a tiny IS Avg lift (+0.12) that did not survive OOS "
        "(HOLD: Avg 3.77→3.70, AnnROR 31.7→31.5) and host DD worsened 17.72→18.26. "
        "0.0643 DISMISS (overlay DD 37.7→42.2). Freeze stays `rl_slope_threshold=0`. "
        "Do not search 0.08. Do not pile slope onto dip."
    )


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
            else "Closed overlay $47,500 / $500k. Overlay Max DD ≠ host account DD."
        )
        sections.append(
            f'<section><h2>Slope gate — {title}</h2>'
            f'<p class="muted">Δ vs control (rl_slope_threshold=0, off). {note} Click column headers to sort.</p>'
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
        ("0.05 − control", by_id[CONTROL_ID], by_id["slope05"]),
        ("0.0643 − control", by_id[CONTROL_ID], by_id["slope064"]),
        ("0.0643 − 0.05", by_id["slope05"], by_id["slope064"]),
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
        exit_rows.append(
            "<tr>"
            f"<td>{html_mod.escape(p['arm']['label'])}</td>"
            f"<td>{ex.get('TARGET', 0)} ({100*ex.get('TARGET',0)/tot:.1f}%)</td>"
            f"<td>{ex.get('STOP_LOSS', 0)} ({100*ex.get('STOP_LOSS',0)/tot:.1f}%)</td>"
            f"<td>{p['m_full']['n']}</td>"
            f"<td>{_host_dd(p)}</td>"
            "</tr>"
        )
    v_lis = []
    for aid in CANDIDATES:
        vis, nis = verdicts[aid]["is"]
        voos, noos = verdicts[aid]["oos"]
        v_lis.append(
            f"<li><strong>{html_mod.escape(aid)}</strong> IS: {html_mod.escape(vis)} "
            f"({html_mod.escape(nis)}); OOS: {html_mod.escape(voos)} ({html_mod.escape(noos)})</li>"
        )
    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RL slope gate A/B — tradable {STAMP}</title>
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
<h1>RL slope gate — tradable 764 (ENTRY)</h1>
<p class="muted">Stamp <code>rl_slope_gate_tradable_{STAMP}</code>. One knob: <code>rl_slope_threshold</code>
(0 → 0.05 / 0.0643). 30-bar SMA50 rise. Freeze: dip=1.055, stop=0.934, target=1.20, trails off.
Not gold / not DailyRun. IS = entry &lt; 2024-01-01; OOS report-only. Click column headers to sort.</p>
</header>
<main>
<div class="callout">
<strong>Evidence:</strong> ImprovePriority <code>260828112205</code> <em>shallow_entry_sma50_fail</em>
(dip tighten did not KEEP) and <em>false_start_2022_2023</em>.
Hypothesis: requiring a rising 50-SMA (30-bar) drops weak-slope false starts and lifts IS quality
even if N falls. Pre-agreed: <strong>0.05</strong> (5%/30d) and <strong>0.0643</strong> (config default)
vs control <strong>0</strong> (off). Do not A/B cut_the_losers on this stamp.
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
{sortable_th("N", "num")}{sortable_th("Host Max DD%", "num")}
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
    hyp = f"""# HYPOTHESIS — RL slope gate (ENTRY)

| Field | Fill in |
|-------|---------|
| System / prefix | RL |
| Baseline stamp | tradable Closed `260828112205` (`rl_slope_threshold=0`) |
| Universe | tradable 2010 / ADV$2m (764) |
| **Evidence** | ImprovePriority `260828112205` **shallow_entry_sma50_fail** (dip HOLD/DISMISS) + **false_start_2022_2023** |
| **Hypothesis** | Requiring 30-bar SMA50 rise filters weak-slope dips and lifts IS quality without collapsing N |
| **Single knob** | `rl_slope_threshold` on vs off (ENTRY) |
| Frozen settings | dip=1.055, expansion=1.163, stop=0.934, target=1.20, trails off, bars=0 |
| Alternatives | control **0** (off); **0.05**; **0.0643**. Not 0.08. Not cut_the_losers on this stamp |
| **Decision** | (fill after compare) |

OOS report-only. Do not retune. Research-only ≠ gold ≠ DailyRun.
"""
    hyp = hyp.replace("| **Decision** | (fill after compare) |", f"| **Decision** | {_decision(verdicts)} |")
    (OUT_DIR / "HYPOTHESIS.md").write_text(hyp, encoding="utf-8")
    lines = [
        f"# BASELINE — `rl_slope_gate_tradable_{STAMP}`",
        "",
        "**Status:** RESEARCH only. One ENTRY knob (slope).",
        "",
        "| Field | Value |",
        "|---|---|",
        "| Universe | tradable 2010 / ADV$2m (764) |",
        "| Control | reuse `RL_Closed_260828112205` (`rl_slope_threshold=0`) |",
        "| Candidates | 0.05 (5%/30d); 0.0643 (config default) |",
        "| Frozen | dip=1.055, stop=0.934, target=1.20, trails off |",
        "| Split | IS entry < 2024-01-01; OOS report-only |",
        "",
        "| Arm | Stamp | N_full | Host Max DD% | OK |",
        "|-----|-------|--------|---------------|-----|",
    ]
    for p in packed:
        lines.append(
            f"| `{p['arm']['id']}` | `{p.get('stamp','')}` | {p['m_full']['n']} | "
            f"{_host_dd(p)} | {'yes' if p.get('ok') else 'no'} |"
        )
    lines.extend(["", "## Verdicts", ""])
    for aid in CANDIDATES:
        vis, nis = verdicts[aid]["is"]
        voos, noos = verdicts[aid]["oos"]
        lines.append(f"- **{aid}** IS `{vis}` ({nis}); OOS `{voos}` ({noos})")
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    slines = [
        f"# SUMMARY — `rl_slope_gate_tradable_{STAMP}`",
        "",
        "Slope gate (`rl_slope_threshold` 0.05 / 0.0643 vs 0) on tradable 764. ENTRY. Research only.",
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
        slines.append(f"- **{aid}**: {_host_dd(by_id[aid])}%")
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
    write_compare_html(packed, verdicts)
    write_metrics_csv(packed, "", OUT_DIR / "metrics_all.csv")
    write_docs(packed, verdicts)
    print(f"[RL-SG] Wrote {OUT_DIR / 'compare.html'}", flush=True)
    return {"verdicts": verdicts, "packed": packed}


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
        print("[RL-SG] Missing tradable universe", flush=True)
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    arms = [
        {
            "id": "control",
            "label": "Control (slope off)",
            "role": "control",
            "symbols": trad,
            "extra_v": ["rl_slope_threshold=0"],
            "live": False,
        },
        {
            "id": "slope05",
            "label": "slope=0.05 (5%/30d)",
            "role": "candidate",
            "symbols": trad,
            "extra_v": ["rl_slope_threshold=0.05"],
            "live": True,
        },
        {
            "id": "slope064",
            "label": "slope=0.0643 (config default)",
            "role": "candidate",
            "symbols": trad,
            "extra_v": ["rl_slope_threshold=0.0643"],
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
                print(f"[RL-SG] Missing Closed for {arm['id']}", flush=True)
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
            f"[RL-SG] control reuse ok={ctrl_run['ok']} n={len(ctrl_run['trades'])} stamp={ctrl_run.get('stamp')}",
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
                    f"[RL-SG] {arm['id']} ok={run['ok']} n={len(run['trades'])} "
                    f"elapsed={run.get('elapsed_s', 0):.0f}s skipped={run.get('skipped')}",
                    flush=True,
                )
                runs.append(run)

    runs.sort(key=lambda r: ARM_ORDER.get(r["arm"]["id"], 99))
    if not all(r.get("ok") for r in runs):
        print("[RL-SG] One or more arms failed", flush=True)
        for r in runs:
            print(f"  {r['arm']['id']}: ok={r.get('ok')} exit={r.get('exit_code')}", flush=True)
        return 1

    packed = [pack_result(r) for r in runs]
    result = summarize(packed)
    ntfy = ROOT / "tools" / "ntfy_job_done.py"
    if ntfy.is_file():
        a = next(p for p in packed if p["arm"]["id"] == "slope05")
        b = next(p for p in packed if p["arm"]["id"] == "slope064")
        subprocess.run(
            [
                py,
                str(ntfy),
                "--path",
                str(OUT_DIR / "compare.html"),
                "-t",
                "RL slope gate tradable",
                "-m",
                (
                    f"0.05 IS {result['verdicts']['slope05']['is'][0]} "
                    f"Avg={a['m_is']['avg_pnl']:.2f}% N={a['m_is']['n']} · "
                    f"0.0643 IS {result['verdicts']['slope064']['is'][0]} "
                    f"Avg={b['m_is']['avg_pnl']:.2f}%"
                ),
            ],
            cwd=str(ROOT),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
