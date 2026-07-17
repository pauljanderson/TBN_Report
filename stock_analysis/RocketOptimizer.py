"""
RocketOptimizer: Grid-optimizes Rocket Launcher parameters by running portfolio_audit.awk
with different -v settings, scoring on CES/ROR/PF/DD/P90, and ratcheting risk baselines.

Improvements made:
- MAX_WORKERS=8 for parallel optimization (set lower if you see AWK memory errors).
- prevent_sleep()/allow_sleep() so the machine does not sleep during long runs.
- Exception logging in calculate_score() for easier debugging.
- SPY_Inclusion and RL_Flush_Days in RESULT_COLUMNS; AWK outputs them after PartFollow.
- RL_ATR_HIGH=0.105, RL_ATR_LOW=0.019 in defaults and progress/settings files.
- AWK maps -v RL_ATR_HIGH/RL_ATR_LOW to RL_ATR_HIGH_PERCENT/RL_ATR_LOW_PERCENT.

If you see "can't allocate" memory errors from AWK, set MAX_WORKERS = 2 and re-run.
"""
import subprocess
import pandas as pd
import os
from concurrent.futures import ThreadPoolExecutor
import glob
import time
import json
import ctypes
import os
import sys
import shutil
import threading


# --- CONFIGURATION ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
AWK_SCRIPT = os.path.join(SCRIPT_DIR, "portfolio_audit.awk")
# Paths passed to AWK; each quoted for safe shell use
DATA_PATHS = [
    r"C:\Users\songg\Downloads\stockresearch\data\newdata\data\SPY.csv",
    r"C:\Users\songg\Downloads\stockresearch\data\newdata\data\*.csv",
]
TEMP_RESULT = "temp_run.csv" # Temporary file for the current test
MASTER_LOG = "Optimization_Master_Log.csv" # PERSISTENT: All winners go here
BEST_SETTINGS_FILE = "Final_Optimized_Settings.txt"
GLOBAL_AUDIT_LOG = "Global_Optimization_Audit.csv"
ALL_RUNS_FILE = "Optimizer_All_Runs.csv"  # Every single AWK run appended here (no overwrites)
PROGRESS_FILE = "optimizer_progress.json"
OUTPUT_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "drive")  # Where AWK writes RL_Closed, DiveBomber.csv, etc.
DIVEBOMBER_CSV = os.path.join(OUTPUT_DIR, "DiveBomber.csv")
_all_runs_lock = threading.Lock()
# Fewer workers reduce memory pressure; each AWK run loads all CSVs. If you see "can't allocate" errors, set to 2.
MAX_WORKERS = 1

# --- AWK OUTPUT SCHEMA (must match portfolio_audit.awk summary line) ---
RESULT_COLUMNS = [
    'Drive', 'Cash', 'Qual', 'Dip', 'Stop', 'Target', 'Exp', 'AccMin', 'AccCnt',
    'TooHi', 'TP1', 'TS1', 'TP2', 'TS2', 'AtHi', 'AtLo', 'SlopePd', 'SlopeTh',
    'ExitDays', 'ExitPct', 'PartTarget', 'PartPct', 'PartFollow',
    'SPY_Inclusion', 'RL_Flush_Days', 'AVG_VOL_DAYS', 'VOL_PCT_THRESHOLD',
    'PNL', 'Wins', 'Losses', 'BE', 'PctWin', 'PctLoss', 'WLRatio', 'Profit_Factor',
    'MaxStreak', 'AvgWin', 'AvgLoss', 'AvgPNL', 'Expectancy', 'OpenW', 'OpenValW',
    'AvgOpenW', 'OpenL', 'OpenValL', 'AvgOpenL', 'Toggle100', 'PNL100', 'Wins100',
    'Losses100', 'AvgDays', 'MedDays', 'Ann_ROR', 'Max_DD',
    'Avg_CES', 'MedCES', 'P90_Days', 'TimedExitCnt', 'TotalHoldDays', 'ProfitPerCapDay',
    'Pct_Time_Underwater', 'Max_Consec_Underwater', 'Max_Pos'
]
# 61 columns total (matches AWK summary line; includes ProfitPerCapDay, time-underwater metrics, max positions)
EXPECTED_COLS = len(RESULT_COLUMNS)

# --- DYNAMIC OPTIMIZATION 2.0 BASELINES ---
# These will "ratchet" throughout the optimization run
current_baseline_dd = 0.2197          # 6.85% [cite: 34]
current_baseline_ces = 0.1         # Initialized during run [cite: 67]
current_baseline_p90 = 143            # Initialized during run [cite: 128]
current_baseline_pct_underwater = 0.93  # Reject if worse than buy-and-hold (~93% underwater); ratchet down as we improve

# Your specific list of parameters
OPTIMIZATION_PLAN = {
    #"AVG_VOL_DAYS": (10),
    #"VOL_PCT_THRESHOLD": (0,10,20,30,40,50,60,70,80,90,100),
    #"DB_STOP_PCT": (1.01, 1.011, 1.012,  1.013, 1.014, 1.015, 1.016, 1.017, 1.018, 1.019, 1.020, 1.021, 1.022, 1.023, 1.024, 1.025, 1.026, 1.027, 1.028, 1.029, 1.030),
    #"DB_TARGET_PCT": (0.80, 0.81, 0.82, 0.83, 0.84, 0.85, 0.86, 0.87, 0.88, 0.89, 0.90, 0.91, 0.92),
    #"DB_RIP_DAYS_MIN": (3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15),
    #"DB_RIP_DAYS_MAX": (5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17),
    #"DB_RIP_TOUCH_TOL": (0.024, 0.025, 0.026, 0.027, 0.028, 0.029, 0.030, 0.031, 0.032, 0.033, 0.034, 0.035, 0.036),
    #"DB_MAX_HOLD_DAYS": (10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42),
    #"DB_SQUEEZE_EXIT": (0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100),
    #"DB_EXPANSION": (0.90, 0.91, 0.92, 0.93, 0.94, 0.95, 0.96, 0.97, 0.98, 0.99, 1.00, 1.01, 1.02),
    #"DB_ACC_MIN": (8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20),
    #"DB_ACC_COUNT": (10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22),
    #"DB_PEAK_TROUGH_MAX": (-0.50, -0.49, -0.48, -0.47, -0.46, -0.45, -0.44, -0.43, -0.42, -0.41, -0.40, -0.39, -0.38),
    #
    #"DB_MAX_HOLD_DAYS": (10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42),
    #"RL_FLUSH_DAYS": (0, 3, 4, 5, 6, 7, 9, 10, 16, 18, 24),
    "RL_EXIT_PERCENT": (0.22, 0.23, 0.24, 0.25, 0.26, 0.27, 0.28, 0.29), # 0.0 effectively turns it off
    #"RL_EXIT_DAYS":    (13, 14, 15, 16, 17, 18, 19, 20, 21, 25, 30, 35, 40, 45, 50, 55, 60),

    #"RL_TRAIL_STOP":  (0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07),

    #"RL_DIP_PCT":     (1.018, 1.019, 1.02, 1.021, 1.022, 1.023, 1.024, 1.025, 1.026, 1.027, 1.028, 1.029, 1.03),  
    #"RL_EXPANSION":   (1.1, 1.11, 1.12, 1.13, 1.14, 1.15, 1.16, 1.17, 1.18, 1.19, 1.2, 1.21, 1.22),
    #"RL_SLOPE_PERIOD": (20, 21, 22, 23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40),
    #"RL_SLOPE_THRESHOLD": (.16, 0.17, 0.18, 0.19, 0.2, 0.21, 0.22, 0.23, 0.24, 0.25, 0.26, 0.27, 0.28, 0.29, 0.30),
    #"RL_SHOCK_THRESHOLD": (0, 0.1, 0.11, 0.09, 0.12, 0.13, 0.14, 0.15, 0.08, 0.07, 0.06),
    #"RL_SHOCK_REHAB_DAYS": (100, 110, 120, 130, 140),
    #"RL_SHOCK_MAX_ALLOWED": (0,1,2),


    # 2. THE CHASSIS (Basic Risk/Reward)
    #"RL_STOP_PCT":    (0.925, 0.924, 0.923, 0.922, 0.921),
    #"RL_TARGET_PCT":  (1.3, 1.31, 1.32, 1.33, 1.34, 1.35, 1.36, 1.37, 1.38, 1.39),
    #"RL_TOO_HIGH":    (1.134, 1.135, 1.136, 1.137, 1.138, 1.139, 1.140, 1.141, 1.142, 1.143, 1.144, 1.145, 1.146),

    # 3. THE TUNING (Trailing Stops)
    #"RL_TRAIL_PROFIT": (0.138, 0.139, 0.14, 0.141, 0.142, 0.143, 0.144, 0.145, 0.146, 0.147, 0.148, 0.149, 0.15),
    #"RL_TRAIL_STOP":  (-0.03, -0.02, -0.01, 0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07),
    #"RL_TRAIL_PROFIT2": (.4, .39, .38, .37, .36, .35, .41, .42, .43, .44, .45),
    #"RL_TRAIL_STOP2": (0.2, 0.19, 0.18, 0.17, 0.16, 0.15, 0.21, 0.22, 0.23, 0.24, 0.25),

    # 4. THE FILTERS (Volatility Constraints)
    #"RL_ATR_HIGH":    (0.101, 0.10, 0.099, 0.098, 0.097, 0.096, 0.095, 0.094, 0.093, 0.092, 0.091),
    #"RL_ATR_LOW":     (0.026, 0.025, 0.024, 0.023, 0.022, 0.021, 0.020, 0.019, 0.018, 0.017),

    # 5. NEW: EXIT VELOCITY & PARTIAL LOGIC
    #"RL_EXIT_PERCENT": (0.0, 0.20, 0.30, 0.40, 0.50), # 0.0 effectively turns it off
    #"RL_EXIT_DAYS":    (0, 1, 3, 5),
    #"PARTIAL_EXIT_TARGET": (0.0, 0.10, 0.15), 
    #"PARTIAL_EXIT_PERCENT": (0.50,),
    #"PARTIAL_EXIT_FOLLOW_TARGET": (0.0, 0.05),
}

current_best_params = {
    "RL_CASH": 47500, "RL_DIP_PCT": 1.024, "RL_STOP_PCT": 0.934, "RL_TARGET_PCT": 1.29,
    "RL_SLOPE_THRESHOLD": 0, "RL_SLOPE_PERIOD": 30, "RL_EXPANSION": 1.163,
    "RL_TOO_HIGH": 1.14, "RL_TRAIL_PROFIT": 0.14, "RL_TRAIL_STOP": 0.0,
    "RL_TRAIL_PROFIT2": 0.40, "RL_TRAIL_STOP2": 0.20, "RL_ATR_HIGH": 0.105, "RL_ATR_LOW": 0.019,
    "RL_EXIT_PERCENT": 0.21, "RL_EXIT_DAYS": 17, "PARTIAL_EXIT_TARGET": 0.0, "PARTIAL_EXIT_PERCENT": 0.5, "PARTIAL_EXIT_FOLLOW_TARGET": 0.1,
    "RL_FLUSH_DAYS": 42, "SPY_INCLUSION": 0,
    "DB_STOP_PCT": 1.09,  # Dive Bomber default; required when optimizing DB_* params
}

def sanitize_value(v):
    """Convert NumPy types (int64, float64) to native Python types."""
    return v.item() if hasattr(v, 'item') else v

def clean_memory():
    """Trim working set of all processes via Windows API (does not kill anything)."""
    ps_cmd = (
        "$code = '[DllImport(\"psapi.dll\")] public static extern int EmptyWorkingSet(IntPtr hwProc);'; "
        "$type = Add-Type -MemberDefinition $code -Name \"MemoryCleaner\" -PassThru; "
        "Get-Process | ForEach-Object { try { if ($_.Handle) { $type::EmptyWorkingSet($_.Handle) | Out-Null } } catch {} }"
    )
    subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True)

# --- SCORING LOGIC ---
def calculate_score(row, b_max_ces, b_max_ror, b_max_pf, b_min_dd, b_min_p90, use_db_scoring=False):
    """Score a run. When use_db_scoring=True (for DB_* param optimization), skip RL baselines and handle negative metrics."""
    try:
        total_trades = row['Wins'] + row['Losses'] + row['BE']
        pct_underwater = float(row.get('Pct_Time_Underwater', 0))

        if use_db_scoring:
            # DB metrics are often negative. Skip RL rejection baselines; only require min trades.
            if total_trades < 20:
                return 0
            # For DB: higher (less negative) CES/ROR/PF is better. Use max-of-batch for normalization.
            denom_ces = b_max_ces if b_max_ces != 0 else 1
            denom_ror = b_max_ror if b_max_ror != 0 else 1
            denom_pf = b_max_pf if b_max_pf > 0 else 1
            s_ces = (row['Avg_CES'] / denom_ces) if denom_ces != 0 else 0
            s_ror = (row['Ann_ROR'] / denom_ror) if denom_ror != 0 else 0
            s_pf = (row['Profit_Factor'] / denom_pf) if denom_pf > 0 else 0
            # Weights for DB: CES 40%, ROR 30%, PF 30%
            return (s_ces * 0.40) + (s_ror * 0.30) + (s_pf * 0.30)
        else:
            # --- REJECTION CLAUSES (RL) ---
            if row['Max_DD'] > current_baseline_dd: return 0
            if current_baseline_ces > 0 and row['Avg_CES'] < current_baseline_ces: return 0
            if current_baseline_p90 < 999 and row['P90_Days'] > current_baseline_p90: return 0
            if pct_underwater > current_baseline_pct_underwater: return 0
            if total_trades < 20: return 0

            # Normalized Components
            s_ces = (row['Avg_CES'] / b_max_ces) if b_max_ces > 0 else 0
            s_ror = (row['Ann_ROR'] / b_max_ror) if b_max_ror > 0 else 0
            s_pf  = (row['Profit_Factor'] / b_max_pf) if b_max_pf > 0 else 0
            s_dd  = (b_min_dd / row['Max_DD']) if row['Max_DD'] > 0 else 0
            s_p90 = (b_min_p90 / row['P90_Days']) if row['P90_Days'] > 0 else 0
            s_underwater = 1.0 - pct_underwater  # more time at new highs = higher

            # Weights: CES 25%, ROR 15%, PF 20%, DD 20%, P90 10%, time-at-new-highs 10%
            score = (s_ces * 0.25) + (s_ror * 0.15)
            score += (s_pf * 0.20) + (s_dd * 0.20)
            score += (s_p90 * 0.10) + (s_underwater * 0.10)
            return score
    except Exception as e:
        print(f"[WARN] calculate_score failed: {e}")
        return 0

def prevent_sleep():
    # ES_CONTINUOUS (0x80000000) | ES_SYSTEM_REQUIRED (0x00000001)
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)

def allow_sleep():
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)

# --- PROGRESS MANAGEMENT ---
def load_progress(initial_params):
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r') as f:
            data = json.load(f)
            return data["completed_params"], data["best_params"]
    return [], initial_params

def save_progress(completed_params, best_params):
    # Convert any NumPy types (int64, float64) to standard Python types
    serializable_best = {}
    for k, v in best_params.items():
        # This converts numpy types to python native types
        if hasattr(v, 'item'): 
            serializable_best[k] = v.item()
        else:
            serializable_best[k] = v

    with open(PROGRESS_FILE, "w") as f:
        json.dump({
            "completed_params": completed_params, 
            "best_params": serializable_best
        }, f, indent=4)
def _load_db_metrics_for_run(run_ts):
    """When optimizing DB_* params, load Dive Bomber metrics from DiveBomber.csv (keyed by run_ts).
    Returns a dict mapping RESULT_COLUMNS names to values for scoring, or None if not found."""
    if not os.path.exists(DIVEBOMBER_CSV):
        return None
    try:
        df = pd.read_csv(DIVEBOMBER_CSV)
        if df.empty or 'TIMESTAMP' not in df.columns:
            return None
        row = df[df['TIMESTAMP'].astype(str) == str(run_ts)]
        if row.empty:
            return None
        r = row.iloc[0]
        # Map DiveBomber columns to RESULT_COLUMNS used by calculate_score
        # DB uses AVG_CES, SYNTHETIC_ROR, PROFIT_FACTOR; no Max_DD/P90/Pct_Time_Underwater - use permissive defaults
        total = int(r.get('WINS', 0)) + int(r.get('LOSSES', 0)) + int(r.get('BEs', 0))
        return {
            'PNL': float(r.get('TOTAL_PNL', 0)),
            'Wins': int(r.get('WINS', 0)),
            'Losses': int(r.get('LOSSES', 0)),
            'BE': int(r.get('BEs', 0)),
            'Profit_Factor': max(0.01, float(r.get('PROFIT_FACTOR', 0))),
            'Avg_CES': float(r.get('AVG_CES', 0)),
            'MedCES': float(r.get('MEDIAN_CES', 0)),
            'Ann_ROR': float(r.get('SYNTHETIC_ROR', 0)),
            'Max_DD': 0.5,  # DB has no DD in DiveBomber; use permissive so scoring proceeds
            'P90_Days': 0,
            'Pct_Time_Underwater': 0,
            'TotalHoldDays': float(r.get('AVG_DAYS_HELD', 0)) * total if total > 0 else 0,
        }
    except Exception as e:
        print(f"  [WARN] Could not load DB metrics: {e}")
        return None

# --- EXECUTION ---
def parallel_awk_worker(task):
    """Worker function to run AWK on a specific CPU core with live progress reporting."""
    params, core_idx, val, param_name, task_id = task
    core_mask = 1 << core_idx
    # Unique temp file per task so parallel runs never overwrite each other's results
    temp_file = os.path.join(SCRIPT_DIR, f"temp_run_task_{task_id}.csv")
    out_file_awk = temp_file.replace("\\", "/")  # GAWK accepts forward slashes on Windows; avoids shell escaping

    # --- LIVE TRACKING ---
    print(f"  [Core {core_idx}] Starting: {val}")

    if os.path.exists(temp_file):
        try:
            os.remove(temp_file)
        except OSError:
            pass
    # Unique run timestamp so RL_Closed_*, RL_Open_*, etc. don't collide when workers finish in the same second
    run_ts = time.strftime("%y%m%d%H%M%S", time.localtime()) + "_" + str(task_id).zfill(3)
    params_with_ts = {**params, "RUN_TS": run_ts}
    v_args = " ".join([f'-v {k}="{v}"' for k, v in params_with_ts.items()])
    v_args += f' -v OUT_FILE="{out_file_awk}"'
    data_args = " ".join(f'"{p}"' for p in DATA_PATHS)
    full_cmd = f'start /affinity {core_mask} /wait /b awk -f "{AWK_SCRIPT}" {v_args} {data_args}'

    try:
        subprocess.run(full_cmd, check=True, shell=True, cwd=SCRIPT_DIR)
        clean_memory()

        if os.path.exists(temp_file) and os.path.getsize(temp_file) > 0:
            df = pd.read_csv(temp_file, header=None)
            if len(df.columns) != EXPECTED_COLS:
                print(f"  [Core {core_idx}] [WARN] Column count {len(df.columns)} != {EXPECTED_COLS}, skip: {val}")
            else:
                df.columns = RESULT_COLUMNS
                result_row = df.iloc[0].to_dict()
                result_row["Param_Value"] = val
                # When optimizing DB_* params, the temp file has RL metrics (unchanged by DB). Override with Dive Bomber metrics.
                if param_name.startswith("DB_"):
                    db_metrics = _load_db_metrics_for_run(run_ts)
                    if db_metrics:
                        result_row.update(db_metrics)
                    else:
                        print(f"  [Core {core_idx}] [WARN] DB run {run_ts}: no DiveBomber row found; using RL metrics (will not reflect DB changes)")
                # Append this run to the all-runs file (thread-safe) so you keep every run, not just last per core
                all_runs_path = os.path.join(SCRIPT_DIR, ALL_RUNS_FILE)
                with _all_runs_lock:
                    write_header = not os.path.exists(all_runs_path) or os.path.getsize(all_runs_path) == 0
                    one = pd.DataFrame([result_row])
                    one.insert(0, "Iterated_Param", param_name)
                    one.to_csv(all_runs_path, mode="a", index=False, header=write_header)
                print(f"  [Core {core_idx}] [OK] Finished: {val}")
                return (val, result_row)
        else:
            print(f"  [Core {core_idx}] [WARN] No output file or empty: {temp_file}")
    except Exception as e:
        print(f"  [Core {core_idx}] [ERR] Failed: {val} Error: {e}")

    return (val, None)

def find_best_in_batch():
    if not os.path.exists(TEMP_RESULT):
        return None
    df = pd.read_csv(TEMP_RESULT, header=None)
    if len(df.columns) != EXPECTED_COLS:
        print(f"[WARN] temp_run.csv has {len(df.columns)} columns, expected {EXPECTED_COLS}; skipping.")
        return None
    df.columns = RESULT_COLUMNS
    df['Score'] = df.apply(calculate_score, axis=1)
    return df.sort_values('Score', ascending=False).iloc[0]

def main():
    global current_baseline_dd, current_baseline_pct_underwater
    
    # --- RECORD START TIME ---
    session_start = time.time()
    print(f"\n[OK] OPTIMIZATION SESSION START: {time.ctime(session_start)}")
    print("="*60)
    try:
        prevent_sleep()
    except Exception:
        pass

    # PASS THE DEFAULT SETTINGS HERE
    completed_params, best_params = load_progress(current_best_params)
    best_params = {k: sanitize_value(v) for k, v in best_params.items()}

    # --- CRITICAL FIX: Ensure best_params is populated with defaults ---
    # This prevents KeyError when run_awk is called for the first time
    for p_name, p_values in OPTIMIZATION_PLAN.items():
        if p_name not in best_params:
            best_params[p_name] = p_values[0]

    print(f"[OK] Starting Resilient Optimization. {len(completed_params)} steps already finished.")

    for param_name, values in OPTIMIZATION_PLAN.items():
        if param_name in completed_params: continue

        print(f"\n--- Optimizing {param_name} (Parallel across {MAX_WORKERS} workers) ---")
        batch_results = []
        
        # Prepare the list of tasks for the current parameter
        # Each task gets a unique task_id so its temp file is never shared (avoids overwrites/race conditions)
        tasks = []
        for i, val in enumerate(values):
            test_params = best_params.copy()
            test_params[param_name] = val
            tasks.append((test_params, i % MAX_WORKERS, val, param_name, i))

        # Launch parallel execution (MAX_WORKERS limits concurrent AWK processes to avoid memory exhaustion)
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            results = list(executor.map(parallel_awk_worker, tasks))

        # Clean up per-task temp files for this parameter
        for i in range(len(values)):
            tf = os.path.join(SCRIPT_DIR, f"temp_run_task_{i}.csv")
            if os.path.exists(tf):
                try:
                    os.remove(tf)
                except OSError:
                    pass

        # Process results
        for val, result_row in results:
            if result_row:
                result_row['Param_Value'] = val
                batch_results.append(result_row)

        if batch_results:
            full_batch = pd.DataFrame(batch_results)
            
            # Normalization for scoring
            b_max_ces = full_batch['Avg_CES'].max()
            b_max_ror = full_batch['Ann_ROR'].max()
            b_max_pf  = full_batch['Profit_Factor'].max()
            b_min_dd  = full_batch['Max_DD'].min()
            b_min_p90 = full_batch['P90_Days'].min()

            full_batch['Score'] = full_batch.apply(
                lambda r: calculate_score(r, b_max_ces, b_max_ror, b_max_pf, b_min_dd, b_min_p90), axis=1
            )
            
            # Sort and find winner
            full_batch = full_batch.sort_values('Score', ascending=False)
            winner_row = full_batch.iloc[0]
            
            # Update best_params with the winner
            best_params[param_name] = sanitize_value(winner_row['Param_Value'])
            
            # Dynamic Ratchet
            if winner_row['Max_DD'] < current_baseline_dd:
                print(f"\n[OK] RISK REDUCED: New DD Baseline {winner_row['Max_DD']:.4f}")
                current_baseline_dd = winner_row['Max_DD']
            pct_uw = float(winner_row.get('Pct_Time_Underwater', 1))
            if pct_uw < current_baseline_pct_underwater:
                print(f"\n[OK] DOWNTIME REDUCED: New Pct-Time-Underwater baseline {pct_uw:.2%}")
                current_baseline_pct_underwater = pct_uw
            
            completed_params.append(param_name)
            save_progress(completed_params, best_params)
            
                        
            # Logs
            winner_row.to_frame().T.to_csv(MASTER_LOG, mode='a', index=False, header=not os.path.exists(MASTER_LOG))
            full_batch.insert(0, 'Iterated_Param', param_name)
            full_batch.to_csv(GLOBAL_AUDIT_LOG, mode='a', index=False, header=not os.path.exists(GLOBAL_AUDIT_LOG))

            print(f"[OK] Winner for {param_name}: {best_params[param_name]} (Score: {winner_row['Score']:.4f})")

    # Final Output
    final_settings = {k: sanitize_value(v) for k, v in best_params.items()}
    with open(BEST_SETTINGS_FILE, "w") as f:
        json.dump(final_settings, f, indent=4)

    # --- RECORD END TIME ---
    session_end = time.time()
    duration = session_end - session_start
    print("\n" + "="*60)
    print(f"[OK] OPTIMIZATION SESSION END: {time.ctime(session_end)}")
    print(f"[OK] TOTAL DURATION: {time.strftime('%H:%M:%S', time.gmtime(duration))}")
    print("="*60)
    print(f"[OK] Settings saved to {BEST_SETTINGS_FILE}")
    try:
        allow_sleep()
    except Exception:
        pass

if __name__ == "__main__":
    main()