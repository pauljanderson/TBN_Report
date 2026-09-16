"""RSI — Relative Strength Index (TBN mode ``rsi_mode``).

Not the RS (Relative Strength vs SPY) system. RSI here is Wilder's Relative
Strength Index (14): a name runs hot (RSI >= 70), cools (trigger RSI < 60),
and is bought at the next open if ATR% is high enough — then sold when RSI
is hot again, or flattened by a calendar time stop.

Outputs: ``drive/RSI_*_<stamp>.csv`` (Closed / Open / Watchlist / Summary /
Summary_Symbols / Report / Audit_Report / EquityCurve / EquityMeta /
Correlation / Correlation_Pairs). Host: ``rocket_tbn.py``.

Research provenance: ``tools/rsi_ob_neutral_rsi70_atr6_ts20_maxrsi60_ab_20260911.py``
and stamp ``drive/paul_experiments/rsi_ob_neutral_rsi70_atr6_ts20_maxrsi60_20260911/``.
Adopt stamp: ``drive/paul_experiments/rsi_atr5_dailyrun_20260914/``
(prior sleeve adopt: ``drive/paul_experiments/rsi_tbn_adopt_20260911/``).

Status: **DailyRun official TBN sleeve** — not walk-forward gold.
"""
from __future__ import annotations

import csv
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, fields, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

try:
    from tbn_host_sizing import (
        HostSizingConfig,
        apply_host_dollar_scale,
        audit_display_brt_cash,
        compute_and_write_host_equity,
    )
except ImportError:
    from stock_analysis.tbn_host_sizing import (  # type: ignore
        HostSizingConfig,
        apply_host_dollar_scale,
        audit_display_brt_cash,
        compute_and_write_host_equity,
    )

FILE_PREFIX = "RSI"

# Upper bound on RSI_Summary rows for the house universe (run_rsi.bat default).
# Anything larger is an ALL / research replay and must not steal the house pin.
RSI_HOUSE_SUMMARY_MAX = 200


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class RsiConfig:
    rsi_mode: bool = True
    rsi_ob: float = 70.0  # "was hot" threshold that arms the setup
    rsi_os: float = 30.0  # Neutral band floor (below = oversold, not a buy here)
    rsi_exit: float = 70.0  # sell when RSI reaches this again
    rsi_max_trigger: float = 60.0  # entry gate: trigger RSI must be under this
    rsi_min_atr_pct: float = 5.0  # entry gate: ATR14 / close * 100 at trigger
    rsi_time_stop_days: int = 20  # calendar days from entry; 0 = off
    rsi_entry_on: str = "next_open"  # next_open (house) | close
    rsi_sheet_notional: float = 10_000.0
    symbol_reentry_cooldown_days: int = 0
    entry_start_date: str = ""
    entry_end_date: str = ""
    brt_cash: float = 10_000.0


def rsi_config_from_brt(cfg: Any) -> RsiConfig:
    kw: dict[str, Any] = {}
    for f in fields(RsiConfig):
        if hasattr(cfg, f.name):
            kw[f.name] = getattr(cfg, f.name)
    rcfg = RsiConfig(**kw)
    notional = float(getattr(cfg, "rsi_sheet_notional", 0) or 0)
    if notional > 0:
        rcfg.brt_cash = notional
    return rcfg


def _rsi_cfg_dict(cfg: RsiConfig) -> dict[str, Any]:
    return {f.name: getattr(cfg, f.name) for f in fields(RsiConfig)}


def _rsi_cfg_from_dict(d: dict[str, Any]) -> RsiConfig:
    return RsiConfig(**{f.name: d[f.name] for f in fields(RsiConfig) if f.name in d})


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


@dataclass
class RsiClosedRow:
    symbol: str
    side: str
    date_opened: str
    entry_price: float
    stop_price: float
    target_price: float
    date_closed: str
    exit_price: float
    exit_type: str
    days_held: int
    pnl_pct: float
    pnl_dollars: float
    ann_ror_pct: float
    max_price: float
    signal_date: str
    entry_on: str
    rsi_trigger: float
    rsi_exit: float
    prior_ob_rsi: float
    rsi_drop_from_ob: float
    atr_pct_at_trigger: float
    dist_to_52w_high_pct_at_trigger: float
    rel_vol_at_trigger: float
    close_vs_sma50_pct_at_trigger: float
    max_rsi_trigger: float
    min_atr_pct: float
    time_stop_days: int
    exit_rsi_level: float
    one_liner: str

    def to_csv_row(self) -> list[str]:
        return [
            self.symbol,
            self.side,
            self.date_opened,
            f"{self.entry_price:.4f}",
            f"{self.stop_price:.4f}",
            f"{self.target_price:.4f}",
            self.date_closed,
            f"{self.exit_price:.4f}",
            self.exit_type,
            str(self.days_held),
            f"{self.pnl_pct:.4f}",
            f"{self.pnl_dollars:.2f}",
            f"{self.ann_ror_pct:.2f}",
            f"{self.max_price:.4f}",
            self.signal_date,
            self.entry_on,
            _fmt_opt(self.rsi_trigger),
            _fmt_opt(self.rsi_exit),
            _fmt_opt(self.prior_ob_rsi),
            _fmt_opt(self.rsi_drop_from_ob),
            _fmt_opt(self.atr_pct_at_trigger),
            _fmt_opt(self.dist_to_52w_high_pct_at_trigger),
            _fmt_opt(self.rel_vol_at_trigger, 3),
            _fmt_opt(self.close_vs_sma50_pct_at_trigger),
            f"{self.max_rsi_trigger:g}",
            f"{self.min_atr_pct:g}",
            str(self.time_stop_days),
            f"{self.exit_rsi_level:g}",
            self.one_liner,
        ]


RSI_CLOSED_HEADER = [
    "SYMBOL",
    "SIDE",
    "DATE_OPENED",
    "ENTRY_PRICE",
    "STOP_PRICE",
    "TARGET_PRICE",
    "DATE_CLOSED",
    "EXIT_PRICE",
    "EXIT_TYPE",
    "DAYS_HELD",
    "PNL_PCT",
    "PNL_DOLLARS",
    "ANN_ROR_PCT",
    "MAX_PRICE",
    "SIGNAL_DATE",
    "ENTRY_ON",
    "RSI14_AT_TRIGGER",
    "RSI14_AT_EXIT",
    "PRIOR_OB_RSI14",
    "RSI14_DROP_FROM_OB",
    "ATR_PCT_AT_TRIGGER",
    "DIST_TO_52W_HIGH_PCT_AT_TRIGGER",
    "REL_VOL_ON_TRIGGER",
    "CLOSE_VS_SMA50_PCT_AT_TRIGGER",
    "MAX_RSI_TRIGGER",
    "MIN_ATR_PCT",
    "TIME_STOP_DAYS",
    "EXIT_RSI_LEVEL",
    "ONE_LINER",
]

RSI_OPEN_HEADER = [
    "SYMBOL",
    "DATE_OPENED",
    "ENTRY_PRICE",
    "CURRENT_PRICE",
    "PNL_PCT",
    "DAYS_OPEN",
    "CALENDAR_DAYS_OPEN",
    "RSI14_NOW",
    "RSI14_AT_TRIGGER",
    "ATR_PCT_AT_TRIGGER",
    "EXIT_RSI_LEVEL",
    "TIME_STOP_DAYS",
    "TIME_STOP_DATE",
    "DAYS_TO_TIME_STOP",
    "SIGNAL_DATE",
    "EXIT_HINT",
]

RSI_WATCHLIST_HEADER = [
    "SYMBOL",
    "ASOF_DATE",
    "ROW_TYPE",
    "STATUS",
    "CLOSE",
    "RSI14",
    "PRIOR_OB_RSI14",
    "ATR_PCT",
    "MAX_RSI_TRIGGER",
    "MIN_ATR_PCT",
    "EXIT_RSI_LEVEL",
    "TIME_STOP_DAYS",
    "TRIGGER_HINT",
]


def _fmt_opt(x: Any, digits: int = 2) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return ""
    if not np.isfinite(v):
        return ""
    return f"{v:.{digits}f}"


def _iso(d: Any) -> str:
    if hasattr(d, "strftime"):
        return d.strftime("%Y%m%d")
    return str(d)[:10].replace("-", "")


def _iso_dash(d: Any) -> str:
    s = _iso(d)
    if len(s) >= 8:
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def _entry_date_allowed(iso: str, start: str, end: str) -> bool:
    s = (start or "").strip().replace("-", "")[:8]
    e = (end or "").strip().replace("-", "")[:8]
    if s and iso < s:
        return False
    if e and iso > e:
        return False
    return True


def _calendar_days(d1: str, d2: str) -> int:
    def _ep(d: str) -> int:
        t = time.struct_time((int(d[:4]), int(d[4:6]), int(d[6:8]), 0, 0, 0, 0, 0, -1))
        return int(time.mktime(t))

    return int((_ep(d2) - _ep(d1)) / 86400)


def _is_rsi_house_universe(universe_label: str, summary_path: Path) -> bool:
    """True for house / run_rsi.bat default — not ALL / research CSVs.

    Size fallback is a tight band around the 149-name house so an 80-name
    research list cannot steal ``RSI_house_last_run_ts.txt``.
    """
    label = str(universe_label or "").replace("\\", "/").lower()
    if label in ("*", "all") or " all " in f" {label} ":
        return False
    if "rsi_universe.csv" in label or "rsin_highfit_isgood" in label:
        return True
    if "paulscore" in label or "research" in label:
        return False
    try:
        n = sum(1 for _ in summary_path.open(encoding="utf-8")) - 1
    except OSError:
        return False
    return 120 <= n <= 180


# ---------------------------------------------------------------------------
# Features (port of tools/rsi_ob_neutral_..._ab_20260911.py::features)
# ---------------------------------------------------------------------------


def compute_features(df: pd.DataFrame, cfg: RsiConfig) -> dict[str, np.ndarray]:
    try:
        from rocket_tbn import _compute_atr_14_arr, _wilder_rsi14_arr
    except ImportError:
        from stock_analysis.rocket_tbn import (  # type: ignore
            _compute_atr_14_arr,
            _wilder_rsi14_arr,
        )

    close = df["Close"].to_numpy(dtype=np.float64)
    high = df["High"].to_numpy(dtype=np.float64)
    low = df["Low"].to_numpy(dtype=np.float64)
    if "Volume" in df.columns:
        vol = df["Volume"].to_numpy(dtype=np.float64)
    else:
        vol = np.full(len(close), np.nan, dtype=np.float64)
    n = len(close)
    rsi = _wilder_rsi14_arr(close)
    atr = _compute_atr_14_arr(high, low, close, 14)
    atr_pct = np.where((close > 0) & np.isfinite(atr), atr / close * 100.0, np.nan)
    close_s = pd.Series(close)
    sma50 = close_s.rolling(50, min_periods=50).mean().to_numpy()
    sma50_pct = np.where(
        (sma50 > 0) & np.isfinite(close), (close / sma50 - 1.0) * 100.0, np.nan
    )
    hi52 = pd.Series(high).rolling(252, min_periods=20).max().to_numpy()
    dist52 = np.where((hi52 > 0) & np.isfinite(close), (1.0 - close / hi52) * 100.0, np.nan)
    avg10 = pd.Series(vol).rolling(10, min_periods=5).mean().to_numpy()
    rel_vol = np.where((avg10 > 0) & np.isfinite(vol), vol / avg10, np.nan)
    ob = float(cfg.rsi_ob)
    prior_ob = np.full(n, np.nan)
    last = np.nan
    for i in range(n):
        if np.isfinite(rsi[i]) and rsi[i] >= ob:
            last = rsi[i]
        prior_ob[i] = last
    return {
        "close": close,
        "open": df["Open"].to_numpy(dtype=np.float64),
        "high": high,
        "rsi": rsi,
        "atr_pct": atr_pct,
        "sma50_pct": sma50_pct,
        "dist52": dist52,
        "rel_vol": rel_vol,
        "prior_ob": prior_ob,
    }


def gate_ok(cfg: RsiConfig, i: int, feat: dict[str, np.ndarray]) -> tuple[bool, str]:
    """Entry gates at the trigger bar. Returns (passed, first_failure_reason)."""
    rsi = feat["rsi"][i]
    if not np.isfinite(rsi):
        return False, "RSI14 not available"
    if rsi >= float(cfg.rsi_max_trigger):
        return False, f"trigger RSI {rsi:.1f} >= max_trigger {float(cfg.rsi_max_trigger):g}"
    min_atr = float(cfg.rsi_min_atr_pct or 0.0)
    if min_atr > 0:
        a = feat["atr_pct"][i]
        if not np.isfinite(a):
            return False, "ATR% not available"
        if a < min_atr:
            return False, f"ATR% {a:.2f} < min_atr_pct {min_atr:g}"
    return True, ""


# ---------------------------------------------------------------------------
# Per-symbol backtest
# ---------------------------------------------------------------------------


def backtest_symbol(
    symbol: str,
    df: pd.DataFrame,
    cfg: RsiConfig,
) -> tuple[list[RsiClosedRow], list[dict[str, Any]], list[dict[str, Any]]]:
    """Prior bar overbought + today Neutral (gated) -> buy next open; sell back at RSI>=exit."""
    closed: list[RsiClosedRow] = []
    open_rows: list[dict[str, Any]] = []
    watch: list[dict[str, Any]] = []
    n = len(df) if df is not None else 0
    if n < 30:
        return closed, open_rows, watch

    feat = compute_features(df, cfg)
    dates = df.index
    open_ = feat["open"]
    close = feat["close"]
    high = feat["high"]
    rsi = feat["rsi"]
    cash = float(cfg.brt_cash)
    ob = float(cfg.rsi_ob)
    os_ = float(cfg.rsi_os)
    exit_rsi = float(cfg.rsi_exit)
    time_stop = int(cfg.rsi_time_stop_days or 0)
    entry_on_close = str(cfg.rsi_entry_on or "next_open").strip().lower() == "close"

    prev_rsi = np.roll(rsi, 1)
    prev_rsi[0] = np.nan
    buy_base = (prev_rsi >= ob) & (rsi > os_) & (rsi < ob)

    pos: dict[str, Any] | None = None
    pending_entry_i = -1
    pending_exit = False
    pending_exit_type = "OVERBOUGHT"
    pending_exit_rsi = float("nan")
    cooldown_until = ""

    def _open_position(entry_i: int, entry_px: float, signal_i: int) -> None:
        nonlocal pos
        pos = {
            "entry_i": entry_i,
            "entry_iso": _iso(dates[entry_i]),
            "entry": entry_px,
            "signal_i": signal_i,
            "signal_iso": _iso(dates[signal_i]),
            "max_price": max(entry_px, float(high[entry_i])),
            "rsi_trigger": float(rsi[signal_i]),
            "atr_pct": float(feat["atr_pct"][signal_i]),
            "prior_ob": float(feat["prior_ob"][signal_i]),
            "dist52": float(feat["dist52"][signal_i]),
            "rel_vol": float(feat["rel_vol"][signal_i]),
            "sma50_pct": float(feat["sma50_pct"][signal_i]),
        }

    def _close_position(exit_i: int, exit_px: float, exit_type: str, exit_rsi_val: float) -> None:
        nonlocal pos, cooldown_until
        assert pos is not None
        iso = _iso(dates[exit_i])
        entry = float(pos["entry"])
        pnl_pct = (exit_px / entry - 1.0) * 100.0 if entry > 0 else 0.0
        cal = max(1, _calendar_days(pos["entry_iso"], iso))
        ann = ((exit_px / entry) ** (365.0 / cal) - 1.0) * 100.0 if entry > 0 else 0.0
        shares = cash / entry if entry > 0 else 0.0
        prior_ob = float(pos["prior_ob"])
        trig = float(pos["rsi_trigger"])
        drop = prior_ob - trig if np.isfinite(prior_ob) and np.isfinite(trig) else float("nan")
        closed.append(
            RsiClosedRow(
                symbol=symbol,
                side="LONG",
                date_opened=pos["entry_iso"],
                entry_price=entry,
                stop_price=0.0,
                target_price=0.0,
                date_closed=iso,
                exit_price=exit_px,
                exit_type=exit_type,
                days_held=int((pd.Timestamp(dates[exit_i]) - pd.Timestamp(dates[pos["entry_i"]])).days),
                pnl_pct=pnl_pct,
                pnl_dollars=shares * (exit_px - entry),
                ann_ror_pct=ann,
                max_price=float(pos["max_price"]),
                signal_date=pos["signal_iso"],
                entry_on=str(cfg.rsi_entry_on or "next_open"),
                rsi_trigger=trig,
                rsi_exit=exit_rsi_val,
                prior_ob_rsi=prior_ob,
                rsi_drop_from_ob=drop,
                atr_pct_at_trigger=float(pos["atr_pct"]),
                dist_to_52w_high_pct_at_trigger=float(pos["dist52"]),
                rel_vol_at_trigger=float(pos["rel_vol"]),
                close_vs_sma50_pct_at_trigger=float(pos["sma50_pct"]),
                max_rsi_trigger=float(cfg.rsi_max_trigger),
                min_atr_pct=float(cfg.rsi_min_atr_pct),
                time_stop_days=time_stop,
                exit_rsi_level=exit_rsi,
                one_liner=(
                    f"{symbol} | IN {pos['entry_iso']} @ {entry:.2f} -> OUT {iso} @ {exit_px:.2f} | "
                    f"{exit_type} {pnl_pct:+.1f}% | RSI trig {trig:.1f} -> exit "
                    f"{exit_rsi_val:.1f}" if np.isfinite(exit_rsi_val) else
                    f"{symbol} | IN {pos['entry_iso']} @ {entry:.2f} -> OUT {iso} @ {exit_px:.2f} | "
                    f"{exit_type} {pnl_pct:+.1f}% | RSI trig {trig:.1f}"
                ),
            )
        )
        cooldown_until = iso
        pos = None

    for i in range(n):
        # 1) Resolve yesterday's pending fills at today's open.
        if pending_entry_i >= 0 and pos is None:
            px = float(open_[i])
            if np.isfinite(px) and px > 0:
                _open_position(i, px, pending_entry_i)
            pending_entry_i = -1
        elif pending_exit and pos is not None:
            px = float(open_[i])
            if np.isfinite(px) and px > 0:
                _close_position(i, px, pending_exit_type, pending_exit_rsi)
            pending_exit = False
            pending_exit_rsi = float("nan")

        if pos is not None:
            pos["max_price"] = max(float(pos["max_price"]), float(high[i]))

        # Last bar: no signal can be filled inside the backtest window.
        if i == n - 1:
            continue

        # 2) Signals evaluated on this bar's close, filled next open.
        if pos is not None:
            sell = np.isfinite(rsi[i]) and rsi[i] >= exit_rsi
            held = int((pd.Timestamp(dates[i]) - pd.Timestamp(dates[pos["entry_i"]])).days)
            timed = time_stop > 0 and held >= time_stop
            if sell:
                pending_exit = True
                pending_exit_type = "OVERBOUGHT"
                pending_exit_rsi = float(rsi[i])
            elif timed:
                pending_exit = True
                pending_exit_type = "TIME"
                pending_exit_rsi = float(rsi[i]) if np.isfinite(rsi[i]) else float("nan")
            continue

        if pending_entry_i >= 0:
            continue
        if not bool(buy_base[i]):
            continue
        ok, _reason = gate_ok(cfg, i, feat)
        if not ok:
            continue
        fill_iso = _iso(dates[i + 1]) if not entry_on_close else _iso(dates[i])
        if not _entry_date_allowed(fill_iso, cfg.entry_start_date, cfg.entry_end_date):
            continue
        cool = int(cfg.symbol_reentry_cooldown_days or 0)
        if cooldown_until and cool > 0 and _calendar_days(cooldown_until, fill_iso) < cool:
            continue
        if entry_on_close:
            px = float(close[i])
            if np.isfinite(px) and px > 0:
                _open_position(i, px, i)
        else:
            pending_entry_i = i

    # Still-open position at the end of the data.
    last = n - 1
    if pos is not None:
        entry = float(pos["entry"])
        cl = float(close[last])
        entry_iso = str(pos["entry_iso"])
        last_iso = _iso(dates[last])
        cal_open = _calendar_days(entry_iso, last_iso)
        stop_iso = ""
        days_to_stop: Any = ""
        if time_stop > 0:
            stop_ts = pd.Timestamp(dates[pos["entry_i"]]) + pd.Timedelta(days=time_stop)
            stop_iso = stop_ts.strftime("%Y%m%d")
            days_to_stop = max(0, time_stop - cal_open)
        rsi_now = float(rsi[last]) if np.isfinite(rsi[last]) else float("nan")
        hint = (
            f"Sell next open once RSI14 >= {exit_rsi:g} (now "
            f"{rsi_now:.1f}). " if np.isfinite(rsi_now)
            else f"Sell next open once RSI14 >= {exit_rsi:g}. "
        )
        if time_stop > 0:
            hint += (
                f"Otherwise flatten at the {time_stop}-calendar-day time stop "
                f"({_iso_dash(stop_iso)}). "
            )
        hint += "No price stop and no price target — RSI and the clock are the only exits."
        open_rows.append(
            {
                "symbol": symbol,
                "date_opened": entry_iso,
                "entry_price": entry,
                "current_price": cl,
                "pnl_pct": (cl / entry - 1.0) * 100.0 if entry else 0.0,
                "days_open": last - int(pos["entry_i"]),
                "calendar_days_open": cal_open,
                "rsi_now": rsi_now,
                "rsi_trigger": float(pos["rsi_trigger"]),
                "atr_pct": float(pos["atr_pct"]),
                "time_stop_date": stop_iso,
                "days_to_time_stop": days_to_stop,
                "signal_date": pos["signal_iso"],
                "hint": hint,
            }
        )
        watch.append(
            {
                "symbol": symbol,
                "asof": _iso(dates[last]),
                "row_type": "OPEN",
                "status": "IN_POSITION",
                "close": float(close[last]),
                "rsi": rsi_now,
                "prior_ob": float(feat["prior_ob"][last]),
                "atr_pct": float(feat["atr_pct"][last]),
                "hint": hint,
            }
        )

    # Watchlist: what the scanner should look at tomorrow.
    if pos is None:
        asof = _iso(dates[last])
        last_close = float(close[last])
        last_rsi = float(rsi[last]) if np.isfinite(rsi[last]) else float("nan")
        last_atr = float(feat["atr_pct"][last])
        last_prior_ob = float(feat["prior_ob"][last])
        row = {
            "symbol": symbol,
            "asof": asof,
            "close": last_close,
            "rsi": last_rsi,
            "prior_ob": last_prior_ob,
            "atr_pct": last_atr,
        }
        if pending_entry_i >= 0:
            # Signal fired on the final bar — the fill has not happened yet.
            watch.append(
                {
                    **row,
                    "row_type": "BUY",
                    "status": "PENDING_NEXT_OPEN",
                    "hint": (
                        f"Signal on {_iso_dash(asof)}: RSI14 cooled from overbought "
                        f"({last_prior_ob:.1f}) to {last_rsi:.1f} with ATR% {last_atr:.2f}. "
                        f"Buy at the next open. Sell back at RSI14 >= {exit_rsi:g}"
                        + (f"; time stop {time_stop} calendar days." if time_stop > 0 else ".")
                    ),
                }
            )
        elif bool(buy_base[last]):
            ok, reason = gate_ok(cfg, last, feat)
            if not ok:
                watch.append(
                    {
                        **row,
                        "row_type": "NEAR",
                        "status": "GATE_FAIL",
                        "hint": (
                            "Cooled into Neutral after overbought but blocked by an entry "
                            f"gate: {reason}. No fill."
                        ),
                    }
                )
        elif np.isfinite(last_rsi) and last_rsi >= ob:
            watch.append(
                {
                    **row,
                    "row_type": "NEAR",
                    "status": "ARMED_OVERBOUGHT",
                    "hint": (
                        f"RSI14 {last_rsi:.1f} is overbought — armed. A close back inside the "
                        f"Neutral band (below {float(cfg.rsi_max_trigger):g} for the entry gate) "
                        f"with ATR% >= {float(cfg.rsi_min_atr_pct):g} triggers a next-open buy."
                    ),
                }
            )

    return closed, open_rows, watch


# ---------------------------------------------------------------------------
# Parallel
# ---------------------------------------------------------------------------


@dataclass
class RsiSymbolResult:
    symbol: str
    closed: list[RsiClosedRow]
    open_rows: list[dict[str, Any]]
    watch: list[dict[str, Any]]
    skip_reason: str = ""


def _process_rsi_symbol(args: tuple[str, pd.DataFrame, dict[str, Any]]) -> RsiSymbolResult:
    sym, df, cfg_d = args
    cfg = _rsi_cfg_from_dict(cfg_d)
    closed, open_rows, watch = backtest_symbol(sym, df, cfg)
    return RsiSymbolResult(sym, closed, open_rows, watch)


def _run_rsi_symbol_tasks(
    tasks: list[tuple[str, pd.DataFrame, dict[str, Any]]],
    workers: int,
) -> list[RsiSymbolResult]:
    results: list[RsiSymbolResult] = []
    if workers > 0 and len(tasks) > 1:
        n_w = min(int(workers), len(tasks), 32)
        print(f"[RSI] Spawning {n_w} worker process(es) for {len(tasks)} symbols", flush=True)
        with ProcessPoolExecutor(max_workers=n_w) as ex:
            futs = {ex.submit(_process_rsi_symbol, t): t[0] for t in tasks}
            for fut in as_completed(futs):
                sym = futs[fut]
                try:
                    res = fut.result()
                except Exception as e:
                    print(f"[RSI] skip {sym}: worker failed ({e})", flush=True)
                    results.append(RsiSymbolResult(sym, [], [], [], skip_reason=f"worker failed ({e})"))
                    continue
                results.append(res)
                print(
                    f"[RSI] {res.symbol}: {len(res.closed)} closed, {len(res.open_rows)} open, "
                    f"{len(res.watch)} watch",
                    flush=True,
                )
    else:
        for t in tasks:
            res = _process_rsi_symbol(t)
            results.append(res)
            print(
                f"[RSI] {res.symbol}: {len(res.closed)} closed, {len(res.open_rows)} open, "
                f"{len(res.watch)} watch",
                flush=True,
            )
    return results


# ---------------------------------------------------------------------------
# Host bridges
# ---------------------------------------------------------------------------


def rsi_closed_to_brt_trade(r: RsiClosedRow) -> Any:
    """Map an RSI closed trade onto BRTTrade so compute_metrics / Audit match VZ/WRL."""
    try:
        from rocket_tbn import BRTTrade
    except ImportError:
        from stock_analysis.rocket_tbn import BRTTrade  # type: ignore

    t = BRTTrade(
        symbol=str(r.symbol).upper(),
        date_opened=str(r.date_opened),
        entry_price=float(r.entry_price),
        stop_price=float(r.stop_price),
        target_price=float(r.target_price),
        date_closed=str(r.date_closed or ""),
        exit_price=float(r.exit_price or 0.0),
        exit_type=str(r.exit_type or ""),
        days_held=int(r.days_held or 0),
        pnl_pct=float(r.pnl_pct or 0.0),
        pnl_dollars=float(r.pnl_dollars or 0.0),
        max_price=float(r.max_price or r.entry_price or 0.0),
        side=str(r.side or "LONG"),
    )
    t.signal_date = str(r.signal_date or "")
    return t


def brt_config_from_rsi(cfg: RsiConfig, host_cfg: Any = None) -> Any:
    """BRTConfig for unified Audit/Report (same wide schema as VZ/WRL/SB)."""
    try:
        from rocket_tbn import BRTConfig
    except ImportError:
        from stock_analysis.rocket_tbn import BRTConfig  # type: ignore

    base_kw: dict[str, Any] = dict(
        rsi_mode=True,
        vz_mode=False,
        wrl_mode=False,
        sb_mode=False,
        qull_mode=False,
        mvcp_mode=False,
        brt_zones=False,
        yh_zones=False,
        wpbr_zones=False,
        vec_zones=False,
        rl_mode="false",
        relative_strength_enabled=False,
        rsi_ob=float(cfg.rsi_ob),
        rsi_os=float(cfg.rsi_os),
        rsi_exit=float(cfg.rsi_exit),
        rsi_max_trigger=float(cfg.rsi_max_trigger),
        rsi_min_atr_pct=float(cfg.rsi_min_atr_pct),
        rsi_time_stop_days=int(cfg.rsi_time_stop_days),
        rsi_entry_on=str(cfg.rsi_entry_on or "next_open"),
        rsi_sheet_notional=float(cfg.rsi_sheet_notional),
        brt_cash=float(cfg.brt_cash),
        symbol_reentry_cooldown_days=int(cfg.symbol_reentry_cooldown_days or 0),
        entry_start_date=str(cfg.entry_start_date or ""),
        entry_end_date=str(cfg.entry_end_date or ""),
        compute_equity_metrics=True,
    )
    if host_cfg is not None:
        for k in (
            "initial_capital",
            "aggressive",
            "aggressive_max_multiple",
            "margin_utilization",
            "max_positions",
            "aggressive_margin_interest",
            "aggressive_avg_positions",
            "aggressive_sizing_equity_cap",
            "days_per_year",
        ):
            if hasattr(host_cfg, k):
                base_kw[k] = getattr(host_cfg, k)
        if hasattr(host_cfg, "rsi_mode"):
            try:
                return replace(host_cfg, **base_kw)
            except TypeError:
                pass
    return BRTConfig(**base_kw)


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------


def _write_summary(
    path: Path,
    closed: list[RsiClosedRow],
    tickers: Optional[dict[str, pd.DataFrame]],
) -> None:
    by_sym: dict[str, list[RsiClosedRow]] = {}
    for r in closed:
        by_sym.setdefault(r.symbol, []).append(r)
    total_pnl_all = sum(r.pnl_dollars for r in closed) or 0.0
    days_per_year = 365.25

    def _first_data_date(sym: str) -> str:
        if not tickers or sym not in tickers:
            return ""
        frame = tickers[sym]
        if frame is None or len(frame) == 0:
            return ""
        try:
            if isinstance(frame.index, pd.DatetimeIndex) and len(frame.index):
                d0 = frame.index[0]
            elif "Date" in frame.columns:
                d0 = pd.to_datetime(frame["Date"].iloc[0])
            else:
                return ""
            return pd.Timestamp(d0).strftime("%Y-%m-%d")
        except Exception:
            return ""

    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "SYMBOL",
                "TRADES",
                "WINS",
                "LOSSES",
                "BEs",
                "PCT_WINS",
                "TOTAL_PNL",
                "SHEET_PNL",
                "AVG_PNL_PCT",
                "PROFIT_FACTOR",
                "PCT_OF_TOTAL_PNL",
                "CURRENT_MARKET_CAP",
                "SECTOR",
                "INDUSTRY",
                "FIRST_DATA_DATE",
                "AVG_TRADES_PER_YEAR",
                "MAX_WIN_PCT",
                "MEDIAN_PNL_PCT",
                "AVG_DAYS_HELD",
                "PCT_EXIT_OVERBOUGHT",
                "PCT_EXIT_TIME",
            ]
        )
        for sym in sorted(by_sym):
            rows = by_sym[sym]
            wins = sum(1 for r in rows if r.pnl_pct > 1e-9)
            losses = sum(1 for r in rows if r.pnl_pct < -1e-9)
            bes = len(rows) - wins - losses
            pnls = [r.pnl_pct for r in rows]
            pnl = sum(r.pnl_dollars for r in rows)
            avg_pct = (sum(pnls) / len(pnls)) if pnls else 0.0
            med_pct = float(np.median(pnls)) if pnls else 0.0
            max_win = max(pnls) if pnls else 0.0
            sum_wins = sum(r.pnl_dollars for r in rows if r.pnl_pct > 1e-9)
            sum_losses = abs(sum(r.pnl_dollars for r in rows if r.pnl_pct < -1e-9))
            if sum_losses > 0:
                pf = sum_wins / sum_losses
            else:
                pf = sum_wins if sum_wins > 0 else 0.0
            n_ob = sum(1 for r in rows if r.exit_type == "OVERBOUGHT")
            n_time = sum(1 for r in rows if r.exit_type == "TIME")
            first = _first_data_date(sym)
            years = 1.0
            if first and rows:
                try:
                    d0 = datetime.strptime(first.replace("-", "")[:8], "%Y%m%d")
                    d1 = datetime.strptime(str(rows[-1].date_closed).replace("-", "")[:8], "%Y%m%d")
                    years = max((d1 - d0).days / days_per_year, 1e-6)
                except Exception:
                    years = 1.0
            w.writerow(
                [
                    sym,
                    len(rows),
                    wins,
                    losses,
                    bes,
                    f"{(100.0 * wins / len(rows)) if rows else 0.0:.1f}%",
                    f"{pnl:.2f}",
                    f"{pnl:.2f}",
                    f"{avg_pct:.2f}%",
                    f"{pf:.2f}",
                    f"{(100.0 * pnl / total_pnl_all) if total_pnl_all else 0.0:.1f}%",
                    "",
                    "",
                    "",
                    first,
                    f"{(len(rows) / years):.2f}",
                    f"{max_win:.2f}%",
                    f"{med_pct:+.2f}%",
                    f"{(sum(r.days_held for r in rows) / len(rows)) if rows else 0.0:.1f}",
                    f"{(100.0 * n_ob / len(rows)) if rows else 0.0:.1f}%",
                    f"{(100.0 * n_time / len(rows)) if rows else 0.0:.1f}%",
                ]
            )


def write_rsi_outputs(
    output_dir: Path,
    ts: str,
    closed: list[RsiClosedRow],
    open_rows: list[dict[str, Any]],
    watch_rows: list[dict[str, Any]],
    cfg: RsiConfig,
    *,
    host_meta: Optional[dict[str, Any]] = None,
    tickers: Optional[dict[str, pd.DataFrame]] = None,
    host_cfg: Any = None,
    tbn_cfg: Any = None,
    drive_link: str = "",
    no_yfinance: bool = False,
    universe_label: str = "",
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    host_meta = host_meta or {}
    closed_path = output_dir / f"{FILE_PREFIX}_Closed_{ts}.csv"
    open_path = output_dir / f"{FILE_PREFIX}_Open_{ts}.csv"
    watch_path = output_dir / f"{FILE_PREFIX}_Watchlist_{ts}.csv"
    summary_path = output_dir / f"{FILE_PREFIX}_Summary_{ts}.csv"
    summary_symbols_path = output_dir / f"{FILE_PREFIX}_Summary_Symbols_{ts}.csv"
    report_path = output_dir / f"{FILE_PREFIX}_Report_{ts}.csv"
    audit_path = output_dir / f"{FILE_PREFIX}_Audit_Report_{ts}.csv"

    with closed_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(RSI_CLOSED_HEADER)
        for r in closed:
            w.writerow(r.to_csv_row())

    with open_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(RSI_OPEN_HEADER)
        for r in open_rows:
            w.writerow(
                [
                    r["symbol"],
                    r["date_opened"],
                    f"{r['entry_price']:.4f}",
                    f"{r['current_price']:.4f}",
                    f"{r['pnl_pct']:.4f}",
                    r["days_open"],
                    r["calendar_days_open"],
                    _fmt_opt(r["rsi_now"]),
                    _fmt_opt(r["rsi_trigger"]),
                    _fmt_opt(r["atr_pct"]),
                    f"{float(cfg.rsi_exit):g}",
                    int(cfg.rsi_time_stop_days or 0),
                    r["time_stop_date"],
                    r["days_to_time_stop"],
                    r["signal_date"],
                    r["hint"],
                ]
            )

    with watch_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(RSI_WATCHLIST_HEADER)
        for r in watch_rows:
            w.writerow(
                [
                    r["symbol"],
                    r["asof"],
                    r["row_type"],
                    r["status"],
                    f"{r['close']:.4f}",
                    _fmt_opt(r["rsi"]),
                    _fmt_opt(r["prior_ob"]),
                    _fmt_opt(r["atr_pct"]),
                    f"{float(cfg.rsi_max_trigger):g}",
                    f"{float(cfg.rsi_min_atr_pct):g}",
                    f"{float(cfg.rsi_exit):g}",
                    int(cfg.rsi_time_stop_days or 0),
                    r["hint"],
                ]
            )

    _write_summary(summary_path, closed, tickers)

    equity_path = output_dir / f"{FILE_PREFIX}_EquityCurve_{ts}.csv"
    equity_meta_path = output_dir / f"{FILE_PREFIX}_EquityMeta_{ts}.csv"
    max_dd_pct = 0.0
    aggressive_total = ""
    aggressive_max_dd = ""
    host_equity_written = False
    if tickers is not None and host_cfg is not None and (
        bool(getattr(host_cfg, "aggressive", False)) or bool(host_meta.get("use_host_equity"))
    ):
        equity = compute_and_write_host_equity(
            output_dir=output_dir,
            ts=ts,
            file_prefix=FILE_PREFIX,
            closed=closed,
            open_trades=open_rows,
            tickers=tickers,
            cfg=host_cfg,
        )
        if equity:
            host_equity_written = True
            md = equity.get("Max_Drawdown", "")
            try:
                max_dd_pct = float(str(md).replace("%", "").strip())
            except (TypeError, ValueError):
                pass
            if equity.get("_aggressive"):
                aggressive_total = f"{float(equity.get('_equity_total_pnl', 0) or 0):.2f}"
                aggressive_max_dd = str(equity.get("Aggressive_Max_Drawdown", "") or "")

    if not host_equity_written:
        by_date: dict[str, float] = {}
        for r in closed:
            d = str(r.date_closed or "").strip().replace("-", "")
            if len(d) >= 8 and d[:8].isdigit():
                iso = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
            else:
                iso = str(r.date_closed or "").strip()
            if not iso:
                continue
            by_date[iso] = by_date.get(iso, 0.0) + float(r.pnl_dollars)
        init_cash = float(host_meta.get("host_brt_cash") or getattr(cfg, "brt_cash", 0) or 10_000.0)
        equity_val = init_cash
        peak = equity_val
        max_dd = 0.0
        eq_rows: list[dict[str, Any]] = []
        for d in sorted(by_date):
            equity_val += by_date[d]
            if equity_val > peak:
                peak = equity_val
            dd = ((peak - equity_val) / peak) if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
            eq_rows.append({"Date": d, "Equity": equity_val, "Positions": ""})
        if not eq_rows:
            eq_rows.append({"Date": "", "Equity": init_cash, "Positions": ""})
        pd.DataFrame(eq_rows).to_csv(equity_path, index=False)
        max_dd_pct = max_dd * 100.0
        pd.DataFrame(
            [
                {
                    "Initial_Account_Size": init_cash,
                    "Max_Drawdown_fraction": max_dd,
                    "Max_Drawdown_pct": f"{max_dd_pct:.2f}%",
                    "Max_Days_Underwater": "",
                    "Pct_Days_Underwater": "",
                    "Aggressive": False,
                    "Curve_Kind": "realized_pnl_by_exit_date",
                }
            ]
        ).to_csv(equity_meta_path, index=False)

    try:
        from rocket_tbn import compute_metrics, write_brt_audit_report, write_brt_report
    except ImportError:
        from stock_analysis.rocket_tbn import (  # type: ignore
            compute_metrics,
            write_brt_audit_report,
            write_brt_report,
        )

    report_cfg = brt_config_from_rsi(cfg, tbn_cfg if tbn_cfg is not None else host_cfg)
    if host_meta.get("host_brt_cash") not in (None, ""):
        try:
            report_cfg = replace(report_cfg, brt_cash=float(host_meta["host_brt_cash"]))
        except (TypeError, ValueError):
            pass
    brt_closed = [rsi_closed_to_brt_trade(r) for r in closed]
    metrics = compute_metrics(brt_closed, report_cfg)
    if host_meta.get("host_max_positions") not in (None, ""):
        try:
            metrics["Max_Positions"] = int(host_meta["host_max_positions"])
        except (TypeError, ValueError):
            pass
    if max_dd_pct:
        metrics["Max_Drawdown"] = max_dd_pct
    if aggressive_total not in (None, ""):
        metrics["Aggressive_Total_PNL"] = aggressive_total
    if aggressive_max_dd not in (None, ""):
        metrics["Aggressive_Max_Drawdown"] = aggressive_max_dd

    write_brt_report(
        report_cfg,
        metrics,
        str(output_dir),
        ts,
        drive_link=drive_link,
        file_prefix=FILE_PREFIX,
    )
    write_brt_audit_report(
        report_cfg,
        metrics,
        str(output_dir),
        ts,
        drive_link=drive_link,
        file_prefix=FILE_PREFIX,
    )
    if report_path.exists():
        report_path = output_dir / f"{FILE_PREFIX}_Report_{ts}.csv"

    corr_path = output_dir / f"{FILE_PREFIX}_Correlation_{ts}.csv"
    corr_pairs_path = output_dir / f"{FILE_PREFIX}_Correlation_Pairs_{ts}.csv"
    try:
        import sys

        _sa = Path(__file__).resolve().parent
        if str(_sa) not in sys.path:
            sys.path.insert(0, str(_sa))
        from correlate_brt_closed import run_correlation_report

        run_correlation_report(str(closed_path), str(corr_path))
    except Exception as e:
        print(f"[RSI] Correlation skipped: {e}", flush=True)

    try:
        import sys

        _sa = Path(__file__).resolve().parent
        if str(_sa) not in sys.path:
            sys.path.insert(0, str(_sa))
        try:
            from rocket_post_analysis import write_analysis_artifacts
        except ImportError:
            from stock_analysis.rocket_post_analysis import write_analysis_artifacts  # type: ignore
        write_analysis_artifacts(
            cfg=None,
            tickers=tickers or {},
            output_dir=output_dir,
            ts=ts,
            closed_path=closed_path,
            summary_path=summary_path,
            open_path=open_path,
            prefix=FILE_PREFIX,
            no_yfinance=bool(no_yfinance),
        )
    except Exception as e:
        print(f"[RSI] analysis artifacts skipped: {e}", flush=True)

    # Per-symbol ledger alias (post_run_analysis prefers *_Summary_Symbols_*).
    if summary_path.is_file():
        summary_symbols_path.write_bytes(summary_path.read_bytes())

    for src, name in (
        (closed_path, f"{FILE_PREFIX}_LatestRun_Closed.csv"),
        (open_path, f"{FILE_PREFIX}_LatestRun_Open.csv"),
        (watch_path, f"{FILE_PREFIX}_LatestRun_Watchlist.csv"),
        (summary_path, f"{FILE_PREFIX}_LatestRun_Summary.csv"),
        (summary_symbols_path, f"{FILE_PREFIX}_LatestRun_Summary_Symbols.csv"),
        (audit_path, f"{FILE_PREFIX}_LatestRun_Audit_Report.csv"),
        (report_path, f"{FILE_PREFIX}_LatestRun_Report.csv"),
        (equity_path, f"{FILE_PREFIX}_LatestRun_EquityCurve.csv"),
        (corr_path, f"{FILE_PREFIX}_LatestRun_Correlation.csv"),
        (corr_pairs_path, f"{FILE_PREFIX}_LatestRun_Correlation_Pairs.csv"),
    ):
        if src.is_file():
            (output_dir / name).write_bytes(src.read_bytes())

    (output_dir / f"{FILE_PREFIX}_last_run_ts.txt").write_text(ts + "\n", encoding="utf-8")
    (output_dir / "last_run_ts.txt").write_text(ts, encoding="utf-8")
    if _is_rsi_house_universe(universe_label, summary_path):
        (output_dir / f"{FILE_PREFIX}_house_last_run_ts.txt").write_text(
            ts + "\n", encoding="utf-8"
        )
        print(f"[RSI] House pin {FILE_PREFIX}_house_last_run_ts.txt -> {ts}", flush=True)

    return {
        "closed": closed_path,
        "open": open_path,
        "watchlist": watch_path,
        "summary": summary_path,
        "summary_symbols": summary_symbols_path,
        "report": report_path,
        "audit": audit_path,
        "equity_curve": equity_path,
        "equity_meta": equity_meta_path,
        "correlation": corr_path,
    }


# ---------------------------------------------------------------------------
# Host entrypoint
# ---------------------------------------------------------------------------


def run_rsi_from_brt_main(
    *,
    cfg: Any,
    tickers: dict[str, pd.DataFrame],
    ticker_list: list[str],
    output_dir: Path,
    ts: str,
    data_dir: Path,
    load_symbol_fn: Any,
    workers: int = 0,
    drive_link: str = "",
    no_yfinance: bool = False,
) -> int:
    rcfg = rsi_config_from_brt(cfg)
    n_workers = max(0, int(workers or 0))
    print(
        f"[RSI] Relative Strength Index on {len(ticker_list)} symbols "
        f"(exit_rsi={rcfg.rsi_exit:g}, max_trigger={rcfg.rsi_max_trigger:g}, "
        f"min_atr_pct={rcfg.rsi_min_atr_pct:g}, time_stop={rcfg.rsi_time_stop_days}d, "
        f"entry_on={rcfg.rsi_entry_on}, workers={n_workers})",
        flush=True,
    )
    print(
        "[RSI] Buy: prior bar RSI14 >= "
        f"{rcfg.rsi_ob:g} and today RSI14 between "
        f"{rcfg.rsi_os:g} and {rcfg.rsi_ob:g} with trigger RSI14 < "
        f"{rcfg.rsi_max_trigger:g} and ATR% >= {rcfg.rsi_min_atr_pct:g}; fill next open. "
        f"Sell: RSI14 >= {rcfg.rsi_exit:g} next open, else flatten at "
        f"{rcfg.rsi_time_stop_days} calendar days. No price stop / target.",
        flush=True,
    )

    all_closed: list[RsiClosedRow] = []
    all_open: list[dict[str, Any]] = []
    all_watch: list[dict[str, Any]] = []
    loaded: dict[str, pd.DataFrame] = {}
    skipped: list[str] = []
    cfg_d = _rsi_cfg_dict(rcfg)
    tasks: list[tuple[str, pd.DataFrame, dict[str, Any]]] = []

    for sym in ticker_list:
        df = tickers.get(sym) if tickers else None
        if df is None or (hasattr(df, "empty") and df.empty):
            if load_symbol_fn is not None:
                try:
                    df = load_symbol_fn(sym, data_dir)
                except Exception as e:
                    print(f"[RSI] skip {sym}: load failed ({e})", flush=True)
                    skipped.append(sym)
                    continue
        if df is None or len(df) < 30:
            print(f"[RSI] skip {sym}: insufficient bars ({0 if df is None else len(df)})", flush=True)
            skipped.append(sym)
            continue
        loaded[sym] = df
        tasks.append((sym, df, cfg_d))

    t_bt = time.time()
    results = _run_rsi_symbol_tasks(tasks, n_workers)
    for res in results:
        if res.skip_reason:
            skipped.append(res.symbol)
            continue
        all_closed.extend(res.closed)
        all_open.extend(res.open_rows)
        all_watch.extend(res.watch)
    print(f"[RSI] Symbol backtest {time.time() - t_bt:.1f}s (workers={n_workers})", flush=True)

    all_closed.sort(key=lambda r: (r.date_opened, r.symbol))
    all_watch.sort(key=lambda r: (r["row_type"], r["symbol"]))

    host_meta: dict[str, Any] = {}
    hcfg = HostSizingConfig(
        brt_cash=float(getattr(cfg, "brt_cash", rcfg.brt_cash) or rcfg.brt_cash),
        initial_capital=float(getattr(cfg, "initial_capital", 500_000) or 500_000),
        aggressive_max_multiple=float(getattr(cfg, "aggressive_max_multiple", 2.0) or 2.0),
        margin_utilization=float(getattr(cfg, "margin_utilization", 0.6) or 0.6),
        max_positions=int(getattr(cfg, "max_positions", 0) or 0),
        aggressive=bool(getattr(cfg, "aggressive", False)),
        aggressive_margin_interest=float(getattr(cfg, "aggressive_margin_interest", 0.10) or 0.10),
        aggressive_avg_positions=float(getattr(cfg, "aggressive_avg_positions", 0) or 0),
        aggressive_sizing_equity_cap=float(getattr(cfg, "aggressive_sizing_equity_cap", 10.0) or 10.0),
        aggressive_sell=str(getattr(cfg, "aggressive_sell", "false") or "false"),
        equity_fast_aggressive=bool(getattr(cfg, "equity_fast_aggressive", False)),
    )
    if all_closed:
        adj, scale, max_pos = apply_host_dollar_scale(all_closed, all_open, hcfg)
        rcfg.brt_cash = adj
        host_meta = {
            "host_max_positions": max_pos,
            "host_brt_cash": adj,
            "host_pnl_scale": scale,
            "host_audit_brt_cash": audit_display_brt_cash(max_pos),
        }
        audit_cash = float(host_meta["host_audit_brt_cash"])
        closed_pnl = sum(r.pnl_dollars for r in all_closed)
        audit_pnl = closed_pnl * (audit_cash / adj) if adj > 0 else closed_pnl
        host_meta["total_pnl_audit_1m"] = f"{audit_pnl:.2f}"
        print(
            f"[RSI] Host dollar-scale: PNL_DOLLARS × {scale:.6g}; "
            f"brt_cash -> {adj:,.0f} (deployable/Max_Positions={max_pos}; "
            f"audit_label 1M/mp={audit_cash:,.0f})",
            flush=True,
        )

    paths = write_rsi_outputs(
        Path(output_dir),
        ts,
        all_closed,
        all_open,
        all_watch,
        rcfg,
        host_meta=host_meta,
        tickers=loaded,
        host_cfg=hcfg,
        tbn_cfg=cfg,
        drive_link=drive_link,
        no_yfinance=bool(no_yfinance),
        universe_label=str(
            getattr(cfg, "universe_label", "")
            or f"tbn rsi_mode ({len(ticker_list)} sym)"
        ),
    )
    wins = sum(1 for r in all_closed if r.pnl_pct > 0)
    losses = sum(1 for r in all_closed if r.pnl_pct <= 0)
    total_pnl = sum(r.pnl_dollars for r in all_closed)
    print(
        f"[RSI] Closed: {paths['closed']} ({len(all_closed)} trades, {wins}W/{losses}L, "
        f"PnL=${total_pnl:.2f})",
        flush=True,
    )
    print(f"[RSI] Open: {paths['open']} ({len(all_open)} positions)", flush=True)
    print(f"[RSI] Watchlist: {paths['watchlist']} ({len(all_watch)} rows)", flush=True)
    print(f"[RSI] Summary: {paths['summary']}", flush=True)
    if skipped:
        print(f"[RSI] Skipped symbols: {','.join(skipped)}", flush=True)
    return 0
