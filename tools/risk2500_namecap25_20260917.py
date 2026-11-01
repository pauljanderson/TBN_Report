#!/usr/bin/env python3
"""5-sys 1% sell-winner + 25% per-name notional cap (research only).

Stamp: drive/paul_experiments/risk2500_namecap25_20260917/

Control identity = risk2500_sys_matrix_20260917 5-sys 1% sell-winner
($250k, $7,500/mo, 10.5%, open ≤ 2×, RSI IS 6.51% freeze).

One knob: after 1% size and before fill, clip each ticker's open notional
to ≤ 25% of current Closed-only equity. Do not also run 10% this stamp.

Not gold. Not DailyRun.
"""
from __future__ import annotations

import html as html_mod
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))

from compare_format import format_money  # noqa: E402

_FSPEC = importlib.util.spec_from_file_location(
    "risk2500_five_sys_20260917",
    REPO / "tools" / "risk2500_five_sys_20260917.py",
)
f = importlib.util.module_from_spec(_FSPEC)
assert _FSPEC.loader is not None
sys.modules["risk2500_five_sys_20260917"] = f
_FSPEC.loader.exec_module(f)

_MSPEC = importlib.util.spec_from_file_location(
    "risk2500_sys_matrix_20260917",
    REPO / "tools" / "risk2500_sys_matrix_20260917.py",
)
m = importlib.util.module_from_spec(_MSPEC)
assert _MSPEC.loader is not None
sys.modules["risk2500_sys_matrix_20260917"] = m
_MSPEC.loader.exec_module(m)

STAMP = "risk2500_namecap25_20260917"
OUT_DIR = REPO / "drive" / "paul_experiments" / STAMP
ACCOUNT = f.ACCOUNT
ASOF = f.ASOF
ET = f.ET
WITHDRAW = f.WITHDRAW
MARGIN_RATE = f.MARGIN_RATE
LEVERAGE = f.LEVERAGE
NAME_CAP = 0.25
R_ONE = 0.01
FIVE = f.FIVE
FIVE_RANK = f.FIVE_RANK
DD_DEF = m.DD_DEF

ORIGINAL_REQUEST = (
    "ok so can we run this test and give me a recommendation? YES / NO — cap "
    "per-name notional (suggested first: ≤25% of equity; 10% is the stricter "
    "sibling). Tight stops then cannot buy the whole 2× book. This is the "
    "cheapest “stop the $5T” knob. Next stamp, one book: 5-sys 1% sell-winner "
    "+ 25% name cap, print YE2012 + as-of vs SPY only."
)
PLAIN_ENGLISH = (
    "Same five sleeves as the last 1% sell-winner book — StockBee (SB), "
    "Relative Strength Index (RSI), Volume Zone (VZ), Magic Touch (MTS), "
    "Rocket Launcher (RL). Indicators (IND) is out. Start $250,000 in one "
    "wallet. Pull $7,500 cash on the 1st. Pay 10.5% a year on whatever you "
    "borrowed. Open stock cost can be at most twice the account. Each month "
    "risk 1% of the account: RSI dollars in = that 1% ÷ 0.0651 (In-Sample "
    "average-loser freeze; do not retune after 2024); other systems shares = "
    "1% ÷ (entry − stop). When a new signal still cannot fit, sell the most "
    "profitable open name, then take the new one. The one new rule: after that "
    "1% size and before the fill, no single ticker may hold more than 25% of "
    "whatever the account is worth right then. A tight stop can no longer "
    "buy the whole 2× book. If 25% is still bigger than leftover buying power, "
    "shrink to leftover buying power. We did not also run a 10% cap this page "
    "(stricter sibling — next yes/no only). Read year-end 2012 and today "
    "versus S&P 500 tracker (SPY), not later-year trillions. Not gold. Not DailyRun."
)


def _fmt_pct(v: Any) -> str:
    return m._fmt_pct(v)


def _vs_spy(end: float, spy_tr: float) -> str:
    return m._vs_spy(end, spy_tr)


def _num(st: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        v = st.get(key)
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _verdict(
    ctrl: dict[str, Any],
    cand: dict[str, Any],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    """Return (tag, prose, extras). Judge quality + realism, not ending dollars."""
    cled, uled = cand["led"], ctrl["led"]
    spy_asof = float(spy["tr_end"])
    spy_2012 = float(spy_dd["eq_2012"])
    asof = float(cled.end_equity)
    ye2012 = float(cled.eq_2012)
    peak_book_u = float(uled.peak_reserved)
    peak_book_c = float(cled.peak_reserved)
    peak_name_u = float(uled.peak_name_notional)
    peak_name_c = float(cled.peak_name_notional)
    trillion_died = asof < 1.0e12 and peak_book_c < 1.0e12
    still_huge = asof >= 10_000_000.0
    cst, ust = cand["stats_full"], ctrl["stats_full"]
    extras = {
        "trillion_died": trillion_died,
        "still_huge": still_huge,
        "asof": asof,
        "ye2012": ye2012,
        "spy_asof": spy_asof,
        "spy_2012": spy_2012,
        "peak_book_uncapped": peak_book_u,
        "peak_book_capped": peak_book_c,
        "peak_name_uncapped": peak_name_u,
        "peak_name_capped": peak_name_c,
        "peak_name_sym_u": uled.peak_name_symbol,
        "peak_name_sym_c": cled.peak_name_symbol,
        "dd_c": float(cled.max_dd_pct),
        "dd_u": float(uled.max_dd_pct),
        "wr_c": _num(cst, "win_pct"),
        "wr_u": _num(ust, "win_pct"),
        "avg_c": _num(cst, "avg_pnl_pct"),
        "avg_u": _num(ust, "avg_pnl_pct"),
        "pf_c": _num(cst, "pf"),
        "pf_u": _num(ust, "pf"),
    }
    quality_worse = (
        extras["wr_c"] + 0.25 < extras["wr_u"]
        and extras["avg_c"] + 0.25 < extras["avg_u"]
        and extras["dd_c"] > extras["dd_u"] + 2.0
    )
    if quality_worse and not trillion_died:
        tag = "DISMISS"
        prose = (
            f"DISMISS versus the uncapped 5-sys 1% sell-winner — quality "
            f"(win rate {_fmt_pct(extras['wr_c'])} vs {_fmt_pct(extras['wr_u'])}, "
            f"average % {extras['avg_c']:.2f} vs {extras['avg_u']:.2f}, "
            f"Max DD {_fmt_pct(extras['dd_c'])} vs {_fmt_pct(extras['dd_u'])}) "
            f"got worse and the $5T book did not die. Versus SPY: year-end 2012 "
            f"{format_money(ye2012)} vs {format_money(spy_2012)}; as-of "
            f"{format_money(asof)} vs {format_money(spy_asof)}. Not gold. Not DailyRun."
        )
        return tag, prose, extras
    if still_huge:
        tag = "HOLD"
        if trillion_died:
            died = (
                "The 25% cap took the book out of the trillion class "
                f"(peak open notional {format_money(peak_book_u)} → "
                f"{format_money(peak_book_c)}; peak single-name "
                f"{format_money(peak_name_u)} {uled.peak_name_symbol or '—'} → "
                f"{format_money(peak_name_c)} {cled.peak_name_symbol or '—'}). "
            )
        else:
            died = (
                f"$5T did not die. Uncapped as-of {format_money(float(uled.end_equity))} "
                f"/ peak book {format_money(peak_book_u)} / peak name "
                f"{format_money(peak_name_u)} {uled.peak_name_symbol or '—'} -> "
                f"capped as-of {format_money(asof)} / peak book "
                f"{format_money(peak_book_c)} / peak name "
                f"{format_money(peak_name_c)} {cled.peak_name_symbol or '—'}. "
                "A 25% cap scales with the pile, so 1% compounding still prints "
                "trillions; one name can still be ~25% of that fiction. "
            )
        prose = (
            f"HOLD versus (a) the uncapped 5-sys 1% sell-winner and (b) SPY. "
            f"{died}"
            f"As-of is still {format_money(asof)} because 1% of a growing pile "
            f"still compounds — that is not a live Fidelity recipe. Year-end 2012 "
            f"{format_money(ye2012)} vs SPY {format_money(spy_2012)}; as-of "
            f"{format_money(asof)} vs SPY {format_money(spy_asof)}. "
            f"Max DD {_fmt_pct(extras['dd_c'])} (uncapped {_fmt_pct(extras['dd_u'])}). "
            f"Do not retune 25% on Out-of-Sample. 10% is the stricter sibling — "
            f"next yes/no only. Not gold. Not DailyRun."
        )
        return tag, prose, extras
    if asof > spy_asof and ye2012 >= spy_2012 * 0.9 and extras["dd_c"] <= extras["dd_u"] + 1.0:
        tag = "KEEP"
        prose = (
            f"KEEP as a research candidate versus the uncapped 5-sys sell-winner "
            f"on realism (peak book {format_money(peak_book_u)} → "
            f"{format_money(peak_book_c)}) without collapsing year-end 2012 "
            f"({format_money(ye2012)} vs SPY {format_money(spy_2012)}; as-of "
            f"{format_money(asof)} vs SPY {format_money(spy_asof)}). Still not gold "
            f"and not DailyRun — one in-sample freeze, no walk-forward."
        )
        return tag, prose, extras
    tag = "HOLD"
    prose = (
        f"HOLD versus (a) uncapped 5-sys 1% sell-winner and (b) SPY. "
        f"Year-end 2012 {format_money(ye2012)} vs SPY {format_money(spy_2012)}; "
        f"as-of {format_money(asof)} vs SPY {format_money(spy_asof)}. "
        f"Peak book {format_money(peak_book_c)} vs uncapped {format_money(peak_book_u)}. "
        f"Quality and realism are mixed; do not adopt 25% from this one page. "
        f"10% is the next yes/no. Not gold. Not DailyRun."
    )
    return tag, prose, extras


def _headline_box(
    ctrl: dict[str, Any],
    cand: dict[str, Any],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
    tag: str,
    extras: dict[str, Any],
) -> str:
    cls = "yes" if tag == "KEEP" else ("no" if tag == "DISMISS" else "holdtag")
    return f"""
<div class="lead">
  <h2>Headline — 25% name cap vs SPY</h2>
  <p><strong class="{cls}">{html_mod.escape(tag)}</strong> · research only · not gold · not DailyRun</p>
  <div class="cards">
    <div class="card card-shared">
      <h3>Year-end 2012 vs SPY</h3>
      <div class="metric">{format_money(extras['ye2012'])}</div>
      <div class="small">SPY {format_money(extras['spy_2012'])} ·
      {_vs_spy(extras['ye2012'], extras['spy_2012'])}</div>
    </div>
    <div class="card card-shared">
      <h3>As-of {ASOF.isoformat()} vs SPY</h3>
      <div class="metric">{format_money(extras['asof'])}</div>
      <div class="small">SPY {format_money(extras['spy_asof'])} ·
      {_vs_spy(extras['asof'], extras['spy_asof'])}</div>
    </div>
    <div class="card">
      <h3>Did $5T die?</h3>
      <div class="metric">{"YES" if extras["trillion_died"] else "NO"}</div>
      <div class="small">Peak book {format_money(extras['peak_book_uncapped'])} →
      {format_money(extras['peak_book_capped'])}</div>
      <div class="small">Peak name {format_money(extras['peak_name_uncapped'])}
      {html_mod.escape(extras['peak_name_sym_u'] or '—')} →
      {format_money(extras['peak_name_capped'])}
      {html_mod.escape(extras['peak_name_sym_c'] or '—')}</div>
    </div>
    <div class="card">
      <h3>Max DD%</h3>
      <div class="metric">{_fmt_pct(extras['dd_c'])}</div>
      <div class="small">Uncapped 5-sys sell-winner {_fmt_pct(extras['dd_u'])}</div>
    </div>
  </div>
</div>"""


def _lead_table(
    ctrl: dict[str, Any],
    cand: dict[str, Any],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
) -> str:
    head = f._sortable_head(
        [
            ("Book", "text"),
            ("Cap / extra rule", "text"),
            ("Ending equity", "num"),
            ("2010 end", "num"),
            ("2011 end", "num"),
            ("2012 end", "num"),
            ("Max DD%", "num"),
            ("vs SPY as-of", "text"),
            ("Peak book notional", "num"),
            ("Peak single-name", "num"),
            ("Peak name ticker", "text"),
            ("Interest", "num"),
            ("Withdrawn", "num"),
            ("Rotates / BP-skip / name-skip", "text"),
            ("Name-capped fills", "num"),
        ]
    )
    rows = [
        (
            "SPY buy-hold $250k (total return)",
            "Sit in S&P 500 tracker (SPY), dividends reinvested",
            spy["tr_end"],
            spy["years"].get(2010, {}).get("tr"),
            spy["years"].get(2011, {}).get("tr"),
            spy_dd["eq_2012"],
            spy_dd["full_dd"],
            "1.00× (yardstick)",
            spy["tr_end"],
            spy["tr_end"],
            "SPY",
            0.0,
            0.0,
            "0 / 0 / 0",
            0,
        )
    ]
    for a, cap in (
        (
            ctrl,
            "5-sys · 1% sell-winner · no per-name cap (matrix control)",
        ),
        (
            cand,
            "5-sys · 1% sell-winner · per-name notional ≤ 25% of current equity",
        ),
    ):
        led = a["led"]
        rows.append(
            (
                a["label"],
                cap,
                led.end_equity,
                led.eq_2010,
                led.eq_2011,
                led.eq_2012,
                led.max_dd_pct,
                _vs_spy(led.end_equity, spy["tr_end"]),
                led.peak_reserved,
                led.peak_name_notional,
                led.peak_name_symbol or "—",
                led.interest,
                led.withdrawals,
                f"{led.n_rotate} / {led.n_skip_bp} / {led.n_skip_name}",
                led.n_name_capped,
            )
        )

    def _m(v: Any) -> str:
        if v is None:
            return "—"
        return format_money(float(v))

    body = ""
    for rec in rows:
        (
            name,
            cap,
            end,
            y0,
            y1,
            y2,
            dd,
            vs,
            peak_b,
            peak_n,
            ticker,
            interest,
            wd,
            sk,
            ncap,
        ) = rec
        body += (
            "<tr>"
            f"<td>{html_mod.escape(str(name))}</td>"
            f"<td class=\"small\">{html_mod.escape(str(cap))}</td>"
            f"<td>{_m(end)}</td>"
            f"<td>{_m(y0)}</td>"
            f"<td>{_m(y1)}</td>"
            f"<td>{_m(y2)}</td>"
            f"<td>{_fmt_pct(dd)}</td>"
            f"<td>{html_mod.escape(str(vs))}</td>"
            f"<td>{_m(peak_b)}</td>"
            f"<td>{_m(peak_n)}</td>"
            f"<td>{html_mod.escape(str(ticker))}</td>"
            f"<td>{_m(interest)}</td>"
            f"<td>{_m(wd)}</td>"
            f"<td>{html_mod.escape(str(sk))}</td>"
            f"<td>{int(ncap)}</td>"
            "</tr>"
        )
    last = (
        '<tr class="total-row"><th>As-of / last</th><td class="small">Pinned</td>'
        f"<td>{format_money(cand['led'].end_equity)}</td>"
        f"<td>{format_money(cand['led'].eq_2010)}</td>"
        f"<td>{format_money(cand['led'].eq_2011)}</td>"
        f"<td>{format_money(cand['led'].eq_2012)}</td>"
        f"<td>{_fmt_pct(cand['led'].max_dd_pct)}</td>"
        f"<td>{html_mod.escape(_vs_spy(cand['led'].end_equity, spy['tr_end']))}</td>"
        f"<td>{format_money(cand['led'].peak_reserved)}</td>"
        f"<td>{format_money(cand['led'].peak_name_notional)}</td>"
        f"<td>{html_mod.escape(cand['led'].peak_name_symbol or '—')}</td>"
        f"<td>{format_money(cand['led'].interest)}</td>"
        f"<td>{format_money(cand['led'].withdrawals)}</td>"
        f"<td>{cand['led'].n_rotate} / {cand['led'].n_skip_bp} / {cand['led'].n_skip_name}</td>"
        f"<td>{cand['led'].n_name_capped}</td></tr>"
    )
    return (
        '<p class="small">Click column headers to sort. Total row pinned. '
        "Uncapped 5-sys 1% sell-winner is the control; 25% name cap is the one change.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}{last}</tbody></table></div>"
    )


def _year_table(
    ctrl: dict[str, Any],
    cand: dict[str, Any],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
) -> str:
    head = f._sortable_head(
        [
            ("Year-end", "num"),
            ("Uncapped 5-sys 1% SW", "num"),
            ("25% name cap", "num"),
            ("SPY total return", "num"),
            ("Uncapped Max DD%", "num"),
            ("25% Max DD%", "num"),
            ("SPY Max DD%", "num"),
            ("Note", "text"),
        ]
    )
    body = ""
    for y in range(2010, ASOF.year + 1):
        ur = next((x for x in ctrl["years"] if x["year"] == y), None)
        cr = next((x for x in cand["years"] if x["year"] == y), None)
        sy = spy["years"].get(y)
        sdd = spy_dd["years"].get(y, {})
        note = ""
        if y == ASOF.year:
            note = f"through {ASOF.isoformat()}"
        body += (
            "<tr>"
            f"<td>{y}</td>"
            f"<td>{format_money(ur['ending_equity']) if ur else '—'}</td>"
            f"<td>{format_money(cr['ending_equity']) if cr else '—'}</td>"
            f"<td>{format_money(sy['tr']) if sy else '—'}</td>"
            f"<td>{_fmt_pct(ur['max_dd_pct']) if ur else '—'}</td>"
            f"<td>{_fmt_pct(cr['max_dd_pct']) if cr else '—'}</td>"
            f"<td>{_fmt_pct(sdd.get('max_dd_pct'))}</td>"
            f"<td class=\"small\">{html_mod.escape(note)}</td>"
            "</tr>"
        )
    last = (
        '<tr class="total-row"><th>Total / last</th>'
        f"<td>{format_money(ctrl['led'].end_equity)}</td>"
        f"<td>{format_money(cand['led'].end_equity)}</td>"
        f"<td>{format_money(spy['tr_end'])}</td>"
        f"<td>{_fmt_pct(ctrl['led'].max_dd_pct)}</td>"
        f"<td>{_fmt_pct(cand['led'].max_dd_pct)}</td>"
        f"<td>{_fmt_pct(spy_dd['full_dd'])}</td>"
        "<td class=\"small\">Pinned as-of</td></tr>"
    )
    return (
        '<p class="small">Closed-only year-end vs $250k SPY total return. '
        "Click headers to sort. Total row pinned.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}{last}</tbody></table></div>"
    )


def _month_path_table(
    ctrl: dict[str, Any],
    cand: dict[str, Any],
    spy_dd: dict[str, Any],
) -> str:
    head = f._sortable_head(
        [
            ("Month", "month"),
            ("Uncapped EOM", "num"),
            ("25% cap EOM", "num"),
            ("SPY TR EOM", "num"),
            ("Uncapped month Max DD%", "num"),
            ("25% month Max DD%", "num"),
            ("SPY month Max DD%", "num"),
        ]
    )
    keys = sorted({(s.year, s.month) for s in ctrl["snaps"]} | {(s.year, s.month) for s in cand["snaps"]})
    u_map = {(s.year, s.month): s for s in ctrl["snaps"]}
    c_map = {(s.year, s.month): s for s in cand["snaps"]}
    body = ""
    for key in keys:
        us, cs = u_map.get(key), c_map.get(key)
        sm = spy_dd["months"].get(key, {})
        body += (
            "<tr>"
            f"<td>{key[0]}-{key[1]:02d}</td>"
            f"<td>{format_money(us.equity_end) if us else '—'}</td>"
            f"<td>{format_money(cs.equity_end) if cs else '—'}</td>"
            f"<td>{format_money(sm['tr']) if sm else '—'}</td>"
            f"<td>{_fmt_pct(us.max_dd_pct) if us else '—'}</td>"
            f"<td>{_fmt_pct(cs.max_dd_pct) if cs else '—'}</td>"
            f"<td>{_fmt_pct(sm.get('max_dd_pct'))}</td>"
            "</tr>"
        )
    last = (
        '<tr class="total-row"><th>As-of / last</th>'
        f"<td>{format_money(ctrl['led'].end_equity)}</td>"
        f"<td>{format_money(cand['led'].end_equity)}</td>"
        f"<td>{format_money(spy_dd['tr_end'])}</td>"
        f"<td>{_fmt_pct(ctrl['led'].max_dd_pct)}</td>"
        f"<td>{_fmt_pct(cand['led'].max_dd_pct)}</td>"
        f"<td>{_fmt_pct(spy_dd['full_dd'])}</td></tr>"
    )
    return (
        '<p class="small">Month-end Closed-only path. Click headers to sort. Total row pinned.</p>'
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}{last}</tbody></table></div>"
    )


def build_monthly(
    *,
    ctrl: dict[str, Any],
    cand: dict[str, Any],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
    tag: str,
    verdict: str,
    extras: dict[str, Any],
    sources: list[str],
    generated: datetime,
) -> str:
    now = generated.astimezone(ET)
    gen_s = now.strftime("%Y-%m-%d %H:%M %Z")
    sources_html = "".join(f"<li>{html_mod.escape(s)}</li>" for s in sources)
    compare_sections = ""
    col_map = {"IS": "stats_is", "OOS": "stats_oos", "FULL": "stats_full"}
    for sl, note in (
        ("IS", "In-Sample — entry before 2024-01-01. Path is continuous; do not retune 25% on OOS."),
        ("OOS", "Out-of-Sample — report-only. Do not pick 25% from this slice."),
        ("FULL", verdict),
    ):
        cols = [
            ("Uncapped 5-sys 1% SW", ctrl[col_map[sl]]),
            ("25% name cap", cand[col_map[sl]]),
        ]
        compare_sections += f"""
<section>
<h2>Canonical compare · {sl}</h2>
<p class="small">{html_mod.escape(note)} Sheet / Total PnL $ omitted. Click headers to sort.</p>
<div class="table-wrap">{f._canonical_table(cols)}</div>
</section>"""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>5-sys 1% sell-winner + 25% name cap — {STAMP}</title>
<style>{f._css()}</style></head><body>
<h1>Monthly Backtest Report — {ASOF.year} · 5-sys 1% sell-winner + 25% name cap</h1>
<p class="sub">
Stamp <code>{STAMP}</code>. Research only. <strong>Not gold. Not DailyRun.</strong>
Indicators (IND) out. Generated {html_mod.escape(gen_s)}. Click column headers to sort.
</p>
<div class="ask">
<h2>What you asked</h2>
<blockquote>{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN_ENGLISH)}</p>
</div>
{_headline_box(ctrl, cand, spy, spy_dd, tag, extras)}
<div class="hold"><strong>{html_mod.escape(verdict)}</strong></div>
<div class="warn">
<strong>2010–2012 first.</strong> Later-year paper dollars can still be capacity
fiction even after a name cap. SPY 2010 / 2011 / 2012:
{format_money(spy['years'].get(2010, {}).get('tr', 0))} /
{format_money(spy['years'].get(2011, {}).get('tr', 0))} /
{format_money(spy_dd['eq_2012'])}.
Uncapped 5-sys: 2010 {format_money(ctrl['led'].eq_2010)} · 2011 {format_money(ctrl['led'].eq_2011)} · 2012 {format_money(ctrl['led'].eq_2012)}.
25% name cap: 2010 {format_money(cand['led'].eq_2010)} · 2011 {format_money(cand['led'].eq_2011)} · 2012 {format_money(cand['led'].eq_2012)}.
10% is the stricter sibling — next yes/no only; not run here.
</div>
<section>
<h2>Two books at a glance</h2>
{_lead_table(ctrl, cand, spy, spy_dd)}
</section>
<section>
<h2>Year-end equity and Max DD%</h2>
{_year_table(ctrl, cand, spy, spy_dd)}
</section>
<section>
<h2>Monthly path</h2>
{_month_path_table(ctrl, cand, spy_dd)}
</section>
<section>
<h2>Ledger — uncapped 5-sys 1% sell-winner</h2>
<p class="small">Control identity from the matrix stamp. Click headers to sort.</p>
{f._ledger_table(ctrl['snaps'])}
</section>
<section>
<h2>Ledger — 25% name cap</h2>
<p class="small">One change: clip each ticker to ≤ 25% of current equity, then remaining buying power. Click headers to sort.</p>
{f._ledger_table(cand['snaps'])}
</section>
{compare_sections}
<section>
<h2>Max drawdown definition</h2>
<p>{html_mod.escape(DD_DEF)}</p>
</section>
<section>
<h2>Data sources</h2>
<ul class="sources">{sources_html}</ul>
<p class="small">Compare: <a href="compare.html">compare.html</a>.
Sibling matrix: <a href="../risk2500_sys_matrix_20260917/compare.html">risk2500_sys_matrix_20260917</a>.
Acronyms first use: StockBee (SB); Relative Strength Index (RSI);
Volume Zone (VZ); Magic Touch (MTS); Rocket Launcher (RL);
Indicators (IND); In-Sample (IS); Out-of-Sample (OOS); buying power (BP);
beginning-of-month (BOM); S&amp;P 500 tracker (SPY); year-end (YE).</p>
</section>
{f.r.monthly._SORTABLE_TABLE_SCRIPT}
</body></html>"""


def build_compare(
    *,
    ctrl: dict[str, Any],
    cand: dict[str, Any],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
    tag: str,
    verdict: str,
    extras: dict[str, Any],
    sources: list[str],
    generated: datetime,
) -> str:
    now = generated.astimezone(ET)
    gen_s = now.strftime("%Y-%m-%d %H:%M %Z")
    sources_html = "".join(f"<li>{html_mod.escape(s)}</li>" for s in sources)
    compare_sections = ""
    col_map = {"IS": "stats_is", "OOS": "stats_oos", "FULL": "stats_full"}
    for sl, note in (
        ("IS", "In-Sample — entry before 2024-01-01. Do not retune 25% on OOS."),
        ("OOS", "Out-of-Sample — report-only."),
        ("FULL", verdict),
    ):
        cols = [
            ("Uncapped 5-sys 1% SW", ctrl[col_map[sl]]),
            ("25% name cap", cand[col_map[sl]]),
        ]
        compare_sections += f"""
<section>
<h2>Canonical compare · {sl}</h2>
<p class="small">{html_mod.escape(note)} Sheet / Total PnL $ omitted. Click headers to sort.</p>
<div class="table-wrap">{f._canonical_table(cols)}</div>
</section>"""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Compare — 25% name cap vs uncapped 5-sys vs SPY — {STAMP}</title>
<style>{f._css()}</style></head><body>
<h1>Compare — 5-sys 1% sell-winner + 25% name cap vs uncapped vs SPY</h1>
<p class="sub">
Stamp <code>{STAMP}</code>. Research only. <strong>Not gold. Not DailyRun.</strong>
Generated {html_mod.escape(gen_s)}. Click column headers to sort.
</p>
<div class="ask">
<h2>What you asked</h2>
<blockquote>{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN_ENGLISH)}</p>
</div>
{_headline_box(ctrl, cand, spy, spy_dd, tag, extras)}
<div class="hold"><strong>{html_mod.escape(verdict)}</strong></div>
<section>
<h2>Two books at a glance</h2>
{_lead_table(ctrl, cand, spy, spy_dd)}
</section>
<section>
<h2>Year-end equity and Max DD%</h2>
{_year_table(ctrl, cand, spy, spy_dd)}
</section>
{compare_sections}
<section>
<h2>Max drawdown definition</h2>
<p>{html_mod.escape(DD_DEF)}</p>
</section>
<section>
<h2>Data sources</h2>
<ul class="sources">{sources_html}</ul>
<p class="small">Monthly: <a href="monthly.html">monthly.html</a>.
10% name cap not run — next yes/no only.</p>
</section>
{f.r.monthly._SORTABLE_TABLE_SCRIPT}
</body></html>"""


def write_baseline(
    *,
    ctrl: dict[str, Any],
    cand: dict[str, Any],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
    tag: str,
    verdict: str,
    extras: dict[str, Any],
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
        "Indicators (IND) is the old live sleeve (~−$40k, 35 lots, go-live 2026); it is not DailyRun-wired; both books exclude it.",
        "",
        "## Selection",
        "",
        "- One stamp, one knob: **per-name notional ≤ 25% of current Closed-only equity** on the frozen 5-sys 1% sell-winner book.",
        "- Control = `risk2500_sys_matrix_20260917` 5-sys 1% sell-winner (uncapped names). Re-run here so peak single-name / peak book are on the same engine.",
        "- Do **not** also run 10% this stamp (stricter sibling — next yes/no only).",
        "- 5-sys: StockBee (SB), Relative Strength Index (RSI), Volume Zone (VZ), Magic Touch (MTS), Rocket Launcher (RL). IND out.",
        "- Start $250,000; one wallet; $7,500 cash on the 1st; 10.5% actual/365 on debit; open notional ≤ 2× equity.",
        "- Monthly risk = 1% of beginning-of-month Closed-only equity.",
        "- RSI: invested = risk_dollar / 0.06509607 (In-Sample avg-loss freeze; do not retune OOS).",
        "- Others: shares = risk_dollar / (entry − stop), then name cap, then remaining buying power.",
        "- When a new signal cannot fit even after name-cap + buying-power clip: sell the most profitable open (last close vs entry), then fill.",
        f"- Decision: **{tag}** — {verdict}",
        "",
        "## Frozen knobs",
        "",
        f"- Account seed: **${ACCOUNT:,.0f}**",
        f"- Leverage cap: **{LEVERAGE:.0f}×** Closed-only equity",
        f"- Margin rate: **{MARGIN_RATE:.1%}** actual/365 daily compound",
        f"- Withdrawal: **${WITHDRAW:,.0f}** on month-start after 2010-01-01",
        "- Monthly risk: **1%** of BOM equity",
        "- Room rule: **sell winner** when buying power < $1",
        f"- **One change:** name cap **{NAME_CAP:.0%}** of current (cash + reserved) equity, applied after 1% size and before fill. Same-ticker open lots share the 25% room.",
        "- If 25% still exceeds remaining buying power, scale to remaining buying power.",
        "- In-Sample (IS) = `entry_date < 2024-01-01`. OOS report-only. Do not retune 25% on OOS.",
        "- Same Closed / Open pins as `risk2500_monthly_20260917` overlays (RSI = avg-loss CSV).",
        "- Fill order: older closes; DailyRun system then symbol; same-day exits.",
        "",
        "## Max drawdown definition",
        "",
        DD_DEF,
        "",
        "## SPY $250k from 2010-01-01",
        "",
        f"- First bar used: **{spy['start_date']}**.",
        f"- Last bar used: **{spy['end_date']}**.",
        f"- Total return as-of: **${spy['tr_end']:,.2f}** ({spy['tr_mult']:.4f}×). Max DD {_fmt_pct(spy_dd['full_dd'])}.",
        f"- Price-only as-of: **${spy['price_end']:,.2f}** ({spy['price_mult']:.4f}×).",
        f"- Year-end 2012 total-return equity: **${spy_dd['eq_2012']:,.2f}**.",
        f"- 2010 / 2011 / 2012 TR: ${spy['years'].get(2010, {}).get('tr', 0):,.2f} / "
        f"${spy['years'].get(2011, {}).get('tr', 0):,.2f} / ${spy_dd['eq_2012']:,.2f}.",
        "",
        "## Books",
        "",
    ]
    for a, title in (
        (ctrl, "Uncapped 5-sys 1% sell-winner (control)"),
        (cand, "5-sys 1% sell-winner + 25% name cap (candidate)"),
    ):
        led = a["led"]
        st = a["stats_full"]
        iso = a["stats_is"]
        oos = a["stats_oos"]
        lines.append(
            f"- **{title}** end **${led.end_equity:,.2f}**; 2010 ${led.eq_2010:,.2f}; "
            f"2011 ${led.eq_2011:,.2f}; 2012 ${led.eq_2012:,.2f}; "
            f"Max DD {_fmt_pct(led.max_dd_pct)} (peak ${led.max_dd_peak:,.2f} → "
            f"trough ${led.max_dd_trough:,.2f}); interest ${led.interest:,.2f}; "
            f"withdrawn ${led.withdrawals:,.2f}; rotates {led.n_rotate}; "
            f"BP-skip {led.n_skip_bp}; name-skip {led.n_skip_name}; "
            f"name-capped fills {led.n_name_capped}; "
            f"peak book ${led.peak_reserved:,.2f}; peak name ${led.peak_name_notional:,.2f} "
            f"({led.peak_name_symbol or '—'}, {led.peak_name_frac:.1%} of equity at peak); "
            f"identity {led.identity_err}; "
            f"FULL N={st.get('n')} WR={st.get('win_pct')} Avg%={st.get('avg_pnl_pct')} "
            f"PF={st.get('pf')}; "
            f"IS N={iso.get('n')} WR={iso.get('win_pct')} Avg%={iso.get('avg_pnl_pct')}; "
            f"OOS N={oos.get('n')} WR={oos.get('win_pct')} Avg%={oos.get('avg_pnl_pct')} (report-only)."
        )
    lines += [
        "",
        "## Headline vs SPY",
        "",
        f"- Year-end 2012: candidate **${extras['ye2012']:,.2f}** vs SPY **${extras['spy_2012']:,.2f}** ({_vs_spy(extras['ye2012'], extras['spy_2012'])}).",
        f"- As-of {ASOF.isoformat()}: candidate **${extras['asof']:,.2f}** vs SPY **${extras['spy_asof']:,.2f}** ({_vs_spy(extras['asof'], extras['spy_asof'])}).",
        f"- $5T died? **{'YES' if extras['trillion_died'] else 'NO'}** "
        f"(uncapped as-of ${ctrl['led'].end_equity:,.2f} / peak book ${extras['peak_book_uncapped']:,.2f} → "
        f"capped as-of ${extras['asof']:,.2f} / peak book ${extras['peak_book_capped']:,.2f}).",
        "",
        "## Honesty",
        "",
        "- Judge quality and realism, not “did we still print a huge number.”",
        "- If as-of is still tens of millions, 1% still compounds — HOLD, not a live recipe.",
        "- OOS is report-only. Do not retune 25% on OOS.",
        "- 10% name cap is the stricter sibling. Not run. Next yes/no only.",
        "- Not gold. Not DailyRun.",
        "",
        "## Pins / sources",
        "",
    ]
    for s in sources:
        lines.append(f"- {s}")
    lines.append("")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_hypothesis(tag: str, verdict: str) -> None:
    text = f"""# HYPOTHESIS — {STAMP}

**Product owner (PO)–aligned process:** one knob, frozen everything else. See `docs/HYPOTHESIS_TEST.md`.

| Field | Fill in |
|-------|---------|
| System / prefix | 5-sys {", ".join(FIVE)} (Indicators / IND out) |
| Baseline stamp | Control identity `risk2500_sys_matrix_20260917` 5-sys 1% sell-winner. Wallet engine `risk2500_five_sys_20260917` |
| Universe | House DailyRun 5-sys. Indicators (IND) excluded |
| **Evidence** | Paul: YES/NO cap per-name notional ≤25% of equity (10% stricter sibling, not this stamp); 5-sys 1% sell-winner + 25% name cap; print YE2012 + as-of vs SPY only |
| **Hypothesis** | After 1% size, clipping each ticker’s open notional to ≤25% of current equity stops tight stops from buying the whole 2× book (the cheap “stop the $5T” knob) without changing systems, risk %, sell-winner, $7,500, 10.5%, or 2× |
| **Single knob** | Per-name notional cap = 25% of current Closed-only equity. Off on the control |
| Frozen settings | $250k start. $7,500 on the 1st. 10.5% actual/365. Open ≤ 2×. Monthly risk 1%. RSI 6.51% IS freeze. Sell winner when BP empty. 10% cap not run |
| Alternatives | Uncapped 5-sys 1% sell-winner (control). SPY $250k total return. 10% name cap = next yes/no only |
| Candidate stamps | `{STAMP}` monthly.html / compare.html |
| Metrics | YE2012 vs SPY; as-of vs SPY; Max DD%; peak single-name / peak book vs uncapped; 2010/2011/2012; canonical IS/OOS (report-only) |
| **Trade-diff HTML** | N/A — size / wallet overlay (not an entry A/B) |
| ToS before path | N/A |
| ToS after path | N/A |
| **Decision** | {tag} — {verdict} |
| Reviewer | AI job {STAMP} |
| PO sign-off | no |
| Reconcile freeze / re-baseline done | no |
| DailyRun | not wired |

## Decision checklist

- [x] Evidence was the PO ask (25% name cap on 5-sys 1% sell-winner; YE2012 + as-of vs SPY)
- [x] One knob (25% per-name cap). 10% not shopped
- [x] Same Closed pins as the sibling $2,500 / matrix stamps
- [x] Out-of-Sample (OOS) report-only; no RSI retune; no 25% retune
- [ ] If adopt: PO signed off — **not adopting / not gold / not DailyRun**
"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "HYPOTHESIS.md").write_text(text, encoding="utf-8")


def run() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    spy = f.spy_buyhold()
    spy_dd = m.spy_paths(spy)
    print(
        f"[SPY] {spy['start_date']} -> {spy['end_date']} "
        f"TR {spy['tr_end']:.2f} ({spy['tr_mult']:.3f}x) "
        f"YE2012={spy_dd['eq_2012']:.2f} MaxDD={spy_dd['full_dd']:.2f}%",
        flush=True,
    )

    static = f.load_static(FIVE)
    sources = [
        f"overlays: {f.PREV_DIR.name} (RSI = RSI_overlay_avgloss.csv IS 6.51% freeze)",
        f"5-sys: {', '.join(FIVE)} — Indicators (IND) out",
        f"SPY: {f.SPY_PATH.as_posix()} Adj Close total return + Close price-only",
        "wallet: tools/risk2500_five_sys_20260917.py run_wallet",
        "control identity: risk2500_sys_matrix_20260917 5-sys 1% sell-winner "
        "($250k, $7,500, 10.5%, 2×, sell winner)",
        "one knob: name_cap_frac=0.25 after 1% size, before fill; then remaining BP",
        "10% name cap not run — next yes/no only",
        DD_DEF,
    ]

    ctrl = f._run_arm(
        static,
        rank=FIVE_RANK,
        rotate="winner",
        withdraw=True,
        label="5-sys · 1% sell winner (uncapped)",
        risk_frac=R_ONE,
        name_cap_frac=None,
    )
    ctrl["short"] = ctrl["label"]
    ctrl["read"] = "Matrix control. Tight stops can still buy the 2× book."

    cand = f._run_arm(
        static,
        rank=FIVE_RANK,
        rotate="winner",
        withdraw=True,
        label="5-sys · 1% sell winner + 25% name cap",
        risk_frac=R_ONE,
        name_cap_frac=NAME_CAP,
    )
    cand["short"] = cand["label"]
    cand["read"] = "One knob. Research only."

    tag, verdict, extras = _verdict(ctrl, cand, spy, spy_dd)
    print(f"[verdict] {tag} {verdict}", flush=True)

    f.r.write_overlay_csv(ctrl["trades"], OUT_DIR / "ALL_overlay_5sys_1pct_sw_uncapped.csv")
    f.r.write_overlay_csv(cand["trades"], OUT_DIR / "ALL_overlay_5sys_1pct_sw_namecap25.csv")

    now = datetime.now(tz=ET)
    monthly_html = build_monthly(
        ctrl=ctrl,
        cand=cand,
        spy=spy,
        spy_dd=spy_dd,
        tag=tag,
        verdict=verdict,
        extras=extras,
        sources=sources,
        generated=now,
    )
    compare_html = build_compare(
        ctrl=ctrl,
        cand=cand,
        spy=spy,
        spy_dd=spy_dd,
        tag=tag,
        verdict=verdict,
        extras=extras,
        sources=sources,
        generated=now,
    )
    (OUT_DIR / "monthly.html").write_text(monthly_html, encoding="utf-8")
    (OUT_DIR / "compare.html").write_text(compare_html, encoding="utf-8")
    write_baseline(
        ctrl=ctrl,
        cand=cand,
        spy=spy,
        spy_dd=spy_dd,
        tag=tag,
        verdict=verdict,
        extras=extras,
        sources=sources,
    )
    write_hypothesis(tag, verdict)

    summary = {
        "tag": tag,
        "verdict": verdict,
        "spy_tr_end": spy["tr_end"],
        "spy_2012": spy_dd["eq_2012"],
        "spy_max_dd_pct": spy_dd["full_dd"],
        "uncapped": {
            "end": ctrl["led"].end_equity,
            "eq_2010": ctrl["led"].eq_2010,
            "eq_2011": ctrl["led"].eq_2011,
            "eq_2012": ctrl["led"].eq_2012,
            "max_dd_pct": ctrl["led"].max_dd_pct,
            "peak_reserved": ctrl["led"].peak_reserved,
            "peak_name": ctrl["led"].peak_name_notional,
            "peak_name_symbol": ctrl["led"].peak_name_symbol,
            "n_rotate": ctrl["led"].n_rotate,
        },
        "namecap25": {
            "end": cand["led"].end_equity,
            "eq_2010": cand["led"].eq_2010,
            "eq_2011": cand["led"].eq_2011,
            "eq_2012": cand["led"].eq_2012,
            "max_dd_pct": cand["led"].max_dd_pct,
            "peak_reserved": cand["led"].peak_reserved,
            "peak_name": cand["led"].peak_name_notional,
            "peak_name_symbol": cand["led"].peak_name_symbol,
            "n_rotate": cand["led"].n_rotate,
            "n_name_capped": cand["led"].n_name_capped,
            "n_skip_name": cand["led"].n_skip_name,
        },
        "extras": extras,
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"wrote {OUT_DIR / 'monthly.html'}", flush=True)
    print(f"wrote {OUT_DIR / 'compare.html'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
