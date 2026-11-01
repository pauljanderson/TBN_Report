# Intraday 1-minute store (yfinance)

Research helper for **1-minute** OHLCV from Yahoo Finance via `yfinance`, so you can
build **5 / 10 / 15 / 30-minute** bars locally and backtest. This is **not** wired
into DailyRun yet.

Local store (gitignored under `data/`): see also `data/intraday/HOW_TO.md` next to the files.

## Layout

| Path | Contents |
|------|----------|
| `data/intraday/1m/{SYMBOL}.parquet` | Canonical 1m store (one file per symbol) |
| `data/intraday/{5m,10m,15m,30m}/` | Optional resample cache (`--cache`) |

Daily OHLC remains under `data/newdata/data/{SYMBOL}.csv` (pygetallMore / DuckDB). Do not mix.

## Schema and timezone

Columns: `ts`, `open`, `high`, `low`, `close`, `volume`, `symbol`

- **`ts` is timezone-aware US/Eastern** (`America/New_York`, DST-aware).
- Prices rounded to 6 decimals (same idea as daily DuckDB upsert).
- Upsert key: `(symbol, ts)` — duplicates keep the latest fetch.
- Resample default: **left-labeled** bars (a `5m` bar at 09:30 covers 09:30–09:34 ET).

## Yahoo / yfinance limits (important)

- Interval `1m`: typically **~7 calendar days per request**.
- Yahoo usually retains only about **~30 days** of 1-minute history total.
- Longer archives require **rolling incremental updates** (fetch often; grow your parquet).
- 1m bars are **not tick data**; sessions have **gaps** (halts, missing minutes, pre/post excluded by default). Label any backtest as **research / approximate**.

## How to run

From repo root:

```bash
# Smoke / liquid names
python tools/fetch_intraday_1m.py -s SPY,AAPL --lookback-days 5

# Universe file (one ticker per line)
python tools/fetch_intraday_1m.py --universe data/rl_gold_universe.txt --lookback-days 7

# All daily CSV symbols (slow; respect --sleep)
python tools/fetch_intraday_1m.py --all --lookback-days 3 --sleep 1.0
```

Incremental behavior: if `{SYMBOL}.parquet` exists, the tool fetches from roughly
`max(ts) - 1 day` through now (still capped by lookback / Yahoo retention), merges,
dedupes, and rewrites the file. Use `--force-full-window` to re-pull the whole lookback.

### Resample (on demand)

```bash
python tools/resample_intraday.py -s SPY,AAPL --tf 5m
python tools/resample_intraday.py -s SPY --tf 15m --cache
python tools/resample_intraday.py -s AAPL --tf 30m --out-csv data/intraday/_scratch/AAPL_30m.csv
```

v1 default: **on-demand** from the 1m store. `--cache` optionally writes
`data/intraday/{tf}/{SYMBOL}.parquet`.

## Rate limits

Default `--sleep 0.75` between windows/symbols, with retries and exponential backoff.
Increase sleep for large universes. Do not blast `--all` without pacing.

## Suggested schedule (manual / Task Scheduler)

| Cadence | Why |
|---------|-----|
| **Daily after close** (e.g. 18:00 ET) | Capture the day’s 1m bars while still inside Yahoo’s short retention |
| **Or twice weekly** | Minimum if you only need a rolling ~2-week research window |

Empty days / holidays: upsert is a no-op merge (no new rows).

## DailyRun (optional later — not wired)

Daily pipeline today: `run_update_data.bat` → `pygetallMore` → daily CSV + `data/ohlcv.duckdb`.

To auto-fetch intraday later (do **not** treat as gold from wiring alone):

1. Add something like `run_fetch_intraday_1m.bat` calling
   `python tools/fetch_intraday_1m.py --universe <csv> --lookback-days 5`.
2. Optionally call it from `DailyRun.bat` behind `SKIP_INTRADAY=1` (same pattern as VZ / WRL comments).
3. Keep it **after** the daily update step; failures should not block BRT/RS unless you choose that.
4. Start with a **small liquid universe** (SPY + Mag10 / Paul list), not `--all`.

## Research disclaimer

Yahoo 1m + our resample is for **hypothesis / microstructure-style research**, not
production fills. Gaps and Yahoo corrections mean bar boundaries can differ from a
broker or Polygon feed.
