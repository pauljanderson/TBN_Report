#!/usr/bin/env python3
"""Worst-10 MUD longs, right-tail diagnostic, shorts hedge, and one-at-a-time stacks.

Research only. Not gold. Not DailyRun. Worst-10 was chosen after an in-sample
horse-race. The top-10% drop is a diagnostic, not a new entry rule.
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

STAMP = _PE / "mud_worst10_stacks_tail_20261008"
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
    "everything was better than control. nice job. can you update the table showing "
    "what the right tail effect is? I am curious if we remove the top10% if the "
    "system is a failure. Let's adopt the worst 10 per day. can we run that against "
    "the best 10 per day and we short those? Also it looks like smaller half by "
    "market cap would be better than larger half by market cap, can we run those "
    "numbers? and finally I'd like to see worst 10 per day + each of the other arms."
)
PLAIN = (
    "Most Up / Most Down (MUD) here means the long book that skips gap-ups and "
    "keeps only the 10 most washed-out names each day. That worst-10 rule is the "
    "adopted research freeze. This page checks whether those results depend on "
    "the best 10% of trades, compares a matching short book (the 10 names that "
    "rose the most, skipping gap-downs), and tries the smaller half of names by "
    "market cap. It also stacks worst-10 with one extra filter at a time. "
    "Annualized rate of return (Ann ROR) and maximum drawdown (Max DD) are shown "
    "with and without the top 10% of trades. Dropping those winners is a check, "
    "not a new way to pick stocks."
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


def _load_sides() -> tuple[pd.DataFrame, pd.DataFrame]:
    df = pd.read_csv(FULL_CSV, usecols=USECOLS, low_memory=False)
    df["SIDE"] = df["SIDE"].astype(str).str.lower()
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
    need = df[["SYMBOL", "SIGNAL_DATE"]].drop_duplicates().rename(
        columns={"SYMBOL": "symbol", "SIGNAL_DATE": "d"}
    )
    need["d"] = need["d"].dt.normalize()
    print(f"rows {len(df):,} signal keys {len(need):,}", flush=True)
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
    entry = df["ENTRY_PRICE"].to_numpy()
    sig = df["sig_c"].to_numpy()
    long = df["SIDE"].to_numpy() == "long"
    # Long: skip gap up. Short: skip gap down. Flat open stays in.
    gap = np.where(long, entry <= sig, entry >= sig) & ok
    df = df.loc[gap].copy()
    df["slice"] = np.where(df["DATE_OPENED"].to_numpy(dtype="datetime64[ns]") < IS_CUT, "IS", "OOS")
    longs = df[df["SIDE"] == "long"].copy()
    shorts = df[df["SIDE"] == "short"].copy()
    print(f"gap-skip longs {len(longs):,} shorts {len(shorts):,}", flush=True)
    return longs, shorts


def _pick_k(df: pd.DataFrame, k: int, *, worst: bool) -> pd.DataFrame:
    # Worst longs: most negative lookback, then lower rank percentile.
    # Best shorts: most positive lookback, then higher rank percentile.
    ordered = df.sort_values(
        ["DATE_OPENED", "LOOKBACK_RETURN_PCT", "RANK_PERCENTILE", "SYMBOL"],
        ascending=[True, worst, not worst, True],
        na_position="last",
        kind="mergesort",
    )
    return ordered.groupby("DATE_OPENED", sort=False, observed=True).head(k)


def _drop_top10(df: pd.DataFrame) -> pd.DataFrame:
    if len(df) == 0:
        return df
    thr = float(df["PNL_PCT"].quantile(0.9))
    return df.loc[df["PNL_PCT"] < thr].copy()


def _score(name: str, kind: str, book: str, g: pd.DataFrame, years: float) -> list[dict[str, Any]]:
    opened = g["DATE_OPENED"].to_numpy(dtype="datetime64[ns]") if len(g) else np.array([], dtype="datetime64[ns]")
    is_m = opened < IS_CUT if len(g) else np.array([], dtype=bool)
    none_early = np.zeros(len(g), dtype=bool)
    rows = []
    masks = (
        ("FULL", np.ones(len(g), dtype=bool)),
        ("IS", is_m),
        ("OOS", ~is_m if len(g) else is_m),
    )
    for sl, mask in masks:
        n = int(mask.sum()) if len(g) else 0
        if n == 0:
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
        met["book"] = book
        met["slice"] = sl
        met["trades_per_year"] = (met["n"] / years) if years > 0 else float("nan")
        rows.append(met)
    r = next(x for x in rows if x["slice"] == "FULL")
    print(
        f"  {name} [{book}] n={r['n']:,} ann={r['ann']:.2f} dd={r['max_dd']:.2f}",
        flush=True,
    )
    return rows


def main() -> None:
    STAMP.mkdir(parents=True, exist_ok=True)
    longs, shorts = _load_sides()
    is_long = longs[longs["slice"] == "IS"]
    rank_cut = float(is_long["RANK_PERCENTILE"].median())
    mcap_cut = float(is_long["MARKET_CAP"].median())
    lb_cut = float(is_long["LOOKBACK_RETURN_PCT"].median())
    span_days = float((longs["DATE_OPENED"].max() - longs["DATE_OPENED"].min()) / np.timedelta64(1, "D"))
    years = span_days / 365.25 if span_days > 0 else float("nan")
    print(
        f"IS rank<={rank_cut:.4f} mcap median {mcap_cut:.0f} lookback<={lb_cut:.4f} years {years:.2f}",
        flush=True,
    )

    worst10 = _pick_k(longs, 10, worst=True)
    best10 = _pick_k(shorts, 10, worst=False)
    hedge = pd.concat([worst10, best10], ignore_index=True)
    small = longs[longs["MARKET_CAP"] < mcap_cut]
    large = longs[longs["MARKET_CAP"] >= mcap_cut]
    stacks = [
        ("Worst 10 + extreme rank", "stack", worst10[worst10["RANK_PERCENTILE"] <= rank_cut]),
        ("Worst 10 + RSI <= 30", "stack", worst10[worst10["RSI14_AT_TRIGGER"] <= 30]),
        ("Worst 10 + smaller cap", "stack", worst10[worst10["MARKET_CAP"] < mcap_cut]),
        ("Worst 10 + deeper drop", "stack", worst10[worst10["LOOKBACK_RETURN_PCT"] <= lb_cut]),
    ]
    books = [
        ("Gap-skip longs (reference)", "reference", longs),
        ("Worst 10 longs", "control", worst10),
        ("Best 10 shorts", "short", best10),
        ("Worst 10 long + best 10 short", "hedge", hedge),
        ("Smaller half by market cap", "mcap", small),
        ("Larger half by market cap", "mcap_ref", large),
        *stacks,
    ]

    rows: list[dict[str, Any]] = []
    for name, kind, g in books:
        rows.extend(_score(name, kind, "All trades", g, years))
        rows.extend(_score(name, kind, "Drop top 10%", _drop_top10(g), years))

    by = {(r["arm"], r["book"], r["slice"]): r for r in rows}
    ctrl_name = "Worst 10 longs"

    def delta(arm: str, book: str, sl: str, key: str) -> float:
        try:
            af = float(by[(arm, book, sl)][key])
            cf = float(by[(ctrl_name, book, sl)][key])
        except (TypeError, ValueError, KeyError):
            return float("nan")
        if not (math.isfinite(af) and math.isfinite(cf)):
            return float("nan")
        return af - cf

    for r in rows:
        # Deltas vs worst-10 on the same book (all trades, or the same tail cut).
        for src, dest in (
            ("n", "d_n"),
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
            r[dest] = delta(r["arm"], r["book"], r["slice"], src)

    def line(arm: str, book: str) -> str:
        full = by[(arm, book, "FULL")]
        ins = by[(arm, book, "IS")]
        oos = by[(arm, book, "OOS")]
        fail = "FAILURE without the top 10%" if full["ann"] <= 0 else "still positive without the top 10%"
        if book == "All trades":
            return (
                f"{arm}: N {full['n']:,}, win {full['win_pct']:.1f}%, avg {full['avg_pct']:.3f}%, "
                f"Ann ROR {full['ann']:.1f}% / {ins['ann']:.1f}% / {oos['ann']:.1f}%, "
                f"Max DD {full['max_dd']:.1f}% / {ins['max_dd']:.1f}% / {oos['max_dd']:.1f}%."
            )
        return (
            f"{arm} after dropping the top 10%: N {full['n']:,}, Ann ROR {full['ann']:.1f}% "
            f"(IS {ins['ann']:.1f}%, OOS {oos['ann']:.1f}%), Max DD {full['max_dd']:.1f}% "
            f"(IS {ins['max_dd']:.1f}%, OOS {oos['max_dd']:.1f}%). {fail}."
        )

    w_is = by[(ctrl_name, "All trades", "IS")]
    notes = []
    keeps = []
    for arm, kind, _g in books:
        if kind not in ("stack", "hedge", "short", "mcap"):
            continue
        a = by[(arm, "All trades", "IS")]
        o = by[(arm, "All trades", "OOS")]
        tail = by[(arm, "Drop top 10%", "FULL")]
        fewer_or_ok = a["n"] >= max(500, 0.15 * w_is["n"])
        ann_up = a["ann"] > w_is["ann"]
        dd_better = a["max_dd"] < w_is["max_dd"]
        if fewer_or_ok and (ann_up or dd_better):
            tag = "KEEP vs worst-10 on IS"
            keeps.append(arm)
        elif a["n"] < max(500, 0.15 * w_is["n"]):
            tag = "DISMISS (N collapsed vs worst-10)"
        else:
            tag = "DISMISS vs worst-10 on IS"
        tail_bit = (
            "The full-book Ann ROR without the top 10% is at or below zero, so the edge is the right tail."
            if tail["ann"] <= 0
            else f"Without the top 10%, full-book Ann ROR is still {tail['ann']:.1f}%."
        )
        notes.append(
            f"{arm}: {tag}. IS Ann ROR {a['ann']:.1f}% vs worst-10 {w_is['ann']:.1f}%, "
            f"IS Max DD {a['max_dd']:.1f}% vs {w_is['max_dd']:.1f}%, IS N {a['n']:,} vs {w_is['n']:,}. "
            f"OOS Ann ROR {o['ann']:.1f}% (report-only). {tail_bit}"
        )
    if keeps:
        lead = (
            "In-sample selection: more than one arm can look better than worst-10. "
            "Arms that improve IS Ann ROR or IS Max DD without collapsing N: " + ", ".join(keeps) + "."
        )
    else:
        lead = "No stack, short book, or smaller-cap book improves IS Ann ROR or IS Max DD versus worst-10 without collapsing N."
    verdict = lead + " " + " ".join(notes)
    tail_ctrl = line(ctrl_name, "Drop top 10%")
    small_full = by[("Smaller half by market cap", "All trades", "FULL")]
    large_full = by[("Larger half by market cap", "All trades", "FULL")]
    size_note = (
        f"Smaller half (market cap below {format_money(mcap_cut)}) full Ann ROR {small_full['ann']:.1f}% "
        f"and Max DD {small_full['max_dd']:.1f}%, versus larger half Ann ROR {large_full['ann']:.1f}% "
        f"and Max DD {large_full['max_dd']:.1f}%. The cutoff is the IS median market cap of gap-skip longs."
    )

    pd.DataFrame(rows).to_csv(STAMP / "scores.csv", index=False)

    def cell(r: dict[str, Any], key: str, nd: int = 2) -> str:
        return _f(r.get(key), nd)

    head_cols = [
        ("Arm", "arm", "text"),
        ("Book", "book", "text"),
        ("Slice", "slice", "text"),
        ("N", "n", "num"),
        ("dN vs worst-10", "d_n", "num"),
        ("Win %", "win_pct", "num"),
        ("Avg PnL %", "avg_pct", "num"),
        ("dAvg pp", "d_avg", "num"),
        ("Ann ROR %", "ann", "num"),
        ("dAnn ROR pp", "d_ann", "num"),
        ("Max DD %", "max_dd", "num"),
        ("dMax DD pp", "d_dd", "num"),
        ("Profit factor", "pf", "num"),
        ("Trades/year", "trades_per_year", "num"),
    ]
    extra_cols = [
        ("Arm", "arm", "text"),
        ("Book", "book", "text"),
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
        ("dPF", "d_pf", "num"),
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
                    if key == "trades_per_year":
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

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>MUD worst 10, tail, and stacks</title>
<style>
body {{ font-family: Georgia, serif; margin: 24px; color: #1a1a1a; line-height: 1.45; }}
h1 {{ font-size: 1.5rem; }}
h2 {{ font-size: 1.15rem; margin-top: 1.5rem; }}
.callout {{ background: #f4f1ea; border-left: 4px solid #8a6a3b; padding: 12px 14px; margin: 12px 0 18px; }}
.note {{ color: #444; font-size: 0.95rem; }}
{SORTABLE_TH_CSS}
{SORT_ARROW_CSS}
</style>
</head><body>
<h1>MUD worst 10, right tail, and stacks</h1>
<p class="note">Most Up / Most Down (MUD). Research freeze only. Not gold. Not DailyRun.</p>
<div class="callout">
<h2 style="margin-top:0">What you asked</h2>
<p>{html_mod.escape(ASK)}</p>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN)}</p>
</div>
{SWIPE_NOTE_HTML}
<p class="note">Click a column header to sort. Enter or Space sorts too. In-sample (IS) is entry before 2024-01-01. Out-of-sample (OOS) is entry on or after that date and is report-only. Annualized rate of return (Ann ROR) uses slot cash equal to the average entry notional of that arm and slice. Maximum drawdown (Max DD) replays closed-trade dollars by exit date from a {format_money(DEFAULT_INITIAL_ACCOUNT)} account. A lower Max DD is better. Deltas compare to worst-10 longs on the same book (all trades, or after the same style of top-10% drop). Trades/year uses the gap-skip long date span ({years:.2f} years) for every arm. Sharpe is exit-date equity, risk-free rate 0, annualized by observed exit frequency. Days underwater, position counts, industry concentration, and Paul / FIT scores are not computed. The top-10% drop uses each arm's own full-book 90th percentile of percent gain. It is not an entry filter and nothing was retuned because of it.</p>
<h2>Verdict</h2>
<p>{html_mod.escape(line(ctrl_name, "All trades"))}</p>
<p>{html_mod.escape(tail_ctrl)}</p>
<p>{html_mod.escape(size_note)}</p>
<p>{html_mod.escape(verdict)}</p>
<h2>Headline</h2>
{table(rows, head_cols)}
<h2>More book metrics</h2>
{table(rows, extra_cols)}
<h2>Freeze</h2>
<ul>
<li><strong>Adopted control.</strong> Gap-skip longs (entry open at or below the signal close), then each entry date keep the 10 most negative 5-day lookback returns. Ties: lower rank percentile, then symbol. Chosen after the prior in-sample horse-race among rank, K=10, and K=20. That choice is in-sample selection.</li>
<li><strong>Reference.</strong> All gap-skip longs, no daily cap.</li>
<li><strong>Best 10 shorts.</strong> Gap-skip shorts (entry open at or above the signal close), then each entry date keep the 10 most positive lookback returns. Ties: higher rank percentile, then symbol.</li>
<li><strong>Hedge.</strong> Worst-10 longs plus best-10 shorts.</li>
<li><strong>Smaller half.</strong> Gap-skip longs with market cap below the IS median, {format_money(mcap_cut)}. Larger half is market cap at or above that same freeze, shown only as the comparison.</li>
<li><strong>Stacks, one extra filter at a time.</strong> Rank percentile &lt;= {rank_cut:.4f}. RSI14 at the signal &lt;= 30. Market cap below {format_money(mcap_cut)}. Lookback return &lt;= {lb_cut:.2f}%. Those cuts were frozen on IS gap-skip longs. Worst 10 is not stacked with worst 20 or with the larger-cap half.</li>
</ul>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    html_path = STAMP / "compare.html"
    html_path.write_text(html, encoding="utf-8")
    (STAMP / "BASELINE.md").write_text(
        "\n".join([
            "# MUD worst 10, tail, and stacks",
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
            "## Adopted freeze",
            "",
            "Worst 10 longs: gap-skip (entry open <= signal close), then 10 most negative",
            "LOOKBACK_RETURN_PCT per entry date. Tie: lower RANK_PERCENTILE, then symbol.",
            "In-sample selection: K=10 was chosen after the IS horse-race among rank, K=10, and K=20.",
            "",
            f"Rank cutoff <= {rank_cut:.4f} (IS median of gap-skip longs).",
            f"Market-cap median {mcap_cut:.2f}. Smaller half is strictly below. Larger half is at or above.",
            f"Lookback cutoff <= {lb_cut:.4f}%.",
            "RSI14 at trigger <= 30.",
            "",
            "## Tail",
            "",
            tail_ctrl,
            "",
            size_note,
            "",
            verdict,
            "",
            "OOS is report-only. The top-10% drop is a diagnostic, not an entry filter.",
            f"Max DD seed {DEFAULT_INITIAL_ACCOUNT:.0f}.",
            "",
        ]),
        encoding="utf-8",
    )
    text = html_path.read_text(encoding="utf-8")
    th_tags = re.findall(r"<th\b[^>]*>", text)
    n_open = len(re.findall(r"<script\b", text, flags=re.I))
    n_close = text.count("</script>")
    n_th = len(th_tags)
    n_sth = sum(1 for t in th_tags if "sortable-th" in t)
    print(
        f"verify script {n_open}/{n_close} th {n_th} sth {n_sth}",
        flush=True,
    )
    if n_open != 1 or n_close != 1 or n_th != n_sth or n_th < 1:
        raise SystemExit("sortable header check failed")
    if 'document.addEventListener("click"' not in text or 'e.key !== "Enter"' not in text:
        raise SystemExit("sort handler missing")
    print("wrote " + str(html_path), flush=True)


if __name__ == "__main__":
    main()
