@echo off
rem RSI — Relative Strength Index (TBN sleeve via rsi_mode)
rem Engine: rocket_tbn.py -v rsi_mode=true -> stock_analysis\rocket_rsi.py
rem Outputs: drive\RSI_*_<ts>.csv - Closed/Open/Watchlist/Summary/Report/Audit/Equity
rem Prior ATR% adopt: drive\paul_experiments\rsi_atr5_dailyrun_20260914\
rem
rem NOT RS (Relative Strength vs SPY). RSI = Wilder Relative Strength Index (14).
rem
rem Freeze (DailyRun + standalone house — do not retune on OOS):
rem   rsi_ob=70, rsi_os=30, rsi_exit=70, rsi_max_trigger=60
rem   rsi_min_atr_pct=2.93, rsi_time_stop_days=20, rsi_entry_on=next_open
rem   rsi_roll_from_max=8  (EXIT: flatten next open when in-trade max RSI − RSI >= 8)
rem   rsi_min_dist_to_52w_high_pct_at_trigger=0  (off — do not pass 7.18)
rem   rsi_sheet_notional=10000
rem Adopt: drive\paul_experiments\rsi_roll_ab_20260916\ (EXIT roll-8 preference; Ann ROR / shorter hold)
rem Prior ATR% adopt: drive\paul_experiments\rsi_atr293_dailyrun_20260916\ (preference; more trades; not WF gold)
rem Prior 7.18 dist wire reverted: drive\paul_experiments\rsi_mindist52_718_20260916\
rem Kelly size A/Bs (research only, house $10k unchanged):
rem   drive\paul_experiments\kelly_size_ab_20260915\
rem   Universe: drive\universes\rsi_universe.csv
rem     = RSIN_HighFIT_ISgood_maxrsi60_20260911.csv (N=149 High-FIT / IS-good recommended)
rem   House pin: RSI_house_last_run_ts.txt (ALL / research must not steal)
rem
rem Override: run_rsi.bat path\to\test_universe.csv
rem   e.g. run_rsi.bat drive\universes\RSIN_PaulScore5_IS_20260915.csv
rem          set RSI_UNIVERSE_CSV=...
rem          set RSI_SYMBOLS=AAPL,MSFT
rem Full universe: run_rsi.bat ALL / --all / "*"
rem Workers: set RSI_WORKERS=12
rem Extra CLI: trailing %* forwarded to rocket_tbn (-v KEY=VALUE kept).
rem Change roll: set RSI_ROLL_FROM_MAX=0  (off)  or  6/7/9/10
rem   or run_rsi.bat ... -v rsi_roll_from_max=0
rem Optional play-around trigger gates (omit / 0 = off). House min_dist52 is off.
rem Column-name -v COL=X means keep if COL >= X at trigger (sheet-style, higher is better):
rem   -v DIST_TO_52W_HIGH_PCT_AT_TRIGGER=7.18  MIN: keep dist>=7.18 (research only; house default 0). Alias of rsi_min_dist_to_52w_high_pct_at_trigger.
rem   -v REL_VOL_ON_TRIGGER=1.4               MIN: keep rel vol>=1.4. Alias of rsi_min_rel_vol_on_trigger.
rem   -v RSI14_DROP_FROM_OB=17                MIN: keep RSI drop>=17. Alias of rsi_min_rsi14_drop_from_ob.
rem Opposite near-high cap (not a column alias): -v rsi_max_dist_to_52w_high_pct_at_trigger=6.81 keep dist<=6.81.
rem Shop IS only: -v entry_end_date=2023-12-31  (fill / DATE_OPENED, not signal date)
rem
rem DailyRun: official TBN sleeve step [10c/13] behind SKIP_RSI=1 (not walk-forward gold).

setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

if not defined RSI_OB set "RSI_OB=70"
if not defined RSI_OS set "RSI_OS=30"
if not defined RSI_EXIT set "RSI_EXIT=70"
if not defined RSI_MAX_TRIGGER set "RSI_MAX_TRIGGER=60"
if not defined RSI_MIN_ATR_PCT set "RSI_MIN_ATR_PCT=2.93"
if not defined RSI_TIME_STOP_DAYS set "RSI_TIME_STOP_DAYS=20"
if not defined RSI_ROLL_FROM_MAX set "RSI_ROLL_FROM_MAX=8"
if not defined RSI_ENTRY_ON set "RSI_ENTRY_ON=next_open"
if not defined RSI_SHEET_NOTIONAL set "RSI_SHEET_NOTIONAL=10000"
if not defined RSI_MIN_DIST_TO_52W_HIGH_PCT_AT_TRIGGER set "RSI_MIN_DIST_TO_52W_HIGH_PCT_AT_TRIGGER=0"
if not defined RSI_AGGRESSIVE set "RSI_AGGRESSIVE=true"
if not defined RSI_WORKERS set "RSI_WORKERS=12"

set "RSI_AGG_FLAG="
if /i "%RSI_AGGRESSIVE%"=="true" set "RSI_AGG_FLAG=--aggressive"
if /i "%RSI_AGGRESSIVE%"=="1" set "RSI_AGG_FLAG=--aggressive"
if /i "%RSI_AGGRESSIVE%"=="yes" set "RSI_AGG_FLAG=--aggressive"

call "%~dp0tools\apply_universe_cli_arg.bat" RSI_UNIV_ARG %1 %2
call "%~dp0tools\build_cli_forward.bat" RSI_FORWARD "%RSI_UNIV_ARG%" %*
call "%~dp0tools\load_universe_csv.bat" RSI "%RSI_UNIV_ARG%"
if errorlevel 1 exit /b 1
echo [RSI] DailyRun/house sleeve via TBN rsi_mode - Universe src=%RSI_UNIVERSE_SRC% pass_s=%RSI_PASS_SYMBOLS%
echo [RSI] freeze ob=%RSI_OB% os=%RSI_OS% exit=%RSI_EXIT% max_trigger=%RSI_MAX_TRIGGER% min_atr=%RSI_MIN_ATR_PCT% ts=%RSI_TIME_STOP_DAYS%d roll_from_max=%RSI_ROLL_FROM_MAX% entry_on=%RSI_ENTRY_ON% min_dist52=%RSI_MIN_DIST_TO_52W_HIGH_PCT_AT_TRIGGER% notional=%RSI_SHEET_NOTIONAL% workers=%RSI_WORKERS%

if /i "%RSI_UNIVERSE_SRC%"=="missing" (
  echo [RSI] ERROR: drive\universes\rsi_universe.csv missing - refusing silent full-universe fallback.
  echo [RSI] ERROR: Restore rsi_universe.csv ^(HighFIT N=149^) or pass an explicit CSV / run_rsi.bat ALL.
  exit /b 1
)

rem Neutralize peer systems; RSI owns entry path via rsi_mode.
rem One-line invokes (like run_vz.bat): blank lines after ^ break CMD continuation.
if "%RSI_PASS_SYMBOLS%"=="1" (
  "%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w %RSI_WORKERS% --no-regression %RSI_AGG_FLAG% --initial-capital 500000 --aggressive-max-multiple 2.0 --margin-utilization 0.6 -v rsi_mode=true -v vz_mode=false -v wrl_mode=false -v brt_zones=false -v yh_zones=false -v wpbr_zones=false -v rl_mode=false -v relative_strength_enabled=false -v rs_mode=false -v mvcp_mode=false -v sb_mode=false -v qull_mode=false -v indicator_buy=off -v rsi_ob=%RSI_OB% -v rsi_os=%RSI_OS% -v rsi_exit=%RSI_EXIT% -v rsi_max_trigger=%RSI_MAX_TRIGGER% -v rsi_min_atr_pct=%RSI_MIN_ATR_PCT% -v rsi_time_stop_days=%RSI_TIME_STOP_DAYS% -v rsi_roll_from_max=%RSI_ROLL_FROM_MAX% -v rsi_entry_on=%RSI_ENTRY_ON% -v rsi_sheet_notional=%RSI_SHEET_NOTIONAL% -v rsi_min_dist_to_52w_high_pct_at_trigger=%RSI_MIN_DIST_TO_52W_HIGH_PCT_AT_TRIGGER% -s "!RSI_SYMBOLS!" !RSI_FORWARD!
) else (
  "%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w %RSI_WORKERS% --no-regression %RSI_AGG_FLAG% --initial-capital 500000 --aggressive-max-multiple 2.0 --margin-utilization 0.6 -v rsi_mode=true -v vz_mode=false -v wrl_mode=false -v brt_zones=false -v yh_zones=false -v wpbr_zones=false -v rl_mode=false -v relative_strength_enabled=false -v rs_mode=false -v mvcp_mode=false -v sb_mode=false -v qull_mode=false -v indicator_buy=off -v rsi_ob=%RSI_OB% -v rsi_os=%RSI_OS% -v rsi_exit=%RSI_EXIT% -v rsi_max_trigger=%RSI_MAX_TRIGGER% -v rsi_min_atr_pct=%RSI_MIN_ATR_PCT% -v rsi_time_stop_days=%RSI_TIME_STOP_DAYS% -v rsi_roll_from_max=%RSI_ROLL_FROM_MAX% -v rsi_entry_on=%RSI_ENTRY_ON% -v rsi_sheet_notional=%RSI_SHEET_NOTIONAL% -v rsi_min_dist_to_52w_high_pct_at_trigger=%RSI_MIN_DIST_TO_52W_HIGH_PCT_AT_TRIGGER% !RSI_FORWARD!
)
exit /b %errorlevel%
