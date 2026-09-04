#!/usr/bin/env python3
"""Symbol universe for daily trendline charts.

Union (deduped):
  gettarget_positions.csv
  ∪ drive/*_LatestRun_Open.csv
  ∪ investment-report scanners (stamped to latest core run)
  ∪ always-include extras (SPY, APP, + durable extras list)

Scanner source matches ``generate_investment_report._scanner_for_latest_run``:
stamped ``{SYS}_Scanner_{core_ts}.csv`` for BRT/IND/RL/YH/MTS/WPBR/RS (WPBR
also checks legacy PBR_), plus SB Watchlist for the same core stamp (SB has no
Scanner). Does **not** use stale ``*_LatestRun_Scanner.csv`` alone — those can
linger after a DailyRun that wrote no Scanner candidates.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent

_ENTRY_DATE_COLS = ("DATE_OPENED", "DATE OPENED", "ENTRY_DATE", "DATE")
_ENTRY_PRICE_COLS = ("ENTRY_PRICE", "ENTRY PRICE", "BUY_PRICE", "OPEN_PRICE")

# Always chart these even if not in portfolio / LatestRun opens / scanners.
# Durable extras (kept across DailyRun); SPY = market reference, APP + watchlist below.
ALWAYS_INCLUDE_SYMBOLS: tuple[str, ...] = (
    "SPY",
    "APP",
    "GFI",
    "AIZ",
    "COP",
    "PNRG",
    "CVI",
    "REPX",
    "EQNR",
    "CF",
    "UAN",
    "HPQ",
    "PDEX",
)

# Same systems as investment-report scanner sections (excl. VZ watchlist fallback —
# VZ has no Scanner file; watchlist is not "came up on a scanner").
SCANNER_SYSTEMS: tuple[str, ...] = (
    "BRT",
    "IND",
    "RL",
    "YH",
    "MTS",
    "WPBR",
    "RS",
    "SB",
)

_RUN_TS_RE = re.compile(
    r"^(?P<prefix>[A-Za-z]+)_(?:Closed|Open|Watchlist|Summary)_(?P<ts>\d{12})\.csv$",
    re.I,
)
_PIPELINE_TS_RE = re.compile(
    r"^(?P<prefix>[A-Za-z]+)_Pipeline_Timings_(?P<ts>\d{12})\.json$",
    re.I,
)


@dataclass
class SymbolOpenInfo:
    symbol: str
    systems: list[str] = field(default_factory=list)
    purchase_date: str = ""
    entry_price: float | None = None
    price_source: str = ""  # gettarget | engine
    in_portfolio: bool = False
    primary_system: str = ""
    scanner_systems: list[str] = field(default_factory=list)


def _norm_date(s: str) -> str:
    s = str(s or "").strip()
    if len(s) >= 8 and s[:8].isdigit() and "-" not in s[:8]:
        d = s[:8]
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    return s[:10]


def _first_col(row: dict[str, Any], cols: tuple[str, ...]) -> str:
    for c in cols:
        v = row.get(c)
        if v is not None and str(v).strip() not in ("", "nan", "None"):
            return _norm_date(str(v).strip())
    return ""


def _entry_price(row: dict[str, Any]) -> float | None:
    for c in _ENTRY_PRICE_COLS:
        v = row.get(c)
        if v is None or str(v).strip() in ("", "nan", "None"):
            continue
        try:
            return float(str(v).replace(",", "").replace("$", "").replace("%", ""))
        except ValueError:
            continue
    return None


def _system_from_open_filename(name: str) -> str:
    # RL_LatestRun_Open.csv -> RL; PBR_LatestRun_Open.csv -> PBR
    base = name.replace("_LatestRun_Open.csv", "").upper()
    return base


def _aliases(prefix: str) -> list[str]:
    pfx = prefix.upper()
    if pfx == "WPBR":
        return ["WPBR", "PBR"]
    return [pfx]


def latest_core_run_timestamp(prefix: str, drive: Path) -> str | None:
    """Latest yyMMddHHmmss from Closed/Open/Watchlist/Summary/Pipeline (not Scanner alone)."""
    stamps: set[str] = set()
    for alias in _aliases(prefix):
        for path in drive.glob(f"{alias}_*.csv"):
            m = _RUN_TS_RE.match(path.name)
            if m and m.group("prefix").upper() == alias.upper():
                stamps.add(m.group("ts"))
        for path in drive.glob(f"{alias}_Pipeline_Timings_*.json"):
            m = _PIPELINE_TS_RE.match(path.name)
            if m and m.group("prefix").upper() == alias.upper():
                stamps.add(m.group("ts"))
    return max(stamps) if stamps else None


def _symbols_from_csv(path: Path) -> list[str]:
    try:
        import pandas as pd

        df = pd.read_csv(path)
    except Exception:
        return []
    if df.empty:
        return []
    cols = {str(c).upper(): c for c in df.columns}
    sym_col = cols.get("SYMBOL")
    if sym_col is None:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in df[sym_col]:
        sym = str(raw or "").strip().upper()
        if not sym or sym in ("NAN", "NONE", "SYMBOL") or sym in seen:
            continue
        seen.add(sym)
        out.append(sym)
    return out


def resolve_scanner_csv(prefix: str, drive: Path) -> tuple[Path | None, str | None]:
    """Stamped scanner (or SB watchlist) for the latest core run — investment-report parity."""
    pfx = prefix.upper()
    run_ts = latest_core_run_timestamp(pfx, drive)
    if not run_ts:
        return None, None
    candidates: list[Path] = []
    if pfx == "SB":
        candidates.append(drive / f"SB_Watchlist_{run_ts}.csv")
    else:
        candidates.append(drive / f"{pfx}_Scanner_{run_ts}.csv")
        if pfx == "WPBR":
            candidates.append(drive / f"PBR_Scanner_{run_ts}.csv")
    path = next((p for p in candidates if p.is_file()), None)
    return path, run_ts


def load_latest_scanners(drive: Path) -> dict[str, list[str]]:
    """symbol -> sorted scanner system prefixes (investment-report latest-run stamps)."""
    by_sym: dict[str, list[str]] = {}
    for prefix in SCANNER_SYSTEMS:
        path, _run_ts = resolve_scanner_csv(prefix, drive)
        if path is None:
            continue
        for sym in _symbols_from_csv(path):
            by_sym.setdefault(sym, []).append(prefix.upper())
    for sym, systems in by_sym.items():
        by_sym[sym] = sorted(set(systems))
    return by_sym


def load_gettarget_positions(path: Path) -> dict[str, SymbolOpenInfo]:
    out: dict[str, SymbolOpenInfo] = {}
    if not path.is_file():
        return out
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            sym = str(row.get("symbol") or row.get("SYMBOL") or "").strip().upper()
            if not sym:
                continue
            pd_raw = _norm_date(str(row.get("purchase_date") or row.get("PURCHASE_DATE") or ""))
            ep_raw = row.get("entry_price") or row.get("ENTRY_PRICE")
            try:
                ep = float(ep_raw) if ep_raw not in (None, "") else None
            except (TypeError, ValueError):
                ep = None
            sys_name = str(row.get("system") or row.get("SYSTEM") or "").strip().upper()
            info = SymbolOpenInfo(
                symbol=sym,
                systems=[sys_name] if sys_name else [],
                purchase_date=pd_raw,
                entry_price=ep,
                price_source="gettarget",
                in_portfolio=True,
                primary_system=sys_name,
            )
            out[sym] = info
    return out


def load_latest_run_opens(drive: Path) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    """symbol -> [(system, row_dict), ...]"""
    by_sym: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for path in sorted(drive.glob("*_LatestRun_Open.csv")):
        sys_name = _system_from_open_filename(path.name)
        try:
            import pandas as pd

            df = pd.read_csv(path)
        except Exception:
            continue
        if df.empty or "SYMBOL" not in df.columns:
            continue
        seen: set[str] = set()
        for _, row in df.iterrows():
            sym = str(row.get("SYMBOL", "")).strip().upper()
            if not sym or sym in seen:
                continue
            seen.add(sym)
            by_sym.setdefault(sym, []).append((sys_name, row.to_dict()))
    return by_sym


def collect_opens_universe(
    drive: Path | None = None,
    positions_csv: Path | None = None,
    *,
    include_spy: bool = True,
    include_scanners: bool = True,
    extra_symbols: tuple[str, ...] | None = None,
) -> tuple[list[str], dict[str, SymbolOpenInfo]]:
    """Return sorted symbols and per-symbol open metadata.

    Always unions ``ALWAYS_INCLUDE_SYMBOLS`` (SPY, APP, durable watchlist extras)
    unless ``include_spy`` is False (then SPY is dropped; other extras still apply).
    Pass ``extra_symbols`` to override the default extras tuple.

    When ``include_scanners`` is True (default), also unions symbols from the
    latest investment-report scanner artifacts (see ``load_latest_scanners``).
    """
    drive = drive or (_REPO / "drive")
    positions_csv = positions_csv or (_REPO / "gettarget_positions.csv")

    portfolio = load_gettarget_positions(positions_csv)
    engine = load_latest_run_opens(drive)
    scanners = load_latest_scanners(drive) if include_scanners else {}

    symbols: set[str] = set(portfolio) | set(engine) | set(scanners)
    extras = list(ALWAYS_INCLUDE_SYMBOLS if extra_symbols is None else extra_symbols)
    if not include_spy:
        extras = [s for s in extras if s.upper() != "SPY"]
    for s in extras:
        sym = str(s or "").strip().upper()
        if sym:
            symbols.add(sym)

    meta: dict[str, SymbolOpenInfo] = {}
    for sym in symbols:
        info = portfolio.get(sym) or SymbolOpenInfo(symbol=sym)
        info.symbol = sym

        eng_hits = engine.get(sym, [])
        eng_systems = sorted({s for s, _ in eng_hits})
        for s in eng_systems:
            if s not in info.systems:
                info.systems.append(s)
        info.systems = sorted(set(info.systems))

        scan_sys = scanners.get(sym, [])
        info.scanner_systems = list(scan_sys)

        if not info.primary_system and info.systems:
            info.primary_system = info.systems[0]
        if not info.primary_system and info.scanner_systems:
            info.primary_system = info.scanner_systems[0]

        if info.in_portfolio:
            # keep gettarget purchase date/price
            pass
        elif eng_hits:
            # earliest engine open date wins
            best_date = ""
            best_price: float | None = None
            best_sys = ""
            for sys_name, row in eng_hits:
                d = _first_col(row, _ENTRY_DATE_COLS)
                p = _entry_price(row)
                if d and (not best_date or d < best_date):
                    best_date = d
                    best_price = p
                    best_sys = sys_name
                elif not best_date and p is not None:
                    best_price = p
                    best_sys = sys_name
            info.purchase_date = best_date
            info.entry_price = best_price
            info.price_source = "engine"
            if best_sys and not info.primary_system:
                info.primary_system = best_sys

        meta[sym] = info

    return sorted(meta.keys()), meta


def meta_to_jsonable(meta: dict[str, SymbolOpenInfo]) -> dict[str, Any]:
    return {
        sym: {
            "systems": info.systems,
            "purchase_date": info.purchase_date,
            "entry_price": info.entry_price,
            "price_source": info.price_source,
            "in_portfolio": info.in_portfolio,
            "primary_system": info.primary_system,
            "scanner_systems": info.scanner_systems,
        }
        for sym, info in meta.items()
    }
