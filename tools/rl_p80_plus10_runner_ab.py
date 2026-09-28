#!/usr/bin/env python3
"""RL EXIT A/B: 80/20 leftover stop at +10% vs breakeven vs original stop.

A (reuse): sell 80% at +20%, leftover stop to breakeven, leftover target +40%.
B (reuse): sell 80% at +20%, original stop stays, leftover target +40%.
C (new): sell 80% at +20%, leftover stop to +10% above entry, leftover target +40%.

No time clock. SMA target off. Same frozen entries.
Capital days: full slot through the +20% sale day, then 20% of a slot.

Usage:
  python tools/rl_p80_plus10_runner_ab.py --workers 8
  python tools/rl_p80_plus10_runner_ab.py --summarize-only
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
OUT_DIR = DRIVE / "paul_experiments" / f"rl_p80_plus10_runner_ab_{STAMP}"
RUNS_DIR = OUT_DIR / "runs"
SRC_RUNS = (
    DRIVE
    / "paul_experiments"
    / "rl_pct20_vs_p80_be_vs_origstop_ab_20260927"
    / "runs"
)
CONTROL_DATA_END = "20260904"
HOUSE_STOP = 0.934
HOUSE_CUT = 1000
HOUSE_DIP = 1.055
TH13 = 1.13
MIN_AVG_VOL = 10_000
MIN_TRIGGER_VOL = 5_000
REMAIN_FRAC = 0.20
TAG = "RL-P80-PLUS10"

A_ID = "p80_be_40"
B_ID = "p80_orig_40"
C_ID = "p80_p10_40"
ARM_ORDER = {A_ID: 0, B_ID: 1, C_ID: 2}
LADDER_C = "0.20:0.80:0.10"

REQUEST_PROMPT = """\
Run one new RL exit arm: 80/20 with +10% protected runner, targeting +40%.

Use the exact same frozen RL entries, universe, and original stop.

When a trade reaches +20% from entry:

Immediately sell 80% of the position at +20%.
Keep the remaining 20% as the runner.
Immediately move the stop on that remaining 20% to +10% above the original entry price.
Keep the runner's profit target at +40% above the original entry price.

Therefore, after reaching +20%, the remaining 20% has only two exits: +10% stop or +40% target.

No time exit. No SMA target. Everything else identical.

Use corrected capital weighting: full capital through the +20% partial-sale day; after that, only 20% of the original capital counts as occupied until the runner exits.

Compare against:
A: 80%@+20 / 20% runner BE stop → +40
B: 80%@+20 / 20% runner original stop → +40
C: 80%@+20 / 20% runner +10% stop → +40

Report IS/OOS/FULL with Avg P&L, PF, Ann ROR, Max DD, Calmar, Sharpe, expectancy, capital days and PPCD.

For the runner specifically, report: reached +20%, reached +40%, stopped at +10%, average runner contribution, and how many trades that hit the +10% stop would subsequently have reached +40% under the original-stop arm.
"""

LAYMAN_TRANSLATION = """\
All three books buy the same dips and sell 80% as soon as the price is 20% above the buy. The last 20% \
tries to reach 40% above the buy. The only difference is where that leftover gets sold if it fails. \
A moves the stop up to the buy price. B leaves the original stop, about 6.6% under the buy. C, the new \
one, moves the stop to 10% above the buy, so the leftover can still give back some of the gain but cannot \
fall all the way back to the buy. There is no time limit and no moving-average target. After the 80% sale, \
only one-fifth of the money is counted as still in the trade. The report also says how often C's leftover \
was stopped at +10%, and how many of those same buys went on to +40% when the stop was left at the original level.
"""

INTERPRETATION = """\
A reuses ladder 0.20:0.80:0 and B reuses ladder 0.20:0.80:-1, both with rl_entry_target_pct=0.40, \
from rl_pct20_vs_p80_be_vs_origstop_ab_20260927. C is new: ladder 0.20:0.80:0.10, same leftover target. \
The 0.10 stop step sets the leftover stop to entry × 1.10, which is above the original stop (entry × 0.934), \
so the stop moves. Fills are at the gain price, or at the open if the day opens through it. On the day \
+20% is first reached, the new stop is checked on that same daily bar: if that bar's low is already through \
+10%, the leftover sells at +10% that day. On any later day, the stop is checked before the +40% target. \
Simple Moving Average (SMA) target is off. No time clock. New buys stop after 2026-09-04. \
Capital Days, profit per capital day, and annualized return count a full slot through the sale day \
and 20% of a slot after that. The runner's contribution is the trade's dollars minus the profit already \
booked on the 80% sale. Whole shares mean the leftover is about 20% of the position. Research-only.
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


def _entry_freeze_v(*, ladder: str, entry_target: float) -> list[str]:
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
        f"rl_dip_pct={HOUSE_DIP}",
        "rl_expansion=1.163",
        f"rl_stop_pct={HOUSE_STOP}",
        "rl_target_pct=1.2",
        "rl_sma_target_off=1",
        f"rl_cut_the_losers={HOUSE_CUT}",
        "rl_exit_percent=0",
        "rl_exit_days=0",
        "rl_exit_calendar_days=0",
        "rl_max_hold_bars=0",
        "rl_max_hold_calendar_days=0",
        f"rl_entry_target_pct={entry_target}",
        "rl_post_target_reentry_bars=0",
        f"rl_too_high={TH13}",
        f"rl_min_avg_vol={MIN_AVG_VOL}",
        f"rl_min_trigger_vol={MIN_TRIGGER_VOL}",
        f"entry_end_date={CONTROL_DATA_END}",
        f"rl_scale_ladder={ladder}",
    ]
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
    runner_days = float(days_held) - float(full_days)
    return float(full_days) + runner_days * REMAIN_FRAC


def _read_rows(closed_path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with closed_path.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened = _parse_d(raw.get("DATE OPENED") or raw.get("DATE_OPENED"))
            if opened is None:
                continue
            closed = _parse_d(raw.get("DATE CLOSED") or raw.get("DATE_CLOSED"))
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
            entry = _f(raw.get("ENTRY PRICE") or raw.get("ENTRY_PRICE"))
            exit_px = _f(raw.get("EXIT PRICE") or raw.get("EXIT_PRICE"))
            out.append(
                {
                    "sym": (raw.get("SYMBOL") or "").strip().upper(),
                    "opened": opened,
                    "closed": closed,
                    "days": days,
                    "pnl": pnl,
                    "pnl_d": pnl_d,
                    "exposure": _exposure_days(days, opened, partial),
                    "partial": partial is not None,
                    "partial_date": partial,
                    "exit": (raw.get("EXIT TYPE") or "").strip().upper() or "OTHER",
                    "partial_amt": partial_amt,
                    "runner_d": (pnl_d - partial_amt) if partial is not None else 0.0,
                    "entry": entry,
                    "exit_px": exit_px,
                }
            )
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


def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else float("nan")


def _split_rows(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    if key == "IS":
        return [r for r in rows if r["opened"] < IS_CUT]
    if key == "OOS":
        return [r for r in rows if r["opened"] >= IS_CUT]
    return rows


def runner_stats(rows: list[dict[str, Any]], *, stop_plus10: bool) -> dict[str, Any]:
    cohort = [r for r in rows if r["partial"]]
    hit = [r for r in cohort if r["exit"] == "ENTRY_TARGET"]
    if stop_plus10:
        stopped = [r for r in cohort if r["exit"] == "TRAIL_STOP"]
    else:
        stopped = [r for r in cohort if r["exit"] in ("TRAIL_STOP", "STOP_LOSS", "GAP_DOWN")]
    same_day = [
        r
        for r in stopped
        if r["partial_date"] is not None and r["closed"] is not None and r["partial_date"] == r["closed"]
    ]
    known_ids = {id(r) for r in hit + stopped}
    other = [r for r in cohort if id(r) not in known_ids]

    def _pack(group: list[dict[str, Any]]) -> dict[str, float]:
        return {
            "n": float(len(group)),
            "avg_runner_pp": _mean([r["runner_d"] / RL_CASH * 100.0 for r in group]),
            "avg_runner_d": _mean([r["runner_d"] for r in group]),
            "avg_trade_pct": _mean([r["pnl"] for r in group]),
        }

    all_pack = _pack(cohort)
    return {
        "closed": len(rows),
        "partials": len(cohort),
        "hit40": len(hit),
        "stopped": len(stopped),
        "same_day_stop": len(same_day),
        "other": len(other),
        "all": all_pack,
        "hit": _pack(hit),
        "stop": _pack(stopped),
    }


def counterfactual(c_rows: list[dict[str, Any]], b_rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Same buy in C stopped at +10%. Did B's leftover reach +40% after that?"""
    bmap: dict[tuple[str, date], dict[str, Any]] = {}
    dupes = 0
    for r in b_rows:
        key = (r["sym"], r["opened"])
        if key in bmap:
            dupes += 1
        bmap[key] = r
    out: dict[str, dict[str, int]] = {"dupes_b": {"n": dupes}}
    for split in ("IS", "OOS", "FULL"):
        stops = [
            r
            for r in _split_rows(c_rows, split)
            if r["partial"] and r["exit"] == "TRAIL_STOP"
        ]
        reached = 0
        later = 0
        same_day = 0
        b_stopped = 0
        unmatched = 0
        b_other = 0
        for r in stops:
            b = bmap.get((r["sym"], r["opened"]))
            if b is None:
                unmatched += 1
                continue
            if b["partial"] and b["exit"] == "ENTRY_TARGET":
                reached += 1
                if b["closed"] is not None and r["closed"] is not None:
                    if b["closed"] > r["closed"]:
                        later += 1
                    elif b["closed"] == r["closed"]:
                        same_day += 1
            elif b["exit"] in ("STOP_LOSS", "GAP_DOWN", "TRAIL_STOP"):
                b_stopped += 1
            else:
                b_other += 1
        out[split] = {
            "stopped_plus10": len(stops),
            "b_reached_40": reached,
            "b_reached_40_later": later,
            "b_reached_40_same_day": same_day,
            "b_stopped": b_stopped,
            "unmatched": unmatched,
            "b_other": b_other,
        }
    return out


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


def _arm_run_from_dir(arm_id: str, label: str, role: str, ladder: str, src_dir: Path) -> dict[str, Any]:
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
            "ladder": ladder,
            "entry_target": 0.40,
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
    for v in _entry_freeze_v(ladder=LADDER_C, entry_target=0.40):
        cmd.extend(["-v", v])
    return cmd


def run_arm_c(py: str, workers: int, skip_existing: bool) -> dict[str, Any]:
    arm_dir = RUNS_DIR / C_ID
    arm_dir.mkdir(parents=True, exist_ok=True)
    closed = _find_latest(arm_dir, "RL_Closed_*.csv")
    if skip_existing and closed and closed.stat().st_size > 0 and load_trades(closed):
        return _arm_run_from_dir(
            C_ID,
            "C: 80/20 +10% stop, leftover at +40%",
            "candidate",
            LADDER_C,
            arm_dir,
        )
    cmd = build_cmd(py, arm_dir, workers)
    log_path = arm_dir / "run.log"
    t0 = time.time()
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write("CMD: " + " ".join(cmd) + "\n\n")
        log.flush()
        proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(ROOT))
    print(f"[{TAG}] C elapsed={time.time() - t0:.0f}s exit={proc.returncode}", flush=True)
    run = _arm_run_from_dir(
        C_ID,
        "C: 80/20 +10% stop, leftover at +40%",
        "candidate",
        LADDER_C,
        arm_dir,
    )
    run["ok"] = proc.returncode == 0 and run["ok"]
    run["exit_code"] = proc.returncode
    return run


def _md_split(p: dict[str, Any], key: str) -> str:
    m = p[key]
    exp = m.get("exposure_avg")
    wtd = f" wtd_days={exp:.1f}" if isinstance(exp, float) else ""
    return (
        f"N={m['n']} WR={m['wr']:.1f}% Avg={m['avg_pnl']:.2f}% PF={m['pf']:.2f} "
        f"AnnROR={fmt_n(m['ann_ror'], 2)} MaxDD={fmt_n(m['max_dd'], 2)} "
        f"Calmar={fmt_n(m.get('calmar'), 2)} Sharpe={fmt_n(m.get('sharpe'), 2)} "
        f"Expect$={fmt_n(m.get('exp_d'), 0)} cap_days={m.get('cap_days', 0):.0f} "
        f"PPCD={fmt_n(m.get('ppc'), 2)} avg_days={m.get('avg_days', 0):.1f}{wtd}"
    )


def _fmt_pp(v: float) -> str:
    return "—" if v != v else f"{v:.2f}"


def _fmt_d(v: float) -> str:
    return "—" if v != v else f"{v:,.0f}"


def _call(is_v: str, oos_v: str, against: str) -> str:
    if is_v == "DISMISS":
        return f"C DISMISS vs {against}"
    if is_v in ("KEEP", "LEAN KEEP") and oos_v == "DISMISS":
        return "HOLD"
    if is_v in ("KEEP", "LEAN KEEP"):
        return f"C {is_v} vs {against}"
    return "HOLD"


def write_compare_html(
    packed: list[dict[str, Any]],
    stats: dict[str, dict[str, dict[str, Any]]],
    cf: dict[str, dict[str, int]],
    calls: dict[str, str],
    verdicts: dict[str, dict[str, tuple[str, str]]],
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
        "Capital days count a full slot through the +20% sale day, then 20% of a slot. "
        "Avg days is still calendar time open. Annualized return, Calmar, and profit per capital day "
        "use those weighted days. Max drawdown is the closed exit replay. Deltas are versus A. "
        "Click column headers to sort."
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
    pw_sections = []
    pairs = [
        ("B − A", by_id[A_ID], by_id[B_ID]),
        ("C − A", by_id[A_ID], by_id[C_ID]),
        ("C − B", by_id[B_ID], by_id[C_ID]),
    ]
    for split_key, split_title in (("m_is", "IS"), ("m_oos", "OOS"), ("m_full", "FULL")):
        rows = "".join(pairwise_delta_row(a, b, split_key, lbl) for lbl, a, b in pairs)
        pw_sections.append(
            f"<section><h2>Pairwise — {split_title}</h2>"
            f'<p class="muted">Click headers to sort.</p>'
            f'<div class="table-wrap"><table class="sortable"><thead><tr>{pw_th}</tr></thead>'
            f"<tbody>{rows}</tbody></table></div></section>"
        )

    run_th = "".join(
        sortable_th(a, b)
        for a, b in (
            ("Split", "text"),
            ("Arm", "text"),
            ("Reached +20%", "num"),
            ("Reached +40%", "num"),
            ("Stopped", "num"),
            ("Stopped same day as +20%", "num"),
            ("Avg runner add (pp)", "num"),
            ("Avg runner $", "num"),
            ("Avg trade % on those", "num"),
        )
    )
    labels = {
        A_ID: "A breakeven",
        B_ID: "B original stop",
        C_ID: "C +10% stop",
    }
    run_rows = []
    for split in ("IS", "OOS", "FULL"):
        for aid in (A_ID, B_ID, C_ID):
            s = stats[aid][split]
            run_rows.append(
                "<tr>"
                f"<td>{split}</td>"
                f"<td>{html_mod.escape(labels[aid])}</td>"
                f"<td>{s['partials']}</td>"
                f"<td>{s['hit40']}</td>"
                f"<td>{s['stopped']}</td>"
                f"<td>{s['same_day_stop']}</td>"
                f"<td>{_fmt_pp(s['all']['avg_runner_pp'])}</td>"
                f"<td>{_fmt_d(s['all']['avg_runner_d'])}</td>"
                f"<td>{_fmt_pp(s['all']['avg_trade_pct'])}</td>"
                "</tr>"
            )

    cf_th = "".join(
        sortable_th(a, b)
        for a, b in (
            ("Split", "text"),
            ("C stopped at +10%", "num"),
            ("Same buy reached +40% on B", "num"),
            ("B +40% on a later day", "num"),
            ("B +40% on the stop day", "num"),
            ("Same buy stopped on B", "num"),
            ("No matching buy on B", "num"),
        )
    )
    cf_rows = []
    for split in ("IS", "OOS", "FULL"):
        s = cf[split]
        cf_rows.append(
            "<tr>"
            f"<td>{split}</td>"
            f"<td>{s['stopped_plus10']}</td>"
            f"<td>{s['b_reached_40']}</td>"
            f"<td>{s['b_reached_40_later']}</td>"
            f"<td>{s['b_reached_40_same_day']}</td>"
            f"<td>{s['b_stopped']}</td>"
            f"<td>{s['unmatched']}</td>"
            "</tr>"
        )

    vis, nis = verdicts["A"]["is"]
    voos, noos = verdicts["A"]["oos"]
    vbs, nbs = verdicts["B"]["is"]
    vbo, nbo = verdicts["B"]["oos"]
    subtitle = (
        f"Stamp <code>rl_p80_plus10_runner_ab_{STAMP}</code>. "
        "A breakeven leftover, B original stop, C stop at +10% above the buy. "
        "Same entries. Research-only. Not gold. Not DailyRun."
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RL 80/20 +10% runner — {STAMP}</title>
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
<h1>Leftover stop at +10% above the buy, versus breakeven and the original stop.</h1>
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
<strong>Call versus A (breakeven): {html_mod.escape(calls['A'])}</strong>
<p>In-sample: <code>{html_mod.escape(vis)}</code> — {html_mod.escape(nis)}</p>
<p>After 2024 (report-only): <code>{html_mod.escape(voos)}</code> — {html_mod.escape(noos)}</p>
<strong>Call versus B (original stop): {html_mod.escape(calls['B'])}</strong>
<p>In-sample: <code>{html_mod.escape(vbs)}</code> — {html_mod.escape(nbs)}</p>
<p>After 2024 (report-only): <code>{html_mod.escape(vbo)}</code> — {html_mod.escape(nbo)}</p>
<p class="muted">Judge average gain and profit factor. A softer out-of-sample result is a hold. Research-only.</p>
</div>
<section>
<h2>Runner after +20%</h2>
<p class="muted">Reached +20% sold the 80% piece. Reached +40% is the leftover sold at the higher target. Stopped on A is breakeven, on B is the original stop (including gaps), and on C is the +10% stop. Same-day means the leftover was sold on the day of the 80% sale. Avg runner add is the leftover's dollars as percentage points of the $47,500 slot, averaged over trades that reached +20%. Click headers to sort.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>{run_th}</tr></thead>
<tbody>{''.join(run_rows)}</tbody></table></div>
</section>
<section>
<h2>Trades C stopped at +10% — what the original-stop book did with the same buy</h2>
<p class="muted">Each C leftover sold at +10% is matched to B by symbol and buy date. “Reached +40% on B” means B sold that leftover at the +40% target. “Later day” means B's sale date is after C's stop date. “Stop day” means B also finished that leftover on the same calendar day, which happens when the high reached +40% and the low never reached the original stop. Click headers to sort.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>{cf_th}</tr></thead>
<tbody>{''.join(cf_rows)}</tbody></table></div>
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
    cf: dict[str, dict[str, int]],
    html_path: Path,
    calls: dict[str, str],
    verdicts: dict[str, dict[str, tuple[str, str]]],
) -> None:
    by_id = {p["arm"]["id"]: p for p in packed}
    lines = [
        f"# BASELINE — `rl_p80_plus10_runner_ab_{STAMP}`",
        "",
        "**Status:** RESEARCH only. EXIT A/B. Same entries. Only the leftover stop differs.",
        f"**A `{A_ID}`:** ladder `0.20:0.80:0`, leftover +40%. Reuse `{SRC_RUNS.as_posix()}/{A_ID}`.",
        f"**B `{B_ID}`:** ladder `0.20:0.80:-1`, leftover +40%. Reuse `{SRC_RUNS.as_posix()}/{B_ID}`.",
        f"**C `{C_ID}`:** ladder `{LADDER_C}`, leftover stop = entry × 1.10, leftover +40%. New run.",
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
        "Every later calendar day uses 20% of a slot until the leftover exits.",
        "",
        "## Split metrics",
        "",
    ]
    for aid, name in ((A_ID, "A"), (B_ID, "B"), (C_ID, "C")):
        for key, label in (("m_is", "IS"), ("m_oos", "OOS"), ("m_full", "FULL")):
            lines.append(f"- **{name} {label}:** {_md_split(by_id[aid], key)}")
    lines.extend(["", "## Runner after +20%", ""])
    for split in ("IS", "OOS", "FULL"):
        for aid, name in ((A_ID, "A"), (B_ID, "B"), (C_ID, "C")):
            s = stats[aid][split]
            lines.append(
                f"- **{name} {split}:** +20% {s['partials']}; +40% {s['hit40']}; "
                f"stopped {s['stopped']} (same day as sale {s['same_day_stop']}); "
                f"avg runner add {s['all']['avg_runner_pp']:.2f} pp "
                f"(${s['all']['avg_runner_d']:,.0f})."
            )
    lines.extend(["", "## C +10% stops versus the original-stop arm", ""])
    for split in ("IS", "OOS", "FULL"):
        s = cf[split]
        lines.append(
            f"- **{split}:** stopped at +10% {s['stopped_plus10']}; "
            f"same buy reached +40% on B {s['b_reached_40']} "
            f"(later day {s['b_reached_40_later']}, same day {s['b_reached_40_same_day']}); "
            f"same buy stopped on B {s['b_stopped']}; unmatched {s['unmatched']}."
        )
    lines.extend(
        [
            "",
            "## Verdict",
            "",
            f"- Versus A: **{calls['A']}**. IS `{verdicts['A']['is'][0]}` ({verdicts['A']['is'][1]}). "
            f"OOS `{verdicts['A']['oos'][0]}` ({verdicts['A']['oos'][1]}).",
            f"- Versus B: **{calls['B']}**. IS `{verdicts['B']['is'][0]}` ({verdicts['B']['is'][1]}). "
            f"OOS `{verdicts['B']['oos'][0]}` ({verdicts['B']['oos'][1]}).",
            "- OOS is report-only. Do not retune.",
            "",
            f"Compare: `{html_path.as_posix()}`",
            "",
        ]
    )
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines), encoding="utf-8")
    summary = [
        f"# SUMMARY — `rl_p80_plus10_runner_ab_{STAMP}`",
        "",
        f"- Versus A: **{calls['A']}** IS `{verdicts['A']['is'][0]}` ({verdicts['A']['is'][1]}); "
        f"OOS `{verdicts['A']['oos'][0]}` ({verdicts['A']['oos'][1]}).",
        f"- Versus B: **{calls['B']}** IS `{verdicts['B']['is'][0]}` ({verdicts['B']['is'][1]}); "
        f"OOS `{verdicts['B']['oos'][0]}` ({verdicts['B']['oos'][1]}).",
        "",
    ]
    for aid, name in ((A_ID, "A"), (B_ID, "B"), (C_ID, "C")):
        summary.append(f"- {name} FULL: {_md_split(by_id[aid], 'm_full')}")
        summary.append(f"- {name} IS: {_md_split(by_id[aid], 'm_is')}")
    summary.append("")
    for split in ("IS", "FULL"):
        s = stats[C_ID][split]
        cfs = cf[split]
        summary.append(
            f"- C {split} runner: +20% {s['partials']}; +40% {s['hit40']}; "
            f"+10% stop {s['stopped']} (same day {s['same_day_stop']}); "
            f"avg add {s['all']['avg_runner_pp']:.2f} pp. "
            f"Of the +10% stops, {cfs['b_reached_40']} reached +40% on B "
            f"({cfs['b_reached_40_later']} on a later day)."
        )
    summary.extend(["", f"Compare: `{html_path.as_posix()}`", ""])
    (OUT_DIR / "SUMMARY.md").write_text("\n".join(summary), encoding="utf-8")


def _stop_gain_check(rows: list[dict[str, Any]]) -> None:
    gains = []
    for r in rows:
        if r["partial"] and r["exit"] == "TRAIL_STOP" and r["entry"] > 0:
            gains.append(r["exit_px"] / r["entry"] - 1.0)
    if not gains:
        print(f"[{TAG}] no +10% stop fills to check", flush=True)
        return
    gains.sort()
    mid = gains[len(gains) // 2]
    near = sum(1 for g in gains if 0.08 <= g <= 0.12)
    print(
        f"[{TAG}] C TRAIL_STOP n={len(gains)} median gain={mid:.3f} "
        f"near +10%={near}",
        flush=True,
    )


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
            "<html><body><h1>80/20 +10% runner failed</h1>"
            f"<p>{html_mod.escape(msg)}</p>"
            f"<pre>{html_mod.escape(REQUEST_PROMPT.strip())}</pre>"
            f"<p>{html_mod.escape(LAYMAN_TRANSLATION.strip())}</p></body></html>",
            encoding="utf-8",
        )
        ntfy = ROOT / "tools" / "ntfy_job_done.py"
        if ntfy.is_file():
            subprocess.run(
                [py, str(ntfy), "--path", str(path), "-t", "RL 80/20 +10% runner FAILED"],
                cwd=str(ROOT),
            )
        print(f"[{TAG}] {msg}", flush=True)
        return 1

    try:
        run_a = _arm_run_from_dir(
            A_ID, "A: 80/20 breakeven, leftover at +40%", "control", "0.20:0.80:0", SRC_RUNS / A_ID
        )
        run_b = _arm_run_from_dir(
            B_ID,
            "B: 80/20 original stop, leftover at +40%",
            "candidate",
            "0.20:0.80:-1",
            SRC_RUNS / B_ID,
        )
    except FileNotFoundError as exc:
        return fail(str(exc))

    _copy_patterns(SRC_RUNS / A_ID, RUNS_DIR / A_ID)
    _copy_patterns(SRC_RUNS / B_ID, RUNS_DIR / B_ID)
    run_c = run_arm_c(py, args.workers, args.skip_existing or args.summarize_only)
    if not run_c.get("ok"):
        return fail(f"C run failed exit={run_c.get('exit_code')}")

    runs = [run_a, run_b, run_c]
    packed = [pack_result(r) for r in runs]
    rows_by_id = {r["arm"]["id"]: _read_rows(Path(r["closed"])) for r in runs}
    apply_capital_weights(packed, rows_by_id)
    _stop_gain_check(rows_by_id[C_ID])
    stats = {
        A_ID: {s: runner_stats(_split_rows(rows_by_id[A_ID], s), stop_plus10=False) for s in ("IS", "OOS", "FULL")},
        B_ID: {s: runner_stats(_split_rows(rows_by_id[B_ID], s), stop_plus10=False) for s in ("IS", "OOS", "FULL")},
        C_ID: {s: runner_stats(_split_rows(rows_by_id[C_ID], s), stop_plus10=True) for s in ("IS", "OOS", "FULL")},
    }
    for aid in (A_ID, B_ID, C_ID):
        other = stats[aid]["FULL"]["other"]
        if other:
            print(f"[{TAG}] {aid} unexpected partial exits: {other}", flush=True)
    cf = counterfactual(rows_by_id[C_ID], rows_by_id[B_ID])
    by_id = {p["arm"]["id"]: p for p in packed}
    verdicts = {
        "A": {
            "is": verdict_vs_control(by_id[C_ID], by_id[A_ID], "m_is"),
            "oos": verdict_vs_control(by_id[C_ID], by_id[A_ID], "m_oos"),
        },
        "B": {
            "is": verdict_vs_control(by_id[C_ID], by_id[B_ID], "m_is"),
            "oos": verdict_vs_control(by_id[C_ID], by_id[B_ID], "m_oos"),
        },
    }
    calls = {
        "A": _call(verdicts["A"]["is"][0], verdicts["A"]["oos"][0], "A"),
        "B": _call(verdicts["B"]["is"][0], verdicts["B"]["oos"][0], "B"),
    }
    html_path = write_compare_html(packed, stats, cf, calls, verdicts)
    write_metrics_csv(packed, "", OUT_DIR / "metrics_all.csv")
    write_docs(packed, stats, cf, html_path, calls, verdicts)
    print(f"[{TAG}] vs A {calls['A']} vs B {calls['B']}", flush=True)
    s = stats[C_ID]["FULL"]
    cfs = cf["FULL"]
    print(
        f"[{TAG}] C FULL +20%={s['partials']} +40%={s['hit40']} "
        f"+10%stop={s['stopped']} same_day={s['same_day_stop']} "
        f"add={s['all']['avg_runner_pp']:.2f}pp "
        f"B_later40={cfs['b_reached_40_later']}/{cfs['stopped_plus10']}",
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
                "RL 80/20 +10% runner",
                "-m",
                f"C leftover stop at +10%, target +40%. Versus A: {calls['A']}. Versus B: {calls['B']}.",
            ],
            cwd=str(ROOT),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
