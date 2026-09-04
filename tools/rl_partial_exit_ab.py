#!/usr/bin/env python3
"""RL partial-exit A/B on tradable 764 tape.

Evidence: target-expand leftover-run (64% of TARGETs continued ≥5% / 15d) but
raising rl_target_pct DISMISS'd on WR / host DD / OOS AnnROR.

One EXIT feature: scale out 50% at +20% from entry, remainder target =
entry × 1.30 (partial_exit_target=0.20 + follow=0.10). SMA50 × 1.20 frozen
after the partial. Stop stays 0.934. Trails off.

Control: partial off (reuse tradable Closed 260828112205).
Not gold. Not DailyRun. Do not overwrite RL_universe.csv.

Usage:
  python tools/rl_partial_exit_ab.py
  python tools/rl_partial_exit_ab.py --summarize-only
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
STAMP = "20260828"
OUT_DIR = DRIVE / "paul_experiments" / f"rl_partial_exit_tradable_{STAMP}"
CONTROL_SRC = (
    DRIVE / "paul_experiments" / "rl_tradable_2010_adv2m_20260828" / "runs" / "tradable"
)
UNIVERSE_CSV = DRIVE / "universes" / "VZ_tradable_2010_adv2m_universe.csv"
CONTROL_ID = "control"
CANDIDATES = ("partial",)

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

ARM_ORDER = {"control": 0, "partial": 1}

PARTIAL_V = [
    "rl_partial_exit_target=0.20",
    "rl_partial_exit_percent=0.50",
    "rl_partial_exit_follow_target=0.10",
]


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
            v = (raw.get("PARTIAL_DATE") or raw.get("partial_date") or "").strip()
            if v and v.upper() not in ("", "N/A", "NONE", "0"):
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
    dd = eq.get("eq_dd")
    return fmt_n(dd, 2) if dd is not None else "—"


def _decision(verdicts: dict[str, dict[str, tuple[str, str]]]) -> str:
    vis, voos = verdicts["partial"]["is"][0], verdicts["partial"]["oos"][0]
    keepish = {"KEEP", "LEAN KEEP"}
    if vis not in keepish:
        return (
            f"**DISMISS**. IS did not beat partial-off ({vis}). OOS report-only ({voos}). "
            "Stop stays 0.934. Target SMA stays 1.20. Do not turn trails on. Do not retune."
        )
    if voos == "DISMISS":
        return (
            f"**HOLD**. IS {vis} but OOS softened ({voos}). Do not retune OOS. Research-only."
        )
    return (
        f"IS {vis}. OOS report-only {voos}. Research candidate ≠ gold ≠ DailyRun. "
        "Stop stays 0.934."
    )


def write_compare_html(
    packed: list[dict[str, Any]],
    verdicts: dict[str, dict[str, tuple[str, str]]],
    n_partial: int,
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
            "Paul/FIT/Sharpe/UW from host Summary + EquityMeta (full history only). "
            "Max DD column is Closed overlay (can exceed 100% if equity goes negative); "
            "use host EquityMeta for live-arm DD."
            if split_key == "m_full"
            else "Closed overlay at $47,500 cash / $500k initial. Overlay Max DD ≠ host account DD."
        )
        sections.append(
            f'<section><h2>Partial scale-out — {title}</h2>'
            f'<p class="muted">Δ vs control (partial off). {note} Click column headers to sort.</p>'
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
    pairs = [("partial − control", by_id[CONTROL_ID], by_id["partial"])]
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
            f"<td>{ex.get('GAP_DOWN', 0)}</td>"
            f"<td>{ex.get('GAP_UP', 0)}</td>"
            f"<td>{ex.get('TIME', 0)}</td>"
            f"<td>{p['m_full']['n']}</td>"
            f"<td>{_host_dd(p)}</td>"
            "</tr>"
        )
    vis, nis = verdicts["partial"]["is"]
    voos, noos = verdicts["partial"]["oos"]
    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RL partial scale-out A/B — tradable {STAMP}</title>
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
<h1>RL partial scale-out — tradable 764</h1>
<p class="muted">Stamp <code>rl_partial_exit_tradable_{STAMP}</code>. One feature: 50% off at +20% from entry,
remainder target = entry × 1.30. Freeze: dip=1.055, expansion=1.163, <strong>stop=0.934</strong>,
SMA target=1.20 until partial, trails off. Not gold / not DailyRun.
IS = entry &lt; 2024-01-01; OOS report-only. Click column headers to sort.</p>
</header>
<main>
<div class="callout">
<strong>Evidence:</strong> leftover-run after TARGET, but raising <code>rl_target_pct</code> DISMISS'd.
Hypothesis: bank half at +20% from entry and let the stub run to +30% from entry — without putting
full size on a higher hard target.
Pre-agreed: <code>rl_partial_exit_target=0.20</code>, percent=0.50, follow=0.10. Trails stay off.
Candidate Closed had <strong>{n_partial}</strong> trades with a PARTIAL_DATE.
<ul><li><strong>partial</strong> IS: {html_mod.escape(vis)} ({html_mod.escape(nis)});
OOS: {html_mod.escape(voos)} ({html_mod.escape(noos)})</li></ul>
<p>{html_mod.escape(_decision(verdicts))}</p>
</div>
{"".join(sections)}
{"".join(pw_sections)}
<section>
<h2>Exit mix (FULL) + host Max DD</h2>
<p class="muted">Host Max DD is EquityMeta passive (engine $500k sim). Click column headers to sort.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>
{sortable_th("Arm", "text")}{sortable_th("TARGET", "text")}{sortable_th("STOP_LOSS", "text")}
{sortable_th("GAP_DOWN", "num")}{sortable_th("GAP_UP", "num")}{sortable_th("TIME", "num")}
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


def write_docs(
    packed: list[dict[str, Any]],
    verdicts: dict[str, dict[str, tuple[str, str]]],
    n_partial: int,
) -> None:
    by_id = {p["arm"]["id"]: p for p in packed}
    hyp = f"""# HYPOTHESIS — RL partial scale-out on tradable tape

| Field | Fill in |
|-------|---------|
| System / prefix | RL |
| Baseline stamp | tradable Closed `260828112205` (partial off) |
| Universe | tradable 2010 / ADV$2m (764) |
| **Evidence** | Target-expand leftover-run (64% of TARGETs continued) but `rl_target_pct` 1.25/1.30 DISMISS (WR/host DD/OOS AnnROR) |
| **Hypothesis** | Scaling out 50% at +20% from entry and letting the remainder run to entry×1.30 captures leftover run without putting full size on a higher hard target |
| **Single knob** | Partial-on (AWK `PARTIAL_EXIT_*` bundle) vs off. Not trails. Not a higher `rl_target_pct` |
| Frozen settings | dip=1.055, expansion=1.163, **stop=0.934**, SMA `rl_target_pct=1.20` until partial, trails off, post-TARGET bars=0 |
| Alternatives | control **off**; **on** (`target=0.20`, `percent=0.50`, `follow=0.10`) |
| **Decision** | (fill after compare) |

Python now applies the remainder target (previously sold the slice but left SMA50×1.20 live). OOS report-only. Research-only ≠ gold ≠ DailyRun.
"""
    hyp = hyp.replace("| **Decision** | (fill after compare) |", f"| **Decision** | {_decision(verdicts)} |")
    (OUT_DIR / "HYPOTHESIS.md").write_text(hyp, encoding="utf-8")
    lines = [
        f"# BASELINE — `rl_partial_exit_tradable_{STAMP}`",
        "",
        "**Status:** RESEARCH only. Not gold. Not DailyRun. One feature (partial scale-out).",
        "",
        "| Field | Value |",
        "|---|---|",
        "| Universe | tradable 2010 / ADV$2m (764) |",
        "| Control | reuse `RL_Closed_260828112205` (partial off) |",
        "| Candidate | 50% at +20% from entry; remainder entry×1.30 |",
        "| Frozen | dip=1.055, expansion=1.163, **stop=0.934**, SMA target 1.20 until partial, trails off |",
        "| Split | IS entry < 2024-01-01; OOS report-only |",
        f"| Partials fired | {n_partial} (candidate Closed PARTIAL_DATE) |",
        "",
        "Do **not** retune on OOS. Do **not** enable trails. Do **not** raise `rl_target_pct`.",
        "",
        "| Arm | Stamp | N_full | Host Max DD% | OK |",
        "|-----|-------|--------|---------------|-----|",
    ]
    for p in packed:
        lines.append(
            f"| `{p['arm']['id']}` | `{p.get('stamp','')}` | {p['m_full']['n']} | "
            f"{_host_dd(p)} | {'yes' if p.get('ok') else 'no'} |"
        )
    vis, nis = verdicts["partial"]["is"]
    voos, noos = verdicts["partial"]["oos"]
    lines.extend(
        [
            "",
            "## Verdicts",
            "",
            f"- **partial** IS `{vis}` ({nis}); OOS `{voos}` ({noos})",
            "",
        ]
    )
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines), encoding="utf-8")
    slines = [
        f"# SUMMARY — `rl_partial_exit_tradable_{STAMP}`",
        "",
        "Partial scale-out (50% at +20% from entry, remainder entry×1.30) on tradable 764. "
        f"Stop 0.934. {n_partial} Closed rows with PARTIAL_DATE. Research only.",
        "",
        "## IS",
        "",
    ]
    for aid in ("control", "partial"):
        slines.append(f"- **{aid}**: {_md_split(by_id[aid], 'm_is')}")
    slines.extend(["", "## OOS (report-only)", ""])
    for aid in ("control", "partial"):
        slines.append(f"- **{aid}**: {_md_split(by_id[aid], 'm_oos')}")
    slines.extend(
        [
            "",
            "## Host Max DD (EquityMeta passive)",
            "",
            f"- **control**: {_host_dd(by_id['control'])}%",
            f"- **partial**: {_host_dd(by_id['partial'])}%",
            "",
            "## Verdicts",
            "",
            f"- **partial** IS `{vis}` ({nis}); OOS `{voos}` ({noos})",
            "",
        ]
    )
    (OUT_DIR / "SUMMARY.md").write_text("\n".join(slines), encoding="utf-8")


def summarize(packed: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {p["arm"]["id"]: p for p in packed}
    control = by_id[CONTROL_ID]
    verdicts = {
        "partial": {
            "is": verdict_vs_control(by_id["partial"], control, "m_is"),
            "oos": verdict_vs_control(by_id["partial"], control, "m_oos"),
        }
    }
    n_partial = count_partials(by_id["partial"].get("closed"))
    write_compare_html(packed, verdicts, n_partial)
    write_metrics_csv(packed, "", OUT_DIR / "metrics_all.csv")
    write_docs(packed, verdicts, n_partial)
    print(f"[RL-PX] Wrote {OUT_DIR / 'compare.html'} partials={n_partial}", flush=True)
    return {"verdicts": verdicts, "packed": packed, "n_partial": n_partial}


def _arm_result_from_disk(arm: dict[str, Any], src: Path, arm_dir: Path) -> dict[str, Any]:
    closed = _find_latest(arm_dir, "RL_Closed_*.csv") or _find_latest(src, "RL_Closed_*.csv")
    trades = load_trades(closed) if closed else []
    return {
        "arm": arm,
        "ok": len(trades) > 0,
        "skipped": True,
        "closed": closed,
        "trades": trades,
        "stamp": closed.stem.split("_")[-1] if closed else "",
        "summary": _find_latest(arm_dir, "RL_Summary_*.csv") or _find_latest(src, "RL_Summary_*.csv"),
        "equity_meta": _find_latest(arm_dir, "RL_EquityMeta_*.csv")
        or _find_latest(src, "RL_EquityMeta_*.csv"),
        "report": _find_latest(arm_dir, "RL_Report_*.csv") or _find_latest(src, "RL_Report_*.csv"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    skip_existing = args.skip_existing or args.summarize_only

    trad = load_universe_symbols(UNIVERSE_CSV)
    if not trad:
        print("[RL-PX] Missing tradable universe", flush=True)
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    arms = [
        {
            "id": "control",
            "label": "Control (partial off)",
            "role": "control",
            "symbols": trad,
            "extra_v": [],
            "live": False,
        },
        {
            "id": "partial",
            "label": "Partial 50% @ +20%, rest entry×1.30",
            "role": "candidate",
            "symbols": trad,
            "extra_v": list(PARTIAL_V),
            "live": True,
        },
    ]
    py = _resolve_python()
    runs: list[dict[str, Any]] = []
    if args.summarize_only:
        for arm in arms:
            arm_dir = OUT_DIR / "runs" / arm["id"]
            src = CONTROL_SRC if arm["id"] == CONTROL_ID else arm_dir
            run = _arm_result_from_disk(arm, src, arm_dir)
            if not run["ok"]:
                print(f"[RL-PX] Missing Closed for {arm['id']}", flush=True)
                return 1
            runs.append(run)
    else:
        ctrl_run = copy_control(arms[0])
        print(
            f"[RL-PX] control reuse ok={ctrl_run['ok']} n={len(ctrl_run['trades'])} stamp={ctrl_run.get('stamp')}",
            flush=True,
        )
        runs.append(ctrl_run)
        live = next(a for a in arms if a.get("live"))
        run = run_live(py, live, args.workers, skip_existing)
        print(
            f"[RL-PX] {live['id']} ok={run['ok']} n={len(run['trades'])} "
            f"elapsed={run.get('elapsed_s', 0):.0f}s skipped={run.get('skipped')}",
            flush=True,
        )
        runs.append(run)

    runs.sort(key=lambda r: ARM_ORDER.get(r["arm"]["id"], 99))
    if not all(r.get("ok") for r in runs):
        print("[RL-PX] One or more arms failed", flush=True)
        for r in runs:
            print(f"  {r['arm']['id']}: ok={r.get('ok')} exit={r.get('exit_code')}", flush=True)
        return 1

    packed = [pack_result(r) for r in runs]
    result = summarize(packed)
    ntfy = ROOT / "tools" / "ntfy_job_done.py"
    if ntfy.is_file():
        cand = next(p for p in packed if p["arm"]["id"] == "partial")
        subprocess.run(
            [
                py,
                str(ntfy),
                "--path",
                str(OUT_DIR / "compare.html"),
                "-t",
                "RL partial scale-out tradable",
                "-m",
                (
                    f"IS {result['verdicts']['partial']['is'][0]} "
                    f"Avg={cand['m_is']['avg_pnl']:.2f}% AnnROR={cand['m_is']['ann_ror']:.1f} "
                    f"partials={result['n_partial']}"
                ),
            ],
            cwd=str(ROOT),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
