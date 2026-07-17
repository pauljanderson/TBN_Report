# DrawdownCalc.py — Recommendations (Principal-Engineer Level)

## Critical / High Priority

### 1. **Broken control flow and redundant load**
- **Issue:** `run_audit()` first loads Closed/Open CSVs (lines ~134–146), runs diagnostics, then later checks `len(sys.argv) < 2` and overwrites `closed_path`/`ticker_dir` from `sys.argv`. The main loop (lines 200+) re-reads from `task_list` and never uses the initially loaded `df_closed`/`df_open`.
- **Impact:** Confusing, duplicate I/O, and the early “usage” return is misleading (we’re already inside a call that had argv).
- **Recommendation:** Have a single entry point: parse `sys.argv` once at the top of `__main__`; pass `closed_path` and `ticker_dir` into `run_audit()`. Inside `run_audit()`, load each file once and use those DataFrames for both diagnostics and the reconstruction loop (build in-memory structures from the DataFrames instead of re-reading from disk).

### 2. **Bug in `clean_numeric`**
- **Issue:** Line 25 strips `'%'` from the string, then line 26 checks `'%' in str(val)` (always false), so the “divide by 100” branch for percentages never runs.
- **Recommendation:** Either (a) check for `'%'` before stripping and set a flag, or (b) if the intent is “value may be stored as 5 for 5%”, divide by 100 only when the original string contained `%`: e.g. `was_pct = '%' in str(val)` before stripping, then use it after parsing the float.

### 3. **Bare `except` clauses**
- **Issue:** `except: continue` (and similar) hide all errors (e.g. KeyError, type errors, file format issues).
- **Recommendation:** Use `except Exception as e:` and at least log (e.g. `print(f"Skip symbol {symbol}: {e}")` or a logger). Optionally re-raise or exit on truly fatal errors.

### 4. **Hard-coded paths and constants**
- **Issue:** `RL_CASH = 47500`, `initial_account_size = RL_CASH * 12`, chart save path `../drive/`, output filename `daily_equity_debug.csv` in cwd.
- **Recommendation:** Make these configurable: CLI args (e.g. `--cash`, `--output-dir`) or a small config (env vars / JSON). Defaults can match current behavior.

---

## Medium Priority

### 5. **Console-unfriendly characters**
- **Issue:** Print statements use ✅, ❌, 📂, 📊, 📈; can render as garbage in some Windows consoles.
- **Recommendation:** Use plain ASCII (e.g. `[OK]`, `[ERR]`, `[FILE]`) so output is consistent with your console-friendly AWK audit.

### 6. **Dead / unused code**
- **Issue:** `generate_underwater_report`, `calculate_stagnation`, `update_rocketlauncher_summary` are never called. Comment block (lines 104–114) shows example integration that doesn’t run.
- **Recommendation:** Either wire them into the main flow (e.g. call `generate_underwater_report` after building the equity series and optionally `update_rocketlauncher_summary` with max DD / stagnation) or remove them (or move to a separate “reporting” module) so the main script’s behavior is clear.

### 7. **Diagnostic output always on**
- **Issue:** `diagnostic_check()` runs on every run and prints DataFrames and column samples.
- **Recommendation:** Gate behind a flag (e.g. `--diagnose` or `DEBUG=1`) so production runs from AWK stay quiet unless debugging.

### 8. **Chart path and cwd**
- **Issue:** `save_path = os.path.join("../drive/", save_name)` and `daily_equity_debug.csv` in cwd assume a fixed repo layout and who invokes the script.
- **Recommendation:** Use an output directory argument (default e.g. current dir or same dir as Closed file); write chart and debug CSV there so behavior is predictable when called from AWK or from different working directories.

---

## Low Priority

### 9. **Type and column contracts**
- **Recommendation:** Add a short docstring or comment at the top listing required Closed/Open columns and expected types (e.g. DATE OPENED as YYYYMMDD integer). Optionally validate columns at load time and fail fast with a clear message.

### 10. **Duplicate timestamp / task_list logic**
- **Issue:** Timestamp is extracted and Open file is discovered twice (once near the start of `run_audit`, once around 166–184).
- **Recommendation:** After fixing (1), do timestamp extraction and task_list construction once and pass the result into a single “process and chart” function.

---

## Summary Table

| # | Area | Priority | Action |
|---|------|----------|--------|
| 1 | Control flow / double load | Critical | Single argv parse, single load, pass paths into run_audit |
| 2 | clean_numeric % handling | Critical | Fix percentage detection so % values are scaled correctly |
| 3 | Bare except | High | Replace with except Exception and log |
| 4 | Hard-coded paths/constants | High | CLI or config for cash, output dir, chart path |
| 5 | Emoji in prints | Medium | Use ASCII for console-friendly output |
| 6 | Unused helpers | Medium | Wire in or remove underwater/stagnation/summary |
| 7 | Diagnostic noise | Medium | Optional --diagnose |
| 8 | Chart/debug paths | Medium | Output dir argument |
| 9 | Column contract | Low | Document/validate required columns |
| 10 | Duplicate logic | Low | Single place for timestamp and task_list |
