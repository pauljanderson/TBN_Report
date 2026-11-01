#!/usr/bin/env python3
"""One $250k wallet, cash-capped monthly 1% (research only).

Control stays monthly.html (static $2,500) and monthly_compound.html
(uncapped monthly-step 1%). This writes monthly_onaccount.html.

Hard cap: deploy <= available cash. Scale-down to remaining cash.
No leverage. Not gold. Not DailyRun.
"""
from __future__ import annotations

import html as html_mod
import importlib.util
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

_CSPEC = importlib.util.spec_from_file_location(
    "risk2500_monthly_compound_20260917",
    REPO / "tools" / "risk2500_monthly_compound_20260917.py",
)
c = importlib.util.module_from_spec(_CSPEC)
assert _CSPEC.loader is not None
sys.modules["risk2500_monthly_compound_20260917"] = c
_CSPEC.loader.exec_module(c)

STAMP = r.STAMP
OUT_DIR = r.OUT_DIR
ACCOUNT = r.ACCOUNT
RISK_FRAC = 0.01
MIN_DEPLOY = 1.0
ASOF = r.ASOF
SYSTEMS = r.SYSTEMS
SYSTEM_EXPAND = r.SYSTEM_EXPAND
ET = r.ET
SYS_RANK = {sys: i for i, sys in enumerate(SYSTEMS)}

PAUL_Q_REQUEST = (
    "is it realistic that had we been running all of these systems that i "
    "would actually have $114,972,205,731,090,800.00 after 16 years? that "
    "seems outrageous."
)
PAUL_WALLET_REQUEST = (
    "BTW, I don't have $250k to invest in each system. I only have $250k "
    "to invest across ALL systems. how does this change things?"
)
PAUL_Q_PLAIN = (
    "No. One hundred fourteen quadrillion dollars is not a real account. "
    "The compound page let every open name risk 1% of a growing paper pile "
    "and buy far more stock than the cash on hand — tight stops turn a "
    "$2,500 risk into a huge share count. No broker lets a $250,000 account "
    "hold trillions of dollars of stock. The nine $250k sleeves were also "
    "not your account (you do not have nine times $250k). The static "
    "all-years dollar sum on monthly.html is the same class of error if you "
    "read it as one wallet: each system was sized as if it had its own "
    "full $2,500-per-trade book with no cash brake."
)
PAUL_WALLET_PLAIN = (
    "One wallet. You start with $250,000 cash. Every DailyRun system shares "
    "that cash. At the start of each month the 1% risk number is 1% of "
    "whatever the account is worth after trades that already closed "
    "(same monthly step you asked for). Stop systems still try shares = "
    "that 1% ÷ (entry − stop). Relative Strength Index (RSI) still uses "
    "the In-Sample (IS) average-loser freeze 6.51%: dollars invested = "
    "that month’s 1% ÷ 0.0651. Then a hard cap: you cannot buy more than "
    "the cash you still have. If the 1% rule wants $2 million of one name, "
    "we scale the order down to remaining cash — so risk on that fill is "
    "less than 1%. That is the realistic broker constraint (no leverage). "
    "When a trade closes, proceeds come back as cash and the next signal "
    "can use them. Same-day order is frozen: first, closes of older "
    "positions; then new fills by system then symbol; then same-day exits. "
    "We do not shop five different queues. Dollars will look much smaller "
    "than the uncapped pages. That is the honest book."
)


@dataclass
class WalletSnap:
    year: int
    month: int
    equity_start: float
    cash_start: float
    reserved_start: float
    risk_dollar: float
    realized_pnl: float
    equity_end: float
    cash_end: float
    reserved_end: float
    n_entries: int
    n_full: int
    n_scaled: int
    n_skip_cash: int
    n_skip_size: int
    n_closes: int
    peak_reserved: float


def _sys_key(t: r.OverlayTrade) -> tuple[int, str, str]:
    return (SYS_RANK.get(t.system, 99), t.system, t.symbol)


def _clip_to_cash(
    desired: r.OverlayTrade,
    cash: float,
) -> r.OverlayTrade:
    """Scale-down to remaining cash. Skip if cash < MIN_DEPLOY."""
    extra = {
        "cash_before": float(cash),
        "desired_invested": float(desired.invested) if desired.sized else 0.0,
        "scaled": False,
    }
    if not desired.sized:
        return r.OverlayTrade(
            **{
                **desired.__dict__,
                **extra,
                "skip_reason": desired.skip_reason or "cannot_size",
            }
        )
    if cash < MIN_DEPLOY:
        return r.OverlayTrade(
            **{
                **desired.__dict__,
                **extra,
                "shares": 0.0,
                "invested": 0.0,
                "overlay_pnl": 0.0,
                "sized": False,
                "scaled": False,
                "skip_reason": "cash_empty",
            }
        )
    invested = min(float(desired.invested), float(cash))
    if invested < MIN_DEPLOY:
        return r.OverlayTrade(
            **{
                **desired.__dict__,
                **extra,
                "shares": 0.0,
                "invested": 0.0,
                "overlay_pnl": 0.0,
                "sized": False,
                "scaled": False,
                "skip_reason": "cash_too_small",
            }
        )
    scaled = invested + 1e-6 < float(desired.invested)
    shares = invested / desired.entry
    overlay_pnl = (desired.pnl_pct / 100.0) * invested
    note = desired.stop_src or ""
    if scaled:
        note = (note + ";").lstrip(";") + f"scaled_to_cash:{invested:.2f}"
    return r.OverlayTrade(
        **{
            **desired.__dict__,
            **extra,
            "shares": shares,
            "invested": invested,
            "overlay_pnl": overlay_pnl,
            "sized": True,
            "scaled": scaled,
            "skip_reason": "",
            "stop_src": note,
        }
    )


def run_wallet_book(
    trades: list[r.OverlayTrade],
) -> tuple[list[r.OverlayTrade], list[WalletSnap], dict[str, Any]]:
    """One cash ledger. Closed-only equity = cash + reserved cost."""
    if not trades:
        return [], [], {
            "n_full": 0,
            "n_scaled": 0,
            "n_skip_cash": 0,
            "n_skip_size": 0,
            "peak_reserved": 0.0,
            "peak_equity": ACCOUNT,
            "end_cash": ACCOUNT,
            "end_reserved": 0.0,
            "end_equity": ACCOUNT,
            "end_mtm": ACCOUNT,
        }

    by_open: dict[date, list[r.OverlayTrade]] = defaultdict(list)
    for t in trades:
        by_open[t.opened].append(t)

    dates = [t.opened for t in trades]
    dates.extend(t.closed for t in trades if t.closed)
    first, last = min(dates), max(dates)
    months = c._month_range(date(first.year, first.month, 1), date(last.year, last.month, 1))

    cash = ACCOUNT
    reserved = 0.0
    realized = 0.0
    peak_reserved = 0.0
    peak_equity = ACCOUNT
    out: list[r.OverlayTrade] = []
    pending_close: dict[date, list[r.OverlayTrade]] = defaultdict(list)
    snaps: list[WalletSnap] = []

    def _do_close(t: r.OverlayTrade) -> None:
        nonlocal cash, reserved, realized
        if not t.sized:
            return
        cash += t.invested + t.overlay_pnl
        reserved -= t.invested
        realized += t.overlay_pnl

    for y, m in months:
        equity_bom = cash + reserved
        risk = RISK_FRAC * max(equity_bom, 0.0)
        cash_s, reserved_s = cash, reserved
        month_start = date(y, m, 1)
        if m == 12:
            month_end = date(y + 1, 1, 1)
        else:
            month_end = date(y, m + 1, 1)
        day_set: set[date] = set()
        for d, ts in by_open.items():
            if month_start <= d < month_end:
                day_set.add(d)
                for raw in ts:
                    if raw.closed is not None and month_start <= raw.closed < month_end:
                        day_set.add(raw.closed)
        for d in pending_close:
            if month_start <= d < month_end:
                day_set.add(d)
        n_entries = n_full = n_scaled = n_skip_cash = n_skip_size = n_closes = 0
        realized_m = 0.0
        peak_res_m = reserved

        for d in sorted(day_set):
            already = pending_close.pop(d, [])
            older = [t for t in already if t.opened < d]
            same_day_early = [t for t in already if t.opened == d]
            for t in sorted(older, key=_sys_key):
                before = realized
                _do_close(t)
                realized_m += realized - before
                n_closes += 1

            entries = list(by_open.get(d, []))
            entries.sort(key=_sys_key)
            for raw in entries:
                n_entries += 1
                desired = c.apply_compound_size(raw, risk, equity_bom)
                sized = _clip_to_cash(desired, cash)
                out.append(sized)
                if sized.sized:
                    cash -= sized.invested
                    reserved += sized.invested
                    if reserved > peak_reserved:
                        peak_reserved = reserved
                    if reserved > peak_res_m:
                        peak_res_m = reserved
                    if sized.scaled:
                        n_scaled += 1
                    else:
                        n_full += 1
                    if sized.status == "closed" and sized.closed is not None:
                        pending_close[sized.closed].append(sized)
                elif sized.skip_reason in {"cash_empty", "cash_too_small"}:
                    n_skip_cash += 1
                else:
                    n_skip_size += 1

            same_day = same_day_early + [
                t for t in pending_close.pop(d, []) if t.opened == d
            ]
            for t in sorted(same_day, key=_sys_key):
                before = realized
                _do_close(t)
                realized_m += realized - before
                n_closes += 1

        equity_end = cash + reserved
        if equity_end > peak_equity:
            peak_equity = equity_end
        snaps.append(
            WalletSnap(
                year=y,
                month=m,
                equity_start=equity_bom,
                cash_start=cash_s,
                reserved_start=reserved_s,
                risk_dollar=risk,
                realized_pnl=realized_m,
                equity_end=equity_end,
                cash_end=cash,
                reserved_end=reserved,
                n_entries=n_entries,
                n_full=n_full,
                n_scaled=n_scaled,
                n_skip_cash=n_skip_cash,
                n_skip_size=n_skip_size,
                n_closes=n_closes,
                peak_reserved=peak_res_m,
            )
        )

    open_mtm = sum(t.overlay_pnl for t in out if t.status == "open" and t.sized)
    ledger = {
        "n_full": sum(1 for t in out if t.sized and not t.scaled),
        "n_scaled": sum(1 for t in out if t.sized and t.scaled),
        "n_skip_cash": sum(
            1 for t in out if (not t.sized) and t.skip_reason in {"cash_empty", "cash_too_small"}
        ),
        "n_skip_size": sum(
            1
            for t in out
            if (not t.sized) and t.skip_reason not in {"cash_empty", "cash_too_small"}
        ),
        "peak_reserved": peak_reserved,
        "peak_equity": peak_equity,
        "end_cash": cash,
        "end_reserved": reserved,
        "end_equity": cash + reserved,
        "end_mtm": cash + reserved + open_mtm,
        "realized": realized,
        "identity_err": abs((cash + reserved) - (ACCOUNT + realized)),
    }
    return out, snaps, ledger


def year_end_rows(snaps: list[WalletSnap], *, through: date) -> list[dict[str, Any]]:
    by_year: dict[int, list[WalletSnap]] = defaultdict(list)
    for s in snaps:
        by_year[s.year].append(s)
    last_eq = ACCOUNT
    last_cash = ACCOUNT
    last_res = 0.0
    rows: list[dict[str, Any]] = []
    for y in range(2010, through.year + 1):
        ys = by_year.get(y)
        if ys:
            last_eq = ys[-1].equity_end
            last_cash = ys[-1].cash_end
            last_res = ys[-1].reserved_end
            jan_risk = ys[0].risk_dollar
            jan_eq = ys[0].equity_start
            realized = sum(s.realized_pnl for s in ys)
            n_scaled = sum(s.n_scaled for s in ys)
            n_skip = sum(s.n_skip_cash for s in ys)
            n_full = sum(s.n_full for s in ys)
        else:
            jan_risk = RISK_FRAC * last_eq
            jan_eq = last_eq
            realized = 0.0
            n_scaled = n_skip = n_full = 0
        note = ""
        if y == through.year and (through.month < 12 or through.day < 31):
            note = f"realized through {through.isoformat()} (year not finished)"
        rows.append(
            {
                "year": y,
                "ending_equity": last_eq,
                "ending_cash": last_cash,
                "ending_reserved": last_res,
                "next_1pct": RISK_FRAC * last_eq,
                "jan_1pct": jan_risk,
                "jan_equity": jan_eq,
                "realized": realized,
                "n_full": n_full,
                "n_scaled": n_scaled,
                "n_skip_cash": n_skip,
                "note": note,
            }
        )
    return rows


def _static_book(sys: str) -> list[r.OverlayTrade]:
    if sys == "RSI":
        path = OUT_DIR / "RSI_overlay_avgloss.csv"
        if not path.is_file():
            raise SystemExit("missing RSI_overlay_avgloss.csv — need IS avg-loss freeze")
        return r.load_overlay_csv(path)
    return r.load_overlay_csv(OUT_DIR / f"{sys}_overlay_risk2500.csv")


def _stats_wallet(trades: list[r.OverlayTrade]) -> dict[str, Any]:
    closed = [t for t in trades if t.status == "closed"]
    return r.book_stats(closed, use_overlay=True, cash_ann=ACCOUNT, dd_seed=ACCOUNT)


def _stats_path(trades: list[r.OverlayTrade]) -> dict[str, Any]:
    """Same helper as the compound page (mean invested as Ann ROR cash)."""
    closed = [t for t in trades if t.status == "closed"]
    sized = [t for t in closed if t.sized]
    mean_ov = (sum(t.invested for t in sized) / len(sized)) if sized else r.RISK_DOLLARS
    return r.book_stats(closed, use_overlay=True, cash_ann=float(mean_ov), dd_seed=ACCOUNT)


def _verdict(wallet: dict[str, Any], ledger: dict[str, Any]) -> str:
    n = wallet.get("n") or 0
    peak = ledger.get("peak_reserved") or 0.0
    end_eq = ledger.get("end_equity") or ACCOUNT
    return (
        "HOLD — one $250k wallet with a cash cap. Dollar totals are much "
        f"smaller than the uncapped compound path (ending equity "
        f"{format_money(end_eq)}; peak deployed {format_money(peak)}). "
        "That is the honest book, not a worse edge. Scaled fills risk less "
        "than 1% when the stop is tight. Mix can change vs the uncapped "
        f"pages because cash-skips drop later same-day names (sized N={n}). "
        "Not gold. Not DailyRun."
    )


def _year_table(rows: list[dict[str, Any]]) -> str:
    head = "".join(
        r._sortable_th(h, t)
        for h, t in (
            ("Year-end", "num"),
            ("Ending equity (cash + reserved cost)", "num"),
            ("Cash (undeployed)", "num"),
            ("Reserved (open cost)", "num"),
            ("That year’s Jan 1%", "num"),
            ("Next Jan 1%", "num"),
            ("Realized $ that year", "num"),
            ("Full-size fills", "num"),
            ("Scaled to cash", "num"),
            ("Skipped (no cash)", "num"),
            ("Note", "text"),
        )
    )
    body = ""
    for row in rows:
        body += (
            "<tr>"
            f"<td>{row['year']}</td>"
            f"<td>{format_money(row['ending_equity'])}</td>"
            f"<td>{format_money(row['ending_cash'])}</td>"
            f"<td>{format_money(row['ending_reserved'])}</td>"
            f"<td>{format_money(row['jan_1pct'])}</td>"
            f"<td>{format_money(row['next_1pct'])}</td>"
            f"<td class=\"{r._pnl_class(row['realized'])}\">{r._fmt_money_signed(row['realized'])}</td>"
            f"<td>{row['n_full']}</td>"
            f"<td>{row['n_scaled']}</td>"
            f"<td>{row['n_skip_cash']}</td>"
            f"<td class=\"small\">{html_mod.escape(row['note'])}</td>"
            "</tr>"
        )
    return (
        '<p class="small">Closed-only ledger: equity = cash + cost of opens '
        "(not marked to market). Click headers to sort.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def _ledger_month_table(snaps: list[WalletSnap]) -> str:
    head = "".join(
        r._sortable_th(h, t)
        for h, t in (
            ("Month", "month"),
            ("BOM equity", "num"),
            ("BOM cash", "num"),
            ("BOM reserved", "num"),
            ("Month 1%", "num"),
            ("Entries", "num"),
            ("Full", "num"),
            ("Scaled", "num"),
            ("Cash-skip", "num"),
            ("Size-skip", "num"),
            ("Closes", "num"),
            ("Realized $", "num"),
            ("EOM equity", "num"),
            ("EOM cash", "num"),
            ("Peak reserved", "num"),
        )
    )
    body = ""
    for s in snaps:
        label = f"{s.year}-{s.month:02d}"
        body += (
            "<tr>"
            f"<td>{label}</td>"
            f"<td>{format_money(s.equity_start)}</td>"
            f"<td>{format_money(s.cash_start)}</td>"
            f"<td>{format_money(s.reserved_start)}</td>"
            f"<td>{format_money(s.risk_dollar)}</td>"
            f"<td>{s.n_entries}</td>"
            f"<td>{s.n_full}</td>"
            f"<td>{s.n_scaled}</td>"
            f"<td>{s.n_skip_cash}</td>"
            f"<td>{s.n_skip_size}</td>"
            f"<td>{s.n_closes}</td>"
            f"<td class=\"{r._pnl_class(s.realized_pnl)}\">{r._fmt_money_signed(s.realized_pnl)}</td>"
            f"<td>{format_money(s.equity_end)}</td>"
            f"<td>{format_money(s.cash_end)}</td>"
            f"<td>{format_money(s.peak_reserved)}</td>"
            "</tr>"
        )
    return (
        '<p class="small">Cash ledger by month. Identity: cash + reserved = '
        "$250k + realized. Peak reserved never exceeds equity (no leverage). "
        "Click headers to sort.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def _three_compare(
    static: dict[str, Any],
    compound: dict[str, Any],
    wallet: dict[str, Any],
) -> str:
    body = ""
    for label, key, kind in r.CANONICAL_METRIC_ROWS:
        if is_excluded_html_compare_label(label):
            continue
        a, b, w = static.get(key), compound.get(key), wallet.get(key)
        body += (
            f"<tr><td>{html_mod.escape(label)}</td>"
            f"<td>{r._fmt_kind(a, kind)}</td>"
            f"<td>{r._fmt_kind(b, kind)}</td>"
            f"<td>{r._fmt_kind(w, kind)}</td>"
            f"<td>{r._delta_kind(w, a, kind)}</td>"
            f"<td>{r._delta_kind(w, b, kind)}</td></tr>"
        )
    head = "".join(
        r._sortable_th(h, t)
        for h, t in (
            ("Metric", "text"),
            ("Static $2,500 uncapped (RSI $38,405 slot)", "text"),
            ("Uncapped monthly-step 1% compound", "text"),
            ("One $250k wallet, cash-capped", "text"),
            ("Δ (wallet − static)", "text"),
            ("Δ (wallet − uncapped compound)", "text"),
        )
    )
    return (
        f'<table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table>"
    )


def _trade_table(trades: list[r.OverlayTrade], *, open_book: bool = False) -> str:
    if not trades:
        return '<p class="small">No trades.</p>'
    rows = sorted(trades, key=lambda t: ((t.closed or date.min), t.system, t.symbol))
    body = ""
    for t in rows:
        d_close = t.closed.strftime("%Y-%m-%d") if t.closed else ""
        stop_s = f"${t.stop_used:,.2f}" if t.stop_used else "—"
        risk_s = format_money(t.risk_dollar) if t.risk_dollar is not None else "—"
        eq_s = format_money(t.equity_bom) if t.equity_bom is not None else "—"
        cash_s = format_money(t.cash_before) if t.cash_before is not None else "—"
        want_s = format_money(t.desired_invested) if t.desired_invested is not None else "—"
        flag = "scaled" if t.scaled else ("full" if t.sized else "skip")
        body += (
            "<tr>"
            f"<td>{html_mod.escape(t.system)}</td>"
            f"<td>{r._symbol_link(t.symbol)}</td>"
            f"<td>{t.opened.strftime('%Y-%m-%d')}</td>"
            f"<td>{d_close}</td>"
            f"<td>{html_mod.escape(t.exit_type)}</td>"
            f"<td>{int(t.days)}</td>"
            f"<td>{stop_s}</td>"
            f"<td>{risk_s}</td>"
            f"<td>{eq_s}</td>"
            f"<td>{cash_s}</td>"
            f"<td>{want_s}</td>"
            f"<td>{r._fmt_num(t.shares, 1)}</td>"
            f"<td>{format_money(t.invested) if t.sized else '—'}</td>"
            f"<td>{html_mod.escape(flag)}</td>"
            f"<td class=\"{r._pnl_class(t.pnl_pct)}\">{r.monthly._fmt_pct(t.pnl_pct)}</td>"
            f"<td class=\"{r._pnl_class(t.overlay_pnl)}\">{r._fmt_money_signed(t.overlay_pnl) if t.sized else 'N/A'}</td>"
            f"<td>{html_mod.escape(t.stop_src if t.sized else t.skip_reason)}</td>"
            "</tr>"
        )
    labels = [
        ("System", "text"),
        ("Symbol", "text"),
        ("Opened", "date"),
        ("Closed" if not open_book else "—", "date"),
        ("Exit", "text"),
        ("Days", "num"),
        ("Stop used", "num"),
        ("Month 1%", "num"),
        ("BOM equity", "num"),
        ("Cash before fill", "num"),
        ("Desired $ (uncapped 1%)", "num"),
        ("Shares", "num"),
        ("$ deployed", "num"),
        ("Fill", "text"),
        ("PnL %", "num"),
        ("Wallet $", "num"),
        ("Size note", "text"),
    ]
    head = "".join(r._sortable_th(a, b) for a, b in labels)
    return (
        f'<table class="sortable"><thead><tr>{head}</tr></thead><tbody>'
        + body
        + "</tbody></table>"
    )


def _path_summary_table(
    *,
    static_pnl: float,
    static_n: int,
    static_peak: float,
    compound_end: float,
    compound_peak: float,
    compound_n: int,
    wallet_end: float,
    wallet_peak: float,
    wallet_n: int,
    wallet_scaled: int,
    wallet_skip: int,
) -> str:
    head = "".join(
        r._sortable_th(h, t)
        for h, t in (
            ("Book", "text"),
            ("Is this one $250k wallet?", "text"),
            ("Ending $ (as-of / implied)", "num"),
            ("Peak deployed", "num"),
            ("Sized closed N", "num"),
            ("Scaled / cash-skip", "text"),
            ("Read as", "text"),
        )
    )
    rows = [
        (
            "Static $2,500 uncapped",
            "No — each fill risks $2,500 with no cash brake; nine systems stacked",
            static_pnl + ACCOUNT,
            static_peak,
            static_n,
            "0 / 0",
            "Fantasy if read as one account (same class of error as the $10.7M all-years sum)",
        ),
        (
            "Uncapped monthly-step 1% compound",
            "Paper one pile, but no cash cap and no leverage brake",
            compound_end,
            compound_peak,
            compound_n,
            "0 / 0",
            "The $114 quadrillion path — math, not a broker",
        ),
        (
            "One $250k wallet, cash-capped",
            "Yes — cash = $250k start; deploy ≤ remaining cash",
            wallet_end,
            wallet_peak,
            wallet_n,
            f"{wallet_scaled} / {wallet_skip}",
            "The honest book for “I only have $250k across all systems”",
        ),
    ]
    body = ""
    for name, one, end, peak, n, sk, read in rows:
        body += (
            "<tr>"
            f"<td>{html_mod.escape(name)}</td>"
            f"<td>{html_mod.escape(one)}</td>"
            f"<td>{format_money(end)}</td>"
            f"<td>{format_money(peak)}</td>"
            f"<td>{n}</td>"
            f"<td>{html_mod.escape(sk)}</td>"
            f"<td class=\"small\">{html_mod.escape(read)}</td>"
            "</tr>"
        )
    return (
        f'<table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table>"
    )


def build_html(
    *,
    year: int,
    wallet: list[r.OverlayTrade],
    snaps: list[WalletSnap],
    ledger: dict[str, Any],
    static_shared: list[r.OverlayTrade],
    compound_shared: list[r.OverlayTrade],
    compound_snaps: list[Any],
    tables: dict[str, dict[str, Any]],
    sources: list[str],
    generated: datetime,
    verdict: str,
) -> str:
    now = generated.astimezone(ET)
    through_month = now.month if now.year == year else 12
    closed = [t for t in wallet if t.status == "closed"]
    sized_closed = [t for t in closed if t.sized]
    year_closed = [t for t in sized_closed if t.closed and t.closed.year == year]
    open_rows = [t for t in wallet if t.status == "open" and t.sized]
    skipped = [t for t in wallet if not t.sized]

    ytd = {sys: {"pnl": 0.0, "trades": 0, "wins": 0} for sys in SYSTEMS}
    for t in year_closed:
        ytd[t.system]["pnl"] += t.overlay_pnl
        ytd[t.system]["trades"] += 1
        if t.overlay_pnl > 0:
            ytd[t.system]["wins"] += 1
    open_by = {sys: [] for sys in SYSTEMS}
    for t in open_rows:
        open_by[t.system].append(t)
    open_tot = {sys: sum(t.overlay_pnl for t in rows) for sys, rows in open_by.items()}

    sh_cur = next((s for s in snaps if s.year == year and s.month == through_month), None)
    ytd_pnl = sum(v["pnl"] for v in ytd.values())
    open_unreal = sum(open_tot.values())

    cards = f"""
  <div class="card card-shared">
    <h3>One $250k wallet (as-of)</h3>
    <div class="metric">{format_money(ledger['end_equity'])}</div>
    <div class="small">Closed-only equity = cash {format_money(ledger['end_cash'])}
      + reserved {format_money(ledger['end_reserved'])}</div>
    <div class="small">If you mark opens: {format_money(ledger['end_mtm'])}
      (cash + reserved + open mark)</div>
    <div class="small">This month 1%: {format_money(sh_cur.risk_dollar) if sh_cur else '—'}
      · BOM equity {format_money(sh_cur.equity_start) if sh_cur else '—'}</div>
  </div>
  <div class="card">
    <h3>{year} realized on this wallet</h3>
    <div class="metric {r._pnl_class(ytd_pnl)}">{r._fmt_money_signed(ytd_pnl)}</div>
    <div class="small">{sum(v['trades'] for v in ytd.values())} sized closes</div>
    <div class="small">Open mark: <span class="{r._pnl_class(open_unreal)}">{r._fmt_money_signed(open_unreal)}</span>
      ({len(open_rows)} names)</div>
  </div>
  <div class="card">
    <h3>Fills vs cash</h3>
    <div class="metric">{ledger['n_full'] + ledger['n_scaled']}</div>
    <div class="small">Full-size {ledger['n_full']} · scaled to cash {ledger['n_scaled']}</div>
    <div class="small">Skipped no cash {ledger['n_skip_cash']} · cannot size {ledger['n_skip_size']}</div>
    <div class="small">Peak deployed {format_money(ledger['peak_reserved'])}
      (must stay ≤ equity — no leverage)</div>
  </div>"""
    for sys in SYSTEMS:
        y = ytd[sys]
        unreal = open_tot[sys]
        wr = (100.0 * y["wins"] / y["trades"]) if y["trades"] else 0.0
        cards += f"""
  <div class="card">
    <h3>{html_mod.escape(SYSTEM_EXPAND.get(sys, sys))} share of this wallet</h3>
    <div class="metric {r._pnl_class(y['pnl'])}">{r._fmt_money_signed(y['pnl'])}</div>
    <div class="small">YTD realized · {y['trades']} sized · {wr:.0f}% win</div>
    <div class="small">Open mark: <span class="{r._pnl_class(unreal)}">{r._fmt_money_signed(unreal)}</span>
      ({len(open_by[sys])})</div>
  </div>"""

    pivot_html, hist_html = c._pivot_and_hist(sized_closed, year=year, through_month=through_month)
    year_rows = year_end_rows(snaps, through=ASOF)
    row2010 = next((x for x in year_rows if x["year"] == 2010), None)
    last_row = year_rows[-1] if year_rows else None
    row2025 = next((x for x in year_rows if x["year"] == 2025), None)

    compound_years = c.year_end_rows(compound_snaps, through=ASOF)
    compound_last = compound_years[-1]["ending_equity"] if compound_years else 0.0
    compound_2010 = next((x for x in compound_years if x["year"] == 2010), None)

    static_sized = [t for t in static_shared if t.status == "closed" and t.sized]
    static_pnl = sum(t.overlay_pnl for t in static_sized)
    static_st = tables["FULL"]["static"]
    compound_st = tables["FULL"]["compound"]

    path_tbl = _path_summary_table(
        static_pnl=static_pnl,
        static_n=int(static_st.get("n") or 0),
        static_peak=float(static_st.get("peak_notional") or 0.0),
        compound_end=compound_last,
        compound_peak=float(compound_st.get("peak_notional") or 0.0),
        compound_n=int(compound_st.get("n") or 0),
        wallet_end=float(ledger["end_equity"]),
        wallet_peak=float(ledger["peak_reserved"]),
        wallet_n=int(tables["FULL"]["wallet"].get("n") or 0),
        wallet_scaled=int(ledger["n_scaled"]),
        wallet_skip=int(ledger["n_skip_cash"]),
    )

    eq2010 = row2010["ending_equity"] if row2010 else ACCOUNT
    jan2011 = row2010["next_1pct"] if row2010 else ACCOUNT * RISK_FRAC
    end_eq = last_row["ending_equity"] if last_row else ledger["end_equity"]
    end2025 = row2025["ending_equity"] if row2025 else end_eq
    c2010 = compound_2010["ending_equity"] if compound_2010 else None

    lead = f"""
<div class="lead">
<h2>After 16 years on one $250k wallet: {format_money(end_eq)}</h2>
<p>As-of {ASOF.isoformat()} Closed-only equity is
<strong>{format_money(end_eq)}</strong>
(cash {format_money(ledger['end_cash'])} + reserved
{format_money(ledger['end_reserved'])}).
Year-end 2025 was {format_money(end2025)}.
Marked opens would print {format_money(ledger['end_mtm'])}.
That is not {format_money(114_972_205_731_090_800.00)}
— about 174 million times smaller than the uncapped compound ending.</p>
<p>2010 on this wallet ended at <strong>{format_money(eq2010)}</strong>;
January 2011 1% = <strong>{format_money(jan2011)}</strong>
(your example was $450k / $4,500).
Uncapped shared compound 2010 ended at
{format_money(c2010) if c2010 is not None else '—'}
(that path still had no cash brake after 2010).</p>
<p><strong>Even {format_money(end_eq)} is not a Schwab balance.</strong>
The cash cap stops leverage, not capacity. After a few good years the first
tight-stop signal of the day often wants more than the whole wallet, so
scale-down puts you <em>all-in</em> on that one name. Later dollar columns
are paper compounding at sizes no DailyRun name would fill. Read 2010–2012
for a human-sized path. Not gold. Not DailyRun.</p>
</div>"""

    compare_sections = ""
    for sl, note in (
        ("IS", "In-Sample — entry before 2024-01-01. Cash path is one continuous wallet; OOS sizes depend on the IS path. Do not retune on OOS."),
        ("OOS", "Out-of-Sample — report-only. Wallet dollars here already felt the IS cash path."),
        ("FULL", verdict),
    ):
        compare_sections += f"""
<section>
<h2>Canonical compare · {sl}</h2>
<p class="small">{html_mod.escape(note)} Control columns are the uncapped books.
Candidate is the one-wallet cash cap. Sheet / Total PnL $ omitted. Click headers to sort.</p>
<div class="table-wrap">{_three_compare(tables[sl]['static'], tables[sl]['compound'], tables[sl]['wallet'])}</div>
</section>"""

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
  <p class="small muted">No sized wallet closes this month.</p>
</section>"""
            continue
        month_total = sum(t.overlay_pnl for t in month_trades)
        month_sections += f"""
<section class="month-section">
  <h2>{label} · <span class="{r._pnl_class(month_total)}">{r._fmt_money_signed(month_total)}</span> wallet</h2>
  <div class="table-wrap">{_trade_table(month_trades)}</div>
</section>"""

    open_html = _trade_table(open_rows, open_book=True) if open_rows else '<p class="small muted">No sized open wallet positions.</p>'
    skip_cash = [t for t in skipped if t.skip_reason in {"cash_empty", "cash_too_small"}]
    skip_html = (
        _trade_table(skip_cash[:200])
        if skip_cash
        else '<p class="small muted">No cash-skips.</p>'
    )
    if len(skip_cash) > 200:
        skip_note = f"<p class=\"small\">Showing first 200 of {len(skip_cash)} cash-skips. Full list in ALL_overlay_onaccount.csv.</p>"
    else:
        skip_note = ""

    sources_html = "".join(f"<li>{html_mod.escape(s)}</li>" for s in sources)
    gen_s = now.strftime("%Y-%m-%d %H:%M %Z")
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>One $250k wallet, cash-capped — {year}</title>
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
.card-shared {{ background:#ecfdf5; border-color:#6ee7b7; }}
.card h3 {{ margin:0 0 8px; font-size:13px; color:#475569; font-weight:700; }}
.metric {{ font-size:1.35rem; font-weight:700; line-height:1.2; }}
.small {{ font-size:12px; color:#64748b; }}
.muted {{ color:#94a3b8; }}
.pos {{ color:#16a34a; }} .neg {{ color:#dc2626; }}
section {{ margin-top:24px; }}
.month-section {{ border-top:1px solid #e2e8f0; padding-top:8px; }}
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
<h1>Monthly Backtest Report — {year} · one $250k wallet, cash-capped</h1>
<p class="sub">
Research size overlay. <strong>Not gold. Not DailyRun.</strong>
Does not replace <a href="monthly.html">monthly.html</a> (static $2,500 control)
or <a href="monthly_compound.html">monthly_compound.html</a> (uncapped compound).
Start cash <strong>$250,000</strong>. One book. All DailyRun systems share it.
Each month: <code>risk_dollar = 0.01 × beginning-of-month equity</code>
(Closed-only: cash + reserved cost). Mid-month closes do not change that month’s 1%,
but they do return cash for later fills.
Stop systems: <code>shares = risk_dollar / (entry − stop)</code>, then
<strong>clip so shares × entry ≤ cash</strong>.
Relative Strength Index (RSI): <code>invested = risk_dollar / 0.0651</code>
(IS freeze 6.51%), then the same cash clip.
No leverage: peak deployed ≤ equity. Generated {html_mod.escape(gen_s)}.
Click column headers to sort.
</p>
<div class="ask">
<h2>What you asked</h2>
<blockquote>{html_mod.escape(r.ORIGINAL_REQUEST)}</blockquote>
<blockquote>{html_mod.escape(r.FOLLOWUP_REQUEST)}</blockquote>
<blockquote>{html_mod.escape(c.COMPOUND_REQUEST)}</blockquote>
<blockquote>{html_mod.escape(PAUL_Q_REQUEST)}</blockquote>
<blockquote>{html_mod.escape(PAUL_WALLET_REQUEST)}</blockquote>
<h2>In plain English</h2>
<p>{html_mod.escape(PAUL_Q_PLAIN)}</p>
<p>{html_mod.escape(PAUL_WALLET_PLAIN)}</p>
</div>
<div class="warn">
<strong>No. $114,972,205,731,090,800.00 is not realistic.</strong>
That number is the uncapped shared compound path after years of every concurrent
name still taking a full 1% of a growing paper equity, with <em>no cash cap</em>.
Tight stops buy huge share counts. A $250k broker account cannot hold trillions.
Per-system $250k sleeves were also not your account. The static all-years sum on
<a href="monthly.html">monthly.html</a> ({format_money(static_pnl)} realized,
or {format_money(ACCOUNT + static_pnl)} if you add the $250k seed) is the same
class of error if you read it as one wallet.
The cash-capped ending ({format_money(ledger['end_equity'])}) is the
no-leverage math — still not money you could actually take out, because
later years often go all-in on one tight-stop name at sizes those stocks
would never fill.
</div>
{lead}
<div class="hold"><strong>{html_mod.escape(verdict)}</strong></div>
<section>
<h2>Three books at a glance</h2>
<p class="small">Same DailyRun fills. Only the size / cash rule changes. Click headers to sort.</p>
<div class="table-wrap">{path_tbl}</div>
</section>
<section>
<h2>Equity / 1% by year-end — one $250k wallet</h2>
<p class="small">This will not be quadrillions. Next year’s 1% is 1% of that year-end.
Your $450k / $4,500 example is the 2010 row → next Jan 1% column, now with a cash brake.</p>
{_year_table(year_rows)}
</section>
<div class="cards">{cards}</div>
<section>
<h2>Monthly realized wallet P&amp;L by system ({year})</h2>
<p class="small">Closed trades by exit month on the shared cash book. Total row pinned. Click headers to sort.</p>
{pivot_html}
</section>
<section>
<h2>All years — wallet realized $ (sized closed)</h2>
<p class="small">Cash-capped dollars. Total row stays at the bottom when you sort. Click headers to sort.</p>
{hist_html}
</section>
<section>
<h2>Cash ledger (how the $250k was tracked)</h2>
<p class="small">Start: cash = $250,000, reserved = $0, equity = $250,000.
On a fill: cash falls by dollars deployed; reserved rises by the same cost.
On a close: reserved falls by cost; cash rises by cost + realized P&amp;L
(proceeds). Equity (Closed-only) = cash + reserved = $250k + realized.
We do not mark historical opens to market for the 1% step — only realized
closes change next month’s 1%. Open names at as-of still sit in reserved.
Identity error this run: {ledger['identity_err']:.6f} (should be ~0).</p>
{_ledger_month_table(snaps)}
</section>
{compare_sections}
{month_sections}
<section>
<h2>Open positions (unrealized wallet $)</h2>
<p class="small">Sized with the entry month’s 1%, then clipped to cash that day.</p>
<div class="table-wrap">{open_html}</div>
</section>
<section>
<h2>Cash-skips (signal existed, no cash left)</h2>
<p class="small">Primary freeze is scale-down, not skip. Skip only when remaining
cash is under $1. Same-day fill order: older closes first, then new fills by
DailyRun system order then symbol. We did not shop other queues. {skip_note}</p>
<div class="table-wrap">{skip_html}</div>
</section>
<section>
<h2>Data sources</h2>
<ul class="sources">{sources_html}</ul>
<p class="small">Static control: <a href="monthly.html">monthly.html</a> ·
uncapped compound: <a href="monthly_compound.html">monthly_compound.html</a> ·
house vs $2,500: <a href="compare.html">compare.html</a> ·
compound compare: <a href="compare_compound.html">compare_compound.html</a> ·
RSI avg-loss write-up: <a href="rsi_avgloss.html">rsi_avgloss.html</a>.
Acronyms: Break and ReTest (BRT); Rocket Launcher (RL); Year High (YH); Magic Touch (MTS);
Weekly Pivot Break and Retest (WPBR); Relative Strength vs SPY (RS); StockBee (SB);
Volume Zone (VZ); Relative Strength Index (RSI); In-Sample (IS); Out-of-Sample (OOS);
Annualized Rate of Return (Ann ROR); Maximum Drawdown (Max DD); beginning-of-month (BOM);
mark-to-market (MTM).</p>
</section>
{r.monthly._SORTABLE_TABLE_SCRIPT}
</body></html>"""


def _append_baseline(
    *,
    verdict: str,
    year_rows: list[dict[str, Any]],
    ledger: dict[str, Any],
    tables: dict[str, dict[str, Any]],
    static_pnl: float,
    compound_end: float,
) -> None:
    path = OUT_DIR / "BASELINE.md"
    old = path.read_text(encoding="utf-8") if path.is_file() else ""
    marker = "## Addendum — one $250k wallet (cash-capped)"
    if marker in old:
        old = old.split(marker)[0].rstrip() + "\n\n"
    y2010 = next((x for x in year_rows if x["year"] == 2010), None)
    last = year_rows[-1] if year_rows else None
    w = tables["FULL"]["wallet"]
    st = tables["FULL"]["static"]
    cd = tables["FULL"]["compound"]
    lines = [
        marker,
        "",
        "**Status:** Research size path. **Not gold. Not DailyRun.** OOS report-only.",
        "",
        "## What you asked",
        "",
        f"> {PAUL_Q_REQUEST}",
        "",
        f"> {PAUL_WALLET_REQUEST}",
        "",
        "## In plain English",
        "",
        PAUL_Q_PLAIN,
        "",
        PAUL_WALLET_PLAIN,
        "",
        "## Selection",
        "",
        "- Paul: $114 quadrillion is not a real account; he has **$250k across all systems**, not $250k per system.",
        "- Start **$250,000 cash**. One book. All DailyRun-wired systems share it.",
        "- `risk_dollar = 0.01 × start-of-month equity` after prior realized overlay PnL (Closed-only: cash + reserved cost).",
        "- Mid-month: closes do not change that month’s 1%; they do return cash.",
        "- RSI IS avg-loss freeze **6.509607%** (do not retune on OOS). Then cash clip.",
        "- Hard cap: deploy ≤ available cash. **Scale-down to remaining cash** (primary). Skip only if cash < $1.",
        "- No leverage: peak notional ≤ equity. Tight-stop 1% that implies $2M of one name is clipped; risk then < 1%.",
        "- Same-day fill order (frozen, not shopped): older closes; then entries by DailyRun system order then symbol; then same-day exits.",
        f"- Decision: **{verdict}**",
        "",
        "## Frozen knobs (delta from uncapped compound)",
        "",
        "- CONTROL A = static $2,500 / RSI $38,405 slot (`monthly.html`).",
        "- CONTROL B = uncapped monthly-step 1% (`monthly_compound.html`). Do not replace those pages.",
        "- CANDIDATE = one-wallet cash cap. Entries, exits, universes unchanged.",
        "- IS = entry_date < 2024-01-01. OOS report-only. Cash path is continuous (OOS sizes depend on IS).",
        "",
        "## Cash ledger",
        "",
        "- cash = undeployed dollars. reserved = cost of opens. equity = cash + reserved = $250k + realized.",
        "- Fill: cash -= deployed; reserved += deployed.",
        "- Close: reserved -= cost; cash += cost + overlay PnL (proceeds).",
        "- 1% uses Closed-only equity (no historical mark-to-market on opens).",
        f"- Identity |cash+reserved − (250k+realized)| = {ledger.get('identity_err')}",
        f"- Peak reserved (deployed) = ${ledger.get('peak_reserved'):,.2f}",
        f"- Full-size fills = {ledger.get('n_full')}; scaled = {ledger.get('n_scaled')}; "
        f"cash-skip = {ledger.get('n_skip_cash')}; cannot-size = {ledger.get('n_skip_size')}",
        "",
        "## 2010 / as-of ending equity",
        "",
    ]
    if y2010:
        lines.append(
            f"- Wallet 2010 ending equity **${y2010['ending_equity']:,.2f}**; "
            f"January 2011 1% **${y2010['next_1pct']:,.2f}**."
        )
    if last:
        lines.append(
            f"- As-of {ASOF.isoformat()} ending equity **${last['ending_equity']:,.2f}** "
            f"(cash ${ledger.get('end_cash'):,.2f} + reserved ${ledger.get('end_reserved'):,.2f}). "
            f"MTM-with-opens ${ledger.get('end_mtm'):,.2f}."
        )
    lines += [
        f"- Uncapped shared compound as-of ending (fantasy): **${compound_end:,.2f}**.",
        f"- Static uncapped realized sum: **${static_pnl:,.2f}** "
        f"(+ $250k seed = ${ACCOUNT + static_pnl:,.2f}) — not one wallet.",
        "",
        "## Honesty",
        "",
        "- $114,972,205,731,090,800 is not tradable. No broker funds that notional from $250k.",
        "- Nine $250k sleeves ≠ one account.",
        "- Cash-skips change the mix vs the uncapped pages. Judge quality on this book, not dollar nostalgia.",
        "- Smaller dollars are the constraint working, not a failed system.",
        "- $661M is still not a bank balance: cash cap stops leverage, not capacity. Tight stops often all-in the first fill of the day. Read 2010–2012.",
        "- Picking KEEP from this same history would be in-sample selection. We are not adopting.",
        "",
        "## FULL quality",
        "",
        f"- Static N={st.get('n')} WR={st.get('win_pct')} Avg%={st.get('avg_pnl_pct')} "
        f"PF={st.get('pf')} AnnROR$250k={st.get('ann_ror_250k')} MaxDD={st.get('max_dd')} "
        f"Calmar={st.get('calmar')} Sharpe={st.get('sharpe')} peak$={st.get('peak_notional')}",
        f"- Uncapped compound N={cd.get('n')} WR={cd.get('win_pct')} Avg%={cd.get('avg_pnl_pct')} "
        f"PF={cd.get('pf')} AnnROR$250k={cd.get('ann_ror_250k')} MaxDD={cd.get('max_dd')} "
        f"peak$={cd.get('peak_notional')}",
        f"- Wallet N={w.get('n')} WR={w.get('win_pct')} Avg%={w.get('avg_pnl_pct')} "
        f"PF={w.get('pf')} AnnROR$250k={w.get('ann_ror_250k')} MaxDD={w.get('max_dd')} "
        f"Calmar={w.get('calmar')} Sharpe={w.get('sharpe')} "
        f"mean$={w.get('mean_notional')} peak$={w.get('peak_notional')} "
        f"end_equity=${ledger.get('end_equity'):,.2f}",
        "",
    ]
    path.write_text(old + "\n".join(lines) + "\n", encoding="utf-8")


def _append_hypothesis(verdict: str) -> None:
    path = OUT_DIR / "HYPOTHESIS.md"
    old = path.read_text(encoding="utf-8") if path.is_file() else ""
    marker = "## Addendum — one $250k wallet (cash-capped)"
    if marker in old:
        old = old.split(marker)[0].rstrip() + "\n\n"
    text = f"""{marker}

| Field | Fill in |
|-------|---------|
| **Evidence** | Paul: $114Q is not real; he has $250k across ALL systems, not $250k each |
| **Hypothesis** | A hard cash cap (scale-down, no leverage) turns the uncapped compound fantasy into a one-wallet dollar path; % mix may change because later same-day names get skipped |
| **Single knob** | CASH CAP + one wallet. Monthly 1% schedule and RSI 6.51% freeze stay. Scale-down vs skip frozen as scale-down |
| Frozen settings | House entries/exits/universes/pins. RSI 6.509607% IS freeze. Mid-month 1% freeze. Fill order: older closes, then system then symbol |
| Alternatives | CONTROL A = static $2,500 (`monthly.html`). CONTROL B = uncapped compound (`monthly_compound.html`). CANDIDATE = one-wallet cash cap |
| **Decision** | {verdict} |
| PO sign-off | no |
| DailyRun | not wired |

- [x] One knob (cash cap / one wallet)
- [x] OOS report-only
- [ ] Adopt — **not adopting**
"""
    path.write_text(old + text, encoding="utf-8")


def run() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    paths = r._resolve_paths()
    sources = r._sources_from_paths(paths)
    sources.append(
        "on-account: one $250k wallet; BOM 1%; scale-down to remaining cash; "
        "RSI IS 6.51% freeze then cash clip; no leverage"
    )

    static_shared: list[r.OverlayTrade] = []
    for sys in SYSTEMS:
        static_shared.extend(_static_book(sys))

    compound_shared, compound_snaps = c.run_compound_book(static_shared)
    wallet, snaps, ledger = run_wallet_book(static_shared)
    r.write_overlay_csv(wallet, OUT_DIR / "ALL_overlay_onaccount.csv")

    print(
        f"[wallet] sized={ledger['n_full'] + ledger['n_scaled']} "
        f"full={ledger['n_full']} scaled={ledger['n_scaled']} "
        f"skip_cash={ledger['n_skip_cash']} skip_size={ledger['n_skip_size']} "
        f"end_equity={ledger['end_equity']:.2f} end_cash={ledger['end_cash']:.2f} "
        f"reserved={ledger['end_reserved']:.2f} peak_reserved={ledger['peak_reserved']:.2f} "
        f"identity_err={ledger['identity_err']:.6f}"
    )

    def sliced(trades: list[r.OverlayTrade], sl: str) -> list[r.OverlayTrade]:
        return r.slice_trades([t for t in trades if t.status == "closed"], sl)

    tables: dict[str, dict[str, Any]] = {}
    for sl in ("IS", "OOS", "FULL"):
        tables[sl] = {
            "static": _stats_path(sliced(static_shared, sl)),
            "compound": _stats_path(sliced(compound_shared, sl)),
            "wallet": _stats_wallet(sliced(wallet, sl)),
        }
    verdict = _verdict(tables["FULL"]["wallet"], ledger)
    tables["FULL"]["verdict"] = verdict

    year_rows = year_end_rows(snaps, through=ASOF)
    y2010 = next((x for x in year_rows if x["year"] == 2010), None)
    if y2010:
        print(
            f"[wallet] 2010 end={y2010['ending_equity']:.2f} "
            f"Jan2011 1%={y2010['next_1pct']:.2f}"
        )
    print(f"[verdict] {verdict}")

    compound_years = c.year_end_rows(compound_snaps, through=ASOF)
    compound_end = compound_years[-1]["ending_equity"] if compound_years else 0.0
    static_pnl = sum(
        t.overlay_pnl for t in static_shared if t.status == "closed" and t.sized
    )

    now = datetime.now(tz=ET)
    html = build_html(
        year=ASOF.year,
        wallet=wallet,
        snaps=snaps,
        ledger=ledger,
        static_shared=static_shared,
        compound_shared=compound_shared,
        compound_snaps=compound_snaps,
        tables=tables,
        sources=sources,
        generated=now,
        verdict=verdict,
    )
    out_html = OUT_DIR / "monthly_onaccount.html"
    out_html.write_text(html, encoding="utf-8")
    print(f"wrote {out_html}")
    _append_baseline(
        verdict=verdict,
        year_rows=year_rows,
        ledger=ledger,
        tables=tables,
        static_pnl=static_pnl,
        compound_end=compound_end,
    )
    _append_hypothesis(verdict)
    print(f"updated {OUT_DIR / 'BASELINE.md'} {OUT_DIR / 'HYPOTHESIS.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
