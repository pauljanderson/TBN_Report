# RocketOptimizer.py — Recommendations (Principal-Engineer Level)

## Critical / High Priority

### 1. **DATA_PATH format and quoting**
- **Issue:** `DATA_PATH` is one long string with spaces between paths (e.g. `C:\...\SPY.csv C:\...\*.csv`). Passed into `full_cmd` as a single token; if paths contain spaces or the shell doesn’t expand `*.csv` as intended, AWK may get wrong or truncated arguments.
- **Impact:** Runs can use wrong data or fail silently.
- **Recommendation:** Use a list of path arguments and build the command safely (e.g. list of paths, or proper quoting per path). If you rely on glob expansion, ensure the command is run in a shell and the glob pattern is correct for the working directory.

### 2. **AWK script contract (OUT_FILE and output format)**
- **Issue:** The optimizer passes `-v OUT_FILE="temp_run_core_N.csv"` and expects one line of 55 comma-separated values. The current `portfolio_audit.awk` does not document or implement this “summary line” output; it writes RL_Closed, RL_Open, etc. to timestamped files in OUTPUT_DIR.
- **Impact:** Either the optimizer is for a different/older AWK mode, or the audit script must be updated to support “optimizer mode” (single-line summary to OUT_FILE).
- **Recommendation:** Confirm whether portfolio_audit.awk is supposed to write the 55-column summary. If yes, add a clear code path (e.g. when OUT_FILE is set) that writes that single line and exits. If no, document that RocketOptimizer targets a different script or add the output to the audit script and document the 55-column schema.

### 3. **Typo in current_best_params**
- **Issue:** `"RL_ATR_HIGH": 1110.101` — almost certainly meant `0.101` (typo extra `1`).
- **Recommendation:** Change to `0.101` (or the intended value) and add a one-line comment or assert so ATR High is in a sensible range (e.g. 0–1).

### 4. **Column count and schema validation**
- **Issue:** RESULT_COLUMNS has 55 names; if AWK outputs a different number of columns (or different order), pandas will misalign columns and scoring will use wrong fields.
- **Recommendation:** After reading the temp CSV, check `len(df.columns) == len(RESULT_COLUMNS)` (and optionally check for NaNs in key columns). On mismatch, log the row and return `(val, None)` with a clear message instead of proceeding.

---

## Medium Priority

### 5. **Hard-coded paths**
- **Issue:** `DATA_PATH` and `AWK_SCRIPT` are hard-coded; script assumes it’s run from the directory containing the AWK script.
- **Recommendation:** Derive paths from script location (e.g. `os.path.dirname(os.path.abspath(__file__))`) and/or accept CLI args or a config file for data directory and script path so the same code works from different drives and layouts.

### 6. **Windows-only and shell dependency**
- **Issue:** `start /affinity`, `ctypes.windll.kernel32.SetThreadExecutionState`, and PowerShell memory cleanup are Windows-specific. `full_cmd` is run with `shell=True`.
- **Recommendation:** Document “Windows only” at the top, or wrap OS-specific parts (affinity, prevent_sleep, clean_memory) behind a small platform check and no-op on non-Windows. Avoid `shell=True` if possible by building an argument list and passing it to `subprocess.run(..., shell=False)` so quoting is predictable.

### 7. **Console-unfriendly characters**
- **Issue:** Emoji in print statements (e.g. 🔔, 🚀, ✅, ❌, 📉, ⏱️, ✨) can render poorly in some terminals.
- **Recommendation:** Use plain ASCII (e.g. `[START]`, `[OK]`, `[FAIL]`, `[BETTER DD]`, `[DONE]`) for consistency with the rest of your tooling.

### 8. **Broad except in calculate_score**
- **Issue:** `except: return 0` hides any exception (e.g. KeyError if a column is missing, or type errors).
- **Recommendation:** Use `except Exception as e:` and log the exception and row (or key fields) before returning 0, so bad data or schema drift is visible.

### 9. **Progress and concurrency**
- **Issue:** Progress is saved after each parameter’s batch. If two optimizer instances run in the same directory, they can overwrite each other’s progress and logs.
- **Recommendation:** Use a lock file or a single “optimizer run” directory per run (e.g. timestamped) for progress and log files, or document that only one instance should run at a time.

---

## Low Priority

### 10. **Magic numbers in scoring**
- **Issue:** Weights (0.30, 0.15, 0.20, …) and thresholds (e.g. 20 trades, baseline limits) are literal.
- **Recommendation:** Name them as module-level constants (e.g. `WEIGHT_CES = 0.30`, `MIN_TRADES = 20`) or move to a small config so tuning doesn’t require editing the scoring function body.

### 11. **prevent_sleep / allow_sleep**
- **Issue:** Defined but not called in the provided main(); unclear if they’re used elsewhere or dead code.
- **Recommendation:** If you want to prevent sleep during long runs, call `prevent_sleep()` at start and `allow_sleep()` at end (e.g. in a try/finally). Otherwise remove or comment as “optional.”

### 12. **Duplicate imports**
- **Issue:** `import os` and `import os, sys` appear; `shutil` imported but not used in the snippet.
- **Recommendation:** Single `import os, sys` and remove unused imports (e.g. shutil if not used).

---

## Summary Table

| # | Area | Priority | Action |
|---|------|----------|--------|
| 1 | DATA_PATH format | Critical | Use list of paths and safe command building / quoting |
| 2 | AWK OUT_FILE contract | Critical | Align with portfolio_audit.awk or document alternate script |
| 3 | RL_ATR_HIGH typo | High | Fix 1110.101 → 0.101 (or intended value) |
| 4 | Column validation | High | Check column count and optionally key values before scoring |
| 5 | Hard-coded paths | Medium | Script-relative or config/CLI for paths |
| 6 | Windows/shell | Medium | Document or isolate platform-specific code; prefer no shell |
| 7 | Emoji in prints | Medium | Use ASCII for console-friendly output |
| 8 | except in scoring | Medium | Log exception and context before return 0 |
| 9 | Progress concurrency | Medium | Lock or per-run directory for progress files |
| 10 | Scoring constants | Low | Named constants or config |
| 11 | prevent_sleep usage | Low | Call or remove |
| 12 | Imports | Low | Deduplicate and remove unused |
