#!/usr/bin/env python3
"""5-sys sell-winner + min(1% BOM, $50k) risk + 1% ADV20 share cap.

Stamp: drive/paul_experiments/risk_1pct_50k_adv_20260917/

One knob pair vs frozen $2,500 flat (risk2500_frozen_20260917) and vs
1% uncapped $5.60T. Do NOT add a 10% per-name cap or a declining 2%
billion-step this stamp (third knob / selection).

Not gold. Not DailyRun. Do not retune $50k or 1% ADV on OOS.
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

STAMP = "risk_1pct_50k_adv_20260917"
OUT_DIR = REPO / "drive" / "paul_experiments" / STAMP
ACCOUNT = f.ACCOUNT
ASOF = f.ASOF
ET = f.ET
WITHDRAW = f.WITHDRAW
MARGIN_RATE = f.MARGIN_RATE
LEVERAGE = f.LEVERAGE
R_ONE = 0.01
RISK_CAP = 50_000.0
ADV_FRAC = 0.01
ADV_WINDOW = f.ADV_WINDOW
RISK_FROZEN = 2_500.0
FIVE = f.FIVE
FIVE_RANK = f.FIVE_RANK
DD_DEF = m.DD_DEF
RSI_SLOT_50K = RISK_CAP / f.c.RSI_AVG_LOSS_FRAC

# Published sibling from risk2500_frozen_20260917 (re-run here for the path).
PUB_FROZEN = {
    "end": 5_935_426.95,
    "eq_2010": 359_318.61,
    "eq_2011": 582_882.22,
    "eq_2012": 682_250.82,
    "max_dd_pct": 22.27,
    "peak_reserved": 4_627_358.44,
    "peak_name": 4_006_449.52,
    "peak_name_symbol": "AU",
}
PUB_UNCAPPED_ASOF = 5_596_536_080_411.02
PUB_SPY_2012 = 334_287.97
PUB_SPY_ASOF = 2_254_118.95

ORIGINAL_REQUEST = (
    "run this book unless his 10% / declining-cap comments change it: "
    "risk = min(1% of month-start equity, $50k) AND shares ≤ 1% of ADV. "
    "Same 5 systems (SB, RSI, VZ, MTS, RL), $7,500/mo wires, 10.5% margin, "
    "2× buying power. Score YE2012 + as-of vs SPY. He also likes a 10% "
    "per-name notional cap, and maybe a declining cap (2% at billions) while "
    "still allowing $1B+ in NVDA/META — coordinator already said that does "
    "not change this run: the $50k risk ceiling binds mega-caps long before "
    "10% of a $1B book. Declining 2% is a later yes/no. Do not add 10% name "
    "cap or 2% step-down this stamp."
)
PLAIN_ENGLISH = (
    "Same five sleeves as the frozen $2,500 and $5.60T books — StockBee (SB), "
    "Relative Strength Index (RSI), Volume Zone (VZ), Magic Touch (MTS), "
    "Rocket Launcher (RL). Indicators (IND) is out. Start $250,000 in one "
    "wallet. Pull $7,500 cash on the 1st. Pay 10.5% a year on whatever you "
    "borrowed. Open stock cost can be at most twice the account. When a new "
    "signal cannot fit even after shrinking to leftover buying power, sell "
    "the most profitable open name, then take the new one (same sell-winner "
    "rule — we did not shop a different rotation). The one new size pair: "
    "each month risk the smaller of 1% of the month-start account or $50,000 "
    "to the stop. RSI dollars in = that risk ÷ 0.0651 (In-Sample average-loser "
    "freeze 6.51%; do not retune after 2024) — at the $50k lid that is about "
    f"${RSI_SLOT_50K:,.0f} before other clips. Other systems: shares = risk ÷ "
    "(entry − stop). Then we also refuse to buy more than 1% of the name’s "
    f"{ADV_WINDOW}-session average daily share volume (on-disk daily Volume; "
    "last known bar if that day is missing; skip the fill if we never had a "
    "full 20-day window). Leftover buying power still clips last. No 10% "
    "per-name lid and no 2%-at-billions step-down on this page — those are "
    "the next yes/no only. The $50k lid should bind NVIDIA (NVDA) / Meta "
    "Platforms (META) long before 10% of a billion-dollar book. Read year-end "
    "2012 and today versus S&P 500 tracker (SPY). Not gold. Not DailyRun."
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
    frozen: dict[str, Any],
    cand: dict[str, Any],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    cled, uled, fled = cand["led"], ctrl["led"], frozen["led"]
    spy_asof = float(spy["tr_end"])
    spy_2012 = float(spy_dd["eq_2012"])
    asof = float(cled.end_equity)
    ye2012 = float(cled.eq_2012)
    frozen_asof = float(fled.end_equity)
    frozen_2012 = float(fled.eq_2012)
    trillion_died = asof < 1.0e12 and float(cled.peak_reserved) < 1.0e12
    still_huge = asof >= 10_000_000.0
    account_dead = asof < 50_000.0 or float(cled.withdrawals) + 1.0 < 1_400_000.0
    n_fills = max(1, int(cled.n_full) + int(cled.n_scaled))
    extras = {
        "trillion_died": trillion_died,
        "still_huge": still_huge,
        "account_dead": account_dead,
        "asof": asof,
        "ye2012": ye2012,
        "spy_asof": spy_asof,
        "spy_2012": spy_2012,
        "frozen_asof": frozen_asof,
        "frozen_2012": frozen_2012,
        "uncapped_asof": float(uled.end_equity),
        "uncapped_2012": float(uled.eq_2012),
        "peak_book_u": float(uled.peak_reserved),
        "peak_book_f": float(fled.peak_reserved),
        "peak_book_c": float(cled.peak_reserved),
        "peak_name_u": float(uled.peak_name_notional),
        "peak_name_f": float(fled.peak_name_notional),
        "peak_name_c": float(cled.peak_name_notional),
        "peak_name_sym_u": uled.peak_name_symbol,
        "peak_name_sym_f": fled.peak_name_symbol,
        "peak_name_sym_c": cled.peak_name_symbol,
        "dd_c": float(cled.max_dd_pct),
        "dd_u": float(uled.max_dd_pct),
        "dd_f": float(fled.max_dd_pct),
        "n_risk_1pct": int(cled.n_risk_1pct_bound),
        "n_risk_50k": int(cled.n_risk_50k_bound),
        "n_adv_clip": int(cled.n_adv_clipped),
        "n_adv_miss": int(cled.n_adv_missing),
        "n_adv_last": int(cled.n_adv_last_known),
        "n_skip_adv": int(cled.n_skip_adv),
        "n_months_50k": int(cled.n_months_50k),
        "n_fills": n_fills,
        "pct_50k": 100.0 * int(cled.n_risk_50k_bound) / n_fills,
        "pct_1pct": 100.0 * int(cled.n_risk_1pct_bound) / n_fills,
        "pct_adv": 100.0 * int(cled.n_adv_clipped) / n_fills,
        "eq_2010": float(cled.eq_2010),
        "eq_2011": float(cled.eq_2011),
        "rsi_slot_50k": RSI_SLOT_50K,
        "who_bound": (
            "both $50k and ADV"
            if int(cled.n_risk_50k_bound) >= n_fills * 0.25
            and int(cled.n_adv_clipped) >= n_fills * 0.25
            else (
                "$50k risk lid"
                if int(cled.n_risk_50k_bound) >= int(cled.n_adv_clipped)
                else "1% ADV share cap"
            )
        ),
    }
    bind_line = (
        f"On the candidate, {extras['n_risk_1pct']:,} fills were 1%-bound "
        f"({extras['pct_1pct']:.1f}%), {extras['n_risk_50k']:,} were $50k-bound "
        f"({extras['pct_50k']:.1f}%, {extras['n_months_50k']} months at the lid), "
        f"{extras['n_adv_clip']:,} were ADV-clipped ({extras['pct_adv']:.1f}%), "
        f"{extras['n_adv_miss']:,} skipped for missing ADV20, "
        f"{extras['n_adv_last']:,} used last-known ADV. "
        f"The workhorse was {extras['who_bound']}. "
    )
    died_line = (
        f"$5.60T died? {'YES' if trillion_died else 'NO'}. "
        f"1% uncapped as-of {format_money(float(uled.end_equity))} / peak book "
        f"{format_money(extras['peak_book_u'])} / peak name "
        f"{format_money(extras['peak_name_u'])} {uled.peak_name_symbol or '—'} -> "
        f"candidate as-of {format_money(asof)} / peak book "
        f"{format_money(extras['peak_book_c'])} / peak name "
        f"{format_money(extras['peak_name_c'])} {cled.peak_name_symbol or '—'}. "
        f"Frozen $2,500 as-of {format_money(frozen_asof)} / peak book "
        f"{format_money(extras['peak_book_f'])} / peak name "
        f"{format_money(extras['peak_name_f'])} {fled.peak_name_symbol or '—'}. "
    )
    path_line = (
        f"2010–2012 path — candidate {format_money(cled.eq_2010)} / "
        f"{format_money(cled.eq_2011)} / {format_money(ye2012)}; "
        f"frozen $2,500 {format_money(fled.eq_2010)} / "
        f"{format_money(fled.eq_2011)} / {format_money(frozen_2012)}; "
        f"1% uncapped {format_money(uled.eq_2010)} / "
        f"{format_money(uled.eq_2011)} / {format_money(uled.eq_2012)}; "
        f"SPY {format_money(spy['years'].get(2010, {}).get('tr', 0))} / "
        f"{format_money(spy['years'].get(2011, {}).get('tr', 0))} / "
        f"{format_money(spy_2012)}. "
    )
    vs = (
        f"Year-end 2012 {format_money(ye2012)} vs SPY {format_money(spy_2012)} "
        f"({_vs_spy(ye2012, spy_2012)}); "
        f"as-of {format_money(asof)} vs SPY {format_money(spy_asof)} "
        f"({_vs_spy(asof, spy_asof)}). "
        f"Max DD {_fmt_pct(extras['dd_c'])} (frozen {_fmt_pct(extras['dd_f'])}; "
        f"1% uncapped {_fmt_pct(extras['dd_u'])}). "
    )
    next_knob = (
        "10% per-name notional cap and a declining 2% at billions are the next "
        "yes/no only — not run. The $50k risk ceiling binds mega-caps long "
        "before 10% of a $1B book ($50k ÷ a 2% stop ≈ $2.5M notional vs $100M "
        "at a 10% name lid). Do not retune $50k or 1% ADV on Out-of-Sample. "
        "Not gold. Not DailyRun."
    )
    if account_dead and extras["dd_c"] >= 80.0:
        tag = "DISMISS"
        prose = (
            f"DISMISS as a live-size recipe — the $50k + ADV book did not "
            f"survive the $7,500 wires "
            f"(withdrawn {format_money(float(cled.withdrawals))}; as-of "
            f"{format_money(asof)}). {died_line}{bind_line}{vs}{path_line}{next_knob}"
        )
        return tag, prose, extras
    if still_huge:
        tag = "HOLD"
        prose = (
            f"HOLD versus (a) frozen $2,500, (b) the 5-sys 1% sell-winner, and "
            f"(c) gold / DailyRun. {died_line}{bind_line}"
            f"As-of {format_money(asof)} is still not a live Fidelity recipe. "
            f"{vs}{path_line}{next_knob}"
        )
        return tag, prose, extras
    beat_spy = asof > spy_asof and ye2012 >= spy_2012 * 0.9
    if trillion_died and beat_spy:
        tag = "HOLD"
        prose = (
            f"HOLD versus frozen $2,500 and versus gold / DailyRun — research "
            f"size view only, even though $5.60T died and the book beat SPY. "
            f"{died_line}{bind_line}{vs}{path_line}"
            f"Versus frozen $2,500 ({format_money(frozen_2012)} YE2012 / "
            f"{format_money(frozen_asof)} as-of) this book is larger by design "
            f"(risk can grow to $50k). Do not pick $50k vs $2,500 from this "
            f"one page. {next_knob}"
        )
        return tag, prose, extras
    tag = "HOLD"
    prose = (
        f"HOLD versus frozen $2,500, versus 1% uncapped, and versus gold / "
        f"DailyRun. {died_line}{bind_line}{vs}{path_line}"
        f"Judge 2010–2012 and as-of versus SPY; do not adopt from this one "
        f"page. {next_knob}"
    )
    return tag, prose, extras


def _headline_box(
    tag: str,
    extras: dict[str, Any],
) -> str:
    cls = "yes" if tag == "KEEP" else ("no" if tag == "DISMISS" else "holdtag")
    return f"""
<div class="lead">
  <h2>Headline — min(1%, $50k) + 1% ADV vs SPY</h2>
  <p><strong class="{cls}">{html_mod.escape(tag)}</strong> · research only · not gold · not DailyRun</p>
  <div class="cards">
    <div class="card card-shared">
      <h3>Year-end 2012 vs SPY</h3>
      <div class="metric">{format_money(extras['ye2012'])}</div>
      <div class="small">SPY {format_money(extras['spy_2012'])} ·
      {_vs_spy(extras['ye2012'], extras['spy_2012'])}</div>
      <div class="small">Frozen $2,500 {format_money(extras['frozen_2012'])} ·
      1% uncapped {format_money(extras['uncapped_2012'])}</div>
    </div>
    <div class="card card-shared">
      <h3>As-of {ASOF.isoformat()} vs SPY</h3>
      <div class="metric">{format_money(extras['asof'])}</div>
      <div class="small">SPY {format_money(extras['spy_asof'])} ·
      {_vs_spy(extras['asof'], extras['spy_asof'])}</div>
      <div class="small">Frozen $2,500 {format_money(extras['frozen_asof'])} ·
      1% uncapped {format_money(extras['uncapped_asof'])}</div>
    </div>
    <div class="card">
      <h3>Did $5.60T die?</h3>
      <div class="metric">{"YES" if extras["trillion_died"] else "NO"}</div>
      <div class="small">1% peak book {format_money(extras['peak_book_u'])} →
      candidate {format_money(extras['peak_book_c'])}</div>
      <div class="small">Peak name {format_money(extras['peak_name_u'])}
      {html_mod.escape(extras['peak_name_sym_u'] or '—')} →
      {format_money(extras['peak_name_c'])}
      {html_mod.escape(extras['peak_name_sym_c'] or '—')}</div>
    </div>
    <div class="card">
      <h3>Who bound?</h3>
      <div class="metric">{html_mod.escape(extras['who_bound'])}</div>
      <div class="small">$50k {extras['n_risk_50k']:,} fills ({extras['pct_50k']:.1f}%) ·
      1% {extras['n_risk_1pct']:,} ({extras['pct_1pct']:.1f}%) ·
      ADV clip {extras['n_adv_clip']:,} ({extras['pct_adv']:.1f}%)</div>
      <div class="small">Max DD {_fmt_pct(extras['dd_c'])} ·
      frozen {_fmt_pct(extras['dd_f'])}</div>
    </div>
  </div>
</div>"""


def _lead_table(
    ctrl: dict[str, Any],
    frozen: dict[str, Any],
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
            ("Rotates / BP-skip", "text"),
            ("$50k / 1% / ADV-clip fills", "text"),
            ("ADV miss / last-known", "text"),
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
            "0 / 0",
            "—",
            "—",
        )
    ]
    for a, cap in (
        (
            ctrl,
            "5-sys · 1% of equity each month · sell-winner · no name cap · no ADV lid",
        ),
        (
            frozen,
            "5-sys · risk frozen at $2,500 every fill · sell-winner · no name cap (sibling)",
        ),
        (
            cand,
            "5-sys · risk = min(1% BOM, $50k) · shares ≤ 1% ADV20 · sell-winner · no name cap",
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
                f"{led.n_rotate} / {led.n_skip_bp}",
                f"{led.n_risk_50k_bound} / {led.n_risk_1pct_bound} / {led.n_adv_clipped}",
                f"{led.n_adv_missing} / {led.n_adv_last_known}",
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
            binds,
            advs,
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
            f"<td>{html_mod.escape(str(binds))}</td>"
            f"<td>{html_mod.escape(str(advs))}</td>"
            "</tr>"
        )
    last = (
        '<tr class="total-row"><th>As-of / last</th><td class="small">Pinned candidate</td>'
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
        f"<td>{cand['led'].n_rotate} / {cand['led'].n_skip_bp}</td>"
        f"<td>{cand['led'].n_risk_50k_bound} / {cand['led'].n_risk_1pct_bound} / {cand['led'].n_adv_clipped}</td>"
        f"<td>{cand['led'].n_adv_missing} / {cand['led'].n_adv_last_known}</td></tr>"
    )
    return (
        '<p class="small">Click column headers to sort. Total row pinned. '
        "1% uncapped is the $5.60T control; frozen $2,500 is the sibling size "
        "recipe; min(1%, $50k) + 1% ADV20 is the one knob pair. No 10% name cap "
        "this page.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}{last}</tbody></table></div>"
    )


def _year_table(
    ctrl: dict[str, Any],
    frozen: dict[str, Any],
    cand: dict[str, Any],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
) -> str:
    head = f._sortable_head(
        [
            ("Year-end", "num"),
            ("1% uncapped 5-sys SW", "num"),
            ("Frozen $2,500", "num"),
            ("min(1%, $50k)+ADV", "num"),
            ("SPY total return", "num"),
            ("1% Max DD%", "num"),
            ("Frozen Max DD%", "num"),
            ("Candidate Max DD%", "num"),
            ("SPY Max DD%", "num"),
            ("Note", "text"),
        ]
    )
    body = ""
    for y in range(2010, ASOF.year + 1):
        ur = next((x for x in ctrl["years"] if x["year"] == y), None)
        fr = next((x for x in frozen["years"] if x["year"] == y), None)
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
            f"<td>{format_money(fr['ending_equity']) if fr else '—'}</td>"
            f"<td>{format_money(cr['ending_equity']) if cr else '—'}</td>"
            f"<td>{format_money(sy['tr']) if sy else '—'}</td>"
            f"<td>{_fmt_pct(ur['max_dd_pct']) if ur else '—'}</td>"
            f"<td>{_fmt_pct(fr['max_dd_pct']) if fr else '—'}</td>"
            f"<td>{_fmt_pct(cr['max_dd_pct']) if cr else '—'}</td>"
            f"<td>{_fmt_pct(sdd.get('max_dd_pct'))}</td>"
            f"<td class=\"small\">{html_mod.escape(note)}</td>"
            "</tr>"
        )
    last = (
        '<tr class="total-row"><th>Total / last</th>'
        f"<td>{format_money(ctrl['led'].end_equity)}</td>"
        f"<td>{format_money(frozen['led'].end_equity)}</td>"
        f"<td>{format_money(cand['led'].end_equity)}</td>"
        f"<td>{format_money(spy['tr_end'])}</td>"
        f"<td>{_fmt_pct(ctrl['led'].max_dd_pct)}</td>"
        f"<td>{_fmt_pct(frozen['led'].max_dd_pct)}</td>"
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
    frozen: dict[str, Any],
    cand: dict[str, Any],
    spy_dd: dict[str, Any],
) -> str:
    head = f._sortable_head(
        [
            ("Month", "month"),
            ("1% uncapped EOM", "num"),
            ("Frozen $2,500 EOM", "num"),
            ("min(1%, $50k)+ADV EOM", "num"),
            ("SPY TR EOM", "num"),
            ("1% month Max DD%", "num"),
            ("Frozen month Max DD%", "num"),
            ("Candidate month Max DD%", "num"),
            ("SPY month Max DD%", "num"),
        ]
    )
    keys = sorted(
        {(s.year, s.month) for s in ctrl["snaps"]}
        | {(s.year, s.month) for s in frozen["snaps"]}
        | {(s.year, s.month) for s in cand["snaps"]}
    )
    u_map = {(s.year, s.month): s for s in ctrl["snaps"]}
    f_map = {(s.year, s.month): s for s in frozen["snaps"]}
    c_map = {(s.year, s.month): s for s in cand["snaps"]}
    body = ""
    for key in keys:
        us, fs, cs = u_map.get(key), f_map.get(key), c_map.get(key)
        sm = spy_dd["months"].get(key, {})
        body += (
            "<tr>"
            f"<td>{key[0]}-{key[1]:02d}</td>"
            f"<td>{format_money(us.equity_end) if us else '—'}</td>"
            f"<td>{format_money(fs.equity_end) if fs else '—'}</td>"
            f"<td>{format_money(cs.equity_end) if cs else '—'}</td>"
            f"<td>{format_money(sm['tr']) if sm else '—'}</td>"
            f"<td>{_fmt_pct(us.max_dd_pct) if us else '—'}</td>"
            f"<td>{_fmt_pct(fs.max_dd_pct) if fs else '—'}</td>"
            f"<td>{_fmt_pct(cs.max_dd_pct) if cs else '—'}</td>"
            f"<td>{_fmt_pct(sm.get('max_dd_pct'))}</td>"
            "</tr>"
        )
    last = (
        '<tr class="total-row"><th>As-of / last</th>'
        f"<td>{format_money(ctrl['led'].end_equity)}</td>"
        f"<td>{format_money(frozen['led'].end_equity)}</td>"
        f"<td>{format_money(cand['led'].end_equity)}</td>"
        f"<td>{format_money(spy_dd['tr_end'])}</td>"
        f"<td>{_fmt_pct(ctrl['led'].max_dd_pct)}</td>"
        f"<td>{_fmt_pct(frozen['led'].max_dd_pct)}</td>"
        f"<td>{_fmt_pct(cand['led'].max_dd_pct)}</td>"
        f"<td>{_fmt_pct(spy_dd['full_dd'])}</td></tr>"
    )
    return (
        '<p class="small">Month-end Closed-only path. Click headers to sort. Total row pinned.</p>'
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}{last}</tbody></table></div>"
    )


def _bind_table(cand: dict[str, Any], extras: dict[str, Any]) -> str:
    led = cand["led"]
    head = f._sortable_head(
        [
            ("Binder", "text"),
            ("N fills / events", "num"),
            ("% of sized fills", "num"),
            ("What it means", "text"),
        ]
    )
    n = max(1, extras["n_fills"])
    rows = [
        (
            "1% of BOM equity",
            extras["n_risk_1pct"],
            extras["pct_1pct"],
            "Month-start 1% was ≤ $50k, so the percent (not the dollar lid) set risk.",
        ),
        (
            "$50k risk ceiling",
            extras["n_risk_50k"],
            extras["pct_50k"],
            f"Month-start equity was above $5M so risk sat at $50k "
            f"({extras['n_months_50k']} months at the lid).",
        ),
        (
            "1% of ADV20 (share volume)",
            extras["n_adv_clip"],
            extras["pct_adv"],
            f"{ADV_WINDOW}-session mean of on-disk daily Volume; clipped shares after risk size.",
        ),
        (
            "ADV missing (skipped)",
            extras["n_adv_miss"],
            100.0 * extras["n_adv_miss"] / n,
            "No full 20-session Volume window on disk — fill skipped, not last-known invented.",
        ),
        (
            "ADV last-known (used)",
            extras["n_adv_last"],
            100.0 * extras["n_adv_last"] / n,
            "Used the most recent ADV20 bar before the fill date (holiday / missing session).",
        ),
    ]
    body = ""
    for name, cnt, pct, note in rows:
        body += (
            "<tr>"
            f"<td>{html_mod.escape(name)}</td>"
            f"<td>{int(cnt):,}</td>"
            f"<td>{pct:.2f}%</td>"
            f"<td class=\"small\">{html_mod.escape(note)}</td>"
            "</tr>"
        )
    last = (
        '<tr class="total-row"><th>Sized fills</th>'
        f"<td>{n:,}</td><td>100%</td>"
        f"<td class=\"small\">full {led.n_full} + scaled {led.n_scaled}; "
        f"ADV skip {led.n_skip_adv}; BP skip {led.n_skip_bp}</td></tr>"
    )
    return (
        '<p class="small">A fill can be both $50k-bound (risk $) and ADV-clipped '
        "(share count). Click headers to sort. Total row pinned. ADV window = "
        f"{ADV_WINDOW} trading sessions, simple mean of daily share Volume, last "
        "bar on or before the fill date.</p>"
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
        f"$50k-bound {led.n_risk_50k_bound}; 1%-bound {led.n_risk_1pct_bound}; "
        f"ADV-clipped {led.n_adv_clipped}; ADV-missing {led.n_adv_missing}; "
        f"ADV last-known {led.n_adv_last_known}; ADV-skip {led.n_skip_adv}; "
        f"months at $50k lid {led.n_months_50k}; "
        f"peak book ${led.peak_reserved:,.2f}; peak name ${led.peak_name_notional:,.2f} "
        f"({led.peak_name_symbol or '—'}, {led.peak_name_frac:.1%} of equity at peak); "
        f"identity {led.identity_err}; "
        f"FULL N={st.get('n')} WR={st.get('win_pct')} Avg%={st.get('avg_pnl_pct')} "
        f"PF={st.get('pf')}; "
        f"IS N={iso.get('n')} WR={iso.get('win_pct')} Avg%={iso.get('avg_pnl_pct')}; "
        f"OOS N={oos.get('n')} WR={oos.get('win_pct')} Avg%={oos.get('avg_pnl_pct')} (report-only)."
    )


def _compare_sections(
    ctrl: dict[str, Any],
    frozen: dict[str, Any],
    cand: dict[str, Any],
    verdict: str,
) -> str:
    out = ""
    col_map = {"IS": "stats_is", "OOS": "stats_oos", "FULL": "stats_full"}
    for sl, note in (
        (
            "IS",
            "In-Sample — entry before 2024-01-01. Path is continuous; "
            "do not retune $50k or 1% ADV on OOS.",
        ),
        (
            "OOS",
            "Out-of-Sample — report-only. Do not pick $50k or 1% ADV from this slice.",
        ),
        ("FULL", verdict),
    ):
        cols = [
            ("1% uncapped 5-sys SW", ctrl[col_map[sl]]),
            ("Frozen $2,500", frozen[col_map[sl]]),
            ("min(1%, $50k)+ADV", cand[col_map[sl]]),
        ]
        out += f"""
<section>
<h2>Canonical compare · {sl}</h2>
<p class="small">{html_mod.escape(note)} Sheet / Total PnL $ omitted. Click headers to sort.</p>
<div class="table-wrap">{f._canonical_table(cols)}</div>
</section>"""
    return out


def build_monthly(
    *,
    ctrl: dict[str, Any],
    frozen: dict[str, Any],
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
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>5-sys sell-winner + min(1%, $50k) + 1% ADV — {STAMP}</title>
<style>{f._css()}</style></head><body>
<h1>Monthly Backtest Report — {ASOF.year} · min(1% BOM, $50k) + 1% ADV20</h1>
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
{_headline_box(tag, extras)}
<div class="hold"><strong>{html_mod.escape(verdict)}</strong></div>
<div class="warn">
<strong>2010–2012 first.</strong> Later-year paper dollars can still be capacity
fiction if tight stops plus sell-winner plus 2× keep recycling. SPY 2010 / 2011 / 2012:
{format_money(spy['years'].get(2010, {}).get('tr', 0))} /
{format_money(spy['years'].get(2011, {}).get('tr', 0))} /
{format_money(spy_dd['eq_2012'])}.
1% uncapped: 2010 {format_money(ctrl['led'].eq_2010)} · 2011 {format_money(ctrl['led'].eq_2011)} · 2012 {format_money(ctrl['led'].eq_2012)}.
Frozen $2,500: 2010 {format_money(frozen['led'].eq_2010)} · 2011 {format_money(frozen['led'].eq_2011)} · 2012 {format_money(frozen['led'].eq_2012)}.
Candidate: 2010 {format_money(cand['led'].eq_2010)} · 2011 {format_money(cand['led'].eq_2011)} · 2012 {format_money(cand['led'].eq_2012)}.
10% name cap + declining 2% at billions is the next yes/no only — not run.
</div>
<section>
<h2>Books at a glance</h2>
{_lead_table(ctrl, frozen, cand, spy, spy_dd)}
</section>
<section>
<h2>Who bound — $50k vs 1% vs ADV</h2>
{_bind_table(cand, extras)}
</section>
<section>
<h2>Year-end equity and Max DD%</h2>
{_year_table(ctrl, frozen, cand, spy, spy_dd)}
</section>
<section>
<h2>Monthly path</h2>
{_month_path_table(ctrl, frozen, cand, spy_dd)}
</section>
<section>
<h2>Ledger — 1% uncapped 5-sys sell-winner</h2>
<p class="small">Control identity from the matrix / frozen uncapped row. Click headers to sort.</p>
{f._ledger_table(ctrl['snaps'])}
</section>
<section>
<h2>Ledger — frozen $2,500 risk</h2>
<p class="small">Sibling size recipe. RSI slot ≈ $2,500 ÷ 0.0651. Click headers to sort.</p>
{f._ledger_table(frozen['snaps'], risk_col="Frozen risk $")}
</section>
<section>
<h2>Ledger — min(1%, $50k) + 1% ADV20</h2>
<p class="small">One knob pair. Risk column is min(1% of BOM, $50k). ADV clip after risk size, then leftover buying power. Click headers to sort.</p>
{f._ledger_table(cand['snaps'], risk_col="min(1%, $50k)", bind_cols=True)}
</section>
{_compare_sections(ctrl, frozen, cand, verdict)}
<section>
<h2>Max drawdown definition</h2>
<p>{html_mod.escape(DD_DEF)}</p>
</section>
<section>
<h2>Data sources</h2>
<ul class="sources">{sources_html}</ul>
<p class="small">Compare: <a href="compare.html">compare.html</a>.
Sibling frozen $2,500: <a href="../risk2500_frozen_20260917/compare.html">risk2500_frozen_20260917</a>.
Acronyms first use: StockBee (SB); Relative Strength Index (RSI);
Volume Zone (VZ); Magic Touch (MTS); Rocket Launcher (RL);
Indicators (IND); In-Sample (IS); Out-of-Sample (OOS); buying power (BP);
beginning-of-month (BOM); Average Daily Volume (ADV);
S&amp;P 500 tracker (SPY); year-end (YE);
NVIDIA (NVDA); Meta Platforms (META).</p>
</section>
{f.r.monthly._SORTABLE_TABLE_SCRIPT}
</body></html>"""


def build_compare(
    *,
    ctrl: dict[str, Any],
    frozen: dict[str, Any],
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
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Compare — min(1%, $50k)+ADV vs frozen $2,500 vs 1% vs SPY — {STAMP}</title>
<style>{f._css()}</style></head><body>
<h1>Compare — min(1% BOM, $50k) + 1% ADV20 vs frozen $2,500 vs 1% uncapped vs SPY</h1>
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
{_headline_box(tag, extras)}
<div class="hold"><strong>{html_mod.escape(verdict)}</strong></div>
<section>
<h2>Books at a glance</h2>
{_lead_table(ctrl, frozen, cand, spy, spy_dd)}
</section>
<section>
<h2>Who bound — $50k vs 1% vs ADV</h2>
{_bind_table(cand, extras)}
</section>
<section>
<h2>Year-end equity and Max DD%</h2>
{_year_table(ctrl, frozen, cand, spy, spy_dd)}
</section>
{_compare_sections(ctrl, frozen, cand, verdict)}
<section>
<h2>Max drawdown definition</h2>
<p>{html_mod.escape(DD_DEF)}</p>
</section>
<section>
<h2>Data sources</h2>
<ul class="sources">{sources_html}</ul>
<p class="small">Monthly: <a href="monthly.html">monthly.html</a>.
10% name cap + declining 2% at billions not run — next yes/no only.</p>
</section>
{f.r.monthly._SORTABLE_TABLE_SCRIPT}
</body></html>"""


def write_baseline(
    *,
    ctrl: dict[str, Any],
    frozen: dict[str, Any],
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
        "Indicators (IND) is the old live sleeve (~−$40k, 35 lots, go-live 2026); it is not DailyRun-wired; all books exclude it.",
        "",
        "## Selection",
        "",
        "- One stamp, one knob pair: **risk_dollar = min(0.01 × BOM Closed-only equity, $50,000)** "
        "AND **shares ≤ 1% of ADV20** (20-session mean of on-disk daily share Volume).",
        "- Controls: (1) `risk2500_frozen_20260917` frozen $2,500 (re-run); "
        "(2) 5-sys 1% sell-winner uncapped (re-run; published as-of $5.60T).",
        "- **No 10% per-name cap and no declining 2% at billions this stamp.** "
        "Those are the next yes/no only. $50k binds mega-caps before 10% of a $1B book.",
        "- 5-sys: StockBee (SB), Relative Strength Index (RSI), Volume Zone (VZ), Magic Touch (MTS), Rocket Launcher (RL). IND out.",
        "- Start $250,000; one wallet; $7,500 cash on the 1st; 10.5% actual/365 on debit; open notional ≤ 2× equity.",
        f"- RSI: invested = risk_dollar / 0.06509607 (In-Sample avg-loss freeze). At the $50k lid ≈ ${RSI_SLOT_50K:,.2f} before ADV / BP. Do not retune OOS.",
        "- Others: shares = risk_dollar / (entry − stop), then ADV clip, then leftover buying power.",
        f"- ADV window: **{ADV_WINDOW} trading sessions**, simple mean of daily share Volume, last bar on or before fill date. "
        "Last-known if that session is missing. Skip if no full 20-bar window exists.",
        "- When a new signal cannot fit even scaled: sell the most profitable open (last close vs entry), then fill. Same sell-winner freeze.",
        f"- Decision: **{tag}** — {verdict}",
        "",
        "## Frozen knobs",
        "",
        f"- Account seed: **${ACCOUNT:,.0f}**",
        f"- Leverage cap: **{LEVERAGE:.0f}×** Closed-only equity",
        f"- Margin rate: **{MARGIN_RATE:.1%}** actual/365 daily compound",
        f"- Withdrawal: **${WITHDRAW:,.0f}** on month-start after 2010-01-01",
        "- Room rule: **sell winner** when buying power < $1",
        f"- **One change pair:** monthly risk = **min(1% of BOM, ${RISK_CAP:,.0f})**; "
        f"then shares = min(risk-sized shares, {ADV_FRAC:.0%} × ADV{ADV_WINDOW}).",
        "- Name cap: **off**. 10% + declining 2% not run.",
        "- In-Sample (IS) = `entry_date < 2024-01-01`. OOS report-only. Do not retune $50k or 1% ADV on OOS.",
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
        _book_bullet("5-sys sell-winner + frozen $2,500 (sibling)", frozen),
        _book_bullet("5-sys sell-winner + min(1%, $50k) + 1% ADV20 (candidate)", cand),
        "",
        "## Headline vs SPY",
        "",
        f"- Year-end 2012: candidate **${extras['ye2012']:,.2f}** vs SPY **${extras['spy_2012']:,.2f}** ({_vs_spy(extras['ye2012'], extras['spy_2012'])}).",
        f"- As-of {ASOF.isoformat()}: candidate **${extras['asof']:,.2f}** vs SPY **${extras['spy_asof']:,.2f}** ({_vs_spy(extras['asof'], extras['spy_asof'])}).",
        f"- Frozen $2,500 YE2012 **${extras['frozen_2012']:,.2f}** / as-of **${extras['frozen_asof']:,.2f}** "
        f"(published sibling {format_money(PUB_FROZEN['eq_2012'])} / {format_money(PUB_FROZEN['end'])}).",
        f"- $5.60T died? **{'YES' if extras['trillion_died'] else 'NO'}** "
        f"(1% uncapped as-of ${ctrl['led'].end_equity:,.2f} / peak book ${extras['peak_book_u']:,.2f} → "
        f"candidate as-of ${extras['asof']:,.2f} / peak book ${extras['peak_book_c']:,.2f}).",
        f"- Who bound? **{extras['who_bound']}** — $50k {extras['n_risk_50k']:,} / 1% {extras['n_risk_1pct']:,} / ADV clip {extras['n_adv_clip']:,}.",
        "",
        "## Honesty",
        "",
        "- Judge quality and realism, not “did we still print a huge number.”",
        "- If as-of is in a human range, still HOLD versus gold / DailyRun — research size view.",
        "- Do not pick $50k vs frozen $2,500 from this one page.",
        "- OOS is report-only. Do not retune $50k or 1% ADV on OOS.",
        "- 10% name cap + declining 2% at billions is the next yes/no only. Not run.",
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

**Product owner (PO)–aligned process:** one knob pair, frozen everything else. See `docs/HYPOTHESIS_TEST.md`.

| Field | Fill in |
|-------|---------|
| System / prefix | 5-sys {", ".join(FIVE)} (Indicators / IND out) |
| Baseline stamp | Frozen sibling `risk2500_frozen_20260917` ($2,500 flat). Control identity `risk2500_sys_matrix_20260917` 5-sys 1% sell-winner. Wallet engine `risk2500_five_sys_20260917` |
| Universe | House DailyRun 5-sys. Indicators (IND) excluded |
| **Evidence** | Paul: run risk = min(1% of month-start equity, $50k) AND shares ≤ 1% of ADV. Same 5-sys, $7,500/mo, 10.5%, 2×. Score YE2012 + as-of vs SPY. 10% name / declining 2% at billions is a comment only — not this stamp |
| **Hypothesis** | Capping monthly risk at $50k and clipping shares to 1% of ADV20 kills the $5.60T paper ending while leaving 2010–2012 near the 1% path (the $50k lid does not bind until equity > $5M). $50k binds mega-caps before a 10% name lid on a $1B book |
| **Single knob** | One pair: risk_dollar = min(1% BOM, $50,000) AND shares ≤ 1% × ADV20. Control A = 1% uncapped. Control B = frozen $2,500. Name cap off |
| Frozen settings | $250k start. $7,500 on the 1st. 10.5% actual/365. Open ≤ 2×. RSI 6.51% IS freeze. Sell winner when BP empty. Name cap off. 10% + 2% step-down not run |
| Alternatives | Uncapped 5-sys 1% sell-winner. Frozen $2,500 sibling. SPY $250k total return. 10% name / declining 2% = next yes/no only |
| Candidate stamps | `{STAMP}` monthly.html / compare.html |
| Metrics | YE2012 vs SPY; as-of vs SPY; Max DD%; peak single-name / peak book; $50k vs ADV vs 1% bind counts; 2010/2011/2012; canonical IS/OOS (report-only) |
| **Trade-diff HTML** | N/A — size / wallet overlay (not an entry A/B) |
| ToS before path | N/A |
| ToS after path | N/A |
| **Decision** | {tag} — {verdict} |
| Reviewer | AI job {STAMP} |
| PO sign-off | no |
| Reconcile freeze / re-baseline done | no |
| DailyRun | not wired |

## Decision checklist

- [x] Evidence was the PO ask (min(1%, $50k) + 1% ADV; no 10% name cap this stamp; YE2012 + as-of vs SPY)
- [x] One knob pair (not shopped as two separate stamps). 10% + 2% step-down not run
- [x] Same Closed pins as the sibling $2,500 / matrix / namecap stamps
- [x] Out-of-Sample (OOS) report-only; no RSI retune; no $50k / 1% ADV retune
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
        f"[size] risk=min(1% BOM, ${RISK_CAP:.0f}) ADV={ADV_FRAC:.0%}×ADV{ADV_WINDOW} "
        f"RSI slot at lid~${RSI_SLOT_50K:.2f} "
        f"({RISK_CAP:.0f} / {f.c.RSI_AVG_LOSS_FRAC:.8f})",
        flush=True,
    )

    static = f.load_static(FIVE)
    n_sym = len({t.symbol for t in static})
    print(f"[adv] warming ADV{ADV_WINDOW} cache for {n_sym} symbols", flush=True)
    for i, sym in enumerate(sorted({t.symbol for t in static}), 1):
        f._adv20_rows(sym)
        if i % 100 == 0 or i == n_sym:
            print(f"  ADV cached {i}/{n_sym}", flush=True)
    sources = [
        f"overlays: {f.PREV_DIR.name} (RSI = RSI_overlay_avgloss.csv IS 6.51% freeze)",
        f"5-sys: {', '.join(FIVE)} — Indicators (IND) out",
        f"SPY: {f.SPY_PATH.as_posix()} Adj Close total return + Close price-only",
        "wallet: tools/risk2500_five_sys_20260917.py run_wallet",
        "control identity: risk2500_sys_matrix_20260917 5-sys 1% sell-winner "
        "($250k, $7,500, 10.5%, 2×, sell winner)",
        "sibling: risk2500_frozen_20260917 frozen $2,500 (re-run for path)",
        "one knob pair: max_risk_dollar=50000 AND adv_frac=0.01 (ADV20 share volume); name cap off",
        f"ADV window: {ADV_WINDOW} sessions, simple mean of on-disk daily Volume; "
        "last bar ≤ fill date; last-known if that session missing; skip if no 20-bar window",
        "10% name cap + declining 2% at billions not run — next yes/no only",
        f"published frozen YE2012 ${PUB_FROZEN['eq_2012']:,.2f} / as-of ${PUB_FROZEN['end']:,.2f} "
        f"(SPY ${PUB_SPY_2012:,.2f} / ${PUB_SPY_ASOF:,.2f})",
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
    ctrl["read"] = "Matrix / frozen control. Risk = 1% of BOM equity."

    frozen = f._run_arm(
        static,
        rank=FIVE_RANK,
        rotate="winner",
        withdraw=True,
        label="5-sys · frozen $2,500 sell winner (uncapped name)",
        risk_frac=R_ONE,
        name_cap_frac=None,
        fixed_risk_dollar=RISK_FROZEN,
    )
    frozen["short"] = frozen["label"]
    frozen["read"] = "Sibling size recipe from risk2500_frozen_20260917."

    cand = f._run_arm(
        static,
        rank=FIVE_RANK,
        rotate="winner",
        withdraw=True,
        label="5-sys · min(1%, $50k) + 1% ADV20 sell winner",
        risk_frac=R_ONE,
        name_cap_frac=None,
        max_risk_dollar=RISK_CAP,
        adv_frac=ADV_FRAC,
    )
    cand["short"] = cand["label"]
    cand["read"] = "One knob pair. Research only."

    tag, verdict, extras = _verdict(ctrl, frozen, cand, spy, spy_dd)
    print(f"[verdict] {tag} {verdict}", flush=True)

    f.r.write_overlay_csv(ctrl["trades"], OUT_DIR / "ALL_overlay_5sys_1pct_sw_uncapped.csv")
    f.r.write_overlay_csv(frozen["trades"], OUT_DIR / "ALL_overlay_5sys_frozen2500.csv")
    f.r.write_overlay_csv(cand["trades"], OUT_DIR / "ALL_overlay_5sys_1pct_50k_adv.csv")

    now = datetime.now(tz=ET)
    monthly_html = build_monthly(
        ctrl=ctrl,
        frozen=frozen,
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
        frozen=frozen,
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
        frozen=frozen,
        cand=cand,
        spy=spy,
        spy_dd=spy_dd,
        tag=tag,
        verdict=verdict,
        extras=extras,
        sources=sources,
    )
    write_hypothesis(tag, verdict)

    def _led_pack(led: Any) -> dict[str, Any]:
        return {
            "end": led.end_equity,
            "eq_2010": led.eq_2010,
            "eq_2011": led.eq_2011,
            "eq_2012": led.eq_2012,
            "max_dd_pct": led.max_dd_pct,
            "peak_reserved": led.peak_reserved,
            "peak_name": led.peak_name_notional,
            "peak_name_symbol": led.peak_name_symbol,
            "n_rotate": led.n_rotate,
            "n_risk_50k_bound": led.n_risk_50k_bound,
            "n_risk_1pct_bound": led.n_risk_1pct_bound,
            "n_adv_clipped": led.n_adv_clipped,
            "n_adv_missing": led.n_adv_missing,
            "n_adv_last_known": led.n_adv_last_known,
            "n_skip_adv": led.n_skip_adv,
            "n_months_50k": led.n_months_50k,
        }

    summary = {
        "tag": tag,
        "verdict": verdict,
        "spy_tr_end": spy["tr_end"],
        "spy_2012": spy_dd["eq_2012"],
        "spy_max_dd_pct": spy_dd["full_dd"],
        "rsi_slot_50k": RSI_SLOT_50K,
        "adv_window": ADV_WINDOW,
        "uncapped_1pct": _led_pack(ctrl["led"]),
        "frozen2500": _led_pack(frozen["led"]),
        "candidate_50k_adv": _led_pack(cand["led"]),
        "published_frozen_asof": PUB_FROZEN["end"],
        "published_uncapped_asof": PUB_UNCAPPED_ASOF,
        "extras": extras,
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"wrote {OUT_DIR / 'monthly.html'}", flush=True)
    print(f"wrote {OUT_DIR / 'compare.html'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
