#!/usr/bin/env python3
"""Generate the historical system and $500k allocation GitHub Pages report.

Live sleeve list comes from tools/dailyrun_system_status.live_wired_systems()
(DailyRun registry), not a frozen tuple. RSI (Relative Strength Index) is the
house pin / LatestRun / rsi_universe.csv book — never RSIN_PaulScore5_IS.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parent
DEFAULT_DRIVE = ROOT / "Drive"
DEFAULT_OUTPUT = ROOT / "docs" / "system_performance.html"
DRIVE_LATEST_NAME = "System_Performance_Latest.html"
ET = ZoneInfo("America/New_York")

# Fallback only if the DailyRun registry helper cannot be imported.
# Keep RSI here so a missing import cannot drop the sleeve again.
_FALLBACK_ACTIVE_SYSTEMS = ("BRT", "RL", "YH", "MTS", "WPBR", "RS", "SB", "VZ", "RSI", "WRL")
LABELS: dict[str, str] = {
    "SPY": "SPY ($500k buy-and-hold)",
    "RS": "RS (Relative Strength vs SPY)",
    "SB": "SB (StockBee)",
    "VZ": "VZ (Volume Zone)",
    "RSI": "RSI (Relative Strength Index)",
    "WRL": "WRL (Weekly Range / Swing)",
    "Live-style (no wires)": "Live-style $250k (no $7,500/mo wires)",
    "Official live-style (with wires)": "Official live-style $250k (includes $7,500/mo wires)",
    "S&P 500 (SPY) $250k": "S&P 500 (SPY) $250k buy-and-hold",
}
COLORS = {
    "BRT": "#2563eb",
    "RL": "#7c3aed",
    "MTS": "#0891b2",
    "WPBR": "#d97706",
    "YH": "#16a34a",
    "RS": "#db2777",
    "SB": "#0d9488",
    "VZ": "#64748b",
    "RSI": "#ea580c",
    "WRL": "#0f766e",
    "Equal capital": "#2563eb",
    "Risk-balanced": "#d97706",
    "Recommended": "#0f766e",
    "SPY": "#111827",
    "Live-style (no wires)": "#0f766e",
    "Official live-style (with wires)": "#d97706",
    "S&P 500 (SPY) $250k": "#111827",
}
_AUTO_COLORS = ("#4f46e5", "#be123c", "#65a30d", "#0284c7", "#a21caf", "#ca8a04")
RL_CASH = 47_500.0
PORTFOLIO_CAPITAL = 500_000.0
SPY_PATH = ROOT / "data" / "newdata" / "data" / "SPY.csv"
# Standalone systems-chart overlay: first trading session on/after this date.
# Allocation-scenario chart stays on the common overlap window (aligned $500k).
SPY_ORIGIN = date(2010, 1, 1)


def _dailyrun_status_mod():
    """Load tools/dailyrun_system_status.py (tools is not a package)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "dailyrun_system_status",
        ROOT / "tools" / "dailyrun_system_status.py",
    )
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def live_performance_systems() -> tuple[str, ...]:
    """Wired DailyRun sleeves in report order.

    Source of truth: tools/dailyrun_system_status.live_wired_systems().
    To put a new system on this page: wire it in DailyRun.bat and
    DAILYRUN_REGISTRY / REPORT_ORDER. Deprecated IND and research-only
    stamps (RSIN, MVCP) stay out until they are wired. WRL is DailyRun-wired
    (official 6-sys mix) — not gold.
    """
    try:
        mod = _dailyrun_status_mod()
        if mod is not None and hasattr(mod, "live_wired_systems"):
            systems = tuple(str(s).upper() for s in mod.live_wired_systems())
            if systems:
                return systems
        if mod is not None and hasattr(mod, "wired_system_ids"):
            systems = tuple(str(s).upper() for s in mod.wired_system_ids())
            if systems:
                return systems
    except Exception:
        pass
    return _FALLBACK_ACTIVE_SYSTEMS


# Snapshot for helpers; build_report always refreshes via live_performance_systems().
ACTIVE_SYSTEMS = live_performance_systems()


def _system_color(label: str) -> str:
    if label in COLORS:
        return COLORS[label]
    idx = sum(ord(c) for c in label) % len(_AUTO_COLORS)
    return _AUTO_COLORS[idx]


def _read_ts_file(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    try:
        ts = path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    except OSError:
        return None
    return ts if re.fullmatch(r"\d{12}", ts) else None


@dataclass(frozen=True)
class Trade:
    system: str
    symbol: str
    opened: date
    closed: date
    entry: float
    exit: float
    days: int
    pnl_pct: float
    pnl: float
    notional: float


def _resolve_drive(path: Path) -> Path:
    if path.resolve().is_dir():
        return path.resolve()
    alt = ROOT / "drive"
    if alt.is_dir():
        return alt.resolve()
    raise FileNotFoundError(f"Drive folder not found: {path}")


def _col(frame: pd.DataFrame, *names: str) -> Optional[str]:
    normalized = {re.sub(r"[^A-Z0-9]", "", str(c).upper()): c for c in frame.columns}
    for name in names:
        found = normalized.get(re.sub(r"[^A-Z0-9]", "", name.upper()))
        if found is not None:
            return str(found)
    return None


def _number(raw: object) -> float:
    text = str(raw or "").strip().replace("$", "").replace("%", "").replace(",", "")
    if not text or text.lower() in {"nan", "none", "null"}:
        return 0.0
    try:
        value = float(text)
        return value if math.isfinite(value) else 0.0
    except ValueError:
        return 0.0


def _date(raw: object) -> Optional[date]:
    text = str(raw or "").strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    compact = re.sub(r"\D", "", text)
    if len(compact) >= 8:
        compact = compact[:8]
        try:
            return date(int(compact[:4]), int(compact[4:6]), int(compact[6:8]))
        except ValueError:
            pass
    try:
        return pd.Timestamp(text).date()
    except Exception:
        return None


def _house_closed(drive: Path, system: str) -> Optional[Path]:
    """House-pin Closed CSV for VZ / RSI so ALL / research stamps never win."""
    sys = system.upper()
    if sys not in {"VZ", "RSI"}:
        return None
    ts = _read_ts_file(drive / f"{sys}_house_last_run_ts.txt")
    if not ts:
        return None
    path = drive / f"{sys}_Closed_{ts}.csv"
    return path if path.is_file() else None


def resolve_closed_path(drive: Path, system: str) -> Optional[Path]:
    """One closed book per sleeve. House pin first for VZ / RSI; no newest-glob."""
    sys = system.upper()
    house = _house_closed(drive, sys)
    if house is not None:
        return house
    latest = drive / f"{sys}_LatestRun_Closed.csv"
    if latest.is_file():
        return latest
    if sys == "WPBR":
        legacy = drive / "PBR_LatestRun_Closed.csv"
        if legacy.is_file():
            return legacy
    if sys == "RL":
        mirrors = sorted(
            drive.glob("BRT_Closed_RL_*.csv"),
            key=lambda p: (p.stat().st_mtime_ns, p.name),
            reverse=True,
        )
        if mirrors:
            return mirrors[0]
    return None


def resolve_sources(
    drive: Path, systems: Optional[Iterable[str]] = None
) -> dict[str, Optional[Path]]:
    """Select one closed file per live system, avoiding PBR/WPBR alias duplication."""
    wanted = tuple(systems) if systems is not None else live_performance_systems()
    return {system: resolve_closed_path(drive, system) for system in wanted}


def load_trades(path: Path, system: str) -> tuple[list[Trade], int]:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, low_memory=False)
    symbol_c = _col(frame, "SYMBOL")
    opened_c = _col(frame, "DATE_OPENED", "DATE OPENED")
    closed_c = _col(frame, "DATE_CLOSED", "DATE CLOSED")
    entry_c = _col(frame, "ENTRY_PRICE", "ENTRY PRICE")
    exit_c = _col(frame, "EXIT_PRICE", "EXIT PRICE", "AVG EXIT PRICE")
    days_c = _col(frame, "DAYS_HELD", "DAYS HELD")
    pct_c = _col(frame, "PNL_PCT", "PNL %")
    pnl_c = _col(frame, "PNL_DOLLARS", "PNL DOLLARS", "TOTAL_PNL")
    required = (symbol_c, opened_c, closed_c, entry_c, exit_c, pct_c)
    if any(c is None for c in required):
        raise ValueError(f"{path.name}: unsupported closed-trade columns")

    loaded: list[Trade] = []
    seen: set[tuple[object, ...]] = set()
    duplicate_count = 0
    for _, row in frame.iterrows():
        opened = _date(row.get(opened_c))
        closed = _date(row.get(closed_c))
        symbol = str(row.get(symbol_c, "")).strip().upper()
        if not symbol or opened is None or closed is None:
            continue
        entry = _number(row.get(entry_c))
        exit_price = _number(row.get(exit_c))
        pct = _number(row.get(pct_c))
        pnl = _number(row.get(pnl_c)) if pnl_c else 0.0
        if not pnl_c:
            pnl = RL_CASH * pct / 100.0 if system == "RL" else 0.0
        days = int(round(_number(row.get(days_c)))) if days_c else max(0, (closed - opened).days)
        if abs(pct) > 1e-9 and abs(pnl) > 1e-9:
            notional = abs(pnl / (pct / 100.0))
        elif system == "RL":
            notional = RL_CASH
        else:
            notional = 0.0
        key = (
            symbol,
            opened,
            closed,
            round(entry, 6),
            round(exit_price, 6),
            round(pct, 6),
            round(pnl, 2),
        )
        if key in seen:
            duplicate_count += 1
            continue
        seen.add(key)
        loaded.append(
            Trade(system, symbol, opened, closed, entry, exit_price, days, pct, pnl, notional)
        )
    return sorted(loaded, key=lambda t: (t.closed, t.opened, t.symbol)), duplicate_count


def _capital_stats(trades: list[Trade]) -> tuple[float, int, float]:
    """Observed peak concurrent positions and estimated gross capital in use."""
    if not trades:
        return 0.0, 0, 0.0
    notionals = [t.notional for t in trades if t.notional > 0]
    fallback = float(pd.Series(notionals).median()) if notionals else 0.0
    events: dict[date, list[tuple[int, float]]] = {}
    for trade in trades:
        amount = trade.notional or fallback
        events.setdefault(trade.opened, []).append((1, amount))
        events.setdefault(trade.closed + timedelta(days=1), []).append((-1, -amount))
    count = 0
    gross = 0.0
    max_count = 0
    max_gross = 0.0
    for day in sorted(events):
        for count_delta, gross_delta in events[day]:
            count += count_delta
            gross += gross_delta
        max_count = max(max_count, count)
        max_gross = max(max_gross, gross)
    # A stable normalized denominator: observed peak modeled gross exposure.
    capital_basis = max_gross if max_gross > 0 else fallback * max_count
    return capital_basis, max_count, max_gross


def _realized_curve(trades: list[Trade], capital_basis: float) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame(columns=["date", "equity", "pnl"])
    pnl_by_day: dict[date, float] = {}
    for trade in trades:
        pnl_by_day[trade.closed] = pnl_by_day.get(trade.closed, 0.0) + trade.pnl
    start = min(t.opened for t in trades)
    rows = [{"date": start, "pnl": 0.0}]
    rows.extend({"date": day, "pnl": pnl} for day, pnl in sorted(pnl_by_day.items()))
    frame = pd.DataFrame(rows)
    frame = frame.groupby("date", as_index=False)["pnl"].sum().sort_values("date")
    frame["equity"] = capital_basis + frame["pnl"].cumsum()
    return frame


def _equity_candidates(drive: Path, system: str) -> list[Path]:
    prefixes = [system]
    if system == "WPBR":
        prefixes.append("PBR")
    candidates: list[Path] = []
    for prefix in prefixes:
        candidates.extend(drive.glob(f"{prefix}_LatestRun_EquityCurve_Regular.csv"))
        candidates.extend(drive.glob(f"{prefix}_EquityCurve_Regular_*.csv"))
        if system in ("SB", "VZ", "WRL", "RSI"):
            # Copy-latest uses {SYS}_LatestRun_EquityCurve.csv; stamp also has EquityCurve_Regular_*.
            candidates.extend(drive.glob(f"{prefix}_LatestRun_EquityCurve.csv"))
            candidates.extend(drive.glob(f"{prefix}_EquityCurve_*.csv"))
    unique = {p.resolve(): p for p in candidates if p.is_file()}
    if system in ("SB", "VZ", "WRL", "RSI"):
        return sorted(
            unique.values(),
            key=lambda p: (
                0 if "Regular" in p.name else 1,
                -p.stat().st_mtime_ns,
                p.name,
            ),
        )
    return sorted(unique.values(), key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)


def _load_equity(path: Path) -> Optional[pd.DataFrame]:
    try:
        frame = pd.read_csv(path, low_memory=False)
    except Exception:
        return None
    date_c = _col(frame, "DATE", "Date", "TRADE_DATE")
    equity_c = _col(frame, "EQUITY", "TOTAL_EQUITY", "ACCOUNT_VALUE", "PORTFOLIO_VALUE")
    if not date_c or not equity_c:
        return None
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(frame[date_c], errors="coerce").dt.date,
            "equity": pd.to_numeric(frame[equity_c], errors="coerce"),
        }
    ).dropna()
    out = out.groupby("date", as_index=False)["equity"].last().sort_values("date")
    if len(out) < 2 or not math.isfinite(float(out["equity"].iloc[0])):
        return None
    return out


def _compatible_equity_curves(
    drive: Path, systems: Iterable[str]
) -> tuple[dict[str, pd.DataFrame], dict[str, Path]]:
    curves: dict[str, pd.DataFrame] = {}
    sources: dict[str, Path] = {}
    for system in systems:
        for candidate in _equity_candidates(drive, system):
            curve = _load_equity(candidate)
            if curve is not None:
                curves[system] = curve
                sources[system] = candidate
                break
    return curves, sources


def _combine_equity(curves: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Sum per-system daily equity changes without forward-looking backfills."""
    all_dates = sorted({d for curve in curves.values() for d in curve["date"]})
    if not all_dates:
        return pd.DataFrame(columns=["date", "equity", "pnl"])
    combined = pd.Series(0.0, index=pd.Index(all_dates, name="date"))
    baseline = 0.0
    for curve in curves.values():
        series = curve.set_index("date")["equity"].astype(float).sort_index()
        baseline += float(series.iloc[0])
        delta = series.diff()
        delta.iloc[0] = 0.0
        combined = combined.add(delta.reindex(combined.index, fill_value=0.0), fill_value=0.0)
    daily_delta = combined
    return pd.DataFrame(
        {
            "date": all_dates,
            "pnl": daily_delta.values,
            "equity": baseline + daily_delta.cumsum().values,
        }
    )


def _max_drawdown(curve: pd.DataFrame) -> tuple[float, float]:
    if curve.empty:
        return 0.0, 0.0
    equity = curve["equity"].astype(float)
    peak = equity.cummax()
    dd = equity - peak
    pct = dd / peak.replace(0, float("nan")) * 100.0
    return float(dd.min()), float(pct.min()) if pct.notna().any() else 0.0


def _losing_streak(trades: list[Trade]) -> int:
    longest = current = 0
    for trade in sorted(trades, key=lambda t: (t.closed, t.opened, t.symbol)):
        if trade.pnl < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _sheet_cash(trades: list[Trade], system: str = "") -> float:
    """Per-trade notional for book Ann ROR (same scale as Closed PNL_DOLLARS)."""
    if system == "RL":
        return RL_CASH
    notionals = [t.notional for t in trades if t.notional > 0]
    if not notionals:
        return RL_CASH if system == "RL" else 0.0
    return float(pd.Series(notionals).median())


def _ann_ror(trades: list[Trade], sheet_cash: float, *, days_per_year: float = 365.0) -> float:
    """Book Ann ROR % — canonical rocket_tbn / Report formula.

    ``((1 + total_pnl / (sheet_cash * n)) ** (days_per_year / avg_days) - 1) * 100``
    """
    if not trades or sheet_cash <= 0:
        return 0.0
    n = len(trades)
    avg_days = sum(t.days for t in trades) / n
    if avg_days <= 0:
        return 0.0
    total_pnl = sum(t.pnl for t in trades)
    base = 1.0 + total_pnl / (sheet_cash * n)
    if base <= 0:
        return 0.0
    return (base ** (days_per_year / avg_days) - 1.0) * 100.0


def metrics(trades: list[Trade], curve: Optional[pd.DataFrame] = None, system: str = "") -> dict[str, float]:
    if not trades:
        return {key: 0.0 for key in (
            "trades", "wins", "losses", "win_rate", "avg_pct", "total_pnl",
            "gross_profit", "gross_loss", "profit_factor", "avg_days", "median_days",
            "p90_days", "expectancy", "expectancy_pct", "annualized", "ann_ror", "ppcd",
            "count_ratio", "dollar_ratio", "max_dd", "max_dd_pct", "losing_streak",
            "capital_basis", "max_concurrent", "max_usage", "sheet_cash",
        )}
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl < 0]
    gross_profit = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))
    total = sum(t.pnl for t in trades)
    basis, max_concurrent, max_usage = _capital_stats(trades)
    actual_curve = curve if curve is not None and not curve.empty else _realized_curve(trades, basis)
    dd, dd_pct = _max_drawdown(actual_curve)
    span = max(1, (max(t.closed for t in trades) - min(t.opened for t in trades)).days)
    total_return = total / basis if basis > 0 else 0.0
    annualized = (
        ((1.0 + total_return) ** (365.25 / span) - 1.0) * 100.0
        if basis > 0 and total_return > -1.0
        else 0.0
    )
    days = pd.Series([t.days for t in trades], dtype=float)
    sys = system or (trades[0].system if trades else "")
    sheet_cash = _sheet_cash(trades, sys)
    return {
        "trades": float(len(trades)),
        "wins": float(len(wins)),
        "losses": float(len(losses)),
        "win_rate": len(wins) / len(trades) * 100.0,
        "avg_pct": sum(t.pnl_pct for t in trades) / len(trades),
        "total_pnl": total,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": gross_profit / gross_loss if gross_loss else float("inf"),
        "avg_days": float(days.mean()),
        "median_days": float(days.median()),
        "p90_days": float(days.quantile(0.9)),
        "expectancy": total / len(trades),
        "expectancy_pct": sum(t.pnl_pct for t in trades) / len(trades),
        "annualized": annualized,
        "ann_ror": _ann_ror(trades, sheet_cash),
        "sheet_cash": sheet_cash,
        "ppcd": total / span,
        "count_ratio": len(wins) / len(losses) if losses else float("inf"),
        "dollar_ratio": gross_profit / gross_loss if gross_loss else float("inf"),
        "max_dd": dd,
        "max_dd_pct": dd_pct,
        "losing_streak": float(_losing_streak(trades)),
        "capital_basis": basis,
        "max_concurrent": float(max_concurrent),
        "max_usage": max_usage,
    }


def yearly_metrics(trades: list[Trade], capital_basis: float) -> list[dict[str, float]]:
    output: list[dict[str, float]] = []
    years = sorted({t.closed.year for t in trades})
    for year in years:
        rows = [t for t in trades if t.closed.year == year]
        curve = _realized_curve(rows, capital_basis)
        item = metrics(rows, curve)
        item["year"] = float(year)
        output.append(item)
    return output


def _common_period(
    trades_by_system: dict[str, list[Trade]],
    systems: Optional[tuple[str, ...]] = None,
) -> tuple[date, date]:
    keys = systems or tuple(trades_by_system)
    start = max(min(t.opened for t in trades_by_system[s]) for s in keys)
    end = min(max(t.closed for t in trades_by_system[s]) for s in keys)
    if start >= end:
        raise ValueError("Active systems do not have an overlapping comparison period")
    return start, end


def _period_trades(trades: list[Trade], start: date, end: date) -> list[Trade]:
    return [t for t in trades if t.opened >= start and t.closed <= end]


def _daily_normalized_pnl(
    trades: list[Trade], capital_basis: float, start: date, end: date
) -> pd.Series:
    index = pd.date_range(start, end, freq="D")
    values = pd.Series(0.0, index=index)
    if capital_basis <= 0:
        return values
    for trade in trades:
        if start <= trade.closed <= end:
            values.loc[pd.Timestamp(trade.closed)] += trade.pnl / capital_basis
    return values


def _load_spy(start: date, end: date) -> tuple[pd.DataFrame, str, Path]:
    if not SPY_PATH.is_file():
        raise FileNotFoundError(f"SPY benchmark missing: {SPY_PATH}")
    raw = pd.read_csv(SPY_PATH, low_memory=False)
    date_c = _col(raw, "DATE")
    adjusted_c = _col(raw, "ADJ CLOSE", "ADJCLOSE")
    close_c = _col(raw, "CLOSE")
    price_c = adjusted_c or close_c
    if not date_c or not price_c:
        raise ValueError(f"{SPY_PATH.name}: Date/Close columns unavailable")
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(raw[date_c], errors="coerce").dt.date,
            "price": pd.to_numeric(raw[price_c], errors="coerce"),
        }
    ).dropna()
    frame = frame[(frame["date"] >= start) & (frame["date"] <= end)]
    frame = frame.groupby("date", as_index=False)["price"].last().sort_values("date")
    if len(frame) < 2:
        raise ValueError(f"SPY has insufficient observations in {start}–{end}")
    initial = float(frame["price"].iloc[0])
    frame["equity"] = PORTFOLIO_CAPITAL * frame["price"] / initial
    frame["pnl"] = frame["equity"].diff().fillna(0.0)
    label = "adjusted-close total return (dividends reinvested)" if adjusted_c else "price-only close return (dividends excluded)"
    return frame[["date", "equity", "pnl"]], label, SPY_PATH


def _bounded_weights(
    raw: dict[str, float],
    floor: float = 0.10,
    cap: float = 0.30,
    systems: Optional[tuple[str, ...]] = None,
) -> dict[str, float]:
    keys = systems or tuple(raw)
    weights = {s: max(0.0, float(raw.get(s, 0.0))) for s in keys}
    total = sum(weights.values())
    weights = {s: (weights[s] / total if total else 1.0 / len(weights)) for s in weights}
    for _ in range(20):
        fixed = {s: min(cap, max(floor, w)) for s, w in weights.items()}
        delta = 1.0 - sum(fixed.values())
        if abs(delta) < 1e-10:
            return fixed
        eligible = [
            s for s, w in fixed.items()
            if (delta > 0 and w < cap - 1e-12) or (delta < 0 and w > floor + 1e-12)
        ]
        if not eligible:
            break
        room = {
            s: (cap - fixed[s] if delta > 0 else fixed[s] - floor)
            for s in eligible
        }
        room_total = sum(room.values())
        for s in eligible:
            fixed[s] += delta * room[s] / room_total
        weights = fixed
    return weights


def _portfolio_curve(
    streams: dict[str, pd.Series],
    weights: dict[str, float],
    systems: Optional[tuple[str, ...]] = None,
) -> pd.DataFrame:
    keys = systems or tuple(weights)
    daily_pnl = sum(
        (streams[s] * (PORTFOLIO_CAPITAL * weights[s]) for s in keys),
        start=pd.Series(0.0, index=next(iter(streams.values())).index),
    )
    return pd.DataFrame(
        {
            "date": daily_pnl.index.date,
            "pnl": daily_pnl.values,
            "equity": PORTFOLIO_CAPITAL + daily_pnl.cumsum().values,
        }
    )


def _portfolio_usage(
    trades_by_system: dict[str, list[Trade]],
    bases: dict[str, float],
    weights: dict[str, float],
    start: date,
    end: date,
    systems: Optional[tuple[str, ...]] = None,
) -> tuple[float, float]:
    events: dict[date, float] = {}
    for system in (systems or tuple(weights)):
        scale = PORTFOLIO_CAPITAL * weights[system] / bases[system] if bases[system] else 0.0
        notionals = [t.notional for t in trades_by_system[system] if t.notional > 0]
        fallback = float(pd.Series(notionals).median()) if notionals else 0.0
        for trade in _period_trades(trades_by_system[system], start, end):
            amount = (trade.notional or fallback) * scale
            events[trade.opened] = events.get(trade.opened, 0.0) + amount
            release = trade.closed + timedelta(days=1)
            events[release] = events.get(release, 0.0) - amount
    usage = peak = 0.0
    for day in sorted(events):
        usage += events[day]
        peak = max(peak, usage)
    return peak, peak / PORTFOLIO_CAPITAL * 100.0


def _curve_stats(curve: pd.DataFrame, start: date, end: date) -> dict[str, float]:
    equity = curve.set_index(pd.to_datetime(curve["date"]))["equity"].astype(float)
    calendar = equity.reindex(pd.date_range(start, end, freq="D")).ffill().bfill()
    total_return = calendar.iloc[-1] / calendar.iloc[0] - 1.0
    years = max((end - start).days / 365.25, 1 / 365.25)
    cagr = (calendar.iloc[-1] / calendar.iloc[0]) ** (1.0 / years) - 1.0
    daily = calendar.pct_change().fillna(0.0)
    vol = daily.std(ddof=1) * math.sqrt(365.25)
    sharpe = daily.mean() / daily.std(ddof=1) * math.sqrt(365.25) if daily.std(ddof=1) > 0 else 0.0
    dd_dollars, dd_pct = _max_drawdown(
        pd.DataFrame({"equity": calendar.values})
    )
    yearly = calendar.groupby(calendar.index.year).agg(["first", "last"])
    yearly_returns = yearly["last"] / yearly["first"] - 1.0
    return {
        "ending_equity": float(calendar.iloc[-1]),
        "pnl": float(calendar.iloc[-1] - PORTFOLIO_CAPITAL),
        "total_return": float(total_return * 100.0),
        "cagr": float(cagr * 100.0),
        "max_dd": dd_dollars,
        "max_dd_pct": dd_pct,
        "volatility": float(vol * 100.0),
        "sharpe": float(sharpe),
        "worst_year": float(yearly_returns.min() * 100.0),
        "worst_year_label": float(yearly_returns.idxmin()),
    }


def _scaled_profit_factor(
    trades_by_system: dict[str, list[Trade]],
    bases: dict[str, float],
    weights: dict[str, float],
    start: date,
    end: date,
    systems: Optional[tuple[str, ...]] = None,
) -> float:
    values: list[float] = []
    for system in (systems or tuple(weights)):
        scale = PORTFOLIO_CAPITAL * weights[system] / bases[system] if bases[system] else 0.0
        values.extend(t.pnl * scale for t in _period_trades(trades_by_system[system], start, end))
    gross_profit = sum(v for v in values if v > 0)
    gross_loss = abs(sum(v for v in values if v < 0))
    return gross_profit / gross_loss if gross_loss else float("inf")


def _money(value: float, *, sign: bool = False) -> str:
    prefix = "+" if sign and value > 0 else ""
    return f"{prefix}${value:,.0f}"


def _pct(value: float, *, sign: bool = False) -> str:
    prefix = "+" if sign and value > 0 else ""
    return f"{prefix}{value:.1f}%"


def _ratio(value: float) -> str:
    return "∞" if math.isinf(value) else f"{value:.2f}"


def _sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _header_row(columns: list[tuple[str, str]]) -> str:
    return "<tr>" + "".join(_sortable_th(label, sort_type) for label, sort_type in columns) + "</tr>"


_SORTABLE_TABLE_SCRIPT = """
<script>
(function () {
  var MONTHS = {
    january:1, february:2, march:3, april:4, may:5, june:6,
    july:7, august:8, september:9, october:10, november:11, december:12
  };
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : 0;
    if (type === "text") return s.toUpperCase();
    if (type === "month") {
      var key = s.toLowerCase().split(/\\s/)[0];
      return MONTHS[key] || 0;
    }
    if (type === "date") {
      var iso = s.match(/(\\d{4})-(\\d{2})-(\\d{2})/);
      if (iso) return parseInt(iso[1] + iso[2] + iso[3], 10);
      var mdy = s.match(/(\\d{1,2})\\/(\\d{1,2})\\/(\\d{4})/);
      if (mdy) return parseInt(mdy[3] + mdy[1].padStart(2, "0") + mdy[2].padStart(2, "0"), 10);
      return 0;
    }
    var n = s.replace(/[$,%+]/g, "").replace(/,/g, "");
    var v = parseFloat(n);
    return Number.isFinite(v) ? v : 0;
  }
  function sortTable(table, col, type, dir) {
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var rows = Array.from(tbody.querySelectorAll("tr"));
    var pinned = rows.filter(function (r) { return r.classList.contains("total-row"); });
    var movable = rows.filter(function (r) { return !r.classList.contains("total-row"); });
    movable.sort(function (a, b) {
      var av = parseSortValue(a.cells[col] && a.cells[col].textContent, type);
      var bv = parseSortValue(b.cells[col] && b.cells[col].textContent, type);
      if (typeof av === "string" || typeof bv === "string") {
        return dir * String(av).localeCompare(String(bv));
      }
      return dir * (av - bv);
    });
    movable.concat(pinned).forEach(function (r) { tbody.appendChild(r); });
  }
  function bindSortHeader(table, th, col) {
    function onActivate(e) {
      if (e.type === "touchend") e.preventDefault();
      var type = th.dataset.sort || "text";
      var dir = th.dataset.dir === "asc" ? -1 : 1;
      table.querySelectorAll("th.sortable-th").forEach(function (h) {
        h.dataset.dir = "";
        h.classList.remove("sort-asc", "sort-desc");
        h.setAttribute("aria-sort", "none");
      });
      th.dataset.dir = dir === 1 ? "asc" : "desc";
      th.classList.add(dir === 1 ? "sort-asc" : "sort-desc");
      th.setAttribute("aria-sort", dir === 1 ? "ascending" : "descending");
      sortTable(table, col, type, dir);
    }
    th.addEventListener("click", onActivate);
    th.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onActivate(e); }
    });
    th.addEventListener("touchend", onActivate, { passive: false });
  }
  document.querySelectorAll("table.sortable").forEach(function (table) {
    table.querySelectorAll("th.sortable-th").forEach(function (th, col) {
      bindSortHeader(table, th, col);
    });
  });
})();
</script>
"""


def _metric_cells(m: dict[str, float]) -> str:
    win_loss = f"{int(m['wins'])}/{int(m['losses'])} ({_ratio(m['count_ratio'])}:1)"
    return "".join(
        (
            f"<td>{int(m['trades']):,}</td>",
            f"<td>{_pct(m['win_rate'])}</td>",
            f"<td>{_pct(m['avg_pct'], sign=True)}</td>",
            f"<td>{win_loss}</td>",
            f"<td>{_ratio(m['dollar_ratio'])}:1</td>",
            f"<td>{m['avg_days']:.1f}</td>",
            f"<td class='{'pos' if m['ann_ror'] >= 0 else 'neg'}'>{_pct(m['ann_ror'], sign=True)}</td>",
            f"<td>{_money(m['max_dd'])}<br><span class='muted'>{_pct(m['max_dd_pct'])}</span></td>",
            f"<td class='{'pos' if m['total_pnl'] >= 0 else 'neg'}'>{_money(m['total_pnl'], sign=True)}</td>",
        )
    )


def _standalone_metric_headers() -> list[tuple[str, str]]:
    return [
        ("Trades", "num"),
        ("Win rate", "num"),
        ("Avg profit", "num"),
        ("W/L count", "text"),
        ("W/L dollars", "num"),
        ("Avg days", "num"),
        ("Ann ROR", "num"),
        ("Drawdown", "num"),
        ("Total profit", "num"),
    ]


def _year_table(rows: list[dict[str, float]]) -> str:
    body = []
    for m in rows:
        body.append(
            "<tr>"
            f"<td>{int(m['year'])}</td><td>{int(m['trades'])}</td>"
            f"<td class='{'pos' if m['total_pnl'] >= 0 else 'neg'}'>{_money(m['total_pnl'], sign=True)}</td>"
            f"<td>{_pct(m['win_rate'])}</td><td>{_ratio(m['profit_factor'])}</td>"
            f"<td>{_money(m['max_dd'])}</td>"
            "</tr>"
        )
    return (
        "<div class='table-wrap'><table class='sortable'><thead>"
        + _header_row(
            [
                ("Year", "num"),
                ("Trades", "num"),
                ("Realized P&L", "num"),
                ("Win rate", "num"),
                ("PF", "num"),
                ("Realized DD", "num"),
            ]
        )
        + "</thead><tbody>" + "".join(body) + "</tbody></table></div>"
    )


def _svg_line(
    curves: dict[str, pd.DataFrame],
    title: str,
    *,
    legend_suffix: Optional[dict[str, str]] = None,
) -> str:
    series: dict[str, list[tuple[date, float]]] = {}
    for label, frame in curves.items():
        if frame.empty:
            continue
        start = float(frame["equity"].iloc[0])
        series[label] = [
            (d, float(v) - start) for d, v in zip(frame["date"], frame["equity"])
        ]
    if not series:
        return "<p class='muted'>No curve data available.</p>"
    all_points = [point for values in series.values() for point in values]
    min_d, max_d = min(p[0] for p in all_points), max(p[0] for p in all_points)
    min_v = min(0.0, min(p[1] for p in all_points))
    max_v = max(0.0, max(p[1] for p in all_points))
    if max_v == min_v:
        max_v += 1.0
    width, height = 1000, 330
    left, right, top, bottom = 78, 24, 24, 45
    plot_w, plot_h = width - left - right, height - top - bottom
    day_span = max(1, (max_d - min_d).days)

    def xy(day: date, value: float) -> tuple[float, float]:
        x = left + ((day - min_d).days / day_span) * plot_w
        y = top + (max_v - value) / (max_v - min_v) * plot_h
        return x, y

    parts = [
        f"<div class='chart-title'>{html.escape(title)}</div>",
        f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='{html.escape(title)}'>",
        "<rect width='100%' height='100%' fill='#fff' rx='10'/>",
    ]
    for idx in range(5):
        value = min_v + (max_v - min_v) * idx / 4
        _, y = xy(min_d, value)
        parts.append(
            f"<line x1='{left}' y1='{y:.1f}' x2='{width-right}' y2='{y:.1f}' stroke='#e2e8f0'/>"
            f"<text x='{left-8}' y='{y+4:.1f}' text-anchor='end' class='axis'>{_money(value)}</text>"
        )
    for label, points in series.items():
        path = " ".join(
            ("M" if idx == 0 else "L") + f"{xy(day, val)[0]:.1f},{xy(day, val)[1]:.1f}"
            for idx, (day, val) in enumerate(points)
        )
        color = _system_color(label)
        parts.append(f"<path d='{path}' fill='none' stroke='{color}' stroke-width='2.5'/>")
    parts.extend(
        (
            f"<text x='{left}' y='{height-14}' class='axis'>{min_d}</text>",
            f"<text x='{width-right}' y='{height-14}' text-anchor='end' class='axis'>{max_d}</text>",
            "</svg><div class='legend'>",
        )
    )
    for label in series:
        suffix = ""
        if legend_suffix and label in legend_suffix:
            suffix = f" · {legend_suffix[label]}"
        parts.append(
            f"<span><i style='background:{_system_color(label)}'></i>"
            f"{html.escape(LABELS.get(label, label))}{html.escape(suffix)}</span>"
        )
    parts.append("</div>")
    return "".join(parts)


def _money_axis(value: float) -> str:
    av = abs(value)
    if av >= 1_000_000:
        return f"${value / 1_000_000:,.1f}M"
    if av >= 10_000:
        return f"${value / 1_000:,.0f}k"
    return _money(value)


def _svg_equity(
    curves: dict[str, pd.DataFrame],
    title: str,
    *,
    legend_suffix: Optional[dict[str, str]] = None,
) -> str:
    """Absolute equity (not P&L-from-zero) for the $250k vs-SPY chart."""
    series: dict[str, list[tuple[date, float]]] = {}
    for label, frame in curves.items():
        if frame is None or getattr(frame, "empty", True):
            continue
        series[label] = [
            (d, float(v)) for d, v in zip(frame["date"], frame["equity"]) if math.isfinite(float(v))
        ]
    if not series:
        return "<p class='muted'>No curve data available.</p>"
    all_points = [point for values in series.values() for point in values]
    min_d, max_d = min(p[0] for p in all_points), max(p[0] for p in all_points)
    min_v = min(0.0, min(p[1] for p in all_points))
    max_v = max(p[1] for p in all_points)
    if max_v == min_v:
        max_v += 1.0
    width, height = 1000, 360
    left, right, top, bottom = 86, 24, 24, 50
    plot_w, plot_h = width - left - right, height - top - bottom
    day_span = max(1, (max_d - min_d).days)

    def xy(day: date, value: float) -> tuple[float, float]:
        x = left + ((day - min_d).days / day_span) * plot_w
        y = top + (max_v - value) / (max_v - min_v) * plot_h
        return x, y

    parts = [
        f"<div class='chart-title'>{html.escape(title)}</div>",
        f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='{html.escape(title)}'>",
        "<rect width='100%' height='100%' fill='#fff' rx='10'/>",
    ]
    for idx in range(5):
        value = min_v + (max_v - min_v) * idx / 4
        _, y = xy(min_d, value)
        parts.append(
            f"<line x1='{left}' y1='{y:.1f}' x2='{width-right}' y2='{y:.1f}' stroke='#e2e8f0'/>"
            f"<text x='{left-8}' y='{y+4:.1f}' text-anchor='end' class='axis'>{_money_axis(value)}</text>"
        )
    year = min_d.year
    while year <= max_d.year:
        tick = date(year, 1, 1)
        if min_d <= tick <= max_d:
            x, _y = xy(tick, min_v)
            parts.append(
                f"<line x1='{x:.1f}' y1='{top}' x2='{x:.1f}' y2='{top+plot_h}' stroke='#f1f5f9'/>"
                f"<text x='{x:.1f}' y='{height-14}' text-anchor='middle' class='axis'>{year}</text>"
            )
        year += 2 if (max_d.year - min_d.year) > 8 else 1
    for label, points in series.items():
        path = " ".join(
            ("M" if idx == 0 else "L") + f"{xy(day, val)[0]:.1f},{xy(day, val)[1]:.1f}"
            for idx, (day, val) in enumerate(points)
        )
        width_n = "3.1" if "no wires" in label.lower() or "no $7" in label.lower() else "2.4"
        parts.append(
            f"<path d='{path}' fill='none' stroke='{_system_color(label)}' stroke-width='{width_n}'/>"
        )
    parts.append("</svg><div class='legend'>")
    for label in series:
        suffix = ""
        if legend_suffix and label in legend_suffix:
            suffix = f" · {legend_suffix[label]}"
        parts.append(
            f"<span><i style='background:{_system_color(label)}'></i>"
            f"{html.escape(LABELS.get(label, label))}{html.escape(suffix)}</span>"
        )
    parts.append("</div>")
    return "".join(parts)


def _system_section(
    system: str, trades: list[Trade], curve: pd.DataFrame, curve_label: str
) -> str:
    m = metrics(trades, curve, system=system)
    rows = yearly_metrics(trades, m["capital_basis"])
    label = LABELS.get(system, system)
    extra = (
        f"<div class='detail-grid'>"
        f"<div><span>Profit factor</span><strong>{_ratio(m['profit_factor'])}</strong></div>"
        f"<div><span>Expectancy</span><strong>{_money(m['expectancy'], sign=True)} / {_pct(m['expectancy_pct'], sign=True)}</strong></div>"
        f"<div><span>Median / P90 hold</span><strong>{m['median_days']:.0f} / {m['p90_days']:.0f} days</strong></div>"
        f"<div><span>Ann ROR</span><strong>{_pct(m['ann_ror'], sign=True)}</strong></div>"
        f"<div><span>PPCD</span><strong>{_money(m['ppcd'], sign=True)}</strong></div>"
        f"<div><span>Longest losing streak</span><strong>{int(m['losing_streak'])}</strong></div>"
        f"<div><span>Max concurrent</span><strong>{int(m['max_concurrent'])}</strong></div>"
        f"<div><span>Peak modeled usage</span><strong>{_money(m['max_usage'])}</strong></div>"
        "</div>"
    )
    return (
        f"<section id='{system.lower()}'><h2>{html.escape(label)}</h2>"
        f"<p class='muted'>Drawdown/equity basis: {html.escape(curve_label)}.</p>"
        "<div class='table-wrap'><table class='summary sortable'><thead>"
        + _header_row(_standalone_metric_headers())
        + f"</thead><tbody><tr>{_metric_cells(m)}</tr></tbody></table></div>"
        + extra
        + _year_table(rows)
        + "</section>"
    )


def _curve_frame(points: list) -> pd.DataFrame:
    rows = []
    for item in points or []:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            d, eq = item[0], item[1]
        else:
            continue
        if isinstance(d, str):
            try:
                d = date.fromisoformat(d[:10])
            except ValueError:
                continue
        try:
            eq_f = float(eq)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(eq_f):
            continue
        rows.append({"date": d, "equity": eq_f})
    if not rows:
        return pd.DataFrame(columns=["date", "equity"])
    return pd.DataFrame(rows).sort_values("date")


def _ann_pct(v: object) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    if abs(x) <= 2.5:
        x *= 100.0
    return f"{x:.2f}%"


def _live_style_performance_section() -> str:
    """Official $250k live-style vs S&P 500 (not house dummy Closed)."""
    try:
        from stock_analysis.live_style_sizing import (
            ACCOUNT_START,
            FREEZE_STAMP,
            NAME_CAP_FRAC,
            official_live_style_callout_html,
            load_freeze_summary,
            ensure_nowire_vs_spy_cache,
            load_wired_vs_spy,
            leftover_5sys_nowire,
            leftover_5sys_wired,
            spy_250k_curve,
        )
    except Exception:
        try:
            from live_style_sizing import (  # type: ignore
                ACCOUNT_START,
                FREEZE_STAMP,
                NAME_CAP_FRAC,
                official_live_style_callout_html,
                load_freeze_summary,
                ensure_nowire_vs_spy_cache,
                load_wired_vs_spy,
                leftover_5sys_nowire,
                leftover_5sys_wired,
                spy_250k_curve,
            )
        except Exception:
            return (
                '<div class="notice recommend" id="live-style">'
                "<strong>Official live-style sizing:</strong> "
                'see <a href="live_style.html">compound growth (live-style)</a>.'
                "</div>"
            )

    summ = load_freeze_summary() or {}
    live = summ.get("live175") or {}
    prior = summ.get("prior10") or {}
    try:
        nowire = ensure_nowire_vs_spy_cache(force=False)
    except Exception as exc:
        print(f"[performance] no-wire vs-SPY cache failed: {exc}", flush=True)
        nowire = {}
    try:
        wired = load_wired_vs_spy()
    except Exception as exc:
        print(f"[performance] wired vs-SPY load failed: {exc}", flush=True)
        wired = {
            "end": live.get("end"),
            "max_dd_pct": live.get("max_dd_pct"),
            "eq_2010": live.get("eq_2010"),
            "eq_2011": live.get("eq_2011"),
            "eq_2012": live.get("eq_2012"),
            "withdrawals": live.get("withdrawals"),
            "asof": None,
            "curve": [],
        }
    spy_end_d = None
    for pack in (nowire, wired):
        asof = pack.get("asof") or pack.get("spy_asof")
        if asof:
            try:
                spy_end_d = date.fromisoformat(str(asof)[:10])
                break
            except ValueError:
                pass
    spy = spy_250k_curve(date(2010, 1, 1), spy_end_d) if spy_end_d else {}
    if not spy.get("end_eq"):
        spy = {
            "end_eq": wired.get("spy_end") or nowire.get("spy_end") or summ.get("spy_tr_end"),
            "ann_ror": wired.get("spy_ann_ror") or nowire.get("spy_ann_ror"),
            "max_dd_pct": wired.get("spy_max_dd_pct") or nowire.get("spy_max_dd_pct"),
            "curve": wired.get("curve") and [],
            "start": "2010-01-04",
            "end": str(spy_end_d or ""),
            "series": "SPY Adj Close total return (dividends reinvested)",
        }

    def _m(v: object) -> str:
        try:
            return f"${float(v):,.0f}"
        except (TypeError, ValueError):
            return "—"

    def _p(v: object) -> str:
        try:
            return f"{float(v):.2f}%"
        except (TypeError, ValueError):
            return "—"

    cap = f"{float(NAME_CAP_FRAC) * 100:.1f}".rstrip("0").rstrip(".")
    nw_end = nowire.get("end")
    spy_end = spy.get("end_eq") or nowire.get("spy_end") or wired.get("spy_end")
    beat = None
    if nw_end is not None and spy_end is not None:
        try:
            beat = float(nw_end) - float(spy_end)
        except (TypeError, ValueError):
            beat = None
    nw_ann = nowire.get("ann_ror")
    spy_ann = spy.get("ann_ror") or nowire.get("spy_ann_ror")
    ann_beat = None
    if nw_ann is not None and spy_ann is not None:
        a = float(nw_ann)
        b = float(spy_ann)
        if abs(a) <= 2.5:
            a *= 100.0
        if abs(b) <= 2.5:
            b *= 100.0
        ann_beat = a - b
    nw_dd = nowire.get("max_dd_pct")
    spy_dd = spy.get("max_dd_pct") or nowire.get("spy_max_dd_pct")
    asof = nowire.get("asof") or wired.get("asof") or spy.get("end") or ""
    spy_start = spy.get("start") or nowire.get("spy_start") or "2010-01-04"
    spy_series = spy.get("series") or "SPY Adj Close total return (dividends reinvested)"

    vs_rows = [
        (
            "Live-style $250k — no $7,500/mo wires (realistic vs S&P 500)",
            nw_end,
            spy_end,
            beat,
            nw_ann,
            spy_ann,
            nw_dd,
            spy_dd,
        ),
        (
            "Official live-style $250k — includes $7,500/mo wires (2026 transfers)",
            wired.get("end") or live.get("end"),
            spy_end,
            (float(wired.get("end") or live.get("end")) - float(spy_end))
            if (wired.get("end") or live.get("end")) is not None and spy_end is not None
            else None,
            wired.get("ann_ror"),
            spy_ann,
            wired.get("max_dd_pct") or live.get("max_dd_pct"),
            spy_dd,
        ),
    ]
    vs_body = ""
    for label, w_end, s_end, dol_beat, w_ann, s_ann, w_dd, s_dd in vs_rows:
        vs_body += (
            f"<tr><td>{html.escape(label)}</td>"
            f"<td>{_m(w_end)}</td><td>{_m(s_end)}</td><td>{_m(dol_beat)}</td>"
            f"<td>{_ann_pct(w_ann)}</td><td>{_ann_pct(s_ann)}</td>"
            f"<td>{_p(w_dd)}</td><td>{_p(s_dd)}</td></tr>"
        )

    try:
        pin5n = leftover_5sys_nowire()
        pin5w = leftover_5sys_wired()
    except Exception:
        pin5n = {
            "eq_2010": 400_050.0,
            "eq_2011": 719_315.0,
            "eq_2012": 938_067.0,
            "end": 64_749_245.0,
            "max_dd_pct": 10.42,
        }
        pin5w = {
            "eq_2010": 284_646.36,
            "eq_2011": 392_517.79,
            "eq_2012": 422_474.98,
            "end": 58_700_020.87,
            "max_dd_pct": 20.59,
        }
    path_rows = [
        (
            "Official 6-sys $250k (no wires) — SB/RSI/VZ/MTS/RL/WRL",
            nowire.get("eq_2010"),
            nowire.get("eq_2011"),
            nowire.get("eq_2012"),
            nw_end,
            nw_dd,
        ),
        (
            "Official 6-sys $250k (with $7,500/mo wires)",
            wired.get("eq_2010") or live.get("eq_2010"),
            wired.get("eq_2011") or live.get("eq_2011"),
            wired.get("eq_2012") or live.get("eq_2012"),
            wired.get("end") or live.get("end"),
            wired.get("max_dd_pct") or live.get("max_dd_pct"),
        ),
        (
            "Leftover 5-sys pin (no wires) — SB/RSI/VZ/MTS/RL only",
            pin5n.get("eq_2010"),
            pin5n.get("eq_2011"),
            pin5n.get("eq_2012"),
            pin5n.get("end"),
            pin5n.get("max_dd_pct"),
        ),
        (
            "Leftover 5-sys pin (with $7,500/mo wires)",
            pin5w.get("eq_2010"),
            pin5w.get("eq_2011"),
            pin5w.get("eq_2012"),
            pin5w.get("end"),
            pin5w.get("max_dd_pct"),
        ),
        (
            "Prior 10% name freeze (history only, with wires)",
            prior.get("eq_2010"),
            prior.get("eq_2011"),
            prior.get("eq_2012"),
            prior.get("end"),
            prior.get("max_dd_pct"),
        ),
        (
            "S&P 500 (SPY) $250k buy-and-hold",
            None,
            None,
            summ.get("spy_2012"),
            spy_end,
            spy_dd,
        ),
    ]
    path_body = ""
    for label, y0, y1, y2, end, dd in path_rows:
        path_body += (
            f"<tr><td>{html.escape(label)}</td>"
            f"<td>{_m(y0)}</td><td>{_m(y1)}</td><td>{_m(y2)}</td>"
            f"<td>{_m(end)}</td><td>{_p(dd)}</td></tr>"
        )

    nw_df = _curve_frame(nowire.get("curve") or [])
    wd_df = _curve_frame(wired.get("curve") or [])
    spy_df = _curve_frame(spy.get("curve") or [])
    chart_curves = {}
    if not nw_df.empty:
        chart_curves["Live-style (no wires)"] = nw_df
    if not wd_df.empty:
        chart_curves["Official live-style (with wires)"] = wd_df
    if not spy_df.empty:
        chart_curves["S&P 500 (SPY) $250k"] = spy_df
    chart = _svg_equity(
        chart_curves,
        f"Live-style $250k vs S&P 500 (SPY) buy-and-hold — {spy_start} through {asof}",
        legend_suffix={
            "Live-style (no wires)": _m(nw_end),
            "Official live-style (with wires)": _m(wired.get("end") or live.get("end")),
            "S&P 500 (SPY) $250k": _m(spy_end),
        },
    ) if chart_curves else "<p class='muted'>Equity curve unavailable.</p>"

    startdates_note = (
        "Start-date robustness (same lids, wires off, other start days) is a local research page: "
        "<code>drive/paul_experiments/live_style_startdates_20260918/compare.html</code> — "
        "do not treat the luckiest start as the headline."
    )
    wd_note = ""
    try:
        wd_amt = float(wired.get("withdrawals") or live.get("withdrawals") or 0.0)
    except (TypeError, ValueError):
        wd_amt = 0.0
    if wd_amt:
        wd_note = (
            f" The official freeze already pulls {_m(wd_amt)} of $7,500/mo wires "
            "(2026 personal transfers, not a sizing lid). "
            "The <strong>realistic vs S&amp;P 500</strong> headline is the no-wire line."
        )

    return f"""
{official_live_style_callout_html()}
<section id="live-style">
<h2>Official live-style $250k vs S&amp;P 500</h2>
<p>Locked freeze <code>{html.escape(FREEZE_STAMP)}</code> — official <strong>six-sleeve</strong> compound wallet
(StockBee, Relative Strength Index, Volume Zone, Magic Touch, Rocket Launcher,
Weekly Range / Swing; Indicators out). DailyRun wire / official mix change — <strong>not gold</strong>.
WRL fill-order sits after the five (RL → MTS → SB → VZ → RSI → WRL).
Risk = min(1% beginning-of-month equity, $50k), shares ≤ 1% ADV20,
notional ≤ {html.escape(cap)}% of current equity. Start {_m(ACCOUNT_START)} on 2010-01-01.
Shares × house Closed <strong>fill prices</strong> (current official lids), not dummy $10k / $47.5k notionals.
The $500k allocation / standalone tables below stay on house dummy Closed for reconcile.{wd_note}</p>
<div class="cards">
<div class="card"><span>Wallet end (no wires)</span><strong>{_m(nw_end)}</strong></div>
<div class="card"><span>S&amp;P 500 (SPY) end</span><strong>{_m(spy_end)}</strong></div>
<div class="card"><span>$ beat vs SPY</span><strong>{_m(beat)}</strong></div>
<div class="card"><span>Ann ROR vs SPY</span><strong>{_ann_pct(nw_ann)} / {_ann_pct(spy_ann)}</strong></div>
<div class="card"><span>Ann ROR beat</span><strong>{(f'{ann_beat:+.2f} pt' if ann_beat is not None else '—')}</strong></div>
<div class="card"><span>Max DD vs SPY</span><strong>{_p(nw_dd)} / {_p(spy_dd)}</strong></div>
</div>
<p class="muted">Same $250k start, same window ({html.escape(str(spy_start))}–{html.escape(str(asof))}).
SPY uses {html.escape(str(spy_series))}. Annualized Rate of Return (Ann ROR) is
(end ÷ start)^(1 ÷ years) − 1. Click column headers to sort.
Working pages:
<a href="live_style.html">compound growth</a> ·
<a href="live_style_monthly.html">wallet monthly</a> ·
<a href="live_style_compare.html">17.5% vs prior 10%</a> ·
<a href="monthly.html#live-style-250k">published monthly $250k section</a> ·
<a href="investment.html">Suggested shares / avg-cost lots</a>.</p>
<h3 id="vs-spy">Realistic outperformance vs S&amp;P 500</h3>
<div class="table-wrap"><table class="sortable"><thead>{_header_row([("Book", "text"), ("Wallet end", "num"), ("SPY end", "num"), ("$ beat", "num"), ("Ann ROR", "num"), ("SPY Ann ROR", "num"), ("Max DD", "num"), ("SPY Max DD", "num")])}</thead><tbody>{vs_body}</tbody></table></div>
<div class="chart" id="vs-spy-chart">{chart}</div>
<p class="muted">{startdates_note}</p>
<h3>Year path</h3>
<div class="table-wrap"><table class="sortable"><thead>{_header_row([("Book", "text"), ("2010", "num"), ("2011", "num"), ("2012", "num"), ("As-of", "num"), ("Max DD", "num")])}</thead><tbody>{path_body}</tbody></table></div>
</section>
"""


def build_report(drive: Path, output: Path = DEFAULT_OUTPUT) -> tuple[Path, dict[str, object]]:
    drive = _resolve_drive(drive)
    wanted = live_performance_systems()
    sources = resolve_sources(drive, wanted)
    trades_by_system: dict[str, list[Trade]] = {}
    duplicates: dict[str, int] = {}
    missing_systems: list[str] = []
    for system in wanted:
        path = sources.get(system)
        if path is None:
            missing_systems.append(system)
            continue
        loaded, dup_n = load_trades(path, system)
        if not loaded:
            missing_systems.append(system)
            continue
        trades_by_system[system] = loaded
        duplicates[system] = dup_n

    systems = tuple(s for s in wanted if s in trades_by_system)
    if len(systems) < 2:
        raise ValueError(
            "Need at least two live systems with closed trades; "
            f"loaded={list(systems)} missing={missing_systems}"
        )
    sources = {s: sources[s] for s in systems}

    common_start, common_end = _common_period(trades_by_system, systems)
    bases = {s: _capital_stats(trades_by_system[s])[0] for s in systems}
    period_trades = {
        s: _period_trades(trades_by_system[s], common_start, common_end)
        for s in systems
    }
    streams = {
        s: _daily_normalized_pnl(period_trades[s], bases[s], common_start, common_end)
        for s in systems
    }

    equal = {s: 1.0 / len(systems) for s in systems}
    sleeve_dd: dict[str, float] = {}
    for system in systems:
        sleeve_curve = pd.DataFrame(
            {"equity": 1.0 + streams[system].cumsum().values}
        )
        sleeve_dd[system] = max(0.01, abs(_max_drawdown(sleeve_curve)[1]) / 100.0)
    weight_floor = min(0.10, 1.0 / max(len(systems), 1))
    risk_balanced = _bounded_weights(
        {s: 1.0 / sleeve_dd[s] for s in systems},
        floor=weight_floor,
        systems=systems,
    )

    monthly = pd.DataFrame(streams).resample("ME").sum()
    correlations = monthly.corr().fillna(0.0)
    avg_corr = {
        s: float(correlations.loc[s, [x for x in systems if x != s]].mean())
        for s in systems
    }
    robustness = {}
    for system in systems:
        m = metrics(period_trades[system])
        robustness[system] = min(1.0, max(0.0, (m["profit_factor"] - 1.0) / 1.5))
    diversification = {s: max(0.25, 1.0 - max(0.0, avg_corr[s])) for s in systems}
    recommended = _bounded_weights(
        {
            s: 0.55 * risk_balanced[s]
            + 0.25 * equal[s] * diversification[s]
            + 0.20 * equal[s] * (0.5 + robustness[s])
            for s in systems
        },
        floor=weight_floor,
        systems=systems,
    )
    scenario_weights = {
        "Equal capital": equal,
        "Risk-balanced": risk_balanced,
        "Recommended": recommended,
    }
    allocation_dollars: dict[str, dict[str, int]] = {}
    for name, weights in scenario_weights.items():
        dollars = {s: int(round(PORTFOLIO_CAPITAL * weights[s])) for s in systems}
        dollars[max(systems, key=lambda s: weights[s])] += (
            int(PORTFOLIO_CAPITAL) - sum(dollars.values())
        )
        allocation_dollars[name] = dollars
    scenario_curves = {
        name: _portfolio_curve(streams, w, systems=systems)
        for name, w in scenario_weights.items()
    }
    spy_curve, spy_label, spy_source = _load_spy(common_start, common_end)
    spy_overlay, _, _ = _load_spy(SPY_ORIGIN, common_end)
    spy_overlay_start = spy_overlay["date"].iloc[0]
    spy_overlay_end = spy_overlay["date"].iloc[-1]
    spy_overlay_stats = _curve_stats(spy_overlay, spy_overlay_start, spy_overlay_end)
    scenario_stats: dict[str, dict[str, float]] = {}
    for name, weights in scenario_weights.items():
        stats = _curve_stats(scenario_curves[name], common_start, common_end)
        stats["profit_factor"] = _scaled_profit_factor(
            trades_by_system, bases, weights, common_start, common_end, systems=systems
        )
        stats["peak_usage"], stats["utilization"] = _portfolio_usage(
            trades_by_system, bases, weights, common_start, common_end, systems=systems
        )
        scenario_stats[name] = stats
    spy_stats = _curve_stats(spy_curve, common_start, common_end)

    available_equity, available_equity_sources = _compatible_equity_curves(drive, systems)
    system_curves: dict[str, pd.DataFrame] = {}
    system_curve_labels: dict[str, str] = {}
    for system in systems:
        if system in available_equity:
            system_curves[system] = available_equity[system]
            system_curve_labels[system] = f"daily mark-to-market regular equity ({available_equity_sources[system].name})"
        else:
            system_curves[system] = _realized_curve(trades_by_system[system], bases[system])
            system_curve_labels[system] = "realized P&L by exit date"

    generated = datetime.now(ET)
    standalone_metrics = {
        system: metrics(trades_by_system[system], system_curves[system], system=system)
        for system in systems
    }
    # Allocation chart: aligned $500k series on the common overlap window.
    # Systems chart: native equity starts; SPY overlay is 2010-origin (not retuned to first trade).
    benchmark_chart = _svg_line(
        {**scenario_curves, "SPY": spy_curve},
        f"$500,000 cumulative P&L · {common_start} to {common_end}",
    )
    systems_chart = _svg_line(
        {**system_curves, "SPY": spy_overlay},
        f"Raw standalone cumulative P&L by system (+ SPY $500k from {spy_overlay_start})",
        legend_suffix={
            system: f"Ann ROR {_pct(standalone_metrics[system]['ann_ror'], sign=True)}"
            for system in systems
        },
    )

    scenario_rows = []
    for name, stats in scenario_stats.items():
        scenario_rows.append(
            f"<tr class='{'combined' if name == 'Recommended' else ''}'><td>{name}</td>"
            f"<td>{_money(stats['ending_equity'])}</td><td>{_pct(stats['total_return'], sign=True)}</td>"
            f"<td>{_pct(stats['cagr'], sign=True)}</td><td>{_money(stats['max_dd'])}<br><span class='muted'>{_pct(stats['max_dd_pct'])}</span></td>"
            f"<td>{_ratio(stats['profit_factor'])}</td><td>{_pct(stats['volatility'])}</td><td>{stats['sharpe']:.2f}</td>"
            f"<td>{int(stats['worst_year_label'])}: {_pct(stats['worst_year'], sign=True)}</td>"
            f"<td>{_money(stats['peak_usage'])}<br><span class='muted'>{_pct(stats['utilization'])}</span></td></tr>"
        )
    scenario_rows.append(
        f"<tr class='total-row'><td>SPY ({common_start}–{common_end})</td><td>{_money(spy_stats['ending_equity'])}</td><td>{_pct(spy_stats['total_return'], sign=True)}</td>"
        f"<td>{_pct(spy_stats['cagr'], sign=True)}</td><td>{_money(spy_stats['max_dd'])}<br><span class='muted'>{_pct(spy_stats['max_dd_pct'])}</span></td>"
        f"<td>n/a</td><td>{_pct(spy_stats['volatility'])}</td><td>{spy_stats['sharpe']:.2f}</td>"
        f"<td>{int(spy_stats['worst_year_label'])}: {_pct(spy_stats['worst_year'], sign=True)}</td><td>100% invested</td></tr>"
    )
    allocation_rows = []
    for system in systems:
        allocation_rows.append(
            "<tr><td>" + system + "</td>"
            + "".join(
                f"<td>{_pct(scenario_weights[name][system] * 100)}<br><span class='muted'>{_money(allocation_dollars[name][system])}</span></td>"
                for name in scenario_weights
            )
            + f"<td>{_money(bases[system])}</td><td>{avg_corr[system]:.2f}</td></tr>"
        )

    summary_rows = []
    for system in systems:
        m = standalone_metrics[system]
        summary_rows.append(
            f"<tr><td><a href='#{system.lower()}'>{system}</a></td>" + _metric_cells(m) + "</tr>"
        )
    source_items = []
    for system in systems:
        duplicate_note = f"; {duplicates[system]} duplicate rows removed" if duplicates[system] else ""
        source_items.append(
            f"<li><strong>{system}:</strong> {html.escape(sources[system].name)}{duplicate_note}; "
            f"capital basis {_money(bases[system])}; curve: {html.escape(system_curve_labels[system])}</li>"
        )
    sections = "".join(
        _system_section(system, trades_by_system[system], system_curves[system], system_curve_labels[system])
        for system in systems
    )
    rec = scenario_stats["Recommended"]
    rsi_house_ts = _read_ts_file(drive / "RSI_house_last_run_ts.txt") if "RSI" in systems else None
    missing_note = (
        f"<div class='notice'><strong>Wired but not on this page yet:</strong> "
        f"{html.escape(', '.join(missing_systems))} (no LatestRun / house Closed book). "
        "They will appear after the first DailyRun copy.</div>"
        if missing_systems
        else ""
    )
    payload = {
        "generated": generated.isoformat(),
        "systems": list(systems),
        "missing_systems": missing_systems,
        "rsi_house_ts": rsi_house_ts,
        "common_period": {"start": common_start, "end": common_end},
        "capital_bases": bases,
        "weights": scenario_weights,
        "allocation_dollars": allocation_dollars,
        "scenario_metrics": scenario_stats,
        "spy_metrics": spy_stats,
        "spy_overlay_metrics": spy_overlay_stats,
        "spy_overlay_period": {"start": spy_overlay_start, "end": spy_overlay_end},
        "spy_basis": spy_label,
        "sources": {k: str(v) for k, v in sources.items()},
    }
    payload_json = json.dumps(payload, allow_nan=False, default=str).replace("</", "<\\/")
    report = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Historical System Performance</title>
<style>
:root{{--ink:#0f172a;--muted:#64748b;--line:#e2e8f0;--panel:#fff;--bg:#f8fafc;--accent:#0f766e}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 "Segoe UI",Arial,sans-serif}}
.shell{{max-width:none;margin:auto;padding:28px}} header{{background:linear-gradient(130deg,#0f172a,#134e4a);color:#fff;padding:28px;border-radius:16px}}
h1{{margin:0 0 5px;font-size:30px}} h2{{margin:0 0 16px;font-size:22px}} h3{{margin:16px 0 8px}} .sub,.muted{{color:var(--muted);font-size:12px}}
header .sub{{color:#cbd5e1}} nav{{margin-top:18px;display:flex;gap:9px;flex-wrap:wrap}} nav a{{color:#fff;text-decoration:none;border:1px solid #ffffff55;border-radius:999px;padding:6px 11px}}
.cards{{display:grid;grid-template-columns:repeat(6,minmax(145px,1fr));gap:12px;margin:18px 0}} .card,section,.chart{{background:var(--panel);border:1px solid var(--line);border-radius:14px;box-shadow:0 3px 14px #0f172a0a}}
.card{{padding:16px}} .card span,.detail-grid span{{display:block;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}} .card strong{{display:block;font-size:23px;margin-top:4px}}
section{{padding:22px;margin:18px 0}} .chart{{padding:16px;margin:18px 0}} .chart-title{{font-size:16px;font-weight:700;margin:0 0 8px}} svg{{display:block;width:100%;height:auto}} .axis{{font-size:11px;fill:#64748b}}
.legend{{display:flex;flex-wrap:wrap;gap:14px;margin:7px 8px 0}} .legend span{{color:var(--muted)}} .legend i{{display:inline-block;width:18px;height:3px;margin:0 5px 3px 0}}
.table-wrap{{overflow:visible;width:100%}} table{{width:100%;border-collapse:collapse;white-space:nowrap}} th,td{{padding:9px 10px;border-bottom:1px solid var(--line);text-align:right}} th{{background:#f1f5f9;color:#475569;font-size:11px;text-transform:uppercase}} th:first-child,td:first-child{{text-align:left}}
th.sortable-th{{cursor:pointer;user-select:none;white-space:nowrap}} th.sortable-th:hover{{background:#e2e8f0}} .sort-ind{{display:inline-block;width:0.9em;margin-left:4px;color:#94a3b8;font-size:10px}} th.sort-asc .sort-ind::after{{content:"▲";color:#334155}} th.sort-desc .sort-ind::after{{content:"▼";color:#334155}}
.combined{{font-weight:700;background:#ecfdf5}} .pos{{color:#15803d;font-weight:650}} .neg{{color:#b91c1c;font-weight:650}} .detail-grid{{display:grid;grid-template-columns:repeat(4,minmax(160px,1fr));gap:10px;margin:16px 0}} .detail-grid div{{background:#f8fafc;border:1px solid var(--line);padding:10px;border-radius:9px}}
.notice{{padding:13px 15px;border-radius:10px;margin:16px 0;background:#ecfeff;border:1px solid #a5f3fc}} .recommend{{background:#ecfdf5;border-color:#86efac}} .ask{{background:#fff7ed;border-color:#fdba74}} details{{margin-top:12px}} footer{{color:var(--muted);font-size:12px;padding:20px 4px 36px}} a{{color:#0f766e}}
@media(max-width:900px){{.cards{{grid-template-columns:repeat(2,1fr)}}.detail-grid{{grid-template-columns:repeat(2,1fr)}}.shell{{padding:12px}}}}
</style></head><body><div class="shell">
<header><h1>Historical System Performance</h1><div class="sub">$500,000 allocation model · generated {generated.strftime("%Y-%m-%d %H:%M %Z")}</div>
<nav><a href="index.html">Scanner</a><a href="investment.html">Investment</a><a href="convergence.html">Convergence</a><a href="monthly.html">Monthly</a><a href="live_style.html">Live-style</a><a href="#live-style">Live-style $250k</a><a href="#vs-spy">vs S&amp;P 500</a><a href="#allocation">Allocation</a><a href="#systems">Systems</a><a href="#method">Methodology</a></nav></header>
{_live_style_performance_section()}
{missing_note}
<div class="notice"><strong>Common comparison period:</strong> {common_start} through {common_end}. Allocation sleeves and the SPY line on the $500k chart below use exactly these endpoints (aligned series). The standalone systems chart overlays SPY from {spy_overlay_start} (first session on/after {SPY_ORIGIN}). SPY uses {html.escape(spy_label)}. Live sleeves on this page: {', '.join(systems)}.</div>
<div class="cards">
<div class="card"><span>Portfolio</span><strong>{_money(PORTFOLIO_CAPITAL)}</strong></div><div class="card"><span>Recommended ending equity</span><strong>{_money(rec['ending_equity'])}</strong></div>
<div class="card"><span>Total return</span><strong>{_pct(rec['total_return'], sign=True)}</strong></div><div class="card"><span>CAGR</span><strong>{_pct(rec['cagr'], sign=True)}</strong></div>
<div class="card"><span>Max drawdown</span><strong>{_pct(rec['max_dd_pct'])}</strong></div><div class="card"><span>SPY return</span><strong>{_pct(spy_stats['total_return'], sign=True)}</strong></div>
</div>
<section id="allocation"><h2>Allocation scenarios</h2>
<p>These are investable-scale models: each system's complete historical return stream is scaled from its observed peak concurrent gross-notional basis to its assigned sleeve. The old sum of full standalone accounts is not used as a portfolio result. Compound Annual Growth Rate (CAGR) and Profit Factor (PF) are in the table. Click column headers to sort.</p>
<div class="table-wrap"><table class="sortable"><thead>{_header_row([("Scenario", "text"), ("Ending equity", "num"), ("Total return", "num"), ("CAGR", "num"), ("Max DD", "num"), ("PF", "num"), ("Ann. vol", "num"), ("Sharpe", "num"), ("Worst year", "text"), ("Peak usage", "num")])}</thead><tbody>{''.join(scenario_rows)}</tbody></table></div>
<div class="chart">{benchmark_chart}</div>
<h3>Dollar allocations</h3><p class="muted">Click column headers to sort.</p><div class="table-wrap"><table class="sortable"><thead>{_header_row([("System", "text"), ("Equal capital", "num"), ("Risk-balanced", "num"), ("Recommended", "num"), ("Standalone basis", "num"), ("Avg monthly corr.", "num")])}</thead><tbody>{''.join(allocation_rows)}</tbody></table></div>
<div class="notice recommend"><strong>Recommendation:</strong> {', '.join(f"{s} {_pct(recommended[s] * 100)} ({_money(allocation_dollars['Recommended'][s])})" for s in systems)}. Rounded dollar targets sum to exactly $500,000. Start from inverse-drawdown risk balance, then apply modest diversification and profit-factor robustness adjustments. Sleeves stay within {_pct(weight_floor * 100)}–30%. Review annually and rebalance to target when a sleeve drifts by more than 5 percentage points.</div>
<p class="muted">This recommendation is a backtest allocation model, not guaranteed performance or personalized financial advice.</p></section>
<section id="systems"><h2>Raw standalone system results</h2><p>These retain each engine's native historical sizing and full available period. They are diagnostic standalone results—not amounts simultaneously investable with $500,000. <strong>Ann ROR</strong> (Annualized Rate of Return) uses the canonical book formula from Report / EquityMeta: ((1 + Total PnL ÷ (sheet cash × trades)) ^ (365 ÷ avg days held) − 1) × 100. Click column headers to sort.</p>
<div class="table-wrap"><table class="sortable"><thead>{_header_row([("System", "text")] + _standalone_metric_headers())}</thead><tbody>{''.join(summary_rows)}</tbody></table></div></section>
<div class="chart">{systems_chart}</div>
<div class="notice"><strong>SPY on this chart:</strong> buy-and-hold equity starting at {_money(PORTFOLIO_CAPITAL)} on {spy_overlay_start} (requested origin {SPY_ORIGIN}; first available session), through {spy_overlay_end}, using {html.escape(spy_label)}. System lines keep their native capital bases (~{_money(min(bases.values()))}–{_money(max(bases.values()))}) and native start dates; they are not truncated to 2010. For like-for-like $500k scaling over {common_start}–{common_end}, see the allocation chart above.</div>
{sections}
<section id="method"><h2>Methodology &amp; caveats</h2><ul>
<li><strong>Live-style $250k vs S&amp;P 500:</strong> the top section is the official <strong>6-sleeve</strong> compound wallet (SB / RSI / VZ / MTS / RL / WRL; stamp <code>risk_1pct_50k_adv_17name_20260917</code> lids, name cap 17.5%) using official shares × house Closed fill prices. DailyRun wire / official mix change — not gold. Parent 5-vs-6 was HOLD on quality (6-sys more $, Max DD 10.4%→17.2%, WR/Avg/PF softened). The old 5-sys pin is leftover in the year-path table. The <em>realistic vs S&amp;P 500 (SPY)</em> headline turns $7,500/mo wires off (those are 2026 personal transfers). Allocation / standalone Closed rows below stay on house dummy notionals for reconcile.</li>
<li><strong>Live systems:</strong> sleeves come from <code>tools/dailyrun_system_status.live_wired_systems()</code> (DailyRun registry). Add a new system there and in DailyRun.bat — this page picks it up on the next generate. Deprecated IND and research-only stamps (including RSIN_PaulScore5_IS) stay off until they are DailyRun-wired. Weekly Range / Swing (WRL) is DailyRun-wired on the 29-name house universe.</li>
<li><strong>RSI (Relative Strength Index):</strong> house book only — <code>RSI_house_last_run_ts.txt</code>{f" ({rsi_house_ts})" if rsi_house_ts else ""} / <code>RSI_LatestRun_Closed.csv</code> / <code>drive/universes/rsi_universe.csv</code> (149 names). Not RS (Relative Strength vs SPY). Not a research ALL-universe replay.</li>
<li><strong>Capital basis:</strong> position notional is inferred as |dollar P&amp;L ÷ percentage P&amp;L|; RL uses its native $47,500 sizing. Each denominator is that system's observed peak overlapping gross notional. Scaling allocation ÷ basis preserves trade economics and proportionally reduces all simultaneous positions when a sleeve is smaller than its standalone basis.</li>
<li><strong>Common period:</strong> begins at the latest first-open date and ends at the earliest last-close date among {', '.join(systems)}. Only trades opened and closed inside it are used. The $500k allocation chart is a single aligned series: sleeves and SPY on that chart share {common_start}–{common_end}.</li>
<li><strong>Benchmark:</strong> local <code>{html.escape(str(spy_source.relative_to(ROOT)))}</code>, using {html.escape(spy_label)}. SPY equity is normalized to the same $500,000. On the standalone systems chart, SPY starts at the first trading session on/after {SPY_ORIGIN} (actual {spy_overlay_start}) and is not shifted to a system's first trade. System equity curves keep their native starts even when they begin before or after 2010.</li>
<li><strong>Risk-balanced:</strong> inverse realized drawdown by sleeve in the common period, constrained to 10% minimum and 30% maximum. <strong>Recommended:</strong> 55% risk-balance anchor, 25% low-correlation diversification, and 20% capped PF robustness; the same guardrails apply.</li>
<li><strong>Drawdown/volatility limitation:</strong> portfolio P&amp;L is recorded on trade exit dates because compatible mark-to-market curves are not available for every sleeve over the common period. This can materially understate intratrade drawdown and makes volatility/Sharpe lumpy; Sharpe is descriptive, zero risk-free rate, and not a forecast.</li>
<li><strong>Concurrency:</strong> peak usage sums scaled inferred notionals across overlapping positions. No borrowing is assumed; proportional sleeve scaling is the transparent capacity rule. Real execution, liquidity, taxes, fees, slippage, and cross-system duplicate-symbol constraints are not modeled.</li>
<li><strong>PF:</strong> scenario PF is gross scaled winning P&amp;L divided by gross scaled losing P&amp;L and is included only as a trade-level descriptive statistic. Annual rebalancing is an operating convention, not dynamically simulated in the curve.</li>
</ul><details><summary>Exact sources and capital bases</summary><ul>{''.join(source_items)}<li><strong>SPY:</strong> {html.escape(str(spy_source))}</li></ul></details></section>
<footer>Generated from local LatestRun backtest exports. Historical backtests are not guarantees of future performance.</footer>
<script type="application/json" id="report-data">{payload_json}</script>
{_SORTABLE_TABLE_SCRIPT}
</div></body></html>"""
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    drive_copy = (drive / DRIVE_LATEST_NAME).resolve()
    if drive_copy != output:
        drive_copy.write_text(report, encoding="utf-8")
        payload["drive_html"] = str(drive_copy)
    return output, payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drive", type=Path, default=DEFAULT_DRIVE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output, payload = build_report(args.drive, args.output)
    recommended = payload["scenario_metrics"]["Recommended"]
    print(f"[performance] Wrote {output}")
    if payload.get("drive_html"):
        print(f"[performance] Drive copy {payload['drive_html']}")
    print(f"[performance] Systems: {', '.join(payload['systems'])}")
    if payload.get("rsi_house_ts"):
        print(f"[performance] RSI house stamp {payload['rsi_house_ts']}")
    if payload.get("missing_systems"):
        print(f"[performance] Missing wired: {', '.join(payload['missing_systems'])}")
    print(
        "[performance] Recommended $500k: "
        f"${recommended['ending_equity']:,.2f} ending equity, "
        f"{recommended['total_return']:.2f}% return, "
        f"{recommended['max_dd_pct']:.2f}% max DD"
    )
    print(
        f"[performance] Common period: {payload['common_period']['start']} "
        f"to {payload['common_period']['end']}"
    )
    print("[performance] Live-style $250k vs SPY is the top section (official shares x fill prices)")
    overlay = payload["spy_overlay_period"]
    print(f"[performance] SPY overlay: {overlay['start']} to {overlay['end']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
