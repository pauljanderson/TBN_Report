#!/usr/bin/env python3
"""5-sys sell-winner + frozen $2,500 risk (does not scale with equity).

Stamp: drive/paul_experiments/risk2500_frozen_20260917/

Control identity = risk2500_sys_matrix_20260917 / namecap25 uncapped row:
5-sys 1% sell-winner ($250k, $7,500/mo, 10.5%, open ≤ 2×, RSI IS 6.51% freeze).

One knob: risk_dollar is always $2,500. No percent name cap this stamp.
10% name cap + $2,500 is the next yes/no only (not run unless free — it is not).

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

STAMP = "risk2500_frozen_20260917"
OUT_DIR = REPO / "drive" / "paul_experiments" / STAMP
ACCOUNT = f.ACCOUNT
ASOF = f.ASOF
ET = f.ET
WITHDRAW = f.WITHDRAW
MARGIN_RATE = f.MARGIN_RATE
LEVERAGE = f.LEVERAGE
R_ONE = 0.01
RISK_FROZEN = 2_500.0
FIVE = f.FIVE
FIVE_RANK = f.FIVE_RANK
DD_DEF = m.DD_DEF
RSI_SLOT = RISK_FROZEN / f.c.RSI_AVG_LOSS_FRAC

# Published siblings from risk2500_namecap25_20260917 (not re-run).
PUB_UNCAPPED_ASOF = 5_596_536_080_411.02
PUB_TEN_ASOF = 220_085_282_576.45
PUB_TEN = {
    "end": 220_085_282_576.45,
    "eq_2010": 281_839.17,
    "eq_2011": 411_885.05,
    "eq_2012": 553_740.87,
    "max_dd_pct": 28.95,
    "peak_reserved": 448_008_405_633.23,
    "peak_name": 22_919_086_769.28,
    "peak_name_symbol": "FEIM",
    "interest": 10_348_001_239.51,
    "withdrawals": 1_500_000.00,
    "n_rotate": 268,
    "n_skip_bp": 0,
    "n_skip_name": 35,
    "n_name_capped": 4104,
}

ORIGINAL_REQUEST = (
    "yes to 1 please — freeze risk at $2,500 (does not scale with equity). "
    "He did not pick keep-vs-drop the 10% name cap — drop the percent name cap "
    "this stamp so this is one knob only. Mention 10%+$2,500 as a later yes/no; "
    "do not run it unless it is truly free."
)
PLAIN_ENGLISH = (
    "Same five sleeves as the $5.60T / 10% / 25% books — StockBee (SB), "
    "Relative Strength Index (RSI), Volume Zone (VZ), Magic Touch (MTS), "
    "Rocket Launcher (RL). Indicators (IND) is out. Start $250,000 in one "
    "wallet. Pull $7,500 cash on the 1st. Pay 10.5% a year on whatever you "
    "borrowed. Open stock cost can be at most twice the account. When a new "
    "signal cannot fit even after shrinking to leftover buying power, sell "
    "the most profitable open name, then take the new one (same sell-winner "
    "rule as the trillion books — we did not shop a different rotation). "
    "The one new rule: every fill risks a flat $2,500 to the stop. That "
    "dollar does not grow when the account grows. RSI dollars in = "
    f"$2,500 ÷ 0.0651 ≈ ${RSI_SLOT:,.0f} every fill (In-Sample average-loser "
    "freeze 6.51%; do not retune after 2024); clip to leftover buying power. "
    "Other systems: shares = $2,500 ÷ (entry − stop), then leftover buying "
    "power. No per-name percent lid this page. The 10% name cap plus frozen "
    "$2,500 is a later yes/no only — not run here. Read year-end 2012 and "
    "today versus S&P 500 tracker (SPY). This should kill the $5.60T / $220B "
    "paper endings. Not gold. Not DailyRun."
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
    """Judge realism + YE2012/as-of vs SPY. Human-range still HOLD vs gold."""
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
    two_twenty_died = asof < 1.0e11
    still_huge = asof >= 10_000_000.0
    account_dead = asof < 50_000.0 or float(cled.withdrawals) + 1.0 < 1_400_000.0
    cst, ust = cand["stats_full"], ctrl["stats_full"]
    extras = {
        "trillion_died": trillion_died,
        "two_twenty_died": two_twenty_died,
        "still_huge": still_huge,
        "account_dead": account_dead,
        "asof": asof,
        "ye2012": ye2012,
        "spy_asof": spy_asof,
        "spy_2012": spy_2012,
        "peak_book_uncapped": peak_book_u,
        "peak_book_frozen": peak_book_c,
        "peak_name_uncapped": peak_name_u,
        "peak_name_frozen": peak_name_c,
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
        "eq_2010": float(cled.eq_2010),
        "eq_2011": float(cled.eq_2011),
        "pub_uncapped": PUB_UNCAPPED_ASOF,
        "pub_ten": PUB_TEN_ASOF,
        "rsi_slot": RSI_SLOT,
    }
    died_line = (
        f"$5.60T died? {'YES' if trillion_died else 'NO'}. "
        f"$220B (10% lid) died? {'YES' if two_twenty_died else 'NO'}. "
        f"Uncapped 1% as-of {format_money(float(uled.end_equity))} / peak book "
        f"{format_money(peak_book_u)} / peak name {format_money(peak_name_u)} "
        f"{uled.peak_name_symbol or '—'} → frozen $2,500 as-of {format_money(asof)} "
        f"/ peak book {format_money(peak_book_c)} / peak name "
        f"{format_money(peak_name_c)} {cled.peak_name_symbol or '—'}. "
        f"Published 10% lid as-of {format_money(PUB_TEN_ASOF)} "
        f"(sibling stamp, not re-run). "
    )
    path_line = (
        f"2010–2012 path — frozen $2,500 {format_money(cled.eq_2010)} / "
        f"{format_money(cled.eq_2011)} / {format_money(ye2012)}; "
        f"1% uncapped {format_money(uled.eq_2010)} / "
        f"{format_money(uled.eq_2011)} / {format_money(uled.eq_2012)}; "
        f"SPY {format_money(spy['years'].get(2010, {}).get('tr', 0))} / "
        f"{format_money(spy['years'].get(2011, {}).get('tr', 0))} / "
        f"{format_money(spy_2012)}. "
    )
    explode_why = ""
    if still_huge or not trillion_died:
        explode_why = (
            "If the pile is still huge, sell-winner plus the 2× cap can still "
            "recycle into tight-stop names: $2,500 ÷ a tiny (entry − stop) is "
            "a large share count, and open notional can sit at 2× equity. "
        )
    vs = (
        f"Year-end 2012 {format_money(ye2012)} vs SPY {format_money(spy_2012)}; "
        f"as-of {format_money(asof)} vs SPY {format_money(spy_asof)}. "
        f"Max DD {_fmt_pct(extras['dd_c'])} (1% uncapped {_fmt_pct(extras['dd_u'])}). "
    )
    next_knob = (
        "10% name cap + frozen $2,500 is the next yes/no only — not run. "
        "Do not retune $2,500 or 6.51% on Out-of-Sample. Not gold. Not DailyRun."
    )
    if account_dead and extras["dd_c"] >= 80.0:
        tag = "DISMISS"
        prose = (
            f"DISMISS as a live-size recipe — the frozen $2,500 book did not "
            f"survive the $7,500 wires "
            f"(withdrawn {format_money(float(cled.withdrawals))}; as-of "
            f"{format_money(asof)}). {died_line}{vs}{path_line}{next_knob}"
        )
        return tag, prose, extras
    if still_huge:
        tag = "HOLD"
        prose = (
            f"HOLD versus (a) the 5-sys 1% sell-winner and (b) gold / DailyRun. "
            f"{died_line}{explode_why}"
            f"As-of {format_money(asof)} is still not a live Fidelity recipe. "
            f"{vs}{path_line}{next_knob}"
        )
        return tag, prose, extras
    tag = "HOLD"
    prose = (
        f"HOLD versus gold / DailyRun — research size view only, even though "
        f"as-of is in a human range. {died_line}{vs}{path_line}"
        f"Judge 2010–2012 and as-of versus SPY; do not adopt from this one "
        f"page. {next_knob}"
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
  <h2>Headline — frozen $2,500 risk vs SPY</h2>
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
      <h3>Did $5.60T / $220B die?</h3>
      <div class="metric">{"YES" if extras["trillion_died"] else "NO"} / {"YES" if extras["two_twenty_died"] else "NO"}</div>
      <div class="small">1% peak book {format_money(extras['peak_book_uncapped'])} →
      frozen {format_money(extras['peak_book_frozen'])}</div>
      <div class="small">Peak name {format_money(extras['peak_name_uncapped'])}
      {html_mod.escape(extras['peak_name_sym_u'] or '—')} →
      {format_money(extras['peak_name_frozen'])}
      {html_mod.escape(extras['peak_name_sym_c'] or '—')}</div>
      <div class="small">Published 10% lid as-of {format_money(PUB_TEN_ASOF)}</div>
    </div>
    <div class="card">
      <h3>Max DD%</h3>
      <div class="metric">{_fmt_pct(extras['dd_c'])}</div>
      <div class="small">1% uncapped sell-winner {_fmt_pct(extras['dd_u'])}</div>
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
    rows: list[tuple[Any, ...]] = [
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
            "5-sys · 1% of equity each month · sell-winner · no name cap (matrix / namecap25 control)",
        ),
        (
            cand,
            "5-sys · risk frozen at $2,500 every fill · sell-winner · no name cap (one knob)",
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
    p = PUB_TEN
    rows.append(
        (
            "10% name cap (published sibling — not re-run)",
            "5-sys · 1% of equity · sell-winner · per-name ≤ 10% (namecap25 stamp)",
            p["end"],
            p["eq_2010"],
            p["eq_2011"],
            p["eq_2012"],
            p["max_dd_pct"],
            _vs_spy(p["end"], spy["tr_end"]),
            p["peak_reserved"],
            p["peak_name"],
            p["peak_name_symbol"],
            p["interest"],
            p["withdrawals"],
            f"{p['n_rotate']} / {p['n_skip_bp']} / {p['n_skip_name']}",
            p["n_name_capped"],
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
        '<tr class="total-row"><th>As-of / last</th><td class="small">Pinned frozen $2,500</td>'
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
        "Uncapped 5-sys 1% sell-winner is the control; frozen $2,500 is the one "
        "change. 10% lid row is the published namecap25 sibling (not re-run). "
        "10% + $2,500 not run — next yes/no only.</p>"
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
            ("1% uncapped 5-sys SW", "num"),
            ("Frozen $2,500", "num"),
            ("SPY total return", "num"),
            ("1% Max DD%", "num"),
            ("Frozen Max DD%", "num"),
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
            ("1% uncapped EOM", "num"),
            ("Frozen $2,500 EOM", "num"),
            ("SPY TR EOM", "num"),
            ("1% month Max DD%", "num"),
            ("Frozen month Max DD%", "num"),
            ("SPY month Max DD%", "num"),
        ]
    )
    keys = sorted(
        {(s.year, s.month) for s in ctrl["snaps"]}
        | {(s.year, s.month) for s in cand["snaps"]}
    )
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


def _book_bullet(title: str, pack: dict[str, Any]) -> str:
    led = pack["led"]
    st = pack["stats_full"]
    iso = pack["stats_is"]
    oos = pack["stats_oos"]
    return (
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
        (
            "IS",
            "In-Sample — entry before 2024-01-01. Path is continuous; do not retune $2,500 or 6.51% on OOS.",
        ),
        (
            "OOS",
            "Out-of-Sample — report-only. Do not pick $2,500 from this slice.",
        ),
        ("FULL", verdict),
    ):
        cols = [
            ("1% uncapped 5-sys SW", ctrl[col_map[sl]]),
            ("Frozen $2,500", cand[col_map[sl]]),
        ]
        compare_sections += f"""
<section>
<h2>Canonical compare · {sl}</h2>
<p class="small">{html_mod.escape(note)} Sheet / Total PnL $ omitted. Click headers to sort.</p>
<div class="table-wrap">{f._canonical_table(cols)}</div>
</section>"""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>5-sys sell-winner + frozen $2,500 risk — {STAMP}</title>
<style>{f._css()}</style></head><body>
<h1>Monthly Backtest Report — {ASOF.year} · 5-sys sell-winner + frozen $2,500 risk</h1>
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
fiction if tight stops plus sell-winner plus 2× keep recycling. SPY 2010 / 2011 / 2012:
{format_money(spy['years'].get(2010, {}).get('tr', 0))} /
{format_money(spy['years'].get(2011, {}).get('tr', 0))} /
{format_money(spy_dd['eq_2012'])}.
1% uncapped: 2010 {format_money(ctrl['led'].eq_2010)} · 2011 {format_money(ctrl['led'].eq_2011)} · 2012 {format_money(ctrl['led'].eq_2012)}.
Frozen $2,500: 2010 {format_money(cand['led'].eq_2010)} · 2011 {format_money(cand['led'].eq_2011)} · 2012 {format_money(cand['led'].eq_2012)}.
Published 10% lid YE2012 {format_money(PUB_TEN['eq_2012'])} / as-of {format_money(PUB_TEN_ASOF)}.
10% name cap + frozen $2,500 is the next yes/no only — not run.
</div>
<section>
<h2>Books at a glance</h2>
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
<h2>Ledger — 1% uncapped 5-sys sell-winner</h2>
<p class="small">Control identity from the matrix / namecap25 uncapped row. Click headers to sort.</p>
{f._ledger_table(ctrl['snaps'])}
</section>
<section>
<h2>Ledger — frozen $2,500 risk</h2>
<p class="small">One change: risk_dollar is always $2,500 (does not scale with equity). RSI slot ≈ {format_money(RSI_SLOT)} every fill. Click headers to sort.</p>
{f._ledger_table(cand['snaps'], risk_col="Frozen risk $")}
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
Sibling name cap: <a href="../risk2500_namecap25_20260917/compare.html">risk2500_namecap25_20260917</a>.
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
        ("IS", "In-Sample — entry before 2024-01-01. Do not retune $2,500 or 6.51% on OOS."),
        ("OOS", "Out-of-Sample — report-only."),
        ("FULL", verdict),
    ):
        cols = [
            ("1% uncapped 5-sys SW", ctrl[col_map[sl]]),
            ("Frozen $2,500", cand[col_map[sl]]),
        ]
        compare_sections += f"""
<section>
<h2>Canonical compare · {sl}</h2>
<p class="small">{html_mod.escape(note)} Sheet / Total PnL $ omitted. Click headers to sort.</p>
<div class="table-wrap">{f._canonical_table(cols)}</div>
</section>"""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Compare — frozen $2,500 vs 1% uncapped 5-sys vs SPY — {STAMP}</title>
<style>{f._css()}</style></head><body>
<h1>Compare — 5-sys sell-winner + frozen $2,500 vs 1% uncapped vs SPY</h1>
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
<h2>Books at a glance</h2>
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
10% name cap + frozen $2,500 not run — next yes/no only.</p>
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
        "- One stamp, one knob: **risk_dollar frozen at $2,500** on the 5-sys sell-winner book (does not scale with equity).",
        "- Control = `risk2500_sys_matrix_20260917` / namecap25 uncapped row: 5-sys 1% sell-winner (uncapped names). Re-run here so peak single-name / peak book are on the same engine.",
        "- **No percent name cap this stamp.** 10% + $2,500 is the next yes/no only — not run (a third wallet pass is not free).",
        "- 5-sys: StockBee (SB), Relative Strength Index (RSI), Volume Zone (VZ), Magic Touch (MTS), Rocket Launcher (RL). IND out.",
        "- Start $250,000; one wallet; $7,500 cash on the 1st; 10.5% actual/365 on debit; open notional ≤ 2× equity.",
        f"- RSI: invested = $2,500 / 0.06509607 ≈ ${RSI_SLOT:,.2f} every fill (In-Sample avg-loss freeze; do not retune OOS). Clip to remaining buying power.",
        "- Others: shares = 2500 / (entry − stop), clip to remaining buying power. **risk_dollar is always $2,500.**",
        "- When a new signal cannot fit even scaled: sell the most profitable open (last close vs entry), then fill. Same sell-winner freeze as the $5T / 25% / 10% books.",
        f"- Decision: **{tag}** — {verdict}",
        "",
        "## Frozen knobs",
        "",
        f"- Account seed: **${ACCOUNT:,.0f}**",
        f"- Leverage cap: **{LEVERAGE:.0f}×** Closed-only equity",
        f"- Margin rate: **{MARGIN_RATE:.1%}** actual/365 daily compound",
        f"- Withdrawal: **${WITHDRAW:,.0f}** on month-start after 2010-01-01",
        "- Room rule: **sell winner** when buying power < $1",
        f"- **One change:** monthly risk = **${RISK_FROZEN:,.0f}** every month (control = 1% of BOM equity).",
        "- Name cap: **off** (dropped this stamp).",
        "- In-Sample (IS) = `entry_date < 2024-01-01`. OOS report-only. Do not retune $2,500 or 6.51% on OOS.",
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
        _book_bullet("Uncapped 5-sys 1% sell-winner (control)", ctrl),
        _book_bullet("5-sys sell-winner + frozen $2,500 risk (candidate)", cand),
        (
            f"- **10% name cap (published sibling — not re-run)** end "
            f"**${PUB_TEN['end']:,.2f}**; 2010 ${PUB_TEN['eq_2010']:,.2f}; "
            f"2011 ${PUB_TEN['eq_2011']:,.2f}; 2012 ${PUB_TEN['eq_2012']:,.2f}; "
            f"Max DD {_fmt_pct(PUB_TEN['max_dd_pct'])}; peak book "
            f"${PUB_TEN['peak_reserved']:,.2f}; peak name ${PUB_TEN['peak_name']:,.2f} "
            f"({PUB_TEN['peak_name_symbol']}). From `risk2500_namecap25_20260917`."
        ),
        "",
        "## Headline vs SPY",
        "",
        f"- Year-end 2012: candidate **${extras['ye2012']:,.2f}** vs SPY **${extras['spy_2012']:,.2f}** ({_vs_spy(extras['ye2012'], extras['spy_2012'])}).",
        f"- As-of {ASOF.isoformat()}: candidate **${extras['asof']:,.2f}** vs SPY **${extras['spy_asof']:,.2f}** ({_vs_spy(extras['asof'], extras['spy_asof'])}).",
        f"- $5.60T died? **{'YES' if extras['trillion_died'] else 'NO'}** "
        f"(1% uncapped as-of ${ctrl['led'].end_equity:,.2f} / peak book ${extras['peak_book_uncapped']:,.2f} → "
        f"frozen as-of ${extras['asof']:,.2f} / peak book ${extras['peak_book_frozen']:,.2f}).",
        f"- $220B (10% lid) died? **{'YES' if extras['two_twenty_died'] else 'NO'}** "
        f"(published 10% as-of ${PUB_TEN_ASOF:,.2f}).",
        "",
        "## Honesty",
        "",
        "- Judge quality and realism, not “did we still print a huge number.”",
        "- If as-of is in a human range, still HOLD versus gold / DailyRun — research size view.",
        "- If it still explodes, sell-winner + 2× + tight stops can still size large notionals on $2,500 risk.",
        "- OOS is report-only. Do not retune $2,500 or 6.51% on OOS.",
        "- 10% name cap + frozen $2,500 is the next yes/no only. Not run.",
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
| Baseline stamp | Control identity `risk2500_sys_matrix_20260917` 5-sys 1% sell-winner (namecap25 uncapped row). Wallet engine `risk2500_five_sys_20260917` |
| Universe | House DailyRun 5-sys. Indicators (IND) excluded |
| **Evidence** | Paul: “yes to 1 please” — freeze risk at $2,500 (does not scale with equity). Drop the percent name cap this stamp so this is one knob only |
| **Hypothesis** | Freezing risk_dollar at $2,500 (RSI slot ≈ $2,500 / 0.0651; others shares = 2500 / (entry − stop)) kills the $5.60T / $220B paper endings without changing systems, sell-winner, $7,500, 10.5%, or 2× |
| **Single knob** | risk_dollar = $2,500 every month. Control = 1% of BOM Closed-only equity. Name cap off |
| Frozen settings | $250k start. $7,500 on the 1st. 10.5% actual/365. Open ≤ 2×. RSI 6.51% IS freeze. Sell winner when BP empty. Name cap off. 10%+$2,500 not run |
| Alternatives | Uncapped 5-sys 1% sell-winner (control). Published 10% lid sibling. SPY $250k total return. 10% + $2,500 = next yes/no only |
| Candidate stamps | `{STAMP}` monthly.html / compare.html |
| Metrics | YE2012 vs SPY; as-of vs SPY; Max DD%; peak single-name / peak book vs 1% and vs $5.60T / $220B; 2010/2011/2012; canonical IS/OOS (report-only) |
| **Trade-diff HTML** | N/A — size / wallet overlay (not an entry A/B) |
| ToS before path | N/A |
| ToS after path | N/A |
| **Decision** | {tag} — {verdict} |
| Reviewer | AI job {STAMP} |
| PO sign-off | no |
| Reconcile freeze / re-baseline done | no |
| DailyRun | not wired |

## Decision checklist

- [x] Evidence was the PO ask (freeze risk $ at $2,500; drop name cap this stamp; YE2012 + as-of vs SPY)
- [x] One knob (frozen $2,500 vs 1% of equity). 10%+$2,500 not shopped
- [x] Same Closed pins as the sibling $2,500 / matrix / namecap stamps
- [x] Out-of-Sample (OOS) report-only; no RSI retune; no $2,500 retune
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
    print(
        f"[size] frozen risk=${RISK_FROZEN:.0f} RSI slot~${RSI_SLOT:.2f} "
        f"(2500 / {f.c.RSI_AVG_LOSS_FRAC:.8f})",
        flush=True,
    )

    static = f.load_static(FIVE)
    sources = [
        f"overlays: {f.PREV_DIR.name} (RSI = RSI_overlay_avgloss.csv IS 6.51% freeze)",
        f"5-sys: {', '.join(FIVE)} — Indicators (IND) out",
        f"SPY: {f.SPY_PATH.as_posix()} Adj Close total return + Close price-only",
        "wallet: tools/risk2500_five_sys_20260917.py run_wallet",
        "control identity: risk2500_sys_matrix_20260917 5-sys 1% sell-winner "
        "($250k, $7,500, 10.5%, 2×, sell winner); namecap25 uncapped row",
        "one knob: fixed_risk_dollar=2500 (does not scale with equity); name cap off",
        "10% name cap + $2,500 not run — next yes/no only (third wallet is not free)",
        f"published 10% lid as-of ${PUB_TEN_ASOF:,.2f} from risk2500_namecap25_20260917",
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
    ctrl["read"] = "Matrix / namecap25 control. Risk = 1% of BOM equity."

    cand = f._run_arm(
        static,
        rank=FIVE_RANK,
        rotate="winner",
        withdraw=True,
        label="5-sys · frozen $2,500 sell winner (uncapped name)",
        risk_frac=R_ONE,
        name_cap_frac=None,
        fixed_risk_dollar=RISK_FROZEN,
    )
    cand["short"] = cand["label"]
    cand["read"] = "One knob. Research only."

    tag, verdict, extras = _verdict(ctrl, cand, spy, spy_dd)
    print(f"[verdict] {tag} {verdict}", flush=True)

    f.r.write_overlay_csv(ctrl["trades"], OUT_DIR / "ALL_overlay_5sys_1pct_sw_uncapped.csv")
    f.r.write_overlay_csv(cand["trades"], OUT_DIR / "ALL_overlay_5sys_frozen2500.csv")

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
        "rsi_slot": RSI_SLOT,
        "uncapped_1pct": {
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
        "frozen2500": {
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
        "published_10pct_lid_asof": PUB_TEN_ASOF,
        "extras": extras,
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"wrote {OUT_DIR / 'monthly.html'}", flush=True)
    print(f"wrote {OUT_DIR / 'compare.html'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
