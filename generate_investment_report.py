#!/usr/bin/env python3
"""
Generate a Google-Docs-friendly HTML investment report for BRT / IND / RL / YH / MTS / WPBR / RS / SB / VZ systems.

Data sources:
  - Accounts_History full exports in Downloads (numbered or timestamped; recent-history sells merged in)
  - History_for_Account_<acct> (N).csv per-account exports (merged when newer than Accounts_History)
  - getTarget_output.csv + gettarget_positions.csv (authoritative open book; persists across Fidelity export windows)
  - closed_positions_log.csv — append-only permanent closed round-trips (survives rolling Fidelity export windows)
  - trade_system_registry.csv — canonical (symbol, purchase_date) -> system
  - Latest IND/BRT/RL/YH/MTS/WPBR/RS/SB/VZ Closed & Open CSVs in Drive/ (per-entry DATE_OPENED)
  - Latest IND/BRT/RL/YH/MTS/WPBR/RS_Scanner_*.csv in Drive/ (matched to latest core run per engine)
  - Latest SB_Watchlist_*.csv when no Scanner (StockBee watchlist fallback)
  - VZ: VZ_house_last_run_ts.txt / house-sized pin / latest house Summary (VZ_new56; not ALL)
  - Per-system Closed CSVs supply Prior avg days held (mean DAYS_HELD) on scanner/watchlist rows
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import re
import shutil
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from sell_report_lib import (
    find_all_pending_sells,
    sell_report_html_section,
    write_sell_report_csv,
)

ROOT = Path(__file__).resolve().parent
import sys

if str(ROOT / "stock_analysis") not in sys.path:
    sys.path.insert(0, str(ROOT / "stock_analysis"))
from mts_universe import MTS_SYMBOLS as _MTS_SYMBOLS_LIST
from vec_zones import hvn_gate_fields_at_bar

DOWNLOADS = Path(r"C:\Users\songg\Downloads")
DRIVE = ROOT / "Drive"
LOGO_FILENAME = "TBN_Logo.png"
SHOWCASE_AAPL_IMAGE_FILENAME = "AAPL_Showcase.jpg"
SHOWCASE_AAPL_IMAGE_DOWNLOADS = Path(
    r"C:\Users\songg\Downloads\c1e0518d-f720-4590-8854-af70231e082f.jpg"
)
LOGO_DOWNLOADS = DOWNLOADS / LOGO_FILENAME
LOGO_DOCS = ROOT / "docs" / LOGO_FILENAME
LOGO_DISPLAY_MAX_HEIGHT_PX = 216  # 3× prior 72px header size
LOGO_RETINA_SCALE = 2
DEFAULT_POSITIONS = ROOT / "gettarget_positions.csv"
DEFAULT_GETTARGET = ROOT / "getTarget_output.csv"
DEFAULT_TRADE_REGISTRY = ROOT / "trade_system_registry.csv"
DEFAULT_CLOSED_LOG = ROOT / "closed_positions_log.csv"
CLOSED_LOG_COLUMNS = (
    "symbol",
    "system",
    "buy_date",
    "buy_price",
    "sell_date",
    "sell_price",
    "qty",
    "pnl_pct",
    "pnl_dollars",
    "original_qty",
    "purchase_value",
    "recorded_at",
)
DEFAULT_OHLCV_DATA_DIR = Path(r"C:\Users\songg\Downloads\stockresearch\data\newdata\data")
CLOSED_SINCE = date(2026, 5, 25)
# Match rocket_brt rl_cash / brt_cash (47500); 50k excluded normal RL fills (~47–48k).
MIN_POSITION_VALUE = 47_500.0
# Still show smaller lots when (symbol, entry_date) is in the system map (registry/engine).
MIN_REGISTRY_TRACKED_VALUE = 5_000.0
REPORT_SYSTEMS = ("BRT", "IND", "RL", "YH", "MTS", "WPBR", "RS", "SB", "VZ")
REPORT_TITLE = f"{len(REPORT_SYSTEMS)}-System Investment Report"
REPORT_SYSTEM_LABELS = {
    "IND": "IND (deprecated)",
    "SB": "SB",
    "VZ": "VZ",
}
_SYSTEM_ALIASES = {"PBR": "WPBR"}


def _normalize_report_system(system: str) -> str:
    s = str(system).strip().upper()
    return _SYSTEM_ALIASES.get(s, s)
# Broker fill date vs engine DATE_OPENED can differ by a session; match within this window.
ENTRY_DATE_MATCH_DAYS = 5
ENTRY_PRICE_MATCH_PCT = 2.0
ET = ZoneInfo("America/New_York")
MARKET_OPEN_ET = time(9, 30)
MARKET_CLOSE_ET = time(16, 0)
POST_CLOSE_REFRESH_END_ET = time(17, 0)
STALE_PRICE_MINUTES = 55
# Set True or pass --showcase-aapl to restore the AAPL buy-and-hold illustrative block.
INCLUDE_SHOWCASE_AAPL_SECTION = False

_BRT_SYMBOLS = {
    "AAPL", "ABBV", "ACN", "ADBE", "ADI", "AMAT", "AMD", "AMZN", "AU", "AVGO", "AXP", "BABA", "BAC",
    "CDNS", "CI", "CRM", "CRWD", "DIS", "GILD", "GOOG", "GOOGL", "HD", "JPM", "KO", "KR", "LOW", "LYV",
    "META", "MPC", "MS", "MSFT", "MU", "NEM", "NFLX", "NVDA", "OMER", "ORCL", "PFE", "PG", "PLTR", "PM",
    "PPTA", "SHOP", "TMUS", "TSLA", "TSM", "UNH", "V", "WFC", "WMT", "XOM", "ENPH", "TEAM", "BEP", "VLO",
    "CRUS", "LUMN",
}
_RL_SYMBOLS = {
    "TSLA", "AMD", "INTC", "XOM", "LRCX", "NFLX", "PLTR", "KLAC", "WFC", "ADI", "STX", "WDC", "ANET", "APP",
    "TOELY", "IBKR", "CRWD", "NEM", "AEM", "CNQ", "FCX", "FTNT", "MPWR", "MELI", "B", "FIX", "RCL",
    "GM", "TER", "OKE", "OXY", "AU", "TRGP", "DVN", "FLEX", "CCJ", "ARGX", "CLS", "IDXX", "EME", "GFI",
    "ARES", "KGC", "ESLT", "STLD", "MTZ", "TECK", "WDAY", "TWLO", "NRG", "RMD", "FOXA", "FTAI", "NTRA", "FTI",
    "MTSI", "TPR", "STRL", "CFG", "FOX", "ALB", "FN", "KEY", "AKAM", "TEAM", "BEP", "LEN", "CRS", "RL",
    "DKS", "AMKR", "NXT", "LYV",
}

_MTS_SYMBOLS = set(_MTS_SYMBOLS_LIST)

_ENGINE_CSV_RE = re.compile(
    r"^(?P<engine>BRT|IND|RL|YH|MTS|WPBR|PBR|RS|SB|VZ)_(?P<kind>Closed|Open)_(?P<ts>\d{12})\.csv$",
    re.I,
)


def _position_value(qty: float, price: float) -> float:
    return abs(float(qty)) * float(price)


def _meets_position_size_threshold(
    purchase_value: float,
    symbol: str,
    buy_date: date,
    sys_map: dict[tuple[str, str], str],
    *,
    min_position_value: float = MIN_POSITION_VALUE,
) -> bool:
    pv = float(purchase_value or 0)
    if pv >= min_position_value:
        return True
    key = (symbol.upper(), buy_date.isoformat())
    if key in sys_map:
        return pv >= MIN_REGISTRY_TRACKED_VALUE
    return False


def _normalize_entry_date(raw) -> str:
    """Canonical registry key date: YYYY-MM-DD."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return ""
    s = str(raw).strip()
    if not s or s.lower() in ("nan", "none"):
        return ""
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    try:
        return pd.Timestamp(s).date().isoformat()
    except Exception:
        return s[:10] if len(s) >= 10 else ""


def _merge_system_maps(*layers: dict[tuple[str, str], str]) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    for layer in layers:
        for key, sys in layer.items():
            sym, d = key
            if sym and d:
                out[(sym.upper(), d)] = sys.upper()
    return out


def _latest_engine_csvs(drive_dir: Path) -> dict[tuple[str, str], Path]:
    """Newest Closed/Open CSV per (engine, kind)."""
    best: dict[tuple[str, str], tuple[str, Path]] = {}
    for path in drive_dir.glob("*_*.csv"):
        m = _ENGINE_CSV_RE.match(path.name)
        if not m:
            continue
        eng = m.group("engine").upper()
        if eng == "PBR":
            eng = "WPBR"  # legacy file prefix
        kind = m.group("kind").title()
        ts = m.group("ts")
        key = (eng, kind)
        if key not in best or ts > best[key][0]:
            best[key] = (ts, path)
    return {k: v[1] for k, v in best.items()}


def _load_engine_trades_from_drive(drive_dir: Path) -> dict[tuple[str, str], str]:
    """
    Map (symbol, entry_date) -> engine from latest BRT/IND/RL/YH/MTS/WPBR/RS/SB/VZ Closed and Open CSVs.
    Same symbol may have different systems on different entry dates.
    """
    out: dict[tuple[str, str], str] = {}
    for (eng, _kind), path in _latest_engine_csvs(drive_dir).items():
        try:
            df = pd.read_csv(path, dtype=str, keep_default_na=False, low_memory=False)
        except Exception:
            continue
        cols = {c.upper(): c for c in df.columns}
        sym_c = cols.get("SYMBOL")
        date_c = cols.get("DATE_OPENED")
        if not sym_c or not date_c:
            continue
        for _, r in df.iterrows():
            sym = str(r.get(sym_c, "")).strip().upper()
            d = _normalize_entry_date(r.get(date_c, ""))
            if sym and d:
                out[(sym, d)] = eng
    return out


def _load_csv_position_maps(
    positions_path: Path,
    gettarget_path: Path,
) -> tuple[dict[tuple[str, str], str], dict[tuple[str, str], float]]:
    """Date-specific rows only — never symbol-wide defaults. Also returns entry prices when present."""
    out: dict[tuple[str, str], str] = {}
    prices: dict[tuple[str, str], float] = {}
    for path in (positions_path, gettarget_path):
        if not path.is_file():
            continue
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        cols = {c.lower(): c for c in df.columns}
        sym_c = cols.get("symbol", "symbol")
        date_c = cols.get(
            "purchase_date",
            cols.get("purchasedate", cols.get("entrydateused", "purchase_date")),
        )
        sys_c = cols.get("system", "system")
        px_c = cols.get("entry_price", cols.get("entryprice", None))
        for _, r in df.iterrows():
            sym = str(r.get(sym_c, "")).strip().upper()
            d = _normalize_entry_date(r.get(date_c, ""))
            sys = _normalize_report_system(str(r.get(sys_c, "")).strip().upper())
            if sym and d and sys in REPORT_SYSTEMS:
                out[(sym, d)] = sys
                if px_c:
                    try:
                        prices[(sym, d)] = float(r.get(px_c, "") or 0)
                    except (TypeError, ValueError):
                        pass
    return out, prices


def _load_registry_with_prices(path: Path) -> tuple[dict[tuple[str, str], str], dict[tuple[str, str], float]]:
    if not path.is_file():
        return {}, {}
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    cols = {c.lower(): c for c in df.columns}
    sym_c = cols.get("symbol", "symbol")
    date_c = cols.get("purchase_date", cols.get("entry_date", cols.get("date_opened", "purchase_date")))
    sys_c = cols.get("system", "system")
    px_c = cols.get("entry_price", None)
    out: dict[tuple[str, str], str] = {}
    prices: dict[tuple[str, str], float] = {}
    for _, r in df.iterrows():
        sym = str(r.get(sym_c, "")).strip().upper()
        d = _normalize_entry_date(r.get(date_c, ""))
        sys = _normalize_report_system(str(r.get(sys_c, "")).strip().upper())
        if sym and d and sys in REPORT_SYSTEMS:
            out[(sym, d)] = sys
            if px_c:
                try:
                    prices[(sym, d)] = float(r.get(px_c, "") or 0)
                except (TypeError, ValueError):
                    pass
    return out, prices


def _build_full_system_map(
    *,
    drive_dir: Path,
    positions_path: Path,
    gettarget_path: Path,
    registry_path: Path,
) -> tuple[dict[tuple[str, str], str], dict[tuple[str, str], float]]:
    """
    Priority (low → high): engine Closed/Open → gettarget CSVs → trade_system_registry.csv.
    """
    pos_map, pos_px = _load_csv_position_maps(positions_path, gettarget_path)
    reg_map, reg_px = _load_registry_with_prices(registry_path)
    sys_map = _merge_system_maps(
        _load_engine_trades_from_drive(drive_dir),
        pos_map,
        reg_map,
    )
    entry_prices = {**pos_px, **reg_px}
    return sys_map, entry_prices


def _legacy_symbol_fallback(symbol: str) -> str:
    if symbol in _RL_SYMBOLS and symbol not in _BRT_SYMBOLS:
        return "RL"
    if symbol in _BRT_SYMBOLS:
        return "BRT"
    return "IND"


def _lookup_system(
    symbol: str,
    buy_date: date,
    buy_price: float,
    sys_map: dict[tuple[str, str], str],
    entry_prices: Optional[dict[tuple[str, str], float]] = None,
) -> str:
    """
    Resolve system for one broker entry lot (symbol + buy date [+ price]).
    Never uses symbol-only mapping — same ticker can be IND on one date and BRT on another.
    """
    sym = symbol.upper()
    ds = buy_date.isoformat()
    if (sym, ds) in sys_map:
        return sys_map[(sym, ds)]

    try:
        buy_ts = pd.Timestamp(ds)
    except Exception:
        return _legacy_symbol_fallback(sym)

    date_candidates: list[tuple[int, str]] = []
    price_candidates: list[tuple[float, int, str]] = []
    for (s, d), sys in sys_map.items():
        if s != sym or not d:
            continue
        try:
            delta = abs((buy_ts - pd.Timestamp(d)).days)
        except Exception:
            continue
        if delta <= ENTRY_DATE_MATCH_DAYS:
            date_candidates.append((delta, sys))
        if entry_prices and buy_price > 0:
            ref_px = entry_prices.get((s, d))
            if ref_px and ref_px > 0:
                pct_diff = abs(buy_price - ref_px) / ref_px * 100.0
                if pct_diff <= ENTRY_PRICE_MATCH_PCT and delta <= ENTRY_DATE_MATCH_DAYS:
                    price_candidates.append((pct_diff, delta, sys))

    if price_candidates:
        price_candidates.sort(key=lambda x: (x[0], x[1]))
        return price_candidates[0][2]
    if date_candidates:
        date_candidates.sort(key=lambda x: (x[0], x[1]))
        return date_candidates[0][1]
    return _legacy_symbol_fallback(sym)


def _persist_trade_registry(
    registry_path: Path,
    sys_map: dict[tuple[str, str], str],
    extra_rows: Optional[list[tuple[str, str, str]]] = None,
) -> None:
    """Write canonical (symbol, purchase_date, system) registry for long-term maintenance."""
    rows: dict[tuple[str, str], str] = dict(sys_map)
    for sym, d, sys in extra_rows or []:
        if sym and d and sys:
            rows[(sym.upper(), _normalize_entry_date(d))] = sys.upper()
    if not rows:
        return
    df = pd.DataFrame(
        [
            {"symbol": sym, "purchase_date": d, "system": sys}
            for (sym, d), sys in sorted(rows.items())
        ]
    )
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(registry_path, index=False)


@dataclass
class Lot:
    symbol: str
    buy_date: date
    buy_price: float
    qty: float
    system: str
    original_qty: float = 0.0


@dataclass
class ClosedTrade:
    symbol: str
    system: str
    buy_date: date
    buy_price: float
    sell_date: date
    sell_price: float
    qty: float
    pnl_pct: float
    pnl_dollars: float
    original_qty: float = 0.0
    purchase_value: float = 0.0


def _closed_trade_dedup_key(t: ClosedTrade) -> tuple:
    return (
        t.symbol.upper(),
        t.buy_date.isoformat(),
        t.sell_date.isoformat(),
        round(float(t.qty), 4),
        round(float(t.sell_price), 4),
        round(float(t.buy_price), 4),
    )


def _closed_trade_to_log_row(t: ClosedTrade, recorded_at: str) -> dict:
    return {
        "symbol": t.symbol.upper(),
        "system": t.system,
        "buy_date": t.buy_date.isoformat(),
        "buy_price": round(float(t.buy_price), 6),
        "sell_date": t.sell_date.isoformat(),
        "sell_price": round(float(t.sell_price), 6),
        "qty": round(float(t.qty), 4),
        "pnl_pct": round(float(t.pnl_pct), 6),
        "pnl_dollars": round(float(t.pnl_dollars), 2),
        "original_qty": round(float(t.original_qty or t.qty), 4),
        "purchase_value": round(float(t.purchase_value or 0), 2),
        "recorded_at": recorded_at,
    }


def _closed_trade_from_log_row(row: pd.Series) -> Optional[ClosedTrade]:
    try:
        sym = str(row.get("symbol", "")).strip().upper()
        if not sym:
            return None
        buy_date = pd.to_datetime(str(row.get("buy_date", "")), errors="coerce").date()
        sell_date = pd.to_datetime(str(row.get("sell_date", "")), errors="coerce").date()
        if buy_date is None or sell_date is None or pd.isna(buy_date) or pd.isna(sell_date):
            return None
        return ClosedTrade(
            symbol=sym,
            system=_normalize_report_system(str(row.get("system", "")).strip().upper()),
            buy_date=buy_date,
            buy_price=float(row.get("buy_price", 0)),
            sell_date=sell_date,
            sell_price=float(row.get("sell_price", 0)),
            qty=float(row.get("qty", 0)),
            pnl_pct=float(row.get("pnl_pct", 0)),
            pnl_dollars=float(row.get("pnl_dollars", 0)),
            original_qty=float(row.get("original_qty", 0) or row.get("qty", 0)),
            purchase_value=float(row.get("purchase_value", 0) or 0),
        )
    except (TypeError, ValueError):
        return None


def _load_closed_positions_log(
    path: Path,
    *,
    closed_since: date,
    min_position_value: float = MIN_POSITION_VALUE,
    sys_map: Optional[dict[tuple[str, str], str]] = None,
) -> list[ClosedTrade]:
    if not path.is_file():
        return []
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    out: list[ClosedTrade] = []
    for _, row in df.iterrows():
        t = _closed_trade_from_log_row(row)
        if t is None:
            continue
        if t.sell_date < closed_since:
            continue
        pv = t.purchase_value or _position_value(t.original_qty or t.qty, t.buy_price)
        if sys_map is not None:
            if not _meets_position_size_threshold(
                pv, t.symbol, t.buy_date, sys_map, min_position_value=min_position_value
            ):
                continue
        elif pv < min_position_value:
            continue
        out.append(t)
    out.sort(key=lambda x: (x.sell_date, x.symbol))
    return out


def _existing_closed_log_keys(path: Path) -> set[tuple]:
    if not path.is_file():
        return set()
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    keys: set[tuple] = set()
    for _, row in df.iterrows():
        t = _closed_trade_from_log_row(row)
        if t is not None:
            keys.add(_closed_trade_dedup_key(t))
    return keys


def _append_closed_positions_log(path: Path, trades: list[ClosedTrade]) -> int:
    """Append closed round-trips not already in the log. Returns count appended."""
    if not trades:
        return 0
    existing = _existing_closed_log_keys(path)
    recorded_at = datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S %Z")
    new_rows: list[dict] = []
    for t in trades:
        key = _closed_trade_dedup_key(t)
        if key in existing:
            continue
        new_rows.append(_closed_trade_to_log_row(t, recorded_at))
        existing.add(key)
    if not new_rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.is_file() or path.stat().st_size == 0
    df = pd.DataFrame(new_rows, columns=list(CLOSED_LOG_COLUMNS))
    df.to_csv(path, mode="a", header=write_header, index=False)
    return len(new_rows)


def _merge_closed_for_report(
    log_trades: list[ClosedTrade],
    fifo_trades: list[ClosedTrade],
) -> list[ClosedTrade]:
    """Union by dedup key; log entry wins on conflict."""
    merged: dict[tuple, ClosedTrade] = {}
    for t in fifo_trades:
        merged[_closed_trade_dedup_key(t)] = t
    for t in log_trades:
        merged[_closed_trade_dedup_key(t)] = t
    out = list(merged.values())
    out.sort(key=lambda x: (x.sell_date, x.symbol))
    return out


def _sync_closed_positions_log(
    log_path: Path,
    fifo_trades: list[ClosedTrade],
    *,
    closed_since: date,
    min_position_value: float,
    sys_map: Optional[dict[tuple[str, str], str]] = None,
) -> tuple[list[ClosedTrade], int]:
    """Append new FIFO closes to the permanent log; return merged list for the report."""
    appended = _append_closed_positions_log(log_path, fifo_trades)
    log_trades = _load_closed_positions_log(
        log_path,
        closed_since=closed_since,
        min_position_value=min_position_value,
        sys_map=sys_map,
    )
    return _merge_closed_for_report(log_trades, fifo_trades), appended


_ACCOUNTS_HISTORY_RE = re.compile(r"^Accounts_History \((\d+)\)\.csv$", re.IGNORECASE)
_ACCOUNTS_TIMESTAMPED_RE = re.compile(
    r"^Accounts_History - \d{4}-\d{2}-\d{2}T[\d.]+\.csv$", re.IGNORECASE
)
_RECENT_HISTORY_RE = re.compile(
    r"^Accounts_History - recent history \((\d+)\)\.csv$", re.IGNORECASE
)
_HISTORY_FOR_ACCOUNT_RE = re.compile(
    r"^History_for_Account_(?P<acct>[A-Z0-9]+)(?: \((?P<num>\d+)\))?\.csv$", re.IGNORECASE
)


def _is_ignored_accounts_export_name(name: str) -> bool:
    n = name.lower()
    return "recent history" in n or "total accounts" in n or n.endswith("total accounts_history.csv")


def _is_full_accounts_export(path: Path) -> bool:
    if _is_ignored_accounts_export_name(path.name):
        return False
    return bool(
        _ACCOUNTS_HISTORY_RE.match(path.name) or _ACCOUNTS_TIMESTAMPED_RE.match(path.name)
    )


def _candidate_full_accounts_exports(downloads: Path) -> list[Path]:
    return [p for p in downloads.glob("Accounts_History*.csv") if _is_full_accounts_export(p)]


def _candidate_account_history_exports(downloads: Path) -> list[Path]:
    return [p for p in downloads.glob("History_for_Account*.csv") if _HISTORY_FOR_ACCOUNT_RE.match(p.name)]


def _latest_account_history_export(downloads: Path) -> Optional[Path]:
    """Best per-account Fidelity export (History_for_Account_<acct> (N).csv)."""
    scored: list[tuple[date, int, float, Path]] = []
    for path in _candidate_account_history_exports(downloads):
        m = _HISTORY_FOR_ACCOUNT_RE.match(path.name)
        max_d = _max_run_date_in_accounts_file(path) or date.min
        num = int(m.group("num") or 0) if m else 0
        scored.append((max_d, num, path.stat().st_mtime, path))
    if not scored:
        return None
    return max(scored, key=lambda x: (x[0], x[1], x[2]))[3]


def _max_run_date_in_accounts_file(path: Path) -> Optional[date]:
    try:
        df = _load_accounts(path)
    except Exception:
        return None
    if df.empty or "Run Date" not in df.columns:
        return None
    dates = [d for d in df["Run Date"].tolist() if d is not None and not pd.isna(d)]
    return max(dates) if dates else None


def _latest_accounts_history(downloads: Path) -> Path:
    """
    Best full Fidelity export: numbered Accounts_History (N).csv or timestamped
    Accounts_History - 2026-....csv. Prefers the file whose newest Run Date is latest
    (then newest mtime). Ignores recent-history and total exports.
    """
    candidates = _candidate_full_accounts_exports(downloads)
    if not candidates:
        raise FileNotFoundError(
            f"No full Accounts_History export in {downloads} "
            "(need Accounts_History (N).csv or Accounts_History - 2026-....csv)"
        )
    scored: list[tuple[date, float, Path]] = []
    for path in candidates:
        max_d = _max_run_date_in_accounts_file(path) or date.min
        scored.append((max_d, path.stat().st_mtime, path))
    return max(scored, key=lambda x: (x[0], x[1]))[2]


def _latest_recent_history_export(downloads: Path) -> Optional[Path]:
    numbered: list[tuple[int, float, Path]] = []
    for path in downloads.glob("Accounts_History*.csv"):
        m = _RECENT_HISTORY_RE.match(path.name)
        if m:
            numbered.append((int(m.group(1)), path.stat().st_mtime, path))
    if not numbered:
        return None
    return max(numbered, key=lambda x: (x[0], x[1]))[2]


def _sell_row_fingerprint(run_date: date, symbol: str, quantity: float, price: float) -> tuple:
    return (
        run_date,
        str(symbol).upper(),
        int(round(abs(float(quantity)))),
        round(float(price), 2),
    )


def _sell_fingerprints(df: pd.DataFrame) -> set[tuple]:
    out: set[tuple] = set()
    if df.empty:
        return out
    for _, r in df.iterrows():
        action = str(r.get("Action", ""))
        if "YOU SOLD" not in action:
            continue
        rd = r.get("Run Date")
        if rd is None or (isinstance(rd, float) and pd.isna(rd)):
            continue
        try:
            out.add(
                _sell_row_fingerprint(
                    rd, str(r.get("Symbol", "")), float(r.get("Quantity", 0)), float(r.get("Price", 0))
                )
            )
        except (TypeError, ValueError):
            continue
    return out


def _buy_row_fingerprint(run_date: date, symbol: str, quantity: float, price: float) -> tuple:
    return (
        run_date,
        str(symbol).upper(),
        int(round(abs(float(quantity)))),
        round(float(price), 2),
    )


def _buy_fingerprints(df: pd.DataFrame) -> set[tuple]:
    out: set[tuple] = set()
    if df.empty:
        return out
    for _, r in df.iterrows():
        action = str(r.get("Action", ""))
        if "YOU BOUGHT" not in action:
            continue
        rd = r.get("Run Date")
        if rd is None or (isinstance(rd, float) and pd.isna(rd)):
            continue
        try:
            out.add(
                _buy_row_fingerprint(
                    rd, str(r.get("Symbol", "")), float(r.get("Quantity", 0)), float(r.get("Price", 0))
                )
            )
        except (TypeError, ValueError):
            continue
    return out


def _load_tracked_position_rows(positions_path: Path) -> list[dict]:
    """
    Authoritative open-position book (gettarget_positions.csv).
    Rows stay on the report until removed from this file (typically after a sell).
    """
    if not positions_path.is_file():
        return []
    df = pd.read_csv(positions_path, dtype=str, keep_default_na=False)
    cols = {c.lower(): c for c in df.columns}
    sym_c = cols.get("symbol", "symbol")
    date_c = cols.get(
        "purchase_date",
        cols.get("purchasedate", cols.get("entrydateused", "purchase_date")),
    )
    sys_c = cols.get("system", "system")
    px_c = cols.get("entry_price", cols.get("entryprice", None))
    qty_c = cols.get("qty", cols.get("quantity", cols.get("shares", None)))
    rows: list[dict] = []
    for _, r in df.iterrows():
        sym = str(r.get(sym_c, "")).strip().upper()
        d_raw = r.get(date_c, "")
        d_norm = _normalize_entry_date(d_raw)
        if not sym or not d_norm:
            continue
        try:
            bd = pd.Timestamp(d_norm).date()
        except Exception:
            continue
        sys = _normalize_report_system(str(r.get(sys_c, "")).strip().upper())
        entry_price = 0.0
        if px_c:
            try:
                entry_price = float(r.get(px_c, "") or 0)
            except (TypeError, ValueError):
                entry_price = 0.0
        qty = 0.0
        if qty_c:
            try:
                qty = abs(float(r.get(qty_c, "") or 0))
            except (TypeError, ValueError):
                qty = 0.0
        rows.append(
            {
                "symbol": sym,
                "buy_date": bd,
                "entry_price": entry_price,
                "system": sys if sys in REPORT_SYSTEMS else "",
                "qty": qty,
            }
        )
    return rows


def _position_has_buy_in_df(df: pd.DataFrame, symbol: str, buy_date: date) -> bool:
    if df.empty:
        return False
    mask = (
        (df["Symbol"].astype(str).str.upper() == symbol.upper())
        & (df["Run Date"] == buy_date)
        & df["Action"].astype(str).str.contains("YOU BOUGHT", na=False)
    )
    return bool(mask.any())


def _find_buy_rows_in_exports(
    downloads: Path,
    symbol: str,
    buy_date: date,
    entry_price: float = 0.0,
) -> list[dict]:
    """
    Search all full Fidelity exports for a matching buy (same symbol + run date).
    Used when the newest export is a rolling ~30-day window missing older entries.
    """
    sym = symbol.upper()
    matches: list[dict] = []
    for path in _candidate_full_accounts_exports(downloads):
        try:
            df = _load_accounts(path)
        except Exception:
            continue
        sub = df[
            (df["Symbol"].astype(str).str.upper() == sym)
            & (df["Run Date"] == buy_date)
            & df["Action"].astype(str).str.contains("YOU BOUGHT", na=False)
        ]
        for _, r in sub.iterrows():
            try:
                px = float(r["Price"])
            except (TypeError, ValueError):
                continue
            if entry_price > 0 and px > 0:
                tol = abs(px - entry_price) / entry_price * 100.0
                if tol > ENTRY_PRICE_MATCH_PCT:
                    continue
            row = {c: r[c] for c in r.index}
            row["_source"] = path.name
            matches.append(row)
    return matches


def _supplement_accounts_from_tracked_positions(
    base: pd.DataFrame,
    downloads: Path,
    positions_path: Path,
) -> tuple[pd.DataFrame, list[str]]:
    """Append missing YOU BOUGHT rows for gettarget_positions.csv from older exports."""
    tracked = _load_tracked_position_rows(positions_path)
    if not tracked:
        return base, []
    existing = _buy_fingerprints(base)
    extra_rows: list[dict] = []
    notes: list[str] = []
    for pos in tracked:
        sym = pos["symbol"]
        bd = pos["buy_date"]
        if _position_has_buy_in_df(base, sym, bd):
            continue
        for row in _find_buy_rows_in_exports(downloads, sym, bd, float(pos.get("entry_price") or 0)):
            fp = _buy_row_fingerprint(bd, sym, float(row["Quantity"]), float(row["Price"]))
            if fp in existing:
                continue
            clean = {k: v for k, v in row.items() if not str(k).startswith("_")}
            extra_rows.append(clean)
            existing.add(fp)
            notes.append(f"{sym} {bd}←{row.get('_source', 'export')}")
            break
    if not extra_rows:
        return base, notes
    merged = pd.concat([base, pd.DataFrame(extra_rows)], ignore_index=True)
    merged = merged.sort_values(["Run Date", "Symbol"], ascending=[True, True]).reset_index(drop=True)
    return _adjust_intraday_order(merged), notes


def _ensure_open_lots_for_registry(
    open_agg: dict[tuple[str, str], Lot],
    open_lots: list[Lot],
    positions_path: Path,
    sys_map: dict[tuple[str, str], str],
    entry_prices: dict[tuple[str, str], float],
    downloads: Path,
) -> tuple[dict[tuple[str, str], Lot], list[Lot]]:
    """Ensure every gettarget_positions.csv row has a Lot (search older exports for qty if needed)."""
    for pos in _load_tracked_position_rows(positions_path):
        sym = pos["symbol"]
        bd: date = pos["buy_date"]
        key = (sym, bd.isoformat())
        if key in open_agg:
            continue
        px = float(pos.get("entry_price") or 0)
        if px <= 0:
            px = float(entry_prices.get(key, 0) or 0)
        qty = float(pos.get("qty") or 0)
        if qty <= 0:
            for row in _find_buy_rows_in_exports(downloads, sym, bd, px):
                try:
                    qty = abs(float(row["Quantity"]))
                    if px <= 0:
                        px = float(row["Price"])
                    break
                except (TypeError, ValueError):
                    continue
        if qty <= 0 or px <= 0:
            continue
        sys = pos.get("system") or sys_map.get(key) or _lookup_system(sym, bd, px, sys_map, entry_prices)
        lot = Lot(sym, bd, px, qty, sys, original_qty=qty)
        open_agg[key] = lot
        open_lots.append(lot)
    return open_agg, open_lots


def _registry_open_keys(positions_path: Path) -> set[tuple[str, str]]:
    return {(p["symbol"], p["buy_date"].isoformat()) for p in _load_tracked_position_rows(positions_path)}


def _mobile_fidelity_supplement_path() -> Path:
    """Phone-ingested Actual-shaped rows (tools/ingest_mobile_trades.py)."""
    return ROOT / "drive" / "mobile_inbox" / "fidelity_mobile_supplement.csv"


def _merge_mobile_fidelity_supplement(base: pd.DataFrame) -> tuple[pd.DataFrame, Optional[str]]:
    """
    Merge drive/mobile_inbox/fidelity_mobile_supplement.csv (Fidelity Accounts_History columns)
    so phone fills appear in Actual before the next broker export catches up.
    """
    path = _mobile_fidelity_supplement_path()
    if not path.is_file() or path.stat().st_size == 0:
        return base, None
    try:
        supplement = _load_accounts(path)
    except Exception:
        return base, None
    if supplement.empty:
        return base, None
    existing_buys = _buy_fingerprints(base)
    existing_sells = _sell_fingerprints(base)
    extra_rows: list[dict] = []
    for _, r in supplement.iterrows():
        action = str(r.get("Action", ""))
        rd = r.get("Run Date")
        if rd is None or (isinstance(rd, float) and pd.isna(rd)):
            continue
        try:
            sym = str(r.get("Symbol", "")).upper()
            qty = float(r.get("Quantity", 0))
            price = float(r.get("Price", 0))
        except (TypeError, ValueError):
            continue
        if "YOU BOUGHT" in action:
            fp = _buy_row_fingerprint(rd, sym, qty, price)
            if fp in existing_buys:
                continue
            existing_buys.add(fp)
        elif "YOU SOLD" in action:
            fp = _sell_row_fingerprint(rd, sym, qty, price)
            if fp in existing_sells:
                continue
            existing_sells.add(fp)
        else:
            continue
        extra_rows.append(r.to_dict())
    if not extra_rows:
        return base, None
    merged = pd.concat([base, pd.DataFrame(extra_rows)], ignore_index=True)
    merged = merged.sort_values(["Run Date", "Symbol"], ascending=[True, True]).reset_index(drop=True)
    return _adjust_intraday_order(merged), path.name


def _load_accounts_for_report(
    downloads: Path,
    positions_path: Path,
    accounts_path: Optional[Path] = None,
) -> tuple[pd.DataFrame, str]:
    """Load primary Fidelity export, merge account/recent/mobile supplements, backfill registry buys."""
    primary = accounts_path or _latest_accounts_history(downloads)
    acct = _load_accounts(primary)
    acct, account_supp = _merge_account_history_trades(acct, downloads)
    acct = _merge_recent_history_sells(acct, downloads)
    acct, mobile_supp = _merge_mobile_fidelity_supplement(acct)
    acct, buy_notes = _supplement_accounts_from_tracked_positions(acct, downloads, positions_path)
    source = primary.name
    if account_supp:
        source = f"{source} + {account_supp}"
    if mobile_supp:
        source = f"{source} + {mobile_supp}"
    if buy_notes:
        preview = ", ".join(buy_notes[:4])
        if len(buy_notes) > 4:
            preview += f", +{len(buy_notes) - 4} more"
        source = f"{source} (+ registry buys: {preview})"
    return acct, source


def _dedupe_accounts_trade_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Drop duplicate YOU BOUGHT / YOU SOLD rows when merging multiple Fidelity exports."""
    if df.empty:
        return df
    seen: set[tuple] = set()
    keep: list[int] = []
    for idx, r in df.iterrows():
        action = str(r.get("Action", ""))
        rd = r.get("Run Date")
        if rd is None or (isinstance(rd, float) and pd.isna(rd)):
            continue
        try:
            sym = str(r.get("Symbol", "")).upper()
            qty = float(r.get("Quantity", 0))
            price = float(r.get("Price", 0))
        except (TypeError, ValueError):
            keep.append(idx)
            continue
        if "YOU BOUGHT" in action:
            fp = _buy_row_fingerprint(rd, sym, qty, price)
        elif "YOU SOLD" in action:
            fp = _sell_row_fingerprint(rd, sym, qty, price)
        else:
            keep.append(idx)
            continue
        if fp in seen:
            continue
        seen.add(fp)
        keep.append(idx)
    out = df.loc[keep].copy()
    return out.sort_values(["Run Date", "Symbol"], ascending=[True, True]).reset_index(drop=True)


def _merge_all_full_accounts_exports(downloads: Path) -> pd.DataFrame:
    """
    Union all full Fidelity exports (deduped) — recovers buys that aged out of a rolling window.
    Used for one-time closed-log backfill.
    """
    frames: list[pd.DataFrame] = []
    for path in sorted(_candidate_full_accounts_exports(downloads), key=lambda p: p.stat().st_mtime):
        try:
            frames.append(_load_accounts(path))
        except Exception:
            continue
    if not frames:
        raise FileNotFoundError(
            f"No full Accounts_History export in {downloads} "
            "(need Accounts_History (N).csv or Accounts_History - 2026-....csv)"
        )
    merged = pd.concat(frames, ignore_index=True)
    return _dedupe_accounts_trade_rows(merged)


def backfill_closed_positions_log(
    *,
    downloads: Path = DOWNLOADS,
    log_path: Path = DEFAULT_CLOSED_LOG,
    positions_path: Path = DEFAULT_POSITIONS,
    accounts_path: Optional[Path] = None,
    closed_since: date = CLOSED_SINCE,
    min_position_value: float = MIN_POSITION_VALUE,
    drive_dir: Path = DRIVE,
    gettarget_path: Path = DEFAULT_GETTARGET,
    registry_path: Path = DEFAULT_TRADE_REGISTRY,
    merge_all_exports: bool = True,
) -> int:
    """
    Import closed round-trips from Fidelity activity into the permanent log.
    With merge_all_exports=True (default), unions every full export in Downloads.
    """
    if merge_all_exports and accounts_path is None:
        acct = _merge_all_full_accounts_exports(downloads)
        source = f"merged {len(_candidate_full_accounts_exports(downloads))} full export(s)"
    else:
        primary = accounts_path or _latest_accounts_history(downloads)
        acct = _load_accounts(primary)
        source = primary.name
    acct, account_supp = _merge_account_history_trades(acct, downloads)
    if account_supp:
        source = f"{source} + {account_supp}"
    acct = _merge_recent_history_sells(acct, downloads)
    acct, mobile_supp = _merge_mobile_fidelity_supplement(acct)
    if mobile_supp:
        source = f"{source} + {mobile_supp}"
    acct, _buy_notes = _supplement_accounts_from_tracked_positions(acct, downloads, positions_path)
    sys_map, entry_prices = _build_full_system_map(
        drive_dir=drive_dir,
        positions_path=positions_path,
        gettarget_path=gettarget_path,
        registry_path=registry_path,
    )
    raw_closed, _open_lots = _fifo_closed_and_open(acct, closed_since, sys_map, entry_prices)
    fifo_closed = _aggregate_closed_by_entry(
        raw_closed, min_position_value=min_position_value, sys_map=sys_map
    )
    appended = _append_closed_positions_log(log_path, fifo_closed)
    print(
        f"Backfill from {source}: {len(fifo_closed)} closed round-trip(s) in export; "
        f"appended {appended} new row(s) to {log_path}"
    )
    return appended


def _load_recent_history_stock_sells(path: Path) -> pd.DataFrame:
    """Fidelity 'recent history' export -> minimal rows compatible with _fifo_closed_and_open."""
    df = pd.read_csv(path, encoding="utf-8-sig")
    if df.empty:
        return pd.DataFrame()
    cols = {c.lower(): c for c in df.columns}
    date_c = cols.get("date")
    sym_c = cols.get("symbol")
    side_c = cols.get("buy/sell") or cols.get("buy_sell")
    qty_c = cols.get("quantity")
    px_c = cols.get("price")
    spread_c = cols.get("spread")
    if not all([date_c, sym_c, side_c, qty_c, px_c]):
        return pd.DataFrame()
    rows: list[dict] = []
    for _, r in df.iterrows():
        side = str(r.get(side_c, "")).strip().lower()
        if side != "sell":
            continue
        if spread_c:
            spread = str(r.get(spread_c, "")).strip().lower()
            if spread and spread not in ("stock", "stocks", ""):
                continue
        sym = str(r.get(sym_c, "")).strip().upper()
        if not sym:
            continue
        try:
            rd = pd.to_datetime(r.get(date_c), errors="coerce").date()
            qty = abs(float(r.get(qty_c)))
            price = float(r.get(px_c))
        except (TypeError, ValueError):
            continue
        if rd is None or pd.isna(rd) or qty <= 0 or price <= 0:
            continue
        rows.append(
            {
                "Run Date": rd,
                "Symbol": sym,
                "Action": f"YOU SOLD {sym} (recent history)",
                "Price": price,
                "Quantity": -qty,
                "Amount": qty * price,
            }
        )
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    return out.sort_values(["Run Date", "Symbol"]).reset_index(drop=True)


def _merge_account_history_trades(
    base: pd.DataFrame, downloads: Path
) -> tuple[pd.DataFrame, Optional[str]]:
    """
    Append YOU BOUGHT / YOU SOLD rows from the latest History_for_Account_*.csv export
    when missing from the primary Accounts_History (per-account export often leads by a day).
    """
    account_path = _latest_account_history_export(downloads)
    if account_path is None:
        return base, None
    try:
        supplement = _load_accounts(account_path)
    except Exception:
        return base, None
    if supplement.empty:
        return base, None
    existing_buys = _buy_fingerprints(base)
    existing_sells = _sell_fingerprints(base)
    extra_rows: list[dict] = []
    for _, r in supplement.iterrows():
        action = str(r.get("Action", ""))
        rd = r.get("Run Date")
        if rd is None or (isinstance(rd, float) and pd.isna(rd)):
            continue
        try:
            sym = str(r.get("Symbol", "")).upper()
            qty = float(r.get("Quantity", 0))
            price = float(r.get("Price", 0))
        except (TypeError, ValueError):
            continue
        if "YOU BOUGHT" in action:
            fp = _buy_row_fingerprint(rd, sym, qty, price)
            if fp in existing_buys:
                continue
            existing_buys.add(fp)
        elif "YOU SOLD" in action:
            fp = _sell_row_fingerprint(rd, sym, qty, price)
            if fp in existing_sells:
                continue
            existing_sells.add(fp)
        else:
            continue
        extra_rows.append(r.to_dict())
    if not extra_rows:
        return base, None
    merged = pd.concat([base, pd.DataFrame(extra_rows)], ignore_index=True)
    merged = merged.sort_values(["Run Date", "Symbol"], ascending=[True, True]).reset_index(drop=True)
    return merged, account_path.name


def _merge_recent_history_sells(base: pd.DataFrame, downloads: Path) -> pd.DataFrame:
    """
    Append stock sells from the latest recent-history export when they are missing
    from the full export (Fidelity often lags same-day sells on numbered downloads).
    """
    recent_path = _latest_recent_history_export(downloads)
    if recent_path is None:
        return base
    supplement = _load_recent_history_stock_sells(recent_path)
    if supplement.empty:
        return base
    existing = _sell_fingerprints(base)
    extra_rows: list[dict] = []
    for _, r in supplement.iterrows():
        fp = _sell_row_fingerprint(
            r["Run Date"], r["Symbol"], float(r["Quantity"]), float(r["Price"])
        )
        if fp in existing:
            continue
        extra_rows.append(r.to_dict())
        existing.add(fp)
    if not extra_rows:
        return base
    merged = pd.concat([base, pd.DataFrame(extra_rows)], ignore_index=True)
    return merged.sort_values(["Run Date", "Symbol"], ascending=[True, True]).reset_index(drop=True)


def _adjust_intraday_order(df: pd.DataFrame) -> pd.DataFrame:
    """
    Fidelity exports sometimes list same-day sells before the matching buy.
    When every sell row precedes every buy row for a (date, symbol), process buys first.
    """
    if df.empty:
        return df
    parts: list[pd.DataFrame] = []
    for (_, _), g in df.groupby(["Run Date", "Symbol"], sort=True):
        g = g.reset_index(drop=True)
        buys = g[g["Action"].str.contains("YOU BOUGHT", na=False)]
        sells = g[g["Action"].str.contains("YOU SOLD", na=False)]
        if not buys.empty and not sells.empty and sells.index.max() < buys.index.min():
            rest = g[~g.index.isin(buys.index) & ~g.index.isin(sells.index)]
            g = pd.concat([buys, sells, rest], ignore_index=True)
        parts.append(g)
    return pd.concat(parts, ignore_index=True)


def _load_accounts(path: Path) -> pd.DataFrame:
    """Load Fidelity Accounts_History export (header row index varies by export version)."""
    preview = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()[:20]
    header_idx = 0
    for i, line in enumerate(preview):
        stripped = line.strip().lstrip("\ufeff")
        if stripped.startswith("Run Date"):
            header_idx = i
            break
    else:
        raise ValueError(f"No 'Run Date' header row in {path.name}")
    df = pd.read_csv(
        path, skiprows=header_idx, on_bad_lines="skip", engine="python", encoding="utf-8-sig"
    )
    df.columns = df.columns.str.strip()
    df = df.dropna(how="all")
    if "Run Date" not in df.columns:
        raise KeyError(
            f"'Run Date' column missing after parsing {path.name}; columns={list(df.columns)[:10]}"
        )
    df["Run Date"] = pd.to_datetime(df["Run Date"], errors="coerce").dt.date
    df["Symbol"] = df["Symbol"].astype(str).str.strip().str.upper()
    df["Price"] = pd.to_numeric(df["Price"], errors="coerce")
    df["Quantity"] = pd.to_numeric(df["Quantity"], errors="coerce")
    df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce")
    df["Action"] = df["Action"].astype(str)
    df = df.sort_values(["Run Date", "Symbol"], ascending=[True, True]).reset_index(drop=True)
    return _adjust_intraday_order(df)


def _tracked_open_symbols(positions_path: Path) -> set[str]:
    """Symbols listed in gettarget_positions.csv (current open-position registry)."""
    if not positions_path.is_file():
        return set()
    df = pd.read_csv(positions_path, dtype=str, keep_default_na=False)
    cols = {c.lower(): c for c in df.columns}
    sym_c = cols.get("symbol", "symbol")
    out: set[str] = set()
    for _, r in df.iterrows():
        sym = str(r.get(sym_c, "")).strip().upper()
        if sym and sym not in ("NAN", "NONE"):
            out.add(sym)
    return out


def _lot_key(lot: Lot) -> tuple[str, str]:
    return (lot.symbol, lot.buy_date.isoformat())


def _aggregate_lots_by_entry(lots: list[Lot]) -> dict[tuple[str, str], Lot]:
    """One row per (symbol, entry_date) — never merge different systems or entries."""
    buckets: dict[tuple[str, str], list[Lot]] = {}
    for lot in lots:
        buckets.setdefault(_lot_key(lot), []).append(lot)
    out: dict[tuple[str, str], Lot] = {}
    for key, parts in buckets.items():
        total_qty = sum(p.qty for p in parts)
        if total_qty <= 1e-9:
            continue
        cost = sum(p.qty * p.buy_price for p in parts)
        out[key] = Lot(
            parts[0].symbol,
            parts[0].buy_date,
            cost / total_qty,
            total_qty,
            parts[0].system,
        )
    return out


def _gettarget_row_for_lot(gt_df: pd.DataFrame, lot: Lot) -> Optional[pd.Series]:
    if gt_df.empty:
        return None
    sym = lot.symbol
    bd = lot.buy_date
    mask = gt_df["Symbol"].astype(str).str.upper() == sym
    if "PurchaseDate" in gt_df.columns:
        pds = pd.to_datetime(gt_df["PurchaseDate"], errors="coerce").dt.date
        dated = mask & (pds == bd)
        if dated.any():
            return gt_df.loc[dated].iloc[0]
    if mask.sum() == 1:
        return gt_df.loc[mask].iloc[0]
    return None


def _fifo_closed_and_open(
    df: pd.DataFrame,
    since: date,
    sys_map: dict[tuple[str, str], str],
    entry_prices: Optional[dict[tuple[str, str], float]] = None,
) -> tuple[list[ClosedTrade], list[Lot]]:
    lots: dict[str, deque[Lot]] = {}
    closed: list[ClosedTrade] = []

    for _, r in df.iterrows():
        sym = r["Symbol"]
        if not sym or sym == "NAN":
            continue
        action = r["Action"]
        if "YOU BOUGHT" in action:
            qty = abs(float(r["Quantity"]))
            price = float(r["Price"])
            bd = r["Run Date"]
            if pd.isna(bd):
                continue
            lot = Lot(
                sym,
                bd,
                price,
                qty,
                _lookup_system(sym, bd, price, sys_map, entry_prices),
                original_qty=qty,
            )
            lots.setdefault(sym, deque()).append(lot)
        elif "DISTRIBUTION" in action:
            dist_qty = abs(float(r["Quantity"]))
            if dist_qty <= 1e-9 or not lots.get(sym):
                continue
            lot = lots[sym][0]
            old_cost = lot.qty * lot.buy_price
            try:
                amount = float(r["Amount"])
            except (TypeError, ValueError):
                amount = 0.0
            if amount and amount > 0:
                old_cost += amount
            lot.qty += dist_qty
            lot.buy_price = old_cost / lot.qty if lot.qty > 0 else lot.buy_price
            orig = lot.original_qty or (lot.qty - dist_qty)
            lot.original_qty = orig + dist_qty
        elif "YOU SOLD" in action:
            sell_qty = abs(float(r["Quantity"]))
            sell_price = float(r["Price"])
            sd = r["Run Date"]
            if pd.isna(sd):
                continue
            remaining = sell_qty
            while remaining > 1e-9 and lots.get(sym):
                lot = lots[sym][0]
                take = min(remaining, lot.qty)
                pnl_pct = (sell_price - lot.buy_price) / lot.buy_price * 100.0 if lot.buy_price else 0.0
                pnl_dollars = take * (sell_price - lot.buy_price)
                if sd >= since:
                    orig = lot.original_qty or lot.qty
                    closed.append(
                        ClosedTrade(
                            symbol=sym,
                            system=lot.system,
                            buy_date=lot.buy_date,
                            buy_price=lot.buy_price,
                            sell_date=sd,
                            sell_price=sell_price,
                            qty=take,
                            pnl_pct=pnl_pct,
                            pnl_dollars=pnl_dollars,
                            original_qty=orig,
                            purchase_value=_position_value(orig, lot.buy_price),
                        )
                    )
                lot.qty -= take
                remaining -= take
                if lot.qty <= 1e-9:
                    lots[sym].popleft()

    open_lots: list[Lot] = []
    for dq in lots.values():
        open_lots.extend(list(dq))
    closed.sort(key=lambda t: (t.sell_date, t.symbol))
    return closed, open_lots


def _aggregate_closed_by_entry(
    closed: list[ClosedTrade],
    min_position_value: float = MIN_POSITION_VALUE,
    sys_map: Optional[dict[tuple[str, str], str]] = None,
) -> list[ClosedTrade]:
    """
    One row per (symbol, buy_date): sum sold shares, quantity-weighted avg entry/exit,
    only when total purchase amount meets the size threshold (or registry-tracked floor).
    """
    from collections import defaultdict

    groups: dict[tuple[str, date], list[ClosedTrade]] = defaultdict(list)
    for t in closed:
        groups[(t.symbol, t.buy_date)].append(t)

    out: list[ClosedTrade] = []
    for (sym, buy_date), slices in groups.items():
        lot_purchase: dict[tuple[float, float], float] = {}
        for t in slices:
            key = (t.buy_price, t.original_qty or t.qty)
            lot_purchase[key] = t.purchase_value or _position_value(
                t.original_qty or t.qty, t.buy_price
            )
        total_pv = sum(lot_purchase.values())
        if sys_map is not None:
            if not _meets_position_size_threshold(
                total_pv, sym, buy_date, sys_map, min_position_value=min_position_value
            ):
                continue
        elif total_pv < min_position_value:
            continue

        total_qty = sum(t.qty for t in slices)
        if total_qty <= 1e-9:
            continue
        avg_buy = sum(t.qty * t.buy_price for t in slices) / total_qty
        avg_sell = sum(t.qty * t.sell_price for t in slices) / total_qty
        pnl_dollars = sum(t.pnl_dollars for t in slices)
        pnl_pct = (avg_sell - avg_buy) / avg_buy * 100.0 if avg_buy else 0.0
        sell_date = max(t.sell_date for t in slices)
        out.append(
            ClosedTrade(
                symbol=sym,
                system=slices[0].system,
                buy_date=buy_date,
                buy_price=avg_buy,
                sell_date=sell_date,
                sell_price=avg_sell,
                qty=total_qty,
                pnl_pct=pnl_pct,
                pnl_dollars=pnl_dollars,
                original_qty=max(t.original_qty or t.qty for t in slices),
                purchase_value=sum(lot_purchase.values()),
            )
        )
    out.sort(key=lambda t: (t.sell_date, t.symbol))
    return out


def _now_et() -> datetime:
    return datetime.now(ET)


def _format_et_datetime(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ET)
    else:
        dt = dt.astimezone(ET)
    s = dt.strftime("%Y-%m-%d %I:%M %p")
    if s[11] == "0":
        s = s[:11] + s[12:]
    return s


def _market_session_kind(now_et: datetime) -> str:
    """regular | post_close_refresh | after_hours (weekends are after_hours)."""
    if now_et.weekday() >= 5:
        return "after_hours"
    t = now_et.time()
    if MARKET_OPEN_ET <= t < MARKET_CLOSE_ET:
        return "regular"
    if MARKET_CLOSE_ET <= t < POST_CLOSE_REFRESH_END_ET:
        return "post_close_refresh"
    return "after_hours"


def _gettarget_file_timestamp(gettarget_path: Path) -> Optional[datetime]:
    if not gettarget_path.is_file():
        return None
    return datetime.fromtimestamp(gettarget_path.stat().st_mtime, tz=ET)


def _row_as_of_date_close_et(row: pd.Series) -> Optional[datetime]:
    raw = row.get("AsOfDate")
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    d = pd.Timestamp(raw).date()
    return datetime.combine(d, MARKET_CLOSE_ET, tzinfo=ET)


def _effective_price_timestamp(
    open_df: pd.DataFrame,
    open_keys: set[tuple[str, str]],
    open_agg: dict[tuple[str, str], Lot],
    gettarget_path: Path,
) -> datetime:
    """Best estimate of when open-position prices were last valid."""
    candidates: list[datetime] = []
    file_ts = _gettarget_file_timestamp(gettarget_path)
    if file_ts is not None:
        candidates.append(file_ts)
    for key in open_keys:
        lot = open_agg.get(key)
        if lot is None:
            continue
        r = _gettarget_row_for_lot(open_df, lot)
        if r is None:
            continue
        row_ts = _row_as_of_date_close_et(r)
        if row_ts is not None:
            candidates.append(row_ts)
    if not candidates:
        return _now_et()
    return min(candidates)


def _needs_open_price_refresh(now_et: datetime, price_ts: datetime) -> bool:
    session = _market_session_kind(now_et)
    if session == "after_hours":
        return False
    age_min = (now_et - price_ts).total_seconds() / 60.0
    if age_min > STALE_PRICE_MINUTES:
        return True
    if (
        session == "post_close_refresh"
        and price_ts.date() == now_et.date()
        and price_ts.time() < MARKET_CLOSE_ET
    ):
        return True
    return False


def _fetch_yfinance_last_prices(symbols: list[str]) -> dict[str, float]:
    if not symbols:
        return {}
    try:
        import yfinance as yf
    except ImportError:
        return {}
    out: dict[str, float] = {}

    def _price_from_ticker(t) -> float:
        try:
            fi = t.fast_info
            raw = getattr(fi, "last_price", None) or getattr(fi, "lastPrice", None)
            if raw is None and hasattr(fi, "get"):
                raw = fi.get("last_price") or fi.get("lastPrice")
            price = float(raw or 0)
            if price > 0:
                return price
        except Exception:
            pass
        try:
            hist = t.history(period="5d", auto_adjust=True)
            if hist is not None and not hist.empty and "Close" in hist.columns:
                close = hist["Close"].dropna()
                if not close.empty:
                    return float(close.iloc[-1])
        except Exception:
            pass
        return 0.0

    try:
        tickers = yf.Tickers(" ".join(symbols))
    except Exception:
        tickers = None
    for sym in symbols:
        try:
            t = tickers.tickers.get(sym) if tickers else None
            if t is None:
                t = yf.Ticker(sym)
            price = _price_from_ticker(t)
            if price > 0:
                out[sym] = price
        except Exception:
            continue
    return out


def _fetch_local_csv_last_prices(
    symbols: list[str],
    data_dir: Path = DEFAULT_OHLCV_DATA_DIR,
) -> dict[str, float]:
    """Last Close from local OHLCV CSV when yfinance has no mark (e.g. thin symbols)."""
    out: dict[str, float] = {}
    for sym in symbols:
        path = data_dir / f"{sym.upper()}.csv"
        if not path.is_file():
            continue
        try:
            df = pd.read_csv(path, usecols=["Date", "Close"])
            close = pd.to_numeric(df["Close"], errors="coerce").dropna()
            if close.empty:
                continue
            px = float(close.iloc[-1])
            if px > 0:
                out[sym.upper()] = px
        except Exception:
            continue
    return out


def _fetch_open_position_prices(symbols: list[str]) -> dict[str, float]:
    """yfinance first; fill gaps from local OHLCV under data/newdata/data."""
    if not symbols:
        return {}
    syms = sorted({s.upper() for s in symbols if s})
    out = _fetch_yfinance_last_prices(syms)
    missing = [s for s in syms if s not in out]
    if missing:
        out.update(_fetch_local_csv_last_prices(missing))
    return out


def _open_symbols_missing_prices(
    open_df: pd.DataFrame,
    open_agg: dict[tuple[str, str], Lot],
    open_keys: set[tuple[str, str]],
) -> list[str]:
    """Symbols in the open book with no getTarget row or no usable CurrentPrice."""
    missing: set[str] = set()
    for key in open_keys:
        lot = open_agg.get(key)
        if lot is None:
            continue
        sym = lot.symbol
        row = _gettarget_row_for_lot(open_df, lot)
        if row is None:
            missing.add(sym)
            continue
        cur = pd.to_numeric(row.get("CurrentPrice"), errors="coerce")
        if cur is None or not np.isfinite(float(cur)) or float(cur) <= 0:
            missing.add(sym)
    return sorted(missing)


def _apply_yfinance_prices_to_open_df(
    open_df: pd.DataFrame,
    open_agg: dict[tuple[str, str], Lot],
    open_keys: set[tuple[str, str]],
    fetched: dict[str, float],
    *,
    now_et: datetime,
) -> pd.DataFrame:
    """Merge yfinance marks into getTarget rows and synthesize rows for registry-only symbols."""
    if not fetched:
        return open_df
    df = open_df.copy() if not open_df.empty else pd.DataFrame(
        columns=[
            "Symbol",
            "PurchaseDate",
            "EntryPrice",
            "CurrentPrice",
            "TargetPrice",
            "StopLoss",
            "GainPct",
            "AsOfDate",
        ]
    )
    for key in open_keys:
        lot = open_agg.get(key)
        if lot is None:
            continue
        sym = lot.symbol
        px = fetched.get(sym)
        if px is None or px <= 0:
            continue
        row = _gettarget_row_for_lot(df, lot)
        if row is not None:
            mask = df.index == row.name
            df.loc[mask, "CurrentPrice"] = px
            entry = pd.to_numeric(df.loc[mask, "EntryPrice"], errors="coerce")
            df.loc[mask, "GainPct"] = (px / entry - 1.0) * 100.0
            if "AsOfDate" in df.columns:
                df.loc[mask, "AsOfDate"] = pd.Timestamp(now_et.date())
            continue
        gain_pct = (px / lot.buy_price - 1.0) * 100.0 if lot.buy_price > 0 else np.nan
        df = pd.concat(
            [
                df,
                pd.DataFrame(
                    [
                        {
                            "Symbol": sym,
                            "PurchaseDate": pd.Timestamp(lot.buy_date),
                            "EntryPrice": lot.buy_price,
                            "CurrentPrice": px,
                            "TargetPrice": np.nan,
                            "StopLoss": np.nan,
                            "GainPct": gain_pct,
                            "AsOfDate": pd.Timestamp(now_et.date()),
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )
    return df


def _maybe_refresh_open_prices(
    open_df: pd.DataFrame,
    open_agg: dict[tuple[str, str], Lot],
    open_keys: set[tuple[str, str]],
    gettarget_path: Path,
    now_et: Optional[datetime] = None,
) -> tuple[pd.DataFrame, datetime, str]:
    """
    Refresh open-position marks via yfinance when stale (>55 min) during RTH or
    in the post-close window (4:00–5:00 PM ET), or when a symbol is missing from
    getTarget_output.csv. After 5 PM ET / weekends use getTarget when prices exist.
    Returns (dataframe, prices_as_of_et, source_label).
    """
    now_et = now_et or _now_et()
    if not open_keys:
        return open_df, now_et, "n/a"

    price_ts = _effective_price_timestamp(open_df, open_keys, open_agg, gettarget_path)
    session = _market_session_kind(now_et)
    missing_symbols = _open_symbols_missing_prices(open_df, open_agg, open_keys)
    stale = _needs_open_price_refresh(now_et, price_ts)

    if not stale and not missing_symbols:
        return open_df, price_ts, gettarget_path.name

    symbols = sorted({open_agg[k].symbol for k in open_keys if k in open_agg})
    if stale:
        fetch_symbols = symbols
    else:
        fetch_symbols = missing_symbols
    fetched = _fetch_open_position_prices(fetch_symbols)
    if not fetched:
        return open_df, price_ts, gettarget_path.name

    yf_only = _fetch_yfinance_last_prices(fetch_symbols)
    used_local = sorted(set(fetched) - set(yf_only))

    df = _apply_yfinance_prices_to_open_df(
        open_df, open_agg, open_keys, fetched, now_et=now_et
    )

    if session == "after_hours" and not missing_symbols:
        return df, price_ts, gettarget_path.name

    if session == "post_close_refresh":
        prices_as_of = datetime.combine(now_et.date(), MARKET_CLOSE_ET, tzinfo=ET)
        source = "yfinance (close)"
    else:
        prices_as_of = now_et.replace(second=0, microsecond=0)
        source = "yfinance"
    if missing_symbols and stale:
        source = f"{source} + missing getTarget"
    elif missing_symbols:
        source = "yfinance (missing getTarget)"
    if used_local:
        source = f"{source} + local OHLCV ({', '.join(used_local)})"
    return df, prices_as_of, source


def _load_open_positions(gettarget_path: Path) -> pd.DataFrame:
    if not gettarget_path.is_file():
        return pd.DataFrame()
    df = pd.read_csv(gettarget_path)
    if df.empty:
        return df
    df["Symbol"] = df["Symbol"].astype(str).str.upper()
    df["PurchaseDate"] = pd.to_datetime(df["PurchaseDate"], errors="coerce")
    if "AsOfDate" in df.columns:
        df["AsOfDate"] = pd.to_datetime(df["AsOfDate"], errors="coerce")
    df["EntryPrice"] = pd.to_numeric(df["EntryPrice"], errors="coerce")
    df["CurrentPrice"] = pd.to_numeric(df["CurrentPrice"], errors="coerce")
    df["TargetPrice"] = pd.to_numeric(df["TargetPrice"], errors="coerce")
    stop = pd.to_numeric(df.get("StopTrailing", df.get("StopInitial")), errors="coerce")
    df["StopLoss"] = stop
    df["GainPct"] = (df["CurrentPrice"] / df["EntryPrice"] - 1.0) * 100.0
    return df


_RUN_TS_RE = re.compile(
    r"^(?P<prefix>BRT|IND|RL|YH|MTS|WPBR|PBR|RS|SB|VZ)_(?:Closed|Open|Watchlist)_(?P<ts>\d{12})\.csv$",
    re.I,
)
_PIPELINE_TS_RE = re.compile(
    r"^(?P<prefix>BRT|IND)_Pipeline_Timings_(?P<ts>\d{12})_", re.I
)


def _read_engine_last_run_ts(prefix: str, drive: Path) -> Optional[str]:
    """12-digit yyMMddHHmmss from drive/{PREFIX}_last_run_ts.txt, if present."""
    path = drive / f"{prefix.upper()}_last_run_ts.txt"
    if not path.is_file():
        return None
    try:
        ts = path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    except OSError:
        return None
    return ts if re.fullmatch(r"\d{12}", ts) else None


def _read_vz_house_run_ts(drive: Path) -> Optional[str]:
    """House pin from drive/VZ_house_last_run_ts.txt (not overwritten by ALL runs)."""
    path = drive / "VZ_house_last_run_ts.txt"
    if not path.is_file():
        return None
    try:
        ts = path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    except OSError:
        return None
    return ts if re.fullmatch(r"\d{12}", ts) else None


def _vz_house_summary_max(drive: Path) -> int:
    """Upper bound on VZ_Summary row count for house / run_vz.bat default universe."""
    univ = drive / "universes" / "VZ_universe.csv"
    if univ.is_file():
        try:
            n = sum(1 for _ in univ.open(encoding="utf-8")) - 1
            if n > 0:
                return max(100, int(n * 1.35))
        except OSError:
            pass
    return 120


def _vz_summary_row_count(drive: Path, ts: str) -> Optional[int]:
    path = drive / f"VZ_Summary_{ts}.csv"
    if not path.is_file():
        return None
    try:
        return sum(1 for _ in path.open(encoding="utf-8")) - 1
    except OSError:
        return None


def _vz_is_house_stamp(drive: Path, ts: str) -> bool:
    n = _vz_summary_row_count(drive, ts)
    return n is not None and n <= _vz_house_summary_max(drive)


def _vz_house_run_timestamp(drive: Path) -> Optional[str]:
    """Public VZ book: house stamp only — never ALL / full-universe research runs."""
    house_max = _vz_house_summary_max(drive)
    for ts in (_read_vz_house_run_ts(drive), _read_engine_last_run_ts("VZ", drive)):
        if ts and _stamp_has_core("VZ", drive, ts) and _vz_is_house_stamp(drive, ts):
            return ts
    house_stamps: list[str] = []
    for path in drive.glob("VZ_Summary_*.csv"):
        m = re.match(r"VZ_Summary_(\d{12})\.csv$", path.name)
        if not m:
            continue
        ts = m.group(1)
        n = _vz_summary_row_count(drive, ts)
        if n is not None and n <= house_max and _stamp_has_core("VZ", drive, ts):
            house_stamps.append(ts)
    return max(house_stamps) if house_stamps else None


_BARS_HELD_RE = re.compile(r"bars_held=(\d+)/")
_HL_ZONE_ID_RE = re.compile(r"HL_(\d{4}-\d{2}-\d{2})")
_VZ_ENTRY_ON = "next_open"


def _ohlc_bar_index(df: pd.DataFrame, ymd: Any) -> Optional[int]:
    s = str(ymd).strip().replace("-", "")[:8]
    if len(s) != 8 or not s.isdigit():
        return None
    dates = pd.to_datetime(df["Date"], errors="coerce")
    ymd_s = dates.dt.strftime("%Y%m%d")
    hits = np.flatnonzero(ymd_s.values == s)
    if hits.size:
        return int(hits[-1])
    target = pd.Timestamp(f"{s[:4]}-{s[4:6]}-{s[6:8]}")
    idx = int(dates.searchsorted(target, side="right") - 1)
    return idx if idx >= 0 else None


def _load_symbol_ohlcv(sym: str, data_dir: Path) -> Optional[pd.DataFrame]:
    path = data_dir / f"{sym.upper()}.csv"
    if not path.is_file():
        return None
    try:
        df = pd.read_csv(path)
    except Exception:
        return None
    need = {"Date", "High", "Low", "Close", "Volume"}
    if not need.issubset(df.columns):
        return None
    out = df[list(need)].copy()
    out["Date"] = pd.to_datetime(out["Date"], errors="coerce")
    out = out.dropna(subset=["Date"])
    for c in ("High", "Low", "Close", "Volume"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.dropna(subset=["High", "Low", "Close", "Volume"])
    if out.empty:
        return None
    return out.reset_index(drop=True)


def _vz_zone_bounds(row: pd.Series, ohlc: pd.DataFrame) -> tuple[float, float]:
    lo = float(pd.to_numeric(row.get("ZONE_LO"), errors="coerce"))
    hi_raw = row.get("ZONE_HI", "")
    hi: Optional[float] = None
    if hi_raw is not None and str(hi_raw).strip():
        hi = float(pd.to_numeric(hi_raw, errors="coerce"))
    if hi is None or not np.isfinite(hi):
        m = _HL_ZONE_ID_RE.match(str(row.get("ZONE_ID", "")))
        if m:
            idx = _ohlc_bar_index(ohlc, m.group(1).replace("-", ""))
            if idx is not None:
                hi = float(ohlc.iloc[idx]["High"])
    if hi is None or not np.isfinite(hi):
        hi = lo
    return min(lo, hi), max(lo, hi)


def _vz_signal_bar_index(
    row: pd.Series,
    ohlc: pd.DataFrame,
    open_by_key: dict[tuple[str, str], dict[str, Any]],
) -> Optional[int]:
    sym = str(row.get("SYMBOL", "")).strip().upper()
    zone_lo = str(row.get("ZONE_LO", "")).strip()
    open_row = open_by_key.get((sym, zone_lo), {})
    entry_idx_raw = open_row.get("ENTRY_BAR_INDEX")
    if entry_idx_raw is not None and str(entry_idx_raw).strip() != "":
        try:
            entry_idx = int(entry_idx_raw)
            if _VZ_ENTRY_ON == "next_open":
                return entry_idx - 1 if entry_idx > 0 else None
            return entry_idx
        except (TypeError, ValueError):
            pass
    entry_ymd = open_row.get("DATE_OPENED") or row.get("DATE_OPENED")
    if entry_ymd:
        entry_idx = _ohlc_bar_index(ohlc, entry_ymd)
        if entry_idx is not None:
            if _VZ_ENTRY_ON == "next_open":
                return entry_idx - 1 if entry_idx > 0 else None
            return entry_idx
    notes = str(row.get("NOTES", ""))
    m = _BARS_HELD_RE.search(notes)
    asof_ymd = row.get("ASOF_DATE")
    if m and asof_ymd:
        asof_idx = _ohlc_bar_index(ohlc, asof_ymd)
        if asof_idx is not None:
            entry_idx = asof_idx - int(m.group(1))
            if _VZ_ENTRY_ON == "next_open":
                return entry_idx - 1 if entry_idx > 0 else None
            return entry_idx
    return None


def _vz_open_lookup(drive: Path, run_ts: Optional[str]) -> dict[tuple[str, str], dict[str, Any]]:
    candidates: list[Path] = []
    if run_ts:
        candidates.append(drive / f"VZ_Open_{run_ts}.csv")
    candidates.append(drive / "VZ_LatestRun_Open.csv")
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        return {}
    try:
        open_df = pd.read_csv(path)
    except Exception:
        return {}
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for _, r in open_df.iterrows():
        sym = str(r.get("SYMBOL", "")).strip().upper()
        zone_lo = str(r.get("ZONE_LOW", r.get("ZONE_LO", ""))).strip()
        if sym:
            out[(sym, zone_lo)] = r.to_dict()
    return out


def _enrich_vz_watchlist_hvn(
    df: pd.DataFrame,
    drive: Path,
    run_ts: Optional[str],
    data_dir: Path = DEFAULT_OHLCV_DATA_DIR,
) -> pd.DataFrame:
    """Add POC / HVN $ / HVN pass? using frozen daily VP at signal bar (research-only)."""
    if df.empty:
        return df
    work = df.copy()
    open_by_key = _vz_open_lookup(drive, run_ts)
    ohlc_cache: dict[str, pd.DataFrame] = {}
    poc_vals: list[str] = []
    hvn_vals: list[str] = []
    pass_vals: list[str] = []
    for _, row in work.iterrows():
        sym = str(row.get("SYMBOL", "")).strip().upper()
        if sym not in ohlc_cache:
            ohlc_cache[sym] = _load_symbol_ohlcv(sym, data_dir)
        ohlc = ohlc_cache.get(sym)
        if ohlc is None:
            poc_vals.append("—")
            hvn_vals.append("—")
            pass_vals.append("—")
            continue
        try:
            zone_lo, zone_hi = _vz_zone_bounds(row, ohlc)
            signal_idx = _vz_signal_bar_index(row, ohlc, open_by_key)
        except (TypeError, ValueError):
            poc_vals.append("—")
            hvn_vals.append("—")
            pass_vals.append("—")
            continue
        if signal_idx is None or signal_idx < 0:
            poc_vals.append("—")
            hvn_vals.append("—")
            pass_vals.append("—")
            continue
        fields = hvn_gate_fields_at_bar(
            ohlc["High"].to_numpy(dtype=np.float64),
            ohlc["Low"].to_numpy(dtype=np.float64),
            ohlc["Close"].to_numpy(dtype=np.float64),
            ohlc["Volume"].to_numpy(dtype=np.float64),
            signal_idx,
            zone_lo,
            zone_hi,
        )
        if fields is None:
            poc_vals.append("—")
            hvn_vals.append("—")
            pass_vals.append("—")
        else:
            poc_vals.append(fields[0])
            hvn_vals.append(fields[1])
            pass_vals.append(fields[2])
    work["POC"] = poc_vals
    work["HVN $"] = hvn_vals
    work["HVN pass?"] = pass_vals
    return work


def _dedupe_vz_watchlist(df: pd.DataFrame) -> pd.DataFrame:
    """One row per SYMBOL; keep the open lot closest to the 40d time stop."""
    if df.empty or "SYMBOL" not in df.columns:
        return df

    def _bars_held(row: pd.Series) -> int:
        notes = str(row.get("NOTES", ""))
        m = _BARS_HELD_RE.search(notes)
        return int(m.group(1)) if m else -1

    work = df.copy()
    work["_sym"] = work["SYMBOL"].astype(str).str.strip().str.upper()
    work["_bars"] = work.apply(_bars_held, axis=1)
    work = work.sort_values(["_sym", "_bars"], ascending=[True, False])
    out = work.drop_duplicates(subset=["_sym"], keep="first").drop(columns=["_sym", "_bars"])
    return out.reset_index(drop=True)


def _stamp_has_core(prefix: str, drive: Path, ts: str) -> bool:
    pfx = prefix.upper()
    aliases = [pfx]
    if pfx == "WPBR":
        aliases.append("PBR")
    kinds = ("Watchlist", "Open", "Closed", "Scanner")
    for alias in aliases:
        for kind in kinds:
            if (drive / f"{alias}_{kind}_{ts}.csv").is_file():
                return True
    return False


def _latest_run_timestamp(prefix: str, drive: Path) -> Optional[str]:
    """Latest yyMMddHHmmss from Closed/Open/Watchlist/Pipeline (not Scanner alone).

    VZ is pinned to the house universe only: ALL / HVN-on full-universe runs also write
    VZ_Watchlist_<stamp>.csv and overwrite VZ_last_run_ts.txt — ignore those for the
    public book. Prefer VZ_house_last_run_ts.txt, else a house-sized VZ_last_run_ts pin,
    else the latest stamp whose VZ_Summary row count matches run_vz.bat house size.
    """
    pfx = prefix.upper()
    if pfx == "VZ":
        return _vz_house_run_timestamp(drive)
    aliases = [pfx]
    if pfx == "WPBR":
        aliases.append("PBR")  # legacy outputs
    stamps: set[str] = set()
    for alias in aliases:
        for path in drive.glob(f"{alias}_*.csv"):
            m = _RUN_TS_RE.match(path.name)
            if m and m.group("prefix").upper() == alias:
                stamps.add(m.group("ts"))
        for path in drive.glob(f"{alias}_Pipeline_Timings_*.json"):
            m = _PIPELINE_TS_RE.match(path.name)
            if m and m.group("prefix").upper() == alias:
                stamps.add(m.group("ts"))
    return max(stamps) if stamps else None


def _scanner_for_latest_run(
    prefix: str, drive: Path
) -> tuple[Optional[Path], pd.DataFrame, Optional[str]]:
    """
    Use scanner CSV only when the latest core run actually wrote one.
    Avoids stale scanner rows when the newest DailyRun had no candidates.
    SB (StockBee) has no Scanner — fall back to Watchlist for the same run stamp.
    VZ (Volume Zone) has no Scanner — Watchlist/Open for the pinned last-run stamp,
    else VZ_LatestRun_Watchlist.csv / Open (not the newest VZ_Watchlist_* on disk).
    """
    pfx = prefix.upper()
    if pfx == "VZ":
        run_ts = _latest_run_timestamp("VZ", drive)
        candidates: list[Path] = []
        if run_ts:
            candidates.append(drive / f"VZ_Watchlist_{run_ts}.csv")
            candidates.append(drive / f"VZ_Open_{run_ts}.csv")
        candidates.append(drive / "VZ_LatestRun_Watchlist.csv")
        candidates.append(drive / "VZ_LatestRun_Open.csv")
        path = next((p for p in candidates if p.is_file()), None)
        if path is None:
            return None, pd.DataFrame(), run_ts
        df = _dedupe_vz_watchlist(pd.read_csv(path))
        return path, df, run_ts

    run_ts = _latest_run_timestamp(prefix, drive)
    if not run_ts:
        return None, pd.DataFrame(), None
    candidates = [drive / f"{prefix}_Scanner_{run_ts}.csv"]
    if pfx == "WPBR":
        candidates.append(drive / f"PBR_Scanner_{run_ts}.csv")
    if pfx == "SB":
        candidates.append(drive / f"SB_Watchlist_{run_ts}.csv")
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        return None, pd.DataFrame(), run_ts
    return path, pd.read_csv(path), run_ts


def _closed_avg_days_held_map(
    prefix: str, drive: Path, run_ts: Optional[str]
) -> dict[str, float]:
    """
    Mean DAYS_HELD from the Closed CSV for the same LatestRun stamp as the scanner.
    Keyed by uppercased SYMBOL. Empty when Closed is missing or has no usable days.
    """
    pfx = prefix.upper()
    candidates: list[Path] = []
    if run_ts:
        candidates.append(drive / f"{pfx}_Closed_{run_ts}.csv")
        if pfx == "WPBR":
            candidates.append(drive / f"PBR_Closed_{run_ts}.csv")
    if pfx == "VZ":
        candidates.append(drive / "VZ_LatestRun_Closed.csv")
    if not candidates:
        return {}
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        return {}
    try:
        df = pd.read_csv(path)
    except Exception:
        return {}
    cols = {str(c).upper(): c for c in df.columns}
    sym_col = cols.get("SYMBOL")
    days_col = cols.get("DAYS_HELD")
    if sym_col is None or days_col is None or df.empty:
        return {}
    days = pd.to_numeric(df[days_col], errors="coerce")
    syms = df[sym_col].astype(str).str.strip().str.upper()
    tmp = pd.DataFrame({"symbol": syms, "days": days}).dropna(subset=["days"])
    if tmp.empty:
        return {}
    means = tmp.groupby("symbol", sort=False)["days"].mean()
    return {str(sym): float(val) for sym, val in means.items() if str(sym)}


def _fmt_avg_days_held(avg: Optional[float]) -> str:
    if avg is None:
        return "—"
    return f"{avg:.1f}"


def _fmt_money(v: float) -> str:
    sign = "-" if v < 0 else ""
    av = abs(v)
    if av >= 1_000_000:
        return f"{sign}${av/1_000_000:.2f}M"
    if av >= 10_000:
        return f"{sign}${av/1_000:.1f}K"
    return f"{sign}${av:,.2f}"


# Illustrative broker rows (not from Accounts_History; excluded from all P&L metrics).
_SHOWCASE_BROKER_HEADERS = [
    "Run Date",
    "Action",
    "Symbol",
    "Description",
    "Currency",
    "Price",
    "Quantity",
    "Amount",
    "Settlement Date",
]


def _showcase_illustrative_broker_rows() -> list[list[str]]:
    return [
        [
            "6/12/1981",
            "YOU BOUGHT Apple TECHNOLOGIES COM USD0.01 (AAPL) (Margin)",
            "AAPL",
            "Apple",
            "USD",
            "0.1479",
            "18602",
            "-$2,751.32",
            "6/12/1981",
        ],
        [
            "06/12/2026",
            "YOU SOLD Apple INC (AAPL) (Margin)",
            "AAPL",
            "Apple",
            "USD",
            "297.14",
            "18602",
            "$5,527,398.28",
            "06/12/2026",
        ],
    ]


def _showcase_illustrative_closed_summary_row() -> list[str]:
    buy_price = 0.1479
    sell_price = 297.14
    qty = 18602.0
    buy_d = date(1981, 6, 12)
    sell_d = date(2026, 6, 12)
    pnl = qty * (sell_price - buy_price)
    pnl_pct = (sell_price - buy_price) / buy_price * 100.0 if buy_price else 0.0
    return [
        "AAPL",
        "Illustrative",
        buy_d.strftime("%m/%d/%Y"),
        f"${buy_price:.4f}",
        sell_d.strftime("%m/%d/%Y"),
        f"${sell_price:.2f}",
        str(max(0, (sell_d - buy_d).days)),
        f"{pnl_pct:+.2f}%",
        f"${pnl:,.2f}",
        f"{qty:,.0f}",
    ]


def _resolve_logo_src() -> Optional[Path]:
    if LOGO_DOWNLOADS.is_file():
        return LOGO_DOWNLOADS
    if LOGO_DOCS.is_file():
        return LOGO_DOCS
    return None


def _build_web_logo(dst: Path) -> bool:
    src = _resolve_logo_src()
    if src is None:
        return False
    from PIL import Image

    target_h = LOGO_DISPLAY_MAX_HEIGHT_PX * LOGO_RETINA_SCALE
    im = Image.open(src).convert("RGBA")
    w = max(1, int(im.width * target_h / im.height))
    im = im.resize((w, target_h), Image.Resampling.LANCZOS)
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, format="PNG", optimize=True, compress_level=9)
    return True


def _copy_logo_beside(out: Path) -> str:
    dst = out.parent / LOGO_FILENAME
    if not _build_web_logo(dst):
        return ""
    return LOGO_FILENAME


def _resolve_showcase_aapl_image_src() -> Optional[Path]:
    docs_img = ROOT / "docs" / SHOWCASE_AAPL_IMAGE_FILENAME
    if docs_img.is_file():
        return docs_img
    if SHOWCASE_AAPL_IMAGE_DOWNLOADS.is_file():
        return SHOWCASE_AAPL_IMAGE_DOWNLOADS
    return None


def _copy_showcase_aapl_image_beside(out: Path) -> str:
    src = _resolve_showcase_aapl_image_src()
    if src is None:
        return ""
    dst = out.parent / SHOWCASE_AAPL_IMAGE_FILENAME
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != dst.resolve():
        shutil.copy2(src, dst)
    return SHOWCASE_AAPL_IMAGE_FILENAME


def _fig_to_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _chart_cumulative_pnl(
    closed: list[ClosedTrade],
    chart_start: date,
    chart_end: Optional[date] = None,
) -> str:
    chart_end = chart_end or date.today()
    if chart_end < chart_start:
        chart_start, chart_end = chart_end, chart_start

    daily_pnl: dict[date, float] = {}
    for t in closed:
        daily_pnl[t.sell_date] = daily_pnl.get(t.sell_date, 0.0) + t.pnl_dollars

    days = pd.date_range(pd.Timestamp(chart_start), pd.Timestamp(chart_end), freq="D")
    cum = 0.0
    xs: list[pd.Timestamp] = []
    ys: list[float] = []
    for d in days:
        cum += daily_pnl.get(d.date(), 0.0)
        xs.append(d)
        ys.append(cum)

    trade_days = [d for d in days if daily_pnl.get(d.date(), 0.0) != 0.0]
    trade_x = [d for d in trade_days]
    trade_y = [ys[days.get_loc(d)] for d in trade_days]

    fig, ax = plt.subplots(figsize=(9, 3.2))
    ax.plot(
        xs,
        ys,
        color="#4c1d95",
        linewidth=2,
        drawstyle="steps-post",
        label="Cumulative realized P&L",
    )
    if trade_x:
        ax.scatter(trade_x, trade_y, color="#4c1d95", s=28, zorder=3, edgecolors="white", linewidths=0.6)
    ax.fill_between(xs, ys, 0, where=[y >= 0 for y in ys], color="#bbf7d0", alpha=0.35, step="post")
    ax.fill_between(xs, ys, 0, where=[y < 0 for y in ys], color="#fecaca", alpha=0.35, step="post")
    ax.axhline(0, color="#94a3b8", linewidth=1, linestyle="--")
    ax.set_title(
        f"Cumulative realized P&L — flat between sell dates ({chart_start:%m/%d/%y} – {chart_end:%m/%d/%y})",
        fontsize=11,
    )
    ax.set_xlim(pd.Timestamp(chart_start), pd.Timestamp(chart_end) + pd.Timedelta(hours=12))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=5, maxticks=10))
    fig.autofmt_xdate()
    ax.grid(True, alpha=0.25)
    ax.legend(loc="upper left", fontsize=8, framealpha=0.9)
    return _fig_to_b64(fig)


def _chart_win_gauge(wins: int, losses: int, be: int) -> str:
    total = max(wins + losses + be, 1)
    wpct = wins / total * 100
    fig, ax = plt.subplots(figsize=(2.2, 1.6), subplot_kw={"aspect": "equal"})
    sizes = [wins, be, losses]
    colors = ["#22c55e", "#60a5fa", "#ef4444"]
    if sum(sizes) == 0:
        sizes, colors = [1], ["#e5e7eb"]
    ax.pie(
        sizes,
        colors=colors,
        startangle=180,
        counterclock=False,
        wedgeprops={"width": 0.35, "edgecolor": "white"},
    )
    ax.text(0, 0, f"{wpct:.1f}%", ha="center", va="center", fontsize=14, fontweight="bold")
    ax.set_title("")
    return _fig_to_b64(fig)


def _chart_profit_factor(wins_sum: float, losses_sum: float) -> str:
    fig, ax = plt.subplots(figsize=(2.2, 1.6), subplot_kw={"aspect": "equal"})
    gw = max(wins_sum, 0)
    gl = max(abs(losses_sum), 0)
    if gw + gl == 0:
        ax.pie([1], colors=["#e5e7eb"])
    else:
        ax.pie([gw, gl], colors=["#22c55e", "#ef4444"], wedgeprops={"width": 0.35, "edgecolor": "white"})
    ax.text(0, 0, "", ha="center", va="center")
    return _fig_to_b64(fig)


def _chart_avg_win_loss(
    avg_win: float,
    avg_loss: float,
    avg_win_pct: float,
    avg_loss_pct: float,
) -> str:
    fig, ax = plt.subplots(figsize=(6.5, 1.45))
    aw, al = max(avg_win, 0), max(abs(avg_loss), 0)
    total = aw + al if aw + al else 1
    ax.barh([0], [aw / total], color="#22c55e", height=0.5)
    ax.barh([0], [al / total], left=[aw / total], color="#ef4444", height=0.5)
    ax.set_xlim(0, 1)
    ax.axis("off")
    ratio = aw / al if al else float("inf")
    ax.text(0.02, -0.55, f"{_fmt_money(aw)} ({avg_win_pct:+.1f}%)", color="#16a34a", fontsize=10, transform=ax.transAxes)
    ax.text(
        0.98,
        -0.55,
        f"-{_fmt_money(al)} ({avg_loss_pct:+.1f}%)",
        color="#dc2626",
        fontsize=10,
        ha="right",
        transform=ax.transAxes,
    )
    ax.text(0.5, 0.5, f"{ratio:.2f}" if al else "—", ha="center", va="center", fontsize=20, fontweight="bold")
    ax.set_title("Avg win/loss trade ($ and %)", fontsize=11, loc="left")
    return _fig_to_b64(fig)


_SORTABLE_TABLE_SCRIPT = """
<script>
(function () {
  function parseSortValue(text, type) {
    const s = String(text || "").trim();
    if (!s) return type === "text" ? "" : 0;
    if (type === "text") return s.toUpperCase();
    if (type === "date") {
      const m = s.match(/(\\d{1,2})\\/(\\d{1,2})\\/(\\d{4})/);
      if (m) return parseInt(m[3] + m[1].padStart(2, "0") + m[2].padStart(2, "0"), 10);
      return 0;
    }
    let n = s.replace(/[$,%+]/g, "").replace(/,/g, "");
    if (n === "" || n === "—" || n === "-") return 0;
    const v = parseFloat(n);
    return Number.isFinite(v) ? v : 0;
  }
  function sortTable(table, col, type, dir) {
    const tbody = table.tBodies[0];
    if (!tbody) return;
    const rows = Array.from(tbody.querySelectorAll("tr"));
    rows.sort((a, b) => {
      const av = parseSortValue(a.cells[col] && a.cells[col].textContent, type);
      const bv = parseSortValue(b.cells[col] && b.cells[col].textContent, type);
      if (typeof av === "string" || typeof bv === "string") {
        return dir * String(av).localeCompare(String(bv));
      }
      return dir * (av - bv);
    });
    rows.forEach((r) => tbody.appendChild(r));
  }
  function bindSortHeader(table, th, col) {
    function onActivate(e) {
      if (e.type === "touchend") e.preventDefault();
      const type = th.dataset.sort || "text";
      const dir = th.dataset.dir === "asc" ? -1 : 1;
      table.querySelectorAll("th.sortable-th").forEach((h) => {
        h.dataset.dir = "";
        h.classList.remove("sort-asc", "sort-desc");
      });
      th.dataset.dir = dir === 1 ? "asc" : "desc";
      th.classList.add(dir === 1 ? "sort-asc" : "sort-desc");
      sortTable(table, col, type, dir);
    }
    th.addEventListener("click", onActivate);
    th.addEventListener("touchend", onActivate, { passive: false });
  }
  document.querySelectorAll("table.sortable").forEach((table) => {
    table.querySelectorAll("th.sortable-th").forEach((th, col) => bindSortHeader(table, th, col));
  });
})();
</script>
"""


def _system_subset_key(systems: frozenset[str]) -> str:
    return "+".join(s for s in REPORT_SYSTEMS if s in systems)


def _nonempty_system_subsets() -> list[frozenset[str]]:
    out: list[frozenset[str]] = []
    for mask in range(1, 1 << len(REPORT_SYSTEMS)):
        out.append(frozenset(REPORT_SYSTEMS[i] for i in range(len(REPORT_SYSTEMS)) if mask & (1 << i)))
    return out


def _filter_closed_by_systems(closed: list[ClosedTrade], systems: frozenset[str]) -> list[ClosedTrade]:
    return [t for t in closed if t.system in systems]


def _summary_for_closed(
    closed: list[ClosedTrade],
    open_agg: dict[tuple[str, str], Lot],
    open_keys: set[tuple[str, str]],
    gt_df: pd.DataFrame,
    systems: frozenset[str],
) -> dict:
    fc = _filter_closed_by_systems(closed, systems)
    wins = [t for t in fc if t.pnl_dollars > 0]
    losses = [t for t in fc if t.pnl_dollars < 0]
    be = [t for t in fc if abs(t.pnl_dollars) < 1e-6]
    win_sum = sum(t.pnl_dollars for t in wins)
    loss_sum = sum(t.pnl_dollars for t in losses)
    pf = win_sum / abs(loss_sum) if loss_sum else float("inf")
    avg_win = win_sum / len(wins) if wins else 0.0
    avg_loss = loss_sum / len(losses) if losses else 0.0
    avg_win_pct = sum(t.pnl_pct for t in wins) / len(wins) if wins else 0.0
    avg_loss_pct = sum(t.pnl_pct for t in losses) / len(losses) if losses else 0.0
    win_pct = len(wins) / len(fc) * 100 if fc else 0.0
    unrealized = 0.0
    for key, lot in open_agg.items():
        if key not in open_keys or lot.system not in systems:
            continue
        r = _gettarget_row_for_lot(gt_df, lot)
        cur = float(r["CurrentPrice"]) if r is not None else lot.buy_price
        unrealized += (cur - lot.buy_price) * lot.qty
    return {
        "realized": sum(t.pnl_dollars for t in fc),
        "unrealized": unrealized,
        "closed_count": len(fc),
        "wins": len(wins),
        "losses": len(losses),
        "be": len(be),
        "win_pct": win_pct,
        "pf": pf,
        "win_sum": win_sum,
        "loss_sum": loss_sum,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "avg_win_pct": avg_win_pct,
        "avg_loss_pct": avg_loss_pct,
    }


def _build_system_filter_bundles(
    closed: list[ClosedTrade],
    *,
    chart_start: date,
    chart_end: date,
    open_agg: dict[tuple[str, str], Lot],
    open_keys: set[tuple[str, str]],
    gt_df: pd.DataFrame,
) -> tuple[dict[str, dict], dict[str, dict]]:
    """Precompute metrics + chart PNGs for every non-empty system subset."""
    metrics_by_key: dict[str, dict] = {}
    charts_by_key: dict[str, dict] = {}
    for subset in _nonempty_system_subsets():
        key = _system_subset_key(subset)
        fc = _filter_closed_by_systems(closed, subset)
        sm = _summary_for_closed(closed, open_agg, open_keys, gt_df, subset)
        metrics_by_key[key] = {
            "realized_fmt": _fmt_money(sm["realized"]),
            "realized_pos": sm["realized"] >= 0,
            "unrealized_fmt": _fmt_money(sm["unrealized"]),
            "closed_table_total_fmt": _fmt_money(sm["realized"]),
            "open_table_total_fmt": _fmt_money(sm["unrealized"]),
            "closed_count": sm["closed_count"],
            "wins": sm["wins"],
            "be": sm["be"],
            "losses": sm["losses"],
            "win_pct": f"{sm['win_pct']:.2f}",
            "pf": f"{sm['pf']:.2f}" if sm["pf"] != float("inf") else "—",
            "win_sum_fmt": _fmt_money(sm["win_sum"]),
            "loss_sum_fmt": _fmt_money(sm["loss_sum"]),
        }
        charts_by_key[key] = {
            "cum": _chart_cumulative_pnl(fc, chart_start=chart_start, chart_end=chart_end),
            "gauge": _chart_win_gauge(sm["wins"], sm["losses"], sm["be"]),
            "pf": _chart_profit_factor(sm["win_sum"], sm["loss_sum"]),
            "awl": _chart_avg_win_loss(
                sm["avg_win"], sm["avg_loss"], sm["avg_win_pct"], sm["avg_loss_pct"]
            ),
        }
    return metrics_by_key, charts_by_key


def _html_table(
    headers: list[str],
    rows: list[list[str]],
    sort_types: Optional[list[str]] = None,
    system_col: Optional[int] = None,
    footer_row: Optional[list[str]] = None,
    *,
    table_id: Optional[str] = None,
    footer_pnl_cell_id: Optional[str] = None,
    footer_pnl_col: Optional[int] = None,
) -> str:
    types = sort_types or ["text"] * len(headers)
    th = "".join(
        f'<th class="sortable-th" data-sort="{types[i] if i < len(types) else "text"}" '
        f'tabindex="0" role="columnheader" aria-sort="none">{h}<span class="sort-ind"></span></th>'
        for i, h in enumerate(headers)
    )
    body = ""
    for row in rows:
        sys_attr = ""
        if system_col is not None and 0 <= system_col < len(row):
            sys_val = _normalize_report_system(str(row[system_col]).strip().upper())
            if sys_val:
                sys_attr = f' data-system="{sys_val}"'
        body += f"<tr{sys_attr}>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>"
    foot = ""
    if footer_row:
        foot_cells: list[str] = []
        for i, c in enumerate(footer_row):
            if footer_pnl_cell_id and footer_pnl_col is not None and i == footer_pnl_col:
                foot_cells.append(f'<td><span id="{footer_pnl_cell_id}">{c}</span></td>')
            else:
                foot_cells.append(f"<td>{c}</td>")
        foot = '<tfoot><tr class="table-total">' + "".join(foot_cells) + "</tr></tfoot>"
    table_id_attr = f' id="{table_id}"' if table_id else ""
    return f'<table class="sortable"{table_id_attr}><thead><tr>{th}</tr></thead><tbody>{body}</tbody>{foot}</table>'


def _showcase_illustrative_section_html(image_file: str = "") -> str:
    photo_html = ""
    if image_file:
        photo_html = (
            f'<figure class="showcase-photo">'
            f'<img src="{image_file}" alt="Illustrative AAPL buy and hold" class="showcase-photo-img">'
            f"</figure>"
        )
    broker_table = _html_table(
        _SHOWCASE_BROKER_HEADERS,
        _showcase_illustrative_broker_rows(),
        ["date", "text", "text", "text", "text", "num", "num", "num", "date"],
        table_id="showcase-broker-table",
    )
    summary_table = _html_table(
        [
            "Symbol",
            "System",
            "Buy Date",
            "Buy Price",
            "Sell Date",
            "Sell Price",
            "Days Held",
            "Gain/Loss %",
            "Gain/Loss $",
            "Shares",
        ],
        [_showcase_illustrative_closed_summary_row()],
        ["text", "text", "date", "num", "date", "num", "num", "num", "num", "num"],
        table_id="showcase-closed-summary-table",
    )
    return f"""
<section class="showcase-section">
<h2>Illustrative — Buy &amp; Hold (AAPL)</h2>
<p class="small">Example broker activity only — not from your Fidelity export and <strong>not included</strong> in realized P&amp;L, win rate, profit factor, or charts above.</p>
{photo_html}
<h3>Broker activity (Fidelity-style)</h3>
<div class="table-wrap">{broker_table}</div>
<h3>Round-trip summary</h3>
<div class="table-wrap">{summary_table}</div>
</section>
"""


_SYSTEM_FILTER_SCRIPT = """
<script>
(function () {
  const metricsByKey = __METRICS_JSON__;
  const chartsByKey = __CHARTS_JSON__;
  const systems = __SYSTEMS_JSON__;

  function selectedSystems() {
    const sel = new Set();
    document.querySelectorAll("#system-filter .sys-chip.active").forEach((btn) => {
      sel.add(btn.dataset.sys);
    });
    return sel;
  }

  function subsetKey(sel) {
    return systems.filter((s) => sel.has(s)).join("+");
  }

  function applySystemFilter() {
    const sel = selectedSystems();
    const key = subsetKey(sel);
    document.querySelectorAll("[data-system]").forEach((row) => {
      const sys = row.dataset.system;
      // Systems not on the chip list (e.g. research VZ) stay visible.
      row.style.display = !sys || sel.has(sys) || systems.indexOf(sys) < 0 ? "" : "none";
    });
    document.querySelectorAll("[data-system-section]").forEach((sec) => {
      sec.style.display = sel.has(sec.dataset.systemSection) ? "" : "none";
    });
    const m = metricsByKey[key];
    const c = chartsByKey[key];
    if (!m || !c) return;
    const realizedEl = document.getElementById("metric-realized");
    if (realizedEl) {
      realizedEl.textContent = m.realized_fmt;
      realizedEl.classList.toggle("pos", m.realized_pos);
      realizedEl.classList.toggle("neg", !m.realized_pos);
    }
    const realizedSub = document.getElementById("metric-realized-sub");
    if (realizedSub) {
      realizedSub.textContent =
        m.closed_count + " closed round-trips · Unrealized (open est.) " + m.unrealized_fmt;
    }
    const winPct = document.getElementById("metric-win-pct");
    if (winPct) winPct.textContent = m.win_pct + "%";
    const winSub = document.getElementById("metric-win-sub");
    if (winSub) winSub.textContent = "W " + m.wins + " · BE " + m.be + " · L " + m.losses;
    const pfEl = document.getElementById("metric-pf");
    if (pfEl) pfEl.textContent = m.pf;
    const pfSub = document.getElementById("metric-pf-sub");
    if (pfSub) {
      pfSub.textContent = "Gross wins " + m.win_sum_fmt + " · Gross losses " + m.loss_sum_fmt;
    }
    const closedFoot = document.getElementById("closed-footer-pnl");
    if (closedFoot && m.closed_table_total_fmt) {
      closedFoot.textContent = m.closed_table_total_fmt;
    }
    const openFoot = document.getElementById("open-footer-pnl");
    if (openFoot && m.open_table_total_fmt) {
      openFoot.textContent = m.open_table_total_fmt;
    }
    const pendWarn = document.getElementById("pending-sells-warn");
    if (pendWarn && m.pending_sells_count !== undefined) {
      if (m.pending_sells_count > 0) {
        pendWarn.style.display = "";
        pendWarn.innerHTML =
          "⚠ " + m.pending_sells_count + " open position(s) need a manual sell action — see Exit reason / When (Fidelity stop/target alone is not enough for time exits).";
      } else {
        pendWarn.style.display = "none";
      }
    }
    const pendSec = document.getElementById("pending-sells-section");
    if (pendSec) {
      pendSec.style.display = (m.pending_sells_count || 0) > 0 ? "" : "none";
    }
    const imgMap = [
      ["chart-gauge", "gauge"],
      ["chart-pf", "pf"],
      ["chart-awl", "awl"],
      ["chart-cum", "cum"],
    ];
    imgMap.forEach(([id, field]) => {
      const el = document.getElementById(id);
      if (el && c[field]) el.src = "data:image/png;base64," + c[field];
    });
  }

  function toggleChip(btn) {
    const sel = selectedSystems();
    if (sel.size === 1 && btn.classList.contains("active")) {
      return;
    }
    btn.classList.toggle("active");
    btn.setAttribute("aria-pressed", btn.classList.contains("active") ? "true" : "false");
    if (selectedSystems().size === 0) {
      btn.classList.add("active");
      btn.setAttribute("aria-pressed", "true");
    }
    applySystemFilter();
  }

  document.querySelectorAll("#system-filter .sys-chip").forEach((btn) => {
    function onTap(e) {
      if (e.type === "touchend") e.preventDefault();
      toggleChip(btn);
    }
    btn.addEventListener("click", onTap);
    btn.addEventListener("touchend", onTap, { passive: false });
  });
  applySystemFilter();
})();
</script>
"""


def build_report(
    *,
    accounts_path: Optional[Path] = None,
    gettarget_path: Path = DEFAULT_GETTARGET,
    positions_path: Path = DEFAULT_POSITIONS,
    registry_path: Path = DEFAULT_TRADE_REGISTRY,
    closed_log_path: Path = DEFAULT_CLOSED_LOG,
    drive_dir: Path = DRIVE,
    closed_since: date = CLOSED_SINCE,
    min_position_value: float = MIN_POSITION_VALUE,
    output_path: Optional[Path] = None,
    include_showcase_aapl: Optional[bool] = None,
) -> Path:
    accounts_path = accounts_path or _latest_accounts_history(DOWNLOADS)
    acct, accounts_source = _load_accounts_for_report(DOWNLOADS, positions_path, accounts_path)
    recent_path = _latest_recent_history_export(DOWNLOADS)
    recent_sells = _load_recent_history_stock_sells(recent_path) if recent_path else pd.DataFrame()
    if recent_path is not None and not recent_sells.empty and "+ registry buys:" not in accounts_source:
        accounts_source = f"{accounts_source} + {recent_path.name} (sell supplement)"
    sys_map, entry_prices = _build_full_system_map(
        drive_dir=drive_dir,
        positions_path=positions_path,
        gettarget_path=gettarget_path,
        registry_path=registry_path,
    )
    raw_closed, open_lots = _fifo_closed_and_open(acct, closed_since, sys_map, entry_prices)
    fifo_closed = _aggregate_closed_by_entry(
        raw_closed, min_position_value=min_position_value, sys_map=sys_map
    )
    closed, log_appended = _sync_closed_positions_log(
        closed_log_path,
        fifo_closed,
        closed_since=closed_since,
        min_position_value=min_position_value,
        sys_map=sys_map,
    )
    if log_appended:
        print(f"Appended {log_appended} closed position(s) to {closed_log_path.name}")
    open_agg = _aggregate_lots_by_entry(open_lots)
    open_agg, open_lots = _ensure_open_lots_for_registry(
        open_agg, open_lots, positions_path, sys_map, entry_prices, DOWNLOADS
    )
    open_df = _load_open_positions(gettarget_path)
    now_et = _now_et()
    fifo_open_keys = {
        key
        for key, lot in open_agg.items()
        if _meets_position_size_threshold(
            _position_value(lot.qty, lot.buy_price),
            lot.symbol,
            lot.buy_date,
            sys_map,
            min_position_value=min_position_value,
        )
    }
    open_keys = _registry_open_keys(positions_path) | fifo_open_keys

    open_df, open_prices_as_of, open_price_source = _maybe_refresh_open_prices(
        open_df, open_agg, open_keys, gettarget_path, now_et=now_et
    )

    # Persist resolved entries back into the registry (symbol + entry date + system).
    resolved_rows = [
        (t.symbol, t.buy_date.isoformat(), t.system)
        for t in closed
        if t.system in REPORT_SYSTEMS
    ] + [
        (lot.symbol, lot.buy_date.isoformat(), lot.system)
        for lot in open_agg.values()
        if lot.system in REPORT_SYSTEMS
    ]
    _persist_trade_registry(registry_path, sys_map, extra_rows=resolved_rows)

    realized = sum(t.pnl_dollars for t in closed)
    unrealized = 0.0
    for key, lot in open_agg.items():
        if key not in open_keys:
            continue
        r = _gettarget_row_for_lot(open_df, lot)
        cur = float(r["CurrentPrice"]) if r is not None else lot.buy_price
        unrealized += (cur - lot.buy_price) * lot.qty

    wins = [t for t in closed if t.pnl_dollars > 0]
    losses = [t for t in closed if t.pnl_dollars < 0]
    be = [t for t in closed if abs(t.pnl_dollars) < 1e-6]
    win_sum = sum(t.pnl_dollars for t in wins)
    loss_sum = sum(t.pnl_dollars for t in losses)
    pf = win_sum / abs(loss_sum) if loss_sum else float("inf")
    avg_win = win_sum / len(wins) if wins else 0.0
    avg_loss = loss_sum / len(losses) if losses else 0.0
    avg_win_pct = sum(t.pnl_pct for t in wins) / len(wins) if wins else 0.0
    avg_loss_pct = sum(t.pnl_pct for t in losses) / len(losses) if losses else 0.0
    win_pct = len(wins) / len(closed) * 100 if closed else 0.0

    ind_scan_path, ind_scan, ind_run_ts = _scanner_for_latest_run("IND", drive_dir)
    brt_scan_path, brt_scan, brt_run_ts = _scanner_for_latest_run("BRT", drive_dir)
    rl_scan_path, rl_scan, rl_run_ts = _scanner_for_latest_run("RL", drive_dir)
    yh_scan_path, yh_scan, yh_run_ts = _scanner_for_latest_run("YH", drive_dir)
    mts_scan_path, mts_scan, mts_run_ts = _scanner_for_latest_run("MTS", drive_dir)
    wpbr_scan_path, wpbr_scan, wpbr_run_ts = _scanner_for_latest_run("WPBR", drive_dir)
    rs_scan_path, rs_scan, rs_run_ts = _scanner_for_latest_run("RS", drive_dir)
    sb_scan_path, sb_scan, sb_run_ts = _scanner_for_latest_run("SB", drive_dir)
    vz_scan_path, vz_scan, vz_run_ts = _scanner_for_latest_run("VZ", drive_dir)

    metrics_by_key, charts_by_key = _build_system_filter_bundles(
        closed,
        chart_start=closed_since,
        chart_end=date.today(),
        open_agg=open_agg,
        open_keys=open_keys,
        gt_df=open_df,
    )
    all_key = _system_subset_key(frozenset(REPORT_SYSTEMS))
    default_charts = charts_by_key[all_key]
    default_metrics = metrics_by_key[all_key]

    cum_b64 = default_charts["cum"]
    gauge_b64 = default_charts["gauge"]
    pf_b64 = default_charts["pf"]
    awl_b64 = default_charts["awl"]

    closed_rows = []
    closed_gain_total = 0.0
    for t in closed:
        days_held = max(0, (t.sell_date - t.buy_date).days)
        closed_gain_total += t.pnl_dollars
        closed_rows.append(
            [
                t.symbol,
                t.system,
                t.buy_date.strftime("%m/%d/%Y"),
                f"${t.buy_price:.2f}",
                t.sell_date.strftime("%m/%d/%Y"),
                f"${t.sell_price:.2f}",
                str(days_held),
                f"{t.pnl_pct:+.2f}%",
                _fmt_money(t.pnl_dollars),
                f"{t.qty:,.0f}",
            ]
        )
    closed_footer = (
        ["Total", "", "", "", "", "", "", "", _fmt_money(closed_gain_total), ""]
        if closed_rows
        else None
    )

    open_price_ts = _format_et_datetime(open_prices_as_of)
    open_rows = []
    open_gain_total = 0.0
    for key in sorted(open_keys):
        lot = open_agg.get(key)
        if lot is None:
            continue
        r = _gettarget_row_for_lot(open_df, lot)
        if r is not None:
            entry = float(r["EntryPrice"])
            cur = float(r["CurrentPrice"])
            gain_pct = float(r["GainPct"])
            pnl_d = (cur - entry) * lot.qty
            open_gain_total += pnl_d
            open_rows.append(
                [
                    lot.symbol,
                    lot.system,
                    lot.buy_date.strftime("%m/%d/%Y"),
                    f"${entry:.2f}",
                    f"${cur:.2f}",
                    open_price_ts,
                    f"{gain_pct:+.2f}%",
                    _fmt_money(pnl_d),
                    f"${float(r['TargetPrice']):.2f}" if pd.notna(r["TargetPrice"]) else "",
                    f"${float(r['StopLoss']):.2f}" if pd.notna(r["StopLoss"]) else "",
                ]
            )
        else:
            open_rows.append(
                [
                    lot.symbol,
                    lot.system,
                    lot.buy_date.strftime("%m/%d/%Y"),
                    f"${lot.buy_price:.2f}",
                    f"${lot.buy_price:.2f}",
                    open_price_ts,
                    "—",
                    "—",
                    "",
                    "",
                ]
            )
    open_footer = (
        ["Total", "", "", "", "", "", "", _fmt_money(open_gain_total), "", ""]
        if open_rows
        else None
    )

    def _scan_rows(
        df: pd.DataFrame,
        avg_days_by_symbol: Optional[dict[str, float]] = None,
        limit: int = 50,
    ) -> tuple[list[list[str]], list[str], list[str]]:
        if df.empty:
            return [], [], []
        cols = list(df.columns)
        pick = [
            c
            for c in [
                "SYMBOL",
                "DATE",
                "CLOSE",
                "ENTRY_OPEN_BAND",
                "MIN_ENTRY_OPEN",
                "MAX_ENTRY_OPEN",
                "PRIOR_DAY_CLOSE",
                "TARGET",
                "STOP_LOSS",
                "IND_SCORE",
                "IND_DIFF",
                "TRIGGER_DATE",
                "TRIGGER_CLOSE",
                "ENTRY_DATE",
                "ENTRY_OPEN_REF",
                "TOO_HIGH_LINE",
                "ENTRY_ALLOWED",
                "ASOF_DATE",
                "POC",
                "HVN $",
                "HVN pass?",
                "SIGNAL_DATE",
                "PCT_DAY",
                "DCR",
                "RANGE_EXP",
                "VOL_RATIO",
                "SIGNAL_LOW",
                "MUST_OPEN_ABOVE",
                "MUST_OPEN_AT_OR_BELOW",
                "MAX_RISK_PCT",
                "NOTES",
            ]
            if c in cols
        ]
        if not pick:
            pick = cols[:8]
        sym_key = "SYMBOL" if "SYMBOL" in cols else ("Symbol" if "Symbol" in cols else None)
        avg_map = avg_days_by_symbol or {}
        out: list[list[str]] = []
        for _, r in df.head(limit).iterrows():
            row = [str(r.get(c, "")) for c in pick]
            sym = str(r.get(sym_key, "")).strip().upper() if sym_key else ""
            row.append(_fmt_avg_days_held(avg_map.get(sym) if sym else None))
            out.append(row)
        headers = list(pick) + ["Prior avg days held"]
        # Prefer num for known numeric scanner fields; keep SYMBOL/dates/notes as text.
        num_like = {
            "CLOSE",
            "ENTRY_OPEN_BAND",
            "MIN_ENTRY_OPEN",
            "MAX_ENTRY_OPEN",
            "PRIOR_DAY_CLOSE",
            "TARGET",
            "STOP_LOSS",
            "IND_SCORE",
            "IND_DIFF",
            "TRIGGER_CLOSE",
            "ENTRY_OPEN_REF",
            "TOO_HIGH_LINE",
            "PCT_DAY",
            "DCR",
            "RANGE_EXP",
            "VOL_RATIO",
            "SIGNAL_LOW",
            "MUST_OPEN_ABOVE",
            "MUST_OPEN_AT_OR_BELOW",
            "MAX_RISK_PCT",
            "POC",
        }
        date_like = {
            "DATE",
            "TRIGGER_DATE",
            "ENTRY_DATE",
            "ASOF_DATE",
            "SIGNAL_DATE",
        }
        sort_types: list[str] = []
        for c in pick:
            cu = str(c).upper()
            if cu in num_like:
                sort_types.append("num")
            elif cu in date_like:
                sort_types.append("date")
            else:
                sort_types.append("text")
        sort_types.append("num")
        return out, headers, sort_types

    ind_rows, ind_cols, ind_sort = _scan_rows(
        ind_scan, _closed_avg_days_held_map("IND", drive_dir, ind_run_ts)
    )
    brt_rows, brt_cols, brt_sort = _scan_rows(
        brt_scan, _closed_avg_days_held_map("BRT", drive_dir, brt_run_ts)
    )
    rl_rows, rl_cols, rl_sort = _scan_rows(
        rl_scan, _closed_avg_days_held_map("RL", drive_dir, rl_run_ts)
    )
    yh_rows, yh_cols, yh_sort = _scan_rows(
        yh_scan, _closed_avg_days_held_map("YH", drive_dir, yh_run_ts)
    )
    mts_rows, mts_cols, mts_sort = _scan_rows(
        mts_scan, _closed_avg_days_held_map("MTS", drive_dir, mts_run_ts)
    )
    wpbr_rows, wpbr_cols, wpbr_sort = _scan_rows(
        wpbr_scan, _closed_avg_days_held_map("WPBR", drive_dir, wpbr_run_ts)
    )
    rs_rows, rs_cols, rs_sort = _scan_rows(
        rs_scan, _closed_avg_days_held_map("RS", drive_dir, rs_run_ts)
    )
    sb_rows, sb_cols, sb_sort = _scan_rows(
        sb_scan, _closed_avg_days_held_map("SB", drive_dir, sb_run_ts)
    )
    vz_scan = _enrich_vz_watchlist_hvn(vz_scan, drive_dir, vz_run_ts)
    vz_rows, vz_cols, vz_sort = _scan_rows(
        vz_scan, _closed_avg_days_held_map("VZ", drive_dir, vz_run_ts)
    )

    pending_sells, sell_thresholds, sell_time_params, sell_as_of = find_all_pending_sells(
        positions_path=positions_path,
        gettarget_path=gettarget_path,
        drive_dir=drive_dir,
    )
    sell_section_html = sell_report_html_section(
        pending_sells,
        sell_thresholds,
        sell_as_of,
        html_table_fn=lambda h, r, st=None, **kw: _html_table(
            h, r, st, system_col=1, **kw
        ),
        time_params=sell_time_params,
    )

    report_sys_set = frozenset(REPORT_SYSTEMS)
    for subset in _nonempty_system_subsets():
        key = _system_subset_key(subset)
        # Include research systems not on the chip list in every subset's sell count.
        metrics_by_key[key]["pending_sells_count"] = sum(
            1
            for p in pending_sells
            if p.system in subset or p.system not in report_sys_set
        )

    def _scanner_subtitle(path: Optional[Path], run_ts: Optional[str], label: str) -> str:
        if path and run_ts:
            return f"{path.name} (run {run_ts})"
        if run_ts:
            return f"No scanner for latest {label} run ({run_ts}); section omitted."
        return f"No {label} run outputs found in Drive."

    ind_scan_sub = _scanner_subtitle(ind_scan_path, ind_run_ts, "IND")
    brt_scan_sub = _scanner_subtitle(brt_scan_path, brt_run_ts, "BRT")
    rl_scan_sub = _scanner_subtitle(rl_scan_path, rl_run_ts, "RL")
    yh_scan_sub = _scanner_subtitle(yh_scan_path, yh_run_ts, "YH")
    mts_scan_sub = _scanner_subtitle(mts_scan_path, mts_run_ts, "MTS")
    wpbr_scan_sub = _scanner_subtitle(wpbr_scan_path, wpbr_run_ts, "WPBR")
    rs_scan_sub = _scanner_subtitle(rs_scan_path, rs_run_ts, "RS")
    sb_scan_sub = _scanner_subtitle(sb_scan_path, sb_run_ts, "SB")
    sb_section_title = (
        "Watchlist — SB"
        if sb_scan_path is not None and "Watchlist" in sb_scan_path.name
        else "Scanner — SB"
    )
    sb_empty_msg = (
        "No SB watchlist for the latest run."
        if sb_run_ts
        else "No SB run outputs found in Drive."
    )
    vz_scan_sub = _scanner_subtitle(vz_scan_path, vz_run_ts, "VZ")
    if vz_scan_path is not None and vz_run_ts is None:
        vz_scan_sub = f"{vz_scan_path.name} (VZ_LatestRun alias; no VZ_last_run_ts.txt pin)"
    if vz_rows:
        vz_scan_sub += (
            " · VP 60d / 0.5% bins / HVN≥50% POC @ signal bar (HVN pass? = "
            "vz_require_hvn_overlap; house default off — research only)"
        )
    vz_section_title = (
        "Watchlist — VZ"
        if vz_scan_path is not None
        and ("Watchlist" in vz_scan_path.name or "Open" in vz_scan_path.name)
        else "Scanner — VZ"
    )
    vz_empty_msg = (
        "No VZ open/watchlist rows for the latest run (Open lists live still_open positions; Watchlist mirrors them)."
        if vz_run_ts or vz_scan_path is not None
        else "No VZ run outputs found in Drive."
    )

    filter_buttons_html = "".join(
        f'  <button type="button" class="sys-chip active" data-sys="{sys}" aria-pressed="true">'
        f'{REPORT_SYSTEM_LABELS.get(sys, sys)}</button>\n'
        for sys in REPORT_SYSTEMS
    )

    now = _format_et_datetime(now_et)
    open_prices_note = _format_et_datetime(open_prices_as_of)
    out = output_path or (drive_dir / f"Investment_Report_{now_et.strftime('%Y%m%d_%H%M%S')}.html")
    logo_file = _copy_logo_beside(out)
    _showcase_on = (
        INCLUDE_SHOWCASE_AAPL_SECTION
        if include_showcase_aapl is None
        else bool(include_showcase_aapl)
    )
    showcase_image_file = _copy_showcase_aapl_image_beside(out) if _showcase_on else ""
    showcase_section_html = (
        _showcase_illustrative_section_html(showcase_image_file) if _showcase_on else ""
    )
    showcase_css = (
        """
.showcase-section { background:#fffbeb; border:1px solid #fde68a; border-radius:12px; padding:16px 20px; }
.showcase-section h3 { margin:16px 0 8px; font-size:1rem; color:#92400e; }
.showcase-photo { margin:12px 0 16px; }
.showcase-photo-img { display:block; max-width:min(100%, 420px); height:auto; border-radius:10px; border:1px solid #fde68a; box-shadow:0 2px 8px rgba(15,23,42,0.08); }
"""
        if _showcase_on
        else ""
    )
    sub_line = (
        f"Report generated {now} ET · Open prices as of {open_prices_note} ET ({open_price_source}) · "
        f"Closed since {closed_since:%b %d, %Y} · Purchases ≥ {_fmt_money(min_position_value)} · "
        f"Accounts: {accounts_source}"
    )
    if logo_file:
        title_block = f"""<header class="report-header">
  <img src="{logo_file}" alt="Twin Beacon Networks" class="report-logo">
  <div class="report-header-text">
    <h1>{REPORT_TITLE}</h1>
    <div class="sub">{sub_line}</div>
  </div>
</header>"""
    else:
        title_block = f"<h1>{REPORT_TITLE}</h1>\n<div class=\"sub\">{sub_line}</div>"

    filter_script = (
        _SYSTEM_FILTER_SCRIPT.replace("__METRICS_JSON__", json.dumps(metrics_by_key))
        .replace("__CHARTS_JSON__", json.dumps(charts_by_key))
        .replace("__SYSTEMS_JSON__", json.dumps(list(REPORT_SYSTEMS)))
    )

    from report_page_extras import CACHE_META, FORCE_RELOAD_SCRIPT

    html = f"""<!DOCTYPE html>
<html><head>
{CACHE_META}
{FORCE_RELOAD_SCRIPT}
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{REPORT_TITLE}</title>
<style>
* {{ box-sizing: border-box; }}
body {{ font-family: Arial, Helvetica, sans-serif; color:#0f172a; margin:24px; max-width:1200px; }}
h1 {{ margin-bottom:4px; font-size:clamp(1.25rem, 4vw, 1.75rem); }}
h2 {{ font-size:clamp(1.05rem, 3.5vw, 1.35rem); }}
.report-header {{ display:flex; align-items:center; gap:20px; margin-bottom:20px; flex-wrap:wrap; }}
.report-logo {{ display:block; max-height:{LOGO_DISPLAY_MAX_HEIGHT_PX}px; width:auto; }}
.report-header-text {{ flex:1 1 280px; min-width:0; }}
.report-header-text .sub {{ margin-bottom:0; }}
.sub {{ color:#64748b; margin-bottom:24px; font-size:clamp(0.8rem, 2.5vw, 0.95rem); line-height:1.45; }}
.cards {{ display:flex; flex-wrap:wrap; gap:16px; margin-bottom:16px; }}
.card {{ flex:1 1 260px; min-width:min(100%, 260px); background:#f8fafc; border:1px solid #e2e8f0; border-radius:12px; padding:16px; }}
.card-full {{ flex:1 1 100%; min-width:100%; }}
.card h3 {{ margin:0 0 8px; font-size:14px; color:#475569; font-weight:600; }}
.metric {{ font-size:clamp(1.35rem, 5vw, 1.75rem); font-weight:700; line-height:1.15; }}
.pos {{ color:#16a34a; }} .neg {{ color:#dc2626; }}
.row {{ display:flex; gap:16px; align-items:center; flex-wrap:wrap; }}
.chart-img {{ display:block; width:100%; max-width:100%; height:auto; }}
.small {{ font-size:12px; color:#64748b; }}
.table-wrap {{ width:100%; overflow-x:auto; -webkit-overflow-scrolling:touch; margin:12px 0 28px; }}
table {{ width:100%; border-collapse:collapse; font-size:12px; min-width:520px; }}
th, td {{ border:1px solid #e2e8f0; padding:8px; text-align:left; }}
th {{ background:#f1f5f9; }}
th.sortable-th {{ cursor:pointer; user-select:none; white-space:nowrap; }}
th.sortable-th:hover {{ background:#e2e8f0; }}
.sort-ind {{ display:inline-block; width:0.9em; margin-left:4px; color:#94a3b8; font-size:10px; }}
th.sort-asc .sort-ind::after {{ content:"▲"; color:#4c1d95; }}
th.sort-desc .sort-ind::after {{ content:"▼"; color:#4c1d95; }}
section {{ page-break-inside: avoid; margin-top:28px; }}
.pagebreak {{ page-break-before: always; }}
@media (max-width: 720px) {{
  body {{ margin:12px; }}
  .cards {{ flex-direction:column; gap:12px; margin-bottom:12px; }}
  .card {{ flex:1 1 100%; min-width:100%; width:100%; }}
  .row {{ flex-direction:column; align-items:flex-start; gap:8px; }}
  .row img {{ width:min(100%, 140px) !important; height:auto !important; }}
  table {{ font-size:11px; min-width:640px; }}
}}
@media print {{
  body {{ margin:16px; max-width:none; }}
  .pagebreak {{ page-break-before: always; }}
  .filter-bar {{ display:none; }}
}}
.filter-bar {{ display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin:16px 0 20px; padding:12px 16px; background:#f1f5f9; border:1px solid #e2e8f0; border-radius:10px; }}
.filter-label {{ font-size:14px; font-weight:700; color:#334155; margin-right:4px; }}
.sys-chip {{ min-height:44px; min-width:64px; padding:10px 16px; border:2px solid #cbd5e1; border-radius:999px; background:#fff; color:#334155; font-size:15px; font-weight:700; cursor:pointer; touch-action:manipulation; -webkit-tap-highlight-color:transparent; }}
.sys-chip.active {{ background:#4c1d95; border-color:#4c1d95; color:#fff; }}
.filter-hint {{ font-size:12px; color:#64748b; flex:1 1 100%; margin-top:4px; }}
th.sortable-th {{ min-height:44px; padding:12px 8px; touch-action:manipulation; -webkit-tap-highlight-color:rgba(76,29,149,0.15); }}
tr.table-total td {{ font-weight:700; border-top:2px solid #334155; background:#f8fafc; }}
{showcase_css}</style></head><body>
{title_block}

<div id="system-filter" class="filter-bar" role="group" aria-label="Filter by trading system">
  <span class="filter-label">Show:</span>
{filter_buttons_html}  <span class="filter-hint">Tap to toggle engines (tables, charts, metrics). System is per entry date, not per symbol.</span>
</div>

<section>
<div class="cards cards-metrics">
  <div class="card">
    <h3>Net P&L (realized, closed)</h3>
    <div id="metric-realized" class="metric {'pos' if default_metrics['realized_pos'] else 'neg'}">{default_metrics['realized_fmt']}</div>
    <div id="metric-realized-sub" class="small">{default_metrics['closed_count']} closed round-trips · Unrealized (open est.) {default_metrics['unrealized_fmt']}</div>
  </div>
  <div class="card">
    <h3>Trade win %</h3>
    <div class="row">
      <div id="metric-win-pct" class="metric">{default_metrics['win_pct']}%</div>
      <img id="chart-gauge" class="chart-img" src="data:image/png;base64,{gauge_b64}" width="120" alt="win gauge">
    </div>
    <div id="metric-win-sub" class="small">W {default_metrics['wins']} · BE {default_metrics['be']} · L {default_metrics['losses']}</div>
  </div>
  <div class="card">
    <h3>Profit factor</h3>
    <div class="row">
      <div id="metric-pf" class="metric">{default_metrics['pf']}</div>
      <img id="chart-pf" class="chart-img" src="data:image/png;base64,{pf_b64}" width="120" alt="profit factor">
    </div>
    <div id="metric-pf-sub" class="small">Gross wins {default_metrics['win_sum_fmt']} · Gross losses {default_metrics['loss_sum_fmt']}</div>
  </div>
</div>
<div class="cards cards-charts">
  <div class="card card-full">
    <img id="chart-awl" class="chart-img" src="data:image/png;base64,{awl_b64}" alt="avg win loss">
  </div>
  <div class="card card-full">
    <img id="chart-cum" class="chart-img" src="data:image/png;base64,{cum_b64}" alt="cumulative pnl">
  </div>
</div>
</section>

<section>
<h2>Open Positions</h2>
<p class="small">Open rows come from <code>gettarget_positions.csv</code> (remove a row when sold) plus any other FIFO open lots ≥ {_fmt_money(min_position_value)}. Older buys are recovered from prior Fidelity exports when the newest file is a rolling window. Prices refresh via yfinance when stale (&gt;{STALE_PRICE_MINUTES} min) during 9:30 AM–5:00 PM ET; after 5 PM ET/weekends uses {gettarget_path.name}. Target/stop from getTarget.</p>
<div class="table-wrap">{_html_table(["Symbol","System","Buy Date","Entry","Current","Price As Of (ET)","Gain/Loss %","Gain/Loss $","Target","Stop"], open_rows, ["text","text","date","num","num","date","num","num","num","num"], system_col=1, footer_row=open_footer, table_id="open-positions-table", footer_pnl_cell_id="open-footer-pnl", footer_pnl_col=7) if open_rows else '<p>No open positions at or above the size threshold.</p>'}</div>
</section>

{showcase_section_html}

<section>
<h2>Closed Positions (sold on/after {closed_since:%m/%d/%Y})</h2>
<p class="small">Closed rows come from <code>closed_positions_log.csv</code> (permanent ledger) merged with the current Fidelity export. Once logged, a closed round-trip stays on this list even when it ages out of a rolling Accounts_History window.</p>
<div class="table-wrap">{_html_table(["Symbol","System","Buy Date","Buy Price","Sell Date","Sell Price","Days Held","Gain/Loss %","Gain/Loss $","Shares"], closed_rows, ["text","text","date","num","date","num","num","num","num","num"], system_col=1, footer_row=closed_footer, table_id="closed-positions-table", footer_pnl_cell_id="closed-footer-pnl", footer_pnl_col=8) if closed_rows else '<p>No closed trades in range.</p>'}</div>
</section>

{sell_section_html}

<section class="pagebreak" data-system-section="IND">
<h2>Scanner — IND (deprecated)</h2>
<p class="small">{ind_scan_sub}</p>
<div class="table-wrap">{_html_table(ind_cols, ind_rows, ind_sort if ind_cols else None) if ind_rows else '<p>No IND scanner output available; IND is deprecated.</p>'}</div>
</section>

<section data-system-section="BRT">
<h2>Scanner — BRT</h2>
<p class="small">{brt_scan_sub}</p>
<div class="table-wrap">{_html_table(brt_cols, brt_rows, brt_sort if brt_cols else None) if brt_rows else '<p>No BRT scanner for the latest run.</p>'}</div>
</section>

<section data-system-section="RL">
<h2>Scanner — RL</h2>
<p class="small">{rl_scan_sub}</p>
<div class="table-wrap">{_html_table(rl_cols, rl_rows, rl_sort if rl_cols else None) if rl_rows else '<p>No RL scanner for the latest run.</p>'}</div>
</section>

<section data-system-section="YH">
<h2>Scanner — YH</h2>
<p class="small">{yh_scan_sub}</p>
<div class="table-wrap">{_html_table(yh_cols, yh_rows, yh_sort if yh_cols else None) if yh_rows else '<p>No YH scanner for the latest run.</p>'}</div>
</section>

<section data-system-section="MTS">
<h2>Scanner — MTS</h2>
<p class="small">{mts_scan_sub}</p>
<div class="table-wrap">{_html_table(mts_cols, mts_rows, mts_sort if mts_cols else None) if mts_rows else '<p>No MTS scanner for the latest run.</p>'}</div>
</section>

<section data-system-section="WPBR">
<h2>Scanner — WPBR</h2>
<p class="small">{wpbr_scan_sub}</p>
<div class="table-wrap">{_html_table(wpbr_cols, wpbr_rows, wpbr_sort if wpbr_cols else None) if wpbr_rows else '<p>No WPBR scanner for the latest run.</p>'}</div>
</section>

<section data-system-section="RS">
<h2>Scanner — RS</h2>
<p class="small">{rs_scan_sub}</p>
<div class="table-wrap">{_html_table(rs_cols, rs_rows, rs_sort if rs_cols else None) if rs_rows else '<p>No RS scanner for the latest run.</p>'}</div>
</section>

<section data-system-section="SB">
<h2>{sb_section_title}</h2>
<p class="small">{sb_scan_sub}</p>
<div class="table-wrap">{_html_table(sb_cols, sb_rows, sb_sort if sb_cols else None) if sb_rows else f'<p>{sb_empty_msg}</p>'}</div>
</section>

<section data-system-section="VZ">
<h2>{vz_section_title}</h2>
<p class="small">{vz_scan_sub}</p>
<div class="table-wrap">{_html_table(vz_cols, vz_rows, vz_sort if vz_cols else None) if vz_rows else f'<p>{vz_empty_msg}</p>'}</div>
</section>

{_SORTABLE_TABLE_SCRIPT}
{filter_script}
</body></html>
"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    sell_csv = drive_dir / f"Sell_Report_{datetime.now():%Y%m%d_%H%M%S}.csv"
    write_sell_report_csv(pending_sells, sell_csv)
    sell_latest = drive_dir / "Sell_Report_Latest.csv"
    shutil.copy2(sell_csv, sell_latest)

    return out


def main() -> None:
    p = argparse.ArgumentParser(description=f"Generate {REPORT_TITLE.lower()}")
    p.add_argument(
        "--accounts",
        type=Path,
        default=None,
        help="Full Accounts_History export (default: newest Run Date in Downloads; recent-history sells merged)",
    )
    p.add_argument("--gettarget", type=Path, default=DEFAULT_GETTARGET)
    p.add_argument("--positions", type=Path, default=DEFAULT_POSITIONS)
    p.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_TRADE_REGISTRY,
        help="Canonical trade_system_registry.csv (symbol, purchase_date, system)",
    )
    p.add_argument(
        "--closed-log",
        type=Path,
        default=DEFAULT_CLOSED_LOG,
        help="Append-only permanent closed round-trip ledger (default: closed_positions_log.csv)",
    )
    p.add_argument("--drive", type=Path, default=DRIVE)
    p.add_argument("--closed-since", default="2026-05-25", help="Include sells on/after this date (YYYY-MM-DD)")
    p.add_argument(
        "--min-position-value",
        type=float,
        default=MIN_POSITION_VALUE,
        help="Only include positions with qty × entry price at or above this amount (default 47500)",
    )
    p.add_argument(
        "--backfill-closed-log",
        action="store_true",
        help="Import closed round-trips from Fidelity exports into the permanent log, then exit",
    )
    p.add_argument(
        "--no-merge-all-exports",
        action="store_true",
        help="With --backfill-closed-log, use only --accounts (or newest export) instead of merging all exports",
    )
    p.add_argument("-o", "--output", type=Path, default=None)
    p.add_argument(
        "--no-copy-latest",
        action="store_true",
        help="Do not copy the report to Drive/Investment_Report_Latest.html",
    )
    p.add_argument(
        "--showcase-aapl",
        action="store_true",
        help="Include illustrative AAPL buy-and-hold section (off by default; see INCLUDE_SHOWCASE_AAPL_SECTION)",
    )
    args = p.parse_args()
    since = datetime.strptime(args.closed_since, "%Y-%m-%d").date()
    if args.backfill_closed_log:
        backfill_closed_positions_log(
            accounts_path=args.accounts,
            log_path=args.closed_log,
            positions_path=args.positions,
            registry_path=args.registry,
            gettarget_path=args.gettarget,
            drive_dir=args.drive,
            closed_since=since,
            min_position_value=float(args.min_position_value),
            merge_all_exports=not args.no_merge_all_exports,
        )
        return
    out = build_report(
        accounts_path=args.accounts,
        gettarget_path=args.gettarget,
        positions_path=args.positions,
        registry_path=args.registry,
        closed_log_path=args.closed_log,
        drive_dir=args.drive,
        closed_since=since,
        min_position_value=float(args.min_position_value),
        output_path=args.output,
        include_showcase_aapl=args.showcase_aapl or None,
    )
    print(f"Wrote {out}")
    sell_latest = args.drive / "Sell_Report_Latest.csv"
    if sell_latest.is_file():
        print(f"Wrote {sell_latest}")
    if not args.no_copy_latest:
        latest = args.drive / "Investment_Report_Latest.html"
        latest.parent.mkdir(parents=True, exist_ok=True)
        if out.resolve() != latest.resolve():
            shutil.copy2(out, latest)
            print(f"Copied to {latest}")


if __name__ == "__main__":
    main()
