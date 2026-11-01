#!/usr/bin/env python3
"""MUD hedge question: gap-skip both sleeves vs gap-skip longs only.

Research only. Not gold. Not DailyRun.
The prior compare page nested the sort script inside a second script tag, so
clicks never bound. This page emits SORTABLE_TABLE_SCRIPT once, unwrapped.
"""
from __future__ import annotations

import html as html_mod
import math
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
_PE = _REPO / "drive" / "paul_experiments"
for _p in (_PE, _REPO / "tools", _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    format_money,
)
from mud_gap_and_day1_exit_ab import _blend, _metrics, _take  # noqa: E402
from mud_tail_price_path import FULL_CSV, _attach_path, _load_closed  # noqa: E402
from report_page_extras import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)

STAMP = _PE / "mud_gap_skip_longs_vs_both_20261008"
IS_CUT = np.datetime64("2024-01-01")

ASK = (
    "this was meant to be a hedge system, where we are shorting stocks in addition "
    "to longs so we offset any bad times in the market, but it appears we would be "
    "better off just focusing on the longs and skipping those that gapped up. can you "
    "show me a comparison of longs + shorts skipping gaps (in both directions) vs. "
    "just longs while skipping gap ups? I would like to see the results including max DD. "
    "Also throw in the results for gap skip + close location exit. reminder - headers "
    "should be sortable. they weren't on the last report"
)
PLAIN = (
    "Most Up / Most Down (MUD) was built as a hedge: buy the names that just fell "
    "the hardest and short the names that just rose the hardest, so a bad market "
    "might be offset by the shorts. This page keeps the full unfiltered book as the "
    "baseline, then compares two gap filters. One still trades both sides, but skips "
    "a long that opens above the signal close and a short that opens below it. The "
    "other trades only the longs that did not gap up, and holds no shorts. Annualized "
    "rate of return (Ann ROR) and maximum drawdown (Max DD) are shown for the full "
    "book, for entries before 2024, and for 2024 onward. A stacked rule also gets out "
    "at the entry-day close unless that close is in the favorable third of the day's range."
)

SORT_ARROW_CSS = """
.sort-ind { display:inline-block; width:0.9em; margin-left:4px; color:#94a3b8; font-size:10px; }
th.sort-asc .sort-ind::after { content:"\\25B2"; color:#4c1d95; }
th.sort-desc .sort-ind::after { content:"\\25BC"; color:#4c1d95; }
th.sortable-th { cursor: pointer; }
"""


def _f(v: Any, nd: int = 2) -> str:
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


def _year_rows(
    arm: str,
    pnl_d: np.ndarray,
    exit_dt: np.ndarray,
    mask: np.ndarray,
) -> list[dict[str, Any]]:
    """Calendar-year profit and within-year Max DD on exit-date equity."""
    dol = pnl_d[mask]
    ex = pd.to_datetime(exit_dt[mask])
    if len(dol) == 0:
        return []
    daily = pd.Series(dol).groupby(ex.normalize(), sort=True).sum()
    equity = float(DEFAULT_INITIAL_ACCOUNT)
    rows = []
    for year, grp in daily.groupby(daily.index.year):
        peak = equity
        worst = 0.0
        for p in grp.to_numpy():
            equity += float(p)
            if equity > peak:
                peak = equity
            if peak > 0:
                dd = (peak - equity) / peak * 100.0
                if dd > worst:
                    worst = dd
        rows.append(
            {
                "arm": arm,
                "year": int(year),
                "pnl_d": float(grp.sum()),
                "max_dd": worst,
                "n_exit_days": int(len(grp)),
            }
        )
    return rows


def main() -> None:
    STAMP.mkdir(parents=True, exist_ok=True)
    print("load unfiltered", flush=True)
    df = _attach_path(_load_closed(FULL_CSV))
    print(f"trades {len(df):,}", flush=True)

    long = df["SIDE"].to_numpy() == "long"
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
    early_pct = np.where(long, (ent_c / entry - 1.0) * 100.0, (entry / ent_c - 1.0) * 100.0)
    gap_keep = np.where(long, entry <= sig_c, entry >= sig_c) & ok & np.isfinite(sig_c)
    long_gap = long & gap_keep
    keep_loc = np.where(long, loc >= (2.0 / 3.0), loc <= (1.0 / 3.0)) & np.isfinite(loc)
    early_loc = ok & ~keep_loc
    od, op, odays, oclosed, use = _blend(
        early_loc, pnl_d0, pnl_pct0, days0, closed, opened, early_d, early_pct
    )
    none_early = np.zeros(len(df), dtype=bool)
    ones = np.ones(len(df), dtype=bool)

    arms = [
        ("Control both", "control", ones, pnl_d0, pnl_pct0, days0, closed, none_early),
        ("Gap skip both", "hedge", gap_keep, pnl_d0, pnl_pct0, days0, closed, none_early),
        ("Gap skip longs only", "longs", long_gap, pnl_d0, pnl_pct0, days0, closed, none_early),
        ("Gap skip both + close location", "stack", gap_keep, od, op, odays, oclosed, use),
        ("Gap skip longs + close location", "stack_long", long_gap, od, op, odays, oclosed, use),
    ]

    slice_masks = {"FULL": ones, "IS": is_m, "OOS": ~is_m}
    rows: list[dict[str, Any]] = []
    print("scoring", flush=True)
    for name, kind, mask, dol, pct, dys, ex, ear in arms:
        for sl, sm in slice_masks.items():
            m = mask & sm
            p, d, dy, e, ea, ntl, sym = _take(m, pct, dol, dys, ex, ear, notional, symbols)
            met = _metrics(p, d, dy, e, ntl, sym, ea)
            met.update({"arm": name, "kind": kind, "slice": sl})
            rows.append(met)
            print(f"  {name} {sl} n={met['n']:,} ann={met['ann']:.2f} dd={met['max_dd']:.2f}", flush=True)

    by = {(r["arm"], r["slice"]): r for r in rows}

    def delta(arm: str, sl: str, key: str) -> float:
        a = by[(arm, sl)][key]
        c = by[("Control both", sl)][key]
        try:
            af, cf = float(a), float(c)
        except (TypeError, ValueError):
            return float("nan")
        if not (math.isfinite(af) and math.isfinite(cf)):
            return float("nan")
        return af - cf

    for r in rows:
        r["d_n"] = delta(r["arm"], r["slice"], "n")
        r["d_win"] = delta(r["arm"], r["slice"], "win_pct")
        r["d_avg"] = delta(r["arm"], r["slice"], "avg_pct")
        r["d_ann"] = delta(r["arm"], r["slice"], "ann")
        r["d_dd"] = delta(r["arm"], r["slice"], "max_dd")
        r["d_pf"] = delta(r["arm"], r["slice"], "pf")
        r["d_wo"] = delta(r["arm"], r["slice"], "avg_wo_max")
        r["d_exp"] = delta(r["arm"], r["slice"], "expect_d")
        r["d_calmar"] = delta(r["arm"], r["slice"], "calmar")
        r["d_sharpe"] = delta(r["arm"], r["slice"], "sharpe")

    year_rows: list[dict[str, Any]] = []
    for name, kind, mask, dol, pct, dys, ex, ear in arms:
        if kind == "stack_long":
            continue
        year_rows.extend(_year_rows(name, dol, ex, mask))
    pd.DataFrame(rows).to_csv(STAMP / "scores.csv", index=False)
    pd.DataFrame(year_rows).to_csv(STAMP / "year_drawdowns.csv", index=False)

    both_dd = by[("Gap skip both", "FULL")]["max_dd"]
    long_dd = by[("Gap skip longs only", "FULL")]["max_dd"]
    shorts_cut_dd = long_dd - both_dd  # positive => shorts lowered Max DD vs longs-only
    y2022 = {r["arm"]: r for r in year_rows if r["year"] == 2022}

    def yline(arm: str) -> str:
        r = y2022.get(arm)
        if not r:
            return f"{arm}: no 2022 exits"
        return (
            f"{arm}: 2022 PnL {format_money(r['pnl_d'])}, "
            f"within-year Max DD {r['max_dd']:.1f}%"
        )

    if shorts_cut_dd > 0.5:
        hedge_sentence = (
            f"On the full book, shorts in the gap-skip hedge do reduce Max DD versus "
            f"longs only: {both_dd:.1f}% with both sleeves versus {long_dd:.1f}% for longs only "
            f"({shorts_cut_dd:.1f} percentage points lower)."
        )
    elif shorts_cut_dd < -0.5:
        hedge_sentence = (
            f"On the full book, adding the gap-skip shorts does not reduce Max DD. "
            f"Longs only are at {long_dd:.1f}% Max DD and both sleeves are at {both_dd:.1f}% "
            f"({abs(shorts_cut_dd):.1f} percentage points higher with the shorts)."
        )
    else:
        hedge_sentence = (
            f"On the full book, Max DD is about the same: both sleeves {both_dd:.1f}% "
            f"versus longs only {long_dd:.1f}%."
        )
    hedge_sentence += " " + " ".join(yline(a) for a in ("Control both", "Gap skip both", "Gap skip longs only")) + "."

    def cell(r: dict[str, Any], key: str, nd: int = 2) -> str:
        return _f(r.get(key), nd)

    head_cols = [
        ("Arm", "arm", "text"),
        ("Slice", "slice", "text"),
        ("N", "n", "num"),
        ("dN vs control", "d_n", "num"),
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
        ("Calmar", "calmar", "num"),
        ("Avg days", "avg_days", "num"),
    ]
    extra_cols = [
        ("Arm", "arm", "text"),
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
        ("Sharpe", "sharpe", "num"),
        ("dSharpe", "d_sharpe", "num"),
        ("dCalmar", "d_calmar", "num"),
        ("Profit per capital day", "ppcd", "money"),
        ("Capital days", "capital_days", "num"),
        ("Median days held", "med_days", "num"),
        ("P90 days held", "p90_days", "num"),
        ("Losing streak", "losing_streak", "num"),
        ("Pct PnL max symbol", "pct_max_symbol", "num"),
        ("Pct PnL max trade", "pct_max_trade", "num"),
        ("Pct PnL top10", "pct_top10", "num"),
        ("Pct PnL bottom10", "pct_bot10", "num"),
        ("Day-1 exits %", "pct_day1_exit", "num"),
    ]
    year_cols = [
        ("Arm", "arm", "text"),
        ("Year", "year", "num"),
        ("Year PnL $", "pnl_d", "money"),
        ("Within-year Max DD %", "max_dd", "num"),
        ("Exit days", "n_exit_days", "num"),
    ]

    def table(records: list[dict[str, Any]], cols: list[tuple[str, str, str]]) -> str:
        th = "".join(_th(lab, "text" if kind == "text" else "num") for lab, _k, kind in cols)
        body = []
        for r in records:
            tds = []
            for _lab, key, kind in cols:
                if kind == "text":
                    tds.append(f"<td>{html_mod.escape(str(r.get(key, '')))}</td>")
                elif kind == "money":
                    tds.append(f"<td>{html_mod.escape(format_money(r.get(key)))}</td>")
                elif key in ("n", "d_n", "wins", "losses", "losing_streak", "year", "n_exit_days"):
                    v = r.get(key)
                    try:
                        tds.append(f"<td>{int(round(float(v))):,}</td>")
                    except (TypeError, ValueError):
                        tds.append("<td></td>")
                else:
                    nd = 3 if key in ("avg_pct", "d_avg", "avg_wo_max", "d_wo", "expect_pct", "avg_win", "avg_loss") else 2
                    tds.append(f"<td>{cell(r, key, nd)}</td>")
            body.append("<tr>" + "".join(tds) + "</tr>")
        return (
            '<div class="table-wrap"><table class="sortable"><thead><tr>'
            + th
            + "</tr></thead><tbody>"
            + "".join(body)
            + "</tbody></table></div>"
        )

    # SORTABLE_TABLE_SCRIPT already contains <script>...</script>. Do not wrap it again.
    # The last report did, and the inner tag closed the script before the click handler.
    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>MUD gap skip: both sleeves vs longs only</title>
<style>
body {{ font-family: Georgia, serif; margin: 24px; color: #1a1a1a; line-height: 1.45; }}
h1 {{ font-size: 1.55rem; }}
h2 {{ font-size: 1.15rem; margin-top: 1.5rem; }}
.callout {{ background: #f4f1ea; border-left: 4px solid #8a6a3b; padding: 12px 14px; margin: 12px 0 18px; }}
.note {{ color: #444; font-size: 0.95rem; }}
code {{ font-family: Consolas, monospace; font-size: 0.9em; }}
{SORTABLE_TH_CSS}
{SORT_ARROW_CSS}
</style>
</head><body>
<h1>MUD gap skip: both sleeves vs longs only</h1>
<p class="note">Most Up / Most Down (MUD), lookback 5 trading days, rebalance 1. Unfiltered book. Research only. Not gold. Not DailyRun.</p>
<div class="callout">
<h2 style="margin-top:0">What you asked</h2>
<p>{html_mod.escape(ASK)}</p>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN)}</p>
</div>
{SWIPE_NOTE_HTML}
<p class="note">Click a column header to sort. Press Enter or Space on a header to sort too. In-sample (IS) is entry before 2024-01-01. Out-of-sample (OOS) is entry on or after that date and is report-only. Annualized rate of return (Ann ROR) uses slot cash equal to the average entry notional of that arm and slice. Maximum drawdown (Max DD) replays closed-trade dollars by exit date from a {format_money(DEFAULT_INITIAL_ACCOUNT)} starting account. A lower Max DD is better, so a negative dMax DD versus control is an improvement. Sharpe is exit-date equity, risk-free rate 0, annualized by how often exits occur. Days underwater, open position counts, industry concentration, and Paul / FIT scores are not computed: this overlay has no daily equity curve and no symbol scorecard.</p>

<h2>Do the shorts hedge?</h2>
<p>{html_mod.escape(hedge_sentence)}</p>
<p class="note">Within-year Max DD starts from equity at the first exit of that year and tracks the peak only inside the year. It is not the full-sample Max DD. Year profit is the sum of closed-trade dollars whose exit date falls in that year.</p>

<h2>Headline</h2>
<p class="note">Deltas are versus Control both on the same slice. Gap skip longs + close location is the same close-location rule on the longs-only book. The primary comparison is Gap skip both versus Gap skip longs only.</p>
{table(rows, head_cols)}

<h2>More book metrics</h2>
{table(rows, extra_cols)}

<h2>Calendar years</h2>
<p class="note">Control, gap-skip both, gap-skip longs only, and gap-skip both plus the close-location exit. Click Year or Within-year Max DD to sort.</p>
{table(year_rows, year_cols)}

<h2>Rules</h2>
<ul>
<li><strong>Control both.</strong> Every unfiltered long and short. Exit at the next session open.</li>
<li><strong>Gap skip both.</strong> Skip a long whose entry open is above the signal close. Skip a short whose entry open is below the signal close. A flat open stays in.</li>
<li><strong>Gap skip longs only.</strong> No shorts. Keep a long only when the entry open is at or below the signal close.</li>
<li><strong>Close location, stacked on gap skip.</strong> After the gap filter, hold overnight only if the entry-day close is in the favorable third of that day's high-low range. Long: (close-low)/(high-low) at least 2/3. Short: that ratio at most 1/3. A zero range exits at the close. Same-day exits count as 1 calendar day so Ann ROR is defined.</li>
</ul>
<p class="note">The last compare page put the sort script inside a second script tag, so the browser stopped before the click handler. This page includes that script once.</p>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    html_path = STAMP / "compare.html"
    html_path.write_text(html, encoding="utf-8")
    (STAMP / "BASELINE.md").write_text(
        "\n".join([
            "# MUD gap skip: both sleeves vs longs only",
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
            "## Hedge",
            "",
            hedge_sentence,
            "",
            "Sort script is included once. The prior page nested it inside another script tag.",
            "Max DD seed: house default initial account. Slot cash: mean ENTRY_NOTIONAL of the arm and slice.",
            "OOS is report-only.",
            "",
        ]),
        encoding="utf-8",
    )
    text = html_path.read_text(encoding="utf-8")
    n_script_open = text.count("<script>")
    n_script_close = text.count("</script>")
    n_tables = text.count('<table class="sortable">')
    th_tags = re.findall(r"<th\b[^>]*>", text)
    n_th = len(th_tags)
    n_sth = sum(1 for t in th_tags if "sortable-th" in t)
    has_click = "document.addEventListener(\"click\"" in text
    has_key = 'e.key !== "Enter"' in text
    print(
        f"verify scripts {n_script_open}/{n_script_close} tables {n_tables} "
        f"th {n_th} sortable-th {n_sth} click {has_click} key {has_key}",
        flush=True,
    )
    if n_script_open != 1 or n_script_close != 1 or n_tables < 1 or n_th != n_sth or not has_click or not has_key:
        raise SystemExit("sortable header check failed")
    print("wrote " + str(html_path), flush=True)
    print(hedge_sentence.encode("ascii", "replace").decode("ascii"), flush=True)


if __name__ == "__main__":
    main()
