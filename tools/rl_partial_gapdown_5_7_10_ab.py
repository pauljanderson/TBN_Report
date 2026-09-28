#!/usr/bin/env python3
"""Partial exit vs gap-down skips of 5%, 7%, and 10% over the prior 20 days.

A (reuse): partial exit, no gap filter.
B: skip a gap down of >= 5%.
C (reuse): skip a gap down of >= 7%.
D: skip a gap down of >= 10%.

Entry day is not counted. Up gaps do not skip the buy. Capital days: full slot
through the +20% sale, then 20%. IS = entry < 2024-01-01. OOS report-only.

Usage:
  python tools/rl_partial_gapdown_5_7_10_ab.py --workers 8
  python tools/rl_partial_gapdown_5_7_10_ab.py --summarize-only
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
DATA_DIR = ROOT / "data" / "newdata" / "data"
STAMP = "20260927"
OUT_DIR = DRIVE / "paul_experiments" / f"rl_partial_gapdown_5_7_10_ab_{STAMP}"
RUNS_DIR = OUT_DIR / "runs"
CTRL_SRC = (
    DRIVE
    / "paul_experiments"
    / "rl_pct20_vs_p80_be_vs_origstop_ab_20260927"
    / "runs"
    / "p80_be_40"
)
DOWN7_SRC = (
    DRIVE
    / "paul_experiments"
    / "rl_partial_gap7_side_ab_20260927"
    / "runs"
    / "gap7_down"
)
CONTROL_DATA_END = "20260904"
TAG = "RL-PARTIAL-GAPDOWN"
A_ID = "partial"
ARMS = (
    (A_ID, None, "A: partial exit, no gap filter", "control"),
    ("down5", 5.0, "B: skip a 5% gap down, prior 20 days", "candidate"),
    ("down7", 7.0, "C: skip a 7% gap down, prior 20 days", "candidate"),
    ("down10", 10.0, "D: skip a 10% gap down, prior 20 days", "candidate"),
)
ARM_ORDER = {aid: i for i, (aid, *_rest) in enumerate(ARMS)}
REUSE_SRC = {A_ID: CTRL_SRC, "down7": DOWN7_SRC}
CAND_IDS = [aid for aid, pct, *_rest in ARMS if pct is not None]

REQUEST_PROMPT = """\
Keep the 20-day lookback and frozen partial exit fixed. Test only gap-downs:

A: No gap filter
B: Skip ≥5% gap down
C: Skip ≥7% gap down
D: Skip ≥10% gap down
"""

LAYMAN_TRANSLATION = """\
All four books sell 80% once the price is 20% above the buy, move the leftover's stop up to the buy \
price, and try to sell that last 20% at 40% above the buy. A takes every one of those buys. B, C, and D \
look at the 20 completed trading days before the buy and skip the buy only when a morning opened below \
the prior close by 5% (B), 7% (C), or 10% (D) or more. A morning that opened higher does not skip the buy. \
The buy day's own opening jump is not part of the check. After the 80% sale, only one-fifth of the money \
is counted as still in the trade. The years before 2024 decide the call. 2024 onward is shown and is not \
used to pick a cutoff.
"""

INTERPRETATION = """\
A reuses the locked partial exit (ladder 0.20:0.80:0, rl_entry_target_pct=0.40, breakeven leftover) \
from p80_be_40. C reuses the 7% gap-down book from rl_partial_gap7_side_ab_20260927. B and D are the \
same command with rl_pre_entry_gap_bars=20, rl_pre_entry_gap_side=down, and rl_pre_entry_gap_pct set \
to 5 or 10. A gap down is an open at least that far below the prior close. Up gaps are ignored. Fewer \
than 20 completed days of clean prices also rejects the buy. Simple Moving Average (SMA) target is off. \
No time clock. New buys stop after 2026-09-04. Capital Days, profit per capital day, and annualized \
return count a full slot through the +20% sale day and 20% of a slot after that. The 7% gap-down rule \
was already scored once; choosing among 5%, 7%, and 10% after seeing this table is in-sample selection. \
Research-only.
"""

sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(DRIVE / "paul_experiments"))
from be_stop_replay_ab import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402
from compare_format import filter_html_compare_columns  # noqa: E402
from rl_partial_vs_gap7_ab import (  # noqa: E402
    _apply_exposure,
    _arm_from_dir,
    _copy_patterns,
    _line,
    _read_rows,
)
from rl_univ_compare_lists import (  # noqa: E402
    IS_CUT,
    PER_SYMBOL,
    SA,
    _find_latest,
    _resolve_python,
    compare_row,
    load_trades,
    pack_result,
    pairwise_delta_row,
    verdict_vs_control,
    write_metrics_csv,
)


def _freeze(gap_pct: float | None) -> list[str]:
    vs = [
        "rl_mode=true",
        "brt_zones=false",
        "yh_zones=false",
        "wpbr_zones=false",
        "indicator_buy=off",
        "rl_sma_qual=1",
        "ATR_LOW=off",
        "ATR_HIGH=off",
        "rl_slope_threshold=0",
        "rl_dip_pct=1.055",
        "rl_expansion=1.163",
        "rl_stop_pct=0.934",
        "rl_target_pct=1.2",
        "rl_sma_target_off=1",
        "rl_cut_the_losers=1000",
        "rl_exit_percent=0",
        "rl_exit_days=0",
        "rl_exit_calendar_days=0",
        "rl_max_hold_bars=0",
        "rl_max_hold_calendar_days=0",
        "rl_entry_target_pct=0.40",
        "rl_post_target_reentry_bars=0",
        "rl_too_high=1.13",
        "rl_min_avg_vol=10000",
        "rl_min_trigger_vol=5000",
        f"entry_end_date={CONTROL_DATA_END}",
        "rl_scale_ladder=0.20:0.80:0",
    ]
    if gap_pct is not None:
        vs.append("rl_pre_entry_gap_bars=20")
        vs.append(f"rl_pre_entry_gap_pct={gap_pct}")
        vs.append("rl_pre_entry_gap_side=down")
    return vs


def build_cmd(py: str, outdir: Path, workers: int, gap_pct: float) -> list[str]:
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
    for v in _freeze(gap_pct):
        cmd.extend(["-v", v])
    return cmd


def run_fresh(py: str, arm_id: str, label: str, gap_pct: float, workers: int, skip_existing: bool) -> dict[str, Any]:
    arm_dir = RUNS_DIR / arm_id
    arm_dir.mkdir(parents=True, exist_ok=True)
    closed = _find_latest(arm_dir, "RL_Closed_*.csv")
    if skip_existing and closed and closed.stat().st_size > 0 and load_trades(closed):
        return _arm_from_dir(arm_id, label, "candidate", arm_dir)
    cmd = build_cmd(py, arm_dir, workers, gap_pct)
    log_path = arm_dir / "run.log"
    t0 = time.time()
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write("CMD: " + " ".join(cmd) + "\n\n")
        log.flush()
        proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(ROOT))
    print(f"[{TAG}] {arm_id} elapsed={time.time() - t0:.0f}s exit={proc.returncode}", flush=True)
    run = _arm_from_dir(arm_id, label, "candidate", arm_dir)
    run["ok"] = proc.returncode == 0 and run["ok"]
    run["exit_code"] = proc.returncode
    return run


def _call(is_v: str, oos_v: str) -> str:
    if is_v == "DISMISS":
        return "DISMISS"
    if is_v in ("KEEP", "LEAN KEEP") and oos_v in ("DISMISS", "HOLD"):
        return "HOLD"
    if is_v in ("KEEP", "LEAN KEEP"):
        return is_v
    return "HOLD"


def _weight(packed: list[dict[str, Any]], rows_by_id: dict[str, list[dict[str, Any]]]) -> None:
    for p in packed:
        rows = rows_by_id[p["arm"]["id"]]
        if len(rows) != int(p["m_full"]["n"]):
            print(
                f"[{TAG}] exposure row mismatch {p['arm']['id']}: csv={len(rows)} metrics={p['m_full']['n']}",
                flush=True,
            )
        _apply_exposure(p["m_full"], rows)
        _apply_exposure(p["m_is"], [r for r in rows if r["opened"] < IS_CUT])
        _apply_exposure(p["m_oos"], [r for r in rows if r["opened"] >= IS_CUT])


def write_html(packed: list[dict[str, Any]], calls: dict[str, str], verdicts: dict[str, dict[str, tuple[str, str]]]) -> Path:
    by_id = {p["arm"]["id"]: p for p in packed}
    baseline = by_id[A_ID]
    th = "".join(
        sortable_th(a, b)
        for a, b in filter_html_compare_columns(
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
    note = (
        "A has no gap filter. B, C, and D skip a buy only when a morning in the prior 20 completed days "
        "opened 5%, 7%, or 10% or more below the prior close. A higher open does not skip the buy. "
        "Capital days count a full slot through the +20% sale day, then 20% of a slot. "
        "Deltas are versus A. Click column headers to sort."
    )
    sections = []
    for split_key, title in (("m_is", "IS"), ("m_oos", "OOS (report-only)"), ("m_full", "FULL book")):
        body = "".join(compare_row(p, split_key, baseline, "", A_ID) for p in packed)
        sections.append(
            f"<section><h2>{title}</h2><p class=\"muted\">{note}</p>"
            f"<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>{th}</tr></thead>"
            f"<tbody>{body}</tbody></table></div></section>"
        )
    pw_th = "".join(
        sortable_th(a, b)
        for a, b in filter_html_compare_columns(
            [
                ("Pair", "text"),
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
    pw = []
    pairs = [(f"{aid} − A", by_id[A_ID], by_id[aid]) for aid in CAND_IDS]
    for split_key, title in (("m_is", "IS"), ("m_oos", "OOS"), ("m_full", "FULL")):
        rows = "".join(pairwise_delta_row(a, b, split_key, lbl) for lbl, a, b in pairs)
        pw.append(
            f"<section><h2>Pairwise — {title}</h2>"
            f"<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>{pw_th}</tr></thead>"
            f"<tbody>{rows}</tbody></table></div></section>"
        )
    items = []
    for aid in CAND_IDS:
        vis, nis = verdicts[aid]["is"]
        voos, noos = verdicts[aid]["oos"]
        items.append(
            f"<li><strong>{html_mod.escape(aid)}: {html_mod.escape(calls[aid])}</strong> "
            f"IS <code>{html_mod.escape(vis)}</code> — {html_mod.escape(nis)} "
            f"OOS <code>{html_mod.escape(voos)}</code> — {html_mod.escape(noos)}</li>"
        )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Partial exit gap-down 5 / 7 / 10 — {STAMP}</title>
<style>
:root {{ --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#9aa7b8; --line:#2a3545; --accent:#5b9fd4; --ctrl:#243044; }}
*{{box-sizing:border-box}}
body{{margin:0;font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.45}}
header{{padding:1.25rem 1rem 0.5rem;max-width:1400px;margin:0 auto}}
h1{{font-size:1.35rem;margin:0 0 .35rem}}
h2{{font-size:1.05rem;margin:.2rem 0 .4rem;color:var(--accent)}}
.muted{{color:var(--muted);font-size:.92rem}}
.callout{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.75rem 1rem;margin:.75rem 0}}
.req pre{{white-space:pre-wrap;font-family:ui-monospace,Consolas,monospace;font-size:.82rem;margin:.4rem 0 0;color:var(--text)}}
.req .layman{{margin:.55rem 0 0;font-size:.95rem}}
main{{max-width:1400px;margin:0 auto;padding:0 1rem 2.5rem}}
section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.75rem 1rem 1rem;margin:1rem 0}}
.table-wrap{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-size:.78rem;min-width:900px}}
th,td{{border-bottom:1px solid var(--line);padding:.35rem .4rem;text-align:right}}
th:first-child,td:first-child{{text-align:left}}
tr.ctrl-row{{background:var(--ctrl)}}
{SORTABLE_TH_CSS.replace('th.sortable-th:hover{{background:#e8e4d8}}', 'th.sortable-th:hover{{background:#2a3545}}')}
</style>
</head>
<body>
<header>
<h1>Partial exit with a gap-down skip of 5%, 7%, or 10% over the prior 20 days.</h1>
<p class="muted">Stamp <code>rl_partial_gapdown_5_7_10_ab_{STAMP}</code>. Research-only. Not gold. Not DailyRun.</p>
</header>
<main>
<div class="callout req">
<strong>What you asked</strong>
<pre>{html_mod.escape(REQUEST_PROMPT.strip())}</pre>
<p class="layman"><strong>In plain English:</strong> {html_mod.escape(LAYMAN_TRANSLATION.strip())}</p>
<p class="layman"><strong>Interpretation:</strong> {html_mod.escape(INTERPRETATION.strip())}</p>
</div>
<div class="callout">
<strong>Calls versus A</strong>
<ul>{''.join(items)}</ul>
<p class="muted">Judge average gain and profit factor. A softer out-of-sample result is a hold. Picking a cutoff after seeing this table is in-sample selection. Research-only.</p>
</div>
{''.join(sections)}
{''.join(pw)}
</main>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    path = OUT_DIR / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def write_docs(packed, html_path, calls, verdicts) -> None:
    by_id = {p["arm"]["id"]: p for p in packed}
    lines = [
        f"# BASELINE — `rl_partial_gapdown_5_7_10_ab_{STAMP}`",
        "",
        "**Status:** RESEARCH only. Gap-down only. 20 completed days. Three pre-specified cutoffs.",
        f"**A `{A_ID}`:** no gap filter. Reuse `{CTRL_SRC.as_posix()}`.",
        "**B `down5`:** `rl_pre_entry_gap_bars=20`, `rl_pre_entry_gap_pct=5`, `rl_pre_entry_gap_side=down`.",
        f"**C `down7`:** `rl_pre_entry_gap_bars=20`, `rl_pre_entry_gap_pct=7`, `rl_pre_entry_gap_side=down`. Reuse `{DOWN7_SRC.as_posix()}`.",
        "**D `down10`:** `rl_pre_entry_gap_bars=20`, `rl_pre_entry_gap_pct=10`, `rl_pre_entry_gap_side=down`.",
        "Ladder `0.20:0.80:0`, leftover target +40%, breakeven leftover stop. Not gold. Not DailyRun.",
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
        "## Interpretation",
        "",
        INTERPRETATION.strip(),
        "",
        "## Capital-weighted hold",
        "",
        "Through the day the 80% piece is sold (inclusive), the trade uses a full slot. "
        "Every later calendar day uses 20% of a slot until the leftover exits.",
        "",
        "## Split metrics",
        "",
    ]
    names = {A_ID: "A", "down5": "B", "down7": "C", "down10": "D"}
    for aid, _pct, _label, _role in ARMS:
        for key, label in (("m_is", "IS"), ("m_oos", "OOS"), ("m_full", "FULL")):
            lines.append(f"- **{names[aid]} {label}:** {_line(by_id[aid], key)}")
    lines.extend(["", "## Verdict versus A", ""])
    for aid in CAND_IDS:
        v, n = verdicts[aid]["is"]
        vo, no = verdicts[aid]["oos"]
        lines.append(f"- **{names[aid]} `{aid}` {calls[aid]}** IS `{v}` ({n}); OOS `{vo}` ({no}).")
    lines.extend(["", "- OOS is report-only. Do not retune. Do not pick a cutoff from this table alone.", "", f"Compare: `{html_path.as_posix()}`", ""])
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines), encoding="utf-8")
    summary = [f"# SUMMARY — `rl_partial_gapdown_5_7_10_ab_{STAMP}`", ""]
    for aid in CAND_IDS:
        v, n = verdicts[aid]["is"]
        vo, no = verdicts[aid]["oos"]
        summary.append(f"- **{names[aid]} `{aid}` {calls[aid]}** IS `{v}` ({n}); OOS `{vo}` ({no}).")
    summary.append("")
    for aid, _pct, _label, _role in ARMS:
        for key, label in (("m_is", "IS"), ("m_oos", "OOS"), ("m_full", "FULL")):
            summary.append(f"- {names[aid]} {label}: {_line(by_id[aid], key)}")
    summary.extend(["", f"Compare: `{html_path.as_posix()}`", ""])
    (OUT_DIR / "SUMMARY.md").write_text("\n".join(summary), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    py = _resolve_python()
    skip = args.skip_existing or args.summarize_only

    def fail(msg: str) -> int:
        path = OUT_DIR / "compare.html"
        path.write_text(
            "<html><body><h1>Partial exit gap-down grid failed</h1>"
            f"<p>{html_mod.escape(msg)}</p>"
            f"<pre>{html_mod.escape(REQUEST_PROMPT.strip())}</pre>"
            f"<p>{html_mod.escape(LAYMAN_TRANSLATION.strip())}</p></body></html>",
            encoding="utf-8",
        )
        ntfy = ROOT / "tools" / "ntfy_job_done.py"
        if ntfy.is_file():
            subprocess.run([py, str(ntfy), "--path", str(path), "-t", "Partial exit gap-down grid FAILED"], cwd=str(ROOT))
        print(f"[{TAG}] {msg}", flush=True)
        return 1

    runs: dict[str, dict[str, Any]] = {}
    try:
        for aid, src in REUSE_SRC.items():
            label = next(lbl for i, _p, lbl, _r in ARMS if i == aid)
            role = "control" if aid == A_ID else "candidate"
            runs[aid] = _arm_from_dir(aid, label, role, src)
            _copy_patterns(src, RUNS_DIR / aid)
    except FileNotFoundError as exc:
        return fail(str(exc))

    fresh = [(aid, pct, lbl) for aid, pct, lbl, _role in ARMS if aid not in REUSE_SRC]
    if skip:
        for aid, _pct, lbl in fresh:
            try:
                runs[aid] = _arm_from_dir(aid, lbl, "candidate", RUNS_DIR / aid)
            except FileNotFoundError as exc:
                return fail(str(exc))
    else:
        with ThreadPoolExecutor(max_workers=max(1, len(fresh))) as ex:
            futs = {
                ex.submit(run_fresh, py, aid, lbl, pct, args.workers, False): aid
                for aid, pct, lbl in fresh
            }
            for fut in as_completed(futs):
                aid = futs[fut]
                runs[aid] = fut.result()

    if not all(runs[aid].get("ok") for aid, *_rest in ARMS):
        return fail("one or more arms failed")

    ordered = [runs[aid] for aid, *_rest in ARMS]
    packed = [pack_result(r) for r in ordered]
    rows = {r["arm"]["id"]: _read_rows(Path(r["closed"])) for r in ordered}
    _weight(packed, rows)
    by_id = {p["arm"]["id"]: p for p in packed}
    verdicts = {
        aid: {
            "is": verdict_vs_control(by_id[aid], by_id[A_ID], "m_is"),
            "oos": verdict_vs_control(by_id[aid], by_id[A_ID], "m_oos"),
        }
        for aid in CAND_IDS
    }
    calls = {aid: _call(verdicts[aid]["is"][0], verdicts[aid]["oos"][0]) for aid in CAND_IDS}
    html_path = write_html(packed, calls, verdicts)
    write_metrics_csv(packed, "", OUT_DIR / "metrics_all.csv")
    write_docs(packed, html_path, calls, verdicts)
    for aid in CAND_IDS:
        print(f"[{TAG}] {aid} {calls[aid]} IS={verdicts[aid]['is'][0]} OOS={verdicts[aid]['oos'][0]}", flush=True)
    print(f"[{TAG}] Wrote {html_path}", flush=True)
    ntfy = ROOT / "tools" / "ntfy_job_done.py"
    if ntfy.is_file():
        bits = " ".join(f"{aid}={calls[aid]}" for aid in CAND_IDS)
        subprocess.run(
            [
                py,
                str(ntfy),
                "--path",
                str(html_path),
                "-t",
                "Partial exit gap-down 5 / 7 / 10",
                "-m",
                f"Frozen partial exit vs 5%, 7%, and 10% gap-down skips over 20 days. {bits}",
            ],
            cwd=str(ROOT),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
