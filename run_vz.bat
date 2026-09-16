@echo off
rem VZ (Volume Zone) - DailyRun official TBN sleeve via TBN host (vz_mode)
rem Engine: rocket_tbn.py -v vz_mode=true -> stock_analysis\rocket_vz.py
rem         (tools\vol_zone_break_retest.py freeze RESEARCH_CANDIDATE_V2_RW63 + EXIT_atr4_s025_r15_ts20)
rem Outputs: drive\VZ_*_<ts>.csv - Closed/Audit/Report match RS/SB wide TBN schema
rem Docs: drive\paul_experiments\VZ_System_Guide.html
rem       drive\paul_experiments\VZ_TBN_Integration_And_Predictive_Timing.html
rem       drive\paul_experiments\tbn_new_systems\volume_zone\HOW_TO_RUN.md
rem
rem Kelly size A/Bs (research only, house sheet $45k unchanged):
rem   drive\paul_experiments\kelly_size_ab_20260915\
rem
rem Freeze (DailyRun + standalone house — do not retune on OOS):
rem   HL-only, first_retest_only=true, min_touches>=1, retest_eps_pct=0.005
rem   lookback=126, retest_window=63, exit=EXIT_atr4_s025_r15_ts20, min_atr_pct_at_trigger=4.0
rem   EXIT token decode (do not guess):
rem     atr4  = 14-day ATR must be >= 4% of trigger close (min_atr_pct_at_trigger /
rem             VZ_MIN_ATR_PCT=4.0 / VZ_MIN_ATR_PCT_AT_TRIGGER). Scanner-known on the
rem             trigger date. Quiet names fail and never enter. NOT a 4-ATR stop.
rem             Operational adopt 2026-09-07 after HOLD AB (entry-priced 4% was quality-
rem             slightly better; flipped for live/scanner identity, not KEEP/gold).
rem             Entry gate is OFF (vz_min_atr_pct_at_entry=0) — one gate only.
rem             Same atr4 prefix was on older EXIT_atr4_s05_r15_ts20 — the 4 did not change when the stop did.
rem     s025  = stop at zone low - 0.25*ATR (stop_atr_buffer=0.25)
rem     r15   = 1.5R target (target_r=1.5)
rem     ts20  = 20-bar time stop (exit_bars=20)
rem   exit_bars=20  (EXIT_ts20 adopt 20260906 — Paul Ann ROR/MaxDD; prior default was 40)
rem   stop_atr=0.25  (PO adopt 20260907 EXIT_stop_atr025; prior house was 0.5 / EXIT_atr4_s05_r15_ts20)
rem   entry_on=next_open (predictive: signal bar T close -> buy T+1 open; never T open)
rem   vz_require_hvn_overlap=false  (delta from prior: HVN knob exists in generate_signals;
rem     DualPaul78 engine A/B HOLD + tradable 764 HOLD — not adopted. Flip to true only after explicit adopt.)
rem   vz_cooldown_after_target_days=10  (house adopt 20260821: post-TARGET re-entry gate;
rem     calendar days inclusive after TARGET exit. set VZ_COOLDOWN_AFTER_TARGET_DAYS=0 to disable.)
rem   One position per symbol (DailyRun lock 2026-09-15): do not buy a name we already hold.
rem     Always on in rocket_vz.enrich_trade_rows (skip later signal while entry_idx is still
rem     on or before the open trade exit bar, including same-day two-zone pile-ups).
rem     No env / -v flag re-enables pyramids. Regression baseline = VZ_LatestRun_* / house pin.
rem     Stamp: drive\paul_experiments\vz_one_position_dailyrun_20260915\
rem   Universe: drive\universes\VZ_universe.csv (Paul78.142, 142-name house); pin VZ_house_last_run_ts.txt
rem
rem Combined adopt note (ts20 + atr05, historical):
rem   drive\paul_experiments\vz_ts20_atr05_adopt_20260906\
rem DailyRun official TBN adopt (Paul78.142 + stop 0.25):
rem   drive\paul_experiments\vz_tbn_adopt_s025_paul78_20260907\
rem ATR% gate at trigger (operational adopt after HOLD AB):
rem   drive\paul_experiments\vz_atr_trigger_adopt_20260907\
rem
rem Universe: drive\universes\VZ_universe.csv (Paul78.142 142-name house; prior 56 backup: VZ_universe_new56_backup_20260907.csv; DualPaul78 backup: VZ_universe_DualPaul78_backup.csv)
rem Override: run_vz.bat path\to\test_universe.csv
rem          set VZ_UNIVERSE_CSV=...
rem          set VZ_SYMBOLS=AAPL,MSFT
rem Full universe: run_vz.bat ALL / --all / "*"
rem Workers: set VZ_WORKERS=12
rem Extra CLI: trailing %* forwarded to rocket_tbn (-v KEY=VALUE kept).
rem
rem DailyRun: official TBN sleeve step [10b/13] behind SKIP_VZ=1 (not walk-forward gold).

setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

if not defined VZ_LOOKBACK set "VZ_LOOKBACK=126"
if not defined VZ_RETEST_WINDOW set "VZ_RETEST_WINDOW=63"
if not defined VZ_RETEST_EPS set "VZ_RETEST_EPS=0.005"
if not defined VZ_MIN_TOUCHES set "VZ_MIN_TOUCHES=1"
if not defined VZ_ENTRY_ON set "VZ_ENTRY_ON=next_open"
if not defined VZ_EXIT_NAME set "VZ_EXIT_NAME=EXIT_atr4_s025_r15_ts20"
if not defined VZ_EXIT_BARS set "VZ_EXIT_BARS=20"
if not defined VZ_TARGET_R set "VZ_TARGET_R=1.5"
if not defined VZ_STOP_ATR set "VZ_STOP_ATR=0.25"
if not defined VZ_MIN_ATR_PCT set "VZ_MIN_ATR_PCT=4.0"
if not defined VZ_MIN_ATR_PCT_AT_ENTRY set "VZ_MIN_ATR_PCT_AT_ENTRY=0"
if not defined VZ_MIN_ATR_PCT_AT_TRIGGER set "VZ_MIN_ATR_PCT_AT_TRIGGER=%VZ_MIN_ATR_PCT%"
if not defined VZ_REQUIRE_HVN_OVERLAP set "VZ_REQUIRE_HVN_OVERLAP=false"
if not defined VZ_TRADE_SIDE set "VZ_TRADE_SIDE=long"
if not defined VZ_COOLDOWN_AFTER_TARGET_DAYS set "VZ_COOLDOWN_AFTER_TARGET_DAYS=10"
if not defined VZ_AGGRESSIVE set "VZ_AGGRESSIVE=true"
if not defined VZ_WORKERS set "VZ_WORKERS=12"

set "VZ_AGG_FLAG="
if /i "%VZ_AGGRESSIVE%"=="true" set "VZ_AGG_FLAG=--aggressive"
if /i "%VZ_AGGRESSIVE%"=="1" set "VZ_AGG_FLAG=--aggressive"
if /i "%VZ_AGGRESSIVE%"=="yes" set "VZ_AGG_FLAG=--aggressive"

call "%~dp0tools\apply_universe_cli_arg.bat" VZ_UNIV_ARG %1 %2
call "%~dp0tools\build_cli_forward.bat" VZ_FORWARD "%VZ_UNIV_ARG%" %*
call "%~dp0tools\load_universe_csv.bat" VZ "%VZ_UNIV_ARG%"
if errorlevel 1 exit /b 1
echo [VZ] DailyRun/house sleeve via TBN vz_mode - Universe src=%VZ_UNIVERSE_SRC% pass_s=%VZ_PASS_SYMBOLS%
echo [VZ] freeze lookback=%VZ_LOOKBACK% rw=%VZ_RETEST_WINDOW% entry_on=%VZ_ENTRY_ON% exit=%VZ_EXIT_NAME% exit_bars=%VZ_EXIT_BARS% stop_atr=%VZ_STOP_ATR% target_r=%VZ_TARGET_R% min_atr_entry=%VZ_MIN_ATR_PCT_AT_ENTRY% min_atr_trigger=%VZ_MIN_ATR_PCT_AT_TRIGGER% hvn=%VZ_REQUIRE_HVN_OVERLAP% trade_side=%VZ_TRADE_SIDE% cd_target=%VZ_COOLDOWN_AFTER_TARGET_DAYS% one_pos=on workers=%VZ_WORKERS%

if /i "%VZ_UNIVERSE_SRC%"=="missing" (
  echo [VZ] ERROR: drive\universes\VZ_universe.csv missing - refusing silent full-universe fallback.
  echo [VZ] ERROR: Restore VZ_universe.csv or pass an explicit CSV / run_vz.bat ALL.
  exit /b 1
)

rem Neutralize peer systems; VZ owns entry path via vz_mode.
rem One-line invokes (like run_rs.bat): blank lines after ^ break CMD continuation.
if "%VZ_PASS_SYMBOLS%"=="1" (
  "%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w %VZ_WORKERS% --no-regression %VZ_AGG_FLAG% --initial-capital 500000 --aggressive-max-multiple 2.0 --margin-utilization 0.6 -v vz_mode=true -v brt_zones=false -v yh_zones=false -v wpbr_zones=false -v rl_mode=false -v relative_strength_enabled=false -v rs_mode=false -v mvcp_mode=false -v sb_mode=false -v qull_mode=false -v indicator_buy=off -v vz_lookback_days=%VZ_LOOKBACK% -v vz_retest_window=%VZ_RETEST_WINDOW% -v vz_retest_eps_pct=%VZ_RETEST_EPS% -v vz_first_retest_only=true -v vz_min_touches_before_entry=%VZ_MIN_TOUCHES% -v vz_entry_on=%VZ_ENTRY_ON% -v vz_zone_kinds=HL -v vz_exit_name=%VZ_EXIT_NAME% -v vz_exit_bars=%VZ_EXIT_BARS% -v vz_target_r=%VZ_TARGET_R% -v vz_stop_atr_buffer=%VZ_STOP_ATR% -v vz_min_atr_pct_at_entry=%VZ_MIN_ATR_PCT_AT_ENTRY% -v vz_min_atr_pct_at_trigger=%VZ_MIN_ATR_PCT_AT_TRIGGER% -v vz_require_hvn_overlap=%VZ_REQUIRE_HVN_OVERLAP% -v vz_trade_side=%VZ_TRADE_SIDE% -v vz_cooldown_after_target_days=%VZ_COOLDOWN_AFTER_TARGET_DAYS% -v vz_sheet_notional=45000 -s "!VZ_SYMBOLS!" !VZ_FORWARD!
) else (
  "%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w %VZ_WORKERS% --no-regression %VZ_AGG_FLAG% --initial-capital 500000 --aggressive-max-multiple 2.0 --margin-utilization 0.6 -v vz_mode=true -v brt_zones=false -v yh_zones=false -v wpbr_zones=false -v rl_mode=false -v relative_strength_enabled=false -v rs_mode=false -v mvcp_mode=false -v sb_mode=false -v qull_mode=false -v indicator_buy=off -v vz_lookback_days=%VZ_LOOKBACK% -v vz_retest_window=%VZ_RETEST_WINDOW% -v vz_retest_eps_pct=%VZ_RETEST_EPS% -v vz_first_retest_only=true -v vz_min_touches_before_entry=%VZ_MIN_TOUCHES% -v vz_entry_on=%VZ_ENTRY_ON% -v vz_zone_kinds=HL -v vz_exit_name=%VZ_EXIT_NAME% -v vz_exit_bars=%VZ_EXIT_BARS% -v vz_target_r=%VZ_TARGET_R% -v vz_stop_atr_buffer=%VZ_STOP_ATR% -v vz_min_atr_pct_at_entry=%VZ_MIN_ATR_PCT_AT_ENTRY% -v vz_min_atr_pct_at_trigger=%VZ_MIN_ATR_PCT_AT_TRIGGER% -v vz_require_hvn_overlap=%VZ_REQUIRE_HVN_OVERLAP% -v vz_trade_side=%VZ_TRADE_SIDE% -v vz_cooldown_after_target_days=%VZ_COOLDOWN_AFTER_TARGET_DAYS% -v vz_sheet_notional=45000 !VZ_FORWARD!
)
exit /b %errorlevel%
