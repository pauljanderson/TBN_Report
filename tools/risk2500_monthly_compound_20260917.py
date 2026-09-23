#!/usr/bin/env python3
"""Beginning-of-month 1% compound size overlay (research only).

Control stays drive/paul_experiments/risk2500_monthly_20260917/monthly.html
(static $2,500; RSI = IS avg-loss slot). This writes monthly_compound.html.

One knob: risk_dollar = 0.01 × start-of-month equity (paper $250k).
Two books: per-system sleeves + one shared $250k account.
RSI invested = risk_dollar / 0.06509607 (IS 6.51% freeze). Not DailyRun.
"""
from __future__ import annotations

import html as html_mod
import importlib.util
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))

from compare_format import (  # noqa: E402
    format_money,
    format_money_delta,
    is_excluded_html_compare_label,
)

_SPEC = importlib.util.spec_from_file_location(
    "risk2500_monthly_20260917",
    REPO / "tools" / "risk2500_monthly_20260917.py",
)
r = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules["risk2500_monthly_20260917"] = r
_SPEC.loader.exec_module(r)

STAMP = r.STAMP
OUT_DIR = r.OUT_DIR
ACCOUNT = r.ACCOUNT
RISK_FRAC = 0.01
# Frozen IS avg |loss| from the static stamp — do not retune on OOS.
RSI_AVG_LOSS_PCT_FREEZE = 6.509607046979868
RSI_AVG_LOSS_FRAC = RSI_AVG_LOSS_PCT_FREEZE / 100.0
ASOF = r.ASOF
SYSTEMS = r.SYSTEMS
SYSTEM_EXPAND = r.SYSTEM_EXPAND
ET = r.ET
IS_CUT = r.IS_CUT

COMPOUND_REQUEST = (
    "cool. thank you. what would this look like if you recalculated the 1% "
    "at the beginning of each month based on how much the account grew. for "
    "example, if we started out with $250k, at the end of 2010, we would have "
    "ended up with 450k and our new 1% would be $4,500. etc."
)
COMPOUND_PLAIN = (
    "Same DailyRun trades as the static $2,500 monthly you already liked. "
    "The only change: each paper account starts at $250,000, and on the first "
    "day of every month we reset the 1% dollar risk to 1% of whatever that "
    "account is worth after trades that already closed. If a sleeve finished "
    "2010 at $450,000, every new January 2011 fill would risk $4,500 — not "
    "$2,500. Risk does not change mid-month when a trade closes. Stop systems "
    "still use shares = that month’s 1% ÷ (entry − stop). Relative Strength "
    "Index (RSI) still uses the In-Sample (IS) average-loser freeze 6.51% "
    "(do not retune after 2024): dollars invested = that month’s 1% ÷ 0.0651, "
    "so a typical loser is about that month’s 1%. Two books: (1) each system "
    "is its own $250k sleeve — that is the monthly table, same columns as "
    "before; (2) one shared $250k “my account” where every DailyRun overlay "
    "trade shares one equity and one monthly 1%. Open names each still get "
    "that full 1%, so book risk stacks. Same-day fills sort by symbol, then "
    "system — size is already frozen for the month, so order does not change "
    "shares. Dollar totals will look bigger later because winners buy more. "
    "That is path-dependence, not a new edge, if Avg PnL % stays the same."
)


@dataclass
class MonthSnap:
    year: int
    month: int
    equity_start: float
    risk_dollar: float
    realized_pnl: float
    equity_end: float
    n_entries: int
    n_closes: int


def _month_range(start: date, end: date) -> list[tuple[int, int]]:
    y, m = start.year, start.month
    out: list[tuple[int, int]] = []
    while (y, m) <= (end.year, end.month):
        out.append((y, m))
        m += 1
        if m == 13:
            m = 1
            y += 1
    return out


def apply_compound_size(t: r.OverlayTrade, risk_dollar: float, equity_bom: float) -> r.OverlayTrade:
    extra = {"risk_dollar": float(risk_dollar), "equity_bom": float(equity_bom)}
    if t.system == "RSI":
        slot = float(risk_dollar) / RSI_AVG_LOSS_FRAC
        st = r.apply_equal_slot(
            t,
            slot,
            src=f"rsi_compound_avgloss:{RSI_AVG_LOSS_PCT_FREEZE:.6f}pct;risk={risk_dollar:.2f}",
        )
        return r.OverlayTrade(**{**st.__dict__, **extra})
    shares, invested, sized, why = r.size_from_stop(t.entry, t.stop_used, risk_dollar)
    overlay_pnl = (t.pnl_pct / 100.0) * invested if sized else 0.0
    return r.OverlayTrade(
        **{
            **t.__dict__,
            **extra,
            "shares": shares,
            "invested": invested,
            "overlay_pnl": overlay_pnl,
            "sized": sized,
            "skip_reason": "" if sized else (t.skip_reason or why),
            "stop_src": t.stop_src if sized else (t.stop_src or why),
        }
    )


def run_compound_book(trades: list[r.OverlayTrade]) -> tuple[list[r.OverlayTrade], list[MonthSnap]]:
    if not trades:
        return [], []
    dates = [t.opened for t in trades]
    dates.extend(t.closed for t in trades if t.closed)
    first, last = min(dates), max(dates)
    months = _month_range(date(first.year, first.month, 1), date(last.year, last.month, 1))
    by_entry: dict[tuple[int, int], list[r.OverlayTrade]] = defaultdict(list)
    for t in trades:
        by_entry[(t.opened.year, t.opened.month)].append(t)

    equity = ACCOUNT
    out: list[r.OverlayTrade] = []
    snaps: list[MonthSnap] = []
    for y, m in months:
        risk = RISK_FRAC * equity
        month_entries = list(by_entry.get((y, m), []))
        month_entries.sort(key=lambda t: (t.opened, t.symbol, t.system))
        for t in month_entries:
            out.append(apply_compound_size(t, risk, equity))
        realized = 0.0
        n_closes = 0
        for t in out:
            if t.sized and t.closed and t.closed.year == y and t.closed.month == m:
                realized += t.overlay_pnl
                n_closes += 1
        equity_end = equity + realized
        snaps.append(
            MonthSnap(
                year=y,
                month=m,
                equity_start=equity,
                risk_dollar=risk,
                realized_pnl=realized,
                equity_end=equity_end,
                n_entries=len(month_entries),
                n_closes=n_closes,
            )
        )
        equity = equity_end
    return out, snaps


def year_end_rows(snaps: list[MonthSnap], *, through: date) -> list[dict[str, Any]]:
    """Calendar years from 2010 (Paul example) through as-of. Idle years stay $250k."""
    by_year: dict[int, list[MonthSnap]] = defaultdict(list)
    for s in snaps:
        by_year[s.year].append(s)
    start_y = 2010
    end_y = through.year
    last_eq = ACCOUNT
    rows: list[dict[str, Any]] = []
    for y in range(start_y, end_y + 1):
        ys = by_year.get(y)
        if ys:
            last_eq = ys[-1].equity_end
            jan_risk = ys[0].risk_dollar
            jan_eq = ys[0].equity_start
            realized = sum(s.realized_pnl for s in ys)
        else:
            jan_risk = RISK_FRAC * last_eq
            jan_eq = last_eq
            realized = 0.0
        note = ""
        if y == through.year and (through.month < 12 or through.day < 31):
            note = f"realized through {through.isoformat()} (year not finished)"
        rows.append(
            {
                "year": y,
                "ending_equity": last_eq,
                "next_1pct": RISK_FRAC * last_eq,
                "jan_1pct": jan_risk,
                "jan_equity": jan_eq,
                "realized": realized,
                "note": note,
            }
        )
    return rows


def _stats(trades: list[r.OverlayTrade]) -> dict[str, Any]:
    closed = [t for t in trades if t.status == "closed"]
    sized = [t for t in closed if t.sized]
    mean_ov = (sum(t.invested for t in sized) / len(sized)) if sized else r.RISK_DOLLARS
    return r.book_stats(
        closed,
        use_overlay=True,
        cash_ann=float(mean_ov),
        dd_seed=ACCOUNT,
    )


def _verdict_compound(static: dict[str, Any], compound: dict[str, Any]) -> str:
    if not compound.get("n"):
        return "HOLD — compound N=0"
    avg_s = static.get("avg_pnl_pct")
    avg_c = compound.get("avg_pnl_pct")
    wr_s = static.get("win_pct")
    wr_c = compound.get("win_pct")
    pct_flat = (
        avg_s is not None
        and avg_c is not None
        and abs(float(avg_s) - float(avg_c)) < 0.20
        and wr_s is not None
        and wr_c is not None
        and abs(float(wr_s) - float(wr_c)) < 0.25
    )
    if pct_flat:
        return (
            "HOLD — Avg PnL % and win % match the static $2,500 book. "
            "Bigger later dollars are path-dependence (winners buy more), not extra edge. "
            "Not gold. Not DailyRun."
        )
    dd_d = r._delta(compound.get("max_dd"), static.get("max_dd"))
    if dd_d is not None and dd_d <= -1.0 and pct_flat:
        return "HOLD — drawdown mix not worse; still a size path, not an adopt"
    return (
        "HOLD — research monthly-step 1% path. Judge % quality, not dollar totals. "
        "Not gold. Not DailyRun."
    )


def _static_book(sys: str) -> list[r.OverlayTrade]:
    if sys == "RSI":
        path = OUT_DIR / "RSI_overlay_avgloss.csv"
        if not path.is_file():
            raise SystemExit("missing RSI_overlay_avgloss.csv — need IS avg-loss freeze")
        return r.load_overlay_csv(path)
    return r.load_overlay_csv(OUT_DIR / f"{sys}_overlay_risk2500.csv")


def _year_table(rows: list[dict[str, Any]], *, caption: str) -> str:
    head = "".join(
        r._sortable_th(h, t)
        for h, t in (
            ("Year-end", "num"),
            ("Ending equity (realized)", "num"),
            ("That year’s Jan 1%", "num"),
            ("Next Jan 1% (1% of year-end)", "num"),
            ("Realized $ that year", "num"),
            ("Note", "text"),
        )
    )
    body = ""
    for row in rows:
        body += (
            "<tr>"
            f"<td>{row['year']}</td>"
            f"<td>{format_money(row['ending_equity'])}</td>"
            f"<td>{format_money(row['jan_1pct'])}</td>"
            f"<td>{format_money(row['next_1pct'])}</td>"
            f"<td class=\"{r._pnl_class(row['realized'])}\">{r._fmt_money_signed(row['realized'])}</td>"
            f"<td class=\"small\">{html_mod.escape(row['note'])}</td>"
            "</tr>"
        )
    return (
        f"<p class=\"small\">{html_mod.escape(caption)} Click headers to sort.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def _compare_table(ctrl: dict[str, Any], cand: dict[str, Any]) -> str:
    body = ""
    for label, key, kind in r.CANONICAL_METRIC_ROWS:
        if is_excluded_html_compare_label(label):
            continue
        c, a = ctrl.get(key), cand.get(key)
        body += (
            f"<tr><td>{html_mod.escape(label)}</td>"
            f"<td>{r._fmt_kind(c, kind)}</td>"
            f"<td>{r._fmt_kind(a, kind)}</td>"
            f"<td>{r._delta_kind(a, c, kind)}</td></tr>"
        )
    head = "".join(
        r._sortable_th(h, t)
        for h, t in (
            ("Metric", "text"),
            ("CONTROL static $2,500 (RSI = $38,405 slot)", "text"),
            ("CANDIDATE monthly-step 1%", "text"),
            ("Δ (compound − static)", "text"),
        )
    )
    return (
        f'<table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table>"
    )


def _trade_table(trades: list[r.OverlayTrade], *, open_book: bool = False) -> str:
    if not trades:
        return '<p class="small">No trades.</p>'
    rows = sorted(trades, key=lambda t: ((t.closed or date.min), t.symbol))
    body = ""
    for t in rows:
        d_close = t.closed.strftime("%Y-%m-%d") if t.closed else ""
        stop_s = f"${t.stop_used:,.2f}" if t.stop_used else "—"
        risk_s = format_money(t.risk_dollar) if t.risk_dollar is not None else "—"
        eq_s = format_money(t.equity_bom) if t.equity_bom is not None else "—"
        body += (
            "<tr>"
            f"<td>{r._symbol_link(t.symbol)}</td>"
            f"<td>{t.opened.strftime('%Y-%m-%d')}</td>"
            f"<td>{d_close}</td>"
            f"<td>{html_mod.escape(t.exit_type)}</td>"
            f"<td>{int(t.days)}</td>"
            f"<td>{stop_s}</td>"
            f"<td>{risk_s}</td>"
            f"<td>{eq_s}</td>"
            f"<td>{r._fmt_num(t.shares, 1)}</td>"
            f"<td>{format_money(t.invested) if t.sized else '—'}</td>"
            f"<td class=\"{r._pnl_class(t.pnl_pct)}\">{r.monthly._fmt_pct(t.pnl_pct)}</td>"
            f"<td class=\"{r._pnl_class(t.overlay_pnl)}\">{r._fmt_money_signed(t.overlay_pnl) if t.sized else 'N/A'}</td>"
            f"<td>{html_mod.escape(t.stop_src if t.sized else t.skip_reason)}</td>"
            "</tr>"
        )
    labels = [
        ("Symbol", "text"),
        ("Opened", "date"),
        ("Closed" if not open_book else "—", "date"),
        ("Exit", "text"),
        ("Days", "num"),
        ("Stop used", "num"),
        ("Month 1%", "num"),
        ("BOM equity", "num"),
        ("Shares", "num"),
        ("$ invested", "num"),
        ("PnL %", "num"),
        ("Overlay $", "num"),
        ("Size note", "text"),
    ]
    head = "".join(r._sortable_th(a, b) for a, b in labels)
    return (
        f'<table class="sortable"><thead><tr>{head}</tr></thead><tbody>'
        + body
        + "</tbody></table>"
    )


def _pivot_and_hist(
    closed: list[r.OverlayTrade],
    *,
    year: int,
    through_month: int,
) -> tuple[str, str]:
    year_closed = [t for t in closed if t.closed and t.closed.year == year and t.sized]
    monthly_agg: dict[tuple[int, int, str], dict] = {}
    for t in year_closed:
        assert t.closed is not None
        key = (t.closed.year, t.closed.month, t.system)
        b = monthly_agg.setdefault(key, {"pnl": 0.0, "trades": 0})
        b["pnl"] += t.overlay_pnl
        b["trades"] += 1
    pivot_head = (
        r._sortable_th("Month", "month")
        + "".join(r._sortable_th(sys, "num") for sys in SYSTEMS)
        + r._sortable_th("Total", "num")
    )
    pivot_body = ""
    ytd_m = {sys: 0.0 for sys in SYSTEMS}
    for month in range(1, through_month + 1):
        label = r.monthly.MONTH_NAMES[month - 1]
        cells = []
        row_total = 0.0
        for sys in SYSTEMS:
            stats = monthly_agg.get((year, month, sys), {"pnl": 0.0, "trades": 0})
            pnl = stats["pnl"]
            n = stats["trades"]
            ytd_m[sys] += pnl
            row_total += pnl
            if n:
                cells.append(
                    f'<td class="{r._pnl_class(pnl)}">{r._fmt_money_signed(pnl)}'
                    f'<br><span class="small">({n} trades)</span></td>'
                )
            else:
                cells.append('<td class="muted">—</td>')
        pivot_body += (
            f"<tr><th>{label}</th>"
            + "".join(cells)
            + f'<td class="{r._pnl_class(row_total)}"><strong>{r._fmt_money_signed(row_total)}</strong></td></tr>'
        )
    foot_cells = []
    grand = 0.0
    for sys in SYSTEMS:
        pnl = ytd_m[sys]
        grand += pnl
        foot_cells.append(
            f'<td class="{r._pnl_class(pnl)}"><strong>{r._fmt_money_signed(pnl)}</strong></td>'
        )
    pivot_foot = (
        '<tr class="total-row"><th>YTD</th>'
        + "".join(foot_cells)
        + f'<td class="{r._pnl_class(grand)}"><strong>{r._fmt_money_signed(grand)}</strong></td></tr>'
    )
    pivot_html = (
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{pivot_head}</tr></thead>'
        f"<tbody>{pivot_body}{pivot_foot}</tbody></table></div>"
    )

    year_tot: dict[int, dict[str, float]] = defaultdict(lambda: {s: 0.0 for s in SYSTEMS})
    year_n: dict[int, dict[str, int]] = defaultdict(lambda: {s: 0 for s in SYSTEMS})
    for t in closed:
        if t.sized and t.closed:
            year_tot[t.closed.year][t.system] += t.overlay_pnl
            year_n[t.closed.year][t.system] += 1
    hist_head = (
        r._sortable_th("Year", "num")
        + "".join(r._sortable_th(s, "num") for s in SYSTEMS)
        + r._sortable_th("Total", "num")
    )
    hist_body = ""
    col_tot = {s: 0.0 for s in SYSTEMS}
    for y in sorted(year_tot):
        cells = []
        tot = 0.0
        for sys in SYSTEMS:
            pnl = year_tot[y][sys]
            n = year_n[y][sys]
            tot += pnl
            col_tot[sys] += pnl
            if n:
                cells.append(
                    f'<td class="{r._pnl_class(pnl)}">{r._fmt_money_signed(pnl)}'
                    f'<br><span class="small">({n})</span></td>'
                )
            else:
                cells.append('<td class="muted">—</td>')
        hist_body += (
            f"<tr><th>{y}</th>"
            + "".join(cells)
            + f'<td class="{r._pnl_class(tot)}"><strong>{r._fmt_money_signed(tot)}</strong></td></tr>'
        )
    grand_hist = sum(col_tot.values())
    hist_foot_cells = [
        f'<td class="{r._pnl_class(col_tot[sys])}"><strong>{r._fmt_money_signed(col_tot[sys])}</strong></td>'
        for sys in SYSTEMS
    ]
    hist_foot = (
        '<tr class="total-row"><th>Total</th>'
        + "".join(hist_foot_cells)
        + f'<td class="{r._pnl_class(grand_hist)}"><strong>{r._fmt_money_signed(grand_hist)}</strong></td></tr>'
    )
    hist_html = (
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{hist_head}</tr></thead>'
        f"<tbody>{hist_body}{hist_foot}</tbody></table></div>"
    )
    return pivot_html, hist_html


def _lead_box(
    *,
    shared_rows: list[dict[str, Any]],
    per_sys_rows: dict[str, list[dict[str, Any]]],
) -> str:
    row2010 = next((x for x in shared_rows if x["year"] == 2010), None)
    row2011 = next((x for x in shared_rows if x["year"] == 2011), None)
    if row2010 is None:
        shared_txt = "Shared book has no 2010 row."
        eq2010 = None
        jan2011 = None
    else:
        eq2010 = row2010["ending_equity"]
        jan2011 = row2010["next_1pct"]
        near = abs(eq2010 - 450_000.0) < 50_000.0
        near_s = "near your $450k example" if near else "not near $450k"
        extra_ex = ""
        if jan2011 is not None and abs(float(jan2011) - 4500.0) < 800:
            extra_ex = " Your example was $4,500 — this is the same idea, a bit higher."
        elif jan2011 is not None and abs(float(jan2011) - 4500.0) >= 800:
            extra_ex = " Your example was $4,500."
        shared_txt = (
            f"Shared $250k account (“my account”): 2010 ended at "
            f"<strong>{format_money(eq2010)}</strong> ({near_s}). "
            f"January 2011 1% = <strong>{format_money(jan2011)}</strong>."
            f"{extra_ex}"
        )
        if row2010["realized"] == 0.0 and eq2010 == ACCOUNT:
            shared_txt += (
                " No sized DailyRun overlay closes in 2010 on this pin, so the "
                "account was still the $250k start and Jan 2011 1% stayed $2,500."
            )
    sleeve_bits = []
    for sys in SYSTEMS:
        rows = per_sys_rows.get(sys) or []
        y2010 = next((x for x in rows if x["year"] == 2010), None)
        if y2010 is None:
            continue
        sleeve_bits.append(
            f"{sys} sleeve 2010 end {format_money(y2010['ending_equity'])} → "
            f"Jan 2011 1% {format_money(y2010['next_1pct'])}"
        )
    sleeve_s = "; ".join(sleeve_bits) if sleeve_bits else "no 2010 sleeve rows"
    return f"""
<div class="lead">
<h2>Did 2010 end near $450k? What is January 2011 1%?</h2>
<p>{shared_txt}</p>
<p class="small">Per-system sleeves (each starts at its own $250k — not “the account”): {html_mod.escape(sleeve_s)}.</p>
<p>Adding the nine sleeve ending equities is <em>not</em> one account. That would count $250k nine times. Use the shared book for “my account.”</p>
</div>"""


def build_monthly_compound_html(
    *,
    year: int,
    per_sys_sized: dict[str, list[r.OverlayTrade]],
    per_sys_snaps: dict[str, list[MonthSnap]],
    shared_sized: list[r.OverlayTrade],
    shared_snaps: list[MonthSnap],
    static_per_sys: dict[str, list[r.OverlayTrade]],
    static_shared: list[r.OverlayTrade],
    sources: list[str],
    generated: datetime,
    tables: dict[str, dict[str, Any]],
    shared_tables: dict[str, Any],
    verdict: str,
) -> str:
    now = generated.astimezone(ET)
    through_month = now.month if now.year == year else 12
    closed = [t for ts in per_sys_sized.values() for t in ts if t.status == "closed"]
    open_rows = [t for ts in per_sys_sized.values() for t in ts if t.status == "open"]
    year_closed = [t for t in closed if t.closed and t.closed.year == year and t.sized]

    ytd = {sys: {"pnl": 0.0, "trades": 0, "wins": 0} for sys in SYSTEMS}
    for t in year_closed:
        ytd[t.system]["pnl"] += t.overlay_pnl
        ytd[t.system]["trades"] += 1
        if t.overlay_pnl > 0:
            ytd[t.system]["wins"] += 1
    open_by = {sys: [] for sys in SYSTEMS}
    for t in open_rows:
        if t.sized:
            open_by[t.system].append(t)
    open_tot = {sys: sum(t.overlay_pnl for t in rows) for sys, rows in open_by.items()}

    cards = ""
    for sys in SYSTEMS:
        y = ytd[sys]
        unreal = open_tot[sys]
        total = y["pnl"] + unreal
        wr = (100.0 * y["wins"] / y["trades"]) if y["trades"] else 0.0
        snaps = per_sys_snaps.get(sys) or []
        cur = next((s for s in snaps if s.year == year and s.month == through_month), None)
        risk_s = format_money(cur.risk_dollar) if cur else "—"
        cards += f"""
  <div class="card">
    <h3>{html_mod.escape(SYSTEM_EXPAND.get(sys, sys))} sleeve</h3>
    <div class="metric {r._pnl_class(y['pnl'])}">{r._fmt_money_signed(y['pnl'])}</div>
    <div class="small">YTD realized · {y['trades']} sized · {wr:.0f}% win · this month 1% {risk_s}</div>
    <div class="small">Open unrealized: <span class="{r._pnl_class(unreal)}">{r._fmt_money_signed(unreal)}</span>
      ({len(open_by[sys])} sized)</div>
    <div class="small">Realized + open: <span class="{r._pnl_class(total)}">{r._fmt_money_signed(total)}</span></div>
  </div>"""
    total_ytd = sum(v["pnl"] for v in ytd.values())
    total_open = sum(open_tot.values())
    cards += f"""
  <div class="card card-total">
    <h3>Sum of nine sleeves (not one account)</h3>
    <div class="metric {r._pnl_class(total_ytd)}">{r._fmt_money_signed(total_ytd)}</div>
    <div class="small">YTD realized · each sleeve compounds on its own $250k</div>
    <div class="small">Open unrealized: <span class="{r._pnl_class(total_open)}">{r._fmt_money_signed(total_open)}</span></div>
    <div class="small">Combined sleeves: <span class="{r._pnl_class(total_ytd + total_open)}">{r._fmt_money_signed(total_ytd + total_open)}</span></div>
  </div>"""

    shared_year = [
        t
        for t in shared_sized
        if t.status == "closed" and t.closed and t.closed.year == year and t.sized
    ]
    shared_ytd = sum(t.overlay_pnl for t in shared_year)
    shared_open = [t for t in shared_sized if t.status == "open" and t.sized]
    shared_unreal = sum(t.overlay_pnl for t in shared_open)
    sh_cur = next((s for s in shared_snaps if s.year == year and s.month == through_month), None)
    sh_eq = format_money(sh_cur.equity_start) if sh_cur else "—"
    sh_risk = format_money(sh_cur.risk_dollar) if sh_cur else "—"
    cards += f"""
  <div class="card card-shared">
    <h3>Shared $250k account (my account)</h3>
    <div class="metric {r._pnl_class(shared_ytd)}">{r._fmt_money_signed(shared_ytd)}</div>
    <div class="small">YTD realized on one equity · BOM equity {sh_eq} · this month 1% {sh_risk}</div>
    <div class="small">Open unrealized: <span class="{r._pnl_class(shared_unreal)}">{r._fmt_money_signed(shared_unreal)}</span>
      ({len(shared_open)} sized)</div>
    <div class="small">Book risk stacks: each open name still gets this month’s full 1%.</div>
  </div>"""

    pivot_html, hist_html = _pivot_and_hist(closed, year=year, through_month=through_month)
    shared_closed = [t for t in shared_sized if t.status == "closed"]
    shared_pivot, shared_hist = _pivot_and_hist(
        shared_closed, year=year, through_month=through_month
    )

    month_sections = ""
    for month in range(1, through_month + 1):
        label = r.monthly._month_label(year, month)
        month_trades = [
            t
            for t in year_closed
            if t.closed and t.closed.year == year and t.closed.month == month
        ]
        if not month_trades:
            month_sections += f"""
<section class="month-section">
  <h2>{label}</h2>
  <p class="small muted">No sized closed compound trades this month.</p>
</section>"""
            continue
        month_total = sum(t.overlay_pnl for t in month_trades)
        sys_blocks = ""
        for sys in SYSTEMS:
            sys_trades = [t for t in month_trades if t.system == sys]
            if not sys_trades:
                continue
            sys_pnl = sum(t.overlay_pnl for t in sys_trades)
            sys_blocks += f"""
  <div class="sys-block">
    <h3>{html_mod.escape(SYSTEM_EXPAND.get(sys, sys))} · <span class="{r._pnl_class(sys_pnl)}">{r._fmt_money_signed(sys_pnl)}</span> · {len(sys_trades)} closed</h3>
    <div class="table-wrap">{_trade_table(sys_trades)}</div>
  </div>"""
        month_sections += f"""
<section class="month-section">
  <h2>{label} · <span class="{r._pnl_class(month_total)}">{r._fmt_money_signed(month_total)}</span> total (sleeves)</h2>
  {sys_blocks}
</section>"""

    open_sections = ""
    for sys in SYSTEMS:
        rows_o = open_by[sys]
        if not rows_o:
            continue
        sys_pnl = open_tot[sys]
        open_sections += f"""
  <div class="sys-block">
    <h3>{html_mod.escape(SYSTEM_EXPAND.get(sys, sys))} · <span class="{r._pnl_class(sys_pnl)}">{r._fmt_money_signed(sys_pnl)}</span> · {len(rows_o)} open</h3>
    <div class="table-wrap">{_trade_table(rows_o, open_book=True)}</div>
  </div>"""

    shared_rows = year_end_rows(shared_snaps, through=ASOF)
    per_sys_year = {sys: year_end_rows(per_sys_snaps[sys], through=ASOF) for sys in SYSTEMS}
    lead = _lead_box(shared_rows=shared_rows, per_sys_rows=per_sys_year)

    sleeve_year_head = (
        r._sortable_th("Year-end", "num")
        + "".join(r._sortable_th(f"{sys} equity", "num") for sys in SYSTEMS)
        + "".join(r._sortable_th(f"{sys} next 1%", "num") for sys in SYSTEMS)
    )
    sleeve_year_body = ""
    years = sorted({row["year"] for rows in per_sys_year.values() for row in rows})
    for y in years:
        cells_eq = []
        cells_r = []
        for sys in SYSTEMS:
            row = next((x for x in per_sys_year[sys] if x["year"] == y), None)
            if row:
                cells_eq.append(f"<td>{format_money(row['ending_equity'])}</td>")
                cells_r.append(f"<td>{format_money(row['next_1pct'])}</td>")
            else:
                cells_eq.append('<td class="muted">—</td>')
                cells_r.append('<td class="muted">—</td>')
        sleeve_year_body += f"<tr><th>{y}</th>" + "".join(cells_eq) + "".join(cells_r) + "</tr>"

    compare_sections = ""
    for sl, note in (
        ("IS", "In-Sample — entry before 2024-01-01; do not retune on OOS"),
        ("OOS", "Out-of-Sample — report-only"),
        ("FULL", verdict),
    ):
        compare_sections += f"""
<section>
<h2>Canonical compare · per-system sleeves rolled into one book · {sl}</h2>
<p class="small">{html_mod.escape(note)}. Control = static $2,500 (RSI = $38,405 IS slot).
Candidate = monthly-step 1%. Sheet / Total PnL $ omitted. Click headers to sort.</p>
<div class="table-wrap">{_compare_table(tables[sl]['static'], tables[sl]['compound'])}</div>
</section>"""
        compare_sections += f"""
<section>
<h2>Canonical compare · shared $250k account · {sl}</h2>
<p class="small">{html_mod.escape(note)}. Same trades, one equity. Click headers to sort.</p>
<div class="table-wrap">{_compare_table(shared_tables[sl]['static'], shared_tables[sl]['compound'])}</div>
</section>"""

    per_sys_compare = ""
    for sys in SYSTEMS:
        pack = tables.get(f"sys_{sys}") or {}
        if not pack:
            continue
        per_sys_compare += f"""
<section>
<h2>{html_mod.escape(SYSTEM_EXPAND.get(sys, sys))} sleeve · FULL static vs compound</h2>
<p class="small">{html_mod.escape(pack.get('verdict') or 'HOLD')} · Click headers to sort.</p>
<div class="table-wrap">{_compare_table(pack['static'], pack['compound'])}</div>
</section>"""

    sources_html = "".join(f"<li>{html_mod.escape(s)}</li>" for s in sources)
    gen_s = now.strftime("%Y-%m-%d %H:%M %Z")
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Monthly beginning-of-month 1% compound — {year}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin:24px; color:#0f172a; }}
h1 {{ font-size:1.5rem; margin-bottom:4px; }}
h2 {{ font-size:1.15rem; margin-top:28px; }}
h3 {{ font-size:1rem; margin:16px 0 8px; color:#334155; }}
.sub {{ color:#64748b; margin-bottom:20px; line-height:1.5; font-size:0.95rem; }}
.ask {{ background:#fff7ed; border:1px solid #fdba74; border-radius:10px; padding:14px 16px; margin:16px 0; }}
.ask h2 {{ margin-top:8px; font-size:1rem; }}
.ask h2:first-child {{ margin-top:0; }}
blockquote {{ margin:8px 0 12px; color:#9a3412; }}
.hold {{ background:#eef2ff; border:1px solid #c7d2fe; border-radius:10px; padding:12px 14px; margin:12px 0 20px; }}
.lead {{ background:#ecfdf5; border:1px solid #6ee7b7; border-radius:10px; padding:14px 16px; margin:12px 0 20px; }}
.warn {{ background:#fef2f2; border:1px solid #fecaca; border-radius:10px; padding:12px 14px; margin:12px 0; }}
.cards {{ display:flex; flex-wrap:wrap; gap:12px; margin:16px 0 24px; }}
.card {{ background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:14px 16px; min-width:200px; flex:1 1 220px; }}
.card-total {{ background:#eef2ff; border-color:#c7d2fe; }}
.card-shared {{ background:#ecfdf5; border-color:#6ee7b7; }}
.card h3 {{ margin:0 0 8px; font-size:13px; color:#475569; font-weight:700; }}
.metric {{ font-size:1.35rem; font-weight:700; line-height:1.2; }}
.small {{ font-size:12px; color:#64748b; }}
.muted {{ color:#94a3b8; }}
.pos {{ color:#16a34a; }} .neg {{ color:#dc2626; }}
section {{ margin-top:24px; }}
.month-section {{ border-top:1px solid #e2e8f0; padding-top:8px; }}
.sys-block {{ margin:12px 0 20px; }}
.table-wrap {{ margin:8px 0; }}
table {{ border-collapse:collapse; font-size:12px; width:100%; }}
th, td {{ border:1px solid #e2e8f0; padding:7px 8px; text-align:left; vertical-align:top; }}
th {{ background:#f1f5f9; }}
th.sortable-th {{ cursor:pointer; user-select:none; white-space:normal; }}
th.sortable-th:hover {{ background:#e2e8f0; }}
.sort-ind {{ display:inline-block; width:0.9em; margin-left:4px; color:#94a3b8; font-size:10px; }}
th.sort-asc .sort-ind::after {{ content:"▲"; color:#334155; }}
th.sort-desc .sort-ind::after {{ content:"▼"; color:#334155; }}
tr.total-row th, tr.total-row td {{ background:#f8fafc; border-top:2px solid #334155; }}
ul.sources {{ font-size:12px; color:#475569; line-height:1.6; }}
a.sym {{ color:#1d4ed8; text-decoration:none; font-weight:600; }}
a.sym:hover {{ text-decoration:underline; }}
{r.TABLE_UNCAP_CSS}
</style></head><body>
<h1>Monthly Backtest Report — {year} · beginning-of-month 1% compound</h1>
<p class="sub">
Research size overlay. <strong>Not gold. Not DailyRun.</strong>
Control stays <a href="monthly.html">monthly.html</a> (static $2,500; RSI = $38,405 IS avg-loss slot).
Paper start $250,000. Each month: <code>risk_dollar = 0.01 × beginning-of-month equity</code>
after prior realized overlay P&amp;L. Mid-month closes do not change that month’s 1%.
Stop systems: <code>shares = risk_dollar / (entry − stop)</code>.
Relative Strength Index (RSI): <code>invested = risk_dollar / 0.0651</code> (IS freeze 6.51%, not roll-8 invert).
Generated {html_mod.escape(gen_s)}. Click column headers to sort.
</p>
<div class="ask">
<h2>What you asked</h2>
<blockquote>{html_mod.escape(r.ORIGINAL_REQUEST)}</blockquote>
<blockquote>{html_mod.escape(r.FOLLOWUP_REQUEST)}</blockquote>
<blockquote>{html_mod.escape(COMPOUND_REQUEST)}</blockquote>
<h2>In plain English</h2>
<p>{html_mod.escape(COMPOUND_PLAIN)}</p>
</div>
{lead}
<div class="hold"><strong>{html_mod.escape(verdict)}</strong></div>
<section>
<h2>Equity / 1% by year-end — shared $250k account</h2>
<p class="small">This is the book that matches “my account.” Year-end equity is $250k plus realized compound overlay P&amp;L through December (2026 = through as-of). Next year’s 1% is 1% of that year-end. Your $450k / $4,500 example is the 2010 row → next Jan 1% column.</p>
<div class="warn">
<strong>Read 2010–2012. Later shared years are a math path, not a tradable account.</strong>
Each open name still takes that month’s full 1%, so 10 names open = about 10% of a growing pile, with no cash cap and no “I only have $250k” brake. After a few good years the 1% itself is huge, so later dollar columns go to billions and then nonsense. That is path-dependence plus stacked book risk — not extra edge. Per-system sleeves stay in a more readable range because each sleeve compounds only on its own trades.
</div>
{_year_table(shared_rows, caption="Shared account path.")}
</section>
<section>
<h2>Equity / 1% by year-end — each system sleeve ($250k each)</h2>
<p class="small">Primary monthly columns treat each system as its own paper account. Ending equity and the next year’s 1% sit side by side. Do not add the nine equities and call it one account. Click headers to sort.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>{sleeve_year_head}</tr></thead>
<tbody>{sleeve_year_body}</tbody></table></div>
</section>
<div class="cards">{cards}</div>
<section>
<h2>Monthly realized compound P&amp;L by system ({year}) — per-sleeve book</h2>
<p class="small">Same layout as the static monthly. Each column is that sleeve’s own $250k compound path. Closed trades by exit month. RSI = that month’s 1% / 0.0651. Total row pinned. Click column headers to sort.</p>
{pivot_html}
</section>
<section>
<h2>All years — per-sleeve overlay realized $ (sized closed)</h2>
<p class="small">Compound dollars. Total row stays at the bottom when you sort. Click headers to sort.</p>
{hist_html}
</section>
<section>
<h2>Shared $250k account — {year} monthly and all-years $</h2>
<p class="small">One equity. Same-day fill order: symbol, then system. Concurrent names each take the month’s full 1% (book risk stacks). Total row pinned.</p>
<h3>{year} by month</h3>
{shared_pivot}
<h3>All years</h3>
{shared_hist}
</section>
{compare_sections}
{per_sys_compare}
{month_sections}
<section>
<h2>Open positions (unrealized compound $) — per sleeve</h2>
<p class="small">Sized with the 1% from the entry month’s beginning equity.</p>
{open_sections if open_sections else '<p class="small muted">No sized open compound positions.</p>'}
</section>
<section>
<h2>Data sources</h2>
<ul class="sources">{sources_html}</ul>
<p class="small">Static control: <a href="monthly.html">monthly.html</a> ·
house vs $2,500: <a href="compare.html">compare.html</a> ·
this compare also: <a href="compare_compound.html">compare_compound.html</a> ·
RSI avg-loss write-up: <a href="rsi_avgloss.html">rsi_avgloss.html</a>.
Acronyms: Break and ReTest (BRT); Rocket Launcher (RL); Year High (YH); Magic Touch (MTS);
Weekly Pivot Break and Retest (WPBR); Relative Strength vs SPY (RS); StockBee (SB);
Volume Zone (VZ); Relative Strength Index (RSI); In-Sample (IS); Out-of-Sample (OOS);
Annualized Rate of Return (Ann ROR); Maximum Drawdown (Max DD); beginning-of-month (BOM).</p>
</section>
{r.monthly._SORTABLE_TABLE_SCRIPT}
</body></html>"""


def build_compare_compound_html(
    *,
    tables: dict[str, dict[str, Any]],
    shared_tables: dict[str, Any],
    verdict: str,
    sources: list[str],
) -> str:
    sections = []
    for sl, note in (
        ("IS", "In-Sample — do not retune OOS"),
        ("OOS", "Out-of-Sample — report-only"),
        ("FULL", verdict),
    ):
        sections.append(
            f"<section><h2>Rolled sleeves (nine $250k accounts, one table) · {sl}</h2>"
            f"<p class=\"small\">{html_mod.escape(note)}</p>"
            f"<div class=\"table-wrap\">{_compare_table(tables[sl]['static'], tables[sl]['compound'])}</div></section>"
        )
        sections.append(
            f"<section><h2>Shared $250k account · {sl}</h2>"
            f"<p class=\"small\">{html_mod.escape(note)}</p>"
            f"<div class=\"table-wrap\">{_compare_table(shared_tables[sl]['static'], shared_tables[sl]['compound'])}</div></section>"
        )
    for sys in SYSTEMS:
        pack = tables.get(f"sys_{sys}")
        if not pack:
            continue
        sections.append(
            f"<section><h2>{html_mod.escape(SYSTEM_EXPAND.get(sys, sys))} sleeve · FULL</h2>"
            f"<p class=\"small\">{html_mod.escape(pack.get('verdict') or 'HOLD')}</p>"
            f"<div class=\"table-wrap\">{_compare_table(pack['static'], pack['compound'])}</div></section>"
        )
    sources_html = "".join(f"<li>{html_mod.escape(s)}</li>" for s in sources)
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Static $2,500 vs monthly-step 1% — {STAMP}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin:24px; color:#0f172a; }}
h1 {{ font-size:1.45rem; margin-bottom:4px; }}
h2 {{ font-size:1.1rem; margin-top:28px; }}
.sub, .small {{ color:#64748b; font-size:13px; line-height:1.5; }}
.ask {{ background:#fff7ed; border:1px solid #fdba74; border-radius:10px; padding:14px 16px; margin:16px 0 24px; }}
.ask h2 {{ margin-top:0; }}
blockquote {{ margin:8px 0; color:#9a3412; }}
.hold {{ background:#eef2ff; border:1px solid #c7d2fe; border-radius:10px; padding:12px 14px; }}
.table-wrap {{ margin:8px 0; }}
table.sortable {{ border-collapse:collapse; font-size:12px; width:100%; }}
th, td {{ border:1px solid #e2e8f0; padding:6px 8px; text-align:left; vertical-align:top; }}
th {{ background:#f1f5f9; }}
th.sortable-th {{ cursor:pointer; user-select:none; white-space:normal; }}
th.sortable-th:hover {{ background:#e2e8f0; }}
.sort-ind {{ display:inline-block; width:0.9em; margin-left:4px; color:#94a3b8; font-size:10px; }}
th.sort-asc .sort-ind::after {{ content:"▲"; color:#334155; }}
th.sort-desc .sort-ind::after {{ content:"▼"; color:#334155; }}
{r.TABLE_UNCAP_CSS}
</style></head><body>
<h1>Static $2,500 vs beginning-of-month 1% compound</h1>
<p class="sub">Stamp <code>{STAMP}</code> · research only · <strong>not gold · not DailyRun</strong>.
In-Sample (IS) = entry_date &lt; 2024-01-01. Out-of-Sample (OOS) report-only.
Canonical metrics. Click column headers to sort.</p>
<div class="ask">
<h2>What you asked</h2>
<blockquote>{html_mod.escape(COMPOUND_REQUEST)}</blockquote>
<h2>In plain English</h2>
<p>{html_mod.escape(COMPOUND_PLAIN)}</p>
</div>
<div class="hold"><strong>{html_mod.escape(verdict)}</strong>
Monthly path: <a href="monthly_compound.html">monthly_compound.html</a>.
Static control: <a href="monthly.html">monthly.html</a>.</div>
{''.join(sections)}
<section><h2>Data</h2><ul>{sources_html}</ul></section>
{r.monthly._SORTABLE_TABLE_SCRIPT}
</body></html>"""


def _append_baseline(
    *,
    verdict: str,
    shared_rows: list[dict[str, Any]],
    per_sys_year: dict[str, list[dict[str, Any]]],
    tables: dict[str, dict[str, Any]],
    shared_tables: dict[str, Any],
) -> None:
    path = OUT_DIR / "BASELINE.md"
    old = path.read_text(encoding="utf-8") if path.is_file() else ""
    marker = "## Addendum — monthly-step 1% compound"
    if marker in old:
        old = old.split(marker)[0].rstrip() + "\n\n"
    y2010 = next((x for x in shared_rows if x["year"] == 2010), None)
    lines = [
        marker,
        "",
        "**Status:** Research size path. **Not gold. Not DailyRun.** OOS report-only.",
        "",
        "## What you asked",
        "",
        f"> {COMPOUND_REQUEST}",
        "",
        "## In plain English",
        "",
        COMPOUND_PLAIN,
        "",
        "## Selection",
        "",
        "- Paul specified compound: recalculate 1% at the beginning of each month from account growth.",
        "- Start **$250,000**. `risk_dollar = 0.01 × start-of-month equity` after prior realized overlay PnL.",
        "- Mid-month freeze: closes do not change that month’s risk.",
        "- RSI IS avg-loss freeze **6.509607%** (do not retune on OOS). `invested = risk_dollar / 0.06509607`.",
        "- Two books labeled: per-system sleeve (primary monthly table) and one shared $250k account.",
        "- Same-day shared fill order: symbol, then system. Book risk stacks (each open name gets the month’s 1%).",
        f"- Decision: **{verdict}**",
        "",
        "## Frozen knobs (delta from static $2,500)",
        "",
        "- CONTROL = SIZE_risk2500 / RSI avg-loss slot on the same house Closed pins (`monthly.html`).",
        "- CANDIDATE = monthly-step 1% only. Entries, exits, universes unchanged.",
        "- IS = entry_date < 2024-01-01. OOS report-only.",
        "",
        "## 2010 year-end / January 2011 1% (Paul example)",
        "",
    ]
    if y2010:
        lines.append(
            f"- Shared account: 2010 ending equity **${y2010['ending_equity']:,.2f}**; "
            f"January 2011 1% **${y2010['next_1pct']:,.2f}** "
            f"(example was $450,000 / $4,500)."
        )
    for sys in SYSTEMS:
        row = next((x for x in per_sys_year.get(sys, []) if x["year"] == 2010), None)
        if row:
            lines.append(
                f"- {sys} sleeve: 2010 end ${row['ending_equity']:,.2f} → Jan 2011 1% ${row['next_1pct']:,.2f}"
            )
    lines += [
        "",
        "## Honesty",
        "",
        "- Dollar totals grow when the path is good because later fills risk more. That is not extra Avg PnL % edge.",
        "- Concurrent names each take the month’s 1%, so book risk is ~1% × names open.",
        "- Shared-book dollars after ~2012 are a math path (no cash cap). Read 2010–2012 for the $450k question.",
        "- Nine sleeves summed ≠ one account (nine $250k starts).",
        "- Picking KEEP from this same history would be in-sample selection. We are not adopting.",
        "",
        "## FULL quality (rolled sleeves)",
        "",
    ]
    st = tables["FULL"]["static"]
    cd = tables["FULL"]["compound"]
    lines.append(
        f"- Static N={st.get('n')} WR={st.get('win_pct')} Avg%={st.get('avg_pnl_pct')} "
        f"PF={st.get('pf')} AnnROR$250k={st.get('ann_ror_250k')} MaxDD={st.get('max_dd')} "
        f"Calmar={st.get('calmar')} Sharpe={st.get('sharpe')}"
    )
    lines.append(
        f"- Compound N={cd.get('n')} WR={cd.get('win_pct')} Avg%={cd.get('avg_pnl_pct')} "
        f"PF={cd.get('pf')} AnnROR$250k={cd.get('ann_ror_250k')} MaxDD={cd.get('max_dd')} "
        f"Calmar={cd.get('calmar')} Sharpe={cd.get('sharpe')} "
        f"mean$={cd.get('mean_notional')} peak$={cd.get('peak_notional')}"
    )
    sst = shared_tables["FULL"]["static"]
    scd = shared_tables["FULL"]["compound"]
    lines += [
        "",
        "## FULL quality (shared $250k)",
        "",
        f"- Static N={sst.get('n')} WR={sst.get('win_pct')} Avg%={sst.get('avg_pnl_pct')} "
        f"PF={sst.get('pf')} AnnROR$250k={sst.get('ann_ror_250k')} MaxDD={sst.get('max_dd')} "
        f"Calmar={sst.get('calmar')} Sharpe={sst.get('sharpe')}",
        f"- Compound N={scd.get('n')} WR={scd.get('win_pct')} Avg%={scd.get('avg_pnl_pct')} "
        f"PF={scd.get('pf')} AnnROR$250k={scd.get('ann_ror_250k')} MaxDD={scd.get('max_dd')} "
        f"Calmar={scd.get('calmar')} Sharpe={scd.get('sharpe')} "
        f"mean$={scd.get('mean_notional')} peak$={scd.get('peak_notional')}",
        "",
    ]
    path.write_text(old + "\n".join(lines) + "\n", encoding="utf-8")


def _append_hypothesis(verdict: str) -> None:
    path = OUT_DIR / "HYPOTHESIS.md"
    old = path.read_text(encoding="utf-8") if path.is_file() else ""
    marker = "## Addendum — monthly-step 1% compound"
    if marker in old:
        old = old.split(marker)[0].rstrip() + "\n\n"
    text = f"""{marker}

| Field | Fill in |
|-------|---------|
| **Evidence** | Paul: reset 1% each month from account growth ($250k start; 2010 ~$450k → $4,500 example) |
| **Hypothesis** | Monthly-step 1% changes dollar path vs frozen $2,500; % quality (Avg PnL %, WR) stays the same if the mix is unchanged |
| **Single knob** | SIZE schedule: monthly 1% of equity vs static $2,500. RSI still IS 6.51% avg-loss scale |
| Frozen settings | House entries/exits/universes/pins. RSI 6.509607% IS freeze. Mid-month risk freeze. Two books labeled |
| Alternatives | CONTROL = static $2,500 / RSI $38,405 slot (`monthly.html`). CANDIDATE = monthly-step 1% |
| **Decision** | {verdict} |
| PO sign-off | no |
| DailyRun | not wired |

- [x] One knob (size schedule)
- [x] OOS report-only
- [ ] Adopt — **not adopting**
"""
    path.write_text(old + text, encoding="utf-8")


def _patch_compare_html() -> None:
    path = OUT_DIR / "compare.html"
    if not path.is_file():
        return
    html = path.read_text(encoding="utf-8")
    block = (
        '<!-- compound-addendum -->\n'
        '<div class="hold"><strong>Follow-up (monthly-step 1%):</strong> '
        'recalculate 1% at the beginning of each month from a $250k paper account. '
        'See <a href="monthly_compound.html">monthly_compound.html</a> and '
        '<a href="compare_compound.html">compare_compound.html</a>. '
        'Static $2,500 monthly stays the control.</div>\n'
        '<!-- /compound-addendum -->\n'
    )
    start = "<!-- compound-addendum -->"
    end = "<!-- /compound-addendum -->"
    if start in html and end in html:
        pre, rest = html.split(start, 1)
        _, post = rest.split(end, 1)
        html = pre + block + post.lstrip("\n")
    else:
        needle = '<div class="hold"><strong>Verdict:</strong>'
        if needle in html:
            html = html.replace(needle, block + needle, 1)
        else:
            html = html.replace("</div>\n<section>", "</div>\n" + block + "<section>", 1)
    ask_q = html_mod.escape(COMPOUND_REQUEST)
    if ask_q not in html:
        html = html.replace(
            f"<blockquote>{html_mod.escape(r.FOLLOWUP_REQUEST)}</blockquote>",
            f"<blockquote>{html_mod.escape(r.FOLLOWUP_REQUEST)}</blockquote>\n"
            f"<blockquote>{ask_q}</blockquote>",
            1,
        )
    path.write_text(html, encoding="utf-8")


def run() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    paths = r._resolve_paths()
    sources = r._sources_from_paths(paths)
    sources.append("compound: monthly-step 1% of BOM equity; RSI IS 6.51% freeze")

    static_per_sys: dict[str, list[r.OverlayTrade]] = {}
    per_sys_sized: dict[str, list[r.OverlayTrade]] = {}
    per_sys_snaps: dict[str, list[MonthSnap]] = {}
    for sys in SYSTEMS:
        st = _static_book(sys)
        static_per_sys[sys] = st
        sized, snaps = run_compound_book(st)
        per_sys_sized[sys] = sized
        per_sys_snaps[sys] = snaps
        r.write_overlay_csv(sized, OUT_DIR / f"{sys}_overlay_compound.csv")
        n_sz = sum(1 for t in sized if t.status == "closed" and t.sized)
        print(f"[{sys} compound] closed_sized={n_sz} snaps={len(snaps)}")

    static_shared: list[r.OverlayTrade] = []
    for sys in SYSTEMS:
        static_shared.extend(static_per_sys[sys])
    shared_sized, shared_snaps = run_compound_book(static_shared)
    r.write_overlay_csv(shared_sized, OUT_DIR / "ALL_overlay_compound_shared.csv")
    sleeve_all: list[r.OverlayTrade] = []
    for sys in SYSTEMS:
        sleeve_all.extend(per_sys_sized[sys])
    r.write_overlay_csv(sleeve_all, OUT_DIR / "ALL_overlay_compound_sleeves.csv")

    def sliced(trades: list[r.OverlayTrade], sl: str) -> list[r.OverlayTrade]:
        return r.slice_trades([t for t in trades if t.status == "closed"], sl)

    tables: dict[str, dict[str, Any]] = {}
    for sl in ("IS", "OOS", "FULL"):
        st_book: list[r.OverlayTrade] = []
        cd_book: list[r.OverlayTrade] = []
        for sys in SYSTEMS:
            st_book.extend(sliced(static_per_sys[sys], sl))
            cd_book.extend(sliced(per_sys_sized[sys], sl))
        tables[sl] = {
            "static": _stats(st_book),
            "compound": _stats(cd_book),
        }
    verdict = _verdict_compound(tables["FULL"]["static"], tables["FULL"]["compound"])
    tables["FULL"]["verdict"] = verdict

    shared_tables: dict[str, Any] = {}
    for sl in ("IS", "OOS", "FULL"):
        shared_tables[sl] = {
            "static": _stats(sliced(static_shared, sl)),
            "compound": _stats(sliced(shared_sized, sl)),
        }
    shared_verdict = _verdict_compound(
        shared_tables["FULL"]["static"], shared_tables["FULL"]["compound"]
    )
    shared_tables["FULL"]["verdict"] = shared_verdict

    for sys in SYSTEMS:
        st = _stats(sliced(static_per_sys[sys], "FULL"))
        cd = _stats(sliced(per_sys_sized[sys], "FULL"))
        tables[f"sys_{sys}"] = {
            "static": st,
            "compound": cd,
            "verdict": _verdict_compound(st, cd),
        }

    per_sys_year = {sys: year_end_rows(per_sys_snaps[sys], through=ASOF) for sys in SYSTEMS}
    shared_rows = year_end_rows(shared_snaps, through=ASOF)
    y2010 = next((x for x in shared_rows if x["year"] == 2010), None)
    if y2010:
        print(
            f"[shared] 2010 end equity={y2010['ending_equity']:.2f} "
            f"Jan2011 1%={y2010['next_1pct']:.2f} realized2010={y2010['realized']:.2f}"
        )
    print(f"[verdict] {verdict}")
    print(f"[shared verdict] {shared_verdict}")

    now = datetime.now(tz=ET)
    monthly_html = build_monthly_compound_html(
        year=ASOF.year,
        per_sys_sized=per_sys_sized,
        per_sys_snaps=per_sys_snaps,
        shared_sized=shared_sized,
        shared_snaps=shared_snaps,
        static_per_sys=static_per_sys,
        static_shared=static_shared,
        sources=sources,
        generated=now,
        tables=tables,
        shared_tables=shared_tables,
        verdict=verdict,
    )
    compare_html = build_compare_compound_html(
        tables=tables,
        shared_tables=shared_tables,
        verdict=verdict,
        sources=sources,
    )
    (OUT_DIR / "monthly_compound.html").write_text(monthly_html, encoding="utf-8")
    (OUT_DIR / "compare_compound.html").write_text(compare_html, encoding="utf-8")
    print(f"wrote {OUT_DIR / 'monthly_compound.html'}")
    print(f"wrote {OUT_DIR / 'compare_compound.html'}")
    _append_baseline(
        verdict=verdict,
        shared_rows=shared_rows,
        per_sys_year=per_sys_year,
        tables=tables,
        shared_tables=shared_tables,
    )
    _append_hypothesis(verdict)
    _patch_compare_html()
    print(f"updated {OUT_DIR / 'BASELINE.md'} {OUT_DIR / 'HYPOTHESIS.md'} {OUT_DIR / 'compare.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
