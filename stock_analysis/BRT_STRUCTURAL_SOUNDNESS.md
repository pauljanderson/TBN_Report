# BRT System — Structural Soundness Checklist

Recommendations to keep the BRT backtest and reporting pipeline structurally sound: backtest integrity, reproducibility, data quality, and operational robustness.

---

## 1. Backtest integrity (already in good shape)

- **Entry timing:** Signal on bar `i`, entry at **next bar open** (`next_op`) — no look-ahead. ✓
- **Exit timing:** Exit uses bar `i` only (gap at open, or intraday stop/target/close). ✓
- **Pivot confirmation:** Uses **future bars only** (j+1 … j+m) per BRT_LOGIC_SPEC — no leakage. ✓

**Consider adding:**
- **Explicit “point-in-time” note in docs:** State that the backtest uses only data available at bar `i` (no future data). Helps auditors and future you.
- **Survivorship bias:** If your CSV universe is “current names only,” backtest results ignore delisted/failed names. Document the universe (e.g. “SPY constituents as of YYYY-MM”) or run on a point-in-time universe if you need unbiased stats.
- **Slippage / execution:** Currently assumes fill at exact open/stop/target. Optional: document as “theoretical” or add a small slippage/commission layer for realism.

---

## 2. Config and reproducibility

- **Config in report:** BRT_Report already includes config (band_pct, touch_threshold, etc.). ✓
- **Run timestamp:** Every output is stamped (`BRT_Closed_<ts>.csv`) so runs are distinguishable. ✓
- **Parallel workers:** Config is serialized with `asdict(cfg)` and rebuilt in workers as `BRTConfig(**cfg_dict)` — same config everywhere. ✓

**Consider adding:**
- **Config version or hash:** Write a short config digest (e.g. hash of sorted key=value) into BRT_Report or a dedicated line so “same config” is trivial to verify across runs.
- **Config validation:** Validate bounds at startup (e.g. `touch_threshold` in 1..20, `band_pct` in 0.001..0.5, `lookback_long` > 0). Fail fast with a clear message instead of silent nonsense.
- **Deterministic ordering:** Ensure symbol processing order is fixed (e.g. sorted ticker list) so that with the same data and config, BRT_Closed row order is reproducible (you already sort; keep it and document it).

---

## 3. Data quality

- **OHLCV load:** `load_csv` normalizes Date/OHLC and keeps Volume when present. ✓
- **Min bars:** Symbols with too few rows are skipped (`len(df) >= pivot_k + pivot_m + 10`). ✓

**Consider adding:**
- **Input validation:** Reject or flag rows where High < Low, or Close outside [Low, High], or negative OHLC/Volume. Optionally drop bad rows and log count.
- **Missing data:** Define policy for NaN/empty in OHLC (e.g. forward-fill once, or drop bar, or skip symbol) and document it.
- **Universe documentation:** In BRT_Report or a small meta file, record: data path, file count (or symbol list hash), and date range (min/max date across all files). Makes “what did this run use?” unambiguous.

---

## 4. Sanity checks on outputs

**Consider adding (in rocket_brt or in a post-step):**
- **Closed trades:** No duplicate (SYMBOL, DATE_OPENED); DATE_CLOSED >= DATE_OPENED; EXIT_PRICE and PNL_PCT consistent with ENTRY_PRICE.
- **Open trades:** DATE_OPENED not in the future; ENTRY_PRICE > 0.
- **Scanner:** Optional check that scanner symbols exist in the data and have not already been opened (if you track global open list).
- **Correlation report:** BRT_Correlation runs on the same BRT_Closed; ensure row count matches (e.g. no accidental truncation).

These can be a small `validate_brt_output()` run after writes, or a separate script; on failure, exit non-zero or write to a BRT_Validation_<ts>.txt.

---

## 5. Error handling and logging

- **yfinance/correlation:** Already wrapped in try/except so one bad symbol or missing module does not kill the run. ✓
- **Worker errors:** If a worker in ProcessPoolExecutor raises, the main process can raise when calling `future.result()`. Consider a try/except per future to log the symbol and error, then continue (or collect failed symbols and exit 1 at the end).

**Consider adding:**
- **Structured logging:** Option to log to a file (e.g. BRT_Run_<ts>.log) with timestamps and levels (INFO/WARNING/ERROR) instead of only print. Helps debugging and auditing.
- **Exit codes:** Document exit codes (0 = success, 1 = validation/regression failure, 2 = data/config error) and use them consistently from rocket_brt and run_brt.ps1.

---

## 6. Regression and tests

- **BRTRegressionCheck.ps1:** Compares current vs previous run; can fail on diff. ✓
- **Perfect Setups check:** check_perfect_setups.py validates a fixed set of trades. ✓

**Consider adding:**
- **Unit tests:** Small tests for: pivot logic (known bar → known pivot), touch count on a tiny series, one-symbol backtest with fixed CSV and config → expected number of trades. Speeds up refactors and prevents regressions.
- **Golden run:** Periodically archive a “golden” BRT_Closed (or key metrics) for a fixed data snapshot and config; CI or nightly job compares new run to golden and alerts on drift.

---

## 7. Risk and reporting clarity

- **Metrics:** compute_metrics and BRT_Report expose wins, losses, PnL, profit factor, etc. ✓
- **Drawdown:** BRT_DrawdownCalc (optional) for Max_DD and underwater. ✓

**Consider adding:**
- **Concentration:** In BRT_Report or summary, report max % of total PnL from a single symbol (or single trade) so you can spot over-concentration.
- **Per-symbol stats:** Already have BRT_Summary; ensure it’s enough for “which names drive results” and document it.
- **Market cap / sector in report:** You now have MARKET_CAP (at entry), SECTOR, INDUSTRY in BRT_Closed/Open; optional: add a one-line summary (e.g. “BRT_Closed: N trades, avg market cap $X, sectors: …”) in BRT_Report or Correlation doc.

---

## 8. Quick wins (low effort)

1. **Config validation:** Validate a few key params (e.g. touch_threshold, band_pct, lookback_long) at startup in rocket_brt; raise with a clear message if out of range.
2. **Data validation:** In load_csv, check High >= Low and OHLC > 0 (or flag and drop); log number of dropped rows.
3. **Worker error handling:** In the parallel loop, catch exceptions from `future.result()`, log symbol and error, optionally collect failed symbols and exit 1 after all futures.
4. **Docstring in main:** In rocket_brt, add a one-line note: “Backtest is point-in-time: at bar i only data up to and including bar i is used; entry at next bar open.”

---

## Summary

The BRT design is already sound on entry/exit timing and config propagation. The main levers to make it more robust are: **config and input validation**, **explicit data-quality and output sanity checks**, **better error handling in workers and logging**, and **lightweight tests plus a golden run**. Prioritize config validation and input validation first; then add a small validation pass on BRT_Closed/Open and worker error handling.
