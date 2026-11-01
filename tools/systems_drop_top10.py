#!/usr/bin/env python3
"""Every live sleeve, plus MUD research books, as-is vs without the top 10% of trades.

Diagnostic only. The cut removes floor(10%) of each book's trades, ranked by
percent gain. A shared target price is not a reason to delete every trade at
that percent. Not a new filter. Not gold. Not DailyRun.
"""
from __future__ import annotations

import html as html_mod
import math
import re
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
    DEFAULT_INITIAL_ACCOUNT,
    ann_ror_from_closed,
    format_money,
    max_dd_pct_from_closed_pnl_by_date,
    sharpe_from_closed_pnl_by_date,
)
from mud_worst10_stacks_tail import _load_sides, _pick_k  # noqa: E402
from mud_tail_price_path import FULL_CSV  # noqa: E402
from report_page_extras import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)
from stop_loss_winner_trim_ab import _cash_for, load_closed  # noqa: E402

STAMP = _PE / "systems_drop_top10_20261008"
IS_CUT = np.datetime64("2024-01-01")
LIVE = ["BRT", "RL", "YH", "MTS", "WPBR", "RS", "SB", "VZ", "RSI", "WRL"]

ASK = (
    "show me what all of our systems look like as is vs. what they would look "
    "like without the top 10% of trades. Correction: This file should be showing "
    "the results after removing the top 10% of best trades, not the top 10 trades. "
    "Isn't that how the fat tail is measured? 10% of winners removed, not top 10 winners?"
)
PLAIN = (
    "The fat tail is the best tenth of the book by count, not the ten biggest trades "
    "and not every trade at or above the 90th percentile. An earlier version of this "
    "page used that percentile cutoff. On Break and ReTest (BRT), Magic Touch (MTS), "
    "and Weekly Pivot Break and Retest (WPBR) many exits share one round percent, "
    "about 20% to 22%, so the cutoff deleted far more than 10% of the trades. This "
    "page now ranks every trade by percent gain, best first. If the percent is missing, "
    "dollars decide. It drops floor(10% of the trade count), at least one trade when "
    "the book has 10 or more. Ties at the cutoff break by dollars, then symbol, then "
    "entry date, so only that count is removed. The count is chosen on the full book, "
    "then the kept trades are scored in full, before 2024, and from 2024 on. Those "
    "later rows are not a clean holdout. Out-of-sample is report-only. This is a "
    "check, not a rule to delete winners, and nothing is retuned."
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


def _metrics(
    pnl_pct: np.ndarray,
    pnl_d: np.ndarray,
    days: np.ndarray,
    exit_dt: np.ndarray,
    cash: float,
) -> dict[str, Any]:
    n = int(len(pnl_pct))
    empty: dict[str, Any] = {
        "n": 0,
        "win_pct": float("nan"),
        "avg_pct": float("nan"),
        "pf": float("nan"),
        "expect_d": float("nan"),
        "avg_days": float("nan"),
        "ann": float("nan"),
        "max_dd": float("nan"),
        "sharpe": float("nan"),
    }
    if n == 0:
        return empty
    wins = pnl_d > 0
    losses = pnl_d < 0
    win_d = float(pnl_d[wins].sum()) if wins.any() else 0.0
    loss_d = float(pnl_d[losses].sum()) if losses.any() else 0.0
    days_ok = days[np.isfinite(days) & (days > 0)]
    avg_days = float(days_ok.mean()) if len(days_ok) else float("nan")
    ann = ann_ror_from_closed(
        total_pnl=float(pnl_d.sum()),
        n_trades=n,
        avg_days_held=avg_days if math.isfinite(avg_days) else 0.0,
        brt_cash=cash if cash and cash > 0 else 0.0,
    )
    g = pd.Series(pnl_d).groupby(pd.to_datetime(exit_dt).normalize(), sort=False).sum()
    dated = list(zip(g.index.date, (float(v) for v in g.to_numpy())))
    mdd = max_dd_pct_from_closed_pnl_by_date(dated, initial_account=DEFAULT_INITIAL_ACCOUNT)
    sharpe = sharpe_from_closed_pnl_by_date(dated, initial_account=DEFAULT_INITIAL_ACCOUNT)
    return {
        "n": n,
        "win_pct": float(wins.mean() * 100.0),
        "avg_pct": float(np.nanmean(pnl_pct)),
        "pf": (win_d / abs(loss_d)) if loss_d < 0 else float("nan"),
        "expect_d": float(pnl_d.mean()),
        "avg_days": avg_days,
        "ann": float(ann) if ann is not None else float("nan"),
        "max_dd": float(mdd) if mdd is not None else float("nan"),
        "sharpe": float(sharpe) if sharpe is not None else float("nan"),
    }


def _slices(df: pd.DataFrame, cash_mode: str, fixed_cash: Optional[float]) -> list[dict[str, Any]]:
    opened = df["DATE_OPENED"].to_numpy(dtype="datetime64[ns]")
    pct = df["PNL_PCT"].to_numpy(dtype=float)
    dol = df["PNL_DOLLARS"].to_numpy(dtype=float)
    days = df["DAYS_HELD"].to_numpy(dtype=float)
    closed = df["DATE_CLOSED"].to_numpy(dtype="datetime64[ns]")
    ntl = df["ENTRY_NOTIONAL"].to_numpy(dtype=float)
    is_m = opened < IS_CUT
    out = []
    for sl, mask in (("FULL", np.ones(len(df), dtype=bool)), ("IS", is_m), ("OOS", ~is_m)):
        if cash_mode == "mean_notional":
            cash = float(np.nanmean(ntl[mask])) if mask.any() else float("nan")
        else:
            cash = float(fixed_cash or 0.0)
        met = _metrics(pct[mask], dol[mask], days[mask], closed[mask], cash)
        met["slice"] = sl
        met["cash"] = cash
        out.append(met)
    return out


def _drop_top_count(df: pd.DataFrame, frac: float = 0.10) -> tuple[pd.DataFrame, int, float]:
    """Drop floor(frac * N) best trades by count.

    Rank by PNL_PCT descending. If PNL_PCT is missing, PNL_DOLLARS ranks that row.
    Ties at the cutoff break by PNL_DOLLARS descending, then symbol, then entry date,
    so a pile of trades at the same percent (about 20% to 22%) does not all drop.
    n_drop is at least 1 when N >= 10, else 0 when floor(frac * N) is 0.
    """
    n = int(len(df))
    k = int(math.floor(n * frac))
    if n >= 10:
        k = max(k, 1)
    if k <= 0 or n == 0:
        return df.copy(), 0, float("nan")
    work = df.copy()
    if "PNL_DOLLARS" not in work.columns:
        work["PNL_DOLLARS"] = np.nan
    if "SYMBOL" not in work.columns:
        work["SYMBOL"] = ""
    if "DATE_OPENED" not in work.columns:
        work["DATE_OPENED"] = pd.NaT
    pct = pd.to_numeric(work["PNL_PCT"], errors="coerce")
    dol = pd.to_numeric(work["PNL_DOLLARS"], errors="coerce")
    # Percent first. A missing percent cannot outrank a real percent; those rows
    # sort by dollars among themselves at the bottom of the percent list.
    work["_rank_pct"] = pct.fillna(-1e18)
    work["_rank_dol"] = dol.fillna(-1e18)
    order = work.sort_values(
        ["_rank_pct", "_rank_dol", "SYMBOL", "DATE_OPENED"],
        ascending=[False, False, True, True],
        kind="mergesort",
    )
    dropped = order.iloc[:k]
    kept = order.iloc[k:].drop(columns=["_rank_pct", "_rank_dol"])
    boundary = dropped["PNL_PCT"].iloc[-1]
    boundary_f = float(boundary) if pd.notna(boundary) else float("nan")
    return kept, k, boundary_f


def _pair(name: str, group: str, df: pd.DataFrame, cash_mode: str, fixed_cash: Optional[float], cash_note: str) -> list[dict[str, Any]]:
    df = df.dropna(subset=["PNL_PCT", "DATE_OPENED", "DATE_CLOSED"]).copy()
    kept_df, n_removed, thr = _drop_top_count(df, 0.10)
    rows = []
    for book, g in (("As-is", df), ("Drop top 10%", kept_df)):
        for met in _slices(g, cash_mode, fixed_cash):
            met["system"] = name
            met["group"] = group
            met["book"] = book
            met["cutoff_pct"] = thr
            met["n_removed"] = n_removed
            met["n_book"] = int(len(df))
            met["pct_removed"] = (100.0 * n_removed / len(df)) if len(df) else 0.0
            met["cash_note"] = cash_note
            rows.append(met)
    full_drop = next(r for r in rows if r["book"] == "Drop top 10%" and r["slice"] == "FULL")
    is_drop = next(r for r in rows if r["book"] == "Drop top 10%" and r["slice"] == "IS")
    oos_drop = next(r for r in rows if r["book"] == "Drop top 10%" and r["slice"] == "OOS")
    ann_full = float(full_drop["ann"])
    fail = (not math.isfinite(ann_full)) or ann_full <= 0
    is_pos = is_drop["ann"] > 0
    oos_pos = oos_drop["ann"] > 0
    if fail:
        verdict = "Failure without the top 10% (full-book Ann ROR at or below zero)."
    elif is_pos and oos_pos:
        verdict = "Still positive on the full book, in-sample, and out-of-sample."
    else:
        bits = []
        if not is_pos:
            bits.append("in-sample Ann ROR is not positive")
        if not oos_pos:
            bits.append("out-of-sample Ann ROR is not positive")
        verdict = "Full-book Ann ROR stays positive, but " + " and ".join(bits) + "."
    for r in rows:
        r["verdict"] = verdict
        r["failure"] = "yes" if fail else "no"
    print(
        f"  {name}: remove {n_removed} of {len(df)}  boundary {thr:.3f}%  "
        f"as-is ann {rows[0]['ann']:.2f}  drop ann {full_drop['ann']:.2f}  fail {fail}",
        flush=True,
    )
    return rows


def _mud_unfiltered() -> pd.DataFrame:
    df = pd.read_csv(
        FULL_CSV,
        usecols=["SYMBOL", "DATE_OPENED", "DATE_CLOSED", "PNL_PCT", "PNL_DOLLARS", "ENTRY_NOTIONAL", "DAYS_HELD"],
        low_memory=False,
    )
    df["DATE_OPENED"] = pd.to_datetime(df["DATE_OPENED"], errors="coerce")
    df["DATE_CLOSED"] = pd.to_datetime(df["DATE_CLOSED"], errors="coerce")
    for c in ("PNL_PCT", "PNL_DOLLARS", "ENTRY_NOTIONAL", "DAYS_HELD"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=["DATE_OPENED", "DATE_CLOSED", "PNL_PCT"])


def main() -> None:
    STAMP.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for sys in LIVE:
        print(f"load {sys}", flush=True)
        df = load_closed(sys)
        cash, note = _cash_for(sys, df)
        rows.extend(_pair(sys, "Live", df, "fixed", cash, note))

    print("load MUD worst 10", flush=True)
    longs, _shorts = _load_sides()
    worst = _pick_k(longs, 10, worst=True)
    rows.extend(
        _pair(
            "MUD worst 10 longs",
            "Research",
            worst,
            "mean_notional",
            None,
            "MUD slot cash = mean ENTRY_NOTIONAL of that slice",
        )
    )
    print("load MUD unfiltered", flush=True)
    mud = _mud_unfiltered()
    rows.extend(
        _pair(
            "MUD L5_R1 both sleeves",
            "Research",
            mud,
            "mean_notional",
            None,
            "MUD slot cash = mean ENTRY_NOTIONAL of that slice",
        )
    )

    pd.DataFrame(rows).to_csv(STAMP / "scores.csv", index=False)

    def cell(r: dict[str, Any], key: str, nd: int = 2) -> str:
        return _f(r.get(key), nd)

    head_cols = [
        ("System", "system", "text"),
        ("Group", "group", "text"),
        ("Book", "book", "text"),
        ("Slice", "slice", "text"),
        ("N", "n", "num"),
        ("Removed", "n_removed", "num"),
        ("% removed", "pct_removed", "num"),
        ("Win %", "win_pct", "num"),
        ("Avg PnL %", "avg_pct", "num"),
        ("Ann ROR %", "ann", "num"),
        ("Max DD %", "max_dd", "num"),
        ("Profit factor", "pf", "num"),
        ("Expectancy $", "expect_d", "money"),
        ("Avg days", "avg_days", "num"),
        ("Failure without tail", "failure", "text"),
    ]

    def table(records: list[dict[str, Any]]) -> str:
        th = "".join(_th(lab, "text" if kind == "text" else "num") for lab, _k, kind in head_cols)
        body = []
        for r in records:
            tds = []
            for _lab, key, kind in head_cols:
                if kind == "text":
                    tds.append(f"<td>{html_mod.escape(str(r.get(key, '')))}</td>")
                elif kind == "money":
                    tds.append(f"<td>{html_mod.escape(format_money(r.get(key)))}</td>")
                elif key in {"n", "n_removed"}:
                    tds.append(f"<td>{int(r[key]):,}</td>")
                else:
                    nd = 3 if key == "avg_pct" else 2
                    tds.append(f"<td>{cell(r, key, nd)}</td>")
            body.append("<tr>" + "".join(tds) + "</tr>")
        return (
            '<div class="table-wrap"><table class="sortable"><thead><tr>'
            + th
            + "</tr></thead><tbody>"
            + "".join(body)
            + "</tbody></table></div>"
        )

    verdicts = []
    seen = set()
    for r in rows:
        if r["slice"] != "FULL" or r["book"] != "Drop top 10%" or r["system"] in seen:
            continue
        seen.add(r["system"])
        asis = next(x for x in rows if x["system"] == r["system"] and x["book"] == "As-is" and x["slice"] == "FULL")
        verdicts.append(
            f"{r['system']}: as-is Ann ROR {asis['ann']:.1f}%, without the best 10% by count "
            f"{r['ann']:.1f}% (dropped {int(r['n_removed']):,} of {int(r['n_book']):,}, "
            f"{r['pct_removed']:.1f}%). {r['verdict']}"
        )

    cash_lines = []
    seen_c = set()
    for r in rows:
        if r["system"] in seen_c or r["slice"] != "FULL" or r["book"] != "As-is":
            continue
        seen_c.add(r["system"])
        cash_lines.append(f"{r['system']}: {r['cash_note']} (full as-is cash used for live slices: {r['cash']:.2f})")

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Systems without the top 10% of trades</title>
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
<h1>Systems as-is vs without the top 10% of trades</h1>
<p class="note">Diagnostic only. Not a strategy. Not gold. Not DailyRun. Indicators (IND) and Minervini Volatility Contraction Pattern (MVCP) are not included.</p>
<div class="callout">
<h2 style="margin-top:0">What you asked</h2>
<p>{html_mod.escape(ASK)}</p>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN)}</p>
</div>
{SWIPE_NOTE_HTML}
<p class="note">Click a column header to sort. Enter or Space sorts too. In-sample (IS) is entry before 2024-01-01. Out-of-sample (OOS) is entry on or after that date and is report-only. The top 10% is a count on the full book: floor(10% of trades), highest percent gain first. The same kept trades are then split into IS and OOS, so those rows are not a pure untouched holdout. Removed is that count, repeated on every row of the system. Annualized rate of return (Ann ROR) uses the house formula. Live sleeves use one slot-cash number from the Closed file (median dollars implied by percent gain; a Report capacity figure is used only if it is within 25% of that median). Most Up / Most Down (MUD) rows use the average entry notional of that slice, the same cash rule as the MUD research pages. Maximum drawdown (Max DD) replays closed-trade dollars by exit date from a {format_money(DEFAULT_INITIAL_ACCOUNT)} account. A lower Max DD is better. A figure above 100% means the replayed equity went below zero. Sharpe is exit-date equity, risk-free rate 0, annualized by observed exit frequency. Days underwater, position counts, industry concentration, and Paul / FIT scores are not on this page.</p>
<h2>One line each</h2>
<ul>
{''.join(f'<li>{html_mod.escape(v)}</li>' for v in verdicts)}
</ul>
<h2>Headline</h2>
{table(rows)}
<h2>Cash used</h2>
<ul>
{''.join(f'<li>{html_mod.escape(c)}</li>' for c in cash_lines)}
</ul>
<p class="note">Failure means full-book Ann ROR is at or below zero after the cut. Do not drop the winners as a live rule.</p>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    html_path = STAMP / "compare.html"
    html_path.write_text(html, encoding="utf-8")
    (STAMP / "BASELINE.md").write_text(
        "\n".join(
            [
                "# Systems without the top 10% of trades",
                "",
                "Diagnostic only. Not gold. Not DailyRun. Do not adopt the cut.",
                "",
                "## What you asked",
                "",
                ASK,
                "",
                "## In plain English",
                "",
                PLAIN,
                "",
                "Cut: n_drop = floor(0.10 * N), at least 1 if N >= 10, else 0.",
                "Rank: PNL_PCT descending. Missing PNL_PCT does not outrank a real percent.",
                "Tie-break: PNL_DOLLARS descending, then SYMBOL, then DATE_OPENED. Only n_drop rows leave.",
                "Boundary percent is the smallest PNL_PCT among the removed trades.",
                "IS/OOS of the cut reuse that full-book kept set. Not a pure holdout.",
                f"Max DD seed {DEFAULT_INITIAL_ACCOUNT:.0f}.",
                "Live cash: Closed median implied notional, capacity only if within 25%.",
                "MUD cash: mean ENTRY_NOTIONAL of the slice.",
                "",
                "## Verdicts",
                "",
                *verdicts,
                "",
                "## Cash",
                "",
                *cash_lines,
                "",
            ]
        ),
        encoding="utf-8",
    )
    text = html_path.read_text(encoding="utf-8")
    th_tags = re.findall(r"<th\b[^>]*>", text)
    n_open = len(re.findall(r"<script\b", text, flags=re.I))
    n_close = text.count("</script>")
    n_th = len(th_tags)
    n_sth = sum(1 for t in th_tags if "sortable-th" in t)
    print(f"verify script {n_open}/{n_close} th {n_th} sth {n_sth}", flush=True)
    if n_open != 1 or n_close != 1 or n_th != n_sth or n_th < 1:
        raise SystemExit("sortable header check failed")
    if 'document.addEventListener("click"' not in text or 'e.key !== "Enter"' not in text:
        raise SystemExit("sort handler missing")
    print("wrote " + str(html_path), flush=True)


if __name__ == "__main__":
    main()
