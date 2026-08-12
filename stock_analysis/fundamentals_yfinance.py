#!/usr/bin/env python3
"""Thin Yahoo Finance (yfinance) fundamentals client with local DuckDB cache.

Used by CAN SLIM soft-fill (C/A/I/S float) and Qull EP catalyst proximity.
Does **not** call Financial Modeling Prep (FMP) — yfinance first.
Also called from ``pygetallMore.py`` after successful OHLC updates (default ON).

Historical vs point-in-time
---------------------------
**Historical (time series)** — safe for as-of backtests when filtered correctly:

- ``yf_earnings_quarterly`` — quarterly Diluted/Basic EPS by fiscal ``period_end``
  (from income statement + earnings history). Upserted on refresh; prior periods are
  retained even if Yahoo’s latest pull returns a shorter window.
- ``yf_earnings_annual`` — annual EPS by fiscal year-end (from annual income statement).
- ``yf_earnings_dates`` — earnings *report* calendar (estimate / reported / surprise).
  Yahoo often returns decades of rows via ``get_earnings_dates``; this is the longest
  EPS-related series Yahoo exposes for free.

**Point-in-time / snapshot** — Yahoo does **not** publish a historical short-interest
API through yfinance. ``Ticker.info`` only has the latest FINRA-lagged short fields
(``sharesShort``, ``shortRatio``, ``shortPercentOfFloat``, ``dateShortInterest``, …).

- ``yf_symbol_info`` — **current** dual-write snapshot (latest refresh). Mag10 /
  earnings-snapshot scripts keep reading this.
- ``yf_short_interest_history`` — **dated snapshots**: each successful refresh
  ``INSERT OR REPLACE`` one row keyed by ``(symbol, as_of)`` so a local history
  accumulates for backtests. Use the latest row with ``as_of <= trade_date``
  (see ``short_interest_as_of``). Settlement date ``date_short_interest`` is FINRA’s
  mid-month date (Yahoo lags ~1–2 weeks) — not “as of today.”

Env / flags
-----------
FUNDAMENTALS_DB       Path to DuckDB file (default: ``drive/fundamentals_cache.duckdb``).
YF_FUND_TTL_DAYS      Info + earnings refresh TTL in days (default: 7).
YF_FUND_FORCE_REFRESH If 1/true — ignore TTL and re-fetch (also appends a short snapshot).
YF_FUND_REFRESH_MISSING_SHORT
                      If 1/true — re-fetch when short fields are null even on TTL hit
                      (ADRs/OTCs that Yahoo leaves empty will re-hit network each call).
NO_YFINANCE           If 1/true — never hit Yahoo; cache-only (may return empty).

CLI: ``--force-refresh`` / ``--refresh-missing-short``. Short interest comes from the
same ``Ticker.info`` fetch — no separate command. Legacy cache rows (pre-short columns,
``raw_json`` lacking ``sharesShort``) soft-miss and re-fetch even within TTL.

Tables
------
yf_symbol_info, yf_earnings_quarterly, yf_earnings_annual, yf_earnings_dates,
yf_short_interest_history
"""
from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Any, Iterable, Optional

# ---------------------------------------------------------------------------
# Paths / policy
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FUNDAMENTALS_DB = _REPO_ROOT / "drive" / "fundamentals_cache.duckdb"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS yf_symbol_info (
    symbol VARCHAR NOT NULL,
    as_of DATE,
    market_cap DOUBLE,
    float_shares DOUBLE,
    inst_pct DOUBLE,
    roe DOUBLE,
    shares_short DOUBLE,
    shares_short_prior_month DOUBLE,
    date_short_interest DATE,
    shares_short_previous_month_date DATE,
    short_ratio DOUBLE,
    short_percent_of_float DOUBLE,
    shares_percent_shares_out DOUBLE,
    raw_json VARCHAR,
    fetched_at TIMESTAMP NOT NULL,
    PRIMARY KEY (symbol)
);
CREATE TABLE IF NOT EXISTS yf_earnings_quarterly (
    symbol VARCHAR NOT NULL,
    period_end DATE NOT NULL,
    eps_actual DOUBLE,
    eps_estimate DOUBLE,
    surprise_pct DOUBLE,
    reported_date DATE,
    fetched_at TIMESTAMP NOT NULL,
    PRIMARY KEY (symbol, period_end)
);
CREATE TABLE IF NOT EXISTS yf_earnings_annual (
    symbol VARCHAR NOT NULL,
    period_end DATE NOT NULL,
    eps_actual DOUBLE,
    eps_estimate DOUBLE,
    surprise_pct DOUBLE,
    reported_date DATE,
    fetched_at TIMESTAMP NOT NULL,
    PRIMARY KEY (symbol, period_end)
);
CREATE TABLE IF NOT EXISTS yf_earnings_dates (
    symbol VARCHAR NOT NULL,
    earnings_date DATE NOT NULL,
    eps_estimate DOUBLE,
    eps_reported DOUBLE,
    surprise_pct DOUBLE,
    fetched_at TIMESTAMP NOT NULL,
    PRIMARY KEY (symbol, earnings_date)
);
CREATE TABLE IF NOT EXISTS yf_short_interest_history (
    symbol VARCHAR NOT NULL,
    as_of DATE NOT NULL,
    shares_short DOUBLE,
    shares_short_prior_month DOUBLE,
    date_short_interest DATE,
    shares_short_previous_month_date DATE,
    short_ratio DOUBLE,
    short_percent_of_float DOUBLE,
    shares_percent_shares_out DOUBLE,
    fetched_at TIMESTAMP NOT NULL,
    PRIMARY KEY (symbol, as_of)
);
"""

# Yahoo caps get_earnings_dates(limit=...) at 100 (higher raises ValueError).
_EARNINGS_DATES_LIMIT = 100

# Columns added after initial deploy — ALTER IF NOT EXISTS keeps old DBs usable.
_YF_SYMBOL_INFO_EXTRA_COLS: tuple[tuple[str, str], ...] = (
    ("shares_short", "DOUBLE"),
    ("shares_short_prior_month", "DOUBLE"),
    ("date_short_interest", "DATE"),
    ("shares_short_previous_month_date", "DATE"),
    ("short_ratio", "DOUBLE"),
    ("short_percent_of_float", "DOUBLE"),
    ("shares_percent_shares_out", "DOUBLE"),
)

_INFO_SELECT_COLS = (
    "symbol",
    "as_of",
    "market_cap",
    "float_shares",
    "inst_pct",
    "roe",
    "shares_short",
    "shares_short_prior_month",
    "date_short_interest",
    "shares_short_previous_month_date",
    "short_ratio",
    "short_percent_of_float",
    "shares_percent_shares_out",
    "raw_json",
    "fetched_at",
)


def _env_truthy(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in ("1", "true", "yes", "on")


def yfinance_disabled() -> bool:
    """Honor NO_YFINANCE (and common aliases)."""
    for k in ("NO_YFINANCE", "NO_YF", "DISABLE_YFINANCE"):
        if _env_truthy(k):
            return True
    return False


def force_refresh_requested() -> bool:
    return _env_truthy("YF_FUND_FORCE_REFRESH")


def refresh_missing_short_requested() -> bool:
    return _env_truthy("YF_FUND_REFRESH_MISSING_SHORT")


def ttl_days(default: int = 7) -> int:
    raw = str(os.environ.get("YF_FUND_TTL_DAYS", "") or "").strip()
    if not raw:
        return int(default)
    try:
        return max(0, int(float(raw)))
    except (TypeError, ValueError):
        return int(default)


def resolve_fundamentals_db(path: str | Path | None = None) -> Path:
    if path is not None and str(path).strip():
        return Path(str(path)).expanduser().resolve()
    env = str(os.environ.get("FUNDAMENTALS_DB", "") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return DEFAULT_FUNDAMENTALS_DB.resolve()


def _connect(db_path: Path, *, read_only: bool = False):
    import duckdb

    db_path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(db_path), read_only=read_only)


def ensure_schema(db_path: str | Path | None = None) -> Path:
    p = resolve_fundamentals_db(db_path)
    con = _connect(p, read_only=False)
    try:
        con.execute(_SCHEMA_SQL)
        _migrate_yf_symbol_info(con)
        _backfill_short_history_from_info(con)
    finally:
        con.close()
    return p


def _migrate_yf_symbol_info(con) -> None:
    """Add short-interest columns to existing caches (CREATE IF NOT EXISTS is a no-op)."""
    for col, typ in _YF_SYMBOL_INFO_EXTRA_COLS:
        try:
            con.execute(f"ALTER TABLE yf_symbol_info ADD COLUMN IF NOT EXISTS {col} {typ}")
        except Exception:
            # Older DuckDB without IF NOT EXISTS: ignore duplicate-column errors.
            try:
                con.execute(f"ALTER TABLE yf_symbol_info ADD COLUMN {col} {typ}")
            except Exception:
                pass


def _backfill_short_history_from_info(con) -> None:
    """Seed history from current ``yf_symbol_info`` when history is empty for a symbol."""
    try:
        con.execute(
            """
            INSERT OR IGNORE INTO yf_short_interest_history
            (symbol, as_of, shares_short, shares_short_prior_month, date_short_interest,
             shares_short_previous_month_date, short_ratio, short_percent_of_float,
             shares_percent_shares_out, fetched_at)
            SELECT
                i.symbol,
                COALESCE(i.as_of, CAST(i.fetched_at AS DATE)),
                i.shares_short,
                i.shares_short_prior_month,
                i.date_short_interest,
                i.shares_short_previous_month_date,
                i.short_ratio,
                i.short_percent_of_float,
                i.shares_percent_shares_out,
                i.fetched_at
            FROM yf_symbol_info i
            WHERE COALESCE(i.as_of, CAST(i.fetched_at AS DATE)) IS NOT NULL
              AND (
                i.shares_short IS NOT NULL
                OR i.short_ratio IS NOT NULL
                OR i.short_percent_of_float IS NOT NULL
              )
              AND NOT EXISTS (
                SELECT 1 FROM yf_short_interest_history h WHERE h.symbol = i.symbol
              )
            """
        )
    except Exception:
        pass


def _parse_ts(v: Any) -> Optional[datetime]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    if isinstance(v, date) and not isinstance(v, datetime):
        return datetime(v.year, v.month, v.day)
    s = str(v).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:26].replace("T", " "), fmt if "T" not in fmt else "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", ""))
    except ValueError:
        return None


def _to_date(v: Any) -> Optional[date]:
    if v is None or (isinstance(v, float) and v != v):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    if not s or s.lower() in ("nat", "none", "nan"):
        return None
    s = s[:10].replace("/", "-")
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        try:
            return datetime.strptime(s.replace("-", "")[:8], "%Y%m%d").date()
        except ValueError:
            return None


def _yahoo_date(v: Any) -> Optional[date]:
    """Parse Yahoo info dates (ISO string or Unix seconds / ms)."""
    d = _to_date(v)
    if d is not None:
        return d
    if isinstance(v, bool) or v is None:
        return None
    try:
        if isinstance(v, (int, float)):
            x = float(v)
            if x != x or x <= 0:
                return None
            # ms vs seconds heuristic
            if x > 1e12:
                x = x / 1000.0
            return datetime.utcfromtimestamp(x).date()
        s = str(v).strip()
        if s.isdigit():
            return _yahoo_date(int(s))
    except (TypeError, ValueError, OSError, OverflowError):
        return None
    return None


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        if isinstance(v, float) and v != v:
            return None
        x = float(v)
        if x != x:
            return None
        return x
    except (TypeError, ValueError):
        return None


def estimate_market_cap(
    market_cap: Optional[float],
    float_shares: Optional[float],
    current_price: Optional[float],
) -> Optional[float]:
    """Prefer Yahoo marketCap; else shares × price when Yahoo omits cap (common)."""
    mc = _safe_float(market_cap)
    if mc is not None and mc > 0:
        return mc
    sh = _safe_float(float_shares)
    px = _safe_float(current_price)
    if sh is not None and px is not None and sh > 0 and px > 0:
        return sh * px
    return mc


def _sleep_backoff(attempt: int = 0, base: float = 0.35) -> None:
    """Polite Yahoo pacing + light jitter."""
    delay = base * (1.0 + 0.5 * attempt) + random.uniform(0.05, 0.25)
    time.sleep(min(delay, 4.0))


def _parse_info_raw(info: dict[str, Any]) -> dict[str, Any]:
    raw_json = info.get("raw_json")
    if not raw_json:
        return {}
    try:
        if isinstance(raw_json, str):
            raw = json.loads(raw_json)
        else:
            raw = raw_json
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _short_typed_present(info: dict[str, Any]) -> bool:
    return (
        _safe_float(info.get("shares_short")) is not None
        or _safe_float(info.get("short_ratio")) is not None
        or _safe_float(info.get("short_percent_of_float")) is not None
    )


def _short_interest_never_fetched(info: dict[str, Any]) -> bool:
    """True for legacy rows that predate short extraction (not Yahoo-empty).

    Modern fetches always write ``sharesShort`` / ``shortRatio`` / ``shortPercentOfFloat``
    into ``raw_json`` (even when null). Pre-short cache rows omit those keys entirely,
    so a TTL hit would otherwise lock null shorts forever.
    """
    if not info:
        return False
    if _short_typed_present(info):
        return False
    raw = _parse_info_raw(info)
    if not raw:
        # No raw_json and null typed shorts — treat as never extracted.
        return True
    return not any(
        k in raw for k in ("sharesShort", "shortRatio", "shortPercentOfFloat")
    )


def _short_fields_null(info: dict[str, Any]) -> bool:
    return bool(info) and not _short_typed_present(info)


# ---------------------------------------------------------------------------
# Bundle
# ---------------------------------------------------------------------------


@dataclass
class SymbolFundamentals:
    symbol: str
    market_cap: Optional[float] = None
    float_shares: Optional[float] = None
    inst_pct: Optional[float] = None  # 0–1 fraction when from Yahoo
    roe: Optional[float] = None  # fraction (e.g. 0.17 = 17%)
    shares_short: Optional[float] = None
    shares_short_prior_month: Optional[float] = None
    date_short_interest: Optional[date] = None  # FINRA settlement date (Yahoo lag)
    shares_short_previous_month_date: Optional[date] = None
    short_ratio: Optional[float] = None  # days to cover
    short_percent_of_float: Optional[float] = None  # 0–1 fraction when from Yahoo
    shares_percent_shares_out: Optional[float] = None  # 0–1 fraction when present
    c_eps_yoy: Optional[float] = None  # fraction YoY (0.25 = +25%)
    a_eps_cagr: Optional[float] = None  # fraction CAGR
    current_price: Optional[float] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    beta: Optional[float] = None
    earnings_quarterly: list[dict[str, Any]] = field(default_factory=list)
    earnings_dates: list[dict[str, Any]] = field(default_factory=list)
    fetched_at: Optional[datetime] = None
    cache_hit: bool = False
    source: str = ""  # CACHE | FETCH | DISABLED | EMPTY

    def as_info_dict(self, *, as_of_date: str | None = None) -> dict[str, Any]:
        """Shape compatible with rocket_tbn yfinance enrich cache entries."""
        return {
            "market_cap": self.market_cap,
            "current_price": self.current_price,
            "sector": self.sector,
            "industry": self.industry,
            "beta": self.beta,
            "float_shares": self.float_shares,
            "heldPercentInstitutions": self.inst_pct,
            "returnOnEquity": self.roe,
            "sharesShort": self.shares_short,
            "sharesShortPriorMonth": self.shares_short_prior_month,
            "dateShortInterest": (
                self.date_short_interest.isoformat() if self.date_short_interest else None
            ),
            "sharesShortPreviousMonthDate": (
                self.shares_short_previous_month_date.isoformat()
                if self.shares_short_previous_month_date
                else None
            ),
            "shortRatio": self.short_ratio,
            "shortPercentOfFloat": self.short_percent_of_float,
            "sharesPercentSharesOut": self.shares_percent_shares_out,
            "as_of_date": as_of_date or datetime.now().strftime("%Y-%m-%d"),
        }


# ---------------------------------------------------------------------------
# Metrics from EPS series
# ---------------------------------------------------------------------------


def compute_eps_yoy(quarterly: list[dict[str, Any]]) -> Optional[float]:
    """YoY EPS growth from most recent quarter vs same quarter ~4 ago.

    Prefers eps_actual; returns fraction (0.25 = +25%).
    """
    rows = sorted(
        (r for r in quarterly if _safe_float(r.get("eps_actual")) is not None and r.get("period_end")),
        key=lambda r: str(r.get("period_end")),
        reverse=True,
    )
    if len(rows) < 5:
        # try with at least 2 spaced ~1y if only sparse
        if len(rows) < 2:
            return None
    latest = rows[0]
    latest_eps = _safe_float(latest.get("eps_actual"))
    if latest_eps is None:
        return None
    # Prefer index +4 (YoY); else nearest period ~365d earlier
    prior = None
    if len(rows) >= 5:
        prior = rows[4]
    else:
        ld = _to_date(latest.get("period_end"))
        if ld is None:
            return None
        best = None
        best_delta = None
        for r in rows[1:]:
            d = _to_date(r.get("period_end"))
            if d is None:
                continue
            delta = abs((ld - d).days - 365)
            if best_delta is None or delta < best_delta:
                best_delta = delta
                best = r
        if best is not None and best_delta is not None and best_delta <= 80:
            prior = best
    if prior is None:
        return None
    prior_eps = _safe_float(prior.get("eps_actual"))
    if prior_eps is None or prior_eps == 0:
        return None
    # Avoid nonsense from tiny / sign-flip bases
    if abs(prior_eps) < 1e-6:
        return None
    return (latest_eps / prior_eps) - 1.0


def compute_eps_cagr(annual_or_q: list[dict[str, Any]], *, years: int = 3) -> Optional[float]:
    """Annual EPS CAGR over ``years`` using period_end ordered series.

    Uses yearly rows when available (period spacing ~365d); else takes
    every 4th quarterly observation.
    """
    rows = sorted(
        (r for r in annual_or_q if _safe_float(r.get("eps_actual")) is not None and r.get("period_end")),
        key=lambda r: str(r.get("period_end")),
    )
    if len(rows) < 2:
        return None
    # Detect annual vs quarterly by median spacing
    dates = [_to_date(r["period_end"]) for r in rows]
    dates = [d for d in dates if d is not None]
    if len(dates) < 2:
        return None
    gaps = [(dates[i] - dates[i - 1]).days for i in range(1, len(dates))]
    med = sorted(gaps)[len(gaps) // 2] if gaps else 90
    if med >= 200:
        series = rows
        need = years
        step = 1
    else:
        series = rows
        need = years
        step = 4
    if len(series) < need * step + 1:
        # fall back to first→last if span is enough
        d0 = _to_date(series[0]["period_end"])
        d1 = _to_date(series[-1]["period_end"])
        e0 = _safe_float(series[0].get("eps_actual"))
        e1 = _safe_float(series[-1].get("eps_actual"))
        if d0 is None or d1 is None or e0 is None or e1 is None or e0 <= 0 or e1 <= 0:
            return None
        yr = max((d1 - d0).days / 365.25, 0.5)
        if yr < 1.5:
            return None
        return (e1 / e0) ** (1.0 / yr) - 1.0
    end = series[-1]
    start = series[-(need * step) - 1]
    e0 = _safe_float(start.get("eps_actual"))
    e1 = _safe_float(end.get("eps_actual"))
    d0 = _to_date(start.get("period_end"))
    d1 = _to_date(end.get("period_end"))
    if e0 is None or e1 is None or e0 <= 0 or e1 <= 0 or d0 is None or d1 is None:
        return None
    yr = max((d1 - d0).days / 365.25, 0.5)
    return (e1 / e0) ** (1.0 / yr) - 1.0


def classify_ep_catalyst(
    gap_date: Any,
    earnings_dates: list[dict[str, Any]],
    *,
    trading_dates: Optional[list[Any]] = None,
    window_trading_days: int = 5,
    min_surprise_pct: Optional[float] = None,
) -> str:
    """Return EP_CATALYST label for a gap day.

    - ``EARNINGS`` if an earnings_date falls within ±window trading days of gap
    - ``EARNINGS_SURPRISE`` if also surprise_pct >= min_surprise_pct (when set)
    - ``UNKNOWN`` otherwise

    ``min_surprise_pct`` is a fraction (0.05 = +5% surprise). Yahoo
    ``surprisePercent`` is typically already a fraction.
    """
    gd = _to_date(gap_date)
    if gd is None or not earnings_dates:
        return "UNKNOWN"

    ed_list: list[tuple[date, Optional[float]]] = []
    for r in earnings_dates:
        d = _to_date(r.get("earnings_date") or r.get("reported_date") or r.get("period_end"))
        if d is None:
            continue
        ed_list.append((d, _safe_float(r.get("surprise_pct"))))
    if not ed_list:
        return "UNKNOWN"

    # Build trading-day distance when a date index is provided
    if trading_dates:
        td: list[date] = []
        for x in trading_dates:
            d = _to_date(x)
            if d is not None:
                td.append(d)
        td = sorted(set(td))
        if not td:
            trading_dates = None
        else:
            try:
                gi = td.index(gd)
            except ValueError:
                # nearest session
                gi = min(range(len(td)), key=lambda i: abs((td[i] - gd).days))
            best: Optional[tuple[int, Optional[float]]] = None
            for ed, surp in ed_list:
                try:
                    ei = td.index(ed)
                except ValueError:
                    ei = min(range(len(td)), key=lambda i: abs((td[i] - ed).days))
                    if abs((td[ei] - ed).days) > 3:
                        continue
                dist = abs(ei - gi)
                if dist <= int(window_trading_days):
                    if best is None or dist < best[0]:
                        best = (dist, surp)
            if best is None:
                return "UNKNOWN"
            surp = best[1]
            if min_surprise_pct is not None and surp is not None and surp >= float(min_surprise_pct):
                return "EARNINGS_SURPRISE"
            return "EARNINGS"

    # Calendar-day fallback (~7d ≈ 5 trading days)
    cal_window = max(int(window_trading_days) * 7 // 5, int(window_trading_days))
    best2: Optional[tuple[int, Optional[float]]] = None
    for ed, surp in ed_list:
        dist = abs((ed - gd).days)
        if dist <= cal_window:
            if best2 is None or dist < best2[0]:
                best2 = (dist, surp)
    if best2 is None:
        return "UNKNOWN"
    surp = best2[1]
    if min_surprise_pct is not None and surp is not None and surp >= float(min_surprise_pct):
        return "EARNINGS_SURPRISE"
    return "EARNINGS"


# ---------------------------------------------------------------------------
# Cache read / freshness
# ---------------------------------------------------------------------------


def _info_fresh(fetched_at: Any, *, ttl: int) -> bool:
    ts = _parse_ts(fetched_at)
    if ts is None:
        return False
    return datetime.now() - ts <= timedelta(days=ttl)


def _load_info_row(con, symbol: str) -> Optional[dict[str, Any]]:
    cols = ", ".join(_INFO_SELECT_COLS)
    row = con.execute(
        f"SELECT {cols} FROM yf_symbol_info WHERE symbol = ?",
        [symbol],
    ).fetchone()
    if not row:
        return None
    return dict(zip(_INFO_SELECT_COLS, row))


def _load_eps_period_table(con, table: str, symbol: str) -> list[dict[str, Any]]:
    rows = con.execute(
        f"SELECT period_end, eps_actual, eps_estimate, surprise_pct, reported_date, fetched_at "
        f"FROM {table} WHERE symbol = ? ORDER BY period_end",
        [symbol],
    ).fetchall()
    out = []
    for r in rows:
        out.append(
            {
                "period_end": r[0],
                "eps_actual": r[1],
                "eps_estimate": r[2],
                "surprise_pct": r[3],
                "reported_date": r[4],
                "fetched_at": r[5],
            }
        )
    return out


def _load_quarterly(con, symbol: str) -> list[dict[str, Any]]:
    return _load_eps_period_table(con, "yf_earnings_quarterly", symbol)


def _load_annual(con, symbol: str) -> list[dict[str, Any]]:
    return _load_eps_period_table(con, "yf_earnings_annual", symbol)


def _load_short_history(con, symbol: str) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        SELECT as_of, shares_short, shares_short_prior_month, date_short_interest,
               shares_short_previous_month_date, short_ratio, short_percent_of_float,
               shares_percent_shares_out, fetched_at
        FROM yf_short_interest_history
        WHERE symbol = ?
        ORDER BY as_of
        """,
        [symbol],
    ).fetchall()
    keys = (
        "as_of",
        "shares_short",
        "shares_short_prior_month",
        "date_short_interest",
        "shares_short_previous_month_date",
        "short_ratio",
        "short_percent_of_float",
        "shares_percent_shares_out",
        "fetched_at",
    )
    return [dict(zip(keys, r)) for r in rows]


def _load_earnings_dates(con, symbol: str) -> list[dict[str, Any]]:
    rows = con.execute(
        "SELECT earnings_date, eps_estimate, eps_reported, surprise_pct, fetched_at "
        "FROM yf_earnings_dates WHERE symbol = ? ORDER BY earnings_date",
        [symbol],
    ).fetchall()
    out = []
    for r in rows:
        out.append(
            {
                "earnings_date": r[0],
                "eps_estimate": r[1],
                "eps_reported": r[2],
                "surprise_pct": r[3],
                "fetched_at": r[4],
            }
        )
    return out


def _quarterly_covers_lookback(quarterly: list[dict[str, Any]], lookback_years: float) -> bool:
    if not quarterly:
        return False
    dates = [_to_date(r.get("period_end")) for r in quarterly]
    dates = [d for d in dates if d is not None]
    if len(dates) < 2:
        return False
    span_years = (max(dates) - min(dates)).days / 365.25
    # Need roughly lookback_years of history (allow slight shortfall)
    return span_years >= max(0.0, float(lookback_years) - 0.35) and len(dates) >= 4


def _earnings_fetch_fresh(quarterly: list[dict[str, Any]], dates: list[dict[str, Any]], *, ttl: int) -> bool:
    stamps = []
    for r in quarterly:
        stamps.append(_parse_ts(r.get("fetched_at")))
    for r in dates:
        stamps.append(_parse_ts(r.get("fetched_at")))
    stamps = [s for s in stamps if s is not None]
    if not stamps:
        return False
    return datetime.now() - max(stamps) <= timedelta(days=ttl)


# ---------------------------------------------------------------------------
# Yahoo fetch
# ---------------------------------------------------------------------------


def _fetch_yahoo_payload(symbol: str) -> dict[str, Any]:
    """Live Yahoo pull. Raises on hard failure; returns partial dict on soft miss."""
    import yfinance as yf

    t = yf.Ticker(symbol)
    info: dict[str, Any] = {}
    try:
        info = dict(getattr(t, "info", None) or {})
    except Exception:
        info = {}

    market_cap = _safe_float(info.get("marketCap"))
    float_shares = _safe_float(info.get("floatShares") or info.get("sharesOutstanding"))
    inst_pct = _safe_float(info.get("heldPercentInstitutions"))
    roe = _safe_float(info.get("returnOnEquity"))
    shares_short = _safe_float(info.get("sharesShort"))
    shares_short_prior_month = _safe_float(info.get("sharesShortPriorMonth"))
    date_short_interest = _yahoo_date(info.get("dateShortInterest"))
    shares_short_previous_month_date = _yahoo_date(info.get("sharesShortPreviousMonthDate"))
    short_ratio = _safe_float(info.get("shortRatio"))
    short_percent_of_float = _safe_float(info.get("shortPercentOfFloat"))
    shares_percent_shares_out = _safe_float(info.get("sharesPercentSharesOut"))
    _px_early = _safe_float(
        info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
    )
    market_cap = estimate_market_cap(market_cap, float_shares, _px_early)

    quarterly_rows: list[dict[str, Any]] = []
    # 1) Diluted EPS from quarterly income statement (multi-year)
    try:
        qi = t.quarterly_income_stmt
        if qi is not None and not getattr(qi, "empty", True):
            eps_key = None
            for cand in ("Diluted EPS", "Basic EPS"):
                if cand in qi.index:
                    eps_key = cand
                    break
            if eps_key is not None:
                series = qi.loc[eps_key]
                for col, val in series.items():
                    pe = _to_date(col)
                    eps = _safe_float(val)
                    if pe is None or eps is None:
                        continue
                    quarterly_rows.append(
                        {
                            "period_end": pe,
                            "eps_actual": eps,
                            "eps_estimate": None,
                            "surprise_pct": None,
                            "reported_date": None,
                        }
                    )
    except Exception:
        pass

    # 2) Merge surprise % from earnings_history (short window)
    try:
        eh = t.get_earnings_history()
        if eh is not None and not getattr(eh, "empty", True):
            by_pe = {_to_date(r.get("period_end")): r for r in quarterly_rows}
            for idx, row in eh.iterrows():
                pe = _to_date(idx)
                if pe is None:
                    continue
                actual = _safe_float(row.get("epsActual"))
                est = _safe_float(row.get("epsEstimate"))
                surp = _safe_float(row.get("surprisePercent"))
                if pe in by_pe:
                    if actual is not None:
                        by_pe[pe]["eps_actual"] = actual
                    by_pe[pe]["eps_estimate"] = est
                    by_pe[pe]["surprise_pct"] = surp
                else:
                    by_pe[pe] = {
                        "period_end": pe,
                        "eps_actual": actual,
                        "eps_estimate": est,
                        "surprise_pct": surp,
                        "reported_date": None,
                    }
            quarterly_rows = list(by_pe.values())
    except Exception:
        pass

    # Annual EPS kept separate for CAGR (do not mix into quarterly table)
    annual_rows: list[dict[str, Any]] = []
    try:
        ai = t.income_stmt
        if ai is not None and not getattr(ai, "empty", True):
            eps_key = None
            for cand in ("Diluted EPS", "Basic EPS"):
                if cand in ai.index:
                    eps_key = cand
                    break
            if eps_key is not None:
                for col, val in ai.loc[eps_key].items():
                    pe = _to_date(col)
                    eps = _safe_float(val)
                    if pe is None or eps is None:
                        continue
                    annual_rows.append(
                        {
                            "period_end": pe,
                            "eps_actual": eps,
                            "eps_estimate": None,
                            "surprise_pct": None,
                            "reported_date": None,
                        }
                    )
    except Exception:
        pass

    # Earnings dates (needs lxml for HTML scrape on many yfinance builds)
    earnings_dates: list[dict[str, Any]] = []
    try:
        ed = t.get_earnings_dates(limit=_EARNINGS_DATES_LIMIT)
        if ed is not None and not getattr(ed, "empty", True):
            # columns vary: EPS Estimate, Reported EPS, Surprise(%)
            colmap = {str(c).lower(): c for c in ed.columns}

            def _col(*names: str):
                for n in names:
                    if n.lower() in colmap:
                        return colmap[n.lower()]
                return None

            c_est = _col("EPS Estimate", "eps estimate")
            c_rep = _col("Reported EPS", "reported eps")
            c_sur = _col("Surprise(%)", "surprise(%)", "surprise%")
            for idx, row in ed.iterrows():
                d = _to_date(idx)
                if d is None:
                    continue
                surp = _safe_float(row[c_sur]) if c_sur is not None else None
                # Surprise(%) sometimes in percent points (5.0) vs fraction — normalize
                if surp is not None and abs(surp) > 2.0:
                    surp = surp / 100.0
                earnings_dates.append(
                    {
                        "earnings_date": d,
                        "eps_estimate": _safe_float(row[c_est]) if c_est is not None else None,
                        "eps_reported": _safe_float(row[c_rep]) if c_rep is not None else None,
                        "surprise_pct": surp,
                    }
                )
    except Exception:
        pass

    # Calendar next earnings date fallback
    try:
        cal = getattr(t, "calendar", None) or {}
        if isinstance(cal, dict):
            edates = cal.get("Earnings Date")
            if edates is not None:
                if not isinstance(edates, (list, tuple)):
                    edates = [edates]
                existing = {r["earnings_date"] for r in earnings_dates}
                for x in edates:
                    d = _to_date(x)
                    if d is None or d in existing:
                        continue
                    earnings_dates.append(
                        {
                            "earnings_date": d,
                            "eps_estimate": _safe_float(cal.get("Earnings Average")),
                            "eps_reported": None,
                            "surprise_pct": None,
                        }
                    )
    except Exception:
        pass

    # If still no earnings_dates, approximate from quarterly period ends (weak)
    if not earnings_dates and quarterly_rows:
        for r in quarterly_rows:
            pe = _to_date(r.get("period_end"))
            if pe is None:
                continue
            earnings_dates.append(
                {
                    "earnings_date": pe,
                    "eps_estimate": r.get("eps_estimate"),
                    "eps_reported": r.get("eps_actual"),
                    "surprise_pct": r.get("surprise_pct"),
                }
            )

    current_price = _px_early
    raw = {
        "marketCap": market_cap,
        "floatShares": float_shares,
        "heldPercentInstitutions": inst_pct,
        "returnOnEquity": roe,
        "sharesShort": shares_short,
        "sharesShortPriorMonth": shares_short_prior_month,
        "dateShortInterest": date_short_interest.isoformat() if date_short_interest else None,
        "sharesShortPreviousMonthDate": (
            shares_short_previous_month_date.isoformat()
            if shares_short_previous_month_date
            else None
        ),
        "shortRatio": short_ratio,
        "shortPercentOfFloat": short_percent_of_float,
        "sharesPercentSharesOut": shares_percent_shares_out,
        "earningsQuarterlyGrowth": _safe_float(info.get("earningsQuarterlyGrowth")),
        "earningsGrowth": _safe_float(info.get("earningsGrowth")),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "beta": info.get("beta"),
        "currentPrice": current_price,
        "a_eps_cagr_hint": compute_eps_cagr(annual_rows, years=3)
        if annual_rows
        else compute_eps_cagr(quarterly_rows, years=3),
    }

    return {
        "market_cap": market_cap,
        "float_shares": float_shares,
        "inst_pct": inst_pct,
        "roe": roe,
        "shares_short": shares_short,
        "shares_short_prior_month": shares_short_prior_month,
        "date_short_interest": date_short_interest,
        "shares_short_previous_month_date": shares_short_previous_month_date,
        "short_ratio": short_ratio,
        "short_percent_of_float": short_percent_of_float,
        "shares_percent_shares_out": shares_percent_shares_out,
        "quarterly": quarterly_rows,
        "annual": annual_rows,
        "earnings_dates": earnings_dates,
        "raw": raw,
    }


def _upsert_eps_rows(
    con,
    table: str,
    symbol: str,
    rows: list[dict[str, Any]],
    *,
    now: datetime,
) -> None:
    """INSERT OR REPLACE by (symbol, period_end) — never wipe older periods."""
    for r in rows or []:
        pe = _to_date(r.get("period_end"))
        if pe is None:
            continue
        con.execute(
            f"""
            INSERT OR REPLACE INTO {table}
            (symbol, period_end, eps_actual, eps_estimate, surprise_pct, reported_date, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                symbol,
                pe,
                _safe_float(r.get("eps_actual")),
                _safe_float(r.get("eps_estimate")),
                _safe_float(r.get("surprise_pct")),
                _to_date(r.get("reported_date")),
                now,
            ],
        )


def _upsert_short_history_row(con, symbol: str, payload: dict[str, Any], *, as_of: date, now: datetime) -> None:
    """Append/replace today's short snapshot. Yahoo has no historical short series."""
    # Skip empty snapshots (Yahoo often null for ADRs/OTCs) so history stays useful.
    if (
        _safe_float(payload.get("shares_short")) is None
        and _safe_float(payload.get("short_ratio")) is None
        and _safe_float(payload.get("short_percent_of_float")) is None
    ):
        return
    con.execute(
        """
        INSERT OR REPLACE INTO yf_short_interest_history
        (symbol, as_of, shares_short, shares_short_prior_month, date_short_interest,
         shares_short_previous_month_date, short_ratio, short_percent_of_float,
         shares_percent_shares_out, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            symbol,
            as_of,
            payload.get("shares_short"),
            payload.get("shares_short_prior_month"),
            payload.get("date_short_interest"),
            payload.get("shares_short_previous_month_date"),
            payload.get("short_ratio"),
            payload.get("short_percent_of_float"),
            payload.get("shares_percent_shares_out"),
            now,
        ],
    )


def _upsert_payload(con, symbol: str, payload: dict[str, Any], *, now: datetime) -> None:
    as_of = now.date()
    con.execute(
        """
        INSERT OR REPLACE INTO yf_symbol_info
        (symbol, as_of, market_cap, float_shares, inst_pct, roe,
         shares_short, shares_short_prior_month, date_short_interest,
         shares_short_previous_month_date, short_ratio, short_percent_of_float,
         shares_percent_shares_out, raw_json, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            symbol,
            as_of,
            payload.get("market_cap"),
            payload.get("float_shares"),
            payload.get("inst_pct"),
            payload.get("roe"),
            payload.get("shares_short"),
            payload.get("shares_short_prior_month"),
            payload.get("date_short_interest"),
            payload.get("shares_short_previous_month_date"),
            payload.get("short_ratio"),
            payload.get("short_percent_of_float"),
            payload.get("shares_percent_shares_out"),
            json.dumps(payload.get("raw") or {}, default=str),
            now,
        ],
    )
    # Dual-write: current snapshot + dated history (for backtests).
    _upsert_short_history_row(con, symbol, payload, as_of=as_of, now=now)

    # Merge EPS series (do not DELETE — Yahoo windows shrink; keep accumulated history).
    _upsert_eps_rows(con, "yf_earnings_quarterly", symbol, payload.get("quarterly") or [], now=now)
    _upsert_eps_rows(con, "yf_earnings_annual", symbol, payload.get("annual") or [], now=now)

    for r in payload.get("earnings_dates") or []:
        ed = _to_date(r.get("earnings_date"))
        if ed is None:
            continue
        con.execute(
            """
            INSERT OR REPLACE INTO yf_earnings_dates
            (symbol, earnings_date, eps_estimate, eps_reported, surprise_pct, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                symbol,
                ed,
                _safe_float(r.get("eps_estimate")),
                _safe_float(r.get("eps_reported")),
                _safe_float(r.get("surprise_pct")),
                now,
            ],
        )


def short_interest_as_of(
    symbol: str,
    as_of: date | str | datetime,
    *,
    db_path: str | Path | None = None,
) -> Optional[dict[str, Any]]:
    """Latest short-interest snapshot with ``as_of <=`` the given date (backtest helper).

    Returns None if no history row exists on or before ``as_of``. Yahoo never supplies
    a true historical short series — this only reflects local refresh snapshots.
    """
    sym = str(symbol or "").strip().upper()
    if not sym:
        return None
    target = _to_date(as_of)
    if target is None:
        return None
    p = ensure_schema(db_path)
    con = _connect(p, read_only=True)
    try:
        row = con.execute(
            """
            SELECT as_of, shares_short, shares_short_prior_month, date_short_interest,
                   shares_short_previous_month_date, short_ratio, short_percent_of_float,
                   shares_percent_shares_out, fetched_at
            FROM yf_short_interest_history
            WHERE symbol = ? AND as_of <= ?
            ORDER BY as_of DESC
            LIMIT 1
            """,
            [sym, target],
        ).fetchone()
        if not row:
            return None
        keys = (
            "as_of",
            "shares_short",
            "shares_short_prior_month",
            "date_short_interest",
            "shares_short_previous_month_date",
            "short_ratio",
            "short_percent_of_float",
            "shares_percent_shares_out",
            "fetched_at",
        )
        return dict(zip(keys, row))
    finally:
        con.close()


def _bundle_from_cache(
    symbol: str,
    info: dict[str, Any],
    quarterly: list[dict[str, Any]],
    dates: list[dict[str, Any]],
    *,
    cache_hit: bool,
    source: str,
) -> SymbolFundamentals:
    yoy = compute_eps_yoy(quarterly)
    sector = industry = None
    beta = current_price = None
    cagr = None
    raw: dict[str, Any] = {}
    if info.get("raw_json"):
        try:
            raw = json.loads(info["raw_json"]) if isinstance(info["raw_json"], str) else {}
            if yoy is None:
                yoy = _safe_float(raw.get("earningsQuarterlyGrowth"))
            sector = raw.get("sector")
            industry = raw.get("industry")
            beta = _safe_float(raw.get("beta"))
            current_price = _safe_float(raw.get("currentPrice"))
            cagr = _safe_float(raw.get("a_eps_cagr_hint"))
        except Exception:
            pass
    if cagr is None:
        cagr = compute_eps_cagr(quarterly, years=3)
    float_shares = _safe_float(info.get("float_shares"))
    market_cap = estimate_market_cap(_safe_float(info.get("market_cap")), float_shares, current_price)

    # Prefer typed columns; fall back to raw_json for pre-migration cache rows.
    shares_short = _safe_float(info.get("shares_short"))
    shares_short_prior_month = _safe_float(info.get("shares_short_prior_month"))
    date_short_interest = _yahoo_date(info.get("date_short_interest"))
    shares_short_previous_month_date = _yahoo_date(info.get("shares_short_previous_month_date"))
    short_ratio = _safe_float(info.get("short_ratio"))
    short_percent_of_float = _safe_float(info.get("short_percent_of_float"))
    shares_percent_shares_out = _safe_float(info.get("shares_percent_shares_out"))
    if raw:
        if shares_short is None:
            shares_short = _safe_float(raw.get("sharesShort"))
        if shares_short_prior_month is None:
            shares_short_prior_month = _safe_float(raw.get("sharesShortPriorMonth"))
        if date_short_interest is None:
            date_short_interest = _yahoo_date(raw.get("dateShortInterest"))
        if shares_short_previous_month_date is None:
            shares_short_previous_month_date = _yahoo_date(raw.get("sharesShortPreviousMonthDate"))
        if short_ratio is None:
            short_ratio = _safe_float(raw.get("shortRatio"))
        if short_percent_of_float is None:
            short_percent_of_float = _safe_float(raw.get("shortPercentOfFloat"))
        if shares_percent_shares_out is None:
            shares_percent_shares_out = _safe_float(raw.get("sharesPercentSharesOut"))

    return SymbolFundamentals(
        symbol=symbol,
        market_cap=market_cap,
        float_shares=float_shares,
        inst_pct=_safe_float(info.get("inst_pct")),
        roe=_safe_float(info.get("roe")),
        shares_short=shares_short,
        shares_short_prior_month=shares_short_prior_month,
        date_short_interest=date_short_interest,
        shares_short_previous_month_date=shares_short_previous_month_date,
        short_ratio=short_ratio,
        short_percent_of_float=short_percent_of_float,
        shares_percent_shares_out=shares_percent_shares_out,
        c_eps_yoy=yoy,
        a_eps_cagr=cagr,
        current_price=current_price,
        sector=str(sector) if sector else None,
        industry=str(industry) if industry else None,
        beta=beta,
        earnings_quarterly=quarterly,
        earnings_dates=dates,
        fetched_at=_parse_ts(info.get("fetched_at")),
        cache_hit=cache_hit,
        source=source,
    )


def get_symbol_fundamentals(
    symbol: str,
    *,
    db_path: str | Path | None = None,
    force_refresh: bool | None = None,
    refresh_missing_short: bool | None = None,
    lookback_years: float = 4.0,
    ttl: int | None = None,
    quiet: bool = False,
) -> SymbolFundamentals:
    """Return fundamentals for ``symbol``, fetching only when cache miss/stale."""
    sym = str(symbol or "").strip().upper()
    if not sym:
        return SymbolFundamentals(symbol="", source="EMPTY")

    p = ensure_schema(db_path)
    ttl_n = int(ttl if ttl is not None else ttl_days())
    force = bool(force_refresh) if force_refresh is not None else force_refresh_requested()
    want_short = (
        bool(refresh_missing_short)
        if refresh_missing_short is not None
        else refresh_missing_short_requested()
    )
    disabled = yfinance_disabled()

    con = _connect(p, read_only=False)
    try:
        info = _load_info_row(con, sym) or {}
        quarterly = _load_quarterly(con, sym)
        dates = _load_earnings_dates(con, sym)

        info_ok = bool(info) and _info_fresh(info.get("fetched_at"), ttl=ttl_n)
        earn_ok = (
            _quarterly_covers_lookback(quarterly, lookback_years)
            and _earnings_fetch_fresh(quarterly, dates, ttl=ttl_n)
        ) or (
            bool(quarterly or dates) and _earnings_fetch_fresh(quarterly, dates, ttl=ttl_n)
        )
        # Soft-miss: legacy rows never extracted short interest, or explicit
        # refresh-missing-short when typed short fields are still null.
        short_gap = bool(info) and (
            _short_interest_never_fetched(info)
            or (want_short and _short_fields_null(info))
        )
        # If we have any rows and fetch is fresh, treat as hit even if lookback short
        # (Yahoo often returns ≤5 annual / ≤5 quarterly columns).
        if (
            not force
            and not short_gap
            and info_ok
            and (earn_ok or (bool(info) and _earnings_fetch_fresh(quarterly, dates, ttl=ttl_n)))
        ):
            if not quiet:
                print(f"[YF_FUND] CACHE HIT {sym}", flush=True)
            return _bundle_from_cache(sym, info, quarterly, dates, cache_hit=True, source="CACHE")

        if not force and not short_gap and info_ok and quarterly and not dates:
            # Partial: enough for C/A soft-fill; still a cache hit for DNA
            if not quiet:
                print(f"[YF_FUND] CACHE HIT {sym} (info+eps; no earnings_dates)", flush=True)
            return _bundle_from_cache(sym, info, quarterly, dates, cache_hit=True, source="CACHE")

        if disabled:
            if not quiet:
                print(f"[YF_FUND] NO_YFINANCE — cache only for {sym}", flush=True)
            if info or quarterly or dates:
                return _bundle_from_cache(sym, info or {"fetched_at": None}, quarterly, dates, cache_hit=True, source="DISABLED")
            return SymbolFundamentals(symbol=sym, source="DISABLED")

        if short_gap and not force and not quiet:
            print(f"[YF_FUND] SHORT GAP {sym} — re-fetch (legacy/null short)", flush=True)

        # Need network
        last_err: Optional[BaseException] = None
        payload = None
        for attempt in range(3):
            try:
                if attempt:
                    _sleep_backoff(attempt)
                else:
                    _sleep_backoff(0)
                payload = _fetch_yahoo_payload(sym)
                break
            except Exception as e:
                last_err = e
                _sleep_backoff(attempt + 1)
        if payload is None:
            if not quiet:
                print(f"[YF_FUND] FETCH FAIL {sym}: {last_err}", flush=True)
            if info or quarterly or dates:
                return _bundle_from_cache(
                    sym, info or {"fetched_at": None}, quarterly, dates, cache_hit=True, source="CACHE"
                )
            return SymbolFundamentals(symbol=sym, source="EMPTY")

        now = datetime.now()
        _upsert_payload(con, sym, payload, now=now)
        # Re-read merged history (Yahoo window may be shorter than accumulated cache).
        quarterly2 = _load_quarterly(con, sym)
        dates2 = _load_earnings_dates(con, sym)
        annual_n = len(_load_annual(con, sym))
        short_n = len(_load_short_history(con, sym))
        if not quiet:
            print(
                f"[YF_FUND] FETCH {sym} q={len(quarterly2)} annual={annual_n} "
                f"dates={len(dates2)} short_hist={short_n}",
                flush=True,
            )
        info2 = {
            "market_cap": payload.get("market_cap"),
            "float_shares": payload.get("float_shares"),
            "inst_pct": payload.get("inst_pct"),
            "roe": payload.get("roe"),
            "shares_short": payload.get("shares_short"),
            "shares_short_prior_month": payload.get("shares_short_prior_month"),
            "date_short_interest": payload.get("date_short_interest"),
            "shares_short_previous_month_date": payload.get("shares_short_previous_month_date"),
            "short_ratio": payload.get("short_ratio"),
            "short_percent_of_float": payload.get("short_percent_of_float"),
            "shares_percent_shares_out": payload.get("shares_percent_shares_out"),
            "raw_json": json.dumps(payload.get("raw") or {}, default=str),
            "fetched_at": now,
        }
        return _bundle_from_cache(
            sym,
            info2,
            quarterly2,
            dates2,
            cache_hit=False,
            source="FETCH",
        )
    finally:
        con.close()


def ensure_symbols(
    symbols: Iterable[str],
    *,
    db_path: str | Path | None = None,
    force_refresh: bool | None = None,
    refresh_missing_short: bool | None = None,
    lookback_years: float = 4.0,
    ttl: int | None = None,
    quiet: bool = False,
) -> dict[str, SymbolFundamentals]:
    """Batch-friendly ensure: sequential with pacing (Yahoo rate limits)."""
    out: dict[str, SymbolFundamentals] = {}
    seen: set[str] = set()
    for raw in symbols:
        sym = str(raw or "").strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        out[sym] = get_symbol_fundamentals(
            sym,
            db_path=db_path,
            force_refresh=force_refresh,
            refresh_missing_short=refresh_missing_short,
            lookback_years=lookback_years,
            ttl=ttl,
            quiet=quiet,
        )
    return out


# ---------------------------------------------------------------------------
# DNA format helpers (CAN SLIM / Qull)
# ---------------------------------------------------------------------------


def fmt_pct_frac(x: Optional[float], *, digits: int = 4) -> str:
    if x is None or not isinstance(x, (int, float)) or x != x:
        return ""
    return f"{float(x):.{digits}f}"


def fmt_float_shares(x: Optional[float]) -> str:
    if x is None or not isinstance(x, (int, float)) or x != x or x <= 0:
        return "STUB"
    if x >= 1_000_000_000:
        return f"{x / 1_000_000_000:.2f}B"
    if x >= 1_000_000:
        return f"{x / 1_000_000:.2f}M"
    return f"{x:.0f}"


def fmt_inst_sponsor(x: Optional[float]) -> str:
    if x is None or not isinstance(x, (int, float)) or x != x:
        return "UNKNOWN"
    # Yahoo heldPercentInstitutions is 0–1
    pct = float(x) * 100.0 if abs(float(x)) <= 1.5 else float(x)
    return f"{pct:.1f}%"


def soft_status(has_data: bool) -> str:
    return "SOFT" if has_data else "STUB"


def canslim_dna_from_fundamentals(f: Optional[SymbolFundamentals]) -> dict[str, str]:
    """Map fundamentals → Closed CSV DNA cells + letter statuses (gates still off)."""
    if f is None or f.source in ("", "EMPTY") and f.c_eps_yoy is None and f.float_shares is None:
        return {
            "c_eps_yoy": "",
            "a_eps_cagr": "",
            "a_roe": "",
            "s_float": "STUB",
            "i_sponsor": "UNKNOWN",
            "c_status": "STUB",
            "a_status": "STUB",
            "i_status": "STUB",
        }
    has_c = f.c_eps_yoy is not None
    has_a = f.a_eps_cagr is not None or f.roe is not None
    has_i = f.inst_pct is not None
    return {
        "c_eps_yoy": fmt_pct_frac(f.c_eps_yoy),
        "a_eps_cagr": fmt_pct_frac(f.a_eps_cagr),
        "a_roe": fmt_pct_frac(f.roe),
        "s_float": fmt_float_shares(f.float_shares),
        "i_sponsor": fmt_inst_sponsor(f.inst_pct),
        "c_status": soft_status(has_c),
        "a_status": soft_status(has_a),
        "i_status": soft_status(has_i),
    }


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------


def _cli(argv: Optional[list[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="yfinance fundamentals → DuckDB cache")
    ap.add_argument("symbols", nargs="*", default=["NVDA", "AAPL", "TSLA"])
    ap.add_argument("--db", default="", help="DuckDB path (else FUNDAMENTALS_DB / default)")
    ap.add_argument(
        "--force-refresh",
        action="store_true",
        help="Ignore TTL and re-fetch info + earnings + short interest from Yahoo",
    )
    ap.add_argument(
        "--refresh-missing-short",
        action="store_true",
        help="Re-fetch when short fields are null even if TTL is still valid",
    )
    ap.add_argument("--ttl-days", type=int, default=-1)
    args = ap.parse_args(argv)
    db = args.db or None
    ttl = None if int(args.ttl_days) < 0 else int(args.ttl_days)
    p = resolve_fundamentals_db(db)
    print(f"[YF_FUND] db={p}", flush=True)
    ensure_schema(db)
    import duckdb as _duckdb

    for sym in args.symbols:
        b = get_symbol_fundamentals(
            sym,
            db_path=db,
            force_refresh=bool(args.force_refresh),
            refresh_missing_short=bool(args.refresh_missing_short),
            ttl=ttl,
        )
        dna = canslim_dna_from_fundamentals(b)
        con = _duckdb.connect(str(p), read_only=True)
        try:
            q_n = int(
                con.execute(
                    "SELECT COUNT(*) FROM yf_earnings_quarterly WHERE symbol = ?", [b.symbol]
                ).fetchone()[0]
            )
            a_n = int(
                con.execute(
                    "SELECT COUNT(*) FROM yf_earnings_annual WHERE symbol = ?", [b.symbol]
                ).fetchone()[0]
            )
            d_n = int(
                con.execute(
                    "SELECT COUNT(*) FROM yf_earnings_dates WHERE symbol = ?", [b.symbol]
                ).fetchone()[0]
            )
            sh = con.execute(
                """
                SELECT as_of, shares_short, short_percent_of_float, short_ratio, date_short_interest
                FROM yf_short_interest_history
                WHERE symbol = ?
                ORDER BY as_of DESC
                LIMIT 1
                """,
                [b.symbol],
            ).fetchone()
            sh_n = int(
                con.execute(
                    "SELECT COUNT(*) FROM yf_short_interest_history WHERE symbol = ?",
                    [b.symbol],
                ).fetchone()[0]
            )
        finally:
            con.close()
        sh_s = (
            f"as_of={sh[0]} shares_short={sh[1]} short%float={sh[2]} "
            f"daysToCover={sh[3]} settle={sh[4]}"
            if sh
            else "none"
        )
        print(
            f"  {b.symbol}: source={b.source} cache_hit={b.cache_hit} "
            f"C_EPS_YOY={dna['c_eps_yoy']} A_EPS_CAGR={dna['a_eps_cagr']} "
            f"A_ROE={dna['a_roe']} S_FLOAT={dna['s_float']} I_SPONSOR={dna['i_sponsor']} "
            f"short={b.shares_short} short%float={b.short_percent_of_float} "
            f"daysToCover={b.short_ratio} shortSettle={b.date_short_interest} "
            f"q={q_n} annual={a_n} dates={d_n} short_hist={sh_n} [{sh_s}]",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
