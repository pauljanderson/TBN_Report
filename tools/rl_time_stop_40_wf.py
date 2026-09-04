#!/usr/bin/env python3
"""Walk-forward: RL time-stop 40d vs off on tradable 764 (locked knob).

Uses existing fill-fixed Closed books — no new engine run, no retune.
Rolling train 3y → test 1y (`stock_analysis/walkforward.py`). One EXIT knob:
`rl_exit_days=40` vs `10000` (off). Freeze everything else.

Not 30/50. Not 40×1.18. Not gold. Not DailyRun.

Usage:
  python tools/rl_time_stop_40_wf.py
"""
from __future__ import annotations

import csv
import html as html_mod
import math
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
STAMP = "20260828"
OUT_DIR = DRIVE / "paul_experiments" / f"rl_time_stop_40_wf_tradable_{STAMP}"
CONTROL_CLOSED = (
    DRIVE
    / "paul_experiments"
    / "rl_tradable_2010_adv2m_20260828"
    / "runs"
    / "tradable"
    / "RL_Closed_260828112205.csv"
)
CAND_CLOSED = (
    DRIVE
    / "paul_experiments"
    / "rl_time_stop_tradable_20260828"
    / "runs"
    / "days40"
    / "RL_Closed_260828184602.csv"
)
WF_START = "2010-01-01"
TRAIN_YEARS = 3
TEST_YEARS = 1
STEP_YEARS = 1
MIN_N = 15

sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "stock_analysis"))
sys.path.insert(0, str(DRIVE / "paul_experiments"))
from be_stop_replay_ab import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402
from compare_format import filter_html_compare_columns  # noqa: E402
from rl_univ_compare_lists import book_stats, fmt_n, load_trades, _resolve_python  # noqa: E402
from walkforward import build_rolling_folds  # noqa: E402


def _in_window(t: dict[str, Any], start: date, end: date) -> bool:
    o = t.get("opened")
    return o is not None and start <= o <= end


def _slice(trades: list[dict[str, Any]], start: str, end: str) -> list[dict[str, Any]]:
    a = date.fromisoformat(start)
    b = date.fromisoformat(end)
    return [t for t in trades if _in_window(t, a, b)]


def _finite(x: Any) -> bool:
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _better_ann(a: dict[str, Any], b: dict[str, Any]) -> Optional[bool]:
    """True if a AnnROR > b. None if missing."""
    if not _finite(a.get("ann_ror")) or not _finite(b.get("ann_ror")):
        return None
    return float(a["ann_ror"]) > float(b["ann_ror"])


def _better_dd(a: dict[str, Any], b: dict[str, Any]) -> Optional[bool]:
    """True if a overlay Max DD is lower (better). None if missing."""
    if not _finite(a.get("max_dd")) or not _finite(b.get("max_dd")):
        return None
    return float(a["max_dd"]) < float(b["max_dd"])


def _yn(v: Optional[bool]) -> str:
    if v is True:
        return "yes"
    if v is False:
        return "no"
    return "—"


def _fold_row(fold_name: str, window: str, off: dict[str, Any], d40: dict[str, Any]) -> str:
    def cell(m: dict[str, Any], k: str, nd: int = 2) -> str:
        return html_mod.escape(fmt_n(m.get(k), nd))

    d_avg = (d40["avg_pnl"] - off["avg_pnl"]) if off["n"] and d40["n"] else float("nan")
    d_ann = (
        float(d40["ann_ror"]) - float(off["ann_ror"])
        if _finite(d40.get("ann_ror")) and _finite(off.get("ann_ror"))
        else float("nan")
    )
    d_dd = (
        float(d40["max_dd"]) - float(off["max_dd"])
        if _finite(d40.get("max_dd")) and _finite(off.get("max_dd"))
        else float("nan")
    )
    thin = off["n"] < MIN_N or d40["n"] < MIN_N
    return (
        "<tr>"
        f"<td>{html_mod.escape(fold_name)}</td>"
        f"<td>{html_mod.escape(window)}</td>"
        f"<td data-sort-value='{off['n']}'>{off['n']}</td>"
        f"<td data-sort-value='{d40['n']}'>{d40['n']}</td>"
        f"<td>{cell(off, 'wr', 1)}</td>"
        f"<td>{cell(d40, 'wr', 1)}</td>"
        f"<td>{cell(off, 'avg_pnl')}</td>"
        f"<td>{cell(d40, 'avg_pnl')}</td>"
        f"<td>{html_mod.escape(fmt_n(d_avg))}</td>"
        f"<td>{cell(off, 'wo_max')}</td>"
        f"<td>{cell(d40, 'wo_max')}</td>"
        f"<td>{cell(off, 'pf')}</td>"
        f"<td>{cell(d40, 'pf')}</td>"
        f"<td>{cell(off, 'ann_ror')}</td>"
        f"<td>{cell(d40, 'ann_ror')}</td>"
        f"<td>{html_mod.escape(fmt_n(d_ann))}</td>"
        f"<td>{cell(off, 'max_dd')}</td>"
        f"<td>{cell(d40, 'max_dd')}</td>"
        f"<td>{html_mod.escape(fmt_n(d_dd))}</td>"
        f"<td>{cell(off, 'avg_days', 1)}</td>"
        f"<td>{cell(d40, 'avg_days', 1)}</td>"
        f"<td>{_yn(_better_ann(d40, off) if not thin else None)}</td>"
        f"<td>{_yn(_better_dd(d40, off) if not thin else None)}</td>"
        f"<td>{'thin' if thin else 'ok'}</td>"
        "</tr>"
    )


def _decision(test_rows: list[dict[str, Any]]) -> str:
    usable = [r for r in test_rows if r["off"]["n"] >= MIN_N and r["d40"]["n"] >= MIN_N]
    n = len(usable)
    if n == 0:
        return "**HOLD**. No test fold with N≥15 on both arms. Do not adopt."
    ann_w = sum(1 for r in usable if _better_ann(r["d40"], r["off"]) is True)
    dd_w = sum(1 for r in usable if _better_dd(r["d40"], r["off"]) is True)
    avg_w = sum(1 for r in usable if r["d40"]["avg_pnl"] > r["off"]["avg_pnl"])
    # Last two folds are the closest thing to unseen-after-2024 if they exist.
    return (
        f"**Walk-forward (locked 40 vs off, {n} test folds with N>={MIN_N}):** "
        f"40d higher AnnROR in {ann_w}/{n}; better overlay DD in {dd_w}/{n}; "
        f"higher Avg in {avg_w}/{n}. "
        "This is still a research CONSIDER, not gold / not DailyRun. "
        "Do not retune days. Do not mix target 1.18 on this stamp. "
        "Overlay Max DD on 1y slices is noisy — prefer fold AnnROR + Avg + the prior host DD on the full 40d book."
    )


def write_html(
    test_rows: list[dict[str, Any]],
    train_rows: list[dict[str, Any]],
    pooled_off: dict[str, Any],
    pooled_40: dict[str, Any],
    embargo: dict[str, Any],
    decision: str,
) -> Path:
    th = "".join(
        sortable_th(a, b)
        for a, b in filter_html_compare_columns(
            [
                ("Fold", "text"),
                ("Test window", "text"),
                ("N off", "num"),
                ("N 40d", "num"),
                ("WR% off", "num"),
                ("WR% 40d", "num"),
                ("Avg% off", "num"),
                ("Avg% 40d", "num"),
                ("Δ Avg%", "num"),
                ("WO_MAX off", "num"),
                ("WO_MAX 40d", "num"),
                ("PF off", "num"),
                ("PF 40d", "num"),
                ("Ann ROR% off", "num"),
                ("Ann ROR% 40d", "num"),
                ("Δ Ann ROR", "num"),
                ("Max DD% off", "num"),
                ("Max DD% 40d", "num"),
                ("Δ Max DD", "num"),
                ("Avg days off", "num"),
                ("Avg days 40d", "num"),
                ("40d AnnROR win", "text"),
                ("40d DD win", "text"),
                ("N flag", "text"),
            ]
        )
    )
    test_body = "".join(
        _fold_row(r["name"], r["window"], r["off"], r["d40"]) for r in test_rows
    )
    train_th = "".join(
        sortable_th(a, b)
        for a, b in filter_html_compare_columns(
            [
                ("Fold", "text"),
                ("Train window", "text"),
                ("N off", "num"),
                ("N 40d", "num"),
                ("Ann ROR% off", "num"),
                ("Ann ROR% 40d", "num"),
                ("Max DD% off", "num"),
                ("Max DD% 40d", "num"),
                ("Train would pick 40 (AnnROR)", "text"),
            ]
        )
    )
    train_body = []
    for r in train_rows:
        pick = _better_ann(r["d40"], r["off"])
        train_body.append(
            "<tr>"
            f"<td>{html_mod.escape(r['name'])}</td>"
            f"<td>{html_mod.escape(r['window'])}</td>"
            f"<td>{r['off']['n']}</td>"
            f"<td>{r['d40']['n']}</td>"
            f"<td>{html_mod.escape(fmt_n(r['off'].get('ann_ror')))}</td>"
            f"<td>{html_mod.escape(fmt_n(r['d40'].get('ann_ror')))}</td>"
            f"<td>{html_mod.escape(fmt_n(r['off'].get('max_dd')))}</td>"
            f"<td>{html_mod.escape(fmt_n(r['d40'].get('max_dd')))}</td>"
            f"<td>{_yn(pick)}</td>"
            "</tr>"
        )
    pooled_th = "".join(
        sortable_th(a, b)
        for a, b in filter_html_compare_columns(
            [
                ("Sleeve", "text"),
                ("Trades", "num"),
                ("WR%", "num"),
                ("Avg PnL%", "num"),
                ("Avg% w/o max", "num"),
                ("PF", "num"),
                ("Ann ROR%", "num"),
                ("Max DD%", "num"),
                ("Calmar", "num"),
                ("Avg days", "num"),
            ]
        )
    )

    def pooled_tr(label: str, m: dict[str, Any]) -> str:
        return (
            "<tr>"
            f"<td>{html_mod.escape(label)}</td>"
            f"<td>{m['n']}</td>"
            f"<td>{html_mod.escape(fmt_n(m.get('wr'), 1))}</td>"
            f"<td>{html_mod.escape(fmt_n(m.get('avg_pnl')))}</td>"
            f"<td>{html_mod.escape(fmt_n(m.get('wo_max')))}</td>"
            f"<td>{html_mod.escape(fmt_n(m.get('pf')))}</td>"
            f"<td>{html_mod.escape(fmt_n(m.get('ann_ror')))}</td>"
            f"<td>{html_mod.escape(fmt_n(m.get('max_dd')))}</td>"
            f"<td>{html_mod.escape(fmt_n(m.get('calmar')))}</td>"
            f"<td>{html_mod.escape(fmt_n(m.get('avg_days'), 1))}</td>"
            "</tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RL 40d time-stop walk-forward — tradable {STAMP}</title>
<style>
:root {{ --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#9aa7b8; --line:#2a3545; --accent:#5b9fd4; }}
*{{box-sizing:border-box}}
body{{margin:0;font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.45}}
header{{padding:1.25rem 1rem 0.5rem;max-width:1500px;margin:0 auto}}
h1{{font-size:1.35rem;margin:0 0 .35rem}}
h2{{font-size:1.05rem;margin:1.25rem 0 .4rem;color:var(--accent)}}
.muted{{color:var(--muted);font-size:.92rem}}
.callout{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.75rem 1rem;margin:.75rem 0}}
main{{max-width:1500px;margin:0 auto;padding:0 1rem 2.5rem}}
section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.75rem 1rem 1rem;margin:1rem 0}}
.table-wrap{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-size:.78rem;min-width:1100px}}
th,td{{border-bottom:1px solid var(--line);padding:.35rem .4rem;text-align:right}}
th:first-child,td:first-child,td:nth-child(2){{text-align:left}}
{SORTABLE_TH_CSS.replace('th.sortable-th:hover{{background:#e8e4d8}}', 'th.sortable-th:hover{{background:#2a3545}}')}
</style>
</head>
<body>
<header>
<h1>RL time-stop 40d — walk-forward vs off</h1>
<p class="muted">Stamp <code>rl_time_stop_40_wf_tradable_{STAMP}</code>. Locked knob
<code>rl_exit_days=40</code> vs <code>10000</code> (off). Freeze: dip=1.055, stop=0.934,
target=1.20, slope off, trails off, +29% gate. Train {TRAIN_YEARS}y → test {TEST_YEARS}y,
step {STEP_YEARS}y from {WF_START}. Slice by <em>entry date</em> on fill-fixed Closed
(control <code>260828112205</code>, 40d <code>260828184602</code>). Not 30/50. Not 40×1.18.
Not gold / not DailyRun. Overlay Max DD ≠ host account DD. Click column headers to sort.</p>
</header>
<main>
<div class="callout">
<strong>Why WF:</strong> 40d was picked after seeing 40 vs 80 on the full tape (in-sample
selection). This report does <em>not</em> retune. It asks whether locked 40d still beats
off on rolling next-year tests. {html_mod.escape(decision)}
</div>
<section>
<h2>Test folds (locked 40 vs off)</h2>
<p class="muted">Entry date in the test window. Overlay Ann ROR / Max DD from Closed replay
($47,500 / $500k). Click column headers to sort.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>{th}</tr></thead>
<tbody>{test_body}</tbody></table></div>
</section>
<section>
<h2>Train folds (would we have picked 40 before seeing the next year?)</h2>
<p class="muted">Report-only. Does not change the locked 40 vs off test table above.
Pick = train AnnROR 40d &gt; off. Click column headers to sort.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>{train_th}</tr></thead>
<tbody>{"".join(train_body)}</tbody></table></div>
</section>
<section>
<h2>Pooled test-window trades (non-overlapping years)</h2>
<p class="muted">All test-fold entries concatenated. Embargoed = each year uses 40d only if
that year’s train AnnROR preferred 40, else off. Click column headers to sort.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>{pooled_th}</tr></thead>
<tbody>
{pooled_tr("Always off (test years)", pooled_off)}
{pooled_tr("Always 40d (test years)", pooled_40)}
{pooled_tr("Embargoed (train AnnROR pick)", embargo)}
</tbody></table></div>
</section>
</main>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    path = OUT_DIR / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def write_docs(
    test_rows: list[dict[str, Any]],
    decision: str,
    pooled_off: dict[str, Any],
    pooled_40: dict[str, Any],
) -> None:
    hyp = f"""# HYPOTHESIS — RL 40d time-stop walk-forward

| Field | Fill in |
|-------|---------|
| System / prefix | RL |
| Baseline stamp | tradable Closed `260828112205` (off) vs 40d `260828184602` (fill-fixed) |
| Universe | tradable 2010 / ADV$2m (764) |
| **Evidence** | PO CONSIDER 40d on `rl_time_stop_tradable_20260828` after 40 vs 80 (in-sample pick) |
| **Hypothesis** | Locked `rl_exit_days=40` still beats off on rolling next-year tests (AnnROR / overlay DD) |
| **Single knob** | `rl_exit_days` 40 vs 10000. Frozen otherwise |
| Frozen settings | dip=1.055, expansion=1.163, stop=0.934, target=1.20, trails off, exit_percent=0.29, slope off |
| Alternatives | off vs **40 only**. Not 30/50. Not 80. Not target 1.18 |
| Method | Slice existing Closed by entry date; train {TRAIN_YEARS}y / test {TEST_YEARS}y; no engine re-run; no retune |
| **Decision** | {decision} |

OOS / WF report-only. Do not retune. Research-only ≠ gold ≠ DailyRun.
"""
    (OUT_DIR / "HYPOTHESIS.md").write_text(hyp, encoding="utf-8")
    lines = [
        f"# BASELINE — `rl_time_stop_40_wf_tradable_{STAMP}`",
        "",
        "**Status:** RESEARCH walk-forward. Locked 40 vs off. Not gold. Not DailyRun.",
        "",
        "| Field | Value |",
        "|---|---|",
        "| Universe | tradable 2010 / ADV$2m (764) |",
        "| Control Closed | `RL_Closed_260828112205` (`rl_exit_days=10000`) |",
        "| Candidate Closed | `RL_Closed_260828184602` (`rl_exit_days=40`, fill-fixed) |",
        f"| Folds | train {TRAIN_YEARS}y / test {TEST_YEARS}y / step {STEP_YEARS}y from {WF_START} |",
        "| Split | entry date in window |",
        "| Frozen | dip=1.055, stop=0.934, target=1.20, slope 0, trails off |",
        "",
        "## Test folds",
        "",
        "| Fold | Window | N_off | N_40 | Avg_off | Avg_40 | AnnROR_off | AnnROR_40 | DD_off | DD_40 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in test_rows:
        lines.append(
            f"| `{r['name']}` | {r['window']} | {r['off']['n']} | {r['d40']['n']} | "
            f"{fmt_n(r['off']['avg_pnl'])} | {fmt_n(r['d40']['avg_pnl'])} | "
            f"{fmt_n(r['off'].get('ann_ror'))} | {fmt_n(r['d40'].get('ann_ror'))} | "
            f"{fmt_n(r['off'].get('max_dd'))} | {fmt_n(r['d40'].get('max_dd'))} |"
        )
    lines.extend(
        [
            "",
            "## Pooled test years",
            "",
            f"- **off**: N={pooled_off['n']} Avg={fmt_n(pooled_off['avg_pnl'])}% "
            f"AnnROR={fmt_n(pooled_off.get('ann_ror'))} DD={fmt_n(pooled_off.get('max_dd'))}",
            f"- **40d**: N={pooled_40['n']} Avg={fmt_n(pooled_40['avg_pnl'])}% "
            f"AnnROR={fmt_n(pooled_40.get('ann_ror'))} DD={fmt_n(pooled_40.get('max_dd'))}",
            "",
            f"## Decision",
            "",
            decision,
            "",
        ]
    )
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    slines = [
        f"# SUMMARY — `rl_time_stop_40_wf_tradable_{STAMP}`",
        "",
        "Locked 40d vs off walk-forward on tradable 764. No retune. Research only.",
        "",
        decision,
        "",
        "## Pooled test years",
        "",
        f"- **off**: N={pooled_off['n']} WR={fmt_n(pooled_off['wr'], 1)}% "
        f"Avg={fmt_n(pooled_off['avg_pnl'])}% PF={fmt_n(pooled_off['pf'])} "
        f"AnnROR={fmt_n(pooled_off.get('ann_ror'))} DD={fmt_n(pooled_off.get('max_dd'))}",
        f"- **40d**: N={pooled_40['n']} WR={fmt_n(pooled_40['wr'], 1)}% "
        f"Avg={fmt_n(pooled_40['avg_pnl'])}% PF={fmt_n(pooled_40['pf'])} "
        f"AnnROR={fmt_n(pooled_40.get('ann_ror'))} DD={fmt_n(pooled_40.get('max_dd'))}",
        "",
    ]
    (OUT_DIR / "SUMMARY.md").write_text("\n".join(slines), encoding="utf-8")


def write_metrics_csv(test_rows: list[dict[str, Any]]) -> None:
    path = OUT_DIR / "metrics_folds.csv"
    fields = [
        "fold",
        "window",
        "n_off",
        "n_40",
        "wr_off",
        "wr_40",
        "avg_off",
        "avg_40",
        "pf_off",
        "pf_40",
        "ann_ror_off",
        "ann_ror_40",
        "max_dd_off",
        "max_dd_40",
        "avg_days_off",
        "avg_days_40",
        "ann_win",
        "dd_win",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in test_rows:
            thin = r["off"]["n"] < MIN_N or r["d40"]["n"] < MIN_N
            w.writerow(
                {
                    "fold": r["name"],
                    "window": r["window"],
                    "n_off": r["off"]["n"],
                    "n_40": r["d40"]["n"],
                    "wr_off": r["off"]["wr"],
                    "wr_40": r["d40"]["wr"],
                    "avg_off": r["off"]["avg_pnl"],
                    "avg_40": r["d40"]["avg_pnl"],
                    "pf_off": r["off"]["pf"],
                    "pf_40": r["d40"]["pf"],
                    "ann_ror_off": r["off"].get("ann_ror"),
                    "ann_ror_40": r["d40"].get("ann_ror"),
                    "max_dd_off": r["off"].get("max_dd"),
                    "max_dd_40": r["d40"].get("max_dd"),
                    "avg_days_off": r["off"].get("avg_days"),
                    "avg_days_40": r["d40"].get("avg_days"),
                    "ann_win": _yn(_better_ann(r["d40"], r["off"]) if not thin else None),
                    "dd_win": _yn(_better_dd(r["d40"], r["off"]) if not thin else None),
                }
            )


def main() -> int:
    if not CONTROL_CLOSED.is_file():
        print(f"[RL-WF] missing control {CONTROL_CLOSED}", flush=True)
        return 1
    if not CAND_CLOSED.is_file():
        print(f"[RL-WF] missing 40d {CAND_CLOSED}", flush=True)
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    src_dir = OUT_DIR / "source_closed"
    src_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CONTROL_CLOSED, src_dir / CONTROL_CLOSED.name)
    shutil.copy2(CAND_CLOSED, src_dir / CAND_CLOSED.name)

    off_t = load_trades(CONTROL_CLOSED)
    d40_t = load_trades(CAND_CLOSED)
    if not off_t or not d40_t:
        print("[RL-WF] empty Closed", flush=True)
        return 1
    last = max(t["opened"] for t in off_t if t.get("opened"))
    folds = build_rolling_folds(
        pd.Timestamp(WF_START),
        pd.Timestamp(last.isoformat()),
        train_years=TRAIN_YEARS,
        test_years=TEST_YEARS,
        step_years=STEP_YEARS,
        wf_start=WF_START,
        wf_end=last.isoformat(),
    )
    if not folds:
        print("[RL-WF] no folds", flush=True)
        return 1

    test_rows: list[dict[str, Any]] = []
    train_rows: list[dict[str, Any]] = []
    pooled_off_t: list[dict[str, Any]] = []
    pooled_40_t: list[dict[str, Any]] = []
    embargo_t: list[dict[str, Any]] = []
    seen_off: set[tuple] = set()
    seen_40: set[tuple] = set()

    def _key(t: dict[str, Any]) -> tuple:
        return (t.get("sym"), t.get("opened"), t.get("closed"), round(float(t.get("pnl") or 0), 4))

    for fold in folds:
        off_te = _slice(off_t, fold.val_start, fold.val_end)
        d40_te = _slice(d40_t, fold.val_start, fold.val_end)
        off_tr = _slice(off_t, fold.train_start, fold.train_end)
        d40_tr = _slice(d40_t, fold.train_start, fold.train_end)
        m_off_te = book_stats(off_te)
        m_40_te = book_stats(d40_te)
        m_off_tr = book_stats(off_tr)
        m_40_tr = book_stats(d40_tr)
        test_rows.append(
            {
                "name": fold.name,
                "window": f"{fold.val_start} … {fold.val_end}",
                "off": m_off_te,
                "d40": m_40_te,
            }
        )
        train_rows.append(
            {
                "name": fold.name,
                "window": f"{fold.train_start} … {fold.train_end}",
                "off": m_off_tr,
                "d40": m_40_tr,
            }
        )
        for t in off_te:
            k = _key(t)
            if k not in seen_off:
                seen_off.add(k)
                pooled_off_t.append(t)
        for t in d40_te:
            k = _key(t)
            if k not in seen_40:
                seen_40.add(k)
                pooled_40_t.append(t)
        pick_40 = _better_ann(m_40_tr, m_off_tr) is True
        for t in (d40_te if pick_40 else off_te):
            embargo_t.append(t)

    pooled_off = book_stats(pooled_off_t)
    pooled_40 = book_stats(pooled_40_t)
    embargo = book_stats(embargo_t)
    decision = _decision(test_rows)
    write_html(test_rows, train_rows, pooled_off, pooled_40, embargo, decision)
    write_docs(test_rows, decision, pooled_off, pooled_40)
    write_metrics_csv(test_rows)
    print(f"[RL-WF] Wrote {OUT_DIR / 'compare.html'} folds={len(test_rows)}", flush=True)
    print(f"[RL-WF] {decision}", flush=True)
    ntfy = ROOT / "tools" / "ntfy_job_done.py"
    if ntfy.is_file():
        py = _resolve_python()
        subprocess.run(
            [
                py,
                str(ntfy),
                "--path",
                str(OUT_DIR / "compare.html"),
                "-t",
                "RL 40d time-stop WF",
                "-m",
                decision[:180],
            ],
            cwd=str(ROOT),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
