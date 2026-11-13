"""BRTConfig: every engine knob for rocket_tbn (all systems).

Moved verbatim out of rocket_tbn.py on 2026-11-12 (TD-16, first split slice).
rocket_tbn re-exports it, so `from rocket_tbn import BRTConfig` keeps working.
Change defaults here only through tools/adopt.py when they affect production.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field  # noqa: F401  (field/asdict used by some defaults)
from typing import Any, Optional  # noqa: F401


@dataclass
class BRTConfig:
    """Shared TBN engine configuration (historical name; alias ``TBNConfig``).

    Field names that say ``brt_*`` (e.g. ``brt_zones``, ``brt_cash``) refer to the Break-and-ReTest
    *system* or legacy sizing - not the engine brand. Prefer speaking of this object as TBN config
    in docs/CLI; keep ``BRTConfig`` for code/MarkTen parity.

    Google Sheet cell mapping (workbook BRT tab), when aligning to spreadsheet:
    - C7  → tight_range_threshold_pct (program-only compression gate; **AI** = Range Qualifier on sheet is **not** in **AL** buy)
    - C10 → strong post-pivot bars (``strong_post_pivot_bars``): Post Pivot Pullback (K) window,
      AB Touch Price forward pullback window, AND AZ:BB = INDEX(AB/AC/AD, ROW()-C10) matured lag
    - C14 → "periods to check" - unused on the live sheet for AB; do not map to a separate engine field
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
    strong_pre_pivot_bars: int = 7  # Sheet "strong Pre-Pivot bars" (C17) - lookback window ending before pivot bar
    strong_pre_pivot_pct: float = 0.1  # House strong Pre-Pivot move % (10%; prior sheet C13 was 8.1%)
    # When > 0: pre threshold = (strong_pre_pivot_pct_atr * ATR14) / pivot_price at the pivot bar (else strong_pre_pivot_pct).
    strong_pre_pivot_pct_atr: float = 0.0
    # Sheet C10 Strong post-pivot bars: K post-drop window + AB Touch Price pullback + AZ:BB maturity lag.
    strong_post_pivot_bars: int = 7
    strong_post_pivot_pct: float = 0.1  # House strong post-pivot move % (10%; prior sheet C15 was 10.8%)
    # Legacy unused: was incorrectly split from C10 for AB pullback. Ignored by sheet-touch path;
    # -v sheet_touch_pullback_bars=X warns and maps to strong_post_pivot_bars unless that key is also set.
    sheet_touch_pullback_bars: int = 7
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
    # WPBR - Pivot Break and Retest (weekly pivot zones, weekly BO, daily retest entry).
    wpbr_zones: bool = False
    wpbr_breakout_confirmation: float = 0.03  # Weekly high > zone_upper * (1 + this)
    wpbr_max_days_after_retest: int = 2  # Entry window after retest bar (inclusive)
    # Daily-retest forward scan mode (matches sheet Daily Retest Row by default):
    #   stop_looking (DEFAULT) - first Low<=upper & Close>upper, but only before the first
    #     bar with Close < zone_lower (sheet abandon-kill window); no prior-close gate.
    #   keep_looking - legacy engine: unbounded scan + prior Close[r-1] >= lower gate.
    wpbr_retest_mode: str = "stop_looking"
    # When True: after a profitable first purchase from a zone, allow exactly one more purchase
    # then retire. When False (default): retire the zone after the first purchase (win or loss).
    wpbr_second_chance_after_win: bool = False
    # When True: merge overlapping WPBR bands into one zone (min low / max high;
    # wpbr_merge_count = member count) before breakout/retest. Default False = sheet parity.
    # Alias: -v merge_overlapping_zones=true
    wpbr_merge_overlapping_zones: bool = False
    # Research-only: persist weekly OHLCV + WPBR zone streams in a sidecar DuckDB
    # (data/wpbr_weekly_zone_cache.duckdb). Default False until parity is proven.
    # Env alias: WPBR_WEEKLY_ZONE_CACHE=1. Does not change trade results when correct.
    wpbr_weekly_zone_cache: bool = False
    wpbr_weekly_zone_cache_db: str = ""  # empty = data/wpbr_weekly_zone_cache.duckdb
    # WPBR incremental resume (default OFF). When True + fingerprint match, seed
    # per-symbol state and advance the bar loop from the prior last bar.
    # Env: WPBR_INCREMENTAL=1. Force cold rebuild: wpbr_incremental_force_full /
    # WPBR_INCREMENTAL_FORCE_FULL=1. State dir: WPBR_incr_state under -o (or
    # wpbr_incremental_state_dir / WPBR_INCREMENTAL_STATE_DIR).
    wpbr_incremental: bool = False
    wpbr_incremental_force_full: bool = False
    wpbr_incremental_state_dir: str = ""
    # Set by main after decide_mode: "" | "full" | "warm" (not a user freeze knob).
    wpbr_incremental_mode: str = ""
    # --- BRT_Like_WPBR (brt_like_wpbr): daily adaptation of the WPBR B/D/E/F package on BRT zones ---
    # Package flag. When False (default): 100% classic BRT (no behavior change). When True: apply the
    # WPBR-like daily rules for B/D/E/F **together** on the existing BRT matured-zone inventory (Z1):
    #   B  retest scan starts on bar c+1 (first session strictly after Stage-2 confirm)
    #   D  hold-above retest (Low <= upper AND Close > upper AND prior Close >= lower)
    #   E  WPBR entry window only (green Close>Open AND Close>upper within max_days_after_retest);
    #      red-to-green / COUNTIF-retest-date are NOT applied on this path (replaced by window).
    #      growth_filter still applies when growth_filter_enabled=true (optional; not forced off).
    #   F  drop C19 (sheet_breakout_scan_start_row_delta) as the retest delay; ignore too-fast (BQ)
    # Stage 1 (Close > upper, strict) + Stage 2 (High > upper*(1+confirm)) breakout and daily
    # strength metrics are always on with the package. Everything NOT in B/D/E/F stays classic BRT
    # (zones, exits, stops, targets, portfolio, sheet-lag maturity, other entry filters).
    brt_like_wpbr: bool = False
    # Stage 2 confirmation: daily High > zone_upper * (1 + this). Only used when brt_like_wpbr=True.
    brt_like_wpbr_confirm_pct: float = 0.03
    # Inclusive entry window (bars) after the retest bar. Only used when brt_like_wpbr=True.
    brt_like_wpbr_max_days_after_retest: int = 2
    # Cap on bars from Stage-1 breakout to Stage-2 confirm (OPEN-C). 0 = unlimited (recommended C1).
    brt_like_wpbr_confirm_max_bars: int = 0
    # Strength (audit-only): pre/post pivot rise window (bars) around the zone band bar.
    brt_like_wpbr_strength_pivot_bars: int = 3
    # Strength (audit-only): prior-extreme lookback in sessions (daily analog of 13 weeks).
    brt_like_wpbr_prior_extreme_bars: int = 65
    # Strength (audit-only): volume-ratio median lookback in sessions.
    brt_like_wpbr_vol_median_bars: int = 20
    # --- VEC (Volume + prior-period Extreme Confluence) ---
    vec_vp_lookback: int = 60  # Trading days for volume-profile POC window.
    vec_vp_bin_pct: float = 0.005  # Histogram bin width as fraction of median price (~0.5%).
    vec_prior_bars: int = 5  # Prior-period length in sessions (5 ≈ prior week on daily bars).
    vec_prior_side: str = "high"  # high | low - extreme to compare against POC (high = resistance retest).
    vec_confluence_pct: float = 0.0075  # Max |POC - extreme| / extreme for confluence (0.75%).
    vec_move_away_pct: float = 0.02  # Min rally above zone center before activation (0 = same bar).
    vec_min_bars_between: int = 20  # Dedup: min bars between activations at similar center.
    # Minervini VCP Stage-2 pivot breakout (new module rocket_minervini_vcp.py).
    # true → MVCP_ prefix; forces isolation from BRT/YH/WPBR/RL/RS in run_minervini_vcp.bat.
    mvcp_mode: bool = False
    mvcp_rs_min_percentile: float = 80.0
    mvcp_rs_lookback: int = 252
    mvcp_sma200_rise_bars: int = 21
    mvcp_min_pct_above_52w_low: float = 0.30
    mvcp_max_pct_below_52w_high: float = 0.25
    mvcp_min_contractions: int = 2
    mvcp_max_contractions: int = 6
    mvcp_swing_k: int = 3
    mvcp_depth_shrink: float = 0.65
    mvcp_max_first_depth: float = 0.40
    mvcp_min_final_depth: float = 0.02
    mvcp_min_base_bars: int = 15
    mvcp_max_base_bars: int = 120
    mvcp_vol_dry_ratio: float = 0.85
    mvcp_vol_dry_soft_confirm: bool = True
    mvcp_require_prior_advance: bool = True
    mvcp_prior_advance_pct: float = 0.20
    mvcp_prior_advance_bars: int = 63
    mvcp_vol_breakout_mult: float = 1.5
    mvcp_max_extension_above_pivot: float = 0.05
    mvcp_stop_eps: float = 0.001
    mvcp_strength_pct: float = 0.25
    mvcp_strength_bars: int = 15
    mvcp_trail_sma: int = 20
    mvcp_trail_arm_pct: float = 0.10
    mvcp_time_stop_bars: int = 10
    mvcp_time_stop_min_gain: float = 0.05
    mvcp_rs_universe: str = "data_dir"  # data_dir | run
    # Qullamaggie HTF / EP proxy (rocket_qull_htf.py). true → QULL_ prefix.
    qull_mode: bool = False
    qull_setup: str = "htf"  # htf | ep | both
    qull_prior_run_bars: int = 42
    qull_prior_run_pct: float = 0.50
    qull_coil_bars: int = 10
    qull_coil_range_pct: float = 0.15
    qull_ema_surf_pct: float = 0.04
    qull_require_ema_surf: bool = True
    qull_vol_dry_ratio: float = 0.85
    qull_vol_dry_soft: bool = True
    qull_vol_breakout_mult: float = 1.5
    qull_min_price: float = 3.0
    qull_min_adv_usd: float = 2_000_000.0
    qull_adv_lookback: int = 20
    qull_market_filter: bool = True
    qull_ep_gap_pct: float = 0.10
    qull_ep_vol_mult: float = 3.0
    qull_ep_require_flat_prior: bool = True
    qull_ep_flat_lookback: int = 63
    qull_ep_flat_max_run_pct: float = 0.30
    qull_stop_under: str = "breakout_low"
    qull_max_stop_adr_mult: float = 1.0
    qull_adr_lookback: int = 20
    qull_trail_ema: int = 10
    qull_partial_days: int = 0
    qull_partial_frac: float = 0.33
    qull_fill: str = "next_open"
    # SMA entry filters (QULL; default OFF)
    qull_require_above_sma50: bool = False
    qull_require_sma50_rising: bool = False
    qull_sma50_slope_bars: int = 10
    qull_require_above_sma20: bool = False
    qull_require_above_sma10: bool = False
    # Volume Zone break->retest (rocket_vz.py / tools/vol_zone_break_retest.py). true → VZ_ prefix.
    vz_mode: bool = False
    vz_lookback_days: int = 126
    vz_retest_window: int = 63
    vz_retest_eps_pct: float = 0.005
    vz_first_retest_only: bool = True
    vz_min_touches_before_entry: int = 1
    # Default next_open = predictive (signal at T close → buy T+1 open). close = EOD fill on signal bar.
    vz_entry_on: str = "next_open"
    vz_zone_kinds: str = "HL"  # comma list; freeze is HL-only
    vz_exit_name: str = "EXIT_atr4_s025_r15_ts20"
    vz_exit_bars: int = 20
    vz_target_r: float = 1.5
    vz_stop_atr_buffer: float = 0.25
    # ATR14/entry*100 gate (FILTER_atr_pct_*); 0 = off. House freeze = 4.0.
    vz_min_atr_pct_at_entry: float = 4.0
    # Research-only: ATR14/trigger_close*100 gate (0 = off). DailyRun stays on entry.
    vz_min_atr_pct_at_trigger: float = 0.0
    # Research-only (0 = off). Wilder RSI(14) on entry-date close; keep if RSI < threshold.
    vz_max_rsi14_at_entry: float = 0.0
    # Research-only (0 = off). Keep if DIST_TO_52W_HIGH_PCT_AT_TRIGGER >= this.
    vz_min_dist_to_52w_high_pct_at_trigger: float = 0.0
    vz_require_hvn_overlap: bool = False  # Step C: knob exists, default OFF (HOLD not adopted)
    vz_sheet_notional: float = 45_000.0
    vz_trade_side: str = "long"  # long | short | both (house default long)
    # Post-TARGET re-entry cooldown (calendar days, inclusive). House adopt 20260821 = 10.
    vz_cooldown_after_target_days: int = 10
    # Research only: write drive/paul_experiments/vz_run_<ts>/ (BASELINE + HTML copies).
    # House / DailyRun / run_vz.bat default OFF — live outputs stay under drive/VZ_* + LatestRun.
    # Opt in: -v vz_write_stamp_folder=true (alias write_stamp_folder) or VZ_WRITE_STAMP_FOLDER=1.
    vz_write_stamp_folder: bool = False
    # WRL — Weekly Range / Swing demand-zone (rocket_wrl.py). true → WRL_ prefix.
    wrl_mode: bool = False
    wrl_target_mode: str = "swing"  # swing (house: 100% at swing high) | range | scale (leftover 50/50)
    wrl_scale_frac: float = 0.50
    wrl_min_zone_pct: float = 0.0
    wrl_min_rr: float = 0.0
    wrl_min_rr_target: str = "range"  # range | swing | primary
    wrl_time_stop_bars: int = 0
    # RSI — Relative Strength Index (rocket_rsi.py). true → RSI_ prefix.
    # Not RS (Relative Strength vs SPY). House freeze: ob=70/os=30/exit=70/max_trigger=60/min_atr%=2.93/ts=20/roll_from_max=8/next_open. min_dist52=off.
    rsi_mode: bool = False
    rsi_ob: float = 70.0
    rsi_os: float = 30.0
    rsi_exit: float = 70.0
    rsi_max_trigger: float = 60.0
    rsi_min_atr_pct: float = 2.93
    rsi_time_stop_days: int = 20
    # EXIT: flatten next open when (in-trade max RSI14 − current) >= this. 0 = off.
    # DailyRun / run_rsi.bat default 8 (preference adopt rsi_roll_ab_20260916).
    rsi_roll_from_max: float = 0.0
    rsi_entry_on: str = "next_open"
    rsi_sheet_notional: float = 10_000.0
    # Optional RSI play-around trigger gates (0 = off). DNA aliases in rocket_rl_config.
    # Column-name -v DIST_TO_52W_HIGH_PCT_AT_TRIGGER= → min (keep if dist >= X).
    # Opposite near-high cap: explicit rsi_max_dist_to_52w_high_pct_at_trigger only.
    rsi_max_dist_to_52w_high_pct_at_trigger: float = 0.0
    rsi_min_dist_to_52w_high_pct_at_trigger: float = 0.0
    rsi_min_rel_vol_on_trigger: float = 0.0
    rsi_min_rsi14_drop_from_ob: float = 0.0
    # StockBee Momentum Burst (rocket_stockbee_burst.py). true → SB_ prefix; isolate peer systems in run_sb.bat.
    sb_mode: bool = False
    burst_min_pct: float = 0.04
    burst_vol_gt_prior: bool = True
    burst_range_lookback: int = 5
    burst_dcr_min: float = 0.70
    burst_max_prior_up_days: int = 1
    burst_fill: str = "next_open"
    burst_max_risk_pct: float = 0.08
    burst_time_stop_days: int = 5
    burst_no_ft_days: int = 3
    burst_mm_gate: bool = False
    burst_mm_min_ratio: float = 2.0
    # Market Monitor membership / liquidity (rocket_stockbee_mm; used when gate ON).
    mm_min_shares: float = 1000.0
    mm_min_adv_usd: float = 250_000.0  # 0 = disable $ filter
    mm_min_price: float = 5.0
    mm_move_pct: float = 0.04
    mm_lookback: int = 10
    mm_force_rebuild: bool = False
    # 2Lynch T−1 narrow/down (“N”); default OFF.
    burst_require_t1_narrow_or_down: bool = False
    burst_t1_narrow_mode: str = "median"  # median | mean | max
    burst_min_price: float = 5.0
    burst_min_adv_usd: float = 0.0
    burst_adv_lookback: int = 20
    burst_size_from_stop: bool = False
    burst_risk_frac: float = 0.01
    # Optional SB trigger-bar gates (0 = off). Applied in rocket_stockbee_burst signal path.
    burst_min_atr_pct_at_trigger: float = 0.0  # ATR14/trigger_close*100 >= this
    burst_max_atr_pct_at_trigger: float = 0.0  # ATR% <= this
    burst_min_dist_to_52w_high_pct: float = 0.0  # % below 52w high >= this
    burst_max_dist_to_52w_high_pct: float = 0.0  # % below 52w high <= this (closer to highs)
    # Vol ≥ k× prior-N avg (exclude signal bar). 0 = off. DNA: VOL_VS_50.
    burst_vol_vs_avg_mult: float = 0.0
    burst_vol_avg_lookback: int = 50
    # SB host dollar-scale (ignored when burst_size_from_stop); blanked on non-SB Audit rows.
    host_dollar_scale: bool = True
    # Optional note when SB run used GOLD_UNIVERSE.csv (blank otherwise).
    sb_gold_universe: str = ""
    # Rocket Launcher (50-SMA dip buy): true/false (separate run from BRT zone/retest).
    # true → RL_ output prefix; AWK math is authoritative (docs/RL_ENGINE_INTEGRATION.md).
    rl_mode: str = "false"
    rl_cash: float = 47_500.0  # RL_CASH notional per trade (AWK default)
    rl_flush_days: int = 0  # Portfolio underwater flush (0=off); two-pass when >0
    rl_watch_min_score: int = 55  # RL_Watchlist minimum setup score (AWK WATCH_MIN_SCORE)
    rl_watch_disable: bool = False  # If true, RL_Watchlist header only
    # --- RL engine params (portfolio_audit.awk 50-trigger; all overridable via -v) ---
    rl_sma_qual: bool = True  # AWK SMA_QUAL
    rl_dip_pct: float = 1.055
    rl_50_sma_lookback: int = 4
    rl_stop_pct: float = 0.934
    rl_stop_anchor: str = "signal_low"  # signal_low | dip_lo | entry_open | sma50 | atr2
    rl_stop_below_pct: float = 0.0  # cushion below dip_lo anchor (research)
    # When > 0 and rl_stop_anchor=entry_open: protective stop = entry × this.
    # Fill gates (too_low / too_high) stay on rl_stop_pct. 0 = use rl_stop_pct (legacy).
    rl_entry_stop_pct: float = 0.0
    # Post-TARGET re-entry window (0 bars = off). Mode is mutually exclusive; see RLConfig.
    rl_post_target_reentry_bars: int = 0
    rl_post_target_reentry_mode: str = "stop_loss"
    rl_post_target_stop_pct: float = 0.0
    rl_post_target_min_stack: float = 0.05
    rl_post_target_under_sma20: float = 0.03
    rl_target_pct: float = 1.20
    # When true: keep expansion hits at rl_target_pct, but do not sell at the moving
    # SMA50 envelope. Recorded target is static entry × rl_target_pct (+20%) until the
    # scale-out, then entry × (1 + rl_entry_target_pct) for the leftover.
    rl_sma_target_off: bool = True
    # Fill: next_open <= signal_low * rl_too_high * rl_stop_pct (0 / off disables; default 0 = off).
    rl_too_high: float = 0.0
    # Research entry gate (0 = off; production and frozen Control unchanged).
    # When bars>0 and pct>0: reject the fill if any of the `bars` completed sessions
    # immediately before the entry date has ABS((Open/prior close)-1)*100 >= pct.
    # The entry day's own opening gap is not included. Short lookback rejects.
    rl_pre_entry_gap_bars: int = 0
    rl_pre_entry_gap_pct: float = 0.0
    # abs (default) | up | down. abs keeps the original absolute-gap rule.
    rl_pre_entry_gap_side: str = "abs"
    # Research entry gate (0 = off). Keep the fill only when
    # ((HIGH - entry) / (HIGH - LOW)) * 100 is at least this percent.
    # HIGH / LOW are the highest daily high and lowest daily low in the
    # rl_retrace_months calendar months strictly before the entry date (default 12).
    # Undefined range rejects.
    rl_min_retrace_12m_pct: float = 0.0
    rl_retrace_months: int = 12
    # Research entry gate (0 = off). Does not turn on Weekly Pivot Break and Retest (WPBR) buys.
    # Reject the next-open fill when a prior WPBR zone's lower edge is above today's
    # 50-day simple moving average, above the fill, and within this fraction of the fill.
    # 0.22 means the lower edge is at most 22% above the Rocket Launcher entry.
    rl_wpbr_overhead_band_pct: float = 0.0
    rl_expansion: float = 1.163
    rl_acc_min: int = 8
    rl_acc_count: int = 10
    rl_expansion_lookback_days: int = 10
    rl_cut_the_losers: float = 1000.0  # OFF — Paul house baseline
    # ATR% band: None = bound off (``-v RL_ATR_LOW=off`` / ``ATR_LOW=off`` / ``RL_ATR_HIGH=off`` / empty).
    # Dual numeric 0/0 also disables the % band; $ cap (rl_atr_high_value) and rl_low_price stay on.
    rl_atr_low_percent: Optional[float] = 0.0244
    rl_atr_high_percent: Optional[float] = 0.0848
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
    rl_exit_percent: float = 0.0  # 0 = time clock off (house freeze 2026-09-27)
    rl_exit_days: int = 0  # trading bars after +% before timed exit (time_counter)
    # Research-only: calendar days after first rl_exit_percent hit (days_diff(arming, today)+1).
    # 0=off. Exit @ open as RL_EXIT_CAL. When >0, ignores trading-bar rl_exit_days timed path.
    # Distinct from rl_max_hold_calendar_days (from entry) and rl_exit_days (trading bars).
    rl_exit_calendar_days: int = 0
    # Research-only hard max-hold from fill bar (trading bars). 0=off.
    # Distinct from rl_exit_days (post-+% clock). Alias: rl_time_stop_from_entry.
    rl_max_hold_bars: int = 0
    # Research-only hard max-hold in calendar days from entry (Closed DAYS HELD clock:
    # days_diff(entry, today) + 1). 0=off. Exit @ open as RL_MAX_HOLD_CAL.
    # Distinct from rl_max_hold_bars (trading bars).
    rl_max_hold_calendar_days: int = 0
    # Leftover target after the 80% sale at +20%. Races the stop (stop first).
    rl_entry_target_pct: float = 0.40
    rl_partial_exit_target: float = 0.0
    rl_partial_exit_percent: float = 0.50
    rl_partial_exit_follow_target: float = 0.1
    rl_scale_ladder: str = "0.20:0.80:0"
    rl_spy_inclusion: bool = False  # AWK SPY_INCLUSION (50>100>200 on entry day)
    rl_avg_vol_days: int = 50  # AWK AVG_VOL_DAYS (0=off)
    rl_vol_pct_threshold: float = 0.0  # AWK VOL_PCT_THRESHOLD (0=off)
    # PIT absolute liquidity: require trigger-bar avg_vol (over rl_avg_vol_days) >= this (shares). 0=off.
    rl_min_avg_vol: float = 0.0
    # PIT absolute liquidity: require trigger-bar volume (TRIGGER_VOL) >= this (shares). 0=off.
    rl_min_trigger_vol: float = 0.0
    # When true, optional BRT entry gates (min_spy_compare_*, growth_filter, etc.) may filter RL entries.
    rl_brt_entry_gates_enabled: bool = False
    # Legacy no-op on DailyRun: charts/deep HTML are via rl_post_run_analysis.py (not in-run).
    # If set true during RL run, write_rl_post_reports only prints a pointer to that script.
    rl_charts: bool = False
    rl_deep_analysis: bool = False
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
    # DI/DW often need several bars - use 60–252 for MSFT-style parity with a multi-day sheet queue.
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
    min_market_cap: float = 0.0  # Require trade market_cap >= this when >0 (0 = no op). None market_cap passes. Applied after enrichment. Audit: MARKET_CAP
    max_market_cap: float = 15130840772900  # Require trade market_cap <= this when >0 (0 = no op). None market_cap passes. Applied after enrichment.
    min_hist_ann_ror_avg: float = -100.0  # Require prior closed trades for symbol and avg ann ROR >= this (-100 = no op). Audit: HIST_ANN_ROR_AVG
    min_avg_volume_10d_at_entry: float = 0.0  # Require AVG_VOLUME_10D_AT_ENTRY >= this when >0 (0 = no op).
    min_atr_pct_at_trigger: float = 0.0  # Require ATR_PCT_AT_TRIGGER (ATR14/trigger_close*100) >= this when >0 (0 = no op).
    max_atr_pct_at_trigger: float = 0.0  # Require ATR_PCT_AT_TRIGGER <= this when >0 (0 = no op).
    # Distance below 52w high at trigger bar close: (max High over 252 bars through trigger - trigger close) / high * 100.
    min_dist_to_52w_high_pct_at_trigger: float = 0.0  # Require DIST >= this when >0 (0 = no op). 0% = at the high.
    max_dist_to_52w_high_pct_at_trigger: float = 0.0  # Require DIST <= this when >0 (0 = no op).
    # Excess total return vs SPY at trigger (SPY_COMPARE_* percentage points); 0 = off.
    # Negative mins are valid (e.g. -12 requires SPY_COMPARE_1Y >= -12). Use 0 or -1000 to disable.
    # NOTE: default 50.0 is a BRT zone-strategy filter. RS mode soft-defaults this to 0
    # (RS already requires all horizons > 0); pass -v min_spy_compare_1y_at_trigger=50 to keep it.
    min_spy_compare_1y_at_trigger: float = 50.0
    max_spy_compare_1y_at_trigger: float = 0.0
    min_spy_compare_2y_at_trigger: float = 0.0
    min_spy_compare_3y_at_trigger: float = 0.0
    # Rolling beta vs SPY at trigger bar (calculated, not yfinance); 0 = off.
    min_beta_at_trigger: float = 0.0
    max_beta_at_trigger: float = 0.0
    # UPPER_WICK_ATR_AT_TRIGGER = (High - max(Open,Close)) / ATR14 at trigger; 0 = off.
    min_upper_wick_atr_at_trigger: float = 0.0
    # Overhead-zone clearance at entry (fraction of current zone high; 0 = off).
    # When >0: take trade if no matured zone above; else require gap > this.
    # gap = (nearest_above_low - current_zone_high) / current_zone_high; reject when gap <= threshold.
    # Nearest above = min matured zone center (lookback_long) whose band does not overlap current
    # (same inventory as zone_above_center / PCT_ENTRY_TO_BOTTOM_ZONE_ABOVE).
    min_zone_above_pct: float = 0.0
    # When True: only take entries with no matured non-overlapping zone above
    # (PCT_ENTRY_TO_BOTTOM_ZONE_ABOVE empty / zone_above_center == 0). Default False.
    # Related but different from min_zone_above_pct (which rejects too-close overhead and keeps empty).
    require_no_zone_above: bool = False
    # Research overlay (off by default): set long target = bottom of nearest matured zone above
    # and long stop = top of nearest matured zone below (same inventory as zone_above/below_center).
    # Missing/invalid side keeps the static target_pct / stop_pct (or trigger_low / ATR) price.
    # Shorts mirror: target = top of zone below; stop = bottom of zone above.
    zone_exits: bool = False
    # Research overlay: same exit rules as zone_exits, but nearest above/below from the *union*
    # of BRT+YH+WPBR+VEC matured zone DNA (computed without flipping entry-system toggles).
    # Pass -v zone_exits_union=true or -v zone_exits=union. Implies exit overlay on.
    zone_exits_union: bool = False
    # Entry gate (0 = off): require (reward_dist / risk_dist) > this, where reward/risk are the
    # absolute distances to the zone target/stop levels above. Missing either side → skip trade.
    # Typically paired with zone_exits=true; gate alone does not change exits.
    zone_rr_min: float = 0.0
    pivot_switch_h_to_l_filter: int = -1  # -1 = no op, 0 = require pivot_switch==False, 1 = require True. Audit: PIVOT_SWITCH_H_TO_L
    # Tri-state (string): true | false | both - matches BRT_Closed ENTRY_MAJOR_PIVOT / IS_20BAR_HIGH_AT_TRIGGER (1/0).
    # ``both`` = no filter. Pass via -v entry_filter_major_pivot=both (or true / false).
    entry_filter_major_pivot: str = "True"  # true => require ENTRY_MAJOR_PIVOT==1; false => ==0
    entry_filter_is_20bar_high_at_trigger: str = "False"  # true => require flag==1; false => ==0 (not at 20-bar high)
    entry_filter_meteoric_rise: str = "both"  # true => HAD_METEORIC_RISE_BEFORE_ENTRY==1; false => ==0
    entry_filter_meteoric_fall: str = "both"  # true => HAD_METEORIC_FALL_BEFORE_ENTRY==1; false => ==0

    # Generic entry engine. "zones" preserves existing BRT/YH/WPBR/VEC behavior.
    # "adx_channel" uses Wilder ADX compression and a next-bar channel stop order.
    entry_mode: str = "zones"
    adx_period: int = 15
    adx_max: float = 20.0
    channel_length: int = 10
    pending_stop_bars: int = 1
    stop_order_gap_fill_at_open: bool = True

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
    # Stop loss base (user-facing): trigger_low = signal/trigger bar Low × stop_pct (sheet AM);
    # entry_open = entry/open × stop_pct; zone_low = zone lower bound × stop_pct.
    # Long side only for trigger_low / zone_low. Legacy alias stop_anchor:
    # signal_low↔trigger_low, entry↔entry_open, zone_low|zone_bottom↔zone_low (still accepted via -v / JSON).
    stop_loss_based: str = "trigger_low"
    stop_anchor: str = "signal_low"  # legacy; kept in sync with stop_loss_based
    # Research high-water trail. 0 = off (today's live stop, no trail).
    # When both are > 0: stop checked on day T uses the high through day T-1.
    # Trail stays off until that high is at least hwm_act_pct percent above entry,
    # then stop = entry + hwm_keep * (high-water mark - entry), never under the
    # base stop already stored on the trade. Entry day cannot sell. DailyRun
    # bats do not pass these. Rocket Launcher also skips its scale ladder.
    hwm_act_pct: float = 0.0
    hwm_keep: float = 0.0
    # If >= 0, round stop comparison prices to this many decimals for stop/gap-stop checks.
    # 2 matches spreadsheet cents-based stop hit checks (default).
    stop_compare_round_decimals: int = 2
    target_pct: float = 1.21  # Multiplier above entry (1.29=29% above)
    # Research partial (off by default; 0 = do not scale). Long only.
    # At entry × (1 + brt_scale_gain), sell brt_scale_sell_frac of the position.
    # The leftover stop moves to entry × (1 + brt_scale_stop_gain) when that is
    # tighter (0 = breakeven). The leftover target becomes entry × (1 + brt_scale_runner_gain).
    # A bar that opens through the original stop still gaps the whole position out.
    # After the sale, the leftover stop is checked before the leftover target.
    brt_scale_gain: float = 0.0
    brt_scale_sell_frac: float = 0.80
    brt_scale_stop_gain: float = 0.0
    brt_scale_runner_gain: float = 0.40
    # False preserves target parameters for reproducibility but disables target exits.
    target_enabled: bool = True
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
    # (1) atr_progress>0 - at first open after (entry_date + atr_days), exit unless High reached
    # entry*(1+atr_progress*ATR_PCT_AT_ENTRY/100) on bars from entry through prior bar.
    # (2) atr_progress==0 - timed flat at that same first open after the deadline.
    atr_progress: float = 0.0
    atr_days: int = 0
    # Portable SB-style exits for BRT/RS/YH host path (0 = off). Same semantics as
    # StockBee burst_no_ft_days / burst_time_stop_days: bars held = i - entry_bar;
    # NO_FT sells at close of fill+N if never Close > entry; TIME sells at close after N bars.
    # Distinct from atr_days (calendar deadline → first open). SB host still uses burst_*.
    no_ft_days: int = 0
    time_stop_days: int = 0
    # WPBR research-only velocity time stop (0 = off). bars_held = i - entry_bar (0 on entry).
    # If High never reaches entry×(1+min_gain) on any bar while held < N, sell at the close of
    # the bar where bars_held first reaches N. Long WPBR only; does not change DailyRun defaults.
    wpbr_velocity_time_stop_bars: int = 0
    wpbr_velocity_time_stop_min_gain: float = 0.10
    # WPBR research-only: at bars_held == N, if Close < entry sell at that close.
    # Checked only on that bar (no later re-check). 0 = off. Long WPBR only.
    wpbr_underwater_time_stop_bars: int = 0
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
    # ATR Chandelier ratchet (research; default OFF). Long: max(High entry..t-1) - k*ATR_N(t-1),
    # never loosens vs prior ratchet or original protective stop. Gap-aware fill like other stops.
    chandelier_enabled: bool = False
    chandelier_atr_period: int = 14  # N ∈ {14, 20} in first-stage grid
    chandelier_atr_mult: float = 3.0  # k ∈ {2.5, 3.5} in first-stage grid
    # Detrended log-price residual z-score exit (research; default OFF). Rolling OLS on last N
    # log closes; robust MAD scale; long exits next open when z < -k at close.
    zscore_exit_enabled: bool = False
    zscore_exit_lookback: int = 40  # N ∈ {20, 40, 60} in first-stage grid
    zscore_exit_k: float = 2.0  # k ∈ {2.0, 2.5} in first-stage grid
    days_per_year: float = 365.0
    # Optional conservative round-trip costs (defaults preserve historical results).
    slippage_bps: float = 0.0  # Charged on both entry and exit notionals.
    commission_per_trade: float = 0.0  # Round-trip dollars per position.
    # Research-only comparability: realize positions at the final close. Default preserves production.
    liquidate_at_end: bool = False

    # Exit: when stop is hit, use close of that bar instead of stop_price (matches some manual conventions)
    exit_at_close_when_stopped: bool = False

    # Growth filter: require full lookback and Close[eval] >= Close[eval - growth_bars] (sheet: 3Y).
    # Sheet anchors 756 rows from 2016-01-01; CSVs may start a few sessions later - see growth_history_slack_bars.
    # Missing lookback Close (short history / IPO / no bar at eval−N): FAIL the gate — do not coerce to $0
    # or treat as pass. Sheet AZ may still PASS when lookback lands on padded $0 OHLC; that is an
    # intentional economics-over-sheet-parity divergence (correct growth confirmation needs a real price).
    # RS mode: when enabled, evaluated on trigger bar T (same timing as SPY_COMPARE / IND_TC), not entry open.
    growth_filter_enabled: bool = True
    growth_bars: int = 756  # e.g. 756 = 3 years; require Close[eval] >= Close[eval - growth_bars]
    growth_history_slack_bars: int = 2  # allow eval when eval_bar >= growth_bars - slack (sheet row vs CSV start)
    # Research gate (0 = off). Require this many sessions before the trigger bar, with a real
    # positive Close exactly that many bars earlier. No slack and no substitute bar. Runs after
    # other entry gates, including standalone WPBR (which otherwise skips the BRT growth filter).
    min_history_bars: int = 0
    # With growth_filter_enabled, require Close[trigger] > Close[trigger - growth_bars] on that
    # exact bar (no slack). Default False keeps the existing >= comparison.
    growth_filter_strict_gt: bool = False
    # Exact-lookback percent hurdle (0 = off). When >0 with growth_filter_enabled, the trigger
    # close must be at least this fraction above the close exactly growth_bars earlier
    # (0.10 = 10%). A gain that lands on the hurdle passes. 0 keeps the strict >0% comparison
    # when growth_filter_strict_gt is on, and does not change that path.
    growth_min_pct: float = 0.0
    # SMA200 persistence (0 = off). When sma200_persist_bars > 0, the trigger bar must have
    # that many sessions ending on the trigger (inclusive), and each of those sessions must
    # have a real positive close and a 200-session simple moving average. A min fraction of
    # 0 still requires the window to exist. A min fraction above 0 also requires at least
    # that share of the window to close strictly above its own SMA200.
    sma200_persist_bars: int = 0
    sma200_persist_min_frac: float = 0.0
    # Research gate (0 = off). On standalone WPBR, reject the entry when any earlier zone
    # has its lower edge strictly above this entry zone's upper edge and that gap is at
    # most this fraction of the upper edge (0.22 = 22%). Does not change the book when 0.
    wpbr_overhead_band_pct: float = 0.0
    # Research only (default False). When True: do not hard-skip on wpbr_overhead_band_pct.
    # Instead, if an earlier WPBR zone sits above this zone, size long target/stop from the
    # nearest overhead gap G (fraction): target gain = wpbr_dyn_oh_target_frac*G, stop under
    # trigger-day low = wpbr_dyn_oh_stop_frac*(target gain). Clear sky (no overhead) keeps
    # cfg target_pct / stop_pct (live 20/8). Applies for every constraining overhead G
    # (including G >= 22%). Production / DailyRun leave this False.
    wpbr_dynamic_overhead: bool = False
    # Fractions used when wpbr_dynamic_overhead is True (research arms A/B/C).
    wpbr_dyn_oh_target_frac: float = 0.90
    wpbr_dyn_oh_stop_frac: float = 0.40

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
    # BM/DI breakout detection (Close vs BI or High vs BI): feeds BY/DW retest simulation only - **not** a buy gate.
    sheet_di_breakout_price: str = "close"  # "close" = sheet BM parity; "high" = legacy intraday highs
    # Require the **eval row** date (same bar as close>open / _eval_bar) in the set of **first BY retest**
    # overlap days (same as column **Retest Date** in BRT_breakout_and_retest CSV - not **Breakout Date**).
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
    # BC multi-zone pick on a long breakout bar (``_sheet_pick_di_breakout_zone_long``):
    # ``max`` = highest crossed zone_upper (sheet MAX / current default); ``min`` = lowest crossed zone_upper.
    breakout_zone_pick: str = "max"
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
    # Universal date window (all zone modes, including YH). Empty = no bound.
    # - entry_start_date: blocks new entries before this date; for WPBR also excludes pivots/
    #   zones whose pivot Monday is before this date (OHLC warmup still loads).
    # - entry_end_date: blocks new entries after this date (inclusive).
    # Independent of sheet_rocket_buy_mode / sheet_start_date.
    # Engine-wide alias: -v start_date= (also data_start / history_start) → entry_start_date.
    entry_start_date: str = ""
    entry_end_date: str = ""
    # Optional hard data cutoff for chronological folds; unlike entry_end_date, bars after this
    # date are removed so open positions cannot leak into later periods.
    backtest_end_date: str = ""
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
    # Relative strength (RS) entry - production DailyRun path via run_rs.bat / --relative-strength / -v rs_mode=true.
    # Timing (locked): evaluate gates on trigger bar T close; fill at bar T+1 open. Never gate on entry bar.
    #   T close: SPY_COMPARE 1Y/2Y/3Y all > 0 AND (if rs_require_tc_strong) IND_TC_*_OUTLOOK all Strong
    #   T+1 open: buy (same stop/target/exit + Closed writers as BRT)
    # Closed IND_TC_* / SPY_COMPARE_* / SMA*_AT_TRIGGER snapshot the trigger bar (T), not the entry open.
    # Skips zone/pivot/retest. Outputs RS_ prefix. SPY.csv required in data dir.
    # Unused in RS mode (ignored safely): band_pct, yh_*/wpbr_*/brt zone pivots, touch_threshold, retest flags.
    relative_strength_enabled: bool = False
    # When True with relative_strength_enabled: require IND_TC_* outlooks all Strong at trigger bar T (not entry).
    rs_require_tc_strong: bool = True
    # RS near-52w-high (O'Neil-style): require Close_T >= high_52w_T * (1 - X) on trigger bar T.
    # X is a fraction (0.15 = within 15% below the 252-bar rolling max High through T).
    # <=0 disables (default). Positive X enables; use a tiny X (e.g. 0.001) to require near/at the high.
    # Related legacy gate (percentage points): max_dist_to_52w_high_pct_at_trigger (15 == X=0.15).
    rs_max_pct_below_52w_high: float = 0.0
    # When True with relative_strength_enabled: require lagged SPY TC outlook != Weak
    # on trigger bar T (allow Strong or Neutral). Uses spy_int_tc_lag (default 1 → outlook[T-1])
    # and spy_tc_weak_horizon (short|int|long; default int). Do not re-check on entry bar T+1.
    rs_spy_int_tc_not_weak: bool = False
    # Shared SPY TC outlook lag in trading sessions. Default 1 = known before open of T
    # (outlook from prior SPY session). lag=0 is same-bar (unsafe for before-open decisions).
    # Production unchanged unless block/exit/rs_spy_int filters are enabled.
    spy_int_tc_lag: int = 1
    # Which SPY IND_TC_*_OUTLOOK the Weak block/exit/rs gates use: short|int|long
    # (aliases: intermediate→int). Default int (backward compatible with *_spy_int_* flags).
    spy_tc_weak_horizon: str = "int"
    # When True: on trigger bar T, block arming a signal if lagged SPY TC outlook is Weak.
    # Evaluated at trigger (not re-checked on entry open T+1). Horizon = spy_tc_weak_horizon.
    block_entries_when_spy_int_weak: bool = False
    # When True: for open positions, on each later trading day D use lag-1 outlook as of D;
    # if that lagged outlook newly turns Weak, exit at D's open
    # (SPY_{SHORT|INT|LONG}_TC_WEAK_EXIT by horizon).
    exit_when_spy_int_turns_weak: bool = False
    # RS-only sell mode (ignored unless relative_strength_enabled). Default "off" = normal
    # target/stop/gap/ATR exits only (also unset/empty/none). See _cfg_sell_breakdown_mode.
    #   off             - current RS exits (no breakdown logic)
    #   breakdown_only  - exit only on RS breakdown OR (SPY OR TC); no stop/target/gap/trailing/ATR
    #                     schedule; END_OF_DATA / liquidate_at_end still apply. Signal at bar close
    #                     (same-bar SPY_COMPARE + stock IND_TC as entry); fill next open.
    #   breakdown_both  - exit only when SPY AND TC breakdown on the same signal bar; same
    #                     schedule restrictions as breakdown_only (no stop/target/gap/trailing/ATR).
    #   breakdown_plus  - normal exits OR breakdown (SPY OR TC), whichever first.
    sell_breakdown: str = "off"
    aggressive: bool = False
    aggressive_margin_interest: float = 0.10
    aggressive_max_multiple: float = 2.0
    aggressive_avg_positions: float = 0.0
    aggressive_sizing_equity_cap: float = 10.0
    # When aggressive: sell existing holdings at new-entry open to free gross/cash.
    # false | average | losers | winners | fifo
    aggressive_sell: str = "false"
    # Fraction of total margin buying power to deploy (equity * aggressive_max_multiple).
    # Default 0.6 = 60% of 2× account. Applies to passive brt_cash / Max_DD sizing only;
    # --aggressive does not change this (aggressive overlay uses full utilization internally).
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
    # When True, append IND_* / IND_*_LAST and IND_ENTRY_* summary columns to BRT_Closed / BRT_Open
    # (see brt_entry_indicators.py), including IND_TC_* horizon outlook fields when populated.
    use_indicators: bool = False
    # Sum IND_SCORE weights for each IND_<id> that is BULL at entry (weights from ind_score_weights.json).
    use_ind_score: bool = True
    ind_score_weights_path: str = ""  # empty = canonical ind_score_weights_<stamp>.json (same file until weights change)
    # Require IND_SCORE >= threshold at entry (price-BULL weights). 0 = filter off.
    min_ind_score: float = 0.0  # Require IND_SCORE >= this at trigger bar close (0 = filter off).
    # Require IND_* states from JSON on the trigger bar. Set path to filename to enable; "" = off.
    mandatory_ind_states_path: str = ""
    # Block entry when IND_* is in a forbidden state from JSON on the trigger bar. "" = off.
    # JSON shape mirrors mandatory: {"rules": {"VOL_SURGE": "BULL"}} or "BULL,BEAR" / ["BULL","BEAR"].
    exclude_ind_states_path: str = ""
    # Entry tri-state using trade-aligned IND counts (bull - bear) at the entry bar open (bar _i_bar+1):
    # off = default (no indicator gate); only = IND-only entry (IND_DIFF >= indicator_diff, no zone/retest/RS);
    # both = zone/retest path + require diff >= indicator_diff and run sheet + programmatic gates.
    indicator_buy: str = "off"
    indicator_diff: int = 10  # Minimum trade-aligned IND_DIFF at trigger bar close (indicator_buy only/both).
    # Upper-bound gate: require trade-aligned IND_DIFF <= N at trigger bar close (None = off).
    # Independent of indicator_buy; useful as a low-DIFF overlay on zone systems (e.g. YH).
    max_ind_diff_at_trigger: Optional[int] = None
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
