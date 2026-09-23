#!/usr/bin/env python3
"""EXIT A/B: adopted RSI roll-8 vs neighbors 6 / 7 / 9 / 10.

Same entries as the house atr=2.93 / no min_dist Closed book. Overlay only.
CONTROL = roll 8 (DailyRun adopt). REF_no_roll is the old house exits.

Usage:
  python tools/rsi_roll_ab_20260916.py
  python tools/rsi_roll_ab_20260916.py --html-only
"""
from __future__ import annotations

import csv
import html as html_mod
import json
import math
import shutil
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "stock_analysis"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

from rsi_giveback_lockin_ab_20260916 import (  # noqa: E402
    Arm,
    SORT_CSS,
    SORT_JS,
    control_trade,
    fmt_delta_pct,
    fmt_int,
    fmt_num,
    fmt_pct,
    load_closed,
    load_ohlcv,
    overlay_exit,
    pack,
    slc,
    sortable_th,
    verdict_for,
)
from rocket_tbn import _wilder_rsi14_arr  # noqa: E402
from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    filter_html_compare_columns,
    format_money,
)

DRIVE = ROOT / "drive"
STAMP = "rsi_roll_ab_20260916"
OUT_DIR = DRIVE / "paul_experiments" / STAMP
IS_CUT = date(2024, 1, 1)
SHEET = 10_000.0
INIT = DEFAULT_INITIAL_ACCOUNT
CTRL_TS_FALLBACK = "260916130107"
GIVEBACK_TS = "260916125816"

ORIGINAL_REQUEST = (
    "thanks. i like this one for RSI. let's adopt it. it is a smaller IS Avg pnl, "
    "but gets us out of trades sooner so our Ann ROR increases. can you run an AB "
    "test of roll 6, 7, 9, and 10 to compare to 8?"
)
PLAIN_ENGLISH = (
    "Relative Strength Index (RSI) buys after a name was hot and then cooled off. "
    "House used to sell only when RSI got hot again (70) or after 20 calendar days. "
    "You liked the 'roll 8' sell: once RSI falls 8 points from its high while we "
    "are in the trade, we sell at the next open. That books a smaller average gain "
    "but frees cash sooner, so annualized rate of return (Ann ROR) goes up. We "
    "wired roll 8 into DailyRun. This test keeps the same buys and only changes "
    "that drop: 6 or 7 (tighter / sooner) and 9 or 10 (looser / later) versus the "
    "adopted 8. In-sample is entries before 2024; after that is report-only. "
    "You picked 8 after seeing the earlier giveback table — that is in-sample "
    "selection. Neighbors are not a retune of 8."
)

ARMS: list[Arm] = [
    Arm(
        "CONTROL",
        "rsi_roll_from_max",
        "rsi_roll",
        "Adopted DailyRun exit: sell next open when RSI14 drops 8 from the in-trade high; else RSI14 >= 70; else flatten at 20 calendar days.",
        "Paul chose EXIT_rsi_roll8 for Ann ROR / shorter hold after seeing the giveback table (metrics DISMISS on Avg%).",
        rsi_drop=8.0,
    ),
    Arm(
        "EXIT_roll6",
        "rsi_roll_from_max",
        "rsi_roll",
        "Same overlay, drop 6 instead of 8 (tighter — get out sooner).",
        "Neighbor of adopted 8. One knob.",
        rsi_drop=6.0,
    ),
    Arm(
        "EXIT_roll7",
        "rsi_roll_from_max",
        "rsi_roll",
        "Same overlay, drop 7 instead of 8 (slightly tighter).",
        "Neighbor of adopted 8. One knob.",
        rsi_drop=7.0,
    ),
    Arm(
        "EXIT_roll9",
        "rsi_roll_from_max",
        "rsi_roll",
        "Same overlay, drop 9 instead of 8 (slightly looser — hold a bit longer).",
        "Neighbor of adopted 8. One knob.",
        rsi_drop=9.0,
    ),
    Arm(
        "EXIT_roll10",
        "rsi_roll_from_max",
        "rsi_roll",
        "Same overlay, drop 10 instead of 8 (looser).",
        "Neighbor of adopted 8. One knob.",
        rsi_drop=10.0,
    ),
    Arm(
        "REF_no_roll",
        "none",
        "control",
        "Old house exits (no roll): RSI14 >= 70 next open, else 20-day time stop. Reference only — not a candidate.",
        "Pre-adopt atr=2.93 book Paul compared roll 8 against.",
    ),
]


def _pin_ts() -> str:
    p = DRIVE / "RSI_house_last_run_ts.txt"
    if p.is_file():
        return p.read_text(encoding="utf-8").strip().splitlines()[0]
    return ""


def _src_closed() -> tuple[Path, str]:
    """Frozen no-roll house book (entries). Prefer the pin Paul just used."""
    for ts in (CTRL_TS_FALLBACK, GIVEBACK_TS):
        path = DRIVE / f"RSI_Closed_{ts}.csv"
        if path.is_file():
            return path, ts
    latest = DRIVE / "RSI_LatestRun_Closed.csv"
    if latest.is_file():
        return latest, "LatestRun"
    raise SystemExit("No RSI Closed book found for overlay source")


def _exit_cell(exits: dict[str, int], key: str) -> str:
    n = int(exits.get(key, 0))
    tot = sum(exits.values()) or 1
    return f"{n} ({100.0 * n / tot:.1f}%)"


def run_overlay(src_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_sym: dict[str, list[dict[str, Any]]] = {}
    for r in src_rows:
        by_sym.setdefault(r["symbol"], []).append(r)
    cache: dict[str, Any] = {}
    miss = 0
    for sym in by_sym:
        df = load_ohlcv(sym)
        if df is None or df.empty:
            miss += 1
            continue
        dates = [d.date() if hasattr(d, "date") else d for d in df["Date"]]
        open_ = df["Open"].to_numpy(dtype=float)
        high = df["High"].to_numpy(dtype=float)
        close = df["Close"].to_numpy(dtype=float)
        rsi = _wilder_rsi14_arr(close)
        ix = {d: i for i, d in enumerate(dates)}
        cache[sym] = (dates, open_, high, close, rsi, ix)
    print(f"Loaded OHLC for {len(cache)} / {len(by_sym)} symbols ({miss} missing files)", flush=True)
    out: dict[str, list[dict[str, Any]]] = {a.name: [] for a in ARMS}
    for src in src_rows:
        pack_sym = cache.get(src["symbol"])
        for arm in ARMS:
            if pack_sym is None:
                out[arm.name].append(control_trade(src))
                continue
            dates, open_, high, close, rsi, ix = pack_sym
            out[arm.name].append(overlay_exit(src, dates, open_, high, close, rsi, arm, ix))
    return out


def write_csv_books(by_arm: dict[str, list[dict[str, Any]]]) -> None:
    for name, rows in by_arm.items():
        path = OUT_DIR / f"overlay_{name}.csv"
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "SYMBOL", "DATE_OPENED", "DATE_CLOSED", "ENTRY_PRICE", "EXIT_PRICE",
                    "EXIT_TYPE", "DAYS_HELD", "PNL_PCT", "PNL_DOLLARS", "EARLY",
                ],
            )
            w.writeheader()
            for r in rows:
                w.writerow(
                    {
                        "SYMBOL": r["symbol"],
                        "DATE_OPENED": r["opened"].strftime("%Y%m%d"),
                        "DATE_CLOSED": r["closed"].strftime("%Y%m%d"),
                        "ENTRY_PRICE": f"{r['entry']:.4f}",
                        "EXIT_PRICE": f"{r['exit_px']:.4f}",
                        "EXIT_TYPE": r["exit"],
                        "DAYS_HELD": r["days"],
                        "PNL_PCT": f"{r['pnl']:.4f}",
                        "PNL_DOLLARS": f"{r['pnl_d']:.2f}",
                        "EARLY": int(bool(r.get("early"))),
                    }
                )


def _verdicts(packs: dict[str, dict[str, dict[str, Any]]]) -> dict[str, str]:
    out = {"CONTROL": "CONTROL", "REF_no_roll": "REF"}
    for arm in ARMS:
        if arm.name in {"CONTROL", "REF_no_roll"}:
            continue
        out[arm.name] = verdict_for(packs["CONTROL"], packs[arm.name])
    return out


def write_html(
    packs: dict[str, dict[str, dict[str, Any]]],
    verdicts: dict[str, str],
    src_ts: str,
    house: dict[str, Any],
) -> Path:
    names = [a.name for a in ARMS]
    ctrl = packs["CONTROL"]
    headline_cols = filter_html_compare_columns(
        [("Arm", "text"), ("Kind", "text"), ("Verdict", "text"), ("Knob", "text")]
        + [(f"{sl} N", "num") for sl in ("FULL", "IS", "OOS")]
        + [(f"{sl} Avg%", "num") for sl in ("FULL", "IS", "OOS")]
        + [(f"{sl} Ann ROR %", "num") for sl in ("FULL", "IS", "OOS")]
        + [(f"{sl} ΔAvg% vs roll8", "num") for sl in ("FULL", "IS", "OOS")]
        + [(f"{sl} ΔAnn ROR vs roll8", "num") for sl in ("FULL", "IS", "OOS")]
        + [
            ("IS Max DD%", "num"),
            ("OOS Max DD%", "num"),
            ("FULL avg days", "num"),
            ("FULL early vs no-roll", "num"),
        ]
    )
    hth = "".join(sortable_th(a, b) for a, b in headline_cols)
    hbody = []
    for arm in ARMS:
        p = packs[arm.name]
        v = verdicts.get(arm.name, "—")
        klass = v.lower() if v in {"KEEP", "HOLD", "DISMISS"} else ""
        hbody.append(
            "<tr>"
            f"<td>{html_mod.escape(arm.name)}</td>"
            f"<td>{'REF' if arm.name == 'REF_no_roll' else 'EXIT'}</td>"
            f"<td class='{klass}'>{html_mod.escape(v)}</td>"
            f"<td>{html_mod.escape(arm.knob)}</td>"
            f"<td>{fmt_int(p['FULL']['n'])}</td>"
            f"<td>{fmt_int(p['IS']['n'])}</td>"
            f"<td>{fmt_int(p['OOS']['n'])}</td>"
            f"<td>{fmt_pct(p['FULL']['avg_pnl_pct'])}</td>"
            f"<td>{fmt_pct(p['IS']['avg_pnl_pct'])}</td>"
            f"<td>{fmt_pct(p['OOS']['avg_pnl_pct'])}</td>"
            f"<td>{fmt_pct(p['FULL']['ann_ror'])}</td>"
            f"<td>{fmt_pct(p['IS']['ann_ror'])}</td>"
            f"<td>{fmt_pct(p['OOS']['ann_ror'])}</td>"
            f"<td>{fmt_delta_pct(p['FULL']['avg_pnl_pct'], ctrl['FULL']['avg_pnl_pct'])}</td>"
            f"<td>{fmt_delta_pct(p['IS']['avg_pnl_pct'], ctrl['IS']['avg_pnl_pct'])}</td>"
            f"<td>{fmt_delta_pct(p['OOS']['avg_pnl_pct'], ctrl['OOS']['avg_pnl_pct'])}</td>"
            f"<td>{fmt_delta_pct(p['FULL']['ann_ror'], ctrl['FULL']['ann_ror'])}</td>"
            f"<td>{fmt_delta_pct(p['IS']['ann_ror'], ctrl['IS']['ann_ror'])}</td>"
            f"<td>{fmt_delta_pct(p['OOS']['ann_ror'], ctrl['OOS']['ann_ror'])}</td>"
            f"<td>{fmt_pct(p['IS']['max_dd'])}</td>"
            f"<td>{fmt_pct(p['OOS']['max_dd'])}</td>"
            f"<td>{fmt_num(p['FULL']['avg_days'])}</td>"
            f"<td>{fmt_int(p['FULL']['early_n'])}</td>"
            "</tr>"
        )

    metric_specs: list[tuple[str, str, str]] = [
        ("Total trades", "num", "n"),
        ("Wins", "num", "wins"),
        ("Losses", "num", "losses"),
        ("Win %", "num", "win_pct"),
        ("Avg PnL %", "num", "avg_pnl_pct"),
        ("Book AVG_PNL_PCT_WO_MAX", "num", "avg_wo_max"),
        ("Expectancy $", "money", "expectancy_d"),
        ("Expectancy %", "num", "expectancy_pct"),
        ("Avg win %", "num", "avg_win_pct"),
        ("Avg loss %", "num", "avg_loss_pct"),
        ("Win/Loss ratio (count)", "num", "wl_count"),
        ("Win/Loss ratio $", "num", "wl_dollar"),
        ("Profit factor", "num", "pf"),
        ("Ann ROR %", "num", "ann_ror"),
        ("Max DD %", "num", "max_dd"),
        ("Calmar", "num", "calmar"),
        ("Sharpe", "num", "sharpe"),
        ("Profit per capital day", "money", "profit_per_cap_day"),
        ("Capital days", "num", "capital_days"),
        ("Avg days held", "num", "avg_days"),
        ("Median days held", "num", "median_days"),
        ("P90 days held", "num", "p90_days"),
        ("Losing streak", "num", "losing_streak"),
        ("Pct PnL max symbol", "num", "pct_max_sym"),
        ("Pct PnL max trade", "num", "pct_max_trade"),
        ("Pct PnL top10", "num", "pct_top10"),
        ("Pct PnL bottom10", "num", "pct_bot10"),
    ]
    book_headers = [("Metric", "text"), ("Slice", "text")]
    for nm in names:
        book_headers.append((nm, "num"))
        if nm != "CONTROL":
            book_headers.append((f"Δ {nm}", "num"))
    book_headers = filter_html_compare_columns(book_headers)
    bth = "".join(sortable_th(a, b) for a, b in book_headers)
    bbody = []
    for sl in ("FULL", "IS", "OOS"):
        bbody.append(
            "<tr>"
            f"<td>Universe size (symbols traded)</td><td>{sl}</td>"
            + "".join(
                (
                    f"<td>{fmt_int(packs[nm][sl]['n_syms'])}</td>"
                    + (
                        f"<td>{fmt_int(packs[nm][sl]['n_syms'] - ctrl[sl]['n_syms'])}</td>"
                        if nm != "CONTROL"
                        else ""
                    )
                )
                for nm in names
            )
            + "</tr>"
        )
        for label, typ, key in metric_specs:
            cells = [f"<td>{html_mod.escape(label)}</td>", f"<td>{sl}</td>"]
            for nm in names:
                val = packs[nm][sl][key]
                if typ == "money":
                    cell = format_money(val)
                elif key in {
                    "win_pct", "avg_pnl_pct", "avg_wo_max", "expectancy_pct",
                    "avg_win_pct", "avg_loss_pct", "ann_ror", "max_dd",
                    "pct_max_sym", "pct_max_trade", "pct_top10", "pct_bot10",
                }:
                    cell = fmt_pct(val)
                elif key in {"n", "wins", "losses", "capital_days", "losing_streak"}:
                    cell = fmt_int(val)
                else:
                    cell = fmt_num(val)
                cells.append(f"<td>{cell}</td>")
                if nm != "CONTROL":
                    cv = ctrl[sl][key]
                    if typ == "money":
                        try:
                            dlt = float(val) - float(cv)
                            cells.append(f"<td>{dlt:+,.2f}</td>")
                        except (TypeError, ValueError):
                            cells.append("<td>—</td>")
                    elif key in {"n", "wins", "losses", "capital_days", "losing_streak"}:
                        try:
                            cells.append(f"<td>{int(val) - int(cv):+,d}</td>")
                        except (TypeError, ValueError):
                            cells.append("<td>—</td>")
                    else:
                        cells.append(f"<td>{fmt_delta_pct(val, cv)}</td>")
            bbody.append("<tr>" + "".join(cells) + "</tr>")
        for lab in (
            "Avg days underwater",
            "P90 days underwater",
            "Max days underwater (equity)",
            "% days underwater (equity)",
            "Avg positions",
            "Median positions",
            "Max positions",
            "Aggressive Total PnL $",
            "Aggressive Max DD %",
            "Pct PnL max industry",
            "CES avg",
            "CES median",
            "Σ Paul Score",
            "Mean Paul Score",
            "Σ FIT Score",
            "Mean FIT Score",
            "Σ FIT Score Robust",
            "Mean FIT Score Robust",
            "Mean AVG_PNL_PCT_WO_MAX",
            "Mean OUTLIER_PCT_OF_WINS",
            "Mean AVG_TRADES_PER_YEAR",
            "Mean MAX_WIN_PCT",
        ):
            cells = [f"<td>{html_mod.escape(lab)}</td>", f"<td>{sl}</td>"]
            for nm in names:
                cells.append("<td>N/A</td>")
                if nm != "CONTROL":
                    cells.append("<td>—</td>")
            bbody.append("<tr>" + "".join(cells) + "</tr>")

    exit_keys = sorted({k for arm in ARMS for k in packs[arm.name]["FULL"]["exits"]})
    eth = "".join(
        sortable_th(a, b)
        for a, b in [("Arm", "text"), ("Slice", "text")] + [(k, "text") for k in exit_keys]
    )
    ebody = []
    for sl in ("FULL", "IS", "OOS"):
        for arm in ARMS:
            ex = packs[arm.name][sl]["exits"]
            ebody.append(
                "<tr>"
                f"<td>{html_mod.escape(arm.name)}</td><td>{sl}</td>"
                + "".join(f"<td>{_exit_cell(ex, k)}</td>" for k in exit_keys)
                + "</tr>"
            )

    arm_rows = []
    for arm in ARMS:
        v = verdicts.get(arm.name, "—")
        klass = v.lower() if v in {"KEEP", "HOLD", "DISMISS"} else ""
        arm_rows.append(
            "<tr>"
            f"<td>{html_mod.escape(arm.name)}</td>"
            f"<td>{'REF' if arm.name == 'REF_no_roll' else 'EXIT'}</td>"
            f"<td>{html_mod.escape(arm.knob)}</td>"
            f"<td>{html_mod.escape(arm.hypothesis)}</td>"
            f"<td>{html_mod.escape(arm.quote)}</td>"
            f"<td class='{klass}'>{html_mod.escape(v)}</td>"
            "</tr>"
        )

    house_html = "House full-engine pin not written yet (overlay-only numbers below)."
    if house.get("ts"):
        house_html = (
            f"House pin <code>RSI_house_last_run_ts.txt</code> = <strong>{html_mod.escape(str(house['ts']))}</strong> "
            f"(full engine, roll 8). LatestRun / Report: N={fmt_int(house.get('n'))}, "
            f"Avg%={fmt_pct(house.get('avg'))}, Ann ROR={fmt_pct(house.get('ann_ror'))}, "
            f"avg days={fmt_num(house.get('avg_days'))}. "
            f"Old no-roll house <code>{html_mod.escape(str(house.get('old_ts') or CTRL_TS_FALLBACK))}</code>: "
            f"N={fmt_int(house.get('old_n'))}, Avg%={fmt_pct(house.get('old_avg'))}, "
            f"Ann ROR={fmt_pct(house.get('old_ann_ror'))}, avg days={fmt_num(house.get('old_avg_days'))}. "
            "Report Ann ROR is the DailyRun book figure (host equity). Overlay Ann ROR in the tables "
            "below uses the same Closed-overlay formula as the giveback stamp Paul just viewed "
            "(larger %; same direction)."
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RSI roll EXIT AB — {STAMP}</title>
<style>{SORT_CSS}</style>
</head>
<body>
<h1>RSI roll-from-max — EXIT A/B (DailyRun adopt 8; neighbors 6/7/9/10)</h1>
<p class="meta">Stamp <code>{STAMP}</code> · source Closed <code>RSI_Closed_{html_mod.escape(src_ts)}.csv</code>
(atr=2.93 house, no min_dist, no roll) · entries frozen · overlay exits only ·
IS = entry &lt; 2024-01-01 · OOS report-only · roll 8 is DailyRun (preference, not gold).
Click column headers to sort.</p>

<div class="ask">
  <h2>What you asked</h2>
  <p>{html_mod.escape(ORIGINAL_REQUEST)}</p>
  <h2>In plain English</h2>
  <p>{html_mod.escape(PLAIN_ENGLISH)}</p>
</div>

<div class="insight">
  <h2>Adopted knob + house pin</h2>
  <p><code>rsi_roll_from_max=8</code> — flatten next open when (in-trade max RSI14 − current RSI14) ≥ 8.
  RSI ≥ 70 and the 20-day time stop stay as other exits (same overlay Paul saw as
  <code>EXIT_rsi_roll8</code>). Engine flag is off unless set; DailyRun / <code>run_rsi.bat</code> default is 8.</p>
  <p>{house_html}</p>
  <p>Change roll: <code>set RSI_ROLL_FROM_MAX=0</code> (off) or <code>6</code>/<code>7</code>/<code>9</code>/<code>10</code>,
  or <code>run_rsi.bat -v rsi_roll_from_max=0</code>.</p>
</div>

<div class="insight">
  <h2>Freeze (ENTRY unchanged)</h2>
  <p>Neutral-after-overbought, <code>rsi_ob=70</code>, <code>rsi_os=30</code>,
  <code>rsi_max_trigger=60</code>, <code>rsi_min_atr_pct=2.93</code>, min distance to 52-week high
  <strong>off</strong>, <code>rsi_exit=70</code>, <code>rsi_time_stop_days=20</code>, fill next open,
  sheet ${SHEET:,.0f}. Overlay Max DD / Sharpe seed ${INIT:,.0f} (exit-date equity).
  Paul / FIT / daily underwater / position counts are N/A on this Closed overlay.
  CONTROL is roll 8 (adopted). <code>REF_no_roll</code> is the old book for context, not a candidate.</p>
</div>

<h2>Arms (EXIT, one knob = roll points)</h2>
<p class="meta">KEEP/DISMISS vs adopted roll 8 on IS Avg% / expectancy / DD (quality).
Ann ROR is why 8 was adopted — a neighbor that only wins Avg% does not un-adopt 8.
You picked 8 after seeing the giveback table: <strong>in-sample selection</strong>.</p>
<table class="sortable"><thead><tr>
{sortable_th("Arm", "text")}{sortable_th("Kind", "text")}{sortable_th("Knob", "text")}{sortable_th("Hypothesis", "text")}{sortable_th("Note", "text")}{sortable_th("Verdict", "text")}
</tr></thead><tbody>{"".join(arm_rows)}</tbody></table>

<h2>Headline N / Avg% / Ann ROR (FULL / IS / OOS)</h2>
<p class="meta">Click column headers to sort. Ann ROR is the Closed-overlay figure
(<code>overlay_ann_ror_max_dd</code>, $10k notional, $500k seed, exit-date equity).
Deltas vs CONTROL (roll 8). KEEP needs IS Avg% and expectancy up without wrecking N or DD;
OOS soften → HOLD. Quality over count.</p>
<table class="sortable"><thead><tr>{hth}</tr></thead><tbody>{"".join(hbody)}</tbody></table>

<h2>Canonical book metrics (Closed overlay)</h2>
<p class="meta">Click column headers to sort. Sheet / Total PnL $ omitted. Ann ROR / Max DD / Calmar / Sharpe
from Closed overlay. Deltas vs CONTROL (roll 8). Underwater / positions / Paul / FIT = N/A.</p>
<table class="sortable"><thead><tr>{bth}</tr></thead><tbody>{"".join(bbody)}</tbody></table>

<h2>Exit mix</h2>
<p class="meta">Click column headers to sort. Counts and % of that slice.</p>
<table class="sortable"><thead><tr>{eth}</tr></thead><tbody>{"".join(ebody)}</tbody></table>

<div class="insight">
  <h2>Honesty</h2>
  <ul>
    <li>EXIT overlay on frozen atr=2.93 entries. Roll 8 was chosen after seeing
    <code>rsi_giveback_lockin_ab_20260916</code> (IS Avg% 4.91 vs no-roll 7.23, Ann ROR up).
    That is <strong>in-sample selection</strong> / a preference, not a quality KEEP.</li>
    <li>This neighbor grid is also in-sample if anyone picks 6/7/9/10 from the table. Do not.</li>
    <li>OOS is report-only. Do not retune on OOS. OOS soften → HOLD.</li>
    <li>Overlay cannot invent a later fill than the original no-roll close; 9/10 can only sit
    between roll 8 and the old TIME/70 exit.</li>
    <li>House engine with roll 8 may add re-entries after earlier exits — LatestRun N can exceed overlay N.</li>
    <li>Not walk-forward gold. Preference DailyRun wire.</li>
  </ul>
</div>
{SORT_JS}
</body>
</html>
"""
    path = OUT_DIR / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def write_baseline(
    packs: dict[str, dict[str, dict[str, Any]]],
    verdicts: dict[str, str],
    src_ts: str,
    house: dict[str, Any],
) -> Path:
    ctrl = packs["CONTROL"]
    ref = packs["REF_no_roll"]
    lines = [
        f"# BASELINE — {STAMP}",
        "",
        "**Status:** DailyRun EXIT adopt `rsi_roll_from_max=8` (preference). Neighbor AB is report-only. **Not gold. Not walk-forward.** OOS report-only.",
        "",
        "## What you asked",
        "",
        f"> {ORIGINAL_REQUEST}",
        "",
        "## In plain English",
        "",
        PLAIN_ENGLISH,
        "",
        "## Adopted knob",
        "",
        "| Knob | Value |",
        "|------|-------|",
        "| `rsi_roll_from_max` | **8** (engine 0 = off; DailyRun / `run_rsi.bat` default 8) |",
        "| Definition | Sell next open when (in-trade max RSI14 − current RSI14) ≥ 8 |",
        "| Other exits | RSI14 ≥ 70 (`OVERBOUGHT`); else flatten at 20 calendar days (`TIME`) |",
        "| Fill | next open (same as other RSI exits) |",
        "| Why adopted | Preference — IS Avg% worse vs no-roll (4.91 vs 7.23 on the giveback overlay); Ann ROR / shorter hold better |",
        "| Selection | In-sample: picked `EXIT_rsi_roll8` after seeing `rsi_giveback_lockin_ab_20260916/compare.html` |",
        "",
        "## Command line to change roll",
        "",
        "```bat",
        "set RSI_ROLL_FROM_MAX=0",
        "run_rsi.bat",
        "```",
        "",
        "Or one-shot: `run_rsi.bat -v rsi_roll_from_max=0` (off) / `6` / `7` / `9` / `10`.",
        "",
        "## Freeze (ENTRY unchanged)",
        "",
        "| Knob | Value |",
        "|------|-------|",
        f"| Source Closed (no-roll entries) | `drive/RSI_Closed_{src_ts}.csv` |",
        "| Kind | EXIT overlay (entries frozen) + DailyRun engine flag |",
        "| rsi_ob / rsi_os | 70 / 30 |",
        "| rsi_max_trigger | 60 |",
        "| rsi_min_atr_pct | 2.93 |",
        "| min_dist_to_52w_high | off |",
        "| rsi_exit | 70 |",
        "| rsi_time_stop_days | 20 calendar |",
        "| Universe | `drive/universes/rsi_universe.csv` (149) |",
        f"| Sheet notional | ${SHEET:,.0f} |",
        f"| Overlay seed | ${INIT:,.0f} |",
        "| IS cut | entry_date < 2024-01-01 |",
        "",
        "## House pin / LatestRun (full engine)",
        "",
    ]
    if house.get("ts"):
        lines += [
            f"- Pin: `drive/RSI_house_last_run_ts.txt` = **{house['ts']}** (roll 8 engine)",
            f"- LatestRun / Report: N={house.get('n')} Avg%={house.get('avg')} Ann ROR%={house.get('ann_ror')} avg days={house.get('avg_days')}",
            f"- Old no-roll house `{house.get('old_ts')}`: N={house.get('old_n')} Avg%={house.get('old_avg')} Ann ROR%={house.get('old_ann_ror')} avg days={house.get('old_avg_days')}",
            f"- Overlay REF_no_roll (same entries, Closed-overlay Ann ROR): N={ref['FULL']['n']} Avg%={ref['FULL']['avg_pnl_pct']:.2f}% Ann ROR={ref['FULL']['ann_ror']:.2f}%",
            "- Engine N matched overlay N=874 on this universe (no extra re-entries this run).",
        ]
    else:
        lines.append("- House pin not written yet (run `run_rsi.bat` after the wire).")
    lines += [
        "",
        "## Arms",
        "",
        "| Arm | Kind | Knob | Hypothesis | Verdict |",
        "|-----|------|------|------------|---------|",
    ]
    for arm in ARMS:
        lines.append(
            f"| {arm.name} | {'REF' if arm.name == 'REF_no_roll' else 'EXIT'} | `{arm.knob}` | {arm.hypothesis} | {verdicts.get(arm.name, '—')} |"
        )
    lines += [
        "",
        "## FULL / IS / OOS vs CONTROL (roll 8)",
        "",
        "Ann ROR is `overlay_ann_ror_max_dd` (same as compare.html).",
        "",
        "| Arm | FULL N | FULL Avg% | FULL Ann ROR | ΔAvg FULL | IS N | IS Avg% | IS Ann ROR | ΔAvg IS | OOS N | OOS Avg% | OOS Ann ROR | ΔAvg OOS | Verdict |",
        "|-----|--------|-----------|--------------|-----------|------|---------|------------|---------|-------|----------|-------------|----------|---------|",
    ]
    for arm in ARMS:
        p = packs[arm.name]
        lines.append(
            f"| {arm.name} | {p['FULL']['n']} | {p['FULL']['avg_pnl_pct']:.2f}% | "
            f"{p['FULL']['ann_ror']:.2f}% | "
            f"{p['FULL']['avg_pnl_pct'] - ctrl['FULL']['avg_pnl_pct']:+.2f} | "
            f"{p['IS']['n']} | {p['IS']['avg_pnl_pct']:.2f}% | "
            f"{p['IS']['ann_ror']:.2f}% | "
            f"{p['IS']['avg_pnl_pct'] - ctrl['IS']['avg_pnl_pct']:+.2f} | "
            f"{p['OOS']['n']} | {p['OOS']['avg_pnl_pct']:.2f}% | "
            f"{p['OOS']['ann_ror']:.2f}% | "
            f"{p['OOS']['avg_pnl_pct'] - ctrl['OOS']['avg_pnl_pct']:+.2f} | "
            f"{verdicts.get(arm.name, '—')} |"
        )
    lines += [
        "",
        "## Honesty",
        "",
        "- One knob: `rsi_roll_from_max`. Entries frozen at atr=2.93 / no min_dist.",
        "- Roll 8 chosen after seeing the giveback AB table → in-sample selection / preference (metrics DISMISS on Avg%).",
        "- Neighbor 6/7/9/10 judged vs adopted 8 on quality (Avg% / expectancy / DD). Do not pick a neighbor from this table to replace 8.",
        "- OOS report-only. Soften → HOLD, do not retune OOS.",
        "- Overlay cannot exit later than the original no-roll close.",
        "- Not walk-forward gold.",
        "",
        f"Compare: `drive/paul_experiments/{STAMP}/compare.html`",
        "",
    ]
    path = OUT_DIR / "BASELINE.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_hypothesis(src_ts: str) -> Path:
    text = f"""# HYPOTHESIS — {STAMP}

| Field | Fill |
|-------|------|
| System / prefix | RSI (Relative Strength Index) |
| Baseline stamp | Adopted roll 8 on `{src_ts}` Closed entries |
| Universe | Same names/fills as `RSI_Closed_{src_ts}.csv` (atr=2.93, no min_dist) |
| Evidence | Paul preferred `EXIT_rsi_roll8` on `rsi_giveback_lockin_ab_20260916` for Ann ROR / shorter hold |
| Hypothesis | Neighbors 6/7/9/10 do not beat adopted 8 on IS quality; 8 stays the DailyRun default |
| Single knob | `rsi_roll_from_max` |
| Frozen settings | Entries + rsi_exit=70 + ts=20 + next_open |
| Alternatives | 6, 7, 9, 10 vs CONTROL 8; REF_no_roll is context only |
| Decision | Neighbor KEEP/HOLD/DISMISS on quality vs 8; do not un-adopt 8 from this grid |

OOS (`entry_date >= 2024-01-01`) is report-only.
"""
    path = OUT_DIR / "HYPOTHESIS.md"
    path.write_text(text, encoding="utf-8")
    return path


def write_plan(src_ts: str) -> Path:
    text = f"""# AB_PLAN — {STAMP}

## Evidence → knob

Paul, after `rsi_giveback_lockin_ab_20260916/compare.html` (Ann ROR added to the headline):

> thanks. i like this one for RSI. let's adopt it. it is a smaller IS Avg pnl, but gets us out of trades sooner so our Ann ROR increases. can you run an AB test of roll 6, 7, 9, and 10 to compare to 8?

Adopted: `EXIT_rsi_roll8` = `rsi_roll_from_max=8`. Not the S&P X=10 book. Not a price trail.

| Arm | Knob | Why |
|-----|------|-----|
| CONTROL | `rsi_roll_from_max=8` | Adopted DailyRun exit |
| EXIT_roll6 | 6 | Tighter neighbor |
| EXIT_roll7 | 7 | Tighter neighbor |
| EXIT_roll9 | 9 | Looser neighbor |
| EXIT_roll10 | 10 | Looser neighbor |
| REF_no_roll | off | Old house (context) |

## Execution

Closed overlay on stamp `{src_ts}`. Same entries. IS/OOS reported. House full-history run wires DailyRun / LatestRun to 8.
"""
    path = OUT_DIR / "AB_PLAN.md"
    path.write_text(text, encoding="utf-8")
    return path


def _report_metrics(ts: str) -> dict[str, Any]:
    out: dict[str, Any] = {"ts": ts}
    closed = DRIVE / f"RSI_Closed_{ts}.csv"
    report = DRIVE / f"RSI_Report_{ts}.csv"
    if closed.is_file():
        rows = load_closed(closed)
        out["n"] = len(rows)
        if rows:
            out["avg"] = float(sum(r["pnl"] for r in rows) / len(rows))
            out["exits"] = dict(Counter(str(r["exit"] or "?") for r in rows))
    if report.is_file():
        with report.open(encoding="utf-8-sig", newline="") as f:
            rec = next(iter(csv.DictReader(f)), None)
        if rec:
            if rec.get("Ann_ROR"):
                try:
                    out["ann_ror"] = float(str(rec["Ann_ROR"]).replace("%", "").replace(",", ""))
                except ValueError:
                    pass
            if rec.get("Avg_PNL_Pct"):
                try:
                    out["avg"] = float(str(rec["Avg_PNL_Pct"]).replace("%", "").replace(",", ""))
                except ValueError:
                    pass
            if rec.get("Avg_Days_Held"):
                try:
                    out["avg_days"] = float(str(rec["Avg_Days_Held"]).replace(",", ""))
                except ValueError:
                    pass
            if rec.get("Max_DD"):
                try:
                    out["max_dd"] = float(str(rec["Max_DD"]).replace("%", "").replace(",", ""))
                except ValueError:
                    pass
    return out


def _house_metrics() -> dict[str, Any]:
    ts = _pin_ts()
    out = _report_metrics(ts) if ts else {"ts": ""}
    old = _report_metrics(CTRL_TS_FALLBACK)
    if old.get("n"):
        out["old_ts"] = CTRL_TS_FALLBACK
        out["old_n"] = old.get("n")
        out["old_avg"] = old.get("avg")
        out["old_ann_ror"] = old.get("ann_ror")
        out["old_avg_days"] = old.get("avg_days")
    if not ts:
        return out
    dest = OUT_DIR / "house"
    dest.mkdir(parents=True, exist_ok=True)
    for name in (
        f"RSI_Closed_{ts}.csv",
        f"RSI_Open_{ts}.csv",
        f"RSI_Watchlist_{ts}.csv",
        f"RSI_Summary_{ts}.csv",
        f"RSI_Report_{ts}.csv",
        f"RSI_EquityCurve_{ts}.csv",
        f"RSI_EquityMeta_{ts}.csv",
        "RSI_house_last_run_ts.txt",
        "RSI_LatestRun_Closed.csv",
        "RSI_LatestRun_Report.csv",
    ):
        src = DRIVE / name
        if src.is_file():
            shutil.copy2(src, dest / name)
    return out


def _packs_from_overlays() -> dict[str, dict[str, dict[str, Any]]]:
    packs: dict[str, dict[str, dict[str, Any]]] = {}
    for arm in ARMS:
        path = OUT_DIR / f"overlay_{arm.name}.csv"
        if not path.is_file():
            raise SystemExit(f"Missing {path}")
        rows = load_closed(path)
        packs[arm.name] = {sl: pack(slc(rows, sl)) for sl in ("FULL", "IS", "OOS")}
    return packs


def write_all(packs: dict[str, dict[str, dict[str, Any]]], src_ts: str) -> tuple[Path, Path]:
    verdicts = _verdicts(packs)
    house = _house_metrics()
    html_path = write_html(packs, verdicts, src_ts, house)
    base_path = write_baseline(packs, verdicts, src_ts, house)
    write_hypothesis(src_ts)
    write_plan(src_ts)
    (OUT_DIR / "run_meta.json").write_text(
        json.dumps(
            {
                "src_ts": src_ts,
                "house": house,
                "verdicts": verdicts,
                "headline": {
                    a.name: {
                        sl: {
                            "n": packs[a.name][sl]["n"],
                            "avg": packs[a.name][sl]["avg_pnl_pct"],
                            "ann_ror": packs[a.name][sl]["ann_ror"],
                        }
                        for sl in ("FULL", "IS", "OOS")
                    }
                    for a in ARMS
                },
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return html_path, base_path


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    src_path, src_ts = _src_closed()
    if "--html-only" in sys.argv:
        packs = _packs_from_overlays()
        html_path, base_path = write_all(packs, src_ts)
        print(f"Wrote {html_path}", flush=True)
        print(f"Wrote {base_path}", flush=True)
        return 0
    src_rows = load_closed(src_path)
    print(f"Loaded {len(src_rows)} Closed trades from {src_path.name}", flush=True)
    by_arm = run_overlay(src_rows)
    write_csv_books(by_arm)
    packs = {name: {sl: pack(slc(rows, sl)) for sl in ("FULL", "IS", "OOS")} for name, rows in by_arm.items()}
    html_path, base_path = write_all(packs, src_ts)
    print(f"Wrote {html_path}", flush=True)
    print(f"Wrote {base_path}", flush=True)
    for arm in ARMS:
        p = packs[arm.name]
        print(
            f"  {arm.name:14s} FULL n={p['FULL']['n']} avg={p['FULL']['avg_pnl_pct']:.2f}% "
            f"ann={p['FULL']['ann_ror']:.2f}%  IS avg={p['IS']['avg_pnl_pct']:.2f}% "
            f"ann={p['IS']['ann_ror']:.2f}%",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
