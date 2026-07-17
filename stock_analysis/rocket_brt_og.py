    #!/usr/bin/env python3
"""
Rocket BRT: Key Level Interaction Trading System (Python Implementation)

This is the **original** full sheet-parity entry engine (AQ/AK/BG, tight range, consolidation
blocker, etc.). The default `rocket_brt.py` in this folder is a simplified entry fork; use
this module when you need spreadsheet-aligned behavior.

Implements the Rocket BRT system from the specs:
- Level 1: Pivot High/Low detection (k±bars, m confirmation, d displacement)
- Level 2: Market structure (HH/HL/LH/LL, major pivots)
- Level 3: Touch stream, zone bands, touch_threshold maturity, buy signal

Outputs to drive directory:
- BRT_Closed: All closed trades with entry, exit, PnL, etc.
- BRT_Open: Currently held positions
- BRT_Scanner: Symbols that passed entry gates with simulated entry on the last bar of history (no room to
  simulate the trade in-sample); use as candidates for the next session open after that last bar's date.
- BRT_Watchlist: Scanner rows plus pending maturities still open at end of history, with heuristic
  gates_remaining / trigger hints (not a full gate replay).
- BRT_Summary: Stock-by-stock view (trades, PnL total/avg)
- BRT_Report: CSV with settings and metrics (one row of headers, one row of data)

When run with a single stock, optionally generates a chart with bands.
"""
from __future__ import annotations

import argparse
import cProfile
import csv
import json
import math
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Optional, get_origin, get_args, get_type_hints

import numpy as np
import pandas as pd

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
    )

    HAS_EQUITY_METRICS = True
except ImportError:
    _compute_equity_metrics = None  # type: ignore[misc, assignment]
    HAS_EQUITY_METRICS = False

# Optional: Numba JIT for fused sheet ladder inner loop (~large win when installed).
# pip install numba
# Force pure Python: set env BRT_DISABLE_NUMBA_LADDER=1
#
# cache=True: Numba writes compiled LLVM machine code to ~/.cache/numba/ (or NUMBA_CACHE_DIR).
# What is cached: the ladder *kernel* for fixed array dtypes (float64, C-contiguous), not your OHLC
# data or BRT parameters. lag, n_rungs, include_close are ordinary Python/Numba arguments each call;
# they do not require a separate on-disk cache entry per value. If you edit this function's source,
# Numba invalidates/rebuilds that cache entry. Upgrading Numba/LLVM can also force recompile.
_NUMBA_LADDER_AVAILABLE = False
_sheet_ladder_fused_numba_impl = None  # type: ignore[assignment]

try:
    from numba import njit

    @njit(cache=True)
    def _sheet_ladder_fused_numba_impl(
        high_arr: np.ndarray,
        low_arr: np.ndarray,
        close_arr: np.ndarray,
        zl_arr: np.ndarray,
        zh_arr: np.ndarray,
        lag: int,
        n_rungs: int,
        include_close: int,
        de_o: np.ndarray,
        df_o: np.ndarray,
        dg_o: np.ndarray,
        dg_slot_o: np.ndarray,
        de_l: np.ndarray,
        df_l: np.ndarray,
        dg_l: np.ndarray,
        dg_slot_l: np.ndarray,
        de_c: np.ndarray,
        df_c: np.ndarray,
        dg_c: np.ndarray,
        dg_slot_c: np.ndarray,
        ce_out: np.ndarray,
        cf_out: np.ndarray,
        slot_zl_hist: np.ndarray,
        slot_zh_hist: np.ndarray,
        slot_dg_hist: np.ndarray,
    ) -> None:
        n = high_arr.shape[0]
        slots_zl = np.full(n_rungs, np.nan, dtype=np.float64)
        slots_zh = np.full(n_rungs, np.nan, dtype=np.float64)
        slots_dg = np.full(n_rungs, np.nan, dtype=np.float64)
        for i in range(n):
            hi_i = high_arr[i]
            lo_i = low_arr[i]
            if include_close != 0 and i < close_arr.shape[0] and np.isfinite(close_arr[i]):
                px_i = close_arr[i]
            else:
                px_i = np.nan

            if i < lag:
                has_ce = False
                ce_val = np.nan
                cf_val = np.nan
            else:
                ce_val = zl_arr[i - lag]
                cf_val = zh_arr[i - lag]
                has_ce = (
                    np.isfinite(ce_val)
                    and np.isfinite(cf_val)
                    and ce_val > 0.0
                    and cf_val > 0.0
                )

            if has_ce:
                ce_out[i] = ce_val
                cf_out[i] = cf_val
            else:
                ce_out[i] = np.nan
                cf_out[i] = np.nan

            if has_ce:
                for k in range(n_rungs - 1, 0, -1):
                    slots_zl[k] = slots_zl[k - 1]
                    slots_zh[k] = slots_zh[k - 1]
                    slots_dg[k] = slots_dg[k - 1]
                slots_zl[0] = ce_val
                slots_zh[0] = cf_val
                slots_dg[0] = float(i)

            found_o = False
            found_l = False
            if include_close != 0:
                found_c = False
            else:
                found_c = True

            for k in range(n_rungs):
                zl = slots_zl[k]
                zh_ = slots_zh[k]
                if not (np.isfinite(zl) and np.isfinite(zh_)):
                    continue
                if not found_o:
                    if hi_i >= zl and lo_i <= zh_:
                        de_o[i] = zl
                        df_o[i] = zh_
                        dg_o[i] = slots_dg[k]
                        dg_slot_o[i] = float(k + 1)
                        found_o = True
                if not found_l:
                    if lo_i >= zl and lo_i <= zh_:
                        de_l[i] = zl
                        df_l[i] = zh_
                        dg_l[i] = slots_dg[k]
                        dg_slot_l[i] = float(k + 1)
                        found_l = True
                if include_close != 0 and (not found_c):
                    if np.isfinite(px_i) and (px_i >= zl) and (px_i <= zh_):
                        de_c[i] = zl
                        df_c[i] = zh_
                        dg_c[i] = slots_dg[k]
                        dg_slot_c[i] = float(k + 1)
                        found_c = True
                if found_o and found_l and found_c:
                    break

            if not found_o:
                de_o[i] = np.nan
                df_o[i] = np.nan
                dg_o[i] = np.nan
                dg_slot_o[i] = np.nan
            if not found_l:
                de_l[i] = np.nan
                df_l[i] = np.nan
                dg_l[i] = np.nan
                dg_slot_l[i] = np.nan
            if include_close != 0 and (not found_c):
                de_c[i] = np.nan
                df_c[i] = np.nan
                dg_c[i] = np.nan
                dg_slot_c[i] = np.nan

            for k in range(n_rungs):
                slot_zl_hist[i, k] = slots_zl[k]
                slot_zh_hist[i, k] = slots_zh[k]
                slot_dg_hist[i, k] = slots_dg[k]

    _NUMBA_LADDER_AVAILABLE = True
except ImportError:
    pass


def _use_numba_sheet_ladder() -> bool:
    if not _NUMBA_LADDER_AVAILABLE or _sheet_ladder_fused_numba_impl is None:
        return False
    v = os.environ.get("BRT_DISABLE_NUMBA_LADDER", "").strip().lower()
    return v not in ("1", "true", "yes", "on")


# ============== CONFIGURATION ==============
@dataclass
class BRTConfig:
    """Rocket BRT configuration (matches spec).

    Google Sheet cell mapping (STONK_DATA 3.0), when aligning to spreadsheet:
    - C7  → tight_range_threshold_pct (Range Qualifier vs tight range %)
    - C14 → lag used in CD/CE/CF (=INDEX(AF/AG/AH, ROW()-C14)); not the same as strong_pre_pivot_bars / strong_post_pivot_bars
    - C24 → tight_range_lookback (BC window length ending current row)
    - C27 → entry_close_min_range_position (BE: close >= low + (high-low)*C27)
    """
    # Level 1: Pivot Detection (local extrema + displacement confirm)
    pivot_k: int = 4      # Local structure window: ±k bars to identify local high/low
    pivot_d: int = 7      # Displacement confirm window: next d bars to check for price move
    pivot_disp: float = 0.06  # Displacement threshold: 6% move required to confirm pivot
    pivot_m: int = 4      # Dedup lookback: ignore pivots within m bars of same-price prior pivot

    # Level 3: Key levels
    band_pct: float = 0.02  # Zone band ±band_pct (2% default)
    lookback_long: int = 504
    touch_threshold: int = 2  # Sheet STONK_DATA 3.0: zone matures when touch_count_long reaches this (2)
    # Strong Pivot Qualification (STONK_DATA 3.0): pre = lookback-only (realtime-safe); post = follow-through ahead
    strong_pivots_enabled: bool = True  # When True, only strong pivots create zones/touches
    strong_pre_pivot_bars: int = 8  # Sheet "strong Pre-Pivot bars" (C17) — lookback window ending before pivot bar
    strong_pre_pivot_pct: float = 0.1  # Sheet "strong Pre-Pivot move %" (C18)
    strong_post_pivot_bars: int = 7  # Sheet "Strong post-pivot bars"
    strong_post_pivot_pct: float = 0.1  # Sheet "Strong post-pivot move %"
    # "pre" = AE/AD-style lookback only; "post" = legacy forward follow-through; "both" = require pre AND post
    strong_pivot_mode: str = "both"
    # Pending entry window in bars after touch event row (sheet-style current/prior => 1)
    close_above_window: int = 1
    # Safety TTL for pending maturities to prevent very stale zones from lingering forever.
    pending_max_bars: int = 252
    # Entry evaluation mode:
    # - pending: evaluate from pending maturities (legacy behavior)
    # - row_local: sheet-style current/prior touch-event eligibility only
    entry_eval_mode: str = "row_local"
    # row_local behavior: when True, allow evaluating maturity events on the same bar
    # (instead of always deferring maturity_bar==i to next bar).
    row_local_eval_touch_same_bar: bool = False
    # Row-local active-zone context filter:
    # When True, require pending maturity_bar to match the row's active DN context.
    # When False (default), do not hard-skip by active context mismatch; downstream
    # AQ/BG/DP/DO gates decide eligibility from row formulas.
    row_local_require_active_context_match: bool = False
    level_acceptance_window: int = 10  # 7/10 rule: N bars ending on trigger day
    level_acceptance_required: int = 7  # At least this many of last N bars close above trigger low (0=disabled)
    # Support Test (Level Acceptance anchor). When True: require overlap + prior close from above
    # on the current or prior bar; overlap counts only on bars strictly after maturity_bar (the bar
    # where touch_count_long first reaches touch_threshold). When False: skip that anchor (7/10
    # still applies if level_acceptance_required > 0).
    support_test_enabled: bool = True
    # Level Acceptance anchor mode:
    # - strict: require Support Test on current or prior bar
    # - rolling: require at least one Support Test in recent anchor window
    level_acceptance_anchor_mode: str = "strict"
    level_acceptance_anchor_window: int = 10
    breakout_bars: int = 100  # AP: MAX(close over breakout_bars) > active zone upper

    # Tight Range Qualifier: block levels that mature in structurally compressed environments
    tight_range_enabled: bool = True
    tight_range_threshold_pct: float = 0.35  # Sheet C7: RangePct must exceed this (35% default)
    tight_range_lookback: int = 105  # Sheet C24: BC window bars ending on entry-eval row

    # Tradeable Key Level: level must be historically mature AND recently active
    # Legacy / optional; spreadsheet no longer uses Tradeable Key Level (TKL); default off.
    tradeable_key_level_enabled: bool = True
    lookback_short: int = 199  # Short window for touch_count_short (recent engagement)

    # Consolidation Blocker: suppress entries in tight consolidation boxes
    consolidation_blocker_enabled: bool = True
    cb_max_box_width_pct: float = 0.35  # Max allowed (box_ceiling / box_floor - 1) for CB to be active. use 9999 for no limit

    # Touch count filters at entry: gate by TC and TC_MIN (None = no filter)
    min_touch_count: Optional[int] = 0  # Require touch_count >= N (0 = no op). Audit: TOUCH_COUNT
    max_touch_count_minor: Optional[int] = 100  # Require touch_count_minor <= N (e.g. 1 for TC_MIN <= 1)
    # Entry filters (minimums; no-op when at default)
    min_pivot_run_l_before_entry: int = 0  # Require pivot_run_low >= this (0 = no op). Audit: PIVOT_RUN_L_BEFORE_ENTRY
    min_pivot_run_h_before_entry: int = 0  # Require pivot_run_high >= this (0 = no op). Audit: PIVOT_RUN_H_BEFORE_ENTRY
    min_rel_vol_at_entry: float = -2.0  # Require rel_vol_at_entry >= this (-2 = no op). Audit: REL_VOL_AT_ENTRY
    min_market_cap: float = 0.0  # Require trade market_cap >= this (0 = no op). Applied after enrichment. Audit: MARKET_CAP
    min_hist_ann_ror_avg: float = -100.0  # Require symbol hist ann ROR avg >= this (-100 = no op). Audit: HIST_ANN_ROR_AVG
    pivot_switch_h_to_l_filter: int = -1  # -1 = no op, 0 = require pivot_switch==False, 1 = require True. Audit: PIVOT_SWITCH_H_TO_L
    # Tri-state (string): true | false | both — matches BRT_Closed ENTRY_MAJOR_PIVOT / IS_20BAR_HIGH_AT_TRIGGER (1/0).
    # ``both`` = no filter. Pass via -v entry_filter_major_pivot=both (or true / false).
    entry_filter_major_pivot: str = "True"  # true => require ENTRY_MAJOR_PIVOT==1; false => ==0
    entry_filter_is_20bar_high_at_trigger: str = "False"  # true => require flag==1; false => ==0 (not at 20-bar high)

    # Risk
    brt_cash: float = 47500
    initial_capital: float = 500000
    stop_pct: float = 0.934  # If stop_pct_is_multiplier=False: fraction below (0.066=6.6%); else multiplier (0.934)
    stop_pct_is_multiplier: bool = True  # True: stop=low*stop_pct (0.934). False: stop=low*(1-stop_pct) per PO
    # If >= 0, round stop comparison prices to this many decimals for stop/gap-stop checks.
    # Example: 2 matches spreadsheet cents-based stop hit checks.
    stop_compare_round_decimals: int = 2
    target_pct: float = 1.22  # Multiplier above entry (1.29=29% above)
    # ATR-based stop/target:=AND($DE8<>"",ROW()>$DG8)=AND($DE8<>"",ROW()>$DG8) when BOTH stop_pct and target_pct are 0, use these instead
    atr_target: float = 2   # 0=use target_pct. Non-zero: target = entry * (1 + ATR_PCT_AT_ENTRY * atr_target / 100)
    atr_stop: float = 1.4     # 0=use stop_pct. Non-zero: stop = entry * (1 - ATR_PCT_AT_ENTRY * atr_stop / 100)
    atr_increment: float = 5.8  # 0=no trailing. Non-zero: for every atr_increment% gain, raise stop by 1% of entry
    days_per_year: float = 365.0

    # Exit: when stop is hit, use close of that bar instead of stop_price (matches some manual conventions)
    exit_at_close_when_stopped: bool = False

    # Growth filter: single check at entry — price today >= price growth_bars days ago (sheet: 3Y); if no history, don't buy
    growth_filter_enabled: bool = True
    growth_bars: int = 756  # e.g. 756 = 3 years; require Close[entry] >= Close[entry - growth_bars]

    # Entry candle BE: after close > open, optionally require close in upper part of the bar.
    # Sheet C27 default 1e-7: AND(H>E, H>=G+(F-G)*C27) => (close-low)/(high-low) >= C27 (effectively above the low).
    # 0 = skip this check (bullish only). 0.5 = close in upper half: (close-low)/(high-low) >= 0.5.
    entry_close_min_range_position: float = 0.00001
    # Sheet zone parity: round pivot touch prices before zone/ladder math (-1 disables rounding).
    zone_price_round_decimals: int = 2
    # Sheet overlap parity: round OHLC and zone bounds before overlap/support/resistance checks.
    # Example: 2 means low=3.3867 and zone_high=3.3864 compare as 3.39 <= 3.39.
    zone_compare_round_decimals: int = 2

    # --- Sheet zone ladder (DE / DF / DG) parity ---
    # CE/CF come from INDEX(AG/AH, ROW()-C14); ladder CG..DC shifts when CE is non-empty (see unused_columns_scan.py).
    sheet_maturity_lag_bars: int = 7  # Spreadsheet C14 (lag for CD/CE/CF mature columns)
    # Sheet-style ladder depth:
    # - >0: fixed rung count (legacy default was 8)
    # - 0: auto-expand to lookback_long (keeps sheet-style ordering, larger memory)
    sheet_zone_ladder_rungs: int = 0  # 0 => use lookback_long
    # When True and entry_eval_mode=row_local: active zone = first overlapping ladder rung (DE/DF/DG), not pending overlap heuristic.
    use_sheet_ladder_active_zone: bool = False
    # When True, AK/AQ/BG gates use per-row active DE/DF/DG zone context (sheet-style),
    # rather than the pending candidate's static zone bounds.
    sheet_active_zone_gates: bool = True
    # Optional as-of lag for active zone context in AQ/BG (DL/DM/DN-style):
    # use DE/DF/DG from (row - lag) and require row - DG[row-lag] >= lag.
    # 0 disables and uses current-row DE/DF/DG directly.
    sheet_active_zone_asof_lag_bars: int = 7
    # Additional constant adjustment for as-of availability age:
    # spreadsheet gating is based on Excel ROW() (not the same coordinate system as python bar index).
    # When >0, it effectively makes a zone become "available" earlier by this many bars.
    sheet_active_zone_asof_age_adjust_bars: int = 7
    # When True, AQ/BG evidence "same zone context" uses dg_slot identity when available.
    # When expanding ladder depth beyond the legacy 8 rungs, dg_slot can shift as the ladder shifts,
    # so bounds-only identity is usually safer for parity with sheet logic that uses CE/CF bounds.
    sheet_use_dg_slot_for_zone_identity: bool = False
    # --- Sheet DO / DP parity gates ---
    # DO parity: recent pre-only strong pivot touch must exist within N rows (C30-style "pre-touch good for").
    do_gate_enabled: bool = True
    do_good_for_bars: int = 3
    # DP parity: current price must be inside ANY matured zone CE/CF in [row-C10 .. row-C14].
    # Uses sheet_maturity_lag_bars as C14 and (by default) lookback_long as C10.
    dp_gate_enabled: bool = True
    dp_window_bars: int = 0  # 0 => use lookback_long
    dp_good_for_bars: int = 2
    # Sheet AW parity ("magic touch event"):
    # When enabled, maturity/touch events are generated from AR/AW semantics:
    # - CD = lagged confirmed touch price (post-confirmed strong pivot) by sheet_maturity_lag_bars
    # - AR[t] = count of CD in [DE[t], DF[t]] over last sheet_magic_touch_window_bars
    # - AW[t] = (AR[t] >= touch_threshold) AND (AR[t-1] < touch_threshold OR active zone changed)
    sheet_magic_touch_enabled: bool = True
    sheet_magic_touch_window_bars: int = 0  # 0 => use lookback_long (e.g. 503)

    # Rolling Average Displacement filter: require price sufficiently away from recent average (avoid stuck/equilibrium)
    displacement_filter_enabled: bool = False
    displacement_rolling_bars: int = 100  # Rolling window for average of closes
    displacement_threshold_pct: float = 0.1 # Min displacement: ABS(Close/RollingAvg100 - 1) >= this (e.g. 0.10 = 10%)

    # Metrics: when True, compute Max_Drawdown etc. via equity reconstruction (BRT_DrawdownCalc)
    compute_equity_metrics: bool = True
    aggressive: bool = False
    aggressive_margin_interest: float = 0.10
    aggressive_max_multiple: float = 2.0
    aggressive_avg_positions: float = 0.0

    # When True, record maturities rejected only by growth/tight_range/consolidation to BRT_WouldHave CSV (for DrawdownCalc zone chart)
    emit_would_have: bool = False

    # Real-time predictive filter (offline analysis / optional gating at entry)
    realtime_filter_enabled: bool = False
    realtime_filter_threshold: float = 0  # Sum of weighted metrics must be >= this to allow entry
    realtime_filter_use_zscore: bool = True  # If True and BRT_ReferenceStats.csv exists, weight z-scores so scale of metrics doesn't dominate
    # Per-metric weights (typically set from correlation r or R_Total; use with z-score normalization so scale of metrics doesn't dominate)
    #weight_zone_cluster_density: float = -0.0724
    #weight_nearby_zones_above: float = -0.0655
    #weight_touch_count_major: float = 0.0620
    #weight_pct_entry_to_bottom_zone_above: float = 0.0545
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

    def to_dict(self) -> dict[str, Any]:
        return {
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
            "BRT_STOP_PCT_IS_MULTIPLIER": self.stop_pct_is_multiplier,
            "BRT_TARGET_PCT": self.target_pct,
            "EXIT_AT_CLOSE_WHEN_STOPPED": self.exit_at_close_when_stopped,
        }


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


def _near(a: float, b: float, eps: float = _PIVOT_DEDUP_EPS) -> bool:
    """Price within ±eps: abs(a/b - 1) <= eps."""
    if b == 0:
        return a == 0
    return abs(a / b - 1.0) <= eps


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
) -> bool:
    """Return True if strong_pivot_mode is configured with positive bars/pct for that mode."""
    m = (mode or "pre").strip().lower()
    if m == "pre":
        return pre_bars > 0 and pre_pct > 0
    if m == "post":
        return post_bars > 0 and post_pct > 0
    if m == "both":
        return (pre_bars > 0 and pre_pct > 0) and (post_bars > 0 and post_pct > 0)
    # Unknown mode: treat like pre
    return pre_bars > 0 and pre_pct > 0


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
    return pre_ok


# ============== LEVEL 3: TOUCH STREAM & 6TH-TOUCH MATURITY ==============
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
    strong_pre_pivot_pct: float = 0.12,
    strong_post_pivot_bars: int = 7,
    strong_post_pivot_pct: float = 0.09,
    strong_pivot_mode: str = "pre",
    zone_price_round_decimals: int = 2,
    debug_symbol: Optional[str] = None,
    realtime_filter_enabled: bool = False,
) -> dict:
    """
    Touch stream: touchPrice = high if pivotHigh else low if pivotLow else null.
    Zone band per touch. Long-memory touch count. Maturity when touch_count_long >= touch_threshold (default 2, sheet).
    Tradeable Key Level (TKL, optional): touch_count_long >= touch_threshold AND touch_count_short >= 2.
    Not used in the current spreadsheet; kept for optional gating only.

    Strong Pivot Qualification (when strong_pivots_enabled=True and not realtime_filter_enabled):
    - Pre (sheet AE/AD): lookback-only on prior strong_pre_pivot_bars bars vs strong_pre_pivot_pct
    - Post: follow-through over the next strong_post_pivot_bars bars vs strong_post_pivot_pct
    - strong_pivot_mode: "pre" | "post" | "both"
    Only strong pivots create touch events; weak pivots are ignored for zone/touch counting.
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
    hi_arr = df["High"].values
    lo_arr = df["Low"].values
    close_arr = df["Close"].values

    tp_arr = np.full(n, np.nan, dtype=np.float64)
    
    # Debug: get date index for logging
    debug_mode = debug_symbol is not None and _DEBUG_SYMBOL == debug_symbol
    date_index = df.index.astype(str).tolist() if debug_mode else []

    # Strong Pivot Qualification: filter pivots per strong_pivot_mode (pre/post/both)
    if realtime_filter_enabled:
        # Real-time mode: no strong filter; all pivots create touch events
        tp_arr[ph_arr] = hi_arr[ph_arr]
        tp_arr[pl_arr] = lo_arr[pl_arr]
    elif strong_pivots_enabled and _strong_pivot_mode_has_active_params(
        strong_pivot_mode, strong_pre_pivot_bars, strong_pre_pivot_pct, strong_post_pivot_bars, strong_post_pivot_pct
    ):
        for t in range(n):
            if ph_arr[t]:
                pivot_price = hi_arr[t]
                is_strong = _strong_pivot_bar_ok(
                    t, "PH", hi_arr, lo_arr, n,
                    pre_bars=strong_pre_pivot_bars,
                    pre_pct=strong_pre_pivot_pct,
                    post_bars=strong_post_pivot_bars,
                    post_pct=strong_post_pivot_pct,
                    mode=strong_pivot_mode,
                )
                if is_strong:
                    tp_arr[t] = pivot_price  # Strong pivot high
                if debug_mode and _DEBUG_DATE and date_index[t][:10] >= "2021-01-01" and date_index[t][:10] <= "2022-08-01":
                    print(f"[DEBUG] {debug_symbol} bar {t} ({date_index[t][:10]}): PIVOT_HIGH @ ${pivot_price:.2f}, strong={is_strong} mode={strong_pivot_mode!r}")
            if pl_arr[t]:
                pivot_price = lo_arr[t]
                is_strong = _strong_pivot_bar_ok(
                    t, "PL", hi_arr, lo_arr, n,
                    pre_bars=strong_pre_pivot_bars,
                    pre_pct=strong_pre_pivot_pct,
                    post_bars=strong_post_pivot_bars,
                    post_pct=strong_post_pivot_pct,
                    mode=strong_pivot_mode,
                )
                if is_strong:
                    tp_arr[t] = pivot_price  # Strong pivot low
                if debug_mode and _DEBUG_DATE and date_index[t][:10] >= "2021-01-01" and date_index[t][:10] <= "2022-08-01":
                    print(f"[DEBUG] {debug_symbol} bar {t} ({date_index[t][:10]}): PIVOT_LOW @ ${pivot_price:.2f}, strong={is_strong} mode={strong_pivot_mode!r}")
    else:
        # Legacy mode: all pivots create touch events
        tp_arr[ph_arr] = hi_arr[ph_arr]
        tp_arr[pl_arr] = lo_arr[pl_arr]

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
        zl = tp * (1 - band_pct)
        zh = tp * (1 + band_pct)
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
    # A zone matures when tc crosses threshold. Only suppress if SAME zone existed
    # on previous bar with tc >= threshold (to avoid re-maturing the same zone).
    # When previous bar has a DIFFERENT zone (or no zone), this bar's zone matures if tc >= threshold.
    same_zone = np.isclose(zc_arr, prev_zc, rtol=1e-9, equal_nan=False)
    matured_arr = (tc_long_arr >= touch_threshold) & (
        (prev_tc < touch_threshold) | ~same_zone | np.isnan(prev_zc)
    )
    # TKL = Tradeable Key Level: historically mature AND recently active
    tkl_arr = (tc_long_arr >= touch_threshold) & (tc_short_arr >= 2)
    short_candidate_arr = matured_arr & (close_arr <= zc_arr)
    short_candidate_arr = np.where(np.isnan(zc_arr), False, short_candidate_arr)
    
    # Debug: log maturity events
    if debug_mode and _DEBUG_DATE:
        matured_idxs = np.where(matured_arr)[0]
        for mi in matured_idxs:
            if date_index[mi][:10] >= "2021-01-01" and date_index[mi][:10] <= "2022-08-10":
                print(f"[DEBUG] {debug_symbol} bar {mi} ({date_index[mi][:10]}): ZONE MATURED! "
                      f"zone=${zc_arr[mi]:.2f}, tc_long={tc_long_arr[mi]}, prev_tc={prev_tc[mi]}, "
                      f"threshold={touch_threshold}")

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
    }


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
    touch_count: int = 0
    touch_count_short: int = 0
    touch_count_major: int = 0
    touch_count_minor: int = 0
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
    # Trace (for 5/23 vs 5/27 debugging): 6th touch bar, close-above bar
    maturity_date: str = ""
    close_above_date: str = ""
    max_price: float = 0.0  # Max High during hold (for BRT_Closed)
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
    # 14-day ATR at entry bar (day of entering the trade)
    atr_14_at_entry: Optional[float] = None
    # Per-trigger-bar technical metrics (computed without future bars, for correlation analysis)
    z_score_at_trigger: float = 0.0
    upper_wick_atr_at_trigger: float = 0.0
    # Lower wick size (min(open,close)-low) as multiple of ATR at trigger bar; can indicate rejection of lows / buying pressure
    lower_wick_atr_at_trigger: float = 0.0
    is_20bar_high_at_trigger: int = 0
    is_20bar_low_at_trigger: int = 0
    move_body_atr_at_trigger: float = 0.0
    # Enriched from yfinance (at report time): market_cap, sector, industry, beta
    market_cap: Optional[float] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    beta: Optional[float] = None
    # Rolling beta vs benchmark (e.g. SPY) over window ending at entry date; computed when benchmark_df provided
    beta_at_entry: Optional[float] = None
    # Sheet 8-rung ladder (CG..DC): at close_above signal bar, which rung (1-8) holds this trade's zone.
    # 9 = zone not on any rung (aged off / not in sheet memory). 0 = unavailable.
    sheet_ladder_rung_at_signal: int = 0

# Default benchmark and window for point-in-time beta at entry
_BETA_BENCHMARK_TICKER = "SPY"
# Per-process cache: _load_benchmark_local hits this so parallel workers load SPY.csv once per process (~6 loads vs ~N symbols).
_BENCHMARK_CSV_CACHE: dict[str, Optional[pd.DataFrame]] = {}
_BETA_ROLLING_WINDOW = 252  # trading days (~1 year)


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


def _compute_sheet_ladder_de_df_dg_all_modes(
    high_arr: np.ndarray,
    low_arr: np.ndarray,
    close_arr: Optional[np.ndarray],
    zl_arr: np.ndarray,
    zh_arr: np.ndarray,
    c14: int,
    n_rungs: int = 8,
    *,
    include_close_membership: bool = True,
) -> tuple[dict[str, Any], dict[str, Any], Optional[dict[str, Any]]]:
    """
    Single-pass zone ladder: overlap, low-membership, and optionally close-membership DE/DF/DG streams.

    Same semantics as three independent calls to the legacy single-mode builder, but one
    slot update and one slot histogram write per bar (dominant cost in profiling).

    ``include_close_membership=False`` skips the close stream (used for sheet parity / diagnostics
    only in BRT backtest — overlap + low drive AR/AW and AK/AQ/BG). Saves inner-loop work and memory.
    """
    n = len(high_arr)
    de_o = np.full(n, np.nan, dtype=np.float64)
    df_o = np.full(n, np.nan, dtype=np.float64)
    dg_o = np.full(n, np.nan, dtype=np.float64)
    dg_slot_o = np.full(n, np.nan, dtype=np.float64)
    de_l = np.full(n, np.nan, dtype=np.float64)
    df_l = np.full(n, np.nan, dtype=np.float64)
    dg_l = np.full(n, np.nan, dtype=np.float64)
    dg_slot_l = np.full(n, np.nan, dtype=np.float64)
    if include_close_membership:
        de_c = np.full(n, np.nan, dtype=np.float64)
        df_c = np.full(n, np.nan, dtype=np.float64)
        dg_c = np.full(n, np.nan, dtype=np.float64)
        dg_slot_c = np.full(n, np.nan, dtype=np.float64)
    else:
        de_c = df_c = dg_c = dg_slot_c = None  # type: ignore[assignment]
    ce_out = np.full(n, np.nan, dtype=np.float64)
    cf_out = np.full(n, np.nan, dtype=np.float64)
    slot_zl_hist = np.full((n, n_rungs), np.nan, dtype=np.float64)
    slot_zh_hist = np.full((n, n_rungs), np.nan, dtype=np.float64)
    slot_dg_hist = np.full((n, n_rungs), np.nan, dtype=np.float64)

    lag = max(0, int(c14))
    nr_i = int(n_rungs)

    if _use_numba_sheet_ladder():
        ha = np.ascontiguousarray(high_arr, dtype=np.float64)
        la = np.ascontiguousarray(low_arr, dtype=np.float64)
        za = np.ascontiguousarray(zl_arr, dtype=np.float64)
        zha = np.ascontiguousarray(zh_arr, dtype=np.float64)
        if close_arr is not None and len(close_arr) >= n:
            ca = np.ascontiguousarray(close_arr, dtype=np.float64)
        else:
            ca = np.full(n, np.nan, dtype=np.float64)
        if include_close_membership and de_c is not None:
            dc_b = de_c
            dfc_b = df_c
            dgc_b = dg_c
            dgslc_b = dg_slot_c
        else:
            dc_b = np.full(n, np.nan, dtype=np.float64)
            dfc_b = np.full(n, np.nan, dtype=np.float64)
            dgc_b = np.full(n, np.nan, dtype=np.float64)
            dgslc_b = np.full(n, np.nan, dtype=np.float64)
        _sheet_ladder_fused_numba_impl(
            ha,
            la,
            ca,
            za,
            zha,
            lag,
            nr_i,
            1 if include_close_membership else 0,
            de_o,
            df_o,
            dg_o,
            dg_slot_o,
            de_l,
            df_l,
            dg_l,
            dg_slot_l,
            dc_b,
            dfc_b,
            dgc_b,
            dgslc_b,
            ce_out,
            cf_out,
            slot_zl_hist,
            slot_zh_hist,
            slot_dg_hist,
        )
    else:
        slots_zl = np.full(n_rungs, np.nan, dtype=np.float64)
        slots_zh = np.full(n_rungs, np.nan, dtype=np.float64)
        slots_dg = np.full(n_rungs, np.nan, dtype=np.float64)
        for i in range(n):
            hi_i = float(high_arr[i])
            lo_i = float(low_arr[i])
            px_i = (
                float(close_arr[i])
                if include_close_membership and close_arr is not None and i < len(close_arr) and np.isfinite(close_arr[i])
                else np.nan
            )

            if i < lag:
                has_ce = False
                ce_val = cf_val = np.nan
            else:
                ce_val = float(zl_arr[i - lag])
                cf_val = float(zh_arr[i - lag])
                has_ce = np.isfinite(ce_val) and np.isfinite(cf_val) and ce_val > 0 and cf_val > 0

            ce_out[i] = ce_val if has_ce else np.nan
            cf_out[i] = cf_val if has_ce else np.nan

            if has_ce:
                for k in range(n_rungs - 1, 0, -1):
                    slots_zl[k] = slots_zl[k - 1]
                    slots_zh[k] = slots_zh[k - 1]
                    slots_dg[k] = slots_dg[k - 1]
                slots_zl[0] = ce_val
                slots_zh[0] = cf_val
                slots_dg[0] = float(i)

            found_o = found_l = False
            found_c = False if include_close_membership else True
            for k in range(n_rungs):
                zl = slots_zl[k]
                zh_ = slots_zh[k]
                if not (np.isfinite(zl) and np.isfinite(zh_)):
                    continue
                if not found_o:
                    if hi_i >= zl and lo_i <= zh_:
                        de_o[i] = zl
                        df_o[i] = zh_
                        dg_o[i] = slots_dg[k]
                        dg_slot_o[i] = float(k + 1)
                        found_o = True
                if not found_l:
                    if lo_i >= zl and lo_i <= zh_:
                        de_l[i] = zl
                        df_l[i] = zh_
                        dg_l[i] = slots_dg[k]
                        dg_slot_l[i] = float(k + 1)
                        found_l = True
                if include_close_membership and de_c is not None and not found_c:
                    if np.isfinite(px_i) and (px_i >= zl and px_i <= zh_):
                        de_c[i] = zl
                        df_c[i] = zh_
                        dg_c[i] = slots_dg[k]
                        dg_slot_c[i] = float(k + 1)
                        found_c = True
                if found_o and found_l and found_c:
                    break
            if not found_o:
                de_o[i] = df_o[i] = dg_o[i] = dg_slot_o[i] = np.nan
            if not found_l:
                de_l[i] = df_l[i] = dg_l[i] = dg_slot_l[i] = np.nan
            if include_close_membership and de_c is not None and not found_c:
                de_c[i] = df_c[i] = dg_c[i] = dg_slot_c[i] = np.nan

            for k in range(n_rungs):
                slot_zl_hist[i, k] = slots_zl[k]
                slot_zh_hist[i, k] = slots_zh[k]
                slot_dg_hist[i, k] = slots_dg[k]

    c14_f = float(lag)
    nr = int(n_rungs)

    def _pack(de: np.ndarray, df: np.ndarray, dg: np.ndarray, dg_slot: np.ndarray) -> dict[str, Any]:
        return {
            "de": de,
            "df": df,
            "dg": dg,
            "dg_slot": dg_slot,
            "ce": ce_out,
            "cf": cf_out,
            "c14": c14_f,
            "slot_zl_hist": slot_zl_hist,
            "slot_zh_hist": slot_zh_hist,
            "slot_dg_hist": slot_dg_hist,
            "n_rungs": nr,
        }

    pack_o = _pack(de_o, df_o, dg_o, dg_slot_o)
    pack_l = _pack(de_l, df_l, dg_l, dg_slot_l)
    if include_close_membership and de_c is not None:
        pack_c: Optional[dict[str, Any]] = _pack(de_c, df_c, dg_c, dg_slot_c)
    else:
        pack_c = None
    return pack_o, pack_l, pack_c


def _compute_sheet_ladder_de_df_dg(
    high_arr: np.ndarray,
    low_arr: np.ndarray,
    close_arr: Optional[np.ndarray],
    zl_arr: np.ndarray,
    zh_arr: np.ndarray,
    c14: int,
    n_rungs: int = 8,
    active_match_mode: str = "overlap",
) -> dict[str, Any]:
    """
    Replicate STONK_DATA zone ladder (CG..DC) and active zone columns DE/DF/DG.

    CE/CF: INDEX(AG/AH, ROW()-C14) -> here zl_arr[i-c14], zh_arr[i-c14] when i >= c14 (0-based bars).
    When CE is finite: push new zone into rung 0; shift older rungs down (see sheet lines 83-106).
    DE/DF/DG: first rung k (in order) where the bar matches the zone by mode:
    - overlap: High >= zl_k AND Low <= zh_k
    - close:   Close in [zl_k, zh_k] (requires close_arr)
    - low:     Low in [zl_k, zh_k]   (sheet DE FILTER uses G vs CE/CF)
    DF/DG: upper bound and maturity bar index (0-based) stored with that rung (sheet CI/CL/..).

    Returns dict with float arrays de, df, dg (NaN when empty), dg_slot (1..n_rungs or NaN),
    plus ce, cf (lagged zone bounds per bar) for export.

    Implementation delegates to the fused all-modes builder and selects one stream (same outputs
    as a standalone single-mode pass).
    """
    mode = str(active_match_mode or "overlap").strip().lower()
    o, l, c = _compute_sheet_ladder_de_df_dg_all_modes(
        high_arr,
        low_arr,
        close_arr,
        zl_arr,
        zh_arr,
        c14,
        n_rungs=n_rungs,
        include_close_membership=(mode == "close"),
    )
    if mode == "low":
        return l
    if mode == "close":
        if c is None:
            raise RuntimeError("close ladder requested but include_close_membership was False")
        return c
    return o


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


def report_trades_vs_sheet_ladder_rungs(
    sym: str,
    closed: list[BRTTrade],
    index_iso: list[str],
    ladder: dict[str, Any],
    band_pct: float,
    zone_tol_pct: float = 0.0001,
) -> tuple[int, int, list[dict[str, Any]]]:
    """
    For each closed trade, at the **signal bar** (close_above_date = bullish close that passed gates),
    check whether the trade's **maturity bar** (and zone bounds) appears in any of the **8** Excel ladder rungs.

    If the zone has "fallen off" the ladder or Python never pushed it into CE, it will **not** match any rung.

    Returns (count_not_on_any_rung, total_analyzed, row dicts for CSV).
    """
    slot_dg = ladder.get("slot_dg_hist")
    slot_zl = ladder.get("slot_zl_hist")
    slot_zh = ladder.get("slot_zh_hist")
    de_arr = ladder.get("de")
    dg_active = ladder.get("dg")
    n_rungs = int(ladder.get("n_rungs", 8))
    if slot_dg is None or slot_zl is None or slot_zh is None:
        return 0, 0, []

    rows: list[dict[str, Any]] = []
    not_on = 0
    total = 0

    for t in closed:
        if t.symbol.upper() != sym.upper():
            continue
        total += 1
        i_sig = _trade_ymd_to_bar_index(index_iso, t.close_above_date)
        mb = _trade_ymd_to_bar_index(index_iso, t.maturity_date)
        zc = float(t.zone_center) if t.zone_center else 0.0
        trade_zl = zc * (1.0 - band_pct) if zc > 0 else float("nan")
        trade_zh = zc * (1.0 + band_pct) if zc > 0 else float("nan")

        row: dict[str, Any] = {
            "SYMBOL": sym,
            "DATE_OPENED": t.date_opened,
            "MATURITY_DATE": t.maturity_date,
            "CLOSE_ABOVE_DATE": t.close_above_date,
            "MATURITY_BAR": mb if mb is not None else "",
            "SIGNAL_BAR": i_sig if i_sig is not None else "",
            "ZONE_CENTER": zc,
        }

        if i_sig is None or mb is None or i_sig < 0 or i_sig >= slot_dg.shape[0]:
            row["ON_ANY_OF_8_RUNGS"] = "UNKNOWN"
            row["MATCH_RUNG"] = ""
            row["NOTES"] = "bad_date_parse_or_range"
            rows.append(row)
            not_on += 1
            continue

        tol = max(zone_tol_pct, 1e-9) * max(abs(trade_zl), 1.0)

        matched_rung: Optional[int] = None
        match_how = ""
        for k in range(min(n_rungs, slot_dg.shape[1])):
            dg_k = slot_dg[i_sig, k]
            zlk = slot_zl[i_sig, k]
            zhk = slot_zh[i_sig, k]
            if not np.isfinite(dg_k):
                continue
            if int(round(float(dg_k))) == int(mb):
                matched_rung = k + 1
                match_how = "maturity_bar"
                break
            if np.isfinite(zlk) and np.isfinite(zhk) and np.isfinite(trade_zl):
                if abs(zlk - trade_zl) <= tol and abs(zhk - trade_zh) <= tol:
                    matched_rung = k + 1
                    match_how = "zone_bounds"
                    break

        de_here = float(de_arr[i_sig]) if de_arr is not None and i_sig < len(de_arr) else float("nan")
        dg_here = float(dg_active[i_sig]) if dg_active is not None and i_sig < len(dg_active) else float("nan")

        row["DE_AT_SIGNAL"] = de_here if np.isfinite(de_here) else ""
        row["DG_ACTIVE_AT_SIGNAL"] = int(dg_here) if np.isfinite(dg_here) else ""
        row["MATCH_HOW"] = match_how
        if matched_rung is not None:
            row["ON_ANY_OF_8_RUNGS"] = "YES"
            row["MATCH_RUNG"] = matched_rung
        else:
            row["ON_ANY_OF_8_RUNGS"] = "NO"
            row["MATCH_RUNG"] = ""
            not_on += 1

        row["MATURITY_EQ_DG_ACTIVE"] = (
            "YES" if np.isfinite(dg_here) and int(mb) == int(dg_here) else "NO"
        ) if np.isfinite(dg_here) else ""

        rows.append(row)

    return not_on, total, rows


def _sheet_ladder_rung_at_signal_bar(
    ladder_pack: Optional[dict[str, Any]],
    i_sig: int,
    maturity_bar: int,
    zone_center: float,
    band_pct: float,
    zone_tol_pct: float = 0.0001,
) -> int:
    """
    Which sheet ladder rung (1-8) contains this trade's maturity zone at signal bar i_sig.
    Returns 9 if the zone is not on any rung (sheet no longer 'remembers' it).
    Returns 0 if ladder missing or indices invalid.
    """
    if ladder_pack is None or i_sig < 0:
        return 0
    slot_dg = ladder_pack.get("slot_dg_hist")
    slot_zl = ladder_pack.get("slot_zl_hist")
    slot_zh = ladder_pack.get("slot_zh_hist")
    if slot_dg is None or slot_zl is None or slot_zh is None or i_sig >= slot_dg.shape[0]:
        return 0
    n_rungs = int(ladder_pack.get("n_rungs", 8))
    zc = float(zone_center)
    if zc <= 0:
        return 0
    trade_zl = zc * (1.0 - band_pct)
    trade_zh = zc * (1.0 + band_pct)
    tol = max(zone_tol_pct, 1e-9) * max(abs(trade_zl), 1.0)
    mb = int(maturity_bar)

    for k in range(min(n_rungs, int(slot_dg.shape[1]))):
        dg_k = slot_dg[i_sig, k]
        zlk = slot_zl[i_sig, k]
        zhk = slot_zh[i_sig, k]
        if not np.isfinite(dg_k):
            continue
        if int(round(float(dg_k))) == mb:
            return k + 1
        if np.isfinite(zlk) and np.isfinite(zhk):
            if abs(zlk - trade_zl) <= tol and abs(zhk - trade_zh) <= tol:
                return k + 1
    return 9


def write_ladder_mismatch_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def write_sheet_parity_csv(
    path: Path,
    sym: str,
    df: pd.DataFrame,
    index_iso: list[str],
    ladder: dict[str, Any],
) -> None:
    """Write per-bar DE/DF/DG (+ CE/CF lag) for diffing against Google Sheet exports."""
    n = len(df)
    de = ladder["de"]
    df_ = ladder["df"]
    dg = ladder["dg"]
    ce = ladder["ce"]
    cf = ladder["cf"]
    dg_slot = ladder.get("dg_slot", np.full(n, np.nan))
    c14 = int(ladder.get("c14", 7))
    rows: list[list[Any]] = []
    for i in range(n):
        iso = index_iso[i] if i < len(index_iso) else ""
        d_str = f"{iso[:4]}-{iso[4:6]}-{iso[6:8]}" if len(iso) >= 8 else str(iso)
        rows.append([
            sym,
            d_str,
            i,
            _fmt_par(c14),
            _fmt_par(ce[i]),
            _fmt_par(cf[i]),
            _fmt_par(de[i]),
            _fmt_par(df_[i]),
            _fmt_par(dg[i]),
            _fmt_par(dg_slot[i]),
        ])
    hdr = [
        "SYMBOL",
        "DATE",
        "BAR",
        "C14_LAG",
        "CE_LAG_ZONE_LOWER",
        "CF_LAG_ZONE_UPPER",
        "DE_ACTIVE_ZONE_LOWER",
        "DF_ACTIVE_ZONE_UPPER",
        "DG_MATURITY_BAR",
        "DG_RUNG",
        "SHEET_DE_PASTE",
        "SHEET_DF_PASTE",
        "SHEET_DG_PASTE",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fp:
        w = csv.writer(fp)
        w.writerow(hdr)
        for r in rows:
            w.writerow(r + ["", "", ""])  # paste columns for manual sheet values


def _fmt_par(x: Any) -> str:
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return ""
    if isinstance(x, (np.floating, float)):
        return f"{float(x):.6g}"
    return str(x)


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


def _brt_active_zone_dn_bar(
    at_i: int,
    ladder_pack_zone: Optional[dict[str, Any]],
    cfg: BRTConfig,
) -> Optional[int]:
    if at_i < 0 or ladder_pack_zone is None:
        return None
    de_arr = ladder_pack_zone.get("de")
    df_arr = ladder_pack_zone.get("df")
    dg_arr = ladder_pack_zone.get("dg")
    if de_arr is None or df_arr is None or dg_arr is None or at_i >= len(dg_arr):
        return None
    zl_i = float(de_arr[at_i]) if np.isfinite(de_arr[at_i]) else float("nan")
    zu_i = float(df_arr[at_i]) if np.isfinite(df_arr[at_i]) else float("nan")
    dg_i = float(dg_arr[at_i]) if np.isfinite(dg_arr[at_i]) else float("nan")
    if not (np.isfinite(zl_i) and np.isfinite(zu_i) and np.isfinite(dg_i)):
        return None
    dg_j = int(dg_i)
    if dg_j < 0:
        return None
    asof_lag = max(0, int(getattr(cfg, "sheet_active_zone_asof_lag_bars", 0)))
    age_adjust = max(0, int(getattr(cfg, "sheet_active_zone_asof_age_adjust_bars", 0)))
    if asof_lag > 0 and ((at_i - dg_j) + age_adjust < asof_lag):
        return None
    return dg_j


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


_SheetLadderGateFns = tuple[
    Callable[[int], tuple[bool, float, float, int, float]],
    Callable[[int, float, float], bool],
    Callable[[tuple[bool, float, float, int, float], tuple[bool, float, float, int, float]], bool],
    Callable[[int], bool],
    Callable[[int], bool],
    Callable[[int], bool],
]

# Optional Numba JIT for sheet AQ/AK precompute (same semantics as _brt_make_entry_gate_query_fns).
_NUMBA_AQ_AK_AVAILABLE = False
_precompute_ak_aq_numba_impl = None  # type: ignore[assignment]
try:
    from numba import njit  # noqa: F401

    @njit(cache=True)
    def _precompute_ak_aq_numba_impl(
        close_arr: np.ndarray,
        low_arr: np.ndarray,
        high_arr: np.ndarray,
        low_rnd: np.ndarray,
        high_rnd: np.ndarray,
        use_rounded_ohlc: int,
        ok_z: np.ndarray,
        zl_a: np.ndarray,
        zu_a: np.ndarray,
        dg_a: np.ndarray,
        sid_a: np.ndarray,
        aq_window: int,
        breakout_window: int,
        zone_cmp_round: int,
        use_sid: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        n = close_arr.shape[0]
        ak_out = np.zeros(n, dtype=np.bool_)
        aq_out = np.zeros(n, dtype=np.bool_)
        for j in range(1, n):
            if not ok_z[j]:
                continue
            zl_j = zl_a[j]
            zu_j = zu_a[j]
            dg_j = dg_a[j]
            if j <= dg_j:
                continue
            if use_rounded_ohlc != 0:
                lo_j = low_rnd[j]
                hi_j = high_rnd[j]
                zlr = round(zl_j, zone_cmp_round)
                zur = round(zu_j, zone_cmp_round)
                ov = (lo_j <= zur) and (hi_j >= zlr)
            else:
                lo_j = low_arr[j]
                hi_j = high_arr[j]
                ov = (lo_j <= zu_j) and (hi_j >= zl_j)
            if ov and (close_arr[j - 1] > zu_j):
                ak_out[j] = True
        for j in range(n):
            if not ok_z[j]:
                continue
            zl_j = zl_a[j]
            zu_j = zu_a[j]
            sid_r = sid_a[j]
            start_ev = j - aq_window + 1
            if start_ev < 0:
                start_ev = 0
            am_cnt = 0
            an_cnt = 0
            for k in range(start_ev, j + 1):
                if not ok_z[k]:
                    continue
                sid_k = sid_a[k]
                same = False
                if use_sid != 0 and np.isfinite(sid_r) and np.isfinite(sid_k):
                    same = int(sid_r) == int(sid_k)
                elif zone_cmp_round >= 0:
                    same = (round(zl_a[k], zone_cmp_round) == round(zl_j, zone_cmp_round)) and (
                        round(zu_a[k], zone_cmp_round) == round(zu_j, zone_cmp_round)
                    )
                else:
                    same = (abs(zl_a[k] - zl_j) <= 1.0e-12) and (abs(zu_a[k] - zu_j) <= 1.0e-12)
                if not same:
                    continue
                if k < 1:
                    continue
                zl_k = zl_a[k]
                zu_k = zu_a[k]
                dg_k = dg_a[k]
                if k <= dg_k:
                    continue
                if use_rounded_ohlc != 0:
                    lo_k = low_rnd[k]
                    hi_k = high_rnd[k]
                    zlr_k = round(zl_k, zone_cmp_round)
                    zur_k = round(zu_k, zone_cmp_round)
                    ov_k = (lo_k <= zur_k) and (hi_k >= zlr_k)
                else:
                    lo_k = low_arr[k]
                    hi_k = high_arr[k]
                    ov_k = (lo_k <= zu_k) and (hi_k >= zl_k)
                if ov_k and (close_arr[k - 1] > zu_k):
                    am_cnt += 1
                if ov_k and (close_arr[k - 1] < zl_k):
                    an_cnt += 1
            am_flag = am_cnt >= 2
            an_flag = an_cnt > 0
            start_br = j - breakout_window + 1
            if start_br < 0:
                start_br = 0
            mx = close_arr[start_br]
            for t in range(start_br + 1, j + 1):
                v = close_arr[t]
                if v > mx:
                    mx = v
            ap_flag = mx > zu_j
            aq_out[j] = am_flag or (an_flag and ap_flag)
        return ak_out, aq_out

    _NUMBA_AQ_AK_AVAILABLE = True
except ImportError:
    pass


def _build_sheet_zone_ctx_arrays(
    n: int,
    cfg: BRTConfig,
    de_ctx: np.ndarray,
    df_ctx: np.ndarray,
    dg_ctx: np.ndarray,
    ds_ctx: Optional[np.ndarray],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Vectorized zone context (replaces per-bar dict cache in _zone_ctx_at for sheet ladder)."""
    asof_lag = max(0, int(getattr(cfg, "sheet_active_zone_asof_lag_bars", 0)))
    age_adjust_cfg = max(0, int(getattr(cfg, "sheet_active_zone_asof_age_adjust_bars", 0)))
    ok_z = np.zeros(n, dtype=np.bool_)
    zl_a = np.full(n, np.nan, dtype=np.float64)
    zu_a = np.full(n, np.nan, dtype=np.float64)
    dg_a = np.full(n, -1.0, dtype=np.float64)
    sid_a = np.full(n, np.nan, dtype=np.float64)
    for j in range(n):
        zl_j = float(de_ctx[j]) if j < len(de_ctx) and np.isfinite(de_ctx[j]) else float("nan")
        zu_j = float(df_ctx[j]) if j < len(df_ctx) and np.isfinite(df_ctx[j]) else float("nan")
        dg_j = int(dg_ctx[j]) if j < len(dg_ctx) and np.isfinite(dg_ctx[j]) else -1
        sid_j = (
            float(ds_ctx[j])
            if ds_ctx is not None and j < len(ds_ctx) and np.isfinite(ds_ctx[j])
            else float("nan")
        )
        ok = np.isfinite(zl_j) and np.isfinite(zu_j) and zl_j > 0 and zu_j > 0 and dg_j >= 0
        if ok and asof_lag > 0:
            if (j - dg_j) + age_adjust_cfg < asof_lag:
                ok = False
        ok_z[j] = ok
        if ok:
            zl_a[j] = zl_j
            zu_a[j] = zu_j
            dg_a[j] = float(dg_j)
            sid_a[j] = sid_j
    return ok_z, zl_a, zu_a, dg_a, sid_a


def _precompute_sheet_aq_ak_arrays(
    cfg: BRTConfig,
    close_arr: np.ndarray,
    low_arr: np.ndarray,
    high_arr: np.ndarray,
    de_ctx: np.ndarray,
    df_ctx: np.ndarray,
    dg_ctx: np.ndarray,
    ds_ctx: Optional[np.ndarray],
    n: int,
) -> tuple[np.ndarray, np.ndarray]:
    """One-pass AK/AQ arrays for sheet DE/DF/DG context (matches _brt_make_entry_gate_query_fns)."""
    ok_z, zl_a, zu_a, dg_a, sid_a = _build_sheet_zone_ctx_arrays(n, cfg, de_ctx, df_ctx, dg_ctx, ds_ctx)
    aq_window = max(1, int(getattr(cfg, "lookback_short", 199)))
    breakout_window = max(1, int(getattr(cfg, "breakout_bars", 100)))
    zone_cmp_round = int(getattr(cfg, "zone_compare_round_decimals", -1))
    use_sid_i = 1 if bool(getattr(cfg, "sheet_use_dg_slot_for_zone_identity", True)) else 0
    use_sid_b = bool(getattr(cfg, "sheet_use_dg_slot_for_zone_identity", True))
    st_on = bool(getattr(cfg, "support_test_enabled", True))
    if not st_on:
        return np.zeros(n, dtype=bool), np.zeros(n, dtype=bool)

    if zone_cmp_round >= 0:
        low_rnd = np.round(np.asarray(low_arr, dtype=np.float64), zone_cmp_round)
        high_rnd = np.round(np.asarray(high_arr, dtype=np.float64), zone_cmp_round)
        use_rounded = 1
    else:
        low_rnd = np.asarray(low_arr, dtype=np.float64)
        high_rnd = np.asarray(high_arr, dtype=np.float64)
        use_rounded = 0

    use_numba = (
        _NUMBA_AQ_AK_AVAILABLE
        and _precompute_ak_aq_numba_impl is not None
        and os.environ.get("BRT_DISABLE_NUMBA_AQ_AK", "").strip().lower() not in ("1", "true", "yes", "on")
    )
    if use_numba:
        try:
            return _precompute_ak_aq_numba_impl(
                np.asarray(close_arr, dtype=np.float64),
                np.asarray(low_arr, dtype=np.float64),
                np.asarray(high_arr, dtype=np.float64),
                low_rnd,
                high_rnd,
                np.int32(use_rounded),
                ok_z,
                zl_a,
                zu_a,
                dg_a,
                sid_a,
                aq_window,
                breakout_window,
                zone_cmp_round,
                use_sid_i,
            )
        except Exception:
            pass

    # Pure Python fallback (still much faster than per-bar dict _zone_ctx_at + nested calls).
    ak_out = np.zeros(n, dtype=bool)
    aq_out = np.zeros(n, dtype=bool)

    def _overlap_j(j: int, zl_v: float, zu_v: float) -> bool:
        if zone_cmp_round >= 0:
            lo_j = float(low_rnd[j])
            hi_j = float(high_rnd[j])
            zlr = round(float(zl_v), zone_cmp_round)
            zur = round(float(zu_v), zone_cmp_round)
        else:
            lo_j = float(low_arr[j])
            hi_j = float(high_arr[j])
            zlr = float(zl_v)
            zur = float(zu_v)
        return bool((lo_j <= zur) and (hi_j >= zlr))

    def _same_ref(ref_i: int, k: int) -> bool:
        if not ok_z[ref_i] or not ok_z[k]:
            return False
        sid_r = sid_a[ref_i]
        sid_k = sid_a[k]
        if use_sid_b and np.isfinite(sid_r) and np.isfinite(sid_k):
            return int(sid_r) == int(sid_k)
        if zone_cmp_round >= 0:
            return (
                round(float(zl_a[ref_i]), zone_cmp_round) == round(float(zl_a[k]), zone_cmp_round)
                and round(float(zu_a[ref_i]), zone_cmp_round) == round(float(zu_a[k]), zone_cmp_round)
            )
        return abs(float(zl_a[ref_i]) - float(zl_a[k])) <= 1e-12 and abs(float(zu_a[ref_i]) - float(zu_a[k])) <= 1e-12

    close_64 = np.asarray(close_arr, dtype=np.float64)
    for j in range(1, n):
        if not ok_z[j]:
            continue
        zl_j = float(zl_a[j])
        zu_j = float(zu_a[j])
        dg_j = int(dg_a[j])
        if j <= dg_j:
            continue
        if _overlap_j(j, zl_j, zu_j) and (close_64[j - 1] > zu_j):
            ak_out[j] = True

    for j in range(n):
        if not ok_z[j]:
            continue
        zl_j = float(zl_a[j])
        zu_j = float(zu_a[j])
        start_ev = max(0, j - aq_window + 1)
        am_cnt = 0
        an_cnt = 0
        for k in range(start_ev, j + 1):
            if not _same_ref(j, k):
                continue
            if k < 1:
                continue
            if not ok_z[k]:
                continue
            zl_k = float(zl_a[k])
            zu_k = float(zu_a[k])
            dg_k = int(dg_a[k])
            if k <= dg_k:
                continue
            ov = _overlap_j(k, zl_k, zu_k)
            if ov and (close_64[k - 1] > zu_k):
                am_cnt += 1
            if ov and (close_64[k - 1] < zl_k):
                an_cnt += 1
        am_flag = am_cnt >= 2
        an_flag = an_cnt > 0
        start_br = max(0, j - breakout_window + 1)
        ap_flag = bool(np.max(close_64[start_br : j + 1]) > zu_j)
        aq_out[j] = bool(am_flag or (an_flag and ap_flag))

    return ak_out, aq_out


def _sheet_ladder_aq_ak_and_gate_fns(
    i: int,
    n: int,
    cfg: BRTConfig,
    ladder_pack_zone: dict[str, Any],
    close_arr: np.ndarray,
    low_arr: np.ndarray,
    high_arr: np.ndarray,
) -> Optional[tuple[tuple[bool, bool, bool, bool], _SheetLadderGateFns]]:
    """
    One ``_brt_make_entry_gate_query_fns`` build for sheet DE/DF/DG: AQ/AK at i and i-1 plus the
    six-tuple reused for every pending zone on this bar. Returns None if support test off, ladder
    off, or arrays too short — caller runs per-p fallback logic.
    """
    if not getattr(cfg, "support_test_enabled", True):
        return None
    if not bool(getattr(cfg, "sheet_active_zone_gates", True)):
        return None
    de_ctx = ladder_pack_zone.get("de")
    df_ctx = ladder_pack_zone.get("df")
    dg_ctx = ladder_pack_zone.get("dg")
    ds_ctx = ladder_pack_zone.get("dg_slot")
    if de_ctx is None or df_ctx is None or dg_ctx is None or len(de_ctx) < n:
        return None

    _fns = _brt_make_entry_gate_query_fns(
        use_sheet_zone_ctx=True,
        st_on=True,
        cfg=cfg,
        close_arr=close_arr,
        low_arr=low_arr,
        high_arr=high_arr,
        de_ctx=de_ctx,
        df_ctx=df_ctx,
        dg_ctx=dg_ctx,
        ds_ctx=ds_ctx,
        zone_low_fb=0.0,
        zone_upper_fb=1.0,
        maturity_bar_fb=-1,
    )
    _ak_at = _fns[3]
    _aq_at = _fns[5]
    _cache = (
        _ak_at(i),
        _ak_at(i - 1) if i >= 1 else False,
        _aq_at(i),
        _aq_at(i - 1) if i >= 1 else False,
    )
    return (_cache, _fns)


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
    sheet_ladder_trace: Optional[dict[str, Any]] = None,
    cprofile_magic_touch: Optional[cProfile.Profile] = None,
    cprofile_pending_sheet_prep: Optional[cProfile.Profile] = None,
) -> tuple[list[BRTTrade], Optional[BRTTrade], list[dict], list[dict]]:
    """
    One trade at a time. Entry at next day open. Stop/Target from spec.
    If benchmark_df is provided (e.g. SPY OHLC), computes beta_at_entry for each trade (rolling beta vs benchmark ending at entry date).
    If profile_backtest_sections is a dict, accumulates per-section seconds, including **pre-main-loop** buckets
    so ``t_backtest`` wall time is explainable: ``bt_init``,     ``bt_ladder_overlap``, ``bt_ladder_low``,
    ``bt_ladder_close`` (0 in backtest — close-membership stream is not computed; overlap/low each get half the fused pass),
    ``bt_beta_precompute``, ``bt_strong_pivot_cd_stream`` (DO + confirmed touch + CD lag),
    then bar loop keys (``bt_loop_cb``, ``bt_loop_sheet_magic_touch``, ``bt_pending_active_zone``,
    ``bt_loop_pending_sheet_prep``, ``bt_loop_pending_for`` (wall time for the whole
    ``for p in pending_maturities`` loop; overlaps gate/entry sub-buckets below),
    ``bt_pending_gates_early``, ``bt_pending_gates_sheet``, ``bt_pending_gates``, ``bt_loop_bar_total``,
    ``bt_pending_pivot_sequence`` (``_pivot_sequence_in_zone`` only),
    ``bt_pending_entry_build`` (enriched metrics + ``BRTTrade`` / scanner after pivot filters),
    ``bt_pending_entry``, ...). Note: block_reason ``close_le_open`` is a high-frequency cheap reject;
    heavy work is often ``bt_ladder_*``, ``bt_strong_pivot_cd_stream``, ``bt_loop_sheet_magic_touch``, or
    ``bt_pending_gates_sheet`` (AQ/AK/BG).
    If ``cprofile_magic_touch`` is a ``cProfile.Profile``, it is enabled only while executing the
    per-bar sheet magic touch block (AR/AW + CD window). If ``cprofile_pending_sheet_prep`` is
    provided, it is enabled only around the per-bar pending sheet prep block that builds AQ/AK
    gates before iterating pending maturities.
    Returns (closed_trades, open_trade, scanner_candidates, would_have_entries, watchlist_rows).
    would_have_entries: when cfg.emit_would_have, list of dicts (SYMBOL, MATURITY_DATE, ZONE_CENTER, WOULD_ENTER_DATE, REJECT_REASON) for maturities blocked only by growth/tight_range/consolidation.
    watchlist_rows: list of dicts for BRT_Watchlist (scanner + pending-at-EOD hints).
    """
    closed: list[BRTTrade] = []
    open_trade: Optional[BRTTrade] = None
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

    _hist_closed_len = -1
    _hist_ann_ror_cached = 0.0

    def _get_hist_ann_ror() -> float:
        nonlocal _hist_closed_len, _hist_ann_ror_cached
        if len(closed) != _hist_closed_len:
            _hist_closed_len = len(closed)
            _, _, _hist_ann_ror_cached = _hist_stats_for_symbol(closed, sym, cfg.days_per_year)
        return _hist_ann_ror_cached

    _t_init = time.perf_counter()
    # Precompute numpy arrays to avoid repeated .iloc in hot loop
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
    # 14-day ATR: TR = max(H-L, |H-prev_C|, |L-prev_C|); ATR14 = rolling mean of TR over 14 bars
    atr_period = 14
    tr_arr = np.empty(n, dtype=np.float64)
    tr_arr[0] = high_arr[0] - low_arr[0]
    if n > 1:
        hl = high_arr[1:] - low_arr[1:]
        h_pc = np.abs(high_arr[1:] - close_arr[:-1])
        l_pc = np.abs(low_arr[1:] - close_arr[:-1])
        tr_arr[1:] = np.maximum.reduce([hl, h_pc, l_pc])
    atr_14_arr = np.full(n, np.nan, dtype=np.float64)
    if n >= atr_period:
        atr_14_arr[atr_period - 1 :] = np.convolve(
            tr_arr, np.ones(atr_period, dtype=np.float64) / float(atr_period), mode="valid"
        )

    _acc_bt("bt_init", time.perf_counter() - _t_init)

    c14_lag = int(getattr(cfg, "sheet_maturity_lag_bars", 7))
    n_rungs_cfg = int(getattr(cfg, "sheet_zone_ladder_rungs", 0))
    n_rungs = max(1, int(cfg.lookback_long) if n_rungs_cfg <= 0 else n_rungs_cfg)
    use_sheet_ladder = bool(getattr(cfg, "use_sheet_ladder_active_zone", False))
    # Two ladders used in backtest (single fused pass shares CE/CF and slot state):
    # - overlap: AR/AW counting semantics
    # - low-membership: DE/DF/DG for AK/AQ/BG (close-membership is diagnostic-only; omitted here for speed)
    _t_lo = time.perf_counter()
    ladder_pack_overlap, ladder_pack_low, ladder_pack_close = _compute_sheet_ladder_de_df_dg_all_modes(
        high_arr, low_arr, close_arr, zl_full_arr, zh_full_arr, c14_lag, n_rungs=n_rungs,
        include_close_membership=False,
    )
    _dt_ladder = time.perf_counter() - _t_lo
    _ld2 = _dt_ladder / 2.0
    _acc_bt("bt_ladder_overlap", _ld2)
    _acc_bt("bt_ladder_low", _ld2)
    _acc_bt("bt_ladder_close", 0.0)
    ladder_pack: dict[str, Any] = ladder_pack_overlap
    ladder_pack_zone: dict[str, Any] = ladder_pack_low
    if sheet_ladder_trace is not None:
        sheet_ladder_trace.clear()
        # Keep overlap ladder as the default trace source since it feeds AR/AW.
        sheet_ladder_trace.update(ladder_pack_overlap)
        sheet_ladder_trace["index_iso"] = list(index_iso)

    beta_by_bar_arr: Optional[np.ndarray] = None
    if benchmark_df is not None:
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
    _t_scd = time.perf_counter()
    if pre_bars > 0 and pre_pct > 0:
        for t in range(n):
            if ph_arr[t] > 0.0:
                do_touch_arr[t] = _strong_pivot_bar_ok(
                    t, "PH", high_arr, low_arr, n,
                    pre_bars=pre_bars,
                    pre_pct=pre_pct,
                    post_bars=0,
                    post_pct=0.0,
                    mode="pre",
                )
                # Confirmed touch (AF-style): require pre AND post.
                if post_bars > 0 and post_pct > 0:
                    if _strong_pivot_bar_ok(
                        t, "PH", high_arr, low_arr, n,
                        pre_bars=pre_bars,
                        pre_pct=pre_pct,
                        post_bars=post_bars,
                        post_pct=post_pct,
                        mode="both",
                    ):
                        confirmed_touch_arr[t] = float(ph_arr[t])
            elif pl_arr[t] > 0.0:
                do_touch_arr[t] = _strong_pivot_bar_ok(
                    t, "PL", high_arr, low_arr, n,
                    pre_bars=pre_bars,
                    pre_pct=pre_pct,
                    post_bars=0,
                    post_pct=0.0,
                    mode="pre",
                )
                if post_bars > 0 and post_pct > 0:
                    if _strong_pivot_bar_ok(
                        t, "PL", high_arr, low_arr, n,
                        pre_bars=pre_bars,
                        pre_pct=pre_pct,
                        post_bars=post_bars,
                        post_pct=post_pct,
                        mode="both",
                    ):
                        confirmed_touch_arr[t] = float(pl_arr[t])
    lag_c14 = max(0, int(getattr(cfg, "sheet_maturity_lag_bars", 7)))
    if lag_c14 > 0:
        for i_cd in range(lag_c14, n):
            cd_touch_arr[i_cd] = confirmed_touch_arr[i_cd - lag_c14]
    else:
        cd_touch_arr[:] = confirmed_touch_arr
    _acc_bt("bt_strong_pivot_cd_stream", time.perf_counter() - _t_scd)

    # DP parity helper: current low in any matured zone CE/CF with rows in [i-C10 .. i-C14].
    ce_ctx = ladder_pack.get("ce") if ladder_pack is not None else None
    cf_ctx = ladder_pack.get("cf") if ladder_pack is not None else None

    def _dp_inside_any_zone(i_bar: int) -> bool:
        if i_bar < 0 or ce_ctx is None or cf_ctx is None:
            return False
        lag = max(0, int(getattr(cfg, "sheet_maturity_lag_bars", 7)))
        c10 = int(getattr(cfg, "dp_window_bars", 0))
        if c10 <= 0:
            c10 = int(getattr(cfg, "lookback_long", 504))
        start = max(0, i_bar - c10)
        end = i_bar - lag
        if end < 0 or end < start:
            return False
        px = float(low_arr[i_bar])
        for k in range(start, end + 1):
            zl_k = float(ce_ctx[k]) if k < len(ce_ctx) and np.isfinite(ce_ctx[k]) else float("nan")
            zu_k = float(cf_ctx[k]) if k < len(cf_ctx) and np.isfinite(cf_ctx[k]) else float("nan")
            if np.isfinite(zl_k) and np.isfinite(zu_k) and zl_k <= px <= zu_k:
                return True
        return False

    # Consolidation Blocker (CB) state (per symbol)
    inside_required_high = 3
    inside_required_low = 3
    max_high_since_entry: float = 0.0  # for ATR_Increment trailing stop
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
    if bool(getattr(cfg, "sheet_magic_touch_enabled", False)) and ladder_pack is not None:
        _sde = ladder_pack.get("de")
        _sdf = ladder_pack.get("df")
        _sdg = ladder_pack.get("dg")
        _smt_asof_lag = max(0, int(getattr(cfg, "sheet_active_zone_asof_lag_bars", 0)))
        _smt_age_adjust = max(0, int(getattr(cfg, "sheet_active_zone_asof_age_adjust_bars", 0)))
        _smt_win_magic = int(getattr(cfg, "sheet_magic_touch_window_bars", 0))
        if _smt_win_magic <= 0:
            _smt_win_magic = int(getattr(cfg, "lookback_long", 504))

        def _smt_bounds_fn(idx: int) -> tuple[bool, float, float, int]:
            if idx < 0 or _sde is None or _sdf is None or _sdg is None or idx >= len(_sde):
                return (False, float("nan"), float("nan"), -1)
            zl_v = float(_sde[idx]) if np.isfinite(_sde[idx]) else float("nan")
            zh_v = float(_sdf[idx]) if np.isfinite(_sdf[idx]) else float("nan")
            dg_v = int(_sdg[idx]) if np.isfinite(_sdg[idx]) else -1
            ok_v = np.isfinite(zl_v) and np.isfinite(zh_v) and zl_v > 0 and zh_v > 0 and dg_v >= 0
            if ok_v and _smt_asof_lag > 0:
                if (idx - dg_v) + _smt_age_adjust < _smt_asof_lag:
                    ok_v = False
            return (bool(ok_v), zl_v, zh_v, dg_v)

    # Carries _smt_bounds_fn(i-1) across bars for zone-change vs prior row (sheet AW).
    _smt_prev_bar: tuple[bool, float, float, int] = (False, float("nan"), float("nan"), -1)

    # Precompute sheet AK/AQ for all bars once (avoids per-bar _sheet_ladder_aq_ak_and_gate_fns + dict cache).
    sheet_prefetched_gate_fns: Optional[_SheetLadderGateFns] = None
    sheet_prefetched_ak_arr: Optional[np.ndarray] = None
    sheet_prefetched_aq_arr: Optional[np.ndarray] = None
    if (
        getattr(cfg, "support_test_enabled", True)
        and bool(getattr(cfg, "sheet_active_zone_gates", True))
        and ladder_pack_zone is not None
    ):
        de_x = ladder_pack_zone.get("de")
        df_x = ladder_pack_zone.get("df")
        dg_x = ladder_pack_zone.get("dg")
        if de_x is not None and df_x is not None and dg_x is not None and len(de_x) >= n:
            ds_x = ladder_pack_zone.get("dg_slot")
            de_xa = np.asarray(de_x, dtype=np.float64)
            df_xa = np.asarray(df_x, dtype=np.float64)
            dg_xa = np.asarray(dg_x, dtype=np.float64)
            ds_xa = np.asarray(ds_x, dtype=np.float64) if ds_x is not None else None
            sheet_prefetched_gate_fns = _brt_make_entry_gate_query_fns(
                use_sheet_zone_ctx=True,
                st_on=True,
                cfg=cfg,
                close_arr=close_arr,
                low_arr=low_arr,
                high_arr=high_arr,
                de_ctx=de_xa,
                df_ctx=df_xa,
                dg_ctx=dg_xa,
                ds_ctx=ds_x,
                zone_low_fb=0.0,
                zone_upper_fb=1.0,
                maturity_bar_fb=-1,
            )
            sheet_prefetched_ak_arr, sheet_prefetched_aq_arr = _precompute_sheet_aq_ak_arrays(
                cfg, close_arr, low_arr, high_arr, de_xa, df_xa, dg_xa, ds_xa, n
            )

    for i in range(n - 1):
        _t_bar = time.perf_counter()
        iso = index_iso[i]
        next_iso = index_iso[i + 1]
        op = open_arr[i]
        hi = high_arr[i]
        lo = low_arr[i]
        cl = close_arr[i]
        next_op = open_arr[i + 1]
        # Per-bar bullish flag: same for all pending zones on this bar (avoid repeated float compares).
        bullish_bar = cl > op

        _t_cb = time.perf_counter()
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
                and box_width_pct <= getattr(cfg, "cb_max_box_width_pct", 0.35)
            ):
                cb_active = True

        _acc_bt("bt_loop_cb", time.perf_counter() - _t_cb)

        # --- EXIT LOGIC (if we have a position) ---
        # Resolution order (first match wins): gap down, gap up, intraday stop, intraday target
        _t_ex = time.perf_counter()
        if open_trade is not None:
            max_high_since_entry = max(max_high_since_entry, hi)
            sp = open_trade.stop_price
            tp = open_trade.target_price
            # ATR_Increment trailing stop: for every atr_increment% gain, raise stop by 1% of entry
            if getattr(cfg, "atr_increment", 0) > 0 and open_trade.entry_price > 0:
                gain_pct = (max_high_since_entry - open_trade.entry_price) / open_trade.entry_price * 100.0
                increments = int(gain_pct / cfg.atr_increment)
                stop_raise = increments * 0.01 * open_trade.entry_price
                sp = open_trade.stop_price + stop_raise
            stop_round_decimals = int(getattr(cfg, "stop_compare_round_decimals", 2))
            if stop_round_decimals >= 0:
                op_cmp = round(float(op), stop_round_decimals)
                lo_cmp = round(float(lo), stop_round_decimals)
                sp_cmp = round(float(sp), stop_round_decimals)
            else:
                op_cmp = float(op)
                lo_cmp = float(lo)
                sp_cmp = float(sp)
            gap_down = op_cmp <= sp_cmp
            gap_up = op >= tp
            stop_hit = lo_cmp <= sp_cmp
            target_hit = hi >= tp
            # Use ATR exit labels (ATR_STOP / ATR_TARGET / ATR_Increment) whenever any ATR-based behavior is configured
            use_atr_mode = (
                getattr(cfg, "atr_target", 0.0) > 0.0
                or getattr(cfg, "atr_stop", 0.0) > 0.0
                or getattr(cfg, "atr_increment", 0.0) > 0.0
            )
            hit_trailing_stop = use_atr_mode and getattr(cfg, "atr_increment", 0) > 0 and sp > open_trade.stop_price

            if gap_down:
                exit_price = op
                if use_atr_mode:
                    exit_type = "ATR_Increment" if hit_trailing_stop else "ATR_STOP"
                else:
                    exit_type = "GAP_DOWN"
            elif gap_up:
                exit_price = op
                exit_type = "ATR_TARGET" if use_atr_mode else "GAP_UP"
            elif stop_hit:
                exit_price = cl if cfg.exit_at_close_when_stopped else sp
                if use_atr_mode:
                    exit_type = "ATR_Increment" if hit_trailing_stop else "ATR_STOP"
                else:
                    exit_type = "STOP_LOSS"
            elif target_hit:
                exit_price = tp
                exit_type = "ATR_TARGET" if use_atr_mode else "TARGET"
            else:
                _acc_bt("bt_loop_exit", time.perf_counter() - _t_ex)
                _acc_bt("bt_loop_bar_total", time.perf_counter() - _t_bar)
                continue

            pnl_pct = (exit_price - open_trade.entry_price) / open_trade.entry_price * 100
            pnl_dollars = (cfg.brt_cash / open_trade.entry_price) * (exit_price - open_trade.entry_price)
            days_held = (pd.Timestamp(iso) - pd.Timestamp(open_trade.date_opened)).days if len(iso) == 8 else 0
            # Max High during hold
            d_open = open_trade.date_opened
            if len(d_open) == 8 and len(iso) == 8:
                start_dt = pd.Timestamp(d_open[:4] + "-" + d_open[4:6] + "-" + d_open[6:8])
                end_dt = pd.Timestamp(iso[:4] + "-" + iso[4:6] + "-" + iso[6:8])
                mask = (df.index >= start_dt) & (df.index <= end_dt)
                max_price = float(df.loc[mask, "High"].max()) if mask.any() else open_trade.entry_price
            else:
                max_price = open_trade.entry_price

            t = BRTTrade(
                symbol=sym,
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
                touch_count=open_trade.touch_count,
                touch_count_short=open_trade.touch_count_short,
                touch_count_major=open_trade.touch_count_major,
                touch_count_minor=open_trade.touch_count_minor,
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
                atr_14_at_entry=getattr(open_trade, "atr_14_at_entry", None),
                market_cap=getattr(open_trade, "market_cap", None),
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
                sheet_ladder_rung_at_signal=getattr(open_trade, "sheet_ladder_rung_at_signal", 0),
            )
            closed.append(t)
            open_trade = None
            # NOTE: Do NOT continue here - maturity detection must run even on exit bars
            # so zones that mature on the same bar as an exit are not lost

        _acc_bt("bt_loop_exit", time.perf_counter() - _t_ex)

        _t_sc = time.perf_counter()
        # --- Short candidate flag (for future shorting) ---
        if short_candidate_arr[i]:
            dt = f"{iso[:4]}-{iso[4:6]}-{iso[6:8]}" if len(iso) >= 8 else iso
            short_candidates.append({
                "symbol": sym, "date": dt, "zone_center": zone_center_arr[i],
                "close": cl, "touch_count": int(touch_count_long_arr[i]),
            })

        _acc_bt("bt_loop_short", time.perf_counter() - _t_sc)

        # --- Pending maturities: touch event (AW) ---
        # Default: maturity when touch_count_long crosses threshold.
        # Optional sheet AW parity: use AR/AW semantics based on lagged CE/CF ladder and CD touches.
        touch_event_now = False
        touch_event_tc = 0
        zc = zone_center_arr[i]
        zl = float(zc) * (1 - cfg.band_pct) if pd.notna(zc) else float("nan")
        zh = float(zc) * (1 + cfg.band_pct) if pd.notna(zc) else float("nan")
        if _smt_bounds_fn is not None:
            if cprofile_magic_touch is not None:
                cprofile_magic_touch.enable()
            try:
                _t_smt = time.perf_counter() if _pbt is not None else 0.0
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
                    thr = int(getattr(cfg, "touch_threshold", 0))
                    touch_event_now = bool((ar >= thr) and ((ar_prev < thr) or zc_changed))
                    touch_event_tc = int(ar)
                    zc = (zl_act + zh_act) / 2.0
                    zl = zl_act
                    zh = zh_act
                if _pbt is not None:
                    _acc_bt("bt_loop_sheet_magic_touch", time.perf_counter() - _t_smt)
                _smt_prev_bar = _smt_bounds_at_i
            finally:
                if cprofile_magic_touch is not None:
                    cprofile_magic_touch.disable()
        else:
            # Legacy maturity event
            if i < len(touch_count_long_arr) and int(touch_count_long_arr[i]) >= int(cfg.touch_threshold):
                prev_tc = int(touch_count_long_arr[i - 1]) if i > 0 else 0
                zc_i = zone_center_arr[i]
                zc_prev = zone_center_arr[i - 1] if i > 0 else np.nan
                zh_i = float(zc_i) * (1 + cfg.band_pct) if pd.notna(zc_i) else np.nan
                zh_prev = float(zc_prev) * (1 + cfg.band_pct) if pd.notna(zc_prev) else np.nan
                zone_changed = bool(pd.notna(zh_i) and pd.notna(zh_prev) and (abs(zh_i - zh_prev) > 1e-12))
                touch_event_now = bool((prev_tc < int(cfg.touch_threshold)) or zone_changed)
                touch_event_tc = int(touch_count_long_arr[i])
        if touch_event_now:
            _t_ma = time.perf_counter()

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
            _acc_bt("bt_loop_maturity", time.perf_counter() - _t_ma)

        # Check pending maturities: evaluate entry gates on each bar until entry/expiry by other rules.
        still_pending: list[dict] = []
        eval_mode_global = str(getattr(cfg, "entry_eval_mode", "pending") or "pending").strip().lower()
        _t_ar = time.perf_counter() if _pbt is not None else 0.0
        if (
            eval_mode_global == "row_local"
            and bool(getattr(cfg, "sheet_active_zone_gates", True))
            and ladder_pack_zone is not None
        ):
            # Use DN-style active zone context (as-of gated), not raw DG.
            active_bar_today = _brt_active_zone_dn_bar(i, ladder_pack_zone, cfg)
            active_bar_prev = _brt_active_zone_dn_bar(i - 1, ladder_pack_zone, cfg) if i > 0 else None
        else:
            active_bar_today = (
                _brt_active_zone_maturity_bar(i, pending_maturities, high_arr, low_arr)
                if eval_mode_global == "row_local"
                else None
            )
            active_bar_prev = (
                _brt_active_zone_maturity_bar(i - 1, pending_maturities, high_arr, low_arr)
                if eval_mode_global == "row_local"
                else None
            )
        if _pbt is not None:
            _acc_bt("bt_pending_active_zone", time.perf_counter() - _t_ar)
        _t_prep = time.perf_counter() if _pbt is not None else 0.0
        # AQ/AK at (i, i-1) depend only on ladder row context when sheet_active_zone_gates + full DE length;
        # compute once per bar instead of once per pending zone (same values for every p).
        _sheet_aq_ak_cache: Optional[tuple[bool, bool, bool, bool]] = None
        _gate_fns_sheet: Optional[_SheetLadderGateFns] = None
        if cprofile_pending_sheet_prep is not None:
            cprofile_pending_sheet_prep.enable()
        try:
            if pending_maturities and ladder_pack_zone is not None:
                if (
                    sheet_prefetched_ak_arr is not None
                    and sheet_prefetched_aq_arr is not None
                    and sheet_prefetched_gate_fns is not None
                ):
                    _sheet_aq_ak_cache = (
                        bool(sheet_prefetched_ak_arr[i]),
                        bool(sheet_prefetched_ak_arr[i - 1]) if i >= 1 else False,
                        bool(sheet_prefetched_aq_arr[i]),
                        bool(sheet_prefetched_aq_arr[i - 1]) if i >= 1 else False,
                    )
                    _gate_fns_sheet = sheet_prefetched_gate_fns
                else:
                    _sheet_bundle = _sheet_ladder_aq_ak_and_gate_fns(
                        i, n, cfg, ladder_pack_zone, close_arr, low_arr, high_arr
                    )
                    if _sheet_bundle is not None:
                        _sheet_aq_ak_cache, _gate_fns_sheet = _sheet_bundle
        finally:
            if cprofile_pending_sheet_prep is not None:
                cprofile_pending_sheet_prep.disable()
        if _pbt is not None:
            _acc_bt("bt_loop_pending_sheet_prep", time.perf_counter() - _t_prep)
        _t_pfor = time.perf_counter() if _pbt is not None else 0.0
        # Debug flag for entry logic
        debug_entry = _DEBUG_SYMBOL and sym == _DEBUG_SYMBOL and _DEBUG_DATE
        debug_date_prefix = _DEBUG_DATE.replace("-", "")[:6] if _DEBUG_DATE else ""  # e.g., "202207"
        for p in pending_maturities:
            _t_p = time.perf_counter() if _pbt is not None else 0.0
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
            maturity_date = index_iso[maturity_bar][:10] if maturity_bar < len(index_iso) else "?"
            trace_eval = (
                len(_TRACE_DATES) > 0
                and index_iso[i] in _TRACE_DATES
                and (_TRACE_SYMBOL is None or sym == _TRACE_SYMBOL)
            )

            def _trace_gate(msg: str) -> None:
                if trace_eval:
                    i_iso = index_iso[i]
                    i_fmt = f"{i_iso[:4]}-{i_iso[4:6]}-{i_iso[6:8]}" if len(i_iso) >= 8 else i_iso
                    print(
                        f"[TRACE] {sym} eval={i_fmt} maturity={maturity_date} "
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
            eval_mode = eval_mode_global
            if eval_mode == "row_local":
                # Sheet-style row-local gating:
                # - keep today's touch event for next bar evaluation
                # - evaluate yesterday's touch event now
                # - drop anything older
                if maturity_bar == i:
                    if not bool(getattr(cfg, "row_local_eval_touch_same_bar", False)):
                        # Defer to next bar — but the main loop only runs i in 0..n-2, so when the next bar is the
                        # last bar of data (i+1 == n-1) there is no following iteration; evaluate below using _eval_bar.
                        if i + 1 < n - 1:
                            _debug_gate_fail("skip: row_local keep today's touch event for next bar")
                            still_pending.append(p)
                            _trace_gate("skip: row_local keep today's touch event for next bar")
                            _pg()
                            continue
                if maturity_bar < (i - 1):
                    _debug_gate_fail("block: expired_touch_event_window (row_local)")
                    _count_block("expired_touch_event_window")
                    _trace_gate("block: expired_touch_event_window (row_local)")
                    _pg()
                    continue
                # DN-style active-zone parity: evaluate exactly one active zone context.
                # Prefer today's active zone; only fall back to prior row when today has no active zone.
                chosen_active_bar = active_bar_today if active_bar_today is not None else active_bar_prev
                if debug_eval_onebar:
                    print(
                        f"[DEBUG-ACTIVE-CTX-ONEBAR] {sym} eval=2022-12-01 maturity={maturity_date} "
                        f"maturity_bar={maturity_bar} active_today={active_bar_today} "
                        f"active_prev={active_bar_prev} chosen={chosen_active_bar}"
                    )
                if bool(getattr(cfg, "row_local_require_active_context_match", False)):
                    if chosen_active_bar is not None and maturity_bar != chosen_active_bar:
                        _debug_gate_fail(f"skip: not active zone context (chosen_active_bar={chosen_active_bar})")
                        still_pending.append(p)
                        _trace_gate(f"skip: not active zone context (chosen_active_bar={chosen_active_bar})")
                        _pg()
                        continue
            # Bar used for entry-gate OHLC (row_local end-of-series: evaluate on last bar i+1 when loop i is n-2).
            _eval_bar = i
            if (
                eval_mode_global == "row_local"
                and maturity_bar == i
                and not bool(getattr(cfg, "row_local_eval_touch_same_bar", False))
                and i + 1 == n - 1
            ):
                _eval_bar = i + 1
            if _eval_bar != i:
                op = open_arr[_eval_bar]
                hi = high_arr[_eval_bar]
                lo = low_arr[_eval_bar]
                cl = close_arr[_eval_bar]
                bullish_bar = cl > op
            # Sheet AW parity: touch event is row-local (today -> next evaluation only).
            if bool(getattr(cfg, "sheet_magic_touch_enabled", False)):
                if _eval_bar > (maturity_bar + int(getattr(cfg, "close_above_window", 1))):
                    _debug_gate_fail("block: expired_touch_event_window (sheet_magic_touch row-local TTL)")
                    _count_block("expired_touch_event_window")
                    _trace_gate("block: expired_touch_event_window (sheet_magic_touch row-local TTL)")
                    _pg()
                    continue
            # Pending lifecycle: prevent stale maturities from lingering indefinitely.
            # NOTE: keep this wider than close_above_window because AQ/Support Test are defined on bars
            # after maturity and may need time to become true.
            if _eval_bar > (maturity_bar + int(getattr(cfg, "pending_max_bars", 252))):
                _debug_gate_fail("block: expired_touch_event_window (pending_max_bars)")
                _count_block("expired_touch_event_window")
                _trace_gate("block: expired_touch_event_window (pending_max_bars)")
                _pg()
                continue
            
            zc = p["zone_center"]
            zone_low = p["zone_low"]  # Zone lower of trigger (6th-touch day or day before)
            tc = p["touch_count"]
            tc_major = p.get("touch_count_major", 0)
            tc_minor = p.get("touch_count_minor", 0)
            sh = p["struct_high"]
            sl = p["struct_low"]
            if not bullish_bar:  # require close > open (bullish candle)
                _debug_gate_fail(f"block: close<=open ({cl:.4f}<={op:.4f})")
                _count_block("close_le_open")
                _trace_gate(f"block: close<=open ({cl:.4f}<={op:.4f})")
                if debug_entry and debug_date_prefix in maturity_date:
                    print(f"[DEBUG-ENTRY] {sym} bar {i} ({index_iso[i][:10]}): zone ${zc:.2f} BLOCKED by close<=open ({cl:.2f}<={op:.2f})")
                still_pending.append(p)
                _pg()
                continue
            # Optional: require close not in lower half of the bar (sheet: >= midpoint between high and low)
            if getattr(cfg, "entry_close_min_range_position", 0.0) > 0.0:
                hi_i = float(high_arr[_eval_bar])
                lo_i = float(low_arr[_eval_bar])
                bar_rng = hi_i - lo_i
                min_pos = float(cfg.entry_close_min_range_position)
                if bar_rng > 1e-12:
                    close_pos = (cl - lo_i) / bar_rng
                    if close_pos + 1e-12 < min_pos:
                        _debug_gate_fail(f"block: close position in bar below min ({close_pos:.4f}<{min_pos:.4f})")
                        _count_block("bullish_close_below_range_mid")
                        _trace_gate(f"block: close position in bar below min ({close_pos:.4f}<{min_pos:.4f})")
                        if debug_entry and debug_date_prefix in maturity_date:
                            print(
                                f"[DEBUG-ENTRY] {sym} bar {i} ({index_iso[i][:10]}): zone ${zc:.2f} BLOCKED by close not high enough in bar "
                                f"(pos={close_pos:.4f} < min={min_pos:.4f}; H={hi_i:.4f} L={lo_i:.4f} C={cl:.4f})"
                            )
                        still_pending.append(p)
                        _pg()
                        continue
                # Zero-range bar: already passed close>open; treat as satisfying midpoint if close equals H/L
            # Touch count filters: TC >= min_touch_count, TC_MIN <= max_touch_count_minor
            if cfg.min_touch_count is not None and tc < cfg.min_touch_count:
                _debug_gate_fail(f"block: min_touch_count ({tc}<{cfg.min_touch_count})")
                _count_block("min_touch_count")
                _trace_gate(f"block: min_touch_count ({tc}<{cfg.min_touch_count})")
                if debug_entry and debug_date_prefix in maturity_date:
                    print(f"[DEBUG-ENTRY] {sym} bar {i}: zone ${zc:.2f} BLOCKED by min_touch_count ({tc} < {cfg.min_touch_count})")
                still_pending.append(p)
                _pg()
                continue
            if cfg.max_touch_count_minor is not None and tc_minor > cfg.max_touch_count_minor:
                _debug_gate_fail(f"block: max_touch_count_minor ({tc_minor}>{cfg.max_touch_count_minor})")
                _count_block("max_touch_count_minor")
                _trace_gate(f"block: max_touch_count_minor ({tc_minor}>{cfg.max_touch_count_minor})")
                if debug_entry and debug_date_prefix in maturity_date:
                    print(f"[DEBUG-ENTRY] {sym} bar {i}: zone ${zc:.2f} BLOCKED by max_touch_count_minor ({tc_minor} > {cfg.max_touch_count_minor})")
                still_pending.append(p)
                _pg()
                continue
            # Tradeable Key Level (TKL): level must be tradeable on current or prior bar
            if cfg.tradeable_key_level_enabled:
                tkl_i = bool(tradeable_key_level_arr[_eval_bar])
                tkl_prev = bool(tradeable_key_level_arr[_eval_bar - 1]) if _eval_bar > 0 else False
                if not (tkl_i or tkl_prev):
                    _debug_gate_fail("block: tradeable_key_level")
                    _count_block("tradeable_key_level")
                    _trace_gate("block: tradeable_key_level")
                    if debug_entry and debug_date_prefix in maturity_date:
                        # Explain why TKL failed: TKL requires touch_count_long >= touch_threshold AND touch_count_short >= 2.
                        # We print both components for the entry-check day i and the prior day.
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
                    still_pending.append(p)
                    _pg()
                    continue
            if _pbt is not None:
                _t_mid = time.perf_counter()
            # Sheet-parity intermediates (row-local) for this zone candidate:
            # AK = Support test, AM = Support evidence, AN = Resistance evidence, AP = Break above evidence,
            # AQ = Zone eligible long, BG = Level acceptance.
            st_on = getattr(cfg, "support_test_enabled", True)
            zone_upper = float(zc) * (1.0 + cfg.band_pct) if pd.notna(zc) else float("nan")
            if _gate_fns_sheet is not None:
                _zone_ctx_at, _overlap_at, _same_zone_ctx, _ak_at, _resistance_test_at, _aq_at = _gate_fns_sheet
            else:
                use_sheet_zone_ctx = bool(getattr(cfg, "sheet_active_zone_gates", True) and ladder_pack_zone is not None)
                de_ctx = ladder_pack_zone.get("de") if (use_sheet_zone_ctx and ladder_pack_zone is not None) else None
                df_ctx = ladder_pack_zone.get("df") if (use_sheet_zone_ctx and ladder_pack_zone is not None) else None
                dg_ctx = ladder_pack_zone.get("dg") if (use_sheet_zone_ctx and ladder_pack_zone is not None) else None
                ds_ctx = ladder_pack_zone.get("dg_slot") if (use_sheet_zone_ctx and ladder_pack_zone is not None) else None
                _zone_ctx_at, _overlap_at, _same_zone_ctx, _ak_at, _resistance_test_at, _aq_at = _brt_make_entry_gate_query_fns(
                    use_sheet_zone_ctx=use_sheet_zone_ctx,
                    st_on=st_on,
                    cfg=cfg,
                    close_arr=close_arr,
                    low_arr=low_arr,
                    high_arr=high_arr,
                    de_ctx=de_ctx,
                    df_ctx=df_ctx,
                    dg_ctx=dg_ctx,
                    ds_ctx=ds_ctx,
                    zone_low_fb=float(zone_low),
                    zone_upper_fb=float(zone_upper),
                    maturity_bar_fb=int(maturity_bar),
                )

            if _sheet_aq_ak_cache is not None:
                ak_today, ak_yesterday, _, _ = _sheet_aq_ak_cache
            else:
                ak_today = _ak_at(i)
                ak_yesterday = _ak_at(i - 1) if i >= 1 else False
            # DO parity gate: require recent pre-only strong touch event.
            if bool(getattr(cfg, "do_gate_enabled", False)):
                do_keep = max(1, int(getattr(cfg, "do_good_for_bars", 2)))
                do_start = max(0, i - do_keep + 1)
                do_ok = bool(np.any(do_touch_arr[do_start : i + 1]))
                if not do_ok:
                    _debug_gate_fail(f"block: DO gate (window={do_keep} bars)")
                    _count_block("do_pre_touch_gate")
                    _trace_gate(f"block: DO gate (window={do_keep} bars)")
                    still_pending.append(p)
                    _pg()
                    continue
            # DP parity gate: require price in any matured zone CE/CF in [row-C10 .. row-C14].
            if bool(getattr(cfg, "dp_gate_enabled", False)):
                dp_keep = max(1, int(getattr(cfg, "dp_good_for_bars", 2)))
                dp_start = max(0, i - dp_keep + 1)
                dp_ok = any(_dp_inside_any_zone(k) for k in range(dp_start, i + 1))
                if not dp_ok:
                    _debug_gate_fail(f"block: DP gate (window={dp_keep} bars)")
                    _count_block("dp_inside_zone_gate")
                    _trace_gate(f"block: DP gate (window={dp_keep} bars)")
                    still_pending.append(p)
                    _pg()
                    continue
            # Level Acceptance anchoring
            # strict: ST today or yesterday
            # rolling: any ST in recent anchor window (bounded, after maturity bar)
            if st_on:
                anchor_mode = str(getattr(cfg, "level_acceptance_anchor_mode", "strict") or "strict").strip().lower()
                if anchor_mode == "rolling":
                    anchor_window = max(1, int(getattr(cfg, "level_acceptance_anchor_window", cfg.level_acceptance_window)))
                    anchor_start = max(maturity_bar + 1, i - anchor_window + 1)
                    if sheet_prefetched_ak_arr is not None:
                        au_anchor_ok = bool(np.any(sheet_prefetched_ak_arr[anchor_start : i + 1]))
                    else:
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
                # Rolling AK window: keep legacy anchor selection (not the sheet single-row DL formula).
                anchor_zone_low = zl_i if ak_today and ok_i else (zl_im1 if ak_yesterday and ok_im1 else (zl_i if ok_i else zone_low))
            elif st_on:
                # Sheet BG: IF(OR(AK_today, AK_yesterday), COUNTIF(last N closes, ">" & IF(AK_today, DL_today, DL_yesterday)) >= k, FALSE).
                # DL is the gated active-zone lower (same as column DL when ROW-DG meets as-of lag), not raw DE or zone_low fallback.
                dl_today = float(zl_i) if ok_i else float("nan")
                dl_prev = float(zl_im1) if (i >= 1 and ok_im1) else float("nan")
                anchor_zone_low = dl_today if ak_today else dl_prev
            else:
                anchor_zone_low = zl_i if ok_i else zone_low
            if cfg.level_acceptance_required > 0:
                if not au_anchor_ok:
                    _debug_gate_fail("block: BG anchor (no AK today/yesterday)")
                    _count_block("level_acceptance_no_anchor")
                    _trace_gate("block: BG anchor (no AK today/yesterday)")
                    if debug_entry and debug_date_prefix in maturity_date:
                        print(f"[DEBUG-ENTRY] {sym} bar {i}: zone ${zc:.2f} BLOCKED by level_acceptance (anchor_mode={getattr(cfg, 'level_acceptance_anchor_mode', 'strict')})")
                    still_pending.append(p)
                    _pg()
                    continue
                if not np.isfinite(anchor_zone_low):
                    _debug_gate_fail("block: BG anchor (no DL / gated lower)")
                    _count_block("level_acceptance_no_dl")
                    _trace_gate("block: BG anchor (no DL / gated lower)")
                    if debug_entry and debug_date_prefix in maturity_date:
                        print(f"[DEBUG-ENTRY] {sym} bar {i}: zone ${zc:.2f} BLOCKED by level_acceptance (no DL anchor)")
                    still_pending.append(p)
                    _pg()
                    continue
                # Evaluate BG parity (sheet): COUNTIF over the current row window, not maturity window.
                # Sheet form: COUNTIF(H[t-window+1:t], ">" & anchor_zone_low) >= required (strict ">" vs zone lower).
                start = max(0, i - cfg.level_acceptance_window + 1)
                closes_above = int(np.sum(close_arr[start : i + 1] > anchor_zone_low))
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
                        f"block: BG ratio ({closes_above}/{cfg.level_acceptance_window}<{cfg.level_acceptance_required})"
                    )
                    _count_block("level_acceptance_ratio")
                    _trace_gate(
                        f"block: BG ratio ({closes_above}/{cfg.level_acceptance_window}<{cfg.level_acceptance_required})"
                    )
                    if debug_entry and debug_date_prefix in maturity_date:
                        print(f"[DEBUG-ENTRY] {sym} bar {i}: zone ${zc:.2f} BLOCKED by level_acceptance ({closes_above}/{cfg.level_acceptance_window} < {cfg.level_acceptance_required})")
                    still_pending.append(p)
                    _pg()
                    continue
            # Tight Range Qualifier: block levels that mature in structurally compressed environments
            if cfg.tight_range_enabled:
                start_idx = max(0, maturity_bar - cfg.tight_range_lookback + 1)
                if maturity_bar - start_idx + 1 < cfg.tight_range_lookback:
                    _count_block("tight_range_not_enough_bars")
                    _trace_gate("block: tight_range_not_enough_bars")
                    if debug_entry and debug_date_prefix in maturity_date:
                        print(f"[DEBUG-ENTRY] {sym} bar {i}: zone ${zc:.2f} BLOCKED by tight_range (not enough bars)")
                    if getattr(cfg, "emit_would_have", False) and (i + 1) < n:
                        would_have.append({
                            "SYMBOL": sym,
                            "MATURITY_DATE": index_iso[maturity_bar][:4] + "-" + index_iso[maturity_bar][4:6] + "-" + index_iso[maturity_bar][6:8],
                            "ZONE_CENTER": zc,
                            "WOULD_ENTER_DATE": index_iso[i + 1][:4] + "-" + index_iso[i + 1][4:6] + "-" + index_iso[i + 1][6:8],
                            "REJECT_REASON": "TIGHT_RANGE",
                        })
                    still_pending.append(p)
                    _pg()
                    continue
                window_high = float(np.max(high_arr[start_idx : maturity_bar + 1]))
                window_low = float(np.min(low_arr[start_idx : maturity_bar + 1]))
                if window_low <= 0:
                    _count_block("tight_range_invalid_window_low")
                    _trace_gate("block: tight_range_invalid_window_low")
                    if getattr(cfg, "emit_would_have", False) and (i + 1) < n:
                        would_have.append({
                            "SYMBOL": sym,
                            "MATURITY_DATE": index_iso[maturity_bar][:4] + "-" + index_iso[maturity_bar][4:6] + "-" + index_iso[maturity_bar][6:8],
                            "ZONE_CENTER": zc,
                            "WOULD_ENTER_DATE": index_iso[i + 1][:4] + "-" + index_iso[i + 1][4:6] + "-" + index_iso[i + 1][6:8],
                            "REJECT_REASON": "TIGHT_RANGE",
                        })
                    still_pending.append(p)
                    _pg()
                    continue
                range_pct = (window_high / window_low) - 1
                if range_pct <= cfg.tight_range_threshold_pct:
                    _count_block("tight_range_threshold")
                    _trace_gate(f"block: tight_range_threshold ({range_pct:.4f}<={cfg.tight_range_threshold_pct:.4f})")
                    if debug_entry and debug_date_prefix in maturity_date:
                        print(f"[DEBUG-ENTRY] {sym} bar {i}: zone ${zc:.2f} BLOCKED by tight_range ({range_pct:.1%} <= {cfg.tight_range_threshold_pct:.1%})")
                    if getattr(cfg, "emit_would_have", False) and (i + 1) < n:
                        would_have.append({
                            "SYMBOL": sym,
                            "MATURITY_DATE": index_iso[maturity_bar][:4] + "-" + index_iso[maturity_bar][4:6] + "-" + index_iso[maturity_bar][6:8],
                            "ZONE_CENTER": zc,
                            "WOULD_ENTER_DATE": index_iso[i + 1][:4] + "-" + index_iso[i + 1][4:6] + "-" + index_iso[i + 1][6:8],
                            "REJECT_REASON": "TIGHT_RANGE",
                        })
                    still_pending.append(p)
                    _pg()
                    continue
            # Growth filter (hard gate): price today >= price growth_bars days ago; if no history (i < growth_bars), don't buy
            growth_pct: Optional[float] = None
            if _eval_bar >= cfg.growth_bars:
                price_now = close_arr[_eval_bar]
                price_ago = close_arr[_eval_bar - cfg.growth_bars]
                if price_ago > 0:
                    growth_pct = (price_now - price_ago) / price_ago * 100.0
            if cfg.growth_filter_enabled:
                if _eval_bar < cfg.growth_bars:
                    _count_block("growth_not_enough_history")
                    _trace_gate("block: growth_not_enough_history")
                    if debug_entry and debug_date_prefix in maturity_date:
                        print(f"[DEBUG-ENTRY] {sym} bar {i}: zone ${zc:.2f} BLOCKED by growth_filter (not enough history)")
                    if getattr(cfg, "emit_would_have", False) and (i + 1) < n:
                        would_have.append({
                            "SYMBOL": sym,
                            "MATURITY_DATE": index_iso[maturity_bar][:4] + "-" + index_iso[maturity_bar][4:6] + "-" + index_iso[maturity_bar][6:8],
                            "ZONE_CENTER": zc,
                            "WOULD_ENTER_DATE": index_iso[i + 1][:4] + "-" + index_iso[i + 1][4:6] + "-" + index_iso[i + 1][6:8],
                            "REJECT_REASON": "GROWTH",
                        })
                    still_pending.append(p)
                    _pg()
                    continue
                if growth_pct is None:
                    _count_block("growth_no_data")
                    _trace_gate("block: growth_no_data")
                    if debug_entry and debug_date_prefix in maturity_date:
                        print(f"[DEBUG-ENTRY] {sym} bar {i}: zone ${zc:.2f} BLOCKED by growth_filter (no growth data)")
                    if getattr(cfg, "emit_would_have", False) and (i + 1) < n:
                        would_have.append({
                            "SYMBOL": sym,
                            "MATURITY_DATE": index_iso[maturity_bar][:4] + "-" + index_iso[maturity_bar][4:6] + "-" + index_iso[maturity_bar][6:8],
                            "ZONE_CENTER": zc,
                            "WOULD_ENTER_DATE": index_iso[i + 1][:4] + "-" + index_iso[i + 1][4:6] + "-" + index_iso[i + 1][6:8],
                            "REJECT_REASON": "GROWTH",
                        })
                    still_pending.append(p)
                    _pg()
                    continue
                if close_arr[_eval_bar] < close_arr[_eval_bar - cfg.growth_bars]:
                    _count_block("growth_filter_fail")
                    _trace_gate(
                        f"block: growth_filter_fail ({close_arr[_eval_bar]:.4f}<{close_arr[_eval_bar - cfg.growth_bars]:.4f})"
                    )
                    if debug_entry and debug_date_prefix in maturity_date:
                        print(f"[DEBUG-ENTRY] {sym} bar {i}: zone ${zc:.2f} BLOCKED by growth_filter ({close_arr[_eval_bar]:.2f} < {close_arr[_eval_bar - cfg.growth_bars]:.2f})")
                    if getattr(cfg, "emit_would_have", False) and (i + 1) < n:
                        would_have.append({
                            "SYMBOL": sym,
                            "MATURITY_DATE": index_iso[maturity_bar][:4] + "-" + index_iso[maturity_bar][4:6] + "-" + index_iso[maturity_bar][6:8],
                            "ZONE_CENTER": zc,
                            "WOULD_ENTER_DATE": index_iso[i + 1][:4] + "-" + index_iso[i + 1][4:6] + "-" + index_iso[i + 1][6:8],
                            "REJECT_REASON": "GROWTH",
                        })
                    still_pending.append(p)
                    _pg()
                    continue

            # Rolling Average Displacement filter: require price sufficiently away from 100-bar rolling mean (avoid stuck/equilibrium)
            displacement_pct = None
            rb = cfg.displacement_rolling_bars
            if cfg.displacement_filter_enabled:
                if maturity_bar < rb - 1:
                    _count_block("displacement_not_enough_bars")
                    still_pending.append(p)
                    _pg()
                    continue
                close_at_maturity = close_arr[maturity_bar]
                roll_slice = close_arr[maturity_bar - rb + 1 : maturity_bar + 1]
                rolling_avg = float(np.mean(roll_slice))
                if rolling_avg <= 0:
                    _count_block("displacement_invalid_rolling_avg")
                    still_pending.append(p)
                    _pg()
                    continue
                displacement_pct = abs(close_at_maturity / rolling_avg - 1.0)
                if displacement_pct < cfg.displacement_threshold_pct:
                    _count_block("displacement_below_threshold")
                    still_pending.append(p)
                    _pg()
                    continue
            else:
                if maturity_bar >= rb - 1:
                    close_at_maturity = close_arr[maturity_bar]
                    roll_slice = close_arr[maturity_bar - rb + 1 : maturity_bar + 1]
                    rolling_avg = float(np.mean(roll_slice))
                    if rolling_avg > 0:
                        displacement_pct = abs(close_at_maturity / rolling_avg - 1.0)
            # Consolidation Blocker: block Rocket Buy when active on this bar
            if getattr(cfg, "consolidation_blocker_enabled", True) and cb_active:
                _count_block("consolidation_blocker")
                _trace_gate("block: consolidation_blocker")
                if debug_entry and debug_date_prefix in maturity_date:
                    print(f"[DEBUG-ENTRY] {sym} bar {i}: zone ${zc:.2f} BLOCKED by consolidation_blocker")
                if getattr(cfg, "emit_would_have", False) and (i + 1) < n:
                    would_have.append({
                        "SYMBOL": sym,
                        "MATURITY_DATE": index_iso[maturity_bar][:4] + "-" + index_iso[maturity_bar][4:6] + "-" + index_iso[maturity_bar][6:8],
                        "ZONE_CENTER": zc,
                        "WOULD_ENTER_DATE": index_iso[i + 1][:4] + "-" + index_iso[i + 1][4:6] + "-" + index_iso[i + 1][6:8],
                        "REJECT_REASON": "CONSOLIDATION",
                    })
                still_pending.append(p)
                _pg()
                continue
            
            if debug_entry and debug_date_prefix in maturity_date:
                print(f"[DEBUG-ENTRY] {sym} bar {i} ({index_iso[i][:10]}): zone ${zc:.2f} PASSED all filters, checking entry...")
            _trace_gate("pass: all gates, proceeding to entry checks")

            _pg()
            _t_e = time.perf_counter() if _pbt is not None else 0.0

            def _pe() -> None:
                if _pbt is not None:
                    _acc_bt("bt_pending_entry", time.perf_counter() - _t_e)

            # Entry at next bar open. Stop/target: percent-based (stop_pct/target_pct) or ATR-based when atr_* > 0
            entry_price = next_op
            # Use signal bar low (close-above day) for stop, not maturity bar low
            trigger_bar_low = low_arr[_i_bar]
            # Entry is always bar _i_bar+1 (same as outer next_op); ATR at entry uses that bar index.
            atr_14_at_entry_val = float(atr_14_arr[_i_bar + 1]) if (_i_bar + 1 < n and not (atr_14_arr[_i_bar + 1] != atr_14_arr[_i_bar + 1])) else None
            # Allow mixing: ATR stop and/or ATR target can independently override the percent-based values
            atr_pct = None
            if atr_14_at_entry_val is not None and entry_price > 0:
                atr_pct = (atr_14_at_entry_val / entry_price) * 100.0

            # Target price
            if getattr(cfg, "atr_target", 0.0) > 0 and atr_pct is not None:
                target_price = entry_price * (1.0 + atr_pct * cfg.atr_target / 100.0)
            else:
                target_price = entry_price * cfg.target_pct

            # Stop price
            if getattr(cfg, "atr_stop", 0.0) > 0 and atr_pct is not None:
                stop_price = entry_price * (1.0 - atr_pct * cfg.atr_stop / 100.0)
            else:
                stop_price = trigger_bar_low * cfg.stop_pct if cfg.stop_pct_is_multiplier else trigger_bar_low * (1 - cfg.stop_pct)
            mat_iso = index_iso[maturity_bar]
            maturity_date = f"{mat_iso[:4]}-{mat_iso[4:6]}-{mat_iso[6:8]}" if len(mat_iso) >= 8 else mat_iso
            _ca_iso = index_iso[_eval_bar]
            close_above_date = f"{_ca_iso[:4]}-{_ca_iso[4:6]}-{_ca_iso[6:8]}" if len(_ca_iso) >= 8 else _ca_iso

            # Pivot sequence in zone: strong setup = 2–3 H then 1–2 L before entry
            zh = float(zc) * (1 + cfg.band_pct) if pd.notna(zc) else zl
            _t_ps = time.perf_counter() if _pbt is not None else 0.0
            _, pivot_high_run, pivot_low_run, pivot_switch = _pivot_sequence_in_zone(
                maturity_bar, zl, zh, ph_arr, pl_arr
            )
            if _pbt is not None:
                _acc_bt("bt_pending_pivot_sequence", time.perf_counter() - _t_ps)
            # Min pivot run L/H and pivot_switch filter
            if getattr(cfg, "min_pivot_run_l_before_entry", 0) > 0 and pivot_low_run < cfg.min_pivot_run_l_before_entry:
                _count_block("min_pivot_run_low")
                still_pending.append(p)
                _pe()
                continue
            if getattr(cfg, "min_pivot_run_h_before_entry", 0) > 0 and pivot_high_run < cfg.min_pivot_run_h_before_entry:
                _count_block("min_pivot_run_high")
                still_pending.append(p)
                _pe()
                continue
            if getattr(cfg, "pivot_switch_h_to_l_filter", -1) >= 0:
                want_true = cfg.pivot_switch_h_to_l_filter == 1
                if pivot_switch != want_true:
                    _count_block("pivot_switch_filter")
                    still_pending.append(p)
                    _pe()
                    continue
            # Min hist ann ROR avg for this symbol (prior closed trades)
            if getattr(cfg, "min_hist_ann_ror_avg", -100.0) > -100.0:
                hist_ann_ror = _get_hist_ann_ror()
                if hist_ann_ror < cfg.min_hist_ann_ror_avg:
                    _count_block("min_hist_ann_ror_avg")
                    still_pending.append(p)
                    _pe()
                    continue

            _t_ent_bld = time.perf_counter() if _pbt is not None else 0.0
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
                getattr(cfg, "strong_pivots_enabled", True)
                and not getattr(cfg, "realtime_filter_enabled", False)
                and _strong_pivot_mode_has_active_params(
                    getattr(cfg, "strong_pivot_mode", "pre"),
                    int(getattr(cfg, "strong_pre_pivot_bars", 0)),
                    float(getattr(cfg, "strong_pre_pivot_pct", 0.0)),
                    int(getattr(cfg, "strong_post_pivot_bars", 0)),
                    float(getattr(cfg, "strong_post_pivot_pct", 0.0)),
                )
            ):
                mb = maturity_bar
                if mb < n and ph_arr[mb] > 0.0:
                    if _strong_pivot_bar_ok(
                        mb, "PH", high_arr, low_arr, n,
                        pre_bars=int(cfg.strong_pre_pivot_bars),
                        pre_pct=float(cfg.strong_pre_pivot_pct),
                        post_bars=int(cfg.strong_post_pivot_bars),
                        post_pct=float(cfg.strong_post_pivot_pct),
                        mode=str(cfg.strong_pivot_mode),
                    ):
                        entry_pivot_was_strong = 1
                elif mb < n and pl_arr[mb] > 0.0:
                    if _strong_pivot_bar_ok(
                        mb, "PL", high_arr, low_arr, n,
                        pre_bars=int(cfg.strong_pre_pivot_bars),
                        pre_pct=float(cfg.strong_pre_pivot_pct),
                        post_bars=int(cfg.strong_post_pivot_bars),
                        post_pct=float(cfg.strong_post_pivot_pct),
                        mode=str(cfg.strong_pivot_mode),
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
                    valid = ~np.isnan(window) & (window > 0)
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
            trigger_bottom = zc_f * (1 - cfg.band_pct)
            current_zone_top = zc_f * (1 + cfg.band_pct)
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
                    min_zone_above_center = current_zone_top / (1 - cfg.band_pct)
                    above_vals = window[window >= min_zone_above_center]
                    below_vals = window[window < trigger_bottom]
                    if len(above_vals) > 0:
                        zone_above_center = float(np.min(above_vals))
                        bottom_above = zone_above_center * (1 - cfg.band_pct)
                        pct_entry_to_bottom_zone_above = (bottom_above - entry_price) / entry_price * 100.0
                    if len(below_vals) > 0:
                        zone_below_center = float(np.max(below_vals))
                        top_below = zone_below_center * (1 + cfg.band_pct)
                        pct_drop_to_top_zone_below = (entry_price - top_below) / entry_price * 100.0
                    if zone_entries_debug is not None:
                        entry_date_iso = next_iso[:4] + "-" + next_iso[4:6] + "-" + next_iso[6:8] if len(next_iso) >= 8 else next_iso
                        all_zones_str = ",".join(f"{x:.4f}" for x in np.unique(window))
                        bottom_above_val = zone_above_center * (1 - cfg.band_pct) if zone_above_center else 0.0
                        zone_entries_debug.append({
                            "ENTRY_DATE": entry_date_iso,
                            "ENTRY_PRICE": round(entry_price, 4),
                            "ZONE_CENTER": round(zc_f, 4),
                            "ZONE_LOW": round(zc_f * (1 - cfg.band_pct), 4),
                            "ZONE_HIGH": round(zc_f * (1 + cfg.band_pct), 4),
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

            # Relative volume on trigger bar (bar i = maturity/6th-touch bar)
            rel_vol_trigger: Optional[float] = None
            if volume_arr is not None and i < n:
                v_tr = volume_arr[i]
                if not (v_tr != v_tr):  # not NaN
                    start_10 = max(0, i - 9)
                    slice_10 = volume_arr[start_10 : i + 1]
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
            # Min rel_vol at entry filter (-2 = no op)
            if getattr(cfg, "min_rel_vol_at_entry", -2.0) > -2.0:
                if rel_vol is None or rel_vol < cfg.min_rel_vol_at_entry:
                    still_pending.append(p)
                    if _pbt is not None:
                        _acc_bt("bt_pending_entry_build", time.perf_counter() - _t_ent_bld)
                    _pe()
                    continue

            # --- Per-trigger-bar technical metrics for correlation analysis (no future bars) ---
            # Use the maturity/6th-touch bar index i as "trigger" context
            z_score_trigger: float = 0.0
            upper_wick_atr_trigger: float = 0.0
            lower_wick_atr_trigger: float = 0.0
            is_20bar_high_trigger: int = 0
            is_20bar_low_trigger: int = 0
            move_body_atr_trigger: float = 0.0
            try:
                if 0 <= i < n:
                    cl_i = close_arr[i]
                    op_i = open_arr[i]
                    hi_i = high_arr[i]
                    lo_i = low_arr[i]
                    # Z-score vs recent closes
                    lookback_z = 20
                    start_z = max(0, i - lookback_z + 1)
                    closes_slice = close_arr[start_z : i + 1]
                    if closes_slice.size > 1:
                        mean_close = float(np.nanmean(closes_slice))
                        std_close = float(np.nanstd(closes_slice))
                        if std_close > 0:
                            z_score_trigger = float((cl_i - mean_close) / std_close)
                    # Wick sizes vs ATR at trigger bar
                    atr_tr = float(atr_14_arr[i]) if not (atr_14_arr[i] != atr_14_arr[i]) else 0.0  # NaN check
                    upper_wick = max(0.0, hi_i - max(op_i, cl_i))
                    lower_wick = max(0.0, min(op_i, cl_i) - lo_i)
                    if atr_tr > 0:
                        upper_wick_atr_trigger = upper_wick / atr_tr
                        lower_wick_atr_trigger = lower_wick / atr_tr
                    # 20-bar range position
                    start_rng = max(0, i - 19)
                    hi_slice = high_arr[start_rng : i + 1]
                    lo_slice = low_arr[start_rng : i + 1]
                    if hi_slice.size > 0 and lo_slice.size > 0:
                        if hi_i >= float(np.nanmax(hi_slice)):
                            is_20bar_high_trigger = 1
                        if lo_i <= float(np.nanmin(lo_slice)):
                            is_20bar_low_trigger = 1
                    # ATR-scaled move vs previous close
                    if i > 0 and atr_tr > 0:
                        prev_close = close_arr[i - 1]
                        move_body_atr_trigger = abs(cl_i - prev_close) / atr_tr
            except Exception:
                # Metrics are best-effort; failures should not block trades
                pass

            _maj_mode = _normalize_entry_filter_tri_state(
                getattr(cfg, "entry_filter_major_pivot", "both"), "entry_filter_major_pivot"
            )
            if _maj_mode == "true" and entry_major_pivot != 1:
                _count_block("entry_filter_major_pivot")
                _trace_gate("block: entry_filter_major_pivot (require ENTRY_MAJOR_PIVOT==1)")
                still_pending.append(p)
                if _pbt is not None:
                    _acc_bt("bt_pending_entry_build", time.perf_counter() - _t_ent_bld)
                _pe()
                continue
            if _maj_mode == "false" and entry_major_pivot != 0:
                _count_block("entry_filter_major_pivot")
                _trace_gate("block: entry_filter_major_pivot (require ENTRY_MAJOR_PIVOT==0)")
                still_pending.append(p)
                if _pbt is not None:
                    _acc_bt("bt_pending_entry_build", time.perf_counter() - _t_ent_bld)
                _pe()
                continue

            _hi_mode = _normalize_entry_filter_tri_state(
                getattr(cfg, "entry_filter_is_20bar_high_at_trigger", "both"),
                "entry_filter_is_20bar_high_at_trigger",
            )
            if _hi_mode == "true" and is_20bar_high_trigger != 1:
                _count_block("entry_filter_20bar_high")
                _trace_gate("block: entry_filter_20bar_high (require IS_20BAR_HIGH_AT_TRIGGER==1)")
                still_pending.append(p)
                if _pbt is not None:
                    _acc_bt("bt_pending_entry_build", time.perf_counter() - _t_ent_bld)
                _pe()
                continue
            if _hi_mode == "false" and is_20bar_high_trigger != 0:
                _count_block("entry_filter_20bar_high")
                _trace_gate("block: entry_filter_20bar_high (require IS_20BAR_HIGH_AT_TRIGGER==0)")
                still_pending.append(p)
                if _pbt is not None:
                    _acc_bt("bt_pending_entry_build", time.perf_counter() - _t_ent_bld)
                _pe()
                continue

            # Beta at entry (for real-time filter and for trade field)
            if benchmark_df is not None:
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

            # --- Optional real-time-style predictive filter based on weighted metrics ---
            if getattr(cfg, "realtime_filter_enabled", False):
                use_z = getattr(cfg, "realtime_filter_use_zscore", True) and reference_stats
                score = 0.0
                # Existing structural metrics at entry (z-score when reference_stats available so scale doesn't dominate)
                score += getattr(cfg, "weight_touch_count_minor", 0.0) * _realtime_score_value(tc_minor, "TOUCH_COUNT_MINOR", reference_stats, use_z)
                score += getattr(cfg, "weight_zone_cluster_density", 0.0) * _realtime_score_value(cluster_density, "ZONE_CLUSTER_DENSITY", reference_stats, use_z)
                score += getattr(cfg, "weight_nearby_zones_above", 0.0) * _realtime_score_value(nearby_above, "NEARBY_ZONES_ABOVE", reference_stats, use_z)
                score += getattr(cfg, "weight_touch_count_major", 0.0) * _realtime_score_value(tc_major, "TOUCH_COUNT_MAJOR", reference_stats, use_z)
                score += getattr(cfg, "weight_pct_entry_to_bottom_zone_above", 0.0) * _realtime_score_value(pct_entry_to_bottom_zone_above, "PCT_ENTRY_TO_BOTTOM_ZONE_ABOVE", reference_stats, use_z)
                score += getattr(cfg, "weight_nearby_zones_below", 0.0) * _realtime_score_value(nearby_below, "NEARBY_ZONES_BELOW", reference_stats, use_z)
                # Per-trigger and entry metrics
                score += getattr(cfg, "weight_z_score_at_trigger", 0.0) * _realtime_score_value(z_score_trigger, "Z_SCORE_AT_TRIGGER", reference_stats, use_z)
                score += getattr(cfg, "weight_pivot_run_l_before_entry", 0.0) * _realtime_score_value(pivot_low_run, "PIVOT_RUN_L_BEFORE_ENTRY", reference_stats, use_z)
                score += getattr(cfg, "weight_pct_drop_to_top_zone_below", 0.0) * _realtime_score_value(pct_drop_to_top_zone_below, "PCT_DROP_TO_TOP_ZONE_BELOW", reference_stats, use_z)
                score += getattr(cfg, "weight_rel_vol_at_entry", 0.0) * _realtime_score_value(rel_vol, "REL_VOL_AT_ENTRY", reference_stats, use_z)
                score += getattr(cfg, "weight_displacement_pct_at_entry", 0.0) * _realtime_score_value(displacement_pct, "DISPLACEMENT_PCT_AT_ENTRY", reference_stats, use_z)
                score += getattr(cfg, "weight_lower_wick_atr_at_trigger", 0.0) * _realtime_score_value(lower_wick_atr_trigger, "LOWER_WICK_ATR_AT_TRIGGER", reference_stats, use_z)
                score += getattr(cfg, "weight_growth_pct_over_period", 0.0) * _realtime_score_value(growth_pct, "GROWTH_PCT_OVER_PERIOD", reference_stats, use_z)
                score += getattr(cfg, "weight_beta_at_entry", 0.0) * _realtime_score_value(beta_at_entry_val, "BETA_AT_ENTRY", reference_stats, use_z)
                if score < getattr(cfg, "realtime_filter_threshold", 0.0):
                    _count_block("realtime_filter_threshold")
                    # Treat as if entry filter failed; leave pending for future opportunities
                    still_pending.append(p)
                    if _pbt is not None:
                        _acc_bt("bt_pending_entry_build", time.perf_counter() - _t_ent_bld)
                    _pe()
                    continue

            if _i_bar + 1 == n - 1:
                scanner.append({
                    "symbol": sym,
                    "date": next_iso,
                    "close": cl,
                    "stop": stop_price,
                    "target": target_price,
                    "zone_center": zc,
                    "maturity_date": maturity_date,
                    "close_above_date": close_above_date,
                })
            else:
                max_high_since_entry = entry_price
                sheet_rung = _sheet_ladder_rung_at_signal_bar(
                    ladder_pack, _i_bar, maturity_bar, float(zc), cfg.band_pct
                )
                open_trade = BRTTrade(
                    symbol=sym,
                    date_opened=next_iso,
                    entry_price=entry_price,
                    stop_price=stop_price,
                    target_price=target_price,
                    zone_center=zc,
                    touch_count=tc,
                    touch_count_major=tc_major,
                    touch_count_minor=tc_minor,
                    touch_count_short=tcs,
                    is_tradeable_key_level=is_ac,
                    struct_high=sh,
                    struct_low=sl,
                    entry_pivot_type=pivot_type,
                    entry_struct_regime=struct_regime,
                    entry_major_pivot=entry_major_pivot,
                    entry_pivot_was_strong=entry_pivot_was_strong,
                    entry_zone_was_strong_pivot=1 if getattr(cfg, "strong_pivots_enabled", True) else 0,
                    nearby_zones_above=nearby_above,
                    nearby_zones_below=nearby_below,
                    zone_cluster_density=cluster_density,
                    maturity_date=maturity_date,
                    close_above_date=close_above_date,
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
                    atr_14_at_entry=float(atr_14_arr[_i_bar + 1]) if (_i_bar + 1 < n and not (atr_14_arr[_i_bar + 1] != atr_14_arr[_i_bar + 1])) else None,
                    z_score_at_trigger=z_score_trigger,
                    upper_wick_atr_at_trigger=upper_wick_atr_trigger,
                    lower_wick_atr_at_trigger=lower_wick_atr_trigger,
                    is_20bar_high_at_trigger=is_20bar_high_trigger,
                    is_20bar_low_at_trigger=is_20bar_low_trigger,
                    move_body_atr_at_trigger=move_body_atr_trigger,
                    beta_at_entry=beta_at_entry_val,
                    sheet_ladder_rung_at_signal=sheet_rung,
                )
            if _pbt is not None:
                _acc_bt("bt_pending_entry_build", time.perf_counter() - _t_ent_bld)
            _pe()
            break
        if _pbt is not None:
            _acc_bt("bt_loop_pending_for", time.perf_counter() - _t_pfor)
        pending_maturities = still_pending
        _acc_bt("bt_loop_bar_total", time.perf_counter() - _t_bar)

    if profile_block_reasons is not None:
        for k, v in _block_reasons.items():
            profile_block_reasons[k] = profile_block_reasons.get(k, 0) + int(v)
    watchlist = _build_brt_watchlist(
        sym, scanner, pending_maturities, cfg, n, index_iso, close_arr, open_arr, high_arr, low_arr
    )
    return closed, open_trade, scanner, short_candidates, would_have, watchlist


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


def load_all_tickers(data_dir: str, pattern: str = "*.csv", max_workers: int | None = 8) -> dict[str, pd.DataFrame]:
    """Load all ticker CSVs (skip SPY). Uses ThreadPoolExecutor when max_workers > 1 for faster I/O."""
    data_path = Path(data_dir)
    files = [f for f in data_path.glob(pattern) if f.stem.upper() != "SPY"]
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


def _enrich_trades_yfinance(closed: list[BRTTrade], open_trades: list[BRTTrade]) -> None:
    """Fetch market_cap, sector, industry, beta from yfinance. Uses local cache file to minimize API calls.
    - Check cache first: if we have data with as_of_date=today, use it (no API call).
    - If cache miss or stale (previous day), call yfinance and update cache.
    Market cap is adjusted to entry date: current_market_cap * (entry_price / current_price)."""
    try:
        import yfinance as yf
    except ImportError:
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
    for sym in symbols_to_fetch:
        try:
            ticker = yf.Ticker(sym)
            info = getattr(ticker, "info", None) or {}
            current_price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
            if current_price is not None:
                try:
                    current_price = float(current_price)
                except (TypeError, ValueError):
                    current_price = None
            cache[sym] = {
                "market_cap": info.get("marketCap"),
                "current_price": current_price,
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "beta": info.get("beta"),
                "as_of_date": today,
            }
        except Exception:
            cache[sym] = {}
    # Persist updated cache (merge file_cache with new fetches)
    if symbols_to_fetch:
        merged = dict(file_cache)
        for sym, data in cache.items():
            if data.get("as_of_date") == today:
                merged[sym] = data
        _save_yfinance_cache(merged)
    # Helper: set market_cap on trade, adjusted to entry date when we have current cap and current price
    def _set_market_cap_and_rest(trade: BRTTrade, c: dict) -> None:
        mc = c.get("market_cap")
        if mc is not None:
            try:
                mc_float = float(mc)
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
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        header = [
            "SYMBOL", "DATE_OPENED", "ENTRY_PRICE", "STOP_PRICE", "TARGET_PRICE",
            "DATE_CLOSED", "EXIT_PRICE", "EXIT_TYPE", "DAYS_HELD", "PNL_PCT", "PNL_DOLLARS",
            "ANN_ROR_PCT", "MAX_PRICE",
            "HIST_TRADES", "HIST_PNL_PCT_AVG", "HIST_ANN_ROR_AVG",
            "ZONE_CENTER", "TOUCH_COUNT", "TOUCH_COUNT_SHORT", "TOUCH_COUNT_MAJOR", "TOUCH_COUNT_MINOR", "IS_TRADEABLE_KEY_LEVEL_AC",
            "STRUCT_HIGH", "STRUCT_LOW",
            "ENTRY_PIVOT_TYPE", "ENTRY_STRUCT_REGIME", "ENTRY_MAJOR_PIVOT", "ENTRY_PIVOT_WAS_STRONG", "ENTRY_ZONE_WAS_STRONG_PIVOT",
            "NEARBY_ZONES_ABOVE", "NEARBY_ZONES_BELOW", "ZONE_CLUSTER_DENSITY",
            "MATURITY_DATE", "CLOSE_ABOVE_DATE", "SHEET_LADDER_RUNG",
            "GROWTH_PCT_OVER_PERIOD",
            "DISPLACEMENT_PCT_AT_ENTRY",
            "PIVOT_RUN_H_BEFORE_ENTRY", "PIVOT_RUN_L_BEFORE_ENTRY", "PIVOT_SWITCH_H_TO_L",
            "ZONE_ABOVE_CENTER", "ZONE_BELOW_CENTER",
            "PCT_ENTRY_TO_BOTTOM_ZONE_ABOVE", "PCT_DROP_TO_TOP_ZONE_BELOW",
            "VOLUME_AT_ENTRY", "AVG_VOLUME_10D_AT_ENTRY", "REL_VOL_AT_ENTRY", "REL_VOL_ON_TRIGGER",
            "ATR_14_AT_ENTRY", "ATR_PCT_AT_ENTRY",
            "MARKET_CAP", "SECTOR", "INDUSTRY", "BETA", "BETA_AT_ENTRY",
            "Z_SCORE_AT_TRIGGER", "UPPER_WICK_ATR_AT_TRIGGER", "LOWER_WICK_ATR_AT_TRIGGER",
            "IS_20BAR_HIGH_AT_TRIGGER", "IS_20BAR_LOW_AT_TRIGGER", "MOVE_BODY_ATR_AT_TRIGGER",
        ]
        if z_cols:
            header = header + z_cols
        w.writerow(header)
        for t in closed:
            md = getattr(t, "maturity_date", "") or ""
            cd = getattr(t, "close_above_date", "") or ""
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
                t.symbol, t.date_opened, f"{t.entry_price:.2f}", f"{t.stop_price:.2f}", f"{t.target_price:.2f}",
                t.date_closed, f"{t.exit_price:.2f}", t.exit_type, t.days_held, f"{t.pnl_pct:.2f}%", f"{t.pnl_dollars:.2f}",
                ann_ror_str, max_price_str,
                hist_n, f"{hist_avg:.2f}" if hist_n else "", f"{hist_ann_ror:.2f}" if hist_n else "",
                f"{t.zone_center:.4f}", t.touch_count, t.touch_count_short, t.touch_count_major, t.touch_count_minor, 1 if t.is_tradeable_key_level else 0,
                t.struct_high, t.struct_low,
                t.entry_pivot_type, t.entry_struct_regime, t.entry_major_pivot, getattr(t, "entry_pivot_was_strong", 0), getattr(t, "entry_zone_was_strong_pivot", 0),
                t.nearby_zones_above, t.nearby_zones_below, t.zone_cluster_density,
                md, cd,
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
                atr_str, atr_pct_str,
                f"{getattr(t, 'market_cap', None):.0f}" if getattr(t, "market_cap", None) is not None else "",
                (getattr(t, "sector", None) or "").replace(",", " "),
                (getattr(t, "industry", None) or "").replace(",", " "),
                f"{getattr(t, 'beta', None):.4f}" if getattr(t, "beta", None) is not None else "",
                f"{getattr(t, 'beta_at_entry', None):.4f}" if getattr(t, "beta_at_entry", None) is not None else "",
                f"{getattr(t, 'z_score_at_trigger', 0.0):.4f}",
                f"{getattr(t, 'upper_wick_atr_at_trigger', 0.0):.4f}",
                f"{getattr(t, 'lower_wick_atr_at_trigger', 0.0):.4f}",
                int(getattr(t, 'is_20bar_high_at_trigger', 0)),
                int(getattr(t, 'is_20bar_low_at_trigger', 0)),
                f"{getattr(t, 'move_body_atr_at_trigger', 0.0):.4f}",
            ]
            if include_zscore_cols and reference_stats:
                for ref_name in _REF_VAR_TO_ATTR:
                    attr = _REF_VAR_TO_ATTR[ref_name]
                    val = getattr(t, attr, None)
                    z = _realtime_score_value(val, ref_name, reference_stats, True)
                    row.append(f"{z:.4f}")
                if cfg is not None:
                    row.append(f"{_realtime_score_for_trade(t, cfg, reference_stats):.4f}")
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
        pnl_pct = (current_price - t.entry_price) / t.entry_price * 100.0
        pnl_dollars = (brt_cash / t.entry_price) * (current_price - t.entry_price)
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
) -> None:
    """Write BRT_Open CSV. No DATE_CLOSED/EXIT_PRICE/EXIT_TYPE. CURRENT_PRICE, DAYS_HELD, PNL_*, ANN_ROR_PCT, MAX_PRICE computed from latest data when tickers/brt_cash provided. HIST_* from closed when provided."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "SYMBOL", "DATE_OPENED", "ENTRY_PRICE", "STOP_PRICE", "TARGET_PRICE",
            "CURRENT_PRICE", "DAYS_HELD", "PNL_PCT", "PNL_DOLLARS", "ANN_ROR_PCT", "MAX_PRICE",
            "HIST_TRADES", "HIST_PNL_PCT_AVG", "HIST_ANN_ROR_AVG",
            "ZONE_CENTER", "TOUCH_COUNT", "TOUCH_COUNT_SHORT", "TOUCH_COUNT_MAJOR", "TOUCH_COUNT_MINOR", "IS_TRADEABLE_KEY_LEVEL_AC",
            "STRUCT_HIGH", "STRUCT_LOW",
            "ENTRY_PIVOT_TYPE", "ENTRY_STRUCT_REGIME", "ENTRY_MAJOR_PIVOT", "ENTRY_PIVOT_WAS_STRONG", "ENTRY_ZONE_WAS_STRONG_PIVOT",
            "NEARBY_ZONES_ABOVE", "NEARBY_ZONES_BELOW", "ZONE_CLUSTER_DENSITY",
            "MATURITY_DATE", "CLOSE_ABOVE_DATE", "SHEET_LADDER_RUNG",
            "GROWTH_PCT_OVER_PERIOD",
            "DISPLACEMENT_PCT_AT_ENTRY",
            "PIVOT_RUN_H_BEFORE_ENTRY", "PIVOT_RUN_L_BEFORE_ENTRY", "PIVOT_SWITCH_H_TO_L",
            "ZONE_ABOVE_CENTER", "ZONE_BELOW_CENTER",
            "PCT_ENTRY_TO_BOTTOM_ZONE_ABOVE", "PCT_DROP_TO_TOP_ZONE_BELOW",
            "VOLUME_AT_ENTRY", "AVG_VOLUME_10D_AT_ENTRY", "REL_VOL_AT_ENTRY", "REL_VOL_ON_TRIGGER",
            "ATR_14_AT_ENTRY", "ATR_PCT_AT_ENTRY",
            "MARKET_CAP", "SECTOR", "INDUSTRY", "BETA", "BETA_AT_ENTRY",
            "Z_SCORE_AT_TRIGGER", "UPPER_WICK_ATR_AT_TRIGGER", "LOWER_WICK_ATR_AT_TRIGGER",
            "IS_20BAR_HIGH_AT_TRIGGER", "IS_20BAR_LOW_AT_TRIGGER", "MOVE_BODY_ATR_AT_TRIGGER",
        ])
        for t in open_trades:
            md = getattr(t, "maturity_date", "") or ""
            cd = getattr(t, "close_above_date", "") or ""
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
            w.writerow([
                t.symbol, t.date_opened, f"{t.entry_price:.2f}", f"{t.stop_price:.2f}", f"{t.target_price:.2f}",
                cur_pr, days_held, pnl_pct_s, pnl_dollars_s, ann_ror_s, max_pr_s,
                hist_n, f"{hist_avg:.2f}" if hist_n else "", f"{hist_ann_ror:.2f}" if hist_n else "",
                f"{t.zone_center:.4f}", t.touch_count, t.touch_count_short, t.touch_count_major, t.touch_count_minor, 1 if t.is_tradeable_key_level else 0,
                t.struct_high, t.struct_low,
                t.entry_pivot_type, t.entry_struct_regime, t.entry_major_pivot, getattr(t, "entry_pivot_was_strong", 0), getattr(t, "entry_zone_was_strong_pivot", 0),
                t.nearby_zones_above, t.nearby_zones_below, t.zone_cluster_density,
                md, cd,
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
                atr_str, atr_pct_str,
                f"{getattr(t, 'market_cap', None):.0f}" if getattr(t, "market_cap", None) is not None else "",
                (getattr(t, "sector", None) or "").replace(",", " "),
                (getattr(t, "industry", None) or "").replace(",", " "),
                f"{getattr(t, 'beta', None):.4f}" if getattr(t, "beta", None) is not None else "",
                f"{getattr(t, 'beta_at_entry', None):.4f}" if getattr(t, "beta_at_entry", None) is not None else "",
                f"{getattr(t, 'z_score_at_trigger', 0.0):.4f}",
                f"{getattr(t, 'upper_wick_atr_at_trigger', 0.0):.4f}",
                f"{getattr(t, 'lower_wick_atr_at_trigger', 0.0):.4f}",
                int(getattr(t, 'is_20bar_high_at_trigger', 0)),
                int(getattr(t, 'is_20bar_low_at_trigger', 0)),
                f"{getattr(t, 'move_body_atr_at_trigger', 0.0):.4f}",
            ])


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
        rows.append(
            {
                "ROW_TYPE": "SCANNER",
                "SYMBOL": sym,
                "AS_OF_DATE": last_iso,
                "ENTRY_DATE": s.get("date", ""),
                "CLOSE": f"{float(s['close']):.2f}" if s.get("close") is not None else "",
                "STOP_LOSS": f"{float(s['stop']):.2f}" if s.get("stop") is not None else "",
                "TARGET": f"{float(s['target']):.2f}" if s.get("target") is not None else "",
                "ZONE_CENTER": f"{float(s.get('zone_center', 0)):.4f}" if s.get("zone_center") is not None else "",
                "ZONE_LOW": "",
                "ZONE_HIGH": "",
                "TOUCH_COUNT": "",
                "STATUS": "PASSED_ALL_GATES_ENTRY_LAST_BAR",
                "GATES_REMAINING": "",
                "TRIGGER_HINT": "All entry gates passed; next session open per BRT (last bar of data).",
                "LAST_CLOSE": f"{last_close:.2f}" if last_close == last_close else "",
                "MATURITY_DATE": str(md) if md is not None else "",
                "CLOSE_ABOVE_DATE": str(cad) if cad is not None else "",
            }
        )
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
        if last_close == last_close and last_open == last_open:
            if last_close <= last_open:
                hints.append("bullish_bar: need Close>Open on evaluation bar (typical long entry gate)")
        gb = int(getattr(cfg, "growth_bars", 0) or 0)
        if getattr(cfg, "growth_filter_enabled", False) and gb > 0 and li >= gb:
            if float(close_arr[li]) < float(close_arr[li - gb]):
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
        rows.append(
            {
                "ROW_TYPE": "PENDING",
                "SYMBOL": sym,
                "AS_OF_DATE": last_iso,
                "ENTRY_DATE": "",
                "CLOSE": "",
                "STOP_LOSS": "",
                "TARGET": "",
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
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in watchlist:
            w.writerow([r.get(c, "") for c in cols])


def write_brt_scanner(scanner: list[dict], path: str) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["SYMBOL", "DATE", "CLOSE", "STOP_LOSS", "TARGET", "ZONE_CENTER"])
        for s in scanner:
            w.writerow([s["symbol"], s["date"], f"{s['close']:.2f}", f"{s['stop']:.2f}", f"{s['target']:.2f}", f"{s.get('zone_center', 0):.4f}"])


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
) -> None:
    """Write BRT_ZONES_<sym>_<ts>.csv (all bars with a zone) and BRT_ZONES_ENTRIES_<sym>_<ts>.csv (overlap debug per entry)."""
    zones_path = os.path.join(output_dir, f"BRT_ZONES_{sym}_{ts}.csv")
    zc_arr = level3["zone_center"]
    zl_arr = level3["zone_low"]
    zh_arr = level3["zone_high"]
    tc_arr = level3["touch_count_long"]
    tp_arr = level3["touch_price"]
    matured = level3.get("matured_now")
    n_zone_rows = 0
    with open(zones_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["SYMBOL", "DATE", "BAR_INDEX", "ZONE_CENTER", "ZONE_LOW", "ZONE_HIGH", "TOUCH_COUNT_LONG", "TOUCH_PRICE", "MATURED_NOW"])
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
            w.writerow([sym, dt, i, f"{float(zc):.4f}", f"{float(zl):.4f}" if not pd.isna(zl) else "", f"{float(zh):.4f}" if not pd.isna(zh) else "", int(tc) if not pd.isna(tc) else "", f"{float(tp):.4f}" if not pd.isna(tp) and tp else "", 1 if mat else 0])
    print(f"Zones written: {zones_path} ({n_zone_rows} rows)")

    entries_path = os.path.join(output_dir, f"BRT_ZONES_ENTRIES_{sym}_{ts}.csv")
    if not zone_entries_debug:
        with open(entries_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["ENTRY_DATE", "ENTRY_PRICE", "ZONE_CENTER", "ZONE_LOW", "ZONE_HIGH", "CURRENT_ZONE_TOP", "TRIGGER_BOTTOM", "MIN_ZONE_ABOVE_CENTER", "ZONE_ABOVE_CENTER_CHOSEN", "BOTTOM_ZONE_ABOVE", "PCT_ENTRY_TO_BOTTOM_ZONE_ABOVE", "ALL_ZONE_CENTERS_IN_WINDOW"])
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
        w.writerow(["SYMBOL", "TRADES", "WINS", "LOSSES", "BEs", "TOTAL_PNL", "AVG_PNL_PCT", "PCT_OF_TOTAL_PNL", "SECTOR", "INDUSTRY"])
        for sym in sorted(by_sym.keys()):
            trades = by_sym[sym]
            wins = sum(1 for t in trades if t.pnl_pct > 0)
            losses = sum(1 for t in trades if t.pnl_pct < 0)
            bes = sum(1 for t in trades if t.pnl_pct == 0)
            total = sum(t.pnl_dollars for t in trades)
            avg_pct = sum(t.pnl_pct for t in trades) / len(trades) if trades else 0
            pct_of_total = (total / total_pnl_overall * 100) if total_pnl_overall and total_pnl_overall != 0 else 0.0
            sector = (getattr(trades[0], "sector", None) or "").replace(",", " ") if trades else ""
            industry = (getattr(trades[0], "industry", None) or "").replace(",", " ") if trades else ""
            w.writerow([sym, len(trades), wins, losses, bes, f"{total:.2f}", f"{avg_pct:.2f}%", f"{pct_of_total:.1f}%", sector, industry])


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


def _write_brt_equity_canonical_outputs(output_dir, ts: str, equity: dict) -> None:
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
        pd.DataFrame(df_data).to_csv(outp / f"BRT_EquityCurve_{ts}.csv", index=False)
        raw = float(equity.get("_max_port_dd_raw", 0) or 0)
        init_sz = float(equity.get("_initial_account_size", 0) or 0)
        meta_row = {
            "Initial_Account_Size": init_sz,
            "Max_Drawdown_fraction": raw,
            "Max_Drawdown_pct": equity.get("Max_Drawdown", ""),
            "Max_Days_Underwater": int(equity.get("Max_Days_Underwater", 0) or 0),
            "Pct_Days_Underwater": equity.get("Pct_Days_Underwater", ""),
        }
        pd.DataFrame([meta_row]).to_csv(outp / f"BRT_EquityMeta_{ts}.csv", index=False)
        print(
            f"[FILE] BRT equity curve (same series as Max_DD in this run; use for BRT_DrawdownCalc): "
            f"BRT_EquityCurve_{ts}.csv, BRT_EquityMeta_{ts}.csv"
        )
    except Exception as e:
        print(f"[WARN] Could not write BRT_EquityCurve/Meta: {e}", file=sys.stderr)


def write_brt_report(
    cfg: BRTConfig,
    metrics: dict,
    output_dir: str,
    ts: str,
    drive_link: str = "",
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
    audit_order = _get_audit_cols_order()
    headers = [c for c in audit_order if c in row]
    extras = [c for c in row.keys() if c not in headers]
    headers.extend(extras)
    headers = _reposition_input_flags(headers)
    values = [row.get(c, "") for c in headers]
    path = os.path.join(output_dir, f"BRT_Report_{ts}.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerow(values)


# Audit report columns (must match BRT_Optimizer.CFG_COLS and AUDIT_COLS_ORDER for alignment)
_AUDIT_CFG_COLS = [
    "pivot_k", "pivot_d", "pivot_disp", "pivot_m", "band_pct", "lookback_long", "touch_threshold",
    "strong_pivots_enabled",
    "strong_pre_pivot_bars", "strong_pre_pivot_pct",
    "strong_post_pivot_bars", "strong_post_pivot_pct", "strong_pivot_mode",
    "close_above_window", "pending_max_bars", "entry_eval_mode", "row_local_eval_touch_same_bar", "row_local_require_active_context_match", "level_acceptance_window", "level_acceptance_required",
    "level_acceptance_anchor_mode", "level_acceptance_anchor_window",
    "support_test_enabled", "breakout_bars",
    "tight_range_enabled", "tight_range_threshold_pct", "tight_range_lookback",
    "tradeable_key_level_enabled", "lookback_short",
    "min_touch_count", "max_touch_count_minor",
    "min_pivot_run_l_before_entry", "min_pivot_run_h_before_entry", "min_rel_vol_at_entry",
    "min_market_cap", "min_hist_ann_ror_avg", "pivot_switch_h_to_l_filter",
    "entry_filter_major_pivot", "entry_filter_is_20bar_high_at_trigger",
    "growth_filter_enabled", "growth_bars", "entry_close_min_range_position",
    "sheet_maturity_lag_bars", "sheet_zone_ladder_rungs", "use_sheet_ladder_active_zone",
    "sheet_use_dg_slot_for_zone_identity", "sheet_active_zone_asof_lag_bars",
    "do_gate_enabled", "do_good_for_bars",
    "dp_gate_enabled", "dp_window_bars", "dp_good_for_bars",
    "sheet_magic_touch_enabled", "sheet_magic_touch_window_bars",
    "displacement_filter_enabled", "displacement_rolling_bars", "displacement_threshold_pct",
    "consolidation_blocker_enabled", "cb_max_box_width_pct",
    "brt_cash", "stop_pct", "stop_pct_is_multiplier", "target_pct",
    "atr_target", "atr_stop", "atr_increment",
    # Realtime predictive filter config + weights (inputs)
    "realtime_filter_enabled", "realtime_filter_threshold", "realtime_filter_use_zscore",
    "weight_touch_count_minor", "weight_zone_cluster_density", "weight_nearby_zones_above",
    "weight_touch_count_major", "weight_pct_entry_to_bottom_zone_above",
    "weight_z_score_at_trigger", "weight_pivot_run_l_before_entry",
    "weight_nearby_zones_below", "weight_pct_drop_to_top_zone_below",
    "weight_rel_vol_at_entry", "weight_displacement_pct_at_entry",
    "weight_lower_wick_atr_at_trigger", "weight_growth_pct_over_period", "weight_beta_at_entry",
    "days_per_year", "exit_at_close_when_stopped", "compute_equity_metrics",
    "initial_capital", "aggressive", "aggressive_margin_interest", "aggressive_max_multiple", "aggressive_avg_positions",
]

_AGGRESSIVE_METRIC_COLS = [
    "Aggressive_Total_PNL",
    "Aggressive_Avg_Positions",
    "Aggressive_Days_AtOrBelow_Avg",
    "Aggressive_Days_In_Margin",
    "Aggressive_Days_Trimmed_Over_2xAvg",
]

_PREFERRED_INPUT_FLAGS_AFTER_EQUITY = [
    "pending_max_bars",
    "entry_eval_mode",
    "row_local_eval_touch_same_bar",
    "row_local_require_active_context_match",
    "level_acceptance_anchor_mode",
    "level_acceptance_anchor_window",
    "sheet_use_dg_slot_for_zone_identity",
    "sheet_active_zone_asof_lag_bars",
    "do_gate_enabled",
    "do_good_for_bars",
    "dp_gate_enabled",
    "dp_window_bars",
    "dp_good_for_bars",
    "sheet_magic_touch_enabled",
    "sheet_magic_touch_window_bars",
    "initial_capital",
    "aggressive",
    "aggressive_margin_interest",
    "aggressive_max_multiple",
    "aggressive_avg_positions",
]

# Human-readable glossary for newer audit/report columns.
# Kept near audit column lists so future additions stay documented.
_AUDIT_FIELD_GLOSSARY: dict[str, str] = {
    # Entry-state / gating knobs
    "pending_max_bars": "Max bars a pending maturity can wait before expiry (stale pending TTL).",
    "entry_eval_mode": "Entry engine mode: 'pending' (legacy pending queue) or 'row_local' (sheet-style row-local evaluation).",
    "row_local_eval_touch_same_bar": "In row_local mode, allow same-bar evaluation on maturity/touch bar when True.",
    "row_local_require_active_context_match": "In row_local mode, require pending maturity to match active DN context.",
    "level_acceptance_anchor_mode": "Support-test anchor mode for level acceptance: 'strict' current/prior, 'rolling' recent-window.",
    "level_acceptance_anchor_window": "Lookback window (bars) for rolling anchor mode.",
    # Sheet parity controls
    "sheet_use_dg_slot_for_zone_identity": "When True, same-zone identity uses ladder slot (DG) instead of bounds-only matching.",
    "sheet_active_zone_asof_lag_bars": "As-of lag (bars) for active-zone context in AQ/BG sheet-style gates.",
    "do_gate_enabled": "Enable DO parity gate (recent pre-only strong pivot touch must exist).",
    "do_good_for_bars": "DO gate recency window in bars ('good for' bars).",
    "dp_gate_enabled": "Enable DP parity gate (current price must be inside any recent matured CE/CF zone).",
    "dp_window_bars": "DP lookback window in bars (0 means use lookback_long).",
    "dp_good_for_bars": "DP event recency window in bars ('good for' bars).",
    "sheet_magic_touch_enabled": "Enable AR/AW sheet magic-touch event generation for maturity/touch events.",
    "sheet_magic_touch_window_bars": "AR/AW rolling window length in bars (0 means use lookback_long).",
    # Equity/DD model controls
    "initial_capital": "Portfolio baseline equity for DD/equity path (independent of brt_cash per-position sizing).",
    "aggressive": "Enable aggressive equity overlay for DD path (target gross at 500k/avg_pos, margin above avg, trim above cap).",
    "aggressive_margin_interest": "Annualized interest rate charged on borrowed margin notional in aggressive mode.",
    "aggressive_max_multiple": "Max gross exposure multiple of initial_capital in aggressive mode (above this, positions are proportionally trimmed).",
    "aggressive_avg_positions": "Override average positions used by aggressive sizing (0/blank = auto from active-position history).",
    # Concentration metrics
    "Pct_PNL_Max_Symbol": "Largest single-symbol contribution as % of total PnL.",
    "Pct_PNL_Max_Trade": "Largest single-trade contribution as % of total PnL.",
    "Pct_PNL_Max_Industry": "Largest single-industry contribution as % of total PnL.",
    # Aggressive run diagnostics
    "Aggressive_Avg_Positions": "Average active positions used by aggressive sizing logic.",
    "Aggressive_Total_PNL": "Aggressive total PnL on initial_capital basis (includes margin + trims + interest).",
    "Aggressive_Days_AtOrBelow_Avg": "Days where desired gross stayed at or below initial_capital (no margin).",
    "Aggressive_Days_In_Margin": "Days where desired gross exceeded initial_capital but stayed within max multiple cap.",
    "Aggressive_Days_Trimmed_Over_2xAvg": "Days where desired gross exceeded cap and was trimmed proportionally to fit cap.",
}


def _get_audit_cols_order() -> list:
    """Return audit column order; use BRT_Optimizer.AUDIT_COLS_ORDER when available so run_audit output matches optimizer."""
    try:
        from BRT_Optimizer import AUDIT_COLS_ORDER
        return list(AUDIT_COLS_ORDER)
    except ImportError:
        pass
    return (
        ["Timestamp_Drive"] + _AUDIT_CFG_COLS + ["Param_Name", "Param_Value"]
        + ["Total_PNL", "Wins", "Losses", "BE", "Pct_Wins", "Pct_Losses",
           "Win_Loss_Ratio", "Win_Loss_Ratio_Dollar", "Total_Trades", "Profit_Factor",
           "Avg_Win_Pct", "Avg_Loss_Pct", "Avg_PNL_Pct", "Expectancy", "Expectancy_Pct"]
        + ["Avg_Days_Held", "Median_Days_Held", "P90_Days", "Capital_Days",
           "Profit_Per_Capital_Day", "Ann_ROR"]
        + ["Max_DD", "Losing_Streak", "DD_Per_Trade"]
        + ["CES_AVG", "CES_Median", "Pct_PNL_Top10", "Pct_PNL_Bottom10", "Max_Positions"]
        + ["Pct_PNL_Max_Symbol", "Pct_PNL_Max_Trade", "Pct_PNL_Max_Industry"]
        + _AGGRESSIVE_METRIC_COLS
        + ["Score"]
    )  # fallback: same order as BRT_Optimizer.AUDIT_COLS_ORDER


def _reposition_input_flags(headers: list[str]) -> list[str]:
    """Place selected input flags right after compute_equity_metrics and before Param_Name."""
    if not headers:
        return headers
    base = [h for h in headers if h not in _PREFERRED_INPUT_FLAGS_AFTER_EQUITY]
    anchor = "compute_equity_metrics"
    anchor_i = base.index(anchor) if anchor in base else None
    to_insert = [h for h in _PREFERRED_INPUT_FLAGS_AFTER_EQUITY if h in headers]
    if anchor_i is not None:
        return base[: anchor_i + 1] + to_insert + base[anchor_i + 1 :]
    # Fallback: keep all inputs left by inserting before Param_Name when anchor missing.
    p_i = base.index("Param_Name") if "Param_Name" in base else len(base)
    return base[:p_i] + to_insert + base[p_i:]


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
        "Aggressive_Avg_Positions": num(metrics.get("Aggressive_Avg_Positions", 0)),
        "Aggressive_Days_AtOrBelow_Avg": int(metrics.get("Aggressive_Days_AtOrBelow_Avg", 0) or 0),
        "Aggressive_Days_In_Margin": int(metrics.get("Aggressive_Days_In_Margin", 0) or 0),
        "Aggressive_Days_Trimmed_Over_2xAvg": int(metrics.get("Aggressive_Days_Trimmed_Over_2xAvg", 0) or 0),
    }


def write_brt_audit_report(
    cfg: BRTConfig,
    metrics: dict,
    output_dir: str,
    ts: str,
    drive_link: str = "",
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
    audit_order = _get_audit_cols_order()
    ordered = [c for c in audit_order if c in row]
    extras = [c for c in row.keys() if c not in ordered]
    headers = ordered + extras
    headers = _reposition_input_flags(headers)
    values = [row.get(c, "") for c in headers]
    path = os.path.join(output_dir, f"BRT_Audit_Report_{ts}.csv")
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


def _report_adjusted_brt_cash(max_positions: int) -> float:
    """BRT_Report convention: notional per slot = 1_000_000 / max(Max_Positions, 1)."""
    mp = max(int(max_positions or 0), 1)
    return 1_000_000.0 / mp


def _apply_report_dollar_scale_to_trades(
    closed: list[BRTTrade],
    open_trades: list[BRTTrade],
    cfg: BRTConfig,
) -> tuple[float, float]:
    """
    Align in-memory dollar fields with BRT_Report / BRT_Audit: ``brt_cash = 1M / max_positions``
    and scale every trade's ``pnl_dollars`` by the same ratio so CSV outputs match the report.

    Returns (adjusted_brt_cash, scale_factor_applied_to_pnl) where scale is 1.0 if no pnl change.
    """
    max_pos = max(_max_concurrent_positions(closed), 1)
    adjusted = _report_adjusted_brt_cash(max_pos)
    orig = float(cfg.brt_cash) if getattr(cfg, "brt_cash", None) and cfg.brt_cash > 0 else adjusted
    scale = adjusted / orig if orig > 0 else 1.0
    if abs(scale - 1.0) >= 1e-12:
        for t in closed:
            t.pnl_dollars = float(t.pnl_dollars) * scale
        for t in open_trades:
            t.pnl_dollars = float(getattr(t, "pnl_dollars", 0) or 0) * scale
    cfg.brt_cash = adjusted
    return adjusted, scale if abs(scale - 1.0) >= 1e-12 else 1.0


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
        "Max_Positions": _max_concurrent_positions(closed),
        "Pct_PNL_Max_Symbol": f"{pct_pnl_max_symbol:.1f}%",
        "Pct_PNL_Max_Trade": f"{pct_pnl_max_trade:.1f}%",
        "Pct_PNL_Max_Industry": f"{pct_pnl_max_industry:.1f}%",
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


def _print_symbol_progress(done: int, total: int, t_start: Optional[float] = None) -> None:
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
    msg = f"[PROGRESS] {done}/{total} ({pct:.1f}%){eta_part}"
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


def _process_symbol(args: tuple) -> tuple[str, list, Optional[BRTTrade], list, list, list, list, dict, dict]:
    """Worker: process one symbol. Picklable for ProcessPoolExecutor. args = (sym, csv_path, cfg_dict, reference_stats) or + profile_backtest bool."""
    do_profile_bt = False
    if len(args) >= 5:
        sym, csv_path, cfg_dict, reference_stats, do_profile_bt = args[0], args[1], args[2], args[3], bool(args[4])
    elif len(args) >= 4:
        sym, csv_path, cfg_dict, reference_stats = args[0], args[1], args[2], args[3]
    else:
        sym, csv_path, cfg_dict = args[0], args[1], args[2]
        reference_stats = None
    t0 = time.time()
    df = load_csv(csv_path)
    t_load = time.time() - t0
    cfg = BRTConfig(**cfg_dict)
    if len(df) < cfg.pivot_k + cfg.pivot_m + 10:
        timing = {
            "symbol": sym, "bars": int(len(df)), "t_load": t_load, "t_pivots": 0.0,
            "t_structure": 0.0, "t_touch": 0.0, "t_backtest": 0.0, "t_collect_pivots": 0.0, "t_total": time.time() - t0
        }
        return (sym, [], None, [], [], [], [], timing, {})
    t1 = time.time()
    pivot_high, pivot_low, ph_price, pl_price = compute_pivots(
        df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m, realtime_filter_enabled=cfg.realtime_filter_enabled
    )
    t_pivots = time.time() - t1
    t2 = time.time()
    struct = compute_market_structure(df, pivot_high, pivot_low, ph_price, pl_price)
    t_structure = time.time() - t2
    t3 = time.time()
    level3 = compute_touch_stream(
        df, pivot_high, pivot_low, ph_price, pl_price,
        cfg.band_pct, cfg.lookback_long, cfg.touch_threshold,
        cfg.lookback_short,
        strong_pivots_enabled=cfg.strong_pivots_enabled,
        strong_pre_pivot_bars=cfg.strong_pre_pivot_bars,
        strong_pre_pivot_pct=cfg.strong_pre_pivot_pct,
        strong_post_pivot_bars=cfg.strong_post_pivot_bars,
        strong_post_pivot_pct=cfg.strong_post_pivot_pct,
        strong_pivot_mode=cfg.strong_pivot_mode,
        zone_price_round_decimals=cfg.zone_price_round_decimals,
        debug_symbol=sym,
        realtime_filter_enabled=cfg.realtime_filter_enabled,
    )
    t_touch = time.time() - t3
    data_dir = Path(csv_path).parent
    benchmark_df = _load_benchmark_local(data_dir)
    block_reasons: dict[str, int] = {}
    bt_sections: dict[str, float] = {}
    t4 = time.time()
    closed, open_trade, scanner, short_cands, would_have, _watchlist = run_brt_backtest(
        sym, df, cfg, ph_price, pl_price, struct, level3, benchmark_df=benchmark_df,
        reference_stats=reference_stats, profile_block_reasons=block_reasons,
        profile_backtest_sections=bt_sections if do_profile_bt else None,
    )
    t_backtest = time.time() - t4
    t5 = time.time()
    pivot_rows = collect_brt_pivots(sym, df, pivot_high, pivot_low, ph_price, pl_price, struct)
    t_collect_pivots = time.time() - t5
    timing = {
        "symbol": sym,
        "bars": int(len(df)),
        "t_load": t_load,
        "t_pivots": t_pivots,
        "t_structure": t_structure,
        "t_touch": t_touch,
        "t_backtest": t_backtest,
        "t_collect_pivots": t_collect_pivots,
        "t_total": time.time() - t0,
    }
    if do_profile_bt and bt_sections:
        timing.update(bt_sections)
    return (sym, closed, open_trade, scanner, short_cands, pivot_rows, would_have, timing, block_reasons, _watchlist)


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
    ticker_list = sorted([
        s for s, df in tickers.items()
        if len(df) >= cfg.pivot_k + cfg.pivot_m + 10
    ])
    all_closed: list[BRTTrade] = []
    cfg_dict = asdict(cfg)
    n_w = max(0, n_workers)
    if n_w > 0:
        n_w = min(n_w, os.cpu_count() or 4)
    all_open: list[BRTTrade] = []
    if n_w > 0:
        tasks = [
            (sym, str(data_path / f"{sym}.csv"), cfg_dict)
            for sym in ticker_list
            if (data_path / f"{sym}.csv").exists()
        ]
        n_batch = len(tasks)
        done_b = 0
        progress_t0 = time.perf_counter()
        with ProcessPoolExecutor(max_workers=n_w) as ex:
            for future in as_completed(ex.submit(_process_symbol, t) for t in tasks):
                _, closed, open_trade, scanner, _, _, _, _, _, _ = future.result()
                all_closed.extend(closed)
                if open_trade is not None:
                    all_open.append(open_trade)
                done_b += 1
                _print_symbol_progress(done_b, n_batch, progress_t0)
        if n_batch > 1:
            print()
    else:
        n_seq = len(ticker_list)
        progress_t0 = time.perf_counter()
        for idx, sym in enumerate(ticker_list, 1):
            df = tickers[sym]
            pivot_high, pivot_low, ph_price, pl_price = compute_pivots(
                df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m, realtime_filter_enabled=cfg.realtime_filter_enabled
            )
            struct = compute_market_structure(df, pivot_high, pivot_low, ph_price, pl_price)
            level3 = compute_touch_stream(
                df, pivot_high, pivot_low, ph_price, pl_price,
                cfg.band_pct, cfg.lookback_long, cfg.touch_threshold,
                cfg.lookback_short,
                strong_pivots_enabled=cfg.strong_pivots_enabled,
                strong_pre_pivot_bars=cfg.strong_pre_pivot_bars,
                strong_pre_pivot_pct=cfg.strong_pre_pivot_pct,
                strong_post_pivot_bars=cfg.strong_post_pivot_bars,
                strong_post_pivot_pct=cfg.strong_post_pivot_pct,
                strong_pivot_mode=cfg.strong_pivot_mode,
                zone_price_round_decimals=cfg.zone_price_round_decimals,
                debug_symbol=sym,
                realtime_filter_enabled=cfg.realtime_filter_enabled,
            )
            closed, open_trade, _, _, _, _ = run_brt_backtest(
                sym, df, cfg, ph_price, pl_price, struct, level3
            )
            all_closed.extend(closed)
            if open_trade is not None:
                all_open.append(open_trade)
            if n_seq > 1:
                _print_symbol_progress(idx, n_seq, progress_t0)
        if n_seq > 1:
            print()
    if all_closed:
        _apply_report_dollar_scale_to_trades(all_closed, all_open, cfg)
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
            )
            metrics["Max_Drawdown"] = equity["Max_Drawdown"]
            metrics["Max_Days_Underwater"] = equity["Max_Days_Underwater"]
            metrics["Pct_Days_Underwater"] = equity["Pct_Days_Underwater"]
            if equity.get("_aggressive"):
                metrics["Aggressive_Avg_Positions"] = equity.get("Aggressive_Avg_Positions", 0)
                metrics["Aggressive_Days_AtOrBelow_Avg"] = equity.get("Aggressive_Days_AtOrBelow_Avg", 0)
                metrics["Aggressive_Days_In_Margin"] = equity.get("Aggressive_Days_In_Margin", 0)
                metrics["Aggressive_Days_Trimmed_Over_2xAvg"] = equity.get("Aggressive_Days_Trimmed_Over_2xAvg", 0)
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


# ============== MAIN ==============
def main() -> int:
    ap = argparse.ArgumentParser(description="Rocket BRT Backtest")
    ap.add_argument("data_dir", nargs="?", default="data/newdata/data", help="Data directory")
    ap.add_argument("--output-dir", "-o", default="drive", help="Output directory")
    ap.add_argument("--symbol", "-s", default="", help="Single symbol (enables chart)")
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
                    help="Write BRT_ZONES_<sym>_<ts>.csv and BRT_ZONES_ENTRIES_<sym>_<ts>.csv for zone/overlap debug (use with -s SYMBOL)")
    ap.add_argument("--debug-symbol", type=str, default=None,
                    help="Enable verbose debug logging for a specific symbol (e.g., ATUSF)")
    ap.add_argument("--debug-date", type=str, default=None,
                    help="Focus debug logging around a specific date (e.g., 2022-07-26)")
    ap.add_argument("--trace-date", action="append", default=[],
                    help="Exact eval-bar date(s) to trace gate-by-gate (YYYY-MM-DD or YYYYMMDD); repeatable")
    ap.add_argument("--trace-symbol", type=str, default=None,
                    help="Optional symbol filter for --trace-date (defaults to --symbol when set)")
    ap.add_argument("--workers", "-w", type=int, default=0,
                    help="Parallel workers (0=sequential, N=process pool). Use -w 4 or -w 8 for ~4-8x speedup on large universes.")
    ap.add_argument("--profile", action="store_true",
                    help="Print timing for load, benchmark, backtest, beta, write, correlation, and equity phases (use: --profile)")
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
                    help="Skip Max_Drawdown / underwater metrics (~30–40s saved on large runs)")
    ap.add_argument("--aggressive", action="store_true",
                    help="Aggressive equity sizing for DD: use 500k/avg_positions, 10% margin above avg, trim above 2x avg")
    ap.add_argument("--aggressive-margin-interest", type=float, default=0.10,
                    help="Annual margin interest rate for --aggressive (default 0.10)")
    ap.add_argument("--aggressive-max-multiple", type=float, default=2.0,
                    help="Max gross exposure multiple of initial_capital for --aggressive (default 2.0)")
    ap.add_argument("--aggressive-avg-positions", type=float, default=0.0,
                    help="Override avg positions for --aggressive (default auto from active-position history)")
    ap.add_argument("--band-pct", type=float, default=None,
                    help="Zone band ±pct (default 0.02=2%%)")
    ap.add_argument("--close-above-window", type=int, default=None,
                    help="Close>zone allowed on maturity-touch day or N days after (default 1 = same or next day only)")
    ap.add_argument("--level-acceptance", type=str, default="",
                    help="7/10 rule: require N of last M bars close above trigger low, e.g. '7/10' (default 7/10)")
    ap.add_argument("--level-acceptance-anchor-mode", type=str, default=None, choices=["strict", "rolling"],
                    help="Level Acceptance anchor mode: strict=current/prior ST, rolling=any ST in recent window")
    ap.add_argument("--level-acceptance-anchor-window", type=int, default=None,
                    help="When anchor mode is rolling, bars to look back for a Support Test anchor (default 10)")
    ap.add_argument("--no-support-test", action="store_true",
                    help="Disable Support Test anchor for Level Acceptance (7/10 can still apply)")
    ap.add_argument("--breakout-bars", type=int, default=None,
                    help="AP breakout lookback bars (legacy internals; default 100)")
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
    ap.add_argument("--growth-bars", type=int, default=756,
                    help="Growth lookback in bars: require Close[entry] >= Close[entry - N]; 756 = 3 years (default 756)")
    ap.add_argument("--entry-close-min-range-position", type=float, default=None,
                    help="After close>open: require (close-low)/(high-low) >= this (sheet C27 default 1e-7; 0.5 = upper half; 0 = off)")
    ap.add_argument("--displacement-filter", action="store_true",
                    help="Enable rolling average displacement filter: require |Close/RollingAvg100 - 1| >= threshold (avoid stuck/equilibrium)")
    ap.add_argument("--displacement-rolling-bars", type=int, default=100,
                    help="Rolling window for displacement average (default 100)")
    ap.add_argument("--displacement-threshold", type=float, default=0.10,
                    help="Min displacement as decimal, e.g. 0.10 = 10%% (default 0.10)")
    ap.add_argument("--emit-sheet-parity", action="store_true",
                    help="With -s SYMBOL: write BRT_SheetParity_<sym>_<ts>.csv (DE/DF/DG per bar + blank columns to paste sheet values)")
    ap.add_argument("--sheet-ladder-active-zone", action="store_true",
                    help="Use Excel zone-ladder DE/DF/DG for row_local active zone (pair with -v entry_eval_mode=row_local)")
    ap.add_argument("--sheet-maturity-lag", type=int, default=None,
                    help="Sheet C14: lag in bars for CE/CF inputs to the ladder (default: config sheet_maturity_lag_bars)")
    ap.add_argument("--sheet-zone-ladder-rungs", type=int, default=None,
                    help="Sheet ladder depth: >0 fixed rungs, 0 => use lookback_long (extended memory)")
    ap.add_argument("--ladder-mismatch-report", action="store_true",
                    help="With -s SYMBOL: count trades whose maturity zone is not on any of 8 sheet rungs at signal bar; write BRT_LadderMismatch_<sym>_<ts>.csv")
    ap.add_argument("--set", "-v", dest="config_set", action="append", default=[], metavar="KEY=VALUE",
                    help="Override config: -v touch_threshold=2 -v min_touch_count=5 (multiple allowed)")
    args = ap.parse_args()

    if _NUMBA_LADDER_AVAILABLE and _use_numba_sheet_ladder():
        print("[BRT] Numba ladder JIT: on (compiled code cached on disk; not invalidated by BRT --set params)")
    elif _NUMBA_LADDER_AVAILABLE:
        print("[BRT] Numba ladder JIT: off (BRT_DISABLE_NUMBA_LADDER is set)")

    # Enable debug logging if requested
    if args.debug_symbol:
        set_debug_target(args.debug_symbol.upper(), args.debug_date)
        print(f"[DEBUG] Debug logging enabled for {args.debug_symbol.upper()}" + 
              (f" around {args.debug_date}" if args.debug_date else ""))
    if getattr(args, "trace_date", None):
        trace_sym = args.trace_symbol or (args.symbol if args.symbol else None)
        set_trace_target(trace_sym, args.trace_date)
        print(f"[TRACE] Enabled for dates={list(args.trace_date)}" + (f", symbol={trace_sym.upper()}" if trace_sym else ""))

    script_dir = Path(__file__).parent.resolve()
    repo_root = script_dir.parent
    data_dir = Path(args.data_dir)
    if not data_dir.is_absolute():
        data_dir = repo_root / data_dir
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = repo_root / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%y%m%d%H%M%S")
    cfg_kw: dict = {"exit_at_close_when_stopped": args.exit_at_close_when_stopped}
    cfg_kw["initial_capital"] = float(args.initial_capital)
    cfg_kw["aggressive"] = bool(args.aggressive)
    cfg_kw["aggressive_margin_interest"] = float(args.aggressive_margin_interest)
    cfg_kw["aggressive_max_multiple"] = float(args.aggressive_max_multiple)
    cfg_kw["aggressive_avg_positions"] = float(args.aggressive_avg_positions)
    if args.stop_pct_multiplier:
        cfg_kw["stop_pct_is_multiplier"] = True
    if args.band_pct is not None:
        cfg_kw["band_pct"] = args.band_pct
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
    if args.growth_filter:
        cfg_kw["growth_filter_enabled"] = True
    cfg_kw["growth_bars"] = args.growth_bars
    if args.entry_close_min_range_position is not None:
        cfg_kw["entry_close_min_range_position"] = args.entry_close_min_range_position
    if args.displacement_filter:
        cfg_kw["displacement_filter_enabled"] = True
        cfg_kw["displacement_rolling_bars"] = args.displacement_rolling_bars
        cfg_kw["displacement_threshold_pct"] = args.displacement_threshold
    if getattr(args, "no_equity_metrics", False):
        cfg_kw["compute_equity_metrics"] = False
    if getattr(args, "sheet_ladder_active_zone", False):
        cfg_kw["use_sheet_ladder_active_zone"] = True
    if getattr(args, "sheet_maturity_lag", None) is not None:
        cfg_kw["sheet_maturity_lag_bars"] = int(args.sheet_maturity_lag)
    if getattr(args, "sheet_zone_ladder_rungs", None) is not None:
        cfg_kw["sheet_zone_ladder_rungs"] = int(args.sheet_zone_ladder_rungs)
    # Apply -v / --set KEY=VALUE overrides
    set_args = getattr(args, "config_set", None) or getattr(args, "set", None)
    if set_args is None:
        set_args = []
    set_args = list(set_args) if set_args else []
    if set_args:
        print(f"[BRT] Config overrides received: {set_args}")
    valid_fields = set(BRTConfig.__dataclass_fields__)
    for s in set_args:
        key, _, val_str = s.partition("=")
        key = key.strip()
        val_str = val_str.strip()
        if not key:
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
    cfg = BRTConfig(**defaults)
    if cfg.stop_pct == 0 and cfg.target_pct == 0:
        print(f"[BRT] ATR mode: atr_target={cfg.atr_target} atr_stop={cfg.atr_stop} atr_increment={cfg.atr_increment}")
    if cfg.use_sheet_ladder_active_zone and str(cfg.entry_eval_mode).strip().lower() != "row_local":
        print(
            "[BRT] Note: use_sheet_ladder_active_zone is designed for entry_eval_mode=row_local "
            f"(current: {cfg.entry_eval_mode}).",
            file=sys.stderr,
        )

    if getattr(args, "cprofile", False):
        if not (args.symbol or "").strip():
            print("[BRT] --cprofile requires --symbol SYM (single-symbol backtest path).", file=sys.stderr)
            _maybe_play_completion_sound(args.play_sound)
            return 1
        if getattr(args, "workers", 0) and args.workers > 0:
            print("[BRT] --cprofile: ignoring -w (profiling uses sequential single-symbol path).", file=sys.stderr)
            args.workers = 0

    if getattr(args, "cprofile_sheet_magic_touch", False):
        if not (args.symbol or "").strip():
            print("[BRT] --cprofile-sheet-magic-touch requires --symbol SYM.", file=sys.stderr)
            _maybe_play_completion_sound(args.play_sound)
            return 1
        if getattr(args, "workers", 0) and args.workers > 0:
            print("[BRT] --cprofile-sheet-magic-touch: ignoring -w (sequential profiling).", file=sys.stderr)
            args.workers = 0
    if getattr(args, "cprofile_pending_sheet_prep", False):
        if not (args.symbol or "").strip():
            print("[BRT] --cprofile-pending-sheet-prep requires --symbol SYM.", file=sys.stderr)
            _maybe_play_completion_sound(args.play_sound)
            return 1
        if getattr(args, "workers", 0) and args.workers > 0:
            print("[BRT] --cprofile-pending-sheet-prep: ignoring -w (sequential profiling).", file=sys.stderr)
            args.workers = 0

    if args.symbol:
        # Single symbol mode + chart
        sym = args.symbol.upper()
        csv_path = data_dir / f"{sym}.csv"
        if not csv_path.exists():
            print(f"File not found: {csv_path}", file=sys.stderr)
            _maybe_play_completion_sound(args.play_sound)
            return 1
        _t_load = time.time()
        tickers = {sym: load_csv(str(csv_path))}
        if args.profile:
            print(f"[PROFILE] load_tickers: {time.time() - _t_load:.2f}s (1 symbol)")
    else:
        _t_load = time.time()
        tickers = load_all_tickers(str(data_dir))
        if args.profile:
            print(f"[PROFILE] load_tickers: {time.time() - _t_load:.2f}s ({len(tickers)} symbols)")

    all_closed: list[BRTTrade] = []
    all_open: list[BRTTrade] = []
    all_scanner: list[dict] = []
    all_watchlist: list[dict] = []
    all_short_candidates: list[dict] = []
    all_would_have: list[dict] = []
    profile_symbol_rows: list[dict] = []
    profile_block_rows: list[dict] = []

    sheet_ladder_sink: Optional[dict[str, Any]] = None
    if getattr(args, "emit_sheet_parity", False) or cfg.use_sheet_ladder_active_zone:
        sheet_ladder_sink = {}

    t0 = time.time()
    n_workers = max(0, args.workers)
    if n_workers > 0:
        n_workers = min(n_workers, os.cpu_count() or 4)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting backtest over {len(tickers)} symbols" +
          (f" ({n_workers} workers)" if n_workers > 0 else "") + "...")
    if args.profile:
        print("[PROFILE] Timing enabled (use --profile on the command line to see this and other phase timings).")

    use_parallel = n_workers > 0 and not args.symbol
    ticker_list = sorted([s for s, df in tickers.items() if len(df) >= cfg.pivot_k + cfg.pivot_m + 10])
    n_total = len(ticker_list)
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

    if use_parallel:
        # Explicit dict for worker processes: ensure all BRTConfig fields are passed
        cfg_dict = {f: getattr(run_cfg, f) for f in BRTConfig.__dataclass_fields__}
        tasks = [
            (sym, str(data_dir / f"{sym}.csv"), cfg_dict, ref_stats, args.profile)
            for sym in ticker_list
            if (data_dir / f"{sym}.csv").exists()
        ]
        n_tasks = len(tasks)
        done = 0
        progress_t0 = time.perf_counter()
        with ProcessPoolExecutor(max_workers=n_workers) as ex:
            for future in as_completed(ex.submit(_process_symbol, t) for t in tasks):
                # _process_symbol returns 10 values (watchlist + timing + block-reason dicts for --profile).
                # Be tolerant of older 7-tuple / 9-tuple returns if a mixed/partial deploy ever happens.
                res = future.result()
                if len(res) == 10:
                    sym, closed, open_trade, scanner, short_cands, pivot_rows, would_have, timing_row, block_counts, watchlist = res
                elif len(res) == 9:
                    sym, closed, open_trade, scanner, short_cands, pivot_rows, would_have, timing_row, block_counts = res
                    watchlist = []
                elif len(res) == 7:
                    sym, closed, open_trade, scanner, short_cands, pivot_rows, would_have = res
                    timing_row, block_counts, watchlist = {}, {}, []
                else:
                    raise ValueError(f"_process_symbol returned {len(res)} values (expected 7, 9, or 10)")
                all_closed.extend(closed)
                if getattr(args, "emit_would_have", False):
                    all_would_have.extend(would_have)
                if open_trade:
                    all_open.append(open_trade)
                all_scanner.extend(scanner)
                all_watchlist.extend(watchlist)
                all_short_candidates.extend(short_cands)
                all_pivot_rows.extend(pivot_rows)
                if args.profile:
                    profile_symbol_rows.append(timing_row)
                    for reason, count in sorted(block_counts.items()):
                        profile_block_rows.append({"symbol": sym, "reason": reason, "count": int(count)})
                done += 1
                _print_symbol_progress(done, n_tasks, progress_t0)
        if n_tasks > 1:
            print()
    else:
        # Load benchmark once for all symbols (sequential path)
        _t_bench = time.time()
        benchmark_df_seq = _load_benchmark_local(data_dir)
        if args.profile:
            print(f"[PROFILE] benchmark_load (SPY): {time.time() - _t_bench:.2f}s")
        profile_beta_times = [] if args.profile else None
        progress_t0 = time.perf_counter()
        for idx, sym in enumerate(ticker_list, 1):
            _sym_t0 = time.time()
            df = tickers[sym]
            _t = time.time()
            pivot_high, pivot_low, ph_price, pl_price = compute_pivots(
                df, run_cfg.pivot_k, run_cfg.pivot_d, run_cfg.pivot_disp, run_cfg.pivot_m, realtime_filter_enabled=run_cfg.realtime_filter_enabled
            )
            t_pivots = time.time() - _t
            _t = time.time()
            struct = compute_market_structure(df, pivot_high, pivot_low, ph_price, pl_price)
            t_structure = time.time() - _t
            _t = time.time()
            level3 = compute_touch_stream(
                df, pivot_high, pivot_low, ph_price, pl_price,
                run_cfg.band_pct, run_cfg.lookback_long, run_cfg.touch_threshold,
                run_cfg.lookback_short,
                strong_pivots_enabled=run_cfg.strong_pivots_enabled,
                strong_pre_pivot_bars=run_cfg.strong_pre_pivot_bars,
                strong_pre_pivot_pct=run_cfg.strong_pre_pivot_pct,
                strong_post_pivot_bars=run_cfg.strong_post_pivot_bars,
                strong_post_pivot_pct=run_cfg.strong_post_pivot_pct,
                strong_pivot_mode=run_cfg.strong_pivot_mode,
                zone_price_round_decimals=run_cfg.zone_price_round_decimals,
                debug_symbol=sym,
                realtime_filter_enabled=run_cfg.realtime_filter_enabled,
            )
            t_touch = time.time() - _t
            zone_entries_debug: list = []
            benchmark_df = benchmark_df_seq
            block_counts: dict[str, int] = {}
            bt_sections: dict[str, float] = {}
            _t = time.time()
            _cprof_sym = bool(getattr(args, "cprofile", False) and args.symbol and sym.upper() == args.symbol.upper())
            _cprof_obj: Optional[cProfile.Profile] = cProfile.Profile() if _cprof_sym else None
            _cprof_smt_sym = bool(
                getattr(args, "cprofile_sheet_magic_touch", False)
                and args.symbol
                and sym.upper() == args.symbol.upper()
            )
            _cprof_smt_obj: Optional[cProfile.Profile] = cProfile.Profile() if _cprof_smt_sym else None
            _cprof_prep_sym = bool(
                getattr(args, "cprofile_pending_sheet_prep", False)
                and args.symbol
                and sym.upper() == args.symbol.upper()
            )
            _cprof_prep_obj: Optional[cProfile.Profile] = cProfile.Profile() if _cprof_prep_sym else None
            if _cprof_obj is not None:
                _cprof_obj.enable()
            try:
                if getattr(args, "print_zones", False) and args.symbol and sym == args.symbol.upper():
                    closed, open_trade, scanner, short_cands, would_have, watchlist = run_brt_backtest(
                        sym, df, run_cfg, ph_price, pl_price, struct, level3, zone_entries_debug=zone_entries_debug,
                        benchmark_df=benchmark_df, profile_beta_times=profile_beta_times, reference_stats=ref_stats,
                        profile_block_reasons=block_counts,
                        profile_backtest_sections=bt_sections if args.profile else None,
                        sheet_ladder_trace=sheet_ladder_sink,
                        cprofile_magic_touch=_cprof_smt_obj,
                        cprofile_pending_sheet_prep=_cprof_prep_obj,
                    )
                else:
                    closed, open_trade, scanner, short_cands, would_have, watchlist = run_brt_backtest(
                        sym, df, run_cfg, ph_price, pl_price, struct, level3, benchmark_df=benchmark_df,
                        profile_beta_times=profile_beta_times, reference_stats=ref_stats,
                        profile_block_reasons=block_counts,
                        profile_backtest_sections=bt_sections if args.profile else None,
                        sheet_ladder_trace=sheet_ladder_sink,
                        cprofile_magic_touch=_cprof_smt_obj,
                        cprofile_pending_sheet_prep=_cprof_prep_obj,
                    )
            finally:
                if _cprof_obj is not None:
                    _cprof_obj.disable()
                    _co = (args.cprofile_out or "").strip()
                    if _co:
                        _cprof_path = Path(_co)
                    else:
                        _cprof_path = output_dir / f"BRT_cProfile_{sym}_{ts}.prof"
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
                        _smt_path = output_dir / f"BRT_cProfile_sheet_magic_touch_{sym}_{ts}.prof"
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
                        _prep_path = output_dir / f"BRT_cProfile_pending_sheet_prep_{sym}_{ts}.prof"
                    if _prep_path.suffix.lower() not in (".prof", ".pstats"):
                        _prep_path = _prep_path.with_suffix(".prof")
                    _prep_path.parent.mkdir(parents=True, exist_ok=True)
                    _cprof_prep_obj.dump_stats(str(_prep_path))
                    print(f"[PROFILE] cProfile (bt_loop_pending_sheet_prep block only): {_prep_path.resolve()}")
                    print(f"[PROFILE]   python -m pstats {_prep_path}   # sort cumulative; stats 30")
                    print(f"[PROFILE]   snakeviz {_prep_path}")
            t_backtest = time.time() - _t
            all_closed.extend(closed)
            if getattr(args, "emit_would_have", False):
                all_would_have.extend(would_have)
            if open_trade:
                all_open.append(open_trade)
            all_scanner.extend(scanner)
            all_watchlist.extend(watchlist)
            all_short_candidates.extend(short_cands)
            if getattr(args, "ladder_mismatch_report", False) and args.symbol and sym.upper() == args.symbol.upper():
                try:
                    idx_parsed_m = pd.to_datetime(df.index, errors="coerce")
                    index_iso_m = pd.DatetimeIndex(idx_parsed_m).strftime("%Y%m%d").tolist()
                except Exception:
                    index_iso_m = [
                        (df.index[i].strftime("%Y%m%d") if hasattr(df.index[i], "strftime") else str(df.index[i])[:10].replace("-", ""))
                        for i in range(len(df))
                    ]
                zl_f = level3["zone_low"].to_numpy(dtype=np.float64)
                zh_f = level3["zone_high"].to_numpy(dtype=np.float64)
                ha = df["High"].to_numpy(dtype=np.float64)
                la = df["Low"].to_numpy(dtype=np.float64)
                ca = df["Close"].to_numpy(dtype=np.float64)
                lb = int(getattr(run_cfg, "sheet_maturity_lag_bars", 7))
                nr_cfg = int(getattr(run_cfg, "sheet_zone_ladder_rungs", 0))
                nr = max(1, int(getattr(run_cfg, "lookback_long", 504)) if nr_cfg <= 0 else nr_cfg)
                ladder_m = _compute_sheet_ladder_de_df_dg(ha, la, ca, zl_f, zh_f, lb, n_rungs=nr)
                nmiss, ntot, lrows = report_trades_vs_sheet_ladder_rungs(sym, closed, index_iso_m, ladder_m, run_cfg.band_pct)
                lp = output_dir / f"BRT_LadderMismatch_{sym}_{ts}.csv"
                write_ladder_mismatch_csv(lp, lrows)
                print(
                    f"[BRT] 8-rung ladder vs trades: {nmiss}/{ntot} closed trades NOT on any ladder rung "
                    f"at signal bar (close_above_date). Report: {lp}"
                )
            _t = time.time()
            all_pivot_rows.extend(collect_brt_pivots(sym, df, pivot_high, pivot_low, ph_price, pl_price, struct))
            t_collect_pivots = time.time() - _t
            if args.profile:
                _row = {
                    "symbol": sym,
                    "bars": int(len(df)),
                    "t_load": 0.0,  # already loaded in parent path
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

            if getattr(args, "print_zones", False) and args.symbol and sym == args.symbol.upper():
                _write_zone_debug_files(sym, df, level3, zone_entries_debug, run_cfg.band_pct, str(output_dir), ts)

            if (
                getattr(args, "emit_sheet_parity", False)
                and args.symbol
                and sym == args.symbol.upper()
                and sheet_ladder_sink
            ):
                sp_path = output_dir / f"BRT_SheetParity_{sym}_{ts}.csv"
                write_sheet_parity_csv(sp_path, sym, df, sheet_ladder_sink.get("index_iso", []), sheet_ladder_sink)
                print(f"[BRT] Sheet parity trace: {sp_path}")

            if n_total > 1:
                _print_symbol_progress(idx, n_total, progress_t0)
        if n_total > 1:
            print()

        if args.profile and profile_beta_times:
            print(f"[PROFILE] beta_at_entry (total {len(profile_beta_times)} calls): {sum(profile_beta_times):.2f}s")

    # After one pass: if z-score filter is on, compute ref stats from all trades and keep only those passing threshold
    if need_post_filter and (all_closed or all_open):
        ref_stats = _compute_reference_stats_from_trades(all_closed, all_open)
        threshold = getattr(cfg, "realtime_filter_threshold", 0.0)
        n_before_closed, n_before_open = len(all_closed), len(all_open)
        all_closed = [t for t in all_closed if _realtime_score_for_trade(t, cfg, ref_stats) >= threshold]
        all_open = [t for t in all_open if _realtime_score_for_trade(t, cfg, ref_stats) >= threshold]
        print(f"[BRT] Z-score: kept {len(all_closed)}/{n_before_closed} closed, {len(all_open)}/{n_before_open} open (threshold={threshold})")
        if args.debug_signals and args.symbol:
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

        if args.symbol and sym == args.symbol.upper() and HAS_MATPLOTLIB:
            chart_path = output_dir / f"BRT_Chart_{sym}_{ts}.png"
            open_for_sym = [t for t in all_open if t.symbol == sym]
            plot_brt_bands(sym, df, level3, closed, str(chart_path), band_pct=cfg.band_pct, open_trades=open_for_sym)
            print(f"Chart saved: {chart_path}")

    elapsed = time.time() - t0
    per_sym = elapsed / n_total if n_total > 0 else 0
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Backtest complete in {elapsed:.1f}s" +
          (f" ({per_sym:.2f}s/symbol)" if n_total > 1 else ""))
    if args.profile:
        print(f"[PROFILE] backtest_loop: {elapsed:.2f}s")
        if profile_symbol_rows:
            prof_sym_path = output_dir / f"BRT_Profile_Symbols_{ts}.csv"
            _df_sym = pd.DataFrame(profile_symbol_rows).sort_values("t_total", ascending=False)
            _df_sym.to_csv(prof_sym_path, index=False)
            print(f"[PROFILE] symbols_timing: {prof_sym_path.name} ({len(profile_symbol_rows)} rows)")
            _bt_cols = [c for c in _df_sym.columns if c.startswith("bt_")]
            if _bt_cols:
                _means = _df_sym[_bt_cols].mean()
                _parts = [f"{c}={float(_means[c]):.4f}" for c in sorted(_bt_cols)]
                _max_parts = 20
                print(f"[PROFILE] run_brt_backtest sections (mean s/symbol): " + "; ".join(_parts[:_max_parts]) + (" ..." if len(_parts) > _max_parts else ""))
        if profile_block_rows:
            prof_block_path = output_dir / f"BRT_Profile_BlockReasons_{ts}.csv"
            df_block = pd.DataFrame(profile_block_rows)
            # Aggregate per reason and per symbol-reason for both quick triage and drilldown
            by_reason = (
                df_block.groupby("reason", as_index=False)["count"].sum()
                .sort_values("count", ascending=False)
                .rename(columns={"count": "total_count"})
            )
            by_symbol_reason = df_block.groupby(["symbol", "reason"], as_index=False)["count"].sum().sort_values("count", ascending=False)
            by_reason.to_csv(prof_block_path, index=False)
            by_symbol_reason.to_csv(output_dir / f"BRT_Profile_BlockReasons_BySymbol_{ts}.csv", index=False)
            top_parts: list[str] = []
            for _, row in by_reason.head(6).iterrows():
                top_parts.append(f"{row['reason']}={int(row['total_count'])}")
            top = ", ".join(top_parts)
            print(f"[PROFILE] block_reasons: {prof_block_path.name} ({len(by_reason)} reasons) | top: {top}")
        print("[PROFILE] --- Post-processing ---")

    _t_yf = time.time()
    _enrich_trades_yfinance(all_closed, all_open)
    if args.profile and (all_closed or all_open):
        print(f"[PROFILE] yfinance enrich: {time.time() - _t_yf:.2f}s")
    # Min market cap filter (applied after enrichment; 0 = no op)
    if getattr(cfg, "min_market_cap", 0) > 0:
        all_closed = [t for t in all_closed if getattr(t, "market_cap", None) is not None and t.market_cap >= cfg.min_market_cap]
        all_open = [t for t in all_open if getattr(t, "market_cap", None) is not None and t.market_cap >= cfg.min_market_cap]
    # Match BRT_Report/BRT_Audit: brt_cash = 1M/max_positions; scale PNL_DOLLARS everywhere before writing CSVs
    if all_closed:
        adj_cash, pnl_scale = _apply_report_dollar_scale_to_trades(all_closed, all_open, cfg)
        if abs(pnl_scale - 1.0) >= 1e-12:
            mp = max(_max_concurrent_positions(all_closed), 1)
            print(
                f"[BRT] Dollar scale (report notional): PNL_DOLLARS × {pnl_scale:.6g}; "
                f"brt_cash -> {adj_cash:,.0f} ($1M / Max_Positions={mp})"
            )
    _t_write_start = time.time()
    closed_path = str(output_dir / f"BRT_Closed_{ts}.csv")
    write_brt_closed(all_closed, closed_path, reference_stats=ref_stats, cfg=cfg)
    if args.profile:
        print(f"[PROFILE] write_brt_closed: {time.time() - _t_write_start:.2f}s ({len(all_closed)} trades)")
    if getattr(args, "emit_would_have", False) and all_would_have:
        would_have_path = str(output_dir / f"BRT_WouldHave_{ts}.csv")
        _write_would_have_csv(all_would_have, would_have_path)
        print(f"[FILE] Would-have entries: {would_have_path} ({len(all_would_have)} rows)")
    _t_corr = time.time()
    try:
        _sa = Path(__file__).resolve().parent
        if str(_sa) not in sys.path:
            sys.path.insert(0, str(_sa))
        from correlate_brt_closed import run_correlation_report
        run_correlation_report(closed_path, str(output_dir / f"BRT_Correlation_{ts}.csv"))
        if args.profile:
            print(f"[PROFILE] correlation_report: {time.time() - _t_corr:.2f}s")
        print(f"Correlation report: BRT_Correlation_{ts}.csv")
    except Exception as e:
        if args.profile:
            print(f"[PROFILE] correlation_report: {time.time() - _t_corr:.2f}s (failed)")
        print(f"[BRT] Correlation report skipped: {e}")
    _t_wo = time.time()
    write_brt_open(all_open, str(output_dir / f"BRT_Open_{ts}.csv"), tickers=tickers, brt_cash=cfg.brt_cash, closed=all_closed)
    if args.profile:
        print(f"[PROFILE] write_brt_open: {time.time() - _t_wo:.2f}s")
    write_brt_scanner(all_scanner, str(output_dir / f"BRT_Scanner_{ts}.csv"))
    _wl_path = str(output_dir / f"BRT_Watchlist_{ts}.csv")
    write_brt_watchlist(all_watchlist, _wl_path)
    print(f"[FILE] Watchlist: {_wl_path} ({len(all_watchlist)} rows)")
    write_brt_short_candidates(all_short_candidates, str(output_dir / f"BRT_ShortCandidates_{ts}.csv"))
    write_brt_summary(all_closed, str(output_dir / f"BRT_Summary_{ts}.csv"))
    write_brt_industry_summary(all_closed, str(output_dir / f"BRT_INDUSTRY_{ts}.csv"))
    if all_pivot_rows:
        write_brt_pivots(all_pivot_rows, str(output_dir / f"BRT_Pivots_{ts}.csv"))

    metrics = compute_metrics(all_closed, cfg)
    if cfg.compute_equity_metrics and HAS_EQUITY_METRICS and all_closed and tickers and _compute_equity_metrics:
        try:
            _t_eq = time.time()
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
            )
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
            _write_brt_equity_canonical_outputs(output_dir, ts, equity)
        except Exception as e:
            print(f"[WARN] Equity metrics failed: {e}", file=sys.stderr)
    write_brt_report(cfg, metrics, str(output_dir), ts, args.drive_link)
    write_brt_audit_report(cfg, metrics, str(output_dir), ts, args.drive_link)
    if args.profile:
        print(f"[PROFILE] write_all_outputs: {time.time() - _t_write_start:.2f}s (closed+correlation+open+scanner+summary+report)")

    print(f"[{datetime.now().strftime('%H:%M:%S')}] BRT outputs written to {output_dir} (ts={ts})")

    # Run regression check (same pattern as run_audit.ps1 for RocketLauncher)
    if not args.symbol and not args.no_regression:
        for folder in ("Drive", "drive"):
            regress_script = repo_root / folder / "BRTRegressionCheck.ps1"
            if regress_script.exists():
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Running BRT regression check...")
                _t_regress = time.time()
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
                break
        else:
            print("[WARN] BRTRegressionCheck.ps1 not found in Drive/; skipping regression check.", file=sys.stderr)

    _maybe_play_completion_sound(args.play_sound)
    return 0


if __name__ == "__main__":
    sys.exit(main())
