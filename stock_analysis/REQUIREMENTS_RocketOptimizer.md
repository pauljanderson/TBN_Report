# RocketOptimizer.py — Requirements (Reverse-Engineed)

## Purpose
Runs a parameter grid over `portfolio_audit.awk`, scores each run on risk/return metrics (CES, Ann ROR, Profit Factor, Max DD, P90 days), keeps the best parameter set and “ratchets” baselines so later rounds cannot worsen risk. Progress is persisted so runs can be resumed; final best settings are written to a JSON file.

---

## 1. Inputs and Configuration

| Item | Description |
|------|-------------|
| **AWK_SCRIPT** | Filename of the audit script (e.g. `portfolio_audit.awk`). Run from the directory containing the script. |
| **DATA_PATH** | Single string: space-separated paths to SPY CSV and data CSVs (e.g. `path\to\SPY.csv path\to\*.csv`). Passed as-is into the shell command that runs AWK. |
| **OPTIMIZATION_PLAN** | Dict mapping parameter names to tuples of values to try (e.g. `"RL_TRAIL_PROFIT2": (0.4, 0.39, ...)`). Only one parameter is optimized at a time; others come from `current_best_params`. |
| **current_best_params** | Dict of all parameters the AWK script accepts. Used as the baseline; the “winner” of each parameter’s grid overwrites that key. |
| **Baselines (ratchet)** | `current_baseline_dd`, `current_baseline_ces`, `current_baseline_p90`. Any candidate that worsens these (higher DD, lower CES, higher P90) is rejected (score 0). DD baseline can be updated when a winner improves it. |

---

## 2. AWK Output Schema

The script assumes AWK writes a single-line CSV with no header and exactly 55 columns, in this order (RESULT_COLUMNS):

- **Drive, Cash, Qual, Dip, Stop, Target, Exp, AccMin, AccCnt, TooHi, TP1, TS1, TP2, TS2, AtHi, AtLo, SlopePd, SlopeTh**
- **ExitDays, ExitPct, PartTarget, PartPct, PartFollow**
- **PNL, Wins, Losses, BE, PctWin, PctLoss, WLRatio, Profit_Factor**
- **MaxStreak, AvgWin, AvgLoss, AvgPNL, Expectancy**
- **OpenW, OpenValW, AvgOpenW, OpenL, OpenValL, AvgOpenL**
- **Toggle100, PNL100, Wins100, Losses100**
- **AvgDays, MedDays, Ann_ROR, Max_DD**
- **Avg_CES, MedCES, P90_Days, TimedExitCnt, TotalHoldDays**
- **Max_Pos, Avg_Pos, Med_Pos**

Scoring uses: `Wins`, `Losses`, `BE`, `Max_DD`, `Avg_CES`, `P90_Days`, `Ann_ROR`, `Profit_Factor`.

---

## 3. Processing Logic

1. **Progress**  
   Load `optimizer_progress.json` if present: `completed_params` (list of parameter names already optimized) and `best_params` (current best full set). Otherwise start from `current_best_params`.

2. **Parameter coverage**  
   For any key in OPTIMIZATION_PLAN that is missing from `best_params`, set it to the first value in that parameter’s tuple so the first AWK run has a full set.

3. **Per-parameter optimization**
   - For each `param_name` in OPTIMIZATION_PLAN: if already in `completed_params`, skip.
   - Build one task per value: `(test_params, core_idx, val)` where `test_params = best_params.copy()` and `test_params[param_name] = val`. Core index cycles 0–7 for affinity.
   - Run up to 8 tasks in parallel via `ThreadPoolExecutor`. Each task runs a **Windows** shell command: `start /affinity <mask> /wait /b awk -f "<AWK_SCRIPT>" -v Param1=Val1 ... -v OUT_FILE="temp_run_core_<i>.csv" <DATA_PATH>`.
   - Worker reads `temp_run_core_<i>.csv`, assigns RESULT_COLUMNS, returns `(val, row_dict)` or `(val, None)` on failure.
   - After each batch: normalize metrics (max CES, ROR, PF; min DD, P90) across the batch; score each row with `calculate_score()`; sort by score descending; winner updates `best_params[param_name]` and optionally ratchets `current_baseline_dd`.
   - Append winner row to `Optimization_Master_Log.csv` and full batch (with `Iterated_Param`) to `Global_Optimization_Audit.csv`. Save progress to `optimizer_progress.json`.

4. **Scoring**
   - **Rejection:** Score = 0 if: `Max_DD > current_baseline_dd`, or `Avg_CES < current_baseline_ces`, or `P90_Days > current_baseline_p90`, or `Wins + Losses + BE < 20`.
   - **Otherwise:** Normalized components (row vs batch max/min); weighted sum: CES 30%, ROR 15%, PF 20%, DD 20%, P90 10%, trade count 5%. Higher score = better.

5. **Final output**  
   Write `best_params` (with NumPy types converted to native Python) to `Final_Optimized_Settings.txt` as JSON.

6. **Side effects**
   - **prevent_sleep** (Windows): SetThreadExecutionState so the machine doesn’t sleep during long runs (not called in the provided snippet; may be used elsewhere or omitted).
   - **clean_memory**: After each AWK run, invoke PowerShell to EmptyWorkingSet on all processes. Called in the worker after each subprocess run.

---

## 4. Assumptions

- AWK script accepts `-v Param=Value` for all keys in `current_best_params` and writes one line of comma-separated numbers to the path given by `-v OUT_FILE=...`. (portfolio_audit.awk may need to be run in a mode that writes this summary line; current audit script may not set OUT_FILE.)
- Windows: `start /affinity`, `awk` in PATH, PowerShell available for memory cleanup. ctypes for SetThreadExecutionState.
- Working directory when running the script is the directory containing the AWK script (so `AWK_SCRIPT` and DATA_PATH resolve as intended).
- DATA_PATH is passed as a single string to the shell; the shell expands any `*.csv` in it.

---

## 5. Error Handling

- Worker: subprocess or CSV read failure returns `(val, None)` and prints an error; that value is skipped in the batch.
- No validation that the AWK output file actually has 55 columns; misalignment would cause column/name errors or wrong scoring.

---

## 6. Dependencies

- Python 3, pandas, subprocess, concurrent.futures, glob, time, json, ctypes, os, sys, shutil.
- Windows: awk (or gawk) in PATH, PowerShell, kernel32 for sleep prevention.
