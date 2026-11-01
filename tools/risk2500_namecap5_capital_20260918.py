#!/usr/bin/env python3
"""5% name-cap capital A/B — same recipe that died at $250k (research only).

Stamp: drive/paul_experiments/risk2500_namecap5_capital_20260918/

Parent 5% DISMISS arm: risk2500_namecap25_20260917 namecap05
($250k start, YE2012 $171k vs SPY $334k, as-of $5,892, Max DD 100%).

One knob: start equity. Same 5% per-name notional, 1% of BOM equity risk
(no $2,500 / $50k ceiling, no 1% ADV, not the later 17.5% live-style lids).
$7,500/mo, 10.5%, 2×, sell-winner, RSI IS 6.51% freeze.

Not gold. Not DailyRun. Do not retune 5% on OOS.
"""
from __future__ import annotations

import html as html_mod
import importlib.util
import json
import math
import sys
from datetime import date, datetime
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

STAMP = "risk2500_namecap5_capital_20260918"
OUT_DIR = REPO / "drive" / "paul_experiments" / STAMP
PARENT = "risk2500_namecap25_20260917"
ACCOUNT = f.ACCOUNT
ASOF = f.ASOF
ET = f.ET
WITHDRAW = f.WITHDRAW
MARGIN_RATE = f.MARGIN_RATE
LEVERAGE = f.LEVERAGE
NAME_CAP = 0.05
R_ONE = 0.01
FIVE = f.FIVE
FIVE_RANK = f.FIVE_RANK
DD_DEF = m.DD_DEF
YEARS = (ASOF - date(2010, 1, 1)).days / 365.25
PUB_WIRE_FULL = 1_500_000.0

# Published 5% DISMISS arm (parent stamp). Reuse as the $250k pin; re-run to
# confirm identity on this engine.
PUB_250 = {
    "end": 5_891.7267023412805,
    "eq_2010": 224_224.88537730355,
    "eq_2011": 204_001.385545685,
    "eq_2012": 171_072.9929953589,
    "max_dd_pct": 99.99799088260971,
    "withdrawals": 562_500.0,
    "peak_reserved": 293_706.74759434996,
    "peak_name": 12_962.803567798348,
    "peak_name_symbol": "AKR",
}

ORIGINAL_REQUEST = (
    "would it matter if we had more capital but kept it to 5%? what if we had "
    "333k? 500k? 1M?"
)
PLAIN_ENGLISH = (
    "Same five sleeves that already died at a 5% per-name lid — StockBee (SB), "
    "Relative Strength Index (RSI), Volume Zone (VZ), Magic Touch (MTS), Rocket "
    "Launcher (RL). Indicators (IND) is out. One wallet. Pull $7,500 cash on the "
    "1st. Pay 10.5% a year on whatever you borrowed. Open stock cost can be at "
    "most twice the account. Each month risk 1% of whatever the account is worth "
    "after closed trades: RSI dollars in = that 1% ÷ 0.0651 (In-Sample "
    "average-loser freeze; do not retune after 2024); other systems shares = "
    "1% ÷ (entry − stop). When a new signal still cannot fit, sell the most "
    "profitable open name, then take the new one. After that 1% size and before "
    "the fill, no single ticker may hold more than 5% of whatever the account is "
    "worth right then. We did not switch to the later live-style lids (17.5% "
    "name, min(1% beginning-of-month, $50k) risk, 1% of 20-day average daily "
    "volume). The only knob: start with $250,000 (the published DISMISS arm), "
    "or $333,000, or $500,000, or $1,000,000. S&P 500 tracker (SPY) scales "
    "linearly with the start ($250k → about $334k at year-end 2012). Question: "
    "does a bigger pile just delay the $7,500 bleed, or does 5% become viable? "
    "Not gold. Not DailyRun."
)

ARM_SPEC: list[tuple[str, float, str]] = [
    ("s250", 250_000.0, "5% name cap · start $250k"),
    ("s333", 333_000.0, "5% name cap · start $333k"),
    ("s500", 500_000.0, "5% name cap · start $500k"),
    ("s1m", 1_000_000.0, "5% name cap · start $1M"),
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


def _m(v: Any) -> str:
    if v is None:
        return "—"
    return format_money(float(v))


def _cagr(end: float, start: float, years: float = YEARS) -> Optional[float]:
    if start <= 0 or years <= 0:
        return None
    if end <= 0:
        return -1.0
    return (end / start) ** (1.0 / years) - 1.0


def _fmt_cagr(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"{100.0 * v:.2f}%"


def _scale(spy250: float, start: float) -> float:
    return float(spy250) * (start / ACCOUNT)


def _died(pack: dict[str, Any]) -> bool:
    return bool(
        pack["max_dd_pct"] >= 90.0
        or pack["end"] < pack["start"] * 0.10
        or pack["end"] < 10_000.0
    )


def _tag_one(pack: dict[str, Any]) -> str:
    if _died(pack):
        return "DISMISS"
    # Survived the $7,500 wire. If as-of is still huge, 1% of a growing pile
    # compounded — HOLD (do not adopt), same as the parent 10% arm. Losing
    # year-end 2012 to own SPY does not flip this to DISMISS; it means 5%
    # is still not a live lid.
    if pack["end"] >= 10_000_000.0:
        return "HOLD"
    if pack["eq_2012"] < pack["spy_2012"] * 0.90 or pack["end"] < pack["spy_asof"]:
        return "DISMISS"
    return "HOLD"


def _led_pack(arm: dict[str, Any], start: float, spy: dict[str, Any]) -> dict[str, Any]:
    led = arm["led"]
    st = arm["stats_full"]
    spy_asof = _scale(spy["tr_end"], start)
    spy_2010 = _scale(float(spy["years"].get(2010, {}).get("tr", 0.0)), start)
    spy_2011 = _scale(float(spy["years"].get(2011, {}).get("tr", 0.0)), start)
    spy_2012 = _scale(float(spy["years"].get(2012, {}).get("tr", 0.0)), start)
    pack = {
        "start": float(start),
        "end": float(led.end_equity),
        "eq_2010": float(led.eq_2010),
        "eq_2011": float(led.eq_2011),
        "eq_2012": float(led.eq_2012),
        "max_dd_pct": float(led.max_dd_pct),
        "max_dd_peak": float(led.max_dd_peak),
        "max_dd_trough": float(led.max_dd_trough),
        "peak_reserved": float(led.peak_reserved),
        "peak_name": float(led.peak_name_notional),
        "peak_name_symbol": led.peak_name_symbol or "—",
        "peak_name_frac": float(led.peak_name_frac),
        "n_rotate": int(led.n_rotate),
        "n_name_capped": int(led.n_name_capped),
        "n_skip_name": int(led.n_skip_name),
        "n_skip_bp": int(led.n_skip_bp),
        "n_wd": int(led.n_wd),
        "n_wd_skip": int(led.n_wd_skip),
        "interest": float(led.interest),
        "withdrawals": float(led.withdrawals),
        "identity_err": float(led.identity_err),
        "wr": _num(st, "win_pct"),
        "avg": _num(st, "avg_pnl_pct"),
        "pf": _num(st, "pf"),
        "ann_ror": _num(st, "ann_ror"),
        "ann_ror_250k": _num(st, "ann_ror_250k"),
        "calmar": _num(st, "calmar"),
        "sharpe": _num(st, "sharpe"),
        "spy_asof": spy_asof,
        "spy_2010": spy_2010,
        "spy_2011": spy_2011,
        "spy_2012": spy_2012,
        "n_closed": int(st.get("n") or 0),
    }
    pack["wallet_cagr"] = _cagr(pack["end"], pack["start"])
    pack["died"] = _died(pack)
    pack["tag"] = _tag_one(pack)
    pack["wires_full"] = pack["withdrawals"] + 1e-9 >= PUB_WIRE_FULL
    return pack


def _verdict(packs: dict[str, dict[str, Any]]) -> tuple[str, str, dict[str, Any]]:
    extras = {k: dict(v) for k, v in packs.items()}
    tags = [packs[k]["tag"] for k, _s, _l in ARM_SPEC]
    dies = [packs[k]["died"] for k, _s, _l in ARM_SPEC]
    n_die = sum(1 for d in dies if d)
    rows = []
    for key, start, _lab in ARM_SPEC:
        p = packs[key]
        rows.append(
            f"{format_money(start)} year-end 2012 {format_money(p['eq_2012'])} vs "
            f"SPY {format_money(p['spy_2012'])} ({_vs_spy(p['eq_2012'], p['spy_2012'])}); "
            f"as-of {format_money(p['end'])} vs SPY {format_money(p['spy_asof'])} "
            f"({_vs_spy(p['end'], p['spy_asof'])}); Max DD {_fmt_pct(p['max_dd_pct'])}; "
            f"dies {'YES' if p['died'] else 'NO'}; {p['tag']}; "
            f"wallet CAGR {_fmt_cagr(p['wallet_cagr'])}; book Ann ROR "
            f"{_fmt_pct(p['ann_ror'])}; wires {format_money(p['withdrawals'])} "
            f"of {format_money(PUB_WIRE_FULL)}."
        )
    p250 = packs["s250"]
    path = (
        "2010–2012 path — "
        + "; ".join(
            f"{format_money(start)} {format_money(packs[k]['eq_2010'])} / "
            f"{format_money(packs[k]['eq_2011'])} / {format_money(packs[k]['eq_2012'])}"
            for k, start, _l in ARM_SPEC
        )
        + f"; SPY $250k {format_money(p250['spy_2010'])} / "
        f"{format_money(p250['spy_2011'])} / {format_money(p250['spy_2012'])} "
        "(other starts’ SPY scale linearly)."
    )
    if n_die == 4:
        tag = "DISMISS"
        prose = (
            "DISMISS 5% at every start in this table. More starting cash helps the "
            "$7,500 wire math (a bigger pile can pay more months before the lid "
            "is too small to outrun the bleed) but 5% is still not viable — the "
            "account still dies or trails its own S&P 500 tracker (SPY). "
            + " ".join(rows)
            + f" {path} Do not retune 5% on Out-of-Sample. Not gold. Not DailyRun."
        )
        return tag, prose, extras
    if n_die > 0 and any(t == "HOLD" for t in tags):
        tag = "HOLD"
        dismiss_starts = [
            format_money(start)
            for k, start, _l in ARM_SPEC
            if packs[k]["died"]
        ]
        hold_starts = [
            format_money(start)
            for k, start, _l in ARM_SPEC
            if packs[k]["tag"] == "HOLD"
        ]
        prose = (
            f"HOLD as a research size view — not a live lid. More capital does "
            f"more than delay the $7,500 bleed: {', '.join(hold_starts)} paid "
            f"every wire and the account did not die, then 1% of a growing pile "
            f"printed billions (same capacity fiction as the parent 10% arm). "
            f"DISMISS 5% at {', '.join(dismiss_starts)} — that seed still died. "
            f"5% is still not viable as a Fidelity recipe and we do not promote "
            f"it. Wallet CAGR is the honest annualized rate of return (Ann ROR) "
            f"on the cash pile; book Ann ROR explodes once overlay dollars dwarf "
            f"the seed. "
            + " ".join(rows)
            + f" {path} Do not retune 5% on Out-of-Sample. Not gold. Not DailyRun."
        )
        return tag, prose, extras
    if all(t == "HOLD" for t in tags):
        tag = "HOLD"
        prose = (
            "HOLD — none of these starts died, so more capital changed the wire "
            "math, but 5% is still not gold and not a DailyRun lid (one in-sample "
            "freeze; later live-style lids were not used). "
            + " ".join(rows)
            + f" {path} Do not retune 5% on Out-of-Sample."
        )
        return tag, prose, extras
    tag = "DISMISS"
    prose = (
        "DISMISS 5% as a lid across this capital ladder. "
        + " ".join(rows)
        + f" {path} Do not retune 5% on Out-of-Sample. Not gold. Not DailyRun."
    )
    return tag, prose, extras


def _ask_block() -> str:
    return f"""
<div class="ask">
<h2>What you asked</h2>
<blockquote>{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN_ENGLISH)}</p>
</div>"""


def _headline_table(packs: dict[str, dict[str, Any]]) -> str:
    head = f._sortable_head(
        [
            ("Start $", "num"),
            ("YE2012", "num"),
            ("SPY YE2012 (scaled)", "num"),
            ("YE2012 vs SPY", "text"),
            ("As-of", "num"),
            ("SPY as-of (scaled)", "num"),
            ("As-of vs SPY", "text"),
            ("Max DD%", "num"),
            ("Dies?", "text"),
            ("5% tag", "text"),
            ("Wallet CAGR", "num"),
            ("Book Ann ROR %", "num"),
            ("Wires paid", "num"),
            ("Wires skipped (months)", "num"),
        ]
    )
    body = ""
    for key, start, _lab in ARM_SPEC:
        p = packs[key]
        died = "YES" if p["died"] else "NO"
        cls = "no" if p["tag"] == "DISMISS" else "holdtag"
        body += (
            "<tr>"
            f"<td>{format_money(start)}</td>"
            f"<td>{format_money(p['eq_2012'])}</td>"
            f"<td>{format_money(p['spy_2012'])}</td>"
            f"<td>{html_mod.escape(_vs_spy(p['eq_2012'], p['spy_2012']))}</td>"
            f"<td>{format_money(p['end'])}</td>"
            f"<td>{format_money(p['spy_asof'])}</td>"
            f"<td>{html_mod.escape(_vs_spy(p['end'], p['spy_asof']))}</td>"
            f"<td>{_fmt_pct(p['max_dd_pct'])}</td>"
            f"<td class=\"{cls}\"><strong>{died}</strong></td>"
            f"<td class=\"{cls}\"><strong>{html_mod.escape(p['tag'])}</strong></td>"
            f"<td>{_fmt_cagr(p['wallet_cagr'])}</td>"
            f"<td>{_fmt_pct(p['ann_ror'])}</td>"
            f"<td>{format_money(p['withdrawals'])}</td>"
            f"<td>{int(p['n_wd_skip'])}</td>"
            "</tr>"
        )
    last = packs["s1m"]
    last_row = (
        '<tr class="total-row"><th>Pinned ($1M 5%)</th>'
        f"<td>{format_money(last['eq_2012'])}</td>"
        f"<td>{format_money(last['spy_2012'])}</td>"
        f"<td>{html_mod.escape(_vs_spy(last['eq_2012'], last['spy_2012']))}</td>"
        f"<td>{format_money(last['end'])}</td>"
        f"<td>{format_money(last['spy_asof'])}</td>"
        f"<td>{html_mod.escape(_vs_spy(last['end'], last['spy_asof']))}</td>"
        f"<td>{_fmt_pct(last['max_dd_pct'])}</td>"
        f"<td>{'YES' if last['died'] else 'NO'}</td>"
        f"<td>{html_mod.escape(last['tag'])}</td>"
        f"<td>{_fmt_cagr(last['wallet_cagr'])}</td>"
        f"<td>{_fmt_pct(last['ann_ror'])}</td>"
        f"<td>{format_money(last['withdrawals'])}</td>"
        f"<td>{int(last['n_wd_skip'])}</td></tr>"
    )
    return (
        '<p class="small">Click column headers to sort. Total row pinned. '
        "SPY dollars scale linearly with start ($250k yardstick × start / $250,000). "
        "Wallet CAGR is (as-of ÷ start)^(1/years) − 1 from 2010-01-01. "
        "Book Ann ROR is the overlay closed-trade formula at that start’s cash seed. "
        "Dies = Max DD ≥ 90% or as-of &lt; 10% of start or as-of &lt; $10,000.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}{last_row}</tbody></table></div>"
    )


def _lead_table(
    books: dict[str, dict[str, Any]],
    packs: dict[str, dict[str, Any]],
) -> str:
    head = f._sortable_head(
        [
            ("Book", "text"),
            ("Start $", "num"),
            ("Ending equity", "num"),
            ("2010 end", "num"),
            ("2011 end", "num"),
            ("2012 end", "num"),
            ("Max DD%", "num"),
            ("vs own SPY as-of", "text"),
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
    body = ""
    for key, start, lab in ARM_SPEC:
        p = packs[key]
        body += (
            "<tr>"
            f"<td>{html_mod.escape(lab)}</td>"
            f"<td>{format_money(start)}</td>"
            f"<td>{_m(p['end'])}</td>"
            f"<td>{_m(p['eq_2010'])}</td>"
            f"<td>{_m(p['eq_2011'])}</td>"
            f"<td>{_m(p['eq_2012'])}</td>"
            f"<td>{_fmt_pct(p['max_dd_pct'])}</td>"
            f"<td>{html_mod.escape(_vs_spy(p['end'], p['spy_asof']))}</td>"
            f"<td>{_m(p['peak_reserved'])}</td>"
            f"<td>{_m(p['peak_name'])}</td>"
            f"<td>{html_mod.escape(p['peak_name_symbol'])}</td>"
            f"<td>{_fmt_pct(100.0 * p['peak_name_frac'])}</td>"
            f"<td>{_m(p['interest'])}</td>"
            f"<td>{_m(p['withdrawals'])}</td>"
            f"<td>{p['n_rotate']} / {p['n_skip_bp']} / {p['n_skip_name']}</td>"
            f"<td>{p['n_name_capped']}</td>"
            "</tr>"
        )
    last = packs["s1m"]
    last_row = (
        '<tr class="total-row"><th>As-of / last ($1M)</th>'
        f"<td>{format_money(1_000_000.0)}</td>"
        f"<td>{format_money(last['end'])}</td>"
        f"<td>{format_money(last['eq_2010'])}</td>"
        f"<td>{format_money(last['eq_2011'])}</td>"
        f"<td>{format_money(last['eq_2012'])}</td>"
        f"<td>{_fmt_pct(last['max_dd_pct'])}</td>"
        f"<td>{html_mod.escape(_vs_spy(last['end'], last['spy_asof']))}</td>"
        f"<td>{format_money(last['peak_reserved'])}</td>"
        f"<td>{format_money(last['peak_name'])}</td>"
        f"<td>{html_mod.escape(last['peak_name_symbol'])}</td>"
        f"<td>{_fmt_pct(100.0 * last['peak_name_frac'])}</td>"
        f"<td>{format_money(last['interest'])}</td>"
        f"<td>{format_money(last['withdrawals'])}</td>"
        f"<td>{last['n_rotate']} / {last['n_skip_bp']} / {last['n_skip_name']}</td>"
        f"<td>{last['n_name_capped']}</td></tr>"
    )
    return (
        '<p class="small">Click column headers to sort. Total row pinned. '
        "Same 5% recipe; only the start changes.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}{last_row}</tbody></table></div>"
    )


def _year_table(
    books: dict[str, dict[str, Any]],
    packs: dict[str, dict[str, Any]],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
) -> str:
    head = f._sortable_head(
        [("Year-end", "num")]
        + [(lab, "num") for _k, _s, lab in ARM_SPEC]
        + [("SPY $250k TR", "num")]
        + [(f"{lab} Max DD%", "num") for _k, _s, lab in ARM_SPEC]
        + [("SPY Max DD%", "num"), ("Note", "text")]
    )
    body = ""
    for y in range(2010, ASOF.year + 1):
        cells = f"<td>{y}</td>"
        for key, _s, _lab in ARM_SPEC:
            row = next((x for x in books[key]["years"] if x["year"] == y), None)
            cells += f"<td>{format_money(row['ending_equity']) if row else '—'}</td>"
        sy = spy["years"].get(y)
        cells += f"<td>{format_money(sy['tr']) if sy else '—'}</td>"
        for key, _s, _lab in ARM_SPEC:
            row = next((x for x in books[key]["years"] if x["year"] == y), None)
            cells += f"<td>{_fmt_pct(row['max_dd_pct']) if row else '—'}</td>"
        sdd = spy_dd["years"].get(y, {})
        note = f"through {ASOF.isoformat()}" if y == ASOF.year else ""
        if y == 2012:
            note = "year-end 2012 headline"
        cells += f"<td>{_fmt_pct(sdd.get('max_dd_pct'))}</td>"
        body += f"<tr>{cells}<td class=\"small\">{html_mod.escape(note)}</td></tr>"
    last = '<tr class="total-row"><th>Total / last</th>'
    for key, _s, _lab in ARM_SPEC:
        last += f"<td>{format_money(packs[key]['end'])}</td>"
    last += f"<td>{format_money(spy['tr_end'])}</td>"
    for key, _s, _lab in ARM_SPEC:
        last += f"<td>{_fmt_pct(packs[key]['max_dd_pct'])}</td>"
    last += f"<td>{_fmt_pct(spy_dd['full_dd'])}</td><td class=\"small\">Pinned as-of</td></tr>"
    return (
        '<p class="small">Closed-only year-end. SPY column is the $250k total-return '
        "yardstick; other starts’ SPY = that number × start / $250,000 (linear). "
        "Click headers to sort. Total row pinned. 2010–2012 is the honest path.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}{last}</tbody></table></div>"
    )


def _path_2010_2012(
    packs: dict[str, dict[str, Any]],
    spy: dict[str, Any],
) -> str:
    head = f._sortable_head(
        [
            ("Book", "text"),
            ("2010 end", "num"),
            ("2011 end", "num"),
            ("2012 end", "num"),
            ("Own SPY YE2012", "num"),
            ("vs own SPY YE2012", "text"),
        ]
    )
    rows = []
    for key, start, lab in ARM_SPEC:
        p = packs[key]
        rows.append(
            (
                lab,
                p["eq_2010"],
                p["eq_2011"],
                p["eq_2012"],
                p["spy_2012"],
                _vs_spy(p["eq_2012"], p["spy_2012"]),
            )
        )
        rows.append(
            (
                f"SPY start {format_money(start)}",
                _scale(float(spy["years"].get(2010, {}).get("tr", 0.0)), start),
                _scale(float(spy["years"].get(2011, {}).get("tr", 0.0)), start),
                p["spy_2012"],
                p["spy_2012"],
                "1.00× (yardstick)",
            )
        )
    body = ""
    for name, y0, y1, y2, spy12, vs in rows:
        body += (
            "<tr>"
            f"<td>{html_mod.escape(str(name))}</td>"
            f"<td>{_m(y0)}</td>"
            f"<td>{_m(y1)}</td>"
            f"<td>{_m(y2)}</td>"
            f"<td>{_m(spy12)}</td>"
            f"<td>{html_mod.escape(str(vs))}</td>"
            "</tr>"
        )
    last = packs["s1m"]
    last_row = (
        '<tr class="total-row"><th>Pinned ($1M 5%)</th>'
        f"<td>{format_money(last['eq_2010'])}</td>"
        f"<td>{format_money(last['eq_2011'])}</td>"
        f"<td>{format_money(last['eq_2012'])}</td>"
        f"<td>{format_money(last['spy_2012'])}</td>"
        f"<td>{html_mod.escape(_vs_spy(last['eq_2012'], last['spy_2012']))}</td></tr>"
    )
    return (
        '<p class="small">Honest early path before later-year capacity fiction. '
        "Each book vs its own linearly scaled SPY. Click headers to sort.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}{last_row}</tbody></table></div>"
    )


def _month_path_table(
    books: dict[str, dict[str, Any]],
    packs: dict[str, dict[str, Any]],
    spy_dd: dict[str, Any],
) -> str:
    keys = [k for k, _s, _l in ARM_SPEC]
    labs = {k: lab.replace("5% name cap · ", "") + " EOM" for k, _s, lab in ARM_SPEC}
    head = f._sortable_head(
        [("Month", "month")]
        + [(labs[k], "num") for k in keys]
        + [("SPY $250k TR EOM", "num")]
        + [(labs[k].replace("EOM", "month Max DD%"), "num") for k in keys]
        + [("SPY month Max DD%", "num")]
    )
    all_keys: set[tuple[int, int]] = set()
    maps: dict[str, dict[tuple[int, int], Any]] = {}
    for k in keys:
        maps[k] = {(s.year, s.month): s for s in books[k]["snaps"]}
        all_keys |= set(maps[k])
    body = ""
    for key in sorted(all_keys):
        cells = f"<td>{key[0]}-{key[1]:02d}</td>"
        for k in keys:
            s = maps[k].get(key)
            cells += f"<td>{format_money(s.equity_end) if s else '—'}</td>"
        sm = spy_dd["months"].get(key, {})
        cells += f"<td>{format_money(sm['tr']) if sm else '—'}</td>"
        for k in keys:
            s = maps[k].get(key)
            cells += f"<td>{_fmt_pct(s.max_dd_pct) if s else '—'}</td>"
        cells += f"<td>{_fmt_pct(sm.get('max_dd_pct'))}</td>"
        body += f"<tr>{cells}</tr>"
    last = '<tr class="total-row"><th>As-of / last</th>'
    for k in keys:
        last += f"<td>{format_money(packs[k]['end'])}</td>"
    last += f"<td>{format_money(spy_dd['tr_end'])}</td>"
    for k in keys:
        last += f"<td>{_fmt_pct(packs[k]['max_dd_pct'])}</td>"
    last += f"<td>{_fmt_pct(spy_dd['full_dd'])}</td></tr>"
    return (
        '<p class="small">Month-end Closed-only path. Click headers to sort. '
        "Total row pinned. Uncapped — no inner scroll box.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}{last}</tbody></table></div>"
    )


def _compare_sections(
    books: dict[str, dict[str, Any]],
    verdict: str,
) -> str:
    col_map = {"IS": "stats_is", "OOS": "stats_oos", "FULL": "stats_full"}
    notes = {
        "IS": "In-Sample — entry before 2024-01-01. Path is continuous; do not retune 5% on OOS.",
        "OOS": "Out-of-Sample — report-only. Do not pick a start or retune 5% from this slice.",
        "FULL": verdict,
    }
    html = ""
    for sl in ("IS", "OOS", "FULL"):
        cols = [(lab, books[key][col_map[sl]]) for key, _s, lab in ARM_SPEC]
        html += f"""
<section>
<h2>Canonical compare · {sl}</h2>
<p class="small">{html_mod.escape(notes[sl])} Sheet / Total PnL $ omitted. Click headers to sort. Δ vs $250k 5% (control = published DISMISS arm).</p>
<div class="table-wrap">{f._canonical_table(cols)}</div>
</section>"""
    return html


def _headline_box(packs: dict[str, dict[str, Any]], tag: str) -> str:
    cls = "yes" if tag == "KEEP" else ("no" if tag == "DISMISS" else "holdtag")
    cards = ""
    for key, start, lab in ARM_SPEC:
        p = packs[key]
        died = "YES — account died" if p["died"] else "NO — still standing"
        cards += f"""
    <div class="card card-shared">
      <h3>{html_mod.escape(lab)}</h3>
      <div class="metric">{format_money(p['eq_2012'])}</div>
      <div class="small">YE2012 vs SPY {format_money(p['spy_2012'])} ·
      {html_mod.escape(_vs_spy(p['eq_2012'], p['spy_2012']))}</div>
      <div class="small">As-of {format_money(p['end'])} vs SPY {format_money(p['spy_asof'])} ·
      {html_mod.escape(_vs_spy(p['end'], p['spy_asof']))}</div>
      <div class="small">Max DD {_fmt_pct(p['max_dd_pct'])} · dies <strong>{died}</strong></div>
      <div class="small">{html_mod.escape(p['tag'])} · wallet CAGR {_fmt_cagr(p['wallet_cagr'])} ·
      book Ann ROR {_fmt_pct(p['ann_ror'])}</div>
    </div>"""
    return f"""
<div class="lead">
  <h2>Headline — 5% name cap at four starts vs own SPY</h2>
  <p><strong class="{cls}">{html_mod.escape(tag)}</strong> · research only · not gold · not DailyRun</p>
  <div class="cards">{cards}
  </div>
</div>"""


def build_compare(
    *,
    books: dict[str, dict[str, Any]],
    packs: dict[str, dict[str, Any]],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
    tag: str,
    verdict: str,
    extras: dict[str, Any],
    sources: list[str],
    generated: datetime,
    pin_note: str,
) -> str:
    now = generated.astimezone(ET)
    gen_s = now.strftime("%Y-%m-%d %H:%M %Z")
    sources_html = "".join(f"<li>{html_mod.escape(s)}</li>" for s in sources)
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Compare — 5% name cap at $250k / $333k / $500k / $1M — {STAMP}</title>
<style>{f._css()}</style></head><body>
<h1>Compare — 5-sys 1% sell-winner · 5% name cap · start-capital A/B vs SPY</h1>
<p class="sub">
Stamp <code>{STAMP}</code>. Parent 5% DISMISS arm: <code>{PARENT}</code>.
Research only. <strong>Not gold. Not DailyRun.</strong>
Generated {html_mod.escape(gen_s)}. Click column headers to sort.
</p>
{_ask_block()}
<div class="warn"><strong>Freeze:</strong> 5% per-name notional after 1% beginning-of-month
(BOM) equity risk. No $2,500 / $50k risk ceiling. No 1% average daily volume (ADV) clip.
Not the later 17.5% live-style lids. $7,500 on the 1st. 10.5% actual/365. Open ≤ 2×.
Sell winner when buying power is empty. RSI In-Sample 6.51% freeze.
{html_mod.escape(pin_note)}</div>
{_headline_box(packs, tag)}
<div class="hold"><strong>{html_mod.escape(verdict)}</strong></div>
<section>
<h2>Four starts — YE2012 / as-of / Max DD / dies?</h2>
{_headline_table(packs)}
</section>
<section>
<h2>2010–2012 path vs own SPY</h2>
{_path_2010_2012(packs, spy)}
</section>
<section>
<h2>Four books at a glance</h2>
{_lead_table(books, packs)}
</section>
<section>
<h2>Year-end equity and Max DD%</h2>
{_year_table(books, packs, spy, spy_dd)}
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
Parent 5% page: <a href="../{PARENT}/compare.html">{PARENT}</a>.
Not gold. Not DailyRun.</p>
</section>
{f.r.monthly._SORTABLE_TABLE_SCRIPT}
</body></html>"""


def build_monthly(
    *,
    books: dict[str, dict[str, Any]],
    packs: dict[str, dict[str, Any]],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
    tag: str,
    verdict: str,
    extras: dict[str, Any],
    sources: list[str],
    generated: datetime,
    pin_note: str,
) -> str:
    now = generated.astimezone(ET)
    gen_s = now.strftime("%Y-%m-%d %H:%M %Z")
    sources_html = "".join(f"<li>{html_mod.escape(s)}</li>" for s in sources)
    ledgers = ""
    for key, start, lab in ARM_SPEC:
        ledgers += f"""
<section>
<h2>Ledger — {html_mod.escape(lab)}</h2>
<p class="small">Start {format_money(start)}. 5% name cap. 1% of BOM equity. Click headers to sort.</p>
{f._ledger_table(books[key]['snaps'])}
</section>"""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>5% name cap capital A/B — {STAMP}</title>
<style>{f._css()}</style></head><body>
<h1>Monthly Backtest Report — {ASOF.year} · 5% name cap · start-capital A/B</h1>
<p class="sub">
Stamp <code>{STAMP}</code>. Research only. <strong>Not gold. Not DailyRun.</strong>
Generated {html_mod.escape(gen_s)}. Click column headers to sort.
</p>
{_ask_block()}
<div class="warn"><strong>Freeze:</strong> same 5% DISMISS recipe as <code>{PARENT}</code>.
Only start equity changes. {html_mod.escape(pin_note)}</div>
{_headline_box(packs, tag)}
<div class="hold"><strong>{html_mod.escape(verdict)}</strong></div>
<section>
<h2>Four starts — YE2012 / as-of / Max DD / dies?</h2>
{_headline_table(packs)}
</section>
<section>
<h2>2010–2012 path</h2>
{_path_2010_2012(packs, spy)}
</section>
<section>
<h2>Year-end equity and Max DD%</h2>
{_year_table(books, packs, spy, spy_dd)}
</section>
<section>
<h2>Monthly path</h2>
{_month_path_table(books, packs, spy_dd)}
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
Acronyms first use: StockBee (SB); Relative Strength Index (RSI);
Volume Zone (VZ); Magic Touch (MTS); Rocket Launcher (RL);
Indicators (IND); In-Sample (IS); Out-of-Sample (OOS); buying power (BP);
beginning-of-month (BOM); S&amp;P 500 tracker (SPY); year-end (YE);
average daily volume (ADV).</p>
</section>
{f.r.monthly._SORTABLE_TABLE_SCRIPT}
</body></html>"""


def _book_bullet(title: str, arm: dict[str, Any], pack: dict[str, Any]) -> str:
    led = arm["led"]
    st = arm["stats_full"]
    iso = arm["stats_is"]
    oos = arm["stats_oos"]
    return (
        f"- **{title}** start **${pack['start']:,.0f}**; end **${led.end_equity:,.2f}**; "
        f"2010 ${led.eq_2010:,.2f}; 2011 ${led.eq_2011:,.2f}; 2012 ${led.eq_2012:,.2f}; "
        f"Max DD {_fmt_pct(led.max_dd_pct)} (peak ${led.max_dd_peak:,.2f} → "
        f"trough ${led.max_dd_trough:,.2f}); dies **{'YES' if pack['died'] else 'NO'}**; "
        f"{pack['tag']}; wallet CAGR {_fmt_cagr(pack['wallet_cagr'])}; "
        f"book Ann ROR {_fmt_pct(pack['ann_ror'])}; "
        f"interest ${led.interest:,.2f}; withdrawn ${led.withdrawals:,.2f} "
        f"({led.n_wd} paid / {led.n_wd_skip} skipped); rotates {led.n_rotate}; "
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
    packs: dict[str, dict[str, Any]],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
    tag: str,
    verdict: str,
    extras: dict[str, Any],
    sources: list[str],
    pin_note: str,
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
        "- One stamp, one knob: **start equity** on the frozen 5-sys 1% sell-winner **5% name-cap** recipe that died at $250k.",
        f"- Control = `{PARENT}` namecap05 ($250k, 5% per-name, 1% BOM, $7,500, 10.5%, 2×, sell-winner, RSI 6.51% IS). Re-run here so $333k / $500k / $1M share the same engine.",
        "- Not the later official live-style lids (17.5% name + min(1% BOM, $50k) + 1% ADV).",
        "- 5-sys: StockBee (SB), Relative Strength Index (RSI), Volume Zone (VZ), Magic Touch (MTS), Rocket Launcher (RL). IND out.",
        "- Starts: $250,000 / $333,000 / $500,000 / $1,000,000. One wallet; $7,500 cash on the 1st; 10.5% actual/365 on debit; open notional ≤ 2× equity.",
        "- Monthly risk = 1% of beginning-of-month Closed-only equity. **No $2,500 freeze. No $50k ceiling.**",
        "- RSI: invested = risk_dollar / 0.06509607 (In-Sample avg-loss freeze; do not retune OOS).",
        "- Others: shares = risk_dollar / (entry − stop), then 5% name cap, then remaining buying power.",
        "- When a new signal cannot fit even after name-cap + buying-power clip: sell the most profitable open (last close vs entry), then fill.",
        f"- Decision: **{tag}** — {verdict}",
        "",
        "## Frozen knobs",
        "",
        "- Account seed: **$250,000 / $333,000 / $500,000 / $1,000,000** (the one change)",
        f"- Leverage cap: **{LEVERAGE:.0f}×** Closed-only equity",
        f"- Margin rate: **{MARGIN_RATE:.1%}** actual/365 daily compound",
        f"- Withdrawal: **${WITHDRAW:,.0f}** on month-start after 2010-01-01",
        "- Monthly risk: **1%** of BOM equity (not frozen $2,500; not min(1%, $50k))",
        "- Room rule: **sell winner** when buying power < $1",
        f"- Name cap: **{NAME_CAP:.0%}** of current (cash + reserved) equity, after 1% size, before fill. Same-ticker open lots share the 5% room.",
        "- ADV clip: **off**",
        "- In-Sample (IS) = `entry_date < 2024-01-01`. OOS report-only. Do not retune 5% on OOS.",
        f"- Same Closed / Open pins as `risk2500_monthly_20260917` overlays (RSI = avg-loss CSV).",
        "- Fill order: older closes; DailyRun system then symbol; same-day exits.",
        f"- $250k pin: {pin_note}",
        "",
        "## Max drawdown definition",
        "",
        DD_DEF,
        "",
        "## SPY (linear in start)",
        "",
        f"- First bar used: **{spy['start_date']}**.",
        f"- Last bar used: **{spy['end_date']}**.",
        f"- $250k total return as-of: **${spy['tr_end']:,.2f}** ({spy['tr_mult']:.4f}×). Max DD {_fmt_pct(spy_dd['full_dd'])}.",
        f"- $250k year-end 2012 total-return equity: **${spy_dd['eq_2012']:,.2f}**.",
        f"- Other starts: SPY dollars = $250k SPY × start / $250,000. Max DD% does not scale.",
        "",
        "## Books",
        "",
    ]
    for key, _start, lab in ARM_SPEC:
        lines.append(_book_bullet(lab, books[key], packs[key]))
    lines.extend(
        [
            "",
            "## Headline vs own SPY",
            "",
        ]
    )
    for key, start, _lab in ARM_SPEC:
        p = packs[key]
        lines.append(
            f"- {format_money(start)} YE2012 **${p['eq_2012']:,.2f}** vs SPY **${p['spy_2012']:,.2f}** "
            f"({_vs_spy(p['eq_2012'], p['spy_2012'])}); as-of **${p['end']:,.2f}** vs SPY "
            f"**${p['spy_asof']:,.2f}** ({_vs_spy(p['end'], p['spy_asof'])}); "
            f"Max DD {_fmt_pct(p['max_dd_pct'])}; dies **{'YES' if p['died'] else 'NO'}**; "
            f"**{p['tag']}**; wallet CAGR {_fmt_cagr(p['wallet_cagr'])}; "
            f"book Ann ROR {_fmt_pct(p['ann_ror'])}."
        )
    lines.extend(
        [
            "",
            "## Honesty",
            "",
            "- Judge whether the account still dies and whether it beats its own SPY at YE2012 / as-of — not “did a bigger seed print a bigger number.”",
            "- More start cash can delay the $7,500 bleed without making 5% a live lid.",
            "- OOS is report-only. Do not retune 5% on OOS.",
            "- Official live-style (17.5% name + min(1% BOM, $50k) + 1% ADV) is a different freeze — not this page.",
            "- Not gold. Not DailyRun.",
            "",
            "## Pins / sources",
            "",
        ]
    )
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
| Baseline stamp | Parent 5% DISMISS arm `{PARENT}` namecap05. Wallet engine `risk2500_five_sys_20260917` |
| Universe | House DailyRun 5-sys. Indicators (IND) excluded |
| **Evidence** | Paul: would it matter if we had more capital but kept it to 5%? what if we had 333k? 500k? 1M? |
| **Hypothesis** | A larger start on the same 5% name-cap + 1% BOM + $7,500 wire recipe might outrun the monthly bleed (viable) or only delay the death of the $250k arm |
| **Single knob** | Start equity = $250,000 / $333,000 / $500,000 / $1,000,000. Name cap stays 5%. Risk stays 1% of BOM (no $2,500 / $50k ceiling, no ADV) |
| Frozen settings | 5% name cap. 1% BOM. $7,500 on the 1st. 10.5% actual/365. Open ≤ 2×. RSI 6.51% IS freeze. Sell winner when BP empty. Not live-style 17.5% / $50k / 1% ADV |
| Alternatives | Parent $250k 5% DISMISS pin. Own SPY scaled linearly. Later live-style lids are a different freeze |
| Candidate stamps | `{STAMP}` compare.html / monthly.html |
| Metrics | YE2012 vs own SPY; as-of vs own SPY; Max DD%; dies?; wallet CAGR; book Ann ROR; wires paid; canonical IS/OOS (report-only) |
| **Trade-diff HTML** | N/A — size / wallet overlay (not an entry A/B) |
| ToS before path | N/A |
| ToS after path | N/A |
| **Decision** | {tag} — {verdict} |
| Reviewer | AI job risk2500_namecap5_capital_20260918 |
| PO sign-off | no |
| Reconcile freeze / re-baseline done | no |
| DailyRun | not wired |

## Decision checklist

- [x] Evidence was the PO ask (5% name cap at $250k / $333k / $500k / $1M; YE2012 + as-of vs scaled SPY)
- [x] One knob (start equity). 5% not retuned. Live-style lids not swapped in
- [x] Same Closed pins as the sibling $2,500 / matrix / namecap25 stamps
- [x] Out-of-Sample (OOS) report-only; no RSI retune; no 5% retune
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
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                out[k] = None
            else:
                out[k] = v
        else:
            out[k] = str(v)
    return out


def _pin_match(led: Any) -> str:
    end_ok = abs(float(led.end_equity) - PUB_250["end"]) < 1.0
    ye_ok = abs(float(led.eq_2012) - PUB_250["eq_2012"]) < 1.0
    dd_ok = abs(float(led.max_dd_pct) - PUB_250["max_dd_pct"]) < 0.05
    if end_ok and ye_ok and dd_ok:
        return (
            f"$250k re-run matched the published {PARENT} 5% pin "
            f"(as-of {format_money(led.end_equity)} / YE2012 {format_money(led.eq_2012)} / "
            f"Max DD {_fmt_pct(led.max_dd_pct)})."
        )
    return (
        f"$250k re-run vs published {PARENT} 5% pin: as-of "
        f"{format_money(led.end_equity)} vs {format_money(PUB_250['end'])}; "
        f"YE2012 {format_money(led.eq_2012)} vs {format_money(PUB_250['eq_2012'])}; "
        f"Max DD {_fmt_pct(led.max_dd_pct)} vs {_fmt_pct(PUB_250['max_dd_pct'])}. "
        "This page uses the re-run so all four starts share one engine."
    )


def run() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    spy = f.spy_buyhold()
    spy_dd = m.spy_paths(spy)
    print(
        f"[SPY $250k] {spy['start_date']} -> {spy['end_date']} "
        f"TR {spy['tr_end']:.2f} ({spy['tr_mult']:.3f}x) "
        f"YE2012={spy_dd['eq_2012']:.2f} MaxDD={spy_dd['full_dd']:.2f}%",
        flush=True,
    )

    static = f.load_static(FIVE)
    sources = [
        f"overlays: {f.PREV_DIR.name} (RSI = RSI_overlay_avgloss.csv IS 6.51% freeze)",
        f"5-sys: {', '.join(FIVE)} — Indicators (IND) out",
        f"SPY: {f.SPY_PATH.as_posix()} Adj Close total return + Close price-only; dollars × start/$250k",
        "wallet: tools/risk2500_five_sys_20260917.py run_wallet start_equity=…",
        f"parent 5% DISMISS identity: {PARENT} namecap05 "
        "($250k, 5% name, 1% BOM, $7,500, 10.5%, 2×, sell winner, no $50k, no ADV)",
        "one knob: start_equity 250000 / 333000 / 500000 / 1000000; name_cap_frac=0.05",
        "not live-style 17.5% / min(1% BOM, $50k) / 1% ADV",
        DD_DEF,
    ]

    books: dict[str, dict[str, Any]] = {}
    for key, start, label in ARM_SPEC:
        arm = f._run_arm(
            static,
            rank=FIVE_RANK,
            rotate="winner",
            withdraw=True,
            label=label,
            risk_frac=R_ONE,
            name_cap_frac=NAME_CAP,
            start_equity=start,
        )
        arm["short"] = arm["label"]
        arm["read"] = "One knob (start). Research only."
        books[key] = arm
        f.r.write_overlay_csv(
            arm["trades"],
            OUT_DIR / f"ALL_overlay_5sys_1pct_sw_namecap05_start{int(start)}.csv",
        )

    pin_note = _pin_match(books["s250"]["led"])
    print(f"[pin] {pin_note}", flush=True)

    packs = {
        key: _led_pack(books[key], start, spy) for key, start, _lab in ARM_SPEC
    }
    tag, verdict, extras = _verdict(packs)
    extras["pin_note"] = pin_note
    extras["spy_250_asof"] = float(spy["tr_end"])
    extras["spy_250_2012"] = float(spy_dd["eq_2012"])
    print(f"[verdict] {tag} {verdict}", flush=True)

    now = datetime.now(tz=ET)
    monthly_html = build_monthly(
        books=books,
        packs=packs,
        spy=spy,
        spy_dd=spy_dd,
        tag=tag,
        verdict=verdict,
        extras=extras,
        sources=sources,
        generated=now,
        pin_note=pin_note,
    )
    compare_html = build_compare(
        books=books,
        packs=packs,
        spy=spy,
        spy_dd=spy_dd,
        tag=tag,
        verdict=verdict,
        extras=extras,
        sources=sources,
        generated=now,
        pin_note=pin_note,
    )
    (OUT_DIR / "monthly.html").write_text(monthly_html, encoding="utf-8")
    (OUT_DIR / "compare.html").write_text(compare_html, encoding="utf-8")
    write_baseline(
        books=books,
        packs=packs,
        spy=spy,
        spy_dd=spy_dd,
        tag=tag,
        verdict=verdict,
        extras=extras,
        sources=sources,
        pin_note=pin_note,
    )
    write_hypothesis(tag, verdict)

    summary = {
        "tag": tag,
        "verdict": verdict,
        "pin_note": pin_note,
        "spy_tr_end_250k": spy["tr_end"],
        "spy_2012_250k": spy_dd["eq_2012"],
        "spy_max_dd_pct": spy_dd["full_dd"],
        "years": YEARS,
        "arms": {k: _jsonable(packs[k]) for k, _s, _l in ARM_SPEC},
        "extras": _jsonable(extras),
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"wrote {OUT_DIR / 'monthly.html'}", flush=True)
    print(f"wrote {OUT_DIR / 'compare.html'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
