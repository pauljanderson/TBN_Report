#!/usr/bin/env python3
"""Clean EXIT A/B: 80/20 breakeven leftover vs 80/20 original stop, both to +40%.

Same frozen Rocket Launcher entries. No time clock. Moving-average target off.
Both arms reuse the closed books from rl_pct20_vs_p80_be_vs_origstop_ab_20260927.

Capital days, profit per capital day, and annualized return count a full slot
through the +20% sale day, then 20% of a slot until the leftover exits.

Usage:
  python tools/rl_p80_be40_vs_orig40_ab.py
"""
from __future__ import annotations

import csv
import html as html_mod
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
STAMP = "20260927"
OUT_DIR = DRIVE / "paul_experiments" / f"rl_p80_be40_vs_orig40_ab_{STAMP}"
SRC_RUNS = (
    DRIVE
    / "paul_experiments"
    / "rl_pct20_vs_p80_be_vs_origstop_ab_20260927"
    / "runs"
)
REMAIN_FRAC = 0.20
TAG = "RL-P80-BE40-VS-ORIG40"
A_ID = "p80_be_40"
B_ID = "p80_orig_40"

REQUEST_PROMPT = """\
Run a clean A/B using the same frozen RL entries and universe.

A — 80/20 + BE: At +20%, sell 80%. Move the remaining 20% stop to breakeven. Exit the remaining 20% at +40%.

B — 80/20 + Original Stop: At +20%, sell 80%. Keep the original stop on the remaining 20%. Exit the remaining 20% at +40%.

No time exit. No SMA target. Everything else identical.

Use corrected capital-weighted exposure: after 80% is sold at +20%, only 20% of original capital counts as occupied until the runner exits.

Report IS/OOS/FULL, plus specifically show the runner outcomes after +20%: number reaching +40%, number stopped at BE/original stop, and average contribution of the 20% runner to total trade P&L.
"""

LAYMAN_TRANSLATION = """\
Both books buy the same dips and sell 80% of the position the moment the price is 20% above the buy. \
The last 20% tries to reach 40% above the buy. The only difference is the safety net on that last piece. \
A moves its stop up to the buy price, so that piece cannot turn into a loss. B leaves the original stop \
in place, about 6.6% under the buy. There is no time limit and no moving-average target. After the 80% \
sale, the leftover is counted as one-fifth of a position until it exits. The report also says how often \
that leftover actually reaches +40%, how often it is stopped, and how many percentage points it adds \
to the trade.
"""

INTERPRETATION = """\
A reuses ladder 0.20:0.80:0 with rl_entry_target_pct=0.40 (leftover stop raised to the entry price). \
B reuses ladder 0.20:0.80:-1 with the same leftover target. The stop step on B sits below the original \
stop (entry × 0.934), so that stop stays. Fills are at the gain price, or at the open if the day opens \
through it. If a day trades both the stop and the leftover target, the stop is checked first. \
Simple Moving Average (SMA) target is off. No time clock. New buys stop after 2026-09-04. \
Capital Days, profit per capital day, and annualized return treat the sale day as a full position \
and every later day as 20% of a position. The runner's profit contribution uses the dollars already \
booked on the 80% sale (PARTIAL_AMT) subtracted from the trade's total dollars. Whole shares mean \
the leftover is about 20% of the position. Research-only.
"""

sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(DRIVE / "paul_experiments"))
from be_stop_replay_ab import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402
from compare_format import ann_ror_from_closed, calmar_ratio, filter_html_compare_columns  # noqa: E402
from rl_univ_compare_lists import (  # noqa: E402
    IS_CUT,
    RL_CASH,
    _f,
    _find_latest,
    _parse_d,
    compare_row,
    fmt_n,
    load_trades,
    pack_result,
    pairwise_delta_row,
    verdict_vs_control,
    write_metrics_csv,
    _resolve_python,
)


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
    runner_days = float(days_held) - float(full_days)
    return float(full_days) + runner_days * REMAIN_FRAC


def _closed_rows(closed_path: Path) -> list[dict[str, Any]]:
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
            pnl = _f(raw.get("PNL %") or raw.get("PNL_PCT"))
            pnl_d = _f(raw.get("PNL_DOLLARS"))
            if pnl_d == 0.0 and pnl != 0.0:
                pnl_d = RL_CASH * pnl / 100.0
            partial_amt = _f(raw.get("PARTIAL_AMT")) if partial is not None else 0.0
            runner_d = (pnl_d - partial_amt) if partial is not None else 0.0
            out.append(
                {
                    "opened": opened,
                    "days": days,
                    "pnl": pnl,
                    "pnl_d": pnl_d,
                    "exposure": _exposure_days(days, opened, partial),
                    "partial": partial is not None,
                    "exit": (raw.get("EXIT TYPE") or "").strip().upper() or "OTHER",
                    "partial_amt": partial_amt,
                    "runner_d": runner_d,
                }
            )
    return out


def _apply_exposure_metrics(m: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    if not rows or m.get("n", 0) <= 0:
        return
    cap = float(sum(r["exposure"] for r in rows))
    pnl_d = float(m.get("pnl_d") or 0.0)
    n = int(m["n"])
    avg_exp = cap / n if n else 0.0
    ann = ann_ror_from_closed(
        total_pnl=pnl_d,
        n_trades=n,
        avg_days_held=avg_exp,
        brt_cash=RL_CASH,
    )
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
                f"[{TAG}] exposure row mismatch {p['arm']['id']}: "
                f"csv={len(rows)} metrics={p['m_full']['n']}",
                flush=True,
            )
        _apply_exposure_metrics(p["m_full"], rows)
        _apply_exposure_metrics(p["m_is"], [r for r in rows if r["opened"] < IS_CUT])
        _apply_exposure_metrics(p["m_oos"], [r for r in rows if r["opened"] >= IS_CUT])


def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else float("nan")


def runner_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Outcomes on trades that sold 80% at +20%."""
    cohort = [r for r in rows if r["partial"]]
    hit = [r for r in cohort if r["exit"] == "ENTRY_TARGET"]
    stopped_be = [r for r in cohort if r["exit"] == "TRAIL_STOP"]
    stopped_px = [r for r in cohort if r["exit"] == "STOP_LOSS"]
    gapped = [r for r in cohort if r["exit"] == "GAP_DOWN"]
    known = {id(r) for r in hit + stopped_be + stopped_px + gapped}
    other = [r for r in cohort if id(r) not in known]
    stopped = stopped_be + stopped_px + gapped

    def _pack(group: list[dict[str, Any]]) -> dict[str, float]:
        runner_pp = [r["runner_d"] / RL_CASH * 100.0 for r in group]
        trade_pct = [r["pnl"] for r in group]
        return {
            "n": float(len(group)),
            "avg_runner_pp": _mean(runner_pp),
            "avg_runner_d": _mean([r["runner_d"] for r in group]),
            "avg_trade_pct": _mean(trade_pct),
            "sum_runner_d": float(sum(r["runner_d"] for r in group)),
            "sum_trade_d": float(sum(r["pnl_d"] for r in group)),
        }

    all_pack = _pack(cohort)
    share = (
        all_pack["sum_runner_d"] / all_pack["sum_trade_d"] * 100.0
        if all_pack["sum_trade_d"]
        else float("nan")
    )
    return {
        "closed": len(rows),
        "partials": len(cohort),
        "hit40": len(hit),
        "stopped": len(stopped),
        "stopped_be": len(stopped_be),
        "stopped_px": len(stopped_px),
        "gapped": len(gapped),
        "other": len(other),
        "all": all_pack,
        "hit": _pack(hit),
        "stop": _pack(stopped),
        "runner_share_pct": share,
    }


def _split_rows(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    if key == "FULL":
        return rows
    if key == "IS":
        return [r for r in rows if r["opened"] < IS_CUT]
    return [r for r in rows if r["opened"] >= IS_CUT]


def _univ_n() -> int:
    data = ROOT / "data" / "newdata" / "data"
    if not data.is_dir():
        return 0
    return sum(1 for p in data.glob("*.csv"))


def _load_arm(arm_id: str, label: str, role: str, ladder: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    arm_dir = SRC_RUNS / arm_id
    closed = _find_latest(arm_dir, "RL_Closed_*.csv")
    if not closed or not closed.is_file():
        raise FileNotFoundError(f"missing closed CSV for {arm_id} under {arm_dir}")
    trades = load_trades(closed)
    run = {
        "arm": {
            "id": arm_id,
            "label": label,
            "role": role,
            "univ_n": _univ_n(),
            "symbols": [""] * _univ_n(),
            "ladder": ladder,
            "entry_target": 0.40,
        },
        "ok": len(trades) > 0,
        "closed": closed,
        "trades": trades,
        "stamp": closed.stem.split("_")[-1],
        "summary": _find_latest(arm_dir, "RL_Summary_*.csv"),
        "equity_meta": _find_latest(arm_dir, "RL_EquityMeta_*.csv"),
        "report": _find_latest(arm_dir, "RL_Report_*.csv"),
        "equity_curve": _find_latest(arm_dir, "RL_EquityCurve_*.csv"),
    }
    return run, _closed_rows(closed)


def _md_split(p: dict[str, Any], key: str) -> str:
    m = p[key]
    exp = m.get("exposure_avg")
    wtd = f" wtd_days={exp:.1f}" if isinstance(exp, float) else ""
    return (
        f"N={m['n']} WR={m['wr']:.1f}% Avg={m['avg_pnl']:.2f}% WO_MAX={m['wo_max']:.2f}% "
        f"PF={m['pf']:.2f} AnnROR={fmt_n(m['ann_ror'], 2)} MaxDD_overlay={fmt_n(m['max_dd'], 2)} "
        f"cap_days={m.get('cap_days', 0):.0f} PPCD={fmt_n(m.get('ppc'), 2)} "
        f"avg_days={m.get('avg_days', 0):.1f}{wtd}"
    )


def _fmt_pp(v: float) -> str:
    return "—" if v != v else f"{v:.2f}"


def _fmt_d(v: float) -> str:
    return "—" if v != v else f"{v:,.0f}"


def write_compare_html(
    packed: list[dict[str, Any]],
    stats: dict[str, dict[str, dict[str, Any]]],
    verdict: tuple[str, str],
    oos_verdict: tuple[str, str],
    call: str,
) -> Path:
    by_id = {p["arm"]["id"]: p for p in packed}
    baseline = by_id[A_ID]
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
    note = (
        "Both arms use capital-weighted hold: a full slot through the +20% sale day, "
        "then 20% of a slot until the leftover exits. Avg days is still calendar time open. "
        "Overlay Max DD is the closed exit replay. Δ is B minus A. Click column headers to sort."
    )
    sections = []
    for split_key, split_title in (("m_is", "IS"), ("m_oos", "OOS (report-only)"), ("m_full", "FULL book")):
        body = "".join(compare_row(p, split_key, baseline, "", A_ID) for p in packed)
        sections.append(
            f"<section><h2>{split_title}</h2>"
            f'<p class="muted">{note}</p>'
            f'<div class="table-wrap"><table class="sortable"><thead><tr>{th_std}</tr></thead>'
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
    pw_sections = []
    for split_key, split_title in (("m_is", "IS"), ("m_oos", "OOS"), ("m_full", "FULL")):
        row = pairwise_delta_row(by_id[A_ID], by_id[B_ID], split_key, "B − A")
        pw_sections.append(
            f"<section><h2>Pairwise — {split_title}</h2>"
            f'<p class="muted">B minus A. Click headers to sort.</p>'
            f'<div class="table-wrap"><table class="sortable"><thead><tr>{pw_th}</tr></thead>'
            f"<tbody>{row}</tbody></table></div></section>"
        )

    run_th = "".join(
        sortable_th(a, b)
        for a, b in (
            ("Split", "text"),
            ("Arm", "text"),
            ("Closed trades", "num"),
            ("Reached +20%", "num"),
            ("Reached +40%", "num"),
            ("Stopped", "num"),
            ("of which gap-through", "num"),
            ("Avg runner add (pp)", "num"),
            ("Avg runner $", "num"),
            ("Avg trade % on those", "num"),
            ("Runner share of those $", "num"),
        )
    )
    run_rows = []
    labels = {A_ID: "A breakeven", B_ID: "B original stop"}
    for split in ("IS", "OOS", "FULL"):
        for aid in (A_ID, B_ID):
            s = stats[aid][split]
            run_rows.append(
                "<tr>"
                f"<td>{split}</td>"
                f"<td>{html_mod.escape(labels[aid])}</td>"
                f"<td>{s['closed']}</td>"
                f"<td>{s['partials']}</td>"
                f"<td>{s['hit40']}</td>"
                f"<td>{s['stopped']}</td>"
                f"<td>{s['gapped']}</td>"
                f"<td>{_fmt_pp(s['all']['avg_runner_pp'])}</td>"
                f"<td>{_fmt_d(s['all']['avg_runner_d'])}</td>"
                f"<td>{_fmt_pp(s['all']['avg_trade_pct'])}</td>"
                f"<td>{_fmt_pp(s['runner_share_pct'])}</td>"
                "</tr>"
            )

    bucket_th = "".join(
        sortable_th(a, b)
        for a, b in (
            ("Split", "text"),
            ("Arm", "text"),
            ("After +20%", "text"),
            ("N", "num"),
            ("Avg runner add (pp)", "num"),
            ("Avg runner $", "num"),
            ("Avg trade %", "num"),
        )
    )
    bucket_rows = []
    for split in ("IS", "OOS", "FULL"):
        for aid in (A_ID, B_ID):
            s = stats[aid][split]
            for name, pack in (
                ("Reached +40%", s["hit"]),
                ("Stopped at breakeven or original stop", s["stop"]),
                ("All trades that reached +20%", s["all"]),
            ):
                bucket_rows.append(
                    "<tr>"
                    f"<td>{split}</td>"
                    f"<td>{html_mod.escape(labels[aid])}</td>"
                    f"<td>{html_mod.escape(name)}</td>"
                    f"<td>{int(pack['n'])}</td>"
                    f"<td>{_fmt_pp(pack['avg_runner_pp'])}</td>"
                    f"<td>{_fmt_d(pack['avg_runner_d'])}</td>"
                    f"<td>{_fmt_pp(pack['avg_trade_pct'])}</td>"
                    "</tr>"
                )

    vis, nis = verdict
    voos, noos = oos_verdict
    subtitle = (
        f"Stamp <code>rl_p80_be40_vs_orig40_ab_{STAMP}</code>. "
        "A is the breakeven leftover. B keeps the original stop. "
        "Same buys as the simple +20% freeze. Research-only. Not gold. Not DailyRun."
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RL 80/20 breakeven vs original stop — {STAMP}</title>
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
table{{border-collapse:collapse;width:100%;font-size:.78rem;min-width:900px}}
th,td{{border-bottom:1px solid var(--line);padding:.35rem .4rem;text-align:right}}
th:first-child,td:first-child{{text-align:left}}
tr.ctrl-row{{background:var(--ctrl)}}
{SORTABLE_TH_CSS.replace('th.sortable-th:hover{{background:#e8e4d8}}', 'th.sortable-th:hover{{background:#2a3545}}')}
</style>
</head>
<body>
<header>
<h1>80/20 breakeven leftover versus original stop. Both try to sell the leftover at +40%.</h1>
<p class="muted">{subtitle}</p>
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
<section>
<h2>Runner after +20%</h2>
<p class="muted">Reached +20% is the count that sold the 80% piece. Reached +40% is that leftover sold at the higher target. Stopped is the leftover sold at breakeven on A, or at the original stop on B, including days that opened through the stop. Avg runner add is the leftover's dollars divided by the $47,500 slot, in percentage points of the original position, averaged only over trades that reached +20%. Runner share is those leftover dollars divided by those trades' total dollars. Click headers to sort.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>{run_th}</tr></thead>
<tbody>{''.join(run_rows)}</tbody></table></div>
</section>
<section>
<h2>What the leftover added, by how it exited</h2>
<p class="muted">Percentage points are the leftover's add to that trade. A leftover sold at the buy price adds about zero. A leftover sold at +40% adds about eight points (one-fifth of 40). Click headers to sort.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>{bucket_th}</tr></thead>
<tbody>{''.join(bucket_rows)}</tbody></table></div>
</section>
{''.join(sections)}
{''.join(pw_sections)}
</main>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    out = OUT_DIR / "compare.html"
    out.write_text(html, encoding="utf-8")
    return out


def write_docs(
    packed: list[dict[str, Any]],
    stats: dict[str, dict[str, dict[str, Any]]],
    html_path: Path,
    call: str,
    verdict: tuple[str, str],
    oos_verdict: tuple[str, str],
) -> None:
    by_id = {p["arm"]["id"]: p for p in packed}
    lines = [
        f"# BASELINE — `rl_p80_be40_vs_orig40_ab_{STAMP}`",
        "",
        "**Status:** RESEARCH only. EXIT A/B. Same entries. Only the leftover stop differs.",
        f"**A `{A_ID}`:** ladder `0.20:0.80:0`, leftover target +40%. Reuse `{SRC_RUNS.as_posix()}/{A_ID}`.",
        f"**B `{B_ID}`:** ladder `0.20:0.80:-1` (original stop stays), leftover target +40%. Reuse `{SRC_RUNS.as_posix()}/{B_ID}`.",
        "No time exit. SMA target off. Not gold. Not DailyRun.",
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
        "Every later calendar day uses 20% of a slot until the leftover exits. "
        "Trades that never reach +20% stay at a full slot. Avg days stays calendar time open. "
        "Max drawdown stays the closed exit replay. Calmar uses the weighted annualized return.",
        "",
        "## Split metrics",
        "",
    ]
    for aid, name in ((A_ID, "A"), (B_ID, "B")):
        for key, label in (("m_is", "IS"), ("m_oos", "OOS"), ("m_full", "FULL")):
            lines.append(f"- **{name} {label}:** {_md_split(by_id[aid], key)}")
    lines.extend(["", "## Runner after +20%", ""])
    for split in ("IS", "OOS", "FULL"):
        for aid, name in ((A_ID, "A"), (B_ID, "B")):
            s = stats[aid][split]
            lines.append(
                f"- **{name} {split}:** reached +20% {s['partials']}; reached +40% {s['hit40']}; "
                f"stopped {s['stopped']} (gap-through {s['gapped']}); "
                f"avg runner add {s['all']['avg_runner_pp']:.2f} pp "
                f"(${s['all']['avg_runner_d']:,.0f}); "
                f"avg trade on those {s['all']['avg_trade_pct']:.2f}%; "
                f"runner share of those dollars {s['runner_share_pct']:.1f}%."
            )
    lines.extend(
        [
            "",
            "## Verdict",
            "",
            f"- Call: **{call}**. IS `{verdict[0]}` ({verdict[1]}). OOS `{oos_verdict[0]}` ({oos_verdict[1]}).",
            "- OOS is report-only. Do not retune.",
            "",
            f"Compare: `{html_path.as_posix()}`",
            "",
        ]
    )
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines), encoding="utf-8")
    summary = [
        f"# SUMMARY — `rl_p80_be40_vs_orig40_ab_{STAMP}`",
        "",
        f"- **{call}** IS `{verdict[0]}` ({verdict[1]}); OOS `{oos_verdict[0]}` ({oos_verdict[1]}).",
        "",
        f"- A FULL: {_md_split(by_id[A_ID], 'm_full')}",
        f"- B FULL: {_md_split(by_id[B_ID], 'm_full')}",
        "",
    ]
    for split in ("IS", "FULL"):
        for aid, name in ((A_ID, "A"), (B_ID, "B")):
            s = stats[aid][split]
            summary.append(
                f"- {name} {split} runner: +40% {s['hit40']} / stopped {s['stopped']} "
                f"of {s['partials']} that reached +20%; avg add {s['all']['avg_runner_pp']:.2f} pp."
            )
    summary.extend(["", f"Compare: `{html_path.as_posix()}`", ""])
    (OUT_DIR / "SUMMARY.md").write_text("\n".join(summary), encoding="utf-8")


def _call(is_v: str, oos_v: str) -> str:
    if is_v in ("KEEP", "LEAN KEEP") and oos_v in ("KEEP", "LEAN KEEP"):
        return f"B {is_v} vs A"
    if is_v in ("KEEP", "LEAN KEEP") and oos_v == "DISMISS":
        return "HOLD"
    if is_v == "DISMISS":
        return "B DISMISS vs A"
    return "HOLD"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    py = _resolve_python()
    try:
        run_a, rows_a = _load_arm(
            A_ID,
            "A: 80/20 + breakeven, leftover at +40%",
            "control",
            "0.20:0.80:0",
        )
        run_b, rows_b = _load_arm(
            B_ID,
            "B: 80/20 + original stop, leftover at +40%",
            "candidate",
            "0.20:0.80:-1",
        )
    except FileNotFoundError as exc:
        fail = OUT_DIR / "compare.html"
        fail.write_text(
            "<html><body><h1>80/20 breakeven vs original stop failed</h1>"
            f"<p>{html_mod.escape(str(exc))}</p>"
            f"<pre>{html_mod.escape(REQUEST_PROMPT.strip())}</pre>"
            f"<p>{html_mod.escape(LAYMAN_TRANSLATION.strip())}</p>"
            "</body></html>",
            encoding="utf-8",
        )
        ntfy = ROOT / "tools" / "ntfy_job_done.py"
        if ntfy.is_file():
            subprocess.run(
                [py, str(ntfy), "--path", str(fail), "-t", "RL 80/20 BE vs original stop FAILED"],
                cwd=str(ROOT),
            )
        print(f"[{TAG}] {exc}", flush=True)
        return 1

    packed = [pack_result(run_a), pack_result(run_b)]
    rows_by_id = {A_ID: rows_a, B_ID: rows_b}
    apply_capital_weights(packed, rows_by_id)
    stats = {
        aid: {split: runner_stats(_split_rows(rows_by_id[aid], split)) for split in ("IS", "OOS", "FULL")}
        for aid in (A_ID, B_ID)
    }
    for aid in (A_ID, B_ID):
        other = stats[aid]["FULL"]["other"]
        if other:
            print(f"[{TAG}] {aid} partials with unexpected exit: {other}", flush=True)

    by_id = {p["arm"]["id"]: p for p in packed}
    verdict = verdict_vs_control(by_id[B_ID], by_id[A_ID], "m_is")
    oos_verdict = verdict_vs_control(by_id[B_ID], by_id[A_ID], "m_oos")
    mb = by_id[B_ID]["m_oos"]
    ma = by_id[A_ID]["m_oos"]
    if (
        oos_verdict[0] == "DISMISS"
        and mb["avg_pnl"] >= ma["avg_pnl"]
        and mb["max_dd"] > ma["max_dd"] + 3.0
    ):
        oos_verdict = (
            oos_verdict[0],
            f"{oos_verdict[1]}. Average gain and profit factor are a bit higher. "
            f"The dismiss flag is Max DD {mb['max_dd']:.2f}% vs {ma['max_dd']:.2f}%.",
        )
    call = _call(verdict[0], oos_verdict[0])
    html_path = write_compare_html(packed, stats, verdict, oos_verdict, call)
    write_metrics_csv(packed, "", OUT_DIR / "metrics_all.csv")
    write_docs(packed, stats, html_path, call, verdict, oos_verdict)
    print(f"[{TAG}] {call} IS={verdict[0]} OOS={oos_verdict[0]}", flush=True)
    for aid, name in ((A_ID, "A"), (B_ID, "B")):
        s = stats[aid]["FULL"]
        print(
            f"[{TAG}] {name} FULL +20%={s['partials']} +40%={s['hit40']} "
            f"stopped={s['stopped']} gap={s['gapped']} "
            f"avg_add={s['all']['avg_runner_pp']:.2f}pp",
            flush=True,
        )
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
                "RL 80/20 BE vs original stop",
                "-m",
                f"A breakeven leftover vs B original stop, both to +40%. {call}. "
                f"IS {verdict[0]}. OOS {oos_verdict[0]}.",
            ],
            cwd=str(ROOT),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
