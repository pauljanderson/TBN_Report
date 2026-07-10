import argparse
import sys
from pathlib import Path

import duckdb

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO / "stock_analysis") not in sys.path:
    sys.path.insert(0, str(_REPO / "stock_analysis"))

try:
    from ohlcv_store import prune_orphan_symbols
except ImportError:
    prune_orphan_symbols = None


def _quote_path(path: Path) -> str:
    return str(path).replace("'", "''")


def build_database(data_dir: Path, db_path: Path, table_name: str, replace: bool) -> None:
    if not data_dir.exists() or not data_dir.is_dir():
        raise FileNotFoundError(f"Data directory not found: {data_dir}")

    csv_glob = data_dir / "*.csv"
    csv_files = list(data_dir.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in: {data_dir}")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        if replace:
            con.execute(f"DROP TABLE IF EXISTS {table_name}")

        con.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                symbol VARCHAR NOT NULL,
                date DATE NOT NULL,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume DOUBLE,
                source_file VARCHAR,
                loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # Supports typical OHLCV per-ticker CSVs where symbol is in filename.
        # If a CSV is missing Volume, it is loaded as NULL.
        con.execute(
            f"""
            INSERT INTO {table_name} (symbol, date, open, high, low, close, volume, source_file)
            SELECT
                UPPER(regexp_extract(filename, '([^\\\\/]+)\\.csv$', 1)) AS symbol,
                CAST("Date" AS DATE) AS date,
                CAST("Open" AS DOUBLE) AS open,
                CAST("High" AS DOUBLE) AS high,
                CAST("Low" AS DOUBLE) AS low,
                CAST("Close" AS DOUBLE) AS close,
                CASE WHEN "Volume" IS NULL THEN NULL ELSE CAST("Volume" AS DOUBLE) END AS volume,
                filename AS source_file
            FROM read_csv_auto('{_quote_path(csv_glob)}', filename=true, union_by_name=true)
            WHERE "Date" IS NOT NULL
            """
        )

        con.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_symbol_date ON {table_name}(symbol, date)")
        con.execute(f"ANALYZE {table_name}")

        row_count = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        sym_count = con.execute(f"SELECT COUNT(DISTINCT symbol) FROM {table_name}").fetchone()[0]
        min_max = con.execute(
            f"SELECT MIN(date), MAX(date) FROM {table_name}"
        ).fetchone()
    finally:
        con.close()

    print(f"Database written: {db_path}")
    print(f"Table: {table_name}")
    print(f"Rows: {row_count:,}")
    print(f"Symbols: {sym_count:,}")
    print(f"Date range: {min_max[0]} -> {min_max[1]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a local DuckDB OHLCV store from per-symbol CSV files.")
    parser.add_argument("--data-dir", type=str, default="data/newdata/data", help="Folder with per-symbol CSV files.")
    parser.add_argument("--db-path", type=str, default="data/ohlcv.duckdb", help="Output DuckDB file path.")
    parser.add_argument("--table", type=str, default="prices", help="Target table name.")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Drop and rebuild table before ingesting.",
    )
    parser.add_argument(
        "--prune-only",
        action="store_true",
        help="Only remove DuckDB symbols not in pygetallMore TICKERS and/or missing CSV files.",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir).resolve()
    db_path = Path(args.db_path).resolve()

    if args.prune_only:
        if prune_orphan_symbols is None:
            raise RuntimeError("ohlcv_store.prune_orphan_symbols is unavailable.")
        pruned = prune_orphan_symbols(db_path, data_dir, args.table)
        print(f"Pruned {len(pruned)} orphan symbol(s) from {db_path}")
        if pruned:
            print(", ".join(pruned))
        return

    build_database(
        data_dir=data_dir,
        db_path=db_path,
        table_name=args.table,
        replace=args.replace,
    )

    if prune_orphan_symbols is not None:
        pruned = prune_orphan_symbols(db_path, data_dir, args.table)
        if pruned:
            print(f"Pruned {len(pruned)} orphan symbol(s) after build: {', '.join(pruned[:12])}")


if __name__ == "__main__":
    main()
