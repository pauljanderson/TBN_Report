# DrawdownCalc.py — Requirements (Reverse-Engineered)

## Purpose
Reconstructs daily portfolio equity from Rocket Launcher closed (and optionally open) trade CSVs plus per-symbol OHLC data, computes portfolio-level max drawdown, optionally benchmarks vs SPY, and produces a chart and debug outputs.

---

## 1. Inputs

| Input | Source | Description |
|-------|--------|-------------|
| **RL_Closed CSV** | CLI arg 1 | Path to `RL_Closed_<timestamp>.csv` from portfolio_audit.awk. Must contain at least: `SYMBOL`, `DATE OPENED`, `DATE CLOSED`, `ENTRY PRICE`, `EXIT PRICE`. |
| **Ticker directory** | CLI arg 2 (optional) | Directory containing one CSV per symbol (e.g. `AAL.csv`) and optionally `SPY.csv`. Default: `data/`. Each file must have `Date` and `Close` (and optionally Open/High/Low). |
| **RL_Open CSV** | Auto-discovered | In the same directory as the Closed file, a file whose name contains the same 12-digit timestamp and the substring `"open"` (case-insensitive). Used to extend unrealized P&L to latest date. |

---

## 2. Processing Logic

1. **Timestamp extraction**  
   From the Closed file path, extract a 12-digit run id (e.g. `260220084455`) via regex. Used to find the matching Open file and in output filenames.

2. **Task list**  
   Build list of `(file_type, path)`: always `('Closed', closed_path)`; if an Open file is found, add `('Open', open_path)`.

3. **Daily P&L reconstruction**
   - **RL_CASH**: Fixed 47,500 (position size per trade).
   - **Initial account size**: `RL_CASH * 12`.
   - For each trade (Closed and Open): resolve symbol CSV in ticker_dir; parse `DATE OPENED` (and for Closed, `DATE CLOSED`); for Open, end date = max date in ticker file and “exit” price = last Close.
   - For each calendar day in the trade’s date range: mark symbol as active that day; compute P&L for that day using entry price, shares = `RL_CASH / entry_p`, and that day’s Close (or actual exit on last day). On the last day of a Closed trade, add P&L to **realized**; otherwise add to **unrealized**.
   - **Unrealized**: Summed by date across all open positions (multiple symbols contribute to the same date).
   - **Realized**: Summed by date from closed trades.

4. **Date range**
   - Collect all dates that have at least one active symbol.
   - If the latest ticker date is after the last trade date, extend the timeline day-by-day, carrying forward the last unrealized P&L and active-symbol set so equity is continuous to “today.”

5. **Equity series**
   - For each date: `equity = initial_account_size + cumsum(realized up to that date) + unrealized for that date`.
   - Track portfolio HWM and compute drawdown: `(HWM - equity) / HWM`; record max drawdown and trough/peak dates.

6. **SPY benchmark (optional)**
   - If `SPY.csv` exists in ticker_dir: build a synthetic “SPY equity” series starting from `initial_account_size` at the first date, scaled by SPY’s cumulative return over the same dates.

7. **Outputs**
   - **Chart**: Line plot of portfolio equity and (if available) SPY equity; secondary axis = active position count; annotation at max-DD trough. Saved as PNG (path hard-coded to `../drive/` + `Portfolio_Performance_<timestamp>.png`).
   - **Debug CSV**: `daily_equity_debug.csv` in current working directory: columns `Date`, `Equity`.
   - **Console**: Summary lines for Max DD, peak date, trough date.

---

## 3. Helper Functions (Defined but Not Used in Main Flow)

- **clean_numeric(val)**  
  Coerce to float; strip `%` and `,` from strings; interpret as percentage when applicable. Used when reading ENTRY PRICE / EXIT PRICE.

- **generate_underwater_report(df_equity, timestamp)**  
  From an equity series, compute underwater periods (equity < HWM), group them, compute trough/HWM/recovery and duration; write `RL_underwater_<timestamp>.csv`. **Not called** by current main path.

- **calculate_stagnation(df_sys, df_spy)**  
  Merge system equity and SPY by date; compute 20-day rolling returns; define “stagnation” as SPY up >2% and system up <0.5%; return % of days stagnant. **Not called**.

- **update_rocketlauncher_summary(summary_path, metrics_dict)**  
  Append metrics as new columns to the last row of a summary CSV (e.g. rocketlauncher.csv). **Not called**.

- **diagnostic_check(df, label)**  
  Print column names, first two rows, and date-column samples. **Called** after loading Closed and Open CSVs.

---

## 4. Assumptions

- Closed CSV has numeric `DATE OPENED` / `DATE CLOSED` as integer YYYYMMDD (or float that converts to it).
- Ticker CSVs have a `Date` column parseable by pandas and a `Close` column.
- All paths may be relative to current working directory; chart output uses a fixed relative path `../drive/`.
- No explicit timezone; dates are treated as calendar days.

---

## 5. Error Handling

- Missing `DATE OPENED` in Closed CSV: print error and return.
- Missing ticker file for a symbol: skip that trade (silent continue).
- Exceptions during row/ticker processing: bare `except: continue` (fail silently per trade).
- CLI: if `len(sys.argv) < 2`, usage is printed and script returns (redundant with later overwrite of `closed_path` from `sys.argv[1]`).

---

## 6. Dependencies

- Python 3 with pandas, matplotlib (and numpy if used).
- Invocation: typically from portfolio_audit.awk via `system("python DrawdownCalc.py <closed_file> <ticker_dir>")` after the Closed file is written.
