#!/usr/bin/env python3
"""MUD L5_R1: open-gap skip, day-1 percent exits, close-location exit vs control.

Research only. Not gold. Not DailyRun. Out-of-sample is report-only.
Control is the unfiltered Most Up / Most Down book (lookback 5, rebalance 1).
"""
from __future__ import annotations

import html as html_mod
import math
import sys
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
_PE = _REPO / "drive" / "paul_experiments"
for _p in (_PE, _REPO / "tools", _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from compare_format import (  # noqa: E402
    ann_ror_from_closed,
    format_money,
    max_dd_pct_from_closed_pnl_by_date,
    sharpe_from_closed_pnl_by_date,
)
from mud_tail_price_path import FULL_CSV, _attach_path, _load_closed  # noqa: E402
from report_page_extras import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)

STAMP = _PE / "mud_gap_day1_exit_ab_20261007"
IS_CUT = np.datetime64("2024-01-01")

ASK = (
    "i think that is a good start. let's see what the results are of removing "
    "the positive gap ups for longs and the negative gap down for shorts. can we "
    "also try getting rid of a stock that doesn't go up a certain percent by the "
    "end of the first day, and another that gets rid of a stock that does what, "
    "you make the next suggestion and then run some comparisons please"
)
PLAIN = (
    "Most Up / Most Down (MUD) buys yesterday's biggest losers and shorts "
    "yesterday's biggest winners, filling at the next open and getting out at "
    "the open after that. The last look showed the big winners reverse during "
    "the entry day, while most other trades do not. This page compares the full "
    "unfiltered book with three ideas: skip opens that have already reversed, "
    "sell at the entry-day close unless the favorable move has reached 0%, 1%, "
    "or 2%, and a suggested rule that only holds overnight when the close is in "
    "the favorable third of that day's range. Annualized rate of return (Ann ROR) "
    "uses the house formula. Out-of-sample numbers are shown and not used to pick a rule."
)


def _f(v: Any, nd: int = 2) -> str:
    if v is None:
        return ""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(x):
        return ""
    return f"{x:,.{nd}f}"


def _th(label: str, typ: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{typ}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _losing_streak(pnl_d: np.ndarray, exit_dt: np.ndarray) -> int:
    if len(pnl_d) == 0:
        return 0
    order = np.argsort(exit_dt, kind="mergesort")
    loss = pnl_d[order] < 0
    best = cur = 0
    for flag in loss:
        if flag:
            cur += 1
            if cur > best:
                best = cur
        else:
            cur = 0
    return int(best)


def _share(part: float, total: float) -> float:
    if not math.isfinite(total) or abs(total) < 1e-9:
        return float("nan")
    return part / total * 100.0


def _metrics(
    pnl_pct: np.ndarray,
    pnl_d: np.ndarray,
    days: np.ndarray,
    exit_dt: np.ndarray,
    notional: np.ndarray,
    symbols: np.ndarray,
    early: np.ndarray,
) -> dict[str, Any]:
    n = int(len(pnl_pct))
    empty = {k: float("nan") for k in (
        "n", "wins", "losses", "win_pct", "avg_pct", "avg_wo_max",
        "expect_d", "expect_pct", "avg_win", "avg_loss", "wl_count", "wl_dollars",
        "pf", "ann", "max_dd", "calmar", "sharpe", "ppcd", "capital_days",
        "avg_days", "med_days", "p90_days", "losing_streak",
        "pct_max_symbol", "pct_max_trade", "pct_top10", "pct_bot10",
        "pct_day1_exit",
    )}
    empty["n"] = n
    if n == 0:
        return empty
    wins_m = pnl_d > 0
    loss_m = pnl_d < 0
    n_win = int(wins_m.sum())
    n_loss = int(loss_m.sum())
    win_d = float(pnl_d[wins_m].sum()) if n_win else 0.0
    loss_d = float(pnl_d[loss_m].sum()) if n_loss else 0.0
    total = float(pnl_d.sum())
    days_ok = days[np.isfinite(days) & (days > 0)]
    avg_days = float(days_ok.mean()) if len(days_ok) else float("nan")
    cash = float(np.nanmean(notional)) if np.isfinite(notional).any() else float("nan")
    ann = ann_ror_from_closed(
        total_pnl=total,
        n_trades=n,
        avg_days_held=avg_days if math.isfinite(avg_days) else 0.0,
        brt_cash=cash if math.isfinite(cash) else 0.0,
    )
    # Dated Max DD / Sharpe on exit-date dollars (not a daily mark-to-market curve).
    g = pd.Series(pnl_d, copy=False).groupby(pd.to_datetime(exit_dt).normalize(), sort=False).sum()
    dated = list(zip(g.index.date, (float(v) for v in g.to_numpy())))
    max_dd = max_dd_pct_from_closed_pnl_by_date(dated)
    sharpe = sharpe_from_closed_pnl_by_date(dated)
    dd_f = float(max_dd) if max_dd is not None else float("nan")
    ann_f = float(ann) if ann is not None else float("nan")
    calmar = ann_f / abs(dd_f) if math.isfinite(ann_f) and math.isfinite(dd_f) and abs(dd_f) > 1e-9 else float("nan")
    cap_days = float(days_ok.sum()) if len(days_ok) else 0.0
    wo = pnl_pct
    if n > 1:
        wo = np.delete(pnl_pct, int(np.nanargmax(pnl_pct)))
    k = max(1, int(round(0.10 * n)))
    if n > k:
        top = float(np.partition(pnl_d, -k)[-k:].sum())
        bot = float(np.partition(pnl_d, k - 1)[:k].sum())
    else:
        top = total
        bot = total
    by_sym = pd.Series(pnl_d, copy=False).groupby(symbols, sort=False).sum()
    max_sym = float(by_sym.max()) if len(by_sym) else float("nan")
    max_trade = float(np.nanmax(pnl_d))
    pf = win_d / abs(loss_d) if n_loss and abs(loss_d) > 0 else float("nan")
    return {
        "n": n,
        "wins": n_win,
        "losses": n_loss,
        "win_pct": n_win / n * 100.0,
        "avg_pct": float(np.nanmean(pnl_pct)),
        "avg_wo_max": float(np.nanmean(wo)),
        "expect_d": total / n,
        "expect_pct": float(np.nanmean(pnl_pct)),
        "avg_win": float(pnl_pct[wins_m].mean()) if n_win else float("nan"),
        "avg_loss": float(pnl_pct[loss_m].mean()) if n_loss else float("nan"),
        "wl_count": (n_win / n_loss) if n_loss else float("nan"),
        "wl_dollars": (win_d / abs(loss_d)) if n_loss and abs(loss_d) > 0 else float("nan"),
        "pf": pf,
        "ann": ann_f,
        "max_dd": dd_f,
        "calmar": calmar,
        "sharpe": float(sharpe) if sharpe is not None else float("nan"),
        "ppcd": (total / cap_days) if cap_days else float("nan"),
        "capital_days": cap_days,
        "avg_days": avg_days,
        "med_days": float(np.median(days_ok)) if len(days_ok) else float("nan"),
        "p90_days": float(np.quantile(days_ok, 0.9)) if len(days_ok) else float("nan"),
        "losing_streak": _losing_streak(pnl_d, exit_dt),
        "pct_max_symbol": _share(max_sym, total),
        "pct_max_trade": _share(max_trade, total),
        "pct_top10": _share(top, total),
        "pct_bot10": _share(bot, total),
        "pct_day1_exit": float(early.mean() * 100.0) if len(early) else float("nan"),
    }


def _take(mask: np.ndarray, *arrs: np.ndarray) -> tuple[np.ndarray, ...]:
    return tuple(a[mask] for a in arrs)


def _blend(
    early: np.ndarray,
    pnl_d: np.ndarray,
    pnl_pct: np.ndarray,
    days: np.ndarray,
    closed: np.ndarray,
    opened: np.ndarray,
    early_d: np.ndarray,
    early_pct: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    use = early & np.isfinite(early_d) & np.isfinite(early_pct)
    out_d = np.where(use, early_d, pnl_d)
    out_pct = np.where(use, early_pct, pnl_pct)
    out_days = np.where(use, 1.0, days)
    out_closed = np.where(use, opened, closed)
    return out_d, out_pct, out_days, out_closed, use


def main() -> None:
    STAMP.mkdir(parents=True, exist_ok=True)
    print("load unfiltered", flush=True)
    df = _attach_path(_load_closed(FULL_CSV))
    print(f"trades {len(df):,} path {df['path_ok'].mean()*100:.1f}%", flush=True)

    long = (df["SIDE"].to_numpy() == "long")
    opened = df["DATE_OPENED"].to_numpy(dtype="datetime64[ns]")
    closed = df["DATE_CLOSED"].to_numpy(dtype="datetime64[ns]")
    is_m = opened < IS_CUT
    entry = df["ENTRY_PRICE"].to_numpy(dtype=float)
    sig_c = df["sig_c"].to_numpy(dtype=float)
    ent_c = df["ent_c"].to_numpy(dtype=float)
    sh = df["SHARES"].to_numpy(dtype=float)
    pnl_d0 = df["PNL_DOLLARS"].to_numpy(dtype=float)
    pnl_pct0 = df["PNL_PCT"].to_numpy(dtype=float)
    days0 = df["DAYS_HELD"].to_numpy(dtype=float)
    notional = df["ENTRY_NOTIONAL"].to_numpy(dtype=float)
    symbols = df["SYMBOL"].to_numpy()
    loc = df["close_loc"].to_numpy(dtype=float)
    ok = df["path_ok"].to_numpy()

    early_d = np.where(long, sh * (ent_c - entry), sh * (entry - ent_c))
    early_pct = np.where(
        long,
        (ent_c / entry - 1.0) * 100.0,
        (entry / ent_c - 1.0) * 100.0,
    )
    # Favorable percent at the entry-day close. Same definition as the exit PnL.
    fav = early_pct.copy()

    gap_keep = np.where(long, entry <= sig_c, entry >= sig_c) & ok & np.isfinite(sig_c)
    none_early = np.zeros(len(df), dtype=bool)

    arms: list[tuple[str, str, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = []
    # name, kind, mask, pnl_d, pnl_pct, days, exit_dt, early_flag  (mask indexes the full book)
    arms.append(("Control", "control", np.ones(len(df), dtype=bool), pnl_d0, pnl_pct0, days0, closed, none_early))

    arms.append((
        "Open gap skip",
        "entry",
        gap_keep,
        pnl_d0,
        pnl_pct0,
        days0,
        closed,
        none_early,
    ))

    for thr in (0.0, 1.0, 2.0):
        early = ok & np.isfinite(fav) & (fav < thr)
        od, op, odays, oclosed, use = _blend(early, pnl_d0, pnl_pct0, days0, closed, opened, early_d, early_pct)
        label = f"Day-1 exit under {thr:.0f}%"
        arms.append((label, "exit", np.ones(len(df), dtype=bool), od, op, odays, oclosed, use))

    keep_loc = np.where(long, loc >= (2.0 / 3.0), loc <= (1.0 / 3.0))
    keep_loc = keep_loc & np.isfinite(loc)
    early_loc = ok & ~keep_loc
    od, op, odays, oclosed, use = _blend(early_loc, pnl_d0, pnl_pct0, days0, closed, opened, early_d, early_pct)
    arms.append((
        "Close-location exit",
        "exit",
        np.ones(len(df), dtype=bool),
        od,
        op,
        odays,
        oclosed,
        use,
    ))

    # Second look only: gap skip, then close-location on the trades still taken.
    od, op, odays, oclosed, use = _blend(early_loc, pnl_d0, pnl_pct0, days0, closed, opened, early_d, early_pct)
    stack = ("Gap skip + close-location", "stack", gap_keep, od, op, odays, oclosed, use)

    rows: list[dict[str, Any]] = []
    sleeve_masks = {
        "Both": np.ones(len(df), dtype=bool),
        "Long": long,
        "Short": ~long,
    }
    slice_masks = {
        "FULL": np.ones(len(df), dtype=bool),
        "IS": is_m,
        "OOS": ~is_m,
    }

    def score_arm(arm_tuple: tuple, sleeve: str, sl: str) -> dict[str, Any]:
        name, kind, mask, od, op, odays, oclosed, use = arm_tuple
        m = mask & sleeve_masks[sleeve] & slice_masks[sl]
        pct, dol, dys, ex, ear, ntl, sym = _take(m, op, od, odays, oclosed, use, notional, symbols)
        met = _metrics(pct, dol, dys, ex, ntl, sym, ear)
        met["arm"] = name
        met["kind"] = kind
        met["sleeve"] = sleeve
        met["slice"] = sl
        return met

    print("scoring", flush=True)
    for arm in arms:
        for sleeve in ("Both", "Long", "Short"):
            for sl in ("FULL", "IS", "OOS"):
                rows.append(score_arm(arm, sleeve, sl))
                print(f"  {arm[0]} {sleeve} {sl} n={rows[-1]['n']:,} ann={rows[-1]['ann']:.2f}", flush=True)

    foot = []
    for sleeve in ("Both", "Long", "Short"):
        for sl in ("FULL", "IS", "OOS"):
            foot.append(score_arm(stack, sleeve, sl))

    by_key = {(r["arm"], r["sleeve"], r["slice"]): r for r in rows}

    def delta(arm: str, sleeve: str, sl: str, key: str) -> float:
        a = by_key[(arm, sleeve, sl)][key]
        c = by_key[("Control", sleeve, sl)][key]
        if isinstance(a, (int, np.integer)) and isinstance(c, (int, np.integer)):
            return float(a - c)
        try:
            af, cf = float(a), float(c)
        except (TypeError, ValueError):
            return float("nan")
        if not (math.isfinite(af) and math.isfinite(cf)):
            return float("nan")
        return af - cf

    for r in rows:
        r["d_n"] = delta(r["arm"], r["sleeve"], r["slice"], "n")
        r["d_win"] = delta(r["arm"], r["sleeve"], r["slice"], "win_pct")
        r["d_avg"] = delta(r["arm"], r["sleeve"], r["slice"], "avg_pct")
        r["d_ann"] = delta(r["arm"], r["sleeve"], r["slice"], "ann")
        r["d_dd"] = delta(r["arm"], r["sleeve"], r["slice"], "max_dd")
        r["d_pf"] = delta(r["arm"], r["sleeve"], r["slice"], "pf")
        r["d_wo"] = delta(r["arm"], r["sleeve"], r["slice"], "avg_wo_max")
        r["d_exp"] = delta(r["arm"], r["sleeve"], r["slice"], "expect_d")
        r["d_calmar"] = delta(r["arm"], r["sleeve"], r["slice"], "calmar")
        r["d_sharpe"] = delta(r["arm"], r["sleeve"], r["slice"], "sharpe")

    # Lean among day-1 thresholds on IS combined quality only.
    day_names = ["Day-1 exit under 0%", "Day-1 exit under 1%", "Day-1 exit under 2%"]
    ctrl_is = by_key[("Control", "Both", "IS")]
    lean_name = day_names[0]
    lean_ann = -1e18
    for name in day_names:
        rec = by_key[(name, "Both", "IS")]
        if rec["n"] < 0.5 * ctrl_is["n"]:
            continue
        if rec["ann"] > lean_ann:
            lean_ann = rec["ann"]
            lean_name = name
    lean = by_key[(lean_name, "Both", "IS")]
    lean_oos = by_key[(lean_name, "Both", "OOS")]
    ctrl_oos = by_key[("Control", "Both", "OOS")]
    beats_is = lean["ann"] > ctrl_is["ann"] and lean["avg_pct"] > ctrl_is["avg_pct"]
    oos_agrees = lean_oos["ann"] > ctrl_oos["ann"] and lean_oos["avg_pct"] > ctrl_oos["avg_pct"]

    scores = pd.DataFrame(rows + foot)
    scores.to_csv(STAMP / "scores.csv", index=False)

    def cell(r: dict[str, Any], key: str, nd: int = 2) -> str:
        return _f(r.get(key), nd)

    head_cols = [
        ("Arm", "arm", "text"),
        ("Sleeve", "sleeve", "text"),
        ("Slice", "slice", "text"),
        ("N", "n", "num"),
        ("dN", "d_n", "num"),
        ("Win %", "win_pct", "num"),
        ("dWin pp", "d_win", "num"),
        ("Avg PnL %", "avg_pct", "num"),
        ("dAvg pp", "d_avg", "num"),
        ("Ann ROR %", "ann", "num"),
        ("dAnn ROR pp", "d_ann", "num"),
        ("Max DD %", "max_dd", "num"),
        ("dMax DD pp", "d_dd", "num"),
        ("Profit factor", "pf", "num"),
        ("dPF", "d_pf", "num"),
        ("Day-1 exits %", "pct_day1_exit", "num"),
        ("Avg days", "avg_days", "num"),
    ]
    extra_cols = [
        ("Arm", "arm", "text"),
        ("Sleeve", "sleeve", "text"),
        ("Slice", "slice", "text"),
        ("Wins", "wins", "num"),
        ("Losses", "losses", "num"),
        ("Book AVG_PNL_PCT_WO_MAX", "avg_wo_max", "num"),
        ("d AVG_PNL_PCT_WO_MAX", "d_wo", "num"),
        ("Expectancy $", "expect_d", "money"),
        ("dExpectancy $", "d_exp", "money"),
        ("Expectancy %", "expect_pct", "num"),
        ("Avg win %", "avg_win", "num"),
        ("Avg loss %", "avg_loss", "num"),
        ("Win/Loss ratio (count)", "wl_count", "num"),
        ("Win/Loss ratio $", "wl_dollars", "num"),
        ("Calmar", "calmar", "num"),
        ("dCalmar", "d_calmar", "num"),
        ("Sharpe", "sharpe", "num"),
        ("dSharpe", "d_sharpe", "num"),
        ("Profit per capital day", "ppcd", "money"),
        ("Capital days", "capital_days", "num"),
        ("Median days held", "med_days", "num"),
        ("P90 days held", "p90_days", "num"),
        ("Losing streak", "losing_streak", "num"),
        ("Pct PnL max symbol", "pct_max_symbol", "num"),
        ("Pct PnL max trade", "pct_max_trade", "num"),
        ("Pct PnL top10", "pct_top10", "num"),
        ("Pct PnL bottom10", "pct_bot10", "num"),
    ]

    def table(records: list[dict[str, Any]], cols: list[tuple[str, str, str]]) -> str:
        th = "".join(_th(lab, "text" if kind == "text" else "num") for lab, _k, kind in cols)
        body = []
        for r in records:
            tds = []
            for lab, key, kind in cols:
                if kind == "text":
                    tds.append(f"<td>{html_mod.escape(str(r.get(key, '')))}</td>")
                elif kind == "money":
                    tds.append(f"<td>{html_mod.escape(format_money(r.get(key)))}</td>")
                elif key in ("n", "d_n", "wins", "losses", "losing_streak"):
                    v = r.get(key)
                    tds.append("<td></td>" if v is None or (isinstance(v, float) and not math.isfinite(v)) else f"<td>{int(round(float(v))):,}</td>")
                else:
                    nd = 3 if key in ("avg_pct", "d_avg", "avg_wo_max", "d_wo", "expect_pct", "avg_win", "avg_loss") else 2
                    tds.append(f"<td>{cell(r, key, nd)}</td>")
            body.append("<tr>" + "".join(tds) + "</tr>")
        return (
            SWIPE_NOTE_HTML
            + '<div class="table-wrap"><table class="sortable"><thead><tr>'
            + th
            + "</tr></thead><tbody>"
            + "".join(body)
            + "</tbody></table></div>"
        )

    def line(arm: str, sleeve: str) -> str:
        bits = []
        for sl in ("FULL", "IS", "OOS"):
            r = by_key[(arm, sleeve, sl)]
            bits.append(
                f"{sl} N={r['n']:,} WR={r['win_pct']:.1f}% avg={r['avg_pct']:.3f}% AnnROR={r['ann']:.1f}%"
            )
        return f"{arm} / {sleeve}: " + "; ".join(bits)

    summary_lines = []
    for sleeve in ("Both", "Long", "Short"):
        for arm, *_rest in arms:
            summary_lines.append(line(arm, sleeve))
    summary = " | ".join(summary_lines)

    gap_both = by_key[("Open gap skip", "Both", "FULL")]
    ctrl_both = by_key[("Control", "Both", "FULL")]
    if beats_is:
        lean_lead = (
            f"Among the three day-1 percent exits, the in-sample combined lean is {lean_name}, "
            f"and it beats the control on IS Ann ROR and average percent."
        )
    else:
        lean_lead = (
            f"None of the day-1 percent exits beat the control on in-sample combined "
            f"Ann ROR or average percent. If one must be named, the least-bad on IS Ann ROR "
            f"is {lean_name}. That is not a keep."
        )
    lean_sentence = (
        lean_lead
        + f" IS Ann ROR {lean['ann']:.1f}% vs control {ctrl_is['ann']:.1f}%, "
        f"IS win rate {lean['win_pct']:.1f}% vs {ctrl_is['win_pct']:.1f}%, "
        f"IS avg {lean['avg_pct']:.3f}% vs {ctrl_is['avg_pct']:.3f}%, "
        f"N {lean['n']:,} vs {ctrl_is['n']:,}. "
        f"Naming it uses in-sample quality only, so it is in-sample selection. "
        f"Out-of-sample for that same arm is Ann ROR {lean_oos['ann']:.1f}% vs control {ctrl_oos['ann']:.1f}% "
        f"and avg {lean_oos['avg_pct']:.3f}% vs {ctrl_oos['avg_pct']:.3f}%. "
        + (
            "OOS is higher than control on both Ann ROR and average percent. Still do not retune from OOS."
            if oos_agrees
            else "OOS does not beat control on both Ann ROR and average percent. Do not retune."
        )
    )

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>MUD gap skip and day-1 exits</title>
<style>
body {{ font-family: Georgia, serif; margin: 24px; color: #1a1a1a; line-height: 1.45; }}
h1 {{ font-size: 1.55rem; }}
h2 {{ font-size: 1.15rem; margin-top: 1.5rem; }}
.callout {{ background: #f4f1ea; border-left: 4px solid #8a6a3b; padding: 12px 14px; margin: 12px 0 18px; }}
.note {{ color: #444; font-size: 0.95rem; }}
code {{ font-family: Consolas, monospace; font-size: 0.9em; }}
{SORTABLE_TH_CSS}
</style>
</head><body>
<h1>MUD gap skip and first-day exits</h1>
<p class="note">Most Up / Most Down (MUD), lookback 5 trading days, rebalance 1. Unfiltered control. Research only. Not gold. Not DailyRun.</p>
<div class="callout">
<h2 style="margin-top:0">What you asked</h2>
<p>{html_mod.escape(ASK)}</p>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN)}</p>
</div>
<p class="note">Click column headers to sort. Swipe sideways to see more columns. In-sample (IS) is entry before 2024-01-01. Out-of-sample (OOS) is entry on or after that date and is report-only. Annualized rate of return (Ann ROR) uses slot cash equal to the average entry notional of that arm and slice. Deltas are versus the control on the same sleeve and slice. A lower Max DD is better, so a negative dMax DD is an improvement. Sharpe is exit-date equity, risk-free rate 0, annualized by how often exits occur, not a daily square-root-of-252 Sharpe. Days underwater, position counts, and Paul / FIT scores are not on this page because this overlay has no daily equity curve and no symbol scorecard.</p>

<h2>How to read the arms</h2>
<ul>
<li><strong>Open gap skip.</strong> Do not take a long whose entry open is above the signal close. Do not take a short whose entry open is below the signal close. A flat open stays in. This is knowable at the open.</li>
<li><strong>Day-1 exit under 0% / 1% / 2%.</strong> You are already filled. If the favorable move from the entry open to the entry-day close is below the threshold, sell or cover at that close. Otherwise keep the original exit at the next open. Long favorable move is close/open minus 1. Short favorable move is open/close minus 1. All three thresholds are pre-declared.</li>
<li><strong>Close-location exit (the suggestion).</strong> Winners in the earlier path look closed near the favorable extreme, not merely slightly green. Hold overnight only if the close is in the favorable third of that day's high-low range. Long: keep only if (close-low)/(high-low) is at least 2/3. Short: keep only if that ratio is at most 1/3. Otherwise exit at the close. A zero range exits at the close. One frozen rule, not a searched grid.</li>
</ul>
<p>{html_mod.escape(lean_sentence)}</p>
<p>Open gap skip on the combined book: full Ann ROR {gap_both['ann']:.1f}% vs control {ctrl_both['ann']:.1f}% (N {gap_both['n']:,} vs {ctrl_both['n']:,}). These comparisons are research only. They do not change DailyRun.</p>

<h2>Headline</h2>
<p class="note">Absolute values and deltas versus control. Combined, longs, and shorts. Full book, IS, and OOS.</p>
{table(rows, head_cols)}

<h2>More book metrics</h2>
<p class="note">Canonical compare fields that this closed-trade overlay can compute. Dollar fields use thousands separators and two decimals. Total profit dollars are left off this table on purpose.</p>
{table(rows, extra_cols)}

<h2>Second look, not the verdict</h2>
<p>Gap skip and the close-location exit stacked. This was not used to pick the day-1 lean. Still research only.</p>
{table(foot, head_cols)}

<h2>Freeze</h2>
<ul>
<li>Control: <code>drive/MUD_LatestRun_Closed.csv</code>, L5_R1, signal close, enter next open, exit next session open. No stop and no target. Average-minimum filter is not the control.</li>
<li>Prices for the signal close, entry-day close, and entry-day range: <code>data/ohlcv.duckdb</code> <code>prices</code>. Fills and original dollars stay on the Closed file.</li>
<li>Same-day exit uses 1 calendar day so Ann ROR is defined.</li>
<li>Day-1 lean, if named, is the best IS combined Ann ROR among 0%, 1%, and 2% with N still at least half of control. OOS did not choose it.</li>
</ul>
<script>
{SORTABLE_TABLE_SCRIPT}
</script>
</body></html>
"""
    (STAMP / "compare.html").write_text(html, encoding="utf-8")
    (STAMP / "BASELINE.md").write_text(
        "\n".join([
            "# MUD gap skip and day-1 exits",
            "",
            "Research only. Not gold. Not DailyRun.",
            "",
            "## What you asked",
            "",
            ASK,
            "",
            "## In plain English",
            "",
            PLAIN,
            "",
            "## Lean (IS combined only)",
            "",
            lean_sentence,
            "",
            "## Snapshot",
            "",
            summary,
            "",
            "Slot cash = mean ENTRY_NOTIONAL of that arm and slice.",
            "Sharpe = exit-date equity, rf=0, annualized by observed exit frequency.",
            "Second look (gap skip + close-location) is in scores.csv kind=stack and is not the verdict.",
            "",
        ]),
        encoding="utf-8",
    )
    print("LEAN " + lean_name, flush=True)
    print("wrote " + str(STAMP / "compare.html"), flush=True)


if __name__ == "__main__":
    main()
