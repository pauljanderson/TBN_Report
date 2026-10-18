#!/usr/bin/env python3
"""SB + RS + VZ one-wallet compound path under the investment-report live-style lids.

Two arms, same freeze:
  1) StockBee (SB), Relative Strength vs SPY (RS), and Volume Zone (VZ) together.
  2) Same book after deleting the top 10% of winning trades (ex-post).

Lids match the investment report / stamp risk_1pct_50k_adv_17name_20260917:
  risk = min(1% beginning-of-month equity, $50,000)
  shares <= 1% of 20-session average daily volume
  open notional in one name <= 17.5% of current equity
  start $250,000, buying power 2x, 10.5% margin interest, no bank wires, no rotation.

Research only. Not gold. Not DailyRun.
"""
from __future__ import annotations

import html as html_mod
import importlib.util
import math
import sys
from copy import copy
from datetime import date
from pathlib import Path
from typing import Any, Optional

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))

from compare_format import format_money, format_money_delta  # noqa: E402
from report_page_extras import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)

STAMP = "sb_rs_vz_live_style_compound_20261012"
OUT = REPO / "drive" / "paul_experiments" / STAMP
IS_CUT = date(2024, 1, 1)
SYSTEMS = ("RS", "SB", "VZ")
RANK = {"RS": 0, "SB": 1, "VZ": 2}

ORIGINAL = (
    "lets do the following but for sb, rs, and vz. The following was: can you "
    "generate a report much like investment history where we realistically compound "
    "growth as per the limits in the investment history report for just RS and VZ "
    "combined? and then show the same if we somehow miss the top 10% of successful "
    "trades. i would like a report and a ntfy please"
)

PLAIN = (
    "This is a paper account, not the broker statement. It starts at $250,000 in 2010 "
    "and only takes StockBee (SB), Relative Strength vs SPY (RS), and Volume Zone (VZ). "
    "Each month the dollars risked on a new buy are 1% of what the account was worth "
    "at the start of that month, and never more than $50,000. A buy cannot be more "
    "than 1% of the stock's recent daily volume, and one ticker cannot be more than "
    "17.5% of the account. The account may borrow so stock cost is at most twice the "
    "account, and pays 10.5% a year on the borrowed part. No money is wired out to "
    "the bank. The second path is the same account after we pretend the best 10% of "
    "the winning trades never happened. That deletion looks at the finished percent "
    "gain, so it is a what-if, not a rule you could have used on the buy day. Nothing "
    "here is gold and nothing is wired into DailyRun."
)


def _load_five():
    spec = importlib.util.spec_from_file_location(
        "risk2500_five_sys_20260917",
        REPO / "tools" / "risk2500_five_sys_20260917.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load risk2500_five_sys_20260917")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["risk2500_five_sys_20260917"] = mod
    spec.loader.exec_module(mod)
    return mod


def _winner_key(t: Any) -> tuple:
    return (t.system, t.symbol, t.opened.isoformat(), round(float(t.entry), 6))


def drop_top_winners(trades: list[Any]) -> tuple[list[Any], dict[str, Any]]:
    """Drop the top 10% of closed winners by percent gain. Open trades stay."""
    winners = [t for t in trades if t.status == "closed" and float(t.pnl_pct) > 0]
    n = len(winners)
    if n == 0:
        return list(trades), {"n_winners": 0, "n_drop": 0, "cutoff_pct": None}
    k = max(1, int(round(n * 0.10)))
    ranked = sorted(
        winners,
        key=lambda t: (-float(t.pnl_pct), t.opened.isoformat(), t.symbol, t.system),
    )
    dropped = ranked[:k]
    cutoff = float(dropped[-1].pnl_pct)
    drop_keys = {_winner_key(t) for t in dropped}
    kept = [t for t in trades if _winner_key(t) not in drop_keys]
    by_sys: dict[str, int] = {}
    for t in dropped:
        by_sys[t.system] = by_sys.get(t.system, 0) + 1
    return kept, {
        "n_winners": n,
        "n_drop": len(dropped),
        "cutoff_pct": cutoff,
        "best_pct": float(ranked[0].pnl_pct),
        "by_system": by_sys,
        "examples": [
            {
                "system": t.system,
                "symbol": t.symbol,
                "opened": t.opened.isoformat(),
                "pnl_pct": float(t.pnl_pct),
            }
            for t in dropped[:15]
        ],
    }


def _cagr(end_eq: float, start_eq: float, start: date, end: date) -> Optional[float]:
    years = (end - start).days / 365.25
    if years <= 0 or start_eq <= 0 or end_eq <= 0:
        return None
    return ((end_eq / start_eq) ** (1.0 / years) - 1.0) * 100.0


def _snap_equity_on_or_before(snaps: list[Any], day: date) -> Optional[float]:
    best = None
    best_d = None
    for s in snaps:
        mend = _month_end(int(s.year), int(s.month))
        if mend <= day and (best_d is None or mend > best_d):
            best_d = mend
            best = float(s.equity_end)
    return best


def _fmt_pct(v: Any, nd: int = 2) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(x):
        return "—"
    return f"{x:,.{nd}f}%"


def _fmt_num(v: Any, nd: int = 2) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(x):
        return "—"
    return f"{x:,.{nd}f}"


def _th(label: str, typ: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{typ}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _td_num(text: str) -> str:
    return f"<td>{text}</td>"


def _delta_pct(a: Any, b: Any) -> str:
    try:
        x, y = float(a), float(b)
    except (TypeError, ValueError):
        return "—"
    if not (math.isfinite(x) and math.isfinite(y)):
        return "—"
    d = y - x
    sign = "+" if d > 0 else ""
    return f"{sign}{d:,.2f} pp"


def _run(mod: Any, trades: list[Any], label: str) -> dict[str, Any]:
    return mod._run_arm(
        [copy(t) for t in trades],
        rank=RANK,
        rotate="none",
        withdraw=False,
        label=label,
        risk_frac=0.01,
        name_cap_frac=0.175,
        max_risk_dollar=50_000.0,
        adv_frac=0.01,
        start_equity=250_000.0,
    )


def _month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date.fromordinal(date(year, month + 1, 1).toordinal() - 1)


def _slice_cagr(arm: dict[str, Any], start: date, asof: date) -> dict[str, Optional[float]]:
    snaps = arm["snaps"]
    led = arm["led"]
    seed = float(arm["start_equity"])
    end_eq = float(led.end_equity)
    is_end = _snap_equity_on_or_before(snaps, date(2023, 12, 31))
    full = _cagr(end_eq, seed, start, asof)
    is_c = _cagr(is_end, seed, start, date(2023, 12, 31)) if is_end else None
    oos_c = _cagr(end_eq, is_end, date(2024, 1, 1), asof) if is_end else None
    return {"full": full, "is": is_c, "oos": oos_c, "is_end_eq": is_end, "end_eq": end_eq}


def _metric_rows(arm: dict[str, Any]) -> list[tuple[str, str, Any, Any, Any]]:
    """(label, kind, full, is, oos) kind in num|pct|money|int."""
    f, i, o = arm["stats_full"], arm["stats_is"], arm["stats_oos"]

    def g(st, key):
        return st.get(key)

    return [
        ("Closed fills", "int", g(f, "n"), g(i, "n"), g(o, "n")),
        ("Wins", "int", g(f, "wins"), g(i, "wins"), g(o, "wins")),
        ("Losses", "int", g(f, "losses"), g(i, "losses"), g(o, "losses")),
        ("Win %", "pct", g(f, "win_pct"), g(i, "win_pct"), g(o, "win_pct")),
        ("Avg PnL %", "pct", g(f, "avg_pnl_pct"), g(i, "avg_pnl_pct"), g(o, "avg_pnl_pct")),
        ("Avg PnL % without best trade", "pct", g(f, "avg_wo_max"), g(i, "avg_wo_max"), g(o, "avg_wo_max")),
        ("Expectancy %", "pct", g(f, "expectancy_pct"), g(i, "expectancy_pct"), g(o, "expectancy_pct")),
        ("Expectancy $", "money", g(f, "expectancy_dol"), g(i, "expectancy_dol"), g(o, "expectancy_dol")),
        ("Avg win %", "pct", g(f, "avg_win_pct"), g(i, "avg_win_pct"), g(o, "avg_win_pct")),
        ("Avg loss %", "pct", g(f, "avg_loss_pct"), g(i, "avg_loss_pct"), g(o, "avg_loss_pct")),
        ("Win/loss count", "num", g(f, "wl_count"), g(i, "wl_count"), g(o, "wl_count")),
        ("Win/loss $", "num", g(f, "wl_dol"), g(i, "wl_dol"), g(o, "wl_dol")),
        ("Profit factor", "num", g(f, "pf"), g(i, "pf"), g(o, "pf")),
        ("Ann ROR %", "pct", g(f, "ann_ror"), g(i, "ann_ror"), g(o, "ann_ror")),
        ("Max DD %", "pct", g(f, "max_dd"), g(i, "max_dd"), g(o, "max_dd")),
        ("Calmar", "num", g(f, "calmar"), g(i, "calmar"), g(o, "calmar")),
        ("Sharpe", "num", g(f, "sharpe"), g(i, "sharpe"), g(o, "sharpe")),
        ("Profit / capital day", "money", g(f, "profit_per_cap_day"), g(i, "profit_per_cap_day"), g(o, "profit_per_cap_day")),
        ("Capital days", "num", g(f, "capital_days"), g(i, "capital_days"), g(o, "capital_days")),
        ("Avg days held", "num", g(f, "avg_days"), g(i, "avg_days"), g(o, "avg_days")),
        ("Median days held", "num", g(f, "median_days"), g(i, "median_days"), g(o, "median_days")),
        ("P90 days held", "num", g(f, "p90_days"), g(i, "p90_days"), g(o, "p90_days")),
        ("Losing streak", "int", g(f, "losing_streak"), g(i, "losing_streak"), g(o, "losing_streak")),
        ("Avg positions", "num", g(f, "avg_pos"), g(i, "avg_pos"), g(o, "avg_pos")),
        ("Max positions", "int", g(f, "max_pos"), g(i, "max_pos"), g(o, "max_pos")),
        ("Mean notional", "money", g(f, "mean_notional"), g(i, "mean_notional"), g(o, "mean_notional")),
    ]


def _cell(kind: str, v: Any) -> str:
    if kind == "money":
        return format_money(v) if v is not None else "—"
    if kind == "pct":
        return _fmt_pct(v)
    if kind == "int":
        try:
            return f"{int(v):,}"
        except (TypeError, ValueError):
            return "—"
    return _fmt_num(v)


def _year_table(arms: list[dict[str, Any]], spy: dict[str, Any], asof: date) -> str:
    head = (
        _th("Year", "num")
        + "".join(_th(a["label"], "num") for a in arms)
        + _th("SPY total return", "num")
        + _th("SPY price only", "num")
    )
    body = []
    for y in range(2010, asof.year + 1):
        cells = [f"<td>{y}</td>"]
        for a in arms:
            row = next((x for x in a["years"] if x["year"] == y), None)
            cells.append(f"<td>{format_money(row['ending_equity']) if row else '—'}</td>")
        sy = spy["years"].get(y)
        cells.append(f"<td>{format_money(sy['tr']) if sy else '—'}</td>")
        cells.append(f"<td>{format_money(sy['price']) if sy else '—'}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    foot = ['<tr class="total-row"><th>Ending</th>']
    for a in arms:
        foot.append(f"<td>{format_money(a['led'].end_equity)}</td>")
    foot.append(f"<td>{format_money(spy['tr_end'])}</td>")
    foot.append(f"<td>{format_money(spy['price_end'])}</td></tr>")
    return (
        SWIPE_NOTE_HTML
        + '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody><tfoot>"
        + "".join(foot)
        + "</tfoot></table></div>"
    )


def _compare_table(asis: dict[str, Any], miss: dict[str, Any]) -> str:
    rows_a = _metric_rows(asis)
    rows_b = _metric_rows(miss)
    head = (
        _th("Metric", "text")
        + _th("As-is full", "num")
        + _th("As-is in-sample", "num")
        + _th("As-is out-of-sample", "num")
        + _th("Miss top 10% full", "num")
        + _th("Miss top 10% in-sample", "num")
        + _th("Miss top 10% out-of-sample", "num")
        + _th("Full-book delta", "num")
    )
    body = []
    for (lab, kind, af, ai, ao), (_, _, bf, bi, bo) in zip(rows_a, rows_b):
        if kind == "pct":
            delta = _delta_pct(af, bf)
        elif kind == "money":
            delta = format_money_delta(
                (float(bf) - float(af))
                if af is not None and bf is not None
                else None
            )
        elif kind in {"num", "int"}:
            try:
                d = float(bf) - float(af)
                delta = f"{d:+,.2f}" if kind == "num" else f"{int(round(d)):+,}"
            except (TypeError, ValueError):
                delta = "—"
        else:
            delta = "—"
        body.append(
            "<tr><td>"
            + html_mod.escape(lab)
            + "</td>"
            + _td_num(_cell(kind, af))
            + _td_num(_cell(kind, ai))
            + _td_num(_cell(kind, ao))
            + _td_num(_cell(kind, bf))
            + _td_num(_cell(kind, bi))
            + _td_num(_cell(kind, bo))
            + _td_num(delta)
            + "</tr>"
        )
    return (
        SWIPE_NOTE_HTML
        + '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def _exit_table(arms: list[dict[str, Any]]) -> str:
    keys: list[str] = []
    for a in arms:
        for k in (a["stats_full"].get("exits") or {}):
            if k not in keys:
                keys.append(k)
    head = _th("Exit", "text") + "".join(_th(a["label"] + " n", "num") + _th(a["label"] + " %", "num") for a in arms)
    body = []
    for k in sorted(keys):
        cells = [f"<td>{html_mod.escape(k)}</td>"]
        for a in arms:
            exits = a["stats_full"].get("exits") or {}
            n = int(exits.get(k) or 0)
            tot = int(a["stats_full"].get("n") or 0)
            pct = (100.0 * n / tot) if tot else float("nan")
            cells.append(f"<td>{n:,}</td><td>{_fmt_pct(pct)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (
        SWIPE_NOTE_HTML
        + '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def _path_table(arms: list[dict[str, Any]], slices: list[dict[str, Any]], spy: dict[str, Any], asof: date, start: date) -> str:
    spy_cagr = _cagr(float(spy["tr_end"]), 250_000.0, start, asof)
    head = (
        _th("Path", "text")
        + _th("Ending equity", "num")
        + _th("2010", "num")
        + _th("2011", "num")
        + _th("2012", "num")
        + _th("End 2023", "num")
        + _th("Wallet CAGR full", "num")
        + _th("Wallet CAGR in-sample", "num")
        + _th("Wallet CAGR out-of-sample", "num")
        + _th("Wallet max DD", "num")
        + _th("Margin interest", "num")
        + _th("Full fills", "num")
        + _th("Scaled fills", "num")
        + _th("Skipped (buying power)", "num")
        + _th("Name-capped", "num")
        + _th("ADV clipped", "num")
        + _th("ADV skipped", "num")
    )
    body = []
    for a, sl in zip(arms, slices):
        led = a["led"]
        body.append(
            "<tr><td>"
            + html_mod.escape(a["label"])
            + "</td>"
            + f"<td>{format_money(led.end_equity)}</td>"
            + f"<td>{format_money(led.eq_2010)}</td>"
            + f"<td>{format_money(led.eq_2011)}</td>"
            + f"<td>{format_money(led.eq_2012)}</td>"
            + f"<td>{format_money(sl.get('is_end_eq'))}</td>"
            + f"<td>{_fmt_pct(sl.get('full'))}</td>"
            + f"<td>{_fmt_pct(sl.get('is'))}</td>"
            + f"<td>{_fmt_pct(sl.get('oos'))}</td>"
            + f"<td>{_fmt_pct(led.max_dd_pct)}</td>"
            + f"<td>{format_money(led.interest)}</td>"
            + f"<td>{int(led.n_full):,}</td>"
            + f"<td>{int(led.n_scaled):,}</td>"
            + f"<td>{int(led.n_skip_bp):,}</td>"
            + f"<td>{int(led.n_name_capped):,}</td>"
            + f"<td>{int(led.n_adv_clipped):,}</td>"
            + f"<td>{int(led.n_skip_adv):,}</td>"
            + "</tr>"
        )
    body.append(
        "<tr class=\"total-row\"><td>SPY $250k total return</td>"
        + f"<td>{format_money(spy['tr_end'])}</td>"
        + "<td>—</td><td>—</td><td>—</td><td>—</td>"
        + f"<td>{_fmt_pct(spy_cagr)}</td>"
        + "<td>—</td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td></tr>"
    )
    return (
        SWIPE_NOTE_HTML
        + '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def _html(
    asis: dict[str, Any],
    miss: dict[str, Any],
    spy: dict[str, Any],
    meta: dict[str, Any],
    asof: date,
    start: date,
    n_src: int,
) -> str:
    sl_a = _slice_cagr(asis, start, asof)
    sl_b = _slice_cagr(miss, start, asof)
    examples = "".join(
        f"<li>{html_mod.escape(e['system'])} {html_mod.escape(e['symbol'])} "
        f"{html_mod.escape(e['opened'])} {_fmt_pct(e['pnl_pct'])}</li>"
        for e in meta.get("examples") or []
    )
    by = meta.get("by_system") or {}
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>SB + RS + VZ live-style compound</title>
<style>
body {{ font-family: system-ui, Segoe UI, sans-serif; margin: 24px; color: #0f172a; line-height: 1.45; }}
h1 {{ font-size: 1.45rem; margin-bottom: 0.2rem; }}
h2 {{ font-size: 1.15rem; margin-top: 1.6rem; }}
.ask {{ background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 10px; padding: 14px 16px; margin: 16px 0; }}
.note {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 12px 14px; }}
.small {{ color: #475569; font-size: 14px; }}
code {{ background: #f1f5f9; padding: 0 4px; border-radius: 4px; }}
{SORTABLE_TH_CSS}
</style>
</head><body>
<h1>SB, RS, and VZ combined — live-style compound growth</h1>
<p class="small">Research wallet. Not gold. Not DailyRun. Stamp <code>{STAMP}</code>. Through {asof.isoformat()}.</p>

<div class="ask">
<h2 style="margin-top:0">What you asked</h2>
<p>{html_mod.escape(ORIGINAL)}</p>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN)}</p>
</div>

<div class="note">
<p><strong>Freeze.</strong> One $250,000 wallet. Systems: Relative Strength vs SPY (RS), then StockBee (SB), then Volume Zone (VZ), same-day fill order as the investment report. Risk = min(1% of beginning-of-month equity, $50,000). Shares ≤ 1% of 20-session average daily volume (ADV20). One name ≤ 17.5% of current equity. Buying power = 2× equity. Margin interest = 10.5% / 365 on borrowed cash. No $7,500 bank wires. No rotation. Source overlays: <code>risk2500_monthly_20260917</code> house Closed/Open pins ({n_src:,} SB+RS+VZ rows before the deletion).</p>
<p>Annualized rate of return (Ann ROR) in the trade table is the house closed-trade formula on the sized fills, using the $250,000 seed as the cash slot. Wallet compound annual growth rate (CAGR) in the path table is the account’s ending equity versus $250,000 over the calendar. Those are different numbers. In-sample is before 2024-01-01. Out-of-sample is from that date forward and is report-only.</p>
<p>The miss-top-10% arm deletes {meta.get('n_drop', 0):,} of {meta.get('n_winners', 0):,} winning closed trades (about 10% of winners), ranked by percent gain. Cutoff on the last deleted winner: {_fmt_pct(meta.get('cutoff_pct'))}. Best winner in the book: {_fmt_pct(meta.get('best_pct'))}. Deleted by sleeve: SB {by.get('SB', 0):,}, RS {by.get('RS', 0):,}, VZ {by.get('VZ', 0):,}. Losers and open trades stay. This uses the finished gain, so it is look-ahead.</p>
</div>

<h2>Account path</h2>
<p class="small">Click column headers to sort. Swipe sideways to see more columns. Ending equity is the compound result under the lids. A positive max-drawdown figure is the deepest hole.</p>
{_path_table([asis, miss], [sl_a, sl_b], spy, asof, start)}

<h2>Year-end equity vs S&amp;P 500 (SPY)</h2>
<p class="small">SPY total return uses Adjusted Close (dividends reinvested). SPY price only uses Close. Both start at $250,000 on the first trading day on or after 2010-01-01.</p>
{_year_table([asis, miss], spy, asof)}

<h2>Closed fills (house metrics)</h2>
<p class="small">Sized fills only. Ann ROR is the house formula. Max drawdown (Max DD) and Sharpe on this table replay closed-trade dollars on the $250,000 seed. They are not the wallet equity-curve drawdown in the path table. Full-book delta is the miss-top-10% arm minus the as-is arm. Percentage deltas are percentage points.</p>
{_compare_table(asis, miss)}

<h2>Exit mix (full book, sized closes)</h2>
{_exit_table([asis, miss])}

<h2>Largest winners removed</h2>
<p class="small">First 15 of the deleted winners, highest percent gain first.</p>
<ul>{examples}</ul>

<p class="small">Verdict: research only. Do not retune SB, RS, or VZ from the out-of-sample column. Missing the best winners is a stress check, not a new entry rule.</p>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""


def _baseline(meta: dict[str, Any], asof: date, n_src: int) -> str:
    return "\n".join(
        [
            "# SB + RS + VZ live-style compound",
            "",
            f"Stamp: `{STAMP}`",
            "",
            "## Original request",
            "",
            ORIGINAL,
            "",
            "## In plain English",
            "",
            PLAIN,
            "",
            "## Freeze",
            "",
            "- Universe: StockBee (SB) + Relative Strength vs SPY (RS) + Volume Zone (VZ) only.",
            "- Overlays: `drive/paul_experiments/risk2500_monthly_20260917` (`SB_overlay_risk2500.csv`, `RS_overlay_risk2500.csv`, `VZ_overlay_risk2500.csv`).",
            f"- Source rows: {n_src}.",
            "- Start equity $250,000 on 2010-01-01.",
            f"- Through {asof.isoformat()} (engine as-of).",
            "- risk = min(1% beginning-of-month equity, $50,000).",
            "- shares ≤ 1% ADV20. Missing ADV skips the fill.",
            "- name cap 17.5% of current equity.",
            "- leverage 2×, margin 10.5% daily compound on debit.",
            "- withdrawals off, rotation off.",
            "- Fill order: RS then SB then VZ (investment-report order), then symbol.",
            "- Second arm: delete the top 10% of closed winners by `pnl_pct` (count = round(10% of winners)), ex post. Open trades and losers stay.",
            f"- Winners {meta.get('n_winners')}; deleted {meta.get('n_drop')}; cutoff {meta.get('cutoff_pct')}; by system {meta.get('by_system')}.",
            "- In-sample: entry_date < 2024-01-01 for trade metrics; wallet in-sample CAGR uses equity at 2023-12-31.",
            "- Out-of-sample is report-only. No knob was chosen from it.",
            "- Not gold. Not DailyRun.",
            "",
        ]
    )


def main() -> int:
    mod = _load_five()
    static = mod.load_static(SYSTEMS)
    kept, meta = drop_top_winners(static)
    print(
        f"[drop] winners={meta['n_winners']} drop={meta['n_drop']} "
        f"cutoff={meta.get('cutoff_pct')} by={meta.get('by_system')} kept={len(kept)}",
        flush=True,
    )
    asof = mod.ASOF
    start = mod.START
    spy = mod.spy_buyhold(start, asof, seed=250_000.0)
    asis = _run(mod, static, "SB+RS+VZ as-is")
    miss = _run(mod, kept, "SB+RS+VZ miss top 10% winners")
    OUT.mkdir(parents=True, exist_ok=True)
    page = OUT / "report.html"
    page.write_text(
        _html(asis, miss, spy, meta, asof, start, len(static)),
        encoding="utf-8",
    )
    (OUT / "BASELINE.md").write_text(_baseline(meta, asof, len(static)), encoding="utf-8")
    print(f"wrote {page}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
