#!/usr/bin/env python3
"""3 universes × 2 size policies, all $7,500/mo + 10.5% margin (research only).

Stamp: drive/paul_experiments/risk2500_sys_matrix_20260917/
Does not overwrite risk2500_five_sys_20260917/monthly.html except a one-line pointer.

Books (Indicators / IND out):
  5-sys = StockBee (SB), Relative Strength Index (RSI), Volume Zone (VZ),
          Magic Touch (MTS), Rocket Launcher (RL)
  9-sys = house DailyRun set (Break and ReTest, VZ, Year High, RL, MTS,
          Weekly Pivot Break and Retest, Relative Strength vs SPY, SB, RSI)
  4-sys = 5-sys minus StockBee

Policies:
  reduced 0.3007% take-all (frozen r; do not re-search)
  1% sell winner

Not gold. Not DailyRun.
"""
from __future__ import annotations

import html as html_mod
import importlib.util
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))

from compare_format import format_money  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "risk2500_five_sys_20260917",
    REPO / "tools" / "risk2500_five_sys_20260917.py",
)
f = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules["risk2500_five_sys_20260917"] = f
_SPEC.loader.exec_module(f)

STAMP = "risk2500_sys_matrix_20260917"
OUT_DIR = REPO / "drive" / "paul_experiments" / STAMP
SIBLING = f.OUT_DIR
ACCOUNT = f.ACCOUNT
ASOF = f.ASOF
ET = f.ET
IS_CUT = f.IS_CUT
WITHDRAW = f.WITHDRAW
MARGIN_RATE = f.MARGIN_RATE
LEVERAGE = f.LEVERAGE
R_REDUCED = 0.003007  # 0.3007% frozen — do not re-search
R_ONE = 0.01

FIVE = f.FIVE
NINE = f.NINE
FOUR: tuple[str, ...] = tuple(s for s in FIVE if s != "SB")
FIVE_RANK = f.FIVE_RANK
NINE_RANK = f.NINE_RANK
FOUR_RANK = {sys: NINE_RANK.get(sys, 99) for sys in FOUR}

UNIVERSE_EXPAND = {
    "5-sys": (
        "StockBee (SB), Relative Strength Index (RSI), Volume Zone (VZ), "
        "Magic Touch (MTS), Rocket Launcher (RL)"
    ),
    "9-sys": (
        "Break and ReTest (BRT), Volume Zone (VZ), Year High (YH), "
        "Rocket Launcher (RL), Magic Touch (MTS), "
        "Weekly Pivot Break and Retest (WPBR), Relative Strength vs SPY (RS), "
        "StockBee (SB), Relative Strength Index (RSI)"
    ),
    "4-sys": (
        "Relative Strength Index (RSI), Volume Zone (VZ), Magic Touch (MTS), "
        "Rocket Launcher (RL) — five-system set minus StockBee (SB)"
    ),
}

ORIGINAL_REQUEST = (
    "can you run the following. all runs withdraw $7,500/month and charge 10.5% "
    "for margin. all using the 5 sys AND the 9 sys and 4 sys (5 sys minus SB) "
    "reduced stop 0.3007% max stop 1% sell winner include max drawdown as a "
    "percent for each line (monthly or yearly)"
)
PLAIN_ENGLISH = (
    "Six paper books, same wallet rules. Start $250,000. Every month pull "
    "$7,500 cash on the 1st (even if that means borrowing more). Pay 10.5% a "
    "year on whatever you borrowed. Open stock cost can be at most twice the "
    "account. Indicators (IND) is the old live sleeve (~−$40k, 35 lots, go-live "
    "2026); it is not DailyRun-wired; all books below exclude it. Three system "
    "sets: the five sleeves (StockBee, RSI, Volume Zone, Magic Touch, Rocket "
    "Launcher); the nine DailyRun sleeves; and the five minus StockBee. Two "
    "size rules: risk 0.3007% of the account each month and take every signal "
    "that still fits (shrink a fill if buying power is tight; skip only if "
    "leftover buying power is under $1); or risk 1% and, when a new signal "
    "cannot fit even shrunk, sell the most profitable open name then take the "
    "new one. RSI dollars in = that month’s risk ÷ 0.0651 (In-Sample average "
    "loser; do not retune after 2024). Other systems: shares = risk ÷ (entry "
    "− stop). Max drawdown % on every month and year line is the worst "
    "peak-to-trough drop of that book inside that month or year. Later-year "
    "trillions are capacity fiction — read 2010–2012 first. Not gold. Not DailyRun."
)

DD_DEF = (
    "Max drawdown % = peak-to-trough of that book’s equity inside the row’s "
    "window (month or year), walking time order so a new high resets the peak. "
    "Proxy (not a full daily mark): Closed-only equity (cash + open cost) after "
    "each event day (entries, exits, interest, $7,500 wire), plus one "
    "month-end mark-to-close of opens (last daily close on or before month-end). "
    "Yearly DD walks that same path inside the year. Running Max DD % is the "
    "same walk from 2010-01-01 through the row. Full-book Max DD % is the "
    "all-years walk. Closed-only equity does not move on a new fill (cash down, "
    "reserved up); it moves on realized P&L, interest, and wires. The month-end "
    "mark catches open losers the cost basis would hide."
)


def _systems_for(univ: str) -> tuple[str, ...]:
    if univ == "5-sys":
        return FIVE
    if univ == "9-sys":
        return NINE
    if univ == "4-sys":
        return FOUR
    raise ValueError(univ)


def _rank_for(univ: str) -> dict[str, int]:
    if univ == "5-sys":
        return FIVE_RANK
    if univ == "9-sys":
        return NINE_RANK
    return FOUR_RANK


def _book_specs() -> list[dict[str, Any]]:
    specs = []
    for univ in ("5-sys", "9-sys", "4-sys"):
        specs.append(
            {
                "key": f"{univ}_r3007",
                "univ": univ,
                "policy": "reduced 0.3007%",
                "short": f"{univ} · 0.3007% take-all",
                "risk_frac": R_REDUCED,
                "rotate": "none",
                "cap": (
                    f"{univ} · monthly risk 0.3007% of BOM equity · take-all / "
                    "scale to buying power · no rotation"
                ),
            }
        )
        specs.append(
            {
                "key": f"{univ}_1pct_sw",
                "univ": univ,
                "policy": "1% sell winner",
                "short": f"{univ} · 1% sell winner",
                "risk_frac": R_ONE,
                "rotate": "winner",
                "cap": (
                    f"{univ} · monthly risk 1% of BOM equity · if a new signal "
                    "cannot fit even scaled, sell the most profitable open"
                ),
            }
        )
    return specs


def spy_paths(spy: dict[str, Any]) -> dict[str, Any]:
    """Month-end + yearly Max DD% on the $250k SPY total-return path."""
    df = pd.read_csv(f.SPY_PATH)
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"]).sort_values("Date")
    df["Adj Close"] = pd.to_numeric(df["Adj Close"], errors="coerce")
    df = df.dropna(subset=["Adj Close"])
    df["d"] = df["Date"].dt.date
    df = df[(df["d"] >= date(2010, 1, 1)) & (df["d"] <= ASOF)]
    adj0 = float(spy["adj0"])
    df["eq"] = ACCOUNT * (df["Adj Close"] / adj0)
    daily = list(zip(df["d"].tolist(), df["eq"].astype(float).tolist()))
    full_dd = f._max_dd_pct([eq for _d, eq in daily])
    months: dict[tuple[int, int], dict[str, Any]] = {}
    years: dict[int, dict[str, Any]] = {}
    by_m: dict[tuple[int, int], list[float]] = {}
    by_y: dict[int, list[float]] = {}
    running: list[float] = []
    eom: dict[tuple[int, int], float] = {}
    for d, eq in daily:
        key = (d.year, d.month)
        by_m.setdefault(key, []).append(eq)
        by_y.setdefault(d.year, []).append(eq)
        running.append(eq)
        eom[key] = eq
    run_so_far: list[float] = []
    for y in range(2010, ASOF.year + 1):
        yvals = by_y.get(y, [])
        run_so_far.extend(yvals)
        years[y] = {
            "tr": float(spy["years"].get(y, {}).get("tr", 0.0)),
            "price": float(spy["years"].get(y, {}).get("price", 0.0)),
            "max_dd_pct": f._max_dd_pct(yvals),
            "running_max_dd_pct": f._max_dd_pct(run_so_far),
        }
        for m in range(1, 13):
            key = (y, m)
            if key not in by_m:
                continue
            months[key] = {
                "tr": eom[key],
                "max_dd_pct": f._max_dd_pct(by_m[key]),
                "running_max_dd_pct": f._max_dd_pct(
                    [eq for (yy, mm), vs in by_m.items() if (yy, mm) <= key for eq in vs]
                ),
            }
    return {
        "full_dd": full_dd,
        "months": months,
        "years": years,
        "tr_end": spy["tr_end"],
        "eq_2012": float(spy["years"].get(2012, {}).get("tr", 0.0)),
    }


def _fmt_pct(v: Any) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    if x != x:  # NaN
        return "—"
    return f"{x:.2f}%"


def _vs_spy(end: float, spy_tr: float) -> str:
    if spy_tr <= 0:
        return "—"
    return f"{end / spy_tr:,.2f}× SPY"


def _verdict(arms: list[dict[str, Any]], spy: dict[str, Any], spy_dd: dict[str, Any]) -> str:
    reduced = [a for a in arms if a["rotate"] == "none"]
    winners = [a for a in arms if a["rotate"] == "winner"]
    r_end = max(a["led"].end_equity for a in reduced)
    w_end = max(a["led"].end_equity for a in winners)
    r_dd = min(a["led"].max_dd_pct for a in reduced)
    w_dd = min(a["led"].max_dd_pct for a in winners)
    explode = w_end > r_end * 20 or w_end > spy["tr_end"] * 50
    bits = [
        "HOLD — do not adopt a universe cut or a 1% sell-winner rule from this "
        "one in-sample horse-race. Judge quality (win rate, average %, profit "
        "factor, Max drawdown %), not ending dollars."
    ]
    if explode:
        bits.append(
            f"Blunt: 1% sell-winner still explodes versus 0.3007% take-all "
            f"(best 1% paper end {format_money(w_end)} vs best reduced "
            f"{format_money(r_end)}; best 1% Max DD {_fmt_pct(w_dd)} vs "
            f"best reduced {_fmt_pct(r_dd)}). Selling the winner to cram the "
            f"next 1% lot is how later-year trillions show up. That is capacity "
            f"fiction, not a Fidelity balance."
        )
    else:
        bits.append(
            f"1% sell-winner did not dwarf 0.3007% by 20× on this freeze "
            f"(best 1% {format_money(w_end)} vs best reduced {format_money(r_end)}). "
            f"Still HOLD — same history picked the compare."
        )
    bits.append(
        f"SPY $250k total return {format_money(spy['tr_end'])} "
        f"(Max DD {_fmt_pct(spy_dd['full_dd'])}). Read 2010–2012 first. "
        "Not gold. Not DailyRun."
    )
    return " ".join(bits)


def _lead_table(arms: list[dict[str, Any]], spy: dict[str, Any], spy_dd: dict[str, Any]) -> str:
    head = f._sortable_head(
        [
            ("Universe", "text"),
            ("Policy", "text"),
            ("Ending equity", "num"),
            ("2010–2012 equity", "num"),
            ("Max DD% (full)", "num"),
            ("vs SPY", "text"),
            ("Interest", "num"),
            ("Withdrawn", "num"),
            ("Rotates / BP-skip", "text"),
        ]
    )
    body = ""
    rows = [
        (
            "SPY buy-hold",
            "Sit in S&P 500 tracker (SPY), dividends reinvested",
            spy["tr_end"],
            spy_dd["eq_2012"],
            spy_dd["full_dd"],
            "1.00× (yardstick)",
            0.0,
            0.0,
            "0 / 0",
        )
    ]
    for a in arms:
        led = a["led"]
        rows.append(
            (
                a["univ"],
                a["policy"],
                led.end_equity,
                led.eq_2012,
                led.max_dd_pct,
                _vs_spy(led.end_equity, spy["tr_end"]),
                led.interest,
                led.withdrawals,
                f"{led.n_rotate} / {led.n_skip_bp}",
            )
        )
    for rec in rows:
        univ, pol, end, y12, dd, vs, interest, wd, sk = rec
        body += (
            "<tr>"
            f"<td>{html_mod.escape(str(univ))}</td>"
            f"<td>{html_mod.escape(str(pol))}</td>"
            f"<td>{format_money(float(end))}</td>"
            f"<td>{format_money(float(y12))}</td>"
            f"<td>{_fmt_pct(dd)}</td>"
            f"<td>{html_mod.escape(str(vs))}</td>"
            f"<td>{format_money(float(interest))}</td>"
            f"<td>{format_money(float(wd))}</td>"
            f"<td>{html_mod.escape(str(sk))}</td>"
            "</tr>"
        )
    return (
        '<p class="small">2010–2012 equity = Closed-only year-end 2012. '
        "Max DD% (full) = peak-to-trough of the whole book (see Data sources). "
        "Click headers to sort.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def _year_table(arms: list[dict[str, Any]], spy: dict[str, Any], spy_dd: dict[str, Any]) -> str:
    pairs = [("Year-end", "num")]
    for a in arms:
        pairs += [
            (f"{a['short']} equity", "num"),
            (f"{a['short']} Max DD%", "num"),
            (f"{a['short']} running Max DD%", "num"),
        ]
    pairs += [
        ("SPY total return", "num"),
        ("SPY Max DD%", "num"),
        ("Note", "text"),
    ]
    head = f._sortable_head(pairs)
    body = ""
    for y in range(2010, ASOF.year + 1):
        cells = f"<td>{y}</td>"
        for a in arms:
            row = next((x for x in a["years"] if x["year"] == y), None)
            if row:
                cells += (
                    f"<td>{format_money(row['ending_equity'])}</td>"
                    f"<td>{_fmt_pct(row.get('max_dd_pct'))}</td>"
                    f"<td>{_fmt_pct(row.get('running_max_dd_pct'))}</td>"
                )
            else:
                cells += "<td>—</td><td>—</td><td>—</td>"
        sy = spy_dd["years"].get(y)
        cells += (
            f"<td>{format_money(sy['tr']) if sy else '—'}</td>"
            f"<td>{_fmt_pct(sy['max_dd_pct']) if sy else '—'}</td>"
        )
        note = f"through {ASOF.isoformat()}" if y == ASOF.year else ""
        if y <= 2012:
            note = (note + " · early-year checkpoint").strip(" ·")
        body += f"<tr>{cells}<td class=\"small\">{html_mod.escape(note)}</td></tr>"
    last = '<tr class="total-row"><th>Total / all years</th>'
    for a in arms:
        last += (
            f"<td>{format_money(a['led'].end_equity)}</td>"
            f"<td>{_fmt_pct(a['led'].max_dd_pct)}</td>"
            f"<td>{_fmt_pct(a['led'].max_dd_pct)}</td>"
        )
    last += (
        f"<td>{format_money(spy['tr_end'])}</td>"
        f"<td>{_fmt_pct(spy_dd['full_dd'])}</td>"
        "<td class=\"small\">Full-book Max DD% on the total row</td></tr>"
    )
    return (
        '<p class="small">Year Max DD% is peak-to-trough <em>inside that year</em>. '
        "Running Max DD% is from 2010 through that year-end. Total row pinned. "
        "Click headers to sort.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}{last}</tbody></table></div>"
    )


def _month_path_table(
    arms: list[dict[str, Any]], spy_dd: dict[str, Any]
) -> str:
    pairs = [("Month", "month")]
    for a in arms:
        pairs += [
            (f"{a['short']} EOM equity", "num"),
            (f"{a['short']} Max DD%", "num"),
            (f"{a['short']} running Max DD%", "num"),
        ]
    pairs += [("SPY TR EOM", "num"), ("SPY Max DD%", "num")]
    head = f._sortable_head(pairs)
    keys: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for a in arms:
        for s in a["snaps"]:
            k = (s.year, s.month)
            if k not in seen:
                seen.add(k)
                keys.append(k)
    keys.sort()
    body = ""
    for y, m in keys:
        cells = f"<td>{y}-{m:02d}</td>"
        for a in arms:
            snap = next((s for s in a["snaps"] if s.year == y and s.month == m), None)
            if snap:
                cells += (
                    f"<td>{format_money(snap.equity_end)}</td>"
                    f"<td>{_fmt_pct(snap.max_dd_pct)}</td>"
                    f"<td>{_fmt_pct(snap.running_max_dd_pct)}</td>"
                )
            else:
                cells += "<td>—</td><td>—</td><td>—</td>"
        sm = spy_dd["months"].get((y, m))
        cells += (
            f"<td>{format_money(sm['tr']) if sm else '—'}</td>"
            f"<td>{_fmt_pct(sm['max_dd_pct']) if sm else '—'}</td>"
        )
        body += f"<tr>{cells}</tr>"
    if keys:
        last = '<tr class="total-row"><th>Total / all years</th>'
        for a in arms:
            last += (
                f"<td>{format_money(a['led'].end_equity)}</td>"
                f"<td>{_fmt_pct(a['led'].max_dd_pct)}</td>"
                f"<td>{_fmt_pct(a['led'].max_dd_pct)}</td>"
            )
        last += (
            f"<td>{format_money(spy_dd['tr_end'])}</td>"
            f"<td>{_fmt_pct(spy_dd['full_dd'])}</td></tr>"
        )
        body += last
    return (
        '<p class="small">Month Max DD% is peak-to-trough <em>inside that month</em> '
        "(event-day Closed-only + month-end mark-to-close). Running Max DD% is "
        "from 2010 through that month. Total row pinned. Click headers to sort.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def _ledger_table(snaps: list[Any], led: Any) -> str:
    head = f._sortable_head(
        [
            ("Month", "month"),
            ("BOM equity", "num"),
            ("Month risk $", "num"),
            ("Entries", "num"),
            ("Full", "num"),
            ("Scaled", "num"),
            ("BP-skip", "num"),
            ("Rotates", "num"),
            ("Closes", "num"),
            ("Realized $", "num"),
            ("Interest $", "num"),
            ("Withdrawn $", "num"),
            ("EOM equity", "num"),
            ("EOM mark-to-close", "num"),
            ("Max DD%", "num"),
            ("Running Max DD%", "num"),
        ]
    )
    body = ""
    for s in snaps:
        body += (
            "<tr>"
            f"<td>{s.year}-{s.month:02d}</td>"
            f"<td>{format_money(s.equity_start)}</td>"
            f"<td>{format_money(s.risk_dollar)}</td>"
            f"<td>{s.n_entries}</td>"
            f"<td>{s.n_full}</td>"
            f"<td>{s.n_scaled}</td>"
            f"<td>{s.n_skip_bp}</td>"
            f"<td>{s.n_rotate}</td>"
            f"<td>{s.n_closes}</td>"
            f"<td class=\"{f.r._pnl_class(s.realized_pnl)}\">{f.r._fmt_money_signed(s.realized_pnl)}</td>"
            f"<td class=\"neg\">{format_money(s.interest)}</td>"
            f"<td>{format_money(s.withdrawals)}</td>"
            f"<td>{format_money(s.equity_end)}</td>"
            f"<td>{format_money(s.mtm_end)}</td>"
            f"<td>{_fmt_pct(s.max_dd_pct)}</td>"
            f"<td>{_fmt_pct(s.running_max_dd_pct)}</td>"
            "</tr>"
        )
    if snaps:
        last = snaps[-1]
        tot_r = sum(s.realized_pnl for s in snaps)
        tot_i = sum(s.interest for s in snaps)
        tot_w = sum(s.withdrawals for s in snaps)
        body += (
            '<tr class="total-row"><th>Total / all years</th>'
            f"<td>{format_money(last.equity_end)}</td><td>—</td>"
            f"<td>{sum(s.n_entries for s in snaps)}</td>"
            f"<td>{sum(s.n_full for s in snaps)}</td>"
            f"<td>{sum(s.n_scaled for s in snaps)}</td>"
            f"<td>{sum(s.n_skip_bp for s in snaps)}</td>"
            f"<td>{sum(s.n_rotate for s in snaps)}</td>"
            f"<td>{sum(s.n_closes for s in snaps)}</td>"
            f"<td class=\"{f.r._pnl_class(tot_r)}\">{f.r._fmt_money_signed(tot_r)}</td>"
            f"<td class=\"neg\">{format_money(tot_i)}</td>"
            f"<td>{format_money(tot_w)}</td>"
            f"<td>{format_money(led.end_equity)}</td>"
            f"<td>{format_money(led.end_mtm)}</td>"
            f"<td>{_fmt_pct(led.max_dd_pct)}</td>"
            f"<td>{_fmt_pct(led.max_dd_pct)}</td></tr>"
        )
    return (
        '<p class="small">Buying-power + interest ledger. Max DD% is inside the month; '
        "running is from 2010. Total row pinned. Click headers to sort.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def build_monthly(
    *,
    arms: list[dict[str, Any]],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
    verdict: str,
    sources: list[str],
    generated: datetime,
) -> str:
    now = generated.astimezone(ET)
    gen_s = now.strftime("%Y-%m-%d %H:%M %Z")
    cards = f"""
  <div class="card card-shared">
    <h3>SPY $250k since {html_mod.escape(spy['start_date'])} (total return)</h3>
    <div class="metric">{format_money(spy['tr_end'])}</div>
    <div class="small">{spy['tr_mult']:.2f}× · Max DD {_fmt_pct(spy_dd['full_dd'])}</div>
    <div class="small">2012 {format_money(spy_dd['eq_2012'])} · price-only {format_money(spy['price_end'])}</div>
  </div>"""
    for a in arms:
        led = a["led"]
        cards += f"""
  <div class="card">
    <h3>{html_mod.escape(a['short'])}</h3>
    <div class="metric">{format_money(led.end_equity)}</div>
    <div class="small">2012 {format_money(led.eq_2012)} · Max DD {_fmt_pct(led.max_dd_pct)}</div>
    <div class="small">vs SPY {_vs_spy(led.end_equity, spy['tr_end'])} · rot {led.n_rotate} · skip {led.n_skip_bp}</div>
  </div>"""

    ledgers = ""
    for a in arms:
        ledgers += f"""
<section>
<h2>Ledger — {html_mod.escape(a['short'])}</h2>
<p class="small">{html_mod.escape(a['cap'])}. {html_mod.escape(UNIVERSE_EXPAND[a['univ']])}.</p>
{_ledger_table(a['snaps'], a['led'])}
</section>"""

    compare_sections = ""
    col_map = {"IS": "stats_is", "OOS": "stats_oos", "FULL": "stats_full"}
    for sl, note in (
        ("IS", "In-Sample — entry before 2024-01-01. Path is continuous; do not retune OOS."),
        ("OOS", "Out-of-Sample — report-only. Wallet dollars already felt the IS path."),
        ("FULL", verdict),
    ):
        cols = [(a["short"], a[col_map[sl]]) for a in arms]
        compare_sections += f"""
<section>
<h2>Canonical compare · {sl}</h2>
<p class="small">{html_mod.escape(note)} Sheet / Total PnL $ omitted. Click headers to sort.</p>
<div class="table-wrap">{f._canonical_table(cols)}</div>
</section>"""

    sources_html = "".join(f"<li>{html_mod.escape(s)}</li>" for s in sources)
    early = ""
    for a in arms:
        early += (
            f"<li><strong>{html_mod.escape(a['short'])}</strong> — "
            f"2010 {format_money(a['led'].eq_2010)} · "
            f"2011 {format_money(a['led'].eq_2011)} · "
            f"2012 {format_money(a['led'].eq_2012)}</li>"
        )
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>6-book system matrix — $7,500 wd + 10.5% — {ASOF.year}</title>
<style>{f._css()}</style></head><body>
<h1>Monthly Backtest Report — {ASOF.year} · 5-sys / 9-sys / 4-sys × 0.3007% vs 1% sell-winner</h1>
<p class="sub">
Stamp <code>{STAMP}</code>. Research only. <strong>Not gold. Not DailyRun.</strong>
Indicators (IND) is the old live sleeve (~−$40k, 35 lots, go-live 2026); it is not
DailyRun-wired; all books below exclude it.
Generated {html_mod.escape(gen_s)}. Click column headers to sort.
</p>
<div class="ask">
<h2>What you asked</h2>
<blockquote>{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN_ENGLISH)}</p>
</div>
<div class="warn">
<strong>2010–2012 first.</strong> Later-year paper dollars can still be capacity
fiction (tight stops + a percent of a growing pile + 2× + selling winners to
make room). The honest read is the first three years versus S&amp;P 500 tracker
(SPY) total return. SPY 2010–2012:
{format_money(spy['years'].get(2010, {}).get('tr', 0))} /
{format_money(spy['years'].get(2011, {}).get('tr', 0))} /
{format_money(spy['years'].get(2012, {}).get('tr', 0))}.
<ul>{early}</ul>
</div>
<div class="hold"><strong>{html_mod.escape(verdict)}</strong></div>
<div class="cards">{cards}</div>
<section>
<h2>Six books at a glance</h2>
{_lead_table(arms, spy, spy_dd)}
</section>
<section>
<h2>Year-end equity and Max DD%</h2>
{_year_table(arms, spy, spy_dd)}
</section>
<section>
<h2>Monthly path — all six books</h2>
{_month_path_table(arms, spy_dd)}
</section>
{ledgers}
{compare_sections}
<section>
<h2>Max drawdown definition</h2>
<p>{html_mod.escape(DD_DEF)}</p>
</section>
<section>
<h2>Data sources</h2>
<ul class="sources">{sources_html}</ul>
<p class="small">Sibling five-system page (not overwritten):
<a href="../risk2500_five_sys_20260917/monthly.html">risk2500_five_sys_20260917/monthly.html</a>.
Compare: <a href="compare.html">compare.html</a>.
Acronyms first use: StockBee (SB); Relative Strength Index (RSI);
Volume Zone (VZ); Magic Touch (MTS); Rocket Launcher (RL);
Break and ReTest (BRT); Year High (YH);
Weekly Pivot Break and Retest (WPBR); Relative Strength vs SPY (RS);
Indicators (IND); In-Sample (IS); Out-of-Sample (OOS); buying power (BP);
beginning-of-month (BOM); S&amp;P 500 tracker (SPY); mark-to-close (last daily close).</p>
</section>
{f.r.monthly._SORTABLE_TABLE_SCRIPT}
</body></html>"""


def build_compare(
    *,
    arms: list[dict[str, Any]],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
    verdict: str,
    sources: list[str],
    generated: datetime,
) -> str:
    now = generated.astimezone(ET)
    gen_s = now.strftime("%Y-%m-%d %H:%M %Z")
    sources_html = "".join(f"<li>{html_mod.escape(s)}</li>" for s in sources)
    compare_sections = ""
    col_map = {"IS": "stats_is", "OOS": "stats_oos", "FULL": "stats_full"}
    for sl, note in (
        ("IS", "In-Sample — entry before 2024-01-01. Do not retune OOS."),
        ("OOS", "Out-of-Sample — report-only."),
        ("FULL", verdict),
    ):
        cols = [(a["short"], a[col_map[sl]]) for a in arms]
        compare_sections += f"""
<section>
<h2>Canonical compare · {sl}</h2>
<p class="small">{html_mod.escape(note)} Sheet / Total PnL $ omitted. Click headers to sort.</p>
<div class="table-wrap">{f._canonical_table(cols)}</div>
</section>"""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Compare — 6-book matrix vs SPY — {STAMP}</title>
<style>{f._css()}</style></head><body>
<h1>Compare — 5-sys / 9-sys / 4-sys × 0.3007% vs 1% sell-winner vs SPY</h1>
<p class="sub">
Stamp <code>{STAMP}</code>. Research only. <strong>Not gold. Not DailyRun.</strong>
Indicators (IND) is the old live sleeve (~−$40k, 35 lots, go-live 2026); it is not
DailyRun-wired; all books below exclude it. Generated {html_mod.escape(gen_s)}.
Click column headers to sort.
</p>
<div class="ask">
<h2>What you asked</h2>
<blockquote>{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN_ENGLISH)}</p>
</div>
<div class="warn">
<strong>2010–2012 first.</strong> Later-year paper dollars are not the headline.
SPY $250k total return ends at {format_money(spy['tr_end'])}
({spy['tr_mult']:.2f}×, Max DD {_fmt_pct(spy_dd['full_dd'])}).
</div>
<div class="hold"><strong>{html_mod.escape(verdict)}</strong></div>
<section>
<h2>Six books at a glance</h2>
{_lead_table(arms, spy, spy_dd)}
</section>
<section>
<h2>Year-end equity and Max DD%</h2>
{_year_table(arms, spy, spy_dd)}
</section>
{compare_sections}
<section>
<h2>Max drawdown definition</h2>
<p>{html_mod.escape(DD_DEF)}</p>
</section>
<section>
<h2>Data sources</h2>
<ul class="sources">{sources_html}</ul>
<p class="small">Monthly: <a href="monthly.html">monthly.html</a>.</p>
</section>
{f.r.monthly._SORTABLE_TABLE_SCRIPT}
</body></html>"""


def write_baseline(
    *,
    arms: list[dict[str, Any]],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
    verdict: str,
    sources: list[str],
) -> None:
    lines = [
        f"# BASELINE — {STAMP}",
        "",
        "**Status:** Research size path. **Not gold. Not DailyRun.** Out-of-Sample (OOS) report-only.",
        "",
        "## What you asked",
        "",
        f"> {ORIGINAL_REQUEST}",
        "",
        "## In plain English",
        "",
        PLAIN_ENGLISH,
        "",
        "## Indicators (one line)",
        "",
        "Indicators (IND) is the old live sleeve (~−$40k, 35 lots, go-live 2026); it is not DailyRun-wired; all books below exclude it.",
        "",
        "## Selection",
        "",
        "- One stamp, six books: 3 universes × 2 size/room policies.",
        "- All books: start $250,000; $7,500 cash on the 1st (when equity ≥ $7,500; still do it if that increases the debit); 10.5% annual on borrowed = max(0, open notional − equity); open notional ≤ 2× equity.",
        "- Relative Strength Index (RSI): invested = risk_dollar / 0.06509607 (In-Sample avg-loss freeze; do not retune OOS).",
        "- Others: shares = risk_dollar / (entry − stop), then clip to remaining buying power.",
        "- **reduced 0.3007%:** monthly risk = 0.3007% of beginning-of-month Closed-only equity; take-all / scale to BP; no rotation. Frozen r — do not re-search.",
        "- **1% sell winner:** monthly risk = 1% of BOM equity; when a new signal cannot fit even scaled, sell the most profitable open (last close vs entry) then take the new fill.",
        "- Do not add sell-loser / sell-oldest this run.",
        f"- Decision: **{verdict}**",
        "",
        "## Frozen knobs",
        "",
        f"- Account seed: **${ACCOUNT:,.0f}**",
        f"- Leverage cap: **{LEVERAGE:.0f}×** Closed-only equity",
        f"- Margin rate: **{MARGIN_RATE:.1%}** actual/365 daily compound",
        f"- Withdrawal: **${WITHDRAW:,.0f}** on month-start after 2010-01-01",
        "- In-Sample (IS) = `entry_date < 2024-01-01`. OOS report-only. Path is continuous.",
        "- Same Closed / Open pins as `risk2500_monthly_20260917` overlays (RSI = avg-loss CSV).",
        "- Fill order: older closes; DailyRun system then symbol; same-day exits.",
        "- Rotation mark: last daily close on or before sale vs entry (no eventual-exit look-ahead).",
        "- Do not overwrite sibling `risk2500_five_sys_20260917/monthly.html` except a one-line pointer.",
        "",
        "## Universes",
        "",
        f"- **5-sys:** {UNIVERSE_EXPAND['5-sys']}",
        f"- **9-sys:** {UNIVERSE_EXPAND['9-sys']}",
        f"- **4-sys:** {UNIVERSE_EXPAND['4-sys']}",
        "",
        "## Max drawdown definition",
        "",
        DD_DEF,
        "",
        "## SPY $250k from 2010-01-01",
        "",
        f"- First bar used: **{spy['start_date']}**.",
        f"- Last bar used: **{spy['end_date']}**.",
        f"- Total return: **${spy['tr_end']:,.2f}** ({spy['tr_mult']:.4f}×). Max DD {_fmt_pct(spy_dd['full_dd'])}.",
        f"- Price-only: **${spy['price_end']:,.2f}** ({spy['price_mult']:.4f}×).",
        f"- 2012 total-return equity: **${spy_dd['eq_2012']:,.2f}**.",
        "",
        "## Six books",
        "",
    ]
    for a in arms:
        led = a["led"]
        st = a["stats_full"]
        lines.append(
            f"- **{a['short']}** end **${led.end_equity:,.2f}**; 2010 ${led.eq_2010:,.2f}; "
            f"2011 ${led.eq_2011:,.2f}; 2012 ${led.eq_2012:,.2f}; "
            f"Max DD {_fmt_pct(led.max_dd_pct)} (peak ${led.max_dd_peak:,.2f} → "
            f"trough ${led.max_dd_trough:,.2f}); interest ${led.interest:,.2f}; "
            f"withdrawn ${led.withdrawals:,.2f}; rotates {led.n_rotate}; "
            f"BP-skip {led.n_skip_bp}; identity {led.identity_err}; "
            f"FULL N={st.get('n')} WR={st.get('win_pct')} Avg%={st.get('avg_pnl_pct')} "
            f"PF={st.get('pf')} book MaxDD={st.get('max_dd')}."
        )
    lines += [
        "",
        "## Honesty",
        "",
        "- Later-year dollars can still be capacity fiction. Read 2010–2012 vs SPY.",
        "- Picking KEEP from this same history would be in-sample selection. HOLD.",
        "- 0.3007% is the frozen “lower 1% so later signals fit” r. Do not re-search on OOS.",
        "- 1% sell-winner is one room rule. Do not treat a bigger ending as better quality.",
        "",
        "## Pins / sources",
        "",
    ]
    for s in sources:
        lines.append(f"- {s}")
    lines.append("")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_hypothesis(verdict: str) -> None:
    text = f"""# HYPOTHESIS — {STAMP}

**Product owner (PO)–aligned process:** one knob per arm, frozen everything else. See `docs/HYPOTHESIS_TEST.md`.

| Field | Fill in |
|-------|---------|
| System / prefix | 5-sys {", ".join(FIVE)}; 9-sys {", ".join(NINE)}; 4-sys {", ".join(FOUR)} (Indicators / IND out) |
| Baseline stamp | House overlays in `risk2500_monthly_20260917` (RSI = IS avg-loss CSV). Wallet engine `risk2500_five_sys_20260917` |
| Universe | House DailyRun universes (unchanged). Indicators (IND) excluded |
| **Evidence** | Paul: all books $7,500/mo + 10.5% margin; 5-sys and 9-sys and 4-sys (5 minus SB); reduced 0.3007%; 1% sell winner; Max DD% on every month/year line |
| **Hypothesis** | (1) 0.3007% take-all is the honest “make later signals fit” size vs 1% sell-winner. (2) Adding 9-sys or dropping StockBee does not change the capacity-fiction read after 2012. (3) Max DD% on each line is the quality number, not ending dollars |
| **Single knob** | Per arm: system set **or** size/room policy. Withdrawal, 10.5%, 2×, RSI 6.51% freeze stay frozen |
| Frozen settings | $250k start. $7,500 on the 1st. 10.5% actual/365. Open ≤ 2×. RSI invested = risk / 0.0651. 0.3007% not re-searched. Sell-loser / sell-oldest off |
| Alternatives | 3 × 2 = 6 books. SPY $250k total return. No extra rotation arms |
| Candidate stamps | `{STAMP}` monthly.html / compare.html |
| Metrics | Canonical book set + wallet ending + 2010–2012 + Max DD% (period + running + full). Judge quality not as-of dollars |
| **Trade-diff HTML** | N/A — size / wallet overlay (not an entry A/B) |
| ToS before path | N/A |
| ToS after path | N/A |
| **Decision** | {verdict} |
| Reviewer | AI job {STAMP} |
| PO sign-off | no |
| Reconcile freeze / re-baseline done | no |
| DailyRun | not wired |

## Decision checklist

- [x] Evidence was the PO ask (6 books, $7,500, 10.5%, Max DD% on every line)
- [x] One knob per arm (universe **or** 0.3007% vs 1% sell-winner)
- [x] Same Closed pins as the sibling $2,500 stamp
- [x] Out-of-Sample (OOS) report-only; no RSI retune; no r re-search
- [ ] If adopt: PO signed off — **not adopting**
"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "HYPOTHESIS.md").write_text(text, encoding="utf-8")


def _pointer_sibling() -> None:
    """One-line pointer on the five-sys monthly. Do not rewrite the page."""
    path = SIBLING / "monthly.html"
    if not path.is_file():
        return
    needle = "risk2500_sys_matrix_20260917/monthly.html"
    raw = path.read_text(encoding="utf-8")
    if needle in raw:
        return
    line = (
        '<p class="small">Follow-on six-book matrix (3 universes × reduced 0.3007% / '
        '1% sell-winner, all $7,500 wd + 10.5%): '
        f'<a href="../{STAMP}/monthly.html">{STAMP}/monthly.html</a>.</p>\n'
    )
    key = "<p class=\"sub\">"
    idx = raw.find(key)
    if idx < 0:
        return
    # Insert immediately after the opening sub paragraph's first tag line.
    end = raw.find("</p>", idx)
    if end < 0:
        return
    end += 4
    path.write_text(raw[:end] + "\n" + line + raw[end:], encoding="utf-8")
    print(f"pointer wrote into {path}", flush=True)


def run() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    spy = f.spy_buyhold()
    spy_dd = spy_paths(spy)
    print(
        f"[SPY] {spy['start_date']} -> {spy['end_date']} "
        f"TR {spy['tr_end']:.2f} ({spy['tr_mult']:.3f}x) "
        f"MaxDD={spy_dd['full_dd']:.2f}%",
        flush=True,
    )

    cache: dict[str, list] = {}
    for univ, systems in (("5-sys", FIVE), ("9-sys", NINE), ("4-sys", FOUR)):
        print(f"[load] {univ} {systems}", flush=True)
        cache[univ] = f.load_static(systems)

    sources = [
        f"overlays: {f.PREV_DIR.name} (RSI = RSI_overlay_avgloss.csv IS 6.51% freeze)",
        f"5-sys: {', '.join(FIVE)}",
        f"9-sys: {', '.join(NINE)}",
        f"4-sys: {', '.join(FOUR)} (5 minus SB)",
        "Indicators (IND) out — old live sleeve, not DailyRun-wired",
        f"SPY: {f.SPY_PATH.as_posix()} Adj Close total return + Close price-only",
        "wallet: tools/risk2500_five_sys_20260917.py run_wallet",
        "all books: $7,500 first-of-month + 10.5%/365 + open ≤ 2×",
        "r=0.3007% frozen (do not re-search); 1% sell-winner = rotate winner",
        DD_DEF,
    ]

    arms: list[dict[str, Any]] = []
    for spec in _book_specs():
        pack = f._run_arm(
            cache[spec["univ"]],
            rank=_rank_for(spec["univ"]),
            rotate=spec["rotate"],
            withdraw=True,
            label=spec["short"],
            risk_frac=spec["risk_frac"],
        )
        pack.update(spec)
        pack["read"] = "Research only. HOLD — quality over dollars."
        arms.append(pack)
        csv_name = f"ALL_overlay_{spec['key'].replace('-', '_')}.csv"
        f.r.write_overlay_csv(pack["trades"], OUT_DIR / csv_name)
        print(
            f"  MaxDD={pack['led'].max_dd_pct:.2f}% "
            f"2012={pack['led'].eq_2012:.2f}",
            flush=True,
        )

    verdict = _verdict(arms, spy, spy_dd)
    print(f"[verdict] {verdict}", flush=True)

    now = datetime.now(tz=ET)
    monthly_html = build_monthly(
        arms=arms,
        spy=spy,
        spy_dd=spy_dd,
        verdict=verdict,
        sources=sources,
        generated=now,
    )
    compare_html = build_compare(
        arms=arms,
        spy=spy,
        spy_dd=spy_dd,
        verdict=verdict,
        sources=sources,
        generated=now,
    )
    (OUT_DIR / "monthly.html").write_text(monthly_html, encoding="utf-8")
    (OUT_DIR / "compare.html").write_text(compare_html, encoding="utf-8")
    write_baseline(arms=arms, spy=spy, spy_dd=spy_dd, verdict=verdict, sources=sources)
    write_hypothesis(verdict)
    _pointer_sibling()

    summary = {
        "spy_tr_end": spy["tr_end"],
        "spy_tr_mult": spy["tr_mult"],
        "spy_max_dd_pct": spy_dd["full_dd"],
        "spy_2012": spy_dd["eq_2012"],
        "verdict": verdict,
        "books": {
            a["key"]: {
                "end": a["led"].end_equity,
                "eq_2010": a["led"].eq_2010,
                "eq_2011": a["led"].eq_2011,
                "eq_2012": a["led"].eq_2012,
                "max_dd_pct": a["led"].max_dd_pct,
                "interest": a["led"].interest,
                "withdrawals": a["led"].withdrawals,
                "n_rotate": a["led"].n_rotate,
                "n_skip_bp": a["led"].n_skip_bp,
                "vs_spy": a["led"].end_equity / spy["tr_end"] if spy["tr_end"] else None,
            }
            for a in arms
        },
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"wrote {OUT_DIR / 'monthly.html'}", flush=True)
    print(f"wrote {OUT_DIR / 'compare.html'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
