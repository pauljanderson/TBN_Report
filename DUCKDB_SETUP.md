# DuckDB OHLCV Setup

This project now includes a local DuckDB store for OHLCV data.

## 1) Build the database

```bash
python scripts/build_ohlcv_duckdb.py --data-dir data/newdata/data --db-path data/ohlcv.duckdb --replace
```

What this creates:
- DuckDB file: `data/ohlcv.duckdb`
- Table: `prices`
- Index: `(symbol, date)`

## 2) Query from Python

Use `stock_analysis/ohlcv_store.py`:
- `list_symbols(...)`
- `load_symbol_df("AAPL", ...)`
- `load_all_tickers(...)`

The returned DataFrame shape matches the existing CSV loader:
- Index: `Date`
- Columns: `Open`, `High`, `Low`, `Close`, `Volume`

## 3) Current status

Built in this workspace with:
- Rows: 2,686,323
- Symbols: 1,084 (including `SPY`)
- Date range: 2016-01-04 to 2026-04-24

## 4) Next integration step

Wire `rocket_brt.py` so it can load from DuckDB via a flag (while keeping CSV fallback).
