"""Four existing Rocket Launcher sell packages, restated with gap-report capital days.

1. pct20_d60 control (reuse)
2. Live 40/30 (reuse)
3. +20% from entry, no time clock (reuse)
4. locked partial exit (reuse): 80% at +20%, breakeven leftover, leftover at +40%

No new backtest. Capital days: arms 1-3 charge a full slot for every day held.
Arm 4 charges a full slot through the +20% sale day, then 20% of a slot.
IS = entry < 2024-01-01. OOS report-only. Research-only.

Usage:
  python tools/rl_four_exit_packages_ab.py
"""
from __future__ import annotations

import argparse
import html as html_mod
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
STAMP = "20260927"
OUT_DIR = DRIVE / "paul_experiments" / f"rl_four_exit_packages_ab_{STAMP}"
RUNS_DIR = OUT_DIR / "runs"
TAG = "RL-FOUR-EXIT"

CTRL_SRC = (
    DRIVE / "paul_experiments" / "rl_no_sma_target_exit_ab_20260905" / "runs" / "pct20_d60"
)
LIVE_SRC = (
    DRIVE
    / "paul_experiments"
    / "rl_live_exit_vs_pct20_d60_ab_20260926"
    / "runs"
    / "live_40_30"
)
NOTIME_SRC = (
    DRIVE
    / "paul_experiments"
    / "rl_control_vs_live_vs_pct20_notime_ab_20260927"
    / "runs"
    / "pct20_notime"
)
PARTIAL_SRC = (
    DRIVE
    / "paul_experiments"
    / "rl_pct20_vs_p80_be_vs_origstop_ab_20260927"
    / "runs"
    / "p80_be_40"
)

CTRL_ID = "pct20_d60"
LIVE_ID = "live_40_30"
NOTIME_ID = "pct20_notime"
PARTIAL_ID = "partial"
ARMS = (
    (CTRL_ID, CTRL_SRC, "1: pct20_d60 control", "control"),
    (LIVE_ID, LIVE_SRC, "2: Live 40_30", "candidate"),
    (NOTIME_ID, NOTIME_SRC, "3: PCT20_NOTIME", "candidate"),
    (PARTIAL_ID, PARTIAL_SRC, "4: partial strategy", "candidate"),
)
CAND_IDS = [LIVE_ID, NOTIME_ID, PARTIAL_ID]
NAMES = {CTRL_ID: "1", LIVE_ID: "2", NOTIME_ID: "3", PARTIAL_ID: "4"}

REQUEST_PROMPT = """\
Can you run an AB test for 4 things.  1. pct20_d60 control, 2. Live 40_30, 3. PCT20_NOTIME, 4 partial strategy.same reporting
"""

LAYMAN_TRANSLATION = """\
These are four ways of selling the same kind of Rocket Launcher buy. 1. The control waits 60 market \
days after the trade is up 20%, then sells, and it does not use a moving-average profit target. \
2. Live uses the current sell rules: a target about 20% above the 50-day average can sell the trade, \
and so can waiting 30 market days after the trade is first up 40%. 3. PCT20_NOTIME sells the whole \
position the moment the price is 20% above the buy. No waiting period and no moving-average target. \
4. The partial strategy sells 80% once the price is 20% above the buy, moves the leftover stop up to \
the buy price, and tries to sell that last 20% at 40% above the buy. No waiting period and no \
moving-average target. For 1, 2, and 3, the full amount of money stays counted until the sell. For 4, \
after the 80% sale only one-fifth of the money still counts. The years before 2024 decide the call \
versus the control. 2024 onward is shown and is not used to change the call.
"""

INTERPRETATION = """\
Four sell packages, reused. Not a one-knob test. 1 reuses pct20_d60: Simple Moving Average (SMA) \
target off, rl_exit_percent=0.20, rl_exit_days=60. 2 reuses live_40_30: SMA target on (yesterday's \
50-day SMA times 1.20 can sell the trade), rl_exit_percent=0.40, rl_exit_days=30. 3 reuses \
pct20_notime: rl_entry_target_pct=0.20, SMA target off, time clock off. 4 reuses the locked partial \
exit from p80_be_40: ladder 0.20:0.80:0, leftover stop at breakeven, rl_entry_target_pct=0.40, SMA \
target off, time clock off. Buys stay the same freeze (dip 1.055, expansion 1.163, stop 0.934, \
too-high 1.13, volume floors). Live, no-time, and partial cap new buys after 2026-09-04 to match the \
frozen control snapshot. Capital Days, profit per capital day, and annualized return use the same \
slot method as the gap reports: a full slot every day for 1-3; for 4, a full slot through the +20% \
sale day and 20% of a slot after that. Max drawdown stays the exit-date overlay. Avg days stays \
calendar time open. Choosing among these four after seeing this table is in-sample selection. \
Research-only.
"""

sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(DRIVE / "paul_experiments"))
from be_stop_replay_ab import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402
from compare_format import filter_html_compare_columns  # noqa: E402
from rl_partial_vs_gap7_ab import _copy_patterns, _read_rows  # noqa: E402
from rl_partial_vs_gap7_ab import _apply_exposure  # noqa: E402
from rl_univ_compare_lists import (  # noqa: E402
    IS_CUT,
    compare_row,
    fmt_n,
    pack_result,
    pairwise_delta_row,
    verdict_vs_control,
    write_metrics_csv,
    _resolve_python,
)


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
        return "DISMISS"
    if is_v in ("KEEP", "LEAN KEEP") and oos_v in ("DISMISS", "HOLD"):
        return "HOLD"
    if is_v in ("KEEP", "LEAN KEEP"):
        return is_v
    return "HOLD"


def write_html(packed, calls, verdicts) -> Path:
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
        "1 is pct20_d60. 2 is the live sell package. 3 sells the whole trade at +20% with no time clock. "
        "4 is the partial strategy. Capital days for 1-3 are a full slot for every day held. "
        "For 4, a full slot through the +20% sale day, then 20% of a slot. "
        "Deltas are versus 1. Click column headers to sort."
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
    pairs = [(f"{NAMES[aid]} − 1", baseline, by_id[aid]) for aid in CAND_IDS]
    pw = []
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
            f"<li><strong>{NAMES[aid]} {html_mod.escape(aid)}: {html_mod.escape(calls[aid])}</strong> "
            f"IS <code>{html_mod.escape(vis)}</code> — {html_mod.escape(nis)} "
            f"OOS <code>{html_mod.escape(voos)}</code> — {html_mod.escape(noos)}</li>"
        )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Four exit packages versus pct20_d60 — {STAMP}</title>
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
<h1>Four sell packages on the pct20_d60 buys.</h1>
<p class="muted">Stamp <code>rl_four_exit_packages_ab_{STAMP}</code>. Research-only. Not gold. Not DailyRun.</p>
</header>
<main>
<div class="callout req">
<strong>What you asked</strong>
<pre>{html_mod.escape(REQUEST_PROMPT.strip())}</pre>
<p class="layman"><strong>In plain English:</strong> {html_mod.escape(LAYMAN_TRANSLATION.strip())}</p>
<p class="layman"><strong>Interpretation:</strong> {html_mod.escape(INTERPRETATION.strip())}</p>
</div>
<div class="callout">
<strong>Calls versus 1 (pct20_d60)</strong>
<ul>{''.join(items)}</ul>
<p class="muted">Judge average gain and profit factor. A softer out-of-sample result is a hold. These four packages differ by more than one knob. Research-only.</p>
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
    srcs = {aid: src for aid, src, _l, _r in ARMS}
    lines = [
        f"# BASELINE — `rl_four_exit_packages_ab_{STAMP}`",
        "",
        "**Status:** RESEARCH only. Four existing sell packages. Not a one-knob test.",
        f"**1 `{CTRL_ID}`:** SMA target off, +20% then 60 trading bars. Reuse `{srcs[CTRL_ID].as_posix()}`.",
        f"**2 `{LIVE_ID}`:** SMA50×1.20 target on, +40% then 30 trading bars. Reuse `{srcs[LIVE_ID].as_posix()}`.",
        f"**3 `{NOTIME_ID}`:** sell 100% at +20% from entry, no time clock. Reuse `{srcs[NOTIME_ID].as_posix()}`.",
        f"**4 `{PARTIAL_ID}`:** 80% at +20%, breakeven leftover, leftover at +40%. Reuse `{srcs[PARTIAL_ID].as_posix()}`.",
        "Not gold. Not DailyRun.",
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
        "Arms 1-3 charge a full slot for every day the trade is open. "
        "Arm 4 charges a full slot through the day the 80% piece is sold (inclusive). "
        "Every later calendar day uses 20% of a slot until the leftover exits.",
        "",
        "## Split metrics",
        "",
    ]
    for aid, _src, _label, _role in ARMS:
        for key, label in (("m_is", "IS"), ("m_oos", "OOS"), ("m_full", "FULL")):
            lines.append(f"- **{NAMES[aid]} {label}:** {_line(by_id[aid], key)}")
    lines.extend(["", "## Verdict versus 1", ""])
    for aid in CAND_IDS:
        v, n = verdicts[aid]["is"]
        vo, no = verdicts[aid]["oos"]
        lines.append(f"- **{NAMES[aid]} `{aid}` {calls[aid]}** IS `{v}` ({n}); OOS `{vo}` ({no}).")
    lines.extend(
        [
            "",
            "- OOS is report-only. Do not retune. Do not pick a package from this table alone.",
            "",
            f"Compare: `{html_path.as_posix()}`",
            "",
        ]
    )
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines), encoding="utf-8")
    summary = [f"# SUMMARY — `rl_four_exit_packages_ab_{STAMP}`", ""]
    for aid in CAND_IDS:
        v, n = verdicts[aid]["is"]
        vo, no = verdicts[aid]["oos"]
        summary.append(f"- **{NAMES[aid]} `{aid}` {calls[aid]}** IS `{v}` ({n}); OOS `{vo}` ({no}).")
    summary.append("")
    for aid, _src, _label, _role in ARMS:
        for key, label in (("m_is", "IS"), ("m_oos", "OOS"), ("m_full", "FULL")):
            summary.append(f"- {NAMES[aid]} {label}: {_line(by_id[aid], key)}")
    summary.extend(["", f"Compare: `{html_path.as_posix()}`", ""])
    (OUT_DIR / "SUMMARY.md").write_text("\n".join(summary), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summarize-only", action="store_true")
    args = parser.parse_args()
    del args
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    py = _resolve_python()
    from rl_partial_vs_gap7_ab import _arm_from_dir

    runs = []
    for aid, src, label, role in ARMS:
        run = _arm_from_dir(aid, label, role, src)
        _copy_patterns(src, RUNS_DIR / aid)
        runs.append(run)
    if not all(r.get("ok") for r in runs):
        raise SystemExit("one or more reused books are empty")
    packed = [pack_result(r) for r in runs]
    rows = {r["arm"]["id"]: _read_rows(Path(r["closed"])) for r in runs}
    _weight(packed, rows)
    by_id = {p["arm"]["id"]: p for p in packed}
    verdicts = {
        aid: {
            "is": verdict_vs_control(by_id[aid], by_id[CTRL_ID], "m_is"),
            "oos": verdict_vs_control(by_id[aid], by_id[CTRL_ID], "m_oos"),
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
        bits = " ".join(f"{NAMES[aid]}={calls[aid]}" for aid in CAND_IDS)
        subprocess.run(
            [
                py,
                str(ntfy),
                "--path",
                str(html_path),
                "-t",
                "Four exit packages versus pct20_d60",
                "-m",
                f"pct20_d60 vs Live 40_30 vs PCT20_NOTIME vs partial. {bits}",
            ],
            cwd=str(ROOT),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
