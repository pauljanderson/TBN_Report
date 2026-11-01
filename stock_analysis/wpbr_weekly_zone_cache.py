"""DuckDB cache for WPBR weekly OHLCV + zone streams.

Research / speed feature. Default OFF. Enable with::

    -v wpbr_weekly_zone_cache=true
    # or
    set WPBR_WEEKLY_ZONE_CACHE=1

Separate file from ``data/ohlcv.duckdb`` so cache writes do not lock daily prices.

Invalidation
------------
Each symbol stores ``daily_fp`` (blake2b of bar count, edge dates, edge OHLCV —
same idea as ``brt_entry_indicators.ohlcv_fingerprint``).

- Fingerprint mismatch (split / dividend adjustment / revised history):
  delete that symbol's weekly rows and stream blob, then rebuild.
- Exact fingerprint + bar count match: reuse weeklies and (if config matches)
  the full zone stream.
- Append-only growth (prefix dates + closes match cached ``n_bars``):
  keep completed week rows with ``week_end`` strictly before the Monday of the
  first new daily bar's week; rebuild from that Monday forward; always rebuild
  zone stream (zone BO/retest can change on new bars). Incomplete current week
  is never trusted from cache alone.

Parity: cold compute and warm cache must match events + entry bars. Default
stays OFF until a stamp proves parity.
"""
from __future__ import annotations

import hashlib
import json
import os
import pickle
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import duckdb
import numpy as np
import pandas as pd

CACHE_VERSION = 1
DEFAULT_DB_NAME = "wpbr_weekly_zone_cache.duckdb"

_STATS_LOCK = threading.Lock()
_STATS: dict[str, int] = {
    "weekly_hit": 0,
    "weekly_partial": 0,
    "weekly_miss": 0,
    "weekly_save": 0,
    "stream_hit": 0,
    "stream_miss": 0,
    "stream_save": 0,
    "invalidate": 0,
    "lock_skip": 0,
}


def get_cache_stats() -> dict[str, int]:
    with _STATS_LOCK:
        return dict(_STATS)


def reset_cache_stats() -> None:
    with _STATS_LOCK:
        for k in _STATS:
            _STATS[k] = 0


def format_cache_stats(stats: Optional[dict[str, int]] = None) -> str:
    s = stats if stats is not None else get_cache_stats()
    parts = [f"{k}={v}" for k, v in s.items() if v]
    return ", ".join(parts) if parts else "no activity"


def _bump(key: str, n: int = 1) -> None:
    with _STATS_LOCK:
        _STATS[key] = int(_STATS.get(key, 0)) + n


def cache_flag_enabled(cfg_value: Any = None) -> bool:
    """True when cfg asks for cache or ``WPBR_WEEKLY_ZONE_CACHE`` is truthy."""
    if cfg_value is not None and str(cfg_value).strip() != "":
        v = str(cfg_value).strip().lower()
        if v in {"1", "true", "yes", "on"}:
            return True
        if v in {"0", "false", "no", "off"}:
            return False
        if isinstance(cfg_value, bool):
            return bool(cfg_value)
    env = os.environ.get("WPBR_WEEKLY_ZONE_CACHE", "").strip().lower()
    return env in {"1", "true", "yes", "on"}


def resolve_cache_db_path(
    db_path: str | Path | None = None,
    *,
    repo_root: str | Path | None = None,
) -> Path:
    raw = (str(db_path).strip() if db_path else "") or os.environ.get(
        "WPBR_WEEKLY_ZONE_CACHE_DB", ""
    ).strip()
    if raw:
        p = Path(raw)
        if not p.is_absolute() and repo_root is not None:
            p = Path(repo_root) / p
        return p.resolve()
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parent.parent
    return (root / "data" / DEFAULT_DB_NAME).resolve()


def daily_fingerprint(df: pd.DataFrame) -> str:
    """Stable hash of daily OHLCV (detects revisions, not just append)."""
    if df is None or df.empty:
        return ""
    try:
        from brt_entry_indicators import ohlcv_fingerprint
    except ImportError:
        try:
            from stock_analysis.brt_entry_indicators import ohlcv_fingerprint
        except ImportError:
            ohlcv_fingerprint = None  # type: ignore[assignment]
    if ohlcv_fingerprint is not None:
        return str(ohlcv_fingerprint(df))
    c = df["Close"].to_numpy(dtype=np.float64, copy=False)
    n = len(c)
    d = np.array([int(pd.Timestamp(x).strftime("%Y%m%d")) for x in df.index], dtype=np.int64)
    h = hashlib.blake2b(digest_size=16)
    h.update(str(n).encode())
    h.update(d[: min(5, n)].tobytes())
    h.update(d[-min(5, n) :].tobytes())
    h.update(c[: min(32, n)].tobytes())
    h.update(c[-min(32, n) :].tobytes())
    if "Volume" in df.columns:
        v = df["Volume"].to_numpy(dtype=np.float64, copy=False)
        h.update(v[-min(32, n) :].tobytes())
    if "Open" in df.columns:
        o = df["Open"].to_numpy(dtype=np.float64, copy=False)
        h.update(o[-min(16, n) :].tobytes())
    return h.hexdigest()


def prefix_fingerprint(df: pd.DataFrame, n_bars: int) -> str:
    """Fingerprint of the first ``n_bars`` rows (append-only check)."""
    if df is None or df.empty or n_bars <= 0:
        return ""
    if n_bars > len(df):
        return ""
    return daily_fingerprint(df.iloc[:n_bars])


def config_hash(**knobs: Any) -> str:
    """Stable hash of WPBR zone knobs that affect weeklies/zones."""
    payload = json.dumps(knobs, sort_keys=True, default=str)
    return hashlib.blake2b(payload.encode("utf-8"), digest_size=16).hexdigest()


def ensure_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS weekly_bars (
            symbol VARCHAR NOT NULL,
            week_end DATE NOT NULL,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            volume DOUBLE,
            PRIMARY KEY (symbol, week_end)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS symbol_daily_meta (
            symbol VARCHAR PRIMARY KEY,
            daily_fp VARCHAR NOT NULL,
            n_bars INTEGER NOT NULL,
            first_date DATE,
            last_date DATE,
            prefix_fp VARCHAR,
            cache_version INTEGER NOT NULL,
            updated_at TIMESTAMP
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS wpbr_stream_cache (
            symbol VARCHAR NOT NULL,
            config_hash VARCHAR NOT NULL,
            daily_fp VARCHAR NOT NULL,
            n_bars INTEGER NOT NULL,
            cache_version INTEGER NOT NULL,
            payload BLOB NOT NULL,
            updated_at TIMESTAMP,
            PRIMARY KEY (symbol, config_hash)
        )
        """
    )


def _connect(db_path: Path, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(db_path), read_only=read_only)


def _with_write(db_path: Path, fn):
    """Open for write with short retries; on lock failure return None and bump lock_skip."""
    last_exc: BaseException | None = None
    for attempt in range(8):
        try:
            con = _connect(db_path, read_only=False)
            try:
                ensure_schema(con)
                return fn(con)
            finally:
                con.close()
        except duckdb.IOException as e:
            last_exc = e
            time.sleep(0.05 * (attempt + 1))
        except duckdb.Error as e:
            last_exc = e
            break
    _bump("lock_skip")
    if last_exc is not None and os.environ.get("WPBR_CACHE_DEBUG", "").strip():
        print(f"[WPBR_CACHE] write skipped: {last_exc}", flush=True)
    return None


def invalidate_symbol(db_path: Path, symbol: str) -> None:
    sym = (symbol or "").strip().upper()
    if not sym:
        return

    def _do(con: duckdb.DuckDBPyConnection) -> None:
        con.execute("DELETE FROM weekly_bars WHERE symbol = ?", [sym])
        con.execute("DELETE FROM symbol_daily_meta WHERE symbol = ?", [sym])
        con.execute("DELETE FROM wpbr_stream_cache WHERE symbol = ?", [sym])
        _bump("invalidate")

    _with_write(db_path, _do)


def _meta_row(con: duckdb.DuckDBPyConnection, symbol: str) -> Optional[dict[str, Any]]:
    row = con.execute(
        """
        SELECT daily_fp, n_bars, first_date, last_date, prefix_fp, cache_version
        FROM symbol_daily_meta WHERE symbol = ?
        """,
        [symbol],
    ).fetchone()
    if not row:
        return None
    return {
        "daily_fp": str(row[0] or ""),
        "n_bars": int(row[1] or 0),
        "first_date": row[2],
        "last_date": row[3],
        "prefix_fp": str(row[4] or ""),
        "cache_version": int(row[5] or 0),
    }


def load_weekly_bars(db_path: Path, symbol: str) -> Optional[pd.DataFrame]:
    sym = (symbol or "").strip().upper()
    if not sym or not db_path.is_file():
        return None
    try:
        con = _connect(db_path, read_only=True)
    except duckdb.IOException:
        _bump("lock_skip")
        return None
    try:
        rows = con.execute(
            """
            SELECT week_end, open, high, low, close, volume
            FROM weekly_bars WHERE symbol = ? ORDER BY week_end
            """,
            [sym],
        ).fetchall()
    except duckdb.Error:
        return None
    finally:
        con.close()
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["week_end", "Open", "High", "Low", "Close", "Volume"])
    df["week_end"] = pd.to_datetime(df["week_end"])
    df = df.set_index("week_end").sort_index()
    return df

def save_weekly_bars(
    db_path: Path,
    symbol: str,
    weekly: pd.DataFrame,
    *,
    daily_fp: str,
    n_bars: int,
    first_date,
    last_date,
    replace_from: Optional[pd.Timestamp] = None,
) -> bool:
    """Upsert weeklies. If ``replace_from`` set, delete weeks on/after that date first."""
    sym = (symbol or "").strip().upper()
    if not sym or weekly is None:
        return False
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    records = []
    for ts, row in weekly.iterrows():
        we = pd.Timestamp(ts).normalize().date()
        records.append(
            (
                sym,
                we,
                float(row["Open"]) if np.isfinite(row["Open"]) else None,
                float(row["High"]) if np.isfinite(row["High"]) else None,
                float(row["Low"]) if np.isfinite(row["Low"]) else None,
                float(row["Close"]) if np.isfinite(row["Close"]) else None,
                float(row["Volume"]) if "Volume" in weekly.columns and np.isfinite(row.get("Volume", np.nan)) else None,
            )
        )

    def _do(con: duckdb.DuckDBPyConnection) -> bool:
        if replace_from is not None:
            con.execute(
                "DELETE FROM weekly_bars WHERE symbol = ? AND week_end >= ?",
                [sym, pd.Timestamp(replace_from).normalize().date()],
            )
        else:
            con.execute("DELETE FROM weekly_bars WHERE symbol = ?", [sym])
        if records:
            con.executemany(
                """
                INSERT OR REPLACE INTO weekly_bars
                (symbol, week_end, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                records,
            )
        con.execute(
            """
            INSERT OR REPLACE INTO symbol_daily_meta
            (symbol, daily_fp, n_bars, first_date, last_date, prefix_fp, cache_version, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                sym,
                daily_fp,
                int(n_bars),
                pd.Timestamp(first_date).date() if first_date is not None else None,
                pd.Timestamp(last_date).date() if last_date is not None else None,
                daily_fp,
                CACHE_VERSION,
                now,
            ],
        )
        _bump("weekly_save")
        return True

    out = _with_write(db_path, _do)
    return bool(out)


def get_or_build_weekly(
    df: pd.DataFrame,
    *,
    symbol: str,
    db_path: Path,
    aggregate_fn,
) -> pd.DataFrame:
    """Return weeklies, preferring DuckDB cache when fingerprint allows."""
    sym = (symbol or "").strip().upper()
    if not sym or df is None or df.empty:
        return aggregate_fn(df)

    fp = daily_fingerprint(df)
    n = len(df)
    first_d = pd.Timestamp(df.index[0]).normalize()
    last_d = pd.Timestamp(df.index[-1]).normalize()

    meta: Optional[dict[str, Any]] = None
    if db_path.is_file():
        try:
            con = _connect(db_path, read_only=True)
            try:
                meta = _meta_row(con, sym)
            except duckdb.Error:
                meta = None
            finally:
                con.close()
        except duckdb.IOException:
            _bump("lock_skip")
            meta = None
    if meta and int(meta.get("cache_version") or 0) == CACHE_VERSION:
        if str(meta.get("daily_fp") or "") == fp and int(meta.get("n_bars") or 0) == n:
            cached = load_weekly_bars(db_path, sym)
            if cached is not None and not cached.empty:
                _bump("weekly_hit")
                return cached

        # Append-only: reuse completed weeks before first new bar's week.
        n_old = int(meta.get("n_bars") or 0)
        if 0 < n_old < n:
            pref = prefix_fingerprint(df, n_old)
            if pref and pref == str(meta.get("prefix_fp") or meta.get("daily_fp") or ""):
                cached = load_weekly_bars(db_path, sym)
                if cached is not None and not cached.empty:
                    new_start = pd.Timestamp(df.index[n_old]).normalize()
                    # Monday of that calendar week (W-FRI week containing new_start).
                    # Rebuild from the Friday week-end that could include new_start.
                    week_anchor = new_start - pd.Timedelta(days=int(new_start.weekday()))
                    replace_from = week_anchor + pd.Timedelta(days=4)  # Friday of that week
                    keep = cached[cached.index < replace_from]
                    tail_daily = df.loc[df.index >= week_anchor]
                    rebuilt_tail = aggregate_fn(tail_daily) if not tail_daily.empty else cached.iloc[0:0]
                    if keep.empty:
                        weekly = rebuilt_tail
                    elif rebuilt_tail.empty:
                        weekly = keep
                    else:
                        weekly = pd.concat([keep, rebuilt_tail])
                        weekly = weekly[~weekly.index.duplicated(keep="last")].sort_index()
                    save_weekly_bars(
                        db_path,
                        sym,
                        weekly,
                        daily_fp=fp,
                        n_bars=n,
                        first_date=first_d,
                        last_date=last_d,
                        replace_from=replace_from,
                    )
                    _bump("weekly_partial")
                    return weekly

        # Revision / shrink / version skew → invalidate
        invalidate_symbol(db_path, sym)

    _bump("weekly_miss")
    weekly = aggregate_fn(df)
    save_weekly_bars(
        db_path,
        sym,
        weekly,
        daily_fp=fp,
        n_bars=n,
        first_date=first_d,
        last_date=last_d,
    )
    return weekly


def _serialize_stream(stream: dict[str, Any]) -> bytes:
    """Pickle zone stream arrays + event lists (index restored by caller)."""
    payload = {
        "version": CACHE_VERSION,
        "touch_price": np.asarray(stream["touch_price"].to_numpy(dtype=np.float64), dtype=np.float64),
        "zone_center": np.asarray(stream["zone_center"].to_numpy(dtype=np.float64), dtype=np.float64),
        "zone_low": np.asarray(stream["zone_low"].to_numpy(dtype=np.float64), dtype=np.float64),
        "zone_high": np.asarray(stream["zone_high"].to_numpy(dtype=np.float64), dtype=np.float64),
        "matured_now": np.asarray(stream["matured_now"].to_numpy(dtype=bool), dtype=bool),
        "zone_touch_origin": np.asarray(stream["zone_touch_origin"].to_numpy(dtype=np.int8), dtype=np.int8),
        "yh_zone_events": list(stream.get("yh_zone_events") or []),
        "wpbr_zone_events": list(stream.get("wpbr_zone_events") or []),
        "wpbr_entry_opportunities": list(stream.get("wpbr_entry_opportunities") or []),
        "wpbr_entry_signal_bars": list(stream.get("wpbr_entry_signal_bars") or []),
        "wpbr_entry_fill_bars": list(stream.get("wpbr_entry_fill_bars") or []),
        "wpbr_audit": list(stream.get("wpbr_audit") or []),
    }
    return pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL)


def _deserialize_stream(blob: bytes, index: pd.DatetimeIndex) -> Optional[dict[str, Any]]:
    try:
        payload = pickle.loads(blob)
    except Exception:
        return None
    if not isinstance(payload, dict) or int(payload.get("version") or 0) != CACHE_VERSION:
        return None
    n = len(index)
    for key in ("touch_price", "zone_center", "zone_low", "zone_high", "matured_now", "zone_touch_origin"):
        arr = payload.get(key)
        if arr is None or len(arr) != n:
            return None
    zc = np.asarray(payload["zone_center"], dtype=np.float64)
    matured = np.asarray(payload["matured_now"], dtype=bool)
    return {
        "touch_price": pd.Series(np.asarray(payload["touch_price"], dtype=np.float64), index=index),
        "zone_center": pd.Series(zc, index=index),
        "zone_low": pd.Series(np.asarray(payload["zone_low"], dtype=np.float64), index=index),
        "zone_high": pd.Series(np.asarray(payload["zone_high"], dtype=np.float64), index=index),
        "touch_count_long": pd.Series(np.where(np.isfinite(zc), 1, 0), index=index),
        "touch_count_short": pd.Series(0, index=index),
        "tradeable_key_level": pd.Series(matured.copy(), index=index),
        "matured_now": pd.Series(matured, index=index),
        "short_candidate": pd.Series(False, index=index),
        "zone_touch_origin": pd.Series(np.asarray(payload["zone_touch_origin"], dtype=np.int8), index=index),
        "yh_zone_events": list(payload.get("yh_zone_events") or []),
        "wpbr_zone_events": list(payload.get("wpbr_zone_events") or []),
        "wpbr_entry_opportunities": list(payload.get("wpbr_entry_opportunities") or []),
        "wpbr_entry_signal_bars": sorted(set(payload.get("wpbr_entry_signal_bars") or [])),
        "wpbr_entry_fill_bars": sorted(set(payload.get("wpbr_entry_fill_bars") or [])),
        "wpbr_entry_bars": sorted(set(payload.get("wpbr_entry_signal_bars") or [])),
        "wpbr_audit": list(payload.get("wpbr_audit") or payload.get("wpbr_zone_events") or []),
    }


def load_stream_cache(
    db_path: Path,
    *,
    symbol: str,
    cfg_hash: str,
    daily_fp: str,
    n_bars: int,
    index: pd.DatetimeIndex,
) -> Optional[dict[str, Any]]:
    sym = (symbol or "").strip().upper()
    if not sym or not db_path.is_file():
        return None
    try:
        con = _connect(db_path, read_only=True)
    except duckdb.IOException:
        _bump("lock_skip")
        return None
    try:
        row = con.execute(
            """
            SELECT daily_fp, n_bars, cache_version, payload
            FROM wpbr_stream_cache
            WHERE symbol = ? AND config_hash = ?
            """,
            [sym, cfg_hash],
        ).fetchone()
    except duckdb.Error:
        _bump("stream_miss")
        return None
    finally:
        con.close()
    if not row:
        _bump("stream_miss")
        return None
    if str(row[0] or "") != daily_fp or int(row[1] or 0) != int(n_bars) or int(row[2] or 0) != CACHE_VERSION:
        _bump("stream_miss")
        return None
    stream = _deserialize_stream(bytes(row[3]), index)
    if stream is None:
        _bump("stream_miss")
        return None
    _bump("stream_hit")
    return stream


def save_stream_cache(
    db_path: Path,
    *,
    symbol: str,
    cfg_hash: str,
    daily_fp: str,
    n_bars: int,
    stream: dict[str, Any],
) -> bool:
    sym = (symbol or "").strip().upper()
    if not sym:
        return False
    blob = _serialize_stream(stream)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    def _do(con: duckdb.DuckDBPyConnection) -> bool:
        con.execute(
            """
            INSERT OR REPLACE INTO wpbr_stream_cache
            (symbol, config_hash, daily_fp, n_bars, cache_version, payload, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [sym, cfg_hash, daily_fp, int(n_bars), CACHE_VERSION, blob, now],
        )
        _bump("stream_save")
        return True

    return bool(_with_write(db_path, _do))
