# DuckDB OHLCV setup

Local DuckDB mirror of daily OHLCV for fast engine loads. Canonical CSVs remain
under `data/newdata/data/`. Architecture context: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## 1) Build / rebuild

```bat
python scripts\build_ohlcv_duckdb.py --data-dir data\newdata\data --db-path data\ohlcv.duckdb --replace
```

Creates:

- File: `data/ohlcv.duckdb`
- Table: `prices`
- Index: `(symbol, date)`

Nightly `pygetallMore` (via `run_update_data.bat`) upserts CSVs and keeps the DB
in sync when wired; rebuild after bulk backfills.

## 2) Query from Python

Use `stock_analysis/ohlcv_store.py`:

- `list_symbols(...)`
- `load_symbol_df("AAPL", ...)`
- `load_all_tickers(...)`

Returned DataFrame shape matches the CSV loader:

- Index: `Date`
- Columns: `Open`, `High`, `Low`, `Close`, `Volume`

Default DB path is **repo-relative**:
`Path(__file__).parent.parent / "data" / "ohlcv.duckdb"`.

## 3) Engine integration (current)

`stock_analysis/rocket_tbn.py` loads via DuckDB when requested / discovered
(`--use-duckdb` / nearby `ohlcv.duckdb` with a `prices` table). YH/WPBR and other
wave jobs often open the DB **read-only**.

**Windows lock:** only one writer (or exclusive connection) at a time. Do not run
two DuckDB-writing jobs in parallel. DailyRun’s wave assumes read-only opens for
price DBs; see `ohlcv_store._duckdb_lock_help`.

## 4) Status note

Row/symbol counts change after every data update — do not treat a fixed count in
docs as authoritative. Inspect locally:

```bat
python -c "import duckdb; c=duckdb.connect('data/ohlcv.duckdb', read_only=True); print(c.execute('select count(*), count(distinct symbol), min(date), max(date) from prices').fetchone())"
```

## 5) Path debt

`pygetallMore.py` and `ohlcv_store.py` both default to repo-relative
`data/ohlcv.duckdb` (fixed 2026-11-06). Research one-offs under `tools/` may
still hardcode the old Downloads path — audit:

```bat
python repo_split\lib\rewrite_paths.py --root C:\Users\songg\code\TBN --audit-only
```
