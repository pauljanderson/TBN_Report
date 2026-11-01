#!/usr/bin/env python3
"""RL controlled one-knob A/B for Mark: too_high OFF (0) vs 1.14.

CONTROL: rl_too_high=0 (DailyRun / run_rl.bat freeze)
TEST:    rl_too_high=1.14
Everything else matches current frozen RL architecture (full universe).

Usage:
  python tools/rl_too_high_114_off_ab_20261007.py
  python tools/rl_too_high_114_off_ab_20261007.py --workers 12
  python tools/rl_too_high_114_off_ab_20261007.py --summarize-only
  python tools/rl_too_high_114_off_ab_20261007.py --force
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
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
SA = ROOT / "stock_analysis"
DATA = ROOT / "data" / "newdata" / "data"
PER_SYMBOL = SA / "Per_Symbol_Optimized_Settings_Approved_Latest.json"

STAMP = "rl_too_high_off_vs_114_20261007"
OUT = DRIVE / "mark_experiments" / STAMP
RUNS = OUT / "runs"

CTRL_ID = "control_too_high_off"
TEST_ID = "test_too_high_114"
REMAIN_FRAC = 0.20
SOLD_FRAC = 0.80
TAG = "RL-TH-114"
IS_CUT = date(2024, 1, 1)
DEFAULT_WORKERS = 12

REQUEST = (
    "RL CONTROLLED A/B — TOO HIGH OFF vs 1.14. Use the current frozen Rocket Launcher "
    "architecture and current full universe. Change one variable only. CONTROL: "
    "rl_too_high=0 — OFF. TEST: rl_too_high=1.14. Keep everything else identical to the "
    "current frozen RL configuration, including: SMA qualification/rising-50 ON; Dip = 1.055; "
    "Expansion = 1.163 over 10 bars; Acceptance = 8/10 closes above SMA50; Stop = .934 vs "
    "signal low; Cut-the-losers OFF; ATR% filters OFF; Slope filter OFF; T+1 next-open fill; "
    "Cash/name = $47,500; Current full data/newdata/data universe; Frozen exit: 80% at +20%; "
    "remaining 20% stop moves to breakeven; runner target +40%; no time exit; no SMA target; "
    "same-bar BE/+40 = stop first. Run IS / OOS / FULL. Report for each arm: Trades, WR, "
    "Avg P&L, expectancy $, PF, Max DD, annualized ROR, Calmar, Sharpe, Avg Winner, Avg Loser, "
    "Avg Days Held, Median Days Held, position-weighted capital days, total capital days, "
    "PPCD, trades/year. Also report: Number of trades rejected by 1.14 versus OFF; "
    "Performance of the rejected trades as a separate cohort: N, WR, Avg P&L, PF, "
    "Avg/Median Days Held; IS/OOS breakdown of that rejected cohort. Do not test 1.13, "
    "neighboring thresholds, or any other parameter. Objective: determine whether Too High "
    "1.14 adds value versus the current OFF setting under the exact current frozen RL "
    "architecture, and whether this setting explains the trade-population difference we "
    "found between the earlier research book and current control."
)

LAYMAN = (
    "Rocket Launcher (RL) currently lets the next-day open fill almost any gap after a buy "
    "signal (Too High OFF). Turning Too High on at 1.14 skips fills where the open jumps too "
    "far above the signal low (fill must stay at or below signal_low × 1.14 × stop). We keep "
    "the same stock universe, buy rules, stop, and exit: sell 80% at +20%, move the leftover "
    "stop to the buy price, aim the rest at +40%. Only that fill gate changes. Buys before "
    "2024 are in-sample; 2024 onward is out of sample and for reading only. We also score "
    "the trades that OFF would take but 1.14 rejects, to see if the gate is cutting junk or "
    "good names — and whether it explains why older research books had fewer trades."
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
    "rl_dip_pct=1.055",
    "rl_cut_the_losers=1000",
    "rl_sma_target_off=1",
    "rl_exit_percent=0",
    "rl_exit_days=0",
    "rl_exit_calendar_days=0",
    "rl_scale_ladder=0.20:0.80:0",
    "rl_entry_target_pct=0.40",
    # House defaults made explicit for freeze clarity (rocket_rl_config):
    "rl_expansion=1.163",
    "rl_expansion_lookback_days=10",
    "rl_acc_min=8",
    "rl_stop_pct=0.934",
]

ARM_TOO_HIGH = {
    CTRL_ID: "0",
    TEST_ID: "1.14",
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
    ("Weighted capital days (position-weighted)", "cap_days", 0, ""),
    ("Total capital days (unweighted sum DAYS_HELD)", "cap_days_raw", 0, ""),
    ("Profit per capital day (PPCD) $", "ppc", 2, "$"),
    ("Trades / year", "tpy", 2, ""),
    ("Avg P&L % without best trade", "wo_max", 2, "%"),
]

DELTA_MAJOR = {
    "n", "wr", "avg_pnl", "expect_pct", "exp_d", "pf", "max_dd", "ann_ror",
    "calmar", "sharpe", "avg_win", "avg_loss", "avg_days", "med_days",
    "exposure_avg", "cap_days", "cap_days_raw", "ppc", "tpy", "wo_max",
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


def _trade_key(t: dict[str, Any]) -> tuple[str, str]:
    opened = t.get("opened")
    od = opened.isoformat() if isinstance(opened, date) else str(opened or "")
    return (str(t.get("sym") or "").upper(), od)


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
                    "sym": str(raw.get("SYMBOL") or "").upper(),
                }
            )
    return out


def _apply_exposure(m: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    if not rows or int(m.get("n") or 0) <= 0:
        m["expect_pct"] = float("nan")
        m["exposure_avg"] = float("nan")
        m["cap_days_raw"] = float("nan")
        m["partials"] = 0
        return
    cap = float(sum(r["exposure"] for r in rows))
    cap_raw = float(sum(float(r["days"]) for r in rows if math.isfinite(float(r["days"]))))
    pnl_d = float(m.get("pnl_d") or 0.0)
    n = int(m["n"])
    avg_exp = cap / n if n else 0.0
    ann = ann_ror_from_closed(total_pnl=pnl_d, n_trades=n, avg_days_held=avg_exp, brt_cash=RL_CASH)
    ann_f = float(ann) if ann is not None else float("nan")
    m["cap_days"] = cap
    m["cap_days_raw"] = cap_raw
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
    if not trades:
        return float("nan"), ""
    ov = overlay_ann_ror_max_dd(trades, cash=RL_CASH, initial_account=INIT)
    s = ov.get("sharpe")
    src = str(ov.get("sharpe_source") or "closed_exit_date_equity")
    if isinstance(s, (int, float)) and math.isfinite(float(s)):
        return float(s), src
    return float("nan"), src


def _harmonize_sharpe(ctrl: dict[str, Any], test: dict[str, Any]) -> None:
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


def _build_cmd(py: str, outdir: Path, arm: str, workers: int) -> list[str]:
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
    # Explicit arm knob LAST so CLI wins over any per-symbol JSON.
    cmd.extend(["-v", f"rl_too_high={ARM_TOO_HIGH[arm]}"])
    return cmd


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
    print(f"[{TAG}] start {arm} rl_too_high={ARM_TOO_HIGH[arm]} workers={workers} -> {outdir}", flush=True)
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
    packed["too_high"] = ARM_TOO_HIGH[arm_id]
    packed["folder"] = folder
    return packed


def _rejected_cohort(ctrl: dict[str, Any], test: dict[str, Any]) -> dict[str, Any]:
    """Control trades not present under test (fill-gate rejects), plus any test-only extras."""
    ctrl_map = {_trade_key(t): t for t in ctrl["trades"]}
    test_keys = {_trade_key(t) for t in test["trades"]}
    rejected = [ctrl_map[k] for k in ctrl_map if k not in test_keys]
    extras = [t for t in test["trades"] if _trade_key(t) not in ctrl_map]
    # Exposure rows for rejected (match by sym+opened)
    ctrl_exp = {
        (r["sym"], r["opened"].isoformat() if isinstance(r["opened"], date) else str(r["opened"])): r
        for r in ctrl.get("exposure_rows") or []
    }
    rej_rows = []
    for t in rejected:
        k = _trade_key(t)
        r = ctrl_exp.get(k)
        if r:
            rej_rows.append(r)
        else:
            rej_rows.append(
                {
                    "opened": t["opened"],
                    "days": t["days"],
                    "partial": False,
                    "exposure": float(t["days"]),
                    "sym": t["sym"],
                }
            )

    def _pack_slice(trades: list[dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, Any]:
        m = book_stats(trades)
        _apply_exposure(m, rows)
        s, src = _overlay_sharpe_for_trades(trades)
        m["sharpe"] = s
        m["sharpe_source"] = src
        return m

    is_t = [t for t in rejected if t["opened"] < IS_CUT]
    oos_t = [t for t in rejected if t["opened"] >= IS_CUT]
    is_r = [r for r in rej_rows if r["opened"] < IS_CUT]
    oos_r = [r for r in rej_rows if r["opened"] >= IS_CUT]
    return {
        "rejected": rejected,
        "extras": extras,
        "m_full": _pack_slice(rejected, rej_rows),
        "m_is": _pack_slice(is_t, is_r),
        "m_oos": _pack_slice(oos_t, oos_r),
        "n_rejected": len(rejected),
        "n_extras": len(extras),
    }


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


def _metrics_table(ctrl: dict[str, Any], test: dict[str, Any], split_key: str) -> str:
    head = "".join(
        [
            sortable_th("Metric", "text"),
            sortable_th("Control (OFF)", "num"),
            sortable_th("Test (1.14)", "num"),
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


def _cohort_table(rej: dict[str, Any]) -> str:
    head = "".join(
        [
            sortable_th("Slice", "text"),
            sortable_th("N", "num"),
            sortable_th("WR %", "num"),
            sortable_th("Avg P&L %", "num"),
            sortable_th("PF", "num"),
            sortable_th("Avg days", "num"),
            sortable_th("Median days", "num"),
            sortable_th("Expectancy $", "num"),
            sortable_th("Ann ROR %", "num"),
            sortable_th("Max DD %", "num"),
        ]
    )
    body = []
    for label, key in (("FULL rejected", "m_full"), ("IS rejected", "m_is"), ("OOS rejected", "m_oos")):
        m = rej[key]
        body.append(
            "<tr>"
            f"<td>{html_mod.escape(label)}</td>"
            f'<td data-sort-value="{m["n"]}">{m["n"]}</td>'
            f'<td data-sort-value="{m["wr"]}">{_fmt(m["wr"], 1, "%")}</td>'
            f'<td data-sort-value="{m["avg_pnl"]}">{_fmt(m["avg_pnl"], 2, "%")}</td>'
            f'<td data-sort-value="{m["pf"]}">{_fmt(m["pf"], 2, "")}</td>'
            f'<td data-sort-value="{m["avg_days"]}">{_fmt(m["avg_days"], 1, "")}</td>'
            f'<td data-sort-value="{m["med_days"]}">{_fmt(m["med_days"], 1, "")}</td>'
            f'<td data-sort-value="{m["exp_d"]}">{_fmt(m["exp_d"], 2, "$")}</td>'
            f'<td data-sort-value="{m.get("ann_ror", float("nan"))}">{_fmt(m.get("ann_ror"), 2, "%")}</td>'
            f'<td data-sort-value="{m.get("max_dd", float("nan"))}">{_fmt(m.get("max_dd"), 2, "%")}</td>'
            "</tr>"
        )
    return (
        f"{SWIPE_NOTE_HTML}"
        '<div class="table-wrap"><table class="sortable">'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def _verdict(ctrl: dict[str, Any], test: dict[str, Any], rej: dict[str, Any]) -> tuple[str, str]:
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
    rm = rej["m_full"]
    rej_note = (
        f" Rejected cohort N={rej['n_rejected']} "
        f"(WR {rm['wr']:.1f}%, Avg {rm['avg_pnl']:.2f}%, PF {rm['pf']:.2f})."
    )
    if rej["n_extras"]:
        rej_note += (
            f" Note: test has {rej['n_extras']} trades not in control "
            "(expected under slot/path dependence when early rejects free later capital — "
            "not new signals from the gate)."
        )
    note = (
        f"IS Avg% {i['avg_pnl']:.2f} vs {c['avg_pnl']:.2f}; "
        f"PF {i['pf']:.2f} vs {c['pf']:.2f}; "
        f"Ann ROR {i.get('ann_ror', float('nan')):.2f} vs {c.get('ann_ror', float('nan')):.2f}; "
        f"N {i['n']} vs {c['n']}. "
        f"OOS Avg% {o['avg_pnl']:.2f} vs {co['avg_pnl']:.2f}."
        + rej_note
    )
    if better_is and oos_soft:
        return "HOLD", note + " IS quality up; OOS softens — do not retune on OOS."
    if better_is and not n_ok:
        return "HOLD", note + " IS quality up but trade count fell hard."
    if better_is:
        return (
            "LEAN KEEP",
            note + " Research candidate only. Not gold. Not DailyRun.",
        )
    if worse_is:
        return "DISMISS", note + " IS quality worse than control (OFF)."
    return "HOLD", note + " IS quality close to control — no clear quality lift from 1.14."


def _line(m: dict[str, Any]) -> str:
    return (
        f"N={m['n']} WR={m['wr']:.1f}% Avg={m['avg_pnl']:.2f}% PF={m['pf']:.2f} "
        f"AnnROR={_fmt(m.get('ann_ror'), 2, '%')} MaxDD={_fmt(m.get('max_dd'), 2, '%')} "
        f"Calmar={_fmt(m.get('calmar'), 2, '')} Sharpe={_fmt(m.get('sharpe'), 2, '')} "
        f"cap_days={_fmt(m.get('cap_days'), 0, '')} PPCD={_fmt(m.get('ppc'), 2, '$')}"
    )


def _population_note(ctrl: dict[str, Any], test: dict[str, Any], rej: dict[str, Any]) -> str:
    cn = int(ctrl["m_full"]["n"])
    tn = int(test["m_full"]["n"])
    drop = cn - tn
    if cn <= 0:
        return "Population gap inconclusive (empty control)."
    pct = 100.0 * rej["n_rejected"] / cn
    if rej["n_rejected"] == 0 and drop == 0:
        return (
            "Too High 1.14 rejected zero control trades under this freeze — it does "
            "not explain a population gap vs OFF on the current full universe."
        )
    extras = int(rej.get("n_extras") or 0)
    return (
        f"Too High 1.14 removes {rej['n_rejected']} of {cn} control trades by key "
        f"({pct:.1f}% of OFF book) and, via slot/path effects, adds {extras} replacement "
        f"trades (closed N {cn} → {tn}; check: {cn} − {rej['n_rejected']} + {extras} = {tn}). "
        "If earlier research books used too_high≈1.14 (or similar) on a comparable universe, "
        "this knob can explain a large share of the OFF-vs-research population gap — but not "
        "as a pure one-for-one reject list, because capital contention reshuffles later fills. "
        "Confirm those books' freeze (universe + other knobs) before calling it the only cause."
    )


def write_docs(
    ctrl: dict[str, Any],
    test: dict[str, Any],
    rej: dict[str, Any],
    started: str,
    elapsed: str,
    ps_note: str,
) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    call, note = _verdict(ctrl, test, rej)
    pop = _population_note(ctrl, test, rej)

    for arm, packed in ((CTRL_ID, ctrl), (TEST_ID, test)):
        src = packed["closed"]
        shutil.copy2(src, OUT / f"{arm}_closed.csv")
        summary = packed.get("summary")
        if summary and Path(summary).is_file():
            shutil.copy2(summary, OUT / f"{arm}_summary.csv")

    # Rejected cohort CSV
    rej_csv = OUT / "rejected_cohort.csv"
    with rej_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["SYMBOL", "DATE_OPENED", "PNL_PCT", "DAYS_HELD", "EXIT_TYPE", "SLICE"],
        )
        w.writeheader()
        for t in rej["rejected"]:
            sl = "IS" if t["opened"] < IS_CUT else "OOS"
            w.writerow(
                {
                    "SYMBOL": t["sym"],
                    "DATE_OPENED": t["opened"].isoformat() if t["opened"] else "",
                    "PNL_PCT": t["pnl"],
                    "DAYS_HELD": t["days"],
                    "EXIT_TYPE": t.get("exit") or "",
                    "SLICE": sl,
                }
            )

    extras_flag = ""
    if rej["n_extras"]:
        extras_flag = (
            f'<p class="note"><strong>Slot / path dependence:</strong> Test has '
            f'{rej["n_extras"]} closed trades whose (SYMBOL, DATE_OPENED) keys are not in '
            "CONTROL. Too High only blocks fills; it does not invent signals. When an early "
            "fill is rejected, capital/slots can open for later names that CONTROL already "
            "had filled — so the books diverge beyond a pure reject set. Net closed: "
            f'CONTROL {int(ctrl["m_full"]["n"])} − rejected {rej["n_rejected"]} + extras '
            f'{rej["n_extras"]} = TEST {int(test["m_full"]["n"])}.</p>'
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RL too_high OFF vs 1.14 (Mark)</title>
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
<h1>Rocket Launcher Too High A/B — OFF vs 1.14</h1>
<p class="verdict"><strong>{html_mod.escape(call)}</strong> — {html_mod.escape(note)}
Research candidate only. Not gold. Not DailyRun. Choosing after seeing this table is
in-sample selection bias for any later adoption.</p>

<div class="callout">
<h2>What you asked</h2>
<pre style="white-space:pre-wrap;font-family:inherit;margin:0">{html_mod.escape(REQUEST)}</pre>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{html_mod.escape(LAYMAN)}</p>
</div>

<div class="note">
<p><strong>One knob.</strong> CONTROL <code>rl_too_high=0</code> (OFF). TEST <code>rl_too_high=1.14</code>.
Fill gate when on: next open ≤ signal low × too_high × stop
(<code>signal_low × 1.14 × 0.934</code>).</p>
<p><strong>Frozen shared architecture</strong> (matches <code>run_rl.bat</code> / DailyRun):
full <code>data/newdata/data</code> universe; <code>rl_mode=true</code>; zones off;
<code>indicator_buy=off</code>; Simple Moving Average (SMA) qualification / rising-50 ON
(<code>rl_sma_qual=1</code>); Dip 1.055; Expansion 1.163 over 10 bars; Acceptance 8/10 closes
above SMA50 (<code>rl_acc_min=8</code>); Stop 0.934 vs signal low; Cut-the-losers OFF (1000);
Average True Range (ATR) % filters OFF; slope OFF; T+1 next-open fill; cash/name $47,500;
partial exit: 80% at +20%, leftover stop → breakeven, runner +40%; no time exit; no SMA target;
same-bar BE/+40 = stop first.</p>
<p><strong>Per-symbol JSON.</strong> {html_mod.escape(ps_note)}</p>
<p><strong>IS / OOS.</strong> In-sample (IS) = entry &lt; 2024-01-01. Out-of-sample (OOS) =
entry ≥ 2024-01-01 (report-only; no retune). Annualized rate of return (Ann ROR) uses
<code>compare_format.ann_ror_from_closed</code> with position-weighted average days held
after the 80% scale. Profit factor (PF), Max drawdown (Max DD), Calmar, Sharpe as house helpers.
Started {html_mod.escape(started)}. Elapsed {html_mod.escape(elapsed)}. Click column headers to sort.</p>
</div>

{extras_flag}

<h2>FULL book</h2>
{_metrics_table(ctrl, test, "m_full")}
<p class="muted">FULL — Control: {_line(ctrl["m_full"])}<br/>FULL — Test: {_line(test["m_full"])}</p>

<h2>IS (entry before 2024-01-01)</h2>
{_metrics_table(ctrl, test, "m_is")}
<p class="muted">IS — Control: {_line(ctrl["m_is"])}<br/>IS — Test: {_line(test["m_is"])}</p>

<h2>OOS (entry on/after 2024-01-01, report-only)</h2>
{_metrics_table(ctrl, test, "m_oos")}
<p class="muted">OOS — Control: {_line(ctrl["m_oos"])}<br/>OOS — Test: {_line(test["m_oos"])}</p>

<h2>Rejected by 1.14 vs OFF</h2>
<p>Trade identity: <code>SYMBOL + DATE_OPENED</code>. Rejected = in CONTROL closed book,
not in TEST. Extras in TEST not in CONTROL: <strong>{rej["n_extras"]}</strong>
(slot/path replacements when rejects free later capital; not a second knob).</p>
<p><strong>N rejected = {rej["n_rejected"]}</strong>
({100.0 * rej["n_rejected"] / max(int(ctrl["m_full"]["n"]), 1):.1f}% of OFF closed trades).</p>
{_cohort_table(rej)}
<p class="muted">Rejected FULL: {_line(rej["m_full"])}<br/>
Rejected IS: {_line(rej["m_is"])}<br/>
Rejected OOS: {_line(rej["m_oos"])}</p>

<h2>Population gap vs earlier research</h2>
<p>{html_mod.escape(pop)}</p>

<p class="muted">Artifacts under <code>{html_mod.escape(str(OUT.relative_to(ROOT)))}</code>.
Runs under <code>runs/</code>. Slot cash ${RL_CASH:,.0f}; account overlay ${INIT:,.0f}.
Leftover frac after 80% sale: {REMAIN_FRAC:.2f}.</p>
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

## Freeze (shared — identical on both arms)

| Knob | Value |
|------|-------|
| Universe | `data/newdata/data` (full / ALL; no symbol-list restriction) |
| `rl_mode` | true |
| Zones | brt/yh/wpbr off |
| `indicator_buy` | off |
| `rl_sma_qual` | 1 (SMA qual / rising-50 ON) |
| `rl_dip_pct` | 1.055 |
| `rl_expansion` | 1.163 |
| `rl_expansion_lookback_days` | 10 |
| `rl_acc_min` | 8 (8/10 closes above SMA50) |
| `rl_stop_pct` | 0.934 |
| `rl_cut_the_losers` | 1000 (OFF) |
| ATR | `ATR_LOW=off` `ATR_HIGH=off` |
| `rl_slope_threshold` | 0 |
| Fill | T+1 next-open (engine default) |
| Cash/name | $47,500 |
| Exit | `rl_scale_ladder=0.20:0.80:0`, `rl_entry_target_pct=0.40`, `rl_sma_target_off=1`, time exits 0 |
| Per-symbol | {ps_note} |

## Arms (ENTRY fill-gate only)

| Arm | `rl_too_high` | Source |
|-----|---------------|--------|
| CONTROL `{CTRL_ID}` | `0` (OFF) | Fresh full-universe run `runs/{CTRL_ID}/` |
| TEST `{TEST_ID}` | `1.14` | Fresh full-universe run `runs/{TEST_ID}/` |

One-knob only. No 1.13 / neighbors.

## Rejected cohort

- Key: `SYMBOL + DATE_OPENED`
- Rejected = control trades absent under test
- Extras in test not in control: {rej["n_extras"]} (slot/path dependence; expected &gt; 0 under capital constraints)

## IS / OOS

- IS = entry &lt; 2024-01-01
- OOS = entry ≥ 2024-01-01 (report-only; no retune)
- KEEP/DISMISS on quality not N; OOS softens → HOLD
- Selection bias: picking KEEP after seeing this table is in-sample selection for later adoption

## Population-gap note

{pop}

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
- Rejected FULL: {_line(rej["m_full"])}
- Rejected IS: {_line(rej["m_is"])}
- Rejected OOS: {_line(rej["m_oos"])}

## Files

- `compare.html`
- `{CTRL_ID}_closed.csv` / `{TEST_ID}_closed.csv`
- `rejected_cohort.csv`
- `metrics.json` / `metrics.csv`
- `runs/`
"""
    (OUT / "BASELINE.md").write_text(baseline, encoding="utf-8")

    ab_plan = f"""# AB_PLAN — `{STAMP}`

## Hypothesis

Enabling Too High fill gate at 1.14 improves trade *quality* vs OFF under the exact current
frozen RL architecture (same universe, entries otherwise, stop, partial exit), without
requiring other knob changes.

## Design

- One knob: `rl_too_high` 0 vs 1.14
- Full `data/newdata/data` universe; match `run_rl.bat` freeze otherwise
- Both arms full engine reruns
- Rejected cohort scored as separate book
- No neighbor search (no 1.13)

## Decision rule

- Judge on IS quality first (WR, Avg P&L, PF, Ann ROR, DD)
- OOS report-only; if OOS softens → HOLD (do not retune)
- Research candidate ≠ gold ≠ DailyRun

## Started / elapsed

- Started: {started}
- Elapsed: {elapsed}
"""
    (OUT / "AB_PLAN.md").write_text(ab_plan, encoding="utf-8")

    def _m_clean(m: dict[str, Any]) -> dict[str, Any]:
        return {
            k: (float(v) if isinstance(v, (int, float)) else v)
            for k, v in m.items()
            if k != "exits"
        } | {"exits": m.get("exits", {})}

    metrics = {
        "stamp": STAMP,
        "verdict": call,
        "note": note,
        "population_note": pop,
        "cash": RL_CASH,
        "remain_frac": REMAIN_FRAC,
        "per_symbol_note": ps_note,
        "rejected_n": rej["n_rejected"],
        "extras_n": rej["n_extras"],
        "slices": {
            arm_id: {
                split: _m_clean(packed[split])
                for split in ("m_full", "m_is", "m_oos")
            }
            for arm_id, packed in ((CTRL_ID, ctrl), (TEST_ID, test))
        },
        "rejected": {
            split: _m_clean(rej[split]) for split in ("m_full", "m_is", "m_oos")
        },
    }
    (OUT / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")

    # Flat CSV for quick glance
    csv_path = OUT / "metrics.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        fields = [
            "arm", "slice", "n", "wr", "avg_pnl", "exp_d", "pf", "max_dd", "ann_ror",
            "calmar", "sharpe", "avg_win", "avg_loss", "avg_days", "med_days",
            "cap_days", "cap_days_raw", "ppc", "tpy",
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for arm_id, packed in (
            (CTRL_ID, ctrl),
            (TEST_ID, test),
            ("rejected_by_114", rej),
        ):
            for slice_name, key in (("FULL", "m_full"), ("IS", "m_is"), ("OOS", "m_oos")):
                m = packed[key]
                w.writerow(
                    {
                        "arm": arm_id,
                        "slice": slice_name,
                        "n": m.get("n"),
                        "wr": m.get("wr"),
                        "avg_pnl": m.get("avg_pnl"),
                        "exp_d": m.get("exp_d"),
                        "pf": m.get("pf"),
                        "max_dd": m.get("max_dd"),
                        "ann_ror": m.get("ann_ror"),
                        "calmar": m.get("calmar"),
                        "sharpe": m.get("sharpe"),
                        "avg_win": m.get("avg_win"),
                        "avg_loss": m.get("avg_loss"),
                        "avg_days": m.get("avg_days"),
                        "med_days": m.get("med_days"),
                        "cap_days": m.get("cap_days"),
                        "cap_days_raw": m.get("cap_days_raw"),
                        "ppc": m.get("ppc"),
                        "tpy": m.get("tpy"),
                    }
                )

    print(f"[{TAG}] wrote {html_path}", flush=True)
    print(f"[{TAG}] verdict={call}", flush=True)
    print(f"[{TAG}] rejected_n={rej['n_rejected']} extras_n={rej['n_extras']}", flush=True)
    return html_path


def _per_symbol_note() -> str:
    if not PER_SYMBOL.is_file():
        return (
            f"Per-symbol file missing at {PER_SYMBOL.name}; arms ran without "
            "--per-symbol-settings. CLI `-v rl_too_high=...` still set per arm."
        )
    try:
        raw = json.loads(PER_SYMBOL.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return f"Could not parse per-symbol JSON ({exc}); CLI arm knob still applied last."
    if raw == {} or raw == []:
        return (
            f"`{PER_SYMBOL.name}` is empty (`{{}}`). Passed via `--per-symbol-settings` "
            "for parity with run_rl.bat; cannot override `rl_too_high`. "
            "Each arm sets CLI `-v rl_too_high=...` last."
        )
    # Scan for too_high overrides
    hits = 0
    if isinstance(raw, dict):
        for _sym, cfg in raw.items():
            if isinstance(cfg, dict):
                for k in cfg:
                    if "too_high" in str(k).lower():
                        hits += 1
    if hits:
        return (
            f"Per-symbol JSON contains {hits} too_high-related key(s). "
            "CLI `-v rl_too_high=...` is applied last on each arm for a clean one-knob test; "
            "verify engine precedence if results look contaminated."
        )
    return (
        f"`{PER_SYMBOL.name}` present with no too_high keys. "
        "CLI `-v rl_too_high=...` set last on each arm."
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    ap.add_argument("--force", action="store_true", help="Rerun both arms even if closed exists")
    ap.add_argument("--summarize-only", action="store_true", help="Rebuild HTML from existing runs/")
    args = ap.parse_args()

    if not DATA.is_dir():
        raise SystemExit(f"missing universe {DATA}")

    OUT.mkdir(parents=True, exist_ok=True)
    RUNS.mkdir(parents=True, exist_ok=True)

    started = datetime.now().isoformat(timespec="seconds")
    t0 = time.time()
    py = _resolve_python()
    ps_note = _per_symbol_note()
    print(f"[{TAG}] {ps_note}", flush=True)

    if args.summarize_only:
        ctrl_dir = RUNS / CTRL_ID
        test_dir = RUNS / TEST_ID
        if not _find_latest(ctrl_dir, "RL_Closed_*.csv"):
            raise SystemExit(f"summarize-only: missing {ctrl_dir}")
        if not _find_latest(test_dir, "RL_Closed_*.csv"):
            raise SystemExit(f"summarize-only: missing {test_dir}")
    else:
        ctrl_dir = _run_arm(py, CTRL_ID, args.workers, force=args.force)
        test_dir = _run_arm(py, TEST_ID, args.workers, force=args.force)

    ctrl = _pack_arm(CTRL_ID, "CONTROL too_high=0 (OFF)", ctrl_dir)
    test = _pack_arm(TEST_ID, "TEST too_high=1.14", test_dir)
    _harmonize_sharpe(ctrl, test)
    rej = _rejected_cohort(ctrl, test)
    elapsed = f"{time.time() - t0:.0f}s"
    write_docs(ctrl, test, rej, started, elapsed, ps_note)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
