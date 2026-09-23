#!/usr/bin/env python3
"""Adopt live-style freeze: 1%+$50k + 1% ADV20 + 17.5% per-name (research only).

Paul locked 17.5% after the name-cap ladder (in-sample selection — labeled).
Prior freeze was 10% name (`risk_1pct_50k_adv_10name_20260917`). New stamp —
do not silently mutate that folder.

    drive/paul_experiments/risk_1pct_50k_adv_17name_20260917/

Ladder evidence: risk_1pct_50k_adv_namecap_ladder_20260917.
Not gold. Not DailyRun. Do not retune lids on OOS.
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

STAMP = "risk_1pct_50k_adv_17name_20260917"
OUT_DIR = REPO / "drive" / "paul_experiments" / STAMP
PRIOR_10 = REPO / "drive" / "paul_experiments" / "risk_1pct_50k_adv_10name_20260917"
LADDER = REPO / "drive" / "paul_experiments" / "risk_1pct_50k_adv_namecap_ladder_20260917"
TWOLID = REPO / "drive" / "paul_experiments" / "risk_1pct_50k_adv_20260917"
FROZEN_DIR = REPO / "drive" / "paul_experiments" / "risk2500_frozen_20260917"
ACCOUNT = f.ACCOUNT
ASOF = f.ASOF
ET = f.ET
WITHDRAW = f.WITHDRAW
MARGIN_RATE = f.MARGIN_RATE
LEVERAGE = f.LEVERAGE
R_ONE = 0.01
MAX_RISK = 50_000.0
ADV_FRAC = 0.01
NAME_CAP = 0.175
PRIOR_CAP = 0.10
FIVE = f.FIVE
FIVE_RANK = f.FIVE_RANK
DD_DEF = m.DD_DEF
HUGE = 10_000_000.0

PUB_FROZEN = {
    "end": 5_935_426.945338332,
    "eq_2010": 359_318.61387035396,
    "eq_2011": 582_882.2200463103,
    "eq_2012": 682_250.8246116126,
    "max_dd_pct": 22.266341065917747,
    "peak_reserved": 4_627_358.435962782,
    "peak_name": 4_006_449.5166489915,
    "peak_name_symbol": "AU",
    "n_rotate": 11,
    "n_name_capped": 0,
    "n_skip_name": 0,
    "tag": "HOLD",
}

ORIGINAL_REQUEST = (
    "thanks. i like 17.5% cap the best. can we lock that in with the other "
    "parts? Freeze held: risk = min(1% BOM, $50k) AND shares ≤ 1% ADV20. "
    "One knob: per-name notional cap 10% (control) / 12.5% / 15% / 17.5%. "
    "Best YE2012 among candidates: 17.5% name $422,474.98 vs control $238,607.36."
)
PLAIN_ENGLISH = (
    "Paul picked 17.5% after seeing the ladder — that choice is in-sample "
    "selection, labeled below. The locked live-style recipe is now: five sleeves "
    "— StockBee (SB), Relative Strength Index (RSI), Volume Zone (VZ), Magic "
    "Touch (MTS), Rocket Launcher (RL); Indicators (IND) out. Start $250,000. "
    "Pull $7,500 on the 1st. Pay 10.5% a year on borrowed money. Open stock "
    "cost ≤ 2× the account. Each month risk dollars = the smaller of 1% of the "
    "account and $50,000. RSI dollars in = that risk ÷ 0.0651 (In-Sample "
    "average-loser freeze; do not retune after 2024); other systems shares = "
    "risk ÷ (entry − stop). Shares ≤ 1% of 20-session average daily volume "
    "(ADV20). One ticker may not hold more than 17.5% of whatever the account "
    "is worth right then. When a new signal still cannot fit, sell the most "
    "profitable open name. The old 10% name freeze stays on disk as history — "
    "we do not overwrite it. Still research only: not gold, not DailyRun."
)

ARM_SPEC: list[tuple[str, float, str, str, str]] = [
    (
        "prior10",
        PRIOR_CAP,
        "10% name (prior freeze)",
        "Prior live-style freeze — notional ≤ 10% (kept for delta; not mutated).",
        "ALL_overlay_5sys_1pct_50k_adv_prior10.csv",
    ),
    (
        "live175",
        NAME_CAP,
        "17.5% name (locked freeze)",
        "Adopted live-style freeze — notional ≤ 17.5% of current equity.",
        "ALL_overlay_5sys_1pct_50k_adv_17name.csv",
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


def _m(v: Any) -> str:
    if v is None:
        return "—"
    try:
        return format_money(float(v))
    except (TypeError, ValueError):
        return "—"


def _rel_change(a: float, b: float) -> float:
    if abs(b) < 1e-9:
        return 0.0
    return (a - b) / abs(b)


def _pct_of(n: int, den: int) -> str:
    if den <= 0:
        return "—"
    return f"{100.0 * n / den:.1f}%"


def _load_frozen() -> dict[str, Any]:
    path = FROZEN_DIR / "summary.json"
    out = dict(PUB_FROZEN)
    if not path.exists():
        return out
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return out
    fz = raw.get("frozen2500") or {}
    for k in PUB_FROZEN:
        if k in fz:
            out[k] = fz[k]
    if raw.get("tag"):
        out["tag"] = raw["tag"]
    return out


def _led_pack(arm: dict[str, Any]) -> dict[str, Any]:
    led = arm["led"]
    st = arm["stats_full"]
    n_fill = int(led.n_full) + int(led.n_scaled)
    return {
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
        "n_full": int(led.n_full),
        "n_scaled": int(led.n_scaled),
        "n_fill": n_fill,
        "n_risk_1pct_bound": int(led.n_risk_1pct_bound),
        "n_risk_50k_bound": int(led.n_risk_50k_bound),
        "n_months_50k": int(led.n_months_50k),
        "n_adv_clipped": int(led.n_adv_clipped),
        "n_skip_adv": int(led.n_skip_adv),
        "interest": float(led.interest),
        "withdrawals": float(led.withdrawals),
        "identity": float(led.identity_err),
        "wr": _num(st, "win_pct"),
        "avg": _num(st, "avg_pnl_pct"),
        "pf": _num(st, "pf"),
        "n": _num(st, "n"),
        "name_cap_frac": float(arm.get("name_cap_frac") or led.name_cap_frac or 0.0),
    }


def _ask_block() -> str:
    return f"""
<div class="ask">
<h2>What you asked</h2>
<blockquote>{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN_ENGLISH)}</p>
</div>"""


def _verdict(
    books: dict[str, dict[str, Any]],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
    frozen: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    prior = _led_pack(books["prior10"])
    live = _led_pack(books["live175"])
    spy_asof = float(spy["tr_end"])
    spy_2012 = float(spy_dd["eq_2012"])
    extras: dict[str, Any] = {
        "spy_asof": spy_asof,
        "spy_2012": spy_2012,
        "prior10": prior,
        "live175": live,
        "frozen": frozen,
        "ye2012_vs_prior": _rel_change(live["eq_2012"], prior["eq_2012"]),
        "asof_vs_prior": _rel_change(live["end"], prior["end"]),
        "dd_delta_vs_prior": live["max_dd_pct"] - prior["max_dd_pct"],
        "ye2012_vs_spy": _vs_spy(live["eq_2012"], spy_2012),
        "asof_vs_spy": _vs_spy(live["end"], spy_asof),
        "selection_bias": True,
    }
    path = (
        f"2010–2012 — locked 17.5% {format_money(live['eq_2010'])} / "
        f"{format_money(live['eq_2011'])} / {format_money(live['eq_2012'])}; "
        f"prior 10% {format_money(prior['eq_2010'])} / "
        f"{format_money(prior['eq_2011'])} / {format_money(prior['eq_2012'])}; "
        f"SPY {format_money(spy['years'].get(2010, {}).get('tr', 0))} / "
        f"{format_money(spy['years'].get(2011, {}).get('tr', 0))} / "
        f"{format_money(spy_2012)}."
    )
    lids = (
        f"Lids on locked book — $50k fills {live['n_risk_50k_bound']} "
        f"({_pct_of(live['n_risk_50k_bound'], live['n_fill'])}); "
        f"1% fills {live['n_risk_1pct_bound']}; ADV clip {live['n_adv_clipped']}; "
        f"17.5% name-capped {live['n_name_capped']} "
        f"({_pct_of(live['n_name_capped'], live['n_fill'])}; "
        f"name-skip {live['n_skip_name']})."
    )
    vs = (
        f"vs prior 10%: YE2012 {format_money(live['eq_2012'])} vs "
        f"{format_money(prior['eq_2012'])} ({extras['ye2012_vs_prior']:+.1%}); "
        f"as-of {format_money(live['end'])} vs {format_money(prior['end'])} "
        f"({extras['asof_vs_prior']:+.1%}); Max DD {_fmt_pct(live['max_dd_pct'])} vs "
        f"{_fmt_pct(prior['max_dd_pct'])} ({extras['dd_delta_vs_prior']:+.2f} pt). "
        f"vs SPY: YE2012 {extras['ye2012_vs_spy']}; as-of {extras['asof_vs_spy']}. "
        f"vs frozen $2,500: YE2012 {format_money(live['eq_2012'])} vs "
        f"{format_money(float(frozen['eq_2012']))}; as-of {format_money(live['end'])} vs "
        f"{format_money(float(frozen['end']))}."
    )
    tail = (
        f"{lids} {vs} {path} "
        "Selection: Paul chose 17.5% after the in-sample ladder "
        f"(`{LADDER.name}`). Freeze is locked for research; still HOLD vs gold / "
        "DailyRun (no walk-forward). Do not retune lids on OOS. Not gold. Not DailyRun."
    )

    if live["end"] < ACCOUNT * 0.1 or live["max_dd_pct"] >= 90.0:
        tag = "DISMISS"
        prose = f"DISMISS — locked 17.5% book died or Max DD >=90%. {tail}"
        return tag, prose, extras

    tag = "ADOPT (research freeze)"
    prose = (
        f"ADOPT 17.5% name into the live-style freeze (research candidate) — "
        f"risk = min(1% BOM, $50k) AND shares <= 1% ADV20 AND notional <= 17.5% "
        f"current equity. Prior 10% freeze remains at `{PRIOR_10.name}` "
        f"(not overwritten). YE2012 {format_money(live['eq_2012'])} vs prior 10% "
        f"{format_money(prior['eq_2012'])} ({extras['ye2012_vs_prior']:+.1%}); "
        f"Max DD {_fmt_pct(live['max_dd_pct'])} vs {_fmt_pct(prior['max_dd_pct'])}. "
        f"HOLD versus gold / DailyRun. {tail}"
    )
    return tag, prose, extras


def _headline_box(extras: dict[str, Any], tag: str) -> str:
    live = extras["live175"]
    prior = extras["prior10"]
    return f"""
<div class="lead">
  <h2>Headline — live-style freeze locked at 17.5% name</h2>
  <p><strong class="yes">{html_mod.escape(tag)}</strong> · research only · not gold · not DailyRun</p>
  <p class="small">Locked: risk = min(1% beginning-of-month equity, $50k)
  AND shares ≤ 1% ADV20 AND notional ≤ <strong>17.5%</strong> of current equity.
  Prior 10% freeze kept as history. Selection bias: chosen after ladder.</p>
  <div class="cards">
    <div class="card card-shared">
      <h3>Locked 17.5% · YE2012</h3>
      <div class="metric">{format_money(live['eq_2012'])}</div>
      <div class="small">SPY {format_money(extras['spy_2012'])} · {extras['ye2012_vs_spy']}</div>
      <div class="small">vs prior 10% {extras['ye2012_vs_prior']:+.1%}</div>
    </div>
    <div class="card card-shared">
      <h3>Locked 17.5% · as-of {ASOF.isoformat()}</h3>
      <div class="metric">{format_money(live['end'])}</div>
      <div class="small">SPY {format_money(extras['spy_asof'])} · {extras['asof_vs_spy']}</div>
      <div class="small">Max DD {_fmt_pct(live['max_dd_pct'])} ({extras['dd_delta_vs_prior']:+.2f} pt vs 10%)</div>
    </div>
    <div class="card">
      <h3>Prior 10% freeze (history)</h3>
      <div class="metric">{format_money(prior['eq_2012'])}</div>
      <div class="small">YE2012 · as-of {format_money(prior['end'])}</div>
      <div class="small">Max DD {_fmt_pct(prior['max_dd_pct'])} · stamp <code>{PRIOR_10.name}</code></div>
    </div>
    <div class="card">
      <h3>Name lid binds</h3>
      <div class="metric">{live['n_name_capped']}</div>
      <div class="small">17.5% capped fills ({_pct_of(live['n_name_capped'], live['n_fill'])})</div>
      <div class="small">Prior 10% capped {prior['n_name_capped']} ({_pct_of(prior['n_name_capped'], prior['n_fill'])})</div>
    </div>
  </div>
</div>"""


def _freeze_table() -> str:
    head = f._sortable_head(
        [("Knob", "text"), ("Locked value", "text"), ("Notes", "text")]
    )
    rows = [
        ("Systems", "SB, RSI, VZ, MTS, RL", "IND out"),
        ("Start equity", format_money(ACCOUNT), "one wallet"),
        ("Monthly withdraw", format_money(WITHDRAW), "1st of month"),
        ("Margin", f"{MARGIN_RATE:.1%}", "on borrowed cash"),
        ("Leverage", f"{LEVERAGE}×", "open cost ≤ 2× equity"),
        ("Rotate", "sell-winner", "when no buying power"),
        ("RSI size", "risk ÷ 0.0651", "IS avg-loss freeze; do not retune OOS"),
        ("Risk lid", "min(1% BOM equity, $50,000)", "locked"),
        ("ADV lid", "shares ≤ 1% ADV20", "locked"),
        ("Name lid", "notional ≤ 17.5% current equity", "adopted from ladder; was 10%"),
    ]
    body = "".join(
        f"<tr><td>{html_mod.escape(a)}</td><td>{html_mod.escape(b)}</td>"
        f"<td class=\"small\">{html_mod.escape(c)}</td></tr>"
        for a, b, c in rows
    )
    return (
        '<p class="small">Click headers to sort. This is the locked research freeze.</p>'
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def _path_table(
    books: dict[str, dict[str, Any]],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
    frozen: dict[str, Any],
) -> str:
    head = f._sortable_head(
        [
            ("Book", "text"),
            ("2010 end", "num"),
            ("2011 end", "num"),
            ("2012 end", "num"),
            ("vs SPY YE2012", "text"),
            ("Full Max DD%", "num"),
            ("As-of", "num"),
        ]
    )
    rows = [
        (
            "SPY $250k total return",
            spy["years"].get(2010, {}).get("tr"),
            spy["years"].get(2011, {}).get("tr"),
            spy_dd["eq_2012"],
            "1.00×",
            spy_dd["full_dd"],
            spy["tr_end"],
        ),
        (
            "Frozen $2,500 (sibling)",
            frozen["eq_2010"],
            frozen["eq_2011"],
            frozen["eq_2012"],
            _vs_spy(float(frozen["eq_2012"]), spy_dd["eq_2012"]),
            frozen["max_dd_pct"],
            frozen["end"],
        ),
    ]
    for k, _frac, lab, *_ in ARM_SPEC:
        led = books[k]["led"]
        rows.append(
            (
                lab,
                led.eq_2010,
                led.eq_2011,
                led.eq_2012,
                _vs_spy(led.eq_2012, spy_dd["eq_2012"]),
                led.max_dd_pct,
                led.end_equity,
            )
        )
    body = ""
    for name, y0, y1, y2, vs, dd, end in rows:
        body += (
            "<tr>"
            f"<td>{html_mod.escape(str(name))}</td>"
            f"<td>{_m(y0)}</td><td>{_m(y1)}</td><td>{_m(y2)}</td>"
            f"<td>{html_mod.escape(str(vs))}</td>"
            f"<td>{_fmt_pct(dd)}</td><td>{_m(end)}</td></tr>"
        )
    live = books["live175"]["led"]
    last = (
        '<tr class="total-row"><th>Pinned (locked 17.5%)</th>'
        f"<td>{format_money(live.eq_2010)}</td>"
        f"<td>{format_money(live.eq_2011)}</td>"
        f"<td>{format_money(live.eq_2012)}</td>"
        f"<td>{html_mod.escape(_vs_spy(live.eq_2012, spy_dd['eq_2012']))}</td>"
        f"<td>{_fmt_pct(live.max_dd_pct)}</td>"
        f"<td>{format_money(live.end_equity)}</td></tr>"
    )
    return (
        '<p class="small">Early path + as-of. Click headers to sort. Total row pinned.</p>'
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}{last}</tbody></table></div>"
    )


def _lead_table(
    books: dict[str, dict[str, Any]],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
) -> str:
    head = f._sortable_head(
        [
            ("Book", "text"),
            ("Name cap", "text"),
            ("YE2012", "num"),
            ("vs prior 10% YE2012", "text"),
            ("As-of", "num"),
            ("Max DD%", "num"),
            ("Δ DD vs 10%", "num"),
            ("Name-capped", "num"),
            ("Peak name %", "num"),
            ("WR%", "num"),
            ("Avg PnL%", "num"),
            ("PF", "num"),
        ]
    )
    prior = books["prior10"]["led"]
    body = ""
    for k, frac, lab, *_ in ARM_SPEC:
        led = books[k]["led"]
        st = books[k]["stats_full"]
        body += (
            "<tr>"
            f"<td>{html_mod.escape(lab)}</td>"
            f"<td>{frac:.1%}</td>"
            f"<td>{format_money(led.eq_2012)}</td>"
            f"<td>{'prior' if k == 'prior10' else f'{_rel_change(led.eq_2012, prior.eq_2012):+.1%}'}</td>"
            f"<td>{format_money(led.end_equity)}</td>"
            f"<td>{_fmt_pct(led.max_dd_pct)}</td>"
            f"<td>{0.0 if k == 'prior10' else led.max_dd_pct - prior.max_dd_pct:+.2f} pt</td>"
            f"<td>{led.n_name_capped}</td>"
            f"<td>{_fmt_pct(100.0 * float(led.peak_name_frac))}</td>"
            f"<td>{_fmt_pct(st.get('win_pct'))}</td>"
            f"<td>{_fmt_pct(st.get('avg_pnl_pct'))}</td>"
            f"<td>{st.get('pf')}</td></tr>"
        )
    body += (
        "<tr><td>SPY $250k TR</td><td>—</td>"
        f"<td>{format_money(spy_dd['eq_2012'])}</td><td>—</td>"
        f"<td>{format_money(spy['tr_end'])}</td>"
        f"<td>{_fmt_pct(spy_dd['full_dd'])}</td>"
        "<td>—</td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td></tr>"
    )
    live = books["live175"]["led"]
    last = (
        '<tr class="total-row"><th>Pinned (locked 17.5%)</th>'
        f"<td>{NAME_CAP:.1%}</td>"
        f"<td>{format_money(live.eq_2012)}</td>"
        f"<td>{_rel_change(live.eq_2012, prior.eq_2012):+.1%}</td>"
        f"<td>{format_money(live.end_equity)}</td>"
        f"<td>{_fmt_pct(live.max_dd_pct)}</td>"
        f"<td>{live.max_dd_pct - prior.max_dd_pct:+.2f} pt</td>"
        f"<td>{live.n_name_capped}</td>"
        f"<td>{_fmt_pct(100.0 * float(live.peak_name_frac))}</td>"
        "<td>—</td><td>—</td><td>—</td></tr>"
    )
    return (
        '<p class="small">Click headers to sort. Total row pinned.</p>'
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}{last}</tbody></table></div>"
    )


def _year_table(
    books: dict[str, dict[str, Any]],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
) -> str:
    labels = [(k, lab) for k, _f, lab, *_ in ARM_SPEC]
    head = f._sortable_head(
        [("Year-end", "num")]
        + [(lab, "num") for _k, lab in labels]
        + [("SPY TR", "num")]
        + [(f"{lab} Max DD%", "num") for _k, lab in labels]
        + [("SPY Max DD%", "num"), ("Note", "text")]
    )
    body = ""
    for y in range(2010, ASOF.year + 1):
        cells = f"<td>{y}</td>"
        for k, _lab in labels:
            row = next((x for x in books[k]["years"] if x["year"] == y), None)
            cells += f"<td>{format_money(row['ending_equity']) if row else '—'}</td>"
        sy = spy["years"].get(y)
        sdd = spy_dd["years"].get(y, {})
        cells += f"<td>{format_money(sy['tr']) if sy else '—'}</td>"
        for k, _lab in labels:
            row = next((x for x in books[k]["years"] if x["year"] == y), None)
            cells += f"<td>{_fmt_pct(row['max_dd_pct']) if row else '—'}</td>"
        note = "YE2012 headline" if y == 2012 else (
            f"through {ASOF.isoformat()}" if y == ASOF.year else ""
        )
        body += (
            f"<tr>{cells}<td>{_fmt_pct(sdd.get('max_dd_pct'))}</td>"
            f"<td class=\"small\">{html_mod.escape(note)}</td></tr>"
        )
    last = '<tr class="total-row"><th>Total / last</th>'
    for k, _lab in labels:
        last += f"<td>{format_money(books[k]['led'].end_equity)}</td>"
    last += f"<td>{format_money(spy['tr_end'])}</td>"
    for k, _lab in labels:
        last += f"<td>{_fmt_pct(books[k]['led'].max_dd_pct)}</td>"
    last += f"<td>{_fmt_pct(spy_dd['full_dd'])}</td><td class=\"small\">Pinned</td></tr>"
    return (
        '<p class="small">Full year-end path. Click headers to sort.</p>'
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}{last}</tbody></table></div>"
    )


def _compare_sections(books: dict[str, dict[str, Any]], verdict: str) -> str:
    col_map = {"IS": "stats_is", "OOS": "stats_oos", "FULL": "stats_full"}
    notes = {
        "IS": "In-Sample — entry before 2024-01-01. 17.5% was chosen on the ladder (selection bias).",
        "OOS": "Out-of-Sample — report-only. Do not retune the 17.5% lid from this slice.",
        "FULL": verdict,
    }
    html = ""
    for sl in ("IS", "OOS", "FULL"):
        cols = [
            ("10% prior freeze", books["prior10"][col_map[sl]]),
            ("17.5% locked freeze", books["live175"][col_map[sl]]),
        ]
        html += f"""
<section>
<h2>Canonical compare · {sl}</h2>
<p class="small">{html_mod.escape(notes[sl])} Sheet / Total PnL $ omitted. Click headers to sort. Δ vs prior 10%.</p>
<div class="table-wrap">{f._canonical_table(cols)}</div>
</section>"""
    return html


def build_compare(
    *,
    books: dict[str, dict[str, Any]],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
    frozen: dict[str, Any],
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
<title>Adopt — live-style freeze 17.5% name — {STAMP}</title>
<style>{f._css()}</style></head><body>
<h1>Adopt — live-style freeze locked at 17.5% name</h1>
<p class="sub">
Stamp <code>{STAMP}</code>. Research only. <strong>Not gold. Not DailyRun.</strong>
Generated {html_mod.escape(gen_s)}. Click column headers to sort.
</p>
{_ask_block()}
{_headline_box(extras, tag)}
<div class="hold"><strong>{html_mod.escape(verdict)}</strong></div>
<section>
<h2>Locked freeze knobs</h2>
{_freeze_table()}
</section>
<section>
<h2>2010–2012 path + as-of</h2>
{_path_table(books, spy, spy_dd, frozen)}
</section>
<section>
<h2>Locked 17.5% vs prior 10%</h2>
{_lead_table(books, spy, spy_dd)}
</section>
<section>
<h2>Year-end equity and Max DD%</h2>
{_year_table(books, spy, spy_dd)}
</section>
{_compare_sections(books, verdict)}
<section>
<h2>Selection bias</h2>
<p>17.5% was chosen <strong>after</strong> seeing the name-cap ladder
(<code>{LADDER.name}</code>) on the same history. That is in-sample selection.
IS/OOS below are re-scored under the chosen freeze; OOS is report-only —
do not retune. Still HOLD vs gold / DailyRun until walk-forward / promotion bar.</p>
</section>
<section>
<h2>Max drawdown definition</h2>
<p>{html_mod.escape(DD_DEF)}</p>
</section>
<section>
<h2>Data sources</h2>
<ul class="sources">{sources_html}</ul>
<p class="small">Monthly: <a href="monthly.html">monthly.html</a>.
Prior 10%: <code>{PRIOR_10.name}</code>. Ladder: <code>{LADDER.name}</code>.
Not gold. Not DailyRun.</p>
</section>
{f.r.monthly._SORTABLE_TABLE_SCRIPT}
</body></html>"""


def build_monthly(
    *,
    books: dict[str, dict[str, Any]],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
    frozen: dict[str, Any],
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
    for k, _frac, lab, *_ in ARM_SPEC:
        ledgers += f"""
<section>
<h2>Month ledger — {html_mod.escape(lab)}</h2>
{f._ledger_table(books[k]['snaps'], risk_col="Month risk $", bind_cols=True)}
</section>"""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Monthly — live-style freeze 17.5% name — {STAMP}</title>
<style>{f._css()}</style></head><body>
<h1>Monthly — live-style freeze locked at 17.5% name</h1>
<p class="sub">
Stamp <code>{STAMP}</code>. Research only. <strong>Not gold. Not DailyRun.</strong>
Generated {html_mod.escape(gen_s)}.
</p>
{_ask_block()}
{_headline_box(extras, tag)}
<div class="hold"><strong>{html_mod.escape(verdict)}</strong></div>
<section>
<h2>Locked freeze knobs</h2>
{_freeze_table()}
</section>
<section>
<h2>2010–2012 path + as-of</h2>
{_path_table(books, spy, spy_dd, frozen)}
</section>
<section>
<h2>Locked 17.5% vs prior 10%</h2>
{_lead_table(books, spy, spy_dd)}
</section>
{ledgers}
<section>
<h2>Data sources</h2>
<ul class="sources">{sources_html}</ul>
<p class="small">Compare: <a href="compare.html">compare.html</a>. Not gold. Not DailyRun.</p>
</section>
{f.r.monthly._SORTABLE_TABLE_SCRIPT}
</body></html>"""


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (int, float, str)) or obj is None:
        return obj
    return str(obj)


def write_baseline(
    *,
    books: dict[str, dict[str, Any]],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
    frozen: dict[str, Any],
    tag: str,
    verdict: str,
    extras: dict[str, Any],
    sources: list[str],
) -> None:
    live = extras["live175"]
    prior = extras["prior10"]
    lines = [
        f"# BASELINE — {STAMP}",
        "",
        "## What you asked",
        "",
        ORIGINAL_REQUEST,
        "",
        "## In plain English",
        "",
        PLAIN_ENGLISH,
        "",
        f"## Tag: {tag}",
        "",
        verdict,
        "",
        "## Locked live-style freeze",
        "",
        "- 5-sys: SB, RSI, VZ, MTS, RL (IND out)",
        f"- Account ${ACCOUNT:,.0f}; withdraw ${WITHDRAW:,.0f}/mo; margin {MARGIN_RATE:.1%}; "
        f"leverage {LEVERAGE}×; sell-winner",
        "- risk = min(1% beginning-of-month equity, $50,000)",
        "- shares ≤ 1% ADV20",
        "- **name_cap_frac = 0.175 (17.5%)** — adopted",
        "- RSI size = risk / 0.0651 (IS avg-loss freeze)",
        "",
        "## Delta from prior freeze",
        "",
        f"- Prior: `{PRIOR_10.name}` — same lids except name_cap_frac = 0.10",
        f"- Ladder evidence: `{LADDER.name}`",
        f"- YE2012: locked ${live['eq_2012']:,.2f} vs prior ${prior['eq_2012']:,.2f} "
        f"({extras['ye2012_vs_prior']:+.1%})",
        f"- As-of: locked ${live['end']:,.2f} vs prior ${prior['end']:,.2f} "
        f"({extras['asof_vs_prior']:+.1%})",
        f"- Max DD: {_fmt_pct(live['max_dd_pct'])} vs {_fmt_pct(prior['max_dd_pct'])} "
        f"({extras['dd_delta_vs_prior']:+.2f} pt)",
        "",
        "## Selection bias",
        "",
        "Paul chose 17.5% after viewing the in-sample name-cap ladder. "
        "Re-scored IS/OOS under this freeze; OOS report-only. "
        "ADOPT (research freeze) ≠ gold ≠ DailyRun.",
        "",
        "## Paths",
        "",
        f"- Locked 17.5%: 2010 ${live['eq_2010']:,.2f}; 2011 ${live['eq_2011']:,.2f}; "
        f"2012 ${live['eq_2012']:,.2f}; as-of ${live['end']:,.2f}; "
        f"Max DD {_fmt_pct(live['max_dd_pct'])}; name-capped {live['n_name_capped']}.",
        f"- Prior 10%: 2010 ${prior['eq_2010']:,.2f}; 2011 ${prior['eq_2011']:,.2f}; "
        f"2012 ${prior['eq_2012']:,.2f}; as-of ${prior['end']:,.2f}; "
        f"Max DD {_fmt_pct(prior['max_dd_pct'])}.",
        f"- SPY YE2012 ${spy_dd['eq_2012']:,.2f}; as-of ${spy['tr_end']:,.2f}.",
        f"- Frozen $2,500 YE2012 ${float(frozen['eq_2012']):,.2f}; "
        f"as-of ${float(frozen['end']):,.2f}.",
        "",
        "## Sources",
        "",
    ]
    for s in sources:
        lines.append(f"- {s}")
    lines.append("")
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines), encoding="utf-8")


def write_hypothesis(tag: str, verdict: str) -> None:
    text = f"""# HYPOTHESIS — {STAMP}

## Adopted freeze
risk = min(1% BOM, $50k) AND shares ≤ 1% ADV20 AND notional ≤ **17.5%** current equity.

## Delta from prior
Prior live-style freeze used 10% name (`{PRIOR_10.name}`).
Paul selected 17.5% after `{LADDER.name}` (in-sample selection — labeled).

## Tag
{tag}

## Verdict
{verdict}

## Promotion
Research freeze only. Not gold. Not DailyRun. No OOS retune.
"""
    (OUT_DIR / "HYPOTHESIS.md").write_text(text, encoding="utf-8")


def update_prior_pointers(tag: str, live: dict[str, Any]) -> None:
    """Mark prior 10% stamp as superseded; note adoption on ladder."""
    note = (
        f"\n\n---\n\n## Superseded (research freeze update)\n\n"
        f"Paul locked **17.5%** name into the live-style freeze on 2026-09-17.\n\n"
        f"- New freeze stamp: `{STAMP}`\n"
        f"- Locked YE2012 ${live['eq_2012']:,.2f}; as-of ${live['end']:,.2f}\n"
        f"- This 10% folder is **history** — not mutated.\n"
        f"- Tag on adopt stamp: {tag}\n"
    )
    ptr = PRIOR_10 / "POINTER.md"
    if ptr.exists():
        text = ptr.read_text(encoding="utf-8")
        if "Superseded (research freeze update)" not in text:
            ptr.write_text(text.rstrip() + note + "\n", encoding="utf-8")
    else:
        ptr.write_text(
            f"# Pointer — {PRIOR_10.name}\n\nPrior 10% live-style freeze.\n{note}\n",
            encoding="utf-8",
        )

    ladder_note = (
        f"\n\n---\n\n## Paul adoption\n\n"
        f"Paul liked **17.5%** best and locked it with the other lids.\n\n"
        f"- Adopt stamp: `{STAMP}`\n"
        f"- Freeze: min(1% BOM, $50k) + 1% ADV20 + **17.5% name**\n"
    )
    lb = LADDER / "BASELINE.md"
    if lb.exists():
        text = lb.read_text(encoding="utf-8")
        if "Paul adoption" not in text:
            lb.write_text(text.rstrip() + ladder_note + "\n", encoding="utf-8")


def write_live_style_pointer(tag: str, live: dict[str, Any]) -> None:
    root = REPO / "drive" / "paul_experiments" / "LIVE_STYLE_FREEZE.md"
    root.write_text(
        "\n".join(
            [
                "# Live-style freeze (current research)",
                "",
                f"**Stamp:** `{STAMP}`",
                "",
                "## Locked lids",
                "",
                "- risk = min(1% beginning-of-month equity, $50,000)",
                "- shares ≤ 1% ADV20",
                "- notional ≤ **17.5%** of current equity",
                "",
                "## Book",
                "",
                "- 5-sys: SB, RSI, VZ, MTS, RL (IND out)",
                f"- ${ACCOUNT:,.0f} start; ${WITHDRAW:,.0f}/mo; {MARGIN_RATE:.1%} margin; "
                f"{LEVERAGE}×; sell-winner; RSI ÷ 0.0651",
                "",
                "## Path",
                "",
                f"- YE2012 ${live['eq_2012']:,.2f}; as-of ${live['end']:,.2f}; "
                f"Max DD {_fmt_pct(live['max_dd_pct'])}",
                f"- Tag: {tag}",
                "",
                "## History",
                "",
                f"- Prior 10% freeze: `{PRIOR_10.name}` (not mutated)",
                f"- Name-cap ladder: `{LADDER.name}`",
                f"- Two-lid (no name): `{TWOLID.name}`",
                "",
                "Research only. Not gold. Not DailyRun.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _run_one(static: list[Any], *, name_cap: float, label: str) -> dict[str, Any]:
    arm = f._run_arm(
        static,
        rank=FIVE_RANK,
        rotate="winner",
        withdraw=True,
        label=label,
        risk_frac=R_ONE,
        name_cap_frac=name_cap,
        max_risk_dollar=MAX_RISK,
        adv_frac=ADV_FRAC,
    )
    arm["name_cap_frac"] = float(name_cap)
    return arm


def run() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    frozen = _load_frozen()
    spy = f.spy_buyhold()
    spy_dd = m.spy_paths(spy)
    print(
        f"[SPY] YE2012={spy_dd['eq_2012']:.2f} asof={spy['tr_end']:.2f} "
        f"MaxDD={spy_dd['full_dd']:.2f}%",
        flush=True,
    )

    static = f.load_static(FIVE)
    sources = [
        f"overlays: {f.PREV_DIR.name} (RSI = RSI_overlay_avgloss.csv IS 6.51% freeze)",
        f"5-sys: {', '.join(FIVE)} — Indicators (IND) out",
        f"SPY: {f.SPY_PATH.as_posix()} Adj Close total return + Close price-only",
        "wallet: tools/risk2500_five_sys_20260917.py run_wallet",
        "LOCKED live-style freeze: risk=min(1% BOM, $50k) AND shares≤1% ADV20 "
        "AND notional≤17.5% current equity",
        f"prior 10% freeze (history): {PRIOR_10.name}",
        f"ladder evidence: {LADDER.name}",
        "selection: Paul chose 17.5% after in-sample ladder — labeled",
        DD_DEF,
    ]

    books: dict[str, dict[str, Any]] = {}
    for key, frac, label, _cap, csv_name in ARM_SPEC:
        print(f"[arm] {key} name_cap={frac:.1%} …", flush=True)
        arm = _run_one(static, name_cap=frac, label=label)
        arm["short"] = arm["label"]
        arm["read"] = "Locked freeze adopt. Research only."
        books[key] = arm
        f.r.write_overlay_csv(arm["trades"], OUT_DIR / csv_name)
        led = arm["led"]
        print(
            f"[arm] {key} YE2012={led.eq_2012:.2f} asof={led.end_equity:.2f} "
            f"MaxDD={led.max_dd_pct:.2f}%",
            flush=True,
        )

    tag, verdict, extras = _verdict(books, spy, spy_dd, frozen)
    print(f"[verdict] {tag}", flush=True)
    print(verdict, flush=True)

    now = datetime.now(tz=ET)
    (OUT_DIR / "compare.html").write_text(
        build_compare(
            books=books,
            spy=spy,
            spy_dd=spy_dd,
            frozen=frozen,
            tag=tag,
            verdict=verdict,
            extras=extras,
            sources=sources,
            generated=now,
        ),
        encoding="utf-8",
    )
    (OUT_DIR / "monthly.html").write_text(
        build_monthly(
            books=books,
            spy=spy,
            spy_dd=spy_dd,
            frozen=frozen,
            tag=tag,
            verdict=verdict,
            extras=extras,
            sources=sources,
            generated=now,
        ),
        encoding="utf-8",
    )
    write_baseline(
        books=books,
        spy=spy,
        spy_dd=spy_dd,
        frozen=frozen,
        tag=tag,
        verdict=verdict,
        extras=extras,
        sources=sources,
    )
    write_hypothesis(tag, verdict)
    update_prior_pointers(tag, extras["live175"])
    write_live_style_pointer(tag, extras["live175"])

    (OUT_DIR / "POINTER.md").write_text(
        "\n".join(
            [
                f"# Pointer — {STAMP}",
                "",
                "**Current research live-style freeze** — 17.5% name locked.",
                "",
                f"- This stamp: `{OUT_DIR.as_posix()}`",
                f"- Prior 10% (history): `{PRIOR_10.as_posix()}`",
                f"- Ladder: `{LADDER.as_posix()}`",
                f"- Two-lid sibling: `{TWOLID.as_posix()}`",
                f"- Index: `drive/paul_experiments/LIVE_STYLE_FREEZE.md`",
                "",
                f"Tag: {tag}",
                "",
                f"Locked YE2012 ${extras['live175']['eq_2012']:,.2f}; "
                f"as-of ${extras['live175']['end']:,.2f}; "
                f"Max DD {_fmt_pct(extras['live175']['max_dd_pct'])}.",
                "",
                "Not gold. Not DailyRun.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    summary = {
        "tag": tag,
        "verdict": verdict,
        "freeze": {
            "risk": "min(1% BOM, $50000)",
            "adv_frac": ADV_FRAC,
            "name_cap_frac": NAME_CAP,
        },
        "spy_tr_end": spy["tr_end"],
        "spy_2012": spy_dd["eq_2012"],
        "live175": extras["live175"],
        "prior10": extras["prior10"],
        "frozen2500": frozen,
        "extras": _jsonable(extras),
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"wrote {OUT_DIR / 'compare.html'}", flush=True)
    print(f"wrote {OUT_DIR / 'monthly.html'}", flush=True)
    print(f"wrote LIVE_STYLE_FREEZE.md", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
