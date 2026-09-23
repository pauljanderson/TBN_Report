#!/usr/bin/env python3
"""5-sys 1% sell-winner + 25% / 10% / 5% per-name cap siblings (research only).

Adds 10% and 5% to the existing 25% stamp so Paul has one table:

    drive/paul_experiments/risk2500_namecap25_20260917/

Same book as risk2500_namecap25_20260917. One knob: name_cap_frac.
Control = uncapped 5-sys 1% sell-winner (reuse / re-run). 25% reused as
the already-HOLD sibling. Do not retune on OOS. Not gold. Not DailyRun.
"""
from __future__ import annotations

import html as html_mod
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

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
R_ONE = 0.01
FIVE = f.FIVE
FIVE_RANK = f.FIVE_RANK
DD_DEF = m.DD_DEF
HUGE = 10_000_000.0
TRILLION = 1.0e12

ORIGINAL_REQUEST = (
    "what if we change the per-name cap from 25% to 10% and 5%? "
    "Same book, change only the per-name notional cap. Parent stamp "
    "risk2500_namecap25_20260917: 5-sys (SB, RSI, VZ, MTS, RL), 1% sell-winner, "
    "$7,500/mo wd, 10.5% margin, open ≤ 2× equity, RSI 6.51% avg-loss freeze. "
    "25% name cap was HOLD (YE2012 $1.24M vs SPY $334k; as-of still $3.74T vs "
    "SPY $2.25M). $5T did not die. Print YE2012 + as-of vs SPY for 25% (reuse) "
    "/ 10% / 5% / uncapped / SPY. Did 10% or 5% kill as-of trillions? If as-of "
    "is still huge, HOLD — next real knob is freeze risk $ at $2500."
)
PLAIN_ENGLISH = (
    "Same five sleeves — StockBee (SB), Relative Strength Index (RSI), "
    "Volume Zone (VZ), Magic Touch (MTS), Rocket Launcher (RL). Indicators "
    "(IND) is out. Start $250,000 in one wallet. Pull $7,500 cash on the 1st. "
    "Pay 10.5% a year on whatever you borrowed. Open stock cost can be at most "
    "twice the account. Each month risk 1% of the account: RSI dollars in = "
    "that 1% ÷ 0.0651 (In-Sample average-loser freeze; do not retune after 2024); "
    "other systems shares = 1% ÷ (entry − stop). When a new signal still cannot "
    "fit, sell the most profitable open name, then take the new one. The one "
    "knob we change: after that 1% size and before the fill, no single ticker "
    "may hold more than 25%, or 10%, or 5% of whatever the account is worth "
    "right then (plus the already-run uncapped book, no per-name lid). A tight "
    "stop can no longer buy the whole 2× book. If the name lid is still bigger "
    "than leftover buying power, shrink to leftover buying power. Read year-end "
    "2012 and today versus S&P 500 tracker (SPY). If 10% or 5% still print "
    "trillions, a percent-of-equity lid is the wrong next knob — freeze the "
    "monthly risk dollar at $2,500 instead. Not gold. Not DailyRun."
)

# key, frac, label, cap prose, overlay csv
ARM_SPEC: list[tuple[str, Optional[float], str, str, str]] = [
    (
        "uncapped",
        None,
        "5-sys · 1% sell winner (uncapped)",
        "5-sys · 1% sell-winner · no per-name cap (matrix control)",
        "ALL_overlay_5sys_1pct_sw_uncapped.csv",
    ),
    (
        "namecap25",
        0.25,
        "5-sys · 1% sell winner + 25% name cap",
        "5-sys · 1% sell-winner · per-name notional ≤ 25% of current equity",
        "ALL_overlay_5sys_1pct_sw_namecap25.csv",
    ),
    (
        "namecap10",
        0.10,
        "5-sys · 1% sell winner + 10% name cap",
        "5-sys · 1% sell-winner · per-name notional ≤ 10% of current equity",
        "ALL_overlay_5sys_1pct_sw_namecap10.csv",
    ),
    (
        "namecap05",
        0.05,
        "5-sys · 1% sell winner + 5% name cap",
        "5-sys · 1% sell-winner · per-name notional ≤ 5% of current equity",
        "ALL_overlay_5sys_1pct_sw_namecap05.csv",
    ),
]


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


def _led_pack(arm: dict[str, Any]) -> dict[str, Any]:
    led = arm["led"]
    st = arm["stats_full"]
    return {
        "end": float(led.end_equity),
        "eq_2010": float(led.eq_2010),
        "eq_2011": float(led.eq_2011),
        "eq_2012": float(led.eq_2012),
        "max_dd_pct": float(led.max_dd_pct),
        "peak_reserved": float(led.peak_reserved),
        "peak_name": float(led.peak_name_notional),
        "peak_name_symbol": led.peak_name_symbol or "—",
        "peak_name_frac": float(led.peak_name_frac),
        "n_rotate": int(led.n_rotate),
        "n_name_capped": int(led.n_name_capped),
        "n_skip_name": int(led.n_skip_name),
        "n_skip_bp": int(led.n_skip_bp),
        "interest": float(led.interest),
        "withdrawals": float(led.withdrawals),
        "wr": _num(st, "win_pct"),
        "avg": _num(st, "avg_pnl_pct"),
        "pf": _num(st, "pf"),
    }


def _trillion_died(asof: float, peak_book: float) -> bool:
    return asof < TRILLION and peak_book < TRILLION


def _quality_worse(cand: dict[str, Any], ctrl: dict[str, Any]) -> bool:
    return (
        cand["wr"] + 0.25 < ctrl["wr"]
        and cand["avg"] + 0.25 < ctrl["avg"]
        and cand["max_dd_pct"] > ctrl["max_dd_pct"] + 2.0
    )


def _verdict(
    books: dict[str, dict[str, Any]],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    """Judge 10% and 5%. 25% is the already-HOLD sibling. Do not retune OOS."""
    u = _led_pack(books["uncapped"])
    c25 = _led_pack(books["namecap25"])
    c10 = _led_pack(books["namecap10"])
    c05 = _led_pack(books["namecap05"])
    spy_asof = float(spy["tr_end"])
    spy_2012 = float(spy_dd["eq_2012"])
    extras: dict[str, Any] = {
        "spy_asof": spy_asof,
        "spy_2012": spy_2012,
        "uncapped": u,
        "namecap25": c25,
        "namecap10": c10,
        "namecap05": c05,
        "trillion_died_25": _trillion_died(c25["end"], c25["peak_reserved"]),
        "trillion_died_10": _trillion_died(c10["end"], c10["peak_reserved"]),
        "trillion_died_05": _trillion_died(c05["end"], c05["peak_reserved"]),
        "still_huge_10": c10["end"] >= HUGE,
        "still_huge_05": c05["end"] >= HUGE,
        "quality_worse_10": _quality_worse(c10, u),
        "quality_worse_05": _quality_worse(c05, u),
    }
    died_10 = extras["trillion_died_10"]
    died_05 = extras["trillion_died_05"]
    huge_10 = extras["still_huge_10"]
    huge_05 = extras["still_huge_05"]
    qw10 = extras["quality_worse_10"]
    qw05 = extras["quality_worse_05"]

    path = (
        f"2010–2012 path — uncapped {format_money(u['eq_2010'])} / "
        f"{format_money(u['eq_2011'])} / {format_money(u['eq_2012'])}; "
        f"25% {format_money(c25['eq_2010'])} / {format_money(c25['eq_2011'])} / "
        f"{format_money(c25['eq_2012'])}; "
        f"10% {format_money(c10['eq_2010'])} / {format_money(c10['eq_2011'])} / "
        f"{format_money(c10['eq_2012'])}; "
        f"5% {format_money(c05['eq_2010'])} / {format_money(c05['eq_2011'])} / "
        f"{format_money(c05['eq_2012'])}; "
        f"SPY {format_money(spy['years'].get(2010, {}).get('tr', 0))} / "
        f"{format_money(spy['years'].get(2011, {}).get('tr', 0))} / "
        f"{format_money(spy_2012)}."
    )
    tail = (
        f"{path} Do not retune 10% or 5% on Out-of-Sample. "
        "If as-of is still huge, the next real knob is freeze risk $ at $2,500 "
        "(not a tighter percent-of-equity lid). Not gold. Not DailyRun."
    )

    if (qw10 or qw05) and not (died_10 or died_05):
        tag = "DISMISS"
        prose = (
            f"DISMISS 10% and 5% versus the uncapped 5-sys 1% sell-winner — "
            f"quality got worse and the $5T book did not die. "
            f"10% year-end 2012 {format_money(c10['eq_2012'])} vs SPY "
            f"{format_money(spy_2012)}; as-of {format_money(c10['end'])} vs SPY "
            f"{format_money(spy_asof)}. 5% year-end 2012 {format_money(c05['eq_2012'])} "
            f"vs SPY {format_money(spy_2012)}; as-of {format_money(c05['end'])} vs SPY "
            f"{format_money(spy_asof)}. 25% stays HOLD (as-of {format_money(c25['end'])}). "
            f"{tail}"
        )
        return tag, prose, extras

    if huge_10 or huge_05:
        tag = "HOLD"
        ten_note = (
            f"10% left the trillion class (as-of {format_money(c10['end'])} / "
            f"peak book {format_money(c10['peak_reserved'])} / peak name "
            f"{format_money(c10['peak_name'])} {c10['peak_name_symbol']}) but "
            f"{format_money(c10['end'])} is still not a live Fidelity recipe — "
            "a 10% lid still scales with the pile. "
        )
        if c05["end"] < ACCOUNT * 0.1 or c05["max_dd_pct"] >= 90.0:
            five_note = (
                f"5% killed the account (as-of {format_money(c05['end'])} / "
                f"peak book {format_money(c05['peak_reserved'])} / peak name "
                f"{format_money(c05['peak_name'])} {c05['peak_name_symbol']}; "
                f"Max DD {_fmt_pct(c05['max_dd_pct'])}; year-end 2012 "
                f"{format_money(c05['eq_2012'])} lost to SPY {format_money(spy_2012)}; "
                f"only {format_money(c05['withdrawals'])} of the $7,500 wires paid). "
                "DISMISS 5% as a lid — too tight with this withdrawal. "
            )
        else:
            five_note = (
                f"5% as-of {format_money(c05['end'])} / peak book "
                f"{format_money(c05['peak_reserved'])} / peak name "
                f"{format_money(c05['peak_name'])} {c05['peak_name_symbol']}. "
            )
        died = (
            f"Uncapped as-of {format_money(u['end'])} / peak book "
            f"{format_money(u['peak_reserved'])} / peak name "
            f"{format_money(u['peak_name'])} {u['peak_name_symbol']}. "
            f"25% as-of {format_money(c25['end'])} / peak name "
            f"{format_money(c25['peak_name'])} {c25['peak_name_symbol']}. "
            f"{ten_note}{five_note}"
        )
        prose = (
            f"HOLD versus (a) the uncapped 5-sys 1% sell-winner and (b) SPY. "
            f"{died}"
            f"10% year-end 2012 {format_money(c10['eq_2012'])} vs SPY "
            f"{format_money(spy_2012)}; as-of {format_money(c10['end'])} vs SPY "
            f"{format_money(spy_asof)}. 5% year-end 2012 {format_money(c05['eq_2012'])} "
            f"vs SPY {format_money(spy_2012)}; as-of {format_money(c05['end'])} vs SPY "
            f"{format_money(spy_asof)}. "
            f"Max DD 10% {_fmt_pct(c10['max_dd_pct'])} · 5% {_fmt_pct(c05['max_dd_pct'])} "
            f"· 25% {_fmt_pct(c25['max_dd_pct'])} · uncapped {_fmt_pct(u['max_dd_pct'])}. "
            f"{tail}"
        )
        return tag, prose, extras

    if (
        (died_10 or died_05)
        and c10["eq_2012"] >= spy_2012 * 0.9
        and c05["eq_2012"] >= spy_2012 * 0.9
        and c10["max_dd_pct"] <= u["max_dd_pct"] + 1.0
        and c05["max_dd_pct"] <= u["max_dd_pct"] + 1.0
    ):
        tag = "KEEP"
        prose = (
            f"KEEP 10% / 5% as a research candidate on realism "
            f"(10% as-of {format_money(c10['end'])}; 5% as-of {format_money(c05['end'])}) "
            f"without collapsing year-end 2012 "
            f"(10% {format_money(c10['eq_2012'])}; 5% {format_money(c05['eq_2012'])} "
            f"vs SPY {format_money(spy_2012)}). Still not gold and not DailyRun — "
            f"one in-sample freeze, no walk-forward. {tail}"
        )
        return tag, prose, extras

    tag = "HOLD"
    prose = (
        f"HOLD versus (a) uncapped 5-sys 1% sell-winner and (b) SPY. "
        f"10% year-end 2012 {format_money(c10['eq_2012'])} vs SPY {format_money(spy_2012)}; "
        f"as-of {format_money(c10['end'])} vs SPY {format_money(spy_asof)}. "
        f"5% year-end 2012 {format_money(c05['eq_2012'])} vs SPY {format_money(spy_2012)}; "
        f"as-of {format_money(c05['end'])} vs SPY {format_money(spy_asof)}. "
        f"Quality and realism are mixed; do not adopt 10% or 5% from this one page. "
        f"{tail}"
    )
    return tag, prose, extras


def _headline_box(
    books: dict[str, dict[str, Any]],
    tag: str,
    extras: dict[str, Any],
) -> str:
    cls = "yes" if tag == "KEEP" else ("no" if tag == "DISMISS" else "holdtag")
    c10 = extras["namecap10"]
    c05 = extras["namecap05"]
    c25 = extras["namecap25"]
    u = extras["uncapped"]
    return f"""
<div class="lead">
  <h2>Headline — 10% and 5% name cap vs SPY</h2>
  <p><strong class="{cls}">{html_mod.escape(tag)}</strong> · research only · not gold · not DailyRun</p>
  <div class="cards">
    <div class="card card-shared">
      <h3>10% · year-end 2012 vs SPY</h3>
      <div class="metric">{format_money(c10['eq_2012'])}</div>
      <div class="small">SPY {format_money(extras['spy_2012'])} ·
      {_vs_spy(c10['eq_2012'], extras['spy_2012'])}</div>
    </div>
    <div class="card card-shared">
      <h3>10% · as-of {ASOF.isoformat()} vs SPY</h3>
      <div class="metric">{format_money(c10['end'])}</div>
      <div class="small">SPY {format_money(extras['spy_asof'])} ·
      {_vs_spy(c10['end'], extras['spy_asof'])}</div>
      <div class="small">Trillion class died? <strong>{"YES" if extras["trillion_died_10"] else "NO"}</strong>
      — still {format_money(c10['end'])}</div>
    </div>
    <div class="card card-shared">
      <h3>5% · year-end 2012 vs SPY</h3>
      <div class="metric">{format_money(c05['eq_2012'])}</div>
      <div class="small">SPY {format_money(extras['spy_2012'])} ·
      {_vs_spy(c05['eq_2012'], extras['spy_2012'])}</div>
    </div>
    <div class="card card-shared">
      <h3>5% · as-of {ASOF.isoformat()} vs SPY</h3>
      <div class="metric">{format_money(c05['end'])}</div>
      <div class="small">SPY {format_money(extras['spy_asof'])} ·
      {_vs_spy(c05['end'], extras['spy_asof'])}</div>
      <div class="small">{"Account died. DISMISS this lid." if (c05["end"] < ACCOUNT * 0.1 or c05["max_dd_pct"] >= 90.0) else ("Trillion class died? YES" if extras["trillion_died_05"] else "Trillion class died? NO")}</div>
    </div>
    <div class="card">
      <h3>25% (reuse) · YE2012 / as-of</h3>
      <div class="metric">{format_money(c25['eq_2012'])}</div>
      <div class="small">As-of {format_money(c25['end'])} ·
      $5T died? {"YES" if extras["trillion_died_25"] else "NO"}</div>
    </div>
    <div class="card">
      <h3>Peak single-name notional</h3>
      <div class="metric">{format_money(c10['peak_name'])}</div>
      <div class="small">10% {html_mod.escape(c10['peak_name_symbol'])} ·
      {c10['peak_name_frac']:.1%} of equity</div>
      <div class="small">5% {format_money(c05['peak_name'])}
      {html_mod.escape(c05['peak_name_symbol'])} · {c05['peak_name_frac']:.1%}</div>
      <div class="small">25% {format_money(c25['peak_name'])}
      {html_mod.escape(c25['peak_name_symbol'])} · {c25['peak_name_frac']:.1%}</div>
      <div class="small">Uncapped {format_money(u['peak_name'])}
      {html_mod.escape(u['peak_name_symbol'])} · {u['peak_name_frac']:.1%}</div>
    </div>
    <div class="card">
      <h3>Max DD%</h3>
      <div class="metric">{_fmt_pct(c10['max_dd_pct'])}</div>
      <div class="small">10% {_fmt_pct(c10['max_dd_pct'])} ·
      5% {_fmt_pct(c05['max_dd_pct'])}</div>
      <div class="small">25% {_fmt_pct(c25['max_dd_pct'])} ·
      uncapped {_fmt_pct(u['max_dd_pct'])}</div>
    </div>
  </div>
</div>"""


def _m(v: Any) -> str:
    if v is None:
        return "—"
    return format_money(float(v))


def _lead_table(
    books: dict[str, dict[str, Any]],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
    spec: list[tuple[str, Optional[float], str, str, str]],
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
            ("Peak name % equity", "num"),
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
            1.0,
            0.0,
            0.0,
            "0 / 0 / 0",
            0,
        )
    ]
    for key, _frac, _label, cap, _csv in spec:
        a = books[key]
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
                led.peak_name_frac,
                led.interest,
                led.withdrawals,
                f"{led.n_rotate} / {led.n_skip_bp} / {led.n_skip_name}",
                led.n_name_capped,
            )
        )

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
            pfrac,
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
            f"<td>{_fmt_pct(100.0 * float(pfrac) if pfrac is not None else None)}</td>"
            f"<td>{_m(interest)}</td>"
            f"<td>{_m(wd)}</td>"
            f"<td>{html_mod.escape(str(sk))}</td>"
            f"<td>{int(ncap)}</td>"
            "</tr>"
        )
    last_led = books["namecap05"]["led"]
    last = (
        '<tr class="total-row"><th>As-of / last (5% name cap)</th>'
        '<td class="small">Pinned</td>'
        f"<td>{format_money(last_led.end_equity)}</td>"
        f"<td>{format_money(last_led.eq_2010)}</td>"
        f"<td>{format_money(last_led.eq_2011)}</td>"
        f"<td>{format_money(last_led.eq_2012)}</td>"
        f"<td>{_fmt_pct(last_led.max_dd_pct)}</td>"
        f"<td>{html_mod.escape(_vs_spy(last_led.end_equity, spy['tr_end']))}</td>"
        f"<td>{format_money(last_led.peak_reserved)}</td>"
        f"<td>{format_money(last_led.peak_name_notional)}</td>"
        f"<td>{html_mod.escape(last_led.peak_name_symbol or '—')}</td>"
        f"<td>{_fmt_pct(100.0 * float(last_led.peak_name_frac))}</td>"
        f"<td>{format_money(last_led.interest)}</td>"
        f"<td>{format_money(last_led.withdrawals)}</td>"
        f"<td>{last_led.n_rotate} / {last_led.n_skip_bp} / {last_led.n_skip_name}</td>"
        f"<td>{last_led.n_name_capped}</td></tr>"
    )
    return (
        '<p class="small">Click column headers to sort. Total row pinned. '
        "Uncapped is the control. 25% is the already-HOLD sibling. "
        "10% and 5% are the one-knob siblings this page adds.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}{last}</tbody></table></div>"
    )


def _year_table(
    books: dict[str, dict[str, Any]],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
    spec: list[tuple[str, Optional[float], str, str, str]],
) -> str:
    labels = [
        ("uncapped", "Uncapped 5-sys 1% SW"),
        ("namecap25", "25% name cap"),
        ("namecap10", "10% name cap"),
        ("namecap05", "5% name cap"),
    ]
    head = f._sortable_head(
        [("Year-end", "num")]
        + [(lab, "num") for _k, lab in labels]
        + [
            ("SPY total return", "num"),
            ("Uncapped Max DD%", "num"),
            ("25% Max DD%", "num"),
            ("10% Max DD%", "num"),
            ("5% Max DD%", "num"),
            ("SPY Max DD%", "num"),
            ("Note", "text"),
        ]
    )
    body = ""
    for y in range(2010, ASOF.year + 1):
        cells = f"<td>{y}</td>"
        for key, _lab in labels:
            row = next((x for x in books[key]["years"] if x["year"] == y), None)
            cells += f"<td>{format_money(row['ending_equity']) if row else '—'}</td>"
        sy = spy["years"].get(y)
        sdd = spy_dd["years"].get(y, {})
        cells += f"<td>{format_money(sy['tr']) if sy else '—'}</td>"
        for key, _lab in labels:
            row = next((x for x in books[key]["years"] if x["year"] == y), None)
            cells += f"<td>{_fmt_pct(row['max_dd_pct']) if row else '—'}</td>"
        note = f"through {ASOF.isoformat()}" if y == ASOF.year else ""
        if y == 2012:
            note = "year-end 2012 headline"
        body += (
            f"<tr>{cells}<td>{_fmt_pct(sdd.get('max_dd_pct'))}</td>"
            f"<td class=\"small\">{html_mod.escape(note)}</td></tr>"
        )
    last = '<tr class="total-row"><th>Total / last</th>'
    for key, _lab in labels:
        last += f"<td>{format_money(books[key]['led'].end_equity)}</td>"
    last += f"<td>{format_money(spy['tr_end'])}</td>"
    for key, _lab in labels:
        last += f"<td>{_fmt_pct(books[key]['led'].max_dd_pct)}</td>"
    last += f"<td>{_fmt_pct(spy_dd['full_dd'])}</td><td class=\"small\">Pinned as-of</td></tr>"
    return (
        '<p class="small">Closed-only year-end vs $250k SPY total return. '
        "Click headers to sort. Total row pinned. 2010–2012 is the honest path.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}{last}</tbody></table></div>"
    )


def _path_2010_2012(
    books: dict[str, dict[str, Any]],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
) -> str:
    head = f._sortable_head(
        [
            ("Book", "text"),
            ("2010 end", "num"),
            ("2011 end", "num"),
            ("2012 end", "num"),
            ("vs SPY YE2012", "text"),
        ]
    )
    rows = [
        (
            "SPY $250k total return",
            spy["years"].get(2010, {}).get("tr"),
            spy["years"].get(2011, {}).get("tr"),
            spy_dd["eq_2012"],
            "1.00× (yardstick)",
        )
    ]
    for key, lab in (
        ("uncapped", "Uncapped 5-sys 1% SW"),
        ("namecap25", "25% name cap"),
        ("namecap10", "10% name cap"),
        ("namecap05", "5% name cap"),
    ):
        led = books[key]["led"]
        rows.append(
            (
                lab,
                led.eq_2010,
                led.eq_2011,
                led.eq_2012,
                _vs_spy(led.eq_2012, spy_dd["eq_2012"]),
            )
        )
    body = ""
    for name, y0, y1, y2, vs in rows:
        body += (
            "<tr>"
            f"<td>{html_mod.escape(str(name))}</td>"
            f"<td>{_m(y0)}</td>"
            f"<td>{_m(y1)}</td>"
            f"<td>{_m(y2)}</td>"
            f"<td>{html_mod.escape(str(vs))}</td>"
            "</tr>"
        )
    last_led = books["namecap05"]["led"]
    last = (
        '<tr class="total-row"><th>Pinned (5%)</th>'
        f"<td>{format_money(last_led.eq_2010)}</td>"
        f"<td>{format_money(last_led.eq_2011)}</td>"
        f"<td>{format_money(last_led.eq_2012)}</td>"
        f"<td>{html_mod.escape(_vs_spy(last_led.eq_2012, spy_dd['eq_2012']))}</td></tr>"
    )
    return (
        '<p class="small">Honest early path before later-year capacity fiction. '
        "Click headers to sort. Total row pinned.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}{last}</tbody></table></div>"
    )


def _month_path_table(
    books: dict[str, dict[str, Any]],
    spy_dd: dict[str, Any],
) -> str:
    keys_order = ["uncapped", "namecap25", "namecap10", "namecap05"]
    labs = {
        "uncapped": "Uncapped EOM",
        "namecap25": "25% cap EOM",
        "namecap10": "10% cap EOM",
        "namecap05": "5% cap EOM",
    }
    head = f._sortable_head(
        [("Month", "month")]
        + [(labs[k], "num") for k in keys_order]
        + [("SPY TR EOM", "num")]
        + [(labs[k].replace("EOM", "month Max DD%"), "num") for k in keys_order]
        + [("SPY month Max DD%", "num")]
    )
    all_keys: set[tuple[int, int]] = set()
    maps: dict[str, dict[tuple[int, int], Any]] = {}
    for k in keys_order:
        maps[k] = {(s.year, s.month): s for s in books[k]["snaps"]}
        all_keys |= set(maps[k])
    body = ""
    for key in sorted(all_keys):
        cells = f"<td>{key[0]}-{key[1]:02d}</td>"
        for k in keys_order:
            s = maps[k].get(key)
            cells += f"<td>{format_money(s.equity_end) if s else '—'}</td>"
        sm = spy_dd["months"].get(key, {})
        cells += f"<td>{format_money(sm['tr']) if sm else '—'}</td>"
        for k in keys_order:
            s = maps[k].get(key)
            cells += f"<td>{_fmt_pct(s.max_dd_pct) if s else '—'}</td>"
        cells += f"<td>{_fmt_pct(sm.get('max_dd_pct'))}</td>"
        body += f"<tr>{cells}</tr>"
    last = '<tr class="total-row"><th>As-of / last</th>'
    for k in keys_order:
        last += f"<td>{format_money(books[k]['led'].end_equity)}</td>"
    last += f"<td>{format_money(spy_dd['tr_end'])}</td>"
    for k in keys_order:
        last += f"<td>{_fmt_pct(books[k]['led'].max_dd_pct)}</td>"
    last += f"<td>{_fmt_pct(spy_dd['full_dd'])}</td></tr>"
    return (
        '<p class="small">Month-end Closed-only path. Click headers to sort. Total row pinned.</p>'
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}{last}</tbody></table></div>"
    )


def _compare_sections(books: dict[str, dict[str, Any]], verdict: str) -> str:
    col_map = {"IS": "stats_is", "OOS": "stats_oos", "FULL": "stats_full"}
    notes = {
        "IS": "In-Sample — entry before 2024-01-01. Path is continuous; do not retune 10% or 5% on OOS.",
        "OOS": "Out-of-Sample — report-only. Do not pick 10% or 5% from this slice.",
        "FULL": verdict,
    }
    html = ""
    for sl in ("IS", "OOS", "FULL"):
        cols = [
            ("Uncapped 5-sys 1% SW", books["uncapped"][col_map[sl]]),
            ("25% name cap", books["namecap25"][col_map[sl]]),
            ("10% name cap", books["namecap10"][col_map[sl]]),
            ("5% name cap", books["namecap05"][col_map[sl]]),
        ]
        html += f"""
<section>
<h2>Canonical compare · {sl}</h2>
<p class="small">{html_mod.escape(notes[sl])} Sheet / Total PnL $ omitted. Click headers to sort. Δ vs uncapped.</p>
<div class="table-wrap">{f._canonical_table(cols)}</div>
</section>"""
    return html


def _ask_block() -> str:
    return f"""
<div class="ask">
<h2>What you asked</h2>
<blockquote>{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN_ENGLISH)}</p>
</div>"""


def build_monthly(
    *,
    books: dict[str, dict[str, Any]],
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
    ledgers = ""
    for key, _frac, _lab, cap, _csv in ARM_SPEC:
        ledgers += f"""
<section>
<h2>Ledger — {html_mod.escape(books[key]['label'])}</h2>
<p class="small">{html_mod.escape(cap)}. Click headers to sort.</p>
{f._ledger_table(books[key]['snaps'])}
</section>"""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>5-sys 1% sell-winner + 25% / 10% / 5% name cap — {STAMP}</title>
<style>{f._css()}</style></head><body>
<h1>Monthly Backtest Report — {ASOF.year} · 5-sys 1% sell-winner + name-cap siblings</h1>
<p class="sub">
Stamp <code>{STAMP}</code>. Research only. <strong>Not gold. Not DailyRun.</strong>
Indicators (IND) out. Generated {html_mod.escape(gen_s)}. Click column headers to sort.
Added 10% and 5% to the 25% page so one table holds uncapped / 25% / 10% / 5% / SPY.
</p>
{_ask_block()}
{_headline_box(books, tag, extras)}
<div class="hold"><strong>{html_mod.escape(verdict)}</strong></div>
<div class="warn">
<strong>2010–2012 first.</strong> Later-year paper dollars can still be capacity
fiction even after a name cap. A percent-of-equity lid scales with the pile.
If 10% or 5% as-of is still huge, the next real knob is freeze risk $ at $2,500.
</div>
<section>
<h2>2010–2012 path</h2>
{_path_2010_2012(books, spy, spy_dd)}
</section>
<section>
<h2>Four books + SPY at a glance</h2>
{_lead_table(books, spy, spy_dd, ARM_SPEC)}
</section>
<section>
<h2>Year-end equity and Max DD%</h2>
{_year_table(books, spy, spy_dd, ARM_SPEC)}
</section>
<section>
<h2>Monthly path</h2>
{_month_path_table(books, spy_dd)}
</section>
{ledgers}
{_compare_sections(books, verdict)}
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
    books: dict[str, dict[str, Any]],
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
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Compare — 25% / 10% / 5% name cap vs uncapped vs SPY — {STAMP}</title>
<style>{f._css()}</style></head><body>
<h1>Compare — 5-sys 1% sell-winner · 25% / 10% / 5% name cap vs uncapped vs SPY</h1>
<p class="sub">
Stamp <code>{STAMP}</code>. Research only. <strong>Not gold. Not DailyRun.</strong>
Generated {html_mod.escape(gen_s)}. Click column headers to sort.
</p>
{_ask_block()}
{_headline_box(books, tag, extras)}
<div class="hold"><strong>{html_mod.escape(verdict)}</strong></div>
<section>
<h2>2010–2012 path</h2>
{_path_2010_2012(books, spy, spy_dd)}
</section>
<section>
<h2>Four books + SPY at a glance</h2>
{_lead_table(books, spy, spy_dd, ARM_SPEC)}
</section>
<section>
<h2>Year-end equity and Max DD%</h2>
{_year_table(books, spy, spy_dd, ARM_SPEC)}
</section>
{_compare_sections(books, verdict)}
<section>
<h2>Max drawdown definition</h2>
<p>{html_mod.escape(DD_DEF)}</p>
</section>
<section>
<h2>Data sources</h2>
<ul class="sources">{sources_html}</ul>
<p class="small">Monthly: <a href="monthly.html">monthly.html</a>.
Next real knob if as-of is still huge: freeze risk $ at $2,500. Not gold. Not DailyRun.</p>
</section>
{f.r.monthly._SORTABLE_TABLE_SCRIPT}
</body></html>"""


def _book_bullet(title: str, arm: dict[str, Any]) -> str:
    led = arm["led"]
    st = arm["stats_full"]
    iso = arm["stats_is"]
    oos = arm["stats_oos"]
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


def write_baseline(
    *,
    books: dict[str, dict[str, Any]],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
    tag: str,
    verdict: str,
    extras: dict[str, Any],
    sources: list[str],
) -> None:
    c10 = extras["namecap10"]
    c05 = extras["namecap05"]
    c25 = extras["namecap25"]
    u = extras["uncapped"]
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
        "Indicators (IND) is the old live sleeve (~−$40k, 35 lots, go-live 2026); it is not DailyRun-wired; all books exclude it.",
        "",
        "## Selection",
        "",
        "- One stamp, one knob: **per-name notional cap % of current Closed-only equity** on the frozen 5-sys 1% sell-winner book.",
        "- Control = `risk2500_sys_matrix_20260917` 5-sys 1% sell-winner (uncapped names). Re-run here so peak single-name / peak book are on the same engine.",
        "- 25% is the already-HOLD sibling from this stamp. **10% and 5%** are the two pre-agreed alternatives this page adds. No other knobs.",
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
        "- **One change:** name cap **off / 25% / 10% / 5%** of current (cash + reserved) equity, applied after 1% size and before fill. Same-ticker open lots share the cap room.",
        "- If the name lid still exceeds remaining buying power, scale to remaining buying power.",
        "- In-Sample (IS) = `entry_date < 2024-01-01`. OOS report-only. Do not retune 10% or 5% on OOS.",
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
        _book_bullet("Uncapped 5-sys 1% sell-winner (control)", books["uncapped"]),
        _book_bullet("5-sys 1% sell-winner + 25% name cap (already HOLD)", books["namecap25"]),
        _book_bullet("5-sys 1% sell-winner + 10% name cap", books["namecap10"]),
        _book_bullet("5-sys 1% sell-winner + 5% name cap", books["namecap05"]),
        "",
        "## Headline vs SPY",
        "",
        f"- 10% year-end 2012: **${c10['eq_2012']:,.2f}** vs SPY **${extras['spy_2012']:,.2f}** ({_vs_spy(c10['eq_2012'], extras['spy_2012'])}).",
        f"- 10% as-of {ASOF.isoformat()}: **${c10['end']:,.2f}** vs SPY **${extras['spy_asof']:,.2f}** ({_vs_spy(c10['end'], extras['spy_asof'])}). $5T died? **{'YES' if extras['trillion_died_10'] else 'NO'}**.",
        f"- 5% year-end 2012: **${c05['eq_2012']:,.2f}** vs SPY **${extras['spy_2012']:,.2f}** ({_vs_spy(c05['eq_2012'], extras['spy_2012'])}).",
        f"- 5% as-of {ASOF.isoformat()}: **${c05['end']:,.2f}** vs SPY **${extras['spy_asof']:,.2f}** ({_vs_spy(c05['end'], extras['spy_asof'])}). $5T died? **{'YES' if extras['trillion_died_05'] else 'NO'}**.",
        f"- 25% (reuse) YE2012 **${c25['eq_2012']:,.2f}** / as-of **${c25['end']:,.2f}**. $5T died? **{'YES' if extras['trillion_died_25'] else 'NO'}**.",
        f"- Uncapped as-of **${u['end']:,.2f}** / peak book **${u['peak_reserved']:,.2f}** / peak name **${u['peak_name']:,.2f}** {u['peak_name_symbol']}.",
        "",
        "## Honesty",
        "",
        "- Judge quality and realism, not “did we still print a huge number.”",
        "- If as-of is still tens of millions, 1% still compounds — HOLD, not a live recipe.",
        "- OOS is report-only. Do not retune 10% or 5% on OOS.",
        "- If 10% or 5% as-of is still huge, the next real knob is freeze risk $ at $2,500 — not a tighter percent lid.",
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
| Baseline stamp | Control identity `risk2500_sys_matrix_20260917` 5-sys 1% sell-winner. Wallet engine `risk2500_five_sys_20260917`. Parent 25% page on this same stamp |
| Universe | House DailyRun 5-sys. Indicators (IND) excluded |
| **Evidence** | Paul: what if we change the per-name cap from 25% to 10% and 5%? Same book, one knob. 25% was HOLD; $5T did not die |
| **Hypothesis** | After 1% size, a tighter per-name notional lid (10% or 5% of current equity) stops tight stops from buying the whole 2× book and might kill as-of trillions without changing systems, risk %, sell-winner, $7,500, 10.5%, or 2× |
| **Single knob** | Per-name notional cap % of current Closed-only equity. Off / 25% / 10% / 5%. Two pre-agreed alternatives (10%, 5%) plus the already-run 25% sibling |
| Frozen settings | $250k start. $7,500 on the 1st. 10.5% actual/365. Open ≤ 2×. Monthly risk 1%. RSI 6.51% IS freeze. Sell winner when BP empty |
| Alternatives | Uncapped 5-sys 1% sell-winner (control). 25% already HOLD. SPY $250k total return. Next real knob if still huge: freeze risk $ at $2,500 |
| Candidate stamps | `{STAMP}` monthly.html / compare.html (10% / 5% added to the 25% page) |
| Metrics | YE2012 vs SPY; as-of vs SPY; Max DD%; peak single-name / peak book; 2010/2011/2012; canonical IS/OOS (report-only) |
| **Trade-diff HTML** | N/A — size / wallet overlay (not an entry A/B) |
| ToS before path | N/A |
| ToS after path | N/A |
| **Decision** | {tag} — {verdict} |
| Reviewer | AI job risk2500_namecap10_5_20260917 (writes into {STAMP}) |
| PO sign-off | no |
| Reconcile freeze / re-baseline done | no |
| DailyRun | not wired |

## Decision checklist

- [x] Evidence was the PO ask (10% and 5% name cap on the same 5-sys 1% sell-winner book; YE2012 + as-of vs SPY)
- [x] One knob (name cap %). Two pre-agreed alternatives (10%, 5%). 25% reused. No other knobs shopped
- [x] Same Closed pins as the sibling $2,500 / matrix stamps
- [x] Out-of-Sample (OOS) report-only; no RSI retune; no 10% / 5% retune
- [ ] If adopt: PO signed off — **not adopting / not gold / not DailyRun**
"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "HYPOTHESIS.md").write_text(text, encoding="utf-8")


def _jsonable(d: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out[k] = _jsonable(v)
        elif isinstance(v, bool):
            out[k] = v
        elif isinstance(v, (int, float, str)) or v is None:
            out[k] = v
        else:
            out[k] = str(v)
    return out


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
        "one knob: name_cap_frac off / 0.25 / 0.10 / 0.05 after 1% size, before fill; then remaining BP",
        "10% and 5% added to the 25% stamp so one table holds all siblings",
        "next real knob if as-of still huge: freeze risk $ at $2500",
        DD_DEF,
    ]

    books: dict[str, dict[str, Any]] = {}
    for key, frac, label, _cap, csv_name in ARM_SPEC:
        arm = f._run_arm(
            static,
            rank=FIVE_RANK,
            rotate="winner",
            withdraw=True,
            label=label,
            risk_frac=R_ONE,
            name_cap_frac=frac,
        )
        arm["short"] = arm["label"]
        arm["read"] = "One knob. Research only."
        books[key] = arm
        f.r.write_overlay_csv(arm["trades"], OUT_DIR / csv_name)

    tag, verdict, extras = _verdict(books, spy, spy_dd)
    print(f"[verdict] {tag} {verdict}", flush=True)

    now = datetime.now(tz=ET)
    monthly_html = build_monthly(
        books=books,
        spy=spy,
        spy_dd=spy_dd,
        tag=tag,
        verdict=verdict,
        extras=extras,
        sources=sources,
        generated=now,
    )
    compare_html = build_compare(
        books=books,
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
        books=books,
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
        "uncapped": extras["uncapped"],
        "namecap25": extras["namecap25"],
        "namecap10": extras["namecap10"],
        "namecap05": extras["namecap05"],
        "extras": _jsonable(extras),
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"wrote {OUT_DIR / 'monthly.html'}", flush=True)
    print(f"wrote {OUT_DIR / 'compare.html'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
