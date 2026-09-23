#!/usr/bin/env python3
"""Official live-style position sizing (source of truth).

Locked freeze (Paul 2026-09-17 — stamp risk_1pct_50k_adv_17name_20260917):

  risk_dollar = min(1% × beginning-of-month equity, $50,000)
  shares ≤ 1% × ADV20 (20-session average daily volume)
  notional ≤ 17.5% × current equity (minus already-open notional in that name)
  RSI invested = risk_dollar / 0.06509607  (IS average-loss freeze; do not retune OOS)

Live buy size applies to every getTarget / DailyRun system (RS, BRT, YH, WPBR,
WRL, CS, MVCP, IND, and the official 6-sys sleeve SB / RSI / VZ / MTS / RL / WRL).
The 6-sys compound-wallet backtest is a separate freeze — do not skip shares
because a name is outside that sleeve. Old 5-sys pin is leftover only.
Engine Closed CSVs stay on house dummy notionals for reconcile — this module is
for live buy size (getTarget / investment report / watchlist Suggested shares).

Account state: drive/live_style_account.json (BOM + current equity).
Index: drive/paul_experiments/LIVE_STYLE_FREEZE.md
"""
from __future__ import annotations

import json
import math
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Optional

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
ACCOUNT_JSON = REPO / "drive" / "live_style_account.json"
OHLCV_DIR = REPO / "data" / "newdata" / "data"
FREEZE_STAMP = "risk_1pct_50k_adv_17name_20260917"

# --- Locked freeze knobs (do not retune casually) ---
RISK_FRAC = 0.01
MAX_RISK_DOLLAR = 50_000.0
ADV_FRAC = 0.01
ADV_WINDOW = 20
NAME_CAP_FRAC = 0.175
RSI_AVG_LOSS_PCT_FREEZE = 6.509607046979868
RSI_AVG_LOSS_FRAC = RSI_AVG_LOSS_PCT_FREEZE / 100.0
ACCOUNT_START = 250_000.0
WITHDRAW_MONTHLY = 7_500.0
MARGIN_RATE = 0.105
LEVERAGE = 2.0
# Every getTarget system — not only the official 6-sys compound-wallet sleeve.
GETTARGET_SYSTEMS = frozenset(
    {"RL", "BRT", "IND", "YH", "MTS", "WPBR", "RS", "SB", "MVCP", "CS", "WRL", "VZ", "RSI"}
)
LIVE_SIZED_SYSTEMS = GETTARGET_SYSTEMS
MIN_DEPLOY = 1.0

_ADV_CACHE: dict[str, list[tuple[date, float]]] = {}
_OHLC_CACHE: dict[str, Optional[pd.DataFrame]] = {}


@dataclass
class AccountState:
    """Live equity inputs for sizing."""

    bom_equity: float = ACCOUNT_START
    current_equity: float = ACCOUNT_START
    asof: str = ""
    notes: str = ""
    source: str = "default"


@dataclass
class SizeResult:
    symbol: str
    system: str
    entry: float
    stop: float
    risk_dollar: float
    shares: float
    notional: float
    adv20: Optional[float]
    shares_risk: float
    shares_adv: float
    shares_name: float
    binding_lid: str
    skip_reason: str = ""
    sized: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def as_row(self) -> dict[str, Any]:
        return {
            "SUGGESTED_SHARES": (
                f"{self.shares:.0f}" if self.sized and self.shares > 0 else "—"
            ),
            "SUGGESTED_NOTIONAL": (
                f"{self.notional:,.2f}" if self.sized and self.notional > 0 else "—"
            ),
            "RISK_DOLLAR": f"{self.risk_dollar:,.2f}",
            "ADV20": f"{self.adv20:,.0f}" if self.adv20 and self.adv20 > 0 else "—",
            "SIZE_LID": self.binding_lid or self.skip_reason or "—",
        }


def freeze_dict() -> dict[str, Any]:
    return {
        "stamp": FREEZE_STAMP,
        "risk": "min(1% BOM equity, $50000)",
        "risk_frac": RISK_FRAC,
        "max_risk_dollar": MAX_RISK_DOLLAR,
        "adv_frac": ADV_FRAC,
        "adv_window": ADV_WINDOW,
        "name_cap_frac": NAME_CAP_FRAC,
        "rsi_avg_loss_frac": RSI_AVG_LOSS_FRAC,
        "rsi_avg_loss_pct_freeze": RSI_AVG_LOSS_PCT_FREEZE,
        "systems": sorted(GETTARGET_SYSTEMS),
        "account_start": ACCOUNT_START,
        "withdraw_monthly": WITHDRAW_MONTHLY,
        "margin_rate": MARGIN_RATE,
        "leverage": LEVERAGE,
        "official": True,
        "engine_closed_unchanged": True,
    }


def risk_dollar(bom_equity: float) -> float:
    return min(RISK_FRAC * max(float(bom_equity), 0.0), MAX_RISK_DOLLAR)


def load_account_state(path: Path = ACCOUNT_JSON) -> AccountState:
    if not path.is_file():
        return AccountState(
            bom_equity=ACCOUNT_START,
            current_equity=ACCOUNT_START,
            asof=date.today().isoformat(),
            notes="Missing live_style_account.json — using $250k defaults.",
            source="default",
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AccountState(
            bom_equity=ACCOUNT_START,
            current_equity=ACCOUNT_START,
            asof=date.today().isoformat(),
            notes="Unreadable live_style_account.json — using $250k defaults.",
            source="default",
        )
    bom = float(raw.get("bom_equity", ACCOUNT_START) or ACCOUNT_START)
    cur = float(raw.get("current_equity", bom) or bom)
    return AccountState(
        bom_equity=bom,
        current_equity=cur,
        asof=str(raw.get("asof") or date.today().isoformat()),
        notes=str(raw.get("notes") or ""),
        source=str(raw.get("source") or path.name),
    )


def save_account_state(state: AccountState, path: Path = ACCOUNT_JSON) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(state)
    payload["freeze"] = freeze_dict()
    payload["updated"] = datetime.now().isoformat(timespec="seconds")
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def ensure_account_json(path: Path = ACCOUNT_JSON) -> AccountState:
    """Create default account JSON if missing; always return current state."""
    if not path.is_file():
        st = AccountState(
            bom_equity=ACCOUNT_START,
            current_equity=ACCOUNT_START,
            asof=date.today().isoformat(),
            notes=(
                "Edit bom_equity (1st-of-month) and current_equity for live share sizing. "
                "BOM drives risk = min(1%, $50k). Current equity drives the 17.5% name lid."
            ),
            source="bootstrap",
        )
        save_account_state(st, path)
        return st
    return load_account_state(path)


def _load_ohlc(symbol: str, data_dir: Path = OHLCV_DIR) -> Optional[pd.DataFrame]:
    key = str(symbol).strip().upper()
    if key in _OHLC_CACHE:
        return _OHLC_CACHE[key]
    path = data_dir / f"{key}.csv"
    if not path.is_file():
        _OHLC_CACHE[key] = None
        return None
    try:
        df = pd.read_csv(path)
    except OSError:
        _OHLC_CACHE[key] = None
        return None
    if "Date" not in df.columns or "Volume" not in df.columns:
        _OHLC_CACHE[key] = None
        return None
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"]).sort_values("Date")
    _OHLC_CACHE[key] = df
    return df


def lookup_adv20(
    symbol: str,
    asof: Optional[date] = None,
    data_dir: Path = OHLCV_DIR,
) -> tuple[Optional[float], str]:
    """Last ADV20 mean volume on or before asof."""
    key = str(symbol).strip().upper()
    if key not in _ADV_CACHE:
        rows: list[tuple[date, float]] = []
        df = _load_ohlc(key, data_dir)
        if df is not None and not df.empty:
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
    rows = _ADV_CACHE[key]
    if not rows:
        return None, "missing"
    if asof is None:
        return rows[-1][1], "full20"
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


def _fnum(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        x = float(str(v).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    return x


def entry_from_row(row: Mapping[str, Any]) -> Optional[float]:
    """Best single fill guess. Prefer a mid-band over the SB open floor.

    MUST_OPEN_ABOVE is the next-open floor (often equal to SIGNAL_LOW) — not a
    typical fill. MUST_OPEN_AT_OR_BELOW is the max fill, not a stop.
    """
    for k in (
        "ENTRY_PRICE",
        "ENTRY_OPEN_REF",
        "ENTRY_OPEN_BAND",
        "CLOSE",
        "TRIGGER_CLOSE",
        "CURRENT_PRICE",
        "PRIOR_DAY_CLOSE",
        "POC",
        "ZONE_HI",
    ):
        if k in row:
            x = _fnum(row.get(k))
            if x is not None and x > 0:
                return x
    lo, hi, _src = fill_band_from_row(row, stop=stop_from_row(row), lookup_ohlc=False)
    if lo is not None and hi is not None and lo > 0 and hi > 0:
        return (lo + hi) / 2.0
    for k in ("MIN_ENTRY_OPEN", "MUST_OPEN_ABOVE"):
        if k in row:
            x = _fnum(row.get(k))
            if x is not None and x > 0:
                return x
    return None


def stop_from_row(row: Mapping[str, Any]) -> Optional[float]:
    # MUST_OPEN_AT_OR_BELOW is the SB max fill, not a stop.
    for k in (
        "STOP_LOSS",
        "SIGNAL_LOW",
        "ZONE_LO",
        "SWING_LOW",
        "STOP_INITIAL",
        "StopInitial",
    ):
        if k in row:
            x = _fnum(row.get(k))
            if x is not None and x > 0:
                return x
    return None


def _valid_entry_above_stop(entry: float, stop: Optional[float]) -> Optional[float]:
    """Bump a fill that sits on the stop so risk_px is usable (SB floor = signal low)."""
    if entry is None or not math.isfinite(float(entry)) or float(entry) <= 0:
        return None
    entry_f = float(entry)
    if stop is None or not math.isfinite(float(stop)) or float(stop) <= 0:
        return entry_f
    stop_f = float(stop)
    if entry_f > stop_f:
        return entry_f
    bumped = max(stop_f * 1.002, stop_f + 0.01)
    return bumped if bumped > stop_f else None


def last_bar_hlc(
    symbol: str,
    asof: Optional[date] = None,
    data_dir: Path = OHLCV_DIR,
) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """Last High / Low / Close / ATR14 on or before asof."""
    df = _load_ohlc(symbol, data_dir)
    if df is None or df.empty:
        return None, None, None, None
    work = df
    if asof is not None:
        work = df[df["Date"].dt.date <= asof]
        if work.empty:
            work = df
    row = work.iloc[-1]
    high = _fnum(row.get("High"))
    low = _fnum(row.get("Low"))
    close = _fnum(row.get("Close"))
    atr: Optional[float] = None
    if "High" in work.columns and "Low" in work.columns and "Close" in work.columns:
        prev_close = work["Close"].shift(1)
        tr = pd.concat(
            [
                work["High"] - work["Low"],
                (work["High"] - prev_close).abs(),
                (work["Low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr_s = tr.rolling(14, min_periods=14).mean()
        try:
            av = float(atr_s.iloc[-1])
            if math.isfinite(av) and av > 0:
                atr = av
        except (TypeError, ValueError, IndexError):
            atr = None
    return high, low, close, atr


def fill_band_from_row(
    row: Mapping[str, Any],
    *,
    stop: Optional[float] = None,
    symbol: str = "",
    asof: Optional[date] = None,
    data_dir: Path = OHLCV_DIR,
    lookup_ohlc: bool = True,
) -> tuple[Optional[float], Optional[float], str]:
    """Min/max fill prices for a suggested-share range (watchlist, pre-fill)."""
    lo = _fnum(row.get("MIN_ENTRY_OPEN"))
    hi = _fnum(row.get("MAX_ENTRY_OPEN"))
    if lo and hi and lo > 0 and hi > 0:
        return min(lo, hi), max(lo, hi), "min_max_entry"

    lo = _fnum(row.get("MUST_OPEN_ABOVE"))
    hi = _fnum(row.get("MUST_OPEN_AT_OR_BELOW"))
    if lo and hi and lo > 0 and hi > 0:
        return min(lo, hi), max(lo, hi), "must_open_band"

    zlo = _fnum(row.get("ZONE_LO"))
    zhi = _fnum(row.get("ZONE_HI"))
    poc = _fnum(row.get("POC"))
    if zlo and zlo > 0 and ((zhi and zhi > 0) or (poc and poc > 0)):
        hi_z = zhi if zhi and zhi > 0 else float(poc)
        return min(zlo, hi_z), max(zlo, hi_z), "zone_poc"

    day_lo = _fnum(row.get("LOW") or row.get("DAY_LOW"))
    day_hi = _fnum(row.get("HIGH") or row.get("DAY_HIGH"))
    if day_lo and day_hi and day_lo > 0 and day_hi > 0:
        return min(day_lo, day_hi), max(day_lo, day_hi), "day_range"

    close = None
    for k in ("CLOSE", "TRIGGER_CLOSE", "CURRENT_PRICE", "PRIOR_DAY_CLOSE", "ENTRY_OPEN_BAND"):
        close = _fnum(row.get(k))
        if close and close > 0:
            break
    atr = _fnum(row.get("ATR") or row.get("ATR14"))
    if close and close > 0 and atr and atr > 0:
        return max(close - atr, 0.01), close + atr, "close_atr"

    if lookup_ohlc and symbol:
        oh, ol, oc, oatr = last_bar_hlc(symbol, asof=asof, data_dir=data_dir)
        if oh and ol and oh > 0 and ol > 0 and oh != ol:
            return min(ol, oh), max(ol, oh), "ohlc_hl"
        px = oc or close
        if px and px > 0 and oatr and oatr > 0:
            return max(px - oatr, 0.01), px + oatr, "ohlc_atr"
        if px and px > 0:
            return px * 0.99, px * 1.01, "ohlc_1pct"

    if close and close > 0:
        return close * 0.99, close * 1.01, "close_1pct"

    if stop and stop > 0:
        bumped = _valid_entry_above_stop(float(stop), stop)
        if bumped:
            hi_guess = bumped * 1.08
            return bumped, hi_guess, "stop_plus"

    return None, None, "missing"


def format_shares_range(a: Optional[float], b: Optional[float]) -> str:
    vals = [v for v in (a, b) if v is not None and math.isfinite(float(v)) and float(v) > 0]
    if not vals:
        return "—"
    lo = int(round(min(vals)))
    hi = int(round(max(vals)))
    if lo <= 0 and hi <= 0:
        return "—"
    if lo <= 0:
        return f"{hi:,}"
    if lo == hi:
        return f"{lo:,}"
    return f"{lo:,}–{hi:,}"


def size_trade(
    *,
    symbol: str,
    system: str,
    entry: float,
    stop: Optional[float],
    bom_equity: float,
    current_equity: float,
    open_notional_same_name: float = 0.0,
    asof: Optional[date] = None,
    data_dir: Path = OHLCV_DIR,
) -> SizeResult:
    """Compute suggested shares under the locked live-style freeze."""
    sym = str(symbol).strip().upper()
    sys_u = str(system).strip().upper()
    rd = risk_dollar(bom_equity)
    base = SizeResult(
        symbol=sym,
        system=sys_u,
        entry=float(entry) if entry else 0.0,
        stop=float(stop) if stop else 0.0,
        risk_dollar=rd,
        shares=0.0,
        notional=0.0,
        adv20=None,
        shares_risk=0.0,
        shares_adv=0.0,
        shares_name=0.0,
        binding_lid="",
        sized=False,
    )
    if entry is None or not math.isfinite(float(entry)) or float(entry) <= 0:
        base.skip_reason = "bad_entry"
        return base
    entry_f = float(entry)

    # 1) Risk / RSI slot → raw shares
    if sys_u == "RSI":
        invested = rd / RSI_AVG_LOSS_FRAC
        shares_risk = invested / entry_f
        base.details["rsi_slot"] = invested
    else:
        if stop is None or not math.isfinite(float(stop)) or float(stop) <= 0:
            base.skip_reason = "stop_missing"
            return base
        stop_f = float(stop)
        base.stop = stop_f
        risk_px = entry_f - stop_f
        if risk_px <= 0:
            base.skip_reason = "stop_ge_entry"
            return base
        shares_risk = rd / risk_px
        invested = shares_risk * entry_f
    base.shares_risk = shares_risk

    # 2) ADV clip
    adv, adv_src = lookup_adv20(sym, asof=asof, data_dir=data_dir)
    base.adv20 = adv
    base.details["adv_src"] = adv_src
    if adv is None or adv <= 0:
        base.skip_reason = "adv_missing"
        return base
    shares_adv = ADV_FRAC * float(adv)
    base.shares_adv = shares_adv

    # 3) Name cap room
    room = max(
        0.0,
        NAME_CAP_FRAC * max(float(current_equity), 0.0)
        - max(float(open_notional_same_name), 0.0),
    )
    shares_name = room / entry_f if entry_f > 0 else 0.0
    base.shares_name = shares_name
    if room < MIN_DEPLOY:
        base.skip_reason = "name_cap_empty"
        base.binding_lid = "name_cap"
        return base

    shares = min(shares_risk, shares_adv, shares_name)
    if shares <= 0 or not math.isfinite(shares):
        base.skip_reason = "bad_size"
        return base

    # Binding lid label
    eps = 1e-9
    if abs(shares - shares_name) <= eps * max(1.0, shares_name):
        lid = "name_cap"
    elif abs(shares - shares_adv) <= eps * max(1.0, shares_adv):
        lid = "adv"
    elif float(bom_equity) * RISK_FRAC >= MAX_RISK_DOLLAR - 1e-6:
        lid = "risk_50k"
    else:
        lid = "risk_1pct"

    notional = shares * entry_f
    base.shares = shares
    base.notional = notional
    base.binding_lid = lid
    base.sized = notional >= MIN_DEPLOY
    if not base.sized:
        base.skip_reason = "below_min_deploy"
    return base


def open_notional_by_symbol(
    lots: list[Any],
    *,
    qty_attr: str = "qty",
    entry_attr: str = "buy_price",
    symbol_attr: str = "symbol",
) -> dict[str, float]:
    """Sum open cost notional by ticker from Lot-like objects or dicts."""
    out: dict[str, float] = {}
    for lot in lots:
        if isinstance(lot, Mapping):
            sym = str(lot.get(symbol_attr) or lot.get("SYMBOL") or "").strip().upper()
            qty = _fnum(lot.get(qty_attr) or lot.get("qty") or lot.get("Quantity")) or 0.0
            px = _fnum(lot.get(entry_attr) or lot.get("buy_price") or lot.get("Entry")) or 0.0
        else:
            sym = str(getattr(lot, symbol_attr, "") or "").strip().upper()
            qty = float(getattr(lot, qty_attr, 0) or 0)
            px = float(getattr(lot, entry_attr, 0) or 0)
        if not sym or qty <= 0 or px <= 0:
            continue
        out[sym] = out.get(sym, 0.0) + abs(qty) * px
    return out


def size_share_range(
    *,
    symbol: str,
    system: str,
    row: Mapping[str, Any],
    bom_equity: float,
    current_equity: float,
    open_notional_same_name: float = 0.0,
    asof: Optional[date] = None,
    data_dir: Path = OHLCV_DIR,
) -> dict[str, Any]:
    """Size at the fill-band edges. Watchlist shows a range until the paid fill."""
    stop = stop_from_row(row)
    lo, hi, band_src = fill_band_from_row(
        row,
        stop=stop,
        symbol=symbol,
        asof=asof,
        data_dir=data_dir,
        lookup_ohlc=True,
    )
    mid = entry_from_row(row)
    sys_u = str(system).strip().upper()
    needs_stop = sys_u != "RSI"

    def _size_at(px: Optional[float]) -> SizeResult:
        use = _valid_entry_above_stop(float(px), stop) if px is not None and needs_stop else px
        if use is None:
            return size_trade(
                symbol=symbol,
                system=system,
                entry=0.0,
                stop=stop,
                bom_equity=bom_equity,
                current_equity=current_equity,
                open_notional_same_name=open_notional_same_name,
                asof=asof,
                data_dir=data_dir,
            )
        return size_trade(
            symbol=symbol,
            system=system,
            entry=float(use),
            stop=stop,
            bom_equity=bom_equity,
            current_equity=current_equity,
            open_notional_same_name=open_notional_same_name,
            asof=asof,
            data_dir=data_dir,
        )

    res_lo = _size_at(lo)
    res_hi = _size_at(hi)
    res_mid = _size_at(mid if mid is not None else ((lo + hi) / 2.0 if lo and hi else lo or hi))
    sized = [r for r in (res_lo, res_hi, res_mid) if r.sized and r.shares > 0]
    shares_lo = min(r.shares for r in sized) if sized else None
    shares_hi = max(r.shares for r in sized) if sized else None
    best = res_mid if res_mid.sized else (sized[0] if sized else res_mid)
    skip = best.skip_reason or res_lo.skip_reason or res_hi.skip_reason
    shares_txt = format_shares_range(shares_lo, shares_hi)
    if shares_txt == "—" and skip:
        shares_txt = "—"
    notional_vals = [r.notional for r in sized]
    if len(notional_vals) >= 2:
        nlo, nhi = min(notional_vals), max(notional_vals)
        notional_txt = f"{nlo:,.0f}–{nhi:,.0f}"
    elif notional_vals:
        notional_txt = f"{notional_vals[0]:,.2f}"
    else:
        notional_txt = "—"
    lid = best.binding_lid or skip or "—"
    if shares_lo and shares_hi and int(round(shares_lo)) != int(round(shares_hi)):
        lid = f"range:{lid}" if lid and lid != "—" else "range"
    return {
        "SUGGESTED_SHARES": shares_txt,
        "SUGGESTED_NOTIONAL": notional_txt,
        "RISK_DOLLAR": f"{best.risk_dollar:,.2f}",
        "ADV20": f"{best.adv20:,.0f}" if best.adv20 and best.adv20 > 0 else "—",
        "SIZE_LID": lid,
        "FILL_BAND": (
            f"{lo:.2f}–{hi:.2f}" if lo and hi else (f"{mid:.2f}" if mid else "—")
        ),
        "FILL_BAND_SRC": band_src,
        "skip_reason": skip,
    }


def enrich_scan_dataframe(
    df: pd.DataFrame,
    *,
    system: str,
    account: Optional[AccountState] = None,
    open_notional: Optional[Mapping[str, float]] = None,
    data_dir: Path = OHLCV_DIR,
    asof: Optional[date] = None,
) -> pd.DataFrame:
    """Add SUGGESTED_SHARES range / RISK_DOLLAR / ADV20 / SIZE_LID columns."""
    if df is None or getattr(df, "empty", True):
        return df
    acct = account or ensure_account_json()
    open_map = dict(open_notional or {})
    work = df.copy()
    shares_c: list[str] = []
    notional_c: list[str] = []
    risk_c: list[str] = []
    adv_c: list[str] = []
    lid_c: list[str] = []
    for _, row in work.iterrows():
        sym = str(row.get("SYMBOL", row.get("Symbol", ""))).strip().upper()
        packed = size_share_range(
            symbol=sym,
            system=system,
            row=row,
            bom_equity=acct.bom_equity,
            current_equity=acct.current_equity,
            open_notional_same_name=float(open_map.get(sym, 0.0)),
            asof=asof,
            data_dir=data_dir,
        )
        shares_c.append(packed["SUGGESTED_SHARES"])
        notional_c.append(packed["SUGGESTED_NOTIONAL"])
        risk_c.append(packed["RISK_DOLLAR"])
        adv_c.append(packed["ADV20"])
        lid_c.append(packed["SIZE_LID"])
    work["SUGGESTED_SHARES"] = shares_c
    work["SUGGESTED_NOTIONAL"] = notional_c
    work["RISK_DOLLAR"] = risk_c
    work["ADV20"] = adv_c
    work["SIZE_LID"] = lid_c
    return work


# --- Published-page helpers (investment / monthly / system_performance) ---

TABLE_UNCAP_CSS = """
/* table-uncap: fill the window; no 1200/1280/1420 body cap.
   Tables grow with column content (min-width: max-content) and scroll
   horizontally inside .table-wrap so nowrap header click targets stay intact.
   overflow:visible + min-width:0 squeezed <th> boxes while painting overflow
   text — header clicks then missed the real cell. */
body { max-width: none !important; width: auto; }
.shell { max-width: none !important; }
.table-wrap {
  width: 100%;
  max-height: none !important;
  overflow-x: auto !important;
  overflow-y: visible;
  -webkit-overflow-scrolling: touch;
}
table, table.sortable { width: max-content; min-width: 100%; }
th.sortable-th { position: relative; z-index: 3; pointer-events: auto; }
"""

FREEZE_SUMMARY = REPO / "drive" / "paul_experiments" / FREEZE_STAMP / "summary.json"
FREEZE_MONTHLY_HTML = REPO / "drive" / "paul_experiments" / FREEZE_STAMP / "monthly.html"
NOWIRE_CACHE = REPO / "drive" / "paul_experiments" / FREEZE_STAMP / "nowire_vs_spy.json"
STARTDATES_COMPARE = (
    REPO / "drive" / "paul_experiments" / "live_style_startdates_20260918" / "compare.html"
)
SPY_CSV = OHLCV_DIR / "SPY.csv"
WALLET_START = date(2010, 1, 1)
# Leftover pin — official mix was five sleeves until 2026-09-22 DailyRun wire.
FIVE_SYS_WALLET = ("SB", "RSI", "VZ", "MTS", "RL")
# Official live-style mix (DailyRun wire 2026-09-22). Indicators (IND) out.
# Fill-order rank: WRL after the five (RL → MTS → SB → VZ → RSI → WRL).
SIX_SYS_WALLET = ("SB", "RSI", "VZ", "MTS", "RL", "WRL")
OFFICIAL_WALLET = SIX_SYS_WALLET
WRL_UNIVERSE_29: tuple[str, ...] = (
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
# Published leftover 5-sys no-wire pin (system_performance vs-SPY headline before 6-sys).
PIN_5SYS_NOWIRE = {
    "eq_2010": 400_050.0,
    "eq_2011": 719_315.0,
    "eq_2012": 938_067.0,
    "end": 64_749_245.0,
    "max_dd_pct": 10.42,
    "ann_ror": 0.3945,
    "label": "Leftover 5-sys pin (no-wire; SB/RSI/VZ/MTS/RL)",
    "source": "docs/system_performance.html live-style $250k vs SPY before 6-sys adopt",
}
PIN_5SYS_WIRED = {
    "eq_2010": 284_646.36,
    "eq_2011": 392_517.79,
    "eq_2012": 422_474.98,
    "end": 58_700_020.87,
    "max_dd_pct": 20.59,
    "label": "Leftover 5-sys pin (with $7,500/mo wires)",
    "source": "docs/live_style.html / risk_1pct_50k_adv_17name_20260917",
}
NOWIRE_CACHE_6SYS = REPO / "drive" / "paul_experiments" / FREEZE_STAMP / "nowire_vs_spy_6sys.json"
WIRED_CACHE_6SYS = REPO / "drive" / "paul_experiments" / FREEZE_STAMP / "wired_vs_spy_6sys.json"


def load_freeze_summary() -> dict[str, Any]:
    if not FREEZE_SUMMARY.is_file():
        return {}
    try:
        return json.loads(FREEZE_SUMMARY.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def parse_live_style_month_ledger(year: int) -> list[dict[str, str]]:
    """Rows from the locked 17.5% wallet month ledger (official compound path)."""
    if not FREEZE_MONTHLY_HTML.is_file():
        return []
    try:
        html = FREEZE_MONTHLY_HTML.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    first = html.find("Month ledger")
    second = html.find("Month ledger", first + 1) if first >= 0 else -1
    part = html[second:] if second >= 0 else html[first:] if first >= 0 else html
    m = re.search(r'<table class="sortable">(.*?)</table>', part, flags=re.S)
    if not m:
        return []
    tbl = m.group(1)
    headers = [
        re.sub(r"<[^>]+>", "", th).strip()
        for th in re.findall(r"<th[^>]*>(.*?)</th>", tbl, flags=re.S)
    ]
    rows: list[dict[str, str]] = []
    prefix = f"{year:04d}-"
    for tr in re.findall(r"<tr>(.*?)</tr>", tbl, flags=re.S):
        cells = [
            re.sub(r"<[^>]+>", "", td).strip()
            for td in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, flags=re.S)
        ]
        if not cells or not cells[0].startswith(prefix):
            continue
        rows.append({headers[i] if i < len(headers) else str(i): cells[i] for i in range(len(cells))})
    return rows


def _money_to_float(text: object) -> Optional[float]:
    if text is None:
        return None
    raw = str(text).replace("$", "").replace(",", "").replace("+", "").replace("—", "").strip()
    if not raw:
        return None
    try:
        x = float(raw)
    except ValueError:
        return None
    if not math.isfinite(x):
        return None
    return x


def _calendar_month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def parse_live_style_eom_curve() -> list[tuple[date, float]]:
    """Month-end Closed-only equity from the locked 17.5% (with-wires) ledger."""
    if not FREEZE_MONTHLY_HTML.is_file():
        return []
    try:
        html = FREEZE_MONTHLY_HTML.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    first = html.find("Month ledger")
    second = html.find("Month ledger", first + 1) if first >= 0 else -1
    part = html[second:] if second >= 0 else html[first:] if first >= 0 else html
    m = re.search(r'<table class="sortable">(.*?)</table>', part, flags=re.S)
    if not m:
        return []
    tbl = m.group(1)
    headers = [
        re.sub(r"<[^>]+>", "", th).strip()
        for th in re.findall(r"<th[^>]*>(.*?)</th>", tbl, flags=re.S)
    ]
    eom_key = next((h for h in headers if "EOM" in h.upper() and "EQUITY" in h.upper()), None)
    month_key = next((h for h in headers if h.strip().lower() in {"month", "date"}), headers[0] if headers else None)
    if not eom_key or not month_key:
        return []
    out: list[tuple[date, float]] = []
    for tr in re.findall(r"<tr>(.*?)</tr>", tbl, flags=re.S):
        cells = [
            re.sub(r"<[^>]+>", "", td).strip()
            for td in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, flags=re.S)
        ]
        if not cells:
            continue
        row = {headers[i] if i < len(headers) else str(i): cells[i] for i in range(len(cells))}
        label = str(row.get(month_key) or "")
        if not re.match(r"^\d{4}-\d{2}$", label):
            continue
        y, mo = int(label[:4]), int(label[5:7])
        eq = _money_to_float(row.get(eom_key))
        if eq is None:
            continue
        out.append((_calendar_month_end(y, mo), eq))
    out.sort(key=lambda x: x[0])
    return out


def _ann_ror_equity(end_eq: float, start_eq: float, start: date, end: date) -> Optional[float]:
    years = max((end - start).days / 365.25, 1e-9)
    if start_eq <= 0 or years <= 0:
        return None
    if end_eq <= 0:
        return -1.0
    return (end_eq / start_eq) ** (1.0 / years) - 1.0


def _max_dd_pct_curve(points: list[tuple[date, float]]) -> float:
    peak = None
    worst = 0.0
    for _d, eq in points:
        if eq is None or not math.isfinite(eq):
            continue
        if peak is None or eq > peak:
            peak = eq
        if peak and peak > 0:
            dd = (eq / peak - 1.0) * 100.0
            if dd < worst:
                worst = dd
    return abs(worst)


def _load_spy_frame() -> Optional[pd.DataFrame]:
    if not SPY_CSV.is_file():
        return None
    try:
        df = pd.read_csv(SPY_CSV)
    except OSError:
        return None
    if "Date" not in df.columns:
        return None
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"]).sort_values("Date")
    close = pd.to_numeric(df.get("Close"), errors="coerce")
    adj = pd.to_numeric(df.get("Adj Close"), errors="coerce") if "Adj Close" in df.columns else None
    px = adj if adj is not None and adj.notna().sum() >= 2 else close
    df["px"] = px
    df = df.dropna(subset=["px"])
    df["d"] = df["Date"].dt.date
    return df[["d", "px"]].reset_index(drop=True)


def spy_250k_curve(
    start: date = WALLET_START,
    end: Optional[date] = None,
) -> dict[str, Any]:
    """S&P 500 tracker (SPY) $250k buy-and-hold, total return when Adj Close exists."""
    df = _load_spy_frame()
    if df is None or df.empty:
        return {}
    work = df[df["d"] >= start]
    if end is not None:
        work = work[work["d"] <= end]
    if len(work) < 2:
        return {}
    px0 = float(work["px"].iloc[0])
    if px0 <= 0:
        return {}
    start_d = work["d"].iloc[0]
    end_d = work["d"].iloc[-1]
    eq = ACCOUNT_START * work["px"].astype(float) / px0
    points = list(zip(work["d"].tolist(), [float(v) for v in eq.tolist()]))
    monthly: list[tuple[date, float]] = [(start_d, ACCOUNT_START)]
    work = work.copy()
    work["ym"] = [d.replace(day=1) for d in work["d"]]
    last_by_m = work.groupby("ym", as_index=False).last()
    for d, v in zip(last_by_m["d"], last_by_m["px"]):
        monthly.append((d, ACCOUNT_START * float(v) / px0))
    if monthly[-1][0] != end_d:
        monthly.append((end_d, float(eq.iloc[-1])))
    end_eq = float(eq.iloc[-1])
    return {
        "start": start_d.isoformat() if hasattr(start_d, "isoformat") else str(start_d),
        "end": end_d.isoformat() if hasattr(end_d, "isoformat") else str(end_d),
        "end_eq": end_eq,
        "ann_ror": _ann_ror_equity(end_eq, ACCOUNT_START, start_d, end_d),
        "max_dd_pct": _max_dd_pct_curve(points),
        "curve": monthly,
        "daily_n": int(len(points)),
        "series": (
            "SPY Adj Close total return (dividends reinvested)"
            if SPY_CSV.is_file() and "Adj Close" in set(pd.read_csv(SPY_CSV, nrows=0).columns)
            else "SPY close (price-only)"
        ),
    }


def _curve_from_snaps(snaps: list[Any], start_eq: float = ACCOUNT_START) -> list[tuple[date, float]]:
    out: list[tuple[date, float]] = [(WALLET_START, start_eq)]
    for s in snaps:
        y = int(getattr(s, "year", 0) or 0)
        mo = int(getattr(s, "month", 0) or 0)
        eq = float(getattr(s, "equity_end", 0.0) or 0.0)
        if y < 2010 or mo < 1:
            continue
        out.append((_calendar_month_end(y, mo), eq))
    out.sort(key=lambda x: x[0])
    return out


def _latest_in(folder: Path, pattern: str) -> Optional[Path]:
    if not folder.is_dir():
        return None
    hits = sorted(folder.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return hits[0] if hits else None


def _find_wrl_closed_for_wallet() -> Path:
    """House WRL Closed for the official 6-sys overlay (29-name EXIT_swing)."""
    drive = REPO / "drive"
    candidates = [
        REPO / "drive" / "paul_experiments" / "wrl_exitswing_univ29_20260922" / "EXIT_swing" / "WRL_LatestRun_Closed.csv",
        REPO / "drive" / "paul_experiments" / "wrl_exitswing_univ29_20260922" / "WRL_LatestRun_Closed.csv",
        drive / "WRL_LatestRun_Closed.csv",
        REPO / "drive" / "paul_experiments" / "wrl_wired_reports_preview_20260922" / "WRL_LatestRun_Closed.csv",
    ]
    for path in candidates:
        if path.is_file() and path.name.endswith(".csv") and "universe" not in path.name.lower():
            return path
    for folder in (
        REPO / "drive" / "paul_experiments" / "wrl_exitswing_univ29_20260922" / "EXIT_swing",
        REPO / "drive" / "paul_experiments" / "wrl_exitswing_univ29_20260922",
        drive,
    ):
        hit = _latest_in(folder, "WRL_Closed_*.csv")
        if hit is not None:
            return hit
    raise RuntimeError(
        "missing WRL Closed for official 6-sys wallet — run run_wrl.bat on WRL_universe.csv"
    )


def _load_wrl_overlay_trades(mod: Any) -> list[Any]:
    closed_path = _find_wrl_closed_for_wallet()
    folder = closed_path.parent
    open_path = folder / "WRL_LatestRun_Open.csv"
    if not open_path.is_file():
        open_path = _latest_in(folder, "WRL_Open_*.csv")
    raw_c = mod.r.load_closed_rows(closed_path, "WRL")
    raw_o = mod.r.load_open_rows(open_path, "WRL") if open_path else []
    keep = set(WRL_UNIVERSE_29)
    raw_c = [row for row in raw_c if str(row.get("symbol") or "").upper() in keep]
    raw_o = [row for row in raw_o if str(row.get("symbol") or "").upper() in keep]
    trades = [mod.r.overlay_one("WRL", row) for row in raw_c]
    trades.extend(mod.r.overlay_one("WRL", row) for row in raw_o)
    return trades


def _run_official_wallet(*, withdraw: bool, label: str) -> dict[str, Any]:
    """Official lids, six sleeves (5-sys + WRL). WRL fill-order after the five."""
    import importlib.util
    from copy import copy

    spec = importlib.util.spec_from_file_location(
        "risk2500_five_sys_20260917",
        REPO / "tools" / "risk2500_five_sys_20260917.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load risk2500_five_sys_20260917")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["risk2500_five_sys_20260917"] = mod
    spec.loader.exec_module(mod)
    static = list(mod.load_static(mod.FIVE))
    static.extend(_load_wrl_overlay_trades(mod))
    six_rank = {sys: i for i, sys in enumerate(tuple(mod.FIVE) + ("WRL",))}
    arm = mod._run_arm(
        [copy(t) for t in static],
        rank=six_rank,
        rotate="winner",
        withdraw=withdraw,
        label=label,
        risk_frac=RISK_FRAC,
        name_cap_frac=NAME_CAP_FRAC,
        max_risk_dollar=MAX_RISK_DOLLAR,
        adv_frac=ADV_FRAC,
    )
    led = arm["led"]
    snaps = arm.get("snaps") or []
    curve = _curve_from_snaps(snaps, ACCOUNT_START)
    through = getattr(mod, "ASOF", None) or (curve[-1][0] if curve else WALLET_START)
    if isinstance(through, str):
        through = date.fromisoformat(through)
    end_eq = float(led.end_equity)
    start_d = WALLET_START
    return {
        "stamp": FREEZE_STAMP,
        "mix": "6sys",
        "sleeves": list(OFFICIAL_WALLET),
        "rank": "RL → MTS → SB → VZ → RSI → WRL",
        "withdrawals": float(led.withdrawals),
        "asof": through.isoformat(),
        "start": start_d.isoformat(),
        "end": end_eq,
        "eq_2010": float(led.eq_2010),
        "eq_2011": float(led.eq_2011),
        "eq_2012": float(led.eq_2012),
        "max_dd_pct": float(led.max_dd_pct),
        "max_dd_peak": float(led.max_dd_peak),
        "max_dd_trough": float(led.max_dd_trough),
        "interest": float(led.interest),
        "n_fill": int(led.n_full) + int(led.n_scaled),
        "curve": [[d.isoformat(), eq] for d, eq in curve],
        "official": True,
        "wires": bool(withdraw),
    }


def _run_nowire_wallet() -> dict[str, Any]:
    """Official lids, $7,500/mo OFF. Official 6-sys overlay (5 + WRL)."""
    return _run_official_wallet(withdraw=False, label="live175_nowire_6sys")


def _pack_vs_spy(wallet: dict[str, Any], spy: dict[str, Any]) -> dict[str, Any]:
    end_eq = float(wallet.get("end") or 0.0)
    spy_end = float(spy.get("end_eq") or 0.0)
    asof = str(wallet.get("asof") or spy.get("end") or "")
    start_s = str(wallet.get("start") or WALLET_START.isoformat())
    try:
        start_d = date.fromisoformat(start_s[:10])
        end_d = date.fromisoformat(asof[:10]) if asof else start_d
    except ValueError:
        start_d, end_d = WALLET_START, WALLET_START
    ann = wallet.get("ann_ror")
    if ann is None:
        ann = _ann_ror_equity(end_eq, ACCOUNT_START, start_d, end_d)
    return {
        **wallet,
        "ann_ror": ann,
        "spy_end": spy_end,
        "spy_ann_ror": spy.get("ann_ror"),
        "spy_max_dd_pct": spy.get("max_dd_pct"),
        "spy_start": spy.get("start"),
        "spy_asof": spy.get("end"),
        "spy_series": spy.get("series"),
        "beat": end_eq - spy_end,
        "ann_ror_beat": (ann - spy["ann_ror"]) if ann is not None and spy.get("ann_ror") is not None else None,
    }


def leftover_5sys_nowire() -> dict[str, Any]:
    """Labeled leftover of the pre-adopt 5-sys no-wire pin. Not the official mix."""
    return dict(PIN_5SYS_NOWIRE)


def leftover_5sys_wired() -> dict[str, Any]:
    """Labeled leftover of the pre-adopt 5-sys with-wires pin."""
    return dict(PIN_5SYS_WIRED)


def ensure_nowire_vs_spy_cache(*, force: bool = False) -> dict[str, Any]:
    """No-wire official-lid 6-sys wallet vs SPY $250k. Cache beside the freeze stamp."""
    cache_path = NOWIRE_CACHE_6SYS
    if cache_path.is_file() and not force:
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached = {}
        if (
            cached.get("stamp") == FREEZE_STAMP
            and cached.get("mix") == "6sys"
            and cached.get("end")
            and cached.get("curve")
            and abs(float(cached.get("withdrawals") or 0.0)) < 1.0
        ):
            asof = cached.get("asof")
            try:
                end_d = date.fromisoformat(str(asof)[:10]) if asof else None
            except ValueError:
                end_d = None
            spy = spy_250k_curve(WALLET_START, end_d)
            pack = _pack_vs_spy(cached, spy)
            pack["curve"] = [
                (date.fromisoformat(d) if isinstance(d, str) else d, float(eq))
                for d, eq in (cached.get("curve") or [])
            ]
            return pack
    raw = _run_nowire_wallet()
    asof = raw.get("asof")
    try:
        end_d = date.fromisoformat(str(asof)[:10]) if asof else None
    except ValueError:
        end_d = None
    spy = spy_250k_curve(WALLET_START, end_d)
    pack = _pack_vs_spy(raw, spy)
    NOWIRE_CACHE_6SYS.parent.mkdir(parents=True, exist_ok=True)
    serial = dict(pack)
    serial["curve"] = raw["curve"]
    serial["mix"] = "6sys"
    NOWIRE_CACHE_6SYS.write_text(json.dumps(serial, indent=2), encoding="utf-8")
    pack["curve"] = [
        (date.fromisoformat(d) if isinstance(d, str) else d, float(eq))
        for d, eq in raw["curve"]
    ]
    return pack


def load_wired_vs_spy() -> dict[str, Any]:
    """Official 6-sys freeze path (includes $7,500/mo wires) vs same-window SPY $250k.

    Prefers the 6-sys wired cache. If missing, returns the leftover 5-sys
    with-wires pin so published reports do not block on a long re-run.
    """
    if WIRED_CACHE_6SYS.is_file():
        try:
            cached = json.loads(WIRED_CACHE_6SYS.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached = {}
        if cached.get("mix") == "6sys" and cached.get("end"):
            asof = cached.get("asof")
            try:
                end_d = date.fromisoformat(str(asof)[:10]) if asof else None
            except ValueError:
                end_d = None
            spy = spy_250k_curve(WALLET_START, end_d)
            pack = _pack_vs_spy(cached, spy)
            curve = cached.get("curve") or []
            pack["curve"] = [
                (date.fromisoformat(d) if isinstance(d, str) else d, float(eq))
                for d, eq in curve
            ]
            return pack
    # Do not block published reports on a long 6-sys wired re-run. Leftover
    # 5-sys with-wires pin stays visible; official vs-SPY headline is no-wire 6-sys.
    pin = leftover_5sys_wired()
    asof = date(2026, 9, 17)
    spy = spy_250k_curve(WALLET_START, asof)
    wallet = {
        "stamp": FREEZE_STAMP,
        "mix": "5sys_leftover_wired",
        "withdrawals": 7_500.0,
        "asof": asof.isoformat(),
        "start": WALLET_START.isoformat(),
        "end": float(pin["end"]),
        "eq_2010": pin.get("eq_2010"),
        "eq_2011": pin.get("eq_2011"),
        "eq_2012": pin.get("eq_2012"),
        "max_dd_pct": pin.get("max_dd_pct"),
        "curve": [],
        "official": False,
        "wires": True,
        "leftover": True,
    }
    return _pack_vs_spy(wallet, spy)


def official_live_style_callout_html() -> str:
    """Green official-sizing note for published pages (no What-you-asked block)."""
    return (
        '<div class="ask live-style-official" style="margin:16px 0;padding:14px 16px;'
        'background:#f0fdf4;border:1px solid #86efac;border-radius:10px;">'
        '<h2 style="margin:0 0 8px;font-size:1.05rem;color:#166534;">'
        "Official live-style sizing + compound growth</h2>"
        '<p style="margin:0 0 8px;font-size:14px;line-height:1.45;">'
        "Live buy size (every getTarget system, including RS / BRT / YH / WPBR — not only 6-sys): "
        "risk = min(1% beginning-of-month equity, $50k), "
        "shares ≤ 1% ADV20, notional ≤ 17.5% of current equity. "
        "The $250k vs S&amp;P 500 (SPY) wallet below is the official six-sleeve compound book "
        "(StockBee, Relative Strength Index, Volume Zone, Magic Touch, Rocket Launcher, "
        "Weekly Range / Swing; Indicators out). DailyRun wire / official mix change — not gold. "
        "Old five-sleeve pin is leftover only. "
        "Uses official shares × house Closed fill prices — not dummy $10k / $47.5k notionals. "
        'See <a href="live_style.html"><strong>compound growth (live-style)</strong></a> '
        '· <a href="live_style_monthly.html">wallet monthly</a> '
        '· <a href="investment.html">investment report Suggested shares / avg-cost lots</a>. '
        "Engine Closed rows further down still use house dummy notionals for reconcile."
        "</p></div>"
    )

