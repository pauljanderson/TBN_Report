"""
1-minute OHLCV store helpers (yfinance → parquet).

Timestamps are timezone-aware America/New_York (US/Eastern). Yahoo 1m bars are
not tick data and routinely have gaps — suitable for research only.

Layout (default):
  data/intraday/1m/{SYMBOL}.parquet
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

DEFAULT_INTRADAY_ROOT = Path(__file__).resolve().parent.parent / "data" / "intraday"
DEFAULT_1M_DIR = DEFAULT_INTRADAY_ROOT / "1m"

# Yahoo typically allows ~7 calendar days of 1m per request; total retention ~30 days.
YF_1M_MAX_DAYS_PER_REQUEST = 7
YF_1M_MAX_LOOKBACK_DAYS = 30

YAHOO_ALIAS = {
    "BRK.B": "BRK-B",
    "BF.B": "BF-B",
    "OCANF": "OGC",
}

RESAMPLE_RULES = {
    "5m": "5min",
    "10m": "10min",
    "15m": "15min",
    "30m": "30min",
}


def to_yahoo(symbol: str) -> str:
    s = str(symbol).strip().upper()
    return YAHOO_ALIAS.get(s, s)


def symbol_path(symbol: str, out_dir: str | Path = DEFAULT_1M_DIR) -> Path:
    return Path(out_dir) / f"{str(symbol).strip().upper()}.parquet"


def _quote_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def _normalize_bars(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Normalize a yfinance OHLCV frame to store schema (tz-aware ET)."""
    if df is None or df.empty:
        return pd.DataFrame(
            columns=["ts", "open", "high", "low", "close", "volume", "symbol"]
        )

    raw = df.copy()
    if isinstance(raw.columns, pd.MultiIndex):
        # Single-symbol MultiIndex sometimes appears as (OHLC, ticker)
        if "Close" in raw.columns.get_level_values(0):
            raw.columns = raw.columns.get_level_values(0)
        elif to_yahoo(symbol) in raw.columns.get_level_values(0):
            raw = raw[to_yahoo(symbol)].copy()
        elif symbol.upper() in raw.columns.get_level_values(0):
            raw = raw[symbol.upper()].copy()

    colmap = {c: str(c).strip().lower().replace(" ", "_") for c in raw.columns}
    raw = raw.rename(columns=colmap)
    needed = ["open", "high", "low", "close", "volume"]
    for c in needed:
        if c not in raw.columns:
            raw[c] = pd.NA

    idx = pd.to_datetime(raw.index, utc=True)
    # Store consistently in US/Eastern (DST-aware).
    ts = idx.tz_convert(ET)
    out = pd.DataFrame(
        {
            "ts": ts,
            "open": pd.to_numeric(raw["open"], errors="coerce").astype("float64").round(6),
            "high": pd.to_numeric(raw["high"], errors="coerce").astype("float64").round(6),
            "low": pd.to_numeric(raw["low"], errors="coerce").astype("float64").round(6),
            "close": pd.to_numeric(raw["close"], errors="coerce").astype("float64").round(6),
            "volume": pd.to_numeric(raw["volume"], errors="coerce"),
            "symbol": str(symbol).strip().upper(),
        }
    )
    out = out.dropna(subset=["ts", "close"]).sort_values("ts")
    out = out.drop_duplicates(subset=["ts"], keep="last").reset_index(drop=True)
    return out


def read_1m(symbol: str, out_dir: str | Path = DEFAULT_1M_DIR) -> pd.DataFrame:
    path = symbol_path(symbol, out_dir)
    if not path.is_file():
        return pd.DataFrame(
            columns=["ts", "open", "high", "low", "close", "volume", "symbol"]
        )
    con = duckdb.connect()
    try:
        df = con.execute(
            f"SELECT * FROM read_parquet('{_quote_path(path)}')"
        ).df()
    finally:
        con.close()
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(ET)
    if "symbol" not in df.columns:
        df["symbol"] = str(symbol).strip().upper()
    return df.sort_values("ts").drop_duplicates(subset=["ts"], keep="last").reset_index(drop=True)


def write_1m(symbol: str, df: pd.DataFrame, out_dir: str | Path = DEFAULT_1M_DIR) -> Path:
    path = symbol_path(symbol, out_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    if df.empty:
        # Still write empty schema for discoverability.
        empty = pd.DataFrame(
            columns=["ts", "open", "high", "low", "close", "volume", "symbol"]
        )
        _copy_df_to_parquet(empty, path)
        return path

    clean = df.copy()
    clean["ts"] = pd.to_datetime(clean["ts"], utc=True).dt.tz_convert(ET)
    clean["symbol"] = str(symbol).strip().upper()
    for col in ("open", "high", "low", "close"):
        clean[col] = pd.to_numeric(clean[col], errors="coerce").astype("float64").round(6)
    clean["volume"] = pd.to_numeric(clean["volume"], errors="coerce")
    clean = (
        clean[["ts", "open", "high", "low", "close", "volume", "symbol"]]
        .dropna(subset=["ts", "close"])
        .sort_values("ts")
        .drop_duplicates(subset=["ts"], keep="last")
        .reset_index(drop=True)
    )
    _copy_df_to_parquet(clean, path)
    return path


def _copy_df_to_parquet(df: pd.DataFrame, path: Path) -> None:
    """Write parquet via DuckDB (no pyarrow required)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()
    con = duckdb.connect()
    try:
        con.register("bars", df)
        con.execute(f"COPY bars TO '{_quote_path(tmp)}' (FORMAT PARQUET)")
    finally:
        try:
            con.unregister("bars")
        except Exception:
            pass
        con.close()
    tmp.replace(path)


def merge_bars(existing: pd.DataFrame, fresh: pd.DataFrame) -> pd.DataFrame:
    if existing is None or existing.empty:
        base = fresh
    elif fresh is None or fresh.empty:
        base = existing
    else:
        base = pd.concat([existing, fresh], ignore_index=True)
    if base is None or base.empty:
        return pd.DataFrame(
            columns=["ts", "open", "high", "low", "close", "volume", "symbol"]
        )
    base = base.copy()
    base["ts"] = pd.to_datetime(base["ts"], utc=True).dt.tz_convert(ET)
    return (
        base.sort_values("ts")
        .drop_duplicates(subset=["ts"], keep="last")
        .reset_index(drop=True)
    )


def max_stored_ts(symbol: str, out_dir: str | Path = DEFAULT_1M_DIR) -> Optional[pd.Timestamp]:
    df = read_1m(symbol, out_dir)
    if df.empty:
        return None
    return pd.Timestamp(df["ts"].max())


def _chunk_windows(
    end_et: pd.Timestamp,
    lookback_days: int,
    *,
    start_floor: Optional[pd.Timestamp] = None,
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Build [start, end) windows of at most 7 days, newest first, within Yahoo retention."""
    lookback_days = max(1, min(int(lookback_days), YF_1M_MAX_LOOKBACK_DAYS))
    end = pd.Timestamp(end_et)
    if end.tzinfo is None:
        end = end.tz_localize(ET)
    else:
        end = end.tz_convert(ET)

    earliest = end - pd.Timedelta(days=lookback_days)
    if start_floor is not None:
        sf = pd.Timestamp(start_floor)
        if sf.tzinfo is None:
            sf = sf.tz_localize(ET)
        else:
            sf = sf.tz_convert(ET)
        # Overlap 1 day so late/corrected bars can upsert.
        earliest = max(earliest, sf - pd.Timedelta(days=1))

    windows: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    cursor_end = end
    while cursor_end > earliest:
        cursor_start = max(earliest, cursor_end - pd.Timedelta(days=YF_1M_MAX_DAYS_PER_REQUEST))
        windows.append((cursor_start, cursor_end))
        cursor_end = cursor_start
    return windows


def fetch_1m_yfinance(
    symbol: str,
    *,
    start_et: pd.Timestamp,
    end_et: pd.Timestamp,
    auto_adjust: bool = True,
) -> pd.DataFrame:
    """Fetch one [start, end) window of 1m bars (must be ≤ ~7 days)."""
    import yfinance as yf

    ysym = to_yahoo(symbol)
    start = pd.Timestamp(start_et)
    end = pd.Timestamp(end_et)
    if start.tzinfo is None:
        start = start.tz_localize(ET)
    else:
        start = start.tz_convert(ET)
    if end.tzinfo is None:
        end = end.tz_localize(ET)
    else:
        end = end.tz_convert(ET)

    # yfinance start/end are typically interpreted in exchange local / naive UTC-ish;
    # pass UTC-naive ISO for stable windowing.
    start_utc = start.tz_convert(UTC).tz_localize(None)
    end_utc = end.tz_convert(UTC).tz_localize(None)

    raw = yf.download(
        ysym,
        start=start_utc,
        end=end_utc,
        interval="1m",
        progress=False,
        auto_adjust=auto_adjust,
        threads=False,
        prepost=False,
    )
    return _normalize_bars(raw, symbol)


def upsert_symbol_1m(
    symbol: str,
    *,
    out_dir: str | Path = DEFAULT_1M_DIR,
    lookback_days: int = 7,
    sleep_s: float = 0.75,
    retries: int = 3,
    force_full_window: bool = False,
) -> dict:
    """
    Incremental upsert for one symbol.

    If a parquet exists, fetch from (max_ts - 1d) through now (capped by lookback
    and Yahoo ~30d retention), merge, dedupe by ts, rewrite parquet.
    """
    symbol = str(symbol).strip().upper()
    now_et = pd.Timestamp.now(tz=ET)
    existing = read_1m(symbol, out_dir)
    max_ts = None if existing.empty else pd.Timestamp(existing["ts"].max())

    start_floor = None if force_full_window or max_ts is None else max_ts
    windows = _chunk_windows(now_et, lookback_days, start_floor=start_floor)

    frames: list[pd.DataFrame] = []
    errors: list[str] = []
    for i, (w_start, w_end) in enumerate(windows):
        last_err = None
        for attempt in range(1, max(1, retries) + 1):
            try:
                part = fetch_1m_yfinance(symbol, start_et=w_start, end_et=w_end)
                if not part.empty:
                    frames.append(part)
                last_err = None
                break
            except Exception as exc:  # noqa: BLE001 — surface to caller summary
                last_err = str(exc)
                time.sleep(min(8.0, sleep_s * (2 ** (attempt - 1))))
        if last_err:
            errors.append(f"{w_start.date()}→{w_end.date()}: {last_err}")
        if i + 1 < len(windows) and sleep_s > 0:
            time.sleep(sleep_s)

    fresh = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume", "symbol"])
    )
    merged = merge_bars(existing, fresh)
    path = write_1m(symbol, merged, out_dir)

    return {
        "symbol": symbol,
        "path": str(path),
        "rows_before": int(len(existing)),
        "rows_fetched": int(len(fresh)),
        "rows_after": int(len(merged)),
        "min_ts": None if merged.empty else str(merged["ts"].min()),
        "max_ts": None if merged.empty else str(merged["ts"].max()),
        "windows": len(windows),
        "errors": errors,
    }


def resample_ohlcv(
    df: pd.DataFrame,
    rule: str,
    *,
    label: str = "left",
    closed: str = "left",
) -> pd.DataFrame:
    """
    Resample 1m OHLCV to a coarser rule (pandas offset alias, e.g. '5min').

    Default label/closed='left' so a 5m bar at 09:30 ET covers 09:30–09:34
    (common equity convention). Volume sums; empty bins dropped.
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume", "symbol"])

    work = df.copy()
    work["ts"] = pd.to_datetime(work["ts"], utc=True).dt.tz_convert(ET)
    work = work.sort_values("ts").drop_duplicates(subset=["ts"], keep="last")
    sym = None
    if "symbol" in work.columns and work["symbol"].notna().any():
        sym = str(work["symbol"].iloc[0]).upper()

    indexed = work.set_index("ts")
    agg = indexed.resample(rule, label=label, closed=closed).agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    agg = agg.dropna(subset=["open", "close"]).reset_index()
    if "ts" not in agg.columns:
        # pandas may name the index column "index" depending on version
        for cand in ("index", "level_0"):
            if cand in agg.columns:
                agg = agg.rename(columns={cand: "ts"})
                break
    if sym is not None:
        agg["symbol"] = sym
    cols = ["ts", "open", "high", "low", "close", "volume"] + (
        ["symbol"] if "symbol" in agg.columns else []
    )
    return agg[cols]


def resample_symbol_1m(
    symbol: str,
    timeframe: str,
    *,
    out_dir: str | Path = DEFAULT_1M_DIR,
    cache: bool = False,
    cache_dir: Optional[str | Path] = None,
) -> pd.DataFrame:
    """Load stored 1m bars and resample to 5m/10m/15m/30m (or raw pandas rule)."""
    key = str(timeframe).strip().lower()
    rule = RESAMPLE_RULES.get(key, key)
    df = read_1m(symbol, out_dir)
    out = resample_ohlcv(df, rule)
    if cache and not out.empty:
        cdir = Path(cache_dir) if cache_dir else Path(out_dir).parent / key
        cdir.mkdir(parents=True, exist_ok=True)
        write_1m(symbol, out, cdir)  # same schema writer
    return out


def list_symbols_from_csv_dir(data_dir: str | Path) -> list[str]:
    p = Path(data_dir)
    if not p.is_dir():
        return []
    return sorted(
        f.stem.upper()
        for f in p.glob("*.csv")
        if f.is_file() and f.stem.upper() not in {"SPY"}  # optional; include SPY via explicit -s
    )


def resolve_symbols(
    symbols: Optional[Iterable[str]] = None,
    *,
    universe_file: Optional[str | Path] = None,
    all_from_daily: bool = False,
    daily_data_dir: str | Path = "",
) -> list[str]:
    """Resolve symbol list from CLI-style inputs."""
    out: list[str] = []
    if symbols:
        for s in symbols:
            for part in str(s).replace(";", ",").split(","):
                tok = part.strip().upper()
                if tok and tok not in {"*", "ALL"}:
                    out.append(tok)

    if universe_file:
        path = Path(universe_file)
        # Prefer shared loader when available.
        try:
            from tools.load_universe_csv import load_tickers  # type: ignore
        except Exception:
            try:
                import importlib.util

                repo = Path(__file__).resolve().parent.parent
                spec = importlib.util.spec_from_file_location(
                    "_univ", repo / "tools" / "load_universe_csv.py"
                )
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    load_tickers = mod.load_tickers  # type: ignore
                else:
                    load_tickers = None
            except Exception:
                load_tickers = None

        if load_tickers is not None:
            loaded = load_tickers(path)
            if loaded == "*":
                all_from_daily = True
            else:
                out.extend(str(t).upper() for t in loaded)
        else:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            for line in text.splitlines():
                line = line.split("#", 1)[0].strip()
                if not line:
                    continue
                for part in line.replace(";", ",").split(","):
                    tok = part.strip().upper()
                    if tok and tok not in {"*", "ALL"}:
                        out.append(tok)

    if all_from_daily:
        daily = Path(daily_data_dir) if daily_data_dir else (
            Path(__file__).resolve().parent.parent / "data" / "newdata" / "data"
        )
        # Include SPY for ALL intraday (liquid benchmark often wanted).
        csv_syms = sorted({f.stem.upper() for f in daily.glob("*.csv") if f.is_file()})
        out.extend(csv_syms)

    seen: set[str] = set()
    uniq: list[str] = []
    for s in out:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq
