#!/usr/bin/env python3
"""Side-by-side: each system's current exit vs Paul's hand-picked high-water stop.

Research only. Does not wire DailyRun. Does not edit earlier stamps.
Reuses the activation-delay walk from hwm_stop_activate_at_n_20261015.
"""
from __future__ import annotations

import html as html_mod
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any, Optional

import numpy as np

_REPO = Path(__file__).resolve().parents[1]
_PE = _REPO / "drive" / "paul_experiments"
_TOOLS = _REPO / "tools"
for _p in (_PE, _TOOLS, _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from compare_format import format_money, format_money_delta  # noqa: E402
from report_page_extras import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)

STAMP = "hwm_stop_paul_picks_20261015"
OUT = _PE / STAMP
FLAT_PP = 0.005  # same printed average return to two decimals

ASK = (
    "give me a side by side compare of each system with the control and with my picks "
    "for the activation / keep. i want to see all the metrics\n"
    "BRT 6% keep 70%\n"
    "RL 6% keep 80%\n"
    "YH 2% keep 70%\n"
    "MTS 4% keep 60%\n"
    "WPBR 2% keep 80%\n"
    "RS 10% keep 80%\n"
    "RSI 6% keep 80%"
)

PLAIN = (
    "Each system keeps the trades it already has. The control is the exit those trades "
    "already used. Paul's pick is a high-water stop that stays off until the stock has "
    "been up enough. The high-water mark is the highest daily high since the buy. "
    "The overlay stays off until a prior day's high-water mark is at least the activation "
    "percent above the buy price. Until then the original stop and the original exit stay. "
    "Once it is on, the stop sits at the buy price plus a keep fraction of the rise from "
    "the buy to that high-water mark. If that stop is not above the system's own stop, "
    "the system's stop stays. The test never loosens risk. "
    "Break and ReTest (BRT) turns on at 6% and keeps 70% of the gain. "
    "Rocket Launcher (RL) turns on at 6% and keeps 80%. "
    "Year High (YH) turns on at 2% and keeps 70%. "
    "Magic Touch (MTS) turns on at 4% and keeps 60%. "
    "Weekly Pivot Break and Retest (WPBR) turns on at 2% and keeps 80%. "
    "Relative Strength vs SPY (RS) turns on at 10% and keeps 80%. "
    "Relative Strength Index (RSI) turns on at 6% and keeps 80%. "
    "Day T uses the high through day T−1 only. A new high raises the next day's stop, "
    "not today's. The entry day cannot turn the overlay on and cannot sell the stock. "
    "If the open is already through the stop, the sell is at the open. If the low tags "
    "the stop, the sell is at the stop. If the new stop never hits, the original exit stands. "
    "Paul noted that live, if price makes a new high before touching the stop, the stop rises. "
    "This historical test cannot see inside the daily bar, so a new high changes the following "
    "day's stop. The test is not switched to an intraday ratchet. "
    "This is not a Simple Moving Average (SMA) trail, and it is not Rocket Launcher's separate "
    "partial-exit plan (sell 80% at +20%, leftover stop at the entry price, leftover sold at +40%)."
)

PICKS = [
    ("BRT", "Break and ReTest (BRT)", 6.0, 0.70),
    ("RL", "Rocket Launcher (RL)", 6.0, 0.80),
    ("YH", "Year High (YH)", 2.0, 0.70),
    ("MTS", "Magic Touch (MTS)", 4.0, 0.60),
    ("WPBR", "Weekly Pivot Break and Retest (WPBR)", 2.0, 0.80),
    ("RS", "Relative Strength vs SPY (RS)", 10.0, 0.80),
    ("RSI", "Relative Strength Index (RSI)", 6.0, 0.80),
]

# Computed book metrics. Total trades is N, shown once per system per slice.
METRIC_SPEC = [
    ("Wins", "wins", "int"),
    ("Losses", "losses", "int"),
    ("Win %", "win_pct", "pct"),
    ("Avg PnL %", "avg_pnl_pct", "pct"),
    ("Book AVG_PNL_PCT_WO_MAX", "avg_pnl_pct_wo_max", "pct"),
    ("Expectancy $", "expectancy_d", "money"),
    ("Expectancy %", "expectancy_pct", "pct"),
    ("Avg win %", "avg_win_pct", "pct"),
    ("Avg loss %", "avg_loss_pct", "pct"),
    ("Win/Loss ratio (count)", "wl_count", "num"),
    ("Win/Loss ratio $", "wl_dollars", "num"),
    ("Profit factor", "profit_factor", "num"),
    ("Ann ROR %", "ann_ror", "pct"),
    ("Max DD %", "max_dd", "pct"),
    ("Calmar", "calmar", "num"),
    ("Sharpe", "sharpe", "num"),
    ("Profit per capital day", "ppcd", "money"),
    ("Capital days", "capital_days", "num"),
    ("Avg days held", "avg_days", "num"),
    ("Median days held", "median_days", "num"),
    ("P90 days held", "p90_days", "num"),
    ("Losing streak", "losing_streak", "int"),
    ("Pct PnL max symbol", "pct_max_symbol", "pct"),
    ("Pct PnL max trade", "pct_max_trade", "pct"),
    ("Pct PnL max industry", "pct_max_industry", "pct"),
    ("Pct PnL top10", "pct_top10", "pct"),
    ("Pct PnL bottom10", "pct_bottom10", "pct"),
    ("Outlier % of win $", "outlier_win_pct", "pct"),
    ("Trades per year", "trades_per_year", "num"),
]

NOT_COMPUTED = [
    ("Universe size", "Same closed book on both arms. Unique symbols are in the coverage table. Entries were not rerun."),
    ("Avg days underwater", "Needs a daily equity curve. This overlay does not build one."),
    ("P90 days underwater", "Needs a daily equity curve. This overlay does not build one."),
    ("Max days underwater (equity)", "Needs a daily equity curve. This overlay does not build one."),
    ("% days underwater (equity)", "Needs a daily equity curve. This overlay does not build one."),
    ("Avg positions", "Needs concurrent open positions. This overlay scores one closed trade at a time."),
    ("Median positions", "Needs concurrent open positions. This overlay scores one closed trade at a time."),
    ("Max positions", "Needs concurrent open positions. This overlay scores one closed trade at a time."),
    ("Aggressive Total PnL $", "Needs the aggressive sizing path. Not recomputed."),
    ("Aggressive Max DD %", "Needs the aggressive sizing path. Not recomputed."),
    ("CES avg", "Needs a Summary rebuild. Not recomputed."),
    ("CES median", "Needs a Summary rebuild. Not recomputed."),
    ("Σ Paul Score", "Needs a Summary rebuild. Not recomputed."),
    ("Mean Paul Score", "Needs a Summary rebuild. Not recomputed."),
    ("Σ FIT Score", "Needs a Summary rebuild. Not recomputed."),
    ("Mean FIT Score", "Needs a Summary rebuild. Not recomputed."),
    ("Σ FIT Score Robust", "Needs a Summary rebuild. Not recomputed."),
    ("Mean FIT Score Robust", "Needs a Summary rebuild. Not recomputed."),
    ("Mean AVG_PNL_PCT_WO_MAX", "Symbol-mean from Summary. The book-level leave-max-win-out number is in the compare tables as Book AVG_PNL_PCT_WO_MAX."),
    ("Mean OUTLIER_PCT_OF_WINS", "Symbol-mean from Summary. The book-level outlier share of win dollars is in the compare tables as Outlier % of win $."),
    ("Mean AVG_TRADES_PER_YEAR", "Symbol-mean from Summary. Book trades per year is in the compare tables."),
    ("Mean MAX_WIN_PCT", "Symbol-mean from Summary. Not recomputed."),
    ("Total PnL $", "Omitted from the HTML compare tables. Kept off the page on purpose."),
    ("Sheet PnL $", "Omitted from the HTML compare tables. Kept off the page on purpose."),
]


def _load_act():
    path = _TOOLS / "hwm_stop_activate_at_n_20261015.py"
    name = "hwm_stop_activate_at_n_20261015"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _th(label: str, typ: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{typ}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _fmt(v: Any, kind: str) -> str:
    if v is None:
        return "—"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return html_mod.escape(str(v))
    if not math.isfinite(x):
        return "—"
    if kind == "money":
        return html_mod.escape(format_money(x))
    if kind == "int":
        return f"{int(round(x)):,}"
    if kind == "pct":
        return f"{x:.2f}%"
    return f"{x:.2f}"


def _delta(a: Any, b: Any) -> Optional[float]:
    if a is None or b is None:
        return None
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(fa) and math.isfinite(fb)):
        return None
    return fa - fb


def _fmt_delta(v: Optional[float], kind: str) -> str:
    if v is None or not math.isfinite(float(v)):
        return "—"
    if kind == "money":
        return html_mod.escape(format_money_delta(v))
    if kind == "int":
        return f"{int(round(v)):+,}"
    if kind == "pct":
        return f"{v:+.2f}%"
    return f"{v:+.2f}"


def _is_read(ctrl: Optional[float], pick: Optional[float]) -> str:
    if ctrl is None or pick is None:
        return "not computed"
    d = float(pick) - float(ctrl)
    if abs(d) < FLAT_PP:
        return "flat"
    return "better" if d > 0 else "worse"


def _pick_label(hurdle: float, keep: float) -> str:
    return f"Activate at {hurdle:.0f}%, keep {keep * 100:.0f}%"


def run_one(act, code: str, label: str, hurdle: float, keep: float) -> dict[str, Any]:
    hwm1 = act._load_hwm1()
    path = hwm1._DRIVE / f"{code}_LatestRun_Closed.csv"
    print(f"=== {code} activate {hurdle:.0f}% keep {keep:.0%} ===", flush=True)
    if not path.exists():
        raise SystemExit(f"{code}: missing closed book {path}")
    df, meta = hwm1.load_trades(code)
    print(f"  loaded {len(df):,}", flush=True)
    cash, cash_src, dollars = hwm1.slot_cash(df, code)
    side = df["side"].astype(str)
    long_syms = set(df.loc[side.isin(["LONG", "L", "", "NAN"]), "symbol"].astype(str).unique().tolist())
    print(f"  ohlc symbols {len(long_syms):,} cash={cash:,.2f}", flush=True)
    ohlc = hwm1.load_ohlc(long_syms)
    print(f"  ohlc hit {len(ohlc):,}", flush=True)
    saved = act.KS
    act.KS = (float(keep),)
    try:
        pack = act.replay_system(df, dollars, ohlc, np.array([float(hurdle)], dtype=np.float64))
    finally:
        act.KS = saved
    if pack.get("n", 0) == 0:
        raise SystemExit(
            f"{code}: no usable trades (shorts {pack.get('short_skipped')}, missing {pack.get('missing_ohlc')})"
        )
    ctrl_cols = {
        "pnl": pack["book_pnl"],
        "pnl_d": pack["book_d"],
        "days": pack["book_days"],
        "opened": pack["opened"],
        "closed": pack["closed"],
        "symbol": pack["symbol"],
        "industry": pack["industry"],
        "exit_type": pack["exit_type"],
        "hit": np.zeros(pack["n"], dtype=bool),
    }
    pick_cols = act._arm_columns(pack, 0, 0)
    slices: dict[str, dict[str, Any]] = {}
    for mode in ("FULL", "IS", "OOS"):
        mask = act._slice_mask(ctrl_cols["opened"], mode)
        ctrl_m = act._full_metrics(ctrl_cols, mask, cash)
        pick_m = act._full_metrics(pick_cols, mask, cash)
        if ctrl_m["n"] != pick_m["n"]:
            raise RuntimeError(f"{code} {mode} N control {ctrl_m['n']} != pick {pick_m['n']}")
        slices[mode] = {"control": ctrl_m, "pick": pick_m}
    symbols = {str(s) for s in pack["symbol"]}
    hits = int(np.sum(pack["tag"][:, 0, 0] > 0))
    res = {
        "code": code,
        "label": label,
        "hurdle": float(hurdle),
        "keep": float(keep),
        "pick_label": _pick_label(hurdle, keep),
        "cash": float(cash),
        "cash_src": cash_src,
        "stop_col": meta.get("stop_col") or "",
        "n_full": slices["FULL"]["control"]["n"],
        "n_is": slices["IS"]["control"]["n"],
        "n_oos": slices["OOS"]["control"]["n"],
        "short_skipped": int(pack["short_skipped"]),
        "missing_ohlc": int(pack["missing_ohlc"]),
        "hits": hits,
        "n_symbols": len(symbols),
        "slices": slices,
        "is_read": _is_read(
            slices["IS"]["control"].get("avg_pnl_pct"),
            slices["IS"]["pick"].get("avg_pnl_pct"),
        ),
    }
    c = slices["IS"]["control"]
    p = slices["IS"]["pick"]
    print(
        f"  {code} N={res['n_full']:,} hits={hits:,} "
        f"IS avg {c.get('avg_pnl_pct')} -> {p.get('avg_pnl_pct')} ({res['is_read']})",
        flush=True,
    )
    return res


def _table(heads: list[str], rows: list[str]) -> str:
    return (
        f"{SWIPE_NOTE_HTML}\n<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>"
        + "".join(heads)
        + "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def _wide(results: list[dict[str, Any]], mode: str, title: str) -> str:
    heads = [_th("System", "text"), _th("Pick", "text"), _th("N", "num")]
    for label, _key, _kind in METRIC_SPEC:
        heads.append(_th(f"Control {label}", "num"))
        heads.append(_th(f"Pick {label}", "num"))
        heads.append(_th(f"Δ {label}", "num"))
    body = []
    for res in results:
        sl = res["slices"][mode]
        cells = [
            f"<td>{html_mod.escape(res['label'])}</td>",
            f"<td>{html_mod.escape(res['pick_label'])}</td>",
            f"<td>{int(sl['control']['n']):,}</td>",
        ]
        for label, key, kind in METRIC_SPEC:
            cval = sl["control"].get(key)
            pval = sl["pick"].get(key)
            cells.append(f"<td>{_fmt(cval, kind)}</td>")
            cells.append(f"<td>{_fmt(pval, kind)}</td>")
            cells.append(f"<td>{_fmt_delta(_delta(pval, cval), kind)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    note = ""
    if mode == "OOS":
        note = (
            "<p>Out-of-sample is report-only. These rows were not used to call a pick "
            "better, flat, or worse.</p>"
        )
    elif mode == "IS":
        note = (
            "<p>The keep or dismiss read uses in-sample average return only "
            "(entry before 2024-01-01). Flat means the two averages match to two decimals.</p>"
        )
    return (
        f"<h2>{html_mod.escape(title)}</h2>\n"
        "<p>One row per system. N is the control trade count; the pick uses the same trades. "
        "Delta is the pick minus the control. Click column headers to sort.</p>\n"
        + note
        + _table(heads, body)
    )


def _verdict_table(results: list[dict[str, Any]]) -> str:
    heads = [
        _th("System", "text"),
        _th("Pick", "text"),
        _th("IS N", "num"),
        _th("Control avg return", "num"),
        _th("Pick avg return", "num"),
        _th("Δ avg return", "num"),
        _th("In-sample read", "text"),
    ]
    rows = []
    for res in results:
        c = res["slices"]["IS"]["control"]
        p = res["slices"]["IS"]["pick"]
        rows.append(
            "<tr>"
            f"<td>{html_mod.escape(res['label'])}</td>"
            f"<td>{html_mod.escape(res['pick_label'])}</td>"
            f"<td>{int(c['n']):,}</td>"
            f"<td>{_fmt(c.get('avg_pnl_pct'), 'pct')}</td>"
            f"<td>{_fmt(p.get('avg_pnl_pct'), 'pct')}</td>"
            f"<td>{_fmt_delta(_delta(p.get('avg_pnl_pct'), c.get('avg_pnl_pct')), 'pct')}</td>"
            f"<td>{html_mod.escape(res['is_read'])}</td>"
            "</tr>"
        )
    return (
        "<h2>In-sample read</h2>\n"
        "<p>Better, flat, or worse is the pick's in-sample average return versus that system's control. "
        "Out-of-sample did not pick a winner. This is research only. Not gold. Not DailyRun.</p>\n"
        + _table(heads, rows)
    )


def _exit_table(results: list[dict[str, Any]]) -> str:
    heads = [
        _th("System", "text"),
        _th("Slice", "text"),
        _th("Exit", "text"),
        _th("Control count", "num"),
        _th("Control %", "num"),
        _th("Pick count", "num"),
        _th("Pick %", "num"),
        _th("Δ count", "num"),
    ]
    rows = []
    for res in results:
        for mode in ("FULL", "IS", "OOS"):
            c = res["slices"][mode]["control"]
            p = res["slices"][mode]["pick"]
            n = int(c["n"] or 0)
            keys = sorted(set(c.get("exit_mix") or {}) | set(p.get("exit_mix") or {}))
            for xt in keys:
                cc = int((c.get("exit_mix") or {}).get(xt, 0))
                pc = int((p.get("exit_mix") or {}).get(xt, 0))
                cp = (100.0 * cc / n) if n else None
                pp = (100.0 * pc / n) if n else None
                rows.append(
                    "<tr>"
                    f"<td>{html_mod.escape(res['label'])}</td>"
                    f"<td>{mode}</td>"
                    f"<td>{html_mod.escape(str(xt))}</td>"
                    f"<td>{cc:,}</td>"
                    f"<td>{_fmt(cp, 'pct')}</td>"
                    f"<td>{pc:,}</td>"
                    f"<td>{_fmt(pp, 'pct')}</td>"
                    f"<td>{pc - cc:+,}</td>"
                    "</tr>"
                )
    return (
        "<h2>Exit mix</h2>\n"
        "<p>Counts and percent of that slice. HWM_GAP is a sell at the open because the open was "
        "already through the high-water stop. HWM_STOP is a sell at the stop because the low tagged it. "
        "Other labels are the book's original exit type. N is the same on both arms, so the percents "
        "use that one trade count.</p>\n"
        + _table(heads, rows)
    )


def _coverage(results: list[dict[str, Any]]) -> str:
    heads = [
        _th("System", "text"),
        _th("Pick", "text"),
        _th("Slot cash", "num"),
        _th("How sized", "text"),
        _th("Stop column", "text"),
        _th("Symbols", "num"),
        _th("Full N", "num"),
        _th("IS N", "num"),
        _th("OOS N", "num"),
        _th("Shorts left out", "num"),
        _th("No OHLC path", "num"),
        _th("Pick stop hits", "num"),
    ]
    rows = []
    for res in results:
        rows.append(
            "<tr>"
            f"<td>{html_mod.escape(res['label'])}</td>"
            f"<td>{html_mod.escape(res['pick_label'])}</td>"
            f"<td>{html_mod.escape(format_money(res['cash']))}</td>"
            f"<td>{html_mod.escape(res['cash_src'])}</td>"
            f"<td>{html_mod.escape(res['stop_col'])}</td>"
            f"<td>{res['n_symbols']:,}</td>"
            f"<td>{res['n_full']:,}</td>"
            f"<td>{res['n_is']:,}</td>"
            f"<td>{res['n_oos']:,}</td>"
            f"<td>{res['short_skipped']:,}</td>"
            f"<td>{res['missing_ohlc']:,}</td>"
            f"<td>{res['hits']:,}</td>"
            "</tr>"
        )
    return (
        "<h2>Coverage and slot cash</h2>\n"
        "<p>Slot cash is the Closed median implied notional. Report capacity is used only when it "
        "sits within about 25% of that median. A flat $47,500 sheet slot is not used when the closed "
        "book is capacity-sized. Rocket Launcher has no Closed dollar column, so its slot is Report "
        "capacity and each trade's dollars are that slot times its percent return.</p>\n"
        + _table(heads, rows)
    )


def _missing_table() -> str:
    heads = [_th("Metric", "text"), _th("Status", "text")]
    rows = [
        "<tr>"
        f"<td>{html_mod.escape(name)}</td>"
        f"<td>{html_mod.escape(why)}</td>"
        "</tr>"
        for name, why in NOT_COMPUTED
    ]
    return (
        "<h2>Canonical metrics not in the number tables</h2>\n"
        "<p>These names are part of the canonical compare list. They are not invented here. "
        "Annualized rate of return, max drawdown, Calmar, and Sharpe for the overlay are in the "
        "number tables (exit-date equity, seed $500,000). If a slice cannot compute annualized "
        "rate of return, the Ann ROR cell is a dash and the reason is in the baseline.</p>\n"
        + _table(heads, rows)
    )


def render(results: list[dict[str, Any]]) -> str:
    reads = " ".join(
        f"{html_mod.escape(r['label'])}: the pick is {html_mod.escape(r['is_read'])} on in-sample average return."
        for r in results
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Paul's high-water stop picks</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 24px; color: #0f172a; line-height: 1.45; }}
h1 {{ font-size: 1.4rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; border-radius: 10px; padding: 12px 14px; margin: 12px 0; }}
.banner {{ background: #fff7ed; border: 1px solid #fdba74; border-radius: 10px; padding: 12px 14px; margin: 12px 0; }}
code {{ font-size: 0.92em; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Paul's high-water stop picks vs each system's current exit</h1>
<p>Research only. Not gold. Not DailyRun. Out-of-sample is report-only.</p>
<div class="callout">
<h2>What you asked</h2>
<p>{html_mod.escape(ASK).replace(chr(10), "<br>")}</p>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN)}</p>
</div>
<div class="banner">
<p><strong>Selection bias.</strong> Paul picked these activation percents and keep fractions after seeing the activation grid in <code>hwm_stop_activate_at_n_20261015</code>. That choice is in-sample selection on the same history. This page does not retune the picks, and it does not pick a winner from out-of-sample.</p>
<p><strong>Control</strong> is each system's current closed book (<code>Drive/{{SYSTEM}}_LatestRun_Closed.csv</code>) and the exit that book already used. Entries are not rerun. Positions are not resized. Rocket Launcher's control is that closed book, not the named partial exit (sell 80% at +20%, leftover stop at the entry price, leftover sold at +40%).</p>
<p><strong>The rule.</strong> The overlay stays off until a prior day's high-water mark is at least the activation percent above entry. Until then the original stop and the original exit stay. Once on, stop = entry + keep × (high-water mark − entry). The stop never loosens below the original stop. A stop price of zero or below counts as no original stop. Day T uses the high through day T−1. A new high raises the next day's stop, not today's. An open through the stop sells at the open. A low at or below the stop sells at the stop. The entry day cannot activate the overlay and cannot sell.</p>
<p><strong>Live versus this test.</strong> Live, if price makes a new high before touching the stop, the stop rises. The daily bars cannot see inside the day, so this test lets a new high change the following day's stop only. It does not switch to an intraday ratchet.</p>
<p><strong>Samples.</strong> In-sample means entry_date before 2024-01-01. Out-of-sample means entry_date on or after 2024-01-01. Full book, in-sample, and out-of-sample are all shown. The better / flat / worse line uses in-sample average return only.</p>
<p>The first mention of annualized rate of return is this sentence. After that, Ann ROR is the house formula <code>((1 + total profit / (slot cash × N)) ^ (365 / average days held) − 1) × 100</code> via <code>compare_format.ann_ror_from_closed</code>. Max drawdown and Sharpe use exit-date equity seeded at $500,000, the same series, because the overlay has no daily equity curve. Calmar is Ann ROR divided by the absolute value of max drawdown when both exist.</p>
<p>{reads}</p>
</div>
<p>Click column headers to sort.</p>
{_verdict_table(results)}
{_wide(results, "FULL", "Full book")}
{_wide(results, "IS", "In-sample (entry before 2024-01-01)")}
{_wide(results, "OOS", "Out-of-sample (entry on or after 2024-01-01) — report only")}
{_coverage(results)}
{_exit_table(results)}
{_missing_table()}
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""


def _pct_txt(v: Any) -> str:
    if v is None or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
        return "not computed"
    return f"{float(v):.2f}%"


def write_baseline(results: list[dict[str, Any]]) -> None:
    lines = [
        "# Paul's high-water stop picks — 2026-10-15",
        "",
        "Research only. Not gold. Not DailyRun. No knob was chosen from out-of-sample.",
        "",
        "## What you asked",
        "",
        "> give me a side by side compare of each system with the control and with my picks for the activation / keep. i want to see all the metrics",
        "> BRT 6% keep 70%",
        "> RL 6% keep 80%",
        "> YH 2% keep 70%",
        "> MTS 4% keep 60%",
        "> WPBR 2% keep 80%",
        "> RS 10% keep 80%",
        "> RSI 6% keep 80%",
        "",
        "## In plain English",
        "",
        PLAIN,
        "",
        "## Freeze",
        "",
        "- Control = each system's current closed book (`Drive/{SYSTEM}_LatestRun_Closed.csv`) and the exit that book already used.",
        "- Same walk as `tools/hwm_stop_activate_at_n_20261015.py` (loader from `tools/hwm_stop_keep_40_50_60_20261015.py`). Entries are not rerun. One threshold and one keep fraction per system.",
        "- Rocket Launcher (RL) control is that closed book, not the named partial exit strategy (80% at +20%, leftover stop at entry, leftover at +40%).",
        "- Overlay stays off until the prior-day high-water mark is at least the activation percent above entry. Until then the original stop and exit stay.",
        "- Once on: stop = entry + keep × (high-water mark − entry). Never loosen below the original stop. Stop price ≤ 0 counts as no original stop.",
        "- High-water mark = highest daily high since the fill, warehouse daily bars (`data/ohlcv.duckdb`). Not a 15-minute high.",
        "- No lookahead: day T uses the mark through T−1. A new high raises the next day's stop, not today's. Entry day cannot activate or sell.",
        "- Live note, stated on the page: if price makes a new high before touching the stop, the live stop rises. This test cannot see inside the daily bar, so it does not use an intraday ratchet.",
        "- Open through the stop fills at the open; else a low through the stop fills at the stop; else the original exit stands.",
        "- One position per closed trade. No resize. Same entries. N matches the control on every slice.",
        "- In-sample: entry_date < 2024-01-01. Out-of-sample: entry_date >= 2024-01-01. Full book reported too.",
        "- Judge: in-sample average return versus that system's control. Better if the pick is higher by at least 0.005 percentage points, worse if lower, flat if the printed two-decimal averages match. Out-of-sample did not pick the arm.",
        "- Annualized rate of return: `compare_format.ann_ror_from_closed`, days_per_year 365, on every arm and every slice. Slot cash = Closed median implied notional. Report capacity_brt_cash only when within 25% of that median. No flat $47,500 when the book is capacity-sized.",
        "- Max DD and Sharpe: exit-date equity, seed $500,000 (`DEFAULT_INITIAL_ACCOUNT`). Not a daily mark-to-market curve. Calmar = Ann ROR / abs(Max DD) when both exist.",
        "- Selection bias: Paul picked these cells after seeing the activation grid on this same history (`hwm_stop_activate_at_n_20261015`).",
        "- This overlay is not a Simple Moving Average (SMA) target.",
        "",
        "## Systems and in-sample read",
        "",
    ]
    for res in results:
        c_is = res["slices"]["IS"]["control"]
        p_is = res["slices"]["IS"]["pick"]
        c_f = res["slices"]["FULL"]["control"]
        p_f = res["slices"]["FULL"]["pick"]
        ann_bits = []
        for mode in ("FULL", "IS", "OOS"):
            for arm in ("control", "pick"):
                note = res["slices"][mode][arm].get("ann_note") or ""
                if note and res["slices"][mode][arm].get("ann_ror") is None:
                    ann_bits.append(f"{mode} {arm}: {note}")
        ann_txt = (" " + " ".join(ann_bits)) if ann_bits else ""
        lines.append(
            f"- **{res['label']}** — {res['pick_label']}. Slot {format_money(res['cash'])}. {res['cash_src']}. "
            f"Stop column `{res['stop_col']}`. Scored {res['n_full']:,} "
            f"(in-sample {res['n_is']:,}, out-of-sample {res['n_oos']:,}); "
            f"symbols {res['n_symbols']:,}; shorts left out {res['short_skipped']:,}; "
            f"no OHLC path {res['missing_ohlc']:,}; pick stop hits {res['hits']:,}. "
            f"Full-book average return { _pct_txt(c_f.get('avg_pnl_pct')) } control vs { _pct_txt(p_f.get('avg_pnl_pct')) } pick; "
            f"full-book annualized rate of return { _pct_txt(c_f.get('ann_ror')) } vs { _pct_txt(p_f.get('ann_ror')) }; "
            f"full-book win rate { _pct_txt(c_f.get('win_pct')) } vs { _pct_txt(p_f.get('win_pct')) }. "
            f"In-sample average return { _pct_txt(c_is.get('avg_pnl_pct')) } control vs { _pct_txt(p_is.get('avg_pnl_pct')) } pick; "
            f"in-sample annualized rate of return { _pct_txt(c_is.get('ann_ror')) } vs { _pct_txt(p_is.get('ann_ror')) }; "
            f"in-sample win rate { _pct_txt(c_is.get('win_pct')) } vs { _pct_txt(p_is.get('win_pct')) }. "
            f"On in-sample average return the pick is **{res['is_read']}**. "
            f"Out-of-sample was not used to change that read.{ann_txt}"
        )
    lines += [
        "",
        "## Not computed",
        "",
        "Days underwater, concurrent position counts, aggressive PnL, CES, and Paul / FIT scores need a daily equity curve or a rebuilt Summary. This page does not invent them. Total PnL $ and Sheet PnL $ stay off the HTML compare tables. Exit mix counts and percents are on the page.",
        "",
        "## Promotion",
        "",
        "Research only. Not gold. Not wired to DailyRun. Out-of-sample was not used to retune.",
        "",
    ]
    (OUT / "BASELINE.md").write_text("\n".join(lines), encoding="utf-8")


def _slim_metrics(m: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in m.items():
        if k == "exit_mix":
            out[k] = {str(a): int(b) for a, b in v.items()}
            continue
        if isinstance(v, (np.floating, np.integer)):
            v = v.item()
        if isinstance(v, float) and not math.isfinite(v):
            v = None
        out[k] = v
    return out


def main() -> int:
    act = _load_act()
    act._self_test_walk()
    OUT.mkdir(parents=True, exist_ok=True)
    results = [run_one(act, code, label, hurdle, keep) for code, label, hurdle, keep in PICKS]
    html = render(results)
    if html.count("<script") != 1:
        raise RuntimeError(f"expected one script tag, found {html.count('<script')}")
    (OUT / "compare.html").write_text(html, encoding="utf-8")
    write_baseline(results)
    slim = []
    for res in results:
        slim.append(
            {
                "code": res["code"],
                "label": res["label"],
                "pick": res["pick_label"],
                "cash": res["cash"],
                "cash_src": res["cash_src"],
                "is_read": res["is_read"],
                "n": {"FULL": res["n_full"], "IS": res["n_is"], "OOS": res["n_oos"]},
                "hits": res["hits"],
                "slices": {
                    mode: {arm: _slim_metrics(res["slices"][mode][arm]) for arm in ("control", "pick")}
                    for mode in ("FULL", "IS", "OOS")
                },
            }
        )
    (OUT / "summary.json").write_text(json.dumps(slim, indent=2), encoding="utf-8")
    print(f"wrote {OUT / 'compare.html'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
