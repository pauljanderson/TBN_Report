#!/usr/bin/env python3
"""One-knob filters on MUD gap-skip longs. Research only. Not gold. Not DailyRun.

Control N on the prior page is the full gap-skip long book (about 211k), not
the in-sample slice (about 175k). Thresholds that need a cut are fit on IS only.
"""
from __future__ import annotations

import html as html_mod
import math
import re
import sys
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
_PE = _REPO / "drive" / "paul_experiments"
for _p in (_PE, _REPO / "tools", _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from compare_format import DEFAULT_INITIAL_ACCOUNT, format_money  # noqa: E402
from mud_gap_and_day1_exit_ab import _metrics  # noqa: E402
from mud_tail_price_path import DB, FULL_CSV  # noqa: E402
from report_page_extras import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)

STAMP = _PE / "mud_gap_skip_longs_filters_20261008"
IS_CUT = np.datetime64("2024-01-01")
USECOLS = [
    "SYMBOL",
    "SIDE",
    "DATE_OPENED",
    "DATE_CLOSED",
    "SIGNAL_DATE",
    "ENTRY_PRICE",
    "PNL_PCT",
    "PNL_DOLLARS",
    "ENTRY_NOTIONAL",
    "DAYS_HELD",
    "LOOKBACK_RETURN_PCT",
    "RANK_PERCENTILE",
    "RSI14_AT_TRIGGER",
    "MARKET_CAP",
]

ASK = (
    "thanks. it looks like gap skip longs is the winner as it has a reasonable "
    "drawdown of 10% and the best Ann ROR. but there are also 174k trades over "
    "16 years. that's a lot. what other filters can we use in identifying which "
    "stocks to go long with to reduce trades, increase ann ROR and reduce DD?"
)
PLAIN = (
    "The book he liked is Most Up / Most Down (MUD) longs only, and only the "
    "ones that did not gap up at the open. The 174k figure is the in-sample "
    "count (entries before 2024). The full control is larger. This page tries "
    "five ways to take fewer of those longs: a more extreme rank, only the 10 "
    "or 20 worst names each day, a Relative Strength Index (RSI) at or below 30, "
    "the larger half by market cap, and a deeper 5-day drop. Annualized rate of "
    "return (Ann ROR) and maximum drawdown (Max DD) have to improve together "
    "with a smaller trade count. A filter that only cuts trades is not a keep. "
    "Out-of-sample results are shown and are not used to pick a winner."
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


def _load_longs() -> pd.DataFrame:
    df = pd.read_csv(FULL_CSV, usecols=USECOLS, low_memory=False)
    df = df[df["SIDE"].astype(str).str.lower() == "long"].copy()
    df["SYMBOL"] = df["SYMBOL"].astype(str).str.upper()
    for c in ("DATE_OPENED", "DATE_CLOSED", "SIGNAL_DATE"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    for c in (
        "ENTRY_PRICE",
        "PNL_PCT",
        "PNL_DOLLARS",
        "ENTRY_NOTIONAL",
        "DAYS_HELD",
        "LOOKBACK_RETURN_PCT",
        "RANK_PERCENTILE",
        "RSI14_AT_TRIGGER",
        "MARKET_CAP",
    ):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["SYMBOL", "DATE_OPENED", "SIGNAL_DATE", "PNL_PCT", "ENTRY_PRICE"])
    need = df[["SYMBOL", "SIGNAL_DATE"]].drop_duplicates()
    need = need.rename(columns={"SYMBOL": "symbol", "SIGNAL_DATE": "d"})
    need["d"] = need["d"].dt.normalize()
    print(f"long rows {len(df):,} signal keys {len(need):,}", flush=True)
    con = duckdb.connect(str(DB), read_only=True)
    con.register("need", need)
    px = con.execute(
        """
        SELECT upper(p.symbol) AS symbol, CAST(p.date AS DATE) AS d, p.close AS sig_c
        FROM prices p
        SEMI JOIN need n
          ON upper(p.symbol) = n.symbol AND CAST(p.date AS DATE) = n.d
        """
    ).fetchdf()
    con.close()
    px["d"] = pd.to_datetime(px["d"])
    px = px.drop_duplicates(["symbol", "d"])
    df["_sig"] = df["SIGNAL_DATE"].dt.normalize()
    df = df.merge(px, left_on=["SYMBOL", "_sig"], right_on=["symbol", "d"], how="left")
    df = df.drop(columns=["symbol", "d", "_sig"])
    ok = np.isfinite(df["sig_c"].to_numpy()) & (df["sig_c"].to_numpy() > 0)
    keep = ok & (df["ENTRY_PRICE"].to_numpy() <= df["sig_c"].to_numpy())
    out = df.loc[keep].copy()
    out["slice"] = np.where(out["DATE_OPENED"].to_numpy(dtype="datetime64[ns]") < IS_CUT, "IS", "OOS")
    print(f"gap-skip longs {len(out):,}", flush=True)
    return out


def _top_k(df: pd.DataFrame, k: int) -> pd.DataFrame:
    ordered = df.sort_values(
        ["DATE_OPENED", "LOOKBACK_RETURN_PCT", "RANK_PERCENTILE", "SYMBOL"],
        ascending=[True, True, True, True],
        na_position="last",
        kind="mergesort",
    )
    return ordered.groupby("DATE_OPENED", sort=False, observed=True).head(k)


def _score(name: str, kind: str, g: pd.DataFrame, years: float) -> list[dict[str, Any]]:
    opened = g["DATE_OPENED"].to_numpy(dtype="datetime64[ns]")
    is_m = opened < IS_CUT
    none_early = np.zeros(len(g), dtype=bool)
    rows = []
    for sl, mask in (
        ("FULL", np.ones(len(g), dtype=bool)),
        ("IS", is_m),
        ("OOS", ~is_m),
    ):
        sub_n = int(mask.sum())
        if sub_n == 0:
            met = _metrics(
                np.array([]),
                np.array([]),
                np.array([]),
                np.array([], dtype="datetime64[ns]"),
                np.array([]),
                np.array([]),
                np.array([], dtype=bool),
            )
        else:
            met = _metrics(
                g["PNL_PCT"].to_numpy(dtype=float)[mask],
                g["PNL_DOLLARS"].to_numpy(dtype=float)[mask],
                g["DAYS_HELD"].to_numpy(dtype=float)[mask],
                g["DATE_CLOSED"].to_numpy(dtype="datetime64[ns]")[mask],
                g["ENTRY_NOTIONAL"].to_numpy(dtype=float)[mask],
                g["SYMBOL"].to_numpy()[mask],
                none_early[mask],
            )
        met["arm"] = name
        met["kind"] = kind
        met["slice"] = sl
        met["trades_per_year"] = (met["n"] / years) if years > 0 else float("nan")
        rows.append(met)
        print(
            f"  {name} {sl} n={met['n']:,} tpy={met['trades_per_year']:.0f} "
            f"ann={met['ann']:.2f} dd={met['max_dd']:.2f}",
            flush=True,
        )
    return rows


def _judge(rows: list[dict[str, Any]]) -> str:
    by = {(r["arm"], r["slice"]): r for r in rows}
    c_is = by[("Gap-skip longs (control)", "IS")]
    c_oos = by[("Gap-skip longs (control)", "OOS")]
    bits = []
    keeps = []
    for arm in (
        "More extreme rank",
        "Worst 10 per day",
        "Worst 20 per day",
        "RSI at or below 30",
        "Larger half by market cap",
        "Deeper 5-day drop",
    ):
        a = by[(arm, "IS")]
        o = by[(arm, "OOS")]
        fewer = a["n"] < c_is["n"]
        ann_up = a["ann"] > c_is["ann"]
        dd_down = a["max_dd"] < c_is["max_dd"]
        collapsed = a["n"] < max(500, 0.15 * c_is["n"])
        oos_soft = (o["ann"] < c_oos["ann"]) or (o["max_dd"] > c_oos["max_dd"])
        if fewer and ann_up and dd_down and not collapsed and not oos_soft:
            tag = "KEEP"
            keeps.append(arm)
        elif fewer and ann_up and dd_down and not collapsed and oos_soft:
            tag = "HOLD"
        elif fewer and (ann_up or dd_down):
            tag = "HOLD"
        else:
            tag = "DISMISS"
        bits.append(
            f"{arm}: {tag}. IS N {a['n']:,} vs {c_is['n']:,}, "
            f"IS Ann ROR {a['ann']:.1f}% vs {c_is['ann']:.1f}%, "
            f"IS Max DD {a['max_dd']:.1f}% vs {c_is['max_dd']:.1f}%. "
            f"OOS Ann ROR {o['ann']:.1f}% vs {c_oos['ann']:.1f}%, "
            f"OOS Max DD {o['max_dd']:.1f}% vs {c_oos['max_dd']:.1f}%."
        )
    if not keeps:
        lead = (
            "No filter does all three on in-sample quality without an out-of-sample "
            "soften: fewer trades, higher Ann ROR, and lower Max DD. Nothing is a KEEP."
        )
    else:
        lead = "In-sample KEEP candidates that also hold up out of sample: " + ", ".join(keeps) + "."
    # Closest: among HOLD/others, best IS Ann ROR that still cuts N.
    return lead + " " + " ".join(bits)


def main() -> None:
    STAMP.mkdir(parents=True, exist_ok=True)
    ctrl = _load_longs()
    is_df = ctrl[ctrl["slice"] == "IS"]
    span_days = float(
        (ctrl["DATE_OPENED"].max() - ctrl["DATE_OPENED"].min()) / np.timedelta64(1, "D")
    )
    years = span_days / 365.25 if span_days > 0 else float("nan")
    rank_cut = float(is_df["RANK_PERCENTILE"].median())
    mcap_cut = float(is_df["MARKET_CAP"].median())
    lb_cut = float(is_df["LOOKBACK_RETURN_PCT"].median())
    print(
        f"IS median rank {rank_cut:.4f}  IS median mcap {mcap_cut:.0f}  IS median lookback {lb_cut:.4f}  years {years:.2f}",
        flush=True,
    )

    arms: list[tuple[str, str, pd.DataFrame]] = [
        ("Gap-skip longs (control)", "control", ctrl),
        ("More extreme rank", "rank", ctrl[ctrl["RANK_PERCENTILE"] <= rank_cut]),
        ("Worst 10 per day", "k10", _top_k(ctrl, 10)),
        ("Worst 20 per day", "k20", _top_k(ctrl, 20)),
        ("RSI at or below 30", "rsi", ctrl[ctrl["RSI14_AT_TRIGGER"] <= 30]),
        ("Larger half by market cap", "mcap", ctrl[ctrl["MARKET_CAP"] >= mcap_cut]),
        ("Deeper 5-day drop", "lookback", ctrl[ctrl["LOOKBACK_RETURN_PCT"] <= lb_cut]),
    ]
    rows: list[dict[str, Any]] = []
    for name, kind, g in arms:
        rows.extend(_score(name, kind, g, years))

    by = {(r["arm"], r["slice"]): r for r in rows}

    def delta(arm: str, sl: str, key: str) -> float:
        try:
            af = float(by[(arm, sl)][key])
            cf = float(by[("Gap-skip longs (control)", sl)][key])
        except (TypeError, ValueError, KeyError):
            return float("nan")
        if not (math.isfinite(af) and math.isfinite(cf)):
            return float("nan")
        return af - cf

    for r in rows:
        for src, dest in (
            ("n", "d_n"),
            ("trades_per_year", "d_tpy"),
            ("win_pct", "d_win"),
            ("avg_pct", "d_avg"),
            ("ann", "d_ann"),
            ("max_dd", "d_dd"),
            ("pf", "d_pf"),
            ("avg_wo_max", "d_wo"),
            ("expect_d", "d_exp"),
            ("calmar", "d_calmar"),
            ("sharpe", "d_sharpe"),
        ):
            r[dest] = delta(r["arm"], r["slice"], src)

    verdict = _judge(rows)
    # K lean on IS only, labeled, not a KEEP by itself.
    k10 = by[("Worst 10 per day", "IS")]
    k20 = by[("Worst 20 per day", "IS")]
    k_lean = "Worst 10 per day" if k10["ann"] >= k20["ann"] else "Worst 20 per day"
    k_note = (
        f"Between the two pre-declared day caps, the higher in-sample Ann ROR is {k_lean} "
        f"({by[(k_lean, 'IS')]['ann']:.1f}% vs the other). That choice is in-sample selection "
        f"between K=10 and K=20. It is not a keep unless the verdict above says so."
    )

    pd.DataFrame(rows).to_csv(STAMP / "scores.csv", index=False)

    def cell(r: dict[str, Any], key: str, nd: int = 2) -> str:
        return _f(r.get(key), nd)

    head_cols = [
        ("Arm", "arm", "text"),
        ("Slice", "slice", "text"),
        ("N", "n", "num"),
        ("dN", "d_n", "num"),
        ("Trades/year", "trades_per_year", "num"),
        ("dTrades/year", "d_tpy", "num"),
        ("Win %", "win_pct", "num"),
        ("dWin pp", "d_win", "num"),
        ("Avg PnL %", "avg_pct", "num"),
        ("dAvg pp", "d_avg", "num"),
        ("Ann ROR %", "ann", "num"),
        ("dAnn ROR pp", "d_ann", "num"),
        ("Max DD %", "max_dd", "num"),
        ("dMax DD pp", "d_dd", "num"),
        ("Profit factor", "pf", "num"),
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
        ("Calmar", "calmar", "num"),
        ("dCalmar", "d_calmar", "num"),
        ("Sharpe", "sharpe", "num"),
        ("dSharpe", "d_sharpe", "num"),
        ("Profit per capital day", "ppcd", "money"),
        ("Capital days", "capital_days", "num"),
        ("Avg days held", "avg_days", "num"),
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
            for _lab, key, kind in cols:
                if kind == "text":
                    tds.append(f"<td>{html_mod.escape(str(r.get(key, '')))}</td>")
                elif kind == "money":
                    tds.append(f"<td>{html_mod.escape(format_money(r.get(key)))}</td>")
                elif key in ("n", "d_n", "wins", "losses", "losing_streak"):
                    try:
                        tds.append(f"<td>{int(round(float(r.get(key)))):,}</td>")
                    except (TypeError, ValueError):
                        tds.append("<td></td>")
                else:
                    nd = 3 if key in ("avg_pct", "d_avg", "avg_wo_max", "d_wo", "expect_pct", "avg_win", "avg_loss") else 2
                    if key in ("trades_per_year", "d_tpy"):
                        nd = 1
                    tds.append(f"<td>{cell(r, key, nd)}</td>")
            body.append("<tr>" + "".join(tds) + "</tr>")
        return (
            '<div class="table-wrap"><table class="sortable"><thead><tr>'
            + th
            + "</tr></thead><tbody>"
            + "".join(body)
            + "</tbody></table></div>"
        )

    n_full = by[("Gap-skip longs (control)", "FULL")]["n"]
    n_is = by[("Gap-skip longs (control)", "IS")]["n"]
    count_note = (
        f"The control is gap-skip longs on the full unfiltered book: N={n_full:,}. "
        f"The in-sample slice is N={n_is:,}. The 174k figure matches that in-sample count, "
        f"not the full book."
    )

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>MUD gap-skip long filters</title>
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
<h1>Filters on MUD gap-skip longs</h1>
<p class="note">Most Up / Most Down (MUD), lookback 5, rebalance 1, longs only, skip a gap up. Research only. Not gold. Not DailyRun.</p>
<div class="callout">
<h2 style="margin-top:0">What you asked</h2>
<p>{html_mod.escape(ASK)}</p>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN)}</p>
<p>{html_mod.escape(count_note)}</p>
</div>
{SWIPE_NOTE_HTML}
<p class="note">Click a column header to sort. Enter or Space on a header sorts too. In-sample (IS) is entry before 2024-01-01. Out-of-sample (OOS) is entry on or after that date and is report-only. Annualized rate of return (Ann ROR) uses slot cash equal to the average entry notional of that arm and slice. Maximum drawdown (Max DD) replays closed-trade dollars by exit date from a {format_money(DEFAULT_INITIAL_ACCOUNT)} account. A lower Max DD is better. Trades/year uses one window for every arm: the control's first entry to its last entry ({years:.2f} years). Deltas are versus the gap-skip longs control on the same slice. Sharpe is exit-date equity, risk-free rate 0, annualized by observed exit frequency. Days underwater, position counts, industry concentration, and Paul / FIT scores are not computed.</p>

<h2>Verdict</h2>
<p>{html_mod.escape(verdict)}</p>
<p>{html_mod.escape(k_note)}</p>
<p>Filters are not stacked. The old average-minimum screen is not in this test. Naming a lean between K=10 and K=20 is in-sample selection.</p>

<h2>Headline</h2>
{table(rows, head_cols)}

<h2>More book metrics</h2>
{table(rows, extra_cols)}

<h2>Frozen cuts</h2>
<ul>
<li><strong>Control.</strong> Longs whose entry open is at or below the signal close. N full {n_full:,}. N IS {n_is:,}.</li>
<li><strong>More extreme rank.</strong> RANK_PERCENTILE at or below the IS median of the control, {rank_cut:.4f}. Lower means more washed out. Fit on IS only, then applied to OOS.</li>
<li><strong>Worst 10 and worst 20 per day.</strong> On each entry date, keep that many names with the most negative 5-day lookback return. Ties: lower rank percentile, then symbol. Both levels were declared before the scores.</li>
<li><strong>RSI at or below 30.</strong> RSI14 at the signal. One level. Missing RSI is left out of this arm.</li>
<li><strong>Larger half by market cap.</strong> Market cap at or above the IS median, {format_money(mcap_cut)}. Missing market cap is left out.</li>
<li><strong>Deeper 5-day drop.</strong> Lookback return at or below the IS median, {lb_cut:.2f}%. Fit on IS only.</li>
</ul>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    html_path = STAMP / "compare.html"
    html_path.write_text(html, encoding="utf-8")
    (STAMP / "BASELINE.md").write_text(
        "\n".join([
            "# MUD gap-skip long filters",
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
            count_note,
            "",
            "## Cuts (IS only)",
            "",
            f"- Rank percentile <= {rank_cut:.4f}",
            f"- Market cap >= {mcap_cut:.2f}",
            f"- Lookback return <= {lb_cut:.4f}%",
            "- RSI14 at trigger <= 30",
            "- K=10 and K=20 worst lookback names per entry date",
            "",
            "## Verdict",
            "",
            verdict,
            "",
            k_note,
            "",
            f"Max DD seed {DEFAULT_INITIAL_ACCOUNT:.0f}. Trades/year denominator {years:.4f} years.",
            "OOS is report-only. Filters are not stacked.",
            "",
        ]),
        encoding="utf-8",
    )
    text = html_path.read_text(encoding="utf-8")
    th_tags = re.findall(r"<th\b[^>]*>", text)
    n_th = len(th_tags)
    n_sth = sum(1 for t in th_tags if "sortable-th" in t)
    n_open = text.count("<script>")
    n_close = text.count("</script>")
    has_click = 'document.addEventListener("click"' in text
    has_key = 'e.key !== "Enter"' in text
    n_tables = text.count('<table class="sortable">')
    print(
        f"verify scripts {n_open}/{n_close} tables {n_tables} th {n_th} sth {n_sth} click {has_click}",
        flush=True,
    )
    if n_open != 1 or n_close != 1 or n_th != n_sth or n_tables < 1 or not has_click or not has_key:
        raise SystemExit("sortable header check failed")
    print(verdict.encode("ascii", "replace").decode("ascii"), flush=True)
    print("wrote " + str(html_path), flush=True)


if __name__ == "__main__":
    main()
