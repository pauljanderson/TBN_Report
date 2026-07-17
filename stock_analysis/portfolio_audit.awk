#!/usr/bin/awk -f

# ==========================================================================================
# 100% COMPREHENSIVE VARIABLE REGISTRY & TECHNICAL DOCUMENTATION
# ------------------------------------------------------------------------------------------
# MODE: Backtest from ticker CSVs + SPY only. History file is not used.
#
# COMMAND LINE ARGUMENTS (Passed via -v)
# DEBUG_SYM:          Optional. If provided (e.g., "HMY"), triggers verbose tracing.
# WATCH_MIN_SCORE:     Minimum setup score (0-110) for RL_Watchlist near/pending rows. Default 55. Try 45-50 for more names.
# WATCH_DISABLE:       If 1, RL_Watchlist gets header only (no approaching/pending rows).
# RS_DAYS:             The number of trading days used to calculate Relative Strength.
# ADD_PCT:             The multiplier used for LVP programmatic additions (e.g., 0.33).
# RL_CASH:             Rocket Launcher investment amount (e.g., 50000).
# RL_DIP_PCT:          Dip threshold multiplier (e.g., 1.02 for 2%).
# RL_STOP_PCT:       Stop loss multiplier (e.g., 0.95 for 5%).
# RL_TARGET_PCT:     Profit target multiplier (e.g., 1.20 for 20%).
# SMA_QUAL:            Toggle for SMA Qualifier (1=On, 0=Off).
# INSTRUMENT:          If set (e.g. 1), enables throughput instrumentation (instrument.txt, per-symbol timing). Default: 0.
# RL_INPUT_MANIFEST:   Optional path to a text file (one input CSV path per line, UTF-8). When set by run_audit.ps1,
#                      gawk appends those paths to ARGV so Windows is not limited by ~8191-char command lines.
#                      Lines starting with # and blank lines are skipped. SPY should be first line, as with argv order.
# RL_FLUSH_DAYS:       If > 0, sell ALL positions after portfolio has been underwater (below HWM) this many consecutive days; exit type FLUSH_EXIT. Default: 0 (off).
# AVG_VOL_DAYS:        Days for rolling avg volume (0=disabled). If 10, avg vol printed in RL_Closed as of entry. Default: 0.
# VOL_PCT_THRESHOLD:   Pct above avg vol required to buy (0=no filter). E.g. 25 = only buy if entry-day vol >= avg_vol*1.25. Default: 0.
#
# OUTPUT — LIVE / LAST BAR:
# RL_Scanner_<ts>.csv — Last calendar bar only: 50-SMA dip setup fired today; model entry is next session open (ENTRY_DATE).
#   ENTRY_ALLOWED=1 means the same gates as the backtest would open on ENTRY_DATE (next-day open not "too high", etc.).
# RL_Watchlist_<ts>.csv / .txt — Last bar only, flat names (not in RL_Open): "approaching" a 50-trigger (NEAR_50_ZONE) or
#   full dip candle but blocked by a filter (PENDING_FILTERS). Tune with -v WATCH_MIN_SCORE=55 (higher = fewer names).
#   -v WATCH_DISABLE=1 turns this off (writes header-only CSV). Excludes symbols already on RL_Scanner and RL_Open.
#
# ROCKET BRT PIVOT DETECTION (Rocket BRT - Pivot Detection Specification v1.0):
# BRT_PIVOT_K:         Local window +/- bars for pivot extreme (default 4).
# BRT_PIVOT_M:         Confirmation lookforward bars (default 7).
# BRT_PIVOT_D:         Minimum displacement 0-1 (default 0.06 = 6%).
#
# DIVE BOMBER (Short-selling, inverse of Rocket Launcher):
# DB_TOGGLE:           1 = enable Dive Bomber. Default: 1.
# DB_CASH:             Position size per short (default: RL_CASH).
# DB_STOP_PCT:         Stop above entry (e.g. 1.05 = 5% against). Default: 1.05.
# DB_TARGET_PCT:       Target below entry (e.g. 0.90 = 10% profit). Default: 0.90.
# DB_RIP_DAYS_MIN/MAX: Rally window for "rip" (3-5 days). Defaults: 3, 5.
# DB_RIP_TOUCH_TOL:    Touch 50 SMA within this fraction (0.02 = 2%). Default: 0.02.
# DB_MAX_HOLD_DAYS:    Time-based exit (squeeze protection). Default: 10.
# DB_SQUEEZE_EXIT:     Days for high (0=off, 10=10-day high, 20=20-day high). Default: 20.
# DB_INVERSE_STRICT:   1 = require 50<100<200; 0 = 50<100 only. Default: 1.
# DB_SLOPE_LOOKBACK:   Days for "falling 50 SMA" check. Default: 4.
# DB_GAP_UP_MAX:       Don't short if next open > sma50*this (e.g. 1.05). Default: 1.05.
# DB_EXPANSION:        Inverse of RL: at least one day in lookback with close <= sma50(prev)*this (prior weakness). Default: 0.90.
# DB_ACC_MIN/COUNT:    Inverse acceptance: rolling days with close < prior 50 must be >= DB_ACC_MIN over DB_ACC_COUNT. Defaults: 8, 10.
# DB_PEAK_TROUGH_MAX:  Inverse peak: don't short if close has already been this far below 50 (e.g. -0.50 = -50%). Entry only if db_peak_trough > this. Default: -0.50.
#
# 100-SMA SYSTEM (same logic as 50-day, separate RL100_* variables and RL100_Closed output):
# RL100_TOGGLE:       1 = enable 100-day SMA system. Default: 0.
# RL100_DIP_PCT, RL100_EXPANSION, RL100_ACC_MIN, RL100_ACC_COUNT: same as RL_* but for SMA100.
# RL100_TOO_HIGH, RL100_TRAIL_PROFIT, RL100_TRAIL_STOP, RL100_TRAIL_PROFIT2, RL100_TRAIL_STOP2: exits.
# RL100_TARGET_PCT, RL100_STOP_PCT, RL100_EXIT_PERCENT, RL100_EXIT_DAYS, RL100_FLUSH_DAYS: same as 50-day.
# RL100_SLOPE_PERIOD, RL100_SLOPE_THRESHOLD, RL100_100_SMA_LOOKBACK: SMA100 slope/lookback.
# RL100_CUT_THE_LOSERS, RL100_CASH, RL100_ATR_* , RL100_LOW_PRICE, RL100_SPY_INCLUSION: filters.
#
# LOCAL CALCULATION VARIABLES
# iso:                     The ISO date string (YYYYMMDD) currently being processed in the loop.
# cq:                       Current Quantity: Literal shares sold on 'iso' according to History.
# crs:                     Current RS State: 1 if (Ticker N-day Return > SPY N-day Return), else 0.
# imp:                     Impact: The dollar Alpha generated by a specific Veto decision.
# ticker_ret:          The trailing N-day percentage return calculated for the symbol.
# spy_ret:              The trailing N-day percentage return calculated for the SPY benchmark.
# exit_p:                 The programmatic execution price (Opening Price of the day AFTER a signal).
# next_iso:             The ISO date of the trading day following the current signal.
# anchor:                 The price reference used for the cycle's final Tactical Buy/Sell math.
# val:                     Temporary variable used to store the result of a single TAC calculation.
# pure_bh:               PNL of ONLY the initial day's shares held until the final weighted exit.
# all_buys_bh:         PNL of ALL shares bought in a cycle held until the final weighted exit.
# rs_buy_val[]:       PNL for the strategy that only buys additions if yesterday was an RS day.
# rs_sell_val[]:      PNL for the strategy (Initial entry only) that only sells interim if yesterday was NOT RS.
#
# LEGACY (History file no longer used): t_list_ptr[], t_list[], tid, st_iso[], en_iso[], t_to_s[],
# term_anchor[] and related vars are only used in no-op loops when History is not supplied; kept for possible future use.
#
# PHASE 2: BENCHMARKING (SPY)
# spy_p[iso]:          Closing price of SPY for a specific date (ISO).
# spy_s[index]:        Chronological sequence of dates for SPY (for lookbacks).
# spy_idx[iso]:      Mapping of date to its chronological position index in the SPY file.
# spy_rec_cnt:          Total records processed from the SPY file.
#
# PHASE 3: PRICE SCOUTING (Symbol CSVs)
# dates[sym,ptr]: Chronological array of all dates found in a Symbol CSV.
# d_ptr[sym]:          Pointer for the chronological date array for a symbol.
# raw_op[sym,iso]:Opening price for a specific symbol and date.
# raw_cl[sym,iso]:Closing price for a specific symbol and date.
# raw_hi[sym,iso]:High price for a specific symbol and date.
# term_anchor[]:    Programmatic price found on en_iso. Found via scouting or Veto exit.
# scout_rec_cnt:    Running count of raw price rows processed across all tickers.
# prev_file:            Internal variable used to detect when awk moves to a new CSV.
# cur_s:                  The ticker symbol currently being audited.
# seen[]:                Dedup map for dates within a file.
# iso_idx[]:            Mapping of date to its pointer index within a ticker file.
#
# PHASE 4: ACCOUNTING (The Audit Loop)
# streak:                1 = Active Veto (Audit is "holding" shares due to RS).
# last_tid:              Caches the Trade ID to allow streaks to outlive history windows.
# s_q[iso]:              Shares captured on a specific date during a veto streak.
# s_p[iso]:              Manual sell price from History for the captured shares.
# s_fv[iso]:              Flag indicating if a captured sell was a "Full Exit" (Inv=0).
# fv_ledger[]:          Dollar impact of Full Veto decisions per tid.
# pv_ledger[]:          Dollar impact of Partial Veto decisions per tid.
# lvp_ledger[]:        Dollar impact of Low Value Purchase decisions per tid.
# diag[]:                Forensic math accumulator for the final log. [Key: Sym] -> [Value: Log].
# trace[]:              Row-by-row logic heartbeat for DEBUG_SYM.
# acc_rec_cnt:          Total count of ticker files successfully processed by the Accountant.
# hist_rs[]:            Map of RS state for every ticker and trading date.
#
# SUMMARY ACCUMULATORS & ITERATORS
# tm, tvb, tvs:      Final System Totals for PnL, Tactical Buy, Tactical Sell.
# tpbh, tabh:          Final System Totals for Pure B&H and All Buys B&H.
# trsb, trss:          Final System Total for RS-Filtered Buy and RS-Filtered Sell metrics.
# tlv, tpv, tfv:      Final System Totals for LVP, Partial Veto, Full Veto.
# i, j, k, n:          Iterators and array size variables.
# sorted_list[]:      Alphabetized list of symbols for the final table.
# ==========================================================================================

# Portable Timer: no subprocess (was: echo %TIME% per call = 1000s+ of spawns over 1k tickers).
# Uses systime() for 1-second resolution; avoids 2000+ shell spawns and saves tens of seconds.
function get_ms() {
    return systime() * 1000
}

# Last-bar watchlist: keep best-scoring row per symbol (see RL_Watchlist_* output in END).
function record_watch_near(sym, iso, sc, tier, miss, cl, ys,   minsc, m2, prev) {
    if (WATCH_DISABLE != "" && (WATCH_DISABLE + 0) == 1) return
    minsc = (WATCH_MIN_SCORE == "") ? 55 : (WATCH_MIN_SCORE + 0)
    if (sc < minsc) return
    m2 = miss
    gsub(/,/, ";", m2)
    prev = -1
    if (sym in watch_best_sc) prev = watch_best_sc[sym]
    if (sc > prev) {
        watch_best_sc[sym] = sc
        watch_best_ln[sym] = sprintf("%s,%s,%d,%s,%s,%.2f,%.2f", sym, iso, sc, tier, m2, cl, ys)
    }
}

BEGIN {  

    # Large input sets (run_audit.ps1): avoid Windows CreateProcess command-line limit (~8191 chars).
    # When RL_INPUT_MANIFEST is set (-v RL_INPUT_MANIFEST=C:/path/list.txt), read one CSV path per line into ARGV.
    if (RL_INPUT_MANIFEST != "") {
        mf = RL_INPUT_MANIFEST
        n = ARGC
        while ((getline line < mf) > 0) {
            gsub(/\r$/, "", line)
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", line)
            if (line == "" || substr(line, 1, 1) == "#") continue
            ARGV[n++] = line
        }
        close(mf)
        ARGC = n
    }

    # ==========================================================================================
    # CONSTANTS - Magic Numbers Extracted for Maintainability
    # ------------------------------------------------------------------------------------------
    # Technical Indicator Periods
    SMA_PERIOD_20 = 20
    SMA_PERIOD_30 = 30
    SMA_PERIOD_50 = 50
    SMA_PERIOD_100 = 100
    SMA_PERIOD_200 = 200
    
    # Expansion Lookback
    EXPANSION_LOOKBACK_DAYS = 10
    
    # ATR Calculation
    ATR_PERIOD = 14
    ATR_EMA_MULTIPLIER = 13  # (ATR_PERIOD - 1)
    
    # Milestone Percentages
    MILESTONE_10_PCT = 0.10
    MILESTONE_20_PCT = 0.20
    MILESTONE_30_PCT = 0.30
    MILESTONE_40_PCT = 0.40
    MILESTONE_50_PCT = 0.50
    MILESTONE_60_PCT = 0.60
    
    # Time Constants
    DAYS_PER_YEAR = 365
    SECONDS_PER_DAY = 86400
    
    # Peak Threshold
    PEAK_THRESHOLD_MAX = 2.0  # 200% maximum historical peak
    
    # Percentile Calculations
    PERCENTILE_90 = 0.90
    
    # Account Size Multiplier
    ACCOUNT_SIZE_MULTIPLIER = 10
    
    # Rocket BRT Pivot Detection (Rocket BRT - Pivot Detection Specification v1.0)
    # k=local window ±bars, m=confirmation lookforward, d=min displacement (6%)
    if (BRT_PIVOT_K == "") BRT_PIVOT_K = 4
    if (BRT_PIVOT_M == "") BRT_PIVOT_M = 7
    if (BRT_PIVOT_D == "") BRT_PIVOT_D = 0.06
    
    # ==========================================================================================

    # Start timestamp: run_audit.ps1 prints start/end to console; skip heavy CON/system here for speed.
    T_START = get_ms()
    if (INSTRUMENT == "") INSTRUMENT = 0
    if (INSTRUMENT) {
        INST_FILE = "instrument.txt"
        T_SPY_END = 0  # Set when leaving SPY file
        T_SHOCK_MS = T_EXPANSION_MS = T_MAIN50_MS = T_DB_MS = T_TOP_MS = T_ATR_MS = T_SMA_MS = T_DIPZONE_MS = T_100DAY_MS = T_DRAWDOWN_MS = 0  # Detailed profiling accumulators
        T_SMA_LOOKUP_MS = T_SMA_NDAY_MS = T_SMA_SLOPE_ACC_MS = 0  # SMA rolling sub-sections
        PRECOMP_SMA_HITS = PRECOMP_SMA_MISS = 0  # Diagnostic: precomputed vs computed
        print "--- THROUGHPUT INSTRUMENTATION START ---" > INST_FILE
    }
    if (SKIP_TRIM == "") SKIP_TRIM = 0  # -v SKIP_TRIM=1 to skip trim_working_set (saves ~13s)
    # Use RUN_TS from optimizer if provided (ensures unique timestamps per parallel run); else generate here
    if (RUN_TS != "") ts = RUN_TS; else ts = strftime("%y%m%d%H%M%S", systime())
    
    # Configuration: File paths (can be overridden via command line)
    if (OUTPUT_DIR == "") OUTPUT_DIR = "C:\\Users\\songg\\Downloads\\stockresearch\\drive"
    if (PYTHON_SCRIPT_DIR == "") PYTHON_SCRIPT_DIR = "C:\\Users\\songg\\Downloads\\stockresearch\\stock_analysis"
    if (DATA_DIR == "") DATA_DIR = "C:\\Users\\songg\\Downloads\\stockresearch\\data\\newdata\\data"
    
    closed_file = OUTPUT_DIR "\\RL_Closed_" ts ".csv"
    RL100_closed_file = OUTPUT_DIR "\\RL100_Closed_" ts ".csv"
    open_file = OUTPUT_DIR "\\RL_Open_" ts ".csv"
    db_closed_file = OUTPUT_DIR "\\DB_Closed_" ts ".csv"
    db_open_file = OUTPUT_DIR "\\DB_Open_" ts ".csv"
    db_summary_file = OUTPUT_DIR "\\DB_Summary_" ts ".csv"
    scanner_file = OUTPUT_DIR "\\RL_Scanner_" ts ".csv"
    watchlist_file = OUTPUT_DIR "\\RL_Watchlist_" ts ".csv"
    watchlist_txt = OUTPUT_DIR "\\RL_Watchlist_" ts ".txt"
    summary_file = OUTPUT_DIR "\\RL_Summary_" ts ".csv"
    pivot_file = OUTPUT_DIR "\\RL_Pivots_" ts ".csv"
    TROUBLESHOOT_FILE = OUTPUT_DIR "\\troubleshoot_purchases.txt"
    DIAG_FILE = OUTPUT_DIR "\\diagnostic_audit.txt"
    printf "=== DIAGNOSTIC RUN ===\n" > DIAG_FILE
    first_audit_sym = ""
    pivot_file_header_done = 0
    diag_dip_zone_enters = 0
    diag_dip_inner_enters = 0
    diag_csv_sample_done = 0
    tr_expansion = tr_acceptance = tr_cut_it = tr_atr_inclusion = tr_spy_inclusion = 0
    tr_peak_inclusion = tr_slope_ok = tr_shock_qualified = tr_too_low = 0
    tr_all_conditions = tr_actually_opened = 0
    # 100-SMA troubleshooting counters (which condition passed how often)
    tr100_block_enters = 0; tr100_sma100_rising = 0; tr100_inthe100zone = 0; tr100_uptick = 0; tr100_closeabove = 0
    tr100_is200 = 0; tr100_stack_ok = 0; tr100_exp100 = 0; tr100_acc100 = 0; tr100_cut_it = 0; tr100_atr = 0
    tr100_spy = 0; tr100_peak = 0; tr100_slope = 0; tr100_shock = 0; tr100_too_low = 0; tr100_vol = 0
    tr100_all_conditions = 0; tr100_actually_opened = 0
    RL100_troubleshoot_done = 0
      
    FS = ","; OFS = "\t"
    # Default values if not passed via command line
    if (RS_DAYS == "") RS_DAYS = 5
    if (ADD_PCT == "") ADD_PCT = 0.33
    if (RL_CASH == "") RL_CASH = 47500
    if (RL_DIP_PCT == "") RL_DIP_PCT = 1.024
    if (RL_STOP_PCT == "") RL_STOP_PCT = 0.934
    if (RL_TARGET_PCT == "") RL_TARGET_PCT = 1.20
    if (SMA_QUAL == "") SMA_QUAL = 1
    if (RL_EXPANSION == "") RL_EXPANSION = 1.163
    if (RL_ACC_MIN == "") RL_ACC_MIN = 8
    if (RL_ACC_COUNT == "") RL_ACC_COUNT = 10
    if (RUN_REPLAYS == "") RUN_REPLAYS = 0
    if (RL_TOO_HIGH == "") RL_TOO_HIGH = 1.14
    if (RL_TRAIL_PROFIT == "") RL_TRAIL_PROFIT = 0
    if (RL_TRAIL_STOP == "") RL_TRAIL_STOP = 0.0
    if (RL_50_SMA_LOOKBACK == "") RL_50_SMA_LOOKBACK = 4
    # --- 100-SMA system: same variables as 50-day but with RL100_ prefix (separate system) ---
    if (RL100_TOGGLE == "" && RL_100_TOGGLE != "") RL100_TOGGLE = RL_100_TOGGLE
    if (RL100_TOGGLE == "") RL100_TOGGLE = 0
    if (RL100_DIP_PCT == "" && RL_100_DIP_PCT != "") RL100_DIP_PCT = RL_100_DIP_PCT
    if (RL100_DIP_PCT == "") RL100_DIP_PCT = 1.024
    if (RL100_EXPANSION == "" && RL_100_EXPANSION != "") RL100_EXPANSION = RL_100_EXPANSION
    if (RL100_EXPANSION == "") RL100_EXPANSION = 1.163
    if (RL100_ACC_MIN == "" && RL_100_ACC_MIN != "") RL100_ACC_MIN = RL_100_ACC_MIN
    if (RL100_ACC_MIN == "") RL100_ACC_MIN = 8
    if (RL100_ACC_COUNT == "" && RL_100_ACC_COUNT != "") RL100_ACC_COUNT = RL_100_ACC_COUNT
    if (RL100_ACC_COUNT == "") RL100_ACC_COUNT = 10
    if (RL100_TOO_HIGH == "") RL100_TOO_HIGH = 1.14
    if (RL100_TRAIL_PROFIT == "" && RL_100_TRAIL_PROFIT != "") RL100_TRAIL_PROFIT = RL_100_TRAIL_PROFIT
    if (RL100_TRAIL_PROFIT == "") RL100_TRAIL_PROFIT = 0.14
    if (RL100_TRAIL_STOP == "" && RL_100_TRAIL_STOP != "") RL100_TRAIL_STOP = RL_100_TRAIL_STOP
    if (RL100_TRAIL_STOP == "") RL100_TRAIL_STOP = 0.0
    if (RL100_TRAIL_PROFIT2 == "") RL100_TRAIL_PROFIT2 = 0.40
    if (RL100_TRAIL_STOP2 == "") RL100_TRAIL_STOP2 = 0.20
    if (RL100_TARGET_PCT == "" && RL_100_TARGET_PCT != "") RL100_TARGET_PCT = RL_100_TARGET_PCT
    if (RL100_TARGET_PCT == "") RL100_TARGET_PCT = 1.29
    if (RL100_STOP_PCT == "" && RL_100_STOP_PCT != "") RL100_STOP_PCT = RL_100_STOP_PCT
    if (RL100_STOP_PCT == "") RL100_STOP_PCT = 0.934
    if (RL100_EXIT_PERCENT == "") RL100_EXIT_PERCENT = 0.22
    if (RL100_EXIT_DAYS == "") RL100_EXIT_DAYS = 17
    if (RL100_SLOPE_PERIOD == "") RL100_SLOPE_PERIOD = 30
    if (RL100_SLOPE_THRESHOLD == "") RL100_SLOPE_THRESHOLD = 0
    if (RL100_100_SMA_LOOKBACK == "") RL100_100_SMA_LOOKBACK = 4
    if (RL100_CUT_THE_LOSERS == "") RL100_CUT_THE_LOSERS = 0.2
    if (RL100_CASH == "") RL100_CASH = RL_CASH + 0
    if (RL100_FLUSH_DAYS == "") RL100_FLUSH_DAYS = 42
    if (RL100_SPY_INCLUSION == "") RL100_SPY_INCLUSION = 0
    if (RL100_PARTIAL_EXIT_TARGET == "") RL100_PARTIAL_EXIT_TARGET = 0
    if (RL100_PARTIAL_EXIT_PERCENT == "") RL100_PARTIAL_EXIT_PERCENT = 0.50
    if (RL100_PARTIAL_EXIT_FOLLOW_TARGET == "") RL100_PARTIAL_EXIT_FOLLOW_TARGET = 0.1
    # Backward compat: old RL_100_* names
    if (RL_100_TOGGLE == "" && RL100_TOGGLE != "") RL_100_TOGGLE = RL100_TOGGLE
    if (RL_100_DIP_PCT == "")     RL_100_DIP_PCT = RL100_DIP_PCT + 0
    if (RL_100_EXPANSION == "")   RL_100_EXPANSION = RL100_EXPANSION + 0
    if (RL_100_ACC_MIN == "")     RL_100_ACC_MIN = RL100_ACC_MIN + 0
    if (RL_100_ACC_COUNT == "")   RL_100_ACC_COUNT = RL100_ACC_COUNT + 0
    if (RL_100_TRAIL_PROFIT == "") RL_100_TRAIL_PROFIT = RL100_TRAIL_PROFIT + 0
    if (RL_100_TRAIL_STOP == "")   RL_100_TRAIL_STOP = RL100_TRAIL_STOP + 0
    if (RL_100_TARGET_PCT == "")   RL_100_TARGET_PCT = RL100_TARGET_PCT + 0
    if (RL_100_STOP_PCT == "")     RL_100_STOP_PCT = RL100_STOP_PCT + 0
    if (RL_CUT_THE_LOSERS == "") RL_CUT_THE_LOSERS = 0.25 #percent to cut the losers. this is the default. if you want to NOT cut the losers, set it to 1000
    if (RL_TRAIL_PROFIT2 == "") RL_TRAIL_PROFIT2 = 0  # 40% Gain
    if (RL_TRAIL_STOP2 == "") RL_TRAIL_STOP2 = 0      # 20% Stop
        
    # New Value and Price Filters
    if (RL_ATR_HIGH_VALUE == "") RL_ATR_HIGH_VALUE = 200 #17.25
    if (RL_LOW_PRICE == "") RL_LOW_PRICE = 0.000001 #1.00
      
    if (RL_ATR_HIGH_PERCENT == "") RL_ATR_HIGH_PERCENT = .0848 #0.105      # Filter out those stocks whose ATR is > 10.5% of their stock price as they are too volatile
    if (RL_ATR_LOW_PERCENT == "") RL_ATR_LOW_PERCENT = .0244 #0.019       # Filter out those stocks whose ATR is < 1.9% of their stock price as they do not have a big enough Range
    # Map optimizer variable names to script variable names (optimizer passes RL_ATR_HIGH / RL_ATR_LOW)
    if (RL_ATR_HIGH != "") RL_ATR_HIGH_PERCENT = RL_ATR_HIGH
    if (RL_ATR_LOW != "") RL_ATR_LOW_PERCENT = RL_ATR_LOW

    # 100-SMA ATR/price defaults must come AFTER RL_ATR_* and RL_LOW_PRICE are set (else RL100_* get 0 and ATR filter excludes every bar)
    if (RL100_ATR_HIGH_PERCENT == "") RL100_ATR_HIGH_PERCENT = RL_ATR_HIGH_PERCENT + 0
    if (RL100_ATR_LOW_PERCENT == "") RL100_ATR_LOW_PERCENT = RL_ATR_LOW_PERCENT + 0
    if (RL100_ATR_HIGH_VALUE == "") RL100_ATR_HIGH_VALUE = RL_ATR_HIGH_VALUE + 0
    if (RL100_LOW_PRICE == "") RL100_LOW_PRICE = RL_LOW_PRICE + 0
      
    if (RL_SLOPE_PERIOD == "") RL_SLOPE_PERIOD = 30
    if (RL_SLOPE_THRESHOLD == "") RL_SLOPE_THRESHOLD = 0.0643
    if (RL_SHOCK_THRESHOLD == "") RL_SHOCK_THRESHOLD = 0
    if (RL_SHOCK_REHAB_DAYS == "") RL_SHOCK_REHAB_DAYS = 120
    if (RL_SHOCK_MAX_ALLOWED == "") RL_SHOCK_MAX_ALLOWED = 1
    if (RL_EXIT_DAYS == "") RL_EXIT_DAYS = 10000
    if (RL_EXIT_PERCENT == "") RL_EXIT_PERCENT = 0.29

    if (RL_FLUSH_DAYS == "") RL_FLUSH_DAYS = 0 #42 may be the optimal number, but to turn it off we use 0
    if (PARTIAL_EXIT_TARGET == "") PARTIAL_EXIT_TARGET = 0
    if (PARTIAL_EXIT_PERCENT == "") PARTIAL_EXIT_PERCENT = 0.50
    if (PARTIAL_EXIT_FOLLOW_TARGET == "") PARTIAL_EXIT_FOLLOW_TARGET = 0.1
    # OUT_FILE: unset/empty = normal audit (summary goes to RocketLauncher.csv + temp_run.csv).
    # Optimizer passes -v OUT_FILE=path to write the summary line only to that path.
    if (SPY_INCLUSION == "") SPY_INCLUSION = 0 # flag that only enters trades if SPY 50>100>200
    spy_inclusion = 0

    # --- DIVE BOMBER (Short-selling inverse of Rocket Launcher) ---
    if (DB_TOGGLE == "") DB_TOGGLE = 0
    if (DB_CASH == "") DB_CASH = RL_CASH
    if (DB_STOP_PCT == "") DB_STOP_PCT = 1.0946      # stop above entry (5% against us for short)
    if (DB_TARGET_PCT == "") DB_TARGET_PCT = 0.92  # target below entry (10% profit)
    if (DB_RIP_DAYS_MIN == "") DB_RIP_DAYS_MIN = 3
    if (DB_RIP_DAYS_MAX == "") DB_RIP_DAYS_MAX = 5
    if (DB_RIP_TOUCH_TOL == "") DB_RIP_TOUCH_TOL = 0.026   # within 2% of 50 SMA = "touch"
    if (DB_MAX_HOLD_DAYS == "") DB_MAX_HOLD_DAYS = 16     # time-based kill (squeeze protection)
    if (DB_SQUEEZE_EXIT == "") DB_SQUEEZE_EXIT = 0       # days for high (0=off); exit if price > N-day high
    if (DB_INVERSE_STRICT == "") DB_INVERSE_STRICT = 0    # 1 = 50<100<200; 0 = 50<100 only
    if (DB_SLOPE_LOOKBACK == "") DB_SLOPE_LOOKBACK = 4    # 50 SMA falling vs N days ago
    if (DB_GAP_UP_MAX == "") DB_GAP_UP_MAX = 1.14         # don't short if next open > ref*this
    if (DB_EXPANSION == "") DB_EXPANSION = 0.98           # inverse expansion: prior close <= sma50*this (weakness)
    if (DB_ACC_MIN == "") DB_ACC_MIN = 9
    if (DB_ACC_COUNT == "") DB_ACC_COUNT = 10
    if (DB_PEAK_TROUGH_MAX == "") DB_PEAK_TROUGH_MAX = -0.43   # inverse peak: no short if already collapsed this far below 50
    if (AVG_VOL_DAYS == "") AVG_VOL_DAYS = 50
    if (VOL_PCT_THRESHOLD == "") VOL_PCT_THRESHOLD = 0

      #printf "# RL_CASH:" RL_CASH
      #printf "\n# RL_DIP_PCT:" RL_DIP_PCT
      #printf "\n# RL_STOP_PCT:" RL_STOP_PCT
      #printf "\n# RL_TARGET_PCT:" RL_TARGET_PCT
      #printf "\n# SMA_QUAL:" SMA_QUAL
      #printf "\n# DEBUG_SYM:" DEBUG_SYM
      #printf "\n# RL_EXPANSION:" RL_EXPANSION
      #printf "\n# RL_ACC_MIN:" RL_ACC_MIN
      #printf "\n# RL_ACC_COUNT:" RL_ACC_COUNT
      #printf "\n# RL_TOO_HIGH:" RL_TOO_HIGH
      #printf "\n# RL_TRAIL_PROFIT:" RL_TRAIL_PROFIT
      #printf "\n# RL_TRAIL_STOP:" RL_TRAIL_STOP
      #printf "\n# RL_100_TOGGLE:" RL_100_TOGGLE
      #printf "\n# RL_100_DIP_PCT:" RL_100_DIP_PCT
      #printf "\n# RL_100_EXPANSION:" RL_100_EXPANSION
      #printf "\n# RL_100_ACC_MIN:" RL_100_ACC_MIN
      #printf "\n# RL_100_ACC_COUNT:" RL_100_ACC_COUNT
      #printf "\n# RL_100_TRAIL_PROFIT:" RL_100_TRAIL_PROFIT
      #printf "\n# RL_100_TRAIL_STOP:" RL_100_TRAIL_STOP
      #printf "\n# RL_100_TARGET_PCT:" RL_100_TARGET_PCT
      #printf "\n# RL_100_STOP_PCT:" RL_100_STOP_PCT
      #printf "\n# RL_CUT_THE_LOSERS:" RL_CUT_THE_LOSERS
      #printf "\n# RL_TRAIL_PROFIT2:" RL_TRAIL_PROFIT2
      #printf "\n# RL_TRAIL_STOP2:" RL_TRAIL_STOP2
      #printf "\n# RL_ATR_HIGH_PERCENT:" RL_ATR_HIGH_PERCENT
      #printf "\n# RL_ATR_LOW_PERCENT:" RL_ATR_LOW_PERCENT
      #printf "\n# RL_SLOPE_PERIOD:" RL_SLOPE_PERIOD
      #printf "\n# RL_SLOPE_THRESHOLD:" RL_SLOPE_THRESHOLD

      # Initialize Global RL Counters (RECORD_CLOSES=1 for normal run; 0 for flush pass 1)
      RECORD_CLOSES = 1
      rl_wins = 0; rl_losses = 0; rl_BEs = 0; rl_sum_wins = 0; rl_sum_losses = 0
      day_exit_equity_50 = ""; day_exit_equity_100 = ""
      rl_open_wins = 0; rl_open_losses = 0; rl_val_open_wins = 0; rl_val_open_losses = 0
      
      # NEW: Initialize Global 100-day Counters and separate closed list for 100-SMA system
      trl100 = 0; rl100_wins = 0; rl100_losses = 0; rl100_sum_wins = 0; rl100_sum_losses = 0
      RL100_closed_ptr = 0
      # Dive Bomber global counters
      trdb = 0; db_wins = 0; db_losses = 0; db_BEs = 0; db_sum_wins = 0; db_sum_losses = 0
      db_closed_ptr = 0; db_open_ptr = 0; db_trade_ptr = 0; db_total_hold_days = 0; db_total_pnl_pct = 0
    
    if (DEBUG_SYM != "")
        printf "" > "Debug.txt"

    if (INSTRUMENT) S_START = get_ms()
}

# ==========================================================================================
# CENTRALIZED TICKER RESET FUNCTION
# ------------------------------------------------------------------------------------------
function reset_ticker_variables() {
    # 1. Clear Accounting States
    rl_inv = 0; rl_pnl = 0; rl_stop = 0; rl_target = 0; rl_trail_active = 0; 
    rl100_inv = 0; rl100_pnl = 0; rl100_stop = 0; rl100_target = 0; rl100_trail_active = 0
    has_hit_time_trigger_100[current_symbol] = 0; time_trigger_counter_100[current_symbol] = 0
    db_inv = 0; db_pnl = 0; db_stop = 0; db_target = 0; db_entry_iso[current_symbol] = ""; db_entry_idx = 0; db_entry_p[current_symbol] = 0; db_entry_smas_set[current_symbol] = 0; db_entry_atr[current_symbol] = 0; db_entry_atr_pct[current_symbol] = 0
    db_pending_signal[current_symbol] = 0; db_pending_entry_iso[current_symbol] = ""; db_peak_trough[current_symbol] = 0
    atr_rolling = 0; s20 = s30 = s50 = s100 = s200 = 0; vol_sum = 0; rl_max_p = rl_min_p = 0; 
    rl100_max_p = rl100_min_p = 0; acc_rolling_hits = 0; acc100_rolling_hits = 0; db_acc_below_50 = 0 
    sym_hwm = 0; max_sym_dd = 0; 
    
    # 2. Reset Milestone & Time Trigger Counters
    m10_days = m20_days = m30_days = m40_days = m50_days = m60_days = 0; 
    has_hit_time_trigger[current_symbol] = 0; time_trigger_counter[current_symbol] = 0; 
    has_hit_milestone[current_symbol] = 0; total_exit_proceeds[current_symbol] = 0; total_shares_sold[current_symbol] = 0; 
    
    # 3. Clear Historical Markers
    exp_hits = 0; ready_to_hit = 1; last_exp_iso = "0"; last_reset_iso = "0"; 
    
    # 4. Clean Memory Slots for the Previous Run
    delete s_q; delete s_p; delete s_fv; 
}

# Currency-safe numeric conversion
function clean(v) {
      gsub(/[\$ \t,"]/, "", v)
      return v + 0
}

function to_iso(d) {
      gsub(/[\$ \t\r"]/, "", d)
      # Fast path: already YYYY-MM-DD (e.g. from CSV) — avoid sprintf to reduce allocator pressure
      if (length(d) == 10 && d ~ /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/) {
            gsub(/-/, "", d); return d
      }
      split(d, a, /[\/\-]/)
      gsub(/\r/, "", a[1]); gsub(/\r/, "", a[2]); gsub(/\r/, "", a[3])
      # Build YYYYMMDD without sprintf to reduce allocator pressure (avoids format_tree/obuf)
      if (length(a[1]) == 4)
            return a[1] (length(a[2])>=2?a[2]:"0"a[2]) (length(a[3])>=2?a[3]:"0"a[3])
      return a[3] (length(a[1])>=2?a[1]:"0"a[1]) (length(a[2])>=2?a[2]:"0"a[2])
}

function abs(v) {  
      return v < 0 ? -v : v  
      }

# Trim working set of all processes via PowerShell (frees RAM; does not kill processes).
# Call after releasing symbol data to reduce AWK process memory pressure.
function trim_working_set(    ps_cmd) {
    ps_cmd = "powershell -NoProfile -Command \"$code = '[DllImport(\\\"psapi.dll\\\")] public static extern int EmptyWorkingSet(IntPtr hwProc);'; $type = Add-Type -MemberDefinition $code -Name \\\"MemoryCleaner\\\" -PassThru; Get-Process | ForEach-Object { try { if ($_.Handle) { $type::EmptyWorkingSet($_.Handle) | Out-Null } } catch {} }\""
    system(ps_cmd)
}

# Date-to-epoch cache: mktime is expensive; cache per unique date
function date_to_epoch(d,    e) {
    if (d in date_epoch) return date_epoch[d]
    e = mktime(substr(d,1,4) " " substr(d,5,2) " " substr(d,7,2) " 00 00 00")
    date_epoch[d] = e
    return e
}
function days_diff(d1, d2) {
    return int((date_to_epoch(d2) - date_to_epoch(d1)) / SECONDS_PER_DAY)
}

# ==========================================================================================
# ROCKET BRT PIVOT DETECTION (Specification v1.0)
# Pivot High: local max + 6% rejection in next 7 bars. Pivot Low: local min + 6% bounce.
# Tie-break: earliest bar among ties. Requires future bars for confirmation.
# ------------------------------------------------------------------------------------------
function compute_pivots_for_symbol(sym,    j, N, k, m, d, hi_j, lo_j, wmax, wmin, firstIdxHi, firstIdxLo, ii, futureLoMin, futureHiMax, isPH, isPL) {
    k = BRT_PIVOT_K + 0
    m = BRT_PIVOT_M + 0
    d = BRT_PIVOT_D + 0
    N = d_ptr[sym] + 0
    if (N < k + 1 + m) return  # Need enough bars
    for (j = k + 1; j <= N - m; j++) {
        hi_j = raw_hi[sym, dates[sym, j]] + 0
        lo_j = raw_lo[sym, dates[sym, j]] + 0
        wmax = hi_j
        wmin = lo_j
        firstIdxHi = j
        firstIdxLo = j
        for (ii = j - k; ii <= j + k; ii++) {
            if (ii >= 1 && ii <= N) {
                if (raw_hi[sym, dates[sym, ii]] + 0 > wmax) { wmax = raw_hi[sym, dates[sym, ii]] + 0; firstIdxHi = ii }
                if (raw_lo[sym, dates[sym, ii]] + 0 < wmin) { wmin = raw_lo[sym, dates[sym, ii]] + 0; firstIdxLo = ii }
            }
        }
        # Tie-break: first bar with max/min
        for (ii = j - k; ii <= j + k; ii++) {
            if (ii >= 1 && ii <= N) {
                if ((raw_hi[sym, dates[sym, ii]] + 0) == wmax && ii < firstIdxHi) firstIdxHi = ii
                if ((raw_lo[sym, dates[sym, ii]] + 0) == wmin && ii < firstIdxLo) firstIdxLo = ii
            }
        }
        isPH = (hi_j == wmax && j == firstIdxHi)
        isPL = (lo_j == wmin && j == firstIdxLo)
        futureLoMin = 1e99
        futureHiMax = -1
        for (ii = j + 1; ii <= j + m; ii++) {
            if (ii <= N) {
                if ((raw_lo[sym, dates[sym, ii]] + 0) < futureLoMin) futureLoMin = raw_lo[sym, dates[sym, ii]] + 0
                if ((raw_hi[sym, dates[sym, ii]] + 0) > futureHiMax) futureHiMax = raw_hi[sym, dates[sym, ii]] + 0
            }
        }
        if (isPH && futureLoMin <= hi_j * (1 - d)) { pivot_high[sym, dates[sym, j]] = 1; pivot_high_price[sym, dates[sym, j]] = hi_j }
        else { pivot_high[sym, dates[sym, j]] = 0; pivot_high_price[sym, dates[sym, j]] = "" }
        if (isPL && futureHiMax >= lo_j * (1 + d)) { pivot_low[sym, dates[sym, j]] = 1; pivot_low_price[sym, dates[sym, j]] = lo_j }
        else { pivot_low[sym, dates[sym, j]] = 0; pivot_low_price[sym, dates[sym, j]] = "" }
    }
}

# ==========================================================================================
# ROCKET BRT LEVEL 2 — Market Structure Engine (Reporting only; no trade impact)
# Structure: HH/HL/LH/LL. Major: pivot that led to structural breakdown/expansion.
# ------------------------------------------------------------------------------------------
function compute_market_structure_for_symbol(sym,    j, N, k, m, lastPH, lastPL, prevPH, prevPL, j2, nextPL, nextPH, _ph, _pl) {
    k = BRT_PIVOT_K + 0
    m = BRT_PIVOT_M + 0
    N = d_ptr[sym] + 0
    if (N < k + 1 + m) return
    lastPH = ""; lastPL = ""; prevPH = ""; prevPL = ""
    # Pass 1: structure labels and last-pivot tracking
    for (j = k + 1; j <= N - m; j++) {
        structure_high[sym, dates[sym, j]] = ""
        structure_low[sym, dates[sym, j]] = ""
        major_pivot_high[sym, dates[sym, j]] = 0
        major_pivot_low[sym, dates[sym, j]] = 0
        if (pivot_high[sym, dates[sym, j]] == 1) {
            _ph = pivot_high_price[sym, dates[sym, j]] + 0
            if (lastPH != "") {
                if (_ph > lastPH + 0) structure_high[sym, dates[sym, j]] = "HH"
                else structure_high[sym, dates[sym, j]] = "LH"
            }
            prevPH = lastPH; lastPH = _ph
        }
        if (pivot_low[sym, dates[sym, j]] == 1) {
            _pl = pivot_low_price[sym, dates[sym, j]] + 0
            if (lastPL != "") {
                if (_pl > lastPL + 0) structure_low[sym, dates[sym, j]] = "HL"
                else structure_low[sym, dates[sym, j]] = "LL"
            }
            prevPL = lastPL; lastPL = _pl
        }
        last_pivot_high_price[sym, dates[sym, j]] = (lastPH != "") ? lastPH + 0 : ""
        last_pivot_low_price[sym, dates[sym, j]] = (lastPL != "") ? lastPL + 0 : ""
        prev_pivot_high_price[sym, dates[sym, j]] = (prevPH != "") ? prevPH + 0 : ""
        prev_pivot_low_price[sym, dates[sym, j]] = (prevPL != "") ? prevPL + 0 : ""
    }
    # Pass 2: major pivots (forward scan to next opposite pivot)
    for (j = k + 1; j <= N - m; j++) {
        if (pivot_high[sym, dates[sym, j]] == 1) {
            nextPL = ""
            for (j2 = j + 1; j2 <= N - m; j2++) {
                if (pivot_low[sym, dates[sym, j2]] == 1) { nextPL = structure_low[sym, dates[sym, j2]]; break }
            }
            major_pivot_high[sym, dates[sym, j]] = (nextPL == "LL") ? 1 : 0
        }
        if (pivot_low[sym, dates[sym, j]] == 1) {
            nextPH = ""
            for (j2 = j + 1; j2 <= N - m; j2++) {
                if (pivot_high[sym, dates[sym, j2]] == 1) { nextPH = structure_high[sym, dates[sym, j2]]; break }
            }
            major_pivot_low[sym, dates[sym, j]] = (nextPH == "HH") ? 1 : 0
        }
    }
}

# ==========================================================================================
# CENTRALIZED DEBUG LOGGING FUNCTIONS
# ------------------------------------------------------------------------------------------
function debug_print(sym, message) {
    if (DEBUG_SYM == sym || DEBUG_SYM == "ALL") {
        printf "[%s] %s\n", sym, message >> "Debug.txt"
    }
}

function debug_printf(sym, format, val1, val2, val3, val4, val5, val6, val7, val8, val9, val10, val11, val12, val13, val14, val15, val16, val17, val18, val19, val20, val21, val22, val23, val24, val25, val26, val27, val28, val29, val30,    formatted) {
    if (DEBUG_SYM == sym || DEBUG_SYM == "ALL") {
        # AWK's sprintf handles extra arguments gracefully (ignores unused ones)
        # Declared 30 value parameters to avoid "called with more arguments than declared" warnings
        formatted = sprintf(format, val1, val2, val3, val4, val5, val6, val7, val8, val9, val10, val11, val12, val13, val14, val15, val16, val17, val18, val19, val20, val21, val22, val23, val24, val25, val26, val27, val28, val29, val30)
        printf "%s", formatted >> "Debug.txt"
    }
}

# (History file / PHASE 1 removed: no longer required; backtest runs from ticker data only.)

# PHASE 4: ACCOUNTING PASS
function perform_audit(sym) {
      if (sym == "") return
      if (first_audit_sym == "") first_audit_sym = sym
      if (sym == first_audit_sym) {
            printf "AUDIT_START sym=%s d_ptr=%d date1=[%s] len_date1=%d raw_op_date1=%.2f raw_lo_date1=%.2f\n", sym, d_ptr[sym]+0, dates[sym, 1], length(dates[sym, 1]), raw_op[sym, dates[sym, 1]]+0, raw_lo[sym, dates[sym, 1]]+0 >> DIAG_FILE
      }
      all_syms[sym] = 1; 
      acc_rec_cnt++; streak = 0; delete s_q; delete s_p; delete s_fv; last_tid = ""
      
      # Parallel Tracking for 50 and 100 day systems
      rl_inv = 0; rl_pnl = 0; rl_stop = 0; rl_target = 0; rl_trail_active = 0
      rl100_inv = 0; rl100_pnl = 0; rl100_stop = 0; rl100_target = 0; rl100_trail_active = 0
      has_hit_time_trigger_100[sym] = 0; time_trigger_counter_100[sym] = 0
      db_inv = 0; db_pnl = 0; db_stop = 0; db_target = 0; db_entry_iso[sym] = ""; db_entry_idx = 0; db_entry_p[sym] = 0; db_entry_smas_set[sym] = 0
      atr_rolling = 0; # NEW: Reset ATR for the current symbol
      s20 = s30 = s50 = s100 = s200 = 0; vol_sum = 0
      rl_max_p = rl_min_p = 0
      rl100_max_p = rl100_min_p = 0
      acc_rolling_hits = 0; acc100_rolling_hits = 0; db_acc_below_50 = 0
      rl_trail_active = 0
      sym_hwm = 0; max_sym_dd = 0
      s_50_wins = s_50_losses = s_50_BEs = 0
      s_100_wins = s_100_losses = s_100_BEs = 0
      m10_days = m20_days = m30_days = m40_days = m50_days = m60_days = 0
      # --- NEW: SHOCK & STREAK RESET ---
      shock_count = 0
      delete shock_event_dates
      max_loss_streak = 0
      cur_loss_streak = 0
      # ---------------------------------
      exit_type = ""

      # Rocket BRT Pivot Detection: compute pivot_high[sym,iso] and pivot_low[sym,iso] for this symbol
      delete pivot_high; delete pivot_low; delete pivot_high_price; delete pivot_low_price
      compute_pivots_for_symbol(sym)
      compute_market_structure_for_symbol(sym)
      # Write pivot report (SYMBOL,DATE,TYPE,PRICE) for all pivots
      N = d_ptr[sym] + 0
      k = BRT_PIVOT_K + 0
      m = BRT_PIVOT_M + 0
      if (N >= k + 1 + m) {
          if (pivot_file_header_done == 0) {
              printf "SYMBOL,DATE,TYPE,PRICE\n" > pivot_file
              pivot_file_header_done = 1
          }
          for (_pj = k + 1; _pj <= N - m; _pj++) {
              _piso = dates[sym, _pj]
              if (pivot_high[sym, _piso] == 1)
                  printf "%s,%s,PIVOT_HIGH,%.4f\n", sym, _piso, pivot_high_price[sym, _piso] + 0 >> pivot_file
              if (pivot_low[sym, _piso] == 1)
                  printf "%s,%s,PIVOT_LOW,%.4f\n", sym, _piso, pivot_low_price[sym, _piso] + 0 >> pivot_file
          }
          close(pivot_file)
      }

# Expansion Validation (Strictly Historical)
      exp_hits = 0; ready_to_hit = 1
      curr_exp_iso = "0"; curr_reset_iso = "0" # Buffer for the "Triggering" event
      hist_exp_iso = "0"; hist_reset_iso = "0" # Buffer for the "Prior" event
      hist_exp_hits = 0
      prior_reset_iso = "0"
      # Final Historical variables for the report
      last_exp_iso = "0"; last_reset_iso = "0"

      for (j = 1; j <= d_ptr[sym]; j++) 
      {
            if (INSTRUMENT) _t0 = get_ms()
            y_iso = (j > 1) ? dates[sym, j-1] : ""
            y_sma = (y_iso != "" && sma50[y_iso] > 0) ? sma50[y_iso] : 0
            if (sma50[y_iso] > 0)
            {
                  # Calculate current day's percentages vs yesterday's SMA50
                  cur_hi_pct = (raw_hi[sym, iso] - y_sma) / y_sma
                  cur_cl_pct = (raw_cl[sym, iso] - y_sma) / y_sma
                  cur_lo_pct = (raw_lo[sym, iso] - y_sma) / y_sma

                  # Update lifetime peaks for this symbol
                  if (cur_hi_pct > peak_hi[sym]) peak_hi[sym] = cur_hi_pct
                  if (cur_cl_pct > peak_cl[sym]) peak_cl[sym] = cur_cl_pct
                  if (cur_lo_pct > peak_lo[sym]) peak_lo[sym] = cur_lo_pct
                  # Dive Bomber inverse peak (trough): min of close % below 50; don't short if already collapsed too far
                  if (cur_cl_pct < db_peak_trough[sym]) db_peak_trough[sym] = cur_cl_pct

                  # Calculate current distance from SMA50
                  cur_exp = (raw_hi[sym, iso] - sma50[iso]) / sma50[iso]
                  target_threshold = RL_TARGET_PCT - 1

                  # 1. THE HIT: Simple and immediate
                if (cur_exp >= target_threshold && ready_to_hit == 1) {
                    exp_hits++
                    # Capture the reset that happened PRIOR to this specific hit
                    prior_reset_iso = last_reset_iso
                    last_exp_iso = iso  # This captures the trigger expansion
                    ready_to_hit = 0  
                }

                # 2. THE RESET: Simple and immediate
                if (raw_lo[sym, iso] <= (sma50[iso] * RL_DIP_PCT)) {
                    ready_to_hit = 1
                    last_reset_iso = iso
                }
                  
            }
            if (INSTRUMENT) T_TOP_MS += get_ms() - _t0
            # --- SHOCK DETECTOR LOGIC (skip entirely when RL_SHOCK_THRESHOLD==0) ---
            if (RL_SHOCK_THRESHOLD == 0) {
                shock_qualified = 1
                active_shocks = 0
                days_remaining_in_rehab = 0
            } else {
                if (INSTRUMENT) _t0 = get_ms()
                p_today_cl = raw_cl[sym, iso]
                p_yesterday_cl = (j > 1) ? raw_cl[sym, dates[sym, j-1]] : p_today_cl
                daily_move = (p_yesterday_cl > 0) ? abs((p_today_cl - p_yesterday_cl) / p_yesterday_cl) : 0
                shock_qualified = (active_shocks <= RL_SHOCK_MAX_ALLOWED)
                if (daily_move > RL_SHOCK_THRESHOLD) {
                    shock_event_dates[++shock_count] = iso
                    last_shock_magnitude[sym] = daily_move
                }
                active_shocks = 0
                days_remaining_in_rehab = 0
                # Iterate newest-to-oldest; break when shock too old (remaining are older)
                for (s_idx = shock_count; s_idx >= 1; s_idx--) {
                    diff = days_diff(shock_event_dates[s_idx], iso)
                    if (diff > RL_SHOCK_REHAB_DAYS) break
                    active_shocks++
                    current_rehab_left = RL_SHOCK_REHAB_DAYS - diff
                    if (current_rehab_left > days_remaining_in_rehab) days_remaining_in_rehab = current_rehab_left
                }
                if (INSTRUMENT) T_SHOCK_MS += get_ms() - _t0
            }

            # --- VOLATILITY TRACKING (ATR) ---
            if (INSTRUMENT) _t0 = get_ms()
            tr_today = raw_hi[sym, iso] - raw_lo[sym, iso]
            if (atr_rolling == 0) {
                atr_rolling = tr_today # Initialize on first day
            } else {
                # ATR_PERIOD-day Exponential Moving Average of True Range
                atr_rolling = ((atr_rolling * ATR_EMA_MULTIPLIER) + tr_today) / ATR_PERIOD
            }
            if (INSTRUMENT) T_ATR_MS += get_ms() - _t0

            iso = dates[sym, j]

            next_day_iso = ""
            tid = ""
            # No-op when History not supplied (t_list_ptr[sym]==0); kept for possible future use.
            for (p = 1; p <= t_list_ptr[sym]; p++) {
                id = t_list[sym, p]
                if (iso >= st_iso[id] && (iso <= en_iso[id] || !en_iso[id])) {
                    tid = id
                    break 
                }
            }

            if (INSTRUMENT) { _t0 = get_ms(); _t_sma_top = _t0 }
            p_today = raw_cl[sym, iso]
            _use_computed = 1
            # Use precomputed SMAs from Python when available; else compute in AWK (backward compat)
            key_sma = sym SUBSEP iso
            if (key_sma in raw_sma && raw_sma[sym, iso] != "") {
                n = split(raw_sma[sym, iso], arr, "|")
                # Accept prepacked row when SMA50 is ready, or before day 50 when SMA20 is
                # already filled (Python precompute); avoids ~50 PRECOMP_SMA_MISS bars per symbol.
                if (n >= 5 && ((arr[3]+0) > 0 || (j < SMA_PERIOD_50 && (arr[1]+0) > 0))) {
                    sma20[iso] = arr[1] + 0
                    sma30[iso] = arr[2] + 0
                    sma50[iso] = arr[3] + 0
                    sma100[iso] = arr[4] + 0
                    sma200[iso] = arr[5] + 0
                    _use_computed = 0
                    if (INSTRUMENT) PRECOMP_SMA_HITS++
                }
            }
            if (_use_computed) {
                if (INSTRUMENT) PRECOMP_SMA_MISS++
                s20 += p_today; if (j > SMA_PERIOD_20) s20 -= raw_cl[sym, dates[sym, j-SMA_PERIOD_20]]
                if (j >= SMA_PERIOD_20) sma20[iso] = s20 / SMA_PERIOD_20
                s30 += p_today; if (j > SMA_PERIOD_30) s30 -= raw_cl[sym, dates[sym, j-SMA_PERIOD_30]]
                if (j >= SMA_PERIOD_30) sma30[iso] = s30 / SMA_PERIOD_30
                s50 += p_today; if (j > SMA_PERIOD_50) s50 -= raw_cl[sym, dates[sym, j-SMA_PERIOD_50]]
                if (j >= SMA_PERIOD_50) sma50[iso] = s50 / SMA_PERIOD_50
                s100 += p_today; if (j > SMA_PERIOD_100) s100 -= raw_cl[sym, dates[sym, j-SMA_PERIOD_100]]
                if (j >= SMA_PERIOD_100) sma100[iso] = s100 / SMA_PERIOD_100
                s200 += p_today; if (j > SMA_PERIOD_200) s200 -= raw_cl[sym, dates[sym, j-SMA_PERIOD_200]]
                if (j >= SMA_PERIOD_200) sma200[iso] = s200 / SMA_PERIOD_200
            }
            # Rolling average volume (for AVG_VOL_DAYS and VOL_PCT_THRESHOLD)
            if (AVG_VOL_DAYS > 0) {
                _v = raw_vol[sym, iso] + 0
                vol_sum += _v
                if (j > AVG_VOL_DAYS) vol_sum -= (raw_vol[sym, dates[sym, j-AVG_VOL_DAYS]] + 0)
                avg_vol = (j >= AVG_VOL_DAYS) ? vol_sum / AVG_VOL_DAYS : 0
            } else {
                avg_vol = 0
            }
            if (INSTRUMENT) T_SMA_LOOKUP_MS += get_ms() - _t0

            if (INSTRUMENT) _t0 = get_ms()
            # N-day high (for Dive Bomber squeeze exit; DB_SQUEEZE_EXIT=0 disables)
            current_squeeze_high = 0
            squeeze_days = DB_SQUEEZE_EXIT + 0
            if (squeeze_days > 0 && j >= squeeze_days) {
                for (_k = 0; _k < squeeze_days; _k++) {
                    _d = dates[sym, j - _k]
                    if (raw_hi[sym, _d] > current_squeeze_high) current_squeeze_high = raw_hi[sym, _d]
                }
            }
            if (INSTRUMENT) T_SMA_NDAY_MS += get_ms() - _t0

            if (INSTRUMENT) _t0 = get_ms()
            # --- SMA50 SLOPE --- only when RL_SLOPE_THRESHOLD != 0 (threshold 0 = filter off; skip ratio work)
            p_idx = j; prev_p_iso = dates[sym, p_idx-1]
            _s50_iso = sma50[iso]; _s50_prev = sma50[prev_p_iso]; _s100_iso = sma100[iso]; _s100_prev = sma100[prev_p_iso]
            current_slope = 0
            if ((RL_SLOPE_THRESHOLD+0) != 0 && j > RL_SLOPE_PERIOD) {
                slope_old_iso = dates[sym, j - RL_SLOPE_PERIOD]
                _s50_old = sma50[slope_old_iso]
                if (_s50_old > 0) current_slope = (_s50_iso / _s50_old) - 1
            }
            if (_s50_prev > 0 && raw_cl[sym, iso] > _s50_prev) acc_rolling_hits++
            if (j > RL_ACC_COUNT) {
                old_idx = j - RL_ACC_COUNT; old_iso = dates[sym, old_idx]; old_prev_iso = dates[sym, old_idx-1]
                _s50_old_prev = sma50[old_prev_iso]
                if (_s50_old_prev > 0 && raw_cl[sym, old_iso] > _s50_old_prev) acc_rolling_hits--
            }
            if (_s50_prev > 0 && raw_cl[sym, iso] < _s50_prev) db_acc_below_50++
            if (j > DB_ACC_COUNT) {
                old_idx_db = j - DB_ACC_COUNT; old_iso_db_acc = dates[sym, old_idx_db]; old_prev_iso_db = dates[sym, old_idx_db-1]
                _s50_old_prev_db = sma50[old_prev_iso_db]
                if (_s50_old_prev_db > 0 && raw_cl[sym, old_iso_db_acc] < _s50_old_prev_db) db_acc_below_50--
            }
            db_acceptance = (db_acc_below_50 >= DB_ACC_MIN) ? 1 : 0
            if (_s100_prev > 0 && raw_cl[sym, iso] > _s100_prev) acc100_rolling_hits++
            if (j > RL100_ACC_COUNT) {
                old_idx100 = j - RL100_ACC_COUNT; old_iso100 = dates[sym, old_idx100]; old_prev_iso100 = dates[sym, old_idx100-1]
                _s100_old_prev = sma100[old_prev_iso100]
                if (_s100_old_prev > 0 && raw_cl[sym, old_iso100] > _s100_old_prev) acc100_rolling_hits--
            }
            # 100-SMA slope ratio only when RL100_SLOPE_THRESHOLD != 0
            current_slope_100 = 0
            if ((RL100_SLOPE_THRESHOLD+0) != 0 && j > RL100_SLOPE_PERIOD) {
                slope_old_iso_100 = dates[sym, j - RL100_SLOPE_PERIOD]
                _s100_old = sma100[slope_old_iso_100]
                if (_s100_old > 0) current_slope_100 = (_s100_iso / _s100_old) - 1
            }
            acceptance = (acc_rolling_hits >= RL_ACC_MIN) ? 1 : 0
            if (INSTRUMENT) { T_SMA_SLOPE_ACC_MS += get_ms() - _t0; T_SMA_MS += get_ms() - _t_sma_top }

            # Dive Bomber: process pending entry on entry day (entry-day open must be within ±DB_RIP_TOUCH_TOL of entry-day SMA50)
            if (DB_TOGGLE == 1 && db_pending_signal[sym] && iso == db_pending_entry_iso[sym] && _s50_iso > 0 && raw_op[sym, iso] > 0) {
                entry_near_50_today = (raw_op[sym, iso] >= _s50_iso * (1 - DB_RIP_TOUCH_TOL) && raw_op[sym, iso] <= _s50_iso * (1 + DB_RIP_TOUCH_TOL))
                if (entry_near_50_today) {
                    db_inv = DB_CASH / raw_op[sym, iso]
                    db_stop = raw_op[sym, iso] * DB_STOP_PCT
                    db_target = raw_op[sym, iso] * DB_TARGET_PCT
                    db_entry_iso[sym] = iso
                    db_entry_p[sym] = raw_op[sym, iso]
                    db_entry_idx = j
                    db_signal_hi[sym] = db_pending_signal_hi[sym]
                    db_signal_sma50[sym] = db_pending_signal_sma50[sym]
                    db_signal_sma100[sym] = db_pending_signal_sma100[sym]
                    db_signal_sma200[sym] = db_pending_signal_sma200[sym]
                    db_entry_sma50[sym] = (_s50_iso > 0) ? _s50_iso : 0
                    db_entry_sma100[sym] = (_s100_iso > 0) ? _s100_iso : 0
                    _s200_iso = sma200[iso]; db_entry_sma200[sym] = (_s200_iso > 0) ? _s200_iso : 0
                    db_entry_smas_set[sym] = 1
                    db_entry_atr[sym] = (atr_rolling > 0) ? atr_rolling : 0
                    db_entry_atr_pct[sym] = (raw_op[sym, iso] > 0 && atr_rolling > 0) ? (atr_rolling / raw_op[sym, iso]) : 0
                }
                db_pending_signal[sym] = 0
                db_pending_entry_iso[sym] = ""
            }

            # ---------------------------------------------------------
            # 50-DAY SYSTEM MANAGEMENT (Original Strategy Pass)
            # ---------------------------------------------------------
            if (rl_inv > 0) {
                if (INSTRUMENT) _t0 = get_ms()
                debug_printf(sym, "\nrl_inv:%.2f", rl_inv)
                
                daily_pos_count[iso]++
                # Capture stock SMAs at entry (as of entry day) on first bar in position
                if (iso == rl_entry_iso[sym] && entry_smas_set[sym] == 0) {
                    entry_sma20[sym] = (sma20[iso] > 0) ? sma20[iso] : 0
                    entry_sma30[sym] = (sma30[iso] > 0) ? sma30[iso] : 0
                    entry_sma50[sym] = (sma50[iso] > 0) ? sma50[iso] : 0
                    entry_sma100[sym] = (sma100[iso] > 0) ? sma100[iso] : 0
                    entry_sma200[sym] = (sma200[iso] > 0) ? sma200[iso] : 0
                    entry_smas_set[sym] = 1
                }

                if (j > 1 && sma50[dates[sym, j-1]] > 0) 
                    {
                    rl_target = sma50[dates[sym, j-1]] * RL_TARGET_PCT
                    debug_printf(sym, "\nSETTING RL_TARGET:\nrl_target:%.2f\niso:%s\ndates[sym, j-1]:%s\nraw_hi[sym, iso]:%.2f\nexecute_exit:%d", rl_target, iso, dates[sym, j-1], raw_hi[sym, iso], execute_exit)
                    }
                # Reset exit flag for the current day's bar
                execute_exit = 0
                # FLUSH_EXIT: sell all positions after portfolio has been underwater RL_FLUSH_DAYS days (flush_trigger set in END pass 1)
                # Only flush positions held at least 1 day (never sell same-day opens)
                if (RL_FLUSH_DAYS > 0 && flush_trigger[iso] == 1 && rl_entry_iso[sym] != iso) {
                    execute_exit = 1
                    exit_type = "FLUSH_EXIT"
                }

                  # --- MILESTONE TRACKING ---
                  # Calculate current profit % from entry
                  curr_profit_pct = (raw_hi[sym, iso] - rl_entry_p[sym]) / rl_entry_p[sym]

                  # Capture day count for each milestone if reached for the first time
                  if (curr_profit_pct >= MILESTONE_10_PCT && m10_days == 0) m10_days = days_diff(rl_entry_iso[sym], iso) + 1
                  if (curr_profit_pct >= MILESTONE_20_PCT && m20_days == 0) m20_days = days_diff(rl_entry_iso[sym], iso) + 1
                  if (curr_profit_pct >= MILESTONE_30_PCT && m30_days == 0) m30_days = days_diff(rl_entry_iso[sym], iso) + 1
                  if (curr_profit_pct >= MILESTONE_40_PCT && m40_days == 0) m40_days = days_diff(rl_entry_iso[sym], iso) + 1
                  if (curr_profit_pct >= MILESTONE_50_PCT && m50_days == 0) m50_days = days_diff(rl_entry_iso[sym], iso) + 1
                  if (curr_profit_pct >= MILESTONE_60_PCT && m60_days == 0) m60_days = days_diff(rl_entry_iso[sym], iso) + 1

                  if (rl_max_p < raw_hi[sym, iso]) rl_max_p = raw_hi[sym, iso]
                  if (rl_min_p > raw_lo[sym, iso] || rl_min_p == 0) rl_min_p = raw_lo[sym, iso]

                # --- TIMED EXIT LOGIC ---
                # Check if we hit the time trigger for the first time
                debug_printf(sym, "\nSection 7:sym:%s\nexit_type:%s\ncurr_profit_pct:%.4f\nRL_EXIT_PERCENT:%.4f\nhas_hit_time_trigger[sym]:%d", sym, exit_type, curr_profit_pct, RL_EXIT_PERCENT, has_hit_time_trigger[sym])
                if (has_hit_time_trigger[sym] == 0 && RL_EXIT_PERCENT > 0 && curr_profit_pct >= RL_EXIT_PERCENT) {
                    has_hit_time_trigger[sym] = 1
                    time_trigger_counter[sym] = 0  # Start the countdown
                }
                  
                # If triggered, manage the exit
                debug_printf(sym, "\nSection 5:sym:%s\nexit_type:%s\ncurr_profit_pct:%.4f\nRL_EXIT_PERCENT:%.4f", sym, exit_type, curr_profit_pct, RL_EXIT_PERCENT)

                if (has_hit_time_trigger[sym] == 1) 
                        time_trigger_counter[sym]++
                
                debug_printf(sym, "\nSection 6:sym:%s\nexit_type:%s", sym, exit_type)

                # --- PARTIAL EXIT LOGIC ---
                if (execute_exit == 0 && has_hit_milestone[sym] == 0 && PARTIAL_EXIT_TARGET > 0 && curr_profit_pct >= PARTIAL_EXIT_TARGET) {
                    debug_print(sym, "\nHERE1: Partial exit triggered")

                    has_hit_milestone[sym] = 1
                    partial_exit_date[sym] = iso

                    # Calculate shares to sell (Partial sell-off)
                    shares_to_sell = int(rl_inv * PARTIAL_EXIT_PERCENT)
                    rl_inv -= shares_to_sell
                    
                    # Track proceeds and shares for the Average Exit Price
                    p_exit_price = raw_hi[sym, iso]
                    total_exit_proceeds[sym] += (shares_to_sell * p_exit_price)
                    total_shares_sold[sym] += shares_to_sell

                    # Bank the amount for the summary
                    p_exit_val = (shares_to_sell * p_exit_price) - (shares_to_sell * rl_entry_p[sym])
                    rl_pnl += p_exit_val
                    trl += p_exit_val
                    partial_exit_amount[sym] = p_exit_val
                    sym_partial_cnt[sym]++
                    sym_partial_amt[sym] += p_exit_val

                    # Reset the target for the remaining shares
                    if (PARTIAL_EXIT_TARGET != 0) {
                        current_target[sym] = (rl_entry_p[sym] * (1 + PARTIAL_EXIT_TARGET + PARTIAL_EXIT_FOLLOW_TARGET))
                        debug_printf(sym, "\ncurrent_target[sym]:%.2f\nrl_entry_p[sym]:%.2f", current_target[sym], rl_entry_p[sym])
                    }
                }

                  if (RL_TRAIL_PROFIT > 0 && rl_trail_active == 0 && raw_hi[sym, iso] >= (rl_entry_p[sym] * (1 + RL_TRAIL_PROFIT))) {
                    debug_print(sym, "\nHERE2: Trail 1 activated")
                      rl_trail_active = 1
                      rl_stop = rl_entry_p[sym] * (1 + RL_TRAIL_STOP)
                  }

                  # --- TRAIL 2 ACTIVATION (The new 40%) ---
                  # If we hit RL_TRAIL_PROFIT2, we overwrite Trail 1 with the more aggressive Trail 2 stop
                  if (RL_TRAIL_PROFIT2 > 0 && raw_hi[sym, iso] >= (rl_entry_p[sym] * (1 + RL_TRAIL_PROFIT2))) {
                    debug_print(sym, "\nHERE3: Trail 2 activated")
                      rl_trail_active = 2 # Setting this to 2 distinguishes the exit type
                      rl_stop = rl_entry_p[sym] * (1 + RL_TRAIL_STOP2)
                  }

# --- PROFIT RACE & DEFENSE DECISION BLOCK ---
                if (execute_exit == 0) {
                # --- 1. UPDATE TARGETS & COUNTDOWN ---
                timed_exit_px = rl_entry_p[sym] * (1 + RL_EXIT_PERCENT)
                sma_target_px = rl_target
                debug_print(sym, "\nHERE4: Checking exit conditions")
                
                # EXECUTION DECISION
                # 1. Check STOP LOSS (Defense First)
                # On entry day only: use close instead of low to avoid false stop-out from wide intraday range.
                # With OHLC we don't know if high or low came first; assuming both can be hit can incorrectly
                # trigger a trail-to-BE then stop (e.g. CMCL 20200630: O=14.59 H=17.36 L=14.50 C=17.32).
                # Using close respects end-of-day outcome and avoids stopping winners that closed strong.
                stop_price = (iso == rl_entry_iso[sym]) ? raw_cl[sym, iso] : raw_lo[sym, iso]
                if (stop_price <= rl_stop) {
                debug_printf(sym, "\nHERE7:\nstop_price:%.2f (entry_day=%d)\nrl_stop:%.2f", stop_price, (iso == rl_entry_iso[sym]), rl_stop)

                    execute_exit = 1
                    rl_sell = (rl_stop > raw_op[sym, iso]) ? rl_stop : raw_op[sym, iso]
                        exit_type = (rl_trail_active == 2) ? "TRAIL_STOP2" : (rl_trail_active == 1 ? "TRAIL_STOP" : "STOP_LOSS")
                } 
                # 2. Check PROFIT RACE (Only if Stop wasn't hit)
                else {
                    hit_sma = (sma_target_px > 0 && raw_hi[sym, iso] >= sma_target_px)
                    hit_timed = (has_hit_time_trigger[sym] == 1 && time_trigger_counter[sym] >= RL_EXIT_DAYS)

                    if (hit_sma && hit_timed) {
                        debug_printf(sym, "\nHERE8:\nhit_timed:%d", hit_timed)
                        execute_exit = 1
                        # Price climbed from Open. Use lower price (hit first).
                        if (sma_target_px < timed_exit_px) {
                            debug_print(sym, "\nHERE9: SMA target hit first")
                            rl_sell = (sma_target_px > raw_op[sym, iso]) ? sma_target_px : raw_op[sym, iso]
                            exit_type = "TARGET"
                        } else {
                            debug_printf(sym, "\nHERE17:\nhit_timed:%d\niso:%s", hit_timed, iso)
                            rl_sell = raw_op[sym, iso]
                            exit_type = "RL_EXIT_DAYS"
                        }
                    }
                    else if (hit_sma) {
                        debug_print(sym, "\nHERE11: SMA target hit")
                        execute_exit = 1; exit_type = "TARGET"
                        rl_sell = (sma_target_px > raw_op[sym, iso]) ? sma_target_px : raw_op[sym, iso]
                    }
                    else if (hit_timed) {
                        debug_printf(sym, "\nHERE12:\nhit_timed:%d\niso:%s", hit_timed, iso)
                        execute_exit = 1; exit_type = "RL_EXIT_DAYS"
                        rl_sell = raw_op[sym, iso]
                    }
                }
            }
                    # If any trigger hit (Timed, Stop, or Target), execute the close
                  if (execute_exit == 1) {
                        debug_print(sym, "\nHERE13: Executing exit")
                    
                    # 1. PRICE DETERMINATION 
                    if (exit_type == "RL_EXIT_DAYS") 
                    {
                        if (hit_timed == 0)
                        {
                            debug_printf(sym, "\nHERE14:STATE1:curr_profit_pct:%.4f\nRL_EXIT_PERCENT:%.4f", curr_profit_pct, RL_EXIT_PERCENT)

                            if (raw_op[sym, iso] > (rl_entry_p[sym] * (1+RL_EXIT_PERCENT)))
                                rl_sell = raw_op[sym, iso]
                            else    
                                rl_sell = (rl_entry_p[sym] * (1+RL_EXIT_PERCENT))
                        
                            timed_exit_count++
                        }
                    }
                    else if (exit_type == "TARGET") 
                    {
                        debug_printf(sym, "\nHERE15:current_target[sym]:%.2f\nraw_op[sym, iso]:%.2f\nrl_target:%.2f\niso:%s", current_target[sym], raw_op[sym, iso], rl_target, iso)
                        rl_sell = (rl_target > raw_op[sym, iso]) ? rl_target : raw_op[sym, iso]
                    }
                    else if (exit_type == "FLUSH_EXIT")
                        rl_sell = raw_op[sym, iso]
                    else 
                        rl_sell = rl_stop # Stop Loss / Trailing Stop

                    # 2. CORE ACCOUNTING (Calculated once per exit)
                    trade_val = (rl_inv * rl_sell)
                    total_exit_proceeds[sym] += trade_val
                    total_shares_sold[sym] += rl_inv

                    debug_printf(sym, "\nHERE16:initial_shares_at_entry[sym]:%.2f\nraw_op[sym, iso]:%.2f\nrl_target:%.2f\niso:%s", initial_shares_at_entry[sym], raw_op[sym, iso], rl_target, iso)
                    
                    if (initial_shares_at_entry[sym] > 0)
                        avg_exit_price = total_exit_proceeds[sym] / initial_shares_at_entry[sym]

                    # Calculate trade value based on the actual exit price
                    current_trade_val = (initial_shares_at_entry[sym] * rl_sell)

                    # Update High Water Mark using this final value
                    if (current_trade_val > sym_hwm) sym_hwm = current_trade_val

                    # Update Max Drawdown one last time (Peak Close to Exit Price)
                    if (sym_hwm > 0 && iso > rl_entry_iso[sym]) {
                        current_dd = (sym_hwm - current_trade_val) / sym_hwm
                        if (current_dd > max_sym_dd) max_sym_dd = current_dd
                    }

                    debug_printf(sym, "\n[DD EXIT] Date: %s | Peak: %.2f | Exit Val: %.2f | DD: %.4f | Shares: %.2f", iso, sym_hwm, current_trade_val, current_dd, initial_shares_at_entry[sym])


                    trade_pnl = total_exit_proceeds[sym] - (initial_shares_at_entry[sym] * rl_entry_p[sym])
                    sys_total_pnl_pct += (trade_pnl / RL_CASH) * 100

                    if (RECORD_CLOSES) {
                    # 3. PORTFOLIO & STREAK TRACKING
                    p_exit_results[++p_trade_ptr] = trade_pnl
                    p_exit_dates[p_trade_ptr] = iso
                    
                    if (trade_pnl > 0) {
                          rl_wins++; s_50_wins++; rl_sum_wins += trade_pnl; cur_loss_streak = 0 
                    } else if (trade_pnl < 0) {
                          rl_losses++; s_50_losses++; rl_sum_losses += trade_pnl; cur_loss_streak++
                          if (cur_loss_streak > max_loss_streak) max_loss_streak = cur_loss_streak
                    } else {
                          rl_BEs++; s_50_BEs++; cur_loss_streak = 0
                    }

                    day_exit_equity_50 = (rl_inv * rl_sell) - RL_CASH 
                    trade_return = (trade_pnl / RL_CASH)
                    mae_pct = (rl_entry_p[sym] - rl_min_p) / rl_entry_p[sym]
                    hold_days = days_diff(rl_entry_iso[sym], iso) + 1
                    
                    if (hold_days > 0 && trade_return > -1) {
                          annualizedROR = ((1 + trade_return)^(DAYS_PER_YEAR / hold_days)) - 1
                    } else {
                          annualizedROR = 0
                    }
                    
                    sys_closed_trades++
                    all_hold_days[sys_closed_trades] = hold_days
                    
                    too_high_threshold = (sma50[dates[sym, rl_entry_idx[sym]-1]] > 0 ? (rl_entry_p[sym]-sma50[dates[sym, rl_entry_idx[sym]-1]])/sma50[dates[sym, rl_entry_idx[sym]-1]] : 0)
                    max_gain = (rl_max_p - rl_entry_p[sym])/rl_entry_p[sym]
                    sys_total_hold_days += hold_days

                    m10_to_close = (m10_days > 0) ? (hold_days - m10_days) : 0
                    m20_to_close = (m20_days > 0) ? (hold_days - m20_days) : 0
                    m30_to_close = (m30_days > 0) ? (hold_days - m30_days) : 0
                    m40_to_close = (m40_days > 0) ? (hold_days - m40_days) : 0
                    m50_to_close = (m50_days > 0) ? (hold_days - m50_days) : 0
                    m60_to_close = (m60_days > 0) ? (hold_days - m60_days) : 0

                    if (hold_days > 0) {
                        trade_ces = ((trade_pnl/RL_CASH)*100) / hold_days
                    } else {
                        trade_ces = ((trade_pnl/RL_CASH)*100)
                    }  

                    # RISK (% decline entry to original stop) and Reward/risk
                    risk_pct = (rl_entry_p[sym] > 0) ? (rl_entry_p[sym] - original_stop) / rl_entry_p[sym] : 0
                    reward_risk = 0
                    if (rl_entry_p[sym] > original_stop && rl_entry_p[sym] > 0)
                        reward_risk = (original_target - rl_entry_p[sym]) / (rl_entry_p[sym] - original_stop)

                    # EXIT TYPE: ensure we have a label (STOP_LOSS, TARGET, RL_EXIT_DAYS, FLUSH_EXIT, TRAIL_STOP, TRAIL_STOP2)
                    exit_type_out = (exit_type != "") ? exit_type : "UNKNOWN"

                    # 4. DATA LOGGING (RL_CLOSED LIST) — built incrementally to avoid format/arg mismatch
                    row = sym "," rl_entry_iso[sym] "," sprintf("%.2f", rl_entry_p[sym])
                    row = row "," sprintf("%.2f", entry_sma20[sym]+0) "," sprintf("%.2f", entry_sma30[sym]+0) "," sprintf("%.2f", entry_sma50[sym]+0) "," sprintf("%.2f", entry_sma100[sym]+0) "," sprintf("%.2f", entry_sma200[sym]+0)
                    row = row "," sprintf("%.2f", rl_close_to_high) "," sprintf("%.2f", rl_max_p) "," sprintf("%.2f", max_gain) "," sprintf("%.2f", rl_min_p) "," sprintf("%.2f", too_high_threshold)
                    row = row "," sprintf("%.4f", original_stop) "," sprintf("%.4f", rl_stop) "," sprintf("%.4f", original_target)
                    row = row "," sprintf("%.4f", risk_pct) "," sprintf("%.2f", reward_risk)
                    row = row "," iso "," hold_days "," sprintf("%.2f", rl_sell) "," sprintf("%.2f", (trade_pnl/RL_CASH)*100) "%" "," sprintf("%.4f", annualizedROR)
                    row = row "," exit_type_out "," sprintf("%.4f", mae_pct) "," sprintf("%.6f", max_sym_dd) "," "50-trigger"
                    row = row "," sprintf("%.4f", entry_peak_hi[sym]) "," sprintf("%.4f", entry_peak_cl[sym]) "," sprintf("%.4f", entry_peak_lo[sym])
                    row = row "," sprintf("%.4f", entry_atr_stop[sym]) "," sprintf("%.4f", entry_atr_val[sym]) "," sprintf("%.6f", entry_atr_val[sym]/rl_entry_p[sym])
                    row = row "," entry_exp_hits[sym] "," entry_prior_reset[sym] "," entry_last_exp[sym] "," entry_last_reset[sym]
                    row = row "," sprintf("%.4f", entry_slope[sym]) "," sprintf("%.2f", entry_spy_price[sym]+0) "," sprintf("%.2f", entry_spy20[sym]+0) "," sprintf("%.2f", entry_spy30[sym]+0)
                    row = row "," sprintf("%.2f", entry_spy50[sym]) "," sprintf("%.2f", entry_spy100[sym]) "," sprintf("%.2f", entry_spy200[sym])
                    row = row "," entry_active_shocks[sym] "," sprintf("%.4f", entry_last_shock_mag[sym]) "," entry_rehab_cooldown[sym]
                    row = row "," sprintf("%.2f", entry_close) "," sprintf("%.2f", raw_op[sym, iso])
                    row = row "," m10_days "," m20_days "," m30_days "," m40_days "," m50_days "," m60_days
                    row = row "," m10_to_close "," m20_to_close "," m30_to_close "," m40_to_close "," m50_to_close "," m60_to_close
                    row = row "," sprintf("%.6f", trade_ces) "," partial_exit_date[sym] "," sprintf("%.2f", partial_exit_amount[sym]) "," sprintf("%.2f", avg_exit_price) "," sprintf("%.0f", entry_avg_vol[sym]+0) "," sprintf("%.0f", entry_trigger_vol[sym]+0)
                    row = row "," entry_pivot_high[sym]+0 "," entry_pivot_low[sym]+0
                    row = row "," (entry_struct_high[sym] != "" ? entry_struct_high[sym] : "") "," (entry_struct_low[sym] != "" ? entry_struct_low[sym] : "")
                    row = row "," entry_major_ph[sym]+0 "," entry_major_pl[sym]+0
                    row = row "," (entry_pivot_high_pr[sym] != "" ? sprintf("%.4f", entry_pivot_high_pr[sym]+0) : "") "," (entry_pivot_low_pr[sym] != "" ? sprintf("%.4f", entry_pivot_low_pr[sym]+0) : "")
                    row = row "," (entry_last_ph_pr[sym] != "" ? sprintf("%.4f", entry_last_ph_pr[sym]+0) : "") "," (entry_last_pl_pr[sym] != "" ? sprintf("%.4f", entry_last_pl_pr[sym]+0) : "")
                    row = row "," (entry_prev_ph_pr[sym] != "" ? sprintf("%.4f", entry_prev_ph_pr[sym]+0) : "") "," (entry_prev_pl_pr[sym] != "" ? sprintf("%.4f", entry_prev_pl_pr[sym]+0) : "")
                    rl_closed_list[++rl_closed_ptr] = row
                    }
                    daily_realized_pnl[iso] += trade_pnl
                    # 5. CRITICAL STATE RESET (Zero out for next trade)
                    rl_pnl += trade_pnl
                    trl += trade_pnl
                    rl_inv = rl_max_p = rl_min_p = rl_trail_active = m10_days = m20_days = m30_days = m40_days = m50_days = m60_days = 0
                    has_hit_time_trigger[sym] = 0
                    time_trigger_counter[sym] = 0
                    has_hit_milestone[sym] = 0
                    total_exit_proceeds[sym] = 0
                    total_shares_sold[sym] = 0
                    
                    execute_exit = 0
                    exit_type = ""
                if (INSTRUMENT) T_MAIN50_MS += get_ms() - _t0
            }
            } else if (SMA_QUAL == 1 && j > SMA_PERIOD_50+RL_50_SMA_LOOKBACK) {
                        if (INSTRUMENT) _t0 = get_ms()
                        diag_dip_zone_enters++
                        sma50rising = sma50[dates[sym, j]] > sma50[dates[sym, j-RL_50_SMA_LOOKBACK]]
                        inthe50zone = (raw_lo[sym, iso] < (y_sma * RL_DIP_PCT) && (raw_lo[sym, iso] > y_sma * (1-(RL_DIP_PCT-1))))
                        uptick = raw_cl[sym, iso] > raw_op[sym, iso]
                        closeabove50sma = raw_cl[sym, iso] > y_sma
                        is200sma = sma200[y_iso] > 0
                        sma20over50 = sma20[iso] > sma50[iso]
                        sma50over100 = sma50[iso] > sma100[iso]
                        sma100over200 = sma100[iso] > sma200[iso]
                        # Watchlist: not yet full dip candle — price/SMA stack "close" to a possible 50 dip (last bar, flat).
                        if (j == d_ptr[sym] && rl_inv == 0) {
                            dip_gate = (sma50rising && inthe50zone && uptick && closeabove50sma && is200sma && sma20over50 && sma50over100 && sma100over200)
                            if (!dip_gate) {
                                wlo = 0
                                wmiss = ""
                                if (is200sma && sma20over50 && sma50over100 && sma100over200) wlo += 25
                                else wmiss = wmiss "STACK "
                                if (sma50rising) wlo += 15
                                zt = y_sma * RL_DIP_PCT
                                zb = y_sma * (1 - (RL_DIP_PCT - 1))
                                if (raw_lo[sym, iso] <= zt * 1.02 && raw_lo[sym, iso] >= zb * 0.98) wlo += 28
                                if (inthe50zone) wlo += 12
                                if (uptick) wlo += 8
                                if (closeabove50sma) wlo += 8
                                sub(/[[:space:]]+$/, "", wmiss)
                                record_watch_near(sym, iso, wlo, "NEAR_50_ZONE", wmiss, raw_cl[sym, iso] + 0, y_sma + 0)
                            }
                        }
                        if (sym == first_audit_sym && j == SMA_PERIOD_50+RL_50_SMA_LOOKBACK+1) {
                              printf "DIP_ZONE_SAMPLE j=%d iso=[%s] y_iso=[%s] y_sma=%.4f raw_lo=%.2f raw_op=%.2f raw_cl=%.2f\n", j, iso, y_iso, y_sma+0, raw_lo[sym, iso]+0, raw_op[sym, iso]+0, raw_cl[sym, iso]+0 >> DIAG_FILE
                              printf "DIP_ZONE_SAMPLE sma50rising=%d inthe50zone=%d uptick=%d closeabove50sma=%d is200sma=%d sma20over50=%d sma50over100=%d sma100over200=%d\n", sma50rising, inthe50zone, uptick, closeabove50sma, is200sma, sma20over50, sma50over100, sma100over200 >> DIAG_FILE
                              next_day_iso_val = dates[sym, j+1]; printf "DIP_ZONE_SAMPLE next_day_iso=[%s] raw_op_next=%.2f\n", next_day_iso_val, raw_op[sym, next_day_iso_val]+0 >> DIAG_FILE
                        }
                        # --- Initialize new trade tracking ---
                        has_hit_milestone[sym] = 0        # Tracks if PARTIAL_EXIT_TARGET was hit
                        has_hit_time_trigger[sym] = 0     # Tracks if RL_EXIT_PERCENT was hit
                        time_trigger_counter[sym] = 0     # Counts days AFTER reaching RL_EXIT_PERCENT
                        current_target[sym] = 0
                        
                        debug_printf(sym, "\n\nsym:%s\niso:%s\nsma50rising:%d\ninthe50zone:%d\nuptick:%d\nraw_cl[sym, iso]:%.2f\nraw_op[sym, iso]:%.2f\nraw_op[sym, dates[sym, j+1]]:%.2f\ncloseabove50sma:%d\nis200sma:%d\nsma20over50:%d\nsma50over100:%d\nsma100over200:%d\ncurrent_target[sym]:%.2f", sym, iso, sma50rising, inthe50zone, uptick, raw_cl[sym, iso], raw_op[sym, iso], raw_op[sym, dates[sym, j+1]], closeabove50sma, is200sma, sma20over50, sma50over100, sma100over200, current_target[sym])
                                                
                        if (sma50rising && inthe50zone && uptick && closeabove50sma && is200sma && (sma20over50 && sma50over100 && sma100over200 ))
                        {
                        diag_dip_inner_enters++

                        expansion = 0
                        if (INSTRUMENT) _t0 = get_ms()
                        for (k=0; k < EXPANSION_LOOKBACK_DAYS; k++) {
                              p_idx = j - k; if (p_idx < 2) continue
                              p_iso = dates[sym, p_idx]; prev_p_iso = dates[sym, p_idx-1]
                              if (sma50[prev_p_iso] > 0 && raw_cl[sym, p_iso] >= (sma50[prev_p_iso] * RL_EXPANSION)) { expansion = 1; break }
                        }
                        if (INSTRUMENT) T_EXPANSION_MS += get_ms() - _t0

                        # CUT THE LOSERS. no stock that didn't meet the 20% expansion from the SMA50 has ever made money. CUT THEM
                        cut_it = 0
                        if (cur_hi_pct < RL_CUT_THE_LOSERS)
                              cut_it = 1
                        

                        debug_printf(sym, "\nexpansion:%d\nacceptance:%d\nraw_lo[sym, iso]:%.2f", expansion, acceptance, raw_lo[sym, iso])

                        atr_volatility = atr_rolling/raw_op[sym,iso]
                        base_price = raw_op[sym,iso]
                        
                        atr_inclusion = 1
                        
                        # 1. Percent-based ATR Filter
                        if (atr_volatility > RL_ATR_HIGH_PERCENT || atr_volatility < RL_ATR_LOW_PERCENT) {
                              atr_inclusion = 0
                        }
                        # 2. Value-based ATR Filter
                        if (atr_rolling >= RL_ATR_HIGH_VALUE) {
                              atr_inclusion = 0
                        }
                        # 3. Minimum Price Filter
                        if (base_price < RL_LOW_PRICE) {
                              atr_inclusion = 0
                        }
                        
                        peak_inclusion = 0
                        if (peak_cl[sym] < PEAK_THRESHOLD_MAX)
                            peak_inclusion = 1

                        # Create a slope boolean
                        # --- SLOPE LOGIC ---
                        # If threshold is 0, we treat it as "Filter Off" (Always OK)
                        if (RL_SLOPE_THRESHOLD == 0) {
                              slope_ok = 1
                        } else {
                              # Your existing regression/slope calculation here...
                              slope_ok = (current_slope >= RL_SLOPE_THRESHOLD)
                        }

                        # We experienced two stocks that after trigger gapped down so low, we would never have bought it. this prevent's that scenario CVCO 20260130 SUBCY	20230315
                        # Safety check: Only look ahead if a next day exists
                        too_low = 0
                        if (j < d_ptr[sym]) {
                             next_op = raw_op[sym, dates[sym, j+1]]
                             if (next_op > 0 && next_op < (raw_lo[sym, iso] * RL_STOP_PCT)) {
                                 too_low = 1
                             }
                        }
                        
                        next_day_iso = dates[sym, j+1]
                        if (SPY_INCLUSION == 1)  
                        {   
                            spy_inclusion = 0
                            if (spy_sma50[next_day_iso] > spy_sma100[next_day_iso] && spy_sma100[next_day_iso] > spy_sma200[next_day_iso])
                                spy_inclusion = 1
                        }
                        debug_printf(sym, "\n\nSPY_INCLUSION:%d\nspy_inclusion:%d\nsym:%s\nexpansion:%d\nacceptance:%d\nnext_day_iso:%s\nraw_op[sym, next_day_iso]:%.2f\nraw_lo[sym, iso] * RL_TOO_HIGH:%.2f\nraw_lo[sym, iso]:%.2f\n(y_sma * RL_DIP_PCT):%.2f\n y_sma * (1-(RL_DIP_PCT-1)):%.2f\nisnottoohigh:%d", SPY_INCLUSION, spy_inclusion, sym, expansion, acceptance, next_day_iso, raw_op[sym, next_day_iso], raw_lo[sym, iso] * RL_TOO_HIGH, raw_lo[sym, iso], (y_sma * RL_DIP_PCT), y_sma * (1-(RL_DIP_PCT-1)), isnottoohigh)
                        # Troubleshooting: count how often each condition passes (when we are in dip-zone evaluation)
                        tr_expansion += expansion; tr_acceptance += acceptance; tr_cut_it += cut_it
                        tr_atr_inclusion += atr_inclusion; tr_spy_inclusion += spy_inclusion; tr_peak_inclusion += peak_inclusion
                        tr_slope_ok += slope_ok; tr_shock_qualified += shock_qualified; tr_too_low += too_low
                        # When SPY_INCLUSION=0 we ignore SPY state; when 1 we require spy_inclusion (50>100>200).
                        spy_ok = (SPY_INCLUSION == 0 || spy_inclusion)
                        if (expansion && acceptance && cut_it && atr_inclusion && spy_ok && peak_inclusion && slope_ok  && shock_qualified && !too_low && vol_ok) tr_all_conditions++

                        vol_ok = 1
                        if (AVG_VOL_DAYS > 0 && VOL_PCT_THRESHOLD > 0) {
                              entry_day_vol = raw_vol[sym, next_day_iso] + 0
                              vol_ok = (avg_vol > 0 && entry_day_vol >= avg_vol * (1 + VOL_PCT_THRESHOLD/100))
                        }
                        if (expansion && acceptance && cut_it && atr_inclusion && spy_ok && peak_inclusion && slope_ok  && shock_qualified && !too_low && vol_ok) {
                              # Next-session entry (same test as opening the RL position below)
                              entry_ok_next_open = 0
                              if (next_day_iso != "" && raw_op[sym, next_day_iso] > 0) {
                                  if ((RL_TOO_HIGH + 0) == 0 || raw_op[sym, next_day_iso] <= (raw_lo[sym, iso] * RL_TOO_HIGH * RL_STOP_PCT))
                                      entry_ok_next_open = 1
                              }
                              if (j == d_ptr[sym]) {
                                    pred_iso_scan = dates[sym, j - 1]
                                    scan_tgt = (pred_iso_scan != "" && sma50[pred_iso_scan] > 0) ? (sma50[pred_iso_scan] * RL_TARGET_PCT) : 0
                                    stop_lv_scan = raw_lo[sym, iso] * RL_STOP_PCT
                                    th_line_scan = stop_lv_scan * RL_TOO_HIGH
                                    nxop_scan = (next_day_iso != "" && raw_op[sym, next_day_iso] > 0) ? raw_op[sym, next_day_iso] : 0
                                    scanner_list[++scanner_ptr] = sprintf("%s,%s,%.2f,%s,%.2f,%.2f,%.2f,%.2f,%d", sym, iso, raw_cl[sym, iso], next_day_iso, nxop_scan, stop_lv_scan, th_line_scan, scan_tgt, entry_ok_next_open)
                              }
                              isnottoohigh = (next_day_iso != "" && raw_op[sym, next_day_iso] > 0 && raw_op[sym, next_day_iso] <= (raw_lo[sym, iso] * RL_TOO_HIGH * RL_STOP_PCT)) ? 1 : 0
                              debug_printf(sym, "\n\nsym:%s\nexpansion:%d\nacceptance:%d\nnext_day_iso:%s\nraw_op[sym, next_day_iso]:%.2f\nraw_lo[sym, iso] * RL_TOO_HIGH:%.2f\nraw_lo[sym, iso]:%.2f\n(y_sma * RL_DIP_PCT):%.2f\n y_sma * (1-(RL_DIP_PCT-1)):%.2f\nisnottoohigh:%d", sym, expansion, acceptance, next_day_iso, raw_op[sym, next_day_iso], raw_lo[sym, iso] * RL_TOO_HIGH, raw_lo[sym, iso], (y_sma * RL_DIP_PCT), y_sma * (1-(RL_DIP_PCT-1)), isnottoohigh)
                              if (entry_ok_next_open) {
                                    # --- THE SNAPSHOT: Freeze the history AT entry ---
                                    entry_exp_hits[sym] = exp_hits
                                    entry_last_exp[sym] = last_exp_iso
                                    entry_last_reset[sym] = last_reset_iso
                                    # Freeze the Prior Reset for the closed file
                                    entry_prior_reset[sym] = prior_reset_iso

                                    entry_peak_hi[sym] = peak_hi[sym]
                                    entry_peak_cl[sym] = peak_cl[sym]
                                    entry_peak_lo[sym] = peak_lo[sym]

                                    entry_avg_vol[sym] = (AVG_VOL_DAYS > 0) ? avg_vol : 0
                                    entry_trigger_vol[sym] = raw_vol[sym, iso] + 0
                                    rl_inv = RL_CASH / raw_op[sym, next_day_iso]; 
                                    initial_shares_at_entry[sym] = rl_inv # Capture the 100% count
                                    entry_atr_stop[sym] = raw_op[sym, next_day_iso] - (atr_rolling * 2)
                                    entry_atr_val[sym] = atr_rolling
                                    rl_stop = raw_lo[sym, iso] * RL_STOP_PCT; 
                                    rl_entry_iso[sym] = next_day_iso; 
                                    rl_entry_p[sym] = raw_op[sym, next_day_iso];
                                    rl_entry_idx[sym] = j+1; 
                                    rl_trail_active = 0
                                    entry_slope[sym] = current_slope
                                    # Rocket BRT: pivot context at entry (Level 1 + Level 2 reporting)
                                    entry_pivot_high[sym] = pivot_high[sym, next_day_iso] + 0
                                    entry_pivot_low[sym] = pivot_low[sym, next_day_iso] + 0
                                    entry_struct_high[sym] = (structure_high[sym, next_day_iso] != "") ? structure_high[sym, next_day_iso] : ""
                                    entry_struct_low[sym] = (structure_low[sym, next_day_iso] != "") ? structure_low[sym, next_day_iso] : ""
                                    entry_major_ph[sym] = major_pivot_high[sym, next_day_iso] + 0
                                    entry_major_pl[sym] = major_pivot_low[sym, next_day_iso] + 0
                                    entry_pivot_high_pr[sym] = (pivot_high_price[sym, next_day_iso] != "") ? pivot_high_price[sym, next_day_iso] + 0 : ""
                                    entry_pivot_low_pr[sym] = (pivot_low_price[sym, next_day_iso] != "") ? pivot_low_price[sym, next_day_iso] + 0 : ""
                                    entry_last_ph_pr[sym] = (last_pivot_high_price[sym, next_day_iso] != "") ? last_pivot_high_price[sym, next_day_iso] + 0 : ""
                                    entry_last_pl_pr[sym] = (last_pivot_low_price[sym, next_day_iso] != "") ? last_pivot_low_price[sym, next_day_iso] + 0 : ""
                                    entry_prev_ph_pr[sym] = (prev_pivot_high_price[sym, next_day_iso] != "") ? prev_pivot_high_price[sym, next_day_iso] + 0 : ""
                                    entry_prev_pl_pr[sym] = (prev_pivot_low_price[sym, next_day_iso] != "") ? prev_pivot_low_price[sym, next_day_iso] + 0 : ""
                                    entry_close = raw_cl[sym, iso]
                                    rl_close_to_high = 1 - ((raw_hi[sym, iso] - raw_cl[sym, iso]) / (raw_hi[sym, iso] - raw_lo[sym, iso]))
                                    original_target = sma50[dates[sym, j-1]] * RL_TARGET_PCT
                                    current_target[sym] = rl_entry_p[sym] * (1 + RL_EXIT_PERCENT)
                                    original_stop = rl_stop
                                    partial_exit_date[sym] = ""
                                    partial_exit_amount[sym] = 0
                                    max_sym_dd = 0; sym_hwm = 0;
                                    total_exit_proceeds[sym] = 0
                                    total_shares_sold[sym] = 0
                                    
                                    entry_spy_price[sym] = (spy_p[next_day_iso] > 0) ? spy_p[next_day_iso] : 0
                                    entry_spy20[sym] = spy_sma20[next_day_iso]
                                    entry_spy30[sym] = spy_sma30[next_day_iso]
                                    entry_spy50[sym] = spy_sma50[next_day_iso]
                                    entry_spy100[sym] = spy_sma100[next_day_iso]
                                    entry_spy200[sym] = spy_sma200[next_day_iso]
                                    entry_smas_set[sym] = 0
                                    
                                    entry_active_shocks[sym] = active_shocks
                                    # Record the move % of the most recent shock before this trade
                                    entry_last_shock_mag[sym] = last_shock_magnitude[sym]
                                    entry_rehab_cooldown[sym] = days_remaining_in_rehab
                                    
                                  # Count 50-triggers
                                  t50_cnt[sym]++
                                  tr_actually_opened++
                            }
                        max_sym_dd = 0; sym_hwm = 0;
                        }
                        # Watchlist: dip candle OK but one or more post-filters block a same-day "scanner" entry (last bar, flat).
                        if (j == d_ptr[sym] && rl_inv == 0) {
                            fullq2 = (expansion && acceptance && cut_it && atr_inclusion && spy_ok && peak_inclusion && slope_ok && shock_qualified && !too_low && vol_ok)
                            if (!fullq2) {
                                wli = 0
                                miss = ""
                                if (is200sma && sma20over50 && sma50over100 && sma100over200) wli += 20
                                else miss = miss "STACK "
                                if (sma50rising) wli += 12
                                if (inthe50zone) wli += 13
                                if (uptick) wli += 10
                                if (closeabove50sma) wli += 10
                                if (expansion) wli += 10
                                else miss = miss "EXP "
                                if (acceptance) wli += 5
                                else miss = miss "ACC "
                                if (cut_it) wli += 5
                                else miss = miss "CUT "
                                if (atr_inclusion) wli += 5
                                else miss = miss "ATR "
                                if (spy_ok) wli += 5
                                else miss = miss "SPY "
                                if (peak_inclusion) wli += 3
                                else miss = miss "PEAK "
                                if (slope_ok) wli += 3
                                else miss = miss "SLOPE "
                                if (shock_qualified) wli += 2
                                else miss = miss "SHOCK "
                                if (!too_low) wli += 1
                                else miss = miss "GAP "
                                if (vol_ok) wli += 4
                                else miss = miss "VOL "
                                sub(/[[:space:]]+$/, "", miss)
                                record_watch_near(sym, iso, wli, "PENDING_FILTERS", miss, raw_cl[sym, iso] + 0, y_sma + 0)
                            }
                        }
                  }
                        if (INSTRUMENT) T_DIPZONE_MS += get_ms() - _t0
            }

            # ---------------------------------------------------------
            # 100-DAY SYSTEM MANAGEMENT (Upgraded with Trail2 & Index Fix)
            # ---------------------------------------------------------
            if (rl100_inv > 0) {
                  if (rl100_max_p < raw_hi[sym, iso]) rl100_max_p = raw_hi[sym, iso]
                  if (rl100_min_p > raw_lo[sym, iso] || rl100_min_p == 0) rl100_min_p = raw_lo[sym, iso]
                  # Capture SMAs at entry (first bar in position) for RL100_Closed row
                  if (iso == rl100_entry_iso) {
                      entry100_sma20[sym] = (sma20[iso] > 0) ? sma20[iso] : 0
                      entry100_sma30[sym] = (sma30[iso] > 0) ? sma30[iso] : 0
                      entry100_sma50[sym] = (sma50[iso] > 0) ? sma50[iso] : 0
                      entry100_sma100[sym] = (sma100[iso] > 0) ? sma100[iso] : 0
                      entry100_sma200[sym] = (sma200[iso] > 0) ? sma200[iso] : 0
                  }
                  # Milestone tracking (days to first hit 10%, 20%, ... 60%)
                  curr_profit_pct_100_m = (raw_hi[sym, iso] - rl100_entry_p) / rl100_entry_p
                  hold_days_100_m = days_diff(rl100_entry_iso, iso) + 1
                  if (curr_profit_pct_100_m >= MILESTONE_10_PCT && m10_days_100[sym] == 0) m10_days_100[sym] = hold_days_100_m
                  if (curr_profit_pct_100_m >= MILESTONE_20_PCT && m20_days_100[sym] == 0) m20_days_100[sym] = hold_days_100_m
                  if (curr_profit_pct_100_m >= MILESTONE_30_PCT && m30_days_100[sym] == 0) m30_days_100[sym] = hold_days_100_m
                  if (curr_profit_pct_100_m >= MILESTONE_40_PCT && m40_days_100[sym] == 0) m40_days_100[sym] = hold_days_100_m
                  if (curr_profit_pct_100_m >= MILESTONE_50_PCT && m50_days_100[sym] == 0) m50_days_100[sym] = hold_days_100_m
                  if (curr_profit_pct_100_m >= MILESTONE_60_PCT && m60_days_100[sym] == 0) m60_days_100[sym] = hold_days_100_m

                # --- TRAIL 1 ACTIVATION (RL100_*) ---
                if (rl100_trail_active == 0 && raw_hi[sym, iso] >= (rl100_entry_p * (1 + RL100_TRAIL_PROFIT))) {
                    rl100_trail_active = 1
                    rl100_stop = rl100_entry_p * (1 + RL100_TRAIL_STOP)
                }

                # --- TRAIL 2 ACTIVATION (RL100_* same as 50-day) ---
                if (RL100_TRAIL_PROFIT2 > 0 && raw_hi[sym, iso] >= (rl100_entry_p * (1 + RL100_TRAIL_PROFIT2))) {
                    rl100_trail_active = 2
                    rl100_stop = rl100_entry_p * (1 + RL100_TRAIL_STOP2)
                }

                # --- EXIT LOGIC (RL100_*: timed exit, flush same as 50-day) ---
                execute_exit_100 = 0
                exit100_type = ""
                if (RL100_FLUSH_DAYS > 0 && flush_trigger[iso] == 1 && rl100_entry_iso != iso) {
                    execute_exit_100 = 1
                    exit100_type = "FLUSH_EXIT"
                }
                curr_profit_pct_100 = (raw_hi[sym, iso] - rl100_entry_p) / rl100_entry_p
                if (execute_exit_100 == 0 && has_hit_time_trigger_100[sym] == 0 && RL100_EXIT_PERCENT > 0 && curr_profit_pct_100 >= RL100_EXIT_PERCENT) {
                    has_hit_time_trigger_100[sym] = 1
                    time_trigger_counter_100[sym] = 0
                }
                if (has_hit_time_trigger_100[sym] == 1) time_trigger_counter_100[sym]++
                if (execute_exit_100 == 0 && has_hit_time_trigger_100[sym] == 1 && time_trigger_counter_100[sym] >= RL100_EXIT_DAYS) {
                    execute_exit_100 = 1
                    exit100_type = "TIMED_EXIT"
                    timed_exit_px_100 = rl100_entry_p * (1 + RL100_EXIT_PERCENT)
                }
                stop100_price = (iso == rl100_entry_iso) ? raw_cl[sym, iso] : raw_lo[sym, iso]
                if (execute_exit_100 == 0 && (stop100_price <= rl100_stop || raw_hi[sym, iso] >= rl100_target)) {
                    if (stop100_price <= rl100_stop) {
                        if (rl100_trail_active == 2) exit100_type = "TRAIL_STOP2"
                        else if (rl100_trail_active == 1) exit100_type = "TRAIL_STOP"
                        else exit100_type = "STOP_LOSS"
                    } else {
                        exit100_type = "TARGET"
                    }
                    execute_exit_100 = 1
                }
                if (execute_exit_100 == 1 && exit100_type != "") {
                    hold_days100 = days_diff(rl100_entry_iso, iso) + 1
                    rl100_sell = (exit100_type == "TIMED_EXIT" || exit100_type == "FLUSH_EXIT") ? (exit100_type == "TIMED_EXIT" ? timed_exit_px_100 : raw_op[sym, iso]) : ((stop100_price <= rl100_stop) ? rl100_stop : ((rl100_target > raw_op[sym, iso]) ? rl100_target : raw_op[sym, iso]))
                    pnl100 = (rl100_inv * rl100_sell) - (RL100_CASH + 0)
                    pnl_pct_100 = (hold_days100 > 0) ? ((rl100_sell - rl100_entry_p) / rl100_entry_p) * 100 : 0
                    trade_ces_100 = (hold_days100 > 0) ? (pnl_pct_100 / hold_days100) : pnl_pct_100
                    if (hold_days100 > 0 && pnl100 > -(RL100_CASH+0)) annualizedROR_100 = ((1 + (pnl100/(RL100_CASH+0)))^(DAYS_PER_YEAR / hold_days100)) - 1; else annualizedROR_100 = 0

                    if (pnl100 > 0) { rl100_wins++; s_100_wins++; rl100_sum_wins += pnl100 }
                    else if (pnl100 < 0) { rl100_losses++; s_100_losses++; rl100_sum_losses += pnl100 }
                    else { s_100_BEs++ }

                    sys_closed_trades++
                    all_hold_days[sys_closed_trades] = hold_days100
                    all_rors[sys_closed_trades] = ((1+(pnl100/(RL100_CASH+0)))^(DAYS_PER_YEAR/hold_days100))-1
                    sys_total_hold_days += hold_days100
                    daily_realized_pnl[iso] += pnl100

                    rl100_max_gain = (rl100_max_p - rl100_entry_p)/rl100_entry_p
                    orig_stop_100 = entry100_original_stop[sym] + 0; orig_tgt_100 = entry100_original_target[sym] + 0
                    close_to_high_100 = 0; denom100 = raw_hi[sym, iso] - raw_lo[sym, iso]; if (denom100 > 0) close_to_high_100 = 1 - ((raw_hi[sym, iso] - raw_cl[sym, iso]) / denom100)
                    too_high_100 = (entry100_sma100[sym] > 0) ? ((rl100_entry_p - entry100_sma100[sym]) / entry100_sma100[sym]) : 0
                    risk_pct_100 = (rl100_entry_p > 0) ? ((rl100_entry_p - orig_stop_100) / rl100_entry_p) : 0
                    reward_risk_100 = 0; if (rl100_entry_p > orig_stop_100 && rl100_entry_p > 0) reward_risk_100 = (orig_tgt_100 - rl100_entry_p) / (rl100_entry_p - orig_stop_100)
                    mae_pct_100 = (rl100_entry_p > 0 && rl100_min_p > 0) ? ((rl100_entry_p - rl100_min_p) / rl100_entry_p) : 0
                    max_dd_100 = mae_pct_100
                    m10_to_c_100 = (m10_days_100[sym] > 0) ? (hold_days100 - m10_days_100[sym]) : 0
                    m20_to_c_100 = (m20_days_100[sym] > 0) ? (hold_days100 - m20_days_100[sym]) : 0
                    m30_to_c_100 = (m30_days_100[sym] > 0) ? (hold_days100 - m30_days_100[sym]) : 0
                    m40_to_c_100 = (m40_days_100[sym] > 0) ? (hold_days100 - m40_days_100[sym]) : 0
                    m50_to_c_100 = (m50_days_100[sym] > 0) ? (hold_days100 - m50_days_100[sym]) : 0
                    m60_to_c_100 = (m60_days_100[sym] > 0) ? (hold_days100 - m60_days_100[sym]) : 0

                    row100 = sym "," rl100_entry_iso "," sprintf("%.2f", rl100_entry_p)
                    row100 = row100 "," sprintf("%.2f", entry100_sma20[sym]+0) "," sprintf("%.2f", entry100_sma30[sym]+0) "," sprintf("%.2f", entry100_sma50[sym]+0) "," sprintf("%.2f", entry100_sma100[sym]+0) "," sprintf("%.2f", entry100_sma200[sym]+0)
                    row100 = row100 "," sprintf("%.2f", close_to_high_100) "," sprintf("%.2f", rl100_max_p) "," sprintf("%.4f", rl100_max_gain) "," sprintf("%.2f", rl100_min_p) "," sprintf("%.4f", too_high_100)
                    row100 = row100 "," sprintf("%.4f", orig_stop_100) "," sprintf("%.4f", rl100_stop) "," sprintf("%.4f", orig_tgt_100)
                    row100 = row100 "," sprintf("%.4f", risk_pct_100) "," sprintf("%.2f", reward_risk_100)
                    row100 = row100 "," iso "," hold_days100 "," sprintf("%.2f", rl100_sell) "," sprintf("%.2f", pnl_pct_100) "%," sprintf("%.4f", annualizedROR_100) "," exit100_type "," sprintf("%.4f", mae_pct_100) "," sprintf("%.6f", max_dd_100) ",100-trigger"
                    row100 = row100 "," sprintf("%.4f", entry100_peak_hi[sym]+0) "," sprintf("%.4f", entry100_peak_cl[sym]+0) "," sprintf("%.4f", entry100_peak_lo[sym]+0)
                    row100 = row100 "," sprintf("%.4f", entry100_atr_stop[sym]+0) "," sprintf("%.4f", entry100_atr_val[sym]+0) "," sprintf("%.6f", entry100_atr_pct[sym]+0)
                    row100 = row100 ",0,0,0,0"
                    row100 = row100 "," sprintf("%.4f", entry_slope_100[sym]+0) ",0,0,0," sprintf("%.2f", entry100_spy50[sym]+0) "," sprintf("%.2f", entry100_spy100[sym]+0) "," sprintf("%.2f", entry100_spy200[sym]+0)
                    row100 = row100 ",0,0,0"
                    row100 = row100 "," sprintf("%.2f", entry100_close[sym]+0) "," sprintf("%.2f", raw_op[sym, iso]+0)
                    row100 = row100 "," (m10_days_100[sym]+0) "," (m20_days_100[sym]+0) "," (m30_days_100[sym]+0) "," (m40_days_100[sym]+0) "," (m50_days_100[sym]+0) "," (m60_days_100[sym]+0)
                    row100 = row100 "," m10_to_c_100 "," m20_to_c_100 "," m30_to_c_100 "," m40_to_c_100 "," m50_to_c_100 "," m60_to_c_100
                    row100 = row100 "," sprintf("%.6f", trade_ces_100) ",0,0," sprintf("%.2f", rl100_sell) "," sprintf("%.0f", entry100_avg_vol[sym]+0) "," sprintf("%.0f", entry100_trigger_vol[sym]+0)
                    row100 = row100 ",0,0,,,0,0,,,,,,"
                    RL100_closed_list[++RL100_closed_ptr] = row100

                    rl100_pnl += pnl100
                    trl100 += pnl100
                    rl100_inv = rl100_max_p = rl100_min_p = rl100_trail_active = 0
                }
            } else if (RL100_TOGGLE == 1 && j > SMA_PERIOD_100 + RL100_100_SMA_LOOKBACK) {
                if (INSTRUMENT) _t0 = get_ms()
                tr100_block_enters++
                # --- 100-DAY SMA ENTRY (same logic as 50-day: dip zone, expansion, acceptance, slope, too_high, cut_it, ATR, peak, shock, SPY, too_low, vol) ---
                sma100_rising = (sma100[iso] > sma100[dates[sym, j-RL100_100_SMA_LOOKBACK]])
                inthe100zone = (raw_lo[sym, iso] < (sma100[y_iso] * RL100_DIP_PCT) && raw_lo[sym, iso] > sma100[y_iso] * (1-(RL100_DIP_PCT-1)))
                uptick100 = raw_cl[sym, iso] > raw_op[sym, iso]
                closeabove100sma = raw_cl[sym, iso] > sma100[y_iso]
                is200sma_100 = sma200[y_iso] > 0
                stack_ok = (sma20[iso] > sma50[iso] && sma50[iso] > sma100[iso] && sma100[iso] > sma200[iso])

                exp100 = 0
                for (k=0; k < EXPANSION_LOOKBACK_DAYS; k++) {
                    p_idx100 = j - k; if (p_idx100 < 2) continue
                    p_iso100 = dates[sym, p_idx100]; prev_p_iso100 = dates[sym, p_idx100-1]
                    if (sma100[prev_p_iso100] > 0 && raw_cl[sym, p_iso100] >= (sma100[prev_p_iso100] * RL100_EXPANSION)) { exp100 = 1; break }
                }
                acc100 = (acc100_rolling_hits >= RL100_ACC_MIN) ? 1 : 0
                slope_ok_100 = (RL100_SLOPE_THRESHOLD == 0) ? 1 : (current_slope_100 >= RL100_SLOPE_THRESHOLD)
                cur_hi_pct_100 = (sma100[iso] > 0) ? ((raw_hi[sym, iso] - sma100[iso]) / sma100[iso]) : -999
                cut_it_100 = (cur_hi_pct_100 < RL100_CUT_THE_LOSERS) ? 1 : 0
                atr_volatility_100 = (raw_op[sym, iso] > 0) ? atr_rolling/raw_op[sym, iso] : 0
                atr_inclusion_100 = 1
                if (atr_volatility_100 > RL100_ATR_HIGH_PERCENT || atr_volatility_100 < RL100_ATR_LOW_PERCENT) atr_inclusion_100 = 0
                if (atr_rolling >= RL100_ATR_HIGH_VALUE) atr_inclusion_100 = 0
                if (raw_op[sym, iso] < RL100_LOW_PRICE) atr_inclusion_100 = 0
                peak_inclusion_100 = (peak_cl[sym] < PEAK_THRESHOLD_MAX) ? 1 : 0
                too_low_100 = 0
                if (j < d_ptr[sym]) {
                    next_op_100 = raw_op[sym, dates[sym, j+1]]
                    if (next_op_100 > 0 && next_op_100 < (raw_lo[sym, iso] * RL100_STOP_PCT)) too_low_100 = 1
                }
                spy_ok_100 = 1
                if (RL100_SPY_INCLUSION == 1) {
                    next_iso100 = dates[sym, j+1]
                    if (next_iso100 != "" && spy_sma50[next_iso100] > spy_sma100[next_iso100] && spy_sma100[next_iso100] > spy_sma200[next_iso100]) spy_ok_100 = 1; else spy_ok_100 = 0
                }
                vol100_ok = 1
                if (AVG_VOL_DAYS > 0 && VOL_PCT_THRESHOLD > 0) {
                    entry100_day_vol = raw_vol[sym, dates[sym, j+1]] + 0
                    vol100_ok = (avg_vol > 0 && entry100_day_vol >= avg_vol * (1 + VOL_PCT_THRESHOLD/100))
                }
                isnottoohigh_100 = (RL100_TOO_HIGH == 0) ? 1 : (raw_op[sym, dates[sym, j+1]] <= (raw_lo[sym, iso] * RL100_TOO_HIGH))

                # Troubleshooting: count how often each condition passes
                if (sma100_rising) tr100_sma100_rising++
                if (inthe100zone) tr100_inthe100zone++
                if (uptick100) tr100_uptick++
                if (closeabove100sma) tr100_closeabove++
                if (is200sma_100) tr100_is200++
                if (stack_ok) tr100_stack_ok++
                if (exp100) tr100_exp100++
                if (acc100) tr100_acc100++
                if (cut_it_100) tr100_cut_it++
                if (atr_inclusion_100) tr100_atr++
                if (spy_ok_100) tr100_spy++
                if (peak_inclusion_100) tr100_peak++
                if (slope_ok_100) tr100_slope++
                if (shock_qualified) tr100_shock++
                if (!too_low_100) tr100_too_low++
                if (vol100_ok) tr100_vol++

                # First-time sample: log one row so we can see RL100_TOGGLE and actual values (e.g. y_iso/sma100)
                if (RL100_troubleshoot_done == 0 && tr100_block_enters == 1) {
                    printf "100SMA_SAMPLE RL100_TOGGLE=%s j=%d iso=%s y_iso=%s sma100_y_iso=%.4f sma100_iso=%.4f raw_lo=%.2f raw_cl=%.2f raw_op=%.2f\n", RL100_TOGGLE+0, j, iso, y_iso, sma100[y_iso]+0, sma100[iso]+0, raw_lo[sym, iso]+0, raw_cl[sym, iso]+0, raw_op[sym, iso]+0 >> DIAG_FILE
                    printf "100SMA_SAMPLE sma100_rising=%d inthe100zone=%d uptick=%d closeabove=%d is200=%d stack_ok=%d exp100=%d acc100=%d cut_it=%d atr=%d spy=%d peak=%d slope=%d shock=%d too_low=%d vol=%d\n", sma100_rising+0, inthe100zone+0, uptick100+0, closeabove100sma+0, is200sma_100+0, stack_ok+0, exp100+0, acc100+0, cut_it_100+0, atr_inclusion_100+0, spy_ok_100+0, peak_inclusion_100+0, slope_ok_100+0, shock_qualified+0, too_low_100+0, vol100_ok+0 >> DIAG_FILE
                    printf "100SMA_SAMPLE dip_zone: raw_lo < sma100*RL100_DIP_PCT => %.2f < %.4f ? %d ; raw_lo > sma100*(1-(DIP-1)) => %.2f > %.4f ? %d\n", raw_lo[sym, iso]+0, sma100[y_iso]*RL100_DIP_PCT, (raw_lo[sym, iso] < (sma100[y_iso] * RL100_DIP_PCT))+0, raw_lo[sym, iso]+0, sma100[y_iso]*(1-(RL100_DIP_PCT-1)), (raw_lo[sym, iso] > sma100[y_iso] * (1-(RL100_DIP_PCT-1)))+0 >> DIAG_FILE
                    RL100_troubleshoot_done = 1
                }

                if (sma100_rising && inthe100zone && uptick100 && closeabove100sma && is200sma_100 && stack_ok && exp100 && acc100 && cut_it_100 && atr_inclusion_100 && spy_ok_100 && peak_inclusion_100 && slope_ok_100 && shock_qualified && !too_low_100 && vol100_ok) {
                    tr100_all_conditions++
                    next_iso100 = dates[sym, j+1]
                    if (next_iso100 != "" && raw_op[sym, next_iso100] > 0 && isnottoohigh_100) {
                        tr100_actually_opened++
                        entry100_avg_vol[sym] = (AVG_VOL_DAYS > 0) ? avg_vol : 0
                        entry100_trigger_vol[sym] = raw_vol[sym, iso] + 0
                        rl100_inv = (RL100_CASH + 0) / raw_op[sym, next_iso100]
                        rl100_stop = raw_lo[sym, iso] * RL100_STOP_PCT
                        rl100_target = sma100[iso] * RL100_TARGET_PCT
                        entry100_original_stop[sym] = rl100_stop
                        entry100_original_target[sym] = rl100_target
                        rl100_entry_iso = next_iso100
                        rl100_entry_p = raw_op[sym, next_iso100]
                        entry100_atr_stop[sym] = (atr_rolling > 0) ? (rl100_entry_p - 2 * atr_rolling) : 0
                        entry100_atr_val[sym] = atr_rolling + 0
                        entry100_atr_pct[sym] = (rl100_entry_p > 0 && atr_rolling > 0) ? (atr_rolling / rl100_entry_p) : 0
                        entry100_close[sym] = raw_cl[sym, iso] + 0
                        m10_days_100[sym] = 0; m20_days_100[sym] = 0; m30_days_100[sym] = 0
                        m40_days_100[sym] = 0; m50_days_100[sym] = 0; m60_days_100[sym] = 0
                        rl100_trail_active = 0
                        entry100_peak_hi[sym] = peak_hi[sym]
                        entry100_peak_cl[sym] = peak_cl[sym]
                        entry100_peak_lo[sym] = peak_lo[sym]
                        entry_slope_100[sym] = current_slope_100
                        has_hit_time_trigger_100[sym] = 0
                        time_trigger_counter_100[sym] = 0
                        t100_cnt[sym]++
                        entry100_spy50[sym] = spy_sma50[next_iso100]
                        entry100_spy100[sym] = spy_sma100[next_iso100]
                        entry100_spy200[sym] = spy_sma200[next_iso100]
                    }
                }
                if (INSTRUMENT) T_100DAY_MS += get_ms() - _t0
            }

            # ---------------------------------------------------------
            # DIVE BOMBER (Short-selling: inverse stack + "sell the rip")
            # ---------------------------------------------------------
            if (DB_TOGGLE == 1 && db_inv > 0) {
                if (INSTRUMENT) _t0 = get_ms()
                # Capture entry-day SMAs (like RL) on first bar in position
                if (iso == db_entry_iso[sym] && db_entry_smas_set[sym] == 0) {
                    db_entry_sma50[sym] = (sma50[iso] > 0) ? sma50[iso] : 0
                    db_entry_sma100[sym] = (sma100[iso] > 0) ? sma100[iso] : 0
                    db_entry_sma200[sym] = (sma200[iso] > 0) ? sma200[iso] : 0
                    db_entry_smas_set[sym] = 1
                }
                db_hold_days = days_diff(db_entry_iso[sym], iso) + 1
                db_exit_type = ""
                db_sell = 0
                # Continuously set target to DB_TARGET_PCT below 50-day SMA (mirror of RL: target 20% above 50)
                if (j > 1 && sma50[dates[sym, j-1]] > 0)
                    db_target = sma50[dates[sym, j-1]] * DB_TARGET_PCT
                # 1. Squeeze: price breaks above 20-day high -> exit immediately
                if (DB_SQUEEZE_EXIT > 0 && current_squeeze_high > 0 && raw_hi[sym, iso] >= current_squeeze_high) {
                    db_exit_type = "SQUEEZE"
                    db_sell = (raw_hi[sym, iso] > raw_op[sym, iso]) ? raw_hi[sym, iso] : raw_op[sym, iso]
                }
                # 2. Stop (price rises): raw_hi >= db_stop
                if (db_exit_type == "" && raw_hi[sym, iso] >= db_stop) {
                    db_exit_type = "STOP"
                    db_sell = (db_stop > raw_op[sym, iso]) ? db_stop : raw_op[sym, iso]
                }
                # 3. Target (price falls): raw_lo <= db_target
                if (db_exit_type == "" && raw_lo[sym, iso] <= db_target) {
                    db_exit_type = "TARGET"
                    db_sell = (db_target < raw_op[sym, iso]) ? db_target : raw_op[sym, iso]
                }
                # 4. Max hold days (time-based kill)
                if (db_exit_type == "" && db_hold_days >= DB_MAX_HOLD_DAYS) {
                    db_exit_type = "MAX_HOLD"
                    db_sell = raw_op[sym, iso]
                }
                if (db_exit_type != "") {
                    db_trade_pnl = (db_entry_p[sym] - db_sell) * db_inv
                    trdb += db_trade_pnl
                    db_pnl += db_trade_pnl
                    if (db_trade_pnl > 0) { db_wins++; db_sum_wins += db_trade_pnl }
                    else if (db_trade_pnl < 0) { db_losses++; db_sum_losses += db_trade_pnl }
                    else db_BEs++
                    # Per-symbol counts for DB_Summary (stock-by-stock report)
                    db_trades_s[sym]++; db_pnl_s[sym] += db_trade_pnl
                    if (db_trade_pnl > 0) db_wins_s[sym]++
                    else if (db_trade_pnl < 0) db_losses_s[sym]++
                    else db_BEs_s[sym]++
                    db_syms[sym] = 1
                    if (RECORD_CLOSES) {
                        db_total_hold_days += db_hold_days
                        db_total_pnl_pct += (db_trade_pnl / DB_CASH) * 100
                        db_trade_ptr++
                        all_db_hold_days[db_trade_ptr] = db_hold_days
                        db_trade_ces = (db_hold_days > 0) ? ((db_trade_pnl/DB_CASH)*100) / db_hold_days : (db_trade_pnl/DB_CASH)*100
                        all_db_trade_ces[db_trade_ptr] = db_trade_ces
                    }
                    db_pct_from_50 = (db_entry_sma50[sym] > 0) ? ((db_entry_p[sym] - db_entry_sma50[sym]) / db_entry_sma50[sym]) * 100 : 0
                    db_signal_pct_from_50 = (db_signal_sma50[sym] > 0) ? ((db_signal_hi[sym] - db_signal_sma50[sym]) / db_signal_sma50[sym]) * 100 : 0
                    db_pnl_pct_str = sprintf("%.2f", (db_trade_pnl/DB_CASH)*100) "%"
                    db_closed_list[++db_closed_ptr] = sprintf("%s,%s,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.4f,%.4f,%s,%d,%.2f,%s,%s,%.4f,%.4f", sym, db_entry_iso[sym], db_entry_p[sym]+0, db_entry_sma50[sym]+0, db_entry_sma100[sym]+0, db_entry_sma200[sym]+0, db_signal_hi[sym]+0, db_signal_sma50[sym]+0, db_pct_from_50, db_signal_pct_from_50, iso, db_hold_days, db_sell, db_pnl_pct_str, db_exit_type, db_entry_atr[sym]+0, db_entry_atr_pct[sym]+0)
                    db_inv = 0
                    db_entry_iso[sym] = ""
                    db_entry_idx = 0
                    db_entry_p[sym] = 0
                    db_entry_smas_set[sym] = 0
                    db_entry_atr[sym] = 0
                    db_entry_atr_pct[sym] = 0
                }
            } else if (DB_TOGGLE == 1 && db_inv == 0 && j > SMA_PERIOD_200 + DB_RIP_DAYS_MAX && sma50[iso] > 0 && sma100[iso] > 0 && sma200[iso] > 0) {
                if (INSTRUMENT) _t0 = get_ms()
                inverse_stack = (sma50[iso] < sma100[iso] && sma100[iso] < sma200[iso])
                if (DB_INVERSE_STRICT == 0) inverse_stack = (sma50[iso] < sma100[iso])
                db_slope_iso = dates[sym, j - DB_SLOPE_LOOKBACK]
                falling_50 = (db_slope_iso != "" && sma50[db_slope_iso] > 0 && sma50[iso] < sma50[db_slope_iso])
                rip_cl_old = raw_cl[sym, dates[sym, j - DB_RIP_DAYS_MAX]]
                rip_ok = (rip_cl_old > 0 && raw_cl[sym, iso] > rip_cl_old)
                touch_50 = (raw_hi[sym, iso] >= sma50[iso] * (1 - DB_RIP_TOUCH_TOL))
                next_day_iso_db = dates[sym, j + 1]
                gap_ok = 1
                if (next_day_iso_db != "" && raw_op[sym, next_day_iso_db] > 0 && DB_GAP_UP_MAX > 0)
                    gap_ok = (raw_op[sym, next_day_iso_db] <= sma50[iso] * DB_GAP_UP_MAX)
                # Inverse expansion: at least one day in lookback had close <= sma50(prev)*DB_EXPANSION (prior weakness)
                db_expansion = 0
                for (k = 0; k < EXPANSION_LOOKBACK_DAYS; k++) {
                    p_idx_db = j - k; if (p_idx_db < 2) continue
                    p_iso_db = dates[sym, p_idx_db]; prev_p_iso_db = dates[sym, p_idx_db - 1]
                    if (sma50[prev_p_iso_db] > 0 && raw_cl[sym, p_iso_db] <= (sma50[prev_p_iso_db] * DB_EXPANSION)) { db_expansion = 1; break }
                }
                # Inverse peak: don't short if price has already collapsed too far below 50 (like RL peak_cl cap)
                inverse_peak_ok = (db_peak_trough[sym] > DB_PEAK_TROUGH_MAX)
                # Signal-day candle must be red (close < open), mirror of RL green candle
                db_red_candle = (raw_op[sym, iso] > 0 && raw_cl[sym, iso] < raw_op[sym, iso])
                # Set pending signal; actual entry happens next bar when we verify entry-day open vs entry-day SMA50
                if (inverse_stack && falling_50 && rip_ok && touch_50 && db_expansion && db_acceptance && next_day_iso_db != "" && raw_op[sym, next_day_iso_db] > 0 && gap_ok && inverse_peak_ok && db_red_candle) {
                    db_pending_signal[sym] = 1
                    db_pending_entry_iso[sym] = next_day_iso_db
                    db_pending_signal_hi[sym] = raw_hi[sym, iso]
                    db_pending_signal_sma50[sym] = sma50[iso]
                    db_pending_signal_sma100[sym] = sma100[iso]
                    db_pending_signal_sma200[sym] = sma200[iso]
                }
                if (INSTRUMENT) T_DB_MS += get_ms() - _t0
            }

            # --- BULLPROOF DRAWDOWN TRACKING ---
            if (INSTRUMENT) _t0 = get_ms()
            if (rl_inv > 0) {
                # Use the Daily Close
                current_trade_val = (rl_inv * raw_cl[sym, iso])
            
                # 2. Track Trade-Specific High Water Mark
                if (current_trade_val > sym_hwm) sym_hwm = current_trade_val

                # 3. Calculate Drawdown strictly on the Day AFTER entry
                if (sym_hwm > 0 && iso > rl_entry_iso[sym]) {

                # Capture the dollar value of the open position for portfolio tracking
                if (rl_inv > 0) {
                    daily_unrealized_equity[iso] += (rl_inv * raw_cl[sym, iso] - RL_CASH)
                }

                # (Highest Trade Value - Current Trade Value) / Highest Trade Value
                current_dd = (sym_hwm - current_trade_val) / sym_hwm
                
                if (current_dd > max_sym_dd) {
                    max_sym_dd = current_dd
                    debug_printf(sym, "\n[DD HIT] Date: %s | Peak Val: %.2f | Curr Val: %.2f | DD: %.4f", iso, sym_hwm, current_trade_val, current_dd)
                }
            }
            if (INSTRUMENT) T_DRAWDOWN_MS += get_ms() - _t0
            # Clean up for next day
            day_exit_equity_50 = ""
            all_trading_dates[iso] = 1
        }
      }

      # Persistence Pass: Store final value for END block
      _open_val = 0
      if (rl_inv > 0) {
            last_cl = raw_cl[sym, dates[sym, d_ptr[sym]]]
            _open_val = (rl_inv * last_cl) - RL_CASH
            distance_covered_to_target = (last_cl-rl_entry_p[sym])/(rl_target-rl_entry_p[sym])
            
            if (_open_val > 0) { rl_open_wins++; rl_val_open_wins += _open_val }
            else { rl_open_losses++; rl_val_open_losses += _open_val }
            rl_open_list[++rl_open_ptr] = sprintf("%s,%s,%.2f,%.2f,%.2f%%,%d,50-trigger,%.2f,%.2f,%.4f,%.0f,%s,%s", sym, rl_entry_iso[sym], rl_entry_p[sym], last_cl, (_open_val/RL_CASH)*100, (d_ptr[sym] - rl_entry_idx[sym]), rl_stop, rl_target, distance_covered_to_target, entry_hist_hits[sym], entry_hist_exp[sym], entry_hist_reset[sym])
      }
      # Persistence for 100-day Open trades
      if (rl100_inv > 0) {
            last_cl100 = raw_cl[sym, dates[sym, d_ptr[sym]]]
            pnl100_open = (rl100_inv * last_cl100) - RL_CASH
            rl_open_list[++rl_open_ptr] = sprintf("%s,%s,%.2f,%.2f,%.2f%%,%d,50-trigger,%.2f,%.2f,%d,%s,%s", sym, rl_entry_iso[sym], rl_entry_p[sym], last_cl, (_open_val/RL_CASH)*100, (d_ptr[sym] - rl_entry_idx[sym]), rl_stop, rl_target, entry_hist_hits[sym], entry_hist_exp[sym], entry_hist_reset[sym]) 
            _open_val += pnl100_open
      }
      # Persistence for Dive Bomber Open trades
      if (db_inv > 0 && db_entry_iso[sym] != "") {
            last_cl_db = raw_cl[sym, dates[sym, d_ptr[sym]]]
            db_open_pnl = (db_entry_p[sym] - last_cl_db) * db_inv
            db_open_list[++db_open_ptr] = sprintf("%s,%s,%.2f,%.2f,%.2f%%,%d,Dive-Bomber,%.2f,%.2f", sym, db_entry_iso[sym], db_entry_p[sym]+0, last_cl_db, (db_open_pnl/DB_CASH)*100, (d_ptr[sym] - db_entry_idx), db_stop, db_target)
      }

      # SUCCESS: rocket_pnl now captures both closed and floating profit
      rocket_pnl[sym] = rl_pnl + rl100_pnl + _open_val + db_pnl
      
      final_50_w[sym] = s_50_wins; final_50_l[sym] = s_50_losses; final_50_b[sym] = s_50_BEs
      final_100_w[sym] = s_100_wins; final_100_l[sym] = s_100_losses; final_100_b[sym] = s_100_BEs

      # Memory Release Pass: skip when RL_FLUSH_DAYS > 0 (two-pass) so pass 2 still has symbol data
      if (RL_FLUSH_DAYS == 0) {
            mem_count = 0
            for (k=1; k <= d_ptr[sym]; k++) {
                  _d = dates[sym, k]
                  if ((sym SUBSEP _d) in raw_op) mem_count++
                  delete raw_op[sym, _d]; delete raw_hi[sym, _d]; delete raw_lo[sym, _d]; delete raw_cl[sym, _d]; delete raw_vol[sym, _d]
                  delete raw_sma[sym, _d]
                  delete sma20[_d]; delete sma30[_d]; delete sma50[_d]; delete sma100[_d]; delete sma200[_d]; delete hist_rs[sym, _d]
                  delete seen[sym, _d]
                  # Free Rocket BRT structure arrays to prevent grow_table OOM (each symbol accumulated ~7 arrays x dates)
                  delete structure_high[sym, _d]; delete structure_low[sym, _d]
                  delete major_pivot_high[sym, _d]; delete major_pivot_low[sym, _d]
                  delete last_pivot_high_price[sym, _d]; delete prev_pivot_high_price[sym, _d]; delete prev_pivot_low_price[sym, _d]
                  delete dates[sym, k]
            }
            # One line per symbol (was missing \n and produced a multi-MB single line + slow I/O with -Instrument).
            if (INSTRUMENT) printf "Memory_Release sym=%s slots=%d\n", sym, mem_count >> INST_FILE
            # Do NOT call trim_working_set() here: it spawns PowerShell and touches every process; once per symbol = 1000+ runs and 5–10 min extra
      }
}

# --- REVISED TICKER RESET LOGIC ---
{
    # Handle Consolidated 'One File' Mode
    if (ONE_FILE == "Y" && $1 == "NEW_TICKER") {
        # Perform audit on previous symbol before resetting if valid
        if (cur_s != "" && cur_s != "NEW_TICKER" && RL_FLUSH_DAYS == 0) {
            perform_audit(cur_s); 
        }
        
        current_symbol = $2;
        cur_s = current_symbol;
        if (INSTRUMENT) S_START = get_ms();
        reset_ticker_variables();
        next; # Skip the marker line 
    }

    # Support Standard File-by-File Mode
    # On each new file's first row: finish the *previous* symbol (Scout/Audit + perform_audit).
    # We set prev_file = FILENAME at the end of this block, so the generic "FILENAME != prev_file"
    # rule below never fires; instrumentation must live here, not only in that block.
    if (ONE_FILE != "Y" && FNR == 1) {
        if (prev_file != "" && cur_s != "") {
            if (INSTRUMENT) {
                t_scout_done = get_ms()
                s_elapsed = (t_scout_done - S_START) / 1000
                printf "Scout [%s] %d days in %.3fs\n", cur_s, d_ptr[cur_s], s_elapsed >> INST_FILE
                if (prev_file ~ /SPY\.csv/) T_SPY_END = t_scout_done
            }
            if (RL_FLUSH_DAYS == 0) {
                if (INSTRUMENT) T_AUDIT_START = get_ms()
                perform_audit(cur_s)
                if (INSTRUMENT) {
                    t_audit_elapsed = (get_ms() - T_AUDIT_START) / 1000
                    printf "Audit [%s] %.3fs\n", cur_s, t_audit_elapsed >> INST_FILE
                }
            }
        }

        current_symbol = FILENAME;
        gsub(/.*\//, "", current_symbol); # Strip path 
        gsub(/.*\\/, "", current_symbol); # Strip Windows path 
        gsub(/\.[Cc][Ss][Vv]/, "", current_symbol); # Strip extension 

        cur_s = toupper(current_symbol);
        if (INSTRUMENT) S_START = get_ms();
        prev_file = FILENAME;
        if (FILENAME !~ /SPY\.csv|look\.csv/) all_syms[++all_syms_count] = cur_s;
        reset_ticker_variables();
    }
}

FILENAME ~ /SPY\.csv/ { 
    if (FNR < 4) next; 
    if (INSTRUMENT && FNR == 4) T_SPY_START = get_ms()
    iso = to_iso($1); 
    p = clean($5); 
    spy_p[iso] = p; 
    spy_rec_cnt++; 
    spy_idx[iso] = spy_rec_cnt; 
    spy_s[spy_rec_cnt] = iso;
    
    # Calculate Rolling SPY SMAs
    sp20 += p; if (spy_rec_cnt > SMA_PERIOD_20) sp20 -= spy_p[spy_s[spy_rec_cnt-SMA_PERIOD_20]];
    if (spy_rec_cnt >= SMA_PERIOD_20) spy_sma20[iso] = sp20 / SMA_PERIOD_20;
    
    sp30 += p; if (spy_rec_cnt > SMA_PERIOD_30) sp30 -= spy_p[spy_s[spy_rec_cnt-SMA_PERIOD_30]];
    if (spy_rec_cnt >= SMA_PERIOD_30) spy_sma30[iso] = sp30 / SMA_PERIOD_30;
    
    sp50 += p; if (spy_rec_cnt > SMA_PERIOD_50) sp50 -= spy_p[spy_s[spy_rec_cnt-SMA_PERIOD_50]];
    if (spy_rec_cnt >= SMA_PERIOD_50) spy_sma50[iso] = sp50 / SMA_PERIOD_50;
    
    sp100 += p; if (spy_rec_cnt > SMA_PERIOD_100) sp100 -= spy_p[spy_s[spy_rec_cnt-SMA_PERIOD_100]];
    if (spy_rec_cnt >= SMA_PERIOD_100) spy_sma100[iso] = sp100 / SMA_PERIOD_100;
    
    sp200 += p; if (spy_rec_cnt > SMA_PERIOD_200) sp200 -= spy_p[spy_s[spy_rec_cnt-SMA_PERIOD_200]];
    if (spy_rec_cnt >= SMA_PERIOD_200) spy_sma200[iso] = sp200 / SMA_PERIOD_200;
    
    next 
}

{
      if (FILENAME ~ /SPY\.csv|look\.csv/) {
        next
    }
      # Normally never true: FNR==1 block sets prev_file=FILENAME before this rule runs.
      # Scout/Audit for file-by-file mode are emitted there. Kept as fallback if that sync changes.
      if (FILENAME != prev_file) {  
        
        # 1. IDENTIFY NEW SYMBOL FIRST
        fn = toupper(FILENAME); sub(/.*\//, "", fn); sub(/.*\\/, "", fn); sub(/\.CSV$/, "", fn)
        r1 = toupper($1)
        new_ticker = fn

        # 2. LOG PREVIOUS SYMBOL ONLY IF VALID
        if (prev_file != "" && cur_s != "") {
            if (INSTRUMENT) {
                t_scout_done = get_ms()
                s_elapsed = (t_scout_done - S_START) / 1000
                printf "Scout [%s] %d days in %.3fs\n", cur_s, d_ptr[cur_s], s_elapsed >> INST_FILE
                if (prev_file ~ /SPY\.csv/) T_SPY_END = t_scout_done
            }
            if (RL_FLUSH_DAYS == 0) {
                if (INSTRUMENT) T_AUDIT_START = get_ms()
                perform_audit(cur_s)
                if (INSTRUMENT) {
                    t_audit_elapsed = (get_ms() - T_AUDIT_START) / 1000
                    printf "Audit [%s] %.3fs\n", cur_s, t_audit_elapsed >> INST_FILE
                }
            }
        }
        
        # 3. SETUP NEW SYMBOL
        if (INSTRUMENT) S_START = get_ms()
        prev_file = FILENAME
        cur_s = new_ticker
        all_syms[++all_syms_count] = new_ticker
    }
      # Technical Fix: Added price numeric check to skip non-standard headers (BYD crash fix)
      if (cur_s == "" || $1 == "" || $1 ~ /[a-zA-Z]/ || clean($2) == 0) next
      iso = to_iso($1);  
      op = clean($2);  
      hi = clean($3);  
      lo = clean($4);  
      cl = clean($5);  
      raw_op[cur_s, iso] = op;  
      raw_hi[cur_s, iso] = hi;  
      raw_lo[cur_s, iso] = lo;  
      raw_cl[cur_s, iso] = cl;
      if (NF >= 7) raw_vol[cur_s, iso] = clean($7) + 0
      # Precomputed SMAs from Python (columns 8-12) - packed to save memory
      if (NF >= 12) raw_sma[cur_s, iso] = ($8+0) "|" ($9+0) "|" ($10+0) "|" ($11+0) "|" ($12+0)
      scout_rec_cnt++
      # No-op when History not supplied (en_iso empty); kept for possible future use.
      # No-op when History not supplied (en_iso empty); kept for possible future use.
      for (id in en_iso)  
      {  
            if (t_to_s[id] == cur_s && en_iso[id] == iso)  
                  term_anchor[id] = cl  
      }
      if (!seen[cur_s, iso]++) {
            dates[cur_s, ++d_ptr[cur_s]] = iso
            if (diag_csv_sample_done < 2 && d_ptr[cur_s] == 1) {
                  printf "CSV_FIRST_ROW sym=%s raw_date=[%s] len_raw=%d iso=[%s] len_iso=%d raw_op_lookup=%.2f\n", cur_s, $1, length($1), iso, length(iso), raw_op[cur_s, iso]+0 >> DIAG_FILE
                  diag_csv_sample_done++
            }
      }
      # iso_idx omitted to save memory (was never read; ~1 array per symbol×date)
}

END {
    if (INSTRUMENT) T_END_START = get_ms()
    if (RL_FLUSH_DAYS == 0) {
        if (cur_s != "") {
            if (INSTRUMENT) T_AUDIT_START = get_ms()
            perform_audit(cur_s)
            if (INSTRUMENT) printf "Audit [%s] %.3fs (final)\n", cur_s, (get_ms() - T_AUDIT_START) / 1000 >> INST_FILE
        }
    } else {
        # Two-pass when RL_FLUSH_DAYS > 0: pass 1 builds equity curve and flush_trigger, pass 2 records closes with FLUSH_EXIT
        RECORD_CLOSES = 0
        if (INSTRUMENT) T_PASS1_START = get_ms()
        for (i = 1; i <= all_syms_count; i++) {
            current_symbol = all_syms[i]
            reset_ticker_variables()
            perform_audit(all_syms[i])
        }
        if (INSTRUMENT) printf "Pass1 (flush curve): %.3fs\n", (get_ms() - T_PASS1_START) / 1000 >> INST_FILE
        # Compute underwater days and flush_trigger from pass 1 equity curve (flush_hwm only; port_hwm stays for drawdown later)
        k_dates = asorti(all_trading_dates, sorted_dates)
        m_realized = 0
        flush_hwm = 0
        consecutive_underwater = 0
        initial_account_size = RL_CASH * ACCOUNT_SIZE_MULTIPLIER
        for (idx = 1; idx <= k_dates; idx++) {
            d_iso = sorted_dates[idx]
            m_realized += daily_realized_pnl[d_iso]
            port_equity = initial_account_size + m_realized + daily_unrealized_equity[d_iso]
            if (port_equity > flush_hwm) {
                flush_hwm = port_equity
                consecutive_underwater = 0
                flush_trigger[d_iso] = 0
            } else if (flush_hwm > 0 && port_equity < flush_hwm) {
                consecutive_underwater++
                flush_trigger[d_iso] = (consecutive_underwater >= RL_FLUSH_DAYS) ? 1 : 0
                # On flush day: reset underwater count and set new flush HWM to post-flush equity (new mountain, not re-climbing)
                if (flush_trigger[d_iso] == 1) {
                    consecutive_underwater = 0
                    flush_hwm = port_equity
                }
            } else {
                consecutive_underwater = 0
                flush_trigger[d_iso] = 0
            }
        }
        # Pass 2: reset and re-run with RECORD_CLOSES=1 so FLUSH_EXIT and all closes are recorded
        rl_closed_ptr = 0
        rl_open_ptr = 0
        rl_open_wins = 0
        rl_open_losses = 0
        rl_val_open_wins = 0
        rl_val_open_losses = 0
        db_closed_ptr = 0
        db_open_ptr = 0
        db_sum_wins = 0
        db_sum_losses = 0
        db_trade_ptr = 0
        db_total_hold_days = 0
        db_total_pnl_pct = 0
        delete all_db_hold_days
        delete all_db_trade_ces
        scanner_ptr = 0
        delete watch_best_sc
        delete watch_best_ln
        p_trade_ptr = 0
        rl_wins = 0
        rl_losses = 0
        rl_BEs = 0
        rl_sum_wins = 0
        rl_sum_losses = 0
        s_50_wins = 0
        s_50_losses = 0
        s_50_BEs = 0
        sys_closed_trades = 0
        sys_total_hold_days = 0
        sys_total_pnl_pct = 0
        cur_loss_streak = 0
        max_loss_streak = 0
        trl = 0
        rl_pnl = 0
        delete daily_realized_pnl
        delete daily_unrealized_equity
        delete daily_pos_count
        RECORD_CLOSES = 1
        if (INSTRUMENT) T_PASS2_START = get_ms()
        for (i = 1; i <= all_syms_count; i++) {
            current_symbol = all_syms[i]
            reset_ticker_variables()
            perform_audit(all_syms[i])
        }
        if (INSTRUMENT) printf "Pass2 (record closes): %.3fs\n", (get_ms() - T_PASS2_START) / 1000 >> INST_FILE
        # Release all symbol data after two-pass so we don't hold 1013 symbols' data for the rest of END
        if (INSTRUMENT) T_MEM_RELEASE_START = get_ms()
        for (i = 1; i <= all_syms_count; i++) {
            sym = all_syms[i]
            for (k = 1; k <= d_ptr[sym]; k++) {
                  _d = dates[sym, k]
                  delete raw_op[sym, _d]; delete raw_hi[sym, _d]; delete raw_lo[sym, _d]; delete raw_cl[sym, _d]; delete raw_vol[sym, _d]
                  delete raw_sma[sym, _d]
                  delete sma20[_d]; delete sma30[_d]; delete sma50[_d]; delete sma100[_d]; delete sma200[_d]; delete hist_rs[sym, _d]
                  delete seen[sym, _d]; delete dates[sym, k]
                  delete structure_high[sym, _d]; delete structure_low[sym, _d]
                  delete major_pivot_high[sym, _d]; delete major_pivot_low[sym, _d]
                  delete last_pivot_high_price[sym, _d]; delete prev_pivot_high_price[sym, _d]; delete prev_pivot_low_price[sym, _d]
            }
        }
        if (SKIP_TRIM != 1) trim_working_set()
        if (INSTRUMENT) printf "Memory release + trim_working_set: %.3fs\n", (get_ms() - T_MEM_RELEASE_START) / 1000 >> INST_FILE
    }

    # --- OPTIMIZATION 2.0 METRICS ---
    if (INSTRUMENT) T_METRICS_START = get_ms()
    p90_days = 0
    avg_ces = 0
    median_ces = 0
    debug_printf(DEBUG_SYM, "\nsys_total_pnl_pct:%.4f\nsys_total_hold_days:%d", sys_total_pnl_pct, sys_total_hold_days)
      if (sys_closed_trades > 0) {
          # 1. System Velocity (Average Daily PnL% across all trade-days)
          # Formula: Total PnL% Generated / Total Capital-Days Utilized
          if (sys_total_hold_days > 0) {
              avg_ces = sys_total_pnl_pct / sys_total_hold_days
          }

          # 2. Median CES (Consistency Check)
          asort(all_trade_ces) 
          if (sys_closed_trades % 2 == 1) {
              median_ces = all_trade_ces[int(sys_closed_trades / 2) + 1]
          } else {
              m1 = all_trade_ces[sys_closed_trades / 2]
              m2 = all_trade_ces[(sys_closed_trades / 2) + 1]
              median_ces = (m1 + m2) / 2
          }

          # 3. Time Risk (90th Percentile)
          asort(all_hold_days)
          p90_idx = int(sys_closed_trades * PERCENTILE_90)
          if (p90_idx < 1) p90_idx = 1
          p90_days = all_hold_days[p90_idx]
      }

      # CHRONOLOGICAL PORTFOLIO STREAK
      # Aligning all trade exits into a single timeline for the account
      for (i = 1; i <= p_trade_ptr; i++) {
          for (k = i + 1; k <= p_trade_ptr; k++) {
              if (p_exit_dates[i] > p_exit_dates[k]) {
                  tmp_d = p_exit_dates[i]; p_exit_dates[i] = p_exit_dates[k]; p_exit_dates[k] = tmp_d
                  tmp_r = p_exit_results[i]; p_exit_results[i] = p_exit_results[k]; p_exit_results[k] = tmp_r
              }
          }
      }
      
      # --- POSITION COUNT METRICS ---
      max_pos = 0
      total_pos_sum = 0
      pos_days_count = 0
      delete pos_array # For median calculation

      for (idx=1; idx<=k_dates; idx++) {
          d_iso = sorted_dates[idx]
          count = daily_pos_count[d_iso] + 0 # Force numeric
          
          if (count > max_pos) max_pos = count
          
          total_pos_sum += count
          pos_days_count++
          pos_array[pos_days_count] = count
      }

      avg_pos = (pos_days_count > 0) ? total_pos_sum / pos_days_count : 0
      
      # Median Position Calculation
      asort(pos_array)
      if (pos_days_count == 0) {
          median_pos = 0
      } else if (pos_days_count % 2 == 1) {
          median_pos = pos_array[int(pos_days_count / 2) + 1]
      } else {
          m1 = pos_array[pos_days_count / 2]
          m2 = pos_array[(pos_days_count / 2) + 1]
          median_pos = (m1 + m2) / 2
      }
      
      # NEW: Portfolio-Level Losing Streak
      p_cur_streak = 0
      p_max_streak = 0
      
      # We iterate through every trade closed in the entire system 
      # in the order they were processed/closed
      for (i = 1; i <= p_trade_ptr; i++) {
          if (p_exit_results[i] < 0) {
              p_cur_streak++
              if (p_cur_streak > p_max_streak) p_max_streak = p_cur_streak
          } else if (p_exit_results[i] > 0) {
              p_cur_streak = 0 # Any win resets the portfolio "pain"
          }
          # Note: BEs (0) are ignored, meaning the streak continues
      }

      
      # 2. CALCULATE PORTFOLIO DRAWDOWN + TIME UNDERWATER
      m_realized = 0; port_hwm = 0; max_port_dd = 0
      days_underwater = 0; consec_underwater = 0; max_consecutive_underwater = 0
      initial_account_size = RL_CASH * ACCOUNT_SIZE_MULTIPLIER 

      k_dates = asorti(all_trading_dates, sorted_dates)
      
      # --- CALCULATE PORTFOLIO DRAWDOWN & TIME UNDERWATER ---
      for (idx=1; idx<=k_dates; idx++) {
        d_iso = sorted_dates[idx]                    
    
        # 1. Bank the closed PnL
        m_realized += daily_realized_pnl[d_iso]      
    
        # 2. Add the "Paper" gains/losses from open positions today
        # 3. port_equity = Initial + Realized + Floating
        port_equity = initial_account_size + m_realized + daily_unrealized_equity[d_iso] 
    
        # 4. Standard HWM and Drawdown math
        if (port_equity > port_hwm) {        
            port_hwm = port_equity
            consec_underwater = 0
        }
    
        if (port_hwm > 0 && port_equity < port_hwm) { 
            p_dd = (port_hwm - port_equity) / port_hwm 
            if (p_dd > max_port_dd) max_port_dd = p_dd
            days_underwater++
            consec_underwater++
            if (consec_underwater > max_consecutive_underwater) max_consecutive_underwater = consec_underwater
        }
    }
      pct_time_underwater = (k_dates > 0) ? (days_underwater / k_dates) : 0

      # 3. RESTORE PERFORMANCE RATIOS & OPEN TRADE AVERAGES
      total_trades = rl_wins + rl_losses
      percent_wins = (total_trades > 0 ? rl_wins / total_trades : 0)
      percent_losses = (total_trades > 0 ? rl_losses / total_trades : 0)
      
      avg_win_amount = (rl_wins > 0 ? rl_sum_wins / rl_wins : 0)
      avg_loss_amount = (rl_losses > 0 ? rl_sum_losses / rl_losses : 0)
      
      denom = (avg_loss_amount < 0) ? -avg_loss_amount : avg_loss_amount
      win_loss_ratio = (denom > 0 ? avg_win_amount / denom : 0)
      
      avg_pnl_per_trade = (total_trades > 0 ? trl / total_trades : 0)
      expected_return_per_trade = (RL_CASH > 0 ? avg_pnl_per_trade / RL_CASH : 0)

      # Restore Open Trade Averages
      avg_open_wins = (rl_open_wins > 0 ? rl_val_open_wins / rl_open_wins : 0)
      avg_open_losses = (rl_open_losses > 0 ? rl_val_open_losses / rl_open_losses : 0)

      # 4. CALCULATE MEDIANS (Days Held)
      if (sys_closed_trades > 0) {
          
          # Median Days Held
          asort(all_hold_days)
          if (sys_closed_trades % 2) median_days = all_hold_days[(sys_closed_trades + 1) / 2]
          else median_days = (all_hold_days[sys_closed_trades / 2] + all_hold_days[sys_closed_trades / 2 + 1]) / 2
      }
      avg_days_open = (sys_closed_trades > 0 ? sys_total_hold_days / sys_closed_trades : 0)

      # Calculate Synthetic Annualized ROR
      # 1. Standard Trade Profile (using Average)
      avg_pnl_pct = (total_trades > 0 ? (trl / (total_trades * RL_CASH)) : 0)
      avg_days = (sys_closed_trades > 0 ? sys_total_hold_days / sys_closed_trades : 0)

      # 2. Annualize over DAYS_PER_YEAR Calendar Days
      if (avg_days > 0 && avg_pnl_pct > -1) {
          synthetic_ror = ((1 + avg_pnl_pct)^(DAYS_PER_YEAR / avg_days)) - 1
      } else {
          synthetic_ror = 0
      }

      # Calculate Profit Factor: Gross Wins / Absolute Gross Losses
      denom_pf = (rl_sum_losses < 0) ? -rl_sum_losses : rl_sum_losses
      profit_factor = (denom_pf > 0 ? rl_sum_wins / denom_pf : rl_sum_wins)

      # 5. OUTPUT SUMMARY (RocketLauncher.csv)
      linktodrive = "\"=hyperlink(\"\"https://drive.google.com/drive/u/0/search?q=" ts "\"\",\"\"" ts "\"\")\""
 
      # --- THE SAFE METHOD: BUILD ROW COLUMN-BY-COLUMN ---
      # Part 1: Parameters
      out = linktodrive "," RL_CASH "," SMA_QUAL "," RL_DIP_PCT "," RL_STOP_PCT
      out = out "," RL_TARGET_PCT "," RL_EXPANSION "," RL_ACC_MIN "," RL_ACC_COUNT
      out = out "," RL_TOO_HIGH "," RL_TRAIL_PROFIT "," RL_TRAIL_STOP
      out = out "," RL_TRAIL_PROFIT2 "," RL_TRAIL_STOP2
      out = out "," sprintf("%.4f", RL_ATR_HIGH_PERCENT) "," sprintf("%.4f", RL_ATR_LOW_PERCENT)
      out = out "," RL_SLOPE_PERIOD "," sprintf("%.4f", RL_SLOPE_THRESHOLD)
      #out = out "," RL_SHOCK_THRESHOLD "," sprintf("%.4f", RL_SHOCK_THRESHOLD)
      #out = out "," RL_SHOCK_REHAB_DAYS "," RL_SHOCK_REHAB_DAYS
      #out = out "," RL_SHOCK_MAX_ALLOWED "," RL_SHOCK_MAX_ALLOWED
    # NEW: Export the Timed and Partial settings
      out = out "," RL_EXIT_DAYS "," sprintf("%.4f", RL_EXIT_PERCENT)
      out = out "," sprintf("%.4f", PARTIAL_EXIT_TARGET) "," sprintf("%.4f", PARTIAL_EXIT_PERCENT)
      out = out "," sprintf("%.4f", PARTIAL_EXIT_FOLLOW_TARGET)
      out = out "," SPY_INCLUSION "," RL_FLUSH_DAYS
      out = out "," AVG_VOL_DAYS "," VOL_PCT_THRESHOLD

      # Part 2: 50-Day System Results (TOTAL PNL and trade counts)
      out = out "," sprintf("%.2f", trl) "," rl_wins "," rl_losses "," rl_BEs
      out = out "," sprintf("%.2f%%", percent_wins*100) "," sprintf("%.2f%%", percent_losses*100)
      out = out "," sprintf("%.2f", win_loss_ratio) 
      out = out "," sprintf("%.2f", profit_factor)
      out = out "," p_max_streak
      out = out "," sprintf("%.2f", avg_win_amount)
      out = out "," sprintf("%.2f", avg_loss_amount) "," sprintf("%.2f", avg_pnl_per_trade)
      out = out "," sprintf("%.4f", expected_return_per_trade)

      # Part 3: Open Trades
      out = out "," rl_open_wins "," sprintf("%.2f", rl_val_open_wins) "," sprintf("%.2f", avg_open_wins)
      out = out "," rl_open_losses "," sprintf("%.2f", rl_val_open_losses) "," sprintf("%.2f", avg_open_losses)

      # Part 4: 100-Day System & Portfolio Totals
    out = out "," RL_100_TOGGLE "," sprintf("%.2f", trl100) "," rl100_wins "," rl100_losses
    out = out "," sprintf("%.2f", avg_days_open) "," sprintf("%.2f", median_days)
    out = out "," sprintf("%.4f", synthetic_ror) "," sprintf("%.4f", max_port_dd)

    # Append new raw data for Python Optimization 2.0 ranking
    out = out "," sprintf("%.6f", avg_ces)      
    out = out "," sprintf("%.4f", median_ces)   
    out = out "," p90_days                   
    out = out "," timed_exit_count
    out = out "," sys_total_hold_days
    profit_per_capital_day = (sys_total_hold_days > 0) ? (trl / sys_total_hold_days) : 0
    out = out "," sprintf("%.6f", profit_per_capital_day)
    out = out "," sprintf("%.4f", pct_time_underwater) "," max_consecutive_underwater "," max_pos
    # summary line has 61 columns (incl. ProfitPerCapDay, Pct_Time_Underwater, Max_Consec_Underwater, Max_Pos)

      # Final Print: normal audit appends to RocketLauncher.csv and temp_run.csv (RegressionCheck.ps1
      # matches CurrentTs in temp_run). Optimizer uses -v OUT_FILE=temp_run_core_N.csv only.
    if (OUT_FILE == "") {
        print out >> "RocketLauncher.csv"
        close("RocketLauncher.csv")
        print out >> "temp_run.csv"
        close("temp_run.csv")
    } else {
        print out >> OUT_FILE
        close(OUT_FILE)
    }

      # --- 2. RESTORED & CSV FORMATTED: RL_SUMMARY.CSV ---
      # Now explicitly comma-delimited
      print "SYMBOL,ROCKET_L,50_TRIG,50_W,50_L,50_BE,PARTIAL_CNT,PARTIAL_AMT,100_TRIG,100_W,100_L,100_BE" > summary_file
      n_list = asorti(all_syms, alphabetized)
      for (i = 1; i <= n_list; i++) {
            s = alphabetized[i]
            if (s ~ /^[0-9.]+$/) continue
            # Standardized CSV output string
            printf "%s,%.2f,%d,%d,%d,%d,%d,%.2f,%d,%d,%d,%d\n", \
            s, rocket_pnl[s], t50_cnt[s], final_50_w[s], final_50_l[s], final_50_b[s], \
            sym_partial_cnt[s], sym_partial_amt[s], \
            t100_cnt[s], final_100_w[s], final_100_l[s], final_100_b[s] >> summary_file
      }

      # --- 3. SCANNER FILE (last bar: 50-trigger day; ENTRY_DATE = next session / model buy day) ---
      if (scanner_ptr > 0) {
          print "SYMBOL,TRIGGER_DATE,TRIGGER_CLOSE,ENTRY_DATE,ENTRY_OPEN_REF,STOP_LOSS,TOO_HIGH_LINE,TARGET,ENTRY_ALLOWED" > scanner_file
          for (i = 1; i <= scanner_ptr; i++) print scanner_list[i] >> scanner_file
          close(scanner_file)
      }

      # --- RL Watchlist: approaching / pending 50-setup (last bar, flat); not RL_Open / not RL_Scanner rows ---
      delete wl_sorted
      delete opn_sym
      delete scan_sym
      for (xp = 1; xp <= rl_open_ptr; xp++) {
          split(rl_open_list[xp], wkv, ",")
          if (wkv[1] != "") opn_sym[wkv[1]] = 1
      }
      for (i = 1; i <= scanner_ptr; i++) {
          split(scanner_list[i], wkv, ",")
          if (wkv[1] != "") scan_sym[wkv[1]] = 1
      }
      nwl = 0
      for (wsym in watch_best_ln) {
          if (wsym in opn_sym || wsym in scan_sym) continue
          wl_sorted[++nwl] = wsym
      }
      if (nwl > 0) {
          for (wi = 1; wi < nwl; wi++) {
              for (wk = wi + 1; wk <= nwl; wk++) {
                  if (wl_sorted[wi] > wl_sorted[wk]) {
                      tmp = wl_sorted[wi]; wl_sorted[wi] = wl_sorted[wk]; wl_sorted[wk] = tmp
                  }
              }
          }
      }
      print "SYMBOL,ASOF_DATE,SETUP_SCORE,WATCH_TIER,MISSING_OR_NOTES,TRIGGER_CLOSE,SMA50_REF" > watchlist_file
      if (nwl > 0) {
          for (wi = 1; wi <= nwl; wi++) {
              print watch_best_ln[wl_sorted[wi]] >> watchlist_file
          }
          for (wi = 1; wi <= nwl; wi++) {
              if (wi == 1) print wl_sorted[wi] > watchlist_txt
              else print wl_sorted[wi] >> watchlist_txt
          }
          close(watchlist_txt)
      }
      close(watchlist_file)

      if (INSTRUMENT) printf "Metrics/sort/processing: %.3fs\n", (get_ms() - T_METRICS_START) / 1000 >> INST_FILE
      # 6. PRINT INDIVIDUAL FILES
      if (INSTRUMENT) T_FILE_START = get_ms()
      if (rl_open_ptr > 0) {
            printf "SYMBOL,DATE OPENED,ENTRY PRICE,CURRENT PRICE,PNL %%,# DAYS OPEN,TRIGGER TYPE,STOP LOSS,TARGET,DISTANCE COVERED TO TARGET,PREVIOUS EXP TO TARGET,MOST recent EXP,MOST RECENT RESET\n" > open_file
            for (xp=1; xp<=rl_open_ptr; xp++) print rl_open_list[xp] >> open_file
      }
      # Always write RL_Closed (header + rows if any) so run timestamp is findable by RegressionCheck
      printf "SYMBOL,DATE OPENED,ENTRY PRICE,SMA20,SMA30,SMA50,SMA100,SMA200,CLOSE TO HIGH,MAX PRICE,MAX GAIN,MIN PRICE,TOO HIGH?,ORIGINAL STOP,STOP LOSS AT CLOSE,ORIGINAL TARGET,RISK (%% to stop),Reward/risk,DATE CLOSED,DAYS HELD,EXIT PRICE,PNL %%,ANNUALIZED ROR,EXIT TYPE,MAE, MAX DRAW DOWN,TRIGGER TYPE,HIST_HIGH_PCT,HIST_CLOSE_PCT,HIST_LOW_PCT,ENTRY_ATR_STOP,ATR,ATR %% OF PRICE,PREVIOUS EXP TO TARGET,PRIOR RESET,MOST recent EXP,MOST RECENT RESET,SLOPE AT ENTRY,SPY AT ENTRY,SPY20,SPY30,SPY50,SPY100,SPY200,ACTIVE_SHOCKS,LAST SHOCK MAGNITUDE,SHOCK REHAB COOLDOWN REMAINING,CLOSE PRIOR,OPEN ON DAY OF CLOSE,DAYS_TO_10,DAYS_TO_20,DAYS_TO_30,DAYS_TO_40,DAYS_TO_50,DAYS_TO_60,10_TO_CLOSE,20_TO_CLOSE,30_TO_CLOSE,40_TO_CLOSE,50_TO_CLOSE,60_TO_CLOSE,Trade_CES,PARTIAL_DATE,PARTIAL_AMT,AVG EXIT PRICE,AVG_VOL,TRIGGER_VOL,PIVOT_HIGH_AT_ENTRY,PIVOT_LOW_AT_ENTRY,STRUCT_HIGH_AT_ENTRY,STRUCT_LOW_AT_ENTRY,MAJOR_PIVOT_HIGH_AT_ENTRY,MAJOR_PIVOT_LOW_AT_ENTRY,PIVOT_HIGH_PRICE_AT_ENTRY,PIVOT_LOW_PRICE_AT_ENTRY,LAST_PIVOT_HIGH_PRICE,LAST_PIVOT_LOW_PRICE,PREV_PIVOT_HIGH_PRICE,PREV_PIVOT_LOW_PRICE\n" > closed_file
      for (xc=1; xc<=rl_closed_ptr; xc++) print rl_closed_list[xc] >> closed_file
      close(closed_file)

      # 100-SMA system: separate RL100_Closed file (same header as RL_Closed for alignment)
      printf "SYMBOL,DATE OPENED,ENTRY PRICE,SMA20,SMA30,SMA50,SMA100,SMA200,CLOSE TO HIGH,MAX PRICE,MAX GAIN,MIN PRICE,TOO HIGH?,ORIGINAL STOP,STOP LOSS AT CLOSE,ORIGINAL TARGET,RISK (%% to stop),Reward/risk,DATE CLOSED,DAYS HELD,EXIT PRICE,PNL %%,ANNUALIZED ROR,EXIT TYPE,MAE, MAX DRAW DOWN,TRIGGER TYPE,HIST_HIGH_PCT,HIST_CLOSE_PCT,HIST_LOW_PCT,ENTRY_ATR_STOP,ATR,ATR %% OF PRICE,PREVIOUS EXP TO TARGET,PRIOR RESET,MOST recent EXP,MOST RECENT RESET,SLOPE AT ENTRY,SPY AT ENTRY,SPY20,SPY30,SPY50,SPY100,SPY200,ACTIVE_SHOCKS,LAST SHOCK MAGNITUDE,SHOCK REHAB COOLDOWN REMAINING,CLOSE PRIOR,OPEN ON DAY OF CLOSE,DAYS_TO_10,DAYS_TO_20,DAYS_TO_30,DAYS_TO_40,DAYS_TO_50,DAYS_TO_60,10_TO_CLOSE,20_TO_CLOSE,30_TO_CLOSE,40_TO_CLOSE,50_TO_CLOSE,60_TO_CLOSE,Trade_CES,PARTIAL_DATE,PARTIAL_AMT,AVG EXIT PRICE,AVG_VOL,TRIGGER_VOL,PIVOT_HIGH_AT_ENTRY,PIVOT_LOW_AT_ENTRY,STRUCT_HIGH_AT_ENTRY,STRUCT_LOW_AT_ENTRY,MAJOR_PIVOT_HIGH_AT_ENTRY,MAJOR_PIVOT_LOW_AT_ENTRY,PIVOT_HIGH_PRICE_AT_ENTRY,PIVOT_LOW_PRICE_AT_ENTRY,LAST_PIVOT_HIGH_PRICE,LAST_PIVOT_LOW_PRICE,PREV_PIVOT_HIGH_PRICE,PREV_PIVOT_LOW_PRICE\n" > RL100_closed_file
      for (xc=1; xc<=RL100_closed_ptr; xc++) print RL100_closed_list[xc] >> RL100_closed_file
      close(RL100_closed_file)

      # Dive Bomber output files
      printf "SYMBOL,DATE OPENED,ENTRY PRICE,SMA50,SMA100,SMA200,SIGNAL_HI,SIGNAL_SMA50,PCT_ENTRY_FROM_50,PCT_SIGNAL_HI_FROM_50,DATE CLOSED,DAYS HELD,EXIT PRICE,PNL %%,EXIT TYPE,ATR,ATR %% OF PRICE\n" > db_closed_file
      for (xc=1; xc<=db_closed_ptr; xc++) print db_closed_list[xc] >> db_closed_file
      close(db_closed_file)
      if (db_open_ptr > 0) {
            printf "SYMBOL,DATE OPENED,ENTRY PRICE,CURRENT PRICE,PNL %%,# DAYS OPEN,TRIGGER TYPE,STOP LOSS,TARGET\n" > db_open_file
            for (xp=1; xp<=db_open_ptr; xp++) print db_open_list[xp] >> db_open_file
            close(db_open_file)
      }

      # Dive Bomber Summary (Total PNL, Profit Factor, CES, etc.)
      total_trades_db = db_wins + db_losses + db_BEs
      percent_wins_db = (total_trades_db > 0 ? db_wins / total_trades_db : 0)
      percent_losses_db = (total_trades_db > 0 ? db_losses / total_trades_db : 0)
      avg_win_amount_db = (db_wins > 0 ? db_sum_wins / db_wins : 0)
      avg_loss_amount_db = (db_losses > 0 ? db_sum_losses / db_losses : 0)
      denom_db = (avg_loss_amount_db < 0) ? -avg_loss_amount_db : avg_loss_amount_db
      win_loss_ratio_db = (denom_db > 0 ? avg_win_amount_db / denom_db : 0)
      denom_pf_db = (db_sum_losses < 0) ? -db_sum_losses : db_sum_losses
      profit_factor_db = (denom_pf_db > 0 ? db_sum_wins / denom_pf_db : (db_sum_losses == 0 ? db_sum_wins : 0))
      avg_ces_db = (db_total_hold_days > 0 ? db_total_pnl_pct / db_total_hold_days : 0)
      median_ces_db = 0
      if (db_trade_ptr > 0) {
          asort(all_db_trade_ces)
          if (db_trade_ptr % 2 == 1) median_ces_db = all_db_trade_ces[int(db_trade_ptr / 2) + 1]
          else { m1 = all_db_trade_ces[db_trade_ptr / 2]; m2 = all_db_trade_ces[db_trade_ptr / 2 + 1]; median_ces_db = (m1 + m2) / 2 }
      }
      avg_days_db = (db_trade_ptr > 0 ? db_total_hold_days / db_trade_ptr : 0)
      avg_pnl_pct_db = (total_trades_db > 0 ? (trdb / (total_trades_db * DB_CASH)) : 0)
      synthetic_ror_db = 0
      if (avg_days_db > 0 && avg_pnl_pct_db > -1) synthetic_ror_db = ((1 + avg_pnl_pct_db)^(DAYS_PER_YEAR / avg_days_db)) - 1
      avg_pnl_per_trade_db = (total_trades_db > 0 ? trdb / total_trades_db : 0)
      expected_return_per_trade_db = (DB_CASH > 0 ? avg_pnl_per_trade_db / DB_CASH : 0)

      # DB_Summary: per-stock report (like RL_Summary) — SYMBOL, TRADES, WINS, LOSSES, BEs, PNL
      print "SYMBOL,TRADES,WINS,LOSSES,BEs,PNL" > db_summary_file
      n_db_list = asorti(db_syms, db_sym_list)
      for (i = 1; i <= n_db_list; i++) {
            s = db_sym_list[i]
            if (s ~ /^[0-9.]+$/) continue
            printf "%s,%d,%d,%d,%d,%.2f\n", s, db_trades_s[s]+0, db_wins_s[s]+0, db_losses_s[s]+0, db_BEs_s[s]+0, db_pnl_s[s]+0 >> db_summary_file
      }
      close(db_summary_file)

      # DiveBomber.csv: append one row per run (like RocketLauncher.csv); write header if new file
      dive_bomber_file = OUTPUT_DIR "\\DiveBomber.csv"
      db_header_line = ""
      if ((getline db_header_line < dive_bomber_file) >= 0) { close(dive_bomber_file) }
      if (db_header_line !~ /^TIMESTAMP/) {
            print "TIMESTAMP,DB_CASH,DB_STOP_PCT,DB_TARGET_PCT,DB_RIP_DAYS_MIN,DB_RIP_DAYS_MAX,DB_RIP_TOUCH_TOL,DB_MAX_HOLD_DAYS,DB_SQUEEZE_EXIT,DB_EXPANSION,DB_ACC_MIN,DB_ACC_COUNT,DB_PEAK_TROUGH_MAX,TOTAL_PNL,WINS,LOSSES,BEs,WIN%%,LOSS%%,AVG_WIN,AVG_LOSS,WIN_LOSS_RATIO,PROFIT_FACTOR,AVG_CES,MEDIAN_CES,AVG_DAYS_HELD,SYNTHETIC_ROR,AVG_PNL_PER_TRADE,EXPECTED_RETURN_PER_TRADE" > dive_bomber_file
            close(dive_bomber_file)
      }
      printf "%s,%.2f,%.4f,%.2f,%d,%d,%.4f,%d,%d,%.2f,%d,%d,%.2f,%.2f,%d,%d,%d,%.2f%%,%.2f%%,%.2f,%.2f,%.2f,%.2f,%.6f,%.4f,%.2f,%.4f,%.2f,%.4f\n", ts, DB_CASH, DB_STOP_PCT, DB_TARGET_PCT, DB_RIP_DAYS_MIN, DB_RIP_DAYS_MAX, DB_RIP_TOUCH_TOL, DB_MAX_HOLD_DAYS, DB_SQUEEZE_EXIT, DB_EXPANSION, DB_ACC_MIN, DB_ACC_COUNT, DB_PEAK_TROUGH_MAX, trdb, db_wins, db_losses, db_BEs, percent_wins_db*100, percent_losses_db*100, avg_win_amount_db, avg_loss_amount_db, win_loss_ratio_db, profit_factor_db, avg_ces_db, median_ces_db, avg_days_db, synthetic_ror_db, avg_pnl_per_trade_db, expected_return_per_trade_db >> dive_bomber_file
      close(dive_bomber_file)

      #printf "\n# MAX PORTFOLIO DRAWDOWN: %.2f%%\n", max_port_dd * 100 > "/dev/stderr"
      if (INSTRUMENT) {
          printf "File output: %.3fs\n", (get_ms() - T_FILE_START) / 1000 >> INST_FILE
          printf "--- PHASE SUMMARY ---\n" >> INST_FILE
          if (T_SPY_END > 0) printf "SPY load: %.3fs\n", (T_SPY_END - T_SPY_START) / 1000 >> INST_FILE
          printf "END block: %.3fs\n", (get_ms() - T_END_START) / 1000 >> INST_FILE
          printf "--- PERFORM_audit SUB-SECTIONS (within Pass1+Pass2) ---\n" >> INST_FILE
          printf "  Top (expansion/peak): %.3fs\n", T_TOP_MS/1000 >> INST_FILE
          printf "  Shock detector: %.3fs\n", T_SHOCK_MS/1000 >> INST_FILE
          printf "  ATR: %.3fs\n", T_ATR_MS/1000 >> INST_FILE
          printf "  SMA rolling: %.3fs (lookup: %.3fs, n-day: %.3fs, slope+acc: %.3fs)\n", T_SMA_MS/1000, T_SMA_LOOKUP_MS/1000, T_SMA_NDAY_MS/1000, T_SMA_SLOPE_ACC_MS/1000 >> INST_FILE
          printf "  Main 50-day (position mgmt): %.3fs\n", T_MAIN50_MS/1000 >> INST_FILE
          printf "  Expansion lookback: %.3fs\n", T_EXPANSION_MS/1000 >> INST_FILE
          printf "  Dip zone: %.3fs\n", T_DIPZONE_MS/1000 >> INST_FILE
          printf "  100-day: %.3fs\n", T_100DAY_MS/1000 >> INST_FILE
          printf "  Dive Bomber: %.3fs\n", T_DB_MS/1000 >> INST_FILE
          printf "  Drawdown (BULLPROOF): %.3fs\n", T_DRAWDOWN_MS/1000 >> INST_FILE
          printf "  [Precomputed SMA: %d hits, %d computed]\n", PRECOMP_SMA_HITS+0, PRECOMP_SMA_MISS+0 >> INST_FILE
          printf "--- TOTAL RUNTIME: %.3fs ---\n", (get_ms() - T_START) / 1000 >> INST_FILE
          close(INST_FILE)
      }

    # 2. Trigger the Python Drawdown Calculation only when there are closed trades
    q = "\""
    if (rl_closed_ptr > 0) {
    python_cmd = "python " PYTHON_SCRIPT_DIR "\\DrawdownCalc.py " q closed_file q " " DATA_DIR
    printf "\n------------------------------------------------------------\n" > "CON"
    printf "TRIGGERING PORTFOLIO RECONSTRUCTION...\n" > "CON"
    system(python_cmd)
    printf "------------------------------------------------------------\n" > "CON"
    }

    # End timestamp and duration (run_audit.ps1 also prints to console; no system() here for speed)
    end_sec = (get_ms() - T_START) / 1000
    printf "\n------------------------------------------------------------\n" > "CON"
    printf "AWK AUDIT END:   (duration: %.1f s)\n", end_sec > "CON"
    printf "------------------------------------------------------------\n" > "CON"

    # Diagnostic summary (investigate when nothing is processed)
    printf "\n=== DIAG SUMMARY ===\n" >> DIAG_FILE
    printf "all_syms_count=%d first_audit_sym=%s d_ptr_first=%s\n", all_syms_count+0, first_audit_sym, (first_audit_sym != "" ? d_ptr[first_audit_sym]+0 : "n/a") >> DIAG_FILE
    printf "diag_dip_zone_enters=%d diag_dip_inner_enters=%d\n", diag_dip_zone_enters+0, diag_dip_inner_enters+0 >> DIAG_FILE
    printf "tr_expansion=%d tr_acceptance=%d tr_all_conditions=%d tr_actually_opened=%d\n", tr_expansion, tr_acceptance, tr_all_conditions, tr_actually_opened >> DIAG_FILE
    close(DIAG_FILE)

    # Troubleshooting: why no purchases? (counts of times each condition passed in dip-zone evaluations)
    printf "PURCHASE TROUBLESHOOT (dip-zone evaluations)\n" > TROUBLESHOOT_FILE
    printf "  expansion:%d acceptance:%d cut_it:%d atr_inclusion:%d spy_inclusion:%d\n", tr_expansion, tr_acceptance, tr_cut_it, tr_atr_inclusion, tr_spy_inclusion >> TROUBLESHOOT_FILE
    printf "  peak_inclusion:%d slope_ok:%d shock_qualified:%d too_low:%d\n", tr_peak_inclusion, tr_slope_ok, tr_shock_qualified, tr_too_low >> TROUBLESHOOT_FILE
    printf "  all_conditions_met:%d actually_opened:%d\n", tr_all_conditions, tr_actually_opened >> TROUBLESHOOT_FILE
    printf "If all_conditions_met > 0 but actually_opened = 0, next_day_iso/raw_op or isnottoohigh failed.\n" >> TROUBLESHOOT_FILE
    close(TROUBLESHOOT_FILE)

    # 100-SMA troubleshooting: separate file + DIAG summary (why 0 triggered purchases?)
    RL100_troubleshoot_path = OUTPUT_DIR "\\100_RL_troubleshoot_" ts ".txt"
    printf "100-SMA TROUBLESHOOT (run %s)\n", ts > RL100_troubleshoot_path
    printf "  RL100_TOGGLE (must be 1 to enable): check run args / optimizer -v RL100_TOGGLE=1 or RL_100_TOGGLE=1\n" >> RL100_troubleshoot_path
    printf "  block_enters (times 100-day entry block was evaluated): %d\n", tr100_block_enters+0 >> RL100_troubleshoot_path
    printf "  Counts (each condition true this many times):\n" >> RL100_troubleshoot_path
    printf "    sma100_rising:%d inthe100zone:%d uptick:%d closeabove100sma:%d is200:%d stack_ok:%d\n", tr100_sma100_rising+0, tr100_inthe100zone+0, tr100_uptick+0, tr100_closeabove+0, tr100_is200+0, tr100_stack_ok+0 >> RL100_troubleshoot_path
    printf "    exp100:%d acc100:%d cut_it:%d atr:%d spy:%d peak:%d slope:%d shock:%d !too_low:%d vol:%d\n", tr100_exp100+0, tr100_acc100+0, tr100_cut_it+0, tr100_atr+0, tr100_spy+0, tr100_peak+0, tr100_slope+0, tr100_shock+0, tr100_too_low+0, tr100_vol+0 >> RL100_troubleshoot_path
    printf "  all_conditions_met:%d actually_opened:%d\n", tr100_all_conditions+0, tr100_actually_opened+0 >> RL100_troubleshoot_path
    printf "  If block_enters=0 then RL100_TOGGLE was 0 or never reached (check -v RL100_TOGGLE=1).\n" >> RL100_troubleshoot_path
    printf "  If block_enters>0 but a count is 0, that condition never passed (see diagnostic_audit.txt 100SMA_SAMPLE for one bar).\n" >> RL100_troubleshoot_path
    close(RL100_troubleshoot_path)
    printf "100SMA tr100_block_enters=%d tr100_all_conditions=%d tr100_actually_opened=%d\n", tr100_block_enters+0, tr100_all_conditions+0, tr100_actually_opened+0 >> DIAG_FILE

    # Write current run timestamp for post-run regression check (used by run_audit.ps1)
      last_run_file = OUTPUT_DIR "\\last_run_ts.txt"
      print ts > last_run_file
      close(last_run_file)
}