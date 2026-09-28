"""Partial exit vs the same exit with too-high 1.16 and expansion 1.17 together.

Control (reuse): rl_too_high=1.13 and rl_expansion=1.163 on the locked partial exit.
Candidate: both knobs on the same book — rl_too_high=1.16 and rl_expansion=1.17.

Two-knob package. Do not attribute a result to either knob alone.
Capital days: full slot through the +20% sale, then 20%.
IS = entry < 2024-01-01. OOS report-only. Research-only.

Usage:
  python tools/rl_partial_th116_exp117_ab.py --workers 8
  python tools/rl_partial_th116_exp117_ab.py --summarize-only
"""
from __future__ import annotations

import argparse
import html as html_mod
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
DATA_DIR = ROOT / "data" / "newdata" / "data"
STAMP = "20260927"
OUT_DIR = DRIVE / "paul_experiments" / f"rl_partial_th116_exp117_ab_{STAMP}"
RUNS_DIR = OUT_DIR / "runs"
TAG = "RL-PARTIAL-TH116-EXP117"
CONTROL_DATA_END = "20260904"
CAND_ID = "th116_exp117"

CTRL_SRC = (
    DRIVE
    / "paul_experiments"
    / "rl_pct20_vs_p80_be_vs_origstop_ab_20260927"
    / "runs"
    / "p80_be_40"
)
CTRL_ID = "partial"
ARMS = (
    (CTRL_ID, "Control: partial exit, too high 1.13, expansion 1.163"),
    (CAND_ID, "Too high 1.16 and expansion 1.17"),
)

REQUEST_PROMPT = """\
Can you run another using partial exit as control vs. changing too high to 1.16 and expansion to 1.17 in the same test group
"""

LAYMAN_TRANSLATION = """\
Both books use the same sell plan: sell 80% once the price is 20% above the buy, move the leftover \
stop up to the buy price, and try to sell that last 20% at 40% above the buy. There is no waiting \
period and no moving-average profit target. Control is the locked partial-exit book. The other book \
changes two entry rules at once. Too high is how high the next morning's open is allowed to be: \
control allows up to 1.13 times the stop line, and the test allows up to 1.16, so more gap-up \
mornings still get filled. Expansion is how strong a prior push above the 50-day average is required \
before a dip buy: control asks for about 16.3% (1.163), and the test asks for 17% (1.17), which is \
a slightly stricter push. After the 80% sale, only one-fifth of the money still counts. The years \
before 2024 decide the call. 2024 onward is shown and is not used to pick a setting.
"""

INTERPRETATION = """\
Control reuses the locked partial exit from p80_be_40: rl_too_high=1.13 and rl_expansion=1.163. The \
candidate changes both knobs on the same book, to rl_too_high=1.16 and rl_expansion=1.17. This is a \
two-knob package, so a better or worse book cannot be credited to either knob by itself. The fill is \
allowed when the next open is at or below the signal-day low times rl_too_high times rl_stop_pct \
(0.934). Expansion still looks back 10 trading days for a close at least that multiple of the prior \
bar's 50-day average, including the signal day. Simple Moving Average (SMA) target is off. No time \
clock. Ladder 0.20:0.80:0, leftover target +40%, leftover stop at breakeven. New buys stop after \
2026-09-04. Capital Days, profit per capital day, and annualized return count a full slot through the \
+20% sale day and 20% of a slot after that. Choosing this package after seeing the table is in-sample \
selection. Research-only.
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


def _freeze() -> list[str]:
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
        "rl_dip_pct=1.055",
        "rl_expansion=1.17",
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
        "rl_too_high=1.16",
        "rl_min_avg_vol=10000",
        "rl_min_trigger_vol=5000",
        f"entry_end_date={CONTROL_DATA_END}",
        "rl_scale_ladder=0.20:0.80:0",
    ]


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
    for v in _freeze():
        cmd.extend(["-v", v])
    return cmd


def run_fresh(py: str, workers: int, skip_existing: bool) -> dict[str, Any]:
    arm_dir = RUNS_DIR / CAND_ID
    arm_dir.mkdir(parents=True, exist_ok=True)
    label = ARMS[1][1]
    closed = _find_latest(arm_dir, "RL_Closed_*.csv")
    if skip_existing and closed and closed.stat().st_size > 0 and load_trades(closed):
        return _arm_from_dir(CAND_ID, label, "candidate", arm_dir)
    cmd = build_cmd(py, arm_dir, workers)
    log_path = arm_dir / "run.log"
    t0 = time.time()
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write("CMD: " + " ".join(cmd) + "\n\n")
        log.flush()
        proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(ROOT))
    print(f"[{TAG}] {CAND_ID} elapsed={time.time() - t0:.0f}s exit={proc.returncode}", flush=True)
    run = _arm_from_dir(CAND_ID, label, "candidate", arm_dir)
    run["ok"] = proc.returncode == 0 and run["ok"]
    run["exit_code"] = proc.returncode
    return run


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


def _call(is_v: str, oos_v: str) -> str:
    if is_v == "DISMISS":
        return "DISMISS"
    if is_v in ("KEEP", "LEAN KEEP") and oos_v in ("DISMISS", "HOLD"):
        return "HOLD"
    if is_v in ("KEEP", "LEAN KEEP"):
        return is_v
    return "HOLD"


def write_html(packed, call, verdicts) -> Path:
    by_id = {p["arm"]["id"]: p for p in packed}
    baseline = by_id[CTRL_ID]
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
        "Control is too high 1.13 and expansion 1.163. The test book sets both to too high 1.16 and "
        "expansion 1.17. Capital days count a full slot through the +20% sale day, then 20% of a slot. "
        "Deltas are versus control. Click column headers to sort."
    )
    sections = []
    for split_key, title in (("m_is", "IS"), ("m_oos", "OOS (report-only)"), ("m_full", "FULL book")):
        body = "".join(compare_row(p, split_key, baseline, "", CTRL_ID) for p in packed)
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
    for split_key, title in (("m_is", "IS"), ("m_oos", "OOS"), ("m_full", "FULL")):
        rows = pairwise_delta_row(baseline, by_id[CAND_ID], split_key, "Package − Control")
        pw.append(
            f"<section><h2>Pairwise — {title}</h2>"
            f"<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>{pw_th}</tr></thead>"
            f"<tbody>{rows}</tbody></table></div></section>"
        )
    vis, nis = verdicts["is"]
    voos, noos = verdicts["oos"]
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Partial exit too-high 1.16 plus expansion 1.17 — {STAMP}</title>
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
<h1>Partial exit with too high 1.16 and expansion 1.17 together.</h1>
<p class="muted">Stamp <code>rl_partial_th116_exp117_ab_{STAMP}</code>. Research-only. Not gold. Not DailyRun.</p>
</header>
<main>
<div class="callout req">
<strong>What you asked</strong>
<pre>{html_mod.escape(REQUEST_PROMPT.strip())}</pre>
<p class="layman"><strong>In plain English:</strong> {html_mod.escape(LAYMAN_TRANSLATION.strip())}</p>
<p class="layman"><strong>Interpretation:</strong> {html_mod.escape(INTERPRETATION.strip())}</p>
</div>
<div class="callout">
<strong>Call versus control</strong>
<ul>
<li><strong>{html_mod.escape(call)}</strong>
IS <code>{html_mod.escape(vis)}</code> — {html_mod.escape(nis)}
OOS <code>{html_mod.escape(voos)}</code> — {html_mod.escape(noos)}</li>
</ul>
<p class="muted">Both knobs moved together, so this call is about the package. Judge average gain and profit factor. A softer out-of-sample result is a hold. Research-only.</p>
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


def write_docs(packed, html_path, call, verdicts) -> None:
    by_id = {p["arm"]["id"]: p for p in packed}
    vis, nis = verdicts["is"]
    voos, noos = verdicts["oos"]
    lines = [
        f"# BASELINE — `rl_partial_th116_exp117_ab_{STAMP}`",
        "",
        "**Status:** RESEARCH only. Two knobs on one book: `rl_too_high` and `rl_expansion`. Partial exit otherwise frozen.",
        f"**Control `{CTRL_ID}`:** `rl_too_high=1.13`, `rl_expansion=1.163`. Reuse `{CTRL_SRC.as_posix()}`.",
        f"**Candidate `{CAND_ID}`:** `rl_too_high=1.16` and `rl_expansion=1.17` together.",
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
    for aid, _label in ARMS:
        name = "Control" if aid == CTRL_ID else "Package"
        for key, label in (("m_is", "IS"), ("m_oos", "OOS"), ("m_full", "FULL")):
            lines.append(f"- **{name} {label}:** {_line(by_id[aid], key)}")
    lines.extend(
        [
            "",
            "## Verdict versus control",
            "",
            f"- **Package `{CAND_ID}` {call}** IS `{vis}` ({nis}); OOS `{voos}` ({noos}).",
            "- OOS is report-only. Do not retune. Do not split this package into a one-knob claim.",
            "",
            f"Compare: `{html_path.as_posix()}`",
            "",
        ]
    )
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines), encoding="utf-8")
    summary = [
        f"# SUMMARY — `rl_partial_th116_exp117_ab_{STAMP}`",
        "",
        f"- **Package `{CAND_ID}` {call}** IS `{vis}` ({nis}); OOS `{voos}` ({noos}).",
        "",
    ]
    for aid, _label in ARMS:
        name = "Control" if aid == CTRL_ID else "Package"
        for key, label in (("m_is", "IS"), ("m_oos", "OOS"), ("m_full", "FULL")):
            summary.append(f"- {name} {label}: {_line(by_id[aid], key)}")
    summary.extend(["", f"Compare: `{html_path.as_posix()}`", ""])
    (OUT_DIR / "SUMMARY.md").write_text("\n".join(summary), encoding="utf-8")


def _notify(py: str, html_path: Path, message: str, title: str) -> None:
    ntfy = ROOT / "tools" / "ntfy_job_done.py"
    if ntfy.is_file():
        subprocess.run([py, str(ntfy), "--path", str(html_path), "-t", title, "-m", message], cwd=str(ROOT))


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
            "<html><body><h1>Partial exit too-high plus expansion package failed</h1>"
            f"<p>{html_mod.escape(msg)}</p>"
            f"<pre>{html_mod.escape(REQUEST_PROMPT.strip())}</pre>"
            f"<p>{html_mod.escape(LAYMAN_TRANSLATION.strip())}</p></body></html>",
            encoding="utf-8",
        )
        _notify(py, path, msg, "Partial exit too-high plus expansion FAILED")
        print(f"[{TAG}] {msg}", flush=True)
        return 1

    try:
        label = ARMS[0][1]
        ctrl = _arm_from_dir(CTRL_ID, label, "control", CTRL_SRC)
        _copy_patterns(CTRL_SRC, RUNS_DIR / CTRL_ID)
        cand = run_fresh(py, args.workers, args.skip_existing or args.summarize_only)
    except FileNotFoundError as exc:
        return fail(str(exc))

    if not ctrl.get("ok") or not cand.get("ok"):
        return fail("control or package arm failed")

    ordered = [ctrl, cand]
    packed = [pack_result(r) for r in ordered]
    rows = {r["arm"]["id"]: _read_rows(Path(r["closed"])) for r in ordered}
    _weight(packed, rows)
    by_id = {p["arm"]["id"]: p for p in packed}
    verdicts = {
        "is": verdict_vs_control(by_id[CAND_ID], by_id[CTRL_ID], "m_is"),
        "oos": verdict_vs_control(by_id[CAND_ID], by_id[CTRL_ID], "m_oos"),
    }
    call = _call(verdicts["is"][0], verdicts["oos"][0])
    html_path = write_html(packed, call, verdicts)
    write_metrics_csv(packed, "", OUT_DIR / "metrics_all.csv")
    write_docs(packed, html_path, call, verdicts)
    print(f"[{TAG}] {call} IS={verdicts['is'][0]} OOS={verdicts['oos'][0]}", flush=True)
    print(f"[{TAG}] Wrote {html_path}", flush=True)
    _notify(
        py,
        html_path,
        f"Partial exit package too high 1.16 and expansion 1.17. {call}",
        "Partial exit too-high plus expansion",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
