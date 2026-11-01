#!/usr/bin/env python3
"""Every non-empty mix of the investment-history sleeves, one shared wallet.

As-is, and again after deleting that mix's best 10% of closed trades by count.
Limits apply to the combined account. Research only. Not gold. Not DailyRun.
"""
from __future__ import annotations

import html as html_mod
import importlib.util
import json
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import copy
from datetime import date
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))

from compare_format import format_money, format_money_delta  # noqa: E402
from report_page_extras import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)

STAMP = "all_system_combo_live_style_20261012"
OUT = REPO / "drive" / "paul_experiments" / STAMP
# Investment-report chip order. Indicators (IND) is retired. Weekly Range /
# Swing (WRL) is DailyRun-wired but has no overlay in this freeze.
SYSTEMS = ("BRT", "RL", "YH", "MTS", "WPBR", "RS", "SB", "VZ", "RSI")
NAMES = {
    "BRT": "Break and ReTest (BRT)",
    "RL": "Rocket Launcher (RL)",
    "YH": "Year High (YH)",
    "MTS": "Magic Touch (MTS)",
    "WPBR": "Weekly Pivot Break and Retest (WPBR)",
    "RS": "Relative Strength vs SPY (RS)",
    "SB": "StockBee (SB)",
    "VZ": "Volume Zone (VZ)",
    "RSI": "Relative Strength Index (RSI)",
}
RANK = {s: i for i, s in enumerate(SYSTEMS)}
IS_END = date(2023, 12, 31)
SEED = 250_000.0

ORIGINAL = (
    "Can you run every combination of every system and see what combination "
    "results in the best returns? Both as-is and removing the top 10 trades "
    "across all systems. The limits must be applied to the aggregate of all "
    "systems, not to each individual one. I assume that's what you've been doing. "
    "Correction: this page should show the results after removing the top 10% of "
    "best trades, not the top 10 trades. The fat tail is 10% of winners removed "
    "by count, not the top 10 winners."
)
PLAIN = (
    "Yes. The earlier Relative Strength vs SPY (RS) and Volume Zone (VZ) wallets "
    "were already one account, not a separate pile of money for each system. "
    "This page does that for every mix of the nine sleeves that have a house "
    "overlay. There are 511 mixes. Each one starts at $250,000 in 2010. Each "
    "month the dollars risked on a new buy are 1% of what that one account was "
    "worth at the start of the month, and never more than $50,000. A buy cannot "
    "be more than 1% of the stock's recent daily volume, and one ticker cannot "
    "be more than 17.5% of the account. The account may borrow so stock cost is "
    "at most twice the account, and pays 10.5% a year on the borrowed part. No "
    "money is wired out. The earlier page's second path deleted only the 10 closed "
    "trades with the biggest percent gain. That is not the fat tail. The fat tail "
    "is the best tenth of that mix by count: floor(10% of the closed trades), at "
    "least one when there are 10 or more. Rank is percent gain, best first. Ties "
    "break by the house dollar result, then symbol, then date, so a pile of trades "
    "at the same percent is not all removed. The count is chosen on the full mix, "
    "then the wallet is run again without those trades and scored in full, through "
    "2023, and from 2024 on. Those later rows are not a clean holdout. Out-of-sample "
    "is report-only. The percent gain is known only after the trade is finished, so "
    "this is a what-if, not a rule you could have used on the buy day. Best returns means the highest ending "
    "account value. Searching all 511 mixes on the same history is in-sample "
    "selection. Weekly Range / Swing (WRL) is on DailyRun but has no overlay in "
    "this freeze, so it is left out. Nothing here is gold and nothing is wired "
    "into DailyRun."
)

_MOD: Any = None
_BY: dict[str, list[Any]] = {}


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


def _init_worker() -> None:
    global _MOD, _BY
    _MOD = _load_five()
    grouped: dict[str, list[Any]] = {s: [] for s in SYSTEMS}
    for t in _MOD.load_static(SYSTEMS):
        grouped[t.system].append(t)
    _BY = grouped


def _cagr(end_eq: float, start_eq: float, start: date, end: date) -> Optional[float]:
    years = (end - start).days / 365.25
    if years <= 0 or start_eq <= 0 or end_eq <= 0:
        return None
    return ((end_eq / start_eq) ** (1.0 / years) - 1.0) * 100.0


def _eq_on_or_before(snaps: list[Any], day: date) -> Optional[float]:
    best = None
    best_d = None
    for s in snaps:
        month = int(s.month)
        year = int(s.year)
        mend = date(year, 12, 31) if month == 12 else date.fromordinal(
            date(year, month + 1, 1).toordinal() - 1
        )
        if mend <= day and (best_d is None or mend > best_d):
            best_d = mend
            best = float(s.equity_end)
    return best


def _clean(v: Any) -> Any:
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    try:
        x = float(v)
    except (TypeError, ValueError):
        return str(v)
    if not math.isfinite(x):
        return None
    return x


def _stat_pack(stats: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "n",
        "wins",
        "losses",
        "win_pct",
        "avg_pnl_pct",
        "avg_wo_max",
        "expectancy_pct",
        "expectancy_dol",
        "avg_win_pct",
        "avg_loss_pct",
        "wl_count",
        "wl_dol",
        "pf",
        "ann_ror",
        "max_dd",
        "calmar",
        "sharpe",
        "profit_per_cap_day",
        "capital_days",
        "avg_days",
        "median_days",
        "p90_days",
        "losing_streak",
        "avg_pos",
        "max_pos",
        "mean_notional",
        "exits",
    )
    return {k: _clean(stats.get(k)) for k in keys}


def _simulate(trades: list[Any], start: date, asof: date) -> dict[str, Any]:
    assert _MOD is not None
    sized, snaps, led = _MOD.run_wallet(
        [copy(t) for t in trades],
        rank=RANK,
        rotate="none",
        withdraw=False,
        through=asof,
        risk_frac=0.01,
        name_cap_frac=0.175,
        max_risk_dollar=50_000.0,
        adv_frac=0.01,
        start_equity=SEED,
    )
    closed = [t for t in sized if t.status == "closed"]
    is_end = _eq_on_or_before(snaps, IS_END)
    end_eq = float(led.end_equity)
    return {
        "end_eq": end_eq,
        "is_end_eq": is_end,
        "cagr_full": _cagr(end_eq, SEED, start, asof),
        "cagr_is": _cagr(is_end, SEED, start, IS_END) if is_end else None,
        "cagr_oos": _cagr(end_eq, is_end, date(2024, 1, 1), asof) if is_end else None,
        "max_dd": float(led.max_dd_pct),
        "interest": float(led.interest),
        "n_full": int(led.n_full),
        "n_scaled": int(led.n_scaled),
        "n_skip_bp": int(led.n_skip_bp),
        "n_name_capped": int(led.n_name_capped),
        "n_adv_clipped": int(led.n_adv_clipped),
        "full": _stat_pack(_MOD._stats_wallet(closed, cash=SEED)),
        "is": _stat_pack(_MOD._stats_wallet(_MOD.r.slice_trades(closed, "IS"), cash=SEED)),
        "oos": _stat_pack(_MOD._stats_wallet(_MOD.r.slice_trades(closed, "OOS"), cash=SEED)),
    }


def _drop_best_tenth(trades: list[Any]) -> tuple[list[Any], dict[str, Any]]:
    """Drop floor(10% of closed trades) by percent gain. Ties: dollars, symbol, date."""
    closed = [t for t in trades if t.status == "closed" and t.pnl_pct is not None]
    n = len(closed)
    k = int(math.floor(0.10 * n))
    if n >= 10:
        k = max(k, 1)

    def _key(t: Any) -> tuple:
        pct = float(t.pnl_pct)
        dol = float(t.house_pnl) if t.house_pnl is not None else 0.0
        return (-pct, -dol, str(t.symbol), t.opened.isoformat(), str(t.system))

    ranked = sorted(closed, key=_key)
    dropped = ranked[:k] if k else []
    drop_ids = {id(t) for t in dropped}
    kept = [t for t in trades if id(t) not in drop_ids]
    by: dict[str, int] = {}
    for t in dropped:
        by[t.system] = by.get(t.system, 0) + 1
    return kept, {
        "n_closed": n,
        "n_drop": len(dropped),
        "pct_drop": (100.0 * len(dropped) / n) if n else 0.0,
        "cutoff_pct": float(dropped[-1].pnl_pct) if dropped else None,
        "by_system": by,
        "examples": [
            {
                "system": t.system,
                "symbol": t.symbol,
                "opened": t.opened.isoformat(),
                "pnl_pct": float(t.pnl_pct),
            }
            for t in dropped[:12]
        ],
    }


def _run_mask(mask: int) -> dict[str, Any]:
    assert _MOD is not None
    chosen = [SYSTEMS[i] for i in range(len(SYSTEMS)) if mask & (1 << i)]
    trades: list[Any] = []
    for s in chosen:
        trades.extend(_BY[s])
    kept, meta = _drop_best_tenth(trades)
    start = _MOD.START
    asof = _MOD.ASOF
    return {
        "combo": "+".join(chosen),
        "systems": chosen,
        "n_sys": len(chosen),
        "n_src": len(trades),
        "drop": meta,
        "asis": _simulate(trades, start, asof),
        "miss": _simulate(kept, start, asof),
    }


def _th(label: str, typ: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{typ}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


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


def _cell(kind: str, v: Any) -> str:
    if v is None:
        return "—"
    if kind == "money":
        return format_money(v)
    if kind == "pct":
        return _fmt_pct(v)
    if kind == "int":
        try:
            return f"{int(v):,}"
        except (TypeError, ValueError):
            return "—"
    return _fmt_num(v)


def _best(rows: list[dict[str, Any]], arm: str, key: str) -> dict[str, Any]:
    def sort_key(row: dict[str, Any]) -> tuple:
        val = row[arm].get(key)
        missing = val is None
        return (missing, -(float(val) if val is not None else 0.0), row["n_sys"], row["combo"])

    return sorted(rows, key=sort_key)[0]


def _wallet_table(rows: list[dict[str, Any]]) -> str:
    head = (
        _th("Mix", "text")
        + _th("Sleeves", "num")
        + _th("Source trades", "num")
        + _th("N dropped", "num")
        + _th("% dropped", "num")
        + _th("As-is ending equity", "num")
        + _th("As-is wallet CAGR full", "num")
        + _th("As-is wallet CAGR in-sample", "num")
        + _th("As-is wallet CAGR out-of-sample", "num")
        + _th("As-is wallet max DD", "num")
        + _th("As-is margin interest", "num")
        + _th("As-is full fills", "num")
        + _th("As-is skipped (buying power)", "num")
        + _th("Without best 10% ending equity", "num")
        + _th("Without best 10% wallet CAGR full", "num")
        + _th("Without best 10% wallet CAGR in-sample", "num")
        + _th("Without best 10% wallet CAGR out-of-sample", "num")
        + _th("Without best 10% wallet max DD", "num")
        + _th("Without best 10% margin interest", "num")
        + _th("Ending equity delta", "num")
    )
    body = []
    for row in rows:
        a, m = row["asis"], row["miss"]
        delta = None
        if a.get("end_eq") is not None and m.get("end_eq") is not None:
            delta = float(m["end_eq"]) - float(a["end_eq"])
        cells = [
            html_mod.escape(row["combo"]),
            f"{row['n_sys']}",
            f"{row['n_src']:,}",
            f"{int(row['drop'].get('n_drop') or 0):,}",
            _fmt_pct(row["drop"].get("pct_drop")),
            format_money(a.get("end_eq")),
            _fmt_pct(a.get("cagr_full")),
            _fmt_pct(a.get("cagr_is")),
            _fmt_pct(a.get("cagr_oos")),
            _fmt_pct(a.get("max_dd")),
            format_money(a.get("interest")),
            f"{int(a.get('n_full') or 0):,}",
            f"{int(a.get('n_skip_bp') or 0):,}",
            format_money(m.get("end_eq")),
            _fmt_pct(m.get("cagr_full")),
            _fmt_pct(m.get("cagr_is")),
            _fmt_pct(m.get("cagr_oos")),
            _fmt_pct(m.get("max_dd")),
            format_money(m.get("interest")),
            format_money_delta(delta),
        ]
        body.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    return (
        SWIPE_NOTE_HTML
        + '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def _house_table(rows: list[dict[str, Any]]) -> str:
    head = (
        _th("Mix", "text")
        + _th("As-is closed", "num")
        + _th("As-is win %", "num")
        + _th("As-is avg PnL %", "num")
        + _th("As-is avg PnL % without best", "num")
        + _th("As-is profit factor", "num")
        + _th("As-is Ann ROR full", "num")
        + _th("As-is Ann ROR in-sample", "num")
        + _th("As-is Ann ROR out-of-sample", "num")
        + _th("As-is Max DD", "num")
        + _th("As-is Calmar", "num")
        + _th("As-is Sharpe", "num")
        + _th("Without best 10% closed", "num")
        + _th("Without best 10% win %", "num")
        + _th("Without best 10% avg PnL %", "num")
        + _th("Without best 10% profit factor", "num")
        + _th("Without best 10% Ann ROR full", "num")
        + _th("Without best 10% Ann ROR in-sample", "num")
        + _th("Without best 10% Ann ROR out-of-sample", "num")
        + _th("Without best 10% Max DD", "num")
        + _th("Without best 10% Calmar", "num")
        + _th("Without best 10% Sharpe", "num")
    )
    body = []
    for row in rows:
        af, mf = row["asis"]["full"], row["miss"]["full"]
        ai, mi = row["asis"]["is"], row["miss"]["is"]
        ao, mo = row["asis"]["oos"], row["miss"]["oos"]
        vals = [
            html_mod.escape(row["combo"]),
            _cell("int", af.get("n")),
            _fmt_pct(af.get("win_pct")),
            _fmt_pct(af.get("avg_pnl_pct")),
            _fmt_pct(af.get("avg_wo_max")),
            _fmt_num(af.get("pf")),
            _fmt_pct(af.get("ann_ror")),
            _fmt_pct(ai.get("ann_ror")),
            _fmt_pct(ao.get("ann_ror")),
            _fmt_pct(af.get("max_dd")),
            _fmt_num(af.get("calmar")),
            _fmt_num(af.get("sharpe")),
            _cell("int", mf.get("n")),
            _fmt_pct(mf.get("win_pct")),
            _fmt_pct(mf.get("avg_pnl_pct")),
            _fmt_num(mf.get("pf")),
            _fmt_pct(mf.get("ann_ror")),
            _fmt_pct(mi.get("ann_ror")),
            _fmt_pct(mo.get("ann_ror")),
            _fmt_pct(mf.get("max_dd")),
            _fmt_num(mf.get("calmar")),
            _fmt_num(mf.get("sharpe")),
        ]
        body.append("<tr>" + "".join(f"<td>{c}</td>" for c in vals) + "</tr>")
    return (
        SWIPE_NOTE_HTML
        + '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


_FOCUS_METRICS = [
    ("Closed fills", "int", "n"),
    ("Wins", "int", "wins"),
    ("Losses", "int", "losses"),
    ("Win %", "pct", "win_pct"),
    ("Avg PnL %", "pct", "avg_pnl_pct"),
    ("Avg PnL % without best trade", "pct", "avg_wo_max"),
    ("Expectancy %", "pct", "expectancy_pct"),
    ("Expectancy $", "money", "expectancy_dol"),
    ("Avg win %", "pct", "avg_win_pct"),
    ("Avg loss %", "pct", "avg_loss_pct"),
    ("Win/loss count", "num", "wl_count"),
    ("Win/loss $", "num", "wl_dol"),
    ("Profit factor", "num", "pf"),
    ("Ann ROR %", "pct", "ann_ror"),
    ("Max DD %", "pct", "max_dd"),
    ("Calmar", "num", "calmar"),
    ("Sharpe", "num", "sharpe"),
    ("Profit / capital day", "money", "profit_per_cap_day"),
    ("Capital days", "num", "capital_days"),
    ("Avg days held", "num", "avg_days"),
    ("Median days held", "num", "median_days"),
    ("P90 days held", "num", "p90_days"),
    ("Losing streak", "int", "losing_streak"),
    ("Avg positions", "num", "avg_pos"),
    ("Max positions", "int", "max_pos"),
    ("Mean notional", "money", "mean_notional"),
]


def _focus_table(focus: list[tuple[str, dict[str, Any], str]]) -> str:
    """focus items: (label, row, arm) arm is asis or miss."""
    head = _th("Metric", "text")
    for lab, _row, _arm in focus:
        head += _th(lab + " full", "num") + _th(lab + " in-sample", "num") + _th(lab + " out-of-sample", "num")
    body = []
    for title, kind, key in _FOCUS_METRICS:
        cells = [f"<td>{html_mod.escape(title)}</td>"]
        for _lab, row, arm in focus:
            pack = row[arm]
            for sl in ("full", "is", "oos"):
                cells.append(f"<td>{_cell(kind, pack[sl].get(key))}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    # wallet rows
    for title, key, kind in (
        ("Wallet ending equity", "end_eq", "money"),
        ("Wallet equity end 2023", "is_end_eq", "money"),
        ("Wallet CAGR", "cagr_full", "pct"),
        ("Wallet max DD", "max_dd", "pct"),
        ("Margin interest", "interest", "money"),
    ):
        cells = [f"<td>{html_mod.escape(title)}</td>"]
        for _lab, row, arm in focus:
            pack = row[arm]
            if key == "cagr_full":
                cells.append(f"<td>{_cell('pct', pack.get('cagr_full'))}</td>")
                cells.append(f"<td>{_cell('pct', pack.get('cagr_is'))}</td>")
                cells.append(f"<td>{_cell('pct', pack.get('cagr_oos'))}</td>")
            elif key in {"end_eq", "max_dd", "interest"}:
                cells.append(f"<td>{_cell(kind, pack.get(key))}</td><td>—</td><td>—</td>")
            else:
                cells.append(f"<td>{_cell(kind, pack.get(key))}</td><td>—</td><td>—</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (
        SWIPE_NOTE_HTML
        + '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def _exit_table(focus: list[tuple[str, dict[str, Any], str]]) -> str:
    keys: list[str] = []
    for _lab, row, arm in focus:
        for k in (row[arm]["full"].get("exits") or {}):
            if k not in keys:
                keys.append(k)
    head = _th("Exit", "text")
    for lab, _row, _arm in focus:
        head += _th(lab + " n", "num") + _th(lab + " %", "num")
    body = []
    for k in sorted(keys):
        cells = [f"<td>{html_mod.escape(str(k))}</td>"]
        for _lab, row, arm in focus:
            exits = row[arm]["full"].get("exits") or {}
            n = int(exits.get(k) or 0)
            tot = int(row[arm]["full"].get("n") or 0)
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


def _examples(meta: dict[str, Any]) -> str:
    items = []
    for e in meta.get("examples") or []:
        items.append(
            f"<li>{html_mod.escape(e['system'])} {html_mod.escape(e['symbol'])} "
            f"{html_mod.escape(e['opened'])} {_fmt_pct(e['pnl_pct'])}</li>"
        )
    return "<ul>" + "".join(items) + "</ul>"


def _html(
    rows: list[dict[str, Any]],
    spy: dict[str, Any],
    asof: date,
    counts: dict[str, int],
    focus: list[tuple[str, dict[str, Any], str]],
) -> str:
    best_as = _best(rows, "asis", "end_eq")
    best_miss = _best(rows, "miss", "end_eq")
    best_is = _best(rows, "asis", "is_end_eq")
    nine = next(r for r in rows if r["n_sys"] == len(SYSTEMS))
    names = ", ".join(NAMES[s] for s in SYSTEMS)
    count_bits = ", ".join(f"{s} {counts[s]:,}" for s in SYSTEMS)
    spy_cagr = _cagr(float(spy["tr_end"]), SEED, date(2010, 1, 1), asof)
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>All system mixes — live-style compound</title>
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
<h1>Every system mix — one shared live-style wallet</h1>
<p class="small">Research search. Not gold. Not DailyRun. Stamp <code>{STAMP}</code>. Through {asof.isoformat()}. {len(rows):,} mixes.</p>

<div class="ask">
<h2 style="margin-top:0">What you asked</h2>
<p>{html_mod.escape(ORIGINAL)}</p>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN)}</p>
</div>

<div class="note">
<p><strong>The limits are on the combined account.</strong> That is what the RS and VZ report did, and what this grid does. Risk, the $50,000 ceiling, the volume clip, the 17.5% name cap, and the 2× buying power all see one wallet. They are not applied separately inside each system and then added up.</p>
<p><strong>Best as-is ending equity:</strong> {html_mod.escape(best_as['combo'])} ends at {format_money(best_as['asis']['end_eq'])}, wallet compound annual growth rate (CAGR) {_fmt_pct(best_as['asis']['cagr_full'])} (in-sample {_fmt_pct(best_as['asis']['cagr_is'])}, out-of-sample {_fmt_pct(best_as['asis']['cagr_oos'])}), wallet max drawdown {_fmt_pct(best_as['asis']['max_dd'])}.</p>
<p><strong>Best ending equity after deleting that mix's best 10% of trades by count:</strong> {html_mod.escape(best_miss['combo'])} ends at {format_money(best_miss['miss']['end_eq'])}, wallet CAGR {_fmt_pct(best_miss['miss']['cagr_full'])} (in-sample {_fmt_pct(best_miss['miss']['cagr_is'])}, out-of-sample {_fmt_pct(best_miss['miss']['cagr_oos'])}), wallet max drawdown {_fmt_pct(best_miss['miss']['max_dd'])}.</p>
<p><strong>Best as-is equity at the end of 2023</strong> (the in-sample wallet, before any 2024 result): {html_mod.escape(best_is['combo'])} at {format_money(best_is['asis']['is_end_eq'])}. Picking the full-history winner from all {len(rows):,} mixes is in-sample selection. Out-of-sample is report-only. Do not retune a sleeve because a mix won this search.</p>
<p>All nine sleeves together end at {format_money(nine['asis']['end_eq'])} as-is and {format_money(nine['miss']['end_eq'])} after their own best 10% by count are removed. S&amp;P 500 (SPY) total return on $250,000 ends at {format_money(spy['tr_end'])}, wallet-style CAGR {_fmt_pct(spy_cagr)}.</p>
<p><strong>Freeze.</strong> Sleeves: {html_mod.escape(names)}. Source rows: {html_mod.escape(count_bits)}. Overlays from <code>risk2500_monthly_20260917</code>. Relative Strength Index (RSI) uses the in-sample average-loss slot (<code>RSI_overlay_avgloss.csv</code>), not the fake-stop overlay. Same-day fills follow investment-report order, then ticker. Start $250,000. No bank wires. No rotation. Left out: Indicators (IND), retired; Weekly Range / Swing (WRL), no overlay in this freeze.</p>
<p>Annualized rate of return (Ann ROR) is the house closed-trade formula on the sized fills, using the $250,000 seed as the cash slot. Wallet CAGR is the account’s ending equity versus $250,000 over the calendar. Those are different numbers. On this freeze every mix shares the same start date, seed, and end date, so full-period wallet CAGR ranks the same way as ending equity. In-sample is an entry before 2024-01-01 for trade metrics. Wallet in-sample CAGR uses equity at 2023-12-31. A positive max-drawdown figure is the deepest hole. The house Max DD replays closed-trade dollars on the $250,000 seed. It is not the wallet equity-curve drawdown.</p>
</div>

<h2>Highlighted mixes</h2>
<p class="small">Click column headers to sort. Swipe sideways to see more columns. These are the full-history winner, the end-2023 winner, the miss-top-10 winner, and all nine sleeves. If two titles land on the same mix, the column still appears twice.</p>
{_focus_table(focus)}

<h2>Exit mix on the highlighted books</h2>
{_exit_table(focus)}

<h2>Best 10% removed from the full-history as-is winner</h2>
<p class="small">{html_mod.escape(best_as['combo'])}. Trades removed {best_as['drop'].get('n_drop')} of {best_as['drop'].get('n_closed')} ({_fmt_pct(best_as['drop'].get('pct_drop'))}). Lowest percent still removed: {_fmt_pct(best_as['drop'].get('cutoff_pct'))}. By sleeve: {html_mod.escape(json.dumps(best_as['drop'].get('by_system') or {}))}.</p>
{_examples(best_as['drop'])}

<h2>Best 10% removed from all nine sleeves</h2>
<p class="small">Trades removed {nine['drop'].get('n_drop')} of {nine['drop'].get('n_closed')} ({_fmt_pct(nine['drop'].get('pct_drop'))}). Lowest percent still removed: {_fmt_pct(nine['drop'].get('cutoff_pct'))}. By sleeve: {html_mod.escape(json.dumps(nine['drop'].get('by_system') or {}))}.</p>
{_examples(nine['drop'])}

<h2>Every mix — account path</h2>
<p class="small">Sorted here by as-is ending equity, highest first. Click a header to resort. Ending-equity delta is the account without the best 10% minus the as-is account.</p>
{_wallet_table(rows)}

<h2>Every mix — sized closes</h2>
<p class="small">House metrics on the fills the wallet actually took. Ann ROR uses the $250,000 slot.</p>
{_house_table(rows)}

<p class="small">Verdict: research search only. The winning mix was chosen by looking at all {len(rows):,} results on this history. That is not a walk-forward test and it is not a reason to drop a sleeve from DailyRun.</p>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""


def _baseline(rows: list[dict[str, Any]], asof: date, counts: dict[str, int]) -> str:
    best_as = _best(rows, "asis", "end_eq")
    best_miss = _best(rows, "miss", "end_eq")
    best_is = _best(rows, "asis", "is_end_eq")
    return "\n".join(
        [
            "# All system mixes, one live-style wallet",
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
            f"- Sleeves: {', '.join(NAMES[s] for s in SYSTEMS)}.",
            "- Left out: Indicators (IND), retired. Weekly Range / Swing (WRL), DailyRun-wired, no overlay in `risk2500_monthly_20260917`.",
            f"- Source rows: {counts}.",
            "- One wallet per mix. Limits are on that wallet, not per sleeve.",
            "- risk = min(1% beginning-of-month equity, $50,000).",
            "- shares ≤ 1% of 20-session average daily volume. Missing volume skips the fill.",
            "- one name ≤ 17.5% of current equity.",
            "- buying power 2×. Margin interest 10.5% / 365 on borrowed cash.",
            "- withdrawals off, rotation off.",
            "- Fill order: investment-report order, then symbol.",
            "- RSI overlay: `RSI_overlay_avgloss.csv` (in-sample average-loss slot).",
            "- Other sleeves: `{SYS}_overlay_risk2500.csv`.",
            f"- Through {asof.isoformat()}. Start 2010-01-01. Seed $250,000.",
            "- Second arm: on each mix, drop floor(10% of closed trades) with the highest pnl_pct. Ties break by house_pnl, then symbol, then date. At least 1 trade when the mix has 10 or more closed trades. Open trades stay. The count is chosen on the full mix, so IS/OOS of the leftover book are not a clean holdout.",
            f"- Mixes: {len(rows)} = 2^{len(SYSTEMS)}−1.",
            f"- Best as-is ending equity: {best_as['combo']} {best_as['asis']['end_eq']}.",
            f"- Best without-best-10% ending equity: {best_miss['combo']} {best_miss['miss']['end_eq']}.",
            f"- Best as-is equity at 2023-12-31: {best_is['combo']} {best_is['asis']['is_end_eq']}.",
            "- Ranking metric: ending equity. Full-period wallet CAGR ranks the same way because start, seed, and end date are shared.",
            "- Out-of-sample is report-only. The search itself is in-sample selection.",
            "- Not gold. Not DailyRun.",
            "",
        ]
    )


def main() -> int:
    mod = _load_five()
    counts: dict[str, int] = {}
    for s, rows_s in (
        (s, [t for t in mod.load_static((s,))]) for s in SYSTEMS
    ):
        counts[s] = len(rows_s)
    print("[counts]", counts, "total", sum(counts.values()), flush=True)
    masks = list(range(1, 1 << len(SYSTEMS)))
    workers = max(1, (os.cpu_count() or 4) - 1)
    print(f"[pool] mixes={len(masks)} workers={workers}", flush=True)
    rows: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker) as pool:
        futs = [pool.submit(_run_mask, m) for m in masks]
        done = 0
        for fut in as_completed(futs):
            rows.append(fut.result())
            done += 1
            if done % 25 == 0 or done == len(masks):
                print(f"[progress] {done}/{len(masks)}", flush=True)
    rows.sort(key=lambda r: (-float(r["asis"]["end_eq"]), r["n_sys"], r["combo"]))
    asof = mod.ASOF
    spy = mod.spy_buyhold(mod.START, asof, seed=SEED)
    best_as = _best(rows, "asis", "end_eq")
    best_miss = _best(rows, "miss", "end_eq")
    best_is = _best(rows, "asis", "is_end_eq")
    nine = next(r for r in rows if r["n_sys"] == len(SYSTEMS))
    focus = [
        (f"Best as-is {best_as['combo']}", best_as, "asis"),
        (f"Best end-2023 {best_is['combo']}", best_is, "asis"),
        (f"Best without best 10% {best_miss['combo']}", best_miss, "miss"),
        ("All nine as-is", nine, "asis"),
        ("All nine without best 10%", nine, "miss"),
    ]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(rows), encoding="utf-8")
    page = OUT / "report.html"
    page.write_text(_html(rows, spy, asof, counts, focus), encoding="utf-8")
    (OUT / "BASELINE.md").write_text(_baseline(rows, asof, counts), encoding="utf-8")
    print(
        f"[best as-is] {best_as['combo']} {best_as['asis']['end_eq']:.2f}",
        flush=True,
    )
    print(
        f"[best miss] {best_miss['combo']} {best_miss['miss']['end_eq']:.2f}",
        flush=True,
    )
    print(
        f"[best is] {best_is['combo']} {best_is['asis']['is_end_eq']}",
        flush=True,
    )
    print(f"wrote {page}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
