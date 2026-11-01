#!/usr/bin/env python3
"""$2,500 risk-to-stop size overlay + monthly-style report (research only).

Paul: account is now $250k (was $500k). Size every DailyRun fill so that if
the stop hits, max $ lost = $2,500 (1% of $250k).

Same house Closed / Open pins as generate_monthly_system_report.py.
Entries / exits / universes frozen. SIZE overlay only.

Relative Strength Index (RSI) Closed writes STOP_PRICE=0. Freeze: implied
roll-8 what-if close (RSI14 <= in-trade-max-at-fill − 8) from SIGNAL_DATE
Wilder state. Not an Average True Range (ATR) % proxy. Not gold. Not DailyRun.
"""
from __future__ import annotations

import csv
import html as html_mod
import importlib.util
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "stock_analysis"))
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))

from compare_format import (  # noqa: E402
    ann_ror_from_closed,
    filter_html_compare_columns,
    format_money,
    format_money_delta,
    is_excluded_html_compare_label,
    overlay_ann_ror_max_dd,
)
from rocket_rsi import (  # noqa: E402
    _wilder_rsi14_avg_state,
    invert_close_for_rsi_at_or_below,
)
_DRS_SPEC = importlib.util.spec_from_file_location(
    "dailyrun_system_status",
    REPO / "tools" / "dailyrun_system_status.py",
)
_drs = importlib.util.module_from_spec(_DRS_SPEC)
assert _DRS_SPEC.loader is not None
sys.modules["dailyrun_system_status"] = _drs
_DRS_SPEC.loader.exec_module(_drs)
live_wired_systems = _drs.live_wired_systems

_MONTHLY_SPEC = importlib.util.spec_from_file_location(
    "generate_monthly_system_report",
    REPO / "generate_monthly_system_report.py",
)
monthly = importlib.util.module_from_spec(_MONTHLY_SPEC)
assert _MONTHLY_SPEC.loader is not None
sys.modules["generate_monthly_system_report"] = monthly
_MONTHLY_SPEC.loader.exec_module(monthly)

STAMP = "risk2500_monthly_20260917"
OUT_DIR = REPO / "drive" / "paul_experiments" / STAMP
DRIVE = REPO / "drive"
DATA_DIR = REPO / "data" / "newdata" / "data"
ET = ZoneInfo("America/New_York")
IS_CUT = date(2024, 1, 1)
ACCOUNT = 250_000.0
RISK_DOLLARS = 2_500.0  # 1% of $250k
RSI_ROLL = 8.0
ACCOUNT_500K = 500_000.0
ACCOUNT_600K = 600_000.0
ASOF = date(2026, 9, 17)

# Layout-only: keep this block in every report <style> so tables grow with the
# window (no inner X/Y scroll box). Page scroll is OK when the window is small.
TABLE_UNCAP_CSS = """
/* table-uncap: grow with the window; no inner scroll box. Keep this block if you regenerate. */
body { max-width: none; }
.table-wrap { max-height: none !important; overflow: visible !important; }
table, table.sortable { width: 100%; min-width: 0; }
th.sortable-th { white-space: normal; }
th, td { overflow-wrap: anywhere; }
"""

# House dummy / sheet notionals (DailyRun identity). Overlay does not use these
# for size; they are the CONTROL dollars when Closed PNL cannot invert a slot.
SHEET_DEFAULT = {
    "BRT": 47_500.0,
    "RL": 47_500.0,
    "YH": 47_500.0,
    "MTS": 47_500.0,
    "WPBR": 47_500.0,
    "RS": 47_500.0,
    "SB": 47_500.0,
    "VZ": 45_000.0,
    "RSI": 10_000.0,
}

SYSTEM_EXPAND = {
    "BRT": "Break and ReTest (BRT)",
    "RL": "Rocket Launcher (RL)",
    "YH": "Year High (YH)",
    "MTS": "Magic Touch (MTS)",
    "WPBR": "Weekly Pivot Break and Retest (WPBR)",
    "RS": "Relative Strength vs SPY (RS)",
    "SB": "StockBee (SB)",
    "VZ": "Volume Zone (VZ)",
    "RSI": "Relative Strength Index (RSI)",
}

ORIGINAL_REQUEST = (
    "can we run each system using the 1% max stop loss for each position? "
    "my account used to be $500k. now it is $250k, so that would be a max "
    "stop loss of $2,500 per entry. I want to see the monthly report using "
    "this new number across all systems."
)
PLAIN_ENGLISH = (
    "Every DailyRun trade stays the same (same ticker, same day, same exit). "
    "We only change how many shares we pretend to buy so that if the stop "
    "is hit, you lose about $2,500 — 1% of a $250,000 account (not the old "
    "$5,000 / 1% of $500k). Shares = $2,500 ÷ (entry − stop). Dollar P&L "
    "is those shares times the price move. Relative Strength Index (RSI) "
    "has no live price stop on Closed (STOP_PRICE=0). First overlay used a "
    "labeled what-if stop: the close that would print RSI 8 points below "
    "the fill-time RSI (the roll-8 exit already in getTarget). That gap is "
    "often a few cents, so size explodes. Paul's follow-up: for RSI only, "
    "use one flat dollar slot so a typical loser is about $2,500."
)
FOLLOWUP_REQUEST = (
    "how are you calculating RSI stop loss? I am thinking the best we can "
    "do with RSI, is maybe calculate the avg loss amount and use that and "
    "calculate the amount to invest expecting that if we lost, it would "
    "avg 1%"
)
FOLLOWUP_PLAIN = (
    "RSI does not have a real price stop — Closed writes STOP_PRICE=0. The "
    "first overlay invented a price by asking: “what close would drop RSI "
    "by 8 points from the entry bar?” Then it bought $2,500 ÷ that tiny "
    "gap. A 20-cent gap on a $20 stock is 1% of price, so the rule buys "
    "$250,000 of that name. Stack a few of those and the book looks like "
    "millions on a $250k account — that is why Maximum Drawdown hit 37%. "
    "Paul’s alternative skips the fake stop. Measure how much a typical "
    "RSI loser actually lost in percent (In-Sample only, before 2024). "
    "Put the same dollars on every RSI fill so that typical loser ≈ $2,500. "
    "Example: if IS losers average −8%, invest $2,500 / 0.08 = $31,250. "
    "Winners and losers both use that slot. One trade can still lose more "
    "or less than $2,500; the average IS loser is calibrated to 1%."
)

SYSTEMS: tuple[str, ...] = live_wired_systems()


@dataclass
class OverlayTrade:
    system: str
    symbol: str
    opened: date
    closed: Optional[date]
    entry: float
    exit_px: Optional[float]
    stop_raw: Optional[float]
    stop_used: Optional[float]
    stop_src: str
    exit_type: str
    days: float
    pnl_pct: float
    house_pnl: float
    house_notional: float
    shares: float
    invested: float
    overlay_pnl: float
    sized: bool
    skip_reason: str
    status: str  # closed | open
    signal_date: Optional[date] = None
    risk_dollar: Optional[float] = None
    equity_bom: Optional[float] = None
    cash_before: Optional[float] = None
    desired_invested: Optional[float] = None
    scaled: bool = False


_OHLC_CACHE: dict[str, Optional[pd.DataFrame]] = {}
_RSI_STATE_CACHE: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list]] = {}


def _parse_date(raw: Any) -> Optional[date]:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s.lower() in {"nan", "none", ""}:
        return None
    s = s.replace("/", "-")
    if "-" in s:
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            pass
    digits = "".join(ch for ch in s if ch.isdigit())[:8]
    if len(digits) == 8:
        try:
            return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
        except ValueError:
            return None
    return None


def _parse_num(raw: Any) -> Optional[float]:
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        if not math.isfinite(float(raw)):
            return None
        return float(raw)
    s = str(raw).strip().replace("$", "").replace(",", "").replace("%", "")
    if not s or s.lower() in {"nan", "none", "—", "-"}:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    if not math.isfinite(v):
        return None
    return v


def _load_ohlc(sym: str) -> Optional[pd.DataFrame]:
    key = (sym or "").strip().upper()
    if not key:
        return None
    if key in _OHLC_CACHE:
        return _OHLC_CACHE[key]
    for name in (f"{key}.csv", f"{key.lower()}.csv"):
        path = DATA_DIR / name
        if not path.is_file():
            continue
        try:
            df = pd.read_csv(path)
        except Exception:
            _OHLC_CACHE[key] = None
            return None
        if "Date" not in df.columns or "Close" not in df.columns:
            _OHLC_CACHE[key] = None
            return None
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.dropna(subset=["Date", "Close"]).sort_values("Date")
        df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
        df = df.dropna(subset=["Close"])
        _OHLC_CACHE[key] = df
        return df
    _OHLC_CACHE[key] = None
    return None


def _rsi_state(sym: str) -> Optional[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list]]:
    if sym in _RSI_STATE_CACHE:
        return _RSI_STATE_CACHE[sym]
    df = _load_ohlc(sym)
    if df is None or df.empty:
        _RSI_STATE_CACHE[sym] = None  # type: ignore[assignment]
        return None
    close = df["Close"].to_numpy(dtype=float)
    dates = [d.date() if hasattr(d, "date") else d for d in df["Date"]]
    rsi, ag, al = _wilder_rsi14_avg_state(close)
    pack = (close, rsi, ag, al, dates)
    _RSI_STATE_CACHE[sym] = pack
    return pack


def implied_roll8_stop(
    symbol: str,
    *,
    signal: Optional[date],
    opened: date,
    rsi_at_trigger: Optional[float],
) -> tuple[Optional[float], str]:
    """What-if close that prints RSI <= (RSI at fill-time max − 8).

    Fill-time max is the trigger-bar RSI (SIGNAL_DATE / last complete bar
    before DATE_OPENED). No look-ahead to the later in-trade RSI peak.
    """
    pack = _rsi_state(symbol)
    if pack is None:
        return None, "no_ohlc"
    close, rsi, ag, al, dates = pack
    idx = None
    if signal is not None:
        for i, d in enumerate(dates):
            if d == signal:
                idx = i
                break
    if idx is None:
        for i, d in enumerate(dates):
            if d < opened:
                idx = i
            else:
                break
    if idx is None:
        return None, "no_bar"
    prev_c = float(close[idx])
    rsi_now = float(rsi[idx]) if idx < len(rsi) and np.isfinite(rsi[idx]) else None
    if rsi_now is None and rsi_at_trigger is not None:
        rsi_now = float(rsi_at_trigger)
    if rsi_now is None or not math.isfinite(rsi_now):
        return None, "rsi_not_ready"
    floor = rsi_now - RSI_ROLL
    if floor <= 0:
        return None, "max_low"
    ag_v = float(ag[idx]) if idx < len(ag) and np.isfinite(ag[idx]) else None
    al_v = float(al[idx]) if idx < len(al) and np.isfinite(al[idx]) else None
    if ag_v is None or al_v is None:
        return None, "rsi_not_ready"
    stop, hint = invert_close_for_rsi_at_or_below(prev_c, ag_v, al_v, floor)
    if stop is None or stop <= 0:
        return None, hint or "impossible"
    return float(stop), f"roll8_{hint}"


def _house_notional(pnl_d: float, pnl_pct: float, default: float) -> float:
    if abs(pnl_pct) > 1e-9:
        return abs(pnl_d / (pnl_pct / 100.0))
    return default


def size_from_stop(
    entry: float, stop: Optional[float], risk_dollar: float = RISK_DOLLARS
) -> tuple[float, float, bool, str]:
    if stop is None or not math.isfinite(stop) or stop <= 0:
        return 0.0, 0.0, False, "stop_missing"
    if entry <= 0 or not math.isfinite(entry):
        return 0.0, 0.0, False, "bad_entry"
    if risk_dollar is None or not math.isfinite(risk_dollar) or risk_dollar <= 0:
        return 0.0, 0.0, False, "bad_risk"
    risk_px = entry - stop
    if risk_px <= 0:
        return 0.0, 0.0, False, "stop_ge_entry"
    shares = float(risk_dollar) / risk_px
    invested = shares * entry
    if not math.isfinite(shares) or shares <= 0 or not math.isfinite(invested):
        return 0.0, 0.0, False, "bad_size"
    return shares, invested, True, "ok"


def _resolve_paths() -> dict[str, dict[str, Optional[Path]]]:
    drive = monthly._resolve_drive(DRIVE)
    all_paths = monthly._resolve_system_paths(drive)
    return {sys: all_paths[sys] for sys in SYSTEMS if sys in all_paths}


def _row_get(raw: dict[str, str], *names: str) -> str:
    upper = {k.upper(): v for k, v in raw.items()}
    for name in names:
        if name.upper() in upper:
            return upper[name.upper()]
    return ""


def load_closed_rows(path: Path, system: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for raw in csv.DictReader(f):
            opened = _parse_date(_row_get(raw, "DATE_OPENED", "DATE OPENED"))
            closed = _parse_date(_row_get(raw, "DATE_CLOSED", "DATE CLOSED"))
            entry = _parse_num(_row_get(raw, "ENTRY_PRICE", "ENTRY PRICE"))
            if opened is None or closed is None or entry is None or entry <= 0:
                continue
            pnl_pct = _parse_num(_row_get(raw, "PNL_PCT", "PNL %", "PNL%"))
            if pnl_pct is None:
                continue
            exit_px = _parse_num(_row_get(raw, "EXIT_PRICE", "EXIT PRICE"))
            stop = _parse_num(
                _row_get(raw, "STOP_PRICE", "STOP PRICE", "ORIGINAL STOP")
            )
            if stop is not None and stop <= 0:
                stop = None
            house_pnl = _parse_num(_row_get(raw, "PNL_DOLLARS", "PNL $", "PNL$"))
            if house_pnl is None:
                house_pnl = (pnl_pct / 100.0) * SHEET_DEFAULT.get(system, 47_500.0)
            days = _parse_num(_row_get(raw, "DAYS_HELD", "DAYS HELD")) or 0.0
            rows.append(
                {
                    "symbol": str(_row_get(raw, "SYMBOL") or "").strip().upper(),
                    "opened": opened,
                    "closed": closed,
                    "entry": float(entry),
                    "exit_px": exit_px,
                    "stop": stop,
                    "pnl_pct": float(pnl_pct),
                    "house_pnl": float(house_pnl),
                    "days": float(days),
                    "exit_type": str(
                        _row_get(raw, "EXIT_TYPE", "EXIT TYPE") or ""
                    ).strip(),
                    "signal": _parse_date(_row_get(raw, "SIGNAL_DATE")),
                    "rsi_trig": _parse_num(_row_get(raw, "RSI14_AT_TRIGGER")),
                    "status": "closed",
                }
            )
    return rows


def load_open_rows(path: Path, system: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for raw in csv.DictReader(f):
            opened = _parse_date(_row_get(raw, "DATE_OPENED", "DATE OPENED"))
            entry = _parse_num(_row_get(raw, "ENTRY_PRICE", "ENTRY PRICE"))
            if opened is None or entry is None or entry <= 0:
                continue
            pnl_pct = _parse_num(_row_get(raw, "PNL_PCT", "PNL %", "PNL%")) or 0.0
            house_pnl = _parse_num(_row_get(raw, "PNL_DOLLARS", "PNL $", "PNL$"))
            if house_pnl is None:
                house_pnl = (pnl_pct / 100.0) * SHEET_DEFAULT.get(system, 47_500.0)
            stop = _parse_num(
                _row_get(raw, "STOP_PRICE", "STOP PRICE", "ORIGINAL STOP")
            )
            if stop is not None and stop <= 0:
                stop = None
            days = _parse_num(_row_get(raw, "DAYS_HELD", "DAYS HELD")) or 0.0
            cur = _parse_num(_row_get(raw, "CURRENT_PRICE", "EXIT_PRICE"))
            rows.append(
                {
                    "symbol": str(_row_get(raw, "SYMBOL") or "").strip().upper(),
                    "opened": opened,
                    "closed": None,
                    "entry": float(entry),
                    "exit_px": cur,
                    "stop": stop,
                    "pnl_pct": float(pnl_pct),
                    "house_pnl": float(house_pnl or 0.0),
                    "days": float(days),
                    "exit_type": "OPEN",
                    "signal": _parse_date(_row_get(raw, "SIGNAL_DATE")),
                    "rsi_trig": _parse_num(_row_get(raw, "RSI14_AT_TRIGGER")),
                    "status": "open",
                }
            )
    return rows


def overlay_one(system: str, raw: dict[str, Any]) -> OverlayTrade:
    stop_raw = raw.get("stop")
    stop_used = stop_raw
    stop_src = "closed_STOP_PRICE" if stop_raw is not None else "missing"
    skip = ""
    if system == "RSI":
        implied, hint = implied_roll8_stop(
            raw["symbol"],
            signal=raw.get("signal"),
            opened=raw["opened"],
            rsi_at_trigger=raw.get("rsi_trig"),
        )
        stop_used = implied
        stop_src = f"rsi_roll8_implied:{hint}"
        if implied is None:
            skip = hint
    shares, invested, sized, why = size_from_stop(raw["entry"], stop_used)
    if not sized:
        skip = skip or why
    overlay_pnl = (raw["pnl_pct"] / 100.0) * invested if sized else 0.0
    house_n = _house_notional(
        raw["house_pnl"], raw["pnl_pct"], SHEET_DEFAULT.get(system, 47_500.0)
    )
    return OverlayTrade(
        system=system,
        symbol=raw["symbol"],
        opened=raw["opened"],
        closed=raw.get("closed"),
        entry=raw["entry"],
        exit_px=raw.get("exit_px"),
        stop_raw=stop_raw,
        stop_used=stop_used,
        stop_src=stop_src,
        exit_type=raw.get("exit_type") or "",
        days=float(raw.get("days") or 0.0),
        pnl_pct=float(raw["pnl_pct"]),
        house_pnl=float(raw["house_pnl"]),
        house_notional=house_n,
        shares=shares,
        invested=invested,
        overlay_pnl=overlay_pnl,
        sized=sized,
        skip_reason=skip,
        status=raw.get("status") or "closed",
        signal_date=raw.get("signal"),
    )


def avg_loss_pct_points(
    rows: list[dict[str, Any]],
    *,
    is_only: bool,
) -> tuple[Optional[float], int]:
    """Mean |PNL_PCT| of losing fills, as percent points (e.g. 8.5 = 8.5%)."""
    losses: list[float] = []
    for r in rows:
        opened = r.get("opened")
        pnl = r.get("pnl_pct")
        if opened is None or pnl is None:
            continue
        if is_only and opened >= IS_CUT:
            continue
        if float(pnl) < 0:
            losses.append(-float(pnl))
    if not losses:
        return None, 0
    return sum(losses) / len(losses), len(losses)


def avgloss_slot(avg_loss_pct_points_v: Optional[float]) -> Optional[float]:
    """invested = $2,500 / |avg_loss as fraction|. None if avg loss missing/0."""
    if avg_loss_pct_points_v is None or avg_loss_pct_points_v <= 0:
        return None
    frac = float(avg_loss_pct_points_v) / 100.0
    slot = RISK_DOLLARS / frac
    if not math.isfinite(slot) or slot <= 0:
        return None
    return slot


def apply_equal_slot(t: OverlayTrade, slot: float, *, src: str) -> OverlayTrade:
    """Same dollar slot on every fill (RSI avg-loss stand-in)."""
    if t.entry <= 0 or not math.isfinite(t.entry):
        return OverlayTrade(
            **{**t.__dict__, "sized": False, "skip_reason": "bad_entry", "stop_src": src}
        )
    shares = slot / t.entry
    invested = float(slot)
    overlay_pnl = (t.pnl_pct / 100.0) * invested
    return OverlayTrade(
        **{
            **t.__dict__,
            "shares": shares,
            "invested": invested,
            "overlay_pnl": overlay_pnl,
            "sized": True,
            "skip_reason": "",
            "stop_used": None,
            "stop_src": src,
        }
    )


def slice_trades(trades: list[OverlayTrade], which: str) -> list[OverlayTrade]:
    if which == "IS":
        return [t for t in trades if t.opened < IS_CUT]
    if which == "OOS":
        return [t for t in trades if t.opened >= IS_CUT]
    return list(trades)


def _losing_streak(pnls: list[float]) -> int:
    worst = cur = 0
    for p in pnls:
        if p < 0:
            cur += 1
            if cur > worst:
                worst = cur
        else:
            cur = 0
    return worst


def _peak_concurrent(trades: list[OverlayTrade]) -> tuple[float, float, int]:
    """Return (peak_notional, avg_open, max_open) on overlay invested."""
    events: list[tuple[date, int, float]] = []
    for t in trades:
        if not t.sized:
            continue
        opened = t.opened
        closed = t.closed or t.opened
        if closed < opened:
            closed = opened
        events.append((opened, 1, t.invested))
        events.append((closed, -1, -t.invested))
    if not events:
        return 0.0, 0.0, 0
    events.sort(key=lambda x: (x[0], -x[1]))
    cur_n = 0
    cur_dol = 0.0
    peak_n = 0
    peak_dol = 0.0
    samples_n: list[int] = []
    last_d: Optional[date] = None
    for d, dn, ddol in events:
        if last_d is not None and d != last_d and cur_n > 0:
            samples_n.append(cur_n)
        cur_n += dn
        cur_dol += ddol
        if cur_n > peak_n:
            peak_n = cur_n
        if cur_dol > peak_dol:
            peak_dol = cur_dol
        last_d = d
    avg_n = (sum(samples_n) / len(samples_n)) if samples_n else float(peak_n)
    return peak_dol, avg_n, peak_n


def book_stats(
    trades: list[OverlayTrade],
    *,
    use_overlay: bool,
    cash_ann: float,
    dd_seed: float,
) -> dict[str, Any]:
    book = [t for t in trades if t.status == "closed"]
    if use_overlay:
        book = [t for t in book if t.sized]
        dollars = [t.overlay_pnl for t in book]
        notionals = [t.invested for t in book]
    else:
        dollars = [t.house_pnl for t in book]
        notionals = [t.house_notional for t in book]
    n = len(book)
    empty = {
        "n": 0,
        "n_sized": 0,
        "n_na": 0,
        "wins": 0,
        "losses": 0,
        "win_pct": None,
        "avg_pnl_pct": None,
        "avg_wo_max": None,
        "expectancy_pct": None,
        "expectancy_dol": None,
        "avg_win_pct": None,
        "avg_loss_pct": None,
        "wl_count": None,
        "wl_dol": None,
        "pf": None,
        "ann_ror": None,
        "ann_ror_250k": None,
        "ann_ror_500k": None,
        "ann_ror_600k": None,
        "max_dd": None,
        "calmar": None,
        "sharpe": None,
        "profit_per_cap_day": None,
        "capital_days": 0.0,
        "avg_days": None,
        "median_days": None,
        "p90_days": None,
        "mean_notional": None,
        "peak_notional": None,
        "avg_pos": None,
        "max_pos": None,
        "losing_streak": None,
        "total_pnl": 0.0,
        "exits": {},
        "n_tiny_stop": 0,
    }
    if n == 0:
        empty["n_na"] = sum(1 for t in trades if t.status == "closed" and not t.sized)
        return empty
    wins = [t for t in book if t.pnl_pct > 0]
    losses = [t for t in book if t.pnl_pct < 0]
    pcts = [t.pnl_pct for t in book]
    avg = sum(pcts) / n
    wo = sorted(pcts)
    avg_wo = (sum(wo[:-1]) / (n - 1)) if n > 1 else avg
    win_pcts = [t.pnl_pct for t in wins]
    loss_pcts = [t.pnl_pct for t in losses]
    avg_w = (sum(win_pcts) / len(win_pcts)) if win_pcts else 0.0
    avg_l = (sum(loss_pcts) / len(loss_pcts)) if loss_pcts else 0.0
    days = [t.days for t in book if t.days > 0]
    avg_days = (sum(days) / len(days)) if days else 0.0
    med_days = sorted(days)[len(days) // 2] if days else 0.0
    p90_days = sorted(days)[int(0.9 * (len(days) - 1))] if days else 0.0
    overlay_rows = []
    for t, pdol in zip(book, dollars):
        overlay_rows.append(
            {
                "pnl": t.pnl_pct,
                "pnl_d": pdol,
                "days": t.days,
                "closed": t.closed,
                "opened": t.opened,
            }
        )
    ov = overlay_ann_ror_max_dd(
        overlay_rows, cash=float(cash_ann), initial_account=float(dd_seed)
    )
    sum_w = sum(x for x in dollars if x > 0)
    sum_l = abs(sum(x for x in dollars if x < 0))
    pf = (sum_w / sum_l) if sum_l > 0 else (sum_w if sum_w > 0 else 0.0)
    wl_dol = (sum_w / len(wins) / (sum_l / len(losses))) if wins and losses and sum_l else None
    wl_c = (len(wins) / len(losses)) if losses else (float(len(wins)) if wins else None)
    total_pnl = float(ov.get("pnl_d") or sum(dollars))
    cap_days = float(ov.get("capital_days") or sum(days))
    ppc = (total_pnl / cap_days) if cap_days else None
    mean_not = (sum(notionals) / n) if n else None
    if use_overlay:
        peak_dol, avg_pos, max_pos = _peak_concurrent(book)
    else:
        fake = [
            OverlayTrade(
                **{
                    **t.__dict__,
                    "invested": t.house_notional,
                    "sized": True,
                }
            )
            for t in book
        ]
        peak_dol, avg_pos, max_pos = _peak_concurrent(fake)
    n_tiny = 0
    if use_overlay:
        for t in book:
            if t.stop_used and t.entry > 0:
                rp = (t.entry - t.stop_used) / t.entry
                if 0 < rp < 0.002:
                    n_tiny += 1
    ann_250 = (
        ann_ror_from_closed(
            total_pnl=total_pnl, n_trades=n, avg_days_held=avg_days, brt_cash=ACCOUNT
        )
        if avg_days > 0
        else None
    )
    ann_500 = (
        ann_ror_from_closed(
            total_pnl=total_pnl,
            n_trades=n,
            avg_days_held=avg_days,
            brt_cash=ACCOUNT_500K,
        )
        if avg_days > 0
        else None
    )
    ann_600 = (
        ann_ror_from_closed(
            total_pnl=total_pnl,
            n_trades=n,
            avg_days_held=avg_days,
            brt_cash=ACCOUNT_600K,
        )
        if avg_days > 0
        else None
    )
    n_all_closed = sum(1 for t in trades if t.status == "closed")
    n_na = n_all_closed - n if use_overlay else 0
    return {
        "n": n,
        "n_sized": n if use_overlay else n_all_closed,
        "n_na": n_na,
        "wins": len(wins),
        "losses": len(losses),
        "win_pct": 100.0 * len(wins) / n,
        "avg_pnl_pct": avg,
        "avg_wo_max": avg_wo,
        "expectancy_pct": avg,
        "expectancy_dol": total_pnl / n,
        "avg_win_pct": avg_w,
        "avg_loss_pct": avg_l,
        "wl_count": wl_c,
        "wl_dol": wl_dol,
        "pf": pf,
        "ann_ror": ov.get("ann_ror"),
        "ann_ror_250k": ann_250,
        "ann_ror_500k": ann_500,
        "ann_ror_600k": ann_600,
        "max_dd": ov.get("max_dd"),
        "calmar": ov.get("calmar"),
        "sharpe": ov.get("sharpe"),
        "profit_per_cap_day": ppc,
        "capital_days": cap_days,
        "avg_days": avg_days,
        "median_days": med_days,
        "p90_days": p90_days,
        "mean_notional": mean_not,
        "peak_notional": peak_dol,
        "avg_pos": avg_pos,
        "max_pos": max_pos,
        "losing_streak": _losing_streak(dollars),
        "total_pnl": total_pnl,
        "exits": dict(Counter((t.exit_type or "?").upper() for t in book)),
        "n_tiny_stop": n_tiny,
    }


def _fmt_pct(v: Any) -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "—"
    return f"{float(v):.2f}%"


def _fmt_num(v: Any, d: int = 2) -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "—"
    return f"{float(v):,.{d}f}"


def _delta(a: Any, b: Any) -> Optional[float]:
    if a is None or b is None:
        return None
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(fa) or not math.isfinite(fb):
        return None
    return fa - fb


def _verdict(ctrl: dict[str, Any], cand: dict[str, Any]) -> str:
    """Size view Paul asked to see. Default HOLD. Do not adopt to DailyRun."""
    if not cand.get("n"):
        return "HOLD — overlay N=0 (cannot size)"
    peak = cand.get("peak_notional") or 0.0
    if peak > ACCOUNT * 20:
        return "HOLD — research size view; peak notional dwarfs the $250k account"
    dd_d = _delta(cand.get("max_dd"), ctrl.get("max_dd"))
    pf_d = _delta(cand.get("pf"), ctrl.get("pf"))
    if dd_d is not None and dd_d <= -1.0 and pf_d is not None and pf_d >= 0:
        return "HOLD — quality mix not worse; still a size view, not DailyRun"
    return "HOLD — research size overlay (Paul specified $2,500; not an adopt)"


def _verdict_rsi_avgloss(ctrl: dict[str, Any], roll8: dict[str, Any], avgloss: dict[str, Any]) -> str:
    """RSI 1% stand-in: avg-loss slot vs house $10k and vs roll-8 invert."""
    if not avgloss.get("n"):
        return "HOLD — avg-loss slot N=0"
    dd_a = avgloss.get("max_dd")
    dd_r = roll8.get("max_dd")
    pf_a = avgloss.get("pf")
    pf_c = ctrl.get("pf")
    peak_a = avgloss.get("peak_notional") or 0.0
    peak_r = roll8.get("peak_notional") or 0.0
    # Equal slot vs house: PF $ should nearly match (same mix). Judge DD / peak.
    if dd_r is not None and dd_a is not None and float(dd_a) + 5.0 < float(dd_r):
        if pf_c is not None and pf_a is not None and abs(float(pf_a) - float(pf_c)) < 0.15:
            if peak_a < peak_r * 0.5:
                return (
                    "LEAN KEEP (research) as the RSI 1% stand-in vs roll-8 invert — "
                    "same mix as house, no fake-stop size bombs. HOLD vs DailyRun $10k "
                    "(slot change, not an edge). Not gold."
                )
    if peak_a > ACCOUNT * 8:
        return "HOLD — avg-loss slot still large vs a $250k account"
    return (
        "HOLD — avg-loss is a cleaner RSI 1% stand-in than roll-8 invert; "
        "equal-slot vs $10k is a size choice, not KEEP. Not DailyRun."
    )


def load_overlay_csv(path: Path) -> list[OverlayTrade]:
    """Reload a stamp overlay CSV (risk2500 or RSI avg-loss)."""
    trades: list[OverlayTrade] = []
    if not path.is_file():
        return trades
    with path.open(encoding="utf-8-sig", newline="") as f:
        for raw in csv.DictReader(f):
            opened = _parse_date(raw.get("DATE_OPENED"))
            entry = _parse_num(raw.get("ENTRY_PRICE"))
            if opened is None or entry is None or entry <= 0:
                continue
            sized = str(raw.get("SIZED") or "").strip().upper() == "Y"
            trades.append(
                OverlayTrade(
                    system=str(raw.get("SYSTEM") or "").strip().upper(),
                    symbol=str(raw.get("SYMBOL") or "").strip().upper(),
                    opened=opened,
                    closed=_parse_date(raw.get("DATE_CLOSED")),
                    entry=float(entry),
                    exit_px=_parse_num(raw.get("EXIT_PRICE")),
                    stop_raw=_parse_num(raw.get("STOP_PRICE_CLOSED")),
                    stop_used=_parse_num(raw.get("STOP_USED")),
                    stop_src=str(raw.get("STOP_SOURCE") or ""),
                    exit_type=str(raw.get("EXIT_TYPE") or ""),
                    days=float(_parse_num(raw.get("DAYS_HELD")) or 0.0),
                    pnl_pct=float(_parse_num(raw.get("PNL_PCT")) or 0.0),
                    house_pnl=float(_parse_num(raw.get("PNL_DOLLARS_HOUSE")) or 0.0),
                    house_notional=float(
                        _parse_num(raw.get("HOUSE_NOTIONAL"))
                        or SHEET_DEFAULT.get(
                            str(raw.get("SYSTEM") or "").strip().upper(), 47_500.0
                        )
                    ),
                    shares=float(_parse_num(raw.get("SHARES")) or 0.0),
                    invested=float(_parse_num(raw.get("DOLLARS_INVESTED")) or 0.0),
                    overlay_pnl=float(_parse_num(raw.get("PNL_DOLLARS_RISK2500")) or 0.0),
                    sized=sized,
                    skip_reason=str(raw.get("SKIP_REASON") or ""),
                    status=str(raw.get("STATUS") or "closed").strip().lower() or "closed",
                    signal_date=_parse_date(raw.get("SIGNAL_DATE")),
                )
            )
    return trades


def write_overlay_csv(trades: list[OverlayTrade], path: Path) -> None:
    cols = [
        "SYSTEM",
        "SYMBOL",
        "DATE_OPENED",
        "DATE_CLOSED",
        "SIGNAL_DATE",
        "ENTRY_PRICE",
        "EXIT_PRICE",
        "STOP_PRICE_CLOSED",
        "STOP_USED",
        "STOP_SOURCE",
        "SHARES",
        "DOLLARS_INVESTED",
        "PNL_PCT",
        "PNL_DOLLARS_HOUSE",
        "PNL_DOLLARS_RISK2500",
        "HOUSE_NOTIONAL",
        "EXIT_TYPE",
        "DAYS_HELD",
        "SIZED",
        "SKIP_REASON",
        "STATUS",
        "RISK_DOLLAR",
        "EQUITY_BOM",
        "CASH_BEFORE",
        "DESIRED_INVESTED",
        "SCALED",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for t in trades:
            w.writerow(
                {
                    "SYSTEM": t.system,
                    "SYMBOL": t.symbol,
                    "DATE_OPENED": t.opened.isoformat(),
                    "DATE_CLOSED": t.closed.isoformat() if t.closed else "",
                    "SIGNAL_DATE": t.signal_date.isoformat() if t.signal_date else "",
                    "ENTRY_PRICE": f"{t.entry:.6f}",
                    "EXIT_PRICE": f"{t.exit_px:.6f}" if t.exit_px is not None else "",
                    "STOP_PRICE_CLOSED": f"{t.stop_raw:.6f}" if t.stop_raw is not None else "",
                    "STOP_USED": f"{t.stop_used:.6f}" if t.stop_used is not None else "",
                    "STOP_SOURCE": t.stop_src,
                    "SHARES": f"{t.shares:.6f}" if t.sized else "",
                    "DOLLARS_INVESTED": f"{t.invested:.4f}" if t.sized else "",
                    "PNL_PCT": f"{t.pnl_pct:.6f}",
                    "PNL_DOLLARS_HOUSE": f"{t.house_pnl:.4f}",
                    "PNL_DOLLARS_RISK2500": f"{t.overlay_pnl:.4f}" if t.sized else "",
                    "HOUSE_NOTIONAL": f"{t.house_notional:.4f}",
                    "EXIT_TYPE": t.exit_type,
                    "DAYS_HELD": f"{t.days:.2f}",
                    "SIZED": "Y" if t.sized else "N",
                    "SKIP_REASON": t.skip_reason,
                    "STATUS": t.status,
                    "RISK_DOLLAR": f"{t.risk_dollar:.4f}" if t.risk_dollar is not None else "",
                    "EQUITY_BOM": f"{t.equity_bom:.4f}" if t.equity_bom is not None else "",
                    "CASH_BEFORE": f"{t.cash_before:.4f}" if t.cash_before is not None else "",
                    "DESIRED_INVESTED": (
                        f"{t.desired_invested:.4f}" if t.desired_invested is not None else ""
                    ),
                    "SCALED": "Y" if t.scaled else "N",
                }
            )


def _sortable_th(label: str, sort_type: str) -> str:
    return monthly._sortable_th(label, sort_type)


def _pnl_class(v: float) -> str:
    return monthly._pnl_class(v)


def _fmt_money_signed(v: float) -> str:
    return monthly._fmt_money(v)


def _symbol_link(symbol: str) -> str:
    return monthly._symbol_link(symbol)


def _metric_cell(label: str, ctrl: Any, cand: Any, *, money: bool = False, pct: bool = False) -> str:
    if is_excluded_html_compare_label(label):
        return ""
    if money:
        c_s = format_money(ctrl)
        a_s = format_money(cand)
        d = _delta(cand, ctrl)
        d_s = format_money_delta(d) if d is not None else "—"
    elif pct:
        c_s = _fmt_pct(ctrl)
        a_s = _fmt_pct(cand)
        d = _delta(cand, ctrl)
        d_s = f"{d:+.2f} pp" if d is not None else "—"
    else:
        c_s = _fmt_num(ctrl)
        a_s = _fmt_num(cand)
        d = _delta(cand, ctrl)
        d_s = f"{d:+.2f}" if d is not None else "—"
    return (
        f"<tr><td>{html_mod.escape(label)}</td>"
        f"<td>{c_s}</td><td>{a_s}</td><td>{d_s}</td></tr>"
    )


def _fmt_kind(v: Any, kind: str) -> str:
    if kind == "money":
        return format_money(v)
    if kind == "pct":
        return _fmt_pct(v)
    return _fmt_num(v)


def _delta_kind(a: Any, b: Any, kind: str) -> str:
    d = _delta(a, b)
    if d is None:
        return "—"
    if kind == "money":
        return format_money_delta(d)
    if kind == "pct":
        return f"{d:+.2f} pp"
    return f"{d:+.2f}"


CANONICAL_METRIC_ROWS = [
    ("Total trades", "n", "num"),
    ("Wins", "wins", "num"),
    ("Losses", "losses", "num"),
    ("Win %", "win_pct", "pct"),
    ("Avg PnL %", "avg_pnl_pct", "pct"),
    ("Book AVG_PNL_PCT_WO_MAX", "avg_wo_max", "pct"),
    ("Expectancy $", "expectancy_dol", "money"),
    ("Expectancy %", "expectancy_pct", "pct"),
    ("Avg win %", "avg_win_pct", "pct"),
    ("Avg loss %", "avg_loss_pct", "pct"),
    ("Win/Loss ratio (count)", "wl_count", "num"),
    ("Win/Loss ratio $", "wl_dol", "num"),
    ("Profit factor", "pf", "num"),
    ("Ann ROR % ($250k)", "ann_ror_250k", "pct"),
    ("Ann ROR % (slot / mean $)", "ann_ror", "pct"),
    ("Ann ROR % ($500k secondary)", "ann_ror_500k", "pct"),
    ("Ann ROR % ($600k secondary)", "ann_ror_600k", "pct"),
    ("Max DD %", "max_dd", "pct"),
    ("Calmar", "calmar", "num"),
    ("Sharpe", "sharpe", "num"),
    ("Profit per capital day", "profit_per_cap_day", "money"),
    ("Capital days", "capital_days", "num"),
    ("Avg days held", "avg_days", "num"),
    ("Median days held", "median_days", "num"),
    ("P90 days held", "p90_days", "num"),
    ("Mean notional", "mean_notional", "money"),
    ("Peak notional", "peak_notional", "money"),
    ("Avg positions", "avg_pos", "num"),
    ("Max positions", "max_pos", "num"),
    ("Losing streak", "losing_streak", "num"),
    ("N cannot size", "n_na", "num"),
    ("N tiny stop (<0.20%)", "n_tiny_stop", "num"),
]


def _three_arm_table(
    ctrl: dict[str, Any],
    roll8: dict[str, Any],
    avgloss: dict[str, Any],
) -> str:
    body = ""
    for label, key, kind in CANONICAL_METRIC_ROWS:
        if is_excluded_html_compare_label(label):
            continue
        c, r, a = ctrl.get(key), roll8.get(key), avgloss.get(key)
        body += (
            f"<tr><td>{html_mod.escape(label)}</td>"
            f"<td>{_fmt_kind(c, kind)}</td>"
            f"<td>{_fmt_kind(r, kind)}</td>"
            f"<td>{_fmt_kind(a, kind)}</td>"
            f"<td>{_delta_kind(a, c, kind)}</td>"
            f"<td>{_delta_kind(a, r, kind)}</td></tr>"
        )
    head = "".join(
        _sortable_th(h, t)
        for h, t in (
            ("Metric", "text"),
            ("House dummy $10k", "text"),
            ("Roll-8 invert $2500-to-synthetic-stop", "text"),
            ("Avg-loss slot (IS freeze)", "text"),
            ("Δ avg-loss − house", "text"),
            ("Δ avg-loss − roll-8", "text"),
        )
    )
    return (
        f'<table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table>"
    )


def build_rsi_avgloss_html(
    *,
    rsi_pack: dict[str, Any],
    avgloss_meta: dict[str, Any],
    sources: list[str],
) -> str:
    tables = rsi_pack["tables"]
    verdict = avgloss_meta.get("verdict") or "HOLD"
    is_loss = avgloss_meta.get("is_avg_loss_pct")
    full_loss = avgloss_meta.get("full_avg_loss_pct")
    slot = avgloss_meta.get("slot")
    n_is_losers = avgloss_meta.get("n_is_losers")
    n_full_losers = avgloss_meta.get("n_full_losers")
    sections = []
    for sl, note in (
        ("IS", "In-Sample — size number was fit here; do not retune on OOS"),
        ("OOS", "Out-of-Sample — report-only"),
        ("FULL", verdict),
    ):
        body = _three_arm_table(
            tables[sl]["CONTROL"],
            tables[sl]["SIZE_risk2500"],
            tables[sl]["SIZE_rsi_avgloss"],
        )
        sections.append(
            f"<section><h2>Relative Strength Index (RSI) · {sl}</h2>"
            f"<p class=\"small\">{html_mod.escape(note)}</p>"
            f"<div class=\"table-wrap\">{body}</div></section>"
        )
    sources_html = "".join(f"<li>{html_mod.escape(s)}</li>" for s in sources if s.startswith("RSI"))
    slot_s = format_money(slot) if slot else "—"
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>RSI size: roll-8 invert vs avg-loss slot — {STAMP}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin:24px; color:#0f172a; }}
h1 {{ font-size:1.45rem; margin-bottom:4px; }}
h2 {{ font-size:1.1rem; margin-top:28px; }}
.sub, .small {{ color:#64748b; font-size:13px; line-height:1.5; }}
.ask {{ background:#fff7ed; border:1px solid #fdba74; border-radius:10px; padding:14px 16px; margin:16px 0 24px; }}
.ask h2 {{ margin-top:12px; font-size:1rem; }}
.ask h2:first-child {{ margin-top:0; }}
blockquote {{ margin:8px 0 12px; color:#9a3412; }}
.hold {{ background:#eef2ff; border:1px solid #c7d2fe; border-radius:10px; padding:12px 14px; margin:12px 0; }}
.warn {{ background:#fef2f2; border:1px solid #fecaca; border-radius:10px; padding:12px 14px; margin:12px 0; }}
.table-wrap {{ margin:8px 0; }}
table.sortable {{ border-collapse:collapse; font-size:12px; width:100%; }}
th, td {{ border:1px solid #e2e8f0; padding:6px 8px; text-align:left; vertical-align:top; }}
th {{ background:#f1f5f9; }}
th.sortable-th {{ cursor:pointer; user-select:none; white-space:normal; }}
th.sortable-th:hover {{ background:#e2e8f0; }}
.sort-ind {{ display:inline-block; width:0.9em; margin-left:4px; color:#94a3b8; font-size:10px; }}
th.sort-asc .sort-ind::after {{ content:"▲"; color:#334155; }}
th.sort-desc .sort-ind::after {{ content:"▼"; color:#334155; }}
code {{ background:#f1f5f9; padding:1px 4px; border-radius:4px; }}
{TABLE_UNCAP_CSS}
</style></head><body>
<h1>Relative Strength Index (RSI) sizing — how the stop was calculated, and the avg-loss alternative</h1>
<p class="sub">Stamp <code>{STAMP}</code> · research only · <strong>not gold · not DailyRun</strong>.
In-Sample (IS) = entry_date &lt; 2024-01-01. Out-of-Sample (OOS) report-only.
Click column headers to sort. Other DailyRun systems still use true $2,500 / (entry − stop).</p>
<div class="ask">
<h2>What you asked</h2>
<blockquote>{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
<blockquote>{html_mod.escape(FOLLOWUP_REQUEST)}</blockquote>
<h2>In plain English</h2>
<p>{html_mod.escape(FOLLOWUP_PLAIN)}</p>
</div>
<div class="warn">
<strong>How we calculated the RSI “stop” today (roll-8 invert) — do not hide this.</strong>
<p>House RSI Closed has <code>STOP_PRICE=0</code>. There is no live price stop. The first
overlay invented one: from the fill / signal bar’s Wilder RSI(14) state, find the
<strong>close that would print RSI ≤ (RSI at entry − 8)</strong> — the same what-if close
<code>getTarget.py</code> shows for the roll-8 exit. Then
<code>shares = $2,500 / (entry − that_close)</code>.</p>
<p>That gap is often tiny (a small drop can move RSI 8 points). Tiny gap → huge shares.
That is why RSI peak notional went to about <strong>$3.1 million</strong> and Maximum
Drawdown to about <strong>37%</strong> on a $250k seed. It is a synthetic stop, not a
house stop. We are not re-shopping it. Average True Range (ATR) % is not used.</p>
</div>
<div class="hold">
<strong>Paul’s alternative (frozen):</strong> IS-only mean |loss| of losing RSI fills =
<strong>{_fmt_pct(is_loss)}</strong> ({n_is_losers} IS losers).
Full-book avg loss (note only, not the freeze) = {_fmt_pct(full_loss)} ({n_full_losers} losers).
Slot = $2,500 / |IS avg loss as a fraction| = <strong>{slot_s}</strong> on every RSI name.
Same dollars for winners and losers. A typical IS loser ≈ $2,500 by construction.
Actual $ on one trade still varies with that trade’s PnL%.</div>
<div class="hold"><strong>Verdict:</strong> {html_mod.escape(verdict)}</div>
{''.join(sections)}
<section>
<h2>Data</h2>
<ul>{sources_html}</ul>
<p class="small">Also: <a href="monthly.html">monthly.html</a> (RSI = IS avg-loss slot; not roll-8) ·
<a href="compare.html">compare.html</a> (all systems). Acronyms: Relative Strength Index (RSI);
In-Sample (IS); Out-of-Sample (OOS); Annualized Rate of Return (Ann ROR);
Maximum Drawdown (Max DD); Profit Factor (PF); Average True Range (ATR).</p>
</section>
{monthly._SORTABLE_TABLE_SCRIPT}
</body></html>"""


def build_compare_html(
    per_sys: dict[str, dict[str, Any]],
    sources: list[str],
) -> str:
    metric_rows = [
        ("Total trades", "n", "num"),
        ("Wins", "wins", "num"),
        ("Losses", "losses", "num"),
        ("Win %", "win_pct", "pct"),
        ("Avg PnL %", "avg_pnl_pct", "pct"),
        ("Book AVG_PNL_PCT_WO_MAX", "avg_wo_max", "pct"),
        ("Expectancy $", "expectancy_dol", "money"),
        ("Expectancy %", "expectancy_pct", "pct"),
        ("Avg win %", "avg_win_pct", "pct"),
        ("Avg loss %", "avg_loss_pct", "pct"),
        ("Win/Loss ratio (count)", "wl_count", "num"),
        ("Win/Loss ratio $", "wl_dol", "num"),
        ("Profit factor", "pf", "num"),
        ("Ann ROR % ($250k)", "ann_ror_250k", "pct"),
        ("Ann ROR % (slot / mean $)", "ann_ror", "pct"),
        ("Ann ROR % ($500k secondary)", "ann_ror_500k", "pct"),
        ("Ann ROR % ($600k secondary)", "ann_ror_600k", "pct"),
        ("Max DD %", "max_dd", "pct"),
        ("Calmar", "calmar", "num"),
        ("Sharpe", "sharpe", "num"),
        ("Profit per capital day", "profit_per_cap_day", "money"),
        ("Capital days", "capital_days", "num"),
        ("Avg days held", "avg_days", "num"),
        ("Median days held", "median_days", "num"),
        ("P90 days held", "p90_days", "num"),
        ("Mean notional", "mean_notional", "money"),
        ("Peak notional", "peak_notional", "money"),
        ("Avg positions", "avg_pos", "num"),
        ("Max positions", "max_pos", "num"),
        ("Losing streak", "losing_streak", "num"),
        ("N cannot size", "n_na", "num"),
        ("N tiny stop (<0.20%)", "n_tiny_stop", "num"),
    ]
    sections = []
    summary_body = ""
    for sys in SYSTEMS:
        pack = per_sys[sys]
        expand = SYSTEM_EXPAND.get(sys, sys)
        for sl in ("IS", "OOS", "FULL"):
            ctrl = pack["tables"][sl]["CONTROL"]
            cand = pack["tables"][sl]["SIZE_risk2500"]
            avgloss = pack["tables"][sl].get("SIZE_rsi_avgloss")
            note = pack["tables"][sl]["verdict"] if sl == "FULL" else (
                "report-only" if sl == "OOS" else "IS only — do not retune OOS"
            )
            if sys == "RSI" and avgloss is not None:
                if sl == "FULL":
                    note = pack.get("avgloss_meta", {}).get("verdict") or note
                sections.append(
                    f"<section><h2>{html_mod.escape(expand)} · {sl} · three RSI size arms</h2>"
                    f"<p class=\"small\">{html_mod.escape(note)} · pin {html_mod.escape(pack['pin'])} · "
                    f"<a href=\"rsi_avgloss.html\">rsi_avgloss.html</a></p>"
                    f"<div class=\"table-wrap\">{_three_arm_table(ctrl, cand, avgloss)}</div></section>"
                )
                continue
            body = ""
            for label, key, kind in metric_rows:
                if is_excluded_html_compare_label(label):
                    continue
                body += _metric_cell(
                    label,
                    ctrl.get(key),
                    cand.get(key),
                    money=(kind == "money"),
                    pct=(kind == "pct"),
                )
            exits_c = ctrl.get("exits") or {}
            exits_a = cand.get("exits") or {}
            keys = sorted(set(exits_c) | set(exits_a))
            for et in keys:
                nc = exits_c.get(et, 0)
                na = exits_a.get(et, 0)
                n_ctrl = ctrl.get("n") or 0
                n_cand = cand.get("n") or 0
                pc = (100.0 * nc / n_ctrl) if n_ctrl else 0.0
                pa = (100.0 * na / n_cand) if n_cand else 0.0
                body += (
                    f"<tr><td>Exit {html_mod.escape(et)} count / %</td>"
                    f"<td>{nc} ({pc:.1f}%)</td><td>{na} ({pa:.1f}%)</td>"
                    f"<td>{na - nc:+d}</td></tr>"
                )
            head = "".join(
                _sortable_th(h, t)
                for h, t in (
                    ("Metric", "text"),
                    ("CONTROL house dummy $", "text"),
                    ("SIZE_risk2500 ($2,500 to stop)", "text"),
                    ("Δ (overlay − house)", "text"),
                )
            )
            sections.append(
                f"<section><h2>{html_mod.escape(expand)} · {sl}</h2>"
                f"<p class=\"small\">{html_mod.escape(note)} · pin {html_mod.escape(pack['pin'])}</p>"
                f"<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>{head}</tr></thead>"
                f"<tbody>{body}</tbody></table></div></section>"
            )
        c = pack["tables"]["FULL"]["CONTROL"]
        a = pack["tables"]["FULL"]["SIZE_risk2500"]
        summary_body += (
            "<tr>"
            f"<td>{html_mod.escape(expand)}</td>"
            f"<td>{c.get('n') or 0}</td><td>{a.get('n') or 0}</td>"
            f"<td>{_fmt_pct(c.get('win_pct'))}</td><td>{_fmt_pct(a.get('win_pct'))}</td>"
            f"<td>{_fmt_pct(c.get('avg_pnl_pct'))}</td><td>{_fmt_pct(a.get('avg_pnl_pct'))}</td>"
            f"<td>{_fmt_num(c.get('pf'))}</td><td>{_fmt_num(a.get('pf'))}</td>"
            f"<td>{_fmt_pct(c.get('ann_ror_250k'))}</td><td>{_fmt_pct(a.get('ann_ror_250k'))}</td>"
            f"<td>{_fmt_pct(c.get('max_dd'))}</td><td>{_fmt_pct(a.get('max_dd'))}</td>"
            f"<td>{_fmt_num(c.get('calmar'))}</td><td>{_fmt_num(a.get('calmar'))}</td>"
            f"<td>{_fmt_num(c.get('sharpe'))}</td><td>{_fmt_num(a.get('sharpe'))}</td>"
            f"<td>{format_money(c.get('mean_notional'))}</td>"
            f"<td>{format_money(a.get('mean_notional'))}</td>"
            f"<td>{format_money(a.get('peak_notional'))}</td>"
            f"<td>{html_mod.escape(pack['tables']['FULL']['verdict'])}</td>"
            "</tr>"
        )
    sum_head = "".join(
        _sortable_th(h, t)
        for h, t in (
            ("System", "text"),
            ("N house", "num"),
            ("N overlay", "num"),
            ("WR house", "num"),
            ("WR overlay", "num"),
            ("Avg% house", "num"),
            ("Avg% overlay", "num"),
            ("PF house", "num"),
            ("PF overlay", "num"),
            ("Ann ROR $250k house", "num"),
            ("Ann ROR $250k overlay", "num"),
            ("Max DD house", "num"),
            ("Max DD overlay", "num"),
            ("Calmar house", "num"),
            ("Calmar overlay", "num"),
            ("Sharpe house", "num"),
            ("Sharpe overlay", "num"),
            ("Mean $ house", "num"),
            ("Mean $ overlay", "num"),
            ("Peak $ overlay", "num"),
            ("Note", "text"),
        )
    )
    sources_html = "".join(f"<li>{html_mod.escape(s)}</li>" for s in sources)
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>$2,500 risk-to-stop vs house dummy — {STAMP}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin:24px; color:#0f172a; }}
h1 {{ font-size:1.45rem; margin-bottom:4px; }}
h2 {{ font-size:1.1rem; margin-top:28px; }}
.sub, .small {{ color:#64748b; font-size:13px; line-height:1.5; }}
.ask {{ background:#fff7ed; border:1px solid #fdba74; border-radius:10px; padding:14px 16px; margin:16px 0 24px; }}
.ask h2 {{ margin-top:0; }}
blockquote {{ margin:8px 0; color:#9a3412; }}
.hold {{ background:#eef2ff; border:1px solid #c7d2fe; border-radius:10px; padding:12px 14px; }}
.table-wrap {{ margin:8px 0; }}
table.sortable {{ border-collapse:collapse; font-size:12px; width:100%; }}
th, td {{ border:1px solid #e2e8f0; padding:6px 8px; text-align:left; vertical-align:top; }}
th {{ background:#f1f5f9; }}
th.sortable-th {{ cursor:pointer; user-select:none; white-space:normal; }}
th.sortable-th:hover {{ background:#e2e8f0; }}
.sort-ind {{ display:inline-block; width:0.9em; margin-left:4px; color:#94a3b8; font-size:10px; }}
th.sort-asc .sort-ind::after {{ content:"▲"; color:#334155; }}
th.sort-desc .sort-ind::after {{ content:"▼"; color:#334155; }}
.pos {{ color:#16a34a; }} .neg {{ color:#dc2626; }}
{TABLE_UNCAP_CSS}
</style></head><body>
<h1>$2,500 risk-to-stop vs house dummy notionals</h1>
<p class="sub">Stamp <code>{STAMP}</code> · as-of {ASOF.isoformat()} · research overlay ·
<strong>not gold · not DailyRun</strong>. In-Sample (IS) = entry_date &lt; 2024-01-01.
Out-of-Sample (OOS) is report-only. Click column headers to sort.</p>
<div class="ask">
<h2>What you asked</h2>
<blockquote>{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
<blockquote>{html_mod.escape(FOLLOWUP_REQUEST)}</blockquote>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN_ENGLISH)}</p>
<p>{html_mod.escape(FOLLOWUP_PLAIN)}</p>
</div>
<div class="hold"><strong>Verdict:</strong> HOLD as a research size view for true 1%-to-stop
on systems that have a price stop. Relative Strength Index (RSI) roll-8 invert blew up size —
see <a href="rsi_avgloss.html">rsi_avgloss.html</a> for the avg-loss slot stand-in.
Judge Profit Factor, Annualized Rate of Return on the $250k seed, Maximum Drawdown, Calmar, Sharpe.
Do not wire DailyRun.</div>
<section>
<h2>FULL book — house dummy $ vs $2,500-to-stop</h2>
<p class="small">Win % and Avg PnL % stay the same when every fill sizes. Dollar mix,
Profit Factor, Annualized Rate of Return, and Maximum Drawdown change because tight stops
get more shares. Sheet / Total PnL $ omitted from this table (canonical rule).</p>
<div class="table-wrap"><table class="sortable"><thead><tr>{sum_head}</tr></thead>
<tbody>{summary_body}</tbody></table></div>
</section>
{''.join(sections)}
<section>
<h2>Data sources</h2>
<ul>{sources_html}</ul>
<p class="small">Acronyms: Break and ReTest (BRT); Rocket Launcher (RL); Year High (YH);
Magic Touch (MTS); Weekly Pivot Break and Retest (WPBR); Relative Strength vs SPY (RS);
StockBee (SB); Volume Zone (VZ); Relative Strength Index (RSI); In-Sample (IS);
Out-of-Sample (OOS); Annualized Rate of Return (Ann ROR); Maximum Drawdown (Max DD);
Profit Factor (PF); Win Rate (WR).</p>
</section>
{monthly._SORTABLE_TABLE_SCRIPT}
</body></html>"""


def build_monthly_html(
    *,
    year: int,
    closed: list[OverlayTrade],
    open_rows: list[OverlayTrade],
    sources: list[str],
    per_sys: dict[str, dict[str, Any]],
    generated: datetime,
    rsi_avgloss_closed: Optional[list[OverlayTrade]] = None,
    rsi_avgloss_open: Optional[list[OverlayTrade]] = None,
) -> str:
    # Monthly RSI dollars: IS avg-loss slot, not roll-8 invert, not dummy $10k.
    roll8_rsi_closed = [t for t in closed if t.system == "RSI"]
    if rsi_avgloss_closed:
        closed = [t for t in closed if t.system != "RSI"] + list(rsi_avgloss_closed)
    if rsi_avgloss_open is not None:
        open_rows = [t for t in open_rows if t.system != "RSI"] + list(rsi_avgloss_open)
    year_closed = [
        t for t in closed if t.closed and t.closed.year == year and t.sized
    ]
    now = generated.astimezone(ET)
    through_month = now.month if now.year == year else 12
    monthly_agg: dict[tuple[int, int, str], dict] = {}
    for t in year_closed:
        assert t.closed is not None
        key = (t.closed.year, t.closed.month, t.system)
        b = monthly_agg.setdefault(key, {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0})
        b["pnl"] += t.overlay_pnl
        b["trades"] += 1
        if t.overlay_pnl > 0:
            b["wins"] += 1
        elif t.overlay_pnl < 0:
            b["losses"] += 1
    ytd = {sys: {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0} for sys in SYSTEMS}
    for t in year_closed:
        ytd[t.system]["pnl"] += t.overlay_pnl
        ytd[t.system]["trades"] += 1
        if t.overlay_pnl > 0:
            ytd[t.system]["wins"] += 1
        elif t.overlay_pnl < 0:
            ytd[t.system]["losses"] += 1
    open_by = {sys: [] for sys in SYSTEMS}
    for t in open_rows:
        if t.sized:
            open_by[t.system].append(t)
    open_tot = {sys: sum(t.overlay_pnl for t in rows) for sys, rows in open_by.items()}
    na_closed = [t for t in closed if not t.sized]
    na_open = [t for t in open_rows if not t.sized]

    cards = ""
    for sys in SYSTEMS:
        y = ytd[sys]
        unreal = open_tot[sys]
        total = y["pnl"] + unreal
        wr = (100.0 * y["wins"] / y["trades"]) if y["trades"] else 0.0
        n_na = sum(1 for t in closed if t.system == sys and not t.sized)
        slot_note = (
            " · $38,405 avg-loss slot"
            if sys == "RSI"
            else ""
        )
        cards += f"""
  <div class="card">
    <h3>{html_mod.escape(SYSTEM_EXPAND.get(sys, sys))}</h3>
    <div class="metric {_pnl_class(y['pnl'])}">{_fmt_money_signed(y['pnl'])}</div>
    <div class="small">YTD realized · {y['trades']} sized · {wr:.0f}% win{slot_note}</div>
    <div class="small">Open unrealized: <span class="{_pnl_class(unreal)}">{_fmt_money_signed(unreal)}</span>
      ({len(open_by[sys])} sized)</div>
    <div class="small">Realized + open: <span class="{_pnl_class(total)}">{_fmt_money_signed(total)}</span></div>
    <div class="small">Cannot size (N/A): {n_na}</div>
  </div>"""
    total_ytd = sum(v["pnl"] for v in ytd.values())
    total_open = sum(open_tot.values())
    cards += f"""
  <div class="card card-total">
    <h3>All DailyRun systems</h3>
    <div class="metric {_pnl_class(total_ytd)}">{_fmt_money_signed(total_ytd)}</div>
    <div class="small">YTD realized · $2,500-to-stop (RSI = $38,405 avg-loss slot)</div>
    <div class="small">Open unrealized: <span class="{_pnl_class(total_open)}">{_fmt_money_signed(total_open)}</span></div>
    <div class="small">Combined: <span class="{_pnl_class(total_ytd + total_open)}">{_fmt_money_signed(total_ytd + total_open)}</span></div>
  </div>"""

    pivot_head = _sortable_th("Month", "month") + "".join(
        _sortable_th(sys, "num") for sys in SYSTEMS
    ) + _sortable_th("Total", "num")
    pivot_body = ""
    ytd_m = {sys: 0.0 for sys in SYSTEMS}
    for month in range(1, through_month + 1):
        label = monthly.MONTH_NAMES[month - 1]
        cells = []
        row_total = 0.0
        for sys in SYSTEMS:
            stats = monthly_agg.get((year, month, sys), {"pnl": 0.0, "trades": 0})
            pnl = stats["pnl"]
            n = stats["trades"]
            ytd_m[sys] += pnl
            row_total += pnl
            if n:
                cells.append(
                    f'<td class="{_pnl_class(pnl)}">{_fmt_money_signed(pnl)}'
                    f'<br><span class="small">({n} trades)</span></td>'
                )
            else:
                cells.append('<td class="muted">—</td>')
        pivot_body += (
            f"<tr><th>{label}</th>" + "".join(cells)
            + f'<td class="{_pnl_class(row_total)}"><strong>{_fmt_money_signed(row_total)}</strong></td></tr>'
        )
    foot_cells = []
    grand = 0.0
    for sys in SYSTEMS:
        pnl = ytd_m[sys]
        grand += pnl
        foot_cells.append(f'<td class="{_pnl_class(pnl)}"><strong>{_fmt_money_signed(pnl)}</strong></td>')
    pivot_foot = (
        '<tr class="total-row"><th>YTD</th>' + "".join(foot_cells)
        + f'<td class="{_pnl_class(grand)}"><strong>{_fmt_money_signed(grand)}</strong></td></tr>'
    )

    def trade_table(trades: list[OverlayTrade], *, open_book: bool = False) -> str:
        if not trades:
            return '<p class="small">No trades.</p>'
        rows = sorted(trades, key=lambda t: ((t.closed or date.min), t.symbol))
        body = ""
        for t in rows:
            d_close = t.closed.strftime("%Y-%m-%d") if t.closed else ""
            stop_s = f"${t.stop_used:,.2f}" if t.stop_used else "—"
            body += (
                "<tr>"
                f"<td>{_symbol_link(t.symbol)}</td>"
                f"<td>{t.opened.strftime('%Y-%m-%d')}</td>"
                f"<td>{d_close}</td>"
                f"<td>{html_mod.escape(t.exit_type)}</td>"
                f"<td>{int(t.days)}</td>"
                f"<td>{stop_s}</td>"
                f"<td>{_fmt_num(t.shares, 1)}</td>"
                f"<td>{format_money(t.invested) if t.sized else '—'}</td>"
                f"<td class=\"{_pnl_class(t.pnl_pct)}\">{monthly._fmt_pct(t.pnl_pct)}</td>"
                f"<td class=\"{_pnl_class(t.overlay_pnl)}\">{_fmt_money_signed(t.overlay_pnl) if t.sized else 'N/A'}</td>"
                f"<td>{html_mod.escape(t.stop_src if t.sized else t.skip_reason)}</td>"
                "</tr>"
            )
        labels = [
            ("Symbol", "text"),
            ("Opened", "date"),
            ("Closed" if not open_book else "—", "date"),
            ("Exit", "text"),
            ("Days", "num"),
            ("Stop used", "num"),
            ("Shares", "num"),
            ("$ invested", "num"),
            ("PnL %", "num"),
            ("Overlay $", "num"),
            ("Size note", "text"),
        ]
        head = "".join(_sortable_th(a, b) for a, b in labels)
        return (
            f'<table class="sortable"><thead><tr>{head}</tr></thead><tbody>'
            + body + "</tbody></table>"
        )

    month_sections = ""
    for month in range(1, through_month + 1):
        label = monthly._month_label(year, month)
        month_trades = [
            t for t in year_closed
            if t.closed and t.closed.year == year and t.closed.month == month
        ]
        if not month_trades:
            month_sections += f"""
<section class="month-section">
  <h2>{label}</h2>
  <p class="small muted">No sized closed overlay trades this month.</p>
</section>"""
            continue
        month_total = sum(t.overlay_pnl for t in month_trades)
        sys_blocks = ""
        for sys in SYSTEMS:
            sys_trades = [t for t in month_trades if t.system == sys]
            if not sys_trades:
                continue
            sys_pnl = sum(t.overlay_pnl for t in sys_trades)
            sys_blocks += f"""
  <div class="sys-block">
    <h3>{html_mod.escape(SYSTEM_EXPAND.get(sys, sys))} · <span class="{_pnl_class(sys_pnl)}">{_fmt_money_signed(sys_pnl)}</span> · {len(sys_trades)} closed</h3>
    <div class="table-wrap">{trade_table(sys_trades)}</div>
  </div>"""
        month_sections += f"""
<section class="month-section">
  <h2>{label} · <span class="{_pnl_class(month_total)}">{_fmt_money_signed(month_total)}</span> total</h2>
  {sys_blocks}
</section>"""

    open_sections = ""
    for sys in SYSTEMS:
        rows = open_by[sys]
        if not rows:
            continue
        sys_pnl = open_tot[sys]
        open_sections += f"""
  <div class="sys-block">
    <h3>{html_mod.escape(SYSTEM_EXPAND.get(sys, sys))} · <span class="{_pnl_class(sys_pnl)}">{_fmt_money_signed(sys_pnl)}</span> · {len(rows)} open</h3>
    <div class="table-wrap">{trade_table(rows, open_book=True)}</div>
  </div>"""

    # All-year overlay totals (closed, sized)
    year_tot: dict[int, dict[str, float]] = defaultdict(lambda: {s: 0.0 for s in SYSTEMS})
    year_n: dict[int, dict[str, int]] = defaultdict(lambda: {s: 0 for s in SYSTEMS})
    for t in closed:
        if t.sized and t.closed:
            year_tot[t.closed.year][t.system] += t.overlay_pnl
            year_n[t.closed.year][t.system] += 1
    hist_head = _sortable_th("Year", "num") + "".join(
        _sortable_th(s, "num") for s in SYSTEMS
    ) + _sortable_th("Total", "num")
    hist_body = ""
    col_tot = {s: 0.0 for s in SYSTEMS}
    for y in sorted(year_tot):
        cells = []
        tot = 0.0
        for sys in SYSTEMS:
            pnl = year_tot[y][sys]
            n = year_n[y][sys]
            tot += pnl
            col_tot[sys] += pnl
            if n:
                cells.append(
                    f'<td class="{_pnl_class(pnl)}">{_fmt_money_signed(pnl)}'
                    f'<br><span class="small">({n})</span></td>'
                )
            else:
                cells.append('<td class="muted">—</td>')
        hist_body += (
            f"<tr><th>{y}</th>" + "".join(cells)
            + f'<td class="{_pnl_class(tot)}"><strong>{_fmt_money_signed(tot)}</strong></td></tr>'
        )
    grand_hist = sum(col_tot.values())
    hist_foot_cells = [
        f'<td class="{_pnl_class(col_tot[sys])}"><strong>{_fmt_money_signed(col_tot[sys])}</strong></td>'
        for sys in SYSTEMS
    ]
    hist_foot = (
        '<tr class="total-row"><th>Total</th>' + "".join(hist_foot_cells)
        + f'<td class="{_pnl_class(grand_hist)}"><strong>{_fmt_money_signed(grand_hist)}</strong></td></tr>'
    )

    na_html = ""
    if na_closed or na_open:
        na_rows = "".join(
            f"<tr><td>{html_mod.escape(t.system)}</td><td>{_symbol_link(t.symbol)}</td>"
            f"<td>{t.opened.isoformat()}</td><td>{html_mod.escape(t.skip_reason)}</td>"
            f"<td>{html_mod.escape(t.stop_src)}</td></tr>"
            for t in (na_closed + na_open)[:400]
        )
        extra = ""
        if len(na_closed) + len(na_open) > 400:
            extra = f"<p class='small'>Showing first 400 of {len(na_closed)+len(na_open)} N/A rows. Full list is in overlay CSVs.</p>"
        na_head = "".join(
            _sortable_th(a, b)
            for a, b in (
                ("System", "text"),
                ("Symbol", "text"),
                ("Opened", "date"),
                ("Why N/A", "text"),
                ("Stop source", "text"),
            )
        )
        na_html = f"""
<section>
<h2>Cannot use 1%-to-stop (N/A)</h2>
<p class="small">{len(na_closed)} closed + {len(na_open)} open. Stop missing, 0, or at/above entry
on true $2,500 / (entry − stop) systems. Relative Strength Index (RSI) uses the avg-loss
slot (every fill with a PnL% sizes). Click headers to sort.</p>
{extra}
<div class="table-wrap"><table class="sortable"><thead><tr>{na_head}</tr></thead>
<tbody>{na_rows}</tbody></table></div>
</section>"""

    sources_html = "".join(f"<li>{html_mod.escape(s)}</li>" for s in sources)
    gen_s = now.strftime("%Y-%m-%d %H:%M %Z")
    verdicts = "; ".join(
        f"{sys}: {(per_sys[sys].get('avgloss_meta') or {}).get('verdict') or per_sys[sys]['tables']['FULL']['verdict']}"
        if sys == "RSI"
        else f"{sys}: {per_sys[sys]['tables']['FULL']['verdict']}"
        for sys in SYSTEMS
    )
    rsi_addendum = ""
    meta = per_sys.get("RSI", {}).get("avgloss_meta")
    if meta and rsi_avgloss_closed:
        ytd_al = ytd.get("RSI", {}).get("pnl", 0.0)
        n_al = ytd.get("RSI", {}).get("trades", 0)
        open_al = open_tot.get("RSI", 0.0)
        ytd_r8 = sum(
            t.overlay_pnl
            for t in roll8_rsi_closed
            if t.closed and t.closed.year == year and t.sized
        )
        slot_s = format_money(meta.get("slot"))
        rsi_addendum = f"""
<section>
<h2>Relative Strength Index (RSI) — this monthly uses the avg-loss slot</h2>
<p>Roll-8 invert is no longer what this monthly uses. RSI dollars here are the
In-Sample freeze: mean |PnL%| on IS losers = <strong>{_fmt_pct(meta.get('is_avg_loss_pct'))}</strong>
({meta.get('n_is_losers')} losers) → slot <strong>{slot_s}</strong> per name
(<code>shares = slot / entry</code>). Typical IS loser ≈ $2,500. Not dummy $10k.
Other DailyRun systems stay on true <code>$2,500 / (entry − stop)</code>.
Full three-arm compare: <a href="rsi_avgloss.html">rsi_avgloss.html</a>.</p>
<p>{year} RSI YTD (avg-loss slot):
<span class="{_pnl_class(ytd_al)}">{_fmt_money_signed(ytd_al)}</span> ({n_al} closed) ·
open unrealized <span class="{_pnl_class(open_al)}">{_fmt_money_signed(open_al)}</span>.
<span class="small">Retired roll-8 invert {year} YTD (not in the tables):
{_fmt_money_signed(ytd_r8)}.</span></p>
<p class="small">{html_mod.escape(str(meta.get('verdict') or ''))} Full-book avg loss
(note only, not the freeze) = {_fmt_pct(meta.get('full_avg_loss_pct'))}.</p>
</section>"""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Monthly $2,500 risk-to-stop — {year}</title>
<style>
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
.cards {{ display:flex; flex-wrap:wrap; gap:12px; margin:16px 0 24px; }}
.card {{ background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:14px 16px; min-width:200px; flex:1 1 220px; }}
.card-total {{ background:#eef2ff; border-color:#c7d2fe; }}
.card h3 {{ margin:0 0 8px; font-size:13px; color:#475569; font-weight:700; }}
.metric {{ font-size:1.35rem; font-weight:700; line-height:1.2; }}
.small {{ font-size:12px; color:#64748b; }}
.muted {{ color:#94a3b8; }}
.pos {{ color:#16a34a; }} .neg {{ color:#dc2626; }}
section {{ margin-top:24px; }}
.month-section {{ border-top:1px solid #e2e8f0; padding-top:8px; }}
.sys-block {{ margin:12px 0 20px; }}
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
{TABLE_UNCAP_CSS}
</style></head><body>
<h1>Monthly Backtest Report — {year} · $2,500 risk-to-stop</h1>
<p class="sub">
Research size overlay on house DailyRun Closed / Open pins. Not live broker P&amp;L.
Not gold. Not DailyRun. Same trades as the house monthly. Other systems:
<code>shares = $2,500 / (entry − stop)</code>. Relative Strength Index (RSI) uses the
In-Sample avg-loss slot (<code>$2,500 / 0.0651 = $38,405</code> per name;
<code>shares = 38405 / entry</code>) — not roll-8 invert and not dummy $10k.
Account context $250,000. Generated {html_mod.escape(gen_s)}. Click column headers to sort.
</p>
<div class="ask">
<h2>What you asked</h2>
<blockquote>{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
<blockquote>{html_mod.escape(FOLLOWUP_REQUEST)}</blockquote>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN_ENGLISH)}</p>
<p>{html_mod.escape(FOLLOWUP_PLAIN)}</p>
</div>
<div class="hold"><strong>HOLD</strong> — size view you asked to see, not an adopt-to-DailyRun.
{html_mod.escape(verdicts)}</div>
{rsi_addendum}
<div class="cards">{cards}</div>
<section>
<h2>Monthly realized overlay P&amp;L by system ({year})</h2>
<p class="small">Closed trades grouped by exit month. Other systems: $2,500 risk-to-stop.
RSI: $38,405 avg-loss slot (IS freeze). Not house dummy notionals. Click column headers to sort.</p>
<div class="table-wrap">
<table class="sortable">
  <thead><tr>{pivot_head}</tr></thead>
  <tbody>{pivot_body}{pivot_foot}</tbody>
</table>
</div>
</section>
<section>
<h2>All years — overlay realized $ (sized closed)</h2>
<p class="small">Same $2,500-to-stop rule on the full house book; RSI = $38,405 avg-loss slot.
Click headers to sort.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>{hist_head}</tr></thead>
<tbody>{hist_body}{hist_foot}</tbody></table></div>
</section>
{month_sections}
<section>
<h2>Open positions (unrealized overlay $)</h2>
<p class="small">Same shares rule on the latest Open book (RSI = avg-loss slot).</p>
{open_sections if open_sections else '<p class="small muted">No sized open overlay positions.</p>'}
</section>
{na_html}
<section>
<h2>Data sources</h2>
<ul class="sources">{sources_html}</ul>
<p class="small">Compare vs house dummy notionals:
<a href="compare.html">compare.html</a>. RSI avg-loss arm:
<a href="rsi_avgloss.html">rsi_avgloss.html</a>. Overlay CSVs live in this stamp folder.
Acronyms: Break and ReTest (BRT); Rocket Launcher (RL); Year High (YH); Magic Touch (MTS);
Weekly Pivot Break and Retest (WPBR); Relative Strength vs SPY (RS); StockBee (SB);
Volume Zone (VZ); Relative Strength Index (RSI); In-Sample (IS); Out-of-Sample (OOS);
Annualized Rate of Return (Ann ROR); Maximum Drawdown (Max DD).</p>
</section>
{monthly._SORTABLE_TABLE_SCRIPT}
</body></html>"""


def write_baseline(per_sys: dict[str, dict[str, Any]], sources: list[str]) -> None:
    lines = [
        f"# BASELINE — {STAMP}",
        "",
        "**Status:** Research size overlay. **Not gold. Not DailyRun.** Out-of-Sample (OOS) report-only.",
        "",
        "## What you asked",
        "",
        f"> {ORIGINAL_REQUEST}",
        "",
        f"> {FOLLOWUP_REQUEST}",
        "",
        "## In plain English",
        "",
        PLAIN_ENGLISH,
        "",
        FOLLOWUP_PLAIN,
        "",
        "## Selection",
        "",
        "- Paul specified the number: account **$250,000**, max loss if stop hits = **$2,500** per entry (1%).",
        "- Do **not** keep using $5,000 (1% of the old $500k).",
        "- Prior 1% stamp `risk1pct_size_ab_20260915` is frozen ($5,000 / path / ATR proxy). This is a **new** stamp.",
        "- This is a SIZE overlay only. Entries, exits, and universes are house DailyRun pins. No retune. No OOS shop.",
        "- Default decision: **HOLD** (size view he asked to see). Not an adopt-to-DailyRun.",
        "",
        "## Frozen knobs",
        "",
        f"- Account (Annualized Rate of Return / Maximum Drawdown seed): **${ACCOUNT:,.0f}**",
        f"- Risk $ per entry if stop hits: **${RISK_DOLLARS:,.0f}**",
        "- Formula: `shares = 2500 / (entry − stop)` when stop < entry; `$ invested = shares × entry`; overlay $ PnL = invested × PnL%.",
        "- Secondary Ann ROR cash: $500k and $600k (host deployable context only).",
        "- In-Sample (IS) = `entry_date < 2024-01-01`. OOS = `entry_date >= 2024-01-01` (report-only).",
        f"- Systems (DailyRun-wired): {', '.join(SYSTEM_EXPAND[s] for s in SYSTEMS)}.",
        "- Indicators (IND) deprecated / skipped. Weekly Range / Swing (WRL) not DailyRun-wired. Minervini Volatility Contraction Pattern (MVCP) retired.",
        "- CONTROL = house Closed `PNL_DOLLARS` (dummy / host / sheet scale as published).",
        "- Candidate = SIZE_risk2500 on the **same** Closed rows.",
        "- **monthly.html RSI column/rows** use Arm B (IS avg-loss slot $38,405), not Arm A roll-8 invert, not dummy $10k. Roll-8 invert is no longer what the monthly uses.",
        "",
        "## Relative Strength Index (RSI) treatment (two labeled arms — do not shop)",
        "",
        "- House Closed writes `STOP_PRICE=0` on every RSI row (no live price stop).",
        "- **Arm A (already run):** implied roll-8 what-if close: invert Wilder RSI(14) to the close that prints RSI ≤ (RSI at SIGNAL_DATE / last complete bar before fill) − 8, then `shares = 2500 / (entry − that_close)`. Synthetic stop. Tiny gap → huge size (peak ~$3.1M, Max DD ~37%). Not re-shopped. **Not in monthly.html.**",
        "- **Arm B (Paul follow-up, freeze; monthly RSI):** IS-only mean |PNL_PCT| of losing RSI fills. `invested = 2500 / |avg_loss as fraction|` — same slot on every RSI name. Full-book avg loss is a note only. No ATR % proxy. No roll-8 invert for this arm.",
        "- If invert fails on Arm A → N/A. Arm B sizes every fill that has a PnL%.",
        "",
        "## Honesty",
        "",
        "- Tight stops size huge positions. Concurrent names each risk ~$2,500, so book risk stacks (~1% × names open).",
        "- Win % and Avg PnL % are unweighted — they match CONTROL when the same fills size. Judge Profit Factor, Ann ROR on $250k, Max DD, Calmar, Sharpe, peak notional.",
        "- House monthly dollars stay on dummy notionals. This stamp does **not** change `run_*.bat` or the live investment report.",
        "- Picking KEEP from this same history would be in-sample selection. We are not picking.",
        "",
        "## Pins / sources",
        "",
    ]
    for s in sources:
        lines.append(f"- {s}")
    lines += ["", "## FULL overlay vs house (quality)", ""]
    for sys in SYSTEMS:
        pack = per_sys[sys]
        c = pack["tables"]["FULL"]["CONTROL"]
        a = pack["tables"]["FULL"]["SIZE_risk2500"]
        lines.append(
            f"### {SYSTEM_EXPAND.get(sys, sys)}  ({pack['pin']})"
        )
        lines.append("")
        lines.append(
            f"- House N={c.get('n')} overlay N={a.get('n')} N/A={a.get('n_na')} "
            f"tiny_stop(<0.20%)={a.get('n_tiny_stop')}"
        )
        lines.append(
            f"- House WR={c.get('win_pct')} Avg%={c.get('avg_pnl_pct')} PF={c.get('pf')} "
            f"AnnROR$250k={c.get('ann_ror_250k')} MaxDD={c.get('max_dd')} Calmar={c.get('calmar')} Sharpe={c.get('sharpe')}"
        )
        lines.append(
            f"- Overlay WR={a.get('win_pct')} Avg%={a.get('avg_pnl_pct')} PF={a.get('pf')} "
            f"AnnROR$250k={a.get('ann_ror_250k')} MaxDD={a.get('max_dd')} Calmar={a.get('calmar')} Sharpe={a.get('sharpe')} "
            f"mean$={a.get('mean_notional')} peak$={a.get('peak_notional')}"
        )
        lines.append(f"- Note: {pack['tables']['FULL']['verdict']}")
        av = pack["tables"]["FULL"].get("SIZE_rsi_avgloss")
        meta = pack.get("avgloss_meta")
        if av and meta:
            lines.append(
                f"- RSI avg-loss slot (IS freeze): avg_loss={meta.get('is_avg_loss_pct')}% "
                f"n_losers={meta.get('n_is_losers')} slot=${meta.get('slot')} "
                f"full_book_avg_loss_note={meta.get('full_avg_loss_pct')}%"
            )
            lines.append(
                f"- Avg-loss FULL N={av.get('n')} WR={av.get('win_pct')} Avg%={av.get('avg_pnl_pct')} "
                f"PF={av.get('pf')} AnnROR$250k={av.get('ann_ror_250k')} MaxDD={av.get('max_dd')} "
                f"Calmar={av.get('calmar')} Sharpe={av.get('sharpe')} mean$={av.get('mean_notional')} "
                f"peak$={av.get('peak_notional')}"
            )
            lines.append(f"- Avg-loss note: {meta.get('verdict')}")
        lines.append("")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_hypothesis() -> None:
    text = f"""# HYPOTHESIS — {STAMP}

**Product owner (PO)–aligned process:** one knob, frozen everything else. See `docs/HYPOTHESIS_TEST.md`.

| Field | Fill in |
|-------|---------|
| System / prefix | DailyRun-wired: {", ".join(SYSTEMS)} |
| Baseline stamp | House LatestRun / golden pins as of {ASOF.isoformat()} (same resolver as `generate_monthly_system_report.py`) |
| Universe | House DailyRun universes (unchanged) |
| **Evidence** | Paul: account is now $250k; 1% = $2,500. Follow-up: RSI has no price stop — use IS avg loser % as the 1% stand-in |
| **Hypothesis** | (1) $2,500 / (entry−stop) changes dollar quality vs house dummy. (2) For RSI, a flat slot = $2,500 / \\|IS avg loss\\%\\| is a saner 1% stand-in than roll-8 invert |
| **Single knob** | SIZE. Other systems: 2500/(entry−stop). RSI Arm B: equal slot from IS avg loss. EXIT/ENTRY freeze unchanged |
| Frozen settings | House entries, exits, universes, pins. RSI Arm A = roll-8 invert (not re-shopped). RSI Arm B = IS avg loss only (full-book avg loss is a note). No ATR % |
| Alternatives | CONTROL = house Closed `PNL_DOLLARS`. SIZE_risk2500. SIZE_rsi_avgloss (RSI only) |
| Candidate stamps | `{STAMP}` overlay CSVs + monthly.html / compare.html / rsi_avgloss.html |
| Metrics | Canonical book set; judge quality not trade count; IS / OOS reported; OOS report-only |
| **Trade-diff HTML** | N/A — same trades, dollars only (not an entry A/B) |
| ToS before path | N/A |
| ToS after path | N/A |
| **Decision** | HOLD on 1%-to-stop book. monthly.html RSI uses Arm B avg-loss slot (not roll-8). RSI avg-loss vs roll-8 scored in rsi_avgloss.html. Not gold. Not DailyRun |
| Reviewer | AI job {STAMP} |
| PO sign-off | no |
| Reconcile freeze / re-baseline done | no |

## Decision checklist

- [x] Evidence was the PO number ($250k → $2,500), not a grid search
- [x] Only one knob differed (size)
- [x] Same Closed pins as the house monthly
- [ ] Charts / Thinkorswim (ToS) — not required for a size overlay
- [x] Out-of-Sample (OOS) report-only; no retune
- [ ] If adopt: PO signed off — **not adopting**
"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "HYPOTHESIS.md").write_text(text, encoding="utf-8")


def _sources_from_paths(paths: dict[str, dict[str, Optional[Path]]]) -> list[str]:
    sources: list[str] = []
    for sys in SYSTEMS:
        cpath = paths.get(sys, {}).get("closed")
        opath = paths.get(sys, {}).get("open")
        sources.append(
            f"{sys} closed: {cpath.name}" if cpath is not None and cpath.is_file() else f"{sys} closed: (missing)"
        )
        sources.append(
            f"{sys} open: {opath.name}" if opath is not None and opath.is_file() else f"{sys} open: (missing)"
        )
    return sources


def rebuild_monthly_from_stamp() -> int:
    """Rebuild monthly.html from stamp overlay CSVs. RSI = avg-loss slot.

    Does not retune the 6.51% IS freeze. Does not rewrite other-system overlays
    or DailyRun. Does not re-run roll-8 invert.
    """
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    paths = _resolve_paths()
    sources = _sources_from_paths(paths)
    closed_all: list[OverlayTrade] = []
    open_all: list[OverlayTrade] = []
    per_sys: dict[str, dict[str, Any]] = {}
    rsi_al_closed: list[OverlayTrade] = []
    rsi_al_open: list[OverlayTrade] = []
    roll8_rsi_closed: list[OverlayTrade] = []

    for sys in SYSTEMS:
        ov = load_overlay_csv(OUT_DIR / f"{sys}_overlay_risk2500.csv")
        closed_ov = [t for t in ov if t.status == "closed"]
        open_ov = [t for t in ov if t.status == "open"]
        pin = "overlay csv"
        cpath = paths.get(sys, {}).get("closed")
        if cpath is not None and cpath.is_file():
            pin = cpath.name

        rsi_al_this: list[OverlayTrade] = []
        avgloss_meta: Optional[dict[str, Any]] = None
        if sys == "RSI":
            roll8_rsi_closed = closed_ov
            al = load_overlay_csv(OUT_DIR / "RSI_overlay_avgloss.csv")
            if not al:
                raise SystemExit("missing RSI_overlay_avgloss.csv — cannot rebuild monthly on avg-loss slot")
            rsi_al_closed = [t for t in al if t.status == "closed"]
            rsi_al_open = [t for t in al if t.status == "open"]
            rsi_al_this = rsi_al_closed
            closed_raw: list[dict[str, Any]] = []
            if cpath is not None and cpath.is_file():
                closed_raw = load_closed_rows(cpath, sys)
            is_loss, n_is_l = avg_loss_pct_points(closed_raw, is_only=True)
            full_loss, n_full_l = avg_loss_pct_points(closed_raw, is_only=False)
            slot = avgloss_slot(is_loss)
            # Freeze check: do not silently replace the stamped 6.51% / $38,405.
            sized_slots = [t.invested for t in rsi_al_closed if t.sized]
            csv_slot = (sum(sized_slots) / len(sized_slots)) if sized_slots else None
            if slot is None and csv_slot is not None:
                slot = csv_slot
                is_loss = 100.0 * RISK_DOLLARS / slot if slot else is_loss
            print(
                f"[RSI] IS avg |loss|={is_loss} n={n_is_l} "
                f"FULL avg |loss|={full_loss} n={n_full_l} slot={slot} csv_slot={csv_slot}"
            )
            avgloss_meta = {
                "is_avg_loss_pct": is_loss,
                "n_is_losers": n_is_l,
                "full_avg_loss_pct": full_loss,
                "n_full_losers": n_full_l,
                "slot": slot if slot is not None else csv_slot,
            }

        tables: dict[str, Any] = {}
        for sl in ("IS", "OOS", "FULL"):
            book = slice_trades(closed_ov, sl)
            ctrl = book_stats(
                book, use_overlay=False, cash_ann=SHEET_DEFAULT.get(sys, 47_500.0), dd_seed=ACCOUNT
            )
            mean_ov = None
            sized = [t for t in book if t.sized]
            if sized:
                mean_ov = sum(t.invested for t in sized) / len(sized)
            cand = book_stats(
                book,
                use_overlay=True,
                cash_ann=float(mean_ov or RISK_DOLLARS),
                dd_seed=ACCOUNT,
            )
            row: dict[str, Any] = {
                "CONTROL": ctrl,
                "SIZE_risk2500": cand,
                "verdict": _verdict(ctrl, cand) if sl == "FULL" else (
                    "report-only" if sl == "OOS" else "IS — do not retune OOS"
                ),
            }
            if sys == "RSI" and rsi_al_this:
                al_book = slice_trades(rsi_al_this, sl)
                al_slot = float(avgloss_meta["slot"]) if avgloss_meta and avgloss_meta.get("slot") else RISK_DOLLARS
                row["SIZE_rsi_avgloss"] = book_stats(
                    al_book,
                    use_overlay=True,
                    cash_ann=al_slot,
                    dd_seed=ACCOUNT,
                )
            tables[sl] = row
        if avgloss_meta and "SIZE_rsi_avgloss" in tables["FULL"]:
            avgloss_meta["verdict"] = _verdict_rsi_avgloss(
                tables["FULL"]["CONTROL"],
                tables["FULL"]["SIZE_risk2500"],
                tables["FULL"]["SIZE_rsi_avgloss"],
            )
        per_sys[sys] = {
            "pin": pin,
            "tables": tables,
            "avgloss_meta": avgloss_meta,
            "rsi_al_closed": rsi_al_this,
            "rsi_al_open": rsi_al_open if sys == "RSI" else [],
        }
        closed_all.extend(closed_ov)
        open_all.extend(open_ov)
        n_sz = sum(1 for t in closed_ov if t.sized)
        n_na = sum(1 for t in closed_ov if not t.sized)
        print(f"[{sys}] pin={pin} closed={len(closed_ov)} sized={n_sz} na={n_na} open={len(open_ov)}")

    write_baseline(per_sys, sources)
    write_hypothesis()
    now = datetime.now(tz=ET)
    monthly_html = build_monthly_html(
        year=ASOF.year,
        closed=closed_all,
        open_rows=open_all,
        sources=sources,
        per_sys=per_sys,
        generated=now,
        rsi_avgloss_closed=rsi_al_closed or None,
        rsi_avgloss_open=rsi_al_open,
    )
    (OUT_DIR / "monthly.html").write_text(monthly_html, encoding="utf-8")
    print(f"wrote {OUT_DIR / 'monthly.html'}")
    print(
        f"[monthly] RSI uses avg-loss slot; roll-8 closed N={len(roll8_rsi_closed)} "
        f"avgloss closed N={len(rsi_al_closed)}"
    )
    return 0


def run() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    paths = _resolve_paths()
    sources: list[str] = []
    closed_all: list[OverlayTrade] = []
    open_all: list[OverlayTrade] = []
    per_sys: dict[str, dict[str, Any]] = {}

    for sys in SYSTEMS:
        cpath = paths.get(sys, {}).get("closed")
        opath = paths.get(sys, {}).get("open")
        pin = "missing"
        closed_raw: list[dict[str, Any]] = []
        open_raw: list[dict[str, Any]] = []
        if cpath is not None and cpath.is_file():
            pin = cpath.name
            sources.append(f"{sys} closed: {cpath.name}")
            closed_raw = load_closed_rows(cpath, sys)
        else:
            sources.append(f"{sys} closed: (missing)")
        if opath is not None and opath.is_file():
            sources.append(f"{sys} open: {opath.name}")
            open_raw = load_open_rows(opath, sys)
        else:
            sources.append(f"{sys} open: (missing)")

        closed_ov = [overlay_one(sys, r) for r in closed_raw]
        open_ov = [overlay_one(sys, r) for r in open_raw]
        closed_all.extend(closed_ov)
        open_all.extend(open_ov)
        write_overlay_csv(closed_ov + open_ov, OUT_DIR / f"{sys}_overlay_risk2500.csv")

        rsi_al_closed: list[OverlayTrade] = []
        rsi_al_open: list[OverlayTrade] = []
        avgloss_meta: Optional[dict[str, Any]] = None
        if sys == "RSI":
            is_loss, n_is_l = avg_loss_pct_points(closed_raw, is_only=True)
            full_loss, n_full_l = avg_loss_pct_points(closed_raw, is_only=False)
            slot = avgloss_slot(is_loss)
            print(
                f"[RSI] IS avg |loss|={is_loss} n={n_is_l} "
                f"FULL avg |loss|={full_loss} n={n_full_l} slot={slot}"
            )
            if slot is not None:
                src = f"rsi_is_avgloss_slot:{is_loss:.6f}pct"
                rsi_al_closed = [apply_equal_slot(t, slot, src=src) for t in closed_ov]
                rsi_al_open = [apply_equal_slot(t, slot, src=src) for t in open_ov]
                write_overlay_csv(
                    rsi_al_closed + rsi_al_open,
                    OUT_DIR / "RSI_overlay_avgloss.csv",
                )
            avgloss_meta = {
                "is_avg_loss_pct": is_loss,
                "n_is_losers": n_is_l,
                "full_avg_loss_pct": full_loss,
                "n_full_losers": n_full_l,
                "slot": slot,
            }

        tables: dict[str, Any] = {}
        for sl in ("IS", "OOS", "FULL"):
            book = slice_trades(closed_ov, sl)
            ctrl = book_stats(
                book, use_overlay=False, cash_ann=SHEET_DEFAULT.get(sys, 47_500.0), dd_seed=ACCOUNT
            )
            mean_ov = None
            sized = [t for t in book if t.sized]
            if sized:
                mean_ov = sum(t.invested for t in sized) / len(sized)
            cand = book_stats(
                book,
                use_overlay=True,
                cash_ann=float(mean_ov or RISK_DOLLARS),
                dd_seed=ACCOUNT,
            )
            row: dict[str, Any] = {
                "CONTROL": ctrl,
                "SIZE_risk2500": cand,
                "verdict": _verdict(ctrl, cand) if sl == "FULL" else (
                    "report-only" if sl == "OOS" else "IS — do not retune OOS"
                ),
            }
            if rsi_al_closed:
                al_book = slice_trades(rsi_al_closed, sl)
                al_slot = float(avgloss_meta["slot"]) if avgloss_meta and avgloss_meta.get("slot") else RISK_DOLLARS
                row["SIZE_rsi_avgloss"] = book_stats(
                    al_book,
                    use_overlay=True,
                    cash_ann=al_slot,
                    dd_seed=ACCOUNT,
                )
            tables[sl] = row
        if avgloss_meta and "SIZE_rsi_avgloss" in tables["FULL"]:
            avgloss_meta["verdict"] = _verdict_rsi_avgloss(
                tables["FULL"]["CONTROL"],
                tables["FULL"]["SIZE_risk2500"],
                tables["FULL"]["SIZE_rsi_avgloss"],
            )
        per_sys[sys] = {
            "pin": pin,
            "tables": tables,
            "avgloss_meta": avgloss_meta,
            "rsi_al_closed": rsi_al_closed,
            "rsi_al_open": rsi_al_open,
        }
        n_sz = sum(1 for t in closed_ov if t.sized)
        n_na = sum(1 for t in closed_ov if not t.sized)
        print(f"[{sys}] pin={pin} closed={len(closed_ov)} sized={n_sz} na={n_na} open={len(open_ov)}")

    write_overlay_csv(closed_all + open_all, OUT_DIR / "ALL_overlay_risk2500.csv")
    write_baseline(per_sys, sources)
    write_hypothesis()

    now = datetime.now(tz=ET)
    rsi_pack = per_sys.get("RSI") or {}
    monthly_html = build_monthly_html(
        year=ASOF.year,
        closed=closed_all,
        open_rows=open_all,
        sources=sources,
        per_sys=per_sys,
        generated=now,
        rsi_avgloss_closed=rsi_pack.get("rsi_al_closed") or None,
        rsi_avgloss_open=rsi_pack.get("rsi_al_open") or None,
    )
    compare_html = build_compare_html(per_sys, sources)
    (OUT_DIR / "monthly.html").write_text(monthly_html, encoding="utf-8")
    (OUT_DIR / "compare.html").write_text(compare_html, encoding="utf-8")
    print(f"wrote {OUT_DIR / 'monthly.html'}")
    print(f"wrote {OUT_DIR / 'compare.html'}")
    if rsi_pack.get("avgloss_meta") and "SIZE_rsi_avgloss" in rsi_pack.get("tables", {}).get("FULL", {}):
        rsi_html = build_rsi_avgloss_html(
            rsi_pack=rsi_pack,
            avgloss_meta=rsi_pack["avgloss_meta"],
            sources=sources,
        )
        (OUT_DIR / "rsi_avgloss.html").write_text(rsi_html, encoding="utf-8")
        print(f"wrote {OUT_DIR / 'rsi_avgloss.html'}")
    return 0


if __name__ == "__main__":
    if "--monthly-only" in sys.argv:
        raise SystemExit(rebuild_monthly_from_stamp())
    if "--compound" in sys.argv:
        _C_SPEC = importlib.util.spec_from_file_location(
            "risk2500_monthly_compound_20260917",
            REPO / "tools" / "risk2500_monthly_compound_20260917.py",
        )
        _comp = importlib.util.module_from_spec(_C_SPEC)
        assert _C_SPEC.loader is not None
        _C_SPEC.loader.exec_module(_comp)
        raise SystemExit(_comp.run())
    raise SystemExit(run())
