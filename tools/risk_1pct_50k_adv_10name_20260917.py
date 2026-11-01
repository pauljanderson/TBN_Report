#!/usr/bin/env python3
"""5-sys live-style freeze: 1%+$50k + 1% ADV20 + 10% per-name (research only).

Paul's correction: the 10% per-name notional lid is part of the system, not a
later yes/no. This stamp is the book he wants.

    drive/paul_experiments/risk_1pct_50k_adv_10name_20260917/

Sibling two-lid control (no 10% name) is owned by another job:

    drive/paul_experiments/risk_1pct_50k_adv_20260917/

Do not overwrite that stamp's two-lid book. If that compare.html is stable when
this job finishes, attach this 10% arm there; always write this folder.

Same 5-sys (SB, RSI, VZ, MTS, RL), $7,500/mo, 10.5%, 2×, sell-winner, RSI
6.51% IS avg-loss. IND out. Not gold. Not DailyRun.
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

STAMP = "risk_1pct_50k_adv_10name_20260917"
OUT_DIR = REPO / "drive" / "paul_experiments" / STAMP
SIBLING = REPO / "drive" / "paul_experiments" / "risk_1pct_50k_adv_20260917"
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
NAME_CAP = 0.10
FIVE = f.FIVE
FIVE_RANK = f.FIVE_RANK
DD_DEF = m.DD_DEF
HUGE = 10_000_000.0
TRILLION = 1.0e12

# Published frozen $2,500 (no name cap) — reuse, do not re-run.
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
    "i thought we agreed having the 10% per name cap was useful and that should "
    "be part of our system. Put 10% per-name notional in the live-style freeze, "
    "not a later yes/no. Same book as the 1%+$50k and 1% ADV two-lid run: "
    "risk = min(1% beginning-of-month equity, $50k) AND shares ≤ 1% of 20-day "
    "average daily volume (ADV20) AND notional ≤ 10% of current equity. "
    "5-sys (SB, RSI, VZ, MTS, RL), $7,500/mo, 10.5% margin, 2×, sell-winner "
    "when no buying power, RSI 6.51% average-loss freeze. Indicators (IND) out. "
    "Print year-end 2012 + as-of versus S&P 500 tracker (SPY) and versus the "
    "two-lid book (no 10% name). How often each lid binds ($50k vs ADV vs 10% "
    "name). HOLD/KEEP versus frozen $2,500 and versus SPY. Not gold. Not DailyRun."
)
PLAIN_ENGLISH = (
    "Paul’s correction: the 10% per-name lid is in this book, not a later "
    "yes/no. Same five sleeves — StockBee (SB), Relative Strength Index (RSI), "
    "Volume Zone (VZ), Magic Touch (MTS), Rocket Launcher (RL). Indicators "
    "(IND) is out. Start $250,000 in one wallet. Pull $7,500 cash on the 1st. "
    "Pay 10.5% a year on whatever you borrowed. Open stock cost can be at most "
    "twice the account. Each month the dollars you may lose to the stop are "
    "the smaller of 1% of the account and $50,000. RSI dollars in = that "
    "month’s risk ÷ 0.0651 (In-Sample average-loser freeze; do not retune "
    "after 2024); other systems shares = risk ÷ (entry − stop). Then two more "
    "lids that are part of the live recipe: you may not buy more than 1% of "
    "that name’s last 20-session average daily share volume, and one ticker "
    "may not hold more than 10% of whatever the account is worth right then. "
    "When a new signal still cannot fit, sell the most profitable open name, "
    "then take the new one. The two-lid sibling (1%+$50k and ADV only, no 10% "
    "name) stays as a control — we do not undo that page. Frozen $2,500 is "
    "the already-HOLD flat-dollar book (risk never grows). Read year-end 2012 "
    "and today versus S&P 500 tracker (SPY). Not gold. Not DailyRun."
)

ARM_SPEC: list[tuple[str, Optional[float], str, str, str]] = [
    (
        "twolid",
        None,
        "5-sys · 1%+$50k · 1% ADV (no 10% name)",
        "Two-lid control — risk = min(1% BOM, $50k) and shares ≤ 1% ADV20. No per-name notional lid.",
        "ALL_overlay_5sys_1pct_50k_adv_twolid.csv",
    ),
    (
        "threelid",
        0.10,
        "5-sys · 1%+$50k · 1% ADV · 10% name",
        "Live-style freeze — risk = min(1% BOM, $50k) AND shares ≤ 1% ADV20 AND notional ≤ 10% of current equity.",
        "ALL_overlay_5sys_1pct_50k_adv_10name.csv",
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
    for k in (
        "end",
        "eq_2010",
        "eq_2011",
        "eq_2012",
        "max_dd_pct",
        "peak_reserved",
        "peak_name",
        "peak_name_symbol",
        "n_rotate",
        "n_name_capped",
        "n_skip_name",
    ):
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
        "n_adv_missing": int(led.n_adv_missing),
        "n_adv_last_known": int(led.n_adv_last_known),
        "n_skip_adv": int(led.n_skip_adv),
        "interest": float(led.interest),
        "withdrawals": float(led.withdrawals),
        "identity": float(led.identity_err),
        "wr": _num(st, "win_pct"),
        "avg": _num(st, "avg_pnl_pct"),
        "pf": _num(st, "pf"),
        "n": _num(st, "n"),
    }


def _pct_of(n: int, den: int) -> str:
    if den <= 0:
        return "—"
    return f"{100.0 * n / den:.1f}%"


def _rel_change(a: float, b: float) -> float:
    if abs(b) < 1e-9:
        return 0.0
    return (a - b) / abs(b)


def _quality_worse(cand: dict[str, Any], ctrl: dict[str, Any]) -> bool:
    return (
        cand["wr"] + 0.25 < ctrl["wr"]
        and cand["avg"] + 0.25 < ctrl["avg"]
        and cand["max_dd_pct"] > ctrl["max_dd_pct"] + 2.0
    )


def _name_changed(three: dict[str, Any], two: dict[str, Any]) -> bool:
    if three["n_name_capped"] > 0 or three["n_skip_name"] > 0:
        return True
    if abs(_rel_change(three["end"], two["end"])) >= 0.05:
        return True
    if abs(_rel_change(three["eq_2012"], two["eq_2012"])) >= 0.05:
        return True
    if abs(three["peak_name_frac"] - two["peak_name_frac"]) >= 0.02:
        return True
    return False


def _verdict(
    books: dict[str, dict[str, Any]],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
    frozen: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    two = _led_pack(books["twolid"])
    three = _led_pack(books["threelid"])
    spy_asof = float(spy["tr_end"])
    spy_2012 = float(spy_dd["eq_2012"])
    fz_asof = float(frozen["end"])
    fz_2012 = float(frozen["eq_2012"])
    changed = _name_changed(three, two)
    qw = _quality_worse(three, two)
    trillion_died = three["end"] < TRILLION and three["peak_reserved"] < TRILLION
    still_huge = three["end"] >= HUGE
    account_dead = three["end"] < ACCOUNT * 0.1 or three["max_dd_pct"] >= 90.0
    extras: dict[str, Any] = {
        "spy_asof": spy_asof,
        "spy_2012": spy_2012,
        "twolid": two,
        "threelid": three,
        "frozen": frozen,
        "name_changed": changed,
        "quality_worse": qw,
        "trillion_died": trillion_died,
        "still_huge": still_huge,
        "account_dead": account_dead,
        "ye2012_vs_spy": _vs_spy(three["eq_2012"], spy_2012),
        "asof_vs_spy": _vs_spy(three["end"], spy_asof),
        "ye2012_vs_two": _rel_change(three["eq_2012"], two["eq_2012"]),
        "asof_vs_two": _rel_change(three["end"], two["end"]),
        "asof_vs_frozen": _rel_change(three["end"], fz_asof),
        "ye2012_vs_frozen": _rel_change(three["eq_2012"], fz_2012),
    }

    lids = (
        f"Lids on the 10% book — $50k bound fills {three['n_risk_50k_bound']} "
        f"({_pct_of(three['n_risk_50k_bound'], three['n_fill'])} of fills; "
        f"{three['n_months_50k']} months at the $50k ceiling); "
        f"1% bound fills {three['n_risk_1pct_bound']} "
        f"({_pct_of(three['n_risk_1pct_bound'], three['n_fill'])}); "
        f"ADV clipped {three['n_adv_clipped']} "
        f"({_pct_of(three['n_adv_clipped'], three['n_fill'])}; "
        f"ADV skip {three['n_skip_adv']}; last-known {three['n_adv_last_known']}); "
        f"10% name-capped fills {three['n_name_capped']} "
        f"({_pct_of(three['n_name_capped'], three['n_fill'])}; "
        f"name-skip {three['n_skip_name']}). "
        f"Two-lid (no 10% name): $50k {two['n_risk_50k_bound']}, "
        f"ADV clip {two['n_adv_clipped']}, name-capped 0."
    )
    path = (
        f"2010–2012 path — 10% book {format_money(three['eq_2010'])} / "
        f"{format_money(three['eq_2011'])} / {format_money(three['eq_2012'])}; "
        f"two-lid {format_money(two['eq_2010'])} / {format_money(two['eq_2011'])} / "
        f"{format_money(two['eq_2012'])}; "
        f"frozen $2,500 {format_money(frozen['eq_2010'])} / "
        f"{format_money(frozen['eq_2011'])} / {format_money(fz_2012)}; "
        f"SPY {format_money(spy['years'].get(2010, {}).get('tr', 0))} / "
        f"{format_money(spy['years'].get(2011, {}).get('tr', 0))} / "
        f"{format_money(spy_2012)}."
    )
    vs_two = (
        f"10% vs two-lid: year-end 2012 {format_money(three['eq_2012'])} vs "
        f"{format_money(two['eq_2012'])} ({_rel_change(three['eq_2012'], two['eq_2012']):+.1%}); "
        f"as-of {format_money(three['end'])} vs {format_money(two['end'])} "
        f"({_rel_change(three['end'], two['end']):+.1%}); "
        f"peak name {format_money(three['peak_name'])} {three['peak_name_symbol']} "
        f"({three['peak_name_frac']:.1%}) vs {format_money(two['peak_name'])} "
        f"{two['peak_name_symbol']} ({two['peak_name_frac']:.1%}). "
        + (
            "The 10% lid bound fills — it is not slack. "
            if changed
            else "The 10% lid barely moved the two-lid path. "
        )
    )
    vs_fz = (
        f"vs frozen $2,500: year-end 2012 {format_money(three['eq_2012'])} vs "
        f"{format_money(fz_2012)}; as-of {format_money(three['end'])} vs "
        f"{format_money(fz_asof)}; Max DD {_fmt_pct(three['max_dd_pct'])} vs "
        f"{_fmt_pct(float(frozen['max_dd_pct']))}."
    )
    vs_spy = (
        f"10% book year-end 2012 {format_money(three['eq_2012'])} vs SPY "
        f"{format_money(spy_2012)} ({_vs_spy(three['eq_2012'], spy_2012)}); "
        f"as-of {format_money(three['end'])} vs SPY {format_money(spy_asof)} "
        f"({_vs_spy(three['end'], spy_asof)})."
    )
    tail = (
        f"{lids} {vs_two}{vs_fz} {vs_spy} {path} "
        "10% name is in this freeze. Do not retune lids on Out-of-Sample. "
        "Not gold. Not DailyRun."
    )

    if account_dead:
        tag = "DISMISS"
        prose = (
            f"DISMISS this live-style freeze versus SPY and versus frozen $2,500 — "
            f"the 10% book died or could not pay the $7,500 wires "
            f"(as-of {format_money(three['end'])}; Max DD {_fmt_pct(three['max_dd_pct'])}; "
            f"withdrawn {format_money(three['withdrawals'])}). {tail}"
        )
        return tag, prose, extras

    if qw and not changed:
        tag = "HOLD"
        prose = (
            f"HOLD versus the two-lid book, frozen $2,500, and SPY. Quality "
            f"softened and the 10% lid did not change the path. {tail}"
        )
        return tag, prose, extras

    if still_huge:
        tag = "HOLD"
        prose = (
            f"HOLD versus gold / DailyRun and versus frozen $2,500 as a live "
            f"recipe — 10% name is in this book, but as-of {format_money(three['end'])} "
            f"is still not a Fidelity-sized ending (1% still scales until equity "
            f"hits $5M, then $50k). vs SPY: year-end 2012 "
            f"{'beats' if three['eq_2012'] >= spy_2012 else 'loses to'} SPY; "
            f"as-of {'beats' if three['end'] >= spy_asof else 'loses to'} SPY. "
            f"{tail}"
        )
        return tag, prose, extras

    if (
        three["eq_2012"] >= spy_2012 * 0.9
        and three["end"] >= spy_asof * 0.9
        and three["max_dd_pct"] <= two["max_dd_pct"] + 2.0
        and not qw
        and trillion_died
    ):
        tag = "KEEP"
        prose = (
            f"KEEP the 10% name lid as part of this live-style freeze "
            f"(research candidate only) versus SPY and versus the two-lid book "
            f"— year-end 2012 and as-of stay in a human range, quality did not "
            f"collapse, and the 10% lid is in the system"
            f"{' and it bound fills' if changed else ''}. "
            f"Still HOLD versus gold / DailyRun (one in-sample freeze, no "
            f"walk-forward). Frozen $2,500 remains the flatter-dollar sibling "
            f"(as-of {format_money(fz_asof)}). {tail}"
        )
        return tag, prose, extras

    tag = "HOLD"
    prose = (
        f"HOLD versus gold / DailyRun. 10% name is in this book. "
        f"vs SPY and vs two-lid / frozen $2,500 the picture is mixed — do not "
        f"adopt from this one page. {tail}"
    )
    return tag, prose, extras


def _headline_box(
    extras: dict[str, Any],
    tag: str,
) -> str:
    cls = "yes" if tag == "KEEP" else ("no" if tag == "DISMISS" else "holdtag")
    three = extras["threelid"]
    two = extras["twolid"]
    fz = extras["frozen"]
    return f"""
<div class="lead">
  <h2>Headline — 10% name is in this book</h2>
  <p><strong class="{cls}">{html_mod.escape(tag)}</strong> · research only · not gold · not DailyRun</p>
  <p class="small">Live-style freeze: risk = min(1% beginning-of-month equity, $50k)
  AND shares ≤ 1% ADV20 AND notional ≤ 10% of current equity. The two-lid sibling
  (no 10% name) is the control, not a replacement.</p>
  <div class="cards">
    <div class="card card-shared">
      <h3>10% book · year-end 2012 vs SPY</h3>
      <div class="metric">{format_money(three['eq_2012'])}</div>
      <div class="small">SPY {format_money(extras['spy_2012'])} ·
      {_vs_spy(three['eq_2012'], extras['spy_2012'])}</div>
    </div>
    <div class="card card-shared">
      <h3>10% book · as-of {ASOF.isoformat()} vs SPY</h3>
      <div class="metric">{format_money(three['end'])}</div>
      <div class="small">SPY {format_money(extras['spy_asof'])} ·
      {_vs_spy(three['end'], extras['spy_asof'])}</div>
    </div>
    <div class="card">
      <h3>Did 10% change the two-lid book?</h3>
      <div class="metric">{"YES" if extras["name_changed"] else "NO"}</div>
      <div class="small">As-of {format_money(three['end'])} vs two-lid
      {format_money(two['end'])} ({extras['asof_vs_two']:+.1%})</div>
      <div class="small">YE2012 {format_money(three['eq_2012'])} vs
      {format_money(two['eq_2012'])} ({extras['ye2012_vs_two']:+.1%})</div>
      <div class="small">Name-capped fills {three['n_name_capped']} ·
      name-skip {three['n_skip_name']}</div>
    </div>
    <div class="card">
      <h3>vs frozen $2,500</h3>
      <div class="metric">{format_money(float(fz['end']))}</div>
      <div class="small">Frozen YE2012 {format_money(float(fz['eq_2012']))} ·
      as-of {format_money(float(fz['end']))}</div>
      <div class="small">10% book as-of Δ {extras['asof_vs_frozen']:+.1%} ·
      YE2012 Δ {extras['ye2012_vs_frozen']:+.1%}</div>
      <div class="small">Frozen stamp was {html_mod.escape(str(fz.get('tag', 'HOLD')))}
      — not gold</div>
    </div>
    <div class="card">
      <h3>Which lid binds (10% book)</h3>
      <div class="metric">{three['n_name_capped']} name</div>
      <div class="small">$50k fills {three['n_risk_50k_bound']}
      ({_pct_of(three['n_risk_50k_bound'], three['n_fill'])}) ·
      {three['n_months_50k']} months at ceiling</div>
      <div class="small">ADV clip {three['n_adv_clipped']}
      ({_pct_of(three['n_adv_clipped'], three['n_fill'])}) ·
      ADV skip {three['n_skip_adv']}</div>
      <div class="small">1% binds {three['n_risk_1pct_bound']}
      ({_pct_of(three['n_risk_1pct_bound'], three['n_fill'])})</div>
    </div>
    <div class="card">
      <h3>Peak single-name notional</h3>
      <div class="metric">{format_money(three['peak_name'])}</div>
      <div class="small">10% book {html_mod.escape(three['peak_name_symbol'])} ·
      {three['peak_name_frac']:.1%} of equity</div>
      <div class="small">Two-lid {format_money(two['peak_name'])}
      {html_mod.escape(two['peak_name_symbol'])} · {two['peak_name_frac']:.1%}</div>
      <div class="small">Frozen $2,500 {format_money(float(fz['peak_name']))}
      {html_mod.escape(str(fz.get('peak_name_symbol') or '—'))}</div>
    </div>
    <div class="card">
      <h3>Max DD%</h3>
      <div class="metric">{_fmt_pct(three['max_dd_pct'])}</div>
      <div class="small">Two-lid {_fmt_pct(two['max_dd_pct'])} ·
      frozen {_fmt_pct(float(fz['max_dd_pct']))}</div>
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
    frozen: dict[str, Any],
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
            ("$50k bound fills", "num"),
            ("ADV clipped", "num"),
            ("10% name-capped", "num"),
            ("Name-skip / ADV-skip / BP-skip", "text"),
            ("Interest", "num"),
            ("Withdrawn", "num"),
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
            0,
            0,
            0,
            "0 / 0 / 0",
            0.0,
            0.0,
        ),
        (
            "Frozen $2,500 (published, no name cap)",
            "Flat $2,500 risk every month — already HOLD; reuse, not re-run",
            frozen["end"],
            frozen["eq_2010"],
            frozen["eq_2011"],
            frozen["eq_2012"],
            frozen["max_dd_pct"],
            _vs_spy(float(frozen["end"]), spy["tr_end"]),
            frozen["peak_reserved"],
            frozen["peak_name"],
            frozen.get("peak_name_symbol") or "—",
            None,
            None,
            None,
            frozen.get("n_name_capped", 0),
            f"{frozen.get('n_rotate', '—')} / — / —",
            None,
            None,
        ),
    ]
    caps = {k: cap for k, _frac, _lab, cap, _csv in ARM_SPEC}
    for key in ("twolid", "threelid"):
        a = books[key]
        led = a["led"]
        rows.append(
            (
                a["label"],
                caps[key],
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
                led.n_risk_50k_bound,
                led.n_adv_clipped,
                led.n_name_capped,
                f"{led.n_skip_name} / {led.n_skip_adv} / {led.n_skip_bp}",
                led.interest,
                led.withdrawals,
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
            n50,
            nadv,
            ncap,
            sk,
            interest,
            wd,
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
            f"<td>{_fmt_pct(100.0 * float(pfrac)) if pfrac is not None else '—'}</td>"
            f"<td>{'—' if n50 is None else int(n50)}</td>"
            f"<td>{'—' if nadv is None else int(nadv)}</td>"
            f"<td>{int(ncap) if ncap is not None else '—'}</td>"
            f"<td>{html_mod.escape(str(sk))}</td>"
            f"<td>{_m(interest) if interest is not None else '—'}</td>"
            f"<td>{_m(wd) if wd is not None else '—'}</td>"
            "</tr>"
        )
    last_led = books["threelid"]["led"]
    last = (
        '<tr class="total-row"><th>As-of / last (10% name book)</th>'
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
        f"<td>{last_led.n_risk_50k_bound}</td>"
        f"<td>{last_led.n_adv_clipped}</td>"
        f"<td>{last_led.n_name_capped}</td>"
        f"<td>{last_led.n_skip_name} / {last_led.n_skip_adv} / {last_led.n_skip_bp}</td>"
        f"<td>{format_money(last_led.interest)}</td>"
        f"<td>{format_money(last_led.withdrawals)}</td></tr>"
    )
    return (
        '<p class="small">Click column headers to sort. Total row pinned. '
        "Dollar fields are uncapped ($nnn,nnn.nn). Two-lid is the no-10% control. "
        "Frozen $2,500 is published reuse.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}{last}</tbody></table></div>"
    )


def _lid_table(books: dict[str, dict[str, Any]]) -> str:
    head = f._sortable_head(
        [
            ("Book", "text"),
            ("Sized fills", "num"),
            ("1% risk bound", "num"),
            ("1% of fills", "text"),
            ("$50k risk bound", "num"),
            ("$50k of fills", "text"),
            ("Months at $50k", "num"),
            ("ADV clipped", "num"),
            ("ADV of fills", "text"),
            ("ADV skip", "num"),
            ("ADV last-known", "num"),
            ("10% name-capped", "num"),
            ("10% of fills", "text"),
            ("Name-skip", "num"),
            ("BP-skip", "num"),
            ("Rotates", "num"),
        ]
    )
    body = ""
    for key, _frac, _lab, _cap, _csv in ARM_SPEC:
        p = _led_pack(books[key])
        body += (
            "<tr>"
            f"<td>{html_mod.escape(books[key]['label'])}</td>"
            f"<td>{p['n_fill']}</td>"
            f"<td>{p['n_risk_1pct_bound']}</td>"
            f"<td>{_pct_of(p['n_risk_1pct_bound'], p['n_fill'])}</td>"
            f"<td>{p['n_risk_50k_bound']}</td>"
            f"<td>{_pct_of(p['n_risk_50k_bound'], p['n_fill'])}</td>"
            f"<td>{p['n_months_50k']}</td>"
            f"<td>{p['n_adv_clipped']}</td>"
            f"<td>{_pct_of(p['n_adv_clipped'], p['n_fill'])}</td>"
            f"<td>{p['n_skip_adv']}</td>"
            f"<td>{p['n_adv_last_known']}</td>"
            f"<td>{p['n_name_capped']}</td>"
            f"<td>{_pct_of(p['n_name_capped'], p['n_fill'])}</td>"
            f"<td>{p['n_skip_name']}</td>"
            f"<td>{p['n_skip_bp']}</td>"
            f"<td>{p['n_rotate']}</td>"
            "</tr>"
        )
    three = _led_pack(books["threelid"])
    last = (
        '<tr class="total-row"><th>Pinned (10% name book)</th>'
        f"<td>{three['n_fill']}</td>"
        f"<td>{three['n_risk_1pct_bound']}</td>"
        f"<td>{_pct_of(three['n_risk_1pct_bound'], three['n_fill'])}</td>"
        f"<td>{three['n_risk_50k_bound']}</td>"
        f"<td>{_pct_of(three['n_risk_50k_bound'], three['n_fill'])}</td>"
        f"<td>{three['n_months_50k']}</td>"
        f"<td>{three['n_adv_clipped']}</td>"
        f"<td>{_pct_of(three['n_adv_clipped'], three['n_fill'])}</td>"
        f"<td>{three['n_skip_adv']}</td>"
        f"<td>{three['n_adv_last_known']}</td>"
        f"<td>{three['n_name_capped']}</td>"
        f"<td>{_pct_of(three['n_name_capped'], three['n_fill'])}</td>"
        f"<td>{three['n_skip_name']}</td>"
        f"<td>{three['n_skip_bp']}</td>"
        f"<td>{three['n_rotate']}</td></tr>"
    )
    return (
        '<p class="small">How often each lid binds. A fill can trip more than '
        "one lid ($50k is the monthly risk ceiling when 1% of beginning-of-month "
        "equity exceeds $50k; ADV clips shares; 10% clips that ticker’s open "
        "notional). Click headers to sort. Total row pinned.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}{last}</tbody></table></div>"
    )


def _year_table(
    books: dict[str, dict[str, Any]],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
) -> str:
    labels = [
        ("twolid", "Two-lid (no 10% name)"),
        ("threelid", "10% name book"),
    ]
    head = f._sortable_head(
        [("Year-end", "num")]
        + [(lab, "num") for _k, lab in labels]
        + [
            ("SPY total return", "num"),
            ("Two-lid Max DD%", "num"),
            ("10% name Max DD%", "num"),
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
    frozen: dict[str, Any],
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
        ),
        (
            "Frozen $2,500 (published)",
            frozen["eq_2010"],
            frozen["eq_2011"],
            frozen["eq_2012"],
            _vs_spy(float(frozen["eq_2012"]), spy_dd["eq_2012"]),
        ),
    ]
    for key, lab in (
        ("twolid", "Two-lid (no 10% name)"),
        ("threelid", "10% name book"),
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
    last_led = books["threelid"]["led"]
    last = (
        '<tr class="total-row"><th>Pinned (10% name)</th>'
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
    keys_order = ["twolid", "threelid"]
    labs = {
        "twolid": "Two-lid EOM",
        "threelid": "10% name EOM",
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
        "IS": "In-Sample — entry before 2024-01-01. Path is continuous; do not retune lids on OOS.",
        "OOS": "Out-of-Sample — report-only. Do not pick 10% name from this slice.",
        "FULL": verdict,
    }
    html = ""
    for sl in ("IS", "OOS", "FULL"):
        cols = [
            ("Two-lid (no 10% name)", books["twolid"][col_map[sl]]),
            ("10% name book", books["threelid"][col_map[sl]]),
        ]
        html += f"""
<section>
<h2>Canonical compare · {sl}</h2>
<p class="small">{html_mod.escape(notes[sl])} Sheet / Total PnL $ omitted. Click headers to sort. Δ vs two-lid.</p>
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


def _sibling_note() -> str:
    if (SIBLING / "compare.html").exists():
        return (
            f'<p class="small">Two-lid sibling stamp (do not revert): '
            f'<a href="../risk_1pct_50k_adv_20260917/compare.html">'
            f"risk_1pct_50k_adv_20260917</a>. This page re-ran the same two-lid "
            f"identity so the 10% arm sits on one table. Frozen $2,500: "
            f'<a href="../risk2500_frozen_20260917/compare.html">'
            f"risk2500_frozen_20260917</a>.</p>"
        )
    return (
        '<p class="small">Two-lid sibling stamp '
        "<code>risk_1pct_50k_adv_20260917</code> was still running when this "
        "page was written — that book is the official no-10% control and is "
        "not overwritten. This page re-ran the same two-lid identity for the "
        "compare. Frozen $2,500: "
        '<a href="../risk2500_frozen_20260917/compare.html">'
        "risk2500_frozen_20260917</a>.</p>"
    )


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
    for key, _frac, _lab, cap, _csv in ARM_SPEC:
        ledgers += f"""
<section>
<h2>Ledger — {html_mod.escape(books[key]['label'])}</h2>
<p class="small">{html_mod.escape(cap)}. Click headers to sort.</p>
{f._ledger_table(books[key]['snaps'], risk_col="Month risk $", bind_cols=True)}
</section>"""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>5-sys 1%+$50k + 1% ADV + 10% name — {STAMP}</title>
<style>{f._css()}</style></head><body>
<h1>Monthly Backtest Report — {ASOF.year} · 10% name is in the live-style freeze</h1>
<p class="sub">
Stamp <code>{STAMP}</code>. Research only. <strong>Not gold. Not DailyRun.</strong>
Indicators (IND) out. Generated {html_mod.escape(gen_s)}. Click column headers to sort.
Dollar fields uncapped.
</p>
{_ask_block()}
{_headline_box(extras, tag)}
<div class="hold"><strong>{html_mod.escape(verdict)}</strong></div>
<div class="warn">
<strong>2010–2012 first.</strong> 10% name is part of this freeze (Paul’s correction).
The two-lid sibling without 10% name is a control, not the live recipe.
Later-year paper dollars can still be capacity fiction — 1% still scales until
the account is $5M, then the $50k lid binds.
</div>
<section>
<h2>2010–2012 path</h2>
{_path_2010_2012(books, spy, spy_dd, frozen)}
</section>
<section>
<h2>Books + SPY at a glance</h2>
{_lead_table(books, spy, spy_dd, frozen)}
</section>
<section>
<h2>How often each lid binds</h2>
{_lid_table(books)}
</section>
<section>
<h2>Year-end equity and Max DD%</h2>
{_year_table(books, spy, spy_dd)}
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
{_sibling_note()}
<p class="small">Compare: <a href="compare.html">compare.html</a>.
Acronyms first use: StockBee (SB); Relative Strength Index (RSI);
Volume Zone (VZ); Magic Touch (MTS); Rocket Launcher (RL);
Indicators (IND); average daily volume (ADV); beginning-of-month (BOM);
buying power (BP); In-Sample (IS); Out-of-Sample (OOS);
S&amp;P 500 tracker (SPY); year-end (YE).</p>
</section>
{f.r.monthly._SORTABLE_TABLE_SCRIPT}
</body></html>"""


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
<title>Compare — 1%+$50k + ADV + 10% name vs two-lid vs SPY — {STAMP}</title>
<style>{f._css()}</style></head><body>
<h1>Compare — 10% name is in the live-style freeze</h1>
<p class="sub">
Stamp <code>{STAMP}</code>. Research only. <strong>Not gold. Not DailyRun.</strong>
Generated {html_mod.escape(gen_s)}. Click column headers to sort. Dollar fields uncapped.
</p>
{_ask_block()}
{_headline_box(extras, tag)}
<div class="hold"><strong>{html_mod.escape(verdict)}</strong></div>
<section>
<h2>2010–2012 path</h2>
{_path_2010_2012(books, spy, spy_dd, frozen)}
</section>
<section>
<h2>Books + SPY at a glance</h2>
{_lead_table(books, spy, spy_dd, frozen)}
</section>
<section>
<h2>How often each lid binds</h2>
{_lid_table(books)}
</section>
<section>
<h2>Year-end equity and Max DD%</h2>
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
{_sibling_note()}
<p class="small">Monthly: <a href="monthly.html">monthly.html</a>. Not gold. Not DailyRun.</p>
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
        f"fills {led.n_full + led.n_scaled} (full {led.n_full} / scaled {led.n_scaled}); "
        f"$50k-bound {led.n_risk_50k_bound}; 1%-bound {led.n_risk_1pct_bound}; "
        f"months at $50k {led.n_months_50k}; ADV clip {led.n_adv_clipped}; "
        f"ADV skip {led.n_skip_adv}; ADV last-known {led.n_adv_last_known}; "
        f"name-capped {led.n_name_capped}; name-skip {led.n_skip_name}; "
        f"BP-skip {led.n_skip_bp}; "
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
    frozen: dict[str, Any],
    tag: str,
    verdict: str,
    extras: dict[str, Any],
    sources: list[str],
    attached_sibling: bool,
) -> None:
    three = extras["threelid"]
    two = extras["twolid"]
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
        "- **10% per-name notional is in the live-style freeze** (Paul’s correction — not a later yes/no).",
        "- Freeze: `risk = min(1% BOM equity, $50k)` AND `shares ≤ 1% ADV20` AND `notional ≤ 10% of current Closed-only equity`.",
        "- Control on this page = same book **without** the 10% name lid (two-lid). Official two-lid sibling stamp: `risk_1pct_50k_adv_20260917` (do not revert).",
        f"- Sibling compare attach this run: **{'yes' if attached_sibling else 'no — sibling not stable / not present; this folder is the 10% book'}**.",
        "- Frozen $2,500 = published `risk2500_frozen_20260917` (reuse, not re-run).",
        "- 5-sys: StockBee (SB), Relative Strength Index (RSI), Volume Zone (VZ), Magic Touch (MTS), Rocket Launcher (RL). IND out.",
        "- Start $250,000; one wallet; $7,500 cash on the 1st; 10.5% actual/365 on debit; open notional ≤ 2× equity.",
        "- RSI: invested = risk_dollar / 0.06509607 (In-Sample avg-loss freeze; do not retune OOS).",
        "- Others: shares = risk_dollar / (entry − stop), then ADV, then name cap, then remaining buying power.",
        "- When a new signal cannot fit: sell the most profitable open (last close vs entry), then fill.",
        f"- Decision: **{tag}** — {verdict}",
        "",
        "## Frozen knobs",
        "",
        f"- Account seed: **${ACCOUNT:,.0f}**",
        f"- Leverage cap: **{LEVERAGE:.0f}×** Closed-only equity",
        f"- Margin rate: **{MARGIN_RATE:.1%}** actual/365 daily compound",
        f"- Withdrawal: **${WITHDRAW:,.0f}** on month-start after 2010-01-01",
        "- Monthly risk: **min(1% of BOM equity, $50,000)**",
        "- ADV lid: **shares ≤ 1% of ADV20** (20-session mean on-disk Volume; last-known if the bar is older; skip if missing)",
        "- Name lid: **open notional ≤ 10% of current (cash + reserved) equity** after ADV, before buying-power clip. Same-ticker open lots share the cap room.",
        "- Room rule: **sell winner** when buying power < $1",
        "- In-Sample (IS) = `entry_date < 2024-01-01`. OOS report-only. Do not retune lids on OOS.",
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
        "",
        "## Books",
        "",
        _book_bullet("Two-lid control (1%+$50k + 1% ADV, no 10% name)", books["twolid"]),
        _book_bullet("10% name book (live-style freeze)", books["threelid"]),
        (
            f"- **Frozen $2,500 (published)** end **${float(frozen['end']):,.2f}**; "
            f"2010 ${float(frozen['eq_2010']):,.2f}; 2011 ${float(frozen['eq_2011']):,.2f}; "
            f"2012 ${float(frozen['eq_2012']):,.2f}; Max DD {_fmt_pct(frozen['max_dd_pct'])}; "
            f"peak name ${float(frozen['peak_name']):,.2f} "
            f"({frozen.get('peak_name_symbol') or '—'}). Reuse from "
            f"`risk2500_frozen_20260917`."
        ),
        "",
        "## Headline vs SPY / two-lid / frozen $2,500",
        "",
        f"- 10% book year-end 2012: **${three['eq_2012']:,.2f}** vs SPY **${extras['spy_2012']:,.2f}** ({_vs_spy(three['eq_2012'], extras['spy_2012'])}).",
        f"- 10% book as-of {ASOF.isoformat()}: **${three['end']:,.2f}** vs SPY **${extras['spy_asof']:,.2f}** ({_vs_spy(three['end'], extras['spy_asof'])}).",
        f"- 10% vs two-lid YE2012 **${three['eq_2012']:,.2f}** vs **${two['eq_2012']:,.2f}** ({extras['ye2012_vs_two']:+.1%}); as-of **${three['end']:,.2f}** vs **${two['end']:,.2f}** ({extras['asof_vs_two']:+.1%}). 10% changed the path? **{'YES' if extras['name_changed'] else 'NO'}**.",
        f"- vs frozen $2,500 YE2012 **${three['eq_2012']:,.2f}** vs **${float(frozen['eq_2012']):,.2f}**; as-of **${three['end']:,.2f}** vs **${float(frozen['end']):,.2f}**.",
        f"- Lids (10% book): $50k fills {three['n_risk_50k_bound']} / ADV clip {three['n_adv_clipped']} / name-capped {three['n_name_capped']}.",
        "",
        "## Honesty",
        "",
        "- 10% name is in the system on this page. The two-lid sibling remains a useful control.",
        "- Judge quality and realism, not “did we still print a huge number.”",
        "- OOS is report-only. Do not retune $50k / ADV / 10% on OOS.",
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

**Product owner (PO)–aligned process:** one live-style freeze (three lids together), not a shop of extras. See `docs/HYPOTHESIS_TEST.md`.

| Field | Fill in |
|-------|---------|
| System / prefix | 5-sys {", ".join(FIVE)} (Indicators / IND out) |
| Baseline stamp | Two-lid sibling `risk_1pct_50k_adv_20260917` (1%+$50k + 1% ADV, no name cap). Wallet engine `risk2500_five_sys_20260917`. Frozen $2,500 published `risk2500_frozen_20260917` |
| Universe | House DailyRun 5-sys. Indicators (IND) excluded |
| **Evidence** | Paul: “i thought we agreed having the 10% per name cap was useful and that should be part of our system.” |
| **Hypothesis** | Putting notional ≤ 10% of current equity into the live-style freeze (with min(1% BOM, $50k) and 1% ADV20) is the book he wants — not a later yes/no. It should cut single-name pile-up versus the two-lid control without killing 2010–2012 versus SPY |
| **Single knob vs two-lid** | Name cap on (10%) vs off. $50k and ADV already on both arms |
| Frozen settings | $250k start. $7,500 on the 1st. 10.5% actual/365. Open ≤ 2×. Risk min(1% BOM, $50k). ADV 1% of ADV20. RSI 6.51% IS freeze. Sell winner when BP empty |
| Alternatives | Two-lid (no 10% name). Frozen $2,500. SPY $250k total return |
| Candidate stamps | `{STAMP}` monthly.html / compare.html. Optional attach on sibling compare.html |
| Metrics | YE2012 vs SPY; as-of vs SPY; vs two-lid; vs frozen $2,500; lid bind counts; Max DD%; peak single-name / peak book; canonical IS/OOS (report-only) |
| **Trade-diff HTML** | N/A — size / wallet overlay (not an entry A/B) |
| ToS before path | N/A |
| ToS after path | N/A |
| **Decision** | {tag} — {verdict} |
| Reviewer | AI job risk_1pct_50k_adv_10name_20260917 |
| PO sign-off | no |
| Reconcile freeze / re-baseline done | no |
| DailyRun | not wired |

## Decision checklist

- [x] Evidence was the PO correction (10% name is part of the live-style freeze)
- [x] Same Closed pins as the sibling $2,500 / two-lid stamps
- [x] Out-of-Sample (OOS) report-only; no RSI retune; no lid retune
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


def _sibling_stable() -> bool:
    compare = SIBLING / "compare.html"
    summary = SIBLING / "summary.json"
    if not compare.exists() or not summary.exists():
        return False
    try:
        html = compare.read_text(encoding="utf-8")
        raw = json.loads(summary.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if "</html>" not in html.lower():
        return False
    if "10name" in html or "10% name" in html.lower() and "attached" in html.lower():
        # already has some 10% mention — still ok to attach once
        pass
    if not raw.get("tag") and not raw.get("verdict"):
        return False
    # Mid-write guard: compare should be more than a stub.
    if len(html) < 2000:
        return False
    return True


def attach_arm_to_sibling(
    *,
    extras: dict[str, Any],
    tag: str,
    verdict: str,
) -> bool:
    """Add this 10% arm as a second-book section on the sibling compare if stable."""
    if not _sibling_stable():
        return False
    compare = SIBLING / "compare.html"
    html = compare.read_text(encoding="utf-8")
    if "data-arm=\"threelid-10name\"" in html:
        return True
    three = extras["threelid"]
    two = extras["twolid"]
    block = f"""
<section data-arm="threelid-10name" id="arm-10name">
<h2>Second arm — 10% name is in the live-style freeze</h2>
<p>Added from <a href="../{STAMP}/compare.html"><code>{STAMP}</code></a>
after Paul corrected that the 10% per-name lid is part of the system, not a
later yes/no. This sibling’s two-lid book is <strong>not</strong> reverted.
Research only. Not gold. Not DailyRun.</p>
<p><strong>{html_mod.escape(tag)}</strong> — {html_mod.escape(verdict)}</p>
<p>10% book YE2012 <strong>{format_money(three['eq_2012'])}</strong>
({_vs_spy(three['eq_2012'], extras['spy_2012'])});
as-of <strong>{format_money(three['end'])}</strong>
({_vs_spy(three['end'], extras['spy_asof'])}).
Two-lid (this stamp) YE2012 {format_money(two['eq_2012'])}; as-of {format_money(two['end'])}.
10% changed the two-lid path? <strong>{"YES" if extras["name_changed"] else "NO"}</strong>.
Lids on the 10% book: $50k fills {three['n_risk_50k_bound']};
ADV clip {three['n_adv_clipped']}; name-capped {three['n_name_capped']}.</p>
<p class="small">Full sortable tables: <a href="../{STAMP}/compare.html">compare</a>
· <a href="../{STAMP}/monthly.html">monthly</a>.</p>
</section>
"""
    lower = html.lower()
    idx = lower.rfind("</body>")
    if idx < 0:
        html = html + block
    else:
        html = html[:idx] + block + html[idx:]
    compare.write_text(html, encoding="utf-8")
    pointer = SIBLING / "ARM_10NAME.md"
    pointer.write_text(
        f"# 10% name arm attached\n\n"
        f"Paul: 10% per-name is part of the system.\n\n"
        f"This stamp’s two-lid book is unchanged.\n\n"
        f"Full 10% book: `../{STAMP}/`\n\n"
        f"Tag: {tag}\n\n"
        f"10% YE2012 ${three['eq_2012']:,.2f}; as-of ${three['end']:,.2f}.\n",
        encoding="utf-8",
    )
    return True


def _run_one(
    static: list[Any],
    *,
    name_cap: Optional[float],
    label: str,
) -> dict[str, Any]:
    return f._run_arm(
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


def run() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    frozen = _load_frozen()
    spy = f.spy_buyhold()
    spy_dd = m.spy_paths(spy)
    print(
        f"[SPY] {spy['start_date']} -> {spy['end_date']} "
        f"TR {spy['tr_end']:.2f} ({spy['tr_mult']:.3f}x) "
        f"YE2012={spy_dd['eq_2012']:.2f} MaxDD={spy_dd['full_dd']:.2f}%",
        flush=True,
    )
    print(
        f"[frozen2500] asof={frozen['end']:.2f} YE2012={frozen['eq_2012']:.2f} "
        f"(reuse {FROZEN_DIR.name})",
        flush=True,
    )

    static = f.load_static(FIVE)
    sources = [
        f"overlays: {f.PREV_DIR.name} (RSI = RSI_overlay_avgloss.csv IS 6.51% freeze)",
        f"5-sys: {', '.join(FIVE)} — Indicators (IND) out",
        f"SPY: {f.SPY_PATH.as_posix()} Adj Close total return + Close price-only",
        "wallet: tools/risk2500_five_sys_20260917.py run_wallet",
        "live-style freeze: risk=min(1% BOM, $50k) AND shares≤1% ADV20 AND notional≤10% current equity",
        "two-lid control on this page: same freeze minus the 10% name lid",
        "official two-lid sibling: risk_1pct_50k_adv_20260917 (do not revert)",
        "frozen $2500 published: risk2500_frozen_20260917 (reuse)",
        "Paul correction: 10% per-name is part of the system, not a later yes/no",
        DD_DEF,
    ]

    books: dict[str, dict[str, Any]] = {}
    # Paul's book first, then the two-lid control (ADV cache warms on the first pass).
    for key, frac, label, _cap, csv_name in reversed(ARM_SPEC):
        arm = _run_one(static, name_cap=frac, label=label)
        arm["short"] = arm["label"]
        arm["read"] = "Live-style freeze. Research only."
        books[key] = arm
        f.r.write_overlay_csv(arm["trades"], OUT_DIR / csv_name)

    tag, verdict, extras = _verdict(books, spy, spy_dd, frozen)
    print(f"[verdict] {tag} {verdict}", flush=True)

    attached = attach_arm_to_sibling(extras=extras, tag=tag, verdict=verdict)
    print(f"[sibling-attach] {attached} path={SIBLING}", flush=True)

    now = datetime.now(tz=ET)
    monthly_html = build_monthly(
        books=books,
        spy=spy,
        spy_dd=spy_dd,
        frozen=frozen,
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
        frozen=frozen,
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
        frozen=frozen,
        tag=tag,
        verdict=verdict,
        extras=extras,
        sources=sources,
        attached_sibling=attached,
    )
    write_hypothesis(tag, verdict)

    pointer_bits = [
        f"# Pointer — {STAMP}",
        "",
        "10% per-name is in this book (Paul’s correction).",
        "",
        f"- This stamp: `{OUT_DIR.as_posix()}`",
        f"- Two-lid sibling (do not revert): `{SIBLING.as_posix()}`",
        f"- Sibling attach this run: {'yes' if attached else 'no'}",
        f"- Frozen $2,500: `{FROZEN_DIR.as_posix()}`",
        "",
        f"Tag: {tag}",
        "",
        f"10% book YE2012 ${extras['threelid']['eq_2012']:,.2f}; "
        f"as-of ${extras['threelid']['end']:,.2f}.",
        f"Two-lid YE2012 ${extras['twolid']['eq_2012']:,.2f}; "
        f"as-of ${extras['twolid']['end']:,.2f}.",
        "",
    ]
    (OUT_DIR / "POINTER.md").write_text("\n".join(pointer_bits) + "\n", encoding="utf-8")

    summary = {
        "tag": tag,
        "verdict": verdict,
        "spy_tr_end": spy["tr_end"],
        "spy_2012": spy_dd["eq_2012"],
        "spy_max_dd_pct": spy_dd["full_dd"],
        "twolid": extras["twolid"],
        "threelid": extras["threelid"],
        "frozen2500": frozen,
        "sibling_attached": attached,
        "extras": _jsonable(extras),
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"wrote {OUT_DIR / 'monthly.html'}", flush=True)
    print(f"wrote {OUT_DIR / 'compare.html'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
