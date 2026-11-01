#!/usr/bin/env python3
"""VZ bundled research gates A/B — ATR% 6.7 + RSI14_AT_ENTRY < 51.379 + DIST52 >= 28.97.

Engine-live (filters before fill / cooldown). Isolated ``run_vz.bat -o`` only.
Does not mutate DailyRun / house pin. Not one-knob. Not gold.
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import math
import os
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))

from compare_format import format_money  # noqa: E402
from _gen_too_high_diff import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    sortable_th,
)
from vz_lookback_zonegap_ab_20260907 import (  # noqa: E402
    find_audit_in_dir,
    find_closed_in_dir,
    find_equity_in_dir,
    find_report_in_dir,
    find_summary_in_dir,
    load_closed,
    load_summary_pack,
    oos_softens,
    read_pin,
    read_report_row,
    score_pack,
    split_is_oos,
    verdict_is as _verdict_is_lookback,
)
from vz_atr_trigger_vs_entry_ab_20260907 import audit_gate_fields  # noqa: E402

STAMP = "vz_atr67_rsi51_d52w_ab_20260907"
OUT_DIR = REPO / "drive" / "paul_experiments" / STAMP
HOUSE_PIN_PATH = REPO / "drive" / "VZ_house_last_run_ts.txt"
CTRL_FULL_CLOSED = (
    REPO
    / "drive"
    / "paul_experiments"
    / "tbn_fulluniv_all_systems_20260906"
    / "closed"
    / "VZ_Closed_260907175439.csv"
)
CTRL_FULL_DIR = (
    REPO / "drive" / "paul_experiments" / "tbn_fulluniv_all_systems_20260906" / "runs" / "VZ_refresh"
)
CTRL_P78_PIN = "260907175402"
CTRL_P78_DIR = REPO / "drive" / "paul_experiments" / f"vz_baseline_{CTRL_P78_PIN}" / "engine_closed"
IS_CUT = date(2024, 1, 1)

ATR_THR = 6.7
RSI_THR = 51.379
DIST_THR = 28.97

ORIGINAL_REQUEST = (
    "can we run vz_run using 6.7 as the ATR_PCT_AT_TRIGGER >= and RSI14_AT_ENTRY < 51.379 "
    "and DIST_TO_52W_HIGH_PCT_AT_TRIGGER >=28.97 as new gates? run this against the universe "
    "and then the p78.142"
)

PLAIN_ENGLISH = (
    "Volume Zone (VZ) waits for a high-volume price shelf, then buys the first bounce. "
    "Average True Range (ATR) is a typical daily swing; Relative Strength Index (RSI) is "
    "a 0–100 'how stretched is this close?' number; distance-to-52-week-high is how far "
    "the stock sits below its one-year peak. House already requires ATR at the "
    "<em>signal</em> close to be at least 4% of price. This test stacks three extra "
    "screens at once: ATR at the signal must be at least 6.7%, RSI on the "
    "<em>entry-day</em> close must stay under 51.379, and the name must be at least "
    "28.97% below its 52-week high at the signal. We ran that bundle on the full tape "
    "and on the Paul78.142 house list. This is one bundled candidate — not a single-knob "
    "KEEP, not gold, and we did not change DailyRun."
)


def _f(v: Any, default: float = float("nan")) -> float:
    if v is None or v == "":
        return default
    s = str(v).strip().replace("%", "").replace(",", "").replace("$", "")
    if not s or s.upper() in {"N/A", "NONE", "NAN"}:
        return default
    try:
        return float(s)
    except ValueError:
        return default


def attach_gate_fields(trades: list[dict[str, Any]]) -> None:
    for t in trades:
        raw = t.get("raw") or {}
        t["atr_trig"] = _f(raw.get("ATR_PCT_AT_TRIGGER"))
        t["rsi_entry"] = _f(raw.get("RSI14_AT_ENTRY"))
        t["dist52"] = _f(raw.get("DIST_TO_52W_HIGH_PCT_AT_TRIGGER"))


def passes_bundle(t: dict[str, Any]) -> bool:
    atr = t.get("atr_trig")
    rsi = t.get("rsi_entry")
    dist = t.get("dist52")
    return (
        math.isfinite(atr)
        and atr >= ATR_THR
        and math.isfinite(rsi)
        and rsi < RSI_THR
        and math.isfinite(dist)
        and dist >= DIST_THR
    )


def trade_key(t: dict[str, Any]) -> tuple[str, str, float]:
    opened = t["opened"].isoformat() if t.get("opened") else ""
    return (str(t.get("sym") or ""), opened, round(float(t.get("entry") or 0.0), 4))


def house_freeze_ok(fields: dict[str, Any], *, atr_trigger: float) -> tuple[bool, str]:
    checks = [
        (str(fields.get("exit_name") or "") == "EXIT_atr4_s025_r15_ts20", "exit_name"),
        (abs(float(fields.get("exit_bars") or 0) - 20) < 0.1, "exit_bars"),
        (abs(float(fields.get("stop_atr") or 0) - 0.25) < 1e-6, "stop_atr"),
        (abs(float(fields.get("target_r") or 0) - 1.5) < 1e-6, "target_r"),
        (abs(float(fields.get("lookback") or 0) - 126) < 0.1, "lookback"),
        (abs(float(fields.get("rw") or 0) - 63) < 0.1, "rw"),
        (str(fields.get("entry_on") or "").lower() == "next_open", "entry_on"),
        (abs(float(fields.get("min_atr_entry") or 0) - 0.0) < 1e-6, "min_atr_entry"),
        (abs(float(fields.get("min_atr_trigger") or 0) - atr_trigger) < 1e-6, "min_atr_trigger"),
        (abs(float(fields.get("cd") or 0) - 10) < 0.1, "cooldown"),
    ]
    bad = [name for ok, name in checks if not ok]
    if bad:
        return False, "freeze mismatch: " + ", ".join(bad)
    return True, f"freeze ok (ATR trigger {atr_trigger})"


def cand_gate_ok(fields: dict[str, Any]) -> tuple[bool, str]:
    ok, why = house_freeze_ok(fields, atr_trigger=ATR_THR)
    if not ok:
        return False, why
    rsi = _f(fields.get("max_rsi14_at_entry"))
    dist = _f(fields.get("min_dist52"))
    if not (math.isfinite(rsi) and abs(rsi - RSI_THR) < 1e-6):
        return False, f"rsi gate {rsi} != {RSI_THR}"
    if not (math.isfinite(dist) and abs(dist - DIST_THR) < 1e-6):
        return False, f"dist52 gate {dist} != {DIST_THR}"
    return True, "candidate bundle gates present"


def audit_bundle_fields(path: Optional[Path]) -> dict[str, Any]:
    fields = audit_gate_fields(path)
    row = read_report_row(path)
    fields["max_rsi14_at_entry"] = _f(row.get("vz_max_rsi14_at_entry"))
    fields["min_dist52"] = _f(row.get("vz_min_dist_to_52w_high_pct_at_trigger"))
    return fields


def run_isolated(univ: str, out_dir: Path, workers: int) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = find_closed_in_dir(out_dir)
    if existing is not None:
        fields = audit_bundle_fields(find_audit_in_dir(out_dir) or find_report_in_dir(out_dir))
        ok, why = cand_gate_ok(fields)
        if ok:
            print(f"[cand] reuse {existing} {why}", flush=True)
            return existing
        print(f"[cand] existing Closed gates={fields} ({why}); rerunning", flush=True)
    env = os.environ.copy()
    env.pop("VZ_SYMBOLS", None)
    env.pop("VZ_UNIVERSE_CSV", None)
    env["VZ_MIN_ATR_PCT"] = str(ATR_THR)
    env["VZ_MIN_ATR_PCT_AT_TRIGGER"] = str(ATR_THR)
    env["VZ_MIN_ATR_PCT_AT_ENTRY"] = "0"
    env["VZ_WORKERS"] = str(workers)
    rel_out = out_dir.relative_to(REPO).as_posix().replace("/", "\\")
    univ_arg = "ALL" if univ == "ALL" else r"drive\universes\VZ_universe.csv"
    cmd = (
        f"run_vz.bat {univ_arg} "
        f"-o {rel_out} "
        f"-v vz_min_atr_pct_at_entry=0 "
        f"-v vz_min_atr_pct_at_trigger={ATR_THR} "
        f"-v vz_max_rsi14_at_entry={RSI_THR} "
        f"-v vz_min_dist_to_52w_high_pct_at_trigger={DIST_THR}"
    )
    pin_before = read_pin(HOUSE_PIN_PATH)
    print(f"[cand] {cmd}", flush=True)
    subprocess.run(cmd, shell=True, check=True, cwd=str(REPO), env=env)
    pin_after = read_pin(HOUSE_PIN_PATH)
    if pin_after != pin_before:
        raise RuntimeError(f"House pin changed {pin_before} -> {pin_after}; aborting")
    closed = find_closed_in_dir(out_dir)
    if closed is None:
        raise FileNotFoundError(f"no Closed in {out_dir}")
    fields = audit_bundle_fields(find_audit_in_dir(out_dir) or find_report_in_dir(out_dir))
    ok, why = cand_gate_ok(fields)
    print(f"[cand] wrote {closed} {why} fields={fields}", flush=True)
    if not ok:
        raise RuntimeError(f"candidate gate mismatch: {why} {fields}")
    return closed


def fmt_num(x: Any, nd: int = 2) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(v):
        return "—"
    return f"{v:.{nd}f}"


def fmt_delta(x: Any, nd: int = 2) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(v):
        return "—"
    return f"{v:+.{nd}f}"


def _exit_mix_s(exits: dict[str, int], n: int) -> str:
    if n <= 0:
        return ""
    return ", ".join(f"{k}={v}({100.0 * v / n:.0f}%)" for k, v in sorted(exits.items()))


def verdict_bundle(arm: str, m: dict[str, Any], ctrl: dict[str, Any]) -> tuple[str, str]:
    if arm == "CONTROL":
        return "CONTROL", "Matching-universe house freeze (ATR% trigger ≥ 4; no RSI / 52w gates)"
    v, why = _verdict_is_lookback(arm, m, ctrl)
    if v == "CONTROL":
        return "CONTROL", why
    note = " Bundled three gates — not a one-knob KEEP / not gold."
    if v == "KEEP":
        return "LEAN KEEP", why + note
    return v, why + note


def pack_compare(
    *,
    arm: str,
    knob: str,
    closed: Path,
    trades: list[dict[str, Any]],
    host: Optional[dict[str, Any]],
    summary: Optional[dict[str, Any]],
    equity: Optional[Path],
    ctrl_is: Optional[dict[str, Any]] = None,
    ctrl_oos: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    scores = score_pack(trades, equity=equity, host=host, summary=summary)
    if arm == "CONTROL" or ctrl_is is None:
        verd, why = "CONTROL", "Matching-universe control"
    else:
        verd, why = verdict_bundle(arm, scores["is"], ctrl_is)
    oos_note = "report-only"
    if ctrl_oos is not None and arm != "CONTROL" and oos_softens(scores["oos"], ctrl_oos):
        oos_note = "OOS softens vs control — HOLD, do not retune"
    return {
        "arm": arm,
        "knob": knob,
        "closed": str(closed),
        "verdict": verd,
        "why": why,
        "oos_note": oos_note,
        **scores,
    }


def pack_row_html(p: dict[str, Any], ctrl: dict[str, Any], key: str) -> str:
    m = p[key]
    c = ctrl[key]
    d_n = m["n"] - c["n"]
    d_wr = m["wr"] - c["wr"]
    d_r = m["avg_r"] - c["avg_r"]
    d_pnl = m["avg_pnl"] - c["avg_pnl"]
    d_ror = (
        m["ann_ror"] - c["ann_ror"]
        if math.isfinite(m["ann_ror"]) and math.isfinite(c["ann_ror"])
        else float("nan")
    )
    d_dd = (
        m["max_dd"] - c["max_dd"]
        if math.isfinite(m["max_dd"]) and math.isfinite(c["max_dd"])
        else float("nan")
    )
    fit = m["fit"]
    cls = ""
    if key == "is":
        if p["verdict"] in ("KEEP", "LEAN KEEP"):
            cls = "keep"
        elif p["verdict"] == "DISMISS":
            cls = "dismiss"
        elif p["verdict"] == "HOLD":
            cls = "hold"
    return (
        f"<tr class='{cls}'>"
        f"<td>{html_mod.escape(p['arm'])}</td>"
        f"<td>{html_mod.escape(p['knob'])}</td>"
        f"<td>{m['n']}</td><td>{fmt_num(m['wr'], 1)}</td>"
        f"<td>{fmt_num(m['avg_pnl'])}</td><td>{fmt_num(m['avg_r'])}</td>"
        f"<td>{fmt_num(m['avg_wo_max'])}</td>"
        f"<td>{fmt_num(m['ann_ror'])}</td><td>{fmt_num(m['max_dd'])}</td>"
        f"<td>{fmt_num(m['calmar'])}</td><td>{fmt_num(m['sharpe'])}</td>"
        f"<td>{fmt_num(m['pf'])}</td>"
        f"<td>{format_money(m.get('expectancy_d'))}</td>"
        f"<td>{fmt_num(m['avg_win'])}</td><td>{fmt_num(m['avg_loss'])}</td>"
        f"<td>{fmt_num(m['wl_count'])}</td><td>{fmt_num(m['wl_dollar'])}</td>"
        f"<td>{fmt_num(m['avg_days'], 1)}</td><td>{fmt_num(m['med_days'], 1)}</td>"
        f"<td>{fmt_num(m['p90_days'], 1)}</td><td>{fmt_num(m['capital_days'], 0)}</td>"
        f"<td>{format_money(m.get('profit_per_cd'))}</td>"
        f"<td>{m['losing_streak']}</td>"
        f"<td>{fmt_num(m['pct_max_sym'], 1)}</td><td>{fmt_num(m['pct_max_trade'], 1)}</td>"
        f"<td>{fmt_num(fit['mean_fit_r'])}</td><td>{fmt_num(fit['mean_paul'])}</td>"
        f"<td>{fmt_num(fit['mean_wo'])}</td><td>{fmt_num(fit['mean_outlier'], 1)}</td>"
        f"<td>{fmt_num(fit['mean_tpy'])}</td>"
        f"<td>{d_n:+d}</td><td>{fmt_delta(d_wr, 1)}</td><td>{fmt_delta(d_r)}</td>"
        f"<td>{fmt_delta(d_pnl)}</td><td>{fmt_delta(d_ror, 1)}</td>"
        f"<td>{fmt_delta(d_dd)}</td><td>{fmt_delta(m['pf'] - c['pf'])}</td>"
        f"<td>{html_mod.escape(p['verdict'] if key == 'is' else 'report-only')}</td>"
        f"<td>{html_mod.escape(p['why'] if key == 'is' else p.get('oos_note', ''))}</td>"
        f"<td>{html_mod.escape(_exit_mix_s(m['exits'], m['n']))}</td>"
        "</tr>"
    )


def metric_thead() -> str:
    cols = [
        ("Arm", "text"),
        ("Knob", "text"),
        ("N", "num"),
        ("Win %", "num"),
        ("Avg PnL %", "num"),
        ("AvgR", "num"),
        ("Book AVG_PNL_PCT_WO_MAX", "num"),
        ("Ann ROR %", "num"),
        ("Max DD %", "num"),
        ("Calmar", "num"),
        ("Sharpe", "num"),
        ("Profit factor", "num"),
        ("Expectancy $", "num"),
        ("Avg win %", "num"),
        ("Avg loss %", "num"),
        ("Win/Loss count", "num"),
        ("Win/Loss $", "num"),
        ("Avg days held", "num"),
        ("Median days held", "num"),
        ("P90 days held", "num"),
        ("Capital days", "num"),
        ("Profit / capital day", "num"),
        ("Losing streak", "num"),
        ("Pct PnL max symbol", "num"),
        ("Pct PnL max trade", "num"),
        ("Mean FIT_SCORE_ROBUST", "num"),
        ("Mean Paul Score", "num"),
        ("Mean AVG_PNL_PCT_WO_MAX", "num"),
        ("Mean OUTLIER_PCT_OF_WINS", "num"),
        ("Mean AVG_TRADES_PER_YEAR", "num"),
        ("Δ N", "num"),
        ("Δ Win %", "num"),
        ("Δ AvgR", "num"),
        ("Δ Avg PnL %", "num"),
        ("Δ Ann ROR", "num"),
        ("Δ Max DD", "num"),
        ("Δ PF", "num"),
        ("Verdict", "text"),
        ("Note", "text"),
        ("Exit mix", "text"),
    ]
    return "".join(sortable_th(a, b) for a, b in cols)


def load_arm_dir(d: Path, closed: Path) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], Optional[Path]]:
    trades = load_closed(closed)
    attach_gate_fields(trades)
    host = read_report_row(find_report_in_dir(d) or find_audit_in_dir(d))
    summary = load_summary_pack(find_summary_in_dir(d))
    equity = find_equity_in_dir(d)
    return trades, host, summary, equity


def write_baseline(
    path: Path,
    *,
    pin_before: str,
    pin_after: str,
    full: dict[str, Any],
    p78: dict[str, Any],
    engine_live: bool,
) -> None:
    fu_c, fu_k = full["ctrl"], full["cand"]
    p_c, p_k = p78["ctrl"], p78["cand"]
    md = f"""# VZ bundled gates A/B — `{STAMP}`

**Status:** research candidate only. **Not gold. Not DailyRun.** Not a one-knob KEEP.

## What you asked

{ORIGINAL_REQUEST}

## In plain English

Volume Zone (VZ) buys the first bounce off a high-volume shelf. This job stacked
three extra entry screens on the current house freeze and re-ran the book on the
full tape and on Paul78.142. House pin was **not** changed.

## Freeze (house — do not mutate)

| Knob | House | Candidate bundle |
|---|---|---|
| `vz_min_atr_pct_at_trigger` | 4.0 | **6.7** |
| `vz_min_atr_pct_at_entry` | 0 (off) | 0 (off) |
| `vz_max_rsi14_at_entry` | 0 (off) | **51.379** (keep if RSI14_AT_ENTRY < this) |
| `vz_min_dist_to_52w_high_pct_at_trigger` | 0 (off) | **28.97** (keep if DIST >= this) |
| stop / target / time stop | 0.25 ATR / 1.5R / ts20 | same |
| lookback / retest window | 126 / 63 | same |
| zone / retest | HL-only, first_retest, mt≥1, eps 0.005 | same |
| entry_on | next_open | same |
| HVN / side / cooldown | off / long / 10d | same |
| Universe | Paul78.142 house; full tape research | both |

IS = `entry_date < 2024-01-01` (judge quality). OOS report-only. No OOS retune.

## Not one-knob

This is a **bundle of three gates**. KEEP/HOLD/DISMISS is IS quality of the
bundle vs the matching-universe control. A KEEP here would still be research-only
and would not identify which of the three screens did the work.

## Engine-live vs post-filter

Gates were applied **engine-side** in `rocket_vz._process_one_symbol` before
`enrich_trade_rows` (fills / TARGET cooldown / overlap). That is a live gate,
not a Closed overlay. Relative Strength Index (RSI) uses the **entry-date**
close (`RSI14_AT_ENTRY` / Wilder RSI(14)) as specified — known only after the
fill bar closes, so it is backtest-honest to the Closed field but **not**
scanner-honest at the trigger close. A live-honest RSI would use trigger-bar
RSI; we did not run a separate trigger-RSI arm (footnote only).

New knobs default **OFF** (`0`). `run_vz.bat` / DailyRun defaults were not flipped.

Engine live: **{engine_live}**

## Controls

| Universe | Control Closed | Gate identity |
|---|---|---|
| Full tape | `VZ_Closed_260907175439` | ATR% trigger ≥ 4; no RSI / 52w |
| Paul78.142 | `VZ_Closed_{CTRL_P78_PIN}` | same house freeze |

## House pin

| Item | Value |
|---|---|
| Pin before | `{pin_before}` |
| Pin after | `{pin_after}` |
| Unchanged | **{"yes" if pin_before == pin_after else "NO — INVESTIGATE"}** |
| Official house Closed used as P78 control | `{CTRL_P78_PIN}` |

## Verdicts (IS quality, bundle)

| Universe | Verdict | Why |
|---|---|---|
| Full tape | {fu_k["verdict"]} | {fu_k["why"]} |
| Paul78.142 | {p_k["verdict"]} | {p_k["why"]} |

## Headline IS / OOS

### Full universe

| Slice | Arm | N | WR | Avg PnL% | AvgR | PF | Ann ROR | Max DD |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| IS | Control | {fu_c["is"]["n"]} | {fu_c["is"]["wr"]:.1f} | {fu_c["is"]["avg_pnl"]:.2f} | {fu_c["is"]["avg_r"]:.2f} | {fu_c["is"]["pf"]:.2f} | {fu_c["is"]["ann_ror"]:.1f} | {fu_c["is"]["max_dd"]:.1f} |
| IS | Candidate | {fu_k["is"]["n"]} | {fu_k["is"]["wr"]:.1f} | {fu_k["is"]["avg_pnl"]:.2f} | {fu_k["is"]["avg_r"]:.2f} | {fu_k["is"]["pf"]:.2f} | {fu_k["is"]["ann_ror"]:.1f} | {fu_k["is"]["max_dd"]:.1f} |
| OOS | Control | {fu_c["oos"]["n"]} | {fu_c["oos"]["wr"]:.1f} | {fu_c["oos"]["avg_pnl"]:.2f} | {fu_c["oos"]["avg_r"]:.2f} | {fu_c["oos"]["pf"]:.2f} | {fu_c["oos"]["ann_ror"]:.1f} | {fu_c["oos"]["max_dd"]:.1f} |
| OOS | Candidate | {fu_k["oos"]["n"]} | {fu_k["oos"]["wr"]:.1f} | {fu_k["oos"]["avg_pnl"]:.2f} | {fu_k["oos"]["avg_r"]:.2f} | {fu_k["oos"]["pf"]:.2f} | {fu_k["oos"]["ann_ror"]:.1f} | {fu_k["oos"]["max_dd"]:.1f} |

### Paul78.142

| Slice | Arm | N | WR | Avg PnL% | AvgR | PF | Ann ROR | Max DD |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| IS | Control | {p_c["is"]["n"]} | {p_c["is"]["wr"]:.1f} | {p_c["is"]["avg_pnl"]:.2f} | {p_c["is"]["avg_r"]:.2f} | {p_c["is"]["pf"]:.2f} | {p_c["is"]["ann_ror"]:.1f} | {p_c["is"]["max_dd"]:.1f} |
| IS | Candidate | {p_k["is"]["n"]} | {p_k["is"]["wr"]:.1f} | {p_k["is"]["avg_pnl"]:.2f} | {p_k["is"]["avg_r"]:.2f} | {p_k["is"]["pf"]:.2f} | {p_k["is"]["ann_ror"]:.1f} | {p_k["is"]["max_dd"]:.1f} |
| OOS | Control | {p_c["oos"]["n"]} | {p_c["oos"]["wr"]:.1f} | {p_c["oos"]["avg_pnl"]:.2f} | {p_c["oos"]["avg_r"]:.2f} | {p_c["oos"]["pf"]:.2f} | {p_c["oos"]["ann_ror"]:.1f} | {p_c["oos"]["max_dd"]:.1f} |
| OOS | Candidate | {p_k["oos"]["n"]} | {p_k["oos"]["wr"]:.1f} | {p_k["oos"]["avg_pnl"]:.2f} | {p_k["oos"]["avg_r"]:.2f} | {p_k["oos"]["pf"]:.2f} | {p_k["oos"]["ann_ror"]:.1f} | {p_k["oos"]["max_dd"]:.1f} |

## Selection bias

Thresholds came from the user request (not an in-stamp horse-race). Still a
bundled in-sample screen. OOS is report-only.

## Outputs

- `compare.html` — canonical metrics, both universes
- `cand_fulluniv/` / `cand_p78/` — isolated engine books
"""
    path.write_text(md, encoding="utf-8")


def write_compare_html(
    path: Path,
    *,
    pin: str,
    full: dict[str, Any],
    p78: dict[str, Any],
    post_n: dict[str, Any],
) -> None:
    fu_c, fu_k = full["ctrl"], full["cand"]
    p_c, p_k = p78["ctrl"], p78["cand"]
    th = metric_thead()

    def table(title: str, slice_key: str, packs: list[dict[str, Any]]) -> str:
        ctrl = next(x for x in packs if x["arm"] == "CONTROL")
        body = "".join(pack_row_html(p, ctrl, slice_key) for p in packs)
        return (
            f"<h2>{html_mod.escape(title)}</h2>"
            f"<p class='muted'>Click column headers to sort. "
            f"{'IS judges quality.' if slice_key == 'is' else 'OOS / FULL are report-only. Do not retune.'}</p>"
            f"<table class='sortable'><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>VZ ATR 6.7 + RSI 51 + DIST52 28.97 — bundled gates</title>
<style>
body {{ font-family: Segoe UI, Georgia, serif; margin: 24px; color: #1a1a18; background: #fafaf8; max-width: 1600px; }}
.muted {{ color: #5c5c56; }}
.callout {{ background:#eef2ff; border:1px solid #c7d2fe; padding:12px 16px; margin:1rem 0; }}
.note {{ background:#fff7ed; border:1px solid #fdba74; padding:12px 16px; margin:1rem 0; }}
table.sortable {{ border-collapse: collapse; width: 100%; background: #fff; margin: 12px 0 28px; font-size: 12px; }}
table.sortable th, table.sortable td {{ border: 1px solid #d8d8d0; padding: 5px 7px; }}
table.sortable th {{ background: #f0f0ea; }}
tr.keep {{ background: #ecfdf3; }}
tr.hold {{ background: #fffbeb; }}
tr.dismiss {{ background: #fef2f2; }}
blockquote {{ margin:0.4rem 0 0.8rem; color:#334155; }}
code {{ background:#f1f5f9; padding:1px 4px; }}
{SORTABLE_TH_CSS}
</style></head><body>
<h1>Volume Zone (VZ) bundled entry gates — ATR 6.7 / RSI 51.379 / 52-week distance 28.97</h1>
<div class="callout">
  <p><strong>What you asked</strong></p>
  <blockquote>{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
  <p><strong>In plain English</strong></p>
  <p>{PLAIN_ENGLISH}</p>
</div>
<div class="note">
  <p><strong>Research only.</strong> Bundled three gates (not one knob).
  Engine-live filters before fill / cooldown. Relative Strength Index (RSI)
  is Wilder RSI(14) on the <em>entry-date</em> close — same as Closed
  <code>RSI14_AT_ENTRY</code>. That is not scanner-known at the trigger close;
  a live-honest RSI-at-trigger arm was not run. House pin
  <code>{html_mod.escape(pin)}</code> unchanged. Not gold. Not DailyRun.</p>
  <p>Post-filter on completed control trades (same three Closed fields) is
  <strong>not</strong> a live gate — cooldown / overlap can differ.
  Full-univ post-filter N={post_n.get("full_post", "—")} vs engine-live
  candidate N={fu_k["full"]["n"]}. Paul78 post-filter N={post_n.get("p78_post", "—")}
  vs engine-live N={p_k["full"]["n"]}.</p>
</div>
<p class="muted">IS cut = entry date &lt; 2024-01-01. Average True Range (ATR) %
is ATR14 / trigger close × 100. Distance-to-52-week-high is % below the 252-bar
high at the trigger close.</p>
{table("Full universe — IS (judge)", "is", [fu_c, fu_k])}
{table("Full universe — OOS (report-only)", "oos", [fu_c, fu_k])}
{table("Full universe — FULL (report-only)", "full", [fu_c, fu_k])}
{table("Paul78.142 — IS (judge)", "is", [p_c, p_k])}
{table("Paul78.142 — OOS (report-only)", "oos", [p_c, p_k])}
{table("Paul78.142 — FULL (report-only)", "full", [p_c, p_k])}
<h2>Verdicts</h2>
<ul>
  <li><strong>Full universe IS:</strong> {html_mod.escape(fu_k["verdict"])} — {html_mod.escape(fu_k["why"])}</li>
  <li><strong>Paul78.142 IS:</strong> {html_mod.escape(p_k["verdict"])} — {html_mod.escape(p_k["why"])}</li>
  <li>OOS full: {html_mod.escape(fu_k.get("oos_note") or "report-only")}</li>
  <li>OOS Paul78: {html_mod.escape(p_k.get("oos_note") or "report-only")}</li>
</ul>
<p class="muted">Stamp <code>{STAMP}</code>. Canonical compare metrics
(book + FIT + exit mix). Dollar cells use thousands separators.</p>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    path.write_text(html, encoding="utf-8")


def slim(p: dict[str, Any]) -> dict[str, Any]:
    out = {"arm": p["arm"], "verdict": p["verdict"], "why": p["why"], "oos_note": p.get("oos_note")}
    for key in ("is", "oos", "full"):
        m = p[key]
        out[key] = {
            "n": m["n"],
            "wr": m["wr"],
            "avg_pnl": m["avg_pnl"],
            "avg_r": m["avg_r"],
            "pf": m["pf"],
            "ann_ror": m["ann_ror"],
            "max_dd": m["max_dd"],
        }
    return out


def build_report(*, pin_before: str, pin_after: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    full_dir = OUT_DIR / "cand_fulluniv"
    p78_dir = OUT_DIR / "cand_p78"
    full_closed = find_closed_in_dir(full_dir)
    p78_closed = find_closed_in_dir(p78_dir)
    if full_closed is None or p78_closed is None:
        raise FileNotFoundError(f"candidate Closed missing: full={full_closed} p78={p78_closed}")

    fu_fields = audit_bundle_fields(find_audit_in_dir(full_dir) or find_report_in_dir(full_dir))
    p78_fields = audit_bundle_fields(find_audit_in_dir(p78_dir) or find_report_in_dir(p78_dir))
    ok_f, why_f = cand_gate_ok(fu_fields)
    ok_p, why_p = cand_gate_ok(p78_fields)
    if not ok_f:
        raise RuntimeError(f"fulluniv candidate gates: {why_f} {fu_fields}")
    if not ok_p:
        raise RuntimeError(f"p78 candidate gates: {why_p} {p78_fields}")

    ctrl_full_closed = CTRL_FULL_CLOSED
    ctrl_p78_closed = CTRL_P78_DIR / f"VZ_Closed_{CTRL_P78_PIN}.csv"
    if not ctrl_p78_closed.is_file():
        ctrl_p78_closed = REPO / "drive" / f"VZ_Closed_{CTRL_P78_PIN}.csv"

    fu_ctrl_t, fu_ctrl_h, fu_ctrl_s, fu_ctrl_e = load_arm_dir(CTRL_FULL_DIR, ctrl_full_closed)
    fu_cand_t, fu_cand_h, fu_cand_s, fu_cand_e = load_arm_dir(full_dir, full_closed)
    p_ctrl_t, p_ctrl_h, p_ctrl_s, p_ctrl_e = load_arm_dir(CTRL_P78_DIR, ctrl_p78_closed)
    p_cand_t, p_cand_h, p_cand_s, p_cand_e = load_arm_dir(p78_dir, p78_closed)

    fu_ctrl = pack_compare(
        arm="CONTROL",
        knob="ATR% trigger ≥ 4 (no RSI / 52w)",
        closed=ctrl_full_closed,
        trades=fu_ctrl_t,
        host=fu_ctrl_h,
        summary=fu_ctrl_s,
        equity=fu_ctrl_e,
    )
    fu_cand = pack_compare(
        arm="CAND_BUNDLE",
        knob="ATR≥6.7 + RSI14_AT_ENTRY<51.379 + DIST52≥28.97",
        closed=full_closed,
        trades=fu_cand_t,
        host=fu_cand_h,
        summary=fu_cand_s,
        equity=fu_cand_e,
        ctrl_is=fu_ctrl["is"],
        ctrl_oos=fu_ctrl["oos"],
    )
    p_ctrl = pack_compare(
        arm="CONTROL",
        knob="ATR% trigger ≥ 4 (no RSI / 52w)",
        closed=ctrl_p78_closed,
        trades=p_ctrl_t,
        host=p_ctrl_h,
        summary=p_ctrl_s,
        equity=p_ctrl_e,
    )
    p_cand = pack_compare(
        arm="CAND_BUNDLE",
        knob="ATR≥6.7 + RSI14_AT_ENTRY<51.379 + DIST52≥28.97",
        closed=p78_closed,
        trades=p_cand_t,
        host=p_cand_h,
        summary=p_cand_s,
        equity=p_cand_e,
        ctrl_is=p_ctrl["is"],
        ctrl_oos=p_ctrl["oos"],
    )
    full = {"ctrl": fu_ctrl, "cand": fu_cand}
    p78 = {"ctrl": p_ctrl, "cand": p_cand}
    post_n = {
        "full_post": sum(1 for t in fu_ctrl_t if passes_bundle(t)),
        "p78_post": sum(1 for t in p_ctrl_t if passes_bundle(t)),
    }
    write_baseline(
        OUT_DIR / "BASELINE.md",
        pin_before=pin_before,
        pin_after=pin_after,
        full=full,
        p78=p78,
        engine_live=True,
    )
    write_compare_html(
        OUT_DIR / "compare.html",
        pin=pin_after,
        full=full,
        p78=p78,
        post_n=post_n,
    )
    payload = {
        "stamp": STAMP,
        "engine_live": True,
        "house_pin_before": pin_before,
        "house_pin_after": pin_after,
        "house_pin_unchanged": pin_before == pin_after,
        "post_filter_n": post_n,
        "fulluniv": {"ctrl": slim(fu_ctrl), "cand": slim(fu_cand)},
        "p78": {"ctrl": slim(p_ctrl), "cand": slim(p_cand)},
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2), flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--workers-full", type=int, default=12)
    ap.add_argument("--workers-p78", type=int, default=8)
    args = ap.parse_args()
    pin_before = read_pin(HOUSE_PIN_PATH)
    if not args.report_only:
        run_isolated("ALL", OUT_DIR / "cand_fulluniv", args.workers_full)
        run_isolated("P78", OUT_DIR / "cand_p78", args.workers_p78)
    pin_after = read_pin(HOUSE_PIN_PATH)
    if pin_after != pin_before:
        raise RuntimeError(f"House pin changed {pin_before} -> {pin_after}")
    build_report(pin_before=pin_before, pin_after=pin_after)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
