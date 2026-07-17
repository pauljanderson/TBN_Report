#!/usr/bin/env python3
"""
MonkeyTrader: Schedule-driven backtester with same target/stop and reporting as BRT.

- Stock picking is arbitrary: driven by a buy schedule (e.g. CSV of Date, Symbol).
- No BRT qualifiers (no pivots, bands, growth, touch counts).
- Same position sizing, target_pct, stop_pct, atr_target / atr_stop / atr_increment, and exit logic as BRT.
- Outputs MonkeyTrader_Closed, MonkeyTrader_Open, MonkeyTrader_Report, MonkeyTrader_Audit_Report
  with the same column layout as BRT so results can be compared to BRT optimizer.

Schedule generator:
- With ``-s``: round-robin across listed symbols (AAPL, MSFT, META, …).
- Full universe: letter-weighted round-robin (A/B/C names interleaved by proportion).

Quick start:
  # Generate schedule (all tickers, ~2.4 buys/trading day)
  python stock_analysis/MonkeyTrader.py generate data/newdata/data 2019-01-01 2019-12-31 -o drive/MonkeyTrader_Schedule.csv

  # Generate for selected symbols only
  python stock_analysis/MonkeyTrader.py generate data/newdata/data 2019-01-01 2019-12-31 -s META,AAPL,MSFT -m 1.0

  # Run backtest from schedule
  python stock_analysis/MonkeyTrader.py run drive/MonkeyTrader_Schedule.csv data/newdata/data -o drive
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

# Reuse BRT trade type and logic
try:
    from rocket_brt import (
        BRTConfig,
        BRTTrade,
        load_csv,
        load_all_tickers,
        compute_metrics,
        write_brt_closed,
        write_brt_open,
        _metrics_to_audit_row,
    )
except ImportError as e:
    print(f"[ERR] MonkeyTrader requires rocket_brt: {e}", file=sys.stderr)
    sys.exit(1)

try:
    from BRT_Optimizer import AUDIT_COLS_ORDER, CFG_COLS
except ImportError:
    AUDIT_COLS_ORDER = None
    CFG_COLS = []

try:
    from BRT_DrawdownCalc import compute_realized_ledger_equity_metrics as _compute_realized_ledger_equity_metrics
    HAS_EQUITY_METRICS = True
except ImportError:
    _compute_realized_ledger_equity_metrics = None  # type: ignore[misc, assignment]
    HAS_EQUITY_METRICS = False


# ============== CONFIG ==============
@dataclass
class MonkeyTraderConfig:
    """Config for MonkeyTrader (subset of BRT: no pivot/band/growth)."""
    brt_cash: float = 47500
    stop_pct: float = 0.934
    stop_pct_is_multiplier: bool = True
    target_pct: float = 1.29
    # ATR-based exits (same semantics as rocket_brt): 0 = use target_pct / stop_pct path instead
    atr_target: float = 0.0
    atr_stop: float = 0.0
    atr_increment: float = 0.0
    stop_compare_round_decimals: int = 2
    days_per_year: float = 365.0
    exit_at_close_when_stopped: bool = False
    compute_equity_metrics: bool = True
    # Default True: skip a scheduled buy when that symbol is already held open.
    skip_entry_if_symbol_open: bool = True

    def to_brt_config(self) -> BRTConfig:
        """BRTConfig with same risk/exit params for metrics and report."""
        return BRTConfig(
            brt_cash=self.brt_cash,
            stop_pct=self.stop_pct,
            stop_pct_is_multiplier=self.stop_pct_is_multiplier,
            target_pct=self.target_pct,
            atr_target=self.atr_target,
            atr_stop=self.atr_stop,
            trailing_stop_increment=self.atr_increment,
            stop_compare_round_decimals=self.stop_compare_round_decimals,
            days_per_year=self.days_per_year,
            exit_at_close_when_stopped=self.exit_at_close_when_stopped,
        )


def _compute_atr_14_series(df: pd.DataFrame) -> pd.Series:
    """
    14-day ATR aligned to df index: TR = max(H-L, |H-prev_C|, |L-prev_C|); ATR14 = SMA(TR, 14).
    Same definition as rocket_brt.run_brt_backtest pre-loop.
    """
    if df is None:
        return pd.Series(dtype=np.float64)
    if df.empty or len(df) < 2:
        return pd.Series(dtype=np.float64, index=df.index)
    high_arr = df["High"].to_numpy(dtype=np.float64)
    low_arr = df["Low"].to_numpy(dtype=np.float64)
    close_arr = df["Close"].to_numpy(dtype=np.float64)
    n = len(df)
    atr_period = 14
    tr_arr = np.empty(n, dtype=np.float64)
    tr_arr[0] = high_arr[0] - low_arr[0]
    hl = high_arr[1:] - low_arr[1:]
    h_pc = np.abs(high_arr[1:] - close_arr[:-1])
    l_pc = np.abs(low_arr[1:] - close_arr[:-1])
    tr_arr[1:] = np.maximum.reduce([hl, h_pc, l_pc])
    atr_14 = np.full(n, np.nan, dtype=np.float64)
    if n >= atr_period:
        atr_14[atr_period - 1 :] = np.convolve(
            tr_arr, np.ones(atr_period, dtype=np.float64) / float(atr_period), mode="valid"
        )
    return pd.Series(atr_14, index=df.index)


# ============== SCHEDULE ==============
def _norm_date(s: str) -> str:
    """Normalize to YYYYMMDD."""
    s = str(s).strip().replace("-", "")[:8]
    if len(s) == 8 and s.isdigit():
        return s
    return ""


def _coerce_monkey_config_value(key: str, val_str: str) -> Any:
    """Coerce -v string to the MonkeyTraderConfig field type."""
    if key not in MonkeyTraderConfig.__dataclass_fields__:
        return val_str
    default = MonkeyTraderConfig.__dataclass_fields__[key].default
    if isinstance(default, bool):
        return val_str.lower() in ("true", "1", "yes", "on")
    if isinstance(default, int) and not isinstance(default, bool):
        return int(float(val_str))
    if isinstance(default, float):
        return float(val_str)
    return val_str


def _apply_monkey_config_overrides(cfg: MonkeyTraderConfig, set_args: list[str]) -> MonkeyTraderConfig:
    """Apply ``-v KEY=VALUE`` overrides (BRT-style) to MonkeyTraderConfig."""
    if not set_args:
        return cfg
    valid = {f.name for f in fields(MonkeyTraderConfig)}
    alias = {"cash": "brt_cash"}
    updates: dict[str, Any] = {}
    for raw in set_args:
        key, _, val_str = str(raw).partition("=")
        key = alias.get(key.strip(), key.strip())
        val_str = val_str.strip()
        if not key or not val_str:
            continue
        if key not in valid:
            print(f"[MonkeyTrader] Unknown -v key {key!r} (ignored)", file=sys.stderr)
            continue
        updates[key] = _coerce_monkey_config_value(key, val_str)
    if updates:
        print(f"[MonkeyTrader] Config overrides applied: {updates}")
    return replace(cfg, **updates) if updates else cfg


def load_schedule(path: str) -> list[tuple[str, str]]:
    """Load schedule CSV: Date, Symbol. Returns list of (date_yyyymmdd, symbol)."""
    out: list[tuple[str, str]] = []
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        if not r.fieldnames:
            return out
        # Accept Date or DATE, Symbol or SYMBOL
        date_col = next((c for c in r.fieldnames if c.strip().lower() == "date"), None)
        sym_col = next((c for c in r.fieldnames if c.strip().lower() == "symbol"), None)
        if not date_col or not sym_col:
            return out
        for row in r:
            dt = _norm_date(row.get(date_col, ""))
            sym = (row.get(sym_col, "") or "").strip().upper()
            if dt and sym:
                out.append((dt, sym))
    return out


def run_monkey_backtest(
    schedule: list[tuple[str, str]],
    tickers: dict[str, pd.DataFrame],
    cfg: MonkeyTraderConfig,
) -> tuple[list[BRTTrade], list[BRTTrade], dict[str, int]]:
    """
    Run backtest from schedule. Entry = Open of schedule date; same exit logic as BRT
    (including ATR target/stop/increment when configured).
    When skip_entry_if_symbol_open is True, skip a scheduled buy if that symbol is
    already open. Exits are evaluated before entries each bar (same-day re-entry OK).
    Returns (closed_trades, open_trades, stats).
    """
    closed: list[BRTTrade] = []
    open_trades: list[BRTTrade] = []
    stats = {"entries_taken": 0, "entries_skipped_symbol_open": 0}

    atr_by_sym: dict[str, pd.Series] = {
        sym: _compute_atr_14_series(df) for sym, df in tickers.items() if df is not None and not df.empty
    }
    # Trailing-stop: max high since entry per open trade object
    trail_max_high: dict[int, float] = {}

    # Index schedule by date for quick lookup
    by_date: dict[str, list[str]] = {}
    for dt, sym in schedule:
        by_date.setdefault(dt, []).append(sym)

    # All trading days from tickers that appear in schedule
    all_dates: set[pd.Timestamp] = set()
    for sym in set(s for _, s in schedule):
        if sym not in tickers:
            continue
        df = tickers[sym]
        if hasattr(df.index, "date"):
            for d in df.index:
                all_dates.add(pd.Timestamp(d))
        else:
            for _, row in df.iterrows():
                if "Date" in row:
                    all_dates.add(pd.Timestamp(row["Date"]))
    sorted_dates = sorted(all_dates)

    for dt in sorted_dates:
        dt_str = dt.strftime("%Y%m%d") if hasattr(dt, "strftime") else str(dt).replace("-", "")[:8]

        # --- EXIT: check each open position
        still_open: list[BRTTrade] = []
        for open_trade in open_trades:
            sym = open_trade.symbol
            df = tickers.get(sym)
            if df is None or df.empty or dt not in df.index:
                still_open.append(open_trade)
                continue
            row = df.loc[dt]
            op = float(row.get("Open", row.get("Close", 0)))
            hi = float(row.get("High", row.get("Close", 0)))
            lo = float(row.get("Low", row.get("Close", 0)))
            cl = float(row.get("Close", 0))
            tid = id(open_trade)
            trail_max_high[tid] = max(trail_max_high.get(tid, 0.0), hi)

            sp = float(open_trade.stop_price)
            tp = float(open_trade.target_price)
            if getattr(cfg, "atr_increment", 0.0) > 0 and open_trade.entry_price > 0:
                gain_pct = (trail_max_high[tid] - open_trade.entry_price) / open_trade.entry_price * 100.0
                increments = int(gain_pct / cfg.atr_increment)
                stop_raise = increments * 0.01 * open_trade.entry_price
                sp = open_trade.stop_price + stop_raise

            stop_round_decimals = int(getattr(cfg, "stop_compare_round_decimals", 2))
            if stop_round_decimals >= 0:
                op_cmp = round(float(op), stop_round_decimals)
                lo_cmp = round(float(lo), stop_round_decimals)
                sp_cmp = round(float(sp), stop_round_decimals)
            else:
                op_cmp = float(op)
                lo_cmp = float(lo)
                sp_cmp = float(sp)

            gap_down = op_cmp <= sp_cmp
            gap_up = op >= tp
            stop_hit = lo_cmp <= sp_cmp
            target_hit = hi >= tp

            use_atr_mode = (
                getattr(cfg, "atr_target", 0.0) > 0.0
                or getattr(cfg, "atr_stop", 0.0) > 0.0
                or getattr(cfg, "atr_increment", 0.0) > 0.0
            )
            hit_trailing_stop = use_atr_mode and getattr(cfg, "atr_increment", 0.0) > 0 and sp > open_trade.stop_price

            if gap_down:
                exit_price = op
                exit_type = ("ATR_Increment" if hit_trailing_stop else "ATR_STOP") if use_atr_mode else "GAP_DOWN"
            elif gap_up:
                exit_price = op
                exit_type = "ATR_TARGET" if use_atr_mode else "GAP_UP"
            elif stop_hit:
                exit_price = cl if cfg.exit_at_close_when_stopped else sp
                exit_type = ("ATR_Increment" if hit_trailing_stop else "ATR_STOP") if use_atr_mode else "STOP_LOSS"
            elif target_hit:
                exit_price = tp
                exit_type = "ATR_TARGET" if use_atr_mode else "TARGET"
            else:
                still_open.append(open_trade)
                continue

            trail_max_high.pop(tid, None)

            pnl_pct = (exit_price - open_trade.entry_price) / open_trade.entry_price * 100
            pnl_dollars = (cfg.brt_cash / open_trade.entry_price) * (exit_price - open_trade.entry_price)
            open_dt = str(open_trade.date_opened).replace("-", "")[:8]
            days_held = (pd.Timestamp(dt_str[:4] + "-" + dt_str[4:6] + "-" + dt_str[6:8]) -
                         pd.Timestamp(open_dt[:4] + "-" + open_dt[4:6] + "-" + open_dt[6:8])).days
            try:
                start_ts = pd.Timestamp(open_dt[:4] + "-" + open_dt[4:6] + "-" + open_dt[6:8])
                slice_df = df.loc[(df.index >= start_ts) & (df.index <= dt)]
                max_price = float(slice_df["High"].max()) if "High" in slice_df.columns and not slice_df.empty else max(open_trade.entry_price, hi)
            except Exception:
                max_price = max(open_trade.entry_price, hi)
            closed.append(BRTTrade(
                symbol=open_trade.symbol,
                date_opened=open_trade.date_opened,
                entry_price=open_trade.entry_price,
                stop_price=open_trade.stop_price,
                target_price=open_trade.target_price,
                date_closed=dt_str,
                exit_price=exit_price,
                exit_type=exit_type or "",
                days_held=max(0, days_held),
                pnl_pct=pnl_pct,
                pnl_dollars=pnl_dollars,
                max_price=max_price,
                atr_14_at_entry=getattr(open_trade, "atr_14_at_entry", None),
            ))
        open_trades = still_open

        # --- ENTRY: new buys for this date (one per schedule row)
        if dt_str in by_date:
            open_symbols = {t.symbol for t in open_trades}
            for sym in by_date[dt_str]:
                if sym not in tickers:
                    continue
                if cfg.skip_entry_if_symbol_open and sym in open_symbols:
                    stats["entries_skipped_symbol_open"] += 1
                    continue
                df = tickers[sym]
                if df.empty or dt not in df.index:
                    continue
                row = df.loc[dt]
                entry_price = float(row.get("Open", row.get("Close", 0)))
                if entry_price <= 0:
                    continue
                lo = float(row.get("Low", entry_price))
                hi_entry = float(row.get("High", entry_price))
                atr_series = atr_by_sym.get(sym)
                atr_14_val: Optional[float] = None
                if atr_series is not None and dt in atr_series.index:
                    raw = atr_series.loc[dt]
                    atr_14_val = float(raw) if pd.notna(raw) else None

                atr_pct: Optional[float] = None
                if atr_14_val is not None and entry_price > 0:
                    atr_pct = (atr_14_val / entry_price) * 100.0

                if getattr(cfg, "atr_target", 0.0) > 0 and atr_pct is not None:
                    target_price = entry_price * (1.0 + atr_pct * cfg.atr_target / 100.0)
                else:
                    target_price = entry_price * cfg.target_pct

                if getattr(cfg, "atr_stop", 0.0) > 0 and atr_pct is not None:
                    stop_price = entry_price * (1.0 - atr_pct * cfg.atr_stop / 100.0)
                else:
                    stop_price = lo * cfg.stop_pct if cfg.stop_pct_is_multiplier else lo * (1 - cfg.stop_pct)

                ot = BRTTrade(
                    symbol=sym,
                    date_opened=dt_str,
                    entry_price=entry_price,
                    stop_price=stop_price,
                    target_price=target_price,
                    atr_14_at_entry=atr_14_val,
                )
                open_trades.append(ot)
                trail_max_high[id(ot)] = hi_entry
                open_symbols.add(sym)
                stats["entries_taken"] += 1

    return closed, open_trades, stats


# ============== REPORTS (same column order as BRT) ==============
def write_monkey_reports(
    cfg: MonkeyTraderConfig,
    metrics: dict,
    output_dir: str,
    ts: str,
    drive_link: str = "",
) -> None:
    """Write MonkeyTrader_Report and MonkeyTrader_Audit_Report with same columns as BRT for comparison."""
    link = drive_link or f"https://drive.google.com/drive/search?q={ts}"
    drive_link_cell = f'=hyperlink("{link}","{ts}")'
    brt_cfg = cfg.to_brt_config()
    cfg_dict = asdict(brt_cfg)
    # Ensure all CFG_COLS exist for alignment
    row: dict[str, Any] = {"Timestamp_Drive": drive_link_cell, "Param_Name": "System", "Param_Value": "MonkeyTrader", "Score": ""}
    for k in (CFG_COLS if CFG_COLS else cfg_dict.keys()):
        row[k] = cfg_dict.get(k, "") if k in cfg_dict else ""
    row.update(_metrics_to_audit_row(metrics))
    order = list(AUDIT_COLS_ORDER) if AUDIT_COLS_ORDER else sorted(row.keys())
    headers = [c for c in order if c in row]
    values = [row.get(c, "") for c in headers]
    for name, prefix in [("MonkeyTrader_Report", "Report"), ("MonkeyTrader_Audit_Report", "Audit_Report")]:
        path = os.path.join(output_dir, f"{name}_{ts}.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(headers)
            w.writerow(values)
        print(f"[FILE] {path}")


# ============== SCHEDULE GENERATOR (letter-weighted) ==============
def _get_trading_dates(tickers: dict[str, pd.DataFrame], start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
    """Union of dates across tickers in [start, end]."""
    all_dates: set[pd.Timestamp] = set()
    for df in tickers.values():
        if df.empty:
            continue
        idx = df.index if hasattr(df.index, "to_series") else pd.DatetimeIndex(df["Date"]) if "Date" in df.columns else pd.DatetimeIndex([])
        for d in idx:
            t = pd.Timestamp(d)
            if start <= t <= end:
                all_dates.add(t)
    return sorted(all_dates)


def _symbol_list_from_arg(symbol_arg: str) -> list[str]:
    """Parse ``-s`` / ``--symbol``: comma-separated tickers, stripped and uppercased. Empty -> []."""
    if not (symbol_arg or "").strip():
        return []
    return [p.strip().upper() for p in symbol_arg.split(",") if p.strip()]


def _interleave_weighted(items: list[str], counts: dict[str, int]) -> list[str]:
    """Round-robin interleave weighted items (A,B,A,C not AAA,BBB,CCC)."""
    remaining = {k: int(counts.get(k, 0)) for k in items}
    total = sum(remaining.values())
    if total <= 0:
        return []
    out: list[str] = []
    while len(out) < total:
        for item in items:
            if remaining.get(item, 0) > 0:
                out.append(item)
                remaining[item] -= 1
    return out


def _symbol_has_bar(tickers: dict[str, pd.DataFrame], sym: str, dt: pd.Timestamp) -> bool:
    df = tickers.get(sym)
    if df is None or df.empty:
        return False
    return dt in df.index


def _pick_symbol_for_date(
    tickers: dict[str, pd.DataFrame],
    dt: pd.Timestamp,
    primary: str,
    fallbacks: list[str],
) -> Optional[str]:
    """Return first symbol in primary+fallbacks that has OHLCV on dt."""
    for sym in [primary] + list(fallbacks):
        if _symbol_has_bar(tickers, sym, dt):
            return sym
    return None


def generate_schedule(
    ticker_dir: str,
    start_date: str,
    end_date: str,
    output_path: str,
    exclude_spy: bool = True,
    multiplier: float = 1.0,
    symbol_whitelist: Optional[list[str]] = None,
) -> int:
    """
    Generate buy schedule CSV.

    - With ``-s`` / symbol_whitelist: round-robin across listed symbols (AAPL, MSFT, META, …).
    - Full universe: letter-weighted round-robin (A-names, B-names, … interleaved, not blocked).
    multiplier: average buys per trading day.
    """
    data_path = Path(ticker_dir)
    if not data_path.is_dir():
        print(f"[ERR] Not a directory: {ticker_dir}", file=sys.stderr)
        return 0

    files = list(data_path.glob("*.csv"))
    allow = set(symbol_whitelist) if symbol_whitelist else None
    symbols_by_letter: dict[str, list[str]] = {}
    for f in files:
        sym = f.stem.upper()
        if allow is not None and sym not in allow:
            continue
        if exclude_spy and sym == "SPY":
            continue
        if len(sym) < 1:
            continue
        letter = sym[0]
        if letter not in symbols_by_letter:
            symbols_by_letter[letter] = []
        symbols_by_letter[letter].append(sym)

    if allow is not None:
        missing = sorted(allow - {s for syms in symbols_by_letter.values() for s in syms})
        if missing:
            print(
                f"[WARN] -s symbols with no CSV in {ticker_dir}: "
                f"{missing[:20]}{'...' if len(missing) > 20 else ''}",
                file=sys.stderr,
            )

    if not symbols_by_letter:
        if allow is not None:
            print("[ERR] No tickers found for -s whitelist.", file=sys.stderr)
        else:
            print("[ERR] No tickers found.", file=sys.stderr)
        return 0

    # Letter counts and proportions
    total = sum(len(v) for v in symbols_by_letter.values())
    proportions = {L: len(syms) / total for L, syms in symbols_by_letter.items()}
    letters_ordered = sorted(symbols_by_letter.keys())

    # Load tickers to get trading days
    tickers = load_all_tickers(str(data_path))
    if not exclude_spy and (data_path / "SPY.csv").exists():
        try:
            tickers["SPY"] = load_csv(str(data_path / "SPY.csv"))
            if "S" not in symbols_by_letter:
                symbols_by_letter["S"] = []
            if "SPY" not in symbols_by_letter["S"]:
                symbols_by_letter["S"].append("SPY")
        except Exception as e:
            print(f"[WARN] Could not load SPY: {e}", file=sys.stderr)
    if not tickers:
        print("[ERR] No ticker data loaded.", file=sys.stderr)
        return 0

    try:
        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date)
    except Exception:
        print("[ERR] Invalid start_date or end_date.", file=sys.stderr)
        return 0

    trading_dates = _get_trading_dates(tickers, start, end)
    if not trading_dates:
        print("[WARN] No trading dates in range.", file=sys.stderr)
        return 0

    n_days = len(trading_dates)
    total_entries = max(1, round(n_days * multiplier))

    # Build interleaved rotation: symbols (-s) or letters (full universe)
    use_symbol_rotation = bool(symbol_whitelist)
    symbols_ordered: list[str] = []
    if use_symbol_rotation:
        seen: set[str] = set()
        for sym in symbol_whitelist or []:
            su = sym.strip().upper()
            if not su or su in seen:
                continue
            for syms in symbols_by_letter.values():
                if su in syms:
                    symbols_ordered.append(su)
                    seen.add(su)
                    break
        if not symbols_ordered:
            print("[ERR] No -s symbols found in ticker_dir.", file=sys.stderr)
            return 0
        base_n = total_entries // len(symbols_ordered)
        rem_n = total_entries % len(symbols_ordered)
        sym_counts = {
            s: base_n + (1 if i < rem_n else 0)
            for i, s in enumerate(symbols_ordered)
        }
        rotation = _interleave_weighted(symbols_ordered, sym_counts)
    else:
        letter_counts = {
            L: max(0, round(proportions[L] * total_entries)) for L in letters_ordered
        }
        # Trim/pad letter counts to exactly total_entries
        while sum(letter_counts.values()) > total_entries and letter_counts:
            for L in letters_ordered:
                if letter_counts[L] > 0 and sum(letter_counts.values()) > total_entries:
                    letter_counts[L] -= 1
        while sum(letter_counts.values()) < total_entries and letters_ordered:
            L = letters_ordered[sum(letter_counts.values()) % len(letters_ordered)]
            letter_counts[L] = letter_counts.get(L, 0) + 1
        rotation = _interleave_weighted(letters_ordered, letter_counts)

    base = total_entries // n_days
    remainder = total_entries % n_days
    rotation_index = 0
    cursor: dict[str, int] = {L: 0 for L in letters_ordered}
    rows: list[tuple[str, str]] = []

    for day_index, dt in enumerate(trading_dates):
        n_this_day = base + (1 if day_index < remainder else 0)
        if n_this_day <= 0:
            continue
        dt_str = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]
        for _ in range(n_this_day):
            if rotation_index >= len(rotation):
                break
            slot = rotation[rotation_index]
            rotation_index += 1

            if use_symbol_rotation:
                sym = slot
                if not _symbol_has_bar(tickers, sym, dt):
                    # Try next symbols in whitelist order for this date
                    idx = symbols_ordered.index(sym) if sym in symbols_ordered else 0
                    alt = [
                        symbols_ordered[(idx + k) % len(symbols_ordered)]
                        for k in range(1, len(symbols_ordered))
                    ]
                    sym = _pick_symbol_for_date(tickers, dt, sym, alt)
                    if sym is None:
                        continue
                rows.append((dt_str, sym))
                continue

            L = slot
            syms = symbols_by_letter.get(L, [])
            if not syms:
                continue
            idx = cursor[L] % len(syms)
            sym = syms[idx]
            cursor[L] += 1
            if not _symbol_has_bar(tickers, sym, dt):
                found = _pick_symbol_for_date(
                    tickers,
                    dt,
                    sym,
                    [s for s in syms if s != sym],
                )
                if found is None:
                    continue
                sym = found
            rows.append((dt_str, sym))

    universe = sorted({sym for _, sym in rows})
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Symbol"])
        w.writerows(rows)
    print(
        f"[OK] Wrote {len(rows)} rows to {output_path} "
        f"({len(universe)} symbols, ~{len(rows)/max(1,n_days):.1f} buys/day, multiplier={multiplier})"
    )
    return len(rows)


# ============== MAIN ==============
def main() -> int:
    ap = argparse.ArgumentParser(description="MonkeyTrader: schedule-driven backtest (same target/stop and reporting as BRT)")
    sub = ap.add_subparsers(dest="cmd", required=True, help="Command: run (backtest) or generate (schedule)")
    # run: backtest from schedule
    run_p = sub.add_parser("run", help="Run backtest from a schedule CSV")
    run_p.add_argument("schedule_csv", help="Path to schedule CSV (Date, Symbol)")
    run_p.add_argument("data_dir", nargs="?", default="data/newdata/data", help="Ticker data directory")
    run_p.add_argument("--output-dir", "-o", default="drive", help="Output directory")
    run_p.add_argument("--drive-link", default="", help="Override Drive link in report")
    run_p.add_argument("--cash", type=float, default=47500, help="Position size per trade")
    run_p.add_argument("--stop-pct", type=float, default=0.934, help="Stop (multiplier of bar low)")
    run_p.add_argument("--target-pct", type=float, default=1.29, help="Target (multiplier of entry)")
    run_p.add_argument(
        "--atr-target",
        type=float,
        default=0.0,
        help="If >0: target = entry * (1 + ATR%%_at_entry * atr_target/100); else use --target-pct (same as BRT)",
    )
    run_p.add_argument(
        "--atr-stop",
        type=float,
        default=0.0,
        help="If >0: stop = entry * (1 - ATR%%_at_entry * atr_stop/100); else use --stop-pct (same as BRT)",
    )
    run_p.add_argument(
        "--atr-increment",
        type=float,
        default=0.0,
        help="If >0: trailing stop — each atr_increment%% gain from entry high raises stop by 1%% of entry (same as BRT)",
    )
    run_p.add_argument("--exit-at-close-when-stopped", action="store_true", help="Use bar close as exit when stop hit")
    run_p.add_argument(
        "--allow-duplicate-symbol-entries",
        action="store_true",
        help="Allow opening another position in a symbol while one is already open (old behavior).",
    )
    run_p.add_argument(
        "-v",
        "--set",
        dest="config_set",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Override run config (e.g. -v target_pct=1.021 -v stop_pct=0.903). "
        "Keys: target_pct, stop_pct, brt_cash (or cash), atr_target, atr_stop, atr_increment, "
        "skip_entry_if_symbol_open, exit_at_close_when_stopped.",
    )
    run_p.add_argument(
        "-s",
        "--symbol",
        default="",
        help="Optional: only load OHLCV for these tickers (comma-separated). Schedule rows for other symbols are skipped.",
    )
    # generate: letter-weighted schedule
    gen = sub.add_parser("generate", help="Generate letter-weighted buy schedule (Date, Symbol)")
    gen.add_argument("ticker_dir", help="Directory of ticker CSVs for symbol list and trading calendar")
    gen.add_argument("start_date", help="Start date (YYYY-MM-DD or YYYYMMDD)")
    gen.add_argument("end_date", help="End date (YYYY-MM-DD or YYYYMMDD)")
    gen.add_argument("-o", "--output", default="MonkeyTrader_Schedule.csv", help="Output schedule CSV path")
    gen.add_argument(
        "-s",
        "--symbol",
        default="",
        help="Ticker whitelist for schedule generation (comma-separated, e.g. META,AAPL,MSFT). Default: all CSVs in ticker_dir.",
    )
    gen.add_argument("--include-spy", action="store_true", help="Include SPY in symbol universe")
    gen.add_argument(
        "-m",
        "--multiplier",
        "--buys-per-day",
        type=float,
        default=2.4,
        dest="multiplier",
        help="Average buys per trading day (default 2.4). Total schedule rows ≈ trading_days × multiplier.",
    )

    args = ap.parse_args()

    if args.cmd == "generate":
        sym_list = _symbol_list_from_arg(getattr(args, "symbol", "") or "")
        n = generate_schedule(
            args.ticker_dir,
            args.start_date,
            args.end_date,
            args.output,
            exclude_spy=not getattr(args, "include_spy", False),
            multiplier=getattr(args, "multiplier", 1.0),
            symbol_whitelist=sym_list or None,
        )
        return 0 if n > 0 else 1

    # Backtest
    schedule = load_schedule(args.schedule_csv)
    if not schedule:
        print(f"[ERR] No rows in schedule: {args.schedule_csv}", file=sys.stderr)
        return 1

    sym_filter = set(_symbol_list_from_arg(getattr(args, "symbol", "") or ""))
    if sym_filter:
        before = len(schedule)
        schedule = [(dt, sym) for dt, sym in schedule if sym in sym_filter]
        skipped = before - len(schedule)
        if skipped:
            print(f"[MonkeyTrader] -s filter: kept {len(schedule)} schedule rows, skipped {skipped}")
        if not schedule:
            print("[ERR] No schedule rows left after -s filter.", file=sys.stderr)
            return 1

    script_dir = Path(__file__).parent.resolve()
    repo_root = script_dir.parent
    data_dir = Path(args.data_dir)
    if not data_dir.is_absolute():
        data_dir = repo_root / data_dir
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = repo_root / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    symbols_needed = set(s for _, s in schedule)
    tickers = load_all_tickers(str(data_dir))
    missing = symbols_needed - set(tickers.keys())
    if missing:
        print(f"[WARN] Missing ticker data for: {sorted(missing)[:20]}{'...' if len(missing) > 20 else ''}", file=sys.stderr)
    tickers = {s: tickers[s] for s in symbols_needed if s in tickers}
    # Ensure DatetimeIndex for date lookups
    for sym, df in list(tickers.items()):
        if df is not None and not df.empty:
            if not isinstance(df.index, pd.DatetimeIndex):
                if "Date" in df.columns:
                    df = df.set_index("Date")
                df.index = pd.to_datetime(df.index)
                tickers[sym] = df

    cfg = MonkeyTraderConfig(
        brt_cash=args.cash,
        stop_pct=args.stop_pct,
        target_pct=args.target_pct,
        exit_at_close_when_stopped=args.exit_at_close_when_stopped,
        atr_target=float(args.atr_target),
        atr_stop=float(args.atr_stop),
        atr_increment=float(args.atr_increment),
        skip_entry_if_symbol_open=not getattr(args, "allow_duplicate_symbol_entries", False),
    )
    cfg = _apply_monkey_config_overrides(cfg, getattr(args, "config_set", []) or [])
    if cfg.atr_target > 0 or cfg.atr_stop > 0 or cfg.atr_increment > 0:
        print(
            f"[MonkeyTrader] ATR mode: atr_target={cfg.atr_target} atr_stop={cfg.atr_stop} "
            f"atr_increment={cfg.atr_increment}"
        )
    closed, open_list, run_stats = run_monkey_backtest(schedule, tickers, cfg)
    skipped = int(run_stats.get("entries_skipped_symbol_open", 0))
    if skipped:
        print(
            f"[MonkeyTrader] Skipped {skipped} scheduled entries "
            f"(symbol already open; {run_stats.get('entries_taken', 0)} entries taken)"
        )

    ts = datetime.now().strftime("%y%m%d%H%M%S")
    brt_cfg = cfg.to_brt_config()
    metrics = compute_metrics(closed, brt_cfg)
    if cfg.compute_equity_metrics and HAS_EQUITY_METRICS and closed and _compute_realized_ledger_equity_metrics:
        try:
            equity = _compute_realized_ledger_equity_metrics(
                closed, open_list, float(cfg.brt_cash), extend_open_to_today=True
            )
            metrics["Max_Drawdown"] = equity["Max_Drawdown"]
            metrics["Max_Days_Underwater"] = equity["Max_Days_Underwater"]
            metrics["Pct_Days_Underwater"] = equity["Pct_Days_Underwater"]
            md = equity["Max_Drawdown"]
            if md and str(md).strip() != "N/A":
                try:
                    pct_val = float(str(md).replace("%", "").strip()) / 100
                    metrics["DD_Per_Trade"] = f"{(pct_val / len(closed)):.4f}" if closed else "N/A"
                except (ValueError, TypeError):
                    metrics["DD_Per_Trade"] = "N/A"
            else:
                metrics["DD_Per_Trade"] = "N/A"
        except Exception as e:
            print(f"[WARN] Equity metrics failed: {e}", file=sys.stderr)

    write_brt_closed(closed, str(output_dir / f"MonkeyTrader_Closed_{ts}.csv"), cfg=brt_cfg)
    write_brt_open(open_list, str(output_dir / f"MonkeyTrader_Open_{ts}.csv"), tickers=tickers, brt_cash=cfg.brt_cash, closed=closed, cfg=brt_cfg)
    write_monkey_reports(cfg, metrics, str(output_dir), ts, args.drive_link)

    print(f"[OK] MonkeyTrader complete: {len(closed)} closed, {len(open_list)} open. Outputs in {output_dir} (ts={ts})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
