#!/usr/bin/env python3
"""Live-style freeze name-cap ladder: 10% vs 12.5 / 15 / 17.5% (research only).

Control = published live-style freeze (1%+$50k + 1% ADV20 + 10% name).
One knob: name_cap_frac. Focus: early years (2010–2012 / first few) + drawdowns.

    drive/paul_experiments/risk_1pct_50k_adv_namecap_ladder_20260917/

Parent freeze: risk_1pct_50k_adv_10name_20260917. Not gold. Not DailyRun.
Do not retune lids on OOS.
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

STAMP = "risk_1pct_50k_adv_namecap_ladder_20260917"
OUT_DIR = REPO / "drive" / "paul_experiments" / STAMP
PARENT = REPO / "drive" / "paul_experiments" / "risk_1pct_50k_adv_10name_20260917"
ACCOUNT = f.ACCOUNT
ASOF = f.ASOF
ET = f.ET
WITHDRAW = f.WITHDRAW
MARGIN_RATE = f.MARGIN_RATE
LEVERAGE = f.LEVERAGE
R_ONE = 0.01
MAX_RISK = 50_000.0
ADV_FRAC = 0.01
FIVE = f.FIVE
FIVE_RANK = f.FIVE_RANK
DD_DEF = m.DD_DEF
HUGE = 10_000_000.0

ORIGINAL_REQUEST = (
    "it looks like the 10% cap per name holds us back in the first few years. "
    "Compare — 10% name is in the live-style freeze. might we do better with a "
    "12.5, 15, or 17.5% cap? how do those compare in the first few years? what "
    "are their drawdowns like?"
)
PLAIN_ENGLISH = (
    "Same live-style recipe as the published 10% book: five sleeves — StockBee "
    "(SB), Relative Strength Index (RSI), Volume Zone (VZ), Magic Touch (MTS), "
    "Rocket Launcher (RL). Indicators (IND) out. Start $250,000. Pull $7,500 on "
    "the 1st. Pay 10.5% a year on borrowed money. Open stock cost ≤ 2× the "
    "account. Each month risk dollars = the smaller of 1% of the account and "
    "$50,000. RSI dollars in = that risk ÷ 0.0651 (In-Sample average-loser freeze; "
    "do not retune after 2024); other systems shares = risk ÷ (entry − stop). "
    "Then shares ≤ 1% of 20-session average daily volume (ADV20). The one knob "
    "we change: one ticker may not hold more than 10% (control / live freeze), "
    "or 12.5%, or 15%, or 17.5% of whatever the account is worth right then. "
    "When a new signal still cannot fit, sell the most profitable open name. "
    "We care most about 2010–2012 (and the first few years) and Max Drawdown "
    "(Max DD) — how deep the account dips from peak — not later-year paper "
    "millions. Not gold. Not DailyRun."
)

# key, frac, short label, prose, overlay csv
ARM_SPEC: list[tuple[str, float, str, str, str]] = [
    (
        "namecap10",
        0.10,
        "10% name (control)",
        "Live-style freeze control — notional ≤ 10% of current equity.",
        "ALL_overlay_5sys_1pct_50k_adv_namecap10.csv",
    ),
    (
        "namecap125",
        0.125,
        "12.5% name",
        "Same freeze; notional ≤ 12.5% of current equity.",
        "ALL_overlay_5sys_1pct_50k_adv_namecap125.csv",
    ),
    (
        "namecap15",
        0.15,
        "15% name",
        "Same freeze; notional ≤ 15% of current equity.",
        "ALL_overlay_5sys_1pct_50k_adv_namecap15.csv",
    ),
    (
        "namecap175",
        0.175,
        "17.5% name",
        "Same freeze; notional ≤ 17.5% of current equity.",
        "ALL_overlay_5sys_1pct_50k_adv_namecap175.csv",
    ),
]

ARM_KEYS = [k for k, *_ in ARM_SPEC]
CONTROL_KEY = "namecap10"
EARLY_YEARS = (2010, 2011, 2012, 2013, 2014)


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


def _led_pack(arm: dict[str, Any]) -> dict[str, Any]:
    led = arm["led"]
    st = arm["stats_full"]
    n_fill = int(led.n_full) + int(led.n_scaled)
    early = {y: float(getattr(led, f"eq_{y}", 0.0)) for y in (2010, 2011, 2012)}
    # year_end rows for 2013–2014
    for y in (2013, 2014):
        row = next((x for x in arm["years"] if x["year"] == y), None)
        early[y] = float(row["ending_equity"]) if row else float("nan")
    year_dd = {int(y): float(v) for y, v in (led.year_max_dd_pct or {}).items()}
    year_run = {int(y): float(v) for y, v in (led.year_running_max_dd_pct or {}).items()}
    return {
        "end": float(led.end_equity),
        "eq_2010": float(led.eq_2010),
        "eq_2011": float(led.eq_2011),
        "eq_2012": float(led.eq_2012),
        "eq_2013": early.get(2013),
        "eq_2014": early.get(2014),
        "max_dd_pct": float(led.max_dd_pct),
        "max_dd_peak": float(led.max_dd_peak),
        "max_dd_trough": float(led.max_dd_trough),
        "year_max_dd_pct": year_dd,
        "year_running_max_dd_pct": year_run,
        "early_worst_year_dd": max(
            (year_dd.get(y, 0.0) for y in EARLY_YEARS), default=0.0
        ),
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


def _quality_worse(cand: dict[str, Any], ctrl: dict[str, Any]) -> bool:
    return (
        cand["wr"] + 0.25 < ctrl["wr"]
        and cand["avg"] + 0.25 < ctrl["avg"]
        and cand["max_dd_pct"] > ctrl["max_dd_pct"] + 2.0
    )


def _early_better(cand: dict[str, Any], ctrl: dict[str, Any]) -> bool:
    """Material early-path lift vs control (YE2012 and at least one of 2010/2011)."""
    ye = _rel_change(cand["eq_2012"], ctrl["eq_2012"])
    if ye < 0.05:
        return False
    y0 = _rel_change(cand["eq_2010"], ctrl["eq_2010"])
    y1 = _rel_change(cand["eq_2011"], ctrl["eq_2011"])
    return y0 >= 0.03 or y1 >= 0.03


def _dd_ok(cand: dict[str, Any], ctrl: dict[str, Any], slack: float = 2.0) -> bool:
    return cand["max_dd_pct"] <= ctrl["max_dd_pct"] + slack


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
) -> tuple[str, str, dict[str, Any]]:
    packs = {k: _led_pack(books[k]) for k in ARM_KEYS}
    ctrl = packs[CONTROL_KEY]
    spy_asof = float(spy["tr_end"])
    spy_2012 = float(spy_dd["eq_2012"])

    ranked = sorted(
        [k for k in ARM_KEYS if k != CONTROL_KEY],
        key=lambda k: packs[k]["eq_2012"],
        reverse=True,
    )
    best_key = ranked[0] if ranked else CONTROL_KEY
    best = packs[best_key]

    lean_keep: list[str] = []
    for k in ARM_KEYS:
        if k == CONTROL_KEY:
            continue
        p = packs[k]
        if (
            _early_better(p, ctrl)
            and _dd_ok(p, ctrl)
            and not _quality_worse(p, ctrl)
        ):
            lean_keep.append(k)

    extras: dict[str, Any] = {
        "spy_asof": spy_asof,
        "spy_2012": spy_2012,
        "packs": packs,
        "best_early_key": best_key,
        "lean_keep_keys": lean_keep,
        "ctrl": ctrl,
    }
    for k, p in packs.items():
        extras[k] = p
        extras[f"ye2012_vs_ctrl_{k}"] = _rel_change(p["eq_2012"], ctrl["eq_2012"])
        extras[f"asof_vs_ctrl_{k}"] = _rel_change(p["end"], ctrl["end"])
        extras[f"dd_delta_{k}"] = p["max_dd_pct"] - ctrl["max_dd_pct"]

    path_bits = []
    for k, _frac, lab, *_ in ARM_SPEC:
        p = packs[k]
        path_bits.append(
            f"{lab} {format_money(p['eq_2010'])} / {format_money(p['eq_2011'])} / "
            f"{format_money(p['eq_2012'])} (Max DD {_fmt_pct(p['max_dd_pct'])}; "
            f"name-capped {p['n_name_capped']})"
        )
    path = (
        "2010–2012 path — "
        + "; ".join(path_bits)
        + f"; SPY {format_money(spy['years'].get(2010, {}).get('tr', 0))} / "
        f"{format_money(spy['years'].get(2011, {}).get('tr', 0))} / "
        f"{format_money(spy_2012)}."
    )
    dd_line = (
        "Full-book Max DD — "
        + "; ".join(
            f"{lab} {_fmt_pct(packs[k]['max_dd_pct'])}"
            for k, _f, lab, *_ in ARM_SPEC
        )
        + f"; SPY {_fmt_pct(spy_dd['full_dd'])}."
    )
    early_dd = (
        "Worst calendar-year Max DD in 2010–2014 — "
        + "; ".join(
            f"{lab} {_fmt_pct(packs[k]['early_worst_year_dd'])}"
            for k, _f, lab, *_ in ARM_SPEC
        )
        + "."
    )
    vs_ctrl = (
        f"Best YE2012 among candidates: {next(lab for kk,_f,lab,*_ in ARM_SPEC if kk==best_key)} "
        f"{format_money(best['eq_2012'])} vs 10% control {format_money(ctrl['eq_2012'])} "
        f"({_rel_change(best['eq_2012'], ctrl['eq_2012']):+.1%}); "
        f"Max DD {_fmt_pct(best['max_dd_pct'])} vs {_fmt_pct(ctrl['max_dd_pct'])} "
        f"({best['max_dd_pct'] - ctrl['max_dd_pct']:+.2f} pt)."
    )
    tail = (
        f"{path} {dd_line} {early_dd} {vs_ctrl} "
        "One knob (name_cap_frac) on the live-style freeze. "
        "Do not retune lids on Out-of-Sample. Not gold. Not DailyRun."
    )

    if any(packs[k]["end"] < ACCOUNT * 0.1 or packs[k]["max_dd_pct"] >= 90 for k in ARM_KEYS):
        tag = "DISMISS"
        prose = (
            f"DISMISS looser name caps that killed the account or printed ≥90% Max DD. "
            f"{tail}"
        )
        return tag, prose, extras

    if lean_keep:
        labs = [
            next(lab for kk, _f, lab, *_ in ARM_SPEC if kk == k) for k in lean_keep
        ]
        # Prefer the tightest lean-keep that still lifts early path (less concentration).
        prefer = min(lean_keep, key=lambda k: packs[k]["name_cap_frac"])
        prefer_lab = next(lab for kk, _f, lab, *_ in ARM_SPEC if kk == prefer)
        tag = "LEAN KEEP"
        prose = (
            f"LEAN KEEP research candidate {prefer_lab} "
            f"(also early-path OK: {', '.join(labs)}) versus the 10% live-style "
            f"control — early years lift without Max DD blowing out by >2 pt and "
            f"without quality collapse. Still HOLD versus gold / DailyRun "
            f"(one in-sample ladder, no walk-forward). {tail}"
        )
        return tag, prose, extras

    # Early lift but DD cost
    early_lifts = [
        k
        for k in ARM_KEYS
        if k != CONTROL_KEY and _early_better(packs[k], ctrl)
    ]
    if early_lifts and not any(_dd_ok(packs[k], ctrl) for k in early_lifts):
        tag = "HOLD"
        prose = (
            f"HOLD — looser caps ({', '.join(early_lifts)}) help the first few years "
            f"on paper, but Max DD worsens beyond the +2 pt slack vs 10% control. "
            f"Do not adopt from this one page. {tail}"
        )
        return tag, prose, extras

    if best["eq_2012"] < ctrl["eq_2012"] * 1.02:
        tag = "HOLD"
        prose = (
            f"HOLD the 10% live-style name cap — 12.5 / 15 / 17.5% do not clearly "
            f"fix the first few years enough to change the freeze "
            f"(best YE2012 {format_money(best['eq_2012'])} vs control "
            f"{format_money(ctrl['eq_2012'])}). {tail}"
        )
        return tag, prose, extras

    tag = "HOLD"
    prose = (
        f"HOLD — mixed early-path / drawdown picture versus 10% control. "
        f"Do not change the live-style freeze from this one ladder. {tail}"
    )
    return tag, prose, extras


def _headline_box(extras: dict[str, Any], tag: str) -> str:
    cls = "yes" if "KEEP" in tag else ("no" if tag == "DISMISS" else "holdtag")
    ctrl = extras["ctrl"]
    best_k = extras["best_early_key"]
    best = extras["packs"][best_k]
    best_lab = next(lab for kk, _f, lab, *_ in ARM_SPEC if kk == best_k)
    cards = []
    for k, _frac, lab, *_ in ARM_SPEC:
        p = extras["packs"][k]
        delta = extras[f"ye2012_vs_ctrl_{k}"]
        cards.append(
            f"""
    <div class="card{" card-shared" if k == CONTROL_KEY else ""}">
      <h3>{html_mod.escape(lab)} · YE2012</h3>
      <div class="metric">{format_money(p['eq_2012'])}</div>
      <div class="small">vs 10% {delta:+.1%} · Max DD {_fmt_pct(p['max_dd_pct'])}</div>
      <div class="small">2010 {format_money(p['eq_2010'])} · 2011 {format_money(p['eq_2011'])}</div>
      <div class="small">name-capped fills {p['n_name_capped']} ({_pct_of(p['n_name_capped'], p['n_fill'])})</div>
    </div>"""
        )
    return f"""
<div class="lead">
  <h2>Headline — name-cap ladder on the live-style freeze</h2>
  <p><strong class="{cls}">{html_mod.escape(tag)}</strong> · research only · not gold · not DailyRun</p>
  <p class="small">Freeze held: risk = min(1% BOM, $50k) AND shares ≤ 1% ADV20.
  One knob: per-name notional cap 10% (control) / 12.5% / 15% / 17.5%.
  Best YE2012 among candidates: <strong>{html_mod.escape(best_lab)}</strong>
  {format_money(best['eq_2012'])} vs control {format_money(ctrl['eq_2012'])}.</p>
  <div class="cards">{"".join(cards)}
  </div>
</div>"""


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
            ("vs 10% YE2012", "text"),
            ("Full Max DD%", "num"),
            ("Δ Max DD vs 10%", "num"),
        ]
    )
    ctrl = books[CONTROL_KEY]["led"]
    rows: list[tuple[Any, ...]] = [
        (
            "SPY $250k total return",
            spy["years"].get(2010, {}).get("tr"),
            spy["years"].get(2011, {}).get("tr"),
            spy_dd["eq_2012"],
            "1.00× (yardstick)",
            "—",
            spy_dd["full_dd"],
            None,
        )
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
                f"{_rel_change(led.eq_2012, ctrl.eq_2012):+.1%}"
                if k != CONTROL_KEY
                else "control",
                led.max_dd_pct,
                (led.max_dd_pct - ctrl.max_dd_pct) if k != CONTROL_KEY else 0.0,
            )
        )
    body = ""
    for name, y0, y1, y2, vs, vs10, dd, ddd in rows:
        body += (
            "<tr>"
            f"<td>{html_mod.escape(str(name))}</td>"
            f"<td>{_m(y0)}</td>"
            f"<td>{_m(y1)}</td>"
            f"<td>{_m(y2)}</td>"
            f"<td>{html_mod.escape(str(vs))}</td>"
            f"<td>{html_mod.escape(str(vs10))}</td>"
            f"<td>{_fmt_pct(dd)}</td>"
            f"<td>{'—' if ddd is None else f'{float(ddd):+.2f} pt'}</td>"
            "</tr>"
        )
    last = (
        '<tr class="total-row"><th>Pinned (10% control)</th>'
        f"<td>{format_money(ctrl.eq_2010)}</td>"
        f"<td>{format_money(ctrl.eq_2011)}</td>"
        f"<td>{format_money(ctrl.eq_2012)}</td>"
        f"<td>{html_mod.escape(_vs_spy(ctrl.eq_2012, spy_dd['eq_2012']))}</td>"
        "<td>control</td>"
        f"<td>{_fmt_pct(ctrl.max_dd_pct)}</td>"
        "<td>0.00 pt</td></tr>"
    )
    return (
        '<p class="small">Honest early path. Click headers to sort. Total row pinned.</p>'
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}{last}</tbody></table></div>"
    )


def _early_years_table(
    books: dict[str, dict[str, Any]],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
) -> str:
    """2010–2014 equity + that calendar year’s Max DD%."""
    head = f._sortable_head(
        [("Year-end", "num")]
        + [(lab, "num") for _k, _f, lab, *_ in ARM_SPEC]
        + [("SPY TR", "num")]
        + [(f"{lab} year Max DD%", "num") for _k, _f, lab, *_ in ARM_SPEC]
        + [("SPY year Max DD%", "num"), ("Note", "text")]
    )
    body = ""
    for y in EARLY_YEARS:
        cells = f"<td>{y}</td>"
        for k, *_ in ARM_SPEC:
            row = next((x for x in books[k]["years"] if x["year"] == y), None)
            cells += f"<td>{format_money(row['ending_equity']) if row else '—'}</td>"
        sy = spy["years"].get(y)
        sdd = spy_dd["years"].get(y, {})
        cells += f"<td>{format_money(sy['tr']) if sy else '—'}</td>"
        for k, *_ in ARM_SPEC:
            row = next((x for x in books[k]["years"] if x["year"] == y), None)
            cells += f"<td>{_fmt_pct(row['max_dd_pct']) if row else '—'}</td>"
        note = "headline YE2012" if y == 2012 else ""
        body += (
            f"<tr>{cells}<td>{_fmt_pct(sdd.get('max_dd_pct'))}</td>"
            f"<td class=\"small\">{html_mod.escape(note)}</td></tr>"
        )
    last = '<tr class="total-row"><th>Full-book Max DD (all years)</th>'
    for k, *_ in ARM_SPEC:
        last += f"<td>{format_money(books[k]['led'].end_equity)}</td>"
    last += f"<td>{format_money(spy['tr_end'])}</td>"
    for k, *_ in ARM_SPEC:
        last += f"<td>{_fmt_pct(books[k]['led'].max_dd_pct)}</td>"
    last += (
        f"<td>{_fmt_pct(spy_dd['full_dd'])}</td>"
        '<td class="small">Pinned as-of equity + full Max DD</td></tr>'
    )
    return (
        '<p class="small">First five calendar years — ending equity and that year’s '
        "peak-to-trough Max DD%. Click headers to sort. Footer = as-of equity + full-book Max DD.</p>"
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
            ("As-of equity", "num"),
            ("YE2012", "num"),
            ("vs 10% YE2012", "text"),
            ("Full Max DD%", "num"),
            ("Δ DD vs 10%", "num"),
            ("Worst year DD% (2010–14)", "num"),
            ("Peak name $", "num"),
            ("Peak name", "text"),
            ("Peak name %", "num"),
            ("Name-capped fills", "num"),
            ("Name-skip", "num"),
            ("Rotates", "num"),
            ("WR%", "num"),
            ("Avg PnL%", "num"),
            ("PF", "num"),
        ]
    )
    ctrl = books[CONTROL_KEY]["led"]
    body = ""
    for k, frac, lab, *_ in ARM_SPEC:
        led = books[k]["led"]
        st = books[k]["stats_full"]
        pack = _led_pack(books[k])
        body += (
            "<tr>"
            f"<td>{html_mod.escape(lab)}</td>"
            f"<td>{frac:.1%}</td>"
            f"<td>{format_money(led.end_equity)}</td>"
            f"<td>{format_money(led.eq_2012)}</td>"
            f"<td>{'control' if k == CONTROL_KEY else f'{_rel_change(led.eq_2012, ctrl.eq_2012):+.1%}'}</td>"
            f"<td>{_fmt_pct(led.max_dd_pct)}</td>"
            f"<td>{0.0 if k == CONTROL_KEY else led.max_dd_pct - ctrl.max_dd_pct:+.2f} pt</td>"
            f"<td>{_fmt_pct(pack['early_worst_year_dd'])}</td>"
            f"<td>{format_money(led.peak_name_notional)}</td>"
            f"<td>{html_mod.escape(led.peak_name_symbol or '—')}</td>"
            f"<td>{_fmt_pct(100.0 * float(led.peak_name_frac))}</td>"
            f"<td>{led.n_name_capped}</td>"
            f"<td>{led.n_skip_name}</td>"
            f"<td>{led.n_rotate}</td>"
            f"<td>{_fmt_pct(st.get('win_pct'))}</td>"
            f"<td>{_fmt_pct(st.get('avg_pnl_pct'))}</td>"
            f"<td>{st.get('pf')}</td>"
            "</tr>"
        )
    # SPY row
    body += (
        "<tr>"
        "<td>SPY $250k total return</td><td>—</td>"
        f"<td>{format_money(spy['tr_end'])}</td>"
        f"<td>{format_money(spy_dd['eq_2012'])}</td>"
        "<td>—</td>"
        f"<td>{_fmt_pct(spy_dd['full_dd'])}</td>"
        "<td>—</td><td>—</td><td>—</td><td>—</td><td>—</td>"
        "<td>—</td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td></tr>"
    )
    last = (
        '<tr class="total-row"><th>Pinned (10% control)</th>'
        "<td>10.0%</td>"
        f"<td>{format_money(ctrl.end_equity)}</td>"
        f"<td>{format_money(ctrl.eq_2012)}</td>"
        "<td>control</td>"
        f"<td>{_fmt_pct(ctrl.max_dd_pct)}</td>"
        "<td>0.00 pt</td>"
        f"<td>{_fmt_pct(_led_pack(books[CONTROL_KEY])['early_worst_year_dd'])}</td>"
        f"<td>{format_money(ctrl.peak_name_notional)}</td>"
        f"<td>{html_mod.escape(ctrl.peak_name_symbol or '—')}</td>"
        f"<td>{_fmt_pct(100.0 * float(ctrl.peak_name_frac))}</td>"
        f"<td>{ctrl.n_name_capped}</td>"
        f"<td>{ctrl.n_skip_name}</td>"
        f"<td>{ctrl.n_rotate}</td>"
        "<td>—</td><td>—</td><td>—</td></tr>"
    )
    return (
        '<p class="small">Click headers to sort. Total row pinned. '
        "Control = live-style 10% name.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}{last}</tbody></table></div>"
    )


def _year_table(
    books: dict[str, dict[str, Any]],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
) -> str:
    head = f._sortable_head(
        [("Year-end", "num")]
        + [(lab, "num") for _k, _f, lab, *_ in ARM_SPEC]
        + [("SPY total return", "num")]
        + [(f"{lab} Max DD%", "num") for _k, _f, lab, *_ in ARM_SPEC]
        + [("SPY Max DD%", "num"), ("Note", "text")]
    )
    body = ""
    for y in range(2010, ASOF.year + 1):
        cells = f"<td>{y}</td>"
        for k, *_ in ARM_SPEC:
            row = next((x for x in books[k]["years"] if x["year"] == y), None)
            cells += f"<td>{format_money(row['ending_equity']) if row else '—'}</td>"
        sy = spy["years"].get(y)
        sdd = spy_dd["years"].get(y, {})
        cells += f"<td>{format_money(sy['tr']) if sy else '—'}</td>"
        for k, *_ in ARM_SPEC:
            row = next((x for x in books[k]["years"] if x["year"] == y), None)
            cells += f"<td>{_fmt_pct(row['max_dd_pct']) if row else '—'}</td>"
        note = f"through {ASOF.isoformat()}" if y == ASOF.year else ""
        if y == 2012:
            note = "year-end 2012 headline"
        body += (
            f"<tr>{cells}<td>{_fmt_pct(sdd.get('max_dd_pct'))}</td>"
            f"<td class=\"small\">{html_mod.escape(note)}</td></tr>"
        )
    last = '<tr class="total-row"><th>Total / last</th>'
    for k, *_ in ARM_SPEC:
        last += f"<td>{format_money(books[k]['led'].end_equity)}</td>"
    last += f"<td>{format_money(spy['tr_end'])}</td>"
    for k, *_ in ARM_SPEC:
        last += f"<td>{_fmt_pct(books[k]['led'].max_dd_pct)}</td>"
    last += f"<td>{_fmt_pct(spy_dd['full_dd'])}</td><td class=\"small\">Pinned as-of</td></tr>"
    return (
        '<p class="small">Full year-end path. Click headers to sort. '
        "2010–2012 is the honest early path; later years still scale with 1%.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}{last}</tbody></table></div>"
    )


def _lid_table(books: dict[str, dict[str, Any]]) -> str:
    head = f._sortable_head(
        [
            ("Book", "text"),
            ("Fills", "num"),
            ("$50k-bound", "num"),
            ("1%-bound", "num"),
            ("ADV clipped", "num"),
            ("Name-capped", "num"),
            ("Name-capped %", "text"),
            ("Name-skip", "num"),
            ("Months at $50k", "num"),
        ]
    )
    body = ""
    for k, _frac, lab, *_ in ARM_SPEC:
        p = _led_pack(books[k])
        body += (
            "<tr>"
            f"<td>{html_mod.escape(lab)}</td>"
            f"<td>{p['n_fill']}</td>"
            f"<td>{p['n_risk_50k_bound']}</td>"
            f"<td>{p['n_risk_1pct_bound']}</td>"
            f"<td>{p['n_adv_clipped']}</td>"
            f"<td>{p['n_name_capped']}</td>"
            f"<td>{_pct_of(p['n_name_capped'], p['n_fill'])}</td>"
            f"<td>{p['n_skip_name']}</td>"
            f"<td>{p['n_months_50k']}</td>"
            "</tr>"
        )
    return (
        '<p class="small">How often each lid binds. Click headers to sort.</p>'
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def _compare_sections(books: dict[str, dict[str, Any]], verdict: str) -> str:
    col_map = {"IS": "stats_is", "OOS": "stats_oos", "FULL": "stats_full"}
    notes = {
        "IS": "In-Sample — entry before 2024-01-01. Do not retune name cap on OOS.",
        "OOS": "Out-of-Sample — report-only. Do not pick 12.5/15/17.5 from this slice.",
        "FULL": verdict,
    }
    html = ""
    for sl in ("IS", "OOS", "FULL"):
        cols = [
            (lab, books[k][col_map[sl]]) for k, _f, lab, *_ in ARM_SPEC
        ]
        html += f"""
<section>
<h2>Canonical compare · {sl}</h2>
<p class="small">{html_mod.escape(notes[sl])} Sheet / Total PnL $ omitted. Click headers to sort. Δ vs first column (10% control).</p>
<div class="table-wrap">{f._canonical_table(cols)}</div>
</section>"""
    return html


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
<title>Compare — name-cap ladder 10/12.5/15/17.5 — {STAMP}</title>
<style>{f._css()}</style></head><body>
<h1>Compare — looser name caps on the live-style freeze</h1>
<p class="sub">
Stamp <code>{STAMP}</code>. Research only. <strong>Not gold. Not DailyRun.</strong>
Generated {html_mod.escape(gen_s)}. Click column headers to sort.
</p>
{_ask_block()}
{_headline_box(extras, tag)}
<div class="hold"><strong>{html_mod.escape(verdict)}</strong></div>
<section>
<h2>2010–2012 path + drawdowns</h2>
{_path_2010_2012(books, spy, spy_dd)}
</section>
<section>
<h2>First few years (2010–2014) — equity and year Max DD%</h2>
{_early_years_table(books, spy, spy_dd)}
</section>
<section>
<h2>Books at a glance</h2>
{_lead_table(books, spy, spy_dd)}
</section>
<section>
<h2>How often each lid binds</h2>
{_lid_table(books)}
</section>
<section>
<h2>Full year-end equity and Max DD%</h2>
{_year_table(books, spy, spy_dd)}
</section>
{_compare_sections(books, verdict)}
<section>
<h2>Max drawdown definition</h2>
<p>{html_mod.escape(DD_DEF)}</p>
</section>
<section>
<h2>Data sources</h2>
<ul class="sources">{sources_html}</ul>
<p class="small">Parent freeze: <code>{PARENT.name}</code>. Monthly: <a href="monthly.html">monthly.html</a>. Not gold. Not DailyRun.</p>
</section>
{f.r.monthly._SORTABLE_TABLE_SCRIPT}
</body></html>"""


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
    for k, _frac, lab, *_ in ARM_SPEC:
        ledgers += f"""
<section>
<h2>Month ledger — {html_mod.escape(lab)}</h2>
{f._ledger_table(books[k]['snaps'], risk_col="Month risk $", bind_cols=True)}
</section>"""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Monthly — name-cap ladder 10/12.5/15/17.5 — {STAMP}</title>
<style>{f._css()}</style></head><body>
<h1>Monthly — name-cap ladder on live-style freeze</h1>
<p class="sub">
Stamp <code>{STAMP}</code>. Research only. <strong>Not gold. Not DailyRun.</strong>
Generated {html_mod.escape(gen_s)}.
</p>
{_ask_block()}
{_headline_box(extras, tag)}
<div class="hold"><strong>{html_mod.escape(verdict)}</strong></div>
<section>
<h2>2010–2012 path + drawdowns</h2>
{_path_2010_2012(books, spy, spy_dd)}
</section>
<section>
<h2>First few years (2010–2014)</h2>
{_early_years_table(books, spy, spy_dd)}
</section>
<section>
<h2>Books at a glance</h2>
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
    if isinstance(obj, float):
        return obj
    if isinstance(obj, (int, str)) or obj is None:
        return obj
    return str(obj)


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
    ctrl = extras["ctrl"]
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
        "## Freeze (held)",
        "",
        "- 5-sys: SB, RSI, VZ, MTS, RL (IND out)",
        f"- Account ${ACCOUNT:,.0f}; withdraw ${WITHDRAW:,.0f}/mo; margin {MARGIN_RATE:.1%}; leverage {LEVERAGE}×; sell-winner",
        "- risk = min(1% beginning-of-month equity, $50,000)",
        "- shares ≤ 1% ADV20",
        "- RSI size = risk / 0.0651 (IS avg-loss freeze)",
        "- **One knob:** name_cap_frac ∈ {0.10 control, 0.125, 0.15, 0.175}",
        f"- Parent: `{PARENT.name}`",
        "",
        "## Early path (2010–2012) + Max DD",
        "",
    ]
    for k, frac, lab, *_ in ARM_SPEC:
        p = extras["packs"][k]
        lines.append(
            f"- **{lab}** ({frac:.1%}): 2010 ${p['eq_2010']:,.2f}; 2011 ${p['eq_2011']:,.2f}; "
            f"2012 ${p['eq_2012']:,.2f}; as-of ${p['end']:,.2f}; "
            f"Max DD {_fmt_pct(p['max_dd_pct'])} "
            f"(peak ${p['max_dd_peak']:,.2f} → trough ${p['max_dd_trough']:,.2f}); "
            f"worst year DD 2010–14 {_fmt_pct(p['early_worst_year_dd'])}; "
            f"name-capped {p['n_name_capped']}; vs 10% YE2012 "
            f"{extras[f'ye2012_vs_ctrl_{k}']:+.1%}; Δ Max DD "
            f"{extras[f'dd_delta_{k}']:+.2f} pt."
        )
    lines += [
        "",
        f"- SPY YE2012 ${spy_dd['eq_2012']:,.2f}; as-of ${spy['tr_end']:,.2f}; "
        f"Max DD {_fmt_pct(spy_dd['full_dd'])}.",
        "",
        "## Selection bias note",
        "",
        "Ladder judged in-sample on early path + Max DD vs 10% control. "
        "OOS is report-only. LEAN KEEP ≠ gold ≠ DailyRun.",
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

## One knob
`name_cap_frac` on the live-style freeze (1%+$50k + 1% ADV20). Control = 10%.

## Arms
10% / 12.5% / 15% / 17.5%

## Question
Does a slightly looser per-name notional lid fix the weak first few years without
worsening Max Drawdown (Max DD) too much?

## Tag
{tag}

## Verdict
{verdict}

## Anti-overfit
Do not retune on OOS. Research only. Not gold. Not DailyRun.
"""
    (OUT_DIR / "HYPOTHESIS.md").write_text(text, encoding="utf-8")


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
    spy = f.spy_buyhold()
    spy_dd = m.spy_paths(spy)
    print(
        f"[SPY] {spy['start_date']} -> {spy['end_date']} "
        f"TR {spy['tr_end']:.2f} YE2012={spy_dd['eq_2012']:.2f} "
        f"MaxDD={spy_dd['full_dd']:.2f}%",
        flush=True,
    )

    static = f.load_static(FIVE)
    sources = [
        f"overlays: {f.PREV_DIR.name} (RSI = RSI_overlay_avgloss.csv IS 6.51% freeze)",
        f"5-sys: {', '.join(FIVE)} — Indicators (IND) out",
        f"SPY: {f.SPY_PATH.as_posix()} Adj Close total return + Close price-only",
        "wallet: tools/risk2500_five_sys_20260917.py run_wallet",
        "live-style freeze held: risk=min(1% BOM, $50k) AND shares≤1% ADV20",
        "one knob: name_cap_frac 0.10 (control) / 0.125 / 0.15 / 0.175",
        f"parent control stamp: {PARENT.name}",
        "focus: 2010–2012 / first few years + Max DD",
        DD_DEF,
    ]

    books: dict[str, dict[str, Any]] = {}
    for key, frac, label, _cap, csv_name in ARM_SPEC:
        print(f"[arm] {key} name_cap={frac:.1%} …", flush=True)
        arm = _run_one(static, name_cap=frac, label=label)
        arm["short"] = arm["label"]
        arm["read"] = "One knob on live-style freeze. Research only."
        books[key] = arm
        f.r.write_overlay_csv(arm["trades"], OUT_DIR / csv_name)
        led = arm["led"]
        print(
            f"[arm] {key} YE2012={led.eq_2012:.2f} asof={led.end_equity:.2f} "
            f"MaxDD={led.max_dd_pct:.2f}% name_capped={led.n_name_capped}",
            flush=True,
        )

    tag, verdict, extras = _verdict(books, spy, spy_dd)
    print(f"[verdict] {tag}", flush=True)
    print(verdict, flush=True)

    now = datetime.now(tz=ET)
    (OUT_DIR / "monthly.html").write_text(
        build_monthly(
            books=books,
            spy=spy,
            spy_dd=spy_dd,
            tag=tag,
            verdict=verdict,
            extras=extras,
            sources=sources,
            generated=now,
        ),
        encoding="utf-8",
    )
    (OUT_DIR / "compare.html").write_text(
        build_compare(
            books=books,
            spy=spy,
            spy_dd=spy_dd,
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
        "arms": {k: extras["packs"][k] for k in ARM_KEYS},
        "best_early_key": extras["best_early_key"],
        "lean_keep_keys": extras["lean_keep_keys"],
        "extras": _jsonable({k: v for k, v in extras.items() if k != "packs"}),
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"wrote {OUT_DIR / 'compare.html'}", flush=True)
    print(f"wrote {OUT_DIR / 'monthly.html'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
