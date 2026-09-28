#!/usr/bin/env python3
"""Partial exit strategy vs the same exit with a 20-day 7% pre-entry gap skip.

A (reuse): partial exit — sell 80% at +20%, leftover stop to breakeven, leftover at +40%.
B (new): same exit. Skip the buy when any of the 20 completed trading days before
entry has ABS((Open / prior close) - 1) >= 7%. The entry day is not counted.

Capital days: full slot through the +20% sale day, then 20% of a slot.
IS = entry < 2024-01-01. OOS report-only.
Research-only. Not gold. Not DailyRun.

Usage:
  python tools/rl_partial_vs_gap7_ab.py --workers 8
  python tools/rl_partial_vs_gap7_ab.py --summarize-only
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import shutil
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
DATA_DIR = ROOT / "data" / "newdata" / "data"
STAMP = "20260927"
OUT_DIR = DRIVE / "paul_experiments" / f"rl_partial_vs_gap7_ab_{STAMP}"
RUNS_DIR = OUT_DIR / "runs"
CTRL_SRC = (
    DRIVE
    / "paul_experiments"
    / "rl_pct20_vs_p80_be_vs_origstop_ab_20260927"
    / "runs"
    / "p80_be_40"
)
CONTROL_DATA_END = "20260904"
REMAIN_FRAC = 0.20
GAP_BARS = 20
GAP_PCT = 7.0
TAG = "RL-PARTIAL-VS-GAP7"
A_ID = "partial"
B_ID = "partial_gap7"

REQUEST_PROMPT = """\
can you do an AB test using partial exit strategy vs partial exit strategy with one gap arm. Skip an entry if any of the prior 20 completed trading days had an absolute open-vs-previous-close gap ≥7%. Do not count the entry day.

Then report IS / OOS / FULL: trades, WR, Avg P&L, PF, Ann ROR, Max DD, Calmar, Sharpe, expectancy, capital days and PPCD.
"""

LAYMAN_TRANSLATION = """\
Both books use the partial exit: sell 80% once the price is 20% above the buy, move the leftover's stop \
up to the buy price, and try to sell that last 20% at 40% above the buy. The second book adds one buy rule. \
Look at the 20 completed trading days before the buy. If any of those mornings opened 7% or more away from \
the prior close, up or down, skip the buy. The buy day's own opening jump is not part of the check. \
After the 80% sale, only one-fifth of the money is counted as still in the trade. The years before 2024 \
decide the call. 2024 onward is shown and is not used to change the rule.
"""

INTERPRETATION = """\
A reuses the locked partial exit (ladder 0.20:0.80:0, rl_entry_target_pct=0.40) from \
p80_be_40 in rl_pct20_vs_p80_be_vs_origstop_ab_20260927. B is that same command plus \
rl_pre_entry_gap_bars=20 and rl_pre_entry_gap_pct=7. Gap % is the absolute jump from the prior close \
to the next open. A gap of 7% or more in that window rejects the buy. Fewer than 20 completed days \
of clean prices also rejects the buy, because the check cannot be completed. Simple Moving Average (SMA) \
target is off. No time clock. New buys stop after 2026-09-04. Capital Days, profit per capital day, \
and annualized return count a full slot through the +20% sale day and 20% of a slot after that. \
Research-only.
"""

sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(DRIVE / "paul_experiments"))
from be_stop_replay_ab import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402
from compare_format import ann_ror_from_closed, calmar_ratio, filter_html_compare_columns  # noqa: E402
from rl_univ_compare_lists import (  # noqa: E402
    IS_CUT,
    PER_SYMBOL,
    RL_CASH,
    SA,
    _f,
    _find_latest,
    _parse_d,
    _resolve_python,
    compare_row,
    fmt_n,
    load_trades,
    pack_result,
    pairwise_delta_row,
    verdict_vs_control,
    write_metrics_csv,
)


def _univ_symbols() -> list[str]:
    if not DATA_DIR.is_dir():
        return []
    return sorted(p.stem.upper() for p in DATA_DIR.glob("*.csv"))


def _freeze(*, gap: bool) -> list[str]:
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
    if gap:
        vs.append(f"rl_pre_entry_gap_bars={GAP_BARS}")
        vs.append(f"rl_pre_entry_gap_pct={GAP_PCT}")
    return vs


def _exposure_days(days_held: float, opened: date | None, partial: date | None) -> float:
    if days_held <= 0:
        return 0.0
    if opened is None or partial is None:
        return float(days_held)
    full_days = (partial - opened).days + 1
    if full_days < 1:
        full_days = 1
    if full_days > days_held:
        full_days = int(days_held)
    return float(full_days) + (float(days_held) - float(full_days)) * REMAIN_FRAC


def _read_rows(closed_path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with closed_path.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened = _parse_d(raw.get("DATE OPENED") or raw.get("DATE_OPENED"))
            if opened is None:
                continue
            days = _f(raw.get("DAYS HELD") or raw.get("DAYS_HELD"))
            partial_raw = (raw.get("PARTIAL_DATE") or "").strip()
            partial = None
            if partial_raw and partial_raw.upper() not in ("N/A", "NONE", "0"):
                partial = _parse_d(partial_raw)
            out.append({"opened": opened, "days": days, "exposure": _exposure_days(days, opened, partial)})
    return out


def _apply_exposure(m: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    if not rows or int(m.get("n") or 0) <= 0:
        return
    cap = float(sum(r["exposure"] for r in rows))
    pnl_d = float(m.get("pnl_d") or 0.0)
    n = int(m["n"])
    avg_exp = cap / n if n else 0.0
    ann = ann_ror_from_closed(total_pnl=pnl_d, n_trades=n, avg_days_held=avg_exp, brt_cash=RL_CASH)
    ann_f = float(ann) if ann is not None else float("nan")
    m["cap_days"] = cap
    m["ppc"] = (pnl_d / cap) if cap else float("nan")
    m["ann_ror"] = ann_f
    m["exposure_avg"] = avg_exp
    cal = calmar_ratio(ann_f, m.get("max_dd"))
    m["calmar"] = float(cal) if cal is not None else float("nan")


def apply_capital_weights(packed: list[dict[str, Any]], rows_by_id: dict[str, list[dict[str, Any]]]) -> None:
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


def _copy_patterns(src_dir: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for pat in (
        "RL_Closed_*.csv",
        "RL_Summary_*.csv",
        "RL_EquityMeta_*.csv",
        "RL_Report_*.csv",
        "RL_EquityCurve_*.csv",
    ):
        src = _find_latest(src_dir, pat)
        if src and src.is_file():
            shutil.copy2(src, dest / src.name)


def _arm_from_dir(arm_id: str, label: str, role: str, src_dir: Path) -> dict[str, Any]:
    closed = _find_latest(src_dir, "RL_Closed_*.csv")
    if not closed or not closed.is_file():
        raise FileNotFoundError(f"missing closed CSV for {arm_id} under {src_dir}")
    trades = load_trades(closed)
    syms = _univ_symbols()
    return {
        "arm": {
            "id": arm_id,
            "label": label,
            "role": role,
            "univ_n": len(syms),
            "symbols": syms,
        },
        "ok": len(trades) > 0,
        "closed": closed,
        "trades": trades,
        "stamp": closed.stem.split("_")[-1],
        "summary": _find_latest(src_dir, "RL_Summary_*.csv"),
        "equity_meta": _find_latest(src_dir, "RL_EquityMeta_*.csv"),
        "report": _find_latest(src_dir, "RL_Report_*.csv"),
        "equity_curve": _find_latest(src_dir, "RL_EquityCurve_*.csv"),
    }


def build_cmd(py: str, outdir: Path, workers: int) -> list[str]:
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
    for v in _freeze(gap=True):
        cmd.extend(["-v", v])
    return cmd


def run_gap(py: str, workers: int, skip_existing: bool) -> dict[str, Any]:
    arm_dir = RUNS_DIR / B_ID
    arm_dir.mkdir(parents=True, exist_ok=True)
    closed = _find_latest(arm_dir, "RL_Closed_*.csv")
    label = "B: partial exit, skip buys after a 7% gap in the prior 20 days"
    if skip_existing and closed and closed.stat().st_size > 0 and load_trades(closed):
        return _arm_from_dir(B_ID, label, "candidate", arm_dir)
    cmd = build_cmd(py, arm_dir, workers)
    log_path = arm_dir / "run.log"
    t0 = time.time()
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write("CMD: " + " ".join(cmd) + "\n\n")
        log.flush()
        proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(ROOT))
    print(f"[{TAG}] gap arm elapsed={time.time() - t0:.0f}s exit={proc.returncode}", flush=True)
    run = _arm_from_dir(B_ID, label, "candidate", arm_dir)
    run["ok"] = proc.returncode == 0 and run["ok"]
    run["exit_code"] = proc.returncode
    return run


def _line(p: dict[str, Any], key: str) -> str:
    m = p[key]
    return (
        f"N={m['n']} WR={m['wr']:.1f}% Avg={m['avg_pnl']:.2f}% PF={m['pf']:.2f} "
        f"AnnROR={fmt_n(m['ann_ror'], 2)} MaxDD={fmt_n(m['max_dd'], 2)} "
        f"Calmar={fmt_n(m.get('calmar'), 2)} Sharpe={fmt_n(m.get('sharpe'), 2)} "
        f"Expect$={fmt_n(m.get('exp_d'), 0)} cap_days={m.get('cap_days', 0):.0f} "
        f"PPCD={fmt_n(m.get('ppc'), 2)}"
    )


def _call(is_v: str, oos_v: str) -> str:
    if is_v == "DISMISS":
        return "gap arm DISMISS"
    if is_v in ("KEEP", "LEAN KEEP") and oos_v == "DISMISS":
        return "HOLD"
    if is_v in ("KEEP", "LEAN KEEP"):
        return f"gap arm {is_v}"
    return "HOLD"


def write_html(
    packed: list[dict[str, Any]],
    call: str,
    verdict: tuple[str, str],
    oos: tuple[str, str],
) -> Path:
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
        "A is the partial exit. B is the same exit and skips buys with a 7% open-vs-prior-close gap "
        "in the prior 20 completed days. Capital days count a full slot through the +20% sale day, "
        "then 20% of a slot. Avg days is still calendar time open. Deltas are B minus A. "
        "Click column headers to sort."
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
    pw = []
    for split_key, title in (("m_is", "IS"), ("m_oos", "OOS"), ("m_full", "FULL")):
        row = pairwise_delta_row(by_id[A_ID], by_id[B_ID], split_key, "B − A")
        pw.append(
            f"<section><h2>Pairwise — {title}</h2>"
            f"<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>{pw_th}</tr></thead>"
            f"<tbody>{row}</tbody></table></div></section>"
        )
    vis, nis = verdict
    voos, noos = oos
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Partial exit vs 7% gap skip — {STAMP}</title>
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
<h1>Partial exit versus the same exit that skips a buy after a 7% gap.</h1>
<p class="muted">Stamp <code>rl_partial_vs_gap7_ab_{STAMP}</code>. Research-only. Not gold. Not DailyRun.</p>
</header>
<main>
<div class="callout req">
<strong>What you asked</strong>
<pre>{html_mod.escape(REQUEST_PROMPT.strip())}</pre>
<p class="layman"><strong>In plain English:</strong> {html_mod.escape(LAYMAN_TRANSLATION.strip())}</p>
<p class="layman"><strong>Interpretation:</strong> {html_mod.escape(INTERPRETATION.strip())}</p>
</div>
<div class="callout">
<strong>Call: {html_mod.escape(call)}</strong>
<p>In-sample: <code>{html_mod.escape(vis)}</code> — {html_mod.escape(nis)}</p>
<p>After 2024 (report-only): <code>{html_mod.escape(voos)}</code> — {html_mod.escape(noos)}</p>
<p class="muted">Judge average gain and profit factor. A softer out-of-sample result is a hold. Research-only.</p>
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


def write_docs(packed: list[dict[str, Any]], html_path: Path, call: str, verdict: tuple[str, str], oos: tuple[str, str]) -> None:
    by_id = {p["arm"]["id"]: p for p in packed}
    lines = [
        f"# BASELINE — `rl_partial_vs_gap7_ab_{STAMP}`",
        "",
        "**Status:** RESEARCH only. ENTRY filter on the locked partial exit.",
        "**A `partial`:** ladder `0.20:0.80:0`, leftover target +40%, breakeven leftover stop. "
        f"Reuse `{CTRL_SRC.as_posix()}`.",
        f"**B `partial_gap7`:** same exit plus `rl_pre_entry_gap_bars={GAP_BARS}` and `rl_pre_entry_gap_pct={GAP_PCT}`.",
        "The only strategy change is the gap skip. Not gold. Not DailyRun.",
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
    for aid, name in ((A_ID, "A"), (B_ID, "B")):
        for key, label in (("m_is", "IS"), ("m_oos", "OOS"), ("m_full", "FULL")):
            lines.append(f"- **{name} {label}:** {_line(by_id[aid], key)}")
    lines.extend(
        [
            "",
            "## Verdict",
            "",
            f"- **{call}**. IS `{verdict[0]}` ({verdict[1]}). OOS `{oos[0]}` ({oos[1]}).",
            "- OOS is report-only. Do not retune.",
            "",
            f"Compare: `{html_path.as_posix()}`",
            "",
        ]
    )
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines), encoding="utf-8")
    summary = [
        f"# SUMMARY — `rl_partial_vs_gap7_ab_{STAMP}`",
        "",
        f"- **{call}** IS `{verdict[0]}` ({verdict[1]}); OOS `{oos[0]}` ({oos[1]}).",
        "",
    ]
    for aid, name in ((A_ID, "A"), (B_ID, "B")):
        for key, label in (("m_is", "IS"), ("m_oos", "OOS"), ("m_full", "FULL")):
            summary.append(f"- {name} {label}: {_line(by_id[aid], key)}")
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

    def fail(msg: str) -> int:
        path = OUT_DIR / "compare.html"
        path.write_text(
            "<html><body><h1>Partial exit vs gap skip failed</h1>"
            f"<p>{html_mod.escape(msg)}</p>"
            f"<pre>{html_mod.escape(REQUEST_PROMPT.strip())}</pre>"
            f"<p>{html_mod.escape(LAYMAN_TRANSLATION.strip())}</p></body></html>",
            encoding="utf-8",
        )
        ntfy = ROOT / "tools" / "ntfy_job_done.py"
        if ntfy.is_file():
            subprocess.run([py, str(ntfy), "--path", str(path), "-t", "Partial exit vs gap skip FAILED"], cwd=str(ROOT))
        print(f"[{TAG}] {msg}", flush=True)
        return 1

    try:
        run_a = _arm_from_dir(A_ID, "A: partial exit", "control", CTRL_SRC)
    except FileNotFoundError as exc:
        return fail(str(exc))
    _copy_patterns(CTRL_SRC, RUNS_DIR / A_ID)
    run_b = run_gap(py, args.workers, args.skip_existing or args.summarize_only)
    if not run_b.get("ok"):
        return fail(f"gap arm failed exit={run_b.get('exit_code')}")

    packed = [pack_result(run_a), pack_result(run_b)]
    rows = {A_ID: _read_rows(Path(run_a["closed"])), B_ID: _read_rows(Path(run_b["closed"]))}
    apply_capital_weights(packed, rows)
    by_id = {p["arm"]["id"]: p for p in packed}
    verdict = verdict_vs_control(by_id[B_ID], by_id[A_ID], "m_is")
    oos = verdict_vs_control(by_id[B_ID], by_id[A_ID], "m_oos")
    call = _call(verdict[0], oos[0])
    html_path = write_html(packed, call, verdict, oos)
    write_metrics_csv(packed, "", OUT_DIR / "metrics_all.csv")
    write_docs(packed, html_path, call, verdict, oos)
    print(f"[{TAG}] {call} IS={verdict[0]} OOS={oos[0]}", flush=True)
    print(f"[{TAG}] A IS {_line(by_id[A_ID], 'm_is')}", flush=True)
    print(f"[{TAG}] B IS {_line(by_id[B_ID], 'm_is')}", flush=True)
    print(f"[{TAG}] Wrote {html_path}", flush=True)
    ntfy = ROOT / "tools" / "ntfy_job_done.py"
    if ntfy.is_file():
        subprocess.run(
            [
                py,
                str(ntfy),
                "--path",
                str(html_path),
                "-t",
                "Partial exit vs 7% gap skip",
                "-m",
                f"Partial exit vs the same exit skipping a 7% gap in the prior 20 days. {call}. IS {verdict[0]}. OOS {oos[0]}.",
            ],
            cwd=str(ROOT),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
