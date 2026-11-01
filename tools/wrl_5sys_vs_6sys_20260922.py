#!/usr/bin/env python3
"""5-sys live-style vs same wallet + WRL (6-sys) — research only.

Stamp: drive/paul_experiments/wrl_5sys_vs_6sys_20260922/

Control = official live-style five (SB / RSI / VZ / MTS / RL; IND out).
Candidate = same freeze + Weekly Range / Swing (WRL) EXIT_swing 29-name sleeve
in the **same** $250k wallet.

Headline matches docs/system_performance.html: **no $7,500/mo wires**.
Official freeze still documents wires; they are OFF here because the published
5-sys vs SPY line is the no-wire book.

Not gold. Not DailyRun. Do not retune on OOS. Do not wire DailyRun.
"""
from __future__ import annotations

import html as html_mod
import importlib.util
import json
import sys
from copy import copy
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "stock_analysis"))
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))

from compare_format import format_money  # noqa: E402
from live_style_sizing import (  # noqa: E402
    ACCOUNT_START,
    ADV_FRAC,
    FREEZE_STAMP,
    MAX_RISK_DOLLAR,
    NAME_CAP_FRAC,
    RISK_FRAC,
    RSI_AVG_LOSS_PCT_FREEZE,
)

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

STAMP = "wrl_5sys_vs_6sys_20260922"
OUT_DIR = REPO / "drive" / "paul_experiments" / STAMP
WRL_U29 = REPO / "drive" / "paul_experiments" / "wrl_exitswing_univ29_20260922"
WRL_PREVIEW = REPO / "drive" / "paul_experiments" / "wrl_wired_reports_preview_20260922"
ACCOUNT = f.ACCOUNT
ASOF = f.ASOF
ET = f.ET
IS_CUT = f.IS_CUT
START = f.START
FIVE = f.FIVE
FIVE_RANK = f.FIVE_RANK
SIX: tuple[str, ...] = FIVE + ("WRL",)
SIX_RANK = {sys: i for i, sys in enumerate(SIX)}
DD_DEF = m.DD_DEF
YEARS = max((ASOF - START).days / 365.25, 1e-9)

UNIVERSE_29: tuple[str, ...] = (
    "GEHC",
    "FTRE",
    "UBER",
    "NE",
    "FANG",
    "CARR",
    "IBP",
    "TDG",
    "DELL",
    "HWM",
    "PANW",
    "STZ",
    "LNC",
    "HCA",
    "GDDY",
    "EXLS",
    "CWK",
    "CRM",
    "PVH",
    "SHC",
    "SPG",
    "DRI",
    "FNF",
    "FN",
    "ADBE",
    "CCL",
    "UNH",
    "HGV",
    "MAR",
)
assert len(UNIVERSE_29) == 29

# Pinned from docs/system_performance.html (realistic vs SPY headline = no-wire).
PUB_5SYS_NOWIRE = {
    "eq_2010": 400_050.0,
    "eq_2011": 719_315.0,
    "eq_2012": 938_067.0,
    "end": 64_749_245.0,
    "max_dd_pct": 10.42,
    "ann_ror": 0.3945,
    "spy_ann_ror": 0.1406,
    "spy_max_dd_pct": 33.72,
    "source": "docs/system_performance.html live-style $250k vs SPY (wires OFF)",
}
# Official freeze *with* wires — shown as context only, not the vs-SPY headline.
PUB_5SYS_WIRED = {
    "eq_2010": 284_646.36,
    "eq_2011": 392_517.79,
    "eq_2012": 422_474.98,
    "end": 58_700_020.87,
    "max_dd_pct": 20.59,
    "source": "docs/live_style.html / risk_1pct_50k_adv_17name_20260917 ($7,500/mo ON)",
}

ORIGINAL_REQUEST = (
    "OK. show me what the current 5sys numbers are and what they look like "
    "if we add WRL to them for a 6sys."
)
PLAIN_ENGLISH = (
    "The live-style book is five sleeves sharing one $250,000 pile: StockBee (SB), "
    "Relative Strength Index (RSI), Volume Zone (VZ), Magic Touch (MTS), Rocket "
    "Launcher (RL). Indicators (IND) stay out. Weekly Range / Swing (WRL) is a "
    "sixth idea: watch last week's lower pocket, buy the upside break, and under "
    "EXIT_swing sell the whole lot at the swing high (stop at the swing low; "
    "min-zone off). We keep the published live-style size recipe — risk is the "
    "smaller of 1% of beginning-of-month Closed-only equity and $50,000; shares "
    "cannot exceed 1% of 20-session average daily volume (ADV20); one ticker "
    "cannot hold more than 17.5% of the account; you may borrow up to 2× equity "
    "and pay 10.5% on the loan; when buying power is empty, sell the winner to "
    "make room; RSI dollars-in uses the In-Sample 6.51% average-loser freeze. "
    "The published 5-sys versus S&P 500 tracker (SPY) headline on "
    "system_performance turns the $7,500/month bank wires OFF (those are 2026 "
    "personal transfers, not a sizing lid) — this compare matches that no-wire "
    "headline. One change only: drop WRL trades into the same wallet (not a "
    "second $250k). WRL fill-order sits after the five (RL → MTS → SB → VZ → "
    "RSI → WRL). The 29 names were picked after seeing In-Sample tables — that "
    "is selection bias, labeled. Out-of-Sample is report-only. Research only: "
    "not gold, not DailyRun."
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


def _wallet_cagr(end: float, *, start: float = ACCOUNT, start_d: date = START, end_d: date = ASOF) -> float:
    years = max((end_d - start_d).days / 365.25, 1e-9)
    if start <= 0:
        return 0.0
    if end <= 0:
        return -1.0
    return (end / start) ** (1.0 / years) - 1.0


def _died(end: float, max_dd_pct: float) -> bool:
    return end < ACCOUNT * 0.10 or max_dd_pct >= 90.0


def _latest(folder: Path, pattern: str) -> Optional[Path]:
    if not folder.is_dir():
        return None
    hits = sorted(folder.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return hits[0] if hits else None


def _wrl_sources() -> list[Path]:
    return [
        WRL_U29 / "EXIT_swing",
        WRL_U29,
        WRL_PREVIEW,
        REPO / "drive" / "paul_experiments" / "wrl_exitswing_is_universe_20260922" / "EXIT_swing",
    ]


def _find_wrl_closed() -> Path:
    for folder in _wrl_sources():
        for name in (
            "WRL_LatestRun_Closed.csv",
            "WRL_Closed_overlay.csv",
        ):
            p = folder / name
            if p.is_file():
                return p
        p = _latest(folder, "WRL_Closed_*.csv")
        if p is not None:
            return p
    raise SystemExit(
        "missing WRL EXIT_swing Closed — expected "
        f"{WRL_U29 / 'EXIT_swing'} or {WRL_PREVIEW}"
    )


def _find_wrl_open(closed: Path) -> Optional[Path]:
    folder = closed.parent
    for name in ("WRL_LatestRun_Open.csv",):
        p = folder / name
        if p.is_file():
            return p
    return _latest(folder, "WRL_Open_*.csv")


def load_wrl_overlay() -> tuple[list[Any], dict[str, str]]:
    closed_path = _find_wrl_closed()
    open_path = _find_wrl_open(closed_path)
    raw_c = f.r.load_closed_rows(closed_path, "WRL")
    raw_o = f.r.load_open_rows(open_path, "WRL") if open_path else []
    keep = set(UNIVERSE_29)
    raw_c = [row for row in raw_c if str(row.get("symbol") or "").upper() in keep]
    raw_o = [row for row in raw_o if str(row.get("symbol") or "").upper() in keep]
    trades = [f.r.overlay_one("WRL", row) for row in raw_c]
    trades.extend(f.r.overlay_one("WRL", row) for row in raw_o)
    meta = {
        "closed_path": closed_path.as_posix(),
        "open_path": open_path.as_posix() if open_path else "",
        "n_closed_src": str(len(raw_c)),
        "n_open_src": str(len(raw_o)),
        "n_overlay": str(len(trades)),
        "n_sized": str(sum(1 for t in trades if t.sized)),
    }
    return trades, meta


def _clone(trades: list[Any]) -> list[Any]:
    return [copy(t) for t in trades]


def _led_pack(arm: dict[str, Any]) -> dict[str, Any]:
    led = arm["led"]
    st = arm["stats_full"]
    n_fill = int(led.n_full) + int(led.n_scaled)
    end = float(led.end_equity)
    cagr = _wallet_cagr(end)
    return {
        "end": end,
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
        "n_adv_clipped": int(led.n_adv_clipped),
        "n_skip_adv": int(led.n_skip_adv),
        "interest": float(led.interest),
        "withdrawals": float(led.withdrawals),
        "identity": float(led.identity_err),
        "wr": _num(st, "win_pct"),
        "avg": _num(st, "avg_pnl_pct"),
        "pf": _num(st, "pf"),
        "n": _num(st, "n"),
        "wallet_cagr": cagr,
        "died": _died(end, float(led.max_dd_pct)),
        "n_wrl_fill": sum(
            1
            for t in arm.get("trades") or []
            if t.system == "WRL" and t.sized and t.status == "closed"
        ),
        "n_wrl_src": sum(1 for t in arm.get("trades") or [] if t.system == "WRL"),
    }


def _run_one(
    static: list[Any],
    *,
    rank: dict[str, int],
    label: str,
) -> dict[str, Any]:
    arm = f._run_arm(
        _clone(static),
        rank=rank,
        rotate="winner",
        withdraw=False,
        label=label,
        risk_frac=RISK_FRAC,
        name_cap_frac=NAME_CAP_FRAC,
        max_risk_dollar=MAX_RISK_DOLLAR,
        adv_frac=ADV_FRAC,
    )
    arm["name_cap_frac"] = NAME_CAP_FRAC
    arm["short"] = label
    return arm


def _pin_delta(rerun: dict[str, Any], pub: dict[str, Any]) -> dict[str, float]:
    return {
        "ye2012": float(rerun["eq_2012"]) - float(pub["eq_2012"]),
        "asof": float(rerun["end"]) - float(pub["end"]),
        "max_dd": float(rerun["max_dd_pct"]) - float(pub["max_dd_pct"]),
    }


def _verdict(
    five: dict[str, Any],
    six: dict[str, Any],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    spy_asof = float(spy["tr_end"])
    spy_2012 = float(spy_dd["eq_2012"])
    extras: dict[str, Any] = {
        "spy_asof": spy_asof,
        "spy_2012": spy_2012,
        "spy_cagr": _wallet_cagr(spy_asof),
        "five": five,
        "six": six,
        "ye2012_vs_five": (six["eq_2012"] - five["eq_2012"]) / abs(five["eq_2012"])
        if abs(five["eq_2012"]) > 1e-9
        else 0.0,
        "asof_vs_five": (six["end"] - five["end"]) / abs(five["end"])
        if abs(five["end"]) > 1e-9
        else 0.0,
        "dd_delta": six["max_dd_pct"] - five["max_dd_pct"],
        "cagr_delta": six["wallet_cagr"] - five["wallet_cagr"],
        "wr_delta": six["wr"] - five["wr"],
        "avg_delta": six["avg"] - five["avg"],
        "pf_delta": six["pf"] - five["pf"],
        "n_delta": six["n"] - five["n"],
        "ye2012_vs_spy_5": _vs_spy(five["eq_2012"], spy_2012),
        "ye2012_vs_spy_6": _vs_spy(six["eq_2012"], spy_2012),
        "asof_vs_spy_5": _vs_spy(five["end"], spy_asof),
        "asof_vs_spy_6": _vs_spy(six["end"], spy_asof),
    }
    path = (
        f"2010–2012 — 5-sys {format_money(five['eq_2010'])} / "
        f"{format_money(five['eq_2011'])} / {format_money(five['eq_2012'])}; "
        f"6-sys {format_money(six['eq_2010'])} / {format_money(six['eq_2011'])} / "
        f"{format_money(six['eq_2012'])}; "
        f"SPY {format_money(spy['years'].get(2010, {}).get('tr', 0))} / "
        f"{format_money(spy['years'].get(2011, {}).get('tr', 0))} / "
        f"{format_money(spy_2012)}."
    )
    vs = (
        f"6-sys vs 5-sys: YE2012 {format_money(six['eq_2012'])} vs "
        f"{format_money(five['eq_2012'])} ({extras['ye2012_vs_five']:+.1%}); "
        f"as-of {format_money(six['end'])} vs {format_money(five['end'])} "
        f"({extras['asof_vs_five']:+.1%}); Max DD {_fmt_pct(six['max_dd_pct'])} vs "
        f"{_fmt_pct(five['max_dd_pct'])} ({extras['dd_delta']:+.2f} pt); "
        f"wallet CAGR {_fmt_pct(100.0 * six['wallet_cagr'])} vs "
        f"{_fmt_pct(100.0 * five['wallet_cagr'])}. "
        f"Book quality FULL: WR {five['wr']:.1f}% → {six['wr']:.1f}% "
        f"({extras['wr_delta']:+.2f} pt); Avg PnL% {five['avg']:+.2f} → "
        f"{six['avg']:+.2f}; PF {five['pf']:.2f} → {six['pf']:.2f}; "
        f"N {five['n']:.0f} → {six['n']:.0f} (WRL filled {six['n_wrl_fill']}). "
        f"vs SPY: 5-sys YE2012 {extras['ye2012_vs_spy_5']} as-of {extras['asof_vs_spy_5']}; "
        f"6-sys YE2012 {extras['ye2012_vs_spy_6']} as-of {extras['asof_vs_spy_6']}. {path} "
        "29-name WRL pick is In-Sample selection. OOS is report-only. "
        "Not gold. Not DailyRun."
    )

    if six["died"]:
        return "DISMISS", f"DISMISS 6-sys — book died or Max DD ≥ 90%. {vs}", extras
    if five["died"]:
        return "HOLD", f"HOLD — 5-sys control died; do not promote 6-sys off a broken baseline. {vs}", extras

    ye_up = extras["ye2012_vs_five"] > 0.02
    ye_flat = abs(extras["ye2012_vs_five"]) <= 0.02
    ye_down = extras["ye2012_vs_five"] < -0.02
    dd_better = extras["dd_delta"] <= -0.25
    dd_worse = extras["dd_delta"] >= 0.50
    quality_up = extras["avg_delta"] > 0.02 and extras["pf_delta"] >= -0.02
    quality_down = extras["avg_delta"] < -0.05 or extras["pf_delta"] < -0.08
    n_up_a_lot = extras["n_delta"] > max(50.0, 0.08 * max(five["n"], 1.0))
    asof_only = extras["asof_vs_five"] > 0.05 and not ye_up and not quality_up

    if ye_down and (dd_worse or quality_down):
        tag = "DISMISS"
        why = "YE2012 and quality/drawdown both softened versus 5-sys."
    elif ye_up and (dd_worse or quality_down):
        tag = "HOLD"
        why = (
            "YE2012 dollars rose, but quality did not: Max DD worsened and/or "
            "WR / Avg PnL% / PF softened while WRL added a large pile of extra fills. "
            "Judge is quality, not trade count."
        )
    elif asof_only or (extras["asof_vs_five"] > 0 and ye_flat and n_up_a_lot and not quality_up):
        tag = "HOLD"
        why = (
            "6-sys only looks better because later-year dollars / more fills "
            "(capacity fiction), not a cleaner early path or better quality."
        )
    elif ye_up and not dd_worse and not quality_down:
        if n_up_a_lot and not quality_up and extras["ye2012_vs_five"] < 0.08:
            tag = "HOLD"
            why = (
                "YE2012 lift is small and rides extra WRL count more than "
                "better average trade quality."
            )
        else:
            tag = "KEEP"
            why = (
                "YE2012 improved versus 5-sys without a worse Max DD or a "
                "collapsed book (WR / Avg PnL% / PF). Research candidate only."
            )
    elif ye_flat and (dd_better or quality_up) and not dd_worse:
        tag = "HOLD"
        why = (
            "Quality / drawdown nudged, YE2012 essentially flat — not enough "
            "to KEEP a sixth sleeve."
        )
    else:
        tag = "HOLD"
        why = (
            "Mixed: adding WRL does not clearly improve live-style quality "
            "versus 5-sys on the honest 2010–2012 read."
        )
    prose = (
        f"{tag} 6-sys (5 + WRL EXIT_swing 29-name) versus official 5-sys no-wire. "
        f"{why} HOLD versus gold / DailyRun. {vs}"
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


def _headline_cards(extras: dict[str, Any], tag: str) -> str:
    five = extras["five"]
    six = extras["six"]
    cls = "yes" if tag == "KEEP" else ("no" if tag == "DISMISS" else "holdtag")
    return f"""
<div class="lead">
  <h2>Headline — official 5-sys vs 6-sys (same wallet + WRL)</h2>
  <p><strong class="{cls}">{html_mod.escape(tag)}</strong> · research only · not gold · not DailyRun</p>
  <p class="small">Freeze = published live-style lids. Wires OFF to match the
  <code>docs/system_performance.html</code> 5-sys vs SPY headline. One knob: add
  Weekly Range / Swing (WRL) EXIT_swing on the 29-name first universe into the
  same $250k wallet. Fill-order: RL → MTS → SB → VZ → RSI → WRL.</p>
  <div class="cards">
    <div class="card card-shared">
      <h3>5-sys (control) · YE2012</h3>
      <div class="metric">{format_money(five['eq_2012'])}</div>
      <div class="small">SPY {format_money(extras['spy_2012'])} · {extras['ye2012_vs_spy_5']}</div>
      <div class="small">as-of {format_money(five['end'])} · {extras['asof_vs_spy_5']}</div>
      <div class="small">Max DD {_fmt_pct(five['max_dd_pct'])} · wallet CAGR {_fmt_pct(100.0 * five['wallet_cagr'])}</div>
      <div class="small">dies? {"yes" if five['died'] else "no"} · peak name {html_mod.escape(five['peak_name_symbol'])} {format_money(five['peak_name'])}</div>
      <div class="small">wires OFF · N {five['n']:.0f}</div>
    </div>
    <div class="card">
      <h3>6-sys (5 + WRL) · YE2012</h3>
      <div class="metric">{format_money(six['eq_2012'])}</div>
      <div class="small">SPY {format_money(extras['spy_2012'])} · {extras['ye2012_vs_spy_6']}</div>
      <div class="small">as-of {format_money(six['end'])} · {extras['asof_vs_spy_6']}</div>
      <div class="small">Max DD {_fmt_pct(six['max_dd_pct'])} · wallet CAGR {_fmt_pct(100.0 * six['wallet_cagr'])}</div>
      <div class="small">dies? {"yes" if six['died'] else "no"} · peak name {html_mod.escape(six['peak_name_symbol'])} {format_money(six['peak_name'])}</div>
      <div class="small">wires OFF · N {six['n']:.0f} · WRL fills {six['n_wrl_fill']}</div>
    </div>
    <div class="card">
      <h3>SPY $250k (total return)</h3>
      <div class="metric">{format_money(extras['spy_asof'])}</div>
      <div class="small">YE2012 {format_money(extras['spy_2012'])}</div>
      <div class="small">Max DD {_fmt_pct(extras.get('spy_dd_full', 0.0))} · Ann ROR {_fmt_pct(100.0 * extras['spy_cagr'])}</div>
      <div class="small">Buy-and-hold from 2010-01-01 · dividends reinvested</div>
    </div>
    <div class="card">
      <h3>6-sys minus 5-sys</h3>
      <div class="metric">{extras['ye2012_vs_five']:+.1%} YE2012</div>
      <div class="small">as-of {extras['asof_vs_five']:+.1%} · Max DD {extras['dd_delta']:+.2f} pt</div>
      <div class="small">wallet CAGR {extras['cagr_delta']*100:+.2f} pt · WR {extras['wr_delta']:+.2f} pt</div>
      <div class="small">Avg PnL% {extras['avg_delta']:+.2f} · PF {extras['pf_delta']:+.2f} · ΔN {extras['n_delta']:+.0f}</div>
    </div>
  </div>
</div>"""


def _wallet_table(
    five: dict[str, Any],
    six: dict[str, Any],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
    pin: dict[str, Any],
    pin_delta: dict[str, float],
) -> str:
    head = f._sortable_head(
        [
            ("Book", "text"),
            ("YE2012", "num"),
            ("vs SPY YE2012", "text"),
            ("As-of", "num"),
            ("vs SPY as-of", "text"),
            ("Max DD%", "num"),
            ("Dies?", "text"),
            ("Wallet CAGR", "num"),
            ("N closed sized", "num"),
            ("Wires", "text"),
            ("Peak name", "text"),
            ("Peak name $", "num"),
        ]
    )
    spy_2012 = float(spy_dd["eq_2012"])
    spy_end = float(spy["tr_end"])
    rows = [
        (
            "5-sys official live-style (this run, no-wire)",
            five["eq_2012"],
            _vs_spy(five["eq_2012"], spy_2012),
            five["end"],
            _vs_spy(five["end"], spy_end),
            five["max_dd_pct"],
            "yes" if five["died"] else "no",
            100.0 * five["wallet_cagr"],
            five["n"],
            "OFF (headline)",
            five["peak_name_symbol"],
            five["peak_name"],
        ),
        (
            "6-sys = 5-sys + WRL EXIT_swing 29-name (no-wire)",
            six["eq_2012"],
            _vs_spy(six["eq_2012"], spy_2012),
            six["end"],
            _vs_spy(six["end"], spy_end),
            six["max_dd_pct"],
            "yes" if six["died"] else "no",
            100.0 * six["wallet_cagr"],
            six["n"],
            "OFF (headline)",
            six["peak_name_symbol"],
            six["peak_name"],
        ),
        (
            "SPY $250k total return",
            spy_2012,
            "1.00×",
            spy_end,
            "1.00×",
            float(spy_dd["full_dd"]),
            "no",
            100.0 * _wallet_cagr(spy_end),
            0,
            "n/a",
            "—",
            0.0,
        ),
        (
            "Pinned published 5-sys no-wire (system_performance)",
            pin["eq_2012"],
            _vs_spy(pin["eq_2012"], spy_2012),
            pin["end"],
            _vs_spy(pin["end"], spy_end),
            pin["max_dd_pct"],
            "no",
            100.0 * float(pin["ann_ror"]),
            0,
            "OFF (published headline)",
            "—",
            0.0,
        ),
        (
            "Pinned official 5-sys WITH wires (context only)",
            PUB_5SYS_WIRED["eq_2012"],
            _vs_spy(PUB_5SYS_WIRED["eq_2012"], spy_2012),
            PUB_5SYS_WIRED["end"],
            _vs_spy(PUB_5SYS_WIRED["end"], spy_end),
            PUB_5SYS_WIRED["max_dd_pct"],
            "no",
            100.0 * _wallet_cagr(PUB_5SYS_WIRED["end"]),
            0,
            "ON $7,500/mo (not this AB)",
            "—",
            0.0,
        ),
    ]
    body = ""
    for i, row in enumerate(rows):
        cls = ' class="total-row"' if i == 0 else ""
        body += (
            f"<tr{cls}>"
            f"<td>{html_mod.escape(str(row[0]))}</td>"
            f"<td>{format_money(row[1])}</td>"
            f"<td>{html_mod.escape(str(row[2]))}</td>"
            f"<td>{format_money(row[3])}</td>"
            f"<td>{html_mod.escape(str(row[4]))}</td>"
            f"<td>{_fmt_pct(row[5])}</td>"
            f"<td>{html_mod.escape(str(row[6]))}</td>"
            f"<td>{_fmt_pct(row[7])}</td>"
            f"<td>{row[8]:.0f}</td>"
            f"<td>{html_mod.escape(str(row[9]))}</td>"
            f"<td>{html_mod.escape(str(row[10]))}</td>"
            f"<td>{format_money(row[11]) if row[11] else '—'}</td>"
            "</tr>"
        )
    note = (
        f"5-sys re-run vs published pin: YE2012 {pin_delta['ye2012']:+,.2f}, "
        f"as-of {pin_delta['asof']:+,.2f}, Max DD {pin_delta['max_dd']:+.2f} pt. "
        "Click column headers to sort. Control row pinned."
    )
    return (
        f'<p class="small">{html_mod.escape(note)}</p>'
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def _freeze_table() -> str:
    head = f._sortable_head(
        [("Knob", "text"), ("Locked value", "text"), ("Notes", "text")]
    )
    rows = [
        ("Start equity", format_money(ACCOUNT), "One wallet — not a second $250k for WRL"),
        ("Wires", "OFF ($0/mo)", "Matches system_performance 5-sys vs SPY headline. Official freeze also has $7,500/mo ON (shown as pin only)."),
        ("Risk", "min(1% BOM Closed-only equity, $50,000)", f"Stamp {FREEZE_STAMP}"),
        ("ADV lid", "shares ≤ 1% ADV20", "20-session average daily volume"),
        ("Name cap", "17.5% of current equity", "Official live-style — not 5%/10%"),
        ("Margin / leverage", "10.5% annual · 2× equity", "Sell-winner when buying power empty"),
        ("RSI size", f"risk ÷ {RSI_AVG_LOSS_PCT_FREEZE/100.0:.6f} (IS 6.51%)", "Do not retune OOS"),
        ("5-sys sleeves", ", ".join(FIVE), "SB / RSI / VZ / MTS / RL. Indicators (IND) out"),
        ("WRL sleeve", "EXIT_swing · 29-name first universe", "100% off at swing high; stop swing low; min-zone off"),
        ("Fill-order", "RL → MTS → SB → VZ → RSI → WRL", "Five-sys DailyRun rank helper; WRL appended (not in REPORT_ORDER; wired=False)"),
        ("IS / OOS cut", "entry_date < 2024-01-01 IS", "OOS report-only. Do not retune."),
        ("Stage", "Research candidate", "Not gold. Not DailyRun. Do not wire."),
    ]
    body = "".join(
        f"<tr><td>{html_mod.escape(a)}</td><td>{html_mod.escape(b)}</td>"
        f"<td>{html_mod.escape(c)}</td></tr>"
        for a, b, c in rows
    )
    return (
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def _year_table(five_arm: dict[str, Any], six_arm: dict[str, Any], spy: dict[str, Any]) -> str:
    head = f._sortable_head(
        [
            ("Year-end", "num"),
            ("5-sys", "num"),
            ("6-sys (5+WRL)", "num"),
            ("SPY TR", "num"),
            ("5-sys vs SPY", "text"),
            ("6-sys vs SPY", "text"),
            ("Note", "text"),
        ]
    )
    body = ""
    for y in range(2010, ASOF.year + 1):
        r5 = next((x for x in five_arm["years"] if x["year"] == y), None)
        r6 = next((x for x in six_arm["years"] if x["year"] == y), None)
        sy = spy["years"].get(y)
        e5 = float(r5["ending_equity"]) if r5 else 0.0
        e6 = float(r6["ending_equity"]) if r6 else 0.0
        st = float(sy["tr"]) if sy else 0.0
        note = f"through {ASOF.isoformat()}" if y == ASOF.year else ""
        body += (
            "<tr>"
            f"<td>{y}</td>"
            f"<td>{format_money(e5) if r5 else '—'}</td>"
            f"<td>{format_money(e6) if r6 else '—'}</td>"
            f"<td>{format_money(st) if sy else '—'}</td>"
            f"<td>{_vs_spy(e5, st) if r5 and sy else '—'}</td>"
            f"<td>{_vs_spy(e6, st) if r6 and sy else '—'}</td>"
            f"<td class=\"small\">{html_mod.escape(note)}</td>"
            "</tr>"
        )
    return (
        '<p class="small">Full year-end path. Click headers to sort.</p>'
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def build_compare(
    *,
    five_arm: dict[str, Any],
    six_arm: dict[str, Any],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
    tag: str,
    verdict: str,
    extras: dict[str, Any],
    pin_delta: dict[str, float],
    wrl_meta: dict[str, str],
    sources: list[str],
    generated: datetime,
) -> str:
    now = generated.astimezone(ET)
    gen_s = now.strftime("%Y-%m-%d %H:%M %Z")
    sources_html = "".join(f"<li>{html_mod.escape(s)}</li>" for s in sources)
    compare_sections = ""
    col_map = {"IS": "stats_is", "OOS": "stats_oos", "FULL": "stats_full"}
    notes = {
        "IS": "In-Sample — overlay closed trades with entry before 2024-01-01. Wallet path is continuous; do not retune OOS.",
        "OOS": "Out-of-Sample — report-only. Do not pick KEEP from this slice. Wallet dollars already felt the IS path.",
        "FULL": verdict,
    }
    for sl in ("IS", "OOS", "FULL"):
        cols = [
            ("5-sys (control)", five_arm[col_map[sl]]),
            ("6-sys (5+WRL)", six_arm[col_map[sl]]),
        ]
        compare_sections += f"""
<section>
<h2>Canonical compare · {sl}</h2>
<p class="small">{html_mod.escape(notes[sl])} Sheet / Total PnL $ omitted. Click headers to sort. Δ vs 5-sys.</p>
<div class="table-wrap">{f._canonical_table(cols)}</div>
</section>"""
    hold_cls = "hold" if tag == "HOLD" else ("warn" if tag == "DISMISS" else "lead")
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Compare — 5-sys vs 6-sys (5+WRL) — {STAMP}</title>
<style>{f._css()}</style></head><body>
<h1>Compare — official 5-sys vs 6-sys (add Weekly Range / Swing)</h1>
<p class="sub">
Stamp <code>{STAMP}</code>. Research only. <strong>Not gold. Not DailyRun.</strong>
Generated {html_mod.escape(gen_s)}. Click column headers to sort.
Wires OFF to match the published 5-sys vs SPY headline.
WRL Closed: <code>{html_mod.escape(wrl_meta.get('closed_path', ''))}</code>
({html_mod.escape(wrl_meta.get('n_closed_src', '0'))} closed /
{html_mod.escape(wrl_meta.get('n_open_src', '0'))} open after 29-name filter).
</p>
{_ask_block()}
<div class="warn">
<strong>2010–2012 first.</strong> Later-year paper dollars can be capacity fiction
(tight stops + 1% of a growing pile + 2× + sell-winner). The honest read is the
first three years versus SPY. 29-name WRL universe is In-Sample selection after
Paul saw the full-universe table. WRL house default adopt may still be in flight.
OOS is report-only.
</div>
<div class="{hold_cls}"><strong>{html_mod.escape(verdict)}</strong></div>
{_headline_cards(extras, tag)}
<section>
<h2>Wallet headlines Paul asked for</h2>
<p class="small">YE2012, as-of vs SPY, Max DD, dies?, wires, peak name. Click headers to sort.</p>
{_wallet_table(extras['five'], extras['six'], spy, spy_dd, PUB_5SYS_NOWIRE, pin_delta)}
</section>
<section>
<h2>Frozen knobs</h2>
{_freeze_table()}
</section>
<section>
<h2>Year-end path</h2>
{_year_table(five_arm, six_arm, spy)}
</section>
{compare_sections}
<section>
<h2>Max drawdown definition</h2>
<p>{html_mod.escape(DD_DEF)}</p>
</section>
<section>
<h2>Data sources</h2>
<ul class="sources">{sources_html}</ul>
<p class="small">
Acronyms first use: Weekly Range / Swing (WRL); StockBee (SB); Relative Strength
Index (RSI); Volume Zone (VZ); Magic Touch (MTS); Rocket Launcher (RL);
Indicators (IND); In-Sample (IS); Out-of-Sample (OOS); beginning-of-month (BOM);
average daily volume over 20 sessions (ADV20); buying power (BP);
S&amp;P 500 tracker (SPY); Annualized Rate of Return (Ann ROR);
compound annual growth rate (CAGR).
</p>
</section>
{f.r.monthly._SORTABLE_TABLE_SCRIPT}
</body></html>"""


def _write_md(
    *,
    tag: str,
    verdict: str,
    extras: dict[str, Any],
    wrl_meta: dict[str, str],
    pin_delta: dict[str, float],
    sources: list[str],
) -> None:
    five = extras["five"]
    six = extras["six"]
    (OUT_DIR / "BASELINE.md").write_text(
        "\n".join(
            [
                "# Baseline — 5-sys vs 6-sys (5+WRL) 20260922",
                "",
                f"**Stamp:** `{STAMP}`",
                "",
                "## What you asked",
                "",
                f"> {ORIGINAL_REQUEST}",
                "",
                "## In plain English",
                "",
                PLAIN_ENGLISH,
                "",
                "## Frozen knobs (official live-style, no-wire headline)",
                "",
                f"- Parent freeze: `{FREEZE_STAMP}` / `stock_analysis/live_style_sizing.py`",
                f"- Start ${ACCOUNT:,.0f}. One wallet.",
                "- Wires **OFF** — matches `docs/system_performance.html` 5-sys vs SPY headline.",
                "- Official-with-wires path is pin-only (not this AB).",
                "- risk = min(1% BOM Closed-only equity, $50,000)",
                "- shares ≤ 1% ADV20",
                "- notional ≤ 17.5% current equity",
                "- 10.5% margin · 2× equity · sell-winner on empty BP",
                f"- RSI invested = risk / {RSI_AVG_LOSS_PCT_FREEZE/100.0:.8f} (IS 6.51% freeze)",
                f"- 5-sys: {', '.join(FIVE)} (IND out)",
                "- WRL: EXIT_swing (100% off swing high; stop swing low; min-zone off)",
                f"- WRL universe (29, Paul's list): {', '.join(UNIVERSE_29)}",
                "- Fill-order: RL → MTS → SB → VZ → RSI → WRL",
                "  (five-sys `FIVE_RANK`; WRL appended. `dailyrun_system_status` has WRL `wired=False`, not in `REPORT_ORDER`.)",
                f"- IS cut: entry < {IS_CUT.isoformat()}. OOS report-only.",
                f"- As-of: {ASOF.isoformat()}",
                "",
                "## Pinned published 5-sys (no-wire headline)",
                "",
                f"- Source: {PUB_5SYS_NOWIRE['source']}",
                f"- YE2012 ${PUB_5SYS_NOWIRE['eq_2012']:,.0f}; as-of ${PUB_5SYS_NOWIRE['end']:,.0f}; "
                f"Max DD {PUB_5SYS_NOWIRE['max_dd_pct']:.2f}%; Ann ROR {PUB_5SYS_NOWIRE['ann_ror']*100:.2f}%",
                f"- SPY Ann ROR {PUB_5SYS_NOWIRE['spy_ann_ror']*100:.2f}%; Max DD {PUB_5SYS_NOWIRE['spy_max_dd_pct']:.2f}%",
                f"- This-run 5-sys vs pin: YE2012 {pin_delta['ye2012']:+,.2f}; as-of {pin_delta['asof']:+,.2f}; "
                f"Max DD {pin_delta['max_dd']:+.2f} pt",
                "",
                "## Official-with-wires (context, not this AB)",
                "",
                f"- Source: {PUB_5SYS_WIRED['source']}",
                f"- YE2012 ${PUB_5SYS_WIRED['eq_2012']:,.2f}; as-of ${PUB_5SYS_WIRED['end']:,.2f}; "
                f"Max DD {PUB_5SYS_WIRED['max_dd_pct']:.2f}%",
                "",
                "## WRL book reused",
                "",
                f"- Closed: `{wrl_meta.get('closed_path', '')}`",
                f"- Open: `{wrl_meta.get('open_path', '') or 'none'}`",
                f"- After 29-name filter: {wrl_meta.get('n_closed_src', '0')} closed / "
                f"{wrl_meta.get('n_open_src', '0')} open / overlay {wrl_meta.get('n_overlay', '0')}",
                "- 29-name pick is in-sample selection. WRL house default adopt may be in flight.",
                "",
                "## This-run wallets (no-wire)",
                "",
                f"- 5-sys YE2012 ${five['eq_2012']:,.2f}; as-of ${five['end']:,.2f}; "
                f"Max DD {_fmt_pct(five['max_dd_pct'])}; wallet CAGR {_fmt_pct(100.0 * five['wallet_cagr'])}; "
                f"N {five['n']:.0f}; dies? {five['died']}; peak {five['peak_name_symbol']} {five['peak_name']:,.2f}",
                f"- 6-sys YE2012 ${six['eq_2012']:,.2f}; as-of ${six['end']:,.2f}; "
                f"Max DD {_fmt_pct(six['max_dd_pct'])}; wallet CAGR {_fmt_pct(100.0 * six['wallet_cagr'])}; "
                f"N {six['n']:.0f}; WRL fills {six['n_wrl_fill']}; dies? {six['died']}; "
                f"peak {six['peak_name_symbol']} {six['peak_name']:,.2f}",
                f"- Tag: {tag}",
                "",
                "## Selection / anti-overfit",
                "",
                "- One knob: add WRL sleeve. Do not retune lids or WRL exit on OOS.",
                "- KEEP/DISMISS on quality (YE2012, Max DD, WR / Avg PnL% / PF), not trade count.",
                "- If 6-sys only wins on later-year dollars / extra fills → HOLD.",
                "- Research candidate ≠ gold ≠ DailyRun.",
                "",
                "## Sources",
                "",
                *[f"- {s}" for s in sources],
                "",
                "Research only. Not gold. Not DailyRun.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (OUT_DIR / "HYPOTHESIS.md").write_text(
        "\n".join(
            [
                "# Hypothesis test — 5-sys vs 6-sys (add WRL) 20260922",
                "",
                f"**Original request:** {ORIGINAL_REQUEST}",
                "",
                "| Field | Value |",
                "| --- | --- |",
                "| Baseline | Official live-style 5-sys no-wire (`risk_1pct_50k_adv_17name_20260917` lids; `docs/system_performance.html` vs-SPY headline) |",
                "| One knob | Add Weekly Range / Swing (WRL) EXIT_swing 29-name as a sixth sleeve in the **same** $250k wallet |",
                "| Control | 5-sys SB / RSI / VZ / MTS / RL |",
                "| Candidate | 5-sys + WRL |",
                "| Fill-order | FIVE_RANK then WRL (RL, MTS, SB, VZ, RSI, WRL) |",
                "| Wires | OFF (headline). Official $7,500/mo is pin-only. |",
                "| IS / OOS | entry < 2024-01-01 IS; OOS report-only |",
                "| Selection | 29-name WRL list is in-sample; labeled |",
                f"| Verdict | {tag} |",
                "",
                "## Why this test",
                "",
                "Paul asked what the current five-sleeve live-style numbers are, and what happens if WRL joins them. Same size recipe. Same wallet. No second pile of cash.",
                "",
                "## Judge",
                "",
                "- Quality over count: YE2012 vs 5-sys and vs SPY, Max DD, wallet CAGR, WR / Avg PnL% / PF.",
                "- If 6-sys wins only because more trades / later-year capacity fiction → HOLD.",
                "- Do not retune WRL or lids on OOS.",
                "- Not gold. Not DailyRun.",
                "",
                "## Result",
                "",
                verdict,
                "",
            ]
        ),
        encoding="utf-8",
    )


def run() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    spy = f.spy_buyhold()
    spy_dd = m.spy_paths(spy)
    print(
        f"[SPY] YE2012={spy_dd['eq_2012']:.2f} asof={spy['tr_end']:.2f} "
        f"MaxDD={spy_dd['full_dd']:.2f}%",
        flush=True,
    )
    print(
        f"[pin] published 5-sys no-wire YE2012={PUB_5SYS_NOWIRE['eq_2012']:.0f} "
        f"asof={PUB_5SYS_NOWIRE['end']:.0f} MaxDD={PUB_5SYS_NOWIRE['max_dd_pct']:.2f}% "
        f"AnnROR={PUB_5SYS_NOWIRE['ann_ror']*100:.2f}%",
        flush=True,
    )

    five_static = f.load_static(FIVE)
    wrl_trades, wrl_meta = load_wrl_overlay()
    print(
        f"[WRL] closed={wrl_meta['closed_path']} n_closed={wrl_meta['n_closed_src']} "
        f"n_open={wrl_meta['n_open_src']} overlay={wrl_meta['n_overlay']} "
        f"sized={wrl_meta['n_sized']}",
        flush=True,
    )
    six_static = five_static + wrl_trades

    sources = [
        f"5-sys overlays: {f.PREV_DIR.name} (RSI = RSI_overlay_avgloss.csv IS 6.51% freeze)",
        f"5-sys sleeves: {', '.join(FIVE)} — Indicators (IND) out",
        f"WRL Closed: {wrl_meta['closed_path']}",
        f"WRL Open: {wrl_meta.get('open_path') or 'none'}",
        "WRL freeze: EXIT_swing (wrl_target_mode=swing); 29-name first universe; min-zone off",
        "Fill-order: FIVE_RANK (RL, MTS, SB, VZ, RSI) then WRL. dailyrun_system_status WRL wired=False, not in REPORT_ORDER.",
        f"SPY: {f.SPY_PATH.as_posix()} Adj Close total return + Close price-only",
        "wallet: tools/risk2500_five_sys_20260917.py run_wallet",
        f"LOCKED live-style lids from {FREEZE_STAMP}: risk=min(1% BOM, $50k) AND shares≤1% ADV20 AND notional≤17.5%",
        "Wires OFF to match docs/system_performance.html 5-sys vs SPY headline",
        "29-name pick is in-sample selection — labeled",
        DD_DEF,
    ]

    print("[arm] 5-sys no-wire official lids …", flush=True)
    five_arm = _run_one(five_static, rank=FIVE_RANK, label="5-sys official live-style (no-wire)")
    print("[arm] 6-sys no-wire + WRL …", flush=True)
    six_arm = _run_one(six_static, rank=SIX_RANK, label="6-sys official live-style + WRL (no-wire)")

    five = _led_pack(five_arm)
    six = _led_pack(six_arm)
    pin_delta = _pin_delta(five, PUB_5SYS_NOWIRE)
    tag, verdict, extras = _verdict(five, six, spy, spy_dd)
    extras["spy_dd_full"] = float(spy_dd["full_dd"])

    f.r.write_overlay_csv(five_arm["trades"], OUT_DIR / "ALL_overlay_5sys_nowire.csv")
    f.r.write_overlay_csv(six_arm["trades"], OUT_DIR / "ALL_overlay_6sys_nowire.csv")
    f.r.write_overlay_csv(wrl_trades, OUT_DIR / "WRL_overlay_exitswing_univ29.csv")

    generated = datetime.now(tz=ET)
    html = build_compare(
        five_arm=five_arm,
        six_arm=six_arm,
        spy=spy,
        spy_dd=spy_dd,
        tag=tag,
        verdict=verdict,
        extras=extras,
        pin_delta=pin_delta,
        wrl_meta=wrl_meta,
        sources=sources,
        generated=generated,
    )
    (OUT_DIR / "compare.html").write_text(html, encoding="utf-8")
    _write_md(
        tag=tag,
        verdict=verdict,
        extras=extras,
        wrl_meta=wrl_meta,
        pin_delta=pin_delta,
        sources=sources,
    )
    summary = {
        "stamp": STAMP,
        "tag": tag,
        "verdict": verdict,
        "wires": False,
        "headline": "no-wire (system_performance 5-sys vs SPY)",
        "asof": ASOF.isoformat(),
        "five": five,
        "six": six,
        "spy_2012": extras["spy_2012"],
        "spy_asof": extras["spy_asof"],
        "spy_cagr": extras["spy_cagr"],
        "spy_max_dd_pct": extras["spy_dd_full"],
        "pin_5sys_nowire": PUB_5SYS_NOWIRE,
        "pin_5sys_wired": PUB_5SYS_WIRED,
        "pin_delta": pin_delta,
        "wrl_meta": wrl_meta,
        "fill_order": list(SIX),
        "universe_29": list(UNIVERSE_29),
        "original_request": ORIGINAL_REQUEST,
    }
    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    print(f"[ok] {tag} wrote {OUT_DIR / 'compare.html'}", flush=True)
    print(
        f"[ok] 5-sys YE2012={five['eq_2012']:.2f} asof={five['end']:.2f} "
        f"dd={five['max_dd_pct']:.2f}% cagr={five['wallet_cagr']*100:.2f}%",
        flush=True,
    )
    print(
        f"[ok] 6-sys YE2012={six['eq_2012']:.2f} asof={six['end']:.2f} "
        f"dd={six['max_dd_pct']:.2f}% cagr={six['wallet_cagr']*100:.2f}% "
        f"wrl_fills={six['n_wrl_fill']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
