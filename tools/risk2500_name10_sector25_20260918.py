#!/usr/bin/env python3
"""10% name + 25% sector sell-winner rotate (research only).

Stamp: drive/paul_experiments/risk2500_name10_sector25_20260918/

Same live-style freeze as risk_1pct_50k_adv_10name_20260917 (min(1% BOM, $50k)
+ 1% ADV20 + 10% per-name + $7,500 + 10.5% + 2× + sell-winner on empty BP)
plus one knob: 25% per-sector notional. If a new buy would push sector S over
25%, sell the winner in S, then buy. If still over, clip; skip if leftover
room < $1.

Control = published / re-run 10% name book (no sector cap). Not 17.5% live-style.
Not gold. Not DailyRun. Do not retune on OOS.
"""
from __future__ import annotations

import csv
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

STAMP = "risk2500_name10_sector25_20260918"
OUT_DIR = REPO / "drive" / "paul_experiments" / STAMP
SIBLING = REPO / "drive" / "paul_experiments" / "risk_1pct_50k_adv_10name_20260917"
YF_CACHE = REPO / "yfinance_cache.json"
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
SECTOR_CAP = 0.25
FIVE = f.FIVE
FIVE_RANK = f.FIVE_RANK
DD_DEF = m.DD_DEF
HUGE = 10_000_000.0
YEARS = (ASOF - date(2010, 1, 1)).days / 365.25
PUB_WIRE_FULL = 1_500_000.0

# Published 10% name, no sector (sibling stamp). Re-run as one-knob control.
PUB_10NAME = {
    "end": 46_721_908.64517073,
    "eq_2010": 247_849.74678970926,
    "eq_2011": 266_502.61332335835,
    "eq_2012": 238_607.360133584,
    "max_dd_pct": 25.655335147274894,
    "peak_reserved": 22_499_226.4652485,
    "peak_name": 4_627_379.9394834265,
    "peak_name_symbol": "MSTR",
    "peak_name_frac": 0.1,
    "n_rotate": 16,
    "n_name_capped": 1618,
    "n_skip_name": 11,
    "withdrawals": 1_500_000.0,
    "tag": "HOLD",
}

ORIGINAL_REQUEST = (
    "let's look at 10% for single stock max and 25% for single sector max. "
    "how do we perform over time starting with $250k? everything else is the "
    "same. we pull $7500/month and we don't buy more than 1% ADV20 shares. "
    "min (1%risk/50k) if we get a buy signal of a stock in a sector that would "
    "put us over 25%, we sell the winner, then buy the new one."
)
PLAIN_ENGLISH = (
    "One $250,000 wallet, five sleeves — StockBee (SB), Relative Strength "
    "Index (RSI), Volume Zone (VZ), Magic Touch (MTS), Rocket Launcher (RL). "
    "Indicators (IND) is out. Pull $7,500 cash on the 1st. Pay 10.5% a year "
    "on whatever you borrowed. Open stock cost can be at most twice the "
    "account. Each month the dollars you may lose to the stop are the smaller "
    "of 1% of beginning-of-month (BOM) Closed-only equity and $50,000. RSI "
    "dollars in = that month’s risk ÷ 0.0651 (In-Sample average-loser freeze; "
    "do not retune after 2024). Other systems: shares = risk ÷ (entry − stop). "
    "Then: you may not buy more than 1% of that name’s last 20-session average "
    "daily volume (ADV20); one ticker may not hold more than 10% of whatever "
    "the account is worth right then (clip the new fill — do not sell a winner "
    "just because the name lid binds). New: one Yahoo sector (a GICS-like "
    "industry group — Global Industry Classification Standard is the official "
    "name; we use the checked-in Yahoo sector map, not official GICS codes) "
    "may not hold more than 25% of the account. If a new buy in sector S would "
    "go over 25%, sell the most profitable open lot already in S (last close "
    "versus entry), then take the new one. If you are still over 25% after "
    "that one sale, shrink the new fill to leftover sector room; skip if that "
    "room is under $1. When buying power is empty — a separate rule — sell "
    "the book-wide winner, then fill (same as the 10% name sibling). Tickers "
    "with no sector each sit in their own UNKNOWN:TICKER bucket so they do "
    "not pile into one fake sector. Yardstick is $250,000 in the S&P 500 "
    "tracker (SPY), dividends reinvested. Not gold. Not DailyRun."
)

ARM_SPEC: list[tuple[str, Optional[float], str, str, str]] = [
    (
        "name10",
        None,
        "5-sys · 1%+$50k · 1% ADV · 10% name (no sector cap)",
        "One-knob control — published sibling risk_1pct_50k_adv_10name_20260917. Same freeze minus the 25% sector lid.",
        "ALL_overlay_5sys_1pct_50k_adv_10name.csv",
    ),
    (
        "sec25",
        0.25,
        "5-sys · 1%+$50k · 1% ADV · 10% name · 25% sector",
        "Candidate — same book plus 25% per-sector notional. Overflow → sell sector winner, then buy; clip leftover room.",
        "ALL_overlay_5sys_1pct_50k_adv_10name_sector25.csv",
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


def _pct_of(n: int, den: int) -> str:
    if den <= 0:
        return "—"
    return f"{100.0 * n / den:.1f}%"


def _rel_change(a: float, b: float) -> float:
    if abs(b) < 1e-9:
        return 0.0
    return (a - b) / abs(b)


def _died(end: float, max_dd: float, start: float = ACCOUNT) -> bool:
    return bool(max_dd >= 90.0 or end < start * 0.10 or end < 10_000.0)


def build_sector_map(symbols: list[str]) -> tuple[dict[str, str], dict[str, Any], list[dict[str, str]]]:
    """Yahoo Finance sector from yfinance_cache.json. Unmapped → UNKNOWN:{TICKER}."""
    cache: dict[str, Any] = {}
    if YF_CACHE.exists():
        try:
            raw = json.loads(YF_CACHE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                cache = raw
        except (OSError, json.JSONDecodeError):
            cache = {}
    mapping: dict[str, str] = {}
    rows: list[dict[str, str]] = []
    mapped = 0
    unknown = 0
    used: dict[str, int] = {}
    for raw_sym in sorted({str(s).upper() for s in symbols if s}):
        info = cache.get(raw_sym) or {}
        if not isinstance(info, dict):
            info = {}
        sec = str(info.get("sector") or "").strip()
        ind = str(info.get("industry") or "").strip()
        if sec:
            mapping[raw_sym] = sec
            mapped += 1
            used[sec] = used.get(sec, 0) + 1
            src = "yfinance_cache.json"
        else:
            mapping[raw_sym] = f"UNKNOWN:{raw_sym}"
            unknown += 1
            used[mapping[raw_sym]] = used.get(mapping[raw_sym], 0) + 1
            src = "unmapped_own_bucket"
        rows.append(
            {
                "symbol": raw_sym,
                "sector": mapping[raw_sym],
                "yahoo_industry": ind,
                "source": src,
            }
        )
    meta = {
        "n_symbols": len(mapping),
        "n_mapped": mapped,
        "n_unknown": unknown,
        "coverage_pct": (100.0 * mapped / len(mapping)) if mapping else 0.0,
        "n_yahoo_sectors": sum(1 for k in used if not str(k).startswith("UNKNOWN:")),
        "sector_counts": dict(sorted(used.items(), key=lambda kv: (-kv[1], kv[0]))),
        "source": str(YF_CACHE.as_posix()),
        "unknown_rule": "each unmapped ticker is its own UNKNOWN:{TICKER} bucket",
    }
    return mapping, meta, rows


def write_sector_csv(rows: list[dict[str, str]]) -> Path:
    path = OUT_DIR / "sector_map.csv"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["symbol", "sector", "yahoo_industry", "source"])
        w.writeheader()
        w.writerows(rows)
    return path


def _led_pack(arm: dict[str, Any]) -> dict[str, Any]:
    led = arm["led"]
    st = arm["stats_full"]
    iso = arm.get("stats_is") or {}
    oos = arm.get("stats_oos") or {}
    n_fill = int(led.n_full) + int(led.n_scaled)
    end = float(led.end_equity)
    pack = {
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
        "peak_sector": float(getattr(led, "peak_sector_notional", 0.0) or 0.0),
        "peak_sector_name": getattr(led, "peak_sector_name", "") or "—",
        "peak_sector_frac": float(getattr(led, "peak_sector_frac", 0.0) or 0.0),
        "peak_sector_frac_name": getattr(led, "peak_sector_frac_name", "") or "—",
        "n_rotate": int(led.n_rotate),
        "n_sector_rotate": int(getattr(led, "n_sector_rotate", 0) or 0),
        "n_skip_sector": int(getattr(led, "n_skip_sector", 0) or 0),
        "n_sector_capped": int(getattr(led, "n_sector_capped", 0) or 0),
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
        "n_wd": int(led.n_wd),
        "n_wd_skip": int(led.n_wd_skip),
        "interest": float(led.interest),
        "withdrawals": float(led.withdrawals),
        "identity": float(led.identity_err),
        "wr": _num(st, "win_pct"),
        "avg": _num(st, "avg_pnl_pct"),
        "pf": _num(st, "pf"),
        "ann_ror": _num(st, "ann_ror"),
        "calmar": _num(st, "calmar"),
        "sharpe": _num(st, "sharpe"),
        "n": _num(st, "n"),
        "wr_is": _num(iso, "win_pct"),
        "avg_is": _num(iso, "avg_pnl_pct"),
        "n_is": _num(iso, "n"),
        "wr_oos": _num(oos, "win_pct"),
        "avg_oos": _num(oos, "avg_pnl_pct"),
        "n_oos": _num(oos, "n"),
    }
    pack["wallet_cagr"] = _cagr(end, ACCOUNT)
    pack["died"] = _died(end, pack["max_dd_pct"])
    pack["wires_full"] = pack["withdrawals"] + 1e-9 >= PUB_WIRE_FULL
    return pack


def _quality_worse(cand: dict[str, Any], ctrl: dict[str, Any]) -> bool:
    return (
        cand["wr"] + 0.25 < ctrl["wr"]
        and cand["avg"] + 0.25 < ctrl["avg"]
        and cand["max_dd_pct"] > ctrl["max_dd_pct"] + 2.0
    )


def _sector_changed(cand: dict[str, Any], ctrl: dict[str, Any]) -> bool:
    if cand["n_sector_rotate"] > 0 or cand["n_skip_sector"] > 0 or cand["n_sector_capped"] > 0:
        return True
    if abs(_rel_change(cand["end"], ctrl["end"])) >= 0.05:
        return True
    if abs(_rel_change(cand["eq_2012"], ctrl["eq_2012"])) >= 0.05:
        return True
    if abs(cand["peak_sector_frac"] - ctrl["peak_sector_frac"]) >= 0.02:
        return True
    return False


def _oos_softens(cand: dict[str, Any]) -> bool:
    if cand["n_oos"] < 20 or cand["n_is"] < 20:
        return False
    return cand["avg_oos"] + 0.50 < cand["avg_is"] or cand["wr_oos"] + 3.0 < cand["wr_is"]


def _verdict(
    books: dict[str, dict[str, Any]],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
    pin_note: str,
    sector_meta: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    ctrl = _led_pack(books["name10"])
    cand = _led_pack(books["sec25"])
    spy_asof = float(spy["tr_end"])
    spy_2012 = float(spy_dd["eq_2012"])
    changed = _sector_changed(cand, ctrl)
    qw = _quality_worse(cand, ctrl)
    oos_soft = _oos_softens(cand)
    still_huge = cand["end"] >= HUGE
    extras: dict[str, Any] = {
        "spy_asof": spy_asof,
        "spy_2012": spy_2012,
        "name10": ctrl,
        "sec25": cand,
        "sector_changed": changed,
        "quality_worse": qw,
        "oos_softens": oos_soft,
        "still_huge": still_huge,
        "account_dead": cand["died"],
        "ye2012_vs_spy": _vs_spy(cand["eq_2012"], spy_2012),
        "asof_vs_spy": _vs_spy(cand["end"], spy_asof),
        "ye2012_vs_ctrl": _rel_change(cand["eq_2012"], ctrl["eq_2012"]),
        "asof_vs_ctrl": _rel_change(cand["end"], ctrl["end"]),
        "pin_note": pin_note,
        "sector_meta": sector_meta,
    }
    lids = (
        f"Lids on the 25% sector book — $50k bound fills {cand['n_risk_50k_bound']} "
        f"({_pct_of(cand['n_risk_50k_bound'], cand['n_fill'])} of fills; "
        f"{cand['n_months_50k']} months at the $50k ceiling); "
        f"1% bound fills {cand['n_risk_1pct_bound']} "
        f"({_pct_of(cand['n_risk_1pct_bound'], cand['n_fill'])}); "
        f"ADV clipped {cand['n_adv_clipped']} "
        f"({_pct_of(cand['n_adv_clipped'], cand['n_fill'])}; "
        f"ADV skip {cand['n_skip_adv']}); "
        f"10% name-capped {cand['n_name_capped']} "
        f"({_pct_of(cand['n_name_capped'], cand['n_fill'])}; "
        f"name-skip {cand['n_skip_name']}); "
        f"sector rotates {cand['n_sector_rotate']}; sector-capped fills "
        f"{cand['n_sector_capped']}; sector-skip {cand['n_skip_sector']}; "
        f"BP sell-winner rotates {cand['n_rotate']}. "
        f"Peak name {format_money(cand['peak_name'])} {cand['peak_name_symbol']} "
        f"({cand['peak_name_frac']:.1%}); peak sector "
        f"{format_money(cand['peak_sector'])} {cand['peak_sector_name']} "
        f"(peak % {cand['peak_sector_frac']:.1%} {cand['peak_sector_frac_name']}). "
        f"Wires paid {format_money(cand['withdrawals'])} "
        f"({cand['n_wd']} months; skipped {cand['n_wd_skip']}). "
        f"Wallet CAGR {_fmt_cagr(cand['wallet_cagr'])}; book Ann ROR "
        f"{_fmt_pct(cand['ann_ror'])}."
    )
    path = (
        f"2010–2012 path — 25% sector {format_money(cand['eq_2010'])} / "
        f"{format_money(cand['eq_2011'])} / {format_money(cand['eq_2012'])}; "
        f"10% name-only {format_money(ctrl['eq_2010'])} / "
        f"{format_money(ctrl['eq_2011'])} / {format_money(ctrl['eq_2012'])}; "
        f"SPY {format_money(spy['years'].get(2010, {}).get('tr', 0))} / "
        f"{format_money(spy['years'].get(2011, {}).get('tr', 0))} / "
        f"{format_money(spy_2012)}."
    )
    vs_ctrl = (
        f"25% sector vs 10% name-only: year-end 2012 {format_money(cand['eq_2012'])} vs "
        f"{format_money(ctrl['eq_2012'])} ({_rel_change(cand['eq_2012'], ctrl['eq_2012']):+.1%}); "
        f"as-of {format_money(cand['end'])} vs {format_money(ctrl['end'])} "
        f"({_rel_change(cand['end'], ctrl['end']):+.1%}). "
        + (
            "The 25% sector lid + sector-winner rotate bound the book — it is not slack. "
            if changed
            else "The 25% sector lid barely moved the 10% name path. "
        )
    )
    vs_spy = (
        f"25% sector year-end 2012 {format_money(cand['eq_2012'])} vs SPY "
        f"{format_money(spy_2012)} ({_vs_spy(cand['eq_2012'], spy_2012)}); "
        f"as-of {format_money(cand['end'])} vs SPY {format_money(spy_asof)} "
        f"({_vs_spy(cand['end'], spy_asof)}). Max DD {_fmt_pct(cand['max_dd_pct'])}."
    )
    oos_note = (
        " Out-of-Sample quality softened versus In-Sample — HOLD, do not retune."
        if oos_soft
        else " Out-of-Sample is report-only; do not retune lids on OOS."
    )
    cap_note = ""
    if still_huge:
        cap_note = (
            f" As-of {format_money(cand['end'])} is still not a Fidelity-sized "
            "ending (1% still scales until equity hits $5M, then $50k) — wallet "
            "CAGR on the cash pile is the honest rate; book Ann ROR is capacity "
            "fiction once overlay dollars dwarf the seed."
        )
    tail = (
        f"{lids} {vs_ctrl}{vs_spy} {path} {pin_note} Sector map coverage "
        f"{sector_meta['n_mapped']}/{sector_meta['n_symbols']} "
        f"({sector_meta['coverage_pct']:.1f}%) from yfinance_cache.json; "
        f"{sector_meta['n_unknown']} unmapped as own UNKNOWN:TICKER buckets. "
        f"{oos_note}{cap_note} Not gold. Not DailyRun."
    )

    if cand["died"] or not cand["wires_full"]:
        tag = "DISMISS"
        why = (
            "the account died"
            if cand["died"]
            else "it could not pay every $7,500 wire"
        )
        prose = (
            f"DISMISS 10% name + 25% sector versus SPY — {why} "
            f"(as-of {format_money(cand['end'])}; Max DD {_fmt_pct(cand['max_dd_pct'])}; "
            f"withdrawn {format_money(cand['withdrawals'])} of "
            f"{format_money(PUB_WIRE_FULL)}; wires skipped {cand['n_wd_skip']}). {tail}"
        )
        return tag, prose, extras

    if oos_soft:
        tag = "HOLD"
        prose = (
            f"HOLD versus gold / DailyRun and versus adopting 25% sector — "
            f"Out-of-Sample softened (IS WR {cand['wr_is']:.1f}% / Avg {cand['avg_is']:.2f}% "
            f"vs OOS WR {cand['wr_oos']:.1f}% / Avg {cand['avg_oos']:.2f}%). "
            f"Do not retune. {tail}"
        )
        return tag, prose, extras

    if still_huge:
        tag = "HOLD"
        prose = (
            f"HOLD versus gold / DailyRun — 25% sector is in this book and the "
            f"$7,500 wires were paid, but as-of {format_money(cand['end'])} is still "
            f"capacity fiction. vs SPY: year-end 2012 "
            f"{'beats' if cand['eq_2012'] >= spy_2012 else 'loses to'} SPY; "
            f"as-of {'beats' if cand['end'] >= spy_asof else 'loses to'} SPY. {tail}"
        )
        return tag, prose, extras

    if qw:
        tag = "HOLD"
        prose = (
            f"HOLD versus the 10% name-only sibling — quality softened and we "
            f"do not adopt 25% sector from this one page. {tail}"
        )
        return tag, prose, extras

    if (
        cand["eq_2012"] >= spy_2012 * 0.9
        and cand["end"] >= spy_asof * 0.9
        and cand["max_dd_pct"] <= ctrl["max_dd_pct"] + 2.0
        and not qw
    ):
        tag = "KEEP"
        prose = (
            f"KEEP 25% sector + sector-winner rotate as a research candidate "
            f"on top of the 10% name freeze versus SPY "
            f"{'(and it bound fills)' if changed else '(lid barely bound)'} — "
            f"year-end 2012 and as-of stay in a human range and the wires were "
            f"paid. Still HOLD versus gold / DailyRun (one in-sample freeze, no "
            f"walk-forward). {tail}"
        )
        return tag, prose, extras

    tag = "HOLD"
    prose = (
        f"HOLD versus gold / DailyRun. 25% sector is in this book. vs SPY and "
        f"vs 10% name-only the picture is mixed — do not adopt from this one "
        f"page. {tail}"
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


def _headline_box(extras: dict[str, Any], tag: str) -> str:
    cls = "yes" if tag == "KEEP" else ("no" if tag == "DISMISS" else "holdtag")
    cand = extras["sec25"]
    ctrl = extras["name10"]
    died = "YES" if cand["died"] else "NO"
    return f"""
<div class="lead">
  <h2>Headline — 10% name + 25% sector, start $250k</h2>
  <p><strong class="{cls}">{html_mod.escape(tag)}</strong> · research only · not gold · not DailyRun</p>
  <p class="small">Same live-style freeze as the 10% name sibling, plus a 25%
  Yahoo-sector lid. Overflow → sell the winner in that sector, then buy.
  If still over, clip. Buying-power sell-winner is a separate book-wide rule.</p>
  <div class="cards">
    <div class="card card-shared">
      <h3>25% sector · year-end 2012 vs SPY</h3>
      <div class="metric">{format_money(cand['eq_2012'])}</div>
      <div class="small">SPY {format_money(extras['spy_2012'])} ·
      {html_mod.escape(_vs_spy(cand['eq_2012'], extras['spy_2012']))}</div>
    </div>
    <div class="card card-shared">
      <h3>25% sector · as-of {ASOF.isoformat()} vs SPY</h3>
      <div class="metric">{format_money(cand['end'])}</div>
      <div class="small">SPY {format_money(extras['spy_asof'])} ·
      {html_mod.escape(_vs_spy(cand['end'], extras['spy_asof']))}</div>
    </div>
    <div class="card">
      <h3>Did it die? Wires?</h3>
      <div class="metric">{died}</div>
      <div class="small">Max DD {_fmt_pct(cand['max_dd_pct'])}</div>
      <div class="small">Wires {format_money(cand['withdrawals'])} ·
      skipped {cand['n_wd_skip']} months</div>
    </div>
    <div class="card">
      <h3>Did 25% sector change 10% name-only?</h3>
      <div class="metric">{"YES" if extras["sector_changed"] else "NO"}</div>
      <div class="small">As-of {format_money(cand['end'])} vs
      {format_money(ctrl['end'])} ({extras['asof_vs_ctrl']:+.1%})</div>
      <div class="small">YE2012 {format_money(cand['eq_2012'])} vs
      {format_money(ctrl['eq_2012'])} ({extras['ye2012_vs_ctrl']:+.1%})</div>
      <div class="small">Sector rotates {cand['n_sector_rotate']} ·
      sector-capped {cand['n_sector_capped']} · skip {cand['n_skip_sector']}</div>
    </div>
    <div class="card">
      <h3>Peak single-name</h3>
      <div class="metric">{format_money(cand['peak_name'])}</div>
      <div class="small">{html_mod.escape(cand['peak_name_symbol'])} ·
      {cand['peak_name_frac']:.1%} of equity</div>
      <div class="small">10% name-only {format_money(ctrl['peak_name'])}
      {html_mod.escape(ctrl['peak_name_symbol'])} · {ctrl['peak_name_frac']:.1%}</div>
    </div>
    <div class="card">
      <h3>Peak single-sector</h3>
      <div class="metric">{format_money(cand['peak_sector'])}</div>
      <div class="small">{html_mod.escape(cand['peak_sector_name'])} ·
      peak % {cand['peak_sector_frac']:.1%}
      {html_mod.escape(cand['peak_sector_frac_name'])}</div>
      <div class="small">Control (no sector lid) {format_money(ctrl['peak_sector'])}
      {html_mod.escape(ctrl['peak_sector_name'])} · {ctrl['peak_sector_frac']:.1%}</div>
    </div>
    <div class="card">
      <h3>Wallet CAGR vs book Ann ROR</h3>
      <div class="metric">{_fmt_cagr(cand['wallet_cagr'])}</div>
      <div class="small">Book Ann ROR {_fmt_pct(cand['ann_ror'])}</div>
      <div class="small">If the pile is huge, book Ann ROR is capacity fiction.</div>
    </div>
  </div>
</div>"""


def _lead_table(
    books: dict[str, dict[str, Any]],
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
            ("Dies?", "text"),
            ("Peak book notional", "num"),
            ("Peak single-name", "num"),
            ("Peak name ticker", "text"),
            ("Peak name %", "num"),
            ("Peak sector $", "num"),
            ("Peak sector name", "text"),
            ("Peak sector %", "num"),
            ("Sector rotates", "num"),
            ("Sector-capped / skip", "text"),
            ("Name-capped", "num"),
            ("BP rotates", "num"),
            ("Wires paid", "num"),
            ("Wires skipped", "num"),
            ("Wallet CAGR", "num"),
            ("Book Ann ROR %", "num"),
        ]
    )
    packs = {k: _led_pack(books[k]) for k, *_ in ARM_SPEC}
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
            "NO",
            spy["tr_end"],
            spy["tr_end"],
            "SPY",
            1.0,
            spy["tr_end"],
            "SPY",
            1.0,
            0,
            "0 / 0",
            0,
            0,
            0.0,
            0,
            _cagr(float(spy["tr_end"]), ACCOUNT),
            None,
        ),
    ]
    caps = {k: cap for k, _frac, _lab, cap, _csv in ARM_SPEC}
    for key, _frac, _lab, _cap, _csv in ARM_SPEC:
        p = packs[key]
        rows.append(
            (
                books[key]["label"],
                caps[key],
                p["end"],
                p["eq_2010"],
                p["eq_2011"],
                p["eq_2012"],
                p["max_dd_pct"],
                _vs_spy(p["end"], spy["tr_end"]),
                "YES" if p["died"] else "NO",
                p["peak_reserved"],
                p["peak_name"],
                p["peak_name_symbol"],
                p["peak_name_frac"],
                p["peak_sector"],
                p["peak_sector_name"],
                p["peak_sector_frac"],
                p["n_sector_rotate"],
                f"{p['n_sector_capped']} / {p['n_skip_sector']}",
                p["n_name_capped"],
                p["n_rotate"],
                p["withdrawals"],
                p["n_wd_skip"],
                p["wallet_cagr"],
                p["ann_ror"],
            )
        )
    body = ""
    for rec in rows:
        (
            name, cap, end, y0, y1, y2, dd, vs, died, peak_b, peak_n, ticker,
            pfrac, peak_s, secn, sfrac, nsr, scsk, ncap, nrot, wd, wdskip,
            cagr, ror,
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
            f"<td>{html_mod.escape(str(died))}</td>"
            f"<td>{_m(peak_b)}</td>"
            f"<td>{_m(peak_n)}</td>"
            f"<td>{html_mod.escape(str(ticker))}</td>"
            f"<td>{_fmt_pct(100.0 * float(pfrac)) if pfrac is not None else '—'}</td>"
            f"<td>{_m(peak_s)}</td>"
            f"<td>{html_mod.escape(str(secn))}</td>"
            f"<td>{_fmt_pct(100.0 * float(sfrac)) if sfrac is not None else '—'}</td>"
            f"<td>{int(nsr)}</td>"
            f"<td>{html_mod.escape(str(scsk))}</td>"
            f"<td>{int(ncap)}</td>"
            f"<td>{int(nrot)}</td>"
            f"<td>{_m(wd)}</td>"
            f"<td>{int(wdskip)}</td>"
            f"<td>{_fmt_cagr(cagr) if cagr is not None else '—'}</td>"
            f"<td>{_fmt_pct(ror) if ror is not None else '—'}</td>"
            "</tr>"
        )
    last = packs["sec25"]
    last_row = (
        '<tr class="total-row"><th>Pinned (25% sector book)</th>'
        '<td class="small">Pinned</td>'
        f"<td>{format_money(last['end'])}</td>"
        f"<td>{format_money(last['eq_2010'])}</td>"
        f"<td>{format_money(last['eq_2011'])}</td>"
        f"<td>{format_money(last['eq_2012'])}</td>"
        f"<td>{_fmt_pct(last['max_dd_pct'])}</td>"
        f"<td>{html_mod.escape(_vs_spy(last['end'], spy['tr_end']))}</td>"
        f"<td>{'YES' if last['died'] else 'NO'}</td>"
        f"<td>{format_money(last['peak_reserved'])}</td>"
        f"<td>{format_money(last['peak_name'])}</td>"
        f"<td>{html_mod.escape(last['peak_name_symbol'])}</td>"
        f"<td>{_fmt_pct(100.0 * last['peak_name_frac'])}</td>"
        f"<td>{format_money(last['peak_sector'])}</td>"
        f"<td>{html_mod.escape(last['peak_sector_name'])}</td>"
        f"<td>{_fmt_pct(100.0 * last['peak_sector_frac'])}</td>"
        f"<td>{last['n_sector_rotate']}</td>"
        f"<td>{last['n_sector_capped']} / {last['n_skip_sector']}</td>"
        f"<td>{last['n_name_capped']}</td>"
        f"<td>{last['n_rotate']}</td>"
        f"<td>{format_money(last['withdrawals'])}</td>"
        f"<td>{last['n_wd_skip']}</td>"
        f"<td>{_fmt_cagr(last['wallet_cagr'])}</td>"
        f"<td>{_fmt_pct(last['ann_ror'])}</td></tr>"
    )
    return (
        '<p class="small">Click column headers to sort. Total row pinned. '
        "Dollar fields are uncapped ($nnn,nnn.nn). 10% name-only is the published "
        "sibling re-run (no sector lid). Dies = Max DD ≥ 90% or as-of &lt; 10% of "
        "start or as-of &lt; $10,000.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}{last_row}</tbody></table></div>"
    )


def _lid_table(books: dict[str, dict[str, Any]]) -> str:
    head = f._sortable_head(
        [
            ("Book", "text"),
            ("Sized fills", "num"),
            ("1% risk bound", "num"),
            ("$50k risk bound", "num"),
            ("Months at $50k", "num"),
            ("ADV clipped", "num"),
            ("ADV skip", "num"),
            ("10% name-capped", "num"),
            ("Name-skip", "num"),
            ("Sector rotates", "num"),
            ("Sector-capped fills", "num"),
            ("Sector-skip", "num"),
            ("BP sell-winner rotates", "num"),
            ("BP-skip", "num"),
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
            f"<td>{p['n_risk_50k_bound']}</td>"
            f"<td>{p['n_months_50k']}</td>"
            f"<td>{p['n_adv_clipped']}</td>"
            f"<td>{p['n_skip_adv']}</td>"
            f"<td>{p['n_name_capped']}</td>"
            f"<td>{p['n_skip_name']}</td>"
            f"<td>{p['n_sector_rotate']}</td>"
            f"<td>{p['n_sector_capped']}</td>"
            f"<td>{p['n_skip_sector']}</td>"
            f"<td>{p['n_rotate']}</td>"
            f"<td>{p['n_skip_bp']}</td>"
            "</tr>"
        )
    last = _led_pack(books["sec25"])
    last_row = (
        '<tr class="total-row"><th>Pinned (25% sector)</th>'
        f"<td>{last['n_fill']}</td>"
        f"<td>{last['n_risk_1pct_bound']}</td>"
        f"<td>{last['n_risk_50k_bound']}</td>"
        f"<td>{last['n_months_50k']}</td>"
        f"<td>{last['n_adv_clipped']}</td>"
        f"<td>{last['n_skip_adv']}</td>"
        f"<td>{last['n_name_capped']}</td>"
        f"<td>{last['n_skip_name']}</td>"
        f"<td>{last['n_sector_rotate']}</td>"
        f"<td>{last['n_sector_capped']}</td>"
        f"<td>{last['n_skip_sector']}</td>"
        f"<td>{last['n_rotate']}</td>"
        f"<td>{last['n_skip_bp']}</td></tr>"
    )
    return (
        '<p class="small">How often each lid binds. Sector rotate is <em>not</em> '
        "the same as buying-power sell-winner (book-wide). Click headers to sort. "
        "Total row pinned.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}{last_row}</tbody></table></div>"
    )


def _year_table(
    books: dict[str, dict[str, Any]],
    spy: dict[str, Any],
    spy_dd: dict[str, Any],
) -> str:
    labels = [
        ("name10", "10% name-only"),
        ("sec25", "10% name + 25% sector"),
    ]
    head = f._sortable_head(
        [("Year-end", "num")]
        + [(lab, "num") for _k, lab in labels]
        + [
            ("SPY total return", "num"),
            ("10% name Max DD%", "num"),
            ("25% sector Max DD%", "num"),
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
        ),
    ]
    for key, lab in (
        ("name10", "10% name-only (control)"),
        ("sec25", "10% name + 25% sector"),
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
    last_led = books["sec25"]["led"]
    last = (
        '<tr class="total-row"><th>Pinned (25% sector)</th>'
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
    keys_order = ["name10", "sec25"]
    labs = {
        "name10": "10% name-only EOM",
        "sec25": "25% sector EOM",
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
        "OOS": "Out-of-Sample — report-only. Do not pick 25% sector from this slice.",
        "FULL": verdict,
    }
    html = ""
    for sl in ("IS", "OOS", "FULL"):
        cols = [
            ("10% name-only (control)", books["name10"][col_map[sl]]),
            ("10% name + 25% sector", books["sec25"][col_map[sl]]),
        ]
        html += f"""
<section>
<h2>Canonical compare · {sl}</h2>
<p class="small">{html_mod.escape(notes[sl])} Sheet / Total PnL $ omitted. Click headers to sort. Δ vs 10% name-only.</p>
<div class="table-wrap">{f._canonical_table(cols)}</div>
</section>"""
    return html


def _sector_cov_table(meta: dict[str, Any]) -> str:
    counts = meta.get("sector_counts") or {}
    head = f._sortable_head(
        [("Sector (Yahoo / own bucket)", "text"), ("Tickers in 5-sys book", "num")]
    )
    body = ""
    for name, n in counts.items():
        body += (
            f"<tr><td>{html_mod.escape(str(name))}</td><td>{int(n)}</td></tr>"
        )
    last = (
        f'<tr class="total-row"><th>Total tickers</th><td>{int(meta.get("n_symbols") or 0)}</td></tr>'
    )
    return (
        '<p class="small">Yahoo Finance sector from checked-in '
        "<code>yfinance_cache.json</code> (GICS-like — Global Industry "
        "Classification Standard — not official GICS codes). Unmapped tickers "
        "each get their own UNKNOWN:TICKER bucket. Click headers to sort.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}{last}</tbody></table></div>"
    )


def _acronyms() -> str:
    return (
        '<p class="small">Acronyms first use: StockBee (SB); Relative Strength '
        "Index (RSI); Volume Zone (VZ); Magic Touch (MTS); Rocket Launcher (RL); "
        "Indicators (IND); average daily volume (ADV); beginning-of-month (BOM); "
        "buying power (BP); In-Sample (IS); Out-of-Sample (OOS); S&amp;P 500 "
        "tracker (SPY); Global Industry Classification Standard (GICS); "
        "year-end (YE).</p>"
    )


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
    sector_meta: dict[str, Any],
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
{f._ledger_table(books[key]['snaps'], risk_col="Month risk $", bind_cols=True, sector_cols=True)}
</section>"""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>5-sys 10% name + 25% sector — {STAMP}</title>
<style>{f._css()}</style></head><body>
<h1>Monthly Backtest Report — {ASOF.year} · 10% name + 25% sector · start $250k</h1>
<p class="sub">
Stamp <code>{STAMP}</code>. Research only. <strong>Not gold. Not DailyRun.</strong>
Indicators (IND) out. Generated {html_mod.escape(gen_s)}. Click column headers to sort.
Dollar fields uncapped.
</p>
{_ask_block()}
{_headline_box(extras, tag)}
<div class="hold"><strong>{html_mod.escape(verdict)}</strong></div>
<div class="warn">
<strong>2010–2012 first.</strong> Do not judge only on later-year paper dollars.
We did not switch to official live-style 17.5% name. Out-of-Sample is report-only.
</div>
<section>
<h2>2010–2012 path</h2>
{_path_2010_2012(books, spy, spy_dd)}
</section>
<section>
<h2>Books + SPY at a glance</h2>
{_lead_table(books, spy, spy_dd)}
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
<section>
<h2>Sector map coverage</h2>
<p class="small">Mapped {sector_meta['n_mapped']} / {sector_meta['n_symbols']}
({sector_meta['coverage_pct']:.1f}%). Unmapped {sector_meta['n_unknown']} as own
buckets. Freeze file: <code>sector_map.csv</code>.</p>
{_sector_cov_table(sector_meta)}
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
Sibling 10% name (no sector):
<a href="../risk_1pct_50k_adv_10name_20260917/compare.html">risk_1pct_50k_adv_10name_20260917</a>.</p>
{_acronyms()}
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
    sector_meta: dict[str, Any],
) -> str:
    now = generated.astimezone(ET)
    gen_s = now.strftime("%Y-%m-%d %H:%M %Z")
    sources_html = "".join(f"<li>{html_mod.escape(s)}</li>" for s in sources)
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Compare — 10% name + 25% sector vs 10% name-only vs SPY — {STAMP}</title>
<style>{f._css()}</style></head><body>
<h1>Compare — 10% name + 25% sector · start $250k</h1>
<p class="sub">
Stamp <code>{STAMP}</code>. Research only. <strong>Not gold. Not DailyRun.</strong>
Generated {html_mod.escape(gen_s)}. Click column headers to sort. Dollar fields uncapped.
</p>
{_ask_block()}
{_headline_box(extras, tag)}
<div class="hold"><strong>{html_mod.escape(verdict)}</strong></div>
<section>
<h2>2010–2012 path</h2>
{_path_2010_2012(books, spy, spy_dd)}
</section>
<section>
<h2>Books + SPY at a glance</h2>
{_lead_table(books, spy, spy_dd)}
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
<h2>Sector map coverage</h2>
<p class="small">Mapped {sector_meta['n_mapped']} / {sector_meta['n_symbols']}
({sector_meta['coverage_pct']:.1f}%). Unmapped {sector_meta['n_unknown']} as own
buckets. Freeze file: <code>sector_map.csv</code>.</p>
{_sector_cov_table(sector_meta)}
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
Sibling 10% name (no sector):
<a href="../risk_1pct_50k_adv_10name_20260917/compare.html">risk_1pct_50k_adv_10name_20260917</a>.</p>
{_acronyms()}
</section>
{f.r.monthly._SORTABLE_TABLE_SCRIPT}
</body></html>"""


def _book_bullet(title: str, arm: dict[str, Any]) -> str:
    led = arm["led"]
    st = arm["stats_full"]
    iso = arm["stats_is"]
    oos = arm["stats_oos"]
    p = _led_pack(arm)
    return (
        f"- **{title}** end **${led.end_equity:,.2f}**; 2010 ${led.eq_2010:,.2f}; "
        f"2011 ${led.eq_2011:,.2f}; 2012 ${led.eq_2012:,.2f}; "
        f"Max DD {_fmt_pct(led.max_dd_pct)} (peak ${led.max_dd_peak:,.2f} → "
        f"trough ${led.max_dd_trough:,.2f}); interest ${led.interest:,.2f}; "
        f"withdrawn ${led.withdrawals:,.2f} (skipped {led.n_wd_skip}); "
        f"BP rotates {led.n_rotate}; sector rotates {p['n_sector_rotate']}; "
        f"fills {led.n_full + led.n_scaled} (full {led.n_full} / scaled {led.n_scaled}); "
        f"$50k-bound {led.n_risk_50k_bound}; 1%-bound {led.n_risk_1pct_bound}; "
        f"months at $50k {led.n_months_50k}; ADV clip {led.n_adv_clipped}; "
        f"ADV skip {led.n_skip_adv}; name-capped {led.n_name_capped}; "
        f"name-skip {led.n_skip_name}; sector-capped {p['n_sector_capped']}; "
        f"sector-skip {p['n_skip_sector']}; BP-skip {led.n_skip_bp}; "
        f"peak book ${led.peak_reserved:,.2f}; peak name ${led.peak_name_notional:,.2f} "
        f"({led.peak_name_symbol or '—'}, {led.peak_name_frac:.1%} of equity); "
        f"peak sector ${p['peak_sector']:,.2f} ({p['peak_sector_name']}, "
        f"peak % {p['peak_sector_frac']:.1%} {p['peak_sector_frac_name']}); "
        f"wallet CAGR {_fmt_cagr(p['wallet_cagr'])}; book Ann ROR {_fmt_pct(p['ann_ror'])}; "
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
    pin_note: str,
    sector_meta: dict[str, Any],
) -> None:
    cand = extras["sec25"]
    ctrl = extras["name10"]
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
        "- One stamp, one added knob: **25% per-sector notional + sell the sector winner, then buy** on top of the published 10% name live-style freeze.",
        "- Control = sibling `risk_1pct_50k_adv_10name_20260917` (10% name, no sector). Re-run here so both arms share this engine.",
        "- Not official live-style 17.5% name. Not frozen $2,500. Not 5% name.",
        "- 5-sys: StockBee (SB), Relative Strength Index (RSI), Volume Zone (VZ), Magic Touch (MTS), Rocket Launcher (RL). IND out.",
        "- Start $250,000; one wallet; $7,500 cash on the 1st; 10.5% actual/365 on debit; open notional ≤ 2× equity.",
        "- Monthly risk: **min(1% of BOM Closed-only equity, $50,000)**.",
        "- RSI: invested = risk_dollar / 0.06509607 (In-Sample avg-loss freeze; do not retune OOS).",
        "- Others: shares = risk_dollar / (entry − stop), then ADV 1%, name 10% (clip), sector 25% (sell-winner then clip), then remaining buying power.",
        "- Name overflow: **clip** the new fill. Same-ticker open lots share the 10% room. Do not sell-winner just for name.",
        "- Sector overflow: **sell the winner in that sector** (most profitable open lot in S, last close vs entry), then buy. If still over 25% after one sale, clip to leftover sector room; skip if room < $1.",
        "- Buying power empty (separate): sell book-wide most profitable, then fill.",
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
        "- Name lid: **open notional ≤ 10% of current (cash + reserved) equity** after ADV, before sector / buying-power. Same-ticker lots share the room. CLIP, do not rotate.",
        "- Sector lid: **open notional ≤ 25% of current equity** after name. One sale of the sector winner, then clip leftover room.",
        "- Room rule (BP): **sell winner** when buying power < $1 (book-wide, not sector).",
        "- In-Sample (IS) = `entry_date < 2024-01-01`. OOS report-only. Do not retune lids on OOS.",
        "- Same Closed / Open pins as `risk2500_monthly_20260917` overlays (RSI = avg-loss CSV).",
        "- Fill order: older closes; DailyRun system then symbol; same-day exits.",
        f"- Control pin: {pin_note}",
        "",
        "## Sector map (Yahoo, GICS-like)",
        "",
        "Sector here is **Yahoo Finance sector** (a Global Industry Classification Standard (GICS)-like grouping). It is **not** official GICS codes. Industry (Yahoo’s finer label) is stored on the freeze CSV and is **not** the cap bucket.",
        "",
        f"- Source: `{YF_CACHE.as_posix()}` (checked-in).",
        f"- Freeze: `{STAMP}/sector_map.csv`.",
        f"- Coverage: **{sector_meta['n_mapped']} / {sector_meta['n_symbols']}** mapped ({sector_meta['coverage_pct']:.1f}%).",
        f"- Unmapped: **{sector_meta['n_unknown']}** — each ticker is its own `UNKNOWN:{{TICKER}}` bucket (they do not share a 25% pile; we do not skip the fill for a missing sector).",
        f"- Distinct Yahoo sectors: {sector_meta['n_yahoo_sectors']}.",
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
        _book_bullet("10% name-only control (no sector cap)", books["name10"]),
        _book_bullet("10% name + 25% sector (candidate)", books["sec25"]),
        "",
        "## Headline vs SPY / 10% name-only",
        "",
        f"- 25% sector year-end 2012: **${cand['eq_2012']:,.2f}** vs SPY **${extras['spy_2012']:,.2f}** ({_vs_spy(cand['eq_2012'], extras['spy_2012'])}).",
        f"- 25% sector as-of {ASOF.isoformat()}: **${cand['end']:,.2f}** vs SPY **${extras['spy_asof']:,.2f}** ({_vs_spy(cand['end'], extras['spy_asof'])}).",
        f"- vs 10% name-only YE2012 **${cand['eq_2012']:,.2f}** vs **${ctrl['eq_2012']:,.2f}** ({extras['ye2012_vs_ctrl']:+.1%}); as-of **${cand['end']:,.2f}** vs **${ctrl['end']:,.2f}** ({extras['asof_vs_ctrl']:+.1%}). Sector lid changed the path? **{'YES' if extras['sector_changed'] else 'NO'}**.",
        f"- Dies? **{'YES' if cand['died'] else 'NO'}**. Wires **${cand['withdrawals']:,.2f}** (skipped {cand['n_wd_skip']}).",
        f"- Peak name **${cand['peak_name']:,.2f}** {cand['peak_name_symbol']} ({cand['peak_name_frac']:.1%}). Peak sector **${cand['peak_sector']:,.2f}** {cand['peak_sector_name']} (peak % {cand['peak_sector_frac']:.1%} {cand['peak_sector_frac_name']}).",
        f"- Wallet CAGR {_fmt_cagr(cand['wallet_cagr'])}; book Ann ROR {_fmt_pct(cand['ann_ror'])}.",
        "",
        "## Honesty",
        "",
        "- This page is “how does THIS book perform over time vs SPY starting $250k.” The 10% name sibling is the one-knob control.",
        "- Judge 2010–2012 and whether the $7,500 wire survives — not later-year billions.",
        "- OOS is report-only. Do not retune 25% / 10% / $50k / ADV on OOS.",
        "- Official live-style 17.5% name was not used.",
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

**Product owner (PO)–aligned process:** one added knob (25% sector + sector-winner rotate) on a frozen live-style book. See `docs/HYPOTHESIS_TEST.md`.

## What you asked

> {ORIGINAL_REQUEST}

## In plain English

{PLAIN_ENGLISH}

| Field | Fill in |
|-------|---------|
| System / prefix | 5-sys {", ".join(FIVE)} (Indicators / IND out) |
| Baseline stamp | 10% name sibling `risk_1pct_50k_adv_10name_20260917`. Wallet engine `risk2500_five_sys_20260917` |
| Universe | House DailyRun 5-sys. Indicators (IND) excluded |
| **Evidence** | Paul: 10% single-stock max and 25% single-sector max; start $250k; $7,500/mo; 1% ADV20; min(1% risk, $50k); if a new buy would put a sector over 25%, sell the winner, then buy the new one |
| **Hypothesis** | Adding a 25% Yahoo-sector lid (sell sector winner, then buy; clip leftover) on top of the 10% name freeze keeps the account alive versus SPY at year-end 2012 / as-of and cuts sector pile-up versus 10% name alone |
| **Single knob vs 10% name** | Sector cap on (25% + sector-winner rotate) vs off. Name 10%, min(1%,$50k), 1% ADV, $7,500, 10.5%, 2× already on both |
| Frozen settings | $250k start. $7,500 on the 1st. 10.5% actual/365. Open ≤ 2×. Risk min(1% BOM, $50k). ADV 1% of ADV20. Name 10% clip. RSI 6.51% IS freeze. BP sell-winner when empty. Not 17.5% name |
| Alternatives | 10% name-only sibling. SPY $250k total return. Official live-style 17.5% name is a different freeze |
| Candidate stamps | `{STAMP}` monthly.html / compare.html |
| Metrics | YE2012 vs SPY; as-of vs SPY; Max DD; dies?; vs 10% name-only; peak name / peak sector; wires; wallet CAGR vs book Ann ROR; canonical IS/OOS (report-only) |
| **Trade-diff HTML** | N/A — size / wallet overlay (not an entry A/B) |
| ToS before path | N/A |
| ToS after path | N/A |
| **Decision** | {tag} — {verdict} |
| Reviewer | AI job risk2500_name10_sector25_20260918 |
| PO sign-off | no |
| Reconcile freeze / re-baseline done | no |
| DailyRun | not wired |

## Decision checklist

- [x] Evidence was the PO ask (10% name + 25% sector + sell sector winner + $250k + $7,500 + 1% ADV + min(1%,$50k))
- [x] One added knob versus the published 10% name sibling
- [x] Same Closed pins as the sibling $2,500 / 10% name stamps
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
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                out[k] = None
            else:
                out[k] = v
        else:
            out[k] = str(v)
    return out


def _pin_match(led: Any) -> str:
    end_ok = abs(float(led.end_equity) - PUB_10NAME["end"]) < 1.0
    ye_ok = abs(float(led.eq_2012) - PUB_10NAME["eq_2012"]) < 1.0
    dd_ok = abs(float(led.max_dd_pct) - PUB_10NAME["max_dd_pct"]) < 0.05
    if end_ok and ye_ok and dd_ok:
        return (
            f"10% name-only re-run matched published {SIBLING.name} "
            f"(as-of {format_money(led.end_equity)} / YE2012 {format_money(led.eq_2012)} / "
            f"Max DD {_fmt_pct(led.max_dd_pct)})."
        )
    return (
        f"10% name-only re-run vs published {SIBLING.name}: as-of "
        f"{format_money(led.end_equity)} vs {format_money(PUB_10NAME['end'])}; "
        f"YE2012 {format_money(led.eq_2012)} vs {format_money(PUB_10NAME['eq_2012'])}; "
        f"Max DD {_fmt_pct(led.max_dd_pct)} vs {_fmt_pct(PUB_10NAME['max_dd_pct'])}. "
        "This page uses the re-run so both arms share one engine."
    )


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
    symbols = [t.symbol for t in static]
    sector_map, sector_meta, sector_rows = build_sector_map(symbols)
    write_sector_csv(sector_rows)
    print(
        f"[sector] mapped {sector_meta['n_mapped']}/{sector_meta['n_symbols']} "
        f"({sector_meta['coverage_pct']:.1f}%) unknown={sector_meta['n_unknown']}",
        flush=True,
    )

    sources = [
        f"overlays: {f.PREV_DIR.name} (RSI = RSI_overlay_avgloss.csv IS 6.51% freeze)",
        f"5-sys: {', '.join(FIVE)} — Indicators (IND) out",
        f"SPY: {f.SPY_PATH.as_posix()} Adj Close total return + Close price-only",
        "wallet: tools/risk2500_five_sys_20260917.py run_wallet "
        "name_cap_frac=0.10 max_risk_dollar=50000 adv_frac=0.01 sector_cap_frac=0.25",
        f"control: {SIBLING.name} 10% name, no sector (re-run on this engine)",
        "sector map: yfinance_cache.json Yahoo sector (GICS-like); freeze sector_map.csv; "
        "unmapped = own UNKNOWN:{TICKER} bucket",
        "name lid: clip only (do not sell-winner for name overflow)",
        "sector lid: sell winner in S, then buy; if still over, clip leftover room",
        "BP empty: book-wide sell-winner (separate from sector)",
        "not official live-style 17.5% name",
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
            name_cap_frac=NAME_CAP,
            max_risk_dollar=MAX_RISK,
            adv_frac=ADV_FRAC,
            start_equity=ACCOUNT,
            sector_cap_frac=frac,
            sector_map=sector_map if frac else None,
        )
        arm["short"] = arm["label"]
        arm["read"] = "Research only. Not gold."
        books[key] = arm
        f.r.write_overlay_csv(arm["trades"], OUT_DIR / csv_name)

    pin_note = _pin_match(books["name10"]["led"])
    print(f"[pin] {pin_note}", flush=True)

    tag, verdict, extras = _verdict(books, spy, spy_dd, pin_note, sector_meta)
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
        sector_meta=sector_meta,
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
        sector_meta=sector_meta,
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
        pin_note=pin_note,
        sector_meta=sector_meta,
    )
    write_hypothesis(tag, verdict)

    summary = {
        "tag": tag,
        "verdict": verdict,
        "pin_note": pin_note,
        "spy_tr_end": spy["tr_end"],
        "spy_2012": spy_dd["eq_2012"],
        "spy_max_dd_pct": spy_dd["full_dd"],
        "years": YEARS,
        "name10": _jsonable(_led_pack(books["name10"])),
        "sec25": _jsonable(_led_pack(books["sec25"])),
        "sector_meta": _jsonable(sector_meta),
        "extras": _jsonable(extras),
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"wrote {OUT_DIR / 'monthly.html'}", flush=True)
    print(f"wrote {OUT_DIR / 'compare.html'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
