#!/usr/bin/env python3
"""One $250k wallet, 2× margin buying-power cap (research only).

Sibling monthly_onaccount.html is the 1× cash control — do not overwrite it.
This writes monthly_onaccount_2x.html.

Hard cap at every fill: open_notional ≤ 2 × Closed-only equity.
Scale-down to remaining buying power; skip if remaining BP < $1.
Same fill-order freeze as the cash book. Not gold. Not DailyRun.
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

_WSPEC = importlib.util.spec_from_file_location(
    "risk2500_monthly_onaccount_20260917",
    REPO / "tools" / "risk2500_monthly_onaccount_20260917.py",
)
w1 = importlib.util.module_from_spec(_WSPEC)
assert _WSPEC.loader is not None
sys.modules["risk2500_monthly_onaccount_20260917"] = w1
_WSPEC.loader.exec_module(w1)

STAMP = r.STAMP
OUT_DIR = r.OUT_DIR
ACCOUNT = r.ACCOUNT
RISK_FRAC = 0.01
MIN_DEPLOY = 1.0
LEVERAGE = 2.0
ASOF = r.ASOF
SYSTEMS = r.SYSTEMS
SYSTEM_EXPAND = r.SYSTEM_EXPAND
ET = r.ET
SYS_RANK = {sys: i for i, sys in enumerate(SYSTEMS)}

MARGIN_REQUEST = (
    "thanks. also, we would be capped to invest a total of the account "
    "value x 2 (to take advantage of margin) at any single point. how do "
    "we account for the real world limitation?"
)
MARGIN_PLAIN = (
    "Fidelity-style buying power: at any moment the sum of stock you have "
    "open cannot be more than twice what the account is worth. One $250,000 "
    "wallet. Every DailyRun system shares it. Each month the 1% risk number "
    "is 1% of Closed-only equity (start plus realized overlay dollars — we "
    "do not invent a daily mark on open names to inflate the 2× cap). Stop "
    "systems still try shares = that 1% ÷ (entry − stop). Relative Strength "
    "Index (RSI) still uses the In-Sample (IS) average-loser freeze 6.51%: "
    "dollars invested = that month’s 1% ÷ 0.0651. Then a hard cap: after a "
    "fill, open notional must stay ≤ 2 × equity. If the next signal would "
    "breach, we scale the order down to remaining buying power "
    "(2 × equity − open notional). If remaining buying power is about $0 "
    "(under $1), we skip. Tight stops that want a huge share count get "
    "clipped the same way — risk on that fill is then less than 1%, and we "
    "label it. When a trade closes, that notional frees and buying power "
    "comes back. Same-day order matches the cash book: older closes first, "
    "then new fills by DailyRun system then symbol, then same-day exits. "
    "We do not flatten existing names if a loser shrinks equity and the "
    "old book briefly sits above the new 2× — we only gate new fills. "
    "Year-end equity stays a finite number. That is how we account for "
    "the real-world margin cap."
)
HOW_WE_ACCOUNT = (
    "Buying-power ledger: equity = $250k + realized (Closed-only; no "
    "fantasy mark-to-market). Open notional = cost of names still open. "
    "Remaining buying power = 2 × equity − open notional. New fills clip "
    "to that remainder (or skip if it is under $1). Cash on the ledger "
    "can go negative — that negative is the margin loan. The 1× cash page "
    "is the no-leverage control; this page is the 2× cap Paul just stated."
)


@dataclass
class WalletSnap:
    year: int
    month: int
    equity_start: float
    cash_start: float
    reserved_start: float
    bp_start: float
    risk_dollar: float
    realized_pnl: float
    equity_end: float
    cash_end: float
    reserved_end: float
    bp_end: float
    n_entries: int
    n_full: int
    n_scaled: int
    n_skip_bp: int
    n_skip_size: int
    n_risk_lt_1pct: int
    n_closes: int
    peak_reserved: float


def _sys_key(t: r.OverlayTrade) -> tuple[int, str, str]:
    return (SYS_RANK.get(t.system, 99), t.system, t.symbol)


def _buying_power(cash: float, reserved: float) -> float:
    equity = cash + reserved
    return LEVERAGE * equity - reserved


def _risk_note(desired: r.OverlayTrade, shares: float, invested: float) -> tuple[str, bool]:
    """Label when clip makes stop-risk (or RSI slot) less than the month’s 1%."""
    risk = float(desired.risk_dollar or 0.0)
    lt = False
    bits: list[str] = []
    if desired.system == "RSI":
        want = float(desired.invested or 0.0)
        if want > 0 and invested + 1e-6 < want:
            bits.append("rsi_slot_lt_1pct_typical")
            lt = True
    elif desired.stop_used and desired.entry > desired.stop_used and shares > 0:
        actual = shares * (desired.entry - desired.stop_used)
        if risk > 0 and actual + 0.01 < risk:
            bits.append(f"risk_lt_1pct:{actual:.2f}<{risk:.2f}")
            lt = True
    return ";".join(bits), lt


def _clip_to_bp(desired: r.OverlayTrade, bp: float) -> tuple[r.OverlayTrade, bool]:
    """Scale-down to remaining buying power. Skip if BP < MIN_DEPLOY."""
    extra = {
        "cash_before": float(bp),
        "desired_invested": float(desired.invested) if desired.sized else 0.0,
        "scaled": False,
    }
    if not desired.sized:
        return (
            r.OverlayTrade(
                **{
                    **desired.__dict__,
                    **extra,
                    "skip_reason": desired.skip_reason or "cannot_size",
                }
            ),
            False,
        )
    if bp < MIN_DEPLOY:
        return (
            r.OverlayTrade(
                **{
                    **desired.__dict__,
                    **extra,
                    "shares": 0.0,
                    "invested": 0.0,
                    "overlay_pnl": 0.0,
                    "sized": False,
                    "scaled": False,
                    "skip_reason": "bp_empty",
                }
            ),
            False,
        )
    invested = min(float(desired.invested), float(bp))
    if invested < MIN_DEPLOY:
        return (
            r.OverlayTrade(
                **{
                    **desired.__dict__,
                    **extra,
                    "shares": 0.0,
                    "invested": 0.0,
                    "overlay_pnl": 0.0,
                    "sized": False,
                    "scaled": False,
                    "skip_reason": "bp_too_small",
                }
            ),
            False,
        )
    scaled = invested + 1e-6 < float(desired.invested)
    shares = invested / desired.entry
    overlay_pnl = (desired.pnl_pct / 100.0) * invested
    note = desired.stop_src or ""
    risk_lt = False
    if scaled:
        extra_note, risk_lt = _risk_note(desired, shares, invested)
        note = (note + ";").lstrip(";") + f"scaled_to_bp:{invested:.2f}"
        if extra_note:
            note += ";" + extra_note
    return (
        r.OverlayTrade(
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
        ),
        risk_lt,
    )


def run_margin_book(
    trades: list[r.OverlayTrade],
) -> tuple[list[r.OverlayTrade], list[WalletSnap], dict[str, Any]]:
    """One wallet. Open notional ≤ 2 × Closed-only equity on new fills."""
    empty_ledger = {
        "n_full": 0,
        "n_scaled": 0,
        "n_skip_bp": 0,
        "n_skip_size": 0,
        "n_risk_lt_1pct": 0,
        "peak_reserved": 0.0,
        "peak_equity": ACCOUNT,
        "peak_loan": 0.0,
        "end_cash": ACCOUNT,
        "end_reserved": 0.0,
        "end_equity": ACCOUNT,
        "end_bp": LEVERAGE * ACCOUNT,
        "end_mtm": ACCOUNT,
        "realized": 0.0,
        "identity_err": 0.0,
        "n_fill_cap_ok": 0,
        "max_reserved_over_2x": 0.0,
    }
    if not trades:
        return [], [], empty_ledger

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
    peak_loan = 0.0
    max_over = 0.0
    n_fill_cap_ok = 0
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
        bp_s = _buying_power(cash, reserved)
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
        n_entries = n_full = n_scaled = n_skip_bp = n_skip_size = n_closes = 0
        n_risk_lt = 0
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
                bp = _buying_power(cash, reserved)
                sized, risk_lt = _clip_to_bp(desired, bp)
                out.append(sized)
                if sized.sized:
                    cash -= sized.invested
                    reserved += sized.invested
                    eq_now = cash + reserved
                    cap = LEVERAGE * eq_now
                    if reserved <= cap + 1e-4:
                        n_fill_cap_ok += 1
                    else:
                        max_over = max(max_over, reserved - cap)
                    if reserved > peak_reserved:
                        peak_reserved = reserved
                    if reserved > peak_res_m:
                        peak_res_m = reserved
                    loan = max(0.0, -cash)
                    if loan > peak_loan:
                        peak_loan = loan
                    if sized.scaled:
                        n_scaled += 1
                    else:
                        n_full += 1
                    if risk_lt:
                        n_risk_lt += 1
                    if sized.status == "closed" and sized.closed is not None:
                        pending_close[sized.closed].append(sized)
                elif sized.skip_reason in {"bp_empty", "bp_too_small"}:
                    n_skip_bp += 1
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
            eq_after = cash + reserved
            over = reserved - LEVERAGE * eq_after
            if over > max_over:
                max_over = over

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
                bp_start=bp_s,
                risk_dollar=risk,
                realized_pnl=realized_m,
                equity_end=equity_end,
                cash_end=cash,
                reserved_end=reserved,
                bp_end=_buying_power(cash, reserved),
                n_entries=n_entries,
                n_full=n_full,
                n_scaled=n_scaled,
                n_skip_bp=n_skip_bp,
                n_skip_size=n_skip_size,
                n_risk_lt_1pct=n_risk_lt,
                n_closes=n_closes,
                peak_reserved=peak_res_m,
            )
        )

    open_mtm = sum(t.overlay_pnl for t in out if t.status == "open" and t.sized)
    n_risk_lt_all = sum(s.n_risk_lt_1pct for s in snaps)
    ledger = {
        "n_full": sum(1 for t in out if t.sized and not t.scaled),
        "n_scaled": sum(1 for t in out if t.sized and t.scaled),
        "n_skip_bp": sum(
            1 for t in out if (not t.sized) and t.skip_reason in {"bp_empty", "bp_too_small"}
        ),
        "n_skip_size": sum(
            1
            for t in out
            if (not t.sized) and t.skip_reason not in {"bp_empty", "bp_too_small"}
        ),
        "n_risk_lt_1pct": n_risk_lt_all,
        "peak_reserved": peak_reserved,
        "peak_equity": peak_equity,
        "peak_loan": peak_loan,
        "end_cash": cash,
        "end_reserved": reserved,
        "end_equity": cash + reserved,
        "end_bp": _buying_power(cash, reserved),
        "end_mtm": cash + reserved + open_mtm,
        "realized": realized,
        "identity_err": abs((cash + reserved) - (ACCOUNT + realized)),
        "n_fill_cap_ok": n_fill_cap_ok,
        "max_reserved_over_2x": max(0.0, max_over),
    }
    return out, snaps, ledger


def year_end_rows(snaps: list[WalletSnap], *, through: date) -> list[dict[str, Any]]:
    by_year: dict[int, list[WalletSnap]] = defaultdict(list)
    for s in snaps:
        by_year[s.year].append(s)
    last_eq = ACCOUNT
    last_cash = ACCOUNT
    last_res = 0.0
    last_bp = LEVERAGE * ACCOUNT
    rows: list[dict[str, Any]] = []
    for y in range(2010, through.year + 1):
        ys = by_year.get(y)
        if ys:
            last_eq = ys[-1].equity_end
            last_cash = ys[-1].cash_end
            last_res = ys[-1].reserved_end
            last_bp = ys[-1].bp_end
            jan_risk = ys[0].risk_dollar
            jan_eq = ys[0].equity_start
            realized = sum(s.realized_pnl for s in ys)
            n_scaled = sum(s.n_scaled for s in ys)
            n_skip = sum(s.n_skip_bp for s in ys)
            n_full = sum(s.n_full for s in ys)
            n_risk_lt = sum(s.n_risk_lt_1pct for s in ys)
        else:
            jan_risk = RISK_FRAC * last_eq
            jan_eq = last_eq
            realized = 0.0
            n_scaled = n_skip = n_full = n_risk_lt = 0
        note = ""
        if y == through.year and (through.month < 12 or through.day < 31):
            note = f"realized through {through.isoformat()} (year not finished)"
        rows.append(
            {
                "year": y,
                "ending_equity": last_eq,
                "ending_cash": last_cash,
                "ending_reserved": last_res,
                "ending_bp": last_bp,
                "ending_loan": max(0.0, -last_cash),
                "next_1pct": RISK_FRAC * last_eq,
                "jan_1pct": jan_risk,
                "jan_equity": jan_eq,
                "realized": realized,
                "n_full": n_full,
                "n_scaled": n_scaled,
                "n_skip_bp": n_skip,
                "n_risk_lt_1pct": n_risk_lt,
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
    closed = [t for t in trades if t.status == "closed"]
    sized = [t for t in closed if t.sized]
    mean_ov = (sum(t.invested for t in sized) / len(sized)) if sized else r.RISK_DOLLARS
    return r.book_stats(closed, use_overlay=True, cash_ann=float(mean_ov), dd_seed=ACCOUNT)


def _verdict(wallet: dict[str, Any], ledger: dict[str, Any]) -> str:
    n = wallet.get("n") or 0
    peak = ledger.get("peak_reserved") or 0.0
    end_eq = ledger.get("end_equity") or ACCOUNT
    return (
        "HOLD — one $250k wallet with a 2x margin cap (open notional <= 2x "
        f"equity). Ending equity {format_money(end_eq)}; peak deployed "
        f"{format_money(peak)}. Finite, unlike the uncapped quadrillion path. "
        "Scaled fills that hit remaining buying power risk less than 1%. "
        f"Mix can change vs uncapped because BP-skips drop later names "
        f"(sized N={n}). Not gold. Not DailyRun."
    )


def _year_table(rows: list[dict[str, Any]]) -> str:
    head = "".join(
        r._sortable_th(h, t)
        for h, t in (
            ("Year-end", "num"),
            ("Ending equity (Closed-only)", "num"),
            ("Cash (neg = margin loan)", "num"),
            ("Open notional", "num"),
            ("Remaining BP (2×eq − open)", "num"),
            ("That year’s Jan 1%", "num"),
            ("Next Jan 1%", "num"),
            ("Realized $ that year", "num"),
            ("Full-size fills", "num"),
            ("Scaled to BP", "num"),
            ("Skipped (no BP)", "num"),
            ("Risk < 1% (clip)", "num"),
            ("Note", "text"),
        )
    )
    body = ""
    tot_real = tot_full = tot_scaled = tot_skip = tot_lt = 0
    last = rows[-1] if rows else None
    for row in rows:
        tot_real += row["realized"]
        tot_full += int(row["n_full"])
        tot_scaled += int(row["n_scaled"])
        tot_skip += int(row["n_skip_bp"])
        tot_lt += int(row["n_risk_lt_1pct"])
        body += (
            "<tr>"
            f"<td>{row['year']}</td>"
            f"<td>{format_money(row['ending_equity'])}</td>"
            f"<td>{format_money(row['ending_cash'])}</td>"
            f"<td>{format_money(row['ending_reserved'])}</td>"
            f"<td>{format_money(row['ending_bp'])}</td>"
            f"<td>{format_money(row['jan_1pct'])}</td>"
            f"<td>{format_money(row['next_1pct'])}</td>"
            f"<td class=\"{r._pnl_class(row['realized'])}\">{r._fmt_money_signed(row['realized'])}</td>"
            f"<td>{row['n_full']}</td>"
            f"<td>{row['n_scaled']}</td>"
            f"<td>{row['n_skip_bp']}</td>"
            f"<td>{row['n_risk_lt_1pct']}</td>"
            f"<td class=\"small\">{html_mod.escape(row['note'])}</td>"
            "</tr>"
        )
    if last:
        body += (
            '<tr class="total-row"><th>Total / last</th>'
            f"<td>{format_money(last['ending_equity'])}</td>"
            f"<td>{format_money(last['ending_cash'])}</td>"
            f"<td>{format_money(last['ending_reserved'])}</td>"
            f"<td>{format_money(last['ending_bp'])}</td>"
            f"<td>{format_money(last['jan_1pct'])}</td>"
            f"<td>{format_money(last['next_1pct'])}</td>"
            f"<td class=\"{r._pnl_class(tot_real)}\">{r._fmt_money_signed(tot_real)}</td>"
            f"<td>{tot_full}</td><td>{tot_scaled}</td><td>{tot_skip}</td><td>{tot_lt}</td>"
            "<td class=\"small\">Ending $ = last year-end; counts and realized $ are sums</td></tr>"
        )
    return (
        '<p class="small">Closed-only ledger: equity = $250k + realized. '
        "Cash can be negative (margin debit). Remaining buying power = "
        "2 × equity − open notional. Total row pinned. Click headers to sort.</p>"
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
            ("BOM open notional", "num"),
            ("BOM remaining BP", "num"),
            ("Month 1%", "num"),
            ("Entries", "num"),
            ("Full", "num"),
            ("Scaled", "num"),
            ("BP-skip", "num"),
            ("Size-skip", "num"),
            ("Risk &lt; 1%", "num"),
            ("Closes", "num"),
            ("Realized $", "num"),
            ("EOM equity", "num"),
            ("EOM remaining BP", "num"),
            ("Peak open notional", "num"),
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
            f"<td>{format_money(s.bp_start)}</td>"
            f"<td>{format_money(s.risk_dollar)}</td>"
            f"<td>{s.n_entries}</td>"
            f"<td>{s.n_full}</td>"
            f"<td>{s.n_scaled}</td>"
            f"<td>{s.n_skip_bp}</td>"
            f"<td>{s.n_skip_size}</td>"
            f"<td>{s.n_risk_lt_1pct}</td>"
            f"<td>{s.n_closes}</td>"
            f"<td class=\"{r._pnl_class(s.realized_pnl)}\">{r._fmt_money_signed(s.realized_pnl)}</td>"
            f"<td>{format_money(s.equity_end)}</td>"
            f"<td>{format_money(s.bp_end)}</td>"
            f"<td>{format_money(s.peak_reserved)}</td>"
            "</tr>"
        )
    if snaps:
        tot_e = sum(s.n_entries for s in snaps)
        tot_f = sum(s.n_full for s in snaps)
        tot_sc = sum(s.n_scaled for s in snaps)
        tot_sk = sum(s.n_skip_bp for s in snaps)
        tot_sz = sum(s.n_skip_size for s in snaps)
        tot_lt = sum(s.n_risk_lt_1pct for s in snaps)
        tot_cl = sum(s.n_closes for s in snaps)
        tot_r = sum(s.realized_pnl for s in snaps)
        last = snaps[-1]
        peak_all = max(s.peak_reserved for s in snaps)
        body += (
            '<tr class="total-row"><th>Total / last</th>'
            f"<td>{format_money(last.equity_end)}</td>"
            f"<td>{format_money(last.cash_end)}</td>"
            f"<td>{format_money(last.reserved_end)}</td>"
            f"<td>{format_money(last.bp_end)}</td>"
            "<td>—</td>"
            f"<td>{tot_e}</td><td>{tot_f}</td><td>{tot_sc}</td>"
            f"<td>{tot_sk}</td><td>{tot_sz}</td><td>{tot_lt}</td><td>{tot_cl}</td>"
            f"<td class=\"{r._pnl_class(tot_r)}\">{r._fmt_money_signed(tot_r)}</td>"
            f"<td>{format_money(last.equity_end)}</td>"
            f"<td>{format_money(last.bp_end)}</td>"
            f"<td>{format_money(peak_all)}</td></tr>"
        )
    return (
        '<p class="small">Buying-power ledger by month. New fills clip so '
        "open notional ≤ 2 × equity. Total row pinned. Click headers to sort.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def _four_compare(
    static: dict[str, Any],
    compound: dict[str, Any],
    cash: dict[str, Any],
    margin: dict[str, Any],
) -> str:
    body = ""
    for label, key, kind in r.CANONICAL_METRIC_ROWS:
        if is_excluded_html_compare_label(label):
            continue
        a, b, k, m = static.get(key), compound.get(key), cash.get(key), margin.get(key)
        body += (
            f"<tr><td>{html_mod.escape(label)}</td>"
            f"<td>{r._fmt_kind(a, kind)}</td>"
            f"<td>{r._fmt_kind(b, kind)}</td>"
            f"<td>{r._fmt_kind(k, kind)}</td>"
            f"<td>{r._fmt_kind(m, kind)}</td>"
            f"<td>{r._delta_kind(m, k, kind)}</td>"
            f"<td>{r._delta_kind(m, b, kind)}</td></tr>"
        )
    head = "".join(
        r._sortable_th(h, t)
        for h, t in (
            ("Metric", "text"),
            ("Static $2,500 uncapped (RSI $38,405 slot)", "text"),
            ("Uncapped monthly-step 1% (fantasy)", "text"),
            ("1× cash wallet (no leverage)", "text"),
            ("2× margin wallet", "text"),
            ("Δ (2× − 1× cash)", "text"),
            ("Δ (2× − uncapped fantasy)", "text"),
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
        bp_s = format_money(t.cash_before) if t.cash_before is not None else "—"
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
            f"<td>{bp_s}</td>"
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
        ("Remaining BP before fill", "num"),
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
    cash_end: Optional[float],
    cash_peak: Optional[float],
    cash_n: Optional[int],
    cash_scaled: Optional[int],
    cash_skip: Optional[int],
    margin_end: float,
    margin_peak: float,
    margin_n: int,
    margin_scaled: int,
    margin_skip: int,
) -> str:
    head = "".join(
        r._sortable_th(h, t)
        for h, t in (
            ("Book", "text"),
            ("Cap at any moment", "text"),
            ("Ending $ (as-of / implied)", "num"),
            ("Peak deployed", "num"),
            ("Sized closed N", "num"),
            ("Scaled / skipped", "text"),
            ("Read as", "text"),
        )
    )

    def _money(v: Optional[float]) -> str:
        return format_money(v) if v is not None else "—"

    def _n(v: Optional[int]) -> str:
        return str(v) if v is not None else "—"

    cash_sk = (
        f"{cash_scaled} / {cash_skip}"
        if cash_scaled is not None and cash_skip is not None
        else "see monthly_onaccount.html"
    )
    rows = [
        (
            "Static $2,500 uncapped",
            "None — each fill risks $2,500; nine systems stacked",
            static_pnl + ACCOUNT,
            static_peak,
            static_n,
            "0 / 0",
            "Fantasy if read as one account",
        ),
        (
            "Uncapped monthly-step 1% compound",
            "None — paper pile, no cash or margin brake",
            compound_end,
            compound_peak,
            compound_n,
            "0 / 0",
            "The ~$114 quadrillion path — math, not a broker",
        ),
        (
            "1× cash wallet (sibling)",
            "Open notional ≤ 1 × equity (no leverage)",
            cash_end,
            cash_peak,
            cash_n,
            cash_sk,
            "Cash-only control — monthly_onaccount.html",
        ),
        (
            "2× margin wallet (this page)",
            "Open notional ≤ 2 × equity (Fidelity-style BP)",
            margin_end,
            margin_peak,
            margin_n,
            f"{margin_scaled} / {margin_skip}",
            "The real-world margin cap Paul just stated",
        ),
    ]
    body = ""
    for name, cap, end, peak, n, sk, read in rows:
        body += (
            "<tr>"
            f"<td>{html_mod.escape(name)}</td>"
            f"<td>{html_mod.escape(cap)}</td>"
            f"<td>{_money(end) if not isinstance(end, str) else html_mod.escape(end)}</td>"
            f"<td>{_money(peak) if not isinstance(peak, str) else html_mod.escape(str(peak))}</td>"
            f"<td>{_n(n) if not isinstance(n, str) else html_mod.escape(str(n))}</td>"
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
    cash_ledger: Optional[dict[str, Any]],
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
    loan_now = max(0.0, -float(ledger["end_cash"]))

    cards = f"""
  <div class="card card-shared">
    <h3>One $250k wallet · 2× margin (as-of)</h3>
    <div class="metric">{format_money(ledger['end_equity'])}</div>
    <div class="small">Closed-only equity = cash {format_money(ledger['end_cash'])}
      + open notional {format_money(ledger['end_reserved'])}</div>
    <div class="small">Margin loan (if cash &lt; 0): {format_money(loan_now)}</div>
    <div class="small">Remaining BP: {format_money(ledger['end_bp'])}
      · If you mark opens: {format_money(ledger['end_mtm'])}</div>
    <div class="small">This month 1%: {format_money(sh_cur.risk_dollar) if sh_cur else '—'}
      · BOM equity {format_money(sh_cur.equity_start) if sh_cur else '—'}</div>
  </div>
  <div class="card">
    <h3>{year} realized on this 2× book</h3>
    <div class="metric {r._pnl_class(ytd_pnl)}">{r._fmt_money_signed(ytd_pnl)}</div>
    <div class="small">{sum(v['trades'] for v in ytd.values())} sized closes</div>
    <div class="small">Open mark: <span class="{r._pnl_class(open_unreal)}">{r._fmt_money_signed(open_unreal)}</span>
      ({len(open_rows)} names)</div>
  </div>
  <div class="card">
    <h3>Fills vs buying power</h3>
    <div class="metric">{ledger['n_full'] + ledger['n_scaled']}</div>
    <div class="small">Full-size {ledger['n_full']} · scaled to BP {ledger['n_scaled']}</div>
    <div class="small">Skipped no BP {ledger['n_skip_bp']} · cannot size {ledger['n_skip_size']}</div>
    <div class="small">Risk &lt; 1% after clip: {ledger['n_risk_lt_1pct']}</div>
    <div class="small">Peak deployed {format_money(ledger['peak_reserved'])}
      · peak loan {format_money(ledger['peak_loan'])}</div>
  </div>"""
    for sys in SYSTEMS:
        y = ytd[sys]
        unreal = open_tot[sys]
        wr = (100.0 * y["wins"] / y["trades"]) if y["trades"] else 0.0
        cards += f"""
  <div class="card">
    <h3>{html_mod.escape(SYSTEM_EXPAND.get(sys, sys))} share of this 2× wallet</h3>
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
    cash_st = tables["FULL"].get("cash") or {}

    cash_end = None
    cash_peak = None
    cash_n = None
    cash_scaled = None
    cash_skip = None
    if cash_ledger:
        cash_end = float(cash_ledger.get("end_equity") or 0.0)
        cash_peak = float(cash_ledger.get("peak_reserved") or 0.0)
        cash_scaled = int(cash_ledger.get("n_scaled") or 0)
        cash_skip = int(cash_ledger.get("n_skip_cash") or 0)
    if cash_st.get("n") is not None:
        cash_n = int(cash_st.get("n") or 0)
        if cash_end is None and cash_st.get("peak_notional") is not None:
            cash_peak = float(cash_st.get("peak_notional") or 0.0)

    path_tbl = _path_summary_table(
        static_pnl=static_pnl,
        static_n=int(static_st.get("n") or 0),
        static_peak=float(static_st.get("peak_notional") or 0.0),
        compound_end=compound_last,
        compound_peak=float(compound_st.get("peak_notional") or 0.0),
        compound_n=int(compound_st.get("n") or 0),
        cash_end=cash_end,
        cash_peak=cash_peak,
        cash_n=cash_n,
        cash_scaled=cash_scaled,
        cash_skip=cash_skip,
        margin_end=float(ledger["end_equity"]),
        margin_peak=float(ledger["peak_reserved"]),
        margin_n=int(tables["FULL"]["margin"].get("n") or 0),
        margin_scaled=int(ledger["n_scaled"]),
        margin_skip=int(ledger["n_skip_bp"]),
    )

    eq2010 = row2010["ending_equity"] if row2010 else ACCOUNT
    jan2011 = row2010["next_1pct"] if row2010 else ACCOUNT * RISK_FRAC
    end_eq = last_row["ending_equity"] if last_row else ledger["end_equity"]
    end2025 = row2025["ending_equity"] if row2025 else end_eq
    c2010 = compound_2010["ending_equity"] if compound_2010 else None
    cash_end_s = format_money(cash_end) if cash_end is not None else "see monthly_onaccount.html"

    lead = f"""
<div class="lead">
<h2>How we account for the 2× cap</h2>
<p>{html_mod.escape(HOW_WE_ACCOUNT)}</p>
<h2>After 16 years on 2× buying power: {format_money(end_eq)}</h2>
<p>As-of {ASOF.isoformat()} Closed-only equity is
<strong>{format_money(end_eq)}</strong>
(cash {format_money(ledger['end_cash'])} + open notional
{format_money(ledger['end_reserved'])}; remaining BP
{format_money(ledger['end_bp'])}).
Year-end 2025 was {format_money(end2025)}.
Marked opens would print {format_money(ledger['end_mtm'])}.
That is a finite account — not {format_money(114_972_205_731_090_800.00)}
on the uncapped compound page, and
{"above" if (cash_end is not None and end_eq > cash_end) else "beside"}
the 1× cash book ({cash_end_s}).</p>
<p>2010 on this 2× wallet ended at <strong>{format_money(eq2010)}</strong>;
January 2011 1% = <strong>{format_money(jan2011)}</strong>.
Uncapped shared compound 2010 ended at
{format_money(c2010) if c2010 is not None else '—'}
(that path still had no buying-power brake after 2010).</p>
</div>"""

    compare_sections = ""
    for sl, note in (
        (
            "IS",
            "In-Sample — entry before 2024-01-01. The 2× path is one continuous "
            "wallet; OOS sizes depend on the IS path. Do not retune on OOS.",
        ),
        (
            "OOS",
            "Out-of-Sample — report-only. Wallet dollars here already felt the IS path.",
        ),
        ("FULL", verdict),
    ):
        cash_col = tables[sl].get("cash") or {}
        compare_sections += f"""
<section>
<h2>Canonical compare · {sl}</h2>
<p class="small">{html_mod.escape(note)} Four books: static $2,500, uncapped
compound fantasy, 1× cash, 2× margin. Sheet / Total PnL $ omitted.
Click headers to sort.</p>
<div class="table-wrap">{_four_compare(tables[sl]['static'], tables[sl]['compound'], cash_col, tables[sl]['margin'])}</div>
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
  <p class="small muted">No sized 2× wallet closes this month.</p>
</section>"""
            continue
        month_total = sum(t.overlay_pnl for t in month_trades)
        month_sections += f"""
<section class="month-section">
  <h2>{label} · <span class="{r._pnl_class(month_total)}">{r._fmt_money_signed(month_total)}</span> 2× wallet</h2>
  <div class="table-wrap">{_trade_table(month_trades)}</div>
</section>"""

    open_html = (
        _trade_table(open_rows, open_book=True)
        if open_rows
        else '<p class="small muted">No sized open 2× positions.</p>'
    )
    skip_bp = [t for t in skipped if t.skip_reason in {"bp_empty", "bp_too_small"}]
    skip_html = (
        _trade_table(skip_bp[:200])
        if skip_bp
        else '<p class="small muted">No buying-power skips.</p>'
    )
    if len(skip_bp) > 200:
        skip_note = (
            f'<p class="small">Showing first 200 of {len(skip_bp)} BP-skips. '
            "Full list in ALL_overlay_onaccount_2x.csv.</p>"
        )
    else:
        skip_note = ""

    sources_html = "".join(f"<li>{html_mod.escape(s)}</li>" for s in sources)
    gen_s = now.strftime("%Y-%m-%d %H:%M %Z")
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>One $250k wallet, 2× margin cap — {year}</title>
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
<h1>Monthly Backtest Report — {year} · one $250k wallet, 2× margin cap</h1>
<p class="sub">
Research size overlay. <strong>Not gold. Not DailyRun.</strong>
Control pages stay
<a href="monthly.html">monthly.html</a> (static $2,500),
<a href="monthly_compound.html">monthly_compound.html</a> (uncapped compound),
and <a href="monthly_onaccount.html">monthly_onaccount.html</a> (1× cash — not overwritten).
Paper start $250,000. Each month:
<code>risk_dollar = 0.01 × beginning-of-month Closed-only equity</code>.
Deploy cap: <code>open_notional ≤ 2 × equity</code>. Scale to remaining
buying power; skip if remaining BP &lt; $1.
Relative Strength Index (RSI): <code>invested = risk_dollar / 0.0651</code>
then the same BP clip. Generated {html_mod.escape(gen_s)}.
Click column headers to sort.
</p>
<div class="ask">
<h2>What you asked</h2>
<blockquote>{html_mod.escape(MARGIN_REQUEST)}</blockquote>
<h2>In plain English</h2>
<p>{html_mod.escape(MARGIN_PLAIN)}</p>
</div>
{lead}
<div class="hold"><strong>{html_mod.escape(verdict)}</strong></div>
<div class="warn">
<strong>The 2× cap uses Closed-only equity, not a made-up daily mark.</strong>
Open names are carried at cost for the buying-power test. A loser can shrink
equity so an already-open book sits above the new 2× until those names close —
we do not force-flatten. New fills still clip or skip. Peak loan is the most
negative cash (margin debit) we recorded.
</div>
<section>
<h2>Four books — one glance</h2>
<p class="small">Same DailyRun fills. Only the wallet / cap changes.
Click headers to sort.</p>
<div class="table-wrap">{path_tbl}</div>
</section>
<section>
<h2>Equity / 1% / buying power by year-end — 2× wallet</h2>
<p class="small">This is the finite path. Year-end equity is $250k plus realized
overlay P&amp;L through December (2026 = through as-of). Next year’s 1% is 1% of
that year-end. Total row is not needed here (one row per year).</p>
{_year_table(year_rows)}
</section>
<div class="cards">{cards}</div>
<section>
<h2>Monthly realized 2× P&amp;L by system ({year})</h2>
<p class="small">Closed trades by exit month on this buying-power book.
Total row pinned. Click column headers to sort.</p>
{pivot_html}
</section>
<section>
<h2>All years — 2× overlay realized $ (sized closed)</h2>
<p class="small">Buying-power-capped dollars. Total row stays at the bottom when
you sort. Click headers to sort.</p>
{hist_html}
</section>
<section>
<h2>Buying-power ledger by month</h2>
{_ledger_month_table(snaps)}
</section>
{compare_sections}
{month_sections}
<section>
<h2>Open positions (unrealized 2× $)</h2>
<p class="small">Sized with the 1% from the entry month, then clipped to remaining BP.</p>
<div class="table-wrap">{open_html}</div>
</section>
<section>
<h2>Skipped — remaining buying power ~ $0</h2>
{skip_note}
<div class="table-wrap">{skip_html}</div>
</section>
<section>
<h2>Data sources</h2>
<ul class="sources">{sources_html}</ul>
<p class="small">Static control: <a href="monthly.html">monthly.html</a> ·
uncapped compound: <a href="monthly_compound.html">monthly_compound.html</a> ·
1× cash wallet: <a href="monthly_onaccount.html">monthly_onaccount.html</a> ·
2× overlay CSV: ALL_overlay_onaccount_2x.csv.
Acronyms: Break and ReTest (BRT); Rocket Launcher (RL); Year High (YH); Magic Touch (MTS);
Weekly Pivot Break and Retest (WPBR); Relative Strength vs SPY (RS); StockBee (SB);
Volume Zone (VZ); Relative Strength Index (RSI); In-Sample (IS); Out-of-Sample (OOS);
Annualized Rate of Return (Ann ROR); Maximum Drawdown (Max DD); beginning-of-month (BOM);
buying power (BP).</p>
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
    cash_end: Optional[float],
) -> None:
    path = OUT_DIR / "BASELINE.md"
    old = path.read_text(encoding="utf-8") if path.is_file() else ""
    marker = "## Addendum — 2× margin buying-power cap"
    if marker in old:
        old = old.split(marker)[0].rstrip() + "\n\n"
    y2010 = next((x for x in year_rows if x["year"] == 2010), None)
    last = year_rows[-1] if year_rows else None
    lines = [
        marker,
        "",
        "**Status:** Research size path. **Not gold. Not DailyRun.** OOS report-only.",
        "",
        "## What you asked",
        "",
        f"> {MARGIN_REQUEST}",
        "",
        "## In plain English",
        "",
        MARGIN_PLAIN,
        "",
        "## How we account for it",
        "",
        HOW_WE_ACCOUNT,
        "",
        "## Selection",
        "",
        "- Paul: capped to invest a total of account value × 2 at any single point.",
        "- Start **$250,000**. One book. All DailyRun-wired systems share it.",
        "- `risk_dollar = 0.01 × start-of-month Closed-only equity`.",
        "- Mid-month: closes do not change that month’s 1%; they free notional / BP.",
        "- RSI IS avg-loss freeze **6.509607%** (do not retune on OOS). Then BP clip.",
        "- Hard cap on **new fills**: open notional ≤ 2 × equity. Scale to remaining BP. Skip if BP < $1.",
        "- Tight-stop 1% that implies a huge share count is clipped; risk then < 1% (labeled).",
        "- Do not flatten existing names if a loser shrinks 2× equity under current open notional.",
        "- Same-day fill order (match cash book, not shopped): older closes; then entries by DailyRun system order then symbol; then same-day exits.",
        f"- Decision: **{verdict}**",
        "",
        "## Frozen knobs (delta from 1× cash book)",
        "",
        "- CONTROL A = static $2,500 / RSI $38,405 slot (`monthly.html`).",
        "- CONTROL B = uncapped monthly-step 1% (`monthly_compound.html`).",
        "- CONTROL C = one-wallet cash cap (`monthly_onaccount.html`). Do not replace that page.",
        "- CANDIDATE = one-wallet **2×** buying-power cap. Entries, exits, universes unchanged.",
        "- IS = entry_date < 2024-01-01. OOS report-only. Path is continuous (OOS sizes depend on IS).",
        "",
        "## Buying-power ledger",
        "",
        "- equity = cash + reserved cost = $250k + realized (Closed-only; no historical MTM on the 2× test).",
        "- Fill: cash -= deployed; reserved += deployed. Cash may go negative (margin loan).",
        "- Close: reserved -= cost; cash += cost + overlay PnL.",
        f"- Remaining BP = 2 × equity − reserved. Identity |cash+reserved − (250k+realized)| = {ledger.get('identity_err')}",
        f"- Peak reserved (deployed) = ${ledger.get('peak_reserved', 0):,.2f}",
        f"- Peak margin loan = ${ledger.get('peak_loan', 0):,.2f}",
        f"- Full-size fills = {ledger.get('n_full')}; scaled = {ledger.get('n_scaled')}; BP-skip = {ledger.get('n_skip_bp')}; cannot-size = {ledger.get('n_skip_size')}; risk&lt;1% clip = {ledger.get('n_risk_lt_1pct')}",
        f"- New-fill cap holds: n_fill_cap_ok={ledger.get('n_fill_cap_ok')}; max reserved over 2× after losers = ${ledger.get('max_reserved_over_2x', 0):,.2f}",
        "",
        "## 2010 / as-of ending equity",
        "",
    ]
    if y2010:
        lines.append(
            f"- 2× wallet 2010 ending equity **${y2010['ending_equity']:,.2f}**; "
            f"January 2011 1% **${y2010['next_1pct']:,.2f}**."
        )
    if last:
        lines.append(
            f"- As-of {ASOF.isoformat()} ending equity **${last['ending_equity']:,.2f}** "
            f"(cash ${ledger.get('end_cash', 0):,.2f} + reserved ${ledger.get('end_reserved', 0):,.2f}). "
            f"MTM-with-opens ${ledger.get('end_mtm', 0):,.2f}."
        )
    lines.append(
        f"- Uncapped shared compound as-of ending (fantasy): **${compound_end:,.2f}**."
    )
    if cash_end is not None:
        lines.append(f"- 1× cash wallet as-of ending: **${cash_end:,.2f}**.")
    lines.append(
        f"- Static uncapped realized sum: **${static_pnl:,.2f}** "
        f"(+ $250k seed = ${static_pnl + ACCOUNT:,.2f}) — not one wallet."
    )
    lines += [
        "",
        "## Honesty",
        "",
        "- The 2× cap is the Fidelity-style buying-power rule Paul stated. Not gold. Not DailyRun.",
        "- 1× cash page stays the no-leverage control.",
        "- Uncapped compound after ~2012 is not tradable.",
        "- BP-skips change the mix vs the uncapped pages.",
        "- Picking KEEP from this same history would be in-sample selection. We are not adopting.",
        "",
        "## FULL quality",
        "",
    ]
    st = tables["FULL"]["static"]
    cd = tables["FULL"]["compound"]
    mg = tables["FULL"]["margin"]
    cash = tables["FULL"].get("cash") or {}
    lines.append(
        f"- Static N={st.get('n')} WR={st.get('win_pct')} Avg%={st.get('avg_pnl_pct')} "
        f"PF={st.get('pf')} AnnROR$250k={st.get('ann_ror_250k')} MaxDD={st.get('max_dd')} "
        f"peak$={st.get('peak_notional')}"
    )
    lines.append(
        f"- Uncapped compound N={cd.get('n')} WR={cd.get('win_pct')} Avg%={cd.get('avg_pnl_pct')} "
        f"PF={cd.get('pf')} AnnROR$250k={cd.get('ann_ror_250k')} MaxDD={cd.get('max_dd')} "
        f"peak$={cd.get('peak_notional')}"
    )
    if cash.get("n") is not None:
        lines.append(
            f"- 1× cash N={cash.get('n')} WR={cash.get('win_pct')} Avg%={cash.get('avg_pnl_pct')} "
            f"PF={cash.get('pf')} AnnROR$250k={cash.get('ann_ror_250k')} MaxDD={cash.get('max_dd')} "
            f"peak$={cash.get('peak_notional')}"
        )
    lines.append(
        f"- 2× margin N={mg.get('n')} WR={mg.get('win_pct')} Avg%={mg.get('avg_pnl_pct')} "
        f"PF={mg.get('pf')} AnnROR$250k={mg.get('ann_ror_250k')} MaxDD={mg.get('max_dd')} "
        f"Calmar={mg.get('calmar')} Sharpe={mg.get('sharpe')} "
        f"mean$={mg.get('mean_notional')} peak$={mg.get('peak_notional')} "
        f"end_equity=${ledger.get('end_equity', 0):,.2f}"
    )
    lines.append("")
    path.write_text(old + "\n".join(lines) + "\n", encoding="utf-8")


def _append_hypothesis(verdict: str) -> None:
    path = OUT_DIR / "HYPOTHESIS.md"
    old = path.read_text(encoding="utf-8") if path.is_file() else ""
    marker = "## Addendum — 2× margin buying-power cap"
    if marker in old:
        old = old.split(marker)[0].rstrip() + "\n\n"
    text = f"""{marker}

| Field | Fill in |
|-------|---------|
| **Evidence** | Paul: capped to invest account value × 2 at any single point (margin) |
| **Hypothesis** | A 2× buying-power cap (scale-down / skip) turns the uncapped compound fantasy into a finite one-wallet path; more capacity than 1× cash, still not the quadrillion book |
| **Single knob** | BUYING-POWER CAP = 2× Closed-only equity. Monthly 1% and RSI 6.51% freeze stay. Same fill order as the 1× cash book |
| Frozen settings | House entries/exits/universes/pins. RSI 6.509607% IS freeze. Mid-month 1% freeze. Fill order: older closes, then system then symbol. 1× cash page not overwritten |
| Alternatives | CONTROL A = static $2,500 (`monthly.html`). CONTROL B = uncapped compound (`monthly_compound.html`). CONTROL C = 1× cash (`monthly_onaccount.html`). CANDIDATE = 2× margin |
| **Decision** | {verdict} |
| PO sign-off | no |
| DailyRun | not wired |

- [x] One knob (2× buying-power cap)
- [x] OOS report-only
- [ ] Adopt — **not adopting**
"""
    path.write_text(old + text, encoding="utf-8")


def run() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    paths = r._resolve_paths()
    sources = r._sources_from_paths(paths)
    sources.append(
        "on-account 2x: one $250k wallet; BOM 1%; scale-down to remaining "
        "buying power (2× equity − open notional); RSI IS 6.51% freeze then BP clip"
    )
    sources.append(
        "fill order (match cash book): older closes; DailyRun system then symbol; same-day exits"
    )

    static_shared: list[r.OverlayTrade] = []
    for sys in SYSTEMS:
        static_shared.extend(_static_book(sys))

    compound_shared, compound_snaps = c.run_compound_book(static_shared)
    margin, snaps, ledger = run_margin_book(static_shared)
    r.write_overlay_csv(margin, OUT_DIR / "ALL_overlay_onaccount_2x.csv")

    cash_book: list[r.OverlayTrade] = []
    cash_ledger: Optional[dict[str, Any]] = None
    cash_csv = OUT_DIR / "ALL_overlay_onaccount.csv"
    if cash_csv.is_file():
        cash_book = r.load_overlay_csv(cash_csv)
        sources.append("1× cash overlay: ALL_overlay_onaccount.csv (sibling)")
    cash_book2, _cash_snaps, cash_ledger = w1.run_wallet_book(static_shared)
    if not cash_book:
        cash_book = cash_book2
        sources.append("1× cash book recomputed in-memory from sibling engine (HTML not written)")
    else:
        # Prefer sibling CSV rows for N/mix; keep live ledger for ending $ if CSV lacks it.
        pass

    print(
        f"[2x] sized={ledger['n_full'] + ledger['n_scaled']} "
        f"full={ledger['n_full']} scaled={ledger['n_scaled']} "
        f"skip_bp={ledger['n_skip_bp']} skip_size={ledger['n_skip_size']} "
        f"risk_lt_1pct={ledger['n_risk_lt_1pct']} "
        f"end_equity={ledger['end_equity']:.2f} end_cash={ledger['end_cash']:.2f} "
        f"reserved={ledger['end_reserved']:.2f} peak_reserved={ledger['peak_reserved']:.2f} "
        f"peak_loan={ledger['peak_loan']:.2f} identity_err={ledger['identity_err']:.6f} "
        f"max_over_2x={ledger['max_reserved_over_2x']:.2f}"
    )
    if cash_ledger:
        print(
            f"[1x sibling engine] end_equity={cash_ledger['end_equity']:.2f} "
            f"peak_reserved={cash_ledger['peak_reserved']:.2f}"
        )

    def sliced(trades: list[r.OverlayTrade], sl: str) -> list[r.OverlayTrade]:
        return r.slice_trades([t for t in trades if t.status == "closed"], sl)

    tables: dict[str, dict[str, Any]] = {}
    for sl in ("IS", "OOS", "FULL"):
        tables[sl] = {
            "static": _stats_path(sliced(static_shared, sl)),
            "compound": _stats_path(sliced(compound_shared, sl)),
            "cash": _stats_wallet(sliced(cash_book, sl)),
            "margin": _stats_wallet(sliced(margin, sl)),
        }
    verdict = _verdict(tables["FULL"]["margin"], ledger)
    tables["FULL"]["verdict"] = verdict

    year_rows = year_end_rows(snaps, through=ASOF)
    y2010 = next((x for x in year_rows if x["year"] == 2010), None)
    if y2010:
        print(
            f"[2x] 2010 end={y2010['ending_equity']:.2f} "
            f"Jan2011 1%={y2010['next_1pct']:.2f}"
        )
    print(f"[verdict] {verdict}")

    compound_years = c.year_end_rows(compound_snaps, through=ASOF)
    compound_end = compound_years[-1]["ending_equity"] if compound_years else 0.0
    static_pnl = sum(
        t.overlay_pnl for t in static_shared if t.status == "closed" and t.sized
    )
    cash_end = float(cash_ledger["end_equity"]) if cash_ledger else None

    now = datetime.now(tz=ET)
    html = build_html(
        year=ASOF.year,
        wallet=margin,
        snaps=snaps,
        ledger=ledger,
        static_shared=static_shared,
        compound_shared=compound_shared,
        compound_snaps=compound_snaps,
        cash_ledger=cash_ledger,
        tables=tables,
        sources=sources,
        generated=now,
        verdict=verdict,
    )
    out_html = OUT_DIR / "monthly_onaccount_2x.html"
    out_html.write_text(html, encoding="utf-8")
    print(f"wrote {out_html}")
    _append_baseline(
        verdict=verdict,
        year_rows=year_rows,
        ledger=ledger,
        tables=tables,
        static_pnl=static_pnl,
        compound_end=compound_end,
        cash_end=cash_end,
    )
    _append_hypothesis(verdict)
    print(f"updated {OUT_DIR / 'BASELINE.md'} {OUT_DIR / 'HYPOTHESIS.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
