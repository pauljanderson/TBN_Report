import importlib.util
from pathlib import Path
from typing import Optional

import duckdb
import pandas as pd


DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "ohlcv.duckdb"
DEFAULT_TABLE = "prices"


def _duckdb_lock_help(db_path: str | Path, exc: BaseException) -> str:
    msg = str(exc)
    p = Path(db_path).resolve()
    lines = [
        f"Cannot open DuckDB file (another process holds a lock): {p}",
        f"  Original error: {msg}",
        "  On Windows only one process (or process pool) can use ohlcv.duckdb at a time.",
        "  Fix:",
        "    1. Wait for the other rocket_brt / DailyRun / build_ohlcv_duckdb run to finish, or",
        "    2. End stale Python workers from an interrupted backtest (Task Manager, or",
        "       taskkill /PID <pid> /F using the PID DuckDB reports above), then retry.",
        "  Do not start two --use-duckdb backtests in parallel.",
    ]
    return "\n".join(lines)


def _connect(db_path: str | Path = DEFAULT_DB_PATH, *, read_only: bool = True) -> duckdb.DuckDBPyConnection:
    p = str(Path(db_path))
    try:
        if read_only:
            return duckdb.connect(p, read_only=True)
        return duckdb.connect(p)
    except duckdb.IOException as e:
        raise duckdb.IOException(_duckdb_lock_help(db_path, e)) from e


def has_table(
    db_path: str | Path,
    table: str = DEFAULT_TABLE,
) -> bool:
    """Return True if ``table`` exists in the DuckDB file."""
    p = Path(db_path)
    if not p.is_file():
        return False
    con = _connect(p)
    try:
        rows = con.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = ? LIMIT 1",
            [table],
        ).fetchall()
        if rows:
            return True
        # Fallback for older DuckDB without information_schema layout
        names = {str(r[0]) for r in con.execute("SHOW TABLES").fetchall()}
        return table in names
    except duckdb.Error:
        return False
    finally:
        con.close()


def resolve_db_path(
    data_dir: str | Path = "",
    db_path: str | Path = "",
    table: str = DEFAULT_TABLE,
) -> Path:
    """Pick a DuckDB file that contains ``table``.

    Search order when ``db_path`` is empty:
      <data_dir>/../ohlcv.duckdb, <data_dir>/../../ohlcv.duckdb, <data_dir>/ohlcv.duckdb,
      then repo ``data/ohlcv.duckdb``.
  Skips empty or wrong-schema files (e.g. placeholder next to CSV folders).
    """
    if db_path:
        p = Path(db_path)
        if not p.is_absolute() and data_dir:
            p = (Path(data_dir) / p).resolve()
        else:
            p = p.resolve()
        if not p.is_file():
            raise FileNotFoundError(f"DuckDB file not found: {p}")
        if not has_table(p, table):
            raise RuntimeError(
                f"DuckDB {p} has no table {table!r}. "
                f"Use --db-table or --db-path pointing at a populated ohlcv database."
            )
        return p

    data_path = Path(data_dir) if data_dir else Path(".")
    candidates: list[Path] = []
    for rel in ("../ohlcv.duckdb", "../../ohlcv.duckdb", "ohlcv.duckdb"):
        candidates.append((data_path / rel).resolve())
    candidates.append(Path(DEFAULT_DB_PATH).resolve())

    seen: set[Path] = set()
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        if c.is_file() and has_table(c, table):
            return c

    existing = [c for c in seen if c.is_file()]
    hint = (
        f"  Tried: {', '.join(str(c) for c in candidates)}\n"
        f"  Populate with: python stock_analysis/build_ohlcv_duckdb.py (or your ingest script)\n"
        f"  Or pass: --db-path C:\\path\\to\\ohlcv.duckdb"
    )
    if existing:
        raise RuntimeError(
            f"No DuckDB file under {data_path} contains table {table!r}. "
            f"Found file(s) without that table: {', '.join(str(x) for x in existing)}.\n{hint}"
        )
    raise FileNotFoundError(
        f"No ohlcv.duckdb found near {data_path}.\n{hint}"
    )


def load_configured_tickers(pygetall_path: str | Path | None = None) -> frozenset[str]:
    """Return uppercase ``TICKERS`` from ``pygetallMore.py``."""
    p = Path(pygetall_path or Path(__file__).resolve().parent / "pygetallMore.py")
    if not p.is_file():
        return frozenset()
    spec = importlib.util.spec_from_file_location("_pygetall_tickers", p)
    if spec is None or spec.loader is None:
        return frozenset()
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    tickers = getattr(mod, "TICKERS", None)
    if not tickers:
        return frozenset()
    return frozenset(str(t).strip().upper() for t in tickers if str(t).strip())


def list_csv_symbols(data_dir: str | Path, *, include_spy: bool = False) -> list[str]:
    """Symbols that have a ``SYMBOL.csv`` file under ``data_dir``."""
    p = Path(data_dir)
    if not p.is_dir():
        return []
    syms = sorted({f.stem.upper() for f in p.glob("*.csv") if f.is_file()})
    if include_spy:
        return syms
    return [s for s in syms if s != "SPY"]


def allowed_universe_symbols(
    data_dir: str | Path,
    configured_tickers: set[str] | frozenset[str] | None = None,
) -> set[str]:
    """Intersection of pygetallMore ``TICKERS`` and on-disk CSV symbols."""
    csv_syms = set(list_csv_symbols(data_dir, include_spy=True))
    cfg_syms = set(configured_tickers) if configured_tickers is not None else set(load_configured_tickers())
    return csv_syms & cfg_syms


def filter_symbols_to_universe(
    symbols: list[str],
    data_dir: str | Path,
    *,
    configured_tickers: set[str] | frozenset[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Keep symbols present in both pygetallMore and the CSV directory."""
    allowed = allowed_universe_symbols(data_dir, configured_tickers)
    sym_set = {str(s).strip().upper() for s in symbols if str(s).strip()}
    kept = sorted(sym_set & allowed)
    excluded = sorted(sym_set - allowed)
    return kept, excluded


def prune_orphan_symbols(
    db_path: str | Path,
    data_dir: str | Path,
    table: str = DEFAULT_TABLE,
    configured_tickers: set[str] | frozenset[str] | None = None,
) -> list[str]:
    """Delete DuckDB rows for symbols not in pygetallMore and/or missing CSV files."""
    allowed = allowed_universe_symbols(data_dir, configured_tickers)
    con = _connect(db_path, read_only=False)
    try:
        db_syms = {
            str(r[0]).upper()
            for r in con.execute(f"SELECT DISTINCT symbol FROM {table}").fetchall()
            if str(r[0]).strip()
        }
        orphans = sorted(db_syms - allowed)
        for sym in orphans:
            con.execute(f"DELETE FROM {table} WHERE symbol = ?", [sym])
        return orphans
    finally:
        con.close()


def symbol_bar_counts(
    db_path: str | Path = DEFAULT_DB_PATH,
    table: str = DEFAULT_TABLE,
    include_spy: bool = False,
) -> dict[str, int]:
    """Return ``{symbol: row_count}`` without loading OHLCV (for parallel BRT symbol lists)."""
    con = _connect(db_path)
    try:
        if include_spy:
            rows = con.execute(
                f"SELECT symbol, COUNT(*) AS n FROM {table} GROUP BY symbol ORDER BY symbol"
            ).fetchall()
        else:
            rows = con.execute(
                f"SELECT symbol, COUNT(*) AS n FROM {table} WHERE symbol <> 'SPY' GROUP BY symbol ORDER BY symbol"
            ).fetchall()
        return {str(r[0]): int(r[1]) for r in rows}
    finally:
        con.close()


def list_symbols(
    db_path: str | Path = DEFAULT_DB_PATH,
    table: str = DEFAULT_TABLE,
    include_spy: bool = False,
) -> list[str]:
    con = _connect(db_path)
    try:
        if include_spy:
            rows = con.execute(f"SELECT DISTINCT symbol FROM {table} ORDER BY symbol").fetchall()
        else:
            rows = con.execute(
                f"SELECT DISTINCT symbol FROM {table} WHERE symbol <> 'SPY' ORDER BY symbol"
            ).fetchall()
        return [str(r[0]) for r in rows]
    finally:
        con.close()


def load_symbol_df(
    symbol: str,
    db_path: str | Path = DEFAULT_DB_PATH,
    table: str = DEFAULT_TABLE,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    con = _connect(db_path)
    try:
        where = ["symbol = ?"]
        params: list[str] = [symbol.upper()]

        if start_date:
            where.append("date >= ?")
            params.append(start_date)
        if end_date:
            where.append("date <= ?")
            params.append(end_date)

        q = f"""
            SELECT
                date AS Date,
                open AS Open,
                high AS High,
                low AS Low,
                close AS Close,
                volume AS Volume
            FROM {table}
            WHERE {' AND '.join(where)}
            ORDER BY date
        """
        rows = con.execute(q, params).fetchdf()
    finally:
        con.close()

    if rows.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    rows["Date"] = pd.to_datetime(rows["Date"])
    rows = rows.set_index("Date")
    return rows


def load_all_tickers(
    db_path: str | Path = DEFAULT_DB_PATH,
    table: str = DEFAULT_TABLE,
    symbols: Optional[list[str]] = None,
    include_spy: bool = False,
) -> dict[str, pd.DataFrame]:
    if symbols is None:
        symbols = list_symbols(db_path=db_path, table=table, include_spy=include_spy)
    else:
        symbols = [s.upper() for s in symbols if include_spy or s.upper() != "SPY"]

    out: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        df = load_symbol_df(sym, db_path=db_path, table=table)
        if not df.empty:
            out[sym] = df
    return out
