#!/usr/bin/env python3
"""Generate the historical system and $500k allocation GitHub Pages report."""
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
ET = ZoneInfo("America/New_York")

ACTIVE_SYSTEMS = ("BRT", "RL", "MTS", "WPBR", "YH")
LABELS: dict[str, str] = {
    "SPY": "SPY ($500k buy-and-hold)",
}
COLORS = {
    "BRT": "#2563eb",
    "RL": "#7c3aed",
    "MTS": "#0891b2",
    "WPBR": "#d97706",
    "YH": "#16a34a",
    "Equal capital": "#2563eb",
    "Risk-balanced": "#d97706",
    "Recommended": "#0f766e",
    "SPY": "#111827",
}
RL_CASH = 47_500.0
PORTFOLIO_CAPITAL = 500_000.0
SPY_PATH = ROOT / "data" / "newdata" / "data" / "SPY.csv"


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


def resolve_sources(drive: Path) -> dict[str, Optional[Path]]:
    """Select one closed file per logical system, avoiding PBR/WPBR alias duplication."""
    out: dict[str, Optional[Path]] = {}
    for system in ("BRT", "MTS", "YH"):
        path = drive / f"{system}_LatestRun_Closed.csv"
        out[system] = path if path.is_file() else None

    wpbr = drive / "WPBR_LatestRun_Closed.csv"
    legacy = drive / "PBR_LatestRun_Closed.csv"
    out["WPBR"] = wpbr if wpbr.is_file() else legacy if legacy.is_file() else None

    # Prefer the canonical LatestRun copy.  Fall back to the newest RL mirror.
    rl = drive / "RL_LatestRun_Closed.csv"
    if rl.is_file():
        out["RL"] = rl
    else:
        mirrors = sorted(
            drive.glob("BRT_Closed_RL_*.csv"),
            key=lambda p: (p.stat().st_mtime_ns, p.name),
            reverse=True,
        )
        out["RL"] = mirrors[0] if mirrors else None
    return out


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
    unique = {p.resolve(): p for p in candidates if p.is_file()}
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


def metrics(trades: list[Trade], curve: Optional[pd.DataFrame] = None) -> dict[str, float]:
    if not trades:
        return {key: 0.0 for key in (
            "trades", "wins", "losses", "win_rate", "avg_pct", "total_pnl",
            "gross_profit", "gross_loss", "profit_factor", "avg_days", "median_days",
            "p90_days", "expectancy", "expectancy_pct", "annualized", "ppcd",
            "count_ratio", "dollar_ratio", "max_dd", "max_dd_pct", "losing_streak",
            "capital_basis", "max_concurrent", "max_usage",
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


def _common_period(trades_by_system: dict[str, list[Trade]]) -> tuple[date, date]:
    start = max(min(t.opened for t in trades_by_system[s]) for s in ACTIVE_SYSTEMS)
    end = min(max(t.closed for t in trades_by_system[s]) for s in ACTIVE_SYSTEMS)
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
        raise ValueError("SPY has insufficient observations in the common period")
    initial = float(frame["price"].iloc[0])
    frame["equity"] = PORTFOLIO_CAPITAL * frame["price"] / initial
    frame["pnl"] = frame["equity"].diff().fillna(0.0)
    label = "adjusted-close total return (dividends reinvested)" if adjusted_c else "price-only close return (dividends excluded)"
    return frame[["date", "equity", "pnl"]], label, SPY_PATH


def _bounded_weights(raw: dict[str, float], floor: float = 0.10, cap: float = 0.30) -> dict[str, float]:
    weights = {s: max(0.0, float(raw.get(s, 0.0))) for s in ACTIVE_SYSTEMS}
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
    streams: dict[str, pd.Series], weights: dict[str, float]
) -> pd.DataFrame:
    daily_pnl = sum(
        (streams[s] * (PORTFOLIO_CAPITAL * weights[s]) for s in ACTIVE_SYSTEMS),
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
) -> tuple[float, float]:
    events: dict[date, float] = {}
    for system in ACTIVE_SYSTEMS:
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
) -> float:
    values: list[float] = []
    for system in ACTIVE_SYSTEMS:
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
            f"<td>{_money(m['max_dd'])}<br><span class='muted'>{_pct(m['max_dd_pct'])}</span></td>",
            f"<td class='{'pos' if m['total_pnl'] >= 0 else 'neg'}'>{_money(m['total_pnl'], sign=True)}</td>",
        )
    )


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
        "<div class='table-wrap'><table><thead><tr><th>Year</th><th>Trades</th>"
        "<th>Realized P&amp;L</th><th>Win rate</th><th>PF</th><th>Realized DD</th>"
        "</tr></thead><tbody>" + "".join(body) + "</tbody></table></div>"
    )


def _svg_line(curves: dict[str, pd.DataFrame], title: str) -> str:
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
        color = COLORS.get(label, "#334155")
        parts.append(f"<path d='{path}' fill='none' stroke='{color}' stroke-width='2.5'/>")
    parts.extend(
        (
            f"<text x='{left}' y='{height-14}' class='axis'>{min_d}</text>",
            f"<text x='{width-right}' y='{height-14}' text-anchor='end' class='axis'>{max_d}</text>",
            "</svg><div class='legend'>",
        )
    )
    for label in series:
        parts.append(
            f"<span><i style='background:{COLORS.get(label, '#334155')}'></i>{html.escape(LABELS.get(label, label))}</span>"
        )
    parts.append("</div>")
    return "".join(parts)


def _system_section(
    system: str, trades: list[Trade], curve: pd.DataFrame, curve_label: str
) -> str:
    m = metrics(trades, curve)
    rows = yearly_metrics(trades, m["capital_basis"])
    label = LABELS.get(system, system)
    extra = (
        f"<div class='detail-grid'>"
        f"<div><span>Profit factor</span><strong>{_ratio(m['profit_factor'])}</strong></div>"
        f"<div><span>Expectancy</span><strong>{_money(m['expectancy'], sign=True)} / {_pct(m['expectancy_pct'], sign=True)}</strong></div>"
        f"<div><span>Median / P90 hold</span><strong>{m['median_days']:.0f} / {m['p90_days']:.0f} days</strong></div>"
        f"<div><span>Annualized return</span><strong>{_pct(m['annualized'], sign=True)}</strong></div>"
        f"<div><span>PPCD</span><strong>{_money(m['ppcd'], sign=True)}</strong></div>"
        f"<div><span>Longest losing streak</span><strong>{int(m['losing_streak'])}</strong></div>"
        f"<div><span>Max concurrent</span><strong>{int(m['max_concurrent'])}</strong></div>"
        f"<div><span>Peak modeled usage</span><strong>{_money(m['max_usage'])}</strong></div>"
        "</div>"
    )
    return (
        f"<section id='{system.lower()}'><h2>{html.escape(label)}</h2>"
        f"<p class='muted'>Drawdown/equity basis: {html.escape(curve_label)}.</p>"
        "<div class='table-wrap'><table class='summary'><thead><tr>"
        "<th>Trades</th><th>Win rate</th><th>Avg profit</th><th>W/L count</th>"
        "<th>W/L dollars</th><th>Avg days</th><th>Drawdown</th><th>Total profit</th>"
        f"</tr></thead><tbody><tr>{_metric_cells(m)}</tr></tbody></table></div>"
        + extra
        + _year_table(rows)
        + "</section>"
    )


def build_report(drive: Path, output: Path = DEFAULT_OUTPUT) -> tuple[Path, dict[str, object]]:
    drive = _resolve_drive(drive)
    sources = resolve_sources(drive)
    trades_by_system: dict[str, list[Trade]] = {}
    duplicates: dict[str, int] = {}
    for system in ACTIVE_SYSTEMS:
        path = sources.get(system)
        if path is None:
            raise FileNotFoundError(f"{system} closed data missing")
        trades_by_system[system], duplicates[system] = load_trades(path, system)
        if not trades_by_system[system]:
            raise ValueError(f"{system} has no usable closed trades")

    common_start, common_end = _common_period(trades_by_system)
    bases = {s: _capital_stats(trades_by_system[s])[0] for s in ACTIVE_SYSTEMS}
    period_trades = {
        s: _period_trades(trades_by_system[s], common_start, common_end)
        for s in ACTIVE_SYSTEMS
    }
    streams = {
        s: _daily_normalized_pnl(period_trades[s], bases[s], common_start, common_end)
        for s in ACTIVE_SYSTEMS
    }

    equal = {s: 0.20 for s in ACTIVE_SYSTEMS}
    sleeve_dd: dict[str, float] = {}
    for system in ACTIVE_SYSTEMS:
        sleeve_curve = pd.DataFrame(
            {"equity": 1.0 + streams[system].cumsum().values}
        )
        sleeve_dd[system] = max(0.01, abs(_max_drawdown(sleeve_curve)[1]) / 100.0)
    risk_balanced = _bounded_weights({s: 1.0 / sleeve_dd[s] for s in ACTIVE_SYSTEMS})

    monthly = pd.DataFrame(streams).resample("ME").sum()
    correlations = monthly.corr().fillna(0.0)
    avg_corr = {
        s: float(correlations.loc[s, [x for x in ACTIVE_SYSTEMS if x != s]].mean())
        for s in ACTIVE_SYSTEMS
    }
    robustness = {}
    for system in ACTIVE_SYSTEMS:
        m = metrics(period_trades[system])
        robustness[system] = min(1.0, max(0.0, (m["profit_factor"] - 1.0) / 1.5))
    diversification = {s: max(0.25, 1.0 - max(0.0, avg_corr[s])) for s in ACTIVE_SYSTEMS}
    recommended = _bounded_weights(
        {
            s: 0.55 * risk_balanced[s]
            + 0.25 * equal[s] * diversification[s]
            + 0.20 * equal[s] * (0.5 + robustness[s])
            for s in ACTIVE_SYSTEMS
        }
    )
    scenario_weights = {
        "Equal capital": equal,
        "Risk-balanced": risk_balanced,
        "Recommended": recommended,
    }
    allocation_dollars: dict[str, dict[str, int]] = {}
    for name, weights in scenario_weights.items():
        dollars = {s: int(round(PORTFOLIO_CAPITAL * weights[s])) for s in ACTIVE_SYSTEMS}
        dollars[max(ACTIVE_SYSTEMS, key=lambda s: weights[s])] += (
            int(PORTFOLIO_CAPITAL) - sum(dollars.values())
        )
        allocation_dollars[name] = dollars
    scenario_curves = {name: _portfolio_curve(streams, w) for name, w in scenario_weights.items()}
    spy_curve, spy_label, spy_source = _load_spy(common_start, common_end)
    scenario_stats: dict[str, dict[str, float]] = {}
    for name, weights in scenario_weights.items():
        stats = _curve_stats(scenario_curves[name], common_start, common_end)
        stats["profit_factor"] = _scaled_profit_factor(
            trades_by_system, bases, weights, common_start, common_end
        )
        stats["peak_usage"], stats["utilization"] = _portfolio_usage(
            trades_by_system, bases, weights, common_start, common_end
        )
        scenario_stats[name] = stats
    spy_stats = _curve_stats(spy_curve, common_start, common_end)

    available_equity, available_equity_sources = _compatible_equity_curves(drive, ACTIVE_SYSTEMS)
    system_curves: dict[str, pd.DataFrame] = {}
    system_curve_labels: dict[str, str] = {}
    for system in ACTIVE_SYSTEMS:
        if system in available_equity:
            system_curves[system] = available_equity[system]
            system_curve_labels[system] = f"daily mark-to-market regular equity ({available_equity_sources[system].name})"
        else:
            system_curves[system] = _realized_curve(trades_by_system[system], bases[system])
            system_curve_labels[system] = "realized P&L by exit date"

    generated = datetime.now(ET)
    benchmark_chart = _svg_line(
        {**scenario_curves, "SPY": spy_curve},
        f"$500,000 cumulative P&L · {common_start} to {common_end}",
    )
    # Systems use native capital bases; SPY is $500k buy-and-hold over the same
    # common window for a visual benchmark (fair $ comparison is the chart above).
    systems_chart = _svg_line(
        {**system_curves, "SPY": spy_curve},
        "Raw standalone cumulative P&L by system (+ SPY $500k)",
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
        f"<tr><td>SPY</td><td>{_money(spy_stats['ending_equity'])}</td><td>{_pct(spy_stats['total_return'], sign=True)}</td>"
        f"<td>{_pct(spy_stats['cagr'], sign=True)}</td><td>{_money(spy_stats['max_dd'])}<br><span class='muted'>{_pct(spy_stats['max_dd_pct'])}</span></td>"
        f"<td>n/a</td><td>{_pct(spy_stats['volatility'])}</td><td>{spy_stats['sharpe']:.2f}</td>"
        f"<td>{int(spy_stats['worst_year_label'])}: {_pct(spy_stats['worst_year'], sign=True)}</td><td>100% invested</td></tr>"
    )
    allocation_rows = []
    for system in ACTIVE_SYSTEMS:
        allocation_rows.append(
            "<tr><td>" + system + "</td>"
            + "".join(
                f"<td>{_pct(scenario_weights[name][system] * 100)}<br><span class='muted'>{_money(allocation_dollars[name][system])}</span></td>"
                for name in scenario_weights
            )
            + f"<td>{_money(bases[system])}</td><td>{avg_corr[system]:.2f}</td></tr>"
        )

    summary_rows = []
    for system in ACTIVE_SYSTEMS:
        m = metrics(trades_by_system[system], system_curves[system])
        summary_rows.append(
            f"<tr><td><a href='#{system.lower()}'>{system}</a></td>" + _metric_cells(m) + "</tr>"
        )
    source_items = []
    for system in ACTIVE_SYSTEMS:
        duplicate_note = f"; {duplicates[system]} duplicate rows removed" if duplicates[system] else ""
        source_items.append(
            f"<li><strong>{system}:</strong> {html.escape(sources[system].name)}{duplicate_note}; "
            f"capital basis {_money(bases[system])}; curve: {html.escape(system_curve_labels[system])}</li>"
        )
    sections = "".join(
        _system_section(system, trades_by_system[system], system_curves[system], system_curve_labels[system])
        for system in ACTIVE_SYSTEMS
    )
    rec = scenario_stats["Recommended"]
    payload = {
        "generated": generated.isoformat(),
        "systems": list(ACTIVE_SYSTEMS),
        "common_period": {"start": common_start, "end": common_end},
        "capital_bases": bases,
        "weights": scenario_weights,
        "allocation_dollars": allocation_dollars,
        "scenario_metrics": scenario_stats,
        "spy_metrics": spy_stats,
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
.shell{{max-width:1420px;margin:auto;padding:28px}} header{{background:linear-gradient(130deg,#0f172a,#134e4a);color:#fff;padding:28px;border-radius:16px}}
h1{{margin:0 0 5px;font-size:30px}} h2{{margin:0 0 16px;font-size:22px}} h3{{margin:16px 0 8px}} .sub,.muted{{color:var(--muted);font-size:12px}}
header .sub{{color:#cbd5e1}} nav{{margin-top:18px;display:flex;gap:9px;flex-wrap:wrap}} nav a{{color:#fff;text-decoration:none;border:1px solid #ffffff55;border-radius:999px;padding:6px 11px}}
.cards{{display:grid;grid-template-columns:repeat(6,minmax(145px,1fr));gap:12px;margin:18px 0}} .card,section,.chart{{background:var(--panel);border:1px solid var(--line);border-radius:14px;box-shadow:0 3px 14px #0f172a0a}}
.card{{padding:16px}} .card span,.detail-grid span{{display:block;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}} .card strong{{display:block;font-size:23px;margin-top:4px}}
section{{padding:22px;margin:18px 0}} .chart{{padding:16px;margin:18px 0}} .chart-title{{font-size:16px;font-weight:700;margin:0 0 8px}} svg{{display:block;width:100%;height:auto}} .axis{{font-size:11px;fill:#64748b}}
.legend{{display:flex;flex-wrap:wrap;gap:14px;margin:7px 8px 0}} .legend span{{color:var(--muted)}} .legend i{{display:inline-block;width:18px;height:3px;margin:0 5px 3px 0}}
.table-wrap{{overflow-x:auto}} table{{width:100%;border-collapse:collapse;white-space:nowrap}} th,td{{padding:9px 10px;border-bottom:1px solid var(--line);text-align:right}} th{{background:#f1f5f9;color:#475569;font-size:11px;text-transform:uppercase}} th:first-child,td:first-child{{text-align:left}}
.combined{{font-weight:700;background:#ecfdf5}} .pos{{color:#15803d;font-weight:650}} .neg{{color:#b91c1c;font-weight:650}} .detail-grid{{display:grid;grid-template-columns:repeat(4,minmax(160px,1fr));gap:10px;margin:16px 0}} .detail-grid div{{background:#f8fafc;border:1px solid var(--line);padding:10px;border-radius:9px}}
.notice{{padding:13px 15px;border-radius:10px;margin:16px 0;background:#ecfeff;border:1px solid #a5f3fc}} .recommend{{background:#ecfdf5;border-color:#86efac}} details{{margin-top:12px}} footer{{color:var(--muted);font-size:12px;padding:20px 4px 36px}} a{{color:#0f766e}}
@media(max-width:900px){{.cards{{grid-template-columns:repeat(2,1fr)}}.detail-grid{{grid-template-columns:repeat(2,1fr)}}.shell{{padding:12px}}}}
</style></head><body><div class="shell">
<header><h1>Historical System Performance</h1><div class="sub">$500,000 allocation model · generated {generated.strftime("%Y-%m-%d %H:%M %Z")}</div>
<nav><a href="index.html">Scanner</a><a href="investment.html">Investment</a><a href="convergence.html">Convergence</a><a href="monthly.html">Monthly</a><a href="#allocation">Allocation</a><a href="#systems">Systems</a><a href="#method">Methodology</a></nav></header>
<div class="notice"><strong>Common comparison period:</strong> {common_start} through {common_end}. Every portfolio sleeve and SPY uses exactly these endpoints. SPY uses {html.escape(spy_label)}.</div>
<div class="cards">
<div class="card"><span>Portfolio</span><strong>{_money(PORTFOLIO_CAPITAL)}</strong></div><div class="card"><span>Recommended ending equity</span><strong>{_money(rec['ending_equity'])}</strong></div>
<div class="card"><span>Total return</span><strong>{_pct(rec['total_return'], sign=True)}</strong></div><div class="card"><span>CAGR</span><strong>{_pct(rec['cagr'], sign=True)}</strong></div>
<div class="card"><span>Max drawdown</span><strong>{_pct(rec['max_dd_pct'])}</strong></div><div class="card"><span>SPY return</span><strong>{_pct(spy_stats['total_return'], sign=True)}</strong></div>
</div>
<section id="allocation"><h2>Allocation scenarios</h2>
<p>These are investable-scale models: each system's complete historical return stream is scaled from its observed peak concurrent gross-notional basis to its assigned sleeve. The old sum of five full standalone accounts is not used as a portfolio result.</p>
<div class="table-wrap"><table><thead><tr><th>Scenario</th><th>Ending equity</th><th>Total return</th><th>CAGR</th><th>Max DD</th><th>PF</th><th>Ann. vol</th><th>Sharpe</th><th>Worst year</th><th>Peak usage</th></tr></thead><tbody>{''.join(scenario_rows)}</tbody></table></div>
<div class="chart">{benchmark_chart}</div>
<h3>Dollar allocations</h3><div class="table-wrap"><table><thead><tr><th>System</th><th>Equal capital</th><th>Risk-balanced</th><th>Recommended</th><th>Standalone basis</th><th>Avg monthly corr.</th></tr></thead><tbody>{''.join(allocation_rows)}</tbody></table></div>
<div class="notice recommend"><strong>Recommendation:</strong> {', '.join(f"{s} {_pct(recommended[s] * 100)} ({_money(allocation_dollars['Recommended'][s])})" for s in ACTIVE_SYSTEMS)}. Rounded dollar targets sum to exactly $500,000. Start from inverse-drawdown risk balance, then apply modest diversification and profit-factor robustness adjustments. All sleeves remain within 10%–30%. Review annually and rebalance to target when a sleeve drifts by more than 5 percentage points.</div>
<p class="muted">This recommendation is a backtest allocation model, not guaranteed performance or personalized financial advice.</p></section>
<section id="systems"><h2>Raw standalone system results</h2><p>These retain each engine's native historical sizing and full available period. They are diagnostic standalone results—not amounts simultaneously investable with $500,000.</p>
<div class="table-wrap"><table><thead><tr><th>System</th><th>Trades</th><th>Win rate</th><th>Avg profit</th><th>W/L count</th><th>W/L dollars</th><th>Avg days</th><th>Drawdown</th><th>Total profit</th></tr></thead><tbody>{''.join(summary_rows)}</tbody></table></div></section>
<div class="chart">{systems_chart}</div>
<div class="notice"><strong>SPY on this chart:</strong> buy-and-hold equity starting at {_money(PORTFOLIO_CAPITAL)}, using {html.escape(spy_label)}, aligned to {common_start}–{common_end}. System lines keep their native capital bases (~{_money(min(bases.values()))}–{_money(max(bases.values()))}); for like-for-like $500k scaling see the allocation chart above.</div>
{sections}
<section id="method"><h2>Methodology &amp; caveats</h2><ul>
<li><strong>Capital basis:</strong> position notional is inferred as |dollar P&amp;L ÷ percentage P&amp;L|; RL uses its native $47,500 sizing. Each denominator is that system's observed peak overlapping gross notional. Scaling allocation ÷ basis preserves trade economics and proportionally reduces all simultaneous positions when a sleeve is smaller than its standalone basis.</li>
<li><strong>Common period:</strong> begins at the latest first-open date and ends at the earliest last-close date among BRT, RL, MTS, WPBR, and YH. Only trades opened and closed inside it are used. SPY is aligned to available trading sessions inside those same dates.</li>
<li><strong>Benchmark:</strong> local <code>{html.escape(str(spy_source.relative_to(ROOT)))}</code>, using {html.escape(spy_label)}. SPY equity is normalized to the same $500,000.</li>
<li><strong>Risk-balanced:</strong> inverse realized drawdown by sleeve in the common period, constrained to 10% minimum and 30% maximum. <strong>Recommended:</strong> 55% risk-balance anchor, 25% low-correlation diversification, and 20% capped PF robustness; the same guardrails apply.</li>
<li><strong>Drawdown/volatility limitation:</strong> portfolio P&amp;L is recorded on trade exit dates because compatible mark-to-market curves are not available for every sleeve over the common period. This can materially understate intratrade drawdown and makes volatility/Sharpe lumpy; Sharpe is descriptive, zero risk-free rate, and not a forecast.</li>
<li><strong>Concurrency:</strong> peak usage sums scaled inferred notionals across overlapping positions. No borrowing is assumed; proportional sleeve scaling is the transparent capacity rule. Real execution, liquidity, taxes, fees, slippage, and cross-system duplicate-symbol constraints are not modeled.</li>
<li><strong>PF:</strong> scenario PF is gross scaled winning P&amp;L divided by gross scaled losing P&amp;L and is included only as a trade-level descriptive statistic. Annual rebalancing is an operating convention, not dynamically simulated in the curve.</li>
</ul><details><summary>Exact sources and capital bases</summary><ul>{''.join(source_items)}<li><strong>SPY:</strong> {html.escape(str(spy_source))}</li></ul></details></section>
<footer>Generated from local LatestRun backtest exports. Historical backtests are not guarantees of future performance.</footer>
<script type="application/json" id="report-data">{payload_json}</script></div></body></html>"""
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    return output, payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drive", type=Path, default=DEFAULT_DRIVE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output, payload = build_report(args.drive, args.output)
    recommended = payload["scenario_metrics"]["Recommended"]
    print(f"[performance] Wrote {output}")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
