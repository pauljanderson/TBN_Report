#!/usr/bin/env python3
"""House fundamental scorecard v1.1 — research proxies (NOT Fidelity/S&P parity).

Four 1–100 peer-relative pillars approximating the *idea* of vendor scorecards:
Valuation, Quality, Growth Stability, Financial Health (+ equal-weight Composite).

v1.1 peer ranks: Yahoo **industry** first (N≥6), else **sector** (N≥8), else
all-universe. Dual ``score_*_sector`` columns keep v1 sector-only peers.
Also emits sector / industry ranking tables (mean/median by pillar).

Reuses ``stock_analysis/fundamentals_yfinance.py`` DuckDB cache for sector /
industry / ROE (Return on Equity) / EPS (Earnings Per Share) history, and
snapshots extra Yahoo ``Ticker.info`` multiples into
``drive/fund_scorecard_cache.duckdb`` so re-runs are cheap within TTL.

Latest rows live in ``yf_scorecard_metrics`` (overwrite-by-symbol). Dated
history for future point-in-time (PIT) joins accumulates in
``yf_scorecard_metrics_history`` / ``yf_scorecard_scores_history`` keyed by
``(symbol, as_of)``. DailyRun wires refresh via
``tools/fund_scorecard_dailyrun_refresh.py`` (research retention path — not
gold promotion of contaminated Closed overlays).

Examples
--------
  python tools/fund_scorecard_v1.py
  python tools/fund_scorecard_v1.py --universe drive/universes/MOM_universe.csv
  python tools/fund_scorecard_v1.py --cache-only --limit 50
  python tools/fund_scorecard_v1.py --force-refresh --workers 6
  python tools/fund_scorecard_dailyrun_refresh.py
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from stock_analysis.fundamentals_yfinance import (  # noqa: E402
    resolve_fundamentals_db,
    yfinance_disabled,
)

DEFAULT_SCORECARD_DB = _REPO / "drive" / "fund_scorecard_cache.duckdb"
DEFAULT_LATEST_DIR = _REPO / "drive" / "fund_scorecard_latest"
STAMP_DEFAULT = _REPO / "drive" / "paul_experiments" / "fund_scorecard_v1_industry_20260831"
LAST_OK_STAMP = _REPO / "drive" / "fund_scorecard_last_ok.json"

UNIVERSE_ALL = _REPO / "drive" / "universes" / "ALL_ohlc_universe.csv"
UNIVERSE_ADV2M = _REPO / "drive" / "universes" / "MOM_universe.csv"  # VZ liquid ADV$2m

MIN_INDUSTRY_N = 6  # industry peer group floor (5–8 band); else sector; else all-univ
MIN_SECTOR_N = 8  # sector peer group floor when industry too thin
MIN_GROWTH_OBS = 3  # need ≥3 YoY growth points for stability
SCORECARD_TTL_DAYS_DEFAULT = 7

_METRIC_COLS = (
    "symbol",
    "fetched_at",
    "sector",
    "industry",
    "trailing_pe",
    "forward_pe",
    "price_to_book",
    "price_to_sales",
    "ev_to_ebitda",
    "return_on_equity",
    "return_on_assets",
    "profit_margins",
    "operating_margins",
    "gross_margins",
    "free_cashflow",
    "operating_cashflow",
    "net_income_to_common",
    "debt_to_equity",
    "current_ratio",
    "quick_ratio",
    "ebitda",
    "total_debt",
    "interest_expense",
    "revenue_growth",
    "earnings_growth",
    "quote_type",
    "raw_json",
)

_SCORECARD_SCHEMA = """
CREATE TABLE IF NOT EXISTS yf_scorecard_metrics (
    symbol VARCHAR NOT NULL,
    fetched_at TIMESTAMP NOT NULL,
    sector VARCHAR,
    industry VARCHAR,
    trailing_pe DOUBLE,
    forward_pe DOUBLE,
    price_to_book DOUBLE,
    price_to_sales DOUBLE,
    ev_to_ebitda DOUBLE,
    return_on_equity DOUBLE,
    return_on_assets DOUBLE,
    profit_margins DOUBLE,
    operating_margins DOUBLE,
    gross_margins DOUBLE,
    free_cashflow DOUBLE,
    operating_cashflow DOUBLE,
    net_income_to_common DOUBLE,
    debt_to_equity DOUBLE,
    current_ratio DOUBLE,
    quick_ratio DOUBLE,
    ebitda DOUBLE,
    total_debt DOUBLE,
    interest_expense DOUBLE,
    revenue_growth DOUBLE,
    earnings_growth DOUBLE,
    quote_type VARCHAR,
    raw_json VARCHAR,
    PRIMARY KEY (symbol)
);
CREATE TABLE IF NOT EXISTS yf_scorecard_metrics_history (
    symbol VARCHAR NOT NULL,
    as_of DATE NOT NULL,
    fetched_at TIMESTAMP NOT NULL,
    sector VARCHAR,
    industry VARCHAR,
    trailing_pe DOUBLE,
    forward_pe DOUBLE,
    price_to_book DOUBLE,
    price_to_sales DOUBLE,
    ev_to_ebitda DOUBLE,
    return_on_equity DOUBLE,
    return_on_assets DOUBLE,
    profit_margins DOUBLE,
    operating_margins DOUBLE,
    gross_margins DOUBLE,
    free_cashflow DOUBLE,
    operating_cashflow DOUBLE,
    net_income_to_common DOUBLE,
    debt_to_equity DOUBLE,
    current_ratio DOUBLE,
    quick_ratio DOUBLE,
    ebitda DOUBLE,
    total_debt DOUBLE,
    interest_expense DOUBLE,
    revenue_growth DOUBLE,
    earnings_growth DOUBLE,
    quote_type VARCHAR,
    raw_json VARCHAR,
    PRIMARY KEY (symbol, as_of)
);
CREATE TABLE IF NOT EXISTS yf_scorecard_scores_history (
    symbol VARCHAR NOT NULL,
    as_of DATE NOT NULL,
    sector VARCHAR,
    industry VARCHAR,
    is_financial BOOLEAN,
    peer_mode VARCHAR,
    score_valuation DOUBLE,
    score_quality DOUBLE,
    score_growth_stability DOUBLE,
    score_financial_health DOUBLE,
    score_composite DOUBLE,
    score_valuation_sector DOUBLE,
    score_quality_sector DOUBLE,
    score_growth_stability_sector DOUBLE,
    score_financial_health_sector DOUBLE,
    score_composite_sector DOUBLE,
    n_pillars INTEGER,
    pe DOUBLE,
    pe_source VARCHAR,
    pb DOUBLE,
    ps DOUBLE,
    ev_ebitda DOUBLE,
    roe DOUBLE,
    roa DOUBLE,
    profit_margin DOUBLE,
    operating_margin DOUBLE,
    fcf_conversion DOUBLE,
    eps_growth_vol DOUBLE,
    debt_to_equity DOUBLE,
    current_ratio DOUBLE,
    interest_coverage DOUBLE,
    earnings_growth DOUBLE,
    revenue_growth DOUBLE,
    scored_at TIMESTAMP NOT NULL,
    PRIMARY KEY (symbol, as_of)
);
"""

# Yahoo sector label used for bank/insurer special-case
FINANCIAL_SECTOR = "Financial Services"


def _safe_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        if isinstance(v, (float, int)) and (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
            return None
        x = float(v)
        if math.isnan(x) or math.isinf(x):
            return None
        return x
    except (TypeError, ValueError):
        return None


def _load_universe(path: Path) -> list[str]:
    syms: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        # allow Symbol,header or bare ticker
        if "," in s and s.lower().startswith("symbol"):
            continue
        syms.append(s.split(",")[0].strip().upper())
    # de-dupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for s in syms:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _connect(db_path: Path, *, read_only: bool = False):
    import duckdb

    db_path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(db_path), read_only=read_only)


def _connect_fund_readonly(db_path: Path):
    """Open fund cache read-only; if Drive-locked, copy to temp and open that."""
    import shutil
    import tempfile

    import duckdb

    try:
        return duckdb.connect(str(db_path), read_only=True), None
    except Exception as exc:
        msg = str(exc).lower()
        if "used by another process" not in msg and "cannot open file" not in msg:
            raise
        tmp = Path(tempfile.gettempdir()) / f"fundamentals_cache_ro_{os.getpid()}.duckdb"
        print(f"[fund-sc] fund DB locked ({exc}); copying to {tmp}")
        shutil.copy2(db_path, tmp)
        return duckdb.connect(str(tmp), read_only=True), tmp


def ensure_scorecard_schema(db_path: Path) -> None:
    con = _connect(db_path, read_only=False)
    try:
        con.execute(_SCORECARD_SCHEMA)
    finally:
        con.close()


def scorecard_ttl_days(default: int = SCORECARD_TTL_DAYS_DEFAULT) -> int:
    """Env ``FUND_SCORECARD_TTL_DAYS`` (fallback ``YF_FUND_TTL_DAYS``), else default."""
    for key in ("FUND_SCORECARD_TTL_DAYS", "YF_FUND_TTL_DAYS"):
        raw = str(os.environ.get(key, "") or "").strip()
        if not raw:
            continue
        try:
            return max(0, int(float(raw)))
        except (TypeError, ValueError):
            continue
    return int(default)


def _as_of_from_fetched(fetched_at: Any, *, fallback: Optional[date] = None) -> date:
    if isinstance(fetched_at, datetime):
        return fetched_at.date()
    if isinstance(fetched_at, date) and not isinstance(fetched_at, datetime):
        return fetched_at
    try:
        return pd.Timestamp(fetched_at).date()
    except Exception:
        return fallback or datetime.utcnow().date()


def _parse_info_to_metrics(symbol: str, info: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    ebitda = _safe_float(info.get("ebitda"))
    interest_expense = _safe_float(
        info.get("interestExpense") or info.get("interestExpenseNonOperating")
    )
    return {
        "symbol": symbol,
        "fetched_at": now,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "trailing_pe": _safe_float(info.get("trailingPE")),
        "forward_pe": _safe_float(info.get("forwardPE")),
        "price_to_book": _safe_float(info.get("priceToBook")),
        "price_to_sales": _safe_float(info.get("priceToSalesTrailing12Months")),
        "ev_to_ebitda": _safe_float(info.get("enterpriseToEbitda")),
        "return_on_equity": _safe_float(info.get("returnOnEquity")),
        "return_on_assets": _safe_float(info.get("returnOnAssets")),
        "profit_margins": _safe_float(info.get("profitMargins")),
        "operating_margins": _safe_float(info.get("operatingMargins")),
        "gross_margins": _safe_float(info.get("grossMargins")),
        "free_cashflow": _safe_float(info.get("freeCashflow")),
        "operating_cashflow": _safe_float(info.get("operatingCashflow")),
        "net_income_to_common": _safe_float(info.get("netIncomeToCommon")),
        "debt_to_equity": _safe_float(info.get("debtToEquity")),
        "current_ratio": _safe_float(info.get("currentRatio")),
        "quick_ratio": _safe_float(info.get("quickRatio")),
        "ebitda": ebitda,
        "total_debt": _safe_float(info.get("totalDebt")),
        "interest_expense": interest_expense,
        "revenue_growth": _safe_float(info.get("revenueGrowth")),
        "earnings_growth": _safe_float(info.get("earningsGrowth")),
        "quote_type": info.get("quoteType"),
        "raw_json": json.dumps({k: info.get(k) for k in sorted(info.keys()) if k in (
            "trailingPE", "forwardPE", "priceToBook", "priceToSalesTrailing12Months",
            "enterpriseToEbitda", "returnOnEquity", "returnOnAssets", "profitMargins",
            "operatingMargins", "grossMargins", "freeCashflow", "operatingCashflow",
            "netIncomeToCommon", "debtToEquity", "currentRatio", "quickRatio", "ebitda",
            "totalDebt", "interestExpense", "revenueGrowth", "earningsGrowth",
            "sector", "industry", "quoteType", "marketCap",
        )}, default=str),
    }


def _fetch_yahoo_info(symbol: str) -> dict[str, Any]:
    import yfinance as yf

    try:
        from yfinance.exceptions import YFRateLimitError
    except Exception:  # noqa: BLE001
        YFRateLimitError = Exception  # type: ignore

    t = yf.Ticker(symbol)
    try:
        info = dict(getattr(t, "info", None) or {})
    except YFRateLimitError:
        raise
    except Exception:
        info = {}
    return info


def _upsert_scorecard_row(con, row: dict[str, Any], *, as_of: Optional[date] = None) -> None:
    """Write latest overwrite row + dated metrics history (PIT retention)."""
    cols = list(_METRIC_COLS)
    placeholders = ", ".join(["?"] * len(cols))
    col_sql = ", ".join(cols)
    vals = [row.get(c) for c in cols]
    con.execute(
        f"INSERT OR REPLACE INTO yf_scorecard_metrics ({col_sql}) VALUES ({placeholders})",
        vals,
    )
    hist_as_of = as_of or _as_of_from_fetched(row.get("fetched_at"))
    hist_cols = ["symbol", "as_of"] + [c for c in cols if c != "symbol"]
    hist_sql = ", ".join(hist_cols)
    hist_ph = ", ".join(["?"] * len(hist_cols))
    hist_vals = [row.get("symbol"), hist_as_of] + [row.get(c) for c in cols if c != "symbol"]
    con.execute(
        f"INSERT OR REPLACE INTO yf_scorecard_metrics_history ({hist_sql}) VALUES ({hist_ph})",
        hist_vals,
    )


def snapshot_metrics_history_from_latest(
    scorecard_db: Path,
    symbols: Optional[list[str]] = None,
    *,
    as_of: Optional[date] = None,
) -> int:
    """Copy current ``yf_scorecard_metrics`` into history for ``as_of`` (idempotent).

    Used on DailyRun days when Yahoo TTL skips fetch so PIT still gets a dated row.
    """
    ensure_scorecard_schema(scorecard_db)
    day = as_of or datetime.utcnow().date()
    con = _connect(scorecard_db, read_only=False)
    try:
        metric_cols = [c for c in _METRIC_COLS if c != "symbol"]
        col_sql = ", ".join(metric_cols)
        if symbols:
            n = 0
            for i in range(0, len(symbols), 400):
                chunk = symbols[i : i + 400]
                qmarks = ", ".join(["?"] * len(chunk))
                con.execute(
                    f"""
                    INSERT OR REPLACE INTO yf_scorecard_metrics_history
                    (symbol, as_of, {col_sql})
                    SELECT symbol, ? AS as_of, {col_sql}
                    FROM yf_scorecard_metrics
                    WHERE symbol IN ({qmarks})
                    """,
                    [day, *chunk],
                )
                n += len(chunk)
            return n
        con.execute(
            f"""
            INSERT OR REPLACE INTO yf_scorecard_metrics_history
            (symbol, as_of, {col_sql})
            SELECT symbol, ? AS as_of, {col_sql}
            FROM yf_scorecard_metrics
            """,
            [day],
        )
        return int(con.execute("SELECT COUNT(*) FROM yf_scorecard_metrics").fetchone()[0])
    finally:
        con.close()


_SCORE_HISTORY_COLS = (
    "symbol",
    "as_of",
    "sector",
    "industry",
    "is_financial",
    "peer_mode",
    "score_valuation",
    "score_quality",
    "score_growth_stability",
    "score_financial_health",
    "score_composite",
    "score_valuation_sector",
    "score_quality_sector",
    "score_growth_stability_sector",
    "score_financial_health_sector",
    "score_composite_sector",
    "n_pillars",
    "pe",
    "pe_source",
    "pb",
    "ps",
    "ev_ebitda",
    "roe",
    "roa",
    "profit_margin",
    "operating_margin",
    "fcf_conversion",
    "eps_growth_vol",
    "debt_to_equity",
    "current_ratio",
    "interest_coverage",
    "earnings_growth",
    "revenue_growth",
    "scored_at",
)


def persist_scores_history(
    scorecard_db: Path,
    scored: pd.DataFrame,
    *,
    as_of: Optional[date] = None,
    scored_at: Optional[datetime] = None,
) -> int:
    """Upsert pillar scores into ``yf_scorecard_scores_history`` for ``as_of``."""
    if scored is None or scored.empty:
        return 0
    ensure_scorecard_schema(scorecard_db)
    day = as_of or datetime.utcnow().date()
    now = scored_at or datetime.utcnow()
    con = _connect(scorecard_db, read_only=False)
    try:
        cols = list(_SCORE_HISTORY_COLS)
        placeholders = ", ".join(["?"] * len(cols))
        col_sql = ", ".join(cols)
        n = 0
        for _, r in scored.iterrows():
            sym = str(r.get("symbol") or "").strip().upper()
            if not sym:
                continue
            row = {c: r.get(c) if c in scored.columns else None for c in cols}
            row["symbol"] = sym
            row["as_of"] = day
            row["scored_at"] = now
            # peer_mode: prefer valuation peer when present
            if row.get("peer_mode") is None:
                for k in ("peer_pe", "peer_roe", "peer_eps_growth_vol"):
                    if k in scored.columns and pd.notna(r.get(k)):
                        row["peer_mode"] = r.get(k)
                        break
            con.execute(
                f"INSERT OR REPLACE INTO yf_scorecard_scores_history ({col_sql}) VALUES ({placeholders})",
                [row.get(c) for c in cols],
            )
            n += 1
        return n
    finally:
        con.close()


def scores_as_of(
    scorecard_db: Path,
    symbol: str,
    entry_date: date | str | datetime,
) -> Optional[dict[str, Any]]:
    """Latest score history row with ``as_of <= entry_date`` (future PIT join helper)."""
    ensure_scorecard_schema(scorecard_db)
    if isinstance(entry_date, datetime):
        target = entry_date.date()
    elif isinstance(entry_date, date):
        target = entry_date
    else:
        target = pd.Timestamp(entry_date).date()
    sym = str(symbol).strip().upper()
    con = _connect(scorecard_db, read_only=True)
    try:
        cols = ", ".join(_SCORE_HISTORY_COLS)
        row = con.execute(
            f"""
            SELECT {cols}
            FROM yf_scorecard_scores_history
            WHERE symbol = ? AND as_of <= ?
            ORDER BY as_of DESC
            LIMIT 1
            """,
            [sym, target],
        ).fetchone()
        if not row:
            return None
        names = [d[0] for d in con.description]
        return dict(zip(names, row))
    finally:
        con.close()


def history_coverage(scorecard_db: Path) -> dict[str, Any]:
    """Quick counts for DailyRun status / stamp docs."""
    ensure_scorecard_schema(scorecard_db)
    con = _connect(scorecard_db, read_only=True)
    try:
        latest_n = int(con.execute("SELECT COUNT(*) FROM yf_scorecard_metrics").fetchone()[0])
        metrics_hist_n = int(
            con.execute("SELECT COUNT(*) FROM yf_scorecard_metrics_history").fetchone()[0]
        )
        scores_hist_n = int(
            con.execute("SELECT COUNT(*) FROM yf_scorecard_scores_history").fetchone()[0]
        )
        min_as_of = con.execute(
            "SELECT MIN(as_of) FROM yf_scorecard_scores_history"
        ).fetchone()[0]
        max_as_of = con.execute(
            "SELECT MAX(as_of) FROM yf_scorecard_scores_history"
        ).fetchone()[0]
        distinct_days = int(
            con.execute(
                "SELECT COUNT(DISTINCT as_of) FROM yf_scorecard_scores_history"
            ).fetchone()[0]
        )
        return {
            "latest_metrics_n": latest_n,
            "metrics_history_n": metrics_hist_n,
            "scores_history_n": scores_hist_n,
            "scores_as_of_min": str(min_as_of) if min_as_of is not None else None,
            "scores_as_of_max": str(max_as_of) if max_as_of is not None else None,
            "scores_distinct_days": distinct_days,
        }
    finally:
        con.close()


def _load_scorecard_cache(con, symbols: list[str]) -> dict[str, dict[str, Any]]:
    if not symbols:
        return {}
    # chunk IN lists
    out: dict[str, dict[str, Any]] = {}
    cols = (
        "symbol, fetched_at, sector, industry, trailing_pe, forward_pe, price_to_book, "
        "price_to_sales, ev_to_ebitda, return_on_equity, return_on_assets, profit_margins, "
        "operating_margins, gross_margins, free_cashflow, operating_cashflow, "
        "net_income_to_common, debt_to_equity, current_ratio, quick_ratio, ebitda, "
        "total_debt, interest_expense, revenue_growth, earnings_growth, quote_type"
    )
    for i in range(0, len(symbols), 400):
        chunk = symbols[i : i + 400]
        qmarks = ", ".join(["?"] * len(chunk))
        rows = con.execute(
            f"SELECT {cols} FROM yf_scorecard_metrics WHERE symbol IN ({qmarks})",
            chunk,
        ).fetchall()
        names = [d[0] for d in con.description]
        for r in rows:
            d = dict(zip(names, r))
            out[str(d["symbol"]).upper()] = d
    return out


def _load_fund_info_fallback(con, symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Sector / ROE / growth hints from yf_symbol_info.raw_json when scorecard row thin."""
    out: dict[str, dict[str, Any]] = {}
    for i in range(0, len(symbols), 400):
        chunk = symbols[i : i + 400]
        qmarks = ", ".join(["?"] * len(chunk))
        rows = con.execute(
            f"SELECT symbol, roe, raw_json FROM yf_symbol_info WHERE symbol IN ({qmarks})",
            chunk,
        ).fetchall()
        for sym, roe, rj in rows:
            d: dict[str, Any] = {"symbol": sym, "return_on_equity": _safe_float(roe)}
            try:
                raw = json.loads(rj) if rj else {}
            except json.JSONDecodeError:
                raw = {}
            d["sector"] = raw.get("sector")
            d["industry"] = raw.get("industry")
            d["earnings_growth"] = _safe_float(raw.get("earningsGrowth"))
            d["revenue_growth"] = _safe_float(raw.get("revenueGrowth"))  # usually absent
            out[str(sym).upper()] = d
    return out


def _load_eps_series(con, symbols: list[str]) -> dict[str, dict[str, list[tuple]]]:
    """Annual + quarterly EPS for growth-stability."""
    annual: dict[str, list[tuple]] = {s: [] for s in symbols}
    quarterly: dict[str, list[tuple]] = {s: [] for s in symbols}
    for i in range(0, len(symbols), 400):
        chunk = symbols[i : i + 400]
        qmarks = ", ".join(["?"] * len(chunk))
        for table, dest in (
            ("yf_earnings_annual", annual),
            ("yf_earnings_quarterly", quarterly),
        ):
            rows = con.execute(
                f"SELECT symbol, period_end, eps_actual FROM {table} "
                f"WHERE symbol IN ({qmarks}) AND eps_actual IS NOT NULL "
                f"ORDER BY symbol, period_end",
                chunk,
            ).fetchall()
            for sym, pe, eps in rows:
                dest.setdefault(str(sym).upper(), []).append((pe, float(eps)))
    return {"annual": annual, "quarterly": quarterly}


def _yoy_growths(series: list[tuple], *, lag: int = 1) -> list[float]:
    """YoY (or lag-period) growth rates; skip if base ~0."""
    if len(series) < lag + 1:
        return []
    series = sorted(series, key=lambda x: x[0])
    out: list[float] = []
    for i in range(lag, len(series)):
        _, cur = series[i]
        _, prev = series[i - lag]
        if prev is None or abs(prev) < 1e-9:
            continue
        out.append((cur - prev) / abs(prev))
    return out


def growth_stability_vol(annual: list[tuple], quarterly: list[tuple]) -> Optional[float]:
    """Lower = more stable. Prefer annual YoY; else quarterly YoY (lag=4)."""
    g = _yoy_growths(annual, lag=1)
    if len(g) < MIN_GROWTH_OBS:
        g = _yoy_growths(quarterly, lag=4)
    if len(g) < MIN_GROWTH_OBS:
        return None
    # clip extreme growth for stdev stability (still research proxy)
    arr = np.clip(np.asarray(g, dtype=float), -5.0, 5.0)
    return float(np.std(arr, ddof=1)) if len(arr) >= 2 else None


def _interest_coverage(ebitda: Optional[float], interest_expense: Optional[float]) -> Optional[float]:
    if ebitda is None or interest_expense is None:
        return None
    if abs(interest_expense) < 1e-6:
        return None
    # interest expense often negative on statements; use abs
    return ebitda / abs(interest_expense)


def _fcf_conversion(fcf: Optional[float], ni: Optional[float]) -> Optional[float]:
    if fcf is None or ni is None or abs(ni) < 1e-6:
        return None
    return fcf / abs(ni)


def _fresh(fetched_at: Any, *, ttl: int) -> bool:
    if fetched_at is None:
        return False
    try:
        if isinstance(fetched_at, datetime):
            ts = fetched_at
        else:
            ts = pd.Timestamp(fetched_at).to_pydatetime()
        if ts.tzinfo is not None:
            ts = ts.replace(tzinfo=None)
        return (datetime.utcnow() - ts) <= timedelta(days=ttl)
    except Exception:
        return False


def refresh_scorecard_metrics(
    symbols: list[str],
    scorecard_db: Path,
    *,
    force: bool = False,
    cache_only: bool = False,
    ttl: int = SCORECARD_TTL_DAYS_DEFAULT,
    workers: int = 6,
) -> dict[str, dict[str, Any]]:
    """Fetch/cache Yahoo multiples into a *separate* DuckDB (avoids Drive lock on fund DB)."""
    ensure_scorecard_schema(scorecard_db)
    con = _connect(scorecard_db, read_only=False)
    try:
        cached = _load_scorecard_cache(con, symbols)
        need = [
            s
            for s in symbols
            if force or s not in cached or not _fresh(cached[s].get("fetched_at"), ttl=ttl)
        ]
        skip_fetch = cache_only or yfinance_disabled()
        print(
            f"[fund-sc] scorecard rows in DB={len(cached)} "
            f"stale_or_missing={len(need)} cache_only={skip_fetch}"
        )
        if skip_fetch:
            need = []
        if need:
            now = datetime.utcnow()
            ok = fail = 0

            def _one(sym: str) -> tuple[str, Optional[dict[str, Any]], bool]:
                """Returns (symbol, row|None, rate_limited)."""
                try:
                    info = _fetch_yahoo_info(sym)
                    if not info:
                        return sym, None, False
                    return sym, _parse_info_to_metrics(sym, info, now=now), False
                except Exception as exc:
                    if "Rate" in type(exc).__name__ or "Rate limited" in str(exc):
                        return sym, None, True
                    return sym, None, False

            with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
                futs = {ex.submit(_one, s): s for s in need}
                done_n = 0
                rate_hits = 0
                for fut in as_completed(futs):
                    sym, row, rate_limited = fut.result()
                    done_n += 1
                    if rate_limited:
                        rate_hits += 1
                        fail += 1
                    elif row is None:
                        fail += 1
                    else:
                        _upsert_scorecard_row(con, row)
                        cached[sym] = row
                        ok += 1
                    if done_n % 50 == 0 or done_n == len(need):
                        print(
                            f"[fund-sc] fetch progress {done_n}/{len(need)} "
                            f"ok={ok} fail={fail} rate_limit_hits={rate_hits}"
                        )
                if rate_hits:
                    print(
                        "[fund-sc] WARNING: Yahoo rate-limited during fetch; "
                        "re-run later with default TTL to backfill missing rows."
                    )
        return cached
    finally:
        con.close()


def _clean_valuation(v: Optional[float], *, max_abs: float = 200.0) -> Optional[float]:
    """Drop non-positive / absurd multiples for peer ranks."""
    if v is None or v <= 0 or v > max_abs:
        return None
    return v


def build_metric_frame(
    symbols: list[str],
    db_path: Path,
    scorecard: dict[str, dict[str, Any]],
) -> pd.DataFrame:
    con, tmp_copy = _connect_fund_readonly(db_path)
    try:
        fallback = _load_fund_info_fallback(con, symbols)
        eps = _load_eps_series(con, symbols)
        # latest price from fund raw_json for house P/E proxy
        prices: dict[str, float] = {}
        for i in range(0, len(symbols), 400):
            chunk = symbols[i : i + 400]
            qmarks = ", ".join(["?"] * len(chunk))
            for sym, rj in con.execute(
                f"SELECT symbol, raw_json FROM yf_symbol_info WHERE symbol IN ({qmarks})",
                chunk,
            ).fetchall():
                try:
                    raw = json.loads(rj) if rj else {}
                except json.JSONDecodeError:
                    raw = {}
                px = _safe_float(raw.get("currentPrice"))
                if px is not None and px > 0:
                    prices[str(sym).upper()] = px
    finally:
        con.close()
        if tmp_copy is not None:
            try:
                tmp_copy.unlink(missing_ok=True)
            except Exception:
                pass

    rows: list[dict[str, Any]] = []
    for sym in symbols:
        sc = scorecard.get(sym) or {}
        fb = fallback.get(sym) or {}
        sector = sc.get("sector") or fb.get("sector")
        industry = sc.get("industry") or fb.get("industry")
        is_fin = str(sector or "") == FINANCIAL_SECTOR

        pe = _clean_valuation(sc.get("trailing_pe") or sc.get("forward_pe"), max_abs=250)
        pe_source = "yahoo" if pe is not None else ""
        if pe is None:
            # House proxy: price / latest annual EPS (not vendor trailing PE)
            ann = eps["annual"].get(sym, [])
            if ann and sym in prices:
                last_eps = sorted(ann, key=lambda x: x[0])[-1][1]
                if last_eps and last_eps > 0:
                    pe = _clean_valuation(prices[sym] / last_eps, max_abs=250)
                    if pe is not None:
                        pe_source = "house_price_eps"

        pb = _clean_valuation(sc.get("price_to_book"), max_abs=50)
        ps = _clean_valuation(sc.get("price_to_sales"), max_abs=80)
        eve = None if is_fin else _clean_valuation(sc.get("ev_to_ebitda"), max_abs=80)

        roe = _safe_float(sc.get("return_on_equity"))
        if roe is None:
            roe = _safe_float(fb.get("return_on_equity"))
        roa = _safe_float(sc.get("return_on_assets"))
        pm = None if is_fin else _safe_float(sc.get("profit_margins"))
        om = None if is_fin else _safe_float(sc.get("operating_margins"))
        fcf_conv = None
        if not is_fin:
            fcf_conv = _fcf_conversion(
                _safe_float(sc.get("free_cashflow")),
                _safe_float(sc.get("net_income_to_common")),
            )

        gvol = growth_stability_vol(
            eps["annual"].get(sym, []),
            eps["quarterly"].get(sym, []),
        )

        de = None if is_fin else _safe_float(sc.get("debt_to_equity"))
        cr = None if is_fin else _safe_float(sc.get("current_ratio"))
        icov = None
        if not is_fin:
            icov = _interest_coverage(
                _safe_float(sc.get("ebitda")),
                _safe_float(sc.get("interest_expense")),
            )

        rows.append(
            {
                "symbol": sym,
                "sector": sector or "",
                "industry": industry or "",
                "is_financial": bool(is_fin),
                "pe": pe,
                "pe_source": pe_source,
                "pb": pb,
                "ps": ps,
                "ev_ebitda": eve,
                "roe": roe,
                "roa": roa,
                "profit_margin": pm,
                "operating_margin": om,
                "fcf_conversion": fcf_conv,
                "eps_growth_vol": gvol,
                "debt_to_equity": de,
                "current_ratio": cr,
                "interest_coverage": icov,
                "earnings_growth": _safe_float(sc.get("earnings_growth") or fb.get("earnings_growth")),
                "revenue_growth": _safe_float(sc.get("revenue_growth") or fb.get("revenue_growth")),
                "has_scorecard_row": sym in scorecard,
                "has_fund_info": sym in fallback,
            }
        )
    return pd.DataFrame(rows)


def _pct_rank(vals: pd.Series, hib: bool) -> pd.Series:
    """Percentile 0–100 within vals; NaN stays NaN. Single valid → 50."""
    valid = vals.dropna()
    if valid.empty:
        return pd.Series(np.nan, index=vals.index)
    if len(valid) == 1:
        out = pd.Series(np.nan, index=vals.index)
        out.loc[valid.index] = 50.0
        return out
    # higher_is_better → ascending rank so large values get high percentile
    r = valid.rank(method="average", ascending=hib)
    pct = (r - 1) / (len(valid) - 1) * 100.0
    out = pd.Series(np.nan, index=vals.index)
    out.loc[pct.index] = pct
    return out


def _peer_percentile_grouped(
    df: pd.DataFrame,
    col: str,
    group_col: str,
    *,
    higher_is_better: bool,
    min_n: int,
    mode_label: str,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Rank within group when group size OK; else mark pending.

    Returns (scores, modes, pending_mask). Pending rows keep NaN scores.
    """
    scores = pd.Series(np.nan, index=df.index, dtype=float)
    modes = pd.Series("", index=df.index, dtype=object)
    pending = pd.Series(True, index=df.index, dtype=bool)
    gkey = df[group_col].fillna("").replace("", "_NONE_")
    min_valid = max(3, min_n // 2)
    for gname, idx in df.groupby(gkey).groups.items():
        sub = df.loc[list(idx)]
        n_valid = int(sub[col].notna().sum())
        use = (
            gname not in ("", "_NONE_")
            and len(sub) >= min_n
            and n_valid >= min_valid
        )
        if use:
            scores.loc[sub.index] = _pct_rank(sub[col], higher_is_better)
            modes.loc[sub.index] = mode_label
            pending.loc[sub.index] = False
    return scores, modes, pending


def _peer_percentile(
    df: pd.DataFrame,
    col: str,
    *,
    higher_is_better: bool,
    min_industry_n: int = MIN_INDUSTRY_N,
    min_sector_n: int = MIN_SECTOR_N,
) -> tuple[pd.Series, pd.Series]:
    """Primary peer rank: industry → sector → all-universe.

    peer_mode values: ``industry`` | ``sector`` | ``all_univ``.
    """
    scores = pd.Series(np.nan, index=df.index, dtype=float)
    modes = pd.Series("", index=df.index, dtype=object)

    ind_s, ind_m, ind_pend = _peer_percentile_grouped(
        df, col, "industry",
        higher_is_better=higher_is_better,
        min_n=min_industry_n,
        mode_label="industry",
    )
    scores.loc[~ind_pend] = ind_s.loc[~ind_pend]
    modes.loc[~ind_pend] = ind_m.loc[~ind_pend]

    remain = ind_pend
    if remain.any():
        sub_df = df.loc[remain]
        sec_s, sec_m, sec_pend = _peer_percentile_grouped(
            sub_df, col, "sector",
            higher_is_better=higher_is_better,
            min_n=min_sector_n,
            mode_label="sector",
        )
        filled = ~sec_pend
        if filled.any():
            idx = filled[filled].index
            scores.loc[idx] = sec_s.loc[idx]
            modes.loc[idx] = sec_m.loc[idx]
        still = remain & modes.eq("")
        if still.any():
            all_pct = _pct_rank(df[col], higher_is_better)
            scores.loc[still] = all_pct.loc[still]
            modes.loc[still] = "all_univ"

    missing_mode = modes == ""
    if missing_mode.any():
        all_pct = _pct_rank(df[col], higher_is_better)
        scores.loc[missing_mode] = all_pct.loc[missing_mode]
        modes.loc[missing_mode] = "all_univ"

    return scores, modes


def _peer_percentile_sector_only(
    df: pd.DataFrame,
    col: str,
    *,
    higher_is_better: bool,
    min_sector_n: int = MIN_SECTOR_N,
) -> tuple[pd.Series, pd.Series]:
    """Sector → all-univ only (v1 continuity / dual columns)."""
    scores, modes, pending = _peer_percentile_grouped(
        df, col, "sector",
        higher_is_better=higher_is_better,
        min_n=min_sector_n,
        mode_label="sector",
    )
    if pending.any():
        all_pct = _pct_rank(df[col], higher_is_better)
        scores.loc[pending] = all_pct.loc[pending]
        modes.loc[pending] = "all_univ"
    return scores, modes


def score_pillars(
    df: pd.DataFrame,
    *,
    min_industry_n: int = MIN_INDUSTRY_N,
    min_sector_n: int = MIN_SECTOR_N,
) -> pd.DataFrame:
    """Score pillars with industry-first peers; also emit sector-only dual columns."""
    out = df.copy()
    kw = dict(min_industry_n=min_industry_n, min_sector_n=min_sector_n)

    def _mean_pillar(pct_cols: list[str]) -> pd.Series:
        return out[pct_cols].mean(axis=1, skipna=True)

    # Valuation: cheap → high (higher_is_better=False on the raw multiple)
    val_cols: list[str] = []
    val_sec_cols: list[str] = []
    for col, hib in (("pe", False), ("pb", False), ("ps", False), ("ev_ebitda", False)):
        s, m = _peer_percentile(out, col, higher_is_better=hib, **kw)
        out[f"pct_{col}"] = s
        out[f"peer_{col}"] = m
        val_cols.append(f"pct_{col}")
        ss, sm = _peer_percentile_sector_only(
            out, col, higher_is_better=hib, min_sector_n=min_sector_n
        )
        out[f"pct_{col}_sector"] = ss
        out[f"peer_{col}_sector"] = sm
        val_sec_cols.append(f"pct_{col}_sector")
    out["score_valuation"] = _mean_pillar(val_cols)
    out["score_valuation_sector"] = _mean_pillar(val_sec_cols)

    # Quality
    q_specs = [
        ("roe", True),
        ("roa", True),
        ("profit_margin", True),
        ("operating_margin", True),
        ("fcf_conversion", True),
    ]
    q_cols: list[str] = []
    q_sec_cols: list[str] = []
    for col, hib in q_specs:
        s, m = _peer_percentile(out, col, higher_is_better=hib, **kw)
        out[f"pct_{col}"] = s
        out[f"peer_{col}"] = m
        q_cols.append(f"pct_{col}")
        ss, sm = _peer_percentile_sector_only(
            out, col, higher_is_better=hib, min_sector_n=min_sector_n
        )
        out[f"pct_{col}_sector"] = ss
        out[f"peer_{col}_sector"] = sm
        q_sec_cols.append(f"pct_{col}_sector")
    out["score_quality"] = _mean_pillar(q_cols)
    out["score_quality_sector"] = _mean_pillar(q_sec_cols)

    # Growth Stability: low EPS growth vol → high
    s, m = _peer_percentile(out, "eps_growth_vol", higher_is_better=False, **kw)
    out["pct_eps_growth_vol"] = s
    out["peer_eps_growth_vol"] = m
    out["score_growth_stability"] = s
    ss, sm = _peer_percentile_sector_only(
        out, "eps_growth_vol", higher_is_better=False, min_sector_n=min_sector_n
    )
    out["pct_eps_growth_vol_sector"] = ss
    out["peer_eps_growth_vol_sector"] = sm
    out["score_growth_stability_sector"] = ss

    # Financial Health
    h_specs = [
        ("debt_to_equity", False),
        ("current_ratio", True),
        ("interest_coverage", True),
    ]
    h_cols: list[str] = []
    h_sec_cols: list[str] = []
    for col, hib in h_specs:
        s, m = _peer_percentile(out, col, higher_is_better=hib, **kw)
        out[f"pct_{col}"] = s
        out[f"peer_{col}"] = m
        h_cols.append(f"pct_{col}")
        ss, sm = _peer_percentile_sector_only(
            out, col, higher_is_better=hib, min_sector_n=min_sector_n
        )
        out[f"pct_{col}_sector"] = ss
        out[f"peer_{col}_sector"] = sm
        h_sec_cols.append(f"pct_{col}_sector")
    out["score_financial_health"] = _mean_pillar(h_cols)
    out["score_financial_health_sector"] = _mean_pillar(h_sec_cols)
    # Banks/financials: leave health null (already missing metrics) + flag
    out.loc[out["is_financial"], "score_financial_health"] = np.nan
    out.loc[out["is_financial"], "score_financial_health_sector"] = np.nan

    pillar_cols = [
        "score_valuation",
        "score_quality",
        "score_growth_stability",
        "score_financial_health",
    ]
    pillar_sec = [
        "score_valuation_sector",
        "score_quality_sector",
        "score_growth_stability_sector",
        "score_financial_health_sector",
    ]
    out["score_composite"] = out[pillar_cols].mean(axis=1, skipna=True)
    out["score_composite_sector"] = out[pillar_sec].mean(axis=1, skipna=True)
    out["n_pillars"] = out[pillar_cols].notna().sum(axis=1)
    out["n_val_metrics"] = out[val_cols].notna().sum(axis=1)
    out["n_qual_metrics"] = out[q_cols].notna().sum(axis=1)
    out["n_health_metrics"] = out[h_cols].notna().sum(axis=1)

    # peer mode summary (majority of primary metric peer modes — not *_sector)
    peer_cols = [
        c for c in out.columns
        if c.startswith("peer_") and not c.endswith("_sector")
    ]

    def _mode_row(r: pd.Series) -> str:
        vals = [v for v in r if isinstance(v, str) and v]
        if not vals:
            return ""
        return max(set(vals), key=vals.count)

    out["peer_mode"] = out[peer_cols].apply(_mode_row, axis=1) if peer_cols else ""
    return out


def _fmt(v: Any, digits: int = 1) -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "—"
    try:
        return f"{float(v):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


_SORTABLE_SCRIPT = """
<script>
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : 0;
    if (type === "text") return s.toUpperCase();
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

_HTML_CSS = """
body { font-family: "Segoe UI", Tahoma, sans-serif; margin: 24px; color: #0f172a; background: #fff; }
h1 { font-size: 1.45rem; margin: 0 0 6px; }
h2 { font-size: 1.15rem; margin: 28px 0 8px; border-bottom: 1px solid #e2e8f0; padding-bottom: 4px; }
.sub, .meta, .small { color: #475569; font-size: 13px; line-height: 1.5; }
.warn { background: #fff7ed; border: 1px solid #fdba74; padding: 10px 12px; border-radius: 6px; margin: 12px 0; font-size: 13px; }
.table-wrap { overflow-x: auto; margin: 12px 0; }
table { border-collapse: collapse; font-size: 12px; width: 100%; min-width: 720px; }
th, td { border: 1px solid #e2e8f0; padding: 6px 8px; text-align: left; }
th { background: #f1f5f9; }
th.sortable-th { cursor: pointer; user-select: none; white-space: nowrap; }
th.sortable-th:hover { background: #e2e8f0; }
.sort-ind { display: inline-block; width: 0.9em; margin-left: 4px; color: #94a3b8; font-size: 10px; }
th.sort-asc .sort-ind::after { content: "▲"; color: #334155; }
th.sort-desc .sort-ind::after { content: "▼"; color: #334155; }
code { font-size: 12px; }
a { color: #1d4ed8; }
"""


def _th(label: str, typ: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{typ}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def group_pillar_rankings(
    df: pd.DataFrame,
    group_col: str,
    *,
    min_n: int = 3,
) -> pd.DataFrame:
    """Mean/median of each primary pillar by sector or industry."""
    scored = df[df["n_pillars"] >= 1].copy()
    scored[group_col] = scored[group_col].fillna("").replace("", "(blank)")
    pillars = [
        "score_valuation",
        "score_quality",
        "score_growth_stability",
        "score_financial_health",
        "score_composite",
    ]
    rows: list[dict[str, Any]] = []
    for name, g in scored.groupby(group_col, dropna=False):
        if len(g) < min_n:
            continue
        row: dict[str, Any] = {group_col: name, "n": len(g)}
        for p in pillars:
            s = g[p].dropna()
            row[f"{p}_mean"] = float(s.mean()) if len(s) else float("nan")
            row[f"{p}_median"] = float(s.median()) if len(s) else float("nan")
            row[f"{p}_n"] = int(len(s))
        rows.append(row)
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values("score_composite_mean", ascending=False)


def write_html(df: pd.DataFrame, path: Path, *, meta: dict[str, Any]) -> None:
    show = df[df["n_pillars"] >= 1].sort_values("score_composite", ascending=False)
    heads = "".join(
        [
            _th("Symbol", "text"),
            _th("Sector", "text"),
            _th("Industry", "text"),
            _th("Financial?", "text"),
            _th("Valuation", "num"),
            _th("Quality", "num"),
            _th("Growth Stability", "num"),
            _th("Fin. Health", "num"),
            _th("Composite", "num"),
            _th("Val (sector)", "num"),
            _th("Qual (sector)", "num"),
            _th("GS (sector)", "num"),
            _th("Comp (sector)", "num"),
            _th("N pillars", "num"),
            _th("Peer mode", "text"),
            _th("P/E", "num"),
            _th("P/B", "num"),
            _th("P/S", "num"),
            _th("EV/EBITDA", "num"),
            _th("ROE", "num"),
            _th("EPS g vol", "num"),
            _th("D/E", "num"),
            _th("Current ratio", "num"),
        ]
    )
    body_rows = []
    for _, r in show.iterrows():
        body_rows.append(
            "<tr>"
            f"<td>{html_mod.escape(str(r['symbol']))}</td>"
            f"<td>{html_mod.escape(str(r['sector'] or ''))}</td>"
            f"<td>{html_mod.escape(str(r['industry'] or ''))}</td>"
            f"<td>{'Y' if r['is_financial'] else ''}</td>"
            f"<td>{_fmt(r['score_valuation'])}</td>"
            f"<td>{_fmt(r['score_quality'])}</td>"
            f"<td>{_fmt(r['score_growth_stability'])}</td>"
            f"<td>{_fmt(r['score_financial_health'])}</td>"
            f"<td><strong>{_fmt(r['score_composite'])}</strong></td>"
            f"<td>{_fmt(r.get('score_valuation_sector'))}</td>"
            f"<td>{_fmt(r.get('score_quality_sector'))}</td>"
            f"<td>{_fmt(r.get('score_growth_stability_sector'))}</td>"
            f"<td>{_fmt(r.get('score_composite_sector'))}</td>"
            f"<td>{int(r['n_pillars'])}</td>"
            f"<td>{html_mod.escape(str(r.get('peer_mode') or ''))}</td>"
            f"<td>{_fmt(r['pe'], 2)}</td>"
            f"<td>{_fmt(r['pb'], 2)}</td>"
            f"<td>{_fmt(r['ps'], 2)}</td>"
            f"<td>{_fmt(r['ev_ebitda'], 2)}</td>"
            f"<td>{_fmt(r['roe'], 3)}</td>"
            f"<td>{_fmt(r['eps_growth_vol'], 3)}</td>"
            f"<td>{_fmt(r['debt_to_equity'], 2)}</td>"
            f"<td>{_fmt(r['current_ratio'], 2)}</td>"
            "</tr>"
        )

    gen = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    rankings_rel = "sector_rankings.html"
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>House fund scorecard v1.1 industry — {html_mod.escape(meta.get('stamp',''))}</title>
<style>{_HTML_CSS}</style></head><body>
<h1>House fundamental scorecard v1.1 (industry peers)</h1>
<p class="sub">Research proxies approximating the <em>idea</em> of Fidelity/S&amp;P four-pillar
1–100 peer-relative scores. <strong>Not Fidelity/S&amp;P parity</strong> — Yahoo public fields +
house percentile logic only.</p>
<div class="warn">
  Generated {html_mod.escape(gen)}. Universe: <code>{html_mod.escape(str(meta.get('universe','')))}</code>
  (N={meta.get('univ_n')}). Scored with ≥1 pillar: <strong>{meta.get('scored_n')}</strong>.
  Missing/skipped: <strong>{meta.get('missing_n')}</strong>.
  Financials flag: Financial Health pillar blank (bank ratios not comparable).
  Click column headers to sort.
  See also <a href="{rankings_rel}">sector / industry rankings</a>.
</div>
<p class="meta">Primary peer ranks: Yahoo <strong>industry</strong> when industry N≥{MIN_INDUSTRY_N};
else <strong>sector</strong> when sector N≥{MIN_SECTOR_N}; else all-universe.
Dual <em>(sector)</em> columns = sector→all-univ only (v1 continuity).
Composite = equal-weight mean of available pillars (Valuation, Quality, Growth Stability,
Financial Health). Valuation inverted (cheap→high).</p>
<div class="table-wrap">
<table class="sortable">
<caption>Per-symbol pillar scores (0–100). Click headers to sort.</caption>
<thead><tr>{heads}</tr></thead>
<tbody>
{''.join(body_rows)}
</tbody>
</table>
</div>
{_SORTABLE_SCRIPT}
</body></html>
"""
    path.write_text(html, encoding="utf-8")


def _ranking_table_html(rank: pd.DataFrame, group_col: str, title: str) -> str:
    if rank.empty:
        return f"<h2>{html_mod.escape(title)}</h2><p class='meta'>No groups with enough names.</p>"
    label = "Sector" if group_col == "sector" else "Industry"
    heads = "".join(
        [
            _th(label, "text"),
            _th("N", "num"),
            _th("Val mean", "num"),
            _th("Val med", "num"),
            _th("Qual mean", "num"),
            _th("Qual med", "num"),
            _th("GS mean", "num"),
            _th("GS med", "num"),
            _th("Health mean", "num"),
            _th("Health med", "num"),
            _th("Comp mean", "num"),
            _th("Comp med", "num"),
        ]
    )
    rows = []
    for _, r in rank.iterrows():
        rows.append(
            "<tr>"
            f"<td>{html_mod.escape(str(r[group_col]))}</td>"
            f"<td>{int(r['n'])}</td>"
            f"<td>{_fmt(r['score_valuation_mean'])}</td>"
            f"<td>{_fmt(r['score_valuation_median'])}</td>"
            f"<td>{_fmt(r['score_quality_mean'])}</td>"
            f"<td>{_fmt(r['score_quality_median'])}</td>"
            f"<td>{_fmt(r['score_growth_stability_mean'])}</td>"
            f"<td>{_fmt(r['score_growth_stability_median'])}</td>"
            f"<td>{_fmt(r['score_financial_health_mean'])}</td>"
            f"<td>{_fmt(r['score_financial_health_median'])}</td>"
            f"<td><strong>{_fmt(r['score_composite_mean'])}</strong></td>"
            f"<td>{_fmt(r['score_composite_median'])}</td>"
            "</tr>"
        )
    return f"""
<h2>{html_mod.escape(title)}</h2>
<p class="meta">Mean / median of primary (industry-first) pillar scores among scored symbols
in each {html_mod.escape(label.lower())}. Groups with N&lt;3 omitted. Click headers to sort —
default order is composite mean descending.</p>
<div class="table-wrap">
<table class="sortable">
<caption>{html_mod.escape(title)} — click headers to sort</caption>
<thead><tr>{heads}</tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
</div>
"""


def write_rankings_html(
    df: pd.DataFrame,
    path: Path,
    *,
    meta: dict[str, Any],
    sector_rank: pd.DataFrame,
    industry_rank: pd.DataFrame,
) -> None:
    gen = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Sector / industry fund rankings — {html_mod.escape(meta.get('stamp',''))}</title>
<style>{_HTML_CSS}</style></head><body>
<h1>Sector &amp; industry pillar rankings</h1>
<p class="sub">Which Yahoo sectors / industries score well on each house pillar
(Valuation, Quality, Growth Stability, Financial Health, Composite).
<strong>Research only — not Fidelity/S&amp;P parity.</strong>
Back to <a href="scorecard.html">per-symbol scorecard</a>.</p>
<div class="warn">
  Generated {html_mod.escape(gen)}. Stamp <code>{html_mod.escape(meta.get('stamp',''))}</code>.
  Universe N={meta.get('univ_n')}; scored={meta.get('scored_n')}.
  Primary scores use industry→sector→all-univ peers. Rankings aggregate those primary scores.
</div>
{_ranking_table_html(sector_rank, "sector", "By sector")}
{_ranking_table_html(industry_rank, "industry", "By industry")}
{_SORTABLE_SCRIPT}
</body></html>
"""
    path.write_text(html, encoding="utf-8")


def write_baseline(path: Path, meta: dict[str, Any]) -> None:
    text = f"""# BASELINE — House fundamental scorecard v1.1 industry ({meta.get('stamp_name', 'fund_scorecard_v1_industry_20260831')})

**Research only. Not gold. Not DailyRun.**  
**House research proxies — NOT Fidelity / S&P Global parity.**

Date: 2026-08-31.

## Delta from v1 (`fund_scorecard_v1_20260830`)

- **Primary peer ranks are industry-first:** Yahoo industry when industry N ≥ {MIN_INDUSTRY_N};
  else sector when sector N ≥ {MIN_SECTOR_N}; else all-universe.
- Dual **sector-only** pillar columns (`score_*_sector`) retained for continuity with v1.
- New **sector / industry ranking** HTML: mean & median of each pillar by group.
- Metric → pillar map unchanged (Valuation, Quality, Growth Stability, Financial Health).

## Purpose

House scorecard approximating the *idea* of vendor four-pillar 1–100 **peer-relative** scores:

| Pillar | House intent |
|--------|----------------|
| Valuation | Cheap vs peers → high score |
| Quality | Profitability / cash conversion vs peers |
| Growth Stability | Low historical EPS (Earnings Per Share) growth volatility → high |
| Financial Health | Balance-sheet resilience vs peers |
| Composite | Equal-weight mean of **available** pillars (skip NA) |

These are **not** reverse-engineered Fidelity or S&P factor definitions, weights,
peer sets, or winsorization rules.

## Universe

- **Primary:** `{meta.get('universe')}` (ALL OHLC (Open-High-Low-Close) tape list preferred).
- **Alt liquid:** `drive/universes/MOM_universe.csv` = VZ tradable **ADV$2m** (Average Daily
  Dollar Volume ≥ ~$2m) static membership — pass via `--universe`.
- Symbols with no usable metrics / no pillars are **skipped** (listed in SUMMARY coverage).

## Data sources

1. **DuckDB** `drive/fundamentals_cache.duckdb` via `stock_analysis/fundamentals_yfinance.py`
   - `yf_symbol_info` — sector, industry, ROE (Return on Equity), earningsGrowth hints
   - `yf_earnings_annual` / `yf_earnings_quarterly` — EPS history for Growth Stability
2. **Yahoo `Ticker.info` snapshot** → separate DuckDB `drive/fund_scorecard_cache.duckdb`
   table `yf_scorecard_metrics` (writable; avoids Google Drive lock on the fund cache)
   - P/E (Price-to-Earnings), P/B (Price-to-Book), P/S (Price-to-Sales),
     EV/EBITDA (Enterprise Value to Earnings Before Interest, Taxes, Depreciation & Amortization)
   - ROA (Return on Assets), margins, FCF (Free Cash Flow), D/E (Debt-to-Equity),
     current ratio, EBITDA / interest expense when present

Point-in-time honesty: snapshots are **as-of last refresh**, not historical PIT panels.

## Metric → pillar map

### Valuation (invert: lower multiple → higher score)

- Trailing P/E (else forward P/E); P/B; P/S; EV/EBITDA (non-financials)
- Drop non-positive / absurd multiples before ranking
- **Fallback:** if Yahoo P/E missing, house proxy `currentPrice / latest annual EPS`
  (`pe_source=house_price_eps`) — not identical to vendor trailing P/E

### Quality

- ROE, ROA, profit margin, operating margin
- FCF conversion ≈ FCF / |net income to common| (non-financials)
- Financials: **ROE / ROA only** (margins & FCF conversion skipped)

### Growth Stability

- Stdev of YoY (Year-over-Year) EPS growth (annual preferred; else quarterly lag-4)
- Need ≥{MIN_GROWTH_OBS} growth observations; growth clipped to ±500% before stdev

### Financial Health

- D/E (lower better), current ratio (higher better), interest coverage ≈ EBITDA / |interest|
- **Financial Services:** pillar set to NA — bank leverage/liquidity ratios are not
  comparable to corporates (`is_financial` flag)

## Peer percentiles (v1.1)

**Primary cascade (feeds `score_*` and `score_composite`):**

1. Within Yahoo **industry** when industry size ≥ {MIN_INDUSTRY_N} and enough non-null metrics
2. Else within Yahoo **sector** when sector size ≥ {MIN_SECTOR_N}
3. Else **all-universe** percentile

`peer_mode` documents majority metric mode (`industry` | `sector` | `all_univ`).

**Dual sector columns** (`score_*_sector`, `pct_*_sector`): sector → all-univ only
(same rule as v1 `fund_scorecard_v1_20260830`) for side-by-side compare.

- Pillar = equal-weight mean of available metric percentiles
- Composite = equal-weight mean of available pillars (financials usually 3 pillars)

## Sector / industry rankings

`sector_rankings.html` + CSVs: for each sector / industry with ≥3 scored names,
report mean & median of Valuation, Quality, Growth Stability, Financial Health, Composite
(using **primary** industry-first scores). Answers: which sectors/industries look strong
on each pillar.

## Caveats

- Not vendor parity; Yahoo field gaps are common (especially interest coverage).
- Static universe membership (survivorship / listing bias).
- No PIT fundamentals; look-ahead if used naïvely in backtests.
- Banks/insurers: health excluded; quality simplified — **document honesty**.
- Thin industries fall back to sector; thin sectors → all-univ — mixes unlike peers.
- Industry labels from Yahoo can be sparse / inconsistent across listings.
- Research toy for screening context — do **not** wire DailyRun from this stamp.

## Re-run

```bash
python tools/fund_scorecard_v1.py
python tools/fund_scorecard_v1.py --universe drive/universes/MOM_universe.csv
python tools/fund_scorecard_v1.py --cache-only
python tools/fund_scorecard_v1.py --force-refresh --workers 6
python tools/fund_scorecard_v1.py --min-industry-n 6 --min-sector-n 8
```

Env: `FUNDAMENTALS_DB`, `NO_YFINANCE`, `YF_FUND_TTL_DAYS` (info TTL; scorecard uses
`--ttl-days`, default 7).
"""
    path.write_text(text, encoding="utf-8")


def write_summary(
    path: Path,
    df: pd.DataFrame,
    meta: dict[str, Any],
    *,
    sector_rank: Optional[pd.DataFrame] = None,
    industry_rank: Optional[pd.DataFrame] = None,
) -> None:
    scored = df[df["n_pillars"] >= 1].copy()
    missing = df[df["n_pillars"] < 1]
    fins = int(df["is_financial"].sum())
    fuller = scored[(scored["n_val_metrics"] >= 1) & (scored["n_pillars"] >= 3)]
    top = scored.nlargest(15, "score_composite")[
        ["symbol", "sector", "industry", "score_valuation", "score_quality",
         "score_growth_stability", "score_financial_health", "score_composite",
         "n_pillars", "peer_mode"]
    ]
    top_full = fuller.nlargest(15, "score_composite")[
        ["symbol", "sector", "industry", "score_valuation", "score_quality",
         "score_growth_stability", "score_financial_health", "score_composite"]
    ]
    bot = scored.nsmallest(15, "score_composite")[
        ["symbol", "sector", "industry", "score_valuation", "score_quality",
         "score_growth_stability", "score_financial_health", "score_composite"]
    ]

    def _tbl(x: pd.DataFrame) -> str:
        cols = list(x.columns)
        lines = [
            "| " + " | ".join(cols) + " |",
            "| " + " | ".join(["---"] * len(cols)) + " |",
        ]
        for _, row in x.iterrows():
            cells = []
            for c in cols:
                v = row[c]
                if c in ("symbol", "sector", "industry", "peer_mode") or c == "n_pillars":
                    cells.append("" if v is None else str(v if c != "n_pillars" else int(v)))
                elif v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
                    cells.append("—")
                else:
                    try:
                        cells.append(f"{float(v):.1f}")
                    except (TypeError, ValueError):
                        cells.append(str(v))
            lines.append("| " + " | ".join(cells) + " |")
        return "\n".join(lines)

    peer_vc = scored["peer_mode"].value_counts().to_dict() if len(scored) else {}
    pe_src = (
        scored["pe_source"].value_counts(dropna=False).to_dict()
        if "pe_source" in scored.columns
        else {}
    )
    n_yahoo_sc = int(df["has_scorecard_row"].sum())

    sec_top = ""
    if sector_rank is not None and len(sector_rank):
        sec_top = _tbl(
            sector_rank.head(12)[
                ["sector", "n", "score_valuation_mean", "score_quality_mean",
                 "score_growth_stability_mean", "score_financial_health_mean",
                 "score_composite_mean"]
            ]
        )
    ind_top = ""
    if industry_rank is not None and len(industry_rank):
        ind_top = _tbl(
            industry_rank.head(15)[
                ["industry", "n", "score_valuation_mean", "score_quality_mean",
                 "score_growth_stability_mean", "score_financial_health_mean",
                 "score_composite_mean"]
            ]
        )

    text = f"""# SUMMARY — House fund scorecard v1.1 (industry peers)

**Research proxies — NOT Fidelity/S&P parity.** Stamp: `{meta.get('stamp_name')}`.

Date: 2026-08-31.

## Coverage

| Item | N |
|------|--:|
| Universe | {meta.get('univ_n')} |
| Scored (≥1 pillar) | {len(scored)} |
| Missing / skipped | {len(missing)} |
| Financial Services (health NA) | {fins} |
| Yahoo scorecard snapshot rows | {n_yahoo_sc} |
| Fund info fallback rows | {int(df['has_fund_info'].sum())} |
| Fuller book (val≥1 metric & ≥3 pillars) | {len(fuller)} |
| Sector groups (rankings) | {0 if sector_rank is None else len(sector_rank)} |
| Industry groups (rankings) | {0 if industry_rank is None else len(industry_rank)} |

Missing symbols: `{sorted(missing['symbol'].tolist()) if len(missing) else []}`

Peer mode counts (scored, primary cascade): `{peer_vc}`  
P/E source counts: `{pe_src}`

Pillar non-null counts (scored):  
Valuation={int(scored['score_valuation'].notna().sum())},  
Quality={int(scored['score_quality'].notna().sum())},  
Growth Stability={int(scored['score_growth_stability'].notna().sum())},  
Financial Health={int(scored['score_financial_health'].notna().sum())}.

## Top sectors by composite mean

{sec_top or '_n/a_'}

## Top industries by composite mean

{ind_top or '_n/a_'}

## Sample top composite (all scored)

{_tbl(top)}

## Sample top composite (fuller: has valuation + ≥3 pillars)

{_tbl(top_full)}

## Sample bottom composite (all scored)

{_tbl(bot)}

## Caveats (short)

- House Yahoo + percentile proxies only — **not** Fidelity/S&P parity.
- Primary peers: industry (N≥{MIN_INDUSTRY_N}) → sector (N≥{MIN_SECTOR_N}) → all-univ.
- Dual `*_sector` columns = v1 sector-only peers for continuity.
- Financials: Financial Health blank; Quality simplified (ROE/ROA).
- Growth Stability = EPS growth vol (revenue history not in DuckDB cache).
- Incomplete pillars can inflate composite for sparse names — prefer the fuller tables.
- Not for DailyRun / not gold.

## Outputs

- `BASELINE.md` — methodology
- `scores.csv` — full metric + score table (primary + sector dual)
- `scorecard.html` — sortable per-symbol HTML
- `sector_rankings.html` — sector & industry mean/median by pillar
- `sector_rankings.csv` / `industry_rankings.csv`
- Re-run: `python tools/fund_scorecard_v1.py`
"""
    path.write_text(text, encoding="utf-8")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="House fundamental scorecard v1.1 industry (research)")
    ap.add_argument(
        "--universe",
        type=Path,
        default=UNIVERSE_ALL,
        help=f"Symbol list CSV (default: {UNIVERSE_ALL})",
    )
    ap.add_argument("--out", type=Path, default=STAMP_DEFAULT, help="Stamp output directory")
    ap.add_argument("--db", type=Path, default=None, help="Fundamentals DuckDB path (read-only)")
    ap.add_argument(
        "--scorecard-db",
        type=Path,
        default=DEFAULT_SCORECARD_DB,
        help="Separate DuckDB for Yahoo scorecard snapshots (writable)",
    )
    ap.add_argument("--limit", type=int, default=0, help="Smoke: first N symbols")
    ap.add_argument("--force-refresh", action="store_true", help="Ignore scorecard TTL")
    ap.add_argument("--cache-only", action="store_true", help="No Yahoo network fetch")
    ap.add_argument("--ttl-days", type=int, default=SCORECARD_TTL_DAYS_DEFAULT)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--min-industry-n", type=int, default=MIN_INDUSTRY_N)
    ap.add_argument("--min-sector-n", type=int, default=MIN_SECTOR_N)
    ap.add_argument("--skip-ntfy", action="store_true")
    args = ap.parse_args(argv)

    univ_path = args.universe if args.universe.is_absolute() else _REPO / args.universe
    if not univ_path.exists():
        # fallback ADV$2m liquid
        if UNIVERSE_ADV2M.exists():
            print(f"[fund-sc] universe missing {univ_path}; falling back to {UNIVERSE_ADV2M}")
            univ_path = UNIVERSE_ADV2M
        else:
            print(f"ERROR: universe not found: {univ_path}", file=sys.stderr)
            return 2

    symbols = _load_universe(univ_path)
    if args.limit and args.limit > 0:
        symbols = symbols[: args.limit]
        print(f"[fund-sc] limit -> {len(symbols)}")

    db_path = resolve_fundamentals_db(args.db)
    sc_db = args.scorecard_db if args.scorecard_db.is_absolute() else _REPO / args.scorecard_db
    out_dir = args.out if args.out.is_absolute() else _REPO / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp_name = out_dir.name

    print(f"[fund-sc] universe={univ_path} N={len(symbols)}")
    print(f"[fund-sc] fund_db={db_path} (read-only)")
    print(f"[fund-sc] scorecard_db={sc_db}")
    print(f"[fund-sc] out={out_dir}")
    print(
        f"[fund-sc] peers: industry N>={args.min_industry_n} -> "
        f"sector N>={args.min_sector_n} -> all_univ"
    )

    scorecard = refresh_scorecard_metrics(
        symbols,
        sc_db,
        force=args.force_refresh,
        cache_only=args.cache_only,
        ttl=args.ttl_days,
        workers=args.workers,
    )
    raw = build_metric_frame(symbols, db_path, scorecard)
    scored = score_pillars(
        raw,
        min_industry_n=args.min_industry_n,
        min_sector_n=args.min_sector_n,
    )

    scored_n = int((scored["n_pillars"] >= 1).sum())
    missing_n = int((scored["n_pillars"] < 1).sum())
    meta = {
        "universe": univ_path.as_posix(),
        "univ_n": len(symbols),
        "scored_n": scored_n,
        "missing_n": missing_n,
        "stamp": stamp_name,
        "stamp_name": stamp_name,
    }

    sector_rank = group_pillar_rankings(scored, "sector", min_n=3)
    industry_rank = group_pillar_rankings(scored, "industry", min_n=3)

    # CSV: useful columns first
    csv_cols = [
        "symbol", "sector", "industry", "is_financial", "peer_mode",
        "score_valuation", "score_quality", "score_growth_stability",
        "score_financial_health", "score_composite",
        "score_valuation_sector", "score_quality_sector",
        "score_growth_stability_sector", "score_financial_health_sector",
        "score_composite_sector",
        "n_pillars",
        "n_val_metrics", "n_qual_metrics", "n_health_metrics",
        "pe", "pe_source", "pb", "ps", "ev_ebitda", "roe", "roa", "profit_margin",
        "operating_margin", "fcf_conversion", "eps_growth_vol",
        "debt_to_equity", "current_ratio", "interest_coverage",
        "earnings_growth", "revenue_growth",
        "has_scorecard_row", "has_fund_info",
    ]
    # include pct_* for transparency (primary + sector dual)
    pct_cols = [c for c in scored.columns if c.startswith("pct_")]
    export_cols = [c for c in csv_cols if c in scored.columns] + pct_cols
    export = scored[export_cols].sort_values("score_composite", ascending=False)
    export.to_csv(out_dir / "scores.csv", index=False)
    if len(sector_rank):
        sector_rank.to_csv(out_dir / "sector_rankings.csv", index=False)
    if len(industry_rank):
        industry_rank.to_csv(out_dir / "industry_rankings.csv", index=False)

    # PIT retention: dated metrics + scores (idempotent same calendar day)
    as_of_day = datetime.utcnow().date()
    snapshot_metrics_history_from_latest(sc_db, symbols, as_of=as_of_day)
    persist_scores_history(sc_db, scored, as_of=as_of_day)

    write_baseline(out_dir / "BASELINE.md", meta)
    write_summary(
        out_dir / "SUMMARY.md",
        scored,
        meta,
        sector_rank=sector_rank,
        industry_rank=industry_rank,
    )
    html_path = out_dir / "scorecard.html"
    rankings_path = out_dir / "sector_rankings.html"
    write_html(scored, html_path, meta=meta)
    write_rankings_html(
        scored, rankings_path, meta=meta,
        sector_rank=sector_rank, industry_rank=industry_rank,
    )

    print(f"[fund-sc] scored={scored_n} missing={missing_n} -> {out_dir}")
    print(
        f"[fund-sc] rankings: sectors={len(sector_rank)} industries={len(industry_rank)}"
    )

    if not args.skip_ntfy:
        import subprocess

        subprocess.run(
            [
                sys.executable,
                str(_REPO / "tools" / "ntfy_job_done.py"),
                "--path",
                str(html_path),
                "--path",
                str(rankings_path),
                "-t",
                "Fund scorecard industry done",
                "-m",
                (
                    f"House fund scorecard v1.1 industry: scored {scored_n}/{len(symbols)}; "
                    f"sectors={len(sector_rank)} industries={len(industry_rank)} -> "
                    f"{html_path.as_posix()}"
                ),
            ],
            check=False,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
