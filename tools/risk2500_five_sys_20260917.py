#!/usr/bin/env python3
"""Five-system one-wallet 2× + 10.5% margin interest (research only).

Stamp: drive/paul_experiments/risk2500_five_sys_20260917/
Does not overwrite risk2500_monthly_20260917/monthly.html.

Systems: StockBee (SB), Relative Strength Index (RSI), Volume Zone (VZ),
Magic Touch (MTS), Rocket Launcher (RL). Drops BRT, YH, WPBR, RS, Indicators (IND).

Real-world freeze: one $250k wallet, BOM 1%, RSI slot = risk/0.0651 (IS freeze),
open notional ≤ 2× Closed-only equity, 10.5% annual on the debit, scale-down /
skip if remaining buying power < $1. Rotation arms only fire when a new signal
cannot take even a $1 scaled fill. Not gold. Not DailyRun.
"""
from __future__ import annotations

import html as html_mod
import importlib.util
import json
import math
import sys
from collections import defaultdict
from copy import copy
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))

from compare_format import (  # noqa: E402
    format_money,
    format_money_delta,
    is_excluded_html_compare_label,
)

_SPEC = importlib.util.spec_from_file_location(
    "risk2500_monthly_20260917",
    REPO / "tools" / "risk2500_monthly_20260917.py",
)
r = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules["risk2500_monthly_20260917"] = r
_SPEC.loader.exec_module(r)

_CSPEC = importlib.util.spec_from_file_location(
    "risk2500_monthly_compound_20260917",
    REPO / "tools" / "risk2500_monthly_compound_20260917.py",
)
c = importlib.util.module_from_spec(_CSPEC)
assert _CSPEC.loader is not None
sys.modules["risk2500_monthly_compound_20260917"] = c
_CSPEC.loader.exec_module(c)

STAMP = "risk2500_five_sys_20260917"
OUT_DIR = REPO / "drive" / "paul_experiments" / STAMP
PREV_DIR = r.OUT_DIR
ACCOUNT = r.ACCOUNT
RISK_FRAC = 0.01
MIN_DEPLOY = 1.0
LEVERAGE = 2.0
MARGIN_RATE = 0.105
WITHDRAW = 7_500.0
ASOF = r.ASOF
START = date(2010, 1, 1)
ET = r.ET
IS_CUT = r.IS_CUT
SPY_PATH = REPO / "data" / "newdata" / "data" / "SPY.csv"

# DailyRun report order among the five (same relative rank as the 9-sys 2× book).
FIVE: tuple[str, ...] = ("RL", "MTS", "SB", "VZ", "RSI")
NINE: tuple[str, ...] = tuple(r.SYSTEMS)
DROPPED = tuple(s for s in NINE if s not in FIVE)
SYSTEM_EXPAND = r.SYSTEM_EXPAND
FIVE_RANK = {sys: i for i, sys in enumerate(FIVE)}
NINE_RANK = {sys: i for i, sys in enumerate(NINE)}

# Published 9-sys 2× book (no interest) from sibling stamp — do not silently mutate.
PUB_9SYS_2X_END = 314_354_539_346.99
PUB_9SYS_2X_2010 = 471_305.91
PUB_1X_END = 660_865_483.66

ORIGINAL_REQUEST = (
    "if we had invested $250k in the S&P 500 at the beginning of 2010, how much "
    "would we have? great - thank you. based on this and the analysis of my "
    "actual trades, how should we proceed moving forward? (I have been transferring "
    "$7,500 to my bank almost monthly so this will account for the difference in "
    "balance) what would the monthly report look like if we kept only SB, RSI, VZ, "
    "MTS, and RL? what would it look like if we sold the current biggest loser, in "
    "order to make room for a new position that we otherwise wouldn't have room for? "
    "what if we sold the oldest position? what if we sold the most profitable "
    "position? when you are calculating this, please remember I pay 10.5% for any "
    "money borrowed in margin."
)
PLAIN_ENGLISH = (
    "Four asks in one job. (1) Buy-and-hold: put $250,000 into the S&P 500 "
    "tracker SPY on the first trading day of 2010 and leave it alone — that is "
    "the yardstick. We use SPY Adjusted Close so dividends are reinvested "
    "(total return); we also print the price-only number so you can see the gap. "
    "(2) Paper book with only five DailyRun sleeves — StockBee (SB), Relative "
    "Strength Index (RSI), Volume Zone (VZ), Magic Touch (MTS), Rocket Launcher "
    "(RL) — sharing one $250,000 wallet. Each month you risk 1% of whatever "
    "the account is worth after closed trades. RSI still uses the In-Sample "
    "average-loser freeze 6.51% (do not retune after 2024): dollars in = that "
    "month’s 1% ÷ 0.0651. Other systems: shares = 1% ÷ (entry − stop). You may "
    "borrow so open stock cost is at most twice the account, and you pay 10.5% "
    "a year on the borrowed part (this was missing from the $314 billion page). "
    "If a fill would blow the 2× cap we shrink it to leftover buying power; if "
    "leftover buying power is under $1 we skip — unless a rotation arm is on. "
    "(3) Rotation: only when a new signal has no buying power, sell one open "
    "name (biggest dollar loser, oldest, or biggest dollar winner — one rule "
    "per arm) at the last close we have that day, then take the new trade with "
    "whatever buying power the sale freed. No extra rules. (4) A second column "
    "pulls $7,500 cash on the first of each month the way you wire to the bank, "
    "even if that means a bigger margin loan. Live: the ~$58k hole versus $250k "
    "now is those wires, not a missing trading loss. None of this is gold or "
    "DailyRun. Later-year paper dollars can still be capacity fiction — read "
    "2010–2012 first."
)

LIVE_GAP_NOTE = (
    "Live reconstruction (late May 2026 go-live): realized −$191,885 on 112 lots; "
    "assumed start $500,000 → $500,000 − $191,885 = $308,115 vs ~$250,000 now → "
    "gap $58,115. $58,115 ÷ $7,500 = 7.75 months. Eight wires = $60,000 (within "
    "rounding / open mark −$1.7k / margin interest). Four post-go-live months "
    "(Jun–Sep 2026) = $30,000 — only half the gap — so the wires almost certainly "
    "started before or around early 2026, not only after go-live. No Fidelity "
    "wire CSV was found; Paul stated the $7,500 monthly bank transfer is the "
    "reconciliation. We take that as the cash-gap story."
)


@dataclass
class WalletSnap:
    year: int
    month: int
    equity_start: float
    cash_start: float
    reserved_start: float
    bp_start: float
    risk_dollar: float
    realized_pnl: float
    interest: float
    withdrawals: float
    equity_end: float
    cash_end: float
    reserved_end: float
    bp_end: float
    n_entries: int
    n_full: int
    n_scaled: int
    n_skip_bp: int
    n_skip_size: int
    n_risk_lt_1pct: int
    n_closes: int
    n_rotate: int
    n_wd: int
    n_wd_skip: int
    peak_reserved: float
    peak_loan: float
    max_dd_pct: float = 0.0
    running_max_dd_pct: float = 0.0
    mtm_end: float = 0.0
    n_name_capped: int = 0
    n_risk_1pct_bound: int = 0
    n_risk_50k_bound: int = 0
    n_adv_clipped: int = 0
    n_adv_missing: int = 0
    n_adv_last_known: int = 0
    n_skip_adv: int = 0
    n_sector_rotate: int = 0
    n_skip_sector: int = 0
    n_sector_capped: int = 0


@dataclass
class Ledger:
    n_full: int = 0
    n_scaled: int = 0
    n_skip_bp: int = 0
    n_skip_size: int = 0
    n_risk_lt_1pct: int = 0
    n_rotate: int = 0
    n_wd: int = 0
    n_wd_skip: int = 0
    peak_reserved: float = 0.0
    peak_equity: float = ACCOUNT
    peak_loan: float = 0.0
    end_cash: float = ACCOUNT
    end_reserved: float = 0.0
    end_equity: float = ACCOUNT
    end_bp: float = LEVERAGE * ACCOUNT
    end_mtm: float = ACCOUNT
    realized: float = 0.0
    interest: float = 0.0
    withdrawals: float = 0.0
    identity_err: float = 0.0
    n_fill_cap_ok: int = 0
    max_reserved_over_2x: float = 0.0
    eq_2010: float = ACCOUNT
    eq_2011: float = ACCOUNT
    eq_2012: float = ACCOUNT
    max_dd_pct: float = 0.0
    max_dd_peak: float = ACCOUNT
    max_dd_trough: float = ACCOUNT
    year_max_dd_pct: dict = field(default_factory=dict)
    year_running_max_dd_pct: dict = field(default_factory=dict)
    peak_name_notional: float = 0.0
    peak_name_symbol: str = ""
    peak_name_frac: float = 0.0
    n_name_capped: int = 0
    n_skip_name: int = 0
    name_cap_frac: float = 0.0
    max_risk_dollar: float = 0.0
    adv_frac: float = 0.0
    n_risk_1pct_bound: int = 0
    n_risk_50k_bound: int = 0
    n_adv_clipped: int = 0
    n_adv_missing: int = 0
    n_adv_last_known: int = 0
    n_skip_adv: int = 0
    n_months_50k: int = 0
    n_sector_rotate: int = 0
    n_skip_sector: int = 0
    n_sector_capped: int = 0
    sector_cap_frac: float = 0.0
    peak_sector_notional: float = 0.0
    peak_sector_name: str = ""
    peak_sector_frac: float = 0.0
    peak_sector_frac_name: str = ""


def _sys_key(t: r.OverlayTrade, rank: dict[str, int]) -> tuple[int, str, str]:
    return (rank.get(t.system, 99), t.system, t.symbol)


def _buying_power(cash: float, reserved: float) -> float:
    equity = cash + reserved
    return LEVERAGE * equity - reserved


def _loan(cash: float) -> float:
    return max(0.0, -cash)


def _apply_interest(cash: float, n_days: int) -> tuple[float, float]:
    """Daily compound at 10.5%/365 on a debit. Returns (new_cash, interest_paid)."""
    if n_days <= 0 or cash >= -1e-9:
        return cash, 0.0
    factor = (1.0 + MARGIN_RATE / 365.0) ** n_days
    new_cash = cash * factor
    paid = cash - new_cash
    if paid < 0:
        paid = 0.0
    return new_cash, paid


_CLOSE_CACHE: dict[str, list[tuple[date, float]]] = {}
_ADV_CACHE: dict[str, list[tuple[date, float]]] = {}
ADV_WINDOW = 20


def _closes(symbol: str) -> list[tuple[date, float]]:
    key = (symbol or "").strip().upper()
    if key in _CLOSE_CACHE:
        return _CLOSE_CACHE[key]
    df = r._load_ohlc(key)
    rows: list[tuple[date, float]] = []
    if df is not None and not df.empty:
        for ts, px in zip(df["Date"], df["Close"]):
            d = ts.date() if hasattr(ts, "date") else ts
            try:
                v = float(px)
            except (TypeError, ValueError):
                continue
            if math.isfinite(v) and v > 0:
                rows.append((d, v))
        rows.sort(key=lambda x: x[0])
    _CLOSE_CACHE[key] = rows
    return rows


def last_close(symbol: str, asof: date) -> Optional[float]:
    rows = _closes(symbol)
    if not rows:
        return None
    lo, hi = 0, len(rows) - 1
    ans = None
    while lo <= hi:
        mid = (lo + hi) // 2
        if rows[mid][0] <= asof:
            ans = rows[mid][1]
            lo = mid + 1
        else:
            hi = mid - 1
    return ans


def _adv20_rows(symbol: str) -> list[tuple[date, float]]:
    """20-session simple mean of on-disk daily share Volume (not dollar ADV)."""
    key = (symbol or "").strip().upper()
    if key in _ADV_CACHE:
        return _ADV_CACHE[key]
    df = r._load_ohlc(key)
    rows: list[tuple[date, float]] = []
    if df is not None and not df.empty and "Volume" in df.columns:
        vol = pd.to_numeric(df["Volume"], errors="coerce")
        adv = vol.rolling(ADV_WINDOW, min_periods=ADV_WINDOW).mean()
        for ts, v in zip(df["Date"], adv):
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(fv) or fv <= 0:
                continue
            d = ts.date() if hasattr(ts, "date") else ts
            rows.append((d, fv))
        rows.sort(key=lambda x: x[0])
    _ADV_CACHE[key] = rows
    return rows


def lookup_adv20(symbol: str, asof: date) -> tuple[Optional[float], str]:
    """Last ADV20 on or before asof. last_known if the bar is older than asof."""
    rows = _adv20_rows(symbol)
    if not rows:
        return None, "missing"
    lo, hi = 0, len(rows) - 1
    ans: Optional[tuple[date, float]] = None
    while lo <= hi:
        mid = (lo + hi) // 2
        if rows[mid][0] <= asof:
            ans = rows[mid]
            lo = mid + 1
        else:
            hi = mid - 1
    if ans is None:
        return None, "missing"
    if ans[0] < asof:
        return ans[1], "last_known"
    return ans[1], "full20"


def _max_dd_pct(vals: list[float]) -> float:
    """Peak-to-trough drawdown % walking a time-ordered equity series."""
    if not vals:
        return 0.0
    peak = vals[0]
    worst = 0.0
    for v in vals:
        if v > peak:
            peak = v
        if peak > 1e-12:
            dd = (peak - v) / peak
            if dd > worst:
                worst = dd
    return worst * 100.0


def _worst_dd_peak_trough(vals: list[float]) -> tuple[float, float, float]:
    """Return (max_dd_pct, peak_of_worst_episode, trough_of_worst_episode)."""
    if not vals:
        return 0.0, 0.0, 0.0
    peak = vals[0]
    trough = vals[0]
    worst = 0.0
    w_peak = vals[0]
    w_trough = vals[0]
    for v in vals:
        if v > peak:
            peak = v
            trough = v
        elif v < trough:
            trough = v
        if peak > 1e-12:
            dd = (peak - trough) / peak
            if dd > worst:
                worst = dd
                w_peak = peak
                w_trough = trough
    return worst * 100.0, w_peak, w_trough


def _mtm_dollar(t: r.OverlayTrade, asof: date) -> Optional[float]:
    if not t.sized or t.entry <= 0:
        return None
    px = last_close(t.symbol, asof)
    if px is None:
        return None
    return (px / t.entry - 1.0) * t.invested


def _pick_victim(
    opens: list[r.OverlayTrade],
    mode: str,
    asof: date,
) -> tuple[Optional[r.OverlayTrade], Optional[float]]:
    """Return (victim, last_close) for a rotation sale. No extra rules."""
    remaining = list(opens)
    while remaining:
        if mode == "oldest":
            victim = min(remaining, key=lambda t: (t.opened, t.system, t.symbol))
        elif mode == "loser":
            scored: list[tuple[float, date, str, str, r.OverlayTrade]] = []
            for t in remaining:
                mtm = _mtm_dollar(t, asof)
                if mtm is None:
                    continue
                scored.append((mtm, t.opened, t.system, t.symbol, t))
            if not scored:
                return None, None
            victim = min(scored, key=lambda x: (x[0], x[1], x[2], x[3]))[-1]
        elif mode == "winner":
            scored = []
            for t in remaining:
                mtm = _mtm_dollar(t, asof)
                if mtm is None:
                    continue
                scored.append((mtm, t.opened, t.system, t.symbol, t))
            if not scored:
                return None, None
            victim = max(scored, key=lambda x: (x[0], -x[1].toordinal(), x[2], x[3]))[-1]
        else:
            return None, None
        px = last_close(victim.symbol, asof)
        if px is not None and victim.entry > 0:
            return victim, px
        remaining = [t for t in remaining if t is not victim]
    return None, None


def _risk_note(desired: r.OverlayTrade, shares: float, invested: float) -> tuple[str, bool]:
    risk = float(desired.risk_dollar or 0.0)
    lt = False
    bits: list[str] = []
    if desired.system == "RSI":
        want = float(desired.invested or 0.0)
        if want > 0 and invested + 1e-6 < want:
            bits.append("rsi_slot_lt_1pct_typical")
            lt = True
    elif desired.stop_used and desired.entry > desired.stop_used and shares > 0:
        actual = shares * (desired.entry - desired.stop_used)
        if risk > 0 and actual + 0.01 < risk:
            bits.append(f"risk_lt_1pct:{actual:.2f}<{risk:.2f}")
            lt = True
    return ";".join(bits), lt


def _clip_to_bp(desired: r.OverlayTrade, bp: float) -> tuple[r.OverlayTrade, bool]:
    extra = {
        "cash_before": float(bp),
        "desired_invested": float(desired.invested) if desired.sized else 0.0,
        "scaled": False,
    }
    if not desired.sized:
        return (
            r.OverlayTrade(
                **{
                    **desired.__dict__,
                    **extra,
                    "skip_reason": desired.skip_reason or "cannot_size",
                }
            ),
            False,
        )
    if bp < MIN_DEPLOY:
        return (
            r.OverlayTrade(
                **{
                    **desired.__dict__,
                    **extra,
                    "shares": 0.0,
                    "invested": 0.0,
                    "overlay_pnl": 0.0,
                    "sized": False,
                    "scaled": False,
                    "skip_reason": "bp_empty",
                }
            ),
            False,
        )
    invested = min(float(desired.invested), float(bp))
    if invested < MIN_DEPLOY:
        return (
            r.OverlayTrade(
                **{
                    **desired.__dict__,
                    **extra,
                    "shares": 0.0,
                    "invested": 0.0,
                    "overlay_pnl": 0.0,
                    "sized": False,
                    "scaled": False,
                    "skip_reason": "bp_too_small",
                }
            ),
            False,
        )
    scaled = invested + 1e-6 < float(desired.invested)
    shares = invested / desired.entry
    overlay_pnl = (desired.pnl_pct / 100.0) * invested
    note = desired.stop_src or ""
    risk_lt = False
    if scaled:
        extra_note, risk_lt = _risk_note(desired, shares, invested)
        note = (note + ";").lstrip(";") + f"scaled_to_bp:{invested:.2f}"
        if extra_note:
            note += ";" + extra_note
    return (
        r.OverlayTrade(
            **{
                **desired.__dict__,
                **extra,
                "shares": shares,
                "invested": invested,
                "overlay_pnl": overlay_pnl,
                "sized": True,
                "scaled": scaled,
                "skip_reason": "",
                "stop_src": note,
            }
        ),
        risk_lt,
    )


def _apply_name_cap(
    desired: r.OverlayTrade,
    *,
    equity: float,
    already: float,
    frac: Optional[float],
) -> r.OverlayTrade:
    """Clip one fill so this ticker's open notional stays ≤ frac × current equity.

    Applied after 1% size and before the buying-power clip. Default off (frac None/0)
    so older stamps keep identity. Tight stops cannot buy the whole 2× book.
    """
    if frac is None or float(frac) <= 0 or not desired.sized:
        return desired
    room = max(0.0, float(frac) * max(float(equity), 0.0) - max(float(already), 0.0))
    pct = int(round(float(frac) * 100.0))
    if room < MIN_DEPLOY:
        return r.OverlayTrade(
            **{
                **desired.__dict__,
                "shares": 0.0,
                "invested": 0.0,
                "overlay_pnl": 0.0,
                "sized": False,
                "scaled": False,
                "skip_reason": "name_cap_empty",
            }
        )
    invested = min(float(desired.invested), room)
    if invested + 1e-6 >= float(desired.invested):
        return desired
    shares = invested / desired.entry
    overlay_pnl = (desired.pnl_pct / 100.0) * invested
    extra_note, _risk_lt = _risk_note(desired, shares, invested)
    note = (desired.stop_src or "")
    note = (note + ";").lstrip(";") + f"name_cap{pct}:{invested:.2f}"
    if extra_note:
        note += ";" + extra_note
    return r.OverlayTrade(
        **{
            **desired.__dict__,
            "shares": shares,
            "invested": invested,
            "overlay_pnl": overlay_pnl,
            "sized": True,
            "scaled": True,
            "skip_reason": "",
            "stop_src": note,
        }
    )


def _apply_sector_cap(
    desired: r.OverlayTrade,
    *,
    equity: float,
    already: float,
    frac: Optional[float],
) -> r.OverlayTrade:
    """Clip one fill so this sector's open notional stays ≤ frac × current equity.

    Applied after ADV + name cap and before the buying-power clip. Default off
    (frac None/0) so older stamps keep identity. One-sale rotate-then-clip is
    handled by run_wallet; this helper only clips leftover room.
    """
    if frac is None or float(frac) <= 0 or not desired.sized:
        return desired
    room = max(0.0, float(frac) * max(float(equity), 0.0) - max(float(already), 0.0))
    pct = int(round(float(frac) * 100.0))
    if room < MIN_DEPLOY:
        return r.OverlayTrade(
            **{
                **desired.__dict__,
                "shares": 0.0,
                "invested": 0.0,
                "overlay_pnl": 0.0,
                "sized": False,
                "scaled": False,
                "skip_reason": "sector_cap_empty",
            }
        )
    invested = min(float(desired.invested), room)
    if invested + 1e-6 >= float(desired.invested):
        return desired
    shares = invested / desired.entry
    overlay_pnl = (desired.pnl_pct / 100.0) * invested
    extra_note, _risk_lt = _risk_note(desired, shares, invested)
    note = (desired.stop_src or "")
    note = (note + ";").lstrip(";") + f"sector_cap{pct}:{invested:.2f}"
    if extra_note:
        note += ";" + extra_note
    return r.OverlayTrade(
        **{
            **desired.__dict__,
            "shares": shares,
            "invested": invested,
            "overlay_pnl": overlay_pnl,
            "sized": True,
            "scaled": True,
            "skip_reason": "",
            "stop_src": note,
        }
    )


def _apply_adv_cap(
    desired: r.OverlayTrade,
    *,
    asof: date,
    frac: Optional[float],
) -> r.OverlayTrade:
    """Clip shares to ≤ frac × ADV20 (share volume). Off when frac is None/0.

    ADV window = 20 on-disk daily Volume bars (simple mean). Lookup is the last
    session on or before the fill date. If that bar is older than the fill date,
    we use last known. If no 20-bar window exists, skip (adv_missing).
    """
    if frac is None or float(frac) <= 0 or not desired.sized:
        return desired
    adv, src = lookup_adv20(desired.symbol, asof)
    if adv is None or adv <= 0:
        return r.OverlayTrade(
            **{
                **desired.__dict__,
                "shares": 0.0,
                "invested": 0.0,
                "overlay_pnl": 0.0,
                "sized": False,
                "scaled": False,
                "skip_reason": "adv_missing",
            }
        )
    max_shares = float(frac) * float(adv)
    want = float(desired.shares)
    if want <= max_shares + 1e-9:
        note = (desired.stop_src or "")
        if src == "last_known":
            note = (note + ";").lstrip(";") + f"adv_last_known:{adv:.2f}"
            return r.OverlayTrade(**{**desired.__dict__, "stop_src": note})
        return desired
    shares = max_shares
    invested = shares * float(desired.entry)
    if invested < MIN_DEPLOY or shares <= 0:
        return r.OverlayTrade(
            **{
                **desired.__dict__,
                "shares": 0.0,
                "invested": 0.0,
                "overlay_pnl": 0.0,
                "sized": False,
                "scaled": False,
                "skip_reason": "adv_empty",
            }
        )
    overlay_pnl = (desired.pnl_pct / 100.0) * invested
    extra_note, _risk_lt = _risk_note(desired, shares, invested)
    note = (desired.stop_src or "")
    note = (note + ";").lstrip(";") + f"adv_cap{int(round(float(frac)*100))}:{shares:.4f}<{want:.4f}"
    if src == "last_known":
        note += f";adv_last_known:{adv:.2f}"
    if extra_note:
        note += ";" + extra_note
    return r.OverlayTrade(
        **{
            **desired.__dict__,
            "shares": shares,
            "invested": invested,
            "overlay_pnl": overlay_pnl,
            "sized": True,
            "scaled": True,
            "skip_reason": "",
            "stop_src": note,
        }
    )


def _force_rotate(
    t: r.OverlayTrade,
    *,
    sale: date,
    px: float,
    mode: str,
) -> None:
    """Close at last close on sale date. Mutates in place (same object as fill row)."""
    pnl_pct = (px / t.entry - 1.0) * 100.0
    t.closed = sale
    t.exit_px = px
    t.pnl_pct = pnl_pct
    t.overlay_pnl = (pnl_pct / 100.0) * t.invested
    t.days = float((sale - t.opened).days)
    t.exit_type = f"ROTATE_{mode.upper()}"
    t.status = "closed"
    t.stop_src = ((t.stop_src or "") + ";").lstrip(";") + f"rotated_{mode}@{sale.isoformat()}:{px:.4f}"


def run_wallet(
    trades: list[r.OverlayTrade],
    *,
    rank: dict[str, int],
    rotate: str = "none",
    withdraw: bool = False,
    through: date = ASOF,
    risk_frac: Optional[float] = None,
    name_cap_frac: Optional[float] = None,
    fixed_risk_dollar: Optional[float] = None,
    max_risk_dollar: Optional[float] = None,
    adv_frac: Optional[float] = None,
    start_equity: Optional[float] = None,
    sector_cap_frac: Optional[float] = None,
    sector_map: Optional[dict[str, str]] = None,
) -> tuple[list[r.OverlayTrade], list[WalletSnap], Ledger]:
    """One wallet. 2× cap. 10.5% daily-compound on debit. Optional rotation / $7,500 wd.

    risk_frac defaults to the frozen 1% monthly risk-to-stop. Passing another
    constant does not change DailyRun; it is a research size path only.
    name_cap_frac (optional): after 1% size and before fill, clip each ticker's
    open notional to ≤ that fraction of current Closed-only equity. Off by default.
    fixed_risk_dollar (optional): if set, every month's risk_dollar is this
    constant (does not scale with equity). Off by default so older 1% stamps
    keep identity.
    max_risk_dollar (optional): if set (and fixed_risk is off), monthly
    risk_dollar = min(risk_frac × BOM equity, this ceiling). Off by default.
    adv_frac (optional): after risk size and before name-cap / BP, clip shares
    to ≤ that fraction of ADV20 (20-session mean of on-disk daily Volume).
    Missing ADV skips the fill. Off by default so older stamps keep identity.
    start_equity (optional): Closed-only cash seed. Defaults to ACCOUNT ($250k)
    so older stamps keep identity. Research capital A/Bs only.
    sector_cap_frac (optional): after ADV + name cap, if a fill would push that
    Yahoo-sector's open notional over this fraction of current equity, sell the
    most profitable open lot in that sector (last close vs entry), then fill.
    If still over after one sale, clip to leftover sector room; skip if room
    is under $1. Off by default so older stamps keep identity. Unmapped tickers
    are each their own UNKNOWN:{TICKER} bucket (they do not share a pile).
    sector_map (optional): ticker → sector label. Ignored when sector_cap is off.
    Buying-power sell-winner stays a separate rule (book-wide, not sector).
    """
    seed = ACCOUNT if start_equity is None else float(start_equity)
    rf = RISK_FRAC if risk_frac is None else float(risk_frac)
    ncap = float(name_cap_frac) if name_cap_frac else 0.0
    freeze_risk = float(fixed_risk_dollar) if fixed_risk_dollar else 0.0
    risk_ceil = float(max_risk_dollar) if max_risk_dollar else 0.0
    afrac = float(adv_frac) if adv_frac else 0.0
    scap = float(sector_cap_frac) if sector_cap_frac else 0.0
    smap = {str(k).upper(): str(v) for k, v in (sector_map or {}).items() if v}
    led = Ledger()
    led.peak_equity = seed
    led.end_cash = seed
    led.end_equity = seed
    led.end_bp = LEVERAGE * seed
    led.end_mtm = seed
    led.eq_2010 = seed
    led.eq_2011 = seed
    led.eq_2012 = seed
    led.max_dd_peak = seed
    led.max_dd_trough = seed
    led.name_cap_frac = ncap
    led.max_risk_dollar = risk_ceil
    led.adv_frac = afrac
    led.sector_cap_frac = scap
    if not trades:
        return [], [], led

    by_open: dict[date, list[r.OverlayTrade]] = defaultdict(list)
    for t in trades:
        by_open[t.opened].append(t)

    month_starts = [
        date(y, m, 1)
        for y, m in c._month_range(date(2010, 1, 1), date(through.year, through.month, 1))
    ]
    event_days = set(month_starts)
    event_days.add(through)
    for t in trades:
        event_days.add(t.opened)
        if t.closed is not None and t.closed <= through:
            event_days.add(t.closed)
    days = sorted(d for d in event_days if START <= d <= through)

    cash = seed
    reserved = 0.0
    realized = 0.0
    interest = 0.0
    withdrawals = 0.0
    prev: Optional[date] = None
    def _month_risk(eq: float) -> float:
        if freeze_risk > 0:
            return freeze_risk
        raw = rf * max(eq, 0.0)
        if risk_ceil > 0:
            return min(raw, risk_ceil)
        return raw

    risk = _month_risk(seed)
    equity_bom = seed
    out: list[r.OverlayTrade] = []
    open_book: list[r.OverlayTrade] = []
    pending_close: dict[date, list[r.OverlayTrade]] = defaultdict(list)
    orig_closed: dict[int, Optional[date]] = {}
    snaps: list[WalletSnap] = []
    cur: Optional[dict[str, Any]] = None
    month_path: list[float] = []
    year_path: list[float] = []
    all_path: list[float] = [seed]
    name_open: dict[str, float] = defaultdict(float)
    sector_open: dict[str, float] = defaultdict(float)

    def _sector(sym: str) -> str:
        key = str(sym or "").upper()
        sec = smap.get(key, "")
        if sec:
            return sec
        return f"UNKNOWN:{key}" if key else "UNKNOWN"

    def _book_mtm(asof: date) -> float:
        eq = cash + reserved
        for t in open_book:
            u = _mtm_dollar(t, asof)
            if u is not None:
                eq += u
        return eq

    def _record_closed() -> None:
        eq = cash + reserved
        month_path.append(eq)
        year_path.append(eq)
        all_path.append(eq)

    def _record_mtm(asof: date) -> float:
        mtm = _book_mtm(asof)
        month_path.append(mtm)
        year_path.append(mtm)
        all_path.append(mtm)
        return mtm

    def _accrue_to(d: date) -> None:
        nonlocal cash, interest, prev
        if prev is None:
            prev = d
            return
        n = (d - prev).days
        cash, paid = _apply_interest(cash, n)
        if paid:
            interest += paid
            if cur is not None:
                cur["interest"] += paid
        prev = d

    def _bp() -> float:
        return _buying_power(cash, reserved)

    def _do_close(t: r.OverlayTrade) -> None:
        nonlocal cash, reserved, realized
        if not t.sized:
            return
        cash += t.invested + t.overlay_pnl
        reserved -= t.invested
        realized += t.overlay_pnl
        name_open[t.symbol] = max(0.0, name_open[t.symbol] - float(t.invested))
        if scap > 0:
            sec = _sector(t.symbol)
            sector_open[sec] = max(0.0, sector_open[sec] - float(t.invested))
        try:
            open_book.remove(t)
        except ValueError:
            pass

    def _finalize_month(end_eq_day: date) -> None:
        nonlocal cur
        if cur is None:
            return
        eq = cash + reserved
        if eq > led.peak_equity:
            led.peak_equity = eq
        asof = end_eq_day - timedelta(days=1) if end_eq_day.day == 1 else end_eq_day
        if asof < START:
            asof = START
        mtm = _record_mtm(asof)
        y = int(cur["year"])
        snaps.append(
            WalletSnap(
                year=cur["year"],
                month=cur["month"],
                equity_start=cur["equity_start"],
                cash_start=cur["cash_start"],
                reserved_start=cur["reserved_start"],
                bp_start=cur["bp_start"],
                risk_dollar=cur["risk_dollar"],
                realized_pnl=cur["realized_pnl"],
                interest=cur["interest"],
                withdrawals=cur["withdrawals"],
                equity_end=eq,
                cash_end=cash,
                reserved_end=reserved,
                bp_end=_bp(),
                n_entries=cur["n_entries"],
                n_full=cur["n_full"],
                n_scaled=cur["n_scaled"],
                n_skip_bp=cur["n_skip_bp"],
                n_skip_size=cur["n_skip_size"],
                n_risk_lt_1pct=cur["n_risk_lt_1pct"],
                n_closes=cur["n_closes"],
                n_rotate=cur["n_rotate"],
                n_wd=cur["n_wd"],
                n_wd_skip=cur["n_wd_skip"],
                peak_reserved=cur["peak_reserved"],
                peak_loan=cur["peak_loan"],
                max_dd_pct=_max_dd_pct(month_path),
                running_max_dd_pct=_max_dd_pct(all_path),
                mtm_end=mtm,
                n_name_capped=cur["n_name_capped"],
                n_risk_1pct_bound=cur["n_risk_1pct_bound"],
                n_risk_50k_bound=cur["n_risk_50k_bound"],
                n_adv_clipped=cur["n_adv_clipped"],
                n_adv_missing=cur["n_adv_missing"],
                n_adv_last_known=cur["n_adv_last_known"],
                n_skip_adv=cur["n_skip_adv"],
                n_sector_rotate=cur["n_sector_rotate"],
                n_skip_sector=cur["n_skip_sector"],
                n_sector_capped=cur["n_sector_capped"],
            )
        )
        close_year = (end_eq_day.month == 1 and end_eq_day.day == 1) or (
            end_eq_day == through
        )
        if close_year:
            led.year_max_dd_pct[y] = _max_dd_pct(year_path)
            led.year_running_max_dd_pct[y] = _max_dd_pct(all_path)
            year_path.clear()
        month_path.clear()
        cur = None

    def _open_month(d: date) -> None:
        nonlocal cur, risk, equity_bom, cash, withdrawals
        n_wd = n_wd_skip = 0
        wd_amt = 0.0
        if withdraw and d > date(2010, 1, 1) and d.day == 1:
            eq = cash + reserved
            if eq >= WITHDRAW:
                cash -= WITHDRAW
                withdrawals += WITHDRAW
                wd_amt = WITHDRAW
                n_wd = 1
                led.n_wd += 1
            else:
                n_wd_skip = 1
                led.n_wd_skip += 1
        equity_bom = cash + reserved
        risk = _month_risk(equity_bom)
        if risk_ceil > 0 and abs(risk - risk_ceil) < 1e-6:
            led.n_months_50k += 1
        _record_closed()
        cur = {
            "year": d.year,
            "month": d.month,
            "equity_start": equity_bom,
            "cash_start": cash,
            "reserved_start": reserved,
            "bp_start": _bp(),
            "risk_dollar": risk,
            "realized_pnl": 0.0,
            "interest": 0.0,
            "withdrawals": wd_amt,
            "n_entries": 0,
            "n_full": 0,
            "n_scaled": 0,
            "n_skip_bp": 0,
            "n_skip_size": 0,
            "n_risk_lt_1pct": 0,
            "n_closes": 0,
            "n_rotate": 0,
            "n_wd": n_wd,
            "n_wd_skip": n_wd_skip,
            "peak_reserved": reserved,
            "peak_loan": _loan(cash),
            "n_name_capped": 0,
            "n_risk_1pct_bound": 0,
            "n_risk_50k_bound": 0,
            "n_adv_clipped": 0,
            "n_adv_missing": 0,
            "n_adv_last_known": 0,
            "n_skip_adv": 0,
            "n_sector_rotate": 0,
            "n_skip_sector": 0,
            "n_sector_capped": 0,
        }

    def _size_adv_name(desired: r.OverlayTrade, d: date) -> r.OverlayTrade:
        clipped = (
            _apply_adv_cap(desired, asof=d, frac=afrac if afrac > 0 else None)
            if afrac > 0
            else desired
        )
        if not clipped.sized:
            return clipped
        eq = cash + reserved
        already = float(name_open.get(clipped.symbol, 0.0))
        return _apply_name_cap(
            clipped,
            equity=eq,
            already=already,
            frac=ncap if ncap > 0 else None,
        )

    def _size_name_then_bp(desired: r.OverlayTrade, d: date) -> tuple[r.OverlayTrade, bool]:
        capped = _size_adv_name(desired, d)
        if not capped.sized:
            return capped, False
        if scap > 0:
            eq = cash + reserved
            sec = _sector(capped.symbol)
            already_s = float(sector_open.get(sec, 0.0))
            capped = _apply_sector_cap(
                capped,
                equity=eq,
                already=already_s,
                frac=scap,
            )
            if not capped.sized:
                return capped, False
        return _clip_to_bp(capped, _bp())

    def _close_victim(victim: r.OverlayTrade, d: date, mode: str, px: float) -> None:
        nonlocal cash, reserved
        oc = orig_closed.get(id(victim))
        if oc is not None and victim in pending_close.get(oc, []):
            pending_close[oc] = [x for x in pending_close[oc] if x is not victim]
        _force_rotate(victim, sale=d, px=px, mode=mode)
        before = realized
        _do_close(victim)
        if cur is not None:
            cur["realized_pnl"] += realized - before
            cur["n_closes"] += 1
            if mode == "sector":
                cur["n_sector_rotate"] += 1
            else:
                cur["n_rotate"] += 1
        if mode == "sector":
            led.n_sector_rotate += 1
        else:
            led.n_rotate += 1

    def _maybe_sector_rotate(desired: r.OverlayTrade, d: date) -> None:
        if scap <= 0 or not open_book:
            return
        after = _size_adv_name(desired, d)
        if not after.sized:
            return
        sec = _sector(after.symbol)
        eq = cash + reserved
        already_s = float(sector_open.get(sec, 0.0))
        room = scap * max(eq, 0.0) - already_s
        if after.invested <= room + 1e-6:
            return
        lots = [t for t in open_book if _sector(t.symbol) == sec]
        victim, px = _pick_victim(lots, "winner", d)
        if victim is None or px is None:
            return
        _close_victim(victim, d, "sector", px)

    def _try_rotate_then_clip(desired: r.OverlayTrade, d: date) -> tuple[r.OverlayTrade, bool]:
        nonlocal cash, reserved
        n_sec_before = led.n_sector_rotate
        _maybe_sector_rotate(desired, d)
        sized, risk_lt = _size_name_then_bp(desired, d)
        if sized.sized and led.n_sector_rotate > n_sec_before:
            note = (sized.stop_src or "") + ";after_rotate_sector"
            sized = r.OverlayTrade(**{**sized.__dict__, "stop_src": note.lstrip(";")})
        if sized.sized or rotate == "none" or not open_book:
            return sized, risk_lt
        if sized.skip_reason not in {"bp_empty", "bp_too_small"}:
            return sized, risk_lt
        victim, px = _pick_victim(open_book, rotate, d)
        if victim is None or px is None:
            return sized, risk_lt
        _close_victim(victim, d, rotate, px)
        sized2, risk_lt2 = _size_name_then_bp(desired, d)
        if sized2.sized:
            note = (sized2.stop_src or "") + f";after_rotate_{rotate}"
            sized2 = r.OverlayTrade(**{**sized2.__dict__, "stop_src": note.lstrip(";")})
        return sized2, risk_lt2

    for d in days:
        _accrue_to(d)
        if d.day == 1:
            if cur is not None:
                _finalize_month(d)
            _open_month(d)
        elif cur is None:
            _open_month(date(d.year, d.month, 1))

        already = pending_close.pop(d, [])
        older = [t for t in already if t.opened < d]
        same_day_early = [t for t in already if t.opened == d]
        for t in sorted(older, key=lambda x: _sys_key(x, rank)):
            before = realized
            _do_close(t)
            if cur is not None:
                cur["realized_pnl"] += realized - before
                cur["n_closes"] += 1

        entries = list(by_open.get(d, []))
        entries.sort(key=lambda x: _sys_key(x, rank))
        for raw in entries:
            if cur is not None:
                cur["n_entries"] += 1
            desired = c.apply_compound_size(raw, risk, equity_bom)
            sized, risk_lt = _try_rotate_then_clip(desired, d)
            out.append(sized)
            if sized.sized:
                cash -= sized.invested
                reserved += sized.invested
                open_book.append(sized)
                name_open[sized.symbol] += float(sized.invested)
                name_now = name_open[sized.symbol]
                eq_now = cash + reserved
                if name_now > led.peak_name_notional:
                    led.peak_name_notional = name_now
                    led.peak_name_symbol = sized.symbol
                    led.peak_name_frac = (name_now / eq_now) if eq_now > 0 else 0.0
                if scap > 0:
                    sec = _sector(sized.symbol)
                    sector_open[sec] += float(sized.invested)
                    sec_now = sector_open[sec]
                    if sec_now > led.peak_sector_notional:
                        led.peak_sector_notional = sec_now
                        led.peak_sector_name = sec
                    sec_frac = (sec_now / eq_now) if eq_now > 0 else 0.0
                    if sec_frac > led.peak_sector_frac:
                        led.peak_sector_frac = sec_frac
                        led.peak_sector_frac_name = sec
                cap = LEVERAGE * eq_now
                if reserved <= cap + 1e-4:
                    led.n_fill_cap_ok += 1
                else:
                    led.max_reserved_over_2x = max(led.max_reserved_over_2x, reserved - cap)
                if reserved > led.peak_reserved:
                    led.peak_reserved = reserved
                loan = _loan(cash)
                if loan > led.peak_loan:
                    led.peak_loan = loan
                name_capped = "name_cap" in (sized.stop_src or "")
                if name_capped:
                    led.n_name_capped += 1
                sector_capped = "sector_cap" in (sized.stop_src or "")
                if sector_capped:
                    led.n_sector_capped += 1
                src_note = sized.stop_src or ""
                one_pct = rf * max(equity_bom, 0.0)
                if risk_ceil > 0 and one_pct > risk_ceil + 1e-6:
                    led.n_risk_50k_bound += 1
                    if cur is not None:
                        cur["n_risk_50k_bound"] += 1
                elif risk_ceil > 0 or freeze_risk <= 0:
                    led.n_risk_1pct_bound += 1
                    if cur is not None:
                        cur["n_risk_1pct_bound"] += 1
                if "adv_cap" in src_note:
                    led.n_adv_clipped += 1
                    if cur is not None:
                        cur["n_adv_clipped"] += 1
                if "adv_last_known" in src_note:
                    led.n_adv_last_known += 1
                    if cur is not None:
                        cur["n_adv_last_known"] += 1
                if cur is not None:
                    if reserved > cur["peak_reserved"]:
                        cur["peak_reserved"] = reserved
                    if loan > cur["peak_loan"]:
                        cur["peak_loan"] = loan
                    if sized.scaled:
                        cur["n_scaled"] += 1
                    else:
                        cur["n_full"] += 1
                    if risk_lt:
                        cur["n_risk_lt_1pct"] += 1
                    if name_capped:
                        cur["n_name_capped"] += 1
                    if sector_capped:
                        cur["n_sector_capped"] += 1
                oc = sized.closed
                orig_closed[id(sized)] = oc
                if sized.status == "closed" and oc is not None and oc >= d:
                    pending_close[oc].append(sized)
            elif sized.skip_reason in {"bp_empty", "bp_too_small"}:
                if cur is not None:
                    cur["n_skip_bp"] += 1
            elif sized.skip_reason == "name_cap_empty":
                led.n_skip_name += 1
                if cur is not None:
                    cur["n_skip_size"] += 1
            elif sized.skip_reason == "sector_cap_empty":
                led.n_skip_sector += 1
                if cur is not None:
                    cur["n_skip_sector"] += 1
                    cur["n_skip_size"] += 1
            elif sized.skip_reason in {"adv_missing", "adv_empty"}:
                led.n_skip_adv += 1
                if sized.skip_reason == "adv_missing":
                    led.n_adv_missing += 1
                    if cur is not None:
                        cur["n_adv_missing"] += 1
                if cur is not None:
                    cur["n_skip_adv"] += 1
                    cur["n_skip_size"] += 1
            else:
                if cur is not None:
                    cur["n_skip_size"] += 1

        same_day = same_day_early + [t for t in pending_close.pop(d, []) if t.opened == d]
        for t in sorted(same_day, key=lambda x: _sys_key(x, rank)):
            if t not in open_book:
                continue
            before = realized
            _do_close(t)
            if cur is not None:
                cur["realized_pnl"] += realized - before
                cur["n_closes"] += 1
        _record_closed()

    if prev is not None and prev < through:
        _accrue_to(through)
    _finalize_month(through)

    open_mtm = 0.0
    for t in out:
        if t.status == "open" and t.sized:
            mtm = _mtm_dollar(t, through)
            open_mtm += mtm if mtm is not None else t.overlay_pnl

    led.n_full = sum(1 for t in out if t.sized and not t.scaled)
    led.n_scaled = sum(1 for t in out if t.sized and t.scaled)
    led.n_skip_bp = sum(
        1 for t in out if (not t.sized) and t.skip_reason in {"bp_empty", "bp_too_small"}
    )
    led.n_skip_name = sum(1 for t in out if (not t.sized) and t.skip_reason == "name_cap_empty")
    led.n_skip_sector = sum(1 for t in out if (not t.sized) and t.skip_reason == "sector_cap_empty")
    led.n_skip_adv = sum(
        1 for t in out if (not t.sized) and t.skip_reason in {"adv_missing", "adv_empty"}
    )
    led.n_adv_missing = sum(1 for t in out if (not t.sized) and t.skip_reason == "adv_missing")
    led.n_skip_size = sum(
        1
        for t in out
        if (not t.sized)
        and t.skip_reason
        not in {
            "bp_empty",
            "bp_too_small",
            "name_cap_empty",
            "adv_missing",
            "adv_empty",
            "sector_cap_empty",
        }
    )
    led.n_risk_lt_1pct = sum(s.n_risk_lt_1pct for s in snaps)
    led.end_cash = cash
    led.end_reserved = reserved
    led.end_equity = cash + reserved
    led.end_bp = _buying_power(cash, reserved)
    led.end_mtm = cash + reserved + open_mtm
    led.realized = realized
    led.interest = interest
    led.withdrawals = withdrawals
    led.identity_err = abs(
        (cash + reserved) - (seed + realized - interest - withdrawals)
    )
    by_y = {s.year: s.equity_end for s in snaps}
    # last snap of each year
    last_by_y: dict[int, float] = {}
    for s in snaps:
        last_by_y[s.year] = s.equity_end
    led.eq_2010 = last_by_y.get(2010, seed)
    led.eq_2011 = last_by_y.get(2011, led.eq_2010)
    led.eq_2012 = last_by_y.get(2012, led.eq_2011)
    led.max_dd_pct, led.max_dd_peak, led.max_dd_trough = _worst_dd_peak_trough(all_path)
    return out, snaps, led


def year_end_rows(
    snaps: list[WalletSnap],
    *,
    through: date,
    risk_frac: Optional[float] = None,
    led: Optional[Ledger] = None,
    fixed_risk_dollar: Optional[float] = None,
    max_risk_dollar: Optional[float] = None,
    start_equity: Optional[float] = None,
) -> list[dict[str, Any]]:
    by_year: dict[int, list[WalletSnap]] = defaultdict(list)
    for s in snaps:
        by_year[s.year].append(s)
    seed = ACCOUNT if start_equity is None else float(start_equity)
    last_eq = seed
    last_cash = seed
    last_res = 0.0
    last_bp = LEVERAGE * seed
    rows: list[dict[str, Any]] = []
    for y in range(2010, through.year + 1):
        ys = by_year.get(y)
        if ys:
            last_eq = ys[-1].equity_end
            last_cash = ys[-1].cash_end
            last_res = ys[-1].reserved_end
            last_bp = ys[-1].bp_end
            jan_risk = ys[0].risk_dollar
            jan_eq = ys[0].equity_start
            realized = sum(s.realized_pnl for s in ys)
            interest = sum(s.interest for s in ys)
            wd = sum(s.withdrawals for s in ys)
            n_scaled = sum(s.n_scaled for s in ys)
            n_skip = sum(s.n_skip_bp for s in ys)
            n_full = sum(s.n_full for s in ys)
            n_rot = sum(s.n_rotate for s in ys)
        else:
            if fixed_risk_dollar:
                jan_risk = float(fixed_risk_dollar)
            else:
                jan_risk = (RISK_FRAC if risk_frac is None else float(risk_frac)) * last_eq
                if max_risk_dollar:
                    jan_risk = min(jan_risk, float(max_risk_dollar))
            jan_eq = last_eq
            realized = interest = wd = 0.0
            n_scaled = n_skip = n_full = n_rot = 0
        note = ""
        if y == through.year and (through.month < 12 or through.day < 31):
            note = f"through {through.isoformat()} (year not finished)"
        rf_row = RISK_FRAC if risk_frac is None else float(risk_frac)
        if fixed_risk_dollar:
            next_risk = float(fixed_risk_dollar)
        else:
            next_risk = rf_row * last_eq
            if max_risk_dollar:
                next_risk = min(next_risk, float(max_risk_dollar))
        rows.append(
            {
                "year": y,
                "ending_equity": last_eq,
                "ending_cash": last_cash,
                "ending_reserved": last_res,
                "ending_bp": last_bp,
                "ending_loan": max(0.0, -last_cash),
                "next_1pct": next_risk,
                "jan_1pct": jan_risk,
                "jan_equity": jan_eq,
                "realized": realized,
                "interest": interest,
                "withdrawals": wd,
                "n_full": n_full,
                "n_scaled": n_scaled,
                "n_skip_bp": n_skip,
                "n_rotate": n_rot,
                "note": note,
                "max_dd_pct": (
                    float(led.year_max_dd_pct.get(y, 0.0)) if led is not None else 0.0
                ),
                "running_max_dd_pct": (
                    float(led.year_running_max_dd_pct.get(y, 0.0))
                    if led is not None
                    else 0.0
                ),
            }
        )
    return rows


def load_static(systems: tuple[str, ...]) -> list[r.OverlayTrade]:
    out: list[r.OverlayTrade] = []
    for sys in systems:
        if sys == "RSI":
            path = PREV_DIR / "RSI_overlay_avgloss.csv"
            if not path.is_file():
                raise SystemExit(f"missing {path} — need IS avg-loss freeze")
            out.extend(r.load_overlay_csv(path))
        else:
            path = PREV_DIR / f"{sys}_overlay_risk2500.csv"
            if not path.is_file():
                raise SystemExit(f"missing {path}")
            out.extend(r.load_overlay_csv(path))
    return out


def spy_buyhold(
    start: date = START,
    end: date = ASOF,
    seed: Optional[float] = None,
) -> dict[str, Any]:
    if not SPY_PATH.is_file():
        raise SystemExit(f"missing {SPY_PATH}")
    acct = ACCOUNT if seed is None else float(seed)
    df = pd.read_csv(SPY_PATH)
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"]).sort_values("Date")
    df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
    df["Adj Close"] = pd.to_numeric(df["Adj Close"], errors="coerce")
    df = df.dropna(subset=["Close", "Adj Close"])
    df["d"] = df["Date"].dt.date
    first = df[df["d"] >= start].iloc[0]
    last = df[df["d"] <= end].iloc[-1]
    px0, px1 = float(first["Close"]), float(last["Close"])
    adj0, adj1 = float(first["Adj Close"]), float(last["Adj Close"])
    price_end = acct * (px1 / px0)
    tr_end = acct * (adj1 / adj0)
    years: dict[int, dict[str, float]] = {}
    for y in range(start.year, end.year + 1):
        chunk = df[(df["d"] >= date(y, 1, 1)) & (df["d"] <= date(y, 12, 31))]
        if y == end.year:
            chunk = chunk[chunk["d"] <= end]
        if chunk.empty:
            continue
        row = chunk.iloc[-1]
        years[y] = {
            "price": acct * (float(row["Close"]) / px0),
            "tr": acct * (float(row["Adj Close"]) / adj0),
            "px": float(row["Close"]),
            "adj": float(row["Adj Close"]),
        }
    return {
        "start_date": first["d"].isoformat() if hasattr(first["d"], "isoformat") else str(first["d"]),
        "end_date": last["d"].isoformat() if hasattr(last["d"], "isoformat") else str(last["d"]),
        "px0": px0,
        "px1": px1,
        "adj0": adj0,
        "adj1": adj1,
        "price_end": price_end,
        "tr_end": tr_end,
        "price_mult": px1 / px0,
        "tr_mult": adj1 / adj0,
        "years": years,
        "series": "SPY Adj Close (Yahoo-style total return, dividends reinvested)",
    }


def _stats_wallet(
    trades: list[r.OverlayTrade],
    *,
    cash: Optional[float] = None,
) -> dict[str, Any]:
    closed = [t for t in trades if t.status == "closed"]
    seed = ACCOUNT if cash is None else float(cash)
    return r.book_stats(closed, use_overlay=True, cash_ann=seed, dd_seed=seed)


def _arm_pack(
    trades: list[r.OverlayTrade],
    snaps: list[WalletSnap],
    led: Ledger,
    *,
    rank: dict[str, int],
    rotate: str,
    withdraw: bool,
    label: str,
    risk_frac: Optional[float] = None,
    through: date = ASOF,
    fixed_risk_dollar: Optional[float] = None,
    max_risk_dollar: Optional[float] = None,
    adv_frac: Optional[float] = None,
    start_equity: Optional[float] = None,
) -> dict[str, Any]:
    years = year_end_rows(
        snaps,
        through=through,
        risk_frac=risk_frac,
        led=led,
        fixed_risk_dollar=fixed_risk_dollar,
        max_risk_dollar=max_risk_dollar,
        start_equity=start_equity,
    )
    closed = [t for t in trades if t.status == "closed"]
    seed = ACCOUNT if start_equity is None else float(start_equity)
    return {
        "label": label,
        "rotate": rotate,
        "withdraw": withdraw,
        "trades": trades,
        "snaps": snaps,
        "led": led,
        "years": years,
        "start_equity": seed,
        "stats_full": _stats_wallet(closed, cash=seed),
        "stats_is": _stats_wallet(r.slice_trades(closed, "IS"), cash=seed),
        "stats_oos": _stats_wallet(r.slice_trades(closed, "OOS"), cash=seed),
        "n_sized_closed": sum(1 for t in closed if t.sized),
        "n_rotate_exits": sum(1 for t in closed if str(t.exit_type).startswith("ROTATE_")),
        "risk_frac": RISK_FRAC if risk_frac is None else float(risk_frac),
        "fixed_risk_dollar": (
            float(fixed_risk_dollar) if fixed_risk_dollar else 0.0
        ),
        "max_risk_dollar": float(max_risk_dollar) if max_risk_dollar else 0.0,
        "adv_frac": float(adv_frac) if adv_frac else 0.0,
    }


def _verdict(ctrl: dict[str, Any], rots: list[dict[str, Any]], spy: dict[str, Any]) -> str:
    z = ctrl["led"].end_equity
    spy_tr = spy["tr_end"]
    least = min(rots, key=lambda a: abs(a["led"].end_equity - z)) if rots else None
    best_end = max(rots, key=lambda a: a["led"].end_equity) if rots else None
    return (
        f"HOLD — do not adopt rotation from this one in-sample horse-race. "
        f"Five-system no-rotation 2× + 10.5% ends at {format_money(z)} vs SPY total-return "
        f"{format_money(spy_tr)}. "
        + (
            f"Least-different rotation vs control is {least['label']} "
            f"({format_money(least['led'].end_equity)}); highest paper ending is "
            f"{best_end['label']} ({format_money(best_end['led'].end_equity)}). "
            if least and best_end
            else ""
        )
        + "If the five-system path still dwarfs SPY after 2012, that is residual "
        "capacity fiction (tight stops + 1% of a growing pile + 2×), not a broker "
        "balance. Read 2010–2012. Not gold. Not DailyRun."
    )


def _sortable_head(pairs: list[tuple[str, str]]) -> str:
    return "".join(r._sortable_th(h, t) for h, t in pairs)


def _year_vs_spy_table(
    arms: list[dict[str, Any]],
    spy: dict[str, Any],
) -> str:
    head = _sortable_head(
        [("Year-end", "num")]
        + [(a["label"], "num") for a in arms]
        + [("SPY total return", "num"), ("SPY price-only", "num"), ("Note", "text")]
    )
    years = range(2010, ASOF.year + 1)
    body = ""
    for y in years:
        cells = f"<td>{y}</td>"
        for a in arms:
            row = next((x for x in a["years"] if x["year"] == y), None)
            cells += f"<td>{format_money(row['ending_equity']) if row else '—'}</td>"
        sy = spy["years"].get(y)
        cells += f"<td>{format_money(sy['tr']) if sy else '—'}</td>"
        cells += f"<td>{format_money(sy['price']) if sy else '—'}</td>"
        note = ""
        if y == ASOF.year:
            note = f"through {ASOF.isoformat()}"
        body += f"<tr>{cells}<td class=\"small\">{html_mod.escape(note)}</td></tr>"
    last_cells = '<tr class="total-row"><th>Total / last</th>'
    for a in arms:
        last_cells += f"<td>{format_money(a['led'].end_equity)}</td>"
    last_cells += (
        f"<td>{format_money(spy['tr_end'])}</td>"
        f"<td>{format_money(spy['price_end'])}</td>"
        "<td class=\"small\">Ending $ = last year-end</td></tr>"
    )
    return (
        '<p class="small">Closed-only five-system equity vs $250k SPY buy-hold. '
        "SPY total return uses Adjusted Close (dividends reinvested). "
        "Total row pinned. Click headers to sort.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}{last_cells}</tbody></table></div>"
    )


def _path_table(arms: list[dict[str, Any]], spy: dict[str, Any], nine: dict[str, Any]) -> str:
    head = _sortable_head(
        [
            ("Book", "text"),
            ("Cap / extra rule", "text"),
            ("Ending equity", "num"),
            ("2010 end", "num"),
            ("2011 end", "num"),
            ("2012 end", "num"),
            ("Interest paid", "num"),
            ("Withdrawals", "num"),
            ("Peak deployed", "num"),
            ("Peak loan", "num"),
            ("Sized closed N", "num"),
            ("Rotated / BP-skip", "text"),
            ("Read as", "text"),
        ]
    )
    rows = []
    rows.append(
        (
            "SPY buy-hold $250k (total return)",
            "None — sit in SPY, dividends reinvested via Adj Close",
            spy["tr_end"],
            spy["years"].get(2010, {}).get("tr"),
            spy["years"].get(2011, {}).get("tr"),
            spy["years"].get(2012, {}).get("tr"),
            0.0,
            0.0,
            spy["tr_end"],
            0.0,
            1,
            "0 / 0",
            "The benchmark. Not capacity fiction.",
        )
    )
    rows.append(
        (
            "SPY buy-hold $250k (price-only)",
            "Close / Close — no dividends",
            spy["price_end"],
            spy["years"].get(2010, {}).get("price"),
            spy["years"].get(2011, {}).get("price"),
            spy["years"].get(2012, {}).get("price"),
            0.0,
            0.0,
            spy["price_end"],
            0.0,
            1,
            "0 / 0",
            "Same shares, ignores dividends. We lead with total return.",
        )
    )
    rows.append(
        (
            "9-system 2× published (no interest)",
            "Open ≤ 2×; 10.5% was missing — sibling stamp",
            PUB_9SYS_2X_END,
            PUB_9SYS_2X_2010,
            None,
            None,
            0.0,
            0.0,
            None,
            None,
            None,
            "see sibling",
            "Capacity fiction. The $314B page Paul already has.",
        )
    )
    for a in [nine] + arms:
        led = a["led"]
        read = a.get("read") or ""
        rows.append(
            (
                a["label"],
                a.get("cap") or "",
                led.end_equity,
                led.eq_2010,
                led.eq_2011,
                led.eq_2012,
                led.interest,
                led.withdrawals,
                led.peak_reserved,
                led.peak_loan,
                a["n_sized_closed"],
                f"{led.n_rotate} / {led.n_skip_bp}",
                read,
            )
        )

    def _m(v: Any) -> str:
        if v is None:
            return "—"
        return format_money(float(v))

    def _n(v: Any) -> str:
        if v is None:
            return "—"
        return f"{int(v)}"

    body = ""
    for rec in rows:
        (
            name,
            cap,
            end,
            y0,
            y1,
            y2,
            interest,
            wd,
            peak,
            loan,
            n,
            sk,
            read,
        ) = rec
        body += (
            "<tr>"
            f"<td>{html_mod.escape(str(name))}</td>"
            f"<td class=\"small\">{html_mod.escape(str(cap))}</td>"
            f"<td>{_m(end)}</td>"
            f"<td>{_m(y0)}</td>"
            f"<td>{_m(y1)}</td>"
            f"<td>{_m(y2)}</td>"
            f"<td>{_m(interest)}</td>"
            f"<td>{_m(wd)}</td>"
            f"<td>{_m(peak)}</td>"
            f"<td>{_m(loan)}</td>"
            f"<td>{_n(n)}</td>"
            f"<td>{html_mod.escape(str(sk))}</td>"
            f"<td class=\"small\">{html_mod.escape(str(read))}</td>"
            "</tr>"
        )
    return (
        f'<table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table>"
    )


def _canonical_table(cols: list[tuple[str, dict[str, Any]]]) -> str:
    body = ""
    for label, key, kind in r.CANONICAL_METRIC_ROWS:
        if is_excluded_html_compare_label(label):
            continue
        cells = f"<td>{html_mod.escape(label)}</td>"
        base = cols[0][1].get(key) if cols else None
        for i, (_name, st) in enumerate(cols):
            cells += f"<td>{r._fmt_kind(st.get(key), kind)}</td>"
            if i > 0:
                cells += f"<td>{r._delta_kind(st.get(key), base, kind)}</td>"
        body += f"<tr>{cells}</tr>"
    pairs = [("Metric", "text")]
    for i, (name, _st) in enumerate(cols):
        pairs.append((name, "text"))
        if i > 0:
            pairs.append((f"Δ vs {cols[0][0]}", "text"))
    head = _sortable_head(pairs)
    return (
        f'<table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table>"
    )


def _ledger_table(
    snaps: list[WalletSnap],
    *,
    risk_col: str = "Month 1%",
    bind_cols: bool = False,
    sector_cols: bool = False,
) -> str:
    cols = [
        ("Month", "month"),
        ("BOM equity", "num"),
        (risk_col, "num"),
        ("Entries", "num"),
        ("Full", "num"),
        ("Scaled", "num"),
        ("BP-skip", "num"),
        ("Rotates", "num"),
        ("Closes", "num"),
        ("Realized $", "num"),
        ("Interest $", "num"),
        ("Withdrawn $", "num"),
        ("EOM equity", "num"),
        ("EOM loan", "num"),
        ("Peak open notional", "num"),
    ]
    if bind_cols:
        cols.extend(
            [
                ("1% bound fills", "num"),
                ("$50k bound fills", "num"),
                ("ADV clipped", "num"),
                ("ADV missing skip", "num"),
                ("ADV last-known", "num"),
            ]
        )
    if sector_cols:
        cols.extend(
            [
                ("Sector rotates", "num"),
                ("Sector-capped fills", "num"),
                ("Sector-skip", "num"),
            ]
        )
    head = _sortable_head(cols)
    body = ""
    for s in snaps:
        loan = max(0.0, -s.cash_end)
        body += (
            "<tr>"
            f"<td>{s.year}-{s.month:02d}</td>"
            f"<td>{format_money(s.equity_start)}</td>"
            f"<td>{format_money(s.risk_dollar)}</td>"
            f"<td>{s.n_entries}</td>"
            f"<td>{s.n_full}</td>"
            f"<td>{s.n_scaled}</td>"
            f"<td>{s.n_skip_bp}</td>"
            f"<td>{s.n_rotate}</td>"
            f"<td>{s.n_closes}</td>"
            f"<td class=\"{r._pnl_class(s.realized_pnl)}\">{r._fmt_money_signed(s.realized_pnl)}</td>"
            f"<td class=\"neg\">{format_money(s.interest)}</td>"
            f"<td>{format_money(s.withdrawals)}</td>"
            f"<td>{format_money(s.equity_end)}</td>"
            f"<td>{format_money(loan)}</td>"
            f"<td>{format_money(s.peak_reserved)}</td>"
        )
        if bind_cols:
            body += (
                f"<td>{s.n_risk_1pct_bound}</td>"
                f"<td>{s.n_risk_50k_bound}</td>"
                f"<td>{s.n_adv_clipped}</td>"
                f"<td>{s.n_adv_missing}</td>"
                f"<td>{s.n_adv_last_known}</td>"
            )
        if sector_cols:
            body += (
                f"<td>{s.n_sector_rotate}</td>"
                f"<td>{s.n_sector_capped}</td>"
                f"<td>{s.n_skip_sector}</td>"
            )
        body += "</tr>"
    if snaps:
        last = snaps[-1]
        tot_r = sum(s.realized_pnl for s in snaps)
        tot_i = sum(s.interest for s in snaps)
        tot_w = sum(s.withdrawals for s in snaps)
        extra = ""
        if bind_cols:
            extra = (
                f"<td>{sum(s.n_risk_1pct_bound for s in snaps)}</td>"
                f"<td>{sum(s.n_risk_50k_bound for s in snaps)}</td>"
                f"<td>{sum(s.n_adv_clipped for s in snaps)}</td>"
                f"<td>{sum(s.n_adv_missing for s in snaps)}</td>"
                f"<td>{sum(s.n_adv_last_known for s in snaps)}</td>"
            )
        if sector_cols:
            extra += (
                f"<td>{sum(s.n_sector_rotate for s in snaps)}</td>"
                f"<td>{sum(s.n_sector_capped for s in snaps)}</td>"
                f"<td>{sum(s.n_skip_sector for s in snaps)}</td>"
            )
        body += (
            '<tr class="total-row"><th>Total / last</th>'
            f"<td>{format_money(last.equity_end)}</td><td>—</td>"
            f"<td>{sum(s.n_entries for s in snaps)}</td>"
            f"<td>{sum(s.n_full for s in snaps)}</td>"
            f"<td>{sum(s.n_scaled for s in snaps)}</td>"
            f"<td>{sum(s.n_skip_bp for s in snaps)}</td>"
            f"<td>{sum(s.n_rotate for s in snaps)}</td>"
            f"<td>{sum(s.n_closes for s in snaps)}</td>"
            f"<td class=\"{r._pnl_class(tot_r)}\">{r._fmt_money_signed(tot_r)}</td>"
            f"<td class=\"neg\">{format_money(tot_i)}</td>"
            f"<td>{format_money(tot_w)}</td>"
            f"<td>{format_money(last.equity_end)}</td>"
            f"<td>{format_money(max(0.0, -last.cash_end))}</td>"
            f"<td>{format_money(max(s.peak_reserved for s in snaps))}</td>"
            f"{extra}</tr>"
        )
    return (
        '<p class="small">Buying-power + interest ledger. Interest is 10.5% / 365 '
        "compounded on calendar days while cash is negative. Total row pinned. "
        "Click headers to sort.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def _trade_table(trades: list[r.OverlayTrade], *, open_book: bool = False) -> str:
    if not trades:
        return '<p class="small">No trades.</p>'
    rows = sorted(trades, key=lambda t: ((t.closed or date.min), t.system, t.symbol))
    body = ""
    for t in rows:
        d_close = t.closed.strftime("%Y-%m-%d") if t.closed else ""
        stop_s = f"${t.stop_used:,.2f}" if t.stop_used else "—"
        flag = "scaled" if t.scaled else ("full" if t.sized else "skip")
        body += (
            "<tr>"
            f"<td>{html_mod.escape(t.system)}</td>"
            f"<td>{r._symbol_link(t.symbol)}</td>"
            f"<td>{t.opened.strftime('%Y-%m-%d')}</td>"
            f"<td>{d_close}</td>"
            f"<td>{html_mod.escape(t.exit_type)}</td>"
            f"<td>{int(t.days)}</td>"
            f"<td>{stop_s}</td>"
            f"<td>{r._fmt_num(t.shares, 1)}</td>"
            f"<td>{format_money(t.invested) if t.sized else '—'}</td>"
            f"<td>{html_mod.escape(flag)}</td>"
            f"<td class=\"{r._pnl_class(t.pnl_pct)}\">{r.monthly._fmt_pct(t.pnl_pct)}</td>"
            f"<td class=\"{r._pnl_class(t.overlay_pnl)}\">{r._fmt_money_signed(t.overlay_pnl) if t.sized else 'N/A'}</td>"
            f"<td>{html_mod.escape(t.stop_src if t.sized else t.skip_reason)}</td>"
            "</tr>"
        )
    labels = [
        ("System", "text"),
        ("Symbol", "text"),
        ("Opened", "date"),
        ("Closed" if not open_book else "—", "date"),
        ("Exit", "text"),
        ("Days", "num"),
        ("Stop used", "num"),
        ("Shares", "num"),
        ("$ deployed", "num"),
        ("Fill", "text"),
        ("PnL %", "num"),
        ("Wallet $", "num"),
        ("Size note", "text"),
    ]
    head = "".join(r._sortable_th(a, b) for a, b in labels)
    return (
        f'<table class="sortable"><thead><tr>{head}</tr></thead><tbody>'
        + body
        + "</tbody></table>"
    )


def _proceed_html(ctrl: dict[str, Any], spy: dict[str, Any], rots: list[dict[str, Any]]) -> str:
    z = ctrl["led"].end_equity
    spy_tr = spy["tr_end"]
    crush = z > spy_tr * 5
    least = min(rots, key=lambda a: a["led"].end_equity) if rots else None
    # "least bad" = closest to not destroying vs control quality; we HOLD all.
    items = [
        (
            "YES",
            f"Treat the live ~$58k cash gap as ~8 × $7,500 bank wires ($60,000). "
            f"{LIVE_GAP_NOTE}",
        ),
        (
            "YES",
            "Keep live size small — about $20–25k lots, or $2,500 risk-to-stop / "
            "RSI In-Sample avg-loss slot. Do <strong>not</strong> go back to "
            "$75–100k lots. Size and stack did the live damage, not the September "
            "RSI / VZ wires.",
        ),
        (
            "YES",
            "Keep Indicators (IND) deprecated. Live Indicators was about −$40k of the hole.",
        ),
        (
            "YES",
            "Charge 10.5% on any future margin paper. The published 9-system 2× "
            f"ending {format_money(PUB_9SYS_2X_END)} omitted interest.",
        ),
        (
            "YES",
            "When you read this paper book, look at 2010–2012 first "
            f"(control 2010 {format_money(ctrl['led'].eq_2010)}, "
            f"2011 {format_money(ctrl['led'].eq_2011)}, "
            f"2012 {format_money(ctrl['led'].eq_2012)} vs SPY total-return "
            f"{format_money(spy['years'].get(2010, {}).get('tr', 0))}/"
            f"{format_money(spy['years'].get(2011, {}).get('tr', 0))}/"
            f"{format_money(spy['years'].get(2012, {}).get('tr', 0))}). "
            + (
                "Later-year endings still crush SPY because leftover capacity fiction "
                "(tight stops + 1% of a growing pile + 2×), not because a $250k "
                "Fidelity account would print that."
                if crush
                else "If later years stay near human size, that is the 2× + interest brake working."
            ),
        ),
        (
            "HOLD",
            "Do not adopt a five-system-only DailyRun cut from this page. Research-only. "
            "Dropped sleeves (Break and ReTest, Year High, Weekly Pivot Break and Retest, "
            "Relative Strength vs SPY) stay off this paper book; that is not a gold promotion.",
        ),
        (
            "HOLD",
            "Do not adopt rotation (sell loser / oldest / winner) from this one "
            "in-sample horse-race. Control is skip-when-no-buying-power. "
            + (
                f"Paper least-ending rotation: {least['label']} at "
                f"{format_money(least['led'].end_equity)}."
                if least
                else ""
            ),
        ),
        (
            "HOLD",
            "Rocket Launcher stays in the five-system paper set, but live RL at "
            "$75–100k was about −$79k of the hole. If RL stays live, keep it small.",
        ),
        (
            "NO",
            "Do not gold-promote this stamp. Do not wire DailyRun from it. Do not "
            "retune the 6.51% RSI freeze on Out-of-Sample.",
        ),
        (
            "YES — optional",
            "Keep a $7,500 first-of-month cash drain in any “what would my account "
            "have looked like” paper so it matches how you actually live.",
        ),
    ]
    lis = ""
    for i, (tag, text) in enumerate(items, 1):
        cls = "yes" if tag.startswith("YES") else ("no" if tag.startswith("NO") else "holdtag")
        lis += f"<li><strong class=\"{cls}\">{i}. {html_mod.escape(tag)}</strong> — {text}</li>"
    return f"<ol class=\"proceed\">{lis}</ol>"


def _css() -> str:
    return f"""
body {{ font-family: system-ui, sans-serif; margin:24px; color:#0f172a; }}
h1 {{ font-size:1.5rem; margin-bottom:4px; }}
h2 {{ font-size:1.15rem; margin-top:28px; }}
h3 {{ font-size:1rem; margin:16px 0 8px; color:#334155; }}
.sub {{ color:#64748b; margin-bottom:20px; line-height:1.5; font-size:0.95rem; }}
.ask {{ background:#fff7ed; border:1px solid #fdba74; border-radius:10px; padding:14px 16px; margin:16px 0; }}
.ask h2 {{ margin-top:8px; font-size:1rem; }}
.ask h2:first-child {{ margin-top:0; }}
blockquote {{ margin:8px 0 12px; color:#9a3412; }}
.hold {{ background:#eef2ff; border:1px solid #c7d2fe; border-radius:10px; padding:12px 14px; margin:12px 0 20px; }}
.lead {{ background:#ecfdf5; border:1px solid #6ee7b7; border-radius:10px; padding:14px 16px; margin:12px 0 20px; }}
.warn {{ background:#fef2f2; border:1px solid #fecaca; border-radius:10px; padding:12px 14px; margin:12px 0; }}
.proceed-box {{ background:#f8fafc; border:1px solid #cbd5e1; border-radius:10px; padding:14px 16px; margin:12px 0 20px; }}
ol.proceed {{ margin:8px 0 0 20px; line-height:1.55; }}
.yes {{ color:#15803d; }} .no {{ color:#b91c1c; }} .holdtag {{ color:#4338ca; }}
.cards {{ display:flex; flex-wrap:wrap; gap:12px; margin:16px 0 24px; }}
.card {{ background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:14px 16px; min-width:200px; flex:1 1 220px; }}
.card-shared {{ background:#ecfdf5; border-color:#6ee7b7; }}
.card h3 {{ margin:0 0 8px; font-size:13px; color:#475569; font-weight:700; }}
.metric {{ font-size:1.35rem; font-weight:700; line-height:1.2; }}
.small {{ font-size:12px; color:#64748b; }}
.muted {{ color:#94a3b8; }}
.pos {{ color:#16a34a; }} .neg {{ color:#dc2626; }}
section {{ margin-top:24px; }}
.month-section {{ border-top:1px solid #e2e8f0; padding-top:8px; }}
.table-wrap {{ margin:8px 0; }}
table {{ border-collapse:collapse; font-size:12px; width:100%; }}
th, td {{ border:1px solid #e2e8f0; padding:7px 8px; text-align:left; vertical-align:top; }}
th {{ background:#f1f5f9; }}
th.sortable-th {{ cursor:pointer; user-select:none; white-space:normal; }}
th.sortable-th:hover {{ background:#e2e8f0; }}
.sort-ind {{ display:inline-block; width:0.9em; margin-left:4px; color:#94a3b8; font-size:10px; }}
th.sort-asc .sort-ind::after {{ content:"▲"; color:#334155; }}
th.sort-desc .sort-ind::after {{ content:"▼"; color:#334155; }}
tr.total-row th, tr.total-row td {{ background:#f8fafc; border-top:2px solid #334155; }}
ul.sources {{ font-size:12px; color:#475569; line-height:1.6; }}
a.sym {{ color:#1d4ed8; text-decoration:none; font-weight:600; }}
a.sym:hover {{ text-decoration:underline; }}
{r.TABLE_UNCAP_CSS}
"""


def build_monthly(
    *,
    ctrl: dict[str, Any],
    wd: dict[str, Any],
    rots: list[dict[str, Any]],
    nine: dict[str, Any],
    spy: dict[str, Any],
    verdict: str,
    sources: list[str],
    generated: datetime,
) -> str:
    now = generated.astimezone(ET)
    year = ASOF.year
    led = ctrl["led"]
    arms_all = [ctrl, wd] + rots
    for a, cap, read in (
        (
            ctrl,
            "5 systems · open ≤ 2× · 10.5% · skip if no BP",
            "Control. Same fill order as the 9-system 2× book.",
        ),
        (
            wd,
            "Control + $7,500 on the 1st (even into margin)",
            "His real bank wire. One extra knob on the control.",
        ),
        (
            nine,
            "All 9 DailyRun systems · 2× · 10.5% · no rotation",
            "Fair compare to the five-system control (interest now on).",
        ),
    ):
        a["cap"] = cap
        a["read"] = read
    rot_caps = {
        "loser": "At 2× cap, sell worst $ mark-to-market (last close vs entry)",
        "oldest": "At 2× cap, sell longest hold",
        "winner": "At 2× cap, sell best $ open mark (last close vs entry)",
    }
    for a in rots:
        a["cap"] = rot_caps.get(a["rotate"], a["rotate"])
        a["read"] = "One-knob vs control. HOLD — in-sample horse-race."

    sized_closed = [t for t in ctrl["trades"] if t.status == "closed" and t.sized]
    year_closed = [t for t in sized_closed if t.closed and t.closed.year == year]
    open_rows = [t for t in ctrl["trades"] if t.status == "open" and t.sized]
    pivot_html, hist_html = c._pivot_and_hist(
        sized_closed, year=year, through_month=now.month if now.year == year else 12
    )
    # _pivot_and_hist uses module SYSTEMS (nine). Rebuild a five-system pivot.
    pivot_html, hist_html = _five_pivot(sized_closed, year=year, through_month=min(now.month, 9) if now.year == year else 12)

    cards = f"""
  <div class="card card-shared">
    <h3>SPY $250k since 2010-01-04 (total return)</h3>
    <div class="metric">{format_money(spy['tr_end'])}</div>
    <div class="small">{spy['tr_mult']:.2f}× · Adj Close {spy['adj0']:.4f} → {spy['adj1']:.4f}</div>
    <div class="small">Price-only: {format_money(spy['price_end'])} ({spy['price_mult']:.2f}×)</div>
    <div class="small">{html_mod.escape(spy['start_date'])} → {html_mod.escape(spy['end_date'])}</div>
  </div>
  <div class="card card-shared">
    <h3>5-sys no-rotation 2× + 10.5%</h3>
    <div class="metric">{format_money(led.end_equity)}</div>
    <div class="small">Interest paid {format_money(led.interest)} · loan now {format_money(max(0.0, -led.end_cash))}</div>
    <div class="small">2010 {format_money(led.eq_2010)} · 2011 {format_money(led.eq_2011)} · 2012 {format_money(led.eq_2012)}</div>
    <div class="small">Peak deployed {format_money(led.peak_reserved)}</div>
  </div>
  <div class="card">
    <h3>With $7,500 / month wire</h3>
    <div class="metric">{format_money(wd['led'].end_equity)}</div>
    <div class="small">Withdrawn {format_money(wd['led'].withdrawals)} · skipped {wd['led'].n_wd_skip} months</div>
    <div class="small">Interest {format_money(wd['led'].interest)}</div>
  </div>
  <div class="card">
    <h3>9-sys 2× + 10.5% (recomputed)</h3>
    <div class="metric">{format_money(nine['led'].end_equity)}</div>
    <div class="small">Published no-interest sibling: {format_money(PUB_9SYS_2X_END)}</div>
    <div class="small">Interest {format_money(nine['led'].interest)}</div>
  </div>"""
    for a in rots:
        cards += f"""
  <div class="card">
    <h3>{html_mod.escape(a['label'])}</h3>
    <div class="metric">{format_money(a['led'].end_equity)}</div>
    <div class="small">Rotates {a['led'].n_rotate} · BP-skip {a['led'].n_skip_bp}</div>
    <div class="small">2010 {format_money(a['led'].eq_2010)}</div>
  </div>"""

    month_sections = ""
    through_month = ASOF.month
    for month in range(1, through_month + 1):
        label = r.monthly._month_label(year, month)
        month_trades = [
            t
            for t in year_closed
            if t.closed and t.closed.year == year and t.closed.month == month
        ]
        if not month_trades:
            month_sections += f"""
<section class="month-section">
  <h2>{label}</h2>
  <p class="small muted">No sized 5-sys control closes this month.</p>
</section>"""
            continue
        month_total = sum(t.overlay_pnl for t in month_trades)
        month_sections += f"""
<section class="month-section">
  <h2>{label} · <span class="{r._pnl_class(month_total)}">{r._fmt_money_signed(month_total)}</span> control wallet</h2>
  <div class="table-wrap">{_trade_table(month_trades)}</div>
</section>"""

    compare_sections = ""
    col_map = {
        "IS": "stats_is",
        "OOS": "stats_oos",
        "FULL": "stats_full",
    }
    for sl, note in (
        ("IS", "In-Sample — entry before 2024-01-01. Path is continuous; do not retune OOS."),
        ("OOS", "Out-of-Sample — report-only. Wallet dollars already felt the IS path."),
        ("FULL", verdict),
    ):
        cols = [
            (ctrl["label"], ctrl[col_map[sl]]),
            (wd["label"], wd[col_map[sl]]),
            (nine["label"], nine[col_map[sl]]),
        ]
        for a in rots:
            cols.append((a["label"], a[col_map[sl]]))
        compare_sections += f"""
<section>
<h2>Canonical compare · {sl}</h2>
<p class="small">{html_mod.escape(note)} Sheet / Total PnL $ omitted. Click headers to sort.</p>
<div class="table-wrap">{_canonical_table(cols)}</div>
</section>"""

    sources_html = "".join(f"<li>{html_mod.escape(s)}</li>" for s in sources)
    gen_s = now.strftime("%Y-%m-%d %H:%M %Z")
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Five systems, 2×, 10.5% — {year}</title>
<style>{_css()}</style></head><body>
<h1>Monthly Backtest Report — {year} · SB / RSI / VZ / MTS / RL · one $250k wallet</h1>
<p class="sub">
Stamp <code>{STAMP}</code>. Research only. <strong>Not gold. Not DailyRun.</strong>
Does not overwrite the static $2,500
<a href="../risk2500_monthly_20260917/monthly.html">monthly.html</a> you liked.
Dropped: Break and ReTest (BRT), Year High (YH), Weekly Pivot Break and Retest (WPBR),
Relative Strength vs SPY (RS), Indicators (IND). Generated {html_mod.escape(gen_s)}.
Click column headers to sort.
</p>
<div class="ask">
<h2>What you asked</h2>
<blockquote>{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN_ENGLISH)}</p>
</div>
<div class="proceed-box">
<h2>How to proceed (yes / no)</h2>
<p class="small">Research-only list. Grounded in the live −$192k book and this paper. You can answer each line.</p>
{_proceed_html(ctrl, spy, rots)}
</div>
<div class="lead">
<h2>Headline</h2>
<p><strong>SPY $250k from 2010-01-04 → {format_money(spy['tr_end'])} today</strong>
({spy['tr_mult']:.2f}× total return on Adj Close {html_mod.escape(spy['start_date'])}→{html_mod.escape(spy['end_date'])}).
Price-only (no dividends) would be {format_money(spy['price_end'])} ({spy['price_mult']:.2f}×).</p>
<p><strong>Five-system one-wallet 2× + 10.5% (no rotation) ends at {format_money(led.end_equity)}</strong>
vs that SPY number. Interest paid {format_money(led.interest)}.
2010–2012: {format_money(led.eq_2010)} / {format_money(led.eq_2011)} / {format_money(led.eq_2012)}
vs SPY TR {format_money(spy['years'].get(2010, {}).get('tr', 0))} /
{format_money(spy['years'].get(2011, {}).get('tr', 0))} /
{format_money(spy['years'].get(2012, {}).get('tr', 0))}.</p>
<p>Rotation is <strong>HOLD</strong>. $7,500 wires explain the live ~$58k balance gap
(~8 months × $7,500 ≈ $60k). Do not go back to $75–100k lots.</p>
</div>
<div class="hold"><strong>{html_mod.escape(verdict)}</strong></div>
<div class="warn">
<strong>Interest is daily compound at 10.5% / 365 on the debit</strong>
(borrowed = max(0, open notional − Closed-only equity) = max(0, −cash)).
Rotation marks use the last daily close on or before the sale date — not the
eventual house exit (that would be look-ahead). $7,500 leaves on the 1st
<em>before</em> that month’s 1% is frozen, starting 2010-02-01, whenever equity
≥ $7,500 (margin may rise). Closed-only 2× test does not flatten an already-open
book if a loser shrinks the cap.
</div>
<div class="cards">{cards}</div>
<section>
<h2>All books at a glance</h2>
<p class="small">Same house Closed pins. Only the wallet / rotation / withdrawal / system-set changes. Click headers to sort.</p>
<div class="table-wrap">{_path_table(arms_all, spy, nine)}</div>
</section>
<section>
<h2>Year-end equity vs SPY</h2>
{_year_vs_spy_table(arms_all + [nine], spy)}
</section>
<section>
<h2>Monthly realized 5-sys control P&amp;L by system ({year})</h2>
<p class="small">Closed trades by exit month on the no-rotation book. Total row pinned. Click headers to sort.</p>
{pivot_html}
</section>
<section>
<h2>All years — 5-sys control overlay realized $</h2>
{hist_html}
</section>
<section>
<h2>Buying-power + interest ledger (control)</h2>
{_ledger_table(ctrl['snaps'])}
</section>
<section>
<h2>Buying-power + interest ledger (with $7,500 wd)</h2>
{_ledger_table(wd['snaps'])}
</section>
{compare_sections}
{month_sections}
<section>
<h2>Open positions (control, cost basis; mark uses last close)</h2>
<div class="table-wrap">{_trade_table(open_rows, open_book=True) if open_rows else '<p class="small muted">No sized open control positions.</p>'}</div>
</section>
<section>
<h2>Data sources</h2>
<ul class="sources">{sources_html}</ul>
<p class="small">Sibling static monthly (do not overwrite):
<a href="../risk2500_monthly_20260917/monthly.html">risk2500_monthly_20260917/monthly.html</a>.
Live book: <a href="../live_drawdown_20260917/report.html">live_drawdown_20260917/report.html</a>.
Compare page: <a href="compare.html">compare.html</a>.
Acronyms: StockBee (SB); Relative Strength Index (RSI); Volume Zone (VZ);
Magic Touch (MTS); Rocket Launcher (RL); Break and ReTest (BRT); Year High (YH);
Weekly Pivot Break and Retest (WPBR); Relative Strength vs SPY (RS);
In-Sample (IS); Out-of-Sample (OOS); buying power (BP); beginning-of-month (BOM);
S&amp;P 500 tracker (SPY).</p>
</section>
{r.monthly._SORTABLE_TABLE_SCRIPT}
</body></html>"""


def _five_pivot(closed: list[r.OverlayTrade], *, year: int, through_month: int) -> tuple[str, str]:
    """Same shape as compound._pivot_and_hist but columns = FIVE."""
    old = c.SYSTEMS
    try:
        c.SYSTEMS = FIVE
        return c._pivot_and_hist(closed, year=year, through_month=through_month)
    finally:
        c.SYSTEMS = old


def build_compare(
    *,
    ctrl: dict[str, Any],
    wd: dict[str, Any],
    rots: list[dict[str, Any]],
    nine: dict[str, Any],
    spy: dict[str, Any],
    verdict: str,
    sources: list[str],
    generated: datetime,
) -> str:
    now = generated.astimezone(ET)
    gen_s = now.strftime("%Y-%m-%d %H:%M %Z")
    arms_all = [ctrl, wd] + rots
    for a, cap, read in (
        (
            ctrl,
            "5 systems · open ≤ 2× · 10.5% · skip if no BP",
            "Control.",
        ),
        (
            wd,
            "Control + $7,500 on the 1st",
            "Bank-wire arm.",
        ),
        (
            nine,
            "9 DailyRun systems · 2× · 10.5%",
            "Fair 9-sys compare with interest on.",
        ),
    ):
        a["cap"] = cap
        a["read"] = read
    for a in rots:
        a["cap"] = a["rotate"]
        a["read"] = "HOLD — in-sample rotation."

    cols_full = [
        ("SPY is not a trade book", {"n": 1, "total_pnl": spy["tr_end"] - ACCOUNT}),
        (ctrl["label"], ctrl["stats_full"]),
        (wd["label"], wd["stats_full"]),
        (nine["label"], nine["stats_full"]),
    ]
    for a in rots:
        cols_full.append((a["label"], a["stats_full"]))

    # SPY is equity path, not overlay stats — compare wallets only vs SPY dollars in the path table.
    wallet_cols = [
        (ctrl["label"], ctrl["stats_full"]),
        (wd["label"], wd["stats_full"]),
        (nine["label"], nine["stats_full"]),
    ]
    for a in rots:
        wallet_cols.append((a["label"], a["stats_full"]))

    least = min(rots, key=lambda a: a["led"].end_equity) if rots else None
    best = max(rots, key=lambda a: a["led"].end_equity) if rots else None
    rot_note = ""
    if least and best:
        rot_note = (
            f"Among rotation arms, lowest paper ending is {least['label']} "
            f"({format_money(least['led'].end_equity)}); highest is {best['label']} "
            f"({format_money(best['led'].end_equity)}). Least-bad is not KEEP. HOLD."
        )

    sources_html = "".join(f"<li>{html_mod.escape(s)}</li>" for s in sources)
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Five-sys 2× + 10.5% vs SPY vs 9-sys — {STAMP}</title>
<style>{_css()}</style></head><body>
<h1>Compare — five systems vs SPY buy-hold vs 9-system 2×</h1>
<p class="sub">Stamp <code>{STAMP}</code> · as-of {ASOF.isoformat()} ·
<strong>not gold · not DailyRun</strong>. Generated {html_mod.escape(gen_s)}.
Click column headers to sort.</p>
<div class="ask">
<h2>What you asked</h2>
<blockquote>{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN_ENGLISH)}</p>
</div>
<div class="proceed-box">
<h2>How to proceed (yes / no)</h2>
{_proceed_html(ctrl, spy, rots)}
</div>
<div class="lead">
<p><strong>SPY $250k → {format_money(spy['tr_end'])}</strong> ({spy['tr_mult']:.2f}× total return).
<strong>5-sys 2× + 10.5% → {format_money(ctrl['led'].end_equity)}</strong>.
9-sys 2× + 10.5% → {format_money(nine['led'].end_equity)}
(published no-interest sibling {format_money(PUB_9SYS_2X_END)}).
{html_mod.escape(rot_note)}</p>
</div>
<div class="hold"><strong>{html_mod.escape(verdict)}</strong></div>
<section>
<h2>Ending $ and 2010–2012 (the honest years)</h2>
<p class="small">If 2013+ still looks like a lottery ticket, that is leftover capacity fiction. Click headers to sort.</p>
<div class="table-wrap">{_path_table(arms_all, spy, nine)}</div>
</section>
<section>
<h2>Year-end equity vs SPY</h2>
{_year_vs_spy_table(arms_all + [nine], spy)}
</section>
<section>
<h2>Canonical book metrics · FULL</h2>
<p class="small">Control = 5-sys no-rotation. Deltas vs control. Sheet / Total PnL $ omitted. Click headers to sort.</p>
<div class="table-wrap">{_canonical_table(wallet_cols)}</div>
</section>
<section>
<h2>Canonical book metrics · IS</h2>
<p class="small">In-Sample — entry before 2024-01-01. Do not retune OOS.</p>
<div class="table-wrap">{_canonical_table(
    [(ctrl['label'], ctrl['stats_is']), (wd['label'], wd['stats_is']), (nine['label'], nine['stats_is'])]
    + [(a['label'], a['stats_is']) for a in rots]
)}</div>
</section>
<section>
<h2>Canonical book metrics · OOS</h2>
<p class="small">Out-of-Sample — report-only. Path already felt IS.</p>
<div class="table-wrap">{_canonical_table(
    [(ctrl['label'], ctrl['stats_oos']), (wd['label'], wd['stats_oos']), (nine['label'], nine['stats_oos'])]
    + [(a['label'], a['stats_oos']) for a in rots]
)}</div>
</section>
<section>
<h2>Live $7,500 wires vs the $58k gap</h2>
<p>{html_mod.escape(LIVE_GAP_NOTE)}</p>
</section>
<section>
<h2>Data sources</h2>
<ul class="sources">{sources_html}</ul>
<p class="small">Monthly: <a href="monthly.html">monthly.html</a>.
Sibling 2× no-interest: <a href="../risk2500_monthly_20260917/monthly_onaccount_2x.html">monthly_onaccount_2x.html</a>.</p>
</section>
{r.monthly._SORTABLE_TABLE_SCRIPT}
</body></html>"""


def write_baseline(
    *,
    ctrl: dict[str, Any],
    wd: dict[str, Any],
    rots: list[dict[str, Any]],
    nine: dict[str, Any],
    spy: dict[str, Any],
    verdict: str,
    sources: list[str],
) -> None:
    led = ctrl["led"]
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
        "## Live $7,500 wires vs the $58k gap",
        "",
        LIVE_GAP_NOTE,
        "",
        "## Selection",
        "",
        "- Combined proceed job (SPY bench + 5-sys monthly + rotation + how to proceed).",
        "- One $250,000 wallet. Systems: Rocket Launcher (RL), Magic Touch (MTS), StockBee (SB), Volume Zone (VZ), Relative Strength Index (RSI).",
        "- Dropped: Break and ReTest (BRT), Year High (YH), Weekly Pivot Break and Retest (WPBR), Relative Strength vs SPY (RS), Indicators (IND, already deprecated).",
        "- `risk_dollar = 0.01 × start-of-month Closed-only equity` after prior realized, interest, and (wd arm) withdrawals.",
        "- RSI In-Sample avg-loss freeze **6.509607%** (do not retune on OOS). `invested = risk_dollar / 0.06509607`.",
        "- Other systems: `shares = risk_dollar / (entry − stop)`, then buying-power clip.",
        "- Hard cap on new fills: open notional ≤ 2 × equity. Scale to remaining buying power. Skip if BP < $1.",
        "- Margin interest **10.5% annual**, daily compound (actual/365) on `max(0, −cash)` for every calendar day the debit is open.",
        "- Control = no rotation (skip when no BP). Candidates = sell biggest $ loser / oldest / most $ profitable at last close, then take the new fill. One knob each.",
        "- Optional arm `with_7500_wd`: $7,500 cash on the 1st starting 2010-02-01 when equity ≥ $7,500, even if that increases the loan.",
        "- Same-day fill order (match 2× sibling): older closes; then entries by DailyRun system order then symbol; then same-day exits.",
        "- Rotation mark: last daily close on or before sale date vs entry (no eventual-exit look-ahead).",
        f"- Decision: **{verdict}**",
        "",
        "## Frozen knobs",
        "",
        f"- Account seed: **${ACCOUNT:,.0f}**",
        f"- Leverage cap: **{LEVERAGE:.0f}×** Closed-only equity",
        f"- Margin rate: **{MARGIN_RATE:.1%}** actual/365 daily compound",
        f"- Withdrawal arm: **${WITHDRAW:,.0f}** on month-start after 2010-01-01",
        "- In-Sample (IS) = `entry_date < 2024-01-01`. OOS report-only. Path is continuous.",
        "- CONTROL = 5-sys no-rotation 2× + 10.5%.",
        "- Same Closed / Open pins as `risk2500_monthly_20260917` overlays (RSI = avg-loss CSV).",
        "- Do not overwrite sibling `monthly.html` (static $2,500).",
        "",
        "## SPY $250k from 2010-01-01",
        "",
        f"- First bar used: **{spy['start_date']}** (first session on/after 2010-01-01).",
        f"- Last bar used: **{spy['end_date']}**.",
        f"- Total return (Adj Close {spy['adj0']:.4f} → {spy['adj1']:.4f}): "
        f"**${spy['tr_end']:,.2f}** ({spy['tr_mult']:.4f}×).",
        f"- Price-only (Close {spy['px0']:.4f} → {spy['px1']:.4f}): "
        f"**${spy['price_end']:,.2f}** ({spy['price_mult']:.4f}×).",
        "- We lead with total return. Price-only is labeled.",
        "",
        "## 5-sys control ledger",
        "",
        f"- End equity **${led.end_equity:,.2f}** (cash ${led.end_cash:,.2f} + reserved ${led.end_reserved:,.2f}).",
        f"- Realized overlay ${led.realized:,.2f}; interest paid ${led.interest:,.2f}; withdrawals ${led.withdrawals:,.2f}.",
        f"- Identity |cash+reserved − (250k+realized−interest−wd)| = {led.identity_err}",
        f"- Peak reserved ${led.peak_reserved:,.2f}; peak loan ${led.peak_loan:,.2f}.",
        f"- Full {led.n_full}; scaled {led.n_scaled}; BP-skip {led.n_skip_bp}; cannot-size {led.n_skip_size}; rotate {led.n_rotate}.",
        f"- 2010 ${led.eq_2010:,.2f}; 2011 ${led.eq_2011:,.2f}; 2012 ${led.eq_2012:,.2f}.",
        "",
        "## Other arms",
        "",
        f"- with_7500_wd end **${wd['led'].end_equity:,.2f}**; withdrawn ${wd['led'].withdrawals:,.2f}; "
        f"interest ${wd['led'].interest:,.2f}; wd months {wd['led'].n_wd}; skipped {wd['led'].n_wd_skip}.",
        f"- 9-sys 2× + 10.5% end **${nine['led'].end_equity:,.2f}**; interest ${nine['led'].interest:,.2f}; "
        f"2010 ${nine['led'].eq_2010:,.2f}.",
        f"- Published 9-sys 2× **no interest** (sibling): **${PUB_9SYS_2X_END:,.2f}** (2010 ${PUB_9SYS_2X_2010:,.2f}).",
    ]
    for a in rots:
        lines.append(
            f"- {a['label']} end **${a['led'].end_equity:,.2f}**; rotates {a['led'].n_rotate}; "
            f"BP-skip {a['led'].n_skip_bp}; 2010 ${a['led'].eq_2010:,.2f}; interest ${a['led'].interest:,.2f}."
        )
    st = ctrl["stats_full"]
    lines += [
        "",
        "## Honesty",
        "",
        "- Later-year five-system dollars can still be capacity fiction (tight stops + 1% of a growing pile + 2×). Read 2010–2012 vs SPY.",
        "- 10.5% was missing from the $314B page. This stamp charges it.",
        "- Rotation ranking uses last close vs entry (Closed-only sim). Forced exits replace the house exit path.",
        "- Picking KEEP from this same history would be in-sample selection. We are not adopting rotation or a 5-sys DailyRun cut.",
        "- Live damage was $75–100k lots and a 12-name / $979k June stack on margin — not the September RSI / VZ wires.",
        "",
        "## FULL quality (5-sys control)",
        "",
        f"- N={st.get('n')} WR={st.get('win_pct')} Avg%={st.get('avg_pnl_pct')} "
        f"PF={st.get('pf')} AnnROR$250k={st.get('ann_ror_250k')} MaxDD={st.get('max_dd')} "
        f"Calmar={st.get('calmar')} Sharpe={st.get('sharpe')} "
        f"mean$={st.get('mean_notional')} peak$={st.get('peak_notional')} "
        f"end_equity=${led.end_equity:,.2f}",
        "",
        "## Pins / sources",
        "",
    ]
    for s in sources:
        lines.append(f"- {s}")
    lines.append("")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_hypothesis(verdict: str) -> None:
    text = f"""# HYPOTHESIS — {STAMP}

**Product owner (PO)–aligned process:** one knob per arm, frozen everything else. See `docs/HYPOTHESIS_TEST.md`.

| Field | Fill in |
|-------|---------|
| System / prefix | Five-system paper book: {", ".join(FIVE)} (dropped {", ".join(DROPPED)}) |
| Baseline stamp | House overlays in `risk2500_monthly_20260917` (RSI = IS avg-loss CSV) |
| Universe | House DailyRun universes (unchanged) |
| **Evidence** | Paul: SPY $250k since 2010; proceed from live −$192k + $7,500/mo wires; 5-sys monthly; rotate at 2× cap; 10.5% margin |
| **Hypothesis** | (1) SPY buy-hold is the honest $250k yardstick. (2) A 5-sys 2× wallet with 10.5% interest is a finite path vs the $314B no-interest 9-sys page. (3) Rotation at the cap is one knob vs skip-when-no-BP — do not adopt from one horse-race |
| **Single knob** | Per arm: system set (5 vs 9) **or** withdrawal **or** rotation rule. Monthly 1%, RSI 6.51% freeze, 2× cap, 10.5% stay frozen inside each arm |
| Frozen settings | House entries/exits/pins. RSI 6.509607% IS freeze. Fill order: older closes, then system then symbol. Interest actual/365 daily compound. Rotation mark = last close ≤ sale date |
| Alternatives | CONTROL = 5-sys no-rotation 2× + 10.5%. `with_7500_wd`. sell_loser / sell_oldest / sell_winner. 9-sys 2× + 10.5%. SPY $250k total return |
| Candidate stamps | `{STAMP}` monthly.html / compare.html |
| Metrics | Canonical book set + wallet ending equity + 2010–2012 vs SPY; judge quality not as-of dollars |
| **Trade-diff HTML** | N/A — size / wallet / rotation overlay (not an entry A/B) |
| ToS before path | N/A |
| ToS after path | N/A |
| **Decision** | {verdict} |
| Reviewer | AI job {STAMP} |
| PO sign-off | no |
| Reconcile freeze / re-baseline done | no |
| DailyRun | not wired |

## Decision checklist

- [x] Evidence was the PO ask (SPY + 5-sys + rotation + 10.5% + $7,500 wires)
- [x] One knob per rotation / withdrawal arm
- [x] Same Closed pins as the sibling $2,500 stamp
- [x] Out-of-Sample (OOS) report-only; no RSI retune
- [ ] If adopt: PO signed off — **not adopting**
"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "HYPOTHESIS.md").write_text(text, encoding="utf-8")


def _run_arm(
    static: list[r.OverlayTrade],
    *,
    rank: dict[str, int],
    rotate: str,
    withdraw: bool,
    label: str,
    risk_frac: Optional[float] = None,
    through: date = ASOF,
    name_cap_frac: Optional[float] = None,
    fixed_risk_dollar: Optional[float] = None,
    max_risk_dollar: Optional[float] = None,
    adv_frac: Optional[float] = None,
    start_equity: Optional[float] = None,
    sector_cap_frac: Optional[float] = None,
    sector_map: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    print(
        f"[run] {label} rotate={rotate} wd={withdraw} n_src={len(static)} "
        f"name_cap={name_cap_frac} fixed_risk={fixed_risk_dollar} "
        f"max_risk={max_risk_dollar} adv_frac={adv_frac} start={start_equity} "
        f"sector_cap={sector_cap_frac}",
        flush=True,
    )
    trades, snaps, led = run_wallet(
        static,
        rank=rank,
        rotate=rotate,
        withdraw=withdraw,
        through=through,
        risk_frac=risk_frac,
        name_cap_frac=name_cap_frac,
        fixed_risk_dollar=fixed_risk_dollar,
        max_risk_dollar=max_risk_dollar,
        adv_frac=adv_frac,
        start_equity=start_equity,
        sector_cap_frac=sector_cap_frac,
        sector_map=sector_map,
    )
    pack = _arm_pack(
        trades,
        snaps,
        led,
        rank=rank,
        rotate=rotate,
        withdraw=withdraw,
        label=label,
        risk_frac=risk_frac,
        through=through,
        fixed_risk_dollar=fixed_risk_dollar,
        max_risk_dollar=max_risk_dollar,
        adv_frac=adv_frac,
        start_equity=start_equity,
    )
    pack["name_cap_frac"] = 0.0 if name_cap_frac is None else float(name_cap_frac)
    pack["sector_cap_frac"] = 0.0 if sector_cap_frac is None else float(sector_cap_frac)
    print(
        f"  end={led.end_equity:.2f} 2010={led.eq_2010:.2f} 2011={led.eq_2011:.2f} "
        f"2012={led.eq_2012:.2f} int={led.interest:.2f} wd={led.withdrawals:.2f} "
        f"full={led.n_full} scaled={led.n_scaled} skip_bp={led.n_skip_bp} "
        f"rot={led.n_rotate} name_cap={led.n_name_capped} skip_name={led.n_skip_name} "
        f"risk50k={led.n_risk_50k_bound} risk1pct={led.n_risk_1pct_bound} "
        f"adv_clip={led.n_adv_clipped} adv_miss={led.n_adv_missing} "
        f"adv_last={led.n_adv_last_known} skip_adv={led.n_skip_adv} "
        f"mo50k={led.n_months_50k} "
        f"sec_rot={led.n_sector_rotate} sec_cap={led.n_sector_capped} "
        f"skip_sec={led.n_skip_sector} "
        f"peak_name={led.peak_name_notional:.2f}({led.peak_name_symbol}) "
        f"peak_sec={led.peak_sector_notional:.2f}({led.peak_sector_name}) "
        f"peak_book={led.peak_reserved:.2f} ident={led.identity_err:.6f}",
        flush=True,
    )
    return pack


def run() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    spy = spy_buyhold()
    print(
        f"[SPY] {spy['start_date']} -> {spy['end_date']} "
        f"TR {spy['tr_end']:.2f} ({spy['tr_mult']:.3f}x) "
        f"px {spy['price_end']:.2f} ({spy['price_mult']:.3f}x)",
        flush=True,
    )

    five_static = load_static(FIVE)
    nine_static = load_static(NINE)
    sources = [
        f"overlays: {PREV_DIR.name} (RSI = RSI_overlay_avgloss.csv IS 6.51% freeze)",
        f"systems five: {', '.join(FIVE)}",
        f"dropped: {', '.join(DROPPED)}",
        f"SPY: {SPY_PATH.as_posix()} Adj Close total return + Close price-only",
        "live gap: drive/paul_experiments/live_drawdown_20260917 (Paul: $7,500/mo wires)",
        "fill order: older closes; DailyRun system then symbol; same-day exits",
        "interest: 10.5% / 365 daily compound on max(0, −cash)",
        "rotation mark: last close on or before sale vs entry (no look-ahead to house exit)",
    ]

    ctrl = _run_arm(
        five_static,
        rank=FIVE_RANK,
        rotate="none",
        withdraw=False,
        label="5-sys no-rotation (control)",
    )
    wd = _run_arm(
        five_static,
        rank=FIVE_RANK,
        rotate="none",
        withdraw=True,
        label="5-sys + $7,500 wd",
    )
    rot_loser = _run_arm(
        five_static,
        rank=FIVE_RANK,
        rotate="loser",
        withdraw=False,
        label="5-sys sell biggest loser",
    )
    rot_oldest = _run_arm(
        five_static,
        rank=FIVE_RANK,
        rotate="oldest",
        withdraw=False,
        label="5-sys sell oldest",
    )
    rot_winner = _run_arm(
        five_static,
        rank=FIVE_RANK,
        rotate="winner",
        withdraw=False,
        label="5-sys sell most profitable",
    )
    nine = _run_arm(
        nine_static,
        rank=NINE_RANK,
        rotate="none",
        withdraw=False,
        label="9-sys 2× + 10.5% (no rotation)",
    )
    rots = [rot_loser, rot_oldest, rot_winner]
    verdict = _verdict(ctrl, rots, spy)
    print(f"[verdict] {verdict}", flush=True)

    r.write_overlay_csv(ctrl["trades"], OUT_DIR / "ALL_overlay_five_norot.csv")
    r.write_overlay_csv(wd["trades"], OUT_DIR / "ALL_overlay_five_wd7500.csv")
    r.write_overlay_csv(rot_loser["trades"], OUT_DIR / "ALL_overlay_five_rot_loser.csv")
    r.write_overlay_csv(rot_oldest["trades"], OUT_DIR / "ALL_overlay_five_rot_oldest.csv")
    r.write_overlay_csv(rot_winner["trades"], OUT_DIR / "ALL_overlay_five_rot_winner.csv")
    r.write_overlay_csv(nine["trades"], OUT_DIR / "ALL_overlay_nine_2x_int.csv")

    now = datetime.now(tz=ET)
    monthly_html = build_monthly(
        ctrl=ctrl,
        wd=wd,
        rots=rots,
        nine=nine,
        spy=spy,
        verdict=verdict,
        sources=sources,
        generated=now,
    )
    compare_html = build_compare(
        ctrl=ctrl,
        wd=wd,
        rots=rots,
        nine=nine,
        spy=spy,
        verdict=verdict,
        sources=sources,
        generated=now,
    )
    (OUT_DIR / "monthly.html").write_text(monthly_html, encoding="utf-8")
    (OUT_DIR / "compare.html").write_text(compare_html, encoding="utf-8")
    write_baseline(
        ctrl=ctrl,
        wd=wd,
        rots=rots,
        nine=nine,
        spy=spy,
        verdict=verdict,
        sources=sources,
    )
    write_hypothesis(verdict)

    summary = {
        "spy_tr_end": spy["tr_end"],
        "spy_tr_mult": spy["tr_mult"],
        "spy_price_end": spy["price_end"],
        "spy_start": spy["start_date"],
        "spy_end": spy["end_date"],
        "five_norot_end": ctrl["led"].end_equity,
        "five_norot_2010": ctrl["led"].eq_2010,
        "five_norot_2011": ctrl["led"].eq_2011,
        "five_norot_2012": ctrl["led"].eq_2012,
        "five_norot_interest": ctrl["led"].interest,
        "five_wd_end": wd["led"].end_equity,
        "five_wd_withdrawn": wd["led"].withdrawals,
        "nine_int_end": nine["led"].end_equity,
        "nine_int_interest": nine["led"].interest,
        "pub_nine_no_int": PUB_9SYS_2X_END,
        "rot_loser_end": rot_loser["led"].end_equity,
        "rot_oldest_end": rot_oldest["led"].end_equity,
        "rot_winner_end": rot_winner["led"].end_equity,
        "rot_loser_n": rot_loser["led"].n_rotate,
        "rot_oldest_n": rot_oldest["led"].n_rotate,
        "rot_winner_n": rot_winner["led"].n_rotate,
        "verdict": verdict,
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"wrote {OUT_DIR / 'monthly.html'}", flush=True)
    print(f"wrote {OUT_DIR / 'compare.html'}", flush=True)
    print(json.dumps({k: v for k, v in summary.items() if k != "verdict"}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
