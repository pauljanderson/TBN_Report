#!/usr/bin/env python3
"""Research A/B: current Rocket Launcher vs the same book with a WPBR overhead filter.

Control is the live Rocket Launcher freeze. The test arm only adds
rl_wpbr_overhead_band_pct=0.22. Nothing in run_rl.bat or the gold book changes.

In-sample is entry before 2024-01-01. Out-of-sample is 2024-01-01 and later.
Out-of-sample is report-only.
"""
from __future__ import annotations

import html as html_mod
import math
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
SA = ROOT / "stock_analysis"
DATA = ROOT / "data" / "newdata" / "data"
STAMP = "20261002"
TAG = "RL-WPBR-OH22"
OUT = DRIVE / "paul_experiments" / f"rl_wpbr_overhead22_ab_{STAMP}"
RUNS = ROOT / "tmp_rl_wpbr_overhead22_ab_20261002"
PER_SYMBOL = SA / "Per_Symbol_Optimized_Settings_Approved_Latest.json"
WORKERS = 8

REQUEST = (
    "Combine the existing WPBR zone logic with the RL system and use those zones as an "
    "overhead-resistance filter. Test whether RL trades perform better when we reject entries "
    "that have a prior qualifying WPBR zone overhead. Only consider prior WPBR zones whose lower "
    "edge is above the RL 50-day SMA at the time of the RL signal. Control: current RL system, "
    "unchanged. Test: current RL plus the WPBR overhead-zone filter. For the first test, use the "
    "same 22% overhead distance logic as WPBR, but measure the 22% distance from the RL entry "
    "price because RL does not have an active WPBR entry zone. Reject the RL trade when a "
    "qualifying prior WPBR zone's lower edge is above the RL entry and within 22% of the RL entry, "
    "provided that zone's lower edge is also above the 50-day SMA. Change nothing else in RL. "
    "Same universe, dates, entry rules, and frozen exit. IS, OOS, and FULL, plus summary and "
    "closed-trades files for the test group. Research only. Do not change the live or gold RL system."
)

LAYMAN = (
    "Rocket Launcher (RL) buys a dip toward the 50-day simple moving average and sells on the usual "
    "plan: 80% of the shares at 20% above the buy, the rest protected at the buy price, and that "
    "leftover sold at 40% above the buy. Weekly Pivot Break and Retest (WPBR) is a different system "
    "that draws a price band around old weekly peaks. This test keeps every Rocket Launcher rule "
    "and only adds one extra no. If an older WPBR band's floor sits above today's 50-day average, "
    "and also sits above the planned buy by 22% or less, that buy is skipped. A band farther than "
    "22% above the buy is ignored. The control book is today's Rocket Launcher with that extra no turned off."
)

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(DRIVE / "paul_experiments"))
from report_page_extras import (  # noqa: E402
    RESPONSIVE_TABLE_CSS,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)
from rl_univ_compare_lists import (  # noqa: E402
    IS_CUT,
    RL_CASH,
    _find_latest,
    _resolve_python,
    book_stats,
    load_trades,
    split_is_oos,
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
    "rl_scale_ladder=0.20:0.80:0",
    "rl_entry_target_pct=0.40",
    "rl_wpbr_overhead_band_pct=0",
]

METRIC_ROWS = [
    ("Trades", "n", 0, ""),
    ("Win %", "wr", 1, "%"),
    ("Avg P&L %", "avg_pnl", 2, "%"),
    ("Avg winner %", "avg_win", 2, "%"),
    ("Avg loser %", "avg_loss", 2, "%"),
    ("Profit factor", "pf", 2, ""),
    ("Avg P&L % without best trade", "wo_max", 2, "%"),
    ("Expectancy $", "exp_d", 0, "$"),
    ("Sheet P&L $", "sheet", 0, "$"),
    ("Annualized rate of return", "ann_ror", 2, "%"),
    ("Max drawdown %", "max_dd", 2, "%"),
    ("Calmar", "calmar", 2, ""),
    ("Sharpe", "sharpe", 2, ""),
    ("Avg days held", "avg_days", 1, ""),
    ("Trades per year", "tpy", 1, ""),
]


def sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _cmd(py: str, outdir: Path, band: float) -> list[str]:
    cmd = [
        py,
        "-u",
        str(SA / "rocket_tbn.py"),
        str(DATA),
        "-o",
        str(outdir),
        "-w",
        str(WORKERS),
        "--aggressive",
        "--no-regression",
    ]
    if PER_SYMBOL.is_file():
        cmd.extend(["--per-symbol-settings", str(PER_SYMBOL)])
    for item in COMMON_V:
        key, _, _ = item.partition("=")
        if key == "rl_wpbr_overhead_band_pct":
            cmd.extend(["-v", f"rl_wpbr_overhead_band_pct={band}"])
        else:
            cmd.extend(["-v", item])
    return cmd


def run_arm(py: str, arm_id: str, band: float) -> Path:
    outdir = RUNS / arm_id
    if outdir.exists():
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True)
    log_path = outdir / f"{arm_id}.log"
    cmd = _cmd(py, outdir, band)
    print(f"[{TAG}] start {arm_id} band={band} -> {outdir}", flush=True)
    with log_path.open("w", encoding="utf-8") as log:
        log.write(" ".join(cmd) + "\n")
        log.flush()
        rc = subprocess.call(cmd, stdout=log, stderr=subprocess.STDOUT)
    if rc != 0:
        raise SystemExit(f"{arm_id} failed rc={rc}. See {log_path}")
    print(f"[{TAG}] done {arm_id}", flush=True)
    return outdir


def _fmt(v: Any, nd: int, suffix: str) -> str:
    if not isinstance(v, (int, float)) or not math.isfinite(float(v)):
        return "—"
    if suffix == "$":
        return f"${float(v):,.0f}"
    if nd == 0 and suffix == "":
        return f"{int(round(float(v))):,}"
    text = f"{float(v):,.{nd}f}"
    return text + suffix


def _delta(a: float, b: float, nd: int, suffix: str) -> str:
    if not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        return "—"
    if not (math.isfinite(float(a)) and math.isfinite(float(b))):
        return "—"
    d = float(b) - float(a)
    if suffix == "$":
        return f"${d:,.0f}"
    if nd == 0 and suffix == "":
        return f"{int(round(d)):+,}"
    return f"{d:+,.{nd}f}{suffix}"


def _pack(arm_id: str, label: str, band: float, folder: Path) -> dict[str, Any]:
    closed = _find_latest(folder, "RL_Closed_*.csv")
    summary = _find_latest(folder, "RL_Summary_*.csv")
    if closed is None:
        raise FileNotFoundError(f"no RL_Closed in {folder}")
    trades = load_trades(closed)
    is_rows, oos_rows = split_is_oos(trades)
    return {
        "id": arm_id,
        "label": label,
        "band": band,
        "closed": closed,
        "summary": summary,
        "trades": trades,
        "slices": {
            "FULL": book_stats(trades),
            "IS": book_stats(is_rows),
            "OOS": book_stats(oos_rows),
        },
    }


def _verdict(ctrl: dict[str, Any], test: dict[str, Any]) -> str:
    i, c = test["slices"]["IS"], ctrl["slices"]["IS"]
    o, co = test["slices"]["OOS"], ctrl["slices"]["OOS"]
    better_is = (
        math.isfinite(i["avg_pnl"])
        and math.isfinite(c["avg_pnl"])
        and i["avg_pnl"] > c["avg_pnl"] + 0.05
        and math.isfinite(i["pf"])
        and math.isfinite(c["pf"])
        and i["pf"] >= c["pf"] - 0.02
    )
    worse_is = (
        math.isfinite(i["avg_pnl"])
        and math.isfinite(c["avg_pnl"])
        and i["avg_pnl"] < c["avg_pnl"] - 0.05
    )
    oos_soft = (
        math.isfinite(o["avg_pnl"])
        and math.isfinite(co["avg_pnl"])
        and o["avg_pnl"] < co["avg_pnl"] - 0.15
    )
    n_drop = c["n"] > 0 and i["n"] < 0.85 * c["n"]
    if better_is and oos_soft:
        call = (
            "HOLD. In-sample average P&L is better, and out of sample is softer. "
            "Do not retune off the out-of-sample row."
        )
    elif better_is and n_drop:
        call = "HOLD. In-sample average is higher, but the trade count fell."
    elif better_is:
        call = (
            "LEAN KEEP as research only. In-sample quality improved and out of sample "
            "did not soften on average P&L. Not gold. Not a live change."
        )
    elif worse_is:
        call = "DISMISS. In-sample average P&L is worse than control."
    else:
        call = "HOLD. In-sample average P&L is close to control."
    return call


def _table(ctrl: dict[str, Any], test: dict[str, Any]) -> str:
    head = "".join(
        [
            sortable_th("Slice", "text"),
            sortable_th("Metric", "text"),
            sortable_th("Control", "num"),
            sortable_th("Test", "num"),
            sortable_th("Test minus control", "num"),
        ]
    )
    body = []
    for slice_name in ("FULL", "IS", "OOS"):
        for label, key, nd, suffix in METRIC_ROWS:
            a = ctrl["slices"][slice_name][key]
            b = test["slices"][slice_name][key]
            body.append(
                "<tr>"
                f"<td>{slice_name}</td>"
                f"<td>{html_mod.escape(label)}</td>"
                f"<td data-sort-value=\"{a}\">{_fmt(a, nd, suffix)}</td>"
                f"<td>{_fmt(b, nd, suffix)}</td>"
                f"<td>{_delta(float(a) if isinstance(a, (int, float)) else float('nan'), float(b) if isinstance(b, (int, float)) else float('nan'), nd, suffix)}</td>"
                "</tr>"
            )
    return (
        '<div class="table-wrap"><table class="sortable">'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def write_reports(ctrl: dict[str, Any], test: dict[str, Any], started: str, elapsed: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    call = _verdict(ctrl, test)
    if test["summary"] and test["summary"].is_file():
        shutil.copy2(test["summary"], OUT / "test_summary.csv")
    shutil.copy2(test["closed"], OUT / "test_closed.csv")
    page = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RL overhead-zone filter, 22%</title>
<style>
body {{ font-family: Georgia, serif; color: #1c1b19; margin: 24px; max-width: 980px; }}
.callout {{ background: #f6f3ea; border: 1px solid #d9d3c4; padding: 12px 14px; margin: 12px 0 18px; }}
.verdict {{ background: #fff8e8; border: 1px solid #e0c878; padding: 12px 14px; }}
{SORTABLE_TH_CSS}
{RESPONSIVE_TABLE_CSS}
</style>
</head><body>
<h1>Rocket Launcher vs a 22% WPBR overhead filter</h1>
<p class="verdict"><strong>{html_mod.escape(call)}</strong> Research only. The live Rocket Launcher file was not changed.</p>
<div class="callout"><h2>What you asked</h2><p>{html_mod.escape(REQUEST)}</p></div>
<div class="callout"><h2>In plain English</h2><p>{html_mod.escape(LAYMAN)}</p></div>
<p>In-sample means the entry date is before 2024-01-01. Out-of-sample means the entry date is 2024-01-01 or later. Out-of-sample is shown for honesty. It is not used to pick a setting. Click a column header to sort.</p>
{SWIPE_NOTE_HTML}
{_table(ctrl, test)}
<h2>Frozen for both arms</h2>
<ul>
<li>Universe: every price file under data/newdata/data. Same dates. No entry-date cut on the backtest itself.</li>
<li>Entries: current Rocket Launcher dip rules. Weekly Pivot Break and Retest buys stay off.</li>
<li>Exit: sell 80% at +20% from the entry, move the leftover stop to the entry price, sell the leftover at +40%. No time clock. The simple moving average target is off.</li>
<li>Cash used in annualized rate of return: ${RL_CASH:,.0f} per trade slot. House formula, one reused slot.</li>
<li>Control overhead band: off (0). Test band: 0.22, measured from the next-open entry, not from a WPBR zone.</li>
<li>A zone counts only when its pivot week starts before the signal bar, its lower edge is above the signal bar's 50-day simple moving average, and that lower edge is above the entry by at most 22%.</li>
<li>Zone shape matches live WPBR zone construction: 1.5% band, strong pivot 3 bars and 10% on either side, breakout confirmation 3%. Zones that never became a WPBR buy are still overhead levels.</li>
<li>Started {html_mod.escape(started)}. Elapsed {html_mod.escape(elapsed)}.</li>
</ul>
<p>Test-group files: test_summary.csv and test_closed.csv in this folder.</p>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    (OUT / "compare.html").write_text(page, encoding="utf-8")
    is_c, is_t = ctrl["slices"]["IS"], test["slices"]["IS"]
    baseline = f"""# RL WPBR overhead 22% A/B

Research only. `run_rl.bat` was not edited. Gold was not edited.

## What you asked

{REQUEST}

## In plain English

{LAYMAN}

## Freeze

- Control: current Rocket Launcher. `rl_wpbr_overhead_band_pct=0`.
- Test: the same run plus `rl_wpbr_overhead_band_pct=0.22`.
- Distance is (zone lower edge − RL entry) / RL entry. At or under 0.22 rejects. Wider than 22% is allowed.
- The lower edge must also be strictly above the 50-day simple moving average on the signal bar, and the zone's pivot week must start before that bar.
- Exit unchanged: `rl_scale_ladder=0.20:0.80:0`, `rl_entry_target_pct=0.40`, SMA target off, no time exit.
- IS = entry before 2024-01-01. OOS = entry on or after 2024-01-01. OOS is report-only.
- Annualized rate of return uses the house formula and ${RL_CASH:,.0f} cash.

## Verdict

{call}

In-sample trades {is_c['n']} vs {is_t['n']}. Average P&L {is_c['avg_pnl']:.2f}% vs {is_t['avg_pnl']:.2f}%. Profit factor {is_c['pf']:.2f} vs {is_t['pf']:.2f}.

## Files

- compare.html
- test_summary.csv
- test_closed.csv
- Arm folders under tmp_rl_wpbr_overhead22_ab_20261002
"""
    (OUT / "BASELINE.md").write_text(baseline, encoding="utf-8")
    print(f"[{TAG}] wrote {OUT / 'compare.html'}", flush=True)
    print(f"[{TAG}] {call}", flush=True)


def main() -> int:
    if not DATA.is_dir():
        raise SystemExit(f"missing universe {DATA}")
    started = datetime.now().isoformat(timespec="seconds")
    t0 = datetime.now()
    py = _resolve_python()
    ctrl_dir = run_arm(py, "control", 0.0)
    test_dir = run_arm(py, "oh22", 0.22)
    ctrl = _pack("control", "Current RL", 0.0, ctrl_dir)
    test = _pack("oh22", "RL + 22% WPBR overhead", 0.22, test_dir)
    elapsed = str(datetime.now() - t0).split(".")[0]
    write_reports(ctrl, test, started, elapsed)
    ntfy = subprocess.call(
        [
            py,
            str(ROOT / "tools" / "ntfy_job_done.py"),
            "--path",
            str(OUT / "compare.html"),
            "-t",
            "RL 22% overhead A/B",
        ]
    )
    print(f"[{TAG}] ntfy rc={ntfy}", flush=True)
    print(f"[{TAG}] DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
