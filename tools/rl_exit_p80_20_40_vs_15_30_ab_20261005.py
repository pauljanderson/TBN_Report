#!/usr/bin/env python3
"""RL controlled exit A/B for Mark: p80@+20 leftover+40 vs p80@+15 leftover+30.

CONTROL reuses the current DailyRun partial-exit freeze closed book when knobs match.
TEST changes only the scale point and leftover target as one package.
Position-weighted capital days after the 80% sale (leftover frac 0.20).

Usage:
  python tools/rl_exit_p80_20_40_vs_15_30_ab_20261005.py
  python tools/rl_exit_p80_20_40_vs_15_30_ab_20261005.py --workers 24
  python tools/rl_exit_p80_20_40_vs_15_30_ab_20261005.py --rerun-control
  python tools/rl_exit_p80_20_40_vs_15_30_ab_20261005.py --summarize-only
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import json
import math
import shutil
import subprocess
import sys
import time
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
SA = ROOT / "stock_analysis"
DATA = ROOT / "data" / "newdata" / "data"
PER_SYMBOL = SA / "Per_Symbol_Optimized_Settings_Approved_Latest.json"

STAMP = "rl_exit_p80_20_40_vs_15_30_ab_20261005"
OUT = DRIVE / "mark_experiments" / STAMP
RUNS = OUT / "runs"
TMP = ROOT / f"tmp_{STAMP}"
CONTROL_STAMP = "261005120747"
CONTROL_CLOSED_SRC = DRIVE / f"RL_Closed_{CONTROL_STAMP}.csv"

CTRL_ID = "control_p80_20_40"
TEST_ID = "test_p80_15_30"
REMAIN_FRAC = 0.20
SOLD_FRAC = 0.80
TAG = "RL-EXIT-15-30"
IS_CUT = date(2024, 1, 1)
DEFAULT_WORKERS = 24

REQUEST = """RL CONTROLLED EXIT A/B — CURRENT EXIT vs +15/+30
Use the exact same RL trade population, entry logic, universe, filters, and date ranges as the current frozen RL system. Change exit logic only.
CONTROL — Current frozen RL exit
- Original stop remains active until +20%
- At +20%: sell 80%
- Remaining 20% runner stop moves to breakeven
- Runner target +40%
- No time exit
- Same-bar BE/+40: stop first
TEST — +15/+30
- Original stop remains active until +15%
- At +15%: sell 80%
- Remaining 20% runner stop moves to breakeven
- Runner target +30%
- No time exit
- Same-bar BE/+30: stop first
Do not change anything else. No parameter search or additional variations.
Report IS / OOS / FULL for CONTROL and TEST:
- Trade count
- Win rate
- Avg P&L / expectancy
- Profit factor
- Max drawdown
- Annualized ROR
- Calmar
- Sharpe
- Avg winner
- Avg loser
- Average days held
- Median days held
- Total/weighted capital days
- PPCD
- Exit-reason counts
Also report the absolute and percentage delta TEST vs CONTROL for the major metrics.
Important: partial-position capital utilization must be position-weighted after the 80% sale so capital-days/PPCD correctly reflect only the remaining 20% runner exposure.
This is one predefined controlled A/B based on the prior +15 timing diagnostic. Do not test neighboring targets, partial percentages, stops, or runner targets. for Mark"""

LAYMAN = (
    "Control is how Rocket Launcher exits today: keep the original stop until the trade is up 20%, "
    "then sell 80% of the shares, slide the leftover stop to the buy price, and aim what is left at +40%. "
    "The test does the same idea but scales at +15% and aims the leftover at +30%. Buys, universe, and "
    "filters stay identical. We only change when the big sale and the leftover target happen. After "
    "selling 80%, capital-days count the leftover 20% at one-fifth size so profit-per-capital-day is fair. "
    "Buys before 2024 are in-sample; 2024 onward is out of sample and for reading only."
)

COMMON_V = [
    "rl_mode=true",
    "brt_zones=false",
    "yh_zones=false",
    "wpbr_zones=false",
    "indicator_buy=off",
    "rl_sma_qual=1",
    "ATR_LOW=off",
    "ATR_HIGH=off",
    "rl_slope_threshold=0",
    "rl_too_high=0",
    "rl_dip_pct=1.055",
    "rl_cut_the_losers=1000",
    "rl_sma_target_off=1",
    "rl_exit_percent=0",
    "rl_exit_days=0",
    "rl_exit_calendar_days=0",
]

CTRL_EXIT = {
    "rl_scale_ladder": "0.20:0.80:0",
    "rl_entry_target_pct": "0.40",
}
TEST_EXIT = {
    "rl_scale_ladder": "0.15:0.80:0",
    "rl_entry_target_pct": "0.30",
}

METRIC_ROWS: list[tuple[str, str, int, str]] = [
    ("Closed trades", "n", 0, ""),
    ("Win rate (WR)", "wr", 1, "%"),
    ("Avg P&L %", "avg_pnl", 2, "%"),
    ("Expectancy %", "expect_pct", 2, "%"),
    ("Expectancy $", "exp_d", 2, "$"),
    ("Profit factor (PF)", "pf", 2, ""),
    ("Max drawdown (Max DD) %", "max_dd", 2, "%"),
    ("Annualized rate of return (Ann ROR) %", "ann_ror", 2, "%"),
    ("Calmar", "calmar", 2, ""),
    ("Sharpe", "sharpe", 2, ""),
    ("Avg winner %", "avg_win", 2, "%"),
    ("Avg loser %", "avg_loss", 2, "%"),
    ("Avg days held (unweighted)", "avg_days", 1, ""),
    ("Median days held (unweighted)", "med_days", 1, ""),
    ("Avg weighted days held", "exposure_avg", 1, ""),
    ("Weighted capital days", "cap_days", 0, ""),
    ("Profit per capital day (PPCD) $", "ppc", 2, "$"),
    ("Trades / year", "tpy", 2, ""),
    ("Avg P&L % without best trade", "wo_max", 2, "%"),
]

DELTA_MAJOR = {
    "n", "wr", "avg_pnl", "expect_pct", "exp_d", "pf", "max_dd", "ann_ror",
    "calmar", "sharpe", "avg_win", "avg_loss", "avg_days", "med_days",
    "exposure_avg", "cap_days", "ppc", "tpy", "wo_max",
}

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(DRIVE / "paul_experiments"))

from compare_format import (  # noqa: E402
    ann_ror_from_closed,
    calmar_ratio,
    format_money,
    format_money_delta,
    overlay_ann_ror_max_dd,
)
from report_page_extras import (  # noqa: E402
    RESPONSIVE_TABLE_CSS,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)
from rl_univ_compare_lists import (  # noqa: E402
    INIT,
    IS_CUT as _IS_CUT_DATE,
    RL_CASH,
    _find_latest,
    _resolve_python,
    book_stats,
    load_trades,
    pack_result,
    split_is_oos,
)

assert _IS_CUT_DATE == IS_CUT


def sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _parse_d(raw: Any) -> date | None:
    t = str(raw or "").strip()
    if not t or t.upper() in {"N/A", "NONE", "0"}:
        return None
    compact = t.replace("-", "").replace("/", "")[:8]
    for cand, fmt in ((t[:10], "%Y-%m-%d"), (compact, "%Y%m%d")):
        try:
            return datetime.strptime(cand, fmt).date()
        except ValueError:
            continue
    return None


def _f(raw: Any, default: float = 0.0) -> float:
    if raw is None:
        return default
    s = str(raw).strip().replace(",", "").replace("%", "").replace("$", "")
    if not s or s.lower() in {"nan", "none", "null", "n/a"}:
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _exposure_days(days_held: float, opened: date | None, partial: date | None) -> float:
    """Full slot through PARTIAL_DATE, then leftover frac until exit (RL partial books)."""
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


def _read_exposure_rows(closed_path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with closed_path.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened = _parse_d(raw.get("DATE OPENED") or raw.get("DATE_OPENED"))
            if opened is None:
                continue
            days = _f(raw.get("DAYS HELD") or raw.get("DAYS_HELD"))
            partial = _parse_d(raw.get("PARTIAL_DATE") or raw.get("PARTIAL DATE"))
            out.append(
                {
                    "opened": opened,
                    "days": days,
                    "partial": partial is not None,
                    "exposure": _exposure_days(days, opened, partial),
                }
            )
    return out


def _apply_exposure(m: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    if not rows or int(m.get("n") or 0) <= 0:
        m["expect_pct"] = float("nan")
        m["exposure_avg"] = float("nan")
        m["partials"] = 0
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
    m["expect_pct"] = float(m.get("avg_pnl") or float("nan"))
    m["partials"] = sum(1 for r in rows if r.get("partial"))
    cal = calmar_ratio(ann_f, m.get("max_dd"))
    m["calmar"] = float(cal) if cal is not None else float("nan")


def _weight_pack(p: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    _apply_exposure(p["m_full"], rows)
    _apply_exposure(p["m_is"], [r for r in rows if r["opened"] < IS_CUT])
    _apply_exposure(p["m_oos"], [r for r in rows if r["opened"] >= IS_CUT])


def _overlay_sharpe_for_trades(trades: list[dict[str, Any]]) -> tuple[float, str]:
    """Exit-date equity Sharpe so arms without EquityCurve stay comparable."""
    if not trades:
        return float("nan"), ""
    ov = overlay_ann_ror_max_dd(trades, cash=RL_CASH, initial_account=INIT)
    s = ov.get("sharpe")
    src = str(ov.get("sharpe_source") or "closed_exit_date_equity")
    if isinstance(s, (int, float)) and math.isfinite(float(s)):
        return float(s), src
    return float("nan"), src


def _harmonize_sharpe(ctrl: dict[str, Any], test: dict[str, Any]) -> None:
    """If either arm lacks a host EquityCurve, use closed overlay Sharpe on both."""
    need = not (ctrl.get("equity_curve") and Path(ctrl["equity_curve"]).is_file())
    need = need or not (test.get("equity_curve") and Path(test["equity_curve"]).is_file())
    if not need:
        return
    for packed in (ctrl, test):
        trades = packed["trades"]
        is_t, oos_t = split_is_oos(trades)
        for key, rows in (("m_full", trades), ("m_is", is_t), ("m_oos", oos_t)):
            s, src = _overlay_sharpe_for_trades(rows)
            packed[key]["sharpe"] = s
            packed[key]["sharpe_source"] = src


def _exit_knobs(arm: str) -> dict[str, str]:
    return dict(CTRL_EXIT if arm == CTRL_ID else TEST_EXIT)


def _build_cmd(py: str, outdir: Path, arm: str, workers: int) -> list[str]:
    knobs = _exit_knobs(arm)
    cmd = [
        py,
        "-u",
        str(SA / "rocket_tbn.py"),
        str(DATA),
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
    for item in COMMON_V:
        cmd.extend(["-v", item])
    for k, v in knobs.items():
        cmd.extend(["-v", f"{k}={v}"])
    return cmd


def _copy_control_artifacts(dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    if not CONTROL_CLOSED_SRC.is_file():
        raise FileNotFoundError(f"missing control closed book {CONTROL_CLOSED_SRC}")
    for path in sorted(DRIVE.glob(f"RL_*_{CONTROL_STAMP}*")):
        if path.is_file():
            shutil.copy2(path, dest / path.name)
    closed = dest / f"RL_Closed_{CONTROL_STAMP}.csv"
    if not closed.is_file():
        raise FileNotFoundError(f"control closed not copied to {closed}")
    (dest / "SOURCE.txt").write_text(
        f"Reused DailyRun freeze book stamp {CONTROL_STAMP}\n"
        f"Source: drive/RL_*_{CONTROL_STAMP}*\n"
        f"Exit: rl_scale_ladder=0.20:0.80:0 rl_entry_target_pct=0.40\n",
        encoding="utf-8",
    )
    return closed


def _run_arm(py: str, arm: str, workers: int, *, force: bool) -> Path:
    outdir = RUNS / arm
    closed = _find_latest(outdir, "RL_Closed_*.csv") if outdir.is_dir() else None
    if (
        not force
        and closed
        and closed.is_file()
        and closed.stat().st_size > 0
        and load_trades(closed)
    ):
        print(f"[{TAG}] reuse existing {arm} -> {closed}", flush=True)
        return outdir
    if outdir.exists():
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True)
    cmd = _build_cmd(py, outdir, arm, workers)
    log_path = outdir / "run.log"
    print(f"[{TAG}] start {arm} workers={workers} -> {outdir}", flush=True)
    t0 = time.time()
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write("CMD: " + " ".join(cmd) + "\n\n")
        log.flush()
        rc = subprocess.call(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(ROOT))
    elapsed = time.time() - t0
    print(f"[{TAG}] done {arm} rc={rc} elapsed={elapsed:.0f}s", flush=True)
    if rc != 0:
        raise SystemExit(f"{arm} failed rc={rc}. See {log_path}")
    closed = _find_latest(outdir, "RL_Closed_*.csv")
    if not closed:
        raise SystemExit(f"no RL_Closed in {outdir}")
    return outdir


def _pack_arm(arm_id: str, label: str, folder: Path) -> dict[str, Any]:
    closed = _find_latest(folder, "RL_Closed_*.csv")
    if closed is None:
        raise FileNotFoundError(f"no RL_Closed in {folder}")
    run = {
        "arm": {"id": arm_id, "label": label, "symbols": []},
        "closed": closed,
        "summary": _find_latest(folder, "RL_Summary_*.csv"),
        "equity_meta": _find_latest(folder, "RL_EquityMeta_*.csv"),
        "report": _find_latest(folder, "RL_Report_*.csv"),
        "equity_curve": _find_latest(folder, "RL_EquityCurve_*.csv"),
        "trades": load_trades(closed),
        "ok": True,
    }
    syms = sorted({t["sym"] for t in run["trades"] if t.get("sym")})
    run["arm"]["symbols"] = syms
    packed = pack_result(run)
    rows = _read_exposure_rows(closed)
    _weight_pack(packed, rows)
    packed["exposure_rows"] = rows
    packed["exit_knobs"] = _exit_knobs(arm_id)
    packed["folder"] = folder
    return packed


def _fmt(v: Any, nd: int, suffix: str) -> str:
    if not isinstance(v, (int, float)) or not math.isfinite(float(v)):
        return "—"
    x = float(v)
    if suffix == "$":
        return format_money(x)
    if nd == 0 and suffix == "":
        return f"{int(round(x)):,}"
    return f"{x:,.{nd}f}{suffix}"


def _delta_abs(a: Any, b: Any, nd: int, suffix: str) -> str:
    if not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        return "—"
    if not (math.isfinite(float(a)) and math.isfinite(float(b))):
        return "—"
    d = float(b) - float(a)
    if suffix == "$":
        return format_money_delta(d)
    if nd == 0 and suffix == "":
        return f"{int(round(d)):+,}"
    return f"{d:+,.{nd}f}{suffix}"


def _delta_pct(a: Any, b: Any) -> str:
    if not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        return "—"
    if not (math.isfinite(float(a)) and math.isfinite(float(b))):
        return "—"
    if abs(float(a)) < 1e-12:
        return "—"
    return f"{(float(b) - float(a)) / abs(float(a)) * 100.0:+.1f}%"


def _exit_table(ctrl: dict[str, Any], test: dict[str, Any]) -> str:
    keys = sorted(
        set(ctrl["m_full"].get("exits", {})) | set(test["m_full"].get("exits", {}))
    )
    head = "".join(
        [
            sortable_th("EXIT TYPE", "text"),
            sortable_th("Control N", "num"),
            sortable_th("Control %", "num"),
            sortable_th("Test N", "num"),
            sortable_th("Test %", "num"),
            sortable_th("Δ N", "num"),
        ]
    )
    cn = max(int(ctrl["m_full"]["n"]), 1)
    tn = max(int(test["m_full"]["n"]), 1)
    body = []
    for k in keys:
        c = int(ctrl["m_full"].get("exits", {}).get(k, 0))
        t = int(test["m_full"].get("exits", {}).get(k, 0))
        body.append(
            "<tr>"
            f"<td>{html_mod.escape(k)}</td>"
            f"<td data-sort-value=\"{c}\">{c}</td>"
            f"<td data-sort-value=\"{100.0 * c / cn}\">{100.0 * c / cn:.1f}%</td>"
            f"<td data-sort-value=\"{t}\">{t}</td>"
            f"<td data-sort-value=\"{100.0 * t / tn}\">{100.0 * t / tn:.1f}%</td>"
            f"<td data-sort-value=\"{t - c}\">{t - c:+d}</td>"
            "</tr>"
        )
    return (
        f"{SWIPE_NOTE_HTML}"
        '<div class="table-wrap"><table class="sortable">'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def _metrics_table(ctrl: dict[str, Any], test: dict[str, Any], split_key: str) -> str:
    head = "".join(
        [
            sortable_th("Metric", "text"),
            sortable_th("Control", "num"),
            sortable_th("Test", "num"),
            sortable_th("Δ abs (Test−Control)", "num"),
            sortable_th("Δ % vs Control", "num"),
        ]
    )
    c = ctrl[split_key]
    t = test[split_key]
    body = []
    for label, key, nd, suffix in METRIC_ROWS:
        a = c.get(key, float("nan"))
        b = t.get(key, float("nan"))
        d_abs = _delta_abs(a, b, nd, suffix) if key in DELTA_MAJOR else "—"
        d_pct = _delta_pct(a, b) if key in DELTA_MAJOR else "—"
        body.append(
            "<tr>"
            f"<td>{html_mod.escape(label)}</td>"
            f'<td data-sort-value="{a}">{_fmt(a, nd, suffix)}</td>'
            f'<td data-sort-value="{b}">{_fmt(b, nd, suffix)}</td>'
            f"<td>{d_abs}</td>"
            f"<td>{d_pct}</td>"
            "</tr>"
        )
    return (
        f"{SWIPE_NOTE_HTML}"
        '<div class="table-wrap"><table class="sortable">'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def _verdict(ctrl: dict[str, Any], test: dict[str, Any]) -> tuple[str, str]:
    i, c = test["m_is"], ctrl["m_is"]
    o, co = test["m_oos"], ctrl["m_oos"]
    n_ok = c["n"] > 0 and i["n"] >= 0.85 * c["n"]
    better_is = (
        math.isfinite(i["avg_pnl"])
        and math.isfinite(c["avg_pnl"])
        and i["avg_pnl"] > c["avg_pnl"] + 0.05
        and math.isfinite(i["pf"])
        and math.isfinite(c["pf"])
        and i["pf"] >= c["pf"] - 0.03
        and math.isfinite(i.get("ann_ror", float("nan")))
        and math.isfinite(c.get("ann_ror", float("nan")))
        and i["ann_ror"] >= c["ann_ror"] - 0.5
    )
    worse_is = (
        math.isfinite(i["avg_pnl"])
        and math.isfinite(c["avg_pnl"])
        and (
            i["avg_pnl"] < c["avg_pnl"] - 0.10
            or (i["pf"] + 0.05 < c["pf"] and i["avg_pnl"] <= c["avg_pnl"])
            or (
                math.isfinite(i["max_dd"])
                and math.isfinite(c["max_dd"])
                and i["max_dd"] > c["max_dd"] + 3.0
            )
        )
    )
    oos_soft = (
        math.isfinite(o["avg_pnl"])
        and math.isfinite(co["avg_pnl"])
        and o["avg_pnl"] < co["avg_pnl"] - 0.15
    )
    note = (
        f"IS Avg% {i['avg_pnl']:.2f} vs {c['avg_pnl']:.2f}; "
        f"PF {i['pf']:.2f} vs {c['pf']:.2f}; "
        f"Ann ROR {i.get('ann_ror', float('nan')):.2f} vs {c.get('ann_ror', float('nan')):.2f}; "
        f"N {i['n']} vs {c['n']}. "
        f"OOS Avg% {o['avg_pnl']:.2f} vs {co['avg_pnl']:.2f}."
    )
    if better_is and oos_soft:
        return "HOLD", note + " IS quality up; OOS softens — do not retune on OOS."
    if better_is and not n_ok:
        return "HOLD", note + " IS quality up but trade count fell."
    if better_is:
        return (
            "LEAN KEEP",
            note + " Research candidate only. Not gold. Not DailyRun.",
        )
    if worse_is:
        return "DISMISS", note + " IS quality worse than control."
    return "HOLD", note + " IS quality close to control."


def _line(m: dict[str, Any]) -> str:
    return (
        f"N={m['n']} WR={m['wr']:.1f}% Avg={m['avg_pnl']:.2f}% PF={m['pf']:.2f} "
        f"AnnROR={_fmt(m.get('ann_ror'), 2, '%')} MaxDD={_fmt(m.get('max_dd'), 2, '%')} "
        f"Calmar={_fmt(m.get('calmar'), 2, '')} Sharpe={_fmt(m.get('sharpe'), 2, '')} "
        f"cap_days={_fmt(m.get('cap_days'), 0, '')} PPCD={_fmt(m.get('ppc'), 2, '$')}"
    )


def write_docs(ctrl: dict[str, Any], test: dict[str, Any], started: str, elapsed: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    call, note = _verdict(ctrl, test)
    for arm, packed in ((CTRL_ID, ctrl), (TEST_ID, test)):
        src = packed["closed"]
        shutil.copy2(src, OUT / f"{arm}_closed.csv")
        summary = packed.get("summary")
        if summary and Path(summary).is_file():
            shutil.copy2(summary, OUT / f"{arm}_summary.csv")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RL exit A/B — p80 +20/+40 vs +15/+30 (Mark)</title>
<style>
:root {{ --bg:#f7f4ee; --ink:#1c1b19; --muted:#5c574e; --line:#d9d3c4; --card:#fffdf8; --accent:#2f5d50; }}
*{{box-sizing:border-box}}
body{{margin:0;font-family:Georgia,"Iowan Old Style",serif;background:var(--bg);color:var(--ink);line-height:1.45}}
main{{max-width:1100px;margin:0 auto;padding:1.25rem 1rem 2.5rem}}
h1,h2,h3{{font-weight:600}}
.callout,.verdict,.note{{background:var(--card);border:1px solid var(--line);padding:12px 14px;margin:12px 0 18px;border-radius:2px}}
.verdict{{border-color:#c9a227;background:#fff8e8}}
.muted{{color:var(--muted)}}
code{{font-family:ui-monospace,Consolas,monospace;font-size:0.92em}}
ul{{padding-left:1.2rem}}
{SORTABLE_TH_CSS}
{RESPONSIVE_TABLE_CSS}
</style>
</head>
<body>
<main>
<h1>Rocket Launcher exit A/B — current p80 +20/+40 vs +15/+30</h1>
<p class="verdict"><strong>{html_mod.escape(call)}</strong> — {html_mod.escape(note)}
Research candidate only. Not gold. Not DailyRun. Exit-only change; selection among these two arms after seeing the table is in-sample selection bias for any later adoption.</p>

<div class="callout">
<h2>What you asked</h2>
<pre style="white-space:pre-wrap;font-family:inherit;margin:0">{html_mod.escape(REQUEST)}</pre>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{html_mod.escape(LAYMAN)}</p>
</div>

<div class="note">
<p><strong>Arms (exit only).</strong> Shared entries/universe match DailyRun Rocket Launcher (RL):
<code>rl_mode=true</code>, zones off, <code>indicator_buy=off</code>, <code>rl_too_high=0</code>,
<code>rl_dip_pct=1.055</code>, <code>rl_cut_the_losers=1000</code>, ATR off, slope 0.
Control: <code>rl_scale_ladder=0.20:0.80:0</code>, <code>rl_entry_target_pct=0.40</code>.
Test: <code>rl_scale_ladder=0.15:0.80:0</code>, <code>rl_entry_target_pct=0.30</code>.
Simple Moving Average (SMA) target off; no time exit. Same-bar breakeven / target: stop first.</p>
<p><strong>Position-weighted capital days.</strong> Until PARTIAL_DATE, count a full slot.
After the 80% sale, count leftover exposure at {REMAIN_FRAC:.0%} (SCALE leftover frac {REMAIN_FRAC:.2f}).
Names that never scale use full DAYS_HELD. Profit per capital day (PPCD) =
equal-slot dollars (<code>PNL% × ${RL_CASH:,.0f}</code>) / weighted capital days.
Unweighted average / median days held stay calendar days open. Annualized rate of return (Ann ROR)
uses the house formula with weighted average days held after the scale.</p>
<p><strong>IS / OOS.</strong> In-sample (IS) = entry &lt; 2024-01-01. Out-of-sample (OOS) = entry ≥ 2024-01-01 (report-only; no retune).
Control closed book reused from <code>drive/RL_Closed_{CONTROL_STAMP}.csv</code> when knobs match the freeze.
Earlier exits can free a slot sooner, so trade count need not match exactly even with identical entry knobs.
Sharpe uses exit-date equity overlay on both arms when either arm lacks a host EquityCurve (fair compare).
Started {html_mod.escape(started)}. Elapsed {html_mod.escape(elapsed)}. Click column headers to sort.</p>
</div>

<h2>FULL book</h2>
{_metrics_table(ctrl, test, "m_full")}
<p class="muted">FULL — Control: {_line(ctrl["m_full"])}<br/>FULL — Test: {_line(test["m_full"])}</p>

<h2>IS (entry before 2024-01-01)</h2>
{_metrics_table(ctrl, test, "m_is")}
<p class="muted">IS — Control: {_line(ctrl["m_is"])}<br/>IS — Test: {_line(test["m_is"])}</p>

<h2>OOS (entry on/after 2024-01-01, report-only)</h2>
{_metrics_table(ctrl, test, "m_oos")}
<p class="muted">OOS — Control: {_line(ctrl["m_oos"])}<br/>OOS — Test: {_line(test["m_oos"])}</p>

<h2>Exit-reason counts (FULL)</h2>
{_exit_table(ctrl, test)}

<h2>Partials</h2>
<p>Control scaled {ctrl["m_full"].get("partials", 0)} / {ctrl["m_full"]["n"]} names.
Test scaled {test["m_full"].get("partials", 0)} / {test["m_full"]["n"]} names.</p>

<p class="muted">Artifacts under <code>{html_mod.escape(str(OUT.relative_to(ROOT)))}</code>.
Runs under <code>runs/</code>. Slot cash ${RL_CASH:,.0f}; account overlay ${INIT:,.0f}.</p>
{SORTABLE_TABLE_SCRIPT}
</main>
</body>
</html>
"""
    html_path = OUT / "compare.html"
    html_path.write_text(html, encoding="utf-8")

    baseline = f"""# BASELINE — `{STAMP}`

Audience: **Mark**. Research candidate only. Not gold. Not DailyRun.

## What you asked

{REQUEST}

## In plain English

{LAYMAN}

## Freeze (shared)

| Knob | Value |
|------|-------|
| Universe | `data/newdata/data` (full) |
| `rl_mode` | true |
| Zones | brt/yh/wpbr off |
| `indicator_buy` | off |
| `rl_too_high` | 0 (DailyRun) |
| `rl_dip_pct` | 1.055 |
| `rl_cut_the_losers` | 1000 |
| ATR | off |
| `rl_slope_threshold` | 0 |
| `rl_sma_target_off` | 1 |
| Time exit | off (`rl_exit_percent/days/calendar_days=0`) |

## Arms (EXIT only)

| Arm | `rl_scale_ladder` | `rl_entry_target_pct` | Source |
|-----|-------------------|-----------------------|--------|
| CONTROL `{CTRL_ID}` | `0.20:0.80:0` | `0.40` | Reused `drive/RL_Closed_{CONTROL_STAMP}.csv` (+ companion RL_* files) |
| TEST `{TEST_ID}` | `0.15:0.80:0` | `0.30` | Fresh run under `runs/{TEST_ID}/` |

One predefined package change (scale point **and** leftover target together). No neighbors.

## Position-weighted capital days

- Full slot from entry through `PARTIAL_DATE` (inclusive day count matching RL partial books).
- After 80% sale: leftover frac **{REMAIN_FRAC:.2f}**.
- Never scaled: full `DAYS_HELD`.
- PPCD $ = sum(PNL%/100 × ${RL_CASH:,.0f}) / weighted capital days.
- Ann ROR house formula via `compare_format.ann_ror_from_closed` using **weighted** average days held.

## IS / OOS

- IS = entry &lt; 2024-01-01
- OOS = entry ≥ 2024-01-01 (report-only; no retune)
- KEEP/DISMISS on quality not N; OOS softens → HOLD

## Verdict

**{call}**

{note}

## Headline lines

- FULL control: {_line(ctrl["m_full"])}
- FULL test: {_line(test["m_full"])}
- IS control: {_line(ctrl["m_is"])}
- IS test: {_line(test["m_is"])}
- OOS control: {_line(ctrl["m_oos"])}
- OOS test: {_line(test["m_oos"])}

## Files

- `compare.html`
- `{CTRL_ID}_closed.csv` / `{TEST_ID}_closed.csv`
- `AB_PLAN.md`
- `runs/`
"""
    (OUT / "BASELINE.md").write_text(baseline, encoding="utf-8")

    ab_plan = f"""# AB_PLAN — `{STAMP}`

## Hypothesis

Scaling 80% earlier at +15% with a leftover target of +30% (vs house +20%/+40%) improves
quality (WR, Avg P&L / expectancy, Ann ROR, DD/Calmar/Sharpe, PF) without collapsing N,
on the same RL entry universe.

## Design

- One change package: exit scale point + leftover target together (as specified).
- Entries, universe, filters, stop, partial %, SMA-off, no time exit: frozen.
- No neighbor search.
- Control reuse of DailyRun freeze book `{CONTROL_STAMP}` when present.
- Position-weighted capital days / PPCD required.

## Decision rule

- Judge on IS quality first.
- OOS report-only; if OOS softens → HOLD (do not retune).
- Research candidate ≠ gold ≠ DailyRun.

## Started / elapsed

- Started: {started}
- Elapsed: {elapsed}
"""
    (OUT / "AB_PLAN.md").write_text(ab_plan, encoding="utf-8")

    metrics = {
        "stamp": STAMP,
        "verdict": call,
        "note": note,
        "cash": RL_CASH,
        "remain_frac": REMAIN_FRAC,
        "control_source": str(CONTROL_CLOSED_SRC),
        "slices": {
            arm_id: {
                split: {
                    k: (float(v) if isinstance(v, (int, float)) else v)
                    for k, v in packed[split].items()
                    if k != "exits"
                }
                | {"exits": packed[split].get("exits", {})}
                for split in ("m_full", "m_is", "m_oos")
            }
            for arm_id, packed in ((CTRL_ID, ctrl), (TEST_ID, test))
        },
    }
    (OUT / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")
    print(f"[{TAG}] wrote {html_path}", flush=True)
    print(f"[{TAG}] verdict={call}", flush=True)
    return html_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    ap.add_argument("--rerun-control", action="store_true", help="Fresh control run instead of reuse")
    ap.add_argument("--force-test", action="store_true", help="Rerun test even if closed exists")
    ap.add_argument("--summarize-only", action="store_true", help="Rebuild HTML from existing runs/")
    args = ap.parse_args()

    if not DATA.is_dir():
        raise SystemExit(f"missing universe {DATA}")

    OUT.mkdir(parents=True, exist_ok=True)
    RUNS.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)

    started = datetime.now().isoformat(timespec="seconds")
    t0 = time.time()
    py = _resolve_python()

    if args.summarize_only:
        ctrl_dir = RUNS / CTRL_ID
        test_dir = RUNS / TEST_ID
        if not _find_latest(ctrl_dir, "RL_Closed_*.csv"):
            raise SystemExit(f"summarize-only: missing {ctrl_dir}")
        if not _find_latest(test_dir, "RL_Closed_*.csv"):
            raise SystemExit(f"summarize-only: missing {test_dir}")
    else:
        if args.rerun_control:
            ctrl_dir = _run_arm(py, CTRL_ID, args.workers, force=True)
        else:
            ctrl_dir = RUNS / CTRL_ID
            ctrl_dir.mkdir(parents=True, exist_ok=True)
            existing_ctrl = _find_latest(ctrl_dir, "RL_Closed_*.csv")
            if existing_ctrl and existing_ctrl.is_file() and existing_ctrl.stat().st_size > 0:
                print(f"[{TAG}] reuse control folder {ctrl_dir}", flush=True)
            else:
                print(f"[{TAG}] copying control artifacts stamp={CONTROL_STAMP}", flush=True)
                _copy_control_artifacts(ctrl_dir)
        test_dir = _run_arm(py, TEST_ID, args.workers, force=args.force_test)

    ctrl = _pack_arm(CTRL_ID, "CONTROL p80 +20 / leftover +40", ctrl_dir)
    test = _pack_arm(TEST_ID, "TEST p80 +15 / leftover +30", test_dir)
    _harmonize_sharpe(ctrl, test)
    elapsed = f"{time.time() - t0:.0f}s"
    write_docs(ctrl, test, started, elapsed)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
