    #!/usr/bin/env python3
"""
Rocket BRT (simplified entry fork): Key Level Interaction Trading System

Zone creation matches the original engine (see rocket_brt_og.py). Entry is intentionally
minimal: bullish signal bar (close > open) plus optional 3-year growth filter
(`growth_filter_enabled`, `growth_bars` default 756). **BH:BI** matured bounds feed **BM/DI** for
breakout/retest (**BY** / DW) simulation only — buys are on **retest**, not on DI as an entry gate.
See ``sheet_column_reference.py``.

**Sheet column names vs Excel:** see ``stock_analysis/sheet_column_reference.py``. Internal
``_ak_at`` is support-test overlap math (not Excel **AK**); **AQ** on the sheet is *Exit type*, not used here as a buy gate.

**Entry gates (sheet vs program):** see ``stock_analysis/ENTRY_GATES_SHEET_VS_PROGRAM.md``.

Implements the Rocket BRT system from the specs:
- Level 1: Pivot High/Low detection (k±bars, m confirmation, d displacement)
- Level 2: Market structure (HH/HL/LH/LL, major pivots)
- Level 3: Touch stream, zone bands, sheet-lag or touch-count maturity, buy signal

Outputs to drive directory:
- BRT_Closed: All closed trades with entry, exit, PnL, etc. (includes POST_ENTRY_GAIN_HIT: gain% in trade direction in-window while open,
  DATE_FIRST_UP_10PCT, DAYS_HELD_FIRST_UP_10PCT, DATE_FIRST_UP_20PCT, DAYS_HELD_FIRST_UP_20PCT,
  LAST_ATH_DATE_AT_ENTRY,
  TRADING_DAYS_SINCE_LAST_ATH_AT_ENTRY, HAD_METEORIC_RISE_BEFORE_ENTRY, HAD_METEORIC_FALL_BEFORE_ENTRY,
  REJECTION_COUNT_PRIOR, OVERLAPPING_MATURE_ZONES_COUNT, REL_VOL_AT_BREAKOUT).
- BRT_Open: Currently held positions (includes POST_ENTRY_GAIN_HIT vs entry, same window as config)
- BRT_Scanner: Symbols that passed entry gates on the last bar of history (no room to simulate the trade
  in-sample). CLOSE = signal-bar close; STOP_LOSS/TARGET are guesstimated from that close (same ATR/% rules
  as live entries, which fill at next open). Omitted when there are no scanner candidates.
- BRT_Watchlist: Scanner rows plus pending maturities still open at end of history, with heuristic
  gates_remaining / trigger hints (not a full gate replay), plus optional APPROACHING_RETEST rows
  (growth OK + price near matured zone + first retest not yet printed in-sample).
- IND_Watchlist (indicator_buy=only): IND_DIFF / IND_SCORE vs entry gates, trend (5/20 bar deltas),
  row types SCANNER | NEAR_GATE | IMPROVING | STALLED | FADING; no zone pending or APPROACHING_RETEST.
  SCANNER = symbol appears in IND_Scanner (backtest entry signal on last bar); not merely pass_all on indicators.
  Optional IND_Watchlist_TopN_<ts>.csv when ind_watchlist_top_n > 0.
- BRT_Summary: Stock-by-stock view (trades, PnL total/avg, current market cap when yfinance ran)
- BRT_Report: CSV with settings and metrics (one row of headers, one row of data)
- BRT_breakout_and_retest_<ts>.csv: Every DI breakout (BM-style) and first overlapping retest (BY-style) per symbol

When run with a single stock, optionally generates a chart with bands.
"""
from __future__ import annotations

import argparse
import contextlib
import cProfile
import csv
import json
import math
import os
import pickle
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Set, get_origin, get_args, get_type_hints

import numpy as np
import pandas as pd

try:
    from sheet_column_reference import ENTRY_GATE_SHEET_TITLES
except ImportError:
    from stock_analysis.sheet_column_reference import ENTRY_GATE_SHEET_TITLES

try:
    from ohlcv_store import (
        filter_symbols_to_universe as _db_filter_symbols_to_universe,
        list_symbols as _db_list_symbols,
        load_symbol_df as _db_load_symbol_df,
        resolve_db_path as _db_resolve_path,
        symbol_bar_counts as _db_symbol_bar_counts,
    )
except ImportError:
    try:
        from stock_analysis.ohlcv_store import (
            filter_symbols_to_universe as _db_filter_symbols_to_universe,
            list_symbols as _db_list_symbols,
            load_symbol_df as _db_load_symbol_df,
            resolve_db_path as _db_resolve_path,
            symbol_bar_counts as _db_symbol_bar_counts,
        )
    except ImportError:
        _db_list_symbols = None
        _db_load_symbol_df = None
        _db_resolve_path = None
        _db_symbol_bar_counts = None
        _db_filter_symbols_to_universe = None

try:
    from brt_pipeline_instrumentation import BRTPipelineInstrument, default_instrument_db_path
except ImportError:
    try:
        from stock_analysis.brt_pipeline_instrumentation import (
            BRTPipelineInstrument,
            default_instrument_db_path,
        )
    except ImportError:
        BRTPipelineInstrument = None  # type: ignore[misc, assignment]
        default_instrument_db_path = None  # type: ignore[misc, assignment]

# Optional: matplotlib for charting
try:
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

# Optional: equity metrics (Max_DD, underwater) from BRT_DrawdownCalc
try:
    from BRT_DrawdownCalc import (
        compute_equity_metrics as _compute_equity_metrics,
        generate_underwater_report as _generate_underwater_report,
    )

    HAS_EQUITY_METRICS = True
except ImportError:
    _compute_equity_metrics = None  # type: ignore[misc, assignment]
    _generate_underwater_report = None  # type: ignore[misc, assignment]
    HAS_EQUITY_METRICS = False

# ============== CONFIGURATION ==============
@dataclass
class BRTConfig:
    """Rocket BRT configuration (matches spec).

    Google Sheet cell mapping (workbook BRT tab), when aligning to spreadsheet:
    - C7  → tight_range_threshold_pct (program-only compression gate; **AI** = Range Qualifier on sheet is **not** in **AL** buy)
    - C10 → strong post-pivot bars; AZ:BB = INDEX(AB/AC/AD, ROW()-C10) (matured lag)
    - C14 → periods to check; AB touch pullback uses MIN(Low[t+1:t+C14]) vs High[t] (not C10)
    - sheet_maturity_lag_bars: 0 = use strong_post_pivot_bars (same as C10 on sheet)
    - C24 → tight_range_lookback (lookback bar count; **not** sheet **BC** = ATH filter)
    - C27 → entry_close_min_range_position (BE: close >= low + (high-low)*C27)
    """
    # Level 1: Pivot Detection (local extrema + displacement confirm)
    pivot_k: int = 4      # Local structure window: ±k bars to identify local high/low
    pivot_d: int = 7      # Displacement confirm window: next d bars to check for price move
    pivot_disp: float = 0.06  # Displacement threshold: 6% move required to confirm pivot
    pivot_m: int = 4      # Dedup lookback: ignore pivots within m bars of same-price prior pivot

    # Level 3: Key levels
    band_pct: float = 0.0154  # Sheet C5 Band variable (1.54%)
    # When > 0: zone half-width as fraction of touch_price = (band_pct_atr * ATR14) / touch_price at the pivot bar
    # (same units as band_pct). When 0, use band_pct only.
    band_pct_atr: float = 0.0
    lookback_long: int = 504
    # "touch_count": matured_now when touch_count_long >= threshold (legacy).
    # "sheet_lag": matured_now pulses lag bars after each strong touch (BF=INDEX(AF,ROW()-C10)); threshold ignored for maturity.
    zone_maturity_model: str = "sheet_lag"
    touch_threshold: int = 2  # Used when zone_maturity_model == "touch_count"; also exported for audit / TKL math
    # Strong Pivot Qualification (STONK_DATA 3.0): pre = lookback-only (realtime-safe); post = follow-through ahead
    strong_pivots_enabled: bool = True  # When True, only strong pivots create zones/touches
    strong_pre_pivot_bars: int = 7  # Sheet "strong Pre-Pivot bars" (C17) — lookback window ending before pivot bar
    strong_pre_pivot_pct: float = 0.081  # Sheet C13 strong Pre-Pivot move % (8.1%)
    # When > 0: pre threshold = (strong_pre_pivot_pct_atr * ATR14) / pivot_price at the pivot bar (else strong_pre_pivot_pct).
    strong_pre_pivot_pct_atr: float = 0.0
    strong_post_pivot_bars: int = 7  # Sheet C10 — Post Pivot Pullback (K) window + matured lag (AZ:BB)
    strong_post_pivot_pct: float = 0.108  # Sheet C15 Strong post-pivot move % (10.8% touch pullback)
    # Sheet C14 "periods to check" — forward Low window for AB Touch Price pullback (distinct from C10).
    sheet_touch_pullback_bars: int = 10
    # When > 0: post threshold = (strong_post_pivot_pct_atr * ATR14) / pivot_price at the pivot bar (else strong_post_pivot_pct).
    strong_post_pivot_pct_atr: float = 0.0
    # "pre" = AE/AD-style lookback only; "post" = legacy forward follow-through; "both" = require pre AND post
    strong_pivot_mode: str = "both"
    # Strong pivot **low** zones: when True, zone center/touch price uses min(Low) over the last
    # strong_pre_pivot_bars bars through the pivot bar (widens zone downward vs pivot-bar low only).
    # Ignored when strong_pivots_enabled is False or realtime_filter_enabled is True.
    zone_include_pre_strong_pivot_lows: bool = False
    # When True (default with brt_zones), Touch Price / matured ladder follow the BRT sheet
    # (Final Pivot High + Pre-strong pivot High + forward pullback), not strong_pivot_mode filter.
    brt_sheet_touch: bool = True
    brt_sheet_warmup_bars: int = 9  # Sheet formulas blank when ROW()<=9
    # MTS parity: also emit pivot-LOW touches (sheet AF low branch: Final Pivot Low +
    # pre-strong low AE + forward-rise pullback >= C15). BRT ladder is PH-only; MTS uses both.
    mts_zone_low_touches: bool = False
    # When False, pivot-low rows do not emit touch_price / zone bands (PH-only ladder).
    zones_from_pivot_lows_enabled: bool = False
    # Zone source toggles: pivot-based BRT ladder vs Year-High (52w) retest ladder vs VEC confluence.
    # Default YH-only mode: brt_zones=False, yh_zones=True (outputs use YH_ prefix).
    # VEC-only: vec_zones=True, brt_zones=False, yh_zones=False (outputs use VEC_ prefix).
    # Set brt_zones=True to merge pivot zones with YH zones (BRT_ prefix unless brt_zones-only).
    brt_zones: bool = False
    yh_zones: bool = True
    vec_zones: bool = False
    # PBR — Pivot Break and Retest (weekly pivot zones, weekly BO, daily retest entry).
    pbr_zones: bool = False
    pbr_breakout_confirmation: float = 0.03  # Weekly high > zone_upper * (1 + this)
    pbr_max_days_after_retest: int = 2  # Entry window after retest bar (inclusive)
    # When True: after a profitable first purchase from a zone, allow exactly one more purchase
    # then retire. When False (default): retire the zone after the first purchase (win or loss).
    pbr_second_chance_after_win: bool = False
    # --- VEC (Volume + prior-period Extreme Confluence) ---
    vec_vp_lookback: int = 60  # Trading days for volume-profile POC window.
    vec_vp_bin_pct: float = 0.005  # Histogram bin width as fraction of median price (~0.5%).
    vec_prior_bars: int = 5  # Prior-period length in sessions (5 ≈ prior week on daily bars).
    vec_prior_side: str = "high"  # high | low — extreme to compare against POC (high = resistance retest).
    vec_confluence_pct: float = 0.0075  # Max |POC - extreme| / extreme for confluence (0.75%).
    vec_move_away_pct: float = 0.02  # Min rally above zone center before activation (0 = same bar).
    vec_min_bars_between: int = 20  # Dedup: min bars between activations at similar center.
    # Rocket Launcher (50-SMA dip buy): true/false (separate run from BRT zone/retest).
    # true → RL_ output prefix; AWK math is authoritative (docs/RL_ENGINE_INTEGRATION.md).
    rl_mode: str = "false"
    rl_cash: float = 47_500.0  # RL_CASH notional per trade (AWK default)
    rl_flush_days: int = 0  # Portfolio underwater flush (0=off); two-pass when >0
    rl_watch_min_score: int = 55  # RL_Watchlist minimum setup score (AWK WATCH_MIN_SCORE)
    rl_watch_disable: bool = False  # If true, RL_Watchlist header only
    # --- RL engine params (portfolio_audit.awk 50-trigger; all overridable via -v) ---
    rl_sma_qual: bool = True  # AWK SMA_QUAL
    rl_dip_pct: float = 1.024
    rl_50_sma_lookback: int = 4
    rl_stop_pct: float = 0.934
    rl_target_pct: float = 1.20
    rl_too_high: float = 1.14
    rl_expansion: float = 1.163
    rl_acc_min: int = 8
    rl_acc_count: int = 10
    rl_expansion_lookback_days: int = 10
    rl_cut_the_losers: float = 0.25
    rl_atr_low_percent: float = 0.0244
    rl_atr_high_percent: float = 0.0848
    rl_atr_high_value: float = 200.0
    rl_low_price: float = 0.000001
    rl_peak_threshold_max: float = 2.0
    rl_slope_period: int = 30
    rl_slope_threshold: float = 0.0643  # 0 = off (AWK)
    rl_shock_threshold: float = 0.0
    rl_shock_rehab_days: int = 120
    rl_shock_max_allowed: int = 1
    rl_trail_profit: float = 0.0
    rl_trail_stop: float = 0.0
    rl_trail_profit2: float = 0.0
    rl_trail_stop2: float = 0.0
    rl_exit_percent: float = 0.29
    rl_exit_days: int = 10000
    rl_partial_exit_target: float = 0.0
    rl_partial_exit_percent: float = 0.50
    rl_partial_exit_follow_target: float = 0.1
    rl_spy_inclusion: bool = False  # AWK SPY_INCLUSION (50>100>200 on entry day)
    rl_avg_vol_days: int = 50  # AWK AVG_VOL_DAYS (0=off)
    rl_vol_pct_threshold: float = 0.0  # AWK VOL_PCT_THRESHOLD (0=off)
    # When true, optional BRT entry gates (min_spy_compare_*, growth_filter, etc.) may filter RL entries.
    rl_brt_entry_gates_enabled: bool = False
    yh_lookback: int = 252  # Trading days for rolling 52-week high detection.
    yh_move_away_pct: float = 0.03  # Min rally above YH before zone activates (3% baseline).
    # YH candidate memory: sheet = live spreadsheet handoff (default); fifo = queued promote; parallel = every YH independent.
    yh_memory_mode: str = "sheet"
    yh_serial_memory: bool = True  # Legacy: -v yh_serial_memory maps to fifo/parallel when yh_memory_mode not set in -v.
    # Pending entry window in bars after touch event row (sheet-style current/prior => 1)
    close_above_window: int = 1
    # Strategy mode: evaluate entries from breakout/retest Retest Date rows only (no touch-event pending queue).
    entry_from_retest_only: bool = True
    # Safety TTL for pending maturities to prevent very stale zones from lingering forever.
    pending_max_bars: int = 252
    # Entry evaluation mode:
    # - pending: evaluate from pending maturities (legacy behavior)
    # - row_local: sheet-style current/prior touch-event eligibility only
    entry_eval_mode: str = "row_local"
    # row_local behavior: when True, allow evaluating maturity events on the same bar
    # (instead of always deferring maturity_bar==i to next bar).
    row_local_eval_touch_same_bar: bool = False
    # Row-local: how many extra bars (after the first post-touch eval day) a pending maturity
    # may stay alive for entry gates. Default 0 = strict sheet-style (one eval day only: i-M<=1);
    # DI/DW often need several bars — use 60–252 for MSFT-style parity with a multi-day sheet queue.
    row_local_eval_ttl_bars_after_first_eval: int = 60
    # Row-local active-zone context filter:
    # When True, require pending maturity_bar to match the row's active DN context.
    # When False (default), do not hard-skip by active context mismatch; downstream
    # AQ/BG/DP/DO gates decide eligibility from row formulas.
    row_local_require_active_context_match: bool = False
    level_acceptance_window: int = 10  # When enabled: N bars ending on trigger day for legacy 7/10-style gate
    level_acceptance_required: int = 0  # 0=off (sheet AL does not use this; sheet BG is matured touch price). Use --level-acceptance 7/10 to enable legacy gate
    # Support Test (internal ladder / AK-style overlap path). Used for optional legacy level_acceptance anchors.
    support_test_enabled: bool = True
    # Legacy level_acceptance anchor modes (only if level_acceptance_required > 0):
    # strict = Support Test on current or prior bar; rolling = any ST in recent window.
    level_acceptance_anchor_mode: str = "strict"
    level_acceptance_anchor_window: int = 10
    breakout_bars: int = 100  # AP: MAX(close over breakout_bars) > active zone upper

    # Tight Range Qualifier: block levels that mature in structurally compressed environments
    tight_range_enabled: bool = False
    tight_range_threshold_pct: float = 0.35  # Sheet C7: RangePct must exceed this (35% default)
    tight_range_lookback: int = 105  # Sheet C24: lookback length (program window ends on maturity_bar; not column AI/BC)

    # Tradeable Key Level: level must be historically mature AND recently active
    # Legacy / optional; spreadsheet no longer uses Tradeable Key Level (TKL); default off.
    tradeable_key_level_enabled: bool = False
    lookback_short: int = 199  # Short window for touch_count_short (recent engagement)

    # Consolidation Blocker: suppress entries in tight consolidation boxes
    consolidation_blocker_enabled: bool = False
    cb_max_box_width_pct: float = 0.35  # Max allowed (box_ceiling / box_floor - 1) for CB to be active. use 9999 for no limit

    # Touch count filters at entry: gate by TC and TC_MIN (None = no filter)
    min_touch_count: Optional[int] = 0  # Require touch_count >= N (0 = no op). Audit: TOUCH_COUNT
    max_touch_count_minor: Optional[int] = 100  # Require touch_count_minor <= N (e.g. 1 for TC_MIN <= 1)
    max_touch_count_short: Optional[int] = None  # Require touch_count_short <= N (0 = no short-window touches). Audit: TOUCH_COUNT_SHORT
    max_ind_entry_neutral_n: Optional[int] = None  # Require IND_ENTRY_NEUTRAL_N <= N at trigger bar close (None = off)
    # Exit: sell at next session open when trade-aligned IND_DIFF on prior bar is < N (None = off).
    sell_ind_diff_below: Optional[int] = None
    # When True (requires sell_ind_diff_below), IND_DIFF exit is the only exit (no stop/target/trailing/ATR schedule).
    exit_ind_diff_only: bool = False
    min_ind_entry_bull_n: Optional[int] = None  # Require IND_ENTRY_BULL_N >= N at trigger bar close (None = off)
    # Entry filters (minimums; no-op when at default)
    min_pivot_run_l_before_entry: int = 0  # Require pivot_run_low >= this (0 = no op). Audit: PIVOT_RUN_L_BEFORE_ENTRY
    min_pivot_run_h_before_entry: int = 0  # Require pivot_run_high >= this (0 = no op). Audit: PIVOT_RUN_H_BEFORE_ENTRY
    min_rel_vol_at_entry: float = -2.0  # Require rel_vol_at_entry >= this (-2 = no op). Audit: REL_VOL_AT_ENTRY
    # Exit at next session open when REL_VOL_AT_ENTRY (entry-day volume) is below this. 0 = off.
    sell_on_low_vol: float = 0.0
    min_market_cap: float = 0.0  # Require trade market_cap >= this (0 = no op). Applied after enrichment. Audit: MARKET_CAP
    max_market_cap: float = 15130840772900 # Require trade market_cap <= this when >0 (0 = no op). Applied after enrichment.
    min_hist_ann_ror_avg: float = -100.0  # Require prior closed trades for symbol and avg ann ROR >= this (-100 = no op). Audit: HIST_ANN_ROR_AVG
    min_avg_volume_10d_at_entry: float = 0.0  # Require AVG_VOLUME_10D_AT_ENTRY >= this when >0 (0 = no op).
    min_atr_pct_at_trigger: float = 0.0  # Require ATR_PCT_AT_TRIGGER (ATR14/trigger_close*100) >= this when >0 (0 = no op).
    max_atr_pct_at_trigger: float = 0.0  # Require ATR_PCT_AT_TRIGGER <= this when >0 (0 = no op).
    # Distance below 52w high at trigger bar close: (max High over 252 bars through trigger - trigger close) / high * 100.
    min_dist_to_52w_high_pct_at_trigger: float = 0.0  # Require DIST >= this when >0 (0 = no op). 0% = at the high.
    max_dist_to_52w_high_pct_at_trigger: float = 0.0  # Require DIST <= this when >0 (0 = no op).
    # Excess total return vs SPY at trigger (SPY_COMPARE_* percentage points); 0 = off.
    # Negative mins are valid (e.g. -12 requires SPY_COMPARE_1Y >= -12). Use 0 or -1000 to disable.
    min_spy_compare_1y_at_trigger: float = 50.0
    max_spy_compare_1y_at_trigger: float = 0.0
    min_spy_compare_2y_at_trigger: float = 0.0
    min_spy_compare_3y_at_trigger: float = 0.0
    # Rolling beta vs SPY at trigger bar (calculated, not yfinance); 0 = off.
    min_beta_at_trigger: float = 0.0
    max_beta_at_trigger: float = 0.0
    # UPPER_WICK_ATR_AT_TRIGGER = (High - max(Open,Close)) / ATR14 at trigger; 0 = off.
    min_upper_wick_atr_at_trigger: float = 0.0
    pivot_switch_h_to_l_filter: int = -1  # -1 = no op, 0 = require pivot_switch==False, 1 = require True. Audit: PIVOT_SWITCH_H_TO_L
    # Tri-state (string): true | false | both — matches BRT_Closed ENTRY_MAJOR_PIVOT / IS_20BAR_HIGH_AT_TRIGGER (1/0).
    # ``both`` = no filter. Pass via -v entry_filter_major_pivot=both (or true / false).
    entry_filter_major_pivot: str = "True"  # true => require ENTRY_MAJOR_PIVOT==1; false => ==0
    entry_filter_is_20bar_high_at_trigger: str = "False"  # true => require flag==1; false => ==0 (not at 20-bar high)
    entry_filter_meteoric_rise: str = "both"  # true => HAD_METEORIC_RISE_BEFORE_ENTRY==1; false => ==0
    entry_filter_meteoric_fall: str = "both"  # true => HAD_METEORIC_FALL_BEFORE_ENTRY==1; false => ==0

    # Trade direction
    # transaction_type controls which strategy streams run:
    # - long: long entries only
    # - short: short entries only
    # - both: run both and merge output rows
    transaction_type: str = "long"
    # entry_type is the active side for a single stream (used by per-side internals).
    # Allowed: long | short.
    entry_type: str = "long"
    # Zone role handling (enforced in DI/retest selection + touch-maturity pending, not RS mode):
    # - dynamic: any zone can produce long or short breakouts/retests (default).
    # - by_origin: longs only on PH/YH-origin (resistance) bands; shorts only on PL-origin (support) bands,
    #   using zone_touch_origin (1=PH, 2=PL, 3=YH). Optional override flips all bands to one role.
    zone_role_mode: str = "dynamic"
    zone_role_override: str = ""  # "", support, resistance, both

    # Risk
    brt_cash: float = 47500
    initial_capital: float = 500000
    stop_pct: float = 0.934  # Sheet 6.6% below entry when stop_pct_is_multiplier (entry × 0.934)
    stop_pct_is_multiplier: bool = True  # True: stop=entry*stop_pct (e.g. 0.934 = 6.6% below entry). False: entry*(1-stop_pct)
    # Stop anchor: "entry" = stop off entry_price (default). "signal_low" = sheet AM = signal-bar Low * (1-C4),
    # i.e. Low[signal_bar] * stop_pct (multiplier) or Low[signal_bar] * (1 - stop_pct). Long side only.
    stop_anchor: str = "entry"
    # If >= 0, round stop comparison prices to this many decimals for stop/gap-stop checks.
    # 2 matches spreadsheet cents-based stop hit checks (default).
    stop_compare_round_decimals: int = 2
    target_pct: float = 1.21  # Multiplier above entry (1.29=29% above)
    # When True (and atr_target==0), long target = SMA(50) * target_pct at entry bar; short uses SMA(50) * short_target formula.
    use_sma50: bool = False
    # Short-side defaults mirror long-side counterparts.
    # short_stop_pct uses same multiplier/fraction semantics as stop_pct with stop_pct_is_multiplier.
    short_stop_pct: float = 0.95
    # short_target_pct defaults to the same multiplier magnitude as target_pct.
    short_target_pct: float = 1.18
    # ATR-based stop/target: when BOTH stop_pct and target_pct are 0, sheet uses atr_* instead.
    atr_target: float = 0.0   # 0=use target_pct. Non-zero: target = entry * (1 + ATR_PCT_AT_ENTRY * atr_target / 100)
    # If 0 while atr_target>0, percent stop uses stop_pct; if stop_pct is also 0 the engine applies default entry×0.934.
    atr_stop: float = 0.0     # 0=use stop_pct path. Non-zero: stop = entry * (1 - ATR_PCT_AT_ENTRY * atr_stop / 100)
    # 0=no trailing. Non-zero: stop is raised by (gain_from_entry%% / trailing_stop_increment) * 1%% of entry above
    # the initial stop, where gain_from_entry uses peak high since entry (fractional steps, not floored).
    trailing_stop_increment: float = 0.0
    # ATR schedule exits (need atr_days>0): calendar-day deadline from entry date.
    # (1) atr_progress>0 — at first open after (entry_date + atr_days), exit unless High reached
    # entry*(1+atr_progress*ATR_PCT_AT_ENTRY/100) on bars from entry through prior bar.
    # (2) atr_progress==0 — timed flat at that same first open after the deadline.
    atr_progress: float = 0.0
    atr_days: int = 0
    # Final entry gate: block when next open is "too high" above trigger-bar low.
    # Example default 1.14 means block if entry_open > trigger_low * 1.14.
    too_high_multiplier: float = 1.058
    # Final entry floor: block when next open is below prior session close * too_low_multiplier.
    # 0 disables (no floor). Long: min buy open = prior_close * too_low_multiplier.
    too_low_multiplier: float = 0.0
    # Optional: after atr_days deadline, treat atr_progress threshold as a stop floor
    # (entry * (1 + atr_progress*ATR_PCT_AT_ENTRY/100)) for regular stop checks.
    atr_progress_incremental_stop: bool = False
    # SMA trailing stop floor: 0=off. When >0 and price is on the favorable side of SMA(N),
    # working stop = max(long) / min(short) of other stops and SMA(N); never loosens.
    sma_stop_days: int = 0
    days_per_year: float = 365.0

    # Exit: when stop is hit, use close of that bar instead of stop_price (matches some manual conventions)
    exit_at_close_when_stopped: bool = False

    # Growth filter: require full lookback and Close[eval] >= Close[eval - growth_bars] (sheet: 3Y).
    # Sheet anchors 756 rows from 2016-01-01; CSVs may start a few sessions later — see growth_history_slack_bars.
    growth_filter_enabled: bool = True
    growth_bars: int = 756  # e.g. 756 = 3 years; require Close[entry] >= Close[entry - growth_bars]
    growth_history_slack_bars: int = 2  # allow eval when eval_bar >= growth_bars - slack (sheet row vs CSV start)

    # Signal-bar candle direction: long requires Close>Open; short requires Close<Open. Set False to skip.
    require_close_gt_open: bool = True
    # Sheet **AH** *BRT Rocket buy*: prior bar Close<=Open and eval bar Close>Open ($H7<=$E7, $H8>$E8).
    sheet_red_to_green_entry_enabled: bool = True
    # Entry candle BE: after close > open, optionally require close in upper part of the bar.
    # Sheet C27 default 1e-7: AND(H>E, H>=G+(F-G)*C27) => (close-low)/(high-low) >= C27 (effectively above the low).
    # 0 = skip this check (bullish only). 0.5 = close in upper half: (close-low)/(high-low) >= 0.5.
    entry_close_min_range_position: float = 0.00001
    # Sheet zone parity: round High/Low to this many decimals for strong-pivot (AD/AE/AF) gates and touch prices;
    # -1 disables (raw floats in strong gates; can disagree with Sheets on marginal post/pre %).
    zone_price_round_decimals: int = 2
    # Sheet overlap parity: round OHLC and zone bounds before overlap/support/resistance checks.
    # Also rounds prior/current breakout_px and each BI[j] in BM/DI (_precompute_di_all_zones_breakout).
    # Example: 2 means low=3.3867 and zone_high=3.3864 compare as 3.39 <= 3.39.
    zone_compare_round_decimals: int = 2

    # MTS sheet parity: store zone lower/upper as full tp*(1±C5) (no ROUND to cents) and compare
    # raw OHLC vs CE/CF in active-zone overlap / AK (sheet FILTER does not ROUND first).
    # Pivot/touch gates still use zone_price_round_decimals for High/Low.
    mts_overlap_full_precision: bool = False

    # CE/CF / CD: INDEX(AG/AH/AF, ROW()-lag). On sheet, lag = C10 (strong post-pivot bars). 0 => use strong_post_pivot_bars.
    sheet_maturity_lag_bars: int = 0
    # --- Sheet DO / DP parity gates ---
    # DO parity: recent pre-only strong pivot touch must exist within N rows (C30-style "pre-touch good for").
    do_gate_enabled: bool = False
    do_good_for_bars: int = 3
    # DP parity: current price must be inside ANY matured zone CE/CF in [row-C10 .. row-lag].
    # lag = effective sheet maturity lag (sheet C10; sheet_maturity_lag_bars or strong_post_pivot_bars).
    dp_gate_enabled: bool = False
    dp_window_bars: int = 0  # 0 => use lookback_long
    dp_good_for_bars: int = 2
    # --- Sheet BH:BI "all zones" DI / BY retest (see sheet_column_reference) ---
    # BM/DI: prior price < BI[j] and current price >= BI[j]; sheet rows use **Close** (not High) for this test.
    # BM/DI breakout detection (Close vs BI or High vs BI): feeds BY/DW retest simulation only — **not** a buy gate.
    sheet_di_breakout_price: str = "close"  # "close" = sheet BM parity; "high" = legacy intraday highs
    # Require the **eval row** date (same bar as close>open / _eval_bar) in the set of **first BY retest**
    # overlap days (same as column **Retest Date** in BRT_breakout_and_retest CSV — not **Breakout Date**).
    # COUNTIF($BY:$BY, $D_eval) > 0; no multi-bar window.
    sheet_dw_countif_entry_enabled: bool = True
    # Sheet BY parity (optional): when True with ``sheet_dw_countif_entry_enabled``, expand the simulated BY
    # date set so each **Retest Date** also adds the **next trading session** after that retest (equivalent to
    # letting the bullish eval row on the session after retest match COUNTIF without a separate prior-bar OR).
    # Default False: sheet ``COUNTIF($BO:$BO,$D)>0`` requires eval date in the retest ledger (not the next session).
    # Set True only if your workbook expands BY dates to the session after each retest touch.
    sheet_dw_countif_include_prior_bar_date: bool = False
    # Sheet: no new entry signal on the same bar a position is closed (exit then flat; buy next bar+).
    sheet_no_entry_same_bar_after_exit: bool = True
    # When several DI breakouts share the same first-retest day, ``retest_rows_by_iso`` has multiple rows.
    # ``all`` = enqueue one synthetic pending per row (legacy). ``lowest`` / ``highest`` = keep one band for entry:
    # lowest = smallest zone_lower (deepest band); highest = largest zone_upper (top of highest band).
    retest_multi_zone_pick: str = "all"
    # When True, skip **TKL** and **consolidation blocker** on long entry (retest + bullish + growth path).
    entry_retest_bullish_growth_only: bool = False
    # Cap DI scan history (bars); 0 = scan all prior rows j < i.
    sheet_di_max_history_bars: int = 0
    # BRT_breakout_and_retest CSV: Excel row number for bar index i is i + sheet_excel_first_data_row (default 2).
    sheet_excel_first_data_row: int = 2
    # Scan Start Row minus Main Row on compact BRT tab (default 3; tuned vs MSFT sheet export).
    sheet_breakout_scan_start_row_delta: int = 2
    # Sheet AW parity ("magic touch event"):
    # When enabled, maturity/touch events are generated from AR/AW semantics:
    # - CD = lagged confirmed touch price (post-confirmed strong pivot) by effective sheet lag (C10)
    # - AR[t] = count of CD in [DE[t], DF[t]] over last sheet_magic_touch_window_bars
    # - AW: sheet_lag uses AR>=1 (first lagged CD in active zone); touch_count uses AR>=touch_threshold
    sheet_magic_touch_enabled: bool = True
    sheet_magic_touch_window_bars: int = 0  # 0 => use lookback_long (e.g. 503)
    # --- MTS sheet mode (STONK_DATA BI / DK–DO); enable via --mts-sheet-parity or mts_mode=true ---
    mts_mode: bool = False
    # MTS DP "First touch after availability": create the entry candidate on the first bar price
    # enters a (persistent, full-history) matured zone, or when the active zone ID changes.
    # DP = DO AND (NOT DO[-1] OR DN<>DN[-1]); DO = active zone exists AND row>maturity row.
    # Each active-zone episode fires one candidate (no re-entry on every touch). Requires
    # use_sheet_active_zone_ctx. When on, this supersedes the AR/AW magic-touch pending creator.
    mts_first_touch_entry: bool = False
    # AM (Support Evidence) config: window (0 -> use lookback_long / C10=503) and min AK count.
    # Sheet AM = COUNTIFS(AK, DN) over C10 >= C6 (same touch_threshold as AR/AW).
    mts_support_evidence_window_bars: int = 0
    mts_support_evidence_min: int = 3
    # Active-zone memory depth (sheet DK ladder rungs). 0 = unlimited ("zones live forever");
    # set to 10 to exactly replicate the sheet's CG..DH 10-rung cap (newest-matured-wins).
    mts_active_zone_max_rungs: int = 0
    # Active-zone pick among overlapping matured zones (unlimited scan mode only).
    # maxj = newest maturity row (legacy); hybrid_overlap_low = overlap-only max DN unless
    # within slack of low-inside max DN, then low-inside max DN;
    # maxj_lowin_ov_slack = maxj unless low-inside max-j with overlap-only max DN more than slack higher.
    mts_active_zone_pick_mode: str = "maxj"
    mts_active_zone_hybrid_dn_slack: int = 2
    # Debug: capture the per-bar active-zone arrays (DK/DL/DM/DN) into a module global for
    # validation against the sheet ground truth (see tools/parse_nvda_zone_truth.py).
    debug_dump_active_zones: bool = False
    use_sheet_active_zone_ctx: bool = False
    sheet_active_zone_asof_lag_bars: int = 0
    sheet_active_zone_asof_age_adjust_bars: int = 0
    sheet_use_dg_slot_for_zone_identity: bool = True
    sheet_rocket_buy_mode: bool = False
    sheet_start_date: str = "2019-01-01"
    sheet_growth_ok_mode: bool = False
    ath_filter_c25: float = 0.3
    ath_filter_c26: float = 0.6
    zone_eligible_long_gate_enabled: bool = False
    zone_eligible_long_or_prior_bar: bool = False
    tight_range_window_end: str = "maturity_bar"  # maturity_bar | eval_bar (MTS BC)
    tight_range_or_prior_bar: bool = False
    level_acceptance_use_high: bool = False
    level_acceptance_window_use_eval_bar: bool = False

    # Rolling Average Displacement filter: require price sufficiently away from recent average (avoid stuck/equilibrium)
    displacement_filter_enabled: bool = False
    displacement_rolling_bars: int = 100  # Rolling window for average of closes
    displacement_threshold_pct: float = 0.1 # Min displacement: ABS(Close/RollingAvg100 - 1) >= this (e.g. 0.10 = 10%)

    # Metrics: when True, compute Max_Drawdown etc. via equity reconstruction (BRT_DrawdownCalc)
    compute_equity_metrics: bool = True
    # Relative strength entry: single gate = stock total return vs SPY over 252/504/756 bars (all strictly greater).
    # When True, skips zone/pivot/retest entry stack; still uses same stop/target/exit simulation as BRT.
    # SPY.csv must exist in the data directory. SPY_COMPARE_* columns are logged for every trade when SPY is aligned.
    relative_strength_enabled: bool = False
    aggressive: bool = False
    aggressive_margin_interest: float = 0.10
    aggressive_max_multiple: float = 2.0
    aggressive_avg_positions: float = 0.0
    aggressive_sizing_equity_cap: float = 10.0
    # When aggressive: sell existing holdings at new-entry open to free gross/cash.
    # false | average | losers | winners
    aggressive_sell: str = "false"
    # Fraction of total margin buying power to deploy (equity * aggressive_max_multiple).
    # Default 0.6 = 60% of 2× account. --aggressive forces 1.0 (use full margin).
    margin_utilization: float = 0.6
    # Slot budget for per-trade notional: deployable_margin / max_positions. 0 = auto from peak concurrent closed trades.
    max_positions: int = 0
    # When True with --aggressive: skip writing passive Equity_Regular CSV (passive Max_DD still computed).
    equity_fast_aggressive: bool = False
    # Calendar days to wait after closing a symbol before allowing a new entry in that symbol (0 = off).
    symbol_reentry_cooldown_days: int = 0
    # When True, allow a new entry in a symbol while another position in that symbol is still open.
    allow_secondary_entries: bool = False

    # When True, record maturities rejected only by growth/tight_range/consolidation to BRT_WouldHave CSV (for DrawdownCalc zone chart)
    emit_would_have: bool = False

    # Real-time predictive filter (offline analysis / optional gating at entry)
    realtime_filter_enabled: bool = False
    # Expensive: rolling beta precompute over full history per symbol (when SPY benchmark is loaded).
    # When True, fills BETA_AT_ENTRY on trades / BRT_Closed. Also implied when weight_beta_at_entry != 0.
    compute_beta: bool = False
    # When True, append IND_* / IND_*_LAST and IND_ENTRY_* summary columns to BRT_Closed / BRT_Open (see brt_entry_indicators.py).
    use_indicators: bool = False
    # Sum IND_SCORE weights for each IND_<id> that is BULL at entry (weights from ind_score_weights.json).
    use_ind_score: bool = True
    ind_score_weights_path: str = ""  # empty = canonical ind_score_weights_<stamp>.json (same file until weights change)
    # Require IND_SCORE >= threshold at entry (price-BULL weights). 0 = filter off.
    min_ind_score: float = 0.0  # Require IND_SCORE >= this at trigger bar close (0 = filter off).
    # Require IND_* states from JSON on the trigger bar. Set path to filename to enable; "" = off.
    mandatory_ind_states_path: str = ""
    # Entry tri-state using trade-aligned IND counts (bull - bear) at the entry bar open (bar _i_bar+1):
    # off = default (no indicator gate); only = IND-only entry (IND_DIFF >= indicator_diff, no zone/retest/RS);
    # both = zone/retest path + require diff >= indicator_diff and run sheet + programmatic gates.
    indicator_buy: str = "off"
    indicator_diff: int = 10  # Minimum trade-aligned IND_DIFF at trigger bar close (indicator_buy only/both).
    # When True, the IND entry gate threshold becomes the per-date cross-sectional average trade-aligned
    # IND_DIFF across the run universe (built in a parent pre-pass) instead of the static indicator_diff.
    # A signal qualifies only when its trigger-bar IND_DIFF >= that date's universe average.
    use_average_ind: bool = False
    # When True (with use_average_ind), require BOTH gates: trigger-bar IND_DIFF >= indicator_diff
    # AND >= that date's universe average. Effective threshold = max(indicator_diff, avg).
    # When False, use_average_ind replaces the static threshold with the average (avg-only).
    average_ind_combine: bool = False
    # Runtime-only carrier populated by the parent when use_average_ind is True:
    # {YYYYMMDD (trigger date): mean trade-aligned IND_DIFF across the run universe that day}.
    # Not user-settable via -v in practice; omitted from the audit report.
    avg_ind_diff_by_date: Optional[dict] = None
    # Which sides use the indicator gate when indicator_buy is only/both: long | short | both.
    # Empty = auto: indicator_buy=only -> both (long on bullish-aligned diff, short on bearish-aligned diff);
    # indicator_buy=both -> long only. Trade-aligned diff uses entry_type per stream (see brt_entry_indicators).
    indicator_sides: str = ""
    # Log [IND-GATE] lines for indicator_buy only/both (useful with -w 0 -s SYM; noisy on full universe).
    trace_indicator_buy: bool = False
    # IND watchlist (indicator_buy=only): lookbacks and inclusion thresholds.
    ind_watchlist_lookback_short: int = 5
    ind_watchlist_lookback_long: int = 20
    ind_watchlist_near_diff_gap: int = 3
    ind_watchlist_near_score_gap: float = 5.0
    ind_watchlist_improve_diff_delta: int = 2
    ind_watchlist_improve_score_delta: float = 1.0
    ind_watchlist_max_rows: int = 250
    ind_watchlist_top_n: int = 50
    ind_watchlist_stalled_max_diff_gap: int = 12
    ind_watchlist_stalled_max_score_gap: float = 12.0
    # SCANNER row: require min_atr_pct_at_trigger on prospective signal bar (not entry open).
    ind_watchlist_scanner_requires_atr: bool = True
    # SCANNER row: AS_OF_DATE must match universe latest session (drop stale last-bar symbols).
    ind_watchlist_scanner_require_latest_asof: bool = True
    # Within this many ATR pct points of min_atr counts as "near" for NEAR_GATE when indicators pass.
    # NEAR_GATE when ATR below min_atr_pct_at_trigger but within this many pct points of the gate.
    ind_watchlist_atr_near_pct: float = 1.0
    # Per-symbol indicator precompute disk cache (see brt_entry_indicators.py); empty dir = data_dir/.brt_indicator_cache.
    indicator_cache: bool = True
    indicator_cache_dir: str = ""
    realtime_filter_threshold: float = 0  # Sum of weighted metrics must be >= this to allow entry
    realtime_filter_use_zscore: bool = True  # If True and BRT_ReferenceStats.csv exists, weight z-scores so scale of metrics doesn't dominate
    # Per-metric weights (typically set from correlation r or R_Total; use with z-score normalization so scale of metrics doesn't dominate)
    #weight_zone_cluster_density: float = -0.0724
    #weight_nearby_zones_above: float = -0.0655
    # Examples of tuned realtime weights from correlation studies (paste into ReferenceStats CSV or pass -v key=value).
    # weight_pct_entry_to_bottom_zone_above: float = 0.5964744717
    #weight_z_score_at_trigger: float = -0.0896
    #weight_displacement_pct_at_entry: float = 0.1008
    #weight_pct_drop_to_top_zone_below: float = 0.1708
    #weight_growth_pct_over_period: float = 0.1221
    #weight_beta_at_entry: float = 0.0961
    #weight_touch_count_minor: float = -0.0827
    #weight_nearby_zones_below: float = -0.0679


    # Additional weights for real-time filter (all known at entry; DISPLACEMENT_PCT = |Close/RollingAvg-1| at maturity bar)
    weight_pivot_run_l_before_entry: float = 0.0
    weight_rel_vol_at_entry: float = 0.0
    weight_lower_wick_atr_at_trigger: float = 0.0
    weight_zone_cluster_density: float = 0.0
    weight_nearby_zones_above: float = 0.0
    weight_touch_count_major: float = 0.0
    weight_pct_entry_to_bottom_zone_above: float = 0.0
    weight_touch_count_minor: float = 0.0
    weight_displacement_pct_at_entry: float = 0.0
    weight_pct_drop_to_top_zone_below: float = 0.0
    weight_nearby_zones_below: float = 0.0
    weight_z_score_at_trigger: float = 0.0
    weight_growth_pct_over_period: float = 0.0
    weight_beta_at_entry: float = 0.0

    # Meteoric move history: cumulative flags through entry bar (see _precompute_meteoric_cumulative_flags).
    # Optional entry gates: entry_filter_meteoric_rise / entry_filter_meteoric_fall (true | false | both).
    meteoric_rise_pct: float = 300.0  # Close >= N-day min Low * (1 + this/100)
    meteoric_rise_lookback: int = 100  # N trading bars for the low window
    meteoric_fall_pct: float = 50.0  # Close <= Y-day max High * (1 - this/100)
    meteoric_fall_lookback: int = 100  # Y trading bars for the high window
    # Post-entry path study (BRT_Closed / BRT_Open / audit): max High vs entry from entry through
    # min(entry + post_entry_gain_calendar_days, exit date); open trades have no exit cap. 0 = disabled.
    post_entry_gain_pct: float = 20.0
    post_entry_gain_calendar_days: int = 75

    def to_dict(self) -> dict[str, Any]:
        return {
            "BRT_TRANSACTION_TYPE": self.transaction_type,
            "BRT_ENTRY_TYPE": self.entry_type,
            "BRT_ZONE_ROLE_MODE": self.zone_role_mode,
            "BRT_ZONE_ROLE_OVERRIDE": self.zone_role_override or "(derive)",
            "BRT_PIVOT_K": self.pivot_k,
            "BRT_PIVOT_M": self.pivot_m,
            "BRT_BAND_PCT": self.band_pct,
            "BRT_LOOKBACK_LONG": self.lookback_long,
            "BRT_TOUCH_THRESHOLD": self.touch_threshold,
            "BRT_CLOSE_ABOVE_WINDOW": self.close_above_window,
            "BRT_LEVEL_ACCEPTANCE": f"{self.level_acceptance_required}/{self.level_acceptance_window}" if self.level_acceptance_required else "off",
            "BRT_TIGHT_RANGE": f"{self.tight_range_threshold_pct:.0%}" if self.tight_range_enabled else "off",
            "BRT_GROWTH_FILTER": f"on (price>=price_{self.growth_bars}d_ago)" if self.growth_filter_enabled else "off",
            "BRT_DISPLACEMENT_FILTER": f"on (|Close/RollingAvg{self.displacement_rolling_bars}-1|>={self.displacement_threshold_pct:.0%})" if self.displacement_filter_enabled else "off",
            "BRT_CASH": self.brt_cash,
            "BRT_STOP_PCT": self.stop_pct,
            "BRT_SHORT_STOP_PCT": self.short_stop_pct,
            "BRT_STOP_PCT_IS_MULTIPLIER": self.stop_pct_is_multiplier,
            "BRT_TARGET_PCT": self.target_pct,
            "BRT_SHORT_TARGET_PCT": self.short_target_pct,
            "EXIT_AT_CLOSE_WHEN_STOPPED": self.exit_at_close_when_stopped,
        }


def mts_sheet_parity_overrides() -> dict[str, Any]:
    """Config overrides for MTS sheet parity (STONK_DATA MTS tab, columns D:DP).

    **MTS buy (BI)** — NOT the BRT retest pipeline::

        BI = AND(
            BW Growth 3 Year,              # Close >= Close[756 bars ago]
            OR(BC, BC[-1]),                # Range Qualifier (eval or prior bar)
            BE Close above open,           # Close > Open
            BG Level Acceptance,           # 7 closes above DK in last 10 bars (needs AK)
            OR(AQ, AQ[-1]),                # Zone Eligible Long (eval or prior bar)
        )

    **When to evaluate** — DP first touch after availability (not AW magic touch)::

        DO = active zone exists AND row > maturity row
        DP = DO AND (NOT DO[-1] OR DN <> DN[-1])

    AW (AR>=C6 crossing) still counts touches but does **not** gate BC or create entries.
    **no** BY/DV retest-day COUNTIF (that is BRT/YH only).

    Zones: sheet AF Touch Price stream (pivot-high AND pivot-low), matured C14=7 bars
    later (CD:CF), active zone DK:DN from 10-rung ladder overlap.

  Exits: target = entry*(1+C3); stop = signal-bar Low*(1-C4) (``stop_anchor="signal_low"``).
    """
    return {
        "mts_mode": True,
        "brt_zones": True,
        "yh_zones": False,
        # --- MTS zone ladder = sheet AF Touch Price stream (pivot-high AND pivot-low) ---
        "brt_sheet_touch": True,
        "mts_zone_low_touches": True,
        "zone_maturity_model": "sheet_lag",
        "sheet_touch_pullback_bars": 7,   # AF forward window = C14 (Strong post-pivot bars)
        "sheet_active_zone_asof_lag_bars": 7,
        "indicator_buy": "off",
        "relative_strength_enabled": False,
        "sheet_red_to_green_entry_enabled": False,
        # --- MTS BI buy gate (no retest pipeline) ---
        "use_sheet_active_zone_ctx": True,
        "sheet_rocket_buy_mode": True,
        "sheet_dw_countif_entry_enabled": False,
        "entry_from_retest_only": False,
        "entry_eval_mode": "row_local",
        "strong_pivot_mode": "both",
        # DP: first touch after availability. Zones persist forever (full-history active zone);
        # each zone episode fires ONE entry candidate on first touch (or when active zone changes).
        "mts_first_touch_entry": True,
        # Unlimited zone memory: scan all CE:CF matured zones (sheet DK/DL/DM/DN via FILTER).
        "mts_active_zone_max_rungs": 0,
        # Evaluate the BI gate on the first-touch bar itself (entry at next open), not deferred.
        "row_local_eval_touch_same_bar": True,
        # DP supersedes AR/AW magic touch as the entry trigger.
        "sheet_magic_touch_enabled": False,
        # --- MTS BI buy gate: exact precompute (_precompute_mts_bi_gates) is authoritative. ---
        # BI = AND(BW, OR(BC[i],BC[i-1]), BE, BG, OR(AQ[i],AQ[i-1])). The engine's approximate
        # BRT gates below are disabled/bypassed; the C-cell numeric params are KEPT because the
        # exact precompute reads them from cfg (tight_range_*, level_acceptance_*, lookback_long,
        # growth_bars).
        #
        # BW Growth 3 Year (Close[i] >= Close[i-756]) -> handled inside BI precompute.
        "sheet_growth_ok_mode": False,
        "growth_filter_enabled": False,   # redundant engine gate (runs outside skip guard); BI's BW is authoritative
        "growth_bars": 756,               # read by _precompute_mts_bi_gates (BW)
        # BE Close above open -> handled inside BI precompute.
        "require_close_gt_open": False,   # redundant engine gate (runs outside skip guard); BI's BE is authoritative
        # BC Range Qualifier params (read by BI precompute): (MAX(H)/MIN(L) over C24 -1) > C7.
        "tight_range_enabled": False,     # engine approximation bypassed; BI precompute owns BC
        "tight_range_threshold_pct": 0.35,  # C7 (read by BI precompute)
        "tight_range_lookback": 105,        # C24 (read by BI precompute)
        # BG Level Acceptance params (read by BI precompute): C8(7) of C9(10) closes above DK anchor.
        "support_test_enabled": False,      # engine approximation bypassed; BI precompute owns BG
        "level_acceptance_required": 7,     # C8 (read by BI precompute)
        "level_acceptance_window": 10,      # C9 (read by BI precompute)
        # AQ Zone Eligible Long (AM: >=3 AK support tests for same zone id in C10) -> BI precompute.
        "zone_eligible_long_gate_enabled": False,  # engine approximation bypassed; BI precompute owns AQ
        # Neutralize gates NOT in MTS BI
        "min_spy_compare_1y_at_trigger": 0.0,
        "min_spy_compare_2y_at_trigger": 0.0,
        "min_spy_compare_3y_at_trigger": 0.0,
        "max_spy_compare_1y_at_trigger": 0.0,
        "min_beta_at_trigger": 0.0,
        "max_beta_at_trigger": 0.0,
        "min_upper_wick_atr_at_trigger": 0.0,
        "too_high_multiplier": 0.0,
        "too_low_multiplier": 0.0,
        "entry_filter_major_pivot": "both",
        "entry_filter_is_20bar_high_at_trigger": "both",
        "entry_filter_meteoric_rise": "both",
        "entry_filter_meteoric_fall": "both",
        "max_market_cap": 0.0,
        "use_sma50": False,
        "displacement_filter_enabled": False,
        "consolidation_blocker_enabled": False,
        "dp_gate_enabled": False,
        "do_gate_enabled": False,
        # Sheet C3 target exit: entry * (1 + C3); reference wins cap at +22%.
        "target_pct": 1.22,
        # Sheet BJ stop: signal-bar Low * (1 - C4) = Low * 0.934 (not entry-anchored).
        "stop_anchor": "signal_low",
        "stop_pct": 0.934,
        "stop_pct_is_multiplier": True,
        # --- Sheet A1:C27 pivot / zone constants (NVDA) ---
        "band_pct": 0.02,          # C5
        "touch_threshold": 2,      # C6 touch points (AR/AW threshold and AM AK COUNTIFS >= C6)
        "lookback_long": 503,      # C10
        "lookback_short": 199,     # C11
        "breakout_bars": 100,      # C16
        "pivot_k": 4,              # C23 pivot_local_window_bars
        "pivot_disp": 0.06,        # C21 pivot_future_move_pct
        "pivot_m": 4,
        "strong_pre_pivot_bars": 7,      # C17
        "strong_pre_pivot_pct": 0.12,    # C18
        "strong_post_pivot_bars": 7,     # C14
        "strong_post_pivot_pct": 0.09,   # C15 AF touch pullback / forward-rise threshold (9%)
        "ath_filter_c25": 0.3,     # C25 knockout_low_mult
        "ath_filter_c26": 0.6,     # C26 knockout_high_mult
        "sheet_start_date": "2016-01-01",  # C2 Start Date
        # Full-precision CE/CF bounds + raw OHLC overlap (sheet FILTER); pivots still use ROUND(OHLC,2).
        "mts_overlap_full_precision": True,
    }


# Debug capture of the most recent active-zone arrays (DK/DL/DM/DN); populated by
# run_brt_backtest when cfg.debug_dump_active_zones is True. Used by validation tooling.
_LAST_ACTIVE_ZONE_ARRAYS: Optional[tuple] = None


# ============== LEVEL 1: PIVOT DETECTION ==============
# Zone cluster neighborhood radius for nearby-zone counts (±5% around trigger zone_center)
_ZONE_CLUSTER_PCT = 0.05

# Pivot dedup: price tolerance for "same price" duplicate detection
_PIVOT_DEDUP_EPS = 0.01  # 1% tolerance


def _normalize_entry_filter_tri_state(val: Any, label: str = "") -> str:
    """
    Tri-state for entry filters aligned with BRT_Closed 0/1 flags.
    - ``true``: require flag == 1
    - ``false``: require flag == 0
    - ``both`` (and ``any``, ``either``, ``all``, ``none``, ``off``, empty): no filter
    """
    if val is True:
        return "true"
    if val is False:
        return "false"
    s = str(val if val is not None else "both").strip().lower()
    if s in ("both", "any", "either", "all", "none", "off", ""):
        return "both"
    if s in ("true", "t", "1", "yes", "on"):
        return "true"
    if s in ("false", "f", "0", "no"):
        return "false"
    print(
        f"[BRT] Unknown {label or 'entry_filter'} mode {val!r}; using 'both' (no filter).",
        file=sys.stderr,
    )
    return "both"


def _entry_filter_tri_state_blocks(flag_value: int, mode: str) -> bool:
    """True if tri-state entry filter rejects this flag (1=yes history, 0=no)."""
    m = _normalize_entry_filter_tri_state(mode)
    fv = int(flag_value or 0)
    if m == "true" and fv != 1:
        return True
    if m == "false" and fv != 0:
        return True
    return False


def _normalize_transaction_type(val: Any) -> str:
    s = str(val if val is not None else "long").strip().lower()
    if s in ("long", "short", "both"):
        return s
    print(f"[BRT] Unknown transaction_type {val!r}; using 'long'.", file=sys.stderr)
    return "long"


def _normalize_entry_type(val: Any) -> str:
    s = str(val if val is not None else "long").strip().lower()
    if s in ("long", "short"):
        return s
    print(f"[BRT] Unknown entry_type {val!r}; using 'long'.", file=sys.stderr)
    return "long"


def _snapshot_entry_indicators_for_trade(
    pre: Any,
    entry_bar_index: int,
    side: str,
) -> dict[str, str]:
    """Point-in-time IND_* snapshot for a trade (uses backtest precompute when available)."""
    if pre is None or entry_bar_index < 0:
        return {}
    try:
        from brt_entry_indicators import snapshot_for_entry
    except ImportError:
        from stock_analysis.brt_entry_indicators import snapshot_for_entry
    return snapshot_for_entry(pre, entry_bar_index, side) or {}


def _output_file_prefix(cfg: "BRTConfig") -> str:
    """RL when rl_mode=true; IND when indicator_buy=only; MTS when mts_mode; VEC/YH when zone-only; else BRT."""
    if bool(getattr(cfg, "mts_mode", False)):
        return "MTS"
    if _rl_mode_active(getattr(cfg, "rl_mode", "false")):
        return "RL"
    if _normalize_indicator_buy(getattr(cfg, "indicator_buy", "off")) == "only":
        return "IND"
    _brt_on = bool(getattr(cfg, "brt_zones", False))
    _yh_on = bool(getattr(cfg, "yh_zones", True))
    _vec_on = bool(getattr(cfg, "vec_zones", False))
    _pbr_on = bool(getattr(cfg, "pbr_zones", False))
    if _pbr_on and not _brt_on and not _yh_on and not _vec_on:
        return "PBR"
    if _vec_on and not _brt_on and not _yh_on:
        return "VEC"
    if _yh_on and not _brt_on:
        return "YH"
    return "BRT"


def _zone_origin_label(origin_code: int) -> str:
    """Human-readable zone_touch_origin for zone debug CSVs."""
    oc = int(origin_code)
    if oc == 1:
        return "PH"
    if oc == 2:
        return "PL"
    if oc == 3:
        return "YH"
    if oc == 4:
        return "VEC"
    return ""


def _indicator_mode_active(cfg: "BRTConfig") -> bool:
    """True when indicator snapshots / gates / while-held output should run."""
    return bool(getattr(cfg, "use_indicators", False)) or _normalize_indicator_buy(
        getattr(cfg, "indicator_buy", "off")
    ) in ("only", "both")


def _cfg_sell_ind_diff_threshold(cfg: "BRTConfig") -> Optional[int]:
    """Parsed sell_ind_diff_below (None = feature off)."""
    raw = getattr(cfg, "sell_ind_diff_below", None)
    if raw is None or (isinstance(raw, str) and not str(raw).strip()):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        print(f"[BRT] Invalid sell_ind_diff_below {raw!r}; ignoring.", file=sys.stderr)
        return None


def _arm_ind_diff_exit_if_signal(
    *,
    threshold: int,
    sym_indicator_pre: Any,
    aligned_fn: Any,
    bar_i: int,
    side: str,
) -> bool:
    """True when IND_DIFF at ``bar_i`` is below threshold (exit next session open)."""
    if sym_indicator_pre is None or aligned_fn is None or bar_i < 0:
        return False
    diff = aligned_fn(sym_indicator_pre, bar_i, side)
    if diff is None:
        return False
    return int(diff) < int(threshold)


def _low_rel_vol_exit_at_open(
    open_trade: "BRTTrade",
    bar_i: int,
    sell_on_low_vol: float,
) -> bool:
    """Exit at this bar's open when entry day is complete and REL_VOL_AT_ENTRY < threshold."""
    if sell_on_low_vol <= 0.0:
        return False
    entry_bar = int(getattr(open_trade, "entry_bar_index", -1) or -1)
    if entry_bar < 0 or bar_i != entry_bar + 1:
        return False
    rv = getattr(open_trade, "rel_vol_at_entry", None)
    if rv is None:
        return False
    try:
        return float(rv) < float(sell_on_low_vol)
    except (TypeError, ValueError):
        return False


def _append_indicators_while_held_row(
    rows_out: Optional[list],
    *,
    sym: str,
    trade: "BRTTrade",
    bar_i: int,
    index_iso: list[str],
    pre: Any,
    close_arr: Optional[np.ndarray] = None,
) -> None:
    """One daily row of trade-aligned IND summary counts while a position is open."""
    if rows_out is None or pre is None or bar_i < 0:
        return
    side = str(getattr(trade, "side", "LONG") or "LONG")
    try:
        from brt_entry_indicators import aligned_bull_bear_diff, entry_bull_n, entry_neutral_n
    except ImportError:
        from stock_analysis.brt_entry_indicators import aligned_bull_bear_diff, entry_bull_n, entry_neutral_n
    bull_n = entry_bull_n(pre, bar_i, side)
    neut_n = entry_neutral_n(pre, bar_i, side)
    diff = aligned_bull_bear_diff(pre, bar_i, side)
    if bull_n is None or neut_n is None or diff is None:
        return
    bear_n = int(bull_n) - int(diff)
    date_iso = index_iso[bar_i] if 0 <= bar_i < len(index_iso) else ""
    hold_date = (
        f"{date_iso[:4]}-{date_iso[4:6]}-{date_iso[6:8]}" if len(date_iso) >= 8 else date_iso
    )
    d_open = str(getattr(trade, "date_opened", "") or "")
    d_close = str(getattr(trade, "date_closed", "") or "")
    hold_close = ""
    if close_arr is not None and 0 <= bar_i < len(close_arr):
        _hc = float(close_arr[bar_i])
        if np.isfinite(_hc):
            hold_close = f"{_hc:.4f}"
    exit_px = float(getattr(trade, "exit_price", 0.0) or 0.0)
    exit_price_s = f"{exit_px:.4f}" if d_close else ""
    rows_out.append(
        {
            "SYMBOL": sym,
            "SIDE": side.upper(),
            "DATE_OPENED": d_open,
            "DATE_CLOSED": d_close,
            "ENTRY_PRICE": f"{float(getattr(trade, 'entry_price', 0.0) or 0.0):.4f}",
            "EXIT_PRICE": exit_price_s,
            "HOLD_DATE": hold_date,
            "HOLD_DAY_CLOSE": hold_close,
            "IND_ENTRY_BULL_N": str(int(bull_n)),
            "IND_ENTRY_BEAR_N": str(int(bear_n)),
            "IND_DIFF": str(int(diff)),
            "IND_ENTRY_NEUTRAL_N": str(int(neut_n)),
        }
    )


def _collect_indicators_while_held_for_trades(
    rows_out: Optional[list],
    *,
    sym: str,
    closed: list["BRTTrade"],
    open_trade: Optional["BRTTrade"],
    index_iso: list[str],
    pre: Any,
    close_arr: Optional[np.ndarray] = None,
) -> None:
    """Day-by-day IND summary counts for each bar from entry through exit (or EOD if still open)."""
    if rows_out is None or pre is None:
        return
    trades: list[BRTTrade] = list(closed)
    if open_trade is not None:
        trades.append(open_trade)
    if not trades or not index_iso:
        return
    n_bars = len(index_iso)
    for trade in trades:
        start_bar = int(getattr(trade, "entry_bar_index", -1) or -1)
        if start_bar < 0:
            mapped = _trade_ymd_to_bar_index(index_iso, str(getattr(trade, "date_opened", "") or ""))
            start_bar = int(mapped) if mapped is not None else -1
        if start_bar < 0:
            continue
        date_closed = str(getattr(trade, "date_closed", "") or "").strip()
        if date_closed:
            end_mapped = _trade_ymd_to_bar_index(index_iso, date_closed)
            end_bar = int(end_mapped) if end_mapped is not None else n_bars - 1
        else:
            end_bar = n_bars - 1
        end_bar = min(max(end_bar, start_bar), n_bars - 1)
        for bar_i in range(start_bar, end_bar + 1):
            _append_indicators_while_held_row(
                rows_out,
                sym=sym,
                trade=trade,
                bar_i=bar_i,
                index_iso=index_iso,
                pre=pre,
                close_arr=close_arr,
            )


def _normalize_indicator_buy(val: Any) -> str:
    s = str(val if val is not None else "off").strip().lower()
    if s in ("off", "only", "both"):
        return s
    print(f"[BRT] Unknown indicator_buy {val!r}; using 'off'.", file=sys.stderr)
    return "off"


def _rl_mode_active(val: Any) -> bool:
    s = str(val if val is not None else "false").strip().lower()
    if s in ("true", "on", "yes", "1", "only"):  # "only" legacy alias
        return True
    if s in ("false", "off", "no", "0", ""):
        return False
    print(f"[BRT] Unknown rl_mode {val!r}; using false.", file=sys.stderr)
    return False


def _normalize_rl_mode(val: Any) -> str:
    return "true" if _rl_mode_active(val) else "false"


def _normalize_indicator_sides(val: Any) -> str:
    s = str(val if val is not None else "").strip().lower()
    if s in ("long", "short", "both"):
        return s
    if s:
        print(f"[BRT] Unknown indicator_sides {val!r}; using 'long'.", file=sys.stderr)
    return "long"


def _default_indicator_sides(indicator_buy: str, explicit: str) -> str:
    """Auto sides when indicator_sides is unset: only -> both streams; both -> long stream only."""
    if explicit in ("long", "short", "both"):
        return explicit
    if indicator_buy == "only":
        return "both"
    return "long"


def _apply_indicator_sides_to_cfg(cfg: "BRTConfig", indicator_buy: str) -> "BRTConfig":
    """
    When indicator_buy is only/both, align transaction_type with indicator_sides.
    both = run long + short streams (short uses bearish-aligned diff >= indicator_diff).
    """
    if indicator_buy not in ("only", "both"):
        return cfg
    raw = str(getattr(cfg, "indicator_sides", "") or "").strip().lower()
    if raw in ("long", "short", "both"):
        sides = raw
    else:
        sides = _default_indicator_sides(indicator_buy, "")
    tt = _normalize_transaction_type(getattr(cfg, "transaction_type", "long"))
    if sides == "both":
        if tt != "both":
            cfg = replace(cfg, transaction_type="both", indicator_sides=sides)
            print(
                "[BRT] indicator_sides=both: transaction_type=both — LONG when trade-aligned "
                f"IND diff >= {int(getattr(cfg, 'indicator_diff', 10) or 10)} (bullish); SHORT when diff >= "
                "threshold (bearish-aligned); indicator_buy=only uses IND-only bar scan (no zone/retest).",
                flush=True,
            )
        else:
            cfg = replace(cfg, indicator_sides=sides)
    elif sides == "short":
        if tt != "short":
            cfg = replace(cfg, transaction_type="short", entry_type="short", indicator_sides=sides)
            print(
                "[BRT] indicator_sides=short: transaction_type=short (bearish-aligned IND diff gate).",
                flush=True,
            )
        else:
            cfg = replace(cfg, indicator_sides=sides)
    else:
        cfg = replace(cfg, indicator_sides=sides)
        if tt == "both" and indicator_buy == "only":
            print(
                "[BRT] indicator_sides=long with indicator_buy=only: only the LONG stream uses the "
                "indicator gate; set indicator_sides=both for shorts on bearish-aligned diff.",
                file=sys.stderr,
            )
    return cfg


def _normalize_aggressive_sell(val: Any) -> str:
    s = str(val or "false").strip().lower()
    if s in ("false", "off", "0", "none", ""):
        return "false"
    if s in ("average", "avg", "equal"):
        return "average"
    if s in ("losers", "loser", "worst"):
        return "losers"
    if s in ("winners", "winner", "best"):
        return "winners"
    return "false"


def _normalize_zone_role_mode(val: Any) -> str:
    s = str(val if val is not None else "dynamic").strip().lower()
    if s in ("dynamic", "by_origin"):
        return s
    print(f"[BRT] Unknown zone_role_mode {val!r}; using 'dynamic'.", file=sys.stderr)
    return "dynamic"


def _normalize_zone_role_override(val: Any) -> str:
    """Optional override for zone semantic role: '' | support | resistance | both."""
    s = str(val if val is not None else "").strip().lower()
    if s in ("", "support", "resistance", "both"):
        return s
    print(f"[BRT] Unknown zone_role_override {val!r}; using '' (derive from pivot origin).", file=sys.stderr)
    return ""


def _effective_zone_role(origin_code: int, zone_role_override: str) -> str:
    """
    Map pivot origin + override to a semantic role.
    origin_code: 0 unknown, 1 pivot-high zone, 2 pivot-low zone, 3 year-high zone, 4 VEC confluence.
    Default without override: PH/YH/VEC -> resistance, PL -> support; unknown -> both (non-blocking).
    """
    ov = _normalize_zone_role_override(zone_role_override)
    if ov == "support":
        return "support"
    if ov == "resistance":
        return "resistance"
    if ov == "both":
        return "both"
    if int(origin_code) in (1, 3, 4):
        return "resistance"
    if int(origin_code) == 2:
        return "support"
    return "both"


def _zone_role_allows_entry(zone_role_mode: str, effective_role: str, entry_side: str) -> bool:
    """
    When zone_role_mode is by_origin, long entries use resistance (PH) zones; short entries use support (PL) zones.
    effective_role 'both' matches either side. dynamic mode skips this filter (always True).
    """
    if _normalize_zone_role_mode(zone_role_mode) != "by_origin":
        return True
    er = str(effective_role or "").strip().lower()
    if er == "both":
        return True
    es = _normalize_entry_type(entry_side)
    if es == "long":
        return er == "resistance"
    return er == "support"


def _zone_origin_code_for_sheet_column(zone_origin_at_bar: np.ndarray, column_bar: int, sheet_lag: int) -> int:
    """
    BH/BI at spreadsheet row ``column_bar`` copies zl/zh from the pivot bar ``column_bar - sheet_lag``
    (see _precompute_mat_bh_bi_stream). Map DI column index -> pivot source bar -> origin code.
    """
    lag = max(0, int(sheet_lag))
    src = int(column_bar) - lag
    if src < 0 or src >= len(zone_origin_at_bar):
        return 0
    return int(zone_origin_at_bar[src])


def _near(a: float, b: float, eps: float = _PIVOT_DEDUP_EPS) -> bool:
    """Price within ±eps: abs(a/b - 1) <= eps."""
    if b == 0:
        return a == 0
    return abs(a / b - 1.0) <= eps


def _effective_sheet_maturity_lag_bars(cfg: Any) -> int:
    """
    Spreadsheet lag for BF/BG/BH and CD/CE/CF ladder inputs (INDEX(..., ROW()-C10)).
    When sheet_maturity_lag_bars > 0, use it; otherwise inherit strong_post_pivot_bars (sheet C10).
    """
    v = int(getattr(cfg, "sheet_maturity_lag_bars", 0) or 0)
    if v > 0:
        return v
    sp = int(getattr(cfg, "strong_post_pivot_bars", 0) or 0)
    return max(0, sp)


def _growth_history_slack_bars(cfg: Any) -> int:
    return max(0, int(getattr(cfg, "growth_history_slack_bars", 0) or 0))


def _growth_min_eval_bar_index(cfg: Any) -> int:
    """Minimum eval bar index before growth filter runs (sheet row count vs CSV start)."""
    gb = int(getattr(cfg, "growth_bars", 0) or 0)
    if gb <= 0:
        return 0
    return max(0, gb - _growth_history_slack_bars(cfg))


def _growth_ago_bar_index(eval_bar: int, cfg: Any) -> int:
    """Bar index for growth comparison close; -1 if insufficient history."""
    gb = int(getattr(cfg, "growth_bars", 0) or 0)
    if gb <= 0:
        return -1
    if eval_bar < _growth_min_eval_bar_index(cfg):
        return -1
    ago = eval_bar - gb
    return 0 if ago < 0 else ago


def compute_pivots(
    df: pd.DataFrame,
    k: int,
    d: int,
    disp: float,
    m: int,
    realtime_filter_enabled: bool = False,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """
    Pivot Detection: local extrema + displacement confirm + duplicate blocker.
    
    Filter 1 (this function): Identifies potential pivot points
    - Pivot High: bar where High is the maximum in ±k bars window
      AND price drops at least disp% within next d bars
    - Pivot Low: bar where Low is the minimum in ±k bars window
      AND price rises at least disp% within next d bars
    - Dedup: ignores pivots within m bars of a prior pivot at same price (±1%)
    
    Parameters:
        k: Local structure window (±k bars to identify local high/low)
        d: Displacement confirm window (next d bars to check for move)
        disp: Displacement threshold (e.g., 0.06 = 6% move required)
        m: Dedup lookback (ignore pivots within m bars of same-price prior pivot)
    """
    n = len(df)
    hi = np.asarray(df["High"].values, dtype=np.float64)
    lo = np.asarray(df["Low"].values, dtype=np.float64)
    # Round to 2 decimal places to match spreadsheet precision for pivot detection
    hi = np.round(hi, 2)
    lo = np.round(lo, 2)
    pivot_high = np.zeros(n, dtype=np.float64)
    pivot_low = np.zeros(n, dtype=np.float64)
    ph_price = np.zeros(n, dtype=np.float64)
    pl_price = np.zeros(n, dtype=np.float64)

    for t in range(k, n - d):
        lo_t = lo[t]
        hi_t = hi[t]

        # Local window [t-k, t+k] inclusive
        lo_win = lo[t - k : t + k + 1]
        hi_win = hi[t - k : t + k + 1]
        lo_min = np.min(lo_win)
        hi_max = np.max(hi_win)

        # First determine local-extrema status
        is_local_low = lo_t == lo_min
        is_local_high = hi_t == hi_max

        # If this bar is BOTH local high and local low, treat as no pivot at all
        if is_local_low and is_local_high:
            continue

        if not realtime_filter_enabled:
            # Pivot Low: local min + displacement confirm + no duplicate
            if is_local_low:
                # Displacement confirm: price must rise at least disp% within next d bars
                future_max_high = np.max(hi[t + 1 : t + d + 1])
                displacement_ok = (future_max_high / lo_t - 1.0) >= disp
                if displacement_ok:
                    dup = False
                    for j in range(max(0, t - m), t):
                        if pivot_low[j] == 1 and _near(pl_price[j], lo_t):
                            dup = True
                            break
                    if not dup:
                        pivot_low[t] = 1
                        pl_price[t] = lo_t

            # Pivot High: local max + displacement confirm + no duplicate
            if is_local_high:
                # Displacement confirm: price must drop at least disp% within next d bars
                future_min_low = np.min(lo[t + 1 : t + d + 1])
                displacement_ok = (future_min_low / hi_t - 1.0) <= -disp
                if displacement_ok:
                    dup = False
                    for j in range(max(0, t - m), t):
                        if pivot_high[j] == 1 and _near(ph_price[j], hi_t):
                            dup = True
                            break
                    if not dup:
                        pivot_high[t] = 1
                        ph_price[t] = hi_t
        else:
            # Real-time mode: no future displacement; use only local extrema + dedup
            # Pivot Low: local min + no duplicate
            if is_local_low:
                dup = False
                for j in range(max(0, t - m), t):
                    if pivot_low[j] == 1 and _near(pl_price[j], lo_t):
                        dup = True
                        break
                if not dup:
                    pivot_low[t] = 1
                    pl_price[t] = lo_t

            # Pivot High: local max + no duplicate
            if is_local_high:
                dup = False
                for j in range(max(0, t - m), t):
                    if pivot_high[j] == 1 and _near(ph_price[j], hi_t):
                        dup = True
                        break
                if not dup:
                    pivot_high[t] = 1
                    ph_price[t] = hi_t

    return (
        pd.Series(pivot_high, index=df.index),
        pd.Series(pivot_low, index=df.index),
        pd.Series(ph_price, index=df.index),
        pd.Series(pl_price, index=df.index),
    )


# ============== LEVEL 2: MARKET STRUCTURE ==============
def compute_market_structure(
    df: pd.DataFrame,
    pivot_high: pd.Series,
    pivot_low: pd.Series,
    ph_price: pd.Series,
    pl_price: pd.Series,
) -> dict:
    """Compute HH/HL/LH/LL labels and major pivots."""
    n = len(df)
    ph_arr = (pivot_high.values == 1)
    pl_arr = (pivot_low.values == 1)
    php = ph_price.values
    plp = pl_price.values
    struct_hi = np.empty(n, dtype=object)
    struct_lo = np.empty(n, dtype=object)
    struct_hi[:] = ""
    struct_lo[:] = ""
    major_ph = np.zeros(n, dtype=np.float64)
    major_pl = np.zeros(n, dtype=np.float64)

    last_ph = last_pl = None
    ph_idxs = np.where(ph_arr)[0]
    pl_idxs = np.where(pl_arr)[0]

    for j in ph_idxs:
        _ph = php[j]
        if last_ph is not None:
            struct_hi[j] = "HH" if _ph > last_ph else "LH"
        last_ph = _ph
    last_pl = None
    for j in pl_idxs:
        _pl = plp[j]
        if last_pl is not None:
            struct_lo[j] = "HL" if _pl > last_pl else "LL"
        last_pl = _pl

    for j in ph_idxs:
        next_pl = ""
        for j2 in pl_idxs:
            if j2 > j:
                next_pl = struct_lo[j2]
                break
        major_ph[j] = 1 if next_pl == "LL" else 0
    for j in pl_idxs:
        next_ph = ""
        for j2 in ph_idxs:
            if j2 > j:
                next_ph = struct_hi[j2]
                break
        major_pl[j] = 1 if next_ph == "HH" else 0

    return {
        "structure_high": pd.Series(struct_hi, index=df.index),
        "structure_low": pd.Series(struct_lo, index=df.index),
        "major_pivot_high": pd.Series(major_ph, index=df.index),
        "major_pivot_low": pd.Series(major_pl, index=df.index),
    }


# ============== DEBUG CONFIGURATION ==============
_DEBUG_SYMBOL: Optional[str] = None  # Set to e.g. "ATUSF" to enable debug logging
_DEBUG_DATE: Optional[str] = None    # Set to e.g. "2022-07-26" to focus on specific date
_TRACE_DATES: set[str] = set()       # Exact eval-bar dates YYYYMMDD to trace gate-by-gate
_TRACE_SYMBOL: Optional[str] = None  # Optional symbol filter for trace dates


def set_debug_target(symbol: Optional[str], date: Optional[str]):
    """Enable debug logging for a specific symbol and date."""
    global _DEBUG_SYMBOL, _DEBUG_DATE
    _DEBUG_SYMBOL = symbol
    _DEBUG_DATE = date


def set_trace_target(symbol: Optional[str], dates: list[str] | None) -> None:
    """Enable exact-date gate tracing on evaluation bars (YYYY-MM-DD or YYYYMMDD)."""
    global _TRACE_DATES, _TRACE_SYMBOL
    _TRACE_SYMBOL = symbol.upper() if symbol else None
    out: set[str] = set()
    for d in (dates or []):
        s = str(d).strip()
        if not s:
            continue
        if len(s) >= 10 and s[4] == "-":
            ymd = s[:10].replace("-", "")
        else:
            ymd = "".join(ch for ch in s if ch.isdigit())[:8]
        if len(ymd) == 8:
            out.add(ymd)
    _TRACE_DATES = out


def _strong_pivot_mode_has_active_params(
    mode: str,
    pre_bars: int,
    pre_pct: float,
    post_bars: int,
    post_pct: float,
    *,
    pre_pct_atr: float = 0.0,
    post_pct_atr: float = 0.0,
) -> bool:
    """Return True if strong_pivot_mode is configured with positive bars/pct for that mode."""
    m = (mode or "pre").strip().lower()
    pre_on = pre_bars > 0 and (pre_pct > 0 or pre_pct_atr > 0)
    post_on = post_bars > 0 and (post_pct > 0 or post_pct_atr > 0)
    if m == "pre":
        return pre_on
    if m == "post":
        return post_on
    if m == "both":
        return pre_on and post_on
    if m in ("either", "any"):
        return pre_on or post_on
    # Unknown mode: treat like pre
    return pre_on


def _compute_atr_14_arr(
    high_arr: np.ndarray, low_arr: np.ndarray, close_arr: np.ndarray, period: int = 14
) -> np.ndarray:
    """Wilder-style simple rolling mean of TR over ``period`` (matches run_brt_backtest ATR14)."""
    n = len(high_arr)
    tr_arr = np.empty(n, dtype=np.float64)
    tr_arr[0] = high_arr[0] - low_arr[0]
    if n > 1:
        hl = high_arr[1:] - low_arr[1:]
        h_pc = np.abs(high_arr[1:] - close_arr[:-1])
        l_pc = np.abs(low_arr[1:] - close_arr[:-1])
        tr_arr[1:] = np.maximum.reduce([hl, h_pc, l_pc])
    atr_arr = np.full(n, np.nan, dtype=np.float64)
    if n >= period:
        atr_arr[period - 1 :] = np.convolve(
            tr_arr, np.ones(period, dtype=np.float64) / float(period), mode="valid"
        )
    return atr_arr


def _compute_sma_arr(close_arr: np.ndarray, period: int = 50) -> np.ndarray:
    """Simple moving average of close; NaN until ``period`` bars are available."""
    n = len(close_arr)
    out = np.full(n, np.nan, dtype=np.float64)
    if n < period:
        return out
    kernel = np.ones(period, dtype=np.float64) / float(period)
    out[period - 1 :] = np.convolve(close_arr, kernel, mode="valid")
    return out


def _brt_target_price(
    cfg: BRTConfig,
    *,
    entry_price: float,
    entry_bar: int,
    is_long_side: bool,
    atr_pct: Optional[float],
    sma50_arr: Optional[np.ndarray],
    cfg_atr_target: float,
    cfg_short_target_pct: float,
) -> float:
    """Percent or ATR target; optional SMA(50) anchor when use_sma50 and not using atr_target."""
    if cfg_atr_target > 0 and atr_pct is not None:
        return (
            entry_price * (1.0 + atr_pct * cfg.atr_target / 100.0)
            if is_long_side
            else entry_price * (1.0 - atr_pct * cfg.atr_target / 100.0)
        )
    if bool(getattr(cfg, "use_sma50", False)) and sma50_arr is not None:
        if 0 <= entry_bar < len(sma50_arr):
            sma50 = float(sma50_arr[entry_bar])
            if np.isfinite(sma50) and sma50 > 0:
                if is_long_side:
                    return sma50 * float(cfg.target_pct)
                _stp = float(cfg_short_target_pct)
                return sma50 * ((2.0 - _stp) if _stp >= 1.0 else (1.0 - _stp))
    if is_long_side:
        return entry_price * float(cfg.target_pct)
    _stp = float(cfg_short_target_pct)
    return entry_price * ((2.0 - _stp) if _stp >= 1.0 else (1.0 - _stp))


def _brt_stop_target_prices(
    cfg: BRTConfig,
    *,
    anchor_price: float,
    entry_bar: int,
    is_long_side: bool,
    atr_14_arr: np.ndarray,
    atr_pct: Optional[float] = None,
    sma50_arr: Optional[np.ndarray] = None,
) -> tuple[float, float]:
    """
    Stop and target from ``anchor_price`` (scanner: last-bar close; live entries use next open).

    Uses the same atr_stop / atr_target / stop_pct / target_pct rules as ``run_brt_backtest`` entries.
    """
    entry_price = float(anchor_price)
    if not (entry_price > 0.0 and np.isfinite(entry_price)):
        return 0.0, 0.0
    cfg_atr_target = float(getattr(cfg, "atr_target", 0.0) or 0.0)
    cfg_atr_stop = float(getattr(cfg, "atr_stop", 0.0) or 0.0)
    cfg_short_target_pct = float(
        getattr(cfg, "short_target_pct", getattr(cfg, "target_pct", 0.0)) or 0.0
    )
    _cfg_stop_pct = float(getattr(cfg, "stop_pct", 0.0) or 0.0)
    _cfg_short_stop_pct = float(getattr(cfg, "short_stop_pct", _cfg_stop_pct) or 0.0)
    atr_14_at_entry_val: Optional[float] = None
    if 0 <= entry_bar < len(atr_14_arr):
        _a14 = float(atr_14_arr[entry_bar])
        if np.isfinite(_a14):
            atr_14_at_entry_val = _a14
    _atr_pct = atr_pct
    if _atr_pct is None and atr_14_at_entry_val is not None:
        _atr_pct = (atr_14_at_entry_val / entry_price) * 100.0
    target_price = _brt_target_price(
        cfg,
        entry_price=entry_price,
        entry_bar=entry_bar,
        is_long_side=is_long_side,
        atr_pct=_atr_pct,
        sma50_arr=sma50_arr,
        cfg_atr_target=cfg_atr_target,
        cfg_short_target_pct=cfg_short_target_pct,
    )
    if cfg_atr_stop > 0 and _atr_pct is not None:
        stop_price = (
            entry_price * (1.0 - _atr_pct * cfg.atr_stop / 100.0)
            if is_long_side
            else entry_price * (1.0 + _atr_pct * cfg.atr_stop / 100.0)
        )
    elif (_cfg_stop_pct > 0 and is_long_side) or (_cfg_short_stop_pct > 0 and (not is_long_side)):
        _sp = _cfg_stop_pct if is_long_side else _cfg_short_stop_pct
        if is_long_side:
            stop_price = (
                entry_price * _sp
                if cfg.stop_pct_is_multiplier
                else entry_price * (1 - _sp)
            )
        else:
            stop_price = (
                entry_price * ((2.0 - _sp) if _sp >= 1.0 else (1.0 + (1.0 - _sp)))
                if cfg.stop_pct_is_multiplier
                else entry_price * (1 + _sp)
            )
    else:
        _def_mult = 0.934
        _def_frac_below = 0.066
        if is_long_side:
            stop_price = (
                entry_price * _def_mult
                if cfg.stop_pct_is_multiplier
                else entry_price * (1 - _def_frac_below)
            )
        else:
            stop_price = (
                entry_price * (2.0 - _def_mult)
                if cfg.stop_pct_is_multiplier
                else entry_price * (1 + _def_frac_below)
            )
    return float(stop_price), float(target_price)


def _effective_band_pct_tp(
    tp: float,
    bar_idx: int,
    atr_arr: np.ndarray,
    band_pct_fixed: float,
    band_pct_atr_mult: float,
) -> float:
    """When band_pct_atr_mult > 0, zone half-width fraction of tp = (mult * ATR14) / tp; else band_pct_fixed."""
    if band_pct_atr_mult <= 0:
        return float(band_pct_fixed)
    if bar_idx < 0 or bar_idx >= len(atr_arr):
        return float(band_pct_fixed)
    atr = float(atr_arr[bar_idx])
    if not (np.isfinite(atr) and atr > 0 and np.isfinite(tp) and tp > 0):
        return float(band_pct_fixed)
    return float((band_pct_atr_mult * atr) / tp)


def _round_zone_price(x: float, decimals: int) -> float:
    """Round like Google Sheets / Excel at cents: half away from zero (not Python banker's round)."""
    if decimals < 0:
        return float(x)
    from decimal import ROUND_HALF_UP, Decimal

    quant = Decimal(10) ** (-int(decimals))
    return float(Decimal(str(float(x))).quantize(quant, rounding=ROUND_HALF_UP))


def _round_ohlc_arr(arr: np.ndarray, decimals: int) -> np.ndarray:
    """Sheets ROUND(x, decimals) on OHLC arrays — half away from zero, not numpy banker's round."""
    if decimals < 0:
        return np.asarray(arr, dtype=np.float64)
    dec = int(decimals)
    flat = np.asarray(arr, dtype=np.float64).ravel()
    rounded = np.array([_round_zone_price(float(x), dec) for x in flat], dtype=np.float64)
    return rounded.reshape(np.asarray(arr).shape)


def _cfg_mts_overlap_full_precision(cfg: BRTConfig) -> bool:
    return bool(getattr(cfg, "mts_overlap_full_precision", False))


def _cfg_zone_bounds_round_decimals(cfg: BRTConfig) -> int:
    """Decimals for tp*(1±C5) zone lower/upper; -1 = full precision (MTS overlap parity)."""
    if _cfg_mts_overlap_full_precision(cfg):
        return -1
    return int(getattr(cfg, "zone_price_round_decimals", 2))


def _cfg_overlap_compare_round_decimals(cfg: BRTConfig) -> int:
    """Decimals for High/Low vs CE/CF overlap; -1 = raw floats (MTS FILTER parity)."""
    if _cfg_mts_overlap_full_precision(cfg):
        return -1
    return int(getattr(cfg, "zone_compare_round_decimals", 2))


def _effective_strong_pivot_pct(
    pivot_px: float,
    bar_idx: int,
    atr_arr: np.ndarray,
    fixed_pct: float,
    atr_mult: float,
) -> float:
    """When atr_mult > 0, threshold fraction = (atr_mult * ATR14) / pivot_px; else fixed_pct."""
    if atr_mult <= 0:
        return float(fixed_pct)
    if bar_idx < 0 or bar_idx >= len(atr_arr):
        return float(fixed_pct)
    atr = float(atr_arr[bar_idx])
    if not (np.isfinite(atr) and atr > 0 and np.isfinite(pivot_px) and pivot_px > 0):
        return float(fixed_pct)
    return float((atr_mult * atr) / pivot_px)


def _strong_pivot_bar_ok(
    t: int,
    kind: str,
    hi_arr: np.ndarray,
    lo_arr: np.ndarray,
    n: int,
    *,
    pre_bars: int,
    pre_pct: float,
    post_bars: int,
    post_pct: float,
    mode: str,
) -> bool:
    """
    Strong pivot at bar t for kind 'PH' or 'PL'.
    Pre (lookback): PL — (1 - Low[t]/max(High[t-pre_bars:t])) >= pre_pct; PH — High[t]/min(Low[...]) - 1 >= pre_pct.
    Post (lookahead): same as legacy — follow-through over next post_bars bars.
    """
    mode_l = (mode or "pre").strip().lower()
    pre_ok = False
    post_ok = False
    if kind == "PL":
        if pre_bars > 0 and pre_pct > 0 and t >= 1:
            start = max(0, t - pre_bars)
            max_h = float(np.max(hi_arr[start:t]))
            if max_h > 0 and lo_arr[t] > 0:
                pre_ok = (1.0 - lo_arr[t] / max_h) >= pre_pct - 1e-12
        if post_bars > 0 and post_pct > 0 and t + post_bars < n:
            pivot_price = lo_arr[t]
            if pivot_price > 0:
                future_max_high = float(np.max(hi_arr[t + 1 : t + post_bars + 1]))
                post_ok = (future_max_high / pivot_price - 1.0) >= post_pct - 1e-12
    elif kind == "PH":
        if pre_bars > 0 and pre_pct > 0 and t >= 1:
            start = max(0, t - pre_bars)
            min_l = float(np.min(lo_arr[start:t]))
            if min_l > 0 and hi_arr[t] > 0:
                pre_ok = (hi_arr[t] / min_l - 1.0) >= pre_pct - 1e-12
        if post_bars > 0 and post_pct > 0 and t + post_bars < n:
            pivot_price = hi_arr[t]
            if pivot_price > 0:
                future_min_low = float(np.min(lo_arr[t + 1 : t + post_bars + 1]))
                move_pct = future_min_low / pivot_price - 1.0
                post_ok = move_pct <= -post_pct
    if mode_l == "pre":
        return pre_ok
    if mode_l == "post":
        return post_ok
    if mode_l == "both":
        return pre_ok and post_ok
    if mode_l in ("either", "any"):
        return pre_ok or post_ok
    return pre_ok


# ============== LEVEL 3: TOUCH STREAM & ZONE MATURITY ==============
def _sheet_price_near(a: float, b: float, tol_pct: float) -> bool:
    """Sheet COUNTIFS dedup: price within ±tol_pct of reference."""
    if not (np.isfinite(a) and np.isfinite(b) and b > 0):
        return False
    return abs(a / b - 1.0) <= float(tol_pct)


def compute_sheet_brt_touch_stream(
    df: pd.DataFrame,
    *,
    band_pct: float = 0.0154,
    pivot_local_window: int = 4,
    post_pivot_bars: int = 7,
    pivot_future_move_pct: float = 0.06,
    dedup_tol_pct: float = 0.01,
    pre_pivot_bars: int = 7,
    pre_pivot_pct: float = 0.081,
    touch_pullback_pct: float = 0.108,
    touch_pullback_bars: int = 10,
    maturity_lag: int = 7,
    warmup_bars: int = 9,
    zone_price_round_decimals: int = 2,
    zone_bounds_round_decimals: int | None = None,
    lookback_long: int = 504,
    lookback_short: int = 199,
    touch_threshold: int = 2,
    include_pivot_low_touches: bool = False,
) -> dict:
    """
    BRT sheet ladder: Touch Price (AB) + TP bands (AC/AD) + matured lag (C9 bars).

    Mirrors row-8 formulas the user provided (BRT tab, not YH):
    - Final Pivot High = Local High Test AND Post Pivot Pullback AND no-dup AND not-also-pivot-low
    - Touch Price when Final PH + Pre-strong pivot High (Z) + forward min-low pullback >= C15
      over **C14** bars (periods to check), not C10
    - Matured touch / zone lower / upper = INDEX(AB/AC/AD, ROW()-C9)
    """
    n = len(df)
    hi_raw = np.asarray(df["High"].values, dtype=np.float64)
    lo_raw = np.asarray(df["Low"].values, dtype=np.float64)
    close_arr = np.asarray(df["Close"].values, dtype=np.float64)
    _dec = int(zone_price_round_decimals)
    _bounds_dec = int(
        zone_bounds_round_decimals
        if zone_bounds_round_decimals is not None
        else zone_price_round_decimals
    )
    # Sheet AD/AE/AF gates use rounded OHLC (see zone_price_round_decimals on BRTConfig).
    if _dec >= 0:
        hi_raw = _round_ohlc_arr(hi_raw, _dec)
        lo_raw = _round_ohlc_arr(lo_raw, _dec)

    def _touch_px(t: int) -> float:
        return _round_zone_price(float(hi_raw[t]), _dec) if _dec >= 0 else float(hi_raw[t])

    def _local_hi(t: int) -> bool:
        w0 = max(0, t - pivot_local_window)
        w1 = min(n, t + pivot_local_window + 1)
        mx = float(np.max(hi_raw[w0:w1]))
        return bool(np.isclose(float(hi_raw[t]), mx, rtol=0.0, atol=1e-6))

    def _local_lo(t: int) -> bool:
        w0 = max(0, t - pivot_local_window)
        w1 = min(n, t + pivot_local_window + 1)
        mn = float(np.min(lo_raw[w0:w1]))
        return bool(np.isclose(float(lo_raw[t]), mn, rtol=0.0, atol=1e-6))

    def _post_drop_from_high(t: int) -> bool:
        if t + post_pivot_bars >= n:
            return False
        fut_min = float(np.min(lo_raw[t + 1 : t + post_pivot_bars + 1]))
        return (fut_min / float(hi_raw[t]) - 1.0) <= -float(pivot_future_move_pct)

    def _future_rise_from_low(t: int) -> bool:
        if t + post_pivot_bars >= n:
            return False
        fut_max = float(np.max(hi_raw[t + 1 : t + post_pivot_bars + 1]))
        return (fut_max / float(lo_raw[t]) - 1.0) >= float(pivot_future_move_pct)

    final_ph = np.zeros(n, dtype=bool)
    final_pl = np.zeros(n, dtype=bool)
    ph_px = np.full(n, np.nan, dtype=np.float64)
    pl_px = np.full(n, np.nan, dtype=np.float64)

    for t in range(n):
        if t < warmup_bars:
            continue
        # No dup pivot high (prior Final PH within window with similar High)
        dup_ph = False
        for j in range(max(0, t - pivot_local_window), t):
            if final_ph[j] and _sheet_price_near(float(ph_px[j]), _touch_px(t), dedup_tol_pct):
                dup_ph = True
                break
        not_also_pl = not (
            _local_lo(t)
            and _future_rise_from_low(t)
            and not any(
                final_pl[j] and _sheet_price_near(float(pl_px[j]), float(lo_raw[t]), dedup_tol_pct)
                for j in range(max(0, t - pivot_local_window), t)
            )
        )
        if _local_hi(t) and _post_drop_from_high(t) and not dup_ph and not_also_pl:
            final_ph[t] = True
            ph_px[t] = _touch_px(t)

        dup_pl = False
        for j in range(max(0, t - pivot_local_window), t):
            if final_pl[j] and _sheet_price_near(float(pl_px[j]), float(lo_raw[t]), dedup_tol_pct):
                dup_pl = True
                break
        not_also_ph = not (
            _local_hi(t)
            and _post_drop_from_high(t)
            and not any(
                final_ph[j] and _sheet_price_near(float(ph_px[j]), _touch_px(t), dedup_tol_pct)
                for j in range(max(0, t - pivot_local_window), t)
            )
        )
        if _local_lo(t) and _future_rise_from_low(t) and not dup_pl and not_also_ph:
            final_pl[t] = True
            pl_px[t] = float(lo_raw[t])

    tp_arr = np.full(n, np.nan, dtype=np.float64)
    origin_arr = np.zeros(n, dtype=np.int8)

    for t in range(n):
        if t < warmup_bars or not final_ph[t]:
            continue
        pre_lo = float(np.min(lo_raw[max(0, t - pre_pivot_bars) : t]))
        if not (pre_lo > 0 and (float(hi_raw[t]) / pre_lo - 1.0) >= float(pre_pivot_pct)):
            continue
        _tp_bars = max(1, int(touch_pullback_bars))
        if t + _tp_bars >= n:
            continue
        fut_min = float(np.min(lo_raw[t + 1 : t + _tp_bars + 1]))
        if (1.0 - fut_min / float(hi_raw[t])) < float(touch_pullback_pct):
            continue
        tp_arr[t] = _touch_px(t)
        origin_arr[t] = 1

    if include_pivot_low_touches:
        # Sheet AF low branch: Final Pivot Low + pre-strong low (AE) + forward-rise
        # pullback >= C15 over touch_pullback_bars. High-side touch wins on ties (AF's IF order).
        for t in range(n):
            if t < warmup_bars or not final_pl[t] or origin_arr[t] != 0:
                continue
            pre_hi = float(np.max(hi_raw[max(0, t - pre_pivot_bars) : t])) if t > 0 else 0.0
            if not (pre_hi > 0 and (1.0 - float(lo_raw[t]) / pre_hi) >= float(pre_pivot_pct)):
                continue
            _tp_bars = max(1, int(touch_pullback_bars))
            if t + _tp_bars >= n:
                continue
            fut_max = float(np.max(hi_raw[t + 1 : t + _tp_bars + 1]))
            if (fut_max / float(lo_raw[t]) - 1.0) < float(touch_pullback_pct):
                continue
            tp_arr[t] = _round_zone_price(float(lo_raw[t]), _dec) if _dec >= 0 else float(lo_raw[t])
            origin_arr[t] = 2

    zc_arr = np.full(n, np.nan, dtype=np.float64)
    zl_arr = np.full(n, np.nan, dtype=np.float64)
    zh_arr = np.full(n, np.nan, dtype=np.float64)
    for t in range(n):
        tp = tp_arr[t]
        if not (np.isfinite(tp) and tp > 0):
            continue
        zc_arr[t] = float(tp)
        # Sheet AC/AD: ROUND(AB*(1±C5), 2) for display; MTS overlap uses full tp*(1±C5) when _bounds_dec < 0.
        zl_arr[t] = (
            _round_zone_price(float(tp) * (1.0 - band_pct), _bounds_dec)
            if _bounds_dec >= 0
            else float(tp) * (1.0 - band_pct)
        )
        zh_arr[t] = (
            _round_zone_price(float(tp) * (1.0 + band_pct), _bounds_dec)
            if _bounds_dec >= 0
            else float(tp) * (1.0 + band_pct)
        )

    lag = max(0, int(maturity_lag))
    matured_arr = np.zeros(n, dtype=bool)
    brt_matured_events: list[dict] = []
    for t in range(lag, n):
        p = t - lag
        if np.isfinite(tp_arr[p]) and tp_arr[p] > 0:
            matured_arr[t] = True
            brt_matured_events.append(
                {
                    "maturity_bar": int(t),
                    "pivot_bar": int(p),
                    "touch_price": float(tp_arr[p]),
                    "zone_center": float(zc_arr[p]),
                    "zone_lower": float(zl_arr[p]),
                    "zone_upper": float(zh_arr[p]),
                }
            )

    # Touch counts (audit / TKL) from pivot touch stream
    pivot_mask = np.isfinite(tp_arr)
    pivot_idxs = np.where(pivot_mask)[0]
    pivot_tps = tp_arr[pivot_idxs]
    tc_long_arr = np.zeros(n, dtype=np.int32)
    tc_short_arr = np.zeros(n, dtype=np.int32)
    for ii, i in enumerate(pivot_idxs):
        tp = pivot_tps[ii]
        zl = zl_arr[i]
        zh = zh_arr[i]
        start_long = max(0, i - lookback_long + 1)
        in_range_long = (pivot_idxs >= start_long) & (pivot_idxs <= i)
        in_zone = (pivot_tps >= zl) & (pivot_tps <= zh)
        tc_long_arr[i] = int(np.sum(in_range_long & in_zone))
        start_short = max(0, i - lookback_short + 1)
        in_range_short = (pivot_idxs >= start_short) & (pivot_idxs <= i)
        tc_short_arr[i] = int(np.sum(in_range_short & in_zone))

    tkl_thr = 1
    tkl_arr = (tc_long_arr >= tkl_thr) & (tc_short_arr >= 2)
    short_candidate_arr = matured_arr & (close_arr <= zc_arr)
    short_candidate_arr = np.where(np.isnan(zc_arr), False, short_candidate_arr)

    return {
        "touch_price": pd.Series(tp_arr, index=df.index),
        "zone_center": pd.Series(zc_arr, index=df.index),
        "zone_low": pd.Series(zl_arr, index=df.index),
        "zone_high": pd.Series(zh_arr, index=df.index),
        "touch_count_long": pd.Series(tc_long_arr, index=df.index),
        "touch_count_short": pd.Series(tc_short_arr, index=df.index),
        "tradeable_key_level": pd.Series(tkl_arr, index=df.index),
        "matured_now": pd.Series(matured_arr, index=df.index),
        "short_candidate": pd.Series(short_candidate_arr, index=df.index),
        "zone_touch_origin": pd.Series(origin_arr, index=df.index),
        "brt_matured_zone_events": brt_matured_events,
    }


def compute_touch_stream(
    df: pd.DataFrame,
    pivot_high: pd.Series,
    pivot_low: pd.Series,
    ph_price: pd.Series,
    pl_price: pd.Series,
    band_pct: float,
    lookback_long: int,
    touch_threshold: int,
    lookback_short: int = 105,
    strong_pivots_enabled: bool = True,
    strong_pre_pivot_bars: int = 7,
    strong_pre_pivot_pct: float = 0.081,
    strong_post_pivot_bars: int = 7,
    strong_post_pivot_pct: float = 0.109,
    strong_pivot_mode: str = "pre",
    band_pct_atr: float = 0.0,
    strong_pre_pivot_pct_atr: float = 0.0,
    strong_post_pivot_pct_atr: float = 0.0,
    zone_include_pre_strong_pivot_lows: bool = False,
    zones_from_pivot_lows_enabled: bool = False,
    zone_price_round_decimals: int = 2,
    debug_symbol: Optional[str] = None,
    realtime_filter_enabled: bool = False,
    zone_maturity_model: str = "sheet_lag",
    sheet_maturity_lag_bars: int = 0,
) -> dict:
    """
    Touch stream: touchPrice = high if pivotHigh else low if pivotLow else null.
    Zone band per touch. Long-memory touch_count_long is still computed for audit/TKL.

    zone_maturity_model:
    - "sheet_lag": matured_now bar i iff a strong touch exists on bar i-lag (BF=INDEX(AF,ROW()-C10)); lag defaults
      to strong_post_pivot_bars when sheet_maturity_lag_bars is 0.
    - "touch_count": matured_now when touch_count_long crosses touch_threshold (legacy).

    Tradeable Key Level (TKL, optional): touch_count_long >= threshold AND touch_count_short >= 2;
    under sheet_lag the threshold is 1 so TKL tracks "any in-band touch" like the visible ladder stream.

    Strong Pivot Qualification (when strong_pivots_enabled=True and not realtime_filter_enabled):
    - Pre (sheet AE/AD): lookback-only on prior strong_pre_pivot_bars bars vs strong_pre_pivot_pct
      (or vs (strong_pre_pivot_pct_atr * ATR14) / pivot_price when strong_pre_pivot_pct_atr > 0)
    - Post: follow-through over the next strong_post_pivot_bars bars vs strong_post_pivot_pct
      (or ATR-scaled when strong_post_pivot_pct_atr > 0)
    - strong_pivot_mode: "pre" | "post" | "both"
    Only strong pivots create touch events; weak pivots are ignored for zone/touch counting.

    Zone band: default is ±band_pct of touch_price. When band_pct_atr > 0, half-width fraction is
    (band_pct_atr * ATR14) / touch_price at the pivot bar (band_pct is fallback when ATR is unavailable).

    When zone_include_pre_strong_pivot_lows is True (and strong pivot lows are active), the touch price
    for a strong pivot low is min(Low over bars [t-strong_pre_pivot_bars, t]) inclusive, so the zone band
    includes the deepest low in that window (aligned with the PL pre-% lookback length).

    When zones_from_pivot_lows_enabled is False, no touch/zone rows are created at pivot-low bars
    (resistance-only ladder for BH/BI / DI parity vs sheets that drop PL zones).

    When zone_price_round_decimals >= 0, High/Low passed into these gates are rounded the same way as
    compute_pivots (sheet F/G cents), so marginal post% cases match Google Sheets.
    """
    n = len(df)
    touch_price = pd.Series(float("nan"), index=df.index)
    zone_center = pd.Series(float("nan"), index=df.index)
    zone_low = pd.Series(float("nan"), index=df.index)
    zone_high = pd.Series(float("nan"), index=df.index)
    touch_count_long = pd.Series(0, index=df.index)
    touch_count_short = pd.Series(0, index=df.index)
    matured_now = pd.Series(False, index=df.index)

    ph_arr = (pivot_high.values == 1)
    pl_arr = (pivot_low.values == 1)
    hi_arr = np.asarray(df["High"].values, dtype=np.float64)
    lo_arr = np.asarray(df["Low"].values, dtype=np.float64)
    close_arr = np.asarray(df["Close"].values, dtype=np.float64)
    atr_14_arr = _compute_atr_14_arr(hi_arr, lo_arr, close_arr, 14)
    _hl_dec = int(zone_price_round_decimals)
    if _hl_dec >= 0:
        hi_arr = _round_ohlc_arr(hi_arr, _hl_dec)
        lo_arr = _round_ohlc_arr(lo_arr, _hl_dec)

    tp_arr = np.full(n, np.nan, dtype=np.float64)
    # 0 unknown, 1 pivot-high touch, 2 pivot-low touch (PL wins if both set same bar).
    origin_arr = np.zeros(n, dtype=np.int8)

    # Debug: get date index for logging
    debug_mode = debug_symbol is not None and _DEBUG_SYMBOL == debug_symbol
    date_index = df.index.astype(str).tolist() if debug_mode else []

    # Strong Pivot Qualification: filter pivots per strong_pivot_mode (pre/post/both)
    if realtime_filter_enabled:
        # Real-time mode: no strong filter; all pivots create touch events (PL optional)
        tp_arr[ph_arr] = hi_arr[ph_arr]
        origin_arr[ph_arr] = 1
        if zones_from_pivot_lows_enabled:
            tp_arr[pl_arr] = lo_arr[pl_arr]
            origin_arr[pl_arr] = 2
    elif strong_pivots_enabled and _strong_pivot_mode_has_active_params(
        strong_pivot_mode,
        strong_pre_pivot_bars,
        strong_pre_pivot_pct,
        strong_post_pivot_bars,
        strong_post_pivot_pct,
        pre_pct_atr=strong_pre_pivot_pct_atr,
        post_pct_atr=strong_post_pivot_pct_atr,
    ):
        for t in range(n):
            if ph_arr[t]:
                pivot_price = hi_arr[t]
                _pre_pct_t = _effective_strong_pivot_pct(
                    float(pivot_price), t, atr_14_arr, strong_pre_pivot_pct, strong_pre_pivot_pct_atr
                )
                _post_pct_t = _effective_strong_pivot_pct(
                    float(pivot_price), t, atr_14_arr, strong_post_pivot_pct, strong_post_pivot_pct_atr
                )
                is_strong = _strong_pivot_bar_ok(
                    t, "PH", hi_arr, lo_arr, n,
                    pre_bars=strong_pre_pivot_bars,
                    pre_pct=_pre_pct_t,
                    post_bars=strong_post_pivot_bars,
                    post_pct=_post_pct_t,
                    mode=strong_pivot_mode,
                )
                if is_strong:
                    tp_arr[t] = pivot_price  # Strong pivot high
                    origin_arr[t] = 1
                if debug_mode and _DEBUG_DATE and date_index[t][:10] >= "2021-01-01" and date_index[t][:10] <= "2022-08-01":
                    print(f"[DEBUG] {debug_symbol} bar {t} ({date_index[t][:10]}): PIVOT_HIGH @ ${pivot_price:.2f}, strong={is_strong} mode={strong_pivot_mode!r}")
            if zones_from_pivot_lows_enabled and pl_arr[t]:
                pivot_price = lo_arr[t]
                _pre_pct_tl = _effective_strong_pivot_pct(
                    float(pivot_price), t, atr_14_arr, strong_pre_pivot_pct, strong_pre_pivot_pct_atr
                )
                _post_pct_tl = _effective_strong_pivot_pct(
                    float(pivot_price), t, atr_14_arr, strong_post_pivot_pct, strong_post_pivot_pct_atr
                )
                is_strong = _strong_pivot_bar_ok(
                    t, "PL", hi_arr, lo_arr, n,
                    pre_bars=strong_pre_pivot_bars,
                    pre_pct=_pre_pct_tl,
                    post_bars=strong_post_pivot_bars,
                    post_pct=_post_pct_tl,
                    mode=strong_pivot_mode,
                )
                if is_strong:
                    touch_anchor = float(pivot_price)
                    if (
                        zone_include_pre_strong_pivot_lows
                        and strong_pre_pivot_bars > 0
                    ):
                        _pre0 = max(0, t - strong_pre_pivot_bars)
                        touch_anchor = float(np.min(lo_arr[_pre0 : t + 1]))
                    tp_arr[t] = touch_anchor  # Strong pivot low (optionally widened to pre-window min low)
                    origin_arr[t] = 2
                if debug_mode and _DEBUG_DATE and date_index[t][:10] >= "2021-01-01" and date_index[t][:10] <= "2022-08-01":
                    print(f"[DEBUG] {debug_symbol} bar {t} ({date_index[t][:10]}): PIVOT_LOW @ ${pivot_price:.2f}, strong={is_strong} mode={strong_pivot_mode!r}")
    else:
        # Legacy mode: all pivots create touch events (PL optional)
        tp_arr[ph_arr] = hi_arr[ph_arr]
        origin_arr[ph_arr] = 1
        if zones_from_pivot_lows_enabled:
            tp_arr[pl_arr] = lo_arr[pl_arr]
            origin_arr[pl_arr] = 2

    # Sheet parity: touch price/zone math is typically computed on rounded touch prices.
    # Keep configurable so we can mirror sheet behavior without hard-coding.
    if int(zone_price_round_decimals) >= 0:
        _dec = int(zone_price_round_decimals)
        tp_arr = np.where(np.isnan(tp_arr), np.nan, np.round(tp_arr, _dec))

    pivot_mask = ~np.isnan(tp_arr)

    zc_arr = np.full(n, np.nan, dtype=np.float64)
    zl_arr = np.full(n, np.nan, dtype=np.float64)
    zh_arr = np.full(n, np.nan, dtype=np.float64)
    tc_long_arr = np.zeros(n, dtype=np.int32)
    tc_short_arr = np.zeros(n, dtype=np.int32)
    pivot_idxs = np.where(pivot_mask)[0]
    pivot_tps = tp_arr[pivot_idxs]

    for ii, i in enumerate(pivot_idxs):
        tp = pivot_tps[ii]
        if not (tp > 0):
            continue
        _bp_i = _effective_band_pct_tp(float(tp), int(i), atr_14_arr, band_pct, band_pct_atr)
        zl = tp * (1 - _bp_i)
        zh = tp * (1 + _bp_i)
        zc_arr[i] = tp
        zl_arr[i] = zl
        zh_arr[i] = zh

        start_long = max(0, i - lookback_long + 1)
        in_range_long = (pivot_idxs >= start_long) & (pivot_idxs <= i)
        in_zone = (pivot_tps >= zl) & (pivot_tps <= zh)
        tc_long_arr[i] = int(np.sum(in_range_long & in_zone))

        start_short = max(0, i - lookback_short + 1)
        in_range_short = (pivot_idxs >= start_short) & (pivot_idxs <= i)
        tc_short_arr[i] = int(np.sum(in_range_short & in_zone))
        
        # Debug: log touch counts for target date range
        if debug_mode and _DEBUG_DATE and date_index[i][:10] >= "2022-07-01" and date_index[i][:10] <= "2022-08-10":
            touches_in_zone = pivot_idxs[in_range_long & in_zone]
            touch_prices = pivot_tps[in_range_long & in_zone]
            touch_dates = [date_index[idx][:10] for idx in touches_in_zone]
            print(f"[DEBUG] {debug_symbol} bar {i} ({date_index[i][:10]}): zone ${zl:.2f}-${zh:.2f}, "
                  f"tc_long={tc_long_arr[i]}, tc_short={tc_short_arr[i]}")
            print(f"        Touches: {list(zip(touch_dates, [f'${p:.2f}' for p in touch_prices]))}")

    prev_tc = np.roll(tc_long_arr, 1)
    prev_tc[0] = 0
    prev_zc = np.roll(zc_arr, 1)
    prev_zc[0] = np.nan
    same_zone = np.isclose(zc_arr, prev_zc, rtol=1e-9, equal_nan=False)
    _zmm = (zone_maturity_model or "touch_count").strip().lower()
    _lag_cfg = int(sheet_maturity_lag_bars) if int(sheet_maturity_lag_bars) > 0 else int(strong_post_pivot_bars)
    lag_m = max(0, _lag_cfg)
    if _zmm == "sheet_lag" and lag_m > 0 and n > lag_m:
        # Sheet BF: bar i shows touch from bar i-lag; one pulse per bar where that lagged pivot exists.
        matured_arr = np.zeros(n, dtype=bool)
        matured_arr[lag_m:] = np.isfinite(tp_arr[:-lag_m])
    elif _zmm == "sheet_lag":
        matured_arr = np.zeros(n, dtype=bool)
    else:
        # Legacy: mature when tc crosses threshold; suppress re-maturing the same zone.
        matured_arr = (tc_long_arr >= touch_threshold) & (
            (prev_tc < touch_threshold) | ~same_zone | np.isnan(prev_zc)
        )
    # TKL = Tradeable Key Level: historically mature AND recently active
    tkl_thr = 1 if _zmm == "sheet_lag" else int(touch_threshold)
    tkl_arr = (tc_long_arr >= tkl_thr) & (tc_short_arr >= 2)
    short_candidate_arr = matured_arr & (close_arr <= zc_arr)
    short_candidate_arr = np.where(np.isnan(zc_arr), False, short_candidate_arr)
    
    # Debug: log maturity events
    if debug_mode and _DEBUG_DATE:
        matured_idxs = np.where(matured_arr)[0]
        for mi in matured_idxs:
            if date_index[mi][:10] >= "2021-01-01" and date_index[mi][:10] <= "2022-08-10":
                print(
                    f"[DEBUG] {debug_symbol} bar {mi} ({date_index[mi][:10]}): ZONE MATURED! "
                    f"mode={_zmm!r} zone=${zc_arr[mi]:.2f}, tc_long={tc_long_arr[mi]}, prev_tc={prev_tc[mi]}, "
                    f"threshold={touch_threshold}, lag_m={lag_m if _zmm == 'sheet_lag' else '-'}"
                )

    touch_price = pd.Series(tp_arr, index=df.index)
    zone_center = pd.Series(zc_arr, index=df.index)
    zone_low = pd.Series(zl_arr, index=df.index)
    zone_high = pd.Series(zh_arr, index=df.index)
    touch_count_long = pd.Series(tc_long_arr, index=df.index)
    touch_count_short = pd.Series(tc_short_arr, index=df.index)
    tradeable_key_level = pd.Series(tkl_arr, index=df.index)
    matured_now = pd.Series(matured_arr, index=df.index)
    short_candidate = pd.Series(short_candidate_arr, index=df.index)

    return {
        "touch_price": touch_price,
        "zone_center": zone_center,
        "zone_low": zone_low,
        "zone_high": zone_high,
        "touch_count_long": touch_count_long,
        "touch_count_short": touch_count_short,
        "tradeable_key_level": tradeable_key_level,
        "matured_now": matured_now,
        "short_candidate": short_candidate,
        "zone_touch_origin": pd.Series(origin_arr, index=df.index),
    }


def _normalize_yh_memory_mode(mode: Any) -> str:
    """Return sheet|fifo|parallel; default sheet (live spreadsheet handoff)."""
    m = str(mode or "sheet").strip().lower()
    if m in ("sheet", "fifo", "parallel"):
        return m
    print(f"[BRT] Invalid yh_memory_mode={mode!r}; using 'sheet'.", file=sys.stderr)
    return "sheet"


def _effective_yh_memory_mode(
    cfg: "BRTConfig",
    cfg_kw: Optional[dict[str, Any]] = None,
    *,
    yh_memory_mode: Optional[str] = None,
    yh_serial_memory: Optional[bool] = None,
) -> str:
    """Resolve YH memory mode from explicit args, -v overrides, or BRTConfig defaults."""
    if yh_memory_mode is not None:
        return _normalize_yh_memory_mode(yh_memory_mode)
    if yh_serial_memory is not None:
        return "fifo" if bool(yh_serial_memory) else "parallel"
    kw = cfg_kw or {}
    if "yh_memory_mode" in kw:
        return _normalize_yh_memory_mode(getattr(cfg, "yh_memory_mode", "sheet"))
    if "yh_serial_memory" in kw:
        return "fifo" if bool(getattr(cfg, "yh_serial_memory", True)) else "parallel"
    return _normalize_yh_memory_mode(getattr(cfg, "yh_memory_mode", "sheet"))


def compute_yh_touch_stream(
    df: pd.DataFrame,
    band_pct: float,
    lookback_long: int,
    touch_threshold: int,
    lookback_short: int = 105,
    band_pct_atr: float = 0.0,
    zone_price_round_decimals: int = 2,
    yh_lookback: int = 252,
    yh_move_away_pct: float = 0.03,
    yh_memory_mode: str = "sheet",
    yh_serial_memory: Optional[bool] = None,
    debug_symbol: Optional[str] = None,
) -> dict:
    """
    Year-High (YH) zone engine.

  ``yh_memory_mode`` (default ``sheet``):
    - **sheet**: YH-tab state machine — **0.03 move away next**, **Active YH Level**,
      **Next YH candidate** (promote CE → BZ; queue BY when CD active). Matches the live
      spreadsheet columns, not a single persisted ``YH Level`` cell.
    - **fifo**: one working + one queued; new 52w highs replace the queue; promote queued on activation.
    - **parallel**: every new 52w high spawns an independent candidate (test variant).

    Legacy ``yh_serial_memory`` when passed: True → fifo, False → parallel (overrides ``yh_memory_mode``).

    All modes:
    - New YH: High[t] > MAX(High[t-yh_lookback : t-1]) after warmup.
    - Activation: High[t] >= ROUND(YH×(1+yh_move_away_pct), 2).
    - Zone bands via ``band_pct`` (not hardcoded 0.98/1.02).
    - Activated zones persist in ``yh_zone_events`` for breakout/retest.
    """
    mode = _effective_yh_memory_mode(
        BRTConfig(),
        yh_memory_mode=yh_memory_mode,
        yh_serial_memory=yh_serial_memory,
    )
    n = len(df)
    hi_raw = np.asarray(df["High"].values, dtype=np.float64)
    lo_arr = np.asarray(df["Low"].values, dtype=np.float64)
    close_arr = np.asarray(df["Close"].values, dtype=np.float64)
    atr_14_arr = _compute_atr_14_arr(hi_raw, lo_arr, close_arr, 14)
    _dec = int(zone_price_round_decimals)
    hi_arr = np.round(hi_raw, _dec) if _dec >= 0 else hi_raw.copy()

    tp_arr = np.full(n, np.nan, dtype=np.float64)
    origin_arr = np.zeros(n, dtype=np.int8)
    zc_arr = np.full(n, np.nan, dtype=np.float64)
    zl_arr = np.full(n, np.nan, dtype=np.float64)
    zh_arr = np.full(n, np.nan, dtype=np.float64)
    matured_arr = np.zeros(n, dtype=bool)
    yh_zone_events: list[dict] = []

    yh_lb = max(1, int(yh_lookback))
    move_pct = max(0.0, float(yh_move_away_pct))
    debug_mode = debug_symbol is not None and _DEBUG_SYMBOL == debug_symbol
    date_index = df.index.astype(str).tolist() if debug_mode else []

    def _rnd(x: float) -> float:
        return _round_zone_price(float(x), _dec) if _dec >= 0 else float(x)

    def _hi_sheet(t: int) -> float:
        return _rnd(float(hi_raw[t]))

    def _make_candidate(yh_bar: int, yh_p: float) -> list:
        act_p = _rnd(yh_p * (1.0 + move_pct))
        return [int(yh_bar), float(yh_p), float(act_p)]

    def _activate(yh_bar: int, yh_price: float, act_price: float, t: int) -> None:
        if yh_price <= 0:
            return
        _bp_i = _effective_band_pct_tp(
            float(yh_price), int(yh_bar), atr_14_arr, band_pct, band_pct_atr
        )
        zl = _rnd(float(yh_price) * (1.0 - _bp_i))
        zh = _rnd(float(yh_price) * (1.0 + _bp_i))
        yh_zone_events.append(
            {
                "yh_bar": int(yh_bar),
                "activation_bar": int(t),
                "touch_price": float(yh_price),
                "zone_center": float(yh_price),
                "zone_lower": zl,
                "zone_upper": zh,
                "activation_price": float(act_price),
            }
        )
        matured_arr[t] = True
        tp_arr[t] = float(yh_price)
        origin_arr[t] = 3
        zc_arr[t] = float(yh_price)
        zl_arr[t] = zl
        zh_arr[t] = zh
        if debug_mode and _DEBUG_DATE:
            print(
                f"[DEBUG] {debug_symbol} bar {t} ({date_index[t][:10]}): "
                f"YH ACTIVATED yh_bar={yh_bar} touch=${yh_price:.2f} "
                f"zone ${zl:.2f}-${zh:.2f}"
            )

    def _yh_move_away_threshold(bz: float) -> float:
        """Sheet compares raw High to BZ*(1+pct) without rounding the product first."""
        return float(bz) * (1.0 + move_pct)

    def _crossed_yh_move_away(hi_raw_val: float, bz: float) -> bool:
        if not np.isfinite(bz) or bz <= 0:
            return False
        return float(hi_raw_val) >= _yh_move_away_threshold(bz)

    def _sheet_yh_row(
        hi_raw_val: float,
        by: float,
        bz_prev: float,
        cd_prev: float,
        ce_prev: float,
    ) -> tuple[float, float, float, float, float]:
        """One bar of the YH sheet state machine (0.03 move away / Active YH / Next candidate)."""
        by_f = float(by) if np.isfinite(by) and by > 0 else np.nan
        bz_p = float(bz_prev) if np.isfinite(bz_prev) and bz_prev > 0 else np.nan
        cd_p = float(cd_prev) if np.isfinite(cd_prev) and cd_prev > 0 else np.nan
        ce_p = float(ce_prev) if np.isfinite(ce_prev) and ce_prev > 0 else np.nan

        if np.isfinite(ce_p):
            bz = ce_p
        elif not np.isfinite(bz_p):
            bz = by_f
        elif not np.isfinite(cd_p):
            bz = bz_p
        elif np.isfinite(by_f):
            bz = by_f
        else:
            bz = bz_p

        ca = (
            _rnd(_yh_move_away_threshold(float(bz)))
            if np.isfinite(bz) and bz > 0
            else np.nan
        )

        cd = np.nan
        if np.isfinite(bz) and bz > 0:
            if np.isfinite(cd_p) and cd_p == bz:
                cd = float(bz)
            elif _crossed_yh_move_away(float(hi_raw_val), float(bz)):
                cd = float(bz)

        ce = by_f if np.isfinite(by_f) and np.isfinite(cd) and cd > 0 else np.nan
        return bz, ca, cd, ce, by_f

    working: Optional[list] = None
    queued: Optional[list] = None
    parallel_pending: list[list] = []

    def _log_new_yh(t: int, yh_p: float, nc: list) -> None:
        if debug_mode and _DEBUG_DATE:
            print(
                f"[DEBUG] {debug_symbol} bar {t} ({date_index[t][:10]}): "
                f"NEW_YH candidate @ ${yh_p:.2f} act>=${nc[2]:.2f}"
            )

    if mode == "sheet":
        bz_prev = np.nan
        cd_prev = np.nan
        ce_prev = np.nan
        bz_bar = -1
        activated_for_bz = False
        for t in range(n):
            by = np.nan
            if t >= yh_lb:
                start = t - yh_lb
                prev_max = float(np.max(hi_arr[start:t]))
                if float(hi_arr[t]) > prev_max:
                    by = _rnd(float(hi_raw[t]))

            bz, ca, cd, ce, _by_f = _sheet_yh_row(
                float(hi_raw[t]), by, bz_prev, cd_prev, ce_prev
            )

            if np.isfinite(bz) and (not np.isfinite(bz_prev) or float(bz) != float(bz_prev)):
                bz_bar = int(t)
                activated_for_bz = False

            if (
                np.isfinite(bz)
                and _crossed_yh_move_away(float(hi_raw[t]), float(bz))
                and not activated_for_bz
            ):
                _activate(max(bz_bar, 0), float(bz), float(ca), t)
                activated_for_bz = True

            bz_prev = bz
            cd_prev = cd
            ce_prev = ce
    else:
        for t in range(n):
            activated = False
            if mode == "fifo":
                if working is not None:
                    yh_bar, yh_price, act_price = working
                    if float(hi_arr[t]) >= float(act_price):
                        _activate(int(yh_bar), float(yh_price), float(act_price), t)
                        activated = True
                        working = queued
                        queued = None
            else:
                for entry in parallel_pending:
                    if entry[3]:
                        continue
                    yh_bar, yh_price, act_price, _ = entry
                    if yh_price <= 0:
                        continue
                    if float(hi_arr[t]) >= float(act_price):
                        entry[3] = True
                        _activate(int(yh_bar), float(yh_price), float(act_price), t)

            if t >= yh_lb:
                start = t - yh_lb
                prev_max = float(np.max(hi_arr[start:t]))
                cur_hi = float(hi_arr[t])
                if cur_hi > prev_max:
                    yh_p = _rnd(cur_hi)
                    nc = _make_candidate(t, yh_p)
                    _log_new_yh(t, yh_p, nc)
                    if mode == "parallel":
                        parallel_pending.append([nc[0], nc[1], nc[2], False])
                    elif mode == "fifo":
                        if working is None:
                            working = nc
                        else:
                            queued = nc

    tc_long_arr = np.zeros(n, dtype=np.int32)
    tc_short_arr = np.zeros(n, dtype=np.int32)
    tkl_arr = np.zeros(n, dtype=bool)
    short_candidate_arr = np.zeros(n, dtype=bool)

    return {
        "touch_price": pd.Series(tp_arr, index=df.index),
        "zone_center": pd.Series(zc_arr, index=df.index),
        "zone_low": pd.Series(zl_arr, index=df.index),
        "zone_high": pd.Series(zh_arr, index=df.index),
        "touch_count_long": pd.Series(tc_long_arr, index=df.index),
        "touch_count_short": pd.Series(tc_short_arr, index=df.index),
        "tradeable_key_level": pd.Series(tkl_arr, index=df.index),
        "matured_now": pd.Series(matured_arr, index=df.index),
        "short_candidate": pd.Series(short_candidate_arr, index=df.index),
        "zone_touch_origin": pd.Series(origin_arr, index=df.index),
        "yh_zone_events": yh_zone_events,
    }


def _merge_level3_streams(level3_a: dict, level3_b: dict) -> dict:
    """
    Merge two level3 dicts bar-by-bar. When both define a touch at the same bar, keep level3_a (BRT).
    Touch counts sum when both streams touch the same bar; matured_now and bool flags use OR.
    """
    idx = level3_a["touch_price"].index
    tp_a = level3_a["touch_price"].to_numpy(dtype=np.float64)
    tp_b = level3_b["touch_price"].to_numpy(dtype=np.float64)
    fin_a = np.isfinite(tp_a)
    fin_b = np.isfinite(tp_b)
    both = fin_a & fin_b

    out: dict[str, pd.Series] = {}
    for k in ("touch_price", "zone_center", "zone_low", "zone_high"):
        a = level3_a[k].to_numpy(dtype=np.float64)
        b = level3_b[k].to_numpy(dtype=np.float64)
        merged = np.where(fin_a, a, b)
        merged = np.where(both, a, merged)
        out[k] = pd.Series(merged, index=idx)

    for k in ("touch_count_long", "touch_count_short"):
        a = level3_a[k].to_numpy(dtype=np.int32)
        b = level3_b[k].to_numpy(dtype=np.int32)
        merged = np.where(both, a + b, np.where(fin_a, a, b))
        out[k] = pd.Series(merged, index=idx)

    for k in ("tradeable_key_level", "matured_now", "short_candidate"):
        a = level3_a[k].to_numpy(dtype=bool)
        b = level3_b[k].to_numpy(dtype=bool)
        out[k] = pd.Series(a | b, index=idx)

    o_a = level3_a["zone_touch_origin"].to_numpy(dtype=np.int8)
    o_b = level3_b["zone_touch_origin"].to_numpy(dtype=np.int8)
    o_m = np.where(fin_a, o_a, o_b)
    o_m = np.where(both, o_a, o_m)
    out["zone_touch_origin"] = pd.Series(o_m, index=idx)
    ev_a = level3_a.get("yh_zone_events") or []
    ev_b = level3_b.get("yh_zone_events") or []
    if ev_a or ev_b:
        out["yh_zone_events"] = list(ev_a) + list(ev_b)
    vec_a = level3_a.get("vec_zone_events") or []
    vec_b = level3_b.get("vec_zone_events") or []
    if vec_a or vec_b:
        out["vec_zone_events"] = list(vec_a) + list(vec_b)
    return out


def build_level3_for_cfg(
    df: pd.DataFrame,
    cfg: Any,
    pivot_high: pd.Series,
    pivot_low: pd.Series,
    ph_price: pd.Series,
    pl_price: pd.Series,
    *,
    debug_symbol: Optional[str] = None,
) -> dict:
    """Build level3 from BRT pivot zones, YH zones, VEC zones, or combinations per cfg toggles."""
    brt_on = bool(getattr(cfg, "brt_zones", False))
    yh_on = bool(getattr(cfg, "yh_zones", True))
    vec_on = bool(getattr(cfg, "vec_zones", False))
    pbr_on = bool(getattr(cfg, "pbr_zones", False))
    if not brt_on and not yh_on and not vec_on and not pbr_on:
        print("[BRT] brt_zones, yh_zones, vec_zones, pbr_zones all False; defaulting to yh_zones=True (YH mode).", file=sys.stderr)
        yh_on = True

    def _brt_level3() -> dict:
        if bool(getattr(cfg, "brt_sheet_touch", False)):
            lag = _effective_sheet_maturity_lag_bars(cfg)
            return compute_sheet_brt_touch_stream(
                df,
                band_pct=cfg.band_pct,
                pivot_local_window=cfg.pivot_k,
                post_pivot_bars=cfg.strong_post_pivot_bars,
                pivot_future_move_pct=cfg.pivot_disp,
                dedup_tol_pct=_PIVOT_DEDUP_EPS,
                pre_pivot_bars=cfg.strong_pre_pivot_bars,
                pre_pivot_pct=cfg.strong_pre_pivot_pct,
                touch_pullback_pct=cfg.strong_post_pivot_pct,
                touch_pullback_bars=int(getattr(cfg, "sheet_touch_pullback_bars", 10) or 10),
                maturity_lag=lag,
                warmup_bars=int(getattr(cfg, "brt_sheet_warmup_bars", 9) or 9),
                zone_price_round_decimals=cfg.zone_price_round_decimals,
                zone_bounds_round_decimals=_cfg_zone_bounds_round_decimals(cfg),
                lookback_long=cfg.lookback_long,
                lookback_short=cfg.lookback_short,
                touch_threshold=cfg.touch_threshold,
                include_pivot_low_touches=bool(getattr(cfg, "mts_zone_low_touches", False)),
            )
        return compute_touch_stream(
            df,
            pivot_high,
            pivot_low,
            ph_price,
            pl_price,
            cfg.band_pct,
            cfg.lookback_long,
            cfg.touch_threshold,
            cfg.lookback_short,
            strong_pivots_enabled=cfg.strong_pivots_enabled,
            strong_pre_pivot_bars=cfg.strong_pre_pivot_bars,
            strong_pre_pivot_pct=cfg.strong_pre_pivot_pct,
            strong_post_pivot_bars=cfg.strong_post_pivot_bars,
            strong_post_pivot_pct=cfg.strong_post_pivot_pct,
            strong_pivot_mode=cfg.strong_pivot_mode,
            band_pct_atr=float(getattr(cfg, "band_pct_atr", 0.0) or 0.0),
            strong_pre_pivot_pct_atr=float(getattr(cfg, "strong_pre_pivot_pct_atr", 0.0) or 0.0),
            strong_post_pivot_pct_atr=float(getattr(cfg, "strong_post_pivot_pct_atr", 0.0) or 0.0),
            zone_include_pre_strong_pivot_lows=cfg.zone_include_pre_strong_pivot_lows,
            zones_from_pivot_lows_enabled=cfg.zones_from_pivot_lows_enabled,
            zone_price_round_decimals=cfg.zone_price_round_decimals,
            debug_symbol=debug_symbol,
            realtime_filter_enabled=cfg.realtime_filter_enabled,
            zone_maturity_model=cfg.zone_maturity_model,
            sheet_maturity_lag_bars=cfg.sheet_maturity_lag_bars,
        )

    def _yh_level3() -> dict:
        return compute_yh_touch_stream(
            df,
            cfg.band_pct,
            cfg.lookback_long,
            cfg.touch_threshold,
            cfg.lookback_short,
            band_pct_atr=float(getattr(cfg, "band_pct_atr", 0.0) or 0.0),
            zone_price_round_decimals=cfg.zone_price_round_decimals,
            yh_lookback=int(getattr(cfg, "yh_lookback", 252) or 252),
            yh_move_away_pct=float(getattr(cfg, "yh_move_away_pct", 0.03) or 0.03),
            yh_memory_mode=_effective_yh_memory_mode(cfg),
            debug_symbol=debug_symbol,
        )

    def _vec_level3() -> dict:
        try:
            from vec_zones import compute_vec_touch_stream
        except ImportError:
            from stock_analysis.vec_zones import compute_vec_touch_stream
        return compute_vec_touch_stream(
            df,
            cfg.band_pct,
            cfg.lookback_long,
            cfg.touch_threshold,
            cfg.lookback_short,
            band_pct_atr=float(getattr(cfg, "band_pct_atr", 0.0) or 0.0),
            zone_price_round_decimals=cfg.zone_price_round_decimals,
            vec_vp_lookback=int(getattr(cfg, "vec_vp_lookback", 60) or 60),
            vec_vp_bin_pct=float(getattr(cfg, "vec_vp_bin_pct", 0.005) or 0.005),
            vec_prior_bars=int(getattr(cfg, "vec_prior_bars", 5) or 5),
            vec_prior_side=str(getattr(cfg, "vec_prior_side", "high") or "high"),
            vec_confluence_pct=float(getattr(cfg, "vec_confluence_pct", 0.0075) or 0.0075),
            vec_move_away_pct=float(getattr(cfg, "vec_move_away_pct", 0.02) or 0.02),
            vec_min_bars_between=int(getattr(cfg, "vec_min_bars_between", 20) or 20),
            debug_symbol=debug_symbol,
            effective_band_pct_fn=_effective_band_pct_tp,
            round_zone_price_fn=_round_zone_price,
            compute_atr_14_fn=_compute_atr_14_arr,
        )

    def _pbr_level3() -> dict:
        try:
            from pbr_zones import compute_pbr_touch_stream
        except ImportError:
            from stock_analysis.pbr_zones import compute_pbr_touch_stream
        return compute_pbr_touch_stream(
            df,
            band_pct=cfg.band_pct,
            strong_pre_pivot_bars=cfg.strong_pre_pivot_bars,
            strong_pre_pivot_pct=cfg.strong_pre_pivot_pct,
            strong_post_pivot_bars=cfg.strong_post_pivot_bars,
            strong_post_pivot_pct=cfg.strong_post_pivot_pct,
            strong_pivot_mode=cfg.strong_pivot_mode,
            breakout_confirmation=float(getattr(cfg, "pbr_breakout_confirmation", 0.03) or 0.03),
            max_days_after_retest=int(getattr(cfg, "pbr_max_days_after_retest", 2) or 2),
            zone_price_round_decimals=cfg.zone_price_round_decimals,
            debug_symbol=debug_symbol,
        )

    streams: list[dict] = []
    if brt_on:
        streams.append(_brt_level3())
    if yh_on:
        streams.append(_yh_level3())
    if vec_on:
        streams.append(_vec_level3())
    if pbr_on:
        streams.append(_pbr_level3())
    if not streams:
        return _yh_level3()
    out = streams[0]
    for s in streams[1:]:
        out = _merge_level3_streams(out, s)
    return out


def _pivot_sequence_in_zone(
    maturity_bar: int,
    zl: float,
    zh: float,
    ph_arr: np.ndarray,
    pl_arr: np.ndarray,
) -> tuple[list[str], int, int, bool]:
    """
    Build sequence of 'H'/'L' for pivots in [zl, zh] from bar 0 to maturity_bar (chronological).
    Uses ph_arr > 0 / pl_arr > 0 to detect pivot high/low. Returns (sequence, high_run, low_run, switch_h_to_l).
    Strong setup: ≥2 highs then 1–2 lows at end of sequence (switch_h_to_l True).
    """
    seq: list[str] = []
    n = min(maturity_bar + 1, len(ph_arr))
    for j in range(n):
        p = ph_arr[j]
        if p > 0 and zl <= p <= zh:
            seq.append("H")
        p = pl_arr[j]
        if p > 0 and zl <= p <= zh:
            seq.append("L")
    low_run = 0
    for k in range(len(seq) - 1, -1, -1):
        if seq[k] == "L" and low_run < 2:
            low_run += 1
        else:
            break
    if low_run not in (1, 2):
        return (seq, 0, low_run, False)
    high_run = 0
    for k in range(len(seq) - 1 - low_run, -1, -1):
        if seq[k] == "H":
            high_run += 1
        else:
            break
    switch_h_to_l = high_run >= 2
    return (seq, high_run, low_run, switch_h_to_l)


# ============== TRADE SIMULATION ==============
@dataclass
class BRTTrade:
    symbol: str
    date_opened: str
    entry_price: float
    stop_price: float
    target_price: float
    date_closed: str = ""
    exit_price: float = 0.0
    exit_type: str = ""
    days_held: int = 0
    pnl_pct: float = 0.0
    pnl_dollars: float = 0.0
    zone_center: float = 0.0
    zone_low: float = 0.0
    zone_high: float = 0.0
    # PBR lifecycle: stable pivot-zone id (pivot_week_end|zl|zh); empty for non-PBR trades
    pbr_zone_id: str = ""
    # PBR zone strength metrics (from pbr_zone_events at entry); see pbr_zones.PBR_STRENGTH_FIELDS
    pbr_pre_rise_pct: Optional[float] = None
    pbr_post_rise_pct: Optional[float] = None
    pbr_pivot_symmetry: Optional[float] = None
    pbr_poc: Optional[float] = None
    pbr_poc_dist_pct: Optional[float] = None
    pbr_prior_extreme: Optional[float] = None
    pbr_prior_extreme_dist_pct: Optional[float] = None
    pbr_bo_close_margin_pct: Optional[float] = None
    pbr_conf_overshoot_pct: Optional[float] = None
    pbr_weeks_pivot_to_bo: Optional[float] = None
    pbr_weeks_bo_to_conf: Optional[float] = None
    pbr_bo_volume_ratio: Optional[float] = None
    pbr_conf_volume_ratio: Optional[float] = None
    pbr_retest_depth_pct: Optional[float] = None
    pbr_retest_close_margin_pct: Optional[float] = None
    pbr_days_conf_to_retest: Optional[float] = None
    pbr_signal_body_pct: Optional[float] = None
    pbr_zone_strength: Optional[float] = None
    touch_count: int = 0
    touch_count_short: int = 0
    touch_count_major: int = 0
    touch_count_minor: int = 0
    # MTS / sheet zone touch metrics at signal bar (active band); see _zone_touch_metrics_at_signal
    zone_rolling_touches: int = 0       # AR: matured CD prices in [DK,DL] over lookback_long
    support_test_count: int = 0         # AM raw count: AK support tests for same DN in window
    support_test_at_signal: int = 0     # AK at signal bar (0/1)
    touch_count_at_maturity: int = 0    # touch_count_long at zone maturity bar
    touch_count_short_at_maturity: int = 0
    zone_episode_dn: int = 0            # DN: active zone episode id at signal
    days_since_maturity: int = 0        # calendar days maturity bar -> signal bar
    is_tradeable_key_level: bool = False
    struct_high: str = ""
    struct_low: str = ""
    entry_pivot_type: str = ""
    entry_struct_regime: str = ""
    entry_major_pivot: int = 0  # Look-ahead: 1 if pivot at maturity was "major" (next struct HH/LL); not known at real entry time
    # Research: 1 if the maturity-bar pivot passes strong-pivot rules per cfg (pre/post/both; same as touch stream)
    entry_pivot_was_strong: int = 0
    entry_zone_was_strong_pivot: int = 0  # 1 if strong_pivots_enabled gated the touch stream; 0 if disabled / realtime (all pivots)
    nearby_zones_above: int = 0
    nearby_zones_below: int = 0
    zone_cluster_density: int = 0
    # Trace (for 5/23 vs 5/27 debugging): 6th touch bar, close-above bar, DI breakout bar
    maturity_date: str = ""
    close_above_date: str = ""
    breakout_date: str = ""
    days_since_breakout: Optional[int] = None  # Calendar days from breakout date to retest/signal date
    max_price: float = 0.0  # Max High during hold (for BRT_Closed)
    # 1 if price reached post_entry_gain_pct in trade direction within min(entry+N calendar days, exit date): LONG=max High>=entry*(1+pct/100); SHORT=min Low<=entry*(1-pct/100)
    post_entry_gain_hit: int = 0
    # First bar on/after entry where High >= entry×1.10 / 1.20; days = calendar days from entry date (same style as days_held)
    date_first_up_10pct: str = ""
    days_held_first_up_10pct: int = 0
    date_first_up_20pct: str = ""
    days_held_first_up_20pct: int = 0
    # Pivot sequence in zone before entry: strong = 2–3 H then 1–2 L
    pivot_run_high: int = 0  # Consecutive H's in zone before trailing L's
    pivot_run_low: int = 0   # Trailing L's in zone (1 or 2)
    pivot_switch_h_to_l: bool = False  # True if pattern "≥2 H then 1–2 L" at end of sequence
    # Adjacent zones for target/stop ideas: band above = next zone up, band below = next zone down
    zone_above_center: float = 0.0   # 0 = none
    zone_below_center: float = 0.0   # 0 = none
    pct_entry_to_bottom_zone_above: float = 0.0  # % from entry to bottom of zone above (target-ish)
    pct_drop_to_top_zone_below: float = 0.0     # % drop from entry to top of zone below (stop-ish)
    # Growth: single-period gain at entry (price today vs price growth_bars days ago), e.g. 33.1 = 33.1% over 3Y
    growth_pct_over_period: Optional[float] = None  # None when insufficient history
    # Displacement: ABS(Close/RollingAvg - 1) at entry bar; filter passes when >= threshold (movement regime)
    displacement_pct_at_entry: Optional[float] = None  # None when filter disabled or insufficient bars
    # Volume at entry (from OHLCV); relative vol = volume_at_entry / avg_volume_10d_at_entry
    volume_at_entry: Optional[float] = None
    avg_volume_10d_at_entry: Optional[float] = None
    rel_vol_at_entry: Optional[float] = None
    # Relative volume on trigger bar (6th-touch / maturity bar), not entry bar
    rel_vol_on_trigger: Optional[float] = None
    # Completed resistance rejections before maturity: probe high in-band (>=10% depth from zl),
    # chop clusters as one episode; clear close below zl counts; close above zu aborts without counting.
    rejection_count_prior: int = 0
    # Other matured BH/BI zones whose bands overlap this trade's band (excludes identical band)
    overlapping_mature_zones_count: int = 0
    # Volume on DI breakout bar / 10d avg volume ending that bar (from OHLCV); None if no breakout bar matched
    rel_vol_at_breakout: Optional[float] = None
    # 14-day ATR at entry bar (day of entering the trade)
    atr_14_at_entry: Optional[float] = None
    # Backtest-only: bar index of entry (open); ATR schedule exits use with atr_pct_at_entry
    entry_bar_index: int = -1
    atr_pct_at_entry: Optional[float] = None  # ATR_14/entry*100 at entry; used when atr_progress>0
    # Per-trigger-bar technical metrics (computed without future bars, for correlation analysis)
    z_score_at_trigger: float = 0.0
    upper_wick_atr_at_trigger: float = 0.0
    # Lower wick size (min(open,close)-low) as multiple of ATR at trigger bar; can indicate rejection of lows / buying pressure
    lower_wick_atr_at_trigger: float = 0.0
    is_20bar_high_at_trigger: int = 0
    is_20bar_low_at_trigger: int = 0
    move_body_atr_at_trigger: float = 0.0
    atr_14_at_trigger: Optional[float] = None
    atr_pct_at_trigger: Optional[float] = None  # ATR_14 / trigger close * 100
    # Enriched from yfinance (at report time): market_cap, sector, industry, beta
    market_cap: Optional[float] = None  # Approx. cap at entry (raw cap scaled by entry/current price when available)
    market_cap_current: Optional[float] = None  # Raw marketCap from yfinance at fetch time (BRT_Summary, etc.)
    sector: Optional[str] = None
    industry: Optional[str] = None
    beta: Optional[float] = None
    # Rolling beta vs benchmark (e.g. SPY) over window ending at entry date; computed when benchmark_df provided
    beta_at_entry: Optional[float] = None
    # Sheet 8-rung ladder (CG..DC): at close_above signal bar, which rung (1-8) holds this trade's zone.
    # 9 = zone not on any rung (aged off / not in sheet memory). 0 = unavailable.
    sheet_ladder_rung_at_signal: int = 0
    # Running all-time high through entry bar (last bar whose High equals max High so far); YYYYMMDD
    last_ath_date_at_entry: str = ""
    trading_days_since_last_ath_at_entry: int = 0
    # Max High over prior 252 trading bars through entry (52-week high); distance below that high in %
    high_52w_at_entry: Optional[float] = None
    dist_to_52w_high_pct: Optional[float] = None
    # 52-week high through trigger bar; distance from trigger close (decision-time filter metric)
    high_52w_at_trigger: Optional[float] = None
    dist_to_52w_high_pct_at_trigger: Optional[float] = None
    # Cumulative history through entry bar (also written to BRT_Closed / BRT_Open)
    had_meteoric_rise_before_entry: int = 0  # 1 if any prior day met rise rule on or before entry
    had_meteoric_fall_before_entry: int = 0  # 1 if any prior day met fall rule on or before entry
    # Excess total return vs SPY (percentage points) at signal bar (day before entry open): Close[t]/Close[t-Lag]-1 minus SPY same.
    spy_compare_1y: Optional[float] = None
    spy_compare_2y: Optional[float] = None
    spy_compare_3y: Optional[float] = None
    # SPY IND_DIFF (bull-bear indicator count) on entry date; side-aligned like symbol IND_DIFF.
    spy_ind_diff_at_entry: Optional[int] = None
    side: str = "LONG"
    # Populated when cfg.use_indicators (keys IND_<id>, IND_<id>_LAST, IND_ENTRY_*_N); see brt_entry_indicators.py.
    entry_indicators: dict[str, str] = field(default_factory=dict)

# Default benchmark and window for point-in-time beta at entry
_BETA_BENCHMARK_TICKER = "SPY"
# Per-process cache: _load_benchmark_local hits this so parallel workers load SPY.csv once per process (~6 loads vs ~N symbols).
_BENCHMARK_CSV_CACHE: dict[str, Optional[pd.DataFrame]] = {}
# Per-process cache: DuckDB SPY load (parallel workers previously reloaded SPY per symbol).
_BENCHMARK_DUCKDB_CACHE: dict[tuple[str, str], Optional[pd.DataFrame]] = {}
# Per-process cache: SPY IND_DIFF by date (built once per worker from cached benchmark_df).
_SPY_IND_DIFF_LOOKUP_CACHE: dict[tuple, Any] = {}
# Set once per worker via ProcessPoolExecutor initializer (parent-built lookup; avoids per-symbol rebuild).
_WORKER_SPY_IND_DIFF_LOOKUP: Optional[Any] = None
_BETA_ROLLING_WINDOW = 252  # trading days (~1 year)
_WEEK52_LOOKBACK = 252  # trading days (~52 weeks)


def _get_spy_ind_diff_lookup(
    benchmark_df: Optional[pd.DataFrame],
    cfg: "BRTConfig",
) -> Any:
    """Return SpyIndDiffByDate for benchmark_df (cached per process). None if SPY unavailable."""
    if benchmark_df is None or benchmark_df.empty:
        return None
    cache_dir = (str(getattr(cfg, "indicator_cache_dir", "") or "").strip() or None)
    use_cache = bool(getattr(cfg, "indicator_cache", True))
    key = ("SPY", cache_dir, use_cache)
    if key not in _SPY_IND_DIFF_LOOKUP_CACHE:
        try:
            from brt_entry_indicators import build_spy_ind_diff_by_date
        except ImportError:
            from stock_analysis.brt_entry_indicators import build_spy_ind_diff_by_date
        _SPY_IND_DIFF_LOOKUP_CACHE[key] = build_spy_ind_diff_by_date(
            benchmark_df, cache_dir=cache_dir, use_cache=use_cache,
        )
    return _SPY_IND_DIFF_LOOKUP_CACHE[key]


def _resolve_spy_ind_diff_lookup(
    cfg: "BRTConfig",
    benchmark_df: Optional[pd.DataFrame],
) -> Any:
    """Return SPY IND_DIFF lookup: worker-global from pool init, else per-process cache build."""
    global _WORKER_SPY_IND_DIFF_LOOKUP
    if _WORKER_SPY_IND_DIFF_LOOKUP is not None:
        return _WORKER_SPY_IND_DIFF_LOOKUP
    return _get_spy_ind_diff_lookup(benchmark_df, cfg)


def _apply_spy_ind_diff_at_entry(
    closed: list["BRTTrade"],
    open_trade: Optional["BRTTrade"],
    extra_opens: Optional[list["BRTTrade"]],
    spy_lookup: Any,
) -> None:
    """Stamp spy_ind_diff_at_entry from precomputed SPY IND_DIFF map."""
    if spy_lookup is None:
        return

    def _stamp(t: "BRTTrade") -> None:
        v = spy_lookup.at_entry(t.date_opened, getattr(t, "side", "LONG") or "LONG")
        if v is not None:
            t.spy_ind_diff_at_entry = v

    for t in closed:
        _stamp(t)
    if open_trade is not None:
        _stamp(open_trade)
    for t in extra_opens or []:
        _stamp(t)


def _rolling_beta_at_entry(
    df: pd.DataFrame,
    entry_bar_index: int,
    benchmark_df: pd.DataFrame,
    window: int = _BETA_ROLLING_WINDOW,
) -> Optional[float]:
    """
    Compute rolling beta (vs benchmark) for the window ending at entry bar.
    Beta = Cov(stock_ret, mkt_ret) / Var(mkt_ret). Returns None if insufficient data or zero market variance.
    Uses only returns on or before the entry bar date so beta is point-in-time at entry.
    """
    if entry_bar_index < 1 or entry_bar_index >= len(df):
        return None
    try:
        entry_date = df.index[entry_bar_index]
        if hasattr(entry_date, "normalize"):
            entry_date = entry_date.normalize()
        else:
            entry_date = pd.Timestamp(entry_date).normalize()

        stock_close = df["Close"]
        stock_ret = stock_close.pct_change().dropna()
        if stock_ret.empty:
            return None
        if "Close" not in benchmark_df.columns:
            return None
        bench_close = benchmark_df["Close"]
        bench_ret = bench_close.pct_change().dropna()
        if bench_ret.empty:
            return None
        # Align by date (normalize to date for join)
        stock_ret = stock_ret.copy()
        stock_ret.index = pd.to_datetime(stock_ret.index).normalize()
        bench_ret = bench_ret.copy()
        bench_ret.index = pd.to_datetime(bench_ret.index).normalize()
        aligned = pd.DataFrame({"s": stock_ret, "m": bench_ret}).dropna(how="any")
        # Restrict to returns on or before entry date (point-in-time at entry)
        aligned = aligned.loc[aligned.index <= entry_date]
        if len(aligned) < min(window, 60):
            return None
        aligned = aligned.tail(window)
        s = aligned["s"].values.astype(np.float64)
        m = aligned["m"].values.astype(np.float64)
        var_m = np.var(m)
        if var_m <= 0:
            return None
        cov_sm = np.cov(s, m)[0, 1]
        return float(cov_sm / var_m)
    except Exception:
        return None


def _precompute_beta_by_bar_index(
    df: pd.DataFrame,
    benchmark_df: pd.DataFrame,
    window: int = _BETA_ROLLING_WINDOW,
) -> np.ndarray:
    """
    For each bar index b (0..n-1), beta matching _rolling_beta_at_entry(df, b, ...) using the same
    aligned returns, tail(window), and min(window,60) row requirement. Vectorized via pandas rolling
    (same numerics as the per-position np.cov / np.var loop: cov ddof=1, var ddof=0).
    """
    n = len(df)
    out = np.full(n, np.nan, dtype=np.float64)
    min_rows = min(window, 60)
    try:
        if "Close" not in benchmark_df.columns:
            return out
        stock_close = df["Close"]
        stock_ret = stock_close.pct_change().dropna()
        bench_close = benchmark_df["Close"]
        bench_ret = bench_close.pct_change().dropna()
        if stock_ret.empty or bench_ret.empty:
            return out
        stock_ret = stock_ret.copy()
        stock_ret.index = pd.to_datetime(stock_ret.index).normalize()
        bench_ret = bench_ret.copy()
        bench_ret.index = pd.to_datetime(bench_ret.index).normalize()
        aligned = pd.DataFrame({"s": stock_ret, "m": bench_ret}).dropna(how="any").sort_index()
        if aligned.empty:
            return out
        L = len(aligned)
        aligned_dates = pd.to_datetime(aligned.index).normalize()
        stock_dates = pd.to_datetime(df.index).normalize()
        # Rolling beta = cov(s,m)/var(m); matches _rolling_beta_at_entry / old loop (np.cov ddof=1, np.var ddof=0)
        rcov = aligned["s"].rolling(window, min_periods=min_rows).cov(aligned["m"])
        rvar = aligned["m"].rolling(window, min_periods=min_rows).var(ddof=0)
        with np.errstate(divide="ignore", invalid="ignore"):
            beta_at_pos = (rcov / rvar).to_numpy(dtype=np.float64)
        rvar_np = rvar.to_numpy(dtype=np.float64)
        beta_at_pos[(~np.isfinite(rvar_np)) | (rvar_np <= 1e-18)] = np.nan
        pos = -1
        for b in range(1, n):
            ed = stock_dates[b]
            while pos + 1 < L and aligned_dates[pos + 1] <= ed:
                pos += 1
            if pos < 0 or pos < min_rows - 1:
                continue
            if aligned_dates[pos] <= ed:
                out[b] = beta_at_pos[pos]
    except Exception:
        return out
    return out


def _realtime_score_value(
    value: float,
    ref_name: str,
    reference_stats: Optional[dict[str, tuple[float, float]]],
    use_zscore: bool,
) -> float:
    """Return value for score: z-score if use_zscore and stats available and std>0, else raw. Handles None/NaN as 0."""
    if value is None or (isinstance(value, float) and (value != value or value == float("inf") or value == float("-inf"))):
        return 0.0
    v = float(value)
    if not use_zscore or not reference_stats or ref_name not in reference_stats:
        return v
    mean, std = reference_stats[ref_name]
    if std is None or std <= 0 or (isinstance(std, float) and std != std):
        return v
    return (v - mean) / std


# Map BRT_Closed Variable name to BRTTrade attribute for computing ref stats from trades
_REF_VAR_TO_ATTR: dict[str, str] = {
    "TOUCH_COUNT_MINOR": "touch_count_minor",
    "ZONE_CLUSTER_DENSITY": "zone_cluster_density",
    "NEARBY_ZONES_ABOVE": "nearby_zones_above",
    "TOUCH_COUNT_MAJOR": "touch_count_major",
    "PCT_ENTRY_TO_BOTTOM_ZONE_ABOVE": "pct_entry_to_bottom_zone_above",
    "NEARBY_ZONES_BELOW": "nearby_zones_below",
    "Z_SCORE_AT_TRIGGER": "z_score_at_trigger",
    "PIVOT_RUN_L_BEFORE_ENTRY": "pivot_run_low",
    "PCT_DROP_TO_TOP_ZONE_BELOW": "pct_drop_to_top_zone_below",
    "REL_VOL_AT_ENTRY": "rel_vol_at_entry",
    "REL_VOL_AT_BREAKOUT": "rel_vol_at_breakout",
    "DISPLACEMENT_PCT_AT_ENTRY": "displacement_pct_at_entry",
    "LOWER_WICK_ATR_AT_TRIGGER": "lower_wick_atr_at_trigger",
    "GROWTH_PCT_OVER_PERIOD": "growth_pct_over_period",
    "BETA_AT_ENTRY": "beta_at_entry",
}


def _realtime_score_for_trade(
    t: BRTTrade,
    cfg: BRTConfig,
    reference_stats: dict[str, tuple[float, float]],
) -> float:
    """Compute the realtime filter score for an existing trade (same formula as at entry). Used when filtering after one pass."""
    use_z = bool(reference_stats)
    score = 0.0
    score += getattr(cfg, "weight_touch_count_minor", 0.0) * _realtime_score_value(getattr(t, "touch_count_minor", 0), "TOUCH_COUNT_MINOR", reference_stats, use_z)
    score += getattr(cfg, "weight_zone_cluster_density", 0.0) * _realtime_score_value(getattr(t, "zone_cluster_density", 0), "ZONE_CLUSTER_DENSITY", reference_stats, use_z)
    score += getattr(cfg, "weight_nearby_zones_above", 0.0) * _realtime_score_value(getattr(t, "nearby_zones_above", 0), "NEARBY_ZONES_ABOVE", reference_stats, use_z)
    score += getattr(cfg, "weight_touch_count_major", 0.0) * _realtime_score_value(getattr(t, "touch_count_major", 0), "TOUCH_COUNT_MAJOR", reference_stats, use_z)
    score += getattr(cfg, "weight_pct_entry_to_bottom_zone_above", 0.0) * _realtime_score_value(getattr(t, "pct_entry_to_bottom_zone_above", 0), "PCT_ENTRY_TO_BOTTOM_ZONE_ABOVE", reference_stats, use_z)
    score += getattr(cfg, "weight_nearby_zones_below", 0.0) * _realtime_score_value(getattr(t, "nearby_zones_below", 0), "NEARBY_ZONES_BELOW", reference_stats, use_z)
    score += getattr(cfg, "weight_z_score_at_trigger", 0.0) * _realtime_score_value(getattr(t, "z_score_at_trigger", 0.0), "Z_SCORE_AT_TRIGGER", reference_stats, use_z)
    score += getattr(cfg, "weight_pivot_run_l_before_entry", 0.0) * _realtime_score_value(getattr(t, "pivot_run_low", 0), "PIVOT_RUN_L_BEFORE_ENTRY", reference_stats, use_z)
    score += getattr(cfg, "weight_pct_drop_to_top_zone_below", 0.0) * _realtime_score_value(getattr(t, "pct_drop_to_top_zone_below", 0), "PCT_DROP_TO_TOP_ZONE_BELOW", reference_stats, use_z)
    score += getattr(cfg, "weight_rel_vol_at_entry", 0.0) * _realtime_score_value(getattr(t, "rel_vol_at_entry", None), "REL_VOL_AT_ENTRY", reference_stats, use_z)
    score += getattr(cfg, "weight_displacement_pct_at_entry", 0.0) * _realtime_score_value(getattr(t, "displacement_pct_at_entry", None), "DISPLACEMENT_PCT_AT_ENTRY", reference_stats, use_z)
    score += getattr(cfg, "weight_lower_wick_atr_at_trigger", 0.0) * _realtime_score_value(getattr(t, "lower_wick_atr_at_trigger", 0.0), "LOWER_WICK_ATR_AT_TRIGGER", reference_stats, use_z)
    score += getattr(cfg, "weight_growth_pct_over_period", 0.0) * _realtime_score_value(getattr(t, "growth_pct_over_period", None), "GROWTH_PCT_OVER_PERIOD", reference_stats, use_z)
    score += getattr(cfg, "weight_beta_at_entry", 0.0) * _realtime_score_value(getattr(t, "beta_at_entry", None), "BETA_AT_ENTRY", reference_stats, use_z)
    return score


def _compute_reference_stats_from_trades(
    closed: list[BRTTrade],
    open_trades: list[BRTTrade],
) -> dict[str, tuple[float, float]]:
    """Compute mean and std for each realtime-filter metric from current-run trades. So z-scores are never one run behind."""
    result: dict[str, tuple[float, float]] = {}
    all_trades = list(closed) + list(open_trades)
    if not all_trades:
        return result
    for ref_name, attr in _REF_VAR_TO_ATTR.items():
        values = []
        for t in all_trades:
            v = getattr(t, attr, None)
            if v is not None and not (isinstance(v, float) and (v != v or v == float("inf") or v == float("-inf"))):
                try:
                    values.append(float(v))
                except (TypeError, ValueError):
                    pass
        if len(values) >= 2:
            arr = np.array(values, dtype=np.float64)
            mean_val = float(np.mean(arr))
            std_val = float(np.std(arr, ddof=0))
            if std_val <= 0:
                std_val = 0.0
            result[ref_name] = (mean_val, std_val)
    return result


def _load_reference_stats(output_dir: Path) -> Optional[dict[str, tuple[float, float]]]:
    """Load BRT_ReferenceStats.csv (Variable, Mean, Std) from output_dir. Returns {Variable: (mean, std)} or None if missing. Used for z-score weighting in realtime filter."""
    path = Path(output_dir) / "BRT_ReferenceStats.csv"
    if not path.exists():
        return None
    try:
        ref = pd.read_csv(path, low_memory=False)
        if "Variable" not in ref.columns:
            return None
        result: dict[str, tuple[float, float]] = {}
        for _, row in ref.iterrows():
            var = str(row.get("Variable", "")).strip()
            if not var:
                continue
            mean_val = row.get("Mean", 0.0)
            std_val = row.get("Std", 0.0)
            if pd.isna(mean_val) or mean_val == "":
                mean_val = 0.0
            if pd.isna(std_val) or std_val == "" or (isinstance(std_val, (int, float)) and std_val <= 0):
                std_val = 0.0
            try:
                result[var] = (float(mean_val), float(std_val))
            except (TypeError, ValueError):
                continue
        return result if result else None
    except Exception:
        return None


def _load_benchmark_local(data_dir: Path) -> Optional[pd.DataFrame]:
    """Load benchmark OHLC from local SPY.csv in data_dir (e.g. data/newdata/data). Returns DataFrame with Date index and Close column, or None if missing.

    Cached per resolved data_dir string per process (safe with ProcessPoolExecutor: each worker caches once).
    """
    try:
        cache_key = str(Path(data_dir).resolve())
    except Exception:
        cache_key = str(data_dir)
    if cache_key in _BENCHMARK_CSV_CACHE:
        return _BENCHMARK_CSV_CACHE[cache_key]

    spypath = data_dir / f"{_BETA_BENCHMARK_TICKER}.csv"
    if not spypath.exists():
        _BENCHMARK_CSV_CACHE[cache_key] = None
        return None
    try:
        bench = load_csv(str(spypath))
        if bench is None or bench.empty or "Close" not in bench.columns:
            _BENCHMARK_CSV_CACHE[cache_key] = None
            return None
        _BENCHMARK_CSV_CACHE[cache_key] = bench
        return bench
    except Exception:
        _BENCHMARK_CSV_CACHE[cache_key] = None
        return None


def _load_benchmark_duckdb(db_path: str, db_table: str) -> Optional[pd.DataFrame]:
    """Load SPY from DuckDB once per worker process (cached)."""
    key = (str(db_path or ""), str(db_table or "prices"))
    if key in _BENCHMARK_DUCKDB_CACHE:
        return _BENCHMARK_DUCKDB_CACHE[key]
    df: Optional[pd.DataFrame] = None
    if _db_load_symbol_df is not None:
        try:
            df = _db_load_symbol_df("SPY", db_path=db_path, table=db_table)
        except Exception:
            df = None
    if df is not None and not df.empty and "Close" in df.columns:
        _BENCHMARK_DUCKDB_CACHE[key] = df
        return df
    _BENCHMARK_DUCKDB_CACHE[key] = None
    return None


def _load_benchmark_unified(
    *,
    use_duckdb: bool,
    db_path: str,
    db_table: str,
    data_dir: Path,
) -> Optional[pd.DataFrame]:
    """Load SPY benchmark from CSV or DuckDB with per-process caching."""
    if use_duckdb:
        db_file = db_path
        if not db_file and _db_resolve_path is not None:
            try:
                db_file = str(_db_resolve_path(data_dir, "", db_table))
            except Exception:
                db_file = ""
        return _load_benchmark_duckdb(db_file, db_table)
    return _load_benchmark_local(data_dir)


def _brt_pool_worker_init(
    spy_lookup: Any,
    use_duckdb: bool,
    db_path: str,
    db_table: str,
    data_dir_s: str,
) -> None:
    """ProcessPoolExecutor initializer: inject parent SPY IND_DIFF lookup and warm benchmark cache."""
    global _WORKER_SPY_IND_DIFF_LOOKUP
    _WORKER_SPY_IND_DIFF_LOOKUP = spy_lookup
    try:
        _load_benchmark_unified(
            use_duckdb=bool(use_duckdb),
            db_path=str(db_path or ""),
            db_table=str(db_table or "prices"),
            data_dir=Path(data_dir_s),
        )
    except Exception:
        pass


def _make_brt_process_pool(
    n_workers: int,
    spy_lookup: Any,
    *,
    use_duckdb: bool,
    db_path: str,
    db_table: str,
    data_dir: Path,
) -> ProcessPoolExecutor:
    return ProcessPoolExecutor(
        max_workers=n_workers,
        initializer=_brt_pool_worker_init,
        initargs=(
            spy_lookup,
            bool(use_duckdb),
            str(db_path or ""),
            str(db_table or "prices"),
            str(data_dir),
        ),
    )


# Relative strength vs SPY: trading-bar horizons (aligned calendar rows on stock dates).
_RS_SPY_LAG_1Y = 252
_RS_SPY_LAG_2Y = 504
_RS_SPY_LAG_3Y = 756
_INDICATOR_ONLY_MIN_BARS = 220


def _indicator_only_mode(cfg: Any) -> bool:
    """Pure indicator entry: IND_DIFF gate only (no zone maturity / retest / relative strength)."""
    return (
        _normalize_indicator_buy(getattr(cfg, "indicator_buy", "off")) == "only"
        and not bool(getattr(cfg, "relative_strength_enabled", False))
    )


def _skip_brt_pivot_stack(cfg: Any) -> bool:
    """Skip pivot/structure/touch when entry uses RS or indicator-only scan."""
    return bool(getattr(cfg, "relative_strength_enabled", False)) or _indicator_only_mode(cfg)


def _min_bars_required_for_cfg(cfg: Any) -> int:
    """Minimum OHLC rows for backtest (pivot stack vs relative-strength / indicator-only horizons)."""
    if bool(getattr(cfg, "relative_strength_enabled", False)):
        return _RS_SPY_LAG_3Y + 10
    if _indicator_only_mode(cfg):
        return _INDICATOR_ONLY_MIN_BARS
    base = int(getattr(cfg, "pivot_k", 4)) + int(getattr(cfg, "pivot_m", 4)) + 10
    if bool(getattr(cfg, "yh_zones", True)):
        yh_lb = int(getattr(cfg, "yh_lookback", 252) or 252)
        base = max(base, yh_lb + 20)
    return base


def _resolve_brt_worker_count(workers_arg: int) -> int:
    """Map CLI ``-w`` to process count (0 = sequential)."""
    w = int(workers_arg)
    if w < 0:
        w = min(8, os.cpu_count() or 4)
    elif w > 0:
        w = min(w, os.cpu_count() or 4)
    return max(0, w)


def _filter_duckdb_symbols_to_universe(symbols: list[str], data_dir: Path) -> list[str]:
    """Drop DuckDB symbols that are not in pygetallMore and/or lack a CSV file."""
    if _db_filter_symbols_to_universe is None:
        return sorted(symbols)
    kept, excluded = _db_filter_symbols_to_universe(symbols, data_dir)
    if excluded:
        preview = ", ".join(excluded[:12])
        more = f" (+{len(excluded) - 12} more)" if len(excluded) > 12 else ""
        print(
            f"[BRT] DuckDB universe check: excluded {len(excluded)} symbol(s) "
            f"not in pygetallMore and/or missing CSV: {preview}{more}",
            flush=True,
        )
    return kept


def _list_duckdb_backtest_symbols(
    cfg: Any,
    *,
    db_path: str,
    db_table: str,
    data_dir: Path,
) -> list[str]:
    """Symbol list for parallel DuckDB backtest without loading OHLCV in the parent."""
    if _db_list_symbols is None:
        raise RuntimeError("DuckDB loader is unavailable.")
    symbols = _db_list_symbols(db_path=db_path, table=db_table, include_spy=False)
    symbols = _filter_duckdb_symbols_to_universe(symbols, data_dir)
    min_req = _min_bars_required_for_cfg(cfg)
    counts: dict[str, int] = {}
    if _db_symbol_bar_counts is not None:
        try:
            counts = _db_symbol_bar_counts(db_path=db_path, table=db_table, include_spy=False)
        except Exception:
            counts = {}
    if counts:
        return sorted(s for s in symbols if counts.get(s, 0) >= min_req)
    return sorted(symbols)


def _align_stock_spy_close_for_rs(df: pd.DataFrame, spy_df: Optional[pd.DataFrame]) -> Optional[tuple[np.ndarray, np.ndarray]]:
    """Stock Close and SPY Close aligned to df.index (NaN where SPY has no row for that date)."""
    if spy_df is None or spy_df.empty or "Close" not in spy_df.columns or "Close" not in df.columns:
        return None
    st = df["Close"].to_numpy(dtype=np.float64)
    sp_series = spy_df["Close"].copy()
    sp_series.index = pd.to_datetime(sp_series.index).normalize()
    dxi = pd.to_datetime(df.index).normalize()
    sp_re = sp_series.reindex(dxi).to_numpy(dtype=np.float64)
    return (st, sp_re)


def _rs_total_returns(
    st: np.ndarray, sp: np.ndarray, t: int, lag: int
) -> tuple[Optional[float], Optional[float]]:
    """Fractional total returns for stock and SPY from bar t-lag to bar t (inclusive endpoints)."""
    if t < lag or lag < 1 or t >= len(st) or t >= len(sp):
        return None, None
    sb, se = float(st[t - lag]), float(st[t])
    pb, pe = float(sp[t - lag]), float(sp[t])
    if not (np.isfinite(sb) and sb > 0 and np.isfinite(se) and np.isfinite(pb) and pb > 0 and np.isfinite(pe)):
        return None, None
    return (se / sb - 1.0), (pe / pb - 1.0)


def _rs_excess_pct_points(st: np.ndarray, sp: np.ndarray, t: int) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Excess total return vs SPY in percentage points at bar t for ~1y / ~2y / ~3y (252/504/756 trading bars)."""
    e1 = e2 = e3 = None
    r1s, r1p = _rs_total_returns(st, sp, t, _RS_SPY_LAG_1Y)
    if r1s is not None and r1p is not None:
        e1 = (r1s - r1p) * 100.0
    r2s, r2p = _rs_total_returns(st, sp, t, _RS_SPY_LAG_2Y)
    if r2s is not None and r2p is not None:
        e2 = (r2s - r2p) * 100.0
    r3s, r3p = _rs_total_returns(st, sp, t, _RS_SPY_LAG_3Y)
    if r3s is not None and r3p is not None:
        e3 = (r3s - r3p) * 100.0
    return e1, e2, e3


def _rs_pass_all_horizons_vs_spy(st: np.ndarray, sp: np.ndarray, t: int) -> bool:
    """True iff stock beats SPY on 1y, 2y, and 3y total return (strictly greater) at bar t."""
    e1, e2, e3 = _rs_excess_pct_points(st, sp, t)
    return e1 is not None and e2 is not None and e3 is not None and e1 > 0 and e2 > 0 and e3 > 0


def _trade_ymd_to_bar_index(index_iso: list[str], date_s: str) -> Optional[int]:
    """Match BRTTrade date strings (YYYY-MM-DD or YYYYMMDD) to index_iso bar position."""
    if not date_s or not str(date_s).strip():
        return None
    s = str(date_s).strip()
    if len(s) >= 10 and s[4] == "-":
        ymd = s[:10].replace("-", "")
    else:
        ymd = "".join(ch for ch in s if ch.isdigit())[:8]
    if len(ymd) != 8:
        return None
    for i, iso in enumerate(index_iso):
        if len(iso) >= 8 and iso[:8] == ymd:
            return i
    return None


def _running_ath_last_bar_index(high_arr: np.ndarray, entry_bar: int) -> tuple[int, int]:
    """
    Through ``entry_bar`` (inclusive), all-time high is ``max(High[0:entry_bar+1])``.
    Return the **last** bar index whose High equals that maximum, and the number of trading
    bars from that bar to ``entry_bar`` (0 if entry is on the ATH bar).
    """
    if entry_bar < 0:
        return (-1, 0)
    n = len(high_arr)
    if n == 0:
        return (-1, 0)
    eb = min(int(entry_bar), n - 1)
    seg = high_arr[: eb + 1]
    if seg.size == 0:
        return (-1, 0)
    last_ath = int(eb - int(np.argmax(seg[::-1])))
    return (last_ath, eb - last_ath)


def _high_52w_and_dist_pct(
    high_arr: np.ndarray, entry_bar: int, entry_price: float
) -> tuple[Optional[float], Optional[float]]:
    """
    52-week high = max(High) over the last 252 trading bars through entry_bar (inclusive).
    Distance = (high_52w - entry_price) / high_52w * 100; 0 at the high, larger when further below.
    """
    if entry_bar < 0:
        return None, None
    n = len(high_arr)
    if n == 0:
        return None, None
    eb = min(int(entry_bar), n - 1)
    start = max(0, eb - _WEEK52_LOOKBACK + 1)
    seg = high_arr[start : eb + 1]
    if seg.size == 0:
        return None, None
    hi_52 = float(np.nanmax(seg))
    if not np.isfinite(hi_52) or hi_52 <= 0:
        return None, None
    if entry_price <= 0 or not np.isfinite(entry_price):
        return hi_52, None
    dist = max(0.0, (hi_52 - entry_price) / hi_52 * 100.0)
    return hi_52, dist


def _atr_14_and_pct_at_bar(
    atr_14_arr: np.ndarray,
    price_arr: np.ndarray,
    bar_i: int,
) -> tuple[Optional[float], Optional[float]]:
    """ATR14 and (ATR14 / bar close) × 100 at ``bar_i`` (trigger-day style)."""
    if bar_i < 0 or bar_i >= len(atr_14_arr) or bar_i >= len(price_arr):
        return None, None
    a14 = float(atr_14_arr[bar_i])
    px = float(price_arr[bar_i])
    if not (np.isfinite(a14) and np.isfinite(px) and px > 0):
        return None, None
    return a14, (a14 / px) * 100.0


def _precompute_meteoric_cumulative_flags(
    close_arr: np.ndarray,
    low_arr: np.ndarray,
    high_arr: np.ndarray,
    rise_pct: float,
    rise_n: int,
    fall_pct: float,
    fall_y: int,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Per bar i (inclusive): whether **any** prior bar j<=i had a "meteoric rise" or "meteoric fall" day.

    Rise day j: over the prior ``rise_n`` trading bars ending at j (inclusive), let L = min(Low).
    Trigger if Close[j] >= L * (1 + rise_pct/100). Default rise_pct=300 => close is 4x the N-day low.

    Fall day j: over the prior ``fall_y`` bars ending at j, let H = max(High).
    Trigger if Close[j] <= H * (1 - fall_pct/100). Default fall_pct=50 => close is at or below half the Y-day high.

    Returns int8 arrays length n (0/1), cumulative "ever so far" — once 1, stays 1 (no need to re-check past).
    """
    n = len(close_arr)
    rise_ever = np.zeros(n, dtype=np.int8)
    fall_ever = np.zeros(n, dtype=np.int8)
    if n == 0:
        return rise_ever, fall_ever
    rise_n = int(rise_n)
    fall_y = int(fall_y)
    rise_trigger = np.zeros(n, dtype=bool)
    fall_trigger = np.zeros(n, dtype=bool)
    rp = float(rise_pct)
    fp = float(fall_pct)
    if rise_n >= 2 and rp > -100.0 + 1e-12 and n >= rise_n:
        try:
            from numpy.lib.stride_tricks import sliding_window_view

            win_lo = sliding_window_view(low_arr, rise_n)
            roll_min = win_lo.min(axis=1)
            thr = roll_min * (1.0 + rp / 100.0)
            c_slice = close_arr[rise_n - 1 :]
            rise_trigger[rise_n - 1 :] = (roll_min > 0) & (c_slice >= thr)
        except Exception:
            for i in range(rise_n - 1, n):
                lo_win = float(np.min(low_arr[i - rise_n + 1 : i + 1]))
                if lo_win > 0:
                    rise_trigger[i] = close_arr[i] >= lo_win * (1.0 + rp / 100.0)
    if fall_y >= 2 and 0.0 < fp < 100.0 - 1e-12 and n >= fall_y:
        try:
            from numpy.lib.stride_tricks import sliding_window_view

            win_hi = sliding_window_view(high_arr, fall_y)
            roll_max = win_hi.max(axis=1)
            thr_f = roll_max * (1.0 - fp / 100.0)
            c2 = close_arr[fall_y - 1 :]
            fall_trigger[fall_y - 1 :] = (roll_max > 0) & (c2 <= thr_f)
        except Exception:
            for i in range(fall_y - 1, n):
                hi_win = float(np.max(high_arr[i - fall_y + 1 : i + 1]))
                if hi_win > 0:
                    fall_trigger[i] = close_arr[i] <= hi_win * (1.0 - fp / 100.0)
    rz = 0
    fz = 0
    for i in range(n):
        if rise_trigger[i]:
            rz = 1
        if fall_trigger[i]:
            fz = 1
        rise_ever[i] = rz
        fall_ever[i] = fz
    return rise_ever, fall_ever


def _brt_active_zone_maturity_bar(
    at_i: int,
    pending_maturities: list[dict],
    high_arr: np.ndarray,
    low_arr: np.ndarray,
) -> Optional[int]:
    if at_i < 0:
        return None
    hi_i = float(high_arr[at_i])
    lo_i = float(low_arr[at_i])
    overlapping: list[tuple[int, int]] = []
    for _p in pending_maturities:
        mb = int(_p.get("maturity_bar", -1))
        zl = _p.get("zone_low", float("nan"))
        zh = _p.get("zone_high", float("nan"))
        if mb < 0 or pd.isna(zl) or pd.isna(zh):
            continue
        if hi_i >= float(zl) and lo_i <= float(zh):
            overlapping.append((mb, mb))
    if not overlapping:
        return None
    overlapping.sort(reverse=True)
    return overlapping[0][1]


def _precompute_sheet_active_zone_arrays(
    high_arr: np.ndarray,
    low_arr: np.ndarray,
    mat_bh: np.ndarray,
    mat_bi: np.ndarray,
    n: int,
    cfg: BRTConfig,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Sheet DK/DL/DM/DN by scanning matured CE/CF (unlimited) or the N newest zones.

    Unlimited (``mts_active_zone_max_rungs=0``) matches the sheet FILTER/MAX formulas::

        DM = MAX(row j) where CE[j] valid and bar overlaps [CE[j], CF[j]]
        DK/DL = CE/DM, CF/DM
        DN = COUNT(CE from DM row through current row)

    Capped mode keeps only the ``max_rungs`` most-recently-matured zones before overlap scan
    (legacy 10-rung CG:DJ ladder behaviour).

    ``mts_active_zone_pick_mode=hybrid_overlap_low`` (MTS parity preset): among zones overlapping
    the bar with ``i >= j`` (same-bar maturity allowed), pick overlap-only max DN unless
    low-inside max DN is within ``mts_active_zone_hybrid_dn_slack`` DN counts, then pick
    low-inside max DN.
    """
    de = np.full(n, np.nan, dtype=np.float64)
    df = np.full(n, np.nan, dtype=np.float64)
    dg = np.full(n, np.nan, dtype=np.float64)
    ds = np.full(n, np.nan, dtype=np.float64)
    zone_cmp_round = _cfg_overlap_compare_round_decimals(cfg)
    high_64 = np.asarray(high_arr, dtype=np.float64)
    low_64 = np.asarray(low_arr, dtype=np.float64)
    ce_all = np.asarray(mat_bh, dtype=np.float64)
    cf_all = np.asarray(mat_bi, dtype=np.float64)
    if zone_cmp_round >= 0:
        high_rnd = np.round(high_64, zone_cmp_round)
        low_rnd = np.round(low_64, zone_cmp_round)
    else:
        high_rnd = high_64
        low_rnd = low_64

    max_rungs = int(getattr(cfg, "mts_active_zone_max_rungs", 0) or 0)
    for i in range(n):
        hi_i = float(high_rnd[i])
        lo_i = float(low_rnd[i])
        # Collect matured-zone bar indices up to i (CE/CF appear on maturity bar).
        matured_js = [
            j for j in range(i + 1)
            if np.isfinite(ce_all[j]) and np.isfinite(cf_all[j]) and ce_all[j] > 0 and cf_all[j] > 0
        ]
        if max_rungs > 0 and len(matured_js) > max_rungs:
            matured_js = matured_js[-max_rungs:]
        pick_mode = str(
            getattr(cfg, "mts_active_zone_pick_mode", "maxj") or "maxj"
        ).strip().lower()
        hybrid_slack = max(
            0, int(getattr(cfg, "mts_active_zone_hybrid_dn_slack", 2) or 2)
        )
        cands: list[tuple[int, float, float, int, bool]] = []
        for j in matured_js:
            ce = float(ce_all[j])
            cf = float(cf_all[j])
            if zone_cmp_round >= 0:
                zlr = round(ce, zone_cmp_round)
                zur = round(cf, zone_cmp_round)
            else:
                zlr, zur = ce, cf
            if not (hi_i >= zlr and lo_i <= zur):
                continue
            # Sheet MAX(FILTER(ROW(CE)...)) includes same-bar maturity (i == j).
            if i < j:
                continue
            cnt = 0
            for k in range(j, i + 1):
                if np.isfinite(ce_all[k]) and ce_all[k] > 0:
                    cnt += 1
            low_in = zlr <= lo_i <= zur
            cands.append((j, ce, cf, cnt, low_in))
        if not cands:
            continue
        if pick_mode in ("hybrid2", "hybrid_overlap_low"):
            ins = [c for c in cands if c[4]]
            ov = [c for c in cands if not c[4]]
            if ins and ov:
                ov_max = max(x[3] for x in ov)
                ins_max = max(x[3] for x in ins)
                if 0 <= ov_max - ins_max <= hybrid_slack:
                    best_j, best_zl, best_zu, _, _ = max(ins, key=lambda x: x[3])
                else:
                    best_j, best_zl, best_zu, _, _ = max(ov, key=lambda x: x[3])
            elif ov:
                best_j, best_zl, best_zu, _, _ = max(ov, key=lambda x: x[3])
            elif ins:
                best_j, best_zl, best_zu, _, _ = max(ins, key=lambda x: x[3])
            else:
                continue
        elif pick_mode == "maxj_lowin_ov_slack":
            best_j, best_zl, best_zu, best_cnt, low_in = max(cands, key=lambda x: x[0])
            if low_in:
                ov = [c for c in cands if not c[4]]
                if ov:
                    ov_max = max(x[3] for x in ov)
                    if ov_max - best_cnt > hybrid_slack:
                        best_j, best_zl, best_zu, _, _ = max(ov, key=lambda x: x[3])
        else:
            best_j, best_zl, best_zu, _, _ = max(cands, key=lambda x: x[0])
        de[i] = best_zl
        df[i] = best_zu
        dg[i] = float(best_j)
        cnt = 0
        for k in range(best_j, i + 1):
            if np.isfinite(ce_all[k]) and ce_all[k] > 0:
                cnt += 1
        ds[i] = float(cnt)
    return de, df, dg, ds


def _precompute_mts_bi_gates(
    open_arr: np.ndarray,
    high_arr: np.ndarray,
    low_arr: np.ndarray,
    close_arr: np.ndarray,
    de_ctx: np.ndarray,   # DK Active zone lower
    df_ctx: np.ndarray,   # DL Active zone upper
    dg_ctx: np.ndarray,   # DM Active zone available (maturity) row
    ds_ctx: np.ndarray,   # DN Active zone ID
    mat_bh: np.ndarray,   # CE Matured zone lower ( = CD*(1-C5) )
    mat_bi: np.ndarray,   # CF Matured zone upper ( = CD*(1+C5) )
    n: int,
    cfg: BRTConfig,
) -> dict[str, np.ndarray]:
    """Exact STONK_DATA MTS-tab buy gate (column BI) and its sub-gates.

    Faithful to the sheet row formulas (active zone = DK/DL/DM/DN)::

        CD Matured touch price = CE / (1 - C5)                    (blank where no matured zone)
        AK Support test      = active zone AND row>DM AND Close[-1]>DL AND Low<=DL AND High>=DK
        AM Support Evidence  = COUNTIFS(AK=TRUE, DN=DN[i]) over [i-C10, i] >= C6
        AQ Zone Eligible     = AM=TRUE
        AR Rolling touch cnt = COUNTIFS(DK<=CD<=DL) over [i-C10, i]   (blank where no active zone)
        AW magic-touch event = N(AR)>=C6 AND (N(AR[-1])<C6 OR DN[i]<>DN[i-1])
        BG Level Acceptance  = (AK[i] OR AK[i-1]) AND COUNT(Close[i-9..i] > (AK[i]?DK[i]:DK[i-1])) >= C8(7)
        BC Range Qualifier   = AW[i] AND row>C24 AND (MAX(High[i-C24-1..i]) / MIN(Low[..]) - 1) > C7
        BW Growth 3 Year     = Close[i] >= Close[i-756] (sheet ROW()-756; slack when CSV start < 756 bars)
        BE Close above open  = Close[i] > Open[i]
        BI MTS buy = AND(BW, OR(BC[i],BC[i-1]), BE, BG, OR(AQ[i],AQ[i-1]))

    Live MTS tab (TSLA 2021-12-21): BI may be TRUE while AW is FALSE — OR(BC,BC[-1]) can pass from a
    prior AW bar's BC. Ledger entries: DP first-touch creates pending; BI on eval bar; fill next open.
    """
    c5 = float(getattr(cfg, "band_pct", 0.02))
    c6 = int(getattr(cfg, "touch_threshold", 2))
    c7 = float(getattr(cfg, "tight_range_threshold_pct", 0.35))
    c10 = max(1, int(getattr(cfg, "lookback_long", 503)))
    # AM (Support Evidence) window. Sheet: COUNTIFS(AK, MAX(2,ROW()-C10):ROW(); DN=DN[i]) >= C6.
    am_win = max(1, int(getattr(cfg, "mts_support_evidence_window_bars", 0) or 0) or c10)
    c24 = max(1, int(getattr(cfg, "tight_range_lookback", 105)))
    la_win = max(1, int(getattr(cfg, "level_acceptance_window", 10)))
    la_req = max(1, int(getattr(cfg, "level_acceptance_required", 7)))
    growth_bars = max(1, int(getattr(cfg, "growth_bars", 756)))

    o = np.asarray(open_arr, dtype=np.float64)
    h = np.asarray(high_arr, dtype=np.float64)
    lo = np.asarray(low_arr, dtype=np.float64)
    c = np.asarray(close_arr, dtype=np.float64)
    dk = np.asarray(de_ctx, dtype=np.float64)
    dl = np.asarray(df_ctx, dtype=np.float64)
    dm = np.asarray(dg_ctx, dtype=np.float64)
    dn = np.asarray(ds_ctx, dtype=np.float64)

    # CD Matured touch price: reconstruct from CE (matured zone lower). Blank where no matured zone.
    ce = np.asarray(mat_bh, dtype=np.float64)
    cd = np.full(n, np.nan, dtype=np.float64)
    denom = (1.0 - c5)
    if abs(denom) > 1e-12:
        for i in range(n):
            if np.isfinite(ce[i]) and ce[i] > 0:
                cd[i] = ce[i] / denom

    ak = np.zeros(n, dtype=bool)   # AK Support test
    for i in range(1, n):
        if not (np.isfinite(dk[i]) and np.isfinite(dl[i]) and np.isfinite(dm[i])):
            continue
        if i > dm[i] and c[i - 1] > dl[i] and lo[i] <= dl[i] and h[i] >= dk[i]:
            ak[i] = True

    am = np.zeros(n, dtype=bool)   # AM Support Evidence: COUNTIFS(AK, DN) over C10 >= C6
    am_cnt = np.zeros(n, dtype=np.int32)
    am_min = max(1, c6)
    for i in range(n):
        if not np.isfinite(dn[i]):
            continue
        s = max(0, i - am_win)
        cnt = 0
        for k in range(s, i + 1):
            if ak[k] and np.isfinite(dn[k]) and dn[k] == dn[i]:
                cnt += 1
        am_cnt[i] = cnt
        am[i] = cnt >= am_min
    aq = am.copy()                 # AQ Zone Eligible Long = AM

    # AR Long-window rolling touch count: COUNTIFS(CD in [DK,DL] over C10 window).
    ar = np.zeros(n, dtype=np.int64)   # 0 where no active zone (sheet blank -> N()=0)
    ar_active = np.zeros(n, dtype=bool)
    for i in range(n):
        if not (np.isfinite(dk[i]) and np.isfinite(dl[i])):
            continue
        ar_active[i] = True
        dk_lo = float(dk[i])
        dk_hi = float(dl[i])
        s = max(0, i - c10)
        cnt = 0
        for k in range(s, i + 1):
            if np.isfinite(cd[k]) and cd[k] >= dk_lo and cd[k] <= dk_hi:
                cnt += 1
        ar[i] = cnt

    # AW magic-touch event: N(AR)>=C6 AND (N(AR[-1])<C6 OR zone id changed).
    aw = np.zeros(n, dtype=bool)
    for i in range(n):
        if ar[i] == 0:  # N(AR)=0 -> sheet blank / FALSE
            continue
        prev_ar = ar[i - 1] if i >= 1 else 0
        zone_changed = (i >= 1) and (
            (np.isfinite(dn[i]) != np.isfinite(dn[i - 1]))
            or (np.isfinite(dn[i]) and np.isfinite(dn[i - 1]) and dn[i] != dn[i - 1])
        )
        if ar[i] >= c6 and (prev_ar < c6 or zone_changed):
            aw[i] = True

    bg = np.zeros(n, dtype=bool)   # BG Level Acceptance
    for i in range(n):
        akt = ak[i]
        aky = ak[i - 1] if i >= 1 else False
        if not (akt or aky):
            continue
        anchor = dk[i] if akt else (dk[i - 1] if i >= 1 else float("nan"))
        if not np.isfinite(anchor):
            continue
        s = max(0, i - (la_win - 1))
        if int(np.sum(c[s : i + 1] > anchor)) >= la_req:
            bg[i] = True

    # BC Range Qualifier: AW-gated (blank when no magic touch); row > C24.
    bc = np.zeros(n, dtype=bool)
    for i in range(n):
        if not aw[i]:
            continue
        s = i - c24 - 1
        if s < 0:
            continue
        wl = float(np.min(lo[s : i + 1]))
        wh = float(np.max(h[s : i + 1]))
        if wl > 0 and (wh / wl - 1.0) > c7:
            bc[i] = True

    bw = np.zeros(n, dtype=bool)   # BW Growth 3 Year (sheet INDEX close, ROW()-756)
    for i in range(n):
        ago = _growth_ago_bar_index(i, cfg)
        if ago >= 0 and c[i] >= c[ago]:
            bw[i] = True

    be = c > o                     # BE Close above open

    bi = np.zeros(n, dtype=bool)   # BI MTS buy
    for i in range(n):
        bc_ok = bc[i] or (bc[i - 1] if i >= 1 else False)
        aq_ok = aq[i] or (aq[i - 1] if i >= 1 else False)
        if bw[i] and bc_ok and be[i] and bg[i] and aq_ok:
            bi[i] = True

    return {
        "ak": ak, "am": am, "am_cnt": am_cnt, "aq": aq, "ar": ar, "aw": aw,
        "bg": bg, "bc": bc, "bw": bw, "be": be, "bi": bi,
    }


def _zone_touch_metrics_at_signal(
    eval_bar: int,
    maturity_bar: int,
    *,
    touch_count_long_arr: np.ndarray,
    touch_count_short_arr: Optional[np.ndarray] = None,
    mts_ar_arr: Optional[np.ndarray] = None,
    mts_ak_arr: Optional[np.ndarray] = None,
    mts_am_cnt_arr: Optional[np.ndarray] = None,
    ds_ctx_arr: Optional[np.ndarray] = None,
    index_iso: Optional[list[str]] = None,
) -> dict[str, int]:
    """Sheet-aligned zone touch metrics for the active band at the entry signal bar."""
    eb = int(eval_bar)
    mb = int(maturity_bar)
    tc_mat = int(touch_count_long_arr[mb]) if 0 <= mb < len(touch_count_long_arr) else 0
    tc_short_mat = 0
    if touch_count_short_arr is not None and 0 <= mb < len(touch_count_short_arr):
        tc_short_mat = int(touch_count_short_arr[mb])
    zone_rolling = int(mts_ar_arr[eb]) if mts_ar_arr is not None and 0 <= eb < len(mts_ar_arr) else 0
    support_at_signal = int(mts_ak_arr[eb]) if mts_ak_arr is not None and 0 <= eb < len(mts_ak_arr) else 0
    support_count = int(mts_am_cnt_arr[eb]) if mts_am_cnt_arr is not None and 0 <= eb < len(mts_am_cnt_arr) else 0
    zone_dn = 0
    if ds_ctx_arr is not None and 0 <= eb < len(ds_ctx_arr) and np.isfinite(ds_ctx_arr[eb]):
        zone_dn = int(ds_ctx_arr[eb])
    days_since_mat = 0
    if index_iso is not None and 0 <= eb < len(index_iso) and 0 <= mb < len(index_iso):
        sig_iso = str(index_iso[eb])[:8]
        mat_iso = str(index_iso[mb])[:8]
        if len(sig_iso) >= 8 and len(mat_iso) >= 8:
            try:
                sig_ts = pd.Timestamp(f"{sig_iso[:4]}-{sig_iso[4:6]}-{sig_iso[6:8]}")
                mat_ts = pd.Timestamp(f"{mat_iso[:4]}-{mat_iso[4:6]}-{mat_iso[6:8]}")
                days_since_mat = max(0, int((sig_ts - mat_ts).days))
            except (TypeError, ValueError):
                days_since_mat = max(0, eb - mb)
        else:
            days_since_mat = max(0, eb - mb)
    return {
        "zone_rolling_touches": zone_rolling,
        "support_test_count": support_count,
        "support_test_at_signal": support_at_signal,
        "touch_count_at_maturity": tc_mat,
        "touch_count_short_at_maturity": tc_short_mat,
        "zone_episode_dn": zone_dn,
        "days_since_maturity": days_since_mat,
    }


def _precompute_sheet_growth_ok(
    high_arr: np.ndarray,
    close_arr: np.ndarray,
    n: int,
    cfg: BRTConfig,
) -> np.ndarray:
    """Sheet BW: >=2 of 1Y/2Y/3Y growth flags (Close >= C25/C26 * rolling MAX(High))."""
    out = np.zeros(n, dtype=bool)
    c25 = float(getattr(cfg, "ath_filter_c25", 0.3))
    c26 = float(getattr(cfg, "ath_filter_c26", 0.6))
    windows = (252, 504, 756)
    thresholds = (c25, c25, c26)
    high_64 = np.asarray(high_arr, dtype=np.float64)
    close_64 = np.asarray(close_arr, dtype=np.float64)
    for i in range(n):
        flags = 0
        for w, thr in zip(windows, thresholds):
            if i < w - 1:
                continue
            mx = float(np.max(high_64[i - w + 1 : i + 1]))
            if mx > 0 and close_64[i] >= thr * mx:
                flags += 1
        out[i] = flags >= 2
    return out


def _sheet_start_bar_index(index_iso: list[str], start_date: str) -> int:
    s = str(start_date or "").strip().replace("-", "")[:8]
    if len(s) != 8:
        return 0
    for i, iso in enumerate(index_iso):
        if len(iso) >= 8 and iso[:8] >= s:
            return i
    return len(index_iso)


def _brt_make_entry_gate_query_fns(
    *,
    use_sheet_zone_ctx: bool,
    st_on: bool,
    cfg: BRTConfig,
    close_arr: np.ndarray,
    low_arr: np.ndarray,
    high_arr: np.ndarray,
    de_ctx: Optional[np.ndarray],
    df_ctx: Optional[np.ndarray],
    dg_ctx: Optional[np.ndarray],
    ds_ctx: Optional[np.ndarray],
    zone_low_fb: float,
    zone_upper_fb: float,
    maturity_bar_fb: int,
) -> tuple[
    Callable[[int], tuple[bool, float, float, int, float]],
    Callable[[int, float, float], bool],
    Callable[[tuple[bool, float, float, int, float], tuple[bool, float, float, int, float]], bool],
    Callable[[int], bool],
    Callable[[int], bool],
    Callable[[int], bool],
]:
    """Shared AK / resistance / AQ helpers for pending-zone gates (sheet ladder or per-maturity fallback)."""
    aq_window = max(1, int(getattr(cfg, "lookback_short", 199)))
    breakout_window = max(1, int(getattr(cfg, "breakout_bars", 100)))
    zone_cmp_round = int(getattr(cfg, "zone_compare_round_decimals", -1))
    asof_lag = max(0, int(getattr(cfg, "sheet_active_zone_asof_lag_bars", 0)))
    age_adjust_cfg = max(0, int(getattr(cfg, "sheet_active_zone_asof_age_adjust_bars", 0)))
    use_sid = bool(getattr(cfg, "sheet_use_dg_slot_for_zone_identity", True))
    # Rounded OHLC for overlap when sheet compares on rounded prices (avoids per-call round on every bar).
    if zone_cmp_round >= 0:
        _low_f = np.asarray(low_arr, dtype=np.float64)
        _high_f = np.asarray(high_arr, dtype=np.float64)
        low_rnd = np.round(_low_f, zone_cmp_round)
        high_rnd = np.round(_high_f, zone_cmp_round)
    else:
        low_rnd = None
        high_rnd = None
    zctx_cache: dict[int, tuple[bool, float, float, int, float]] = {}

    def _zone_ctx_at(j: int) -> tuple[bool, float, float, int, float]:
        if j < 0:
            return (False, float("nan"), float("nan"), -1, float("nan"))
        hit = zctx_cache.get(j)
        if hit is not None:
            return hit
        if use_sheet_zone_ctx and de_ctx is not None and df_ctx is not None and dg_ctx is not None and j < len(de_ctx):
            src = j
            zl_j = float(de_ctx[src]) if np.isfinite(de_ctx[src]) else float("nan")
            zu_j = float(df_ctx[src]) if np.isfinite(df_ctx[src]) else float("nan")
            dg_j = int(dg_ctx[src]) if np.isfinite(dg_ctx[src]) else -1
            sid_j = (
                float(ds_ctx[src])
                if (ds_ctx is not None and src < len(ds_ctx) and np.isfinite(ds_ctx[src]))
                else float("nan")
            )
            ok = np.isfinite(zl_j) and np.isfinite(zu_j) and zl_j > 0 and zu_j > 0 and dg_j >= 0
            if ok and asof_lag > 0:
                if (j - dg_j) + age_adjust_cfg < asof_lag:
                    ok = False
            out = (bool(ok), zl_j, zu_j, dg_j, sid_j)
        else:
            ok_fb = pd.notna(zone_low_fb) and pd.notna(zone_upper_fb) and zone_low_fb > 0 and zone_upper_fb > 0
            out = (bool(ok_fb), float(zone_low_fb), float(zone_upper_fb), int(maturity_bar_fb), float("nan"))
        zctx_cache[j] = out
        return out

    def _overlap_at(j: int, zl_v: float, zu_v: float) -> bool:
        if zone_cmp_round >= 0:
            lo_j = float(low_rnd[j])  # type: ignore[index]
            hi_j = float(high_rnd[j])  # type: ignore[index]
            zl_j = round(float(zl_v), zone_cmp_round)
            zu_j = round(float(zu_v), zone_cmp_round)
        else:
            lo_j = float(low_arr[j])
            hi_j = float(high_arr[j])
            zl_j = float(zl_v)
            zu_j = float(zu_v)
        return bool((lo_j <= zu_j) and (hi_j >= zl_j))

    def _same_zone_ctx(
        a: tuple[bool, float, float, int, float], b: tuple[bool, float, float, int, float]
    ) -> bool:
        if (not a[0]) or (not b[0]):
            return False
        sid_a = a[4]
        sid_b = b[4]
        if use_sid and np.isfinite(sid_a) and np.isfinite(sid_b):
            return int(sid_a) == int(sid_b)
        if zone_cmp_round >= 0:
            return (
                round(float(a[1]), zone_cmp_round) == round(float(b[1]), zone_cmp_round)
                and round(float(a[2]), zone_cmp_round) == round(float(b[2]), zone_cmp_round)
            )
        return abs(float(a[1]) - float(b[1])) <= 1e-12 and abs(float(a[2]) - float(b[2])) <= 1e-12

    def _ak_at(j: int) -> bool:
        if not st_on or j < 1:
            return False
        ok, zl_j, zu_j, dg_j, _ = _zone_ctx_at(j)
        if (not ok) or j <= dg_j:
            return False
        ov = _overlap_at(j, zl_j, zu_j)
        return bool(ov and (close_arr[j - 1] > zu_j))

    def _resistance_test_at(j: int) -> bool:
        if not st_on or j < 1:
            return False
        ok, zl_j, zu_j, dg_j, _ = _zone_ctx_at(j)
        if (not ok) or j <= dg_j:
            return False
        ov = _overlap_at(j, zl_j, zu_j)
        return bool(ov and (close_arr[j - 1] < zl_j))

    def _aq_at(j: int) -> bool:
        if not st_on or j < 0:
            return False
        ok_j, zl_j, zu_j, _dg_j, _sid_j = _zone_ctx_at(j)
        if not ok_j:
            return False
        start_ev = max(0, j - aq_window + 1)
        am_cnt = 0
        an_cnt = 0
        ref = (ok_j, zl_j, zu_j, _dg_j, _sid_j)
        for k in range(start_ev, j + 1):
            ctx_k = _zone_ctx_at(k)
            if not _same_zone_ctx(ctx_k, ref):
                continue
            if k < 1:
                continue
            ok_k, zl_k, zu_k, dg_k, _ = ctx_k
            if (not ok_k) or k <= dg_k:
                continue
            ov = _overlap_at(k, zl_k, zu_k)
            if ov and (close_arr[k - 1] > zu_k):
                am_cnt += 1
            if ov and (close_arr[k - 1] < zl_k):
                an_cnt += 1
        am = am_cnt >= 2
        an = an_cnt > 0
        start_br = max(0, j - breakout_window + 1)
        ap_flag = bool(np.max(close_arr[start_br : j + 1]) > zu_j)
        return bool(am or (an and ap_flag))

    return _zone_ctx_at, _overlap_at, _same_zone_ctx, _ak_at, _resistance_test_at, _aq_at


def _bands_overlap(zl_a: float, zu_a: float, zl_b: float, zu_b: float) -> bool:
    return not (zu_a < zl_b or zl_a > zu_b)


# Resistance episode counting (prior to maturity): penetration by high, close below zone to finish,
# chop inside band = one episode, clear move-away threshold below zl.
_RESIST_PENETRATION_FRAC = 0.10
_RESIST_CLEAR_BELOW_FRAC = 0.005  # close must be at least this fraction of band width below zl


def _count_rejection_episodes_prior(
    close_arr: np.ndarray,
    low_arr: np.ndarray,
    high_arr: np.ndarray,
    zl_e: float,
    zu_e: float,
    maturity_bar: int,
    zone_cmp_round: int,
) -> int:
    """
    Count completed **resistance episodes** on bars prior to ``maturity_bar`` (indices ``1 .. maturity_bar-1``).

    Episode **start** (from below): prior close is below the zone lower, this bar's **high** lies in
    ``[zl, zu]``, and the high reaches at least ``zl + 10%`` of the band width (capped at ``zu``).

    **Chop** while ``in_episode``: multiple closes inside ``[zl, zu]`` (or shallow dips above ``zl`` that
    are not clearly below the band) still belong to the **same** episode.

    Episode **ends with one count** when a close is clearly below the zone: ``close <= zl - k`` where
    ``k = max(1e-12*zl, _RESIST_CLEAR_BELOW_FRAC * (zu-zl))`` (not merely hovering on ``zl``).

    Episode **aborts without a count** if price **accepts above** the zone (``close > zu``) before a
    rejection — treated as breakout, not a failed resistance touch.
    """
    if maturity_bar < 2 or not (np.isfinite(zl_e) and np.isfinite(zu_e) and zl_e > 0 and zu_e > zl_e):
        return 0
    rd = int(zone_cmp_round)
    if rd >= 0:
        zle = round(float(zl_e), rd)
        zue = round(float(zu_e), rd)
    else:
        zle, zue = float(zl_e), float(zu_e)
    w = zue - zle
    if w <= 0:
        return 0
    pen_hi = min(zle + _RESIST_PENETRATION_FRAC * w, zue)
    reject_cl = zle - max(1e-12 * abs(zle), _RESIST_CLEAR_BELOW_FRAC * w)

    def _ohlc(j: int) -> tuple[float, float, float, float]:
        if rd >= 0:
            return (
                round(float(close_arr[j - 1]), rd),
                round(float(high_arr[j]), rd),
                round(float(low_arr[j]), rd),
                round(float(close_arr[j]), rd),
            )
        return (
            float(close_arr[j - 1]),
            float(high_arr[j]),
            float(low_arr[j]),
            float(close_arr[j]),
        )

    cnt = 0
    in_ep = False
    for j in range(1, int(maturity_bar)):
        prev_cl, hi, _lo, cl = _ohlc(j)
        if not in_ep:
            # Start only from below: prior session closed under the band; high probes in-band with depth.
            if prev_cl < zle and pen_hi <= hi <= zue:
                if cl <= reject_cl:
                    cnt += 1
                    in_ep = False
                else:
                    in_ep = True
            continue
        # In episode: chop inside/hover until clear rejection or acceptance above zone.
        if cl > zue:
            in_ep = False
            continue
        if cl <= reject_cl:
            cnt += 1
            in_ep = False
            continue
        # Still inside / hovering / partial dip above reject line — same interaction.
    return cnt


def _count_overlapping_mature_zones(
    zl_full: np.ndarray,
    zh_full: np.ndarray,
    matured: np.ndarray,
    zl_e: float,
    zu_e: float,
    maturity_bar: int,
    zone_cmp_round: int,
) -> int:
    """Count matured zone rows j <= maturity_bar whose [BH,BI] overlaps entry band, excluding the identical band."""
    if not (np.isfinite(zl_e) and np.isfinite(zu_e) and zl_e > 0 and zu_e > zl_e):
        return 0
    n = int(len(zl_full))
    mb = min(int(maturity_bar), n - 1)
    if mb < 0:
        return 0
    rd = int(zone_cmp_round)
    if rd >= 0:
        zle, zue = round(float(zl_e), rd), round(float(zu_e), rd)
    else:
        zle, zue = float(zl_e), float(zu_e)
    cnt = 0
    for j in range(0, mb + 1):
        if j >= len(matured) or not bool(matured[j]):
            continue
        zla = float(zl_full[j])
        zua = float(zh_full[j])
        if not (np.isfinite(zla) and np.isfinite(zua) and zla > 0 and zua > zla):
            continue
        if rd >= 0:
            zla, zua = round(zla, rd), round(zua, rd)
        if abs(zla - zle) < 1e-12 and abs(zua - zue) < 1e-12:
            continue
        if _bands_overlap(zle, zue, zla, zua):
            cnt += 1
    return cnt


def _lookup_breakout_bar_for_zone(
    br_rows: list[dict],
    zl_e: float,
    zu_e: float,
    maturity_bar: int,
    zone_cmp_round: int,
) -> Optional[int]:
    """Latest breakout_bar on or before maturity_bar whose zone band matches entry (rounded bounds when rd>=0)."""
    if not (np.isfinite(zl_e) and np.isfinite(zu_e) and zl_e > 0 and zu_e > zl_e):
        return None
    rd = int(zone_cmp_round)
    if rd >= 0:
        t_lo, t_hi = round(float(zl_e), rd), round(float(zu_e), rd)
    else:
        t_lo, t_hi = float(zl_e), float(zu_e)
    best: Optional[int] = None
    for r in br_rows:
        try:
            zl = float(r.get("zone_lower", float("nan")))
            zu = float(r.get("zone_upper", float("nan")))
        except (TypeError, ValueError):
            continue
        if not (np.isfinite(zl) and np.isfinite(zu) and zu > zl):
            continue
        if rd >= 0:
            zl, zu = round(zl, rd), round(zu, rd)
        if zl != t_lo or zu != t_hi:
            continue
        try:
            bb = int(r.get("breakout_bar", -1))
        except (TypeError, ValueError):
            continue
        if bb < 0 or bb > int(maturity_bar):
            continue
        best = bb
    return best


def _pending_zone_band_zl_zh(
    p: dict[str, Any],
    maturity_bar: int,
    band_pct_at: Callable[[int, float], float],
) -> tuple[float, float]:
    """Resolve entry zone lower/upper from a touch or retest pending row (same as post-gate entry band)."""
    zc = p.get("zone_center")
    try:
        zl = float(p.get("zone_low", float("nan")))
    except (TypeError, ValueError):
        zl = float("nan")
    if not np.isfinite(zl) and pd.notna(zc):
        zl = float(zc) * (1 - band_pct_at(int(maturity_bar), float(zc)))
    zh_raw = p.get("zone_high")
    try:
        zh = float(zh_raw) if zh_raw is not None and str(zh_raw).strip() != "" else float("nan")
    except (TypeError, ValueError):
        zh = float("nan")
    if not np.isfinite(zh) and pd.notna(zc):
        zh = float(zc) * (1 + band_pct_at(int(maturity_bar), float(zc)))
    return zl, zh


def _find_last_matured_identical_band_bar(
    zl_full: np.ndarray,
    zh_full: np.ndarray,
    matured: np.ndarray,
    zl_e: float,
    zu_e: float,
    hi_bar: int,
    zone_cmp_round: int,
) -> Optional[int]:
    """Latest bar index <= hi_bar where matured_now and sheet zone band equals (zl_e, zu_e).

    Used so MATURITY_DATE reflects the zone's matured row (BH/BI-style band), not the retest signal bar.
    """
    if not (np.isfinite(zl_e) and np.isfinite(zu_e) and zl_e > 0 and zu_e > zl_e):
        return None
    n = int(len(zl_full))
    mb = min(int(hi_bar), n - 1)
    if mb < 0:
        return None
    rd = int(zone_cmp_round)
    if rd >= 0:
        t_lo, t_hi = round(float(zl_e), rd), round(float(zu_e), rd)
    else:
        t_lo, t_hi = float(zl_e), float(zu_e)
    best: Optional[int] = None
    for j in range(0, mb + 1):
        if j >= len(matured) or not bool(matured[j]):
            continue
        zla = float(zl_full[j])
        zua = float(zh_full[j])
        if not (np.isfinite(zla) and np.isfinite(zua) and zla > 0 and zua > zla):
            continue
        if rd >= 0:
            zla, zua = round(zla, rd), round(zua, rd)
        if abs(zla - t_lo) < 1e-12 and abs(zua - t_hi) < 1e-12:
            best = j
    return best


def _rel_vol_at_bar(volume_arr: np.ndarray, bar: int) -> Optional[float]:
    """volume[bar] / mean(volume[bar-9:bar]) when valid (same window style as rel_vol_on_trigger)."""
    if volume_arr is None or bar < 0 or bar >= len(volume_arr):
        return None
    v = float(volume_arr[bar])
    if v != v:
        return None
    start_10 = max(0, bar - 9)
    sl = volume_arr[start_10 : bar + 1]
    if sl.size == 0:
        return None
    avg_tr = float(np.nanmean(sl))
    if not avg_tr or avg_tr <= 0:
        return None
    return float(v) / avg_tr


_SheetLadderGateFns = tuple[
    Callable[[int], tuple[bool, float, float, int, float]],
    Callable[[int, float, float], bool],
    Callable[[tuple[bool, float, float, int, float], tuple[bool, float, float, int, float]], bool],
    Callable[[int], bool],
    Callable[[int], bool],
    Callable[[int], bool],
]

def _precompute_mat_bh_bi_stream(
    zl_full_arr: np.ndarray,
    zh_full_arr: np.ndarray,
    lag: int,
    n: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Sheet BH/BI: INDEX(AG/AH, ROW()-lag) → zone lower/upper from bar (i - lag)."""
    mat_bh = np.full(n, np.nan, dtype=np.float64)
    mat_bi = np.full(n, np.nan, dtype=np.float64)
    lag = max(0, int(lag))
    for i in range(n):
        j = i - lag
        if j >= 0:
            mat_bh[i] = float(zl_full_arr[j])
            mat_bi[i] = float(zh_full_arr[j])
    return mat_bh, mat_bi


def _precompute_di_all_zones_breakout(
    breakout_px: np.ndarray,
    mat_bh: np.ndarray,
    mat_bi: np.ndarray,
    n: int,
    max_hist: int,
    compare_round_decimals: int = -1,
    direction: str = "long",
    *,
    zone_sheet_lag_bars: int = 0,
    zone_role_mode: str = "dynamic",
    zone_role_override: str = "",
    zone_origin_at_bar: Optional[np.ndarray] = None,
    yh_zone_events: Optional[list[dict]] = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Sheet **BM** / **DI** (all zones): among historical matured bounds rows j < i, require
    for long: prior_px < BI[j] and current_px >= BI[j]
    for short: prior_px > BH[j] and current_px <= BH[j]
    on adjacent bars of ``breakout_px``.
    Use **Close** (default) for sheet parity; **High** was an earlier intraday-based approximation.
    Take the **maximum qualifying BI** among zones activated **before** the breakout bar
    (same-day activation crosses alone do not register). Short: maximum qualifying BH.

    When ``compare_round_decimals >= 0`` (same as ``zone_compare_round_decimals``), prior/current
    breakout prices and each historical ``BI[j]`` are rounded before the strict inequalities. That
    matches spreadsheet display precision and avoids spurious extra DI rows when the close dips
    a fraction of a cent below ``BI`` (e.g. NFLX 2020-01-16 vs 33.864).

    Zone role policy (``zone_role_mode=by_origin``): each candidate column j is kept only if the
    zone's pivot origin (PH→resistance / PL→support, optionally overridden) matches ``direction``.
    Column j references BH/BI at row j, sourced from pivot bar ``j - zone_sheet_lag_bars``.
    """
    di_ok = np.zeros(n, dtype=np.bool_)
    sel_j = np.full(n, -1, dtype=np.int32)
    sel_yh_ev = np.full(n, -1, dtype=np.int32)
    mh = max(0, int(max_hist))
    px_64 = np.asarray(breakout_px, dtype=np.float64)
    _dir = _normalize_entry_type(direction)
    cross_arr = np.asarray(mat_bi if _dir == "long" else mat_bh, dtype=np.float64)
    finite_cross = np.isfinite(cross_arr)
    _rd = int(compare_round_decimals)
    _zrm = _normalize_zone_role_mode(zone_role_mode)
    _zov = _normalize_zone_role_override(zone_role_override)
    _lag_z = max(0, int(zone_sheet_lag_bars))
    _orig = np.asarray(zone_origin_at_bar, dtype=np.int8).reshape(-1) if zone_origin_at_bar is not None else None
    _use_role = (
        _zrm == "by_origin"
        and _orig is not None
        and _orig.size >= n
    )

    # Per-bar scan: long uses sheet pick (before-day activations, then max BI); short max BH.
    for i in range(1, n):
        hp = float(px_64[i - 1])
        hc = float(px_64[i])
        if not (np.isfinite(hp) and np.isfinite(hc)):
            continue
        if _rd >= 0:
            hp = round(hp, _rd)
            hc = round(hc, _rd)
        j0 = max(0, i - mh) if mh > 0 else 0
        best_cross = np.inf if _dir == "long" else -np.inf
        best_j = -1
        best_yh_ev = -1

        seg = cross_arr[j0:i]
        if _dir == "long":
            long_quals: list[tuple[float, float, int, int, int]] = []
            if seg.size > 0:
                fin_seg = finite_cross[j0:i]
                if _rd >= 0:
                    seg_cmp = np.round(seg, _rd)
                    mask = fin_seg & (seg_cmp > hp) & (seg_cmp <= hc)
                else:
                    mask = fin_seg & (seg > hp) & (seg <= hc)
                if _use_role:
                    role_ok = np.zeros(seg.shape[0], dtype=bool)
                    for kk in range(seg.shape[0]):
                        col_bar = j0 + kk
                        oc = _zone_origin_code_for_sheet_column(_orig, col_bar, _lag_z)
                        er = _effective_zone_role(oc, _zov)
                        role_ok[kk] = _zone_role_allows_entry(_zrm, er, _dir)
                    mask = mask & role_ok
                for kk in range(seg.shape[0]):
                    if not mask[kk]:
                        continue
                    col_bar = j0 + kk
                    zu = float(mat_bi[col_bar])
                    zl = float(mat_bh[col_bar])
                    long_quals.append((zl, zu, col_bar, col_bar, -1))
            if yh_zone_events:
                for ev_i, ev in enumerate(yh_zone_events):
                    ab = int(ev.get("activation_bar", -1))
                    if ab < 0 or ab > i:
                        continue
                    if mh > 0 and ab < j0:
                        continue
                    zu = float(ev.get("zone_upper", np.nan))
                    zl = float(ev.get("zone_lower", np.nan))
                    if not (np.isfinite(zu) and np.isfinite(zl)):
                        continue
                    zu_cmp = round(zu, _rd) if _rd >= 0 else zu
                    if not (zu_cmp > hp and zu_cmp <= hc):
                        continue
                    if _use_role:
                        ev_origin = int(ev.get("origin", 3))
                        er = _effective_zone_role(ev_origin, _zov)
                        if not _zone_role_allows_entry(_zrm, er, _dir):
                            continue
                    long_quals.append((zl, zu, ab, ab, ev_i))
            pick_pool = [(zl, zu, ab) for zl, zu, ab, _, _ in long_quals]
            picked = _sheet_pick_di_breakout_zone_long(pick_pool, i)
            if picked is not None:
                _zl_p, zu_p, ab_p = picked
                for zl, zu, ab, j_col, ev_i in long_quals:
                    if int(ab) == int(ab_p) and abs(float(zu) - float(zu_p)) < 1e-9:
                        best_cross = float(zu_p)
                        best_j = int(j_col)
                        best_yh_ev = int(ev_i)
                        break
        elif seg.size > 0:
            fin_seg = finite_cross[j0:i]
            if _rd >= 0:
                seg_cmp = np.round(seg, _rd)
                mask = fin_seg & (seg_cmp < hp) & (seg_cmp >= hc)
            else:
                seg_cmp = seg
                mask = fin_seg & (seg_cmp < hp) & (seg_cmp >= hc)
            if _use_role:
                role_ok = np.zeros(seg.shape[0], dtype=bool)
                for kk in range(seg.shape[0]):
                    col_bar = j0 + kk
                    oc = _zone_origin_code_for_sheet_column(_orig, col_bar, _lag_z)
                    er = _effective_zone_role(oc, _zov)
                    role_ok[kk] = _zone_role_allows_entry(_zrm, er, _dir)
                mask = mask & role_ok
            if np.any(mask):
                vals = np.where(mask, seg, -np.inf)
                rel = int(np.argmax(vals))
                if np.isfinite(vals[rel]):
                    best_cross = float(vals[rel])
                    best_j = j0 + rel

        if yh_zone_events and _dir != "long":
            for ev_i, ev in enumerate(yh_zone_events):
                ab = int(ev.get("activation_bar", -1))
                if ab < 0 or ab >= i:
                    continue
                if mh > 0 and ab < j0:
                    continue
                zl = float(ev.get("zone_lower", np.nan))
                if not np.isfinite(zl):
                    continue
                zl_cmp = round(zl, _rd) if _rd >= 0 else zl
                if not (zl_cmp < hp and zl_cmp >= hc):
                    continue
                if _use_role:
                    ev_origin = int(ev.get("origin", 3))
                    er = _effective_zone_role(ev_origin, _zov)
                    if not _zone_role_allows_entry(_zrm, er, _dir):
                        continue
                if zl > best_cross:
                    best_cross = zl
                    best_j = ab
                    best_yh_ev = ev_i

        if best_j >= 0 and np.isfinite(best_cross):
            di_ok[i] = True
            sel_j[i] = best_j
            sel_yh_ev[i] = best_yh_ev
    return di_ok, sel_j, sel_yh_ev


def _precompute_dw_dates_from_di_breakouts(
    low_arr: np.ndarray,
    high_arr: np.ndarray,
    mat_bh: np.ndarray,
    mat_bi: np.ndarray,
    di_ok: np.ndarray,
    selected_j: np.ndarray,
    index_iso: list[str],
    n: int,
    retest_first_bar_delta: int = 3,
    round_decimals: int = -1,
) -> Set[str]:
    """
    Minimal **DW** simulation: after a DI breakout at bar b on zone row j*, first bar r whose range
    overlaps [BH[j*], BI[j*]] **and** r >= b + retest_first_bar_delta records a retest date (column DW).

    ``retest_first_bar_delta`` matches the sheet **Scan Start Row** offset from **Main Row** (same
    config as ``sheet_breakout_scan_start_row_delta``): Excel row (b + first_row + delta) is the
    first bar eligible for a retest, so bar index r must satisfy r >= b + delta (delta defaults to 2).
    """
    dates_in_dw: Set[str] = set()
    pending: list[tuple[int, int]] = []
    low_64 = np.asarray(low_arr, dtype=np.float64)
    high_64 = np.asarray(high_arr, dtype=np.float64)
    _delta = int(retest_first_bar_delta)
    if _delta < 1:
        _delta = 1
    _rd = int(round_decimals)
    for i in range(1, n):
        new_pending: list[tuple[int, int]] = []
        for b, j_star in pending:
            if i <= b:
                new_pending.append((b, j_star))
            continue
            if i < b + _delta:
                new_pending.append((b, j_star))
            continue
            zl = float(mat_bh[j_star])
            zu = float(mat_bi[j_star])
            if not (np.isfinite(zl) and np.isfinite(zu)):
                new_pending.append((b, j_star))
            continue
            lo = float(low_64[i])
            hi = float(high_64[i])
            if _rd >= 0:
                zl = round(zl, _rd)
                zu = round(zu, _rd)
                lo = round(lo, _rd)
                hi = round(hi, _rd)
            if (lo <= zu) and (hi >= zl):
                if i < len(index_iso):
                    dates_in_dw.add(index_iso[i])
            else:
                new_pending.append((b, j_star))
        pending = new_pending
        sj = int(selected_j[i])
        if bool(di_ok[i]) and sj >= 0:
            if (not bool(di_ok[i - 1])) or int(selected_j[i - 1]) != sj:
                pending.append((i, sj))
    return dates_in_dw


def _iso_yyyymmdd_to_mdy(iso: str) -> str:
    """Format YYYYMMDD sheet index string as M/D/YYYY for CSV (no zero-pad on month/day)."""
    if len(iso) >= 8 and iso[:8].isdigit():
        y, m, d = int(iso[:4]), int(iso[4:6]), int(iso[6:8])
        return f"{m}/{d}/{y}"
    return iso


def _brt_idx_for_isoyyyymmdd(iso: str, index_iso: list[str]) -> int:
    """Bar index for a YYYYMMDD index string, or -1 if missing."""
    if not iso or len(iso) < 8 or not iso[:8].isdigit():
        return -1
    try:
        return index_iso.index(iso)
    except ValueError:
        return -1


def _brt_next_trading_isoyyyymmdd(retest_iso: str, index_iso: list[str]) -> str:
    """Next calendar row in ``index_iso`` after ``retest_iso`` (trading-day series)."""
    bi = _brt_idx_for_isoyyyymmdd(retest_iso, index_iso)
    if bi < 0 or bi + 1 >= len(index_iso):
        return ""
    return index_iso[bi + 1]


def _brt_expand_dw_dates_for_by_gate(
    dates: Set[str], index_iso: list[str], include_next_trading_after_retest: bool
) -> Set[str]:
    """
    BY / DW COUNTIF-style eval date set: each retest YYYYMMDD plus, when enabled, the **next**
    trading session after that retest (so a bullish eval bar the day after retest matches the same
    BY column as checking the prior bar against raw retest dates).
    """
    out: Set[str] = set(dates)
    if not include_next_trading_after_retest:
        return out
    for iso in list(dates):
        if not iso:
            continue
        nx = _brt_next_trading_isoyyyymmdd(iso, index_iso)
        if nx:
            out.add(nx)
    return out


def _enrich_brt_rows_for_engine_csv(
    rows: list[dict], cfg: Any, index_iso: list[str], *, by_superset: bool
) -> list[dict]:
    """
    Shallow-copy rows with CSV columns that match gates (BY superset) and which DI row is kept when
    ``retest_multi_zone_pick`` is lowest/highest (synthetic pending uses that subset only).
    """
    pick = str(getattr(cfg, "retest_multi_zone_pick", "all") or "all").strip().lower()
    by_iso: dict[str, list[int]] = {}
    for idx, r in enumerate(rows):
        riso = str(r.get("retest_iso") or "").strip()
        if riso:
            by_iso.setdefault(riso, []).append(idx)
    pending_yes: set[int] = set()
    for _riso, idxs in by_iso.items():
        if len(idxs) <= 1 or pick not in ("lowest", "highest"):
            pending_yes.update(idxs)
            continue
        grp = [rows[i] for i in idxs]
        kept = _filter_retest_rows_for_zone_pick(grp, pick)
        k_ids = {id(k) for k in kept}
        for i in idxs:
            if id(rows[i]) in k_ids:
                pending_yes.add(i)
    out: list[dict] = []
    for idx, r in enumerate(rows):
        e = dict(r)
        riso = str(r.get("retest_iso") or "").strip()
        if by_superset and riso:
            nx = _brt_next_trading_isoyyyymmdd(riso, index_iso)
            e["by_gate_also_matches_eval_on_mdy"] = _iso_yyyymmdd_to_mdy(nx) if nx else ""
        else:
            e["by_gate_also_matches_eval_on_mdy"] = ""
        if not riso:
            e["engine_pending_row"] = ""
        elif idx in pending_yes:
            e["engine_pending_row"] = "Yes"
        else:
            e["engine_pending_row"] = "No"
        out.append(e)
    return out


def _filter_retest_rows_for_zone_pick(rt_rows: list[dict], pick: str) -> list[dict]:
    """If ``pick`` is lowest/highest, keep a single retest row by zone band price; else return ``rt_rows`` unchanged."""
    p = (pick or "all").strip().lower()
    if p not in ("lowest", "highest") or len(rt_rows) <= 1:
        return rt_rows

    def _zl(r: dict) -> float:
        return float(r.get("zone_lower", float("nan")))

    def _zu(r: dict) -> float:
        return float(r.get("zone_upper", float("nan")))

    valids = [r for r in rt_rows if np.isfinite(_zl(r)) and np.isfinite(_zu(r))]
    if not valids:
        return rt_rows
    if p == "lowest":
        return [min(valids, key=_zl)]
    return [max(valids, key=_zu)]


def _sheet_pick_di_breakout_zone_long(
    quals: list[tuple[float, float, int]],
    breakout_bar: int,
) -> Optional[tuple[float, float, int]]:
    """
    Sheet **BC** zone choice on a long breakout bar:

    Among zones whose upper was crossed (prior close < BB, current close >= BB) from
    matured rows before the breakout bar, pick **minimum BB** (lowest crossed band).
    Matches ``MIN(FILTER(zU, p<zU, c>=zU))`` over BA/BB history rows 2..ROW()-1.
    """
    if not quals or breakout_bar < 0:
        return None
    before = [(zl, zu, ab) for zl, zu, ab in quals if int(ab) < int(breakout_bar)]
    if not before:
        return None
    return min(before, key=lambda t: (float(t[1]), int(t[2])))


def _sheet_breakout_zone_bounds_long(
    i: int,
    prev_px: float,
    cur_px: float,
    open_px: float,
    mat_bh: np.ndarray,
    mat_bi: np.ndarray,
    yh_ev: list[dict],
    rd: int,
    *,
    gap_max_pick_pct: float = 0.08,
) -> tuple[float, float]:
    """
    Zone lower/upper for sheet **BM/DI** breakout detail: crossed zones collected from
    matured BH/BI rows and YH activations, then ``_sheet_pick_di_breakout_zone_long``.
    ``gap_max_pick_pct`` is ignored (legacy); kept for call-site compatibility.
    """
    hp = float(prev_px)
    hc = float(cur_px)
    if not (np.isfinite(hp) and np.isfinite(hc)):
        return float("nan"), float("nan")
    if rd >= 0:
        hp = round(hp, rd)
        hc = round(hc, rd)
    quals: list[tuple[float, float, int]] = []
    for j in range(0, i):
        zu = float(mat_bi[j])
        zl = float(mat_bh[j])
        if not (np.isfinite(zu) and np.isfinite(zl)):
            continue
        zu_c = round(zu, rd) if rd >= 0 else zu
        if zu_c > hp and zu_c <= hc:
            quals.append((zl, zu, int(j)))
    for ev in yh_ev:
        ab = int(ev.get("activation_bar", -1))
        if ab < 0 or ab > i:
            continue
        zu = float(ev.get("zone_upper", np.nan))
        zl = float(ev.get("zone_lower", np.nan))
        if not (np.isfinite(zu) and np.isfinite(zl)):
            continue
        zu_c = round(zu, rd) if rd >= 0 else zu
        if zu_c > hp and zu_c <= hc:
            quals.append((zl, zu, ab))
    picked = _sheet_pick_di_breakout_zone_long(quals, i)
    if picked is None:
        return float("nan"), float("nan")
    return float(picked[0]), float(picked[1])


def _compute_breakout_retest_rows(
    sym: str,
    mat_bh: np.ndarray,
    mat_bi: np.ndarray,
    low_arr: np.ndarray,
    high_arr: np.ndarray,
    close_arr: np.ndarray,
    open_arr: np.ndarray,
    di_ok: np.ndarray,
    selected_j: np.ndarray,
    index_iso: list[str],
    n: int,
    cfg: Any,
    *,
    zone_sheet_lag_bars: int = 0,
    selected_yh_ev: Optional[np.ndarray] = None,
    yh_zone_events: Optional[list[dict]] = None,
) -> list[dict]:
    """
    Replay the same pending/overlap logic as ``_precompute_dw_dates_from_di_breakouts`` and emit one row
    per new DI breakout with zone bounds (BH/BI at j*) and optional first retest bar (BY-style).

    Retest overlap uses the same high/low vs [zl, zu] rule as DW, only on bars
    ``i >= breakout_bar + sheet_breakout_scan_start_row_delta`` (Scan Start Row in Excel).
    """
    lag_b = max(0, int(zone_sheet_lag_bars))
    first_row = max(1, int(getattr(cfg, "sheet_excel_first_data_row", 2) or 2))
    scan_delta = max(0, int(getattr(cfg, "sheet_breakout_scan_start_row_delta", 2)))
    # First bar index eligible for retest overlap (same as DW): breakout bar b plus row delta Main→Scan.
    retest_min_delta = scan_delta if scan_delta > 0 else 1
    records: list[dict] = []
    pending: list[tuple[int, int, int, int]] = []
    low_64 = np.asarray(low_arr, dtype=np.float64)
    high_64 = np.asarray(high_arr, dtype=np.float64)
    _rd = int(getattr(cfg, "zone_compare_round_decimals", -1))
    _yh_ev = yh_zone_events or []
    close_64 = np.asarray(close_arr, dtype=np.float64)
    open_64 = np.asarray(open_arr, dtype=np.float64)
    for i in range(1, n):
        new_pending: list[tuple[int, int, int, int]] = []
        for b, j_star, yh_idx, ridx in pending:
            if i <= b:
                new_pending.append((b, j_star, yh_idx, ridx))
                continue
            if i < b + retest_min_delta:
                new_pending.append((b, j_star, yh_idx, ridx))
                continue
            zl = float(records[ridx].get("zone_lower", np.nan))
            zu = float(records[ridx].get("zone_upper", np.nan))
            if not (np.isfinite(zl) and np.isfinite(zu)):
                new_pending.append((b, j_star, yh_idx, ridx))
                continue
            lo = float(low_64[i])
            hi = float(high_64[i])
            if _rd >= 0:
                zl = round(zl, _rd)
                zu = round(zu, _rd)
                lo = round(lo, _rd)
                hi = round(hi, _rd)
            if (lo <= zu) and (hi >= zl):
                if i < len(index_iso):
                    records[ridx]["retest_bar"] = i
                    records[ridx]["retest_iso"] = index_iso[i]
            else:
                new_pending.append((b, j_star, yh_idx, ridx))
        pending = new_pending
        sj = int(selected_j[i])
        syh = int(selected_yh_ev[i]) if selected_yh_ev is not None else -1
        if bool(di_ok[i]) and sj >= 0:
            prev_syh = int(selected_yh_ev[i - 1]) if selected_yh_ev is not None else -1
            if (not bool(di_ok[i - 1])) or int(selected_j[i - 1]) != sj or prev_syh != syh:
                hp = float(close_64[i - 1]) if i >= 1 else float("nan")
                hc = float(close_64[i])
                ho = float(open_64[i]) if i < len(open_64) else float("nan")
                zl_b, zu_b = _sheet_breakout_zone_bounds_long(
                    i, hp, hc, ho, mat_bh, mat_bi, _yh_ev, _rd
                )
                if np.isfinite(zl_b) and np.isfinite(zu_b) and zl_b > 0 and zu_b > zl_b:
                    zone_band = i
                    m_src = max(0, i - lag_b)
                elif syh >= 0 and syh < len(_yh_ev):
                    ev = _yh_ev[syh]
                    zl_b = float(ev.get("zone_lower", np.nan))
                    zu_b = float(ev.get("zone_upper", np.nan))
                    zone_band = int(ev.get("activation_bar", sj))
                    m_src = int(ev.get("yh_bar", max(0, sj - lag_b)))
                else:
                    zl_b = float(mat_bh[sj])
                    zu_b = float(mat_bi[sj])
                    zone_band = sj
                    m_src = max(0, sj - lag_b)
                main_row = i + first_row
                rec: dict[str, Any] = {
                    "SYMBOL": sym,
                    "breakout_bar": i,
                    "breakout_iso": index_iso[i] if i < len(index_iso) else "",
                    "zone_lower": zl_b,
                    "zone_upper": zu_b,
                    "zone_band_bar": zone_band,
                    "zone_lag_source_bar": m_src,
                    "zone_asof_iso": index_iso[zone_band] if 0 <= zone_band < len(index_iso) else "",
                    "maturity_source_iso": index_iso[m_src] if 0 <= m_src < len(index_iso) else "",
                    "main_row": main_row,
                    "scan_start_row": main_row + scan_delta,
                    "retest_bar": None,
                    "retest_iso": "",
                    "excel_first_row": first_row,
                    "yh_event_index": syh,
                }
                ridx = len(records)
                records.append(rec)
                pending.append((i, zone_band, syh, ridx))
    return records


def write_brt_breakout_and_retest(rows: list[dict], path: str) -> None:
    """Write BRT_breakout_and_retest_<ts>.csv (breakout + first retest per program logic)."""
    headers = [
        "SYMBOL",
        "SIDE",
        "Breakout Date",
        "Maturity Date",
        "Zone Band Date",
        "Zone Lower",
        "Zone Upper",
        "Main Row",
        "Scan Start Row",
        "retest Row",
        "Retest Date",
        "BY Gate Also Matches Eval On",
        "Engine Pending Row",
    ]
    out_rows: list[list[str]] = []
    for r in rows:
        zl = float(r["zone_lower"])
        zu = float(r["zone_upper"])
        zone_lo = f"${zl:.2f}"
        zone_hi = f"{zu:.4f}"
        rb = r.get("retest_bar")
        fr = int(r.get("excel_first_row", 2))
        retest_row_str = "" if rb is None else str(int(rb) + fr)
        riso = str(r.get("retest_iso") or "")
        retest_date_str = _iso_yyyymmdd_to_mdy(riso) if riso else ""
        mat_iso = str(r.get("maturity_source_iso") or "")
        maturity_str = _iso_yyyymmdd_to_mdy(mat_iso) if mat_iso else ""
        zband_iso = str(r.get("zone_asof_iso") or "")
        zone_band_str = _iso_yyyymmdd_to_mdy(zband_iso) if zband_iso else ""
        by_next = str(r.get("by_gate_also_matches_eval_on_mdy") or "")
        pend = str(r.get("engine_pending_row") or "")
        out_rows.append(
            [
                str(r["SYMBOL"]),
                str(r.get("SIDE", "") or ""),
                _iso_yyyymmdd_to_mdy(str(r.get("breakout_iso") or "")),
                maturity_str,
                zone_band_str,
                zone_lo,
                zone_hi,
                str(int(r["main_row"])),
                str(int(r["scan_start_row"])),
                retest_row_str,
                retest_date_str,
                by_next,
                pend,
            ]
        )
    outp = Path(path)
    outp.parent.mkdir(parents=True, exist_ok=True)
    with open(outp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(out_rows)


def _atr_schedule_exit_now(
    cfg: Any,
    open_trade: "BRTTrade",
    bar_index: int,
    high_arr: np.ndarray,
    open_arr: np.ndarray,
    index_iso: list[str],
) -> tuple[bool, float, str]:
    """
    ATR schedule exit using calendar-day deadline:
    first trading bar open after (entry_date + atr_days calendar days).

    - atr_days<=0: disabled.
    - atr_progress<=0: timed exit (``ATR_timed``) — always exit at first open strictly after the
      calendar deadline.
    - atr_progress>0: inaction exit (``ATR_inaction``) — same open unless max High from entry bar
      through the prior bar reached entry*(1+atr_progress*atr_pct_at_entry/100).
    """
    ad = int(getattr(cfg, "atr_days", 0) or 0)
    if ad <= 0:
        return (False, float("nan"), "")
    eb = int(getattr(open_trade, "entry_bar_index", -1) or -1)
    if eb < 0:
        return (False, float("nan"), "")
    if bar_index < 0 or bar_index >= len(index_iso):
        return (False, float("nan"), "")
    if eb >= len(index_iso):
        return (False, float("nan"), "")
    d_open = str(getattr(open_trade, "date_opened", "") or "")
    if len(d_open) >= 8 and d_open[:8].isdigit():
        d_open_fmt = f"{d_open[:4]}-{d_open[4:6]}-{d_open[6:8]}"
    else:
        d_open_fmt = d_open
    try:
        entry_ts = pd.Timestamp(d_open_fmt)
    except Exception:
        return (False, float("nan"), "")
    cur_iso = index_iso[bar_index]
    cur_fmt = f"{cur_iso[:4]}-{cur_iso[4:6]}-{cur_iso[6:8]}" if len(cur_iso) >= 8 else cur_iso
    try:
        cur_ts = pd.Timestamp(cur_fmt)
    except Exception:
        return (False, float("nan"), "")
    due_ts = entry_ts + pd.Timedelta(days=ad)
    # Exit at next session open after the deadline date.
    if not (cur_ts > due_ts):
        return (False, float("nan"), "")
    if bar_index >= len(open_arr):
        return (False, float("nan"), "")

    ap = float(getattr(cfg, "atr_progress", 0.0) or 0.0)
    opx = float(open_arr[bar_index])

    if ap <= 0:
        return (True, opx, "ATR_timed")

    atr_pct = getattr(open_trade, "atr_pct_at_entry", None)
    if atr_pct is None or not np.isfinite(float(atr_pct)) or float(atr_pct) <= 0:
        return (False, float("nan"), "")
    entry = float(open_trade.entry_price)
    if entry <= 0:
        return (False, float("nan"), "")
    req = entry * (1.0 + (ap * float(atr_pct)) / 100.0)
    end_excl = bar_index
    if eb >= len(high_arr) or end_excl > len(high_arr) or end_excl <= eb:
        return (False, float("nan"), "")
    peak = float(np.max(high_arr[eb:end_excl]))
    if peak >= req:
        return (False, float("nan"), "")
    return (True, opx, "ATR_inaction")


def _atr_incremental_stop_floor(
    cfg: Any,
    open_trade: "BRTTrade",
    bar_index: int,
    index_iso: list[str],
) -> Optional[float]:
    """
    Optional ATR incremental stop:
    after the atr_days calendar deadline, raise stop floor to
    entry*(1 + atr_progress*ATR_PCT_AT_ENTRY/100) when enabled.
    """
    if not bool(getattr(cfg, "atr_progress_incremental_stop", False)):
        return None
    ad = int(getattr(cfg, "atr_days", 0) or 0)
    ap = float(getattr(cfg, "atr_progress", 0.0) or 0.0)
    if ad <= 0 or ap <= 0:
        return None
    if bar_index < 0 or bar_index >= len(index_iso):
        return None
    d_open = str(getattr(open_trade, "date_opened", "") or "")
    if len(d_open) >= 8 and d_open[:8].isdigit():
        d_open_fmt = f"{d_open[:4]}-{d_open[4:6]}-{d_open[6:8]}"
    else:
        d_open_fmt = d_open
    try:
        entry_ts = pd.Timestamp(d_open_fmt)
    except Exception:
        return None
    cur_iso = index_iso[bar_index]
    cur_fmt = f"{cur_iso[:4]}-{cur_iso[4:6]}-{cur_iso[6:8]}" if len(cur_iso) >= 8 else cur_iso
    try:
        cur_ts = pd.Timestamp(cur_fmt)
    except Exception:
        return None
    due_ts = entry_ts + pd.Timedelta(days=ad)
    # Activate at first session strictly after deadline (same cadence as ATR schedule exit).
    if not (cur_ts > due_ts):
        return None
    atr_pct = getattr(open_trade, "atr_pct_at_entry", None)
    if atr_pct is None or not np.isfinite(float(atr_pct)) or float(atr_pct) <= 0:
        return None
    entry = float(getattr(open_trade, "entry_price", 0.0) or 0.0)
    if entry <= 0:
        return None
    floor = entry * (1.0 + (ap * float(atr_pct)) / 100.0)
    return float(floor) if np.isfinite(float(floor)) else None


def sma_trailing_stop_floor(
    sma_stop_days: int,
    close_arr: np.ndarray,
    sma_arr: Optional[np.ndarray],
    bar_i: int,
    is_long: bool,
) -> Optional[float]:
    """
    When enabled, return SMA(N) as a candidate stop floor if price is on the favorable side:
    long: Close > SMA; short: Close < SMA. Caller merges with max(long) / min(short).
    """
    if int(sma_stop_days or 0) <= 0 or sma_arr is None:
        return None
    if bar_i < 0 or bar_i >= len(sma_arr) or bar_i >= len(close_arr):
        return None
    sma = float(sma_arr[bar_i])
    if not np.isfinite(sma) or sma <= 0:
        return None
    cl = float(close_arr[bar_i])
    if not np.isfinite(cl):
        return None
    if is_long:
        if cl > sma:
            return sma
    elif cl < sma:
        return sma
    return None


def merge_sma_stop_into_working(
    sp: float,
    sma_floor: Optional[float],
    is_long: bool,
) -> tuple[float, bool]:
    """Ratchet working stop with SMA floor (long: raise only; short: tighten only)."""
    if sma_floor is None or not np.isfinite(float(sma_floor)):
        return sp, False
    sf = float(sma_floor)
    if is_long:
        if sf > float(sp):
            return sf, True
    elif sf < float(sp):
        return sf, True
    return sp, False


def _resolve_working_stop(
    open_trade: "BRTTrade",
    bar_i: int,
    cfg: Any,
    index_iso: list[str],
    close_arr: np.ndarray,
    sma_stop_arr: Optional[np.ndarray],
    max_high_since_entry: float,
    trail_inc: float,
    sma_stop_days: int,
    is_long: bool,
) -> tuple[float, bool, bool, bool, Optional[float]]:
    """
    Combine gain-based trailing, ATR progress floor, and SMA(N) floor into one working stop.
    Returns (sp, inc_active, sma_active, hit_trailing_gain, inc_floor).
    """
    sp = float(open_trade.stop_price)
    hit_trailing_gain = False
    if trail_inc > 0 and float(open_trade.entry_price) > 0:
        gain_pct = (max_high_since_entry - float(open_trade.entry_price)) / float(open_trade.entry_price) * 100.0
        step_ratio = max(0.0, float(gain_pct)) / float(trail_inc)
        stop_raise = step_ratio * 0.01 * float(open_trade.entry_price)
        sp = float(open_trade.stop_price) + stop_raise
        hit_trailing_gain = sp > float(open_trade.stop_price)
    inc_floor = _atr_incremental_stop_floor(cfg, open_trade, bar_i, index_iso)
    prev_cl = float(close_arr[bar_i - 1]) if bar_i > 0 else float(close_arr[bar_i])
    inc_active = (
        inc_floor is not None
        and np.isfinite(float(inc_floor))
        and float(inc_floor) > float(sp)
        and prev_cl > float(inc_floor)
    )
    if inc_active:
        sp = float(inc_floor)
    sma_floor = sma_trailing_stop_floor(sma_stop_days, close_arr, sma_stop_arr, bar_i, is_long)
    sp, sma_active = merge_sma_stop_into_working(sp, sma_floor, is_long)
    return sp, inc_active, sma_active, hit_trailing_gain, inc_floor


def _brt_closed_from_open(
    open_trade: "BRTTrade",
    *,
    sym: str,
    cfg: Any,
    df: pd.DataFrame,
    iso: str,
    exit_price: float,
    exit_type: str,
) -> "BRTTrade":
    """Build a closed BRTTrade from an open position."""
    _trade_is_long = str(getattr(open_trade, "side", "LONG") or "LONG").upper() != "SHORT"
    pnl_move = (exit_price - open_trade.entry_price) if _trade_is_long else (open_trade.entry_price - exit_price)
    pnl_pct = (pnl_move / open_trade.entry_price) * 100
    pnl_dollars = (cfg.brt_cash / open_trade.entry_price) * pnl_move
    days_held = (pd.Timestamp(iso) - pd.Timestamp(open_trade.date_opened)).days if len(iso) == 8 else 0
    d_open = open_trade.date_opened
    if len(d_open) == 8 and len(iso) == 8:
        start_dt = pd.Timestamp(d_open[:4] + "-" + d_open[4:6] + "-" + d_open[6:8])
        end_dt = pd.Timestamp(iso[:4] + "-" + iso[4:6] + "-" + iso[6:8])
        mask = (df.index >= start_dt) & (df.index <= end_dt)
        max_price = float(df.loc[mask, "High"].max()) if mask.any() else open_trade.entry_price
    else:
        max_price = open_trade.entry_price
    return BRTTrade(
        symbol=sym,
        side=getattr(open_trade, "side", "LONG"),
        date_opened=open_trade.date_opened,
        entry_price=open_trade.entry_price,
        stop_price=open_trade.stop_price,
        target_price=open_trade.target_price,
        date_closed=iso,
        exit_price=exit_price,
        exit_type=exit_type,
        days_held=days_held,
        pnl_pct=pnl_pct,
        pnl_dollars=pnl_dollars,
        zone_center=open_trade.zone_center,
        zone_low=getattr(open_trade, "zone_low", 0.0),
        zone_high=getattr(open_trade, "zone_high", 0.0),
        pbr_zone_id=str(getattr(open_trade, "pbr_zone_id", "") or ""),
        touch_count=open_trade.touch_count,
        touch_count_short=open_trade.touch_count_short,
        touch_count_major=open_trade.touch_count_major,
        touch_count_minor=open_trade.touch_count_minor,
        zone_rolling_touches=int(getattr(open_trade, "zone_rolling_touches", 0) or 0),
        support_test_count=int(getattr(open_trade, "support_test_count", 0) or 0),
        support_test_at_signal=int(getattr(open_trade, "support_test_at_signal", 0) or 0),
        touch_count_at_maturity=int(getattr(open_trade, "touch_count_at_maturity", 0) or 0),
        touch_count_short_at_maturity=int(getattr(open_trade, "touch_count_short_at_maturity", 0) or 0),
        zone_episode_dn=int(getattr(open_trade, "zone_episode_dn", 0) or 0),
        days_since_maturity=int(getattr(open_trade, "days_since_maturity", 0) or 0),
        is_tradeable_key_level=open_trade.is_tradeable_key_level,
        struct_high=open_trade.struct_high,
        struct_low=open_trade.struct_low,
        entry_pivot_type=open_trade.entry_pivot_type,
        entry_struct_regime=open_trade.entry_struct_regime,
        entry_major_pivot=open_trade.entry_major_pivot,
        entry_pivot_was_strong=getattr(open_trade, "entry_pivot_was_strong", 0),
        entry_zone_was_strong_pivot=getattr(open_trade, "entry_zone_was_strong_pivot", 0),
        nearby_zones_above=open_trade.nearby_zones_above,
        nearby_zones_below=open_trade.nearby_zones_below,
        zone_cluster_density=open_trade.zone_cluster_density,
        maturity_date=open_trade.maturity_date,
        close_above_date=open_trade.close_above_date,
        breakout_date=getattr(open_trade, "breakout_date", "") or "",
        days_since_breakout=getattr(open_trade, "days_since_breakout", None),
        max_price=max_price,
        growth_pct_over_period=getattr(open_trade, "growth_pct_over_period", None),
        displacement_pct_at_entry=getattr(open_trade, "displacement_pct_at_entry", None),
        pivot_run_high=getattr(open_trade, "pivot_run_high", 0),
        pivot_run_low=getattr(open_trade, "pivot_run_low", 0),
        pivot_switch_h_to_l=getattr(open_trade, "pivot_switch_h_to_l", False),
        zone_above_center=getattr(open_trade, "zone_above_center", 0.0),
        zone_below_center=getattr(open_trade, "zone_below_center", 0.0),
        pct_entry_to_bottom_zone_above=getattr(open_trade, "pct_entry_to_bottom_zone_above", 0.0),
        pct_drop_to_top_zone_below=getattr(open_trade, "pct_drop_to_top_zone_below", 0.0),
        volume_at_entry=getattr(open_trade, "volume_at_entry", None),
        avg_volume_10d_at_entry=getattr(open_trade, "avg_volume_10d_at_entry", None),
        rel_vol_at_entry=getattr(open_trade, "rel_vol_at_entry", None),
        rel_vol_on_trigger=getattr(open_trade, "rel_vol_on_trigger", None),
        rejection_count_prior=int(
            getattr(open_trade, "rejection_count_prior", None)
            or getattr(open_trade, "resistance_touch_count_prior", 0)
            or 0
        ),
        overlapping_mature_zones_count=int(getattr(open_trade, "overlapping_mature_zones_count", 0) or 0),
        rel_vol_at_breakout=getattr(open_trade, "rel_vol_at_breakout", None),
        atr_14_at_entry=getattr(open_trade, "atr_14_at_entry", None),
        entry_bar_index=int(getattr(open_trade, "entry_bar_index", -1) or -1),
        atr_pct_at_entry=getattr(open_trade, "atr_pct_at_entry", None),
        market_cap=getattr(open_trade, "market_cap", None),
        market_cap_current=getattr(open_trade, "market_cap_current", None),
        sector=getattr(open_trade, "sector", None),
        industry=getattr(open_trade, "industry", None),
        beta=getattr(open_trade, "beta", None),
        beta_at_entry=getattr(open_trade, "beta_at_entry", None),
        z_score_at_trigger=getattr(open_trade, "z_score_at_trigger", 0.0),
        upper_wick_atr_at_trigger=getattr(open_trade, "upper_wick_atr_at_trigger", 0.0),
        lower_wick_atr_at_trigger=getattr(open_trade, "lower_wick_atr_at_trigger", 0.0),
        is_20bar_high_at_trigger=getattr(open_trade, "is_20bar_high_at_trigger", 0),
        is_20bar_low_at_trigger=getattr(open_trade, "is_20bar_low_at_trigger", 0),
        move_body_atr_at_trigger=getattr(open_trade, "move_body_atr_at_trigger", 0.0),
        atr_14_at_trigger=getattr(open_trade, "atr_14_at_trigger", None),
        atr_pct_at_trigger=getattr(open_trade, "atr_pct_at_trigger", None),
        sheet_ladder_rung_at_signal=getattr(open_trade, "sheet_ladder_rung_at_signal", 0),
        last_ath_date_at_entry=getattr(open_trade, "last_ath_date_at_entry", ""),
        trading_days_since_last_ath_at_entry=int(
            getattr(open_trade, "trading_days_since_last_ath_at_entry", 0) or 0
        ),
        high_52w_at_entry=getattr(open_trade, "high_52w_at_entry", None),
        dist_to_52w_high_pct=getattr(open_trade, "dist_to_52w_high_pct", None),
        high_52w_at_trigger=getattr(open_trade, "high_52w_at_trigger", None),
        dist_to_52w_high_pct_at_trigger=getattr(open_trade, "dist_to_52w_high_pct_at_trigger", None),
        had_meteoric_rise_before_entry=int(getattr(open_trade, "had_meteoric_rise_before_entry", 0) or 0),
        had_meteoric_fall_before_entry=int(getattr(open_trade, "had_meteoric_fall_before_entry", 0) or 0),
        spy_compare_1y=getattr(open_trade, "spy_compare_1y", None),
        spy_compare_2y=getattr(open_trade, "spy_compare_2y", None),
        spy_compare_3y=getattr(open_trade, "spy_compare_3y", None),
        spy_ind_diff_at_entry=getattr(open_trade, "spy_ind_diff_at_entry", None),
        entry_indicators=dict(getattr(open_trade, "entry_indicators", None) or {}),
        **_pbr_strength_kwargs_from_trade(open_trade),
    )


def _brt_attempt_exit_at_bar(
    open_trade: "BRTTrade",
    max_high_since_entry: float,
    pending_ind_diff_exit: bool,
    *,
    sym: str,
    i: int,
    iso: str,
    op: float,
    hi: float,
    lo: float,
    cl: float,
    cfg: Any,
    df: pd.DataFrame,
    index_iso: list[str],
    open_arr: np.ndarray,
    high_arr: np.ndarray,
    close_arr: np.ndarray,
    sma_stop_arr: Optional[np.ndarray],
    cfg_sell_ind_diff_below: Optional[float],
    cfg_exit_ind_diff_only: bool,
    cfg_sell_on_low_vol: bool,
    cfg_trailing_stop_inc: float,
    cfg_sma_stop_days: int,
    cfg_stop_cmp_rd: int,
    use_atr_exits_loop: bool,
    sym_indicator_pre: Any,
    aligned_bull_bear_diff_fn: Any,
) -> tuple[Optional["BRTTrade"], float, bool, bool]:
    """
    Try to exit ``open_trade`` on bar ``i``.
    Returns (closed_trade_or_none, updated_max_high, updated_pending_ind, early_continue_bar).
    """
    _trade_is_long = str(getattr(open_trade, "side", "LONG") or "LONG").upper() != "SHORT"
    _trade_side = str(getattr(open_trade, "side", "LONG") or "LONG")
    max_high_since_entry = max(max_high_since_entry, hi)
    _ind_diff_exit_now = False
    if (
        cfg_sell_ind_diff_below is not None
        and pending_ind_diff_exit
        and sym_indicator_pre is not None
        and aligned_bull_bear_diff_fn is not None
    ):
        _ind_diff_exit_now = True
        pending_ind_diff_exit = False
    tp = open_trade.target_price
    trail_inc = cfg_trailing_stop_inc
    sp, inc_active, sma_active, hit_trailing_gain, inc_floor = _resolve_working_stop(
        open_trade,
        i,
        cfg,
        index_iso,
        close_arr,
        sma_stop_arr,
        max_high_since_entry,
        trail_inc,
        cfg_sma_stop_days,
        _trade_is_long,
    )
    stop_round_decimals = cfg_stop_cmp_rd
    if stop_round_decimals >= 0:
        op_cmp = round(float(op), stop_round_decimals)
        lo_cmp = round(float(lo), stop_round_decimals)
        sp_cmp = round(float(sp), stop_round_decimals)
        inc_cmp = round(float(inc_floor), stop_round_decimals) if inc_active else None
    else:
        op_cmp = float(op)
        lo_cmp = float(lo)
        sp_cmp = float(sp)
        inc_cmp = float(inc_floor) if inc_active else None
    if _trade_is_long:
        gap_down = op_cmp <= sp_cmp
        gap_up = op >= tp
        stop_hit = lo_cmp <= sp_cmp
        target_hit = hi >= tp
    else:
        gap_down = op <= tp
        gap_up = op_cmp >= sp_cmp
        stop_hit = hi >= sp
        target_hit = lo <= tp
    use_atr_exits = use_atr_exits_loop
    hit_trailing_stop = bool(hit_trailing_gain and not inc_active and not sma_active)
    hit_inc_stop_gap = bool(inc_active and inc_cmp is not None and op_cmp <= inc_cmp)
    hit_inc_stop_touch = bool(inc_active and inc_cmp is not None and lo_cmp <= inc_cmp)
    hit_sma_stop_gap = bool(sma_active and op_cmp <= sp_cmp)
    hit_sma_stop_touch = bool(sma_active and lo_cmp <= sp_cmp)

    exit_price: float
    exit_type: str
    if _ind_diff_exit_now:
        exit_price = op
        exit_type = "IND_DIFF_EXIT"
    elif _low_rel_vol_exit_at_open(open_trade, i, cfg_sell_on_low_vol):
        exit_price = op
        exit_type = "LOW_REL_VOL_EXIT"
    elif cfg_exit_ind_diff_only:
        if _arm_ind_diff_exit_if_signal(
            threshold=int(cfg_sell_ind_diff_below),
            sym_indicator_pre=sym_indicator_pre,
            aligned_fn=aligned_bull_bear_diff_fn,
            bar_i=i,
            side=_trade_side,
        ):
            pending_ind_diff_exit = True
        return None, max_high_since_entry, pending_ind_diff_exit, True
    elif _trade_is_long and gap_down:
        exit_price = op
        if hit_inc_stop_gap:
            exit_type = "atr_incremental_stop"
        elif hit_sma_stop_gap:
            exit_type = "SMA_STOP"
        elif hit_trailing_stop:
            exit_type = "TRAILING_STOP"
        elif use_atr_exits:
            exit_type = "ATR_STOP"
        else:
            exit_type = "GAP_DOWN"
    elif _trade_is_long and gap_up:
        exit_price = op
        exit_type = "ATR_TARGET" if use_atr_exits else "GAP_UP"
    elif (not _trade_is_long) and gap_up:
        exit_price = op
        if hit_inc_stop_gap:
            exit_type = "atr_incremental_stop"
        elif hit_sma_stop_gap:
            exit_type = "SMA_STOP"
        elif hit_trailing_stop:
            exit_type = "TRAILING_STOP"
        elif use_atr_exits:
            exit_type = "ATR_STOP"
        else:
            exit_type = "GAP_UP"
    elif (not _trade_is_long) and gap_down:
        exit_price = op
        exit_type = "ATR_TARGET" if use_atr_exits else "GAP_DOWN"
    elif stop_hit:
        exit_price = cl if cfg.exit_at_close_when_stopped else sp
        if hit_inc_stop_touch:
            exit_type = "atr_incremental_stop"
        elif hit_sma_stop_touch:
            exit_type = "SMA_STOP"
        elif hit_trailing_stop:
            exit_type = "TRAILING_STOP"
        elif use_atr_exits:
            exit_type = "ATR_STOP"
        else:
            exit_type = "STOP_LOSS"
    elif target_hit:
        exit_price = tp
        exit_type = "ATR_TARGET" if use_atr_exits else "TARGET"
    else:
        _ai_ok, _ai_px, _ai_typ = _atr_schedule_exit_now(cfg, open_trade, i, high_arr, open_arr, index_iso)
        if _ai_ok:
            exit_price = _ai_px
            exit_type = _ai_typ
        else:
            if cfg_sell_ind_diff_below is not None and _arm_ind_diff_exit_if_signal(
                threshold=int(cfg_sell_ind_diff_below),
                sym_indicator_pre=sym_indicator_pre,
                aligned_fn=aligned_bull_bear_diff_fn,
                bar_i=i,
                side=_trade_side,
            ):
                pending_ind_diff_exit = True
            return None, max_high_since_entry, pending_ind_diff_exit, False

    closed_t = _brt_closed_from_open(
        open_trade,
        sym=sym,
        cfg=cfg,
        df=df,
        iso=iso,
        exit_price=exit_price,
        exit_type=exit_type,
    )
    return closed_t, max_high_since_entry, pending_ind_diff_exit, False


def run_brt_backtest(
    sym: str,
    df: pd.DataFrame,
    cfg: BRTConfig,
    ph_price: pd.Series,
    pl_price: pd.Series,
    struct: dict,
    level3: dict,
    zone_entries_debug: Optional[list] = None,
    benchmark_df: Optional[pd.DataFrame] = None,
    profile_beta_times: Optional[list] = None,
    reference_stats: Optional[dict[str, tuple[float, float]]] = None,
    profile_block_reasons: Optional[dict[str, int]] = None,
    profile_backtest_sections: Optional[dict[str, float]] = None,
    cprofile_magic_touch: Optional[cProfile.Profile] = None,
    cprofile_pending_sheet_prep: Optional[cProfile.Profile] = None,
    breakout_retest_rows_out: Optional[list] = None,
    indicators_while_held_rows_out: Optional[list] = None,
) -> tuple[list[BRTTrade], Optional[BRTTrade], list[dict], list[dict], list[dict], list[dict], list[BRTTrade]]:
    """
    One trade at a time by default (set allow_secondary_entries=True for concurrent same-symbol positions).
    If benchmark_df is provided (e.g. SPY OHLC), computes beta_at_entry for each trade (rolling beta vs benchmark ending at entry date).
    If profile_backtest_sections is a dict, accumulates per-section seconds, including **pre-main-loop** buckets
    so ``t_backtest`` wall time is explainable: ``bt_init``, ``bt_beta_precompute``,
    ``bt_strong_pivot_cd_stream`` (DO + confirmed touch + CD lag),
    then bar loop keys (``bt_loop_cb``, ``bt_loop_sheet_magic_touch``, ``bt_pending_active_zone``,
    ``bt_loop_pending_sheet_prep``, ``bt_loop_pending_for`` (wall time for the whole
    ``for p in pending_maturities`` loop; overlaps gate/entry sub-buckets below),
    ``bt_pending_gates_early``, ``bt_pending_gates_sheet``, ``bt_pending_gates``, ``bt_loop_bar_total``,
    ``bt_pending_pivot_sequence`` (``_pivot_sequence_in_zone`` only),
    ``bt_pending_entry_build`` (enriched metrics + ``BRTTrade`` / scanner after pivot filters),
    ``bt_pending_entry``, ...). Note: block_reason ``close_le_open`` is a high-frequency cheap reject;
    heavy work is often ``bt_strong_pivot_cd_stream``, ``bt_loop_sheet_magic_touch``, or pending-loop gates.
    If ``cprofile_magic_touch`` is a ``cProfile.Profile``, it is enabled only while executing the
    per-bar sheet magic touch block (AR/AW + CD window). If ``cprofile_pending_sheet_prep`` is
    provided, it is enabled only around the (minimal) pending-sheet prep timing bucket for that bar.
    Returns (closed_trades, open_trade, scanner_candidates, would_have_entries, watchlist_rows, extra_open_trades).
    would_have_entries: when cfg.emit_would_have, list of dicts (SYMBOL, MATURITY_DATE, ZONE_CENTER, WOULD_ENTER_DATE, REJECT_REASON) for maturities blocked only by growth/tight_range/consolidation.
    watchlist_rows: list of dicts for BRT_Watchlist (scanner + pending-at-EOD hints).
    """
    closed: list[BRTTrade] = []
    open_trade: Optional[BRTTrade] = None
    extra_open_trades: list[BRTTrade] = []
    _secondary_max_high: list[float] = []
    _secondary_pending_ind: list[bool] = []
    _cfg_allow_secondary = bool(getattr(cfg, "allow_secondary_entries", False))
    last_exit_yyyymmdd: str = ""
    scanner: list[dict] = []
    short_candidates: list[dict] = []
    would_have: list[dict] = []
    pending_maturities: list[dict] = []
    _block_reasons: dict[str, int] = {}
    def _count_block(reason: str) -> None:
        _block_reasons[reason] = _block_reasons.get(reason, 0) + 1
    n = len(df)

    _pbt = profile_backtest_sections

    def _acc_bt(key: str, dt: float) -> None:
        if _pbt is not None:
            _pbt[key] = _pbt.get(key, 0.0) + dt

    _t_init = time.perf_counter()
    # Precompute numpy arrays to avoid repeated .iloc in hot loop
    open_arr = df["Open"].to_numpy(dtype=np.float64)
    high_arr = df["High"].to_numpy(dtype=np.float64)
    low_arr = df["Low"].to_numpy(dtype=np.float64)
    close_arr = df["Close"].to_numpy(dtype=np.float64)
    _hl_dec_bt = int(getattr(cfg, "zone_price_round_decimals", 2))
    if _hl_dec_bt >= 0:
        strong_hi_arr = np.round(high_arr, _hl_dec_bt)
        strong_lo_arr = np.round(low_arr, _hl_dec_bt)
        # Entry gates (Close>Open, close-in-range) use same rounding as sheet display / zone prices.
        open_ent_arr = np.round(open_arr, _hl_dec_bt)
        high_ent_arr = np.round(high_arr, _hl_dec_bt)
        low_ent_arr = np.round(low_arr, _hl_dec_bt)
        close_ent_arr = np.round(close_arr, _hl_dec_bt)
    else:
        strong_hi_arr = high_arr
        strong_lo_arr = low_arr
        open_ent_arr = open_arr
        high_ent_arr = high_arr
        low_ent_arr = low_arr
        close_ent_arr = close_arr
    try:
        idx_parsed = pd.to_datetime(df.index, errors="coerce")
        if pd.isna(idx_parsed).any():
            raise ValueError("index has unparseable dates")
        index_iso = pd.DatetimeIndex(idx_parsed).strftime("%Y%m%d").tolist()
        if len(index_iso) != n:
            raise ValueError("index_iso length mismatch")
    except Exception:
        index_iso = [
            (df.index[i].strftime("%Y%m%d") if hasattr(df.index[i], "strftime") else str(df.index[i])[:10].replace("-", ""))
            for i in range(n)
        ]
    short_candidate_arr = level3["short_candidate"].to_numpy()
    matured_now_arr = level3["matured_now"].to_numpy()
    zone_center_arr = level3["zone_center"].to_numpy()
    zl_full_arr = level3["zone_low"].to_numpy(dtype=np.float64)
    zh_full_arr = level3["zone_high"].to_numpy(dtype=np.float64)
    touch_count_long_arr = level3["touch_count_long"].to_numpy()
    tradeable_key_level_arr = (
        level3["tradeable_key_level"].to_numpy()
        if "tradeable_key_level" in level3
        else np.zeros(n, dtype=bool)
    )
    touch_count_short_arr = (
        level3["touch_count_short"].to_numpy()
        if "touch_count_short" in level3
        else np.zeros(n, dtype=np.float64)
    )
    # Touch price array for "touch event today or yesterday" check
    touch_price_arr = (
        level3["touch_price"].to_numpy()
        if "touch_price" in level3
        else np.full(n, np.nan, dtype=np.float64)
    )
    struct_high_arr = struct["structure_high"].values
    struct_low_arr = struct["structure_low"].values
    ph_arr = ph_price.to_numpy(dtype=np.float64)
    pl_arr = pl_price.to_numpy(dtype=np.float64)
    mp_h_arr = struct["major_pivot_high"].values if struct.get("major_pivot_high") is not None else None
    mp_l_arr = struct["major_pivot_low"].values if struct.get("major_pivot_low") is not None else None
    volume_arr = df["Volume"].to_numpy(dtype=np.float64) if "Volume" in df.columns else None
    # 14-day ATR (same rolling mean TR as compute_touch_stream / _compute_atr_14_arr).
    atr_14_arr = _compute_atr_14_arr(high_arr, low_arr, close_arr, 14)
    sma50_arr: Optional[np.ndarray] = (
        _compute_sma_arr(close_arr, 50) if bool(getattr(cfg, "use_sma50", False)) else None
    )
    _sma_stop_days_init = int(getattr(cfg, "sma_stop_days", 0) or 0)
    sma_stop_arr: Optional[np.ndarray] = (
        _compute_sma_arr(close_arr, _sma_stop_days_init) if _sma_stop_days_init > 0 else None
    )

    meteor_rise_ever_arr, meteor_fall_ever_arr = _precompute_meteoric_cumulative_flags(
        close_arr,
        low_arr,
        high_arr,
        float(getattr(cfg, "meteoric_rise_pct", 300.0) or 0.0),
        int(getattr(cfg, "meteoric_rise_lookback", 100) or 0),
        float(getattr(cfg, "meteoric_fall_pct", 50.0) or 0.0),
        int(getattr(cfg, "meteoric_fall_lookback", 100) or 0),
    )

    _rs_st: Optional[np.ndarray] = None
    _rs_sp: Optional[np.ndarray] = None
    if benchmark_df is not None:
        _al_rs = _align_stock_spy_close_for_rs(df, benchmark_df)
        if _al_rs is not None:
            _rs_st, _rs_sp = _al_rs

    _acc_bt("bt_init", time.perf_counter() - _t_init)

    lag_c14 = max(0, _effective_sheet_maturity_lag_bars(cfg))

    _zto_raw = level3.get("zone_touch_origin")
    if _zto_raw is None:
        _zone_origin_np_bt = np.zeros(n, dtype=np.int8)
    else:
        _zone_origin_np_bt = np.asarray(
            _zto_raw.to_numpy() if hasattr(_zto_raw, "to_numpy") else _zto_raw,
            dtype=np.int8,
        ).ravel()
        if _zone_origin_np_bt.size != n:
            _z_fix_o = np.zeros(n, dtype=np.int8)
            _lim_o = min(n, _zone_origin_np_bt.size)
            if _lim_o > 0:
                _z_fix_o[:_lim_o] = _zone_origin_np_bt[:_lim_o]
            _zone_origin_np_bt = _z_fix_o

    beta_by_bar_arr: Optional[np.ndarray] = None
    _need_beta = bool(
        benchmark_df is not None
        and (
            bool(getattr(cfg, "compute_beta", False))
            or abs(float(getattr(cfg, "weight_beta_at_entry", 0.0) or 0.0)) > 1e-12
            or float(getattr(cfg, "min_beta_at_trigger", 0.0) or 0.0) > 0.0
            or float(getattr(cfg, "max_beta_at_trigger", 0.0) or 0.0) > 0.0
        )
    )
    if _need_beta:
        _t_beta = time.perf_counter()
        beta_by_bar_arr = _precompute_beta_by_bar_index(df, benchmark_df, _BETA_ROLLING_WINDOW)
        _acc_bt("bt_beta_precompute", time.perf_counter() - _t_beta)

    # DO parity helper: pre-only strong pivot touch event on bar t (N/S with AD/AE-style pre check).
    do_touch_arr = np.zeros(n, dtype=bool)
    # AF/CD parity helper: confirmed strong touch price stream (pre AND post), then lagged by C14.
    confirmed_touch_arr = np.full(n, np.nan, dtype=np.float64)
    cd_touch_arr = np.full(n, np.nan, dtype=np.float64)
    pre_bars = int(getattr(cfg, "strong_pre_pivot_bars", 0))
    pre_pct = float(getattr(cfg, "strong_pre_pivot_pct", 0.0))
    post_bars = int(getattr(cfg, "strong_post_pivot_bars", 0))
    post_pct = float(getattr(cfg, "strong_post_pivot_pct", 0.0))
    pre_pct_atr_do = float(getattr(cfg, "strong_pre_pivot_pct_atr", 0.0) or 0.0)
    post_pct_atr_do = float(getattr(cfg, "strong_post_pivot_pct_atr", 0.0) or 0.0)
    _pre_active_do = pre_bars > 0 and (pre_pct > 0 or pre_pct_atr_do > 0)
    _post_active_do = post_bars > 0 and (post_pct > 0 or post_pct_atr_do > 0)
    _t_scd = time.perf_counter()
    if _pre_active_do:
        for t in range(n):
            if ph_arr[t] > 0.0:
                _pp = float(ph_arr[t])
                _pre_u = _effective_strong_pivot_pct(_pp, t, atr_14_arr, pre_pct, pre_pct_atr_do)
                do_touch_arr[t] = _strong_pivot_bar_ok(
                    t, "PH", strong_hi_arr, strong_lo_arr, n,
                    pre_bars=pre_bars,
                    pre_pct=_pre_u,
                    post_bars=0,
                    post_pct=0.0,
                    mode="pre",
                )
                # Confirmed touch (AF-style): require pre AND post.
                if _post_active_do:
                    _post_u = _effective_strong_pivot_pct(_pp, t, atr_14_arr, post_pct, post_pct_atr_do)
                    if _strong_pivot_bar_ok(
                        t, "PH", strong_hi_arr, strong_lo_arr, n,
                        pre_bars=pre_bars,
                        pre_pct=_pre_u,
                        post_bars=post_bars,
                        post_pct=_post_u,
                        mode="both",
                    ):
                        confirmed_touch_arr[t] = float(ph_arr[t])
            elif pl_arr[t] > 0.0:
                _pp = float(pl_arr[t])
                _pre_u = _effective_strong_pivot_pct(_pp, t, atr_14_arr, pre_pct, pre_pct_atr_do)
                do_touch_arr[t] = _strong_pivot_bar_ok(
                    t, "PL", strong_hi_arr, strong_lo_arr, n,
                    pre_bars=pre_bars,
                    pre_pct=_pre_u,
                    post_bars=0,
                    post_pct=0.0,
                    mode="pre",
                )
                if _post_active_do:
                    _post_u = _effective_strong_pivot_pct(_pp, t, atr_14_arr, post_pct, post_pct_atr_do)
                    if _strong_pivot_bar_ok(
                        t, "PL", strong_hi_arr, strong_lo_arr, n,
                        pre_bars=pre_bars,
                        pre_pct=_pre_u,
                        post_bars=post_bars,
                        post_pct=_post_u,
                        mode="both",
                    ):
                        confirmed_touch_arr[t] = float(pl_arr[t])
    if lag_c14 > 0:
        for i_cd in range(lag_c14, n):
            cd_touch_arr[i_cd] = confirmed_touch_arr[i_cd - lag_c14]
    else:
        cd_touch_arr[:] = confirmed_touch_arr
    _acc_bt("bt_strong_pivot_cd_stream", time.perf_counter() - _t_scd)

    # Matured BH/BI streams + ladder-free DI / simulated DW dates (sheet_column_reference).
    mat_bh_arr, mat_bi_arr = _precompute_mat_bh_bi_stream(zl_full_arr, zh_full_arr, lag_c14, n)
    di_max_hist = int(getattr(cfg, "sheet_di_max_history_bars", 0) or 0)
    _di_mode = str(getattr(cfg, "sheet_di_breakout_price", "close") or "close").strip().lower()
    _di_px = high_arr if _di_mode == "high" else close_arr
    _dw_round_dec = int(getattr(cfg, "zone_compare_round_decimals", -1))
    _entry_side = _normalize_entry_type(getattr(cfg, "entry_type", "long"))
    _yh_zone_events = level3.get("yh_zone_events") or []
    if not isinstance(_yh_zone_events, list):
        _yh_zone_events = []
    di_ok_arr, di_sel_j_arr, di_sel_yh_ev_arr = _precompute_di_all_zones_breakout(
        _di_px,
        mat_bh_arr,
        mat_bi_arr,
        n,
        max_hist=di_max_hist,
        compare_round_decimals=_dw_round_dec,
        direction=_entry_side,
        zone_sheet_lag_bars=lag_c14,
        zone_role_mode=str(getattr(cfg, "zone_role_mode", "dynamic")),
        zone_role_override=str(getattr(cfg, "zone_role_override", "")),
        zone_origin_at_bar=_zone_origin_np_bt,
        yh_zone_events=_yh_zone_events if _yh_zone_events else None,
    )
    _dw_scan_delta = int(getattr(cfg, "sheet_breakout_scan_start_row_delta", 2))
    _brt_br_rows = _compute_breakout_retest_rows(
        sym,
        mat_bh_arr,
        mat_bi_arr,
        low_arr,
        high_arr,
        close_arr,
        open_arr,
        di_ok_arr,
        di_sel_j_arr,
        index_iso,
        n,
        cfg,
        zone_sheet_lag_bars=lag_c14,
        selected_yh_ev=di_sel_yh_ev_arr,
        yh_zone_events=_yh_zone_events,
    )
    _cfg_dw_countif_prior = bool(getattr(cfg, "sheet_dw_countif_include_prior_bar_date", False))
    # Raw retest YYYYMMDD from BH/BI pipeline; BY gate may also treat the next session as a match.
    dw_dates_set_raw: Set[str] = {
        str(r.get("retest_iso") or "")
        for r in _brt_br_rows
        if str(r.get("retest_iso") or "")
    }
    dw_dates_set = _brt_expand_dw_dates_for_by_gate(dw_dates_set_raw, index_iso, _cfg_dw_countif_prior)
    # Retest-driven candidates keyed by eval-bar date. This allows buys to be evaluated directly
    # from the breakout/retest pipeline without requiring a prior pending maturity event.
    retest_rows_by_iso: dict[str, list[dict]] = {}
    for _r in _brt_br_rows:
        _riso = str(_r.get("retest_iso") or "")
        if not _riso:
            continue
        retest_rows_by_iso.setdefault(_riso, []).append(_r)
    if breakout_retest_rows_out is not None:
        breakout_retest_rows_out.extend(
            _enrich_brt_rows_for_engine_csv(_brt_br_rows, cfg, index_iso, by_superset=_cfg_dw_countif_prior)
        )

    # DP parity helper: current low inside any matured BH/BI band in [i-window .. i-lag].
    def _dp_inside_any_zone(i_bar: int) -> bool:
        if i_bar < 0:
            return False
        lag = max(0, _effective_sheet_maturity_lag_bars(cfg))
        c10 = int(getattr(cfg, "dp_window_bars", 0))
        if c10 <= 0:
            c10 = int(getattr(cfg, "lookback_long", 504))
        start = max(0, i_bar - c10)
        end = i_bar - lag
        if end < 0 or end < start:
            return False
        px = float(low_arr[i_bar])
        for k in range(start, end + 1):
            zl_k = float(mat_bh_arr[k]) if k < len(mat_bh_arr) and np.isfinite(mat_bh_arr[k]) else float("nan")
            zu_k = float(mat_bi_arr[k]) if k < len(mat_bi_arr) and np.isfinite(mat_bi_arr[k]) else float("nan")
            if np.isfinite(zl_k) and np.isfinite(zu_k) and zl_k <= px <= zu_k:
                return True
        return False

    # Consolidation Blocker (CB) state (per symbol)
    inside_required_high = 3
    inside_required_low = 3
    max_high_since_entry: float = 0.0  # peak High since entry; used for trailing_stop_increment
    box_ceiling: Optional[float] = None
    box_floor: Optional[float] = None
    inside_high_count = 0
    inside_low_count = 0
    cb_active = False
    last_pivot_high: Optional[float] = None
    last_pivot_low: Optional[float] = None

    # Sheet magic touch (AR/AW): hoist bounds helper + window once — was ~90% of bt_loop_bar_total (per-bar def + Python AR loops).
    # _smt_prev_bar carries f(i-1); each bar calls _smt_bounds_fn(i) at most once (magic block or finally on early continue).
    zone_cmp_round_bt = int(getattr(cfg, "zone_compare_round_decimals", -1))
    _smt_bounds_fn: Optional[Callable[[int], tuple[bool, float, float, int]]] = None
    _smt_win_magic = 0
    if bool(getattr(cfg, "sheet_magic_touch_enabled", False)):
        _smt_win_magic = int(getattr(cfg, "sheet_magic_touch_window_bars", 0))
        if _smt_win_magic <= 0:
            _smt_win_magic = int(getattr(cfg, "lookback_long", 504))

        def _smt_bounds_fn(idx: int) -> tuple[bool, float, float, int]:
            if idx < 0 or idx >= n:
                return (False, float("nan"), float("nan"), -1)
            zl_v = float(mat_bh_arr[idx])
            zh_v = float(mat_bi_arr[idx])
            ok_v = np.isfinite(zl_v) and np.isfinite(zh_v) and zl_v > 0.0 and zh_v > 0.0
            if not ok_v:
                return (False, float("nan"), float("nan"), -1)
            return (True, zl_v, zh_v, idx)

    # Carries _smt_bounds_fn(i-1) across bars for zone-change vs prior row (sheet AW).
    _smt_prev_bar: tuple[bool, float, float, int] = (False, float("nan"), float("nan"), -1)

    # MTS / sheet BI: full-history active zone (DE/DF/DG) + hoisted gate helpers.
    _use_sheet_ctx = bool(getattr(cfg, "use_sheet_active_zone_ctx", False))
    de_ctx_arr: Optional[np.ndarray] = None
    df_ctx_arr: Optional[np.ndarray] = None
    dg_ctx_arr: Optional[np.ndarray] = None
    ds_ctx_arr: Optional[np.ndarray] = None
    dp_first_touch_arr: Optional[np.ndarray] = None
    mts_aw_arr: Optional[np.ndarray] = None
    mts_ar_arr: Optional[np.ndarray] = None
    mts_ak_arr: Optional[np.ndarray] = None
    mts_am_cnt_arr: Optional[np.ndarray] = None
    growth_ok_arr: Optional[np.ndarray] = None
    _gate_fns_sheet_global: Optional[_SheetLadderGateFns] = None
    _sheet_start_bar = 0
    _cfg_rocket_buy = bool(getattr(cfg, "sheet_rocket_buy_mode", False))
    _cfg_mts_first_touch = bool(getattr(cfg, "mts_first_touch_entry", False))
    _cfg_pbr_zones = bool(getattr(cfg, "pbr_zones", False))
    _cfg_pbr_second_chance = bool(getattr(cfg, "pbr_second_chance_after_win", False))
    pbr_entries_by_bar: dict[int, list[dict]] = {}
    pbr_zone_meta: dict[str, dict] = {}
    # Per-zone lifecycle: purchases, retired, open, allow_second, resume_scan_bar
    pbr_zone_state: dict[str, dict[str, Any]] = {}
    _pbr_find_signal = None
    if _cfg_pbr_zones:
        try:
            from pbr_zones import find_pbr_retest_and_signal as _pbr_find_signal
        except ImportError:
            from stock_analysis.pbr_zones import find_pbr_retest_and_signal as _pbr_find_signal
        for _opp in level3.get("pbr_entry_opportunities") or []:
            try:
                _sb = int(_opp.get("entry_signal_bar", -1))
            except (TypeError, ValueError):
                continue
            if 0 <= _sb < n:
                pbr_entries_by_bar.setdefault(_sb, []).append(_opp)
        # Fallback if older level3 lacked opportunities
        if not pbr_entries_by_bar:
            for _bi in level3.get("pbr_entry_signal_bars") or level3.get("pbr_entry_bars") or []:
                try:
                    _sb = int(_bi)
                except (TypeError, ValueError):
                    continue
                if 0 <= _sb < n:
                    pbr_entries_by_bar.setdefault(_sb, []).append(
                        {
                            "pbr_zone_id": "",
                            "zone_lower": float(zl_full_arr[_sb]) if np.isfinite(zl_full_arr[_sb]) else 0.0,
                            "zone_upper": float(zh_full_arr[_sb]) if np.isfinite(zh_full_arr[_sb]) else 0.0,
                            "zone_center": float(zone_center_arr[_sb]) if np.isfinite(zone_center_arr[_sb]) else 0.0,
                            "entry_signal_bar": _sb,
                            "opportunity_index": 0,
                        }
                    )
        for _ev in level3.get("pbr_zone_events") or []:
            _zid = str(_ev.get("pbr_zone_id", "") or "")
            if _zid:
                pbr_zone_meta[_zid] = _ev

    def _pbr_allows_new_entry(zone_id: str) -> bool:
        if not zone_id:
            return True
        st = pbr_zone_state.get(zone_id)
        if st is None:
            return True
        if st.get("retired") or st.get("open"):
            return False
        purchases = int(st.get("purchases", 0) or 0)
        if purchases <= 0:
            return True
        if purchases == 1 and bool(st.get("allow_second")):
            return True
        return False

    def _pbr_pending_has_zone(zone_id: str) -> bool:
        if not zone_id:
            return False
        return any(str(p.get("pbr_zone_id", "") or "") == zone_id for p in pending_maturities)

    def _pbr_on_entry(zone_id: str) -> None:
        if not zone_id:
            return
        st = pbr_zone_state.setdefault(
            zone_id,
            {"purchases": 0, "retired": False, "open": False, "allow_second": False, "resume_scan_bar": -1},
        )
        st["purchases"] = int(st.get("purchases", 0) or 0) + 1
        st["open"] = True
        st["allow_second"] = False
        if int(st["purchases"]) >= 2:
            st["retired"] = True

    def _pbr_on_exit(trade: "BRTTrade", exit_bar_i: int) -> None:
        zone_id = str(getattr(trade, "pbr_zone_id", "") or "")
        if not zone_id:
            return
        st = pbr_zone_state.setdefault(
            zone_id,
            {"purchases": 0, "retired": False, "open": False, "allow_second": False, "resume_scan_bar": -1},
        )
        st["open"] = False
        purchases = int(st.get("purchases", 0) or 0)
        if purchases >= 2:
            st["retired"] = True
            st["allow_second"] = False
            return
        if purchases == 1:
            if _cfg_pbr_second_chance and float(getattr(trade, "pnl_pct", 0.0) or 0.0) > 0.0:
                st["allow_second"] = True
                st["retired"] = False
                st["resume_scan_bar"] = int(exit_bar_i) + 1
            else:
                st["retired"] = True
                st["allow_second"] = False
    if _use_sheet_ctx:
        _t_az = time.perf_counter()
        de_ctx_arr, df_ctx_arr, dg_ctx_arr, ds_ctx_arr = _precompute_sheet_active_zone_arrays(
            high_arr, low_arr, mat_bh_arr, mat_bi_arr, n, cfg
        )
        if bool(getattr(cfg, "debug_dump_active_zones", False)):
            global _LAST_ACTIVE_ZONE_ARRAYS
            _LAST_ACTIVE_ZONE_ARRAYS = (de_ctx_arr, df_ctx_arr, dg_ctx_arr, ds_ctx_arr)
        # DP: first touch after availability. DO[i] = active zone exists at bar i
        # (_precompute_sheet_active_zone_arrays only sets DE/DF/DG/DS when i > maturity_bar,
        # so finite DS already implies row>maturity row). DP fires on the first bar of each
        # active-zone episode or when the zone ID (DS) changes vs the prior bar.
        if _cfg_mts_first_touch and ds_ctx_arr is not None:
            # DO = active zone exists AND row > available (maturity) row (DK/DL/DM/DN are also
            # set on the maturity bar itself, where DO is FALSE).
            _do_arr = np.zeros(n, dtype=bool)
            for _bi in range(n):
                if np.isfinite(ds_ctx_arr[_bi]) and (
                    dg_ctx_arr is None or not np.isfinite(dg_ctx_arr[_bi]) or _bi > dg_ctx_arr[_bi]
                ):
                    _do_arr[_bi] = True
            dp_first_touch_arr = np.zeros(n, dtype=bool)
            for _bi in range(n):
                if not _do_arr[_bi]:
                    continue
                if _bi == 0 or not _do_arr[_bi - 1] or ds_ctx_arr[_bi] != ds_ctx_arr[_bi - 1]:
                    dp_first_touch_arr[_bi] = True
        _acc_bt("bt_active_zone_precompute", time.perf_counter() - _t_az)

    # Exact MTS BI buy-gate arrays (AK/AM/AQ/BG/BC/BW/BE -> BI). Authoritative for MTS.
    mts_bi_arr: Optional[np.ndarray] = None
    if (
        _cfg_mts_first_touch
        and de_ctx_arr is not None
        and df_ctx_arr is not None
        and dg_ctx_arr is not None
        and ds_ctx_arr is not None
    ):
        _t_bi = time.perf_counter()
        _mts_gates = _precompute_mts_bi_gates(
            open_arr, high_arr, low_arr, close_arr,
            de_ctx_arr, df_ctx_arr, dg_ctx_arr, ds_ctx_arr,
            mat_bh_arr, mat_bi_arr, n, cfg,
        )
        mts_bi_arr = _mts_gates["bi"]
        mts_aw_arr = _mts_gates["aw"]
        mts_ar_arr = _mts_gates["ar"]
        mts_ak_arr = _mts_gates["ak"]
        mts_am_cnt_arr = _mts_gates["am_cnt"]
        _acc_bt("bt_mts_bi_precompute", time.perf_counter() - _t_bi)
        st_on_sheet = bool(getattr(cfg, "support_test_enabled", True))
        _gate_fns_sheet_global = _brt_make_entry_gate_query_fns(
            use_sheet_zone_ctx=True,
            st_on=st_on_sheet,
            cfg=cfg,
            close_arr=close_arr,
            low_arr=low_arr,
            high_arr=high_arr,
            de_ctx=de_ctx_arr,
            df_ctx=df_ctx_arr,
            dg_ctx=dg_ctx_arr,
            ds_ctx=ds_ctx_arr,
            zone_low_fb=float("nan"),
            zone_upper_fb=float("nan"),
            maturity_bar_fb=-1,
        )
    if bool(getattr(cfg, "sheet_growth_ok_mode", False)):
        growth_ok_arr = _precompute_sheet_growth_ok(high_arr, close_arr, n, cfg)
    if _cfg_rocket_buy:
        _sheet_start_bar = _sheet_start_bar_index(
            index_iso, str(getattr(cfg, "sheet_start_date", "2019-01-01"))
        )

    # Profiling: avoid perf_counter() syscalls on every bar when section timings are disabled.
    _perf = _pbt is not None
    # Hoisted config reads for the per-bar / per-pending hot path (avoid repeated getattr).
    _cfg_trailing_stop_inc = float(getattr(cfg, "trailing_stop_increment", 0.0) or 0.0)
    _cfg_sell_on_low_vol = float(getattr(cfg, "sell_on_low_vol", 0.0) or 0.0)
    _cfg_sma_stop_days = int(getattr(cfg, "sma_stop_days", 0) or 0)
    _cfg_stop_cmp_rd = int(getattr(cfg, "stop_compare_round_decimals", 2))
    _cfg_stop_pct = float(getattr(cfg, "stop_pct", 0.0) or 0.0)
    _cfg_short_stop_pct = float(getattr(cfg, "short_stop_pct", _cfg_stop_pct) or 0.0)
    _cfg_short_target_pct = float(getattr(cfg, "short_target_pct", getattr(cfg, "target_pct", 0.0)) or 0.0)
    _cfg_entry_side = _normalize_entry_type(getattr(cfg, "entry_type", "long"))
    _is_long_side = _cfg_entry_side == "long"
    _cfg_atr_target = float(getattr(cfg, "atr_target", 0.0) or 0.0)
    _cfg_atr_stop = float(getattr(cfg, "atr_stop", 0.0) or 0.0)
    _use_atr_exits_loop = (_cfg_atr_target > 0.0) or (_cfg_atr_stop > 0.0)
    _cfg_cb_max_box = float(getattr(cfg, "cb_max_box_width_pct", 0.35))
    _cfg_entry_from_retest_only = bool(getattr(cfg, "entry_from_retest_only", True))
    _cfg_touch_threshold = int(getattr(cfg, "touch_threshold", 0))
    _cfg_zone_mm = str(getattr(cfg, "zone_maturity_model", "touch_count") or "touch_count").strip().lower()
    _cfg_thr_magic = 1 if _cfg_zone_mm == "sheet_lag" else _cfg_touch_threshold
    _cfg_retest_pick = str(getattr(cfg, "retest_multi_zone_pick", "all") or "all")
    _cfg_eval_mode = str(getattr(cfg, "entry_eval_mode", "pending") or "pending").strip().lower()
    _cfg_row_local_same_bar = bool(getattr(cfg, "row_local_eval_touch_same_bar", False))
    _cfg_row_local_ctx = bool(getattr(cfg, "row_local_require_active_context_match", False))
    _cfg_entry_close_min_rng = float(getattr(cfg, "entry_close_min_range_position", 0.0))
    _cfg_require_close_gt_open = bool(getattr(cfg, "require_close_gt_open", True))
    _cfg_sheet_red_to_green = bool(getattr(cfg, "sheet_red_to_green_entry_enabled", True))
    _cfg_no_entry_same_bar_exit = bool(getattr(cfg, "sheet_no_entry_same_bar_after_exit", True))
    _cfg_erg_only = bool(getattr(cfg, "entry_retest_bullish_growth_only", False))
    _cfg_consol_block = bool(getattr(cfg, "consolidation_blocker_enabled", False))
    _cfg_dw_countif = bool(getattr(cfg, "sheet_dw_countif_entry_enabled", True))
    _cfg_emit_would = bool(getattr(cfg, "emit_would_have", False))
    _cfg_do_gate = bool(getattr(cfg, "do_gate_enabled", False))
    _cfg_do_keep = max(1, int(getattr(cfg, "do_good_for_bars", 2)))
    _cfg_dp_gate = bool(getattr(cfg, "dp_gate_enabled", False))
    _cfg_dp_keep = max(1, int(getattr(cfg, "dp_good_for_bars", 2)))
    _cfg_min_atr_trig = _cfg_min_atr_pct_trigger(cfg)
    _cfg_max_atr_trig = _cfg_max_atr_pct_trigger(cfg)
    _cfg_st_on = bool(getattr(cfg, "support_test_enabled", True))
    _cfg_anchor_mode = str(getattr(cfg, "level_acceptance_anchor_mode", "strict") or "strict").strip().lower()
    _cfg_anchor_win = max(1, int(getattr(cfg, "level_acceptance_anchor_window", cfg.level_acceptance_window)))
    _cfg_stop_pct = float(getattr(cfg, "stop_pct", 0.0) or 0.0)
    _cfg_short_stop_pct = float(getattr(cfg, "short_stop_pct", _cfg_stop_pct) or 0.0)
    _cfg_stop_anchor = str(getattr(cfg, "stop_anchor", "entry") or "entry").strip().lower()
    _cfg_short_target_pct = float(getattr(cfg, "short_target_pct", getattr(cfg, "target_pct", 0.0)) or 0.0)
    _cfg_entry_side = _normalize_entry_type(getattr(cfg, "entry_type", "long"))
    _cfg_strong_on = bool(getattr(cfg, "strong_pivots_enabled", True))
    _cfg_rt_filter = bool(getattr(cfg, "realtime_filter_enabled", False))
    _cfg_sp_mode = str(getattr(cfg, "strong_pivot_mode", "pre"))
    _cfg_sp_pre_b = int(cfg.strong_pre_pivot_bars)
    _cfg_sp_pre_pct = float(cfg.strong_pre_pivot_pct)
    _cfg_sp_post_b = int(cfg.strong_post_pivot_bars)
    _cfg_sp_post_pct = float(cfg.strong_post_pivot_pct)
    _cfg_band_pct_atr = float(getattr(cfg, "band_pct_atr", 0.0) or 0.0)
    _cfg_pre_pct_atr = float(getattr(cfg, "strong_pre_pivot_pct_atr", 0.0) or 0.0)
    _cfg_post_pct_atr = float(getattr(cfg, "strong_post_pivot_pct_atr", 0.0) or 0.0)
    _cfg_indicator_buy = _normalize_indicator_buy(getattr(cfg, "indicator_buy", "off"))
    _cfg_indicator_diff = int(getattr(cfg, "indicator_diff", 10) or 10)
    _use_avg_ind = bool(getattr(cfg, "use_average_ind", False))
    _avg_ind_combine = bool(getattr(cfg, "average_ind_combine", False))
    _avg_ind_map = getattr(cfg, "avg_ind_diff_by_date", None) or {}
    _cfg_use_indicators = bool(getattr(cfg, "use_indicators", False))
    _cfg_max_ind_entry_neutral_n = getattr(cfg, "max_ind_entry_neutral_n", None)
    _cfg_min_ind_entry_bull_n = getattr(cfg, "min_ind_entry_bull_n", None)
    _min_ind_score_thr = _cfg_min_ind_score(cfg)
    _cfg_min_ind_score_active = _cfg_min_ind_score_filter_active(cfg)
    _sym_indicator_pre: Optional[Any] = None
    _aligned_bull_bear_diff_fn: Optional[Any] = None
    _entry_bull_n_fn: Optional[Any] = None
    _entry_neutral_n_fn: Optional[Any] = None
    _cfg_collect_ind_while_held = indicators_while_held_rows_out is not None
    _cfg_sell_ind_diff_below = _cfg_sell_ind_diff_threshold(cfg)
    _cfg_exit_ind_diff_only = bool(getattr(cfg, "exit_ind_diff_only", False)) and (
        _cfg_sell_ind_diff_below is not None
    )
    _need_indicator_pre = (
        _cfg_use_indicators
        or _cfg_indicator_buy in ("only", "both")
        or _cfg_max_ind_entry_neutral_n is not None
        or _cfg_min_ind_entry_bull_n is not None
        or _cfg_collect_ind_while_held
        or _cfg_sell_ind_diff_below is not None
        or _cfg_min_ind_score_active
    )
    _ind_score_at_bar_fn: Optional[Any] = None
    if _need_indicator_pre:
        try:
            from brt_entry_indicators import (
                aligned_bull_bear_diff as _aligned_bull_bear_diff_fn_bt,
                build_entry_indicator_precompute,
                entry_bull_n as _entry_bull_n_fn_bt,
                entry_neutral_n as _entry_neutral_n_fn_bt,
                ind_score_at_bar as _ind_score_at_bar_fn_bt,
            )
        except ImportError:
            from stock_analysis.brt_entry_indicators import (
                aligned_bull_bear_diff as _aligned_bull_bear_diff_fn_bt,
                build_entry_indicator_precompute,
                entry_bull_n as _entry_bull_n_fn_bt,
                entry_neutral_n as _entry_neutral_n_fn_bt,
                ind_score_at_bar as _ind_score_at_bar_fn_bt,
            )
        if _cfg_min_ind_score_active:
            _ind_score_at_bar_fn = _ind_score_at_bar_fn_bt
        if _cfg_indicator_buy in ("only", "both") or _cfg_sell_ind_diff_below is not None:
            _aligned_bull_bear_diff_fn = _aligned_bull_bear_diff_fn_bt
        if _cfg_max_ind_entry_neutral_n is not None or _cfg_min_ind_entry_bull_n is not None:
            _entry_bull_n_fn = _entry_bull_n_fn_bt
            _entry_neutral_n_fn = _entry_neutral_n_fn_bt
        _t_ind = time.perf_counter()
        _sym_indicator_pre = build_entry_indicator_precompute(
            df,
            symbol=sym,
            cache_dir=(str(getattr(cfg, "indicator_cache_dir", "") or "").strip() or None),
            use_cache=bool(getattr(cfg, "indicator_cache", True)),
        )
        _acc_bt("bt_indicators", time.perf_counter() - _t_ind)
        if _sym_indicator_pre is None and (
            _cfg_indicator_buy in ("only", "both")
            or _cfg_max_ind_entry_neutral_n is not None
            or _cfg_min_ind_entry_bull_n is not None
            or _cfg_sell_ind_diff_below is not None
        ):
            # In ProcessPoolExecutor workers, stderr breaks the parent's \r progress line on Windows;
            # only emit this diagnostic from the main interpreter process.
            try:
                import multiprocessing as _mp_bt

                _ind_warn_ok = _mp_bt.current_process().name == "MainProcess"
            except Exception:
                _ind_warn_ok = True
            if _ind_warn_ok:
                _ind_gate_note = (
                    f"indicator_buy={_cfg_indicator_buy}"
                    if _cfg_indicator_buy in ("only", "both")
                    else "ind_entry_count gates"
                )
                print(
                    f"[BRT] {sym}: {_ind_gate_note} but entry-indicator precompute is unavailable "
                    f"(need ~220 bars with OHLCV); indicator gate rejects all entries for this symbol.",
                    file=sys.stderr,
                )

    def _band_pct_at(i_bar: int, zc_px: float) -> float:
        if not (np.isfinite(zc_px) and zc_px > 0):
            return float(cfg.band_pct)
        return _effective_band_pct_tp(float(zc_px), int(i_bar), atr_14_arr, float(cfg.band_pct), _cfg_band_pct_atr)

    _pending_ind_diff_exit = False
    for i in range(n - 1):
        _t_bar = time.perf_counter() if _perf else 0.0
        _exited_this_bar = False
        iso = index_iso[i]
        next_iso = index_iso[i + 1]
        op = open_arr[i]
        hi = high_arr[i]
        lo = low_arr[i]
        cl = close_arr[i]
        next_op = open_arr[i + 1]

        _t_cb = time.perf_counter() if _perf else 0.0
        # --- Consolidation Blocker (CB) update on bar i ---
        # Update last pivot highs/lows from Level 1 pivots
        pivot_high_price = float(ph_arr[i]) if i < len(ph_arr) else 0.0
        pivot_low_price = float(pl_arr[i]) if i < len(pl_arr) else 0.0
        pivot_high_flag = pivot_high_price > 0.0
        pivot_low_flag = pivot_low_price > 0.0
        if pivot_high_flag:
            last_pivot_high = pivot_high_price
        if pivot_low_flag:
            last_pivot_low = pivot_low_price

        # Box reset/start when uninitialized or broken (Close-based)
        box_invalid = box_ceiling is None or box_floor is None
        box_broken = False
        if not box_invalid:
            if cl > box_ceiling or cl < box_floor:
                box_broken = True
        if box_invalid or box_broken:
            inside_high_count = 0
            inside_low_count = 0
            cb_active = False
            if last_pivot_high is not None and last_pivot_low is not None:
                box_ceiling = last_pivot_high
                box_floor = last_pivot_low
            else:
                box_ceiling = None
                box_floor = None

        # Inside counting only when box is valid and unbroken
        if box_ceiling is not None and box_floor is not None and not (cl > box_ceiling or cl < box_floor):
            if pivot_high_flag and pivot_high_price <= box_ceiling:
                inside_high_count += 1
            if pivot_low_flag and pivot_low_price >= box_floor:
                inside_low_count += 1

        # Consolidation Blocker active only when:
        # - insideHighCount and insideLowCount meet thresholds
        # - price is inside the box
        # - box width is tight enough: (box_ceiling / box_floor - 1) <= cb_max_box_width_pct
        cb_active = False
        if box_ceiling is not None and box_floor is not None and box_floor > 0:
            price_inside_box = (cl <= box_ceiling) and (cl >= box_floor)
            box_width_pct = (box_ceiling / box_floor) - 1.0
            if (
                inside_high_count >= inside_required_high
                and inside_low_count >= inside_required_low
                and price_inside_box
                and box_width_pct <= _cfg_cb_max_box
            ):
                cb_active = True

        if _perf:
            _acc_bt("bt_loop_cb", time.perf_counter() - _t_cb)

        # --- EXIT LOGIC (if we have a position) ---
        # Resolution order (first match wins): gap down, gap up, intraday stop, intraday target
        _t_ex = time.perf_counter() if _perf else 0.0
        if open_trade is not None:
            _closed_t, max_high_since_entry, _pending_ind_diff_exit, _exit_early = _brt_attempt_exit_at_bar(
                open_trade,
                max_high_since_entry,
                _pending_ind_diff_exit,
                sym=sym,
                i=i,
                iso=iso,
                op=op,
                hi=hi,
                lo=lo,
                cl=cl,
                cfg=cfg,
                df=df,
                index_iso=index_iso,
                open_arr=open_arr,
                high_arr=high_arr,
                close_arr=close_arr,
                sma_stop_arr=sma_stop_arr,
                cfg_sell_ind_diff_below=_cfg_sell_ind_diff_below,
                cfg_exit_ind_diff_only=_cfg_exit_ind_diff_only,
                cfg_sell_on_low_vol=_cfg_sell_on_low_vol,
                cfg_trailing_stop_inc=_cfg_trailing_stop_inc,
                cfg_sma_stop_days=_cfg_sma_stop_days,
                cfg_stop_cmp_rd=_cfg_stop_cmp_rd,
                use_atr_exits_loop=_use_atr_exits_loop,
                sym_indicator_pre=_sym_indicator_pre,
                aligned_bull_bear_diff_fn=_aligned_bull_bear_diff_fn,
            )
            if _exit_early:
                if _perf:
                    _acc_bt("bt_loop_exit", time.perf_counter() - _t_ex)
                    _acc_bt("bt_loop_bar_total", time.perf_counter() - _t_bar)
                continue
            if _closed_t is not None:
                closed.append(_closed_t)
                if _cfg_pbr_zones:
                    _pbr_on_exit(_closed_t, i)
                last_exit_yyyymmdd = str(iso).strip().replace("-", "")[:8]
                open_trade = None
                _exited_this_bar = True
        if _cfg_allow_secondary:
            for _si in range(len(extra_open_trades) - 1, -1, -1):
                _sec = extra_open_trades[_si]
                _closed_t, _mh, _pend, _exit_early = _brt_attempt_exit_at_bar(
                    _sec,
                    _secondary_max_high[_si],
                    _secondary_pending_ind[_si],
                    sym=sym,
                    i=i,
                    iso=iso,
                    op=op,
                    hi=hi,
                    lo=lo,
                    cl=cl,
                    cfg=cfg,
                    df=df,
                    index_iso=index_iso,
                    open_arr=open_arr,
                    high_arr=high_arr,
                    close_arr=close_arr,
                    sma_stop_arr=sma_stop_arr,
                    cfg_sell_ind_diff_below=_cfg_sell_ind_diff_below,
                    cfg_exit_ind_diff_only=_cfg_exit_ind_diff_only,
                    cfg_sell_on_low_vol=_cfg_sell_on_low_vol,
                    cfg_trailing_stop_inc=_cfg_trailing_stop_inc,
                    cfg_sma_stop_days=_cfg_sma_stop_days,
                    cfg_stop_cmp_rd=_cfg_stop_cmp_rd,
                    use_atr_exits_loop=_use_atr_exits_loop,
                    sym_indicator_pre=_sym_indicator_pre,
                    aligned_bull_bear_diff_fn=_aligned_bull_bear_diff_fn,
                )
                _secondary_max_high[_si] = _mh
                _secondary_pending_ind[_si] = _pend
                if _closed_t is not None:
                    closed.append(_closed_t)
                    if _cfg_pbr_zones:
                        _pbr_on_exit(_closed_t, i)
                    last_exit_yyyymmdd = str(iso).strip().replace("-", "")[:8]
                    extra_open_trades.pop(_si)
                    _secondary_max_high.pop(_si)
                    _secondary_pending_ind.pop(_si)
                    _exited_this_bar = True

        if _perf:
            _acc_bt("bt_loop_exit", time.perf_counter() - _t_ex)

        _t_sc = time.perf_counter() if _perf else 0.0
        # --- Short candidate flag (for future shorting) ---
        if short_candidate_arr[i]:
            dt = f"{iso[:4]}-{iso[4:6]}-{iso[6:8]}" if len(iso) >= 8 else iso
            short_candidates.append({
                "symbol": sym, "date": dt, "zone_center": zone_center_arr[i],
                "close": cl, "touch_count": int(touch_count_long_arr[i]),
            })

        if _perf:
            _acc_bt("bt_loop_short", time.perf_counter() - _t_sc)

        # --- MTS entry trigger: DP first touch after availability; BI buy gate on eval bar ---
        if _cfg_mts_first_touch and dp_first_touch_arr is not None:
            if dp_first_touch_arr[i] and de_ctx_arr is not None and df_ctx_arr is not None:
                _dp_zl = float(de_ctx_arr[i])
                _dp_zh = float(df_ctx_arr[i])
                _dp_mb = int(dg_ctx_arr[i]) if (dg_ctx_arr is not None and np.isfinite(dg_ctx_arr[i])) else i
                if np.isfinite(_dp_zl) and np.isfinite(_dp_zh):
                    sh_val = struct_high_arr[i] if i < len(struct_high_arr) and pd.notna(struct_high_arr[i]) and struct_high_arr[i] else ""
                    sl_val = struct_low_arr[i] if i < len(struct_low_arr) and pd.notna(struct_low_arr[i]) and struct_low_arr[i] else ""
                    pending_maturities.append({
                        "maturity_bar": i,
                        "zone_center": (_dp_zl + _dp_zh) / 2.0,
                        "zone_low": _dp_zl,
                        "zone_high": _dp_zh,
                        "touch_count": int(touch_count_long_arr[i]) if i < len(touch_count_long_arr) else 0,
                        "touch_count_major": 0,
                        "touch_count_minor": 0,
                        "struct_high": sh_val,
                        "struct_low": sl_val,
                        "mts_first_touch": True,
                    })
            # DP is authoritative for MTS: skip the AR/AW magic-touch pending creator below.
            _mts_dp_skip_magic = True
        else:
            _mts_dp_skip_magic = False

        # --- PBR entry trigger: first opportunity + resume-scan after profitable first trade ---
        if _cfg_pbr_zones:
            sh_val = struct_high_arr[i] if i < len(struct_high_arr) and pd.notna(struct_high_arr[i]) and struct_high_arr[i] else ""
            sl_val = struct_low_arr[i] if i < len(struct_low_arr) and pd.notna(struct_low_arr[i]) and struct_low_arr[i] else ""

            def _pbr_append_pending(opp: dict) -> None:
                _zid = str(opp.get("pbr_zone_id", "") or "")
                if _zid and (not _pbr_allows_new_entry(_zid) or _pbr_pending_has_zone(_zid)):
                    return
                try:
                    _zl = float(opp.get("zone_lower", float("nan")))
                    _zh = float(opp.get("zone_upper", float("nan")))
                except (TypeError, ValueError):
                    return
                if not (np.isfinite(_zl) and np.isfinite(_zh)):
                    return
                try:
                    _zc = float(opp.get("zone_center", (_zl + _zh) / 2.0))
                except (TypeError, ValueError):
                    _zc = (_zl + _zh) / 2.0
                pending_maturities.append(
                    {
                        "maturity_bar": i,
                        "zone_center": _zc if np.isfinite(_zc) else (_zl + _zh) / 2.0,
                        "zone_low": _zl,
                        "zone_high": _zh,
                        "touch_count": 1,
                        "touch_count_major": 0,
                        "touch_count_minor": 0,
                        "struct_high": sh_val,
                        "struct_low": sl_val,
                        "pbr_retest_entry": True,
                        "from_retest_row": True,
                        "pbr_zone_id": _zid,
                        "pbr_opportunity_index": int(opp.get("opportunity_index", 0) or 0),
                    }
                )

            for _opp in pbr_entries_by_bar.get(i, []):
                _pbr_append_pending(_opp)

            # After a profitable first purchase (when pbr_second_chance_after_win), resume retest/signal scan.
            if _cfg_pbr_second_chance and _pbr_find_signal is not None:
                for _zid, _st in list(pbr_zone_state.items()):
                    if not _st.get("allow_second") or _st.get("retired") or _st.get("open"):
                        continue
                    if _pbr_pending_has_zone(_zid):
                        continue
                    _meta = pbr_zone_meta.get(_zid) or {}
                    try:
                        _resume = int(_st.get("resume_scan_bar", -1))
                    except (TypeError, ValueError):
                        continue
                    if _resume < 0 or _resume > i:
                        continue
                    try:
                        _zl = float(_meta.get("zone_lower", float("nan")))
                        _zh = float(_meta.get("zone_upper", float("nan")))
                        _zc = float(_meta.get("zone_center", (_zl + _zh) / 2.0))
                        _max_d = int(_meta.get("max_days_after_retest", getattr(cfg, "pbr_max_days_after_retest", 2)) or 2)
                    except (TypeError, ValueError):
                        continue
                    _rt, _sig, _fill = _pbr_find_signal(
                        low_arr,
                        close_arr,
                        open_arr,
                        scan_start=_resume,
                        zone_lower=_zl,
                        zone_upper=_zh,
                        max_days_after_retest=_max_d,
                        n=n,
                        stop_at=i,
                    )
                    if _sig == i and _fill is not None:
                        _pbr_append_pending(
                            {
                                "pbr_zone_id": _zid,
                                "zone_lower": _zl,
                                "zone_upper": _zh,
                                "zone_center": _zc,
                                "retest_bar": _rt,
                                "entry_signal_bar": _sig,
                                "entry_fill_bar": _fill,
                                "opportunity_index": 1,
                            }
                        )
                        # If this signal day is skipped by gates, look for a later retest.
                        _st["resume_scan_bar"] = i + 1
            if any(bool(p.get("pbr_retest_entry")) and int(p.get("maturity_bar", -1)) == i for p in pending_maturities):
                _mts_dp_skip_magic = True

        # --- Pending maturities: touch event (AW) ---
        # Default: maturity when touch_count_long crosses threshold.
        # Optional sheet AW parity: use AR/AW semantics based on lagged CE/CF ladder and CD touches.
        touch_event_now = False
        touch_event_tc = 0
        zc = zone_center_arr[i]
        _bp_i0 = _band_pct_at(i, float(zc)) if pd.notna(zc) else float(cfg.band_pct)
        zl = float(zc) * (1 - _bp_i0) if pd.notna(zc) else float("nan")
        zh = float(zc) * (1 + _bp_i0) if pd.notna(zc) else float("nan")
        if _mts_dp_skip_magic:
            pass
        elif _smt_bounds_fn is not None:
            if cprofile_magic_touch is not None:
                cprofile_magic_touch.enable()
            try:
                _t_smt = time.perf_counter() if _perf else 0.0
                win = _smt_win_magic
                _smt_bounds_at_i = _smt_bounds_fn(i)
                ok_act, zl_act, zh_act, _ = _smt_bounds_at_i
                ok_prev, zl_prev, zh_prev, _ = _smt_prev_bar
                if zone_cmp_round_bt >= 0:
                    zc_changed = not (
                        ok_act and ok_prev
                        and np.isfinite(zl_act) and np.isfinite(zh_act) and np.isfinite(zl_prev) and np.isfinite(zh_prev)
                        and round(zl_act, zone_cmp_round_bt) == round(zl_prev, zone_cmp_round_bt)
                        and round(zh_act, zone_cmp_round_bt) == round(zh_prev, zone_cmp_round_bt)
                    )
                else:
                    zc_changed = not (ok_act and ok_prev and np.isfinite(zl_act) and np.isfinite(zh_act) and np.isfinite(zl_prev) and np.isfinite(zh_prev)
                                      and abs(zl_act - zl_prev) <= 1e-12 and abs(zh_act - zh_prev) <= 1e-12)
                if ok_act:
                    start = max(0, i - win + 1)
                    end = i
                    seg = cd_touch_arr[start : end + 1]
                    ar = int(np.sum(np.isfinite(seg) & (seg > 0) & (seg >= zl_act) & (seg <= zh_act)))
                    if i > 0 and ok_prev:
                        start_p = max(0, (i - 1) - win + 1)
                        end_p = i - 1
                        seg_p = cd_touch_arr[start_p : end_p + 1]
                        ar_prev = int(
                            np.sum(np.isfinite(seg_p) & (seg_p > 0) & (seg_p >= zl_prev) & (seg_p <= zh_prev))
                        )
                    else:
                        ar_prev = 0
                    thr = _cfg_thr_magic
                    touch_event_now = bool((ar >= thr) and ((ar_prev < thr) or zc_changed))
                    touch_event_tc = int(ar)
                    zc = (zl_act + zh_act) / 2.0
                    zl = zl_act
                    zh = zh_act
                if _perf:
                    _acc_bt("bt_loop_sheet_magic_touch", time.perf_counter() - _t_smt)
                _smt_prev_bar = _smt_bounds_at_i
            finally:
                if cprofile_magic_touch is not None:
                    cprofile_magic_touch.disable()
        else:
            # Legacy maturity event
            if i < len(touch_count_long_arr) and int(touch_count_long_arr[i]) >= _cfg_touch_threshold:
                prev_tc = int(touch_count_long_arr[i - 1]) if i > 0 else 0
                zc_i = zone_center_arr[i]
                zc_prev = zone_center_arr[i - 1] if i > 0 else np.nan
                _bp_ii = _band_pct_at(i, float(zc_i)) if pd.notna(zc_i) else float(cfg.band_pct)
                _bp_ip = _band_pct_at(i - 1, float(zc_prev)) if pd.notna(zc_prev) else float(cfg.band_pct)
                zh_i = float(zc_i) * (1 + _bp_ii) if pd.notna(zc_i) else np.nan
                zh_prev = float(zc_prev) * (1 + _bp_ip) if pd.notna(zc_prev) else np.nan
                zone_changed = bool(pd.notna(zh_i) and pd.notna(zh_prev) and (abs(zh_i - zh_prev) > 1e-12))
                touch_event_now = bool((prev_tc < _cfg_touch_threshold) or zone_changed)
                touch_event_tc = int(touch_count_long_arr[i])
        if touch_event_now:
            _zrm_ev = _normalize_zone_role_mode(getattr(cfg, "zone_role_mode", "dynamic"))
            if _zrm_ev == "by_origin":
                _magic_ev = bool(getattr(cfg, "sheet_magic_touch_enabled", False))
                _lag_ev = max(0, lag_c14)
                _src_ev = (i - _lag_ev) if (_magic_ev and _lag_ev > 0) else i
                _oc_ev = int(_zone_origin_np_bt[_src_ev]) if 0 <= _src_ev < len(_zone_origin_np_bt) else 0
                _eff_ev = _effective_zone_role(_oc_ev, str(getattr(cfg, "zone_role_override", "")))
                if not _zone_role_allows_entry(_zrm_ev, _eff_ev, _cfg_entry_side):
                    touch_event_now = False
                    _count_block("zone_role_by_origin")
        if touch_event_now and (not _cfg_entry_from_retest_only):
            _t_ma = time.perf_counter() if _perf else 0.0

            # Long-window touches within band, split into major vs minor pivots
            major_touches = 0
            minor_touches = 0
            if pd.notna(zc):
                try:
                    start_long = max(0, i - cfg.lookback_long + 1)
                    end = i + 1
                    ph_win = ph_arr[start_long:end]
                    pl_win = pl_arr[start_long:end]
                    in_band_high = (ph_win > 0) & (ph_win >= zl) & (ph_win <= zh)
                    in_band_low = (pl_win > 0) & (pl_win >= zl) & (pl_win <= zh)
                    is_touch = in_band_high | in_band_low
                    if mp_h_arr is not None and mp_l_arr is not None:
                        mp_h_win = mp_h_arr[start_long:end]
                        mp_l_win = mp_l_arr[start_long:end]
                        is_major = is_touch & ((mp_h_win == 1) | (mp_l_win == 1))
                    else:
                        is_major = np.zeros_like(is_touch, dtype=bool)
                    major_touches = int(np.sum(is_major))
                    minor_touches = int(np.sum(is_touch)) - major_touches
                except Exception:
                    major_touches = 0
                    minor_touches = 0

            sh_val = struct_high_arr[i] if i < len(struct_high_arr) and pd.notna(struct_high_arr[i]) and struct_high_arr[i] else ""
            sl_val = struct_low_arr[i] if i < len(struct_low_arr) and pd.notna(struct_low_arr[i]) and struct_low_arr[i] else ""
            pending_maturities.append({
                "maturity_bar": i, "zone_center": zc,
                "zone_low": zl,  # Zone lower of trigger (6th-touch bar) for 7/10
                "zone_high": zh,  # Zone upper of trigger; used for AW zone-change semantics
                "touch_count": int(touch_event_tc) if touch_event_tc else int(touch_count_long_arr[i]),
                "touch_count_major": major_touches,
                "touch_count_minor": minor_touches,
                "struct_high": sh_val,
                "struct_low": sl_val,
            })
            if _perf:
                _acc_bt("bt_loop_maturity", time.perf_counter() - _t_ma)

        # Retest-date entry source: add synthetic pending candidates on retest bars so
        # entry gates run even when no touch-event pending exists.
        # MTS (mts_first_touch_entry) has NO retest pipeline — DP first-touch is authoritative.
        _rt_rows = [] if (_cfg_mts_first_touch or _cfg_pbr_zones) else retest_rows_by_iso.get(iso, [])
        _rt_rows = _filter_retest_rows_for_zone_pick(_rt_rows, _cfg_retest_pick)
        if _rt_rows and not (_cfg_no_entry_same_bar_exit and _exited_this_bar):
            for _rr in _rt_rows:
                _b = int(_rr.get("breakout_bar", i))
                _b = max(0, min(n - 1, _b))
                _mb = i  # retest row is the signal row for row_local TTL / eval
                _zl = float(_rr.get("zone_lower", float("nan")))
                _zu = float(_rr.get("zone_upper", float("nan")))
                if not (np.isfinite(_zl) and np.isfinite(_zu)):
                    continue
                _zc = (_zl + _zu) / 2.0
                sh_val = struct_high_arr[_b] if _b < len(struct_high_arr) and pd.notna(struct_high_arr[_b]) and struct_high_arr[_b] else ""
                sl_val = struct_low_arr[_b] if _b < len(struct_low_arr) and pd.notna(struct_low_arr[_b]) and struct_low_arr[_b] else ""
                pending_maturities.append({
                    "maturity_bar": _mb,
                    "zone_center": _zc,
                    "zone_low": _zl,
                    "zone_high": _zu,
                    "breakout_bar": _b,
                    "touch_count": int(touch_count_long_arr[_b]) if _b < len(touch_count_long_arr) else 0,
                    "touch_count_major": 0,
                    "touch_count_minor": 0,
                    "struct_high": sh_val,
                    "struct_low": sl_val,
                    "from_retest_row": True,
                })

        # Check pending maturities: evaluate entry gates on each bar until entry/expiry by other rules.
        still_pending: list[dict] = []
        eval_mode_global = _cfg_eval_mode
        _t_ar = time.perf_counter() if _perf else 0.0
        if eval_mode_global == "row_local":
            if _use_sheet_ctx and dg_ctx_arr is not None and i < len(dg_ctx_arr) and np.isfinite(dg_ctx_arr[i]):
                active_bar_today = int(dg_ctx_arr[i])
            else:
                active_bar_today = _brt_active_zone_maturity_bar(i, pending_maturities, high_arr, low_arr)
            if _use_sheet_ctx and dg_ctx_arr is not None and i > 0 and (i - 1) < len(dg_ctx_arr) and np.isfinite(dg_ctx_arr[i - 1]):
                active_bar_prev = int(dg_ctx_arr[i - 1])
            elif i > 0:
                active_bar_prev = _brt_active_zone_maturity_bar(i - 1, pending_maturities, high_arr, low_arr)
            else:
                active_bar_prev = None
        else:
            active_bar_today = None
            active_bar_prev = None
        if _perf:
            _acc_bt("bt_pending_active_zone", time.perf_counter() - _t_ar)
        _t_prep = time.perf_counter() if _perf else 0.0
        _gate_fns_sheet: Optional[_SheetLadderGateFns] = _gate_fns_sheet_global
        if _perf:
            _acc_bt("bt_loop_pending_sheet_prep", time.perf_counter() - _t_prep)
        _t_pfor = time.perf_counter() if _perf else 0.0
        # Debug flag for entry logic
        debug_entry = _DEBUG_SYMBOL and sym == _DEBUG_SYMBOL and _DEBUG_DATE
        debug_date_prefix = _DEBUG_DATE.replace("-", "")[:6] if _DEBUG_DATE else ""  # e.g., "202207"
        _debug_logged_open_trade_block = False
        for p in pending_maturities:
            _atr_pct_gate: Optional[float] = None
            # MTS DP pending TTL: only evaluate on the DP bar and the next bar (OR(BC,BC[-1]));
            # otherwise drop so a stale first-touch event cannot enter on an unrelated later bar.
            if _cfg_mts_first_touch and bool(p.get("mts_first_touch", False)):
                _mts_mb = int(p.get("maturity_bar", i))
                if i - _mts_mb > 1:
                    continue
            # PBR zone lifecycle: drop candidates from retired / open / already-used zones.
            if _cfg_pbr_zones and bool(p.get("pbr_retest_entry", False)):
                _pbr_zid = str(p.get("pbr_zone_id", "") or "")
                if _pbr_zid and not _pbr_allows_new_entry(_pbr_zid):
                    continue
            if _cfg_no_entry_same_bar_exit and _exited_this_bar:
                if not bool(p.get("from_retest_row", False)):
                    still_pending.append(p)
                continue
            if open_trade is not None and not _cfg_allow_secondary:
                if debug_entry and not _debug_logged_open_trade_block:
                    _debug_logged_open_trade_block = True
                    _do = str(getattr(open_trade, "date_opened", "") or "")
                    _do_fmt = (
                        f"{_do[:4]}-{_do[4:6]}-{_do[6:8]}" if len(_do) >= 8 and _do[:8].isdigit() else _do
                    )
                    print(
                        f"[DEBUG-ENTRY] {sym} bar {i} ({index_iso[i][:10]}): skip all new-entry gate checks — "
                        f"already in open trade (opened {_do_fmt} @ {getattr(open_trade, 'entry_price', '')})"
                    )
                if not bool(p.get("from_retest_row", False)):
                    still_pending.append(p)
                continue
            _from_retest_row = bool(p.get("from_retest_row", False))
            def _keep_pending() -> None:
                if not _from_retest_row:
                    still_pending.append(p)
                    return
                # Synthetic retest pending: first overlap day is often not the bullish **AK** bar; keep the
                # candidate for ``close_above_window`` bars after ``maturity_bar`` (same idea as touch
                # maturity + next session). Without this, BY=1/8 + buy 1/9 never runs (pending dropped on 1/8).
                _mb_r = int(p.get("maturity_bar", -1))
                _ca_win = max(0, int(getattr(cfg, "close_above_window", 1) or 0))
                if _mb_r >= 0 and (i - _mb_r) <= _ca_win:
                    still_pending.append(p)
            _t_p = time.perf_counter() if _perf else 0.0
            _t_mid: Optional[float] = None

            def _pg() -> None:
                if _pbt is None:
                    return
                now = time.perf_counter()
                if _t_mid is None:
                    _acc_bt("bt_pending_gates_early", now - _t_p)
                    _acc_bt("bt_pending_gates", now - _t_p)
                else:
                    _acc_bt("bt_pending_gates_early", _t_mid - _t_p)
                    _acc_bt("bt_pending_gates_sheet", now - _t_mid)
                    _acc_bt("bt_pending_gates", now - _t_p)

            maturity_bar = p["maturity_bar"]
            # Outer bar index for this backtest day (loop i is in range(n-1)). Used for scanner vs open_trade split.
            _i_bar = i
            zc = p["zone_center"]
            zone_low = p["zone_low"]
            zl, zh = _pending_zone_band_zl_zh(p, int(maturity_bar), _band_pct_at)
            _rd_zone = int(zone_cmp_round_bt)
            _zm_bar_opt = _find_last_matured_identical_band_bar(
                zl_full_arr,
                zh_full_arr,
                matured_now_arr,
                float(zl),
                float(zh),
                int(maturity_bar),
                _rd_zone,
            )
            _md_bar = int(_zm_bar_opt) if _zm_bar_opt is not None else int(maturity_bar)
            _md_iso = index_iso[_md_bar] if 0 <= _md_bar < len(index_iso) else ""
            _md_iso8 = _md_iso[:8] if len(_md_iso) >= 8 else ""
            maturity_date = f"{_md_iso[:4]}-{_md_iso[4:6]}-{_md_iso[6:8]}" if len(_md_iso) >= 8 else _md_iso
            trace_eval = (
                len(_TRACE_DATES) > 0
                and index_iso[i] in _TRACE_DATES
                and (_TRACE_SYMBOL is None or sym == _TRACE_SYMBOL)
            )
            # Default signal row to loop day; row_local last-bar case may bump to i+1 below.
            _eval_bar = i

            def _trace_gate(msg: str) -> None:
                if trace_eval:
                    i_iso = index_iso[i]
                    i_fmt = f"{i_iso[:4]}-{i_iso[4:6]}-{i_iso[6:8]}" if len(i_iso) >= 8 else i_iso
                    row_note = ""
                    if _eval_bar != i and _eval_bar < len(index_iso):
                        ev_iso = index_iso[_eval_bar]
                        ev_fmt = (
                            f"{ev_iso[:4]}-{ev_iso[4:6]}-{ev_iso[6:8]}" if len(ev_iso) >= 8 else ev_iso
                        )
                        row_note = f" ohlc_row={ev_fmt}"
                    print(
                        f"[TRACE] {sym} loop_i={i_fmt}{row_note} maturity={maturity_date} "
                        f"zc={float(p.get('zone_center', float('nan'))):.4f} :: {msg}"
                    )
            # One-bar gate trace (noisy); enable only when --debug-symbol NVDA is set.
            debug_eval_onebar = (
                _DEBUG_SYMBOL is not None
                and sym == _DEBUG_SYMBOL
                and index_iso[i] == "20221201"
            )

            def _debug_gate_fail(reason: str) -> None:
                if debug_eval_onebar:
                    print(
                        f"[DEBUG-GATE-ONEBAR] {sym} eval=2022-12-01 maturity={maturity_date} "
                        f"zc={float(p.get('zone_center', float('nan'))):.4f} :: {reason}"
                    )

            _cd_days = int(getattr(cfg, "symbol_reentry_cooldown_days", 0) or 0)
            if _cd_days > 0 and last_exit_yyyymmdd:
                _entry_cd_bar = int(_i_bar) + 1
                if 0 <= _entry_cd_bar < len(index_iso):
                    _entry_cd_iso = index_iso[_entry_cd_bar]
                    if _symbol_reentry_cooldown_blocks(last_exit_yyyymmdd, _entry_cd_iso, _cd_days):
                        _count_block("symbol_reentry_cooldown")
                        _trace_gate(
                            f"block: symbol_reentry_cooldown ({_cd_days}d since exit "
                            f"{_last_exit_yyyymmdd_fmt(last_exit_yyyymmdd)})"
                        )
                        _keep_pending()
                        _pg()
                        continue

            eval_mode = eval_mode_global
            if eval_mode == "row_local":
                _from_retest_row = bool(p.get("from_retest_row", False))
                # Sheet-style row-local gating:
                # - keep today's touch event for next bar evaluation
                # - evaluate yesterday's touch event now
                # - drop anything older
                if maturity_bar == i:
                    if not _cfg_row_local_same_bar and not _from_retest_row:
                        # Defer to next bar — but the main loop only runs i in 0..n-2, so when the next bar is the
                        # last bar of data (i+1 == n-1) there is no following iteration; evaluate below using _eval_bar.
                        if i + 1 < n - 1:
                            _debug_gate_fail("skip: row_local keep today's touch event for next bar")
                            _keep_pending()
                            _trace_gate("skip: row_local keep today's touch event for next bar")
                            _pg()
                            continue
                if _cfg_rocket_buy:
                    _row_local_ttl = int(getattr(cfg, "pending_max_bars", 252))
                    if i > (maturity_bar + _row_local_ttl):
                        _debug_gate_fail("block: expired_touch_event_window (sheet row_local TTL)")
                        _count_block("expired_touch_event_window")
                        _trace_gate("block: expired_touch_event_window (sheet row_local TTL)")
                        _pg()
                        continue
                # No row-local TTL expiry in default retest-driven BRT mode.
                # DN-style active-zone parity: evaluate exactly one active zone context.
                # Prefer today's active zone; only fall back to prior row when today has no active zone.
                chosen_active_bar = active_bar_today if active_bar_today is not None else active_bar_prev
                if debug_eval_onebar:
                    print(
                        f"[DEBUG-ACTIVE-CTX-ONEBAR] {sym} eval=2022-12-01 maturity={maturity_date} "
                        f"maturity_bar={maturity_bar} active_today={active_bar_today} "
                        f"active_prev={active_bar_prev} chosen={chosen_active_bar}"
                    )
                if _cfg_row_local_ctx:
                    if chosen_active_bar is not None and maturity_bar != chosen_active_bar:
                        _debug_gate_fail(f"skip: not active zone context (chosen_active_bar={chosen_active_bar})")
                        _keep_pending()
                        _trace_gate(f"skip: not active zone context (chosen_active_bar={chosen_active_bar})")
                        _pg()
                        continue
            # Bar used for entry-gate OHLC (row_local end-of-series: evaluate on last bar i+1 when loop i is n-2).
            if (
                eval_mode_global == "row_local"
                and maturity_bar == i
                and not _cfg_row_local_same_bar
                and i + 1 == n - 1
            ):
                _eval_bar = i + 1
            if _eval_bar != i:
                op = open_arr[_eval_bar]
                hi = high_arr[_eval_bar]
                lo = low_arr[_eval_bar]
                cl = close_arr[_eval_bar]
            if _cfg_rocket_buy and bool(getattr(cfg, "sheet_magic_touch_enabled", False)):
                _magic_ttl = int(getattr(cfg, "pending_max_bars", 252))
                if _eval_bar > (maturity_bar + _magic_ttl):
                    _debug_gate_fail("block: expired_touch_event_window (sheet_magic_touch row-local TTL)")
                    _count_block("expired_touch_event_window")
                    _trace_gate("block: expired_touch_event_window (sheet_magic_touch row-local TTL)")
                    _keep_pending()
                    _pg()
                    continue
            # No pending TTL expiry checks (close_above_window/pending_max) in default retest-driven BRT.

            tc = p["touch_count"]
            tc_major = p.get("touch_count_major", 0)
            tc_minor = p.get("touch_count_minor", 0)
            sh = p["struct_high"]
            sl = p["struct_low"]
            # Bullish candle gate uses rounded OHLC (same decimals as zone_price_round_decimals) for sheet parity.
            op_ent = float(open_ent_arr[_eval_bar])
            cl_ent = float(close_ent_arr[_eval_bar])
            hi_ent = float(high_ent_arr[_eval_bar])
            lo_ent = float(low_ent_arr[_eval_bar])
            _is_long_side = _cfg_entry_side == "long"
            _pbr_prequalified = bool(p.get("pbr_retest_entry", False))
            if _cfg_require_close_gt_open and not _pbr_prequalified:
                side_bar_ok = (cl_ent > op_ent) if _is_long_side else (cl_ent < op_ent)
            else:
                side_bar_ok = True
            if not side_bar_ok:
                if _is_long_side:
                    _debug_gate_fail(f"block: close<=open ({cl_ent:.4f}<={op_ent:.4f})")
                    _trace_gate(f"block: close<=open ({cl_ent:.4f}<={op_ent:.4f})")
                    _count_block("close_le_open")
                else:
                    _debug_gate_fail(f"block: close>=open ({cl_ent:.4f}>={op_ent:.4f})")
                    _trace_gate(f"block: close>=open ({cl_ent:.4f}>={op_ent:.4f})")
                    _count_block("close_ge_open")
                if debug_entry and debug_date_prefix in _md_iso8:
                    if _is_long_side:
                        print(f"[DEBUG-ENTRY] {sym} bar {i} ({index_iso[i][:10]}): zone ${zc:.2f} BLOCKED by close<=open ({cl_ent:.2f}<={op_ent:.2f})")
                    else:
                        print(f"[DEBUG-ENTRY] {sym} bar {i} ({index_iso[i][:10]}): zone ${zc:.2f} BLOCKED by close>=open ({cl_ent:.2f}>={op_ent:.2f})")
                _keep_pending()
                _pg()
                continue
            if _cfg_rocket_buy and _eval_bar < _sheet_start_bar:
                _count_block("sheet_start_date")
                _trace_gate(f"block: sheet_start_date (eval_bar={_eval_bar}<{_sheet_start_bar})")
                _keep_pending()
                _pg()
                continue
            if _cfg_sheet_red_to_green and _is_long_side:
                if _eval_bar < 1:
                    _debug_gate_fail("block: red_to_green (no prior bar)")
                    _trace_gate("block: red_to_green (no prior bar)")
                    _count_block("sheet_red_to_green")
                    _keep_pending()
                    _pg()
                    continue
                op_prev = float(open_ent_arr[_eval_bar - 1])
                cl_prev = float(close_ent_arr[_eval_bar - 1])
                if not (cl_prev <= op_prev and cl_ent > op_ent):
                    _debug_gate_fail(
                        f"block: red_to_green (prior {cl_prev:.4f}<={op_prev:.4f} need today {cl_ent:.4f}>{op_ent:.4f})"
                    )
                    _trace_gate(
                        f"block: red_to_green (prior C<=O={cl_prev:.4f}<={op_prev:.4f}, today C>O={cl_ent:.4f}>{op_ent:.4f})"
                    )
                    _count_block("sheet_red_to_green")
                    if debug_entry and debug_date_prefix in _md_iso8:
                        print(
                            f"[DEBUG-ENTRY] {sym} bar {i} ({index_iso[i][:10]}): zone ${zc:.2f} BLOCKED by red_to_green "
                            f"(prior C={cl_prev:.2f} O={op_prev:.2f}, today C={cl_ent:.2f} O={op_ent:.2f})"
                        )
                    _keep_pending()
                    _pg()
                    continue
            # Optional: require close not in lower part of the bar (sheet: >= midpoint between high and low)
            if _cfg_entry_close_min_rng > 0.0:
                hi_i = hi_ent
                lo_i = lo_ent
                bar_rng = hi_i - lo_i
                min_pos = _cfg_entry_close_min_rng
                if bar_rng > 1e-12:
                    close_pos = (cl_ent - lo_i) / bar_rng
                    if (_is_long_side and (close_pos + 1e-12 < min_pos)) or (
                        (not _is_long_side) and (close_pos - 1e-12 > (1.0 - min_pos))
                    ):
                        _debug_gate_fail(f"block: close position in bar below min ({close_pos:.4f}<{min_pos:.4f})")
                        _count_block("bullish_close_below_range_mid")
                        _trace_gate(f"block: close position in bar below min ({close_pos:.4f}<{min_pos:.4f})")
                        if debug_entry and debug_date_prefix in _md_iso8:
                            print(
                                f"[DEBUG-ENTRY] {sym} bar {i} ({index_iso[i][:10]}): zone ${zc:.2f} BLOCKED by close not high enough in bar "
                                f"(pos={close_pos:.4f} < min={min_pos:.4f}; H={hi_i:.4f} L={lo_i:.4f} C={cl_ent:.4f})"
                            )
                        _keep_pending()
                        _pg()
                        continue
            # Touch count filters: TC >= min_touch_count, TC_MIN <= max_touch_count_minor, TC_SHORT <= max_touch_count_short
            if cfg.min_touch_count is not None and tc < cfg.min_touch_count:
                _debug_gate_fail(f"block: min_touch_count ({tc}<{cfg.min_touch_count})")
                _count_block("min_touch_count")
                _trace_gate(f"block: min_touch_count ({tc}<{cfg.min_touch_count})")
                if debug_entry and debug_date_prefix in _md_iso8:
                    print(f"[DEBUG-ENTRY] {sym} bar {i}: zone ${zc:.2f} BLOCKED by min_touch_count ({tc} < {cfg.min_touch_count})")
                _keep_pending()
                _pg()
                continue
            if cfg.max_touch_count_minor is not None and tc_minor > cfg.max_touch_count_minor:
                _debug_gate_fail(f"block: max_touch_count_minor ({tc_minor}>{cfg.max_touch_count_minor})")
                _count_block("max_touch_count_minor")
                _trace_gate(f"block: max_touch_count_minor ({tc_minor}>{cfg.max_touch_count_minor})")
                if debug_entry and debug_date_prefix in _md_iso8:
                    print(f"[DEBUG-ENTRY] {sym} bar {i}: zone ${zc:.2f} BLOCKED by max_touch_count_minor ({tc_minor} > {cfg.max_touch_count_minor})")
                _keep_pending()
                _pg()
                continue
            if cfg.max_touch_count_short is not None:
                tc_short = int(touch_count_short_arr[maturity_bar]) if maturity_bar < len(touch_count_short_arr) else 0
                if tc_short > cfg.max_touch_count_short:
                    _debug_gate_fail(f"block: max_touch_count_short ({tc_short}>{cfg.max_touch_count_short})")
                    _count_block("max_touch_count_short")
                    _trace_gate(f"block: max_touch_count_short ({tc_short}>{cfg.max_touch_count_short})")
                    if debug_entry and debug_date_prefix in _md_iso8:
                        print(
                            f"[DEBUG-ENTRY] {sym} bar {i}: zone ${zc:.2f} BLOCKED by max_touch_count_short "
                            f"({tc_short} > {cfg.max_touch_count_short})"
                        )
                    _keep_pending()
                    _pg()
                    continue
            _entry_bar_meteor = int(_eval_bar)
            _had_meteoric_rise = (
                int(meteor_rise_ever_arr[_entry_bar_meteor])
                if 0 <= _entry_bar_meteor < len(meteor_rise_ever_arr)
                else 0
            )
            _had_meteoric_fall = (
                int(meteor_fall_ever_arr[_entry_bar_meteor])
                if 0 <= _entry_bar_meteor < len(meteor_fall_ever_arr)
                else 0
            )
            if _entry_filter_tri_state_blocks(
                _had_meteoric_rise, getattr(cfg, "entry_filter_meteoric_rise", "both")
            ):
                _debug_gate_fail("block: entry_filter_meteoric_rise")
                _count_block("entry_filter_meteoric_rise")
                _trace_gate(f"block: entry_filter_meteoric_rise (flag={_had_meteoric_rise})")
                _keep_pending()
                _pg()
                continue
            if _entry_filter_tri_state_blocks(
                _had_meteoric_fall, getattr(cfg, "entry_filter_meteoric_fall", "both")
            ):
                _debug_gate_fail("block: entry_filter_meteoric_fall")
                _count_block("entry_filter_meteoric_fall")
                _trace_gate(f"block: entry_filter_meteoric_fall (flag={_had_meteoric_fall})")
                _keep_pending()
                _pg()
                continue
            # indicator_buy: bull-bear diff gate; "only" uses IND-only bar scan (see run_indicator_only_backtest);
            # "both" adds diff gate on zone/retest path and skips sheet gates only when diff passes with indicator_buy=only
            # (legacy note: indicator_buy=only no longer runs this pending-maturity loop).
            _erg_only = _cfg_erg_only
            use_bh_bi = False
            _skip_brt_sheet_gates = False
            growth_pct: Optional[float] = None
            displacement_pct: Optional[float] = None
            # MTS: exact BI buy gate (BW AND OR(BC) AND BE AND BG AND OR(AQ)) is authoritative;
            # when it passes, skip the approximate BRT gate stack (level_acceptance/zone_eligible/
            # tight_range/etc.). BI already encodes close>open (BE) and 3yr growth (BW).
            if _cfg_mts_first_touch and mts_bi_arr is not None:
                if _eval_bar < 0 or _eval_bar >= n or not bool(mts_bi_arr[_eval_bar]):
                    _debug_gate_fail("block: mts_bi_gate (BW/BC/BE/BG/AQ)")
                    _count_block("mts_bi_gate")
                    _trace_gate("block: mts_bi_gate (BI = BW AND OR(BC) AND BE AND BG AND OR(AQ))")
                    _keep_pending()
                    _pg()
                    continue
                _skip_brt_sheet_gates = True
                _trace_gate("pass: mts_bi_gate (exact BI); skipping approximate BRT gates")
            _cfg_trace_ind = bool(getattr(cfg, "trace_indicator_buy", False))

            def _ind_gate_trace(msg: str) -> None:
                if _cfg_trace_ind and _cfg_indicator_buy in ("only", "both"):
                    i_iso = index_iso[i] if 0 <= i < len(index_iso) else str(i)
                    i_fmt = f"{i_iso[:4]}-{i_iso[4:6]}-{i_iso[6:8]}" if len(i_iso) >= 8 else i_iso
                    print(f"[IND-GATE] {sym} loop_i={i_fmt} :: {msg}", flush=True)

            if _cfg_indicator_buy in ("only", "both"):
                _trigger_i_ind = int(_eval_bar)
                _ind_diff_val: Optional[int] = None
                if _aligned_bull_bear_diff_fn is not None:
                    _ind_diff_val = _aligned_bull_bear_diff_fn(
                        _sym_indicator_pre, _trigger_i_ind, _cfg_entry_side
                    )
                _thr_ind = _cfg_indicator_diff
                if _use_avg_ind and 0 <= _trigger_i_ind < len(index_iso):
                    _av_ind = _avg_ind_map.get(index_iso[_trigger_i_ind])
                    if _av_ind is not None:
                        _thr_ind = max(_cfg_indicator_diff, _av_ind) if _avg_ind_combine else _av_ind
                if _ind_diff_val is None or float(_ind_diff_val) < _thr_ind:
                    _count_block("indicator_buy_diff")
                    _trace_gate(
                        f"block: indicator_buy diff ({_ind_diff_val} < {_thr_ind})"
                    )
                    _ind_gate_trace(
                        f"block diff ({_ind_diff_val} < {_thr_ind}) side={_cfg_entry_side} "
                        f"trigger_i={_trigger_i_ind}"
                    )
                    _keep_pending()
                    _pg()
                    continue
                if _cfg_indicator_buy == "only":
                    _skip_brt_sheet_gates = True
                    _ind_gate_trace(
                        f"pass diff={_ind_diff_val} side={_cfg_entry_side} "
                        f"skip_brt_sheet_gates=True (sheet gates bypassed)"
                    )
                else:
                    _ind_gate_trace(f"pass diff={_ind_diff_val} mode=both (sheet gates still apply)")

            if _cfg_max_ind_entry_neutral_n is not None or _cfg_min_ind_entry_bull_n is not None:
                _trigger_i_ind_counts = int(_eval_bar)
                if _sym_indicator_pre is None:
                    _count_block("ind_entry_counts_unavailable")
                    _trace_gate("block: ind_entry_counts precompute unavailable")
                    _keep_pending()
                    _pg()
                    continue
                if _cfg_max_ind_entry_neutral_n is not None and _entry_neutral_n_fn is not None:
                    _ind_neut_n = _entry_neutral_n_fn(_sym_indicator_pre, _trigger_i_ind_counts, _cfg_entry_side)
                    if _ind_neut_n is None or int(_ind_neut_n) > int(_cfg_max_ind_entry_neutral_n):
                        _debug_gate_fail(
                            f"block: max_ind_entry_neutral_n ({_ind_neut_n}>{_cfg_max_ind_entry_neutral_n})"
                        )
                        _count_block("max_ind_entry_neutral_n")
                        _trace_gate(
                            f"block: max_ind_entry_neutral_n ({_ind_neut_n}>{_cfg_max_ind_entry_neutral_n})"
                        )
                        if debug_entry and debug_date_prefix in _md_iso8:
                            print(
                                f"[DEBUG-ENTRY] {sym} bar {i}: zone ${zc:.2f} BLOCKED by max_ind_entry_neutral_n "
                                f"({_ind_neut_n} > {_cfg_max_ind_entry_neutral_n})"
                            )
                        _keep_pending()
                        _pg()
                        continue
                if _cfg_min_ind_entry_bull_n is not None and _entry_bull_n_fn is not None:
                    _ind_bull_n = _entry_bull_n_fn(_sym_indicator_pre, _trigger_i_ind_counts, _cfg_entry_side)
                    if _ind_bull_n is None or int(_ind_bull_n) < int(_cfg_min_ind_entry_bull_n):
                        _debug_gate_fail(
                            f"block: min_ind_entry_bull_n ({_ind_bull_n}<{_cfg_min_ind_entry_bull_n})"
                        )
                        _count_block("min_ind_entry_bull_n")
                        _trace_gate(
                            f"block: min_ind_entry_bull_n ({_ind_bull_n}<{_cfg_min_ind_entry_bull_n})"
                        )
                        if debug_entry and debug_date_prefix in _md_iso8:
                            print(
                                f"[DEBUG-ENTRY] {sym} bar {i}: zone ${zc:.2f} BLOCKED by min_ind_entry_bull_n "
                                f"({_ind_bull_n} < {_cfg_min_ind_entry_bull_n})"
                            )
                        _keep_pending()
                        _pg()
                        continue

            if _cfg_min_ind_score_active:
                _trigger_i_score = int(_eval_bar)
                if _sym_indicator_pre is None or _ind_score_at_bar_fn is None:
                    _count_block("min_ind_score_unavailable")
                    _trace_gate("block: min_ind_score precompute/weights unavailable")
                    _ind_gate_trace("block min_ind_score: indicator precompute unavailable")
                    _keep_pending()
                    _pg()
                    continue
                _ind_score_val = _ind_score_at_bar_fn(_sym_indicator_pre, _trigger_i_score)
                if _ind_score_val is None or float(_ind_score_val) < _min_ind_score_thr:
                    _debug_gate_fail(
                        f"block: min_ind_score ({_ind_score_val}<{_min_ind_score_thr:.2f})"
                    )
                    _count_block("min_ind_score")
                    _trace_gate(
                        f"block: min_ind_score ({_ind_score_val} < {_min_ind_score_thr:.2f})"
                    )
                    _ind_gate_trace(
                        f"block min_ind_score ({_ind_score_val} < {_min_ind_score_thr:.2f}) "
                        f"trigger_i={_trigger_i_score} side={_cfg_entry_side}"
                    )
                    if debug_entry and debug_date_prefix in _md_iso8:
                        print(
                            f"[DEBUG-ENTRY] {sym} bar {i}: zone ${zc:.2f} BLOCKED by min_ind_score "
                            f"({_ind_score_val} < {_min_ind_score_thr:.2f})"
                        )
                    _keep_pending()
                    _pg()
                    continue
                _ind_gate_trace(
                    f"pass min_ind_score={_ind_score_val:.2f} (>= {_min_ind_score_thr:.2f})"
                )

            # ATR% at trigger (signal bar close) — check early to skip expensive pivot/zone work on rejects.
            if _cfg_min_atr_trig > 0.0 or _cfg_max_atr_trig > 0.0:
                _atr_pct_gate = None
                _trig_a14, _atr_pct_gate = _atr_14_and_pct_at_bar(atr_14_arr, close_arr, int(_eval_bar))
                if _cfg_min_atr_trig > 0.0:
                    if (
                        _atr_pct_gate is None
                        or not np.isfinite(_atr_pct_gate)
                        or _atr_pct_gate < _cfg_min_atr_trig
                    ):
                        _count_block("min_atr_pct_at_trigger")
                        _keep_pending()
                        _pg()
                        continue
                if _cfg_max_atr_trig > 0.0:
                    if (
                        _atr_pct_gate is None
                        or not np.isfinite(_atr_pct_gate)
                        or _atr_pct_gate > _cfg_max_atr_trig
                    ):
                        _count_block("max_atr_pct_at_trigger")
                        _keep_pending()
                        _pg()
                        continue

            if _dist_52w_high_at_trigger_gate_blocks(cfg, high_arr, close_arr, int(_eval_bar)):
                _count_block("dist_to_52w_high_pct_at_trigger")
                _keep_pending()
                _pg()
                continue

            if _spy_compare_1y_at_trigger_gate_blocks(cfg, _rs_st, _rs_sp, int(_eval_bar)):
                _count_block("min_spy_compare_1y_at_trigger")
                _keep_pending()
                _pg()
                continue

            if _spy_compare_1y_max_at_trigger_gate_blocks(cfg, _rs_st, _rs_sp, int(_eval_bar)):
                _count_block("max_spy_compare_1y_at_trigger")
                _keep_pending()
                _pg()
                continue

            if _spy_compare_2y_at_trigger_gate_blocks(cfg, _rs_st, _rs_sp, int(_eval_bar)):
                _count_block("min_spy_compare_2y_at_trigger")
                _keep_pending()
                _pg()
                continue

            if _spy_compare_3y_at_trigger_gate_blocks(cfg, _rs_st, _rs_sp, int(_eval_bar)):
                _count_block("min_spy_compare_3y_at_trigger")
                _keep_pending()
                _pg()
                continue

            if _beta_min_at_trigger_gate_blocks(cfg, beta_by_bar_arr, int(_eval_bar)):
                _count_block("min_beta_at_trigger")
                _keep_pending()
                _pg()
                continue

            if _beta_max_at_trigger_gate_blocks(cfg, beta_by_bar_arr, int(_eval_bar)):
                _count_block("max_beta_at_trigger")
                _keep_pending()
                _pg()
                continue

            if _upper_wick_atr_min_at_trigger_gate_blocks(
                cfg, high_arr, open_arr, close_arr, atr_14_arr, int(_eval_bar)
            ):
                _count_block("min_upper_wick_atr_at_trigger")
                _keep_pending()
                _pg()
                continue

            if _mandatory_ind_states_gate_blocks(cfg, _sym_indicator_pre, int(_eval_bar), _cfg_entry_side):
                _count_block("mandatory_ind_states")
                _keep_pending()
                _pg()
                continue

            # Audit growth/displacement for trade record (always, even when sheet gates skipped).
            rb = cfg.displacement_rolling_bars
            _growth_ago = _growth_ago_bar_index(_eval_bar, cfg)
            if _growth_ago >= 0:
                price_now = close_arr[_eval_bar]
                price_ago = close_arr[_growth_ago]
                if price_ago > 0:
                    growth_pct = (price_now - price_ago) / price_ago * 100.0
            if maturity_bar >= rb - 1:
                close_at_maturity = close_arr[maturity_bar]
                roll_slice = close_arr[maturity_bar - rb + 1 : maturity_bar + 1]
                rolling_avg = float(np.mean(roll_slice))
                if rolling_avg > 0:
                    displacement_pct = abs(close_at_maturity / rolling_avg - 1.0)

            # Growth filter: programmatic gate (not skipped when indicator_buy=only).
            if bool(getattr(cfg, "sheet_growth_ok_mode", False)) and growth_ok_arr is not None:
                if not bool(growth_ok_arr[_eval_bar]):
                    _count_block("sheet_growth_ok_fail")
                    _trace_gate("block: sheet_growth_ok (BW: need >=2 of 1Y/2Y/3Y flags)")
                    _keep_pending()
                    _pg()
                    continue
            elif cfg.growth_filter_enabled and int(cfg.growth_bars) > 0:
                _growth_min = _growth_min_eval_bar_index(cfg)
                if _growth_ago < 0:
                    _count_block("growth_not_enough_history")
                    _trace_gate(
                        f"block: growth_not_enough_history (eval_bar={_eval_bar} < min={_growth_min}, "
                        f"growth_bars={cfg.growth_bars}, slack={_growth_history_slack_bars(cfg)})"
                    )
                    if debug_entry and debug_date_prefix in _md_iso8:
                        print(
                            f"[DEBUG-ENTRY] {sym} bar {i}: zone ${zc:.2f} BLOCKED by growth_filter "
                            f"(not enough history: eval_bar={_eval_bar} < min={_growth_min})"
                        )
                    _keep_pending()
                    _pg()
                    continue
                if growth_pct is None:
                    _count_block("growth_no_data")
                    _trace_gate("block: growth_no_data")
                    if debug_entry and debug_date_prefix in _md_iso8:
                        print(f"[DEBUG-ENTRY] {sym} bar {i}: zone ${zc:.2f} BLOCKED by growth_filter (no growth data)")
                    if _cfg_emit_would and (i + 1) < n:
                        would_have.append({
                            "SYMBOL": sym,
                            "MATURITY_DATE": index_iso[maturity_bar][:4] + "-" + index_iso[maturity_bar][4:6] + "-" + index_iso[maturity_bar][6:8],
                            "ZONE_CENTER": zc,
                            "WOULD_ENTER_DATE": index_iso[i + 1][:4] + "-" + index_iso[i + 1][4:6] + "-" + index_iso[i + 1][6:8],
                            "REJECT_REASON": "GROWTH",
                        })
                    _keep_pending()
                    _pg()
                    continue
                if close_arr[_eval_bar] < close_arr[_growth_ago]:
                    _count_block("growth_filter_fail")
                    _trace_gate(
                        f"block: growth_filter_fail ({close_arr[_eval_bar]:.4f}<{close_arr[_growth_ago]:.4f})"
                    )
                    if debug_entry and debug_date_prefix in _md_iso8:
                        print(
                            f"[DEBUG-ENTRY] {sym} bar {i}: zone ${zc:.2f} BLOCKED by growth_filter "
                            f"({close_arr[_eval_bar]:.2f} < {close_arr[_growth_ago]:.2f})"
                        )
                    if _cfg_emit_would and (i + 1) < n:
                        would_have.append({
                            "SYMBOL": sym,
                            "MATURITY_DATE": index_iso[maturity_bar][:4] + "-" + index_iso[maturity_bar][4:6] + "-" + index_iso[maturity_bar][6:8],
                            "ZONE_CENTER": zc,
                            "WOULD_ENTER_DATE": index_iso[i + 1][:4] + "-" + index_iso[i + 1][4:6] + "-" + index_iso[i + 1][6:8],
                            "REJECT_REASON": "GROWTH",
                        })
                    _keep_pending()
                    _pg()
                    continue

            if not _skip_brt_sheet_gates:
                # Tradeable Key Level (TKL): level must be tradeable on current or prior bar
                if cfg.tradeable_key_level_enabled and not _erg_only:
                    tkl_i = bool(tradeable_key_level_arr[_eval_bar])
                    tkl_prev = bool(tradeable_key_level_arr[_eval_bar - 1]) if _eval_bar > 0 else False
                    if not (tkl_i or tkl_prev):
                        _debug_gate_fail("block: tradeable_key_level")
                        _count_block("tradeable_key_level")
                        _trace_gate("block: tradeable_key_level")
                        if debug_entry and debug_date_prefix in _md_iso8:
                            tc_long_i = int(touch_count_long_arr[_eval_bar]) if _eval_bar < len(touch_count_long_arr) else 0
                            tc_short_i = float(touch_count_short_arr[_eval_bar]) if _eval_bar < len(touch_count_short_arr) else 0.0
                            tc_long_prev = int(touch_count_long_arr[_eval_bar - 1]) if _eval_bar - 1 >= 0 and _eval_bar - 1 < len(touch_count_long_arr) else 0
                            tc_short_prev = float(touch_count_short_arr[_eval_bar - 1]) if _eval_bar - 1 >= 0 and _eval_bar - 1 < len(touch_count_short_arr) else 0.0
                            print(
                                f"[DEBUG-ENTRY] {sym} bar {i}: zone ${zc:.2f} BLOCKED by tradeable_key_level "
                                f"(tkl_i={tkl_i}, tkl_prev={tkl_prev}); "
                                f"TC_LONG(i)={tc_long_i} TC_SHORT(i)={tc_short_i}; "
                                f"TC_LONG(prev)={tc_long_prev} TC_SHORT(prev)={tc_short_prev}; "
                                f"touch_threshold={cfg.touch_threshold}"
                            )
                        _keep_pending()
                        _pg()
                        continue
                if _perf:
                    _t_mid = time.perf_counter()
                use_bh_bi = True
                # DI / all-zones breakout is precomputed for BY/DW (retest) only — not a long entry gate; we buy on retest.
                st_on = _cfg_st_on
                _bp_z = _band_pct_at(i, float(zc)) if pd.notna(zc) else float(cfg.band_pct)
                zone_upper = float(zc) * (1.0 + _bp_z) if pd.notna(zc) else float("nan")
                if _gate_fns_sheet is not None:
                    _zone_ctx_at, _overlap_at, _same_zone_ctx, _ak_at, _, _aq_at = _gate_fns_sheet
                else:
                    _zone_ctx_at, _overlap_at, _same_zone_ctx, _ak_at, _, _aq_at = _brt_make_entry_gate_query_fns(
                        use_sheet_zone_ctx=False,
                        st_on=st_on,
                        cfg=cfg,
                        close_arr=close_arr,
                        low_arr=low_arr,
                        high_arr=high_arr,
                        de_ctx=None,
                        df_ctx=None,
                        dg_ctx=None,
                        ds_ctx=None,
                        zone_low_fb=float(zone_low),
                        zone_upper_fb=float(zone_upper),
                        maturity_bar_fb=int(maturity_bar),
                    )

                ak_today = _ak_at(i)
                ak_yesterday = _ak_at(i - 1) if i >= 1 else False
                # DO parity gate: recent pre-only strong pivot touch event.
                if _cfg_do_gate:
                    do_keep = _cfg_do_keep
                    do_start = max(0, i - do_keep + 1)
                    do_ok = bool(np.any(do_touch_arr[do_start : i + 1]))
                    if not do_ok:
                        _debug_gate_fail(f"block: DO gate (window={do_keep} bars)")
                        _count_block("do_pre_touch_gate")
                        _trace_gate(f"block: DO gate (window={do_keep} bars)")
                        _keep_pending()
                        _pg()
                        continue
                # DP parity gate: require price in any matured zone CE/CF in [row-C10 .. row-lag].
                if _cfg_dp_gate:
                    dp_keep = _cfg_dp_keep
                    dp_start = max(0, i - dp_keep + 1)
                    dp_ok = any(_dp_inside_any_zone(k) for k in range(dp_start, i + 1))
                    if not dp_ok:
                        _debug_gate_fail(f"block: DP gate (window={dp_keep} bars)")
                        _count_block("dp_inside_zone_gate")
                        _trace_gate(f"block: DP gate (window={dp_keep} bars)")
                        _keep_pending()
                        _pg()
                        continue
                # Legacy level-acceptance (7/10 closes above anchor): not part of compact sheet AL; off by default.
                if cfg.level_acceptance_required > 0:
                    anchor_mode = "strict"
                    if st_on:
                        anchor_mode = _cfg_anchor_mode
                        if anchor_mode == "rolling":
                            anchor_window = _cfg_anchor_win
                            anchor_start = max(maturity_bar + 1, i - anchor_window + 1)
                            au_anchor_ok = any(_ak_at(k) for k in range(anchor_start, i + 1))
                        else:
                            au_anchor_ok = (ak_today or ak_yesterday)
                    else:
                        au_anchor_ok = True
                    ok_i, zl_i, _zu_i, _dg_i, _sid_i = _zone_ctx_at(i)
                    ok_im1, zl_im1, _zu_im1, _dg_im1, _sid_im1 = _zone_ctx_at(i - 1) if i >= 1 else (False, float("nan"), float("nan"), -1, float("nan"))
                    dl_today = float("nan")
                    dl_prev = float("nan")
                    if st_on and anchor_mode == "rolling":
                        anchor_zone_low = zl_i if ak_today and ok_i else (zl_im1 if ak_yesterday and ok_im1 else (zl_i if ok_i else zone_low))
                    elif st_on:
                        dl_today = float(zl_i) if ok_i else float("nan")
                        dl_prev = float(zl_im1) if (i >= 1 and ok_im1) else float("nan")
                        anchor_zone_low = dl_today if ak_today else dl_prev
                    else:
                        anchor_zone_low = zl_i if ok_i else zone_low
                    if not au_anchor_ok:
                        _debug_gate_fail("block: level_acceptance anchor (no support-test / DI anchor)")
                        _count_block("level_acceptance_no_anchor")
                        _trace_gate("block: level_acceptance anchor (no support-test / DI anchor)")
                        if debug_entry and debug_date_prefix in _md_iso8:
                            print(f"[DEBUG-ENTRY] {sym} bar {i}: zone ${zc:.2f} BLOCKED by level_acceptance (anchor_mode={_cfg_anchor_mode})")
                        _keep_pending()
                        _pg()
                        continue
                    if not np.isfinite(anchor_zone_low):
                        _debug_gate_fail("block: level_acceptance anchor (no DL / gated lower)")
                        _count_block("level_acceptance_no_dl")
                        _trace_gate("block: level_acceptance anchor (no DL / gated lower)")
                        if debug_entry and debug_date_prefix in _md_iso8:
                            print(f"[DEBUG-ENTRY] {sym} bar {i}: zone ${zc:.2f} BLOCKED by level_acceptance (no DL anchor)")
                        _keep_pending()
                        _pg()
                        continue
                    _la_bar = _eval_bar if bool(getattr(cfg, "level_acceptance_window_use_eval_bar", False)) else i
                    if _la_bar < 0:
                        _la_bar = 0
                    start = max(0, _la_bar - cfg.level_acceptance_window + 1)
                    _la_px = high_arr if bool(getattr(cfg, "level_acceptance_use_high", False)) else close_arr
                    closes_above = int(np.sum(_la_px[start : _la_bar + 1] > anchor_zone_low))
                    if (
                        _DEBUG_SYMBOL is not None
                        and sym == _DEBUG_SYMBOL
                        and index_iso[i] == "20221201"
                    ):
                        print(
                            f"[DEBUG-BG-ONEBAR] {sym} eval=2022-12-01 maturity={maturity_date} "
                            f"ak_t={ak_today} ak_y={ak_yesterday} dl_t={dl_today:.4f} dl_prev={dl_prev:.4f} "
                            f"anchor={anchor_zone_low:.4f} closes_above={closes_above}/{cfg.level_acceptance_window}"
                        )
                    if closes_above < cfg.level_acceptance_required:
                        _debug_gate_fail(
                            f"block: level_acceptance ratio ({closes_above}/{cfg.level_acceptance_window}<{cfg.level_acceptance_required})"
                        )
                        _count_block("level_acceptance_ratio")
                        _trace_gate(
                            f"block: level_acceptance ratio ({closes_above}/{cfg.level_acceptance_window}<{cfg.level_acceptance_required})"
                        )
                        if debug_entry and debug_date_prefix in _md_iso8:
                            print(f"[DEBUG-ENTRY] {sym} bar {i}: zone ${zc:.2f} BLOCKED by level_acceptance ({closes_above}/{cfg.level_acceptance_window} < {cfg.level_acceptance_required})")
                        _keep_pending()
                        _pg()
                        continue
                if bool(getattr(cfg, "zone_eligible_long_gate_enabled", False)) and st_on:
                    _zeb = int(_eval_bar) if bool(getattr(cfg, "level_acceptance_window_use_eval_bar", False)) else int(i)
                    if _zeb < 1:
                        _zeb = 1
                    if _gate_fns_sheet is not None and _use_sheet_ctx:
                        z_ok = bool(_aq_at(_zeb))
                        if bool(getattr(cfg, "zone_eligible_long_or_prior_bar", False)):
                            z_ok = z_ok or bool(_aq_at(_zeb - 1))
                    else:
                        try:
                            zl_p = float(p["zone_low"])
                            zu_p = float(p.get("zone_high", float(zc) * (1.0 + _bp_z) if pd.notna(zc) else float("nan")))
                        except (TypeError, ValueError, KeyError):
                            zl_p = float("nan")
                            zu_p = float("nan")

                        def _zel_ok(at: int) -> bool:
                            if at < 1 or at < int(maturity_bar):
                                return False
                            if not (np.isfinite(zl_p) and np.isfinite(zu_p) and zu_p > zl_p):
                                return False
                            hp = float(high_arr[at - 1])
                            lo_a = float(low_arr[at])
                            hi_a = float(high_arr[at])
                            am_ok = bool((hp > zl_p) and (lo_a <= zu_p) and (hi_a >= zl_p))
                            an_ok = bool((hp < zu_p) and (lo_a <= zu_p) and (hi_a >= zl_p))
                            return bool(am_ok and an_ok)

                        z_ok = _zel_ok(_zeb)
                        if bool(getattr(cfg, "zone_eligible_long_or_prior_bar", False)):
                            z_ok = z_ok or _zel_ok(_zeb - 1)
                    if not z_ok:
                        _count_block("zone_eligible_long_fail")
                        _trace_gate("block: zone_eligible_long (AQ; OR prior bar)")
                        _keep_pending()
                        _pg()
                        continue
                # Tight Range Qualifier: block levels that mature in structurally compressed environments
                if cfg.tight_range_enabled:
                    L = int(cfg.tight_range_lookback)
                    end_mode = str(getattr(cfg, "tight_range_window_end", "maturity_bar") or "maturity_bar").strip().lower()
                    if end_mode == "eval_bar":

                        def _tight_range_range_pct_at_end(end_bar: int) -> tuple[bool, float]:
                            if end_bar < 0:
                                return (False, 0.0)
                            s0 = max(0, end_bar - L + 1)
                            if end_bar - s0 + 1 < L:
                                return (False, 0.0)
                            wh = float(np.max(high_arr[s0 : end_bar + 1]))
                            wl = float(np.min(low_arr[s0 : end_bar + 1]))
                            if wl <= 0:
                                return (True, float("nan"))
                            return (True, (wh / wl) - 1.0)

                        def _range_qual_passes(end_bar: int) -> bool:
                            ok_w, rp = _tight_range_range_pct_at_end(end_bar)
                            if not ok_w or rp != rp:
                                return False
                            return bool(rp > float(cfg.tight_range_threshold_pct))

                        eb_tr = int(_eval_bar)
                        or_pr = bool(getattr(cfg, "tight_range_or_prior_bar", False))
                        okw0, _rp0 = _tight_range_range_pct_at_end(eb_tr)
                        okw1, _rp1 = (
                            _tight_range_range_pct_at_end(eb_tr - 1) if (or_pr and eb_tr > 0) else (False, float("nan"))
                        )
                        can_compute = bool(okw0 or (or_pr and eb_tr > 0 and okw1))
                        if not can_compute:
                            _trace_gate("pass: tight_range skipped (insufficient history for eval_bar window)")
                        else:
                            ok_today = _range_qual_passes(eb_tr)
                            ok_prev = bool(or_pr and eb_tr > 0 and _range_qual_passes(eb_tr - 1))
                            if not (ok_today or ok_prev):
                                _count_block("tight_range_threshold")
                                _trace_gate("block: tight_range_threshold (eval_bar OR prior)")
                                if _cfg_emit_would and (i + 1) < n:
                                    would_have.append({
                                        "SYMBOL": sym,
                                        "MATURITY_DATE": index_iso[maturity_bar][:4] + "-" + index_iso[maturity_bar][4:6] + "-" + index_iso[maturity_bar][6:8],
                                        "ZONE_CENTER": zc,
                                        "WOULD_ENTER_DATE": index_iso[i + 1][:4] + "-" + index_iso[i + 1][4:6] + "-" + index_iso[i + 1][6:8],
                                        "REJECT_REASON": "TIGHT_RANGE",
                                    })
                                _keep_pending()
                                _pg()
                                continue
                    else:
                        start_idx = max(0, maturity_bar - cfg.tight_range_lookback + 1)
                        if maturity_bar - start_idx + 1 < cfg.tight_range_lookback:
                            _count_block("tight_range_not_enough_bars")
                            _trace_gate("block: tight_range_not_enough_bars")
                            if debug_entry and debug_date_prefix in _md_iso8:
                                print(f"[DEBUG-ENTRY] {sym} bar {i}: zone ${zc:.2f} BLOCKED by tight_range (not enough bars)")
                            if _cfg_emit_would and (i + 1) < n:
                                would_have.append({
                                    "SYMBOL": sym,
                                    "MATURITY_DATE": index_iso[maturity_bar][:4] + "-" + index_iso[maturity_bar][4:6] + "-" + index_iso[maturity_bar][6:8],
                                    "ZONE_CENTER": zc,
                                    "WOULD_ENTER_DATE": index_iso[i + 1][:4] + "-" + index_iso[i + 1][4:6] + "-" + index_iso[i + 1][6:8],
                                    "REJECT_REASON": "TIGHT_RANGE",
                                })
                            _keep_pending()
                            _pg()
                            continue
                        window_high = float(np.max(high_arr[start_idx : maturity_bar + 1]))
                        window_low = float(np.min(low_arr[start_idx : maturity_bar + 1]))
                        if window_low <= 0:
                            _count_block("tight_range_invalid_window_low")
                            _trace_gate("block: tight_range_invalid_window_low")
                            if _cfg_emit_would and (i + 1) < n:
                                would_have.append({
                                    "SYMBOL": sym,
                                    "MATURITY_DATE": index_iso[maturity_bar][:4] + "-" + index_iso[maturity_bar][4:6] + "-" + index_iso[maturity_bar][6:8],
                                    "ZONE_CENTER": zc,
                                    "WOULD_ENTER_DATE": index_iso[i + 1][:4] + "-" + index_iso[i + 1][4:6] + "-" + index_iso[i + 1][6:8],
                                    "REJECT_REASON": "TIGHT_RANGE",
                                })
                            _keep_pending()
                            _pg()
                            continue
                        range_pct = (window_high / window_low) - 1
                        if range_pct <= cfg.tight_range_threshold_pct:
                            _count_block("tight_range_threshold")
                            _trace_gate(f"block: tight_range_threshold ({range_pct:.4f}<={cfg.tight_range_threshold_pct:.4f})")
                            if debug_entry and debug_date_prefix in _md_iso8:
                                print(f"[DEBUG-ENTRY] {sym} bar {i}: zone ${zc:.2f} BLOCKED by tight_range ({range_pct:.1%} <= {cfg.tight_range_threshold_pct:.1%})")
                            if _cfg_emit_would and (i + 1) < n:
                                would_have.append({
                                    "SYMBOL": sym,
                                    "MATURITY_DATE": index_iso[maturity_bar][:4] + "-" + index_iso[maturity_bar][4:6] + "-" + index_iso[maturity_bar][6:8],
                                    "ZONE_CENTER": zc,
                                    "WOULD_ENTER_DATE": index_iso[i + 1][:4] + "-" + index_iso[i + 1][4:6] + "-" + index_iso[i + 1][6:8],
                                    "REJECT_REASON": "TIGHT_RANGE",
                                })
                            _keep_pending()
                            _pg()
                            continue
                # Rolling Average Displacement filter (optional entry gate)
                if cfg.displacement_filter_enabled:
                    if maturity_bar < rb - 1:
                        _count_block("displacement_not_enough_bars")
                        _keep_pending()
                        _pg()
                        continue
                    close_at_maturity = close_arr[maturity_bar]
                    roll_slice = close_arr[maturity_bar - rb + 1 : maturity_bar + 1]
                    rolling_avg = float(np.mean(roll_slice))
                    if rolling_avg <= 0:
                        _count_block("displacement_invalid_rolling_avg")
                        _keep_pending()
                        _pg()
                        continue
                    displacement_pct = abs(close_at_maturity / rolling_avg - 1.0)
                    if displacement_pct < cfg.displacement_threshold_pct:
                        _count_block("displacement_below_threshold")
                        _keep_pending()
                        _pg()
                        continue
                # Consolidation Blocker: block Rocket Buy when active on this bar
                if _cfg_consol_block and cb_active and not _erg_only:
                    _count_block("consolidation_blocker")
                    _trace_gate("block: consolidation_blocker")
                    if debug_entry and debug_date_prefix in _md_iso8:
                        print(f"[DEBUG-ENTRY] {sym} bar {i}: zone ${zc:.2f} BLOCKED by consolidation_blocker")
                    if _cfg_emit_would and (i + 1) < n:
                        would_have.append({
                            "SYMBOL": sym,
                            "MATURITY_DATE": index_iso[maturity_bar][:4] + "-" + index_iso[maturity_bar][4:6] + "-" + index_iso[maturity_bar][6:8],
                            "ZONE_CENTER": zc,
                            "WOULD_ENTER_DATE": index_iso[i + 1][:4] + "-" + index_iso[i + 1][4:6] + "-" + index_iso[i + 1][6:8],
                            "REJECT_REASON": "CONSOLIDATION",
                        })
                    _keep_pending()
                    _pg()
                    continue
                # Simulated BY retest date: COUNTIF(BY:$BY, date on eval row) > 0 (BH:BI pipeline); see sheet_column_reference.
                # Eval row = _eval_bar (same session as close>open / ladder gates), not a wide window before it.
                if use_bh_bi and _cfg_dw_countif:
                    if _eval_bar < 0 or _eval_bar >= len(index_iso):
                        _rt = ENTRY_GATE_SHEET_TITLES["retest_date"]
                        _debug_gate_fail(f"block: {_rt} - invalid eval bar index {_eval_bar}")
                        _count_block("sheet_dw_countif")
                        _trace_gate(f"block: {_rt} - invalid eval bar index {_eval_bar}")
                        _keep_pending()
                        _pg()
                        continue
                    _sig_iso = index_iso[_eval_bar]
                    _by_ok = _sig_iso in dw_dates_set
                    if not _by_ok:
                        _rt = ENTRY_GATE_SHEET_TITLES["retest_date"]
                        _extra = (
                            " (set includes next session after each retest when sheet_dw_countif_include_prior_bar_date is on)"
                            if _cfg_dw_countif_prior
                            else ""
                        )
                        _debug_gate_fail(
                            f"block: {_rt} - eval date {_sig_iso} not in simulated BY retest set (strict COUNTIF){_extra}"
                        )
                        _count_block("sheet_dw_countif")
                        _trace_gate(f"block: {_rt} - eval {_sig_iso} not in BY retest set{_extra}")
                        _keep_pending()
                        _pg()
                        continue
            else:
                use_bh_bi = False
                _trace_gate("pass: indicator_buy=only (sheet gates skipped)")
                _ind_gate_trace("sheet gates bypassed; growth_filter still applies when enabled")

            if debug_entry and debug_date_prefix in _md_iso8:
                print(f"[DEBUG-ENTRY] {sym} bar {i} ({index_iso[i][:10]}): zone ${zc:.2f} PASSED all filters, checking entry...")
            _trace_gate("pass: all gates, proceeding to entry checks")

            _pg()
            _t_e = time.perf_counter() if _perf else 0.0

            def _pe() -> None:
                if _perf:
                    _acc_bt("bt_pending_entry", time.perf_counter() - _t_e)

            # Entry at next bar open. Stop/target: percent-based (stop_pct/target_pct) or ATR-based when atr_* > 0
            entry_price = next_op
            # Signal-bar extremum for final entry gate; percent stops/targets use entry_price.
            trigger_bar_low = low_arr[_eval_bar]
            trigger_bar_high = high_arr[_eval_bar]
            prior_close = float(close_arr[_eval_bar - 1]) if _eval_bar >= 1 else float("nan")
            too_high_mult = float(getattr(cfg, "too_high_multiplier", 0.0) or 0.0)
            too_low_mult = float(getattr(cfg, "too_low_multiplier", 0.0) or 0.0)
            _too_far = False
            _too_far_msg = ""
            _too_far_reason = ""
            if too_high_mult > 0:
                if _is_long_side and trigger_bar_low > 0 and entry_price > (trigger_bar_low * too_high_mult):
                    _too_far = True
                    _too_far_reason = "too_high_final_gate"
                    _too_far_msg = (
                        f"(open={entry_price:.4f} > trigger_low={trigger_bar_low:.4f} * too_high={too_high_mult:.4f})"
                    )
                elif (not _is_long_side) and trigger_bar_high > 0 and entry_price < (trigger_bar_high / too_high_mult):
                    _too_far = True
                    _too_far_reason = "too_high_final_gate"
                    _too_far_msg = (
                        f"(open={entry_price:.4f} < trigger_high={trigger_bar_high:.4f} / too_high={too_high_mult:.4f})"
                    )
            if not _too_far and too_low_mult > 0 and _eval_bar >= 1 and np.isfinite(prior_close) and prior_close > 0:
                if _is_long_side and entry_price < (prior_close * too_low_mult):
                    _too_far = True
                    _too_far_reason = "too_low_final_gate"
                    _too_far_msg = (
                        f"(open={entry_price:.4f} < prior_close={prior_close:.4f} * too_low={too_low_mult:.4f})"
                    )
                elif (not _is_long_side) and entry_price > (prior_close / too_low_mult):
                    _too_far = True
                    _too_far_reason = "too_low_final_gate"
                    _too_far_msg = (
                        f"(open={entry_price:.4f} > prior_close={prior_close:.4f} / too_low={too_low_mult:.4f})"
                    )
            if _too_far:
                _count_block(_too_far_reason or "too_high_final_gate")
                _trace_gate(f"block: {_too_far_reason} {_too_far_msg}")
                if debug_entry and debug_date_prefix in _md_iso8:
                    print(
                        f"[DEBUG-ENTRY] {sym} bar {i}: zone ${zc:.2f} BLOCKED by {_too_far_reason} {_too_far_msg}"
                    )
                if _cfg_emit_would and (i + 1) < n:
                    would_have.append({
                        "SYMBOL": sym,
                        "MATURITY_DATE": index_iso[maturity_bar][:4] + "-" + index_iso[maturity_bar][4:6] + "-" + index_iso[maturity_bar][6:8],
                        "ZONE_CENTER": zc,
                        "WOULD_ENTER_DATE": index_iso[i + 1][:4] + "-" + index_iso[i + 1][4:6] + "-" + index_iso[i + 1][6:8],
                        "REJECT_REASON": "TOO_HIGH" if _too_far_reason == "too_high_final_gate" else "TOO_LOW",
                    })
                _keep_pending()
                _pg()
                continue
            # Entry is always bar _i_bar+1 (same as outer next_op); ATR at entry uses that bar index.
            atr_14_at_entry_val = float(atr_14_arr[_i_bar + 1]) if (_i_bar + 1 < n and not (atr_14_arr[_i_bar + 1] != atr_14_arr[_i_bar + 1])) else None
            atr_pct = None
            if atr_14_at_entry_val is not None and entry_price > 0:
                atr_pct = (atr_14_at_entry_val / entry_price) * 100.0

            target_price = _brt_target_price(
                cfg,
                entry_price=entry_price,
                entry_bar=_i_bar + 1,
                is_long_side=_is_long_side,
                atr_pct=atr_pct,
                sma50_arr=sma50_arr,
                cfg_atr_target=_cfg_atr_target,
                cfg_short_target_pct=_cfg_short_target_pct,
            )

            # Stop price
            _sheet_low_stop = (
                _cfg_stop_anchor == "signal_low"
                and _is_long_side
                and _cfg_stop_pct > 0
                and 0 <= _eval_bar < n
            )
            if _sheet_low_stop:
                # Sheet AM: Stop = signal-bar Low * (1-C4) = Low[signal] * stop_pct (multiplier).
                _sig_low = float(low_arr[_eval_bar])
                stop_price = (
                    _sig_low * _cfg_stop_pct
                    if cfg.stop_pct_is_multiplier
                    else _sig_low * (1 - _cfg_stop_pct)
                )
            elif _cfg_atr_stop > 0 and atr_pct is not None:
                stop_price = (
                    entry_price * (1.0 - atr_pct * cfg.atr_stop / 100.0)
                    if _is_long_side
                    else entry_price * (1.0 + atr_pct * cfg.atr_stop / 100.0)
                )
            elif (_cfg_stop_pct > 0 and _is_long_side) or (_cfg_short_stop_pct > 0 and (not _is_long_side)):
                _sp = _cfg_stop_pct if _is_long_side else _cfg_short_stop_pct
                if _is_long_side:
                    stop_price = (
                        entry_price * _sp
                        if cfg.stop_pct_is_multiplier
                        else entry_price * (1 - _sp)
                    )
                else:
                    stop_price = (
                        entry_price * ((2.0 - _sp) if _sp >= 1.0 else (1.0 + (1.0 - _sp)))
                        if cfg.stop_pct_is_multiplier
                        else entry_price * (1 + _sp)
                    )
            else:
                # stop_pct==0 and atr_stop==0 would yield stop_price=0: gap_down/stop_hit never fire (only target exits).
                # Default matches BRTConfig.stop_pct / fraction-below convention when sheet uses ATR target only.
                _def_mult = 0.934
                _def_frac_below = 0.066
                if _is_long_side:
                    stop_price = (
                        entry_price * _def_mult
                        if cfg.stop_pct_is_multiplier
                        else entry_price * (1 - _def_frac_below)
                    )
                else:
                    stop_price = (
                        entry_price * (2.0 - _def_mult)
                        if cfg.stop_pct_is_multiplier
                        else entry_price * (1 + _def_frac_below)
                    )
            _ca_iso = index_iso[_eval_bar]
            close_above_date = f"{_ca_iso[:4]}-{_ca_iso[4:6]}-{_ca_iso[6:8]}" if len(_ca_iso) >= 8 else _ca_iso

            rejection_count_prior = _count_rejection_episodes_prior(
                close_arr, low_arr, high_arr, float(zl), float(zh), int(maturity_bar), _rd_zone,
            )
            overlapping_mature_zones = _count_overlapping_mature_zones(
                zl_full_arr, zh_full_arr, matured_now_arr, float(zl), float(zh), int(maturity_bar), _rd_zone,
            )
            _bb_o = p.get("breakout_bar", None)
            if _bb_o is None:
                _bb_o = _lookup_breakout_bar_for_zone(_brt_br_rows, float(zl), float(zh), int(maturity_bar), _rd_zone)
            breakout_date = ""
            days_since_breakout: Optional[int] = None
            rel_vol_breakout: Optional[float] = None
            if volume_arr is not None and _bb_o is not None:
                try:
                    _bbi = int(_bb_o)
                    if 0 <= _bbi < len(index_iso):
                        breakout_date = str(index_iso[_bbi])[:8]
                        if len(_ca_iso) >= 8 and len(breakout_date) >= 8:
                            _rt_ts = pd.Timestamp(f"{_ca_iso[:4]}-{_ca_iso[4:6]}-{_ca_iso[6:8]}")
                            _br_ts = pd.Timestamp(
                                f"{breakout_date[:4]}-{breakout_date[4:6]}-{breakout_date[6:8]}"
                            )
                            days_since_breakout = int((_rt_ts - _br_ts).days)
                    rel_vol_breakout = _rel_vol_at_bar(volume_arr, _bbi)
                except (TypeError, ValueError):
                    rel_vol_breakout = None

            # Pivot sequence in zone: strong setup = 2–3 H then 1–2 L before entry
            _t_ps = time.perf_counter() if _perf else 0.0
            _, pivot_high_run, pivot_low_run, pivot_switch = _pivot_sequence_in_zone(
                maturity_bar, zl, zh, ph_arr, pl_arr
            )
            if _perf:
                _acc_bt("bt_pending_pivot_sequence", time.perf_counter() - _t_ps)

            if getattr(cfg, "min_pivot_run_l_before_entry", 0) > 0 and pivot_low_run < cfg.min_pivot_run_l_before_entry:
                _count_block("min_pivot_run_low")
                _keep_pending()
                _pg()
                continue
            if getattr(cfg, "min_pivot_run_h_before_entry", 0) > 0 and pivot_high_run < cfg.min_pivot_run_h_before_entry:
                _count_block("min_pivot_run_high")
                _keep_pending()
                _pg()
                continue
            if getattr(cfg, "pivot_switch_h_to_l_filter", -1) >= 0:
                want_true_ps = int(cfg.pivot_switch_h_to_l_filter) == 1
                if pivot_switch != want_true_ps:
                    _count_block("pivot_switch_filter")
                    _keep_pending()
                    _pg()
                    continue
            if getattr(cfg, "min_hist_ann_ror_avg", -100.0) > -100.0:
                _hn_hist, _, hist_ann_ror_gate = _hist_stats_for_symbol(
                    closed, sym, float(getattr(cfg, "days_per_year", 365.0) or 365.0)
                )
                # No prior closed trades for this symbol: avg ann ROR is undefined; do not block.
                if _hn_hist > 0 and hist_ann_ror_gate < cfg.min_hist_ann_ror_avg:
                    _count_block("min_hist_ann_ror_avg")
                    _keep_pending()
                    _pg()
                    continue

            _t_ent_bld = time.perf_counter() if _perf else 0.0
            # --- Enriched context for trade ---
            # Pivot type at maturity bar: PH, PL, or PH+PL
            pivot_type = ""
            ph_val = ph_arr[maturity_bar] if maturity_bar < len(ph_arr) else 0.0
            pl_val = pl_arr[maturity_bar] if maturity_bar < len(pl_arr) else 0.0
            has_ph = ph_val > 0
            has_pl = pl_val > 0
            if has_ph and has_pl:
                pivot_type = "PH+PL"
            elif has_ph:
                pivot_type = "PH"
            elif has_pl:
                pivot_type = "PL"

            # Structural regime: prefer low-side (HL/LL) when available, else high-side (HH/LH)
            struct_regime = sl or sh or ""

            # Major pivot flag (high or low)
            entry_major_pivot = 0
            if mp_h_arr is not None and maturity_bar < len(mp_h_arr) and mp_h_arr[maturity_bar] == 1:
                entry_major_pivot = 1
            if mp_l_arr is not None and maturity_bar < len(mp_l_arr) and mp_l_arr[maturity_bar] == 1:
                entry_major_pivot = 1

            # Strong-pivot label for the triggering pivot (research; aligned with compute_touch_stream)
            entry_pivot_was_strong = 0
            if (
                _cfg_strong_on
                and not _cfg_rt_filter
                and _strong_pivot_mode_has_active_params(
                    _cfg_sp_mode,
                    _cfg_sp_pre_b,
                    _cfg_sp_pre_pct,
                    _cfg_sp_post_b,
                    _cfg_sp_post_pct,
                    pre_pct_atr=_cfg_pre_pct_atr,
                    post_pct_atr=_cfg_post_pct_atr,
                )
            ):
                mb = maturity_bar
                if mb < n and ph_arr[mb] > 0.0:
                    _pp_e = float(ph_arr[mb])
                    _pre_e = _effective_strong_pivot_pct(_pp_e, mb, atr_14_arr, _cfg_sp_pre_pct, _cfg_pre_pct_atr)
                    _post_e = _effective_strong_pivot_pct(_pp_e, mb, atr_14_arr, _cfg_sp_post_pct, _cfg_post_pct_atr)
                    if _strong_pivot_bar_ok(
                        mb, "PH", strong_hi_arr, strong_lo_arr, n,
                        pre_bars=_cfg_sp_pre_b,
                        pre_pct=_pre_e,
                        post_bars=_cfg_sp_post_b,
                        post_pct=_post_e,
                        mode=_cfg_sp_mode,
                    ):
                        entry_pivot_was_strong = 1
                elif mb < n and pl_arr[mb] > 0.0:
                    _pp_el = float(pl_arr[mb])
                    _pre_el = _effective_strong_pivot_pct(_pp_el, mb, atr_14_arr, _cfg_sp_pre_pct, _cfg_pre_pct_atr)
                    _post_el = _effective_strong_pivot_pct(_pp_el, mb, atr_14_arr, _cfg_sp_post_pct, _cfg_post_pct_atr)
                    if _strong_pivot_bar_ok(
                        mb, "PL", strong_hi_arr, strong_lo_arr, n,
                        pre_bars=_cfg_sp_pre_b,
                        pre_pct=_pre_el,
                        post_bars=_cfg_sp_post_b,
                        post_pct=_post_el,
                        mode=_cfg_sp_mode,
                    ):
                        entry_pivot_was_strong = 1

            # Short-window touch count and TKL flag at maturity bar
            tcs = int(touch_count_short_arr[maturity_bar]) if maturity_bar < len(touch_count_short_arr) else 0
            is_ac = bool(tradeable_key_level_arr[maturity_bar])

            # Nearby zone cluster: count unique zone_center levels above/below within ±_ZONE_CLUSTER_PCT
            nearby_above = 0
            nearby_below = 0
            if pd.notna(zc):
                try:
                    start_idx = max(0, maturity_bar - cfg.lookback_long + 1)
                    window = zone_center_arr[start_idx : maturity_bar + 1]
                    matured_near = matured_now_arr[start_idx : maturity_bar + 1]
                    valid = ~np.isnan(window) & (window > 0) & matured_near
                    window = window[valid]
                    if len(window) > 0:
                        upper = zc * (1 + _ZONE_CLUSTER_PCT)
                        lower = zc * (1 - _ZONE_CLUSTER_PCT)
                        above_vals = np.unique(window[(window > zc) & (window <= upper)])
                        below_vals = np.unique(window[(window < zc) & (window >= lower)])
                        nearby_above = len(above_vals)
                        nearby_below = len(below_vals)
                except Exception:
                    nearby_above = 0
                    nearby_below = 0
            cluster_density = nearby_above + nearby_below

            # Zone above = next key level above current zone with no overlap.
            # Zone below = next key level below trigger band.
            # Only consider zones that have MATURED_NOW == 1 (complete key level), not partial touch-only levels.
            zc_f = float(zc)
            _bp_ent = _band_pct_at(int(maturity_bar), zc_f) if pd.notna(zc) and zc_f > 0 else float(cfg.band_pct)
            trigger_bottom = zc_f * (1 - _bp_ent)
            current_zone_top = zc_f * (1 + _bp_ent)
            zone_above_center = 0.0
            zone_below_center = 0.0
            pct_entry_to_bottom_zone_above = 0.0
            pct_drop_to_top_zone_below = 0.0
            if pd.notna(zc) and zc_f > 0:
                try:
                    start_idx = max(0, maturity_bar - cfg.lookback_long + 1)
                    window = zone_center_arr[start_idx : maturity_bar + 1]
                    matured_slice = matured_now_arr[start_idx : maturity_bar + 1]
                    valid = ~np.isnan(window) & (window > 0) & matured_slice
                    window = window[valid]
                    min_zone_above_center = current_zone_top / (1 - _bp_ent)
                    above_vals = window[window >= min_zone_above_center]
                    below_vals = window[window < trigger_bottom]
                    if len(above_vals) > 0:
                        zone_above_center = float(np.min(above_vals))
                        bottom_above = zone_above_center * (1 - _bp_ent)
                        pct_entry_to_bottom_zone_above = (bottom_above - entry_price) / entry_price * 100.0
                    if len(below_vals) > 0:
                        zone_below_center = float(np.max(below_vals))
                        top_below = zone_below_center * (1 + _bp_ent)
                        pct_drop_to_top_zone_below = (entry_price - top_below) / entry_price * 100.0
                    if zone_entries_debug is not None:
                        entry_date_iso = next_iso[:4] + "-" + next_iso[4:6] + "-" + next_iso[6:8] if len(next_iso) >= 8 else next_iso
                        _mb_iso = index_iso[_md_bar] if 0 <= int(_md_bar) < len(index_iso) else ""
                        maturity_date_iso = (
                            _mb_iso[:4] + "-" + _mb_iso[4:6] + "-" + _mb_iso[6:8]
                            if len(_mb_iso) >= 8
                            else ""
                        )
                        all_zones_str = ",".join(f"{x:.4f}" for x in np.unique(window))
                        bottom_above_val = zone_above_center * (1 - _bp_ent) if zone_above_center else 0.0
                        zone_entries_debug.append({
                            "ENTRY_DATE": entry_date_iso,
                            "MATURITY_DATE": maturity_date_iso,
                            "ENTRY_PRICE": round(entry_price, 4),
                            "ZONE_CENTER": round(zc_f, 4),
                            "ZONE_LOW": round(zc_f * (1 - _bp_ent), 4),
                            "ZONE_HIGH": round(zc_f * (1 + _bp_ent), 4),
                            "CURRENT_ZONE_TOP": round(current_zone_top, 4),
                            "TRIGGER_BOTTOM": round(trigger_bottom, 4),
                            "MIN_ZONE_ABOVE_CENTER": round(min_zone_above_center, 4),
                            "ZONE_ABOVE_CENTER_CHOSEN": round(zone_above_center, 4) if zone_above_center else "",
                            "BOTTOM_ZONE_ABOVE": round(bottom_above_val, 4) if zone_above_center else "",
                            "PCT_ENTRY_TO_BOTTOM_ZONE_ABOVE": round(pct_entry_to_bottom_zone_above, 2),
                            "ALL_ZONE_CENTERS_IN_WINDOW": all_zones_str,
                        })
                except Exception:
                    pass

            # Relative volume on signal bar (bullish eval day)
            rel_vol_trigger: Optional[float] = None
            if volume_arr is not None and _eval_bar < n:
                v_tr = volume_arr[_eval_bar]
                if not (v_tr != v_tr):  # not NaN
                    start_10 = max(0, _eval_bar - 9)
                    slice_10 = volume_arr[start_10 : _eval_bar + 1]
                    if len(slice_10) > 0:
                        avg_tr = float(np.nanmean(slice_10))
                        if avg_tr and avg_tr > 0:
                            rel_vol_trigger = float(v_tr) / avg_tr

            # Volume at entry (bar i+1) and 10d avg ending at entry
            vol_entry: Optional[float] = None
            avg_10d: Optional[float] = None
            rel_vol: Optional[float] = None
            if volume_arr is not None and _i_bar + 1 < n:
                v1 = volume_arr[_i_bar + 1]
                if not (v1 != v1):  # not NaN
                    vol_entry = float(v1)
                if vol_entry is not None:
                    start_10 = max(0, _i_bar + 1 - 9)
                    slice_10 = volume_arr[start_10 : _i_bar + 2]
                    valid = slice_10 == slice_10  # not NaN
                    if np.any(valid):
                        avg_10d = float(np.nanmean(slice_10))
                        if avg_10d and avg_10d > 0:
                            rel_vol = vol_entry / avg_10d

            if getattr(cfg, "min_rel_vol_at_entry", -2.0) > -2.0:
                if rel_vol is None or rel_vol < cfg.min_rel_vol_at_entry:
                    _count_block("min_rel_vol_at_entry")
                    _keep_pending()
                    _pg()
                    continue
            if float(getattr(cfg, "min_avg_volume_10d_at_entry", 0.0) or 0.0) > 0.0:
                if avg_10d is None or not np.isfinite(float(avg_10d)) or float(avg_10d) < float(cfg.min_avg_volume_10d_at_entry):
                    _count_block("min_avg_volume_10d_at_entry")
                    _keep_pending()
                    _pg()
                    continue

            # --- Per-trigger-bar technical metrics for correlation analysis (no future bars) ---
            # Eval bar (bullish signal day) for trigger metrics in this fork
            z_score_trigger: float = 0.0
            upper_wick_atr_trigger: float = 0.0
            lower_wick_atr_trigger: float = 0.0
            is_20bar_high_trigger: int = 0
            is_20bar_low_trigger: int = 0
            move_body_atr_trigger: float = 0.0
            atr_14_at_trigger_val: Optional[float] = None
            atr_pct_at_trigger_val: Optional[float] = None
            high_52w_at_trigger_val: Optional[float] = None
            dist_to_52w_high_pct_at_trigger_val: Optional[float] = None
            try:
                _sig_bar = _eval_bar
                if 0 <= _sig_bar < n:
                    cl_i = close_arr[_sig_bar]
                    op_i = open_arr[_sig_bar]
                    hi_i = high_arr[_sig_bar]
                    lo_i = low_arr[_sig_bar]
                    # Z-score vs recent closes
                    lookback_z = 20
                    start_z = max(0, _sig_bar - lookback_z + 1)
                    closes_slice = close_arr[start_z : _sig_bar + 1]
                    if closes_slice.size > 1:
                        mean_close = float(np.nanmean(closes_slice))
                        std_close = float(np.nanstd(closes_slice))
                        if std_close > 0:
                            z_score_trigger = float((cl_i - mean_close) / std_close)
                    # Wick sizes vs ATR at trigger bar
                    atr_tr = float(atr_14_arr[_sig_bar]) if not (atr_14_arr[_sig_bar] != atr_14_arr[_sig_bar]) else 0.0  # NaN check
                    upper_wick = max(0.0, hi_i - max(op_i, cl_i))
                    lower_wick = max(0.0, min(op_i, cl_i) - lo_i)
                    if atr_tr > 0:
                        upper_wick_atr_trigger = upper_wick / atr_tr
                        lower_wick_atr_trigger = lower_wick / atr_tr
                    # 20-bar range position
                    start_rng = max(0, _sig_bar - 19)
                    hi_slice = high_arr[start_rng : _sig_bar + 1]
                    lo_slice = low_arr[start_rng : _sig_bar + 1]
                    if hi_slice.size > 0 and lo_slice.size > 0:
                        if hi_i >= float(np.nanmax(hi_slice)):
                            is_20bar_high_trigger = 1
                        if lo_i <= float(np.nanmin(lo_slice)):
                            is_20bar_low_trigger = 1
                    # ATR-scaled move vs previous close
                    if _sig_bar > 0 and atr_tr > 0:
                        prev_close = close_arr[_sig_bar - 1]
                        move_body_atr_trigger = abs(cl_i - prev_close) / atr_tr
                    atr_14_at_trigger_val, atr_pct_at_trigger_val = _atr_14_and_pct_at_bar(
                        atr_14_arr, close_arr, _sig_bar
                    )
                    high_52w_at_trigger_val, dist_to_52w_high_pct_at_trigger_val = _high_52w_and_dist_pct(
                        high_arr, _sig_bar, float(cl_i)
                    )
            except Exception:
                # Metrics are best-effort; failures should not block trades
                pass

            # Beta at entry when compute_beta or weight_beta_at_entry requests it.
            if _need_beta and benchmark_df is not None:
                if profile_beta_times is not None:
                    _t0 = time.time()
                eb = _i_bar + 1
                if beta_by_bar_arr is not None and eb < len(beta_by_bar_arr):
                    bv = beta_by_bar_arr[eb]
                    beta_at_entry_val = float(bv) if (bv == bv and np.isfinite(bv)) else None
                else:
                    beta_at_entry_val = _rolling_beta_at_entry(df, eb, benchmark_df, _BETA_ROLLING_WINDOW)
                if profile_beta_times is not None:
                    profile_beta_times.append(time.time() - _t0)
            else:
                beta_at_entry_val = None

            if _i_bar + 1 == n - 1:
                _th_lim = _entry_open_band_fields(
                    trigger_bar_low,
                    trigger_bar_high,
                    prior_close,
                    too_high_mult,
                    too_low_mult,
                    _is_long_side,
                )
                _sc_anchor = float(cl)
                _sc_stop, _sc_target = _brt_stop_target_prices(
                    cfg,
                    anchor_price=_sc_anchor,
                    entry_bar=_i_bar + 1,
                    is_long_side=_is_long_side,
                    atr_14_arr=atr_14_arr,
                    sma50_arr=sma50_arr,
                )
                scanner.append({
                    "symbol": sym,
                    "date": next_iso,
                    "close": _sc_anchor,
                    "stop": _sc_stop,
                    "target": _sc_target,
                    "zone_center": zc,
                    "atr_pct_at_entry": atr_pct,
                    "atr_pct_at_trigger": atr_pct_at_trigger_val,
                    **_th_lim,
                    "maturity_date": maturity_date,
                    "close_above_date": close_above_date,
                    "entry_indicators": (
                        _snapshot_entry_indicators_for_trade(
                            _sym_indicator_pre,
                            int(_eval_bar),
                            "LONG" if _is_long_side else "SHORT",
                        )
                        if _need_indicator_pre and _sym_indicator_pre is not None
                        else {}
                    ),
                })
            else:
                max_high_since_entry = entry_price
                _zt_metrics = _zone_touch_metrics_at_signal(
                    int(_eval_bar),
                    int(_md_bar),
                    touch_count_long_arr=touch_count_long_arr,
                    touch_count_short_arr=touch_count_short_arr,
                    mts_ar_arr=mts_ar_arr,
                    mts_ak_arr=mts_ak_arr,
                    mts_am_cnt_arr=mts_am_cnt_arr,
                    ds_ctx_arr=ds_ctx_arr,
                    index_iso=index_iso,
                )
                sheet_rung = int(_zt_metrics.get("zone_episode_dn", 0) or 0)
                _entry_bar = _i_bar + 1
                _trigger_bar = int(_eval_bar)
                _spy_c1: Optional[float] = None
                _spy_c2: Optional[float] = None
                _spy_c3: Optional[float] = None
                _rs_sig = _trigger_bar
                if _rs_st is not None and _rs_sp is not None and _rs_sig >= 0:
                    _spy_c1, _spy_c2, _spy_c3 = _rs_excess_pct_points(_rs_st, _rs_sp, _rs_sig)
                _last_ath_bar, _td_since_ath = _running_ath_last_bar_index(high_arr, _entry_bar)
                _last_ath_date = (
                    index_iso[_last_ath_bar][:8]
                    if 0 <= _last_ath_bar < len(index_iso)
                    else ""
                )
                _hi52, _dist52 = _high_52w_and_dist_pct(high_arr, _entry_bar, entry_price)
                _new_trade = BRTTrade(
                    symbol=sym,
                    side=("LONG" if _is_long_side else "SHORT"),
                    date_opened=next_iso,
                    entry_price=entry_price,
                    stop_price=stop_price,
                    target_price=target_price,
                    zone_center=zc,
                    zone_low=float(zl) if np.isfinite(zl) else 0.0,
                    zone_high=float(zh) if np.isfinite(zh) else 0.0,
                    pbr_zone_id=str(p.get("pbr_zone_id", "") or ""),
                    touch_count=tc,
                    touch_count_major=tc_major,
                    touch_count_minor=tc_minor,
                    zone_rolling_touches=int(_zt_metrics.get("zone_rolling_touches", 0) or 0),
                    support_test_count=int(_zt_metrics.get("support_test_count", 0) or 0),
                    support_test_at_signal=int(_zt_metrics.get("support_test_at_signal", 0) or 0),
                    touch_count_at_maturity=int(_zt_metrics.get("touch_count_at_maturity", 0) or 0),
                    touch_count_short_at_maturity=int(_zt_metrics.get("touch_count_short_at_maturity", 0) or 0),
                    zone_episode_dn=int(_zt_metrics.get("zone_episode_dn", 0) or 0),
                    days_since_maturity=int(_zt_metrics.get("days_since_maturity", 0) or 0),
                    touch_count_short=tcs,
                    is_tradeable_key_level=is_ac,
                    struct_high=sh,
                    struct_low=sl,
                    entry_pivot_type=pivot_type,
                    entry_struct_regime=struct_regime,
                    entry_major_pivot=entry_major_pivot,
                    entry_pivot_was_strong=entry_pivot_was_strong,
                    entry_zone_was_strong_pivot=1 if _cfg_strong_on else 0,
                    nearby_zones_above=nearby_above,
                    nearby_zones_below=nearby_below,
                    zone_cluster_density=cluster_density,
                    maturity_date=maturity_date,
                    close_above_date=close_above_date,
                    breakout_date=breakout_date,
                    days_since_breakout=days_since_breakout,
                    growth_pct_over_period=growth_pct,
                    displacement_pct_at_entry=displacement_pct,
                    pivot_run_high=pivot_high_run,
                    pivot_run_low=pivot_low_run,
                    pivot_switch_h_to_l=pivot_switch,
                    zone_above_center=zone_above_center,
                    zone_below_center=zone_below_center,
                    pct_entry_to_bottom_zone_above=pct_entry_to_bottom_zone_above,
                    pct_drop_to_top_zone_below=pct_drop_to_top_zone_below,
                    volume_at_entry=vol_entry,
                    avg_volume_10d_at_entry=avg_10d,
                    rel_vol_at_entry=rel_vol,
                    rel_vol_on_trigger=rel_vol_trigger,
                    rejection_count_prior=rejection_count_prior,
                    overlapping_mature_zones_count=overlapping_mature_zones,
                    rel_vol_at_breakout=rel_vol_breakout,
                    atr_14_at_entry=float(atr_14_arr[_i_bar + 1]) if (_i_bar + 1 < n and not (atr_14_arr[_i_bar + 1] != atr_14_arr[_i_bar + 1])) else None,
                    entry_bar_index=int(_i_bar + 1),
                    atr_pct_at_entry=float(atr_pct) if atr_pct is not None and np.isfinite(float(atr_pct)) else None,
                    z_score_at_trigger=z_score_trigger,
                    upper_wick_atr_at_trigger=upper_wick_atr_trigger,
                    lower_wick_atr_at_trigger=lower_wick_atr_trigger,
                    is_20bar_high_at_trigger=is_20bar_high_trigger,
                    is_20bar_low_at_trigger=is_20bar_low_trigger,
                    move_body_atr_at_trigger=move_body_atr_trigger,
                    atr_14_at_trigger=atr_14_at_trigger_val,
                    atr_pct_at_trigger=atr_pct_at_trigger_val,
                    beta_at_entry=beta_at_entry_val,
                    sheet_ladder_rung_at_signal=sheet_rung,
                    last_ath_date_at_entry=_last_ath_date,
                    trading_days_since_last_ath_at_entry=_td_since_ath,
                    high_52w_at_entry=_hi52,
                    dist_to_52w_high_pct=_dist52,
                    high_52w_at_trigger=high_52w_at_trigger_val,
                    dist_to_52w_high_pct_at_trigger=dist_to_52w_high_pct_at_trigger_val,
                    had_meteoric_rise_before_entry=int(meteor_rise_ever_arr[_trigger_bar])
                    if 0 <= _trigger_bar < len(meteor_rise_ever_arr)
                    else 0,
                    had_meteoric_fall_before_entry=int(meteor_fall_ever_arr[_trigger_bar])
                    if 0 <= _trigger_bar < len(meteor_fall_ever_arr)
                    else 0,
                    spy_compare_1y=_spy_c1,
                    spy_compare_2y=_spy_c2,
                    spy_compare_3y=_spy_c3,
                    entry_indicators=(
                        _snapshot_entry_indicators_for_trade(
                            _sym_indicator_pre,
                            int(_trigger_bar),
                            "LONG" if _is_long_side else "SHORT",
                        )
                        if _cfg_use_indicators
                        else {}
                    ),
                )
                if open_trade is None:
                    open_trade = _new_trade
                    max_high_since_entry = entry_price
                elif _cfg_allow_secondary:
                    extra_open_trades.append(_new_trade)
                    _secondary_max_high.append(float(entry_price))
                    _secondary_pending_ind.append(False)
                else:
                    open_trade = _new_trade
                    max_high_since_entry = entry_price
                if _cfg_pbr_zones:
                    _pzid = str(getattr(_new_trade, "pbr_zone_id", "") or "")
                    if _pzid:
                        _apply_pbr_strength_to_trade(_new_trade, pbr_zone_meta.get(_pzid) or {})
                    _pbr_on_entry(_pzid)
            if _perf:
                _acc_bt("bt_pending_entry_build", time.perf_counter() - _t_ent_bld)
            _pe()
            break
        if _perf:
            _acc_bt("bt_loop_pending_for", time.perf_counter() - _t_pfor)
        pending_maturities = still_pending
        if _perf:
            _acc_bt("bt_loop_bar_total", time.perf_counter() - _t_bar)

    if profile_block_reasons is not None:
        for k, v in _block_reasons.items():
            profile_block_reasons[k] = profile_block_reasons.get(k, 0) + int(v)
    if _cfg_collect_ind_while_held and _sym_indicator_pre is not None:
        _collect_indicators_while_held_for_trades(
            indicators_while_held_rows_out,
            sym=sym,
            closed=closed,
            open_trade=open_trade,
            index_iso=index_iso,
            pre=_sym_indicator_pre,
            close_arr=close_arr,
        )
    watchlist = _watchlist_for_symbol(
        sym,
        scanner,
        pending_maturities,
        cfg,
        n,
        index_iso,
        close_arr,
        open_arr,
        high_arr,
        low_arr,
        _brt_br_rows,
        pre=_sym_indicator_pre,
        entry_side=_cfg_entry_side,
        rs_st=_rs_st,
        rs_sp=_rs_sp,
    )
    return closed, open_trade, scanner, short_candidates, would_have, watchlist, extra_open_trades


def _indicator_only_scan_gates_block(
    cfg: BRTConfig,
    *,
    signal_t: int,
    close_arr: np.ndarray,
    open_arr: np.ndarray,
    high_arr: np.ndarray,
    low_arr: np.ndarray,
    atr_14_arr: np.ndarray,
    entry_side: str,
    sym_indicator_pre: Any,
    entry_neutral_n_fn: Any,
    entry_bull_n_fn: Any,
    ind_score_at_bar_fn: Any,
    hl_dec: int,
    rs_st: Optional[np.ndarray] = None,
    rs_sp: Optional[np.ndarray] = None,
    beta_by_bar: Optional[np.ndarray] = None,
) -> bool:
    """True when optional programmatic gates reject an indicator-only scan candidate."""
    _is_long = _normalize_entry_type(entry_side) == "long"
    if bool(getattr(cfg, "require_close_gt_open", True)):
        if hl_dec >= 0:
            cl = round(float(close_arr[signal_t]), hl_dec)
            op = round(float(open_arr[signal_t]), hl_dec)
            hi = round(float(high_arr[signal_t]), hl_dec)
            lo = round(float(low_arr[signal_t]), hl_dec)
        else:
            cl = float(close_arr[signal_t])
            op = float(open_arr[signal_t])
            hi = float(high_arr[signal_t])
            lo = float(low_arr[signal_t])
        if _is_long:
            if not (cl > op):
                return True
        elif not (cl < op):
            return True
        min_rng = float(getattr(cfg, "entry_close_min_range_position", 0.0) or 0.0)
        if min_rng > 0 and hi > lo:
            if _is_long and cl < lo + (hi - lo) * min_rng:
                return True
            if (not _is_long) and cl > hi - (hi - lo) * min_rng:
                return True
    if bool(getattr(cfg, "growth_filter_enabled", False)) and int(getattr(cfg, "growth_bars", 0) or 0) > 0:
        ago = _growth_ago_bar_index(signal_t, cfg)
        if ago < 0:
            return True
        if float(close_arr[signal_t]) < float(close_arr[ago]):
            return True
    min_trig = _cfg_min_atr_pct_trigger(cfg)
    max_trig = _cfg_max_atr_pct_trigger(cfg)
    if min_trig > 0.0 or max_trig > 0.0:
        _, atr_pct_trig = _atr_14_and_pct_at_bar(atr_14_arr, close_arr, signal_t)
        if min_trig > 0.0:
            if atr_pct_trig is None or not np.isfinite(float(atr_pct_trig)) or float(atr_pct_trig) < min_trig:
                return True
        if max_trig > 0.0:
            if atr_pct_trig is None or not np.isfinite(float(atr_pct_trig)) or float(atr_pct_trig) > max_trig:
                return True
    _max_neut = getattr(cfg, "max_ind_entry_neutral_n", None)
    _min_bull = getattr(cfg, "min_ind_entry_bull_n", None)
    if sym_indicator_pre is None:
        if _max_neut is not None or _min_bull is not None or _cfg_min_ind_score_filter_active(cfg):
            return True
    else:
        if _max_neut is not None and entry_neutral_n_fn is not None:
            nn = entry_neutral_n_fn(sym_indicator_pre, signal_t, entry_side)
            if nn is None or int(nn) > int(_max_neut):
                return True
        if _min_bull is not None and entry_bull_n_fn is not None:
            bn = entry_bull_n_fn(sym_indicator_pre, signal_t, entry_side)
            if bn is None or int(bn) < int(_min_bull):
                return True
        if _cfg_min_ind_score_filter_active(cfg):
            if ind_score_at_bar_fn is None:
                return True
            sc = ind_score_at_bar_fn(sym_indicator_pre, signal_t)
            if sc is None or float(sc) < _cfg_min_ind_score(cfg):
                return True
    if _dist_52w_high_at_trigger_gate_blocks(cfg, high_arr, close_arr, signal_t):
        return True
    if _spy_compare_1y_at_trigger_gate_blocks(cfg, rs_st, rs_sp, signal_t):
        return True
    if _spy_compare_1y_max_at_trigger_gate_blocks(cfg, rs_st, rs_sp, signal_t):
        return True
    if _spy_compare_2y_at_trigger_gate_blocks(cfg, rs_st, rs_sp, signal_t):
        return True
    if _spy_compare_3y_at_trigger_gate_blocks(cfg, rs_st, rs_sp, signal_t):
        return True
    if _beta_min_at_trigger_gate_blocks(cfg, beta_by_bar, signal_t):
        return True
    if _beta_max_at_trigger_gate_blocks(cfg, beta_by_bar, signal_t):
        return True
    if _upper_wick_atr_min_at_trigger_gate_blocks(
        cfg, high_arr, open_arr, close_arr, atr_14_arr, signal_t
    ):
        return True
    if _mandatory_ind_states_gate_blocks(cfg, sym_indicator_pre, signal_t, entry_side):
        return True
    return False


def _run_scan_entry_backtest(
    sym: str,
    df: pd.DataFrame,
    cfg: BRTConfig,
    benchmark_df: Optional[pd.DataFrame],
    *,
    entry_mode: str,
) -> tuple[list[BRTTrade], Optional[BRTTrade], list[dict], list[dict], list[dict], list[dict]]:
    """
    Bar-scan entry (repeated): open at bar t+1 after signal on bar t; one position at a time per symbol.
    ``entry_mode`` ``rs`` = SPY 252/504/756 excess returns; ``ind`` = trade-aligned IND_DIFF >= indicator_diff.
    Exit rules match ``run_brt_backtest`` (gap/stop/target/ATR schedule).
    """
    _is_ind_mode = str(entry_mode or "rs").strip().lower() == "ind"
    _is_rs_mode = not _is_ind_mode
    closed: list[BRTTrade] = []
    open_trade: Optional[BRTTrade] = None
    last_exit_yyyymmdd: str = ""
    scanner: list[dict] = []
    short_candidates: list[dict] = []
    would_have: list[dict] = []
    n = len(df)
    min_req = _min_bars_required_for_cfg(cfg)
    if n < min_req or sym.strip().upper() == "SPY":
        try:
            idx_parsed = pd.to_datetime(df.index, errors="coerce")
            index_iso = pd.DatetimeIndex(idx_parsed).strftime("%Y%m%d").tolist() if len(idx_parsed) == n else []
        except Exception:
            index_iso = []
        if len(index_iso) != n:
            index_iso = [
                (df.index[i].strftime("%Y%m%d") if hasattr(df.index[i], "strftime") else str(df.index[i])[:10].replace("-", ""))
                for i in range(n)
            ]
        close_arr = df["Close"].to_numpy(dtype=np.float64) if n else np.array([], dtype=np.float64)
        open_arr = df["Open"].to_numpy(dtype=np.float64) if n else np.array([], dtype=np.float64)
        high_arr = df["High"].to_numpy(dtype=np.float64) if n else np.array([], dtype=np.float64)
        low_arr = df["Low"].to_numpy(dtype=np.float64) if n else np.array([], dtype=np.float64)
        wl = _watchlist_for_symbol(
            sym, scanner, [], cfg, n, index_iso, close_arr, open_arr, high_arr, low_arr, None,
            pre=None, entry_side=_normalize_entry_type(getattr(cfg, "entry_type", "long")),
        )
        return closed, open_trade, scanner, short_candidates, would_have, wl

    open_arr = df["Open"].to_numpy(dtype=np.float64)
    high_arr = df["High"].to_numpy(dtype=np.float64)
    low_arr = df["Low"].to_numpy(dtype=np.float64)
    close_arr = df["Close"].to_numpy(dtype=np.float64)
    try:
        idx_parsed = pd.to_datetime(df.index, errors="coerce")
        if pd.isna(idx_parsed).any():
            raise ValueError("index has unparseable dates")
        index_iso = pd.DatetimeIndex(idx_parsed).strftime("%Y%m%d").tolist()
        if len(index_iso) != n:
            raise ValueError("index_iso length mismatch")
    except Exception:
        index_iso = [
            (df.index[i].strftime("%Y%m%d") if hasattr(df.index[i], "strftime") else str(df.index[i])[:10].replace("-", ""))
            for i in range(n)
        ]
    atr_14_arr = _compute_atr_14_arr(high_arr, low_arr, close_arr, 14)
    sma50_arr_rs: Optional[np.ndarray] = (
        _compute_sma_arr(close_arr, 50) if bool(getattr(cfg, "use_sma50", False)) else None
    )
    _sma_stop_days_rs = int(getattr(cfg, "sma_stop_days", 0) or 0)
    sma_stop_arr_rs: Optional[np.ndarray] = (
        _compute_sma_arr(close_arr, _sma_stop_days_rs) if _sma_stop_days_rs > 0 else None
    )
    volume_arr = df["Volume"].to_numpy(dtype=np.float64) if "Volume" in df.columns else None
    meteor_rise_ever_arr, meteor_fall_ever_arr = _precompute_meteoric_cumulative_flags(
        close_arr,
        low_arr,
        high_arr,
        float(getattr(cfg, "meteoric_rise_pct", 300.0) or 0.0),
        int(getattr(cfg, "meteoric_rise_lookback", 100) or 0),
        float(getattr(cfg, "meteoric_fall_pct", 50.0) or 0.0),
        int(getattr(cfg, "meteoric_fall_lookback", 100) or 0),
    )
    aligned = _align_stock_spy_close_for_rs(df, benchmark_df)
    st: Optional[np.ndarray] = None
    sp: Optional[np.ndarray] = None
    if aligned is not None:
        st, sp = aligned
    elif _is_rs_mode:
        wl = _watchlist_for_symbol(
            sym, scanner, [], cfg, n, index_iso, close_arr, open_arr, high_arr, low_arr, None,
            pre=None,
            entry_side=_normalize_entry_type(getattr(cfg, "entry_type", "long")),
        )
        return closed, open_trade, scanner, short_candidates, would_have, wl

    _cfg_atr_target = float(getattr(cfg, "atr_target", 0.0) or 0.0)
    _cfg_atr_stop = float(getattr(cfg, "atr_stop", 0.0) or 0.0)
    _use_atr_exits_loop = (_cfg_atr_target > 0.0) or (_cfg_atr_stop > 0.0)
    _cfg_trailing_stop_inc = float(getattr(cfg, "trailing_stop_increment", 0.0) or 0.0)
    _cfg_sell_on_low_vol_rs = float(getattr(cfg, "sell_on_low_vol", 0.0) or 0.0)
    _cfg_sma_stop_days_rs = int(getattr(cfg, "sma_stop_days", 0) or 0)
    _cfg_stop_cmp_rd = int(getattr(cfg, "stop_compare_round_decimals", 2))
    _cfg_entry_side_rs = _normalize_entry_type(getattr(cfg, "entry_type", "long"))
    _is_long_side = _cfg_entry_side_rs == "long"
    _cfg_stop_pct = float(getattr(cfg, "stop_pct", 0.0) or 0.0)
    _cfg_short_stop_pct = float(getattr(cfg, "short_stop_pct", _cfg_stop_pct) or 0.0)
    _cfg_short_target_pct = float(getattr(cfg, "short_target_pct", getattr(cfg, "target_pct", 0.0)) or 0.0)
    _need_beta = bool(
        benchmark_df is not None
        and (
            bool(getattr(cfg, "compute_beta", False))
            or abs(float(getattr(cfg, "weight_beta_at_entry", 0.0) or 0.0)) > 1e-12
            or float(getattr(cfg, "min_beta_at_trigger", 0.0) or 0.0) > 0.0
            or float(getattr(cfg, "max_beta_at_trigger", 0.0) or 0.0) > 0.0
        )
    )
    beta_by_bar_rs: Optional[np.ndarray] = None
    if _need_beta:
        beta_by_bar_rs = _precompute_beta_by_bar_index(df, benchmark_df, _BETA_ROLLING_WINDOW)

    _cfg_sell_ind_diff_below_rs = _cfg_sell_ind_diff_threshold(cfg)
    _cfg_exit_ind_diff_only_rs = bool(getattr(cfg, "exit_ind_diff_only", False)) and (
        _cfg_sell_ind_diff_below_rs is not None
    )
    _cfg_indicator_buy_rs = _normalize_indicator_buy(getattr(cfg, "indicator_buy", "off"))
    _cfg_use_indicators_rs = bool(getattr(cfg, "use_indicators", False))
    _cfg_indicator_diff_scan = int(getattr(cfg, "indicator_diff", 10) or 10)
    _use_avg_ind_scan = bool(getattr(cfg, "use_average_ind", False))
    _avg_ind_combine_scan = bool(getattr(cfg, "average_ind_combine", False))
    _avg_ind_map_scan = getattr(cfg, "avg_ind_diff_by_date", None) or {}
    _hl_dec_scan = int(getattr(cfg, "zone_price_round_decimals", 2))
    _sym_indicator_pre_rs: Optional[Any] = None
    _aligned_bull_bear_diff_fn_rs: Optional[Any] = None
    _entry_neutral_n_fn_rs: Optional[Any] = None
    _entry_bull_n_fn_rs: Optional[Any] = None
    _ind_score_at_bar_fn_rs: Optional[Any] = None
    if (
        _is_ind_mode
        or _cfg_use_indicators_rs
        or _cfg_sell_ind_diff_below_rs is not None
        or _cfg_indicator_buy_rs in ("only", "both")
    ):
        try:
            from brt_entry_indicators import (
                aligned_bull_bear_diff as _aligned_bull_bear_diff_fn_rs_bt,
                build_entry_indicator_precompute,
                entry_bull_n as _entry_bull_n_fn_rs_bt,
                entry_neutral_n as _entry_neutral_n_fn_rs_bt,
                ind_score_at_bar as _ind_score_at_bar_fn_rs_bt,
            )
        except ImportError:
            from stock_analysis.brt_entry_indicators import (
                aligned_bull_bear_diff as _aligned_bull_bear_diff_fn_rs_bt,
                build_entry_indicator_precompute,
                entry_bull_n as _entry_bull_n_fn_rs_bt,
                entry_neutral_n as _entry_neutral_n_fn_rs_bt,
                ind_score_at_bar as _ind_score_at_bar_fn_rs_bt,
            )
        _aligned_bull_bear_diff_fn_rs = _aligned_bull_bear_diff_fn_rs_bt
        _entry_neutral_n_fn_rs = _entry_neutral_n_fn_rs_bt
        _entry_bull_n_fn_rs = _entry_bull_n_fn_rs_bt
        _ind_score_at_bar_fn_rs = _ind_score_at_bar_fn_rs_bt
        _sym_indicator_pre_rs = build_entry_indicator_precompute(
            df,
            symbol=sym,
            cache_dir=(str(getattr(cfg, "indicator_cache_dir", "") or "").strip() or None),
            use_cache=bool(getattr(cfg, "indicator_cache", True)),
        )

    if _is_ind_mode and _sym_indicator_pre_rs is None:
        wl = _watchlist_for_symbol(
            sym, scanner, [], cfg, n, index_iso, close_arr, open_arr, high_arr, low_arr, None,
            pre=None,
            entry_side=_cfg_entry_side_rs,
        )
        return closed, open_trade, scanner, short_candidates, would_have, wl

    search_from = (_INDICATOR_ONLY_MIN_BARS - 1) if _is_ind_mode else _RS_SPY_LAG_3Y
    while search_from <= n - 2:
        signal_t = -1
        for t in range(search_from, n - 1):
            if _is_ind_mode:
                if _sym_indicator_pre_rs is None or _aligned_bull_bear_diff_fn_rs is None:
                    continue
                _ind_diff_probe = _aligned_bull_bear_diff_fn_rs(
                    _sym_indicator_pre_rs, t, _cfg_entry_side_rs
                )
                _thr_scan = _cfg_indicator_diff_scan
                if _use_avg_ind_scan and 0 <= t < len(index_iso):
                    _av_scan = _avg_ind_map_scan.get(index_iso[t])
                    if _av_scan is not None:
                        _thr_scan = max(_cfg_indicator_diff_scan, _av_scan) if _avg_ind_combine_scan else _av_scan
                if _ind_diff_probe is None or float(_ind_diff_probe) < _thr_scan:
                    continue
                if _indicator_only_scan_gates_block(
                    cfg,
                    signal_t=t,
                    close_arr=close_arr,
                    open_arr=open_arr,
                    high_arr=high_arr,
                    low_arr=low_arr,
                    atr_14_arr=atr_14_arr,
                    entry_side=_cfg_entry_side_rs,
                    sym_indicator_pre=_sym_indicator_pre_rs,
                    entry_neutral_n_fn=_entry_neutral_n_fn_rs,
                    entry_bull_n_fn=_entry_bull_n_fn_rs,
                    ind_score_at_bar_fn=_ind_score_at_bar_fn_rs,
                    hl_dec=_hl_dec_scan,
                    rs_st=st,
                    rs_sp=sp,
                    beta_by_bar=beta_by_bar_rs,
                ):
                    continue
            elif st is None or sp is None or not _rs_pass_all_horizons_vs_spy(st, sp, t):
                continue
            if _dist_52w_high_at_trigger_gate_blocks(cfg, high_arr, close_arr, t):
                continue
            if _spy_compare_1y_at_trigger_gate_blocks(cfg, st, sp, t):
                continue
            if _spy_compare_1y_max_at_trigger_gate_blocks(cfg, st, sp, t):
                continue
            if _spy_compare_2y_at_trigger_gate_blocks(cfg, st, sp, t):
                continue
            if _spy_compare_3y_at_trigger_gate_blocks(cfg, st, sp, t):
                continue
            if _beta_min_at_trigger_gate_blocks(cfg, beta_by_bar_rs, t):
                continue
            if _beta_max_at_trigger_gate_blocks(cfg, beta_by_bar_rs, t):
                continue
            if _upper_wick_atr_min_at_trigger_gate_blocks(
                cfg, high_arr, open_arr, close_arr, atr_14_arr, t
            ):
                continue
            if _mandatory_ind_states_gate_blocks(cfg, _sym_indicator_pre_rs, t, _cfg_entry_side_rs):
                continue
            signal_t = t
            break
        if signal_t < 0:
            break

        if st is not None and sp is not None:
            sc1, sc2, sc3 = _rs_excess_pct_points(st, sp, signal_t)
        else:
            sc1 = sc2 = sc3 = None
        entry_bar = signal_t + 1
        entry_price = float(open_arr[entry_bar])
        trigger_bar_low = float(low_arr[signal_t])
        trigger_bar_high = float(high_arr[signal_t])
        prior_close_rs = float(close_arr[signal_t - 1]) if signal_t >= 1 else float("nan")
        too_high_mult = float(getattr(cfg, "too_high_multiplier", 0.0) or 0.0)
        too_low_mult = float(getattr(cfg, "too_low_multiplier", 0.0) or 0.0)
        _skip_entry_open = False
        if too_high_mult > 0:
            if _is_long_side and trigger_bar_low > 0 and entry_price > (trigger_bar_low * too_high_mult):
                _skip_entry_open = True
            elif (not _is_long_side) and trigger_bar_high > 0 and entry_price < (trigger_bar_high / too_high_mult):
                _skip_entry_open = True
        if (
            not _skip_entry_open
            and too_low_mult > 0
            and signal_t >= 1
            and np.isfinite(prior_close_rs)
            and prior_close_rs > 0
        ):
            if _is_long_side and entry_price < (prior_close_rs * too_low_mult):
                _skip_entry_open = True
            elif (not _is_long_side) and entry_price > (prior_close_rs / too_low_mult):
                _skip_entry_open = True
        if _skip_entry_open:
            search_from = signal_t + 1
            continue
        atr_14_at_trigger_val, atr_pct_at_trigger_val = _atr_14_and_pct_at_bar(
            atr_14_arr, close_arr, signal_t
        )
        high_52w_at_trigger_val, dist_to_52w_high_pct_at_trigger_val = _high_52w_and_dist_pct(
            high_arr, signal_t, float(close_arr[signal_t])
        )
        _had_meteoric_rise_rs = (
            int(meteor_rise_ever_arr[signal_t])
            if 0 <= signal_t < len(meteor_rise_ever_arr)
            else 0
        )
        _had_meteoric_fall_rs = (
            int(meteor_fall_ever_arr[signal_t])
            if 0 <= signal_t < len(meteor_fall_ever_arr)
            else 0
        )
        if _entry_filter_tri_state_blocks(
            _had_meteoric_rise_rs, getattr(cfg, "entry_filter_meteoric_rise", "both")
        ):
            search_from = signal_t + 1
            continue
        if _entry_filter_tri_state_blocks(
            _had_meteoric_fall_rs, getattr(cfg, "entry_filter_meteoric_fall", "both")
        ):
            search_from = signal_t + 1
            continue
        atr_14_at_entry_val = (
            float(atr_14_arr[entry_bar])
            if (entry_bar < n and not (atr_14_arr[entry_bar] != atr_14_arr[entry_bar]))
            else None
        )
        atr_pct = None
        if atr_14_at_entry_val is not None and entry_price > 0:
            atr_pct = (atr_14_at_entry_val / entry_price) * 100.0
        target_price = _brt_target_price(
            cfg,
            entry_price=entry_price,
            entry_bar=entry_bar,
            is_long_side=_is_long_side,
            atr_pct=atr_pct,
            sma50_arr=sma50_arr_rs,
            cfg_atr_target=_cfg_atr_target,
            cfg_short_target_pct=_cfg_short_target_pct,
        )
        if _cfg_atr_stop > 0 and atr_pct is not None:
            stop_price = (
                entry_price * (1.0 - atr_pct * cfg.atr_stop / 100.0)
                if _is_long_side
                else entry_price * (1.0 + atr_pct * cfg.atr_stop / 100.0)
            )
        elif (_cfg_stop_pct > 0 and _is_long_side) or (_cfg_short_stop_pct > 0 and (not _is_long_side)):
            _sp = _cfg_stop_pct if _is_long_side else _cfg_short_stop_pct
            if _is_long_side:
                stop_price = entry_price * _sp if cfg.stop_pct_is_multiplier else entry_price * (1 - _sp)
            else:
                stop_price = (
                    entry_price * (2.0 - _sp)
                    if cfg.stop_pct_is_multiplier
                    else entry_price * (1 + _sp)
                )
        else:
            _def_mult = 0.934
            _def_frac_below = 0.066
            if _is_long_side:
                stop_price = (
                    entry_price * _def_mult
                    if cfg.stop_pct_is_multiplier
                    else entry_price * (1 - _def_frac_below)
                )
            else:
                stop_price = (
                    entry_price * (2.0 - _def_mult)
                    if cfg.stop_pct_is_multiplier
                    else entry_price * (1 + _def_frac_below)
                )

        next_iso = index_iso[entry_bar] if entry_bar < len(index_iso) else ""
        cl_sig = float(close_arr[signal_t])

        if entry_bar >= n - 1:
            _th_lim_rs = _entry_open_band_fields(
                trigger_bar_low,
                trigger_bar_high,
                prior_close_rs,
                too_high_mult,
                too_low_mult,
                _is_long_side,
            )
            _sc_stop, _sc_target = _brt_stop_target_prices(
                cfg,
                anchor_price=cl_sig,
                entry_bar=entry_bar,
                is_long_side=_is_long_side,
                atr_14_arr=atr_14_arr,
                sma50_arr=sma50_arr_rs,
            )
            scanner.append({
                "symbol": sym,
                "date": next_iso,
                "close": cl_sig,
                "stop": _sc_stop,
                "target": _sc_target,
                "zone_center": 0.0,
                "atr_pct_at_entry": atr_pct,
                "atr_pct_at_trigger": atr_pct_at_trigger_val,
                **_th_lim_rs,
                "maturity_date": "",
                "close_above_date": "",
                "entry_indicators": (
                    _snapshot_entry_indicators_for_trade(
                        _sym_indicator_pre_rs,
                        int(signal_t),
                        "LONG",
                    )
                    if _sym_indicator_pre_rs is not None
                    else {}
                ),
            })
            search_from = signal_t + 1
            continue

        if getattr(cfg, "min_hist_ann_ror_avg", -100.0) > -100.0:
            _hn_rs, _, _har_rs = _hist_stats_for_symbol(closed, sym, float(getattr(cfg, "days_per_year", 365.0) or 365.0))
            if _hn_rs > 0 and _har_rs < cfg.min_hist_ann_ror_avg:
                search_from = signal_t + 1
                continue

        if _need_beta:
            if beta_by_bar_rs is not None and entry_bar < len(beta_by_bar_rs):
                bv = beta_by_bar_rs[entry_bar]
                beta_at_entry_val = float(bv) if (bv == bv and np.isfinite(bv)) else None
            else:
                beta_at_entry_val = _rolling_beta_at_entry(df, entry_bar, benchmark_df, _BETA_ROLLING_WINDOW)
        else:
            beta_at_entry_val = None

        _last_ath_bar, _td_since_ath = _running_ath_last_bar_index(high_arr, entry_bar)
        _last_ath_date = (
            index_iso[_last_ath_bar][:8]
            if 0 <= _last_ath_bar < len(index_iso)
            else ""
        )
        _hi52, _dist52 = _high_52w_and_dist_pct(high_arr, entry_bar, entry_price)

        vol_entry: Optional[float] = None
        avg_10d: Optional[float] = None
        rel_vol: Optional[float] = None
        if volume_arr is not None and entry_bar < n:
            v1 = volume_arr[entry_bar]
            if not (v1 != v1):
                vol_entry = float(v1)
            if vol_entry is not None:
                start_10 = max(0, entry_bar - 9)
                slice_10 = volume_arr[start_10 : entry_bar + 1]
                valid = slice_10 == slice_10
                if np.any(valid):
                    avg_10d = float(np.nanmean(slice_10))
                    if avg_10d and avg_10d > 0:
                        rel_vol = vol_entry / avg_10d

        if getattr(cfg, "min_rel_vol_at_entry", -2.0) > -2.0:
            if rel_vol is None or rel_vol < cfg.min_rel_vol_at_entry:
                search_from = signal_t + 1
                continue
        if float(getattr(cfg, "min_avg_volume_10d_at_entry", 0.0) or 0.0) > 0.0:
            if avg_10d is None or not np.isfinite(float(avg_10d)) or float(avg_10d) < float(cfg.min_avg_volume_10d_at_entry):
                search_from = signal_t + 1
                continue

        _cd_days_rs = int(getattr(cfg, "symbol_reentry_cooldown_days", 0) or 0)
        if _cd_days_rs > 0 and last_exit_yyyymmdd and next_iso:
            if _symbol_reentry_cooldown_blocks(last_exit_yyyymmdd, next_iso, _cd_days_rs):
                search_from = signal_t + 1
                continue

        open_trade = BRTTrade(
            symbol=sym,
            side=("LONG" if _is_long_side else "SHORT"),
            date_opened=next_iso,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            zone_center=0.0,
            touch_count=0,
            touch_count_major=0,
            touch_count_minor=0,
            touch_count_short=0,
            is_tradeable_key_level=False,
            struct_high="",
            struct_low="",
            entry_pivot_type=("IND" if _is_ind_mode else "RS"),
            entry_struct_regime="",
            entry_major_pivot=0,
            entry_pivot_was_strong=0,
            entry_zone_was_strong_pivot=0,
            nearby_zones_above=0,
            nearby_zones_below=0,
            zone_cluster_density=0,
            maturity_date="",
            close_above_date="",
            breakout_date="",
            days_since_breakout=None,
            volume_at_entry=vol_entry,
            avg_volume_10d_at_entry=avg_10d,
            rel_vol_at_entry=rel_vol,
            rel_vol_on_trigger=None,
            atr_14_at_entry=atr_14_at_entry_val,
            entry_bar_index=int(entry_bar),
            atr_pct_at_entry=float(atr_pct) if atr_pct is not None and np.isfinite(float(atr_pct)) else None,
            atr_14_at_trigger=atr_14_at_trigger_val,
            atr_pct_at_trigger=atr_pct_at_trigger_val,
            beta_at_entry=beta_at_entry_val,
            sheet_ladder_rung_at_signal=0,
            last_ath_date_at_entry=_last_ath_date,
            trading_days_since_last_ath_at_entry=_td_since_ath,
            high_52w_at_entry=_hi52,
            dist_to_52w_high_pct=_dist52,
            high_52w_at_trigger=high_52w_at_trigger_val,
            dist_to_52w_high_pct_at_trigger=dist_to_52w_high_pct_at_trigger_val,
            had_meteoric_rise_before_entry=int(meteor_rise_ever_arr[signal_t])
            if 0 <= signal_t < len(meteor_rise_ever_arr)
            else 0,
            had_meteoric_fall_before_entry=int(meteor_fall_ever_arr[signal_t])
            if 0 <= signal_t < len(meteor_fall_ever_arr)
            else 0,
            spy_compare_1y=sc1,
            spy_compare_2y=sc2,
            spy_compare_3y=sc3,
            entry_indicators=(
                _snapshot_entry_indicators_for_trade(
                    _sym_indicator_pre_rs,
                    int(signal_t),
                    "LONG" if _is_long_side else "SHORT",
                )
                if (_cfg_use_indicators_rs or _is_ind_mode) and _sym_indicator_pre_rs is not None
                else {}
            ),
        )

        max_high_since_entry = float(entry_price)
        exit_bar = -1
        _pending_ind_diff_exit_rs = False
        for j in range(entry_bar, n):
            if open_trade is None:
                break
            iso = index_iso[j]
            op = open_arr[j]
            hi = high_arr[j]
            lo = low_arr[j]
            cl = close_arr[j]
            max_high_since_entry = max(max_high_since_entry, hi)
            _trade_is_long = str(getattr(open_trade, "side", "LONG") or "LONG").upper() != "SHORT"
            _trade_side_rs = str(getattr(open_trade, "side", "LONG") or "LONG")
            _ind_diff_exit_now_rs = False
            if (
                _cfg_sell_ind_diff_below_rs is not None
                and _pending_ind_diff_exit_rs
                and _sym_indicator_pre_rs is not None
                and _aligned_bull_bear_diff_fn_rs is not None
            ):
                _ind_diff_exit_now_rs = True
                _pending_ind_diff_exit_rs = False
            tp = open_trade.target_price
            trail_inc = _cfg_trailing_stop_inc
            if _ind_diff_exit_now_rs or _cfg_exit_ind_diff_only_rs:
                sp_work = float(open_trade.stop_price)
                inc_active = False
                sma_active = False
                hit_trailing_gain = False
                inc_floor = None
            else:
                sp_work, inc_active, sma_active, hit_trailing_gain, inc_floor = _resolve_working_stop(
                    open_trade,
                    j,
                    cfg,
                    index_iso,
                    close_arr,
                    sma_stop_arr_rs,
                    max_high_since_entry,
                    trail_inc,
                    _cfg_sma_stop_days_rs,
                    _trade_is_long,
                )
            if _cfg_stop_cmp_rd >= 0:
                op_cmp = round(float(op), _cfg_stop_cmp_rd)
                lo_cmp = round(float(lo), _cfg_stop_cmp_rd)
                sp_cmp = round(float(sp_work), _cfg_stop_cmp_rd)
                inc_cmp = round(float(inc_floor), _cfg_stop_cmp_rd) if inc_active else None
            else:
                op_cmp = float(op)
                lo_cmp = float(lo)
                sp_cmp = float(sp_work)
                inc_cmp = float(inc_floor) if inc_active else None
            if _trade_is_long:
                gap_down = op_cmp <= sp_cmp
                gap_up = op >= tp
                stop_hit = lo_cmp <= sp_cmp
                target_hit = hi >= tp
            else:
                gap_down = op <= tp
                gap_up = op_cmp >= sp_cmp
                stop_hit = hi >= sp_work
                target_hit = lo <= tp
            hit_trailing_stop = bool(hit_trailing_gain and not inc_active and not sma_active)
            hit_inc_stop_gap = bool(inc_active and inc_cmp is not None and op_cmp <= inc_cmp)
            hit_inc_stop_touch = bool(inc_active and inc_cmp is not None and lo_cmp <= inc_cmp)
            hit_sma_stop_gap = bool(sma_active and op_cmp <= sp_cmp)
            hit_sma_stop_touch = bool(sma_active and lo_cmp <= sp_cmp)

            if _ind_diff_exit_now_rs:
                exit_price = op
                exit_type = "IND_DIFF_EXIT"
            elif _low_rel_vol_exit_at_open(open_trade, j, _cfg_sell_on_low_vol_rs):
                exit_price = op
                exit_type = "LOW_REL_VOL_EXIT"
            elif _cfg_exit_ind_diff_only_rs:
                if _arm_ind_diff_exit_if_signal(
                    threshold=int(_cfg_sell_ind_diff_below_rs),
                    sym_indicator_pre=_sym_indicator_pre_rs,
                    aligned_fn=_aligned_bull_bear_diff_fn_rs,
                    bar_i=j,
                    side=_trade_side_rs,
                ):
                    _pending_ind_diff_exit_rs = True
                continue
            elif _trade_is_long and gap_down:
                exit_price = op
                if hit_inc_stop_gap:
                    exit_type = "atr_incremental_stop"
                elif hit_sma_stop_gap:
                    exit_type = "SMA_STOP"
                elif hit_trailing_stop:
                    exit_type = "TRAILING_STOP"
                elif _use_atr_exits_loop:
                    exit_type = "ATR_STOP"
                else:
                    exit_type = "GAP_DOWN"
            elif _trade_is_long and gap_up:
                exit_price = op
                exit_type = "ATR_TARGET" if _use_atr_exits_loop else "GAP_UP"
            elif (not _trade_is_long) and gap_up:
                exit_price = op
                if hit_inc_stop_gap:
                    exit_type = "atr_incremental_stop"
                elif hit_sma_stop_gap:
                    exit_type = "SMA_STOP"
                elif hit_trailing_stop:
                    exit_type = "TRAILING_STOP"
                elif _use_atr_exits_loop:
                    exit_type = "ATR_STOP"
                else:
                    exit_type = "GAP_UP"
            elif (not _trade_is_long) and gap_down:
                exit_price = op
                exit_type = "ATR_TARGET" if _use_atr_exits_loop else "GAP_DOWN"
            elif stop_hit:
                exit_price = cl if cfg.exit_at_close_when_stopped else sp_work
                if hit_inc_stop_touch:
                    exit_type = "atr_incremental_stop"
                elif hit_sma_stop_touch:
                    exit_type = "SMA_STOP"
                elif hit_trailing_stop:
                    exit_type = "TRAILING_STOP"
                elif _use_atr_exits_loop:
                    exit_type = "ATR_STOP"
                else:
                    exit_type = "STOP_LOSS"
            elif target_hit:
                exit_price = tp
                exit_type = "ATR_TARGET" if _use_atr_exits_loop else "TARGET"
            else:
                _ai_ok, _ai_px, _ai_typ = _atr_schedule_exit_now(cfg, open_trade, j, high_arr, open_arr, index_iso)
                if _ai_ok:
                    exit_price = _ai_px
                    exit_type = _ai_typ
                else:
                    if _cfg_sell_ind_diff_below_rs is not None and _arm_ind_diff_exit_if_signal(
                        threshold=int(_cfg_sell_ind_diff_below_rs),
                        sym_indicator_pre=_sym_indicator_pre_rs,
                        aligned_fn=_aligned_bull_bear_diff_fn_rs,
                        bar_i=j,
                        side=_trade_side_rs,
                    ):
                        _pending_ind_diff_exit_rs = True
                    continue

            pnl_move = (exit_price - open_trade.entry_price) if _trade_is_long else (open_trade.entry_price - exit_price)
            pnl_pct = (pnl_move / open_trade.entry_price) * 100
            pnl_dollars = (cfg.brt_cash / open_trade.entry_price) * pnl_move
            days_held = (pd.Timestamp(iso) - pd.Timestamp(open_trade.date_opened)).days if len(iso) == 8 else 0
            d_open = open_trade.date_opened
            if len(d_open) == 8 and len(iso) == 8:
                start_dt = pd.Timestamp(d_open[:4] + "-" + d_open[4:6] + "-" + d_open[6:8])
                end_dt = pd.Timestamp(iso[:4] + "-" + iso[4:6] + "-" + iso[6:8])
                mask = (df.index >= start_dt) & (df.index <= end_dt)
                max_price = float(df.loc[mask, "High"].max()) if mask.any() else open_trade.entry_price
            else:
                max_price = open_trade.entry_price

            t_closed = BRTTrade(
                symbol=sym,
                side=getattr(open_trade, "side", "LONG"),
                date_opened=open_trade.date_opened,
                entry_price=open_trade.entry_price,
                stop_price=open_trade.stop_price,
                target_price=open_trade.target_price,
                date_closed=iso,
                exit_price=exit_price,
                exit_type=exit_type,
                days_held=days_held,
                pnl_pct=pnl_pct,
                pnl_dollars=pnl_dollars,
                zone_center=open_trade.zone_center,
                zone_low=getattr(open_trade, "zone_low", 0.0),
                zone_high=getattr(open_trade, "zone_high", 0.0),
                pbr_zone_id=str(getattr(open_trade, "pbr_zone_id", "") or ""),
                touch_count=open_trade.touch_count,
                touch_count_short=open_trade.touch_count_short,
                touch_count_major=open_trade.touch_count_major,
                touch_count_minor=open_trade.touch_count_minor,
                zone_rolling_touches=int(getattr(open_trade, "zone_rolling_touches", 0) or 0),
                support_test_count=int(getattr(open_trade, "support_test_count", 0) or 0),
                support_test_at_signal=int(getattr(open_trade, "support_test_at_signal", 0) or 0),
                touch_count_at_maturity=int(getattr(open_trade, "touch_count_at_maturity", 0) or 0),
                touch_count_short_at_maturity=int(getattr(open_trade, "touch_count_short_at_maturity", 0) or 0),
                zone_episode_dn=int(getattr(open_trade, "zone_episode_dn", 0) or 0),
                days_since_maturity=int(getattr(open_trade, "days_since_maturity", 0) or 0),
                is_tradeable_key_level=open_trade.is_tradeable_key_level,
                struct_high=open_trade.struct_high,
                struct_low=open_trade.struct_low,
                entry_pivot_type=open_trade.entry_pivot_type,
                entry_struct_regime=open_trade.entry_struct_regime,
                entry_major_pivot=open_trade.entry_major_pivot,
                entry_pivot_was_strong=getattr(open_trade, "entry_pivot_was_strong", 0),
                entry_zone_was_strong_pivot=getattr(open_trade, "entry_zone_was_strong_pivot", 0),
                nearby_zones_above=open_trade.nearby_zones_above,
                nearby_zones_below=open_trade.nearby_zones_below,
                zone_cluster_density=open_trade.zone_cluster_density,
                maturity_date=open_trade.maturity_date,
                close_above_date=open_trade.close_above_date,
                breakout_date=getattr(open_trade, "breakout_date", "") or "",
                days_since_breakout=getattr(open_trade, "days_since_breakout", None),
                max_price=max_price,
                growth_pct_over_period=getattr(open_trade, "growth_pct_over_period", None),
                displacement_pct_at_entry=getattr(open_trade, "displacement_pct_at_entry", None),
                pivot_run_high=getattr(open_trade, "pivot_run_high", 0),
                pivot_run_low=getattr(open_trade, "pivot_run_low", 0),
                pivot_switch_h_to_l=getattr(open_trade, "pivot_switch_h_to_l", False),
                zone_above_center=getattr(open_trade, "zone_above_center", 0.0),
                zone_below_center=getattr(open_trade, "zone_below_center", 0.0),
                pct_entry_to_bottom_zone_above=getattr(open_trade, "pct_entry_to_bottom_zone_above", 0.0),
                pct_drop_to_top_zone_below=getattr(open_trade, "pct_drop_to_top_zone_below", 0.0),
                volume_at_entry=getattr(open_trade, "volume_at_entry", None),
                avg_volume_10d_at_entry=getattr(open_trade, "avg_volume_10d_at_entry", None),
                rel_vol_at_entry=getattr(open_trade, "rel_vol_at_entry", None),
                rel_vol_on_trigger=getattr(open_trade, "rel_vol_on_trigger", None),
                rejection_count_prior=int(
                    getattr(open_trade, "rejection_count_prior", None)
                    or getattr(open_trade, "resistance_touch_count_prior", 0)
                    or 0
                ),
                overlapping_mature_zones_count=int(getattr(open_trade, "overlapping_mature_zones_count", 0) or 0),
                rel_vol_at_breakout=getattr(open_trade, "rel_vol_at_breakout", None),
                atr_14_at_entry=getattr(open_trade, "atr_14_at_entry", None),
                entry_bar_index=int(getattr(open_trade, "entry_bar_index", -1) or -1),
                atr_pct_at_entry=getattr(open_trade, "atr_pct_at_entry", None),
                market_cap=getattr(open_trade, "market_cap", None),
                market_cap_current=getattr(open_trade, "market_cap_current", None),
                sector=getattr(open_trade, "sector", None),
                industry=getattr(open_trade, "industry", None),
                beta=getattr(open_trade, "beta", None),
                beta_at_entry=getattr(open_trade, "beta_at_entry", None),
                z_score_at_trigger=getattr(open_trade, "z_score_at_trigger", 0.0),
                upper_wick_atr_at_trigger=getattr(open_trade, "upper_wick_atr_at_trigger", 0.0),
                lower_wick_atr_at_trigger=getattr(open_trade, "lower_wick_atr_at_trigger", 0.0),
                is_20bar_high_at_trigger=getattr(open_trade, "is_20bar_high_at_trigger", 0),
                is_20bar_low_at_trigger=getattr(open_trade, "is_20bar_low_at_trigger", 0),
                move_body_atr_at_trigger=getattr(open_trade, "move_body_atr_at_trigger", 0.0),
                atr_14_at_trigger=getattr(open_trade, "atr_14_at_trigger", None),
                atr_pct_at_trigger=getattr(open_trade, "atr_pct_at_trigger", None),
                sheet_ladder_rung_at_signal=getattr(open_trade, "sheet_ladder_rung_at_signal", 0),
                last_ath_date_at_entry=getattr(open_trade, "last_ath_date_at_entry", ""),
                trading_days_since_last_ath_at_entry=int(
                    getattr(open_trade, "trading_days_since_last_ath_at_entry", 0) or 0
                ),
                high_52w_at_entry=getattr(open_trade, "high_52w_at_entry", None),
                dist_to_52w_high_pct=getattr(open_trade, "dist_to_52w_high_pct", None),
                high_52w_at_trigger=getattr(open_trade, "high_52w_at_trigger", None),
                dist_to_52w_high_pct_at_trigger=getattr(open_trade, "dist_to_52w_high_pct_at_trigger", None),
                had_meteoric_rise_before_entry=int(getattr(open_trade, "had_meteoric_rise_before_entry", 0) or 0),
                had_meteoric_fall_before_entry=int(getattr(open_trade, "had_meteoric_fall_before_entry", 0) or 0),
                spy_compare_1y=getattr(open_trade, "spy_compare_1y", None),
                spy_compare_2y=getattr(open_trade, "spy_compare_2y", None),
                spy_compare_3y=getattr(open_trade, "spy_compare_3y", None),
                spy_ind_diff_at_entry=getattr(open_trade, "spy_ind_diff_at_entry", None),
                entry_indicators=dict(getattr(open_trade, "entry_indicators", None) or {}),
                **_pbr_strength_kwargs_from_trade(open_trade),
            )
            closed.append(t_closed)
            last_exit_yyyymmdd = str(iso).strip().replace("-", "")[:8]
            open_trade = None
            exit_bar = j
            break

        if exit_bar >= 0:
            search_from = exit_bar + 1
            continue
        break

    watchlist = _watchlist_for_symbol(
        sym,
        scanner,
        [],
        cfg,
        n,
        index_iso,
        close_arr,
        open_arr,
        high_arr,
        low_arr,
        None,
        pre=_sym_indicator_pre_rs,
        entry_side=_cfg_entry_side_rs,
        rs_st=st,
        rs_sp=sp,
    )
    return closed, open_trade, scanner, short_candidates, would_have, watchlist


def run_relative_strength_backtest(
    sym: str,
    df: pd.DataFrame,
    cfg: BRTConfig,
    benchmark_df: Optional[pd.DataFrame],
) -> tuple[list[BRTTrade], Optional[BRTTrade], list[dict], list[dict], list[dict], list[dict]]:
    """SPY 252/504/756-bar relative-strength entry scan (no zone/retest stack)."""
    return _run_scan_entry_backtest(sym, df, cfg, benchmark_df, entry_mode="rs")


def run_indicator_only_backtest(
    sym: str,
    df: pd.DataFrame,
    cfg: BRTConfig,
    benchmark_df: Optional[pd.DataFrame],
) -> tuple[list[BRTTrade], Optional[BRTTrade], list[dict], list[dict], list[dict], list[dict]]:
    """IND-only entry scan: trade-aligned IND_DIFF >= indicator_diff at trigger bar close (no zone/retest/RS)."""
    return _run_scan_entry_backtest(sym, df, cfg, benchmark_df, entry_mode="ind")


def _run_alt_entry_backtest_bundle(
    sym: str,
    df: pd.DataFrame,
    cfg: BRTConfig,
    benchmark_df: Optional[pd.DataFrame],
) -> tuple[
    list[BRTTrade],
    Optional[BRTTrade],
    list[dict],
    list[dict],
    list[dict],
    list[dict],
    list[BRTTrade],
]:
    """Run RS or indicator-only backtest; dual-stream when transaction_type=both."""
    _fn = (
        run_relative_strength_backtest
        if bool(getattr(cfg, "relative_strength_enabled", False))
        else run_indicator_only_backtest
    )
    _tt = _normalize_transaction_type(getattr(cfg, "transaction_type", "long"))
    if _tt == "both":
        cfg_long = replace(cfg, entry_type="long", transaction_type="long")
        cfg_short = replace(cfg, entry_type="short", transaction_type="short")
        closed_l, ot_l, scan_l, sc_l, wh_l, wl_l = _fn(sym, df, cfg_long, benchmark_df)
        closed_s, ot_s, scan_s, sc_s, wh_s, wl_s = _fn(sym, df, cfg_short, benchmark_df)
        closed = _merge_closed_dual_streams(closed_l, closed_s)
        scanner = scan_l + scan_s
        short_cands = sc_l + sc_s
        would_have = wh_l + wh_s
        watchlist = _merge_dual_stream_watchlists(wl_l, wl_s, cfg)
        open_trade, extra_open = _dual_bundle_primary_extra_open(ot_l, ot_s)
        return closed, open_trade, scanner, short_cands, would_have, watchlist, extra_open
    closed, open_trade, scanner, short_cands, would_have, watchlist = _fn(sym, df, cfg, benchmark_df)
    return closed, open_trade, scanner, short_cands, would_have, watchlist, []


# ============== DATA LOADING ==============
def load_csv(path: str) -> pd.DataFrame:
    """Load OHLCV CSV. Expects Date, Open, High, Low, Close, (Volume)."""
    df = pd.read_csv(path, low_memory=False)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date", ignore_index=True)
    cols = ["Open", "High", "Low", "Close"]
    for c in cols:
        if c not in df.columns and c.lower() in [x.lower() for x in df.columns]:
            df[c] = df[[x for x in df.columns if x.lower() == c.lower()][0]]
    keep = ["Date"] + [c for c in cols if c in df.columns]
    if "Volume" in df.columns:
        keep.append("Volume")
    df = df[keep]
    df = df.set_index("Date")
    return df


def _load_one_ticker(f: Path) -> tuple[str, pd.DataFrame] | tuple[str, None]:
    """Load a single CSV; return (symbol, df) or (symbol, None) on error."""
    sym = f.stem.upper()
    if sym == "SPY":
        return (sym, None)  # caller skips SPY
    try:
        return (sym, load_csv(str(f)))
    except Exception as e:
        print(f"Skip {f}: {e}", file=sys.stderr)
        return (sym, None)


def load_all_tickers(
    data_dir: str,
    pattern: str = "*.csv",
    max_workers: int | None = 8,
    symbols_filter: set[str] | None = None,
) -> dict[str, pd.DataFrame]:
    """Load all ticker CSVs (skip SPY). Uses ThreadPoolExecutor when max_workers > 1 for faster I/O.

    If ``symbols_filter`` is set (uppercase symbols), only those CSVs are loaded (still skips SPY file).
    """
    data_path = Path(data_dir)
    filt = {s.strip().upper() for s in symbols_filter} if symbols_filter else None
    files = [f for f in data_path.glob(pattern) if f.stem.upper() != "SPY"]
    if filt:
        files = [f for f in files if f.stem.upper() in filt]
    result: dict[str, pd.DataFrame] = {}
    workers = 1 if max_workers is None or max_workers <= 1 else min(max_workers, len(files), 32)
    if workers <= 1:
        for f in files:
            sym, df = _load_one_ticker(f)
            if df is not None:
                result[sym] = df
        return result
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_load_one_ticker, f): f for f in files}
        for fut in as_completed(futures):
            sym, df = fut.result()
            if df is not None:
                result[sym] = df
    return result


def _load_symbol_data(
    sym: str,
    data_dir: Path,
    use_duckdb: bool = False,
    db_path: str = "",
    db_table: str = "prices",
) -> pd.DataFrame | None:
    """Load one symbol from DuckDB when enabled, else CSV."""
    if use_duckdb:
        if _db_load_symbol_df is None or _db_resolve_path is None:
            raise RuntimeError("DuckDB loader is unavailable. Install duckdb and ensure stock_analysis/ohlcv_store.py exists.")
        db_file = db_path or str(_db_resolve_path(data_dir, "", db_table))
        df = _db_load_symbol_df(sym, db_path=db_file, table=db_table)
        return df if df is not None and not df.empty else None
    csv_path = data_dir / f"{sym}.csv"
    if not csv_path.exists():
        return None
    return load_csv(str(csv_path))


def load_all_tickers_source(
    data_dir: str,
    use_duckdb: bool = False,
    db_path: str = "",
    db_table: str = "prices",
    pattern: str = "*.csv",
    max_workers: int | None = 8,
) -> dict[str, pd.DataFrame]:
    """Load all symbols from selected source (CSV or DuckDB)."""
    if not use_duckdb:
        return load_all_tickers(data_dir, pattern=pattern, max_workers=max_workers)
    if _db_list_symbols is None:
        raise RuntimeError("DuckDB loader is unavailable. Install duckdb and ensure stock_analysis/ohlcv_store.py exists.")
    db_file = db_path or str(_db_resolve_path(data_dir, "", db_table))
    symbols = _db_list_symbols(db_path=db_file, table=db_table, include_spy=False)
    symbols = _filter_duckdb_symbols_to_universe(symbols, Path(data_dir))
    out: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        df = _db_load_symbol_df(sym, db_path=db_file, table=db_table)
        if df is not None and not df.empty:
            out[sym] = df
    return out


# ============== OUTPUT FILES ==============
def _hist_stats_for_trade(
    symbol: str,
    date_opened: str,
    closed: list[BRTTrade],
    days_per_year: float = 365.0,
) -> tuple[int, float, float]:
    """Prior trades in same symbol that closed before date_opened. Returns (count, avg_pnl_pct, avg_ann_ror)."""
    dop = str(date_opened).strip().replace("-", "")[:8]
    prior = [c for c in closed if c.symbol == symbol and str(c.date_closed).strip().replace("-", "")[:8] < dop]
    if not prior:
        return 0, 0.0, 0.0
    avg_pnl = sum(c.pnl_pct for c in prior) / len(prior)
    ann_rors = [
        ((1 + c.pnl_pct / 100) ** (days_per_year / c.days_held) - 1) * 100
        for c in prior if c.days_held and c.days_held > 0
    ]
    avg_ann_ror = sum(ann_rors) / len(ann_rors) if ann_rors else 0.0
    return len(prior), avg_pnl, avg_ann_ror


def _precompute_hist_stats(closed: list[BRTTrade], days_per_year: float = 365.0) -> dict[tuple[str, str], tuple[int, float, float]]:
    """Precompute hist stats for all trades in O(n) instead of O(n^2). Returns {(symbol, date_opened): (count, avg_pnl, avg_ann_ror)}."""
    out: dict[tuple[str, str], tuple[int, float, float]] = {}
    # Per-symbol list of (date_closed_yyyymmdd, pnl_pct, days_held), appended in date_closed order
    sym_lists: dict[str, list[tuple[str, float, int]]] = {}
    # Sort by symbol then date_closed so we process in chronological close order
    key = lambda t: (t.symbol, str(t.date_closed).strip().replace("-", "")[:8])
    for t in sorted(closed, key=key):
        dop = str(t.date_opened).strip().replace("-", "")[:8]
        dcl = str(t.date_closed).strip().replace("-", "")[:8]
        lst = sym_lists.setdefault(t.symbol, [])
        prior = [(dc, p, d) for dc, p, d in lst if dc < dop]
        if not prior:
            out[(t.symbol, t.date_opened)] = 0, 0.0, 0.0
        else:
            avg_pnl = sum(p for _, p, _ in prior) / len(prior)
            ann_rors = [
                ((1 + p / 100) ** (days_per_year / d) - 1) * 100
                for _, p, d in prior if d and d > 0
            ]
            avg_ann_ror = sum(ann_rors) / len(ann_rors) if ann_rors else 0.0
            out[(t.symbol, t.date_opened)] = len(prior), avg_pnl, avg_ann_ror
        lst.append((dcl, t.pnl_pct, t.days_held or 0))
    return out


def _normalize_trade_yyyymmdd(date_str: str) -> str:
    return str(date_str or "").strip().replace("-", "")[:8]


def _last_exit_yyyymmdd_fmt(yyyymmdd: str) -> str:
    d = _normalize_trade_yyyymmdd(yyyymmdd)
    if len(d) >= 8:
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    return d


def _symbol_reentry_cooldown_blocks(
    last_exit_yyyymmdd: str,
    entry_yyyymmdd: str,
    cooldown_days: int,
) -> bool:
    """True when entry is too soon after last exit (calendar days). cooldown_days=0 disables."""
    cd = int(cooldown_days or 0)
    if cd <= 0:
        return False
    ex = _normalize_trade_yyyymmdd(last_exit_yyyymmdd)
    ent = _normalize_trade_yyyymmdd(entry_yyyymmdd)
    if len(ex) < 8 or len(ent) < 8:
        return False
    try:
        delta = (pd.Timestamp(ent) - pd.Timestamp(ex)).days
    except Exception:
        return False
    return delta < cd


def _hist_stats_for_symbol(
    closed: list[BRTTrade],
    symbol: str,
    days_per_year: float = 365.0,
) -> tuple[int, float, float]:
    """All closed trades in symbol (for open trades). Returns (count, avg_pnl_pct, avg_ann_ror)."""
    prior = [c for c in closed if c.symbol == symbol]
    if not prior:
        return 0, 0.0, 0.0
    avg_pnl = sum(c.pnl_pct for c in prior) / len(prior)
    ann_rors = [
        ((1 + c.pnl_pct / 100) ** (days_per_year / c.days_held) - 1) * 100
        for c in prior if c.days_held and c.days_held > 0
    ]
    avg_ann_ror = sum(ann_rors) / len(ann_rors) if ann_rors else 0.0
    return len(prior), avg_pnl, avg_ann_ror


_YFINANCE_CACHE_FILENAME = "yfinance_cache.json"


def _yfinance_cache_path() -> Path:
    """Path to local yfinance cache file (repo root)."""
    return Path(__file__).resolve().parent.parent / _YFINANCE_CACHE_FILENAME


def _load_yfinance_cache() -> dict[str, dict]:
    """Load yfinance cache from local file. Returns {symbol: {market_cap, current_price, sector, industry, beta, as_of_date}}."""
    path = _yfinance_cache_path()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_yfinance_cache(cache: dict[str, dict]) -> None:
    """Save yfinance cache to local file."""
    path = _yfinance_cache_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=0)
    except OSError:
        pass


def _yfinance_fetch_symbol_info(sym: str, today: str) -> tuple[str, dict]:
    """One Yahoo quote/info fetch for ``sym``; safe for ThreadPoolExecutor (no shared state)."""
    try:
        import yfinance as yf
    except ImportError:
        return sym, {}
    try:
        ticker = yf.Ticker(sym)
        info = getattr(ticker, "info", None) or {}
        current_price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
        if current_price is not None:
            try:
                current_price = float(current_price)
            except (TypeError, ValueError):
                current_price = None
        return sym, {
            "market_cap": info.get("marketCap"),
            "current_price": current_price,
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "beta": info.get("beta"),
            "as_of_date": today,
        }
    except Exception:
        return sym, {}


def _enrich_trades_yfinance(
    closed: list[BRTTrade],
    open_trades: list[BRTTrade],
    *,
    yfinance_workers: Optional[int] = None,
    pipeline: Optional[Any] = None,
) -> None:
    """Fetch market_cap, sector, industry, beta from yfinance. Uses local cache file to minimize API calls.
    - Check cache first: if we have data with as_of_date=today, use it (no API call).
    - If cache miss or stale (previous day), call yfinance and update cache.
    ``market_cap`` on each trade is scaled toward entry-date notion: raw cap × (entry_price / current_price)
    when both prices exist. ``market_cap_current`` is the raw yfinance marketCap (also in BRT_Summary).

    Network fetches run in parallel (ThreadPoolExecutor) when more than one symbol needs a refresh.
    ``yfinance_workers``: max threads (capped); ``None`` = min(8, CPU count, symbol count). Pass the same
    value as ``-w`` from the CLI when > 0 to align post-run Yahoo throughput with the backtest pool size.
    """
    try:
        import importlib.util

        if importlib.util.find_spec("yfinance") is None:
            return
    except Exception:
        return
    symbols = set()
    for t in closed:
        symbols.add(t.symbol)
    for t in open_trades:
        symbols.add(t.symbol)
    if not symbols:
        return
    today = datetime.now().strftime("%Y-%m-%d")
    file_cache = _load_yfinance_cache()
    # In-memory cache for this run: file_cache + any fresh fetches
    cache: dict[str, dict] = {}
    symbols_to_fetch = []
    for sym in symbols:
        entry = file_cache.get(sym, {})
        as_of = entry.get("as_of_date", "")
        if as_of == today and entry.get("market_cap") is not None:
            cache[sym] = dict(entry)
        else:
            symbols_to_fetch.append(sym)
    n_cached = len(symbols) - len(symbols_to_fetch)
    if n_cached > 0 or symbols_to_fetch:
        print(f"[BRT] yfinance: {n_cached} from cache, {len(symbols_to_fetch)} fetched")
    # Fetch only symbols not in cache or with stale data
    n_to_fetch = len(symbols_to_fetch)
    t_yf_prog = time.perf_counter() if n_to_fetch > 1 else None
    if yfinance_workers is None or yfinance_workers < 1:
        _yf_w = min(8, os.cpu_count() or 4, max(1, n_to_fetch))
    else:
        _yf_w = min(int(yfinance_workers), 24, max(1, n_to_fetch))
    if n_to_fetch > 1 and _yf_w > 1:
        print(f"[BRT] yfinance: fetching with {_yf_w} parallel workers (I/O-bound; Yahoo may still throttle)", flush=True)
        done = 0
        with ThreadPoolExecutor(max_workers=_yf_w) as ex:
            futs = [ex.submit(_yfinance_fetch_symbol_info, sym, today) for sym in symbols_to_fetch]
            for fut in as_completed(futs):
                sym, data = fut.result()
                cache[sym] = data
                done += 1
                if pipeline is not None and getattr(pipeline, "enabled", False):
                    pipeline.post_tick("yfinance_enrich", done, n_to_fetch)
                else:
                    _print_symbol_progress(done, n_to_fetch, t_yf_prog, label="[PROGRESS yfinance]")
    else:
        for i_done, sym in enumerate(symbols_to_fetch, start=1):
            sym2, data = _yfinance_fetch_symbol_info(sym, today)
            cache[sym2] = data
            if pipeline is not None and getattr(pipeline, "enabled", False):
                pipeline.post_tick("yfinance_enrich", i_done, n_to_fetch)
            else:
                _print_symbol_progress(i_done, n_to_fetch, t_yf_prog, label="[PROGRESS yfinance]")
    if n_to_fetch > 1 and sys.stdout.isatty():
        print(file=sys.stdout, flush=True)
    # Persist updated cache (merge file_cache with new fetches)
    if symbols_to_fetch:
        merged = dict(file_cache)
        for sym, data in cache.items():
            if data.get("as_of_date") == today:
                merged[sym] = data
        _save_yfinance_cache(merged)
    # Helper: set market_cap on trade (entry-scaled when prices available), market_cap_current raw from feed
    def _set_market_cap_and_rest(trade: BRTTrade, c: dict) -> None:
        mc = c.get("market_cap")
        if mc is not None:
            try:
                mc_raw = float(mc)
                setattr(trade, "market_cap_current", mc_raw)
                mc_float = mc_raw
                curr_pr = c.get("current_price")
                if curr_pr and curr_pr > 0 and getattr(trade, "entry_price", 0) and trade.entry_price > 0:
                    mc_float = mc_float * (trade.entry_price / curr_pr)
                setattr(trade, "market_cap", mc_float)
            except (TypeError, ValueError):
                pass
        if c.get("sector") is not None:
            setattr(trade, "sector", str(c["sector"]))
        if c.get("industry") is not None:
            setattr(trade, "industry", str(c["industry"]))
        if c.get("beta") is not None:
            try:
                setattr(trade, "beta", float(c["beta"]))
            except (TypeError, ValueError):
                pass
    for t in closed:
        c = cache.get(t.symbol, {})
        _set_market_cap_and_rest(t, c)
    for t in open_trades:
        c = cache.get(t.symbol, {})
        _set_market_cap_and_rest(t, c)


def _write_would_have_csv(entries: list[dict], path: str) -> None:
    """Write BRT_WouldHave CSV: SYMBOL, MATURITY_DATE, ZONE_CENTER, WOULD_ENTER_DATE, REJECT_REASON."""
    if not entries:
        return
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["SYMBOL", "MATURITY_DATE", "ZONE_CENTER", "WOULD_ENTER_DATE", "REJECT_REASON"])
        for row in entries:
            w.writerow([
                row.get("SYMBOL", ""),
                row.get("MATURITY_DATE", ""),
                row.get("ZONE_CENTER", ""),
                row.get("WOULD_ENTER_DATE", ""),
                row.get("REJECT_REASON", ""),
            ])


def _brt_indicator_header_suffix(cfg: Optional[BRTConfig]) -> list[str]:
    if cfg is None or not _indicator_mode_active(cfg):
        return []
    try:
        from brt_entry_indicators import entry_indicator_csv_headers
    except ImportError:
        from stock_analysis.brt_entry_indicators import entry_indicator_csv_headers
    return entry_indicator_csv_headers()


def _brt_indicator_row_suffix(cfg: Optional[BRTConfig], t: BRTTrade) -> list[str]:
    if cfg is None or not _indicator_mode_active(cfg):
        return []
    try:
        from brt_entry_indicators import format_indicator_csv_row
    except ImportError:
        from stock_analysis.brt_entry_indicators import format_indicator_csv_row
    return format_indicator_csv_row(getattr(t, "entry_indicators", None) or {})


def _enrich_trades_entry_indicators(
    trades: list[BRTTrade],
    tickers: Optional[dict[str, pd.DataFrame]],
    cfg: BRTConfig,
    pipeline: Optional[Any] = None,
    workers: int = 0,
) -> None:
    if not bool(getattr(cfg, "use_indicators", False)) or not trades:
        return
    try:
        from brt_entry_indicators import enrich_trades_entry_indicators, trades_need_indicator_enrichment
    except ImportError:
        from stock_analysis.brt_entry_indicators import enrich_trades_entry_indicators, trades_need_indicator_enrichment

    if not trades_need_indicator_enrichment(trades):
        print(
            "[BRT] entry_indicators: skipped post-pass (snapshots already set during backtest)",
            flush=True,
        )
        if pipeline is not None and getattr(pipeline, "enabled", False):
            pipeline.complete_phase_units("entry_indicators")
        return

    def _prog(done: int, total: int, _sym: str) -> None:
        if pipeline is not None and getattr(pipeline, "enabled", False):
            pipeline.post_tick("entry_indicators", done, total)

    enrich_trades_entry_indicators(
        trades,
        tickers or {},
        bool(getattr(cfg, "use_indicators", False)),
        progress_callback=_prog if pipeline is not None else None,
        workers=workers,
        cache_dir=(str(getattr(cfg, "indicator_cache_dir", "") or "").strip() or None),
        use_cache=bool(getattr(cfg, "indicator_cache", True)),
    )


def _pbr_strength_csv_header() -> list[str]:
    try:
        from pbr_zones import PBR_STRENGTH_FIELDS
    except ImportError:
        from stock_analysis.pbr_zones import PBR_STRENGTH_FIELDS
    return [f.upper() for f in PBR_STRENGTH_FIELDS]


def _pbr_strength_csv_row(t: "BRTTrade") -> list[str]:
    try:
        from pbr_zones import PBR_STRENGTH_FIELDS
    except ImportError:
        from stock_analysis.pbr_zones import PBR_STRENGTH_FIELDS
    out: list[str] = []
    for field in PBR_STRENGTH_FIELDS:
        v = getattr(t, field, None)
        if v is None:
            out.append("")
        else:
            try:
                fv = float(v)
                if not np.isfinite(fv):
                    out.append("")
                else:
                    out.append(f"{fv:.6f}")
            except (TypeError, ValueError):
                out.append("")
    return out


def _apply_pbr_strength_to_trade(trade: "BRTTrade", meta: dict) -> None:
    """Copy PBR strength metrics from zone event metadata onto a trade."""
    if not meta:
        return
    try:
        from pbr_zones import PBR_STRENGTH_FIELDS
    except ImportError:
        from stock_analysis.pbr_zones import PBR_STRENGTH_FIELDS
    for field in PBR_STRENGTH_FIELDS:
        v = meta.get(field)
        if v is None:
            continue
        try:
            fv = float(v)
            if np.isfinite(fv):
                setattr(trade, field, fv)
        except (TypeError, ValueError):
            pass


def _pbr_strength_kwargs_from_trade(trade: "BRTTrade") -> dict[str, float]:
    """Snapshot PBR strength fields for closed-trade construction."""
    try:
        from pbr_zones import PBR_STRENGTH_FIELDS
    except ImportError:
        from stock_analysis.pbr_zones import PBR_STRENGTH_FIELDS
    out: dict[str, float] = {}
    for field in PBR_STRENGTH_FIELDS:
        v = getattr(trade, field, None)
        if v is None:
            continue
        try:
            fv = float(v)
            if np.isfinite(fv):
                out[field] = fv
        except (TypeError, ValueError):
            pass
    return out


def write_brt_closed(
    closed: list[BRTTrade],
    path: str,
    reference_stats: Optional[dict[str, tuple[float, float]]] = None,
    cfg: Optional[BRTConfig] = None,
) -> None:
    DAYS_PER_YEAR = 365.0
    include_zscore_cols = reference_stats is not None and len(reference_stats) > 0
    z_cols = [f"Z_{ref_name}" for ref_name in _REF_VAR_TO_ATTR] if include_zscore_cols else []
    if include_zscore_cols and cfg is not None:
        z_cols.append("REALTIME_SCORE")

    # Precompute hist stats in O(n) when many trades (avoids O(n^2) per-trade filtering)
    hist_cache = _precompute_hist_stats(closed, DAYS_PER_YEAR) if len(closed) > 100 else None
    ind_h = _brt_indicator_header_suffix(cfg)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        header = [
            "SYMBOL", "SIDE", "DATE_OPENED", "ENTRY_PRICE", "STOP_PRICE", "TARGET_PRICE",
            "DATE_CLOSED", "EXIT_PRICE", "EXIT_TYPE", "DAYS_HELD", "PNL_PCT", "PNL_DOLLARS",
            "ANN_ROR_PCT", "MAX_PRICE", "POST_ENTRY_GAIN_HIT",
            "DATE_FIRST_UP_10PCT", "DAYS_HELD_FIRST_UP_10PCT",
            "DATE_FIRST_UP_20PCT", "DAYS_HELD_FIRST_UP_20PCT",
            "HIST_TRADES", "HIST_PNL_PCT_AVG", "HIST_ANN_ROR_AVG",
            "ZONE_CENTER", "PBR_ZONE_ID",
        ] + _pbr_strength_csv_header() + [
            "TOUCH_COUNT", "TOUCH_COUNT_SHORT", "TOUCH_COUNT_MAJOR", "TOUCH_COUNT_MINOR", "IS_TRADEABLE_KEY_LEVEL_AC",
            "ZONE_ROLLING_TOUCHES", "SUPPORT_TEST_COUNT", "SUPPORT_TEST_AT_SIGNAL",
            "TOUCH_COUNT_AT_MATURITY", "TOUCH_COUNT_SHORT_AT_MATURITY", "ZONE_EPISODE_DN", "DAYS_SINCE_MATURITY",
            "STRUCT_HIGH", "STRUCT_LOW",
            "ENTRY_PIVOT_TYPE", "ENTRY_STRUCT_REGIME", "ENTRY_MAJOR_PIVOT", "ENTRY_PIVOT_WAS_STRONG", "ENTRY_ZONE_WAS_STRONG_PIVOT",
            "NEARBY_ZONES_ABOVE", "NEARBY_ZONES_BELOW", "ZONE_CLUSTER_DENSITY",
            "MATURITY_DATE", "CLOSE_ABOVE_DATE", "BREAKOUT_DATE", "DAYS_SINCE_BREAKOUT", "SHEET_LADDER_RUNG",
            "GROWTH_PCT_OVER_PERIOD",
            "DISPLACEMENT_PCT_AT_ENTRY",
            "PIVOT_RUN_H_BEFORE_ENTRY", "PIVOT_RUN_L_BEFORE_ENTRY", "PIVOT_SWITCH_H_TO_L",
            "ZONE_ABOVE_CENTER", "ZONE_BELOW_CENTER",
            "PCT_ENTRY_TO_BOTTOM_ZONE_ABOVE", "PCT_DROP_TO_TOP_ZONE_BELOW",
            "VOLUME_AT_ENTRY", "AVG_VOLUME_10D_AT_ENTRY", "REL_VOL_AT_ENTRY", "REL_VOL_ON_TRIGGER",
            "REJECTION_COUNT_PRIOR", "OVERLAPPING_MATURE_ZONES_COUNT", "REL_VOL_AT_BREAKOUT",
            "ATR_14_AT_ENTRY", "ATR_PCT_AT_ENTRY",
            "MARKET_CAP", "SECTOR", "INDUSTRY", "BETA", "BETA_AT_ENTRY",
            "LAST_ATH_DATE_AT_ENTRY", "TRADING_DAYS_SINCE_LAST_ATH_AT_ENTRY",
            "HIGH_52W_AT_ENTRY", "DIST_TO_52W_HIGH_PCT",
            "HIGH_52W_AT_TRIGGER", "DIST_TO_52W_HIGH_PCT_AT_TRIGGER",
            "HAD_METEORIC_RISE_BEFORE_ENTRY", "HAD_METEORIC_FALL_BEFORE_ENTRY",
            "Z_SCORE_AT_TRIGGER", "UPPER_WICK_ATR_AT_TRIGGER", "LOWER_WICK_ATR_AT_TRIGGER",
            "IS_20BAR_HIGH_AT_TRIGGER", "IS_20BAR_LOW_AT_TRIGGER", "MOVE_BODY_ATR_AT_TRIGGER",
            "ATR_14_AT_TRIGGER", "ATR_PCT_AT_TRIGGER",
            "SPY_COMPARE_1Y", "SPY_COMPARE_2Y", "SPY_COMPARE_3Y", "SPY_IND_DIFF",
        ]
        if z_cols:
            header = header + z_cols
        header = header + ind_h
        w.writerow(header)
        for t in closed:
            md = getattr(t, "maturity_date", "") or ""
            cd = getattr(t, "close_above_date", "") or ""
            bd = getattr(t, "breakout_date", "") or ""
            dsb = getattr(t, "days_since_breakout", None)
            if hist_cache is not None:
                hist_n, hist_avg, hist_ann_ror = hist_cache.get((t.symbol, t.date_opened), (0, 0.0, 0.0))
            else:
                hist_n, hist_avg, hist_ann_ror = _hist_stats_for_trade(t.symbol, t.date_opened, closed)
            # Annualized ROR per trade: (1 + pnl_pct/100)^(365/days_held) - 1
            if t.days_held and t.days_held > 0:
                ann_ror = ((1 + t.pnl_pct / 100) ** (DAYS_PER_YEAR / t.days_held) - 1) * 100
                ann_ror_str = f"{ann_ror:.2f}%"
            else:
                ann_ror_str = ""
            max_price = getattr(t, "max_price", 0.0) or t.entry_price
            max_price_str = f"{max_price:.2f}"
            gp = getattr(t, "growth_pct_over_period", None)
            growth_str = f"{gp:.2f}" if gp is not None else ""
            dp = getattr(t, "displacement_pct_at_entry", None)
            displacement_str = f"{dp:.4f}" if dp is not None else ""
            atr_raw = getattr(t, "atr_14_at_entry", None)
            atr_str = f"{atr_raw:.4f}" if atr_raw is not None else ""
            atr_pct_str = ""
            if atr_raw is not None and getattr(t, "entry_price", 0) and t.entry_price > 0:
                atr_pct_str = f"{(atr_raw / t.entry_price) * 100.0:.2f}%"
            row = [
                t.symbol, (getattr(t, "side", "LONG") or "LONG"), t.date_opened, f"{t.entry_price:.2f}", f"{t.stop_price:.2f}", f"{t.target_price:.2f}",
                t.date_closed, f"{t.exit_price:.2f}", t.exit_type, t.days_held, f"{t.pnl_pct:.2f}%", f"{t.pnl_dollars:.2f}",
                ann_ror_str, max_price_str,
                int(getattr(t, "post_entry_gain_hit", 0) or 0),
                getattr(t, "date_first_up_10pct", "") or "",
                int(getattr(t, "days_held_first_up_10pct", 0) or 0),
                getattr(t, "date_first_up_20pct", "") or "",
                int(getattr(t, "days_held_first_up_20pct", 0) or 0),
                hist_n, f"{hist_avg:.2f}" if hist_n else "", f"{hist_ann_ror:.2f}" if hist_n else "",
                f"{t.zone_center:.4f}",
                str(getattr(t, "pbr_zone_id", "") or ""),
            ] + _pbr_strength_csv_row(t) + [
                t.touch_count, t.touch_count_short, t.touch_count_major, t.touch_count_minor, 1 if t.is_tradeable_key_level else 0,
                int(getattr(t, "zone_rolling_touches", 0) or 0),
                int(getattr(t, "support_test_count", 0) or 0),
                int(getattr(t, "support_test_at_signal", 0) or 0),
                int(getattr(t, "touch_count_at_maturity", 0) or 0),
                int(getattr(t, "touch_count_short_at_maturity", 0) or 0),
                int(getattr(t, "zone_episode_dn", 0) or 0),
                int(getattr(t, "days_since_maturity", 0) or 0),
                t.struct_high, t.struct_low,
                t.entry_pivot_type, t.entry_struct_regime, t.entry_major_pivot, getattr(t, "entry_pivot_was_strong", 0), getattr(t, "entry_zone_was_strong_pivot", 0),
                t.nearby_zones_above, t.nearby_zones_below, t.zone_cluster_density,
                md, cd, bd, int(dsb) if dsb is not None else "",
                int(getattr(t, "sheet_ladder_rung_at_signal", 0) or 0),
                growth_str,
                displacement_str,
                getattr(t, "pivot_run_high", 0),
                getattr(t, "pivot_run_low", 0),
                1 if getattr(t, "pivot_switch_h_to_l", False) else 0,
                f"{getattr(t, 'zone_above_center', 0):.4f}" if getattr(t, "zone_above_center", 0) else "",
                f"{getattr(t, 'zone_below_center', 0):.4f}" if getattr(t, "zone_below_center", 0) else "",
                f"{getattr(t, 'pct_entry_to_bottom_zone_above', 0):.2f}" if getattr(t, "zone_above_center", 0) else "",
                f"{getattr(t, 'pct_drop_to_top_zone_below', 0):.2f}" if getattr(t, "zone_below_center", 0) else "",
                f"{getattr(t, 'volume_at_entry', None):.0f}" if getattr(t, "volume_at_entry", None) is not None else "",
                f"{getattr(t, 'avg_volume_10d_at_entry', None):.0f}" if getattr(t, "avg_volume_10d_at_entry", None) is not None else "",
                f"{getattr(t, 'rel_vol_at_entry', None):.4f}" if getattr(t, "rel_vol_at_entry", None) is not None else "",
                f"{getattr(t, 'rel_vol_on_trigger', None):.4f}" if getattr(t, "rel_vol_on_trigger", None) is not None else "",
                int(getattr(t, "rejection_count_prior", None) or getattr(t, "resistance_touch_count_prior", 0) or 0),
                int(getattr(t, "overlapping_mature_zones_count", 0) or 0),
                f"{getattr(t, 'rel_vol_at_breakout', None):.4f}" if getattr(t, "rel_vol_at_breakout", None) is not None else "",
                atr_str, atr_pct_str,
                f"{getattr(t, 'market_cap', None):.0f}" if getattr(t, "market_cap", None) is not None else "",
                (getattr(t, "sector", None) or "").replace(",", " "),
                (getattr(t, "industry", None) or "").replace(",", " "),
                f"{getattr(t, 'beta', None):.4f}" if getattr(t, "beta", None) is not None else "",
                f"{getattr(t, 'beta_at_entry', None):.4f}" if getattr(t, "beta_at_entry", None) is not None else "",
                getattr(t, "last_ath_date_at_entry", "") or "",
                int(getattr(t, "trading_days_since_last_ath_at_entry", 0) or 0),
                f"{getattr(t, 'high_52w_at_entry'):.2f}"
                if getattr(t, "high_52w_at_entry", None) is not None
                else "",
                f"{getattr(t, 'dist_to_52w_high_pct'):.2f}%"
                if getattr(t, "dist_to_52w_high_pct", None) is not None
                else "",
                f"{getattr(t, 'high_52w_at_trigger'):.2f}"
                if getattr(t, "high_52w_at_trigger", None) is not None
                else "",
                f"{getattr(t, 'dist_to_52w_high_pct_at_trigger'):.2f}%"
                if getattr(t, "dist_to_52w_high_pct_at_trigger", None) is not None
                else "",
                int(getattr(t, "had_meteoric_rise_before_entry", 0) or 0),
                int(getattr(t, "had_meteoric_fall_before_entry", 0) or 0),
                f"{getattr(t, 'z_score_at_trigger', 0.0):.4f}",
                f"{getattr(t, 'upper_wick_atr_at_trigger', 0.0):.4f}",
                f"{getattr(t, 'lower_wick_atr_at_trigger', 0.0):.4f}",
                int(getattr(t, 'is_20bar_high_at_trigger', 0)),
                int(getattr(t, 'is_20bar_low_at_trigger', 0)),
                f"{getattr(t, 'move_body_atr_at_trigger', 0.0):.4f}",
                f"{getattr(t, 'atr_14_at_trigger'):.4f}"
                if getattr(t, "atr_14_at_trigger", None) is not None
                else "",
                f"{getattr(t, 'atr_pct_at_trigger'):.2f}%"
                if getattr(t, "atr_pct_at_trigger", None) is not None
                else "",
                f"{getattr(t, 'spy_compare_1y', None):.4f}" if getattr(t, "spy_compare_1y", None) is not None else "",
                f"{getattr(t, 'spy_compare_2y', None):.4f}" if getattr(t, "spy_compare_2y", None) is not None else "",
                f"{getattr(t, 'spy_compare_3y', None):.4f}" if getattr(t, "spy_compare_3y", None) is not None else "",
                int(getattr(t, "spy_ind_diff_at_entry")) if getattr(t, "spy_ind_diff_at_entry", None) is not None else "",
            ]
            if include_zscore_cols and reference_stats:
                for ref_name in _REF_VAR_TO_ATTR:
                    attr = _REF_VAR_TO_ATTR[ref_name]
                    val = getattr(t, attr, None)
                    z = _realtime_score_value(val, ref_name, reference_stats, True)
                    row.append(f"{z:.4f}")
                if cfg is not None:
                    row.append(f"{_realtime_score_for_trade(t, cfg, reference_stats):.4f}")
            row.extend(_brt_indicator_row_suffix(cfg, t))
            w.writerow(row)


def _open_trade_mtm(t: BRTTrade, df: pd.DataFrame, brt_cash: float) -> tuple[str, int, str, str, str, str]:
    """Compute mark-to-market for an open trade: current_price, days_held, pnl_pct, pnl_dollars, ann_ror_pct, max_price. Uses latest bar as 'today'."""
    DAYS_PER_YEAR = 365.0
    try:
        if df is None or df.empty or "Close" not in df.columns or "High" not in df.columns:
            return ("", 0, "", "", "", "")
        # date_opened is YYYYMMDD
        s = str(t.date_opened).strip().replace("-", "")[:8]
        if len(s) != 8:
            return ("", 0, "", "", "", "")
        entry_ts = pd.Timestamp(s[:4] + "-" + s[4:6] + "-" + s[6:8])
        mask = df.index >= entry_ts
        if not mask.any():
            return ("", 0, "", "", "", "")
        current_price = float(df.loc[mask, "Close"].iloc[-1])
        days_held = (df.index[mask][-1] - entry_ts).days
        max_price = float(df.loc[mask, "High"].max())
        if t.entry_price <= 0:
            return (f"{current_price:.2f}", days_held, "", "", "", f"{max_price:.2f}")
        _is_long = str(getattr(t, "side", "LONG") or "LONG").upper() != "SHORT"
        pnl_move = (current_price - t.entry_price) if _is_long else (t.entry_price - current_price)
        pnl_pct = (pnl_move / t.entry_price) * 100.0
        pnl_dollars = (brt_cash / t.entry_price) * pnl_move
        pnl_pct_str = f"{pnl_pct:.2f}%"
        pnl_dollars_str = f"{pnl_dollars:.2f}"
        max_price_str = f"{max_price:.2f}"
        if days_held and days_held > 0:
            ann_ror = ((1 + pnl_pct / 100) ** (DAYS_PER_YEAR / days_held) - 1) * 100
            ann_ror_str = f"{ann_ror:.2f}%"
        else:
            ann_ror_str = ""
        return (f"{current_price:.2f}", days_held, pnl_pct_str, pnl_dollars_str, ann_ror_str, max_price_str)
    except Exception:
        return ("", 0, "", "", "", "")


def write_brt_open(
    open_trades: list[BRTTrade],
    path: str,
    tickers: Optional[dict[str, pd.DataFrame]] = None,
    brt_cash: float = 0.0,
    closed: Optional[list[BRTTrade]] = None,
    cfg: Optional[BRTConfig] = None,
) -> None:
    """Write BRT_Open CSV. No DATE_CLOSED/EXIT_PRICE/EXIT_TYPE. CURRENT_PRICE, DAYS_HELD, PNL_*, ANN_ROR_PCT, MAX_PRICE computed from latest data when tickers/brt_cash provided. HIST_* from closed when provided."""
    ind_h = _brt_indicator_header_suffix(cfg)
    _band_pct_fb = float(getattr(cfg, "band_pct", 0.017) or 0.017) if cfg is not None else 0.017

    def _open_zone_band(t: BRTTrade) -> tuple[float, float]:
        zl = float(getattr(t, "zone_low", 0) or 0)
        zh = float(getattr(t, "zone_high", 0) or 0)
        if zl > 0 and zh > zl:
            return zl, zh
        zc = float(getattr(t, "zone_center", 0) or 0)
        if zc > 0:
            return zc * (1.0 - _band_pct_fb), zc * (1.0 + _band_pct_fb)
        return zl, zh

    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "SYMBOL", "SIDE", "DATE_OPENED", "ENTRY_PRICE", "STOP_PRICE", "TARGET_PRICE",
            "ZONE_CENTER", "ZONE_LOW", "ZONE_HIGH", "PBR_ZONE_ID",
        ] + _pbr_strength_csv_header() + [
            "CURRENT_PRICE", "DAYS_HELD", "PNL_PCT", "PNL_DOLLARS", "ANN_ROR_PCT", "MAX_PRICE", "POST_ENTRY_GAIN_HIT",
            "HIST_TRADES", "HIST_PNL_PCT_AVG", "HIST_ANN_ROR_AVG",
            "TOUCH_COUNT", "TOUCH_COUNT_SHORT", "TOUCH_COUNT_MAJOR", "TOUCH_COUNT_MINOR", "IS_TRADEABLE_KEY_LEVEL_AC",
            "ZONE_ROLLING_TOUCHES", "SUPPORT_TEST_COUNT", "SUPPORT_TEST_AT_SIGNAL",
            "TOUCH_COUNT_AT_MATURITY", "TOUCH_COUNT_SHORT_AT_MATURITY", "ZONE_EPISODE_DN", "DAYS_SINCE_MATURITY",
            "STRUCT_HIGH", "STRUCT_LOW",
            "ENTRY_PIVOT_TYPE", "ENTRY_STRUCT_REGIME", "ENTRY_MAJOR_PIVOT", "ENTRY_PIVOT_WAS_STRONG", "ENTRY_ZONE_WAS_STRONG_PIVOT",
            "NEARBY_ZONES_ABOVE", "NEARBY_ZONES_BELOW", "ZONE_CLUSTER_DENSITY",
            "MATURITY_DATE", "CLOSE_ABOVE_DATE", "BREAKOUT_DATE", "DAYS_SINCE_BREAKOUT", "SHEET_LADDER_RUNG",
            "GROWTH_PCT_OVER_PERIOD",
            "DISPLACEMENT_PCT_AT_ENTRY",
            "PIVOT_RUN_H_BEFORE_ENTRY", "PIVOT_RUN_L_BEFORE_ENTRY", "PIVOT_SWITCH_H_TO_L",
            "ZONE_ABOVE_CENTER", "ZONE_BELOW_CENTER",
            "PCT_ENTRY_TO_BOTTOM_ZONE_ABOVE", "PCT_DROP_TO_TOP_ZONE_BELOW",
            "VOLUME_AT_ENTRY", "AVG_VOLUME_10D_AT_ENTRY", "REL_VOL_AT_ENTRY", "REL_VOL_ON_TRIGGER",
            "REJECTION_COUNT_PRIOR", "OVERLAPPING_MATURE_ZONES_COUNT", "REL_VOL_AT_BREAKOUT",
            "ATR_14_AT_ENTRY", "ATR_PCT_AT_ENTRY",
            "MARKET_CAP", "SECTOR", "INDUSTRY", "BETA", "BETA_AT_ENTRY",
            "LAST_ATH_DATE_AT_ENTRY", "TRADING_DAYS_SINCE_LAST_ATH_AT_ENTRY",
            "HIGH_52W_AT_ENTRY", "DIST_TO_52W_HIGH_PCT",
            "HIGH_52W_AT_TRIGGER", "DIST_TO_52W_HIGH_PCT_AT_TRIGGER",
            "HAD_METEORIC_RISE_BEFORE_ENTRY", "HAD_METEORIC_FALL_BEFORE_ENTRY",
            "Z_SCORE_AT_TRIGGER", "UPPER_WICK_ATR_AT_TRIGGER", "LOWER_WICK_ATR_AT_TRIGGER",
            "IS_20BAR_HIGH_AT_TRIGGER", "IS_20BAR_LOW_AT_TRIGGER", "MOVE_BODY_ATR_AT_TRIGGER",
            "ATR_14_AT_TRIGGER", "ATR_PCT_AT_TRIGGER",
            "SPY_COMPARE_1Y", "SPY_COMPARE_2Y", "SPY_COMPARE_3Y", "SPY_IND_DIFF",
        ] + ind_h)
        for t in open_trades:
            md = getattr(t, "maturity_date", "") or ""
            cd = getattr(t, "close_above_date", "") or ""
            bd = getattr(t, "breakout_date", "") or ""
            dsb = getattr(t, "days_since_breakout", None)
            hist_n, hist_avg, hist_ann_ror = _hist_stats_for_symbol(closed, t.symbol) if closed else (0, 0.0, 0.0)
            gp = getattr(t, "growth_pct_over_period", None)
            growth_str = f"{gp:.2f}" if gp is not None else ""
            dp = getattr(t, "displacement_pct_at_entry", None)
            displacement_str = f"{dp:.4f}" if dp is not None else ""
            za = getattr(t, "zone_above_center", 0) or 0
            zb = getattr(t, "zone_below_center", 0) or 0
            pct_above = f"{getattr(t, 'pct_entry_to_bottom_zone_above', 0):.2f}" if za else ""
            pct_below = f"{getattr(t, 'pct_drop_to_top_zone_below', 0):.2f}" if zb else ""
            if tickers and brt_cash and t.symbol in tickers:
                cur_pr, days_held, pnl_pct_s, pnl_dollars_s, ann_ror_s, max_pr_s = _open_trade_mtm(t, tickers[t.symbol], brt_cash)
            else:
                cur_pr, days_held, pnl_pct_s, pnl_dollars_s, ann_ror_s, max_pr_s = "", 0, "", "", "", ""
            atr_raw = getattr(t, "atr_14_at_entry", None)
            atr_str = f"{atr_raw:.4f}" if atr_raw is not None else ""
            atr_pct_str = ""
            if atr_raw is not None and getattr(t, "entry_price", 0) and t.entry_price > 0:
                atr_pct_str = f"{(atr_raw / t.entry_price) * 100.0:.2f}%"
            zl_o, zh_o = _open_zone_band(t)
            w.writerow(
                [
                t.symbol, (getattr(t, "side", "LONG") or "LONG"), t.date_opened, f"{t.entry_price:.2f}", f"{t.stop_price:.2f}", f"{t.target_price:.2f}",
                f"{t.zone_center:.4f}" if t.zone_center else "",
                f"{zl_o:.4f}" if zl_o > 0 else "",
                f"{zh_o:.4f}" if zh_o > 0 else "",
                str(getattr(t, "pbr_zone_id", "") or ""),
            ] + _pbr_strength_csv_row(t) + [
                cur_pr, days_held, pnl_pct_s, pnl_dollars_s, ann_ror_s, max_pr_s,
                int(getattr(t, "post_entry_gain_hit", 0) or 0),
                hist_n, f"{hist_avg:.2f}" if hist_n else "", f"{hist_ann_ror:.2f}" if hist_n else "",
                t.touch_count, t.touch_count_short, t.touch_count_major, t.touch_count_minor, 1 if t.is_tradeable_key_level else 0,
                int(getattr(t, "zone_rolling_touches", 0) or 0),
                int(getattr(t, "support_test_count", 0) or 0),
                int(getattr(t, "support_test_at_signal", 0) or 0),
                int(getattr(t, "touch_count_at_maturity", 0) or 0),
                int(getattr(t, "touch_count_short_at_maturity", 0) or 0),
                int(getattr(t, "zone_episode_dn", 0) or 0),
                int(getattr(t, "days_since_maturity", 0) or 0),
                t.struct_high, t.struct_low,
                t.entry_pivot_type, t.entry_struct_regime, t.entry_major_pivot, getattr(t, "entry_pivot_was_strong", 0), getattr(t, "entry_zone_was_strong_pivot", 0),
                t.nearby_zones_above, t.nearby_zones_below, t.zone_cluster_density,
                md, cd, bd, int(dsb) if dsb is not None else "",
                int(getattr(t, "sheet_ladder_rung_at_signal", 0) or 0),
                growth_str,
                displacement_str,
                getattr(t, "pivot_run_high", 0),
                getattr(t, "pivot_run_low", 0),
                1 if getattr(t, "pivot_switch_h_to_l", False) else 0,
                f"{za:.4f}" if za else "", f"{zb:.4f}" if zb else "",
                pct_above, pct_below,
                f"{getattr(t, 'volume_at_entry', None):.0f}" if getattr(t, "volume_at_entry", None) is not None else "",
                f"{getattr(t, 'avg_volume_10d_at_entry', None):.0f}" if getattr(t, "avg_volume_10d_at_entry", None) is not None else "",
                f"{getattr(t, 'rel_vol_at_entry', None):.4f}" if getattr(t, "rel_vol_at_entry", None) is not None else "",
                f"{getattr(t, 'rel_vol_on_trigger', None):.4f}" if getattr(t, "rel_vol_on_trigger", None) is not None else "",
                int(getattr(t, "rejection_count_prior", None) or getattr(t, "resistance_touch_count_prior", 0) or 0),
                int(getattr(t, "overlapping_mature_zones_count", 0) or 0),
                f"{getattr(t, 'rel_vol_at_breakout', None):.4f}" if getattr(t, "rel_vol_at_breakout", None) is not None else "",
                atr_str, atr_pct_str,
                f"{getattr(t, 'market_cap', None):.0f}" if getattr(t, "market_cap", None) is not None else "",
                (getattr(t, "sector", None) or "").replace(",", " "),
                (getattr(t, "industry", None) or "").replace(",", " "),
                f"{getattr(t, 'beta', None):.4f}" if getattr(t, "beta", None) is not None else "",
                f"{getattr(t, 'beta_at_entry', None):.4f}" if getattr(t, "beta_at_entry", None) is not None else "",
                getattr(t, "last_ath_date_at_entry", "") or "",
                int(getattr(t, "trading_days_since_last_ath_at_entry", 0) or 0),
                f"{getattr(t, 'high_52w_at_entry'):.2f}"
                if getattr(t, "high_52w_at_entry", None) is not None
                else "",
                f"{getattr(t, 'dist_to_52w_high_pct'):.2f}%"
                if getattr(t, "dist_to_52w_high_pct", None) is not None
                else "",
                f"{getattr(t, 'high_52w_at_trigger'):.2f}"
                if getattr(t, "high_52w_at_trigger", None) is not None
                else "",
                f"{getattr(t, 'dist_to_52w_high_pct_at_trigger'):.2f}%"
                if getattr(t, "dist_to_52w_high_pct_at_trigger", None) is not None
                else "",
                int(getattr(t, "had_meteoric_rise_before_entry", 0) or 0),
                int(getattr(t, "had_meteoric_fall_before_entry", 0) or 0),
                f"{getattr(t, 'z_score_at_trigger', 0.0):.4f}",
                f"{getattr(t, 'upper_wick_atr_at_trigger', 0.0):.4f}",
                f"{getattr(t, 'lower_wick_atr_at_trigger', 0.0):.4f}",
                int(getattr(t, 'is_20bar_high_at_trigger', 0)),
                int(getattr(t, 'is_20bar_low_at_trigger', 0)),
                f"{getattr(t, 'move_body_atr_at_trigger', 0.0):.4f}",
                f"{getattr(t, 'atr_14_at_trigger'):.4f}"
                if getattr(t, "atr_14_at_trigger", None) is not None
                else "",
                f"{getattr(t, 'atr_pct_at_trigger'):.2f}%"
                if getattr(t, "atr_pct_at_trigger", None) is not None
                else "",
                f"{getattr(t, 'spy_compare_1y', None):.4f}" if getattr(t, "spy_compare_1y", None) is not None else "",
                f"{getattr(t, 'spy_compare_2y', None):.4f}" if getattr(t, "spy_compare_2y", None) is not None else "",
                f"{getattr(t, 'spy_compare_3y', None):.4f}" if getattr(t, "spy_compare_3y", None) is not None else "",
                int(getattr(t, "spy_ind_diff_at_entry")) if getattr(t, "spy_ind_diff_at_entry", None) is not None else "",
                ]
                + _brt_indicator_row_suffix(cfg, t)
            )


# Watchlist APPROACHING_RETEST: fixed heuristics (no config knobs).
_WATCHLIST_BR_MAX_BARS_AFTER_BREAKOUT = 504
_WATCHLIST_ZONE_EDGE_PROXIMITY_FRAC = 0.04  # within 4% of zone band (by price) or inside band

_IND_WL_ROW_RANK = {
    "SCANNER": 0,
    "NEAR_GATE": 1,
    "IMPROVING": 2,
    "FADING": 3,
    "STALLED": 4,
}


def _cfg_float_param(cfg: BRTConfig, name: str, default: float) -> float:
    """Read a numeric config field; unlike ``float(x or default)``, preserves 0 and negative values."""
    if not hasattr(cfg, name):
        return default
    v = getattr(cfg, name)
    if v is None:
        return default
    return float(v)


def _cfg_min_atr_pct_trigger(cfg: BRTConfig) -> float:
    return float(getattr(cfg, "min_atr_pct_at_trigger", 0.0) or 0.0)


def _cfg_max_atr_pct_trigger(cfg: BRTConfig) -> float:
    return float(getattr(cfg, "max_atr_pct_at_trigger", 0.0) or 0.0)


def _cfg_min_dist_52w_high_pct_at_trigger(cfg: BRTConfig) -> float:
    return float(getattr(cfg, "min_dist_to_52w_high_pct_at_trigger", 0.0) or 0.0)


def _cfg_max_dist_52w_high_pct_at_trigger(cfg: BRTConfig) -> float:
    return float(getattr(cfg, "max_dist_to_52w_high_pct_at_trigger", 0.0) or 0.0)


def _cfg_min_spy_compare_1y_at_trigger(cfg: BRTConfig) -> float:
    return _cfg_float_param(cfg, "min_spy_compare_1y_at_trigger", 50.0)


def _cfg_max_spy_compare_1y_at_trigger(cfg: BRTConfig) -> float:
    return _cfg_float_param(cfg, "max_spy_compare_1y_at_trigger", 0.0)


def _cfg_min_spy_compare_2y_at_trigger(cfg: BRTConfig) -> float:
    return _cfg_float_param(cfg, "min_spy_compare_2y_at_trigger", 0.0)


def _cfg_min_spy_compare_3y_at_trigger(cfg: BRTConfig) -> float:
    return _cfg_float_param(cfg, "min_spy_compare_3y_at_trigger", 0.0)


def _cfg_min_beta_at_trigger(cfg: BRTConfig) -> float:
    return _cfg_float_param(cfg, "min_beta_at_trigger", 0.0)


def _cfg_max_beta_at_trigger(cfg: BRTConfig) -> float:
    return _cfg_float_param(cfg, "max_beta_at_trigger", 0.0)


def _cfg_min_upper_wick_atr_at_trigger(cfg: BRTConfig) -> float:
    return _cfg_float_param(cfg, "min_upper_wick_atr_at_trigger", 0.0)


def _upper_wick_atr_at_bar(
    high_arr: np.ndarray,
    open_arr: np.ndarray,
    close_arr: np.ndarray,
    atr_14_arr: np.ndarray,
    bar: int,
) -> Optional[float]:
    """UPPER_WICK_ATR_AT_TRIGGER: (High - max(Open, Close)) / ATR14 at bar."""
    if bar < 0 or bar >= len(close_arr):
        return None
    atr_tr = float(atr_14_arr[bar])
    if not np.isfinite(atr_tr) or atr_tr <= 0.0:
        return None
    hi = float(high_arr[bar])
    op = float(open_arr[bar])
    cl = float(close_arr[bar])
    if not (np.isfinite(hi) and np.isfinite(op) and np.isfinite(cl)):
        return None
    upper_wick = max(0.0, hi - max(op, cl))
    return float(upper_wick / atr_tr)


def _upper_wick_atr_min_at_trigger_gate_blocks(
    cfg: BRTConfig,
    high_arr: np.ndarray,
    open_arr: np.ndarray,
    close_arr: np.ndarray,
    atr_14_arr: np.ndarray,
    signal_t: int,
) -> bool:
    """True when UPPER_WICK_ATR_AT_TRIGGER is below min_upper_wick_atr_at_trigger (0 = off)."""
    min_u = _cfg_min_upper_wick_atr_at_trigger(cfg)
    if min_u <= 0.0:
        return False
    val = _upper_wick_atr_at_bar(high_arr, open_arr, close_arr, atr_14_arr, signal_t)
    if val is None or not np.isfinite(val) or float(val) < min_u:
        return True
    return False


def _beta_min_at_trigger_gate_blocks(
    cfg: BRTConfig,
    beta_by_bar: Optional[np.ndarray],
    signal_t: int,
) -> bool:
    """True when rolling calculated beta (vs SPY) at trigger is below min_beta_at_trigger (0 = off)."""
    min_b = _cfg_min_beta_at_trigger(cfg)
    if min_b <= 0.0:
        return False
    if beta_by_bar is None or signal_t < 0 or signal_t >= len(beta_by_bar):
        return True
    bv = float(beta_by_bar[signal_t])
    if not np.isfinite(bv) or bv < min_b:
        return True
    return False


def _beta_max_at_trigger_gate_blocks(
    cfg: BRTConfig,
    beta_by_bar: Optional[np.ndarray],
    signal_t: int,
) -> bool:
    """True when rolling calculated beta (vs SPY) at trigger is above max_beta_at_trigger (0 = off)."""
    max_b = _cfg_max_beta_at_trigger(cfg)
    if max_b <= 0.0:
        return False
    if beta_by_bar is None or signal_t < 0 or signal_t >= len(beta_by_bar):
        return True
    bv = float(beta_by_bar[signal_t])
    if not np.isfinite(bv) or bv > max_b:
        return True
    return False


def _spy_compare_min_gate_active(min_c: float) -> bool:
    """True when a min SPY_COMPARE gate is on. Exactly 0 = off; negatives are valid thresholds."""
    return float(min_c) != 0.0


def _spy_compare_horizon_at_trigger_gate_blocks(
    cfg: BRTConfig,
    rs_st: Optional[np.ndarray],
    rs_sp: Optional[np.ndarray],
    signal_t: int,
    *,
    min_c: float,
    excess: Optional[float],
) -> bool:
    """True when SPY excess return at trigger is below ``min_c`` (exactly 0 = off; negatives allowed)."""
    if not _spy_compare_min_gate_active(min_c):
        return False
    if rs_st is None or rs_sp is None:
        return True
    if excess is None or not np.isfinite(excess) or float(excess) < min_c:
        return True
    return False


def _spy_compare_horizon_max_at_trigger_gate_blocks(
    cfg: BRTConfig,
    rs_st: Optional[np.ndarray],
    rs_sp: Optional[np.ndarray],
    signal_t: int,
    *,
    max_c: float,
    excess: Optional[float],
) -> bool:
    """True when SPY excess return at trigger is above ``max_c`` (0 = off)."""
    if max_c <= 0.0:
        return False
    if rs_st is None or rs_sp is None:
        return False
    if excess is None or not np.isfinite(excess):
        return False
    return float(excess) > max_c


def _spy_compare_1y_at_trigger_gate_blocks(
    cfg: BRTConfig,
    rs_st: Optional[np.ndarray],
    rs_sp: Optional[np.ndarray],
    signal_t: int,
) -> bool:
    """True when SPY_COMPARE_1Y at trigger is below min_spy_compare_1y_at_trigger (exactly 0 = off)."""
    e1, _, _ = _rs_excess_pct_points(rs_st, rs_sp, signal_t) if rs_st is not None and rs_sp is not None else (None, None, None)
    return _spy_compare_horizon_at_trigger_gate_blocks(
        cfg, rs_st, rs_sp, signal_t, min_c=_cfg_min_spy_compare_1y_at_trigger(cfg), excess=e1
    )


def _spy_compare_1y_max_at_trigger_gate_blocks(
    cfg: BRTConfig,
    rs_st: Optional[np.ndarray],
    rs_sp: Optional[np.ndarray],
    signal_t: int,
) -> bool:
    """True when SPY_COMPARE_1Y at trigger is above max_spy_compare_1y_at_trigger (0 = off)."""
    e1, _, _ = _rs_excess_pct_points(rs_st, rs_sp, signal_t) if rs_st is not None and rs_sp is not None else (None, None, None)
    return _spy_compare_horizon_max_at_trigger_gate_blocks(
        cfg, rs_st, rs_sp, signal_t, max_c=_cfg_max_spy_compare_1y_at_trigger(cfg), excess=e1
    )


def _spy_compare_2y_at_trigger_gate_blocks(
    cfg: BRTConfig,
    rs_st: Optional[np.ndarray],
    rs_sp: Optional[np.ndarray],
    signal_t: int,
) -> bool:
    """True when SPY_COMPARE_2Y at trigger is below min_spy_compare_2y_at_trigger (exactly 0 = off)."""
    _, e2, _ = _rs_excess_pct_points(rs_st, rs_sp, signal_t) if rs_st is not None and rs_sp is not None else (None, None, None)
    return _spy_compare_horizon_at_trigger_gate_blocks(
        cfg, rs_st, rs_sp, signal_t, min_c=_cfg_min_spy_compare_2y_at_trigger(cfg), excess=e2
    )


def _spy_compare_3y_at_trigger_gate_blocks(
    cfg: BRTConfig,
    rs_st: Optional[np.ndarray],
    rs_sp: Optional[np.ndarray],
    signal_t: int,
) -> bool:
    """True when SPY_COMPARE_3Y at trigger is below min_spy_compare_3y_at_trigger (exactly 0 = off)."""
    _, _, e3 = _rs_excess_pct_points(rs_st, rs_sp, signal_t) if rs_st is not None and rs_sp is not None else (None, None, None)
    return _spy_compare_horizon_at_trigger_gate_blocks(
        cfg, rs_st, rs_sp, signal_t, min_c=_cfg_min_spy_compare_3y_at_trigger(cfg), excess=e3
    )


def _dist_52w_high_at_trigger_gate_blocks(
    cfg: BRTConfig,
    high_arr: np.ndarray,
    price_arr: np.ndarray,
    signal_t: int,
) -> bool:
    """True when dist-to-52w-high gates reject (trigger close vs 52w high through that bar)."""
    min_d = _cfg_min_dist_52w_high_pct_at_trigger(cfg)
    max_d = _cfg_max_dist_52w_high_pct_at_trigger(cfg)
    if min_d <= 0.0 and max_d <= 0.0:
        return False
    if signal_t < 0 or signal_t >= len(price_arr):
        return True
    trig_close = float(price_arr[signal_t])
    if not (trig_close > 0.0 and np.isfinite(trig_close)):
        return True
    _, dist = _high_52w_and_dist_pct(high_arr, signal_t, trig_close)
    if dist is None or not np.isfinite(dist):
        return True
    if min_d > 0.0 and float(dist) < min_d:
        return True
    if max_d > 0.0 and float(dist) > max_d:
        return True
    return False


def _cfg_min_ind_score(cfg: BRTConfig) -> float:
    return _cfg_float_param(cfg, "min_ind_score", 0.0)


def _cfg_min_ind_score_filter_active(cfg: BRTConfig) -> bool:
    return _cfg_min_ind_score(cfg) > 0.0


def _cfg_mandatory_ind_states_path_raw(cfg: BRTConfig) -> str:
    return str(getattr(cfg, "mandatory_ind_states_path", "") or "").strip()


def _cfg_mandatory_ind_states_active(cfg: BRTConfig) -> bool:
    return bool(_cfg_mandatory_ind_states_path_raw(cfg))


def _resolve_mandatory_ind_states_file(cfg: BRTConfig) -> Optional[Path]:
    raw = _cfg_mandatory_ind_states_path_raw(cfg)
    if not raw:
        return None
    try:
        from brt_entry_indicators import resolve_mandatory_ind_states_path
    except ImportError:
        from stock_analysis.brt_entry_indicators import resolve_mandatory_ind_states_path
    return resolve_mandatory_ind_states_path(raw)


def _load_mandatory_ind_states_rules(cfg: BRTConfig) -> dict[str, str]:
    raw = _cfg_mandatory_ind_states_path_raw(cfg)
    if not raw:
        return {}
    try:
        from brt_entry_indicators import load_mandatory_ind_states
    except ImportError:
        from stock_analysis.brt_entry_indicators import load_mandatory_ind_states
    return load_mandatory_ind_states(raw)


def _mandatory_ind_states_gate_blocks(
    cfg: BRTConfig,
    sym_indicator_pre: Any,
    signal_t: int,
    entry_side: str,
) -> bool:
    """True when mandatory IND_* state rules reject the trigger bar."""
    rules = _load_mandatory_ind_states_rules(cfg)
    if not rules:
        return False
    try:
        from brt_entry_indicators import mandatory_ind_states_passes
    except ImportError:
        from stock_analysis.brt_entry_indicators import mandatory_ind_states_passes
    return not mandatory_ind_states_passes(sym_indicator_pre, signal_t, entry_side, rules)


def _cfg_uses_ind_score(cfg: BRTConfig) -> bool:
    _ibuy = _normalize_indicator_buy(getattr(cfg, "indicator_buy", "off"))
    return bool(
        bool(getattr(cfg, "use_indicators", False))
        or _ibuy in ("only", "both")
        or _cfg_min_ind_score_filter_active(cfg)
        or bool(getattr(cfg, "use_ind_score", True))
    )


def _resolve_ind_score_weights_path(raw: Optional[str]) -> Optional[str]:
    """Resolve weights JSON to an existing file (cwd, stock_analysis/, repo root, or default latest)."""
    s = str(raw or "").strip()
    if not s:
        try:
            from brt_entry_indicators import resolve_default_ind_score_weights_path
        except ImportError:
            from stock_analysis.brt_entry_indicators import resolve_default_ind_score_weights_path
        default_p = resolve_default_ind_score_weights_path()
        return str(default_p.resolve()) if default_p is not None else None
    p = Path(s)
    if p.is_file():
        return str(p.resolve())
    script_dir = Path(__file__).resolve().parent
    for base in (Path.cwd(), script_dir, script_dir.parent):
        candidate = (base / s).resolve()
        if candidate.is_file():
            return str(candidate)
    return None


def _snapshot_ind_score_weights_for_run(cfg: BRTConfig, run_ts: str) -> BRTConfig:
    """
    Record which IND_SCORE weights JSON this run uses (audit ``ind_score_weights_path``).

    Does not copy weights per run. Default (empty path) resolves to the canonical
    ``ind_score_weights_<stamp>.json`` for the active weights content; explicit
    ``-v ind_score_weights_path=...`` uses that file as given.
    """
    del run_ts  # retained for call-site stability; no per-run filename
    if not _cfg_uses_ind_score(cfg):
        return cfg
    explicit = str(getattr(cfg, "ind_score_weights_path", "") or "").strip()
    source = _resolve_ind_score_weights_path(explicit or None)
    if not source:
        print("[BRT] IND_SCORE: no weights JSON found (build with build_ind_score_weights.py)", file=sys.stderr)
        return cfg
    src_p = Path(source)
    if not src_p.is_file():
        print(f"[BRT] IND_SCORE: weights file not found: {source}", file=sys.stderr)
        return cfg
    weights_name = src_p.name
    if explicit:
        print(f"[BRT] IND_SCORE: weights {explicit}")
    else:
        print(f"[BRT] IND_SCORE: weights {weights_name}")
    if explicit and weights_name != explicit.replace("\\", "/").split("/")[-1]:
        return cfg
    return replace(cfg, ind_score_weights_path=weights_name)


def _configure_ind_score_from_cfg(cfg: BRTConfig) -> None:
    """Apply IND_SCORE settings in the current process (required in ProcessPool workers)."""
    if not _cfg_uses_ind_score(cfg):
        return
    try:
        from brt_entry_indicators import configure_ind_score
    except ImportError:
        from stock_analysis.brt_entry_indicators import configure_ind_score
    _iscore_path = _resolve_ind_score_weights_path(getattr(cfg, "ind_score_weights_path", ""))
    configure_ind_score(
        enabled=bool(getattr(cfg, "use_ind_score", True)),
        weights_path=_iscore_path,
    )


def _ind_watchlist_side_label(entry_side: str) -> str:
    return "LONG" if str(entry_side or "long").strip().lower() == "long" else "SHORT"


def _fmt_limit_price(v: Any) -> str:
    if v is None or v == "":
        return ""
    try:
        f = float(v)
        return f"{f:.4f}" if np.isfinite(f) and f > 0 else ""
    except (TypeError, ValueError):
        return ""


def _entry_open_band_fields(
    signal_low: float,
    signal_high: float,
    prior_close: float,
    too_high_mult: float,
    too_low_mult: float,
    is_long: bool,
) -> dict[str, Any]:
    """Next-open band for final entry gates (long: buy only if min <= open <= max)."""
    lo = float(signal_low) if np.isfinite(signal_low) else float("nan")
    hi = float(signal_high) if np.isfinite(signal_high) else float("nan")
    pc = float(prior_close) if np.isfinite(prior_close) else float("nan")
    th = float(too_high_mult or 0.0)
    tl = float(too_low_mult or 0.0)
    out: dict[str, Any] = {
        "signal_bar_low": lo if lo > 0 else None,
        "signal_bar_high": hi if hi > 0 else None,
        "prior_day_close": pc if pc > 0 else None,
        "too_high_multiplier": th if th > 0 else None,
        "too_low_multiplier": tl if tl > 0 else None,
        "max_entry_open": None,
        "min_entry_open": None,
    }
    if is_long:
        if th > 0 and lo > 0:
            out["max_entry_open"] = lo * th
        if tl > 0 and pc > 0:
            out["min_entry_open"] = pc * tl
    else:
        if th > 0 and hi > 0:
            out["min_entry_open"] = hi / th
        if tl > 0 and pc > 0:
            out["max_entry_open"] = pc / tl
    return out


def _too_high_open_limit_fields(
    signal_low: float,
    signal_high: float,
    too_high_mult: float,
    is_long: bool,
) -> dict[str, Any]:
    """Backward-compatible wrapper (no prior-close floor)."""
    return _entry_open_band_fields(signal_low, signal_high, float("nan"), too_high_mult, 0.0, is_long)


def _watchlist_entry_open_csv_fields(
    cfg: BRTConfig,
    signal_low: float,
    signal_high: float,
    *,
    is_long: bool = True,
    scanner_row: Optional[dict] = None,
    prior_close: float = float("nan"),
) -> dict[str, str]:
    if scanner_row:
        lo = scanner_row.get("signal_bar_low", signal_low)
        hi = scanner_row.get("signal_bar_high", signal_high)
        pc = scanner_row.get("prior_day_close", prior_close)
        th = scanner_row.get("too_high_multiplier")
        if th is None:
            th = float(getattr(cfg, "too_high_multiplier", 0.0) or 0.0)
        tl = scanner_row.get("too_low_multiplier")
        if tl is None:
            tl = float(getattr(cfg, "too_low_multiplier", 0.0) or 0.0)
        lim = {
            "signal_bar_low": lo,
            "signal_bar_high": hi,
            "prior_day_close": pc,
            "too_high_multiplier": th,
            "too_low_multiplier": tl,
            "max_entry_open": scanner_row.get("max_entry_open"),
            "min_entry_open": scanner_row.get("min_entry_open"),
        }
    else:
        lim = _entry_open_band_fields(
            signal_low,
            signal_high,
            prior_close,
            float(getattr(cfg, "too_high_multiplier", 0.0) or 0.0),
            float(getattr(cfg, "too_low_multiplier", 0.0) or 0.0),
            is_long,
        )
    th = lim.get("too_high_multiplier")
    tl = lim.get("too_low_multiplier")
    min_o = _fmt_limit_price(lim.get("min_entry_open"))
    max_o = _fmt_limit_price(lim.get("max_entry_open"))
    band = ""
    if min_o and max_o:
        band = f"{min_o} .. {max_o}"
    elif min_o:
        band = f">= {min_o}"
    elif max_o:
        band = f"<= {max_o}"
    return {
        "SIGNAL_BAR_LOW": _fmt_limit_price(lim.get("signal_bar_low")),
        "SIGNAL_BAR_HIGH": _fmt_limit_price(lim.get("signal_bar_high")),
        "PRIOR_DAY_CLOSE": _fmt_limit_price(lim.get("prior_day_close")),
        "TOO_HIGH_MULTIPLIER": f"{float(th):.4f}" if th not in (None, "") else "",
        "TOO_LOW_MULTIPLIER": f"{float(tl):.4f}" if tl not in (None, "") else "",
        "MIN_ENTRY_OPEN": min_o,
        "MAX_ENTRY_OPEN": max_o,
        "ENTRY_OPEN_BAND": band,
    }


def _watchlist_too_high_csv_fields(
    cfg: BRTConfig,
    signal_low: float,
    signal_high: float,
    *,
    is_long: bool = True,
    scanner_row: Optional[dict] = None,
    prior_close: float = float("nan"),
) -> dict[str, str]:
    """Backward-compatible alias for entry-open band CSV fields."""
    return _watchlist_entry_open_csv_fields(
        cfg,
        signal_low,
        signal_high,
        is_long=is_long,
        scanner_row=scanner_row,
        prior_close=prior_close,
    )


def _ind_watchlist_prospective_entry_checks(
    entry_bar: int,
    signal_bar: int,
    *,
    open_arr: Any,
    high_arr: Any,
    low_arr: Any,
    close_arr: Any,
    cfg: BRTConfig,
    is_long: bool = True,
    rs_st: Optional[np.ndarray] = None,
    rs_sp: Optional[np.ndarray] = None,
    sym_indicator_pre: Any = None,
) -> dict[str, Any]:
    """Mirror key programmatic entry checks for a would-enter-next-open bar (IND / RS paths)."""
    out: dict[str, Any] = {
        "entry_bar": entry_bar,
        "signal_bar": signal_bar,
        "atr_pct": None,
        "min_atr_gate": _cfg_min_atr_pct_trigger(cfg),
        "max_atr_gate": _cfg_max_atr_pct_trigger(cfg),
        "pass_atr_min": True,
        "pass_atr_max": True,
        "pass_atr": True,
        "atr_gap": 0.0,
        "pass_close_gt_open": True,
        "too_high_mult": float(_cfg_float_param(cfg, "too_high_multiplier", 0.0)),
        "too_low_mult": float(_cfg_float_param(cfg, "too_low_multiplier", 0.0)),
        "pass_too_high": True,
        "pass_too_low": True,
        "dist_52w_pct": None,
        "min_dist_52w_gate": _cfg_min_dist_52w_high_pct_at_trigger(cfg),
        "max_dist_52w_gate": _cfg_max_dist_52w_high_pct_at_trigger(cfg),
        "pass_dist_52w": True,
        "spy_compare_1y": None,
        "spy_compare_2y": None,
        "spy_compare_3y": None,
        "min_spy_compare_1y_gate": _cfg_min_spy_compare_1y_at_trigger(cfg),
        "max_spy_compare_1y_gate": _cfg_max_spy_compare_1y_at_trigger(cfg),
        "min_spy_compare_2y_gate": _cfg_min_spy_compare_2y_at_trigger(cfg),
        "min_spy_compare_3y_gate": _cfg_min_spy_compare_3y_at_trigger(cfg),
        "pass_spy_compare_1y": True,
        "pass_spy_compare_1y_min": True,
        "pass_spy_compare_1y_max": True,
        "pass_spy_compare_2y": True,
        "pass_spy_compare_3y": True,
        "pass_mandatory_ind": True,
    }
    n = len(close_arr) if close_arr is not None else 0
    if entry_bar < 0 or entry_bar >= n or signal_bar < 0 or signal_bar >= n:
        out["pass_atr"] = False
        out["pass_close_gt_open"] = False
        out["pass_too_high"] = False
        out["pass_too_low"] = False
        out["pass_dist_52w"] = False
        out["pass_spy_compare_1y"] = False
        out["pass_spy_compare_1y_min"] = False
        out["pass_spy_compare_1y_max"] = False
        out["pass_spy_compare_2y"] = False
        out["pass_spy_compare_3y"] = False
        out["pass_mandatory_ind"] = False
        return out
    entry_px = float(open_arr[entry_bar]) if entry_bar < len(open_arr) else float("nan")
    if not (entry_px > 0.0 and np.isfinite(entry_px)):
        out["pass_too_high"] = False
        out["pass_too_low"] = False
    atr_arr = _compute_atr_14_arr(high_arr, low_arr, close_arr, 14)
    _, atr_pct_trig = _atr_14_and_pct_at_bar(atr_arr, close_arr, signal_bar)
    if atr_pct_trig is not None and np.isfinite(float(atr_pct_trig)):
        out["atr_pct"] = float(atr_pct_trig)
        min_a = out["min_atr_gate"]
        max_a = out["max_atr_gate"]
        if min_a > 0.0:
            out["pass_atr_min"] = float(atr_pct_trig) >= min_a
            out["atr_gap"] = max(0.0, min_a - float(atr_pct_trig))
        if max_a > 0.0:
            out["pass_atr_max"] = float(atr_pct_trig) <= max_a
        out["pass_atr"] = bool(out["pass_atr_min"] and out["pass_atr_max"])
    elif out["min_atr_gate"] > 0.0 or out["max_atr_gate"] > 0.0:
        out["pass_atr"] = False
        out["atr_gap"] = out["min_atr_gate"] if out["min_atr_gate"] > 0.0 else 999.0
    if 0 <= signal_bar < n:
        cl = float(close_arr[signal_bar])
        op = float(open_arr[signal_bar]) if signal_bar < len(open_arr) else float("nan")
        if bool(getattr(cfg, "require_close_gt_open", True)):
            if is_long:
                out["pass_close_gt_open"] = bool(np.isfinite(cl) and np.isfinite(op) and cl > op)
            else:
                out["pass_close_gt_open"] = bool(np.isfinite(cl) and np.isfinite(op) and cl < op)
        lo = float(low_arr[signal_bar]) if signal_bar < len(low_arr) else float("nan")
        hi = float(high_arr[signal_bar]) if signal_bar < len(high_arr) else float("nan")
        if out["too_high_mult"] > 0.0:
            if is_long and np.isfinite(lo) and lo > 0.0:
                out["pass_too_high"] = entry_px <= lo * out["too_high_mult"]
            elif (not is_long) and np.isfinite(hi) and hi > 0.0:
                out["pass_too_high"] = entry_px >= hi / out["too_high_mult"]
        if out["too_low_mult"] > 0.0 and signal_bar >= 1:
            pc = float(close_arr[signal_bar - 1]) if signal_bar - 1 < len(close_arr) else float("nan")
            if is_long and np.isfinite(pc) and pc > 0.0:
                out["pass_too_low"] = entry_px >= pc * out["too_low_mult"]
            elif (not is_long) and np.isfinite(pc) and pc > 0.0:
                out["pass_too_low"] = entry_px <= pc / out["too_low_mult"]
    min_d52 = out["min_dist_52w_gate"]
    max_d52 = out["max_dist_52w_gate"]
    if min_d52 > 0.0 or max_d52 > 0.0:
        if high_arr is not None and 0 <= signal_bar < len(high_arr):
            trig_close = float(close_arr[signal_bar])
            _, dist52 = _high_52w_and_dist_pct(high_arr, signal_bar, trig_close)
            if dist52 is not None and np.isfinite(dist52):
                out["dist_52w_pct"] = float(dist52)
                out["pass_dist_52w"] = True
                if min_d52 > 0.0 and float(dist52) < min_d52:
                    out["pass_dist_52w"] = False
                if max_d52 > 0.0 and float(dist52) > max_d52:
                    out["pass_dist_52w"] = False
            else:
                out["pass_dist_52w"] = False
        else:
            out["pass_dist_52w"] = False
    e1 = e2 = e3 = None
    if rs_st is not None and rs_sp is not None:
        e1, e2, e3 = _rs_excess_pct_points(rs_st, rs_sp, signal_bar)
    min_spy1 = out["min_spy_compare_1y_gate"]
    max_spy1 = out["max_spy_compare_1y_gate"]
    if _spy_compare_min_gate_active(min_spy1) or max_spy1 > 0.0:
        if e1 is not None and np.isfinite(e1):
            out["spy_compare_1y"] = float(e1)
            if _spy_compare_min_gate_active(min_spy1):
                out["pass_spy_compare_1y_min"] = float(e1) >= min_spy1
            if max_spy1 > 0.0:
                out["pass_spy_compare_1y_max"] = float(e1) <= max_spy1
        elif _spy_compare_min_gate_active(min_spy1):
            out["pass_spy_compare_1y_min"] = False
        out["pass_spy_compare_1y"] = bool(
            out["pass_spy_compare_1y_min"] and out["pass_spy_compare_1y_max"]
        )
    for excess, min_gate_key, spy_key, pass_key in (
        (e2, "min_spy_compare_2y_gate", "spy_compare_2y", "pass_spy_compare_2y"),
        (e3, "min_spy_compare_3y_gate", "spy_compare_3y", "pass_spy_compare_3y"),
    ):
        min_gate = out[min_gate_key]
        if _spy_compare_min_gate_active(min_gate):
            if excess is not None and np.isfinite(excess):
                out[spy_key] = float(excess)
                out[pass_key] = float(excess) >= min_gate
            else:
                out[pass_key] = False
    side = "LONG" if is_long else "SHORT"
    if _cfg_mandatory_ind_states_active(cfg):
        out["pass_mandatory_ind"] = not _mandatory_ind_states_gate_blocks(
            cfg, sym_indicator_pre, signal_bar, side
        )
    return out


def _ind_watchlist_metrics_at_bar(
    pre: Any,
    bar_i: int,
    side: str,
    cfg: BRTConfig,
    *,
    entry_checks: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Point-in-time IND gate metrics at ``bar_i`` (trade-aligned diff)."""
    try:
        from brt_entry_indicators import (
            aligned_bull_bear_diff,
            entry_bull_n,
            entry_neutral_n,
            ind_score_at_bar,
        )
    except ImportError:
        from stock_analysis.brt_entry_indicators import (
            aligned_bull_bear_diff,
            entry_bull_n,
            entry_neutral_n,
            ind_score_at_bar,
        )
    if pre is None or bar_i < 0 or bar_i >= len(pre.dates):
        return None
    diff = aligned_bull_bear_diff(pre, bar_i, side)
    if diff is None:
        return None
    score: Optional[float] = None
    min_score = _cfg_min_ind_score(cfg)
    min_score_active = _cfg_min_ind_score_filter_active(cfg)
    if min_score_active:
        score = ind_score_at_bar(pre, bar_i)
    neutral = entry_neutral_n(pre, bar_i, side)
    bull = entry_bull_n(pre, bar_i, side)
    diff_gate = int(getattr(cfg, "indicator_diff", 10) or 10)
    max_neutral = getattr(cfg, "max_ind_entry_neutral_n", None)
    min_bull = getattr(cfg, "min_ind_entry_bull_n", None)
    pass_diff = int(diff) >= diff_gate
    pass_score = (not min_score_active) or (score is not None and float(score) >= min_score)
    pass_neutral = max_neutral is None or (
        neutral is not None and int(neutral) <= int(max_neutral)
    )
    pass_bull = min_bull is None or (bull is not None and int(bull) >= int(min_bull))
    pass_all = pass_diff and pass_score and pass_neutral and pass_bull
    pass_atr = True
    pass_close = True
    pass_too_high = True
    pass_too_low = True
    pass_dist_52w = True
    pass_spy_compare_1y = True
    pass_spy_compare_1y_min = True
    pass_spy_compare_1y_max = True
    pass_spy_compare_2y = True
    pass_spy_compare_3y = True
    pass_mandatory_ind = True
    atr_pct: Optional[float] = None
    atr_gap = 0.0
    if entry_checks is not None:
        pass_atr = bool(entry_checks.get("pass_atr", True))
        pass_close = bool(entry_checks.get("pass_close_gt_open", True))
        pass_too_high = bool(entry_checks.get("pass_too_high", True))
        pass_too_low = bool(entry_checks.get("pass_too_low", True))
        pass_dist_52w = bool(entry_checks.get("pass_dist_52w", True))
        pass_spy_compare_1y = bool(entry_checks.get("pass_spy_compare_1y", True))
        pass_spy_compare_1y_min = bool(entry_checks.get("pass_spy_compare_1y_min", True))
        pass_spy_compare_1y_max = bool(entry_checks.get("pass_spy_compare_1y_max", True))
        pass_spy_compare_2y = bool(entry_checks.get("pass_spy_compare_2y", True))
        pass_spy_compare_3y = bool(entry_checks.get("pass_spy_compare_3y", True))
        pass_mandatory_ind = bool(entry_checks.get("pass_mandatory_ind", True))
        atr_pct = entry_checks.get("atr_pct")
        try:
            atr_gap = float(entry_checks.get("atr_gap", 0.0) or 0.0)
        except (TypeError, ValueError):
            atr_gap = 0.0
    pass_scanner = (
        pass_all
        and pass_atr
        and pass_close
        and pass_too_high
        and pass_too_low
        and pass_dist_52w
        and pass_spy_compare_1y
        and pass_spy_compare_2y
        and pass_spy_compare_3y
        and pass_mandatory_ind
    )
    diff_gap = max(0, diff_gate - int(diff))
    score_gap = (
        max(0.0, min_score - float(score))
        if min_score_active and score is not None
        else (999.0 if min_score_active else 0.0)
    )
    neutral_gap = (
        max(0, int(neutral) - int(max_neutral))
        if max_neutral is not None and neutral is not None
        else 0
    )
    return {
        "diff": int(diff),
        "score": score,
        "neutral": neutral,
        "bull": bull,
        "diff_gate": diff_gate,
        "score_gate": min_score if min_score_active else "",
        "neutral_max": max_neutral if max_neutral is not None else "",
        "min_bull_gate": min_bull if min_bull is not None else "",
        "pass_diff": pass_diff,
        "pass_score": pass_score,
        "pass_neutral": pass_neutral,
        "pass_bull": pass_bull,
        "pass_all": pass_all,
        "pass_atr": pass_atr,
        "pass_close_gt_open": pass_close,
        "pass_too_high": pass_too_high,
        "pass_too_low": pass_too_low,
        "pass_dist_52w": pass_dist_52w,
        "pass_spy_compare_1y": pass_spy_compare_1y,
        "pass_spy_compare_1y_min": pass_spy_compare_1y_min,
        "pass_spy_compare_1y_max": pass_spy_compare_1y_max,
        "pass_spy_compare_2y": pass_spy_compare_2y,
        "pass_spy_compare_3y": pass_spy_compare_3y,
        "pass_mandatory_ind": pass_mandatory_ind,
        "pass_scanner": pass_scanner,
        "atr_pct": atr_pct,
        "atr_gap": atr_gap,
        "min_atr_gate": (
            float(entry_checks.get("min_atr_gate", 0.0) or 0.0)
            if entry_checks is not None
            else _cfg_min_atr_pct_trigger(cfg)
        ),
        "diff_gap": diff_gap,
        "score_gap": score_gap,
        "neutral_gap": neutral_gap,
    }


def _ind_watchlist_trend_label(delta_diff: Optional[int], delta_score: Optional[float], cfg: BRTConfig) -> str:
    d_min = int(getattr(cfg, "ind_watchlist_improve_diff_delta", 2) or 2)
    s_min = float(getattr(cfg, "ind_watchlist_improve_score_delta", 1.0) or 1.0)
    d_up = delta_diff is not None and int(delta_diff) >= d_min
    d_dn = delta_diff is not None and int(delta_diff) <= -d_min
    s_up = delta_score is not None and float(delta_score) >= s_min
    s_dn = delta_score is not None and float(delta_score) <= -s_min
    if d_up or s_up:
        if d_dn or s_dn:
            return "MIXED"
        return "IMPROVING"
    if d_dn or s_dn:
        return "WORSENING"
    return "FLAT"


def _ind_watchlist_readiness(m: dict[str, Any], row_type: str, trend: str) -> float:
    if row_type == "SCANNER":
        return -1000.0
    base = float(m["diff_gap"]) * 2.0 + float(m["score_gap"]) + float(m["neutral_gap"]) * 0.5
    if trend == "IMPROVING":
        base -= 4.0
    elif trend == "WORSENING":
        base += 3.0
    elif trend == "MIXED":
        base += 1.0
    if row_type == "NEAR_GATE":
        base -= 2.0
    elif row_type == "FADING":
        base += 2.0
    return base


def _ind_watchlist_classify(
    m: dict[str, Any],
    *,
    in_scanner: bool,
    delta_diff: Optional[int],
    delta_score: Optional[float],
    near_diff: int,
    near_score: float,
    was_near: bool,
    cfg: BRTConfig,
) -> tuple[str, str]:
    trend = _ind_watchlist_trend_label(delta_diff, delta_score, cfg)
    atr_near = float(getattr(cfg, "ind_watchlist_atr_near_pct", 1.0) or 1.0)
    require_atr = bool(getattr(cfg, "ind_watchlist_scanner_requires_atr", True))
    if in_scanner:
        return "SCANNER", trend
    if m.get("pass_scanner") and not in_scanner:
        if trend == "IMPROVING":
            return "IMPROVING", trend
        if was_near and trend == "WORSENING":
            return "FADING", trend
        return "STALLED", trend
    if m["pass_all"] and require_atr and not m.get("pass_atr", True):
        try:
            ag = float(m.get("atr_gap", 999.0) or 999.0)
        except (TypeError, ValueError):
            ag = 999.0
        if ag <= atr_near:
            return "NEAR_GATE", trend
    near = (int(m["diff_gap"]) <= near_diff) or (
        float(m["score_gap"]) <= near_score and m.get("score") is not None
    )
    improving = trend == "IMPROVING"
    worsening = trend == "WORSENING"
    if near and improving:
        return "NEAR_GATE", trend
    if (int(m["diff_gap"]) > 0 or float(m["score_gap"]) > 0) and improving:
        return "IMPROVING", trend
    if was_near and worsening:
        return "FADING", trend
    return "STALLED", trend


def _ind_watchlist_include_row(row_type: str, m: dict[str, Any], cfg: BRTConfig) -> bool:
    if row_type == "SCANNER":
        return True
    if row_type in ("NEAR_GATE", "IMPROVING", "FADING"):
        return True
    stalled_diff = int(getattr(cfg, "ind_watchlist_stalled_max_diff_gap", 12) or 12)
    stalled_score = float(getattr(cfg, "ind_watchlist_stalled_max_score_gap", 12.0) or 12.0)
    return int(m["diff_gap"]) <= stalled_diff and float(m["score_gap"]) <= stalled_score


def _ind_watchlist_row_from_metrics(
    sym: str,
    as_of_iso: str,
    last_close: float,
    m: dict[str, Any],
    cfg: BRTConfig,
    *,
    row_type: str,
    trend: str,
    delta_diff: Optional[int],
    delta_score: Optional[float],
    diff_lb: Optional[int],
    score_lb: Optional[float],
    scanner_row: Optional[dict] = None,
    signal_bar_low: float = float("nan"),
    signal_bar_high: float = float("nan"),
    prior_close: float = float("nan"),
    is_long: bool = True,
) -> dict[str, Any]:
    _th_ind = _watchlist_entry_open_csv_fields(
        cfg,
        signal_bar_low,
        signal_bar_high,
        is_long=is_long,
        scanner_row=scanner_row,
        prior_close=prior_close,
    )
    readiness = _ind_watchlist_readiness(m, row_type, trend)
    gates_bits: list[str] = []
    if not m["pass_diff"]:
        gates_bits.append(f"IND_DIFF={m['diff']}<{m['diff_gate']}")
    if m.get("score_gate") != "" and not m["pass_score"]:
        gates_bits.append(f"IND_SCORE={m['score']:.2f}<{m['score_gate']}")
    if m.get("neutral_max") != "" and not m["pass_neutral"]:
        gates_bits.append(f"NEUTRAL={m['neutral']}>{m['neutral_max']}")
    if m.get("min_bull_gate") != "" and not m["pass_bull"]:
        gates_bits.append(f"BULL={m['bull']}<{m['min_bull_gate']}")
    if not m.get("pass_atr", True):
        ap = m.get("atr_pct")
        min_a = float(m.get("min_atr_gate", 0.0) or 0.0)
        if ap is not None and min_a > 0.0:
            gates_bits.append(f"ATR_PCT={float(ap):.2f}<{min_a:.2f}")
        else:
            gates_bits.append("ATR_PCT below min_atr_pct_at_trigger")
    if not m.get("pass_close_gt_open", True):
        gates_bits.append("close_le_open on signal bar")
    if not m.get("pass_too_high", True):
        gates_bits.append("too_high_final_gate")
    if not m.get("pass_too_low", True):
        gates_bits.append("too_low_final_gate")
    if not m.get("pass_dist_52w", True):
        gates_bits.append("dist_to_52w_high_pct_at_trigger")
    if not m.get("pass_spy_compare_1y_min", True):
        gates_bits.append("min_spy_compare_1y_at_trigger")
    if not m.get("pass_spy_compare_1y_max", True):
        gates_bits.append("max_spy_compare_1y_at_trigger")
    if not m.get("pass_spy_compare_2y", True):
        gates_bits.append("min_spy_compare_2y_at_trigger")
    if not m.get("pass_spy_compare_3y", True):
        gates_bits.append("min_spy_compare_3y_at_trigger")
    if not m.get("pass_mandatory_ind", True):
        gates_bits.append("mandatory_ind_states")
    _band = _th_ind.get("ENTRY_OPEN_BAND", "")
    if row_type == "SCANNER":
        if is_long and _band:
            _th_note = f" Long: buy only if next open in [{_band}]."
        elif (not is_long) and _band:
            _th_note = f" Short: sell only if next open in [{_band}]."
        elif _th_ind.get("MAX_ENTRY_OPEN"):
            _th_note = f" Long: buy only if open <= {_th_ind['MAX_ENTRY_OPEN']}."
        elif _th_ind.get("MIN_ENTRY_OPEN"):
            _th_note = f" Short: sell only if open >= {_th_ind['MIN_ENTRY_OPEN']}."
        else:
            _th_note = ""
        hint = (
            "Backtest entry signal on last bar (same row set as IND_Scanner)."
            f"{_th_note}"
        )
    elif m.get("pass_scanner") and scanner_row is None:
        hint = (
            "Indicator gates + min_atr pass on last bar but no backtest entry signal "
            "(no IND_Scanner row); not labeled SCANNER."
        )
    elif row_type == "NEAR_GATE":
        if not m.get("pass_atr", True):
            hint = (
                f"ATR within {float(getattr(cfg, 'ind_watchlist_atr_near_pct', 1.0) or 1.0):.1f} "
                "pct points of min_atr_pct_at_trigger and improving (5-bar trend)."
            )
        else:
            hint = "Within margin of one or more gates and improving (5-bar trend)."
    elif row_type == "IMPROVING":
        hint = "Below gates but IND_DIFF/IND_SCORE trending toward entry thresholds."
    elif row_type == "FADING":
        hint = "Was near gates recently; IND_DIFF/IND_SCORE deteriorating."
    else:
        hint = "Below gates; flat or weak trend toward entry."
    stop = ""
    target = ""
    entry_date = as_of_iso
    if scanner_row:
        entry_date = str(scanner_row.get("date", as_of_iso) or as_of_iso)
        if scanner_row.get("stop") is not None:
            stop = f"{float(scanner_row['stop']):.2f}"
        if scanner_row.get("target") is not None:
            target = f"{float(scanner_row['target']):.2f}"
    score_s = f"{float(m['score']):.2f}" if m.get("score") is not None else ""
    score_lb_s = f"{float(score_lb):.2f}" if score_lb is not None else ""
    return {
        "ROW_TYPE": row_type,
        "SYMBOL": sym,
        "AS_OF_DATE": as_of_iso,
        "ENTRY_DATE": entry_date,
        "CLOSE": f"{last_close:.2f}" if last_close == last_close else "",
        "STOP_LOSS": stop,
        "TARGET": target,
        **_th_ind,
        "LAST_CLOSE": f"{last_close:.2f}" if last_close == last_close else "",
        "IND_DIFF": str(m["diff"]),
        "IND_SCORE": score_s,
        "IND_ENTRY_NEUTRAL_N": str(m["neutral"]) if m["neutral"] is not None else "",
        "IND_ENTRY_BULL_N": str(m["bull"]) if m["bull"] is not None else "",
        "DIFF_GATE": str(m["diff_gate"]),
        "SCORE_GATE": str(m["score_gate"]) if m.get("score_gate") != "" else "",
        "NEUTRAL_MAX": str(m["neutral_max"]) if m.get("neutral_max") != "" else "",
        "DIFF_GAP": str(m["diff_gap"]),
        "SCORE_GAP": f"{float(m['score_gap']):.2f}",
        "NEUTRAL_GAP": str(m["neutral_gap"]),
        "ATR_PCT_AT_TRIGGER": (
            f"{float(m['atr_pct']):.2f}" if m.get("atr_pct") is not None else ""
        ),
        "ATR_GATE": (
            f"{float(m.get('min_atr_gate', 0.0) or 0.0):.2f}"
            if float(m.get("min_atr_gate", 0.0) or 0.0) > 0.0
            else ""
        ),
        "ATR_GAP": f"{float(m.get('atr_gap', 0.0) or 0.0):.2f}",
        "IND_DIFF_5": str(diff_lb) if diff_lb is not None else "",
        "IND_DIFF_20": "",
        "IND_DIFF_DELTA_5": str(delta_diff) if delta_diff is not None else "",
        "IND_SCORE_5": score_lb_s,
        "IND_SCORE_DELTA_5": f"{float(delta_score):.2f}" if delta_score is not None else "",
        "TREND": trend,
        "READINESS": f"{readiness:.4f}",
        "STATUS": row_type,
        "GATES_REMAINING": "; ".join(gates_bits),
        "TRIGGER_HINT": hint,
    }


def _build_ind_watchlist(
    sym: str,
    scanner: list[dict],
    cfg: BRTConfig,
    n: int,
    index_iso: list[str],
    close_arr: Any,
    open_arr: Any,
    high_arr: Any,
    low_arr: Any,
    pre: Optional[Any],
    entry_side: str,
    rs_st: Optional[np.ndarray] = None,
    rs_sp: Optional[np.ndarray] = None,
) -> list[dict]:
    """Indicator-only watchlist: IND_DIFF / IND_SCORE vs gates and 5-bar trend (no zone/retest rows)."""
    if n < 1 or pre is None:
        return []
    li = n - 1
    as_of = index_iso[li] if li < len(index_iso) else ""
    last_close = float(close_arr[li]) if li < len(close_arr) else float("nan")
    side = _ind_watchlist_side_label(entry_side)
    is_long = side == "LONG"
    signal_bar = max(0, li - 1)
    entry_checks = _ind_watchlist_prospective_entry_checks(
        li,
        signal_bar,
        open_arr=open_arr,
        high_arr=high_arr,
        low_arr=low_arr,
        close_arr=close_arr,
        cfg=cfg,
        is_long=is_long,
        rs_st=rs_st,
        rs_sp=rs_sp,
        sym_indicator_pre=pre,
    )
    if bool(getattr(cfg, "ind_watchlist_scanner_requires_atr", True)):
        entry_checks_for_metrics = entry_checks
    else:
        entry_checks_for_metrics = {
            **entry_checks,
            "pass_atr": True,
            "pass_atr_min": True,
            "pass_atr_max": True,
            "atr_gap": 0.0,
        }
    lb_short = max(1, int(getattr(cfg, "ind_watchlist_lookback_short", 5) or 5))
    near_diff = max(0, int(getattr(cfg, "ind_watchlist_near_diff_gap", 3) or 3))
    near_score = float(getattr(cfg, "ind_watchlist_near_score_gap", 5.0) or 5.0)
    m_now = _ind_watchlist_metrics_at_bar(
        pre, signal_bar, side, cfg, entry_checks=entry_checks_for_metrics
    )
    if m_now is None:
        return []
    i5 = signal_bar - lb_short
    i20 = signal_bar - max(1, int(getattr(cfg, "ind_watchlist_lookback_long", 20) or 20))
    m5 = (
        _ind_watchlist_metrics_at_bar(pre, i5, side, cfg, entry_checks=entry_checks_for_metrics)
        if i5 >= 0
        else None
    )
    m20 = (
        _ind_watchlist_metrics_at_bar(pre, i20, side, cfg, entry_checks=entry_checks_for_metrics)
        if i20 >= 0
        else None
    )
    delta_diff = int(m_now["diff"]) - int(m5["diff"]) if m5 is not None else None
    delta_score = (
        float(m_now["score"]) - float(m5["score"])
        if m5 is not None and m_now.get("score") is not None and m5.get("score") is not None
        else None
    )
    diff_lb = int(m5["diff"]) if m5 is not None else None
    score_lb = float(m5["score"]) if m5 is not None and m5.get("score") is not None else None
    was_near = False
    if m5 is not None:
        was_near = (int(m5["diff_gap"]) <= near_diff * 2) or (
            float(m5["score_gap"]) <= near_score * 2 and m5.get("score") is not None
        )
    scanner_by_sym: dict[str, dict] = {}
    for s in scanner:
        k = str(s.get("symbol", sym) or sym).strip().upper()
        scanner_by_sym[k] = s
    in_scanner = sym.strip().upper() in scanner_by_sym
    row_type, trend = _ind_watchlist_classify(
        m_now,
        in_scanner=in_scanner,
        delta_diff=delta_diff,
        delta_score=delta_score,
        near_diff=near_diff,
        near_score=near_score,
        was_near=was_near,
        cfg=cfg,
    )
    if not _ind_watchlist_include_row(row_type, m_now, cfg):
        return []
    _sig_lo = float(low_arr[signal_bar]) if signal_bar < len(low_arr) else float("nan")
    _sig_hi = float(high_arr[signal_bar]) if signal_bar < len(high_arr) else float("nan")
    _prior_pc = (
        float(close_arr[signal_bar - 1])
        if signal_bar >= 1 and signal_bar - 1 < len(close_arr)
        else float("nan")
    )
    row = _ind_watchlist_row_from_metrics(
        sym,
        as_of,
        last_close,
        m_now,
        cfg,
        row_type=row_type,
        trend=trend,
        delta_diff=delta_diff,
        delta_score=delta_score,
        diff_lb=diff_lb,
        score_lb=score_lb,
        scanner_row=scanner_by_sym.get(sym.strip().upper()),
        signal_bar_low=_sig_lo,
        signal_bar_high=_sig_hi,
        prior_close=_prior_pc,
        is_long=is_long,
    )
    if m20 is not None:
        row["IND_DIFF_20"] = str(m20["diff"])
    return [row]


def _ind_watchlist_sort_key(r: dict) -> tuple:
    rt = str(r.get("ROW_TYPE", "STALLED"))
    try:
        readiness = float(r.get("READINESS", 9999) or 9999)
    except (TypeError, ValueError):
        readiness = 9999.0
    return (_IND_WL_ROW_RANK.get(rt, 9), readiness, str(r.get("SYMBOL", "")))


def _merge_dual_stream_watchlists(wl_long: list[dict], wl_short: list[dict], cfg: BRTConfig) -> list[dict]:
    """IND indicator_buy=only uses the long stream watchlist only (trade-aligned long diff)."""
    if _normalize_indicator_buy(getattr(cfg, "indicator_buy", "off")) == "only":
        return list(wl_long)
    return list(wl_long) + list(wl_short)


def _finalize_ind_watchlist(rows: list[dict], cfg: BRTConfig) -> list[dict]:
    """Dedupe by symbol, sort by row priority then readiness; cap to ind_watchlist_max_rows."""
    if not rows:
        return rows
    if bool(getattr(cfg, "ind_watchlist_scanner_require_latest_asof", True)):
        asof_keys = [
            str(r.get("AS_OF_DATE", "") or "").replace("-", "")[:8]
            for r in rows
            if str(r.get("AS_OF_DATE", "") or "").strip()
        ]
        if asof_keys:
            latest_asof = max(asof_keys)
            adjusted: list[dict] = []
            for r in rows:
                if str(r.get("ROW_TYPE", "")) != "SCANNER":
                    adjusted.append(r)
                    continue
                d = str(r.get("AS_OF_DATE", "") or "").replace("-", "")[:8]
                if d == latest_asof:
                    adjusted.append(r)
                else:
                    rr = dict(r)
                    rr["ROW_TYPE"] = "STALLED"
                    rr["STATUS"] = "STALLED"
                    rr["READINESS"] = "9999"
                    rr["TRIGGER_HINT"] = (
                        f"Stale last bar ({d}); universe latest session is {latest_asof}."
                    )
                    gates = str(rr.get("GATES_REMAINING", "") or "").strip()
                    rr["GATES_REMAINING"] = (
                        f"{gates}; stale_asof" if gates else "stale_asof"
                    )
                    adjusted.append(rr)
            rows = adjusted
    by_sym: dict[str, dict] = {}
    for r in rows:
        sym = str(r.get("SYMBOL", "") or "").strip().upper()
        if not sym:
            continue
        prev = by_sym.get(sym)
        if prev is None or _ind_watchlist_sort_key(r) < _ind_watchlist_sort_key(prev):
            by_sym[sym] = r
    rows = list(by_sym.values())
    rows = sorted(rows, key=_ind_watchlist_sort_key)
    max_rows = int(getattr(cfg, "ind_watchlist_max_rows", 250) or 0)
    if max_rows > 0 and len(rows) > max_rows:
        rows = rows[:max_rows]
    return rows


def _watchlist_for_symbol(
    sym: str,
    scanner: list[dict],
    pending_final: list[dict],
    cfg: BRTConfig,
    n: int,
    index_iso: list[str],
    close_arr: Any,
    open_arr: Any,
    high_arr: Any,
    low_arr: Any,
    breakout_retest_rows: Optional[list[dict]],
    pre: Optional[Any] = None,
    entry_side: str = "long",
    rs_st: Optional[np.ndarray] = None,
    rs_sp: Optional[np.ndarray] = None,
) -> list[dict]:
    if _normalize_indicator_buy(getattr(cfg, "indicator_buy", "off")) == "only":
        return _build_ind_watchlist(
            sym,
            scanner,
            cfg,
            n,
            index_iso,
            close_arr,
            open_arr,
            high_arr,
            low_arr,
            pre,
            entry_side,
            rs_st=rs_st,
            rs_sp=rs_sp,
        )
    return _build_brt_watchlist(
        sym,
        scanner,
        pending_final,
        cfg,
        n,
        index_iso,
        close_arr,
        open_arr,
        high_arr,
        low_arr,
        breakout_retest_rows,
    )


def _build_brt_watchlist(
    sym: str,
    scanner: list[dict],
    pending_final: list[dict],
    cfg: BRTConfig,
    n: int,
    index_iso: list[str],
    close_arr: Any,
    open_arr: Any,
    high_arr: Any,
    low_arr: Any,
    breakout_retest_rows: Optional[list[dict]] = None,
) -> list[dict]:
    """
    Combine scanner (ready last-bar) rows with still-pending maturities at end of series.
    GATES_REMAINING / TRIGGER_HINT are heuristics from last bar only, not a full gate replay.
    """
    rows: list[dict] = []
    if n < 1:
        return rows
    li = n - 1
    last_iso = index_iso[li] if li < len(index_iso) else ""
    last_close = float(close_arr[li]) if li < len(close_arr) else float("nan")
    last_open = float(open_arr[li]) if li < len(open_arr) else float("nan")
    scanner_z: set[float] = set()
    for s in scanner:
        zcv = s.get("zone_center")
        try:
            zf = float(zcv) if zcv is not None and str(zcv).strip() != "" else float("nan")
            if zf == zf:
                scanner_z.add(round(zf, 4))
        except (TypeError, ValueError):
            pass
        md = s.get("maturity_date", "")
        if hasattr(md, "strftime"):
            md = md.strftime("%Y-%m-%d") if hasattr(md, "strftime") else str(md)
        cad = s.get("close_above_date", "")
        if hasattr(cad, "strftime"):
            cad = cad.strftime("%Y-%m-%d") if hasattr(cad, "strftime") else str(cad)
        _wl_long = str(getattr(cfg, "entry_type", "long") or "long").strip().lower() != "short"
        _th_scan = _watchlist_entry_open_csv_fields(
            cfg,
            float(s.get("signal_bar_low") or 0),
            float(s.get("signal_bar_high") or 0),
            is_long=_wl_long,
            scanner_row=s,
            prior_close=float(s.get("prior_day_close") or 0),
        )
        _band_scan = _th_scan.get("ENTRY_OPEN_BAND", "")
        if _wl_long and _band_scan:
            _open_hint = f" Long: buy only if next open in [{_band_scan}]."
        elif (not _wl_long) and _band_scan:
            _open_hint = f" Short: sell only if next open in [{_band_scan}]."
        elif _th_scan.get("MAX_ENTRY_OPEN"):
            _open_hint = f" Long: buy only if open <= {_th_scan['MAX_ENTRY_OPEN']}."
        elif _th_scan.get("MIN_ENTRY_OPEN"):
            _open_hint = f" Short: sell only if open >= {_th_scan['MIN_ENTRY_OPEN']}."
        else:
            _open_hint = ""
        rows.append(
            {
                "ROW_TYPE": "SCANNER",
                "SYMBOL": sym,
                "AS_OF_DATE": last_iso,
                "ENTRY_DATE": s.get("date", ""),
                "CLOSE": f"{float(s['close']):.2f}" if s.get("close") is not None else "",
                "STOP_LOSS": f"{float(s['stop']):.2f}" if s.get("stop") is not None else "",
                "TARGET": f"{float(s['target']):.2f}" if s.get("target") is not None else "",
                **_th_scan,
                "ZONE_CENTER": f"{float(s.get('zone_center', 0)):.4f}" if s.get("zone_center") is not None else "",
                "ZONE_LOW": "",
                "ZONE_HIGH": "",
                "TOUCH_COUNT": "",
                "STATUS": "PASSED_ALL_GATES_ENTRY_LAST_BAR",
                "GATES_REMAINING": "",
                "TRIGGER_HINT": (
                    "All entry gates passed; next session open per BRT (last bar of data)."
                    + _open_hint
                ),
                "LAST_CLOSE": f"{last_close:.2f}" if last_close == last_close else "",
                "MATURITY_DATE": str(md) if md is not None else "",
                "CLOSE_ABOVE_DATE": str(cad) if cad is not None else "",
            }
        )
    # Zone centers that will appear on PENDING rows (for deduping APPROACHING_RETEST vs same setup).
    pending_z: set[float] = set()
    for p in pending_final:
        zc0 = p.get("zone_center")
        pz: float | None = None
        try:
            zf0 = float(zc0) if zc0 is not None and str(zc0).strip() != "" else float("nan")
            pz = round(zf0, 4) if zf0 == zf0 else None
        except (TypeError, ValueError):
            pz = None
        if pz is not None and pz not in scanner_z:
            pending_z.add(pz)
    eval_mode = str(getattr(cfg, "entry_eval_mode", "pending") or "pending").strip().lower()
    for p in pending_final:
        zc_raw = p.get("zone_center")
        zcr: float | None = None
        try:
            zf = float(zc_raw) if zc_raw is not None and str(zc_raw).strip() != "" else float("nan")
            zcr = round(zf, 4) if zf == zf else None
        except (TypeError, ValueError):
            zcr = None
        if zcr is not None and zcr in scanner_z:
            continue
        try:
            zl = float(p.get("zone_low", 0) or 0)
        except (TypeError, ValueError):
            zl = 0.0
        try:
            zh = float(p.get("zone_high", 0) or 0)
        except (TypeError, ValueError):
            zh = 0.0
        mb = int(p.get("maturity_bar", -1))
        mat_iso = index_iso[mb] if 0 <= mb < len(index_iso) else ""
        tc = p.get("touch_count", "")
        hints: list[str] = []
        if bool(getattr(cfg, "require_close_gt_open", True)) and last_close == last_close and last_open == last_open:
            if last_close <= last_open:
                hints.append("bullish_bar: need Close>Open on evaluation bar (typical long entry gate)")
        if getattr(cfg, "growth_filter_enabled", False) and int(getattr(cfg, "growth_bars", 0) or 0) > 0:
            _g_ago = _growth_ago_bar_index(li, cfg)
            if _g_ago >= 0 and float(close_arr[li]) < float(close_arr[_g_ago]):
                gb = int(cfg.growth_bars)
                hints.append(f"growth_filter: need Close >= close from {gb} bars ago on eval bar")
        if zl > 0 and zh > 0:
            hints.append(f"zone_band [{zl:.4f} .. {zh:.4f}]")
        if eval_mode == "row_local":
            hints.append("row_local: touch/maturity may defer to next bar; compare maturity_bar vs last bar")
        mid = 0.5 * (zl + zh) if zl > 0 and zh > 0 else (float(zc_raw) if zcr is not None else float("nan"))
        trigger_hint = ""
        if mid == mid and zl > 0 and zh > 0:
            trigger_hint = (
                f"Watch zone: hold/develop within [{zl:.4f},{zh:.4f}]; reference mid ~{mid:.4f}. "
                f"Entry target: next open after gates pass (not a limit price)."
            )
        elif zcr is not None:
            trigger_hint = f"Watch zone_center ~{zcr:.4f}; entry at next open after gates pass."
        else:
            trigger_hint = "Entry at next session open after full gate stack passes."
        _sig_lo = float(low_arr[li]) if li < len(low_arr) else float("nan")
        _sig_hi = float(high_arr[li]) if li < len(high_arr) else float("nan")
        _prior_li = float(close_arr[li - 1]) if li >= 1 and li - 1 < len(close_arr) else float("nan")
        _th_pend = _watchlist_entry_open_csv_fields(
            cfg, _sig_lo, _sig_hi, is_long=True, prior_close=_prior_li
        )
        rows.append(
            {
                "ROW_TYPE": "PENDING",
                "SYMBOL": sym,
                "AS_OF_DATE": last_iso,
                "ENTRY_DATE": "",
                "CLOSE": "",
                "STOP_LOSS": "",
                "TARGET": "",
                **_th_pend,
                "ZONE_CENTER": f"{float(zc_raw):.4f}" if zc_raw is not None and str(zc_raw).strip() != "" else "",
                "ZONE_LOW": f"{zl:.4f}" if zl > 0 else "",
                "ZONE_HIGH": f"{zh:.4f}" if zh > 0 else "",
                "TOUCH_COUNT": str(tc) if tc is not None else "",
                "STATUS": "PENDING_MATURITY_NOT_ENTERED",
                "GATES_REMAINING": "; ".join(hints) if hints else "run_full_gates_next_bar",
                "TRIGGER_HINT": trigger_hint,
                "LAST_CLOSE": f"{last_close:.2f}" if last_close == last_close else "",
                "MATURITY_DATE": mat_iso,
                "CLOSE_ABOVE_DATE": "",
            }
        )
    # --- APPROACHING_RETEST: DI breakout with first retest not yet observed; growth OK; price near zone band ---
    if breakout_retest_rows:
        _scan_delta = max(0, int(getattr(cfg, "sheet_breakout_scan_start_row_delta", 2) or 0))
        retest_min_delta = _scan_delta if _scan_delta > 0 else 1
        growth_on = (
            bool(getattr(cfg, "growth_filter_enabled", False))
            and int(getattr(cfg, "growth_bars", 0) or 0) > 0
            and _growth_ago_bar_index(li, cfg) >= 0
        )
        seen_br: set[tuple] = set()
        for r in breakout_retest_rows:
            if str(r.get("SYMBOL", sym) or sym).strip().upper() != sym.strip().upper():
                continue
            riso = str(r.get("retest_iso") or "").strip()
            rb = r.get("retest_bar")
            if riso or rb is not None:
                continue
            b = int(r.get("breakout_bar", -1) or -1)
            if b < 0 or b >= n:
                continue
            if li < b + retest_min_delta:
                continue
            if li - b > _WATCHLIST_BR_MAX_BARS_AFTER_BREAKOUT:
                continue
            try:
                zl = float(r.get("zone_lower", float("nan")))
                zu = float(r.get("zone_upper", float("nan")))
            except (TypeError, ValueError):
                continue
            if not (np.isfinite(zl) and np.isfinite(zu) and zl > 0 and zu > zl):
                continue
            lc = last_close
            if not (lc == lc and lc > 0):
                continue
            if lc < zl:
                dist_frac = (zl - lc) / lc
            elif lc > zu:
                dist_frac = (lc - zu) / lc
            else:
                dist_frac = 0.0
            if dist_frac > _WATCHLIST_ZONE_EDGE_PROXIMITY_FRAC:
                continue
            growth_ok = True
            if growth_on:
                _g_ago = _growth_ago_bar_index(li, cfg)
                growth_ok = _g_ago >= 0 and float(close_arr[li]) >= float(close_arr[_g_ago])
            if not growth_ok:
                continue
            dedupe_k = (b, round(zl, 4), round(zu, 4))
            if dedupe_k in seen_br:
                continue
            seen_br.add(dedupe_k)
            bo_iso = str(r.get("breakout_iso") or "").strip()
            mid = 0.5 * (zl + zu)
            am = round(mid, 4) if mid == mid else None
            if am is not None and (am in scanner_z or am in pending_z):
                continue
            zc_s = f"{mid:.4f}" if mid == mid else ""
            bo_disp = bo_iso
            if len(bo_iso) >= 8 and bo_iso[:8].isdigit():
                bo_disp = f"{bo_iso[:4]}-{bo_iso[4:6]}-{bo_iso[6:8]}"
            hint = (
                f"First retest not yet in sample after breakout {bo_disp}; "
                f"price within {_WATCHLIST_ZONE_EDGE_PROXIMITY_FRAC:.0%} of zone [{zl:.4f},{zu:.4f}] or inside band. "
                f"Next step: overlap retest window (BY/DW) + eval-bar gates."
            )
            gates_bits = [
                f"growth_3y_ok={'yes' if growth_ok else 'no'}",
                f"dist_to_zone_edge_frac={dist_frac:.6f}",
                f"breakout_bar={b}",
            ]
            _prior_br = float(close_arr[li - 1]) if li >= 1 and li - 1 < len(close_arr) else float("nan")
            _th_br = _watchlist_entry_open_csv_fields(
                cfg,
                float(low_arr[li]),
                float(high_arr[li]),
                is_long=True,
                prior_close=_prior_br,
            )
            rows.append(
                {
                    "ROW_TYPE": "APPROACHING_RETEST",
                    "SYMBOL": sym,
                    "AS_OF_DATE": last_iso,
                    "ENTRY_DATE": "",
                    "CLOSE": "",
                    "STOP_LOSS": "",
                    "TARGET": "",
                    **_th_br,
                    "ZONE_CENTER": zc_s,
                    "ZONE_LOW": f"{zl:.4f}",
                    "ZONE_HIGH": f"{zu:.4f}",
                    "TOUCH_COUNT": "",
                    "STATUS": "APPROACHING_RETEST_PENDING_FIRST_OVERLAP",
                    "GATES_REMAINING": "; ".join(gates_bits),
                    "TRIGGER_HINT": hint,
                    "LAST_CLOSE": f"{last_close:.2f}" if last_close == last_close else "",
                    "MATURITY_DATE": bo_iso,
                    "CLOSE_ABOVE_DATE": "",
                    "GROWTH_OK": "yes" if growth_ok else "no",
                    "DIST_TO_ZONE_FRAC": f"{dist_frac:.6f}",
                    "BREAKOUT_ISO": bo_iso,
                }
            )
    return rows


def write_brt_watchlist(watchlist: list[dict], path: str) -> None:
    cols = [
        "ROW_TYPE",
        "SYMBOL",
        "AS_OF_DATE",
        "ENTRY_DATE",
        "CLOSE",
        "STOP_LOSS",
        "TARGET",
        "SIGNAL_BAR_LOW",
        "SIGNAL_BAR_HIGH",
        "PRIOR_DAY_CLOSE",
        "TOO_HIGH_MULTIPLIER",
        "TOO_LOW_MULTIPLIER",
        "MIN_ENTRY_OPEN",
        "MAX_ENTRY_OPEN",
        "ENTRY_OPEN_BAND",
        "ZONE_CENTER",
        "ZONE_LOW",
        "ZONE_HIGH",
        "TOUCH_COUNT",
        "STATUS",
        "GATES_REMAINING",
        "TRIGGER_HINT",
        "LAST_CLOSE",
        "MATURITY_DATE",
        "CLOSE_ABOVE_DATE",
        "GROWTH_OK",
        "DIST_TO_ZONE_FRAC",
        "BREAKOUT_ISO",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in watchlist:
            w.writerow([r.get(c, "") for c in cols])


def write_ind_watchlist(watchlist: list[dict], path: str) -> None:
    """IND indicator-only watchlist (IND_DIFF / IND_SCORE gates and trend)."""
    cols = [
        "ROW_TYPE",
        "SYMBOL",
        "AS_OF_DATE",
        "ENTRY_DATE",
        "CLOSE",
        "STOP_LOSS",
        "TARGET",
        "SIGNAL_BAR_LOW",
        "SIGNAL_BAR_HIGH",
        "PRIOR_DAY_CLOSE",
        "TOO_HIGH_MULTIPLIER",
        "TOO_LOW_MULTIPLIER",
        "MIN_ENTRY_OPEN",
        "MAX_ENTRY_OPEN",
        "ENTRY_OPEN_BAND",
        "LAST_CLOSE",
        "IND_DIFF",
        "IND_SCORE",
        "IND_ENTRY_NEUTRAL_N",
        "IND_ENTRY_BULL_N",
        "DIFF_GATE",
        "SCORE_GATE",
        "NEUTRAL_MAX",
        "DIFF_GAP",
        "SCORE_GAP",
        "NEUTRAL_GAP",
        "ATR_PCT_AT_TRIGGER",
        "ATR_GATE",
        "ATR_GAP",
        "IND_DIFF_5",
        "IND_DIFF_20",
        "IND_DIFF_DELTA_5",
        "IND_SCORE_5",
        "IND_SCORE_DELTA_5",
        "TREND",
        "READINESS",
        "STATUS",
        "GATES_REMAINING",
        "TRIGGER_HINT",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in watchlist:
            w.writerow([r.get(c, "") for c in cols])


def write_ind_indicators_while_held(rows: list[dict], path: str) -> None:
    """Daily trade-aligned IND summary counts for each day a position was held."""
    cols = [
        "SYMBOL",
        "SIDE",
        "DATE_OPENED",
        "DATE_CLOSED",
        "ENTRY_PRICE",
        "EXIT_PRICE",
        "HOLD_DATE",
        "HOLD_DAY_CLOSE",
        "IND_ENTRY_BULL_N",
        "IND_ENTRY_BEAR_N",
        "IND_DIFF",
        "IND_ENTRY_NEUTRAL_N",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([r.get(c, "") for c in cols])


def write_brt_scanner(
    scanner: list[dict],
    path: str,
    cfg: Optional[BRTConfig] = None,
) -> bool:
    """Write scanner CSV. Returns False when there are no candidates (no file created)."""
    if not scanner:
        return False
    ind_h = _brt_indicator_header_suffix(cfg)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "SYMBOL",
                "DATE",
                "CLOSE",
                "STOP_LOSS",
                "TARGET",
                "SIGNAL_BAR_LOW",
                "SIGNAL_BAR_HIGH",
                "PRIOR_DAY_CLOSE",
                "TOO_HIGH_MULTIPLIER",
                "TOO_LOW_MULTIPLIER",
                "MIN_ENTRY_OPEN",
                "MAX_ENTRY_OPEN",
                "ENTRY_OPEN_BAND",
                "ATR_PCT_AT_TRIGGER",
                "ATR_PCT_AT_ENTRY",
                "ZONE_CENTER",
            ]
            + ind_h
        )
        for s in scanner:
            _band_lim = _entry_open_band_fields(
                float(s.get("signal_bar_low") or 0),
                float(s.get("signal_bar_high") or 0),
                float(s.get("prior_day_close") or 0),
                float(s.get("too_high_multiplier") or 0),
                float(s.get("too_low_multiplier") or 0),
                str(getattr(cfg, "entry_type", "long") or "long").strip().lower() != "short"
                if cfg is not None
                else True,
            )
            _min_o = _fmt_limit_price(s.get("min_entry_open") or _band_lim.get("min_entry_open"))
            _max_o = _fmt_limit_price(s.get("max_entry_open") or _band_lim.get("max_entry_open"))
            _band_s = ""
            if _min_o and _max_o:
                _band_s = f"{_min_o} .. {_max_o}"
            elif _min_o:
                _band_s = f">= {_min_o}"
            elif _max_o:
                _band_s = f"<= {_max_o}"
            _atr_pct = s.get("atr_pct_at_entry")
            _atr_pct_s = ""
            if _atr_pct is not None:
                try:
                    _apf = float(_atr_pct)
                    if np.isfinite(_apf):
                        _atr_pct_s = f"{_apf:.2f}"
                except (TypeError, ValueError):
                    pass
            _atr_trig = s.get("atr_pct_at_trigger")
            _atr_trig_s = ""
            if _atr_trig is not None:
                try:
                    _atf = float(_atr_trig)
                    if np.isfinite(_atf):
                        _atr_trig_s = f"{_atf:.2f}"
                except (TypeError, ValueError):
                    pass
            row = [
                s["symbol"],
                s["date"],
                f"{s['close']:.2f}",
                f"{s['stop']:.2f}",
                f"{s['target']:.2f}",
                _fmt_limit_price(s.get("signal_bar_low")),
                _fmt_limit_price(s.get("signal_bar_high")),
                _fmt_limit_price(s.get("prior_day_close") or _band_lim.get("prior_day_close")),
                (
                    f"{float(s['too_high_multiplier']):.4f}"
                    if s.get("too_high_multiplier") not in (None, "")
                    else ""
                ),
                (
                    f"{float(s['too_low_multiplier']):.4f}"
                    if s.get("too_low_multiplier") not in (None, "")
                    else ""
                ),
                _min_o,
                _max_o,
                _band_s,
                _atr_trig_s,
                _atr_pct_s,
                f"{s.get('zone_center', 0):.4f}",
            ]
            if ind_h:
                ei = s.get("entry_indicators") or {}
                if ei and "IND_SCORE" not in ei:
                    try:
                        from brt_entry_indicators import apply_ind_score_to_entry_indicators
                    except ImportError:
                        from stock_analysis.brt_entry_indicators import apply_ind_score_to_entry_indicators
                    apply_ind_score_to_entry_indicators(ei)
                row.extend(_brt_indicator_row_from_dict(ei) if ei else _empty_indicator_row_cells())
            w.writerow(row)
    return True


def _brt_indicator_row_from_dict(entry_indicators: dict[str, str]) -> list[str]:
    try:
        from brt_entry_indicators import format_indicator_csv_row
    except ImportError:
        from stock_analysis.brt_entry_indicators import format_indicator_csv_row
    return format_indicator_csv_row(entry_indicators)


def _empty_indicator_row_cells() -> list[str]:
    try:
        from brt_entry_indicators import format_indicator_csv_row
    except ImportError:
        from stock_analysis.brt_entry_indicators import format_indicator_csv_row
    return format_indicator_csv_row({})


def write_brt_short_candidates(short_cands: list[dict], path: str) -> None:
    """Write matured-below-zone signals (potential shorts for future use)."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["SYMBOL", "DATE", "ZONE_CENTER", "CLOSE", "TOUCH_COUNT"])
        for s in short_cands:
            w.writerow([s["symbol"], s["date"], f"{s['zone_center']:.4f}", f"{s['close']:.2f}", s["touch_count"]])


def _write_zone_debug_files(
    sym: str,
    df: pd.DataFrame,
    level3: dict,
    zone_entries_debug: list,
    band_pct: float,
    output_dir: str,
    ts: str,
    file_prefix: str = "BRT",
) -> None:
    """Write {prefix}_ZONES_<sym>_<ts>.csv and {prefix}_ZONES_ENTRIES_<sym>_<ts>.csv."""
    zones_path = os.path.join(output_dir, f"{file_prefix}_ZONES_{sym}_{ts}.csv")
    yh_events = level3.get("yh_zone_events") or []
    vec_events = level3.get("vec_zone_events") or []
    pbr_events = level3.get("pbr_zone_events") or []
    brt_events = level3.get("brt_matured_zone_events") or []
    n_zone_rows = 0
    if vec_events:
        with open(zones_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(
                [
                    "SYMBOL",
                    "DATE",
                    "BAR_INDEX",
                    "CONFLUENCE_BAR",
                    "ACTIVATION_BAR",
                    "ZONE_ORIGIN",
                    "ZONE_CENTER",
                    "ZONE_LOW",
                    "ZONE_HIGH",
                    "TOUCH_PRICE",
                    "VEC_POC",
                    "VEC_PRIOR_EXTREME",
                    "VEC_CONFLUENCE_DIST_PCT",
                    "ACTIVATION_PRICE",
                    "MATURED_NOW",
                    "MATURITY_DATE",
                ]
            )
            for ev in vec_events:
                ab = int(ev.get("activation_bar", -1))
                cf_bar = int(ev.get("yh_bar", -1))
                if ab < 0 or ab >= len(df):
                    continue
                n_zone_rows += 1
                dt = df.index[ab].strftime("%Y-%m-%d") if hasattr(df.index[ab], "strftime") else str(df.index[ab])[:10]
                zc = float(ev.get("zone_center", ev.get("touch_price", 0.0)))
                zl = float(ev.get("zone_lower", np.nan))
                zh = float(ev.get("zone_upper", np.nan))
                tp = float(ev.get("touch_price", zc))
                act_p = float(ev.get("activation_price", np.nan))
                poc = float(ev.get("vec_poc", np.nan))
                ext = float(ev.get("vec_prior_extreme", np.nan))
                dist = float(ev.get("vec_confluence_dist_pct", np.nan))
                w.writerow(
                    [
                        sym,
                        dt,
                        ab,
                        cf_bar,
                        ab,
                        _zone_origin_label(4),
                        f"{zc:.4f}",
                        f"{zl:.4f}" if np.isfinite(zl) else "",
                        f"{zh:.4f}" if np.isfinite(zh) else "",
                        f"{tp:.4f}",
                        f"{poc:.4f}" if np.isfinite(poc) else "",
                        f"{ext:.4f}" if np.isfinite(ext) else "",
                        f"{dist:.6f}" if np.isfinite(dist) else "",
                        f"{act_p:.4f}" if np.isfinite(act_p) else "",
                        1,
                        dt,
                    ]
                )
        print(f"Zones written: {zones_path} ({n_zone_rows} rows from {len(vec_events)} VEC activations)")
    elif pbr_events:
        try:
            from pbr_zones import PBR_STRENGTH_FIELDS
        except ImportError:
            from stock_analysis.pbr_zones import PBR_STRENGTH_FIELDS
        strength_cols = [f.upper() for f in PBR_STRENGTH_FIELDS]
        with open(zones_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(
                [
                    "SYMBOL",
                    "DATE",
                    "BAR_INDEX",
                    "PIVOT_MONDAY",
                    "ACTIVATION_BAR",
                    "ZONE_ORIGIN",
                    "ZONE_CENTER",
                    "ZONE_LOW",
                    "ZONE_HIGH",
                    "PBR_ZONE_ID",
                    "BREAKOUT_MONDAY",
                    "CONF_MONDAY",
                    "RETEST_BAR",
                    "ENTRY_SIGNAL_BAR",
                    "ENTRY_FILL_BAR",
                    "HAS_TRADE",
                ]
                + strength_cols
            )
            for ev in pbr_events:
                ab = int(ev.get("activation_bar", ev.get("yh_bar", -1)))
                if ab < 0 or ab >= len(df):
                    continue
                n_zone_rows += 1
                dt = df.index[ab].strftime("%Y-%m-%d") if hasattr(df.index[ab], "strftime") else str(df.index[ab])[:10]
                zc = float(ev.get("zone_center", ev.get("touch_price", 0.0)))
                zl = float(ev.get("zone_lower", ev.get("zone_lower_f", np.nan)))
                zh = float(ev.get("zone_upper", ev.get("zone_upper_f", np.nan)))
                sig = int(ev.get("entry_signal_bar", -1))
                strength_vals = []
                for field in PBR_STRENGTH_FIELDS:
                    v = ev.get(field)
                    if v is None:
                        strength_vals.append("")
                    else:
                        try:
                            fv = float(v)
                            strength_vals.append(f"{fv:.6f}" if np.isfinite(fv) else "")
                        except (TypeError, ValueError):
                            strength_vals.append("")
                w.writerow(
                    [
                        sym,
                        dt,
                        ab,
                        ev.get("pivot_monday", ""),
                        ab,
                        _zone_origin_label(5),
                        f"{zc:.4f}",
                        f"{zl:.4f}" if np.isfinite(zl) else "",
                        f"{zh:.4f}" if np.isfinite(zh) else "",
                        ev.get("pbr_zone_id", ""),
                        ev.get("breakout_monday", ""),
                        ev.get("conf_monday", ""),
                        ev.get("retest_bar", -1),
                        sig,
                        ev.get("entry_fill_bar", -1),
                        1 if sig >= 0 else 0,
                    ]
                    + strength_vals
                )
        print(f"Zones written: {zones_path} ({n_zone_rows} rows from {len(pbr_events)} PBR zones)")
    elif yh_events:
        with open(zones_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(
                [
                    "SYMBOL",
                    "DATE",
                    "BAR_INDEX",
                    "YH_BAR",
                    "ACTIVATION_BAR",
                    "ZONE_ORIGIN",
                    "ZONE_CENTER",
                    "ZONE_LOW",
                    "ZONE_HIGH",
                    "TOUCH_PRICE",
                    "ACTIVATION_PRICE",
                    "MATURED_NOW",
                    "MATURITY_DATE",
                ]
            )
            for ev in yh_events:
                ab = int(ev.get("activation_bar", -1))
                yh_bar = int(ev.get("yh_bar", -1))
                if ab < 0 or ab >= len(df):
                    continue
                n_zone_rows += 1
                dt = df.index[ab].strftime("%Y-%m-%d") if hasattr(df.index[ab], "strftime") else str(df.index[ab])[:10]
                zc = float(ev.get("zone_center", ev.get("touch_price", 0.0)))
                zl = float(ev.get("zone_lower", np.nan))
                zh = float(ev.get("zone_upper", np.nan))
                tp = float(ev.get("touch_price", zc))
                act_p = float(ev.get("activation_price", np.nan))
                w.writerow(
                    [
                        sym,
                        dt,
                        ab,
                        yh_bar,
                        ab,
                        _zone_origin_label(3),
                        f"{zc:.4f}",
                        f"{zl:.4f}" if np.isfinite(zl) else "",
                        f"{zh:.4f}" if np.isfinite(zh) else "",
                        f"{tp:.4f}",
                        f"{act_p:.4f}" if np.isfinite(act_p) else "",
                        1,
                        dt,
                    ]
                )
        print(f"Zones written: {zones_path} ({n_zone_rows} rows from {len(yh_events)} YH activations)")
    elif brt_events:
        with open(zones_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(
                [
                    "SYMBOL",
                    "DATE",
                    "BAR_INDEX",
                    "PIVOT_BAR",
                    "ZONE_ORIGIN",
                    "ZONE_CENTER",
                    "ZONE_LOW",
                    "ZONE_HIGH",
                    "TOUCH_PRICE",
                    "MATURED_NOW",
                    "MATURITY_DATE",
                ]
            )
            for ev in brt_events:
                mb = int(ev.get("maturity_bar", -1))
                pb = int(ev.get("pivot_bar", -1))
                if mb < 0 or mb >= len(df):
                    continue
                n_zone_rows += 1
                dt = df.index[mb].strftime("%Y-%m-%d") if hasattr(df.index[mb], "strftime") else str(df.index[mb])[:10]
                zc = float(ev.get("zone_center", ev.get("touch_price", 0.0)))
                zl = float(ev.get("zone_lower", np.nan))
                zh = float(ev.get("zone_upper", np.nan))
                tp = float(ev.get("touch_price", zc))
                w.writerow(
                    [
                        sym,
                        dt,
                        mb,
                        pb,
                        _zone_origin_label(1),
                        f"{zc:.4f}",
                        f"{zl:.4f}" if np.isfinite(zl) else "",
                        f"{zh:.4f}" if np.isfinite(zh) else "",
                        f"{tp:.4f}",
                        1,
                        dt,
                    ]
                )
        print(f"Zones written: {zones_path} ({n_zone_rows} rows from {len(brt_events)} BRT matured events)")
    else:
        zc_arr = level3["zone_center"]
        zl_arr = level3["zone_low"]
        zh_arr = level3["zone_high"]
        tc_arr = level3["touch_count_long"]
        tp_arr = level3["touch_price"]
        matured = level3.get("matured_now")
        origin_s = level3.get("zone_touch_origin")
        with open(zones_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(
                [
                    "SYMBOL",
                    "DATE",
                    "BAR_INDEX",
                    "ZONE_ORIGIN",
                    "ZONE_CENTER",
                    "ZONE_LOW",
                    "ZONE_HIGH",
                    "TOUCH_COUNT_LONG",
                    "TOUCH_PRICE",
                    "MATURED_NOW",
                    "MATURITY_DATE",
                ]
            )
            for i in range(len(df)):
                zc = zc_arr.iloc[i] if hasattr(zc_arr, "iloc") else zc_arr[i]
                if pd.isna(zc) or (isinstance(zc, (int, float)) and float(zc) <= 0):
                    continue
                n_zone_rows += 1
                dt = df.index[i].strftime("%Y-%m-%d") if hasattr(df.index[i], "strftime") else str(df.index[i])[:10]
                zl = zl_arr.iloc[i] if hasattr(zl_arr, "iloc") else zl_arr[i]
                zh = zh_arr.iloc[i] if hasattr(zh_arr, "iloc") else zh_arr[i]
                tc = tc_arr.iloc[i] if hasattr(tc_arr, "iloc") else tc_arr[i]
                tp = tp_arr.iloc[i] if hasattr(tp_arr, "iloc") else tp_arr[i]
                mat = matured.iloc[i] if matured is not None and hasattr(matured, "iloc") else False
                mat_flag = 1 if mat else 0
                mat_date_col = dt if mat_flag else ""
                oc = 0
                if origin_s is not None:
                    oc = int(origin_s.iloc[i] if hasattr(origin_s, "iloc") else origin_s[i])
                w.writerow(
                    [
                        sym,
                        dt,
                        i,
                        _zone_origin_label(oc),
                        f"{float(zc):.4f}",
                        f"{float(zl):.4f}" if not pd.isna(zl) else "",
                        f"{float(zh):.4f}" if not pd.isna(zh) else "",
                        int(tc) if not pd.isna(tc) else "",
                        f"{float(tp):.4f}" if not pd.isna(tp) and tp else "",
                        mat_flag,
                        mat_date_col,
                    ]
                )
        print(f"Zones written: {zones_path} ({n_zone_rows} rows)")

    entries_path = os.path.join(output_dir, f"{file_prefix}_ZONES_ENTRIES_{sym}_{ts}.csv")
    if not zone_entries_debug:
        with open(entries_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(
                [
                    "ENTRY_DATE",
                    "MATURITY_DATE",
                    "ENTRY_PRICE",
                    "ZONE_CENTER",
                    "ZONE_LOW",
                    "ZONE_HIGH",
                    "CURRENT_ZONE_TOP",
                    "TRIGGER_BOTTOM",
                    "MIN_ZONE_ABOVE_CENTER",
                    "ZONE_ABOVE_CENTER_CHOSEN",
                    "BOTTOM_ZONE_ABOVE",
                    "PCT_ENTRY_TO_BOTTOM_ZONE_ABOVE",
                    "ALL_ZONE_CENTERS_IN_WINDOW",
                ]
            )
        print(f"Zone entries written: {entries_path} (0 entries)")
        return
    with open(entries_path, "w", newline="") as f:
        w = csv.writer(f)
        headers = list(zone_entries_debug[0].keys())
        w.writerow(headers)
        for row in zone_entries_debug:
            w.writerow([row.get(h, "") for h in headers])
    print(f"Zone entries written: {entries_path} ({len(zone_entries_debug)} entries)")


def collect_brt_pivots(
    sym: str,
    df: pd.DataFrame,
    pivot_high: pd.Series,
    pivot_low: pd.Series,
    ph_price: pd.Series,
    pl_price: pd.Series,
    struct: dict,
) -> list[tuple[str, str, str, float, str]]:
    """
    Collect all pivot rows for one symbol (same info as RL_Pivots plus STRENGTH).
    Returns list of (symbol, date_str, type_str, price, strength_str).
    STRENGTH is MAJOR or MINOR from market structure (HH/LL vs HL/LH).
    """
    rows: list[tuple[str, str, str, float, str]] = []
    maj_ph = struct.get("major_pivot_high")
    maj_pl = struct.get("major_pivot_low")
    n = len(df)
    for i in range(n):
        dt_str = df.index[i].strftime("%Y-%m-%d") if hasattr(df.index[i], "strftime") else str(df.index[i])[:10]
        if pivot_high.iloc[i] == 1:
            price = float(ph_price.iloc[i])
            strength = "MAJOR" if (maj_ph is not None and i < len(maj_ph) and maj_ph.iloc[i] == 1) else "MINOR"
            rows.append((sym, dt_str, "PIVOT_HIGH", price, strength))
        if pivot_low.iloc[i] == 1:
            price = float(pl_price.iloc[i])
            strength = "MAJOR" if (maj_pl is not None and i < len(maj_pl) and maj_pl.iloc[i] == 1) else "MINOR"
            rows.append((sym, dt_str, "PIVOT_LOW", price, strength))
    return rows


def write_brt_pivots(rows: list[tuple[str, str, str, float, str]], path: str) -> None:
    """Write BRT_Pivots CSV (same columns as RL_Pivots plus STRENGTH: MAJOR/MINOR)."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["SYMBOL", "DATE", "TYPE", "PRICE", "STRENGTH"])
        for r in rows:
            w.writerow([r[0], r[1], r[2], f"{r[3]:.4f}", r[4]])


def write_brt_summary(closed: list[BRTTrade], path: str, total_pnl_overall: Optional[float] = None) -> None:
    from collections import defaultdict
    by_sym: dict[str, list[BRTTrade]] = defaultdict(list)
    for t in closed:
        by_sym[t.symbol].append(t)
    if total_pnl_overall is None:
        total_pnl_overall = sum(t.pnl_dollars for t in closed)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "SYMBOL",
                "TRADES",
                "WINS",
                "LOSSES",
                "BEs",
                "TOTAL_PNL",
                "AVG_PNL_PCT",
                "PCT_OF_TOTAL_PNL",
                "CURRENT_MARKET_CAP",
                "SECTOR",
                "INDUSTRY",
            ]
        )
        for sym in sorted(by_sym.keys()):
            trades = by_sym[sym]
            wins = sum(1 for t in trades if t.pnl_pct > 0)
            losses = sum(1 for t in trades if t.pnl_pct < 0)
            bes = sum(1 for t in trades if t.pnl_pct == 0)
            total = sum(t.pnl_dollars for t in trades)
            avg_pct = sum(t.pnl_pct for t in trades) / len(trades) if trades else 0
            pct_of_total = (total / total_pnl_overall * 100) if total_pnl_overall and total_pnl_overall != 0 else 0.0
            mc_cur = None
            for t in trades:
                v = getattr(t, "market_cap_current", None)
                if v is not None:
                    mc_cur = float(v)
                    break
            mc_cur_s = f"{mc_cur:.0f}" if mc_cur is not None else ""
            sector = (getattr(trades[0], "sector", None) or "").replace(",", " ") if trades else ""
            industry = (getattr(trades[0], "industry", None) or "").replace(",", " ") if trades else ""
            w.writerow(
                [
                    sym,
                    len(trades),
                    wins,
                    losses,
                    bes,
                    f"{total:.2f}",
                    f"{avg_pct:.2f}%",
                    f"{pct_of_total:.1f}%",
                    mc_cur_s,
                    sector,
                    industry,
                ]
            )


def write_brt_industry_summary(closed: list[BRTTrade], path: str) -> None:
    """Write BRT_INDUSTRY CSV grouped by industry: total PnL, distinct symbols, and trade count."""
    from collections import defaultdict

    pnl_by_industry: dict[str, float] = defaultdict(float)
    symbols_by_industry: dict[str, set[str]] = defaultdict(set)
    trades_by_industry: dict[str, int] = defaultdict(int)

    for t in closed:
        ind = (getattr(t, "industry", None) or "").strip() or "(unknown)"
        pnl_by_industry[ind] += t.pnl_dollars
        symbols_by_industry[ind].add(t.symbol)
        trades_by_industry[ind] += 1

    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["INDUSTRY", "PNL", "Symbols", "Trades"])
        for ind in sorted(pnl_by_industry.keys(), key=lambda k: pnl_by_industry[k], reverse=True):
            pnl = pnl_by_industry[ind]
            symbols_count = len(symbols_by_industry[ind])
            trades_count = trades_by_industry[ind]
            w.writerow([ind, f"{pnl:.2f}", symbols_count, trades_count])


def _write_brt_equity_canonical_outputs(
    output_dir,
    ts: str,
    equity: dict,
    file_prefix: str = "BRT",
) -> None:
    """Persist daily equity (realized-ledger or OHLC) so BRT_DrawdownCalc / audits can replay the same Max_DD."""
    dates = equity.get("equity_dates")
    values = equity.get("equity_values")
    pos = equity.get("equity_positions")
    if not dates or not values or len(dates) != len(values):
        return
    try:
        outp = Path(output_dir)
        outp.mkdir(parents=True, exist_ok=True)
        df_data: dict[str, Any] = {"Date": pd.to_datetime(dates), "Equity": values}
        if pos and len(pos) == len(values):
            df_data["Positions"] = pos
        reg = equity.get("equity_values_regular")
        if reg and len(reg) == len(values):
            df_data["Equity_Regular"] = reg
        pd.DataFrame(df_data).to_csv(outp / f"{file_prefix}_EquityCurve_{ts}.csv", index=False)
        raw = float(equity.get("_max_port_dd_raw", 0) or 0)
        init_sz = float(equity.get("_initial_account_size", 0) or 0)
        meta_row = {
            "Initial_Account_Size": init_sz,
            "Max_Drawdown_fraction": raw,
            "Max_Drawdown_pct": equity.get("Max_Drawdown", ""),
            "Max_Days_Underwater": int(equity.get("Max_Days_Underwater", 0) or 0),
            "Pct_Days_Underwater": equity.get("Pct_Days_Underwater", ""),
            "Aggressive": bool(equity.get("_aggressive")),
        }
        if equity.get("_aggressive"):
            agg_raw = float(equity.get("_aggressive_max_dd_raw", 0) or 0)
            meta_row["Aggressive_Max_Drawdown_fraction"] = agg_raw
            meta_row["Aggressive_Max_Drawdown_pct"] = equity.get("Aggressive_Max_Drawdown", "")
        pd.DataFrame([meta_row]).to_csv(outp / f"{file_prefix}_EquityMeta_{ts}.csv", index=False)
        print(
            f"[FILE] {file_prefix} equity curve (same series as Max_DD in this run; use for BRT_DrawdownCalc): "
            f"{file_prefix}_EquityCurve_{ts}.csv, {file_prefix}_EquityMeta_{ts}.csv"
        )
        _write_aggressive_equity_curve(output_dir, ts, equity, file_prefix)
    except Exception as e:
        print(f"[WARN] Could not write BRT_EquityCurve/Meta: {e}", file=sys.stderr)


def _write_aggressive_equity_curve(
    output_dir,
    ts: str,
    equity: dict,
    file_prefix: str = "BRT",
) -> None:
    """Dedicated aggressive ledger equity curve (when cfg.aggressive / equity['_aggressive'])."""
    if not equity.get("_aggressive"):
        return
    dates = equity.get("equity_dates")
    values = equity.get("equity_values")
    pos = equity.get("equity_positions")
    if not dates or not values or len(dates) != len(values):
        return
    try:
        outp = Path(output_dir)
        init_sz = float(equity.get("_initial_account_size", 0) or 0)
        df_data: dict[str, Any] = {
            "Date": pd.to_datetime(dates),
            "Equity": values,
        }
        if pos and len(pos) == len(values):
            df_data["Positions"] = pos
        if init_sz > 0:
            df_data["Equity_Pct_of_Initial"] = [
                (float(v) / init_sz - 1.0) * 100.0 for v in values
            ]
        path = outp / f"{file_prefix}_EquityCurve_Aggressive_{ts}.csv"
        pd.DataFrame(df_data).to_csv(path, index=False)
        print(f"[FILE] Aggressive equity curve: {path} ({len(values)} days)")
        trim_log = equity.get("aggressive_trim_log")
        if trim_log:
            trim_path = outp / f"{file_prefix}_aggressive_trim_log_{ts}.csv"
            pd.DataFrame(trim_log).to_csv(trim_path, index=False)
            print(f"[FILE] Aggressive trim log: {trim_path} ({len(trim_log)} rows)")
        reg = equity.get("equity_values_regular")
        if reg and len(reg) == len(values):
            passive_path = outp / f"{file_prefix}_EquityCurve_Regular_{ts}.csv"
            passive_df: dict[str, Any] = {
                "Date": pd.to_datetime(dates),
                "Equity": reg,
            }
            if pos and len(pos) == len(values):
                passive_df["Positions"] = pos
            pd.DataFrame(passive_df).to_csv(passive_path, index=False)
            print(
                f"[FILE] Passive OHLC equity curve (comparison): {passive_path} ({len(reg)} days)"
            )
    except Exception as e:
        print(f"[WARN] Could not write aggressive equity curve: {e}", file=sys.stderr)


def write_brt_report(
    cfg: BRTConfig,
    metrics: dict,
    output_dir: str,
    ts: str,
    drive_link: str = "",
    file_prefix: Optional[str] = None,
) -> None:
    """Write BRT_Report CSV with same structure as BRT_Optimization_Audit: full config + all audit metrics.
    After a full run, capital is reported as 1,000,000 / max_positions and Total_PNL is scaled proportionally."""
    link = drive_link or f"https://drive.google.com/drive/search?q={ts}"
    drive_link_cell = f'=hyperlink("{link}","{ts}")'
    cfg_dict = asdict(cfg)
    row: dict[str, Any] = {"Timestamp_Drive": drive_link_cell, "Param_Name": "", "Param_Value": "", "Score": ""}
    for k in _AUDIT_CFG_COLS:
        row[k] = cfg_dict.get(k, "")
    row.update(_metrics_to_audit_row(metrics))
    _apply_aggressive_avg_positions_actual_to_audit_row(row, metrics, cfg)
    # Post-run capital scaling (same for aggressive and non-aggressive):
    # Trades and metrics["Total_PNL"] are already in dollars after _apply_report_dollar_scale_to_trades
    # (brt_cash = 1M/Max_Positions). Scale to report row only if cfg.brt_cash still differs from 1M/max_pos.
    # Do NOT use initial_capital here — that incorrectly doubled Total_PNL when initial_capital=500k.
    max_pos = int(row.get("Max_Positions", 1) or 1)
    if max_pos > 0:
        adjusted_brt_cash = 1_000_000.0 / max_pos
        orig_cash = float(cfg.brt_cash) if getattr(cfg, "brt_cash", None) and cfg.brt_cash > 0 else adjusted_brt_cash
        scale_for_total_pnl = (adjusted_brt_cash / orig_cash) if orig_cash > 0 else 1.0
        total_pnl_val = row.get("Total_PNL", 0)
        if isinstance(total_pnl_val, str):
            total_pnl_val = float(total_pnl_val.replace(",", "").replace("%", "").strip() or 0)
        row["Total_PNL"] = total_pnl_val * scale_for_total_pnl
        # Aggressive_Total_PNL stays from metrics (equity sim on initial_capital); do not overwrite with trade sum.
        row["brt_cash"] = adjusted_brt_cash
        # Profit_Per_Capital_Day scales with Total_PNL (dollars per day)
        cap_days = row.get("Capital_Days") or 0
        try:
            cap_days = int(cap_days) if isinstance(cap_days, (int, float)) else int(float(str(cap_days).strip() or 0))
        except (TypeError, ValueError):
            cap_days = 0
        if cap_days > 0:
            row["Profit_Per_Capital_Day"] = row["Total_PNL"] / cap_days
    headers = _get_audit_cols_order()
    values = [row.get(c, "") for c in headers]
    prefix = file_prefix or _output_file_prefix(cfg)
    path = os.path.join(output_dir, f"{prefix}_Report_{ts}.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerow(values)


# Audit report columns (written in ``brt_audit_columns.get_brt_audit_column_order()`` order; see brt_audit_columns.py)
_AUDIT_CFG_COLS = [
    "pivot_k", "pivot_d", "pivot_disp", "pivot_m", "band_pct", "band_pct_atr", "lookback_long", "zone_maturity_model", "touch_threshold",
    "strong_pivots_enabled",
    "strong_pre_pivot_bars", "strong_pre_pivot_pct", "strong_pre_pivot_pct_atr",
    "strong_post_pivot_bars", "strong_post_pivot_pct", "strong_post_pivot_pct_atr", "strong_pivot_mode",
    "sheet_touch_pullback_bars",
    "zone_include_pre_strong_pivot_lows",
    "zones_from_pivot_lows_enabled",
    "brt_zones",
    "yh_zones",
    "vec_zones",
    "vec_vp_lookback",
    "vec_vp_bin_pct",
    "vec_prior_bars",
    "vec_prior_side",
    "vec_confluence_pct",
    "vec_move_away_pct",
    "vec_min_bars_between",
    "pbr_zones",
    "pbr_breakout_confirmation",
    "pbr_max_days_after_retest",
    "pbr_second_chance_after_win",
    "rl_mode",
    "rl_cash",
    "rl_flush_days",
    "rl_watch_min_score",
    "rl_watch_disable",
    "yh_lookback",
    "yh_move_away_pct",
    "yh_memory_mode",
    "yh_serial_memory",
    "close_above_window", "pending_max_bars", "entry_eval_mode", "row_local_eval_touch_same_bar", "row_local_eval_ttl_bars_after_first_eval", "row_local_require_active_context_match", "level_acceptance_window", "level_acceptance_required",
    "level_acceptance_anchor_mode", "level_acceptance_anchor_window",
    "support_test_enabled", "breakout_bars",
    "tight_range_enabled", "tight_range_threshold_pct", "tight_range_lookback",
    "tradeable_key_level_enabled", "lookback_short",
    "min_touch_count", "max_touch_count_minor", "max_touch_count_short",
    "max_ind_entry_neutral_n", "min_ind_entry_bull_n",
    "min_pivot_run_l_before_entry", "min_pivot_run_h_before_entry", "min_rel_vol_at_entry", "sell_on_low_vol",
    "min_market_cap",
    "max_market_cap",
    "min_hist_ann_ror_avg",
    "min_avg_volume_10d_at_entry",
    "min_atr_pct_at_trigger",
    "max_atr_pct_at_trigger",
    "min_dist_to_52w_high_pct_at_trigger",
    "max_dist_to_52w_high_pct_at_trigger",
    "min_spy_compare_1y_at_trigger",
    "max_spy_compare_1y_at_trigger",
    "min_spy_compare_2y_at_trigger",
    "min_spy_compare_3y_at_trigger",
    "min_beta_at_trigger",
    "max_beta_at_trigger",
    "min_upper_wick_atr_at_trigger",
    "pivot_switch_h_to_l_filter",
    "entry_filter_major_pivot", "entry_filter_is_20bar_high_at_trigger",
    "entry_filter_meteoric_rise", "entry_filter_meteoric_fall",
    "growth_filter_enabled", "growth_bars", "growth_history_slack_bars", "require_close_gt_open", "sheet_red_to_green_entry_enabled", "entry_close_min_range_position",
    "sheet_maturity_lag_bars",
    "sheet_di_breakout_price",
    "sheet_dw_countif_entry_enabled",
    "sheet_dw_countif_include_prior_bar_date",
    "sheet_no_entry_same_bar_after_exit",
    "retest_multi_zone_pick",
    "entry_retest_bullish_growth_only",
    "sheet_di_max_history_bars",
    "compute_beta",
    "use_indicators",
    "use_ind_score",
    "ind_score_weights_path",
    "min_ind_score",
    "mandatory_ind_states_path",
    "indicator_buy",
    "indicator_diff",
    "sell_ind_diff_below",
    "exit_ind_diff_only",
    "indicator_sides",
    "relative_strength_enabled",
    "do_gate_enabled", "do_good_for_bars",
    "dp_gate_enabled", "dp_window_bars", "dp_good_for_bars",
    "sheet_magic_touch_enabled", "sheet_magic_touch_window_bars",
    "displacement_filter_enabled", "displacement_rolling_bars", "displacement_threshold_pct",
    "consolidation_blocker_enabled", "cb_max_box_width_pct",
    "transaction_type", "entry_type", "zone_role_mode", "zone_role_override",
    "brt_cash", "stop_pct", "short_stop_pct", "stop_pct_is_multiplier", "stop_anchor", "target_pct", "use_sma50", "short_target_pct", "too_high_multiplier", "too_low_multiplier",
    "atr_target", "atr_stop", "trailing_stop_increment", "atr_progress", "atr_days", "atr_progress_incremental_stop",
    "sma_stop_days",
    # Realtime predictive filter config + weights (inputs)
    "realtime_filter_enabled", "realtime_filter_threshold", "realtime_filter_use_zscore",
    "weight_touch_count_minor", "weight_zone_cluster_density", "weight_nearby_zones_above",
    "weight_touch_count_major", "weight_pct_entry_to_bottom_zone_above",
    "weight_z_score_at_trigger", "weight_pivot_run_l_before_entry",
    "weight_nearby_zones_below", "weight_pct_drop_to_top_zone_below",
    "weight_rel_vol_at_entry", "weight_displacement_pct_at_entry",
    "weight_lower_wick_atr_at_trigger", "weight_growth_pct_over_period", "weight_beta_at_entry",
    "meteoric_rise_pct", "meteoric_rise_lookback", "meteoric_fall_pct", "meteoric_fall_lookback",
    "post_entry_gain_pct", "post_entry_gain_calendar_days",
    "days_per_year", "exit_at_close_when_stopped", "compute_equity_metrics",
    "initial_capital", "aggressive", "aggressive_margin_interest", "aggressive_max_multiple", "aggressive_avg_positions",
    "aggressive_sizing_equity_cap", "aggressive_sell",
    "margin_utilization",
    "max_positions",
    "symbol_reentry_cooldown_days",
    "allow_secondary_entries",
]

_AGGRESSIVE_METRIC_COLS = [
    "Aggressive_Total_PNL",
    "Aggressive_Max_DD",
    "Aggressive_Avg_Positions",
    "Aggressive_Days_AtOrBelow_Avg",
    "Aggressive_Days_In_Margin",
    "Aggressive_Days_Trimmed_Over_2xAvg",
]

# Result metrics written after Param_Name / Param_Value (see brt_audit_columns.py).
_METRIC_AUDIT_COLS = [
    "Total_PNL",
    "Wins",
    "Losses",
    "BE",
    "Pct_Wins",
    "Pct_Losses",
    "Win_Loss_Ratio",
    "Win_Loss_Ratio_Dollar",
    "Total_Trades",
    "Profit_Factor",
    "Avg_Win_Pct",
    "Avg_Loss_Pct",
    "Avg_PNL_Pct",
    "Expectancy",
    "Expectancy_Pct",
    "Avg_Days_Held",
    "Median_Days_Held",
    "P90_Days",
    "Avg_Days_Underwater",
    "P90_Days_Underwater",
    "Capital_Days",
    "Profit_Per_Capital_Day",
    "Ann_ROR",
    "Max_DD",
    "Losing_Streak",
    "DD_Per_Trade",
    "CES_AVG",
    "CES_Median",
    "Pct_PNL_Top10",
    "Pct_PNL_Bottom10",
    "Max_Positions",
    "Score",
    "Pct_PNL_Max_Symbol",
    "Pct_PNL_Max_Trade",
    "Pct_PNL_Max_Industry",
    *_AGGRESSIVE_METRIC_COLS,
    "Trades_With_Meteoric_Rise_History",
    "Pct_Trades_With_Meteoric_Rise_History",
    "Trades_With_Meteoric_Fall_History",
    "Pct_Trades_With_Meteoric_Fall_History",
    "Trades_Post_Entry_Gain_Hit",
    "Pct_Trades_Post_Entry_Gain_Hit",
]

# Human-readable glossary for newer audit/report columns.
# Kept near audit column lists so future additions stay documented.
_AUDIT_FIELD_GLOSSARY: dict[str, str] = {
    # Entry-state / gating knobs
    "pending_max_bars": "Max bars a pending maturity can wait before expiry (stale pending TTL).",
    "entry_eval_mode": "Entry engine mode: 'pending' (legacy pending queue) or 'row_local' (sheet-style row-local evaluation).",
    "transaction_type": "Strategy side mode: long | short | both.",
    "entry_type": "Active side for a single stream: long | short.",
    "zone_role_mode": "Zone role policy: dynamic (no filter) or by_origin (PH→resistance for longs, PL→support for shorts; filters DI + touch pending).",
    "zone_role_override": "Optional: support | resistance | both — forces all zones to that role (both = no extra filter).",
    "row_local_eval_touch_same_bar": "In row_local mode, allow same-bar evaluation on maturity/touch bar when True.",
    "row_local_eval_ttl_bars_after_first_eval": "Row-local: extra bars a touch maturity stays pending after its first eval day (0 = one day only).",
    "row_local_require_active_context_match": "In row_local mode, require pending maturity to match active DN context.",
    "level_acceptance_required": "Legacy only: min closes above anchor in last N bars (0=off, matches sheet AL without 7/10).",
    "level_acceptance_anchor_mode": "Legacy level_acceptance: support-test anchor strict vs rolling.",
    "level_acceptance_anchor_window": "Legacy level_acceptance: rolling anchor lookback (bars).",
    "zone_include_pre_strong_pivot_lows": "Strong PL touch/zone uses min(Low) over strong_pre_pivot_bars through pivot bar when True.",
    "zones_from_pivot_lows_enabled": "When False, pivot lows do not create touch/zone rows (PH-only BH/BI ladder).",
    "brt_zones": "When True, create zones from pivot-high/low BRT ladder. Default False (YH-only mode).",
    "yh_zones": "When True (default), add Year-High (52w) retest zones: new 52w high → move-away → activation → same breakout/retest pipeline.",
    "vec_zones": "When True, add Volume + prior-period Extreme Confluence zones (POC vs prior-week high). VEC-only: vec_zones=true, brt_zones=false, yh_zones=false.",
    "vec_vp_lookback": "VEC: trading-day window for volume-profile POC (default 60).",
    "vec_vp_bin_pct": "VEC: histogram bin width as fraction of median price (default 0.005 = 0.5%).",
    "vec_prior_bars": "VEC: prior-period length in sessions (default 5 ≈ prior week on daily bars).",
    "vec_prior_side": "VEC: prior extreme to compare to POC — high (resistance) or low (support).",
    "vec_confluence_pct": "VEC: max |POC - extreme| / extreme for confluence (default 0.0075 = 0.75%).",
    "vec_move_away_pct": "VEC: min rally above zone center before activation (default 0.02; 0 = activate on confluence bar).",
    "vec_min_bars_between": "VEC: min bars between activations at a similar center (dedup, default 20).",
    "pbr_zones": "When True, add Pivot Break and Retest zones (weekly pivot bands, two-stage weekly breakout, daily retest, next-open entry). PBR-only: pbr_zones=true, brt_zones=false, yh_zones=false, vec_zones=false.",
    "pbr_breakout_confirmation": "PBR stage-2 breakout: first weekly high > zone_upper * (1 + this) sets confirmation week (default 0.03 = 3%).",
    "pbr_max_days_after_retest": "PBR entry window: max trading days after retest bar (inclusive) to allow Rocket Buy signal (default 2).",
    "pbr_second_chance_after_win": "PBR zone lifecycle: when True, a profitable first purchase from a zone allows exactly one more purchase then retire; when False (default), retire the zone after the first purchase win or loss.",
    "rl_mode": "true | false — Rocket Launcher 50-SMA dip buy (separate run from BRT zone/retest). true = RL_ prefix; AWK/portfolio_audit.awk math is authoritative; Python port in progress.",
    "rl_cash": "Rocket Launcher fixed notional per trade (AWK RL_CASH, default 47500).",
    "rl_flush_days": "Portfolio flush: sell all open RL positions after N consecutive underwater days (0=off, AWK RL_FLUSH_DAYS).",
    "rl_watch_min_score": "Minimum setup score for RL_Watchlist rows (AWK WATCH_MIN_SCORE, default 55).",
    "rl_watch_disable": "If true, skip RL_Watchlist rows (header-only CSV).",
    "yh_lookback": "Trading-day lookback for rolling 52-week high detection (default 252).",
    "yh_move_away_pct": "Min rally above YH before zone activates (default 0.03 = 3%).",
    "yh_memory_mode": "YH candidate memory: sheet (default, live spreadsheet handoff), fifo (queued promote), or parallel (test).",
    "yh_serial_memory": "Legacy: maps to fifo (true) or parallel (false) when yh_memory_mode is not set in -v.",
    # Sheet parity (compact BH/BI / DI / retest)
    "sheet_di_breakout_price": "BM/DI breakout price series for BY/DW simulation only (Close vs BI or High vs BI); not a buy gate.",
    "sheet_dw_countif_entry_enabled": "Eval bar date must be a **first retest overlap** day (BY / Retest Date column), not the DI breakout day unless retest falls same session.",
    "growth_history_slack_bars": "Allow growth filter when eval_bar >= growth_bars - slack (default 2 for sheet 2016-01-01 anchor vs CSV start).",
    "sheet_dw_countif_include_prior_bar_date": "When True, adds the next trading session after each retest to the COUNTIF set. Default False (strict COUNTIF(BO,D) parity).",
    "sheet_no_entry_same_bar_after_exit": "When True, suppress new entry evaluation on the same bar a position is closed (sheet IN TRADE semantics).",
    "retest_multi_zone_pick": "When multiple BY retest rows share the same retest day: all | lowest (min zone_lower) | highest (max zone_upper) for which band feeds entry pending.",
    "entry_retest_bullish_growth_only": "When True, skip TKL and consolidation blocker on long entry.",
    "sheet_di_max_history_bars": "Cap bars of BH/BI history scanned for DI (0 = full history).",
    "compute_beta": "When True with benchmark, fills BETA_AT_ENTRY on trades (rolling beta vs SPY; not yfinance).",
    "min_beta_at_trigger": "Require rolling calculated beta vs SPY at trigger bar >= this (0 = off). Uses same calculated beta as BETA_AT_ENTRY, not yfinance.",
    "max_beta_at_trigger": "Require rolling calculated beta vs SPY at trigger bar <= this (0 = off). Uses same calculated beta as BETA_AT_ENTRY, not yfinance.",
    "min_upper_wick_atr_at_trigger": "Require UPPER_WICK_ATR_AT_TRIGGER ((High-max(Open,Close))/ATR14 at trigger) >= this (0 = off).",
    "use_indicators": "When True, append IND_* / IND_ENTRY_* columns at entry (see brt_entry_indicators).",
    "use_ind_score": "When True, append IND_SCORE = sum of per-indicator weights for each IND_<id> that is BULL at entry (see ind_score_weights.json).",
    "ind_score_weights_path": "IND_SCORE weights JSON (explicit -v path as given; empty default → canonical ind_score_weights_<stamp>.json, reused until weights change).",
    "min_ind_score": "Require IND_SCORE >= this at trigger bar close (default 0 = filter off).",
    "mandatory_ind_states_path": "Mandatory IND state rules JSON filename (e.g. mandatory_ind_states.json). Empty = gate off. Resolves from cwd, stock_analysis/, or repo root.",
    "use_sma50": "When true and atr_target=0: long target = SMA(50)*target_pct at entry; short uses SMA(50)*short_target_pct formula.",
    "indicator_buy": "off | only | both — only = IND-only entry (trade-aligned IND_DIFF >= indicator_diff at trigger close, no zone/retest/RS); both = zone/retest + diff gate + sheet gates; growth_filter still applies when enabled.",
    "indicator_diff": "Minimum trade-aligned (bull−bear) IND count at trigger bar close when indicator_buy is only or both (default 10). Negative values allowed (e.g. -100). LONG: bullish-aligned; SHORT: bearish-aligned.",
    "min_rel_vol_at_entry": "Require REL_VOL_AT_ENTRY (entry-day volume / 10d avg) >= this at entry (-2 = off). Knowable only after entry day closes; not a pre-entry scanner filter.",
    "sell_on_low_vol": "Exit at next session open when REL_VOL_AT_ENTRY < this (0 = off). Uses entry-day volume stored at open; e.g. 0.8592 sells if rel vol was below 0.8592 on the fill day.",
    "sell_ind_diff_below": "Exit at next session open when trade-aligned IND_DIFF on the prior held session is below N (None = off).",
    "exit_ind_diff_only": "When True (requires sell_ind_diff_below), IND_DIFF exit is the only exit; stop/target/trailing/ATR schedule exits are disabled.",
    "max_touch_count_short": "Require TOUCH_COUNT_SHORT <= N at maturity bar (None = off; 0 = no short-window touches).",
    "entry_filter_meteoric_rise": "Tri-state: true=require HAD_METEORIC_RISE_BEFORE_ENTRY==1; false=require ==0; both=no filter.",
    "entry_filter_meteoric_fall": "Tri-state: true=require HAD_METEORIC_FALL_BEFORE_ENTRY==1; false=require ==0; both=no filter.",
    "max_ind_entry_neutral_n": "Require IND_ENTRY_NEUTRAL_N <= N at trigger bar close (None = off; needs OHLCV precompute).",
    "min_ind_entry_bull_n": "Require IND_ENTRY_BULL_N >= N at trigger bar close (None = off; trade-aligned; needs OHLCV precompute).",
    "indicator_sides": "long | short | both — which streams run the indicator gate (only/both modes). Default auto: only→both, both→long. both sets transaction_type=both for long+short indicator entries.",
    "trace_indicator_buy": "When True, print [IND-GATE] lines for indicator_buy only/both (CLI: --trace-indicator-buy).",
    "indicator_cache": "When True, cache per-symbol indicator precompute on disk (reuse across runs; incremental on new bars).",
    "indicator_cache_dir": "Indicator cache folder (default <data-dir>/.brt_indicator_cache; CLI: --indicator-cache-dir).",
    "relative_strength_enabled": "When True, use SPY-relative 252/504/756-bar return gate only (no zone/retest entry stack).",
    "do_gate_enabled": "Enable DO parity gate (recent pre-only strong pivot touch must exist).",
    "do_good_for_bars": "DO gate recency window in bars ('good for' bars).",
    "dp_gate_enabled": "Enable DP parity gate (current low inside any recent matured BH/BI band).",
    "dp_window_bars": "DP lookback window in bars (0 means use lookback_long).",
    "dp_good_for_bars": "DP event recency window in bars ('good for' bars).",
    "too_high_multiplier": "Final entry gate: block entry when next open > trigger-bar low * too_high_multiplier (0 disables).",
    "too_low_multiplier": "Final entry floor: block entry when next open < prior-day close * too_low_multiplier (0 disables).",
    "entry_close_min_range_position": (
        "Long: require close in upper portion of signal bar (close_pos = (C-L)/(H-L) >= this; 0 disables). "
        "Block reason: bullish_close_below_range_mid."
    ),
    "require_close_gt_open": "When True, long entries require Close>Open on the signal bar; short requires Close<Open.",
    "sheet_red_to_green_entry_enabled": "Sheet AH buy: prior bar Close<=Open and eval bar Close>Open (red-to-green flip).",
    "atr_progress_incremental_stop": "When True, after atr_days calendar days, raise active stop floor to entry*(1+atr_progress*ATR%%/100); stop exits from this raised floor use exit type atr_incremental_stop.",
    "sheet_magic_touch_enabled": "Enable AR/AW sheet magic-touch event generation for maturity/touch events.",
    "sheet_magic_touch_window_bars": "AR/AW rolling window length in bars (0 means use lookback_long).",
    # Equity/DD model controls
    "initial_capital": "Portfolio baseline equity for DD/equity path (independent of brt_cash per-position sizing).",
    "aggressive": "Enable aggressive equity overlay: size each entry as equity×max_multiple/avg_positions; margin interest on borrowed notional.",
    "aggressive_margin_interest": "Annualized interest rate on borrowed margin (max(0, -cash)) in aggressive mode.",
    "aggressive_max_multiple": "Target gross leverage vs equity when sizing new entries (default 2 = 2× equity / avg_positions per slot).",
    "aggressive_avg_positions": "Override average positions for aggressive sizing (0 = auto from run history; see aggressive_avg_positions_actual for value used).",
    "aggressive_avg_positions_actual": "Average active positions used in this run's aggressive equity simulation (auto mean when override is 0).",
    "aggressive_sizing_equity_cap": "Cap equity used for aggressive entry sizing at initial_capital×this multiple (default 10); does not cap reported equity.",
    "aggressive_sell": "When aggressive: false=current behavior; average=equal %% trim of all holdings at new entry; losers=trim worst unrealized PnL first; winners=trim best first.",
    "margin_utilization": "Fraction of total margin buying power to deploy (initial_capital×aggressive_max_multiple×this). Default 0.6; --aggressive forces 1.0.",
    "max_positions": "Per-slot notional divisor: deployable_margin / max_positions. 0 = auto from peak concurrent closed trades.",
    "symbol_reentry_cooldown_days": "Calendar days after closing a symbol before a new entry in that same symbol is allowed (0=off). Example: 5 blocks same-week re-entry; 20 ~ one month.",
    "allow_secondary_entries": "When true, allow a new entry in a symbol while another position in that same symbol is still open (default false).",
    "trailing_stop_increment": "Trailing stop: 0=off. Else working stop = initial stop + (gain%%/N)*1%% of entry (gain from peak high since entry; fractional N, not floored).",
    "sma_stop_days": "SMA trailing stop: 0=off. When >0 and Close is above SMA(N) (long) or below SMA(N) (short), working stop = max/min of other stops and SMA(N); never loosens (e.g. 20 or 8).",
    "atr_progress": "ATR schedule: <=0 with atr_days>0 = timed exit only (ATR_timed) at first open after entry_date+atr_days calendar days. >0 = inaction rule (ATR_inaction) unless High clears entry*(1+atr_progress*ATR%%/100) before that scheduled open.",
    "atr_days": "ATR schedule: calendar days from entry date. Exit check occurs at the first trading-bar open strictly after entry_date+atr_days.",
    # Concentration metrics
    "Pct_PNL_Max_Symbol": "Largest single-symbol contribution as % of total PnL.",
    "Pct_PNL_Max_Trade": "Largest single-trade contribution as % of total PnL.",
    "Pct_PNL_Max_Industry": "Largest single-industry contribution as % of total PnL.",
    "meteoric_rise_pct": "Meteoric rise: a day counts if Close >= (1+pct/100)×min(Low) over prior meteoric_rise_lookback bars.",
    "meteoric_rise_lookback": "Trading-bar window N for meteoric rise min-low (default 100).",
    "meteoric_fall_pct": "Meteoric fall: a day counts if Close <= (1-pct/100)×max(High) over prior meteoric_fall_lookback bars.",
    "meteoric_fall_lookback": "Trading-bar window Y for meteoric fall max-high (default 100).",
    "Trades_With_Meteoric_Rise_History": "Closed trades where the symbol had ≥1 meteoric-rise day on or before entry (see BRT_Closed HAD_METEORIC_RISE_BEFORE_ENTRY).",
    "Pct_Trades_With_Meteoric_Rise_History": "Percent of closed trades with prior meteoric rise history.",
    "Trades_With_Meteoric_Fall_History": "Closed trades where the symbol had ≥1 meteoric-fall day on or before entry (see BRT_Closed HAD_METEORIC_FALL_BEFORE_ENTRY).",
    "Pct_Trades_With_Meteoric_Fall_History": "Percent of closed trades with prior meteoric fall history.",
    "post_entry_gain_pct": "Post-entry study: LONG if max High>=entry×(1+this/100); SHORT if min Low<=entry×(1-this/100), within min(post_entry_gain_calendar_days, days until exit) (POST_ENTRY_GAIN_HIT).",
    "post_entry_gain_calendar_days": "Post-entry study: max calendar days from entry (inclusive) to scan; window is also capped at exit date for closed trades. 0 disables hit computation.",
    "Trades_Post_Entry_Gain_Hit": "Closed trades where High reached the threshold on some day no later than exit and within the post-entry gain window (still in trade when the bar occurs).",
    "Pct_Trades_Post_Entry_Gain_Hit": "Percent of closed trades with POST_ENTRY_GAIN_HIT=1 (same window/threshold as config; exit-capped).",
    # Aggressive run diagnostics
    "Aggressive_Avg_Positions": "Average active positions used by aggressive sizing logic.",
    "Aggressive_Max_DD": "Max drawdown on the aggressive equity curve (initial_capital basis); Max_DD stays on passive/regular equity.",
    "Aggressive_Total_PNL": "Aggressive total PnL on initial_capital basis (includes margin + trims + interest).",
    "Aggressive_Days_AtOrBelow_Avg": "Days where desired gross stayed at or below initial_capital (no margin).",
    "Aggressive_Days_In_Margin": "Days where borrowed notional > 0 (cash negative / on margin).",
    "Aggressive_Days_Trimmed_Over_2xAvg": "Days where aggressive_sell trimmed existing holdings to fund a new entry.",
}


def _get_audit_cols_order() -> list[str]:
    """Stable BRT_Report / BRT_Audit header order (``brt_audit_columns``; new fields append at end)."""
    try:
        from brt_audit_columns import get_brt_audit_column_order

        order: list[str] = list(get_brt_audit_column_order())
    except ImportError:
        order = ["Timestamp_Drive"] + list(_AUDIT_CFG_COLS) + ["Param_Name", "Param_Value"] + list(
            _METRIC_AUDIT_COLS
        )
    seen = set(order)
    # Same trailing-append behavior as legacy BRT reports: new cfg/metric keys after the baseline.
    for col in _AUDIT_CFG_COLS:
        if col not in seen:
            order.append(col)
            seen.add(col)
    for col in _METRIC_AUDIT_COLS:
        if col not in seen:
            order.append(col)
            seen.add(col)
    return order


def _resolve_aggressive_avg_positions_actual(metrics: dict, cfg: BRTConfig) -> float | str:
    """Avg positions used in aggressive sizing for this run (from equity sim, or override when set)."""
    if not getattr(cfg, "aggressive", False):
        return ""
    raw = metrics.get("Aggressive_Avg_Positions")
    if raw is not None and raw != "":
        try:
            v = float(raw)
            if v > 0:
                return round(v, 4)
        except (TypeError, ValueError):
            pass
    override = float(getattr(cfg, "aggressive_avg_positions", 0) or 0)
    if override > 0:
        return round(override, 4)
    return ""


def _apply_aggressive_avg_positions_actual_to_audit_row(row: dict, metrics: dict, cfg: BRTConfig) -> None:
    row["aggressive_avg_positions_actual"] = _resolve_aggressive_avg_positions_actual(metrics, cfg)


def _metrics_to_audit_row(metrics: dict) -> dict:
    """Convert BRT metrics dict to audit row format (same as optimizer _metrics_to_row)."""
    def num(x):
        if x is None or x == "N/A":
            return 0.0
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).replace("%", "").strip()
        try:
            return float(s)
        except ValueError:
            return 0.0

    wins = int(metrics.get("Wins", 0))
    losses = int(metrics.get("Losses", 0))
    bes = int(metrics.get("BEs", 0))
    total_trades = wins + losses + bes
    pct_wins = (wins / total_trades * 100) if total_trades else 0.0
    pct_losses = (losses / total_trades * 100) if total_trades else 0.0
    max_dd_raw = metrics.get("Max_Drawdown", "N/A")
    max_dd = max_dd_raw if (max_dd_raw is None or max_dd_raw == "N/A" or str(max_dd_raw).strip() == "N/A") else num(max_dd_raw)
    dd_raw = metrics.get("DD_Per_Trade", "N/A")
    dd_per_trade = dd_raw if (dd_raw is None or dd_raw == "N/A" or str(dd_raw).strip() == "N/A") else num(dd_raw)

    return {
        "Total_PNL": num(metrics.get("Total_PNL", 0)),
        "Wins": wins, "Losses": losses, "BE": bes,
        "Pct_Wins": pct_wins, "Pct_Losses": pct_losses,
        "Win_Loss_Ratio": (wins / losses) if losses else (float(wins) if wins else 0.0),
        "Win_Loss_Ratio_Dollar": num(metrics.get("Win_Loss_Ratio_Dollar", 0)),
        "Total_Trades": total_trades,
        "Profit_Factor": num(metrics.get("Profit_Factor", 0)),
        "Avg_Win_Pct": num(metrics.get("Avg_Win_Pct", 0)),
        "Avg_Loss_Pct": num(metrics.get("Avg_Loss_Pct", 0)),
        "Avg_PNL_Pct": num(metrics.get("Avg_PNL_Pct", 0)),
        "Expectancy": num(metrics.get("Expectancy", 0)),
        "Expectancy_Pct": num(metrics.get("Avg_PNL_Pct", 0)),
        "Avg_Days_Held": num(metrics.get("Avg_Days_Held", 0)),
        "Median_Days_Held": num(metrics.get("Median_Days_Held", 0)),
        "P90_Days": num(metrics.get("P90_Days", 0)),
        "Avg_Days_Underwater": num(metrics.get("Avg_Days_Underwater", 0)),
        "P90_Days_Underwater": num(metrics.get("P90_Days_Underwater", 0)),
        "Capital_Days": int(metrics.get("Capital_Days", 0)),
        "Profit_Per_Capital_Day": num(metrics.get("Profit_Per_Capital_Day", 0)),
        "Ann_ROR": num(metrics.get("Annualized_ROR", 0)),
        "Max_DD": max_dd, "Losing_Streak": int(metrics.get("Losing_Streak", 0)),
        "DD_Per_Trade": dd_per_trade,
        "CES_AVG": num(metrics.get("CES_AVG", 0)),
        "CES_Median": num(metrics.get("CES_Median", 0)),
        "Pct_PNL_Top10": num(metrics.get("Pct_PNL_Top10", 0)),
        "Pct_PNL_Bottom10": num(metrics.get("Pct_PNL_Bottom10", 0)),
        "Max_Positions": int(metrics.get("Max_Positions", 1)),
        "Pct_PNL_Max_Symbol": num(metrics.get("Pct_PNL_Max_Symbol", 0)),
        "Pct_PNL_Max_Trade": num(metrics.get("Pct_PNL_Max_Trade", 0)),
        "Pct_PNL_Max_Industry": num(metrics.get("Pct_PNL_Max_Industry", 0)),
        "Aggressive_Total_PNL": num(metrics.get("Aggressive_Total_PNL", 0)),
        "Aggressive_Max_DD": (
            metrics.get("Aggressive_Max_Drawdown", "N/A")
            if metrics.get("Aggressive_Max_Drawdown") in (None, "N/A")
            or str(metrics.get("Aggressive_Max_Drawdown", "")).strip() == "N/A"
            else num(metrics.get("Aggressive_Max_Drawdown", 0))
        ),
        "Aggressive_Avg_Positions": num(metrics.get("Aggressive_Avg_Positions", 0)),
        "Aggressive_Days_AtOrBelow_Avg": int(metrics.get("Aggressive_Days_AtOrBelow_Avg", 0) or 0),
        "Aggressive_Days_In_Margin": int(metrics.get("Aggressive_Days_In_Margin", 0) or 0),
        "Aggressive_Days_Trimmed_Over_2xAvg": int(metrics.get("Aggressive_Days_Trimmed_Over_2xAvg", 0) or 0),
        "Trades_With_Meteoric_Rise_History": int(metrics.get("Trades_With_Meteoric_Rise_History", 0) or 0),
        "Pct_Trades_With_Meteoric_Rise_History": num(metrics.get("Pct_Trades_With_Meteoric_Rise_History", 0)),
        "Trades_With_Meteoric_Fall_History": int(metrics.get("Trades_With_Meteoric_Fall_History", 0) or 0),
        "Pct_Trades_With_Meteoric_Fall_History": num(metrics.get("Pct_Trades_With_Meteoric_Fall_History", 0)),
        "Trades_Post_Entry_Gain_Hit": int(metrics.get("Trades_Post_Entry_Gain_Hit", 0) or 0),
        "Pct_Trades_Post_Entry_Gain_Hit": num(metrics.get("Pct_Trades_Post_Entry_Gain_Hit", 0)),
    }


def write_brt_audit_report(
    cfg: BRTConfig,
    metrics: dict,
    output_dir: str,
    ts: str,
    drive_link: str = "",
    file_prefix: Optional[str] = None,
    audit_report_suffix: str = "",
) -> None:
    """Write audit-format CSV (same structure as BRT_Optimization_Audit) for standalone runs.
    Uses same post-run capital scaling as BRT_Report (brt_cash = 1M/max_positions, Total_PNL scaled)."""
    link = drive_link or f"https://drive.google.com/drive/search?q={ts}"
    drive_link_cell = f'=hyperlink("{link}","{ts}")'
    cfg_dict = asdict(cfg)
    row = {"Timestamp_Drive": drive_link_cell, "Param_Name": "", "Param_Value": "", "Score": ""}
    for k in _AUDIT_CFG_COLS:
        row[k] = cfg_dict.get(k, "")
    row.update(_metrics_to_audit_row(metrics))
    _apply_aggressive_avg_positions_actual_to_audit_row(row, metrics, cfg)
    max_pos = int(row.get("Max_Positions", 1) or 1)
    if max_pos > 0:
        adjusted_brt_cash = 1_000_000.0 / max_pos
        orig_cash = float(cfg.brt_cash) if getattr(cfg, "brt_cash", None) and cfg.brt_cash > 0 else adjusted_brt_cash
        scale_for_total_pnl = (adjusted_brt_cash / orig_cash) if orig_cash > 0 else 1.0
        total_pnl_val = row.get("Total_PNL", 0)
        if isinstance(total_pnl_val, str):
            total_pnl_val = float(total_pnl_val.replace(",", "").replace("%", "").strip() or 0)
        row["Total_PNL"] = total_pnl_val * scale_for_total_pnl
        row["brt_cash"] = adjusted_brt_cash
        cap_days = row.get("Capital_Days") or 0
        try:
            cap_days = int(cap_days) if isinstance(cap_days, (int, float)) else int(float(str(cap_days).strip() or 0))
        except (TypeError, ValueError):
            cap_days = 0
        if cap_days > 0:
            row["Profit_Per_Capital_Day"] = row["Total_PNL"] / cap_days
    headers = _get_audit_cols_order()
    values = [row.get(c, "") for c in headers]
    prefix = file_prefix or _output_file_prefix(cfg)
    path = os.path.join(output_dir, f"{prefix}_Audit_Report{audit_report_suffix}_{ts}.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerow(values)


# ============== METRICS ==============
def _parse_trade_date(s: str) -> pd.Timestamp | None:
    """Parse DATE_OPENED/DATE_CLOSED (YYYYMMDD or YYYY-MM-DD) to Timestamp."""
    if not s or len(s) < 8:
        return None
    try:
        if "-" in s:
            return pd.Timestamp(s[:10])
        return pd.Timestamp(s[:4] + "-" + s[4:6] + "-" + s[6:8])
    except Exception:
        return None


def _first_calendar_up_pct_date_days(
    df: pd.DataFrame,
    entry_ts: pd.Timestamp,
    entry_price: float,
    up_pct: float,
) -> tuple[str, int]:
    """First bar on/after entry where High >= entry*(1+up_pct/100). Returns (YYYYMMDD, calendar days from entry)."""
    if entry_price <= 0 or up_pct <= 0:
        return "", 0
    thr = entry_price * (1.0 + up_pct / 100.0)
    idx = pd.DatetimeIndex(pd.to_datetime(df.index, errors="coerce"))
    try:
        if idx.tz is not None:
            idx = idx.tz_convert("UTC").tz_localize(None)
    except Exception:
        pass
    idx_n = idx.normalize()
    entry_n = pd.Timestamp(entry_ts).normalize()
    m = idx_n >= entry_n
    if not bool(np.any(m)):
        return "", 0
    try:
        sub = df.loc[m]
        for i in range(len(sub)):
            ts_i = sub.index[i]
            h_i = float(sub.iloc[i]["High"])
            if h_i >= thr - 1e-12:
                ds = pd.Timestamp(ts_i).normalize()
                date_str = f"{ds.year:04d}{ds.month:02d}{ds.day:02d}"
                return date_str, int((ds - entry_n).days)
        return "", 0
    except Exception:
        return "", 0


def _entry_bar_for_trade(t: BRTTrade, df: pd.DataFrame, n: int) -> int:
    eb = int(getattr(t, "entry_bar_index", -1) or -1)
    if 0 <= eb < n:
        return eb
    entry_ts = _parse_trade_date(t.date_opened)
    if entry_ts is None or pd.isna(entry_ts):
        return -1
    pos = int(df.index.searchsorted(entry_ts, side="left"))
    return min(max(pos, 0), n - 1)


def _first_up_pct_from_bar(
    high: np.ndarray,
    idx_norm: pd.DatetimeIndex,
    entry_bar: int,
    entry_n: pd.Timestamp,
    entry_price: float,
    up_pct: float,
) -> tuple[str, int]:
    if entry_price <= 0 or up_pct <= 0 or entry_bar < 0 or entry_bar >= len(high):
        return "", 0
    thr = entry_price * (1.0 + up_pct / 100.0)
    sub = high[entry_bar:]
    hits = np.flatnonzero(sub >= thr - 1e-12)
    if hits.size == 0:
        return "", 0
    bi = entry_bar + int(hits[0])
    ds = pd.Timestamp(idx_norm[bi]).normalize()
    return f"{ds.year:04d}{ds.month:02d}{ds.day:02d}", int((ds - entry_n).days)


def _trade_is_long_side(t: BRTTrade) -> bool:
    return str(getattr(t, "side", "LONG") or "LONG").strip().upper() != "SHORT"


def _enrich_symbol_post_entry_gain(
    sym: str,
    tlist: list[BRTTrade],
    df: Optional[pd.DataFrame],
    gain_pct: float,
    cal_days: int,
) -> str:
    if df is None or df.empty or "High" not in df.columns or "Low" not in df.columns:
        return sym
    high = np.asarray(df["High"], dtype=np.float64)
    low = np.asarray(df["Low"], dtype=np.float64)
    n = len(high)
    idx = pd.DatetimeIndex(pd.to_datetime(df.index, errors="coerce"))
    try:
        if idx.tz is not None:
            idx = idx.tz_convert("UTC").tz_localize(None)
    except Exception:
        pass
    idx_norm = idx.normalize()
    for t in tlist:
        ep = float(getattr(t, "entry_price", 0) or 0)
        if ep <= 0:
            continue
        eb = _entry_bar_for_trade(t, df, n)
        if eb < 0:
            continue
        entry_n = pd.Timestamp(idx_norm[eb]).normalize()
        d10, n10 = _first_up_pct_from_bar(high, idx_norm, eb, entry_n, ep, 10.0)
        t.date_first_up_10pct = d10
        t.days_held_first_up_10pct = n10
        d20, n20 = _first_up_pct_from_bar(high, idx_norm, eb, entry_n, ep, 20.0)
        t.date_first_up_20pct = d20
        t.days_held_first_up_20pct = n20
        if gain_pct <= 0 or cal_days <= 0:
            continue
        end_cfg_n = entry_n + timedelta(days=cal_days)
        exit_n: Optional[pd.Timestamp] = None
        dc = str(getattr(t, "date_closed", "") or "").strip()
        if dc:
            exit_ts = _parse_trade_date(dc)
            if exit_ts is not None and not pd.isna(exit_ts):
                exit_n = pd.Timestamp(exit_ts).normalize()
        window_end_n = end_cfg_n if exit_n is None else min(end_cfg_n, exit_n)
        if window_end_n < entry_n:
            continue
        end_pos = int(idx_norm.searchsorted(window_end_n, side="right")) - 1
        end_pos = min(max(end_pos, eb), n - 1)
        win_hi = high[eb : end_pos + 1]
        win_lo = low[eb : end_pos + 1]
        if _trade_is_long_side(t):
            thr = ep * (1.0 + gain_pct / 100.0)
            t.post_entry_gain_hit = 1 if float(np.max(win_hi)) >= thr - 1e-12 else 0
        else:
            thr = ep * (1.0 - gain_pct / 100.0)
            t.post_entry_gain_hit = 1 if float(np.min(win_lo)) <= thr + 1e-12 else 0
    return sym


def _enrich_post_entry_gain_hit(
    trades: list[BRTTrade],
    tickers: dict[str, pd.DataFrame],
    cfg: BRTConfig,
    pipeline: Optional[Any] = None,
    workers: int = 0,
) -> None:
    """Set post-entry path fields: window hit (config), first +10%/+20% dates and calendar days held."""
    pct = float(getattr(cfg, "post_entry_gain_pct", 0.0) or 0.0)
    cal_days = int(getattr(cfg, "post_entry_gain_calendar_days", 0) or 0)
    for t in trades:
        t.post_entry_gain_hit = 0
        t.date_first_up_10pct = ""
        t.days_held_first_up_10pct = 0
        t.date_first_up_20pct = ""
        t.days_held_first_up_20pct = 0
    if not tickers or not trades:
        return
    gain_pct = float(pct) if cal_days > 0 and pct > 0 else 0.0
    by_sym: dict[str, list[BRTTrade]] = {}
    for t in trades:
        by_sym.setdefault((t.symbol or "").strip().upper(), []).append(t)
    sym_list = sorted(by_sym.keys())
    n_syms = len(sym_list)
    n_workers = max(0, int(workers or 0))
    if n_workers > 1 and n_syms > 1:
        n_workers = min(n_workers, n_syms, 16)
        done = 0
        with ThreadPoolExecutor(max_workers=n_workers) as ex:
            futs = {
                ex.submit(_enrich_symbol_post_entry_gain, sym, by_sym[sym], tickers.get(sym), gain_pct, cal_days): sym
                for sym in sym_list
            }
            for fut in as_completed(futs):
                sym = fut.result()
                done += 1
                if pipeline is not None and getattr(pipeline, "enabled", False):
                    pipeline.post_tick("post_entry_gain_hit", done, n_syms)
        if pipeline is not None and getattr(pipeline, "enabled", False):
            pipeline.complete_phase_units("post_entry_gain_hit")
        return
    for sym_i, sym in enumerate(sym_list, start=1):
        if pipeline is not None and getattr(pipeline, "enabled", False) and n_syms > 1:
            pipeline.post_tick("post_entry_gain_hit", sym_i, n_syms)
        _enrich_symbol_post_entry_gain(sym, by_sym[sym], tickers.get(sym), gain_pct, cal_days)
    if pipeline is not None and getattr(pipeline, "enabled", False):
        pipeline.complete_phase_units("post_entry_gain_hit")


def _effective_margin_utilization(cfg: "BRTConfig") -> float:
    """1.0 when --aggressive; else margin_utilization (default 0.6)."""
    if bool(getattr(cfg, "aggressive", False)):
        return 1.0
    util = float(getattr(cfg, "margin_utilization", 0.6) or 0.6)
    return max(0.0, min(util, 1.0))


def _margin_deployable_capital(cfg: "BRTConfig") -> float:
    """Total notional budget: initial_capital × leverage × margin_utilization."""
    init = float(cfg.initial_capital) if getattr(cfg, "initial_capital", None) and cfg.initial_capital > 0 else 1_000_000.0
    mult = float(getattr(cfg, "aggressive_max_multiple", 2.0) or 2.0)
    return init * mult * _effective_margin_utilization(cfg)


def _report_adjusted_brt_cash(max_positions: int, cfg: "BRTConfig") -> float:
    """Per-slot notional = deployable margin budget / max(Max_Positions, 1)."""
    mp = max(int(max_positions or 0), 1)
    return _margin_deployable_capital(cfg) / mp


def _max_concurrent_positions(closed: list[BRTTrade]) -> int:
    """Compute max number of overlapping positions from closed trades."""
    if not closed:
        return 0
    events: list[tuple[pd.Timestamp, int]] = []
    for t in closed:
        dopen = _parse_trade_date(t.date_opened)
        dclose = _parse_trade_date(t.date_closed)
        if dopen is None or dclose is None:
            continue
        events.append((dopen, 1))
        events.append((dclose, -1))
    events.sort(key=lambda x: (x[0], -x[1]))  # closes before opens on same day
    cur, mx = 0, 0
    for _, delta in events:
        cur += delta
        mx = max(mx, cur)
    return mx


def _resolve_max_positions(closed: list[BRTTrade], cfg: BRTConfig) -> int:
    """Slot budget for brt_cash scaling: cfg.max_positions when >0, else peak concurrent (min 1)."""
    override = int(getattr(cfg, "max_positions", 0) or 0)
    if override > 0:
        return override
    return max(_max_concurrent_positions(closed), 1)


def _apply_report_dollar_scale_to_trades(
    closed: list[BRTTrade],
    open_trades: list[BRTTrade],
    cfg: BRTConfig,
) -> tuple[float, float]:
    """
    Align in-memory dollar fields with BRT_Report / BRT_Audit: ``brt_cash = deployable_margin / max_positions``
    where deployable = initial_capital × aggressive_max_multiple × margin_utilization (1.0 when --aggressive),
    and scale every trade's ``pnl_dollars`` by the same ratio so CSV outputs match the report.

    Returns (adjusted_brt_cash, scale_factor_applied_to_pnl) where scale is 1.0 if no pnl change.
    """
    max_pos = _resolve_max_positions(closed, cfg)
    adjusted = _report_adjusted_brt_cash(max_pos, cfg)
    orig = float(cfg.brt_cash) if getattr(cfg, "brt_cash", None) and cfg.brt_cash > 0 else adjusted
    scale = adjusted / orig if orig > 0 else 1.0
    if abs(scale - 1.0) >= 1e-12:
        for t in closed:
            t.pnl_dollars = float(t.pnl_dollars) * scale
        for t in open_trades:
            t.pnl_dollars = float(getattr(t, "pnl_dollars", 0) or 0) * scale
    cfg.brt_cash = adjusted
    return adjusted, scale if abs(scale - 1.0) >= 1e-12 else 1.0


def compute_metrics(closed: list[BRTTrade], cfg: BRTConfig) -> dict:
    if not closed:
        return {
            "Total_PNL": 0, "Wins": 0, "Losses": 0, "BEs": 0,
            "Profit_Factor": 0, "Losing_Streak": 0, "Expectancy": 0, "Avg_PNL_Pct": "0.00%",
            "Avg_Days_Held": 0, "Median_Days_Held": 0, "Annualized_ROR": 0, "Max_Drawdown": "N/A",
            "CES_AVG": 0, "CES_Median": 0, "P90_Days": 0, "Capital_Days": 0,
            "Profit_Per_Capital_Day": 0, "Avg_Win_Pct": "0.00%", "Avg_Loss_Pct": "0.00%",
            "Win_Loss_Ratio_Dollar": 0, "Pct_PNL_Top10": "0.0%", "Pct_PNL_Bottom10": "0.0%",
            "Pct_Days_Underwater": "N/A", "Max_Days_Underwater": "N/A", "Max_Positions": 0,
            "Pct_PNL_Max_Symbol": "0.0%", "Pct_PNL_Max_Trade": "0.0%", "Pct_PNL_Max_Industry": "0.0%",
            "Trades_With_Meteoric_Rise_History": 0,
            "Pct_Trades_With_Meteoric_Rise_History": "0.0%",
            "Trades_With_Meteoric_Fall_History": 0,
            "Pct_Trades_With_Meteoric_Fall_History": "0.0%",
            "Trades_Post_Entry_Gain_Hit": 0,
            "Pct_Trades_Post_Entry_Gain_Hit": "0.0%",
        }
    total_pnl = sum(t.pnl_dollars for t in closed)
    wins = sum(1 for t in closed if t.pnl_pct > 0)
    losses = sum(1 for t in closed if t.pnl_pct < 0)
    bes = sum(1 for t in closed if t.pnl_pct == 0)
    sum_wins = sum(t.pnl_dollars for t in closed if t.pnl_pct > 0)
    sum_losses = abs(sum(t.pnl_dollars for t in closed if t.pnl_pct < 0))
    pf = sum_wins / sum_losses if sum_losses > 0 else (sum_wins if sum_wins > 0 else 0)
    avg_win = sum_wins / wins if wins else 0
    avg_loss = sum_losses / losses if losses else 0
    # Expectancy = expected $ per trade = total_pnl / n (avg PNL per trade)
    expectancy_dollars = total_pnl / len(closed) if closed else 0
    avg_pnl_pct = sum(t.pnl_pct for t in closed) / len(closed) if closed else 0.0

    days_held = [t.days_held for t in closed if t.days_held > 0]
    avg_days = sum(days_held) / len(days_held) if days_held else 0
    capital_days = sum(days_held)
    p90 = sorted(days_held)[int(len(days_held) * 0.9) - 1] if len(days_held) >= 10 else (max(days_held) if days_held else 0)
    ces_list = [(t.pnl_pct / t.days_held) for t in closed if t.days_held > 0]
    ces_avg = sum(ces_list) / len(ces_list) if ces_list else 0
    ces_median = sorted(ces_list)[len(ces_list) // 2] if ces_list else 0
    median_days = sorted(days_held)[len(days_held) // 2] if days_held else 0
    win_pcts = [t.pnl_pct for t in closed if t.pnl_pct > 0]
    loss_pcts = [t.pnl_pct for t in closed if t.pnl_pct < 0]
    avg_win_pct = sum(win_pcts) / len(win_pcts) if win_pcts else 0.0
    avg_loss_pct = sum(loss_pcts) / len(loss_pcts) if loss_pcts else 0.0
    win_loss_ratio_dollar = (avg_win / avg_loss) if avg_loss > 0 else (float(avg_win) if avg_win > 0 else 0.0)
    sorted_pnl = sorted([t.pnl_dollars for t in closed])
    top10_pnl = sum(sorted_pnl[-10:]) if len(sorted_pnl) >= 10 else sum(sorted_pnl)
    bottom10_pnl = sum(sorted_pnl[:10]) if len(sorted_pnl) >= 10 else sum(sorted_pnl)
    pct_pnl_top10 = (top10_pnl / total_pnl * 100) if total_pnl != 0 else 0.0
    pct_pnl_bottom10 = (bottom10_pnl / total_pnl * 100) if total_pnl != 0 else 0.0
    profit_per_cap_day = total_pnl / capital_days if capital_days > 0 else 0
    ann_ror = ((1 + total_pnl / (cfg.brt_cash * len(closed))) ** (cfg.days_per_year / avg_days) - 1) * 100 if avg_days > 0 and closed else 0

    max_streak = 0
    cur = 0
    for t in closed:
        if t.pnl_pct < 0:
            cur += 1
            max_streak = max(max_streak, cur)
        else:
            cur = 0

    # Concentration: max % of total PnL from a single symbol, single trade, and single industry
    pnl_by_sym: dict[str, float] = {}
    for t in closed:
        pnl_by_sym[t.symbol] = pnl_by_sym.get(t.symbol, 0) + t.pnl_dollars
    max_sym_pnl = max(pnl_by_sym.values()) if pnl_by_sym else 0
    pct_pnl_max_symbol = (max_sym_pnl / total_pnl * 100) if total_pnl != 0 else 0.0
    max_single_trade_pnl = max((abs(t.pnl_dollars) for t in closed), default=0)
    pct_pnl_max_trade = (max_single_trade_pnl / abs(total_pnl) * 100) if total_pnl != 0 else 0.0
    pnl_by_industry: dict[str, float] = {}
    for t in closed:
        ind = (getattr(t, "industry", None) or "").strip() or "(unknown)"
        pnl_by_industry[ind] = pnl_by_industry.get(ind, 0) + t.pnl_dollars
    max_industry_pnl = max(pnl_by_industry.values(), key=abs) if pnl_by_industry else 0
    pct_pnl_max_industry = (abs(max_industry_pnl) / abs(total_pnl) * 100) if total_pnl != 0 else 0.0

    n_tr = len(closed)
    n_rise = sum(1 for t in closed if int(getattr(t, "had_meteoric_rise_before_entry", 0) or 0) == 1)
    n_fall = sum(1 for t in closed if int(getattr(t, "had_meteoric_fall_before_entry", 0) or 0) == 1)
    pct_rise = (n_rise / n_tr * 100.0) if n_tr else 0.0
    pct_fall = (n_fall / n_tr * 100.0) if n_tr else 0.0
    n_pe = sum(1 for t in closed if int(getattr(t, "post_entry_gain_hit", 0) or 0) == 1)
    pct_pe = (n_pe / n_tr * 100.0) if n_tr else 0.0

    return {
        "Total_PNL": f"{total_pnl:.2f}",
        "Wins": wins,
        "Losses": losses,
        "BEs": bes,
        "Profit_Factor": f"{pf:.2f}",
        "Losing_Streak": max_streak,
        "Expectancy": f"{expectancy_dollars:.2f}",
        "Avg_PNL_Pct": f"{avg_pnl_pct:.2f}%",
        "Avg_Days_Held": f"{avg_days:.1f}",
        "Median_Days_Held": median_days,
        "Annualized_ROR": f"{ann_ror:.2f}%",
        "Max_Drawdown": "N/A",
        "CES_AVG": f"{ces_avg:.4f}",
        "CES_Median": f"{ces_median:.4f}",
        "P90_Days": p90,
        "Capital_Days": capital_days,
        "Profit_Per_Capital_Day": f"{profit_per_cap_day:.2f}",
        "Avg_Win_Pct": f"{avg_win_pct:.2f}%",
        "Avg_Loss_Pct": f"{avg_loss_pct:.2f}%",
        "Win_Loss_Ratio_Dollar": f"{win_loss_ratio_dollar:.2f}",
        "Pct_PNL_Top10": f"{pct_pnl_top10:.1f}%",
        "Pct_PNL_Bottom10": f"{pct_pnl_bottom10:.1f}%",
        "DD_Per_Trade": "N/A",
        "Pct_Days_Underwater": "N/A",
        "Max_Days_Underwater": "N/A",
        "Max_Positions": _resolve_max_positions(closed, cfg),
        "Pct_PNL_Max_Symbol": f"{pct_pnl_max_symbol:.1f}%",
        "Pct_PNL_Max_Trade": f"{pct_pnl_max_trade:.1f}%",
        "Pct_PNL_Max_Industry": f"{pct_pnl_max_industry:.1f}%",
        "Trades_With_Meteoric_Rise_History": n_rise,
        "Pct_Trades_With_Meteoric_Rise_History": f"{pct_rise:.1f}%",
        "Trades_With_Meteoric_Fall_History": n_fall,
        "Pct_Trades_With_Meteoric_Fall_History": f"{pct_fall:.1f}%",
        "Trades_Post_Entry_Gain_Hit": n_pe,
        "Pct_Trades_Post_Entry_Gain_Hit": f"{pct_pe:.1f}%",
    }


# ============== CHART (single stock) ==============
def plot_brt_bands(
    sym: str,
    df: pd.DataFrame,
    level3: dict,
    closed: list[BRTTrade],
    output_path: str,
    band_pct: float = 0.02,
    open_trades: Optional[list[BRTTrade]] = None,
) -> None:
    """Plot Close and only bands that resulted in trades (closed=blue). For open trades also draw entry zone (green), band above (teal), band below (coral)."""
    if not HAS_MATPLOTLIB:
        print("matplotlib not installed; skipping chart.", file=sys.stderr)
        return
    fig, ax = plt.subplots(figsize=(14, 7))
    ax.plot(df.index, df["Close"], color="black", linewidth=1, label="Close")

    def draw_band(zc_val: float, color: str, alpha_span: float = 0.12, alpha_line: float = 0.4) -> None:
        if not zc_val or zc_val <= 0:
            return
        zl = zc_val * (1 - band_pct)
        zh = zc_val * (1 + band_pct)
        ax.axhline(y=zc_val, color=color, alpha=alpha_line, linewidth=0.8)
        ax.axhspan(zl, zh, alpha=alpha_span, color=color)

    # Closed: unique zone_centers
    seen_zc: set[float] = set()
    for t in closed:
        if t.symbol != sym or not t.zone_center or t.zone_center <= 0:
            continue
        zc = float(t.zone_center)
        if zc in seen_zc:
            continue
        seen_zc.add(zc)
        draw_band(zc, "blue", alpha_span=0.12, alpha_line=0.4)

    # Open: entry zone + band above + band below
    for t in open_trades or []:
        if t.symbol != sym:
            continue
        draw_band(t.zone_center, "green", alpha_span=0.15, alpha_line=0.6)
        za = getattr(t, "zone_above_center", 0) or 0
        zb = getattr(t, "zone_below_center", 0) or 0
        if za > 0:
            draw_band(za, "teal", alpha_span=0.1, alpha_line=0.5)
        if zb > 0:
            draw_band(zb, "coral", alpha_span=0.1, alpha_line=0.5)

    # Vertical lines: closed trades (green=opened, red=closed); open trades (orange=opened)
    for t in closed:
        if t.symbol != sym:
            continue
        ax.axvline(x=pd.Timestamp(t.date_opened), color="green", alpha=0.5, linestyle="--")
        ax.axvline(x=pd.Timestamp(t.date_closed), color="red", alpha=0.5, linestyle="--")
    for t in open_trades or []:
        if t.symbol != sym:
            continue
        ax.axvline(x=pd.Timestamp(t.date_opened), color="orange", alpha=0.6, linewidth=1.2, linestyle="-")

    ax.set_title(f"Rocket BRT: {sym} - Bands (closed=blue, open=green, above=teal, below=coral) | green/red=closed, orange=open")
    ax.legend()
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()


def _format_eta_remaining(seconds: float) -> str:
    """Compact remaining-time string for the progress line (estimate)."""
    if not (seconds > 0) or not math.isfinite(seconds):
        return "?"
    s = int(round(seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        m, sec = divmod(s, 60)
        return f"{m}m {sec:02d}s"
    h, r = divmod(s, 3600)
    m, sec = divmod(r, 60)
    return f"{h}h {m}m {sec:02d}s"


def _print_symbol_progress(
    done: int,
    total: int,
    t_start: Optional[float] = None,
    label: str = "[PROGRESS]",
) -> None:
    """Overwrite one line with symbol/file progress (use \\r). Caller should print a newline after the batch.

    If ``t_start`` is ``time.perf_counter()`` taken when the batch began (or when the first symbol started),
    show an estimated time remaining based on average time per completed symbol.
    """
    if total <= 1:
        return
    pct = 100.0 * done / total
    eta_part = ""
    if t_start is not None and 0 < done < total:
        elapsed = time.perf_counter() - t_start
        if elapsed > 0:
            remaining_s = (total - done) * (elapsed / float(done))
            rem_str = _format_eta_remaining(remaining_s)
            now = datetime.now()
            finish_at = now + timedelta(seconds=remaining_s)
            if finish_at.date() == now.date():
                done_clock = finish_at.strftime("%H:%M:%S")
            else:
                done_clock = finish_at.strftime("%Y-%m-%d %H:%M")
            eta_part = f"  ~{rem_str} left  (done ~{done_clock})"
    msg = f"{label} {done}/{total} ({pct:.1f}%){eta_part}"
    out = sys.stdout
    if out.isatty():
        try:
            cols = max(40, shutil.get_terminal_size().columns)
        except OSError:
            cols = 80
        # Fixed wide padding used to exceed the terminal width, wrap the line, and break \\r updates.
        pad = max(0, (cols - 1) - len(msg))
        out.write("\r" + msg + " " * pad)
    else:
        out.write(msg + "\n")
    out.flush()


_BRT_CHECKPOINT_VERSION = 1


def _brt_checkpoint_path(output_dir: Path, ts: str, prefix: str = "BRT") -> Path:
    return output_dir / f"{prefix}_Checkpoint_{ts}.pkl"


def _resolve_brt_checkpoint_path(
    output_dir: Path,
    from_checkpoint: str,
    from_run: str,
) -> Optional[Path]:
    """Resolve checkpoint file for --post-only (newest in output_dir if unspecified)."""
    raw = (from_checkpoint or "").strip()
    if raw:
        p = Path(raw)
        if not p.is_absolute():
            p = output_dir / p
        return p
    run_ts = (from_run or "").strip()
    if run_ts:
        if run_ts.endswith(".pkl"):
            p = Path(run_ts)
            return p if p.is_absolute() else output_dir / p
        for prefix in ("IND", "YH", "BRT"):
            candidate = output_dir / f"{prefix}_Checkpoint_{run_ts}.pkl"
            if candidate.is_file():
                return candidate
        return output_dir / f"BRT_Checkpoint_{run_ts}.pkl"
    matches = sorted(
        list(output_dir.glob("IND_Checkpoint_*.pkl"))
        + list(output_dir.glob("YH_Checkpoint_*.pkl"))
        + list(output_dir.glob("BRT_Checkpoint_*.pkl")),
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    )
    return matches[0] if matches else None


def _brt_trade_symbols(*trade_lists: Iterable[Any]) -> set[str]:
    out: set[str] = set()
    for lst in trade_lists:
        for t in lst or []:
            s = (getattr(t, "symbol", None) or "").strip().upper()
            if s:
                out.add(s)
    return out


def _load_tickers_for_symbols(
    symbols: set[str],
    data_dir: Path,
    *,
    use_duckdb: bool,
    db_path: str,
    db_table: str,
    pipeline: Optional[Any] = None,
    extra_symbols: Optional[set[str]] = None,
) -> dict[str, pd.DataFrame]:
    syms = set(symbols)
    if extra_symbols:
        syms |= {s.strip().upper() for s in extra_symbols if s}
    tickers: dict[str, pd.DataFrame] = {}
    _load_ctx = pipeline.phase("load_tickers") if pipeline is not None else None
    if _load_ctx is not None:
        _load_ctx.__enter__()
    try:
        for sym in sorted(syms):
            df_sym = _load_symbol_data(sym, data_dir, use_duckdb=use_duckdb, db_path=db_path, db_table=db_table)
            if df_sym is not None and not df_sym.empty:
                tickers[sym] = df_sym
    finally:
        if _load_ctx is not None:
            _load_ctx.__exit__(None, None, None)
    return tickers


def _save_brt_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".pkl.tmp")
    with open(tmp, "wb") as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(path)


def _load_brt_checkpoint(path: Path) -> dict[str, Any]:
    with open(path, "rb") as f:
        data = pickle.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"checkpoint is not a dict: {path}")
    ver = int(data.get("version", 0) or 0)
    if ver != _BRT_CHECKPOINT_VERSION:
        raise ValueError(
            f"unsupported checkpoint version {ver} in {path.name} "
            f"(expected {_BRT_CHECKPOINT_VERSION})"
        )
    return data


def _backtest_progress(
    done: int,
    total: int,
    t_start: Optional[float],
    pipeline: Optional[Any],
) -> None:
    if pipeline is not None and getattr(pipeline, "enabled", False):
        pipeline.backtest_tick(done, total)
    elif total > 1:
        _print_symbol_progress(done, total, t_start)


def _print_profile_symbol_summary(rows: list[dict]) -> None:
    """Print aggregate per-section timings from _process_symbol (use with --profile)."""
    if not rows:
        return
    df = pd.DataFrame(rows)
    phase_cols = [
        c
        for c in (
            "t_load",
            "t_spy_lookup",
            "t_pivots",
            "t_structure",
            "t_touch",
            "t_backtest",
            "t_collect_pivots",
            "bt_indicators",
        )
        if c in df.columns
    ]
    if not phase_cols:
        return
    n = len(df)
    total_sum = float(df["t_total"].sum()) if "t_total" in df.columns else 0.0
    print(f"[PROFILE] Per-symbol section timings ({n} symbols, t_total sum={total_sum:.1f}s):")
    for col in phase_cols:
        s = float(df[col].fillna(0.0).sum())
        m = float(df[col].fillna(0.0).mean())
        pct = (100.0 * s / total_sum) if total_sum > 0 else 0.0
        print(f"  {col:20s}  sum={s:8.1f}s  mean={m*1000:6.1f}ms/sym  ({pct:4.1f}% of t_total)")
    _bt_cols = sorted(c for c in df.columns if c.startswith("bt_") and c != "bt_indicators")
    if _bt_cols:
        print("[PROFILE] run_brt_backtest internals (mean s/symbol):")
        _means = df[_bt_cols].fillna(0.0).mean().sort_values(ascending=False)
        for col in _means.head(12).index:
            print(f"  {col:28s}  {float(_means[col]):.4f}s")
        if len(_means) > 12:
            print(f"  ... +{len(_means) - 12} more bt_* columns in Profile_Symbols CSV")


def _plan_post_pipeline_units(
    pipeline: Optional[Any],
    all_closed: list[BRTTrade],
    all_open: list[BRTTrade],
    cfg: BRTConfig,
    *,
    will_yfinance: bool,
    will_equity: bool,
    will_correlation: bool,
    will_regression: bool,
    will_zscore_filter: bool,
) -> None:
    if pipeline is None or not getattr(pipeline, "enabled", False):
        return
    trade_syms = {(t.symbol or "").strip().upper() for t in all_closed + all_open if getattr(t, "symbol", None)}
    n_trade_syms = len(trade_syms)
    n_ind = n_trade_syms if bool(getattr(cfg, "use_indicators", False)) and n_trade_syms else 0
    weights: dict[str, int] = {}
    if will_yfinance and n_trade_syms:
        weights["yfinance_enrich"] = max(1, n_trade_syms)
    if n_trade_syms:
        weights["post_entry_gain_hit"] = max(1, n_trade_syms)
    if n_ind:
        weights["entry_indicators"] = max(1, n_ind)
    weights["market_cap_filter"] = 1
    weights["dollar_scale"] = 1 if all_closed else 0
    weights["write_closed"] = 1
    weights["write_breakout_retest"] = 1
    weights["write_would_have"] = 1
    weights["correlation_report"] = 1 if will_correlation else 0
    weights["write_open"] = 1
    weights["write_misc"] = 1
    weights["compute_equity_metrics"] = 3 if will_equity else 0
    weights["write_reports"] = 1
    if will_zscore_filter:
        weights["zscore_post_filter"] = 1
    weights["regression_check"] = 2 if will_regression else 0
    pipeline.add_post_units(**{k: v for k, v in weights.items() if v > 0})


def _brt_closed_sort_key(t: BRTTrade) -> tuple[str, str]:
    d = str(getattr(t, "date_opened", "") or "").strip().replace("-", "")[:8]
    side = str(getattr(t, "side", "LONG") or "LONG").upper()
    return (d, side)


def _merge_closed_dual_streams(closed_long: list[BRTTrade], closed_short: list[BRTTrade]) -> list[BRTTrade]:
    merged = list(closed_long) + list(closed_short)
    merged.sort(key=_brt_closed_sort_key)
    return merged


def _tag_breakout_rows_side(rows: Iterable[dict], side_label: str) -> None:
    for r in rows:
        if isinstance(r, dict):
            r["SIDE"] = side_label


def _dual_bundle_primary_extra_open(
    open_long: Optional[BRTTrade],
    open_short: Optional[BRTTrade],
) -> tuple[Optional[BRTTrade], list[BRTTrade]]:
    """If both sides have an open position, LONG stays in the primary slot; SHORT is listed as extras."""
    if open_long is not None and open_short is not None:
        return open_long, [open_short]
    if open_long is not None:
        return open_long, []
    return open_short, []


def _process_symbol(args: tuple) -> tuple:
    """Worker: process one symbol. Picklable for ProcessPoolExecutor.

    Tuple forms (optional tail for --print-zones in parallel runs):
    - (sym, csv_path, cfg_dict[, reference_stats[, do_profile_bt[, use_duckdb, db_path, db_table
      [, zones_out_dir, zones_ts, file_prefix, print_zones]]]]])
    Returns 13-tuple ending with watchlist, breakout_retest_rows, extra_open_trades, indicators_while_held.
    """
    do_profile_bt = False
    use_duckdb, db_path, db_table = False, "", "prices"
    zones_out_dir, zones_ts, file_prefix, print_zones = "", "", "BRT", False
    if len(args) >= 12:
        (
            sym,
            csv_path,
            cfg_dict,
            reference_stats,
            do_profile_bt,
            use_duckdb,
            db_path,
            db_table,
            zones_out_dir,
            zones_ts,
            file_prefix,
            print_zones,
        ) = (
            args[0],
            args[1],
            args[2],
            args[3],
            bool(args[4]),
            bool(args[5]),
            str(args[6] or ""),
            str(args[7] or "prices"),
            str(args[8] or ""),
            str(args[9] or ""),
            str(args[10] or "BRT"),
            bool(args[11]),
        )
    elif len(args) >= 8:
        sym, csv_path, cfg_dict, reference_stats, do_profile_bt, use_duckdb, db_path, db_table = (
            args[0], args[1], args[2], args[3], bool(args[4]), bool(args[5]), str(args[6] or ""), str(args[7] or "prices")
        )
    elif len(args) >= 5:
        sym, csv_path, cfg_dict, reference_stats, do_profile_bt = args[0], args[1], args[2], args[3], bool(args[4])
    elif len(args) >= 4:
        sym, csv_path, cfg_dict, reference_stats = args[0], args[1], args[2], args[3]
    else:
        sym, csv_path, cfg_dict = args[0], args[1], args[2]
        reference_stats = None
    t0 = time.time()
    if use_duckdb:
        if _db_load_symbol_df is None:
            raise RuntimeError("DuckDB mode requested but ohlcv_store is unavailable.")
        df = _db_load_symbol_df(sym, db_path=db_path, table=db_table)
    else:
        df = load_csv(csv_path)
    t_load = time.time() - t0
    cfg = BRTConfig(**cfg_dict)
    _configure_ind_score_from_cfg(cfg)
    _min_req = _min_bars_required_for_cfg(cfg)
    if use_duckdb:
        data_dir = Path(csv_path).parent
    else:
        data_dir = Path(csv_path).parent
    benchmark_df = _load_benchmark_unified(
        use_duckdb=use_duckdb,
        db_path=db_path,
        db_table=db_table,
        data_dir=data_dir,
    )
    _t_spy = time.time()
    spy_lookup = _resolve_spy_ind_diff_lookup(cfg, benchmark_df)
    t_spy_lookup = time.time() - _t_spy
    if len(df) < _min_req:
        timing = {
            "symbol": sym, "bars": int(len(df)), "t_load": t_load, "t_spy_lookup": t_spy_lookup,
            "t_pivots": 0.0, "t_structure": 0.0, "t_touch": 0.0, "t_backtest": 0.0,
            "t_collect_pivots": 0.0, "t_total": time.time() - t0,
        }
        return (sym, [], None, [], [], [], [], timing, {}, [], [], [], [])
    if _skip_brt_pivot_stack(cfg):
        t_pivots = 0.0
        t_structure = 0.0
        t_touch = 0.0
        block_reasons: dict[str, int] = {}
        bt_sections: dict[str, float] = {}
        t4 = time.time()
        closed, open_trade, scanner, short_cands, would_have, _watchlist, extra_open_trades = (
            _run_alt_entry_backtest_bundle(sym, df, cfg, benchmark_df)
        )
        t_backtest = time.time() - t4
        pivot_rows: list = []
        t_collect_pivots = 0.0
        timing = {
            "symbol": sym,
            "bars": int(len(df)),
            "t_load": t_load,
            "t_spy_lookup": t_spy_lookup,
            "t_pivots": t_pivots,
            "t_structure": t_structure,
            "t_touch": t_touch,
            "t_backtest": t_backtest,
            "t_collect_pivots": t_collect_pivots,
            "t_total": time.time() - t0,
        }
        if do_profile_bt and bt_sections:
            timing.update(bt_sections)
        _apply_spy_ind_diff_at_entry(closed, open_trade, extra_open_trades, spy_lookup)
        return (
            sym,
            closed,
            open_trade,
            scanner,
            short_cands,
            pivot_rows,
            would_have,
            timing,
            block_reasons,
            _watchlist,
            [],
            extra_open_trades,
            [],
        )
    t1 = time.time()
    pivot_high, pivot_low, ph_price, pl_price = compute_pivots(
        df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m, realtime_filter_enabled=cfg.realtime_filter_enabled
    )
    t_pivots = time.time() - t1
    t2 = time.time()
    struct = compute_market_structure(df, pivot_high, pivot_low, ph_price, pl_price)
    t_structure = time.time() - t2
    t3 = time.time()
    level3 = build_level3_for_cfg(
        df, cfg, pivot_high, pivot_low, ph_price, pl_price, debug_symbol=sym,
    )
    t_touch = time.time() - t3
    block_reasons: dict[str, int] = {}
    bt_sections: dict[str, float] = {}
    t4 = time.time()
    _brt_breakout_retest_rows: list[dict] = []
    _ind_wh_rows: list[dict] = []
    _ind_wh_out = (
        _ind_wh_rows if _indicator_mode_active(cfg) else None
    )
    zone_entries_debug: list = [] if print_zones else None
    _tt_mm = _normalize_transaction_type(getattr(cfg, "transaction_type", "long"))
    if _tt_mm == "both":
        br_long: list[dict] = []
        br_short: list[dict] = []
        cfg_long = replace(cfg, entry_type="long", transaction_type="long")
        cfg_short = replace(cfg, entry_type="short", transaction_type="short")
        closed_l, ot_l, scan_l, sc_l, wh_l, wl_l, extra_l = run_brt_backtest(
            sym, df, cfg_long, ph_price, pl_price, struct, level3,
            zone_entries_debug=zone_entries_debug,
            benchmark_df=benchmark_df,
            reference_stats=reference_stats, profile_block_reasons=block_reasons,
            profile_backtest_sections=bt_sections if do_profile_bt else None,
            breakout_retest_rows_out=br_long,
            indicators_while_held_rows_out=_ind_wh_out,
        )
        _tag_breakout_rows_side(br_long, "LONG")
        closed_s, ot_s, scan_s, sc_s, wh_s, wl_s, extra_s = run_brt_backtest(
            sym, df, cfg_short, ph_price, pl_price, struct, level3, benchmark_df=benchmark_df,
            reference_stats=reference_stats, profile_block_reasons=block_reasons,
            profile_backtest_sections=bt_sections if do_profile_bt else None,
            breakout_retest_rows_out=br_short,
            indicators_while_held_rows_out=_ind_wh_out,
        )
        _tag_breakout_rows_side(br_short, "SHORT")
        _brt_breakout_retest_rows = br_long + br_short
        closed = _merge_closed_dual_streams(closed_l, closed_s)
        scanner = scan_l + scan_s
        short_cands = sc_l + sc_s
        would_have = wh_l + wh_s
        _watchlist = _merge_dual_stream_watchlists(wl_l, wl_s, cfg)
        open_trade, extra_from_dual = _dual_bundle_primary_extra_open(ot_l, ot_s)
        extra_open_trades = list(extra_l) + list(extra_s) + list(extra_from_dual)
    else:
        closed, open_trade, scanner, short_cands, would_have, _watchlist, extra_open_trades = run_brt_backtest(
            sym, df, cfg, ph_price, pl_price, struct, level3,
            zone_entries_debug=zone_entries_debug,
            benchmark_df=benchmark_df,
            reference_stats=reference_stats, profile_block_reasons=block_reasons,
            profile_backtest_sections=bt_sections if do_profile_bt else None,
            breakout_retest_rows_out=_brt_breakout_retest_rows,
            indicators_while_held_rows_out=_ind_wh_out,
        )
    t_backtest = time.time() - t4
    if print_zones and zones_out_dir.strip() and zones_ts:
        _write_zone_debug_files(
            sym,
            df,
            level3,
            zone_entries_debug or [],
            cfg.band_pct,
            zones_out_dir.strip(),
            zones_ts,
            file_prefix or _output_file_prefix(cfg),
        )
    t5 = time.time()
    pivot_rows = collect_brt_pivots(sym, df, pivot_high, pivot_low, ph_price, pl_price, struct)
    t_collect_pivots = time.time() - t5
    timing = {
        "symbol": sym,
        "bars": int(len(df)),
        "t_load": t_load,
        "t_spy_lookup": t_spy_lookup,
        "t_pivots": t_pivots,
        "t_structure": t_structure,
        "t_touch": t_touch,
        "t_backtest": t_backtest,
        "t_collect_pivots": t_collect_pivots,
        "t_total": time.time() - t0,
    }
    if do_profile_bt and bt_sections:
        timing.update(bt_sections)
    _apply_spy_ind_diff_at_entry(closed, open_trade, extra_open_trades, spy_lookup)
    return (
        sym,
        closed,
        open_trade,
        scanner,
        short_cands,
        pivot_rows,
        would_have,
        timing,
        block_reasons,
        _watchlist,
        _brt_breakout_retest_rows,
        extra_open_trades,
        _ind_wh_rows,
    )


def run_brt_backtest_batch(
    data_dir: str,
    cfg: BRTConfig,
    n_workers: int = 0,
) -> tuple[list[BRTTrade], dict[str, Any]]:
    """
    Run BRT backtest over all tickers in data_dir. Returns (all_closed, metrics).
    For optimizer or programmatic use. No file output.
    """
    data_path = Path(data_dir)
    tickers = load_all_tickers(str(data_path))
    _min_b = _min_bars_required_for_cfg(cfg)
    ticker_list = sorted([s for s, df in tickers.items() if len(df) >= _min_b])
    all_closed: list[BRTTrade] = []
    cfg_dict = asdict(cfg)
    n_w = max(0, n_workers)
    if n_w > 0:
        n_w = min(n_w, os.cpu_count() or 4)
    all_open: list[BRTTrade] = []
    if n_w > 0:
        _spy_batch_df = _load_benchmark_unified(
            use_duckdb=False, db_path="", db_table="prices", data_dir=data_path
        )
        _spy_batch_lookup = _get_spy_ind_diff_lookup(_spy_batch_df, cfg) if _spy_batch_df is not None else None
        tasks = [
            (sym, str(data_path / f"{sym}.csv"), cfg_dict)
            for sym in ticker_list
            if (data_path / f"{sym}.csv").exists()
        ]
        n_batch = len(tasks)
        done_b = 0
        progress_t0 = time.perf_counter()
        with _make_brt_process_pool(
            n_w,
            _spy_batch_lookup,
            use_duckdb=False,
            db_path="",
            db_table="prices",
            data_dir=data_path,
        ) as ex:
            for future in as_completed(ex.submit(_process_symbol, t) for t in tasks):
                res_bt = future.result()
                if len(res_bt) >= 12:
                    _, closed, open_trade, scanner, _, _, _, _, _, _, _, extra_opens_bt = res_bt[:12]
                elif len(res_bt) == 11:
                    _, closed, open_trade, scanner, _, _, _, _, _, _, _ = res_bt
                    extra_opens_bt = []
                else:
                    raise ValueError(f"_process_symbol returned {len(res_bt)} values (expected 11 or 12)")
                all_closed.extend(closed)
                if open_trade is not None:
                    all_open.append(open_trade)
                for _xo in extra_opens_bt or []:
                    all_open.append(_xo)
                done_b += 1
                _print_symbol_progress(done_b, n_batch, progress_t0)
        if n_batch > 1:
            print()
    else:
        n_seq = len(ticker_list)
        benchmark_df_batch = _load_benchmark_local(data_path)
        spy_lookup_batch = _get_spy_ind_diff_lookup(benchmark_df_batch, cfg)
        progress_t0 = time.perf_counter()
        for idx, sym in enumerate(ticker_list, 1):
            df = tickers[sym]
            pivot_high, pivot_low, ph_price, pl_price = compute_pivots(
                df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m, realtime_filter_enabled=cfg.realtime_filter_enabled
            )
            struct = compute_market_structure(df, pivot_high, pivot_low, ph_price, pl_price)
            level3 = build_level3_for_cfg(
                df, cfg, pivot_high, pivot_low, ph_price, pl_price, debug_symbol=sym,
            )
            _tt_batch = _normalize_transaction_type(getattr(cfg, "transaction_type", "long"))
            if _tt_batch == "both":
                br_lo: list[dict] = []
                br_sh: list[dict] = []
                cfg_lo = replace(cfg, entry_type="long", transaction_type="long")
                cfg_sh = replace(cfg, entry_type="short", transaction_type="short")
                closed_lo, ot_lo, _, _, _, _, extra_lo = run_brt_backtest(
                    sym, df, cfg_lo, ph_price, pl_price, struct, level3, breakout_retest_rows_out=br_lo,
                )
                _tag_breakout_rows_side(br_lo, "LONG")
                closed_sh, ot_sh, _, _, _, _, extra_sh = run_brt_backtest(
                    sym, df, cfg_sh, ph_price, pl_price, struct, level3, breakout_retest_rows_out=br_sh,
                )
                _tag_breakout_rows_side(br_sh, "SHORT")
                closed = _merge_closed_dual_streams(closed_lo, closed_sh)
                ot_pri, ot_extras = _dual_bundle_primary_extra_open(ot_lo, ot_sh)
                ot_extras = list(extra_lo) + list(extra_sh) + list(ot_extras)
                _apply_spy_ind_diff_at_entry(closed, ot_pri, ot_extras, spy_lookup_batch)
                all_closed.extend(closed)
                if ot_pri is not None:
                    all_open.append(ot_pri)
                all_open.extend(ot_extras)
            else:
                closed, open_trade, _, _, _, _, extra_one = run_brt_backtest(
                    sym, df, cfg, ph_price, pl_price, struct, level3,
                    benchmark_df=benchmark_df_batch,
                )
                _apply_spy_ind_diff_at_entry(closed, open_trade, extra_one, spy_lookup_batch)
                all_closed.extend(closed)
                if open_trade is not None:
                    all_open.append(open_trade)
                all_open.extend(extra_one)
            if n_seq > 1:
                _print_symbol_progress(idx, n_seq, progress_t0)
        if n_seq > 1:
            print()
    if all_closed:
        _apply_report_dollar_scale_to_trades(all_closed, all_open, cfg)
    _enrich_post_entry_gain_hit(all_closed + all_open, tickers, cfg)
    metrics = compute_metrics(all_closed, cfg)
    if cfg.compute_equity_metrics and HAS_EQUITY_METRICS and all_closed and tickers and _compute_equity_metrics:
        try:
            equity = _compute_equity_metrics(
                all_closed,
                all_open,
                tickers,
                cfg.brt_cash,
                initial_capital=cfg.initial_capital,
                aggressive=cfg.aggressive,
                aggressive_margin_interest=cfg.aggressive_margin_interest,
                aggressive_max_multiple=cfg.aggressive_max_multiple,
                aggressive_avg_positions=(cfg.aggressive_avg_positions if cfg.aggressive_avg_positions > 0 else None),
                aggressive_sizing_equity_cap=cfg.aggressive_sizing_equity_cap,
                margin_utilization=_effective_margin_utilization(cfg),
                aggressive_sell=_normalize_aggressive_sell(getattr(cfg, "aggressive_sell", "false")),
                skip_passive_mtm_for_aggressive=bool(
                    getattr(cfg, "equity_fast_aggressive", False) and cfg.aggressive
                ),
            )
            metrics["Max_Drawdown"] = equity["Max_Drawdown"]
            metrics["Max_Days_Underwater"] = equity["Max_Days_Underwater"]
            metrics["Pct_Days_Underwater"] = equity["Pct_Days_Underwater"]
            if equity.get("_aggressive"):
                metrics["Aggressive_Avg_Positions"] = equity.get("Aggressive_Avg_Positions", 0)
                metrics["Aggressive_Days_AtOrBelow_Avg"] = equity.get("Aggressive_Days_AtOrBelow_Avg", 0)
                metrics["Aggressive_Days_In_Margin"] = equity.get("Aggressive_Days_In_Margin", 0)
                metrics["Aggressive_Days_Trimmed_Over_2xAvg"] = equity.get("Aggressive_Days_Trimmed_Over_2xAvg", 0)
                metrics["Aggressive_Max_Drawdown"] = equity.get("Aggressive_Max_Drawdown", "N/A")
                agg_total_pnl = float(equity.get("_equity_total_pnl", 0.0) or 0.0)
                metrics["Aggressive_Total_PNL"] = f"{agg_total_pnl:.2f}"
            md = equity["Max_Drawdown"]
            if md and str(md).strip() != "N/A":
                try:
                    pct_val = float(str(md).replace("%", "").strip()) / 100
                    metrics["DD_Per_Trade"] = f"{(pct_val / len(all_closed)):.4f}" if all_closed else "N/A"
                except (ValueError, TypeError):
                    metrics["DD_Per_Trade"] = "N/A"
            else:
                metrics["DD_Per_Trade"] = "N/A"
        except Exception as e:
            print(f"[WARN] Equity metrics failed: {e}", file=sys.stderr)
    return all_closed, metrics


def _maybe_play_completion_sound(enabled: bool) -> None:
    """Notify that a long run finished.

    Windows: ``winsound.Beep`` (frequency Hz, duration ms) — longer and clearer than ``MessageBeep``.
    Loudness follows the system output volume; raise Windows volume or use speakers for more impact.
    Other OS: several ASCII bells in a row.
    """
    if not enabled:
        return
    try:
        if sys.platform == "win32":
            import winsound

            # Short ascending chime (~1.7s total); tweak freq (Hz) / dur (ms) / sleep for taste.
            for freq, dur in ((666, 2500), (659, 450), (784, 550)):
                winsound.Beep(int(freq), int(dur))
                time.sleep(0.06)
        else:
            for _ in range(3):
                sys.stdout.write("\a")
                sys.stdout.flush()
                time.sleep(0.2)
    except Exception:
        pass


def _symbol_list_from_arg(symbol_arg: str) -> list[str]:
    """Parse ``-s`` / ``--symbol``: comma-separated tickers, stripped and uppercased. Empty -> []."""
    if not (symbol_arg or "").strip():
        return []
    return [p.strip().upper() for p in symbol_arg.split(",") if p.strip()]


# ============== MAIN ==============
def main() -> int:
    ap = argparse.ArgumentParser(description="Rocket BRT Backtest")
    ap.add_argument("data_dir", nargs="?", default="data/newdata/data", help="Data directory")
    ap.add_argument("--output-dir", "-o", default="drive", help="Output directory")
    ap.add_argument("--use-duckdb", action="store_true", help="Load OHLCV from DuckDB instead of per-symbol CSV files.")
    ap.add_argument(
        "--db-path",
        type=str,
        default="",
        help="DuckDB file path (default: first ohlcv.duckdb near data_dir with a prices table, e.g. data/ohlcv.duckdb).",
    )
    ap.add_argument("--db-table", type=str, default="prices", help="DuckDB table name for OHLCV (default: prices).")
    ap.add_argument(
        "--symbol",
        "-s",
        default="",
        help="Ticker whitelist: one symbol (loads that CSV, enables chart) or comma list "
        "e.g. AAPL,MSFT (only those symbols from data_dir; no chart).",
    )
    ap.add_argument("--initial-capital", type=float, default=500000.0,
                    help="Portfolio starting equity for drawdown/equity curve (default 500000, independent of brt_cash)")
    ap.add_argument("--drive-link", default="", help="Override Google Drive link (default: https://drive.google.com/drive/search?q=<timestamp>)")
    ap.add_argument("--exit-at-close-when-stopped", action="store_true",
                    help="When stop hit, use bar close as exit price (may match manual)")
    ap.add_argument("--stop-pct-multiplier", action="store_true",
                    help="Use stop_pct as multiplier (0.934) instead of fraction-below (0.066)")
    ap.add_argument("--debug-signals", action="store_true",
                    help="Print all buy signals and maturity events for the symbol (use with -s)")
    ap.add_argument("--print-zones", action="store_true",
                    help="Write {prefix}_ZONES_<sym>_<ts>.csv and {prefix}_ZONES_ENTRIES_<sym>_<ts>.csv "
                    "(prefix=BRT, YH when yh_zones-only, IND when indicator_buy=only). "
                    "Works for every symbol in -s (sequential or process-pool).")
    ap.add_argument("--debug-symbol", type=str, default=None,
                    help="Enable verbose debug logging for a specific symbol (e.g., ATUSF)")
    ap.add_argument("--debug-date", type=str, default=None,
                    help="Focus debug logging around a specific date (e.g., 2022-07-26)")
    ap.add_argument(
        "--debug-entry",
        nargs=2,
        metavar=("SYMBOL", "DATE"),
        default=None,
        help="Shorthand for --debug-symbol SYMBOL --debug-date DATE (DEBUG-ENTRY / gate lines for maturities in that month). "
        "Example: -s NFLX --debug-entry NFLX 2023-01-20",
    )
    ap.add_argument("--trace-date", action="append", default=[],
                    help="Exact eval-bar date(s) to trace gate-by-gate (YYYY-MM-DD or YYYYMMDD); repeatable")
    ap.add_argument("--trace-symbol", type=str, default=None,
                    help="Optional symbol filter for --trace-date (defaults to --symbol when set)")
    ap.add_argument(
        "--trace-indicator-buy",
        action="store_true",
        help="Print [IND-GATE] lines when indicator_buy is only/both (diff + sheet-gate skip). "
        "Use with -w 0 -s SYMBOL on full runs; very noisy with -w N.",
    )
    ap.add_argument(
        "--indicator-cache-dir",
        default="",
        help="Directory for per-symbol indicator precompute cache (default: <data-dir>/.brt_indicator_cache).",
    )
    ap.add_argument(
        "--no-indicator-cache",
        action="store_true",
        help="Disable indicator precompute disk/memory cache (rebuild all symbols every run).",
    )
    ap.add_argument("--workers", "-w", type=int, default=-1,
                    help="Parallel workers: -1=auto min(8, CPU count); 0=sequential. Single ticker with -s always sequential; comma list uses pool. When >0, same count caps parallel Yahoo (yfinance) fetches after the backtest.")
    ap.add_argument("--profile", action="store_true",
                    help="Print timing for load, benchmark, backtest, beta, write, correlation, and equity phases (use: --profile)")
    ap.add_argument(
        "--no-instrument",
        action="store_true",
        help="Disable full-pipeline [PIPELINE] progress, phase timing summary, CSV/JSON export, and DuckDB timing store",
    )
    ap.add_argument(
        "--instrument-db",
        type=str,
        default="",
        help="DuckDB file for run timing history (default: <output_dir>/brt_profile.duckdb)",
    )
    ap.add_argument(
        "--post-only",
        action="store_true",
        help="Skip backtest; run post-processing from BRT_Checkpoint_<ts>.pkl (default OFF). "
        "Use --from-run TS or --from-checkpoint PATH; else newest checkpoint in -o output dir.",
    )
    ap.add_argument(
        "--from-checkpoint",
        type=str,
        default="",
        help="Checkpoint .pkl for --post-only (default: newest BRT_Checkpoint_*.pkl in output dir)",
    )
    ap.add_argument(
        "--from-run",
        type=str,
        default="",
        metavar="TS",
        help="Run id for --post-only, e.g. 260517070023 loads <output>/BRT_Checkpoint_260517070023.pkl",
    )
    ap.add_argument(
        "--no-checkpoint",
        action="store_true",
        help="After a normal backtest, do not write BRT_Checkpoint_<ts>.pkl (default: write checkpoint)",
    )
    ap.add_argument("--cprofile", action="store_true",
                    help="Write cProfile stats for run_brt_backtest only (requires --symbol SYM; use with --profile for bt_* CSV columns)")
    ap.add_argument("--cprofile-out", type=str, default="",
                    help="Output path for --cprofile .prof file (default: drive/BRT_cProfile_<SYM>_<ts>.prof)")
    ap.add_argument("--cprofile-sheet-magic-touch", action="store_true",
                    help="cProfile only the per-bar sheet magic touch block (AR/AW); requires --symbol")
    ap.add_argument("--cprofile-sheet-magic-touch-out", type=str, default="",
                    help="Output .prof for --cprofile-sheet-magic-touch (default: drive/BRT_cProfile_sheet_magic_touch_<SYM>_<ts>.prof)")
    ap.add_argument("--cprofile-pending-sheet-prep", action="store_true",
                    help="cProfile only the per-bar pending sheet prep block (AQ/AK prep); requires --symbol")
    ap.add_argument("--cprofile-pending-sheet-prep-out", type=str, default="",
                    help="Output .prof for --cprofile-pending-sheet-prep (default: drive/BRT_cProfile_pending_sheet_prep_<SYM>_<ts>.prof)")
    ap.add_argument("--play-sound", action="store_true",
                    help="Play a short beep when the run exits (Windows: system OK beep; else terminal bell)")
    ap.add_argument("--emit-would-have", action="store_true",
                    help="Emit BRT_WouldHave_<ts>.csv for maturities blocked only by growth/tight_range/consolidation (for DrawdownCalc --show-would-have)")
    ap.add_argument("--no-regression", action="store_true",
                    help="Skip regression check after backtest (default: run BRTRegressionCheck.ps1)")
    ap.add_argument("--no-equity-metrics", action="store_true",
                    help="Skip Max_Drawdown / equity curve / underwater metrics (saves minutes on large --aggressive runs)")
    ap.add_argument(
        "--equity-fast-aggressive",
        action="store_true",
        help="With --aggressive: skip passive Equity_Regular CSV (passive Max_DD still computed; much faster on large runs)",
    )
    ap.add_argument("--aggressive", action="store_true",
                    help="Aggressive equity: each entry = equity×2/avg_positions; margin interest on borrowed notional")
    ap.add_argument("--aggressive-margin-interest", type=float, default=0.10,
                    help="Annual margin interest rate for --aggressive (default 0.10)")
    ap.add_argument("--aggressive-max-multiple", type=float, default=2.0,
                    help="Max gross exposure multiple of initial_capital for --aggressive (default 2.0)")
    ap.add_argument("--aggressive-avg-positions", type=float, default=0.0,
                    help="Override avg positions for --aggressive (default auto from active-position history)")
    ap.add_argument("--aggressive-sizing-equity-cap", type=float, default=10.0,
                    help="Cap equity for aggressive entry sizing at initial_capital×this (default 10; does not cap reported equity)")
    ap.add_argument(
        "--margin-utilization",
        type=float,
        default=0.6,
        help="Fraction of margin buying power to deploy (initial_capital×max_multiple×util / max_positions). "
        "Default 0.6; --aggressive uses 1.0 (full margin account).",
    )
    ap.add_argument("--symbol-reentry-cooldown-days", type=int, default=0,
                    help="Calendar days after exit before re-entering the same symbol (0=off). "
                    "Blocks churn; setup stays pending and may enter after cooldown.")
    ap.add_argument("--band-pct", type=float, default=None,
                    help="Zone band ±pct (default 0.02=2%%)")
    ap.add_argument("--band-pct-atr", type=float, default=None,
                    help="When >0, zone half-width = (band_pct_atr * ATR14) / touch_price at pivot (0=use --band-pct only)")
    ap.add_argument("--strong-pre-pivot-pct-atr", type=float, default=None,
                    help="When >0, strong pre threshold = (mult * ATR14) / pivot_price (0=use fixed strong_pre_pivot_pct)")
    ap.add_argument("--strong-post-pivot-pct-atr", type=float, default=None,
                    help="When >0, strong post threshold = (mult * ATR14) / pivot_price (0=use fixed strong_post_pivot_pct)")
    ap.add_argument("--close-above-window", type=int, default=None,
                    help="Close>zone allowed on maturity-touch day or N days after (default 1 = same or next day only)")
    ap.add_argument("--level-acceptance", type=str, default="",
                    help="Optional legacy gate (not sheet AL): N of last M closes above anchor low, e.g. '7/10' (default off; 0/10 in config)")
    ap.add_argument("--level-acceptance-anchor-mode", type=str, default=None, choices=["strict", "rolling"],
                    help="Level Acceptance anchor mode: strict=current/prior ST, rolling=any ST in recent window")
    ap.add_argument("--level-acceptance-anchor-window", type=int, default=None,
                    help="When anchor mode is rolling, bars to look back for a Support Test anchor (default 10)")
    ap.add_argument("--no-support-test", action="store_true",
                    help="Disable Support Test anchor (internal ladder / AK-style overlap path)")
    ap.add_argument("--breakout-bars", type=int, default=None,
                    help="AP breakout lookback bars (legacy AQ internals; default 100)")
    ap.add_argument("--tight-range-off", action="store_true",
                    help="Disable Tight Range Qualifier (block levels in compressed ranges)")
    ap.add_argument("--tight-range-threshold", type=float, default=None,
                    help="Tight Range Qualifier: RangePct must exceed this (default 0.35=35%%)")
    ap.add_argument("--tight-range-lookback", type=int, default=None,
                    help="Tight Range Qualifier lookback bars (default 105)")
    ap.add_argument("--tradeable-key-level-off", action="store_true",
                    help="(Legacy) TKL is off by default; this forces Tradeable Key Level gate off")
    ap.add_argument("--lookback-short", type=int, default=None,
                    help="Short lookback for touch_count_short (used if TKL enabled), default 105 bars")
    ap.add_argument("--consolidation-blocker-off", action="store_true",
                    help="Disable Consolidation Blocker (CB) so consolidation boxes do not block entries")
    ap.add_argument("--growth-filter", action="store_true",
                    help="Enable growth filter: require price at entry >= price growth_bars days ago (default: on)")
    ap.add_argument("--no-growth-filter", action="store_true",
                    help="Disable growth filter (default is enabled with growth_bars=756)")
    ap.add_argument(
        "--no-require-close-gt-open",
        action="store_true",
        help="Disable signal-bar direction gate (long: Close>Open; short: Close<Open)",
    )
    ap.add_argument("--growth-bars", type=int, default=756,
                    help="Growth lookback in bars: require Close[entry] >= Close[entry - N]; 756 = 3 years (default 756)")
    ap.add_argument(
        "--growth-history-slack-bars",
        type=int,
        default=None,
        help="Allow growth filter when eval_bar >= growth_bars - N (default 2; sheet 2016-01-01 anchor vs CSV start)",
    )
    ap.add_argument(
        "--relative-strength",
        action="store_true",
        help="Relative strength mode: enter when stock beats SPY on 252/504/756-bar total returns (all strict); skips zone/retest gates; needs SPY.csv in data dir",
    )
    ap.add_argument("--meteoric-rise-pct", type=float, default=None,
                    help="Meteoric rise rule: close >= (1+pct/100) × min(Low over prior N bars); default 300 (not an entry gate)")
    ap.add_argument("--meteoric-rise-lookback", type=int, default=None,
                    help="Meteoric rise: N trading bars for min-low window (default 100)")
    ap.add_argument("--meteoric-fall-pct", type=float, default=None,
                    help="Meteoric fall rule: close <= (1-pct/100) × max(High over prior Y bars); default 50 (not an entry gate)")
    ap.add_argument("--meteoric-fall-lookback", type=int, default=None,
                    help="Meteoric fall: Y trading bars for max-high window (default 100)")
    ap.add_argument("--entry-close-min-range-position", type=float, default=None,
                    help="After close>open: require (close-low)/(high-low) >= this (sheet C27 default 1e-7; 0.5 = upper half; 0 = off)")
    ap.add_argument("--displacement-filter", action="store_true",
                    help="Enable rolling average displacement filter: require |Close/RollingAvg100 - 1| >= threshold (avoid stuck/equilibrium)")
    ap.add_argument("--displacement-rolling-bars", type=int, default=100,
                    help="Rolling window for displacement average (default 100)")
    ap.add_argument("--displacement-threshold", type=float, default=0.10,
                    help="Min displacement as decimal, e.g. 0.10 = 10%% (default 0.10)")
    ap.add_argument("--sheet-maturity-lag", type=int, default=None,
                    help="Sheet C10 lag for matured zone (BF=INDEX(AF,...)); 0=config default inherits strong_post_pivot_bars")
    ap.add_argument(
        "--mts-sheet-parity",
        "--sheet-parity",
        action="store_true",
        dest="mts_sheet_parity",
        help="MTS/STONK_DATA sheet preset: mts_mode, full-history DE/DF/DG, BI gates, BW growth OK",
    )
    ap.add_argument(
        "--sheet-di-breakout-price",
        type=str,
        default=None,
        choices=["close", "high"],
        help="BM / all-zones DI: compare prior vs current Close (sheet parity, default) or High (legacy) to BI[j]",
    )
    ap.add_argument(
        "--entry-retest-bullish-growth-only",
        action="store_true",
        help="Long entry: skip TKL and consolidation blocker (retest + other configured gates unchanged)",
    )
    ap.add_argument(
        "--sheet-dw-countif-prior-day",
        action="store_true",
        help="BY retest gate (opt-in): expand simulated BY dates with the next session after each retest (sets sheet_dw_countif_include_prior_bar_date=True). Default config is strict retest date only.",
    )
    ap.add_argument(
        "--no-sheet-dw-countif-prior-day",
        action="store_true",
        help="BY retest gate: strict eval date in raw retest set only (force sheet_dw_countif_include_prior_bar_date=False; overrides -v)",
    )
    ap.add_argument(
        "--retest-multi-zone-pick",
        type=str,
        default="all",
        choices=["all", "lowest", "highest"],
        help="When several DI zones first-retest the same day: all=pending per zone (default); "
        "lowest=entry uses band with smallest zone_lower; highest=largest zone_upper (-v retest_multi_zone_pick=… overrides)",
    )
    ap.add_argument("--set", "-v", dest="config_set", action="append", default=[], metavar="KEY=VALUE",
                    help="Override config: -v touch_threshold=2 -v min_touch_count=5 (multiple allowed)")
    ap.add_argument(
        "--per-symbol-settings",
        default="",
        help="Per-symbol optimized params JSON (default: PER_SYMBOL_SETTINGS env or "
        "stock_analysis/Per_Symbol_Optimized_Settings_Latest.json)",
    )
    args = ap.parse_args()

    symbol_list = _symbol_list_from_arg(getattr(args, "symbol", "") or "")

    # Full-universe default: parallelize (was sequential when default was 0, which made large runs very slow).
    _w = int(getattr(args, "workers", -1))
    if _w < 0:
        _w = 0 if len(symbol_list) == 1 else min(8, (os.cpu_count() or 4))
    args.workers = _w

    # Enable debug logging if requested (--debug-entry wins over --debug-symbol if both set)
    if getattr(args, "debug_entry", None):
        de_sym, de_date = str(args.debug_entry[0]).strip(), str(args.debug_entry[1]).strip()
        set_debug_target(de_sym.upper(), de_date)
        print(f"[DEBUG] --debug-entry {de_sym.upper()} / {de_date!r} (same as --debug-symbol + --debug-date)")
    elif args.debug_symbol:
        set_debug_target(args.debug_symbol.upper(), args.debug_date)
        print(f"[DEBUG] Debug logging enabled for {args.debug_symbol.upper()}" + 
              (f" around {args.debug_date}" if args.debug_date else ""))
    if getattr(args, "trace_date", None):
        trace_sym = args.trace_symbol or (symbol_list[0] if len(symbol_list) == 1 else None)
        set_trace_target(trace_sym, args.trace_date)
        print(f"[TRACE] Enabled for dates={list(args.trace_date)}" + (f", symbol={trace_sym.upper()}" if trace_sym else ""))
    if getattr(args, "trace_indicator_buy", False):
        print("[IND-GATE] trace_indicator_buy enabled ([IND-GATE] logs when indicator_buy is only/both)")

    script_dir = Path(__file__).parent.resolve()
    repo_root = script_dir.parent
    data_dir = Path(args.data_dir)
    if not data_dir.is_absolute():
        data_dir = repo_root / data_dir
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = repo_root / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    use_duckdb = bool(getattr(args, "use_duckdb", False))
    db_path = str(getattr(args, "db_path", "") or "")
    db_table = str(getattr(args, "db_table", "prices") or "prices")
    if use_duckdb and _db_load_symbol_df is None:
        print("[BRT] --use-duckdb requested, but DuckDB loader is unavailable.", file=sys.stderr)
        _maybe_play_completion_sound(args.play_sound)
        return 1
    if use_duckdb and _db_resolve_path is not None:
        try:
            db_path = str(_db_resolve_path(data_dir, db_path, db_table))
        except (OSError, RuntimeError) as e:
            print(f"[BRT] DuckDB: {e}", file=sys.stderr)
            _maybe_play_completion_sound(args.play_sound)
            return 1
        print(f"[BRT] DuckDB: {db_path} (table={db_table})")

    ts = datetime.now().strftime("%y%m%d%H%M%S")
    _use_instrument = BRTPipelineInstrument is not None and not getattr(args, "no_instrument", False)
    pipeline: Optional[Any] = None
    if _use_instrument:
        _inst_db_raw = (getattr(args, "instrument_db", "") or "").strip()
        _inst_db = Path(_inst_db_raw) if _inst_db_raw else default_instrument_db_path(output_dir)
        pipeline = BRTPipelineInstrument(enabled=True, output_dir=output_dir, db_path=_inst_db)
    cfg_kw: dict = {"exit_at_close_when_stopped": args.exit_at_close_when_stopped}
    if getattr(args, "mts_sheet_parity", False):
        cfg_kw.update(mts_sheet_parity_overrides())
        print("[BRT] MTS sheet parity preset (mts_mode); override any field with -v")
    cfg_kw["trace_indicator_buy"] = bool(getattr(args, "trace_indicator_buy", False))
    if getattr(args, "no_indicator_cache", False):
        cfg_kw["indicator_cache"] = False
    cfg_kw["initial_capital"] = float(args.initial_capital)
    cfg_kw["aggressive"] = bool(args.aggressive)
    cfg_kw["aggressive_margin_interest"] = float(args.aggressive_margin_interest)
    cfg_kw["aggressive_max_multiple"] = float(args.aggressive_max_multiple)
    cfg_kw["aggressive_avg_positions"] = float(args.aggressive_avg_positions)
    cfg_kw["aggressive_sizing_equity_cap"] = float(args.aggressive_sizing_equity_cap)
    cfg_kw["margin_utilization"] = float(getattr(args, "margin_utilization", 0.6) or 0.6)
    cfg_kw["symbol_reentry_cooldown_days"] = int(getattr(args, "symbol_reentry_cooldown_days", 0) or 0)
    if getattr(args, "relative_strength", False):
        cfg_kw["relative_strength_enabled"] = True
    if args.stop_pct_multiplier:
        cfg_kw["stop_pct_is_multiplier"] = True
    if args.band_pct is not None:
        cfg_kw["band_pct"] = args.band_pct
    if getattr(args, "band_pct_atr", None) is not None:
        cfg_kw["band_pct_atr"] = float(args.band_pct_atr)
    if getattr(args, "strong_pre_pivot_pct_atr", None) is not None:
        cfg_kw["strong_pre_pivot_pct_atr"] = float(args.strong_pre_pivot_pct_atr)
    if getattr(args, "strong_post_pivot_pct_atr", None) is not None:
        cfg_kw["strong_post_pivot_pct_atr"] = float(args.strong_post_pivot_pct_atr)
    if args.close_above_window is not None:
        cfg_kw["close_above_window"] = args.close_above_window
    if args.level_acceptance:
        parts = args.level_acceptance.split("/")
        if len(parts) == 2:
            cfg_kw["level_acceptance_required"] = int(parts[0])
            cfg_kw["level_acceptance_window"] = int(parts[1])
    if getattr(args, "level_acceptance_anchor_mode", None):
        cfg_kw["level_acceptance_anchor_mode"] = str(args.level_acceptance_anchor_mode)
    if getattr(args, "level_acceptance_anchor_window", None) is not None:
        cfg_kw["level_acceptance_anchor_window"] = int(args.level_acceptance_anchor_window)
    if getattr(args, "no_support_test", False):
        cfg_kw["support_test_enabled"] = False
    if getattr(args, "breakout_bars", None) is not None:
        cfg_kw["breakout_bars"] = int(args.breakout_bars)
    if args.tight_range_off:
        cfg_kw["tight_range_enabled"] = False
    if args.tight_range_threshold is not None:
        cfg_kw["tight_range_threshold_pct"] = args.tight_range_threshold
    if args.tight_range_lookback is not None:
        cfg_kw["tight_range_lookback"] = args.tight_range_lookback
    if args.tradeable_key_level_off:
        cfg_kw["tradeable_key_level_enabled"] = False
    if args.lookback_short is not None:
        cfg_kw["lookback_short"] = args.lookback_short
    if getattr(args, "consolidation_blocker_off", False):
        cfg_kw["consolidation_blocker_enabled"] = False
    if args.no_growth_filter:
        cfg_kw["growth_filter_enabled"] = False
    if getattr(args, "no_require_close_gt_open", False):
        cfg_kw["require_close_gt_open"] = False
    if args.growth_filter:
        cfg_kw["growth_filter_enabled"] = True
    cfg_kw["growth_bars"] = args.growth_bars
    if getattr(args, "growth_history_slack_bars", None) is not None:
        cfg_kw["growth_history_slack_bars"] = int(args.growth_history_slack_bars)
    if getattr(args, "meteoric_rise_pct", None) is not None:
        cfg_kw["meteoric_rise_pct"] = float(args.meteoric_rise_pct)
    if getattr(args, "meteoric_rise_lookback", None) is not None:
        cfg_kw["meteoric_rise_lookback"] = int(args.meteoric_rise_lookback)
    if getattr(args, "meteoric_fall_pct", None) is not None:
        cfg_kw["meteoric_fall_pct"] = float(args.meteoric_fall_pct)
    if getattr(args, "meteoric_fall_lookback", None) is not None:
        cfg_kw["meteoric_fall_lookback"] = int(args.meteoric_fall_lookback)
    if args.entry_close_min_range_position is not None:
        cfg_kw["entry_close_min_range_position"] = args.entry_close_min_range_position
    if args.displacement_filter:
        cfg_kw["displacement_filter_enabled"] = True
        cfg_kw["displacement_rolling_bars"] = args.displacement_rolling_bars
        cfg_kw["displacement_threshold_pct"] = args.displacement_threshold
    if getattr(args, "no_equity_metrics", False):
        cfg_kw["compute_equity_metrics"] = False
    if getattr(args, "equity_fast_aggressive", False):
        cfg_kw["equity_fast_aggressive"] = True
    if getattr(args, "sheet_maturity_lag", None) is not None:
        cfg_kw["sheet_maturity_lag_bars"] = int(args.sheet_maturity_lag)
    if getattr(args, "sheet_di_breakout_price", None) is not None:
        cfg_kw["sheet_di_breakout_price"] = str(args.sheet_di_breakout_price)
    if getattr(args, "entry_retest_bullish_growth_only", False):
        cfg_kw["entry_retest_bullish_growth_only"] = True
    if getattr(args, "sheet_dw_countif_prior_day", False):
        cfg_kw["sheet_dw_countif_include_prior_bar_date"] = True
    if getattr(args, "no_sheet_dw_countif_prior_day", False):
        cfg_kw["sheet_dw_countif_include_prior_bar_date"] = False
    if getattr(args, "retest_multi_zone_pick", None) is not None:
        cfg_kw["retest_multi_zone_pick"] = str(args.retest_multi_zone_pick).strip().lower()
    # Apply -v / --set KEY=VALUE overrides
    set_args = getattr(args, "config_set", None) or getattr(args, "set", None)
    if set_args is None:
        set_args = []
    set_args = list(set_args) if set_args else []
    if set_args:
        print(f"[BRT] Config overrides received: {set_args}")
    valid_fields = set(BRTConfig.__dataclass_fields__)
    explicit_v_keys: list[str] = []
    try:
        from rocket_rl_config import apply_rl_defaults_to_brt_kw, normalize_rl_v_key
    except ImportError:
        from stock_analysis.rocket_rl_config import apply_rl_defaults_to_brt_kw, normalize_rl_v_key  # type: ignore
    for s in set_args:
        key, _, val_str = s.partition("=")
        key = normalize_rl_v_key(key.strip())
        explicit_v_keys.append(key)
        val_str = val_str.strip()
        if not key:
            continue
        if key == "atr_increment":
            print(
                "[BRT] Config key 'atr_increment' is deprecated; use 'trailing_stop_increment' (same meaning).",
                file=sys.stderr,
            )
            key = "trailing_stop_increment"
        if key == "min_atr_pct_at_entry":
            print(
                "[BRT] Config key 'min_atr_pct_at_entry' is deprecated; use 'min_atr_pct_at_trigger'.",
                file=sys.stderr,
            )
            key = "min_atr_pct_at_trigger"
        if key == "max_atr_pct_at_entry":
            print(
                "[BRT] Config key 'max_atr_pct_at_entry' is deprecated; use 'max_atr_pct_at_trigger'.",
                file=sys.stderr,
            )
            key = "max_atr_pct_at_trigger"
        if key == "mandatory_ind_states_enabled":
            print(
                "[BRT] Config key 'mandatory_ind_states_enabled' is deprecated; "
                "use mandatory_ind_states_path=<filename> (empty or omit = off).",
                file=sys.stderr,
            )
            if val_str.lower() in ("true", "1", "yes", "on"):
                if "mandatory_ind_states_path" not in cfg_kw:
                    cfg_kw["mandatory_ind_states_path"] = "mandatory_ind_states.json"
            else:
                cfg_kw["mandatory_ind_states_path"] = ""
            continue
        if key not in valid_fields:
            print(f"[BRT] Unknown config key in -v {key}=... (skipped)", file=sys.stderr)
            continue
        # Use get_type_hints: with "from __future__ annotations", __annotations__ are strings; get_type_hints resolves them
        hints = get_type_hints(BRTConfig)
        ann = hints.get(key, str)
        args_ann = get_args(ann) if get_origin(ann) is not None else ()
        is_optional = type(None) in args_ann
        if is_optional:
            ann = next((a for a in args_ann if a is not type(None)), ann)
        try:
            if ann is bool:
                cfg_kw[key] = val_str.lower() in ("true", "1", "yes", "on")
            elif ann is int:
                cfg_kw[key] = int(val_str)
            elif ann is float:
                cfg_kw[key] = float(val_str)
            elif ann is str:
                cfg_kw[key] = val_str
            elif is_optional:
                if val_str.lower() in ("none", "null", ""):
                    cfg_kw[key] = None
                else:
                    cfg_kw[key] = int(val_str)
        except ValueError as e:
            print(f"[BRT] Invalid value for -v {key}={val_str!r}: {e} (skipped)", file=sys.stderr)
    # Build from defaults first so -v overrides apply; cfg_kw may omit many fields
    defaults = asdict(BRTConfig())
    defaults.update(cfg_kw)
    defaults = apply_rl_defaults_to_brt_kw(defaults, explicit_v_keys)
    cfg = BRTConfig(**defaults)
    _yh_mm = _effective_yh_memory_mode(cfg, cfg_kw)
    if _yh_mm != _normalize_yh_memory_mode(getattr(cfg, "yh_memory_mode", "sheet")):
        cfg = replace(cfg, yh_memory_mode=_yh_mm)
    if getattr(args, "no_sheet_dw_countif_prior_day", False):
        cfg = replace(cfg, sheet_dw_countif_include_prior_bar_date=False)
    _rzp = str(getattr(cfg, "retest_multi_zone_pick", "all") or "all").strip().lower()
    if _rzp not in ("all", "lowest", "highest"):
        print(
            f"[BRT] Invalid retest_multi_zone_pick={_rzp!r}; using 'all'. Expected all|lowest|highest.",
            file=sys.stderr,
        )
        cfg = replace(cfg, retest_multi_zone_pick="all")
    _tt = _normalize_transaction_type(getattr(cfg, "transaction_type", "long"))
    _et = _normalize_entry_type(getattr(cfg, "entry_type", "long"))
    _zrm = _normalize_zone_role_mode(getattr(cfg, "zone_role_mode", "dynamic"))
    _zro = _normalize_zone_role_override(getattr(cfg, "zone_role_override", ""))
    if (
        _tt != getattr(cfg, "transaction_type", "long")
        or _et != getattr(cfg, "entry_type", "long")
        or _zrm != getattr(cfg, "zone_role_mode", "dynamic")
        or _zro != getattr(cfg, "zone_role_override", "")
    ):
        cfg = replace(cfg, transaction_type=_tt, entry_type=_et, zone_role_mode=_zrm, zone_role_override=_zro)
    _ibuy_n = _normalize_indicator_buy(getattr(cfg, "indicator_buy", "off"))
    _idiff_n = int(getattr(cfg, "indicator_diff", 10) or 10)
    _asell_n = _normalize_aggressive_sell(getattr(cfg, "aggressive_sell", "false"))
    if _ibuy_n != getattr(cfg, "indicator_buy", "off") or _idiff_n != int(getattr(cfg, "indicator_diff", 10) or 10):
        cfg = replace(cfg, indicator_buy=_ibuy_n, indicator_diff=_idiff_n)
    _rl_mode_n = _normalize_rl_mode(getattr(cfg, "rl_mode", "false"))
    if getattr(cfg, "rl_mode", "false") != _rl_mode_n:
        cfg = replace(cfg, rl_mode=_rl_mode_n)
    if _asell_n != getattr(cfg, "aggressive_sell", "false"):
        cfg = replace(cfg, aggressive_sell=_asell_n)
    cfg = _apply_indicator_sides_to_cfg(cfg, _ibuy_n)
    _uses_indicators = (
        bool(getattr(cfg, "use_indicators", False))
        or _ibuy_n in ("only", "both")
        or getattr(cfg, "max_ind_entry_neutral_n", None) is not None
        or getattr(cfg, "min_ind_entry_bull_n", None) is not None
        or _cfg_min_ind_score_filter_active(cfg)
    )
    if _uses_indicators and bool(getattr(cfg, "indicator_cache", True)):
        try:
            from brt_entry_indicators import resolve_indicator_cache_dir, reset_indicator_cache_stats
        except ImportError:
            from stock_analysis.brt_entry_indicators import resolve_indicator_cache_dir, reset_indicator_cache_stats
        _icd_arg = str(getattr(args, "indicator_cache_dir", "") or getattr(cfg, "indicator_cache_dir", "") or "").strip()
        _icd_path = resolve_indicator_cache_dir(
            _icd_arg or None,
            repo_root=repo_root,
            data_dir=data_dir,
        )
        cfg = replace(cfg, indicator_cache=True, indicator_cache_dir=str(_icd_path))
        reset_indicator_cache_stats()
        print(f"[BRT] Indicator cache: {_icd_path}")
    elif _uses_indicators:
        print("[BRT] Indicator cache disabled (--no-indicator-cache or indicator_cache=false)")
    _min_iscore = _cfg_min_ind_score(cfg)
    if (
        _uses_indicators
        or _ibuy_n in ("only", "both")
        or _min_iscore > 0.0
        or bool(getattr(cfg, "use_ind_score", True))
    ):
        cfg = _snapshot_ind_score_weights_for_run(cfg, ts)
        _configure_ind_score_from_cfg(cfg)
        if not bool(getattr(cfg, "use_ind_score", True)):
            print("[BRT] IND_SCORE column disabled (use_ind_score=false)")
    if _min_iscore > 0.0:
        print(f"[BRT] min_ind_score entry filter: IND_SCORE >= {_min_iscore:.2f} at trigger bar close")
    _mand_raw = _cfg_mandatory_ind_states_path_raw(cfg)
    if _mand_raw:
        _mand_rules = _load_mandatory_ind_states_rules(cfg)
        _mand_resolved = _resolve_mandatory_ind_states_file(cfg)
        _mand_label = (
            str(_mand_resolved.name)
            if _mand_resolved is not None
            else _mand_raw
        )
        if not _mand_rules:
            print(
                f"[BRT] mandatory_ind_states_path={_mand_raw!r} but no rules loaded "
                f"(file not found or empty rules) — gate inactive",
                file=sys.stderr,
            )
        else:
            _mand_where = (
                f"{_mand_label} ({_mand_resolved})"
                if _mand_resolved is not None and _mand_resolved.name != _mand_raw
                else _mand_label
            )
            print(
                f"[BRT] mandatory_ind_states: {len(_mand_rules)} rule(s) from {_mand_where} "
                f"({', '.join(f'{k}={v}' for k, v in list(_mand_rules.items())[:4])}"
                f"{'...' if len(_mand_rules) > 4 else ''})"
            )
    if bool(getattr(cfg, "use_sma50", False)):
        print(
            "[BRT] use_sma50: percent target anchored to SMA(50) at entry "
            f"(long: SMA50×target_pct={float(cfg.target_pct):.4f}; "
            "falls back to entry×target_pct if SMA unavailable)"
        )
    if _tt in ("long", "short") and _et != _tt:
        # Keep explicit entry_type in sync for single-sided runs.
        cfg = replace(cfg, entry_type=_tt)
    if _tt == "both":
        print(
            "[BRT] transaction_type=both: each symbol runs independent LONG and SHORT streams; closed trades and outputs are merged.",
        )
    if _zrm == "by_origin":
        print(
            "[BRT] zone_role_mode=by_origin: long entries use pivot-high (resistance) zones; "
            "short entries use pivot-low (support) zones unless zone_role_override forces support|resistance|both.",
        )
    if getattr(cfg, "relative_strength_enabled", False):
        print(
            "[BRT] Relative strength mode: entries when stock beats SPY on 252/504/756-bar total returns (all strict); "
            "requires SPY.csv in the data directory."
        )
    elif _rl_mode_active(getattr(cfg, "rl_mode", "false")):
        print(
            "[BRT] Rocket Launcher mode (rl_mode=true): 50-SMA dip-buy — "
            "Python engine (stock_analysis/rocket_rl.py); outputs RL_Closed_/RL_Open_. "
            "All portfolio_audit.awk RL_* params are -v overridable (see rocket_rl_config.py)."
        )
    elif _indicator_only_mode(cfg):
        print(
            f"[BRT] Indicator-only mode (indicator_buy=only): enter when trade-aligned IND_DIFF >= "
            f"{int(getattr(cfg, 'indicator_diff', 10) or 10)} at trigger bar close — no zone maturity, retest, or relative strength."
        )
    elif bool(getattr(cfg, "vec_zones", False)) and not bool(getattr(cfg, "brt_zones", False)) and not bool(getattr(cfg, "yh_zones", True)):
        print(
            f"[BRT] VEC zone mode (vec_zones-only): outputs use VEC_ prefix; "
            f"vec_vp_lookback={int(getattr(cfg, 'vec_vp_lookback', 60) or 60)}, "
            f"vec_prior_bars={int(getattr(cfg, 'vec_prior_bars', 5) or 5)}, "
            f"vec_confluence_pct={float(getattr(cfg, 'vec_confluence_pct', 0.0075) or 0.0075):.4f}, "
            f"vec_move_away_pct={float(getattr(cfg, 'vec_move_away_pct', 0.02) or 0.02):.3f}."
        )
    elif bool(getattr(cfg, "yh_zones", True)) and not bool(getattr(cfg, "brt_zones", False)):
        print(
            f"[BRT] Year-High zone mode (yh_zones-only): outputs use YH_ prefix; "
            f"yh_lookback={int(getattr(cfg, 'yh_lookback', 252) or 252)}, "
            f"yh_move_away_pct={float(getattr(cfg, 'yh_move_away_pct', 0.03) or 0.03):.3f}, "
            f"yh_memory_mode={_effective_yh_memory_mode(cfg)!r}."
        )
    if cfg.stop_pct == 0 and cfg.target_pct == 0:
        print(f"[BRT] ATR stop/target: atr_target={cfg.atr_target} atr_stop={cfg.atr_stop}")
    _file_prefix = _output_file_prefix(cfg)
    if (
        float(getattr(cfg, "atr_target", 0.0) or 0.0) > 0
        and float(getattr(cfg, "atr_stop", 0.0) or 0.0) <= 0
        and float(getattr(cfg, "stop_pct", 0.0) or 0.0) <= 0
    ):
        print(
            "[BRT] WARNING: atr_target>0 but atr_stop and stop_pct are both 0. "
            "A literal stop of 0 would disable stop-loss (only ATR_TARGET exits). "
            "Backtest now uses default stop (low×0.934 or low×(1-0.066)); set atr_stop or stop_pct to match your sheet.",
            file=sys.stderr,
        )
    if float(getattr(cfg, "trailing_stop_increment", 0.0) or 0.0) > 0:
        print(f"[BRT] Trailing stop: trailing_stop_increment={cfg.trailing_stop_increment}")
    _ad = int(getattr(cfg, "atr_days", 0) or 0)
    _ap = float(getattr(cfg, "atr_progress", 0.0) or 0.0)
    if _ad > 0:
        if _ap > 0:
            print(f"[BRT] ATR schedule exit (inaction): atr_progress={cfg.atr_progress} atr_days={cfg.atr_days}")
        else:
            print(f"[BRT] ATR schedule exit (timed only): atr_progress=0 atr_days={cfg.atr_days}")
    if getattr(args, "cprofile", False):
        if len(symbol_list) != 1:
            print("[BRT] --cprofile requires exactly one ticker with -s/--symbol (no comma list).", file=sys.stderr)
            _maybe_play_completion_sound(args.play_sound)
            return 1
        if getattr(args, "workers", 0) and args.workers > 0:
            print("[BRT] --cprofile: ignoring -w (profiling uses sequential single-symbol path).", file=sys.stderr)
            args.workers = 0

    if getattr(args, "cprofile_sheet_magic_touch", False):
        if len(symbol_list) != 1:
            print("[BRT] --cprofile-sheet-magic-touch requires exactly one ticker with -s/--symbol.", file=sys.stderr)
            _maybe_play_completion_sound(args.play_sound)
            return 1
        if getattr(args, "workers", 0) and args.workers > 0:
            print("[BRT] --cprofile-sheet-magic-touch: ignoring -w (sequential profiling).", file=sys.stderr)
            args.workers = 0
    if getattr(args, "cprofile_pending_sheet_prep", False):
        if len(symbol_list) != 1:
            print("[BRT] --cprofile-pending-sheet-prep requires exactly one ticker with -s/--symbol.", file=sys.stderr)
            _maybe_play_completion_sound(args.play_sound)
            return 1
        if getattr(args, "workers", 0) and args.workers > 0:
            print("[BRT] --cprofile-pending-sheet-prep: ignoring -w (sequential profiling).", file=sys.stderr)
            args.workers = 0

    _collect_symbol_timings = bool(args.profile or pipeline is not None)
    _profile_backtest_workers = _collect_symbol_timings

    post_only = bool(getattr(args, "post_only", False))
    if post_only and (
        getattr(args, "cprofile", False)
        or getattr(args, "cprofile_sheet_magic_touch", False)
        or getattr(args, "cprofile_pending_sheet_prep", False)
    ):
        print("[BRT] --post-only cannot be used with --cprofile* flags.", file=sys.stderr)
        _maybe_play_completion_sound(args.play_sound)
        return 1

    all_closed: list[BRTTrade] = []
    all_open: list[BRTTrade] = []
    all_scanner: list[dict] = []
    all_watchlist: list[dict] = []
    all_short_candidates: list[dict] = []
    all_would_have: list[dict] = []
    all_breakout_retest: list[dict] = []
    all_indicators_while_held: list[dict] = []
    profile_symbol_rows: list[dict] = []
    profile_block_rows: list[dict] = []
    all_pivot_rows: list[tuple[str, str, str, float, str]] = []
    skip_backtest = post_only
    n_total = 0
    ticker_list: list[str] = []
    _duckdb_parallel_symbol_list: Optional[list[str]] = None
    elapsed = 0.0

    if post_only:
        ck_path = _resolve_brt_checkpoint_path(
            output_dir,
            str(getattr(args, "from_checkpoint", "") or ""),
            str(getattr(args, "from_run", "") or ""),
        )
        if ck_path is None or not ck_path.is_file():
            print(
                "[BRT] --post-only: no checkpoint found. Run a full backtest first (writes "
                "BRT_Checkpoint_<ts>.pkl), or pass --from-run TS / --from-checkpoint PATH.",
                file=sys.stderr,
            )
            _maybe_play_completion_sound(args.play_sound)
            return 1
        try:
            ck = _load_brt_checkpoint(ck_path)
        except (OSError, pickle.UnpicklingError, ValueError) as e:
            print(f"[BRT] --post-only: failed to load {ck_path}: {e}", file=sys.stderr)
            _maybe_play_completion_sound(args.play_sound)
            return 1
        ck_ts = str(ck.get("ts") or "").strip()
        if ck_ts:
            ts = ck_ts
        all_closed = list(ck.get("all_closed") or [])
        all_open = list(ck.get("all_open") or [])
        all_scanner = list(ck.get("all_scanner") or [])
        all_watchlist = list(ck.get("all_watchlist") or [])
        all_short_candidates = list(ck.get("all_short_candidates") or [])
        all_would_have = list(ck.get("all_would_have") or [])
        all_breakout_retest = list(ck.get("all_breakout_retest") or [])
        all_indicators_while_held = list(ck.get("all_indicators_while_held") or [])
        all_pivot_rows = list(ck.get("all_pivot_rows") or [])
        profile_symbol_rows = list(ck.get("profile_symbol_rows") or [])
        profile_block_rows = list(ck.get("profile_block_rows") or [])
        ref_stats = ck.get("ref_stats")
        if ref_stats is None:
            ref_stats = _load_reference_stats(output_dir)
        n_total = int(ck.get("n_symbols") or 0)
        ticker_list = list(ck.get("ticker_list") or [])
        trade_syms = _brt_trade_symbols(all_closed, all_open)
        _extra_load: set[str] = set()
        if cfg.compute_equity_metrics and not getattr(args, "no_equity_metrics", False):
            _extra_load.add("SPY")
        _t_load = time.time()
        tickers = _load_tickers_for_symbols(
            trade_syms,
            data_dir,
            use_duckdb=use_duckdb,
            db_path=db_path,
            db_table=db_table,
            pipeline=pipeline,
            extra_symbols=_extra_load,
        )
        if args.profile:
            print(
                f"[PROFILE] load_tickers (post-only): {time.time() - _t_load:.2f}s "
                f"({len(tickers)} symbols for {len(trade_syms)} trade tickers)"
            )
        print(
            f"[BRT] --post-only: loaded {ck_path.name} "
            f"({len(all_closed)} closed, {len(all_open)} open, ts={ts}); backtest skipped.",
            flush=True,
        )
    elif len(symbol_list) == 1:
        # Single symbol mode + chart
        sym = symbol_list[0]
        _t_load = time.time()
        if pipeline is not None:
            with pipeline.phase("load_tickers"):
                one_df = _load_symbol_data(sym, data_dir, use_duckdb=use_duckdb, db_path=db_path, db_table=db_table)
        else:
            one_df = _load_symbol_data(sym, data_dir, use_duckdb=use_duckdb, db_path=db_path, db_table=db_table)
        if one_df is None or one_df.empty:
            src = db_path if use_duckdb else str(data_dir / f"{sym}.csv")
            print(f"File not found: {src}", file=sys.stderr)
            _maybe_play_completion_sound(args.play_sound)
            return 1
        tickers = {sym: one_df}
        if args.profile:
            print(f"[PROFILE] load_tickers: {time.time() - _t_load:.2f}s (1 symbol)")
    elif len(symbol_list) > 1:
        _t_load = time.time()
        tickers = {}
        missing_syms: list[str] = []
        _load_ctx = pipeline.phase("load_tickers") if pipeline is not None else None
        if _load_ctx is not None:
            _load_ctx.__enter__()
        try:
            for sym in symbol_list:
                df_sym = _load_symbol_data(sym, data_dir, use_duckdb=use_duckdb, db_path=db_path, db_table=db_table)
                if df_sym is not None and not df_sym.empty:
                    tickers[sym] = df_sym
                else:
                    missing_syms.append(sym)
        finally:
            if _load_ctx is not None:
                _load_ctx.__exit__(None, None, None)
        if missing_syms:
            print(
                f"[BRT] Warning: missing data for {len(missing_syms)} requested symbol(s) (skipped): "
                f"{', '.join(missing_syms)}",
                file=sys.stderr,
            )
        if not tickers:
            print("[BRT] No data found for any -s/--symbol tickers.", file=sys.stderr)
            _maybe_play_completion_sound(args.play_sound)
            return 1
        if args.profile:
            print(
                f"[PROFILE] load_tickers: {time.time() - _t_load:.2f}s "
                f"({len(tickers)}/{len(symbol_list)} symbols loaded)"
            )
        print(
            f"[BRT] Whitelist mode: backtesting {len(tickers)} symbol(s) from -s "
            f"(requested {len(symbol_list)})"
        )
    else:
        _t_load = time.time()
        n_workers_plan = _resolve_brt_worker_count(int(getattr(args, "workers", -1)))
        _defer_parent_duckdb_load = (
            use_duckdb
            and n_workers_plan > 0
            and not symbol_list
            and not post_only
        )
        if _defer_parent_duckdb_load:
            if pipeline is not None:
                with pipeline.phase("load_tickers"):
                    _duckdb_parallel_symbol_list = _list_duckdb_backtest_symbols(
                        cfg, db_path=db_path, db_table=db_table, data_dir=data_dir
                    )
            else:
                _duckdb_parallel_symbol_list = _list_duckdb_backtest_symbols(
                    cfg, db_path=db_path, db_table=db_table, data_dir=data_dir
                )
            tickers = {}
            if args.profile:
                print(
                    f"[PROFILE] load_tickers: {time.time() - _t_load:.2f}s "
                    f"({len(_duckdb_parallel_symbol_list)} symbols listed; OHLCV loaded in workers)"
                )
            print(
                f"[BRT] DuckDB parallel: symbol list only in parent ({len(_duckdb_parallel_symbol_list)} symbols); "
                "workers load OHLCV per symbol.",
                flush=True,
            )
        else:
            if pipeline is not None:
                with pipeline.phase("load_tickers"):
                    tickers = load_all_tickers_source(
                        str(data_dir), use_duckdb=use_duckdb, db_path=db_path, db_table=db_table
                    )
            else:
                tickers = load_all_tickers_source(
                    str(data_dir), use_duckdb=use_duckdb, db_path=db_path, db_table=db_table
                )
            if args.profile:
                print(f"[PROFILE] load_tickers: {time.time() - _t_load:.2f}s ({len(tickers)} symbols)")

    n_workers = _resolve_brt_worker_count(int(getattr(args, "workers", -1)))

    need_post_filter = (
        False
        if post_only
        else cfg.realtime_filter_enabled and getattr(cfg, "realtime_filter_use_zscore", True)
    )
    if post_only and pipeline is not None:
        pipeline.set_meta(
            ts=ts,
            n_symbols=n_total,
            workers=n_workers,
            use_indicators=bool(getattr(cfg, "use_indicators", False)),
            indicator_buy=str(getattr(cfg, "indicator_buy", "off")),
            post_only=True,
        )
        pipeline.configure_backtest(0)
        _will_equity_po = (
            bool(cfg.compute_equity_metrics)
            and not getattr(args, "no_equity_metrics", False)
            and bool(all_closed)
            and bool(tickers)
            and _compute_equity_metrics is not None
        )
        _plan_post_pipeline_units(
            pipeline,
            all_closed,
            all_open,
            cfg,
            will_yfinance=bool(all_closed or all_open),
            will_equity=_will_equity_po,
            will_correlation=bool(all_closed),
            will_regression=not symbol_list and not getattr(args, "no_regression", False),
            will_zscore_filter=False,
        )
        if args.profile and profile_symbol_rows:
            print("[PROFILE] --- Post-processing ---")

    if not skip_backtest:
        t0 = time.time()
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] Starting backtest over "
        f"{len(_duckdb_parallel_symbol_list) if _duckdb_parallel_symbol_list is not None else len(tickers)} symbols"
        + (f" ({n_workers} workers)" if n_workers > 0 else "")
        + "...",
        flush=True,
    )
    if args.profile:
        print("[PROFILE] Timing enabled (use --profile on the command line to see this and other phase timings).")

    use_parallel = n_workers > 0 and len(symbol_list) != 1
    _print_zones = bool(getattr(args, "print_zones", False))
    if _print_zones and use_parallel:
        print(
            f"[BRT] --print-zones: each worker writes {{prefix}}_ZONES_<sym>_{ts}.csv under {output_dir}",
            flush=True,
        )
    if _duckdb_parallel_symbol_list is not None:
        ticker_list = list(_duckdb_parallel_symbol_list)
    else:
        ticker_list = sorted([s for s, df in tickers.items() if len(df) >= _min_bars_required_for_cfg(cfg)])
    n_total = len(ticker_list)

    if not skip_backtest and _rl_mode_active(getattr(cfg, "rl_mode", "false")):
        try:
            from rocket_rl import run_rl_from_brt_main
        except ImportError:
            from stock_analysis.rocket_rl import run_rl_from_brt_main  # type: ignore

        _rl_rc = run_rl_from_brt_main(
            cfg=cfg,
            tickers=tickers,
            ticker_list=ticker_list,
            output_dir=output_dir,
            ts=ts,
            data_dir=data_dir,
            load_symbol_fn=lambda sym, dd: _load_symbol_data(
                sym, dd, use_duckdb=use_duckdb, db_path=db_path, db_table=db_table
            ),
            workers=n_workers,
            drive_link=args.drive_link,
        )
        _maybe_play_completion_sound(args.play_sound)
        return _rl_rc

    if pipeline is not None:
        pipeline.set_meta(
            ts=ts,
            n_symbols=n_total,
            workers=n_workers,
            use_indicators=bool(getattr(cfg, "use_indicators", False)),
            indicator_buy=str(getattr(cfg, "indicator_buy", "off")),
        )
        pipeline.configure_backtest(n_total)
    all_pivot_rows: list[tuple[str, str, str, float, str]] = []

    # Z-score: one pass (accept all), then filter trade list by z-scored score before writing
    need_post_filter = cfg.realtime_filter_enabled and getattr(cfg, "realtime_filter_use_zscore", True)
    if need_post_filter:
        ref_stats = None
        run_cfg = replace(cfg, realtime_filter_threshold=-1e9)
        print("[BRT] Z-score: one pass (filter off), then filter trades by z-scored score before writing...")
    else:
        ref_stats = _load_reference_stats(output_dir)
        run_cfg = cfg
        if ref_stats:
            # Misleading if we said "realtime filter": z-scores are only used when realtime_filter_enabled is True
            # (entry gate or post-pass filter). Here ref_stats only enriches BRT_Closed optional columns.
            print(
                f"[BRT] BRT_ReferenceStats: {len(ref_stats)} variables loaded (audit columns only; "
                f"realtime_filter_enabled={cfg.realtime_filter_enabled})"
            )
    run_cfg = replace(run_cfg, emit_would_have=getattr(args, "emit_would_have", False))
    if getattr(args, "emit_would_have", False):
        print("[BRT] Emit would-have: recording maturities blocked by growth/tight_range/consolidation for BRT_WouldHave CSV")

    try:
        from per_symbol_settings import load_per_symbol_settings, resolve_settings_path
    except ImportError:
        from stock_analysis.per_symbol_settings import load_per_symbol_settings, resolve_settings_path  # type: ignore
    _ps_arg = str(getattr(args, "per_symbol_settings", "") or "").strip()
    _ps_path = resolve_settings_path(_ps_arg) if _ps_arg else resolve_settings_path()
    _per_symbol_settings = load_per_symbol_settings(_ps_path) if _ps_path else {}
    _run_system = "RL" if _rl_mode_active(getattr(run_cfg, "rl_mode", "false")) else "BRT"
    _brt_field_names = set(BRTConfig.__dataclass_fields__)
    if _per_symbol_settings:
        _n_ps = sum(
            1
            for e in _per_symbol_settings.values()
            if str(e.get("system", "")).strip().upper() in ("", _run_system)
        )
        print(
            f"[BRT] Per-symbol settings: {_ps_path} ({_n_ps} symbols for {_run_system})",
            flush=True,
        )

    # use_average_ind: replace the static indicator_diff gate with the per-date cross-sectional
    # average IND_DIFF across this run's universe. Delegates to the incremental, disk-cached
    # pre-pass (ind_avg_prepass) so only dates not already covered for this universe are computed.
    if bool(getattr(run_cfg, "use_average_ind", False)) and str(getattr(run_cfg, "indicator_buy", "off")).lower() in ("only", "both"):
        try:
            from ind_avg_prepass import get_or_build_avg_ind_diff_by_date
        except ImportError:
            from stock_analysis.ind_avg_prepass import get_or_build_avg_ind_diff_by_date  # type: ignore

        def _avg_load(sym: str):
            df = tickers.get(sym) if tickers else None
            if df is not None and len(df):
                return df
            return _load_symbol_data(sym, data_dir, use_duckdb=use_duckdb, db_path=db_path, db_table=db_table)

        _avg_side = "SHORT" if str(getattr(run_cfg, "indicator_sides", "")).strip().lower() == "short" else "LONG"
        print(
            f"[BRT] use_average_ind: building/loading per-date universe-average IND_DIFF "
            f"({len(ticker_list)} symbols, side={_avg_side})...",
            flush=True,
        )
        _avg_map = get_or_build_avg_ind_diff_by_date(
            ticker_list, _avg_load, cfg=run_cfg, side=_avg_side, verbose=True
        )
        run_cfg = replace(run_cfg, avg_ind_diff_by_date=_avg_map)

    if use_parallel:
        # Pre-build SPY IND_DIFF lookup in parent; workers receive it via pool initializer (no per-symbol rebuild).
        _t_spy_prewarm = time.time()
        _spy_prewarm_df = _load_benchmark_unified(
            use_duckdb=use_duckdb,
            db_path=db_path,
            db_table=db_table,
            data_dir=data_dir,
        )
        _spy_prewarm_lookup = None
        if _spy_prewarm_df is not None and not _spy_prewarm_df.empty:
            _spy_prewarm_lookup = _get_spy_ind_diff_lookup(_spy_prewarm_df, run_cfg)
            if _spy_prewarm_lookup is not None:
                print(
                    f"[BRT] SPY IND_DIFF precomputed ({len(_spy_prewarm_lookup.long_by_date)} days) "
                    f"in {time.time() - _t_spy_prewarm:.1f}s (workers reuse parent lookup)",
                    flush=True,
                )
        # Explicit dict for worker processes: ensure all BRTConfig fields are passed
        try:
            from per_symbol_settings import cfg_dict_with_overrides
        except ImportError:
            from stock_analysis.per_symbol_settings import cfg_dict_with_overrides  # type: ignore
        _zones_task_tail = (
            str(output_dir),
            ts,
            _file_prefix,
            _print_zones,
        ) if _print_zones else ()
        tasks = [
            (
                sym,
                str(data_dir / f"{sym}.csv"),
                cfg_dict_with_overrides(
                    run_cfg, sym, _per_symbol_settings, _run_system, field_names=_brt_field_names
                ),
                ref_stats,
                _profile_backtest_workers,
                use_duckdb,
                db_path,
                db_table,
                *_zones_task_tail,
            )
            for sym in ticker_list
        ]
        n_tasks = len(tasks)
        done = 0
        progress_t0 = time.perf_counter()
        print(
            f"[BRT] Spawning {n_workers} worker process(es) for {n_tasks} symbols — "
            "no progress line until the first symbol completes (often several minutes on a cold run).",
            flush=True,
        )
        with _make_brt_process_pool(
            n_workers,
            _spy_prewarm_lookup,
            use_duckdb=use_duckdb,
            db_path=db_path,
            db_table=db_table,
            data_dir=data_dir,
        ) as ex:
            for future in as_completed(ex.submit(_process_symbol, t) for t in tasks):
                # _process_symbol returns 13 values (watchlist, breakout_retest_rows, extra_open_trades, indicators_while_held, …).
                # Be tolerant of older 7-tuple / 9-tuple / 10-tuple / 12-tuple returns if a mixed/partial deploy ever happens.
                res = future.result()
                extra_open_parallel: list[BRTTrade] = []
                br_rows: list = []
                ind_wh_rows: list = []
                if len(res) >= 13:
                    sym, closed, open_trade, scanner, short_cands, pivot_rows, would_have, timing_row, block_counts, watchlist, br_rows, extra_open_parallel, ind_wh_rows = (
                        res[:13]
                    )
                    all_breakout_retest.extend(br_rows)
                    all_indicators_while_held.extend(ind_wh_rows)
                elif len(res) >= 12:
                    sym, closed, open_trade, scanner, short_cands, pivot_rows, would_have, timing_row, block_counts, watchlist, br_rows, extra_open_parallel = (
                        res[:12]
                    )
                    all_breakout_retest.extend(br_rows)
                elif len(res) == 11:
                    sym, closed, open_trade, scanner, short_cands, pivot_rows, would_have, timing_row, block_counts, watchlist, br_rows = res
                    all_breakout_retest.extend(br_rows)
                elif len(res) == 10:
                    sym, closed, open_trade, scanner, short_cands, pivot_rows, would_have, timing_row, block_counts, watchlist = res
                elif len(res) == 9:
                    sym, closed, open_trade, scanner, short_cands, pivot_rows, would_have, timing_row, block_counts = res
                    watchlist = []
                elif len(res) == 7:
                    sym, closed, open_trade, scanner, short_cands, pivot_rows, would_have = res
                    timing_row, block_counts, watchlist = {}, {}, []
                else:
                    raise ValueError(f"_process_symbol returned {len(res)} values (expected 7, 9, 10, 11, 12, or 13)")
                all_closed.extend(closed)
                if getattr(args, "emit_would_have", False):
                    all_would_have.extend(would_have)
                if open_trade:
                    all_open.append(open_trade)
                for _xo in extra_open_parallel or []:
                    all_open.append(_xo)
                all_scanner.extend(scanner)
                all_watchlist.extend(watchlist)
                all_short_candidates.extend(short_cands)
                all_pivot_rows.extend(pivot_rows)
                if _collect_symbol_timings and timing_row:
                    profile_symbol_rows.append(timing_row)
                    for reason, count in sorted(block_counts.items()):
                        profile_block_rows.append({"symbol": sym, "reason": reason, "count": int(count)})
                done += 1
                _backtest_progress(done, n_tasks, progress_t0, pipeline)
        if n_tasks > 1:
            print()
        if _normalize_indicator_buy(getattr(run_cfg, "indicator_buy", "off")) in ("only", "both"):
            print(
                "[BRT] Parallel run: suppressed per-symbol stderr for short-history indicator_buy precompute "
                "(keeps the [PROGRESS] line stable). Use -w 0 or -s SYMBOL to log each symbol.",
                flush=True,
            )
    else:
        # Load benchmark once for all symbols (sequential path)
        _t_bench = time.time()
        if pipeline is not None:
            with pipeline.phase("benchmark_load"):
                benchmark_df_seq = _load_benchmark_unified(
                    use_duckdb=use_duckdb,
                    db_path=db_path,
                    db_table=db_table,
                    data_dir=data_dir,
                )
        elif use_duckdb:
            benchmark_df_seq = _load_benchmark_unified(
                use_duckdb=True,
                db_path=db_path,
                db_table=db_table,
                data_dir=data_dir,
            )
        else:
            benchmark_df_seq = _load_benchmark_unified(
                use_duckdb=False,
                db_path="",
                db_table=db_table,
                data_dir=data_dir,
            )
        if args.profile:
            print(f"[PROFILE] benchmark_load (SPY): {time.time() - _t_bench:.2f}s")
        spy_lookup_seq = _resolve_spy_ind_diff_lookup(run_cfg, benchmark_df_seq)
        profile_beta_times = [] if args.profile else None
        _ind_wh_out_seq = all_indicators_while_held if _indicator_mode_active(run_cfg) else None
        progress_t0 = time.perf_counter()
        for idx, sym in enumerate(ticker_list, 1):
            _sym_t0 = time.time()
            df = tickers[sym]
            try:
                from per_symbol_settings import overrides_for_symbol
            except ImportError:
                from stock_analysis.per_symbol_settings import overrides_for_symbol  # type: ignore
            _sym_ov = (
                overrides_for_symbol(_per_symbol_settings, sym, _run_system, valid_fields=_brt_field_names)
                if _per_symbol_settings
                else {}
            )
            _sym_cfg = replace(run_cfg, **_sym_ov) if _sym_ov else run_cfg
            _alt_entry_run = _skip_brt_pivot_stack(_sym_cfg)
            if not _alt_entry_run:
                _t = time.time()
                pivot_high, pivot_low, ph_price, pl_price = compute_pivots(
                    df, _sym_cfg.pivot_k, _sym_cfg.pivot_d, _sym_cfg.pivot_disp, _sym_cfg.pivot_m, realtime_filter_enabled=_sym_cfg.realtime_filter_enabled
                )
                t_pivots = time.time() - _t
                _t = time.time()
                struct = compute_market_structure(df, pivot_high, pivot_low, ph_price, pl_price)
                t_structure = time.time() - _t
                _t = time.time()
                level3 = build_level3_for_cfg(
                    df, _sym_cfg, pivot_high, pivot_low, ph_price, pl_price, debug_symbol=sym,
                )
                t_touch = time.time() - _t
            else:
                t_pivots = 0.0
                t_structure = 0.0
                t_touch = 0.0
            zone_entries_debug: list = []
            benchmark_df = benchmark_df_seq
            block_counts: dict[str, int] = {}
            bt_sections: dict[str, float] = {}
            _t = time.time()
            _cprof_sym = bool(
                getattr(args, "cprofile", False) and len(symbol_list) == 1 and sym == symbol_list[0]
            )
            _cprof_obj: Optional[cProfile.Profile] = cProfile.Profile() if _cprof_sym else None
            _cprof_smt_sym = bool(
                getattr(args, "cprofile_sheet_magic_touch", False)
                and len(symbol_list) == 1
                and sym == symbol_list[0]
            )
            _cprof_smt_obj: Optional[cProfile.Profile] = cProfile.Profile() if _cprof_smt_sym else None
            _cprof_prep_sym = bool(
                getattr(args, "cprofile_pending_sheet_prep", False)
                and len(symbol_list) == 1
                and sym == symbol_list[0]
            )
            _cprof_prep_obj: Optional[cProfile.Profile] = cProfile.Profile() if _cprof_prep_sym else None
            if _cprof_obj is not None:
                _cprof_obj.enable()
            _dual_sym = _normalize_transaction_type(getattr(_sym_cfg, "transaction_type", "long")) == "both"
            extra_open_trades_loop: list[BRTTrade] = []
            try:
                if _alt_entry_run:
                    closed, open_trade, scanner, short_cands, would_have, watchlist, extra_open_trades_loop = (
                        _run_alt_entry_backtest_bundle(sym, df, _sym_cfg, benchmark_df)
                    )
                elif _print_zones:
                    if _dual_sym:
                        br_zl: list[dict] = []
                        br_zs: list[dict] = []
                        cfg_zl = replace(_sym_cfg, entry_type="long", transaction_type="long")
                        cfg_zs = replace(_sym_cfg, entry_type="short", transaction_type="short")
                        closed_l, ot_l, scan_l, sc_l, wh_l, wl_l, extra_l = run_brt_backtest(
                            sym, df, cfg_zl, ph_price, pl_price, struct, level3, zone_entries_debug=zone_entries_debug,
                            benchmark_df=benchmark_df, profile_beta_times=profile_beta_times, reference_stats=ref_stats,
                            profile_block_reasons=block_counts,
                            profile_backtest_sections=bt_sections if args.profile else None,
                            cprofile_magic_touch=_cprof_smt_obj,
                            cprofile_pending_sheet_prep=_cprof_prep_obj,
                            breakout_retest_rows_out=br_zl,
                            indicators_while_held_rows_out=_ind_wh_out_seq,
                        )
                        _tag_breakout_rows_side(br_zl, "LONG")
                        all_breakout_retest.extend(br_zl)
                        closed_s, ot_s, scan_s, sc_s, wh_s, wl_s, extra_s = run_brt_backtest(
                            sym, df, cfg_zs, ph_price, pl_price, struct, level3, zone_entries_debug=None,
                            benchmark_df=benchmark_df, profile_beta_times=profile_beta_times, reference_stats=ref_stats,
                            profile_block_reasons=block_counts,
                            profile_backtest_sections=bt_sections if args.profile else None,
                            cprofile_magic_touch=_cprof_smt_obj,
                            cprofile_pending_sheet_prep=_cprof_prep_obj,
                            breakout_retest_rows_out=br_zs,
                            indicators_while_held_rows_out=_ind_wh_out_seq,
                        )
                        _tag_breakout_rows_side(br_zs, "SHORT")
                        all_breakout_retest.extend(br_zs)
                        closed = _merge_closed_dual_streams(closed_l, closed_s)
                        scanner = scan_l + scan_s
                        short_cands = sc_l + sc_s
                        would_have = wh_l + wh_s
                        watchlist = wl_l + wl_s
                        open_trade, extra_from_dual = _dual_bundle_primary_extra_open(ot_l, ot_s)
                        extra_open_trades_loop = list(extra_l) + list(extra_s) + list(extra_from_dual)
                    else:
                        closed, open_trade, scanner, short_cands, would_have, watchlist, extra_open_trades_loop = run_brt_backtest(
                            sym, df, _sym_cfg, ph_price, pl_price, struct, level3, zone_entries_debug=zone_entries_debug,
                            benchmark_df=benchmark_df, profile_beta_times=profile_beta_times, reference_stats=ref_stats,
                            profile_block_reasons=block_counts,
                            profile_backtest_sections=bt_sections if args.profile else None,
                            cprofile_magic_touch=_cprof_smt_obj,
                            cprofile_pending_sheet_prep=_cprof_prep_obj,
                            breakout_retest_rows_out=all_breakout_retest,
                            indicators_while_held_rows_out=_ind_wh_out_seq,
                        )
                else:
                    if _dual_sym:
                        br_dl: list[dict] = []
                        br_ds: list[dict] = []
                        cfg_dl = replace(_sym_cfg, entry_type="long", transaction_type="long")
                        cfg_ds = replace(_sym_cfg, entry_type="short", transaction_type="short")
                        closed_l, ot_l, scan_l, sc_l, wh_l, wl_l, extra_l = run_brt_backtest(
                            sym, df, cfg_dl, ph_price, pl_price, struct, level3, benchmark_df=benchmark_df,
                            profile_beta_times=profile_beta_times, reference_stats=ref_stats,
                            profile_block_reasons=block_counts,
                            profile_backtest_sections=bt_sections if args.profile else None,
                            cprofile_magic_touch=_cprof_smt_obj,
                            cprofile_pending_sheet_prep=_cprof_prep_obj,
                            breakout_retest_rows_out=br_dl,
                            indicators_while_held_rows_out=_ind_wh_out_seq,
                        )
                        _tag_breakout_rows_side(br_dl, "LONG")
                        all_breakout_retest.extend(br_dl)
                        closed_s, ot_s, scan_s, sc_s, wh_s, wl_s, extra_s = run_brt_backtest(
                            sym, df, cfg_ds, ph_price, pl_price, struct, level3, benchmark_df=benchmark_df,
                            profile_beta_times=profile_beta_times, reference_stats=ref_stats,
                            profile_block_reasons=block_counts,
                            profile_backtest_sections=bt_sections if args.profile else None,
                            cprofile_magic_touch=_cprof_smt_obj,
                            cprofile_pending_sheet_prep=_cprof_prep_obj,
                            breakout_retest_rows_out=br_ds,
                            indicators_while_held_rows_out=_ind_wh_out_seq,
                        )
                        _tag_breakout_rows_side(br_ds, "SHORT")
                        all_breakout_retest.extend(br_ds)
                        closed = _merge_closed_dual_streams(closed_l, closed_s)
                        scanner = scan_l + scan_s
                        short_cands = sc_l + sc_s
                        would_have = wh_l + wh_s
                        watchlist = wl_l + wl_s
                        open_trade, extra_from_dual = _dual_bundle_primary_extra_open(ot_l, ot_s)
                        extra_open_trades_loop = list(extra_l) + list(extra_s) + list(extra_from_dual)
                    else:
                        closed, open_trade, scanner, short_cands, would_have, watchlist, extra_open_trades_loop = run_brt_backtest(
                            sym, df, _sym_cfg, ph_price, pl_price, struct, level3, benchmark_df=benchmark_df,
                            profile_beta_times=profile_beta_times, reference_stats=ref_stats,
                            profile_block_reasons=block_counts,
                            profile_backtest_sections=bt_sections if args.profile else None,
                            cprofile_magic_touch=_cprof_smt_obj,
                            cprofile_pending_sheet_prep=_cprof_prep_obj,
                            breakout_retest_rows_out=all_breakout_retest,
                            indicators_while_held_rows_out=_ind_wh_out_seq,
                        )
            finally:
                if _cprof_obj is not None:
                    _cprof_obj.disable()
                    _co = (args.cprofile_out or "").strip()
                    if _co:
                        _cprof_path = Path(_co)
                    else:
                        _cprof_path = output_dir / f"{_file_prefix}_cProfile_{sym}_{ts}.prof"
                    if _cprof_path.suffix.lower() not in (".prof", ".pstats"):
                        _cprof_path = _cprof_path.with_suffix(".prof")
                    _cprof_path.parent.mkdir(parents=True, exist_ok=True)
                    _cprof_obj.dump_stats(str(_cprof_path))
                    print(f"[PROFILE] cProfile (run_brt_backtest only): {_cprof_path.resolve()}")
                    print(f"[PROFILE]   python -m pstats {_cprof_path}   # then: sort cumulative / stats 40")
                    print(f"[PROFILE]   snakeviz {_cprof_path}   # pip install snakeviz")
                    print("[PROFILE] Wall-time flame (optional): py-spy record -o flame.svg -- python ... rocket_brt.py ...")
                if _cprof_smt_obj is not None:
                    _smt_co = (getattr(args, "cprofile_sheet_magic_touch_out", "") or "").strip()
                    if _smt_co:
                        _smt_path = Path(_smt_co)
                    else:
                        _smt_path = output_dir / f"{_file_prefix}_cProfile_sheet_magic_touch_{sym}_{ts}.prof"
                    if _smt_path.suffix.lower() not in (".prof", ".pstats"):
                        _smt_path = _smt_path.with_suffix(".prof")
                    _smt_path.parent.mkdir(parents=True, exist_ok=True)
                    _cprof_smt_obj.dump_stats(str(_smt_path))
                    print(f"[PROFILE] cProfile (bt_loop_sheet_magic_touch block only): {_smt_path.resolve()}")
                    print(f"[PROFILE]   python -m pstats {_smt_path}   # sort cumulative; stats 30")
                    print(f"[PROFILE]   snakeviz {_smt_path}")
                if _cprof_prep_obj is not None:
                    _prep_co = (getattr(args, "cprofile_pending_sheet_prep_out", "") or "").strip()
                    if _prep_co:
                        _prep_path = Path(_prep_co)
                    else:
                        _prep_path = output_dir / f"{_file_prefix}_cProfile_pending_sheet_prep_{sym}_{ts}.prof"
                    if _prep_path.suffix.lower() not in (".prof", ".pstats"):
                        _prep_path = _prep_path.with_suffix(".prof")
                    _prep_path.parent.mkdir(parents=True, exist_ok=True)
                    _cprof_prep_obj.dump_stats(str(_prep_path))
                    print(f"[PROFILE] cProfile (bt_loop_pending_sheet_prep block only): {_prep_path.resolve()}")
                    print(f"[PROFILE]   python -m pstats {_prep_path}   # sort cumulative; stats 30")
                    print(f"[PROFILE]   snakeviz {_prep_path}")
            t_backtest = time.time() - _t
            _apply_spy_ind_diff_at_entry(closed, open_trade, extra_open_trades_loop, spy_lookup_seq)
            all_closed.extend(closed)
            if getattr(args, "emit_would_have", False):
                all_would_have.extend(would_have)
            if open_trade:
                all_open.append(open_trade)
            all_open.extend(extra_open_trades_loop)
            all_scanner.extend(scanner)
            all_watchlist.extend(watchlist)
            all_short_candidates.extend(short_cands)
            _t = time.time()
            if not _alt_entry_run:
                all_pivot_rows.extend(collect_brt_pivots(sym, df, pivot_high, pivot_low, ph_price, pl_price, struct))
            t_collect_pivots = time.time() - _t
            if _collect_symbol_timings:
                _row = {
                    "symbol": sym,
                    "bars": int(len(df)),
                    "t_load": 0.0,  # already loaded in parent path
                    "t_spy_lookup": 0.0,
                    "t_pivots": t_pivots,
                    "t_structure": t_structure,
                    "t_touch": t_touch,
                    "t_backtest": t_backtest,
                    "t_collect_pivots": t_collect_pivots,
                    "t_total": time.time() - _sym_t0,
                }
                _row.update(bt_sections)
                profile_symbol_rows.append(_row)
                for reason, count in sorted(block_counts.items()):
                    profile_block_rows.append({"symbol": sym, "reason": reason, "count": int(count)})

            if not _alt_entry_run and _print_zones:
                _write_zone_debug_files(
                    sym,
                    df,
                    level3,
                    zone_entries_debug,
                    _sym_cfg.band_pct,
                    str(output_dir),
                    ts,
                    _file_prefix,
                )

            if n_total > 1:
                _backtest_progress(idx, n_total, progress_t0, pipeline)
        if n_total > 1:
            print()

        if args.profile and profile_beta_times:
            print(f"[PROFILE] beta_at_entry (total {len(profile_beta_times)} calls): {sum(profile_beta_times):.2f}s")

    if not skip_backtest:
        elapsed = time.time() - t0
        per_sym = elapsed / n_total if n_total > 0 else 0
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] Backtest complete in {elapsed:.1f}s"
            + (f" ({per_sym:.2f}s/symbol)" if n_total > 1 else ""),
            flush=True,
        )
        if pipeline is not None and getattr(pipeline, "enabled", False):
            pipeline.record_phase_seconds("backtest_loop", elapsed)
            pipeline.mark_backtest_complete()
            pipeline.end_progress_line()
            _will_equity_bt = (
                bool(cfg.compute_equity_metrics)
                and not getattr(args, "no_equity_metrics", False)
                and bool(all_closed)
                and bool(tickers)
                and _compute_equity_metrics is not None
            )
            _will_regress_bt = not symbol_list and not getattr(args, "no_regression", False)
            _plan_post_pipeline_units(
                pipeline,
                all_closed,
                all_open,
                cfg,
                will_yfinance=bool(all_closed or all_open),
                will_equity=_will_equity_bt,
                will_correlation=bool(all_closed),
                will_regression=_will_regress_bt,
                will_zscore_filter=bool(need_post_filter and (all_closed or all_open)),
            )
        if args.profile:
            print(f"[PROFILE] backtest_loop: {elapsed:.2f}s")
            if profile_symbol_rows:
                prof_sym_path = output_dir / f"{_file_prefix}_Profile_Symbols_{ts}.csv"
                _df_sym = pd.DataFrame(profile_symbol_rows).sort_values("t_total", ascending=False)
                _df_sym.to_csv(prof_sym_path, index=False)
                print(f"[PROFILE] symbols_timing: {prof_sym_path.name} ({len(profile_symbol_rows)} rows)")
                _print_profile_symbol_summary(profile_symbol_rows)
                _bt_cols = [c for c in _df_sym.columns if c.startswith("bt_")]
                if _bt_cols:
                    _means = _df_sym[_bt_cols].mean()
                    _parts = [f"{c}={float(_means[c]):.4f}" for c in sorted(_bt_cols)]
                    _max_parts = 20
                    print(
                        f"[PROFILE] run_brt_backtest sections (mean s/symbol): "
                        + "; ".join(_parts[:_max_parts])
                        + (" ..." if len(_parts) > _max_parts else "")
                    )
            if profile_block_rows and (args.profile or pipeline is not None):
                prof_block_path = output_dir / f"{_file_prefix}_Profile_BlockReasons_{ts}.csv"
                df_block = pd.DataFrame(profile_block_rows)
                by_reason = (
                    df_block.groupby("reason", as_index=False)["count"].sum()
                    .sort_values("count", ascending=False)
                    .rename(columns={"count": "total_count"})
                )
                by_symbol_reason = df_block.groupby(["symbol", "reason"], as_index=False)["count"].sum().sort_values(
                    "count", ascending=False
                )
                by_reason.to_csv(prof_block_path, index=False)
                by_symbol_reason.to_csv(output_dir / f"{_file_prefix}_Profile_BlockReasons_BySymbol_{ts}.csv", index=False)
                top_parts: list[str] = []
                for _, row in by_reason.head(6).iterrows():
                    top_parts.append(f"{row['reason']}={int(row['total_count'])}")
                top = ", ".join(top_parts)
                print(f"[PROFILE] block_reasons: {prof_block_path.name} ({len(by_reason)} reasons) | top: {top}")
            print("[PROFILE] --- Post-processing ---")
        elif pipeline is not None and getattr(pipeline, "enabled", False) and profile_symbol_rows:
            prof_sym_path = output_dir / f"BRT_Profile_Symbols_{ts}.csv"
            pd.DataFrame(profile_symbol_rows).sort_values("t_total", ascending=False).to_csv(prof_sym_path, index=False)
            print(f"[PIPELINE] Per-symbol timings: {prof_sym_path.name} ({len(profile_symbol_rows)} rows)", flush=True)
        if not getattr(args, "no_checkpoint", False):
            _ck_out = _brt_checkpoint_path(output_dir, ts, _file_prefix)
            try:
                _save_brt_checkpoint(
                    _ck_out,
                    {
                        "version": _BRT_CHECKPOINT_VERSION,
                        "ts": ts,
                        "n_symbols": n_total,
                        "ticker_list": ticker_list,
                        "all_closed": all_closed,
                        "all_open": all_open,
                        "all_scanner": all_scanner,
                        "all_watchlist": all_watchlist,
                        "all_short_candidates": all_short_candidates,
                        "all_would_have": all_would_have,
                        "all_breakout_retest": all_breakout_retest,
                        "all_indicators_while_held": all_indicators_while_held,
                        "all_pivot_rows": all_pivot_rows,
                        "profile_symbol_rows": profile_symbol_rows,
                        "profile_block_rows": profile_block_rows,
                        "ref_stats": ref_stats,
                    },
                )
                print(
                    f"[BRT] Checkpoint saved: {_ck_out.name} "
                    f"({len(all_closed)} closed, {len(all_open)} open). "
                    f"Resume post-processing: add --post-only --from-run {ts}",
                    flush=True,
                )
            except OSError as e:
                print(f"[BRT] Warning: could not save checkpoint: {e}", file=sys.stderr)

    if _duckdb_parallel_symbol_list is not None and not post_only:
        _trade_syms_post = _brt_trade_symbols(all_closed, all_open)
        _extra_load_post: set[str] = set()
        if (
            bool(cfg.compute_equity_metrics)
            and not getattr(args, "no_equity_metrics", False)
            and _compute_equity_metrics is not None
        ):
            _extra_load_post.add("SPY")
        _t_ld_post = time.time()
        if pipeline is not None:
            with pipeline.phase("load_tickers"):
                tickers = _load_tickers_for_symbols(
                    _trade_syms_post,
                    data_dir,
                    use_duckdb=use_duckdb,
                    db_path=db_path,
                    db_table=db_table,
                    extra_symbols=_extra_load_post,
                )
        else:
            tickers = _load_tickers_for_symbols(
                _trade_syms_post,
                data_dir,
                use_duckdb=use_duckdb,
                db_path=db_path,
                db_table=db_table,
                extra_symbols=_extra_load_post,
            )
        if args.profile:
            print(
                f"[PROFILE] load_tickers (post-backtest): {time.time() - _t_ld_post:.2f}s "
                f"({len(tickers)} symbols for {len(_trade_syms_post)} trade tickers)",
                flush=True,
            )
        print(
            f"[BRT] Loaded OHLCV for {len(tickers)} symbol(s) used in post-processing "
            f"({len(_trade_syms_post)} trade ticker(s)).",
            flush=True,
        )

    # After one pass: if z-score filter is on, compute ref stats from all trades and keep only those passing threshold
    if need_post_filter and (all_closed or all_open):
        with (pipeline.phase("zscore_post_filter") if pipeline is not None else contextlib.nullcontext()):
            ref_stats = _compute_reference_stats_from_trades(all_closed, all_open)
            threshold = getattr(cfg, "realtime_filter_threshold", 0.0)
            n_before_closed, n_before_open = len(all_closed), len(all_open)
            all_closed = [t for t in all_closed if _realtime_score_for_trade(t, cfg, ref_stats) >= threshold]
            all_open = [t for t in all_open if _realtime_score_for_trade(t, cfg, ref_stats) >= threshold]
            print(
                f"[BRT] Z-score: kept {len(all_closed)}/{n_before_closed} closed, "
                f"{len(all_open)}/{n_before_open} open (threshold={threshold})"
            )
        if pipeline is not None:
            pipeline.complete_phase_units("zscore_post_filter")
        if args.debug_signals and len(symbol_list) == 1:
            # Diagnostic: maturity events, short candidates, entries
            print(f"\n--- BRT Debug: {sym} ---")
            entries = [(t.date_opened[:4]+"-"+t.date_opened[4:6]+"-"+t.date_opened[6:8], t.entry_price, t.zone_center) for t in closed]
            for s in scanner:
                if s.get("symbol") == sym:
                    entries.append((s["date"], s.get("close", 0), s.get("zone_center", 0)))
            print(f"Entries ({len(entries)}):")
            for dt, ep, zc in entries:
                print(f"  {dt} entry={ep:.2f} zone_center={zc:.4f}")
            # Trade trace: 6th touch -> close-above -> entry (for 5/23 vs 5/27 alignment check)
            print("Trade trace (6th touch -> close-above -> entry):")
            for t in closed:
                md = getattr(t, "maturity_date", "") or ""
                cd = getattr(t, "close_above_date", "") or ""
                ed = t.date_opened[:4]+"-"+t.date_opened[4:6]+"-"+t.date_opened[6:8] if len(t.date_opened) >= 8 else t.date_opened
                flag = " <-- 5/23 vs 5/27 case" if "2025-05" in ed or "2025-05" in cd else ""
                print(f"  {t.symbol} 6th_touch={md} close_above={cd} entry={ed} @{t.entry_price:.2f}{flag}")
            print(f"Short candidates ({len(short_cands)}):")
            for s in short_cands[:10]:
                print(f"  {s['date']} zone_center={s['zone_center']:.4f} close={s['close']:.2f} touch_count={s['touch_count']}")
            if len(short_cands) > 10:
                print(f"  ... and {len(short_cands) - 10} more")
            # Pivots and touches around 2022-09 and 2023-05 (manual 9/12 and 5/15)
            print("Pivots/touches near 2022-09-08 to 2022-09-14:")
            for i in range(len(df)):
                dt = df.index[i].strftime("%Y-%m-%d") if hasattr(df.index[i], "strftime") else str(df.index[i])[:10]
                if "2022-09-0" in dt or "2022-09-1" in dt:
                    ph = pivot_high.iloc[i] == 1
                    pl = pivot_low.iloc[i] == 1
                    tp = level3["touch_price"].iloc[i] if pd.notna(level3["touch_price"].iloc[i]) else ""
                    tc = int(level3["touch_count_long"].iloc[i]) if level3["touch_count_long"].iloc[i] > 0 else ""
                    zc = level3["zone_center"].iloc[i] if pd.notna(level3["zone_center"].iloc[i]) else ""
                    sh = struct["structure_high"].iloc[i] or ""
                    sl = struct["structure_low"].iloc[i] or ""
                    maj_ph = struct["major_pivot_high"].iloc[i] == 1
                    maj_pl = struct["major_pivot_low"].iloc[i] == 1
                    if ph or pl:
                        print(f"  {dt} H={df['High'].iloc[i]:.2f} L={df['Low'].iloc[i]:.2f} PivotH={ph} PivotL={pl} touch_price={tp} zone_center={zc} touch_cnt={tc} structH={sh} structL={sl} majPH={maj_ph} majPL={maj_pl}")
            print("Pivots/touches near 2023-05-10 to 2023-05-18:")
            for i in range(len(df)):
                dt = df.index[i].strftime("%Y-%m-%d") if hasattr(df.index[i], "strftime") else str(df.index[i])[:10]
                if "2023-05-1" in dt:
                    ph = pivot_high.iloc[i] == 1
                    pl = pivot_low.iloc[i] == 1
                    tp = level3["touch_price"].iloc[i] if pd.notna(level3["touch_price"].iloc[i]) else ""
                    tc = int(level3["touch_count_long"].iloc[i]) if level3["touch_count_long"].iloc[i] > 0 else ""
                    zc = level3["zone_center"].iloc[i] if pd.notna(level3["zone_center"].iloc[i]) else ""
                    sh = struct["structure_high"].iloc[i] or ""
                    sl = struct["structure_low"].iloc[i] or ""
                    if ph or pl:
                        print(f"  {dt} H={df['High'].iloc[i]:.2f} L={df['Low'].iloc[i]:.2f} PivotH={ph} PivotL={pl} touch_price={tp} zone_center={zc} touch_cnt={tc} structH={sh} structL={sl}")
            # For 9/12 zone [14.26, 14.84]: which pivots fall inside? (manual: 7/13, 4/22, 11/9, 10/12, 10/13, 9/2)
            zl, zu = 14.26, 14.84
            print(f"All pivots with touch_price in zone [{zl},{zu}] (manual's 9/12 zone):")
            for i in range(len(df)):
                if not pd.notna(level3["touch_price"].iloc[i]) or level3["touch_price"].iloc[i] <= 0:
                    continue
                tp = float(level3["touch_price"].iloc[i])
                if zl <= tp <= zu:
                    dt = df.index[i].strftime("%Y-%m-%d") if hasattr(df.index[i], "strftime") else str(df.index[i])[:10]
                    ph = pivot_high.iloc[i] == 1
                    pl = pivot_low.iloc[i] == 1
                    pty = "PivotH" if ph else "PivotL"
                    print(f"  {dt} {pty} touch_price={tp:.2f}")
            # Explicit: which touches we count for 9/12's zone (within lookback)
            idx_912 = None
            for i in range(len(df)):
                dt = df.index[i].strftime("%Y-%m-%d") if hasattr(df.index[i], "strftime") else str(df.index[i])[:10]
                if dt == "2022-09-12":
                    idx_912 = i
                    break
            if idx_912 is not None:
                i = idx_912
                zc_i = level3["zone_center"].iloc[i]
                zl_i = level3["zone_low"].iloc[i]
                zu_i = level3["zone_high"].iloc[i]
                start = max(0, i - cfg.lookback_long + 1)
                touches = []
                for j in range(start, i + 1):
                    if pd.notna(level3["touch_price"].iloc[j]) and level3["touch_price"].iloc[j] > 0:
                        tp = float(level3["touch_price"].iloc[j])
                        if zl_i <= tp <= zu_i:
                            dt_j = df.index[j].strftime("%Y-%m-%d") if hasattr(df.index[j], "strftime") else str(df.index[j])[:10]
                            pty = "PivotH" if pivot_high.iloc[j] == 1 else "PivotL"
                            touches.append((dt_j, pty, tp))
                print(f"Touches we count for 9/12 zone (lookback={cfg.lookback_long}, start=bar {start}):")
                for dt_j, pty, tp in touches:
                    print(f"  {dt_j} {pty} {tp:.2f}")
            # For 5/12 zone [27.49, 28.61]: manual has 6 touches (4/18, 4/4, 3/22, 1/12/22, 12/6/21, 5/12)
            zl512, zu512 = 27.49, 28.61
            print(f"All pivots with touch_price in zone [{zl512},{zu512}] (manual's 5/12 zone):")
            for i in range(len(df)):
                if not pd.notna(level3["touch_price"].iloc[i]) or level3["touch_price"].iloc[i] <= 0:
                    continue
                tp = float(level3["touch_price"].iloc[i])
                if zl512 <= tp <= zu512:
                    dt = df.index[i].strftime("%Y-%m-%d") if hasattr(df.index[i], "strftime") else str(df.index[i])[:10]
                    ph = pivot_high.iloc[i] == 1
                    pl = pivot_low.iloc[i] == 1
                    pty = "PivotH" if ph else "PivotL"
                    print(f"  {dt} {pty} touch_price={tp:.2f}")
            idx_512 = None
            for i in range(len(df)):
                dt = df.index[i].strftime("%Y-%m-%d") if hasattr(df.index[i], "strftime") else str(df.index[i])[:10]
                if dt == "2023-05-12":
                    idx_512 = i
                    break
            if idx_512 is not None:
                i = idx_512
                zc_i = level3["zone_center"].iloc[i]
                zl_i = level3["zone_low"].iloc[i]
                zu_i = level3["zone_high"].iloc[i]
                start = max(0, i - cfg.lookback_long + 1)
                touches = []
                for j in range(start, i + 1):
                    if pd.notna(level3["touch_price"].iloc[j]) and level3["touch_price"].iloc[j] > 0:
                        tp = float(level3["touch_price"].iloc[j])
                        if zl_i <= tp <= zu_i:
                            dt_j = df.index[j].strftime("%Y-%m-%d") if hasattr(df.index[j], "strftime") else str(df.index[j])[:10]
                            pty = "PivotH" if pivot_high.iloc[j] == 1 else "PivotL"
                            touches.append((dt_j, pty, tp))
                print(f"Touches we count for 5/12 zone (lookback={cfg.lookback_long}, start=bar {start}):")
                for dt_j, pty, tp in touches:
                    print(f"  {dt_j} {pty} {tp:.2f}")
            print("---\n")

        if len(symbol_list) == 1 and sym == symbol_list[0] and HAS_MATPLOTLIB:
            chart_path = output_dir / f"{_file_prefix}_Chart_{sym}_{ts}.png"
            open_for_sym = [t for t in all_open if t.symbol == sym]
            plot_brt_bands(sym, df, level3, closed, str(chart_path), band_pct=cfg.band_pct, open_trades=open_for_sym)
            print(f"Chart saved: {chart_path}")

    if pipeline is not None:
        print("[PIPELINE] Post-processing started", flush=True)

    _t_yf = time.time()
    if all_closed or all_open:
        print(
            "[BRT] Post-run: yfinance enrichment (market cap / sector; may take several minutes; "
            "HTTP 404 from Yahoo is normal for invalid or thin symbols).",
            flush=True,
        )
    with (pipeline.phase("yfinance_enrich") if pipeline is not None else contextlib.nullcontext()):
        _enrich_trades_yfinance(
            all_closed,
            all_open,
            yfinance_workers=n_workers if n_workers > 0 else None,
            pipeline=pipeline,
        )
    if pipeline is not None:
        pipeline.complete_phase_units("yfinance_enrich")
    if all_closed or all_open:
        print(f"[BRT] Post-run: yfinance enrichment finished in {time.time() - _t_yf:.1f}s", flush=True)
    if args.profile and (all_closed or all_open):
        print(f"[PROFILE] yfinance enrich: {time.time() - _t_yf:.2f}s")
    # Min market cap filter (applied after enrichment; 0 = no op)
    with (pipeline.phase("market_cap_filter") if pipeline is not None else contextlib.nullcontext()):
        if getattr(cfg, "min_market_cap", 0) > 0:
            all_closed = [t for t in all_closed if getattr(t, "market_cap", None) is not None and t.market_cap >= cfg.min_market_cap]
            all_open = [t for t in all_open if getattr(t, "market_cap", None) is not None and t.market_cap >= cfg.min_market_cap]
        if float(getattr(cfg, "max_market_cap", 0) or 0) > 0:
            mx = float(cfg.max_market_cap)
            all_closed = [t for t in all_closed if getattr(t, "market_cap", None) is not None and float(t.market_cap) <= mx]
            all_open = [t for t in all_open if getattr(t, "market_cap", None) is not None and float(t.market_cap) <= mx]
    if pipeline is not None:
        pipeline.complete_phase_units("market_cap_filter")
    with (pipeline.phase("post_entry_gain_hit") if pipeline is not None else contextlib.nullcontext()):
        _enrich_post_entry_gain_hit(
            all_closed + all_open,
            tickers,
            cfg,
            pipeline=pipeline,
            workers=n_workers if n_workers > 0 else 0,
        )
    _t_ind = time.time()
    with (pipeline.phase("entry_indicators") if pipeline is not None else contextlib.nullcontext()):
        _enrich_trades_entry_indicators(
            all_closed + all_open,
            tickers,
            cfg,
            pipeline=pipeline,
            workers=n_workers if n_workers > 0 else 0,
        )
    if pipeline is not None:
        pipeline.complete_phase_units("entry_indicators")
    if args.profile and bool(getattr(cfg, "use_indicators", False)):
        _nw = n_workers if n_workers > 0 else 1
        print(
            f"[PROFILE] entry_indicators: {time.time() - _t_ind:.2f}s "
            f"({len(all_closed) + len(all_open)} trades, workers={_nw})",
            flush=True,
        )
    if _uses_indicators and bool(getattr(cfg, "indicator_cache", True)):
        try:
            from brt_entry_indicators import format_indicator_cache_stats, get_indicator_cache_stats
        except ImportError:
            from stock_analysis.brt_entry_indicators import format_indicator_cache_stats, get_indicator_cache_stats
        _ics = get_indicator_cache_stats()
        if sum(_ics.values()):
            print(f"[BRT] Indicator cache stats: {format_indicator_cache_stats(_ics)}")
    # Match BRT_Report/BRT_Audit: brt_cash = 1M/max_positions; scale PNL_DOLLARS everywhere before writing CSVs
    with (pipeline.phase("dollar_scale") if pipeline is not None else contextlib.nullcontext()):
        if all_closed:
            adj_cash, pnl_scale = _apply_report_dollar_scale_to_trades(all_closed, all_open, cfg)
            if abs(pnl_scale - 1.0) >= 1e-12:
                mp = _resolve_max_positions(all_closed, cfg)
                print(
                    f"[BRT] Dollar scale (report notional): PNL_DOLLARS × {pnl_scale:.6g}; "
                    f"brt_cash -> {adj_cash:,.0f} ($1M / Max_Positions={mp})"
                )
    if pipeline is not None:
        pipeline.complete_phase_units("dollar_scale")
    _t_write_start = time.time()
    closed_path = str(output_dir / f"{_file_prefix}_Closed_{ts}.csv")
    with (pipeline.phase("write_closed") if pipeline is not None else contextlib.nullcontext()):
        write_brt_closed(all_closed, closed_path, reference_stats=ref_stats, cfg=cfg)
    if pipeline is not None:
        pipeline.complete_phase_units("write_closed")
    if args.profile:
        print(f"[PROFILE] write_brt_closed: {time.time() - _t_write_start:.2f}s ({len(all_closed)} trades)")
    br_retest_path = str(output_dir / f"{_file_prefix}_breakout_and_retest_{ts}.csv")
    with (pipeline.phase("write_breakout_retest") if pipeline is not None else contextlib.nullcontext()):
        write_brt_breakout_and_retest(all_breakout_retest, br_retest_path)
    if pipeline is not None:
        pipeline.complete_phase_units("write_breakout_retest")
    print(f"[FILE] Breakout/retest audit: {br_retest_path} ({len(all_breakout_retest)} rows)")
    if getattr(args, "emit_would_have", False) and all_would_have:
        would_have_path = str(output_dir / f"{_file_prefix}_WouldHave_{ts}.csv")
        with (pipeline.phase("write_would_have") if pipeline is not None else contextlib.nullcontext()):
            _write_would_have_csv(all_would_have, would_have_path)
        if pipeline is not None:
            pipeline.complete_phase_units("write_would_have")
        print(f"[FILE] Would-have entries: {would_have_path} ({len(all_would_have)} rows)")
    _t_corr = time.time()
    with (pipeline.phase("correlation_report") if pipeline is not None else contextlib.nullcontext()):
        try:
            _sa = Path(__file__).resolve().parent
            if str(_sa) not in sys.path:
                sys.path.insert(0, str(_sa))
            from correlate_brt_closed import run_correlation_report
            run_correlation_report(closed_path, str(output_dir / f"{_file_prefix}_Correlation_{ts}.csv"))
            if args.profile:
                print(f"[PROFILE] correlation_report: {time.time() - _t_corr:.2f}s")
            print(f"Correlation report: {_file_prefix}_Correlation_{ts}.csv")
            print(f"Correlation pairs report: {_file_prefix}_Correlation_Pairs_{ts}.csv")
        except Exception as e:
            if args.profile:
                print(f"[PROFILE] correlation_report: {time.time() - _t_corr:.2f}s (failed)")
            print(f"[BRT] Correlation report skipped: {e}")
    if pipeline is not None:
        pipeline.complete_phase_units("correlation_report")
    _t_wo = time.time()
    with (pipeline.phase("write_open") if pipeline is not None else contextlib.nullcontext()):
        write_brt_open(all_open, str(output_dir / f"{_file_prefix}_Open_{ts}.csv"), tickers=tickers, brt_cash=cfg.brt_cash, closed=all_closed, cfg=cfg)
    if pipeline is not None:
        pipeline.complete_phase_units("write_open")
    if args.profile:
        print(f"[PROFILE] write_brt_open: {time.time() - _t_wo:.2f}s")
    with (pipeline.phase("write_misc") if pipeline is not None else contextlib.nullcontext()):
        _scanner_path = str(output_dir / f"{_file_prefix}_Scanner_{ts}.csv")
        if write_brt_scanner(all_scanner, _scanner_path, cfg=cfg):
            print(f"[FILE] Scanner: {_scanner_path} ({len(all_scanner)} rows)")
        _wl_path = str(output_dir / f"{_file_prefix}_Watchlist_{ts}.csv")
        if _normalize_indicator_buy(getattr(cfg, "indicator_buy", "off")) == "only":
            all_watchlist = _finalize_ind_watchlist(all_watchlist, cfg)
            write_ind_watchlist(all_watchlist, _wl_path)
            print(f"[FILE] Watchlist: {_wl_path} ({len(all_watchlist)} rows)")
            _top_n = int(getattr(cfg, "ind_watchlist_top_n", 50) or 0)
            if _top_n > 0 and all_watchlist:
                _wl_top_path = str(output_dir / f"{_file_prefix}_Watchlist_Top{_top_n}_{ts}.csv")
                write_ind_watchlist(all_watchlist[:_top_n], _wl_top_path)
                print(f"[FILE] Watchlist top {_top_n}: {_wl_top_path}")
        else:
            write_brt_watchlist(all_watchlist, _wl_path)
            print(f"[FILE] Watchlist: {_wl_path} ({len(all_watchlist)} rows)")
        if _indicator_mode_active(cfg):
            _iwh_path = str(output_dir / f"{_file_prefix}_indicators_while_held_{ts}.csv")
            write_ind_indicators_while_held(all_indicators_while_held, _iwh_path)
            print(
                f"[FILE] Indicators while held: {_iwh_path} ({len(all_indicators_while_held)} rows)"
            )
        write_brt_short_candidates(all_short_candidates, str(output_dir / f"{_file_prefix}_ShortCandidates_{ts}.csv"))
        write_brt_summary(all_closed, str(output_dir / f"{_file_prefix}_Summary_{ts}.csv"))
        write_brt_industry_summary(all_closed, str(output_dir / f"{_file_prefix}_INDUSTRY_{ts}.csv"))
        if all_pivot_rows:
            write_brt_pivots(all_pivot_rows, str(output_dir / f"{_file_prefix}_Pivots_{ts}.csv"))
    if pipeline is not None:
        pipeline.complete_phase_units("write_misc")

    metrics = compute_metrics(all_closed, cfg)
    if cfg.compute_equity_metrics and HAS_EQUITY_METRICS and all_closed and tickers and _compute_equity_metrics:
        try:
            _t_eq = time.time()
            with (pipeline.phase("compute_equity_metrics") if pipeline is not None else contextlib.nullcontext()):
                equity = _compute_equity_metrics(
                    all_closed,
                    all_open,
                    tickers,
                    cfg.brt_cash,
                    initial_capital=cfg.initial_capital,
                    aggressive=cfg.aggressive,
                    aggressive_margin_interest=cfg.aggressive_margin_interest,
                    aggressive_max_multiple=cfg.aggressive_max_multiple,
                    aggressive_avg_positions=(
                        cfg.aggressive_avg_positions if cfg.aggressive_avg_positions > 0 else None
                    ),
                    aggressive_sizing_equity_cap=cfg.aggressive_sizing_equity_cap,
                    margin_utilization=_effective_margin_utilization(cfg),
                    aggressive_sell=_normalize_aggressive_sell(getattr(cfg, "aggressive_sell", "false")),
                    skip_passive_mtm_for_aggressive=bool(
                        getattr(cfg, "equity_fast_aggressive", False) and cfg.aggressive
                    ),
                )
            if pipeline is not None:
                pipeline.complete_phase_units("compute_equity_metrics")
            if args.profile:
                print(f"[PROFILE] compute_equity_metrics: {time.time() - _t_eq:.2f}s")
            metrics["Max_Drawdown"] = equity["Max_Drawdown"]
            metrics["Max_Days_Underwater"] = equity["Max_Days_Underwater"]
            metrics["Pct_Days_Underwater"] = equity["Pct_Days_Underwater"]
            if equity.get("_aggressive"):
                metrics["Aggressive_Avg_Positions"] = equity.get("Aggressive_Avg_Positions", 0)
                metrics["Aggressive_Days_AtOrBelow_Avg"] = equity.get("Aggressive_Days_AtOrBelow_Avg", 0)
                metrics["Aggressive_Days_In_Margin"] = equity.get("Aggressive_Days_In_Margin", 0)
                metrics["Aggressive_Days_Trimmed_Over_2xAvg"] = equity.get("Aggressive_Days_Trimmed_Over_2xAvg", 0)
                metrics["Aggressive_Max_Drawdown"] = equity.get("Aggressive_Max_Drawdown", "N/A")
                agg_total_pnl = float(equity.get("_equity_total_pnl", 0.0) or 0.0)
                metrics["Aggressive_Total_PNL"] = f"{agg_total_pnl:.2f}"
            md = equity["Max_Drawdown"]
            if md and str(md).strip() != "N/A":
                try:
                    pct_val = float(str(md).replace("%", "").strip()) / 100
                    metrics["DD_Per_Trade"] = f"{(pct_val / len(all_closed)):.4f}" if all_closed else "N/A"
                except (ValueError, TypeError):
                    metrics["DD_Per_Trade"] = "N/A"
            else:
                metrics["DD_Per_Trade"] = "N/A"
            _write_brt_equity_canonical_outputs(output_dir, ts, equity, _file_prefix)
            if _generate_underwater_report is not None:
                eq_dates = equity.get("equity_dates") or []
                eq_vals = equity.get("equity_values") or []
                if eq_dates and eq_vals and len(eq_dates) == len(eq_vals):
                    try:
                        _uw_df = pd.DataFrame({"Date": eq_dates, "Equity": eq_vals})
                        _uw_stats = _generate_underwater_report(
                            _uw_df, ts, output_dir=str(output_dir), prefix=_file_prefix
                        )
                        if isinstance(_uw_stats, dict):
                            metrics["Avg_Days_Underwater"] = _uw_stats.get("avg_days_underwater", 0)
                            metrics["P90_Days_Underwater"] = _uw_stats.get("p90_days_underwater", 0)
                    except Exception as _uw_err:
                        print(f"[WARN] Underwater report failed: {_uw_err}", file=sys.stderr)
        except Exception as e:
            print(f"[WARN] Equity metrics failed: {e}", file=sys.stderr)
    with (pipeline.phase("write_reports") if pipeline is not None else contextlib.nullcontext()):
        write_brt_report(cfg, metrics, str(output_dir), ts, args.drive_link, file_prefix=_file_prefix)
        write_brt_audit_report(cfg, metrics, str(output_dir), ts, args.drive_link, file_prefix=_file_prefix)
    if pipeline is not None:
        pipeline.complete_phase_units("write_reports")
    if args.profile:
        print(f"[PROFILE] write_all_outputs: {time.time() - _t_write_start:.2f}s (closed+correlation+open+scanner+summary+report)")

    print(f"[{datetime.now().strftime('%H:%M:%S')}] {_file_prefix} outputs written to {output_dir} (ts={ts})")

    # Run regression check (same pattern as run_audit.ps1 for RocketLauncher)
    if not symbol_list and not args.no_regression:
        for folder in ("Drive", "drive"):
            regress_script = repo_root / folder / "BRTRegressionCheck.ps1"
            if regress_script.exists():
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Running BRT regression check...")
                _t_regress = time.time()
                with (pipeline.phase("regression_check") if pipeline is not None else contextlib.nullcontext()):
                    try:
                        result = subprocess.run(
                            [
                                "powershell", "-ExecutionPolicy", "Bypass", "-NoProfile",
                                "-File", str(regress_script),
                                "-OutputDir", str(output_dir),
                                "-SkipPerfectSetups",
                            ],
                            cwd=str(repo_root),
                            capture_output=False,
                        )
                        if args.profile:
                            print(f"[PROFILE] regression_check: {time.time() - _t_regress:.2f}s")
                        if result.returncode != 0:
                            if pipeline is not None:
                                pipeline.finish()
                            _maybe_play_completion_sound(args.play_sound)
                            return result.returncode
                    except FileNotFoundError:
                        if args.profile:
                            print(f"[PROFILE] regression_check: {time.time() - _t_regress:.2f}s (PowerShell not found)")
                        print("[WARN] PowerShell not found; skipping regression check.", file=sys.stderr)
                    except Exception as e:
                        if args.profile:
                            print(f"[PROFILE] regression_check: {time.time() - _t_regress:.2f}s (failed)")
                        print(f"[WARN] Regression check failed: {e}", file=sys.stderr)
                if pipeline is not None:
                    pipeline.complete_phase_units("regression_check")
                break
        else:
            print("[WARN] BRTRegressionCheck.ps1 not found in Drive/; skipping regression check.", file=sys.stderr)

    if pipeline is not None:
        pipeline.finish()

    _maybe_play_completion_sound(args.play_sound)
    return 0


if __name__ == "__main__":
    sys.exit(main())
18.72